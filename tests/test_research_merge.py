from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from datetime import UTC, datetime
import json

from server.knowledge import (
    graph_tools,
    mature_learning,
    physical_graph,
    research_memory,
    research_merge,
)


def _record(*, schema: int, source: str, evidence: str) -> dict[str, object]:
    package: dict[str, object] = {
        "skillKey": "skill:SparkPlayer",
        "supportKeys": ["support:SupportGemArcaneTempo"],
    }
    if schema == 2:
        package["deliveryRole"] = "direct"
    return {
        "research_group_id": "research:case:merge-fixture",
        "record_kind": "skill_package",
        "title": "Spark support package",
        "summary": "Spark uses Arcane Tempo in the tested source.",
        "content": "Spark uses Arcane Tempo while the socket group remains enabled.",
        "content_language": "en",
        "length_exception_reason": None,
        "component_keys": ["skill:SparkPlayer", "support:SupportGemArcaneTempo"],
        "component_mentions": [
            {
                "role": "primary_damage",
                "candidate_name": "Spark",
                "component_key": "skill:SparkPlayer",
                "resolver_query": "Spark",
                "resolution_status": "resolved",
            },
            {
                "role": "support_modifier",
                "candidate_name": "Arcane Tempo",
                "component_key": "support:SupportGemArcaneTempo",
                "resolver_query": "Arcane Tempo",
                "resolution_status": "resolved",
            },
        ],
        "source_case_refs": [source],
        "safe_evidence_refs": [evidence],
        "conditions": ["The source group is enabled."],
        "failure_conditions": ["The support is removed."],
        "typed_payload": {
            "knowledgeShape": "state_causal_chain",
            "supportPackages": [package],
        },
        "class_key": "class:sorceress",
        "ascendancy_key": "ascendancy:sorceress:stormweaver",
        "extraction_method_version": "deep_research_mvp_v1",
        "record_schema_version": schema,
        "game_patch": "0.5.4",
        "passive_tree_version": "0_5",
        "pob_version_or_commit": "unknown",
        "visibility": "creator_visible",
        "split": "train_context",
        "knowledge_scope": "global_seed",
        "status": "valid",
        "copy_safety_state": "passed",
        "source_state_scope": "active_state",
    }


def _dispositions() -> list[dict[str, object]]:
    return [
        {
            "field": field,
            "disposition": "preserved",
            "reason": "The reviewer confirmed this field remains part of the canonical record.",
            "safeEvidenceRefs": [],
        }
        for field in sorted(research_merge.MERGE_FIELDS)
    ]


def _reviewer() -> dict[str, object]:
    return {
        "verdict": "approve",
        "fieldIssues": [],
        "externalResearch": {
            "status": "not_needed",
            "reason": "This merge changes schema ownership only; no PoE2 mechanic is disputed.",
            "queries": [],
            "sources": [],
            "conclusion": "The two records describe the same tested package.",
            "confidence": "high",
            "residualUncertainty": "",
        },
    }


def _seed(db_path: Path) -> tuple[str, str, dict[str, object]]:
    source = physical_graph.GraphSource(
        source_id="fixture:merge",
        kind="test_fixture",
        source_file="tests/test_research_merge.py",
    )
    graph = graph_tools.GraphQueryService.from_snapshot(
        physical_graph.GraphSnapshot(
            snapshot_id="snapshot:merge",
            created_at=datetime(2026, 8, 24, tzinfo=UTC),
            sources=(source,),
                nodes=(
                physical_graph.GraphNode(
                    "skill:SparkPlayer", "active_skill", "Spark", (source.source_id,)
                ),
                    physical_graph.GraphNode(
                        "support:SupportGemArcaneTempo",
                        "support_gem",
                        "Arcane Tempo",
                        (source.source_id,),
                    ),
                    physical_graph.GraphNode(
                        "class:sorceress", "class", "Sorceress", (source.source_id,)
                    ),
                    physical_graph.GraphNode(
                        "ascendancy:sorceress:stormweaver",
                        "ascendancy",
                        "Stormweaver",
                        (source.source_id,),
                    ),
                ),
                edges=(),
                aliases=(
                physical_graph.GraphAlias(
                    "Spark", "skill:SparkPlayer", (source.source_id,)
                ),
                physical_graph.GraphAlias(
                    "Arcane Tempo", "support:SupportGemArcaneTempo", (source.source_id,)
                ),
            ),
        )
    )
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=graph)
    legacy = _record(schema=1, source="case:legacy", evidence="evidence:legacy")
    current = _record(schema=2, source="case:current", evidence="evidence:current")
    first = service.propose_deep_research_records(
        {"schema_version": 5, "deep_research_records": [legacy]}
    )
    second = service.propose_deep_research_records(
        {"schema_version": 6, "deep_research_records": [current]}
    )
    assert "recordIds" in first, json.dumps(first, ensure_ascii=False)
    assert "recordIds" in second, json.dumps(second, ensure_ascii=False)
    con = mature_learning.connect(db_path)
    try:
        current_row = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = ?",
            (second["recordIds"][0],),
        ).fetchone()
        current_payload = research_merge.proposal_payload_from_row(current_row)
    finally:
        con.close()
    return first["recordIds"][0], second["recordIds"][0], current_payload


def _plan(legacy_id: str, current_id: str, merged: dict[str, object]) -> dict[str, object]:
    merged = deepcopy(merged)
    merged["source_case_refs"] = ["case:current", "case:legacy"]
    merged["safe_evidence_refs"] = ["evidence:current", "evidence:legacy"]
    return {
        "reportId": "research-merge-plan-v1",
        "items": [
            {
                "action": "merge_into_head",
                "targetRecordId": current_id,
                "sourceRecordIds": [legacy_id, current_id],
                "mergedRecord": merged,
                "fieldDispositions": _dispositions(),
                "reviewer": _reviewer(),
                "requiresExternalResearch": False,
            }
        ],
    }


def test_model_reviewed_merge_preview_and_apply_preserve_active_head(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite"
    legacy_id, current_id, current = _seed(db_path)
    service = research_merge.ResearchMergeService(db_path)
    plan = _plan(legacy_id, current_id, current)

    candidates = service.inspect_candidates(build_family_key=None, limit=10)
    assert candidates["candidateCount"] == 1
    assert candidates["candidates"][0]["semanticDecisionRequired"] is True

    preview = service.preview(plan)

    assert preview["status"] == "preview_ready", preview
    assert preview["items"][0]["proposedHeadRecordId"] == current_id
    assert preview["items"][0]["wouldRemainCreateAuthorizing"] is True

    applied = service.apply(
        plan,
        expected_memory_revision=preview["expectedMemoryRevision"],
        merge_plan_hash=preview["mergePlanHash"],
        user_approved=True,
    )

    assert applied["status"] == "applied"
    assert applied["items"][0]["headRecordId"] == current_id
    con = mature_learning.connect(db_path)
    try:
        legacy = con.execute(
            "SELECT status, superseded_by_id FROM deep_research_records WHERE record_id = ?",
            (legacy_id,),
        ).fetchone()
        head = con.execute(
            "SELECT status, superseded_by_id FROM deep_research_records WHERE record_id = ?",
            (current_id,),
        ).fetchone()
    finally:
        con.close()
    assert tuple(legacy) == ("deprecated", current_id)
    assert tuple(head) == ("valid", None)


def test_schema_upgrade_updates_selected_head_without_creating_successor(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite"
    legacy_id, current_id, current = _seed(db_path)
    service = research_merge.ResearchMergeService(db_path)
    plan = _plan(legacy_id, current_id, current)
    plan["items"][0]["targetRecordId"] = legacy_id

    preview = service.preview(plan)
    assert preview["status"] == "preview_ready", preview
    assert preview["items"][0]["proposedHeadRecordId"] == legacy_id

    applied = service.apply(
        plan,
        expected_memory_revision=preview["expectedMemoryRevision"],
        merge_plan_hash=preview["mergePlanHash"],
        user_approved=True,
    )

    assert applied["status"] == "applied"
    assert applied["items"][0]["headRecordId"] == legacy_id
    con = mature_learning.connect(db_path)
    try:
        head = con.execute(
            "SELECT record_schema_version, status, superseded_by_id "
            "FROM deep_research_records WHERE record_id = ?",
            (legacy_id,),
        ).fetchone()
        duplicate = con.execute(
            "SELECT status, superseded_by_id FROM deep_research_records WHERE record_id = ?",
            (current_id,),
        ).fetchone()
    finally:
        con.close()
    assert tuple(head) == (2, "valid", None)
    assert tuple(duplicate) == ("deprecated", legacy_id)


def test_merge_rejects_missing_field_review_and_stale_preview(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite"
    legacy_id, current_id, current = _seed(db_path)
    service = research_merge.ResearchMergeService(db_path)
    plan = _plan(legacy_id, current_id, current)
    plan["items"][0]["fieldDispositions"].pop()

    invalid = service.preview(plan)
    assert invalid["errorCode"] == "research_merge_plan_invalid"

    plan = _plan(legacy_id, current_id, current)
    preview = service.preview(plan)
    assert preview["status"] == "preview_ready", preview
    stale = service.apply(
        plan,
        expected_memory_revision=preview["expectedMemoryRevision"] + 1,
        merge_plan_hash=preview["mergePlanHash"],
        user_approved=True,
    )
    assert stale["errorCode"] == "research_merge_preview_stale"


def test_merge_requires_primary_research_when_reviewer_is_uncertain(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite"
    legacy_id, current_id, current = _seed(db_path)
    service = research_merge.ResearchMergeService(db_path)
    plan = _plan(legacy_id, current_id, current)
    plan["items"][0]["requiresExternalResearch"] = True

    result = service.preview(plan)

    assert result["errorCode"] == "research_merge_plan_invalid"


def test_merge_disables_successor_rows_for_same_knowledge_updates(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite"
    legacy_id, current_id, current = _seed(db_path)
    service = research_merge.ResearchMergeService(db_path)
    plan = _plan(legacy_id, current_id, current)
    plan["items"][0]["action"] = "create_successor"

    result = service.preview(plan)

    assert result["errorCode"] == "research_merge_plan_invalid"


def test_deprecate_incorrect_requires_a_distinct_corrected_identity(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite"
    legacy_id, current_id, current = _seed(db_path)
    service = research_merge.ResearchMergeService(db_path)
    plan = _plan(legacy_id, current_id, current)
    plan["items"][0]["action"] = "deprecate_incorrect"

    result = service.preview(plan)

    assert result["errorCode"] == "research_merge_plan_invalid"
