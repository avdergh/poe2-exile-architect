"""Real-effect evaluation guards for mature-build learning.

Creator inputs must stay separated from evaluator-only or holdout evidence. These helpers are
small pre-LLM guards: they reject contaminated creator research payloads and keep evaluator gap
types constrained to a known vocabulary.
"""

from __future__ import annotations

from typing import Any

from . import copy_safety

VALID_GAP_TYPES = {
    "missing_core_mechanism",
    "wrong_lifecycle_classification",
    "unsafe_transition",
    "numeric_underperformance",
    "defense_gap",
    "sustain_gap",
    "budget_unrealistic",
    "pob_modelability_missed",
    "copyability_risk",
    "stale_or_unknown_freshness",
    "novice_explanation_gap",
}

VALID_GAP_SEVERITIES = {"low", "medium", "high", "critical"}


def validate_creator_research_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Reject creator input that contains holdout/evaluator or raw-copyable material."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "creator_input_must_be_object"}

    flags = sorted(
        {
            *_boundary_flags(payload),
            *_raw_field_flags(payload),
            *_copyability_flags(payload),
        }
    )
    if flags:
        return {"ok": False, "error": "creator_input_contamination", "flags": flags}
    return {"ok": True}


def validate_evaluator_gap(gap: dict[str, Any]) -> dict[str, Any]:
    """Validate a structured evaluator gap before it can be used for reflection."""
    if not isinstance(gap, dict):
        return {"ok": False, "error": "gap_must_be_object"}
    gap_type = gap.get("gapType")
    severity = gap.get("severity")
    if not copy_safety.is_allowed_enum(gap_type, VALID_GAP_TYPES):
        return {"ok": False, "error": "invalid_gap_type"}
    if not copy_safety.is_allowed_enum(severity, VALID_GAP_SEVERITIES):
        return {"ok": False, "error": "invalid_gap_severity"}
    if copy_safety.is_empty(gap.get("evidence")) or copy_safety.is_empty(gap.get("fixIdea")):
        return {"ok": False, "error": "gap_missing_evidence_or_fix"}
    if copy_safety.copyability_flags(gap) or copy_safety.find_forbidden_paths(gap):
        return {"ok": False, "error": "gap_copyability_risk"}
    return {"ok": True, "gapType": gap_type, "severity": severity}


def _boundary_flags(value: Any) -> set[str]:
    flags: set[str] = set()
    if isinstance(value, dict):
        visibility = value.get("visibility")
        split = value.get("split")
        if visibility == "evaluator_only":
            flags.add("evaluator_only")
        if split == "eval_holdout":
            flags.add("eval_holdout")
        if visibility == "quarantined":
            flags.add("quarantined")
        if split == "quarantine":
            flags.add("quarantine")
        for child in value.values():
            flags.update(_boundary_flags(child))
    elif isinstance(value, list):
        for child in value:
            flags.update(_boundary_flags(child))
    return flags


def _raw_field_flags(value: Any, *, path: str = "") -> set[str]:
    forbidden_paths = copy_safety.find_forbidden_paths(value, path=path)
    flags: set[str] = set()
    if forbidden_paths:
        flags.add("raw_copyable_field")
    if any(
        any(token in path_text.lower() for token in ("pob", "pastebin", "rawxml"))
        for path_text in forbidden_paths
    ):
        flags.add("raw_pob_code")
    return flags


def _copyability_flags(value: Any) -> set[str]:
    raw_flags = set(copy_safety.copyability_flags(value))
    flags: set[str] = set(raw_flags)
    if "pob_code_like_blob" in raw_flags or "copyable_build_link" in raw_flags:
        flags.add("raw_pob_code")
    return flags
