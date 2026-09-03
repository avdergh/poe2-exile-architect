"""Query-time Research execution contracts for Agent-led build generation.

The durable Research store remains the authority.  This module builds a bounded, copy-safe view
that converts one selected source-case lane plus reviewed comparison lanes into explicit packages
the Agent must adopt, reject, retain as an alternative, or mark not applicable.  It never merges
away source-case or scope authority and never assembles a PoB automatically.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable

from server.knowledge import copy_safety, mature_learning, research_memory


CONTRACT_VERSION = 1
MAX_CONTRACT_PACKAGES = 96
_SAFE_REF = re.compile(r"^[A-Za-z0-9_.:/\-]{3,240}$")
_COMPONENT_ROLES = {
    "primary_damage",
    "clear_skill",
    "boss_skill",
    "generator",
    "payoff",
    "reservation",
    "defensive_buff",
    "ascendancy_shell",
    "movement",
    "trigger_host",
    "unique_enabler",
    "transition_gate",
    "passive_anchor",
    "keystone_transformer",
    "gear_base",
    "weapon_base",
    "defense_layer",
    "resource_engine",
    "secondary_skill",
    "triggered_payload",
    "control_skill",
}
_TYPED_PACKAGE_KEYS = (
    "supportPackages",
    "resourceMechanisms",
    "gearResponsibilities",
    "gearSubjects",
    "ascendancyResponsibilities",
    "familyCoreSkillKeys",
)


def construct_research_execution_contract(
    *,
    authoritative_dedupe_query_refs: list[str],
    comparison_dedupe_query_refs: list[str],
    build_family_key: str,
    selected_knowledge_scope: str,
    selected_source_case_ref: str,
    game_patch: str,
    passive_tree_version: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Build one deterministic contract from complete Create-authorizing receipt chains."""

    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        initialize_store=False,
    )
    return _construct(
        authoritative_dedupe_query_refs=authoritative_dedupe_query_refs,
        comparison_dedupe_query_refs=comparison_dedupe_query_refs,
        build_family_key=build_family_key,
        selected_knowledge_scope=selected_knowledge_scope,
        selected_source_case_ref=selected_source_case_ref,
        game_patch=game_patch,
        passive_tree_version=passive_tree_version,
        receipt_reader=service.read_query_receipt,
        db_path=db_path,
    )


def construct_from_research_use(
    research_memory_use: dict[str, Any],
    *,
    game_patch: str,
    passive_tree_version: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Rebuild the exact contract used by generation validation."""

    family_keys = list(
        research_memory_use.get("buildFamilyKeys")
        or research_memory_use.get("build_family_keys")
        or []
    )
    if len(family_keys) != 1:
        return _error(
            "research_execution_requires_one_family",
            "Execution contracts require exactly one selected Build Family.",
        )
    return construct_research_execution_contract(
        authoritative_dedupe_query_refs=list(
            research_memory_use.get("dedupeQueryRefs")
            or research_memory_use.get("dedupe_query_refs")
            or []
        ),
        comparison_dedupe_query_refs=list(
            research_memory_use.get("comparisonDedupeQueryRefs")
            or research_memory_use.get("comparison_dedupe_query_refs")
            or []
        ),
        build_family_key=str(family_keys[0]),
        selected_knowledge_scope=str(
            research_memory_use.get("selectedKnowledgeScope")
            or research_memory_use.get("selected_knowledge_scope")
            or ""
        ),
        selected_source_case_ref=str(
            research_memory_use.get("selectedSourceCaseRef")
            or research_memory_use.get("selected_source_case_ref")
            or ""
        ),
        game_patch=game_patch,
        passive_tree_version=passive_tree_version,
        db_path=db_path,
    )


def validate_research_execution_plan(
    plan: dict[str, Any],
    contract: dict[str, Any],
    *,
    allowed_evidence_refs: set[str] | None = None,
    external_evidence_refs: set[str] | None = None,
) -> tuple[str | None, list[str], dict[str, Any] | None]:
    """Validate package coverage and cross-case integration without trusting prose claims."""

    if contract.get("status") != "ready":
        return "research_execution_contract_unavailable", [], None
    contract_ref = str(contract.get("contractRef") or "")
    if str(_pick(plan, "contractRef", "contract_ref") or "") != contract_ref:
        return "research_execution_contract_mismatch", [], None
    selected_case = str(contract.get("selectedDesignCaseRef") or "")
    if str(_pick(plan, "selectedDesignCaseRef", "selected_design_case_ref") or "") != selected_case:
        return "research_execution_selected_case_mismatch", [], None

    packages = {
        str(item.get("packageId")): item
        for item in contract.get("packages") or []
        if isinstance(item, dict) and item.get("packageId")
    }
    required_ids = set(contract.get("reviewRequiredPackageIds") or [])
    decisions = list(_pick(plan, "packageDecisions", "package_decisions") or [])
    decision_map = {
        str(_pick(item, "packageId", "package_id") or ""): item
        for item in decisions
        if isinstance(item, dict)
    }
    if set(decision_map) != required_ids:
        missing = sorted(required_ids - set(decision_map))
        extra = sorted(set(decision_map) - required_ids)
        caveats = []
        if missing:
            caveats.append("missing package decisions: " + ", ".join(missing[:12]))
        if extra:
            caveats.append("unknown package decisions: " + ", ".join(extra[:12]))
        return "research_execution_package_decisions_incomplete", caveats, None
    if allowed_evidence_refs is not None:
        for package_id, decision in decision_map.items():
            evidence_refs = set(
                _pick(
                    decision,
                    "verificationEvidenceRefs",
                    "verification_evidence_refs",
                )
                or []
            )
            unknown = sorted(evidence_refs - allowed_evidence_refs)
            if unknown:
                return (
                    "research_execution_decision_evidence_unknown",
                    [package_id + ": " + ", ".join(unknown[:5])],
                    None,
                )
            if (
                external_evidence_refs is not None
                and str(decision.get("decision") or "")
                in {"adopted", "tested_and_rejected"}
                and not evidence_refs & external_evidence_refs
            ):
                return (
                    "research_execution_decision_external_evidence_required",
                    [package_id],
                    None,
                )

    plans = list(_pick(plan, "crossCaseMechanismPlans", "cross_case_mechanism_plans") or [])
    plan_map = {
        str(_pick(item, "planId", "plan_id") or ""): item
        for item in plans
        if isinstance(item, dict)
    }
    if len(plan_map) != len(plans):
        return "research_execution_cross_case_plan_duplicate", [], None

    comparison_cases = set(contract.get("comparisonCaseRefs") or [])
    authoritative_ids = {
        package_id
        for package_id, package in packages.items()
        if package.get("authority") in {"authoritative", "authoritative_and_comparison"}
    }
    comparison_only_ids = {
        package_id
        for package_id, package in packages.items()
        if package.get("authority") == "comparison"
    }
    authoritative_deep_reads = set(contract.get("authoritativeDeepReadRecordIds") or [])
    comparison_deep_reads = set(contract.get("comparisonDeepReadRecordIds") or [])
    adopted_comparison_ids: set[str] = set()
    for package_id, decision in decision_map.items():
        package = packages[package_id]
        value = str(decision.get("decision") or "")
        plan_ref = str(_pick(decision, "crossCasePlanRef", "cross_case_plan_ref") or "")
        if package_id in authoritative_ids:
            if str(package.get("recordId") or "") not in authoritative_deep_reads:
                return "research_execution_authoritative_package_not_deep_read", [package_id], None
            if value == "retained_as_alternative":
                return "research_execution_authoritative_package_deferred", [package_id], None
            if plan_ref:
                return "research_execution_authoritative_package_has_cross_case_plan", [package_id], None
            continue
        if package_id not in comparison_only_ids:
            return "research_execution_package_authority_unknown", [package_id], None
        if value == "adopted":
            adopted_comparison_ids.add(package_id)
            if str(package.get("recordId") or "") not in comparison_deep_reads:
                return "research_execution_cross_case_package_not_deep_read", [package_id], None
            if not plan_ref or plan_ref not in plan_map:
                return "research_execution_cross_case_plan_required", [package_id], None
        elif plan_ref:
            return "research_execution_unused_cross_case_plan", [package_id], None

    planned_source_ids: set[str] = set()
    for plan_id, item in plan_map.items():
        source_cases = set(_pick(item, "sourceCaseRefs", "source_case_refs") or [])
        source_ids = set(_pick(item, "sourcePackageIds", "source_package_ids") or [])
        target_ids = set(
            _pick(item, "targetCompanionPackageIds", "target_companion_package_ids") or []
        )
        additional_ids = set(
            _pick(item, "additionalCompanionPackageIds", "additional_companion_package_ids")
            or []
        )
        if allowed_evidence_refs is not None:
            plan_evidence = set(_pick(item, "evidenceRefs", "evidence_refs") or [])
            unknown_evidence = sorted(
                plan_evidence
                - allowed_evidence_refs
            )
            if unknown_evidence:
                return (
                    "research_execution_cross_case_evidence_unknown",
                    [plan_id + ": " + ", ".join(unknown_evidence[:5])],
                    None,
                )
            if (
                external_evidence_refs is not None
                and not plan_evidence & external_evidence_refs
            ):
                return (
                    "research_execution_cross_case_external_evidence_required",
                    [plan_id],
                    None,
                )
        if selected_case in source_cases or not source_cases.issubset(comparison_cases):
            return "research_execution_cross_case_source_mismatch", [plan_id], None
        if not source_ids.issubset(comparison_only_ids):
            return "research_execution_cross_case_package_mismatch", [plan_id], None
        if not target_ids.issubset(authoritative_ids):
            return "research_execution_target_companion_mismatch", [plan_id], None
        if not additional_ids.issubset(set(packages)):
            return "research_execution_additional_companion_unknown", [plan_id], None
        if planned_source_ids & source_ids:
            return "research_execution_cross_case_package_reused", [plan_id], None
        for package_id in source_ids:
            package_cases = set(packages[package_id].get("sourceCaseRefs") or [])
            if not package_cases & source_cases:
                return "research_execution_cross_case_source_package_unbound", [package_id], None
            decision = decision_map.get(package_id) or {}
            if decision.get("decision") != "adopted" or str(
                _pick(decision, "crossCasePlanRef", "cross_case_plan_ref") or ""
            ) != plan_id:
                return "research_execution_cross_case_decision_mismatch", [package_id], None
        planned_source_ids.update(source_ids)

    if planned_source_ids != adopted_comparison_ids:
        return (
            "research_execution_cross_case_plan_coverage_mismatch",
            sorted(adopted_comparison_ids ^ planned_source_ids)[:12],
            None,
        )
    plan_hash = stable_plan_hash(plan)
    structure_hash = stable_plan_structure_hash(plan)
    return (
        None,
        [],
        {
            "contractRef": contract_ref,
            "planHash": plan_hash,
            "structureHash": structure_hash,
            "selectedDesignCaseRef": selected_case,
            "packageDecisionCount": len(decision_map),
            "adoptedCrossCasePackageCount": len(adopted_comparison_ids),
            "crossCasePlanCount": len(plan_map),
            "noRawMaterial": True,
        },
    )


def stable_plan_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(plan).encode("utf-8")).hexdigest()


def stable_plan_structure_hash(plan: dict[str, Any]) -> str:
    """Hash only the Research decisions and cross-case dependency structure.

    Draft validation freezes source authority and design choices before Judge.  Rationale,
    concrete build application, evidence, implementation steps, verification, and failure-exit
    text remain editable so the Agent can apply Judge-driven corrections without changing the
    Research decision it already validated.
    """

    package_decisions = [
        {
            "packageId": str(_pick(item, "packageId", "package_id") or ""),
            "decision": str(item.get("decision") or ""),
            "crossCasePlanRef": str(
                _pick(item, "crossCasePlanRef", "cross_case_plan_ref") or ""
            ),
        }
        for item in list(_pick(plan, "packageDecisions", "package_decisions") or [])
        if isinstance(item, dict)
    ]
    package_decisions.sort(key=lambda item: item["packageId"])

    cross_case_plans = [
        {
            "planId": str(_pick(item, "planId", "plan_id") or ""),
            "sourceCaseRefs": _sorted_structure_refs(
                item,
                "sourceCaseRefs",
                "source_case_refs",
            ),
            "sourcePackageIds": _sorted_structure_refs(
                item,
                "sourcePackageIds",
                "source_package_ids",
            ),
            "targetCompanionPackageIds": _sorted_structure_refs(
                item,
                "targetCompanionPackageIds",
                "target_companion_package_ids",
            ),
            "additionalCompanionPackageIds": _sorted_structure_refs(
                item,
                "additionalCompanionPackageIds",
                "additional_companion_package_ids",
            ),
        }
        for item in list(
            _pick(plan, "crossCaseMechanismPlans", "cross_case_mechanism_plans") or []
        )
        if isinstance(item, dict)
    ]
    cross_case_plans.sort(key=lambda item: item["planId"])
    structure = {
        "contractRef": str(_pick(plan, "contractRef", "contract_ref") or ""),
        "selectedDesignCaseRef": str(
            _pick(plan, "selectedDesignCaseRef", "selected_design_case_ref") or ""
        ),
        "packageDecisions": package_decisions,
        "crossCaseMechanismPlans": cross_case_plans,
    }
    return hashlib.sha256(_stable_json(structure).encode("utf-8")).hexdigest()


def _sorted_structure_refs(item: dict[str, Any], camel: str, snake: str) -> list[str]:
    return sorted(str(value) for value in (_pick(item, camel, snake) or []) if value)


def _construct(
    *,
    authoritative_dedupe_query_refs: list[str],
    comparison_dedupe_query_refs: list[str],
    build_family_key: str,
    selected_knowledge_scope: str,
    selected_source_case_ref: str,
    game_patch: str,
    passive_tree_version: str,
    receipt_reader: Callable[[str], dict[str, Any] | None],
    db_path: Path | None,
) -> dict[str, Any]:
    if not build_family_key.startswith("bf-"):
        return _error("research_execution_family_invalid", "Use one stored bf- Family key.")
    if selected_knowledge_scope not in {"global_seed", "local_user"}:
        return _error("research_execution_scope_invalid", "Select a Create-visible scope.")
    if not selected_source_case_ref:
        return _error("research_execution_case_required", "Select one authoritative source case.")
    auth_receipts, error = _load_receipts(authoritative_dedupe_query_refs, receipt_reader)
    if error:
        return error
    comparison_receipts, error = _load_receipts(comparison_dedupe_query_refs, receipt_reader)
    if error:
        return error
    error = _validate_receipt_sessions(auth_receipts)
    if error:
        return error
    error = _validate_receipt_sessions(comparison_receipts)
    if error:
        return error
    if not auth_receipts:
        return _error("research_execution_authoritative_receipts_required", "Read the selected lane first.")

    auth_lanes = {_receipt_lane(item) for item in auth_receipts}
    if auth_lanes != {(selected_knowledge_scope, selected_source_case_ref)}:
        return _error(
            "research_execution_authoritative_lane_mismatch",
            "All authoritative receipts must use the selected scope and source case.",
        )
    comparison_lanes = {_receipt_lane(item) for item in comparison_receipts}
    if (selected_knowledge_scope, selected_source_case_ref) in comparison_lanes:
        return _error(
            "research_execution_comparison_lane_mismatch",
            "Comparison receipts must not repeat the selected design lane.",
        )
    if any(not scope or not case for scope, case in comparison_lanes):
        return _error(
            "research_execution_comparison_lane_unscoped",
            "Comparison receipts must bind one explicit source lane.",
        )

    all_receipts = [*auth_receipts, *comparison_receipts]
    revisions = {
        int(item["memoryRevision"]) if item.get("memoryRevision") is not None else -1
        for item in all_receipts
    }
    if len(revisions) != 1:
        return _error(
            "research_execution_memory_revision_mismatch",
            "All execution-contract receipts must use one memory revision.",
        )
    if any(not bool((item.get("result") or {}).get("createAuthorizing")) for item in all_receipts):
        return _error(
            "research_execution_receipt_not_authorizing",
            "Execution contracts accept only complete create_compact lane receipts.",
        )
    returned_families = {
        str(family.get("buildFamilyKey"))
        for item in all_receipts
        for family in (item.get("result") or {}).get("buildFamilies") or []
        if isinstance(family, dict) and family.get("buildFamilyKey")
    }
    requested_families = {
        str(value)
        for item in all_receipts
        for value in (item.get("result") or {}).get("requestedBuildFamilyKeys") or []
        if value
    }
    if build_family_key not in returned_families | requested_families:
        return _error(
            "research_execution_family_not_in_receipts",
            "The selected Family is absent from the supplied receipt chains.",
        )
    for key, expected in (
        ("requestedGamePatch", game_patch),
        ("requestedPassiveTreeVersion", passive_tree_version),
    ):
        actual = {
            str((item.get("result") or {}).get(key) or "")
            for item in all_receipts
            if (item.get("result") or {}).get(key)
        }
        if actual and actual != {expected}:
            return _error(
                "research_execution_version_mismatch",
                "All execution-contract receipts must use the selected patch and passive tree.",
            )

    lanes = [(selected_knowledge_scope, selected_source_case_ref), *sorted(comparison_lanes)]
    con = mature_learning.connect(db_path)
    try:
        rows_by_lane = {
            lane: _fetch_lane_records(
                con,
                build_family_key=build_family_key,
                knowledge_scope=lane[0],
                source_case_ref=lane[1],
                game_patch=game_patch,
                passive_tree_version=passive_tree_version,
            )
            for lane in lanes
        }
    finally:
        con.close()
    if not rows_by_lane[(selected_knowledge_scope, selected_source_case_ref)]:
        return _error(
            "research_execution_authoritative_lane_empty",
            "The selected source case has no Create-authorizing records.",
        )

    case_profiles = [
        _case_profile(
            build_family_key=build_family_key,
            knowledge_scope=scope,
            source_case_ref=case_ref,
            records=rows_by_lane[(scope, case_ref)],
            authority=(
                "authoritative"
                if (scope, case_ref) == (selected_knowledge_scope, selected_source_case_ref)
                else "comparison"
            ),
        )
        for scope, case_ref in lanes
    ]
    package_rows: dict[str, dict[str, Any]] = {}
    for lane, records in rows_by_lane.items():
        for row in records:
            record_id = str(row["record_id"])
            package = package_rows.get(record_id)
            if package is None:
                package = _record_package(
                    row,
                    build_family_key=build_family_key,
                    selected_case_ref=selected_source_case_ref,
                )
                package_rows[record_id] = package
            if lane[1] not in package["sourceCaseRefs"]:
                package["sourceCaseRefs"].append(lane[1])
            if lane == (selected_knowledge_scope, selected_source_case_ref):
                package["authority"] = "authoritative"
            elif package["authority"] == "authoritative":
                package["authority"] = "authoritative_and_comparison"
    packages = sorted(package_rows.values(), key=lambda item: (item["authority"], item["recordKind"], item["packageId"]))
    if len(packages) > MAX_CONTRACT_PACKAGES:
        return _error(
            "research_execution_contract_too_large",
            f"The selected lanes expose {len(packages)} packages; narrow comparison lanes before constructing the contract.",
        )
    for package in packages:
        package["sourceCaseRefs"] = sorted(package["sourceCaseRefs"])
    review_ids = [package["packageId"] for package in packages]
    revision = next(iter(revisions))
    contract_core = {
        "contractVersion": CONTRACT_VERSION,
        "memoryRevision": revision,
        "buildFamilyKey": build_family_key,
        "gamePatch": game_patch,
        "passiveTreeVersion": passive_tree_version,
        "selectedKnowledgeScope": selected_knowledge_scope,
        "selectedDesignCaseRef": selected_source_case_ref,
        "comparisonCaseRefs": sorted(case for _scope, case in comparison_lanes),
        "caseProfiles": case_profiles,
        "packages": packages,
        "reviewRequiredPackageIds": review_ids,
    }
    contract_ref = "rec-" + hashlib.sha256(_stable_json(contract_core).encode("utf-8")).hexdigest()[:16]
    authoritative_deep_reads = sorted(
        {
            str(record_id)
            for item in auth_receipts
            for record_id in (item.get("result") or {}).get("deepReadRecordIds") or []
            if record_id
        }
    )
    comparison_deep_reads = sorted(
        {
            str(record_id)
            for item in comparison_receipts
            for record_id in (item.get("result") or {}).get("deepReadRecordIds") or []
            if record_id
        }
    )
    output = {
        "status": "ready",
        "contractRef": contract_ref,
        **contract_core,
        "authoritativeDeepReadRecordIds": authoritative_deep_reads,
        "comparisonDeepReadRecordIds": comparison_deep_reads,
        "contractRules": {
            "everyPackageRequiresDecision": True,
            "comparisonAdoptionRequiresCrossCasePlan": True,
            "crossCasePlanRequiresTargetCompanions": True,
            "sourceAuthorityMustBePreserved": True,
            "contractDoesNotAuthorizeAutomaticBuildAssembly": True,
        },
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }
    if _unsafe(output):
        return _error(
            "research_execution_contract_unsafe",
            "The execution contract failed copy-safety validation.",
        )
    return output


def _load_receipts(
    refs: list[str],
    reader: Callable[[str], dict[str, Any] | None],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if len(refs) != len(set(refs)):
        return [], _error("research_execution_receipt_duplicate", "Receipt refs must be unique.")
    receipts: list[dict[str, Any]] = []
    for ref in refs:
        if not re.fullmatch(r"dq-[0-9a-f]{16}", str(ref or "")):
            return [], _error("research_execution_receipt_invalid", "Use typed dq- receipt refs.")
        receipt = reader(ref)
        if receipt is None:
            return [], _error("research_execution_receipt_missing", f"Receipt {ref} is unavailable.")
        receipts.append(receipt)
    return receipts, None


def _validate_receipt_sessions(receipts: list[dict[str, Any]]) -> dict[str, Any] | None:
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for receipt in receipts:
        retrieval_ref = str(receipt.get("retrievalRef") or "")
        if not retrieval_ref:
            return _error(
                "research_execution_retrieval_incomplete",
                "Every receipt must belong to one bounded retrieval session.",
            )
        sessions[retrieval_ref].append(receipt)
    for values in sessions.values():
        page_counts = {int(item.get("pageCount") or 0) for item in values}
        manifests = {str(item.get("manifestHash") or "") for item in values}
        indexes = {int(item.get("pageIndex") or 0) for item in values}
        if len(page_counts) != 1 or len(manifests) != 1:
            return _error(
                "research_execution_retrieval_conflict",
                "Receipt pages disagree on page count or manifest hash.",
            )
        page_count = next(iter(page_counts))
        if indexes != set(range(page_count)) or not any(item.get("retrievalComplete") for item in values):
            return _error(
                "research_execution_retrieval_incomplete",
                "Provide every page from zero through the terminal receipt.",
            )
    return None


def _receipt_lane(receipt: dict[str, Any]) -> tuple[str, str]:
    result = receipt.get("result") if isinstance(receipt.get("result"), dict) else {}
    return (
        str(result.get("selectedKnowledgeScope") or ""),
        str(result.get("selectedSourceCaseRef") or ""),
    )


def _fetch_lane_records(
    con: sqlite3.Connection,
    *,
    build_family_key: str,
    knowledge_scope: str,
    source_case_ref: str,
    game_patch: str,
    passive_tree_version: str,
) -> list[sqlite3.Row]:
    return list(
        con.execute(
            """
            SELECT DISTINCT record.record_id, record.record_kind, record.title, record.summary,
                   record.component_keys, record.component_mentions, record.conditions,
                   record.failure_conditions, record.typed_payload, record.projection_hash
            FROM deep_research_records AS record
            JOIN deep_research_record_evidence AS evidence
              ON evidence.knowledge_scope = record.knowledge_scope
             AND evidence.knowledge_key = record.knowledge_key
            JOIN research_source_provenance AS provenance
              ON provenance.knowledge_scope = evidence.knowledge_scope
             AND provenance.source_case_ref = evidence.source_case_ref
            WHERE record.build_family_key = ?
              AND record.knowledge_scope = ?
              AND evidence.source_case_ref = ?
              AND record.game_patch = ?
              AND record.passive_tree_version = ?
              AND record.visibility = 'creator_visible'
              AND record.split = 'train_context'
              AND record.copy_safety_state = 'passed'
              AND record.status = 'valid'
              AND record.superseded_by_id IS NULL
              AND record.record_schema_version = 2
              AND record.source_state_scope IN ('active_state', 'state_agnostic')
              AND evidence.source_state_scope IN ('active_state', 'state_agnostic')
              AND record.projection_hash IS NOT NULL
              AND evidence.accepted_projection_hash = record.projection_hash
              AND COALESCE(json_extract(record.typed_payload, '$.availability'), 'standard') = 'standard'
            ORDER BY record.record_kind, record.record_id
            """,
            (
                build_family_key,
                knowledge_scope,
                source_case_ref,
                game_patch,
                passive_tree_version,
            ),
        ).fetchall()
    )


def _case_profile(
    *,
    build_family_key: str,
    knowledge_scope: str,
    source_case_ref: str,
    records: list[sqlite3.Row],
    authority: str,
) -> dict[str, Any]:
    kinds = Counter(str(row["record_kind"]) for row in records)
    resources: set[str] = set()
    core_skills: set[str] = set()
    unique_components: set[str] = set()
    defense_components: set[str] = set()
    passive_components: set[str] = set()
    skill_duties: dict[str, set[str]] = defaultdict(set)
    gear_roles: set[tuple[str, str]] = set()
    ascendancy_components: set[str] = set()
    jewel_states: Counter[str] = Counter()
    support_count = 0
    condition_count = 0
    failure_count = 0
    for row in records:
        typed = _loads(row["typed_payload"], {})
        resources.update(str(value) for value in typed.get("resourceMechanisms") or [])
        core_skills.update(str(value) for value in typed.get("familyCoreSkillKeys") or [])
        support_count += len(typed.get("supportPackages") or [])
        for item in typed.get("gearResponsibilities") or []:
            if isinstance(item, dict):
                gear_roles.add(
                    (
                        str(item.get("componentKey") or ""),
                        str(item.get("responsibilityType") or ""),
                    )
                )
        for item in typed.get("ascendancyResponsibilities") or []:
            if isinstance(item, dict) and item.get("componentKey"):
                ascendancy_components.add(str(item["componentKey"]))
        for item in typed.get("jewelSocketStates") or []:
            if isinstance(item, dict) and item.get("state"):
                jewel_states[str(item["state"])] += 1
        condition_count += len(_loads(row["conditions"], []))
        failure_count += len(_loads(row["failure_conditions"], []))
        for mention in _loads(row["component_mentions"], []):
            if not isinstance(mention, dict) or not mention.get("component_key"):
                continue
            key = str(mention["component_key"])
            role = str(mention.get("role") or "")
            if role == "unique_enabler":
                unique_components.add(key)
            elif role == "defense_layer":
                defense_components.add(key)
            elif role in {"passive_anchor", "keystone_transformer"}:
                passive_components.add(key)
            if role in {
                "primary_damage",
                "clear_skill",
                "boss_skill",
                "generator",
                "payoff",
                "reservation",
                "defensive_buff",
                "movement",
                "trigger_host",
                "secondary_skill",
                "triggered_payload",
                "control_skill",
            }:
                skill_duties[role].add(key)
    core = {
        "buildFamilyKey": build_family_key,
        "knowledgeScope": knowledge_scope,
        "sourceCaseRef": source_case_ref,
        "authority": authority,
        "recordCount": len(records),
        "recordKindCounts": dict(sorted(kinds.items())),
        "coreSkillKeys": sorted(core_skills),
        "skillDuties": {key: sorted(values) for key, values in sorted(skill_duties.items())},
        "supportPackageCount": support_count,
        "resourceMechanisms": sorted(resources),
        "uniqueComponentKeys": sorted(unique_components),
        "gearResponsibilityKeys": [
            {"componentKey": component, "responsibilityType": role}
            for component, role in sorted(gear_roles)
            if component and role
        ],
        "ascendancyComponentKeys": sorted(ascendancy_components),
        "defenseLayerComponentKeys": sorted(defense_components),
        "passiveAnchorComponentKeys": sorted(passive_components),
        "jewelStateCounts": dict(sorted(jewel_states.items())),
        "conditionCount": condition_count,
        "failureConditionCount": failure_count,
    }
    return {
        "caseProfileRef": "rcp-" + hashlib.sha256(_stable_json(core).encode("utf-8")).hexdigest()[:16],
        **core,
    }


def _record_package(
    row: sqlite3.Row,
    *,
    build_family_key: str,
    selected_case_ref: str,
) -> dict[str, Any]:
    record_id = str(row["record_id"])
    typed = _loads(row["typed_payload"], {})
    selected_typed = {
        key: deepcopy(typed[key])
        for key in _TYPED_PACKAGE_KEYS
        if key in typed
    }
    jewel_states = Counter(
        str(item.get("state"))
        for item in typed.get("jewelSocketStates") or []
        if isinstance(item, dict) and item.get("state")
    )
    component_responsibilities = [
        {
            "componentKey": str(item.get("component_key")),
            "role": str(item.get("role")),
        }
        for item in _loads(row["component_mentions"], [])
        if isinstance(item, dict)
        and item.get("component_key")
        and item.get("role") in _COMPONENT_ROLES
    ]
    package_id = "rep-" + hashlib.sha256(
        f"{build_family_key}|{record_id}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "packageId": package_id,
        "recordId": record_id,
        "recordKind": str(row["record_kind"]),
        "title": str(row["title"]),
        "summary": str(row["summary"]),
        "componentKeys": _loads(row["component_keys"], []),
        "componentResponsibilities": component_responsibilities,
        "typedResponsibilities": selected_typed,
        "jewelStateCounts": dict(sorted(jewel_states.items())),
        "conditions": _loads(row["conditions"], []),
        "failureConditions": _loads(row["failure_conditions"], []),
        "projectionHash": str(row["projection_hash"]),
        "sourceCaseRefs": [],
        "authority": "comparison",
        "reviewRequirement": "required_review",
        "selectedCaseHint": selected_case_ref,
    }


def _pick(payload: dict[str, Any], camel: str, snake: str) -> Any:
    return payload[camel] if camel in payload else payload.get(snake)


def _loads(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    return parsed


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _unsafe(value: Any) -> bool:
    return bool(
        copy_safety.find_forbidden_paths(value)
        or copy_safety.durable_knowledge_flags(value)
        or copy_safety.contains_raw_url(value)
    )


def _error(error_code: str, caveat: str) -> dict[str, Any]:
    return {
        "status": "error",
        "errorCode": error_code,
        "caveats": [caveat],
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }
