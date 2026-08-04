"""Run bindings and trusted evaluation receipts for Phase 5 generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from . import models


ROOT = Path(__file__).resolve().parents[2]
RUN_TTL = timedelta(hours=2)


class RunStoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BoundRun:
    run_id: str
    run_dir: Path
    manifest: dict[str, Any]

    @property
    def trusted_evaluation_path(self) -> Path:
        return self.run_dir / "trusted-evaluation.json"

    @property
    def trusted_evaluations_dir(self) -> Path:
        return self.run_dir / "trusted-evaluations"

    @property
    def artifact_selection_path(self) -> Path:
        return self.run_dir / "artifact-selection.json"


def runs_dir() -> Path:
    override = os.environ.get("POE_BD_CREATE_RUNS_DIR")
    return Path(override).resolve() if override else (ROOT / ".poe-bd-create" / "runs").resolve()


def load_bound_run(
    run_id: str,
    run_token: str,
    *,
    require_unconsumed: bool = True,
) -> BoundRun:
    canonical = canonical_run_id(run_id)
    if canonical is None:
        raise RunStoreError("invalid_run_manifest")
    run_dir = runs_dir() / canonical
    if require_unconsumed and (run_dir / "review-consumed").exists():
        raise RunStoreError("run_already_consumed")
    manifest = read_run_manifest(
        run_dir / "run-manifest.json",
        canonical,
        run_dir / "agent-output.json",
    )
    if manifest is None:
        raise RunStoreError("invalid_run_manifest")
    if manifest["runContext"]["runToken"] != run_token:
        raise RunStoreError("run_binding_mismatch")
    if run_expired(manifest["startedAt"]):
        raise RunStoreError("run_expired")
    return BoundRun(run_id=canonical, run_dir=run_dir, manifest=manifest)


def read_run_manifest(
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
    if manifest_output_path != output_path.resolve():
        return None
    return data


def read_trusted_evaluation(bound_run: BoundRun) -> dict[str, Any] | None:
    try:
        payload = json.loads(bound_run.trusted_evaluation_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schemaVersion") not in {1, 2} or payload.get("runId") != bound_run.run_id:
        return None
    if not isinstance(payload.get("candidateId"), str) or not payload["candidateId"]:
        return None
    if not isinstance(payload.get("transientBuildState"), dict):
        return None
    if not isinstance(payload.get("judgeAdvisoryReport"), dict):
        return None
    if payload.get("schemaVersion") == 2 and not _valid_hard_legality_audit(payload):
        return None
    return payload


def read_trusted_evaluations(bound_run: BoundRun) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for attempt_index in range(3):
        path = bound_run.trusted_evaluations_dir / f"attempt-{attempt_index}.json"
        if not path.is_file():
            break
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError, json.JSONDecodeError):
            return []
        if (
            not isinstance(payload, dict)
            or payload.get("schemaVersion") not in {1, 2}
            or payload.get("runId") != bound_run.run_id
            or payload.get("attemptIndex") != attempt_index
            or not isinstance(payload.get("candidateId"), str)
            or not isinstance(payload.get("transientBuildState"), dict)
            or not isinstance(payload.get("judgeAdvisoryReport"), dict)
        ):
            return []
        if payload.get("schemaVersion") == 2 and not _valid_hard_legality_audit(payload):
            return []
        receipts.append(payload)
    return receipts


def read_trusted_evaluations_strict(bound_run: BoundRun) -> list[dict[str, Any]]:
    """Read a complete receipt chain and fail closed on corruption or index gaps."""
    directory = bound_run.trusted_evaluations_dir
    indexed_paths: dict[int, Path] = {}
    if directory.exists():
        for path in directory.glob("attempt-*.json"):
            match = re.fullmatch(r"attempt-(\d+)\.json", path.name)
            if match is None:
                raise RunStoreError("trusted_evaluation_corrupt")
            index = int(match.group(1))
            if index > 2 or index in indexed_paths:
                raise RunStoreError("trusted_evaluation_corrupt")
            indexed_paths[index] = path

    if indexed_paths and sorted(indexed_paths) != list(range(max(indexed_paths) + 1)):
        raise RunStoreError("trusted_attempt_gap")

    receipts: list[dict[str, Any]] = []
    for attempt_index in sorted(indexed_paths):
        path = indexed_paths[attempt_index]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError, json.JSONDecodeError) as exc:
            raise RunStoreError("trusted_evaluation_corrupt") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schemaVersion") not in {1, 2}
            or payload.get("runId") != bound_run.run_id
            or payload.get("attemptIndex") != attempt_index
            or not isinstance(payload.get("candidateId"), str)
            or not payload.get("candidateId")
        ):
            raise RunStoreError("trusted_evaluation_corrupt")
        try:
            models.TransientBuildStateRef.model_validate(payload.get("transientBuildState"))
            models.JudgeAdvisoryReport.model_validate(payload.get("judgeAdvisoryReport"))
        except ValidationError as exc:
            raise RunStoreError("trusted_evaluation_corrupt") from exc
        if payload.get("schemaVersion") == 2 and not _valid_hard_legality_audit(payload):
            raise RunStoreError("trusted_evaluation_corrupt")
        receipts.append(payload)

    latest_path = bound_run.trusted_evaluation_path
    if not receipts:
        if latest_path.exists():
            raise RunStoreError("trusted_evaluation_corrupt")
        return []
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError, json.JSONDecodeError) as exc:
        raise RunStoreError("trusted_evaluation_corrupt") from exc
    if latest != receipts[-1]:
        raise RunStoreError("trusted_latest_mismatch")
    return receipts


def write_trusted_evaluation(bound_run: BoundRun, payload: dict[str, Any]) -> int | None:
    existing = read_trusted_evaluations_strict(bound_run)
    attempt_index = len(existing)
    if attempt_index >= 3:
        raise RunStoreError("retry_limit_reached")
    schema_version = 2 if isinstance(payload.get("hardLegalityAudit"), dict) else 1
    receipt = {
        "schemaVersion": schema_version,
        "runId": bound_run.run_id,
        "attemptIndex": attempt_index,
        "candidateId": payload["candidateId"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "transientBuildState": payload["transientBuildState"],
        "judgeAdvisoryReport": payload["judgeAdvisoryReport"],
        **({"hardLegalityAudit": payload["hardLegalityAudit"]} if schema_version == 2 else {}),
    }
    attempt_path = bound_run.trusted_evaluations_dir / f"attempt-{attempt_index}.json"
    if attempt_path.exists() or not write_json_atomic(attempt_path, receipt):
        return None
    if not write_json_atomic(bound_run.trusted_evaluation_path, receipt):
        attempt_path.unlink(missing_ok=True)
        return None
    return attempt_index


def _valid_hard_legality_audit(receipt: dict[str, Any]) -> bool:
    audit = receipt.get("hardLegalityAudit")
    state = receipt.get("transientBuildState")
    if not isinstance(audit, dict) or not isinstance(state, dict):
        return False
    failures = audit.get("hardFailures")
    state_hash = audit.get("stateHash")
    if (
        audit.get("auditVersion") != "hard_legality_v1"
        or audit.get("status") not in {"passed", "blocked"}
        or not isinstance(audit.get("hardLegalityReady"), bool)
        or not isinstance(failures, list)
        or any(not isinstance(item, str) for item in failures)
        or not isinstance(state_hash, str)
        or state_hash != state.get("semanticStateHash")
        or not re.fullmatch(r"sha256:[A-Fa-f0-9]{64}", state_hash)
        or not isinstance(audit.get("validationRef"), str)
    ):
        return False
    return audit["hardLegalityReady"] is (not failures) and audit["status"] == (
        "passed" if not failures else "blocked"
    )


def write_artifact_selection(bound_run: BoundRun, payload: dict[str, Any]) -> bool:
    """Persist a raw-free receipt identifying the exact Judge attempt chosen for delivery."""

    if bound_run.artifact_selection_path.exists():
        return False
    receipt = {
        "schemaVersion": 1,
        "runId": bound_run.run_id,
        "artifactId": payload["artifactId"],
        "candidateId": payload["candidateId"],
        "selectedAttemptIndex": payload["selectedAttemptIndex"],
        "selectedEvaluationRef": payload["selectedEvaluationRef"],
        "selectionOutcome": payload["selectionOutcome"],
        "selectionReason": payload.get("selectionReason"),
        "laterFindingsScope": payload["laterFindingsScope"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "containsRawPob": False,
    }
    return write_json_atomic(bound_run.artifact_selection_path, receipt)


def read_artifact_selection(bound_run: BoundRun) -> dict[str, Any] | None:
    try:
        payload = json.loads(bound_run.artifact_selection_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    selected_index = payload.get("selectedAttemptIndex")
    selection_outcome = payload.get("selectionOutcome")
    selection_reason = payload.get("selectionReason")
    later_findings_scope = payload.get("laterFindingsScope")
    if (
        payload.get("schemaVersion") != 1
        or payload.get("runId") != bound_run.run_id
        or not isinstance(selected_index, int)
        or selected_index not in {0, 1, 2}
        or not isinstance(payload.get("artifactId"), str)
        or not payload["artifactId"].startswith("final-build:")
        or not isinstance(payload.get("candidateId"), str)
        or not payload["candidateId"]
        or payload.get("selectedEvaluationRef")
        != f"run:{bound_run.run_id}:attempt:{selected_index}"
        or selection_outcome
        not in {
            "latest_passing_attempt_selected",
            "earlier_passing_baseline_selected",
            "baseline_restored_after_regression",
        }
        or later_findings_scope not in {"not_applicable", "candidate_delta_only"}
        or (
            selection_reason is not None
            and (
                not isinstance(selection_reason, str)
                or not selection_reason.strip()
                or len(selection_reason) > 500
                or "://" in selection_reason
            )
        )
        or (
            selection_outcome
            in {"earlier_passing_baseline_selected", "baseline_restored_after_regression"}
            and (
                later_findings_scope != "candidate_delta_only"
                or not isinstance(selection_reason, str)
                or not selection_reason.strip()
            )
        )
        or payload.get("containsRawPob") is not False
    ):
        return None
    return payload


def write_json_atomic(path: Path, payload: dict[str, Any]) -> bool:
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def canonical_run_id(value: str) -> str | None:
    try:
        canonical = str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        return None
    return canonical if canonical == value else None


def run_expired(started_at: str) -> bool:
    try:
        started = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return True
    if started.tzinfo is None:
        return True
    age = datetime.now(timezone.utc) - started.astimezone(timezone.utc)
    return age < timedelta(0) or age > RUN_TTL
