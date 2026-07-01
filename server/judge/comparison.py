"""BuildEvaluation comparison contract for selection and reward learning."""

from __future__ import annotations

from typing import Any


def compare_evaluations(candidate: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    candidate_ok = bool(candidate.get("pass"))
    reference_ok = bool(reference.get("pass"))

    if candidate_ok and not reference_ok:
        return _result("candidate", "unknown", "reference_invalid", False, "none")
    if reference_ok and not candidate_ok:
        return _result("reference", "unknown", "candidate_invalid", False, "none")
    if not candidate_ok and not reference_ok:
        return _result("unknown", "unknown", "both_invalid", False, "none")

    if _core_blocked(candidate) or _core_blocked(reference):
        return _result("unknown", "unknown", "incomparable", False, "none")

    selection = _higher_score(candidate, reference)
    if _limited_evidence(candidate) or _limited_evidence(reference):
        return _result(selection, "unknown", "limited_evidence", "limited", "limited")
    if _partial(candidate) or _partial(reference):
        return _result(selection, "unknown", "partial_modelability", "limited", "limited")
    return _result(selection, selection, "comparable", True, "strong")


def _higher_score(candidate: dict[str, Any], reference: dict[str, Any]) -> str:
    c_score = float((candidate.get("aggregateScore") or {}).get("value") or 0.0)
    r_score = float((reference.get("aggregateScore") or {}).get("value") or 0.0)
    if c_score > r_score:
        return "candidate"
    if r_score > c_score:
        return "reference"
    return "tie"


def _core_blocked(evaluation: dict[str, Any]) -> bool:
    modelability = evaluation.get("modelability") or {}
    return bool(modelability.get("coreBlocked")) or modelability.get("status") == "not_modelable"


def _partial(evaluation: dict[str, Any]) -> bool:
    return (evaluation.get("modelability") or {}).get("status") == "partial"


def _limited_evidence(evaluation: dict[str, Any]) -> bool:
    if evaluation.get("rewardEligible") == "limited":
        return True
    if evaluation.get("rewardStrength") == "limited":
        return True
    limited_caveats = {
        "lower_bound_dps_caveat",
        "minion_dps_unverified_caveat",
        "minion_count_multiplier_caveat",
        "full_dps_rollup_caveat",
        "metric_unavailable_caveat",
        "primary_pool_unavailable_caveat",
        "dual_weapon_state_limited_caveat",
    }
    return bool(limited_caveats & set(evaluation.get("caveats") or []))


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
