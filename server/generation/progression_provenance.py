"""Trusted Research-provenance checks for ordinary single-stage Create.

The progression state machine was removed; this module keeps only the receipt/premise audit that
ordinary Create relies on (``evaluate_generation_candidate`` freshness fail-fast and the
``validate_generation_output`` / ``complete_generation_review`` receipt audit).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from pydantic import ValidationError

from server.knowledge import copy_safety

from . import models


def validate_research_use_receipts(
    *,
    research_memory_use: dict[str, Any],
    receipt_reader: Callable[[str], dict[str, Any] | None],
    not_before: str | None = None,
) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    """Validate ordinary Create Research use and any premise catalog in its receipts."""

    error, validated, caveats = _validate_research_use_receipts(
        research_memory_use=research_memory_use,
        receipt_reader=receipt_reader,
        not_before=not_before,
    )
    if error or validated is None:
        return error, None, caveats
    usage = validated["usage"]
    summary = {
        "dedupeQueryRefs": list(usage.dedupe_query_refs),
        **{key: sorted(value) for key, value in validated["usedSets"].items()},
        "retrievalOutcome": usage.retrieval_outcome,
        "premiseAuditVersion": usage.premise_audit_version,
        "premiseDecisions": validated["premiseDecisions"],
        "premiseDecisionIds": validated["premiseDecisionIds"],
        "caveatedPremiseIds": validated["caveatedPremiseIds"],
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }
    if _unsafe(summary):
        return "progression_research_provenance_unsafe", None, []
    return None, summary, caveats


def _validate_research_use_receipts(
    *,
    research_memory_use: dict[str, Any],
    receipt_reader: Callable[[str], dict[str, Any] | None],
    not_before: str | None,
) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    try:
        usage = models.ResearchMemoryUse.model_validate(research_memory_use)
    except ValidationError as exc:
        caveats = [
            "researchMemoryUse{}. {}".format(
                ("." + ".".join(str(part) for part in error.get("loc", ())))
                if error.get("loc")
                else "",
                " ".join(str(error.get("msg") or "validation failed").split())[:160],
            )
            for error in exc.errors()[:5]
        ]
        if len(exc.errors()) > 5:
            caveats.append(f"... and {len(exc.errors()) - 5} more validation error(s)")
        # Schema misuse is a client-contract problem, not a receipt-trust problem: surface the
        # field paths so the Agent can repair the payload instead of guessing.
        return "progression_research_use_invalid", None, caveats

    receipts: list[dict[str, Any]] = []
    for ref in usage.dedupe_query_refs:
        receipt = receipt_reader(ref)
        if receipt is None:
            return "progression_research_receipt_missing", None, []
        receipts.append(receipt)
    if not_before is not None:
        stale_refs = [
            str(receipt.get("dedupeQueryRef") or "")
            for receipt in receipts
            if not receipt_was_seen_at_or_after(receipt, not_before)
        ]
        if stale_refs:
            return (
                "progression_research_receipt_not_current_run",
                None,
                [
                    "receipts queried before this run started: "
                    + ", ".join(sorted(stale_refs))
                    + " — re-query Research inside the current run and pass the new "
                    "dedupeQueryRefs",
                ],
            )

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
            missing = sorted(used - result_sets[key])
            return (
                "progression_research_item_not_in_receipt",
                None,
                [f"{key} not present in the referenced receipts: " + ", ".join(missing)],
            )

    premise_error, premise_summary = _validate_premise_decisions(
        usage=usage,
        receipts=receipts,
    )
    if premise_error:
        return premise_error, None, []
    return (
        None,
        {
            "usage": usage,
            "receipts": receipts,
            "usedSets": used_sets,
            **(premise_summary or {}),
        },
        [],
    )


def _validate_premise_decisions(
    *,
    usage: models.ResearchMemoryUse,
    receipts: list[dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None]:
    selected_family_keys = set(usage.build_family_keys)
    catalog: dict[str, dict[str, Any]] = {}
    premise_audit_available = False
    for receipt in receipts:
        result = receipt.get("result") or {}
        if result.get("premiseAuditVersion") == 1:
            premise_audit_available = True
        for item in result.get("familyPremiseCatalog") or []:
            if not isinstance(item, dict):
                continue
            family_key = str(item.get("buildFamilyKey") or "")
            if selected_family_keys and family_key not in selected_family_keys:
                continue
            premise_id = str(item.get("premiseId") or "")
            if not premise_id:
                continue
            previous = catalog.get(premise_id)
            if previous is not None and previous != item:
                return "progression_research_premise_receipt_conflict", None
            catalog[premise_id] = item

    if catalog and usage.premise_audit_version != 1:
        return "progression_research_premise_audit_required", None
    if usage.premise_audit_version == 1 and not premise_audit_available:
        return "progression_research_premise_catalog_missing", None

    decisions = {item.premise_id: item for item in usage.premise_decisions}
    if any(premise_id not in catalog for premise_id in decisions):
        return "progression_research_premise_not_in_receipt", None
    required_failure_ids = {
        premise_id
        for premise_id, item in catalog.items()
        if item.get("premiseType") == "failure_condition"
    }
    if not required_failure_ids.issubset(decisions):
        return "progression_research_premise_decision_incomplete", None

    deep_read_ids = _result_ids(receipts, "deepReadRecordIds")
    for decision in decisions.values():
        if decision.decision != "resolved":
            continue
        resolution_records = {ref for ref in decision.resolution_refs if ref.startswith("drr-")}
        if not resolution_records or not resolution_records.issubset(deep_read_ids):
            return "progression_research_resolution_not_deep_read", None

    serialized = [
        item.model_dump(mode="json", by_alias=True)
        for item in sorted(usage.premise_decisions, key=lambda value: value.premise_id)
    ]
    return (
        None,
        {
            "premiseDecisions": serialized,
            "premiseDecisionIds": sorted(decisions),
            "caveatedPremiseIds": sorted(
                item.premise_id for item in usage.premise_decisions if item.decision == "caveated"
            ),
        },
    )


def receipt_was_seen_at_or_after(receipt: dict[str, Any], not_before: str) -> bool:
    """Return whether a typed receipt was actually queried during this run."""

    threshold = _parse_timestamp(not_before)
    seen = _parse_timestamp(receipt.get("lastSeenAt"))
    return threshold is not None and seen is not None and seen >= threshold


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
