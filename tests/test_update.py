"""Self-update decoupling: data refreshes apply automatically and reuse the unchanged engine,
while the .mcpb ("new tools") nag stays tied to app_version. Mirrors the scheduled refresh flow.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

from server import paths
from server.live import update


def test_default_update_source_matches_this_repository():
    assert "Egonex-AI/poe-bd-creator" in update.MANIFEST_URL
    assert "Egonex-AI/poe-bd-creator" in update.RELEASES_PAGE


def _engine_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pob/pob_headless.lua", "-- dummy engine")
    return buf.getvalue()


def _manifest(version: str, corpus_blob: bytes, engine_blob: bytes, app: str = "0.1.20") -> dict:
    return {
        "version": version,
        "app_version": app,
        "pob_commit": "abc123",
        "game_patch": "0.5.3",
        "passive_tree": "0_5",
        "corpus": {
            "url": "http://x/corpus.sqlite",
            "sha256": hashlib.sha256(corpus_blob).hexdigest(),
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


def test_check_for_updates_decouples_data_from_mcpb(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(update, "_bundle_version", lambda: "0.1.20")
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
