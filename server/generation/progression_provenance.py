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
    expected_blind_run_ref: str | None = None,
    expected_blind_claim_ref: str | None = None,
) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    """Validate ordinary Create Research use and any premise catalog in its receipts."""

    error, validated, caveats = _validate_research_use_receipts(
        research_memory_use=research_memory_use,
        receipt_reader=receipt_reader,
        not_before=not_before,
        expected_blind_run_ref=expected_blind_run_ref,
        expected_blind_claim_ref=expected_blind_claim_ref,
    )
    if error or validated is None:
        return error, None, caveats
    usage = validated["usage"]
    summary = {
        "dedupeQueryRefs": list(usage.dedupe_query_refs),
        "comparisonDedupeQueryRefs": list(usage.comparison_dedupe_query_refs),
        **{key: sorted(value) for key, value in validated["usedSets"].items()},
        "retrievalOutcome": usage.retrieval_outcome,
        "selectedKnowledgeScope": usage.selected_knowledge_scope,
        "selectedSourceCaseRef": usage.selected_source_case_ref,
        "caseComparison": validated.get("caseComparison") or {},
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
    expected_blind_run_ref: str | None,
    expected_blind_claim_ref: str | None,
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
    comparison_receipts: list[dict[str, Any]] = []
    for ref in usage.comparison_dedupe_query_refs:
        receipt = receipt_reader(ref)
        if receipt is None:
            return "progression_research_comparison_receipt_missing", None, []
        comparison_receipts.append(receipt)
    if not_before is not None:
        stale_refs = [
            str(receipt.get("dedupeQueryRef") or "")
            for receipt in [*receipts, *comparison_receipts]
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

    v2_receipts = [
        receipt
        for receipt in receipts
        if int((receipt.get("result") or {}).get("queryContractVersion") or 0) >= 2
    ]
    if len(v2_receipts) != len(receipts):
        return "progression_research_receipt_legacy_unscoped", None, []
    if v2_receipts:
        matched = usage.retrieval_outcome == "matched"
        if matched and (not usage.selected_knowledge_scope or not usage.selected_source_case_ref):
            return "progression_research_source_lane_required", None, []
        for receipt in v2_receipts:
            result = receipt.get("result") or {}
            if matched and not bool(result.get("createAuthorizing")):
                return "progression_research_receipt_not_create_authorizing", None, []
            if matched and result.get("selectedKnowledgeScope") != usage.selected_knowledge_scope:
                return "progression_research_source_lane_mixed", None, []
            if matched and result.get("selectedSourceCaseRef") != usage.selected_source_case_ref:
                return "progression_research_source_lane_mixed", None, []
            if not matched and (
                bool(result.get("createAuthorizing"))
                or result.get("selectedKnowledgeScope")
                or result.get("selectedSourceCaseRef")
            ):
                return "progression_research_no_match_receipt_conflict", None, []
        blind_flags = {
            bool((receipt.get("request") or {}).get("blindClaimBound")) for receipt in v2_receipts
        }
        if len(blind_flags) != 1:
            return "progression_research_blind_claim_mixed", None, []
        if True in blind_flags:
            run_refs = {str(receipt.get("runRef") or "") for receipt in v2_receipts}
            claim_refs = {str(receipt.get("claimRef") or "") for receipt in v2_receipts}
            if (
                (matched and usage.selected_knowledge_scope != "global_seed")
                or len(run_refs) != 1
                or len(claim_refs) != 1
                or not next(iter(run_refs))
                or not next(iter(claim_refs))
            ):
                return "progression_research_blind_claim_binding_mismatch", None, []
            effective_scopes = {str(receipt.get("effectiveScope") or "") for receipt in v2_receipts}
            if effective_scopes != {"global_seed"}:
                return "progression_research_blind_claim_binding_mismatch", None, []
        if expected_blind_run_ref is not None or expected_blind_claim_ref is not None:
            if not expected_blind_run_ref or not expected_blind_claim_ref or blind_flags != {True}:
                return "progression_research_blind_claim_binding_mismatch", None, []
            if {str(receipt.get("runRef") or "") for receipt in v2_receipts} != {
                expected_blind_run_ref
            } or {str(receipt.get("claimRef") or "") for receipt in v2_receipts} != {
                expected_blind_claim_ref
            }:
                return "progression_research_blind_claim_binding_mismatch", None, []
        sessions: dict[str, list[dict[str, Any]]] = {}
        for receipt in v2_receipts:
            retrieval_ref = str(receipt.get("retrievalRef") or "")
            if not retrieval_ref:
                return "progression_research_retrieval_incomplete", None, []
            sessions.setdefault(retrieval_ref, []).append(receipt)
        for session_receipts in sessions.values():
            page_counts = {int(item.get("pageCount") or 0) for item in session_receipts}
            manifest_hashes = {str(item.get("manifestHash") or "") for item in session_receipts}
            revisions = {
                int(item["memoryRevision"]) if item.get("memoryRevision") is not None else -1
                for item in session_receipts
            }
            if len(page_counts) != 1 or len(manifest_hashes) != 1 or len(revisions) != 1:
                return "progression_research_retrieval_conflict", None, []
            page_count = next(iter(page_counts))
            indexes = {int(item.get("pageIndex") or 0) for item in session_receipts}
            if indexes != set(range(page_count)) or not any(
                bool(item.get("retrievalComplete")) for item in session_receipts
            ):
                return "progression_research_retrieval_incomplete", None, []

    comparison_error, comparison_summary = _validate_case_comparison_receipts(
        usage=usage,
        authoritative_receipts=receipts,
        comparison_receipts=comparison_receipts,
    )
    if comparison_error:
        return comparison_error, None, []

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

    if usage.retrieval_outcome == "matched":
        required_deep_reads = {
            str(record_id)
            for receipt in receipts
            for coverage in (receipt.get("result") or {}).get("familyRecordCoverage", [])
            if isinstance(coverage, dict)
            and (
                not usage.build_family_keys
                or str(coverage.get("buildFamilyKey") or "") in set(usage.build_family_keys)
            )
            for record_id in coverage.get("requiredDeepReadRecordIds") or []
            if isinstance(record_id, str) and record_id
        }
        deep_read_ids = _result_ids(receipts, "deepReadRecordIds")
        missing_required_reads = sorted(required_deep_reads - deep_read_ids)
        if missing_required_reads:
            return (
                "research_required_records_not_read",
                None,
                [
                    "required Family records were not deep-read in this run: "
                    + ", ".join(missing_required_reads)
                ],
            )
        decided_refs = {
            str(source_ref)
            for decision in usage.insight_decisions
            for source_ref in decision.source_refs
        }
        undecided_required = sorted(required_deep_reads - decided_refs)
        if undecided_required:
            return (
                "research_required_records_not_decided",
                None,
                [
                    "required Family records need an adopted/caveated/rejected insight decision: "
                    + ", ".join(undecided_required)
                ],
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
            "comparisonReceipts": comparison_receipts,
            "caseComparison": comparison_summary or {},
            "usedSets": used_sets,
            **(premise_summary or {}),
        },
        [],
    )


def _validate_case_comparison_receipts(
    *,
    usage: models.ResearchMemoryUse,
    authoritative_receipts: list[dict[str, Any]],
    comparison_receipts: list[dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None]:
    """Require bounded multi-case comparison while keeping one authoritative source lane."""

    if usage.retrieval_outcome != "matched":
        return None, {"requiredAdditionalCases": 0, "comparedAdditionalCases": 0}

    blind_bound = any(
        bool((receipt.get("result") or {}).get("blindClaimBound"))
        for receipt in authoritative_receipts
    )
    if blind_bound:
        if comparison_receipts:
            return "progression_research_blind_case_comparison_forbidden", None
        return None, {"requiredAdditionalCases": 0, "comparedAdditionalCases": 0}

    authoritative_lane = (
        str(usage.selected_knowledge_scope or ""),
        str(usage.selected_source_case_ref or ""),
    )
    available_lanes: set[tuple[str, str]] = set()
    required_count = 0
    authoritative_patches: set[str] = set()
    authoritative_trees: set[str] = set()
    for receipt in authoritative_receipts:
        result = receipt.get("result") or {}
        required_count = max(required_count, int(result.get("comparisonRequiredCount") or 0))
        for item in result.get("familyAvailableSourceCaseLanes") or []:
            if not isinstance(item, dict):
                continue
            scope = str(item.get("knowledgeScope") or "")
            case_ref = str(item.get("sourceCaseRef") or "")
            if scope and case_ref:
                available_lanes.add((scope, case_ref))
        if result.get("requestedGamePatch"):
            authoritative_patches.add(str(result["requestedGamePatch"]))
        if result.get("requestedPassiveTreeVersion"):
            authoritative_trees.add(str(result["requestedPassiveTreeVersion"]))

    available_additional = available_lanes - {authoritative_lane}
    required_count = min(2, len(available_additional), required_count or len(available_additional))
    if required_count == 0:
        if comparison_receipts:
            return "progression_research_case_comparison_not_available", None
        return None, {"requiredAdditionalCases": 0, "comparedAdditionalCases": 0}

    if not comparison_receipts:
        return "progression_research_case_comparison_incomplete", None
    if any(
        int((receipt.get("result") or {}).get("queryContractVersion") or 0) < 2
        or not bool((receipt.get("result") or {}).get("createAuthorizing"))
        or bool((receipt.get("result") or {}).get("blindClaimBound"))
        for receipt in comparison_receipts
    ):
        return "progression_research_comparison_receipt_invalid", None

    sessions: dict[str, list[dict[str, Any]]] = {}
    for receipt in comparison_receipts:
        retrieval_ref = str(receipt.get("retrievalRef") or "")
        if not retrieval_ref:
            return "progression_research_comparison_retrieval_incomplete", None
        sessions.setdefault(retrieval_ref, []).append(receipt)

    compared_lanes: set[tuple[str, str]] = set()
    selected_families = set(usage.build_family_keys)
    for session_receipts in sessions.values():
        page_counts = {int(item.get("pageCount") or 0) for item in session_receipts}
        indexes = {int(item.get("pageIndex") or 0) for item in session_receipts}
        manifest_hashes = {str(item.get("manifestHash") or "") for item in session_receipts}
        revisions = {
            int(item["memoryRevision"]) if item.get("memoryRevision") is not None else -1
            for item in session_receipts
        }
        if len(page_counts) != 1 or len(manifest_hashes) != 1 or len(revisions) != 1:
            return "progression_research_comparison_retrieval_conflict", None
        page_count = next(iter(page_counts))
        if indexes != set(range(page_count)) or not any(
            bool(item.get("retrievalComplete")) for item in session_receipts
        ):
            return "progression_research_comparison_retrieval_incomplete", None

        lane_values = {
            (
                str((item.get("result") or {}).get("selectedKnowledgeScope") or ""),
                str((item.get("result") or {}).get("selectedSourceCaseRef") or ""),
            )
            for item in session_receipts
        }
        if len(lane_values) != 1:
            return "progression_research_comparison_source_lane_mixed", None
        lane = next(iter(lane_values))
        if lane == authoritative_lane or lane not in available_additional:
            return "progression_research_comparison_source_lane_mismatch", None

        requested_families = {
            str(family_key)
            for item in session_receipts
            for family_key in (item.get("result") or {}).get("requestedBuildFamilyKeys") or []
            if str(family_key)
        }
        if selected_families and not selected_families.issubset(requested_families):
            return "progression_research_comparison_family_mismatch", None
        comparison_patches = {
            str((item.get("result") or {}).get("requestedGamePatch") or "")
            for item in session_receipts
            if (item.get("result") or {}).get("requestedGamePatch")
        }
        comparison_trees = {
            str((item.get("result") or {}).get("requestedPassiveTreeVersion") or "")
            for item in session_receipts
            if (item.get("result") or {}).get("requestedPassiveTreeVersion")
        }
        if authoritative_patches and comparison_patches != authoritative_patches:
            return "progression_research_comparison_version_mismatch", None
        if authoritative_trees and comparison_trees != authoritative_trees:
            return "progression_research_comparison_version_mismatch", None
        compared_lanes.add(lane)

    if len(compared_lanes) < required_count:
        return "progression_research_case_comparison_incomplete", None
    return (
        None,
        {
            "requiredAdditionalCases": required_count,
            "comparedAdditionalCases": len(compared_lanes),
            "totalCasesReviewed": 1 + len(compared_lanes),
        },
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
