"""Phase 5 Agent-led prototype helper CLI."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
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

from server.generation import canonicalize, models, prototype, retry, run_store  # noqa: E402


RUN_TTL = timedelta(hours=2)


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
        "agentOutputFile": str(run_dir / "agent-output.json"),
        "experimentContext": {
            "memoryMode": args.memory_mode,
            "maxRetryCount": 2,
        },
    }
    manifest_path = run_dir / "run-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    output_template = {
        "schemaVersion": 2,
        "runContext": run_context,
        "packetId": manifest["packetId"],
        "agentRefinedBuildPrompt": {
            "promptId": manifest["promptId"],
            "requestRef": manifest["requestRef"],
        },
        "generationAttempts": [],
    }
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
        "reviewResultFile": str(run_dir / "review-result.json"),
        "experimentContext": manifest["experimentContext"],
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
    if _run_expired(manifest["startedAt"]):
        return models.rejected("run_expired")

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
    canonical = canonicalize.canonicalize_agent_output(data, trusted_receipts)
    if canonical.get("status") != "accepted":
        return canonical

    canonical_payload = canonical["payload"]
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
        "noRawMaterial": True,
        "noHiddenChainOfThought": True,
    }
    return compact


def _runs_dir() -> Path:
    override = os.environ.get("POE_BD_CREATE_RUNS_DIR")
    return Path(override).resolve() if override else (ROOT / ".poe-bd-create" / "runs").resolve()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> bool:
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except OSError:
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


def _run_expired(started_at: str) -> bool:
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return True
    if started.tzinfo is None:
        return True
    age = datetime.now(timezone.utc) - started.astimezone(timezone.utc)
    return age < timedelta(0) or age > RUN_TTL


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
