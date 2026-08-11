"""Package the latest validated physical graph as a portable plugin seed."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.knowledge import physical_graph  # noqa: E402


DEFAULT_SOURCE = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "poe2-build-mcp"
    / "physical_graph"
)


def package_graph_seed(*, source_dir: str | Path, output_dir: str | Path) -> dict[str, object]:
    source_root = Path(source_dir).resolve()
    output_root = Path(output_dir).resolve()
    rows = physical_graph.list_registered_snapshots(source_root / "snapshot_index.sqlite")
    latest = next((row for row in rows if bool(row.get("is_latest"))), None)
    if latest is None:
        raise FileNotFoundError("no latest physical graph snapshot is registered")
    source_snapshot = Path(str(latest["snapshot_path"])).resolve()
    snapshot = physical_graph.load_snapshot(source_snapshot)
    if snapshot.snapshot_id != str(latest["snapshot_id"]):
        raise ValueError("physical graph index and snapshot identity differ")
    snapshots_dir = output_root / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    target = snapshots_dir / f"{snapshot.snapshot_id}.json.gz"
    temp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    _write_gzip_snapshot(source_snapshot, temp)
    temp.replace(target)
    digest = _sha256(target)
    manifest = {
        "schemaVersion": 1,
        "snapshotId": snapshot.snapshot_id,
        "snapshotFile": f"snapshots/{target.name}",
        "sha256": digest,
        "compressed": True,
        "nodeCount": len(snapshot.nodes),
        "edgeCount": len(snapshot.edges),
        "sourceCount": len(snapshot.sources),
    }
    manifest_path = output_root / "seed.json"
    manifest_temp = manifest_path.with_name(f".{manifest_path.name}.{uuid4().hex}.tmp")
    with manifest_temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, indent=2) + "\n")
    manifest_temp.replace(manifest_path)
    return {
        "status": "packaged",
        "output": str(output_root),
        "snapshotId": snapshot.snapshot_id,
        "sha256": digest,
        "sizeBytes": target.stat().st_size,
        "nodeCount": len(snapshot.nodes),
        "edgeCount": len(snapshot.edges),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_gzip_snapshot(source: Path, target: Path) -> None:
    """Stream a validated snapshot into a deterministic gzip seed for Git/bundles.

    Newlines are normalized to LF (like the old plain-JSON packaging) so the decompressed
    content is platform-independent. gzip header embeds no timestamp by default in this Python
    implementation, so the bytes are reproducible across builds; the manifest sha256 covers the
    compressed file.
    """

    with (
        source.open("r", encoding="utf-8", newline=None) as source_handle,
        gzip.GzipFile(filename="", mode="wb", fileobj=target.open("wb"), mtime=0) as target_handle,
    ):
        while chunk := source_handle.read(1024 * 1024):
            target_handle.write(chunk.replace("\r\n", "\n").encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    report = package_graph_seed(source_dir=args.source_dir, output_dir=args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
