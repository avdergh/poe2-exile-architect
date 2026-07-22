"""Validation and descriptive metrics for Phase 7 comparisons."""

from __future__ import annotations

import hashlib
import json
import statistics
from typing import Any

from pydantic import ValidationError

from . import models


NOT_WEAKER = {"generated_stronger", "tradeoff"}


def validate_report(payload: dict[str, Any], *, expected_case_id: str) -> dict[str, Any]:
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
    data = report.model_dump(mode="json", by_alias=True)
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "status": "accepted",
        "report": data,
        "reportRef": f"comparison:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]}",
        "metrics": case_metrics(report),
        "winnerSource": "external_comparator",
        "judgeAdvisoryOnly": True,
        "containsRawMaterial": False,
    }


def case_metrics(report: models.BuildComparisonReport) -> dict[str, Any]:
    reference_advantages = sum(item.verdict == "reference_advantage" for item in report.dimensions)
    critical_gaps = sum(item.critical for item in report.gaps)
    judge_values = list(report.judge_advisory.values())
    return {
        "overallVerdict": report.overall_verdict,
        "notWeaker": report.overall_verdict in NOT_WEAKER,
        "referenceAdvantageDimensions": reference_advantages,
        "criticalGapCount": critical_gaps,
        "familyMatch": report.family_match,
        "levelMatch": report.level_match,
        "generatedLegal": report.generated_legal,
        "judgeAvailable": bool(judge_values) and all(item.available for item in judge_values),
        "modelabilityAvailable": bool(judge_values)
        and all(item.modelability not in {"unknown", "unavailable"} for item in judge_values),
    }


def campaign_trend(completed_case_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the fixed first-three/last-three descriptive Phase 7 trend."""

    rows = [item for item in completed_case_metrics if isinstance(item, dict)]
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
        "notWeakerRateIncreased": last["notWeakerRate"] > first["notWeakerRate"],
        "referenceAdvantageMedianDecreased": (
            last["referenceAdvantageMedian"] < first["referenceAdvantageMedian"]
        ),
        "criticalGapDidNotIncrease": last["criticalGapMedian"] <= first["criticalGapMedian"],
        "legalityDidNotRegress": last["legalRate"] >= first["legalRate"],
        "familyMatchDidNotRegress": last["familyMatchRate"] >= first["familyMatchRate"],
    }
    improved = all(conditions.values())
    return {
        "status": "evaluated",
        "completedCaseCount": len(rows),
        "rollingWindow": 3,
        "firstThree": first,
        "lastThree": last,
        "middleCaseCount": 4,
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
        "referenceAdvantageMedian": _median(rows, "referenceAdvantageDimensions"),
        "criticalGapMedian": _median(rows, "criticalGapCount"),
        "legalRate": _rate(rows, "generatedLegal", True),
        "familyMatchRate": _rate(rows, "familyMatch", True),
        "comparisonCoverageRate": _rate(rows, "comparisonCompleted", True),
    }


def _rate(rows: list[dict[str, Any]], field: str, expected: Any) -> float:
    if not rows:
        return 0.0
    return sum(item.get(field) is expected for item in rows) / len(rows)


def _median(rows: list[dict[str, Any]], field: str) -> float:
    values = [float(item.get(field, 0)) for item in rows]
    return float(statistics.median(values)) if values else 0.0
