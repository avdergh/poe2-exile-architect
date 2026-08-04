"""Bounded, copy-safe working context for long Phase 8 Create runs.

Conversation context is transport, not durable working memory.  This module stores only the
Agent's concise, auditable decisions and selected Research premises beside one progression run so
an automatic context compaction can be recovered without replaying every earlier tool response.
It never stores PoB XML/import codes, web pages, raw URLs, transcripts, or hidden reasoning.
"""

from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, ValidationError, model_validator

from server import paths
from server.knowledge import copy_safety
from server.learning.file_lock import interprocess_file_lock

from . import models, progression_models


CONTEXT_SCHEMA_VERSION = 1
MAX_CONTEXT_BYTES = 24_000
MAX_OPERATION_HISTORY = 40
_LOCK = threading.RLock()
_OPERATION_ID = re.compile(r"^[A-Za-z0-9_.:\-]{3,160}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9_.:/\-]{3,240}$")

EvidenceDecision = Literal["adopted", "caveated", "rejected"]


class RecalledEvidenceCheckpoint(models.StrictModel):
    """One selected Research item and the conditions the Agent must keep visible."""

    evidence_ref: str = Field(min_length=3, max_length=240)
    knowledge_kind: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=180)
    decision: EvidenceDecision
    application: str = Field(min_length=1, max_length=360)
    critical_conditions: list[str] = Field(default_factory=list, max_length=8)
    failure_conditions: list[str] = Field(default_factory=list, max_length=8)
    verification_tasks: list[str] = Field(default_factory=list, max_length=8)
    verification_refs: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _safe(self) -> "RecalledEvidenceCheckpoint":
        _safe_refs([self.evidence_ref, *self.verification_refs])
        _safe_authored(
            {
                "knowledgeKind": self.knowledge_kind,
                "title": self.title,
                "application": self.application,
                "criticalConditions": self.critical_conditions,
                "failureConditions": self.failure_conditions,
                "verificationTasks": self.verification_tasks,
            }
        )
        return self


class RecalledPremiseDecisionCheckpoint(models.StrictModel):
    """One critical Research premise and the Agent's durable handling decision."""

    premise_id: str = Field(pattern=r"^rp-[0-9a-f]{16}$")
    decision: Literal["resolved", "caveated", "not_applicable"]
    resolution_refs: list[str] = Field(default_factory=list, max_length=12)
    application: str = Field(min_length=1, max_length=360)
    caveat: str | None = Field(default=None, min_length=1, max_length=360)
    verification_tasks: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _safe(self) -> "RecalledPremiseDecisionCheckpoint":
        _safe_refs(self.resolution_refs)
        if len(self.resolution_refs) != len(set(self.resolution_refs)):
            raise ValueError("premise resolution refs must be unique")
        if self.decision == "resolved":
            if not self.resolution_refs or self.caveat is not None:
                raise ValueError("resolved premise requires refs and no caveat")
        elif self.decision == "caveated":
            if not self.caveat:
                raise ValueError("caveated premise requires a caveat")
        elif self.resolution_refs or self.caveat is not None:
            raise ValueError("not_applicable premise uses application as its reason")
        _safe_authored(
            {
                "application": self.application,
                "caveat": self.caveat,
                "verificationTasks": self.verification_tasks,
            }
        )
        return self


class MechanismCheckpoint(models.StrictModel):
    """Compact conclusions, not a hidden reasoning trace."""

    summary: str = Field(min_length=1, max_length=500)
    damage_loop: list[str] = Field(default_factory=list, max_length=10)
    resource_loop: list[str] = Field(default_factory=list, max_length=10)
    defense_loop: list[str] = Field(default_factory=list, max_length=10)
    configuration_assumptions: list[str] = Field(default_factory=list, max_length=12)
    unresolved_items: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _safe(self) -> "MechanismCheckpoint":
        _safe_authored(self.model_dump(mode="json", by_alias=True))
        return self


class ProgressionWorkingCheckpoint(models.StrictModel):
    """The bounded semantic working set restored after compaction."""

    checkpoint_id: str = Field(pattern=r"^context-checkpoint:[A-Za-z0-9\-]{3,100}$")
    stage_id: str | None = Field(
        default=None,
        pattern=r"^stage:[A-Za-z0-9\-]{3,100}$",
    )
    current_goal: str = Field(min_length=1, max_length=400)
    knowledge_mode: progression_models.StageKnowledgeMode | None = None
    family_identity: progression_models.StageFamilyIdentity | None = None
    starter_identity: progression_models.StarterStageIdentity | None = None
    recalled_evidence: list[RecalledEvidenceCheckpoint] = Field(
        default_factory=list,
        max_length=24,
    )
    premise_decisions: list[RecalledPremiseDecisionCheckpoint] = Field(
        default_factory=list,
    )
    mechanism: MechanismCheckpoint
    next_actions: list[str] = Field(min_length=1, max_length=10)
    active_artifact_id: str | None = Field(
        default=None,
        pattern=r"^final-build:[A-Za-z0-9\-]{3,100}$",
    )
    active_build_state_hash: str | None = Field(default=None, min_length=3, max_length=240)

    @model_validator(mode="after")
    def _safe(self) -> "ProgressionWorkingCheckpoint":
        if self.knowledge_mode == "family_exact" and (
            self.family_identity is None or self.starter_identity is not None
        ):
            raise ValueError("family checkpoint requires only a Family identity")
        if self.knowledge_mode == "starter_common" and (
            self.starter_identity is None or self.family_identity is not None
        ):
            raise ValueError("starter checkpoint requires only a starter identity")
        refs = [item.evidence_ref for item in self.recalled_evidence]
        if len(refs) != len(set(refs)):
            raise ValueError("working-context evidence refs must be unique")
        premise_ids = [item.premise_id for item in self.premise_decisions]
        if len(premise_ids) != len(set(premise_ids)):
            raise ValueError("working-context premise IDs must be unique")
        if self.active_build_state_hash is not None:
            _safe_refs([self.active_build_state_hash])
        _safe_authored(
            {
                "currentGoal": self.current_goal,
                "nextActions": self.next_actions,
            }
        )
        payload = self.model_dump(mode="json", by_alias=True)
        _ensure_safe(payload)
        if _json_size(payload) > MAX_CONTEXT_BYTES:
            raise ValueError("progression working context exceeds bounded size")
        return self


@contextmanager
def _locked_context():
    with _LOCK:
        with interprocess_file_lock(paths.build_progression_runs_dir() / ".context.lock"):
            yield


def checkpoint_progression_context(
    *,
    progression_id: str,
    expected_context_revision: int,
    operation_id: str,
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    """CAS-update one progression's semantic working set."""

    if not _valid_progression_id(progression_id):
        return models.rejected("invalid_progression_id")
    if not isinstance(operation_id, str) or not _OPERATION_ID.fullmatch(operation_id):
        return models.rejected("invalid_operation_id")
    try:
        parsed = ProgressionWorkingCheckpoint.model_validate(checkpoint)
    except ValidationError as exc:
        return {
            "status": "rejected",
            "errorCode": "invalid_progression_working_context",
            "details": str(exc)[:600],
        }

    with _locked_context():
        context_path = _context_path(progression_id)
        state = _read_context(progression_id)
        if state is None and context_path.exists():
            return models.rejected("progression_context_corrupt")
        state = state or _empty_context(progression_id)
        existing = next(
            (item for item in state["operations"] if item.get("operationId") == operation_id),
            None,
        )
        if existing is not None:
            return {
                **existing["response"],
                "idempotent": True,
                "contextRevision": state["contextRevision"],
            }
        if (
            isinstance(expected_context_revision, bool)
            or expected_context_revision != state["contextRevision"]
        ):
            return {
                "status": "rejected",
                "errorCode": "progression_context_revision_conflict",
                "expectedContextRevision": expected_context_revision,
                "currentContextRevision": state["contextRevision"],
            }

        state["contextRevision"] += 1
        state["checkpoint"] = parsed.model_dump(mode="json", by_alias=True)
        state["updatedAt"] = _utc_now()
        response = {
            "status": "context_checkpointed",
            "progressionId": progression_id,
            "contextRevision": state["contextRevision"],
            "checkpointId": parsed.checkpoint_id,
            "stageId": parsed.stage_id,
            "resumePacketAvailable": True,
            "containsRawMaterial": False,
        }
        state["operations"].append(
            {
                "operationId": operation_id,
                "committedAt": state["updatedAt"],
                "response": response,
            }
        )
        state["operations"] = state["operations"][-MAX_OPERATION_HISTORY:]
        if not _write_context(progression_id, state):
            return models.rejected("progression_context_write_failed")
        return response


def read_progression_context(progression_id: str) -> dict[str, Any] | None:
    """Read a validated working set without exposing operation history."""

    if not _valid_progression_id(progression_id):
        return None
    with _locked_context():
        state = _read_context(progression_id)
    if state is None:
        return None
    return {
        "schemaVersion": state["schemaVersion"],
        "progressionId": state["progressionId"],
        "contextRevision": state["contextRevision"],
        "checkpoint": state["checkpoint"],
        "updatedAt": state["updatedAt"],
    }


def _empty_context(progression_id: str) -> dict[str, Any]:
    now = _utc_now()
    return {
        "schemaVersion": CONTEXT_SCHEMA_VERSION,
        "progressionId": progression_id,
        "contextRevision": 0,
        "checkpoint": None,
        "operations": [],
        "createdAt": now,
        "updatedAt": now,
    }


def _context_path(progression_id: str) -> Path:
    return paths.build_progression_runs_dir() / progression_id / "working-context.json"


def _read_context(progression_id: str) -> dict[str, Any] | None:
    path = _context_path(progression_id)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != CONTEXT_SCHEMA_VERSION
        or value.get("progressionId") != progression_id
        or not isinstance(value.get("contextRevision"), int)
        or isinstance(value.get("contextRevision"), bool)
        or not isinstance(value.get("operations"), list)
    ):
        return None
    checkpoint = value.get("checkpoint")
    if checkpoint is not None:
        try:
            ProgressionWorkingCheckpoint.model_validate(checkpoint)
        except ValidationError:
            return None
    return value


def _write_context(progression_id: str, value: dict[str, Any]) -> bool:
    path = _context_path(progression_id)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def _valid_progression_id(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except (AttributeError, TypeError, ValueError):
        return False


def _safe_refs(values: list[str]) -> None:
    if len(values) != len(set(values)) or any(not _SAFE_REF.fullmatch(item) for item in values):
        raise ValueError("working-context refs must be unique safe references")


def _safe_authored(value: Any) -> None:
    if copy_safety.copyability_flags(value) or copy_safety.contains_raw_url(value):
        raise ValueError("copyable material is forbidden in progression working context")


def _ensure_safe(value: Any) -> None:
    if (
        copy_safety.find_forbidden_paths(value)
        or copy_safety.durable_knowledge_flags(value)
        or copy_safety.contains_raw_url(value)
    ):
        raise ValueError("unsafe progression working context")


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
