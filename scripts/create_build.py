"""Phase 5 Agent-led prototype helper CLI."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import wraps
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import paths  # noqa: E402
from server.generation import (  # noqa: E402
    canonicalize,
    evidence_authority,
    mechanism_evidence,
    mechanism_signature,
    models,
    progression_provenance,
    prototype,
    retry,
    run_store,
)
from server.knowledge import component_keys, research_execution, research_memory  # noqa: E402
from server.knowledge import db as knowledge_db  # noqa: E402


def _serialized_design_validation(function):
    """Keep validated design markers stable across Judge and artifact publication."""

    @wraps(function)
    def guarded(run_id, run_token, *args, **kwargs):
        try:
            bound_run = run_store.load_bound_run(run_id, run_token)
        except run_store.RunStoreError as exc:
            return models.rejected(exc.code)
        lock_path = bound_run.run_dir / "evaluation-lock"
        if not run_store.acquire_generation_lock(lock_path):
            return models.rejected("generation_evaluation_in_progress")
        try:
            # A saved artifact has frozen its selection; new design revisions belong to a new run.
            if bound_run.artifact_selection_path.exists():
                return models.rejected("final_artifact_already_exists")
            try:
                run_store.load_bound_run(run_id, run_token)
            except run_store.RunStoreError as exc:
                return models.rejected(exc.code)
            return function(run_id, run_token, *args, **kwargs)
        finally:
            run_store.release_generation_lock(lock_path)

    return guarded


def start_generation_run(memory_mode: str = "memory_assisted") -> dict[str, Any]:
    """MCP-safe wrapper for the CLI ``start-run`` operation."""

    if memory_mode not in {"standard", "no_memory", "memory_assisted"}:
        return models.rejected("invalid_memory_mode")
    payload = _start_run(argparse.Namespace(memory_mode=memory_mode))
    payload.pop("agentOutputFile", None)
    payload.pop("reviewResultFile", None)
    payload["storage"] = "managed_user_data"
    return payload


@_serialized_design_validation
def validate_generation_blueprint(
    run_id: str,
    run_token: str,
    blueprint_draft: dict[str, Any],
) -> dict[str, Any]:
    """Validate and bind one knowledge-grounded free-form mechanism blueprint.

    This runs after Research synthesis and before Create mutates the active PoB.  It stores a safe
    blueprint receipt in managed run data; it does not select gear or change the build.
    """

    try:
        bound_run = run_store.load_bound_run(run_id, run_token)
    except run_store.RunStoreError as exc:
        return models.rejected(exc.code)
    if run_store.generation_contract_upgrade_required(bound_run.manifest):
        return models.rejected("generation_contract_upgrade_requires_restart")
    if not isinstance(blueprint_draft, dict):
        return models.rejected("invalid_input")
    raw_safety = models.validate_no_raw_or_hidden_reasoning(blueprint_draft)
    if raw_safety.get("status") != "accepted":
        return raw_safety
    try:
        draft = models.GenerationMechanismBlueprintDraft.model_validate(blueprint_draft)
    except models.ValidationError as exc:
        return models.schema_error(exc, max_errors=20)
    research_use = draft.research_memory_use
    family_binding = _read_family_discovery_binding(bound_run.run_dir)
    memory_mode = str((bound_run.manifest.get("experimentContext") or {}).get("memoryMode") or "")
    if memory_mode == "memory_assisted":
        if family_binding is None:
            return models.rejected("generation_family_discovery_required")
        binding_error = _family_binding_research_error(family_binding, research_use)
        if binding_error is not None:
            return models.rejected(binding_error)

    execution_contract: dict[str, Any] | None = None
    execution_summary: dict[str, Any] | None = None
    tool_references = [
        item.model_dump(mode="json", by_alias=True) for item in draft.tool_references
    ]
    try:
        evidence_authority.normalized_refs(tool_references)
    except ValueError:
        return models.rejected("invalid_tool_evidence_reference")
    if research_use is not None:
        research_payload = research_use.model_dump(mode="json", by_alias=True)
        premise_error, _summary, caveats = progression_provenance.validate_research_use_receipts(
            research_memory_use=research_payload,
            receipt_reader=research_memory.ResearchMemoryService().read_query_receipt,
            not_before=str(bound_run.manifest.get("startedAt") or ""),
        )
        if premise_error:
            return models.rejected(premise_error, caveats=caveats)
        if research_use.retrieval_outcome == "matched":
            execution_contract = research_execution.construct_from_research_use(
                research_payload,
                game_patch=draft.version_context.game_patch,
                passive_tree_version=draft.version_context.passive_tree_version,
            )
            if execution_contract.get("status") != "ready":
                return models.rejected(
                    str(
                        execution_contract.get("errorCode")
                        or "research_execution_contract_unavailable"
                    ),
                    caveats=list(execution_contract.get("caveats") or []),
                )
            if draft.research_execution_plan is None:
                return models.rejected("research_execution_plan_required")
            execution_error, execution_caveats, execution_summary = (
                research_execution.validate_research_execution_plan(
                    draft.research_execution_plan.model_dump(mode="json", by_alias=True),
                    execution_contract,
                    allowed_evidence_refs=_execution_evidence_refs(
                        tool_references=tool_references,
                        research_use=research_payload,
                        contract=execution_contract,
                    ),
                    external_evidence_refs=_execution_external_evidence_refs(tool_references),
                )
            )
            if execution_error:
                return models.rejected(execution_error, caveats=execution_caveats)
            subject_error, subject_caveats = research_execution.validate_insight_decision_subjects(
                research_payload,
                execution_contract,
            )
            if subject_error:
                return models.rejected(subject_error, caveats=subject_caveats)

    evidence_error, evidence_audit = evidence_authority.blueprint_audit(
        draft.mechanism_blueprint, tool_references,
        _research_evidence_refs(
            research_use.model_dump(mode="json", by_alias=True) if research_use else {},
            execution_contract or {},
        ),
    )
    if evidence_error:
        return models.rejected(evidence_error)

    blueprint_hash = models.mechanism_blueprint_hash(draft.mechanism_blueprint)
    blueprint_ref = f"gbp-{blueprint_hash[:16]}"
    validated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schemaVersion": 1,
        "evidenceAudit": evidence_audit,
        "evidenceAuditHash": evidence_authority.audit_hash(evidence_audit),
        "blueprintRef": blueprint_ref,
        "blueprintHash": blueprint_hash,
        "candidateId": draft.candidate_id,
        "researchMemoryRef": draft.version_context.research_memory_ref,
        "researchExecutionContractRef": (
            execution_contract.get("contractRef") if execution_contract else None
        ),
        "researchExecutionStructureHash": (
            (execution_summary or {}).get("structureHash") if execution_summary else None
        ),
        "mechanismBlueprint": draft.mechanism_blueprint.model_dump(mode="json", by_alias=True),
        "validatedAt": validated_at,
        "noRawMaterial": True,
    }
    marker = {key: value for key, value in payload.items() if key != "mechanismBlueprint"}
    if not _write_json_atomic(bound_run.run_dir / "mechanism-blueprint.json", payload):
        return models.rejected("run_state_write_failed")
    if not _write_json_atomic(bound_run.run_dir / "mechanism-blueprint-validation.json", marker):
        return models.rejected("run_state_write_failed")
    return {
        "status": "accepted",
        "validationOnly": True,
        "candidateId": draft.candidate_id,
        "blueprintRef": blueprint_ref,
        "blueprintHash": blueprint_hash,
        "coverage": {item.axis: item.status for item in draft.mechanism_blueprint.coverage},
        "evidenceAudit": evidence_audit,
        "unresolvedQuestionCount": len(draft.mechanism_blueprint.unresolved_questions),
        "researchExecutionContractRef": marker["researchExecutionContractRef"],
        "noRawMaterial": True,
        "noHiddenChainOfThought": True,
    }


def validate_generation_output(
    run_id: str,
    run_token: str,
    agent_output: dict[str, Any],
) -> dict[str, Any]:
    """Persist one bound safe submission and validate it without consuming the run."""

    return _submit_generation_output(
        run_id=run_id,
        run_token=run_token,
        agent_output=agent_output,
        consume=False,
    )


@_serialized_design_validation
def validate_generation_draft(
    run_id: str,
    run_token: str,
    agent_output_draft: dict[str, Any],
    *,
    active_engine: Any | None = None,
    offense_skill_group_index: int | None = None,
    expected_skill_name: str | None = None,
) -> dict[str, Any]:
    """Validate prompt, candidate and Research use before the first formal Judge attempt."""

    canonical = _canonical_run_id(run_id)
    if canonical is None:
        return models.rejected("invalid_run_manifest")
    run_dir = _runs_dir() / canonical
    output_path = run_dir / "agent-output.json"
    manifest = _read_run_manifest(run_dir / "run-manifest.json", canonical, output_path)
    if manifest is None:
        return models.rejected("invalid_run_manifest")
    if manifest["runContext"]["runToken"] != run_token:
        return models.rejected("run_binding_mismatch")
    if run_store.run_expired(manifest["startedAt"]):
        return models.rejected("run_expired")
    if run_store.generation_contract_upgrade_required(manifest):
        return models.rejected("generation_contract_upgrade_requires_restart")
    if not isinstance(agent_output_draft, dict):
        return models.rejected("invalid_input")
    raw_safety = models.validate_no_raw_or_hidden_reasoning(agent_output_draft)
    if raw_safety.get("status") != "accepted":
        return raw_safety
    binding_error = _run_binding_error(agent_output_draft, manifest)
    if binding_error is not None:
        return binding_error
    try:
        draft = models.GenerationDraft.model_validate(
            {
                "agentRefinedBuildPrompt": agent_output_draft.get("agentRefinedBuildPrompt"),
                "prototypeBuildCandidate": agent_output_draft.get("prototypeBuildCandidate"),
            }
        )
    except models.ValidationError as exc:
        return models.schema_error(exc, max_errors=20)

    try:
        evidence_authority.normalized_refs(draft.prototype_build_candidate.tool_references)
    except ValueError:
        return models.rejected("invalid_tool_evidence_reference")
    research_use = draft.prototype_build_candidate.research_memory_use
    family_binding = _read_family_discovery_binding(run_dir)
    memory_mode = str((manifest.get("experimentContext") or {}).get("memoryMode") or "")
    if memory_mode == "memory_assisted":
        if family_binding is None:
            return models.rejected("generation_family_discovery_required")
        binding_error = _family_binding_research_error(family_binding, research_use)
        if binding_error is not None:
            return models.rejected(binding_error)
    if research_use is not None:
        premise_error, _summary, caveats = progression_provenance.validate_research_use_receipts(
            research_memory_use=research_use.model_dump(mode="json", by_alias=True),
            receipt_reader=research_memory.ResearchMemoryService().read_query_receipt,
            not_before=manifest["startedAt"],
        )
        if premise_error:
            return models.rejected(premise_error, caveats=caveats)
        if research_use.retrieval_outcome == "matched":
            execution_contract = research_execution.construct_from_research_use(
                research_use.model_dump(mode="json", by_alias=True),
                game_patch=draft.prototype_build_candidate.version_context.game_patch,
                passive_tree_version=(
                    draft.prototype_build_candidate.version_context.passive_tree_version
                ),
            )
            if execution_contract.get("status") != "ready":
                return models.rejected(
                    str(
                        execution_contract.get("errorCode")
                        or "research_execution_contract_unavailable"
                    ),
                    caveats=list(execution_contract.get("caveats") or []),
                )
            execution_plan = draft.prototype_build_candidate.research_execution_plan
            if execution_plan is None:
                return models.rejected("research_execution_plan_required")
            execution_error, execution_caveats, execution_summary = (
                research_execution.validate_research_execution_plan(
                    execution_plan.model_dump(mode="json", by_alias=True),
                    execution_contract,
                    allowed_evidence_refs=_execution_evidence_refs(
                        tool_references=[
                            item.model_dump(mode="json", by_alias=True)
                            for item in draft.prototype_build_candidate.tool_references
                        ],
                        research_use=research_use.model_dump(mode="json", by_alias=True),
                        contract=execution_contract,
                    ),
                    external_evidence_refs=_execution_external_evidence_refs(
                        [
                            item.model_dump(mode="json", by_alias=True)
                            for item in draft.prototype_build_candidate.tool_references
                        ]
                    ),
                )
            )
            if execution_error:
                return models.rejected(execution_error, caveats=execution_caveats)
            subject_error, subject_caveats = research_execution.validate_insight_decision_subjects(
                research_use.model_dump(mode="json", by_alias=True),
                execution_contract,
            )
            if subject_error:
                return models.rejected(subject_error, caveats=subject_caveats)
        else:
            execution_contract = None
            execution_summary = None
    else:
        execution_contract = None
        execution_summary = None
    evidence_error = evidence_authority.validate_internal_claims(
        draft.prototype_build_candidate.tool_references,
        _research_evidence_refs(
            research_use.model_dump(mode="json", by_alias=True) if research_use else {},
            execution_contract or {},
        ),
    )
    if evidence_error:
        return models.rejected(evidence_error)
    blueprint_error, blueprint_marker = _validate_candidate_blueprint_use(
        draft.prototype_build_candidate,
        run_dir=run_dir,
        manifest=manifest,
        require_draft_binding=False,
    )
    if blueprint_error:
        return models.rejected(blueprint_error)
    signature_required = bool(
        (manifest.get("experimentContext") or {}).get("mechanismBlueprintRequired")
    )
    if (offense_skill_group_index is None) != (expected_skill_name is None):
        return models.rejected("generation_mechanism_signature_target_incomplete")
    if offense_skill_group_index is None:
        if signature_required:
            return models.rejected("generation_mechanism_signature_target_required")
        observed_signature: dict[str, Any] = {
            "signatureHash": None,
            "signature": None,
            "calculationContext": None,
            "stateHash": None,
        }
    else:
        if active_engine is None:
            return models.rejected("generation_mechanism_signature_engine_required")
        observed_signature = mechanism_signature.observe(
            active_engine,
            {
                "offenseSkillGroupIndex": int(offense_skill_group_index),
                "activeSkillName": str(expected_skill_name or ""),
            },
        )
        if not observed_signature.get("ok"):
            return models.rejected(
                str(
                    observed_signature.get("errorCode")
                    or "generation_mechanism_signature_inspection_failed"
                )
            )
        adoption_error = _adopted_primary_skill_package_error(
            execution_contract=execution_contract,
            execution_plan=draft.prototype_build_candidate.research_execution_plan,
            observed_signature=dict(observed_signature.get("signature") or {}),
        )
        if adoption_error:
            return models.rejected(adoption_error)
    evidence_uses = evidence_authority.design_evidence_uses(draft.prototype_build_candidate.research_execution_plan)
    marker = {
        "schemaVersion": 3,
        "candidateId": draft.prototype_build_candidate.candidate_id,
        "researchMemoryRef": draft.prototype_build_candidate.version_context.research_memory_ref,
        "validatedAt": datetime.now(timezone.utc).isoformat(),
        "researchPremiseAuditReady": research_use is not None,
        "researchExecutionContractRef": (
            execution_contract.get("contractRef") if execution_contract else None
        ),
        "researchExecutionPlanHash": (
            (execution_summary or {}).get("planHash") if execution_summary else None
        ),
        "researchExecutionStructureHash": (
            (execution_summary or {}).get("structureHash") if execution_summary else None
        ),
        "researchDecisionHash": mechanism_evidence.research_decision_hash(
            research_use, draft.prototype_build_candidate.research_execution_plan
        ),
        "mechanismBlueprintRef": (
            blueprint_marker.get("blueprintRef") if blueprint_marker else None
        ),
        "mechanismBlueprintHash": (
            blueprint_marker.get("blueprintHash") if blueprint_marker else None
        ),
        "evidenceAuditHash": (
            blueprint_marker.get("evidenceAuditHash") if blueprint_marker else None
        ),
        "designToolsHash": evidence_authority.design_tools_hash(draft.prototype_build_candidate),
        "designToolRefs": [row["queryRef"] for row in evidence_authority.design_tool_refs(draft.prototype_build_candidate)],
        "designEvidenceUses": evidence_uses,
        "designEvidenceUsesHash": evidence_authority.audit_hash(evidence_uses),
        "mechanismSignatureHash": observed_signature["signatureHash"],
        "mechanismSignature": observed_signature["signature"],
        "calculationContext": observed_signature["calculationContext"],
        "buildStateHash": observed_signature["stateHash"],
        "familyDiscoveryRef": (
            family_binding.get("familyDiscoveryRef") if family_binding else None
        ),
        "selectedFamilyKey": family_binding.get("selectedFamilyKey") if family_binding else None,
        "noRawMaterial": True,
    }
    existing_marker = _read_json(run_dir / "draft-validation.json")
    bound_run = run_store.BoundRun(run_id=canonical, run_dir=run_dir, manifest=manifest)
    evidence_rebuilt = False
    already_validated = False
    if isinstance(existing_marker, dict) and all(
        existing_marker.get(key) == marker.get(key)
        for key in marker
        if key not in {"validatedAt", "researchExecutionPlanHash"}
    ):
        # Every provenance, source authority, execution-plan and PoB check above still runs.
        # A semantic duplicate never refreshes markers or an existing bundle. Cache loss is
        # recoverable from the same validated identity, with the original marker and lifetime.
        try:
            frozen = mechanism_evidence.read_validated_draft(
                bound_run, candidate_id=draft.prototype_build_candidate.candidate_id
            )
        except run_store.RunStoreError as exc:
            return models.rejected(exc.code)
        if (
            frozen is not None
            or not marker.get("mechanismSignatureHash")
            or blueprint_marker is None
        ):
            already_validated = True
        marker = existing_marker
        evidence_rebuilt = not already_validated
    elif not _write_json_atomic(run_dir / "draft-validation.json", marker):
        return models.rejected("run_state_write_failed")
    if marker.get("mechanismSignatureHash") and not already_validated:
        try:
            mechanism_evidence.remember_validated_draft(
                bound_run,
                draft.prototype_build_candidate,
                marker,
                blueprint_marker,
            )
        except run_store.RunStoreError as exc:
            return models.rejected(exc.code)
    return {
        "status": "already_validated" if already_validated else "accepted",
        "validationOnly": True,
        "changed": not (already_validated or evidence_rebuilt),
        "validatedAt": marker["validatedAt"],
        "evidenceRebuilt": evidence_rebuilt,
        "candidateId": draft.prototype_build_candidate.candidate_id,
        "promptId": draft.agent_refined_build_prompt.prompt_id,
        "researchPremiseAuditReady": research_use is not None,
        "researchExecutionContractRef": marker["researchExecutionContractRef"],
        "researchExecutionPlanHash": marker["researchExecutionPlanHash"],
        "researchExecutionStructureHash": marker["researchExecutionStructureHash"],
        "researchDecisionHash": marker["researchDecisionHash"],
        "mechanismBlueprintRef": marker["mechanismBlueprintRef"],
        "mechanismBlueprintHash": marker["mechanismBlueprintHash"],
        "mechanismSignatureHash": marker["mechanismSignatureHash"],
        "calculationContext": marker["calculationContext"],
        "buildStateHash": marker["buildStateHash"],
        "noRawMaterial": True,
        "noHiddenChainOfThought": True,
    }


def record_generation_family_discovery(
    run_id: str,
    run_token: str,
    family_discovery_ref: str,
    selected_family_key: str = "",
) -> dict[str, Any]:
    """Bind one run-fresh Family discovery result before candidate validation/Judge."""

    try:
        bound_run = run_store.load_bound_run(run_id, run_token)
    except run_store.RunStoreError as exc:
        return models.rejected(exc.code)
    if not family_discovery_ref.startswith("dq-"):
        return models.rejected("invalid_family_discovery_ref")
    receipt = research_memory.ResearchMemoryService().read_query_receipt(family_discovery_ref)
    if receipt is None:
        return models.rejected("family_discovery_receipt_missing")
    if not progression_provenance.receipt_was_seen_at_or_after(
        receipt,
        str(bound_run.manifest.get("startedAt") or ""),
    ):
        return models.rejected("family_discovery_receipt_not_current_run")
    request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    result = receipt.get("result") if isinstance(receipt.get("result"), dict) else {}
    if request.get("detailLevel") != "family":
        return models.rejected("family_discovery_receipt_wrong_detail")
    if receipt.get("retrievalComplete") is not True:
        return models.rejected("family_discovery_receipt_incomplete")
    families = [row for row in result.get("buildFamilies") or [] if isinstance(row, dict)]
    selected = str(selected_family_key or "").strip()
    selected_row = next(
        (row for row in families if str(row.get("buildFamilyKey") or "") == selected),
        None,
    )
    outcome = str((result.get("familyDiscovery") or {}).get("outcome") or "")
    if selected:
        if selected_row is None:
            return models.rejected("selected_family_not_in_discovery")
        eligibility = dict(selected_row.get("createEligibility") or {})
        eligibility_status = str(eligibility.get("status") or "needs_revalidation")
        if eligibility_status not in {"authorized", "needs_revalidation"}:
            return models.rejected("invalid_family_create_eligibility")
        binding_status = "selected"
    else:
        if families or outcome != "no_family":
            return models.rejected("selected_family_key_required")
        eligibility = {}
        eligibility_status = "no_family"
        binding_status = "no_family"
    marker = {
        "schemaVersion": 1,
        "familyDiscoveryRef": family_discovery_ref,
        "selectedFamilyKey": selected or None,
        "status": binding_status,
        "createEligibilityStatus": eligibility_status,
        "createEligibilityBlockers": list(eligibility.get("blockers") or []),
        "classKey": request.get("classKey"),
        "ascendancyKey": request.get("ascendancyKey"),
        "relatedSkillKey": request.get("relatedSkillKey"),
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "noRawMaterial": True,
    }
    if not _write_json_atomic(bound_run.run_dir / "family-discovery.json", marker):
        return models.rejected("run_state_write_failed")
    return {**marker, "bindingStatus": marker["status"], "status": "recorded"}


def _read_family_discovery_binding(run_dir: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((run_dir / "family-discovery.json").read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 1
        or value.get("status") not in {"selected", "no_family"}
        or not isinstance(value.get("familyDiscoveryRef"), str)
        or value.get("noRawMaterial") is not True
    ):
        return None
    return value


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _family_binding_research_error(
    binding: dict[str, Any],
    research_use: models.ResearchMemoryUse | None,
) -> str | None:
    eligibility = str(binding.get("createEligibilityStatus") or "")
    selected = str(binding.get("selectedFamilyKey") or "")
    if research_use is None:
        return "generation_research_use_required"
    if eligibility == "authorized":
        if research_use.retrieval_outcome != "matched":
            return "authorized_family_cannot_be_no_matching_memory"
        if selected not in research_use.build_family_keys:
            return "selected_family_not_in_research_use"
    elif research_use.retrieval_outcome != "no_matching_memory":
        return "non_authorized_family_cannot_authorize_create"
    return None


def complete_generation_review(
    run_id: str,
    run_token: str,
    agent_output: dict[str, Any],
) -> dict[str, Any]:
    """Persist one bound safe submission and consume the run after trusted review."""

    return _submit_generation_output(
        run_id=run_id,
        run_token=run_token,
        agent_output=agent_output,
        consume=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PoE2 BD Creator Phase 5 prototype helper.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser(
        "start-run",
        help="Create an isolated run directory and one-time review binding.",
    )
    start_parser.add_argument(
        "--memory-mode",
        choices=("standard", "no_memory", "memory_assisted"),
        default="memory_assisted",
    )
    review_parser = subparsers.add_parser(
        "review-packet",
        help="Validate Agent-led prototype output and build a safe human review packet.",
    )
    review_parser.add_argument("--run-id", required=True)
    review_parser.add_argument("--run-token", required=True)
    review_parser.add_argument(
        "--compact",
        action="store_true",
        help="Print a compact result while preserving the complete review-result.json.",
    )
    validate_parser = subparsers.add_parser(
        "validate-output",
        help="Validate and canonicalize Agent output without consuming the generation run.",
    )
    validate_parser.add_argument("--run-id", required=True)
    validate_parser.add_argument("--run-token", required=True)

    args = parser.parse_args(argv)
    if args.command == "start-run":
        print(json.dumps(_start_run(args), ensure_ascii=False, indent=2))
        return 0
    if args.command == "review-packet":
        payload = _run_review_packet(args, consume=True, compact=bool(args.compact))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("status") == "accepted" else 1
    if args.command == "validate-output":
        payload = _run_review_packet(args, consume=False, compact=True)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("status") == "accepted" else 1
    parser.error(f"unsupported command: {args.command}")
    return 2


def _start_run(args: argparse.Namespace) -> dict[str, Any]:
    run_id = str(uuid4())
    run_dir = _runs_dir() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now(timezone.utc).isoformat()
    run_context = {
        "runId": run_id,
        "runToken": f"run_{secrets.token_urlsafe(24)}",
    }
    manifest = {
        "schemaVersion": 1,
        "state": "active",
        "startedAt": started_at,
        "runContext": run_context,
        "requestRef": f"request:{run_id}",
        "promptId": f"prompt:{run_id}",
        "packetId": f"human-review:{run_id}",
        "agentOutputContractVersion": run_store.CURRENT_AGENT_OUTPUT_CONTRACT_VERSION,
        "agentOutputFile": str(run_dir / "agent-output.json"),
        "experimentContext": {
            "memoryMode": args.memory_mode,
            "maxRetryCount": 2,
            "globalOptimizerAllowed": False,
            "passiveTreeOptimizationMode": "manual_targeted",
            "mutationBatchPreferred": True,
            "mechanismBlueprintRequired": args.memory_mode != "standard",
        },
    }
    manifest_path = run_dir / "run-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    output_template = _generation_draft_template(manifest)
    output_path = Path(manifest["agentOutputFile"])
    output_path.write_text(
        json.dumps(output_template, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "status": "started",
        "runContext": run_context,
        "requestRef": manifest["requestRef"],
        "promptId": manifest["promptId"],
        "packetId": manifest["packetId"],
        "agentOutputFile": manifest["agentOutputFile"],
        "agentOutputTemplateInitialized": True,
        "agentOutputContractVersion": manifest["agentOutputContractVersion"],
        "agentOutputDraftTemplate": output_template,
        "agentInputContracts": _generation_input_contracts(),
        "reviewResultFile": str(run_dir / "review-result.json"),
        "experimentContext": manifest["experimentContext"],
    }


def _generation_input_contracts() -> dict[str, Any]:
    """Publish the actual nested model constraints once, sharing repeated definitions.

    Schemas describe content; the run envelope comes from the template and runtime provenance
    checks still apply. Keeping this outside the template avoids adding non-input metadata to a
    candidate and avoids inventing Research/Blueprint content just to populate null placeholders.
    """
    definitions: dict[str, Any] = {}
    schemas: dict[str, Any] = {}
    for name, model in (
        ("blueprintDraft", models.GenerationMechanismBlueprintDraft),
        ("agentOutputDraftContent", models.GenerationDraft),
    ):
        schema = model.model_json_schema(by_alias=True)
        definitions.update(schema.pop("$defs", {}))
        schemas[name] = schema
    return {
        "$defs": definitions,
        **schemas,
        "scope": "input_structure_not_evidence_authorization",
        "draftEnvelope": {
            "source": "agentOutputDraftTemplate",
            "boundFields": ["runContext", "packetId"],
            "contentFields": ["agentRefinedBuildPrompt", "prototypeBuildCandidate"],
        },
        "runtimeValidationRequired": [
            "copy_safety_and_no_hidden_reasoning",
            "run_fresh_research_receipts_and_authority",
            "research_subject_coverage_and_source_associations",
            "cross_field_consistency_and_unique_references",
            "blueprint_and_observed_build_signature_binding",
        ],
    }


def _generation_draft_template(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a complete alias-generated camelCase skeleton without inventing content."""

    version_context = models.VersionContext.model_construct(
        league="",
        ruleset="",
        game_patch="",
        passive_tree_version="",
        pob_version_or_commit="",
        graph_snapshot_id="",
        research_memory_ref="",
    )
    prompt = models.AgentRefinedBuildPrompt.model_construct(
        prompt_id=manifest["promptId"],
        request_ref=manifest["requestRef"],
        user_request_summary="",
        refined_prompt_summary="",
        current_output_stages=[],
        target_lifecycle_stages=[],
        cross_stage_locked_dimensions=["class"],
        field_sources={
            "user_request_summary": "unknown",
            "refined_prompt_summary": "unknown",
            "current_output_stages": "unknown",
            "target_lifecycle_stages": "unknown",
            "cross_stage_locked_dimensions": "unknown",
        },
        default_assumptions=[],
        clarification_questions=[],
        unresolved_items=[],
        version_context=version_context,
        no_raw_material=True,
    )
    candidate = models.PrototypeBuildCandidate.model_construct(
        candidate_id="",
        prompt_ref=manifest["promptId"],
        current_output_stages=[],
        target_lifecycle_stages=[],
        cross_stage_locked_dimensions=["class"],
        class_shell="",
        primary_skill_intent="",
        secondary_skill_intents=[],
        mechanic_axes=[],
        defense_layers=[],
        spirit_assumptions=[],
        gear_roles=[],
        passive_anchor_intents=[],
        transition_gates=[],
        unresolved_caveats=[],
        completeness_advisory_decisions=[],
        tool_references=[],
        memory_references=[],
        research_memory_use=None,
        research_execution_plan=None,
        mechanism_blueprint_ref=None,
        mechanism_blueprint=None,
        rationale_summary="",
        version_context=version_context.model_copy(deep=True),
        no_raw_material=True,
    )
    draft = models.GenerationDraft.model_construct(
        agent_refined_build_prompt=prompt,
        prototype_build_candidate=candidate,
    ).model_dump(mode="json", by_alias=True)
    return {
        "schemaVersion": 2,
        "runContext": manifest["runContext"],
        "packetId": manifest["packetId"],
        **draft,
        "generationAttempts": [],
    }


def _run_review_packet(
    args: argparse.Namespace,
    *,
    consume: bool,
    compact: bool,
) -> dict[str, Any]:
    run_id = _canonical_run_id(args.run_id)
    if run_id is None:
        return models.rejected("invalid_run_manifest")
    run_dir = _runs_dir() / run_id
    manifest_path = run_dir / "run-manifest.json"
    output_path = run_dir / "agent-output.json"
    review_lock = run_dir / "review-lock"
    consumed_marker = run_dir / "review-consumed"
    if consumed_marker.exists():
        return models.rejected("run_already_consumed")
    manifest = _read_run_manifest(manifest_path, run_id, output_path)
    if manifest is None:
        return models.rejected("invalid_run_manifest")
    if manifest["runContext"]["runToken"] != args.run_token:
        return models.rejected("run_binding_mismatch")
    if run_store.run_expired(manifest["startedAt"]):
        return models.rejected("run_expired")
    if run_store.generation_contract_upgrade_required(manifest):
        return models.rejected("generation_contract_upgrade_requires_restart")

    try:
        raw = output_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return models.rejected("invalid_input", caveats=["agent_output_file_invalid_encoding"])
    except OSError:
        return models.rejected("invalid_input", caveats=["agent_output_file_unreadable"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return models.rejected("invalid_input", caveats=["agent_output_file_invalid_json"])
    if not isinstance(data, dict):
        return models.rejected("invalid_input", caveats=["agent_output_file_must_be_object"])
    raw_safety = models.validate_no_raw_or_hidden_reasoning(data)
    if raw_safety.get("status") != "accepted":
        return raw_safety
    binding_error = _run_binding_error(data, manifest)
    if binding_error is not None:
        return binding_error
    bound_run = run_store.BoundRun(run_id=run_id, run_dir=run_dir, manifest=manifest)
    try:
        trusted_receipts = run_store.read_trusted_evaluations_strict(bound_run)
    except run_store.RunStoreError as exc:
        return models.rejected(exc.code)
    artifact_selection = run_store.read_artifact_selection(bound_run)
    if bound_run.artifact_selection_path.exists() and artifact_selection is None:
        return models.rejected("artifact_selection_receipt_corrupt")
    canonical = canonicalize.canonicalize_agent_output(
        data,
        trusted_receipts,
        artifact_selection=artifact_selection,
    )
    if canonical.get("status") != "accepted":
        return canonical

    canonical_payload = canonical["payload"]
    try:
        evidence_context = mechanism_evidence.review_context(
            bound_run,
            trusted_receipts,
            artifact_selection,
            canonical_payload.get("prototypeBuildCandidate") or {},
        )
    except run_store.RunStoreError as exc:
        return models.rejected(exc.code)
    premise_error, premise_caveats = _validate_candidate_research_use(
        canonical_payload,
        receipt_reader=research_memory.ResearchMemoryService().read_query_receipt,
        not_before=manifest["startedAt"],
        run_dir=run_dir,
        evidence_context=evidence_context,
    )
    if premise_error:
        detail_hints = {
            "progression_research_receipt_not_current_run": (
                "researchMemoryUse receipts must be queried after this run started; re-query "
                "Research inside the current run and pass the new dedupeQueryRefs"
            ),
            "progression_research_receipt_missing": (
                "a dedupeQueryRef does not resolve to a recorded research receipt"
            ),
            "progression_research_resolution_not_deep_read": (
                "resolved premise resolutionRefs must be deep-read in this run's receipts "
                "(detail_level='record')"
            ),
            "progression_research_premise_decision_incomplete": (
                "every failure_condition premise in the selected Family's catalog needs a "
                "premiseDecisions entry"
            ),
        }
        caveats = list(premise_caveats or [])
        if premise_error in detail_hints:
            caveats.append(detail_hints[premise_error])
        return models.rejected(premise_error, caveats=caveats)
    blueprint_error, _blueprint_marker = _validate_candidate_blueprint_use(
        canonical_payload.get("prototypeBuildCandidate") or {},
        run_dir=run_dir,
        manifest=manifest,
        require_draft_binding=True,
        evidence_context=evidence_context,
    )
    if blueprint_error:
        return models.rejected(blueprint_error)
    result = prototype.validate_and_build_human_review_packet(
        canonical_payload,
        trusted_evaluation=True,
    )
    if result.get("status") == "accepted":
        retry_result = retry.validate_and_build_retry_report(
            result["humanReviewPacket"],
            manifest,
            trusted_receipts,
            run_id=run_id,
        )
        if retry_result.get("status") != "accepted":
            return retry_result
        result["experimentContext"] = retry_result["experimentContext"]
        result["retryComparisonReport"] = retry_result["retryComparisonReport"]
        mechanism_error = _selected_attempt_mechanism_binding_error(
            bound_run,
            trusted_receipts,
            retry_result.get("retryComparisonReport"),
            evidence_context=evidence_context,
        )
        if mechanism_error is not None:
            return models.rejected(mechanism_error)
        if not consume:
            return _compact_review_result(result, run_dir=run_dir, consumed=False)
        try:
            review_lock.open("x", encoding="utf-8").close()
        except FileExistsError:
            return models.rejected("run_already_consumed")
        except OSError:
            return models.rejected("run_state_write_failed")
        if consumed_marker.exists():
            review_lock.unlink(missing_ok=True)
            return models.rejected("run_already_consumed")
        result_path = run_dir / "review-result.json"
        if not _write_json_atomic(result_path, result):
            review_lock.unlink(missing_ok=True)
            return models.rejected("run_state_write_failed")
        try:
            review_lock.replace(consumed_marker)
        except OSError:
            result_path.unlink(missing_ok=True)
            review_lock.unlink(missing_ok=True)
            return models.rejected("run_state_write_failed")
    if compact and result.get("status") == "accepted":
        return _compact_review_result(result, run_dir=run_dir, consumed=True)
    return result


def _selected_attempt_mechanism_binding_error(
    bound_run: run_store.BoundRun,
    trusted_receipts: list[dict[str, Any]],
    retry_report: dict[str, Any] | None,
    *,
    evidence_context: dict[str, Any] | None = None,
) -> str | None:
    required = bool(
        ((bound_run.manifest or {}).get("experimentContext") or {}).get(
            "mechanismBlueprintRequired"
        )
    )
    if not required:
        return None
    current = (
        evidence_context.get("mechanismBinding")
        if evidence_context is not None
        else run_store.current_mechanism_binding(bound_run)
    )
    if current is None:
        return "generation_draft_validation_required"
    selected = (retry_report or {}).get("selectedAttemptIndex")
    selected_index = (
        selected
        if isinstance(selected, int) and not isinstance(selected, bool)
        else len(trusted_receipts) - 1
    )
    if selected_index < 0 or selected_index >= len(trusted_receipts):
        return "trusted_evaluation_mismatch"
    if (
        evidence_context is not None
        and evidence_context.get("selectedAttemptIndex") != selected_index
    ):
        return "trusted_evaluation_mismatch"
    if trusted_receipts[selected_index].get("mechanismBinding") != current:
        return "generation_attempt_mechanism_binding_mismatch"
    return None


def _submit_generation_output(
    *,
    run_id: str,
    run_token: str,
    agent_output: dict[str, Any],
    consume: bool,
) -> dict[str, Any]:
    canonical = _canonical_run_id(run_id)
    if canonical is None:
        return models.rejected("invalid_run_manifest")
    run_dir = _runs_dir() / canonical
    output_path = run_dir / "agent-output.json"
    if (run_dir / "review-consumed").exists():
        return models.rejected("run_already_consumed")
    manifest = _read_run_manifest(run_dir / "run-manifest.json", canonical, output_path)
    if manifest is None:
        return models.rejected("invalid_run_manifest")
    if manifest["runContext"]["runToken"] != run_token:
        return models.rejected("run_binding_mismatch")
    if run_store.run_expired(manifest["startedAt"]):
        return models.rejected("run_expired")
    if run_store.generation_contract_upgrade_required(manifest):
        return models.rejected("generation_contract_upgrade_requires_restart")
    if not isinstance(agent_output, dict):
        return models.rejected("invalid_input")
    raw_safety = models.validate_no_raw_or_hidden_reasoning(agent_output)
    if raw_safety.get("status") != "accepted":
        return raw_safety
    binding_error = _run_binding_error(agent_output, manifest)
    if binding_error is not None:
        return binding_error
    if not _write_json_atomic(output_path, agent_output):
        return models.rejected("run_state_write_failed")
    args = argparse.Namespace(run_id=canonical, run_token=run_token)
    return _run_review_packet(args, consume=consume, compact=True)


def _validate_candidate_research_use(
    canonical_payload: dict[str, Any],
    *,
    receipt_reader: Any,
    not_before: str | None = None,
    run_dir: Path | None = None,
    evidence_context: dict[str, Any] | None = None,
) -> tuple[str | None, list[str]]:
    """Apply the shared receipt/premise audit to ordinary single-stage Create.

    The canonical payload keeps the submission's field casing (snake_case from the Agent), so
    both alias shapes must be read here — otherwise a snake_case researchMemoryUse silently
    skips the receipt/premise audit.
    """

    candidate = canonical_payload.get("prototypeBuildCandidate") or {}
    tool_refs = list(candidate.get("toolReferences") or candidate.get("tool_references") or [])
    try:
        evidence_authority.normalized_refs(tool_refs)
    except ValueError:
        return "invalid_tool_evidence_reference", []
    research_use = candidate.get("researchMemoryUse")
    if not isinstance(research_use, dict):
        research_use = candidate.get("research_memory_use")
    if not isinstance(research_use, dict):
        return evidence_authority.validate_internal_claims(tool_refs, set()), []
    premise_error, _premise_summary, premise_caveats = (
        progression_provenance.validate_research_use_receipts(
            research_memory_use=research_use,
            receipt_reader=receipt_reader,
            not_before=not_before,
        )
    )
    if premise_error:
        return premise_error, premise_caveats
    retrieval_outcome = str(
        research_use.get("retrievalOutcome") or research_use.get("retrieval_outcome") or ""
    )
    if retrieval_outcome != "matched":
        return evidence_authority.validate_internal_claims(
            tool_refs, _research_evidence_refs(research_use, {})
        ), []
    version = candidate.get("versionContext") or candidate.get("version_context") or {}
    contract = research_execution.construct_from_research_use(
        research_use,
        game_patch=str(version.get("gamePatch") or version.get("game_patch") or ""),
        passive_tree_version=str(
            version.get("passiveTreeVersion") or version.get("passive_tree_version") or ""
        ),
    )
    if contract.get("status") != "ready":
        return (
            str(contract.get("errorCode") or "research_execution_contract_unavailable"),
            list(contract.get("caveats") or []),
        )
    evidence_error = evidence_authority.validate_internal_claims(
        tool_refs, _research_evidence_refs(research_use, contract)
    )
    if evidence_error:
        return evidence_error, []
    execution_plan = candidate.get("researchExecutionPlan")
    if not isinstance(execution_plan, dict):
        execution_plan = candidate.get("research_execution_plan")
    if not isinstance(execution_plan, dict):
        return "research_execution_plan_required", []
    error, caveats, summary = research_execution.validate_research_execution_plan(
        execution_plan,
        contract,
        allowed_evidence_refs=_execution_evidence_refs(
            tool_references=list(
                candidate.get("toolReferences") or candidate.get("tool_references") or []
            ),
            research_use=research_use,
            contract=contract,
        ),
        external_evidence_refs=_execution_external_evidence_refs(
            list(candidate.get("toolReferences") or candidate.get("tool_references") or [])
        ),
    )
    if error:
        return error, caveats
    subject_error, subject_caveats = research_execution.validate_insight_decision_subjects(
        research_use,
        contract,
    )
    if subject_error:
        return subject_error, subject_caveats
    if run_dir is not None:
        if evidence_context is not None:
            marker = evidence_context.get("draftMarker")
        else:
            marker = _read_json(run_dir / "draft-validation.json")
        if not isinstance(marker, dict):
            return "generation_draft_validation_required", []
        structure_hash_matches = (
            marker.get("researchExecutionStructureHash") == (summary or {}).get("structureHash")
            if "researchExecutionStructureHash" in marker
            else marker.get("researchExecutionPlanHash") == (summary or {}).get("planHash")
        )
        if (
            marker.get("researchExecutionContractRef") != contract.get("contractRef")
            or not structure_hash_matches
        ):
            return "research_execution_plan_changed_after_draft", []
    return None, []


def _validate_candidate_blueprint_use(
    candidate: models.PrototypeBuildCandidate | dict[str, Any],
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    require_draft_binding: bool,
    evidence_context: dict[str, Any] | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Bind the candidate's free-form blueprint to its pre-build validation receipt."""

    required = bool((manifest.get("experimentContext") or {}).get("mechanismBlueprintRequired"))
    if isinstance(candidate, models.PrototypeBuildCandidate):
        candidate_id = candidate.candidate_id
        blueprint_ref = candidate.mechanism_blueprint_ref
        blueprint = candidate.mechanism_blueprint
        research_memory_ref = candidate.version_context.research_memory_ref
    else:
        candidate_id = str(candidate.get("candidateId") or candidate.get("candidate_id") or "")
        blueprint_ref = candidate.get("mechanismBlueprintRef")
        if blueprint_ref is None:
            blueprint_ref = candidate.get("mechanism_blueprint_ref")
        blueprint = candidate.get("mechanismBlueprint")
        if blueprint is None:
            blueprint = candidate.get("mechanism_blueprint")
        version = candidate.get("versionContext") or candidate.get("version_context") or {}
        research_memory_ref = str(
            version.get("researchMemoryRef") or version.get("research_memory_ref") or ""
        )
    if blueprint_ref is None and blueprint is None:
        return (
            ("generation_mechanism_blueprint_required" if required else None),
            None,
        )
    if not isinstance(blueprint_ref, str) or blueprint is None:
        return "generation_mechanism_blueprint_incomplete", None
    try:
        blueprint_model = (
            blueprint
            if isinstance(blueprint, models.MechanismBlueprint)
            else models.MechanismBlueprint.model_validate(blueprint)
        )
    except models.ValidationError:
        return "generation_mechanism_blueprint_invalid", None
    marker = (
        evidence_context.get("blueprintMarker")
        if evidence_context is not None
        else _read_json(run_dir / "mechanism-blueprint-validation.json")
    )
    if not isinstance(marker, dict) or marker.get("schemaVersion") != 1:
        return "generation_blueprint_validation_required", None
    candidate_tools = (
        candidate.tool_references if isinstance(candidate, models.PrototypeBuildCandidate)
        else candidate.get("toolReferences") or candidate.get("tool_references") or []
    )
    if not evidence_authority.audit_matches(marker, blueprint_model, candidate_tools):
        return "generation_blueprint_evidence_binding_mismatch", None
    blueprint_hash = models.mechanism_blueprint_hash(blueprint_model)
    if (
        marker.get("blueprintRef") != blueprint_ref
        or marker.get("blueprintHash") != blueprint_hash
        or marker.get("candidateId") != candidate_id
        or marker.get("researchMemoryRef") != research_memory_ref
    ):
        return "generation_mechanism_blueprint_binding_mismatch", None
    if require_draft_binding:
        draft_marker = (
            evidence_context.get("draftMarker")
            if evidence_context is not None
            else _read_json(run_dir / "draft-validation.json")
        )
        if not isinstance(draft_marker, dict):
            return "generation_draft_validation_required", None
        try:
            parsed_candidate = (candidate if isinstance(candidate, models.PrototypeBuildCandidate)
                                else models.PrototypeBuildCandidate.model_validate(candidate))
            if not evidence_authority.design_tools_match(
                parsed_candidate, draft_marker,
                original_evidence_uses=(evidence_context or {}).get("designEvidenceUses"),
            ):
                return "generation_tool_evidence_changed_after_draft", None
        except ValueError:
            return "invalid_tool_evidence_reference", None
        if (
            draft_marker.get("mechanismBlueprintRef") != blueprint_ref
            or draft_marker.get("mechanismBlueprintHash") != blueprint_hash
            or draft_marker.get("evidenceAuditHash") != marker.get("evidenceAuditHash")
        ):
            return "generation_mechanism_blueprint_changed_after_draft", None
        if draft_marker.get("schemaVersion") == 3:
            try:
                research_hash = mechanism_evidence.research_decision_hash(
                    candidate.research_memory_use
                    if isinstance(candidate, models.PrototypeBuildCandidate)
                    else candidate.get("researchMemoryUse") or candidate.get("research_memory_use"),
                    candidate.research_execution_plan
                    if isinstance(candidate, models.PrototypeBuildCandidate)
                    else candidate.get("researchExecutionPlan")
                    or candidate.get("research_execution_plan"),
                )
            except models.ValidationError:
                return "generation_research_decisions_invalid", None
            if draft_marker.get("researchDecisionHash") != research_hash:
                return "generation_research_decisions_changed_after_draft", None
    return None, marker


def _execution_evidence_refs(
    *,
    tool_references: list[dict[str, Any]],
    research_use: dict[str, Any],
    contract: dict[str, Any],
) -> set[str]:
    return _research_evidence_refs(research_use, contract) | _execution_external_evidence_refs(tool_references)


def _research_evidence_refs(research_use: dict[str, Any], contract: dict[str, Any]) -> set[str]:
    # Call only after run-fresh receipt validation and construction of the typed contract.
    refs: set[str] = set()
    refs.update(
        str(value)
        for key in (
            "dedupeQueryRefs",
            "dedupe_query_refs",
            "comparisonDedupeQueryRefs",
            "comparison_dedupe_query_refs",
        )
        for value in research_use.get(key) or []
    )
    refs.add(str(contract.get("contractRef") or ""))
    for package in contract.get("packages") or []:
        if not isinstance(package, dict):
            continue
        refs.add(str(package.get("packageId") or ""))
        refs.add(str(package.get("recordId") or ""))
    return {value for value in refs if value}


def _adopted_primary_skill_package_error(
    *,
    execution_contract: dict[str, Any] | None,
    execution_plan: models.ResearchExecutionPlan | None,
    observed_signature: dict[str, Any],
) -> str | None:
    """Reject full adoption claims when the observed primary socket package is only partial."""

    if not execution_contract or execution_plan is None:
        return None
    active_name = str(observed_signature.get("activeSkillName") or "")
    active_gem = knowledge_db.get_gem(active_name)
    if not isinstance(active_gem, dict):
        return "research_execution_adopted_skill_unresolved"
    active_keys = {"skill:" + str(value) for value in active_gem.get("grants") or [] if value}
    decisions = {item.package_id: item for item in execution_plan.package_decisions}
    for package in execution_contract.get("packages") or []:
        if not isinstance(package, dict) or package.get("recordKind") != "skill_package":
            continue
        decision = decisions.get(str(package.get("packageId") or ""))
        if decision is None or decision.decision != "adopted":
            continue
        primary_keys = {
            str(item.get("componentKey") or "")
            for item in package.get("componentResponsibilities") or []
            if isinstance(item, dict)
            and item.get("role") in {"primary_damage", "clear_skill", "boss_skill"}
        }
        if not active_keys.intersection(primary_keys):
            continue
        support_packages = (package.get("typedResponsibilities") or {}).get("supportPackages") or []
        matching = [
            item
            for item in support_packages
            if isinstance(item, dict) and str(item.get("skillKey") or "") in active_keys
        ]
        if not matching:
            continue
        actual_support_keys: set[str] = set()
        for name in observed_signature.get("supportNames") or []:
            gem = knowledge_db.get_gem(str(name))
            gem_id = str((gem or {}).get("id") or "") if isinstance(gem, dict) else ""
            if not gem_id:
                return "research_execution_adopted_support_unresolved"
            try:
                actual_support_keys.add(component_keys.canonical_support_component_key(gem_id))
            except ValueError:
                return "research_execution_adopted_support_unresolved"
        expected_sets = [
            {str(value) for value in item.get("supportKeys") or [] if value} for item in matching
        ]
        if actual_support_keys not in expected_sets:
            return "research_execution_adoption_mismatch"
    return None


def _execution_external_evidence_refs(
    tool_references: list[dict[str, Any]],
) -> set[str]:
    return evidence_authority.external_refs(tool_references)


def _compact_review_result(
    result: dict[str, Any],
    *,
    run_dir: Path,
    consumed: bool,
) -> dict[str, Any]:
    packet = result.get("humanReviewPacket") or {}
    judge = packet.get("judgeAdvisoryReport") or {}
    candidate = packet.get("prototypeBuildCandidate") or {}
    retry_report = result.get("retryComparisonReport") or {}
    attempts = retry_report.get("attempts") or packet.get("generationAttempts") or []
    compact = {
        "status": "accepted",
        "validationOnly": not consumed,
        "reviewResultFile": str(run_dir / "review-result.json") if consumed else None,
        "packetId": packet.get("packetId"),
        "candidateId": candidate.get("candidateId"),
        "attemptCount": len(attempts),
        "finalJudge": {
            "status": judge.get("status"),
            "passed": judge.get("passed"),
            "aggregateScore": judge.get("aggregateScore"),
            "qualityBand": judge.get("qualityBand"),
            "rewardStrength": judge.get("rewardStrength"),
            "finalClassification": judge.get("finalClassification"),
            "hardFailures": judge.get("hardFailures") or [],
            "playabilityFailures": judge.get("playabilityFailures") or [],
            "qualityWarnings": judge.get("qualityWarnings") or [],
            "offenseEvidence": judge.get("offenseEvidence"),
        },
        "lifecycleEvidenceCoverage": packet.get("lifecycleEvidenceCoverage"),
        "retrySummary": {
            "programmaticOutcome": retry_report.get("programmaticOutcome"),
            "scoreDelta": retry_report.get("scoreDelta"),
        },
        "requiredUserDisclosures": candidate.get("completenessAdvisoryDecisions") or [],
        "performanceEstimates": candidate.get("performanceEstimates") or [],
        "performanceEstimateNotice": (
            "这些是Agent给出的条件情景粗估，未经PoB完整验证；不得替换PoB/Judge数值，"
            "也不得在未核对重叠与重复计数时直接相加。建模覆盖不代表技能价值。"
            if candidate.get("performanceEstimates") else None
        ),
        "noRawMaterial": True,
        "noHiddenChainOfThought": True,
    }
    return compact


def _runs_dir() -> Path:
    override = os.environ.get("POE_BD_CREATE_RUNS_DIR")
    return (
        Path(override).resolve()
        if override
        else (paths.user_data_dir() / "generation-runs").resolve()
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> bool:
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except (OSError, TypeError, ValueError):
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def _read_run_manifest(
    path: Path,
    run_id: str,
    output_path: Path,
) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (UnicodeDecodeError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    context = data.get("runContext")
    if not isinstance(context, dict):
        return None
    required_strings = {
        "startedAt": data.get("startedAt"),
        "requestRef": data.get("requestRef"),
        "promptId": data.get("promptId"),
        "packetId": data.get("packetId"),
        "agentOutputFile": data.get("agentOutputFile"),
        "runId": context.get("runId"),
        "runToken": context.get("runToken"),
    }
    if not all(isinstance(value, str) and value for value in required_strings.values()):
        return None
    if data.get("schemaVersion") != 1 or data.get("state") != "active":
        return None
    if context["runId"] != run_id:
        return None
    try:
        manifest_output_path = Path(data["agentOutputFile"]).resolve()
    except (OSError, ValueError):
        return None
    if manifest_output_path != output_path:
        return None
    return data


def _canonical_run_id(value: str) -> str | None:
    try:
        canonical = str(UUID(value))
    except ValueError:
        return None
    return canonical if canonical == value else None


def _run_binding_error(
    data: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any] | None:
    prompt = _matching_alias(data, "agentRefinedBuildPrompt", "agent_refined_build_prompt")
    if not isinstance(prompt, dict):
        return models.rejected("run_binding_mismatch")
    actual = {
        "runContext": _matching_alias(data, "runContext", "run_context"),
        "packetId": _matching_alias(data, "packetId", "packet_id"),
        "requestRef": _matching_alias(prompt, "requestRef", "request_ref"),
        "promptId": _matching_alias(prompt, "promptId", "prompt_id"),
    }
    expected = {
        "runContext": manifest.get("runContext"),
        "packetId": manifest.get("packetId"),
        "requestRef": manifest.get("requestRef"),
        "promptId": manifest.get("promptId"),
    }
    if actual != expected:
        return models.rejected("run_binding_mismatch")
    artifact_aliases = (
        ("prototypeBuildCandidate", "prototype_build_candidate"),
        ("transientBuildState", "transient_build_state"),
        ("judgeAdvisoryReport", "judge_advisory_report"),
        ("toolFeedbackEvents", "tool_feedback_events"),
        ("failureAudit", "failure_audit"),
        ("generationAttempts", "generation_attempts"),
    )
    for camel, snake in artifact_aliases:
        if camel in data and snake in data and data[camel] != data[snake]:
            return models.rejected("invalid_schema")
    return None


def _matching_alias(payload: dict[str, Any], camel: str, snake: str) -> Any:
    camel_present = camel in payload
    snake_present = snake in payload
    if camel_present and snake_present and payload[camel] != payload[snake]:
        return None
    if camel_present:
        return payload[camel]
    return payload.get(snake)


if __name__ == "__main__":
    raise SystemExit(main())
