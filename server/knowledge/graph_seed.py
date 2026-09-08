"""Install a portable, release-bundled physical graph seed on first use."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from .. import paths
from . import physical_graph

_INSTALL_LOCK = threading.RLock()


def _file_signature(path: Path) -> tuple[object, ...]:
    try:
        stat = path.stat()
        return (str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
    except FileNotFoundError:
        return (str(path.resolve()), None)


def _validation_state(index_path: Path, manifest_path: Path) -> tuple[object, ...]:
    rows = physical_graph.list_registered_snapshots(index_path)
    latest = next((row for row in rows if row["is_latest"]), rows[0] if rows else None)
    local = (json.dumps(latest, sort_keys=True),
             _file_signature(Path(latest["snapshot_path"]))) if latest else None
    if manifest_path.is_file():
        manifest = _read_manifest(manifest_path)
        bundled = (json.dumps(manifest, sort_keys=True), _file_signature(manifest_path),
                   _file_signature(manifest_path.parent / manifest["snapshotFile"]))
    else:
        bundled = _file_signature(manifest_path)
    return (local, bundled)


def ensure_installed() -> Path:
    """Return a usable user-data graph index, installing the bundled seed when necessary."""

    graph_root = paths.user_data_dir() / "physical_graph"
    index_path = graph_root / "snapshot_index.sqlite"
    manifest_path = paths.physical_graph_seed_manifest_path()
    with _INSTALL_LOCK:
        return _ensure_validated(str(index_path.resolve()), str(manifest_path.resolve()),
                                 _validation_state(index_path, manifest_path))


@lru_cache(maxsize=8)
def _ensure_validated(index: str, manifest_file: str, state: tuple[object, ...]) -> Path:
    # Cache only successful validations. A registry/file/manifest change takes the cold path.
    del state
    index_path = Path(index)
    graph_root = index_path.parent
    manifest_path = Path(manifest_file)
    installed_snapshot = None
    try:
        installed_snapshot = physical_graph.load_latest_snapshot(index_path)
    except (FileNotFoundError, OSError, ValueError, KeyError):
        pass

    if installed_snapshot is not None and not manifest_path.is_file():
        return index_path
    manifest = _read_manifest(manifest_path)
    bundled_snapshot = manifest_path.parent / manifest["snapshotFile"]
    expected_hash = manifest["sha256"]
    if _sha256(bundled_snapshot) != expected_hash:
        raise ValueError("bundled physical graph seed checksum mismatch")
    snapshot = physical_graph.load_snapshot(bundled_snapshot)
    if snapshot.snapshot_id != manifest["snapshotId"]:
        raise ValueError("bundled physical graph seed identity mismatch")
    if installed_snapshot is not None and installed_snapshot.created_at >= snapshot.created_at:
        return index_path

    target = graph_root / "snapshots" / bundled_snapshot.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temp = target.with_name(f".{target.name}.{uuid4().hex}.installing")
        shutil.copy2(bundled_snapshot, temp)
        try:
            os.link(temp, target)
        except FileExistsError:
            pass
        finally:
            temp.unlink(missing_ok=True)
    if _sha256(target) != expected_hash:
        raise ValueError("installed physical graph seed checksum mismatch")
    physical_graph.register_snapshot(index_path, snapshot, target)
    return index_path


def _read_manifest(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FileNotFoundError("bundled physical graph seed is unavailable") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("bundled physical graph seed manifest is invalid")
    required = {key: payload.get(key) for key in ("snapshotId", "snapshotFile", "sha256")}
    if not all(isinstance(value, str) and value for value in required.values()):
        raise ValueError("bundled physical graph seed manifest is incomplete")
    snapshot_file = str(required["snapshotFile"])
    candidate = (path.parent / snapshot_file).resolve()
    if path.parent.resolve() not in candidate.parents:
        raise ValueError("bundled physical graph seed path escapes its data directory")
    return {
        "snapshotId": str(required["snapshotId"]),
        "snapshotFile": snapshot_file,
        "sha256": str(required["sha256"]),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
