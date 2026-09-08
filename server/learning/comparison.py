"""Validation and descriptive metrics for Phase 7 comparisons."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from typing import Any

from pydantic import ValidationError

from . import models


METRICS_VERSION = 2


def validate_report(
    payload: dict[str, Any],
    *,
    expected_case_id: str,
    reference_evidence: dict[str, Any] | None = None,
    generated_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a Comparator-authored report without deriving its winner from Judge data."""

    try:
        report = models.BuildComparisonReport.model_validate(payload)
    except ValidationError as exc:
        first: Any = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(part) for part in first.get("loc", ())) or "input"
        return {
            "status": "rejected",
            "errorCode": "invalid_comparison_report",
            "detail": f"{loc}: {first.get('msg', '')}"[:240],
            "containsRawMaterial": False,
        }
    if report.case_id != expected_case_id:
        return {
            "status": "rejected",
            "errorCode": "comparison_case_mismatch",
            "containsRawMaterial": False,
        }
    bound = reference_evidence is not None and generated_evidence is not None
    if reference_evidence is not None or generated_evidence is not None:
        error = _evidence_binding_error(report, reference_evidence, generated_evidence)
        if error:
            return {"status": "rejected", "errorCode": error, "containsRawMaterial": False}
    data = report.model_dump(mode="json", by_alias=True)
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "status": "accepted",
        "report": data,
        "reportRef": f"comparison:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]}",
        "metrics": case_metrics(report, evidence_bound=bound),
        "winnerSource": "external_comparator",
        "judgeAdvisoryOnly": True,
        "containsRawMaterial": False,
    }


def _evidence_binding_error(report, reference_evidence, generated_evidence) -> str | None:
    allowed: dict[str, set[str]] = {}
    for side, payload in (("reference", reference_evidence), ("generated", generated_evidence)):
        try:
            evidence = models.SafeBuildEvidence.model_validate(payload)
        except ValidationError:
            return "comparison_evidence_unavailable"
        if evidence.side != side:
            return "comparison_evidence_side_mismatch"
        allowed[side] = {evidence.evidence_ref, *evidence.safe_evidence_refs}
        for item in report.dimensions:
            if not set(getattr(item, f"{side}_evidence_refs")) <= allowed[side]:
                return "comparison_evidence_reference_mismatch"
    if any(
        not set(item.safe_evidence_refs) <= allowed["reference"] | allowed["generated"]
        for item in report.gaps
    ):
        return "comparison_gap_evidence_mismatch"
    return None


def case_metrics(
    report: models.BuildComparisonReport,
    *,
    evidence_bound: bool = False,
) -> dict[str, Any]:
    reference_advantages = sum(item.verdict == "reference_advantage" for item in report.dimensions)
    critical_gaps = sum(item.critical for item in report.gaps)
    judge_values = list(report.judge_advisory.values())
    unknown = sum(item.verdict == "unknown" for item in report.dimensions)
    return {
        "metricsVersion": METRICS_VERSION,
        "evidenceBound": evidence_bound,
        "unknownDimensionCount": unknown,
        "comparableDimensionCount": len(report.dimensions) - unknown,
        "trendEligible": report.schema_version == 2
        and evidence_bound
        and unknown == 0
        and report.overall_verdict != "incomparable"
        and report.generated_legal is not None
        and report.reference_legal is not None,
        "overallVerdict": report.overall_verdict,
        "notWeaker": report.overall_verdict == "generated_stronger",
        "tradeoff": report.overall_verdict == "tradeoff",
        "referenceAdvantageDimensions": reference_advantages,
        "criticalGapCount": critical_gaps,
        "familyMatch": report.family_match,
        "levelMatch": report.level_match,
        "generatedLegal": report.generated_legal,
        "judgeAvailable": bool(judge_values) and all(item.available for item in judge_values),
        "modelabilityAvailable": bool(judge_values)
        and all(item.modelability not in {"unknown", "unavailable"} for item in judge_values),
    }


def stored_case_metrics(case: dict[str, Any]) -> dict[str, Any]:
    """Revalidate v2 reports against case-owned evidence; never upgrade legacy caches."""
    report = case.get("comparison")
    if isinstance(report, dict) and report.get("schemaVersion") == 2:
        result = validate_report(
            report,
            expected_case_id=str(case.get("caseId") or ""),
            reference_evidence=case.get("referenceEvidence"),
            generated_evidence=case.get("generatedEvidence"),
        )
        if result.get("status") == "accepted" and case.get("comparisonRef") == result.get(
            "reportRef"
        ):
            return {
                **(case.get("metrics") or {}),
                **result["metrics"],
                "comparisonCompleted": True,
                "coverageStatus": "current",
            }
    # Historical diagnostics remain visible; qualification is never inferred from them.
    return {
        **(case.get("metrics") or {}),
        "metricsVersion": None,
        "trendEligible": False,
        "coverageStatus": "legacy_or_unverified",
        "notWeaker": None,
        "evidenceBound": False,
        "unknownDimensionCount": None,
        "comparableDimensionCount": None,
    }


def campaign_trend(completed_case_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the fixed first-three/last-three descriptive Phase 7 trend."""

    # A missing row is an evidence gap, not permission to remove a case from the denominator.
    rows = [item if isinstance(item, dict) else {} for item in completed_case_metrics]
    rolling = [
        _window_metrics(rows[index - 2 : index + 1], ending_at=index + 1)
        for index in range(2, len(rows))
    ]
    if len(rows) < 10:
        return {
            "status": "insufficient_cases",
            "completedCaseCount": len(rows),
            "requiredCaseCount": 10,
            "rollingWindow": 3,
            "rollingMetrics": rolling,
            "claim": "learning_effect_not_evaluated",
        }
    first = _window_metrics(rows[:3], ending_at=3)
    last = _window_metrics(rows[-3:], ending_at=len(rows))
    conditions = {
        "comparisonCoverageComplete": first["comparisonCoverageRate"] == 1.0
        and last["comparisonCoverageRate"] == 1.0,
        "evidenceCoverageComplete": all(_eligible(row) for row in rows),
        "notWeakerRateIncreased": last["notWeakerRate"] > first["notWeakerRate"],
        "referenceAdvantageMedianDecreased": (
            _compare(last["referenceAdvantageMedian"], first["referenceAdvantageMedian"], "lt")
        ),
        "criticalGapDidNotIncrease": _compare(
            last["criticalGapMedian"], first["criticalGapMedian"], "le"
        ),
        "legalityDidNotRegress": last["legalRate"] >= first["legalRate"],
        "familyMatchDidNotRegress": last["familyMatchRate"] >= first["familyMatchRate"],
        "levelMatchDidNotRegress": last["levelMatchRate"] >= first["levelMatchRate"],
    }
    improved = all(conditions.values())
    return {
        "status": "evaluated",
        "completedCaseCount": len(rows),
        "rollingWindow": 3,
        "firstThree": first,
        "lastThree": last,
        "middleCaseCount": len(rows) - 6,
        "conditions": conditions,
        "claim": "initial_progress_signal" if improved else "function_complete_learning_unproven",
        "causalProof": False,
        "rollingMetrics": rolling,
    }


def _window_metrics(rows: list[dict[str, Any]], *, ending_at: int) -> dict[str, Any]:
    count = len(rows)
    return {
        "endingAtCase": ending_at,
        "caseCount": count,
        "notWeakerRate": _rate(rows, "notWeaker", True),
        "tradeoffRate": _rate(rows, "tradeoff", True),
        "unknownDimensionMedian": _median(rows, "unknownDimensionCount"),
        "comparableDimensionMedian": _median(rows, "comparableDimensionCount"),
        "trendEligibleRate": sum(_eligible(row) for row in rows) / count if count else 0.0,
        "referenceAdvantageMedian": _median(rows, "referenceAdvantageDimensions"),
        "criticalGapMedian": _median(rows, "criticalGapCount"),
        "legalRate": _rate(rows, "generatedLegal", True),
        "familyMatchRate": _rate(rows, "familyMatch", True),
        "levelMatchRate": _rate(rows, "levelMatch", True),
        "comparisonCoverageRate": _rate(rows, "comparisonCompleted", True),
    }


def _rate(rows: list[dict[str, Any]], field: str, expected: Any) -> float:
    if not rows:
        return 0.0
    return sum(item.get(field) is expected for item in rows) / len(rows)


def _median(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [item.get(field) for item in rows]
    if not values or any(
        type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in values
    ):
        return None
    return float(statistics.median(values))


def _compare(left: float | None, right: float | None, operator: str) -> bool:
    if left is None or right is None:
        return False
    return left < right if operator == "lt" else left <= right


def _eligible(row: dict[str, Any]) -> bool:
    return (
        row.get("metricsVersion") == METRICS_VERSION
        and row.get("trendEligible") is True
        and row.get("evidenceBound") is True
        and row.get("comparisonCompleted") is True
        and row.get("comparableDimensionCount") == len(models.COMPARISON_DIMENSIONS)
        and row.get("unknownDimensionCount") == 0
        and row.get("familyMatch") is True
        and row.get("levelMatch") is True
        and _median([row], "referenceAdvantageDimensions") is not None
        and _median([row], "criticalGapCount") is not None
    )
