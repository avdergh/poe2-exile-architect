"""Structural quality gate for lifecycle build routes.

This module checks whether a route is complete enough to research and present. It does not judge
whether the build is powerful; engine verification and cohort/reference checks still own that.
"""

from __future__ import annotations

from typing import Any

_ENDGAME_STAGES = {"endgame_budget", "endgame_final"}
_TRANSITIONAL_CLASSIFICATIONS = {"starter_then_transition", "endgame_only"}


def audit_lifecycle_route(route: dict[str, Any]) -> dict[str, Any]:
    """Audit structural completeness of a lifecycle route."""
    stages = [stage for stage in route.get("stages") or [] if isinstance(stage, dict)]
    gates = [gate for gate in route.get("transitionGates") or [] if isinstance(gate, dict)]
    stage_ids = {str(stage.get("id") or "") for stage in stages}
    checks = [
        _check(
            "has_campaign_stage", any(stage_id.startswith("campaign") for stage_id in stage_ids)
        ),
        _check("has_maps_entry_stage", "maps_entry" in stage_ids),
        _check("has_endgame_stage", bool(stage_ids & _ENDGAME_STAGES)),
        _check("has_transition_gates", bool(gates)),
        _check("all_stages_have_evidence", _all_stages_have(stages, "evidenceTags")),
        _check("all_stages_have_verification", _all_stages_have_verification(stages)),
        _check(
            "transition_classification_has_endgame_gate",
            _has_endgame_gate(route.get("classification"), gates),
        ),
    ]
    missing = [_missing_code(row["check"]) for row in checks if not row["ok"]]
    warnings = _warnings(route)
    score = max(0, 100 - len(missing) * 15 - len(warnings) * 5)
    return {
        "ok": True,
        "pass": not missing,
        "score": score,
        "missing": missing,
        "warnings": warnings,
        "checks": checks,
        "evidenceTags": ["lifecycle-quality-gate"],
        "note": (
            "This is a structural quality gate, not a power check. Passing means the route is "
            "complete enough to verify, not that the build is strong."
        ),
    }


def _check(name: str, ok: bool) -> dict[str, Any]:
    return {"check": name, "ok": bool(ok)}


def _all_stages_have(stages: list[dict[str, Any]], key: str) -> bool:
    return bool(stages) and all(bool(stage.get(key)) for stage in stages)


def _all_stages_have_verification(stages: list[dict[str, Any]]) -> bool:
    return bool(stages) and all(
        isinstance(stage.get("verification"), dict) and stage["verification"].get("ok")
        for stage in stages
    )


def _has_endgame_gate(classification: Any, gates: list[dict[str, Any]]) -> bool:
    if classification not in _TRANSITIONAL_CLASSIFICATIONS:
        return True
    return any(str(gate.get("toStage") or "") in _ENDGAME_STAGES for gate in gates)


def _missing_code(check: str) -> str:
    return {
        "has_campaign_stage": "missing_campaign_stage",
        "has_maps_entry_stage": "missing_maps_entry_stage",
        "has_endgame_stage": "missing_endgame_stage",
        "has_transition_gates": "missing_transition_gates",
        "all_stages_have_evidence": "missing_stage_evidence_tags",
        "all_stages_have_verification": "missing_stage_verification_plan",
        "transition_classification_has_endgame_gate": "missing_endgame_transition_gate",
    }[check]


def _warnings(route: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    freshness = route.get("freshness") if isinstance(route.get("freshness"), dict) else {}
    if freshness.get("decision") in {None, "", "not_checked"}:
        warnings.append("freshness_not_verified")
    if not route.get("cohortAnalysis"):
        warnings.append("cohort_analysis_missing")
    return warnings
