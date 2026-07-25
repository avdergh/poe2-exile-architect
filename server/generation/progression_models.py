"""Typed contracts shared by the Phase 8 progression orchestrator and Route v2."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from server.knowledge import copy_safety

from . import models
from .progression_research import StarterEvidenceUse


RouteRole = Literal[
    "starter_bootstrap",
    "starter_established",
    "transition",
    "target",
]
EvidenceStatus = Literal["supported", "limited", "limited_offline_inference"]
RequirementStatus = Literal["satisfied", "required", "unverified"]
RequirementKind = Literal[
    "level",
    "quest",
    "skill_available",
    "ascendancy_points",
    "respec_points",
    "passive_threshold",
    "spirit",
    "attribute",
    "resource_loop",
    "defense_gate",
    "required_item_owned",
    "judge_gate",
    "budget",
    "price",
    "manual",
]
Responsibility = Literal[
    "clear",
    "boss",
    "defense",
    "recovery",
    "resource",
    "mobility",
]
CostBand = Literal["routine", "cheap", "moderate", "expensive", "chase", "unknown"]
_SAFE_REF = re.compile(r"^[A-Za-z0-9_.:/\-]{3,240}$")
_MECHANISM_GATES = {
    "level",
    "quest",
    "skill_available",
    "ascendancy_points",
    "respec_points",
    "passive_threshold",
    "spirit",
    "attribute",
    "resource_loop",
    "defense_gate",
    "required_item_owned",
    "judge_gate",
    "manual",
}


class TransitionRequirement(models.StrictModel):
    requirement_id: str = Field(pattern=r"^gate:[A-Za-z0-9\-]{3,100}$")
    kind: RequirementKind
    description: str = Field(min_length=1, max_length=320)
    status: RequirementStatus = "required"
    blocking: bool = True
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _consistent(self) -> "TransitionRequirement":
        _safe_refs(self.evidence_refs)
        if self.status == "satisfied" and not self.evidence_refs:
            raise ValueError("satisfied transition requirement requires evidence")
        if self.kind in {"budget", "price"} and self.blocking:
            raise ValueError("budget and price are advisory and cannot block a transition")
        _ensure_authored_text({"description": self.description})
        return self


class StageCostSummary(models.StrictModel):
    cost_profile_ref: str = Field(pattern=r"^progression-cost:[A-Za-z0-9\-]{3,100}$")
    league: str = Field(min_length=1, max_length=100)
    base_currency: str = Field(default="", max_length=100)
    highest_required_band: CostBand
    paid_dependency_count: int = Field(ge=0, le=20)
    required_dependency_count: int = Field(ge=0, le=20)
    unknown_required_dependency_count: int = Field(ge=0, le=20)
    fallback_coverage: float = Field(ge=0.0, le=1.0)
    live_price_coverage: float = Field(ge=0.0, le=1.0)
    cost_evidence_status: Literal["supported", "limited", "unavailable"]
    captured_at: str
    expires_at: str
    contains_total_price: Literal[False] = False

    @model_validator(mode="after")
    def _time_order(self) -> "StageCostSummary":
        try:
            captured = datetime.fromisoformat(self.captured_at.replace("Z", "+00:00"))
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("cost summary timestamps must be ISO-8601") from exc
        if captured.tzinfo is None or expires.tzinfo is None or expires <= captured:
            raise ValueError("cost summary expiry must follow capture time")
        if self.paid_dependency_count > self.required_dependency_count:
            raise ValueError("paid dependency count exceeds required dependency count")
        if self.unknown_required_dependency_count > self.required_dependency_count:
            raise ValueError("unknown required dependency count exceeds required dependency count")
        if (
            self.paid_dependency_count + self.unknown_required_dependency_count
            > self.required_dependency_count
        ):
            raise ValueError("known paid and unknown dependency counts exceed required count")
        _ensure_authored_text(
            {
                "league": self.league,
                "baseCurrency": self.base_currency,
            }
        )
        return self


class TransitionBridge(models.StrictModel):
    bridge_id: str = Field(pattern=r"^bridge:[A-Za-z0-9\-]{3,100}$")
    summary: str = Field(min_length=1, max_length=500)
    requirements: list[TransitionRequirement] = Field(min_length=1, max_length=20)
    fallback_plan: str = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def _mechanically_driven(self) -> "TransitionBridge":
        ids = [item.requirement_id for item in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("transition requirement ids must be unique")
        if not any(item.blocking and item.kind in _MECHANISM_GATES for item in self.requirements):
            raise ValueError("transition bridge requires a non-price mechanism gate")
        _ensure_authored_text({"summary": self.summary, "fallbackPlan": self.fallback_plan})
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


class TargetBuildIntent(models.StrictModel):
    ascendancy_intent: str = Field(min_length=1, max_length=120)
    primary_skill_intent: str = Field(min_length=1, max_length=160)
    mechanic_intents: list[str] = Field(min_length=1, max_length=10)
    ceiling_goals: list[str] = Field(min_length=1, max_length=8)
    known_early_failures: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _safe_text(self) -> "TargetBuildIntent":
        _ensure_authored_text(self.model_dump(mode="json", by_alias=True))
        return self


class StageFamilyIdentity(models.StrictModel):
    ascendancy_key: str = Field(min_length=3, max_length=240)
    primary_skill_key: str = Field(min_length=3, max_length=240)
    secondary_skill_keys: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _resolved_keys(self) -> "StageFamilyIdentity":
        _safe_refs(
            [
                self.ascendancy_key,
                self.primary_skill_key,
                *self.secondary_skill_keys,
            ]
        )
        if not self.ascendancy_key.startswith("ascendancy:"):
            raise ValueError("stage Family ascendancy key must be a resolved ascendancy key")
        if not self.primary_skill_key.startswith("skill:") or any(
            not key.startswith("skill:") for key in self.secondary_skill_keys
        ):
            raise ValueError("stage Family skill keys must be resolved skill keys")
        return self


class StageBlueprint(models.StrictModel):
    stage_id: str = Field(pattern=r"^stage:[A-Za-z0-9\-]{3,100}$")
    lifecycle_stage: models.LIFECYCLE_STAGE
    route_role: RouteRole
    target_level: int = Field(ge=2, le=100)
    family_identity: StageFamilyIdentity
    ascendancy_intent: str = Field(min_length=1, max_length=120)
    primary_skill_intent: str = Field(min_length=1, max_length=160)
    skill_package_intents: list[str] = Field(min_length=1, max_length=8)
    passive_anchor_intents: list[str] = Field(default_factory=list, max_length=12)
    gear_role_intents: list[str] = Field(default_factory=list, max_length=12)
    responsibility_coverage: list[Responsibility] = Field(min_length=4, max_length=6)
    evidence_status: EvidenceStatus = "limited"
    entry_bridge: TransitionBridge | None = None
    expected_cost_band: CostBand = "unknown"
    research_query_refs: list[str] = Field(min_length=1, max_length=8)
    rebuild_from_scratch: bool = False

    @field_validator("lifecycle_stage", mode="before")
    @classmethod
    def _normalize_stage(cls, value: Any) -> Any:
        normalized = models.normalize_lifecycle_stages([value])
        return normalized[0] if normalized else value

    @model_validator(mode="after")
    def _safe_unique_fields(self) -> "StageBlueprint":
        if len(self.responsibility_coverage) != len(set(self.responsibility_coverage)):
            raise ValueError("responsibility coverage must be unique")
        if not {"clear", "boss", "defense", "resource"}.issubset(set(self.responsibility_coverage)):
            raise ValueError("each stage must cover clear, boss, defense and resource duties")
        _safe_refs(self.research_query_refs)
        _ensure_authored_text(
            {
                "ascendancyIntent": self.ascendancy_intent,
                "primarySkillIntent": self.primary_skill_intent,
                "skillPackageIntents": self.skill_package_intents,
                "passiveAnchorIntents": self.passive_anchor_intents,
                "gearRoleIntents": self.gear_role_intents,
            }
        )
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


class ProgressionBlueprint(models.VersionedSafeModel):
    blueprint_id: str = Field(pattern=r"^progression-blueprint:[A-Za-z0-9\-]{3,100}$")
    route_name: str = Field(min_length=1, max_length=120)
    base_class: str = Field(min_length=1, max_length=80)
    target_level: int = Field(ge=2, le=100)
    starter_research_packet_id: str = Field(pattern=r"^starter-research:[A-Za-z0-9\-]{3,100}$")
    starter_evidence_use: StarterEvidenceUse
    starter_choice_summary: str = Field(min_length=1, max_length=600)
    target_intent: TargetBuildIntent
    stages: list[StageBlueprint] = Field(min_length=2, max_length=5)
    merge_rationale: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _ordered_route(self) -> "ProgressionBlueprint":
        stage_ids = [stage.stage_id for stage in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("stage ids must be unique")
        levels = [stage.target_level for stage in self.stages]
        if levels != sorted(set(levels)):
            raise ValueError("stage target levels must be strictly increasing")
        for stage in self.stages:
            minimum_level = {
                "endgame_budget": 82,
                "endgame_final": 92,
            }.get(str(stage.lifecycle_stage))
            if minimum_level is not None and stage.target_level < minimum_level:
                raise ValueError(
                    f"{stage.lifecycle_stage} requires target level {minimum_level} or higher"
                )
        orders = [_stage_order(stage.lifecycle_stage) for stage in self.stages]
        if orders != sorted(orders):
            raise ValueError("lifecycle stages must be non-decreasing")
        if self.stages[-1].target_level != self.target_level:
            raise ValueError("last stage must match target level")
        if self.stages[0].route_role not in {"starter_bootstrap", "starter_established"}:
            raise ValueError("first stage must be a starter stage")
        if self.stages[0].entry_bridge is not None:
            raise ValueError("first stage cannot carry an entry bridge")
        for stage in self.stages[1:]:
            if stage.entry_bridge is None:
                raise ValueError("later stages require a transition bridge")
        if self.stages[-1].route_role not in {"target", "transition"}:
            raise ValueError("last stage must be target or unresolved transition form")
        role_order = {
            "starter_bootstrap": 0,
            "starter_established": 1,
            "transition": 2,
            "target": 3,
        }
        roles = [role_order[stage.route_role] for stage in self.stages]
        if roles != sorted(roles) or any(
            stage.route_role == "target" for stage in self.stages[:-1]
        ):
            raise ValueError("route roles must progress from starter through transition to target")
        if self.starter_evidence_use.packet_id != self.starter_research_packet_id:
            raise ValueError("starter evidence use must reference the selected packet")
        seen_queries: set[str] = set()
        previous_family: StageFamilyIdentity | None = None
        for stage in self.stages:
            current_queries = set(stage.research_query_refs)
            if (
                previous_family is not None
                and stage.family_identity != previous_family
                and not (current_queries - seen_queries)
            ):
                raise ValueError("a changed stage Family requires a fresh Research query ref")
            seen_queries.update(current_queries)
            previous_family = stage.family_identity
        _ensure_authored_text(
            {
                "routeName": self.route_name,
                "baseClass": self.base_class,
                "starterChoiceSummary": self.starter_choice_summary,
                "mergeRationale": self.merge_rationale,
            }
        )
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


class StageCreatePacket(models.VersionedSafeModel):
    progression_id: str = Field(pattern=r"^[0-9a-f\-]{36}$")
    blueprint_id: str = Field(pattern=r"^progression-blueprint:[A-Za-z0-9\-]{3,100}$")
    base_class: str = Field(min_length=1, max_length=80)
    target_level: int = Field(ge=2, le=100)
    route_target_level: int = Field(ge=2, le=100)
    target_intent: TargetBuildIntent
    stage: StageBlueprint
    previous_artifact_id: str | None = Field(
        default=None,
        pattern=r"^final-build:[A-Za-z0-9\-]{3,100}$",
    )
    starter_research_packet_id: str = Field(pattern=r"^starter-research:[A-Za-z0-9\-]{3,100}$")
    starter_evidence_use: StarterEvidenceUse
    progression_bound: bool = True

    @model_validator(mode="after")
    def _bound(self) -> "StageCreatePacket":
        if not self.progression_bound:
            raise ValueError("stage packet must be progression-bound")
        if self.stage.target_level != self.target_level:
            raise ValueError("stage packet target level mismatch")
        if self.target_level > self.route_target_level:
            raise ValueError("stage target cannot exceed route target")
        return self


def _stage_order(value: str) -> int:
    order = {
        "campaign_early": 0,
        "campaign_mid": 1,
        "campaign_late": 2,
        "maps_entry": 3,
        "endgame_budget": 4,
        "endgame_final": 5,
    }
    return order[str(value)]


def _safe_refs(values: list[str]) -> None:
    if len(values) != len(set(values)) or any(not _SAFE_REF.fullmatch(item) for item in values):
        raise ValueError("references must be unique safe refs")


def _ensure_safe(value: Any) -> None:
    if (
        copy_safety.find_forbidden_paths(value)
        or copy_safety.durable_knowledge_flags(value)
        or copy_safety.contains_raw_url(value)
    ):
        raise ValueError("unsafe progression blueprint payload")


def _ensure_authored_text(value: Any) -> None:
    if copy_safety.copyability_flags(value) or copy_safety.contains_raw_url(value):
        raise ValueError("copyable material is forbidden in progression text")
