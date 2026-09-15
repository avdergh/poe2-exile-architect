"""公开操作目录与实际schema同源，且不需要图快照。"""

from server import main
from server.knowledge import graph_tools


def test_catalog_uses_real_registered_operations_without_loading_a_graph(monkeypatch):
    def forbidden():
        raise AssertionError("catalog must not load a graph")

    monkeypatch.setattr(main, "_graph_query_service", forbidden)
    result = main.graph_tool_query("list_graph_tools", {})
    assert result["status"] == "ok"
    assert {item["queryFamily"] for item in result["tools"]} == set(graph_tools.INPUT_MODELS)
    assert result["staticEffectRead"]["tool_name"] == "explain_graph_evidence"


def test_exact_catalog_schema_uses_typed_validation_contract():
    for name, model in graph_tools.INPUT_MODELS.items():
        result = main.graph_tool_query("list_graph_tools", {"query_family": name})
        assert result["inputSchema"] == model.model_json_schema()
        assert result["contextPolicy"] == graph_tools.CONTEXT_POLICIES[name]
    result = main.graph_tool_query("list_graph_tools", {"query_family": "explain_graph_evidence"})
    assert "node_key" in result["inputSchema"]["properties"]


def test_catalog_rejects_raw_queries_and_unregistered_helpers():
    assert (
        main.graph_tool_query("list_graph_tools", {"sql": "SELECT 1"})["errorCode"]
        == "invalid_payload"
    )
    assert (
        main.graph_tool_query(
            "list_graph_tools", {"query_family": "support_skill_group_candidates"}
        )["errorCode"]
        == "unsupported_tool"
    )
