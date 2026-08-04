"""P5.1 Agent-led prototype review packet builder."""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from . import models


def validate_and_build_human_review_packet(
    payload: Any,
    *,
    trusted_evaluation: bool = False,
) -> dict[str, Any]:
    safety = models.validate_no_raw_or_hidden_reasoning(payload)
    if safety["status"] != "accepted":
        return safety
    try:
        prompt = models.AgentRefinedBuildPrompt.model_validate(
            _pick(payload, "agentRefinedBuildPrompt")
        )
        candidate = models.PrototypeBuildCandidate.model_validate(
            _pick(payload, "prototypeBuildCandidate")
        )
        state = models.TransientBuildStateRef.model_validate(_pick(payload, "transientBuildState"))
        judge = models.JudgeAdvisoryReport.model_validate(_pick(payload, "judgeAdvisoryReport"))
        feedback_payload = _pick(payload, "toolFeedbackEvents", default=[])
        if not isinstance(feedback_payload, list):
            return models.rejected("invalid_schema")
        feedback = [models.ToolFeedbackEvent.model_validate(item) for item in feedback_payload]
        audit_payload = _optional_pick(payload, "failureAudit")
        failure_audit = (
            models.FailureAuditSummary.model_validate(audit_payload)
            if audit_payload is not None
            else None
        )
        attempts_payload = _pick(payload, "generationAttempts", default=[])
        if not isinstance(attempts_payload, list):
            return models.rejected("invalid_schema")
        generation_attempts = [
            models.GenerationAttemptRecord.model_validate(item) for item in attempts_payload
        ]
        selected_attempt_index = _optional_int(
            payload,
            "selectedAttemptIndex",
            "selected_attempt_index",
        )
        artifact_selection_outcome = _optional_string(
            payload,
            "artifactSelectionOutcome",
            "artifact_selection_outcome",
        )
    except ValidationError as exc:
        return models.schema_error(exc)
    except KeyError as exc:
        return models.rejected("invalid_schema", caveats=[str(exc)])
    except ValueError as exc:
        return models.rejected("invalid_schema", caveats=[str(exc)])

    domain_error = _domain_acceptance_error(candidate, state, judge)
    if domain_error is not None:
        return domain_error

    action = _recommended_action(state, judge, trusted_evaluation=trusted_evaluation)
    try:
        packet = models.HumanReviewPacket(
            packet_id=_string(payload, "packet_id")
            or _string(payload, "packetId")
            or (f"human-review:{candidate.candidate_id}"),
            agent_refined_build_prompt=prompt,
            prototype_build_candidate=candidate,
            transient_build_state=state,
            judge_advisory_report=judge,
            tool_feedback_events=feedback,
            failure_audit=failure_audit,
            generation_attempts=generation_attempts,
            selected_attempt_index=selected_attempt_index,
            artifact_selection_outcome=artifact_selection_outcome,
            lifecycle_evidence_coverage=_lifecycle_evidence_coverage(candidate, state),
            human_review_fields=_human_review_fields(judge.feedback_mode),
            recommended_next_action=action,
            version_context=prompt.version_context,
            no_raw_material=True,
            no_hidden_chain_of_thought=True,
        )
    except ValidationError as exc:
        return models.schema_error(exc)
    packet_safety = models.validate_no_raw_or_hidden_reasoning(packet)
    if packet_safety["status"] != "accepted":
        return packet_safety
    return {
        "status": "accepted",
        "humanReviewPacket": _camelize_public_dict(packet.model_dump()),
        "noRawMaterial": True,
        "noHiddenChainOfThought": True,
    }


def _domain_acceptance_error(
    candidate: models.PrototypeBuildCandidate,
    state: models.TransientBuildStateRef,
    judge: models.JudgeAdvisoryReport,
) -> dict[str, Any] | None:
    if not candidate.tool_references and not candidate.memory_references:
        return models.rejected("missing_evidence_references")
    if not any(
        reference.tool_name.casefold().endswith("get_freshness_report")
        for reference in candidate.tool_references
    ):
        return models.rejected("missing_freshness_probe")
    if _has_explicit_class_change_plan(candidate):
        return models.rejected("invalid_class_lifecycle_contract")
    if state.status != "available" and not state.missing_reasons:
        if state.status == "missing" and judge.status == "not_evaluated":
            return models.rejected("missing_not_evaluated_reason")
        return models.rejected("missing_transient_state_reason")
    if state.status != "available" and judge.status == "evaluated":
        return models.rejected("judge_evaluated_without_transient_state")
    if judge.status == "evaluated" and (
        judge.evaluated_snapshot_id != state.snapshot_id
        or judge.evaluated_source_hash != state.source_hash
    ):
        return models.rejected("judge_state_mismatch")
    return None


def _has_explicit_class_change_plan(candidate: models.PrototypeBuildCandidate) -> bool:
    text = "\n".join(
        [
            candidate.class_shell,
            *candidate.transition_gates,
            *candidate.unresolved_caveats,
            candidate.rationale_summary,
        ]
    ).casefold()
    sentences = re.split(r"[\n。！？.!?;；]+", text)
    negative_markers = (
        "不能",
        "不可",
        "不允许",
        "不會",
        "不会",
        "不換",
        "不换",
        "无法",
        "無法",
        "唯一硬锁",
        "唯一硬鎖",
        "职业锁",
        "職業鎖",
        "class lock",
        "class is locked",
        "cannot",
        "can't",
        "do not",
        "don't",
        "must not",
        "no class change",
    )
    explicit_patterns = (
        r"(?:换|換|更换|更換|改换|改換|转|轉)(?:个|一個|一个)?职业",
        r"职业.{0,6}(?:换成|換成|改为|改為|转为|轉為)",
        r"(?:switch|change|reroll)(?:\s+(?:the|to|into|a|an|another))*\s+class\b",
        r"\bclass\s+(?:switch|change|reroll)\b",
    )
    for sentence in sentences:
        if any(marker in sentence for marker in negative_markers):
            continue
        if any(re.search(pattern, sentence) for pattern in explicit_patterns):
            return True
    return False


def _recommended_action(
    state: models.TransientBuildStateRef,
    judge: models.JudgeAdvisoryReport,
    *,
    trusted_evaluation: bool,
) -> str:
    if judge.hard_failures:
        return "blocked_by_hard_failure"
    if trusted_evaluation and judge.status == "evaluated":
        return "ready_for_human_review"
    return "human_review_required"


def _human_review_fields(feedback_mode: str) -> dict[str, str]:
    if feedback_mode == "hard_only":
        return {
            "briefFit": "pending",
            "designValue": "pending",
            "stageFit": "pending",
            "evidenceQuality": "pending",
            "hardLegalityEvidenceReasonable": "pending",
            "continueToNextPrototypeStep": "pending",
        }
    return {
        "briefFit": "pending",
        "designValue": "pending",
        "stageFit": "pending",
        "evidenceQuality": "pending",
        "judgeCaveatReasonable": "pending",
        "continueToNextPrototypeStep": "pending",
    }


def _lifecycle_evidence_coverage(
    candidate: models.PrototypeBuildCandidate,
    state: models.TransientBuildStateRef,
) -> models.LifecycleEvidenceCoverage:
    evaluated_level = _positive_level(state.safe_summary.get("level"))
    evaluated_stage = _stage_for_level(evaluated_level) if evaluated_level is not None else None
    evaluated_stages = [evaluated_stage] if state.status == "available" and evaluated_stage else []
    text_only_stages = [
        stage for stage in candidate.current_output_stages if stage not in evaluated_stages
    ]
    complete = bool(evaluated_stages) and not text_only_stages
    return models.LifecycleEvidenceCoverage(
        coverage_status="complete" if complete else "partial",
        evaluated_stages=evaluated_stages,
        text_only_stages=text_only_stages,
        evaluated_level=evaluated_level,
        source_snapshot_id=state.snapshot_id if state.status == "available" else None,
    )


def _positive_level(value: Any) -> int | None:
    try:
        level = int(str(value))
    except (TypeError, ValueError):
        return None
    return level if level > 0 else None


def _stage_for_level(level: int) -> str:
    if level <= 25:
        return "campaign_early"
    if level <= 45:
        return "campaign_mid"
    if level < 65:
        return "campaign_late"
    # Phase 8 uses stage readiness rather than a price or generic level band as the
    # transition clock.  In particular, a level-80 target remains maps_entry unless
    # its endgame mechanism is independently closed and verified.
    if level < 82:
        return "maps_entry"
    if level < 92:
        return "endgame_budget"
    return "endgame_final"


def _pick(payload: Any, key: str, *, default: Any = None) -> Any:
    if not isinstance(payload, dict):
        raise KeyError(key)
    if key in payload:
        return payload[key]
    snake = _camel_to_snake(key)
    if snake in payload:
        return payload[snake]
    if default is not None:
        return default
    raise KeyError(key)


def _optional_pick(payload: Any, key: str) -> Any:
    if not isinstance(payload, dict):
        raise KeyError(key)
    if key in payload:
        return payload[key]
    return payload.get(_camel_to_snake(key))


def _string(payload: Any, key: str) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get(key), str):
        return payload[key]
    return None


def _optional_int(payload: Any, camel: str, snake: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    if camel in payload and snake in payload and payload[camel] != payload[snake]:
        raise ValueError(f"{camel} alias conflict")
    value = payload[camel] if camel in payload else payload.get(snake)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_string(payload: Any, camel: str, snake: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    if camel in payload and snake in payload and payload[camel] != payload[snake]:
        raise ValueError(f"{camel} alias conflict")
    value = payload[camel] if camel in payload else payload.get(snake)
    return value if isinstance(value, str) else None


def _camelize_public_dict(value: Any, *, preserve_keys: bool = False) -> Any:
    if isinstance(value, list):
        return [_camelize_public_dict(item, preserve_keys=preserve_keys) for item in value]
    if not isinstance(value, dict):
        return value
    if preserve_keys:
        return value
    output: dict[str, Any] = {}
    for key, child in value.items():
        key_text = str(key)
        output[_snake_to_camel(key_text)] = _camelize_public_dict(
            child,
            preserve_keys=key_text in {"field_sources", "human_review_fields", "safe_summary"},
        )
    return output


def _snake_to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _camel_to_snake(value: str) -> str:
    output: list[str] = []
    for index, char in enumerate(value):
        if char.isupper() and index > 0:
            output.append("_")
        output.append(char.lower())
    return "".join(output)
