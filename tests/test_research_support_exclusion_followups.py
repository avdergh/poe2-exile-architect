"""源辅助排除只关闭本来源的明确不适用缺口，不冒充已修复知识。"""

from copy import deepcopy

import pytest

from server.knowledge import research_completion, research_followups as followups
from test_research_acceptance_diagnostics import _clean
import test_research_followups as helpers
from test_research_v3_contracts import _record


REASONS = ("unsupported_structured_skill_support_pair", "unsupported_source_skill_support_pair")
SKILL = "skill:CometPlayer"
SUPPORT = "support:ArcaneTempo"


@pytest.fixture(params=REASONS)
def exclusion_case(tmp_path, request):
    return (*helpers.case.__wrapped__(tmp_path), request.param)


def _origin(case, *, component_keys=None):
    candidate = _record()
    reason = case[4]
    diagnostic = {
        "diagnosticIndex": 0,
        "reason": reason,
        "candidateKind": "deep_research_record",
        "recordKind": candidate["record_kind"],
        "recordSubjectHash": research_completion.record_subject_hash(candidate),
        "componentKeys": component_keys or [SKILL, SUPPORT],
    }
    case[2](
        "support-origin",
        {
            **_clean(),
            "acceptanceMode": "partial_with_deferred",
            "deferredCandidateCount": 1,
            "deferredReasonCounts": {reason: 1},
            "deferredGapSummaries": [diagnostic],
            "caseCoverage": {"supports": "evidence_missing"},
            "caseCoverageGapCount": 1,
            "caseCoverageGaps": ["supports"],
        },
    )
    params = {
        **case[0],
        "run_ref": "research-run:followup-support-origin",
        "sample_id": "case:support-origin",
    }
    state = followups.inspect_followups(**params)
    return params, next(gap for gap in state["gaps"] if gap["kind"] == "deferred")


def _pair(**changes):
    return {
        "groupRef": "skill-set:1:group:2",
        "socketedItemRef": "skill-set:1:group:2:socketed:2",
        "skillKey": SKILL,
        "supportKey": SUPPORT,
        "evaluatedSkillKeys": [SKILL],
        "sourceRefs": ["fixture:v3"],
        "evaluationMode": "support_group_fixed_point",
        "compatibilityStatus": "unsupported",
        "decision": "exclude_incompatible",
        "sourcePairInstanceCount": 1,
        **changes,
    }


def _support(case, name="support-revisit", *, pairs=None, **kwargs):
    return case[2](
        name,
        {
            **_clean(),
            "caseCoverage": {"supports": "covered"},
            "supportCompatibility": {
                "contractVersion": "fixture-support-v2",
                "graphSnapshotId": "snapshot:v3",
                "scope": "static_type_compatibility",
                "excludedSourceSupportPairs": deepcopy(pairs or []),
            },
        },
        record_change={"title": "复核后的正确技能包"},
        context_change={"reResearchScope": "full_case", **kwargs.pop("context_change", {})},
        **kwargs,
    )


def _close(params, gap, support, disposition="not_applicable"):
    return followups.submit_followup_decisions(
        **params,
        expected_revision=0,
        request_id="support-exclusion",
        decisions=[helpers._decision(gap, support, disposition=disposition)],
    )


def test_omitted_deferred_support_cannot_be_called_resolved(exclusion_case):
    params, gap = _origin(exclusion_case)
    result = _close(params, gap, _support(exclusion_case), "resolved")
    assert result["errorCode"] == "followup_support_exclusion_requires_not_applicable"
    assert followups.inspect_followups(**params)["eventCount"] == 0


def test_unconfirmed_exclusion_does_not_close_by_clean_full_case(exclusion_case):
    params, gap = _origin(exclusion_case)
    result = _close(params, gap, _support(exclusion_case))
    assert result["errorCode"] == "followup_support_exclusion_unproven"
    assert followups.inspect_followups(**params)["openGapCount"] == 2


def test_exact_unique_source_exclusion_closes_only_deferred_gap(exclusion_case):
    params, gap = _origin(exclusion_case)
    original = exclusion_case[1].get_research_write_receipt(
        followups.inspect_followups(**params)["originWriteReceiptRef"]
    )
    support = _support(exclusion_case, pairs=[_pair()])
    result = _close(params, gap, support)
    assert result["status"] == "accepted", result
    assert result["closedGapCount"] == 1 and result["openGapCount"] == 1
    assert result["originalResearchCompletion"] == "needs_followup"
    receipt = exclusion_case[1].get_research_write_receipt(support["writeReceiptRef"])
    assert receipt["writtenMapping"]
    assert all(
        SUPPORT not in row["canonicalRecord"]["componentKeys"] for row in receipt["writtenMapping"]
    )
    assert (
        exclusion_case[1].get_research_write_receipt(original["writeReceiptRef"])[
            "acceptanceSummary"
        ]
        == original["acceptanceSummary"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"sourcePairInstanceCount": None},
        {"sourcePairInstanceCount": 0},
        {"sourcePairInstanceCount": 2},
        {"sourcePairInstanceCount": True},
        {"compatibilityStatus": "unknown"},
        {"compatibilityStatus": "supported"},
        {"decision": "unverified"},
        {"evaluationMode": "single_pair"},
        {"groupRef": "skill-set:1:group:3"},
        {"socketedItemRef": ""},
        {"evaluatedSkillKeys": []},
        {"evaluatedSkillKeys": ["skill:OtherPlayer"]},
        {"sourceRefs": []},
        {"skillKey": "skill:OtherPlayer"},
        {"supportKey": "support:Other"},
    ],
)
def test_unknown_cross_instance_or_wrong_pair_exclusion_fails_closed(exclusion_case, changes):
    params, gap = _origin(exclusion_case)
    result = _close(params, gap, _support(exclusion_case, pairs=[_pair(**changes)]))
    assert result["errorCode"] == "followup_support_exclusion_unproven", result
    assert followups.inspect_followups(**params)["eventCount"] == 0


@pytest.mark.parametrize(
    "field",
    [
        "sourcePairInstanceCount",
        "compatibilityStatus",
        "decision",
        "groupRef",
        "socketedItemRef",
        "sourceRefs",
    ],
)
def test_legacy_incomplete_exclusion_cannot_gain_authority(exclusion_case, field):
    params, gap = _origin(exclusion_case)
    pair = _pair()
    pair.pop(field)
    result = _close(params, gap, _support(exclusion_case, pairs=[pair]))
    assert result["errorCode"] == "followup_support_exclusion_unproven", result


def test_same_pair_in_another_source_instance_is_ambiguous(exclusion_case):
    params, gap = _origin(exclusion_case)
    pairs = [
        _pair(),
        _pair(groupRef="skill-set:1:group:3", socketedItemRef="skill-set:1:group:3:socketed:2"),
    ]
    result = _close(params, gap, _support(exclusion_case, pairs=pairs))
    assert result["errorCode"] == "followup_support_exclusion_unproven", result


def test_partial_match_does_not_infer_old_socket_ownership(exclusion_case):
    params, gap = _origin(exclusion_case, component_keys=[SKILL, "skill:OtherPlayer", SUPPORT])
    result = _close(params, gap, _support(exclusion_case, pairs=[_pair()]))
    assert result["errorCode"] == "followup_support_exclusion_unproven", result


def test_every_declared_support_pair_requires_unique_exclusion(exclusion_case):
    second = "support:Other"
    params, gap = _origin(exclusion_case, component_keys=[SKILL, SUPPORT, second])
    incomplete = _support(exclusion_case, name="incomplete-pairs", pairs=[_pair()])
    assert _close(params, gap, incomplete)["errorCode"] == "followup_support_exclusion_unproven"
    complete = _support(
        exclusion_case,
        name="complete-pairs",
        pairs=[
            _pair(),
            _pair(supportKey=second, socketedItemRef="skill-set:1:group:2:socketed:3"),
        ],
    )
    assert _close(params, gap, complete)["status"] == "accepted"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"supplement": True},
        {"context_change": {"reResearchScope": "case"}},
    ],
)
def test_exclusion_requires_explicit_full_case_scope(exclusion_case, kwargs):
    params, gap = _origin(exclusion_case)
    result = _close(params, gap, _support(exclusion_case, pairs=[_pair()], **kwargs))
    assert result["errorCode"] == "followup_complete_acceptance_required", result


def test_confirmed_exclusion_still_cannot_be_called_resolved(exclusion_case):
    params, gap = _origin(exclusion_case)
    result = _close(params, gap, _support(exclusion_case, pairs=[_pair()]), "resolved")
    assert result["errorCode"] == "followup_support_exclusion_requires_not_applicable", result


def test_exclusion_keeps_cross_source_receipt_unauthorized(exclusion_case):
    params, gap = _origin(exclusion_case)
    result = _close(
        params,
        gap,
        _support(
            exclusion_case,
            context_change={
                "sourceSnapshotHash": "c" * 64,
            },
        ),
    )
    assert result["errorCode"] == "followup_source_mismatch_use_successor_evidence"


def test_exclusion_keeps_stale_written_projection_unauthorized(exclusion_case):
    params, gap = _origin(exclusion_case)
    support = _support(exclusion_case, pairs=[_pair()])
    exclusion_case[2](
        "later-record",
        record_change={
            "title": "复核后的正确技能包",
            "content": "后续条件修订不能沿用旧的接受投影。",
        },
    )
    result = _close(params, gap, support)
    assert result["errorCode"] == "followup_support_projection_stale", result


def test_exclusion_does_not_change_covered_support_gap_rule(exclusion_case):
    params, _ = _origin(exclusion_case)
    gap = next(
        item for item in followups.inspect_followups(**params)["gaps"] if item["kind"] == "coverage"
    )
    support = _support(exclusion_case)
    wrong = _close(params, gap, support)
    assert wrong["errorCode"] == "followup_support_coverage_unproven"
    result = _close(params, gap, support, "resolved")
    assert result["status"] == "accepted"
    assert result["closedGapCount"] == 1
    assert result["openGapCount"] == 1
