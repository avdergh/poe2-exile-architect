"""Phase 5 Agent-led prototype artifact contracts."""

from __future__ import annotations

import re
import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from server.knowledge import copy_safety


FIELD_SOURCE = Literal["user_explicit", "agent_inferred", "defaulted", "unknown"]
MEMORY_MODE = Literal["standard", "no_memory", "memory_assisted"]
LIFECYCLE_STAGE = Literal[
    "campaign_early",
    "campaign_mid",
    "campaign_late",
    "maps_entry",
    "endgame_budget",
    "endgame_final",
    # Legacy Phase 5 spellings remain accepted at the input boundary and are normalized below.
    "budget_endgame",
    "final_endgame",
]

LIFECYCLE_STAGE_ALIASES = {
    "budget_endgame": "endgame_budget",
    "final_endgame": "endgame_final",
}

HIDDEN_REASONING_FIELDS = {
    "hidden_chain_of_thought",
    "chain_of_thought",
    "raw_chain_of_thought",
    "reasoning_trace",
    "raw_reasoning_trace",
    "scratchpad",
    "raw_scratchpad",
    "transcript",
    "raw_transcript",
    "full_transcript",
    "conversation_transcript",
    "dialogue",
    "raw_dialogue",
    "conversation_dialogue",
    "user_prompt",
    "raw_user_prompt",
    "raw_prompt",
}


def _snake_to_camel_alias(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class StrictModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_snake_to_camel_alias,
        extra="forbid",
        populate_by_name=True,
        strict=True,
    )


class VersionContext(StrictModel):
    league: str = Field(min_length=1)
    ruleset: str = Field(min_length=1)
    game_patch: str = Field(min_length=1)
    passive_tree_version: str = Field(min_length=1)
    pob_version_or_commit: str = Field(min_length=1)
    graph_snapshot_id: str = Field(min_length=1)
    research_memory_ref: str = Field(min_length=1)


class VersionedSafeModel(StrictModel):
    version_context: VersionContext
    no_raw_material: bool = True

    @model_validator(mode="after")
    def _no_raw_flag_is_true(self) -> "VersionedSafeModel":
        if not self.no_raw_material:
            raise ValueError("no_raw_material must be true")
        return self


class GenerationExperimentContext(StrictModel):
    memory_mode: MEMORY_MODE = "standard"
    max_retry_count: Literal[2] = 2


class AgentRefinedBuildPrompt(VersionedSafeModel):
    prompt_id: str = Field(min_length=1)
    request_ref: str = Field(min_length=1)
    user_request_summary: str = Field(min_length=1)
    refined_prompt_summary: str = Field(min_length=1)
    current_output_stages: list[LIFECYCLE_STAGE] = Field(min_length=1)
    target_lifecycle_stages: list[LIFECYCLE_STAGE] = Field(min_length=1)
    cross_stage_locked_dimensions: list[Literal["class"]] = Field(default_factory=lambda: ["class"])
    field_sources: dict[str, FIELD_SOURCE] = Field(default_factory=dict)
    default_assumptions: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)

    @field_validator("current_output_stages", "target_lifecycle_stages", mode="before")
    @classmethod
    def _normalize_stage_names(cls, value: Any) -> Any:
        return normalize_lifecycle_stages(value)

    @model_validator(mode="after")
    def _stage_contract_is_valid(self) -> "AgentRefinedBuildPrompt":
        _require_stage_contract(self.current_output_stages, self.target_lifecycle_stages)
        _require_class_only_lock(self.cross_stage_locked_dimensions)
        self.field_sources = {
            _camel_to_snake_name(str(key)): value for key, value in self.field_sources.items()
        }
        required = {
            "user_request_summary",
            "refined_prompt_summary",
            "current_output_stages",
            "target_lifecycle_stages",
            "cross_stage_locked_dimensions",
        }
        missing = sorted(required - set(self.field_sources))
        if missing:
            raise ValueError(f"field_sources missing required fields: {', '.join(missing)}")
        return self


class ToolReference(StrictModel):
    tool_name: str = Field(min_length=1)
    query_ref: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class ResearchMemoryInsightDecision(StrictModel):
    source_refs: list[str] = Field(min_length=1, max_length=12)
    decision: Literal["adopted", "caveated", "rejected"]
    summary: str = Field(min_length=1, max_length=320)
    application: str = Field(min_length=1, max_length=320)


class ResearchMemoryUse(StrictModel):
    retrieval_outcome: Literal["matched", "no_matching_memory"]
    dedupe_query_refs: list[str] = Field(min_length=1, max_length=8)
    component_keys: list[str] = Field(default_factory=list, max_length=24)
    build_family_keys: list[str] = Field(default_factory=list, max_length=12)
    deep_record_ids: list[str] = Field(default_factory=list, max_length=24)
    pattern_ids: list[str] = Field(default_factory=list, max_length=24)
    semantic_edge_ids: list[str] = Field(default_factory=list, max_length=24)
    memory_item_ids: list[str] = Field(default_factory=list, max_length=24)
    insight_decisions: list[ResearchMemoryInsightDecision] = Field(
        default_factory=list,
        max_length=12,
    )
    no_match_reason: str | None = Field(default=None, min_length=1, max_length=320)

    @model_validator(mode="after")
    def _usage_is_traceable(self) -> "ResearchMemoryUse":
        list_fields = (
            "dedupe_query_refs",
            "component_keys",
            "build_family_keys",
            "deep_record_ids",
            "pattern_ids",
            "semantic_edge_ids",
            "memory_item_ids",
        )
        for field_name in list_fields:
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
        if any(not re.fullmatch(r"dq-[0-9a-f]{16}", ref) for ref in self.dedupe_query_refs):
            raise ValueError(
                "dedupe_query_refs must use query_research_memory dedupeQueryRef values"
            )

        source_refs = set(self.source_refs())
        if self.retrieval_outcome == "matched":
            if not source_refs:
                raise ValueError("matched research memory requires at least one recalled item")
            if not self.insight_decisions:
                raise ValueError("matched research memory requires an adoption decision")
            if self.no_match_reason is not None:
                raise ValueError("matched research memory cannot carry no_match_reason")
            for decision in self.insight_decisions:
                unknown = sorted(set(decision.source_refs) - source_refs)
                if unknown:
                    raise ValueError(
                        "insight decision references memory items absent from research_memory_use"
                    )
        else:
            if source_refs or self.insight_decisions:
                raise ValueError("no_matching_memory cannot carry recalled items or decisions")
            if not self.no_match_reason:
                raise ValueError("no_matching_memory requires no_match_reason")
        return self

    def source_refs(self) -> list[str]:
        return [
            *self.build_family_keys,
            *self.deep_record_ids,
            *self.pattern_ids,
            *self.semantic_edge_ids,
            *self.memory_item_ids,
        ]


class CompletenessAdvisoryDecision(StrictModel):
    advisory_code: str = Field(min_length=1)
    decision: Literal["deferred", "intentionally_unused"]
    reason: str = Field(min_length=1)


class PrototypeBuildCandidate(VersionedSafeModel):
    candidate_id: str = Field(min_length=1)
    prompt_ref: str = Field(min_length=1)
    current_output_stages: list[LIFECYCLE_STAGE] = Field(min_length=1)
    target_lifecycle_stages: list[LIFECYCLE_STAGE] = Field(min_length=1)
    cross_stage_locked_dimensions: list[Literal["class"]] = Field(default_factory=lambda: ["class"])
    class_shell: str = Field(min_length=1)
    primary_skill_intent: str = Field(min_length=1)
    secondary_skill_intents: list[str] = Field(default_factory=list)
    mechanic_axes: list[str] = Field(min_length=1)
    defense_layers: list[str] = Field(min_length=1)
    spirit_assumptions: list[str] = Field(default_factory=list)
    gear_roles: list[str] = Field(default_factory=list)
    passive_anchor_intents: list[str] = Field(default_factory=list)
    transition_gates: list[str] = Field(default_factory=list)
    unresolved_caveats: list[str] = Field(default_factory=list)
    completeness_advisory_decisions: list[CompletenessAdvisoryDecision] = Field(
        default_factory=list
    )
    tool_references: list[ToolReference] = Field(default_factory=list)
    memory_references: list[str] = Field(default_factory=list)
    research_memory_use: ResearchMemoryUse | None = None
    rationale_summary: str = Field(min_length=1)

    @field_validator("current_output_stages", "target_lifecycle_stages", mode="before")
    @classmethod
    def _normalize_stage_names(cls, value: Any) -> Any:
        return normalize_lifecycle_stages(value)

    @model_validator(mode="after")
    def _candidate_contract_is_valid(self) -> "PrototypeBuildCandidate":
        _require_stage_contract(self.current_output_stages, self.target_lifecycle_stages)
        _require_class_only_lock(self.cross_stage_locked_dimensions)
        advisory_codes = [item.advisory_code for item in self.completeness_advisory_decisions]
        if len(advisory_codes) != len(set(advisory_codes)):
            raise ValueError("completeness advisory decisions must not contain duplicates")
        if self.research_memory_use is not None:
            usage = self.research_memory_use
            memory_tool_refs = {
                reference.query_ref
                for reference in self.tool_references
                if reference.tool_name.casefold().endswith("query_research_memory")
            }
            if not set(usage.dedupe_query_refs).issubset(memory_tool_refs):
                raise ValueError(
                    "research_memory_use query refs must match query_research_memory tool references"
                )
            # This list is a denormalized review convenience. The typed usage object remains the
            # authority, so derive its complete trace set instead of asking the Agent to copy it.
            self.memory_references = _dedupe_strings(
                [*self.memory_references, *usage.dedupe_query_refs, *usage.source_refs()]
            )
            if self.version_context.research_memory_ref not in usage.dedupe_query_refs:
                raise ValueError(
                    "version_context research_memory_ref must identify a recorded memory query"
                )
        return self


class TestedSkillGroup(StrictModel):
    group_index: int | None = Field(default=None, ge=1)
    role: str = Field(min_length=1)
    active_skill: str = Field(min_length=1)
    active_skills: list[str] = Field(default_factory=list)
    active_skill_count: int | None = Field(default=None, ge=1)
    supports: list[str]
    enabled: bool

    @model_validator(mode="after")
    def _skill_group_diagnostics_are_consistent(self) -> "TestedSkillGroup":
        if not self.active_skills:
            self.active_skills = [self.active_skill]
        if self.active_skill not in self.active_skills:
            raise ValueError("active_skill must be present in active_skills")
        if self.active_skill_count is None:
            self.active_skill_count = len(self.active_skills)
        if self.active_skill_count != len(self.active_skills):
            raise ValueError("active_skill_count must match active_skills")
        return self


class JudgeSelectedSkillDiagnostic(StrictModel):
    skill_name: str = Field(min_length=1)
    group_index: int | None = Field(default=None, ge=1)
    active_skill_count: int | None = Field(default=None, ge=0)
    group_origin: str = Field(default="unknown", min_length=1)
    group_source: str | None = None
    socket_legality_applicable: bool = True
    scenario_limitations: list[str] = Field(default_factory=list)


class JudgeSupplementalSkillDiagnostic(StrictModel):
    skill_name: str = Field(min_length=1)
    group_index: int | None = Field(default=None, ge=1)
    group_origin: str = Field(min_length=1)
    scenario_limitations: list[str] = Field(default_factory=list)


class JudgeSkillGroupDiagnostic(StrictModel):
    group_index: int | None = Field(default=None, ge=1)
    active_skills: list[str] = Field(default_factory=list)
    active_skill_count: int = Field(ge=0)
    supports: list[str] = Field(default_factory=list)
    support_count: int = Field(ge=0)
    single_active_skill_valid: bool
    group_origin: str = Field(default="socketed", min_length=1)
    group_source: str | None = None
    selected_by_judge: bool = False


class AttributeShortfallDiagnostic(StrictModel):
    attribute: Literal["strength", "dexterity", "intelligence"]
    current: float = Field(ge=0.0)
    required: float = Field(ge=0.0)
    shortfall: float = Field(gt=0.0)


class TransientBuildStateRef(VersionedSafeModel):
    status: Literal["available", "missing", "error"]
    snapshot_id: str | None = None
    source_hash: str | None = None
    safe_summary: dict[str, str] = Field(default_factory=dict)
    tested_skill_groups: list[TestedSkillGroup] = Field(default_factory=list)
    completeness_advisories: list[str] = Field(default_factory=list)
    missing_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _state_ref_matches_status(self) -> "TransientBuildStateRef":
        if self.status == "available":
            if not self.snapshot_id or not self.source_hash:
                raise ValueError("available transient state requires snapshot_id and source_hash")
            if not self.tested_skill_groups:
                raise ValueError("available transient state requires tested_skill_groups")
        elif self.snapshot_id or self.source_hash or self.tested_skill_groups:
            raise ValueError(
                "missing or error transient state cannot carry snapshot, source hash, or tested skills"
            )
        return self


def _require_completeness_advisory_decisions(
    candidate: PrototypeBuildCandidate,
    state: TransientBuildStateRef,
) -> None:
    required = set(state.completeness_advisories)
    recorded = {decision.advisory_code for decision in candidate.completeness_advisory_decisions}
    missing = sorted(required - recorded)
    stale = sorted(recorded - required)
    if missing:
        raise ValueError(
            "candidate must record a decision and reason for each trusted completeness advisory: "
            + ", ".join(missing)
        )
    if stale:
        raise ValueError(
            "candidate carries completeness decisions absent from the trusted final snapshot: "
            + ", ".join(stale)
        )


class JudgeScoreDimension(StrictModel):
    value: float = Field(ge=0.0, le=1.0)
    blocked: bool = False


class JudgeScoreVector(StrictModel):
    offense: JudgeScoreDimension
    defense: JudgeScoreDimension
    recovery: JudgeScoreDimension
    mobility: JudgeScoreDimension


class JudgeOffenseEvidence(StrictModel):
    raw_dps: float = Field(ge=0.0)
    effective_dps: float = Field(ge=0.0)
    direct_dps: float = Field(default=0.0, ge=0.0)
    full_dps: float = Field(default=0.0, ge=0.0)
    source_metric: str = Field(min_length=1)
    evidence_level: Literal["strong", "limited", "none", "unknown"]
    metric_status: Literal["available", "unavailable"]
    observed_value: float = Field(ge=0.0, le=1.0)
    floor_progress: float = Field(ge=0.0, le=1.0)
    floor_status: Literal["met", "missed", "unverified", "unavailable"]
    delivery_evidence_status: Literal["established", "limited", "unavailable"]
    score_confidence_factor: float = Field(ge=0.0, le=1.0)
    score_policy: str = Field(min_length=1)


class JudgeAdvisoryReport(StrictModel):
    report_id: str = Field(min_length=1)
    status: Literal["evaluated", "not_evaluated", "error"]
    hard_failures: list[str] = Field(default_factory=list)
    playability_failures: list[str] = Field(default_factory=list)
    quality_warnings: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    aggregate_score: float | None = Field(default=None, ge=0.0, le=1.0)
    reward_strength: Literal["strong", "limited", "none", "unknown"] = "unknown"
    reward_limit_reasons: list[str] = Field(default_factory=list)
    evaluated_snapshot_id: str | None = None
    evaluated_source_hash: str | None = None
    passed: bool | None = None
    quality_band: str | None = None
    score_vector: JudgeScoreVector | None = None
    offense_evidence: JudgeOffenseEvidence | None = None
    modelability_status: str | None = None
    score_applicability: Literal["applicable", "unavailable", "unknown"] = "unknown"
    level_band: str | None = None
    evaluator_version: str | None = None
    final_classification: str | None = None
    selected_skill: JudgeSelectedSkillDiagnostic | None = None
    supplemental_skills: list[JudgeSupplementalSkillDiagnostic] = Field(default_factory=list)
    skill_group_diagnostics: list[JudgeSkillGroupDiagnostic] = Field(default_factory=list)
    attribute_shortfalls: list[AttributeShortfallDiagnostic] = Field(default_factory=list)
    error_code: (
        Literal[
            "judge_timeout",
            "judge_process_error",
            "judge_protocol_error",
            "judge_internal_error",
        ]
        | None
    ) = None
    version_context: VersionContext
    no_raw_material: bool = True

    @model_validator(mode="after")
    def _judge_report_is_safe(self) -> "JudgeAdvisoryReport":
        if not self.no_raw_material:
            raise ValueError("no_raw_material must be true")
        if self.reward_strength == "strong":
            raise ValueError("phase5 prototype judge report cannot carry strong reward_strength")
        if self.status == "evaluated":
            if self.error_code is not None:
                raise ValueError("evaluated judge report cannot carry error_code")
            if self.aggregate_score is None:
                raise ValueError("evaluated judge report requires aggregate_score")
            if not self.evaluated_snapshot_id or not self.evaluated_source_hash:
                raise ValueError(
                    "evaluated judge report requires evaluated_snapshot_id and "
                    "evaluated_source_hash"
                )
        else:
            if self.aggregate_score is not None:
                raise ValueError("unevaluated judge report cannot carry aggregate_score")
            if self.reward_strength != "unknown":
                raise ValueError("unevaluated judge report must use unknown reward_strength")
            if self.evaluated_snapshot_id or self.evaluated_source_hash:
                raise ValueError("unevaluated judge report cannot carry evaluated state refs")
            if any(
                value is not None
                for value in (
                    self.passed,
                    self.quality_band,
                    self.score_vector,
                    self.offense_evidence,
                    self.modelability_status,
                    None if self.score_applicability == "unknown" else self.score_applicability,
                    self.level_band,
                    self.evaluator_version,
                    self.final_classification,
                    self.selected_skill,
                )
            ):
                raise ValueError("unevaluated judge report cannot carry evaluation details")
            if (
                self.skill_group_diagnostics
                or self.attribute_shortfalls
                or self.supplemental_skills
            ):
                raise ValueError("unevaluated judge report cannot carry legality diagnostics")
            if self.status == "not_evaluated" and self.error_code is not None:
                raise ValueError("not_evaluated judge report cannot carry error_code")
            if self.status == "error":
                if self.error_code is None:
                    raise ValueError("error judge report requires error_code")
                if self.hard_failures:
                    raise ValueError("error judge report cannot carry build hard_failures")
                if self.playability_failures or self.quality_warnings:
                    raise ValueError("error judge report cannot carry build quality diagnostics")
        if self.status != "evaluated" and not self.caveats and not self.hard_failures:
            raise ValueError(
                "not evaluated or error judge report requires caveats or hard_failures"
            )
        return self


class ToolFeedbackEvent(StrictModel):
    event_id: str = Field(min_length=1)
    feedback_type: Literal[
        "judge_modelability_gap",
        "judge_offense_evidence_gap",
        "judge_score_review_required",
        "query_gap",
        "copy_safety_gap",
        "pob_state_gap",
        "tool_usability_gap",
    ]
    summary: str = Field(min_length=1)
    requires_human_or_test_review: bool = True
    version_context: VersionContext
    no_raw_material: bool = True

    @model_validator(mode="after")
    def _feedback_is_safe(self) -> "ToolFeedbackEvent":
        if not self.no_raw_material:
            raise ValueError("no_raw_material must be true")
        return self


class FailureAuditSummary(VersionedSafeModel):
    audit_id: str = Field(min_length=1)
    attempt_index: int = Field(ge=0, le=2)
    candidate_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    classification: Literal[
        "true_build_failure",
        "judge_modelability_gap",
        "judge_offense_evidence_gap",
        "judge_score_review_required",
        "selected_skill_suspect",
        "tool_or_data_gap",
        "mixed",
        "no_material_failure",
        "unknown",
    ]
    retry_decision: Literal["retry", "stop", "accept"]
    summary: str = Field(min_length=1)
    planned_changes: list[str] = Field(default_factory=list)
    retained_caveats: list[str] = Field(default_factory=list)
    stop_reason: str | None = None

    @model_validator(mode="after")
    def _decision_has_required_explanation(self) -> "FailureAuditSummary":
        if self.retry_decision == "retry":
            if not self.planned_changes:
                raise ValueError("retry decision requires planned_changes")
            if self.stop_reason is not None:
                raise ValueError("retry decision cannot carry stop_reason")
        elif self.retry_decision == "stop":
            if not self.stop_reason:
                raise ValueError("stop decision requires stop_reason")
        elif self.stop_reason is not None:
            raise ValueError("accept decision cannot carry stop_reason")
        return self


class GenerationAttemptRecord(StrictModel):
    attempt_index: int = Field(ge=0, le=2)
    prototype_build_candidate: PrototypeBuildCandidate
    transient_build_state: TransientBuildStateRef
    judge_advisory_report: JudgeAdvisoryReport
    failure_audit: FailureAuditSummary

    @model_validator(mode="after")
    def _attempt_refs_match(self) -> "GenerationAttemptRecord":
        candidate = self.prototype_build_candidate
        state = self.transient_build_state
        judge = self.judge_advisory_report
        audit = self.failure_audit
        if audit.attempt_index != self.attempt_index:
            raise ValueError("failure audit attempt_index must match attempt")
        if audit.candidate_id != candidate.candidate_id:
            raise ValueError("failure audit candidate_id must match attempt candidate")
        if audit.snapshot_id != state.snapshot_id:
            raise ValueError("failure audit snapshot_id must match attempt snapshot")
        if state.status != "available":
            raise ValueError("generation attempt requires an available transient state")
        _require_completeness_advisory_decisions(candidate, state)
        if judge.status == "evaluated":
            if judge.evaluated_snapshot_id != state.snapshot_id:
                raise ValueError("attempt Judge snapshot must match transient state")
            if judge.evaluated_source_hash != state.source_hash:
                raise ValueError("attempt Judge source hash must match transient state")
        if audit.retry_decision == "accept" and (
            judge.status != "evaluated" or judge.passed is not True or bool(judge.hard_failures)
        ):
            raise ValueError("attempt accept decision requires a passing Judge report")
        contexts = (
            candidate.version_context,
            state.version_context,
            judge.version_context,
            audit.version_context,
        )
        if any(not same_version(contexts[0], context) for context in contexts[1:]):
            raise ValueError("version_context mismatch inside generation attempt")
        return self


class LifecycleEvidenceCoverage(StrictModel):
    coverage_status: Literal["complete", "partial"]
    evaluated_stages: list[str] = Field(max_length=1)
    text_only_stages: list[str]
    evaluated_level: int | None = Field(default=None, ge=1)
    source_snapshot_id: str | None = None


class HumanReviewPacket(StrictModel):
    packet_id: str = Field(min_length=1)
    agent_refined_build_prompt: AgentRefinedBuildPrompt
    prototype_build_candidate: PrototypeBuildCandidate
    transient_build_state: TransientBuildStateRef
    judge_advisory_report: JudgeAdvisoryReport
    tool_feedback_events: list[ToolFeedbackEvent] = Field(default_factory=list)
    failure_audit: FailureAuditSummary | None = None
    generation_attempts: list[GenerationAttemptRecord] = Field(
        default_factory=list,
        max_length=3,
    )
    lifecycle_evidence_coverage: LifecycleEvidenceCoverage
    human_review_fields: dict[str, str] = Field(default_factory=dict)
    recommended_next_action: Literal[
        "ready_for_human_review",
        "human_review_required",
        "blocked_by_hard_failure",
    ]
    version_context: VersionContext
    no_raw_material: bool = True
    no_hidden_chain_of_thought: bool = True

    @model_validator(mode="after")
    def _packet_is_consistent(self) -> "HumanReviewPacket":
        if not self.no_raw_material:
            raise ValueError("no_raw_material must be true")
        if not self.no_hidden_chain_of_thought:
            raise ValueError("no_hidden_chain_of_thought must be true")
        contexts = [
            self.agent_refined_build_prompt.version_context,
            self.prototype_build_candidate.version_context,
            self.transient_build_state.version_context,
            self.judge_advisory_report.version_context,
            *(event.version_context for event in self.tool_feedback_events),
        ]
        if self.failure_audit is not None:
            contexts.append(self.failure_audit.version_context)
        for context in contexts:
            if not same_version(self.version_context, context):
                raise ValueError("version_context mismatch inside human review packet")
        if self.agent_refined_build_prompt.prompt_id != self.prototype_build_candidate.prompt_ref:
            raise ValueError("candidate prompt_ref must match prompt_id")
        _require_completeness_advisory_decisions(
            self.prototype_build_candidate,
            self.transient_build_state,
        )
        if (
            self.agent_refined_build_prompt.current_output_stages
            != self.prototype_build_candidate.current_output_stages
        ):
            raise ValueError("candidate current stages must match refined prompt")
        if (
            self.agent_refined_build_prompt.target_lifecycle_stages
            != self.prototype_build_candidate.target_lifecycle_stages
        ):
            raise ValueError("candidate lifecycle targets must match refined prompt")
        if self.failure_audit is not None:
            if self.failure_audit.candidate_id != self.prototype_build_candidate.candidate_id:
                raise ValueError("failure audit candidate_id must match candidate")
            if self.failure_audit.snapshot_id != self.transient_build_state.snapshot_id:
                raise ValueError("failure audit snapshot_id must match transient state")
            if self.failure_audit.retry_decision == "accept" and (
                self.judge_advisory_report.status != "evaluated"
                or self.judge_advisory_report.passed is not True
                or bool(self.judge_advisory_report.hard_failures)
            ):
                raise ValueError("accept decision requires a passing evaluated Judge report")
        if self.generation_attempts:
            indices = [attempt.attempt_index for attempt in self.generation_attempts]
            if indices != list(range(len(indices))):
                raise ValueError("generation attempts must be contiguous and ordered from zero")
            for attempt in self.generation_attempts[:-1]:
                if attempt.failure_audit.retry_decision != "retry":
                    raise ValueError("non-final generation attempt must choose retry")
            for attempt in self.generation_attempts:
                if not same_version(
                    self.version_context,
                    attempt.prototype_build_candidate.version_context,
                ):
                    raise ValueError("generation attempt version_context must match packet")
                if (
                    attempt.prototype_build_candidate.prompt_ref
                    != self.agent_refined_build_prompt.prompt_id
                ):
                    raise ValueError("generation attempt prompt_ref must match prompt_id")
            final_attempt = self.generation_attempts[-1]
            if final_attempt.failure_audit.retry_decision == "retry":
                raise ValueError("final generation attempt cannot choose retry")
            if (
                final_attempt.prototype_build_candidate.model_dump()
                != self.prototype_build_candidate.model_dump()
                or final_attempt.transient_build_state.model_dump()
                != self.transient_build_state.model_dump()
                or final_attempt.judge_advisory_report.model_dump()
                != self.judge_advisory_report.model_dump()
            ):
                raise ValueError("top-level candidate and evaluation must match final attempt")
        return self


class RetryAttemptSummary(StrictModel):
    run_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    attempt_index: int = Field(ge=0, le=2)
    snapshot_id: str = Field(min_length=1)
    source_hash: str = Field(min_length=1)
    judge_status: Literal["evaluated", "not_evaluated", "error"]
    passed: bool | None = None
    aggregate_score: float | None = Field(default=None, ge=0.0, le=1.0)
    hard_failures: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    failure_audit: FailureAuditSummary
    version_context: VersionContext
    no_raw_material: bool = True

    @model_validator(mode="after")
    def _attempt_is_safe(self) -> "RetryAttemptSummary":
        if not self.no_raw_material:
            raise ValueError("no_raw_material must be true")
        return self


class RetryComparisonReport(StrictModel):
    report_id: str = Field(min_length=1)
    experiment_context: GenerationExperimentContext
    attempts: list[RetryAttemptSummary] = Field(min_length=1, max_length=3)
    score_delta: float | None = None
    resolved_hard_failures: list[str] = Field(default_factory=list)
    introduced_hard_failures: list[str] = Field(default_factory=list)
    programmatic_outcome: Literal[
        "initial_accepted",
        "legality_improved",
        "evaluability_improved",
        "score_improved",
        "mixed",
        "no_measurable_improvement",
        "regressed",
        "stopped_with_reason",
    ]
    human_review_fields: dict[str, str] = Field(default_factory=dict)
    no_raw_material: bool = True

    @model_validator(mode="after")
    def _comparison_is_ordered_and_safe(self) -> "RetryComparisonReport":
        if not self.no_raw_material:
            raise ValueError("no_raw_material must be true")
        indices = [attempt.attempt_index for attempt in self.attempts]
        if indices != list(range(len(indices))):
            raise ValueError("retry attempts must be contiguous and ordered from zero")
        return self


def same_version(left: VersionContext, right: VersionContext) -> bool:
    return (
        left.league == right.league
        and left.ruleset == right.ruleset
        and left.game_patch == right.game_patch
        and left.passive_tree_version == right.passive_tree_version
        and left.pob_version_or_commit == right.pob_version_or_commit
        and left.graph_snapshot_id == right.graph_snapshot_id
        and left.research_memory_ref == right.research_memory_ref
    )


def validate_no_raw_or_hidden_reasoning(payload: Any) -> dict[str, Any]:
    scanned = scan_payload(payload)
    hidden_paths = _hidden_reasoning_paths(scanned) + _hidden_reasoning_value_paths(scanned)
    if hidden_paths:
        return rejected("unsafe_reasoning_material", caveats=sorted(set(hidden_paths)))
    raw_query_paths = _raw_query_paths(scanned)
    if raw_query_paths:
        return rejected("raw_query_violation", caveats=sorted(set(raw_query_paths)))
    raw_material_flags = _phase5_raw_material_flags(scanned)
    if raw_material_flags:
        return rejected("copy_safety_violation", caveats=raw_material_flags)
    return {"status": "accepted", "noRawMaterial": True, "noHiddenChainOfThought": True}


def scan_payload(payload: Any) -> Any:
    if isinstance(payload, BaseModel):
        return payload.model_dump()
    if isinstance(payload, dict):
        return {key: scan_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [scan_payload(item) for item in payload]
    return payload


def schema_error(exc: ValidationError) -> dict[str, Any]:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", ())) or "input"
    message = " ".join(str(first.get("msg") or "validation failed").split())[:160]
    return rejected("invalid_schema", caveats=[f"{loc}: {message}"])


def rejected(error_code: str, caveats: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": "rejected",
        "errorCode": error_code,
        "caveats": list(caveats or []),
        "noRawMaterial": True,
        "noHiddenChainOfThought": True,
    }


def _require_stage_contract(current: list[str], target: list[str]) -> None:
    if not set(current).issubset(set(target)):
        raise ValueError("target_lifecycle_stages must include current_output_stages")


def _require_class_only_lock(locks: list[str]) -> None:
    if locks != ["class"]:
        raise ValueError("cross_stage_locked_dimensions must be exactly ['class']")


def _hidden_reasoning_paths(value: Any, *, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        normalized_hidden = {_normalize_name(field) for field in HIDDEN_REASONING_FIELDS}
        for key, child in value.items():
            key_text = str(key)
            child_path = _join_path(path, _safe_path_segment(key_text))
            normalized_key = _normalize_name(key_text)
            if normalized_key in normalized_hidden or _contains_hidden_reasoning_key(key_text):
                found.append(child_path)
            found.extend(_hidden_reasoning_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            found.extend(_hidden_reasoning_paths(child, path=child_path))
    return sorted(found)


def _hidden_reasoning_value_paths(value: Any, *, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = _join_path(path, _safe_path_segment(str(key)))
            found.extend(_hidden_reasoning_value_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            found.extend(_hidden_reasoning_value_paths(child, path=child_path))
    elif isinstance(value, str) and _contains_hidden_reasoning_label(value):
        found.append(path or "input")
    return found


def _raw_query_paths(value: Any, *, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        raw_query_keys = {"rawquery", "querystring", "cypher", "gremlin", "sql"}
        for key, child in value.items():
            key_text = str(key)
            child_path = _join_path(path, _safe_path_segment(key_text))
            if _normalize_name(key_text) in raw_query_keys:
                found.append(child_path)
            found.extend(_raw_query_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            found.extend(_raw_query_paths(child, path=child_path))
    elif isinstance(value, str) and _contains_raw_query_text(value):
        found.append(path or "input")
    return found


def _contains_hidden_reasoning_label(value: str) -> bool:
    labels = (
        r"hidden[-_\s]*chain[-_\s]*of[-_\s]*thought",
        r"raw[-_\s]*chain[-_\s]*of[-_\s]*thought",
        r"chain[-_\s]*of[-_\s]*thought",
        r"raw[-_\s]*reasoning[-_\s]*trace",
        r"reasoning[-_\s]*trace",
        r"raw[-_\s]*scratchpad",
        r"scratchpad",
        r"full[-_\s]*transcript",
        r"conversation[-_\s]*transcript",
        r"raw[-_\s]*transcript",
        r"transcript",
        r"raw[-_\s]*dialogue",
        r"conversation[-_\s]*dialogue",
        r"dialogue",
        r"raw[-_\s]*user[-_\s]*prompt",
        r"user[-_\s]*prompt",
        r"raw[-_\s]*prompt",
    )
    pattern = r"(?i)\b(?:" + "|".join(labels) + r")\s*[:=]"
    return re.search(pattern, value) is not None


def _contains_hidden_reasoning_key(value: str) -> bool:
    normalized = _normalize_name(value)
    allowed_flags = {"nohiddenchainofthought"}
    if normalized in allowed_flags:
        return False
    patterns = (
        r"(?i)(^|[^a-z0-9])hidden[-_\s]*chain[-_\s]*of[-_\s]*thought([^a-z0-9]|$)",
        r"(?i)(^|[^a-z0-9])chain[-_\s]*of[-_\s]*thought([^a-z0-9]|$)",
        r"(?i)(^|[^a-z0-9])reasoning[-_\s]*trace([^a-z0-9]|$)",
        r"(?i)(^|[^a-z0-9])scratchpad([^a-z0-9]|$)",
        r"(?i)(^|[^a-z0-9])transcript([^a-z0-9]|$)",
        r"(?i)(^|[^a-z0-9])dialogue([^a-z0-9]|$)",
        r"(?i)(^|[^a-z0-9])raw[-_\s]*prompt([^a-z0-9]|$)",
    )
    return any(re.search(pattern, value) for pattern in patterns)


def _contains_raw_query_text(value: str) -> bool:
    patterns = (
        r"(?is)\bselect\s+.+?\s+from\s+",
        r"(?is)\bmatch\s*\(.+?\)\s*return\b",
        r"(?is)\bcypher\s*[:=]",
        r"(?is)\bgremlin\s*[:=]",
        r"(?is)\bsql\s*[:=]",
        r"(?is)\bg\s*\.\s*v\s*\(",
    )
    return any(re.search(pattern, value) for pattern in patterns)


def _contains_full_url(value: Any) -> bool:
    text = "\n".join(copy_safety.all_text(value)).casefold()
    return re.search(r"https?://[^\s)]+", text) is not None


def _phase5_raw_material_flags(value: Any) -> list[str]:
    """Reject raw source leaks, not Agent-generated build specificity.

    Phase 5 creates new candidates. A concrete skill package, gear slot summary,
    or passive anchor path can be legitimate output and should not be treated as
    copying merely because it resembles a build. Hard rejection is reserved for
    raw/importable/source-identifying material that would leak a third-party or
    transient build artifact.
    """
    text = "\n".join(copy_safety.all_text(value))
    lower = text.casefold()
    flags: set[str] = set()
    if any(marker in text for marker in ("PathOfBuilding", "<PathOfBuilding", "<Build", "<Skills")):
        flags.add("raw_pob_xml_marker")
    if any(marker in lower for marker in ("rawxml", "rawimportcode", "rawpob")):
        flags.add("raw_pob_xml_marker")
    if copy_safety.contains_pob_code_like_blob(text):
        flags.add("pob_code_like_blob")
    if _contains_full_url(value):
        flags.add("full_url")
    raw_paths = _phase5_raw_material_paths(value)
    flags.update(raw_paths)
    return sorted(flags)


def _phase5_raw_material_paths(value: Any, *, path: str = "") -> list[str]:
    raw_field_names = {
        "pobcode",
        "pastebincode",
        "pobbincode",
        "rawxml",
        "rawpob",
        "rawimportcode",
        "rawcontent",
        "rawpayload",
        "rawjson",
        "rawhtml",
        "rawresponse",
        "rawguidetext",
        "characterurl",
        "profileurl",
        "accountname",
        "charactername",
    }
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = _join_path(path, _safe_path_segment(key_text))
            if _normalize_name(key_text) in raw_field_names:
                found.append(child_path)
            found.extend(_phase5_raw_material_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            found.extend(_phase5_raw_material_paths(child, path=child_path))
    return sorted(found)


def _normalize_name(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _join_path(parent: str, segment: str) -> str:
    return f"{parent}.{segment}" if parent else segment


def _safe_path_segment(segment: str) -> str:
    if copy_safety.copyability_flags(segment) or _contains_full_url(segment) or len(segment) > 120:
        digest = hashlib.sha256(segment.encode("utf-8")).hexdigest()[:12]
        return f"redacted-key:{digest}"
    return segment


def normalize_lifecycle_stages(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    return [LIFECYCLE_STAGE_ALIASES.get(str(stage), stage) for stage in value]


def _dedupe_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output


def _camel_to_snake_name(value: str) -> str:
    output: list[str] = []
    for index, char in enumerate(value):
        if char.isupper() and index > 0:
            output.append("_")
        output.append(char.lower())
    return "".join(output)
