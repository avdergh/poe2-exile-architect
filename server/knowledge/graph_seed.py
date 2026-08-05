"""Install a portable, release-bundled physical graph seed on first use."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from .. import paths
from . import physical_graph


def ensure_installed() -> Path:
    """Return a usable user-data graph index, installing the bundled seed when necessary."""

    graph_root = paths.user_data_dir() / "physical_graph"
    index_path = graph_root / "snapshot_index.sqlite"
    try:
        physical_graph.load_latest_snapshot(index_path)
        return index_path
    except (FileNotFoundError, OSError, ValueError, KeyError):
        pass

    manifest_path = paths.physical_graph_seed_manifest_path()
    manifest = _read_manifest(manifest_path)
    bundled_snapshot = manifest_path.parent / manifest["snapshotFile"]
    expected_hash = manifest["sha256"]
    if _sha256(bundled_snapshot) != expected_hash:
        raise ValueError("bundled physical graph seed checksum mismatch")
    snapshot = physical_graph.load_snapshot(bundled_snapshot)
    if snapshot.snapshot_id != manifest["snapshotId"]:
        raise ValueError("bundled physical graph seed identity mismatch")

    target = graph_root / "snapshots" / f"{snapshot.snapshot_id}.json"
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
