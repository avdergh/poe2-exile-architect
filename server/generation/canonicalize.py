"""Canonical Agent-output assembly from safe design fields and trusted run receipts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from . import models


def canonicalize_agent_output(
    payload: dict[str, Any],
    trusted_receipts: list[dict[str, Any]],
    artifact_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fill omitted trusted fields without expanding the receipt trust boundary."""
    if not trusted_receipts:
        return models.rejected("missing_trusted_evaluation")

    output = deepcopy(payload)
    if _alias_conflict(output, "generationAttempts", "generation_attempts"):
        return models.rejected("invalid_schema", caveats=["generationAttempts alias conflict"])
    attempts_value = _alias_value(output, "generationAttempts", "generation_attempts")
    if attempts_value is None:
        attempts_value = []
    if not isinstance(attempts_value, list):
        return models.rejected("invalid_schema", caveats=["generationAttempts must be a list"])

    attempts = deepcopy(attempts_value)
    if not attempts:
        if len(trusted_receipts) > 1:
            return models.rejected("missing_generation_attempts")
        top_candidate = _alias_value(output, "prototypeBuildCandidate", "prototype_build_candidate")
        top_audit = _alias_value(output, "failureAudit", "failure_audit")
        if top_candidate is not None and top_audit is not None:
            attempts = [
                {
                    "attemptIndex": 0,
                    "prototypeBuildCandidate": deepcopy(top_candidate),
                    "failureAudit": deepcopy(top_audit),
                }
            ]

    if attempts and len(attempts) != len(trusted_receipts):
        return models.rejected("trusted_attempt_count_mismatch")
    if len(trusted_receipts) > 1 and artifact_selection is None:
        return models.rejected("missing_artifact_selection")

    canonical_attempts: list[dict[str, Any]] = []
    for expected_index, (attempt, receipt) in enumerate(zip(attempts, trusted_receipts)):
        if not isinstance(attempt, dict):
            return models.rejected("invalid_schema", caveats=["generation attempt must be object"])
        if any(
            _alias_conflict(attempt, camel, snake)
            for camel, snake in (
                ("prototypeBuildCandidate", "prototype_build_candidate"),
                ("failureAudit", "failure_audit"),
                ("transientBuildState", "transient_build_state"),
                ("judgeAdvisoryReport", "judge_advisory_report"),
            )
        ):
            return models.rejected("invalid_schema", caveats=["generation attempt alias conflict"])
        index = _alias_value(attempt, "attemptIndex", "attempt_index")
        if index != expected_index or receipt.get("attemptIndex") != expected_index:
            return models.rejected("trusted_evaluation_mismatch")
        candidate = _alias_value(attempt, "prototypeBuildCandidate", "prototype_build_candidate")
        audit = _alias_value(attempt, "failureAudit", "failure_audit")
        if not isinstance(candidate, dict) or not isinstance(audit, dict):
            return models.rejected("invalid_schema", caveats=["compact attempt fields missing"])
        candidate_id = _alias_value(candidate, "candidateId", "candidate_id")
        if candidate_id != receipt.get("candidateId"):
            return models.rejected("trusted_evaluation_mismatch")

        canonical_attempt = {
            "attemptIndex": expected_index,
            "prototypeBuildCandidate": _canonical_attempt_candidate(candidate, candidate_id),
            "failureAudit": deepcopy(audit),
        }
        state_error = _fill_or_match_trusted(
            attempt,
            canonical_attempt,
            "transientBuildState",
            "transient_build_state",
            receipt.get("transientBuildState"),
            models.TransientBuildStateRef,
        )
        if state_error is not None:
            return state_error
        judge_error = _fill_or_match_trusted(
            attempt,
            canonical_attempt,
            "judgeAdvisoryReport",
            "judge_advisory_report",
            receipt.get("judgeAdvisoryReport"),
            models.JudgeAdvisoryReport,
        )
        if judge_error is not None:
            return judge_error
        canonical_attempts.append(canonical_attempt)

    if artifact_selection is not None:
        selected_value = artifact_selection.get("selectedAttemptIndex")
        if not isinstance(selected_value, int) or isinstance(selected_value, bool):
            return models.rejected("artifact_selection_receipt_mismatch")
        selected_index = selected_value
    else:
        selected_index = len(trusted_receipts) - 1
    if selected_index < 0 or selected_index >= len(trusted_receipts):
        return models.rejected("artifact_selection_receipt_mismatch")
    selected_receipt = trusted_receipts[selected_index]
    if artifact_selection is not None and (
        artifact_selection.get("candidateId") != selected_receipt.get("candidateId")
        or artifact_selection.get("selectedEvaluationRef")
        != f"run:{artifact_selection.get('runId')}:attempt:{selected_index}"
    ):
        return models.rejected("artifact_selection_receipt_mismatch")
    selected_attempt = canonical_attempts[selected_index] if canonical_attempts else None
    top_candidate = _alias_value(output, "prototypeBuildCandidate", "prototype_build_candidate")
    top_audit = _alias_value(output, "failureAudit", "failure_audit")
    if selected_attempt is not None:
        final_candidate = selected_attempt["prototypeBuildCandidate"]
        final_audit = selected_attempt["failureAudit"]
        if top_candidate is None:
            top_candidate = deepcopy(final_candidate)
        elif _alias_value(top_candidate, "candidateId", "candidate_id") != _alias_value(
            final_candidate,
            "candidateId",
            "candidate_id",
        ):
            return models.rejected("selected_attempt_mismatch")
        if artifact_selection is not None and selected_index != len(trusted_receipts) - 1:
            if top_audit is None:
                return models.rejected("baseline_acceptance_audit_required")
        elif top_audit is None:
            top_audit = deepcopy(final_audit)
        elif not _models_equal(top_audit, final_audit, models.FailureAuditSummary):
            return models.rejected("final_attempt_mismatch")

    if not isinstance(top_candidate, dict):
        return models.rejected("invalid_schema", caveats=["prototypeBuildCandidate is required"])
    if _alias_value(top_candidate, "candidateId", "candidate_id") != selected_receipt.get(
        "candidateId"
    ):
        return models.rejected("trusted_evaluation_mismatch")

    _replace_alias(output, "prototypeBuildCandidate", "prototype_build_candidate", top_candidate)
    if top_audit is not None:
        _replace_alias(output, "failureAudit", "failure_audit", top_audit)
    if canonical_attempts:
        _replace_alias(output, "generationAttempts", "generation_attempts", canonical_attempts)
    output["selectedAttemptIndex"] = selected_index
    output["artifactSelectionOutcome"] = (
        artifact_selection.get("selectionOutcome")
        if artifact_selection is not None
        else "latest_passing_attempt_selected"
    )

    state_error = _fill_or_match_trusted(
        payload,
        output,
        "transientBuildState",
        "transient_build_state",
        selected_receipt.get("transientBuildState"),
        models.TransientBuildStateRef,
    )
    if state_error is not None:
        return state_error
    judge_error = _fill_or_match_trusted(
        payload,
        output,
        "judgeAdvisoryReport",
        "judge_advisory_report",
        selected_receipt.get("judgeAdvisoryReport"),
        models.JudgeAdvisoryReport,
    )
    if judge_error is not None:
        return judge_error

    return {"status": "accepted", "payload": output}


def _canonical_attempt_candidate(candidate: dict[str, Any], candidate_id: Any) -> dict[str, Any]:
    """Keep complete legacy candidates, otherwise reduce an attempt to its trusted identity."""

    try:
        models.PrototypeBuildCandidate.model_validate(candidate)
    except ValidationError:
        return {"candidateId": candidate_id}
    return deepcopy(candidate)


def _fill_or_match_trusted(
    submitted: dict[str, Any],
    target: dict[str, Any],
    camel: str,
    snake: str,
    trusted: Any,
    model_type: type[models.StrictModel],
) -> dict[str, Any] | None:
    if not isinstance(trusted, dict):
        return models.rejected("trusted_evaluation_corrupt")
    if _alias_conflict(submitted, camel, snake):
        return models.rejected("invalid_schema", caveats=[f"{camel} alias conflict"])
    explicit = _alias_value(submitted, camel, snake)
    if explicit is not None and not _models_equal(explicit, trusted, model_type):
        return models.rejected("trusted_evaluation_mismatch")
    _replace_alias(target, camel, snake, deepcopy(trusted))
    return None


def _models_equal(left: Any, right: Any, model_type: type[models.StrictModel]) -> bool:
    try:
        left_model = model_type.model_validate(left)
        right_model = model_type.model_validate(right)
    except ValidationError:
        return False
    return left_model.model_dump() == right_model.model_dump()


def _alias_value(payload: dict[str, Any], camel: str, snake: str) -> Any:
    camel_present = camel in payload
    snake_present = snake in payload
    if camel_present and snake_present and payload[camel] != payload[snake]:
        return None
    if camel_present:
        return payload[camel]
    return payload.get(snake)


def _alias_conflict(payload: dict[str, Any], camel: str, snake: str) -> bool:
    return camel in payload and snake in payload and payload[camel] != payload[snake]


def _replace_alias(
    payload: dict[str, Any],
    camel: str,
    snake: str,
    value: Any,
) -> None:
    payload.pop(camel, None)
    payload.pop(snake, None)
    payload[camel] = value
