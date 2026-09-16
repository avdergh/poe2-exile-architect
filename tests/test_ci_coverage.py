from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.verify_ci_coverage import collection_digest, selected_nodes, verify_coverage


def plans():
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
            "shardCount": 6,
            "selectedNodeIds": selected_nodes(nodes, i, 6),
            "completedNodeIds": selected_nodes(nodes, i, 6),
            "collectionOnly": False,
        }
        for i in range(6)
    ]
    return expected, shards


def test_all_tests_are_covered_once_including_an_uneven_remainder():
    expected, shards = plans()
    assert verify_coverage(expected, shards, 6) == 13
    assert max(map(lambda s: len(s["selectedNodeIds"]), shards)) == 3


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
