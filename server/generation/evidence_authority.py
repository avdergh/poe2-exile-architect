"""Separate receipt identity checks, external Agent review and unverified design inputs.

Only validated run-fresh Research sources are currently internally resolvable here. General
compute/graph/web ToolReferences have no receipt registry: explicit review remains an Agent
assertion, never proof of tool execution, semantic correctness or PoB legality.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from . import models


AUDIT_VERSION = "generation_evidence_v1"
_INTERNAL_TOOLS = {"query_research_memory", "construct_research_execution_contract"}
_NON_MECHANISM_TOOLS = _INTERNAL_TOOLS | {
    "query_public_learning_memory",
    "get_freshness_report",
    "get_prices",
}


def normalized_refs(values: list[Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for value in values:
        parsed = (
            value
            if isinstance(value, models.ToolReference)
            else models.ToolReference.model_validate(value)
        )
        row = parsed.model_dump(mode="json", by_alias=True)
        if parsed.query_ref in result and result[parsed.query_ref] != row:
            raise ValueError("conflicting_tool_evidence_reference")
        result[parsed.query_ref] = row
    return result


def tool_name(row: dict[str, Any]) -> str:
    return str(row["toolName"]).casefold().split("__")[-1]


def external_refs(values: list[Any]) -> set[str]:
    return {
        ref
        for ref, row in normalized_refs(values).items()
        if row["evidenceKind"] == "agent_reviewed" and tool_name(row) not in _NON_MECHANISM_TOOLS
    }


def validate_internal_claims(values: list[Any], trusted_refs: set[str]) -> str | None:
    try:
        rows = normalized_refs(values)
    except (ValueError, models.ValidationError):
        return "invalid_tool_evidence_reference"
    for ref, row in rows.items():
        expected_tool = (
            "query_research_memory"
            if ref.startswith("dq-")
            else "construct_research_execution_contract"
            if ref.startswith("rec-")
            else None
        )
        if row["evidenceKind"] == "internal_receipt" and (
            ref not in trusted_refs or tool_name(row) != expected_tool
        ):
            return "tool_evidence_receipt_unverified"
    return None


def blueprint_audit(
    blueprint: models.MechanismBlueprint,
    values: list[Any],
    trusted_refs: set[str],
) -> tuple[str | None, dict[str, Any] | None]:
    error = validate_internal_claims(values, trusted_refs)
    if error:
        return error, None
    refs = normalized_refs(values)
    reviewed = external_refs(values)
    used = {ref for claim in blueprint.claims for ref in claim.source_refs}
    if used - (set(refs) | trusted_refs):
        return "mechanism_blueprint_evidence_unresolved", None
    for claim in blueprint.claims:
        unverified = set(claim.source_refs) - (trusted_refs | reviewed)
        if unverified and claim.status not in {"hypothesis", "unknown"}:
            return "mechanism_blueprint_evidence_unverified", None
        if unverified and claim.status == "hypothesis" and not claim.verification_tasks:
            return "mechanism_blueprint_hypothesis_verification_required", None
    audit = {
        "version": AUDIT_VERSION,
        "sources": [
            {
                "sourceRef": ref,
                "evidenceKind": "internal_receipt"
                if ref in trusted_refs
                else "agent_reviewed"
                if ref in reviewed
                else "unverified",
                "toolReference": refs.get(ref),
            }
            for ref in sorted(used)
        ],
        "semanticTruthVerified": False,
        "numericLegalityVerified": False,
    }
    return None, audit


def audit_hash(audit: dict[str, Any]) -> str:
    audit = deepcopy(audit)
    for row in audit.get("sources", []):
        if isinstance(row.get("toolReference"), dict):
            row["toolReference"].pop("summary", None)
    for row in audit.get("toolReferences") or []:
        row.pop("summary", None)
    return hashlib.sha256(
        json.dumps(
            audit,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def audit_matches(
    marker: dict[str, Any],
    blueprint: models.MechanismBlueprint,
    values: list[Any],
) -> bool:
    """Compare against already validated authority; never infer new receipt authority here."""
    audit = marker.get("evidenceAudit")
    if not isinstance(audit, dict) or audit.get("version") != AUDIT_VERSION:
        return False
    try:
        if marker.get("evidenceAuditHash") != audit_hash(audit):
            return False
        trusted = {
            row["sourceRef"]
            for row in audit["sources"]
            if row["evidenceKind"] == "internal_receipt"
        }
        # Only Blueprint-used refs belong to this marker. Additional final tool diagnostics do
        # not revise the mechanism; the Draft validator separately checks all internal claims.
        used = {ref for claim in blueprint.claims for ref in claim.source_refs}
        selected = [row for ref, row in normalized_refs(values).items() if ref in used]
        error, rebuilt = blueprint_audit(blueprint, selected, trusted)
        return error is None and audit_hash(rebuilt) == audit_hash(audit)
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def design_tool_refs(candidate: models.PrototypeBuildCandidate) -> list[dict[str, Any]]:
    used = {
        ref
        for claim in (candidate.mechanism_blueprint.claims if candidate.mechanism_blueprint else [])
        for ref in claim.source_refs
    }
    plan = candidate.research_execution_plan
    if plan:
        used.update(
            ref
            for decision in plan.package_decisions
            for ref in decision.verification_evidence_refs
        )
        used.update(
            ref
            for cross_case in plan.cross_case_mechanism_plans
            for ref in cross_case.evidence_refs
        )
    refs = normalized_refs(candidate.tool_references)
    return [refs[ref] for ref in sorted(used & set(refs))]


def design_tools_hash(candidate: models.PrototypeBuildCandidate) -> str:
    return audit_hash({"toolReferences": design_tool_refs(candidate)})


def design_evidence_uses(
    plan: models.ResearchExecutionPlan | dict[str, Any] | None,
) -> dict[str, dict[str, list[str]]]:
    """Preserve ownership of every execution source, including direct Research references."""
    if plan is None:
        return {"packages": {}, "crossCasePlans": {}}
    parsed = (
        plan
        if isinstance(plan, models.ResearchExecutionPlan)
        else models.ResearchExecutionPlan.model_validate(plan)
    )
    return {
        "packages": {
            item.package_id: sorted(item.verification_evidence_refs)
            for item in parsed.package_decisions
        },
        "crossCasePlans": {
            item.plan_id: sorted(item.evidence_refs) for item in parsed.cross_case_mechanism_plans
        },
    }


def evidence_uses_preserved(
    plan: models.ResearchExecutionPlan | dict[str, Any] | None,
    original: Any,
) -> bool:
    current = design_evidence_uses(plan)
    if not isinstance(original, dict) or set(original) != set(current):
        return False
    for kind, subjects in current.items():
        previous = original[kind]
        if not isinstance(previous, dict) or set(previous) != set(subjects):
            return False
        for subject, refs in previous.items():
            if (
                not isinstance(refs, list)
                or any(not isinstance(ref, str) for ref in refs)
                or refs != sorted(set(refs))
                or not set(refs) <= set(subjects[subject])
            ):
                return False
    return True


def design_tools_match(
    candidate: models.PrototypeBuildCandidate,
    marker: dict[str, Any],
    *,
    original_evidence_uses: dict[str, Any] | None = None,
) -> bool:
    """Keep original design evidence immutable while allowing post-Judge corroboration."""
    original_refs = marker.get("designToolRefs")
    if not isinstance(original_refs, list) or any(
        not isinstance(ref, str) for ref in original_refs
    ):
        return False
    if original_refs != sorted(set(original_refs)):
        return False
    # A legacy marker may borrow ownership only from its authenticated Judge bundle, never
    # from the candidate now being submitted. Active legacy Drafts must be fully revalidated.
    uses = marker.get("designEvidenceUses", original_evidence_uses)
    if "designEvidenceUses" in marker and (
        not isinstance(uses, dict)
        or marker.get("designEvidenceUsesHash") != audit_hash(uses)
        or (original_evidence_uses is not None and uses != original_evidence_uses)
    ):
        return False
    if not evidence_uses_preserved(candidate.research_execution_plan, uses):
        return False
    refs = {row["queryRef"]: row for row in design_tool_refs(candidate)}
    if not set(original_refs) <= set(refs):
        return False
    return audit_hash({"toolReferences": [refs[ref] for ref in original_refs]}) == marker.get(
        "designToolsHash"
    )
