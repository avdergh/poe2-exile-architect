from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import threading
import subprocess
import sys

import pytest

from server import paths
from server.freshness import providers
from server.knowledge import corpus_certification as certificates, db
from server.live import update


def corpus_bytes(path, stamp):
    stamp = {"old": "2026-09-01T00:00:00Z", "new": "2026-09-05T00:00:00Z"}.get(stamp, stamp)
    with closing(sqlite3.connect(path)) as con:
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        con.executemany(
            "INSERT INTO meta VALUES (?,?)", [("schema_version", "4"), ("built_at", stamp)]
        )
        con.commit()
    return path.read_bytes()


def certificate(blob, patch="0.5.4"):
    return {
        "schemaVersion": 1,
        "sha256": hashlib.sha256(blob).hexdigest(),
        "game_patch": patch,
        "passive_tree": "0_5",
    }


@pytest.fixture
def setup_corpus(tmp_path, monkeypatch):
    user = tmp_path / "user"
    bundle = tmp_path / "bundle"
    user.mkdir()
    (bundle / "data" / "compatibility").mkdir(parents=True)
    old = corpus_bytes(bundle / "data" / "corpus.sqlite", "old")
    (bundle / "data" / "compatibility" / "corpus.json").write_text(json.dumps(certificate(old)))
    monkeypatch.setattr(paths, "BUNDLE_ROOT", bundle)
    monkeypatch.setattr(paths, "user_data_dir", lambda: user)
    monkeypatch.setattr(update, "_bundle_version", lambda: "1")
    monkeypatch.setattr(update, "_bundle_app_version", lambda: "1")
    db.reset()
    yield user, old
    db.reset()


def install(monkeypatch, blob, *, version="2", cert=True):
    corpus = {"url": "memory:corpus", "sha256": hashlib.sha256(blob).hexdigest()}
    if cert is not False:
        corpus["certificate"] = certificate(blob) if cert is True else cert
    manifest = {"version": version, "app_version": "1", "corpus": corpus}
    monkeypatch.setattr(update, "_fetch_manifest", lambda: manifest)
    monkeypatch.setattr(update, "_http", lambda *args, **kwargs: blob)
    return manifest


def corpus_evidence():
    rows = providers.collect_local_evidence(datetime.now(timezone.utc))
    return next(row for row in rows if row.source == "validated-release-corpus")


def test_data_update_installs_independent_certificate_and_keeps_current(
    setup_corpus, tmp_path, monkeypatch
):
    user, _ = setup_corpus
    blob = corpus_bytes(tmp_path / "new.sqlite", "new")
    install(monkeypatch, blob)
    assert update.apply_updates()["updated"] is True
    evidence = corpus_evidence()
    assert evidence.status.value == "current"
    assert {claim.key.value: claim.value for claim in evidence.claims} == {
        "game_patch": "0.5.4",
        "passive_tree": "0_5",
    }
    assert (user / certificates.CERTIFICATE_FILENAME).is_file()
    assert db.corpus_info()["built_at"] == "2026-09-05T00:00:00Z"


@pytest.mark.parametrize("bad", ["missing", "wrong_hash", "missing_patch"])
def test_bad_certificate_rejects_before_replacing_data(setup_corpus, tmp_path, monkeypatch, bad):
    user, old = setup_corpus
    blob = corpus_bytes(tmp_path / "new.sqlite", "new")
    cert = certificate(blob)
    if bad == "wrong_hash":
        cert["sha256"] = "0" * 64
    if bad == "missing_patch":
        cert.pop("game_patch")
    install(monkeypatch, blob, cert=False if bad == "missing" else cert)
    result = update.apply_updates()
    assert result["updated"] is False and "certificate" in result["error"]
    assert not (user / "installed.json").exists()
    assert paths.corpus_path().read_bytes() == old


def test_legacy_manifest_can_only_reuse_a_hash_matching_certificate(setup_corpus, monkeypatch):
    _, old = setup_corpus
    install(monkeypatch, old, cert=False)
    assert update.apply_updates()["updated"] is True
    assert corpus_evidence().status.value == "current"


def test_same_version_repairs_missing_certificate(setup_corpus, tmp_path, monkeypatch):
    user, _ = setup_corpus
    blob = corpus_bytes(tmp_path / "new.sqlite", "new")
    (user / "corpus.sqlite").write_bytes(blob)
    (user / "installed.json").write_text(json.dumps({"version": "2", "app_version": "1"}))
    assert certificates.active_certificate() is None
    install(monkeypatch, blob)
    assert update.check_for_updates()["available"] is True
    assert update.apply_updates()["updated"] is True
    assert corpus_evidence().status.value == "current"
    assert update.apply_updates()["reason"] == "already up to date"


def test_certificate_and_metadata_roll_back_with_corpus(setup_corpus, tmp_path, monkeypatch):
    user, old = setup_corpus
    install(monkeypatch, old)
    assert update.apply_updates()["updated"]
    names = ("corpus.sqlite", certificates.CERTIFICATE_FILENAME, "installed.json")
    before = {name: (user / name).read_bytes() for name in names}
    blob = corpus_bytes(tmp_path / "new.sqlite", "new")
    install(monkeypatch, blob, version="3")
    original = update.os.replace

    def fail(source, target):
        if target == user / "installed.json" and source.parent.name.startswith(".update-stage"):
            raise OSError("injected failure")
        original(source, target)

    monkeypatch.setattr(update.os, "replace", fail)
    assert update.apply_updates()["updated"] is False
    assert {name: (user / name).read_bytes() for name in names} == before
    assert corpus_evidence().status.value == "current"


def test_freshness_read_waits_for_complete_pair_replacement(setup_corpus, tmp_path, monkeypatch):
    user, _ = setup_corpus
    blob = corpus_bytes(tmp_path / "new.sqlite", "new")
    install(monkeypatch, blob)
    entered, release, reader_started = threading.Event(), threading.Event(), threading.Event()
    original = update.os.replace

    def paused(source, target):
        original(source, target)
        if target == user / "corpus.sqlite":
            entered.set()
            assert release.wait(10)

    def read():
        reader_started.set()
        return corpus_evidence()

    monkeypatch.setattr(update.os, "replace", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(update.apply_updates)
        assert entered.wait(10)
        reader = pool.submit(read)
        assert reader_started.wait(10)
        assert not reader.done()
        release.set()
        assert writer.result()["updated"] is True
        assert reader.result().status.value == "current"


def test_other_mcp_process_can_update_twice_and_reader_reloads_matching_snapshot(
    setup_corpus, tmp_path
):
    user, _ = setup_corpus
    assert db.corpus_info()["built_at"] == "2026-09-01T00:00:00Z"
    initial = db._conn()
    child = """
import json, sys
from pathlib import Path
from server import paths
from server.live import update
paths.BUNDLE_ROOT = Path(sys.argv[1])
paths.user_data_dir = lambda: Path(sys.argv[2])
update._bundle_version = lambda: "1"
update._bundle_app_version = lambda: "1"
manifest = json.loads(sys.argv[3])
update._fetch_manifest = lambda: manifest
update._http = lambda *a, **k: Path(sys.argv[4]).read_bytes()
result = update.apply_updates()
assert result["updated"], result
"""
    for version, stamp in (("2", "2026-09-05T00:00:00Z"), ("3", "2026-09-06T00:00:00Z")):
        source = tmp_path / f"corpus-{version}.sqlite"
        blob = corpus_bytes(source, stamp)
        manifest = {
            "version": version,
            "app_version": "1",
            "corpus": {
                "url": "memory:corpus",
                "sha256": hashlib.sha256(blob).hexdigest(),
                "certificate": certificate(blob, patch="0.5.5"),
            },
        }
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                child,
                str(paths.BUNDLE_ROOT),
                str(user),
                json.dumps(manifest),
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert db.corpus_info()["built_at"] == stamp
        evidence = corpus_evidence()
        assert evidence.version == stamp
        assert (
            next(claim.value for claim in evidence.claims if claim.key.value == "game_patch")
            == "0.5.5"
        )
    assert (
        initial.execute("SELECT value FROM meta WHERE key='built_at'").fetchone()[0]
        == "2026-09-01T00:00:00Z"
    )
    with pytest.raises(sqlite3.OperationalError):
        db._conn().execute("UPDATE meta SET value='unexpected mutation'")
