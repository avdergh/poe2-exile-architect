"""Physical graph contracts for source-backed PoE2 facts.

Phase 2 starts with small immutable records and strict validation. This module
does not ingest source files yet; it defines the contracts later ingestion code
must satisfy before facts can enter a durable physical graph snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


ALLOWED_EDGE_TYPES: frozenset[str] = frozenset(
    {
        "applies_to_tag",
        "belongs_to",
        "belongs_to_passive",
        "compatible_with",
        "connected_to",
        "granted_by",
        "grants_skill",
        "has_allocation_option",
        "has_base",
        "has_item_class",
        "has_mod_text",
        "has_requirement",
        "has_resource_cost",
        "has_reservation",
        "has_socket_constraint",
        "has_stat_text",
        "has_support_limit_rule",
        "has_tag",
        "has_type",
        "has_unlock_constraint",
        "recommended_for",
        "requires_item_class",
        "requires_weapon_type",
        "shares_tag_with",
        "starts_at",
    }
)

RESOLUTION_STATUSES: frozenset[str] = frozenset(
    {"resolved", "ambiguous", "unsupported", "stale", "missing"}
)
CAPABILITY_STATUSES: frozenset[str] = frozenset(
    {"exportable", "unsupported", "ambiguous", "requires_phase6_mapping"}
)
FACT_STATUSES: frozenset[str] = frozenset({"known", "unknown", "unsupported", "ambiguous"})
ALLOCATION_STATES: frozenset[str] = frozenset(
    {"normal", "weapon_set_1", "weapon_set_2", "both_sets"}
)


@dataclass(frozen=True, slots=True)
class SourceInventorySpec:
    """One static source file expected by the Phase 2 source inventory."""

    source_id: str
    kind: str
    relative_path: str
    schema_version: str
    claims: tuple[SourceClaim, ...] = ()
    source_url: str | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _required_text(self.source_id, "source id"))
        object.__setattr__(self, "kind", _required_text(self.kind, "source kind"))
        object.__setattr__(
            self,
            "relative_path",
            _required_text(self.relative_path, "source relative path"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema version"),
        )
        claims = tuple(self.claims)
        _reject_duplicate_texts((claim.key for claim in claims), "source claim")
        object.__setattr__(self, "claims", claims)
        if self.source_url is not None:
            object.__setattr__(self, "source_url", _required_text(self.source_url, "source url"))
        object.__setattr__(self, "confidence", _confidence(self.confidence))


@dataclass(frozen=True, slots=True)
class SourceClaim:
    """A single source-level provenance claim.

    Claim values deliberately preserve explicit states such as ``unknown`` and
    ``not_applicable`` instead of forcing fake patch or version identifiers.
    """

    key: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _required_text(self.key, "claim key"))
        object.__setattr__(self, "value", _required_text(self.value, "claim value"))


@dataclass(frozen=True, slots=True)
class GraphSource:
    """Provenance record for a static source used by the physical graph."""

    source_id: str
    kind: str
    source_file: str
    claims: tuple[SourceClaim, ...] = ()
    expected_count: int | None = None
    confidence: float = 1.0
    source_url: str | None = None
    schema_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _required_text(self.source_id, "source id"))
        object.__setattr__(self, "kind", _required_text(self.kind, "source kind"))
        object.__setattr__(self, "source_file", _required_text(self.source_file, "source file"))
        claims = tuple(self.claims)
        _reject_duplicate_texts((claim.key for claim in claims), "source claim")
        object.__setattr__(self, "claims", claims)
        if self.expected_count is not None and self.expected_count < 0:
            raise ValueError("expected count must be non-negative")
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if self.source_url is not None:
            object.__setattr__(self, "source_url", _required_text(self.source_url, "source url"))
        if self.schema_version is not None:
            object.__setattr__(
                self,
                "schema_version",
                _required_text(self.schema_version, "schema version"),
            )

    def claim(self, key: str) -> str | None:
        """Return a provenance claim value by key, or ``None`` when absent."""

        normalized_key = _required_text(key, "claim key")
        for claim in self.claims:
            if claim.key == normalized_key:
                return claim.value
        return None


def build_source_inventory(
    *,
    raw_data_dir: str | Path,
    specs: tuple[SourceInventorySpec, ...] | None = None,
    include_missing: bool = False,
) -> tuple[GraphSource, ...]:
    """Build a deterministic inventory for static raw sources.

    The builder records conservative provenance only. Freshness integration can
    later override claims through explicit ``SourceInventorySpec.claims`` values;
    absent evidence remains ``unknown`` or ``not_applicable``.
    """

    root = Path(raw_data_dir)
    specs = specs or DEFAULT_SOURCE_INVENTORY_SPECS
    sources: list[GraphSource] = []
    _reject_duplicate_texts((spec.source_id for spec in specs), "source inventory spec")
    for spec in specs:
        source_path = root / spec.relative_path
        if not source_path.exists():
            if not include_missing:
                raise FileNotFoundError(str(source_path))
            sources.append(_missing_inventory_source(spec))
            continue
        sources.append(
            GraphSource(
                source_id=spec.source_id,
                kind=spec.kind,
                source_file=spec.relative_path,
                claims=_inventory_claims(spec, freshness_status="unknown"),
                expected_count=_json_top_level_count(source_path),
                confidence=spec.confidence,
                source_url=spec.source_url,
                schema_version=spec.schema_version,
            )
        )
    return tuple(sorted(sources, key=lambda source: source.source_id))


def ingest_skill_gems(path: str | Path, *, source: GraphSource) -> GraphIngestionResult:
    """Ingest RePoE skill gem records into physical graph nodes and edges.

    This parser only materializes explicit raw facts. Recommended support links
    stay ``recommended_for`` and are never promoted to hard compatibility.
    """

    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("skill gem source must be a JSON object")

    nodes: dict[str, GraphNode] = {}
    edges: set[GraphEdge] = set()
    aliases: dict[tuple[str, str], GraphAlias] = {}
    id_mappings: dict[tuple[str, str], GraphIdMapping] = {}

    for metadata_id, record in sorted(payload.items()):
        if not isinstance(record, dict):
            raise ValueError(f"skill gem record must be an object: {metadata_id}")
        gem_type = _required_text(str(record.get("gem_type") or "active"), "gem type")
        gem_node_type = "support_gem" if gem_type == "support" else "skill_gem"
        gem_key = _gem_key(str(metadata_id), gem_type)
        display_name = _gem_display_name(record, str(metadata_id))
        nodes[gem_key] = GraphNode(
            stable_key=gem_key,
            node_type=gem_node_type,
            display_name=display_name,
            source_refs=(source.source_id,),
        )
        aliases[(display_name, gem_key)] = GraphAlias(
            alias=display_name,
            target_key=gem_key,
            source_refs=(source.source_id,),
        )
        id_mappings[("repoe:gem_metadata", str(metadata_id))] = GraphIdMapping(
            system="repoe:gem_metadata",
            external_id=str(metadata_id),
            target_key=gem_key,
            source_refs=(source.source_id,),
        )

        for tag in _string_list(record.get("tags"), f"{metadata_id} tags"):
            tag_key = f"tag:gem:{_normalized_token(tag)}"
            nodes.setdefault(
                tag_key,
                GraphNode(
                    stable_key=tag_key,
                    node_type="gem_tag",
                    display_name=tag,
                    source_refs=(source.source_id,),
                ),
            )
            edges.add(
                GraphEdge(
                    edge_type="has_tag",
                    source_key=gem_key,
                    target_key=tag_key,
                    evidence_refs=(source.source_id,),
                )
            )

        for skill_id in _string_list(record.get("grants_skills"), f"{metadata_id} grants_skills"):
            skill_key = f"skill:{skill_id}"
            nodes.setdefault(
                skill_key,
                GraphNode(
                    stable_key=skill_key,
                    node_type="active_skill",
                    display_name=skill_id,
                    source_refs=(source.source_id,),
                ),
            )
            edges.add(
                GraphEdge(
                    edge_type="grants_skill",
                    source_key=gem_key,
                    target_key=skill_key,
                    evidence_refs=(source.source_id,),
                )
            )
            edges.add(
                GraphEdge(
                    edge_type="granted_by",
                    source_key=skill_key,
                    target_key=gem_key,
                    evidence_refs=(source.source_id,),
                )
            )

        for support_metadata_id in _string_list(
            record.get("recommended_supports"),
            f"{metadata_id} recommended_supports",
        ):
            support_record = payload.get(support_metadata_id)
            if not isinstance(support_record, dict) or support_record.get("gem_type") != "support":
                continue
            support_key = _gem_key(support_metadata_id, "support")
            edges.add(
                GraphEdge(
                    edge_type="recommended_for",
                    source_key=support_key,
                    target_key=gem_key,
                    evidence_refs=(source.source_id,),
                    confidence=0.75,
                )
            )

    return GraphIngestionResult(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.stable_key)),
        edges=tuple(sorted(edges, key=_edge_sort_key)),
        aliases=tuple(
            sorted(aliases.values(), key=lambda alias: (alias.normalized_alias, alias.target_key))
        ),
        id_mappings=tuple(
            sorted(id_mappings.values(), key=lambda mapping: (mapping.system, mapping.external_id))
        ),
    )


def ingest_skills(path: str | Path, *, source: GraphSource) -> GraphIngestionResult:
    """Ingest RePoE skill records into source-backed skill nodes and resource facts."""

    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("skill source must be a JSON object")

    nodes: dict[str, GraphNode] = {}
    edges: set[GraphEdge] = set()
    aliases: dict[tuple[str, str], GraphAlias] = {}
    id_mappings: dict[tuple[str, str], GraphIdMapping] = {}
    requirement_facts: dict[tuple[str, str], RequirementFact] = {}
    resource_facts: dict[tuple[str, str], ResourceFact] = {}

    for skill_id, record in sorted(payload.items()):
        if not isinstance(record, dict):
            raise ValueError(f"skill record must be an object: {skill_id}")
        skill_key = f"skill:{skill_id}"
        nodes[skill_key] = GraphNode(
            stable_key=skill_key,
            node_type="active_skill",
            display_name=str(skill_id),
            source_refs=(source.source_id,),
        )
        id_mappings[("repoe:skill_id", str(skill_id))] = GraphIdMapping(
            system="repoe:skill_id",
            external_id=str(skill_id),
            target_key=skill_key,
            source_refs=(source.source_id,),
        )

        active_skill = record.get("active_skill")
        if isinstance(active_skill, dict):
            display_name = active_skill.get("display_name")
            if isinstance(display_name, str) and display_name.strip():
                aliases[(display_name, skill_key)] = GraphAlias(
                    alias=display_name,
                    target_key=skill_key,
                    source_refs=(source.source_id,),
                )

            for skill_type in _string_list(
                active_skill.get("types"), f"{skill_id} active_skill.types"
            ):
                type_key = f"skill_type:{_normalized_token(skill_type)}"
                nodes.setdefault(
                    type_key,
                    GraphNode(
                        stable_key=type_key,
                        node_type="skill_type",
                        display_name=skill_type,
                        source_refs=(source.source_id,),
                    ),
                )
                edges.add(
                    GraphEdge(
                        edge_type="has_type",
                        source_key=skill_key,
                        target_key=type_key,
                        evidence_refs=(source.source_id,),
                    )
                )

            for weapon_type in _string_list(
                active_skill.get("weapon_restrictions"),
                f"{skill_id} active_skill.weapon_restrictions",
            ):
                weapon_key = f"weapon_type:{_normalized_token(weapon_type)}"
                nodes.setdefault(
                    weapon_key,
                    GraphNode(
                        stable_key=weapon_key,
                        node_type="weapon_type",
                        display_name=weapon_type,
                        source_refs=(source.source_id,),
                    ),
                )
                edges.add(
                    GraphEdge(
                        edge_type="requires_weapon_type",
                        source_key=skill_key,
                        target_key=weapon_key,
                        evidence_refs=(source.source_id,),
                    )
                )

        static_profile = _resource_profile_parts(record.get("static"), skill_id, label="static")
        if static_profile is not None:
            resource_facts[(skill_key, "base")] = ResourceFact(
                component_key=skill_key,
                level_or_stage="base",
                costs=static_profile["costs"],
                reservations=static_profile["reservations"],
                source_refs=(source.source_id,),
            )

        per_level = record.get("per_level")
        if per_level is not None:
            if not isinstance(per_level, dict):
                raise ValueError(f"{skill_id} per_level must be an object")
            for level_or_stage, stage_payload in sorted(per_level.items()):
                profile = _resource_profile_parts(
                    stage_payload,
                    skill_id,
                    label=f"per_level[{level_or_stage}]",
                )
                if profile is None:
                    continue
                resource_facts[(skill_key, str(level_or_stage))] = ResourceFact(
                    component_key=skill_key,
                    level_or_stage=str(level_or_stage),
                    costs=profile["costs"],
                    reservations=profile["reservations"],
                    source_refs=(source.source_id,),
                )

        support_gem = record.get("support_gem")
        if isinstance(support_gem, dict):
            support_contract = {
                "allowed_types_expr": _type_expression(
                    support_gem.get("allowed_types"),
                    f"{skill_id} support_gem.allowed_types",
                ),
                "excluded_types_expr": _type_expression(
                    support_gem.get("excluded_types"),
                    f"{skill_id} support_gem.excluded_types",
                ),
                "supports_gems_only": bool(support_gem.get("supports_gems_only", False)),
                "added_types": _type_expression(
                    support_gem.get("added_types"),
                    f"{skill_id} support_gem.added_types",
                ),
                "added_minion_types": _type_expression(
                    support_gem.get("added_minion_types"),
                    f"{skill_id} support_gem.added_minion_types",
                ),
            }
            requirement_facts[(skill_key, "support_contract")] = RequirementFact(
                component_key=skill_key,
                level_or_stage="support_contract",
                requirements=support_contract,
                source_refs=(source.source_id,),
            )

    return GraphIngestionResult(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.stable_key)),
        edges=tuple(sorted(edges, key=_edge_sort_key)),
        aliases=tuple(
            sorted(aliases.values(), key=lambda alias: (alias.normalized_alias, alias.target_key))
        ),
        id_mappings=tuple(
            sorted(id_mappings.values(), key=lambda mapping: (mapping.system, mapping.external_id))
        ),
        requirement_facts=tuple(
            sorted(
                requirement_facts.values(),
                key=lambda fact: (fact.component_key, fact.level_or_stage),
            )
        ),
        resource_facts=tuple(
            sorted(
                resource_facts.values(), key=lambda fact: (fact.component_key, fact.level_or_stage)
            )
        ),
    )


def ingest_base_items(path: str | Path, *, source: GraphSource) -> GraphIngestionResult:
    """Ingest RePoE base item records into physical graph nodes and facts."""

    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("base item source must be a JSON object")

    nodes: dict[str, GraphNode] = {}
    edges: set[GraphEdge] = set()
    aliases: dict[tuple[str, str], GraphAlias] = {}
    id_mappings: dict[tuple[str, str], GraphIdMapping] = {}
    requirement_facts: dict[str, RequirementFact] = {}

    for metadata_id, record in sorted(payload.items()):
        if not isinstance(record, dict):
            raise ValueError(f"base item record must be an object: {metadata_id}")
        item_key = f"item_base:{metadata_id}"
        display_name = _required_text(
            str(record.get("name") or metadata_id.rsplit("/", 1)[-1]),
            "base item display name",
        )
        nodes[item_key] = GraphNode(
            stable_key=item_key,
            node_type="item_base",
            display_name=display_name,
            source_refs=(source.source_id,),
        )
        aliases[(display_name, item_key)] = GraphAlias(
            alias=display_name,
            target_key=item_key,
            source_refs=(source.source_id,),
        )
        id_mappings[("repoe:base_item_metadata", str(metadata_id))] = GraphIdMapping(
            system="repoe:base_item_metadata",
            external_id=str(metadata_id),
            target_key=item_key,
            source_refs=(source.source_id,),
        )

        item_class = record.get("item_class")
        if item_class:
            class_key = f"item_class:{_normalized_token(str(item_class))}"
            nodes.setdefault(
                class_key,
                GraphNode(
                    stable_key=class_key,
                    node_type="item_class",
                    display_name=str(item_class),
                    source_refs=(source.source_id,),
                ),
            )
            edges.add(
                GraphEdge(
                    edge_type="has_item_class",
                    source_key=item_key,
                    target_key=class_key,
                    evidence_refs=(source.source_id,),
                )
            )

        for tag in _string_list(record.get("tags"), f"{metadata_id} tags"):
            tag_key = f"tag:item:{_normalized_token(tag)}"
            nodes.setdefault(
                tag_key,
                GraphNode(
                    stable_key=tag_key,
                    node_type="item_tag",
                    display_name=tag,
                    source_refs=(source.source_id,),
                ),
            )
            edges.add(
                GraphEdge(
                    edge_type="has_tag",
                    source_key=item_key,
                    target_key=tag_key,
                    evidence_refs=(source.source_id,),
                )
            )

        requirements: dict[str, Any] = {}
        raw_requirements = record.get("requirements")
        if isinstance(raw_requirements, dict):
            requirements.update(raw_requirements)
        if record.get("domain") is not None:
            requirements["domain"] = _required_text(str(record["domain"]), "base item domain")
        if record.get("drop_level") is not None:
            requirements["drop_level"] = record["drop_level"]
        if item_class:
            requirements["item_class"] = str(item_class)
        if requirements:
            requirement_facts[item_key] = RequirementFact(
                component_key=item_key,
                level_or_stage="base",
                requirements=requirements,
                source_refs=(source.source_id,),
            )

    return GraphIngestionResult(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.stable_key)),
        edges=tuple(sorted(edges, key=_edge_sort_key)),
        aliases=tuple(
            sorted(aliases.values(), key=lambda alias: (alias.normalized_alias, alias.target_key))
        ),
        id_mappings=tuple(
            sorted(id_mappings.values(), key=lambda mapping: (mapping.system, mapping.external_id))
        ),
        requirement_facts=tuple(
            sorted(requirement_facts.values(), key=lambda fact: fact.component_key)
        ),
    )


def ingest_passive_tree(
    path: str | Path,
    *,
    source: GraphSource,
    tree_version: str | None = None,
) -> GraphIngestionResult:
    """Ingest one PoB passive tree JSON into minimal passive graph nodes and edges."""

    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("passive tree source must be a JSON object")

    resolved_tree_version = (
        _required_text(tree_version, "passive tree version")
        if tree_version is not None
        else source.claim("passive_tree_version")
    )
    if resolved_tree_version in {None, "unknown", "not_applicable"}:
        raise ValueError("passive tree version is required")
    tree_version_text = _required_text(str(resolved_tree_version), "passive tree version")

    classes_payload = payload.get("classes")
    nodes_payload = payload.get("nodes")
    if not isinstance(classes_payload, list):
        raise ValueError("passive tree classes must be a list")
    if not isinstance(nodes_payload, dict):
        raise ValueError("passive tree nodes must be an object")

    nodes: dict[str, GraphNode] = {}
    edges: set[GraphEdge] = set()
    aliases: dict[tuple[str, str], GraphAlias] = {}
    id_mappings: dict[tuple[str, str], GraphIdMapping] = {}
    requirement_facts: dict[tuple[str, str], RequirementFact] = {}
    passive_choices: dict[str, PassiveChoice] = {}
    allocation_options: dict[str, AllocationOption] = {}

    class_names = {
        _normalized_token(str(class_record.get("name")))
        for class_record in classes_payload
        if isinstance(class_record, dict) and class_record.get("name")
    }

    for class_record in classes_payload:
        if not isinstance(class_record, dict):
            raise ValueError("passive tree class entry must be an object")
        class_name = _required_text(str(class_record.get("name")), "passive tree class name")
        class_key = f"class:{_normalized_token(class_name)}"
        nodes[class_key] = GraphNode(
            stable_key=class_key,
            node_type="class",
            display_name=class_name,
            source_refs=(source.source_id,),
        )
        aliases[(class_name, class_key)] = GraphAlias(
            alias=class_name,
            target_key=class_key,
            source_refs=(source.source_id,),
        )
        if class_record.get("integerId") is not None:
            id_mappings[("pob:class_integer_id", str(class_record["integerId"]))] = GraphIdMapping(
                system="pob:class_integer_id",
                external_id=str(class_record["integerId"]),
                target_key=class_key,
                source_refs=(source.source_id,),
            )

        ascendancies = class_record.get("ascendancies")
        if ascendancies is None:
            continue
        if not isinstance(ascendancies, list):
            raise ValueError(f"{class_name} ascendancies must be a list")
        for ascendancy in ascendancies:
            if not isinstance(ascendancy, dict):
                raise ValueError("ascendancy entry must be an object")
            ascendancy_name = _required_text(
                str(ascendancy.get("name") or ascendancy.get("id")),
                "ascendancy name",
            )
            ascendancy_key = (
                f"ascendancy:{_normalized_token(class_name)}:{_normalized_token(ascendancy_name)}"
            )
            nodes[ascendancy_key] = GraphNode(
                stable_key=ascendancy_key,
                node_type="ascendancy",
                display_name=ascendancy_name,
                source_refs=(source.source_id,),
            )
            aliases[(ascendancy_name, ascendancy_key)] = GraphAlias(
                alias=ascendancy_name,
                target_key=ascendancy_key,
                source_refs=(source.source_id,),
            )
            edges.add(
                GraphEdge(
                    edge_type="belongs_to",
                    source_key=ascendancy_key,
                    target_key=class_key,
                    evidence_refs=(source.source_id,),
                )
            )
            if ascendancy.get("id") is not None:
                id_mappings[("pob:ascendancy_id", str(ascendancy["id"]))] = GraphIdMapping(
                    system="pob:ascendancy_id",
                    external_id=str(ascendancy["id"]),
                    target_key=ascendancy_key,
                    source_refs=(source.source_id,),
                )
            if ascendancy.get("internalId") is not None:
                id_mappings[("pob:ascendancy_internal_id", str(ascendancy["internalId"]))] = (
                    GraphIdMapping(
                        system="pob:ascendancy_internal_id",
                        external_id=str(ascendancy["internalId"]),
                        target_key=ascendancy_key,
                        source_refs=(source.source_id,),
                    )
                )

    type_keys = {
        "class_start": "passive_type:class_start",
        "ascendancy_start": "passive_type:ascendancy_start",
        "notable": "passive_type:notable",
        "keystone": "passive_type:keystone",
        "passive": "passive_type:passive",
    }
    for label, type_key in type_keys.items():
        nodes[type_key] = GraphNode(
            stable_key=type_key,
            node_type="passive_type",
            display_name=label,
            source_refs=(source.source_id,),
        )

    for node_id, node_record in sorted(nodes_payload.items(), key=lambda item: int(str(item[0]))):
        if not isinstance(node_record, dict):
            raise ValueError(f"passive node record must be an object: {node_id}")
        passive_key = _passive_node_key(
            node_record, node_id=node_id, tree_version=tree_version_text
        )
        passive_name = _required_text(
            str(node_record.get("name") or node_id),
            "passive node name",
        )
        node_type = _passive_node_type(node_record)
        nodes[passive_key] = GraphNode(
            stable_key=passive_key,
            node_type=node_type,
            display_name=passive_name,
            source_refs=(source.source_id,),
            official_ids={
                "pob:passive_node_id": str(node_id),
                "pob:passive_skill_node_id": str(node_record.get("skill") or node_id),
            },
        )
        aliases[(passive_name, passive_key)] = GraphAlias(
            alias=passive_name,
            target_key=passive_key,
            source_refs=(source.source_id,),
        )
        id_mappings[("pob:passive_node_id", str(node_id))] = GraphIdMapping(
            system="pob:passive_node_id",
            external_id=str(node_id),
            target_key=passive_key,
            source_refs=(source.source_id,),
        )
        if node_record.get("skill") is not None:
            id_mappings[("pob:passive_skill_node_id", str(node_record["skill"]))] = GraphIdMapping(
                system="pob:passive_skill_node_id",
                external_id=str(node_record["skill"]),
                target_key=passive_key,
                source_refs=(source.source_id,),
            )

        passive_type_key = _passive_type_key_for_record(node_record)
        edges.add(
            GraphEdge(
                edge_type="has_type",
                source_key=passive_key,
                target_key=passive_type_key,
                evidence_refs=(source.source_id,),
            )
        )

        for class_name in _string_list(
            node_record.get("classesStart"),
            f"{node_id} classesStart",
        ):
            class_key = f"class:{_normalized_token(class_name)}"
            if _normalized_token(class_name) in class_names:
                edges.add(
                    GraphEdge(
                        edge_type="starts_at",
                        source_key=class_key,
                        target_key=passive_key,
                        evidence_refs=(source.source_id,),
                    )
                )

        ascendancy_name = node_record.get("ascendancyName")
        if isinstance(ascendancy_name, str) and ascendancy_name.strip():
            ascendancy_key = _ascendancy_key_for_name(nodes, ascendancy_name)
            if ascendancy_key is not None:
                edges.add(
                    GraphEdge(
                        edge_type="belongs_to",
                        source_key=passive_key,
                        target_key=ascendancy_key,
                        evidence_refs=(source.source_id,),
                    )
                )

        for stat_text in _string_list(node_record.get("stats"), f"{node_id} stats"):
            stat_key = (
                f"passive_stat_text:{tree_version_text}:{node_id}:{_stable_text_token(stat_text)}"
            )
            nodes.setdefault(
                stat_key,
                GraphNode(
                    stable_key=stat_key,
                    node_type="passive_stat_text",
                    display_name=stat_text,
                    source_refs=(source.source_id,),
                ),
            )
            edges.add(
                GraphEdge(
                    edge_type="has_stat_text",
                    source_key=passive_key,
                    target_key=stat_key,
                    evidence_refs=(source.source_id,),
                )
            )

        if "unlockConstraint" in node_record:
            unlock_constraint = node_record["unlockConstraint"]
            if not isinstance(unlock_constraint, dict):
                raise ValueError(f"{node_id} unlockConstraint must be an object")
            requirement_facts[(passive_key, "unlock_constraint")] = RequirementFact(
                component_key=passive_key,
                level_or_stage="unlock_constraint",
                requirements=dict(unlock_constraint),
                source_refs=(source.source_id,),
            )
        options_payload = node_record.get("options")
        if options_payload is not None:
            choice_id = str(node_record.get("skill") or node_id)
            choice_key = f"passive_choice:{passive_key}:{choice_id}"
            passive_choices[choice_key] = PassiveChoice(
                choice_key=choice_key,
                parent_passive_key=passive_key,
                display_name=passive_name,
                stat_text=_first_stat_text(node_record.get("stats")),
                source_refs=(source.source_id,),
            )
            for option in _passive_options(options_payload, node_id=node_id):
                if not isinstance(option, dict):
                    raise ValueError(f"{node_id} option entry must be an object")
                option_id = _required_text(str(option.get("id")), f"{node_id} option id")
                option_name = _required_text(
                    str(option.get("name") or option_id),
                    f"{node_id} option name",
                )
                option_key = f"allocation_option:{passive_key}:{option_id}"
                allocation_options[option_key] = AllocationOption(
                    option_key=option_key,
                    choice_key=choice_key,
                    display_name=option_name,
                    stat_text=_first_stat_text(option.get("stats")) or option_name,
                    source_refs=(source.source_id,),
                )

    for node_id, node_record in sorted(nodes_payload.items(), key=lambda item: int(str(item[0]))):
        passive_key = _passive_node_key(
            node_record, node_id=node_id, tree_version=tree_version_text
        )
        unresolved_connections: list[int] = []
        for connection in _node_connections(node_record, node_id=node_id):
            target_record = nodes_payload.get(str(connection))
            if not isinstance(target_record, dict):
                unresolved_connections.append(connection)
                continue
            target_key = _passive_node_key(
                target_record,
                node_id=str(connection),
                tree_version=tree_version_text,
            )
            edges.add(
                GraphEdge(
                    edge_type="connected_to",
                    source_key=passive_key,
                    target_key=target_key,
                    evidence_refs=(source.source_id,),
                )
            )
        if unresolved_connections:
            requirement_facts[(passive_key, "connection_caveat")] = RequirementFact(
                component_key=passive_key,
                level_or_stage="connection_caveat",
                requirements={
                    "unresolved_connection_ids": sorted(unresolved_connections),
                    "skipped_unresolved_connections": len(unresolved_connections),
                },
                source_refs=(source.source_id,),
                status="ambiguous",
                confidence=0.5,
            )

    return GraphIngestionResult(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.stable_key)),
        edges=tuple(sorted(edges, key=_edge_sort_key)),
        aliases=tuple(
            sorted(aliases.values(), key=lambda alias: (alias.normalized_alias, alias.target_key))
        ),
        id_mappings=tuple(
            sorted(id_mappings.values(), key=lambda mapping: (mapping.system, mapping.external_id))
        ),
        requirement_facts=tuple(
            sorted(
                requirement_facts.values(),
                key=lambda fact: (fact.component_key, fact.level_or_stage),
            )
        ),
        passive_choices=tuple(
            sorted(passive_choices.values(), key=lambda choice: choice.choice_key)
        ),
        allocation_options=tuple(
            sorted(allocation_options.values(), key=lambda option: option.option_key)
        ),
    )


def ingest_mods(path: str | Path, *, source: GraphSource) -> GraphIngestionResult:
    """Ingest RePoE mod records without materializing item/mod cartesian products."""

    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("mod source must be a JSON object")

    nodes: dict[str, GraphNode] = {}
    edges: set[GraphEdge] = set()
    id_mappings: dict[tuple[str, str], GraphIdMapping] = {}
    requirement_facts: dict[str, RequirementFact] = {}

    for mod_id, record in sorted(payload.items()):
        if not isinstance(record, dict):
            raise ValueError(f"mod record must be an object: {mod_id}")
        mod_key = f"mod:{mod_id}"
        display_name = _required_text(str(record.get("name") or mod_id), "mod display name")
        nodes[mod_key] = GraphNode(
            stable_key=mod_key,
            node_type="mod",
            display_name=display_name,
            source_refs=(source.source_id,),
        )
        id_mappings[("repoe:mod_id", str(mod_id))] = GraphIdMapping(
            system="repoe:mod_id",
            external_id=str(mod_id),
            target_key=mod_key,
            source_refs=(source.source_id,),
        )
        required_level = record.get("required_level")
        generation_type = record.get("generation_type")
        groups = record.get("groups") if isinstance(record.get("groups"), list) else []
        text = record.get("text")
        requirement_facts[mod_key] = RequirementFact(
            component_key=mod_key,
            level_or_stage="base",
            requirements={
                "domain": record.get("domain"),
                "required_level": required_level,
                "generation_type": generation_type,
                "groups": groups,
                "text": text,
            },
            source_refs=(source.source_id,),
        )

        for tag in _positive_spawn_tags(record.get("spawn_weights"), str(mod_id)):
            tag_key = f"tag:item:{_normalized_token(tag)}"
            nodes.setdefault(
                tag_key,
                GraphNode(
                    stable_key=tag_key,
                    node_type="item_tag",
                    display_name=tag,
                    source_refs=(source.source_id,),
                ),
            )
            edges.add(
                GraphEdge(
                    edge_type="applies_to_tag",
                    source_key=mod_key,
                    target_key=tag_key,
                    evidence_refs=(source.source_id,),
                )
            )

    return GraphIngestionResult(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.stable_key)),
        edges=tuple(sorted(edges, key=_edge_sort_key)),
        id_mappings=tuple(
            sorted(id_mappings.values(), key=lambda mapping: (mapping.system, mapping.external_id))
        ),
        requirement_facts=tuple(
            sorted(requirement_facts.values(), key=lambda fact: fact.component_key)
        ),
    )


def ingest_inventory_slots(path: str | Path, *, source: GraphSource) -> GraphIngestionResult:
    """Ingest official Build Planner inventory slot examples into graph mappings."""

    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("inventory slot source must be a JSON object")

    nodes: dict[str, GraphNode] = {}
    aliases: dict[tuple[str, str], GraphAlias] = {}
    id_mappings: dict[tuple[str, str], GraphIdMapping] = {}
    requirement_facts: dict[tuple[str, str], RequirementFact] = {}

    for inventory_id, record in sorted(payload.items()):
        if not isinstance(record, dict):
            raise ValueError(f"inventory slot record must be an object: {inventory_id}")
        normalized_inventory_id = _required_text(str(inventory_id), "inventory id")
        slot_key = f"inventory_slot:{normalized_inventory_id}"
        display_name = _required_text(
            str(record.get("display_name") or normalized_inventory_id),
            "inventory slot display name",
        )
        nodes[slot_key] = GraphNode(
            stable_key=slot_key,
            node_type="inventory_slot",
            display_name=display_name,
            source_refs=(source.source_id,),
            official_ids={"ggg:Inventories": normalized_inventory_id},
        )
        aliases[(display_name, slot_key)] = GraphAlias(
            alias=display_name,
            target_key=slot_key,
            source_refs=(source.source_id,),
        )
        id_mappings[("ggg:Inventories", normalized_inventory_id)] = GraphIdMapping(
            system="ggg:Inventories",
            external_id=normalized_inventory_id,
            target_key=slot_key,
            source_refs=(source.source_id,),
        )

        requirements: dict[str, Any] = {}
        if record.get("build_slot") is not None:
            requirements["build_slot"] = _required_text(str(record["build_slot"]), "build slot")
        if record.get("weapon_set") is not None:
            requirements["weapon_set"] = _optional_int(record["weapon_set"])
        if requirements:
            requirement_facts[(slot_key, "build_inventory_slot")] = RequirementFact(
                component_key=slot_key,
                level_or_stage="build_inventory_slot",
                requirements=requirements,
                source_refs=(source.source_id,),
            )

    return GraphIngestionResult(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.stable_key)),
        aliases=tuple(
            sorted(aliases.values(), key=lambda alias: (alias.normalized_alias, alias.target_key))
        ),
        id_mappings=tuple(
            sorted(id_mappings.values(), key=lambda mapping: (mapping.system, mapping.external_id))
        ),
        requirement_facts=tuple(
            sorted(
                requirement_facts.values(),
                key=lambda fact: (fact.component_key, fact.level_or_stage),
            )
        ),
    )


def ingest_uniques(
    path: str | Path,
    *,
    source: GraphSource,
    known_base_nodes: tuple[GraphNode, ...] = (),
    known_base_aliases: tuple[GraphAlias, ...] = (),
) -> GraphIngestionResult:
    """Ingest PoB unique text blocks into conservative unique/base/mod-text facts."""

    text = Path(path).read_text(encoding="utf-8")
    blocks = _unique_item_blocks(text)
    base_by_name = {
        node.display_name: node.stable_key
        for node in known_base_nodes
        if node.node_type == "item_base"
    }
    for alias in known_base_aliases:
        target = next(
            (
                node.stable_key
                for node in known_base_nodes
                if node.stable_key == alias.target_key and node.node_type == "item_base"
            ),
            None,
        )
        if target is not None:
            base_by_name.setdefault(alias.alias, target)

    nodes: dict[str, GraphNode] = {}
    edges: set[GraphEdge] = set()
    aliases: dict[tuple[str, str], GraphAlias] = {}
    id_mappings: dict[tuple[str, str], GraphIdMapping] = {}

    for block in blocks:
        if len(block) < 2:
            continue
        unique_name = _required_text(block[0], "unique name")
        base_name = _required_text(block[1], "unique base name")
        unique_key = f"unique:pob:{_normalized_token(unique_name)}"
        nodes[unique_key] = GraphNode(
            stable_key=unique_key,
            node_type="unique",
            display_name=unique_name,
            source_refs=(source.source_id,),
        )
        aliases[(unique_name, unique_key)] = GraphAlias(
            alias=unique_name,
            target_key=unique_key,
            source_refs=(source.source_id,),
        )
        id_mappings[("pob:unique_name", unique_name)] = GraphIdMapping(
            system="pob:unique_name",
            external_id=unique_name,
            target_key=unique_key,
            source_refs=(source.source_id,),
        )
        base_key = base_by_name.get(base_name)
        if base_key is not None:
            edges.add(
                GraphEdge(
                    edge_type="has_base",
                    source_key=unique_key,
                    target_key=base_key,
                    evidence_refs=(source.source_id,),
                )
            )
        for line in _unique_mod_lines(block[2:]):
            mod_text_key = (
                f"unique_mod_text:{_normalized_token(unique_name)}:{_stable_text_token(line)}"
            )
            nodes.setdefault(
                mod_text_key,
                GraphNode(
                    stable_key=mod_text_key,
                    node_type="unique_mod_text",
                    display_name=line,
                    source_refs=(source.source_id,),
                ),
            )
            edges.add(
                GraphEdge(
                    edge_type="has_mod_text",
                    source_key=unique_key,
                    target_key=mod_text_key,
                    evidence_refs=(source.source_id,),
                )
            )

    return GraphIngestionResult(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.stable_key)),
        edges=tuple(sorted(edges, key=_edge_sort_key)),
        aliases=tuple(
            sorted(aliases.values(), key=lambda alias: (alias.normalized_alias, alias.target_key))
        ),
        id_mappings=tuple(
            sorted(id_mappings.values(), key=lambda mapping: (mapping.system, mapping.external_id))
        ),
    )


def can_roll_mod(
    *,
    snapshot: GraphSnapshot,
    base_item_key: str,
    mod_key: str,
    item_level: int,
) -> ComputedFactResult:
    """Compute whether one mod can roll on one base at a given item level."""

    base_key = _required_text(base_item_key, "base item key")
    mod_stable_key = _required_text(mod_key, "mod key")
    if item_level < 0:
        raise ValueError("item level must be non-negative")

    nodes_by_key = {node.stable_key: node for node in snapshot.nodes}
    if base_key not in nodes_by_key:
        raise ValueError(f"missing base item node: {base_key}")
    if mod_stable_key not in nodes_by_key:
        raise ValueError(f"missing mod node: {mod_stable_key}")

    base_tags = _target_keys(snapshot.edges, source_key=base_key, edge_type="has_tag")
    mod_tags = _target_keys(snapshot.edges, source_key=mod_stable_key, edge_type="applies_to_tag")
    matching_tags = sorted(_tag_name(tag) for tag in base_tags & mod_tags)
    base_requirements = _requirements_for(snapshot, base_key)
    mod_requirements = _requirements_for(snapshot, mod_stable_key)
    base_domain = _optional_nonempty_text(base_requirements.get("domain"))
    mod_domain = _optional_nonempty_text(mod_requirements.get("domain"))
    generation_type = _optional_nonempty_text(mod_requirements.get("generation_type"))
    required_level = _int_or_zero(mod_requirements.get("required_level"))
    source_refs = _source_refs_for_components(snapshot, (base_key, mod_stable_key))

    missing_constraints: list[str] = []
    if base_domain is None:
        missing_constraints.append("base_domain")
    if generation_type is None:
        missing_constraints.append("generation_type")
    if mod_domain is None:
        missing_constraints.append("mod_domain")
    if missing_constraints:
        return ComputedFactResult(
            request=ComputedFactRequest(
                fact_type="can_roll_mod",
                inputs={
                    "base_item_key": base_key,
                    "mod_key": mod_stable_key,
                    "item_level": item_level,
                },
            ),
            status="ambiguous",
            facts={
                "base_item_key": base_key,
                "mod_key": mod_stable_key,
                "item_level": item_level,
                "required_level": required_level,
                "matching_tags": matching_tags,
                "base_domain": base_domain,
                "mod_domain": mod_domain,
                "generation_type": generation_type,
                "missing_constraints": missing_constraints,
                "can_roll": None,
            },
            source_refs=source_refs,
            confidence=0.5,
            caveat="incomplete_mod_roll_constraints",
        )

    if base_domain != mod_domain:
        can_roll = False
        excluded_reason = "domain_mismatch"
    elif item_level < required_level:
        can_roll = False
        excluded_reason = "item_level_too_low"
    elif not matching_tags:
        can_roll = False
        excluded_reason = "tag_mismatch"
    else:
        can_roll = True
        excluded_reason = None

    facts: dict[str, Any] = {
        "base_item_key": base_key,
        "mod_key": mod_stable_key,
        "item_level": item_level,
        "required_level": required_level,
        "matching_tags": matching_tags,
        "base_domain": base_domain,
        "mod_domain": mod_domain,
        "generation_type": generation_type,
        "can_roll": can_roll,
    }
    if excluded_reason is not None:
        facts["excluded_reason"] = excluded_reason

    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type="can_roll_mod",
            inputs={
                "base_item_key": base_key,
                "mod_key": mod_stable_key,
                "item_level": item_level,
            },
        ),
        status="known",
        facts=facts,
        source_refs=source_refs,
    )


def unique_base_item(
    snapshot: GraphSnapshot,
    unique_key: str,
) -> ComputedFactResult:
    """Return the source-backed base item behind one unique item node."""

    stable_key = _required_text(unique_key, "unique key")
    node = next((item for item in snapshot.nodes if item.stable_key == stable_key), None)
    if node is None:
        raise ValueError(f"missing unique node: {stable_key}")
    if node.node_type != "unique":
        raise ValueError(f"node is not a unique item: {stable_key}")

    base_key = next(
        (
            edge.target_key
            for edge in snapshot.edges
            if edge.edge_type == "has_base" and edge.source_key == stable_key
        ),
        None,
    )
    if base_key is None:
        return ComputedFactResult(
            request=ComputedFactRequest(
                fact_type="unique_base_item",
                inputs={"unique_key": stable_key},
            ),
            status="unknown",
            facts={"unique_key": stable_key, "base_item_key": None, "base_item_name": None},
            source_refs=_source_refs_for_components(snapshot, (stable_key,)),
        )
    base_node = next((item for item in snapshot.nodes if item.stable_key == base_key), None)
    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type="unique_base_item",
            inputs={"unique_key": stable_key},
        ),
        status="known",
        facts={
            "unique_key": stable_key,
            "base_item_key": base_key,
            "base_item_name": base_node.display_name if base_node is not None else None,
        },
        source_refs=_source_refs_for_components(snapshot, (stable_key, base_key)),
    )


def requirements_for_component(
    snapshot: GraphSnapshot,
    component_key: str,
    *,
    level_or_stage: str,
) -> ComputedFactResult:
    """Return source-backed requirements for one known component and stage."""

    stable_key = _required_text(component_key, "component key")
    stage = _required_text(level_or_stage, "level or stage")
    node_keys = {node.stable_key for node in snapshot.nodes}
    if stable_key not in node_keys:
        raise ValueError(f"missing component node: {stable_key}")
    for fact in snapshot.requirement_facts:
        if fact.component_key == stable_key and fact.level_or_stage == stage:
            return ComputedFactResult(
                request=ComputedFactRequest(
                    fact_type="requirements_for_component",
                    inputs={"component_key": stable_key, "level_or_stage": stage},
                ),
                status="known",
                facts={"requirements": dict(fact.requirements)},
                source_refs=fact.source_refs,
            )
    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type="requirements_for_component",
            inputs={"component_key": stable_key, "level_or_stage": stage},
        ),
        status="unknown",
        facts={"requirements": {}},
        source_refs=_source_refs_for_components(snapshot, (stable_key,)),
    )


def resource_profile_for_component(
    snapshot: GraphSnapshot,
    component_key: str,
    *,
    level_or_stage: str,
) -> ComputedFactResult:
    """Return source-backed cost and reservation data for one component and stage."""

    stable_key = _required_text(component_key, "component key")
    stage = _required_text(level_or_stage, "level or stage")
    node_keys = {node.stable_key for node in snapshot.nodes}
    if stable_key not in node_keys:
        raise ValueError(f"missing component node: {stable_key}")
    facts_for_component = [
        fact for fact in snapshot.resource_facts if fact.component_key == stable_key
    ]
    exact = next((fact for fact in facts_for_component if fact.level_or_stage == stage), None)
    base = next((fact for fact in facts_for_component if fact.level_or_stage == "base"), None)
    staged = [fact for fact in facts_for_component if fact.level_or_stage != "base"]

    merged = _merge_resource_fact(exact, base, requested_stage=stage)
    if merged is not None:
        return merged
    if base is not None and not staged:
        return _resource_result(
            component_key=stable_key,
            requested_stage=stage,
            actual_stage=base.level_or_stage,
            costs=base.costs,
            reservations=base.reservations,
            source_refs=base.source_refs,
        )

    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type="resource_profile_for_component",
            inputs={"component_key": stable_key, "level_or_stage": stage},
        ),
        status="unknown",
        facts={
            "level_or_stage": stage,
            "costs": {},
            "reservations": {},
        },
        source_refs=_source_refs_for_components(snapshot, (stable_key,)),
    )


def support_skill_candidate(
    *,
    snapshot: GraphSnapshot,
    support_key: str,
    skill_key: str,
) -> ComputedFactResult:
    """Evaluate source-backed support-vs-skill legality without promoting candidate tags."""

    return _support_skill_candidate_for_types(
        snapshot=snapshot,
        support_key=support_key,
        skill_key=skill_key,
        skill_types=_skill_types_for(snapshot, _required_text(skill_key, "skill key")),
    )


def support_skill_group_candidates(
    *,
    snapshot: GraphSnapshot,
    support_keys: tuple[str, ...] | list[str],
    skill_key: str,
) -> tuple[ComputedFactResult, ...]:
    """Evaluate one active skill's support group after the PoB skill-type fixed point."""

    normalized_skill_key = _required_text(skill_key, "skill key")
    normalized_support_keys = tuple(_required_text(value, "support key") for value in support_keys)
    if len(set(normalized_support_keys)) != len(normalized_support_keys):
        raise ValueError("support group must not contain duplicate support keys")

    skill_types = _skill_types_for(snapshot, normalized_skill_key)
    rejected: list[str] = []
    for normalized_support_key in normalized_support_keys:
        result = _support_skill_candidate_for_types(
            snapshot=snapshot,
            support_key=normalized_support_key,
            skill_key=normalized_skill_key,
            skill_types=skill_types,
        )
        if result.status == "known":
            skill_types.update(_added_skill_types_for_support(snapshot, normalized_support_key))
        else:
            rejected.append(normalized_support_key)

    while rejected:
        remaining: list[str] = []
        added_support = False
        for normalized_support_key in rejected:
            result = _support_skill_candidate_for_types(
                snapshot=snapshot,
                support_key=normalized_support_key,
                skill_key=normalized_skill_key,
                skill_types=skill_types,
            )
            if result.status == "known":
                skill_types.update(_added_skill_types_for_support(snapshot, normalized_support_key))
                added_support = True
            else:
                remaining.append(normalized_support_key)
        rejected = remaining
        if not added_support:
            break

    return tuple(
        _support_skill_candidate_for_types(
            snapshot=snapshot,
            support_key=normalized_support_key,
            skill_key=normalized_skill_key,
            skill_types=skill_types,
        )
        for normalized_support_key in normalized_support_keys
    )


def _support_skill_candidate_for_types(
    *,
    snapshot: GraphSnapshot,
    support_key: str,
    skill_key: str,
    skill_types: set[str],
) -> ComputedFactResult:
    """Evaluate a support against an already accumulated set of active-skill types."""

    normalized_support_key = _required_text(support_key, "support key")
    normalized_skill_key = _required_text(skill_key, "skill key")
    nodes_by_key = {node.stable_key: node for node in snapshot.nodes}
    support_node = nodes_by_key.get(normalized_support_key)
    if support_node is None:
        raise ValueError(f"missing support node: {normalized_support_key}")
    skill_node = nodes_by_key.get(normalized_skill_key)
    if skill_node is None:
        raise ValueError(f"missing skill node: {normalized_skill_key}")
    if support_node.node_type != "support_gem":
        raise ValueError(f"node is not a support gem: {normalized_support_key}")
    if skill_node.node_type != "active_skill":
        raise ValueError(f"node is not an active skill: {normalized_skill_key}")

    _, contract_requirements = _support_contract_for(snapshot, normalized_support_key)

    supports_gems_only = bool(contract_requirements.requirements.get("supports_gems_only", False))
    is_gem_granted = _is_skill_granted_by_gem(snapshot, normalized_skill_key)
    if supports_gems_only and not is_gem_granted:
        return _support_candidate_result(
            snapshot=snapshot,
            support_key=normalized_support_key,
            skill_key=normalized_skill_key,
            status="unsupported",
            candidate_status="unsupported",
            excluded_reason="supports_gems_only",
            matched_skill_types=(),
            shared_tags=_shared_component_tags(
                snapshot, normalized_support_key, normalized_skill_key
            ),
        )

    allowed_expr = _string_tuple(contract_requirements.requirements.get("allowed_types_expr"))
    excluded_expr = _string_tuple(contract_requirements.requirements.get("excluded_types_expr"))
    matched_skill_types = sorted(
        {
            token.casefold()
            for token in allowed_expr
            if token not in {"AND", "OR", "NOT"} and token.casefold() in skill_types
        }
    )
    excluded_match = bool(excluded_expr) and _type_expression_matches(excluded_expr, skill_types)
    if excluded_match:
        return _support_candidate_result(
            snapshot=snapshot,
            support_key=normalized_support_key,
            skill_key=normalized_skill_key,
            status="unsupported",
            candidate_status="unsupported",
            excluded_reason="excluded_types_matched",
            matched_skill_types=matched_skill_types,
            shared_tags=_shared_component_tags(
                snapshot, normalized_support_key, normalized_skill_key
            ),
        )

    required_match = not allowed_expr or _type_expression_matches(allowed_expr, skill_types)
    if not required_match:
        return _support_candidate_result(
            snapshot=snapshot,
            support_key=normalized_support_key,
            skill_key=normalized_skill_key,
            status="unsupported",
            candidate_status="unsupported",
            excluded_reason="required_types_not_matched",
            matched_skill_types=matched_skill_types,
            shared_tags=_shared_component_tags(
                snapshot, normalized_support_key, normalized_skill_key
            ),
        )

    recommended = any(
        edge.edge_type == "recommended_for"
        and edge.source_key == normalized_support_key
        and edge.target_key == _granted_by_skill(snapshot, normalized_skill_key)
        for edge in snapshot.edges
    )
    candidate_status = "recommended" if recommended else "hard_compatible"
    return _support_candidate_result(
        snapshot=snapshot,
        support_key=normalized_support_key,
        skill_key=normalized_skill_key,
        status="known",
        candidate_status=candidate_status,
        excluded_reason=None,
        matched_skill_types=matched_skill_types,
        shared_tags=_shared_component_tags(snapshot, normalized_support_key, normalized_skill_key),
    )


def socket_support_legality(
    *,
    snapshot: GraphSnapshot,
    skill_key: str,
    support_key: str,
    socket_context: dict[str, Any] | None = None,
) -> ComputedFactResult:
    """Evaluate a support in a concrete socket context using source-backed rules."""

    normalized_skill_key = _required_text(skill_key, "skill key")
    normalized_support_key = _required_text(support_key, "support key")
    candidate = support_skill_candidate(
        snapshot=snapshot,
        support_key=normalized_support_key,
        skill_key=normalized_skill_key,
    )
    if candidate.status == "unsupported":
        return _socket_support_result(
            snapshot=snapshot,
            skill_key=normalized_skill_key,
            support_key=normalized_support_key,
            status="unsupported",
            legality_status="unsupported",
            excluded_reasons=[
                str(candidate.facts.get("excluded_reason", "support_not_compatible"))
            ],
            context={},
            support_candidate_status=str(candidate.facts["candidate_status"]),
            support_family=None,
            source_refs=tuple(sorted(candidate.source_refs)),
        )

    socket_fact = _requirement_fact_for(
        snapshot,
        component_key=normalized_skill_key,
        level_or_stage="socket_context",
    )
    if socket_fact is None and socket_context is None:
        return _socket_support_result(
            snapshot=snapshot,
            skill_key=normalized_skill_key,
            support_key=normalized_support_key,
            status="unknown",
            legality_status="unknown",
            excluded_reasons=[],
            context={},
            support_candidate_status=str(candidate.facts["candidate_status"]),
            support_family=_support_family_for(snapshot, normalized_support_key),
            source_refs=_source_refs_for_components(
                snapshot, (normalized_skill_key, normalized_support_key)
            ),
            caveat="missing_socket_context",
        )

    context: dict[str, Any] = dict(socket_fact.requirements) if socket_fact is not None else {}
    if socket_context is not None:
        context.update(dict(socket_context))

    socketed_support_keys = list(
        _string_values(context.get("socketed_support_keys"), "socketed_support_keys")
    )
    socketed_support_families = list(
        _string_values(context.get("socketed_support_families"), "socketed_support_families")
    )
    max_support_count = _optional_int(context.get("max_support_count"))
    current_support_count = _optional_int(context.get("current_support_count"))
    if current_support_count is None:
        current_support_count = len(socketed_support_keys)
    duplicate_policy = str(context.get("duplicate_support_policy") or "reject_same_support_key")
    support_family = _support_family_for(snapshot, normalized_support_key)

    excluded_reasons: list[str] = []
    duplicate_support = (
        duplicate_policy == "reject_same_support_key"
        and normalized_support_key in socketed_support_keys
    )
    duplicate_family = (
        duplicate_policy == "reject_same_family"
        and support_family is not None
        and support_family in socketed_support_families
    )
    if duplicate_support or duplicate_family:
        excluded_reasons.append("duplicate_support")
    if not excluded_reasons and max_support_count is not None:
        if current_support_count >= max_support_count:
            excluded_reasons.append("support_limit_exceeded")

    status = "unsupported" if excluded_reasons else "known"
    legality_status = "unsupported" if excluded_reasons else "socket_compatible"
    source_refs = set(candidate.source_refs)
    if socket_fact is not None:
        source_refs.update(socket_fact.source_refs)
    else:
        source_refs.update(
            _source_refs_for_components(snapshot, (normalized_skill_key, normalized_support_key))
        )
    return _socket_support_result(
        snapshot=snapshot,
        skill_key=normalized_skill_key,
        support_key=normalized_support_key,
        status=status,
        legality_status=legality_status,
        excluded_reasons=excluded_reasons,
        context={
            "max_support_count": max_support_count,
            "current_support_count": current_support_count,
            "socketed_support_keys": socketed_support_keys,
            "socketed_support_families": socketed_support_families,
            "duplicate_support_policy": duplicate_policy,
        },
        support_candidate_status=str(candidate.facts["candidate_status"]),
        support_family=support_family,
        source_refs=tuple(sorted(source_refs)),
    )


def passive_neighbors(
    snapshot: GraphSnapshot,
    passive_key: str,
) -> ComputedFactResult:
    """Return connected passive neighbors and unresolved connection caveats."""

    stable_key = _required_text(passive_key, "passive key")
    node = next((item for item in snapshot.nodes if item.stable_key == stable_key), None)
    if node is None:
        raise ValueError(f"missing passive node: {stable_key}")
    if node.node_type not in {"passive", "notable", "keystone"}:
        raise ValueError(f"node is not a passive node: {stable_key}")

    neighbor_keys = sorted(
        _target_keys(snapshot.edges, source_key=stable_key, edge_type="connected_to")
    )
    caveat_fact = _requirement_fact_for(
        snapshot,
        component_key=stable_key,
        level_or_stage="connection_caveat",
    )
    unresolved_connection_ids: list[int] = []
    if caveat_fact is not None:
        unresolved_connection_ids = sorted(
            int(value)
            for value in list(caveat_fact.requirements.get("unresolved_connection_ids", []))
        )

    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type="passive_neighbors",
            inputs={"passive_key": stable_key},
        ),
        status="ambiguous" if unresolved_connection_ids else "known",
        facts={
            "passive_key": stable_key,
            "neighbor_keys": neighbor_keys,
            "unresolved_connection_ids": unresolved_connection_ids,
        },
        source_refs=_source_refs_for_components(snapshot, (stable_key,)),
        confidence=0.5 if unresolved_connection_ids else 1.0,
        caveat="unresolved_passive_connections" if unresolved_connection_ids else None,
    )


def passive_allocation_options(
    snapshot: GraphSnapshot,
    passive_key: str,
) -> ComputedFactResult:
    """Return source-backed passive choices and allocation options for one passive node."""

    stable_key = _required_text(passive_key, "passive key")
    node = next((item for item in snapshot.nodes if item.stable_key == stable_key), None)
    if node is None:
        raise ValueError(f"missing passive node: {stable_key}")
    if node.node_type not in {"passive", "notable", "keystone"}:
        raise ValueError(f"node is not a passive node: {stable_key}")

    choices = [
        choice for choice in snapshot.passive_choices if choice.parent_passive_key == stable_key
    ]
    if not choices:
        return ComputedFactResult(
            request=ComputedFactRequest(
                fact_type="passive_allocation_options",
                inputs={"passive_key": stable_key},
            ),
            status="unknown",
            facts={"passive_key": stable_key, "choice_keys": [], "options": []},
            source_refs=_source_refs_for_components(snapshot, (stable_key,)),
        )

    choice_keys = [choice.choice_key for choice in choices]
    options = [
        option for option in snapshot.allocation_options if option.choice_key in set(choice_keys)
    ]
    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type="passive_allocation_options",
            inputs={"passive_key": stable_key},
        ),
        status="known",
        facts={
            "passive_key": stable_key,
            "choice_keys": choice_keys,
            "options": [
                {
                    "option_key": option.option_key,
                    "choice_key": option.choice_key,
                    "display_name": option.display_name,
                    "stat_text": option.stat_text,
                    "allocation_states": list(option.allocation_states),
                    "caveat": option.caveat,
                }
                for option in sorted(options, key=lambda item: item.option_key)
            ],
        },
        source_refs=tuple(
            sorted(
                set(_source_refs_for_components(snapshot, (stable_key,)))
                | {ref for choice in choices for ref in choice.source_refs}
                | {ref for option in options for ref in option.source_refs}
            )
        ),
    )


def passive_allocation_overlay(
    snapshot: GraphSnapshot,
    passive_key: str,
) -> ComputedFactResult:
    """Return state caveats for passives that depend on weapon-set allocation overlays."""

    stable_key = _required_text(passive_key, "passive key")
    node = next((item for item in snapshot.nodes if item.stable_key == stable_key), None)
    if node is None:
        raise ValueError(f"missing passive node: {stable_key}")
    fact = _requirement_fact_for(
        snapshot,
        component_key=stable_key,
        level_or_stage="weapon_set_overlay",
    )
    if fact is None:
        return ComputedFactResult(
            request=ComputedFactRequest(
                fact_type="passive_allocation_overlay",
                inputs={"passive_key": stable_key},
            ),
            status="unknown",
            facts={
                "passive_key": stable_key,
                "allocation_states": ["normal"],
                "weapon_set_point_conversion": 0,
                "state_specific_reachability": False,
            },
            source_refs=_source_refs_for_components(snapshot, (stable_key,)),
        )

    allocation_states = [
        _required_text(str(state), "allocation state")
        for state in list(fact.requirements.get("allocation_states", []))
    ]
    state_specific_reachability = bool(fact.requirements.get("state_specific_reachability", False))
    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type="passive_allocation_overlay",
            inputs={"passive_key": stable_key},
        ),
        status=fact.status,
        facts={
            "passive_key": stable_key,
            "allocation_states": allocation_states or ["normal"],
            "documented_weapon_set_indices": list(
                fact.requirements.get("documented_weapon_set_indices", [])
            ),
            "weapon_set_point_conversion": int(
                fact.requirements.get("weapon_set_point_conversion", 0)
            ),
            "state_specific_reachability": state_specific_reachability,
        },
        source_refs=fact.source_refs,
        confidence=fact.confidence,
        caveat=(
            "dual_weapon_state_limited_caveat"
            if state_specific_reachability
            and any(state.startswith("weapon_set_") for state in allocation_states)
            else None
        ),
    )


def caveat_component_set(
    snapshot: GraphSnapshot,
    caveat_key: str,
) -> ComputedFactResult:
    """Return the deterministic component-set context behind one caveat node."""

    stable_key = _required_text(caveat_key, "caveat key")
    node = next((item for item in snapshot.nodes if item.stable_key == stable_key), None)
    if node is None:
        raise ValueError(f"missing caveat node: {stable_key}")
    fact = _requirement_fact_for(
        snapshot,
        component_key=stable_key,
        level_or_stage="component_set",
    )
    if fact is None:
        return ComputedFactResult(
            request=ComputedFactRequest(
                fact_type="caveat_component_set",
                inputs={"caveat_key": stable_key},
            ),
            status="unknown",
            facts={
                "caveat_key": stable_key,
                "component_keys": [],
                "trigger_condition": None,
                "modelability_effect": None,
                "reward_eligibility_effect": None,
            },
            source_refs=_source_refs_for_components(snapshot, (stable_key,)),
        )
    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type="caveat_component_set",
            inputs={"caveat_key": stable_key},
        ),
        status=fact.status,
        facts={
            "caveat_key": stable_key,
            "component_keys": list(fact.requirements.get("component_keys", [])),
            "trigger_condition": fact.requirements.get("trigger_condition"),
            "modelability_effect": fact.requirements.get("modelability_effect"),
            "reward_eligibility_effect": fact.requirements.get("reward_eligibility_effect"),
        },
        source_refs=fact.source_refs,
        confidence=fact.confidence,
    )


def save_snapshot(snapshot: GraphSnapshot, path: str | Path) -> None:
    """Persist a deterministic JSON snapshot for later reload."""

    payload = _snapshot_payload(snapshot)
    target = Path(path)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )


def load_snapshot(path: str | Path) -> GraphSnapshot:
    """Load a JSON snapshot produced by :func:`save_snapshot`.

    Gzip-compressed snapshots (``.json.gz`` or raw gzip magic) are transparently decompressed;
    plain JSON files keep working unchanged.
    """

    snapshot_path = Path(path)
    raw = snapshot_path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    payload = json.loads(raw.decode("utf-8"))
    return GraphSnapshot(
        snapshot_id=_required_text(str(payload["snapshot_id"]), "snapshot id"),
        created_at=datetime.fromisoformat(_required_text(payload["created_at"], "created_at")),
        sources=tuple(_graph_source_from_payload(item) for item in payload.get("sources", [])),
        nodes=tuple(_graph_node_from_payload(item) for item in payload.get("nodes", [])),
        edges=tuple(_graph_edge_from_payload(item) for item in payload.get("edges", [])),
        aliases=tuple(_graph_alias_from_payload(item) for item in payload.get("aliases", [])),
        id_mappings=tuple(
            _graph_id_mapping_from_payload(item) for item in payload.get("id_mappings", [])
        ),
        capabilities=tuple(
            _graph_capability_from_payload(item) for item in payload.get("capabilities", [])
        ),
        requirement_facts=tuple(
            _requirement_fact_from_payload(item) for item in payload.get("requirement_facts", [])
        ),
        resource_facts=tuple(
            _resource_fact_from_payload(item) for item in payload.get("resource_facts", [])
        ),
        passive_choices=tuple(
            _passive_choice_from_payload(item) for item in payload.get("passive_choices", [])
        ),
        allocation_options=tuple(
            _allocation_option_from_payload(item) for item in payload.get("allocation_options", [])
        ),
        computed_results=tuple(
            _computed_result_from_payload(item) for item in payload.get("computed_results", [])
        ),
    )


def resolve_node(snapshot: GraphSnapshot, query: str) -> str:
    """Resolve a stable key, alias, display name, or external id to one node key."""

    result = resolve_candidates(snapshot, query)
    if result["status"] == "resolved":
        return str(result["resolved_key"])
    if result["status"] == "ambiguous":
        raise ValueError(f"ambiguous node resolution: {query}")
    raise ValueError(f"missing node resolution: {query}")


def resolve_candidates(snapshot: GraphSnapshot, query: str) -> dict[str, Any]:
    """Return deterministic resolver candidates without auto-guessing."""

    text = _required_text(query, "resolve query")
    node_keys = {node.stable_key for node in snapshot.nodes}
    if text in node_keys:
        return {"status": "resolved", "resolved_key": text, "candidate_keys": [text]}

    mapping_matches = sorted(
        {
            mapping.target_key
            for mapping in snapshot.id_mappings
            if mapping.external_id == text
            and mapping.target_key is not None
            and mapping.status == "resolved"
        }
    )
    if len(mapping_matches) == 1:
        return {
            "status": "resolved",
            "resolved_key": mapping_matches[0],
            "candidate_keys": mapping_matches,
        }
    if len(mapping_matches) > 1:
        return {"status": "ambiguous", "resolved_key": None, "candidate_keys": mapping_matches}

    normalized = " ".join(text.casefold().split())
    alias_matches = sorted(
        {alias.target_key for alias in snapshot.aliases if alias.normalized_alias == normalized}
    )
    if len(alias_matches) == 1:
        return {
            "status": "resolved",
            "resolved_key": alias_matches[0],
            "candidate_keys": alias_matches,
        }
    if len(alias_matches) > 1:
        return {"status": "ambiguous", "resolved_key": None, "candidate_keys": alias_matches}

    display_matches = sorted(
        {
            node.stable_key
            for node in snapshot.nodes
            if " ".join(node.display_name.casefold().split()) == normalized
        }
    )
    if len(display_matches) == 1:
        return {
            "status": "resolved",
            "resolved_key": display_matches[0],
            "candidate_keys": display_matches,
        }
    if len(display_matches) > 1:
        return {"status": "ambiguous", "resolved_key": None, "candidate_keys": display_matches}
    return {"status": "missing", "resolved_key": None, "candidate_keys": []}


def search_candidates(
    snapshot: GraphSnapshot,
    query: str,
    *,
    expected_node_types: tuple[str, ...] = (),
    allowed_keys: frozenset[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return bounded lexical discovery candidates without authorizing an endpoint."""

    text = _required_text(query, "component search query")
    normalized = " ".join(text.casefold().split())
    expected = {str(value).strip() for value in expected_node_types if str(value).strip()}
    nodes_by_key = {node.stable_key: node for node in snapshot.nodes}
    aliases_by_key: dict[str, set[str]] = {}
    for alias in snapshot.aliases:
        aliases_by_key.setdefault(alias.target_key, set()).add(alias.normalized_alias)

    ranked: list[tuple[int, str]] = []
    for node in snapshot.nodes:
        if (
            allowed_keys is not None
            and node.node_type == "active_skill"
            and node.stable_key not in allowed_keys
        ):
            continue
        if expected and node.node_type not in expected:
            continue
        names = {
            " ".join(node.display_name.casefold().split()),
            *aliases_by_key.get(node.stable_key, set()),
        }
        if normalized in names:
            rank = 0
        elif any(name.startswith(normalized) for name in names):
            rank = 1
        elif any(normalized in name for name in names):
            rank = 2
        else:
            query_tokens = {token for token in normalized.split() if token}
            if not query_tokens or not any(query_tokens <= set(name.split()) for name in names):
                continue
            rank = 3
        ranked.append((rank, node.stable_key))

    candidate_keys = [key for _, key in sorted(ranked, key=lambda item: (item[0], item[1]))[:limit]]
    return {
        "status": "found" if candidate_keys else "missing",
        "candidate_keys": candidate_keys,
        "expected_node_types": sorted(expected),
        "truncated": len(ranked) > limit,
        "matched_node_types": sorted({nodes_by_key[key].node_type for key in candidate_keys}),
    }


def resolve_id_mapping(
    snapshot: GraphSnapshot,
    system: str,
    external_id: str,
) -> dict[str, Any]:
    """Resolve one explicit id-mapping query without guessing across systems."""

    mapping_system = _required_text(system, "mapping system")
    mapping_external_id = _required_text(external_id, "external id")
    matches = [
        mapping
        for mapping in snapshot.id_mappings
        if mapping.system == mapping_system and mapping.external_id == mapping_external_id
    ]
    if not matches:
        return {
            "status": "missing",
            "system": mapping_system,
            "external_id": mapping_external_id,
            "target_key": None,
            "caveat": None,
        }
    if len(matches) > 1:
        resolved_targets = sorted(
            {
                mapping.target_key
                for mapping in matches
                if mapping.target_key is not None and mapping.status == "resolved"
            }
        )
        return {
            "status": "ambiguous",
            "system": mapping_system,
            "external_id": mapping_external_id,
            "target_key": None,
            "candidate_keys": resolved_targets,
            "caveat": None,
        }
    match = matches[0]
    return {
        "status": match.status,
        "system": match.system,
        "external_id": match.external_id,
        "target_key": match.target_key,
        "caveat": match.caveat,
    }


def alias_collision_report(snapshot: GraphSnapshot) -> list[dict[str, Any]]:
    """Report aliases that normalize to multiple target keys."""

    candidates: dict[str, set[str]] = {}
    for alias in snapshot.aliases:
        candidates.setdefault(alias.normalized_alias, set()).add(alias.target_key)
    return [
        {
            "normalized_alias": normalized_alias,
            "candidate_keys": sorted(target_keys),
        }
        for normalized_alias, target_keys in sorted(candidates.items())
        if len(target_keys) > 1
    ]


def build_component_resolver_payload(snapshot: GraphSnapshot, node_key: str) -> dict[str, Any]:
    """Return a build-facing resolver payload for export-capable components."""

    stable_key = _required_text(node_key, "node key")
    node = next((item for item in snapshot.nodes if item.stable_key == stable_key), None)
    if node is None:
        raise ValueError(f"missing node for resolver payload: {stable_key}")

    if node.node_type not in {"skill_gem", "support_gem"}:
        return {
            "status": "unsupported",
            "node_key": stable_key,
            "component_type": node.node_type,
            "reason": "node_type_not_export_ready",
            "export_status": "unsupported",
            "caveats": ["node_type_not_export_ready"],
        }
    if any(
        edge.edge_type == "has_tag"
        and edge.source_key == stable_key
        and edge.target_key == "tag:gem:meta"
        for edge in snapshot.edges
    ):
        return {
            "status": "unsupported",
            "node_key": stable_key,
            "component_type": node.node_type,
            "reason": "meta_gem_not_supported",
            "export_status": "unsupported",
            "caveats": ["meta_gem_not_supported"],
        }

    metadata_id = next(
        (
            mapping.external_id
            for mapping in snapshot.id_mappings
            if mapping.target_key == stable_key
            and mapping.system == "repoe:gem_metadata"
            and mapping.status == "resolved"
        ),
        None,
    )
    if metadata_id is None:
        return {
            "status": "missing",
            "node_key": stable_key,
            "component_type": node.node_type,
            "reason": "metadata_id_not_mapped",
            "export_status": "missing",
            "caveats": ["metadata_id_not_mapped"],
        }

    return {
        "status": "resolved",
        "node_key": stable_key,
        "component_type": node.node_type,
        "display_name": node.display_name,
        "metadata_id": metadata_id,
        "source_refs": list(node.source_refs),
        "export_status": "exportable",
        "caveats": [],
    }


def build_component_resolver_export(
    snapshot: GraphSnapshot,
    node_keys: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Build a flat export-readiness report for multiple component nodes."""

    entries: list[dict[str, Any]] = []
    resolved_count = 0
    unsupported_count = 0
    missing_count = 0
    known_keys = {node.stable_key for node in snapshot.nodes}

    for node_key in node_keys:
        stable_key = _required_text(str(node_key), "node key")
        if stable_key not in known_keys:
            entries.append({"status": "missing", "node_key": stable_key})
            missing_count += 1
            continue
        payload = build_component_resolver_payload(snapshot, stable_key)
        entries.append(payload)
        if payload["status"] == "resolved":
            resolved_count += 1
        elif payload["status"] == "unsupported":
            unsupported_count += 1
        else:
            missing_count += 1

    return {
        "resolved_count": resolved_count,
        "unsupported_count": unsupported_count,
        "missing_count": missing_count,
        "entries": entries,
    }


def build_resolver_preflight_summary(
    snapshot: GraphSnapshot,
    node_keys: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Build a compact resolver readiness summary for later export/report steps."""

    export_report = build_component_resolver_export(snapshot, node_keys)
    collisions = alias_collision_report(snapshot)
    return {
        "resolved_count": export_report["resolved_count"],
        "unsupported_count": export_report["unsupported_count"],
        "missing_count": export_report["missing_count"],
        "alias_collision_count": len(collisions),
        "ready_for_export": (
            export_report["unsupported_count"] == 0
            and export_report["missing_count"] == 0
            and len(collisions) == 0
        ),
        "export_report": export_report,
        "alias_collisions": collisions,
    }


def build_fixed_resolver_e2e_report(
    snapshot: GraphSnapshot,
    node_keys: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Build a small fixed-sample resolver report as the start of Phase 2 E2E coverage."""

    export_report = build_component_resolver_export(snapshot, node_keys)
    samples = [{"query": entry["node_key"], "result": entry} for entry in export_report["entries"]]
    return {
        "sample_count": len(samples),
        "samples": samples,
        "summary": {
            "resolved_count": export_report["resolved_count"],
            "unsupported_count": export_report["unsupported_count"],
            "missing_count": export_report["missing_count"],
        },
    }


def build_can_roll_mod_e2e_sample(
    *,
    snapshot: GraphSnapshot,
    base_item_key: str,
    mod_key: str,
    item_level: int,
) -> dict[str, Any]:
    """Build one fixed-sample computed-fact report entry for can_roll_mod."""

    result = can_roll_mod(
        snapshot=snapshot,
        base_item_key=base_item_key,
        mod_key=mod_key,
        item_level=item_level,
    )
    return {
        "query": {
            "fact_type": "can_roll_mod",
            "base_item_key": base_item_key,
            "mod_key": mod_key,
            "item_level": item_level,
        },
        "result": {
            "status": result.status,
            "facts": result.facts,
            "source_refs": list(result.source_refs),
            "caveat": result.caveat,
        },
    }


def build_requirements_for_component_e2e_sample(
    *,
    snapshot: GraphSnapshot,
    component_key: str,
    level_or_stage: str,
) -> dict[str, Any]:
    """Build one fixed-sample computed-fact report entry for requirements_for_component."""

    result = requirements_for_component(
        snapshot,
        component_key,
        level_or_stage=level_or_stage,
    )
    return {
        "query": {
            "fact_type": "requirements_for_component",
            "component_key": component_key,
            "level_or_stage": level_or_stage,
        },
        "result": {
            "status": result.status,
            "facts": result.facts,
            "source_refs": list(result.source_refs),
            "caveat": result.caveat,
        },
    }


def build_resource_profile_for_component_e2e_sample(
    *,
    snapshot: GraphSnapshot,
    component_key: str,
    level_or_stage: str,
) -> dict[str, Any]:
    """Build one fixed-sample computed-fact report entry for resource_profile_for_component."""

    result = resource_profile_for_component(
        snapshot,
        component_key,
        level_or_stage=level_or_stage,
    )
    return {
        "query": {
            "fact_type": "resource_profile_for_component",
            "component_key": component_key,
            "level_or_stage": level_or_stage,
        },
        "result": {
            "status": result.status,
            "facts": result.facts,
            "source_refs": list(result.source_refs),
            "caveat": result.caveat,
        },
    }


def build_support_skill_candidate_e2e_sample(
    *,
    snapshot: GraphSnapshot,
    support_key: str,
    skill_key: str,
) -> dict[str, Any]:
    """Build one fixed-sample computed-fact report entry for support_skill_candidate."""

    result = support_skill_candidate(
        snapshot=snapshot,
        support_key=support_key,
        skill_key=skill_key,
    )
    return {
        "query": {
            "fact_type": "support_skill_candidate",
            "support_key": support_key,
            "skill_key": skill_key,
        },
        "result": {
            "status": result.status,
            "facts": result.facts,
            "source_refs": list(result.source_refs),
            "caveat": result.caveat,
        },
    }


def build_socket_support_legality_e2e_sample(
    *,
    snapshot: GraphSnapshot,
    skill_key: str,
    support_key: str,
    socket_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one fixed-sample report entry for socket/support hard constraints."""

    result = socket_support_legality(
        snapshot=snapshot,
        skill_key=skill_key,
        support_key=support_key,
        socket_context=socket_context,
    )
    return {
        "query": {
            "fact_type": "socket_support_legality",
            "skill_key": skill_key,
            "support_key": support_key,
            "socket_context": dict(socket_context or {}),
        },
        "result": {
            "status": result.status,
            "facts": result.facts,
            "source_refs": list(result.source_refs),
            "caveat": result.caveat,
        },
    }


def build_passive_neighbors_e2e_sample(
    *,
    snapshot: GraphSnapshot,
    passive_key: str,
) -> dict[str, Any]:
    """Build one fixed-sample computed-fact report entry for passive_neighbors."""

    result = passive_neighbors(snapshot, passive_key)
    return {
        "query": {
            "fact_type": "passive_neighbors",
            "passive_key": passive_key,
        },
        "result": {
            "status": result.status,
            "facts": result.facts,
            "source_refs": list(result.source_refs),
            "caveat": result.caveat,
        },
    }


def build_unique_base_item_e2e_sample(
    *,
    snapshot: GraphSnapshot,
    unique_key: str,
) -> dict[str, Any]:
    """Build one fixed-sample computed-fact report entry for unique_base_item."""

    result = unique_base_item(snapshot, unique_key)
    return {
        "query": {
            "fact_type": "unique_base_item",
            "unique_key": unique_key,
        },
        "result": {
            "status": result.status,
            "facts": result.facts,
            "source_refs": list(result.source_refs),
            "caveat": result.caveat,
        },
    }


def build_id_mapping_e2e_sample(
    *,
    snapshot: GraphSnapshot,
    system: str,
    external_id: str,
) -> dict[str, Any]:
    """Build one fixed-sample resolver report entry for an explicit id mapping."""

    result = resolve_id_mapping(snapshot, system, external_id)
    return {
        "query": {
            "fact_type": "resolve_id_mapping",
            "system": system,
            "external_id": external_id,
        },
        "result": result,
    }


def build_edge_provenance_e2e_sample(
    *,
    snapshot: GraphSnapshot,
    edge_type: str,
    source_key: str,
    target_key: str,
) -> dict[str, Any]:
    """Build one fixed-sample provenance report entry for a physical edge."""

    result = explain_edge_sources(
        snapshot,
        edge_type=edge_type,
        source_key=source_key,
        target_key=target_key,
    )
    return {
        "query": {
            "fact_type": "edge_provenance",
            "edge_type": edge_type,
            "source_key": source_key,
            "target_key": target_key,
        },
        "result": result,
    }


def build_phase2_mini_e2e_report(
    *,
    resolver_snapshot: GraphSnapshot,
    resolver_node_keys: list[str] | tuple[str, ...],
    compute_snapshot: GraphSnapshot,
    requirement_snapshot: GraphSnapshot | None = None,
    can_roll_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    requirement_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    resource_snapshot: GraphSnapshot | None = None,
    resource_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    support_candidate_snapshot: GraphSnapshot | None = None,
    support_candidate_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    passive_snapshot: GraphSnapshot | None = None,
    passive_neighbor_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Aggregate a small cross-family E2E report while Phase 2 coverage is still growing."""

    resolver_report = build_fixed_resolver_e2e_report(resolver_snapshot, resolver_node_keys)
    resolver_preflight = build_resolver_preflight_summary(
        resolver_snapshot,
        resolver_node_keys,
    )
    resolver_samples = [{"family": "resolver", **sample} for sample in resolver_report["samples"]]
    can_roll_samples = [
        {
            "family": "can_roll_mod",
            **build_can_roll_mod_e2e_sample(
                snapshot=compute_snapshot,
                base_item_key=str(spec["base_item_key"]),
                mod_key=str(spec["mod_key"]),
                item_level=int(spec["item_level"]),
            ),
        }
        for spec in can_roll_specs
    ]
    requirement_snapshot = requirement_snapshot or compute_snapshot
    requirement_samples = [
        {
            "family": "requirements_for_component",
            **build_requirements_for_component_e2e_sample(
                snapshot=requirement_snapshot,
                component_key=str(spec["component_key"]),
                level_or_stage=str(spec["level_or_stage"]),
            ),
        }
        for spec in requirement_specs
    ]
    resource_snapshot = resource_snapshot or requirement_snapshot or compute_snapshot
    resource_samples = [
        {
            "family": "resource_profile_for_component",
            **build_resource_profile_for_component_e2e_sample(
                snapshot=resource_snapshot,
                component_key=str(spec["component_key"]),
                level_or_stage=str(spec["level_or_stage"]),
            ),
        }
        for spec in resource_specs
    ]
    support_candidate_snapshot = support_candidate_snapshot or compute_snapshot
    support_candidate_samples = [
        {
            "family": "support_skill_candidate",
            **build_support_skill_candidate_e2e_sample(
                snapshot=support_candidate_snapshot,
                support_key=str(spec["support_key"]),
                skill_key=str(spec["skill_key"]),
            ),
        }
        for spec in support_candidate_specs
    ]
    passive_snapshot = passive_snapshot or compute_snapshot
    passive_neighbor_samples = [
        {
            "family": "passive_neighbors",
            **build_passive_neighbors_e2e_sample(
                snapshot=passive_snapshot,
                passive_key=str(spec["passive_key"]),
            ),
        }
        for spec in passive_neighbor_specs
    ]
    samples = (
        resolver_samples
        + can_roll_samples
        + requirement_samples
        + resource_samples
        + support_candidate_samples
        + passive_neighbor_samples
    )
    return {
        "sample_count": len(samples),
        "family_counts": {
            "resolver": len(resolver_samples),
            "can_roll_mod": len(can_roll_samples),
            "requirements_for_component": len(requirement_samples),
            "resource_profile_for_component": len(resource_samples),
            "support_skill_candidate": len(support_candidate_samples),
            "passive_neighbors": len(passive_neighbor_samples),
        },
        "resolver_preflight": resolver_preflight,
        "samples": samples,
    }


def build_phase2_fixed_sample_bundle(
    *,
    snapshot: GraphSnapshot,
    gem_key: str,
    skill_key: str,
    support_key: str,
    passive_key: str,
    unique_key: str,
    caveat_key: str,
) -> dict[str, Any]:
    """Build a richer fixed-sample bundle toward the final Phase 2 acceptance pack."""

    gem_grants_skill = [
        edge.target_key
        for edge in snapshot.edges
        if edge.edge_type == "grants_skill" and edge.source_key == gem_key
    ]
    weapon_requirements = [
        edge.target_key
        for edge in snapshot.edges
        if edge.edge_type == "requires_weapon_type" and edge.source_key == skill_key
    ]
    passive_choice_sample = passive_allocation_options(snapshot, passive_key)
    passive_overlay_sample = passive_allocation_overlay(snapshot, passive_key)
    caveat_sample = caveat_component_set(snapshot, caveat_key)
    can_roll_sample = _phase2_can_roll_sample(snapshot)
    requirement_sample = _phase2_requirement_sample(snapshot, gem_key)
    resource_sample = _phase2_resource_sample(snapshot, skill_key)

    samples = [
        {
            "family": "gem_grants_skill",
            "query": {"gem_key": gem_key},
            "result": {
                "status": "known" if gem_grants_skill else "unknown",
                "facts": {"skill_keys": gem_grants_skill},
                "source_refs": list(_source_refs_for_components(snapshot, (gem_key,))),
                "caveat": None,
            },
        },
        {
            "family": "skill_weapon_requirement",
            "query": {"skill_key": skill_key},
            "result": {
                "status": "known" if weapon_requirements else "unknown",
                "facts": {"weapon_type_keys": weapon_requirements},
                "source_refs": list(_source_refs_for_components(snapshot, (skill_key,))),
                "caveat": None,
            },
        },
        {
            "family": "support_skill_candidate",
            **build_support_skill_candidate_e2e_sample(
                snapshot=snapshot,
                support_key=support_key,
                skill_key=skill_key,
            ),
        },
        {
            "family": "socket_support_legality",
            **build_socket_support_legality_e2e_sample(
                snapshot=snapshot,
                support_key=support_key,
                skill_key=skill_key,
            ),
        },
        {
            "family": "can_roll_mod",
            **can_roll_sample,
        },
        {
            "family": "requirements_for_component",
            **requirement_sample,
        },
        {
            "family": "resource_profile_for_component",
            **resource_sample,
        },
        {
            "family": "unique_base_item",
            **build_unique_base_item_e2e_sample(snapshot=snapshot, unique_key=unique_key),
        },
        {
            "family": "passive_allocation_options",
            "query": {"passive_key": passive_key},
            "result": {
                "status": passive_choice_sample.status,
                "facts": passive_choice_sample.facts,
                "source_refs": list(passive_choice_sample.source_refs),
                "caveat": passive_choice_sample.caveat,
            },
        },
        {
            "family": "passive_allocation_overlay",
            "query": {"passive_key": passive_key},
            "result": {
                "status": passive_overlay_sample.status,
                "facts": passive_overlay_sample.facts,
                "source_refs": list(passive_overlay_sample.source_refs),
                "caveat": passive_overlay_sample.caveat,
            },
        },
        {
            "family": "caveat_component_set",
            "query": {"caveat_key": caveat_key},
            "result": {
                "status": caveat_sample.status,
                "facts": caveat_sample.facts,
                "source_refs": list(caveat_sample.source_refs),
                "caveat": caveat_sample.caveat,
            },
        },
        {
            "family": "resolver_ambiguous_alias",
            "query": {"query": "Lightning Arrow"},
            "result": {
                "status": resolve_candidates(snapshot, "Lightning Arrow")["status"],
                "facts": resolve_candidates(snapshot, "Lightning Arrow"),
                "source_refs": list(_source_refs_for_components(snapshot, (gem_key, skill_key))),
                "caveat": "ambiguous_alias",
            },
        },
        {
            "family": "resolver_missing_node",
            "query": {"query": "Missing Node"},
            "result": {
                "status": resolve_candidates(snapshot, "Missing Node")["status"],
                "facts": resolve_candidates(snapshot, "Missing Node"),
                "source_refs": [],
                "caveat": None,
            },
        },
        {
            "family": "build_resolver_skill_support",
            "query": {"node_key": support_key},
            "result": build_component_resolver_payload(snapshot, support_key),
        },
        {
            "family": "id_mapping_supported",
            **build_id_mapping_e2e_sample(
                snapshot=snapshot,
                system="pob:passive_skill_node_id",
                external_id="32183",
            ),
        },
        {
            "family": "id_mapping_unsupported",
            **build_id_mapping_e2e_sample(
                snapshot=snapshot,
                system="ggg:PassiveSkills",
                external_id="strength89",
            ),
        },
        {
            "family": "inventory_slot_mapping",
            **build_id_mapping_e2e_sample(
                snapshot=snapshot,
                system="ggg:Inventories",
                external_id="Weapon1",
            ),
        },
        {
            "family": "unique_name_mapping",
            **build_id_mapping_e2e_sample(
                snapshot=snapshot,
                system="ggg:Words:UniqueName",
                external_id="The Anvil",
            ),
        },
        {
            "family": "edge_provenance",
            **_phase2_passive_connected_to_sample(snapshot, passive_key),
        },
    ]
    family_counts: dict[str, int] = {}
    for sample in samples:
        family = str(sample["family"])
        family_counts[family] = family_counts.get(family, 0) + 1
    return {
        "sample_count": len(samples),
        "family_counts": dict(sorted(family_counts.items())),
        "samples": samples,
    }


def build_phase2_fixed_acceptance_report(
    samples: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Summarize fixed E2E samples into a human-review-friendly acceptance report."""

    normalized_samples = [dict(sample) for sample in samples]
    family_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    review_counts: dict[str, int] = {}
    fail_reasons: set[str] = set()
    families: dict[str, dict[str, Any]] = {}

    for sample in normalized_samples:
        family = _required_text(str(sample["family"]), "sample family")
        result = sample.get("result")
        if not isinstance(result, dict):
            raise ValueError("sample result must be an object")
        status = _required_text(str(result["status"]), "sample status")
        family_counts[family] = family_counts.get(family, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1

        family_bucket = families.setdefault(
            family,
            {
                "count": 0,
                "statuses": {},
                "caveats": set(),
            },
        )
        family_bucket["count"] += 1
        family_bucket["statuses"][status] = family_bucket["statuses"].get(status, 0) + 1
        caveat = result.get("caveat")
        if isinstance(caveat, str) and caveat.strip():
            family_bucket["caveats"].add(caveat.strip())

        review = sample.get("review")
        if isinstance(review, dict) and review.get("grade") is not None:
            grade = _required_text(str(review["grade"]), "review grade")
            review_counts[grade] = review_counts.get(grade, 0) + 1
            reasons = review.get("reasons")
            if isinstance(reasons, list):
                for reason in reasons:
                    fail_reasons.add(_required_text(str(reason), "review reason"))

    return {
        "sample_count": len(normalized_samples),
        "family_counts": dict(sorted(family_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "review_counts": dict(sorted(review_counts.items())),
        "fail_reasons": sorted(fail_reasons),
        "families": {
            family: {
                "count": bucket["count"],
                "statuses": dict(sorted(bucket["statuses"].items())),
                "caveats": sorted(bucket["caveats"]),
            }
            for family, bucket in sorted(families.items())
        },
        "ready_for_human_review": review_counts.get("fail", 0) == 0,
        "ready_for_phase2_exit": (
            len(normalized_samples) > 0
            and review_counts.get("fail", 0) == 0
            and review_counts.get("minor_issue", 0) == 0
            and review_counts.get("pass", 0) == len(normalized_samples)
        ),
        "samples": normalized_samples,
    }


def build_phase2_acceptance_artifact(
    *,
    snapshot: GraphSnapshot,
    gem_key: str,
    skill_key: str,
    support_key: str,
    passive_key: str,
    unique_key: str,
    caveat_key: str,
    default_review_grade: str | None = None,
) -> dict[str, Any]:
    """Build the current Phase 2 acceptance artifact from bundle plus report."""

    bundle = build_phase2_fixed_sample_bundle(
        snapshot=snapshot,
        gem_key=gem_key,
        skill_key=skill_key,
        support_key=support_key,
        passive_key=passive_key,
        unique_key=unique_key,
        caveat_key=caveat_key,
    )
    samples = list(bundle["samples"])
    if default_review_grade is not None:
        grade = _required_text(default_review_grade, "default review grade")
        samples = [
            {**sample, "review": {"grade": grade}} if sample.get("review") is None else dict(sample)
            for sample in samples
        ]
    acceptance_report = build_phase2_fixed_acceptance_report(samples)
    return {
        "bundle": bundle,
        "acceptance_report": acceptance_report,
    }


def explain_sources(snapshot: GraphSnapshot, node_key: str) -> list[dict[str, Any]]:
    """Explain which sources back a given node key."""

    stable_key = _required_text(node_key, "node key")
    node = next((item for item in snapshot.nodes if item.stable_key == stable_key), None)
    if node is None:
        raise ValueError(f"missing node for source explain: {stable_key}")
    sources_by_id = {source.source_id: source for source in snapshot.sources}
    explained: list[dict[str, Any]] = []
    for source_id in node.source_refs:
        source = sources_by_id[source_id]
        explained.append(
            {
                "source_id": source.source_id,
                "kind": source.kind,
                "source_file": source.source_file,
                "claims": {claim.key: claim.value for claim in source.claims},
                "schema_version": source.schema_version,
                "source_url": source.source_url,
            }
        )
    return explained


def explain_edge_sources(
    snapshot: GraphSnapshot,
    *,
    edge_type: str,
    source_key: str,
    target_key: str,
) -> dict[str, Any]:
    """Explain which sources back one specific physical graph edge."""

    normalized_edge_type = _required_text(edge_type, "edge type")
    normalized_source_key = _required_text(source_key, "source key")
    normalized_target_key = _required_text(target_key, "target key")
    edge = next(
        (
            item
            for item in snapshot.edges
            if item.edge_type == normalized_edge_type
            and item.source_key == normalized_source_key
            and item.target_key == normalized_target_key
        ),
        None,
    )
    if edge is None:
        return {
            "status": "missing",
            "edge_type": normalized_edge_type,
            "source_key": normalized_source_key,
            "target_key": normalized_target_key,
            "evidence": [],
        }
    sources_by_id = {source.source_id: source for source in snapshot.sources}
    evidence = []
    for source_id in edge.evidence_refs:
        source = sources_by_id[source_id]
        evidence.append(
            {
                "source_id": source.source_id,
                "kind": source.kind,
                "source_file": source.source_file,
                "claims": {claim.key: claim.value for claim in source.claims},
                "schema_version": source.schema_version,
                "source_url": source.source_url,
            }
        )
    return {
        "status": "known",
        "edge_type": normalized_edge_type,
        "source_key": normalized_source_key,
        "target_key": normalized_target_key,
        "evidence": evidence,
    }


def register_snapshot(
    index_path: str | Path, snapshot: GraphSnapshot, snapshot_path: str | Path
) -> None:
    """Register one persisted JSON snapshot inside a SQLite snapshot index."""

    db_path = Path(index_path)
    json_path = str(Path(snapshot_path).resolve())
    with sqlite3.connect(db_path) as conn:
        _ensure_snapshot_index_schema(conn)
        conn.execute("UPDATE snapshot_index SET is_latest = 0")
        conn.execute(
            """
            INSERT INTO snapshot_index (
                snapshot_id,
                created_at,
                snapshot_path,
                node_count,
                edge_count,
                source_count,
                is_latest
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(snapshot_id) DO UPDATE SET
                created_at = excluded.created_at,
                snapshot_path = excluded.snapshot_path,
                node_count = excluded.node_count,
                edge_count = excluded.edge_count,
                source_count = excluded.source_count,
                is_latest = 1
            """,
            (
                snapshot.snapshot_id,
                snapshot.created_at.isoformat(),
                json_path,
                len(snapshot.nodes),
                len(snapshot.edges),
                len(snapshot.sources),
            ),
        )
        conn.commit()


def list_registered_snapshots(index_path: str | Path) -> list[dict[str, Any]]:
    """List registered snapshots from newest to oldest."""

    db_path = Path(index_path)
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        _ensure_snapshot_index_schema(conn)
        rows = conn.execute(
            """
            SELECT snapshot_id, created_at, snapshot_path, node_count, edge_count, source_count, is_latest
            FROM snapshot_index
            ORDER BY is_latest DESC, created_at DESC, snapshot_id DESC
            """
        ).fetchall()
    return [
        {
            "snapshot_id": row[0],
            "created_at": row[1],
            "snapshot_path": row[2],
            "node_count": row[3],
            "edge_count": row[4],
            "source_count": row[5],
            "is_latest": bool(row[6]),
        }
        for row in rows
    ]


def load_latest_snapshot(index_path: str | Path) -> GraphSnapshot:
    """Load the latest registered snapshot from the SQLite index."""

    rows = list_registered_snapshots(index_path)
    if not rows:
        raise ValueError("missing latest snapshot")
    latest = next((row for row in rows if row["is_latest"]), rows[0])
    return load_snapshot(latest["snapshot_path"])


@dataclass(frozen=True, slots=True)
class GraphNode:
    """A physical graph node backed by at least one static source."""

    stable_key: str
    node_type: str
    display_name: str
    source_refs: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    status: str = "valid"
    confidence: float = 1.0
    official_ids: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        stable_key = _required_text(self.stable_key, "stable key")
        if ":" not in stable_key or stable_key.startswith(":") or stable_key.endswith(":"):
            raise ValueError("graph node stable key must be namespaced")
        object.__setattr__(self, "stable_key", stable_key)
        object.__setattr__(self, "node_type", _required_text(self.node_type, "node type"))
        object.__setattr__(self, "display_name", _required_text(self.display_name, "display name"))
        object.__setattr__(self, "source_refs", _required_tuple(self.source_refs, "source refs"))
        object.__setattr__(
            self,
            "aliases",
            tuple(_required_text(alias, "alias") for alias in self.aliases),
        )
        object.__setattr__(self, "status", _required_text(self.status, "node status"))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        official_ids = {
            _required_text(key, "official id kind"): _required_text(value, "official id")
            for key, value in dict(self.official_ids).items()
        }
        object.__setattr__(self, "official_ids", official_ids)

    @property
    def namespace(self) -> str:
        return self.stable_key.split(":", 1)[0]


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """A source-backed physical graph edge between existing nodes."""

    edge_type: str
    source_key: str
    target_key: str
    evidence_refs: tuple[str, ...]
    status: str = "valid"
    confidence: float = 1.0
    modelability: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_type", _required_text(self.edge_type, "edge type"))
        object.__setattr__(self, "source_key", _required_text(self.source_key, "source node"))
        object.__setattr__(self, "target_key", _required_text(self.target_key, "target node"))
        object.__setattr__(
            self,
            "evidence_refs",
            _required_tuple(self.evidence_refs, "edge evidence refs"),
        )
        object.__setattr__(self, "status", _required_text(self.status, "edge status"))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if self.modelability is not None:
            object.__setattr__(
                self,
                "modelability",
                _required_text(self.modelability, "modelability"),
            )


@dataclass(frozen=True, slots=True)
class GraphAlias:
    """Alias pointing at a source-backed graph node."""

    alias: str
    target_key: str
    source_refs: tuple[str, ...]
    status: str = "valid"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "alias", _required_text(self.alias, "alias"))
        object.__setattr__(self, "target_key", _required_text(self.target_key, "alias target"))
        object.__setattr__(
            self,
            "source_refs",
            _required_tuple(self.source_refs, "alias source refs"),
        )
        object.__setattr__(self, "status", _required_text(self.status, "alias status"))
        object.__setattr__(self, "confidence", _confidence(self.confidence))

    @property
    def normalized_alias(self) -> str:
        return " ".join(self.alias.lower().split())


@dataclass(frozen=True, slots=True)
class GraphIdMapping:
    """Mapping from an external official/planner identifier to a graph node."""

    system: str
    external_id: str
    target_key: str | None
    source_refs: tuple[str, ...]
    status: str = "resolved"
    confidence: float = 1.0
    caveat: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "system", _required_text(self.system, "id mapping system"))
        object.__setattr__(self, "external_id", _required_text(self.external_id, "external id"))
        status = _required_text(self.status, "resolution status")
        if status not in RESOLUTION_STATUSES:
            raise ValueError(f"invalid resolution status: {status}")
        if status == "resolved" and self.target_key is None:
            raise ValueError("resolved id mapping requires target key")
        if self.target_key is not None:
            object.__setattr__(
                self, "target_key", _required_text(self.target_key, "mapping target")
            )
        object.__setattr__(
            self,
            "source_refs",
            _required_tuple(self.source_refs, "id mapping source refs"),
        )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if self.caveat is not None:
            object.__setattr__(self, "caveat", _required_text(self.caveat, "mapping caveat"))


@dataclass(frozen=True, slots=True)
class GraphCapability:
    """Export/resolver capability attached to a physical graph node."""

    node_key: str
    capability: str
    status: str
    source_refs: tuple[str, ...]
    confidence: float = 1.0
    caveat: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_key", _required_text(self.node_key, "capability node"))
        object.__setattr__(
            self,
            "capability",
            _required_text(self.capability, "capability"),
        )
        status = _required_text(self.status, "capability status")
        if status not in CAPABILITY_STATUSES:
            raise ValueError(f"invalid capability status: {status}")
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "source_refs",
            _required_tuple(self.source_refs, "capability source refs"),
        )
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if self.caveat is not None:
            object.__setattr__(self, "caveat", _required_text(self.caveat, "capability caveat"))


@dataclass(frozen=True, slots=True)
class RequirementFact:
    """Static level/attribute/equipment requirements for a component."""

    component_key: str
    level_or_stage: str
    requirements: dict[str, Any]
    source_refs: tuple[str, ...]
    status: str = "known"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_key", _required_text(self.component_key, "component"))
        object.__setattr__(
            self,
            "level_or_stage",
            _required_text(self.level_or_stage, "level or stage"),
        )
        if not isinstance(self.requirements, dict):
            raise ValueError("requirements must be a mapping")
        object.__setattr__(self, "requirements", dict(self.requirements))
        object.__setattr__(
            self,
            "source_refs",
            _required_tuple(self.source_refs, "requirement source refs"),
        )
        object.__setattr__(self, "status", _fact_status(self.status))
        object.__setattr__(self, "confidence", _confidence(self.confidence))


@dataclass(frozen=True, slots=True)
class ResourceFact:
    """Static cost and reservation profile for a component."""

    component_key: str
    level_or_stage: str
    costs: dict[str, Any]
    reservations: dict[str, Any]
    source_refs: tuple[str, ...]
    status: str = "known"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_key", _required_text(self.component_key, "component"))
        object.__setattr__(
            self,
            "level_or_stage",
            _required_text(self.level_or_stage, "level or stage"),
        )
        if not isinstance(self.costs, dict) or not isinstance(self.reservations, dict):
            raise ValueError("resource facts must use mapping costs and reservations")
        object.__setattr__(self, "costs", dict(self.costs))
        object.__setattr__(self, "reservations", dict(self.reservations))
        object.__setattr__(
            self,
            "source_refs",
            _required_tuple(self.source_refs, "resource source refs"),
        )
        object.__setattr__(self, "status", _fact_status(self.status))
        object.__setattr__(self, "confidence", _confidence(self.confidence))


@dataclass(frozen=True, slots=True)
class PassiveChoice:
    """A source-backed passive tree choice owned by a passive node."""

    choice_key: str
    parent_passive_key: str
    display_name: str
    source_refs: tuple[str, ...]
    status: str = "valid"
    confidence: float = 1.0
    stat_text: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "choice_key", _required_text(self.choice_key, "choice key"))
        object.__setattr__(
            self,
            "parent_passive_key",
            _required_text(self.parent_passive_key, "parent passive"),
        )
        object.__setattr__(self, "display_name", _required_text(self.display_name, "display name"))
        object.__setattr__(
            self,
            "source_refs",
            _required_tuple(self.source_refs, "passive choice source refs"),
        )
        object.__setattr__(self, "status", _required_text(self.status, "passive choice status"))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if self.stat_text is not None:
            object.__setattr__(self, "stat_text", _required_text(self.stat_text, "stat text"))


@dataclass(frozen=True, slots=True)
class AllocationOption:
    """An allocation option under a passive choice."""

    option_key: str
    choice_key: str
    display_name: str
    stat_text: str
    source_refs: tuple[str, ...]
    allocation_states: tuple[str, ...] = ("normal",)
    status: str = "valid"
    confidence: float = 1.0
    caveat: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "option_key", _required_text(self.option_key, "option key"))
        object.__setattr__(self, "choice_key", _required_text(self.choice_key, "choice key"))
        object.__setattr__(self, "display_name", _required_text(self.display_name, "display name"))
        object.__setattr__(self, "stat_text", _required_text(self.stat_text, "stat text"))
        object.__setattr__(
            self,
            "source_refs",
            _required_tuple(self.source_refs, "allocation option source refs"),
        )
        states = _required_tuple(self.allocation_states, "allocation states")
        invalid_states = sorted(set(states) - ALLOCATION_STATES)
        if invalid_states:
            raise ValueError(f"invalid allocation state: {invalid_states[0]}")
        object.__setattr__(self, "allocation_states", states)
        object.__setattr__(self, "status", _required_text(self.status, "allocation option status"))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if self.caveat is not None:
            object.__setattr__(self, "caveat", _required_text(self.caveat, "allocation caveat"))


@dataclass(frozen=True, slots=True)
class ComputedFactRequest:
    """Deterministic computed physical fact request."""

    fact_type: str
    inputs: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_type", _required_text(self.fact_type, "computed fact type"))
        if not isinstance(self.inputs, dict) or not self.inputs:
            raise ValueError("computed fact inputs must be a non-empty mapping")
        object.__setattr__(self, "inputs", dict(self.inputs))


@dataclass(frozen=True, slots=True)
class ComputedFactResult:
    """Source-explainable result from a computed physical fact contract."""

    request: ComputedFactRequest
    status: str
    facts: dict[str, Any]
    source_refs: tuple[str, ...]
    confidence: float = 1.0
    caveat: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, ComputedFactRequest):
            raise ValueError("computed fact result requires a ComputedFactRequest")
        object.__setattr__(self, "status", _fact_status(self.status))
        if not isinstance(self.facts, dict):
            raise ValueError("computed fact result must use mapping facts")
        object.__setattr__(self, "facts", dict(self.facts))
        object.__setattr__(
            self,
            "source_refs",
            _required_tuple(self.source_refs, "computed fact source refs"),
        )
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if self.caveat is not None:
            object.__setattr__(self, "caveat", _required_text(self.caveat, "computed fact caveat"))


@dataclass(frozen=True, slots=True)
class GraphIngestionResult:
    """Nodes, edges and resolver records emitted by one source parser."""

    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    aliases: tuple[GraphAlias, ...] = ()
    id_mappings: tuple[GraphIdMapping, ...] = ()
    requirement_facts: tuple[RequirementFact, ...] = ()
    resource_facts: tuple[ResourceFact, ...] = ()
    passive_choices: tuple[PassiveChoice, ...] = ()
    allocation_options: tuple[AllocationOption, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(self, "aliases", tuple(self.aliases))
        object.__setattr__(self, "id_mappings", tuple(self.id_mappings))
        object.__setattr__(self, "requirement_facts", tuple(self.requirement_facts))
        object.__setattr__(self, "resource_facts", tuple(self.resource_facts))
        object.__setattr__(self, "passive_choices", tuple(self.passive_choices))
        object.__setattr__(self, "allocation_options", tuple(self.allocation_options))


def merge_ingestion_results(*results: GraphIngestionResult) -> GraphIngestionResult:
    """Merge parser outputs while preserving snapshot duplicate checks."""

    nodes: dict[str, GraphNode] = {}
    edges: set[GraphEdge] = set()
    aliases: dict[tuple[str, str], GraphAlias] = {}
    id_mappings: dict[tuple[str, str, str], GraphIdMapping] = {}
    requirement_facts: dict[tuple[str, str], RequirementFact] = {}
    resource_facts: dict[tuple[str, str], ResourceFact] = {}
    passive_choices: dict[str, PassiveChoice] = {}
    allocation_options: dict[str, AllocationOption] = {}

    for result in results:
        for node in result.nodes:
            existing = nodes.get(node.stable_key)
            nodes[node.stable_key] = _merge_node(existing, node) if existing else node
        edges.update(result.edges)
        for alias in result.aliases:
            aliases[(alias.normalized_alias, alias.target_key)] = alias
        for mapping in result.id_mappings:
            key = (mapping.system, mapping.external_id, mapping.status)
            existing = id_mappings.get(key)
            id_mappings[key] = _merge_id_mapping(existing, mapping) if existing else mapping
        for fact in result.requirement_facts:
            requirement_facts[(fact.component_key, fact.level_or_stage)] = fact
        for fact in result.resource_facts:
            resource_facts[(fact.component_key, fact.level_or_stage)] = fact
        for choice in result.passive_choices:
            passive_choices[choice.choice_key] = choice
        for option in result.allocation_options:
            allocation_options[option.option_key] = option

    return GraphIngestionResult(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.stable_key)),
        edges=tuple(sorted(edges, key=_edge_sort_key)),
        aliases=tuple(
            sorted(aliases.values(), key=lambda alias: (alias.normalized_alias, alias.target_key))
        ),
        id_mappings=tuple(
            sorted(id_mappings.values(), key=lambda mapping: (mapping.system, mapping.external_id))
        ),
        requirement_facts=tuple(
            sorted(
                requirement_facts.values(),
                key=lambda fact: (fact.component_key, fact.level_or_stage),
            )
        ),
        resource_facts=tuple(
            sorted(
                resource_facts.values(), key=lambda fact: (fact.component_key, fact.level_or_stage)
            )
        ),
        passive_choices=tuple(
            sorted(passive_choices.values(), key=lambda choice: choice.choice_key)
        ),
        allocation_options=tuple(
            sorted(allocation_options.values(), key=lambda option: option.option_key)
        ),
    )


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    """Deterministic physical graph snapshot."""

    snapshot_id: str
    created_at: datetime
    sources: tuple[GraphSource, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    aliases: tuple[GraphAlias, ...] = ()
    id_mappings: tuple[GraphIdMapping, ...] = ()
    capabilities: tuple[GraphCapability, ...] = ()
    requirement_facts: tuple[RequirementFact, ...] = ()
    resource_facts: tuple[ResourceFact, ...] = ()
    passive_choices: tuple[PassiveChoice, ...] = ()
    allocation_options: tuple[AllocationOption, ...] = ()
    computed_results: tuple[ComputedFactResult, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _required_text(self.snapshot_id, "snapshot id"))
        if self.created_at.tzinfo is None:
            raise ValueError("snapshot created_at must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))

        sources = tuple(sorted(self.sources, key=lambda source: source.source_id))
        nodes = tuple(sorted(self.nodes, key=lambda node: node.stable_key))
        edges = tuple(sorted(self.edges, key=_edge_sort_key))
        aliases = tuple(
            sorted(self.aliases, key=lambda alias: (alias.normalized_alias, alias.target_key))
        )
        id_mappings = tuple(
            sorted(
                self.id_mappings,
                key=lambda mapping: (mapping.system, mapping.external_id, mapping.status),
            )
        )
        capabilities = tuple(
            sorted(
                self.capabilities,
                key=lambda capability: (capability.node_key, capability.capability),
            )
        )
        requirement_facts = tuple(
            sorted(
                self.requirement_facts,
                key=lambda fact: (fact.component_key, fact.level_or_stage),
            )
        )
        resource_facts = tuple(
            sorted(self.resource_facts, key=lambda fact: (fact.component_key, fact.level_or_stage))
        )
        passive_choices = tuple(sorted(self.passive_choices, key=lambda choice: choice.choice_key))
        allocation_options = tuple(
            sorted(self.allocation_options, key=lambda option: option.option_key)
        )
        computed_results = tuple(
            sorted(
                self.computed_results,
                key=lambda result: (
                    result.request.fact_type,
                    json.dumps(result.request.inputs, sort_keys=True, default=str),
                ),
            )
        )

        _reject_duplicate_texts((source.source_id for source in sources), "source id")
        _reject_duplicate_texts((node.stable_key for node in nodes), "node stable key")
        _reject_duplicate_texts(
            (f"{alias.normalized_alias}\0{alias.target_key}" for alias in aliases),
            "alias",
        )
        _reject_duplicate_texts(
            (
                f"{mapping.system}\0{mapping.external_id}\0{mapping.status}"
                for mapping in id_mappings
            ),
            "id mapping",
        )
        _reject_duplicate_texts(
            (f"{fact.component_key}\0{fact.level_or_stage}" for fact in requirement_facts),
            "requirement fact",
        )
        _reject_duplicate_texts(
            (f"{fact.component_key}\0{fact.level_or_stage}" for fact in resource_facts),
            "resource fact",
        )
        _reject_duplicate_texts(
            (choice.choice_key for choice in passive_choices),
            "passive choice",
        )
        _reject_duplicate_texts(
            (option.option_key for option in allocation_options),
            "allocation option",
        )

        source_ids = {source.source_id for source in sources}
        node_keys = {node.stable_key for node in nodes}
        for node in nodes:
            missing_sources = sorted(set(node.source_refs) - source_ids)
            if missing_sources:
                raise ValueError(
                    f"node {node.stable_key!r} references unknown source {missing_sources[0]!r}"
                )
        for edge in edges:
            if edge.edge_type not in ALLOWED_EDGE_TYPES:
                raise ValueError(f"unknown edge type: {edge.edge_type}")
            if edge.source_key not in node_keys or edge.target_key not in node_keys:
                raise ValueError(
                    f"orphan edge: {edge.edge_type} {edge.source_key!r} -> {edge.target_key!r}"
                )
            missing_evidence = sorted(set(edge.evidence_refs) - source_ids)
            if missing_evidence:
                raise ValueError(
                    f"edge {edge.edge_type!r} references unknown evidence {missing_evidence[0]!r}"
                )
        for alias in aliases:
            _ensure_sources_exist(alias.source_refs, source_ids, f"alias {alias.alias!r}")
            _ensure_node_exists(alias.target_key, node_keys, "alias target")
        for mapping in id_mappings:
            _ensure_sources_exist(
                mapping.source_refs,
                source_ids,
                f"id mapping {mapping.external_id!r}",
            )
            if mapping.target_key is not None:
                _ensure_node_exists(mapping.target_key, node_keys, "id mapping target")
        for capability in capabilities:
            _ensure_sources_exist(
                capability.source_refs,
                source_ids,
                f"capability {capability.capability!r}",
            )
            _ensure_node_exists(capability.node_key, node_keys, "capability node")
        for fact in requirement_facts:
            _ensure_sources_exist(fact.source_refs, source_ids, "requirement fact")
            _ensure_node_exists(fact.component_key, node_keys, "requirement component")
        for fact in resource_facts:
            _ensure_sources_exist(fact.source_refs, source_ids, "resource fact")
            _ensure_node_exists(fact.component_key, node_keys, "resource component")
        for choice in passive_choices:
            _ensure_sources_exist(choice.source_refs, source_ids, "passive choice")
            _ensure_node_exists(choice.parent_passive_key, node_keys, "parent passive")
        choice_keys = {choice.choice_key for choice in passive_choices}
        for option in allocation_options:
            _ensure_sources_exist(option.source_refs, source_ids, "allocation option")
            if option.choice_key not in choice_keys:
                raise ValueError(
                    f"allocation option references unknown choice {option.choice_key!r}"
                )
        for result in computed_results:
            _ensure_sources_exist(result.source_refs, source_ids, "computed fact")

        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(self, "id_mappings", id_mappings)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "requirement_facts", requirement_facts)
        object.__setattr__(self, "resource_facts", resource_facts)
        object.__setattr__(self, "passive_choices", passive_choices)
        object.__setattr__(self, "allocation_options", allocation_options)
        object.__setattr__(self, "computed_results", computed_results)


def build_snapshot(
    *,
    sources: tuple[GraphSource, ...],
    nodes: tuple[GraphNode, ...],
    edges: tuple[GraphEdge, ...],
    aliases: tuple[GraphAlias, ...] = (),
    id_mappings: tuple[GraphIdMapping, ...] = (),
    capabilities: tuple[GraphCapability, ...] = (),
    requirement_facts: tuple[RequirementFact, ...] = (),
    resource_facts: tuple[ResourceFact, ...] = (),
    passive_choices: tuple[PassiveChoice, ...] = (),
    allocation_options: tuple[AllocationOption, ...] = (),
    computed_results: tuple[ComputedFactResult, ...] = (),
) -> GraphSnapshot:
    """Build a snapshot whose id depends only on sorted graph inputs."""

    sorted_sources = tuple(sorted(sources, key=lambda source: source.source_id))
    sorted_nodes = tuple(sorted(nodes, key=lambda node: node.stable_key))
    sorted_edges = tuple(sorted(edges, key=_edge_sort_key))
    sorted_aliases = tuple(
        sorted(aliases, key=lambda alias: (alias.normalized_alias, alias.target_key))
    )
    sorted_id_mappings = tuple(
        sorted(
            id_mappings, key=lambda mapping: (mapping.system, mapping.external_id, mapping.status)
        )
    )
    sorted_capabilities = tuple(
        sorted(capabilities, key=lambda capability: (capability.node_key, capability.capability))
    )
    sorted_requirement_facts = tuple(
        sorted(requirement_facts, key=lambda fact: (fact.component_key, fact.level_or_stage))
    )
    sorted_resource_facts = tuple(
        sorted(resource_facts, key=lambda fact: (fact.component_key, fact.level_or_stage))
    )
    sorted_passive_choices = tuple(sorted(passive_choices, key=lambda choice: choice.choice_key))
    sorted_allocation_options = tuple(
        sorted(allocation_options, key=lambda option: option.option_key)
    )
    sorted_computed_results = tuple(
        sorted(
            computed_results,
            key=lambda result: (
                result.request.fact_type,
                json.dumps(result.request.inputs, sort_keys=True, default=str),
            ),
        )
    )
    payload = {
        "sources": [_source_payload(source) for source in sorted_sources],
        "nodes": [_node_payload(node) for node in sorted_nodes],
        "edges": [_edge_payload(edge) for edge in sorted_edges],
        "aliases": [_alias_payload(alias) for alias in sorted_aliases],
        "id_mappings": [_mapping_payload(mapping) for mapping in sorted_id_mappings],
        "capabilities": [_capability_payload(capability) for capability in sorted_capabilities],
        "requirement_facts": [_requirement_payload(fact) for fact in sorted_requirement_facts],
        "resource_facts": [_resource_payload(fact) for fact in sorted_resource_facts],
        "passive_choices": [_passive_choice_payload(choice) for choice in sorted_passive_choices],
        "allocation_options": [
            _allocation_option_payload(option) for option in sorted_allocation_options
        ],
        "computed_results": [
            _computed_result_payload(result) for result in sorted_computed_results
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    return GraphSnapshot(
        snapshot_id=f"physical-graph-{digest}",
        created_at=datetime.now(UTC),
        sources=sorted_sources,
        nodes=sorted_nodes,
        edges=sorted_edges,
        aliases=sorted_aliases,
        id_mappings=sorted_id_mappings,
        capabilities=sorted_capabilities,
        requirement_facts=sorted_requirement_facts,
        resource_facts=sorted_resource_facts,
        passive_choices=sorted_passive_choices,
        allocation_options=sorted_allocation_options,
        computed_results=sorted_computed_results,
    )


def _source_payload(source: GraphSource) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "kind": source.kind,
        "source_file": source.source_file,
        "claims": [(claim.key, claim.value) for claim in source.claims],
        "expected_count": source.expected_count,
        "confidence": source.confidence,
        "source_url": source.source_url,
        "schema_version": source.schema_version,
    }


def _node_payload(node: GraphNode) -> dict[str, Any]:
    return {
        "stable_key": node.stable_key,
        "node_type": node.node_type,
        "display_name": node.display_name,
        "source_refs": node.source_refs,
        "aliases": node.aliases,
        "status": node.status,
        "confidence": node.confidence,
        "official_ids": dict(sorted(node.official_ids.items())),
    }


def _edge_payload(edge: GraphEdge) -> dict[str, Any]:
    return {
        "edge_type": edge.edge_type,
        "source_key": edge.source_key,
        "target_key": edge.target_key,
        "evidence_refs": edge.evidence_refs,
        "status": edge.status,
        "confidence": edge.confidence,
        "modelability": edge.modelability,
    }


def _alias_payload(alias: GraphAlias) -> dict[str, Any]:
    return {
        "alias": alias.alias,
        "target_key": alias.target_key,
        "source_refs": alias.source_refs,
        "status": alias.status,
        "confidence": alias.confidence,
    }


def _mapping_payload(mapping: GraphIdMapping) -> dict[str, Any]:
    return {
        "system": mapping.system,
        "external_id": mapping.external_id,
        "target_key": mapping.target_key,
        "source_refs": mapping.source_refs,
        "status": mapping.status,
        "confidence": mapping.confidence,
        "caveat": mapping.caveat,
    }


def _capability_payload(capability: GraphCapability) -> dict[str, Any]:
    return {
        "node_key": capability.node_key,
        "capability": capability.capability,
        "status": capability.status,
        "source_refs": capability.source_refs,
        "confidence": capability.confidence,
        "caveat": capability.caveat,
    }


def _requirement_payload(fact: RequirementFact) -> dict[str, Any]:
    return {
        "component_key": fact.component_key,
        "level_or_stage": fact.level_or_stage,
        "requirements": fact.requirements,
        "source_refs": fact.source_refs,
        "status": fact.status,
        "confidence": fact.confidence,
    }


def _resource_payload(fact: ResourceFact) -> dict[str, Any]:
    return {
        "component_key": fact.component_key,
        "level_or_stage": fact.level_or_stage,
        "costs": fact.costs,
        "reservations": fact.reservations,
        "source_refs": fact.source_refs,
        "status": fact.status,
        "confidence": fact.confidence,
    }


def _passive_choice_payload(choice: PassiveChoice) -> dict[str, Any]:
    return {
        "choice_key": choice.choice_key,
        "parent_passive_key": choice.parent_passive_key,
        "display_name": choice.display_name,
        "source_refs": choice.source_refs,
        "status": choice.status,
        "confidence": choice.confidence,
        "stat_text": choice.stat_text,
    }


def _allocation_option_payload(option: AllocationOption) -> dict[str, Any]:
    return {
        "option_key": option.option_key,
        "choice_key": option.choice_key,
        "display_name": option.display_name,
        "stat_text": option.stat_text,
        "source_refs": option.source_refs,
        "allocation_states": option.allocation_states,
        "status": option.status,
        "confidence": option.confidence,
        "caveat": option.caveat,
    }


def _computed_result_payload(result: ComputedFactResult) -> dict[str, Any]:
    return {
        "request": {
            "fact_type": result.request.fact_type,
            "inputs": result.request.inputs,
        },
        "status": result.status,
        "facts": result.facts,
        "source_refs": result.source_refs,
        "confidence": result.confidence,
        "caveat": result.caveat,
    }


def _snapshot_payload(snapshot: GraphSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "created_at": snapshot.created_at.isoformat(),
        "sources": [_source_payload(source) for source in snapshot.sources],
        "nodes": [_node_payload(node) for node in snapshot.nodes],
        "edges": [_edge_payload(edge) for edge in snapshot.edges],
        "aliases": [_alias_payload(alias) for alias in snapshot.aliases],
        "id_mappings": [_mapping_payload(mapping) for mapping in snapshot.id_mappings],
        "capabilities": [_capability_payload(capability) for capability in snapshot.capabilities],
        "requirement_facts": [_requirement_payload(fact) for fact in snapshot.requirement_facts],
        "resource_facts": [_resource_payload(fact) for fact in snapshot.resource_facts],
        "passive_choices": [_passive_choice_payload(choice) for choice in snapshot.passive_choices],
        "allocation_options": [
            _allocation_option_payload(option) for option in snapshot.allocation_options
        ],
        "computed_results": [
            _computed_result_payload(result) for result in snapshot.computed_results
        ],
    }


def _graph_source_from_payload(payload: dict[str, Any]) -> GraphSource:
    return GraphSource(
        source_id=payload["source_id"],
        kind=payload["kind"],
        source_file=payload["source_file"],
        claims=tuple(SourceClaim(key, value) for key, value in payload.get("claims", [])),
        expected_count=payload.get("expected_count"),
        confidence=payload.get("confidence", 1.0),
        source_url=payload.get("source_url"),
        schema_version=payload.get("schema_version"),
    )


def _graph_node_from_payload(payload: dict[str, Any]) -> GraphNode:
    return GraphNode(
        stable_key=payload["stable_key"],
        node_type=payload["node_type"],
        display_name=payload["display_name"],
        source_refs=tuple(payload.get("source_refs", [])),
        aliases=tuple(payload.get("aliases", [])),
        status=payload.get("status", "valid"),
        confidence=payload.get("confidence", 1.0),
        official_ids=dict(payload.get("official_ids", {})),
    )


def _graph_edge_from_payload(payload: dict[str, Any]) -> GraphEdge:
    return GraphEdge(
        edge_type=payload["edge_type"],
        source_key=payload["source_key"],
        target_key=payload["target_key"],
        evidence_refs=tuple(payload.get("evidence_refs", [])),
        status=payload.get("status", "valid"),
        confidence=payload.get("confidence", 1.0),
        modelability=payload.get("modelability"),
    )


def _graph_alias_from_payload(payload: dict[str, Any]) -> GraphAlias:
    return GraphAlias(
        alias=payload["alias"],
        target_key=payload["target_key"],
        source_refs=tuple(payload.get("source_refs", [])),
        status=payload.get("status", "valid"),
        confidence=payload.get("confidence", 1.0),
    )


def _graph_id_mapping_from_payload(payload: dict[str, Any]) -> GraphIdMapping:
    return GraphIdMapping(
        system=payload["system"],
        external_id=payload["external_id"],
        target_key=payload.get("target_key"),
        source_refs=tuple(payload.get("source_refs", [])),
        status=payload.get("status", "resolved"),
        confidence=payload.get("confidence", 1.0),
        caveat=payload.get("caveat"),
    )


def _graph_capability_from_payload(payload: dict[str, Any]) -> GraphCapability:
    return GraphCapability(
        node_key=payload["node_key"],
        capability=payload["capability"],
        status=payload["status"],
        source_refs=tuple(payload.get("source_refs", [])),
        confidence=payload.get("confidence", 1.0),
        caveat=payload.get("caveat"),
    )


def _requirement_fact_from_payload(payload: dict[str, Any]) -> RequirementFact:
    return RequirementFact(
        component_key=payload["component_key"],
        level_or_stage=payload["level_or_stage"],
        requirements=dict(payload.get("requirements", {})),
        source_refs=tuple(payload.get("source_refs", [])),
        status=payload.get("status", "known"),
        confidence=payload.get("confidence", 1.0),
    )


def _resource_fact_from_payload(payload: dict[str, Any]) -> ResourceFact:
    return ResourceFact(
        component_key=payload["component_key"],
        level_or_stage=payload["level_or_stage"],
        costs=dict(payload.get("costs", {})),
        reservations=dict(payload.get("reservations", {})),
        source_refs=tuple(payload.get("source_refs", [])),
        status=payload.get("status", "known"),
        confidence=payload.get("confidence", 1.0),
    )


def _passive_choice_from_payload(payload: dict[str, Any]) -> PassiveChoice:
    return PassiveChoice(
        choice_key=payload["choice_key"],
        parent_passive_key=payload["parent_passive_key"],
        display_name=payload["display_name"],
        source_refs=tuple(payload.get("source_refs", [])),
        status=payload.get("status", "valid"),
        confidence=payload.get("confidence", 1.0),
        stat_text=payload.get("stat_text"),
    )


def _allocation_option_from_payload(payload: dict[str, Any]) -> AllocationOption:
    return AllocationOption(
        option_key=payload["option_key"],
        choice_key=payload["choice_key"],
        display_name=payload["display_name"],
        stat_text=payload["stat_text"],
        source_refs=tuple(payload.get("source_refs", [])),
        allocation_states=tuple(payload.get("allocation_states", ["normal"])),
        status=payload.get("status", "valid"),
        confidence=payload.get("confidence", 1.0),
        caveat=payload.get("caveat"),
    )


def _computed_result_from_payload(payload: dict[str, Any]) -> ComputedFactResult:
    request_payload = dict(payload.get("request", {}))
    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type=request_payload["fact_type"],
            inputs=dict(request_payload.get("inputs", {})),
        ),
        status=payload["status"],
        facts=dict(payload.get("facts", {})),
        source_refs=tuple(payload.get("source_refs", [])),
        confidence=payload.get("confidence", 1.0),
        caveat=payload.get("caveat"),
    )


def _inventory_claims(
    spec: SourceInventorySpec,
    *,
    freshness_status: str,
) -> tuple[SourceClaim, ...]:
    base_claims = {
        "game_patch": "unknown",
        "passive_tree_version": "not_applicable",
        "pob_commit": "not_applicable",
        "freshness_status": freshness_status,
    }
    for claim in spec.claims:
        base_claims[claim.key] = claim.value
    return tuple(SourceClaim(key, base_claims[key]) for key in sorted(base_claims))


def _missing_inventory_source(spec: SourceInventorySpec) -> GraphSource:
    return GraphSource(
        source_id=spec.source_id,
        kind=spec.kind,
        source_file=spec.relative_path,
        claims=_inventory_claims(spec, freshness_status="missing"),
        expected_count=0,
        confidence=0.0,
        source_url=spec.source_url,
        schema_version=spec.schema_version,
    )


def _json_top_level_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict | list):
        return len(payload)
    raise ValueError(f"source inventory JSON must be object or array: {path}")


def _gem_key(metadata_id: str, gem_type: str) -> str:
    metadata = _required_text(metadata_id, "gem metadata id")
    return f"support:{metadata}" if gem_type == "support" else f"gem:{metadata}"


def _gem_display_name(record: dict[str, Any], fallback: str) -> str:
    base_item = record.get("base_item")
    if isinstance(base_item, dict) and base_item.get("display_name"):
        return _required_text(str(base_item["display_name"]), "gem display name")
    return _required_text(fallback.rsplit("/", 1)[-1], "gem display name")


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return tuple(_required_text(str(item), label) for item in value)


def _positive_spawn_tags(value: object, mod_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{mod_id} spawn_weights must be a list")
    tags: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError(f"{mod_id} spawn weight entry must be an object")
        weight = entry.get("weight")
        if not isinstance(weight, int | float) or weight <= 0:
            continue
        tags.append(_required_text(str(entry.get("tag")), f"{mod_id} spawn tag"))
    return tuple(tags)


def _target_keys(
    edges: tuple[GraphEdge, ...],
    *,
    source_key: str,
    edge_type: str,
) -> set[str]:
    return {
        edge.target_key
        for edge in edges
        if edge.source_key == source_key and edge.edge_type == edge_type
    }


def _tag_name(tag_key: str) -> str:
    return _required_text(tag_key.rsplit(":", 1)[-1], "tag key")


def _requirements_for(snapshot: GraphSnapshot, component_key: str) -> dict[str, Any]:
    for fact in snapshot.requirement_facts:
        if fact.component_key == component_key:
            return fact.requirements
    return {}


def _requirement_fact_for(
    snapshot: GraphSnapshot,
    *,
    component_key: str,
    level_or_stage: str,
) -> RequirementFact | None:
    for fact in snapshot.requirement_facts:
        if fact.component_key == component_key and fact.level_or_stage == level_or_stage:
            return fact
    return None


def _passive_node_key(
    node_record: dict[str, Any],
    *,
    node_id: str,
    tree_version: str,
) -> str:
    node_id_text = _required_text(str(node_id), "passive node id")
    if bool(node_record.get("isKeystone")):
        prefix = "keystone"
    elif bool(node_record.get("isNotable")):
        prefix = "notable"
    else:
        prefix = "passive"
    return f"{prefix}:pob:{tree_version}:{node_id_text}"


def _passive_node_type(node_record: dict[str, Any]) -> str:
    if bool(node_record.get("isKeystone")):
        return "keystone"
    if bool(node_record.get("isNotable")):
        return "notable"
    return "passive"


def _passive_type_key_for_record(node_record: dict[str, Any]) -> str:
    if node_record.get("classesStart"):
        return "passive_type:class_start"
    if bool(node_record.get("isAscendancyStart")):
        return "passive_type:ascendancy_start"
    if bool(node_record.get("isKeystone")):
        return "passive_type:keystone"
    if bool(node_record.get("isNotable")):
        return "passive_type:notable"
    return "passive_type:passive"


def _ascendancy_key_for_name(
    nodes: dict[str, GraphNode],
    ascendancy_name: str,
) -> str | None:
    normalized = _normalized_token(ascendancy_name)
    matches = [
        key
        for key, node in nodes.items()
        if node.node_type == "ascendancy" and _normalized_token(node.display_name) == normalized
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _node_connections(node_record: dict[str, Any], *, node_id: str) -> tuple[int, ...]:
    raw_connections = node_record.get("connections")
    if raw_connections is None:
        return ()
    if not isinstance(raw_connections, list):
        raise ValueError(f"{node_id} connections must be a list")
    resolved: list[int] = []
    for entry in raw_connections:
        if isinstance(entry, int):
            resolved.append(entry)
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"{node_id} connection entry must be an object or int")
        connection_id = entry.get("id")
        if not isinstance(connection_id, int):
            raise ValueError(f"{node_id} connection id must be an integer")
        resolved.append(connection_id)
    return tuple(resolved)


def _first_stat_text(value: object) -> str | None:
    if value is None:
        return None
    values = _string_list(value, "stat text")
    return values[0] if values else None


def _passive_options(value: object, *, node_id: str) -> tuple[dict[str, Any], ...]:
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, dict):
        options: list[dict[str, Any]] = []
        for key, payload in value.items():
            if payload is not None and not isinstance(payload, dict):
                raise ValueError(f"{node_id} option entry must be an object")
            record = dict(payload or {})
            option_name = _required_text(str(record.get("name") or key), f"{node_id} option name")
            option_id = str(record.get("id") or option_name.replace(" ", "_"))
            record["id"] = option_id
            record["name"] = option_name
            if "stats" not in record:
                record["stats"] = [f"selector:{option_name}"]
            options.append(record)
        return tuple(options)
    raise ValueError(f"{node_id} options must be a list or object")


def _unique_item_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    segments = text.split("[[")
    for segment in segments[1:]:
        body = segment.split("]]", 1)[0]
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        if lines:
            blocks.append(lines)
    return blocks


def _unique_mod_lines(lines: list[str]) -> list[str]:
    ignored_prefixes = (
        "Variant:",
        "Implicits:",
        "Source:",
        "Requires Level",
    )
    return [line for line in lines if not line.startswith(ignored_prefixes)]


def _resource_profile_parts(
    payload: object,
    record_id: str,
    *,
    label: str,
) -> dict[str, dict[str, Any]] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError(f"{record_id} {label} must be an object")

    costs: dict[str, Any] = {}
    reservations: dict[str, Any] = {}
    raw_costs = payload.get("costs")
    if raw_costs is not None:
        if not isinstance(raw_costs, dict):
            raise ValueError(f"{record_id} {label}.costs must be an object")
        costs.update(_normalized_fact_mapping(raw_costs))
    raw_reservations = payload.get("reservations")
    if raw_reservations is not None:
        if not isinstance(raw_reservations, dict):
            raise ValueError(f"{record_id} {label}.reservations must be an object")
        reservations.update(_normalized_fact_mapping(raw_reservations))

    for scalar_key in ("cost_multiplier", "cooldown", "stored_uses"):
        if scalar_key in payload:
            costs[_normalized_token(scalar_key)] = payload[scalar_key]

    if not costs and not reservations:
        return None
    return {"costs": costs, "reservations": reservations}


def _type_expression(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return tuple(_required_text(str(item), label) for item in value)


def _int_or_zero(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid numeric requirement")
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str) and value.strip():
        return int(value)
    return 0


def _source_refs_for_components(
    snapshot: GraphSnapshot,
    component_keys: tuple[str, ...],
) -> tuple[str, ...]:
    refs: set[str] = set()
    component_set = set(component_keys)
    for node in snapshot.nodes:
        if node.stable_key in component_set:
            refs.update(node.source_refs)
    for fact in snapshot.requirement_facts:
        if fact.component_key in component_set:
            refs.update(fact.source_refs)
    for edge in snapshot.edges:
        if edge.source_key in component_set or edge.target_key in component_set:
            refs.update(edge.evidence_refs)
    return tuple(sorted(refs))


def _merge_resource_fact(
    exact: ResourceFact | None,
    base: ResourceFact | None,
    *,
    requested_stage: str,
) -> ComputedFactResult | None:
    if exact is None:
        return None
    merged_costs = dict(base.costs) if base is not None and exact.level_or_stage != "base" else {}
    merged_reservations = (
        dict(base.reservations) if base is not None and exact.level_or_stage != "base" else {}
    )
    merged_costs.update(exact.costs)
    merged_reservations.update(exact.reservations)
    source_refs = exact.source_refs
    if base is not None and exact.level_or_stage != "base":
        source_refs = tuple(sorted(set(source_refs) | set(base.source_refs)))
    return _resource_result(
        component_key=exact.component_key,
        requested_stage=requested_stage,
        actual_stage=exact.level_or_stage,
        costs=merged_costs,
        reservations=merged_reservations,
        source_refs=source_refs,
    )


def _resource_result(
    *,
    component_key: str,
    requested_stage: str,
    actual_stage: str,
    costs: dict[str, Any],
    reservations: dict[str, Any],
    source_refs: tuple[str, ...],
) -> ComputedFactResult:
    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type="resource_profile_for_component",
            inputs={"component_key": component_key, "level_or_stage": requested_stage},
        ),
        status="known",
        facts={
            "level_or_stage": actual_stage,
            "costs": dict(costs),
            "reservations": dict(reservations),
        },
        source_refs=source_refs,
    )


def _support_candidate_result(
    *,
    snapshot: GraphSnapshot,
    support_key: str,
    skill_key: str,
    status: str,
    candidate_status: str,
    excluded_reason: str | None,
    matched_skill_types: list[str] | tuple[str, ...],
    shared_tags: list[str] | tuple[str, ...],
) -> ComputedFactResult:
    facts: dict[str, Any] = {
        "support_key": support_key,
        "skill_key": skill_key,
        "candidate_status": candidate_status,
        "matched_skill_types": list(matched_skill_types),
        "shared_tags": list(shared_tags),
    }
    if excluded_reason is not None:
        facts["excluded_reason"] = excluded_reason
    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type="support_skill_candidate",
            inputs={"support_key": support_key, "skill_key": skill_key},
        ),
        status=status,
        facts=facts,
        source_refs=_source_refs_for_components(snapshot, (support_key, skill_key)),
    )


def _socket_support_result(
    *,
    snapshot: GraphSnapshot,
    skill_key: str,
    support_key: str,
    status: str,
    legality_status: str,
    excluded_reasons: list[str],
    context: dict[str, Any],
    support_candidate_status: str,
    support_family: str | None,
    source_refs: tuple[str, ...],
    caveat: str | None = None,
) -> ComputedFactResult:
    facts: dict[str, Any] = {
        "skill_key": skill_key,
        "support_key": support_key,
        "legality_status": legality_status,
        "excluded_reasons": list(excluded_reasons),
        "support_candidate_status": support_candidate_status,
        "socket_context": dict(context),
    }
    if support_family is not None:
        facts["support_family"] = support_family
    return ComputedFactResult(
        request=ComputedFactRequest(
            fact_type="socket_support_legality",
            inputs={"skill_key": skill_key, "support_key": support_key},
        ),
        status=status,
        facts=facts,
        source_refs=source_refs or _source_refs_for_components(snapshot, (skill_key, support_key)),
        caveat=caveat,
        confidence=0.5 if status == "unknown" else 1.0,
    )


def _phase2_can_roll_sample(snapshot: GraphSnapshot) -> dict[str, Any]:
    base_keys = sorted(node.stable_key for node in snapshot.nodes if node.node_type == "item_base")
    mod_keys = sorted(node.stable_key for node in snapshot.nodes if node.node_type == "mod")
    for base_key in base_keys:
        for mod_key in mod_keys:
            requirement = _requirements_for(snapshot, mod_key)
            item_level = max(_int_or_zero(requirement.get("required_level")), 1)
            try:
                sample = build_can_roll_mod_e2e_sample(
                    snapshot=snapshot,
                    base_item_key=base_key,
                    mod_key=mod_key,
                    item_level=item_level,
                )
            except ValueError:
                continue
            if sample["result"]["facts"].get("can_roll") is True:
                return sample
    return _missing_fixed_sample(
        fact_type="can_roll_mod",
        caveat="missing_can_roll_fixture",
    )


def _phase2_requirement_sample(
    snapshot: GraphSnapshot, preferred_component_key: str
) -> dict[str, Any]:
    preferred = next(
        (
            fact
            for fact in snapshot.requirement_facts
            if fact.component_key == preferred_component_key and fact.level_or_stage == "base"
        ),
        None,
    )
    fact = preferred or next(
        (
            item
            for item in snapshot.requirement_facts
            if item.level_or_stage == "base"
            and item.component_key.startswith(("gem:", "support:", "skill:"))
        ),
        None,
    )
    if fact is None:
        return _missing_fixed_sample(
            fact_type="requirements_for_component",
            caveat="missing_requirement_fixture",
        )
    return build_requirements_for_component_e2e_sample(
        snapshot=snapshot,
        component_key=fact.component_key,
        level_or_stage=fact.level_or_stage,
    )


def _phase2_resource_sample(
    snapshot: GraphSnapshot, preferred_component_key: str
) -> dict[str, Any]:
    preferred = next(
        (fact for fact in snapshot.resource_facts if fact.component_key == preferred_component_key),
        None,
    )
    fact = preferred or next(iter(snapshot.resource_facts), None)
    if fact is None:
        return _missing_fixed_sample(
            fact_type="resource_profile_for_component",
            caveat="missing_resource_fixture",
        )
    return build_resource_profile_for_component_e2e_sample(
        snapshot=snapshot,
        component_key=fact.component_key,
        level_or_stage=fact.level_or_stage,
    )


def _phase2_passive_connected_to_sample(
    snapshot: GraphSnapshot, passive_key: str
) -> dict[str, Any]:
    edge = next(
        (
            item
            for item in snapshot.edges
            if item.edge_type == "connected_to" and item.source_key == passive_key
        ),
        None,
    )
    if edge is None:
        return _missing_fixed_sample(
            fact_type="edge_provenance",
            caveat="missing_passive_connected_to_fixture",
        )
    return build_edge_provenance_e2e_sample(
        snapshot=snapshot,
        edge_type=edge.edge_type,
        source_key=edge.source_key,
        target_key=edge.target_key,
    )


def _missing_fixed_sample(*, fact_type: str, caveat: str) -> dict[str, Any]:
    return {
        "query": {"fact_type": fact_type},
        "result": {
            "status": "unknown",
            "facts": {},
            "source_refs": [],
            "caveat": caveat,
        },
    }


def _granted_skill_keys(snapshot: GraphSnapshot, gem_key: str) -> list[str]:
    return sorted(
        {
            edge.target_key
            for edge in snapshot.edges
            if edge.edge_type == "grants_skill" and edge.source_key == gem_key
        }
    )


def _support_contract_for(
    snapshot: GraphSnapshot,
    support_key: str,
) -> tuple[str, RequirementFact]:
    granted_skill_keys = _granted_skill_keys(snapshot, support_key)
    if not granted_skill_keys:
        raise ValueError(f"missing granted support skill contract: {support_key}")
    contracts = [
        (granted_skill_key, fact)
        for granted_skill_key in granted_skill_keys
        if (
            fact := _requirement_fact_for(
                snapshot,
                component_key=granted_skill_key,
                level_or_stage="support_contract",
            )
        )
        is not None
    ]
    if not contracts:
        raise ValueError(f"missing support contract requirements: {support_key}")
    if len(contracts) > 1:
        raise ValueError(f"ambiguous granted support skill contract: {support_key}")
    return contracts[0]


def _added_skill_types_for_support(snapshot: GraphSnapshot, support_key: str) -> set[str]:
    _, contract_requirements = _support_contract_for(snapshot, support_key)
    return {
        token.casefold()
        for token in _string_tuple(contract_requirements.requirements.get("added_types"))
        if token.casefold() not in {"and", "or", "not"}
    }


def _granted_by_skill(snapshot: GraphSnapshot, skill_key: str) -> str | None:
    for edge in snapshot.edges:
        if edge.edge_type == "granted_by" and edge.source_key == skill_key:
            return edge.target_key
    return None


def _is_skill_granted_by_gem(snapshot: GraphSnapshot, skill_key: str) -> bool:
    return _granted_by_skill(snapshot, skill_key) is not None


def _skill_types_for(snapshot: GraphSnapshot, skill_key: str) -> set[str]:
    return {
        node_key.rsplit(":", 1)[-1]
        for node_key in _target_keys(snapshot.edges, source_key=skill_key, edge_type="has_type")
    }


def _shared_component_tags(snapshot: GraphSnapshot, support_key: str, skill_key: str) -> list[str]:
    granted_component = _granted_by_skill(snapshot, skill_key) or skill_key
    support_tags = {
        _tag_name(tag)
        for tag in _target_keys(snapshot.edges, source_key=support_key, edge_type="has_tag")
    }
    skill_tags = {
        _tag_name(tag)
        for tag in _target_keys(snapshot.edges, source_key=granted_component, edge_type="has_tag")
    }
    return sorted(support_tags & skill_tags)


def _support_family_for(snapshot: GraphSnapshot, support_key: str) -> str | None:
    try:
        _, contract_requirements = _support_contract_for(snapshot, support_key)
    except ValueError:
        return None
    family = contract_requirements.requirements.get("support_family")
    if family is None:
        return support_key
    return _required_text(str(family), "support family")


def _type_expression_matches(
    expression: tuple[str, ...],
    skill_types: set[str],
) -> bool:
    if not expression:
        return False
    stack: list[bool] = []
    for token in expression:
        operator = token.casefold()
        if operator == "or":
            other = stack.pop() if stack else False
            current = stack.pop() if stack else False
            stack.append(current or other)
        elif operator == "and":
            other = stack.pop() if stack else False
            current = stack.pop() if stack else False
            stack.append(current and other)
        elif operator == "not":
            current = stack.pop() if stack else False
            stack.append(not current)
        else:
            stack.append(operator in skill_types)
    return any(stack)


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(_required_text(str(item), "string tuple") for item in value)
    if isinstance(value, list):
        return tuple(_required_text(str(item), "string tuple") for item in value)
    raise ValueError("value must be a list or tuple of strings")


def _string_values(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple | list):
        return tuple(_required_text(str(item), label) for item in value)
    raise ValueError(f"{label} must be a list")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid integer")
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str) and value.strip():
        return int(value)
    return None


def _optional_nonempty_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _merge_node(existing: GraphNode, incoming: GraphNode) -> GraphNode:
    if (
        existing.node_type != incoming.node_type
        or existing.display_name != incoming.display_name
        or existing.status != incoming.status
    ):
        raise ValueError(f"conflicting graph node: {existing.stable_key}")
    official_ids = {**existing.official_ids, **incoming.official_ids}
    for key, value in existing.official_ids.items():
        if key in incoming.official_ids and incoming.official_ids[key] != value:
            raise ValueError(f"conflicting official id for node: {existing.stable_key}")
    return GraphNode(
        stable_key=existing.stable_key,
        node_type=existing.node_type,
        display_name=existing.display_name,
        source_refs=tuple(sorted(set(existing.source_refs) | set(incoming.source_refs))),
        aliases=tuple(sorted(set(existing.aliases) | set(incoming.aliases))),
        status=existing.status,
        confidence=min(existing.confidence, incoming.confidence),
        official_ids=official_ids,
    )


def _merge_id_mapping(existing: GraphIdMapping, incoming: GraphIdMapping) -> GraphIdMapping:
    if (
        existing.target_key != incoming.target_key
        or existing.caveat != incoming.caveat
        or existing.confidence != incoming.confidence
    ):
        raise ValueError(
            f"conflicting id mapping: {existing.system}:{existing.external_id}:{existing.status}"
        )
    return GraphIdMapping(
        system=existing.system,
        external_id=existing.external_id,
        target_key=existing.target_key,
        source_refs=tuple(sorted(set(existing.source_refs) | set(incoming.source_refs))),
        status=existing.status,
        caveat=existing.caveat,
        confidence=existing.confidence,
    )


def _normalized_token(value: str) -> str:
    return _required_text(value, "token").casefold().replace(" ", "_")


def _normalized_fact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {_normalized_token(str(key)): value for key, value in mapping.items()}


def _stable_text_token(value: str) -> str:
    text = _required_text(value, "text token")
    slug = "".join(char if char.isalnum() else "_" for char in text.casefold()).strip("_")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return f"{slug[:48] or 'text'}_{digest}"


def _edge_sort_key(edge: GraphEdge) -> tuple[str, str, str, tuple[str, ...]]:
    return (edge.edge_type, edge.source_key, edge.target_key, edge.evidence_refs)


def _required_text(value: str, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _required_tuple(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    normalized = tuple(_required_text(value, label) for value in values)
    if not normalized:
        raise ValueError(f"{label} must include at least one source")
    return normalized


def _confidence(value: float) -> float:
    confidence = float(value)
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


def _fact_status(value: str) -> str:
    status = _required_text(value, "fact status")
    if status not in FACT_STATUSES:
        raise ValueError(f"invalid fact status: {status}")
    return status


def _reject_duplicate_texts(values: object, label: str) -> None:
    seen: set[str] = set()
    for value in values:
        text = _required_text(value, label)
        if text in seen:
            raise ValueError(f"duplicate {label}: {text}")
        seen.add(text)


def _ensure_sources_exist(source_refs: tuple[str, ...], source_ids: set[str], label: str) -> None:
    missing = sorted(set(source_refs) - source_ids)
    if missing:
        raise ValueError(f"{label} references unknown source {missing[0]!r}")


def _ensure_node_exists(node_key: str, node_keys: set[str], label: str) -> None:
    if node_key not in node_keys:
        raise ValueError(f"{label} references unknown node {node_key!r}")


def _ensure_snapshot_index_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshot_index (
            snapshot_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            snapshot_path TEXT NOT NULL,
            node_count INTEGER NOT NULL,
            edge_count INTEGER NOT NULL,
            source_count INTEGER NOT NULL,
            is_latest INTEGER NOT NULL CHECK (is_latest IN (0, 1))
        )
        """
    )


DEFAULT_SOURCE_INVENTORY_SPECS: tuple[SourceInventorySpec, ...] = (
    SourceInventorySpec(
        source_id="repoe:ascendancies",
        kind="repoe_raw",
        relative_path="ascendancies.min.json",
        schema_version="repoe_min_json_v1",
    ),
    SourceInventorySpec(
        source_id="repoe:base_items",
        kind="repoe_raw",
        relative_path="base_items.min.json",
        schema_version="repoe_min_json_v1",
    ),
    SourceInventorySpec(
        source_id="repoe:mods",
        kind="repoe_raw",
        relative_path="mods.min.json",
        schema_version="repoe_min_json_v1",
    ),
    SourceInventorySpec(
        source_id="repoe:skill_gems",
        kind="repoe_raw",
        relative_path="skill_gems.min.json",
        schema_version="repoe_min_json_v1",
    ),
    SourceInventorySpec(
        source_id="repoe:skills",
        kind="repoe_raw",
        relative_path="skills.min.json",
        schema_version="repoe_min_json_v1",
    ),
    SourceInventorySpec(
        source_id="ggg:developer_docs:inventories",
        kind="official_docs_fixture",
        relative_path="official/inventories.min.json",
        schema_version="phase2_fixture_v1",
        claims=(
            SourceClaim("build_planner_field", "BuildInventorySlot.inventory_id"),
            SourceClaim("source_scope", "official_doc_examples"),
        ),
        source_url="https://www.pathofexile.com/developer/docs/game",
        confidence=0.85,
    ),
)
