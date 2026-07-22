"""Typed contracts for the Phase 7 comparative-learning loop."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from server.knowledge import copy_safety


def _camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class StrictModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        extra="forbid",
        populate_by_name=True,
        strict=True,
    )


StableKey = str
MemoryStatus = Literal["active", "narrowed", "superseded", "deprecated", "stale"]
MemoryScope = Literal["global", "family", "level_band"]
MemoryDecision = Literal["adopted", "caveated", "rejected"]
CorrectionAction = Literal["narrow", "revise", "supersede", "deprecate"]
DimensionVerdict = Literal[
    "generated_advantage",
    "reference_advantage",
    "tradeoff",
    "tie",
    "unknown",
]
OverallVerdict = Literal[
    "generated_stronger",
    "reference_stronger",
    "tradeoff",
    "incomparable",
]
RootCause = Literal[
    "missing_critical_technique",
    "create_instruction_tool_or_data_defect",
    "research_knowledge_or_retrieval_defect",
    "learning_memory_missing_or_polluted",
    "judge_or_modelability_gap",
    "unrealistic_reference_configuration",
    "insufficient_evidence",
]
ComparisonDimension = Literal[
    "damage_loop_delivery",
    "skill_roles_supports",
    "configuration_realism",
    "trigger_conversion_chain",
    "gear_passive_ascendancy_synergy",
    "clear_boss_burst",
    "defense_recovery_resource_spirit",
    "mobility_playability",
    "legality_completeness_modelability",
    "gear_effort_attainability",
]

COMPARISON_DIMENSIONS: tuple[str, ...] = (
    "damage_loop_delivery",
    "skill_roles_supports",
    "configuration_realism",
    "trigger_conversion_chain",
    "gear_passive_ascendancy_synergy",
    "clear_boss_burst",
    "defense_recovery_resource_spirit",
    "mobility_playability",
    "legality_completeness_modelability",
    "gear_effort_attainability",
)

_STABLE_KEY = re.compile(r"^[A-Za-z0-9_.:/\-']+$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9_.:/\-]{3,240}$")


class LearningVersionContext(StrictModel):
    game_patch: str = Field(min_length=1, max_length=80)
    passive_tree_version: str = Field(min_length=1, max_length=120)
    pob_version_or_commit: str = Field(min_length=1, max_length=160)


class FamilyTarget(StrictModel):
    schema_version: Literal[1] = 1
    build_family_key: str = Field(pattern=r"^bf-[a-f0-9]{20}$")
    ascendancy_key: StableKey = Field(min_length=3, max_length=240)
    primary_skill_key: StableKey = Field(min_length=3, max_length=240)
    secondary_skill_keys: list[StableKey] = Field(default_factory=list, max_length=12)
    target_level: int = Field(ge=1, le=100)
    version_context: LearningVersionContext
    safe_evidence_refs: list[str] = Field(min_length=1, max_length=12)

    @field_validator("ascendancy_key")
    @classmethod
    def _ascendancy_key(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value) or not value.startswith("ascendancy:"):
            raise ValueError("ascendancy_key must be a resolved ascendancy stable key")
        return value

    @field_validator("primary_skill_key")
    @classmethod
    def _primary_skill_key(cls, value: str) -> str:
        if not _STABLE_KEY.fullmatch(value) or not value.startswith("skill:"):
            raise ValueError("primary_skill_key must be a resolved skill stable key")
        return value

    @field_validator("secondary_skill_keys")
    @classmethod
    def _secondary_keys(cls, values: list[str]) -> list[str]:
        if any(
            not _STABLE_KEY.fullmatch(value) or not value.startswith("skill:") for value in values
        ):
            raise ValueError("secondary_skill_keys must contain resolved skill stable keys")
        if values != sorted(set(values)):
            raise ValueError("secondary_skill_keys must be unique and sorted")
        return values

    @field_validator("safe_evidence_refs")
    @classmethod
    def _safe_refs(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(
            not _SAFE_REF.fullmatch(value) for value in values
        ):
            raise ValueError("safe_evidence_refs must be unique safe references")
        return values

    @model_validator(mode="after")
    def _consistent(self) -> "FamilyTarget":
        if self.primary_skill_key in self.secondary_skill_keys:
            raise ValueError("primary skill must not be repeated as a secondary skill")
        return self


class BlindCreatePacket(StrictModel):
    schema_version: Literal[1] = 1
    campaign_id: str = Field(min_length=1, max_length=80)
    case_id: str = Field(min_length=1, max_length=80)
    family_target: FamilyTarget
    default_goal: Literal["softcore_trade_no_fixed_budget_overall_strength_and_playability"] = (
        "softcore_trade_no_fixed_budget_overall_strength_and_playability"
    )
    reference_blind: Literal[True] = True
    research_allowed: Literal[True] = True
    learning_memory_allowed: Literal[True] = True
    create_invocation_limit: Literal[1] = 1
    phase5_internal_retry_limit: Literal[2] = 2

    @model_validator(mode="after")
    def _safe(self) -> "BlindCreatePacket":
        ensure_safe_durable_payload(self.model_dump(mode="json", by_alias=True))
        return self


class MemoryUseDecisionRecord(StrictModel):
    lesson_id: str = Field(min_length=1, max_length=100)
    decision: MemoryDecision
    application: str = Field(min_length=1, max_length=500)
    harmful_or_incorrect: bool = False
    observation: str | None = Field(default=None, max_length=500)


class LearningMemoryUse(StrictModel):
    query_ref: str = Field(pattern=r"^learning-query:[a-f0-9]{20}$")
    recalled_lesson_ids: list[str] = Field(default_factory=list, max_length=20)
    decisions: list[MemoryUseDecisionRecord] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _decisions_are_recalled(self) -> "LearningMemoryUse":
        recalled = set(self.recalled_lesson_ids)
        if len(recalled) != len(self.recalled_lesson_ids):
            raise ValueError("recalled_lesson_ids must be unique")
        decision_ids = [item.lesson_id for item in self.decisions]
        if len(set(decision_ids)) != len(decision_ids):
            raise ValueError("each recalled lesson may have at most one decision")
        if any(item_id not in recalled for item_id in decision_ids):
            raise ValueError("memory decisions must reference recalled lessons")
        if set(decision_ids) != recalled:
            raise ValueError("every recalled lesson requires an adopted/caveated/rejected decision")
        return self


class JudgeAdvisoryAttachment(StrictModel):
    advisory_only: Literal[True] = True
    available: bool
    score_applicability: str = Field(min_length=1, max_length=80)
    modelability: str = Field(min_length=1, max_length=80)
    safe_summary: str = Field(default="", max_length=600)
    metrics: dict[str, int | float | None] = Field(default_factory=dict, max_length=20)


class SafeBuildEvidence(StrictModel):
    schema_version: Literal[1] = 1
    evidence_ref: str = Field(min_length=3, max_length=240)
    side: Literal["reference", "generated"]
    summary: str = Field(min_length=1, max_length=800)
    dimension_notes: dict[str, str] = Field(default_factory=dict, max_length=10)
    configuration_caveats: list[str] = Field(default_factory=list, max_length=12)
    legality_status: Literal["passed", "failed", "unknown"]
    modelability_status: Literal["full", "partial", "unavailable", "unknown"]
    safe_evidence_refs: list[str] = Field(min_length=1, max_length=20)
    judge_advisory: JudgeAdvisoryAttachment | None = None
    no_raw_material: Literal[True] = True

    @model_validator(mode="after")
    def _safe_and_bounded(self) -> "SafeBuildEvidence":
        if any(key not in COMPARISON_DIMENSIONS for key in self.dimension_notes):
            raise ValueError("dimension_notes contains an unknown comparison dimension")
        if any(len(value) > 500 for value in self.dimension_notes.values()):
            raise ValueError("dimension note exceeds 500 characters")
        ensure_safe_durable_payload(self.model_dump(mode="json", by_alias=True))
        return self


class DimensionComparison(StrictModel):
    dimension: ComparisonDimension
    verdict: DimensionVerdict
    rationale: str = Field(min_length=1, max_length=800)
    generated_evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    reference_evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    critical_gap: bool = False


class ComparisonGap(StrictModel):
    gap_id: str = Field(min_length=1, max_length=100)
    dimension: ComparisonDimension
    root_cause: RootCause
    summary: str = Field(min_length=1, max_length=600)
    critical: bool
    safe_evidence_refs: list[str] = Field(min_length=1, max_length=12)


class BuildComparisonReport(StrictModel):
    schema_version: Literal[1] = 1
    comparison_id: str = Field(min_length=1, max_length=100)
    case_id: str = Field(min_length=1, max_length=80)
    family_match: bool
    level_match: bool
    generated_legal: bool | None
    reference_legal: bool | None
    dimensions: list[DimensionComparison] = Field(min_length=10, max_length=10)
    overall_verdict: OverallVerdict
    gaps: list[ComparisonGap] = Field(default_factory=list, max_length=30)
    judge_advisory: dict[Literal["generated", "reference"], JudgeAdvisoryAttachment] = Field(
        default_factory=dict
    )
    comparator_summary: str = Field(min_length=1, max_length=1200)
    no_automatic_winner: Literal[True] = True
    no_reward_write: Literal[True] = True
    no_raw_material: Literal[True] = True

    @model_validator(mode="after")
    def _complete_dimensions_and_safe(self) -> "BuildComparisonReport":
        dimensions = [item.dimension for item in self.dimensions]
        if set(dimensions) != set(COMPARISON_DIMENSIONS) or len(set(dimensions)) != 10:
            raise ValueError("comparison must contain each required dimension exactly once")
        if self.overall_verdict == "reference_stronger" and not self.gaps:
            raise ValueError("reference_stronger requires typed gaps")
        ensure_safe_durable_payload(self.model_dump(mode="json", by_alias=True))
        return self


class LearningLessonProposal(StrictModel):
    schema_version: Literal[1] = 1
    lesson: str = Field(min_length=8, max_length=500)
    scope: MemoryScope
    family_key: str | None = Field(default=None, pattern=r"^bf-[a-f0-9]{20}$")
    level_min: int | None = Field(default=None, ge=1, le=100)
    level_max: int | None = Field(default=None, ge=1, le=100)
    dimension: ComparisonDimension
    conditions: list[str] = Field(default_factory=list, max_length=12)
    exclusions: list[str] = Field(default_factory=list, max_length=12)
    recommended_create_behavior: str = Field(min_length=8, max_length=700)
    verification_tasks: list[str] = Field(min_length=1, max_length=12)
    comparison_refs: list[str] = Field(min_length=1, max_length=12)
    source_refs: list[str] = Field(min_length=1, max_length=12)
    candidate_refs: list[str] = Field(min_length=1, max_length=12)
    version_context: LearningVersionContext
    reviewed_case_id: str = Field(min_length=1, max_length=80)
    db_fit: Literal[False] = False
    cited_correction_ids: list[str] = Field(default_factory=list, max_length=12)
    new_evidence_refs: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _scope_and_safety(self) -> "LearningLessonProposal":
        if self.scope == "global" and any(
            value is not None for value in (self.family_key, self.level_min, self.level_max)
        ):
            raise ValueError("global scope cannot carry family or level bounds")
        if self.scope == "family" and (
            self.family_key is None or self.level_min is not None or self.level_max is not None
        ):
            raise ValueError("family scope requires only family_key")
        if self.scope == "level_band" and (
            self.family_key is not None or self.level_min is None or self.level_max is None
        ):
            raise ValueError("level_band scope requires only level_min and level_max")
        if (
            self.level_min is not None
            and self.level_max is not None
            and self.level_min > self.level_max
        ):
            raise ValueError("level_min must not exceed level_max")
        ensure_safe_durable_payload(self.model_dump(mode="json", by_alias=True))
        return self


class LearningMemoryEntry(LearningLessonProposal):
    lesson_id: str = Field(min_length=1, max_length=100)
    lesson_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: MemoryStatus
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)


class LearningCorrectionProposal(StrictModel):
    schema_version: Literal[1] = 1
    target_lesson_id: str = Field(min_length=1, max_length=100)
    action: CorrectionAction
    reason: str = Field(min_length=8, max_length=700)
    trigger_case_id: str = Field(min_length=1, max_length=80)
    safe_evidence_refs: list[str] = Field(min_length=1, max_length=12)
    after_lesson: str | None = Field(default=None, min_length=8, max_length=500)
    after_conditions: list[str] = Field(default_factory=list, max_length=12)
    after_exclusions: list[str] = Field(default_factory=list, max_length=12)
    replacement_lesson_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _action_contract(self) -> "LearningCorrectionProposal":
        if self.action in {"narrow", "revise"}:
            if self.after_lesson is None:
                raise ValueError("narrow/revise requires after_lesson")
            if self.replacement_lesson_id is not None:
                raise ValueError("narrow/revise cannot carry replacement_lesson_id")
        elif self.action == "supersede":
            if self.replacement_lesson_id is None:
                raise ValueError("supersede requires replacement_lesson_id")
            if self.after_lesson is not None or self.after_conditions or self.after_exclusions:
                raise ValueError("supersede cannot carry revised lesson fields")
        elif self.after_lesson is not None or self.replacement_lesson_id is not None:
            raise ValueError("deprecate cannot carry replacement or revised lesson fields")
        ensure_safe_durable_payload(self.model_dump(mode="json", by_alias=True))
        return self


class LearningMemoryCorrection(LearningCorrectionProposal):
    correction_id: str = Field(min_length=1, max_length=100)
    before_summary: str = Field(min_length=1, max_length=500)
    after_summary: str = Field(min_length=1, max_length=500)
    created_at: str = Field(min_length=1)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_safe_durable_payload(value: Any) -> None:
    forbidden = copy_safety.find_forbidden_paths(value)
    flags = copy_safety.durable_knowledge_flags(value)
    if forbidden:
        raise ValueError(f"forbidden durable fields: {', '.join(forbidden[:5])}")
    if flags:
        raise ValueError(f"copy-safety rejected payload: {', '.join(flags)}")
