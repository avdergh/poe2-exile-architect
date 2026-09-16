"""Fail CI if its shards omit tests, duplicate tests, or use different inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def collection_digest(node_ids: list[str]) -> str:
    return hashlib.sha256(json.dumps(node_ids, ensure_ascii=True).encode()).hexdigest()


def execution_context(root: Path) -> dict[str, str]:
    return {
        "commit": os.environ.get("GITHUB_SHA", "local"),
        "pobCommit": os.environ.get("POB_COMMIT", "local"),
        **{
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("data/corpus.sqlite", "data/compatibility/corpus.json", "uv.lock")
        },
    }


def selected_nodes(node_ids: list[str], index: int, count: int) -> list[str]:
    if count < 1 or not 0 <= index < count:
        raise ValueError("invalid CI shard index/count")
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("duplicate collected test IDs")
    return node_ids[index::count]


def verify_coverage(expected: dict, shards: list[dict], count: int) -> int:
    nodes = expected["selectedNodeIds"]
    digest = collection_digest(nodes)
    if (
        expected["shardCount"] != 1
        or expected["shardIndex"] != 0
        or expected["collectedCount"] != len(nodes)
        or expected["collectionDigest"] != digest
        or expected["collectionOnly"] is not True
        or expected["exitStatus"] != 0
        or not nodes
    ):
        raise ValueError("invalid full collection manifest")
    selected_nodes(nodes, 0, 1)
    if len(shards) != count or {s["shardIndex"] for s in shards} != set(range(count)):
        raise ValueError("missing or duplicate shard manifests")
    for shard in shards:
        if (
            shard["shardCount"] != count
            or shard["collectedCount"] != len(nodes)
            or shard["collectionDigest"] != digest
            or shard["executionContext"] != expected["executionContext"]
        ):
            raise ValueError("shards used different collections or inputs")
        if shard["selectedNodeIds"] != selected_nodes(nodes, shard["shardIndex"], count):
            raise ValueError("shard omitted, duplicated, or reassigned tests")
        completed = shard["completedNodeIds"]
        if (
            shard["collectionOnly"] is not False
            or shard["exitStatus"] != 0
            or len(completed) != len(shard["selectedNodeIds"])
            or set(completed) != set(shard["selectedNodeIds"])
        ):
            raise ValueError("shard did not finish all selected tests successfully")
    return len(nodes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    shards = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(args.results.glob("ci-shard-*/selection.json"))
    ]
    covered = verify_coverage(expected, shards, args.count)
    print(f"Coverage verified: all {covered} tests assigned exactly once across {args.count} shards.")
