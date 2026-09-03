"""Typed read-only graph tool facade for Phase 3.

This module wraps the Phase 2 physical graph contracts in a public, validated
tool envelope. It never exposes raw graph-query strings and it keeps topology
queries bounded and read-only.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Annotated, Any, Literal

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import physical_graph as pg


MAX_HOP_LIMIT = 6
MAX_NODE_LIMIT = 200
MAX_PAYLOAD_BYTES = 65536
RAW_QUERY_FIELDS = frozenset({"query_string", "raw_query", "cypher", "gremlin", "sql"})
PASSIVE_NODE_TYPES = frozenset({"passive", "notable", "keystone"})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class VersionContext(StrictModel):
    context_type: Literal["version_context"]
    game_patch: str | None = None
    passive_tree_version: str | None = None
    pob_version: str | None = None
    pob_commit: str | None = None


class ItemContext(StrictModel):
    context_type: Literal["item_context"]
    item_level: int = Field(ge=0)
    item_base_key: str | None = None
    domain: str | None = None
    tags: list[str] = Field(default_factory=list)
    rarity: str | None = None
    slot: str | None = None


class SocketContext(StrictModel):
    context_type: Literal["socket_context"]
    socketed_support_keys: list[str] = Field(default_factory=list)
    socketed_support_families: list[str] = Field(default_factory=list)
    current_support_count: int | None = Field(default=None, ge=0)
    max_support_count: int | None = Field(default=None, ge=0)
    duplicate_support_policy: str | None = None
    socket_group_kind: str | None = None


class PassiveContext(StrictModel):
    context_type: Literal["passive_context"]
    active_weapon_set: int | None = Field(default=None, ge=1, le=2)
    target_weapon_set: int | None = Field(default=None, ge=1, le=2)
    allocated_passive_keys: list[str] = Field(default_factory=list)
    weapon_set_point_budget: int | None = Field(default=None, ge=0)
    normal_point_budget: int | None = Field(default=None, ge=0)


class BuildStateContext(StrictModel):
    context_type: Literal["build_state_context"]
    current_attributes: dict[str, int] = Field(default_factory=dict)
    spirit_reservation_summary: dict[str, Any] = Field(default_factory=dict)
    equipped_weapon_types: list[str] = Field(default_factory=list)
    relevant_caveats: list[str] = Field(default_factory=list)


GraphToolContext = Annotated[
    VersionContext | ItemContext | SocketContext | PassiveContext | BuildStateContext,
    Field(discriminator="context_type"),
]

_CONTEXT_TYPE_TAGS = tuple(
    sorted(
        str(member.model_fields["context_type"].annotation.__args__[0])
        for member in GraphToolContext.__args__[0].__args__
        if "context_type" in (getattr(member, "model_fields", None) or {})
        and getattr(member.model_fields["context_type"].annotation, "__args__", None)
    )
)


class ResolveGraphComponentInput(StrictModel):
    query: str = Field(default="", max_length=240)
    keys: list[str] = Field(default_factory=list, max_length=60)
    detail: Literal["full", "compact"] = "full"
    expected_node_types: list[str] = Field(default_factory=list, max_length=12)
    scope: Literal["any", "player"] = "any"
    context: GraphToolContext | None = None

    @model_validator(mode="after")
    def _require_query_or_keys(self) -> "ResolveGraphComponentInput":
        if not self.query.strip() and not self.keys:
            raise ValueError("resolve_graph_component requires 'query' or a non-empty 'keys' list")
        return self


class SearchGraphComponentsInput(StrictModel):
    query: str
    expected_node_types: list[str] = Field(default_factory=list, max_length=12)
    scope: Literal["any", "player"] = "any"
    limit: int = Field(default=20, ge=1, le=50)
    context: GraphToolContext | None = None


class ExplainGraphEvidenceInput(StrictModel):
    node_key: str | None = None
    edge_type: str | None = None
    source_key: str | None = None
    target_key: str | None = None
    context: GraphToolContext | None = None


class ComponentStageInput(StrictModel):
    component_key: str
    level_or_stage: str
    context: GraphToolContext | None = None


class SupportSkillCandidateInput(StrictModel):
    support_key: str
    skill_key: str
    context: GraphToolContext | None = None


class SocketSupportLegalityInput(StrictModel):
    skill_key: str
    support_key: str
    context: GraphToolContext | None = None


class CanRollModInput(StrictModel):
    base_item_key: str
    mod_key: str
    context: GraphToolContext | None = None


class PassiveNodeInput(StrictModel):
    passive_key: str
    context: GraphToolContext | None = None


class PassiveTopologyPathInput(StrictModel):
    start_key: str
    end_key: str
    hop_limit: int = Field(default=MAX_HOP_LIMIT, ge=0, le=MAX_HOP_LIMIT)
    context: GraphToolContext | None = None


class PassiveSubgraphInput(StrictModel):
    node_key: str
    hop_limit: int = Field(default=MAX_HOP_LIMIT, ge=0, le=MAX_HOP_LIMIT)
    node_limit: int = Field(default=MAX_NODE_LIMIT, ge=1, le=MAX_NODE_LIMIT)
    context: GraphToolContext | None = None


class CaveatComponentSetInput(StrictModel):
    caveat_key: str
    context: GraphToolContext | None = None


class IdResolveInput(StrictModel):
    system: str
    external_id: str
    context: GraphToolContext | None = None


class InspectStaleSourcesInput(StrictModel):
    context: GraphToolContext | None = None


INPUT_MODELS: dict[str, type[StrictModel]] = {
    "search_graph_components": SearchGraphComponentsInput,
    "resolve_graph_component": ResolveGraphComponentInput,
    "explain_graph_evidence": ExplainGraphEvidenceInput,
    "requirements_for_component": ComponentStageInput,
    "resource_profile_for_component": ComponentStageInput,
    "support_skill_candidate": SupportSkillCandidateInput,
    "socket_support_legality": SocketSupportLegalityInput,
    "can_roll_mod": CanRollModInput,
    "passive_neighbors": PassiveNodeInput,
    "passive_allocation_options": PassiveNodeInput,
    "passive_allocation_overlay": PassiveNodeInput,
    "find_passive_topology_path": PassiveTopologyPathInput,
    "get_passive_subgraph_in_radius": PassiveSubgraphInput,
    "caveat_component_set": CaveatComponentSetInput,
    "build_planner_id_resolve": IdResolveInput,
    "inspect_stale_graph_sources": InspectStaleSourcesInput,
}


CONTEXT_POLICIES: dict[str, str] = {
    "search_graph_components": "none",
    "resolve_graph_component": "none",
    "explain_graph_evidence": "none",
    "requirements_for_component": "version_only",
    "resource_profile_for_component": "version_only",
    "support_skill_candidate": "version_only",
    "socket_support_legality": "socket_context",
    "can_roll_mod": "item_context",
    "passive_neighbors": "passive_context",
    "passive_allocation_options": "passive_context",
    "passive_allocation_overlay": "passive_context",
    "find_passive_topology_path": "passive_context",
    "get_passive_subgraph_in_radius": "passive_context",
    "caveat_component_set": "none",
    "build_planner_id_resolve": "none",
    "inspect_stale_graph_sources": "version_only",
}


def _normalize_resolve_component_key_alias(
    query_family: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Accept ``componentKey`` (safe-review contract vocabulary) as an alias of ``query``.

    resolve_graph_component's typed schema uses ``query``/``keys``, while safe reviews
    name components ``componentKey``. Researchers naturally pass ``componentKey`` first
    and only learn the real fields from a validation error; normalize the alias before
    schema validation so the first call works. When both ``query`` and ``componentKey``
    are supplied, leave the payload untouched so the schema rejects the ambiguity loudly
    (with its available-fields hint) instead of silently preferring one.
    """
    if query_family != "resolve_graph_component" or "componentKey" not in payload:
        return payload
    normalized = dict(payload)
    component_key = normalized.pop("componentKey")
    if normalized.get("query"):
        normalized["componentKey"] = component_key
    else:
        normalized["query"] = component_key
    return normalized


class GraphQueryService:
    """Read-only typed facade over one physical graph snapshot."""

    def __init__(self, snapshot: pg.GraphSnapshot) -> None:
        self.snapshot = snapshot
        self._nodes_by_key = {node.stable_key: node for node in snapshot.nodes}
        self._sources_by_id = {source.source_id: source for source in snapshot.sources}
        self._ascendancy_by_passive = {
            edge.source_key: edge.target_key
            for edge in snapshot.edges
            if edge.edge_type == "belongs_to"
            and edge.source_key in self._nodes_by_key
            and edge.target_key in self._nodes_by_key
            and self._nodes_by_key[edge.target_key].node_type == "ascendancy"
        }
        self._player_skill_keys = {
            edge.target_key
            for edge in snapshot.edges
            if edge.edge_type == "grants_skill"
            and edge.source_key in self._nodes_by_key
            and self._nodes_by_key[edge.source_key].node_type in {"skill_gem", "support_gem"}
        }
        self._player_skill_keys.update(
            node.stable_key
            for node in snapshot.nodes
            if node.node_type == "active_skill"
            and "player" in node.stable_key.split(":", 1)[-1].casefold()
        )
        self._topology_graph = self._build_topology_graph(snapshot)
        self.topology_build_count = 1

    @classmethod
    def from_snapshot(cls, snapshot: pg.GraphSnapshot) -> GraphQueryService:
        return cls(snapshot)

    @classmethod
    def from_snapshot_path(cls, snapshot_path: str | Path) -> GraphQueryService:
        return cls(pg.load_snapshot(snapshot_path))

    @classmethod
    def from_snapshot_index(cls, index_path: str | Path) -> GraphQueryService:
        return cls(pg.load_latest_snapshot(index_path))

    def run_tool(self, tool_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        query_family = str(tool_name)
        if query_family not in INPUT_MODELS:
            return self._error(
                query_family=query_family,
                error_code="unsupported_tool",
                caveats=[f"unsupported graph tool: {query_family}"],
            )
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return self._error(
                query_family=query_family,
                error_code="invalid_schema",
                caveats=["Tool input validation failed: payload must be an object."],
            )
        raw_fields = _raw_query_field_paths(payload)
        if raw_fields:
            return self._error(
                query_family=query_family,
                error_code="invalid_schema",
                caveats=[
                    "Tool input validation failed: raw graph query fields are not permitted "
                    f"({', '.join(raw_fields)}). Only use typed schema."
                ],
            )

        model_cls = INPUT_MODELS[query_family]
        payload = _normalize_resolve_component_key_alias(query_family, payload)
        try:
            typed_input = model_cls.model_validate(payload)
        except ValidationError as exc:
            available = ", ".join(sorted(model_cls.model_fields))
            return self._error(
                query_family=query_family,
                error_code="invalid_schema",
                caveats=[
                    _validation_caveat(exc),
                    f"Available payload fields for {query_family}: {available}.",
                ],
            )

        missing_context = self._missing_context(query_family, typed_input)
        if missing_context is not None:
            return missing_context

        try:
            if query_family == "search_graph_components":
                return self._search_graph_components(typed_input)
            if query_family == "resolve_graph_component":
                if typed_input.keys:
                    return self._resolve_graph_components_batch(typed_input)
                return self._resolve_graph_component(typed_input)
            if query_family == "explain_graph_evidence":
                return self._explain_graph_evidence(typed_input)
            if query_family == "requirements_for_component":
                result = pg.requirements_for_component(
                    self.snapshot,
                    typed_input.component_key,
                    level_or_stage=typed_input.level_or_stage,
                )
                return self._computed_result(query_family, result, typed_input=typed_input)
            if query_family == "resource_profile_for_component":
                result = pg.resource_profile_for_component(
                    self.snapshot,
                    typed_input.component_key,
                    level_or_stage=typed_input.level_or_stage,
                )
                return self._computed_result(query_family, result, typed_input=typed_input)
            if query_family == "support_skill_candidate":
                result = pg.support_skill_candidate(
                    snapshot=self.snapshot,
                    support_key=typed_input.support_key,
                    skill_key=typed_input.skill_key,
                )
                return self._computed_result(query_family, result, typed_input=typed_input)
            if query_family == "socket_support_legality":
                socket_context = _context_payload(typed_input.context)
                socket_context.pop("context_type", None)
                result = pg.socket_support_legality(
                    snapshot=self.snapshot,
                    skill_key=typed_input.skill_key,
                    support_key=typed_input.support_key,
                    socket_context=socket_context,
                )
                return self._computed_result(query_family, result, typed_input=typed_input)
            if query_family == "can_roll_mod":
                context = typed_input.context
                assert isinstance(context, ItemContext)
                result = pg.can_roll_mod(
                    snapshot=self.snapshot,
                    base_item_key=typed_input.base_item_key,
                    mod_key=typed_input.mod_key,
                    item_level=context.item_level,
                )
                return self._computed_result(query_family, result, typed_input=typed_input)
            if query_family == "passive_neighbors":
                result = pg.passive_neighbors(self.snapshot, typed_input.passive_key)
                return self._computed_result(query_family, result, typed_input=typed_input)
            if query_family == "passive_allocation_options":
                result = pg.passive_allocation_options(self.snapshot, typed_input.passive_key)
                return self._computed_result(query_family, result, typed_input=typed_input)
            if query_family == "passive_allocation_overlay":
                result = pg.passive_allocation_overlay(self.snapshot, typed_input.passive_key)
                return self._computed_result(query_family, result, typed_input=typed_input)
            if query_family == "find_passive_topology_path":
                return self._find_passive_topology_path(typed_input)
            if query_family == "get_passive_subgraph_in_radius":
                return self._get_passive_subgraph_in_radius(typed_input)
            if query_family == "caveat_component_set":
                result = pg.caveat_component_set(self.snapshot, typed_input.caveat_key)
                return self._computed_result(query_family, result, typed_input=typed_input)
            if query_family == "build_planner_id_resolve":
                return self._build_planner_id_resolve(typed_input)
            if query_family == "inspect_stale_graph_sources":
                return self._inspect_stale_graph_sources(typed_input)
        except ValueError as exc:
            return self._error(
                query_family=query_family,
                error_code="invalid_reference",
                caveats=[str(exc)],
                context=_context_payload(getattr(typed_input, "context", None)),
            )

        return self._error(
            query_family=query_family,
            error_code="unsupported_tool",
            caveats=[f"unsupported graph tool: {query_family}"],
        )

    def _build_topology_graph(self, snapshot: pg.GraphSnapshot) -> nx.Graph:
        graph = nx.Graph()
        passive_keys = sorted(
            node.stable_key for node in snapshot.nodes if node.node_type in PASSIVE_NODE_TYPES
        )
        graph.add_nodes_from(passive_keys)
        for edge in sorted(
            snapshot.edges, key=lambda item: (item.edge_type, item.source_key, item.target_key)
        ):
            if (
                edge.edge_type == "connected_to"
                and edge.source_key in graph
                and edge.target_key in graph
            ):
                graph.add_edge(edge.source_key, edge.target_key, source_refs=edge.evidence_refs)
        return graph

    def _missing_context(
        self, query_family: str, typed_input: StrictModel
    ) -> dict[str, Any] | None:
        policy = CONTEXT_POLICIES[query_family]
        context = getattr(typed_input, "context", None)
        if policy == "none":
            if context is not None:
                return self._missing_context_result(
                    query_family=query_family,
                    missing=[],
                    context_caveats=["unexpected_context"],
                    context=_context_payload(context),
                )
        if policy == "version_only":
            if context is not None and not isinstance(context, VersionContext):
                return self._missing_context_result(
                    query_family=query_family,
                    missing=["version_context"],
                    context_caveats=["expected_version_context"],
                    context=_context_payload(context),
                )
            if isinstance(context, VersionContext):
                mismatches = self._version_context_mismatches(context)
                if mismatches:
                    return self._envelope(
                        query_family=query_family,
                        status="stale",
                        facts={
                            "version_context": _context_payload(context),
                            "snapshot_version_context": self._version_context(),
                            "mismatched_fields": mismatches,
                        },
                        confidence=0.0,
                        caveats=["version_context_mismatch"],
                        context=_context_payload(context),
                        context_caveats=[
                            f"version_context_mismatch:{field}" for field in mismatches
                        ],
                    )
        if policy == "item_context":
            if context is None:
                return self._missing_context_result(
                    query_family=query_family,
                    missing=["item_context.item_level"],
                )
            if not isinstance(context, ItemContext):
                return self._missing_context_result(
                    query_family=query_family,
                    missing=["item_context"],
                    context_caveats=["expected_item_context"],
                    context=_context_payload(context),
                )
        if policy == "socket_context":
            if context is None:
                return self._missing_context_result(
                    query_family=query_family,
                    missing=["socket_context"],
                )
            if not isinstance(context, SocketContext):
                return self._missing_context_result(
                    query_family=query_family,
                    missing=["socket_context"],
                    context_caveats=["expected_socket_context"],
                    context=_context_payload(context),
                )
        if policy == "passive_context":
            if context is None:
                return self._missing_context_result(
                    query_family=query_family,
                    missing=["passive_context"],
                )
            if not isinstance(context, PassiveContext):
                return self._missing_context_result(
                    query_family=query_family,
                    missing=["passive_context"],
                    context_caveats=["expected_passive_context"],
                    context=_context_payload(context),
                )
        return None

    def _resolve_graph_component(self, typed_input: ResolveGraphComponentInput) -> dict[str, Any]:
        resolution = pg.resolve_candidates(self.snapshot, typed_input.query)
        expected_node_types = set(typed_input.expected_node_types)
        if expected_node_types and resolution.get("candidate_keys"):
            candidate_keys = [
                key
                for key in resolution["candidate_keys"]
                if key in self._nodes_by_key
                and self._nodes_by_key[key].node_type in expected_node_types
            ]
            resolution = {
                "status": "resolved"
                if len(candidate_keys) == 1
                else "ambiguous"
                if candidate_keys
                else "missing",
                "resolved_key": candidate_keys[0] if len(candidate_keys) == 1 else None,
                "candidate_keys": candidate_keys,
            }
        if typed_input.scope == "player" and resolution.get("candidate_keys"):
            candidate_keys = [
                key
                for key in resolution["candidate_keys"]
                if self._nodes_by_key[key].node_type != "active_skill"
                or key in self._player_skill_keys
            ]
            resolution = {
                "status": "resolved"
                if len(candidate_keys) == 1
                else "ambiguous"
                if candidate_keys
                else "missing",
                "resolved_key": candidate_keys[0] if len(candidate_keys) == 1 else None,
                "candidate_keys": candidate_keys,
            }
        status = str(resolution["status"])
        candidate_keys = list(resolution.get("candidate_keys", []))
        candidates = [
            self._candidate_summary(key) for key in candidate_keys if key in self._nodes_by_key
        ]
        source_refs = sorted(
            {
                source_ref
                for candidate in candidates
                for source_ref in candidate.get("sourceRefs", [])
            }
        )
        resolved_key = resolution.get("resolved_key")
        resolved_subject = self._node_summary(str(resolved_key)) if resolved_key else None
        endpoint_assessment = None
        if status in {"missing", "unknown"} and not candidate_keys:
            endpoint_assessment = _endpoint_assessment(
                "source_coverage_gap",
                candidate_endpoint_names=[typed_input.query],
            )
            search_candidates = pg.search_candidates(
                self.snapshot,
                typed_input.query,
                limit=5,
            ).get("candidate_keys", [])
            facts = {
                "query": typed_input.query,
                "expected_node_types": sorted(expected_node_types),
                "scope": typed_input.scope,
                "candidate_keys": candidate_keys,
                "candidates": candidates,
                "searchCandidates": [
                    self._candidate_summary(key)
                    for key in search_candidates
                    if key in self._nodes_by_key
                ],
                "endpointAssessment": endpoint_assessment,
            }
        else:
            facts = {
                "query": typed_input.query,
                "expected_node_types": sorted(expected_node_types),
                "scope": typed_input.scope,
                "candidate_keys": candidate_keys,
                "candidates": candidates,
            }
        return self._envelope(
            query_family="resolve_graph_component",
            status=status,
            facts=facts,
            resolved_subject=resolved_subject,
            source_refs=source_refs,
            evidence_path=self._evidence_path(nodes=candidate_keys, source_refs=source_refs),
            confidence=1.0 if status == "resolved" else 0.5 if status == "ambiguous" else 0.0,
            caveats=(
                ["ambiguous_alias"]
                if status == "ambiguous"
                else ["candidate_discovery_only"]
                if facts.get("searchCandidates")
                else []
            ),
            context=_context_payload(typed_input.context),
            endpoint_assessment=endpoint_assessment,
        )

    def _resolve_graph_components_batch(
        self, typed_input: ResolveGraphComponentInput
    ) -> dict[str, Any]:
        """Resolve many stable keys in one call.

        ``detail=compact`` returns only the evidence-preserving fields each resolution needs
        (resolvedKey / nodeType / displayName / candidateKeys / evidencePathNodes / snapshotId /
        sourceRefs) so bulk support/skill resolution stays cheap; ``detail=full`` also embeds
        every full envelope. The four fields required for semantic-edge endpoint evidence
        (stable_key, evidence_path_nodes, snapshot_id, source_refs) are always preserved.
        """
        resolutions: list[dict[str, Any]] = []
        envelopes: dict[str, dict[str, Any]] = {}
        for key in typed_input.keys:
            envelope = self._resolve_graph_component(
                ResolveGraphComponentInput(
                    query=key,
                    expected_node_types=typed_input.expected_node_types,
                    scope=typed_input.scope,
                    context=typed_input.context,
                    detail="full",
                )
            )
            envelopes[key] = envelope
            resolved = envelope.get("resolvedSubject") or {}
            evidence_path = envelope.get("evidencePath") or {}
            resolutions.append(
                {
                    "query": key,
                    "status": envelope.get("status"),
                    "resolvedKey": (
                        str(resolved.get("stableKey") or "")
                        if envelope.get("status") == "resolved"
                        else None
                    ),
                    "nodeType": str(resolved.get("nodeType") or "") if resolved else None,
                    "displayName": str(resolved.get("displayName") or "") if resolved else None,
                    "candidateKeys": list(
                        (envelope.get("facts") or {}).get("candidate_keys") or []
                    ),
                    "evidencePathNodes": list(evidence_path.get("nodes") or []),
                    "snapshotId": str(evidence_path.get("snapshotId") or self.snapshot.snapshot_id),
                    "sourceRefs": list(envelope.get("sourceRefs") or []),
                }
            )
        unresolved = [item for item in resolutions if item["status"] != "resolved"]
        caveats = ["partial_resolution"] if unresolved else []
        if any(item["status"] == "ambiguous" for item in unresolved):
            caveats.append("ambiguous_resolution")
        facts: dict[str, Any] = {
            "keys": list(typed_input.keys),
            "detail": typed_input.detail,
            "resolutions": resolutions,
        }
        if typed_input.detail == "full":
            full_facts = {
                **facts,
                "envelopes": {key: envelopes[key] for key in typed_input.keys},
            }
            if _json_size(full_facts) > MAX_PAYLOAD_BYTES:
                # Full envelopes exceed the payload budget at this key count; keep the
                # evidence-preserving compact projection (the four semantic-edge fields
                # are always retained) and say so explicitly instead of truncating mid-way.
                facts["detail"] = "compact"
                caveats.append("payload_limit_truncated")
            else:
                facts = full_facts
        aggregate_confidence = min(
            1.0 if item["status"] == "resolved" else 0.5 if item["status"] == "ambiguous" else 0.0
            for item in resolutions
        )
        return {
            "toolName": "resolve_graph_component",
            "queryFamily": "resolve_graph_component",
            "snapshotId": self.snapshot.snapshot_id,
            "status": "ok" if not unresolved else "partial",
            "errorCode": None,
            "resolvedSubject": None,
            "facts": facts,
            "evidencePath": self._evidence_path(),
            "sourceRefs": sorted({ref for item in resolutions for ref in item["sourceRefs"]}),
            "confidence": aggregate_confidence,
            "caveats": caveats,
            "contextPolicy": CONTEXT_POLICIES.get("resolve_graph_component", "none"),
            "contextUsed": {},
            "missingContext": [],
            "contextCaveats": [],
            "freshness": {"versionContext": self._version_context()},
            "noRawQuery": True,
        }

    def _search_graph_components(self, typed_input: SearchGraphComponentsInput) -> dict[str, Any]:
        discovery = pg.search_candidates(
            self.snapshot,
            typed_input.query,
            expected_node_types=tuple(typed_input.expected_node_types),
            allowed_keys=(
                frozenset(self._player_skill_keys) if typed_input.scope == "player" else None
            ),
            limit=typed_input.limit,
        )
        candidate_keys = list(discovery.get("candidate_keys") or [])
        candidates = [
            {
                **self._candidate_summary(key),
                "resolverPayload": {"componentKey": key},
            }
            for key in candidate_keys
        ]
        source_refs = sorted(
            {
                source_ref
                for candidate in candidates
                for source_ref in candidate.get("sourceRefs", [])
            }
        )
        status = str(discovery.get("status") or "missing")
        return self._envelope(
            query_family="search_graph_components",
            status=status,
            facts={
                "query": typed_input.query,
                "expected_node_types": list(discovery.get("expected_node_types") or []),
                "scope": typed_input.scope,
                "candidates": candidates,
                "truncated": bool(discovery.get("truncated")),
            },
            resolved_subject=None,
            source_refs=source_refs,
            evidence_path=self._evidence_path(nodes=candidate_keys, source_refs=source_refs),
            confidence=0.75 if candidate_keys else 0.0,
            caveats=["candidate_discovery_only"] if candidate_keys else [],
            context=_context_payload(typed_input.context),
        )

    def _explain_graph_evidence(self, typed_input: ExplainGraphEvidenceInput) -> dict[str, Any]:
        if typed_input.node_key is not None:
            try:
                evidence = pg.explain_sources(self.snapshot, typed_input.node_key)
            except ValueError as exc:
                return self._error(
                    query_family="explain_graph_evidence",
                    error_code="invalid_reference",
                    caveats=[str(exc)],
                    context=_context_payload(typed_input.context),
                )
            source_refs = [item["source_id"] for item in evidence]
            return self._envelope(
                query_family="explain_graph_evidence",
                status="known",
                facts={"node_key": typed_input.node_key, "evidence": evidence},
                resolved_subject=self._node_summary(typed_input.node_key),
                source_refs=source_refs,
                evidence_path=self._evidence_path(
                    nodes=[typed_input.node_key], source_refs=source_refs
                ),
                context=_context_payload(typed_input.context),
            )
        if (
            typed_input.edge_type is not None
            and typed_input.source_key is not None
            and typed_input.target_key is not None
        ):
            evidence = pg.explain_edge_sources(
                self.snapshot,
                edge_type=typed_input.edge_type,
                source_key=typed_input.source_key,
                target_key=typed_input.target_key,
            )
            source_refs = [item["source_id"] for item in evidence.get("evidence", [])]
            return self._envelope(
                query_family="explain_graph_evidence",
                status=str(evidence["status"]),
                facts=evidence,
                resolved_subject=self._node_summary(typed_input.source_key),
                source_refs=source_refs,
                evidence_path=self._evidence_path(
                    nodes=[typed_input.source_key, typed_input.target_key],
                    edges=[
                        {
                            "edgeType": typed_input.edge_type,
                            "sourceKey": typed_input.source_key,
                            "targetKey": typed_input.target_key,
                        }
                    ],
                    source_refs=source_refs,
                ),
                context=_context_payload(typed_input.context),
            )
        return self._error(
            query_family="explain_graph_evidence",
            error_code="invalid_schema",
            caveats=[
                "Tool input validation failed: provide node_key or edge_type/source_key/target_key."
            ],
            context=_context_payload(typed_input.context),
        )

    def _computed_result(
        self,
        query_family: str,
        result: pg.ComputedFactResult,
        *,
        typed_input: StrictModel,
    ) -> dict[str, Any]:
        status = result.status
        subject_key = _subject_key(result)
        subject = self._node_summary(subject_key) if subject_key in self._nodes_by_key else None
        caveats = [result.caveat] if result.caveat else []
        return self._envelope(
            query_family=query_family,
            status=status,
            facts=result.facts,
            resolved_subject=subject,
            source_refs=sorted(result.source_refs),
            evidence_path=self._evidence_path(
                nodes=[key for key in _fact_node_keys(result.facts) if key in self._nodes_by_key],
                computed_fact_ids=[result.request.fact_type],
                source_refs=sorted(result.source_refs),
                caveats=caveats,
                confidence=result.confidence,
            ),
            confidence=result.confidence,
            caveats=caveats,
            context=_context_payload(getattr(typed_input, "context", None)),
        )

    def _find_passive_topology_path(self, typed_input: PassiveTopologyPathInput) -> dict[str, Any]:
        context = typed_input.context
        assert isinstance(context, PassiveContext)
        conflict = self._weapon_set_conflict(typed_input.start_key, typed_input.end_key, context)
        if conflict:
            return self._envelope(
                query_family="find_passive_topology_path",
                status="unsupported",
                facts={
                    "start_key": typed_input.start_key,
                    "end_key": typed_input.end_key,
                    "path_keys": [],
                    "hop_count": None,
                },
                resolved_subject=self._node_summary(typed_input.start_key),
                source_refs=self._source_refs_for_keys(
                    [typed_input.start_key, typed_input.end_key]
                ),
                evidence_path=self._evidence_path(
                    nodes=[typed_input.start_key, typed_input.end_key],
                    source_refs=self._source_refs_for_keys(
                        [typed_input.start_key, typed_input.end_key]
                    ),
                    caveats=["conflicting_weapon_set_caveat"],
                    confidence=0.0,
                ),
                confidence=0.0,
                caveats=["conflicting_weapon_set_caveat"],
                context=_context_payload(context),
            )
        if (
            typed_input.start_key not in self._topology_graph
            or typed_input.end_key not in self._topology_graph
        ):
            return self._envelope(
                query_family="find_passive_topology_path",
                status="unknown",
                facts={
                    "start_key": typed_input.start_key,
                    "end_key": typed_input.end_key,
                    "path_keys": [],
                    "hop_count": None,
                },
                confidence=0.0,
                caveats=["missing_passive_topology_node"],
                context=_context_payload(context),
            )
        bounded_paths = nx.single_source_shortest_path(
            self._topology_graph,
            typed_input.start_key,
            cutoff=typed_input.hop_limit,
        )
        path = bounded_paths.get(typed_input.end_key, [])
        if not path:
            unrestricted_length = _bounded_shortest_path_length(
                self._topology_graph,
                typed_input.start_key,
                typed_input.end_key,
                cutoff=MAX_HOP_LIMIT,
            )
            if unrestricted_length is not None and unrestricted_length > typed_input.hop_limit:
                return self._envelope(
                    query_family="find_passive_topology_path",
                    status="unknown",
                    facts={
                        "start_key": typed_input.start_key,
                        "end_key": typed_input.end_key,
                        "path_keys": [],
                        "hop_count": None,
                        "required_hops": unrestricted_length,
                    },
                    resolved_subject=self._node_summary(typed_input.start_key),
                    source_refs=self._source_refs_for_keys(
                        [typed_input.start_key, typed_input.end_key]
                    ),
                    confidence=0.0,
                    caveats=["hop_limit_exceeded", "topology_only_path"],
                    context=_context_payload(context),
                )
            path = []
        source_refs = self._source_refs_for_keys(path)
        return self._envelope(
            query_family="find_passive_topology_path",
            status="known" if path else "unknown",
            facts={
                "start_key": typed_input.start_key,
                "end_key": typed_input.end_key,
                "path_keys": path,
                "hop_count": len(path) - 1 if path else None,
                "topology_only": True,
            },
            resolved_subject=self._node_summary(typed_input.start_key),
            source_refs=source_refs,
            evidence_path=self._evidence_path(
                nodes=path,
                edges=_path_edges(path),
                source_refs=source_refs,
                caveats=["topology_only_path"],
            ),
            caveats=["topology_only_path"],
            context=_context_payload(context),
        )

    def _get_passive_subgraph_in_radius(self, typed_input: PassiveSubgraphInput) -> dict[str, Any]:
        context = typed_input.context
        assert isinstance(context, PassiveContext)
        if typed_input.node_key not in self._topology_graph:
            return self._envelope(
                query_family="get_passive_subgraph_in_radius",
                status="unknown",
                facts={"node_key": typed_input.node_key, "nodes": [], "edges": [], "node_count": 0},
                confidence=0.0,
                caveats=["missing_passive_topology_node"],
                context=_context_payload(context),
            )
        lengths = nx.single_source_shortest_path_length(
            self._topology_graph,
            typed_input.node_key,
            cutoff=typed_input.hop_limit,
        )
        ordered_nodes = sorted(lengths, key=lambda key: (lengths[key], key))
        truncated = len(ordered_nodes) > typed_input.node_limit
        selected_nodes = sorted(ordered_nodes[: typed_input.node_limit])
        subgraph = self._topology_graph.subgraph(selected_nodes)
        edges = sorted(
            {
                tuple(sorted((source, target)))
                for source, target in subgraph.edges()
                if source in selected_nodes and target in selected_nodes
            }
        )
        facts = {
            "node_key": typed_input.node_key,
            "hop_limit": typed_input.hop_limit,
            "node_limit": typed_input.node_limit,
            "nodes": [
                {
                    "stableKey": key,
                    "distance": lengths[key],
                    "displayName": self._nodes_by_key[key].display_name,
                }
                for key in selected_nodes
            ],
            "edges": [
                {"sourceKey": source, "targetKey": target, "edgeType": "connected_to"}
                for source, target in edges
            ],
            "node_count": len(selected_nodes),
            "edge_count": len(edges),
            "truncated": truncated,
            "topology_only": True,
        }
        payload_bytes = len(json.dumps(facts, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        facts["payload_bytes"] = payload_bytes
        caveats = ["topology_only_subgraph"]
        if truncated:
            caveats.append("node_limit_truncated")
        if payload_bytes > MAX_PAYLOAD_BYTES:
            facts["nodes"] = facts["nodes"][: max(1, len(facts["nodes"]) // 2)]
            facts["edges"] = [
                edge
                for edge in facts["edges"]
                if edge["sourceKey"] in {node["stableKey"] for node in facts["nodes"]}
                and edge["targetKey"] in {node["stableKey"] for node in facts["nodes"]}
            ]
            facts["node_count"] = len(facts["nodes"])
            facts["edge_count"] = len(facts["edges"])
            facts["truncated"] = True
            facts["payload_bytes"] = len(
                json.dumps(facts, ensure_ascii=False, sort_keys=True).encode("utf-8")
            )
            caveats.append("payload_limit_truncated")
        while True:
            payload_nodes = [str(node["stableKey"]) for node in facts["nodes"]]
            payload_edges = [
                (str(edge["sourceKey"]), str(edge["targetKey"])) for edge in facts["edges"]
            ]
            source_refs = self._source_refs_for_keys(payload_nodes)
            evidence_edges = [
                {"edgeType": "connected_to", "sourceKey": source, "targetKey": target}
                for source, target in payload_edges
            ]
            projected = self._envelope(
                query_family="get_passive_subgraph_in_radius",
                status="known",
                facts=facts,
                resolved_subject=self._node_summary(typed_input.node_key),
                source_refs=source_refs,
                evidence_path=self._evidence_path(
                    nodes=payload_nodes,
                    edges=evidence_edges,
                    source_refs=source_refs,
                    caveats=caveats,
                ),
                caveats=caveats,
                context=_context_payload(context),
            )
            for _ in range(3):
                payload_bytes = _json_size(projected)
                if facts.get("payload_bytes") == payload_bytes:
                    break
                facts["payload_bytes"] = payload_bytes
                projected["facts"] = facts
            final_payload_bytes = _json_size(projected)
            facts["payload_bytes"] = final_payload_bytes
            projected["facts"] = facts
            if final_payload_bytes <= MAX_PAYLOAD_BYTES:
                return projected
            if len(facts["nodes"]) <= 1 and any(
                len(str(node.get("displayName", ""))) > 120 for node in facts["nodes"]
            ):
                for node in facts["nodes"]:
                    display_name = str(node.get("displayName", ""))
                    if len(display_name) > 120:
                        node["displayName"] = display_name[:117] + "..."
                facts["truncated"] = True
                if "payload_limit_truncated" not in caveats:
                    caveats.append("payload_limit_truncated")
                continue
            if len(facts["nodes"]) <= 1:
                return projected

            facts["nodes"] = facts["nodes"][: max(1, len(facts["nodes"]) // 2)]
            allowed_keys = {str(node["stableKey"]) for node in facts["nodes"]}
            facts["edges"] = [
                edge
                for edge in facts["edges"]
                if edge["sourceKey"] in allowed_keys and edge["targetKey"] in allowed_keys
            ]
            facts["node_count"] = len(facts["nodes"])
            facts["edge_count"] = len(facts["edges"])
            facts["truncated"] = True
            if "payload_limit_truncated" not in caveats:
                caveats.append("payload_limit_truncated")

    def _build_planner_id_resolve(self, typed_input: IdResolveInput) -> dict[str, Any]:
        result = pg.resolve_id_mapping(self.snapshot, typed_input.system, typed_input.external_id)
        status = str(result["status"])
        target_key = result.get("target_key")
        caveats = [str(result["caveat"])] if result.get("caveat") else []
        source_refs = (
            self._source_refs_for_keys([target_key])
            if target_key
            else self._mapping_source_refs(
                typed_input.system,
                typed_input.external_id,
            )
        )
        return self._envelope(
            query_family="build_planner_id_resolve",
            status=status,
            facts=result,
            resolved_subject=self._node_summary(str(target_key)) if target_key else None,
            source_refs=source_refs,
            evidence_path=self._evidence_path(
                nodes=[target_key] if target_key else [],
                source_refs=source_refs,
                caveats=caveats,
                confidence=1.0 if status == "resolved" else 0.0,
            ),
            confidence=1.0 if status == "resolved" else 0.0,
            caveats=caveats,
            context=_context_payload(typed_input.context),
        )

    def _inspect_stale_graph_sources(self, typed_input: InspectStaleSourcesInput) -> dict[str, Any]:
        stale_sources = [
            {
                "sourceId": source.source_id,
                "kind": source.kind,
                "sourceFile": source.source_file,
                "status": "stale",
            }
            for source in self.snapshot.sources
            if source.claim("freshness_status") == "stale"
        ]
        return self._envelope(
            query_family="inspect_stale_graph_sources",
            status="stale" if stale_sources else "known",
            facts={"stale_sources": stale_sources},
            source_refs=[source["sourceId"] for source in stale_sources],
            caveats=["stale_source_detected"] if stale_sources else [],
            context=_context_payload(typed_input.context),
        )

    def _weapon_set_conflict(self, start_key: str, end_key: str, context: PassiveContext) -> bool:
        if context.active_weapon_set is not None and context.target_weapon_set is not None:
            if context.active_weapon_set != context.target_weapon_set:
                return True
        start_states = self._allocation_states(start_key)
        end_states = self._allocation_states(end_key)
        exclusive_start = _exclusive_weapon_state(start_states)
        exclusive_end = _exclusive_weapon_state(end_states)
        return (
            exclusive_start is not None
            and exclusive_end is not None
            and exclusive_start != exclusive_end
        )

    def _allocation_states(self, passive_key: str) -> set[str]:
        fact = next(
            (
                item
                for item in self.snapshot.requirement_facts
                if item.component_key == passive_key and item.level_or_stage == "weapon_set_overlay"
            ),
            None,
        )
        if fact is None:
            return {"normal"}
        values = fact.requirements.get("allocation_states", ["normal"])
        if not isinstance(values, list):
            return {"normal"}
        return {str(value) for value in values}

    def _candidate_summary(self, node_key: str) -> dict[str, Any]:
        node = self._nodes_by_key[node_key]
        result = {
            "stableKey": node.stable_key,
            "nodeType": node.node_type,
            "displayName": node.display_name,
            "confidence": node.confidence,
            "sourceRefs": list(node.source_refs),
        }
        ascendancy_key = self._ascendancy_by_passive.get(node_key)
        if ascendancy_key:
            result["ascendancyKey"] = ascendancy_key
        return result

    def _node_summary(self, node_key: str) -> dict[str, Any] | None:
        node = self._nodes_by_key.get(node_key)
        if node is None:
            return None
        result = {
            "stableKey": node.stable_key,
            "nodeType": node.node_type,
            "displayName": node.display_name,
            "status": node.status,
            "confidence": node.confidence,
        }
        ascendancy_key = self._ascendancy_by_passive.get(node_key)
        if ascendancy_key:
            result["ascendancyKey"] = ascendancy_key
        return result

    def _source_refs_for_keys(
        self, node_keys: list[str | None] | tuple[str | None, ...]
    ) -> list[str]:
        refs: set[str] = set()
        for node_key in node_keys:
            if node_key is None:
                continue
            node = self._nodes_by_key.get(str(node_key))
            if node is not None:
                refs.update(node.source_refs)
        return sorted(refs)

    def _mapping_source_refs(self, system: str, external_id: str) -> list[str]:
        refs = {
            source_ref
            for mapping in self.snapshot.id_mappings
            if mapping.system == system and mapping.external_id == external_id
            for source_ref in mapping.source_refs
        }
        return sorted(refs)

    def _evidence_path(
        self,
        *,
        nodes: list[str] | tuple[str, ...] = (),
        edges: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        computed_fact_ids: list[str] | tuple[str, ...] = (),
        source_refs: list[str] | tuple[str, ...] = (),
        caveats: list[str] | tuple[str, ...] = (),
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        source_status = {
            source_ref: self._sources_by_id[source_ref].kind
            for source_ref in source_refs
            if source_ref in self._sources_by_id
        }
        return {
            "snapshotId": self.snapshot.snapshot_id,
            "nodes": list(nodes),
            "edges": list(edges),
            "computedFactIds": list(computed_fact_ids),
            "sourceRefs": list(source_refs),
            "sourceStatus": source_status,
            "confidence": confidence,
            "caveats": list(caveats),
            "versionContext": self._version_context(),
        }

    def _version_context(self) -> dict[str, Any]:
        context: dict[str, Any] = {}
        for source in self.snapshot.sources:
            for key in ("game_patch", "passive_tree_version", "pob_version", "pob_commit"):
                value = source.claim(key)
                if value is not None and key not in context:
                    context[key] = value
        return context

    def _version_context_mismatches(self, context: VersionContext) -> list[str]:
        snapshot_context = self._version_context()
        mismatches: list[str] = []
        supplied = context.model_dump(exclude_none=True)
        supplied.pop("context_type", None)
        for key, value in sorted(supplied.items()):
            snapshot_value = snapshot_context.get(key)
            if snapshot_value is not None and snapshot_value != value:
                mismatches.append(key)
        return mismatches

    def _missing_context_result(
        self,
        *,
        query_family: str,
        missing: list[str],
        context_caveats: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._envelope(
            query_family=query_family,
            status="missing_context",
            facts={},
            confidence=0.0,
            caveats=list(context_caveats or []),
            missing_context=missing,
            context_caveats=list(context_caveats or []),
            context=context or {},
        )

    def _error(
        self,
        *,
        query_family: str,
        error_code: str,
        caveats: list[str],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._envelope(
            query_family=query_family,
            status="error",
            error_code=error_code,
            facts={"recoverable": True},
            confidence=0.0,
            caveats=caveats,
            context=context or {},
        )

    def _envelope(
        self,
        *,
        query_family: str,
        status: str,
        facts: dict[str, Any],
        error_code: str | None = None,
        resolved_subject: dict[str, Any] | None = None,
        source_refs: list[str] | tuple[str, ...] = (),
        evidence_path: dict[str, Any] | None = None,
        confidence: float = 1.0,
        caveats: list[str] | tuple[str, ...] = (),
        context: dict[str, Any] | None = None,
        missing_context: list[str] | tuple[str, ...] = (),
        context_caveats: list[str] | tuple[str, ...] = (),
        endpoint_assessment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_refs_list = sorted({str(ref) for ref in source_refs})
        envelope = {
            "toolName": query_family,
            "queryFamily": query_family,
            "snapshotId": self.snapshot.snapshot_id,
            "status": status,
            "errorCode": error_code,
            "resolvedSubject": resolved_subject,
            "facts": facts,
            "evidencePath": evidence_path
            or self._evidence_path(
                source_refs=source_refs_list,
                caveats=list(caveats),
                confidence=confidence,
            ),
            "sourceRefs": source_refs_list,
            "confidence": confidence,
            "caveats": list(caveats),
            "contextPolicy": CONTEXT_POLICIES.get(query_family, "none"),
            "contextUsed": context or {},
            "missingContext": list(missing_context),
            "contextCaveats": list(context_caveats),
            "freshness": {"versionContext": self._version_context()},
            "noRawQuery": True,
        }
        if endpoint_assessment is not None:
            envelope["endpointAssessment"] = endpoint_assessment
        return envelope


@lru_cache(maxsize=8)
def service_from_snapshot_path(snapshot_path: str) -> GraphQueryService:
    return GraphQueryService.from_snapshot_path(snapshot_path)


def service_from_snapshot_index(index_path: str) -> GraphQueryService:
    rows = pg.list_registered_snapshots(index_path)
    if not rows:
        raise ValueError("missing latest snapshot")
    latest = next((row for row in rows if row["is_latest"]), rows[0])
    snapshot_path = str(latest["snapshot_path"])
    mtime_ns = Path(snapshot_path).stat().st_mtime_ns
    return _service_from_latest_registration(
        str(Path(index_path).resolve()),
        str(latest["snapshot_id"]),
        snapshot_path,
        mtime_ns,
    )


@lru_cache(maxsize=8)
def _service_from_latest_registration(
    index_path: str,
    snapshot_id: str,
    snapshot_path: str,
    snapshot_mtime_ns: int,
) -> GraphQueryService:
    del index_path, snapshot_id, snapshot_mtime_ns
    return GraphQueryService.from_snapshot_path(snapshot_path)


def clear_service_cache() -> None:
    service_from_snapshot_path.cache_clear()
    _service_from_latest_registration.cache_clear()


def _context_payload(context: GraphToolContext | None) -> dict[str, Any]:
    if context is None:
        return {}
    return context.model_dump(exclude_none=True)


def _endpoint_assessment(
    classification: str,
    *,
    candidate_endpoint_names: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "classification": classification,
        "hallucinationVerdict": "not_assessed",
        "candidateEndpointKeys": [],
        "missingEndpointKeys": [],
        "safeMetadataCandidateNames": sorted(
            {str(name) for name in candidate_endpoint_names or [] if str(name).strip()}
        ),
        "candidateNameProvenance": "resolver_query_unresolved_label",
        "reason": (
            "No graph candidate matched this resolver query in the current physical graph snapshot. "
            "This can be a static source coverage gap for a real game entity, so it is not evidence "
            "of hallucination by itself."
        ),
        "requiresStaticSourceReview": True,
    }


def _validation_caveat(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", ())) or "input"
    message = str(first.get("msg", "invalid input"))
    hint = ""
    if "context" in loc.split(".") and first.get("type") in {
        "union_tag_invalid",
        "union_tag_not_found",
        "model_attributes_type",
    }:
        hint = (
            f" context_type must be one of: {', '.join(_CONTEXT_TYPE_TAGS)} "
            "(or omit context entirely)."
        )
    return f"Tool input validation failed at '{loc}': {message}. Only use typed schema.{hint}"


def _json_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _raw_query_field_paths(value: Any, *, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text.casefold() in RAW_QUERY_FIELDS:
                paths.append(path)
            paths.extend(_raw_query_field_paths(nested, prefix=path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_raw_query_field_paths(nested, prefix=f"{prefix}[{index}]"))
    return sorted(paths)


def _bounded_shortest_path_length(
    graph: nx.Graph,
    start_key: str,
    end_key: str,
    *,
    cutoff: int,
) -> int | None:
    lengths = nx.single_source_shortest_path_length(graph, start_key, cutoff=cutoff)
    value = lengths.get(end_key)
    return int(value) if value is not None else None


def _subject_key(result: pg.ComputedFactResult) -> str:
    inputs = result.request.inputs
    for key in (
        "component_key",
        "skill_key",
        "base_item_key",
        "passive_key",
        "unique_key",
        "caveat_key",
        "support_key",
    ):
        value = inputs.get(key)
        if isinstance(value, str):
            return value
    return ""


def _fact_node_keys(facts: dict[str, Any]) -> list[str]:
    keys: set[str] = set()
    for key, value in facts.items():
        if key.endswith("_key") and isinstance(value, str):
            keys.add(value)
        elif key.endswith("_keys") and isinstance(value, list):
            keys.update(str(item) for item in value if isinstance(item, str))
    return sorted(keys)


def _path_edges(path: list[str]) -> list[dict[str, str]]:
    return [
        {"edgeType": "connected_to", "sourceKey": source, "targetKey": target}
        for source, target in zip(path, path[1:])
    ]


def _exclusive_weapon_state(states: set[str]) -> int | None:
    if "weapon_set_1" in states and "weapon_set_2" not in states and "both_sets" not in states:
        return 1
    if "weapon_set_2" in states and "weapon_set_1" not in states and "both_sets" not in states:
        return 2
    return None
