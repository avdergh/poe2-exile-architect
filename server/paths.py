"""Runtime path resolution.

The server ships a self-contained *seed* (bundled corpus + PoB engine) but auto-updates
into a writable per-user data directory. Every runtime path prefers the updated user copy
and falls back to the bundled seed, so a fresh install works offline and updates layer on top.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Bundle/repo root (this file is <root>/server/paths.py).
BUNDLE_ROOT = Path(__file__).resolve().parents[1]

_PLATFORM_DIR = {"win32": "win-x64", "darwin": "mac-arm64", "linux": "linux-x64"}


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


def corpus_path() -> Path:
    return _prefer(user_data_dir() / "corpus.sqlite", BUNDLE_ROOT / "data" / "corpus.sqlite")


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
    return _prefer(
        user_data_dir() / "pob" / "PathOfBuilding-PoE2" / "src",
        BUNDLE_ROOT / "pob" / "PathOfBuilding-PoE2" / "src",
        is_dir=True,
    )


def pob_headless_script() -> Path:
    return _prefer(
        user_data_dir() / "pob" / "pob_headless.lua",
        BUNDLE_ROOT / "pob" / "pob_headless.lua",
    )


def bundled_luajit() -> Path | None:
    """A LuaJIT binary shipped inside the bundle for this platform, if present."""
    plat = _PLATFORM_DIR.get(sys.platform)
    if not plat:
        return None
    exe = "luajit.exe" if sys.platform == "win32" else "luajit"
    cand = BUNDLE_ROOT / "runtime" / "luajit" / plat / exe
    return cand if cand.exists() else None
