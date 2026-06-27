"""LLM-assisted mature build extraction contracts.

LLM output is useful only as an untrusted research candidate. This module defines the copy-safe
prompt package and validates structured extraction output before any later phase may persist it as
candidate evidence. It intentionally does not call a model provider, change route synthesis, or
promote durable memory.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import copy_safety

SCHEMA_VERSION = 1
EXTRACTION_METHOD = "llm_mature_technique_v1"

VALID_LIFECYCLE = {
    "starter_to_endgame",
    "starter_then_transition",
    "endgame_only",
    "starter_only",
    "unknown_lifecycle",
}
VALID_MODELABILITY = {"full", "partial", "not_modelable", "unknown"}
VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_COPYABILITY = {"low", "medium", "high"}

REQUIRED_TOP_LEVEL = {
    "schemaVersion",
    "sourceCaseId",
    "league",
    "gamePatch",
    "passiveTreeVersion",
    "techniques",
}

REQUIRED_TECHNIQUE_FIELDS = {
    "techniqueName",
    "mechanismSummary",
    "whyItWorks",
    "requiredComponents",
    "thresholdsOrBreakpoints",
    "lifecycleApplicability",
    "starterRisks",
    "transitionGates",
    "skillLinksSummary",
    "passiveTreeAnchors",
    "gearOrUniqueRoles",
    "defensePlan",
    "pobModelability",
    "evidenceRefs",
    "confidence",
    "copyabilityRisk",
}


def validate_llm_extraction_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate an untrusted LLM extraction payload.

    Validation is intentionally conservative: the output must be structured, attributed to a
    source case and patch/tree scope, and free of reconstructable build details. A valid payload is
    still only a low-trust candidate; it is not proof that a technique is correct.
    """
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload_must_be_object"}

    forbidden_paths = copy_safety.find_forbidden_paths(payload)
    if forbidden_paths:
        return {
            "ok": False,
            "error": "copyable_output_field",
            "paths": forbidden_paths,
        }

    copyability_flags = copy_safety.copyability_flags(payload)
    if copyability_flags:
        return {
            "ok": False,
            "error": "copyability_guard_failed",
            "flags": copyability_flags,
        }

    missing_top = sorted(
        key for key in REQUIRED_TOP_LEVEL if copy_safety.is_empty(payload.get(key))
    )
    if missing_top:
        return {"ok": False, "error": "top_level_missing_required_fields", "missing": missing_top}
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        return {"ok": False, "error": "unsupported_schema_version"}

    techniques = payload.get("techniques")
    if not isinstance(techniques, list) or not techniques:
        return {"ok": False, "error": "techniques_required"}
    if len(techniques) > 8:
        return {"ok": False, "error": "too_many_techniques"}

    for index, technique in enumerate(techniques):
        error = _validate_technique(technique)
        if error:
            return {"ok": False, "error": error, "techniqueIndex": index}

    return {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "sourceCaseId": copy_safety.safe_text(payload["sourceCaseId"], limit=120),
        "techniqueCount": len(techniques),
        "extractionMethod": EXTRACTION_METHOD,
    }


def build_extraction_prompt_package(sanitized_case: dict[str, Any]) -> dict[str, Any]:
    """Build a copy-safe prompt package from an already-sanitized mature case.

    The caller must pass only sanitized case fields. This helper also rejects accidental raw fields
    so prompt construction cannot become a bypass around the mature-learning sanitizer.
    """
    if not isinstance(sanitized_case, dict):
        return {"ok": False, "error": "sanitized_case_must_be_object"}
    forbidden_paths = copy_safety.find_forbidden_paths(sanitized_case)
    if forbidden_paths:
        return {
            "ok": False,
            "error": "copyable_prompt_field",
            "paths": forbidden_paths,
        }
    copyability_flags = copy_safety.copyability_flags(sanitized_case)
    if copyability_flags:
        return {
            "ok": False,
            "error": "copyability_guard_failed",
            "flags": copyability_flags,
        }

    safe_case = _prompt_safe_case(sanitized_case)
    system = (
        "You extract high-level Path of Exile 2 build design techniques from sanitized mature "
        "build evidence. Output JSON only. Do not output PoB code. Do not output full gear. "
        "Do not output full passive trees, passive node lists, exact affixes, full gem links, "
        "or copied guide text. Explain mechanisms, thresholds, lifecycle risks, transition gates, "
        "and PoB modelability in non-copyable terms."
    )
    user = (
        "Analyze this sanitized mature build case and return schemaVersion 1 JSON with a "
        "`techniques` array using the required fields. Treat the evidence as a research signal, "
        "not as a build template.\n\n"
        f"Sanitized case:\n{safe_case}"
    )
    return {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "sourceCaseId": safe_case.get("case_id")
        or safe_case.get("caseId")
        or safe_case.get("sourceRef"),
        "messages": [system, user],
        "allowedOutput": sorted(REQUIRED_TECHNIQUE_FIELDS),
    }


def _validate_technique(technique: Any) -> str | None:
    if not isinstance(technique, dict):
        return "technique_must_be_object"

    missing = sorted(
        key for key in REQUIRED_TECHNIQUE_FIELDS if copy_safety.is_empty(technique.get(key))
    )
    if missing:
        return "technique_missing_required_fields"
    if not copy_safety.is_allowed_enum(technique["lifecycleApplicability"], VALID_LIFECYCLE):
        return "invalid_lifecycle_applicability"
    if not copy_safety.is_allowed_enum(technique["pobModelability"], VALID_MODELABILITY):
        return "invalid_pob_modelability"
    if not copy_safety.is_allowed_enum(technique["confidence"], VALID_CONFIDENCE):
        return "invalid_confidence"
    if not copy_safety.is_allowed_enum(technique["copyabilityRisk"], VALID_COPYABILITY):
        return "invalid_copyability_risk"
    if technique["copyabilityRisk"] == "high":
        return "high_copyability_risk"

    for key in (
        "requiredComponents",
        "thresholdsOrBreakpoints",
        "starterRisks",
        "transitionGates",
        "passiveTreeAnchors",
        "gearOrUniqueRoles",
        "evidenceRefs",
    ):
        if not _is_nonempty_string_list(technique.get(key), max_items=12):
            return f"invalid_{key}"
    return None


def _prompt_safe_case(sanitized_case: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "case_id",
        "caseId",
        "sourceRef",
        "source_group_id",
        "source_snapshot_id",
        "class",
        "ascendancy",
        "main_skill",
        "mainSkill",
        "damage_types",
        "damageTypes",
        "delivery_tags",
        "deliveryTags",
        "defense_tags",
        "defenseTags",
        "mechanic_tags",
        "mechanicTags",
        "lifecycle_stage",
        "lifecycleStage",
        "budget_band",
        "budgetBand",
        "pob_modelability",
        "pobModelability",
        "sanitized_keypoints",
        "keypoints",
        "numeric_ranges_or_metrics",
        "numericRangesOrMetrics",
        "evidence_type",
        "evidenceType",
        "league",
        "game_patch",
        "gamePatch",
        "passive_tree_version",
        "passiveTreeVersion",
        "freshness_status",
        "freshnessStatus",
        "compatibility_status",
        "compatibilityStatus",
        "diversity_bucket",
        "diversityBucket",
    }
    safe: dict[str, Any] = {}
    for key, value in sanitized_case.items():
        if key in allowed:
            safe[key] = _truncate_value(value)
    return safe


def _truncate_value(value: Any) -> Any:
    if isinstance(value, str):
        return copy_safety.safe_text(value, limit=400)
    if isinstance(value, list):
        return [_truncate_value(item) for item in value[:12]]
    if isinstance(value, dict):
        return {str(key)[:80]: _truncate_value(child) for key, child in list(value.items())[:16]}
    return value


def _is_nonempty_string_list(value: Any, *, max_items: int) -> bool:
    if not isinstance(value, list) or not value or len(value) > max_items:
        return False
    return all(isinstance(item, str) and item.strip() for item in value)
