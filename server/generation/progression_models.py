"""Typed contracts shared by the Phase 8 progression orchestrator and Route v3."""

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
StageKnowledgeMode = Literal["starter_common", "family_exact"]
OptimizationObjective = Literal[
    "skill_availability",
    "weapon_compatibility",
    "resource_sustain",
    "damage_delivery",
    "defense_layers",
    "gear_legality",
    "lifecycle_readiness",
]
ExcludedOptimizationObjective = Literal[
    "elemental_resistance_judgment",
    "global_whole_build_optimization",
    "global_passive_tree_optimization",
    "offense_quality_chasing",
    "defense_quality_chasing",
    "full_gear_optimization",
]
EvidenceStatus = Literal["supported", "limited", "limited_offline_inference"]
RequirementStatus = Literal["satisfied", "required", "unverified"]
TargetCoverageStatus = Literal[
    "research_adopted",
    "independently_verified",
    "unavailable_with_caveat",
    "rejected",
]
TargetCoverageDimension = Literal[
    "skill_package",
    "clear_duty",
    "boss_duty",
    "damage_delivery",
    "ascendancy_and_passives",
    "gear_synergy",
    "defense_and_recovery",
    "resource_and_spirit",
    "combat_configuration",
    "modelability",
]
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
    ascendancy_name: str | None = Field(default=None, min_length=1, max_length=120)
    primary_skill_name: str | None = Field(default=None, min_length=1, max_length=160)
    secondary_skill_names: list[str] = Field(default_factory=list, max_length=8)

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
            raise ValueError(
                "stage Family skill keys must use resolved skill keys for active-skill nodes; "
                "gem keys are query aliases, not Family identity keys"
            )
        _ensure_authored_text(
            {
                "ascendancyName": self.ascendancy_name,
                "primarySkillName": self.primary_skill_name,
                "secondarySkillNames": self.secondary_skill_names,
            }
        )
        return self


class StarterStageIdentity(models.StrictModel):
    """Skill identity for a campaign stage that is not yet a mature build Family.

    Early campaign snapshots may legitimately be unascended and the mature Research database is
    intentionally biased toward finished builds.  Keep the skill package typed without inventing
    an ascendancy-backed Family that does not exist.
    """

    primary_skill_key: str = Field(min_length=3, max_length=240)
    secondary_skill_keys: list[str] = Field(default_factory=list, max_length=8)
    primary_skill_name: str = Field(min_length=1, max_length=160)
    secondary_skill_names: list[str] = Field(default_factory=list, max_length=8)
    expected_ascendancy_key: str | None = Field(default=None, min_length=3, max_length=240)
    expected_ascendancy_name: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def _resolved_keys(self) -> "StarterStageIdentity":
        _safe_refs(
            [
                self.primary_skill_key,
                *self.secondary_skill_keys,
                *(
                    [self.expected_ascendancy_key]
                    if self.expected_ascendancy_key is not None
                    else []
                ),
            ]
        )
        if not self.primary_skill_key.startswith("skill:") or any(
            not key.startswith("skill:") for key in self.secondary_skill_keys
        ):
            raise ValueError("starter stage skills must use resolved active-skill keys")
        if self.expected_ascendancy_key is not None and not self.expected_ascendancy_key.startswith(
            "ascendancy:"
        ):
            raise ValueError("starter expected ascendancy must use a resolved ascendancy key")
        if (self.expected_ascendancy_key is None) != (self.expected_ascendancy_name is None):
            raise ValueError("starter expected ascendancy key and name must be supplied together")
        if len(self.secondary_skill_names) != len(self.secondary_skill_keys):
            raise ValueError("starter secondary skill keys and names must align")
        _ensure_authored_text(
            {
                "primarySkillName": self.primary_skill_name,
                "secondarySkillNames": self.secondary_skill_names,
                "expectedAscendancyName": self.expected_ascendancy_name,
            }
        )
        return self


class TargetAnchorIdentity(StageFamilyIdentity):
    ascendancy_name: str = Field(min_length=1, max_length=120)
    primary_skill_name: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def _safe_names(self) -> "TargetAnchorIdentity":
        if len(self.secondary_skill_names) != len(self.secondary_skill_keys):
            raise ValueError("target core secondary skill keys and names must align")
        _ensure_authored_text(
            {
                "ascendancyName": self.ascendancy_name,
                "primarySkillName": self.primary_skill_name,
                "secondarySkillNames": self.secondary_skill_names,
            }
        )
        return self


class TargetFamilyConstraint(models.StrictModel):
    """Optional user constraint for target discovery; a full locked identity skips comparison."""

    ascendancy_key: str | None = Field(default=None, min_length=3, max_length=240)
    primary_skill_key: str | None = Field(default=None, min_length=3, max_length=240)
    build_family_key: str | None = Field(default=None, min_length=3, max_length=240)
    locked_identity: TargetAnchorIdentity | None = None

    @model_validator(mode="after")
    def _coherent_constraint(self) -> "TargetFamilyConstraint":
        refs = [
            value
            for value in (
                self.ascendancy_key,
                self.primary_skill_key,
                self.build_family_key,
            )
            if value is not None
        ]
        if not refs and self.locked_identity is None:
            raise ValueError("target Family constraint must contain at least one filter")
        _safe_refs(refs)
        if self.ascendancy_key and not self.ascendancy_key.startswith("ascendancy:"):
            raise ValueError("target ascendancy constraint must use a resolved ascendancy key")
        if self.primary_skill_key and not self.primary_skill_key.startswith("skill:"):
            raise ValueError("target skill constraint must use a resolved active-skill key")
        if self.locked_identity is not None:
            if self.build_family_key is None:
                raise ValueError("a locked target identity requires its exact build Family key")
            if self.ascendancy_key not in {
                None,
                self.locked_identity.ascendancy_key,
            } or self.primary_skill_key not in {None, self.locked_identity.primary_skill_key}:
                raise ValueError("locked target identity must agree with Family filters")
        return self

    @property
    def is_user_locked(self) -> bool:
        return self.locked_identity is not None


class StageOptimizationPolicy(models.StrictModel):
    mode: Literal["early_minimal", "stage_targeted", "target_anchor_targeted"]
    loadout_scope: Literal["minimal_mechanism_shell", "stage_complete_loadout"]
    required_objectives: list[OptimizationObjective] = Field(min_length=3, max_length=7)
    advisory_objectives: list[OptimizationObjective] = Field(default_factory=list, max_length=7)
    excluded_objectives: list[ExcludedOptimizationObjective] = Field(min_length=2, max_length=6)
    outside_mask_findings: Literal["report_only_no_retry"] = "report_only_no_retry"
    global_optimizer_allowed: Literal[False] = False
    passive_tree_optimization_mode: Literal["manual_targeted"] = "manual_targeted"
    judge_elemental_resistance_policy: Literal[
        "diagnostic_only",
        "endgame_minimums_60_30",
    ] = "diagnostic_only"
    mutation_batch_preferred: Literal[True] = True
    quality_goal: Literal[
        "legacy_early_policy",
        "complete_stage_build",
    ] = "complete_stage_build"
    mutation_strategy: Literal["single_initialization_then_function_scoped_deltas"] = (
        "single_initialization_then_function_scoped_deltas"
    )
    design_change_policy: Literal["blueprint_declared_or_versioned_replan_only"] = (
        "blueprint_declared_or_versioned_replan_only"
    )

    @model_validator(mode="before")
    @classmethod
    def _preserve_legacy_quality_goal(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "qualityGoal" in value or "quality_goal" in value:
            return value
        normalized = dict(value)
        normalized["quality_goal"] = (
            "legacy_early_policy"
            if normalized.get("mode") == "early_minimal"
            else "complete_stage_build"
        )
        return normalized

    @model_validator(mode="after")
    def _coherent_mask(self) -> "StageOptimizationPolicy":
        if len(self.required_objectives) != len(set(self.required_objectives)):
            raise ValueError("required optimization objectives must be unique")
        if len(self.advisory_objectives) != len(set(self.advisory_objectives)):
            raise ValueError("advisory optimization objectives must be unique")
        if len(self.excluded_objectives) != len(set(self.excluded_objectives)):
            raise ValueError("excluded optimization objectives must be unique")
        if set(self.required_objectives) & set(self.advisory_objectives):
            raise ValueError("required and advisory optimization objectives cannot overlap")
        if self.mode == "early_minimal":
            if self.quality_goal != "legacy_early_policy":
                raise ValueError("legacy early policy cannot claim a complete stage quality goal")
            if self.loadout_scope != "minimal_mechanism_shell":
                raise ValueError("early_minimal requires only a minimal mechanism shell")
            expected = {
                "skill_availability",
                "weapon_compatibility",
                "resource_sustain",
            }
            if set(self.required_objectives) != expected or self.advisory_objectives:
                raise ValueError(
                    "early_minimal keeps only skill availability, weapon compatibility and "
                    "resource sustain"
                )
            required_exclusions = {
                "elemental_resistance_judgment",
                "global_whole_build_optimization",
                "global_passive_tree_optimization",
                "offense_quality_chasing",
                "defense_quality_chasing",
                "full_gear_optimization",
            }
            if set(self.excluded_objectives) != required_exclusions:
                raise ValueError("early_minimal must exclude every non-essential optimization")
        else:
            if self.quality_goal != "complete_stage_build":
                raise ValueError("new stage policies require a complete stage quality goal")
            if self.loadout_scope != "stage_complete_loadout":
                raise ValueError("later stages and target anchors require a stage-complete loadout")
        return self


class MinimalTargetCandidate(models.StrictModel):
    candidate_id: str = Field(pattern=r"^target-candidate:[A-Za-z0-9\-]{3,100}$")
    build_family_key: str = Field(min_length=3, max_length=240)
    family_discovery_ref: str = Field(pattern=r"^dq-[A-Fa-f0-9]{16}$")
    identity: TargetAnchorIdentity
    mechanism_summary: str = Field(min_length=1, max_length=500)
    expected_strengths: list[str] = Field(min_length=1, max_length=6)
    known_risks: list[str] = Field(min_length=1, max_length=6)
    evidence_refs: list[str] = Field(min_length=1, max_length=10)
    global_optimizer_used: Literal[False] = False
    full_judge_used: Literal[False] = False

    @model_validator(mode="after")
    def _safe_candidate(self) -> "MinimalTargetCandidate":
        # The discovery receipt is deliberately repeated in evidence_refs so the
        # candidate stays independently auditable.  Validate the identity and
        # evidence collections separately instead of treating that required
        # repetition as a duplicate reference.
        _safe_refs([self.build_family_key])
        _safe_refs(self.evidence_refs)
        if self.family_discovery_ref not in self.evidence_refs:
            raise ValueError("target candidate evidence must include its discovery receipt")
        _ensure_authored_text(
            {
                "mechanismSummary": self.mechanism_summary,
                "expectedStrengths": self.expected_strengths,
                "knownRisks": self.known_risks,
            }
        )
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


class TargetCandidateDimensionComparison(models.StrictModel):
    dimension: Literal[
        "mechanism_closure",
        "research_support",
        "goal_fit_and_power_evidence",
        "playability_risk",
        "modelability",
    ]
    preferred_candidate_id: str | None = Field(
        default=None,
        pattern=r"^target-candidate:[A-Za-z0-9\-]{3,100}$",
    )
    summary: str = Field(min_length=1, max_length=320)

    @model_validator(mode="after")
    def _safe_summary(self) -> "TargetCandidateDimensionComparison":
        _ensure_authored_text({"summary": self.summary})
        return self


class TargetCandidateSelection(models.StrictModel):
    selection_id: str = Field(pattern=r"^target-selection:[A-Za-z0-9\-]{3,100}$")
    family_discovery_ref: str = Field(pattern=r"^dq-[A-Fa-f0-9]{16}$")
    candidates: list[MinimalTargetCandidate] = Field(min_length=2, max_length=10)
    dimension_comparisons: list[TargetCandidateDimensionComparison] = Field(
        min_length=5,
        max_length=5,
    )
    candidate_ranking: list[str] = Field(min_length=2, max_length=10)
    selected_candidate_id: str = Field(pattern=r"^target-candidate:[A-Za-z0-9\-]{3,100}$")
    selection_summary: str = Field(min_length=1, max_length=600)
    unresolved_risks: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _complete_distinct_candidate_ranking(self) -> "TargetCandidateSelection":
        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("target selection requires distinct candidate ids")
        if any(item.family_discovery_ref != self.family_discovery_ref for item in self.candidates):
            raise ValueError("all target candidates must use the same discovery receipt")
        family_keys = [item.build_family_key for item in self.candidates]
        if len(set(family_keys)) != len(family_keys):
            raise ValueError("target selection requires distinct build Families")
        signatures = {
            (
                item.identity.ascendancy_key,
                item.identity.primary_skill_key,
                tuple(item.identity.secondary_skill_keys),
                item.mechanism_summary.strip().casefold(),
            )
            for item in self.candidates
        }
        if len(signatures) != len(self.candidates):
            raise ValueError("target selection requires materially distinct target designs")
        if self.selected_candidate_id not in candidate_ids:
            raise ValueError("selected target candidate must be one of the compared candidates")
        if (
            len(self.candidate_ranking) != len(candidate_ids)
            or set(self.candidate_ranking) != set(candidate_ids)
            or len(set(self.candidate_ranking)) != len(candidate_ids)
        ):
            raise ValueError("candidate ranking must be a complete permutation")
        if self.candidate_ranking[0] != self.selected_candidate_id:
            raise ValueError("the first ranked candidate must be selected")
        expected_dimensions = {
            "mechanism_closure",
            "research_support",
            "goal_fit_and_power_evidence",
            "playability_risk",
            "modelability",
        }
        actual_dimensions = {item.dimension for item in self.dimension_comparisons}
        if actual_dimensions != expected_dimensions or len(actual_dimensions) != len(
            self.dimension_comparisons
        ):
            raise ValueError("target selection must compare every minimal dimension exactly once")
        for comparison in self.dimension_comparisons:
            if (
                comparison.preferred_candidate_id is not None
                and comparison.preferred_candidate_id not in candidate_ids
            ):
                raise ValueError("dimension preference must reference a compared candidate")
        decisive_dimensions = {
            item.dimension
            for item in self.dimension_comparisons
            if item.preferred_candidate_id == self.selected_candidate_id
        }
        if not decisive_dimensions.intersection(
            {
                "mechanism_closure",
                "research_support",
                "goal_fit_and_power_evidence",
            }
        ):
            raise ValueError(
                "modelability alone cannot select a target without an advantage in a core dimension"
            )
        _ensure_authored_text(
            {
                "selectionSummary": self.selection_summary,
                "unresolvedRisks": self.unresolved_risks,
            }
        )
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self

    @property
    def selected_candidate(self) -> MinimalTargetCandidate:
        return next(
            item for item in self.candidates if item.candidate_id == self.selected_candidate_id
        )

    @property
    def reserve_candidate(self) -> MinimalTargetCandidate:
        reserve_id = self.candidate_ranking[1]
        return next(item for item in self.candidates if item.candidate_id == reserve_id)


class TargetCandidateSelectionPacket(models.VersionedSafeModel):
    progression_id: str = Field(pattern=r"^[0-9a-f\-]{36}$")
    base_class: str = Field(min_length=1, max_length=80)
    target_level: int = Field(ge=2, le=100)
    goal: str = Field(min_length=1, max_length=600)
    class_key: str = Field(min_length=3, max_length=240)
    candidate_count_requested: Literal[10] = 10
    minimum_candidate_count: Literal[2] = 2
    maximum_candidate_count: Literal[10] = 10
    family_filters: dict[str, str] = Field(default_factory=dict)
    comparison_scope: list[
        Literal[
            "mechanism_closure",
            "research_support",
            "goal_fit_and_power_evidence",
            "playability_risk",
            "modelability",
        ]
    ] = Field(
        default_factory=lambda: [
            "mechanism_closure",
            "research_support",
            "goal_fit_and_power_evidence",
            "playability_risk",
            "modelability",
        ],
        min_length=5,
        max_length=5,
    )
    full_judge_required: Literal[False] = False
    global_optimizer_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _safe_packet(self) -> "TargetCandidateSelectionPacket":
        _ensure_authored_text({"baseClass": self.base_class, "goal": self.goal})
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


class TargetDesignDimensionEvidence(models.StrictModel):
    dimension: TargetCoverageDimension
    status: TargetCoverageStatus
    summary: str = Field(min_length=1, max_length=320)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    caveat: str | None = Field(default=None, min_length=1, max_length=320)

    @model_validator(mode="after")
    def _traceable(self) -> "TargetDesignDimensionEvidence":
        _safe_refs(self.evidence_refs)
        if self.status in {"research_adopted", "independently_verified"} and not self.evidence_refs:
            raise ValueError("verified target design coverage requires evidence")
        if self.status == "unavailable_with_caveat" and not self.caveat:
            raise ValueError("unavailable target design coverage requires a caveat")
        if self.status != "unavailable_with_caveat" and self.caveat is not None:
            raise ValueError("only unavailable target design coverage may carry a caveat")
        _ensure_authored_text({"summary": self.summary, "caveat": self.caveat})
        return self


class TargetDesignCoverage(models.StrictModel):
    coverage_id: str = Field(pattern=r"^target-coverage:[A-Za-z0-9\-]{3,100}$")
    dimensions: list[TargetDesignDimensionEvidence] = Field(min_length=10, max_length=10)
    acceptance_summary: str = Field(min_length=1, max_length=600)
    unresolved_caveats: list[str] = Field(default_factory=list, max_length=12)
    agent_acceptance: Literal["accepted"]

    @model_validator(mode="after")
    def _complete(self) -> "TargetDesignCoverage":
        expected = {
            "skill_package",
            "clear_duty",
            "boss_duty",
            "damage_delivery",
            "ascendancy_and_passives",
            "gear_synergy",
            "defense_and_recovery",
            "resource_and_spirit",
            "combat_configuration",
            "modelability",
        }
        actual = {item.dimension for item in self.dimensions}
        if actual != expected or len(actual) != len(self.dimensions):
            raise ValueError("target design coverage must contain every dimension exactly once")
        if any(item.status == "rejected" for item in self.dimensions):
            raise ValueError("a rejected target design dimension cannot anchor a progression")
        _ensure_authored_text(
            {
                "acceptanceSummary": self.acceptance_summary,
                "unresolvedCaveats": self.unresolved_caveats,
            }
        )
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


class TargetAnchorCreatePacket(models.VersionedSafeModel):
    progression_id: str = Field(pattern=r"^[0-9a-f\-]{36}$")
    base_class: str = Field(min_length=1, max_length=80)
    target_level: int = Field(ge=2, le=100)
    goal: str = Field(min_length=1, max_length=600)
    create_mode: Literal["standard_single_stage"] = "standard_single_stage"
    build_from_blank: Literal[True] = True
    research_memory_policy: Literal["progressive_actual_queries"] = "progressive_actual_queries"
    judge_policy: Literal["advisory_only"] = "advisory_only"
    candidate_selection_required: bool = False
    selected_build_family_key: str | None = Field(default=None, min_length=3, max_length=240)
    selected_candidate_id: str | None = Field(
        default=None,
        pattern=r"^target-candidate:[A-Za-z0-9\-]{3,100}$",
    )
    selected_target_identity: TargetAnchorIdentity | None = None
    selected_candidate: MinimalTargetCandidate | None = None
    optimization_policy: StageOptimizationPolicy | None = None
    global_optimizer_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _safe_packet(self) -> "TargetAnchorCreatePacket":
        expected_policy = target_anchor_optimization_policy(self.target_level)
        if self.optimization_policy is None:
            self.optimization_policy = expected_policy
        elif self.optimization_policy != expected_policy:
            raise ValueError("target optimization policy does not match the target level")
        if self.candidate_selection_required and (
            self.selected_candidate_id is None
            or self.selected_build_family_key is None
            or self.selected_target_identity is None
            or self.selected_candidate is None
        ):
            raise ValueError("selected target candidate is required before target Create")
        if self.selected_candidate is not None and (
            self.selected_candidate_id != self.selected_candidate.candidate_id
            or self.selected_build_family_key != self.selected_candidate.build_family_key
            or self.selected_target_identity != self.selected_candidate.identity
        ):
            raise ValueError("selected target candidate packet fields must agree")
        if self.selected_build_family_key is not None:
            _safe_refs([self.selected_build_family_key])
        _ensure_authored_text(
            {
                "baseClass": self.base_class,
                "goal": self.goal,
            }
        )
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


class StageBlueprint(models.StrictModel):
    stage_id: str = Field(pattern=r"^stage:[A-Za-z0-9\-]{3,100}$")
    lifecycle_stage: models.LIFECYCLE_STAGE
    route_role: RouteRole
    target_level: int = Field(ge=2, le=100)
    knowledge_mode: StageKnowledgeMode = "family_exact"
    family_identity: StageFamilyIdentity | None = None
    starter_identity: StarterStageIdentity | None = None
    ascendancy_intent: str = Field(min_length=1, max_length=120)
    primary_skill_intent: str = Field(min_length=1, max_length=160)
    skill_package_intents: list[str] = Field(min_length=1, max_length=8)
    passive_anchor_intents: list[str] = Field(default_factory=list, max_length=12)
    gear_role_intents: list[str] = Field(default_factory=list, max_length=12)
    responsibility_coverage: list[Responsibility] = Field(min_length=4, max_length=6)
    evidence_status: EvidenceStatus = "limited"
    entry_bridge: TransitionBridge | None = None
    expected_cost_band: CostBand = "unknown"
    research_query_refs: list[str] = Field(default_factory=list, max_length=8)
    common_knowledge_refs: list[str] = Field(default_factory=list, max_length=12)
    rebuild_from_scratch: bool = False
    rebuild_reason: str | None = Field(default=None, min_length=8, max_length=400)

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
        _safe_refs(self.common_knowledge_refs)
        if self.knowledge_mode == "family_exact":
            if self.family_identity is None or self.starter_identity is not None:
                raise ValueError("family_exact stages require only a resolved Family identity")
            if not self.research_query_refs:
                raise ValueError("family_exact stages require a Research query ref")
        else:
            if self.route_role not in {"starter_bootstrap", "starter_established"}:
                raise ValueError("starter_common knowledge is limited to starter stages")
            if self.starter_identity is None or self.family_identity is not None:
                raise ValueError("starter_common stages require only a starter skill identity")
            if self.research_query_refs:
                raise ValueError("starter_common stages cannot claim mature Family Research")
            if not self.common_knowledge_refs:
                raise ValueError("starter_common stages require public/starter evidence refs")
        _ensure_authored_text(
            {
                "ascendancyIntent": self.ascendancy_intent,
                "primarySkillIntent": self.primary_skill_intent,
                "skillPackageIntents": self.skill_package_intents,
                "passiveAnchorIntents": self.passive_anchor_intents,
                "gearRoleIntents": self.gear_role_intents,
                "rebuildReason": self.rebuild_reason,
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
    target_anchor_artifact_id: str | None = Field(
        default=None,
        pattern=r"^final-build:[A-Za-z0-9\-]{3,100}$",
    )
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
                stage.knowledge_mode == "family_exact"
                and previous_family is not None
                and stage.family_identity != previous_family
                and not (current_queries - seen_queries)
            ):
                raise ValueError("a changed stage Family requires a fresh Research query ref")
            seen_queries.update(current_queries)
            previous_family = (
                stage.family_identity if stage.knowledge_mode == "family_exact" else None
            )
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
    target_anchor_artifact_id: str | None = Field(
        default=None,
        pattern=r"^final-build:[A-Za-z0-9\-]{3,100}$",
    )
    starter_research_packet_id: str = Field(pattern=r"^starter-research:[A-Za-z0-9\-]{3,100}$")
    starter_evidence_use: StarterEvidenceUse
    progression_bound: bool = True
    requires_phase5_run: bool = True
    research_memory_policy: Literal[
        "progressive_actual_queries",
        "starter_common_no_family_memory",
    ] = "progressive_actual_queries"
    generation_memory_mode: Literal["standard", "memory_assisted"] = "memory_assisted"
    optimization_policy: StageOptimizationPolicy | None = None
    global_optimizer_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _bound(self) -> "StageCreatePacket":
        if not self.progression_bound:
            raise ValueError("stage packet must be progression-bound")
        if self.stage.target_level != self.target_level:
            raise ValueError("stage packet target level mismatch")
        if self.target_level > self.route_target_level:
            raise ValueError("stage target cannot exceed route target")
        if self.requires_phase5_run and self.target_anchor_artifact_id is not None:
            raise ValueError("ordinary progression stages cannot carry a target anchor")
        if not self.requires_phase5_run and (
            self.stage.route_role != "target" or self.target_anchor_artifact_id is None
        ):
            raise ValueError("anchor closure packets require the target stage and artifact")
        if self.stage.knowledge_mode == "starter_common":
            if (
                self.research_memory_policy != "starter_common_no_family_memory"
                or self.generation_memory_mode != "standard"
            ):
                raise ValueError("starter_common stages must use the standard no-Family lane")
        elif (
            self.research_memory_policy != "progressive_actual_queries"
            or self.generation_memory_mode != "memory_assisted"
        ):
            raise ValueError("family_exact stages must use the memory-assisted Family lane")
        expected_policy = stage_optimization_policy(self.stage)
        if self.optimization_policy is None:
            self.optimization_policy = expected_policy
        elif self.optimization_policy != expected_policy and not (
            str(self.stage.lifecycle_stage) == "campaign_early"
            and self.optimization_policy.mode == "early_minimal"
        ):
            raise ValueError("stage optimization policy does not match the lifecycle stage")
        return self


def target_anchor_optimization_policy(target_level: int | None = None) -> StageOptimizationPolicy:
    endgame = int(target_level or 0) >= 80
    return StageOptimizationPolicy(
        mode="target_anchor_targeted",
        loadout_scope="stage_complete_loadout",
        required_objectives=[
            "skill_availability",
            "weapon_compatibility",
            "resource_sustain",
            "damage_delivery",
            "defense_layers",
            "gear_legality",
            "lifecycle_readiness",
        ],
        advisory_objectives=[],
        excluded_objectives=[
            *([] if endgame else ["elemental_resistance_judgment"]),
            "global_whole_build_optimization",
            "global_passive_tree_optimization",
        ],
        judge_elemental_resistance_policy=(
            "endgame_minimums_60_30" if endgame else "diagnostic_only"
        ),
    )


def stage_optimization_policy(stage: StageBlueprint) -> StageOptimizationPolicy:
    endgame = stage.target_level >= 80
    return StageOptimizationPolicy(
        mode="stage_targeted",
        loadout_scope="stage_complete_loadout",
        required_objectives=[
            "skill_availability",
            "weapon_compatibility",
            "resource_sustain",
            "damage_delivery",
            "defense_layers",
            "gear_legality",
            "lifecycle_readiness",
        ],
        advisory_objectives=[],
        excluded_objectives=[
            *([] if endgame else ["elemental_resistance_judgment"]),
            "global_whole_build_optimization",
            "global_passive_tree_optimization",
        ],
        judge_elemental_resistance_policy=(
            "endgame_minimums_60_30" if endgame else "diagnostic_only"
        ),
    )


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
