"""Local-only storage for the final Agent-accepted PoB candidate."""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4
import xml.etree.ElementTree as ET

from pydantic import Field, ValidationError

from server import paths
from server.compute import completeness, pob_structure
from server.compute.state import build_state_hash
from server.knowledge import copy_safety
from server.knowledge.lifecycle_verification import LifecycleStageVerificationState
from server.judge import evaluator, hard_legality
from server.runtime.file_lock import interprocess_file_lock

from . import (
    evaluation_snapshots,
    lifecycle_observation,
    mechanism_evidence,
    models,
    run_store,
    validation_checkpoint,
)


ARTIFACT_SCHEMA_VERSION = 2
SPIRIT_REVALIDATION_SCHEMA_VERSION = 1
_RECOVERY_ATTRIBUTE = "_poe2_mutation_batch_recovery_required"


class FinalBuildArtifactManifest(models.StrictModel):
    schema_version: int = ARTIFACT_SCHEMA_VERSION
    artifact_id: str
    run_id: str
    candidate_id: str
    attempt_index: int
    snapshot_id: str
    source_hash: str
    trusted_evaluation_ref: str
    safe_summary: dict[str, str]
    tested_skill_groups: list[models.TestedSkillGroup]
    judge_report: models.JudgeAdvisoryReport
    version_context: models.VersionContext
    hard_legality_audit_version: str | None = None
    delivery_status: str = "candidate"
    create_quality_checklist: dict[str, dict[str, Any]] = Field(default_factory=dict)
    pob_round_trip: dict[str, Any] = Field(default_factory=dict)
    lifecycle_verification: dict[str, Any] = Field(default_factory=dict)
    lifecycle_declaration_binding: dict[str, Any] | None = None
    artifact_selection_ref: str | None = None
    mechanism_evidence_hash: str | None = None
    selection_outcome: str = "latest_passing_attempt_selected"
    created_at: str
    local_only: bool = True
    no_chat_output: bool = True
    no_research_memory: bool = True


def artifacts_dir() -> Path:
    override = os.environ.get("POE_BD_FINAL_ARTIFACTS_DIR")
    return (
        Path(override).resolve()
        if override
        else (paths.user_data_dir() / "final-build-artifacts").resolve()
    )


def save_final_build_artifact(
    active_engine: Any,
    *,
    run_id: str,
    run_token: str,
    candidate_id: str,
    attempt_index: int,
    selection_reason: str | None = None,
    later_findings_scope: str = "not_applicable",
) -> dict[str, Any]:
    """Freeze the Judge chain while checking and publishing the selected exact artifact."""

    try:
        bound_run = run_store.load_bound_run(run_id, run_token, require_unconsumed=False)
    except run_store.RunStoreError as exc:
        return models.rejected(exc.code)
    lock_path = bound_run.run_dir / "evaluation-lock"
    if not run_store.acquire_generation_lock(lock_path):
        return models.rejected("generation_evaluation_in_progress")
    try:
        lock_factory = getattr(active_engine, "transaction_lock", None)
        with lock_factory() if callable(lock_factory) else nullcontext():
            if getattr(active_engine, _RECOVERY_ATTRIBUTE, False):
                return {
                    **models.rejected("build_state_recovery_required"),
                    "recoveryRequired": True,
                }
            return _save_final_build_artifact_locked(
                active_engine,
                run_id=run_id,
                run_token=run_token,
                candidate_id=candidate_id,
                attempt_index=attempt_index,
                selection_reason=selection_reason,
                later_findings_scope=later_findings_scope,
            )
    finally:
        run_store.release_generation_lock(lock_path)


def _save_final_build_artifact_locked(
    active_engine: Any,
    *,
    run_id: str,
    run_token: str,
    candidate_id: str,
    attempt_index: int,
    selection_reason: str | None = None,
    later_findings_scope: str = "not_applicable",
) -> dict[str, Any]:
    """Persist exactly one hard-valid, unchanged PoB snapshot for a generation run."""
    try:
        # Review consumption is an audit/workflow boundary, not build evidence.  A long
        # progression may accidentally consume its review packet before saving the immutable
        # artifact.  Keep every trusted-evaluation, exact-snapshot and semantic-state check below,
        # but allow that ordering mistake to recover instead of turning a verified build into a
        # zero-file delivery.
        bound_run = run_store.load_bound_run(
            run_id,
            run_token,
            require_unconsumed=False,
        )
    except run_store.RunStoreError as exc:
        return models.rejected(exc.code)
    review_already_consumed = (bound_run.run_dir / "review-consumed").exists()
    if run_store.generation_contract_upgrade_required(bound_run.manifest):
        return models.rejected("generation_contract_upgrade_requires_restart")
    try:
        receipts = run_store.read_trusted_evaluations_strict(bound_run)
    except run_store.RunStoreError as exc:
        return models.rejected(exc.code)
    if isinstance(attempt_index, bool) or attempt_index < 0 or attempt_index >= len(receipts):
        return models.rejected("trusted_evaluation_not_found")
    root = artifacts_dir()
    final_dir = root / bound_run.run_id
    if final_dir.exists():
        return models.rejected("final_artifact_already_exists")
    historical_attempt = attempt_index != len(receipts) - 1
    selection_reason_valid = bool(
        selection_reason
        and selection_reason.strip()
        and len(selection_reason) <= 500
        and not copy_safety.copyability_flags(selection_reason)
        and not copy_safety.contains_raw_url(selection_reason)
    )
    if historical_attempt:
        if not selection_reason_valid:
            return models.rejected("baseline_selection_reason_required")
        if later_findings_scope != "candidate_delta_only":
            return models.rejected("passing_baseline_implicated_by_later_findings")
    elif later_findings_scope not in {"not_applicable", "candidate_delta_only"}:
        return models.rejected("invalid_later_findings_scope")
    receipt = receipts[attempt_index]
    if receipt.get("candidateId") != candidate_id:
        return models.rejected("trusted_evaluation_mismatch")
    mechanism_required = bool(
        ((bound_run.manifest or {}).get("experimentContext") or {}).get(
            "mechanismBlueprintRequired"
        )
    )
    mechanism_revision_changed = False
    historical_evidence = receipt.get("mechanismEvidence")
    if mechanism_required:
        current_binding = run_store.current_mechanism_binding(bound_run)
        mechanism_revision_changed = (
            current_binding is None
            or receipt.get("mechanismBinding") != current_binding
            or (
                historical_evidence is not None
                and not mechanism_evidence.current_markers_match(bound_run, receipt)
            )
        )
        if mechanism_revision_changed:
            if historical_evidence is None:
                return models.rejected("trusted_evaluation_mechanism_binding_mismatch")
            if not selection_reason_valid:
                return models.rejected("baseline_selection_reason_required")
            if later_findings_scope != "candidate_delta_only":
                return models.rejected("passing_baseline_implicated_by_later_findings")
    if receipt.get("schemaVersion") not in {2, 3}:
        return models.rejected("legacy_evaluation_requires_rejudge")
    audit_version = str((receipt.get("hardLegalityAudit") or {}).get("auditVersion") or "")
    # Older receipts did not audit active-Spec jewels. Keep historical artifact metadata intact,
    # but only a current Judge may authorize a new artifact, including baseline recovery.
    if audit_version != hard_legality.AUDIT_VERSION:
        return models.rejected("legacy_evaluation_requires_rejudge")
    try:
        state = models.TransientBuildStateRef.model_validate(receipt.get("transientBuildState"))
        judge = models.JudgeAdvisoryReport.model_validate(receipt.get("judgeAdvisoryReport"))
    except ValidationError:
        return models.rejected("trusted_evaluation_mismatch")
    if (
        judge.status != "evaluated"
        or judge.passed is not True
        or judge.hard_failures
        or state.status != "available"
    ):
        return models.rejected("final_candidate_not_passed")
    if (
        judge.evaluated_snapshot_id != state.snapshot_id
        or judge.evaluated_source_hash != state.source_hash
    ):
        return models.rejected("trusted_evaluation_mismatch")

    target_level = int(state.safe_summary.get("level") or 0)
    # A hard-legal but incomplete build may still be exported as a technical candidate. The
    # trusted receipt and manifest retain ``deliveryStatus=candidate`` so no downstream surface can
    # honestly relabel it as a recommended finished build.

    snapshot = evaluation_snapshots.read(
        run_id=bound_run.run_id,
        attempt_index=attempt_index,
        candidate_id=candidate_id,
        source_hash=str(state.source_hash),
    )
    expected_semantic_hash = state.semantic_state_hash
    if receipt.get("schemaVersion") in {2, 3}:
        legality = receipt.get("hardLegalityAudit") or {}
        if (
            legality.get("status") != "passed"
            or legality.get("hardLegalityReady") is not True
            or legality.get("hardFailures")
            or legality.get("stateHash") != expected_semantic_hash
        ):
            return models.rejected("final_candidate_hard_legality_not_verified")
        if snapshot is None:
            return models.rejected("trusted_evaluation_snapshot_unavailable")
        if expected_semantic_hash != snapshot.semantic_state_hash:
            return models.rejected("trusted_evaluation_snapshot_mismatch")
        if snapshot.mechanism_evidence_hash != (
            historical_evidence.get("bundleHash") if isinstance(historical_evidence, dict) else None
        ):
            return models.rejected("trusted_mechanism_evidence_mismatch")
        active_state_regressed = False
        if not historical_attempt:
            try:
                active_xml = active_engine.get_xml()
            except Exception:  # noqa: BLE001 - never expose engine internals through MCP.
                if not selection_reason_valid:
                    return models.rejected("active_build_snapshot_failed")
                active_state_regressed = True
            else:
                active_state_regressed = (
                    not _valid_pob_xml(active_xml)
                    or build_state_hash(active_xml) != snapshot.semantic_state_hash
                )
                if active_state_regressed and not selection_reason_valid:
                    return models.rejected("active_build_changed_after_evaluation")
            if active_state_regressed and later_findings_scope != "candidate_delta_only":
                return models.rejected("passing_baseline_implicated_by_later_findings")
        xml = snapshot.xml
    else:
        active_state_regressed = False
        if historical_attempt:
            return models.rejected("legacy_baseline_restore_unsupported")
        try:
            active_xml = active_engine.get_xml()
        except Exception:  # noqa: BLE001 - never expose engine internals through MCP.
            return models.rejected("active_build_snapshot_failed")
        if not _valid_pob_xml(active_xml):
            return models.rejected("active_build_snapshot_invalid")
        active_semantic_hash = build_state_hash(active_xml)
        if expected_semantic_hash and active_semantic_hash != expected_semantic_hash:
            return models.rejected("active_build_changed_after_evaluation")
        if snapshot is not None:
            if active_semantic_hash != snapshot.semantic_state_hash:
                return models.rejected("active_build_changed_after_evaluation")
            xml = snapshot.xml
        else:
            # Legacy receipts did not carry an in-memory Judge snapshot. Preserve their exact-raw
            # behavior when the active serializer is still byte-identical, otherwise fail closed and
            # require a fresh evaluation instead of inventing Judge provenance for new XML.
            if evaluator.compute_source_hash(active_xml) != state.source_hash:
                return models.rejected("trusted_evaluation_snapshot_unavailable")
            xml = active_xml
    blockers = completeness.artifact_blockers(xml)
    if blockers:
        return models.rejected(blockers[0], caveats=blockers[1:])
    round_trip = _validate_pob_round_trip(active_engine, xml)
    if round_trip.get("recoveryRequired"):
        return {
            **models.rejected("final_pob_round_trip_restore_failed"),
            "recoveryRequired": True,
        }
    if target_level >= 90 and round_trip.get("status") != "passed":
        return models.rejected(
            "final_pob_round_trip_failed",
            caveats=[str(round_trip.get("errorCode") or "round_trip_unavailable")],
        )

    refreshed_lifecycle = _refresh_saved_lifecycle(active_engine, xml, judge)
    if refreshed_lifecycle is not None and refreshed_lifecycle.get("errorCode"):
        return {
            **models.rejected(str(refreshed_lifecycle["errorCode"])),
            **({"recoveryRequired": True} if refreshed_lifecycle.get("recoveryRequired") else {}),
        }
    refreshed_checklist = (
        refreshed_lifecycle.pop("_createQualityChecklist", {})
        if refreshed_lifecycle is not None
        else {}
    )
    declaration_binding = (
        refreshed_lifecycle.pop("_lifecycleDeclarationBinding", None)
        if refreshed_lifecycle is not None
        else None
    )
    final_lifecycle = (
        refreshed_lifecycle
        if refreshed_lifecycle is not None
        else dict(receipt.get("lifecycleVerification") or {})
    )
    final_checklist = _tighten_quality_checklist(
        receipt.get("createQualityChecklist") or {}, refreshed_checklist
    )
    final_delivery_status = str(receipt.get("deliveryStatus") or "candidate")
    if refreshed_lifecycle is not None:
        # Keep every historical quality restriction, while retaining current same-state adverse
        # evidence. Cache loss is not a counterexample to the trusted historical checks.
        final_delivery_status = (
            "recommended"
            if final_checklist
            and all(
                item.get("status") in {"passed", "not_applicable"}
                for item in final_checklist.values()
            )
            and final_lifecycle.get("pass") is True
            else "candidate"
        )

    artifact_id = f"final-build:{uuid4()}"
    later_receipts = receipts[attempt_index + 1 :]
    later_regressed = any(
        item.get("judgeAdvisoryReport", {}).get("pass") is not True
        or bool(item.get("judgeAdvisoryReport", {}).get("hardFailures"))
        or item.get("hardLegalityAudit", {}).get("hardLegalityReady") is False
        for item in later_receipts
    )
    restoring_baseline = historical_attempt or active_state_regressed or mechanism_revision_changed
    selection_outcome = (
        "baseline_restored_after_regression"
        if restoring_baseline
        and (later_regressed or active_state_regressed or mechanism_revision_changed)
        else "earlier_passing_baseline_selected"
        if historical_attempt
        else "latest_passing_attempt_selected"
    )
    selection_ref = f"artifact-selection:{bound_run.run_id}:{attempt_index}"
    manifest = FinalBuildArtifactManifest(
        artifact_id=artifact_id,
        run_id=bound_run.run_id,
        candidate_id=candidate_id,
        attempt_index=attempt_index,
        snapshot_id=str(state.snapshot_id),
        source_hash=str(state.source_hash),
        trusted_evaluation_ref=f"run:{bound_run.run_id}:attempt:{attempt_index}",
        safe_summary=state.safe_summary,
        tested_skill_groups=state.tested_skill_groups,
        judge_report=judge,
        version_context=judge.version_context,
        hard_legality_audit_version=str(
            (receipt.get("hardLegalityAudit") or {}).get("auditVersion") or ""
        )
        or None,
        delivery_status=final_delivery_status,
        create_quality_checklist=final_checklist,
        pob_round_trip=round_trip,
        lifecycle_verification=final_lifecycle,
        lifecycle_declaration_binding=declaration_binding,
        artifact_selection_ref=selection_ref,
        mechanism_evidence_hash=(
            historical_evidence.get("bundleHash") if isinstance(historical_evidence, dict) else None
        ),
        selection_outcome=selection_outcome,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    temp_dir = root / f".{bound_run.run_id}.{uuid4().hex}.tmp"
    try:
        root.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir()
        (temp_dir / "build.xml").write_text(xml, encoding="utf-8")
        (temp_dir / "manifest.json").write_text(
            json.dumps(
                manifest.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        temp_dir.replace(final_dir)
    except OSError:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return models.rejected("final_artifact_write_failed")
    selection_written = run_store.write_artifact_selection(
        bound_run,
        {
            "artifactId": artifact_id,
            "candidateId": candidate_id,
            "selectedAttemptIndex": attempt_index,
            "selectedEvaluationRef": manifest.trusted_evaluation_ref,
            "selectionOutcome": selection_outcome,
            "selectionReason": (
                copy_safety.safe_text(selection_reason, limit=500) if selection_reason else None
            ),
            "laterFindingsScope": later_findings_scope,
            **(
                {
                    "mechanismEvidenceHash": historical_evidence["bundleHash"],
                    "sourceHash": state.source_hash,
                    "semanticStateHash": state.semantic_state_hash,
                }
                if isinstance(historical_evidence, dict)
                else {}
            ),
        },
    )
    if not selection_written:
        shutil.rmtree(final_dir, ignore_errors=True)
        return models.rejected("artifact_selection_receipt_write_failed")
    evaluation_snapshots.forget(run_id=bound_run.run_id)
    return {
        "status": "saved",
        "finalBuildArtifact": _safe_manifest(manifest),
        "artifactSelection": {
            "selectionRef": selection_ref,
            "selectedAttemptIndex": attempt_index,
            "selectionOutcome": selection_outcome,
            "restoredEarlierBaseline": historical_attempt,
            "restoredPassingBaseline": restoring_baseline,
        },
        **(
            {
                "selectedDesignEvidence": {
                    "mechanismEvidenceHash": historical_evidence["bundleHash"],
                    "mechanismBlueprintRef": historical_evidence["blueprintMarker"]["blueprintRef"],
                    "mechanismBlueprint": deepcopy(historical_evidence["mechanismBlueprint"]),
                    "researchMemoryUse": deepcopy(historical_evidence.get("researchMemoryUse")),
                    "researchExecutionPlan": deepcopy(
                        historical_evidence.get("researchExecutionPlan")
                    ),
                    "toolReferences": deepcopy(historical_evidence.get("toolReferences") or []),
                    "evidenceAudit": deepcopy(historical_evidence["blueprintMarker"].get("evidenceAudit")),
                }
            }
            if restoring_baseline and isinstance(historical_evidence, dict)
            else {}
        ),
        "containsRawPob": False,
        "orderingRecovery": (
            {
                "reviewAlreadyConsumed": True,
                "normalOrder": "save_artifact_before_review",
            }
            if review_already_consumed
            else None
        ),
    }


def list_final_build_artifacts() -> dict[str, Any]:
    artifacts = _iter_artifacts()
    artifacts.sort(key=lambda item: item[1].created_at, reverse=True)
    return {
        "status": "ok",
        "artifacts": [
            _safe_manifest(manifest, artifact_dir=artifact_dir)
            for artifact_dir, manifest in artifacts
        ],
        "containsRawPob": False,
    }


def preview_final_artifact_spirit_revalidation(
    engine_factory: Any,
    *,
    artifact_id: str,
) -> dict[str, Any]:
    """Recompute one immutable artifact's Spirit ledger without writing a receipt."""

    found = _find_artifact(artifact_id)
    if found is None:
        return models.rejected("final_artifact_not_found")
    artifact_dir, manifest = found
    xml = _verified_artifact_xml(artifact_dir, manifest)
    if xml is None:
        return models.rejected("final_artifact_corrupt")
    proposal = _compute_spirit_revalidation(engine_factory, manifest, xml)
    plan_hash = _spirit_revalidation_plan_hash(manifest, proposal)
    return {
        "status": "preview_ready",
        "artifactId": manifest.artifact_id,
        "expectedSourceHash": manifest.source_hash,
        "revalidationPlanHash": plan_hash,
        "proposedResult": proposal,
        "requiresUserApproval": True,
        "containsRawPob": False,
    }


def apply_final_artifact_spirit_revalidation(
    engine_factory: Any,
    *,
    artifact_id: str,
    expected_source_hash: str,
    revalidation_plan_hash: str,
    user_approved: bool,
) -> dict[str, Any]:
    """Append one preview-bound Spirit revalidation event without rewriting the artifact."""

    if user_approved is not True:
        return models.rejected("user_approval_required")
    preview = preview_final_artifact_spirit_revalidation(
        engine_factory,
        artifact_id=artifact_id,
    )
    if preview.get("status") != "preview_ready":
        return preview
    if (
        preview.get("expectedSourceHash") != expected_source_hash
        or preview.get("revalidationPlanHash") != revalidation_plan_hash
    ):
        return models.rejected("stale_spirit_revalidation_preview")
    found = _find_artifact(artifact_id)
    if found is None:
        return models.rejected("final_artifact_not_found")
    artifact_dir, manifest = found
    if manifest.source_hash != expected_source_hash:
        return models.rejected("stale_spirit_revalidation_preview")
    log_path = artifact_dir / "spirit-revalidation.json"
    with interprocess_file_lock(artifact_dir / ".spirit-revalidation.lock"):
        current = _read_spirit_revalidation_log(log_path, manifest)
        if current is None:
            return models.rejected("spirit_revalidation_log_corrupt")
        existing = next(
            (
                event
                for event in current["events"]
                if event.get("revalidationPlanHash") == revalidation_plan_hash
            ),
            None,
        )
        if existing is not None:
            return {
                "status": "already_applied",
                "artifactId": manifest.artifact_id,
                "revalidation": existing,
                "containsRawPob": False,
            }
        event = {
            "eventId": f"artifact-spirit-revalidation:{uuid4()}",
            "artifactId": manifest.artifact_id,
            "sourceHash": manifest.source_hash,
            "revalidationPlanHash": revalidation_plan_hash,
            **dict(preview["proposedResult"]),
            "appliedAt": datetime.now(timezone.utc).isoformat(),
            "containsRawPob": False,
        }
        current["events"].append(event)
        if not run_store.write_json_atomic(log_path, current):
            return models.rejected("spirit_revalidation_write_failed")
    return {
        "status": "applied",
        "artifactId": manifest.artifact_id,
        "revalidation": event,
        "containsRawPob": False,
    }


def mark_final_build_delivery_complete(artifact_id: str) -> bool:
    """Record that every required user-facing file was exported for this artifact."""

    found = _find_artifact(artifact_id)
    if found is None:
        return False
    artifact_dir, manifest = found
    marker = {
        "schemaVersion": 1,
        "artifactId": manifest.artifact_id,
        "runId": manifest.run_id,
        "deliveredAt": datetime.now(timezone.utc).isoformat(),
        "containsRawPob": False,
    }
    return run_store.write_json_atomic(artifact_dir / "delivery-complete.json", marker)


def load_final_build_artifact(active_engine: Any, *, artifact_id: str) -> dict[str, Any]:
    found = _find_artifact(artifact_id)
    if found is None:
        return models.rejected("final_artifact_not_found")
    artifact_dir, manifest = found
    try:
        xml = (artifact_dir / "build.xml").read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return models.rejected("final_artifact_corrupt")
    if not _valid_pob_xml(xml) or evaluator.compute_source_hash(xml) != manifest.source_hash:
        return models.rejected("final_artifact_corrupt")
    try:
        loaded = active_engine.load_build_xml(xml, name=manifest.artifact_id)
    except Exception:  # noqa: BLE001 - never expose engine internals through MCP.
        return models.rejected("final_artifact_restore_failed")
    return {
        "status": "loaded",
        "finalBuildArtifact": _safe_manifest(manifest, artifact_dir=artifact_dir),
        "activeBuild": _safe_loaded_summary(loaded),
        "containsRawPob": False,
    }


def read_final_build_artifact_for_export(
    artifact_id: str,
) -> tuple[FinalBuildArtifactManifest, str] | None:
    """Return a verified artifact to the internal export layer without exposing it through MCP."""
    found = _find_artifact(artifact_id)
    if found is None:
        return None
    artifact_dir, manifest = found
    try:
        xml = (artifact_dir / "build.xml").read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    if (
        not _valid_pob_xml(xml)
        or evaluator.compute_source_hash(xml) != manifest.source_hash
        or manifest.judge_report.status != "evaluated"
        or manifest.judge_report.passed is not True
        or manifest.judge_report.hard_failures
        or manifest.judge_report.evaluated_snapshot_id != manifest.snapshot_id
        or manifest.judge_report.evaluated_source_hash != manifest.source_hash
        or not _spirit_delivery_eligible(artifact_dir, manifest)
    ):
        return None
    return manifest, xml


def read_artifact_lifecycle_declarations(
    manifest: FinalBuildArtifactManifest,
    xml: str,
) -> dict[str, Any] | None:
    """Read typed declarations only when bound to this artifact's exact state and Judge target.

    These are inputs to a new observation, never a reusable pass result. Legacy artifacts without
    declarations remain unverified; explicit empty declarations remain an intentional revocation.
    """
    binding = getattr(manifest, "lifecycle_declaration_binding", None)
    target = manifest.judge_report.calculation_context
    if not isinstance(binding, dict) or target is None:
        return None
    expected_target = lifecycle_observation.normalize_target(
        target.model_dump(mode="json", by_alias=True)
    )
    if (
        not _valid_pob_xml(xml)
        or evaluator.compute_source_hash(xml) != manifest.source_hash
        or binding.get("observationVersion") != lifecycle_observation.OBSERVATION_VERSION
        or binding.get("stateHash") != build_state_hash(xml)
        or binding.get("observationTarget") != expected_target
        or not isinstance(binding.get("declarations"), dict)
    ):
        return None
    try:
        # Validate without the legacy-derived-field stripping used by older direct callers.
        parsed = LifecycleStageVerificationState.model_validate(binding["declarations"])
        declarations = lifecycle_observation.declaration_payload(parsed)
    except (ValidationError, TypeError, ValueError):
        return None
    if models.validate_no_raw_or_hidden_reasoning(declarations).get("status") != "accepted":
        return None
    return declarations


def _tighten_quality_checklist(
    previous: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Join current adverse evidence without promoting historical quality restrictions."""
    result = deepcopy(previous)
    severity = {"not_applicable": 0, "passed": 0, "unknown": 1, "failed": 2}
    for name, item in current.items():
        if not isinstance(item, dict) or item.get("currentAdverseEvidence") is not True:
            continue
        new_status = item.get("status")
        if new_status not in {"unknown", "failed"}:
            continue
        old = result.get(name) or {}
        if severity.get(str(old.get("status")), 0) > severity[new_status]:
            tightened = deepcopy(old)
            tightened["currentAdverseEvidence"] = True
        else:
            tightened = deepcopy(item)
        tightened["reasons"] = list(dict.fromkeys([
            *old.get("reasons", []), *item.get("reasons", []),
        ]))
        result[name] = tightened
    return result


def _iter_artifacts() -> list[tuple[Path, FinalBuildArtifactManifest]]:
    root = artifacts_dir()
    if not root.is_dir():
        return []
    found: list[tuple[Path, FinalBuildArtifactManifest]] = []
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest = _read_manifest(child / "manifest.json")
        if manifest is not None:
            found.append((child, manifest))
    return found


def _find_artifact(artifact_id: str) -> tuple[Path, FinalBuildArtifactManifest] | None:
    if not isinstance(artifact_id, str) or not artifact_id.startswith("final-build:"):
        return None
    return next(
        (
            (artifact_dir, manifest)
            for artifact_dir, manifest in _iter_artifacts()
            if manifest.artifact_id == artifact_id
        ),
        None,
    )


def _read_manifest(path: Path) -> FinalBuildArtifactManifest | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = FinalBuildArtifactManifest.model_validate(payload)
    except (UnicodeDecodeError, OSError, json.JSONDecodeError, ValidationError):
        return None
    if manifest.schema_version not in {1, ARTIFACT_SCHEMA_VERSION}:
        return None
    if (
        manifest.schema_version == ARTIFACT_SCHEMA_VERSION
        and manifest.hard_legality_audit_version
        not in hard_legality.ARTIFACT_COMPATIBLE_AUDIT_VERSIONS
    ):
        return None
    return manifest


def _safe_manifest(
    manifest: FinalBuildArtifactManifest,
    *,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    judge = manifest.judge_report
    output = {
        "artifactId": manifest.artifact_id,
        "runId": manifest.run_id,
        "candidateId": manifest.candidate_id,
        "attemptIndex": manifest.attempt_index,
        "snapshotId": manifest.snapshot_id,
        "sourceHash": manifest.source_hash,
        "artifactSelectionRef": manifest.artifact_selection_ref,
        "selectionOutcome": manifest.selection_outcome,
        "safeSummary": manifest.safe_summary,
        "testedSkillGroups": [
            group.model_dump(mode="json", by_alias=True) for group in manifest.tested_skill_groups
        ],
        "judgeStatus": judge.status,
        "judgePassed": judge.passed,
        "judgeHardFailures": judge.hard_failures,
        "judgeFeedbackMode": judge.feedback_mode,
        "judgeSubjectiveFeedbackSuppressed": judge.subjective_feedback_suppressed,
        "versionContext": manifest.version_context.model_dump(mode="json", by_alias=True),
        "hardLegalityAuditVersion": manifest.hard_legality_audit_version,
        "deliveryStatus": manifest.delivery_status,
        "createQualityChecklist": manifest.create_quality_checklist,
        "pobRoundTrip": manifest.pob_round_trip,
        "lifecycleVerification": manifest.lifecycle_verification,
        "spiritValidationStatus": _spirit_validation_status(artifact_dir, manifest),
        "createdAt": manifest.created_at,
        "localOnly": manifest.local_only,
    }
    if judge.feedback_mode == "strict":
        output.update(
            {
                "judgeQualityBand": judge.quality_band,
                "judgeScoreApplicability": judge.score_applicability,
                "judgePlayabilityFailures": judge.playability_failures,
                "judgeQualityWarnings": judge.quality_warnings,
                "judgeCaveats": judge.caveats,
            }
        )
    return output


def _safe_loaded_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"loaded": True}
    return {
        key: payload[key]
        for key in ("mainSkill", "treeVersion")
        if key in payload and isinstance(payload[key], (str, int, float, bool))
    }


def _valid_pob_xml(xml: Any) -> bool:
    if not isinstance(xml, str) or not xml.strip():
        return False
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return False
    return root.tag in {"PathOfBuilding", "PathOfBuilding2"}


def _validate_pob_round_trip(engine: Any, xml: str) -> dict[str, Any]:
    """Load/save once in PoB and compare only user-visible build structure."""

    load = getattr(engine, "load_build_xml", None)
    get_xml = getattr(engine, "get_xml", None)
    if not callable(load) or not callable(get_xml):
        return {"status": "unavailable", "errorCode": "round_trip_engine_unavailable"}
    lock_factory = getattr(engine, "transaction_lock", None)
    context = lock_factory() if callable(lock_factory) else nullcontext()
    try:
        with context:
            if getattr(engine, _RECOVERY_ATTRIBUTE, False):
                return {
                    "status": "failed",
                    "errorCode": "build_state_recovery_required",
                    "recoveryRequired": True,
                    "stateRestored": False,
                }
            original = get_xml()
            original_hash = build_state_hash(original)
            try:
                load(xml, name="final-artifact-round-trip")
                serialized = get_xml()
            finally:
                try:
                    load(original, name="final-artifact-round-trip-restore")
                    restored_hash = build_state_hash(get_xml())
                except Exception:  # noqa: BLE001 - a failed restore must stop every save level.
                    setattr(engine, _RECOVERY_ATTRIBUTE, True)
                    return {
                        "status": "failed",
                        "errorCode": "round_trip_restore_failed",
                        "recoveryRequired": True,
                        "stateRestored": False,
                    }
                if restored_hash != original_hash:
                    setattr(engine, _RECOVERY_ATTRIBUTE, True)
                    return {
                        "status": "failed",
                        "errorCode": "round_trip_restore_failed",
                        "recoveryRequired": True,
                        "stateRestored": False,
                    }
    except Exception:  # noqa: BLE001 - final delivery fails closed without engine internals.
        return {"status": "failed", "errorCode": "round_trip_engine_failed"}
    expected = _pob_structure_summary(xml)
    actual = _pob_structure_summary(serialized)
    if expected is None or actual is None:
        return {"status": "failed", "errorCode": "round_trip_snapshot_invalid"}
    comparisons = {
        "skillGroupsAndSupports": expected["skillGroups"] == actual["skillGroups"],
        "equipmentCount": expected["equipmentSlots"] == actual["equipmentSlots"],
        "itemSocketsAndRunes": expected["itemSockets"] == actual["itemSockets"],
        "passiveJewels": expected["passiveJewels"] == actual["passiveJewels"],
    }
    return {
        "status": "passed" if all(comparisons.values()) else "failed",
        "checks": comparisons,
        "equipmentCount": len(actual["equipmentSlots"]),
        "skillGroupCount": len(actual["skillGroups"]),
        "passiveJewelCount": len(actual["passiveJewels"]),
        "stateRestored": True,
        "restoredStateHash": restored_hash,
        **({"errorCode": "round_trip_structure_changed"} if not all(comparisons.values()) else {}),
    }


def _refresh_saved_lifecycle(
    engine: Any,
    xml: str,
    judge: models.JudgeAdvisoryReport,
) -> dict[str, Any] | None:
    """Observe late mechanism evidence against this exact Judge state and target only."""

    if not all(
        callable(getattr(engine, name, None))
        for name in (
            "transaction_lock",
            "get_xml",
            "load_build_xml",
            "get_build",
            "get_stats",
            "get_defenses",
        )
    ):
        return None
    target = (
        judge.calculation_context.model_dump(mode="json", by_alias=True)
        if judge.calculation_context is not None
        else {}
    )
    if not all(target.get(key) for key in ("groupIndex", "activeIndex", "skillName")):
        return None
    expected_hash = build_state_hash(xml)
    with engine.transaction_lock():
        if getattr(engine, _RECOVERY_ATTRIBUTE, False):
            return {"errorCode": "build_state_recovery_required", "recoveryRequired": True}
        try:
            original = engine.get_xml()
            original_hash = build_state_hash(original)
        except Exception:  # noqa: BLE001 - expose no engine internals.
            return {"errorCode": "final_lifecycle_snapshot_failed"}
        result: dict[str, Any]
        try:
            engine.load_build_xml(xml, name="final-artifact-lifecycle")
            if build_state_hash(engine.get_xml()) != expected_hash:
                result = {"errorCode": "final_lifecycle_snapshot_mismatch"}
            else:
                checked = validation_checkpoint.inspect_generation_checkpoint(
                    engine,
                    strict_mode=judge.feedback_mode == "strict",
                    offense_skill_group_index=int(target["groupIndex"]),
                    expected_skill_name=str(target["skillName"]),
                )
                actual_target = checked.get("calculationContext") or {}
                lifecycle = checked.get("lifecycleVerification")
                if (
                    checked.get("status") == "error"
                    or checked.get("stateHash") != expected_hash
                    or build_state_hash(engine.get_xml()) != expected_hash
                    or any(
                        actual_target.get(key) != target[key]
                        for key in ("groupIndex", "activeIndex", "skillName")
                    )
                    or not isinstance(lifecycle, dict)
                    or lifecycle.get("stateHash") != expected_hash
                    or lifecycle.get("observationTarget")
                    != {key: target[key] for key in ("groupIndex", "activeIndex", "skillName")}
                ):
                    result = {"errorCode": "final_lifecycle_snapshot_mismatch"}
                else:
                    legality = checked.get("hardLegality") or {}
                    if (
                        checked.get("hardLegalityReady") is False
                        or legality.get("status") == "failed"
                        or legality.get("hardFailures")
                    ):
                        result = {"errorCode": "final_candidate_hard_legality_not_verified"}
                    else:
                        result = dict(lifecycle)
                        result["_createQualityChecklist"] = deepcopy(
                            checked.get("createQualityChecklist") or {}
                        )
                        declarations = lifecycle_observation.state_for_target(
                            engine, state_hash=expected_hash, observation_target=target
                        )
                        if declarations is not None:
                            parsed = LifecycleStageVerificationState.model_validate(declarations)
                            declarations = lifecycle_observation.declaration_payload(parsed)
                            if (
                                models.validate_no_raw_or_hidden_reasoning(declarations).get("status")
                                != "accepted"
                            ):
                                raise ValueError("unsafe lifecycle declarations")
                            result["_lifecycleDeclarationBinding"] = {
                                "observationVersion": lifecycle_observation.OBSERVATION_VERSION,
                                "stateHash": expected_hash,
                                "observationTarget": lifecycle_observation.normalize_target(target),
                                "declarations": declarations,
                            }
        except Exception:  # noqa: BLE001
            result = {"errorCode": "final_lifecycle_verification_failed"}
        try:
            engine.load_build_xml(original, name="final-artifact-lifecycle-restore")
            if build_state_hash(engine.get_xml()) != original_hash:
                raise ValueError("state mismatch")
        except Exception:  # noqa: BLE001
            setattr(engine, _RECOVERY_ATTRIBUTE, True)
            return {"errorCode": "final_lifecycle_restore_failed", "recoveryRequired": True}
        if getattr(engine, _RECOVERY_ATTRIBUTE, False):
            return {"errorCode": "build_state_recovery_required", "recoveryRequired": True}
        return result


def _pob_structure_summary(xml: str) -> dict[str, Any] | None:
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, TypeError, ValueError):
        return None
    skills = root.find("Skills")
    items = root.find("Items")
    if skills is None or items is None:
        return None
    active_skill_set = str(skills.get("activeSkillSet") or "1")
    skill_set = next(
        (node for node in skills.findall("SkillSet") if str(node.get("id")) == active_skill_set),
        None,
    )
    active_item_set = str(items.get("activeItemSet") or "1")
    item_set = next(
        (node for node in items.findall("ItemSet") if str(node.get("id")) == active_item_set),
        None,
    )
    if skill_set is None or item_set is None:
        return None
    passive_jewels = pob_structure.active_spec_passive_jewels(root)
    if passive_jewels is None:
        return None
    skill_groups = []
    for group in skill_set.findall("Skill"):
        if str(group.get("enabled") or "true").casefold() not in {"1", "true"}:
            continue
        skill_groups.append(
            tuple(
                (
                    str(gem.get("nameSpec") or gem.get("skillId") or ""),
                    "support"
                    if "SupportGem" in str(gem.get("gemId") or "")
                    or str(gem.get("skillId") or "").startswith("Support")
                    else "active",
                )
                for gem in group.findall("Gem")
                if str(gem.get("enabled") or "true").casefold() in {"1", "true"}
            )
        )
    by_id = {
        str(item.get("id")): completeness._parse_item_text(item.text or "")
        for item in items.findall("Item")
        if item.get("id")
    }
    slots = {
        str(slot.get("name") or ""): str(slot.get("itemId") or "0")
        for slot in item_set.findall("Slot")
        if str(slot.get("itemId") or "0") != "0"
    }
    equipment_slots = sorted(slot for slot in slots if not slot.startswith("Jewel "))
    item_sockets = {
        slot: {
            "socketCount": int((by_id.get(item_id) or {}).get("runeSockets") or 0),
            "runes": tuple((by_id.get(item_id) or {}).get("runes") or []),
        }
        for slot, item_id in slots.items()
        if not slot.startswith("Jewel ")
    }
    return {
        "skillGroups": tuple(skill_groups),
        "equipmentSlots": tuple(equipment_slots),
        "itemSockets": item_sockets,
        "passiveJewels": passive_jewels,
    }


def _verified_artifact_xml(
    artifact_dir: Path,
    manifest: FinalBuildArtifactManifest,
) -> str | None:
    try:
        xml = (artifact_dir / "build.xml").read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    if not _valid_pob_xml(xml) or evaluator.compute_source_hash(xml) != manifest.source_hash:
        return None
    return xml


def _compute_spirit_revalidation(
    engine_factory: Any,
    manifest: FinalBuildArtifactManifest,
    xml: str,
) -> dict[str, Any]:
    engine = None
    try:
        engine = engine_factory()
        engine.load_build_xml(xml, name=manifest.artifact_id)
        build = engine.get_build()
        if not isinstance(build, dict):
            raise TypeError("invalid build readback")
        ledger = hard_legality.spirit_budget_check(build)
        active_weapon_set = build.get("activeWeaponSet")
    except Exception:  # noqa: BLE001 - a legacy artifact must fail closed without internals.
        ledger = hard_legality.spirit_budget_check({})
        active_weapon_set = None
    finally:
        close = getattr(engine, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - cleanup cannot change the safe outcome.
                pass
    failure = ledger.get("failureCode")
    if failure == "spirit_budget_exceeded":
        outcome = "spirit_budget_exceeded"
    elif failure is not None:
        outcome = "legacy_spirit_unverified"
    else:
        outcome = "passed"
    return {
        "outcome": outcome,
        "deliveryEligible": outcome == "passed",
        "failureCode": failure if outcome != "legacy_spirit_unverified" else outcome,
        "ledger": {
            key: ledger.get(key)
            for key in (
                "available",
                "reservedCapped",
                "unreserved",
                "requested",
                "overBy",
                "used",
                "ledgerStatus",
            )
        },
        "activeWeaponSet": active_weapon_set if active_weapon_set in {1, 2} else None,
    }


def _spirit_revalidation_plan_hash(
    manifest: FinalBuildArtifactManifest,
    proposal: dict[str, Any],
) -> str:
    encoded = json.dumps(
        {
            "artifactId": manifest.artifact_id,
            "sourceHash": manifest.source_hash,
            "proposal": proposal,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _read_spirit_revalidation_log(
    path: Path,
    manifest: FinalBuildArtifactManifest,
) -> dict[str, Any] | None:
    if not path.exists():
        return {
            "schemaVersion": SPIRIT_REVALIDATION_SCHEMA_VERSION,
            "artifactId": manifest.artifact_id,
            "events": [],
            "containsRawPob": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    events = payload.get("events") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != SPIRIT_REVALIDATION_SCHEMA_VERSION
        or payload.get("artifactId") != manifest.artifact_id
        or payload.get("containsRawPob") is not False
        or not isinstance(events, list)
        or any(
            not isinstance(event, dict)
            or event.get("artifactId") != manifest.artifact_id
            or event.get("sourceHash") != manifest.source_hash
            or event.get("outcome")
            not in {"passed", "spirit_budget_exceeded", "legacy_spirit_unverified"}
            or not isinstance(event.get("deliveryEligible"), bool)
            or event.get("containsRawPob") is not False
            for event in events
        )
    ):
        return None
    return payload


def _latest_spirit_revalidation(
    artifact_dir: Path | None,
    manifest: FinalBuildArtifactManifest,
) -> dict[str, Any] | None:
    if artifact_dir is None:
        return None
    payload = _read_spirit_revalidation_log(
        artifact_dir / "spirit-revalidation.json",
        manifest,
    )
    if payload is None or not payload["events"]:
        return None
    return payload["events"][-1]


def _spirit_delivery_eligible(
    artifact_dir: Path,
    manifest: FinalBuildArtifactManifest,
) -> bool:
    if (
        manifest.schema_version == ARTIFACT_SCHEMA_VERSION
        and manifest.hard_legality_audit_version in hard_legality.ARTIFACT_COMPATIBLE_AUDIT_VERSIONS
    ):
        return True
    latest = _latest_spirit_revalidation(artifact_dir, manifest)
    return bool(latest and latest.get("outcome") == "passed")


def _spirit_validation_status(
    artifact_dir: Path | None,
    manifest: FinalBuildArtifactManifest,
) -> str:
    if (
        manifest.schema_version == ARTIFACT_SCHEMA_VERSION
        and manifest.hard_legality_audit_version in hard_legality.ARTIFACT_COMPATIBLE_AUDIT_VERSIONS
    ):
        return "current"
    latest = _latest_spirit_revalidation(artifact_dir, manifest)
    return str(latest.get("outcome")) if latest is not None else "legacy_spirit_unverified"
