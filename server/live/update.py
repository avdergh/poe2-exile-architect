"""Self-update from our validated GitHub releases.

A release publishes ``update-manifest.json`` plus ``corpus.sqlite`` and ``pob-engine.zip``
(a golden-test-gated PoB snapshot). Updates install into the user-data dir, which is preferred
over the bundled seed (see paths.py). Per project policy, the engine only ever updates from
these pre-tested releases — never live upstream.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import paths
from ..knowledge import db

MANIFEST_URL = os.environ.get(
    "POE2_MCP_MANIFEST_URL",
    "https://github.com/Egonex-AI/poe-bd-creator/releases/latest/download/update-manifest.json",
)
# Where to grab a newer .mcpb for tool/code changes (data updates apply automatically; new
# tools require reinstalling the bundle, which Claude Desktop has no native auto-updater for).
RELEASES_PAGE = "https://github.com/Egonex-AI/poe-bd-creator/releases/latest"
CHECK_INTERVAL_SECONDS = 24 * 3600
UA = {"User-Agent": "poe2-build-mcp-updater/0.1"}


def _vkey(version: str) -> tuple[int, ...]:
    """Numeric version key so v0.10.0 > v0.2.0 (lexicographic compare would get this wrong)."""
    return tuple(int(n) for n in re.findall(r"\d+", version or "")) or (0,)


def _http(url: str, timeout: float = 60.0) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _bundle_version() -> str:
    f = paths.BUNDLE_ROOT / "data" / "VERSION"
    return f.read_text().strip() if f.exists() else "0"


def installed_meta() -> dict:
    f = paths.user_data_dir() / "installed.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def installed_version() -> str:
    """The installed DATA version (corpus/engine payload), falling back to the bundle stamp."""
    return installed_meta().get("version") or _bundle_version()


def _fetch_manifest() -> dict | None:
    try:
        return json.loads(_http(MANIFEST_URL, timeout=15))
    except Exception:  # noqa: BLE001
        return None


def check_for_updates() -> dict[str, Any]:
    """Is a newer validated release (engine + corpus) available?"""
    current = installed_version()
    manifest = _fetch_manifest()
    if not manifest:
        return {
            "available": False,
            "current_version": current,
            "reason": "no release manifest reachable (no published release yet?)",
        }
    latest = str(manifest.get("version", "0"))
    # app_version is the .mcpb/code version, decoupled from the data version so a data-only
    # refresh (same app_version, bumped version) doesn't masquerade as a new bundle to install.
    app_latest = str(manifest.get("app_version") or latest)
    app_current = _bundle_version()
    return {
        # data (corpus/engine) update — applies automatically via apply_updates/auto_update
        "available": _vkey(latest) > _vkey(current),
        "current_version": current,
        "latest_version": latest,
        # new tools/code need a fresh .mcpb (no auto-installer); only true on real app releases
        "mcpb_update_available": _vkey(app_latest) > _vkey(app_current),
        "app_version_installed": app_current,
        "app_version_latest": app_latest,
        "pob_commit": manifest.get("pob_commit"),
        "download_page": RELEASES_PAGE,
    }


def _verify(blob: bytes, sha: str | None) -> bool:
    # Refuse to "verify" when no checksum is published — an unverifiable blob must NOT install.
    return bool(sha) and hashlib.sha256(blob).hexdigest() == sha


def apply_updates(force: bool = False) -> dict[str, Any]:
    """Download + install the latest validated release into the user-data dir."""
    manifest = _fetch_manifest()
    if not manifest:
        return {"updated": False, "reason": "no release manifest reachable"}
    latest = str(manifest.get("version", "0"))
    current = installed_version()
    if not force and _vkey(latest) <= _vkey(current):
        return {"updated": False, "reason": "already up to date", "version": current}

    data_dir = paths.user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    corpus = manifest.get("corpus") or {}
    if corpus.get("url"):
        blob = _http(corpus["url"])
        if not _verify(blob, corpus.get("sha256")):
            return {"updated": False, "error": "corpus checksum missing or mismatched"}
        db.reset()  # release the read handle before replacing the file
        tmp = data_dir / "corpus.sqlite.tmp"
        tmp.write_bytes(blob)
        os.replace(tmp, data_dir / "corpus.sqlite")

    prev = installed_meta()
    engine = manifest.get("engine") or {}
    engine_sha = engine.get("sha256")
    # Skip the engine download on data-only refreshes — its sha is unchanged from what's installed
    # (the engine only moves on a real PoB bump / app release), so there's nothing new to fetch.
    if engine.get("url") and (force or engine_sha != prev.get("engine_sha256")):
        blob = _http(engine["url"])
        if not _verify(blob, engine_sha):
            return {"updated": False, "error": "engine checksum missing or mismatched"}
        with tempfile.TemporaryDirectory() as td:
            zpath = Path(td) / "engine.zip"
            zpath.write_bytes(blob)
            extract = Path(td) / "x"
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(extract)
            src_pob = extract / "pob"
            dst_pob = data_dir / "pob"
            if src_pob.is_dir():
                if dst_pob.exists():
                    shutil.rmtree(dst_pob)
                shutil.move(str(src_pob), str(dst_pob))

    (data_dir / "installed.json").write_text(
        json.dumps(
            {
                "version": latest,
                "app_version": manifest.get("app_version") or latest,
                "pob_commit": manifest.get("pob_commit"),
                # Freshness providers deliberately refuse to infer game compatibility from
                # release names. Persist the certified claims published by update-manifest.json.
                "game_patch": manifest.get("game_patch"),
                "passive_tree": manifest.get("passive_tree"),
                "engine_sha256": engine_sha or prev.get("engine_sha256"),
            }
        )
    )
    return {"updated": True, "version": latest}


def auto_update(on_applied: Callable[[], None] | None = None) -> None:
    """Throttled, best-effort startup update. Safe to run in a daemon thread."""
    if os.environ.get("POE2_MCP_NO_AUTOUPDATE"):
        return
    try:
        marker = paths.user_data_dir() / "last_check"
        now = time.time()
        if marker.exists():
            try:
                if now - float(marker.read_text().strip()) < CHECK_INTERVAL_SECONDS:
                    return
            except Exception:  # noqa: BLE001
                pass
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(now))
        if check_for_updates().get("available"):
            res = apply_updates()
            if res.get("updated") and on_applied:
                on_applied()
    except Exception:  # noqa: BLE001 - auto-update must never break the server
        pass
