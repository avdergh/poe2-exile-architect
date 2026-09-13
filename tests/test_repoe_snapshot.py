import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from pipeline import repoe_snapshot

COMMIT = "a" * 40


def source(monkeypatch):
    requests = []

    def read(url):
        requests.append(url)
        if url == repoe_snapshot.HEAD_URL:
            return json.dumps({"sha": COMMIT}).encode()
        assert f"/{COMMIT}/" in url
        if url.endswith("exported-version.txt"):
            return b"4.5.5.2\n"
        return json.dumps({url.rsplit("/", 1)[-1]: {"value": "static"}}).encode()

    monkeypatch.setattr(repoe_snapshot, "_read_url", read)
    return requests, read


def test_fetch_freezes_head_once_and_binds_every_file(monkeypatch, tmp_path):
    requests, _ = source(monkeypatch)
    result = repoe_snapshot.fetch_snapshot(tmp_path)
    assert requests.count(repoe_snapshot.HEAD_URL) == 1
    assert all(f"/{COMMIT}/" in url for url in requests[1:])
    assert result["sourceCommit"] == COMMIT
    assert result["exportedVersion"] == "4.5.5.2"
    assert repoe_snapshot.verify_snapshot(tmp_path) == result


def test_failed_download_preserves_prior_export(monkeypatch, tmp_path):
    _, read = source(monkeypatch)
    repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    def failed(url):
        if url.endswith("mods.json"):
            raise OSError("interrupted download")
        if url.endswith("exported-version.txt"):
            return read(url)
        return b'{"different": {}}'

    monkeypatch.setattr(repoe_snapshot, "_read_url", failed)
    with pytest.raises(OSError):
        repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize("change", ["bytes", "commit", "url", "duplicate", "version", "schema"])
def test_mixed_or_relabelled_inputs_fail_verification(monkeypatch, tmp_path, change):
    source(monkeypatch)
    manifest = repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    if change == "bytes":
        (tmp_path / repoe_snapshot.SOURCE_FILES[0]).write_text('{"altered": {}}')
    elif change == "commit":
        manifest["sourceCommit"] = "b" * 40
    elif change == "url":
        manifest["files"][0]["sourceUrl"] = "https://repoe-fork.github.io/poe2/base_items.min.json"
    elif change == "duplicate":
        manifest["files"][1] = manifest["files"][0]
    elif change == "version":
        manifest["exportedVersion"] = "4.5.6.0"
    else:
        manifest["schemaVersion"] = 3
    (tmp_path / repoe_snapshot.MANIFEST_NAME).write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        repoe_snapshot.verify_snapshot(tmp_path)


@pytest.mark.parametrize("initial", ["v2", "legacy", "no_manifest"])
def test_interrupted_publication_cannot_authorize_mixed_files(monkeypatch, tmp_path, initial):
    _, read = source(monkeypatch)
    if initial == "v2":
        repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    else:
        for name in repoe_snapshot.SOURCE_FILES:
            (tmp_path / name).write_bytes(b'{"old": {}}')
        if initial == "legacy":
            (tmp_path / repoe_snapshot.MANIFEST_NAME).write_text(json.dumps({"exportedVersion": "4.5.4.11"}))
    monkeypatch.setattr(repoe_snapshot, "_read_url", lambda url: read(url) if url.endswith(".txt") else b'{"changed": {}}')
    replace = Path.replace

    def interrupted(path, target):
        if path.name == repoe_snapshot.SOURCE_FILES[1]:
            raise OSError("interrupted publication")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", interrupted)
    with pytest.raises(OSError):
        repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    with pytest.raises(ValueError, match="publication interrupted"):
        repoe_snapshot.verify_snapshot(tmp_path)
    monkeypatch.setattr(Path, "replace", replace)
    repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    assert repoe_snapshot.verify_snapshot(tmp_path)["sourceCommit"] == COMMIT


def test_builder_rejects_pending_export_before_replacing_corpus(monkeypatch, tmp_path):
    from pipeline import build_corpus

    database = tmp_path / "corpus.sqlite"
    database.write_bytes(b"previous reviewed corpus")
    (tmp_path / repoe_snapshot.PENDING_NAME).write_text("{}")
    monkeypatch.setattr(build_corpus, "RAW_DIR", tmp_path)
    monkeypatch.setattr(build_corpus, "DB_PATH", database)
    with pytest.raises(ValueError, match="publication interrupted"):
        build_corpus.build()
    assert database.read_bytes() == b"previous reviewed corpus"


def test_input_reader_holds_one_complete_snapshot_during_publication(monkeypatch, tmp_path):
    source(monkeypatch)
    repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    before = (tmp_path / repoe_snapshot.SOURCE_FILES[0]).read_bytes()
    downloaded = threading.Event()

    def replacement(url):
        if url.endswith(".txt"):
            return b"4.5.6.0\n"
        if url.endswith("mods.json"):
            downloaded.set()
        return b'{"new": {}}'

    monkeypatch.setattr(repoe_snapshot, "_read_url", replacement)
    with ThreadPoolExecutor(max_workers=1) as worker:
        with repoe_snapshot.snapshot_guard(tmp_path):
            future = worker.submit(repoe_snapshot.fetch_snapshot, tmp_path, commit="b" * 40)
            assert downloaded.wait(5)
            assert not future.done()
            assert (tmp_path / repoe_snapshot.SOURCE_FILES[0]).read_bytes() == before
            assert repoe_snapshot.verify_snapshot(tmp_path)["sourceCommit"] == COMMIT
        assert future.result(timeout=5)["sourceCommit"] == "b" * 40


def test_legacy_cache_does_not_gain_immutable_source_claims(tmp_path):
    (tmp_path / repoe_snapshot.MANIFEST_NAME).write_text(json.dumps({"exportedVersion": "4.5.5.2"}))
    assert repoe_snapshot.verify_snapshot(tmp_path) is None
