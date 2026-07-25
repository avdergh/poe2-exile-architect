"""Recoverable local state service for Agent-led Phase 8 progression creation.

The service owns safe control state only. It does not create Desktop tasks, browse the web,
call a model, or construct a build. Every milestone is produced through an independently bound
Phase 5 run and verified FinalBuildArtifact.
"""

from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, ValidationError, model_validator

from server import paths
from server.knowledge import copy_safety
from server.learning.file_lock import interprocess_file_lock

from . import (
    artifacts,
    models,
    progression,
    progression_costs,
    progression_models,
    progression_research,
    run_store,
)


STATE_SCHEMA_VERSION = 1
_LOCK = threading.RLock()
_OPERATION_ID = re.compile(r"^[A-Za-z0-9_.:\-]{3,160}$")
_FAILURE_CODE = re.compile(r"^[a-z0-9_]{3,100}$")
_LIFECYCLE_TOKEN = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")
_LIFECYCLE_STAGES = {
    "campaign_early",
    "campaign_mid",
    "campaign_late",
    "maps_entry",
    "endgame_budget",
    "endgame_final",
}


class StageCompletionReport(models.StrictModel):
    purpose: str = Field(min_length=1, max_length=320)
    play_pattern: str = Field(min_length=1, max_length=500)
    changes_from_previous: list[progression.ProgressionChange] = Field(
        default_factory=list, max_length=24
    )
    acquisition_priorities: list[str] = Field(default_factory=list, max_length=12)
    caveats: list[str] = Field(default_factory=list, max_length=12)
    source_refs: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _safe(self) -> "StageCompletionReport":
        if any(not re.fullmatch(r"[A-Za-z0-9_.:/\-]{3,240}", ref) for ref in self.source_refs):
            raise ValueError("stage source refs must be safe references")
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("stage source refs must be unique")
        authored = {
            "purpose": self.purpose,
            "playPattern": self.play_pattern,
            "acquisitionPriorities": self.acquisition_priorities,
            "caveats": self.caveats,
        }
        if copy_safety.copyability_flags(authored) or copy_safety.contains_raw_url(authored):
            raise ValueError("copyable material is forbidden in stage completion text")
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


@contextmanager
def _locked_state():
    with _LOCK:
        with interprocess_file_lock(paths.build_progression_runs_dir() / ".state.lock"):
            yield


def start_build_progression(
    *,
    operation_id: str,
    base_class: str,
    target_level: int,
    goal: str,
    version_context: dict[str, Any],
) -> dict[str, Any]:
    """Start a progression and reuse only a fresh exact-version starter packet."""

    if not _valid_operation_id(operation_id):
        return models.rejected("invalid_operation_id")
    try:
        version = models.VersionContext.model_validate(version_context)
    except ValidationError as exc:
        return _validation_rejected("invalid_progression_version_context", exc)
    if not base_class.strip() or len(base_class) > 80 or not 2 <= target_level <= 100:
        return models.rejected("invalid_progression_request")
    if not goal.strip() or len(goal) > 600:
        return models.rejected("invalid_progression_goal")
    if copy_safety.copyability_flags(goal) or copy_safety.contains_raw_url(goal):
        return models.rejected("unsafe_progression_goal")

    with _locked_state():
        existing = _find_by_start_operation(operation_id)
        if existing is not None:
            return {
                "status": "idempotent",
                "progressionId": existing["progressionId"],
                "revision": existing["revision"],
                "currentState": existing["status"],
                "nextAction": _next_action(existing),
            }
        cached = progression_research.lookup_starter_research_cache(
            base_class=base_class,
            game_patch=version.game_patch,
            passive_tree_version=version.passive_tree_version,
        )
        packet = (
            cached.get("starterResearchPacket")
            if cached.get("status") == "hit" and cached.get("mayAdoptWithoutRevalidation") is True
            else None
        )
        candidate = cached.get("starterResearchPacket") if cached.get("status") == "stale" else None
        now = _utc_now()
        progression_id = str(uuid4())
        state: dict[str, Any] = {
            "schemaVersion": STATE_SCHEMA_VERSION,
            "progressionId": progression_id,
            "revision": 0,
            "status": "blueprint_pending" if packet else "research_pending",
            "request": {
                "baseClass": base_class.strip(),
                "targetLevel": target_level,
                "goal": goal.strip(),
                "versionContext": version.model_dump(mode="json", by_alias=True),
                "defaultMilestoneCount": 4,
                "maxMilestoneCount": 5,
            },
            "starterResearchPacket": packet,
            "starterResearchCandidate": candidate,
            "blueprint": None,
            "stages": [],
            "activeStageId": None,
            "routeId": None,
            "pause": None,
            "startOperationId": operation_id,
            "operations": [],
            "createdAt": now,
            "updatedAt": now,
        }
        if not _write_state(state):
            return models.rejected("progression_state_write_failed")
        return {
            "status": "started",
            "progressionId": progression_id,
            "revision": 0,
            "currentState": state["status"],
            "starterCache": {
                "status": cached.get("status"),
                "cacheStatus": cached.get("cacheStatus"),
                "packetId": (
                    packet.get("packetId")
                    if isinstance(packet, dict)
                    else (candidate.get("packetId") if isinstance(candidate, dict) else None)
                ),
            },
            "starterResearchPacket": packet,
            "starterResearchCandidate": candidate,
            "nextAction": _next_action(state),
            "strictlySerial": True,
            "defaultMilestoneCount": 4,
            "maxMilestoneCount": 5,
        }


def intake_starter_research_packet(
    *,
    progression_id: str,
    expected_revision: int,
    operation_id: str,
    packet: dict[str, Any],
) -> dict[str, Any]:
    with _locked_state():
        loaded = _load_for_mutation(progression_id, expected_revision, operation_id)
        if _is_terminal_load(loaded):
            return loaded
        state = loaded
        if state["status"] != "research_pending":
            return models.rejected("progression_research_not_pending")
        result = progression_research.intake_starter_research_packet(
            packet,
            version_context=state["request"]["versionContext"],
        )
        if result.get("status") != "accepted":
            return result
        safe_packet = result["starterResearchPacket"]
        if safe_packet["baseClass"].casefold() != state["request"]["baseClass"].casefold():
            return models.rejected("progression_base_class_mismatch")
        state["starterResearchPacket"] = safe_packet
        state["starterResearchCandidate"] = None
        state["status"] = "blueprint_pending"
        return _commit(
            state,
            operation_id,
            {
                "status": "research_accepted",
                "progressionId": progression_id,
                "packetId": safe_packet["packetId"],
                "evidenceStatus": safe_packet["evidenceStatus"],
                "starterResearchPacket": safe_packet,
                "containsRawWebMaterial": False,
                "containsFullUrls": False,
                "nextAction": "submit_blueprint",
            },
        )


def submit_build_progression_blueprint(
    *,
    progression_id: str,
    expected_revision: int,
    operation_id: str,
    blueprint: dict[str, Any],
) -> dict[str, Any]:
    with _locked_state():
        loaded = _load_for_mutation(progression_id, expected_revision, operation_id)
        if _is_terminal_load(loaded):
            return loaded
        state = loaded
        if state["status"] != "blueprint_pending":
            return models.rejected("progression_blueprint_not_pending")
        try:
            parsed = progression_models.ProgressionBlueprint.model_validate(blueprint)
        except ValidationError as exc:
            return _validation_rejected("invalid_progression_blueprint", exc)
        mismatch = _blueprint_mismatch(state, parsed)
        if mismatch:
            return models.rejected(mismatch)
        packet = state["starterResearchPacket"]
        claim_ids = {item["claimId"] for item in packet["claims"]}
        decision_ids = {item.claim_id for item in parsed.starter_evidence_use.decisions}
        if claim_ids != decision_ids:
            return models.rejected("starter_evidence_use_incomplete")
        if not any(
            item.decision in {"adopted", "caveated"}
            for item in parsed.starter_evidence_use.decisions
        ):
            return models.rejected("starter_evidence_use_has_no_selected_claim")
        if len(parsed.stages) < 4 and len(parsed.merge_rationale) < 4 - len(parsed.stages):
            return models.rejected("progression_milestone_merge_rationale_required")
        packet_evidence = packet["evidenceStatus"]
        if any(
            stage.route_role in {"starter_bootstrap", "starter_established"}
            and stage.evidence_status != packet_evidence
            for stage in parsed.stages
        ):
            return models.rejected("starter_stage_evidence_status_mismatch")
        state["blueprint"] = parsed.model_dump(mode="json", by_alias=True)
        state["stages"] = [
            {
                "stageId": stage.stage_id,
                "status": "pending",
                "claimId": None,
                "stageCreatePacket": None,
                "boundRunId": None,
                "artifactId": None,
                "artifactFact": None,
                "lifecycleVerification": None,
                "costProfile": None,
                "completionReport": None,
                "retryCount": 0,
                "failureCode": None,
                "startedAt": None,
                "completedAt": None,
            }
            for stage in parsed.stages
        ]
        state["status"] = "stage_pending"
        return _commit(
            state,
            operation_id,
            {
                "status": "blueprint_accepted",
                "progressionId": progression_id,
                "blueprintId": parsed.blueprint_id,
                "stageCount": len(parsed.stages),
                "nextStageId": parsed.stages[0].stage_id,
                "nextAction": "claim_stage",
            },
        )


def revise_future_build_progression_stages(
    *,
    progression_id: str,
    expected_revision: int,
    operation_id: str,
    blueprint: dict[str, Any],
) -> dict[str, Any]:
    """Version future stages while preserving every completed or active milestone."""

    with _locked_state():
        loaded = _load_for_mutation(progression_id, expected_revision, operation_id)
        if _is_terminal_load(loaded):
            return loaded
        state = loaded
        if state["status"] != "stage_pending":
            return models.rejected("progression_future_revision_not_allowed")
        if state.get("activeStageId"):
            return models.rejected("progression_active_stage_immutable")
        try:
            parsed = progression_models.ProgressionBlueprint.model_validate(blueprint)
        except ValidationError as exc:
            return _validation_rejected("invalid_progression_blueprint", exc)
        mismatch = _blueprint_mismatch(state, parsed)
        if mismatch:
            return models.rejected(mismatch)
        packet = state["starterResearchPacket"]
        claim_ids = {item["claimId"] for item in packet["claims"]}
        decision_ids = {item.claim_id for item in parsed.starter_evidence_use.decisions}
        if claim_ids != decision_ids:
            return models.rejected("starter_evidence_use_incomplete")
        if not any(
            item.decision in {"adopted", "caveated"}
            for item in parsed.starter_evidence_use.decisions
        ):
            return models.rejected("starter_evidence_use_has_no_selected_claim")
        if len(parsed.stages) < 4 and len(parsed.merge_rationale) < 4 - len(parsed.stages):
            return models.rejected("progression_milestone_merge_rationale_required")
        packet_evidence = packet["evidenceStatus"]
        if any(
            stage.route_role in {"starter_bootstrap", "starter_established"}
            and stage.evidence_status != packet_evidence
            for stage in parsed.stages
        ):
            return models.rejected("starter_stage_evidence_status_mismatch")
        old_blueprint = state["blueprint"]
        old_stages = state["stages"]
        if parsed.blueprint_id == old_blueprint["blueprintId"]:
            return models.rejected("progression_blueprint_version_id_required")
        parsed_payload = parsed.model_dump(mode="json", by_alias=True)
        if any(
            parsed_payload[key] != old_blueprint[key]
            for key in (
                "routeName",
                "starterResearchPacketId",
                "starterEvidenceUse",
                "starterChoiceSummary",
                "targetIntent",
            )
        ):
            return models.rejected("progression_blueprint_design_immutable")
        locked_records = [
            item
            for item in old_stages
            if item["status"] == "completed"
            or item["retryCount"] > 0
            or item["startedAt"] is not None
        ]
        locked_ids = [item["stageId"] for item in locked_records]
        if [stage.stage_id for stage in parsed.stages[: len(locked_ids)]] != locked_ids:
            return models.rejected("started_progression_stage_order_immutable")
        new_by_id = {stage.stage_id: stage for stage in parsed.stages}
        old_blueprint_by_id = {item["stageId"]: item for item in old_blueprint["stages"]}
        for stage_id in locked_ids:
            if (
                stage_id not in new_by_id
                or new_by_id[stage_id].model_dump(mode="json", by_alias=True)
                != old_blueprint_by_id[stage_id]
            ):
                return models.rejected("started_progression_stage_immutable")
        preserved_records = {item["stageId"]: item for item in locked_records}
        state["blueprint"] = parsed.model_dump(mode="json", by_alias=True)
        state["stages"] = [
            preserved_records.get(
                stage.stage_id,
                {
                    "stageId": stage.stage_id,
                    "status": "pending",
                    "claimId": None,
                    "stageCreatePacket": None,
                    "boundRunId": None,
                    "artifactId": None,
                    "artifactFact": None,
                    "lifecycleVerification": None,
                    "costProfile": None,
                    "completionReport": None,
                    "retryCount": 0,
                    "failureCode": None,
                    "startedAt": None,
                    "completedAt": None,
                },
            )
            for stage in parsed.stages
        ]
        state["status"] = "stage_pending"
        return _commit(
            state,
            operation_id,
            {
                "status": "future_stages_revised",
                "progressionId": progression_id,
                "blueprintId": parsed.blueprint_id,
                "preservedCompletedStageIds": [
                    item["stageId"] for item in locked_records if item["status"] == "completed"
                ],
                "preservedStartedStageIds": locked_ids,
                "nextAction": "claim_stage",
            },
        )


def claim_build_progression_stage(
    *,
    progression_id: str,
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    with _locked_state():
        loaded = _load_for_mutation(progression_id, expected_revision, operation_id)
        if _is_terminal_load(loaded):
            return loaded
        state = loaded
        if state["status"] != "stage_pending" or state.get("activeStageId"):
            return models.rejected("progression_stage_not_claimable")
        stage_state = next(
            (item for item in state["stages"] if item["status"] == "pending"),
            None,
        )
        if stage_state is None:
            return models.rejected("progression_stage_not_found")
        stage_index = state["stages"].index(stage_state)
        if any(item["status"] != "completed" for item in state["stages"][:stage_index]):
            return models.rejected("progression_strict_serial_violation")
        stage_blueprint = state["blueprint"]["stages"][stage_index]
        previous_artifact = (
            state["stages"][stage_index - 1]["artifactId"]
            if stage_index > 0 and not stage_blueprint["rebuildFromScratch"]
            else None
        )
        stage_version_context = dict(state["request"]["versionContext"])
        stage_version_context["researchMemoryRef"] = stage_blueprint["researchQueryRefs"][-1]
        packet = progression_models.StageCreatePacket(
            progression_id=state["progressionId"],
            blueprint_id=state["blueprint"]["blueprintId"],
            base_class=state["request"]["baseClass"],
            target_level=stage_blueprint["targetLevel"],
            route_target_level=state["request"]["targetLevel"],
            target_intent=state["blueprint"]["targetIntent"],
            stage=stage_blueprint,
            previous_artifact_id=previous_artifact,
            starter_research_packet_id=state["starterResearchPacket"]["packetId"],
            starter_evidence_use=state["blueprint"]["starterEvidenceUse"],
            version_context=stage_version_context,
            no_raw_material=True,
            progression_bound=True,
        )
        claim_id = f"stage-claim:{uuid4()}"
        stage_state["status"] = "running"
        stage_state["claimId"] = claim_id
        stage_state["stageCreatePacket"] = packet.model_dump(mode="json", by_alias=True)
        stage_state["startedAt"] = _utc_now()
        stage_state["failureCode"] = None
        state["activeStageId"] = stage_state["stageId"]
        state["status"] = "stage_running"
        return _commit(
            state,
            operation_id,
            {
                "status": "claimed",
                "progressionId": progression_id,
                "stageId": stage_state["stageId"],
                "claimId": claim_id,
                "stageCreatePacket": packet.model_dump(mode="json", by_alias=True),
                "nextAction": "start_phase5_run_then_bind",
                "containsRawPob": False,
            },
        )


def bind_build_progression_stage_run(
    *,
    progression_id: str,
    stage_id: str,
    claim_id: str,
    run_id: str,
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    with _locked_state():
        loaded = _load_for_mutation(progression_id, expected_revision, operation_id)
        if _is_terminal_load(loaded):
            return loaded
        state = loaded
        stage = _active_stage(state, stage_id, claim_id)
        if stage is None:
            return models.rejected("progression_stage_claim_mismatch")
        if stage["boundRunId"] is not None:
            return models.rejected("progression_stage_run_already_bound")
        if any(item["boundRunId"] == run_id for item in state["stages"]):
            return models.rejected("progression_run_already_bound")
        if _run_bound_to_other_progression(progression_id, run_id):
            return models.rejected("progression_run_already_bound")
        if not _valid_phase5_run(run_id, not_before=stage["startedAt"]):
            return models.rejected("progression_phase5_run_not_found")
        stage["boundRunId"] = run_id
        return _commit(
            state,
            operation_id,
            {
                "status": "run_bound",
                "progressionId": progression_id,
                "stageId": stage_id,
                "runId": run_id,
                "nextAction": "complete_phase5_stage",
            },
        )


def complete_build_progression_stage(
    *,
    progression_id: str,
    stage_id: str,
    claim_id: str,
    artifact_id: str,
    lifecycle_verification: dict[str, Any],
    cost_profile: dict[str, Any],
    completion_report: dict[str, Any],
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    with _locked_state():
        loaded = _load_for_mutation(progression_id, expected_revision, operation_id)
        if _is_terminal_load(loaded):
            return loaded
        state = loaded
        stage = _active_stage(state, stage_id, claim_id)
        if stage is None:
            return models.rejected("progression_stage_claim_mismatch")
        if not stage.get("boundRunId"):
            return models.rejected("progression_stage_run_not_bound")
        try:
            report = StageCompletionReport.model_validate(completion_report)
        except ValidationError as exc:
            return _validation_rejected("invalid_stage_completion_report", exc)
        stage_index = state["stages"].index(stage)
        if stage_index == 0 and report.changes_from_previous:
            return models.rejected("first_progression_stage_cannot_have_changes")
        if stage_index > 0 and not report.changes_from_previous:
            return models.rejected("later_progression_stage_requires_changes")
        verified = artifacts.read_final_build_artifact_for_export(artifact_id)
        if verified is None:
            return models.rejected("progression_stage_artifact_not_trusted")
        manifest, _xml = verified
        stage_blueprint = state["blueprint"]["stages"][stage_index]
        artifact_error = _artifact_mismatch(state, stage, stage_blueprint, manifest)
        if artifact_error:
            return models.rejected(artifact_error)
        safe_lifecycle = _safe_lifecycle_verification(lifecycle_verification)
        if safe_lifecycle is None:
            return models.rejected("invalid_progression_lifecycle_verification")
        if (
            safe_lifecycle["pass"] is not True
            or safe_lifecycle["status"] != "passed"
            or safe_lifecycle["stage"] != stage_blueprint["lifecycleStage"]
        ):
            return models.rejected("progression_lifecycle_stage_not_verified")
        if safe_lifecycle["evaluatedSourceHash"] != manifest.source_hash:
            return models.rejected("progression_lifecycle_source_hash_mismatch")
        trusted_cost = progression_costs.read_trusted_cost_profile(
            str(cost_profile.get("costProfileRef") or ""),
            stage_id=stage_id,
        )
        if trusted_cost is None:
            return models.rejected("invalid_progression_cost_profile")
        if (
            str(trusted_cost.get("league") or "").casefold()
            != str(state["request"]["versionContext"]["league"]).casefold()
        ):
            return models.rejected("progression_cost_profile_league_mismatch")
        if any(
            key in cost_profile
            for key in ("totalPrice", "totalDivine", "estimatedTotal", "buildTotal")
        ):
            return models.rejected("progression_total_price_forbidden")
        stage["status"] = "completed"
        stage["artifactId"] = artifact_id
        stage["artifactFact"] = {
            "artifactId": manifest.artifact_id,
            "runId": manifest.run_id,
            "sourceHash": manifest.source_hash,
            "class": str(manifest.safe_summary.get("class") or ""),
            "ascendancy": str(manifest.safe_summary.get("ascendancy") or ""),
            "level": int(manifest.safe_summary.get("level") or 0),
            "mainSkill": str(manifest.safe_summary.get("mainSkill") or ""),
            "judgePlayabilityFailures": list(manifest.judge_report.playability_failures),
            "judgeQualityWarnings": list(manifest.judge_report.quality_warnings),
            "judgeCaveats": list(manifest.judge_report.caveats),
            "judgeScoreApplicability": manifest.judge_report.score_applicability,
            "judgeModelabilityStatus": manifest.judge_report.modelability_status,
        }
        stage["lifecycleVerification"] = safe_lifecycle
        stage["costProfile"] = trusted_cost
        stage["completionReport"] = report.model_dump(mode="json", by_alias=True)
        stage["completedAt"] = _utc_now()
        state["activeStageId"] = None
        remaining = [item for item in state["stages"] if item["status"] != "completed"]
        state["status"] = "stage_pending" if remaining else "finalize_pending"
        return _commit(
            state,
            operation_id,
            {
                "status": "stage_completed",
                "progressionId": progression_id,
                "stageId": stage_id,
                "artifactId": artifact_id,
                "nextStageId": remaining[0]["stageId"] if remaining else None,
                "nextAction": "claim_stage" if remaining else "finalize_progression",
            },
        )


def fail_build_progression_stage(
    *,
    progression_id: str,
    stage_id: str,
    claim_id: str,
    failure_code: str,
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    with _locked_state():
        loaded = _load_for_mutation(progression_id, expected_revision, operation_id)
        if _is_terminal_load(loaded):
            return loaded
        state = loaded
        stage = _active_stage(state, stage_id, claim_id)
        if stage is None:
            return models.rejected("progression_stage_claim_mismatch")
        if not _FAILURE_CODE.fullmatch(failure_code):
            return models.rejected("invalid_progression_failure_code")
        stage["status"] = "failed"
        stage["failureCode"] = failure_code
        state["activeStageId"] = None
        state["status"] = "failed"
        return _commit(
            state,
            operation_id,
            {
                "status": "stage_failed",
                "progressionId": progression_id,
                "stageId": stage_id,
                "failureCode": failure_code,
                "retryAvailable": stage["retryCount"] < 1,
                "nextAction": "retry_stage_or_review",
            },
        )


def retry_build_progression_stage(
    *,
    progression_id: str,
    stage_id: str,
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    with _locked_state():
        loaded = _load_for_mutation(progression_id, expected_revision, operation_id)
        if _is_terminal_load(loaded):
            return loaded
        state = loaded
        if state["status"] != "failed":
            return models.rejected("progression_stage_retry_not_available")
        stage = _find_stage(state, stage_id)
        if stage is None or stage["status"] != "failed":
            return models.rejected("progression_stage_retry_not_available")
        if stage["retryCount"] >= 1:
            return models.rejected("progression_stage_retry_limit_reached")
        stage.update(
            {
                "status": "pending",
                "claimId": None,
                "stageCreatePacket": None,
                "boundRunId": None,
                "failureCode": None,
                "retryCount": 1,
                "startedAt": None,
            }
        )
        state["status"] = "stage_pending"
        return _commit(
            state,
            operation_id,
            {
                "status": "stage_retry_opened",
                "progressionId": progression_id,
                "stageId": stage_id,
                "retryCount": 1,
                "nextAction": "claim_stage",
            },
        )


def pause_build_progression(
    *,
    progression_id: str,
    expected_revision: int,
    operation_id: str,
    reason: str,
) -> dict[str, Any]:
    with _locked_state():
        loaded = _load_for_mutation(progression_id, expected_revision, operation_id)
        if _is_terminal_load(loaded):
            return loaded
        state = loaded
        if state["status"] in {"completed", "paused"}:
            return models.rejected("progression_not_pausable")
        if not reason.strip() or len(reason) > 320:
            return models.rejected("invalid_progression_pause_reason")
        if copy_safety.copyability_flags(reason) or copy_safety.contains_raw_url(reason):
            return models.rejected("invalid_progression_pause_reason")
        previous = state["status"]
        state["pause"] = {
            "previousState": previous,
            "reason": copy_safety.safe_text(reason, limit=320),
            "pausedAt": _utc_now(),
        }
        state["status"] = "paused"
        return _commit(
            state,
            operation_id,
            {
                "status": "paused",
                "progressionId": progression_id,
                "previousState": previous,
                "nextAction": "resume_progression",
            },
        )


def resume_build_progression(
    *,
    progression_id: str,
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    with _locked_state():
        loaded = _load_for_mutation(progression_id, expected_revision, operation_id)
        if _is_terminal_load(loaded):
            return loaded
        state = loaded
        if state["status"] != "paused" or not isinstance(state.get("pause"), dict):
            return models.rejected("progression_not_paused")
        restored = state["pause"].get("previousState")
        if restored not in {
            "research_pending",
            "blueprint_pending",
            "stage_pending",
            "stage_running",
            "finalize_pending",
            "failed",
        }:
            return models.rejected("progression_pause_state_invalid")
        state["status"] = restored
        state["pause"] = None
        return _commit(
            state,
            operation_id,
            {
                "status": "resumed",
                "progressionId": progression_id,
                "currentState": restored,
                "nextAction": _next_action(state),
            },
        )


def get_build_progression_status(progression_id: str) -> dict[str, Any]:
    state = _read_state(progression_id)
    if state is None:
        return models.rejected("build_progression_not_found")
    return {
        "status": "ok",
        "buildProgression": _public_state(state),
        "containsRawPob": False,
        "containsRawWebMaterial": False,
    }


def finalize_build_progression(
    *,
    progression_id: str,
    expected_revision: int,
    operation_id: str,
    route_summary: str,
) -> dict[str, Any]:
    with _locked_state():
        loaded = _load_for_mutation(progression_id, expected_revision, operation_id)
        if _is_terminal_load(loaded):
            return loaded
        state = loaded
        if state["status"] != "finalize_pending":
            return models.rejected("progression_not_ready_to_finalize")
        if not route_summary.strip() or len(route_summary) > 800:
            return models.rejected("invalid_progression_route_summary")
        if copy_safety.copyability_flags(route_summary) or copy_safety.contains_raw_url(
            route_summary
        ):
            return models.rejected("unsafe_progression_route_summary")
        route_stages = []
        packet = state["starterResearchPacket"]
        for index, stage_state in enumerate(state["stages"]):
            blueprint = state["blueprint"]["stages"][index]
            report = stage_state["completionReport"]
            route_stages.append(
                {
                    "stageId": stage_state["stageId"],
                    "lifecycleStage": blueprint["lifecycleStage"],
                    "routeRole": blueprint["routeRole"],
                    "targetLevel": blueprint["targetLevel"],
                    "artifactId": stage_state["artifactId"],
                    "purpose": report["purpose"],
                    "playPattern": report["playPattern"],
                    "evidenceStatus": blueprint["evidenceStatus"],
                    "sourceRefs": list(
                        dict.fromkeys(
                            [
                                packet["packetId"],
                                *blueprint["researchQueryRefs"],
                                *report["sourceRefs"],
                            ]
                        )
                    ),
                    "changesFromPrevious": report["changesFromPrevious"],
                    "transitionBridge": blueprint["entryBridge"],
                    "acquisitionPriorities": report["acquisitionPriorities"],
                    "caveats": report["caveats"],
                    "costProfileRef": stage_state["costProfile"]["costProfileRef"],
                    "costProfile": {
                        key: stage_state["costProfile"][key]
                        for key in (
                            "costProfileRef",
                            "league",
                            "baseCurrency",
                            "highestRequiredBand",
                            "paidDependencyCount",
                            "requiredDependencyCount",
                            "unknownRequiredDependencyCount",
                            "fallbackCoverage",
                            "livePriceCoverage",
                            "costEvidenceStatus",
                            "capturedAt",
                            "expiresAt",
                            "containsTotalPrice",
                        )
                    },
                }
            )
        target_artifact = state["stages"][-1]["artifactId"]
        route = progression.save_progression_route(
            {
                "routeName": state["blueprint"]["routeName"],
                "classShell": state["request"]["baseClass"],
                "targetArtifactId": target_artifact,
                "stages": route_stages,
                "routeSummary": route_summary.strip(),
                "starterResearchPacketId": packet["packetId"],
                "versionContext": state["request"]["versionContext"],
                "noRawMaterial": True,
            },
            route_id=progression_id,
        )
        if route.get("status") != "saved":
            return route
        state["routeId"] = route["progressionRoute"]["routeId"]
        state["status"] = "completed"
        return _commit(
            state,
            operation_id,
            {
                "status": "completed",
                "progressionId": progression_id,
                "routeId": state["routeId"],
                "qualityStatus": route["progressionRoute"]["qualityStatus"],
                "targetArtifactId": target_artifact,
                "nextAction": "export_progression_package",
                "containsRawPob": False,
            },
        )


def _blueprint_mismatch(
    state: dict[str, Any],
    blueprint: progression_models.ProgressionBlueprint,
) -> str | None:
    request = state["request"]
    packet = state.get("starterResearchPacket") or {}
    if blueprint.base_class.casefold() != request["baseClass"].casefold():
        return "progression_base_class_mismatch"
    if blueprint.target_level != request["targetLevel"]:
        return "progression_target_level_mismatch"
    if blueprint.starter_research_packet_id != packet.get("packetId"):
        return "progression_starter_packet_mismatch"
    if (
        blueprint.version_context.model_dump(mode="json", by_alias=True)
        != request["versionContext"]
    ):
        return "progression_version_context_mismatch"
    return None


def _artifact_mismatch(
    state: dict[str, Any],
    stage_state: dict[str, Any],
    stage_blueprint: dict[str, Any],
    manifest: artifacts.FinalBuildArtifactManifest,
) -> str | None:
    if manifest.run_id != stage_state["boundRunId"]:
        return "progression_stage_run_artifact_mismatch"
    try:
        level = int(manifest.safe_summary.get("level") or 0)
    except (TypeError, ValueError):
        return "progression_stage_level_mismatch"
    if level != stage_blueprint["targetLevel"]:
        return "progression_stage_level_mismatch"
    class_shell = str(manifest.safe_summary.get("class") or "")
    if class_shell.casefold() != state["request"]["baseClass"].casefold():
        return "progression_base_class_mismatch"
    artifact_version = manifest.version_context.model_dump(mode="json", by_alias=True)
    requested_version = state["request"]["versionContext"]
    immutable_version_keys = (
        "league",
        "ruleset",
        "gamePatch",
        "passiveTreeVersion",
        "pobVersionOrCommit",
        "graphSnapshotId",
    )
    if any(
        artifact_version.get(key) != requested_version.get(key) for key in immutable_version_keys
    ):
        return "progression_version_context_mismatch"
    stage_packet = stage_state.get("stageCreatePacket")
    packet_version = (
        stage_packet.get("versionContext")
        if isinstance(stage_packet, dict) and isinstance(stage_packet.get("versionContext"), dict)
        else {}
    )
    if artifact_version.get("researchMemoryRef") != packet_version.get("researchMemoryRef"):
        return "progression_stage_research_query_mismatch"
    if any(
        item.get("artifactId") == manifest.artifact_id
        or (
            item.get("artifactFact")
            and item["artifactFact"].get("sourceHash") == manifest.source_hash
        )
        for item in state["stages"]
        if item is not stage_state
    ):
        return "progression_duplicate_snapshot"
    return None


def _safe_lifecycle_verification(value: dict[str, Any]) -> dict[str, Any] | None:
    """Select and bound the lifecycle fields allowed into durable progression state."""

    if not isinstance(value, dict):
        return None
    stage = value.get("stage")
    status = value.get("status")
    passed = value.get("pass")
    source_hash = value.get("evaluatedSourceHash")
    if (
        stage not in _LIFECYCLE_STAGES
        or status not in {"passed", "failed", "unknown"}
        or not isinstance(passed, bool)
        or not isinstance(source_hash, str)
        or not _LIFECYCLE_TOKEN.fullmatch(source_hash)
    ):
        return None

    def token_list(key: str, limit: int) -> list[str] | None:
        raw = value.get(key, [])
        if (
            not isinstance(raw, list)
            or len(raw) > limit
            or any(
                not isinstance(item, str) or not _LIFECYCLE_TOKEN.fullmatch(item) for item in raw
            )
        ):
            return None
        return list(raw)

    failed = token_list("failedChecks", 24)
    unknown = token_list("unknownChecks", 24)
    evidence_tags = token_list("evidenceTags", 8)
    caveats = value.get("caveats", [])
    if (
        failed is None
        or unknown is None
        or evidence_tags is None
        or not isinstance(caveats, list)
        or len(caveats) > 12
        or any(not isinstance(item, str) or not item.strip() or len(item) > 500 for item in caveats)
    ):
        return None
    selected = {
        "stage": value.get("stage"),
        "status": value.get("status"),
        "pass": value.get("pass"),
        "failedChecks": failed,
        "unknownChecks": unknown,
        "caveats": list(caveats),
        "evidenceTags": evidence_tags,
        "evaluatedSourceHash": value.get("evaluatedSourceHash"),
    }
    try:
        _ensure_safe(selected)
    except ValueError:
        return None
    return selected


def _valid_phase5_run(run_id: str, *, not_before: str) -> bool:
    canonical = run_store.canonical_run_id(run_id)
    if canonical is None:
        return False
    run_dir = run_store.runs_dir() / canonical
    manifest = run_store.read_run_manifest(
        run_dir / "run-manifest.json",
        canonical,
        run_dir / "agent-output.json",
    )
    if manifest is None or run_store.run_expired(str(manifest["startedAt"])):
        return False
    try:
        run_started = datetime.fromisoformat(str(manifest["startedAt"]))
        stage_started = datetime.fromisoformat(not_before)
    except (TypeError, ValueError):
        return False
    if run_started.tzinfo is None or stage_started.tzinfo is None:
        return False
    return run_started >= stage_started


def _active_stage(
    state: dict[str, Any],
    stage_id: str,
    claim_id: str,
) -> dict[str, Any] | None:
    if state["status"] != "stage_running" or state.get("activeStageId") != stage_id:
        return None
    stage = _find_stage(state, stage_id)
    if stage is None or stage["status"] != "running" or stage["claimId"] != claim_id:
        return None
    return stage


def _find_stage(state: dict[str, Any], stage_id: str) -> dict[str, Any] | None:
    return next((item for item in state.get("stages", []) if item["stageId"] == stage_id), None)


def _next_action(state: dict[str, Any]) -> str:
    return {
        "research_pending": "intake_starter_research",
        "blueprint_pending": "submit_blueprint",
        "stage_pending": "claim_stage",
        "stage_running": "continue_bound_stage",
        "finalize_pending": "finalize_progression",
        "completed": "export_progression_package",
        "paused": "resume_progression",
        "failed": "retry_stage_or_review",
    }.get(state["status"], "inspect_progression")


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    packet = state.get("starterResearchPacket")
    active_stage = (
        _find_stage(state, state["activeStageId"]) if state.get("activeStageId") else None
    )
    active_stage_blueprint = None
    if active_stage is not None and isinstance(state.get("blueprint"), dict):
        active_stage_blueprint = next(
            (
                item
                for item in state["blueprint"]["stages"]
                if item["stageId"] == active_stage["stageId"]
            ),
            None,
        )
    return {
        "progressionId": state["progressionId"],
        "revision": state["revision"],
        "currentState": state["status"],
        "request": state["request"],
        "starterResearch": (
            {
                "packetId": packet["packetId"],
                "evidenceStatus": packet["evidenceStatus"],
                "packetStatus": packet["packetStatus"],
                "sourceCount": len(packet["sources"]),
                "claimCount": len(packet["claims"]),
                "expiresAt": packet["expiresAt"],
            }
            if isinstance(packet, dict)
            else None
        ),
        "starterResearchPacket": packet,
        "starterResearchCandidate": state.get("starterResearchCandidate"),
        "blueprintId": (
            state["blueprint"].get("blueprintId")
            if isinstance(state.get("blueprint"), dict)
            else None
        ),
        "stages": [
            {
                "stageId": item["stageId"],
                "status": item["status"],
                "claimId": item["claimId"] if item["status"] == "running" else None,
                "boundRunId": item["boundRunId"],
                "artifactId": item["artifactId"],
                "artifactEvidence": item["artifactFact"],
                "retryCount": item["retryCount"],
                "failureCode": item["failureCode"],
                "lifecycleVerification": item["lifecycleVerification"],
                "costProfileRef": (
                    item["costProfile"].get("costProfileRef")
                    if isinstance(item.get("costProfile"), dict)
                    else None
                ),
            }
            for item in state["stages"]
        ],
        "activeStageId": state.get("activeStageId"),
        "activeStage": (
            {
                "stageId": active_stage["stageId"],
                "claimId": active_stage["claimId"],
                "boundRunId": active_stage["boundRunId"],
                "stageCreatePacket": active_stage.get("stageCreatePacket"),
                "stageBlueprint": active_stage_blueprint,
                "routeTargetLevel": state["request"]["targetLevel"],
                "targetIntent": state["blueprint"]["targetIntent"],
                "starterResearchPacketId": state["starterResearchPacket"]["packetId"],
                "starterEvidenceUse": state["blueprint"]["starterEvidenceUse"],
                "versionContext": {
                    **state["request"]["versionContext"],
                    "researchMemoryRef": active_stage_blueprint["researchQueryRefs"][-1],
                },
            }
            if active_stage is not None and active_stage_blueprint is not None
            else None
        ),
        "routeId": state.get("routeId"),
        "pause": state.get("pause"),
        "nextAction": _next_action(state),
        "createdAt": state["createdAt"],
        "updatedAt": state["updatedAt"],
    }


def _state_path(progression_id: str) -> Path | None:
    try:
        canonical = str(UUID(progression_id))
    except (AttributeError, TypeError, ValueError):
        return None
    if canonical != progression_id:
        return None
    return paths.build_progression_runs_dir() / canonical / "state.json"


def _read_state(progression_id: str) -> dict[str, Any] | None:
    path = _state_path(progression_id)
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        payload.get("schemaVersion") != STATE_SCHEMA_VERSION
        or payload.get("progressionId") != progression_id
        or not isinstance(payload.get("revision"), int)
        or not isinstance(payload.get("operations"), list)
    ):
        return None
    try:
        _ensure_safe(payload)
    except ValueError:
        return None
    return payload


def _write_state(state: dict[str, Any]) -> bool:
    path = _state_path(state["progressionId"])
    if path is None:
        return False
    temp = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        _ensure_safe(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)
    except (OSError, ValueError):
        temp.unlink(missing_ok=True)
        return False
    return True


def _find_by_start_operation(operation_id: str) -> dict[str, Any] | None:
    root = paths.build_progression_runs_dir()
    if not root.is_dir():
        return None
    for child in root.iterdir():
        state = _read_state(child.name)
        if state is not None and state.get("startOperationId") == operation_id:
            return state
    return None


def _run_bound_to_other_progression(progression_id: str, run_id: str) -> bool:
    root = paths.build_progression_runs_dir()
    if not root.is_dir():
        return False
    for child in root.iterdir():
        if child.name == progression_id:
            continue
        state = _read_state(child.name)
        if state is not None and any(
            stage.get("boundRunId") == run_id for stage in state.get("stages", [])
        ):
            return True
    return False


def _load_for_mutation(
    progression_id: str,
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    if not _valid_operation_id(operation_id):
        return models.rejected("invalid_operation_id")
    state = _read_state(progression_id)
    if state is None:
        return models.rejected("build_progression_not_found")
    existing = next(
        (item for item in state["operations"] if item.get("operationId") == operation_id),
        None,
    )
    if existing is not None:
        response = dict(existing["response"])
        response["idempotent"] = True
        response["revision"] = state["revision"]
        return response
    if isinstance(expected_revision, bool) or expected_revision != state["revision"]:
        return {
            "status": "rejected",
            "errorCode": "progression_revision_conflict",
            "expectedRevision": expected_revision,
            "currentRevision": state["revision"],
        }
    return state


def _commit(
    state: dict[str, Any],
    operation_id: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    state["revision"] += 1
    state["updatedAt"] = _utc_now()
    committed = dict(response)
    committed["revision"] = state["revision"]
    committed["currentState"] = state["status"]
    state["operations"].append(
        {
            "operationId": operation_id,
            "committedAt": state["updatedAt"],
            "response": committed,
        }
    )
    state["operations"] = state["operations"][-200:]
    if not _write_state(state):
        return models.rejected("progression_state_write_failed")
    return committed


def _is_terminal_load(value: dict[str, Any]) -> bool:
    return value.get("status") in {"rejected", "idempotent"} or value.get("idempotent") is True


def _valid_operation_id(value: str) -> bool:
    return isinstance(value, str) and bool(_OPERATION_ID.fullmatch(value))


def _ensure_safe(value: Any) -> None:
    if (
        copy_safety.find_forbidden_paths(value)
        or copy_safety.durable_knowledge_flags(value)
        or copy_safety.contains_raw_url(value)
    ):
        raise ValueError("unsafe progression control state")


def _validation_rejected(code: str, exc: ValidationError) -> dict[str, Any]:
    first: Any = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", ())) or "input"
    return models.rejected(code, caveats=[f"{loc}: {first.get('msg', '')}"[:240]])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
