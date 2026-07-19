"""Safe P5.2 retry and memory-lane comparison helpers."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from . import models


def validate_and_build_retry_report(
    human_review_packet: dict[str, Any],
    manifest: dict[str, Any],
    trusted_receipts: list[dict[str, Any]],
    *,
    run_id: str,
) -> dict[str, Any]:
    try:
        experiment = models.GenerationExperimentContext.model_validate(
            manifest.get("experimentContext")
        )
        packet = models.HumanReviewPacket.model_validate(human_review_packet)
    except ValidationError as exc:
        return models.schema_error(exc)

    attempts = packet.generation_attempts
    if experiment.memory_mode == "standard" and not attempts:
        if len(trusted_receipts) > 1:
            return models.rejected("missing_generation_attempts")
        return {
            "status": "accepted",
            "experimentContext": experiment.model_dump(by_alias=True),
            "retryComparisonReport": None,
        }
    if not attempts:
        return models.rejected("missing_generation_attempts")
    if len(attempts) != len(trusted_receipts):
        return models.rejected("trusted_attempt_count_mismatch")

    for attempt, receipt in zip(attempts, trusted_receipts, strict=True):
        if attempt.attempt_index != receipt.get("attemptIndex"):
            return models.rejected("trusted_evaluation_mismatch")
        if attempt.prototype_build_candidate.candidate_id != receipt.get("candidateId"):
            return models.rejected("trusted_evaluation_mismatch")
        try:
            trusted_state = models.TransientBuildStateRef.model_validate(
                receipt.get("transientBuildState")
            )
            trusted_judge = models.JudgeAdvisoryReport.model_validate(
                receipt.get("judgeAdvisoryReport")
            )
        except ValidationError:
            return models.rejected("trusted_evaluation_mismatch")
        if attempt.transient_build_state.model_dump() != trusted_state.model_dump():
            return models.rejected("trusted_evaluation_mismatch")
        if attempt.judge_advisory_report.model_dump() != trusted_judge.model_dump():
            return models.rejected("trusted_evaluation_mismatch")
        memory_error = _memory_mode_error(
            attempt.prototype_build_candidate,
            experiment.memory_mode,
        )
        if memory_error is not None:
            return memory_error

    if experiment.memory_mode == "memory_assisted":
        requery_error = _memory_requery_error(attempts)
        if requery_error is not None:
            return requery_error

    report = _build_retry_report(run_id, experiment, attempts)
    return {
        "status": "accepted",
        "experimentContext": experiment.model_dump(by_alias=True),
        "retryComparisonReport": report.model_dump(by_alias=True),
    }


def _memory_mode_error(
    candidate: models.PrototypeBuildCandidate,
    memory_mode: str,
) -> dict[str, Any] | None:
    memory_tools = [
        reference
        for reference in candidate.tool_references
        if reference.tool_name.casefold().endswith("query_research_memory")
    ]
    memory_ref = candidate.version_context.research_memory_ref.casefold()
    if memory_mode == "no_memory":
        if candidate.memory_references or memory_tools or candidate.research_memory_use is not None:
            return models.rejected("no_memory_lane_used_research_memory")
        if memory_ref != "disabled:no_memory_baseline":
            return models.rejected("invalid_no_memory_version_context")
    elif memory_mode == "memory_assisted":
        if (
            not candidate.memory_references
            or not memory_tools
            or candidate.research_memory_use is None
        ):
            return models.rejected("memory_assisted_lane_missing_memory_evidence")
        if memory_ref.startswith(("disabled:", "unavailable", "unknown")):
            return models.rejected("invalid_memory_assisted_version_context")
    return None


def _memory_requery_error(
    attempts: list[models.GenerationAttemptRecord],
) -> dict[str, Any] | None:
    for previous, current in zip(attempts, attempts[1:], strict=False):
        changed_fields = _changed_research_identity_fields(previous, current)
        if not changed_fields:
            continue
        previous_usage = previous.prototype_build_candidate.research_memory_use
        current_usage = current.prototype_build_candidate.research_memory_use
        if previous_usage is None or current_usage is None:
            return models.rejected(
                "research_memory_requery_required",
                caveats=[f"Changed identity fields: {', '.join(changed_fields)}."],
            )
        fresh_refs = set(current_usage.dedupe_query_refs) - set(previous_usage.dedupe_query_refs)
        current_ref = current.prototype_build_candidate.version_context.research_memory_ref
        if not fresh_refs or current_ref not in fresh_refs:
            return models.rejected(
                "research_memory_requery_required",
                caveats=[f"Changed identity fields: {', '.join(changed_fields)}."],
            )
    return None


def _changed_research_identity_fields(
    previous: models.GenerationAttemptRecord,
    current: models.GenerationAttemptRecord,
) -> list[str]:
    previous_identity = _attempt_research_identity(previous)
    current_identity = _attempt_research_identity(current)
    changed: list[str] = []
    for field in ("ascendancy", "primary_skill"):
        previous_value = previous_identity[field]
        current_value = current_identity[field]
        if previous_value and current_value and previous_value != current_value:
            changed.append(field)
    return changed


def _attempt_research_identity(
    attempt: models.GenerationAttemptRecord,
) -> dict[str, str]:
    summary = attempt.transient_build_state.safe_summary
    ascendancy = _safe_summary_value(summary, "ascendancy")
    primary_skill = _safe_summary_value(summary, "mainSkill", "main_skill")
    if not primary_skill and attempt.judge_advisory_report.selected_skill is not None:
        primary_skill = attempt.judge_advisory_report.selected_skill.skill_name
    if not primary_skill and attempt.transient_build_state.tested_skill_groups:
        primary_skill = attempt.transient_build_state.tested_skill_groups[0].active_skill
    return {
        "ascendancy": _normalize_identity_value(ascendancy),
        "primary_skill": _normalize_identity_value(primary_skill),
    }


def _safe_summary_value(summary: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(summary.get(key) or "").strip()
        if value:
            return value
    return ""


def _normalize_identity_value(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _build_retry_report(
    run_id: str,
    experiment: models.GenerationExperimentContext,
    attempts: list[models.GenerationAttemptRecord],
) -> models.RetryComparisonReport:
    summaries = [
        models.RetryAttemptSummary(
            run_id=run_id,
            candidate_id=attempt.prototype_build_candidate.candidate_id,
            attempt_index=attempt.attempt_index,
            snapshot_id=str(attempt.transient_build_state.snapshot_id),
            source_hash=str(attempt.transient_build_state.source_hash),
            judge_status=attempt.judge_advisory_report.status,
            passed=attempt.judge_advisory_report.passed,
            aggregate_score=attempt.judge_advisory_report.aggregate_score,
            hard_failures=attempt.judge_advisory_report.hard_failures,
            caveats=attempt.judge_advisory_report.caveats,
            failure_audit=attempt.failure_audit,
            version_context=attempt.judge_advisory_report.version_context,
            no_raw_material=True,
        )
        for attempt in attempts
    ]
    first = summaries[0]
    final = summaries[-1]
    score_delta = None
    if first.aggregate_score is not None and final.aggregate_score is not None:
        score_delta = final.aggregate_score - first.aggregate_score
    resolved = sorted(set(first.hard_failures) - set(final.hard_failures))
    introduced = sorted(set(final.hard_failures) - set(first.hard_failures))
    outcome = _programmatic_outcome(summaries, score_delta, resolved, introduced)
    return models.RetryComparisonReport(
        report_id=f"retry-comparison:{run_id}",
        experiment_context=experiment,
        attempts=summaries,
        score_delta=score_delta,
        resolved_hard_failures=resolved,
        introduced_hard_failures=introduced,
        programmatic_outcome=outcome,
        human_review_fields={
            "failureAuditReasonable": "pending",
            "retryChangesRelevant": "pending",
            "qualityActuallyImproved": "pending",
            "stopReasonReasonable": "pending",
        },
        no_raw_material=True,
    )


def _programmatic_outcome(
    attempts: list[models.RetryAttemptSummary],
    score_delta: float | None,
    resolved: list[str],
    introduced: list[str],
) -> str:
    if len(attempts) == 1:
        return (
            "initial_accepted"
            if attempts[0].failure_audit.retry_decision == "accept"
            else "stopped_with_reason"
        )
    first = attempts[0]
    final = attempts[-1]
    if introduced or (score_delta is not None and score_delta < 0):
        return "regressed"
    if first.judge_status != "evaluated" and final.judge_status == "evaluated":
        return "evaluability_improved"
    if resolved:
        return "legality_improved"
    if score_delta is not None and score_delta > 0:
        return "score_improved"
    if final.failure_audit.retry_decision == "stop":
        return "stopped_with_reason"
    if score_delta is None and first.judge_status != final.judge_status:
        return "mixed"
    return "no_measurable_improvement"
