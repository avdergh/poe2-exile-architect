"""Strict Phase 4 research-memory proposal contracts."""

from __future__ import annotations

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
    "weapon_base",
    "scaling_stat",
    "defense_layer",
    "resource_engine",
}
PATTERN_CONFIDENCE_TIERS = {
    "case_observation",
    "recurring_observation",
    "likely_pattern",
    "common_within_archetype",
    "strong_ranking_hint",
}
VISIBILITY_SPLITS = {
    ("creator_visible", "train_context"),
    ("evaluator_only", "eval_holdout"),
    ("quarantined", "quarantine"),
}


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
        "weapon_base",
        "scaling_stat",
        "defense_layer",
        "resource_engine",
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
    component_keys: list[StableKey] = Field(min_length=1)
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
            "weapon_base",
            "scaling_stat",
            "defense_layer",
            "resource_engine",
        ],
    ] = Field(default_factory=dict)
    confidence_tier: Literal[
        "case_observation",
        "recurring_observation",
        "likely_pattern",
        "common_within_archetype",
        "strong_ranking_hint",
    ]
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
        role_keys = set(self.component_roles)
        if role_keys != component_keys:
            raise ValueError("component_roles keys must exactly match component_keys")
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


class ResearcherOutput(StrictModel):
    schema_version: Literal[4]
    fragments: list[CleanFragmentProposal] = Field(default_factory=list)
    semantic_edges: list[SemanticEdgeProposal] = Field(default_factory=list)
    build_design_observations: list[BuildDesignObservation] = Field(default_factory=list)
    patterns: list[BuildPatternProposal] = Field(default_factory=list)


def public_error(error_code: str, caveats: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": "error",
        "errorCode": error_code,
        "recoverable": True,
        "caveats": list(caveats or []),
        "suggestedRepair": "",
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
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(part) for part in first.get("loc", ())) or "input"
        return public_error("invalid_schema", [f"Validation failed at {loc}."])
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
        overclaim = _pattern_overclaim_error(pattern)
        if overclaim is not None:
            return public_error("overclaimed_pattern_confidence", [overclaim])
        evidence_error = _pattern_evidence_error(pattern)
        if evidence_error is not None:
            return public_error("insufficient_pattern_evidence", [evidence_error])
    return {
        "status": "accepted",
        "fragmentCount": len(output.fragments),
        "semanticEdgeCount": len(output.semantic_edges),
        "observationCount": len(output.build_design_observations),
        "patternCount": len(output.patterns),
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }


def _pattern_evidence_error(pattern: BuildPatternProposal) -> str | None:
    if pattern.confidence_tier == "case_observation":
        return None
    if pattern.confidence_tier == "recurring_observation" and pattern.sample_count >= 2:
        return None
    if (
        pattern.confidence_tier == "likely_pattern"
        and pattern.sample_count >= 4
        and pattern.source_diversity_count >= 2
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


def _pattern_overclaim_error(pattern: BuildPatternProposal) -> str | None:
    if pattern.confidence_tier not in {"case_observation", "recurring_observation"}:
        return None
    text = " ".join(
        str(value or "") for value in (pattern.title, pattern.summary, pattern.planner_hint)
    ).casefold()
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
        return f"{pattern.confidence_tier} cannot use common-pattern language: " + ", ".join(found)
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
