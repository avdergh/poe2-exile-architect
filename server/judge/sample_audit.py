"""Shared sample-audit helpers for Judge calibration scripts."""

from __future__ import annotations

from collections import Counter
from typing import Any


SOURCE_DATA_PROBLEM_CAVEATS = {
    "source_data_problem_caveat",
}

UNSOLVED_GAP_CAVEATS = {
    "state_or_import_suspect_caveat",
    "defense_state_unverified_caveat",
    "trusted_reference_attribute_requirement_mismatch_caveat",
    "external_multi_active_socket_group_caveat",
}


def finalize_sample_classification(sample: dict[str, Any]) -> dict[str, Any]:
    out = dict(sample)
    caveats = set(out.get("caveats") or [])
    if out.get("finalClassification") == "source_data_problem" or (
        caveats & SOURCE_DATA_PROBLEM_CAVEATS
    ):
        out["scoreReviewNeeded"] = False
        out["finalClassification"] = "source_data_problem"
        return out
    if out.get("playabilityFailures"):
        out["scoreReviewNeeded"] = False
        out["finalClassification"] = "severe_playability_failure"
        return out
    if not out.get("pass"):
        out["scoreReviewNeeded"] = False
        failures = set(out.get("hardFailures") or [])
        caveats = set(out.get("caveats") or [])
        if out.get("finalClassification") == "source_data_problem":
            return out
        if caveats & SOURCE_DATA_PROBLEM_CAVEATS:
            out["finalClassification"] = "source_data_problem"
        elif "pob_compute_failed" in failures:
            out["finalClassification"] = "judge_unsolved_modelability_gap"
        elif caveats & UNSOLVED_GAP_CAVEATS:
            out["finalClassification"] = "judge_unsolved_modelability_gap"
        elif failures:
            out["finalClassification"] = "real_legality_failure"
        else:
            out["finalClassification"] = "judge_unsolved_modelability_gap"
        return out

    reasons: list[str] = []
    score_unavailable = (
        (out.get("scoreApplicability") or {}).get("status") == "unavailable"
    )
    aggregate = float((out.get("aggregateScore") or {}).get("value") or 0.0)
    if not score_unavailable and aggregate < 0.5:
        reasons.append("aggregate_below_0_5")
    vector = out.get("scoreVector") or {}
    for key in ("offense", "defense", "recovery", "mobility"):
        if score_unavailable and key == "offense":
            continue
        value = float((vector.get(key) or {}).get("value") or 0.0)
        if value < 0.5:
            reasons.append(f"{key}_below_0_5")

    if score_unavailable and not reasons:
        out["scoreReviewNeeded"] = False
        out["finalClassification"] = "judge_pass_numeric_evidence_limited"
        return out

    out["scoreReviewNeeded"] = bool(reasons)
    if reasons:
        unresolved = _resolve_review_reasons(out, reasons)
        out["scoreReviewReasons"] = list(unresolved)
        if not unresolved:
            out["scoreReviewNeeded"] = False
            out["finalClassification"] = (
                "judge_offense_evidence_gap"
                if _has_offense_evidence_gap(out)
                else "judge_pass_and_scores_explained"
            )
        elif _explained_as_real_low(out, unresolved):
            out["scoreReviewNeeded"] = False
            out["finalClassification"] = "judge_pass_and_scores_explained"
        else:
            out["finalClassification"] = "judge_score_review_required"
    else:
        out["finalClassification"] = "judge_pass_and_scores_explained"
    return out


def summarize_results(samples: list[dict[str, Any]]) -> dict[str, Any]:
    classification_counts = Counter(
        str(sample.get("finalClassification") or "unknown") for sample in samples
    )
    pass_count = sum(1 for sample in samples if sample.get("pass"))
    score_review_count = sum(1 for sample in samples if sample.get("scoreReviewNeeded"))
    return {
        "sampleCount": len(samples),
        "passCount": pass_count,
        "scoreReviewCount": score_review_count,
        "classifications": dict(classification_counts),
    }


def _resolve_review_reasons(sample: dict[str, Any], reasons: list[str]) -> list[str]:
    unresolved = set(reasons)
    if "offense_below_0_5" in unresolved and _offense_gap_explained(sample):
        unresolved.remove("offense_below_0_5")
    if "defense_below_0_5" in unresolved and _defense_gap_explained(sample):
        unresolved.remove("defense_below_0_5")
    if "recovery_below_0_5" in unresolved and _recovery_gap_explained(sample):
        unresolved.remove("recovery_below_0_5")
    if "mobility_below_0_5" in unresolved and _mobility_gap_explained(sample):
        unresolved.remove("mobility_below_0_5")
    if "aggregate_below_0_5" in unresolved and not unresolved.intersection(
        {"offense_below_0_5", "defense_below_0_5", "recovery_below_0_5", "mobility_below_0_5"}
    ):
        unresolved.remove("aggregate_below_0_5")
    return [reason for reason in reasons if reason in unresolved]


def _offense_gap_explained(sample: dict[str, Any]) -> bool:
    offense = (sample.get("scoreBreakdown") or {}).get("offense") or {}
    evidence = str(offense.get("evidenceLevel") or "")
    provenance = str(offense.get("provenance") or "")
    caveats = set(sample.get("caveats") or [])
    delivery = str(offense.get("deliveryEvidenceStatus") or "")
    return evidence == "limited" and (
        delivery == "limited"
        or provenance in {"isolated_full_dps_rollup", "minion_pob_output"}
        or "limited_offense_floor_unverified_caveat" in caveats
        or "full_dps_rollup_caveat" in caveats
    )


def _has_offense_evidence_gap(sample: dict[str, Any]) -> bool:
    offense = (sample.get("scoreBreakdown") or {}).get("offense") or {}
    evidence = str(offense.get("evidenceLevel") or "")
    delivery = str(offense.get("deliveryEvidenceStatus") or "")
    value = float(offense.get("value") or 0.0)
    return value < 0.5 and (evidence == "limited" or delivery == "limited")


def _defense_gap_explained(sample: dict[str, Any]) -> bool:
    breakdown = (sample.get("scoreBreakdown") or {}).get("defense") or {}
    policy = str(breakdown.get("scorePolicy") or "")
    avoidance = (sample.get("defenseModel") or {}).get("avoidanceModel") or {}
    evade = float(avoidance.get("evadeChance") or 0.0)
    ehp = float(
        ((sample.get("defenseModel") or {}).get("hitMitigationModel") or {}).get("totalEHP") or 0.0
    )
    phys = float(
        (((sample.get("scoreBreakdown") or {}).get("physical") or {}).get("rawValue")) or 0.0
    )
    if policy == "avoidance_evasion_hybrid":
        return True
    return evade >= 40.0 and ehp >= 15_000.0 and 3_000.0 <= phys <= 6_500.0


def _recovery_gap_explained(sample: dict[str, Any]) -> bool:
    recovery = (sample.get("scoreBreakdown") or {}).get("recovery") or {}
    diagnostics = recovery.get("diagnostics") or {}
    primary_pool = float(recovery.get("primaryPool") or 0.0)
    raw_recovery = float(recovery.get("rawValue") or 0.0)
    quality_floor = float(recovery.get("qualityFloor") or 0.0)
    offense = (sample.get("scoreBreakdown") or {}).get("offense") or {}
    evidence = str(offense.get("evidenceLevel") or "")
    mana = float(diagnostics.get("Mana") or 0.0)
    return (
        evidence == "limited"
        and primary_pool <= 4_500.0
        and raw_recovery <= quality_floor
        and mana >= primary_pool * 0.25
    )


def _mobility_gap_explained(sample: dict[str, Any]) -> bool:
    mobility = (sample.get("scoreBreakdown") or {}).get("mobility") or {}
    policy = str(mobility.get("scorePolicy") or "")
    raw = float(mobility.get("rawValue") or 0.0)
    offense = (sample.get("scoreBreakdown") or {}).get("offense") or {}
    evidence = str(offense.get("evidenceLevel") or "")
    if policy in {"skill_speed_overlay", "skill_speed_fallback"}:
        return True
    return evidence == "limited" and 1.0 <= raw <= 1.1


def _explained_as_real_low(sample: dict[str, Any], reasons: list[str]) -> bool:
    for reason in reasons:
        if reason == "offense_below_0_5" and not _offense_real_low(sample):
            return False
        if reason == "defense_below_0_5" and not _defense_real_low(sample):
            return False
        if reason == "recovery_below_0_5" and not _recovery_real_low(sample):
            return False
        if reason == "mobility_below_0_5" and not _mobility_real_low(sample):
            return False
        if reason == "aggregate_below_0_5":
            continue
    return True


def _offense_real_low(sample: dict[str, Any]) -> bool:
    offense = (sample.get("scoreBreakdown") or {}).get("offense") or {}
    return str(offense.get("evidenceLevel") or "") == "strong"


def _defense_real_low(sample: dict[str, Any]) -> bool:
    breakdown = (sample.get("scoreBreakdown") or {}).get("defense") or {}
    policy = str(breakdown.get("scorePolicy") or "")
    avoidance = (sample.get("defenseModel") or {}).get("avoidanceModel") or {}
    evade = float(avoidance.get("evadeChance") or 0.0)
    ehp = float(
        ((sample.get("defenseModel") or {}).get("hitMitigationModel") or {}).get("totalEHP") or 0.0
    )
    phys = float(
        (((sample.get("scoreBreakdown") or {}).get("physical") or {}).get("rawValue")) or 0.0
    )
    return policy == "max_hit_shortboard" and evade < 40.0 and phys <= 6_500.0 and ehp < 16_000.0


def _recovery_real_low(sample: dict[str, Any]) -> bool:
    recovery = (sample.get("scoreBreakdown") or {}).get("recovery") or {}
    primary_pool = float(recovery.get("primaryPool") or 0.0)
    raw_recovery = float(recovery.get("rawValue") or 0.0)
    quality_floor = float(recovery.get("qualityFloor") or 0.0)
    return primary_pool > 0.0 and raw_recovery <= max(quality_floor * 1.25, quality_floor + 10.0)


def _mobility_real_low(sample: dict[str, Any]) -> bool:
    mobility = (sample.get("scoreBreakdown") or {}).get("mobility") or {}
    raw = float(mobility.get("rawValue") or 0.0)
    policy = str(mobility.get("scorePolicy") or "")
    return policy == "movement_speed" and raw < 1.2
