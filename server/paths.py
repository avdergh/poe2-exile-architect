"""Runtime path resolution.

The server ships a self-contained *seed* and can install validated updates into writable
user-data.  Data files may be selected independently, but the PoB source tree and its headless
bridge are one executable runtime and must always be selected as a pair.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

# Bundle/repo root (this file is <root>/server/paths.py).
BUNDLE_ROOT = Path(__file__).resolve().parents[1]

_PLATFORM_DIR = {"win32": "win-x64", "darwin": "mac-arm64", "linux": "linux-x64"}

# Bump this only when bundled Python requires a newer headless bridge contract.  Validated
# user-data engines advertise the same value in installed.json; an older or unlabelled engine is
# deliberately ignored instead of being mixed with the new Python runtime.
POB_RUNTIME_CONTRACT = 11


@dataclass(frozen=True)
class PobRuntimePair:
    """One indivisible PoB source-tree + headless-bridge selection."""

    root: Path
    src_dir: Path
    headless_script: Path
    source: str


def user_data_dir() -> Path:
    """Writable directory for auto-updated data (override with POE2_MCP_DATA)."""
    override = os.environ.get("POE2_MCP_DATA")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "poe2-build-mcp"


def _prefer(updated: Path, seed: Path, *, is_dir: bool = False) -> Path:
    ok = updated.is_dir() if is_dir else updated.exists()
    return updated if ok else seed


def _version_key(version: object) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(version or ""))) or (0,)


def bundle_app_version() -> str:
    """Return the bundled MCP application version.

    ``data/VERSION`` is the independently released corpus/data stamp.  Runtime-engine
    compatibility is tied to the Python/MCP application instead, whose version lives in the
    bundle manifest.
    """

    try:
        manifest = json.loads((BUNDLE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return "0"
    return str(manifest.get("version") or "0") if isinstance(manifest, dict) else "0"


def _pob_runtime_at(root: Path, *, source: str) -> PobRuntimePair:
    return PobRuntimePair(
        root=root,
        src_dir=root / "PathOfBuilding-PoE2" / "src",
        headless_script=root / "pob_headless.lua",
        source=source,
    )


def _runtime_pair_complete(pair: PobRuntimePair) -> bool:
    return (
        pair.src_dir.is_dir()
        and pair.headless_script.is_file()
        and (pair.root / "PathOfBuilding-PoE2" / "runtime" / "lua").is_dir()
    )


def _compatible_user_pob_runtime(pair: PobRuntimePair) -> bool:
    if not _runtime_pair_complete(pair):
        return False
    try:
        metadata = json.loads((user_data_dir() / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(metadata, dict):
        return False
    engine_contract = metadata.get("engine_contract")
    if isinstance(engine_contract, bool) or not isinstance(engine_contract, int):
        return False
    if engine_contract != POB_RUNTIME_CONTRACT:
        return False
    # engine_app_version is bound to the engine payload.  app_version remains a compatibility
    # fallback for the first release that adds this field to existing validated installations.
    engine_version = metadata.get("engine_app_version") or metadata.get("app_version")
    bundled_version = bundle_app_version()
    if _version_key(engine_version) == (0,) or _version_key(bundled_version) == (0,):
        return False
    return _version_key(engine_version) >= _version_key(bundled_version)


def pob_runtime_pair() -> PobRuntimePair:
    """Select a complete, compatible PoB runtime without mixing user and bundle paths."""

    updated = _pob_runtime_at(user_data_dir() / "pob", source="user-data")
    if _compatible_user_pob_runtime(updated):
        return updated
    return _pob_runtime_at(BUNDLE_ROOT / "pob", source="bundle")


def _corpus_revision(path: Path) -> tuple[int, str] | None:
    """Read the corpus-owned schema/build stamp without trusting external install metadata."""

    if not path.is_file():
        return None
    con: sqlite3.Connection | None = None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = dict(
            con.execute(
                "SELECT key, value FROM meta WHERE key IN ('schema_version', 'built_at')"
            ).fetchall()
        )
        return int(rows["schema_version"]), str(rows["built_at"])
    except (KeyError, OSError, sqlite3.Error, TypeError, ValueError):
        return None
    finally:
        if con is not None:
            con.close()


def corpus_path() -> Path:
    """Select the newest compatible corpus; an old user copy must not shadow a new bundle seed."""

    updated = user_data_dir() / "corpus.sqlite"
    seed = BUNDLE_ROOT / "data" / "corpus.sqlite"
    if not updated.is_file():
        return seed
    if not seed.is_file():
        return updated
    updated_revision = _corpus_revision(updated)
    seed_revision = _corpus_revision(seed)
    if updated_revision is None or seed_revision is None:
        return seed
    # A different schema belongs to a different code/data contract. The current bundle seed is
    # the only version known to match this code; same-schema user data may still be a newer update.
    if updated_revision[0] != seed_revision[0]:
        return seed
    return updated if updated_revision[1] >= seed_revision[1] else seed


def reference_builds_path() -> Path:
    """Bundled reference/calibration build library (data/reference_builds.json)."""
    return _prefer(
        user_data_dir() / "reference_builds.json",
        BUNDLE_ROOT / "data" / "reference_builds.json",
    )


def lifecycle_memory_path() -> Path:
    """Writable Phase 3 lifecycle research memory.

    The corpus remains read-only and release-managed; user feedback and promoted build
    techniques are local learning artifacts, so they live in the mutable user-data layer.
    """
    return user_data_dir() / "lifecycle_memory.json"


def mature_learning_path() -> Path:
    """Writable Phase 3N mature-build learning store.

    Mature build learning is release-seeded but locally mutable. The SQLite database belongs in
    user-data so fixture imports, later revalidation metadata, and local-only feedback boundaries do
    not modify bundled project files.
    """
    return user_data_dir() / "mature_build_learning.sqlite"


def research_runtime_dir() -> Path:
    """Private queue/review/quarantine runtime for mature-build Research tasks.

    Product runs must never live under the source checkout or an installed plugin cache: both are
    code locations, and the latter may be replaced by a cachebuster update. Durable accepted
    knowledge remains in :func:`mature_learning_path`; this directory contains only resumable
    task runtime that can be cleaned after acceptance/revisit completes.
    """

    return user_data_dir() / "research"


def mature_learning_release_seed_path() -> Path:
    """Creator-safe Research Memory seed shipped with a release."""
    return BUNDLE_ROOT / "data" / "mature_build_learning" / "release.sqlite"


def comparative_learning_release_seed_path() -> Path:
    """Copy-safe Phase 7 Learning Memory seed shipped with a release."""
    return BUNDLE_ROOT / "data" / "comparative_learning" / "learning-memory.seed.jsonl"


def physical_graph_seed_manifest_path() -> Path:
    """Portable physical-graph seed manifest shipped with a release."""
    return BUNDLE_ROOT / "data" / "physical_graph" / "seed.json"


def comparative_learning_dir() -> Path:
    """Writable, local-only root for Phase 7 campaign and quarantine state."""
    return user_data_dir() / "comparative-learning"


def comparative_learning_memory_path() -> Path:
    """Writable append-only Phase 7 Learning Memory, initialized from the release seed."""
    return comparative_learning_dir() / "learning-memory.jsonl"


def build_progression_lifecycle_receipts_dir() -> Path:
    """Artifact-bound lifecycle receipts used by artifact lifecycle verification."""
    return user_data_dir() / "build-progression" / "lifecycle-receipts"


def craft_legality_receipts_dir() -> Path:
    """Content-addressed, raw-free receipts for PoB-generated special crafting sources."""
    return user_data_dir() / "runtime" / "craft-legality-receipts"


def mature_learning_seed_fixtures_path() -> Path:
    """Bundled sanitized seed fixtures for the mature-learning store."""
    return BUNDLE_ROOT / "data" / "mature_build_learning" / "seed_cases.json"


def pob_src_dir() -> Path:
    return pob_runtime_pair().src_dir


def pob_headless_script() -> Path:
    return pob_runtime_pair().headless_script


def bundled_luajit() -> Path | None:
    """A LuaJIT binary shipped inside the bundle for this platform, if present."""
    plat = _PLATFORM_DIR.get(sys.platform)
    if not plat:
        return None
    exe = "luajit.exe" if sys.platform == "win32" else "luajit"
    cand = BUNDLE_ROOT / "runtime" / "luajit" / plat / exe
    return cand if cand.exists() else None
