"""独立审查补充：共享结论的结构化主题更正也必须保持来源隔离。"""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest

from server.knowledge import mature_learning, research_claims, research_memory, research_runtime
from test_patch_reviews import query, seeded
from test_research_memory import _family_deep_payload, _graph_service


def _claim_revision(result):
    write = result["recordWrites"][0]
    return {
        "knowledge_key": write["knowledgeKey"],
        "record_id": write["recordId"],
        "projection_hash": write["afterProjectionHash"],
    }


@pytest.mark.parametrize("correcting_source", ["case:source-a", "case:source-b"])
def test_shared_source_topic_correction_retracts_only_its_old_claim(tmp_path, correcting_source):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    payload = _family_deep_payload(
        title="资源恢复归因复核", group="research:source-a", sources=("case:source-a",)
    )
    payload["schema_version"] = 6
    original = payload["deep_research_records"][0]
    original.update(
        record_schema_version=2,
        source_state_scope="active_state",
        source_claim_key="resource-origin",
        record_kind="resource_engine",
        content="这个来源最初将资源恢复归因为命中恢复。",
        typed_payload={**original["typed_payload"], "resourceMechanisms": ["on_hit_recovery"]},
    )
    first = service.propose_deep_research_records(payload)
    assert first["status"] == "accepted", first
    family = first["buildFamilyKeys"][0]

    other = deepcopy(payload)
    other["deep_research_records"][0].update(
        research_group_id="research:source-b", source_case_refs=["case:source-b"]
    )
    accepted_other = service.propose_deep_research_records(other)
    assert accepted_other["status"] == "accepted", accepted_other
    assert accepted_other["recordIds"] == first["recordIds"]

    correction = deepcopy(payload if correcting_source == "case:source-a" else other)
    corrected = correction["deep_research_records"][0]
    corrected.update(
        content="复核纠正资源归因为药剂恢复，撤回该来源原有的命中恢复结论。",
        typed_payload={**corrected["typed_payload"], "resourceMechanisms": ["flask_recovery"]},
        source_claim_revision=_claim_revision(first),
    )
    accepted = service.propose_deep_research_records(correction)
    assert accepted["status"] == "accepted", accepted
    assert accepted["knowledgeKeys"] != first["knowledgeKeys"]

    def lane(source):
        return query(
            service,
            family,
            patch="0.5.4",
            detail_level="record",
            response_profile="create_compact",
            knowledge_scope="global_seed",
            source_case_ref=source,
        )["deepResearchRecords"]

    retained_source = "case:source-b" if correcting_source == "case:source-a" else "case:source-a"
    corrected_lane = lane(correcting_source)
    retained_lane = lane(retained_source)
    assert [row["content"] for row in corrected_lane] == [corrected["content"]]
    assert [row["content"] for row in retained_lane] == [original["content"]]
    assert corrected_lane[0]["sourceCaseRefs"] == [correcting_source]
    assert retained_lane[0]["sourceCaseRefs"] == [retained_source]
    assert corrected_lane[0]["evidenceCount"] == retained_lane[0]["evidenceCount"] == 1


def test_multiple_source_revisions_can_return_to_an_exact_variant(tmp_path):
    service, payload, first = seeded(tmp_path)
    family = first["buildFamilyKeys"][0]
    other = deepcopy(payload)
    other["deep_research_records"][0]["source_case_refs"] = ["case:other"]
    service.propose_deep_research_records(other)
    for content in ("条件二的安全说明。", "条件三的安全说明。", "条件二的安全说明。"):
        revision = deepcopy(payload)
        revision["deep_research_records"][0]["content"] = content
        result = service.propose_deep_research_records(revision)
        assert result["status"] == "accepted"
        assert result["createdRecordCount"] + result["updatedRecordCount"] == 1
        rows = query(
            service,
            family,
            patch="0.5.4",
            detail_level="record",
            response_profile="create_compact",
            source_case_ref="case:la-safe",
        )["deepResearchRecords"]
        assert [row["content"] for row in rows] == [content]
        assert rows[0]["evidenceCount"] == 1
    reunited = service.propose_deep_research_records(payload)
    assert reunited["updatedRecordCount"] == 1
    assert reunited["recordIds"] == first["recordIds"]


def test_concurrent_shared_source_revisions_keep_both_lanes(tmp_path):
    service, payload, first = seeded(tmp_path)
    family = first["buildFamilyKeys"][0]
    other = deepcopy(payload)
    other["deep_research_records"][0].update(
        source_case_refs=["case:other"], research_group_id="research:other"
    )
    service.propose_deep_research_records(other)
    revised = [deepcopy(payload), deepcopy(other)]
    for number, value in enumerate(revised):
        value["deep_research_records"][0]["content"] = f"并发来源{number}自己的条件修订。"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(service.propose_deep_research_records, revised))
    assert all(value["status"] == "accepted" for value in outcomes)
    for value in revised:
        record = value["deep_research_records"][0]
        page = query(
            service,
            family,
            patch="0.5.4",
            detail_level="record",
            response_profile="create_compact",
            source_case_ref=record["source_case_refs"][0],
        )
        assert len(page["deepResearchRecords"]) == 1
        result = page["deepResearchRecords"][0]
        assert result["content"] == record["content"]
        assert result["evidenceCount"] == 1
        assert result["sourceClaims"] == [
            {
                "sourceCaseRef": record["source_case_refs"][0],
                "sourceClaimKey": "default",
                "bindingIssue": None,
            }
        ]


def test_topic_correction_uses_claim_key_not_other_same_title_branch(tmp_path):
    service, payload, first = seeded(tmp_path)
    family = first["buildFamilyKeys"][0]
    resource = deepcopy(payload)
    record = resource["deep_research_records"][0]
    record.update(
        record_kind="resource_engine",
        title="资源条件复核",
        content="默认命中条件。",
        typed_payload={**record["typed_payload"], "resourceMechanisms": ["on_hit_recovery"]},
    )
    original = service.propose_deep_research_records(resource)
    branch = deepcopy(resource)
    branch["deep_research_records"][0].update(
        source_claim_key="boss", content="另一分支的独立条件。"
    )
    service.propose_deep_research_records(branch)
    corrected = deepcopy(resource)
    corrected["deep_research_records"][0]["typed_payload"]["resourceMechanisms"] = [
        "flask_recovery"
    ]
    corrected["deep_research_records"][0]["content"] = "默认条件已纠正为药剂恢复。"
    corrected["deep_research_records"][0]["source_claim_revision"] = _claim_revision(original)
    service.propose_deep_research_records(corrected)
    records = query(
        service,
        family,
        patch="0.5.4",
        detail_level="record",
        response_profile="create_compact",
        source_case_ref="case:la-safe",
    )["deepResearchRecords"]
    resources = [row for row in records if row["recordKind"] == "resource_engine"]
    assert {row["content"] for row in resources} == {
        "另一分支的独立条件。",
        "默认条件已纠正为药剂恢复。",
    }
    assert all(row["evidenceCount"] == 1 for row in resources)


def test_component_order_normalizes_before_projection_and_source_binding(tmp_path):
    service, payload, first = seeded(tmp_path)
    second = deepcopy(payload)
    record = second["deep_research_records"][0]
    assert len(record["component_keys"]) > 1
    record["component_keys"] = list(reversed(record["component_keys"]))
    record["source_case_refs"] = ["case:reordered"]
    result = service.propose_deep_research_records(second)
    assert result["recordIds"] == first["recordIds"]
    con = mature_learning.connect(service.db_path)
    try:
        row = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id=?", (result["recordIds"][0],)
        ).fetchone()
        assert row["projection_hash"] == research_runtime.projection_hash(row)
        research_claims.validate_storage(con)
    finally:
        con.close()
