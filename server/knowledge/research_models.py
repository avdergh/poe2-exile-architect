"""Strict Phase 4 research-memory proposal contracts."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import graph_tools


StableKey = Annotated[str, Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9_.:/\-']+$")]

CONFIDENCE = {"low", "medium", "high"}
OBSERVATION_AXES = {
    "identity",
    "character_shell",
    "primary_skill_package",
    "secondary_skill_package",
    "passive_tree_shape",
    "itemization",
    "scaling_axis",
    "resource_engine",
    "defense_layers",
    "mechanic_engine",
    "rotation_playstyle",
    "transition_gates",
    "failure_modes",
    "variant_relations",
    "modelability_caveats",
}
COMPONENT_ROLES = {
    "primary_damage",
    "clear_skill",
    "boss_skill",
    "generator",
    "payoff",
    "reservation",
    "defensive_buff",
    "ascendancy_shell",
    "movement",
    "trigger_host",
    "support_modifier",
    "unique_enabler",
    "transition_gate",
    "passive_anchor",
    "keystone_transformer",
    "gear_base",
    "weapon_base",
    "scaling_stat",
    "defense_layer",
    "resource_engine",
    "secondary_skill",
    "triggered_payload",
    "control_skill",
}
ASCENDANCY_RESPONSIBILITY_ROLES = {
    "generator",
    "payoff",
    "transition_gate",
    "passive_anchor",
    "keystone_transformer",
    "scaling_stat",
    "defense_layer",
    "resource_engine",
}
GEAR_RESPONSIBILITY_TYPES = {
    "primary_skill_source",
    "identity_enabler",
    "scaling",
    "resource_or_spirit",
    "defense",
    "recovery",
    "utility",
    "optional_upgrade",
    "budget_substitute",
}
PATTERN_CONFIDENCE_TIERS = {
    "case_observation",
    "recurring_observation",
    "likely_pattern",
    "common_within_archetype",
    "strong_ranking_hint",
}
PATTERN_TRANSFER_SCOPES = {"family", "component", "global"}
TRANSFERABLE_PATTERN_MAX_CONFIDENCE = "likely_pattern"
VISIBILITY_SPLITS = {
    ("creator_visible", "train_context"),
    ("evaluator_only", "eval_holdout"),
    ("quarantined", "quarantine"),
}

DEEP_RESEARCH_RECORD_KINDS = {
    "skill_package",
    "mechanic_chain",
    "rotation",
    "gear_synergy",
    "passive_package",
    "defense_engine",
    "resource_engine",
    "design_tradeoff",
    "failure_mode",
    "modelability_caveat",
    "variant_comparison",
    "class_or_ascendancy_principle",
    "open_question",
}
IDENTITY_TAG_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LifecycleStageRequirement(StrictModel):
    context_type: Literal["lifecycle_stage_requirement"]
    stages: list[str] = Field(min_length=1)


class TransitionGateRequirement(StrictModel):
    context_type: Literal["transition_gate_requirement"]
    gate: str


class VerificationGateRequirement(StrictModel):
    context_type: Literal["verification_gate_requirement"]
    task: str


class ResourceThresholdRequirement(StrictModel):
    context_type: Literal["resource_threshold_requirement"]
    resource: str
    minimum: int | float


class SpiritReservationRequirement(StrictModel):
    context_type: Literal["spirit_reservation_requirement"]
    reservation_state: str


class ItemRoleRequirement(StrictModel):
    context_type: Literal["item_role_requirement"]
    role: str
    component_key: str | None = None


class WeaponSetRequirement(StrictModel):
    context_type: Literal["weapon_set_requirement"]
    active_weapon_set: int = Field(ge=1, le=2)


class SocketRequirement(StrictModel):
    context_type: Literal["socket_requirement"]
    skill_key: str
    support_key: str | None = None


ResearchContextRequirement = Annotated[
    graph_tools.VersionContext
    | graph_tools.ItemContext
    | graph_tools.SocketContext
    | graph_tools.PassiveContext
    | LifecycleStageRequirement
    | TransitionGateRequirement
    | VerificationGateRequirement
    | ResourceThresholdRequirement
    | SpiritReservationRequirement
    | ItemRoleRequirement
    | WeaponSetRequirement
    | SocketRequirement,
    Field(discriminator="context_type"),
]


class CleanFragmentProposal(StrictModel):
    fragment_type: str
    title: str
    summary: str
    reusable_principle: str
    source_case_refs: list[str] = Field(min_length=1)
    safe_evidence_refs: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    copyability_risk: Literal["low", "medium"]
    lifecycle_stages: list[str] = Field(default_factory=list)
    modelability: Literal["full", "partial", "not_modelable", "unknown"]
    verification_tasks: list[str] = Field(min_length=1)
    component_keys: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    game_patch: str
    passive_tree_version: str
    pob_version_or_commit: str
    visibility: Literal["creator_visible", "evaluator_only", "quarantined"]
    split: Literal["train_context", "eval_holdout", "quarantine"]
    knowledge_scope: Literal["global_seed", "local_user", "eval_ephemeral"]


class EndpointResolutionEvidence(StrictModel):
    tool_name: Literal["resolve_graph_component"]
    status: Literal["resolved"]
    stable_key: StableKey
    snapshot_id: str = Field(min_length=1)
    evidence_path_nodes: list[StableKey] = Field(min_length=1)
    source_refs: list[str] = Field(default_factory=list)


class BuildDesignComponent(StrictModel):
    component_key: StableKey
    role: Literal[
        "primary_damage",
        "clear_skill",
        "boss_skill",
        "generator",
        "payoff",
        "reservation",
        "defensive_buff",
        "ascendancy_shell",
        "movement",
        "trigger_host",
        "support_modifier",
        "unique_enabler",
        "transition_gate",
        "passive_anchor",
        "keystone_transformer",
        "gear_base",
        "weapon_base",
        "scaling_stat",
        "defense_layer",
        "resource_engine",
        "secondary_skill",
        "triggered_payload",
        "control_skill",
    ]
    resolution: EndpointResolutionEvidence | None = None


class BuildDesignObservation(StrictModel):
    observation_type: Literal[
        "build_archetype",
        "cooccurrence",
        "transition_gate",
        "failure_pattern",
        "planner_hint",
        "modelability_caveat",
    ]
    title: str
    summary: str
    axes: list[
        Literal[
            "identity",
            "character_shell",
            "primary_skill_package",
            "secondary_skill_package",
            "passive_tree_shape",
            "itemization",
            "scaling_axis",
            "resource_engine",
            "defense_layers",
            "mechanic_engine",
            "rotation_playstyle",
            "transition_gates",
            "failure_modes",
            "variant_relations",
            "modelability_caveats",
        ]
    ] = Field(min_length=1)
    components: list[BuildDesignComponent] = Field(default_factory=list)
    source_case_refs: list[str] = Field(min_length=1)
    safe_evidence_refs: list[str] = Field(default_factory=list)
    game_patch: str
    passive_tree_version: str
    pob_version_or_commit: str
    visibility: Literal["creator_visible", "evaluator_only", "quarantined"]
    split: Literal["train_context", "eval_holdout", "quarantine"]
    knowledge_scope: Literal["global_seed", "local_user", "eval_ephemeral"]


class BuildPatternProposal(StrictModel):
    pattern_type: Literal[
        "build_archetype",
        "cooccurrence",
        "transition_gate",
        "failure_pattern",
        "planner_hint",
    ]
    title: str
    summary: str
    component_keys: list[StableKey] = Field(min_length=2)
    component_roles: dict[
        str,
        Literal[
            "primary_damage",
            "clear_skill",
            "boss_skill",
            "generator",
            "payoff",
            "reservation",
            "defensive_buff",
            "ascendancy_shell",
            "movement",
            "trigger_host",
            "support_modifier",
            "unique_enabler",
            "transition_gate",
            "passive_anchor",
            "keystone_transformer",
            "gear_base",
            "weapon_base",
            "scaling_stat",
            "defense_layer",
            "resource_engine",
            "secondary_skill",
            "triggered_payload",
            "control_skill",
        ],
    ] = Field(default_factory=dict)
    confidence_tier: Literal[
        "case_observation",
        "recurring_observation",
        "likely_pattern",
        "common_within_archetype",
        "strong_ranking_hint",
    ]
    transfer_scope: Literal["family", "component", "global"] = "family"
    applicability_axes: list[
        Literal[
            "identity",
            "character_shell",
            "primary_skill_package",
            "secondary_skill_package",
            "passive_tree_shape",
            "itemization",
            "scaling_axis",
            "resource_engine",
            "defense_layers",
            "mechanic_engine",
            "rotation_playstyle",
            "transition_gates",
            "failure_modes",
            "variant_relations",
            "modelability_caveats",
        ]
    ] = Field(default_factory=list)
    applicability_requirements: list[str] = Field(default_factory=list)
    exclusion_conditions: list[str] = Field(default_factory=list)
    transfer_rationale: str | None = None
    origin_family_keys: list[StableKey] = Field(default_factory=list)
    sample_count: int = Field(ge=1)
    family_count: int = Field(ge=1)
    source_diversity_count: int = Field(ge=1)
    denominator: int | None = Field(default=None, ge=1)
    source_case_refs: list[str] = Field(min_length=1)
    safe_evidence_refs: list[str] = Field(default_factory=list)
    context_requirements: list[ResearchContextRequirement] = Field(default_factory=list)
    planner_hint: str | None = None
    verification_tasks: list[str] = Field(default_factory=list)
    game_patch: str
    passive_tree_version: str
    pob_version_or_commit: str
    visibility: Literal["creator_visible", "evaluator_only", "quarantined"]
    split: Literal["train_context", "eval_holdout", "quarantine"]
    knowledge_scope: Literal["global_seed", "local_user", "eval_ephemeral"]

    @model_validator(mode="after")
    def _component_roles_align(self) -> "BuildPatternProposal":
        component_keys = set(self.component_keys)
        if len(component_keys) < 2:
            raise ValueError("durable build patterns require at least two distinct components")
        role_keys = set(self.component_roles)
        if role_keys != component_keys:
            raise ValueError("component_roles keys must exactly match component_keys")
        if self.transfer_scope != "family":
            if not self.applicability_axes:
                raise ValueError("transferable patterns require applicability_axes")
            if not self.applicability_requirements:
                raise ValueError("transferable patterns require applicability_requirements")
            if not self.exclusion_conditions:
                raise ValueError("transferable patterns require exclusion_conditions")
            if not str(self.transfer_rationale or "").strip():
                raise ValueError("transferable patterns require transfer_rationale")
            if not self.verification_tasks:
                raise ValueError("transferable patterns require verification_tasks")
        if self.transfer_scope == "component":
            distinct_families = set(self.origin_family_keys)
            if not distinct_families:
                raise ValueError("component patterns require origin_family_keys")
            if self.family_count != len(distinct_families):
                raise ValueError(
                    "component pattern family_count must match distinct origin_family_keys"
                )
        return self


class SemanticEdgeProposal(StrictModel):
    source_key: StableKey
    target_key: StableKey
    source_resolution: EndpointResolutionEvidence | None = None
    target_resolution: EndpointResolutionEvidence | None = None
    edge_type: Literal[
        "enables_mechanic",
        "scales_with",
        "mitigates_weakness_of",
        "creates_failure_risk_for",
        "requires_transition_gate",
        "has_modelability_caveat",
        "synergizes_with",
    ]
    rationale: str
    source_case_refs: list[str] = Field(min_length=1)
    safe_evidence_refs: list[str] = Field(default_factory=list)
    game_patch: str
    passive_tree_version: str
    pob_version_or_commit: str
    status: Literal["valid", "needs_revalidation", "stale", "rejected", "deprecated", "quarantined"]
    confidence: Literal["low", "medium", "high"]
    modelability: Literal["full", "partial", "not_modelable", "unknown"]
    copy_safety_state: Literal["passed", "needs_review", "rejected"]
    context_requirements: list[ResearchContextRequirement] = Field(min_length=1)
    affected_component_keys: list[StableKey] = Field(min_length=1)
    visibility: Literal["creator_visible", "evaluator_only", "quarantined"]
    split: Literal["train_context", "eval_holdout", "quarantine"]
    knowledge_scope: Literal["global_seed", "local_user", "eval_ephemeral"]
    directionality: Literal["directional", "associative"]


class DeepResearchComponentMention(StrictModel):
    candidate_name: str = Field(min_length=1, max_length=160)
    role: Literal[
        "primary_damage",
        "clear_skill",
        "boss_skill",
        "generator",
        "payoff",
        "reservation",
        "defensive_buff",
        "ascendancy_shell",
        "movement",
        "trigger_host",
        "support_modifier",
        "unique_enabler",
        "transition_gate",
        "passive_anchor",
        "keystone_transformer",
        "gear_base",
        "weapon_base",
        "scaling_stat",
        "defense_layer",
        "resource_engine",
        "secondary_skill",
        "triggered_payload",
        "control_skill",
    ]
    resolver_query: str = Field(min_length=1, max_length=240)
    expected_node_types: list[str] = Field(default_factory=list, max_length=12)
    scope: Literal["any", "player"] = "any"
    component_key: StableKey | None = None
    resolution_status: Literal["resolved", "ambiguous", "missing", "type_mismatch"]


class DeepResearchRecordProposal(StrictModel):
    research_group_id: str = Field(min_length=1, max_length=240)
    record_kind: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=280)
    content: str = Field(min_length=1)
    content_language: Literal["zh-CN", "en"]
    length_exception_reason: str | None = Field(default=None, max_length=240)
    component_keys: list[StableKey] = Field(default_factory=list)
    component_mentions: list[DeepResearchComponentMention] = Field(default_factory=list)
    source_case_refs: list[str] = Field(min_length=1)
    safe_evidence_refs: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    failure_conditions: list[str] = Field(default_factory=list)
    typed_payload: dict[str, Any] = Field(default_factory=dict)
    class_key: StableKey | None = None
    ascendancy_key: StableKey | None = None
    extraction_method_version: str = Field(min_length=1)
    record_schema_version: Literal[1]
    game_patch: str
    passive_tree_version: str
    pob_version_or_commit: str
    visibility: Literal["creator_visible", "evaluator_only", "quarantined"]
    split: Literal["train_context", "eval_holdout", "quarantine"]
    knowledge_scope: Literal["global_seed", "local_user", "eval_ephemeral"]
    status: Literal["valid", "needs_revalidation", "stale", "deprecated", "quarantined"] = "valid"
    copy_safety_state: Literal["passed", "needs_review", "rejected"] = "passed"

    @model_validator(mode="after")
    def _content_budget(self) -> "DeepResearchRecordProposal":
        has_cjk = bool(re.search(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", self.content))
        if has_cjk and self.content_language != "zh-CN":
            raise ValueError("CJK content must use content_language=zh-CN for character budgeting")
        if self.content_language == "zh-CN":
            length = len(re.sub(r"\s+", "", self.content))
            over_budget = length > 400
            budget_name = "400 Chinese characters"
        else:
            length = len(re.findall(r"\b[\w'-]+\b", self.content, flags=re.UNICODE))
            over_budget = length > 250
            budget_name = "250 English words"
        if over_budget and not str(self.length_exception_reason or "").strip():
            raise ValueError(
                f"content exceeds {budget_name}; split the record or provide "
                "length_exception_reason for an indivisible mechanism chain"
            )
        return self

    @model_validator(mode="after")
    def _typed_identity_fields(self) -> "DeepResearchRecordProposal":
        for key in ("familyCoreSkillKeys", "resourceMechanisms"):
            if key not in self.typed_payload:
                continue
            values = self.typed_payload[key]
            if not isinstance(values, list) or not values:
                raise ValueError(f"typed_payload.{key} must be a non-empty list")
            if len(values) > 12 or any(not isinstance(value, str) for value in values):
                raise ValueError(f"typed_payload.{key} must contain at most 12 strings")
            if len(set(values)) != len(values):
                raise ValueError(f"typed_payload.{key} must not contain duplicates")
            if key == "familyCoreSkillKeys" and any(
                not re.fullmatch(r"skill:[A-Za-z0-9_.:/\-']+", value) for value in values
            ):
                raise ValueError(
                    "typed_payload.familyCoreSkillKeys must contain resolved skill stable keys"
                )
            if key == "familyCoreSkillKeys" and self.record_kind not in {
                "skill_package",
                "mechanic_chain",
            }:
                raise ValueError(
                    "typed_payload.familyCoreSkillKeys is only valid on confirmed skill_package or mechanic_chain records"
                )
            if key == "resourceMechanisms" and any(
                not IDENTITY_TAG_RE.fullmatch(value) for value in values
            ):
                raise ValueError(
                    "typed_payload.resourceMechanisms must contain lower_snake_case identity tags"
                )
        availability = self.typed_payload.get("availability")
        if availability is not None and availability not in {
            "standard",
            "source_specific_random",
        }:
            raise ValueError(
                "typed_payload.availability must be standard or source_specific_random"
            )
        physical_supports = {
            mention.component_key
            for mention in self.component_mentions
            if mention.component_key and mention.component_key.startswith("support:")
        }
        packages = self.typed_payload.get("supportPackages")
        if self.record_kind == "skill_package" and physical_supports and packages is None:
            raise ValueError(
                "skill_package records with resolved support gems require "
                "typed_payload.supportPackages"
            )
        if packages is not None:
            if not isinstance(packages, list) or len(packages) > 12:
                raise ValueError(
                    "typed_payload.supportPackages must be a list with at most 12 entries"
                )
            mentioned_skills = {
                mention.component_key
                for mention in self.component_mentions
                if mention.component_key and mention.component_key.startswith("skill:")
            }
            normalized_packages: set[tuple[str, tuple[str, ...]]] = set()
            packaged_supports: set[str] = set()
            for package in packages:
                if not isinstance(package, dict) or set(package) != {"skillKey", "supportKeys"}:
                    raise ValueError(
                        "each typed_payload.supportPackages entry must contain only skillKey and supportKeys"
                    )
                skill_key = package.get("skillKey")
                support_keys = package.get("supportKeys")
                if not isinstance(skill_key, str) or skill_key not in mentioned_skills:
                    raise ValueError(
                        "typed_payload.supportPackages skillKey must reference a resolved skill "
                        f"in the same record (unknown skillKey={skill_key!r}; resolved skills: "
                        + ", ".join(sorted(mentioned_skills))
                        + ")"
                    )
                if (
                    not isinstance(support_keys, list)
                    or not support_keys
                    or len(support_keys) > 12
                    or any(not isinstance(value, str) for value in support_keys)
                    or len(set(support_keys)) != len(support_keys)
                ):
                    raise ValueError(
                        "typed_payload.supportPackages supportKeys must be a non-empty unique string list"
                    )
                if any(
                    not value.startswith("support:") or value not in physical_supports
                    for value in support_keys
                ):
                    raise ValueError(
                        "typed_payload.supportPackages supportKeys must reference resolved "
                        "support gem components in the same record (unknown supportKeys: "
                        + ", ".join(
                            repr(value)
                            for value in support_keys
                            if not value.startswith("support:") or value not in physical_supports
                        )
                        + "; resolved supports: "
                        + ", ".join(sorted(physical_supports))
                        + ")"
                    )
                identity = (skill_key, tuple(sorted(support_keys)))
                if identity in normalized_packages:
                    raise ValueError("typed_payload.supportPackages must not contain duplicates")
                normalized_packages.add(identity)
                packaged_supports.update(support_keys)
            if self.record_kind == "skill_package" and packaged_supports != physical_supports:
                raise ValueError(
                    "skill_package supportPackages must assign every resolved support gem in the record"
                )
        support_exceptions = self.typed_payload.get("supportCoverageExceptions")
        if support_exceptions is not None:
            if not isinstance(support_exceptions, list) or len(support_exceptions) > 12:
                raise ValueError(
                    "typed_payload.supportCoverageExceptions must be a list with at most 12 entries"
                )
            mentioned_skills = {
                mention.component_key
                for mention in self.component_mentions
                if mention.component_key and mention.component_key.startswith("skill:")
            }
            seen_support_exceptions: set[str] = set()
            for exception in support_exceptions:
                if (
                    not isinstance(exception, dict)
                    or set(exception) != {"skillKey", "reason", "detail"}
                    or not isinstance(exception.get("skillKey"), str)
                    or exception["skillKey"] not in mentioned_skills
                    or exception.get("reason") not in {"source_coverage_gap", "not_applicable"}
                    or not isinstance(exception.get("detail"), str)
                    or not exception["detail"].strip()
                    or len(exception["detail"]) > 240
                    or exception["skillKey"] in seen_support_exceptions
                ):
                    raise ValueError(
                        "typed_payload.supportCoverageExceptions entries must reference a resolved skill and provide reason/detail"
                    )
                seen_support_exceptions.add(exception["skillKey"])
        source_specific_keys = self.typed_payload.get("sourceSpecificComponentKeys")
        if source_specific_keys is not None:
            if availability != "source_specific_random":
                raise ValueError(
                    "typed_payload.sourceSpecificComponentKeys requires availability=source_specific_random"
                )
            if (
                not isinstance(source_specific_keys, list)
                or not source_specific_keys
                or len(source_specific_keys) > 12
                or any(not isinstance(value, str) for value in source_specific_keys)
                or len(set(source_specific_keys)) != len(source_specific_keys)
                or any(value not in self.component_keys for value in source_specific_keys)
            ):
                raise ValueError(
                    "typed_payload.sourceSpecificComponentKeys must reference unique resolved components in the same record"
                )
        responsibilities = self.typed_payload.get("ascendancyResponsibilities")
        if responsibilities is not None:
            if (
                not isinstance(responsibilities, list)
                or not responsibilities
                or len(responsibilities) > 12
            ):
                raise ValueError(
                    "typed_payload.ascendancyResponsibilities must be a non-empty list with at most 12 entries"
                )
            mentioned_keys = {
                mention.component_key
                for mention in self.component_mentions
                if mention.component_key
            }
            responsibility_component_keys = {
                mention.component_key
                for mention in self.component_mentions
                if mention.component_key and mention.role in ASCENDANCY_RESPONSIBILITY_ROLES
            }
            for responsibility in responsibilities:
                if (
                    not isinstance(responsibility, dict)
                    or set(responsibility) != {"componentKey", "responsibility"}
                    or not isinstance(responsibility.get("componentKey"), str)
                    or responsibility["componentKey"] not in mentioned_keys
                    or responsibility["componentKey"] not in responsibility_component_keys
                    or not isinstance(responsibility.get("responsibility"), str)
                    or not responsibility["responsibility"].strip()
                    or len(responsibility["responsibility"]) > 240
                ):
                    raise ValueError(
                        "typed_payload.ascendancyResponsibilities entries must reference a resolved component and provide a concise responsibility"
                    )
        gear_responsibilities = self.typed_payload.get("gearResponsibilities")
        if gear_responsibilities is not None:
            if self.record_kind != "gear_synergy":
                raise ValueError(
                    "typed_payload.gearResponsibilities is only valid on gear_synergy records"
                )
            if (
                not isinstance(gear_responsibilities, list)
                or not gear_responsibilities
                or len(gear_responsibilities) > 12
            ):
                raise ValueError(
                    "typed_payload.gearResponsibilities must be a non-empty list with at most 12 entries"
                )
            gear_keys = {
                mention.component_key
                for mention in self.component_mentions
                if mention.component_key
                and mention.role in {"unique_enabler", "gear_base", "weapon_base"}
            }
            seen_gear_keys: set[str] = set()
            for responsibility in gear_responsibilities:
                if (
                    not isinstance(responsibility, dict)
                    or set(responsibility)
                    != {
                        "componentKey",
                        "responsibilityType",
                        "responsibility",
                    }
                    or not isinstance(responsibility.get("componentKey"), str)
                    or responsibility["componentKey"] not in gear_keys
                    or responsibility.get("responsibilityType") not in GEAR_RESPONSIBILITY_TYPES
                    or not isinstance(responsibility.get("responsibility"), str)
                    or not responsibility["responsibility"].strip()
                    or len(responsibility["responsibility"]) > 240
                    or responsibility["componentKey"] in seen_gear_keys
                ):
                    raise ValueError(
                        "typed_payload.gearResponsibilities entries must reference resolved gear and provide a canonical responsibility type"
                    )
                seen_gear_keys.add(responsibility["componentKey"])
        return self


class ResearcherOutput(StrictModel):
    schema_version: Literal[4, 5]
    fragments: list[CleanFragmentProposal] = Field(default_factory=list)
    semantic_edges: list[SemanticEdgeProposal] = Field(default_factory=list)
    build_design_observations: list[BuildDesignObservation] = Field(default_factory=list)
    patterns: list[BuildPatternProposal] = Field(default_factory=list)
    deep_research_records: list[DeepResearchRecordProposal] = Field(default_factory=list)

    @model_validator(mode="after")
    def _deep_records_require_v5(self) -> "ResearcherOutput":
        if self.deep_research_records and self.schema_version != 5:
            raise ValueError("deep_research_records require schema_version=5")
        return self


def public_error(
    error_code: str,
    caveats: list[str] | None = None,
    *,
    suggested_repair: str = "",
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": "error",
        "errorCode": error_code,
        "recoverable": True,
        "caveats": list(caveats or []),
        "suggestedRepair": suggested_repair,
        "facts": facts or {},
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }


def rejection(
    error_code: str,
    *,
    proposal_id: str | None = None,
    caveats: list[str] | None = None,
    suggested_repair: str = "",
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = {
        "status": "rejected",
        "errorCode": error_code,
        "proposalId": proposal_id,
        "recoverable": True,
        "caveats": list(caveats or []),
        "suggestedRepair": suggested_repair,
        "facts": facts or {},
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }
    endpoint_assessment = envelope["facts"].get("endpointAssessment")
    if isinstance(endpoint_assessment, dict):
        envelope["endpointAssessment"] = endpoint_assessment
    return envelope


def validate_researcher_output(payload: Any) -> dict[str, Any]:
    try:
        output = ResearcherOutput.model_validate(payload)
    except ValidationError as exc:
        issues = [_validation_issue(item) for item in exc.errors()[:8]]
        first = issues[0] if issues else {"path": "input", "message": "invalid payload"}
        caveat = f"Validation failed at {first['path']}: {first['message']}"
        return public_error(
            "invalid_schema",
            [caveat],
            suggested_repair=(
                "Review every validationIssues entry, use only the listed canonical enum values, "
                "and validate the corrected artifact again. Do not invent enum values."
            ),
            facts={"validationIssues": issues},
        )
    for fragment in output.fragments:
        if (fragment.visibility, fragment.split) not in VISIBILITY_SPLITS:
            return public_error("invalid_visibility_split", ["visibility/split bucket mismatch"])
    for edge in output.semantic_edges:
        if (edge.visibility, edge.split) not in VISIBILITY_SPLITS:
            return public_error("invalid_visibility_split", ["visibility/split bucket mismatch"])
        if edge.edge_type == "synergizes_with" and edge.directionality != "associative":
            return public_error("invalid_directionality", ["synergizes_with must be associative"])
        if edge.edge_type != "synergizes_with" and edge.directionality != "directional":
            return public_error(
                "invalid_directionality", ["directional edge type must be directional"]
            )
    for observation in output.build_design_observations:
        if (observation.visibility, observation.split) not in VISIBILITY_SPLITS:
            return public_error("invalid_visibility_split", ["visibility/split bucket mismatch"])
    for pattern in output.patterns:
        if (pattern.visibility, pattern.split) not in VISIBILITY_SPLITS:
            return public_error("invalid_visibility_split", ["visibility/split bucket mismatch"])
        transfer_error = _pattern_transfer_error(pattern)
        if transfer_error is not None:
            return public_error("overclaimed_transfer_scope", [transfer_error])
        overclaim = _pattern_overclaim_error(pattern)
        if overclaim is not None:
            return public_error("overclaimed_pattern_confidence", [overclaim])
        evidence_error = _pattern_evidence_error(pattern)
        if evidence_error is not None:
            return public_error("insufficient_pattern_evidence", [evidence_error])
    for record in output.deep_research_records:
        if (record.visibility, record.split) not in VISIBILITY_SPLITS:
            return public_error("invalid_visibility_split", ["visibility/split bucket mismatch"])
    return {
        "status": "accepted",
        "fragmentCount": len(output.fragments),
        "semanticEdgeCount": len(output.semantic_edges),
        "observationCount": len(output.build_design_observations),
        "patternCount": len(output.patterns),
        "deepResearchRecordCount": len(output.deep_research_records),
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }


def _validation_issue(error: dict[str, Any]) -> dict[str, Any]:
    location = tuple(error.get("loc", ()))
    path = ".".join(str(part) for part in location) or "input"
    issue: dict[str, Any] = {
        "path": path,
        "message": str(error.get("msg") or "invalid value")[:320],
        "errorType": str(error.get("type") or "validation_error"),
    }
    submitted = error.get("input")
    if isinstance(submitted, (str, int, float, bool)) or submitted is None:
        submitted_text = str(submitted)
        if len(submitted_text) <= 160:
            issue["submittedValue"] = submitted
    allowed_values = _allowed_values_for_location(location)
    if allowed_values:
        issue["allowedValues"] = allowed_values
    return issue


def _allowed_values_for_location(location: tuple[Any, ...]) -> list[str]:
    fields = {str(part) for part in location}
    if "role" in fields or "component_roles" in fields:
        return sorted(COMPONENT_ROLES)
    if "axes" in fields:
        return sorted(OBSERVATION_AXES)
    if "pattern_type" in fields:
        return [
            "build_archetype",
            "cooccurrence",
            "failure_pattern",
            "planner_hint",
            "transition_gate",
        ]
    if "observation_type" in fields:
        return [
            "build_archetype",
            "cooccurrence",
            "failure_pattern",
            "modelability_caveat",
            "planner_hint",
            "transition_gate",
        ]
    if "confidence_tier" in fields:
        return sorted(PATTERN_CONFIDENCE_TIERS)
    if "transfer_scope" in fields:
        return sorted(PATTERN_TRANSFER_SCOPES)
    return []


def _pattern_evidence_error(pattern: BuildPatternProposal) -> str | None:
    if pattern.confidence_tier == "case_observation":
        return None
    if (
        pattern.confidence_tier == "recurring_observation"
        and pattern.sample_count >= 2
        and (pattern.transfer_scope == "family" or pattern.family_count >= 2)
    ):
        return None
    if (
        pattern.confidence_tier == "likely_pattern"
        and pattern.sample_count >= 4
        and pattern.source_diversity_count >= 2
        and (pattern.transfer_scope == "family" or pattern.family_count >= 2)
    ):
        return None
    if (
        pattern.confidence_tier == "common_within_archetype"
        and pattern.sample_count >= 8
        and pattern.family_count >= 2
        and pattern.source_diversity_count >= 2
        and pattern.denominator is not None
        and pattern.denominator >= pattern.sample_count
    ):
        return None
    if (
        pattern.confidence_tier == "strong_ranking_hint"
        and pattern.sample_count >= 15
        and pattern.source_diversity_count >= 2
        and (pattern.denominator is None or pattern.denominator >= pattern.sample_count)
    ):
        return None
    return (
        f"{pattern.confidence_tier} requires stronger sample/source evidence than "
        f"sample_count={pattern.sample_count}, source_diversity_count={pattern.source_diversity_count}"
    )


def _pattern_transfer_error(pattern: BuildPatternProposal) -> str | None:
    if pattern.transfer_scope == "family":
        return None
    if pattern.confidence_tier in {"common_within_archetype", "strong_ranking_hint"}:
        return (
            f"{pattern.transfer_scope} knowledge cannot use {pattern.confidence_tier}; "
            f"cross-Family knowledge is capped at {TRANSFERABLE_PATTERN_MAX_CONFIDENCE}"
        )
    if pattern.confidence_tier == "recurring_observation" and pattern.family_count < 2:
        return "recurring transferable knowledge requires evidence from at least two Build Families"
    if pattern.confidence_tier == "likely_pattern" and pattern.family_count < 2:
        return "likely transferable knowledge requires evidence from at least two Build Families"
    return None


def _pattern_overclaim_error(pattern: BuildPatternProposal) -> str | None:
    if pattern.confidence_tier not in {"case_observation", "recurring_observation"}:
        return None
    return case_observation_overclaim_error(
        title=pattern.title,
        summary=pattern.summary,
        planner_hint=pattern.planner_hint,
        confidence_tier=pattern.confidence_tier,
    )


def case_observation_overclaim_error(
    *,
    title: str,
    summary: str,
    planner_hint: str | None = None,
    confidence_tier: str = "case_observation",
) -> str | None:
    """Reject population-level language from single-case observations or patterns."""
    text = " ".join(str(value or "") for value in (title, summary, planner_hint)).casefold()
    blocked = (
        "usually",
        "commonly",
        "common",
        "usual",
        "often",
        "typically",
        "frequently",
        "常见",
        "通常",
        "经常",
        "常用",
    )
    found = [term for term in blocked if _has_unqualified_overclaim_term(text, term)]
    if found:
        return f"{confidence_tier} cannot use common-pattern language: " + ", ".join(found)
    return None


def _has_unqualified_overclaim_term(text: str, term: str) -> bool:
    start = 0
    while True:
        index = text.find(term, start)
        if index < 0:
            return False
        before = text[max(0, index - 48) : index]
        after = text[index + len(term) : index + len(term) + 32]
        context = before + term + after
        if not _is_negated_or_guardrail_context(context):
            return True
        start = index + len(term)


def _is_negated_or_guardrail_context(context: str) -> bool:
    guardrails = (
        "not ",
        "not-",
        "no ",
        "do not",
        "don't",
        "cannot",
        "can't",
        "must not",
        "should not",
        "without sufficient",
        "not claim",
        "cannot use",
        "不能",
        "不得",
        "不要",
        "不应",
        "不可",
        "不是",
        "不声明",
        "不声称",
        "禁止",
        "不能声称",
        "不能外推",
        "不可外推",
        "不外推",
    )
    return any(marker in context for marker in guardrails)
