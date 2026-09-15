from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess

import pytest

from server.knowledge import physical_graph as pg


def _source() -> pg.GraphSource:
    return pg.GraphSource(
        source_id="repoe:skill_gems",
        kind="repoe_raw",
        source_file="data/raw/skill_gems.min.json",
        claims=(
            pg.SourceClaim("passive_tree_version", "not_applicable"),
            pg.SourceClaim("pob_commit", "unknown"),
        ),
        expected_count=1200,
        confidence=0.8,
    )


def test_pinned_pob_minion_payload_types_are_endpoint_scoped(tmp_path: Path):
    source = pg.GraphSource(
        source_id="pob:skill_payload_types",
        kind="pinned_pob_skill_payload_types",
        source_file="Data/Skills/fixture.lua",
    )
    lua = tmp_path / "fixture.lua"
    lua.write_text(
        '''skills["SummonFixturePlayer"] = {
\tname = "Fixture Minion",
\tskillTypes = { [SkillType.Minion] = true, [SkillType.CreatesMinion] = true, },
\tminionSkillTypes = { [SkillType.Attack] = true, [SkillType.Damage] = true, },
}
skills["OrdinaryPlayer"] = {
\tname = "Ordinary",
\tskillTypes = { [SkillType.Attack] = true, },
}
''',
        encoding="utf-8",
    )

    result = pg.ingest_pob_minion_payload_types(
        [lua],
        source=source,
        known_skill_keys={"skill:SummonFixturePlayer", "skill:OrdinaryPlayer"},
    )

    assert len(result.requirement_facts) == 1
    fact = result.requirement_facts[0]
    assert fact.component_key == "skill:SummonFixturePlayer"
    assert fact.level_or_stage == "minion_payload_types"
    assert fact.requirements == {
        "endpoint_kind": "minion_payload",
        "skill_types": ["Attack", "Damage"],
    }


def test_support_candidate_requires_pinned_minion_flags_without_widening_summon():
    source = _source()
    skill_key = "skill:SummonFixturePlayer"
    support_key = "support:FixtureAttackSupport"
    contract_key = "skill:FixtureAttackSupportContract"
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(
            pg.GraphNode(skill_key, "active_skill", "Fixture Minion", (source.source_id,)),
            pg.GraphNode(support_key, "support_gem", "Attack Support", (source.source_id,)),
            pg.GraphNode(contract_key, "active_skill", "Attack Contract", (source.source_id,)),
            pg.GraphNode("skill_type:minion", "skill_type", "Minion", (source.source_id,)),
        ),
        edges=(
            pg.GraphEdge("has_type", skill_key, "skill_type:minion", (source.source_id,)),
            pg.GraphEdge("grants_skill", support_key, contract_key, (source.source_id,)),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key=contract_key,
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Attack"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=skill_key,
                level_or_stage="minion_payload_types",
                requirements={
                    "endpoint_kind": "minion_payload",
                    "skill_types": ["Attack", "Damage"],
                },
                source_refs=(source.source_id,),
            ),
        ),
    )

    active = pg.support_skill_candidate(
        snapshot=snapshot,
        support_key=support_key,
        skill_key=skill_key,
    )
    payload = pg.support_skill_candidate(
        snapshot=snapshot,
        support_key=support_key,
        skill_key=skill_key,
        endpoint_kind="minion_payload",
    )

    assert active.status == "unknown"
    assert active.facts["endpoint_kind"] == "active_skill"
    assert active.facts["excluded_reason"] == "minion_support_flags_unavailable"
    assert payload.status == "unknown"
    assert payload.facts["endpoint_kind"] == "minion_payload"
    assert payload.facts["host_skill_types"] == ["minion"]
    assert payload.facts["minion_skill_types"] == ["attack", "damage"]


def test_source_claims_preserve_unknown_and_not_applicable_without_fake_versions():
    source = _source()

    assert source.claim("passive_tree_version") == "not_applicable"
    assert source.claim("pob_commit") == "unknown"
    assert source.claim("game_patch") is None
    assert source.confidence == 0.8


def test_graph_node_requires_namespaced_stable_key_and_source_ref():
    source = _source()

    node = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )

    assert node.namespace == "gem"
    assert node.display_name == "Lightning Arrow"

    with pytest.raises(ValueError, match="namespaced"):
        pg.GraphNode(
            stable_key="Lightning Arrow",
            node_type="skill_gem",
            display_name="Lightning Arrow",
            source_refs=(source.source_id,),
        )

    with pytest.raises(ValueError, match="source"):
        pg.GraphNode(
            stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
            node_type="skill_gem",
            display_name="Lightning Arrow",
            source_refs=(),
        )


def test_snapshot_rejects_orphan_edges_and_unknown_edge_types():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )

    pg.GraphSnapshot(
        snapshot_id="physical-graph-test",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        sources=(source,),
        nodes=(gem, skill),
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=gem.stable_key,
                target_key=skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
    )

    with pytest.raises(ValueError, match="unknown edge type"):
        pg.GraphSnapshot(
            snapshot_id="bad-edge-type",
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
            sources=(source,),
            nodes=(gem, skill),
            edges=(
                pg.GraphEdge(
                    edge_type="invented_synergy",
                    source_key=gem.stable_key,
                    target_key=skill.stable_key,
                    evidence_refs=(source.source_id,),
                ),
            ),
        )

    with pytest.raises(ValueError, match="orphan"):
        pg.GraphSnapshot(
            snapshot_id="orphan-edge",
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
            sources=(source,),
            nodes=(gem,),
            edges=(
                pg.GraphEdge(
                    edge_type="grants_skill",
                    source_key=gem.stable_key,
                    target_key=skill.stable_key,
                    evidence_refs=(source.source_id,),
                ),
            ),
        )


def test_build_snapshot_is_deterministic_for_same_inputs():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    edge = pg.GraphEdge(
        edge_type="grants_skill",
        source_key=gem.stable_key,
        target_key=skill.stable_key,
        evidence_refs=(source.source_id,),
    )

    first = pg.build_snapshot(sources=(source,), nodes=(gem, skill), edges=(edge,))
    second = pg.build_snapshot(sources=(source,), nodes=(skill, gem), edges=(edge,))

    assert first.snapshot_id == second.snapshot_id
    assert [node.stable_key for node in first.nodes] == [
        "gem:Metadata/Items/Gems/SkillGemLightningArrow",
        "skill:LightningArrowPlayer",
    ]


def test_snapshot_validates_alias_mapping_capability_and_fact_contract_refs():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    passive = pg.GraphNode(
        stable_key="passive:ggg:12345",
        node_type="passive",
        display_name="Dexterity",
        source_refs=(source.source_id,),
    )
    alias = pg.GraphAlias(
        alias="Lightning Arrow",
        target_key=gem.stable_key,
        source_refs=(source.source_id,),
    )
    id_mapping = pg.GraphIdMapping(
        system="ggg:SkillGems",
        external_id="Metadata/Items/Gems/SkillGemLightningArrow",
        target_key=gem.stable_key,
        source_refs=(source.source_id,),
    )
    capability = pg.GraphCapability(
        node_key=gem.stable_key,
        capability="build_planner_export",
        status="requires_phase6_mapping",
        source_refs=(source.source_id,),
    )
    requirement = pg.RequirementFact(
        component_key=gem.stable_key,
        level_or_stage="gem_level_20",
        requirements={"level": 70, "dex": 155},
        source_refs=(source.source_id,),
    )
    resource = pg.ResourceFact(
        component_key=gem.stable_key,
        level_or_stage="gem_level_1",
        costs={"mana": 6},
        reservations={},
        source_refs=(source.source_id,),
    )
    passive_choice = pg.PassiveChoice(
        choice_key="passive_choice:passive:ggg:12345:attribute",
        parent_passive_key=passive.stable_key,
        display_name="Attribute choice",
        source_refs=(source.source_id,),
    )
    allocation_option = pg.AllocationOption(
        option_key="allocation_option:passive:ggg:12345:dex",
        choice_key=passive_choice.choice_key,
        display_name="Dexterity",
        stat_text="+5 to Dexterity",
        source_refs=(source.source_id,),
        allocation_states=("normal", "weapon_set_1"),
    )
    computed = pg.ComputedFactResult(
        request=pg.ComputedFactRequest(
            fact_type="requirements_for_component",
            inputs={"component_key": gem.stable_key, "level_or_stage": "gem_level_20"},
        ),
        status="known",
        facts={"requirements": {"level": 70, "dex": 155}},
        source_refs=(source.source_id,),
    )

    snapshot = pg.GraphSnapshot(
        snapshot_id="contract-slice-2",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        sources=(source,),
        nodes=(gem, passive),
        edges=(),
        aliases=(alias,),
        id_mappings=(id_mapping,),
        capabilities=(capability,),
        requirement_facts=(requirement,),
        resource_facts=(resource,),
        passive_choices=(passive_choice,),
        allocation_options=(allocation_option,),
        computed_results=(computed,),
    )

    assert snapshot.aliases[0].normalized_alias == "lightning arrow"
    assert snapshot.id_mappings[0].status == "resolved"
    assert snapshot.capabilities[0].status == "requires_phase6_mapping"
    assert snapshot.allocation_options[0].allocation_states == ("normal", "weapon_set_1")


def test_merge_ingestion_results_rejects_conflicting_id_mappings():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    first = pg.GraphIngestionResult(
        nodes=(gem,),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:shared_id",
                external_id="LightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
    )
    second = pg.GraphIngestionResult(
        nodes=(skill,),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:shared_id",
                external_id="LightningArrow",
                target_key=skill.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
    )

    with pytest.raises(ValueError, match="conflicting id mapping"):
        pg.merge_ingestion_results(first, second)


def test_contracts_reject_invalid_resolution_status_and_allocation_state():
    source = _source()

    with pytest.raises(ValueError, match="resolution status"):
        pg.GraphIdMapping(
            system="ggg:SkillGems",
            external_id="Metadata/Items/Gems/SkillGemLightningArrow",
            target_key=None,
            status="maybe",
            source_refs=(source.source_id,),
        )

    with pytest.raises(ValueError, match="allocation state"):
        pg.AllocationOption(
            option_key="allocation_option:passive:ggg:12345:dex",
            choice_key="passive_choice:passive:ggg:12345:attribute",
            display_name="Dexterity",
            stat_text="+5 to Dexterity",
            source_refs=(source.source_id,),
            allocation_states=("weapon_set_3",),
        )


def test_build_source_inventory_counts_raw_json_sources_and_preserves_conservative_claims(
    tmp_path,
):
    (tmp_path / "skill_gems.min.json").write_text(
        json.dumps({"SkillGemLightningArrow": {}, "SupportGemPierce": {}}),
        encoding="utf-8",
    )
    (tmp_path / "mods.min.json").write_text(
        json.dumps({"LightningDamage1": {}}),
        encoding="utf-8",
    )
    specs = (
        pg.SourceInventorySpec(
            source_id="repoe:skill_gems",
            kind="repoe_raw",
            relative_path="skill_gems.min.json",
            schema_version="repoe_min_json_v1",
        ),
        pg.SourceInventorySpec(
            source_id="repoe:mods",
            kind="repoe_raw",
            relative_path="mods.min.json",
            schema_version="repoe_min_json_v1",
        ),
    )

    inventory = pg.build_source_inventory(raw_data_dir=tmp_path, specs=specs)

    assert [source.source_id for source in inventory] == ["repoe:mods", "repoe:skill_gems"]
    assert inventory[0].expected_count == 1
    assert inventory[1].expected_count == 2
    assert inventory[1].claim("game_patch") == "unknown"
    assert inventory[1].claim("passive_tree_version") == "not_applicable"
    assert inventory[1].claim("pob_commit") == "not_applicable"
    assert inventory[1].claim("freshness_status") == "unknown"


def test_build_source_inventory_rejects_missing_sources_unless_explicitly_allowed(tmp_path):
    specs = (
        pg.SourceInventorySpec(
            source_id="repoe:skill_gems",
            kind="repoe_raw",
            relative_path="skill_gems.min.json",
            schema_version="repoe_min_json_v1",
        ),
    )

    with pytest.raises(FileNotFoundError, match="skill_gems.min.json"):
        pg.build_source_inventory(raw_data_dir=tmp_path, specs=specs)

    inventory = pg.build_source_inventory(
        raw_data_dir=tmp_path,
        specs=specs,
        include_missing=True,
    )

    assert inventory[0].expected_count == 0
    assert inventory[0].claim("freshness_status") == "missing"
    assert inventory[0].confidence == 0.0


def test_default_source_inventory_includes_official_inventory_fixture():
    repo_root = Path(__file__).resolve().parents[1]
    raw_data_dir = repo_root / "data/raw"
    official_fixture = raw_data_dir / "official/inventories.min.json"

    inventory = pg.build_source_inventory(
        raw_data_dir=raw_data_dir,
        specs=(
            pg.SourceInventorySpec(
                source_id="ggg:developer_docs:inventories",
                kind="official_docs_fixture",
                relative_path=official_fixture.relative_to(raw_data_dir).as_posix(),
                schema_version="official_developer_docs_examples_v1",
                source_url="https://www.pathofexile.com/developer/docs/game",
                claims=(
                    pg.SourceClaim(
                        "build_planner_field",
                        "BuildInventorySlot.inventory_id",
                    ),
                    pg.SourceClaim("source_scope", "official_doc_examples"),
                ),
            ),
        ),
    )
    by_id = {source.source_id: source for source in inventory}

    assert "ggg:developer_docs:inventories" in by_id
    source = by_id["ggg:developer_docs:inventories"]
    assert source.expected_count == 2
    assert source.claim("source_scope") == "official_doc_examples"
    assert source.source_url == "https://www.pathofexile.com/developer/docs/game"


def test_ingest_skill_gem_source_builds_source_backed_nodes_and_edges(tmp_path):
    source_file = tmp_path / "skill_gems.min.json"
    source_file.write_text(
        json.dumps(
            {
                "Metadata/Items/Gems/SkillGemLightningArrow": {
                    "base_item": {
                        "display_name": "Lightning Arrow",
                        "id": "Metadata/Items/Gems/SkillGemLightningArrow",
                    },
                    "gem_type": "active",
                    "grants_skills": ["LightningArrowPlayer"],
                    "recommended_supports": ["Metadata/Items/Gems/SupportGemPierce"],
                    "tags": ["attack", "projectile", "lightning"],
                },
                "Metadata/Items/Gems/SupportGemPierce": {
                    "base_item": {
                        "display_name": "Pierce",
                        "id": "Metadata/Items/Gems/SupportGemPierce",
                    },
                    "gem_type": "support",
                    "grants_skills": ["SupportPiercePlayer"],
                    "tags": ["support", "projectile"],
                },
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="repoe:skill_gems",
        kind="repoe_raw",
        source_file="skill_gems.min.json",
        claims=(pg.SourceClaim("freshness_status", "unknown"),),
        expected_count=2,
    )

    ingestion = pg.ingest_skill_gems(source_file, source=source)
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=ingestion.nodes,
        edges=ingestion.edges,
        aliases=ingestion.aliases,
        id_mappings=ingestion.id_mappings,
    )

    node_keys = {node.stable_key for node in snapshot.nodes}
    edge_types = {(edge.edge_type, edge.source_key, edge.target_key) for edge in snapshot.edges}

    assert "gem:Metadata/Items/Gems/SkillGemLightningArrow" in node_keys
    assert "support:Metadata/Items/Gems/SupportGemPierce" in node_keys
    assert "skill:LightningArrowPlayer" in node_keys
    assert "tag:gem:projectile" in node_keys
    assert (
        "grants_skill",
        "gem:Metadata/Items/Gems/SkillGemLightningArrow",
        "skill:LightningArrowPlayer",
    ) in edge_types
    assert (
        "recommended_for",
        "support:Metadata/Items/Gems/SupportGemPierce",
        "gem:Metadata/Items/Gems/SkillGemLightningArrow",
    ) in edge_types
    assert not any(edge.edge_type == "compatible_with" for edge in snapshot.edges)
    assert snapshot.aliases[0].source_refs == (source.source_id,)
    assert any(mapping.system == "repoe:gem_metadata" for mapping in snapshot.id_mappings)


def test_ingest_skill_gems_skips_non_support_recommended_refs_without_dangling_edges(
    tmp_path,
):
    source_file = tmp_path / "skill_gems.min.json"
    source_file.write_text(
        json.dumps(
            {
                "Metadata/Items/Gems/SkillGemCrushingFear": {
                    "base_item": {"display_name": "Crushing Fear"},
                    "gem_type": "active",
                    "grants_skills": ["CrushingFearPlayer"],
                    "recommended_supports": ["Metadata/Items/Gem/SkillGemManaDrain"],
                    "tags": ["attack"],
                },
                "Metadata/Items/Gem/SkillGemManaDrain": {
                    "base_item": {"display_name": "Mana Drain"},
                    "gem_type": "active",
                    "grants_skills": ["ManaDrainPlayer"],
                    "tags": ["spell"],
                },
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="repoe:skill_gems",
        kind="repoe_raw",
        source_file="skill_gems.min.json",
        expected_count=2,
    )

    ingestion = pg.ingest_skill_gems(source_file, source=source)
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=ingestion.nodes,
        edges=ingestion.edges,
        aliases=ingestion.aliases,
        id_mappings=ingestion.id_mappings,
    )

    assert "gem:Metadata/Items/Gem/SkillGemManaDrain" in {
        node.stable_key for node in snapshot.nodes
    }
    assert not any(edge.edge_type == "recommended_for" for edge in snapshot.edges)


def test_ingest_base_items_and_mods_support_computed_can_roll_without_can_roll_edges(
    tmp_path,
):
    base_file = tmp_path / "base_items.min.json"
    base_file.write_text(
        json.dumps(
            {
                "Metadata/Items/Weapons/Bows/Bow1": {
                    "name": "Shortbow",
                    "item_class": "Bow",
                    "domain": "item",
                    "drop_level": 1,
                    "tags": ["bow", "weapon", "default"],
                    "requirements": {"level": 1, "dexterity": 0, "strength": 0},
                },
                "Metadata/Items/Weapons/Swords/Sword1": {
                    "name": "Shortsword",
                    "item_class": "One Hand Sword",
                    "domain": "item",
                    "drop_level": 1,
                    "tags": ["sword", "weapon", "default"],
                    "requirements": {"level": 1, "dexterity": 0, "strength": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    mod_file = tmp_path / "mods.min.json"
    mod_file.write_text(
        json.dumps(
            {
                "LightningDamage1": {
                    "name": "Crackling",
                    "domain": "item",
                    "generation_type": "prefix",
                    "groups": ["LightningDamage"],
                    "required_level": 10,
                    "spawn_weights": [
                        {"tag": "bow", "weight": 1},
                        {"tag": "default", "weight": 0},
                    ],
                    "text": "Adds (1-4) to (5-8) [Lightning|Lightning] Damage",
                }
            }
        ),
        encoding="utf-8",
    )
    base_source = pg.GraphSource(
        source_id="repoe:base_items",
        kind="repoe_raw",
        source_file="base_items.min.json",
        expected_count=2,
    )
    mod_source = pg.GraphSource(
        source_id="repoe:mods",
        kind="repoe_raw",
        source_file="mods.min.json",
        expected_count=1,
    )

    base_ingestion = pg.ingest_base_items(base_file, source=base_source)
    mod_ingestion = pg.ingest_mods(mod_file, source=mod_source)
    merged = pg.merge_ingestion_results(base_ingestion, mod_ingestion)
    snapshot = pg.build_snapshot(
        sources=(base_source, mod_source),
        nodes=merged.nodes,
        edges=merged.edges,
        aliases=base_ingestion.aliases,
        id_mappings=merged.id_mappings,
        requirement_facts=merged.requirement_facts,
    )

    node_keys = {node.stable_key for node in snapshot.nodes}
    edge_types = {(edge.edge_type, edge.source_key, edge.target_key) for edge in snapshot.edges}

    assert "item_base:Metadata/Items/Weapons/Bows/Bow1" in node_keys
    assert "mod:LightningDamage1" in node_keys
    assert "tag:item:bow" in node_keys
    assert "item_class:bow" in node_keys
    assert (
        "has_tag",
        "item_base:Metadata/Items/Weapons/Bows/Bow1",
        "tag:item:bow",
    ) in edge_types
    assert ("applies_to_tag", "mod:LightningDamage1", "tag:item:bow") in edge_types
    assert not any(edge.edge_type == "can_roll" for edge in snapshot.edges)

    positive = pg.can_roll_mod(
        snapshot=snapshot,
        base_item_key="item_base:Metadata/Items/Weapons/Bows/Bow1",
        mod_key="mod:LightningDamage1",
        item_level=12,
    )
    low_level = pg.can_roll_mod(
        snapshot=snapshot,
        base_item_key="item_base:Metadata/Items/Weapons/Bows/Bow1",
        mod_key="mod:LightningDamage1",
        item_level=5,
    )
    tag_mismatch = pg.can_roll_mod(
        snapshot=snapshot,
        base_item_key="item_base:Metadata/Items/Weapons/Swords/Sword1",
        mod_key="mod:LightningDamage1",
        item_level=12,
    )

    assert positive.status == "known"
    assert positive.facts["can_roll"] is True
    assert positive.facts["required_level"] == 10
    assert positive.facts["matching_tags"] == ["bow"]
    assert low_level.facts["can_roll"] is False
    assert low_level.facts["excluded_reason"] == "item_level_too_low"
    assert tag_mismatch.facts["can_roll"] is False
    assert tag_mismatch.facts["excluded_reason"] == "tag_mismatch"
    assert positive.facts["base_domain"] == "item"
    assert positive.facts["mod_domain"] == "item"
    assert positive.facts["generation_type"] == "prefix"


def test_can_roll_mod_rejects_known_domain_mismatch(tmp_path):
    base_file = tmp_path / "base_items.min.json"
    base_file.write_text(
        json.dumps(
            {
                "Metadata/Items/Weapons/Bows/Bow1": {
                    "name": "Shortbow",
                    "item_class": "Bow",
                    "domain": "item",
                    "drop_level": 1,
                    "tags": ["bow"],
                    "requirements": {"level": 1},
                }
            }
        ),
        encoding="utf-8",
    )
    mod_file = tmp_path / "mods.min.json"
    mod_file.write_text(
        json.dumps(
            {
                "AreaOnlyMod": {
                    "name": "Area Only",
                    "domain": "area",
                    "generation_type": "suffix",
                    "groups": ["Area"],
                    "required_level": 1,
                    "spawn_weights": [{"tag": "bow", "weight": 1}],
                    "text": "Area-only modifier",
                }
            }
        ),
        encoding="utf-8",
    )
    base_source = pg.GraphSource(
        source_id="repoe:base_items",
        kind="repoe_raw",
        source_file="base_items.min.json",
        expected_count=1,
    )
    mod_source = pg.GraphSource(
        source_id="repoe:mods",
        kind="repoe_raw",
        source_file="mods.min.json",
        expected_count=1,
    )
    base_ingestion = pg.ingest_base_items(base_file, source=base_source)
    mod_ingestion = pg.ingest_mods(mod_file, source=mod_source)
    merged = pg.merge_ingestion_results(base_ingestion, mod_ingestion)
    snapshot = pg.build_snapshot(
        sources=(base_source, mod_source),
        nodes=merged.nodes,
        edges=merged.edges,
        aliases=merged.aliases,
        id_mappings=merged.id_mappings,
        requirement_facts=merged.requirement_facts,
    )

    result = pg.can_roll_mod(
        snapshot=snapshot,
        base_item_key="item_base:Metadata/Items/Weapons/Bows/Bow1",
        mod_key="mod:AreaOnlyMod",
        item_level=82,
    )

    assert result.status == "known"
    assert result.facts["can_roll"] is False
    assert result.facts["excluded_reason"] == "domain_mismatch"
    assert result.facts["base_domain"] == "item"
    assert result.facts["mod_domain"] == "area"


def test_can_roll_mod_reports_ambiguous_when_required_roll_constraints_are_missing():
    source = _source()
    base_item = pg.GraphNode(
        stable_key="item_base:Metadata/Items/Weapons/Bows/Bow1",
        node_type="item_base",
        display_name="Shortbow",
        source_refs=(source.source_id,),
    )
    mod = pg.GraphNode(
        stable_key="mod:LightningDamage1",
        node_type="mod",
        display_name="Crackling",
        source_refs=(source.source_id,),
    )
    tag = pg.GraphNode(
        stable_key="tag:item:bow",
        node_type="item_tag",
        display_name="bow",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(base_item, mod, tag),
        edges=(
            pg.GraphEdge(
                edge_type="has_tag",
                source_key=base_item.stable_key,
                target_key=tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="applies_to_tag",
                source_key=mod.stable_key,
                target_key=tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key=mod.stable_key,
                level_or_stage="base",
                requirements={
                    "required_level": 1,
                    "groups": ["LightningDamage"],
                    "text": "Adds Lightning Damage",
                },
                source_refs=(source.source_id,),
            ),
        ),
    )

    result = pg.can_roll_mod(
        snapshot=snapshot,
        base_item_key=base_item.stable_key,
        mod_key=mod.stable_key,
        item_level=82,
    )

    assert result.status == "ambiguous"
    assert result.facts["can_roll"] is None
    assert result.caveat == "incomplete_mod_roll_constraints"
    assert result.facts["missing_constraints"] == ["base_domain", "generation_type", "mod_domain"]


def test_snapshot_store_round_trips_and_resolves_alias_with_source_explain(tmp_path):
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    alias = pg.GraphAlias(
        alias="Lightning Arrow",
        target_key=gem.stable_key,
        source_refs=(source.source_id,),
    )
    mapping = pg.GraphIdMapping(
        system="repoe:gem_metadata",
        external_id="Metadata/Items/Gems/SkillGemLightningArrow",
        target_key=gem.stable_key,
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem,),
        edges=(),
        aliases=(alias,),
        id_mappings=(mapping,),
    )
    snapshot_file = tmp_path / "physical_graph_snapshot.json"

    pg.save_snapshot(snapshot, snapshot_file)
    loaded = pg.load_snapshot(snapshot_file)
    resolved = pg.resolve_node(loaded, "Lightning Arrow")
    explained = pg.explain_sources(loaded, gem.stable_key)

    assert loaded.snapshot_id == snapshot.snapshot_id
    assert resolved == gem.stable_key
    assert explained[0]["source_id"] == source.source_id
    assert explained[0]["source_file"] == source.source_file


def test_resolve_node_reports_ambiguous_and_missing_aliases():
    source = _source()
    first = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    second = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(first, second),
        edges=(),
        aliases=(
            pg.GraphAlias("Lightning Arrow", first.stable_key, (source.source_id,)),
            pg.GraphAlias("Lightning Arrow", second.stable_key, (source.source_id,)),
        ),
    )

    with pytest.raises(ValueError, match="ambiguous"):
        pg.resolve_node(snapshot, "Lightning Arrow")

    with pytest.raises(ValueError, match="missing"):
        pg.resolve_node(snapshot, "Unknown Gem")


def test_snapshot_sqlite_index_registers_and_lists_snapshots(tmp_path):
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(sources=(source,), nodes=(gem,), edges=())
    snapshot_file = tmp_path / "snapshot.json"
    index_file = tmp_path / "physical_graph.sqlite"

    pg.save_snapshot(snapshot, snapshot_file)
    pg.register_snapshot(index_file, snapshot, snapshot_file)
    rows = pg.list_registered_snapshots(index_file)

    assert rows[0]["snapshot_id"] == snapshot.snapshot_id
    assert rows[0]["snapshot_path"] == str(snapshot_file)
    assert rows[0]["is_latest"] is True


def test_load_latest_snapshot_from_index_round_trips_json_snapshot(tmp_path):
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    older = pg.GraphSnapshot(
        snapshot_id="physical-graph-older",
        created_at=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        sources=(source,),
        nodes=(gem,),
        edges=(),
        aliases=(pg.GraphAlias("Lightning Arrow", gem.stable_key, (source.source_id,)),),
    )
    newer = pg.GraphSnapshot(
        snapshot_id="physical-graph-newer",
        created_at=datetime(2026, 7, 1, 1, 0, tzinfo=UTC),
        sources=(source,),
        nodes=(gem,),
        edges=(),
        aliases=(pg.GraphAlias("Lightning Arrow", gem.stable_key, (source.source_id,)),),
    )
    older_file = tmp_path / "older.json"
    newer_file = tmp_path / "newer.json"
    index_file = tmp_path / "physical_graph.sqlite"

    pg.save_snapshot(older, older_file)
    pg.save_snapshot(newer, newer_file)
    pg.register_snapshot(index_file, older, older_file)
    pg.register_snapshot(index_file, newer, newer_file)
    loaded = pg.load_latest_snapshot(index_file)

    assert loaded.snapshot_id == "physical-graph-newer"
    assert pg.resolve_node(loaded, "Lightning Arrow") == gem.stable_key


def test_resolve_candidates_reports_resolved_ambiguous_and_missing_states():
    source = _source()
    first = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    second = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    mapping = pg.GraphIdMapping(
        system="repoe:gem_metadata",
        external_id="Metadata/Items/Gems/SkillGemLightningArrow",
        target_key=first.stable_key,
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(first, second),
        edges=(),
        aliases=(
            pg.GraphAlias("Lightning Arrow", first.stable_key, (source.source_id,)),
            pg.GraphAlias("Lightning Arrow", second.stable_key, (source.source_id,)),
        ),
        id_mappings=(mapping,),
    )

    resolved = pg.resolve_candidates(snapshot, "Metadata/Items/Gems/SkillGemLightningArrow")
    ambiguous = pg.resolve_candidates(snapshot, "Lightning Arrow")
    missing = pg.resolve_candidates(snapshot, "Unknown Gem")

    assert resolved["status"] == "resolved"
    assert resolved["resolved_key"] == first.stable_key
    assert ambiguous["status"] == "ambiguous"
    assert sorted(ambiguous["candidate_keys"]) == sorted([first.stable_key, second.stable_key])
    assert missing["status"] == "missing"
    assert missing["candidate_keys"] == []


def test_alias_collision_report_groups_normalized_alias_conflicts():
    source = _source()
    first = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    second = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(first, second),
        edges=(),
        aliases=(
            pg.GraphAlias("Lightning Arrow", first.stable_key, (source.source_id,)),
            pg.GraphAlias("  lightning   arrow  ", second.stable_key, (source.source_id,)),
        ),
    )

    collisions = pg.alias_collision_report(snapshot)

    assert collisions == [
        {
            "normalized_alias": "lightning arrow",
            "candidate_keys": sorted([first.stable_key, second.stable_key]),
        }
    ]


def test_build_component_resolver_payload_reports_supported_and_unsupported_nodes():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    unsupported = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem, support, unsupported),
        edges=(),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SupportGemPierce",
                target_key=support.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
    )

    gem_payload = pg.build_component_resolver_payload(snapshot, gem.stable_key)
    support_payload = pg.build_component_resolver_payload(snapshot, support.stable_key)
    unsupported_payload = pg.build_component_resolver_payload(snapshot, unsupported.stable_key)

    assert gem_payload["status"] == "resolved"
    assert gem_payload["component_type"] == "skill_gem"
    assert gem_payload["metadata_id"] == "Metadata/Items/Gems/SkillGemLightningArrow"
    assert gem_payload["export_status"] == "exportable"
    assert gem_payload["caveats"] == []
    assert support_payload["status"] == "resolved"
    assert support_payload["component_type"] == "support_gem"
    assert support_payload["metadata_id"] == "Metadata/Items/Gems/SupportGemPierce"
    assert support_payload["export_status"] == "exportable"
    assert support_payload["caveats"] == []
    assert unsupported_payload["status"] == "unsupported"
    assert unsupported_payload["reason"] == "node_type_not_export_ready"
    assert unsupported_payload["export_status"] == "unsupported"
    assert unsupported_payload["caveats"] == ["node_type_not_export_ready"]


def test_build_component_resolver_export_reports_bulk_statuses():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    unsupported = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem, support, unsupported),
        edges=(),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SupportGemPierce",
                target_key=support.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
    )

    report = pg.build_component_resolver_export(
        snapshot,
        [
            gem.stable_key,
            support.stable_key,
            unsupported.stable_key,
            "gem:Missing",
        ],
    )

    assert report["resolved_count"] == 2
    assert report["unsupported_count"] == 1
    assert report["missing_count"] == 1
    assert report["entries"][0]["node_key"] == gem.stable_key
    assert report["entries"][3]["status"] == "missing"


def test_build_component_resolver_payload_reports_missing_metadata_mapping():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemUnknown",
        node_type="skill_gem",
        display_name="Unknown Gem",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem,),
        edges=(),
    )

    payload = pg.build_component_resolver_payload(snapshot, gem.stable_key)

    assert payload["status"] == "missing"
    assert payload["reason"] == "metadata_id_not_mapped"
    assert payload["export_status"] == "missing"
    assert payload["caveats"] == ["metadata_id_not_mapped"]


def test_build_component_resolver_payload_rejects_meta_gem_for_build_export():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gem/SkillGemAscendancyFireSpellOnHit",
        node_type="skill_gem",
        display_name="Fire Spell on Hit",
        source_refs=(source.source_id,),
    )
    meta_tag = pg.GraphNode(
        stable_key="tag:gem:meta",
        node_type="gem_tag",
        display_name="meta",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem, meta_tag),
        edges=(
            pg.GraphEdge(
                edge_type="has_tag",
                source_key=gem.stable_key,
                target_key=meta_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gem/SkillGemAscendancyFireSpellOnHit",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
    )

    payload = pg.build_component_resolver_payload(snapshot, gem.stable_key)

    assert payload["status"] == "unsupported"
    assert payload["reason"] == "meta_gem_not_supported"
    assert payload["export_status"] == "unsupported"
    assert payload["caveats"] == ["meta_gem_not_supported"]


def test_build_resolver_preflight_summary_aggregates_export_and_collision_counts():
    source = _source()
    first = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    second = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(first, second, support),
        edges=(),
        aliases=(
            pg.GraphAlias("Lightning Arrow", first.stable_key, (source.source_id,)),
            pg.GraphAlias("Lightning Arrow", second.stable_key, (source.source_id,)),
        ),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=first.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SupportGemPierce",
                target_key=support.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
    )

    summary = pg.build_resolver_preflight_summary(
        snapshot,
        [
            first.stable_key,
            support.stable_key,
            second.stable_key,
            "gem:Missing",
        ],
    )

    assert summary["resolved_count"] == 2
    assert summary["unsupported_count"] == 1
    assert summary["missing_count"] == 1
    assert summary["alias_collision_count"] == 1
    assert summary["ready_for_export"] is False


def test_build_fixed_resolver_e2e_report_returns_query_samples_and_summary():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem, support),
        edges=(),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SupportGemPierce",
                target_key=support.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
    )

    report = pg.build_fixed_resolver_e2e_report(
        snapshot,
        [
            gem.stable_key,
            support.stable_key,
            "gem:Missing",
        ],
    )

    assert report["sample_count"] == 3
    assert report["summary"]["resolved_count"] == 2
    assert report["summary"]["missing_count"] == 1
    assert report["samples"][0]["query"] == gem.stable_key
    assert report["samples"][2]["result"]["status"] == "missing"


def test_resolve_id_mapping_reports_resolved_unsupported_and_missing_states():
    source = _source()
    passive = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Attribute",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(passive,),
        edges=(),
        id_mappings=(
            pg.GraphIdMapping(
                system="pob:passive_skill_node_id",
                external_id="32183",
                target_key=passive.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:PassiveSkills",
                external_id="strength89",
                target_key=None,
                source_refs=(source.source_id,),
                status="unsupported",
                caveat="official_passive_string_id_not_vendored",
            ),
        ),
    )

    resolved = pg.resolve_id_mapping(snapshot, "pob:passive_skill_node_id", "32183")
    unsupported = pg.resolve_id_mapping(snapshot, "ggg:PassiveSkills", "strength89")
    missing = pg.resolve_id_mapping(snapshot, "ggg:PassiveSkills", "missing_passive")

    assert resolved["status"] == "resolved"
    assert resolved["target_key"] == passive.stable_key
    assert unsupported["status"] == "unsupported"
    assert unsupported["caveat"] == "official_passive_string_id_not_vendored"
    assert missing["status"] == "missing"
    assert missing["target_key"] is None


def test_explain_edge_sources_reports_evidence_for_passive_connections():
    source = _source()
    first = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Shared Start",
        source_refs=(source.source_id,),
    )
    second = pg.GraphNode(
        stable_key="passive:pob:0_5:101",
        node_type="passive",
        display_name="Path Node",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(first, second),
        edges=(
            pg.GraphEdge(
                edge_type="connected_to",
                source_key=first.stable_key,
                target_key=second.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
    )

    explained = pg.explain_edge_sources(
        snapshot,
        edge_type="connected_to",
        source_key=first.stable_key,
        target_key=second.stable_key,
    )

    assert explained["status"] == "known"
    assert explained["edge_type"] == "connected_to"
    assert explained["evidence"][0]["source_id"] == source.source_id


def test_build_id_mapping_e2e_sample_reports_supported_and_unsupported_shapes():
    source = _source()
    passive = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Attribute",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(passive,),
        edges=(),
        id_mappings=(
            pg.GraphIdMapping(
                system="pob:passive_skill_node_id",
                external_id="32183",
                target_key=passive.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:PassiveSkills",
                external_id="strength89",
                target_key=None,
                source_refs=(source.source_id,),
                status="unsupported",
                caveat="official_passive_string_id_not_vendored",
            ),
        ),
    )

    supported = pg.build_id_mapping_e2e_sample(
        snapshot=snapshot,
        system="pob:passive_skill_node_id",
        external_id="32183",
    )
    unsupported = pg.build_id_mapping_e2e_sample(
        snapshot=snapshot,
        system="ggg:PassiveSkills",
        external_id="strength89",
    )

    assert supported["result"]["status"] == "resolved"
    assert supported["result"]["target_key"] == passive.stable_key
    assert unsupported["result"]["status"] == "unsupported"
    assert unsupported["result"]["caveat"] == "official_passive_string_id_not_vendored"


def test_build_edge_provenance_e2e_sample_reports_passive_connection_sources():
    source = _source()
    first = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Shared Start",
        source_refs=(source.source_id,),
    )
    second = pg.GraphNode(
        stable_key="passive:pob:0_5:101",
        node_type="passive",
        display_name="Path Node",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(first, second),
        edges=(
            pg.GraphEdge(
                edge_type="connected_to",
                source_key=first.stable_key,
                target_key=second.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
    )

    sample = pg.build_edge_provenance_e2e_sample(
        snapshot=snapshot,
        edge_type="connected_to",
        source_key=first.stable_key,
        target_key=second.stable_key,
    )

    assert sample["result"]["status"] == "known"
    assert sample["result"]["evidence"][0]["source_id"] == source.source_id


def test_fixed_sample_bundle_uses_passive_connected_to_for_edge_provenance():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    weapon = pg.GraphNode(
        stable_key="weapon_type:bow",
        node_type="weapon_type",
        display_name="Bow",
        source_refs=(source.source_id,),
    )
    passive = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Attribute",
        source_refs=(source.source_id,),
    )
    passive_neighbor = pg.GraphNode(
        stable_key="passive:pob:0_5:101",
        node_type="passive",
        display_name="Path Node",
        source_refs=(source.source_id,),
    )
    caveat = pg.GraphNode(
        stable_key="caveat:dual_weapon_state_limited_caveat",
        node_type="caveat",
        display_name="dual_weapon_state_limited_caveat",
        source_refs=(source.source_id,),
    )
    unique = pg.GraphNode(
        stable_key="unique:pob:the_anvil",
        node_type="unique",
        display_name="The Anvil",
        source_refs=(source.source_id,),
    )
    base_item = pg.GraphNode(
        stable_key="item_base:Metadata/Items/Amulets/BloodstoneAmulet",
        node_type="item_base",
        display_name="Bloodstone Amulet",
        source_refs=(source.source_id,),
    )
    mod = pg.GraphNode(
        stable_key="mod:MovementSpeed1",
        node_type="mod",
        display_name="of Movement",
        source_refs=(source.source_id,),
    )
    item_tag = pg.GraphNode(
        stable_key="tag:item:default",
        node_type="item_tag",
        display_name="default",
        source_refs=(source.source_id,),
    )
    support_skill = pg.GraphNode(
        stable_key="skill:SupportPiercePlayer",
        node_type="active_skill",
        display_name="Support Pierce",
        source_refs=(source.source_id,),
    )
    projectile_type = pg.GraphNode(
        stable_key="skill_type:projectile",
        node_type="skill_type",
        display_name="Projectile",
        source_refs=(source.source_id,),
    )
    attack_type = pg.GraphNode(
        stable_key="skill_type:attack",
        node_type="skill_type",
        display_name="Attack",
        source_refs=(source.source_id,),
    )
    inventory_slot = pg.GraphNode(
        stable_key="inventory_slot:Weapon1",
        node_type="inventory_slot",
        display_name="Weapon 1",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(
            gem,
            support,
            skill,
            weapon,
            passive,
            passive_neighbor,
            caveat,
            unique,
            base_item,
            mod,
            item_tag,
            support_skill,
            projectile_type,
            attack_type,
            inventory_slot,
        ),
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=gem.stable_key,
                target_key=skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=support.stable_key,
                target_key=support_skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="granted_by",
                source_key=skill.stable_key,
                target_key=gem.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="connected_to",
                source_key=passive.stable_key,
                target_key=passive_neighbor.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_base",
                source_key=unique.stable_key,
                target_key=base_item.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_tag",
                source_key=base_item.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="applies_to_tag",
                source_key=mod.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="requires_weapon_type",
                source_key=skill.stable_key,
                target_key=weapon.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=projectile_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=attack_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        aliases=(
            pg.GraphAlias("Lightning Arrow", gem.stable_key, (source.source_id,)),
            pg.GraphAlias("Lightning Arrow", skill.stable_key, (source.source_id,)),
        ),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SupportGemPierce",
                target_key=support.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="pob:passive_skill_node_id",
                external_id="32183",
                target_key=passive.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:PassiveSkills",
                external_id="strength89",
                target_key=None,
                source_refs=(source.source_id,),
                status="unsupported",
                caveat="official_passive_string_id_not_vendored",
            ),
            pg.GraphIdMapping(
                system="ggg:Inventories",
                external_id="Weapon1",
                target_key=inventory_slot.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:Words:UniqueName",
                external_id="The Anvil",
                target_key=unique.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key=base_item.stable_key,
                level_or_stage="base",
                requirements={"domain": "item", "drop_level": 1},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=mod.stable_key,
                level_or_stage="base",
                requirements={
                    "domain": "item",
                    "required_level": 70,
                    "generation_type": "suffix",
                    "groups": ["MovementSpeed"],
                    "text": "increased Movement Speed",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=gem.stable_key,
                level_or_stage="base",
                requirements={"level": 1, "dex": 9},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=support_skill.stable_key,
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Projectile", "Attack", "AND"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                    "added_types": [],
                    "added_minion_types": [],
                    "support_family": "Pierce",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=skill.stable_key,
                level_or_stage="socket_context",
                requirements={
                    "max_support_count": 1,
                    "socketed_support_keys": [support.stable_key],
                    "socketed_support_families": ["Pierce"],
                    "duplicate_support_policy": "reject_same_support_key",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=caveat.stable_key,
                level_or_stage="component_set",
                requirements={
                    "component_keys": [passive.stable_key, skill.stable_key],
                    "trigger_condition": "weapon_set_passives_used_without_dual_state_scores",
                    "modelability_effect": "limited",
                    "reward_eligibility_effect": "limited",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=passive.stable_key,
                level_or_stage="weapon_set_overlay",
                requirements={
                    "allocation_states": ["weapon_set_1"],
                    "weapon_set_point_conversion": 24,
                    "state_specific_reachability": True,
                },
                source_refs=(source.source_id,),
                status="ambiguous",
                confidence=0.5,
            ),
        ),
        resource_facts=(
            pg.ResourceFact(
                component_key=skill.stable_key,
                level_or_stage="1",
                costs={"mana": 6},
                reservations={},
                source_refs=(source.source_id,),
            ),
        ),
        passive_choices=(
            pg.PassiveChoice(
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                parent_passive_key=passive.stable_key,
                display_name="Attribute",
                source_refs=(source.source_id,),
            ),
        ),
        allocation_options=(
            pg.AllocationOption(
                option_key="allocation_option:passive:pob:0_5:100:26297",
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                display_name="Strength",
                stat_text="+5 to Strength",
                source_refs=(source.source_id,),
            ),
        ),
    )

    bundle = pg.build_phase2_fixed_sample_bundle(
        snapshot=snapshot,
        gem_key=gem.stable_key,
        skill_key=skill.stable_key,
        support_key=support.stable_key,
        passive_key=passive.stable_key,
        unique_key=unique.stable_key,
        caveat_key=caveat.stable_key,
    )
    edge_sample = next(
        sample for sample in bundle["samples"] if sample["family"] == "edge_provenance"
    )

    assert edge_sample["query"]["edge_type"] == "connected_to"
    assert edge_sample["query"]["source_key"] == passive.stable_key
    assert edge_sample["query"]["target_key"] == passive_neighbor.stable_key
    assert edge_sample["result"]["status"] == "known"


def test_resolve_inventory_slot_and_unique_name_mappings():
    source = _source()
    slot = pg.GraphNode(
        stable_key="inventory_slot:Weapon1",
        node_type="inventory_slot",
        display_name="Weapon 1",
        source_refs=(source.source_id,),
    )
    unique = pg.GraphNode(
        stable_key="unique:pob:the_anvil",
        node_type="unique",
        display_name="The Anvil",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(slot, unique),
        edges=(),
        id_mappings=(
            pg.GraphIdMapping(
                system="ggg:Inventories",
                external_id="Weapon1",
                target_key=slot.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:Words:UniqueName",
                external_id="The Anvil",
                target_key=unique.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
    )

    slot_result = pg.resolve_id_mapping(snapshot, "ggg:Inventories", "Weapon1")
    unique_result = pg.resolve_id_mapping(snapshot, "ggg:Words:UniqueName", "The Anvil")

    assert slot_result["status"] == "resolved"
    assert slot_result["target_key"] == slot.stable_key
    assert unique_result["status"] == "resolved"
    assert unique_result["target_key"] == unique.stable_key


def test_ingest_inventory_slots_from_official_build_planner_sample(tmp_path):
    inventory_file = tmp_path / "inventories.min.json"
    inventory_file.write_text(
        json.dumps(
            {
                "Weapon1": {
                    "display_name": "Weapon 1",
                    "build_slot": "weapon",
                    "weapon_set": 0,
                },
                "BodyArmour1": {
                    "display_name": "Body Armour",
                    "build_slot": "body_armour",
                },
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="ggg:developer_docs:inventories",
        kind="official_docs_fixture",
        source_file="data/raw/official/inventories.min.json",
        source_url="https://www.pathofexile.com/developer/docs/game",
        claims=(
            pg.SourceClaim("build_planner_field", "BuildInventorySlot.inventory_id"),
            pg.SourceClaim("source_scope", "official_doc_examples"),
        ),
        expected_count=2,
        confidence=0.85,
    )

    ingestion = pg.ingest_inventory_slots(inventory_file, source=source)
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=ingestion.nodes,
        edges=(),
        id_mappings=ingestion.id_mappings,
        requirement_facts=ingestion.requirement_facts,
    )

    assert {node.stable_key for node in ingestion.nodes} == {
        "inventory_slot:BodyArmour1",
        "inventory_slot:Weapon1",
    }
    weapon = pg.resolve_id_mapping(snapshot, "ggg:Inventories", "Weapon1")
    body = pg.resolve_id_mapping(snapshot, "ggg:Inventories", "BodyArmour1")
    requirement = pg.requirements_for_component(
        snapshot,
        "inventory_slot:Weapon1",
        level_or_stage="build_inventory_slot",
    )

    assert weapon["status"] == "resolved"
    assert weapon["target_key"] == "inventory_slot:Weapon1"
    assert body["status"] == "resolved"
    assert requirement.status == "known"
    assert requirement.facts["requirements"]["weapon_set"] == 0
    assert requirement.facts["requirements"]["build_slot"] == "weapon"


def test_passive_allocation_overlay_supports_documented_weapon_set_zero_to_two():
    source = _source()
    passive = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Weapon Set Passive",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(passive,),
        edges=(),
        requirement_facts=(
            pg.RequirementFact(
                component_key=passive.stable_key,
                level_or_stage="weapon_set_overlay",
                requirements={
                    "allocation_states": ["weapon_set_1", "weapon_set_2"],
                    "documented_weapon_set_indices": [0, 1, 2],
                    "weapon_set_point_conversion": 24,
                    "state_specific_reachability": True,
                },
                source_refs=(source.source_id,),
                status="ambiguous",
                confidence=0.5,
            ),
        ),
    )

    result = pg.passive_allocation_overlay(snapshot, passive.stable_key)

    assert result.facts["documented_weapon_set_indices"] == [0, 1, 2]


def test_build_phase2_fixed_sample_bundle_includes_inventory_and_official_id_families():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    weapon = pg.GraphNode(
        stable_key="weapon_type:bow",
        node_type="weapon_type",
        display_name="Bow",
        source_refs=(source.source_id,),
    )
    passive = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Attribute",
        source_refs=(source.source_id,),
    )
    passive_neighbor = pg.GraphNode(
        stable_key="passive:pob:0_5:101",
        node_type="passive",
        display_name="Path Node",
        source_refs=(source.source_id,),
    )
    caveat = pg.GraphNode(
        stable_key="caveat:dual_weapon_state_limited_caveat",
        node_type="caveat",
        display_name="dual_weapon_state_limited_caveat",
        source_refs=(source.source_id,),
    )
    unique = pg.GraphNode(
        stable_key="unique:pob:the_anvil",
        node_type="unique",
        display_name="The Anvil",
        source_refs=(source.source_id,),
    )
    base_item = pg.GraphNode(
        stable_key="item_base:Metadata/Items/Amulets/BloodstoneAmulet",
        node_type="item_base",
        display_name="Bloodstone Amulet",
        source_refs=(source.source_id,),
    )
    support_skill = pg.GraphNode(
        stable_key="skill:SupportPiercePlayer",
        node_type="active_skill",
        display_name="Support Pierce",
        source_refs=(source.source_id,),
    )
    projectile_type = pg.GraphNode(
        stable_key="skill_type:projectile",
        node_type="skill_type",
        display_name="Projectile",
        source_refs=(source.source_id,),
    )
    attack_type = pg.GraphNode(
        stable_key="skill_type:attack",
        node_type="skill_type",
        display_name="Attack",
        source_refs=(source.source_id,),
    )
    inventory_slot = pg.GraphNode(
        stable_key="inventory_slot:Weapon1",
        node_type="inventory_slot",
        display_name="Weapon 1",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(
            gem,
            support,
            skill,
            weapon,
            passive,
            passive_neighbor,
            caveat,
            unique,
            base_item,
            support_skill,
            projectile_type,
            attack_type,
            inventory_slot,
        ),
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=gem.stable_key,
                target_key=skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=support.stable_key,
                target_key=support_skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="granted_by",
                source_key=skill.stable_key,
                target_key=gem.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="connected_to",
                source_key=passive.stable_key,
                target_key=passive_neighbor.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_base",
                source_key=unique.stable_key,
                target_key=base_item.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="requires_weapon_type",
                source_key=skill.stable_key,
                target_key=weapon.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=projectile_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=attack_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        aliases=(
            pg.GraphAlias("Lightning Arrow", gem.stable_key, (source.source_id,)),
            pg.GraphAlias("Lightning Arrow", skill.stable_key, (source.source_id,)),
        ),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SupportGemPierce",
                target_key=support.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="pob:passive_skill_node_id",
                external_id="32183",
                target_key=passive.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:PassiveSkills",
                external_id="strength89",
                target_key=None,
                source_refs=(source.source_id,),
                status="unsupported",
                caveat="official_passive_string_id_not_vendored",
            ),
            pg.GraphIdMapping(
                system="ggg:Inventories",
                external_id="Weapon1",
                target_key=inventory_slot.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:Words:UniqueName",
                external_id="The Anvil",
                target_key=unique.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key=support_skill.stable_key,
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Projectile", "Attack", "AND"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                    "added_types": [],
                    "added_minion_types": [],
                    "support_family": "Pierce",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=skill.stable_key,
                level_or_stage="socket_context",
                requirements={
                    "max_support_count": 1,
                    "socketed_support_keys": [support.stable_key],
                    "socketed_support_families": ["Pierce"],
                    "duplicate_support_policy": "reject_same_support_key",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=caveat.stable_key,
                level_or_stage="component_set",
                requirements={
                    "component_keys": [passive.stable_key, skill.stable_key],
                    "trigger_condition": "weapon_set_passives_used_without_dual_state_scores",
                    "modelability_effect": "limited",
                    "reward_eligibility_effect": "limited",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=passive.stable_key,
                level_or_stage="weapon_set_overlay",
                requirements={
                    "allocation_states": ["weapon_set_1"],
                    "weapon_set_point_conversion": 24,
                    "state_specific_reachability": True,
                },
                source_refs=(source.source_id,),
                status="ambiguous",
                confidence=0.5,
            ),
        ),
        passive_choices=(
            pg.PassiveChoice(
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                parent_passive_key=passive.stable_key,
                display_name="Attribute",
                source_refs=(source.source_id,),
            ),
        ),
        allocation_options=(
            pg.AllocationOption(
                option_key="allocation_option:passive:pob:0_5:100:26297",
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                display_name="Strength",
                stat_text="+5 to Strength",
                source_refs=(source.source_id,),
            ),
        ),
    )

    report = pg.build_phase2_fixed_sample_bundle(
        snapshot=snapshot,
        gem_key=gem.stable_key,
        skill_key=skill.stable_key,
        support_key=support.stable_key,
        passive_key=passive.stable_key,
        unique_key=unique.stable_key,
        caveat_key=caveat.stable_key,
    )

    assert "id_mapping_supported" in report["family_counts"]
    assert "id_mapping_unsupported" in report["family_counts"]
    assert "inventory_slot_mapping" in report["family_counts"]
    assert "edge_provenance" in report["family_counts"]
    assert report["sample_count"] >= 15


def test_build_can_roll_mod_e2e_sample_reports_result_shape(tmp_path):
    base_file = tmp_path / "base_items.min.json"
    base_file.write_text(
        json.dumps(
            {
                "Metadata/Items/Weapons/Bows/Bow1": {
                    "name": "Shortbow",
                    "item_class": "Bow",
                    "domain": "item",
                    "drop_level": 1,
                    "tags": ["bow", "weapon", "default"],
                    "requirements": {"level": 1},
                }
            }
        ),
        encoding="utf-8",
    )
    mod_file = tmp_path / "mods.min.json"
    mod_file.write_text(
        json.dumps(
            {
                "LightningDamage1": {
                    "name": "Crackling",
                    "domain": "item",
                    "generation_type": "prefix",
                    "groups": ["LightningDamage"],
                    "required_level": 10,
                    "spawn_weights": [{"tag": "bow", "weight": 1}],
                    "text": "Adds Lightning Damage",
                }
            }
        ),
        encoding="utf-8",
    )
    base_source = pg.GraphSource(
        source_id="repoe:base_items",
        kind="repoe_raw",
        source_file="base_items.min.json",
        expected_count=1,
    )
    mod_source = pg.GraphSource(
        source_id="repoe:mods",
        kind="repoe_raw",
        source_file="mods.min.json",
        expected_count=1,
    )
    base_ingestion = pg.ingest_base_items(base_file, source=base_source)
    mod_ingestion = pg.ingest_mods(mod_file, source=mod_source)
    merged = pg.merge_ingestion_results(base_ingestion, mod_ingestion)
    snapshot = pg.build_snapshot(
        sources=(base_source, mod_source),
        nodes=merged.nodes,
        edges=merged.edges,
        aliases=merged.aliases,
        id_mappings=merged.id_mappings,
        requirement_facts=merged.requirement_facts,
    )

    sample = pg.build_can_roll_mod_e2e_sample(
        snapshot=snapshot,
        base_item_key="item_base:Metadata/Items/Weapons/Bows/Bow1",
        mod_key="mod:LightningDamage1",
        item_level=12,
    )

    assert sample["query"]["fact_type"] == "can_roll_mod"
    assert sample["result"]["facts"]["can_roll"] is True
    assert sample["result"]["facts"]["matching_tags"] == ["bow"]


def test_requirements_for_component_returns_known_and_unknown_results():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    base = pg.GraphNode(
        stable_key="item_base:Metadata/Items/Weapons/Bows/Bow1",
        node_type="item_base",
        display_name="Shortbow",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem, base),
        edges=(),
        requirement_facts=(
            pg.RequirementFact(
                component_key=base.stable_key,
                level_or_stage="base",
                requirements={"level": 1, "dexterity": 0},
                source_refs=(source.source_id,),
            ),
        ),
    )

    known = pg.requirements_for_component(snapshot, base.stable_key, level_or_stage="base")
    unknown = pg.requirements_for_component(snapshot, gem.stable_key, level_or_stage="base")

    assert known.status == "known"
    assert known.facts["requirements"]["level"] == 1
    assert known.facts["requirements"]["dexterity"] == 0
    assert known.source_refs == (source.source_id,)
    assert unknown.status == "unknown"
    assert unknown.facts["requirements"] == {}


def test_build_requirements_for_component_e2e_sample_reports_result_shape():
    source = _source()
    base = pg.GraphNode(
        stable_key="item_base:Metadata/Items/Weapons/Bows/Bow1",
        node_type="item_base",
        display_name="Shortbow",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(base,),
        edges=(),
        requirement_facts=(
            pg.RequirementFact(
                component_key=base.stable_key,
                level_or_stage="base",
                requirements={"level": 1, "dexterity": 0},
                source_refs=(source.source_id,),
            ),
        ),
    )

    sample = pg.build_requirements_for_component_e2e_sample(
        snapshot=snapshot,
        component_key=base.stable_key,
        level_or_stage="base",
    )

    assert sample["query"]["fact_type"] == "requirements_for_component"
    assert sample["result"]["status"] == "known"
    assert sample["result"]["facts"]["requirements"]["level"] == 1


def test_ingest_skills_builds_resource_facts_and_skill_type_edges(tmp_path):
    skill_file = tmp_path / "skills.min.json"
    skill_file.write_text(
        json.dumps(
            {
                "LightningArrowPlayer": {
                    "active_skill": {
                        "description": "Fire a charged arrow.",
                        "display_name": "Lightning Arrow",
                        "id": "lightning_arrow",
                        "types": ["Attack", "Projectile", "Bow"],
                        "weapon_restrictions": [],
                    },
                    "cast_time": 1000,
                    "is_support": False,
                    "per_level": {
                        "1": {"costs": {"Mana": 6}},
                        "2": {"costs": {"Mana": 7}},
                    },
                    "static": {"attack_speed_multiplier": -10},
                },
                "SupportVitalityPlayer": {
                    "is_support": True,
                    "per_level": {"1": {}},
                    "static": {
                        "cost_multiplier": 100,
                        "reservations": {"spirit": 20},
                    },
                    "support_gem": {
                        "allowed_types": ["Persistent", "Buff", "AND"],
                        "supports_gems_only": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="repoe:skills",
        kind="repoe_raw",
        source_file="skills.min.json",
        expected_count=2,
    )
    gem_source = pg.GraphSource(
        source_id="repoe:skill_gems",
        kind="repoe_raw",
        source_file="skill_gems.min.json",
        expected_count=2,
    )
    gem_nodes = (
        pg.GraphNode(
            stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
            node_type="skill_gem",
            display_name="Lightning Arrow",
            source_refs=(gem_source.source_id,),
        ),
        pg.GraphNode(
            stable_key="support:Metadata/Items/Gems/SupportGemVitality",
            node_type="support_gem",
            display_name="Vitality I",
            source_refs=(gem_source.source_id,),
        ),
    )
    gem_edges = (
        pg.GraphEdge(
            edge_type="grants_skill",
            source_key=gem_nodes[0].stable_key,
            target_key="skill:LightningArrowPlayer",
            evidence_refs=(gem_source.source_id,),
        ),
        pg.GraphEdge(
            edge_type="grants_skill",
            source_key=gem_nodes[1].stable_key,
            target_key="skill:SupportVitalityPlayer",
            evidence_refs=(gem_source.source_id,),
        ),
    )

    ingestion = pg.ingest_skills(skill_file, source=source)
    snapshot = pg.build_snapshot(
        sources=(source, gem_source),
        nodes=gem_nodes + ingestion.nodes,
        edges=gem_edges + ingestion.edges,
        resource_facts=ingestion.resource_facts,
    )

    node_keys = {node.stable_key for node in snapshot.nodes}
    edge_types = {(edge.edge_type, edge.source_key, edge.target_key) for edge in snapshot.edges}

    assert "skill:LightningArrowPlayer" in node_keys
    assert "skill_type:attack" in node_keys
    assert ("has_type", "skill:LightningArrowPlayer", "skill_type:attack") in edge_types
    assert ("has_type", "skill:LightningArrowPlayer", "skill_type:bow") in edge_types

    mana_level_1 = pg.resource_profile_for_component(
        snapshot,
        "skill:LightningArrowPlayer",
        level_or_stage="1",
    )
    mana_level_2 = pg.resource_profile_for_component(
        snapshot,
        "skill:LightningArrowPlayer",
        level_or_stage="2",
    )
    vitality_base = pg.resource_profile_for_component(
        snapshot,
        "skill:SupportVitalityPlayer",
        level_or_stage="base",
    )

    assert mana_level_1.status == "known"
    assert mana_level_1.facts["costs"] == {"mana": 6}
    assert mana_level_1.facts["reservations"] == {}
    assert mana_level_2.facts["costs"] == {"mana": 7}
    assert vitality_base.status == "known"
    assert vitality_base.facts["costs"] == {"cost_multiplier": 100}
    assert vitality_base.facts["reservations"] == {"spirit": 20}


def test_resource_profile_for_component_returns_known_unknown_and_base_fallback():
    source = _source()
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemVitality",
        node_type="support_gem",
        display_name="Vitality I",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(support, skill),
        edges=(),
        resource_facts=(
            pg.ResourceFact(
                component_key=support.stable_key,
                level_or_stage="base",
                costs={"cost_multiplier": 100},
                reservations={"spirit": 20},
                source_refs=(source.source_id,),
            ),
            pg.ResourceFact(
                component_key=skill.stable_key,
                level_or_stage="1",
                costs={"mana": 6},
                reservations={},
                source_refs=(source.source_id,),
            ),
        ),
    )

    support_base = pg.resource_profile_for_component(
        snapshot,
        support.stable_key,
        level_or_stage="base",
    )
    support_fallback = pg.resource_profile_for_component(
        snapshot,
        support.stable_key,
        level_or_stage="gem_level_20",
    )
    missing_level = pg.resource_profile_for_component(
        snapshot,
        skill.stable_key,
        level_or_stage="gem_level_20",
    )

    assert support_base.status == "known"
    assert support_fallback.status == "known"
    assert support_fallback.facts["level_or_stage"] == "base"
    assert support_fallback.facts["costs"] == {"cost_multiplier": 100}
    assert missing_level.status == "unknown"
    assert missing_level.facts["costs"] == {}
    assert missing_level.facts["reservations"] == {}
    with pytest.raises(ValueError, match="missing component node"):
        pg.resource_profile_for_component(
            snapshot,
            "skill:UnknownSkill",
            level_or_stage="base",
        )


def test_build_resource_profile_for_component_e2e_sample_reports_result_shape():
    source = _source()
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemVitality",
        node_type="support_gem",
        display_name="Vitality I",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(support,),
        edges=(),
        resource_facts=(
            pg.ResourceFact(
                component_key=support.stable_key,
                level_or_stage="base",
                costs={"cost_multiplier": 100},
                reservations={"spirit": 20},
                source_refs=(source.source_id,),
            ),
        ),
    )

    sample = pg.build_resource_profile_for_component_e2e_sample(
        snapshot=snapshot,
        component_key=support.stable_key,
        level_or_stage="base",
    )

    assert sample["query"]["fact_type"] == "resource_profile_for_component"
    assert sample["result"]["status"] == "known"
    assert sample["result"]["facts"]["reservations"]["spirit"] == 20


def test_ingest_passive_tree_builds_class_ascendancy_passive_nodes_and_edges(tmp_path):
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(
        json.dumps(
            {
                "classes": [
                    {
                        "name": "Monk",
                        "integerId": 10,
                        "ascendancies": [
                            {
                                "id": "Invoker",
                                "internalId": "Monk1",
                                "name": "Invoker",
                            }
                        ],
                    },
                    {
                        "name": "Warrior",
                        "integerId": 6,
                        "ascendancies": [],
                    },
                ],
                "groups": [{"nodes": [100, 101, 102, 200], "orbits": [0], "x": 0, "y": 0}],
                "nodes": {
                    "100": {
                        "classesStart": ["Shadow", "Monk"],
                        "connections": [{"id": 101, "orbit": 0}],
                        "group": 1,
                        "icon": "start.dds",
                        "name": "Shared Start",
                        "orbit": 0,
                        "orbitIndex": 0,
                        "skill": 100,
                        "stats": [],
                    },
                    "101": {
                        "connections": [{"id": 100, "orbit": 0}, {"id": 102, "orbit": 0}],
                        "group": 1,
                        "icon": "notable.dds",
                        "isNotable": True,
                        "name": "Power Within",
                        "orbit": 1,
                        "orbitIndex": 0,
                        "skill": 101,
                        "stats": ["20% increased Damage"],
                    },
                    "102": {
                        "connections": [{"id": 101, "orbit": 0}],
                        "group": 1,
                        "icon": "keystone.dds",
                        "isKeystone": True,
                        "name": "Avatar of Flow",
                        "orbit": 2,
                        "orbitIndex": 0,
                        "skill": 102,
                        "stats": ["You can only Wear Blue Items"],
                    },
                    "200": {
                        "ascendancyName": "Invoker",
                        "connections": [],
                        "group": 1,
                        "icon": "asc.dds",
                        "isAscendancyStart": True,
                        "name": "Invoker",
                        "orbit": 3,
                        "orbitIndex": 0,
                        "skill": 200,
                        "stats": [],
                        "unlockConstraint": {"ascendancy": "Invoker", "nodes": [101]},
                    },
                },
                "tree": "0_5",
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="pob:passive_tree",
        kind="pob_tree",
        source_file="TreeData/0_5/tree.json",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
        expected_count=4,
    )

    ingestion = pg.ingest_passive_tree(tree_file, source=source)
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=ingestion.nodes,
        edges=ingestion.edges,
        aliases=ingestion.aliases,
        id_mappings=ingestion.id_mappings,
        requirement_facts=ingestion.requirement_facts,
    )

    node_keys = {node.stable_key for node in snapshot.nodes}
    edge_types = {(edge.edge_type, edge.source_key, edge.target_key) for edge in snapshot.edges}

    assert "class:monk" in node_keys
    assert "class:warrior" in node_keys
    assert "ascendancy:monk:invoker" in node_keys
    assert "passive:pob:0_5:100" in node_keys
    assert "notable:pob:0_5:101" in node_keys
    assert "keystone:pob:0_5:102" in node_keys
    assert "passive_type:class_start" in node_keys
    assert "passive_type:ascendancy_start" in node_keys
    assert "passive_type:notable" in node_keys
    assert "passive_type:keystone" in node_keys
    assert "class:shadow" not in node_keys
    assert ("starts_at", "class:monk", "passive:pob:0_5:100") in edge_types
    assert ("belongs_to", "ascendancy:monk:invoker", "class:monk") in edge_types
    assert (
        "connected_to",
        "passive:pob:0_5:100",
        "notable:pob:0_5:101",
    ) in edge_types
    assert (
        "has_type",
        "passive:pob:0_5:100",
        "passive_type:class_start",
    ) in edge_types
    assert (
        "has_type",
        "notable:pob:0_5:101",
        "passive_type:notable",
    ) in edge_types
    assert (
        "has_type",
        "keystone:pob:0_5:102",
        "passive_type:keystone",
    ) in edge_types
    assert any(mapping.system == "pob:passive_node_id" for mapping in snapshot.id_mappings)
    unlock_fact = next(
        fact
        for fact in snapshot.requirement_facts
        if fact.component_key == "passive:pob:0_5:200"
        and fact.level_or_stage == "unlock_constraint"
    )
    assert unlock_fact.requirements["ascendancy"] == "Invoker"
    assert unlock_fact.requirements["nodes"] == [101]


def test_ingest_passive_tree_requires_tree_version_from_source_or_argument(tmp_path):
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(
        json.dumps({"classes": [], "groups": [], "nodes": {}, "tree": "0_5"}),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="pob:passive_tree",
        kind="pob_tree",
        source_file="TreeData/0_5/tree.json",
        expected_count=0,
    )

    with pytest.raises(ValueError, match="passive tree version"):
        pg.ingest_passive_tree(tree_file, source=source)


def test_ingest_passive_tree_skips_unknown_connection_targets_without_dangling_edges(tmp_path):
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(
        json.dumps(
            {
                "classes": [{"name": "Monk", "integerId": 10, "ascendancies": []}],
                "groups": [{"nodes": [100], "orbits": [0], "x": 0, "y": 0}],
                "nodes": {
                    "100": {
                        "classesStart": ["Monk"],
                        "connections": [{"id": 101, "orbit": 0}, {"id": 999999, "orbit": 0}],
                        "group": 1,
                        "icon": "start.dds",
                        "name": "Shared Start",
                        "orbit": 0,
                        "orbitIndex": 0,
                        "skill": 100,
                        "stats": [],
                    },
                    "101": {
                        "connections": [{"id": 100, "orbit": 0}],
                        "group": 1,
                        "icon": "node.dds",
                        "name": "Path Node",
                        "orbit": 1,
                        "orbitIndex": 0,
                        "skill": 101,
                        "stats": [],
                    },
                },
                "tree": "0_5",
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="pob:passive_tree",
        kind="pob_tree",
        source_file="TreeData/0_5/tree.json",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
        expected_count=2,
    )

    ingestion = pg.ingest_passive_tree(tree_file, source=source)
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=ingestion.nodes,
        edges=ingestion.edges,
        aliases=ingestion.aliases,
        id_mappings=ingestion.id_mappings,
        requirement_facts=ingestion.requirement_facts,
    )

    edge_types = {(edge.edge_type, edge.source_key, edge.target_key) for edge in snapshot.edges}

    assert (
        "connected_to",
        "passive:pob:0_5:100",
        "passive:pob:0_5:101",
    ) in edge_types
    assert not any(edge.target_key.endswith(":999999") for edge in snapshot.edges)
    caveat_fact = next(
        fact
        for fact in snapshot.requirement_facts
        if fact.component_key == "passive:pob:0_5:100"
        and fact.level_or_stage == "connection_caveat"
    )
    assert caveat_fact.requirements["unresolved_connection_ids"] == [999999]
    assert caveat_fact.requirements["skipped_unresolved_connections"] == 1


def test_ingest_passive_tree_builds_passive_official_ids_and_allocation_options(tmp_path):
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(
        json.dumps(
            {
                "classes": [{"name": "Warrior", "integerId": 6, "ascendancies": []}],
                "groups": [{"nodes": [100], "orbits": [0], "x": 0, "y": 0}],
                "nodes": {
                    "100": {
                        "connections": [],
                        "group": 1,
                        "icon": "attribute.dds",
                        "isAttribute": True,
                        "name": "Attribute",
                        "options": [
                            {
                                "id": 26297,
                                "name": "Strength",
                                "stats": ["+5 to Strength"],
                            },
                            {
                                "id": 14927,
                                "name": "Dexterity",
                                "stats": ["+5 to Dexterity"],
                            },
                        ],
                        "orbit": 0,
                        "orbitIndex": 0,
                        "skill": 32183,
                        "stats": ["+5 to any Attribute"],
                    }
                },
                "tree": "0_5",
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="pob:passive_tree",
        kind="pob_tree",
        source_file="TreeData/0_5/tree.json",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
        expected_count=1,
    )

    ingestion = pg.ingest_passive_tree(tree_file, source=source)
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=ingestion.nodes,
        edges=ingestion.edges,
        aliases=ingestion.aliases,
        id_mappings=ingestion.id_mappings,
        requirement_facts=ingestion.requirement_facts,
        passive_choices=ingestion.passive_choices,
        allocation_options=ingestion.allocation_options,
    )

    passive = next(node for node in snapshot.nodes if node.stable_key == "passive:pob:0_5:100")
    assert passive.official_ids == {
        "pob:passive_node_id": "100",
        "pob:passive_skill_node_id": "32183",
    }
    assert any(
        mapping.system == "pob:passive_skill_node_id"
        and mapping.external_id == "32183"
        and mapping.target_key == passive.stable_key
        for mapping in snapshot.id_mappings
    )
    assert [choice.choice_key for choice in snapshot.passive_choices] == [
        "passive_choice:passive:pob:0_5:100:32183"
    ]
    assert [option.option_key for option in snapshot.allocation_options] == [
        "allocation_option:passive:pob:0_5:100:14927",
        "allocation_option:passive:pob:0_5:100:26297",
    ]
    assert snapshot.allocation_options[0].display_name == "Dexterity"
    assert snapshot.allocation_options[1].stat_text == "+5 to Strength"


def test_ingest_passive_tree_accepts_pob_dict_allocation_options(tmp_path):
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(
        json.dumps(
            {
                "classes": [
                    {
                        "name": "Witch",
                        "integerId": 3,
                        "ascendancies": [{"name": "Abyssal Lich", "id": "AbyssalLich"}],
                    }
                ],
                "groups": [{"nodes": [59], "orbits": [0], "x": 0, "y": 0}],
                "nodes": {
                    "59": {
                        "connections": [],
                        "group": 1,
                        "icon": "ascendancy.dds",
                        "name": "Abyssal Lich Choice",
                        "options": {
                            "Abyssal Lich": {
                                "ascendancyName": "Abyssal Lich",
                                "nodeOverlay": {
                                    "alloc": "Allocated",
                                    "path": "CanAllocate",
                                    "unalloc": "Normal",
                                },
                            }
                        },
                        "orbit": 0,
                        "orbitIndex": 0,
                        "skill": 59,
                        "stats": [],
                    }
                },
                "tree": "0_5",
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="pob:passive_tree",
        kind="pob_tree",
        source_file="TreeData/0_5/tree.json",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
        expected_count=1,
    )

    ingestion = pg.ingest_passive_tree(tree_file, source=source)
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=ingestion.nodes,
        edges=ingestion.edges,
        aliases=ingestion.aliases,
        id_mappings=ingestion.id_mappings,
        passive_choices=ingestion.passive_choices,
        allocation_options=ingestion.allocation_options,
    )

    assert [choice.choice_key for choice in snapshot.passive_choices] == [
        "passive_choice:passive:pob:0_5:59:59"
    ]
    assert [option.option_key for option in snapshot.allocation_options] == [
        "allocation_option:passive:pob:0_5:59:Abyssal_Lich"
    ]
    assert snapshot.allocation_options[0].display_name == "Abyssal Lich"
    assert snapshot.allocation_options[0].stat_text == "selector:Abyssal Lich"


def test_passive_neighbors_returns_known_and_ambiguous_results(tmp_path):
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(
        json.dumps(
            {
                "classes": [{"name": "Monk", "integerId": 10, "ascendancies": []}],
                "groups": [{"nodes": [100, 101], "orbits": [0], "x": 0, "y": 0}],
                "nodes": {
                    "100": {
                        "classesStart": ["Monk"],
                        "connections": [{"id": 101, "orbit": 0}, {"id": 999999, "orbit": 0}],
                        "group": 1,
                        "icon": "start.dds",
                        "name": "Shared Start",
                        "orbit": 0,
                        "orbitIndex": 0,
                        "skill": 100,
                        "stats": [],
                    },
                    "101": {
                        "connections": [{"id": 100, "orbit": 0}],
                        "group": 1,
                        "icon": "node.dds",
                        "name": "Path Node",
                        "orbit": 1,
                        "orbitIndex": 0,
                        "skill": 101,
                        "stats": [],
                    },
                },
                "tree": "0_5",
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="pob:passive_tree",
        kind="pob_tree",
        source_file="TreeData/0_5/tree.json",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
        expected_count=2,
    )
    ingestion = pg.ingest_passive_tree(tree_file, source=source)
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=ingestion.nodes,
        edges=ingestion.edges,
        aliases=ingestion.aliases,
        id_mappings=ingestion.id_mappings,
        requirement_facts=ingestion.requirement_facts,
    )

    ambiguous = pg.passive_neighbors(snapshot, "passive:pob:0_5:100")
    known = pg.passive_neighbors(snapshot, "passive:pob:0_5:101")

    assert ambiguous.status == "ambiguous"
    assert ambiguous.facts["neighbor_keys"] == ["passive:pob:0_5:101"]
    assert ambiguous.facts["unresolved_connection_ids"] == [999999]
    assert known.status == "known"
    assert known.facts["neighbor_keys"] == ["passive:pob:0_5:100"]
    assert known.facts["unresolved_connection_ids"] == []


def test_passive_allocation_options_returns_known_and_unknown_results(tmp_path):
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(
        json.dumps(
            {
                "classes": [{"name": "Warrior", "integerId": 6, "ascendancies": []}],
                "groups": [{"nodes": [100, 101], "orbits": [0], "x": 0, "y": 0}],
                "nodes": {
                    "100": {
                        "connections": [],
                        "group": 1,
                        "icon": "attribute.dds",
                        "isAttribute": True,
                        "name": "Attribute",
                        "options": [
                            {
                                "id": 26297,
                                "name": "Strength",
                                "stats": ["+5 to Strength"],
                            }
                        ],
                        "orbit": 0,
                        "orbitIndex": 0,
                        "skill": 32183,
                        "stats": ["+5 to any Attribute"],
                    },
                    "101": {
                        "connections": [],
                        "group": 1,
                        "icon": "node.dds",
                        "name": "Attack Speed",
                        "orbit": 1,
                        "orbitIndex": 0,
                        "skill": 32399,
                        "stats": ["2% increased Attack Speed"],
                    },
                },
                "tree": "0_5",
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="pob:passive_tree",
        kind="pob_tree",
        source_file="TreeData/0_5/tree.json",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
        expected_count=2,
    )
    ingestion = pg.ingest_passive_tree(tree_file, source=source)
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=ingestion.nodes,
        edges=ingestion.edges,
        aliases=ingestion.aliases,
        id_mappings=ingestion.id_mappings,
        passive_choices=ingestion.passive_choices,
        allocation_options=ingestion.allocation_options,
    )

    known = pg.passive_allocation_options(snapshot, "passive:pob:0_5:100")
    unknown = pg.passive_allocation_options(snapshot, "passive:pob:0_5:101")

    assert known.status == "known"
    assert known.facts["choice_keys"] == ["passive_choice:passive:pob:0_5:100:32183"]
    assert known.facts["options"][0]["display_name"] == "Strength"
    assert known.source_refs == (source.source_id,)
    assert unknown.status == "unknown"
    assert unknown.facts["options"] == []


def test_passive_allocation_overlay_reports_weapon_set_caveat():
    source = _source()
    passive = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Weapon Conversion",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(passive,),
        edges=(),
        requirement_facts=(
            pg.RequirementFact(
                component_key=passive.stable_key,
                level_or_stage="weapon_set_overlay",
                requirements={
                    "allocation_states": ["weapon_set_1", "weapon_set_2"],
                    "weapon_set_point_conversion": 24,
                    "state_specific_reachability": True,
                },
                source_refs=(source.source_id,),
                status="ambiguous",
                confidence=0.5,
            ),
        ),
    )

    overlay = pg.passive_allocation_overlay(snapshot, passive.stable_key)

    assert overlay.status == "ambiguous"
    assert overlay.caveat == "dual_weapon_state_limited_caveat"
    assert overlay.facts["allocation_states"] == ["weapon_set_1", "weapon_set_2"]
    assert overlay.facts["weapon_set_point_conversion"] == 24


def test_caveat_component_set_returns_trigger_context():
    source = _source()
    caveat = pg.GraphNode(
        stable_key="caveat:dual_weapon_state_limited_caveat",
        node_type="caveat",
        display_name="dual_weapon_state_limited_caveat",
        source_refs=(source.source_id,),
    )
    passive = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Weapon Conversion",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(caveat, passive, skill),
        edges=(),
        requirement_facts=(
            pg.RequirementFact(
                component_key=caveat.stable_key,
                level_or_stage="component_set",
                requirements={
                    "component_keys": [passive.stable_key, skill.stable_key],
                    "trigger_condition": "weapon_set_passives_used_without_dual_state_scores",
                    "modelability_effect": "limited",
                    "reward_eligibility_effect": "limited",
                },
                source_refs=(source.source_id,),
                status="known",
            ),
        ),
    )

    result = pg.caveat_component_set(snapshot, caveat.stable_key)

    assert result.status == "known"
    assert result.facts["component_keys"] == [passive.stable_key, skill.stable_key]
    assert result.facts["trigger_condition"] == "weapon_set_passives_used_without_dual_state_scores"


def test_ingest_unique_items_builds_unique_to_base_edges_and_mod_text_nodes(tmp_path):
    base_file = tmp_path / "base_items.min.json"
    base_file.write_text(
        json.dumps(
            {
                "Metadata/Items/Amulets/BloodstoneAmulet": {
                    "name": "Bloodstone Amulet",
                    "item_class": "Amulet",
                    "domain": "item",
                    "drop_level": 1,
                    "tags": ["amulet", "jewellery"],
                    "requirements": {"level": 1},
                }
            }
        ),
        encoding="utf-8",
    )
    unique_file = tmp_path / "amulet.lua"
    unique_file.write_text(
        """-- Item data (c) Grinding Gear Games

return {
-- Amulet
[[
The Anvil
Bloodstone Amulet
Implicits: 1
+(30-40) to maximum Life
10% reduced Movement Speed
]],
}
""",
        encoding="utf-8",
    )
    base_source = pg.GraphSource(
        source_id="repoe:base_items",
        kind="repoe_raw",
        source_file="base_items.min.json",
        expected_count=1,
    )
    unique_source = pg.GraphSource(
        source_id="pob:uniques",
        kind="pob_unique_text",
        source_file="amulet.lua",
        expected_count=1,
    )

    base_ingestion = pg.ingest_base_items(base_file, source=base_source)
    unique_ingestion = pg.ingest_uniques(
        unique_file,
        source=unique_source,
        known_base_nodes=base_ingestion.nodes,
        known_base_aliases=base_ingestion.aliases,
    )
    merged = pg.merge_ingestion_results(base_ingestion, unique_ingestion)
    snapshot = pg.build_snapshot(
        sources=(base_source, unique_source),
        nodes=merged.nodes,
        edges=merged.edges,
        aliases=merged.aliases,
        id_mappings=merged.id_mappings,
        requirement_facts=merged.requirement_facts,
    )

    unique_key = "unique:pob:the_anvil"
    assert unique_key in {node.stable_key for node in snapshot.nodes}
    assert (
        "has_base",
        unique_key,
        "item_base:Metadata/Items/Amulets/BloodstoneAmulet",
    ) in {(edge.edge_type, edge.source_key, edge.target_key) for edge in snapshot.edges}
    assert any(
        edge.edge_type == "has_mod_text" and edge.source_key == unique_key
        for edge in snapshot.edges
    )

    result = pg.unique_base_item(snapshot, unique_key)

    assert result.status == "known"
    assert result.facts["base_item_key"] == "item_base:Metadata/Items/Amulets/BloodstoneAmulet"
    assert result.facts["base_item_name"] == "Bloodstone Amulet"


def test_ingest_exported_generated_uniques_blocks(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    exported = repo_root / "data" / "physical_graph" / "uniques" / "generated_uniques.lua"
    if not exported.exists():
        pytest.skip(
            "exported generated uniques not present; run scripts/export_generated_uniques.py"
        )
    source = pg.GraphSource(
        source_id="pob:uniques",
        kind="pob_unique_text",
        source_file="generated_uniques.lua",
        expected_count=8,
    )
    ingestion = pg.ingest_uniques(
        exported,
        source=source,
        known_base_nodes={},
        known_base_aliases=(),
    )
    keys = {node.stable_key for node in ingestion.nodes}
    for name in (
        "against_the_darkness",
        "flesh_crucible",
        "from_nothing",
        "grip_of_kulemak",
        "heart_of_the_well",
        "loreweave",
        "megalomaniac",
        "prism_of_belief",
    ):
        assert f"unique:pob:{name}" in keys, f"missing generated unique {name}"

    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=ingestion.nodes,
        edges=ingestion.edges,
        aliases=ingestion.aliases,
        id_mappings=ingestion.id_mappings,
        requirement_facts=ingestion.requirement_facts,
    )
    resolved = pg.resolve_candidates(snapshot, "Heart of the Well")
    assert resolved["status"] == "resolved"
    assert resolved["resolved_key"] == "unique:pob:heart_of_the_well"
    missing = pg.resolve_candidates(snapshot, "Soul Hope")
    assert missing["status"] == "missing"


def test_build_phase2_fixed_sample_bundle_covers_multiple_acceptance_families():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    weapon = pg.GraphNode(
        stable_key="weapon_type:bow",
        node_type="weapon_type",
        display_name="Bow",
        source_refs=(source.source_id,),
    )
    passive = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Attribute",
        source_refs=(source.source_id,),
    )
    passive_neighbor = pg.GraphNode(
        stable_key="passive:pob:0_5:101",
        node_type="passive",
        display_name="Path Node",
        source_refs=(source.source_id,),
    )
    caveat = pg.GraphNode(
        stable_key="caveat:dual_weapon_state_limited_caveat",
        node_type="caveat",
        display_name="dual_weapon_state_limited_caveat",
        source_refs=(source.source_id,),
    )
    unique = pg.GraphNode(
        stable_key="unique:pob:the_anvil",
        node_type="unique",
        display_name="The Anvil",
        source_refs=(source.source_id,),
    )
    base_item = pg.GraphNode(
        stable_key="item_base:Metadata/Items/Amulets/BloodstoneAmulet",
        node_type="item_base",
        display_name="Bloodstone Amulet",
        source_refs=(source.source_id,),
    )
    mod = pg.GraphNode(
        stable_key="mod:MovementSpeed1",
        node_type="mod",
        display_name="of Movement",
        source_refs=(source.source_id,),
    )
    item_tag = pg.GraphNode(
        stable_key="tag:item:default",
        node_type="item_tag",
        display_name="default",
        source_refs=(source.source_id,),
    )
    support_skill = pg.GraphNode(
        stable_key="skill:SupportPiercePlayer",
        node_type="active_skill",
        display_name="Support Pierce",
        source_refs=(source.source_id,),
    )
    projectile_type = pg.GraphNode(
        stable_key="skill_type:projectile",
        node_type="skill_type",
        display_name="Projectile",
        source_refs=(source.source_id,),
    )
    attack_type = pg.GraphNode(
        stable_key="skill_type:attack",
        node_type="skill_type",
        display_name="Attack",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(
            gem,
            support,
            skill,
            weapon,
            passive,
            passive_neighbor,
            caveat,
            unique,
            base_item,
            mod,
            item_tag,
            support_skill,
            projectile_type,
            attack_type,
        ),
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=gem.stable_key,
                target_key=skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=support.stable_key,
                target_key=support_skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="granted_by",
                source_key=skill.stable_key,
                target_key=gem.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="connected_to",
                source_key=passive.stable_key,
                target_key=passive_neighbor.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_base",
                source_key=unique.stable_key,
                target_key=base_item.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_tag",
                source_key=base_item.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="applies_to_tag",
                source_key=mod.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="requires_weapon_type",
                source_key=skill.stable_key,
                target_key=weapon.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=projectile_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=attack_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        aliases=(
            pg.GraphAlias("Lightning Arrow", gem.stable_key, (source.source_id,)),
            pg.GraphAlias("Lightning Arrow", skill.stable_key, (source.source_id,)),
        ),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SupportGemPierce",
                target_key=support.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key=base_item.stable_key,
                level_or_stage="base",
                requirements={"domain": "item", "drop_level": 1},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=mod.stable_key,
                level_or_stage="base",
                requirements={
                    "domain": "item",
                    "required_level": 70,
                    "generation_type": "suffix",
                    "groups": ["MovementSpeed"],
                    "text": "increased Movement Speed",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=gem.stable_key,
                level_or_stage="base",
                requirements={"level": 1, "dex": 9},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=support_skill.stable_key,
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Projectile", "Attack", "AND"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                    "added_types": [],
                    "added_minion_types": [],
                    "support_family": "Pierce",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=skill.stable_key,
                level_or_stage="socket_context",
                requirements={
                    "max_support_count": 1,
                    "socketed_support_keys": [support.stable_key],
                    "socketed_support_families": ["Pierce"],
                    "duplicate_support_policy": "reject_same_support_key",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=caveat.stable_key,
                level_or_stage="component_set",
                requirements={
                    "component_keys": [passive.stable_key, skill.stable_key],
                    "trigger_condition": "weapon_set_passives_used_without_dual_state_scores",
                    "modelability_effect": "limited",
                    "reward_eligibility_effect": "limited",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=passive.stable_key,
                level_or_stage="weapon_set_overlay",
                requirements={
                    "allocation_states": ["weapon_set_1"],
                    "weapon_set_point_conversion": 24,
                    "state_specific_reachability": True,
                },
                source_refs=(source.source_id,),
                status="ambiguous",
                confidence=0.5,
            ),
        ),
        resource_facts=(
            pg.ResourceFact(
                component_key=skill.stable_key,
                level_or_stage="1",
                costs={"mana": 6},
                reservations={},
                source_refs=(source.source_id,),
            ),
        ),
        passive_choices=(
            pg.PassiveChoice(
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                parent_passive_key=passive.stable_key,
                display_name="Attribute",
                source_refs=(source.source_id,),
            ),
        ),
        allocation_options=(
            pg.AllocationOption(
                option_key="allocation_option:passive:pob:0_5:100:26297",
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                display_name="Strength",
                stat_text="+5 to Strength",
                source_refs=(source.source_id,),
            ),
        ),
    )

    report = pg.build_phase2_fixed_sample_bundle(
        snapshot=snapshot,
        gem_key=gem.stable_key,
        skill_key=skill.stable_key,
        support_key=support.stable_key,
        passive_key=passive.stable_key,
        unique_key=unique.stable_key,
        caveat_key=caveat.stable_key,
    )

    assert report["sample_count"] >= 10
    assert "gem_grants_skill" in report["family_counts"]
    assert "unique_base_item" in report["family_counts"]
    assert "passive_allocation_options" in report["family_counts"]
    assert "caveat_component_set" in report["family_counts"]
    assert "socket_support_legality" in report["family_counts"]
    assert "can_roll_mod" in report["family_counts"]
    assert "requirements_for_component" in report["family_counts"]
    assert "resource_profile_for_component" in report["family_counts"]


def test_build_passive_neighbors_e2e_sample_reports_result_shape(tmp_path):
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(
        json.dumps(
            {
                "classes": [{"name": "Monk", "integerId": 10, "ascendancies": []}],
                "groups": [{"nodes": [100, 101], "orbits": [0], "x": 0, "y": 0}],
                "nodes": {
                    "100": {
                        "classesStart": ["Monk"],
                        "connections": [{"id": 101, "orbit": 0}],
                        "group": 1,
                        "icon": "start.dds",
                        "name": "Shared Start",
                        "orbit": 0,
                        "orbitIndex": 0,
                        "skill": 100,
                        "stats": [],
                    },
                    "101": {
                        "connections": [{"id": 100, "orbit": 0}],
                        "group": 1,
                        "icon": "node.dds",
                        "name": "Path Node",
                        "orbit": 1,
                        "orbitIndex": 0,
                        "skill": 101,
                        "stats": [],
                    },
                },
                "tree": "0_5",
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="pob:passive_tree",
        kind="pob_tree",
        source_file="TreeData/0_5/tree.json",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
        expected_count=2,
    )
    ingestion = pg.ingest_passive_tree(tree_file, source=source)
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=ingestion.nodes,
        edges=ingestion.edges,
        aliases=ingestion.aliases,
        id_mappings=ingestion.id_mappings,
        requirement_facts=ingestion.requirement_facts,
    )

    sample = pg.build_passive_neighbors_e2e_sample(
        snapshot=snapshot,
        passive_key="passive:pob:0_5:100",
    )

    assert sample["query"]["fact_type"] == "passive_neighbors"
    assert sample["result"]["status"] == "known"
    assert sample["result"]["facts"]["neighbor_keys"] == ["passive:pob:0_5:101"]


def test_support_skill_candidate_distinguishes_recommended_hard_compatible_and_unsupported(
    tmp_path,
):
    gem_file = tmp_path / "skill_gems.min.json"
    gem_file.write_text(
        json.dumps(
            {
                "Metadata/Items/Gems/SkillGemHeraldOfAsh": {
                    "base_item": {"display_name": "Herald of Ash"},
                    "gem_type": "active",
                    "grants_skills": ["HeraldOfAshPlayer"],
                    "recommended_supports": ["Metadata/Items/Gems/SupportGemVitality"],
                    "tags": ["buff", "persistent", "fire"],
                },
                "Metadata/Items/Gems/SkillGemLightningArrow": {
                    "base_item": {"display_name": "Lightning Arrow"},
                    "gem_type": "active",
                    "grants_skills": ["LightningArrowPlayer"],
                    "recommended_supports": [],
                    "tags": ["attack", "projectile", "lightning"],
                },
                "Metadata/Items/Gems/SupportGemVitality": {
                    "base_item": {"display_name": "Vitality I"},
                    "gem_type": "support",
                    "grants_skills": ["SupportVitalityPlayer"],
                    "tags": ["support", "buff", "persistent"],
                },
                "Metadata/Items/Gems/SupportGemRuthless": {
                    "base_item": {"display_name": "Ruthless"},
                    "gem_type": "support",
                    "grants_skills": ["SupportRuthlessPlayer"],
                    "tags": ["support", "attack"],
                },
                "Metadata/Items/Gems/SupportGemGemOnly": {
                    "base_item": {"display_name": "Gem Only Support"},
                    "gem_type": "support",
                    "grants_skills": ["SupportGemOnlyPlayer"],
                    "tags": ["support", "attack"],
                },
            }
        ),
        encoding="utf-8",
    )
    skills_file = tmp_path / "skills.min.json"
    skills_file.write_text(
        json.dumps(
            {
                "HeraldOfAshPlayer": {
                    "active_skill": {
                        "display_name": "Herald of Ash",
                        "id": "herald_of_ash",
                        "types": ["Persistent", "Buff", "AttackInPlace"],
                        "weapon_restrictions": [],
                    },
                    "is_support": False,
                    "per_level": {"1": {}},
                },
                "LightningArrowPlayer": {
                    "active_skill": {
                        "display_name": "Lightning Arrow",
                        "id": "lightning_arrow",
                        "types": ["Attack", "Projectile", "Bow"],
                        "weapon_restrictions": [],
                    },
                    "is_support": False,
                    "per_level": {"1": {"costs": {"Mana": 6}}},
                },
                "SupportVitalityPlayer": {
                    "is_support": True,
                    "per_level": {"1": {}},
                    "support_gem": {
                        "allowed_types": ["Persistent", "Buff", "AND"],
                        "supports_gems_only": False,
                    },
                },
                "SupportRuthlessPlayer": {
                    "is_support": True,
                    "per_level": {"1": {}},
                    "support_gem": {
                        "allowed_types": ["Attack"],
                        "supports_gems_only": False,
                    },
                },
                "SupportGemOnlyPlayer": {
                    "is_support": True,
                    "per_level": {"1": {}},
                    "support_gem": {
                        "allowed_types": ["Attack"],
                        "supports_gems_only": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    gem_source = pg.GraphSource(
        source_id="repoe:skill_gems",
        kind="repoe_raw",
        source_file="skill_gems.min.json",
        expected_count=5,
    )
    skill_source = pg.GraphSource(
        source_id="repoe:skills",
        kind="repoe_raw",
        source_file="skills.min.json",
        expected_count=5,
    )

    gem_ingestion = pg.ingest_skill_gems(gem_file, source=gem_source)
    skill_ingestion = pg.ingest_skills(skills_file, source=skill_source)
    merged = pg.merge_ingestion_results(gem_ingestion, skill_ingestion)
    handcrafted_skill = pg.GraphNode(
        stable_key="skill:CraftGrantedAttack",
        node_type="active_skill",
        display_name="Craft Granted Attack",
        source_refs=(skill_source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(gem_source, skill_source),
        nodes=merged.nodes + (handcrafted_skill,),
        edges=merged.edges
        + (
            pg.GraphEdge(
                edge_type="has_type",
                source_key=handcrafted_skill.stable_key,
                target_key="skill_type:attack",
                evidence_refs=(skill_source.source_id,),
            ),
        ),
        aliases=merged.aliases,
        id_mappings=merged.id_mappings,
        requirement_facts=merged.requirement_facts,
        resource_facts=merged.resource_facts,
    )

    recommended = pg.support_skill_candidate(
        snapshot=snapshot,
        support_key="support:Metadata/Items/Gems/SupportGemVitality",
        skill_key="skill:HeraldOfAshPlayer",
    )
    hard_compatible = pg.support_skill_candidate(
        snapshot=snapshot,
        support_key="support:Metadata/Items/Gems/SupportGemRuthless",
        skill_key="skill:LightningArrowPlayer",
    )
    unsupported = pg.support_skill_candidate(
        snapshot=snapshot,
        support_key="support:Metadata/Items/Gems/SupportGemVitality",
        skill_key="skill:LightningArrowPlayer",
    )
    gem_only = pg.support_skill_candidate(
        snapshot=snapshot,
        support_key="support:Metadata/Items/Gems/SupportGemGemOnly",
        skill_key=handcrafted_skill.stable_key,
    )

    assert recommended.status == "known"
    assert recommended.facts["candidate_status"] == "recommended"
    assert recommended.facts["shared_tags"] == ["buff", "persistent"]
    assert hard_compatible.status == "known"
    assert hard_compatible.facts["candidate_status"] == "hard_compatible"
    assert hard_compatible.facts["matched_skill_types"] == ["attack"]
    assert unsupported.status == "unsupported"
    assert unsupported.facts["candidate_status"] == "unsupported"
    assert unsupported.facts["excluded_reason"] == "required_types_not_matched"
    assert gem_only.status == "unsupported"
    assert gem_only.facts["excluded_reason"] == "supports_gems_only"


def test_build_support_skill_candidate_e2e_sample_reports_result_shape(tmp_path):
    gem_file = tmp_path / "skill_gems.min.json"
    gem_file.write_text(
        json.dumps(
            {
                "Metadata/Items/Gems/SkillGemHeraldOfAsh": {
                    "base_item": {"display_name": "Herald of Ash"},
                    "gem_type": "active",
                    "grants_skills": ["HeraldOfAshPlayer"],
                    "recommended_supports": ["Metadata/Items/Gems/SupportGemVitality"],
                    "tags": ["buff", "persistent", "fire"],
                },
                "Metadata/Items/Gems/SupportGemVitality": {
                    "base_item": {"display_name": "Vitality I"},
                    "gem_type": "support",
                    "grants_skills": ["SupportVitalityPlayer"],
                    "tags": ["support", "buff", "persistent"],
                },
            }
        ),
        encoding="utf-8",
    )
    skills_file = tmp_path / "skills.min.json"
    skills_file.write_text(
        json.dumps(
            {
                "HeraldOfAshPlayer": {
                    "active_skill": {
                        "display_name": "Herald of Ash",
                        "id": "herald_of_ash",
                        "types": ["Persistent", "Buff", "AttackInPlace"],
                        "weapon_restrictions": [],
                    },
                    "is_support": False,
                    "per_level": {"1": {}},
                },
                "SupportVitalityPlayer": {
                    "is_support": True,
                    "per_level": {"1": {}},
                    "support_gem": {
                        "allowed_types": ["Persistent", "Buff", "AND"],
                        "supports_gems_only": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    gem_source = pg.GraphSource(
        source_id="repoe:skill_gems",
        kind="repoe_raw",
        source_file="skill_gems.min.json",
        expected_count=2,
    )
    skill_source = pg.GraphSource(
        source_id="repoe:skills",
        kind="repoe_raw",
        source_file="skills.min.json",
        expected_count=2,
    )
    merged = pg.merge_ingestion_results(
        pg.ingest_skill_gems(gem_file, source=gem_source),
        pg.ingest_skills(skills_file, source=skill_source),
    )
    snapshot = pg.build_snapshot(
        sources=(gem_source, skill_source),
        nodes=merged.nodes,
        edges=merged.edges,
        aliases=merged.aliases,
        id_mappings=merged.id_mappings,
        requirement_facts=merged.requirement_facts,
        resource_facts=merged.resource_facts,
    )

    sample = pg.build_support_skill_candidate_e2e_sample(
        snapshot=snapshot,
        support_key="support:Metadata/Items/Gems/SupportGemVitality",
        skill_key="skill:HeraldOfAshPlayer",
    )

    assert sample["query"]["fact_type"] == "support_skill_candidate"
    assert sample["result"]["status"] == "known"
    assert sample["result"]["facts"]["candidate_status"] == "recommended"


def test_socket_support_legality_rejects_duplicate_and_support_limit():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support_skill = pg.GraphNode(
        stable_key="skill:SupportPiercePlayer",
        node_type="active_skill",
        display_name="Support Pierce",
        source_refs=(source.source_id,),
    )
    projectile_type = pg.GraphNode(
        stable_key="skill_type:projectile",
        node_type="skill_type",
        display_name="Projectile",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem, support, skill, support_skill, projectile_type),
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=gem.stable_key,
                target_key=skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=support.stable_key,
                target_key=support_skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="granted_by",
                source_key=skill.stable_key,
                target_key=gem.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=projectile_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key=support_skill.stable_key,
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Projectile"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                    "support_family": "Pierce",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=skill.stable_key,
                level_or_stage="socket_context",
                requirements={
                    "max_support_count": 1,
                    "socketed_support_keys": [support.stable_key],
                    "socketed_support_families": ["Pierce"],
                    "duplicate_support_policy": "reject_same_support_key",
                },
                source_refs=(source.source_id,),
            ),
        ),
    )

    duplicate = pg.socket_support_legality(
        snapshot=snapshot,
        skill_key=skill.stable_key,
        support_key=support.stable_key,
        socket_context={"socketed_support_keys": [support.stable_key]},
    )
    support_limit = pg.socket_support_legality(
        snapshot=snapshot,
        skill_key=skill.stable_key,
        support_key=support.stable_key,
        socket_context={
            "socketed_support_keys": [],
            "socketed_support_families": [],
            "current_support_count": 1,
        },
    )

    assert duplicate.status == "unsupported"
    assert duplicate.facts["legality_status"] == "unsupported"
    assert duplicate.facts["excluded_reasons"] == ["duplicate_support"]
    assert duplicate.facts["support_candidate_status"] == "hard_compatible"
    assert support_limit.status == "unsupported"
    assert support_limit.facts["excluded_reasons"] == ["support_limit_exceeded"]


def test_socket_support_legality_accepts_empty_socket_context_when_candidate_is_hard_compatible():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support_skill = pg.GraphNode(
        stable_key="skill:SupportPiercePlayer",
        node_type="active_skill",
        display_name="Support Pierce",
        source_refs=(source.source_id,),
    )
    projectile_type = pg.GraphNode(
        stable_key="skill_type:projectile",
        node_type="skill_type",
        display_name="Projectile",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem, support, skill, support_skill, projectile_type),
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=gem.stable_key,
                target_key=skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=support.stable_key,
                target_key=support_skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="granted_by",
                source_key=skill.stable_key,
                target_key=gem.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=projectile_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key=support_skill.stable_key,
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Projectile"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                    "support_family": "Pierce",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=skill.stable_key,
                level_or_stage="socket_context",
                requirements={
                    "max_support_count": 2,
                    "socketed_support_keys": [],
                    "socketed_support_families": [],
                    "duplicate_support_policy": "reject_same_support_key",
                },
                source_refs=(source.source_id,),
            ),
        ),
    )

    result = pg.socket_support_legality(
        snapshot=snapshot,
        skill_key=skill.stable_key,
        support_key=support.stable_key,
    )

    assert result.status == "known"
    assert result.facts["legality_status"] == "socket_compatible"
    assert result.facts["excluded_reasons"] == []
    assert result.facts["support_candidate_status"] == "hard_compatible"


def test_build_socket_support_legality_e2e_sample_reports_result_shape():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support_skill = pg.GraphNode(
        stable_key="skill:SupportPiercePlayer",
        node_type="active_skill",
        display_name="Support Pierce",
        source_refs=(source.source_id,),
    )
    projectile_type = pg.GraphNode(
        stable_key="skill_type:projectile",
        node_type="skill_type",
        display_name="Projectile",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem, support, skill, support_skill, projectile_type),
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=gem.stable_key,
                target_key=skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=support.stable_key,
                target_key=support_skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="granted_by",
                source_key=skill.stable_key,
                target_key=gem.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=projectile_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key=support_skill.stable_key,
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Projectile"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                    "support_family": "Pierce",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=skill.stable_key,
                level_or_stage="socket_context",
                requirements={
                    "max_support_count": 1,
                    "socketed_support_keys": [support.stable_key],
                    "socketed_support_families": ["Pierce"],
                    "duplicate_support_policy": "reject_same_support_key",
                },
                source_refs=(source.source_id,),
            ),
        ),
    )

    sample = pg.build_socket_support_legality_e2e_sample(
        snapshot=snapshot,
        skill_key=skill.stable_key,
        support_key=support.stable_key,
    )

    assert sample["query"]["fact_type"] == "socket_support_legality"
    assert sample["result"]["status"] == "unsupported"
    assert sample["result"]["facts"]["excluded_reasons"] == ["duplicate_support"]


def test_build_phase2_mini_e2e_report_aggregates_query_families(tmp_path):
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    resolver_snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem, support),
        edges=(),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SupportGemPierce",
                target_key=support.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
    )

    base_file = tmp_path / "base_items.min.json"
    base_file.write_text(
        json.dumps(
            {
                "Metadata/Items/Weapons/Bows/Bow1": {
                    "name": "Shortbow",
                    "item_class": "Bow",
                    "domain": "item",
                    "drop_level": 1,
                    "tags": ["bow", "weapon", "default"],
                    "requirements": {"level": 1},
                }
            }
        ),
        encoding="utf-8",
    )
    mod_file = tmp_path / "mods.min.json"
    mod_file.write_text(
        json.dumps(
            {
                "LightningDamage1": {
                    "name": "Crackling",
                    "domain": "item",
                    "generation_type": "prefix",
                    "groups": ["LightningDamage"],
                    "required_level": 10,
                    "spawn_weights": [{"tag": "bow", "weight": 1}],
                    "text": "Adds Lightning Damage",
                }
            }
        ),
        encoding="utf-8",
    )
    base_source = pg.GraphSource(
        source_id="repoe:base_items",
        kind="repoe_raw",
        source_file="base_items.min.json",
        expected_count=1,
    )
    mod_source = pg.GraphSource(
        source_id="repoe:mods",
        kind="repoe_raw",
        source_file="mods.min.json",
        expected_count=1,
    )
    base_ingestion = pg.ingest_base_items(base_file, source=base_source)
    mod_ingestion = pg.ingest_mods(mod_file, source=mod_source)
    merged = pg.merge_ingestion_results(base_ingestion, mod_ingestion)
    compute_snapshot = pg.build_snapshot(
        sources=(base_source, mod_source),
        nodes=merged.nodes,
        edges=merged.edges,
        aliases=merged.aliases,
        id_mappings=merged.id_mappings,
        requirement_facts=merged.requirement_facts,
    )
    requirement_resource_snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(gem, support),
        edges=(),
        resource_facts=(
            pg.ResourceFact(
                component_key=support.stable_key,
                level_or_stage="base",
                costs={"cost_multiplier": 100},
                reservations={"spirit": 20},
                source_refs=(source.source_id,),
            ),
        ),
    )
    support_candidate_snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(
            gem,
            support,
            pg.GraphNode(
                stable_key="skill:LightningArrowPlayer",
                node_type="active_skill",
                display_name="Lightning Arrow",
                source_refs=(source.source_id,),
            ),
            pg.GraphNode(
                stable_key="skill:SupportPiercePlayer",
                node_type="active_skill",
                display_name="Support Pierce",
                source_refs=(source.source_id,),
            ),
            pg.GraphNode(
                stable_key="skill_type:projectile",
                node_type="skill_type",
                display_name="Projectile",
                source_refs=(source.source_id,),
            ),
            pg.GraphNode(
                stable_key="skill_type:attack",
                node_type="skill_type",
                display_name="Attack",
                source_refs=(source.source_id,),
            ),
        ),
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=support.stable_key,
                target_key="skill:SupportPiercePlayer",
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="granted_by",
                source_key="skill:LightningArrowPlayer",
                target_key=gem.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key="skill:LightningArrowPlayer",
                target_key="skill_type:projectile",
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key="skill:LightningArrowPlayer",
                target_key="skill_type:attack",
                evidence_refs=(source.source_id,),
            ),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key="skill:SupportPiercePlayer",
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Projectile"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                    "added_types": [],
                    "added_minion_types": [],
                },
                source_refs=(source.source_id,),
            ),
        ),
    )
    passive_snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(
            pg.GraphNode(
                stable_key="passive:pob:0_5:100",
                node_type="passive",
                display_name="Shared Start",
                source_refs=(source.source_id,),
            ),
            pg.GraphNode(
                stable_key="passive:pob:0_5:101",
                node_type="passive",
                display_name="Path Node",
                source_refs=(source.source_id,),
            ),
        ),
        edges=(
            pg.GraphEdge(
                edge_type="connected_to",
                source_key="passive:pob:0_5:100",
                target_key="passive:pob:0_5:101",
                evidence_refs=(source.source_id,),
            ),
        ),
    )

    report = pg.build_phase2_mini_e2e_report(
        resolver_snapshot=resolver_snapshot,
        resolver_node_keys=[gem.stable_key, support.stable_key],
        compute_snapshot=compute_snapshot,
        requirement_snapshot=requirement_resource_snapshot,
        resource_snapshot=requirement_resource_snapshot,
        can_roll_specs=[
            {
                "base_item_key": "item_base:Metadata/Items/Weapons/Bows/Bow1",
                "mod_key": "mod:LightningDamage1",
                "item_level": 12,
            },
            {
                "base_item_key": "item_base:Metadata/Items/Weapons/Bows/Bow1",
                "mod_key": "mod:LightningDamage1",
                "item_level": 5,
            },
        ],
        requirement_specs=[
            {
                "component_key": gem.stable_key,
                "level_or_stage": "base",
            }
        ],
        resource_specs=[
            {
                "component_key": support.stable_key,
                "level_or_stage": "base",
            }
        ],
        support_candidate_snapshot=support_candidate_snapshot,
        support_candidate_specs=[
            {
                "support_key": support.stable_key,
                "skill_key": "skill:LightningArrowPlayer",
            }
        ],
        passive_snapshot=passive_snapshot,
        passive_neighbor_specs=[
            {
                "passive_key": "passive:pob:0_5:100",
            }
        ],
    )

    assert report["sample_count"] == 8
    assert report["family_counts"] == {
        "resolver": 2,
        "can_roll_mod": 2,
        "requirements_for_component": 1,
        "resource_profile_for_component": 1,
        "support_skill_candidate": 1,
        "passive_neighbors": 1,
    }
    assert report["samples"][0]["family"] == "resolver"
    assert report["samples"][2]["family"] == "can_roll_mod"
    assert report["samples"][3]["result"]["facts"]["excluded_reason"] == "item_level_too_low"
    assert report["samples"][4]["family"] == "requirements_for_component"
    assert report["samples"][4]["result"]["status"] == "unknown"
    assert report["samples"][5]["family"] == "resource_profile_for_component"
    assert report["samples"][5]["result"]["facts"]["reservations"]["spirit"] == 20
    assert report["samples"][6]["family"] == "support_skill_candidate"
    assert report["samples"][6]["result"]["facts"]["candidate_status"] == "hard_compatible"
    assert report["samples"][7]["family"] == "passive_neighbors"
    assert report["samples"][7]["result"]["facts"]["neighbor_keys"] == ["passive:pob:0_5:101"]
    assert report["resolver_preflight"]["resolved_count"] == 2


def test_build_phase2_fixed_acceptance_report_summarizes_samples_by_family():
    report = pg.build_phase2_fixed_acceptance_report(
        [
            {
                "family": "resolver",
                "query": {"node_key": "gem:LightningArrow"},
                "result": {"status": "resolved"},
                "review": {"grade": "pass"},
            },
            {
                "family": "resolver",
                "query": {"node_key": "gem:Missing"},
                "result": {"status": "missing"},
                "review": {"grade": "pass"},
            },
            {
                "family": "passive_neighbors",
                "query": {"passive_key": "passive:pob:0_5:100"},
                "result": {
                    "status": "ambiguous",
                    "caveat": "unresolved_passive_connections",
                },
                "review": {"grade": "minor_issue", "notes": "shared-start unresolved ids visible"},
            },
            {
                "family": "support_skill_candidate",
                "query": {
                    "support_key": "support:Pierce",
                    "skill_key": "skill:LightningArrowPlayer",
                },
                "result": {
                    "status": "known",
                    "facts": {"candidate_status": "hard_compatible"},
                },
                "review": {"grade": "pass"},
            },
        ]
    )

    assert report["sample_count"] == 4
    assert report["family_counts"] == {
        "resolver": 2,
        "passive_neighbors": 1,
        "support_skill_candidate": 1,
    }
    assert report["status_counts"] == {
        "resolved": 1,
        "missing": 1,
        "ambiguous": 1,
        "known": 1,
    }
    assert report["families"]["resolver"]["count"] == 2
    assert report["families"]["resolver"]["statuses"] == {"resolved": 1, "missing": 1}
    assert report["families"]["passive_neighbors"]["caveats"] == ["unresolved_passive_connections"]
    assert report["review_counts"] == {"minor_issue": 1, "pass": 3}
    assert report["ready_for_human_review"] is True
    assert report["ready_for_phase2_exit"] is False


def test_build_phase2_fixed_acceptance_report_marks_failures_and_blocks_ready_state():
    report = pg.build_phase2_fixed_acceptance_report(
        [
            {
                "family": "resolver",
                "query": {"node_key": "gem:Bad"},
                "result": {"status": "resolved"},
                "review": {
                    "grade": "fail",
                    "reasons": ["unsupported_id_treated_as_resolved"],
                },
            },
            {
                "family": "passive_neighbors",
                "query": {"passive_key": "passive:pob:0_5:100"},
                "result": {"status": "known"},
                "review": {"grade": "pass"},
            },
        ]
    )

    assert report["review_counts"] == {"fail": 1, "pass": 1}
    assert report["fail_reasons"] == ["unsupported_id_treated_as_resolved"]
    assert report["ready_for_human_review"] is False
    assert report["ready_for_phase2_exit"] is False


def test_build_phase2_fixed_acceptance_report_marks_clean_pass_only_bundle_ready_for_exit():
    report = pg.build_phase2_fixed_acceptance_report(
        [
            {
                "family": "resolver",
                "query": {"node_key": "gem:LightningArrow"},
                "result": {"status": "resolved"},
                "review": {"grade": "pass"},
            },
            {
                "family": "unique_base_item",
                "query": {"unique_key": "unique:pob:the_anvil"},
                "result": {"status": "known"},
                "review": {"grade": "pass"},
            },
        ]
    )

    assert report["ready_for_human_review"] is True
    assert report["ready_for_phase2_exit"] is True


def test_build_phase2_fixed_acceptance_report_counts_new_inventory_and_id_mapping_families():
    report = pg.build_phase2_fixed_acceptance_report(
        [
            {
                "family": "inventory_slot_mapping",
                "query": {"system": "ggg:Inventories", "external_id": "Weapon1"},
                "result": {"status": "resolved"},
                "review": {"grade": "pass"},
            },
            {
                "family": "id_mapping_unsupported",
                "query": {"system": "ggg:PassiveSkills", "external_id": "strength89"},
                "result": {
                    "status": "unsupported",
                    "caveat": "official_passive_string_id_not_vendored",
                },
                "review": {"grade": "pass"},
            },
            {
                "family": "edge_provenance",
                "query": {
                    "edge_type": "connected_to",
                    "source_key": "passive:pob:0_5:100",
                    "target_key": "passive:pob:0_5:101",
                },
                "result": {"status": "known"},
                "review": {"grade": "pass"},
            },
        ]
    )

    assert report["family_counts"]["inventory_slot_mapping"] == 1
    assert report["family_counts"]["id_mapping_unsupported"] == 1
    assert report["family_counts"]["edge_provenance"] == 1


def test_fixed_sample_bundle_can_flow_into_acceptance_report_without_failures():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    weapon = pg.GraphNode(
        stable_key="weapon_type:bow",
        node_type="weapon_type",
        display_name="Bow",
        source_refs=(source.source_id,),
    )
    passive = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Attribute",
        source_refs=(source.source_id,),
    )
    passive_neighbor = pg.GraphNode(
        stable_key="passive:pob:0_5:101",
        node_type="passive",
        display_name="Path Node",
        source_refs=(source.source_id,),
    )
    caveat = pg.GraphNode(
        stable_key="caveat:dual_weapon_state_limited_caveat",
        node_type="caveat",
        display_name="dual_weapon_state_limited_caveat",
        source_refs=(source.source_id,),
    )
    unique = pg.GraphNode(
        stable_key="unique:pob:the_anvil",
        node_type="unique",
        display_name="The Anvil",
        source_refs=(source.source_id,),
    )
    base_item = pg.GraphNode(
        stable_key="item_base:Metadata/Items/Amulets/BloodstoneAmulet",
        node_type="item_base",
        display_name="Bloodstone Amulet",
        source_refs=(source.source_id,),
    )
    mod = pg.GraphNode(
        stable_key="mod:MovementSpeed1",
        node_type="mod",
        display_name="of Movement",
        source_refs=(source.source_id,),
    )
    item_tag = pg.GraphNode(
        stable_key="tag:item:default",
        node_type="item_tag",
        display_name="default",
        source_refs=(source.source_id,),
    )
    support_skill = pg.GraphNode(
        stable_key="skill:SupportPiercePlayer",
        node_type="active_skill",
        display_name="Support Pierce",
        source_refs=(source.source_id,),
    )
    projectile_type = pg.GraphNode(
        stable_key="skill_type:projectile",
        node_type="skill_type",
        display_name="Projectile",
        source_refs=(source.source_id,),
    )
    attack_type = pg.GraphNode(
        stable_key="skill_type:attack",
        node_type="skill_type",
        display_name="Attack",
        source_refs=(source.source_id,),
    )
    inventory_slot = pg.GraphNode(
        stable_key="inventory_slot:Weapon1",
        node_type="inventory_slot",
        display_name="Weapon 1",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(
            gem,
            support,
            skill,
            weapon,
            passive,
            passive_neighbor,
            caveat,
            unique,
            base_item,
            mod,
            item_tag,
            support_skill,
            projectile_type,
            attack_type,
            inventory_slot,
        ),
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=gem.stable_key,
                target_key=skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=support.stable_key,
                target_key=support_skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="granted_by",
                source_key=skill.stable_key,
                target_key=gem.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="connected_to",
                source_key=passive.stable_key,
                target_key=passive_neighbor.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_base",
                source_key=unique.stable_key,
                target_key=base_item.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_tag",
                source_key=base_item.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="applies_to_tag",
                source_key=mod.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="requires_weapon_type",
                source_key=skill.stable_key,
                target_key=weapon.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=projectile_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=attack_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        aliases=(
            pg.GraphAlias("Lightning Arrow", gem.stable_key, (source.source_id,)),
            pg.GraphAlias("Lightning Arrow", skill.stable_key, (source.source_id,)),
        ),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SupportGemPierce",
                target_key=support.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="pob:passive_skill_node_id",
                external_id="32183",
                target_key=passive.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:PassiveSkills",
                external_id="strength89",
                target_key=None,
                source_refs=(source.source_id,),
                status="unsupported",
                caveat="official_passive_string_id_not_vendored",
            ),
            pg.GraphIdMapping(
                system="ggg:Inventories",
                external_id="Weapon1",
                target_key=inventory_slot.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:Words:UniqueName",
                external_id="The Anvil",
                target_key=unique.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key=base_item.stable_key,
                level_or_stage="base",
                requirements={"domain": "item", "drop_level": 1},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=mod.stable_key,
                level_or_stage="base",
                requirements={
                    "domain": "item",
                    "required_level": 70,
                    "generation_type": "suffix",
                    "groups": ["MovementSpeed"],
                    "text": "increased Movement Speed",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=gem.stable_key,
                level_or_stage="base",
                requirements={"level": 1, "dex": 9},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=support_skill.stable_key,
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Projectile", "Attack", "AND"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                    "added_types": [],
                    "added_minion_types": [],
                    "support_family": "Pierce",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=skill.stable_key,
                level_or_stage="socket_context",
                requirements={
                    "max_support_count": 1,
                    "socketed_support_keys": [support.stable_key],
                    "socketed_support_families": ["Pierce"],
                    "duplicate_support_policy": "reject_same_support_key",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=caveat.stable_key,
                level_or_stage="component_set",
                requirements={
                    "component_keys": [passive.stable_key, skill.stable_key],
                    "trigger_condition": "weapon_set_passives_used_without_dual_state_scores",
                    "modelability_effect": "limited",
                    "reward_eligibility_effect": "limited",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=passive.stable_key,
                level_or_stage="weapon_set_overlay",
                requirements={
                    "allocation_states": ["weapon_set_1"],
                    "weapon_set_point_conversion": 24,
                    "state_specific_reachability": True,
                },
                source_refs=(source.source_id,),
                status="ambiguous",
                confidence=0.5,
            ),
        ),
        resource_facts=(
            pg.ResourceFact(
                component_key=skill.stable_key,
                level_or_stage="1",
                costs={"mana": 6},
                reservations={},
                source_refs=(source.source_id,),
            ),
        ),
        passive_choices=(
            pg.PassiveChoice(
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                parent_passive_key=passive.stable_key,
                display_name="Attribute",
                source_refs=(source.source_id,),
            ),
        ),
        allocation_options=(
            pg.AllocationOption(
                option_key="allocation_option:passive:pob:0_5:100:26297",
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                display_name="Strength",
                stat_text="+5 to Strength",
                source_refs=(source.source_id,),
            ),
        ),
    )

    bundle = pg.build_phase2_fixed_sample_bundle(
        snapshot=snapshot,
        gem_key=gem.stable_key,
        skill_key=skill.stable_key,
        support_key=support.stable_key,
        passive_key=passive.stable_key,
        unique_key=unique.stable_key,
        caveat_key=caveat.stable_key,
    )
    reviewed_samples = [{**sample, "review": {"grade": "pass"}} for sample in bundle["samples"]]
    report = pg.build_phase2_fixed_acceptance_report(reviewed_samples)

    assert report["sample_count"] == bundle["sample_count"]
    assert report["families"]["can_roll_mod"]["statuses"] == {"known": 1}
    assert report["families"]["requirements_for_component"]["statuses"] == {"known": 1}
    assert report["families"]["resource_profile_for_component"]["statuses"] == {"known": 1}
    assert report["ready_for_human_review"] is True
    assert report["ready_for_phase2_exit"] is True


def test_build_phase2_acceptance_artifact_wraps_bundle_and_report():
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    weapon = pg.GraphNode(
        stable_key="weapon_type:bow",
        node_type="weapon_type",
        display_name="Bow",
        source_refs=(source.source_id,),
    )
    passive = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Attribute",
        source_refs=(source.source_id,),
    )
    passive_neighbor = pg.GraphNode(
        stable_key="passive:pob:0_5:101",
        node_type="passive",
        display_name="Path Node",
        source_refs=(source.source_id,),
    )
    caveat = pg.GraphNode(
        stable_key="caveat:dual_weapon_state_limited_caveat",
        node_type="caveat",
        display_name="dual_weapon_state_limited_caveat",
        source_refs=(source.source_id,),
    )
    unique = pg.GraphNode(
        stable_key="unique:pob:the_anvil",
        node_type="unique",
        display_name="The Anvil",
        source_refs=(source.source_id,),
    )
    base_item = pg.GraphNode(
        stable_key="item_base:Metadata/Items/Amulets/BloodstoneAmulet",
        node_type="item_base",
        display_name="Bloodstone Amulet",
        source_refs=(source.source_id,),
    )
    mod = pg.GraphNode(
        stable_key="mod:MovementSpeed1",
        node_type="mod",
        display_name="of Movement",
        source_refs=(source.source_id,),
    )
    item_tag = pg.GraphNode(
        stable_key="tag:item:default",
        node_type="item_tag",
        display_name="default",
        source_refs=(source.source_id,),
    )
    support_skill = pg.GraphNode(
        stable_key="skill:SupportPiercePlayer",
        node_type="active_skill",
        display_name="Support Pierce",
        source_refs=(source.source_id,),
    )
    projectile_type = pg.GraphNode(
        stable_key="skill_type:projectile",
        node_type="skill_type",
        display_name="Projectile",
        source_refs=(source.source_id,),
    )
    attack_type = pg.GraphNode(
        stable_key="skill_type:attack",
        node_type="skill_type",
        display_name="Attack",
        source_refs=(source.source_id,),
    )
    inventory_slot = pg.GraphNode(
        stable_key="inventory_slot:Weapon1",
        node_type="inventory_slot",
        display_name="Weapon 1",
        source_refs=(source.source_id,),
    )
    snapshot = pg.build_snapshot(
        sources=(source,),
        nodes=(
            gem,
            support,
            skill,
            weapon,
            passive,
            passive_neighbor,
            caveat,
            unique,
            base_item,
            mod,
            item_tag,
            support_skill,
            projectile_type,
            attack_type,
            inventory_slot,
        ),
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=gem.stable_key,
                target_key=skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=support.stable_key,
                target_key=support_skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="granted_by",
                source_key=skill.stable_key,
                target_key=gem.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="connected_to",
                source_key=passive.stable_key,
                target_key=passive_neighbor.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_base",
                source_key=unique.stable_key,
                target_key=base_item.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_tag",
                source_key=base_item.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="applies_to_tag",
                source_key=mod.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="requires_weapon_type",
                source_key=skill.stable_key,
                target_key=weapon.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=projectile_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=attack_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        aliases=(
            pg.GraphAlias("Lightning Arrow", gem.stable_key, (source.source_id,)),
            pg.GraphAlias("Lightning Arrow", skill.stable_key, (source.source_id,)),
        ),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SupportGemPierce",
                target_key=support.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="pob:passive_skill_node_id",
                external_id="32183",
                target_key=passive.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:PassiveSkills",
                external_id="strength89",
                target_key=None,
                source_refs=(source.source_id,),
                status="unsupported",
                caveat="official_passive_string_id_not_vendored",
            ),
            pg.GraphIdMapping(
                system="ggg:Inventories",
                external_id="Weapon1",
                target_key=inventory_slot.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:Words:UniqueName",
                external_id="The Anvil",
                target_key=unique.stable_key,
                source_refs=(source.source_id,),
            ),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key=base_item.stable_key,
                level_or_stage="base",
                requirements={"domain": "item", "drop_level": 1},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=mod.stable_key,
                level_or_stage="base",
                requirements={
                    "domain": "item",
                    "required_level": 70,
                    "generation_type": "suffix",
                    "groups": ["MovementSpeed"],
                    "text": "increased Movement Speed",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=gem.stable_key,
                level_or_stage="base",
                requirements={"level": 1, "dex": 9},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=support_skill.stable_key,
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Projectile", "Attack", "AND"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                    "added_types": [],
                    "added_minion_types": [],
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=caveat.stable_key,
                level_or_stage="component_set",
                requirements={
                    "component_keys": [passive.stable_key, skill.stable_key],
                    "trigger_condition": "weapon_set_passives_used_without_dual_state_scores",
                    "modelability_effect": "limited",
                    "reward_eligibility_effect": "limited",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=passive.stable_key,
                level_or_stage="weapon_set_overlay",
                requirements={
                    "allocation_states": ["weapon_set_1"],
                    "documented_weapon_set_indices": [0, 1, 2],
                    "weapon_set_point_conversion": 24,
                    "state_specific_reachability": True,
                },
                source_refs=(source.source_id,),
                status="ambiguous",
                confidence=0.5,
            ),
        ),
        resource_facts=(
            pg.ResourceFact(
                component_key=skill.stable_key,
                level_or_stage="1",
                costs={"mana": 6},
                reservations={},
                source_refs=(source.source_id,),
            ),
        ),
        passive_choices=(
            pg.PassiveChoice(
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                parent_passive_key=passive.stable_key,
                display_name="Attribute",
                source_refs=(source.source_id,),
            ),
        ),
        allocation_options=(
            pg.AllocationOption(
                option_key="allocation_option:passive:pob:0_5:100:26297",
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                display_name="Strength",
                stat_text="+5 to Strength",
                source_refs=(source.source_id,),
            ),
        ),
    )

    artifact = pg.build_phase2_acceptance_artifact(
        snapshot=snapshot,
        gem_key=gem.stable_key,
        skill_key=skill.stable_key,
        support_key=support.stable_key,
        passive_key=passive.stable_key,
        unique_key=unique.stable_key,
        caveat_key=caveat.stable_key,
        default_review_grade="pass",
    )

    assert artifact["bundle"]["sample_count"] >= 15
    assert artifact["acceptance_report"]["families"]["can_roll_mod"]["statuses"] == {"known": 1}
    assert artifact["acceptance_report"]["families"]["requirements_for_component"]["statuses"] == {
        "known": 1
    }
    assert artifact["acceptance_report"]["families"]["resource_profile_for_component"][
        "statuses"
    ] == {"known": 1}
    assert artifact["acceptance_report"]["ready_for_phase2_exit"] is True


def test_run_phase2_acceptance_artifact_script_writes_json(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    output_path = repo_root / "phase2_acceptance_artifact.json"
    report_path = repo_root / "phase2_acceptance_report.md"
    previous_payload = output_path.read_text(encoding="utf-8") if output_path.exists() else None
    previous_report = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    try:
        result = subprocess.run(
            [
                str(repo_root / ".tools" / "uv" / "uv.exe"),
                "run",
                "python",
                "scripts/run_phase2_acceptance_artifact.py",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        assert output_path.exists()
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["bundle"]["sample_count"] >= 19
        assert payload["acceptance_report"]["ready_for_human_review"] is True
        assert payload["acceptance_report"]["ready_for_phase2_exit"] is False
        assert payload["acceptance_report"]["review_counts"] == {}
        assert report_path.exists()
        report_text = report_path.read_text(encoding="utf-8")
        assert "# Phase 2 E2E 样例人工验收报告" in report_text
        assert "- 样例总数：19" in report_text
        assert "- Phase 2 出关状态：待人工评分" in report_text
        assert (
            "| socket/support hard constraint | covered | socket_support_legality |" in report_text
        )
        assert (
            "| modelability caveat component set | covered | caveat_component_set |" in report_text
        )
        assert str(output_path) in result.stdout
        assert str(report_path) in result.stdout
    finally:
        if previous_payload is None:
            if output_path.exists():
                output_path.unlink()
        else:
            output_path.write_text(previous_payload, encoding="utf-8")
        if previous_report is None:
            if report_path.exists():
                report_path.unlink()
        else:
            report_path.write_text(previous_report, encoding="utf-8")


def test_run_phase2_acceptance_artifact_script_can_emit_reviewed_pass_report(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    output_path = repo_root / "phase2_acceptance_artifact.json"
    report_path = repo_root / "phase2_acceptance_report.md"
    previous_payload = output_path.read_text(encoding="utf-8") if output_path.exists() else None
    previous_report = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    try:
        result = subprocess.run(
            [
                str(repo_root / ".tools" / "uv" / "uv.exe"),
                "run",
                "python",
                "scripts/run_phase2_acceptance_artifact.py",
                "--default-review-grade",
                "pass",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )

        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["bundle"]["sample_count"] == 19
        assert payload["acceptance_report"]["ready_for_human_review"] is True
        assert payload["acceptance_report"]["ready_for_phase2_exit"] is True
        assert payload["acceptance_report"]["review_counts"] == {"pass": 19}
        report_text = report_path.read_text(encoding="utf-8")
        assert "- Phase 2 出关状态：可出关" in report_text
        assert "- ready_for_phase2_exit：true" in report_text
        assert "已预填人工评分：pass x 19" in report_text
        assert "当前报告未预填人工评分" not in report_text
        assert str(report_path) in result.stdout
    finally:
        if previous_payload is None:
            if output_path.exists():
                output_path.unlink()
        else:
            output_path.write_text(previous_payload, encoding="utf-8")
        if previous_report is None:
            if report_path.exists():
                report_path.unlink()
        else:
            report_path.write_text(previous_report, encoding="utf-8")


def test_validation_caveat_exposes_context_type_enum():
    from pydantic import ValidationError

    from server.knowledge import graph_tools

    try:
        graph_tools.SupportSkillCandidateInput.model_validate(
            {
                "support_key": "support:Execute",
                "skill_key": "skill:SparkPlayer",
                "context": {},
            }
        )
        raise AssertionError("expected context validation to fail")
    except ValidationError as exc:
        caveat = graph_tools._validation_caveat(exc)

    assert "context_type must be one of" in caveat
    assert "version_context" in caveat
    assert "build_state_context" in caveat

    try:
        graph_tools.SupportSkillCandidateInput.model_validate(
            {
                "support_key": "support:Execute",
                "skill_key": "skill:SparkPlayer",
                "context": "not-an-object",
            }
        )
        raise AssertionError("expected context validation to fail")
    except ValidationError as exc:
        string_caveat = graph_tools._validation_caveat(exc)

    assert "context_type must be one of" in string_caveat

    try:
        graph_tools.SupportSkillCandidateInput.model_validate(
            {
                "support_key": "support:Execute",
                "skill_key": "skill:SparkPlayer",
                "context": {"context_type": "typo"},
            }
        )
        raise AssertionError("expected context validation to fail")
    except ValidationError as exc:
        wrong_tag_caveat = graph_tools._validation_caveat(exc)

    assert "context_type must be one of" in wrong_tag_caveat
    assert "version_context" in wrong_tag_caveat


def test_ingest_passive_tree_aliases_renamed_ascendancy_to_canonical_key(tmp_path):
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(
        json.dumps(
            {
                "classes": [
                    {
                        "name": "Witch",
                        "integerId": 2,
                        "ascendancies": [
                            {
                                "id": "Lich",
                                "internalId": "Witch3",
                                "name": "Lich",
                                "replaceBy": "Abyssal Lich",
                            },
                            {
                                "id": "Abyssal Lich",
                                "internalId": "Witch3b",
                                "name": "Abyssal Lich",
                                "replace": "Lich",
                            },
                        ],
                    }
                ],
                "groups": [{"nodes": [28431], "orbits": [0], "x": 0, "y": 0}],
                "nodes": {
                    "28431": {
                        "ascendancyName": "Lich",
                        "connections": [],
                        "group": 1,
                        "icon": "asc.dds",
                        "isNotable": True,
                        "name": "Eternal Life",
                        "orbit": 0,
                        "orbitIndex": 0,
                        "skill": 28431,
                        "stats": [],
                    }
                },
                "tree": "0_5",
            }
        ),
        encoding="utf-8",
    )
    source = pg.GraphSource(
        source_id="pob:passive_tree",
        kind="pob_tree",
        source_file="TreeData/0_5/tree.json",
        expected_count=0,
    )
    ingestion = pg.ingest_passive_tree(tree_file, source=source, tree_version="0_5")

    node_keys = {node.stable_key for node in ingestion.nodes}
    assert "ascendancy:witch:abyssal_lich" in node_keys
    assert "ascendancy:witch:lich" not in node_keys

    edge_pairs = {(edge.source_key, edge.target_key) for edge in ingestion.edges}
    assert ("notable:pob:0_5:28431", "ascendancy:witch:abyssal_lich") in edge_pairs
    assert ("ascendancy:witch:abyssal_lich", "class:witch") in edge_pairs
    assert not any(
        source_key == "notable:pob:0_5:28431" and target_key == "ascendancy:witch:lich"
        for source_key, target_key in edge_pairs
    )

    alias_targets = {
        alias.alias: alias.target_key
        for alias in ingestion.aliases
        if alias.target_key.startswith("ascendancy:")
    }
    assert alias_targets["Lich"] == "ascendancy:witch:abyssal_lich"

    mapping_targets = {
        (mapping.system, mapping.external_id): mapping.target_key
        for mapping in ingestion.id_mappings
    }
    assert mapping_targets[("pob:ascendancy_id", "Lich")] == "ascendancy:witch:abyssal_lich"
    assert (
        mapping_targets[("pob:ascendancy_internal_id", "Witch3")] == "ascendancy:witch:abyssal_lich"
    )
    assert (
        mapping_targets[("pob:ascendancy_internal_id", "Witch3b")]
        == "ascendancy:witch:abyssal_lich"
    )
