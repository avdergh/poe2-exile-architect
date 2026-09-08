"""Recoverable state service for the external-agent Phase 7 Desktop workflow."""

from __future__ import annotations

import json
import threading
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import ValidationError

from server import paths
from server.knowledge import research_identity, research_memory
from server.generation import artifacts as generation_artifacts
from server.generation import progression_provenance

from . import case_store, comparison, memory as learning_memory, models
from .file_lock import interprocess_file_lock


PhaseName = Literal["profile", "create", "compare", "learn", "rereview"]
_PHASES = {"profile", "create", "compare", "learn", "rereview"}
_LOCK = threading.RLock()


@contextmanager
def _locked_campaign_state():
    """Protect revision read/check/write across independent Desktop MCP processes."""

    with _LOCK:
        with interprocess_file_lock(campaigns_dir() / ".state.lock"):
            yield


def campaigns_dir() -> Path:
    return (paths.comparative_learning_dir() / "campaigns").resolve()


def start_campaign(*, operation_id: str, case_limit: int = 10) -> dict[str, Any]:
    if not _valid_operation_id(operation_id):
        return _rejected("invalid_operation_id")
    if case_limit != 10:
        return _rejected("phase7_pilot_requires_ten_cases")
    with _locked_campaign_state():
        existing = _find_campaign_by_start_operation(operation_id)
        if existing is not None:
            return {
                "status": "idempotent",
                "campaignId": existing["campaignId"],
                "revision": existing["revision"],
                "nextAction": "intake_case",
            }
        now = models.utc_now()
        campaign_id = str(uuid4())
        campaign = {
            "schemaVersion": 1,
            "campaignId": campaign_id,
            "status": "active",
            "caseLimit": 10,
            "rollingWindow": 3,
            "revision": 0,
            "activeCaseId": None,
            "cases": [],
            "operations": [],
            "startOperationId": operation_id,
            "createdAt": now,
            "updatedAt": now,
            "pause": None,
        }
        response = {
            "status": "started",
            "campaignId": campaign_id,
            "revision": 0,
            "caseLimit": 10,
            "strictlySerial": True,
            "rollingWindow": 3,
            "nextAction": "intake_case",
        }
        if not _write_campaign(campaign):
            return _rejected("campaign_write_failed")
        return response


def intake_case(
    *,
    campaign_id: str,
    expected_revision: int,
    operation_id: str,
    source: str,
    source_mode: str,
    source_ref: str = "",
) -> dict[str, Any]:
    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        if campaign["status"] != "active":
            return _rejected("campaign_not_active")
        if campaign.get("activeCaseId"):
            return _rejected("strict_serial_case_active", caseId=campaign["activeCaseId"])
        if len(campaign["cases"]) >= campaign["caseLimit"]:
            return _rejected("campaign_case_limit_reached")
        existing_source_hashes = {
            str(item.get("source", {}).get("sourceHash") or "")
            for item in campaign["cases"]
            if isinstance(item, dict) and isinstance(item.get("source"), dict)
        }
        intake = case_store.intake_reference_source(
            source=source,
            source_mode=source_mode,  # type: ignore[arg-type]
            source_ref=source_ref,
            reject_source_hashes=existing_source_hashes,
        )
        if intake.get("status") != "intaked":
            return intake
        safe = intake["case"]
        now = models.utc_now()
        case = {
            "caseId": safe["caseId"],
            "ordinal": len(campaign["cases"]) + 1,
            "phase": "profile_pending",
            "source": {
                "sourceMode": safe["sourceMode"],
                "sourceType": safe["sourceType"],
                "safeSourceRef": safe["safeSourceRef"],
                "sourceHash": safe["sourceHash"],
                "discoveredLevel": safe["discoveredLevel"],
            },
            "bindings": {"profileComparator": None, "create": None},
            "activeClaim": None,
            "familyTarget": None,
            "blindCreatePacket": None,
            "referenceEvidence": None,
            "generatedEvidence": None,
            "artifactId": None,
            "memoryQueryReceipt": None,
            "learningMemoryUse": None,
            "comparison": None,
            "comparisonRef": None,
            "metrics": {},
            "learningOutcome": None,
            "rereview": None,
            "createConsumed": False,
            "terminalFailure": False,
            "failedPhase": None,
            "failureCode": None,
            "retryCounts": {},
            "phaseDurationsSeconds": {},
            "startedAt": now,
            "completedAt": None,
        }
        campaign["cases"].append(case)
        campaign["activeCaseId"] = case["caseId"]
        response = {
            "status": "case_intaked",
            "campaignId": campaign_id,
            "caseId": case["caseId"],
            "ordinal": case["ordinal"],
            "phase": case["phase"],
            "source": case["source"],
            "containsRawMaterial": False,
        }
        return _commit(campaign, operation_id, response)


def discard_duplicate_pending_case(
    *,
    campaign_id: str,
    case_id: str,
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    """Repair a legacy duplicate intake before Profile without deleting quarantine evidence."""

    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        if campaign["status"] != "active":
            return _rejected("campaign_not_active")
        case = _find_case(campaign, case_id)
        if case is None or campaign.get("activeCaseId") != case_id:
            return _rejected("active_learning_case_required")
        if (
            case.get("phase") != "profile_pending"
            or case.get("activeClaim") is not None
            or any((case.get("bindings") or {}).values())
            or case.get("familyTarget") is not None
            or case.get("artifactId") is not None
            or case.get("comparison") is not None
            or case.get("createConsumed") is not False
        ):
            return _rejected("unstarted_profile_case_required")
        duplicate_hash = str((case.get("source") or {}).get("sourceHash") or "")
        earlier = [item for item in campaign["cases"] if item is not case]
        if not duplicate_hash or not any(
            str((item.get("source") or {}).get("sourceHash") or "") == duplicate_hash
            for item in earlier
        ):
            return _rejected("duplicate_reference_source_required")

        campaign["cases"] = earlier
        campaign["activeCaseId"] = None
        campaign.setdefault("discardedIntakes", []).append(
            {
                "caseId": case_id,
                "ordinal": case.get("ordinal"),
                "source": case.get("source"),
                "reason": "duplicate_reference_source",
                "discardedAt": models.utc_now(),
            }
        )
        return _commit(
            campaign,
            operation_id,
            {
                "status": "duplicate_intake_discarded",
                "caseId": case_id,
                "nextAction": "intake_case",
                "containsRawMaterial": False,
            },
        )


def claim_phase(
    *,
    campaign_id: str,
    case_id: str,
    phase: str,
    task_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        if campaign["status"] != "active":
            return _rejected("campaign_not_active")
        case = _find_case(campaign, case_id)
        if case is None:
            return _rejected("learning_case_not_found")
        if phase not in _PHASES or case["phase"] != f"{phase}_pending":
            return _rejected("learning_phase_mismatch", currentPhase=case["phase"])
        if not _valid_binding_value(task_id) or not _valid_binding_value(thread_id):
            return _rejected("invalid_task_binding")
        binding_error = _bind_task(case, phase=phase, task_id=task_id, thread_id=thread_id)
        if binding_error:
            return _rejected(binding_error)
        claim_id = f"claim:{uuid4()}"
        claimed_at = models.utc_now()
        case["activeClaim"] = {
            "claimId": claim_id,
            "phase": phase,
            "taskId": task_id,
            "threadId": thread_id,
            "claimedAt": claimed_at,
        }
        case["phase"] = f"{phase}_running"
        response = {
            "status": "claimed",
            "campaignId": campaign_id,
            "caseId": case_id,
            "phase": phase,
            "claimId": claim_id,
            "taskBinding": {"taskId": task_id, "threadId": thread_id},
            "phasePacket": _phase_packet(case, phase),
            "containsRawMaterial": False,
        }
        return _commit(campaign, operation_id, response)


def load_reference_into_engine(
    active_engine: Any,
    *,
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
) -> dict[str, Any]:
    campaign = _read_campaign(campaign_id)
    if campaign is None:
        return _rejected("learning_campaign_not_found")
    case = _find_case(campaign, case_id)
    error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase="profile")
    if error:
        error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase="compare")
        if error:
            return _rejected(error)
    xml = case_store.read_reference_xml(case_id)
    if xml is None:
        return _rejected("quarantine_case_unavailable")
    try:
        loaded = active_engine.load_build_xml(xml, name=f"phase7-reference-{case_id}")
    except Exception:  # noqa: BLE001 - do not expose engine internals.
        return _rejected("reference_load_failed")
    safe_build = {}
    if isinstance(loaded, dict):
        safe_build = {
            key: loaded[key]
            for key in ("mainSkill", "treeVersion")
            if key in loaded and isinstance(loaded[key], (str, int, float, bool))
        }
        if "mainSkill" in safe_build:
            # Engine readback is authoritative, unlike the research queue's
            # programmatic_snapshot_non_authoritative first-nameSpec label.
            safe_build["mainSkillAuthority"] = "engine_readback_authoritative"
    return {
        "status": "loaded",
        "caseId": case_id,
        "activeReference": safe_build,
        "containsRawMaterial": False,
    }


def submit_profile(
    *,
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    identity_records: list[dict[str, Any]],
    target_level: int,
    version_context: dict[str, Any],
    reference_evidence: dict[str, Any],
) -> dict[str, Any]:
    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        case = _find_case(campaign, case_id)
        error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase="profile")
        if error:
            return _rejected(error)
        assert case is not None
        family = research_identity.infer_build_family(identity_records, allow_multi_primary=False)
        if family is None:
            return _fail_case(campaign, case, operation_id, "ambiguous_build_family")
        if target_level != case["source"]["discoveredLevel"]:
            return _fail_case(campaign, case, operation_id, "reference_level_mismatch")
        try:
            version = models.LearningVersionContext.model_validate(version_context)
            evidence = models.SafeBuildEvidence.model_validate(reference_evidence)
        except ValidationError as exc:
            return _validation_rejected("invalid_reference_profile", exc)
        if evidence.side != "reference":
            return _rejected("reference_evidence_side_mismatch")
        try:
            target = models.FamilyTarget(
                build_family_key=family.key,
                ascendancy_key=family.ascendancy_key,
                primary_skill_key=family.primary_skill_key,
                secondary_skill_keys=list(family.secondary_skill_keys),
                target_level=target_level,
                version_context=version,
                safe_evidence_refs=evidence.safe_evidence_refs,
            )
            packet = models.BlindCreatePacket(
                campaign_id=campaign_id,
                case_id=case_id,
                family_target=target,
            )
        except (ValidationError, ValueError) as exc:
            return _rejected("invalid_family_target", detail=str(exc)[:240])
        case["familyTarget"] = target.model_dump(mode="json", by_alias=True)
        case["blindCreatePacket"] = packet.model_dump(mode="json", by_alias=True)
        case["referenceEvidence"] = evidence.model_dump(mode="json", by_alias=True)
        _finish_phase(case, "profile", next_phase="create_pending")
        response = {
            "status": "profile_accepted",
            "caseId": case_id,
            "familyTarget": case["familyTarget"],
            "nextPhase": "create",
            "containsRawMaterial": False,
        }
        return _commit(campaign, operation_id, response)


def get_blind_create_packet(
    *, campaign_id: str, case_id: str, claim_id: str, thread_id: str
) -> dict[str, Any]:
    campaign = _read_campaign(campaign_id)
    if campaign is None:
        return _rejected("learning_campaign_not_found")
    case = _find_case(campaign, case_id)
    error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase="create")
    if error:
        return _rejected(error)
    assert case is not None
    packet = case.get("blindCreatePacket")
    if not isinstance(packet, dict):
        return _rejected("blind_create_packet_unavailable")
    try:
        valid = models.BlindCreatePacket.model_validate(packet)
    except ValidationError:
        return _rejected("blind_create_packet_corrupt")
    return {
        "status": "ok",
        "blindCreatePacket": valid.model_dump(mode="json", by_alias=True),
        "containsReferenceDetails": False,
        "containsRawMaterial": False,
    }


def validate_blind_research_claim(*, campaign_id: str, claim_id: str) -> dict[str, Any]:
    """Resolve a Research query binding from server-owned Blind Create state.

    The generic Research query must not trust a caller-supplied scope flag.  A matching campaign
    and active Create claim are the authority that permits the server to force ``global_seed``.
    """

    campaign = _read_campaign(campaign_id)
    if campaign is None or campaign.get("status") != "active":
        return _rejected("blind_research_campaign_unavailable")
    matches = [
        case
        for case in campaign.get("cases") or []
        if isinstance(case, dict)
        and case.get("phase") == "create_running"
        and isinstance(case.get("activeClaim"), dict)
        and case["activeClaim"].get("claimId") == claim_id
        and isinstance(case.get("blindCreatePacket"), dict)
        and case["blindCreatePacket"].get("referenceBlind") is True
    ]
    if len(matches) != 1:
        return _rejected("blind_research_claim_binding_mismatch")
    return {
        "status": "ok",
        "campaignId": campaign_id,
        "caseId": str(matches[0].get("caseId") or ""),
        "claimId": claim_id,
        "knowledgeScope": "global_seed",
        "containsRawMaterial": False,
    }


def query_memory_for_create(
    *,
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    dimensions: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Query Memory inside a Create claim and persist only a safe query receipt."""

    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        case = _find_case(campaign, case_id)
        error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase="create")
        if error:
            return _rejected(error)
        assert case is not None
        target = case.get("familyTarget")
        if not isinstance(target, dict):
            return _rejected("family_target_unavailable")
        target_level = target.get("targetLevel")
        if isinstance(target_level, bool) or not isinstance(target_level, int):
            return _rejected("family_target_corrupt")
        result = learning_memory.query_memory(
            family_key=str(target.get("buildFamilyKey") or ""),
            target_level=target_level,
            dimensions=dimensions,
            limit=limit,
            version_context=target.get("versionContext"),
        )
        if result.get("status") != "ok":
            return result
        recalled_ids = list(result.get("recalledLessonIds") or [])
        case["memoryQueryReceipt"] = {
            "queryRef": result["queryRef"],
            "recalledLessonIds": recalled_ids,
            "queriedAt": models.utc_now(),
        }
        response = {
            **result,
            "campaignId": campaign_id,
            "caseId": case_id,
            "auditReceiptRecorded": True,
        }
        return _commit(campaign, operation_id, response)


def submit_create_result(
    *,
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    identity_records: list[dict[str, Any]],
    target_level: int,
    artifact_id: str,
    generated_evidence: dict[str, Any],
    learning_memory_use: dict[str, Any],
    research_memory_use: dict[str, Any],
) -> dict[str, Any]:
    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        case = _find_case(campaign, case_id)
        error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase="create")
        if error:
            return _rejected(error)
        assert case is not None
        if case.get("createConsumed"):
            return _rejected("create_already_consumed")
        if not isinstance(artifact_id, str) or not artifact_id.startswith("final-build:"):
            return _rejected("invalid_final_artifact_ref")
        artifact_metadata = _artifact_metadata(artifact_id)
        if artifact_metadata is None:
            return _rejected("final_artifact_not_found_or_untrusted")
        family = research_identity.infer_build_family(identity_records, allow_multi_primary=False)
        if family is None:
            case["createConsumed"] = True
            case["metrics"].update(
                {"createAccepted": False, "familyMatch": False, "levelMatch": None}
            )
            return _fail_case(
                campaign,
                case,
                operation_id,
                "generated_family_ambiguous",
                terminal=True,
            )
        target = case.get("familyTarget") or {}
        family_matches = (
            family.key == target.get("buildFamilyKey")
            and family.ascendancy_key == target.get("ascendancyKey")
            and family.primary_skill_key == target.get("primarySkillKey")
            and list(family.secondary_skill_keys) == target.get("secondarySkillKeys")
        )
        level_matches = target_level == target.get("targetLevel") and artifact_metadata[
            "level"
        ] == target.get("targetLevel")
        if not family_matches or not level_matches:
            case["createConsumed"] = True
            case["metrics"].update(
                {
                    "createAccepted": False,
                    "familyMatch": family_matches,
                    "levelMatch": level_matches,
                }
            )
            return _fail_case(
                campaign,
                case,
                operation_id,
                "generated_family_or_level_mismatch",
                terminal=True,
                familyMatch=family_matches,
                levelMatch=level_matches,
            )
        try:
            evidence = models.SafeBuildEvidence.model_validate(generated_evidence)
            memory_use = models.LearningMemoryUse.model_validate(learning_memory_use)
        except ValidationError as exc:
            return _validation_rejected("invalid_create_result", exc)
        if evidence.side != "generated":
            return _rejected("generated_evidence_side_mismatch")
        receipt = case.get("memoryQueryReceipt")
        if not isinstance(receipt, dict):
            return _rejected("learning_memory_query_receipt_required")
        if memory_use.query_ref != receipt.get("queryRef") or set(
            memory_use.recalled_lesson_ids
        ) != set(receipt.get("recalledLessonIds") or []):
            return _rejected("learning_memory_use_receipt_mismatch")
        memory_refs = learning_memory.validate_references(
            lesson_ids=memory_use.recalled_lesson_ids,
        )
        if memory_refs.get("status") != "ok":
            return memory_refs
        claim = case.get("activeClaim") or {}
        research_error, research_summary, research_caveats = (
            progression_provenance.validate_research_use_receipts(
                research_memory_use=research_memory_use,
                receipt_reader=research_memory.ResearchMemoryService().read_query_receipt,
                not_before=str(claim.get("claimedAt") or "") or None,
                expected_blind_run_ref=campaign_id,
                expected_blind_claim_ref=claim_id,
            )
        )
        if research_error or research_summary is None:
            return _rejected(
                research_error or "progression_research_use_invalid",
                caveats=research_caveats,
            )
        case["createConsumed"] = True
        case["artifactId"] = artifact_id
        case["artifactSourceHash"] = artifact_metadata["sourceHash"]
        case["generatedEvidence"] = evidence.model_dump(mode="json", by_alias=True)
        case["learningMemoryUse"] = memory_use.model_dump(mode="json", by_alias=True)
        case["researchMemoryUse"] = research_summary
        case["metrics"].update(
            {
                "createAccepted": True,
                "familyMatch": True,
                "levelMatch": True,
                "memoryRecalled": len(memory_use.recalled_lesson_ids),
                "memoryAdopted": sum(item.decision == "adopted" for item in memory_use.decisions),
                "memoryCaveated": sum(item.decision == "caveated" for item in memory_use.decisions),
                "memoryRejected": sum(item.decision == "rejected" for item in memory_use.decisions),
                "memoryHarmful": sum(item.harmful_or_incorrect for item in memory_use.decisions),
            }
        )
        _finish_phase(case, "create", next_phase="compare_pending")
        response = {
            "status": "create_accepted",
            "caseId": case_id,
            "artifactId": artifact_id,
            "familyMatch": True,
            "levelMatch": True,
            "nextPhase": "compare",
            "containsRawMaterial": False,
        }
        return _commit(campaign, operation_id, response)


def submit_comparison(
    *,
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        case = _find_case(campaign, case_id)
        error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase="compare")
        if error:
            return _rejected(error)
        assert case is not None
        if not case.get("referenceEvidence") or not case.get("generatedEvidence"):
            return _rejected("comparison_evidence_unavailable")
        validated = comparison.validate_report(
            report, expected_case_id=case_id,
            reference_evidence=case["referenceEvidence"],
            generated_evidence=case["generatedEvidence"],
        )
        if validated.get("status") != "accepted":
            return validated
        report_value = validated["report"]
        if not report_value["familyMatch"] or not report_value["levelMatch"]:
            return _rejected("comparison_target_match_must_be_true")
        case["comparison"] = report_value
        case["comparisonRef"] = validated["reportRef"]
        case["metrics"].update(validated["metrics"])
        case["metrics"]["comparisonCompleted"] = True
        _finish_phase(case, "compare", next_phase="learn_pending")
        response = {
            "status": "comparison_accepted",
            "caseId": case_id,
            "comparisonRef": case["comparisonRef"],
            "metrics": validated["metrics"],
            "judgeAdvisoryOnly": True,
            "winnerSource": "external_comparator",
            "nextPhase": "learn",
            "containsRawMaterial": False,
        }
        return _commit(campaign, operation_id, response)


def complete_learning(
    *,
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    mutations: list[str],
    research_refs: list[str] | None = None,
    memory_lesson_ids: list[str] | None = None,
    correction_ids: list[str] | None = None,
    code_change_refs: list[str] | None = None,
    backlog: list[str] | None = None,
) -> dict[str, Any]:
    allowed_mutations = {"none", "research", "memory", "code"}
    if not mutations or not set(mutations).issubset(allowed_mutations):
        return _rejected("invalid_learning_mutation")
    if "none" in mutations and len(set(mutations)) > 1:
        return _rejected("none_learning_mutation_must_be_exclusive")
    outcome = {
        "mutations": sorted(set(mutations)),
        "researchRefs": list(research_refs or []),
        "memoryLessonIds": list(memory_lesson_ids or []),
        "correctionIds": list(correction_ids or []),
        "codeChangeRefs": list(code_change_refs or []),
        "backlog": list(backlog or []),
    }
    try:
        models.ensure_safe_durable_payload(outcome)
    except ValueError as exc:
        return _rejected("unsafe_learning_outcome", detail=str(exc)[:240])
    if "research" in mutations and not outcome["researchRefs"]:
        return _rejected("research_mutation_requires_refs")
    if "memory" in mutations and not (outcome["memoryLessonIds"] or outcome["correctionIds"]):
        return _rejected("memory_mutation_requires_refs")
    if "code" in mutations and not outcome["codeChangeRefs"]:
        return _rejected("code_mutation_requires_refs")
    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        case = _find_case(campaign, case_id)
        error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase="learn")
        if error:
            return _rejected(error)
        assert case is not None
        if "memory" in mutations:
            memory_refs = learning_memory.validate_references(
                lesson_ids=outcome["memoryLessonIds"],
                correction_ids=outcome["correctionIds"],
            )
            if memory_refs.get("status") != "ok":
                return memory_refs
        case["learningOutcome"] = outcome
        case["metrics"].update(
            {
                "memoryWritten": len(outcome["memoryLessonIds"]),
                "memoryCorrected": len(outcome["correctionIds"]),
                "researchFeedbackCount": len(outcome["researchRefs"]),
            }
        )
        _record_phase_duration(case, "learn")
        case["activeClaim"] = None
        if outcome["backlog"]:
            case["phase"] = "paused"
            campaign["status"] = "paused"
            campaign["pause"] = {
                "caseId": case_id,
                "resumePhase": "learn_pending",
                "reason": "human_decision_required",
                "backlog": outcome["backlog"],
            }
            next_phase = "paused"
        elif set(outcome["mutations"]) - {"none"}:
            case["phase"] = "rereview_pending"
            next_phase = "rereview"
        else:
            _complete_case(campaign, case)
            next_phase = "completed"
        response = {
            "status": "learning_recorded",
            "caseId": case_id,
            "nextPhase": next_phase,
            "conditionalRereviewRequired": next_phase == "rereview",
            "containsRawMaterial": False,
        }
        return _commit(campaign, operation_id, response)


def submit_rereview(
    *,
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    accepted: bool,
    summary: str,
    safe_evidence_refs: list[str],
) -> dict[str, Any]:
    payload = {"accepted": accepted, "summary": summary, "safeEvidenceRefs": safe_evidence_refs}
    try:
        models.ensure_safe_durable_payload(payload)
    except ValueError as exc:
        return _rejected("unsafe_rereview", detail=str(exc)[:240])
    if not isinstance(summary, str) or not 1 <= len(summary) <= 800 or not safe_evidence_refs:
        return _rejected("invalid_rereview")
    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        case = _find_case(campaign, case_id)
        error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase="rereview")
        if error:
            return _rejected(error)
        assert case is not None
        case["rereview"] = payload
        _record_phase_duration(case, "rereview")
        case["activeClaim"] = None
        if accepted:
            _complete_case(campaign, case)
            response_status = "case_completed"
        else:
            case["phase"] = "paused"
            campaign["status"] = "paused"
            campaign["pause"] = {
                "caseId": case_id,
                "resumePhase": "rereview_pending",
                "reason": "conditional_rereview_not_accepted",
                "backlog": [],
            }
            response_status = "rereview_paused"
        response = {
            "status": response_status,
            "caseId": case_id,
            "campaignStatus": campaign["status"],
            "nextAction": "intake_case" if case["phase"] == "completed" else "human_decision",
        }
        return _commit(campaign, operation_id, response)


def propose_memory_lesson(
    *,
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Bind a Memory proposal to the active Comparator Learn claim and comparison."""

    with _locked_campaign_state():
        campaign = _read_campaign(campaign_id)
        if campaign is None:
            return _rejected("learning_campaign_not_found")
        case = _find_case(campaign, case_id)
        error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase="learn")
        if error:
            return _rejected(error)
        assert case is not None
        if proposal.get("reviewedCaseId") != case_id:
            return _rejected("learning_lesson_case_mismatch")
        comparison_ref = case.get("comparisonRef")
        refs = proposal.get("comparisonRefs")
        if not isinstance(refs, list) or comparison_ref not in refs:
            return _rejected("learning_lesson_comparison_ref_required")
        target = case.get("familyTarget") or {}
        if proposal.get("versionContext") != target.get("versionContext"):
            return _rejected("learning_lesson_version_context_mismatch")
        if proposal.get("scope") == "family" and proposal.get("familyKey") != target.get(
            "buildFamilyKey"
        ):
            return _rejected("learning_lesson_family_scope_mismatch")
        if proposal.get("scope") == "level_band":
            level = target.get("targetLevel")
            lower = proposal.get("levelMin")
            upper = proposal.get("levelMax")
            if (
                isinstance(level, bool)
                or not isinstance(level, int)
                or isinstance(lower, bool)
                or not isinstance(lower, int)
                or isinstance(upper, bool)
                or not isinstance(upper, int)
                or not lower <= level <= upper
            ):
                return _rejected("learning_lesson_level_scope_mismatch")
        return learning_memory.propose_lesson(proposal)


def correct_memory_lesson(
    *,
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    correction: dict[str, Any],
) -> dict[str, Any]:
    """Bind a correction event to the active Comparator Learn claim and comparison."""

    with _locked_campaign_state():
        campaign = _read_campaign(campaign_id)
        if campaign is None:
            return _rejected("learning_campaign_not_found")
        case = _find_case(campaign, case_id)
        error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase="learn")
        if error:
            return _rejected(error)
        assert case is not None
        if correction.get("triggerCaseId") != case_id:
            return _rejected("learning_correction_case_mismatch")
        comparison_ref = case.get("comparisonRef")
        refs = correction.get("safeEvidenceRefs")
        if not isinstance(refs, list) or comparison_ref not in refs:
            return _rejected("learning_correction_comparison_ref_required")
        return learning_memory.append_correction(correction)


def fail_phase(
    *,
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    error_code: str,
) -> dict[str, Any]:
    if not re_safe_code(error_code):
        return _rejected("invalid_failure_code")
    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        case = _find_case(campaign, case_id)
        claim = case.get("activeClaim") if case else None
        if not isinstance(claim, dict):
            return _rejected("active_learning_claim_required")
        phase = claim.get("phase")
        error = _claim_error(case, claim_id=claim_id, thread_id=thread_id, phase=str(phase))
        if error:
            return _rejected(error)
        assert case is not None
        _record_phase_duration(case, str(phase))
        case["phase"] = "failed"
        case["failedPhase"] = phase
        case["failureCode"] = error_code
        case["activeClaim"] = None
        response = {
            "status": "phase_failed",
            "caseId": case_id,
            "failedPhase": phase,
            "retryAllowed": not (phase == "create" and case.get("createConsumed")),
        }
        return _commit(campaign, operation_id, response)


def retry_failed_phase(
    *,
    campaign_id: str,
    case_id: str,
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        case = _find_case(campaign, case_id)
        if (
            case is None
            or case["phase"] != "failed"
            or case.get("terminalFailure")
            or case.get("failedPhase") not in _PHASES
        ):
            return _rejected("failed_learning_phase_required")
        phase = case["failedPhase"]
        if phase == "create" and case.get("createConsumed"):
            return _rejected("create_result_cannot_be_retried")
        count = int(case["retryCounts"].get(phase, 0)) + 1
        case["retryCounts"][phase] = count
        case["phase"] = f"{phase}_pending"
        case["failureCode"] = None
        response = {
            "status": "retry_scheduled",
            "caseId": case_id,
            "phase": phase,
            "retryCount": count,
        }
        return _commit(campaign, operation_id, response)


def pause_campaign(
    *,
    campaign_id: str,
    expected_revision: int,
    operation_id: str,
    reason: str,
) -> dict[str, Any]:
    if not isinstance(reason, str) or not 1 <= len(reason) <= 400:
        return _rejected("invalid_pause_reason")
    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        if campaign["status"] != "active":
            return _rejected("campaign_not_active")
        active = _find_case(campaign, campaign.get("activeCaseId"))
        resume_phase = active.get("phase") if active else None
        if active and str(resume_phase).endswith("_running"):
            phase = str(resume_phase).removesuffix("_running")
            _record_phase_duration(active, phase)
            active["phase"] = f"{phase}_pending"
            active["activeClaim"] = None
            resume_phase = active["phase"]
        campaign["status"] = "paused"
        campaign["pause"] = {
            "caseId": active.get("caseId") if active else None,
            "resumePhase": resume_phase,
            "reason": reason,
            "backlog": [],
        }
        return _commit(campaign, operation_id, {"status": "paused", "reason": reason})


def resume_campaign(
    *,
    campaign_id: str,
    expected_revision: int,
    operation_id: str,
    human_decision: str = "",
) -> dict[str, Any]:
    if human_decision:
        try:
            models.ensure_safe_durable_payload({"humanDecision": human_decision})
        except ValueError as exc:
            return _rejected("unsafe_human_decision", detail=str(exc)[:240])
    with _locked_campaign_state():
        loaded = _load_for_mutation(campaign_id, expected_revision, operation_id)
        if isinstance(loaded, dict) and loaded.get("status") in {"rejected", "idempotent"}:
            return loaded
        campaign = loaded
        if campaign["status"] != "paused":
            return _rejected("campaign_not_paused")
        pause = campaign.get("pause") or {}
        case = _find_case(campaign, pause.get("caseId"))
        if case is not None and case.get("phase") == "paused":
            case["phase"] = pause.get("resumePhase") or "learn_pending"
            case.setdefault("humanDecisions", []).append(
                {"decision": human_decision or "resume", "createdAt": models.utc_now()}
            )
        campaign["status"] = "active"
        campaign["pause"] = None
        return _commit(
            campaign,
            operation_id,
            {
                "status": "resumed",
                "caseId": case.get("caseId") if case else None,
                "phase": case.get("phase") if case else None,
            },
        )


def campaign_status(*, campaign_id: str) -> dict[str, Any]:
    campaign = _read_campaign(campaign_id)
    if campaign is None:
        return _rejected("learning_campaign_not_found")
    cases = [_safe_case_status(item) for item in campaign["cases"]]
    completed_metrics = [
        comparison.stored_case_metrics(item)
        for item in campaign["cases"]
        if item.get("phase") == "completed" or item.get("terminalFailure") is True
    ]
    return {
        "status": "ok",
        "campaignId": campaign["campaignId"],
        "campaignStatus": campaign["status"],
        "revision": campaign["revision"],
        "caseLimit": campaign["caseLimit"],
        "activeCaseId": campaign.get("activeCaseId"),
        "cases": cases,
        "pause": campaign.get("pause"),
        "trend": comparison.campaign_trend(completed_metrics),
        "containsRawMaterial": False,
    }


def _phase_packet(case: dict[str, Any], phase: str) -> dict[str, Any]:
    if phase == "profile":
        return {
            "caseId": case["caseId"],
            "source": case["source"],
            "instruction": "load_reference_then_profile_family_and_safe_evidence",
        }
    if phase == "create":
        return {
            "caseId": case["caseId"],
            "blindCreatePacketAvailable": True,
            "instruction": "call_get_learning_create_packet_in_create_task",
        }
    if phase == "compare":
        return {
            "caseId": case["caseId"],
            "familyTarget": case["familyTarget"],
            "referenceEvidence": case["referenceEvidence"],
            "generatedEvidence": case["generatedEvidence"],
            "artifactId": case["artifactId"],
            "judgeAdvisoryOnly": True,
        }
    if phase == "learn":
        return {
            "caseId": case["caseId"],
            "comparisonRef": case["comparisonRef"],
            "gaps": (case.get("comparison") or {}).get("gaps", []),
            "instruction": "route_db_fit_knowledge_to_research_and_only_cross_dimensional_lessons_to_learning_memory",
        }
    return {
        "caseId": case["caseId"],
        "comparisonRef": case["comparisonRef"],
        "learningOutcome": case["learningOutcome"],
        "instruction": "review_mutations_without_regenerating_this_case",
    }


def _artifact_metadata(artifact_id: str) -> dict[str, Any] | None:
    """Verify the local final artifact and return only level/hash binding metadata."""

    verified = generation_artifacts.read_final_build_artifact_for_export(artifact_id)
    if verified is None:
        return None
    manifest, xml = verified
    try:
        root = ET.fromstring(xml)
        build = root.find("Build")
        level = int(build.attrib.get("level") or "0") if build is not None else 0
    except (ET.ParseError, TypeError, ValueError):
        return None
    if not 1 <= level <= 100:
        return None
    return {"level": level, "sourceHash": manifest.source_hash}


def _bind_task(case: dict[str, Any], *, phase: str, task_id: str, thread_id: str) -> str | None:
    binding = {"taskId": task_id, "threadId": thread_id}
    reference = case["bindings"].get("profileComparator")
    create = case["bindings"].get("create")
    if phase == "profile":
        if reference is not None and reference != binding:
            return "profile_comparator_task_binding_mismatch"
        case["bindings"]["profileComparator"] = binding
        return None
    if phase == "create":
        if not isinstance(reference, dict):
            return "profile_comparator_task_required"
        if reference["taskId"] == task_id or reference["threadId"] == thread_id:
            return "create_task_must_be_independent"
        if create is not None and create != binding:
            return "create_task_binding_mismatch"
        case["bindings"]["create"] = binding
        return None
    if not isinstance(reference, dict):
        return "profile_comparator_task_required"
    if reference != binding:
        return "comparator_task_binding_mismatch"
    return None


def _finish_phase(case: dict[str, Any], phase: str, *, next_phase: str) -> None:
    _record_phase_duration(case, phase)
    case["activeClaim"] = None
    case["phase"] = next_phase


def _record_phase_duration(case: dict[str, Any], phase: str) -> None:
    claim = case.get("activeClaim")
    if not isinstance(claim, dict) or claim.get("phase") != phase:
        return
    try:
        start = datetime.fromisoformat(claim["claimedAt"])
        duration = max(0.0, (datetime.now(timezone.utc) - start).total_seconds())
    except (TypeError, ValueError):
        duration = 0.0
    case["phaseDurationsSeconds"][phase] = round(
        float(case["phaseDurationsSeconds"].get(phase, 0.0)) + duration, 3
    )


def _complete_case(campaign: dict[str, Any], case: dict[str, Any]) -> None:
    case["phase"] = "completed"
    case["terminalFailure"] = False
    case["completedAt"] = models.utc_now()
    try:
        started = datetime.fromisoformat(case["startedAt"])
        completed = datetime.fromisoformat(case["completedAt"])
        case["metrics"]["caseDurationSeconds"] = round((completed - started).total_seconds(), 3)
    except (TypeError, ValueError):
        case["metrics"]["caseDurationSeconds"] = None
    case["metrics"]["phaseDurationsSeconds"] = dict(case["phaseDurationsSeconds"])
    campaign["activeCaseId"] = None
    if len(campaign["cases"]) >= campaign["caseLimit"]:
        campaign["status"] = "completed"


def _fail_case(
    campaign: dict[str, Any],
    case: dict[str, Any],
    operation_id: str,
    error_code: str,
    terminal: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    claim = case.get("activeClaim") or {}
    phase = claim.get("phase")
    if phase:
        _record_phase_duration(case, str(phase))
    case["phase"] = "failed"
    case["failedPhase"] = phase
    case["failureCode"] = error_code
    case["terminalFailure"] = terminal
    case["activeClaim"] = None
    if terminal:
        case["completedAt"] = models.utc_now()
        try:
            started = datetime.fromisoformat(case["startedAt"])
            completed = datetime.fromisoformat(case["completedAt"])
            case["metrics"]["caseDurationSeconds"] = round((completed - started).total_seconds(), 3)
        except (TypeError, ValueError):
            case["metrics"]["caseDurationSeconds"] = None
        case["metrics"]["phaseDurationsSeconds"] = dict(case["phaseDurationsSeconds"])
        case["metrics"]["comparisonCompleted"] = False
        campaign["activeCaseId"] = None
        if len(campaign["cases"]) >= campaign["caseLimit"]:
            campaign["status"] = "completed"
    response = {
        "status": "case_failed",
        "caseId": case["caseId"],
        "errorCode": error_code,
        "failedPhase": phase,
        "terminalFailure": terminal,
        "retryAllowed": not terminal,
        "nextAction": "intake_case" if terminal and campaign["status"] == "active" else None,
        "containsRawMaterial": False,
        **extra,
    }
    return _commit(campaign, operation_id, response)


def _claim_error(
    case: dict[str, Any] | None, *, claim_id: str, thread_id: str, phase: str
) -> str | None:
    if case is None:
        return "learning_case_not_found"
    if phase not in _PHASES or case.get("phase") != f"{phase}_running":
        return "learning_phase_mismatch"
    claim = case.get("activeClaim")
    if not isinstance(claim, dict):
        return "active_learning_claim_required"
    if claim.get("claimId") != claim_id or claim.get("threadId") != thread_id:
        return "learning_claim_binding_mismatch"
    return None


def _load_for_mutation(
    campaign_id: str, expected_revision: int, operation_id: str
) -> dict[str, Any]:
    if not _valid_operation_id(operation_id):
        return _rejected("invalid_operation_id")
    campaign = _read_campaign(campaign_id)
    if campaign is None:
        return _rejected("learning_campaign_not_found")
    for item in campaign.get("operations", []):
        if item.get("operationId") == operation_id:
            original = dict(item.get("response") or {})
            return {
                **original,
                "status": "idempotent",
                "originalStatus": original.get("status"),
            }
    if isinstance(expected_revision, bool) or expected_revision != campaign.get("revision"):
        return _rejected("campaign_revision_conflict", currentRevision=campaign.get("revision"))
    return campaign


def _commit(
    campaign: dict[str, Any], operation_id: str, response: dict[str, Any]
) -> dict[str, Any]:
    campaign["revision"] += 1
    campaign["updatedAt"] = models.utc_now()
    final_response = {**response, "revision": campaign["revision"]}
    campaign["operations"].append(
        {
            "operationId": operation_id,
            "response": final_response,
            "appliedAt": campaign["updatedAt"],
        }
    )
    campaign["operations"] = campaign["operations"][-200:]
    if not _write_campaign(campaign):
        return _rejected("campaign_write_failed")
    return final_response


def _safe_case_status(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "caseId": case["caseId"],
        "ordinal": case["ordinal"],
        "phase": case["phase"],
        "source": case["source"],
        "bindings": case["bindings"],
        "familyTarget": case["familyTarget"],
        "artifactId": case["artifactId"],
        "comparisonRef": case["comparisonRef"],
        "metrics": comparison.stored_case_metrics(case),
        "retryCounts": case["retryCounts"],
        "failureCode": case["failureCode"],
        "terminalFailure": case.get("terminalFailure", False),
        "startedAt": case["startedAt"],
        "completedAt": case["completedAt"],
    }


def _find_case(campaign: dict[str, Any], case_id: Any) -> dict[str, Any] | None:
    return next((item for item in campaign.get("cases", []) if item.get("caseId") == case_id), None)


def _campaign_path(campaign_id: str) -> Path | None:
    try:
        canonical = str(UUID(campaign_id))
    except (AttributeError, TypeError, ValueError):
        return None
    if canonical != campaign_id:
        return None
    root = campaigns_dir()
    path = (root / f"{canonical}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _read_campaign(campaign_id: str) -> dict[str, Any] | None:
    path = _campaign_path(campaign_id)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 1
        or payload.get("campaignId") != campaign_id
        or not isinstance(payload.get("revision"), int)
        or not isinstance(payload.get("cases"), list)
    ):
        return None
    try:
        models.ensure_safe_durable_payload(payload)
    except ValueError:
        return None
    return payload


def _write_campaign(campaign: dict[str, Any]) -> bool:
    path = _campaign_path(campaign["campaignId"])
    if path is None:
        return False
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        models.ensure_safe_durable_payload(campaign)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(campaign, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
    except (OSError, ValueError):
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def _find_campaign_by_start_operation(operation_id: str) -> dict[str, Any] | None:
    root = campaigns_dir()
    if not root.is_dir():
        return None
    for path in root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("startOperationId") == operation_id:
            return payload
    return None


def _validation_rejected(code: str, exc: ValidationError) -> dict[str, Any]:
    first: Any = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", ())) or "input"
    return _rejected(code, detail=f"{loc}: {first.get('msg', '')}"[:240])


def _valid_operation_id(value: str) -> bool:
    return isinstance(value, str) and 3 <= len(value) <= 120 and re_safe_code(value)


def _valid_binding_value(value: str) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 200 and "\n" not in value


def re_safe_code(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in "_.:-" for char in value)


def _rejected(error_code: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": "rejected",
        "errorCode": error_code,
        "containsRawMaterial": False,
        **extra,
    }
