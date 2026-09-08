"""纯合成案例：未知证据不得成为 Phase 7 进步信号。"""

from copy import deepcopy

import pytest

from server.learning import comparison, models, service
from test_phase7_comparative_learning import _evidence, _report


def _validate(report):
    return comparison.validate_report(report, expected_case_id="test-case")


def test_original_unknown_critical_gap_counterexample_is_rejected():
    report = _report("test-case", verdict="tradeoff")
    for dimension in report["dimensions"]:
        dimension.update(verdict="unknown", criticalGap=True)
        dimension.pop("generatedEvidenceRefs")
        dimension.pop("referenceEvidenceRefs")
    assert _validate(report)["status"] == "rejected"


@pytest.mark.parametrize("side", ["reference", "generated"])
def test_non_unknown_dimension_needs_both_sides(side):
    report = _report("test-case")
    report["dimensions"][0][f"{side}EvidenceRefs"] = []
    assert _validate(report)["status"] == "rejected"


def test_tradeoff_is_reported_separately_not_automatically_noninferior():
    result = _validate(_report("test-case", verdict="tradeoff"))
    assert result["status"] == "accepted"
    assert result["metrics"]["notWeaker"] is False
    assert result["metrics"]["tradeoff"] is True


def test_unknown_dimensions_are_visible_and_not_trend_eligible():
    report = _report("test-case", verdict="incomparable")
    for dimension in report["dimensions"]:
        dimension["verdict"] = "unknown"
    result = _validate(report)
    assert result["status"] == "accepted"
    assert result["metrics"]["unknownDimensionCount"] == len(models.COMPARISON_DIMENSIONS)
    assert result["metrics"]["comparableDimensionCount"] == 0
    assert result["metrics"]["trendEligible"] is False


@pytest.mark.parametrize("bad_ref", ["safe:reference:other-case", "safe:generated:test-case"])
def test_bound_report_rejects_other_case_or_wrong_side(bad_ref):
    report = _report("test-case")
    report["dimensions"][0]["referenceEvidenceRefs"] = [bad_ref]
    result = comparison.validate_report(
        report,
        expected_case_id="test-case",
        reference_evidence=_evidence("reference", "test-case"),
        generated_evidence=_evidence("generated", "test-case"),
    )
    assert result["status"] == "rejected"


def test_missing_and_legacy_metrics_cannot_show_progress():
    first = dict(
        notWeaker=False,
        referenceAdvantageDimensions=3,
        criticalGapCount=1,
        generatedLegal=True,
        familyMatch=True,
        comparisonCompleted=True,
    )
    last = dict(notWeaker=True, generatedLegal=True, familyMatch=True, comparisonCompleted=True)
    result = comparison.campaign_trend([first] * 7 + [last] * 3)
    assert result["claim"] != "initial_progress_signal"
    assert result["lastThree"]["criticalGapMedian"] is None


def test_saved_metrics_are_not_authority_for_campaign_status(monkeypatch):
    report = _report("test-case")
    report["schemaVersion"] = 1  # legacy report must not silently gain v2 coverage
    forged = dict(
        notWeaker=False,
        referenceAdvantageDimensions=3,
        criticalGapCount=1,
        generatedLegal=True,
        familyMatch=True,
        comparisonCompleted=True,
    )
    case = dict(
        phase="completed",
        metrics=forged,
        caseId="test-case",
        comparison=report,
        referenceEvidence=_evidence("reference", "test-case"),
        generatedEvidence=_evidence("generated", "test-case"),
    )
    cases = [deepcopy(case) for _ in range(10)]
    for row in cases[-3:]:
        row["metrics"].update(notWeaker=True, referenceAdvantageDimensions=0, criticalGapCount=0)
    monkeypatch.setattr(
        service,
        "_read_campaign",
        lambda _: dict(
            campaignId="campaign:test", status="completed", revision=1, caseLimit=10, cases=cases
        ),
    )
    monkeypatch.setattr(service, "_safe_case_status", lambda item: {})
    result = service.campaign_status(campaign_id="campaign:test")
    assert result["trend"]["claim"] != "initial_progress_signal"


def _bound(report):
    return comparison.validate_report(
        report,
        expected_case_id="test-case",
        reference_evidence=_evidence("reference", "test-case"),
        generated_evidence=_evidence("generated", "test-case"),
    )


def _gap():
    return dict(
        gapId="gap:one",
        dimension=models.COMPARISON_DIMENSIONS[0],
        rootCause="insufficient_evidence",
        summary="Synthetic critical gap",
        critical=True,
        safeEvidenceRefs=["safe:reference:test-case"],
    )


@pytest.mark.parametrize(
    "mutation", ["missing_flag", "missing_gap", "duplicate_gap", "wrong_source"]
)
def test_critical_gap_consistency_and_source_binding(mutation):
    report = _report("test-case", verdict="reference_stronger")
    report["dimensions"][0]["criticalGap"] = True
    report["gaps"] = [_gap()]
    if mutation == "missing_flag":
        report["dimensions"][0]["criticalGap"] = False
    elif mutation == "missing_gap":
        report["gaps"] = []
    elif mutation == "duplicate_gap":
        report["gaps"].append(_gap())
    else:
        report["gaps"][0]["safeEvidenceRefs"] = ["evidence:wrong-case"]
    assert _bound(report)["status"] == "rejected"


def test_fully_bound_reports_can_show_directional_progress_but_lost_coverage_cannot():
    before = _report("test-case", verdict="reference_stronger")
    before["dimensions"][0].update(verdict="reference_advantage", criticalGap=True)
    before["gaps"] = [_gap()]
    after = _report("test-case")
    first = {**_bound(before)["metrics"], "comparisonCompleted": True}
    last = {**_bound(after)["metrics"], "comparisonCompleted": True}
    result = comparison.campaign_trend([first] * 7 + [last] * 3)
    assert result["claim"] == "initial_progress_signal"
    assert result["causalProof"] is False
    after["dimensions"][0]["verdict"] = "unknown"
    incomplete = {**_bound(after)["metrics"], "comparisonCompleted": True}
    result = comparison.campaign_trend([first] * 7 + [incomplete] * 3)
    assert result["claim"] != "initial_progress_signal"
    # Even missing evidence in the middle cannot disappear from campaign qualification.
    result = comparison.campaign_trend([first] * 3 + [incomplete] + [first] * 3 + [last] * 3)
    assert result["conditions"]["evidenceCoverageComplete"] is False
    result = comparison.campaign_trend([first] * 3 + [None] + [first] * 3 + [last] * 3)
    assert result["completedCaseCount"] == 10
    assert result["conditions"]["evidenceCoverageComplete"] is False


def test_current_report_rederivation_preserves_other_metrics_and_rejects_tampering():
    case = dict(
        caseId="test-case",
        comparison=_report("test-case"),
        referenceEvidence=_evidence("reference", "test-case"),
        generatedEvidence=_evidence("generated", "test-case"),
        metrics=dict(memoryAdoptedCount=3, referenceAdvantageDimensions=7, notWeaker=False),
    )
    case["comparisonRef"] = _bound(case["comparison"])["reportRef"]
    result = comparison.stored_case_metrics(case)
    assert result["notWeaker"] is True
    assert result["referenceAdvantageDimensions"] == 0
    assert result["memoryAdoptedCount"] == 3
    case["comparison"]["dimensions"][0]["generatedEvidenceRefs"] = ["wrong:case"]
    assert comparison.stored_case_metrics(case)["trendEligible"] is False


def test_report_must_still_match_accepted_content_reference():
    case = dict(
        caseId="test-case",
        comparison=_report("test-case"),
        referenceEvidence=_evidence("reference", "test-case"),
        generatedEvidence=_evidence("generated", "test-case"),
        metrics={},
    )
    assert comparison.stored_case_metrics(case)["trendEligible"] is False
    case["comparisonRef"] = _bound(case["comparison"])["reportRef"]
    assert comparison.stored_case_metrics(case)["trendEligible"] is True
    case["comparison"]["overallVerdict"] = "tradeoff"
    assert comparison.stored_case_metrics(case)["trendEligible"] is False


@pytest.mark.parametrize("value", [None, True, "0", -1, float("nan"), float("inf")])
def test_missing_invalid_gap_metric_does_not_become_zero(value):
    row = {
        **_bound(_report("test-case"))["metrics"],
        "comparisonCompleted": True,
        "criticalGapCount": value,
    }
    result = comparison.campaign_trend([row] * 10)
    assert result["claim"] != "initial_progress_signal"
    assert result["firstThree"]["criticalGapMedian"] is None
