from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from scripts import create_build
from server.generation import models, prototype
from tests.test_phase5_prototype_models import agent_submission_payload


def estimate():
    return {
        "estimateId": "estimate:fixture:copy-window",
        "subject": "测试技能的复制窗口",
        "estimateScope": "additional_dps",
        "evidenceKind": "agent_estimated",
        "lowerDps": 10000,
        "upperDps": 40000,
        "basis": "使用已审读的测试机制锚点，按复制命中比例和有效持续窗口给出情景范围。",
        "assumptions": ["测试情景假定目标保持在复制范围内。"],
        "sourceRefs": ["reviewed:estimate-fixture"],
        "overlapHandling": "这是额外部分，不包含原始射击；不与其他复制估计直接相加。",
        "limitations": ["这不是实测，也不是概率置信区间。"],
    }


def submission():
    payload = agent_submission_payload()
    candidate = payload["prototypeBuildCandidate"]
    candidate["tool_references"].append({
        "toolName": "get_gem", "queryRef": "reviewed:estimate-fixture",
        "summary": "测试用机制证据。", "evidenceKind": "agent_reviewed",
        "reviewBasis": "这个测试显式声明已审读的机制依据，用于核对粗估字段的证据隔离。",
    })
    candidate["performanceEstimates"] = [estimate()]
    return payload


def test_estimates_are_visible_but_do_not_change_judge_or_state(tmp_path):
    payload = submission()
    baseline = deepcopy(payload)
    baseline["prototypeBuildCandidate"].pop("performanceEstimates")
    before = prototype.validate_and_build_human_review_packet(baseline)
    result = prototype.validate_and_build_human_review_packet(payload)
    assert before["status"] == result["status"] == "accepted"
    packet = result["humanReviewPacket"]
    assert packet["prototypeBuildCandidate"]["performanceEstimates"] == [estimate()]
    for key in ("judgeAdvisoryReport", "transientBuildState", "recommendedNextAction"):
        assert packet[key] == before["humanReviewPacket"][key]
    compact = create_build._compact_review_result(result, run_dir=tmp_path, consumed=False)
    compact_before = create_build._compact_review_result(before, run_dir=tmp_path, consumed=False)
    assert compact["performanceEstimates"] == [estimate()]
    assert compact["performanceEstimateNotice"]
    assert compact["finalJudge"] == compact_before["finalJudge"]
    assert compact["retrySummary"] == compact_before["retrySummary"]
    assert "performanceEstimates" not in packet["judgeAdvisoryReport"]


@pytest.mark.parametrize("field,value", [
    ("lowerDps", -1), ("lowerDps", float("nan")), ("upperDps", float("inf")),
    ("upperDps", 0), ("lowerDps", True), ("upperDps", "100000"),
    ("lowerDps", 50000), ("assumptions", []), ("limitations", []),
    ("overlapHandling", ""), ("evidenceKind", "internal_receipt"),
    ("sourceRefs", ["https://example.com/raw"]),
])
def test_invalid_or_promoted_estimates_are_rejected(field, value):
    value_estimate = estimate()
    value_estimate[field] = value
    with pytest.raises(ValidationError):
        models.AgentDpsEstimate.model_validate(value_estimate)


@pytest.mark.parametrize("case", ["unresolved", "unverified", "duplicate_id"])
def test_candidate_requires_reviewed_estimate_sources_and_unique_ids(case):
    payload = submission()
    candidate = payload["prototypeBuildCandidate"]
    if case == "unresolved":
        candidate["performanceEstimates"][0]["sourceRefs"] = ["missing:source"]
    elif case == "unverified":
        candidate["tool_references"][-1]["evidenceKind"] = "unverified"
        candidate["tool_references"][-1].pop("reviewBasis")
    else:
        candidate["performanceEstimates"].append(estimate())
    assert prototype.validate_and_build_human_review_packet(payload)["status"] == "rejected"


def test_estimate_explanations_remain_inside_copy_safety_boundary():
    payload = submission()
    payload["prototypeBuildCandidate"]["performanceEstimates"][0]["basis"] = (
        '<PathOfBuilding2><Build level="95" /><Skills/><Items/><Tree/></PathOfBuilding2>'
    )
    result = prototype.validate_and_build_human_review_packet(payload)
    assert result["status"] == "rejected"
