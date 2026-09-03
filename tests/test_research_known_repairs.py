from __future__ import annotations

from datetime import UTC, datetime

from server.knowledge import graph_tools, physical_graph, research_known_repairs
from server.knowledge import mature_learning, research_memory, research_runtime


def _graph_service() -> graph_tools.GraphQueryService:
    source = physical_graph.GraphSource("fixture:repair", "test", __file__)
    return graph_tools.GraphQueryService.from_snapshot(
        physical_graph.GraphSnapshot(
            snapshot_id="snapshot:repair",
            created_at=datetime(2026, 8, 23, tzinfo=UTC),
            sources=(source,),
            nodes=(
                physical_graph.GraphNode(
                    "skill:RepairPlayer", "active_skill", "Repair", (source.source_id,)
                ),
                physical_graph.GraphNode(
                    "ascendancy:witch:blood_mage",
                    "ascendancy",
                    "Blood Mage",
                    (source.source_id,),
                ),
            ),
            edges=(),
            aliases=(),
        )
    )


def _payload() -> dict:
    return {
        "schema_version": 6,
        "deep_research_records": [
            {
                "research_group_id": "research:repair",
                "record_kind": "resource_engine",
                "title": "Repair fixture",
                "summary": "Safe repair fixture.",
                "content": "资源机制仅用于测试精确指纹隔离。",
                "content_language": "zh-CN",
                "component_keys": ["skill:RepairPlayer"],
                "component_mentions": [
                    {
                        "candidate_name": "Repair",
                        "role": "primary_damage",
                        "resolver_query": "skill:RepairPlayer",
                        "expected_node_types": ["active_skill"],
                        "scope": "player",
                        "component_key": "skill:RepairPlayer",
                        "resolution_status": "resolved",
                    }
                ],
                "source_case_refs": ["source-hash:repair"],
                "safe_evidence_refs": ["evidence:repair"],
                "conditions": [],
                "failure_conditions": [],
                "typed_payload": {"resourceMechanisms": ["mana_flask"]},
                "ascendancy_key": "ascendancy:witch:blood_mage",
                "extraction_method_version": "test",
                "record_schema_version": 2,
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "local_user",
                "status": "valid",
                "copy_safety_state": "passed",
                "source_state_scope": "state_agnostic",
            }
        ],
    }


def test_known_repair_is_fingerprint_bound_and_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    accepted = service.propose_deep_research_records(_payload())
    record_id = accepted["recordIds"][0]
    con = mature_learning.connect(db_path)
    try:
        row = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = ?", (record_id,)
        ).fetchone()
        manifest = (
            {
                "recordId": record_id,
                "knowledgeKey": str(row["knowledge_key"]),
                "recordKind": str(row["record_kind"]),
                "projectionHash": research_runtime.projection_hash(row),
                "sourceCaseRefs": ["source-hash:repair"],
            },
        )
    finally:
        con.close()
    monkeypatch.setattr(research_known_repairs, "KNOWN_BAD_RECORDS", manifest)
    assert research_known_repairs.inspect_known_repair(db_path)["status"] == "ready"
    applied = research_known_repairs.apply_known_repair(db_path)
    assert applied["status"] == "applied"
    assert research_known_repairs.apply_known_repair(db_path)["status"] == "already_applied"
    con = mature_learning.connect(db_path)
    try:
        assert (
            con.execute(
                "SELECT status FROM deep_research_records WHERE record_id = ?", (record_id,)
            ).fetchone()[0]
            == "quarantined"
        )
    finally:
        con.close()
