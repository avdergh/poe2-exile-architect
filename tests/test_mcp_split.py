"""MCP four-split tests: disjoint domain servers, complete coverage, legacy aggregate intact.

The full tool surface stays in ``server.main`` (single fact source). Each domain server
re-registers its own subset with its own short bootstrap; the legacy aggregate server keeps all
160 tools so tests, smoke scripts and old host configurations keep working.
"""

from __future__ import annotations

import asyncio

from server import main
from server.mcp import build_server, knowledge_server, learning_server, research_server


def _tool_names(server) -> set[str]:
    return {t.name for t in asyncio.run(server.list_tools())}


def test_four_splits_are_disjoint():
    parts = {
        "knowledge": _tool_names(knowledge_server.mcp),
        "build": _tool_names(build_server.mcp),
        "research": _tool_names(research_server.mcp),
        "learning": _tool_names(learning_server.mcp),
    }
    names = list(parts)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            assert not (parts[a] & parts[b]), f"{a} and {b} overlap: {parts[a] & parts[b]}"


def test_splits_cover_the_entire_legacy_surface():
    legacy = _tool_names(main.mcp)
    union = set().union(
        *[
            _tool_names(s.mcp)
            for s in (knowledge_server, build_server, research_server, learning_server)
        ]
    )
    assert legacy == union, (
        f"legacy has {legacy - union} tools outside the split; "
        f"splits have {union - legacy} unknown tools"
    )
    assert len(legacy) >= 125  # guard against accidental tool loss


def test_key_tools_land_in_the_right_server():
    assert "get_build_stats" in _tool_names(build_server.mcp)
    assert "import_build" in _tool_names(build_server.mcp)
    assert "evaluate_generation_candidate" in _tool_names(build_server.mcp)
    assert "save_final_build_artifact" in _tool_names(build_server.mcp)
    assert "preview_final_artifact_spirit_revalidation" in _tool_names(build_server.mcp)
    assert "apply_final_artifact_spirit_revalidation" in _tool_names(build_server.mcp)
    assert "verify_lifecycle_stage" in _tool_names(build_server.mcp)
    assert "evaluate_jewel_socket" in _tool_names(build_server.mcp)
    assert "optimize_flask" in _tool_names(build_server.mcp)

    assert "search_items" in _tool_names(knowledge_server.mcp)
    assert "query_research_memory" in _tool_names(knowledge_server.mcp)
    assert "get_research_write_receipt" in _tool_names(knowledge_server.mcp)
    assert "get_freshness_report" in _tool_names(knowledge_server.mcp)
    assert "graph_tool_query" in _tool_names(knowledge_server.mcp)
    assert "explain_mechanic" in _tool_names(knowledge_server.mcp)
    # Live/update ops and the copy-safe public learning projection ride with knowledge (read-only).
    assert "apply_updates" in _tool_names(knowledge_server.mcp)
    assert "query_public_learning_memory" in _tool_names(knowledge_server.mcp)

    assert "propose_research_fragments" in _tool_names(research_server.mcp)
    assert "validate_researcher_output" in _tool_names(research_server.mcp)
    assert "build_research_packet" in _tool_names(research_server.mcp)
    assert "preview_research_record_merge" in _tool_names(research_server.mcp)
    assert "apply_research_record_merge" in _tool_names(research_server.mcp)
    assert "inspect_research_merge_candidates" in _tool_names(research_server.mcp)
    assert {
        "start_research_run",
        "get_research_run_status",
        "claim_research_case",
        "cleanup_research_run",
        "inspect_research_case",
        "read_research_case",
        "search_research_case",
        "get_research_review_contract",
        "initialize_research_review",
        "validate_research_review",
        "accept_research_review",
        "retry_research_review",
    } <= _tool_names(research_server.mcp)

    assert "claim_learning_phase" in _tool_names(learning_server.mcp)
    assert "get_learning_create_packet" in _tool_names(learning_server.mcp)
    assert "submit_learning_create_result" in _tool_names(learning_server.mcp)


def test_engine_tools_are_build_server_only():
    # The single headless PoB engine must be reachable through exactly one server.
    engine_tools = {"new_build", "set_class", "get_build_stats", "equip_item", "optimize_passives"}
    assert engine_tools <= _tool_names(build_server.mcp)
    for other in (knowledge_server, research_server, learning_server):
        assert not (engine_tools & _tool_names(other.mcp))


def test_each_server_has_short_domain_instructions():
    for label, server in (
        ("knowledge", knowledge_server.mcp),
        ("build", build_server.mcp),
        ("research", research_server.mcp),
        ("learning", learning_server.mcp),
    ):
        instr = server.instructions or ""
        # Short, hard-boundary bootstrap — never the full runtime guide.
        assert 100 <= len(instr) <= 2400, f"{label} instructions out of bounds: {len(instr)}"
        # Workflow prose lives in the skills; the server channel stays boundary-only.
        assert "lifecycle" not in instr.lower() or label == "build" or label == "knowledge"


def test_server_identities():
    assert knowledge_server.mcp.name == "poe-knowledge-mcp"
    assert build_server.mcp.name == "poe-build-mcp"
    assert research_server.mcp.name == "poe-research-mcp"
    assert learning_server.mcp.name == "poe-learning-mcp"


def test_legacy_aggregate_still_registers_everything():
    legacy = _tool_names(main.mcp)
    assert "get_build_stats" in legacy
    assert "claim_learning_phase" in legacy
    assert "propose_research_fragments" in legacy
    assert "query_research_memory" in legacy
    assert "get_research_write_receipt" in legacy


def test_manifest_tool_list_matches_registered_surface():
    import json

    from server import paths as server_paths

    manifest = json.loads((server_paths.BUNDLE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    manifest_tools = {str(item["name"]) for item in manifest["tools"]}
    registered = _tool_names(main.mcp)
    assert manifest_tools == registered, (
        f"manifest lists {len(manifest_tools)} tools but {len(registered)} are registered; "
        f"manifest-only: {sorted(manifest_tools - registered)}; "
        f"registered-only: {sorted(registered - manifest_tools)}"
    )
