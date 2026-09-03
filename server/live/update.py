"""Self-update from our validated GitHub releases.

A release publishes ``update-manifest.json`` plus ``corpus.sqlite`` and ``pob-engine.zip``
(a golden-test-gated PoB snapshot). Compatible engine updates install as one source-tree + bridge
pair; an older user-data engine never shadows only part of the bundled runtime. Per project policy,
the engine only ever updates from these pre-tested releases — never live upstream.
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
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any

from .. import paths
from ..knowledge import db

MANIFEST_URL = os.environ.get(
    "POE2_MCP_MANIFEST_URL",
    "https://github.com/avdergh/poe2-exile-architect/releases/latest/download/update-manifest.json",
)
# Where to grab a newer .mcpb for tool/code changes (data updates apply automatically; new
# tools require reinstalling the bundle, which Claude Desktop has no native auto-updater for).
RELEASES_PAGE = "https://github.com/avdergh/poe2-exile-architect/releases/latest"
CHECK_INTERVAL_SECONDS = 24 * 3600
UA = {"User-Agent": "poe2-build-mcp-updater/0.1"}


def _vkey(version: str) -> tuple[int, ...]:
    """Numeric version key so v0.10.0 > v0.2.0 (lexicographic compare would get this wrong)."""
    return tuple(int(n) for n in re.findall(r"\d+", version or "")) or (0,)


def _http(url: str, timeout: float = 60.0) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _bundle_version() -> str:
    """Return the bundled data/corpus release stamp."""

    f = paths.BUNDLE_ROOT / "data" / "VERSION"
    return f.read_text().strip() if f.exists() else "0"


def _bundle_app_version() -> str:
    """Return the MCP application version used by engine compatibility checks."""

    return paths.bundle_app_version()


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
    app_latest = str(manifest.get("app_version") or "0")
    app_current = _bundle_app_version()
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


def apply_updates(
    force: bool = False,
    *,
    install_context: Callable[[bool], AbstractContextManager[Any]] | None = None,
    validate_engine: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
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
    prev = installed_meta()
    corpus = manifest.get("corpus") or {}
    engine = manifest.get("engine") or {}
    engine_sha = engine.get("sha256")
    replace_engine = bool(engine.get("url") and (force or engine_sha != prev.get("engine_sha256")))
    manifest_app_version = manifest.get("app_version")
    app_version = manifest_app_version or prev.get("app_version") or _bundle_app_version()
    engine_contract = manifest.get("engine_contract")
    if replace_engine and engine_contract != paths.POB_RUNTIME_CONTRACT:
        return {"updated": False, "error": "engine runtime contract missing or incompatible"}
    if replace_engine and not manifest_app_version:
        return {"updated": False, "error": "engine app version missing"}
    metadata = {
        "version": latest,
        "app_version": app_version,
        "engine_app_version": (
            app_version
            if replace_engine
            else prev.get("engine_app_version") or prev.get("app_version")
        ),
        "engine_contract": (
            engine_contract if replace_engine else prev.get("engine_contract")
        ),
        "pob_commit": manifest.get("pob_commit") or prev.get("pob_commit"),
        "pob_version": manifest.get("pob_version") or prev.get("pob_version"),
        # Data-only refreshes must preserve the compatibility claims certified with the unchanged
        # engine. Missing fields in a refreshed manifest cannot revoke an installed claim.
        "game_patch": manifest.get("game_patch") or prev.get("game_patch"),
        "passive_tree": manifest.get("passive_tree") or prev.get("passive_tree"),
        "engine_sha256": engine_sha or prev.get("engine_sha256"),
    }

    try:
        with tempfile.TemporaryDirectory(
            dir=data_dir,
            prefix=".update-stage-",
            ignore_cleanup_errors=True,
        ) as td:
            stage = Path(td)
            replacements: list[tuple[Path, Path]] = []
            if corpus.get("url"):
                blob = _http(corpus["url"])
                if not _verify(blob, corpus.get("sha256")):
                    return {"updated": False, "error": "corpus checksum missing or mismatched"}
                staged_corpus = stage / "corpus.sqlite"
                staged_corpus.write_bytes(blob)
                replacements.append((staged_corpus, data_dir / "corpus.sqlite"))

            if replace_engine:
                blob = _http(engine["url"])
                if not _verify(blob, engine_sha):
                    return {"updated": False, "error": "engine checksum missing or mismatched"}
                zpath = stage / "engine.zip"
                zpath.write_bytes(blob)
                extract = stage / "engine-extract"
                with zipfile.ZipFile(zpath) as zf:
                    _safe_extract(zf, extract)
                staged_pob = extract / "pob"
                if not staged_pob.is_dir():
                    return {"updated": False, "error": "engine archive missing pob directory"}
                if validate_engine is not None:
                    try:
                        validate_engine(staged_pob)
                    except Exception as exc:  # noqa: BLE001 - reject before any runtime mutation.
                        return {
                            "updated": False,
                            "error": f"staged engine validation failed: {type(exc).__name__}",
                        }
                replacements.append((staged_pob, data_dir / "pob"))

            staged_metadata = stage / "installed.json"
            staged_metadata.write_text(json.dumps(metadata), encoding="utf-8")
            replacements.append((staged_metadata, data_dir / "installed.json"))

            context = (
                install_context(replace_engine) if install_context is not None else nullcontext()
            )
            with context:
                if corpus.get("url"):
                    db.reset()
                _install_replacements(replacements, stage / "backups")
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        return {"updated": False, "error": f"update installation failed: {type(exc).__name__}"}
    return {"updated": True, "version": latest}


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != root and root not in target.parents:
            raise ValueError("engine archive contains an unsafe path")
    archive.extractall(destination)


def _install_replacements(replacements: list[tuple[Path, Path]], backup_root: Path) -> None:
    backup_root.mkdir()
    installed: list[tuple[Path, Path | None]] = []
    try:
        for index, (staged, target) in enumerate(replacements):
            backup = backup_root / f"{index}-{target.name}"
            previous = backup if target.exists() else None
            if previous is not None:
                os.replace(target, previous)
            try:
                os.replace(staged, target)
            except BaseException:
                if previous is not None:
                    os.replace(previous, target)
                raise
            installed.append((target, previous))
    except BaseException:
        for target, previous in reversed(installed):
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
            if previous is not None:
                os.replace(previous, target)
        raise


def auto_update(
    install_context: Callable[[bool], AbstractContextManager[Any]] | None = None,
    validate_engine: Callable[[Path], None] | None = None,
) -> None:
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
            apply_updates(install_context=install_context, validate_engine=validate_engine)
    except Exception:  # noqa: BLE001 - auto-update must never break the server
        pass
