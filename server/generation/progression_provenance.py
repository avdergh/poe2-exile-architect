"""Trusted Phase 5 and Research provenance checks for anchored progression runs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from server.knowledge import copy_safety

from . import models, progression_models, run_store


def read_consumed_phase5_provenance(run_id: str) -> dict[str, Any] | None:
    """Read the canonical safe review produced by one consumed Phase 5 run."""

    canonical = run_store.canonical_run_id(run_id)
    if canonical is None:
        return None
    run_dir = run_store.runs_dir() / canonical
    if not (run_dir / "review-consumed").is_file():
        return None
    manifest = run_store.read_run_manifest(
        run_dir / "run-manifest.json",
        canonical,
        run_dir / "agent-output.json",
    )
    if manifest is None:
        return None
    try:
        payload = json.loads((run_dir / "review-result.json").read_text(encoding="utf-8"))
        packet = models.HumanReviewPacket.model_validate(payload.get("humanReviewPacket"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, AttributeError):
        return None
    candidate = packet.prototype_build_candidate
    usage = candidate.research_memory_use
    final_audit = (
        packet.generation_attempts[-1].failure_audit
        if packet.generation_attempts
        else packet.failure_audit
    )
    if usage is None or final_audit is None:
        return None
    safe = {
        "runId": canonical,
        "candidateId": candidate.candidate_id,
        "sourceHash": packet.transient_build_state.source_hash,
        "researchMemoryUse": usage.model_dump(mode="json", by_alias=True),
        "finalFailureAudit": final_audit.model_dump(mode="json", by_alias=True),
        "versionContext": packet.version_context.model_dump(mode="json", by_alias=True),
        "noRawMaterial": True,
    }
    if _unsafe(safe):
        return None
    return safe


def validate_research_provenance(
    *,
    identity: progression_models.StageFamilyIdentity,
    research_memory_use: dict[str, Any],
    artifact_research_ref: str,
    receipt_reader: Callable[[str], dict[str, Any] | None],
    not_before: str | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Validate exact Family intent and every recalled item against durable query receipts."""

    try:
        usage = models.ResearchMemoryUse.model_validate(research_memory_use)
    except ValidationError:
        return "progression_research_use_invalid", None
    if artifact_research_ref not in usage.dedupe_query_refs:
        return "progression_artifact_research_ref_not_used", None

    receipts: list[dict[str, Any]] = []
    for ref in usage.dedupe_query_refs:
        receipt = receipt_reader(ref)
        if receipt is None:
            return "progression_research_receipt_missing", None
        receipts.append(receipt)
    if not_before is not None:
        if any(not receipt_was_seen_at_or_after(receipt, not_before) for receipt in receipts):
            return "progression_research_receipt_not_current_run", None

    exact_refs = [
        str(receipt["dedupeQueryRef"])
        for receipt in receipts
        if receipt_matches_identity_query(receipt, identity)
    ]
    if not exact_refs:
        return "progression_exact_family_query_missing", None

    result_sets = {
        "buildFamilyKeys": {
            str(family.get("buildFamilyKey"))
            for receipt in receipts
            for family in (receipt.get("result") or {}).get("buildFamilies", [])
            if isinstance(family, dict) and family.get("buildFamilyKey")
        },
        "deepRecordIds": _result_ids(receipts, "deepRecordIds"),
        "patternIds": _result_ids(receipts, "patternIds"),
        "semanticEdgeIds": _result_ids(receipts, "semanticEdgeIds"),
        "memoryItemIds": _result_ids(receipts, "memoryItemIds"),
    }
    used_sets = {
        "buildFamilyKeys": set(usage.build_family_keys),
        "deepRecordIds": set(usage.deep_record_ids),
        "patternIds": set(usage.pattern_ids),
        "semanticEdgeIds": set(usage.semantic_edge_ids),
        "memoryItemIds": set(usage.memory_item_ids),
    }
    for key, used in used_sets.items():
        if not used.issubset(result_sets[key]):
            return "progression_research_item_not_in_receipt", None

    matching_families = [
        family
        for receipt in receipts
        for family in (receipt.get("result") or {}).get("buildFamilies", [])
        if isinstance(family, dict)
        and family.get("ascendancyKey") == identity.ascendancy_key
        and family.get("primarySkillKey") == identity.primary_skill_key
        and sorted(family.get("secondarySkillKeys") or []) == sorted(identity.secondary_skill_keys)
    ]
    if usage.build_family_keys and not any(
        str(item.get("buildFamilyKey")) in used_sets["buildFamilyKeys"]
        for item in matching_families
    ):
        return "progression_research_family_identity_mismatch", None

    summary = {
        "dedupeQueryRefs": list(usage.dedupe_query_refs),
        "exactIdentityQueryRefs": exact_refs,
        **{key: sorted(value) for key, value in used_sets.items()},
        "retrievalOutcome": usage.retrieval_outcome,
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }
    if _unsafe(summary):
        return "progression_research_provenance_unsafe", None
    return None, summary


def receipt_matches_identity_query(
    receipt: dict[str, Any],
    identity: progression_models.StageFamilyIdentity,
) -> bool:
    """Match an exact Family query while honoring graph-backed gem/active-skill aliases."""

    request = receipt.get("request") or {}
    if request.get("ascendancyKey") != identity.ascendancy_key:
        return False
    equivalent_keys = request.get("primarySkillKeys")
    if not isinstance(equivalent_keys, list) or not equivalent_keys:
        equivalent_keys = [request.get("primarySkillKey")]
    return identity.primary_skill_key in {
        str(key) for key in equivalent_keys if isinstance(key, str) and key
    }


def receipt_was_seen_at_or_after(receipt: dict[str, Any], not_before: str) -> bool:
    """Return whether a typed receipt was actually queried during this progression."""

    threshold = _parse_timestamp(not_before)
    seen = _parse_timestamp(receipt.get("lastSeenAt"))
    return threshold is not None and seen is not None and seen >= threshold


def review_result_path(run_id: str) -> Path | None:
    """Return the canonical local review path for diagnostics without reading raw build state."""

    canonical = run_store.canonical_run_id(run_id)
    return (run_store.runs_dir() / canonical / "review-result.json") if canonical else None


def _result_ids(receipts: list[dict[str, Any]], key: str) -> set[str]:
    return {
        str(item)
        for receipt in receipts
        for item in (receipt.get("result") or {}).get(key, [])
        if isinstance(item, str) and item
    }


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _unsafe(value: Any) -> bool:
    return bool(
        copy_safety.find_forbidden_paths(value)
        or copy_safety.durable_knowledge_flags(value)
        or copy_safety.contains_raw_url(value)
    )
