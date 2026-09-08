"""R1/R2 的合成回归：Family 身份稳定，来源声明与正文修订独立。"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from scripts import run_phase4_deep_review_acceptance as acceptance
from server.knowledge import research_content, research_contracts, research_memory
from server.knowledge import research_models, research_runtime
from test_patch_reviews import query, review_payload, seeded
from test_research_memory import _family_deep_payload, _graph_service


SOURCE_A = "case:la-safe"
SOURCE_B = "case:second-source"


def _variant(payload, *, source=None, **changes):
    result = deepcopy(payload)
    record = result["deep_research_records"][0]
    if source is not None:
        record["source_case_refs"] = [source]
        record["research_group_id"] = "research:" + source.removeprefix("case:")
    record.update(changes)
    return result


def _accept(service, payload):
    result = service.propose_deep_research_records(payload)
    assert result["status"] == "accepted", result
    return result


def _lane(service, family, source, *, scope="global_seed", patch="0.5.4"):
    return query(
        service,
        family,
        patch=patch,
        response_profile="create_compact",
        detail_level="record",
        knowledge_scope=scope,
        source_case_ref=source,
    )


def _assert_lane_content(service, family, source, expected, *, scope="global_seed"):
    result = _lane(service, family, source, scope=scope)
    assert result["selectedSourceCaseRef"] == source, result
    assert result["selectedKnowledgeScope"] == scope, result
    rows = result["deepResearchRecords"]
    assert len(rows) == 1, rows
    assert rows[0]["content"] == expected
    return rows[0]


@pytest.mark.parametrize("same_submission", [False, True])
def test_same_family_conditional_claims_coexist_without_growing_families(
    tmp_path, same_submission
):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    first = _family_deep_payload()
    first["schema_version"] = 6
    first["deep_research_records"][0].update(
        record_schema_version=2,
        source_state_scope="active_state",
        content="这一投射物配套的覆盖收益只在存在可击杀小怪时成立。",
        conditions=["存在可击杀小怪"],
        failure_conditions=["无小怪单体场景缺少该收益"],
    )
    second = _variant(
        first,
        source=SOURCE_B,
        content="这一投射物配套在无小怪单体场景依赖另一项明确前提。",
        conditions=["无小怪且单体命中前提已核对"],
        failure_conditions=["目标离开命中范围时收益不成立"],
    )
    if same_submission:
        combined = deepcopy(first)
        combined["deep_research_records"].extend(second["deep_research_records"])
        accepted = _accept(service, combined)
    else:
        accepted = _accept(service, first)
        other = _accept(service, second)
        assert other["buildFamilyKeys"] == accepted["buildFamilyKeys"]
    assert len(set(accepted["buildFamilyKeys"])) == 1
    family = accepted["buildFamilyKeys"][0]
    all_records = query(service, family, patch="0.5.4", detail_level="record")
    assert len(all_records["buildFamilies"]) == 1
    assert len(all_records["deepResearchRecords"]) == 2
    for payload, source in ((first, SOURCE_A), (second, SOURCE_B)):
        expected = payload["deep_research_records"][0]
        row = _assert_lane_content(service, family, source, expected["content"])
        assert row["conditions"] == expected["conditions"]
        assert row["failureConditions"] == expected["failure_conditions"]
        assert row["evidenceCount"] == 1
        assert row["sourceCaseRefs"] == [source]


def test_one_source_revision_preserves_other_source_original_lane(tmp_path):
    service, payload, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    original_content = payload["deep_research_records"][0]["content"]
    _accept(service, _variant(payload, source=SOURCE_B))
    _assert_lane_content(service, family, SOURCE_B, original_content)

    revised_content = "第一个来源复核后只修正自身场景，第二个来源的原条件和正文保留。"
    revised = _variant(payload, content=revised_content)
    _accept(service, revised)

    retained = _assert_lane_content(service, family, SOURCE_B, original_content)
    updated = _assert_lane_content(service, family, SOURCE_A, revised_content)
    assert retained["sourceCaseRefs"] == [SOURCE_B]
    assert updated["sourceCaseRefs"] == [SOURCE_A]
    assert retained["evidenceCount"] == updated["evidenceCount"] == 1


def test_revised_conclusion_does_not_count_other_source_old_evidence(tmp_path):
    service, payload, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    _accept(service, _variant(payload, source=SOURCE_B))
    revised_content = "来源 A 的后续核查增加独有前提，其他来源没有为这个新结论提供证据。"
    _accept(service, _variant(payload, content=revised_content))

    rows = query(service, family, patch="0.5.4", detail_level="record")["deepResearchRecords"]
    revised = next(row for row in rows if row["content"] == revised_content)
    assert revised["evidenceCount"] == 1
    assert revised["sourceCaseRefs"] == [SOURCE_A]


def test_replayed_source_is_idempotent_and_equal_sources_do_not_expand_reads(tmp_path):
    service, payload, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    original = payload["deep_research_records"][0]
    sources = [SOURCE_A, SOURCE_B, "case:third-source", "case:fourth-source"]
    for source in sources:
        submission = _variant(payload, source=source)
        _accept(service, submission)
        replay = _accept(service, submission)
        assert replay["evidenceAddedCount"] == 0
        assert replay["createdBuildFamilyCount"] == 0

    summary = query(service, family, patch="0.5.4")
    assert len(summary["buildFamilies"]) == 1
    assert len(summary["deepResearchRecords"]) == 1
    assert summary["deepResearchRecords"][0]["evidenceCount"] == len(sources)
    assert summary["deepResearchRecords"][0]["summary"] == original["summary"]
    for source in sources:
        lane = _lane(service, family, source)
        assert lane["selectedSourceCaseRef"] == source
        assert len(lane["deepResearchRecords"]) == 1
        assert lane["deepResearchRecords"][0]["content"] == original["content"]
        assert len(lane["familyRecordCoverage"]) == 1
        assert len(lane["familyRecordCoverage"][0]["requiredDeepReadRecordIds"]) == 1


def test_sources_reconverge_without_duplicate_conclusions_or_evidence(tmp_path):
    service, payload, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    _accept(service, _variant(payload, source=SOURCE_B))
    _accept(service, _variant(payload, content="来源 A 暂时采用不同场景前提并独立保存。"))
    _accept(service, payload)
    _accept(service, payload)

    result = query(service, family, patch="0.5.4", detail_level="record")
    assert len(result["buildFamilies"]) == 1
    assert len(result["deepResearchRecords"]) == 1
    row = result["deepResearchRecords"][0]
    assert row["content"] == payload["deep_research_records"][0]["content"]
    assert row["evidenceCount"] == 2
    assert set(row["sourceCaseRefs"]) == {SOURCE_A, SOURCE_B}
    for source in (SOURCE_A, SOURCE_B):
        _assert_lane_content(service, family, source, row["content"])


def test_source_revision_in_one_scope_cannot_move_other_scope_authority(tmp_path):
    service, payload, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    original_content = payload["deep_research_records"][0]["content"]
    _accept(service, _variant(payload, knowledge_scope="local_user"))
    local_content = "同名本地来源修订了自己的前提，不能替换全局来源保存的机制证据。"
    _accept(service, _variant(payload, knowledge_scope="local_user", content=local_content))

    global_row = _assert_lane_content(service, family, SOURCE_A, original_content)
    local_row = _assert_lane_content(
        service, family, SOURCE_A, local_content, scope="local_user"
    )
    assert global_row["evidenceCount"] == local_row["evidenceCount"] == 1
    assert global_row["recordId"] != local_row["recordId"]


def test_source_revision_in_new_patch_preserves_old_patch_claim(tmp_path):
    service, payload, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    original_content = payload["deep_research_records"][0]["content"]
    future_content = "新补丁对来源 A 的机制前提有独立修订，旧补丁知识保持原样。"
    future = _accept(service, _variant(payload, game_patch="0.5.5", content=future_content))
    assert future["buildFamilyKeys"] == accepted["buildFamilyKeys"]

    old_row = _assert_lane_content(service, family, SOURCE_A, original_content)
    assert old_row["gamePatch"] == "0.5.4"
    exact = query(
        service,
        family,
        patch="0.5.5",
        detail_level="record",
        record_ids=[*accepted["recordIds"], *future["recordIds"]],
    )["deepResearchRecords"]
    assert {(row["gamePatch"], row["content"]) for row in exact} == {
        ("0.5.4", original_content),
        ("0.5.5", future_content),
    }
    assert all(row["evidenceCount"] == 1 for row in exact)


def test_same_source_multiple_topics_are_not_replaced_by_one_source_update(tmp_path):
    service, payload, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    resource_payload = _variant(
        payload,
        record_kind="resource_engine",
        title="命中时恢复资源的条件",
        content="命中恢复只承担命中场景的资源补充职责，恢复量仍需单独验证。",
        typed_payload={
            **payload["deep_research_records"][0]["typed_payload"],
            "resourceMechanisms": ["on_hit_recovery"],
        },
    )
    _accept(service, resource_payload)
    other_resource = _variant(
        resource_payload,
        title="药剂恢复资源的窗口",
        content="药剂恢复承担有充能窗口的资源补充职责，不能假定持续可用。",
        typed_payload={
            **payload["deep_research_records"][0]["typed_payload"],
            "resourceMechanisms": ["flask_recovery"],
        },
    )
    _accept(service, other_resource)
    revised_content = "命中恢复复核后增加目标命中频率条件，其他资源主题不变。"
    _accept(service, _variant(resource_payload, content=revised_content))

    rows = _lane(service, family, SOURCE_A)["deepResearchRecords"]
    assert len(rows) == 3
    assert {row["content"] for row in rows} == {
        payload["deep_research_records"][0]["content"],
        other_resource["deep_research_records"][0]["content"],
        revised_content,
    }
    assert all(row["evidenceCount"] == 1 for row in rows)


@pytest.mark.parametrize("same_submission", [False, True])
def test_explicit_claim_keys_preserve_same_source_conditional_branches(
    tmp_path, same_submission
):
    service, payload, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    conditional = _variant(
        payload,
        source_claim_key="boss-window",
        content="同一案例的无小怪条件分支依赖独立命中窗口，不能覆盖原清图条件。",
        conditions=["无小怪且命中窗口成立"],
        failure_conditions=["目标移出窗口时该分支不成立"],
    )
    if same_submission:
        combined = deepcopy(payload)
        combined["deep_research_records"].extend(conditional["deep_research_records"])
        _accept(service, combined)
    else:
        _accept(service, conditional)
    _accept(service, conditional)

    revised_default = "原清图分支修订只增加覆盖范围前提，无小怪分支保持原条件。"
    _accept(service, _variant(payload, content=revised_default))
    lane = _lane(service, family, SOURCE_A)
    rows = lane["deepResearchRecords"]
    assert {row["content"] for row in rows} == {
        revised_default,
        conditional["deep_research_records"][0]["content"],
    }
    assert len(rows) == 2
    assert all(row["evidenceCount"] == 1 for row in rows)
    assert all(row["sourceCaseRefs"] == [SOURCE_A] for row in rows)
    family_summary = query(service, family, patch="0.5.4")["buildFamilies"]
    assert len(family_summary) == 1
    assert family_summary[0]["evidenceCount"] == 1


def test_undistinguished_conflicting_claims_in_one_submission_fail_atomically(tmp_path):
    service, payload, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    conflicting = deepcopy(payload)
    conflicting["deep_research_records"].extend(
        _variant(payload, content="同一次提交中的另一个不相同结论，没有独立声明键。")
        ["deep_research_records"]
    )

    assert service.validate_deep_research_records(conflicting)["status"] == "rejected"
    assert service.propose_deep_research_records(conflicting)["status"] == "rejected"
    _assert_lane_content(
        service, family, SOURCE_A, payload["deep_research_records"][0]["content"]
    )


def test_different_claim_keys_do_not_fabricate_independent_source_evidence(tmp_path):
    service, payload, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    for claim_key in ("parallel-a", "parallel-b"):
        _accept(service, _variant(payload, source_claim_key=claim_key))
    result = query(service, family, patch="0.5.4", detail_level="record")
    assert len(result["deepResearchRecords"]) == 1
    assert result["deepResearchRecords"][0]["evidenceCount"] == 1
    assert result["deepResearchRecords"][0]["sourceCaseRefs"] == [SOURCE_A]
    assert len(result["buildFamilies"]) == 1
    assert result["buildFamilies"][0]["evidenceCount"] == 1


@pytest.mark.parametrize("claim_key", ["", "Uppercase", "unsafe/branch", "有小怪", "a" * 81, None])
def test_claim_key_rejects_invalid_slugs(claim_key):
    proposal = _family_deep_payload()["deep_research_records"][0]
    with pytest.raises(ValidationError):
        research_models.DeepResearchRecordProposal.model_validate(
            {**proposal, "source_claim_key": claim_key}
        )


def test_claim_key_is_source_binding_metadata_not_shared_content_or_projection():
    proposal = _family_deep_payload()["deep_research_records"][0]
    first = research_models.DeepResearchRecordProposal.model_validate(proposal)
    second = research_models.DeepResearchRecordProposal.model_validate(
        {**proposal, "source_claim_key": "boss-window"}
    )
    assert first.source_claim_key == "default"
    first_fields = first.model_dump(mode="json")
    second_fields = second.model_dump(mode="json")
    assert research_runtime.create_visible_projection(first_fields) == (
        research_runtime.create_visible_projection(second_fields)
    )
    assert research_runtime.projection_hash(first_fields) == research_runtime.projection_hash(
        second_fields
    )
    assert {
        field: first_fields[field] for field in research_content.CONTENT_FIELDS
    } == {field: second_fields[field] for field in research_content.CONTENT_FIELDS}


def _safe_review_record():
    return {
        "sampleId": "sample:claim-fixture",
        "researchGroupId": "research:claim-fixture",
        "caseRef": SOURCE_A,
        "safeEvidenceRefs": ["safe:claim-fixture"],
        "recordKind": "skill_package",
        "title": "主技能覆盖条件",
        "summary": "主技能覆盖的明确条件与验证边界。",
        "content": "主技能覆盖依赖可命中的目标，单体收益需另行实测。",
        "components": [{
            "candidateName": "Lightning Arrow",
            "componentKey": "skill:LightningArrowPlayer",
            "resolverQuery": "skill:LightningArrowPlayer",
            "role": "primary_damage",
            "expectedNodeTypes": ["active_skill"],
            "scope": "player",
        }],
        "ascendancyKey": "ascendancy:monk:martial_artist",
        "sourceStateScope": "active_state",
    }


def _convert_safe_record(record):
    return acceptance._build_deep_record_payload(
        graph_service=_graph_service(),
        review={
            "safeArtifactOnly": True,
            "reviewContractVersion": research_contracts.SAFE_REVIEW_CONTRACT_VERSION,
            "deepResearchRecords": [record],
        },
        reviewed_mappings={},
        confirmed_review_components={},
        source_skill_resolutions={},
        source_skill_manifest=None,
        version_context={
            "gamePatch": "0.5.4",
            "passiveTreeVersion": "0_5",
            "pobVersionOrCommit": "fixture",
        },
    )


@pytest.mark.parametrize("explicit", [False, True])
def test_safe_review_claim_key_reaches_typed_proposal(explicit):
    record = _safe_review_record()
    if explicit:
        record["sourceClaimKey"] = "boss-window"
    payload, accepted, deferred = _convert_safe_record(record)
    assert not deferred, deferred
    assert len(accepted) == len(payload["deep_research_records"]) == 1
    proposal = payload["deep_research_records"][0]
    assert proposal["source_claim_key"] == ("boss-window" if explicit else "default")
    assert "sourceClaimKey" not in proposal["typed_payload"]
    assert "source_claim_key" not in proposal["typed_payload"]


def test_safe_review_invalid_claim_key_is_deferred_with_public_field_path():
    record = {**_safe_review_record(), "sourceClaimKey": "unsafe/branch"}
    payload, accepted, deferred = _convert_safe_record(record)
    assert not accepted and not payload["deep_research_records"]
    issues = [issue for item in deferred for issue in item.get("validationIssues", [])]
    assert any(issue["reviewPath"].endswith("sourceClaimKey") for issue in issues), issues


@pytest.mark.parametrize("outcome", ["invalid", "still_valid"])
def test_shared_content_patch_review_remains_with_b_after_a_revises(tmp_path, outcome):
    service, payload, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    original_content = payload["deep_research_records"][0]["content"]
    _accept(service, _variant(payload, source=SOURCE_B))
    original_b = _assert_lane_content(service, family, SOURCE_B, original_content)
    review = review_payload(service)
    assert review["target_id"] == original_b["recordId"]
    review["outcome"] = outcome
    service.submit_patch_review(review)

    revised_content = "来源 A 的条件经过单独修正，新结论尚未做目标补丁复核。"
    _accept(service, _variant(payload, content=revised_content))

    # B 在来源补丁仍能原样深读；旧正文的目标补丁复核不能迁移至 A 新正文。
    retained_b = _assert_lane_content(service, family, SOURCE_B, original_content)
    assert retained_b["recordId"] == original_b["recordId"]
    b_detail = query(
        service,
        family,
        patch="0.5.5",
        detail_level="record",
        record_ids=[retained_b["recordId"]],
    )["deepResearchRecords"]
    assert len(b_detail) == 1
    expected_status = "incompatible" if outcome == "invalid" else "reviewed_compatible"
    assert b_detail[0]["targetApplicability"]["status"] == expected_status
    a_lane = _lane(service, family, SOURCE_A, patch="0.5.5")
    assert a_lane["selectedSourceCaseRef"] == SOURCE_A
    assert len(a_lane["deepResearchRecords"]) == 1
    updated_a = a_lane["deepResearchRecords"][0]
    assert updated_a["content"] == revised_content
    assert updated_a["recordId"] != retained_b["recordId"]
    assert updated_a["targetApplicability"]["status"] == "historical_unreviewed"
    assert updated_a["evidenceCount"] == 1
    b_lane = _lane(service, family, SOURCE_B, patch="0.5.5")
    if outcome == "invalid":
        assert b_lane["deepResearchRecords"] == []
    else:
        assert len(b_lane["deepResearchRecords"]) == 1
        assert b_lane["deepResearchRecords"][0]["content"] == original_content
