"""已排除的来源辅助不能改走模式、语义边或正文进入知识库。"""

from copy import deepcopy

import pytest

from scripts import run_phase4_deep_review_acceptance as acceptance
from tests.test_research_confirmed_support_exclusions import _record, _review
from tests.test_research_support_source_context import SUPPORTS, graph, group


VERSION = {
    "gamePatch": "0.5.5",
    "passiveTreeVersion": "0_5",
    "pobVersionOrCommit": "fixture",
}
REASON = "excluded_incompatible_source_support"


def _case(*, valid_elsewhere=False, retain_elsewhere=True, content=None):
    service = graph()
    bad = group("group:bad", supports=("Host", "Damage"))
    sources = [bad]
    records = [_record(bad, ("Host",))]
    records[0]["title"] = "宿主的有效辅助"
    if content is not None:
        records[0]["content"] = content
    dispositions = {bad["groupRef"]: "packaged"}
    if valid_elsewhere:
        good = group("group:good", root="PayloadBPlayer", supports=("Damage",))
        sources.append(good)
        dispositions[good["groupRef"]] = "packaged"
        if retain_elsewhere:
            records.append(_record(good, ("Damage",)))
            records[-1]["title"] = "另一技能的有效辅助"
    manifest = {"activeSkillGroups": sources}
    review = _review(sources, records, dispositions)
    resolutions = acceptance._source_skill_id_resolutions(
        graph_service=service, source_skill_manifest=manifest
    )
    compatibility = acceptance._source_support_compatibility_diagnostics(
        graph_service=service,
        source_skill_manifest=manifest,
        source_skill_resolutions=resolutions,
    )
    payload, kept, deferred = acceptance._build_deep_record_payload(
        graph_service=service,
        review=review,
        reviewed_mappings={},
        confirmed_review_components={},
        source_skill_resolutions=resolutions,
        source_skill_manifest=manifest,
        version_context=VERSION,
    )
    assert not deferred
    payload, kept, deferred = (
        acceptance._filter_records_with_unsupported_structured_support_packages(
            graph_service=service,
            source_skill_manifest=manifest,
            deep_payload=payload,
            accepted_records=kept,
        )
    )
    assert not deferred
    payload, kept, deferred = acceptance._filter_records_with_unsupported_source_supports(
        deep_payload=payload, accepted_records=kept, diagnostics=compatibility
    )
    assert not deferred
    evidence = acceptance._source_skill_evidence_diagnostics(
        review=review,
        source_skill_manifest=manifest,
        accepted_records=kept,
        graph_service=service,
        source_skill_resolutions=resolutions,
        support_compatibility_diagnostics=compatibility,
    )
    exclusions = evidence["excludedIncompatibleSupportPairs"]
    assert len(exclusions) == 1 and exclusions[0]["supportKey"] == SUPPORTS["Damage"]
    return {
        "service": service,
        "review": review,
        "manifest": manifest,
        "payload": payload,
        "exclusions": exclusions,
        "pairs": acceptance._unretained_excluded_support_pairs(exclusions, kept),
        "keys": acceptance._unretained_excluded_support_keys(exclusions, kept),
    }


def _pattern(case, keys, *, enforce_exclusions=True):
    names = {node.stable_key: node.display_name for node in case["service"].snapshot.nodes}
    candidate = {
        "sampleId": "fixture",
        "caseRef": "source-hash:fixture",
        "safeEvidenceRefs": ["evidence:fixture"],
        "patternType": "cooccurrence",
        "title": "来源组合观察",
        "summary": "只记录本来源中的组件组合。",
        "axes": ["primary_skill_package"],
        "components": [
            {
                "candidateName": names[key],
                "componentKey": key,
                "resolverQuery": key,
                "role": "support_modifier" if key.startswith("support:") else "secondary_skill",
            }
            for key in keys
        ],
        "plannerHint": "先核对来源组合的使用条件。",
        "verificationGate": "验证精确来源。",
        "verificationTasks": ["复核实际辅助效果。"],
        "claimScopeReview": {
            "evidenceScope": "current_case",
            "claimScope": "case_only",
            "verdict": "supported",
            "reason": "仅陈述本来源。",
            "safeEvidenceRefs": ["evidence:fixture"],
        },
    }
    return acceptance._build_payload(
        graph_service=case["service"],
        review={"safeArtifactOnly": True, "candidateReviews": [candidate]},
        reviewed_mappings={},
        confirmed_review_components={},
        source_skill_resolutions={},
        source_skill_manifest=case["manifest"],
        version_context=VERSION,
        origin_family_by_case_ref={},
        source_specific_components_by_case_ref={},
        component_transfer_allowed=True,
        excluded_source_support_pairs=case["pairs"] if enforce_exclusions else set(),
        excluded_source_support_keys=case["keys"] if enforce_exclusions else set(),
    )


def _claim_issues(case, *, deep=None, patterns=None, observations=None, edges=None):
    payloads = {
        "deep_payload": {"deep_research_records": deep or []},
        "pattern_payload": {
            "patterns": patterns or [],
            "build_design_observations": observations or [],
        },
        "edge_payload": {"semantic_edges": edges or []},
    }
    before = deepcopy(payloads)
    issues = acceptance._excluded_support_claim_issues(
        **payloads,
        excluded_support_keys=case["keys"],
        exclusions=case["exclusions"],
        graph_service=case["service"],
    )
    assert payloads == before, "验收必须拒绝原声明，不能自动改写正文"
    return issues


def test_excluded_support_only_pattern_cannot_avoid_root_pair_filter():
    case = _case()
    keys = [SUPPORTS["Host"], SUPPORTS["Damage"]]
    assert len(_pattern(case, keys, enforce_exclusions=False)[0]["patterns"]) == 1
    payload, _, _, _, deferred = _pattern(case, keys)
    assert not payload["patterns"] and not payload["build_design_observations"]
    assert deferred[0]["reason"] == REASON


@pytest.mark.parametrize("field", ["source_key", "target_key", "rationale"])
def test_non_root_edge_or_rationale_cannot_reintroduce_excluded_support(field):
    case = _case()
    edge = {
        "source_key": "skill:PayloadAPlayer",
        "target_key": "skill:PayloadBPlayer",
        "rationale": "两个独立效果的关系待观察。",
    }
    edge[field] = "Damage 不适用。" if field == "rationale" else SUPPORTS["Damage"]
    issues = _claim_issues(case, edges=[edge])
    assert len(issues) == 1
    assert issues[0]["reason"] == REASON
    assert issues[0]["candidateKind"] == "semantic_edge"


@pytest.mark.parametrize(
    "claim",
    [
        "HostPlayer 用作触发宿主。Damage 提升输出。",
        "HostPlayer 用作触发宿主。Damage 与本组不兼容，不应选用。",
    ],
)
def test_split_sentence_and_negative_explanations_are_not_durable_knowledge(claim):
    case = _case(content=claim)
    records = case["payload"]["deep_research_records"]
    assert records[0]["content"] == claim
    issues = _claim_issues(case, deep=records)
    assert len(issues) == 1 and issues[0]["reason"] == REASON
    assert issues[0]["componentKeys"] == [SUPPORTS["Damage"]]


@pytest.mark.parametrize(
    "field,value",
    [
        ("summary", "Damage 已从本组排除。"),
        ("conditions", ["启用 Damage 才成立。"]),
        ("failure_conditions", ["Damage 不能作用于原宿主。"]),
    ],
)
def test_deep_summary_and_conditions_cannot_preserve_excluded_identity(field, value):
    case = _case()
    record = deepcopy(case["payload"]["deep_research_records"][0])
    record[field] = value
    assert _claim_issues(case, deep=[record])[0]["reason"] == REASON


@pytest.mark.parametrize("channel", ["patterns", "observations"])
def test_pattern_prose_and_single_component_observations_are_checked(channel):
    case = _case()
    item = {"component_keys": [SUPPORTS["Host"]], "summary": "Damage 提升输出。"}
    assert _claim_issues(case, **{channel: [item]})[0]["reason"] == REASON


def test_valid_other_group_authorizes_its_use_without_licensing_original_bad_pair():
    case = _case(valid_elsewhere=True)
    assert SUPPORTS["Damage"] not in case["keys"]
    assert ("skill:HostPlayer", SUPPORTS["Damage"]) in case["pairs"]
    payload, _, _, _, deferred = _pattern(case, ["skill:PayloadBPlayer", SUPPORTS["Damage"]])
    assert len(payload["patterns"]) == 1 and not deferred
    assert not _claim_issues(case, deep=case["payload"]["deep_research_records"])
    payload, _, _, _, deferred = _pattern(case, ["skill:HostPlayer", SUPPORTS["Damage"]])
    assert not payload["patterns"] and deferred[0]["reason"] == REASON


def test_unretained_compatible_source_group_cannot_release_key_level_block():
    case = _case(valid_elsewhere=True, retain_elsewhere=False)
    assert SUPPORTS["Damage"] in case["keys"]
    payload, _, _, _, deferred = _pattern(case, ["skill:PayloadBPlayer", SUPPORTS["Damage"]])
    assert not payload["patterns"] and deferred[0]["reason"] == REASON


def test_legal_other_group_does_not_license_wrong_group_split_sentence_claim():
    case = _case(
        valid_elsewhere=True,
        content="HostPlayer 用作触发宿主。Damage 提升这组技能的输出。",
    )
    assert SUPPORTS["Damage"] not in case["keys"]
    assert ("skill:HostPlayer", SUPPORTS["Damage"]) in case["pairs"]
    issues = _claim_issues(case, deep=case["payload"]["deep_research_records"])
    assert len(issues) == 1 and issues[0]["reason"] == REASON


def test_exact_name_guard_does_not_reject_unrelated_larger_word():
    case = _case()
    assert not _claim_issues(case, deep=[{"content": "Damageable 是另一个测试标识。"}])


@pytest.mark.parametrize("channel", ["deep_prose", "edge_endpoint", "edge_rationale"])
def test_residual_exclusion_blocks_entire_acceptance_preview(tmp_path, monkeypatch, channel):
    monkeypatch.setattr(acceptance, "_local_certified_version_context", lambda: dict(VERSION))
    case = _case()
    review = deepcopy(case["review"])
    review["memoryUse"] = {"queries": []}
    if channel == "deep_prose":
        review["deepResearchRecords"][0]["content"] = (
            "HostPlayer 用作触发宿主。Damage 与本组不兼容。"
        )
    else:
        review["semanticEdges"] = [
            {
                "source_key": "skill:PayloadAPlayer",
                "target_key": (
                    SUPPORTS["Damage"] if channel == "edge_endpoint" else "skill:PayloadBPlayer"
                ),
                "rationale": "Damage 与另一个效果的关系。",
            }
        ]
    report = acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "unused-memory.sqlite",
        json_output=tmp_path / "unused-report.json",
        md_output=tmp_path / "unused-report.md",
        primary_mapping_report=None,
        secondary_mapping_report=None,
        graph_service=case["service"],
        source_skill_manifest=case["manifest"],
        review_payload=review,
        validation_only=True,
    )
    assert report["status"] == "rejected", report
    assert report["acceptanceMode"] == "blocked"
    assert any(item["reason"] == REASON for item in report["deferredCandidates"])
    assert report["acceptedPatternCount"] == report["acceptedDeepRecordCount"] == 0
    assert not (tmp_path / "unused-memory.sqlite").exists()
    assert not (tmp_path / "unused-report.json").exists()
