"""Self-update decoupling: data refreshes apply automatically and reuse the unchanged engine,
while the .mcpb ("new tools") nag stays tied to app_version. Mirrors the scheduled refresh flow.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile

from server import paths
from server.live import update


def test_default_update_source_matches_this_repository():
    assert "avdergh/poe2-exile-architect" in update.MANIFEST_URL
    assert "avdergh/poe2-exile-architect" in update.RELEASES_PAGE


def _engine_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pob/pob_headless.lua", "-- dummy engine")
    return buf.getvalue()


def _manifest(version: str, corpus_blob: bytes, engine_blob: bytes, app: str = "0.1.20") -> dict:
    return {
        "version": version,
        "app_version": app,
        "engine_contract": paths.POB_RUNTIME_CONTRACT,
        "pob_commit": "abc123",
        "game_patch": "0.5.3",
        "passive_tree": "0_5",
        "corpus": {
            "url": "http://x/corpus.sqlite",
            "sha256": hashlib.sha256(corpus_blob).hexdigest(),
            "certificate": {
                "schemaVersion": 1, "sha256": hashlib.sha256(corpus_blob).hexdigest(),
                "game_patch": "0.5.3", "passive_tree": "0_5",
            },
        },
        "engine": {"url": "http://x/engine.zip", "sha256": hashlib.sha256(engine_blob).hexdigest()},
    }


def test_data_refresh_reuses_unchanged_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(update, "_bundle_version", lambda: "0")
    engine = _engine_zip()
    corpus1, corpus2 = b"corpus-v1", b"corpus-v2"
    blobs = {"http://x/engine.zip": engine, "http://x/corpus.sqlite": corpus1}
    calls: list[str] = []

    def fake_http(url, timeout=60.0):
        calls.append(url)
        return blobs[url]

    monkeypatch.setattr(update, "_http", fake_http)

    # first install: both corpus and engine fetched
    monkeypatch.setattr(update, "_fetch_manifest", lambda: _manifest("0.1.20", corpus1, engine))
    r = update.apply_updates()
    assert r["updated"] and r["version"] == "0.1.20"
    assert any("engine.zip" in u for u in calls)
    assert any("corpus.sqlite" in u for u in calls)

    # data-only refresh: bumped data version, SAME engine sha -> corpus re-fetched, engine skipped
    calls.clear()
    blobs["http://x/corpus.sqlite"] = corpus2
    monkeypatch.setattr(update, "_fetch_manifest", lambda: _manifest("0.1.20.5", corpus2, engine))
    r = update.apply_updates()
    assert r["updated"] and r["version"] == "0.1.20.5"
    assert any("corpus.sqlite" in u for u in calls)
    assert not any("engine.zip" in u for u in calls)  # unchanged engine not re-downloaded


def test_apply_updates_persists_certified_freshness_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(update, "_bundle_version", lambda: "0")
    engine = _engine_zip()
    corpus = b"corpus"
    blobs = {"http://x/engine.zip": engine, "http://x/corpus.sqlite": corpus}

    monkeypatch.setattr(update, "_http", lambda url, timeout=60.0: blobs[url])
    monkeypatch.setattr(update, "_fetch_manifest", lambda: _manifest("0.1.20", corpus, engine))

    r = update.apply_updates()

    assert r["updated"] is True
    installed = json.loads((tmp_path / "installed.json").read_text())
    assert installed["pob_commit"] == "abc123"
    assert installed["game_patch"] == "0.5.3"
    assert installed["passive_tree"] == "0_5"
    assert installed["engine_app_version"] == "0.1.20"
    assert installed["engine_contract"] == paths.POB_RUNTIME_CONTRACT


def test_failed_engine_validation_keeps_previous_corpus_and_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(update, "_bundle_version", lambda: "0")
    old_corpus = b"old-corpus"
    new_corpus = b"new-corpus"
    bad_engine = b"bad-engine"
    (tmp_path / "corpus.sqlite").write_bytes(old_corpus)
    previous = {
        "version": "0.1.19",
        "pob_commit": "old-commit",
        "game_patch": "0.5.3",
        "passive_tree": "0_5",
        "engine_sha256": "old-engine",
    }
    (tmp_path / "installed.json").write_text(json.dumps(previous), encoding="utf-8")
    manifest = _manifest("0.1.20", new_corpus, bad_engine)
    manifest["engine"]["sha256"] = "0" * 64
    monkeypatch.setattr(update, "_fetch_manifest", lambda: manifest)
    monkeypatch.setattr(
        update,
        "_http",
        lambda url, timeout=60.0: new_corpus if "corpus" in url else bad_engine,
    )
    result = update.apply_updates()

    assert result == {"updated": False, "error": "engine checksum missing or mismatched"}
    assert (tmp_path / "corpus.sqlite").read_bytes() == old_corpus
    assert json.loads((tmp_path / "installed.json").read_text(encoding="utf-8")) == previous


def test_data_only_refresh_preserves_certified_compatibility_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(update, "_bundle_version", lambda: "0.1.20")
    monkeypatch.setattr(update, "_bundle_app_version", lambda: "0.1.20")
    engine = _engine_zip()
    corpus = b"new-corpus"
    previous = {
        "version": "0.1.20",
        "app_version": "0.1.20",
        "pob_commit": "abc123",
        "pob_version": "0.22.0",
        "game_patch": "0.5.4",
        "passive_tree": "0_5",
        "engine_sha256": hashlib.sha256(engine).hexdigest(),
        "engine_app_version": "0.1.20",
        "engine_contract": paths.POB_RUNTIME_CONTRACT,
    }
    (tmp_path / "installed.json").write_text(json.dumps(previous), encoding="utf-8")
    manifest = _manifest("0.1.20.1", corpus, engine)
    for key in ("game_patch", "passive_tree"):
        manifest.pop(key)
    monkeypatch.setattr(update, "_fetch_manifest", lambda: manifest)
    monkeypatch.setattr(update, "_http", lambda url, timeout=60.0: corpus)

    result = update.apply_updates()

    assert result["updated"] is True
    installed = json.loads((tmp_path / "installed.json").read_text(encoding="utf-8"))
    assert installed["game_patch"] == "0.5.4"
    assert installed["passive_tree"] == "0_5"
    assert installed["pob_version"] == "0.22.0"
    assert installed["engine_app_version"] == "0.1.20"
    assert installed["engine_contract"] == paths.POB_RUNTIME_CONTRACT


def test_engine_update_rejects_missing_runtime_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(update, "_bundle_version", lambda: "0")
    engine = _engine_zip()
    corpus = b"corpus"
    manifest = _manifest("0.1.20", corpus, engine)
    manifest.pop("engine_contract")
    monkeypatch.setattr(update, "_fetch_manifest", lambda: manifest)

    result = update.apply_updates()

    assert result == {
        "updated": False,
        "error": "engine runtime contract missing or incompatible",
    }
    assert not (tmp_path / "pob").exists()


def test_install_failure_rolls_back_every_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(update, "_bundle_version", lambda: "0")
    old_corpus = b"old-corpus"
    new_corpus = b"new-corpus"
    engine = _engine_zip()
    (tmp_path / "corpus.sqlite").write_bytes(old_corpus)
    previous = {
        "version": "0.1.19",
        "pob_commit": "old-commit",
        "game_patch": "0.5.3",
        "passive_tree": "0_5",
        "engine_sha256": "old-engine",
    }
    (tmp_path / "installed.json").write_text(json.dumps(previous), encoding="utf-8")
    old_pob = tmp_path / "pob"
    old_pob.mkdir()
    (old_pob / "marker.txt").write_text("old-engine", encoding="utf-8")
    manifest = _manifest("0.1.20", new_corpus, engine)
    monkeypatch.setattr(update, "_fetch_manifest", lambda: manifest)
    monkeypatch.setattr(
        update,
        "_http",
        lambda url, timeout=60.0: new_corpus if "corpus" in url else engine,
    )
    real_replace = update.os.replace

    def fail_engine_install(source, target):
        if Path(target) == tmp_path / "pob" and "engine-extract" in str(source):
            raise OSError("simulated engine install failure")
        return real_replace(source, target)

    monkeypatch.setattr(update.os, "replace", fail_engine_install)

    result = update.apply_updates()

    assert result["updated"] is False
    assert (tmp_path / "corpus.sqlite").read_bytes() == old_corpus
    assert json.loads((tmp_path / "installed.json").read_text(encoding="utf-8")) == previous
    assert (tmp_path / "pob" / "marker.txt").read_text(encoding="utf-8") == "old-engine"


def test_staged_engine_validation_runs_before_install_context(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(update, "_bundle_version", lambda: "0")
    corpus = b"new-corpus"
    engine = _engine_zip()
    manifest = _manifest("0.1.20", corpus, engine)
    monkeypatch.setattr(update, "_fetch_manifest", lambda: manifest)
    monkeypatch.setattr(
        update,
        "_http",
        lambda url, timeout=60.0: corpus if "corpus" in url else engine,
    )
    events: list[str] = []

    class InstallContext:
        def __enter__(self):
            events.append("install-enter")

        def __exit__(self, *exc):
            events.append("install-exit")

    def validate(staged_pob: Path):
        assert (staged_pob / "pob_headless.lua").is_file()
        events.append("validated")

    result = update.apply_updates(
        validate_engine=validate,
        install_context=lambda replace_engine: InstallContext(),
    )

    assert result["updated"] is True
    assert events == ["validated", "install-enter", "install-exit"]


def test_staged_engine_validation_failure_does_not_enter_install_context(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(update, "_bundle_version", lambda: "0")
    corpus = b"new-corpus"
    engine = _engine_zip()
    manifest = _manifest("0.1.20", corpus, engine)
    monkeypatch.setattr(update, "_fetch_manifest", lambda: manifest)
    monkeypatch.setattr(
        update,
        "_http",
        lambda url, timeout=60.0: corpus if "corpus" in url else engine,
    )
    entered: list[bool] = []

    result = update.apply_updates(
        validate_engine=lambda _path: (_ for _ in ()).throw(RuntimeError("bad staged runtime")),
        install_context=lambda replace_engine: entered.append(replace_engine),
    )

    assert result == {"updated": False, "error": "staged engine validation failed: RuntimeError"}
    assert entered == []
    assert not (tmp_path / "corpus.sqlite").exists()
    assert not (tmp_path / "installed.json").exists()


def test_check_for_updates_decouples_data_from_mcpb(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(update, "_bundle_version", lambda: "0.1.20")
    monkeypatch.setattr(update, "_bundle_app_version", lambda: "0.1.20")
    (tmp_path / "installed.json").write_text(
        json.dumps({"version": "0.1.20.5", "app_version": "0.1.20"})
    )
    # a newer DATA version, same app_version -> data update available, but no .mcpb nag
    monkeypatch.setattr(
        update, "_fetch_manifest", lambda: {"version": "0.1.20.6", "app_version": "0.1.20"}
    )
    r = update.check_for_updates()
    assert r["available"] is True
    assert r["mcpb_update_available"] is False

    # a real app release bumps app_version -> .mcpb nag fires
    monkeypatch.setattr(
        update, "_fetch_manifest", lambda: {"version": "0.1.21", "app_version": "0.1.21"}
    )
    r = update.check_for_updates()
    assert r["available"] is True
    assert r["mcpb_update_available"] is True
