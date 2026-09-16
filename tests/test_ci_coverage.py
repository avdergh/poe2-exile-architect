from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.verify_ci_coverage import (
    collection_digest, execution_context, selected_nodes, verify_coverage,
)


def plans(count=6):
    nodes = [f"tests/test_example.py::test_case[{i}]" for i in range(13)]
    expected = {
        "shardIndex": 0,
        "shardCount": 1,
        "collectedCount": len(nodes),
        "collectionDigest": collection_digest(nodes),
        "selectedNodeIds": nodes,
        "executionContext": {"commit": "same-commit", "corpus": "same-corpus"},
        "collectionOnly": True,
        "exitStatus": 0,
    }
    shards = [
        {
            **expected,
            "shardIndex": i,
            "shardCount": count,
            "selectedNodeIds": selected_nodes(nodes, i, count),
            "completedNodeIds": selected_nodes(nodes, i, count),
            "collectionOnly": False,
        }
        for i in range(count)
    ]
    return expected, shards


@pytest.mark.parametrize("count", [1, 2, 6, 8])
def test_all_tests_are_covered_once_including_an_uneven_remainder(count):
    expected, shards = plans(count)
    assert verify_coverage(expected, shards, count) == 13
    assert max(len(s["selectedNodeIds"]) for s in shards) == (13 + count - 1) // count


@pytest.mark.parametrize(
    "problem", ["missing", "duplicate", "omitted", "reassigned", "inputs", "unfinished", "failed-exit"]
)
def test_coverage_rejects_incomplete_or_mixed_results(problem):
    expected, original = plans()
    shards = deepcopy(original)
    if problem == "missing":
        shards.pop()
    elif problem == "duplicate":
        shards[-1] = shards[0]
    elif problem == "omitted":
        shards[0]["selectedNodeIds"].pop()
    elif problem == "reassigned":
        shards[0]["selectedNodeIds"].append(shards[1]["selectedNodeIds"].pop())
    elif problem == "inputs":
        shards[0]["executionContext"]["corpus"] = "different-corpus"
    elif problem == "unfinished":
        shards[0]["completedNodeIds"].pop()
    else:
        shards[0]["exitStatus"] = 1
    with pytest.raises(ValueError):
        verify_coverage(expected, shards, 6)


@pytest.mark.parametrize("index,count", [(-1, 6), (6, 6), (0, 0)])
def test_invalid_shards_are_rejected(index, count):
    with pytest.raises(ValueError):
        selected_nodes(["one"], index, count)


def test_duplicate_collected_ids_are_rejected():
    with pytest.raises(ValueError):
        selected_nodes(["same", "same"], 0, 1)


def test_context_detects_changed_and_missing_raw_skill_inputs(tmp_path):
    for name in ("data/corpus.sqlite", "data/compatibility/corpus.json", "uv.lock"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    raw = tmp_path / "data/raw/skills.min.json"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b'{"skill":"original"}')
    before = execution_context(tmp_path)
    raw.write_bytes(b'{"skill":"changed"}')
    assert execution_context(tmp_path) != before
    raw.unlink()
    assert execution_context(tmp_path) != before
