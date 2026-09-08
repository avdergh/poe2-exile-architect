"""Trusted, raw-free Draft evidence retained with an exact Judge attempt.

Drafts are frozen only by the successful validator, in process memory. Judge receipts may retain
that safe evidence; the exact XML remains exclusively in ``evaluation_snapshots`` until artifact
selection. Historical evidence never overwrites the current Draft or Blueprint markers.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from threading import RLock
from typing import Any

from server.compute.state import build_state_hash
from server.knowledge import research_execution

from . import evidence_authority, mechanism_signature, models, run_store


_LOCK = RLock()
_MAX_DRAFTS = 32
_DRAFT_TTL = timedelta(hours=4)
_DRAFTS: OrderedDict[tuple[str, str], tuple[datetime, dict[str, Any]]] = OrderedDict()
_DRAFT_KEYS = {
    "runId",
    "candidateId",
    "blueprintMarker",
    "draftMarker",
    "mechanismBlueprint",
    "researchMemoryUse",
    "researchExecutionPlan",
}


def remember_validated_draft(
    bound_run: run_store.BoundRun,
    candidate: models.PrototypeBuildCandidate,
    draft_marker: dict[str, Any],
    blueprint_marker: dict[str, Any] | None,
) -> None:
    """Freeze only a successfully validated design, never arbitrary caller evidence."""

    if (
        candidate.mechanism_blueprint is None
        or blueprint_marker is None
        or not draft_marker.get("mechanismSignatureHash")
    ):
        return
    payload = {
        "runId": bound_run.run_id,
        "candidateId": candidate.candidate_id,
        "blueprintMarker": deepcopy(blueprint_marker),
        "draftMarker": deepcopy(draft_marker),
        "mechanismBlueprint": candidate.mechanism_blueprint.model_dump(mode="json", by_alias=True),
        "researchMemoryUse": (
            candidate.research_memory_use.model_dump(mode="json", by_alias=True)
            if candidate.research_memory_use is not None
            else None
        ),
        "researchExecutionPlan": (
            candidate.research_execution_plan.model_dump(mode="json", by_alias=True)
            if candidate.research_execution_plan is not None
            else None
        ),
    }
    if "designToolsHash" in draft_marker:
        payload["toolReferences"] = evidence_authority.design_tool_refs(candidate)
    if not _valid_draft(payload):
        raise run_store.RunStoreError("generation_draft_evidence_invalid")
    if not _current_markers_match(bound_run, payload):
        raise run_store.RunStoreError("generation_draft_evidence_changed")
    with _LOCK:
        _evict_locked()
        key = _draft_key(bound_run)
        # Reconstructing a lost bundle must not renew its original validation lifetime.
        validated_at = draft_marker.get("validatedAt")
        created_at = (
            datetime.fromisoformat(validated_at).astimezone(timezone.utc)
            if validated_at
            else datetime.now(timezone.utc)
        )
        _DRAFTS[key] = (created_at, payload)
        _DRAFTS.move_to_end(key)
        while len(_DRAFTS) > _MAX_DRAFTS:
            _DRAFTS.popitem(last=False)


def read_validated_draft(
    bound_run: run_store.BoundRun,
    *,
    candidate_id: str,
) -> dict[str, Any] | None:
    """Missing legacy/process-local evidence cannot authorize historical restoration."""

    with _LOCK:
        _evict_locked()
        entry = _DRAFTS.get(_draft_key(bound_run))
        payload = deepcopy(entry[1]) if entry else None
    if payload is None:
        return None
    if payload.get("candidateId") != candidate_id or not _current_markers_match(bound_run, payload):
        raise run_store.RunStoreError("generation_draft_evidence_changed")
    return payload


def bind_evaluation(
    draft: dict[str, Any] | None,
    receipt: dict[str, Any],
    *,
    run_id: str,
    attempt_index: int,
) -> dict[str, Any] | None:
    """Bind the frozen design to the exact state, source and Judge calculation target."""

    if draft is None or (receipt.get("judgeAdvisoryReport") or {}).get("status") != "evaluated":
        return None
    state = receipt.get("transientBuildState") or {}
    payload = {
        "schemaVersion": 1,
        **deepcopy(draft),
        "runId": run_id,
        "attemptIndex": attempt_index,
        "sourceHash": state.get("sourceHash"),
        "semanticStateHash": state.get("semanticStateHash"),
        "snapshotId": state.get("snapshotId"),
        "mechanismBinding": deepcopy(receipt.get("mechanismBinding")),
        "containsRawPob": False,
    }
    payload["bundleHash"] = _hash(payload)
    if not valid_evaluation_evidence(
        {**receipt, "runId": run_id, "attemptIndex": attempt_index, "mechanismEvidence": payload}
    ):
        raise run_store.RunStoreError("trusted_mechanism_evidence_mismatch")
    return payload


def valid_evaluation_evidence(receipt: dict[str, Any]) -> bool:
    """Validate all historical bindings on every receipt read and before persistence."""

    evidence = receipt.get("mechanismEvidence")
    if not isinstance(evidence, dict):
        return False
    state = receipt.get("transientBuildState") or {}
    judge = receipt.get("judgeAdvisoryReport") or {}
    if (
        evidence.get("schemaVersion") != 1
        or set(evidence)
        != (_DRAFT_KEYS | ({"toolReferences"} if "toolReferences" in evidence else set()))
        | {
            "schemaVersion",
            "attemptIndex",
            "sourceHash",
            "semanticStateHash",
            "snapshotId",
            "mechanismBinding",
            "containsRawPob",
            "bundleHash",
        }
        or evidence.get("containsRawPob") is not False
        or evidence.get("bundleHash")
        != _hash({key: value for key, value in evidence.items() if key != "bundleHash"})
        or not _valid_draft(evidence)
        or any(
            evidence.get(key) != receipt.get(key)
            for key in ("runId", "candidateId", "attemptIndex")
        )
        or any(
            evidence.get(key) != state.get(key)
            for key in ("sourceHash", "semanticStateHash", "snapshotId")
        )
        or evidence.get("mechanismBinding") != receipt.get("mechanismBinding")
        or evidence.get("mechanismBinding") != _binding(evidence["draftMarker"])
        or judge.get("evaluatedSnapshotId") != state.get("snapshotId")
        or judge.get("evaluatedSourceHash") != state.get("sourceHash")
        or (judge.get("versionContext") or {}).get("researchMemoryRef")
        != evidence["draftMarker"].get("researchMemoryRef")
    ):
        return False
    selected = judge.get("selectedSkill")
    context = evidence["draftMarker"].get("calculationContext") or {}
    actual_context = judge.get("calculationContext") or {}
    return isinstance(selected, dict) and (
        all(
            actual_context.get(key) == context.get(key)
            for key in ("groupIndex", "activeIndex", "skillName")
        )
        and isinstance(context.get("groupIndex"), int)
        and context["groupIndex"] > 0
        and isinstance(context.get("activeIndex"), int)
        and context["activeIndex"] > 0
        and bool(context.get("skillName"))
        and selected.get("groupIndex") == context.get("groupIndex")
        and selected.get("skillName") == context.get("skillName")
    )


def current_markers_match(bound_run: run_store.BoundRun, receipt: dict[str, Any]) -> bool:
    """A later Research/Draft revision also counts as drift even if the signature is unchanged."""

    evidence = receipt.get("mechanismEvidence")
    return isinstance(evidence, dict) and _current_markers_match(bound_run, evidence)


def review_context(
    bound_run: run_store.BoundRun,
    trusted_receipts: list[dict[str, Any]],
    artifact_selection: dict[str, Any] | None,
    candidate: models.PrototypeBuildCandidate | dict[str, Any],
) -> dict[str, Any] | None:
    """Authorize old validator markers only through the saved exact artifact selection.

    Existing provenance, Blueprint and Research validators must still run using these markers.
    This function cannot promote raw input, a caller-provided selection, or an unsaved baseline.
    """

    if artifact_selection is None:
        return None
    if artifact_selection != run_store.read_artifact_selection(bound_run):
        raise run_store.RunStoreError("artifact_selection_receipt_mismatch")
    index = artifact_selection.get("selectedAttemptIndex")
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or not 0 <= index < len(trusted_receipts)
    ):
        raise run_store.RunStoreError("artifact_selection_receipt_mismatch")
    receipt = trusted_receipts[index]
    if receipt.get("runId") != bound_run.run_id or receipt.get("attemptIndex") != index:
        raise run_store.RunStoreError("trusted_evaluation_mismatch")
    evidence = receipt.get("mechanismEvidence")
    if evidence is None:
        if artifact_selection.get("mechanismEvidenceHash") is not None:
            raise run_store.RunStoreError("trusted_mechanism_evidence_mismatch")
        return None
    if not valid_evaluation_evidence(receipt):
        raise run_store.RunStoreError("trusted_mechanism_evidence_mismatch")
    state = receipt["transientBuildState"]
    if (
        artifact_selection.get("mechanismEvidenceHash") != evidence["bundleHash"]
        or artifact_selection.get("candidateId") != receipt["candidateId"]
        or artifact_selection.get("sourceHash") != state["sourceHash"]
        or artifact_selection.get("semanticStateHash") != state["semanticStateHash"]
    ):
        raise run_store.RunStoreError("artifact_selection_receipt_mismatch")
    restoring = (
        index != len(trusted_receipts) - 1
        or not _current_markers_match(bound_run, evidence)
        or artifact_selection.get("selectionOutcome") != "latest_passing_attempt_selected"
    )
    if restoring and (
        artifact_selection.get("laterFindingsScope") != "candidate_delta_only"
        or not artifact_selection.get("selectionReason")
    ):
        raise run_store.RunStoreError("passing_baseline_implicated_by_later_findings")
    # The artifact, not the now-evicted process snapshot, anchors post-save validation.
    from . import artifacts

    loaded = artifacts.read_final_build_artifact_for_export(artifact_selection["artifactId"])
    if loaded is None:
        raise run_store.RunStoreError("final_artifact_corrupt")
    manifest, xml = loaded
    if (
        manifest.run_id != bound_run.run_id
        or manifest.candidate_id != receipt["candidateId"]
        or manifest.attempt_index != index
        or manifest.trusted_evaluation_ref != artifact_selection.get("selectedEvaluationRef")
        or manifest.source_hash != state["sourceHash"]
        or manifest.snapshot_id != state["snapshotId"]
        or manifest.mechanism_evidence_hash != evidence["bundleHash"]
        or manifest.selection_outcome != artifact_selection.get("selectionOutcome")
        or manifest.artifact_selection_ref != f"artifact-selection:{bound_run.run_id}:{index}"
        or manifest.judge_report.model_dump(mode="json", by_alias=True)
        != receipt["judgeAdvisoryReport"]
        or build_state_hash(xml) != state["semanticStateHash"]
    ):
        raise run_store.RunStoreError("trusted_mechanism_evidence_mismatch")
    try:
        parsed = (
            candidate
            if isinstance(candidate, models.PrototypeBuildCandidate)
            else models.PrototypeBuildCandidate.model_validate(candidate)
        )
    except models.ValidationError as exc:
        raise run_store.RunStoreError("generation_baseline_candidate_mismatch") from exc
    if (
        parsed.candidate_id != receipt["candidateId"]
        or parsed.mechanism_blueprint_ref != evidence["blueprintMarker"]["blueprintRef"]
        or parsed.mechanism_blueprint is None
        or models.mechanism_blueprint_hash(parsed.mechanism_blueprint)
        != evidence["blueprintMarker"]["blueprintHash"]
        or parsed.version_context.research_memory_ref
        != evidence["draftMarker"]["researchMemoryRef"]
        or research_decision_hash(parsed.research_memory_use, parsed.research_execution_plan)
        != research_decision_hash(
            evidence.get("researchMemoryUse"), evidence.get("researchExecutionPlan")
        )
        or ("designToolsHash" in evidence["draftMarker"]
            and not evidence_authority.design_tools_match(
                parsed, evidence["draftMarker"],
                original_evidence_uses=evidence_authority.design_evidence_uses(evidence.get("researchExecutionPlan")),
            ))
    ):
        raise run_store.RunStoreError("generation_baseline_candidate_mismatch")
    return {
        "draftMarker": deepcopy(evidence["draftMarker"]),
        "blueprintMarker": deepcopy(evidence["blueprintMarker"]),
        "mechanismBinding": deepcopy(evidence["mechanismBinding"]),
        "selectedAttemptIndex": index,
        "mechanismEvidenceHash": evidence["bundleHash"],
        "designEvidenceUses": evidence_authority.design_evidence_uses(evidence.get("researchExecutionPlan")),
    }


def _valid_draft(payload: dict[str, Any]) -> bool:
    try:
        blueprint = models.MechanismBlueprint.model_validate(payload.get("mechanismBlueprint"))
        use = payload.get("researchMemoryUse")
        if use is not None:
            models.ResearchMemoryUse.model_validate(use)
        plan = payload.get("researchExecutionPlan")
        if plan is not None:
            models.ResearchExecutionPlan.model_validate(plan)
        marker = payload.get("blueprintMarker")
        draft = payload.get("draftMarker")
        if not isinstance(marker, dict) or not isinstance(draft, dict):
            return False
        if "designEvidenceUses" in draft or "designEvidenceUsesHash" in draft:
            uses = evidence_authority.design_evidence_uses(plan)
            if (draft.get("designEvidenceUses") != uses
                or draft.get("designEvidenceUsesHash") != evidence_authority.audit_hash(uses)):
                return False
        return (
            models.validate_no_raw_or_hidden_reasoning(
                {key: payload.get(key) for key in _DRAFT_KEYS | {"toolReferences"}}
            ).get("status")
            == "accepted"
            and marker.get("schemaVersion") == 1
            and ("evidenceAuditHash" not in draft or (
                evidence_authority.audit_matches(marker, blueprint, payload.get("toolReferences") or [])
                and draft.get("evidenceAuditHash") == marker.get("evidenceAuditHash")
                and draft.get("designToolsHash") == evidence_authority.audit_hash(
                    {"toolReferences": payload.get("toolReferences")}
                )
                and draft.get("designToolRefs") == [row["queryRef"] for row in payload.get("toolReferences") or []]
            ))
            and draft.get("schemaVersion") in {2, 3}
            and (
                draft.get("schemaVersion") == 2
                or draft.get("researchDecisionHash") == research_decision_hash(use, plan)
            )
            and marker.get("candidateId") == draft.get("candidateId") == payload.get("candidateId")
            and marker.get("researchMemoryRef") == draft.get("researchMemoryRef")
            and marker.get("blueprintHash") == models.mechanism_blueprint_hash(blueprint)
            and marker.get("blueprintRef") == draft.get("mechanismBlueprintRef")
            and marker.get("blueprintHash") == draft.get("mechanismBlueprintHash")
            and draft.get("mechanismSignatureHash")
            == mechanism_signature.signature_hash(draft.get("mechanismSignature") or {})
            and draft.get("researchExecutionStructureHash") == _plan_structure(plan)
            and draft.get("researchExecutionContractRef")
            == (plan.get("contractRef") if isinstance(plan, dict) else None)
            and marker.get("noRawMaterial") is True
            and draft.get("noRawMaterial") is True
        )
    except (models.ValidationError, ValueError, TypeError):
        return False


def _research_decisions(value: models.ResearchMemoryUse | dict[str, Any] | None) -> Any:
    if value is None:
        return None
    use = (
        value
        if isinstance(value, models.ResearchMemoryUse)
        else models.ResearchMemoryUse.model_validate(value)
    )
    result = use.model_dump(mode="json", by_alias=True)
    # Only narrative implementation may evolve after Judge; source authority and each decision
    # stay fixed, including resolved-premise evidence and caveats.
    for decision in result["insightDecisions"]:
        decision.pop("summary", None)
        decision.pop("application", None)
    for decision in result["premiseDecisions"]:
        decision.pop("application", None)
    # These are sets of source/decision identities; presentation order is not a revision.
    for key, values in result.items():
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict):
                    for nested_key, refs in value.items():
                        if isinstance(refs, list):
                            value[nested_key] = sorted(refs)
            result[key] = sorted(
                values, key=lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False)
            )
    return result


def research_decision_hash(
    use: models.ResearchMemoryUse | dict[str, Any] | None,
    plan: models.ResearchExecutionPlan | dict[str, Any] | None,
) -> str:
    """One identity for Draft deduplication, bundle rebuilding and final candidate binding.

    Keep source authority, receipt refs, decisions, premise resolutions/caveats and execution
    structure. The narrative fields already permitted by final review do not create revisions.
    """

    return _hash(
        {"researchMemoryUse": _research_decisions(use), "planStructure": _plan_structure(plan)}
    )


def _plan_structure(value: models.ResearchExecutionPlan | dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    plan = (
        value.model_dump(mode="json", by_alias=True)
        if isinstance(value, models.ResearchExecutionPlan)
        else value
    )
    return research_execution.stable_plan_structure_hash(plan)


def _binding(marker: dict[str, Any]) -> dict[str, Any]:
    return run_store.draft_mechanism_binding(marker)


def _current_markers_match(bound_run: run_store.BoundRun, payload: dict[str, Any]) -> bool:
    try:
        return all(
            json.loads((bound_run.run_dir / filename).read_text(encoding="utf-8"))
            == payload.get(key)
            for filename, key in (
                ("draft-validation.json", "draftMarker"),
                ("mechanism-blueprint-validation.json", "blueprintMarker"),
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def _draft_key(bound_run: run_store.BoundRun) -> tuple[str, str]:
    return str(bound_run.run_dir.resolve()), bound_run.run_id


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _evict_locked() -> None:
    cutoff = datetime.now(timezone.utc) - _DRAFT_TTL
    for key in [key for key, (created_at, _) in _DRAFTS.items() if created_at < cutoff]:
        _DRAFTS.pop(key, None)
