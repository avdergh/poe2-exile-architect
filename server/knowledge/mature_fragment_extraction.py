"""Legacy v3 raw-rich mature research contracts for external agent workflows.

Codex, Claude Code, or another mature agent may inspect richer build material transiently.
This module only builds the research packet and validates the clean fragments that are allowed to
survive after that agent work. It does not call a model provider or run an internal agent loop.

Phase 4's current primary ingestion SOP is the v4 tool-driven flow in
``server/knowledge/research_prompt.py`` plus ``ResearchMemoryService`` proposal tools. This v3
fragment-only helper is retained for legacy fixtures and focused sanitizer checks; do not treat its
"Return one JSON object" prompt as the current MCP write path.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import copy_safety

FRAGMENT_SCHEMA_VERSION = 3

VALID_FRAGMENT_TYPES = {
    "mechanic",
    "gear_role",
    "skill_role",
    "passive_anchor",
    "transition_gate",
    "starter_warning",
    "modelability_caveat",
    "failure_pattern",
    "comparison_note",
    "open_question",
}
VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_COPYABILITY = {"low", "medium", "high"}
VALID_MODELABILITY = {"full", "partial", "not_modelable", "unknown"}

REQUIRED_TOP_LEVEL = {"schemaVersion", "fragments"}
REQUIRED_FRAGMENT_FIELDS = {
    "fragmentType",
    "title",
    "summary",
    "sourceCaseRefs",
    "confidence",
    "copyabilityRisk",
    "reusablePrinciple",
    "verificationTasks",
}
OPTIONAL_LIST_FIELDS = {
    "evidenceRefs",
    "lifecycleStages",
    "componentNames",
    "conditions",
    "risks",
    "notes",
}

_FORBIDDEN_REPORT_LABELS = (
    "pobcode",
    "rawxml",
    "rawpayload",
    "rawjson",
    "rawhtml",
    "supportgems",
    "fullgemlinks",
    "characterurl",
    "profileurl",
    "accountname",
    "charactername",
    "passivetree",
    "passivenodeids",
)


def normalize_extractor_case(case: dict[str, Any], *, index: int | None = None) -> dict[str, Any]:
    """Normalize either a legacy flat case or a new raw-rich case."""
    if not isinstance(case, dict):
        return {"ok": False, "error": "extractor_case_must_be_object"}

    if "safeMetadata" in case or "rawContext" in case:
        safe_metadata = case.get("safeMetadata")
        raw_context = case.get("rawContext")
    else:
        safe_metadata = dict(case)
        raw_context = {}

    if not isinstance(safe_metadata, dict):
        return {"ok": False, "error": "safe_metadata_must_be_object"}
    if raw_context is None:
        raw_context = {}
    if not isinstance(raw_context, dict):
        return {"ok": False, "error": "raw_context_must_be_object"}

    forbidden_paths = copy_safety.find_forbidden_paths(safe_metadata)
    if forbidden_paths:
        return {
            "ok": False,
            "error": "copyable_safe_metadata_field",
            "paths": forbidden_paths,
        }
    copyability_flags = copy_safety.copyability_flags(safe_metadata)
    if copyability_flags:
        return {
            "ok": False,
            "error": "copyability_guard_failed",
            "flags": copyability_flags,
        }

    return {
        "ok": True,
        "extractorCase": {
            "caseRef": _case_ref(safe_metadata, index=index),
            "safeMetadata": safe_metadata,
            "rawContext": raw_context,
        },
    }


def build_fragment_prompt_package(
    case: dict[str, Any], *, user_language: str | None = None
) -> dict[str, Any]:
    """Build an external-agent research packet from a raw-rich mature case."""
    normalized = normalize_extractor_case(case)
    if not normalized.get("ok"):
        return normalized

    extractor_case = normalized["extractorCase"]
    language_label = _output_language_label(user_language)
    system = (
        "You are an external Path of Exile 2 build-research agent. Use your own research loop, "
        "tool calls, comparison, and reflection as needed. The project supplies raw-rich evidence "
        "only so you can understand the sample; your final answer must be clean JSON fragments, "
        "not a build recipe."
    )
    user = (
        "Analyze the research case set below as an agent research brief, not as a single-pass "
        "summary question. Before producing final JSON, reason through these duties:\n"
        "- sample fact inventory: identify what the sample actually proves and what it does not.\n"
        "- core mechanism: explain the scaling, sustain, defense, or play-pattern engine.\n"
        "- reusable principle: state what can transfer to other builds without copying this one.\n"
        "- endgame-only classification: decide whether this is final-form, transition, starter, "
        "or unknown evidence.\n"
        "- starter risk: explain what breaks if a new player tries this too early.\n"
        "- transition gate: name the safe non-copyable conditions for switching into the idea.\n"
        "- failure mode: describe where the sample is fragile or misleading.\n"
        "- PoB modelability: separate engine-verifiable facts from unmodelled/corrupted evidence.\n"
        "- evidence references: cite safe evidence labels from the packet, not raw build text.\n"
        "- verification task: propose concrete follow-up checks for Codex or Claude Code.\n\n"
        "Return one JSON object that matches this schema:\n"
        "{\n"
        '  "schemaVersion": 3,\n'
        '  "fragments": [\n'
        "    {\n"
        '      "fragmentType": "mechanic | gear_role | skill_role | passive_anchor | '
        "transition_gate | starter_warning | modelability_caveat | failure_pattern | "
        'comparison_note | open_question",\n'
        '      "title": "short fragment title",\n'
        '      "summary": "main insight in one short paragraph",\n'
        '      "reusablePrinciple": "transferable design principle, not a recipe",\n'
        '      "sourceCaseRefs": ["case ref ids this fragment came from"],\n'
        '      "confidence": "low | medium | high",\n'
        '      "copyabilityRisk": "low | medium",\n'
        '      "evidenceRefs": ["optional safe evidence refs"],\n'
        '      "lifecycleStages": ["optional lifecycle stages"],\n'
        '      "componentNames": ["optional mechanism-level exact names"],\n'
        '      "conditions": ["optional conditions or thresholds"],\n'
        '      "risks": ["optional risks or caveats"],\n'
        '      "modelability": "optional full | partial | not_modelable | unknown",\n'
        '      "verificationTasks": ["agent or engine checks needed before reuse"],\n'
        '      "notes": ["optional extra notes"]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Extraction guidance:\n"
        "- You may emit zero, one, or many fragments depending on how much is genuinely learnable.\n"
        "- Keep only evidence-backed, reusable insights.\n"
        "- `componentNames` may include mechanism-level exact names such as skill, ascendancy, "
        "key unique, support, or notable names when they matter.\n"
        "- Do not restate recipe-level build material such as full gear tables, full links, full "
        "passive paths, PoB exports, or raw page/forum text.\n"
        "- Prefer fewer, sharper fragments over broad labels. A fragment without a reusable "
        "principle and verification task is not useful enough to keep.\n"
        f"- Keep JSON field names and enum values in English, but write explanatory string content in {language_label}.\n\n"
        "Research case:\n"
        f"{json.dumps(extractor_case, ensure_ascii=False, indent=2)}"
    )
    return {
        "ok": True,
        "schemaVersion": FRAGMENT_SCHEMA_VERSION,
        "caseRef": extractor_case["caseRef"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


def validate_fragment_extraction_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a clean persisted fragment payload."""
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
    if payload.get("schemaVersion") != FRAGMENT_SCHEMA_VERSION:
        return {"ok": False, "error": "unsupported_schema_version"}

    fragments = payload.get("fragments")
    if not isinstance(fragments, list):
        return {"ok": False, "error": "fragments_must_be_list"}

    for index, fragment in enumerate(fragments):
        error = _validate_fragment(fragment)
        if error:
            return {"ok": False, "error": error, "fragmentIndex": index}

    return {
        "ok": True,
        "schemaVersion": FRAGMENT_SCHEMA_VERSION,
        "fragmentCount": len(fragments),
        "extractionMethod": "agent_mature_fragment_v3",
    }


def validate_fragment_report_markdown(markdown: str) -> dict[str, Any]:
    """Ensure the rendered report remains free of recipe-level build material."""
    if not isinstance(markdown, str):
        return {"ok": False, "error": "markdown_must_be_string"}

    copyability_flags = copy_safety.copyability_flags({"markdown": markdown})
    if copyability_flags:
        return {
            "ok": False,
            "error": "copyability_guard_failed",
            "flags": copyability_flags,
        }
    if _contains_forbidden_report_labels(markdown):
        return {"ok": False, "error": "report_contains_forbidden_raw_labels"}
    return {"ok": True}


def _validate_fragment(fragment: Any) -> str | None:
    if not isinstance(fragment, dict):
        return "fragment_must_be_object"

    missing = sorted(key for key in REQUIRED_FRAGMENT_FIELDS if key not in fragment)
    if missing:
        return "fragment_missing_required_fields"
    if not _is_nonempty_string(fragment.get("title")):
        return "invalid_title"
    if not _is_nonempty_string(fragment.get("summary")):
        return "invalid_summary"
    if not copy_safety.is_allowed_enum(fragment.get("fragmentType"), VALID_FRAGMENT_TYPES):
        return "invalid_fragment_type"
    if not copy_safety.is_allowed_enum(fragment.get("confidence"), VALID_CONFIDENCE):
        return "invalid_confidence"
    if not copy_safety.is_allowed_enum(fragment.get("copyabilityRisk"), VALID_COPYABILITY):
        return "invalid_copyability_risk"
    if fragment.get("copyabilityRisk") == "high":
        return "high_copyability_risk"
    if not _is_string_list(fragment.get("sourceCaseRefs"), require_non_empty=True):
        return "invalid_sourceCaseRefs"
    if not _is_nonempty_string(fragment.get("reusablePrinciple")):
        return "invalid_reusablePrinciple"
    if not _is_string_list(fragment.get("verificationTasks"), require_non_empty=True):
        return "invalid_verificationTasks"

    for key in OPTIONAL_LIST_FIELDS:
        value = fragment.get(key)
        if value is None:
            continue
        if not _is_string_list(value, require_non_empty=False):
            return f"invalid_{key}"

    modelability = fragment.get("modelability")
    if modelability is not None and modelability != "":
        if not copy_safety.is_allowed_enum(modelability, VALID_MODELABILITY):
            return "invalid_modelability"
    return None


def _case_ref(safe_metadata: dict[str, Any], *, index: int | None = None) -> str:
    for key in ("case_id", "caseId", "sourceRef", "buildId"):
        value = safe_metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if index is not None:
        return f"case-{index + 1}"
    return "unknown-case"


def _output_language_label(user_language: str | None) -> str:
    normalized = str(user_language or "").strip().lower()
    if normalized.startswith("zh"):
        return "Simplified Chinese"
    return "English"


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_string_list(value: Any, *, require_non_empty: bool) -> bool:
    if not isinstance(value, list):
        return False
    if require_non_empty and not value:
        return False
    return all(isinstance(item, str) and item.strip() for item in value)


def _contains_forbidden_report_labels(markdown: str) -> bool:
    lowered = markdown.lower()
    return any(re.search(rf"\b{label}\b", lowered) for label in _FORBIDDEN_REPORT_LABELS)
