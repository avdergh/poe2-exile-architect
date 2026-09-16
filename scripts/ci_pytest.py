"""Opt-in pytest sharding for CI; ordinary local pytest runs are unchanged."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_ci_coverage import collection_digest, execution_context, selected_nodes


class CompletionRecorder:
    def __init__(self, manifest: Path, document: dict):
        self.manifest = manifest
        self.document = document
        self.completed: list[str] = []

    def pytest_runtest_logfinish(self, nodeid, location):
        self.completed.append(nodeid)

    def pytest_sessionfinish(self, session, exitstatus):
        self.document["completedNodeIds"] = self.completed
        self.document["exitStatus"] = int(exitstatus)
        self.manifest.write_text(json.dumps(self.document, indent=2) + "\n", encoding="utf-8")


def pytest_addoption(parser):
    group = parser.getgroup("ci-sharding")
    group.addoption("--ci-shard-index", type=int, default=0)
    group.addoption("--ci-shard-count", type=int, default=1)
    group.addoption("--ci-manifest", type=Path)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    index = config.getoption("ci_shard_index")
    count = config.getoption("ci_shard_count")
    node_ids = [item.nodeid for item in items]
    try:
        selected = selected_nodes(node_ids, index, count)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
    manifest = config.getoption("ci_manifest")
    if manifest:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "shardIndex": index,
            "shardCount": count,
            "collectedCount": len(node_ids),
            "collectionDigest": collection_digest(node_ids),
            "selectedNodeIds": selected,
            "executionContext": execution_context(Path(config.rootpath)),
            "collectionOnly": config.getoption("collectonly"),
        }
        manifest.write_text(
            json.dumps(document, indent=2) + "\n",
            encoding="utf-8",
        )
        config.pluginmanager.register(CompletionRecorder(manifest, document))
    if count > 1:
        kept = set(selected)
        deselected = [item for item in items if item.nodeid not in kept]
        items[:] = [item for item in items if item.nodeid in kept]
        config.hook.pytest_deselected(items=deselected)
