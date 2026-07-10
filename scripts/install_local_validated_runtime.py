"""Install the current certified PoB/corpus pair into a local runtime data directory.

This is a development helper, not the public self-updater. It exists so a freshly certified
PoB commit can be smoke-tested through the same `POE2_MCP_DATA` path that production uses,
before a GitHub release publishes `update-manifest.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.freshness.pob import (  # noqa: E402
    PobParseError,
    load_compatibility_manifest,
    read_pinned_commit,
    resolve_compatibility,
)


DEFAULT_VERSION = "0.1.39.2-local.20260710"
DEFAULT_APP_VERSION = "0.1.39"

# Same art/media exclusions as bundle creation. The headless engine does not load these, and
# copying them would make local runtime installs slow and huge for no calculation benefit.
ART_SUFFIXES = {
    ".dds",
    ".zst",
    ".png",
    ".jpg",
    ".jpeg",
    ".tga",
    ".gif",
    ".bk2",
    ".mp4",
    ".ogg",
    ".mp3",
}


class LocalRuntimeInstallError(RuntimeError):
    """Expected local runtime installation failure."""


def install_local_runtime(
    *,
    root: str | Path = ROOT,
    target: str | Path,
    version: str = DEFAULT_VERSION,
    app_version: str = DEFAULT_APP_VERSION,
    pob_commit: str | None = None,
) -> dict[str, Any]:
    repo_root = Path(root).resolve()
    target_dir = Path(target).resolve()
    _validate_target(repo_root, target_dir)

    commit = pob_commit or _git_head(repo_root / "pob" / "PathOfBuilding-PoE2")
    manifest_path = repo_root / "data" / "compatibility" / "pob.json"
    try:
        manifest = load_compatibility_manifest(manifest_path)
        compatibility = resolve_compatibility(commit, manifest)
    except (OSError, ValueError, PobParseError) as exc:
        raise LocalRuntimeInstallError(f"compatibility manifest invalid: {exc}") from exc
    if compatibility is None:
        raise LocalRuntimeInstallError(f"PoB commit {commit} is not certified in {manifest_path}")

    pinned = read_pinned_commit(repo_root / "pob" / "PINNED.md")
    if pinned and not (
        compatibility.commit.startswith(pinned) or pinned.startswith(compatibility.commit)
    ):
        raise LocalRuntimeInstallError(
            f"pob/PINNED.md points at {pinned}, not certified commit {compatibility.commit}"
        )

    corpus = _required_file(repo_root / "data" / "corpus.sqlite")
    headless = _required_file(repo_root / "pob" / "pob_headless.lua")
    src = _required_dir(repo_root / "pob" / "PathOfBuilding-PoE2" / "src")
    runtime_lua = _required_dir(repo_root / "pob" / "PathOfBuilding-PoE2" / "runtime" / "lua")

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(corpus, target_dir / "corpus.sqlite")

    target_pob = target_dir / "pob"
    # Only this child directory is replaced. `_validate_target` prevents target_dir from being the
    # repository root, so this cannot delete the source `pob/` tree by accident.
    if target_pob.exists():
        shutil.rmtree(target_pob)
    _copy_file(headless, target_pob / "pob_headless.lua")
    _copy_tree(src, target_pob / "PathOfBuilding-PoE2" / "src")
    _copy_tree(runtime_lua, target_pob / "PathOfBuilding-PoE2" / "runtime" / "lua")
    pinned_path = repo_root / "pob" / "PINNED.md"
    if pinned_path.exists():
        _copy_file(pinned_path, target_pob / "PINNED.md")

    installed = {
        "version": version,
        "app_version": app_version,
        "pob_commit": compatibility.commit,
        "pob_version": compatibility.pob_version,
        "game_patch": compatibility.game_patch,
        "passive_tree": compatibility.passive_tree,
        # This is a local provenance fingerprint of the copied engine subset, not a public release
        # zip checksum. A later official update will still download the engine if its zip SHA differs.
        "engine_sha256": _directory_sha256(target_pob),
    }
    _write_json_atomic(target_dir / "installed.json", installed)
    return {"updated": True, "target": str(target_dir), **installed}


def _validate_target(root: Path, target: Path) -> None:
    forbidden = {root, root / "pob", root / "data"}
    if target in {path.resolve() for path in forbidden}:
        raise LocalRuntimeInstallError("refusing to install local runtime into repository root")


def _required_file(path: Path) -> Path:
    if not path.is_file():
        raise LocalRuntimeInstallError(f"required file missing: {path}")
    return path


def _required_dir(path: Path) -> Path:
    if not path.is_dir():
        raise LocalRuntimeInstallError(f"required directory missing: {path}")
    return path


def _git_head(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LocalRuntimeInstallError(f"cannot read PoB git HEAD from {repo}") from exc
    return result.stdout.strip()


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
    for item in src.rglob("*"):
        if item.is_dir() or item.suffix.lower() in ART_SUFFIXES:
            continue
        _copy_file(item, dst / item.relative_to(src))


def _directory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = item.relative_to(path).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=str(ROOT / ".runtime-data"))
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--app-version", default=DEFAULT_APP_VERSION)
    args = parser.parse_args()

    try:
        result = install_local_runtime(
            target=args.target,
            version=args.version,
            app_version=args.app_version,
        )
    except LocalRuntimeInstallError as exc:
        print(f"install failed: {exc}")
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
