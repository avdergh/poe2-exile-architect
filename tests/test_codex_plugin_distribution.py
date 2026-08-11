from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codex_plugin_registers_self_contained_mcp_runtime() -> None:
    plugin_root = ROOT / "poe-bd-creator-plugin"
    manifest = json.loads(
        (plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    mcp = json.loads((plugin_root / ".mcp.json").read_text(encoding="utf-8"))
    servers = mcp["mcpServers"]

    assert manifest["mcpServers"] == "./.mcp.json"
    assert set(servers) == {
        "poe_knowledge_mcp",
        "poe_build_mcp",
        "poe_research_mcp",
        "poe_learning_mcp",
    }
    for server_name, args in (
        ("poe_knowledge_mcp", ["knowledge"]),
        ("poe_build_mcp", ["build"]),
        ("poe_research_mcp", ["research"]),
        ("poe_learning_mcp", ["learning"]),
    ):
        server = servers[server_name]
        assert server["cwd"] == "."
        assert server["command"] == "node"
        assert server["args"] == ["./scripts/run_plugin_server.mjs", "--server", *args]
    assert (plugin_root / "scripts" / "run_plugin_server.mjs").is_file()
    assert (plugin_root / "scripts" / "run_plugin_server.py").is_file()


def test_codex_distribution_requires_helper_and_release_databases() -> None:
    text = (ROOT / "scripts" / "build_codex_plugin.py").read_text(encoding="utf-8")
    bundle = (ROOT / "scripts" / "build_bundle.py").read_text(encoding="utf-8")
    assert "scripts/create_build.py" in text
    assert "data/mature_build_learning/release.sqlite" in text
    assert "data/comparative_learning/learning-memory.seed.jsonl" in text
    assert "data/physical_graph/seed.json" in text
    assert "data/corpus.sqlite" in text
    assert '"mcp>=1.2,<2"' in bundle


def test_github_checkout_contains_offline_create_seeds() -> None:
    required = (
        "data/corpus.sqlite",
        "data/mature_build_learning/release.sqlite",
        "data/comparative_learning/learning-memory.seed.jsonl",
        "data/physical_graph/seed.json",
    )
    for relative_path in required:
        assert (ROOT / relative_path).is_file(), relative_path

    graph_manifest = json.loads(
        (ROOT / "data" / "physical_graph" / "seed.json").read_text(encoding="utf-8")
    )
    assert (ROOT / "data" / "physical_graph" / graph_manifest["snapshotFile"]).is_file()
