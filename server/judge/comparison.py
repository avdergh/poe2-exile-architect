"""BuildEvaluation comparison contract for selection and reward learning."""

from __future__ import annotations

from typing import Any


def compare_evaluations(candidate: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    candidate_error = bool(candidate.get("errorKind"))
    reference_error = bool(reference.get("errorKind"))
    if candidate_error or reference_error:
        status = (
            "both_evidence_unavailable"
            if candidate_error and reference_error
            else "candidate_evidence_unavailable"
            if candidate_error
            else "reference_evidence_unavailable"
        )
        return _result("unknown", "unknown", status, False, "none")

    candidate_ok = bool(candidate.get("pass"))
    reference_ok = bool(reference.get("pass"))

    if candidate_ok and not reference_ok:
        return _result("candidate", "unknown", "reference_invalid", False, "none")
    if reference_ok and not candidate_ok:
        return _result("reference", "unknown", "candidate_invalid", False, "none")
    if not candidate_ok and not reference_ok:
        return _result("unknown", "unknown", "both_invalid", False, "none")

    if _score_unavailable(candidate) or _score_unavailable(reference):
        return _result("unknown", "unknown", "numeric_evidence_unavailable", False, "none")

    candidate_band = candidate.get("levelBand")
    reference_band = reference.get("levelBand")
    if candidate_band and reference_band and candidate_band != reference_band:
        return _result("unknown", "unknown", "level_band_mismatch", False, "none")

    selection = _higher_score(candidate, reference)
    if _not_rewardable(candidate) or _not_rewardable(reference):
        return _result(selection, "unknown", "non_rewardable", False, "none")
    if _limited_evidence(candidate) or _limited_evidence(reference):
        return _result(selection, "unknown", "limited_evidence", "limited", "limited")
    return _result(selection, selection, "comparable", True, "strong")


def _higher_score(candidate: dict[str, Any], reference: dict[str, Any]) -> str:
    c_score = float((candidate.get("aggregateScore") or {}).get("value") or 0.0)
    r_score = float((reference.get("aggregateScore") or {}).get("value") or 0.0)
    if c_score > r_score:
        return "candidate"
    if r_score > c_score:
        return "reference"
    return "tie"


def _limited_evidence(evaluation: dict[str, Any]) -> bool:
    if evaluation.get("rewardLimitReasons"):
        return True
    if evaluation.get("rewardEligible") == "limited":
        return True
    if evaluation.get("rewardStrength") == "limited":
        return True
    if (evaluation.get("modelability") or {}).get("status") in {"partial", "not_modelable"}:
        return True
    limited_caveats = {
        "lower_bound_dps_caveat",
        "projectile_overlap_unverified_caveat",
        "minion_dps_unverified_caveat",
        "minion_count_multiplier_caveat",
        "full_dps_rollup_caveat",
        "metric_unavailable_caveat",
        "primary_pool_unavailable_caveat",
        "dual_weapon_state_limited_caveat",
    }
    return bool(limited_caveats & set(evaluation.get("caveats") or []))


def _score_unavailable(evaluation: dict[str, Any]) -> bool:
    return (evaluation.get("scoreApplicability") or {}).get("status") == "unavailable"


def _not_rewardable(evaluation: dict[str, Any]) -> bool:
    return evaluation.get("rewardEligible") is False or evaluation.get("rewardStrength") == "none"


def _result(
    selection: str,
    reward: str,
    status: str,
    eligible: Any,
    reward_strength: str,
) -> dict[str, Any]:
    return {
        "selectionWinner": selection,
        "rewardWinner": reward,
        "comparisonStatus": status,
        "rewardEligible": eligible,
        "rewardStrength": reward_strength,
    }
