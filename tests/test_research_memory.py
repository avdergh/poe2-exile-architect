from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

from server.knowledge import mature_learning
from server.knowledge import graph_tools as gt
from server.knowledge import physical_graph as pg
from server.knowledge import research_memory
from server.knowledge import research_identity
from server.knowledge import research_models
from server.knowledge import research_packet
from server.knowledge import skill_equivalence


def _tables(con: sqlite3.Connection) -> set[str]:
    return {
        str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _graph_service(
    *,
    extra_nodes: list[pg.GraphNode] | None = None,
    extra_aliases: list[pg.GraphAlias] | None = None,
) -> gt.GraphQueryService:
    source = pg.GraphSource(
        source_id="fixture:phase4",
        kind="test_fixture",
        source_file="tests/test_research_memory.py",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
    )
    nodes = (
        pg.GraphNode("gem:A", "skill_gem", "A", (source.source_id,)),
        pg.GraphNode("mechanic:BC", "mechanic", "BC", (source.source_id,)),
        pg.GraphNode("gem:AB", "skill_gem", "AB", (source.source_id,)),
        pg.GraphNode("mechanic:C", "mechanic", "C", (source.source_id,)),
        pg.GraphNode(
            "skill:LightningArrowPlayer", "active_skill", "Lightning Arrow", (source.source_id,)
        ),
        pg.GraphNode(
            "gem:Metadata/Items/Gems/SkillGemLightningArrow",
            "skill_gem",
            "Lightning Arrow",
            (source.source_id,),
        ),
        pg.GraphNode(
            "ascendancy:monk:martial_artist",
            "ascendancy",
            "Martial Artist",
            (source.source_id,),
        ),
        pg.GraphNode("support:Scattershot", "support_gem", "Scattershot", (source.source_id,)),
        pg.GraphNode("passive:pob:0_5:100", "passive", "Projectile Cluster", (source.source_id,)),
        pg.GraphNode(
            "caveat:projectile_floor", "caveat", "Projectile floor caveat", (source.source_id,)
        ),
        *(extra_nodes or []),
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="snapshot:phase4",
        created_at=datetime(2026, 7, 2, tzinfo=UTC),
        sources=(source,),
        nodes=nodes,
        aliases=tuple(extra_aliases or ()),
        edges=(
            pg.GraphEdge(
                "grants_skill",
                "gem:Metadata/Items/Gems/SkillGemLightningArrow",
                "skill:LightningArrowPlayer",
                (source.source_id,),
            ),
            pg.GraphEdge(
                "granted_by",
                "skill:LightningArrowPlayer",
                "gem:Metadata/Items/Gems/SkillGemLightningArrow",
                (source.source_id,),
            ),
        ),
    )
    return gt.GraphQueryService.from_snapshot(snapshot)


def _fragment_payload(title: str = "Projectile overlap principle") -> dict[str, object]:
    return {
        "schema_version": 4,
        "fragments": [
            {
                "fragment_type": "mechanic",
                "title": title,
                "summary": "Projectile builds can scale clear when extra projectiles preserve single-target checks.",
                "reusable_principle": "Treat projectile count as conditional coverage until Judge verifies target context.",
                "source_case_refs": ["case:la-safe"],
                "safe_evidence_refs": ["safe:la:hash"],
                "confidence": "medium",
                "copyability_risk": "low",
                "lifecycle_stages": ["endgame_budget"],
                "modelability": "partial",
                "verification_tasks": ["Run selected-skill Judge readback for projectile count."],
                "component_keys": ["skill:LightningArrowPlayer", "support:Scattershot"],
                "conditions": ["projectile context"],
                "risks": ["single-target overclaim"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "0.22.0",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
        "semantic_edges": [],
    }


def _resolution_evidence(stable_key: str) -> dict[str, object]:
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": stable_key,
        "snapshot_id": "snapshot:phase4",
        "evidence_path_nodes": [stable_key],
        "source_refs": ["fixture:phase4"],
    }


def _edge_payload(
    source: str, target: str, edge_type: str = "synergizes_with"
) -> dict[str, object]:
    return {
        "schema_version": 4,
        "fragments": [],
        "semantic_edges": [
            {
                "source_key": source,
                "target_key": target,
                "source_resolution": _resolution_evidence(source),
                "target_resolution": _resolution_evidence(target),
                "edge_type": edge_type,
                "rationale": "Safe mechanism-level relationship, not a build recipe.",
                "source_case_refs": ["case:la-safe"],
                "safe_evidence_refs": ["safe:la:hash"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "status": "valid",
                "confidence": "medium",
                "modelability": "partial",
                "copy_safety_state": "passed",
                "context_requirements": [
                    {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_budget"]}
                ],
                "affected_component_keys": [source, target],
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
                "directionality": "associative"
                if edge_type == "synergizes_with"
                else "directional",
            }
        ],
    }


def _deep_record_payload(content: str = "投射物覆盖依赖主技能与辅助共同改变清图范围。") -> dict:
    return {
        "schema_version": 5,
        "deep_research_records": [
            {
                "research_group_id": "research:la-safe",
                "record_kind": "mechanic_chain",
                "title": "投射物覆盖机制链",
                "summary": "记录主技能与辅助如何共同形成覆盖，并保留单体复核条件。",
                "content": content,
                "content_language": "zh-CN",
                "length_exception_reason": None,
                "component_keys": ["skill:LightningArrowPlayer", "support:Scattershot"],
                "component_mentions": [],
                "source_case_refs": ["case:la-safe"],
                "safe_evidence_refs": ["safe:la:hash"],
                "conditions": ["投射物命中环境成立"],
                "failure_conditions": ["单体重叠未经验证"],
                "typed_payload": {"roles": ["delivery", "coverage"]},
                "class_key": None,
                "ascendancy_key": None,
                "extraction_method_version": "deep_research_mvp_v1",
                "record_schema_version": 1,
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "0.22.0",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
    }


def test_build_family_identity_uses_only_ascendancy_and_core_skills():
    payload = _deep_record_payload()
    record = payload["deep_research_records"][0]
    record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    record["component_mentions"] = [
        {
            "role": "primary_damage",
            "component_key": "skill:LightningArrowPlayer",
        },
        {"role": "clear_skill", "component_key": "skill:ClearSkillPlayer"},
        {"role": "support_modifier", "component_key": "support:Scattershot"},
        {"role": "unique_enabler", "component_key": "unique:Fixture"},
        {"role": "defense_layer", "component_key": "keystone:Fixture"},
    ]

    family = research_identity.infer_build_family([record])

    assert family is not None
    assert family.ascendancy_key == "ascendancy:monk:martial_artist"
    assert family.primary_skill_key == "skill:LightningArrowPlayer"
    assert family.secondary_skill_keys == ("skill:ClearSkillPlayer",)


def test_build_family_ignores_generic_secondary_but_accepts_explicit_core_skill():
    record = _deep_record_payload()["deep_research_records"][0]
    record["ascendancy_key"] = "ascendancy:ranger:deadeye"
    record["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:IceShotPlayer"},
        {"role": "secondary_skill", "component_key": "skill:TornadoShotPlayer"},
        {"role": "generator", "component_key": "skill:LightningRodPlayer"},
    ]

    variant_family = research_identity.infer_build_family([record])
    record["typed_payload"] = {"familyCoreSkillKeys": ["skill:LightningRodPlayer"]}
    explicit_family = research_identity.infer_build_family([record])

    assert variant_family is not None
    assert variant_family.secondary_skill_keys == ()
    assert explicit_family is not None
    assert explicit_family.secondary_skill_keys == ("skill:LightningRodPlayer",)


def test_trigger_host_and_payload_form_a_deterministic_family_pair():
    trigger_record = _deep_record_payload()["deep_research_records"][0]
    trigger_record["record_kind"] = "skill_package"
    trigger_record["ascendancy_key"] = "ascendancy:sorceress:stormweaver"
    trigger_record["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:SparkPlayer"},
        {"role": "trigger_host", "component_key": "skill:MetaCastOnCritPlayer"},
        {"role": "triggered_payload", "component_key": "skill:CometPlayer"},
    ]
    automatic = research_identity.infer_build_family([trigger_record])
    trigger_record["typed_payload"] = {"familyCoreSkillKeys": ["skill:MetaCastOnCritPlayer"]}
    explicitly_declared = research_identity.infer_build_family([trigger_record])

    assert automatic is not None
    assert automatic.secondary_skill_keys == ("skill:CometPlayer",)
    assert explicitly_declared is not None
    assert explicitly_declared.secondary_skill_keys == (
        "skill:CometPlayer",
        "skill:MetaCastOnCritPlayer",
    )


def test_trigger_host_enters_family_identity_only_when_declared():
    trigger_record = _deep_record_payload()["deep_research_records"][0]
    trigger_record["record_kind"] = "skill_package"
    trigger_record["ascendancy_key"] = "ascendancy:druid:oracle"
    trigger_record["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:CometPlayer"},
        {"role": "trigger_host", "component_key": "skill:MetaSpellslingerPlayer"},
        {"role": "trigger_host", "component_key": "skill:MetaCastOnCritPlayer"},
    ]

    automatic = research_identity.infer_build_family([trigger_record])
    assert automatic is not None
    assert automatic.secondary_skill_keys == ()

    trigger_record["typed_payload"] = {"familyCoreSkillKeys": ["skill:MetaCastOnCritPlayer"]}
    declared = research_identity.infer_build_family([trigger_record])
    assert declared is not None
    assert declared.secondary_skill_keys == ("skill:MetaCastOnCritPlayer",)


def test_unpaired_trigger_host_does_not_change_family_identity():
    primary = _deep_record_payload()["deep_research_records"][0]
    primary["record_kind"] = "skill_package"
    primary["ascendancy_key"] = "ascendancy:sorceress:stormweaver"
    primary["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:SparkPlayer"},
        {"role": "trigger_host", "component_key": "skill:MetaCastOnCritPlayer"},
        {"role": "triggered_payload", "component_key": "skill:CometPlayer"},
    ]
    caveat = _deep_record_payload()["deep_research_records"][0]
    caveat["record_kind"] = "modelability_caveat"
    caveat["ascendancy_key"] = "ascendancy:sorceress:stormweaver"
    caveat["component_mentions"] = [
        {"role": "trigger_host", "component_key": "skill:MetaSpellslingerPlayer"}
    ]

    family = research_identity.infer_build_family([primary, caveat])

    assert family is not None
    assert "skill:MetaSpellslingerPlayer" not in family.secondary_skill_keys


def test_modelability_caveat_payload_does_not_change_family_identity():
    primary = _deep_record_payload()["deep_research_records"][0]
    primary["record_kind"] = "skill_package"
    primary["ascendancy_key"] = "ascendancy:sorceress:stormweaver"
    primary["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:SparkPlayer"},
        {"role": "trigger_host", "component_key": "skill:MetaCastOnCritPlayer"},
        {"role": "triggered_payload", "component_key": "skill:CometPlayer"},
    ]
    caveat = _deep_record_payload()["deep_research_records"][0]
    caveat["record_kind"] = "modelability_caveat"
    caveat["ascendancy_key"] = "ascendancy:sorceress:stormweaver"
    caveat["component_mentions"] = [
        {"role": "triggered_payload", "component_key": "skill:ExplosiveTransmutationPlayer"}
    ]

    family = research_identity.infer_build_family([primary, caveat])

    assert family is not None
    assert family.secondary_skill_keys == ("skill:CometPlayer",)


def test_resource_knowledge_identity_uses_structured_mechanisms_without_graph_nodes():
    record = _deep_record_payload()["deep_research_records"][0]
    record["record_kind"] = "resource_engine"
    record["ascendancy_key"] = "ascendancy:ranger:deadeye"
    record["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:LightningArrowPlayer"}
    ]
    family = research_identity.infer_build_family([record])

    assert family is not None
    assert research_identity.knowledge_key(record, family) is None

    record["typed_payload"] = {
        "resourceMechanisms": ["mana_leech", "mana_flask", "mana_gear_affix"]
    }
    identity = research_identity.knowledge_identity(record, family)

    assert identity is not None
    assert identity["role_components"] == [
        ("resource_mechanism", "mana_flask"),
        ("resource_mechanism", "mana_gear_affix"),
        ("resource_mechanism", "mana_leech"),
    ]


def test_structured_resource_identity_upgrades_same_unkeyed_record(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite", graph_service=_graph_service()
    )
    payload = _deep_record_payload()
    record = payload["deep_research_records"][0]
    record["record_kind"] = "resource_engine"
    record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        }
    ]

    unkeyed = service.propose_deep_research_records(payload)
    record["typed_payload"] = {"resourceMechanisms": ["mana_leech", "mana_flask"]}
    upgraded = service.propose_deep_research_records(payload)

    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        con.execute("UPDATE deep_research_records SET typed_payload = '{}' ")
        con.commit()
    finally:
        con.close()
    repaired_payload = service.propose_deep_research_records(payload)

    assert unkeyed["unkeyedRecordCount"] == 1
    assert upgraded["createdRecordCount"] == 0
    assert upgraded["updatedRecordCount"] == 1
    assert upgraded["unkeyedRecordCount"] == 0
    assert upgraded["evidenceAddedCount"] == 1
    assert repaired_payload["createdRecordCount"] == 0
    assert repaired_payload["updatedRecordCount"] == 1
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT knowledge_key, evidence_count, typed_payload FROM deep_research_records"
        ).fetchone()
        assert row["knowledge_key"] is not None
        assert row["evidence_count"] == 1
        assert json.loads(row["typed_payload"])["resourceMechanisms"] == [
            "mana_leech",
            "mana_flask",
        ]
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 1
    finally:
        con.close()


def test_skill_package_knowledge_identity_preserves_support_variants():
    first = _deep_record_payload()["deep_research_records"][0]
    first["record_kind"] = "skill_package"
    first["ascendancy_key"] = "ascendancy:monk:martial_artist"
    first["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:LightningArrowPlayer"},
        {"role": "support_modifier", "component_key": "support:Scattershot"},
    ]
    second = json.loads(json.dumps(first))
    second["component_mentions"][1]["component_key"] = "support:DifferentSupport"
    family = research_identity.infer_build_family([first, second])

    assert family is not None
    assert research_identity.knowledge_key(first, family) != research_identity.knowledge_key(
        second, family
    )


def test_structured_support_packages_preserve_socket_ownership_in_identity():
    first = _deep_record_payload()["deep_research_records"][0]
    first["record_kind"] = "skill_package"
    first["ascendancy_key"] = "ascendancy:sorceress:stormweaver"
    first["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:SparkPlayer"},
        {"role": "trigger_host", "component_key": "skill:MetaCastOnCritPlayer"},
        {"role": "triggered_payload", "component_key": "skill:CometPlayer"},
        {"role": "support_modifier", "component_key": "support:Execute"},
        {"role": "support_modifier", "component_key": "support:SpellCascade"},
    ]
    first["typed_payload"] = {
        "supportPackages": [
            {"skillKey": "skill:SparkPlayer", "supportKeys": ["support:Execute"]},
            {
                "skillKey": "skill:MetaCastOnCritPlayer",
                "supportKeys": ["support:SpellCascade"],
            },
        ]
    }
    second = json.loads(json.dumps(first))
    second["typed_payload"]["supportPackages"] = [
        {"skillKey": "skill:SparkPlayer", "supportKeys": ["support:SpellCascade"]},
        {
            "skillKey": "skill:MetaCastOnCritPlayer",
            "supportKeys": ["support:Execute"],
        },
    ]
    family = research_identity.infer_build_family([first, second])

    assert family is not None
    assert research_identity.knowledge_key(first, family) != research_identity.knowledge_key(
        second, family
    )


def test_source_specific_random_record_is_hidden_from_normal_retrieval(tmp_path):
    mutated_unique = pg.GraphNode(
        "unique:MutatedFixture",
        "unique",
        "Mutated Fixture",
        ("fixture:phase4",),
    )
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(extra_nodes=[mutated_unique]),
    )
    payload = _deep_record_payload()
    record = payload["deep_research_records"][0]
    record["record_kind"] = "gear_synergy"
    record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    record["component_keys"] = [
        "skill:LightningArrowPlayer",
        "unique:MutatedFixture",
    ]
    record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        },
        {
            "candidate_name": "Mutated Fixture",
            "role": "unique_enabler",
            "resolver_query": "Mutated Fixture",
            "expected_node_types": ["unique"],
            "scope": "any",
            "component_key": "unique:MutatedFixture",
            "resolution_status": "resolved",
        },
    ]
    record["typed_payload"] = {
        "availability": "source_specific_random",
        "sourceSpecificComponentKeys": ["unique:MutatedFixture"],
    }
    accepted = service.propose_deep_research_records(payload)

    normal = service.query_research_memory("", component_keys=["skill:LightningArrowPlayer"])
    audit = service.query_research_memory(
        "", record_ids=accepted["recordIds"], detail_level="record"
    )

    assert normal["deepResearchRecords"] == []
    assert [row["recordId"] for row in audit["deepResearchRecords"]] == accepted["recordIds"]


def test_source_specific_random_record_has_a_distinct_knowledge_identity():
    standard = _deep_record_payload()["deep_research_records"][0]
    standard["record_kind"] = "gear_synergy"
    standard["ascendancy_key"] = "ascendancy:monk:martial_artist"
    standard["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:LightningArrowPlayer"},
        {"role": "unique_enabler", "component_key": "unique:Fixture"},
    ]
    random_instance = json.loads(json.dumps(standard))
    random_instance["typed_payload"] = {
        "availability": "source_specific_random",
        "sourceSpecificComponentKeys": ["unique:Fixture"],
    }
    family = research_identity.infer_build_family([standard, random_instance])

    assert family is not None
    assert research_identity.knowledge_key(standard, family) != research_identity.knowledge_key(
        random_instance, family
    )


def test_skill_package_requires_structured_support_ownership():
    payload = _deep_record_payload()
    record = payload["deep_research_records"][0]
    record["record_kind"] = "skill_package"
    record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        },
        {
            "candidate_name": "Scattershot",
            "role": "support_modifier",
            "resolver_query": "Scattershot",
            "expected_node_types": ["support_gem"],
            "scope": "any",
            "component_key": "support:Scattershot",
            "resolution_status": "resolved",
        },
    ]
    record["component_keys"] = ["skill:LightningArrowPlayer", "support:Scattershot"]
    record["typed_payload"] = {}

    missing = research_models.validate_researcher_output(payload)
    record["typed_payload"] = {
        "supportPackages": [
            {
                "skillKey": "skill:LightningArrowPlayer",
                "supportKeys": ["support:Scattershot"],
            }
        ]
    }
    structured = research_models.validate_researcher_output(payload)

    assert missing["status"] == "error"
    assert missing["errorCode"] == "invalid_schema"
    assert structured["status"] == "accepted"


def test_origin_family_component_pattern_keeps_a_reserved_result_slot(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite", graph_service=_graph_service()
    )
    record_payload = _deep_record_payload()
    record = record_payload["deep_research_records"][0]
    record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        }
    ]
    family_key = service.propose_deep_research_records(record_payload)["buildFamilyKeys"][0]
    for index in range(6):
        shared = _pattern_payload()
        shared["patterns"][0]["title"] = f"Shared component pattern {index}"
        shared["build_design_observations"][0]["title"] = f"Shared observation {index}"
        assert service.propose_build_patterns(shared)["status"] == "accepted"
    origin = _as_transfer_candidate(
        _pattern_payload(),
        family_key=family_key,
        case_ref="case:origin-priority",
        title="Origin family component module",
    )
    origin_id = service.propose_build_patterns(origin)["patternIds"][0]

    recalled = service.query_research_memory(
        "",
        component_keys=[
            "ascendancy:monk:martial_artist",
            "skill:LightningArrowPlayer",
        ],
        limit=1,
    )

    assert [row["patternId"] for row in recalled["buildPatterns"]] == [origin_id]
    assert recalled["buildPatterns"][0]["matchScope"] == "origin_family"


def test_defense_knowledge_identity_normalizes_equivalent_component_roles():
    first = _deep_record_payload()["deep_research_records"][0]
    first["record_kind"] = "defense_engine"
    first["ascendancy_key"] = "ascendancy:monk:martial_artist"
    first["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:LightningArrowPlayer"},
        {"role": "defense_layer", "component_key": "notable:pob:0_5:100"},
    ]
    second = json.loads(json.dumps(first))
    second["component_mentions"][1]["role"] = "passive_anchor"
    family = research_identity.infer_build_family([first, second])

    assert family is not None
    assert research_identity.knowledge_key(first, family) == research_identity.knowledge_key(
        second, family
    )


def test_gear_knowledge_identity_normalizes_legacy_weapon_base_to_gear_base():
    first = _deep_record_payload()["deep_research_records"][0]
    first["record_kind"] = "gear_synergy"
    first["ascendancy_key"] = "ascendancy:monk:martial_artist"
    first["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:LightningArrowPlayer"},
        {
            "role": "weapon_base",
            "component_key": "item_base:Metadata/Items/Armours/BodyArmours/Fixture",
        },
    ]
    second = json.loads(json.dumps(first))
    second["component_mentions"][1]["role"] = "gear_base"
    family = research_identity.infer_build_family([first, second])

    assert family is not None
    assert research_identity.knowledge_key(first, family) == research_identity.knowledge_key(
        second, family
    )


def test_build_family_identity_uses_full_primary_skill_set():
    first = _deep_record_payload()["deep_research_records"][0]
    first["ascendancy_key"] = "ascendancy:monk:martial_artist"
    first["component_mentions"] = [
        {"role": "primary_damage", "component_key": "skill:LightningArrowPlayer"}
    ]
    second = json.loads(json.dumps(first))
    second["component_mentions"][0]["component_key"] = "skill:OtherPrimaryPlayer"

    family = research_identity.infer_build_family([first, second])
    assert family is not None
    assert family.primary_skill_keys == (
        "skill:LightningArrowPlayer",
        "skill:OtherPrimaryPlayer",
    )
    assert family.primary_skill_key == "skill:LightningArrowPlayer"


def test_historical_family_identity_can_repair_a_clearly_dominant_primary_role():
    records = []
    for key in (
        "skill:LightningArrowPlayer",
        "skill:LightningArrowPlayer",
        "skill:LightningArrowPlayer",
        "skill:OtherPrimaryPlayer",
    ):
        record = _deep_record_payload()["deep_research_records"][0]
        record["ascendancy_key"] = "ascendancy:monk:martial_artist"
        record["component_mentions"] = [{"role": "primary_damage", "component_key": key}]
        records.append(record)

    repaired = research_identity.infer_build_family(records, allow_dominant_primary=True)
    assert repaired is not None
    assert repaired.primary_skill_key == "skill:LightningArrowPlayer"
    assert repaired.primary_skill_keys == (
        "skill:LightningArrowPlayer",
        "skill:OtherPrimaryPlayer",
    )


def test_initialize_store_adds_phase4_schema_with_colon_safe_fts(tmp_path):
    db_path = tmp_path / "mature.sqlite"

    mature_learning.initialize_store(db_path)
    con = mature_learning.connect(db_path)
    try:
        assert mature_learning.schema_version(con) == 4
        assert {
            "research_fragments",
            "research_fragment_evidence",
            "research_fragment_fts",
            "research_semantic_edges",
            "research_rejected_proposals",
            "research_revalidation_events",
            "deep_research_records",
            "deep_research_record_evidence",
            "research_build_families",
            "research_build_family_evidence",
        } <= _tables(con)
        columns = {
            str(row["name"]) for row in con.execute("PRAGMA table_info(deep_research_records)")
        }
        assert {"build_family_key", "knowledge_key", "evidence_count"} <= columns
        query_columns = {
            str(row["name"]) for row in con.execute("PRAGMA table_info(research_dedupe_queries)")
        }
        assert {"request_contract", "result_contract"} <= query_columns

        service = research_memory.ResearchMemoryService(db_path=db_path)
        query_ref = service.query_research_memory(
            "Lightning Arrow", component_keys=["skill:LightningArrowPlayer"]
        )["dedupeQueryRef"]
        accepted = service.propose_research_fragments(
            _fragment_payload(), dedupe_query_ref=query_ref
        )
        assert accepted["status"] == "accepted"

        rows = con.execute(
            "SELECT fragment_id FROM research_fragment_fts WHERE research_fragment_fts MATCH ?",
            ('"skill:LightningArrowPlayer"',),
        ).fetchall()
        assert rows
    finally:
        con.close()


def test_query_receipt_preserves_typed_identity_and_safe_result_ids(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")

    result = service.query_research_memory(
        "Plan a target Family.",
        component_keys=["ascendancy:target-monk", "skill:target-attack"],
        ascendancy_key="ascendancy:target-monk",
        primary_skill_key="skill:target-attack",
        include_transferable=True,
        research_axes=["mechanic_engine"],
    )
    receipt = service.read_query_receipt(result["dedupeQueryRef"])

    assert receipt is not None
    assert receipt["request"]["ascendancyKey"] == "ascendancy:target-monk"
    assert receipt["request"]["primarySkillKey"] == "skill:target-attack"
    assert receipt["request"]["primarySkillKeys"] == ["skill:target-attack"]
    assert receipt["request"]["includeTransferable"] is True
    assert receipt["result"] == {
        "buildFamilies": [],
        "deepRecordIds": [],
        "patternIds": [],
        "semanticEdgeIds": [],
        "memoryItemIds": [],
        "deepReadRecordIds": [],
        "familyRecordCoverage": [],
        "familyPremiseCatalog": [],
        "premiseAuditVersion": None,
    }
    assert receipt["noRawQuery"] is True
    assert "Plan a target Family." not in str(receipt)


def test_query_receipt_records_graph_backed_primary_skill_equivalence(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )

    result = service.query_research_memory(
        "Plan a Lightning Arrow Family.",
        component_keys=[
            "ascendancy:monk:martial_artist",
            "gem:Metadata/Items/Gems/SkillGemLightningArrow",
        ],
        ascendancy_key="ascendancy:monk:martial_artist",
        primary_skill_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
    )
    receipt = service.read_query_receipt(result["dedupeQueryRef"])

    assert receipt is not None
    assert receipt["request"]["primarySkillKey"] == (
        "gem:Metadata/Items/Gems/SkillGemLightningArrow"
    )
    assert receipt["request"]["primarySkillKeys"] == [
        "gem:Metadata/Items/Gems/SkillGemLightningArrow",
        "skill:LightningArrowPlayer",
    ]


def test_canonical_identity_unique_variant_shares_family_token():
    index = skill_equivalence.SkillEquivalenceIndex.shared()
    assert index.canonical_key("skill:LightningBoltPlayer") == index.canonical_key(
        "skill:UniqueBreachLightningBoltPlayer"
    )
    assert index.canonical_key("skill:SparkPlayer") == index.canonical_key(
        "skill:UniqueEarthboundTriggeredSparkPlayer"
    )
    # Unique gems without a display-name match stay on a distinct key: token until a
    # model-confirmed equivalence row unions them; never silently merged by name.
    assert index.canonical_key("skill:UniqueSkillGemHeraldOfAshPlayer").startswith("key:")


def test_canonical_identity_set_unions_model_equivalence_rows(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    research_memory.ResearchMemoryService(db_path=db_path)
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            "INSERT INTO skill_equivalence (key_a, key_b, method, rationale, game_patch, status, created_at, last_seen_at) "
            "VALUES (?, ?, 'model_review', 'renamed across versions', '0_5', 'valid', datetime('now'), datetime('now'))",
            ("skill:OldSkillPlayer", "skill:NewSkillPlayer"),
        )
        con.commit()
        canon = research_memory.ResearchMemoryService._canonical_identity_set(
            con, ["skill:OldSkillPlayer", "skill:NewSkillPlayer", "skill:LightningBoltPlayer"]
        )
        assert "skill:oldskillplayer" not in canon
        assert "skill:newskillplayer" not in canon
        assert "gem:lightningbolt" in canon
    finally:
        con.close()


def test_query_receipt_is_immutable_when_later_research_changes_results(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_args = {
        "query": "Projectile overlap principle",
        "component_keys": ["skill:LightningArrowPlayer"],
    }

    before = service.query_research_memory(**query_args)
    accepted = service.propose_research_fragments(
        _fragment_payload(),
        dedupe_query_ref=before["dedupeQueryRef"],
    )
    after = service.query_research_memory(**query_args)

    assert accepted["status"] == "accepted"
    assert after["dedupeQueryRef"] != before["dedupeQueryRef"]
    assert service.read_query_receipt(before["dedupeQueryRef"])["result"]["memoryItemIds"] == []
    assert service.read_query_receipt(after["dedupeQueryRef"])["result"]["memoryItemIds"]


def test_core_support_package_is_not_rejected_by_component_count(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    bad = _fragment_payload()
    bad["fragments"][0]["summary"] = "Supports: A, B, C, D, E"
    query_ref = service.query_research_memory("copy safety rejection", component_keys=[])[
        "dedupeQueryRef"
    ]

    first = service.propose_research_fragments(bad, dedupe_query_ref=query_ref)

    assert first["status"] == "accepted"


def test_deep_records_persist_and_support_summary_then_record_recall(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite", graph_service=_graph_service()
    )

    accepted = service.propose_deep_research_records(_deep_record_payload())
    fragment_ref = service.query_research_memory("旧片段", component_keys=[])["dedupeQueryRef"]
    service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=fragment_ref)
    summary = service.query_research_memory(
        "投射物覆盖", component_keys=["skill:LightningArrowPlayer"]
    )
    record_id = accepted["recordIds"][0]
    detail = service.query_research_memory("", detail_level="record", record_ids=[record_id])

    assert accepted["status"] == "accepted"
    assert summary["deepResearchRecords"][0]["recordId"] == record_id
    assert "content" not in summary["deepResearchRecords"][0]
    assert detail["deepResearchRecords"][0]["content"].startswith("投射物覆盖")
    assert detail["results"] == []
    assert detail["deepResearchRecords"][0]["typedPayload"]["roles"] == [
        "delivery",
        "coverage",
    ]


def test_exact_family_identity_is_not_filtered_by_goal_text_or_secondary_skill(tmp_path):
    source_id = "fixture:phase4"
    other_primary = pg.GraphNode(
        "skill:OtherPrimaryPlayer", "active_skill", "Other Primary", (source_id,)
    )
    second_core = pg.GraphNode(
        "skill:SecondCorePlayer", "active_skill", "Second Core", (source_id,)
    )
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(extra_nodes=[other_primary, second_core]),
    )

    def store_family(
        group_id: str,
        primary_key: str,
        secondary_key: str | None,
    ) -> str:
        payload = _deep_record_payload()
        record = payload["deep_research_records"][0]
        record["research_group_id"] = group_id
        record["title"] = f"{group_id} mechanism"
        record["summary"] = f"Safe summary for {group_id}."
        record["source_case_refs"] = [f"case:{group_id}"]
        record["safe_evidence_refs"] = [f"safe:{group_id}"]
        record["ascendancy_key"] = "ascendancy:monk:martial_artist"
        record["component_keys"] = [primary_key]
        record["component_mentions"] = [
            {
                "candidate_name": primary_key,
                "role": "primary_damage",
                "resolver_query": primary_key,
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": primary_key,
                "resolution_status": "resolved",
            }
        ]
        if secondary_key:
            record["component_keys"].append(secondary_key)
            record["component_mentions"].append(
                {
                    "candidate_name": secondary_key,
                    "role": "clear_skill",
                    "resolver_query": secondary_key,
                    "expected_node_types": ["active_skill"],
                    "scope": "player",
                    "component_key": secondary_key,
                    "resolution_status": "resolved",
                }
            )
        result = service.propose_deep_research_records(payload)
        assert result["status"] == "accepted"
        return result["buildFamilyKeys"][0]

    exact_a = store_family("research:exact-a", "skill:LightningArrowPlayer", None)
    exact_b = store_family(
        "research:exact-b", "skill:LightningArrowPlayer", "skill:SecondCorePlayer"
    )
    secondary_only = store_family(
        "research:secondary-only", "skill:OtherPrimaryPlayer", "skill:LightningArrowPlayer"
    )

    recalled = service.query_research_memory(
        "开荒顺畅但这段目标文字不应成为硬过滤条件",
        component_keys=[
            "ascendancy:monk:martial_artist",
            "skill:LightningArrowPlayer",
        ],
        ascendancy_key="ascendancy:monk:martial_artist",
        primary_skill_key="skill:LightningArrowPlayer",
        limit=2,
    )
    gem_recalled = service.query_research_memory(
        "",
        ascendancy_key="ascendancy:monk:martial_artist",
        primary_skill_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
    )

    recalled_families = {row["buildFamilyKey"] for row in recalled["buildFamilies"]}
    assert recalled_families == {exact_a, exact_b}
    assert secondary_only not in recalled_families
    assert {row["buildFamilyKey"] for row in recalled["deepResearchRecords"]} == {
        exact_a,
        exact_b,
    }
    assert recalled["requestedAscendancyKey"] == "ascendancy:monk:martial_artist"
    assert recalled["requestedPrimarySkillKey"] == "skill:LightningArrowPlayer"
    assert {row["buildFamilyKey"] for row in gem_recalled["buildFamilies"]} == {
        exact_a,
        exact_b,
    }


def test_family_summary_indexes_record_kinds_for_targeted_recall(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite", graph_service=_graph_service()
    )
    family_key = ""
    for record_kind in ("mechanic_chain", "rotation", "resource_engine"):
        payload = _deep_record_payload()
        record = payload["deep_research_records"][0]
        record["research_group_id"] = f"research:kind-{record_kind}"
        record["record_kind"] = record_kind
        record["title"] = f"{record_kind} title"
        record["summary"] = f"{record_kind} summary"
        record["source_case_refs"] = [f"case:{record_kind}"]
        record["safe_evidence_refs"] = [f"safe:{record_kind}"]
        record["ascendancy_key"] = "ascendancy:monk:martial_artist"
        record["component_keys"] = ["skill:LightningArrowPlayer"]
        record["component_mentions"] = [
            {
                "candidate_name": "Lightning Arrow",
                "role": "primary_damage",
                "resolver_query": "skill:LightningArrowPlayer",
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": "skill:LightningArrowPlayer",
                "resolution_status": "resolved",
            }
        ]
        accepted = service.propose_deep_research_records(payload)
        assert accepted["status"] == "accepted"
        family_key = accepted["buildFamilyKeys"][0]

    summary = service.query_research_memory(
        "unmatched planning objective",
        ascendancy_key="ascendancy:monk:martial_artist",
        primary_skill_key="skill:LightningArrowPlayer",
    )
    family = summary["buildFamilies"][0]
    targeted = service.query_research_memory(
        "another unmatched objective",
        build_family_keys=[family_key],
        record_kinds=["rotation"],
        detail_level="summary",
    )
    invalid = service.query_research_memory(
        "",
        build_family_keys=[family_key],
        record_kinds=["invented_record_kind"],
    )

    assert family["deepRecordCount"] == 3
    assert family["recordKindCounts"] == {
        "mechanic_chain": 1,
        "resource_engine": 1,
        "rotation": 1,
    }
    assert family["availableRecordKinds"] == [
        "mechanic_chain",
        "resource_engine",
        "rotation",
    ]
    assert [row["recordKind"] for row in targeted["deepResearchRecords"]] == ["rotation"]
    assert targeted["requestedBuildFamilyKeys"] == [family_key]
    assert targeted["requestedRecordKinds"] == ["rotation"]
    assert invalid["status"] == "error"
    assert invalid["errorCode"] == "invalid_record_kinds"


def test_exact_family_query_indexes_the_seventh_critical_record_and_allows_exact_deep_read(
    tmp_path,
):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(
            extra_nodes=[
                pg.GraphNode(
                    "skill:FlickerStrikePlayer",
                    "active_skill",
                    "Flicker Strike",
                    ("fixture:phase4",),
                ),
                pg.GraphNode(
                    "skill:HollowFocusPlayer",
                    "active_skill",
                    "Hollow Focus",
                    ("fixture:phase4",),
                ),
                pg.GraphNode(
                    "skill:KillingPalmPlayer",
                    "active_skill",
                    "Killing Palm",
                    ("fixture:phase4",),
                ),
            ]
        ),
    )
    record_kinds = [
        "mechanic_chain",
        "rotation",
        "resource_engine",
        "passive_package",
        "defense_engine",
        "design_tradeoff",
        "failure_mode",
    ]
    records: list[dict] = []
    for index, record_kind in enumerate(record_kinds):
        is_boss_failure = index == len(record_kinds) - 1
        payload = _deep_record_payload(
            f"{record_kind} 记录用于验证同一 Family 的完整知识索引与定向深读。"
        )
        record = payload["deep_research_records"][0]
        record["research_group_id"] = "research:flicker-coverage"
        record["record_kind"] = record_kind
        record["title"] = (
            "无小怪 Boss 的 Hollow Focus 充能替代链"
            if is_boss_failure
            else f"Flicker coverage {record_kind}"
        )
        record["summary"] = (
            "Killing Palm 不能单独保证健康 Boss 的起始球，需定向验证 Hollow Focus 替代链。"
            if is_boss_failure
            else f"Flicker {record_kind} 的安全摘要。"
        )
        record["component_keys"] = [
            "skill:FlickerStrikePlayer",
            *(
                ["skill:HollowFocusPlayer"]
                if record_kind == "mechanic_chain" or is_boss_failure
                else []
            ),
            *(["skill:KillingPalmPlayer"] if is_boss_failure else []),
        ]
        record["component_mentions"] = [
            {
                "candidate_name": "Flicker Strike",
                "role": "primary_damage",
                "resolver_query": "skill:FlickerStrikePlayer",
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": "skill:FlickerStrikePlayer",
                "resolution_status": "resolved",
            },
            *(
                [
                    {
                        "candidate_name": "Hollow Focus",
                        "role": "boss_skill",
                        "resolver_query": "skill:HollowFocusPlayer",
                        "expected_node_types": ["active_skill"],
                        "scope": "player",
                        "component_key": "skill:HollowFocusPlayer",
                        "resolution_status": "resolved",
                    }
                ]
                if record_kind == "mechanic_chain" or is_boss_failure
                else []
            ),
            *(
                [
                    {
                        "candidate_name": "Killing Palm",
                        "role": "generator",
                        "resolver_query": "skill:KillingPalmPlayer",
                        "expected_node_types": ["active_skill"],
                        "scope": "player",
                        "component_key": "skill:KillingPalmPlayer",
                        "resolution_status": "resolved",
                    }
                ]
                if is_boss_failure
                else []
            ),
        ]
        record["source_case_refs"] = [f"case:flicker-coverage-{index}"]
        record["safe_evidence_refs"] = [f"safe:flicker-coverage:{index}"]
        record["ascendancy_key"] = "ascendancy:monk:martial_artist"
        record["conditions"] = (
            ["Hollow Focus 已启用且可生成 Power Charge"]
            if is_boss_failure
            else [f"{record_kind} 前提已验证"]
        )
        record["failure_conditions"] = (
            ["无小怪 Boss 中 Power Charge 枯竭"] if is_boss_failure else [f"{record_kind} 失败条件"]
        )
        records.append(record)

    accepted = service.propose_deep_research_records(
        {
            "schema_version": 5,
            "deep_research_records": records,
        }
    )
    assert accepted["status"] == "accepted", accepted
    assert len(accepted["buildFamilyKeys"]) == 1
    family_key = accepted["buildFamilyKeys"][0]
    record_ids = list(accepted["recordIds"])

    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        boss_record_id = str(
            con.execute(
                "SELECT record_id FROM deep_research_records WHERE title = ?",
                ("无小怪 Boss 的 Hollow Focus 充能替代链",),
            ).fetchone()["record_id"]
        )
        for index, record_id in enumerate(record_ids):
            con.execute(
                "UPDATE deep_research_records SET evidence_count = ? WHERE record_id = ?",
                (10 + index, record_id),
            )
        con.execute(
            "UPDATE deep_research_records SET evidence_count = 1 WHERE record_id = ?",
            (boss_record_id,),
        )
        con.commit()
    finally:
        con.close()

    first_page = service.query_research_memory(
        "",
        build_family_keys=[family_key],
        game_patch="0.5.4",
        passive_tree_version="0_5",
        limit=6,
    )

    assert len(first_page["deepResearchRecords"]) == 6
    coverage = first_page["familyRecordCoverage"][0]
    assert coverage["eligibleRecordCount"] == 7
    assert coverage["returnedRecordCount"] == 6
    assert coverage["unreturnedRecordCount"] == 1
    assert coverage["responseComplete"] is False
    assert len(first_page["familyRecordIndex"]) == 1
    omitted = first_page["familyRecordIndex"]
    assert [row["recordId"] for row in omitted] == [boss_record_id]
    assert set(omitted[0]["componentKeys"]) >= {
        "skill:FlickerStrikePlayer",
        "skill:HollowFocusPlayer",
        "skill:KillingPalmPlayer",
    }
    failure_premises = [
        row
        for row in first_page["familyPremiseCatalog"]
        if row["premiseType"] == "failure_condition"
    ]
    assert any(row["text"] == "无小怪 Boss 中 Power Charge 枯竭" for row in failure_premises)

    targeted_failure = service.query_research_memory(
        "无小怪 Boss 中 Power Charge 枯竭",
        build_family_keys=[family_key],
        game_patch="0.5.4",
        passive_tree_version="0_5",
        limit=1,
    )
    assert [row["recordId"] for row in targeted_failure["deepResearchRecords"]] == [boss_record_id]

    receipt = service.read_query_receipt(first_page["dedupeQueryRef"])
    assert receipt is not None
    assert receipt["result"]["familyRecordCoverage"] == first_page["familyRecordCoverage"]
    assert receipt["result"]["familyPremiseCatalog"] == first_page["familyPremiseCatalog"]

    discovery = service.query_research_memory(
        "",
        detail_level="family",
        class_key="class:monk",
        game_patch="0.5.4",
        passive_tree_version="0_5",
    )
    discovered_family = next(
        row for row in discovery["buildFamilies"] if row["buildFamilyKey"] == family_key
    )
    kind_by_id = {
        row["recordId"]: row["recordKind"]
        for row in [
            *first_page["deepResearchRecords"],
            *first_page["familyRecordIndex"],
        ]
    }
    assert {kind_by_id[record_id] for record_id in discovered_family["supportingRecordIds"]} == {
        "mechanic_chain",
        "rotation",
        "resource_engine",
        "failure_mode",
    }

    exact_deep_read = service.query_research_memory(
        "",
        build_family_keys=[family_key],
        record_ids=record_ids,
        detail_level="record",
        game_patch="0.5.4",
        passive_tree_version="0_5",
        limit=1,
    )
    assert {row["recordId"] for row in exact_deep_read["deepResearchRecords"]} == set(record_ids)
    deep_receipt = service.read_query_receipt(exact_deep_read["dedupeQueryRef"])
    assert deep_receipt is not None
    assert set(deep_receipt["result"]["deepReadRecordIds"]) == set(record_ids)


def test_deep_record_resolution_enrichment_updates_existing_knowledge_unit(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    initial = _deep_record_payload()
    initial_record = initial["deep_research_records"][0]
    initial_record["component_keys"] = ["skill:LightningArrowPlayer"]
    initial_record["component_mentions"] = [
        {
            "candidate_name": "Scattershot",
            "role": "support_modifier",
            "resolver_query": "Scattershot support",
            "expected_node_types": ["support_gem"],
            "scope": "any",
            "component_key": None,
            "resolution_status": "ambiguous",
        }
    ]
    first = service.propose_deep_research_records(initial)

    enriched = _deep_record_payload()
    enriched_record = enriched["deep_research_records"][0]
    enriched_record["component_mentions"] = [
        {
            "candidate_name": "Scattershot",
            "role": "support_modifier",
            "resolver_query": "support:Scattershot",
            "expected_node_types": ["support_gem"],
            "scope": "any",
            "component_key": "support:Scattershot",
            "resolution_status": "resolved",
        }
    ]
    second = service.propose_deep_research_records(enriched)

    assert second["recordIds"] == first["recordIds"]
    con = mature_learning.connect(db_path)
    try:
        rows = con.execute(
            "SELECT component_keys, component_mentions FROM deep_research_records"
        ).fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0]["component_keys"]) == [
            "skill:LightningArrowPlayer",
            "support:Scattershot",
        ]
        assert json.loads(rows[0]["component_mentions"])[0]["resolution_status"] == "resolved"
    finally:
        con.close()


def test_deep_records_canonicalize_across_sources_with_family_evidence(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = _deep_record_payload()
    first_record = first["deep_research_records"][0]
    first_record["record_kind"] = "skill_package"
    first_record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    first_record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        },
        {
            "candidate_name": "Scattershot",
            "role": "support_modifier",
            "resolver_query": "Scattershot",
            "expected_node_types": ["support_gem"],
            "scope": "any",
            "component_key": "support:Scattershot",
            "resolution_status": "resolved",
        },
    ]
    first_record["typed_payload"] = {
        "supportPackages": [
            {
                "skillKey": "skill:LightningArrowPlayer",
                "supportKeys": ["support:Scattershot"],
            }
        ]
    }
    first_record["source_case_refs"] = ["source-hash:first"]
    second = json.loads(json.dumps(first))
    second_record = second["deep_research_records"][0]
    second_record["research_group_id"] = "research:second-source"
    second_record["title"] = "另一种标题不会创建重复知识"
    second_record["content"] = "第二个来源提供更完整的主技能职责和辅助使用边界。"
    second_record["source_case_refs"] = ["source-hash:second"]

    first_result = service.propose_deep_research_records(first)
    second_result = service.propose_deep_research_records(second)

    assert first_result["createdRecordCount"] == 1
    assert first_result["createdBuildFamilyCount"] == 1
    assert first_result["evidenceAddedCount"] == 1
    assert second_result["createdRecordCount"] == 0
    assert second_result["createdBuildFamilyCount"] == 0
    assert second_result["updatedRecordCount"] == 1
    assert second_result["evidenceAddedCount"] == 1
    assert second_result["recordIds"] == first_result["recordIds"]
    assert second_result["buildFamilyKeys"] == first_result["buildFamilyKeys"]
    recalled = service.query_research_memory(
        "", component_keys=["ascendancy:monk:martial_artist"], detail_level="record"
    )["deepResearchRecords"]
    assert len(recalled) == 1
    assert recalled[0]["evidenceCount"] == 2
    assert recalled[0]["buildFamilyKey"] == first_result["buildFamilyKeys"][0]
    family_result = service.query_research_memory("另一种标题")
    assert family_result["buildFamilies"] == [
        {
            "buildFamilyKey": first_result["buildFamilyKeys"][0],
            "ascendancyKey": "ascendancy:monk:martial_artist",
            "primarySkillKey": "skill:LightningArrowPlayer",
            "primarySkillKeys": ["skill:LightningArrowPlayer"],
            "secondarySkillKeys": [],
            "evidenceCount": 2,
            "deepRecordCount": 1,
            "recordKindCounts": {"skill_package": 1},
            "availableRecordKinds": ["skill_package"],
        }
    ]

    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM research_build_families").fetchone()[0] == 1
        assert con.execute("SELECT evidence_count FROM research_build_families").fetchone()[0] == 2
        assert con.execute("SELECT count(*) FROM deep_research_record_evidence").fetchone()[0] == 2
    finally:
        con.close()


def test_record_writes_report_the_persisted_canonical_record(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = _deep_record_payload(
        "第一个来源提供较完整的机制说明，覆盖主技能职责、辅助边界与需要复核的失效条件。"
    )
    first_record = first["deep_research_records"][0]
    first_record["record_kind"] = "skill_package"
    first_record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    first_record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        }
    ]
    first_record["title"] = "最终保留的 canonical 标题"
    first_record["source_case_refs"] = ["source-hash:canonical"]
    second = json.loads(json.dumps(first))
    second_record = second["deep_research_records"][0]
    second_record["research_group_id"] = "research:second-source"
    second_record["title"] = "本次提交标题"
    second_record["summary"] = "较短摘要。"
    second_record["content"] = "较短说明。"
    second_record["source_case_refs"] = ["source-hash:submitted"]

    first_result = service.propose_deep_research_records(first)
    second_result = service.propose_deep_research_records(second)

    write = second_result["recordWrites"][0]
    assert write["recordId"] == first_result["recordIds"][0]
    assert write["title"] == "本次提交标题"
    assert write["submittedTitle"] == "本次提交标题"
    assert write["canonicalContentMatchesSubmitted"] is False
    assert write["canonicalRecord"] == {
        "recordId": first_result["recordIds"][0],
        "researchGroupId": "research:la-safe",
        "buildFamilyKey": first_result["buildFamilyKeys"][0],
        "knowledgeKey": first_result["knowledgeKeys"][0],
        "evidenceCount": 2,
        "recordKind": "skill_package",
        "title": "最终保留的 canonical 标题",
        "summary": first_record["summary"],
        "componentKeys": ["skill:LightningArrowPlayer", "support:Scattershot"],
        "sourceCaseRefs": ["source-hash:canonical", "source-hash:submitted"],
        "safeEvidenceRefs": ["safe:la:hash"],
    }


def test_same_source_accepted_revision_can_replace_longer_canonical_prose(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = _deep_record_payload(
        "旧分析包含较长的机制解释，但其中有一项已被静态资料推翻，需要由同一来源的复审纠正。"
    )
    first_record = first["deep_research_records"][0]
    first_record["record_kind"] = "skill_package"
    first_record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    first_record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        },
        {
            "candidate_name": "Scattershot",
            "role": "support_modifier",
            "resolver_query": "Scattershot",
            "expected_node_types": ["support_gem"],
            "scope": "any",
            "component_key": "support:Scattershot",
            "resolution_status": "resolved",
        },
    ]
    first_record["typed_payload"] = {
        "supportPackages": [
            {
                "skillKey": "skill:LightningArrowPlayer",
                "supportKeys": ["support:Scattershot"],
            }
        ]
    }
    first_record["conditions"] = ["第一个条件", "第二个条件"]
    first_record["failure_conditions"] = ["第一个失败条件", "第二个失败条件"]
    corrected = json.loads(json.dumps(first))
    corrected_record = corrected["deep_research_records"][0]
    corrected_record["summary"] = "同一来源复审后的精确结论。"
    corrected_record["content"] = "静态资料复核后的纠正结论。"
    corrected_record["conditions"] = ["复核条件"]
    corrected_record["failure_conditions"] = ["失效边界"]

    assert research_identity.record_quality(
        research_models.DeepResearchRecordProposal.model_validate(corrected_record)
    ) < research_identity.record_quality(
        research_models.DeepResearchRecordProposal.model_validate(first_record)
    )

    first_result = service.propose_deep_research_records(first)
    corrected_result = service.propose_deep_research_records(corrected)

    assert corrected_result["createdRecordCount"] == 0
    assert corrected_result["updatedRecordCount"] == 1
    assert corrected_result["recordIds"] == first_result["recordIds"]
    con = mature_learning.connect(db_path)
    try:
        row = con.execute(
            "SELECT summary, content, conditions, failure_conditions, evidence_count "
            "FROM deep_research_records WHERE record_id = ?",
            (first_result["recordIds"][0],),
        ).fetchone()
        assert row["summary"] == corrected_record["summary"]
        assert row["content"] == corrected_record["content"]
        assert json.loads(row["conditions"]) == ["复核条件"]
        assert json.loads(row["failure_conditions"]) == ["失效边界"]
        assert row["evidence_count"] == 1
    finally:
        con.close()


def test_sibling_family_hints_flag_same_primary_different_secondary(tmp_path):
    from server.knowledge import mature_learning, research_memory

    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
        initialize_store=True,
    )
    now = research_memory._now()
    con = mature_learning.connect(service.db_path)
    con.execute(
        """
        INSERT INTO research_build_families(
            build_family_key, ascendancy_key, primary_skill_key, secondary_skill_keys,
            evidence_count, created_at, last_seen_at
        ) VALUES (?, ?, ?, ?, 0, ?, ?)
        """,
        (
            "bf-alpha",
            "ascendancy:mercenary:gemling_legionnaire",
            "skill:TwisterPlayer",
            '["skill:FrostWallPlayer"]',
            now,
            now,
        ),
    )
    con.execute(
        """
        INSERT INTO research_build_families(
            build_family_key, ascendancy_key, primary_skill_key, secondary_skill_keys,
            evidence_count, created_at, last_seen_at
        ) VALUES (?, ?, ?, ?, 0, ?, ?)
        """,
        (
            "bf-beta",
            "ascendancy:mercenary:gemling_legionnaire",
            "skill:TwisterPlayer",
            "[]",
            now,
            now,
        ),
    )
    con.commit()

    hints = research_memory._sibling_family_hints(con, {"bf-beta"})
    con.close()

    assert hints == [
        {
            "familyKey": "bf-beta",
            "ascendancyKey": "ascendancy:mercenary:gemling_legionnaire",
            "primarySkillKeys": ["skill:TwisterPlayer"],
            "relation": "identical",
            "siblingFamilyKey": "bf-alpha",
            "siblingPrimarySkillKeys": ["skill:TwisterPlayer"],
        }
    ]


def test_defense_engine_identity_keeps_distinct_unique_enablers_separate():
    first = _deep_record_payload("第一个防御方案由独立暗金提供关键防御基底。")
    first_record = first["deep_research_records"][0]
    first_record["record_kind"] = "defense_engine"
    first_record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    first_record["component_mentions"] = [
        {
            "candidate_name": "Rathpith Globe",
            "role": "unique_enabler",
            "resolver_query": "Rathpith Globe",
            "expected_node_types": ["unique"],
            "scope": "any",
            "component_key": "unique:pob:rathpith_globe",
            "resolution_status": "resolved",
        },
        {
            "candidate_name": "Lightning Arrow",
            "role": "defensive_buff",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        },
    ]
    first_record["component_keys"] = [
        "unique:pob:rathpith_globe",
        "skill:LightningArrowPlayer",
    ]

    second = json.loads(json.dumps(first))
    second_record = second["deep_research_records"][0]
    second_record["research_group_id"] = "research:second-defense-source"
    second_record["title"] = "第二个暗金防御方案"
    second_record["source_case_refs"] = ["source-hash:second-defense"]
    second_record["component_mentions"][0].update(
        {
            "candidate_name": "Different Defensive Unique",
            "resolver_query": "Different Defensive Unique",
            "component_key": "unique:pob:different_defensive_unique",
        }
    )
    second_record["component_keys"] = [
        "unique:pob:different_defensive_unique",
        "skill:LightningArrowPlayer",
    ]

    family = research_identity.BuildFamilyIdentity(
        ascendancy_key="ascendancy:monk:martial_artist",
        primary_skill_keys=("skill:LightningArrowPlayer",),
        secondary_skill_keys=(),
    )
    first_proposal = research_models.DeepResearchRecordProposal.model_validate(first_record)
    second_proposal = research_models.DeepResearchRecordProposal.model_validate(second_record)

    assert research_identity.knowledge_key(
        first_proposal, family
    ) != research_identity.knowledge_key(second_proposal, family)


def test_same_pattern_revision_updates_semantic_title(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    original = _as_transfer_candidate(
        _pattern_payload(),
        family_key="bf-origin",
        case_ref="case:la-safe",
        title="原始语义标题",
    )
    first = service.propose_build_patterns(original)
    revised = _as_transfer_candidate(
        _pattern_payload(),
        family_key="bf-origin",
        case_ref="case:la-safe",
        title="原始语义标题",
    )
    revised["patterns"][0]["title"] = "静态机制复核后的修正标题"

    second = service.propose_build_patterns(revised)

    assert second["patternIds"] == first["patternIds"]
    con = mature_learning.connect(db_path)
    try:
        row = con.execute(
            "SELECT title FROM research_build_patterns WHERE pattern_id = ?",
            (first["patternIds"][0],),
        ).fetchone()
        assert row["title"] == "静态机制复核后的修正标题"
    finally:
        con.close()


def test_same_source_identity_revision_replaces_old_evidence_key(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = _deep_record_payload("原始轮转把一个组件记录为普通辅助。")
    record = first["deep_research_records"][0]
    record["record_kind"] = "rotation"
    record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        },
        {
            "candidate_name": "Scattershot",
            "role": "support_modifier",
            "resolver_query": "Scattershot",
            "expected_node_types": ["support_gem"],
            "scope": "any",
            "component_key": "support:Scattershot",
            "resolution_status": "resolved",
        },
    ]
    first_result = service.propose_deep_research_records(first)
    old_key = first_result["knowledgeKeys"][0]

    corrected = json.loads(json.dumps(first))
    corrected_record = corrected["deep_research_records"][0]
    corrected_record["content"] = "同一来源复审后确认该组件承担触发载荷职责。"
    corrected_record["component_mentions"][1]["role"] = "triggered_payload"
    corrected_result = service.propose_deep_research_records(corrected)
    new_key = corrected_result["knowledgeKeys"][0]

    assert new_key != old_key
    assert corrected_result["recordIds"] == first_result["recordIds"]
    con = mature_learning.connect(db_path)
    try:
        row = con.execute(
            "SELECT knowledge_key, evidence_count FROM deep_research_records"
        ).fetchone()
        evidence_keys = [
            str(item[0])
            for item in con.execute(
                "SELECT knowledge_key FROM deep_research_record_evidence ORDER BY knowledge_key"
            )
        ]
        assert row["knowledge_key"] == new_key
        assert row["evidence_count"] == 1
        assert evidence_keys == [new_key]
    finally:
        con.close()


def test_text_recall_expands_to_other_knowledge_in_the_matched_family(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite", graph_service=_graph_service()
    )
    payload = _deep_record_payload()
    skill_record = payload["deep_research_records"][0]
    skill_record["record_kind"] = "skill_package"
    skill_record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    skill_record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        }
    ]
    passive_record = json.loads(json.dumps(skill_record))
    passive_record["record_kind"] = "passive_package"
    passive_record["title"] = "局部投射物天赋包"
    passive_record["summary"] = "记录局部天赋职责。"
    passive_record["content"] = "该局部天赋节点承担独立的路径职责。"
    passive_record["component_keys"] = ["passive:pob:0_5:100"]
    passive_record["component_mentions"] = [
        {
            "candidate_name": "Projectile Cluster",
            "role": "passive_anchor",
            "resolver_query": "Projectile Cluster",
            "expected_node_types": ["passive"],
            "scope": "any",
            "component_key": "passive:pob:0_5:100",
            "resolution_status": "resolved",
        }
    ]
    payload["deep_research_records"].append(passive_record)
    service.propose_deep_research_records(payload)

    result = service.query_research_memory("投射物覆盖")

    assert {row["recordKind"] for row in result["deepResearchRecords"]} == {
        "skill_package",
        "passive_package",
    }
    assert len(result["buildFamilies"]) == 1


def test_historical_backfill_supersedes_only_high_confidence_duplicates(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = _deep_record_payload()
    first_record = first["deep_research_records"][0]
    first_record["source_case_refs"] = ["source-hash:legacy-first"]
    second = json.loads(json.dumps(first))
    second_record = second["deep_research_records"][0]
    second_record["title"] = "历史改写标题"
    second_record["source_case_refs"] = ["source-hash:legacy-second"]
    service.propose_deep_research_records(first)
    service.propose_deep_research_records(second)

    resolved_mentions = json.dumps(
        [
            {
                "candidate_name": "Lightning Arrow",
                "role": "primary_damage",
                "resolver_query": "Lightning Arrow",
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": "skill:LightningArrowPlayer",
                "resolution_status": "resolved",
            }
        ]
    )
    con = mature_learning.connect(db_path)
    try:
        con.execute(
            """
            UPDATE deep_research_records
            SET component_mentions = ?, build_family_key = 'bf-legacy-secondary-split'
            """,
            (resolved_mentions,),
        )
        con.execute(
            """
            INSERT INTO research_build_families(
                build_family_key, ascendancy_key, primary_skill_key, secondary_skill_keys,
                evidence_count, created_at, last_seen_at
            ) VALUES (
                'bf-legacy-secondary-split', 'ascendancy:monk:martial_artist',
                'skill:LightningArrowPlayer', '["skill:UtilitySkillPlayer"]',
                1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )
        con.execute(
            """
            INSERT INTO research_build_family_evidence(
                build_family_key, source_case_ref, first_seen_at, last_seen_at
            ) VALUES (
                'bf-legacy-secondary-split', 'source-hash:legacy-first',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )
        con.execute(
            """
            INSERT INTO meta(key, value) VALUES ('phase4_build_family_backfill_version', '1')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
        )
        con.commit()
    finally:
        con.close()
    pattern_payload = _pattern_payload()
    ascendancy_component = {
        "component_key": "ascendancy:monk:martial_artist",
        "role": "ascendancy_shell",
        "resolution": _resolution_evidence("ascendancy:monk:martial_artist"),
    }
    pattern_payload["build_design_observations"][0]["components"].append(ascendancy_component)
    pattern_payload["build_design_observations"][0]["source_case_refs"] = [
        "source-hash:legacy-first"
    ]
    pattern_payload["patterns"][0]["component_keys"].append("ascendancy:monk:martial_artist")
    pattern_payload["patterns"][0]["component_roles"]["ascendancy:monk:martial_artist"] = (
        "ascendancy_shell"
    )
    pattern_payload["patterns"][0]["source_case_refs"] = ["source-hash:legacy-first"]
    assert service.propose_build_patterns(pattern_payload)["status"] == "accepted"

    report = service.backfill_deep_research_knowledge(force=True)

    assert report["supersededRecordCount"] == 2
    assert report["canonicalRecordCount"] == 1
    assert report["relocatedRecordCount"] == 1
    assert report["evidenceAddedCount"] == 2
    con = mature_learning.connect(db_path)
    try:
        rows = con.execute(
            """
            SELECT record_id, status, superseded_by_id, knowledge_key, evidence_count
            FROM deep_research_records ORDER BY status
            """
        ).fetchall()
        assert len(rows) == 3
        deprecated = [row for row in rows if row["status"] == "deprecated"]
        canonical = next(row for row in rows if row["status"] == "valid")
        assert len(deprecated) == 2
        assert all(row["superseded_by_id"] is not None for row in deprecated)
        assert all(row["knowledge_key"] == canonical["knowledge_key"] for row in deprecated)
        # The canonical now lives at id = hash(knowledge_key); its old id is a tombstone.
        assert (
            canonical["record_id"]
            == "drr-"
            + research_memory._stable_hash({"knowledge_key": canonical["knowledge_key"]})[:16]
        )
        assert canonical["evidence_count"] == 2
        assert (
            con.execute(
                "SELECT count(*) FROM research_build_families "
                "WHERE build_family_key = 'bf-legacy-secondary-split'"
            ).fetchone()[0]
            == 0
        )
        assert (
            con.execute(
                "SELECT value FROM meta WHERE key = 'phase4_build_family_backfill_version'"
            ).fetchone()[0]
            == research_memory.BUILD_FAMILY_BACKFILL_VERSION
        )
    finally:
        con.close()


def test_validation_only_deep_record_proposal_does_not_persist(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())

    validated = service.validate_deep_research_records(_deep_record_payload())

    assert validated["status"] == "accepted"
    assert validated["validationOnly"] is True
    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 0
    finally:
        con.close()


def test_deep_record_batch_rejection_does_not_partially_persist(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    payload = _deep_record_payload()
    invalid = json.loads(json.dumps(payload["deep_research_records"][0]))
    invalid["research_group_id"] = "research:missing-endpoint"
    invalid["title"] = "缺失端点记录"
    invalid["component_keys"] = ["skill:MissingFromPhysicalGraph"]
    invalid["source_case_refs"] = ["case:missing-endpoint"]
    invalid["safe_evidence_refs"] = ["safe:missing-endpoint"]
    payload["deep_research_records"].append(invalid)

    rejected = service.propose_deep_research_records(payload)

    assert rejected["status"] == "rejected"
    assert rejected["errorCode"] == "missing_endpoint"
    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM research_build_families").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM deep_research_record_evidence").fetchone()[0] == 0
    finally:
        con.close()


def test_deep_record_content_budget_requires_explicit_indivisible_exception(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite", graph_service=_graph_service()
    )
    payload = _deep_record_payload("机" * 401)

    rejected = service.propose_deep_research_records(payload)
    payload["deep_research_records"][0]["length_exception_reason"] = (
        "拆分会破坏同一生成、状态与兑现链的因果闭环。"
    )
    accepted = service.propose_deep_research_records(payload)

    assert rejected["status"] == "error"
    assert rejected["errorCode"] == "invalid_schema"
    assert accepted["status"] == "accepted"


def test_deep_record_normalizes_unknown_to_application_current_version(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite", graph_service=_graph_service()
    )
    payload = _deep_record_payload()
    payload["deep_research_records"][0]["pob_version_or_commit"] = "unknown"

    result = service.propose_deep_research_records(payload)

    assert result["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT game_patch, passive_tree_version, pob_version_or_commit "
            "FROM deep_research_records"
        ).fetchone()
        assert row["game_patch"] == "0.5.4"
        assert row["passive_tree_version"] == "0_5"
        assert row["pob_version_or_commit"] == "0.22.0"
    finally:
        con.close()


def test_deep_record_rejects_unsupported_explicit_pob_version(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite", graph_service=_graph_service()
    )
    payload = _deep_record_payload()
    payload["deep_research_records"][0]["pob_version_or_commit"] = "99.99.99"

    result = service.propose_deep_research_records(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "unsupported_pob_version"


def test_deep_record_cjk_content_cannot_use_english_word_budget(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite", graph_service=_graph_service()
    )
    payload = _deep_record_payload("机制链必须按中文字符预算。")
    payload["deep_research_records"][0]["content_language"] = "en"

    result = service.propose_deep_research_records(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"


def test_context_requirements_reject_arbitrary_dicts():
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    payload["semantic_edges"][0]["context_requirements"] = [
        {"context_type": "invented_context", "need_more_dps": True}
    ]

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"
    assert "Traceback" not in str(result)


def test_context_requirements_accept_phase3_graph_tool_context(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload(
        "skill:LightningArrowPlayer", "support:Scattershot", "requires_transition_gate"
    )
    payload["semantic_edges"][0]["context_requirements"] = [
        {"context_type": "passive_context", "active_weapon_set": 1}
    ]

    validated = research_models.validate_researcher_output(payload)
    accepted = service.propose_semantic_edges(payload)

    assert validated["status"] == "accepted"
    assert accepted["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT context_requirements FROM research_semantic_edges WHERE edge_id = ?",
            (accepted["edgeIds"][0],),
        ).fetchone()
        stored = json.loads(row["context_requirements"])
        assert stored == [{"active_weapon_set": 1, "context_type": "passive_context"}]
    finally:
        con.close()


def _pattern_payload(confidence_tier: str = "case_observation") -> dict[str, object]:
    return {
        "schema_version": 4,
        "build_design_observations": [
            {
                "observation_type": "build_archetype",
                "title": "Lightning projectile shell",
                "summary": "A safe observation about a projectile shell.",
                "axes": ["character_shell", "primary_skill_package", "scaling_axis"],
                "components": [
                    {
                        "component_key": "skill:LightningArrowPlayer",
                        "role": "primary_damage",
                        "resolution": _resolution_evidence("skill:LightningArrowPlayer"),
                    },
                    {
                        "component_key": "support:Scattershot",
                        "role": "support_modifier",
                        "resolution": _resolution_evidence("support:Scattershot"),
                    },
                ],
                "source_case_refs": ["case:la-safe"],
                "safe_evidence_refs": ["safe:la:hash"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
        "patterns": [
            {
                "pattern_type": "cooccurrence",
                "title": "Projectile primary plus projectile support",
                "summary": "A safe co-occurrence pattern without recipe detail.",
                "component_keys": ["skill:LightningArrowPlayer", "support:Scattershot"],
                "component_roles": {
                    "skill:LightningArrowPlayer": "primary_damage",
                    "support:Scattershot": "support_modifier",
                },
                "confidence_tier": confidence_tier,
                "sample_count": 1,
                "family_count": 1,
                "source_diversity_count": 1,
                "denominator": 1,
                "source_case_refs": ["case:la-safe"],
                "safe_evidence_refs": ["safe:la:hash"],
                "context_requirements": [
                    {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_budget"]}
                ],
                "planner_hint": "Try this as an advisory projectile package candidate.",
                "verification_tasks": ["Verify support legality with socket helper."],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
    }


def test_pattern_payload_accepts_build_design_observation_and_case_pattern():
    result = research_models.validate_researcher_output(_pattern_payload())

    assert result["status"] == "accepted"
    assert result["observationCount"] == 1


def test_memory_query_returns_creator_patterns_and_semantic_edges(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    edge_result = service.propose_semantic_edges(
        _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    )
    pattern_result = service.propose_build_patterns(_pattern_payload())

    recalled = service.query_research_memory(
        "投射物组合",
        component_keys=["skill:LightningArrowPlayer"],
    )

    assert [row["edgeId"] for row in recalled["semanticEdges"]] == edge_result["edgeIds"]
    assert [row["patternId"] for row in recalled["buildPatterns"]] == pattern_result["patternIds"]
    assert recalled["buildPatterns"][0]["confidenceTier"] == "case_observation"
    assert recalled["buildPatterns"][0]["componentRoles"]["support:Scattershot"] == (
        "support_modifier"
    )
    assert recalled["semanticEdges"][0]["contextRequirements"]
    assert recalled["noRawMatureBuildMaterial"] is True


def test_pattern_payload_rejects_single_component_pattern():
    payload = _pattern_payload()
    payload["patterns"][0]["component_keys"] = ["skill:LightningArrowPlayer"]
    payload["patterns"][0]["component_roles"] = {"skill:LightningArrowPlayer": "primary_damage"}

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"


def test_pattern_payload_accepts_ascendancy_shell_role():
    payload = _pattern_payload()
    ascendancy_component = {
        "component_key": "ascendancy:monk:martial_artist",
        "role": "ascendancy_shell",
        "resolution": _resolution_evidence("ascendancy:monk:martial_artist"),
    }
    payload["build_design_observations"][0]["components"].append(ascendancy_component)
    payload["patterns"][0]["component_keys"].append("ascendancy:monk:martial_artist")
    payload["patterns"][0]["component_roles"]["ascendancy:monk:martial_artist"] = "ascendancy_shell"

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "accepted"
    assert result["patternCount"] == 1


def test_pattern_payload_rejects_common_claim_with_low_sample_count():
    payload = _pattern_payload(confidence_tier="common_within_archetype")

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "insufficient_pattern_evidence"


def _as_transfer_candidate(
    payload: dict[str, object],
    *,
    family_key: str,
    case_ref: str,
    title: str,
) -> dict[str, object]:
    observation = payload["build_design_observations"][0]
    pattern = payload["patterns"][0]
    observation["title"] = title
    observation["source_case_refs"] = [case_ref]
    observation["safe_evidence_refs"] = [f"safe:{case_ref}"]
    pattern.update(
        {
            "title": title,
            "transfer_scope": "component",
            "applicability_axes": ["primary_skill_package"],
            "applicability_requirements": ["The active skill can use projectile supports."],
            "exclusion_conditions": ["Reject when the support is illegal for the active skill."],
            "transfer_rationale": "The package depends on skill/support compatibility, not ascendancy.",
            "origin_family_keys": [family_key],
            "source_case_refs": [case_ref],
            "safe_evidence_refs": [f"safe:{case_ref}"],
        }
    )
    return payload


def test_transferable_pattern_rejects_cross_family_strong_ranking_authority():
    payload = _as_transfer_candidate(
        _pattern_payload(confidence_tier="strong_ranking_hint"),
        family_key="bf-family-one",
        case_ref="case:transfer-one",
        title="Transfer candidate one",
    )
    payload["patterns"][0]["sample_count"] = 15
    payload["patterns"][0]["source_diversity_count"] = 2

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "overclaimed_transfer_scope"


def test_transferable_patterns_aggregate_only_across_distinct_families(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    first = _as_transfer_candidate(
        _pattern_payload(),
        family_key="bf-family-one",
        case_ref="case:transfer-one",
        title="First wording for the transferable package",
    )
    second = _as_transfer_candidate(
        _pattern_payload(),
        family_key="bf-family-two",
        case_ref="case:transfer-two",
        title="Different wording for the same transferable package",
    )

    first_result = service.propose_build_patterns(first)
    second_result = service.propose_build_patterns(second)

    assert first_result["status"] == "accepted"
    assert second_result["status"] == "accepted"
    assert first_result["patternIds"] == second_result["patternIds"]
    assert second_result["promotedPatternIds"] == second_result["patternIds"]
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        rows = con.execute("SELECT * FROM research_build_patterns").fetchall()
        assert len(rows) == 1
        assert rows[0]["transfer_scope"] == "component"
        assert rows[0]["confidence_tier"] == "recurring_observation"
        assert rows[0]["sample_count"] == 2
        assert rows[0]["family_count"] == 2
        assert json.loads(rows[0]["origin_family_keys"]) == [
            "bf-family-one",
            "bf-family-two",
        ]
    finally:
        con.close()


def test_query_returns_transferable_patterns_in_a_separate_capped_lane(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _as_transfer_candidate(
        _pattern_payload(),
        family_key="bf-family-one",
        case_ref="case:transfer-one",
        title="Transferable projectile package",
    )
    accepted = service.propose_build_patterns(payload)

    exact_only = service.query_research_memory(
        "projectile package",
        component_keys=["skill:LightningArrowPlayer"],
    )
    with_transfer = service.query_research_memory(
        "projectile package",
        component_keys=["skill:LightningArrowPlayer"],
        include_transferable=True,
        research_axes=["primary_skill_package"],
    )

    assert accepted["status"] == "accepted"
    assert exact_only["buildPatterns"] == []
    assert exact_only["transferablePatterns"] == []
    assert [row["patternId"] for row in with_transfer["transferablePatterns"]] == accepted[
        "patternIds"
    ]
    recalled = with_transfer["transferablePatterns"][0]
    assert recalled["transferScope"] == "component"
    assert recalled["scopeWeightCap"] == 0.8
    assert (
        with_transfer["retrievalPolicy"][
            "transferableKnowledgeNeverOutranksEquivalentFamilyKnowledge"
        ]
        is True
    )


def test_transferable_pattern_keeps_family_weight_in_its_origin_family(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    record_payload = _deep_record_payload()
    record = record_payload["deep_research_records"][0]
    record["record_kind"] = "skill_package"
    record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        },
        {
            "candidate_name": "Scattershot",
            "role": "support_modifier",
            "resolver_query": "Scattershot",
            "expected_node_types": ["support_gem"],
            "scope": "any",
            "component_key": "support:Scattershot",
            "resolution_status": "resolved",
        },
    ]
    record["typed_payload"] = {
        "supportPackages": [
            {
                "skillKey": "skill:LightningArrowPlayer",
                "supportKeys": ["support:Scattershot"],
            }
        ]
    }
    record_result = service.propose_deep_research_records(record_payload)
    family_key = record_result["buildFamilyKeys"][0]
    pattern_result = service.propose_build_patterns(
        _as_transfer_candidate(
            _pattern_payload(),
            family_key=family_key,
            case_ref="case:origin-family",
            title="Transferable package important to its origin family",
        )
    )

    recalled = service.query_research_memory(
        "",
        component_keys=[
            "ascendancy:monk:martial_artist",
            "skill:LightningArrowPlayer",
        ],
        include_transferable=True,
        research_axes=["primary_skill_package"],
    )

    assert pattern_result["status"] == "accepted"
    assert [row["patternId"] for row in recalled["buildPatterns"]] == pattern_result["patternIds"]
    origin_pattern = recalled["buildPatterns"][0]
    assert origin_pattern["transferScope"] == "component"
    assert origin_pattern["matchScope"] == "origin_family"
    assert origin_pattern["scopeWeightCap"] == 1.0
    assert recalled["transferablePatterns"] == []
    assert recalled["retrievalPolicy"]["originFamilyTransferablePatternsUseFamilyWeight"] is True


def test_propose_build_patterns_persists_creator_visible_safe_patterns(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )

    result = service.propose_build_patterns(_pattern_payload())

    assert result["status"] == "accepted"
    assert result["observationIds"]
    assert result["patternIds"]
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        pattern = con.execute("SELECT * FROM research_build_patterns").fetchone()
        assert pattern["pattern_type"] == "cooccurrence"
        assert pattern["confidence_tier"] == "case_observation"
        assert pattern["planner_visible"] == 1
    finally:
        con.close()


def test_propose_build_patterns_refreshes_source_refs_on_idempotent_update(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    first = _pattern_payload()
    second = _pattern_payload()
    second["build_design_observations"][0]["source_case_refs"] = ["case:new-ref"]
    second["build_design_observations"][0]["safe_evidence_refs"] = ["safe:new-ref"]
    second["patterns"][0]["source_case_refs"] = ["case:new-ref"]
    second["patterns"][0]["safe_evidence_refs"] = ["safe:new-ref"]

    assert service.propose_build_patterns(first)["status"] == "accepted"
    assert service.propose_build_patterns(second)["status"] == "accepted"

    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        observation = con.execute(
            "SELECT source_case_refs FROM research_build_design_observations"
        ).fetchone()
        pattern = con.execute("SELECT source_case_refs FROM research_build_patterns").fetchone()
        assert json.loads(observation["source_case_refs"]) == ["case:new-ref"]
        assert json.loads(pattern["source_case_refs"]) == ["case:new-ref"]
    finally:
        con.close()


def test_propose_build_patterns_persists_ascendancy_shell_role(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _pattern_payload()
    ascendancy_component = {
        "component_key": "ascendancy:monk:martial_artist",
        "role": "ascendancy_shell",
        "resolution": _resolution_evidence("ascendancy:monk:martial_artist"),
    }
    payload["build_design_observations"][0]["components"].append(ascendancy_component)
    payload["patterns"][0]["component_keys"].append("ascendancy:monk:martial_artist")
    payload["patterns"][0]["component_roles"]["ascendancy:monk:martial_artist"] = "ascendancy_shell"

    result = service.propose_build_patterns(payload)

    assert result["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute("SELECT component_roles FROM research_build_patterns").fetchone()
        assert (
            json.loads(row["component_roles"])["ascendancy:monk:martial_artist"]
            == "ascendancy_shell"
        )
    finally:
        con.close()


def test_propose_build_patterns_accepts_apostrophe_unique_stable_key(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(
            extra_nodes=[
                pg.GraphNode(
                    stable_key="unique:pob:alpha's_howl",
                    node_type="unique",
                    display_name="Alpha's Howl",
                    status="valid",
                    source_refs=("fixture:phase4",),
                )
            ],
            extra_aliases=[
                pg.GraphAlias(
                    alias="Alpha's Howl",
                    target_key="unique:pob:alpha's_howl",
                    source_refs=("fixture:phase4",),
                )
            ],
        ),
    )
    payload = _pattern_payload()
    unique_component = {
        "component_key": "unique:pob:alpha's_howl",
        "role": "unique_enabler",
        "resolution": _resolution_evidence("unique:pob:alpha's_howl"),
    }
    payload["build_design_observations"][0]["components"].append(unique_component)
    payload["patterns"][0]["component_keys"].append("unique:pob:alpha's_howl")
    payload["patterns"][0]["component_roles"]["unique:pob:alpha's_howl"] = "unique_enabler"

    result = service.propose_build_patterns(payload)

    assert result["status"] == "accepted"


def test_propose_build_patterns_rejects_unresolved_component_endpoint(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _pattern_payload()
    payload["build_design_observations"][0]["components"][0]["resolution"] = None

    result = service.propose_build_patterns(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_endpoint_resolution"


def test_propose_build_patterns_requires_observation_for_pattern(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _pattern_payload()
    payload["build_design_observations"] = []

    result = service.propose_build_patterns(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_build_design_observation"


def test_propose_build_patterns_rejects_pattern_patched_from_unrelated_observations(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _pattern_payload()
    payload["build_design_observations"] = [
        {
            **payload["build_design_observations"][0],
            "components": [payload["build_design_observations"][0]["components"][0]],
        },
        {
            **payload["build_design_observations"][0],
            "title": "Unrelated support observation",
            "components": [payload["build_design_observations"][0]["components"][1]],
        },
    ]

    result = service.propose_build_patterns(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_build_design_observation"


def test_propose_build_patterns_rejects_visibility_or_version_mismatch_observation(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _pattern_payload()
    payload["build_design_observations"][0]["visibility"] = "evaluator_only"
    payload["build_design_observations"][0]["split"] = "eval_holdout"

    result = service.propose_build_patterns(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_build_design_observation"


def test_pattern_payload_rejects_case_observation_using_common_language():
    payload = _pattern_payload()
    payload["patterns"][0]["summary"] = "This commonly appears as a usual package."

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "overclaimed_pattern_confidence"


def test_pattern_payload_allows_negated_common_language_guardrail():
    payload = _pattern_payload()
    payload["patterns"][0]["summary"] = (
        "This is a single-sample observation and cannot be claimed as common."
    )
    payload["patterns"][0]["planner_hint"] = "不能外推为常见组合，只能作为低置信观察。"

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "accepted"


def test_propose_build_patterns_updates_planner_fields_for_same_pattern_revision(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    original = _pattern_payload()
    first = service.propose_build_patterns(original)
    assert first["status"] == "accepted"

    revised = _pattern_payload()
    revised["build_design_observations"][0]["components"][0]["role"] = "clear_skill"
    revised["patterns"][0]["component_roles"]["skill:LightningArrowPlayer"] = "clear_skill"
    revised["patterns"][0]["denominator"] = 2
    revised["patterns"][0]["context_requirements"] = [
        {
            "context_type": "verification_gate_requirement",
            "task": "Verify the revised resource state before reuse.",
        }
    ]
    revised["patterns"][0]["planner_hint"] = "Use the revised planner guidance."
    revised["patterns"][0]["verification_tasks"] = [
        "Verify the revised endpoint and resource state."
    ]
    revised["build_design_observations"][0]["pob_version_or_commit"] = "0.22.0"
    revised["patterns"][0]["pob_version_or_commit"] = "0.22.0"

    second = service.propose_build_patterns(revised)
    assert second["status"] == "accepted"

    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT component_roles, denominator, context_requirements, planner_hint, "
            "verification_tasks, pob_version_or_commit "
            "FROM research_build_patterns WHERE pattern_id = ?",
            (first["patternIds"][0],),
        ).fetchone()
        assert row is not None
        assert json.loads(row["component_roles"]) == revised["patterns"][0]["component_roles"]
        assert row["denominator"] == 2
        assert (
            json.loads(row["context_requirements"])
            == revised["patterns"][0]["context_requirements"]
        )
        assert row["planner_hint"] == revised["patterns"][0]["planner_hint"]
        assert json.loads(row["verification_tasks"]) == revised["patterns"][0]["verification_tasks"]
        assert row["pob_version_or_commit"] == "0.22.0"
        observation = con.execute(
            "SELECT components, pob_version_or_commit "
            "FROM research_build_design_observations WHERE observation_id = ?",
            (first["observationIds"][0],),
        ).fetchone()
        assert observation is not None
        assert (
            json.loads(observation["components"])
            == revised["build_design_observations"][0]["components"]
        )
        assert observation["pob_version_or_commit"] == "0.22.0"
    finally:
        con.close()


def test_pattern_payload_rejects_common_without_source_diversity():
    payload = _pattern_payload(confidence_tier="common_within_archetype")
    payload["patterns"][0]["sample_count"] = 8
    payload["patterns"][0]["family_count"] = 1
    payload["patterns"][0]["source_diversity_count"] = 1
    payload["patterns"][0]["denominator"] = 12

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "insufficient_pattern_evidence"


def test_pattern_payload_rejects_open_build_state_context_requirement():
    payload = _pattern_payload()
    payload["patterns"][0]["context_requirements"] = [
        {
            "context_type": "build_state_context",
            "spirit_reservation_summary": {"anything": {"nested": "dict"}},
        }
    ]

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"


def test_pattern_payload_rejects_component_role_key_or_role_mismatch():
    payload = _pattern_payload()
    payload["patterns"][0]["component_roles"] = {
        "skill:LightningArrowPlayer": "primary_damage",
        "skill:NotInPattern": "whatever_role",
    }

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"


def test_pattern_payload_rejects_blank_component_key():
    payload = _pattern_payload()
    payload["build_design_observations"][0]["components"][0]["component_key"] = ""
    payload["build_design_observations"][0]["components"][0]["resolution"]["stable_key"] = ""
    payload["build_design_observations"][0]["components"][0]["resolution"][
        "evidence_path_nodes"
    ] = [""]
    payload["patterns"][0]["component_keys"][0] = ""
    payload["patterns"][0]["component_roles"] = {
        "": "primary_damage",
        "support:Scattershot": "support_modifier",
    }

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"


def test_pattern_payload_rejects_denominator_below_sample_count():
    payload = _pattern_payload(confidence_tier="common_within_archetype")
    payload["patterns"][0]["sample_count"] = 8
    payload["patterns"][0]["family_count"] = 2
    payload["patterns"][0]["source_diversity_count"] = 2
    payload["patterns"][0]["denominator"] = 7

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "insufficient_pattern_evidence"


def test_skill_package_cannot_hide_resolved_support_from_ownership_with_functional_role():
    payload = _deep_record_payload()
    record = payload["deep_research_records"][0]
    support_key = "support:FixtureFunctionalGenerator"
    record["record_kind"] = "skill_package"
    record["component_keys"] = ["skill:LightningArrowPlayer", support_key]
    record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "skill:LightningArrowPlayer",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        },
        {
            "candidate_name": "Fixture Functional Generator",
            "role": "generator",
            "resolver_query": support_key,
            "expected_node_types": ["support_gem"],
            "scope": "any",
            "component_key": support_key,
            "resolution_status": "resolved",
        },
    ]
    record["typed_payload"] = {}

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"
    assert "supportPackages" in json.dumps(result["facts"]["validationIssues"], ensure_ascii=False)


def test_skill_package_support_ownership_allows_functional_role_when_explicitly_packaged():
    payload = _deep_record_payload()
    record = payload["deep_research_records"][0]
    support_key = "support:FixtureFunctionalGenerator"
    record["record_kind"] = "skill_package"
    record["component_keys"] = ["skill:LightningArrowPlayer", support_key]
    record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "skill:LightningArrowPlayer",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        },
        {
            "candidate_name": "Fixture Functional Generator",
            "role": "generator",
            "resolver_query": support_key,
            "expected_node_types": ["support_gem"],
            "scope": "any",
            "component_key": support_key,
            "resolution_status": "resolved",
        },
    ]
    record["typed_payload"] = {
        "supportPackages": [
            {
                "skillKey": "skill:LightningArrowPlayer",
                "supportKeys": [support_key],
            }
        ]
    }

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "accepted"


def test_pattern_patch_decay_removes_pattern_from_planner_visible_context(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    accepted = service.propose_build_patterns(_pattern_payload())

    decay = service.apply_patch_decay(
        changed_component_keys=["support:Scattershot"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )

    assert decay["patternsUpdated"] == 1
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT status, planner_visible FROM research_build_patterns WHERE pattern_id = ?",
            (accepted["patternIds"][0],),
        ).fetchone()
        assert row["status"] == "needs_revalidation"
        assert row["planner_visible"] == 0
    finally:
        con.close()


def test_pattern_revalidation_can_restore_planner_visible_context(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    accepted = service.propose_build_patterns(_pattern_payload())
    pattern_id = accepted["patternIds"][0]
    service.apply_patch_decay(
        changed_component_keys=["support:Scattershot"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )

    result = service.submit_revalidation_result(
        target_kind="build_pattern",
        target_id=pattern_id,
        outcome="still_valid",
        new_version_context={
            "game_patch": "0.6.0",
            "passive_tree_version": "0_6",
            "pob_version_or_commit": "unknown",
        },
        safe_evidence_refs=["safe:pattern-revalidated"],
        affected_component_keys=["support:Scattershot"],
    )

    assert result["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            """
            SELECT status, planner_visible, game_patch, passive_tree_version, current_version_context
            FROM research_build_patterns
            WHERE pattern_id = ?
            """,
            (pattern_id,),
        ).fetchone()
        assert row["status"] == "valid"
        assert row["planner_visible"] == 1
        assert row["game_patch"] == "0.6.0"
        assert row["passive_tree_version"] == "0_6"
        assert json.loads(row["current_version_context"])["game_patch"] == "0.6.0"
        event = con.execute(
            "SELECT target_kind FROM research_revalidation_events WHERE target_id = ?",
            (pattern_id,),
        ).fetchone()
        assert event["target_kind"] == "build_pattern"
    finally:
        con.close()


def test_pattern_revalidation_migrates_legacy_revalidation_event_check(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")
        con.execute(
            """
            CREATE TABLE research_revalidation_events (
                event_id TEXT PRIMARY KEY,
                target_kind TEXT NOT NULL,
                target_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                old_version_context TEXT NOT NULL,
                new_version_context TEXT NOT NULL,
                safe_evidence_refs TEXT NOT NULL,
                affected_component_keys TEXT NOT NULL,
                created_at TEXT NOT NULL,
                CHECK (target_kind IN ('fragment', 'semantic_edge')),
                CHECK (outcome IN ('still_valid', 'invalidated', 'changed_scope', 'needs_review'))
            )
            """
        )
        con.commit()
    finally:
        con.close()

    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    accepted = service.propose_build_patterns(_pattern_payload())
    pattern_id = accepted["patternIds"][0]
    service.apply_patch_decay(
        changed_component_keys=["support:Scattershot"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )

    result = service.submit_revalidation_result(
        target_kind="build_pattern",
        target_id=pattern_id,
        outcome="still_valid",
        new_version_context={
            "game_patch": "0.6.0",
            "passive_tree_version": "0_6",
            "pob_version_or_commit": "unknown",
        },
        safe_evidence_refs=["safe:pattern-revalidated"],
        affected_component_keys=["support:Scattershot"],
    )

    assert result["status"] == "accepted"


def test_transient_packet_uses_temp_prefix_and_startup_gc(tmp_path):
    case = {
        "safeMetadata": {"caseId": "safe-case", "mainSkill": "Lightning Arrow"},
        "rawContext": {"pobCode": "eNrt" + "A" * 80},
    }
    result = research_packet.build_research_packet(
        case,
        persist_for_transport=True,
        ttl_seconds=1,
        temp_root=tmp_path,
    )

    assert result["ok"] is True
    packet_path = Path(result["packetPath"])
    assert "poe-bd-creator-research-packet-" in str(packet_path)
    assert result["packet"]["safeHash"]
    assert "pobCode" in json.loads(packet_path.read_text(encoding="utf-8"))["rawContext"]

    removed = research_packet.cleanup_expired_packets(
        temp_root=tmp_path, now=result["packet"]["expiresAt"]
    )
    assert removed["removed"] == 1
    assert not packet_path.parent.exists()


def test_transient_packet_path_is_json_serializable_string(tmp_path):
    result = research_packet.build_research_packet(
        {"safeMetadata": {"caseId": "safe-case"}, "rawContext": {"raw": "quarantine-only"}},
        persist_for_transport=True,
        ttl_seconds=1,
        temp_root=tmp_path,
    )

    json.dumps(result)
    assert isinstance(result["packetPath"], str)


def test_query_before_propose_and_append_evidence_prevent_duplicate_fragments(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")

    missing = service.propose_research_fragments(_fragment_payload())
    assert missing["errorCode"] == "missing_dedupe_query"

    forged = service.propose_research_fragments(
        _fragment_payload("Forged query ref should fail"),
        dedupe_query_ref="dq-forged",
    )
    assert forged["status"] == "rejected"
    assert forged["errorCode"] == "invalid_dedupe_query_ref"

    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    duplicate = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)

    assert accepted["status"] == "accepted"
    assert duplicate["status"] == "rejected"
    assert duplicate["errorCode"] == "duplicate_fragment_candidate"

    fragment_id = accepted["fragmentIds"][0]
    appended = service.append_evidence_to_fragment(
        fragment_id=fragment_id,
        source_case_refs=["case:la-second"],
        safe_evidence_refs=["safe:la:second"],
        game_patch="0.5.4",
        passive_tree_version="0_5",
        pob_version_or_commit="unknown",
        visibility="creator_visible",
        split="train_context",
        knowledge_scope="global_seed",
        confidence="medium",
    )
    holdout = service.append_evidence_to_fragment(
        fragment_id=fragment_id,
        source_case_refs=["case:holdout"],
        safe_evidence_refs=["safe:holdout"],
        game_patch="0.5.4",
        passive_tree_version="0_5",
        pob_version_or_commit="unknown",
        visibility="evaluator_only",
        split="eval_holdout",
        knowledge_scope="eval_ephemeral",
        confidence="medium",
    )

    assert appended["status"] == "accepted"
    assert appended["evidenceCount"] == 2
    assert holdout["status"] == "rejected"
    assert holdout["errorCode"] == "holdout_boundary_violation"


def test_semantic_edges_require_resolver_evidence_for_each_endpoint(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    del payload["semantic_edges"][0]["source_resolution"]

    result = service.propose_semantic_edges(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_endpoint_resolution"


def test_semantic_edge_resolver_evidence_must_match_stable_key_and_snapshot(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    mismatch = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    mismatch["semantic_edges"][0]["source_resolution"]["stable_key"] = "support:Scattershot"
    stale_snapshot = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    stale_snapshot["semantic_edges"][0]["target_resolution"]["snapshot_id"] = "snapshot:old"

    mismatch_result = service.propose_semantic_edges(mismatch)
    stale_result = service.propose_semantic_edges(stale_snapshot)

    assert mismatch_result["status"] == "rejected"
    assert mismatch_result["errorCode"] == "endpoint_resolution_mismatch"
    assert stale_result["status"] == "rejected"
    assert stale_result["errorCode"] == "stale_endpoint_resolution"


def test_semantic_edge_resolver_evidence_source_refs_must_match_graph_sources(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    payload["semantic_edges"][0]["source_resolution"]["source_refs"] = ["fixture:wrong"]

    result = service.propose_semantic_edges(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "endpoint_resolution_mismatch"
    assert "source refs" in result["caveats"][0]


def test_semantic_edge_resolver_evidence_rejects_forged_extra_source_refs(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    payload["semantic_edges"][0]["source_resolution"]["source_refs"] = [
        "fixture:phase4",
        "fixture:forged",
    ]

    result = service.propose_semantic_edges(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "endpoint_resolution_mismatch"
    assert "source refs" in result["caveats"][0]


def test_synergizes_with_id_uses_canonical_payload_not_raw_concatenation(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )

    first = service.propose_semantic_edges(_edge_payload("gem:A", "mechanic:BC"))
    second = service.propose_semantic_edges(_edge_payload("gem:AB", "mechanic:C"))

    assert first["status"] == "accepted"
    assert second["status"] == "accepted"
    assert first["edgeIds"][0] != second["edgeIds"][0]


def test_directional_short_cycle_detection_is_bounded_to_depth_three(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )

    assert (
        service.propose_semantic_edges(
            _edge_payload("skill:LightningArrowPlayer", "support:Scattershot", "enables_mechanic")
        )["status"]
        == "accepted"
    )
    assert (
        service.propose_semantic_edges(
            _edge_payload("support:Scattershot", "passive:pob:0_5:100", "enables_mechanic")
        )["status"]
        == "accepted"
    )
    cycle = service.propose_semantic_edges(
        _edge_payload("passive:pob:0_5:100", "skill:LightningArrowPlayer", "enables_mechanic")
    )

    assert cycle["status"] == "rejected"
    assert cycle["errorCode"] == "semantic_cycle_or_conflict"
    assert cycle["facts"]["maxDepthChecked"] == 3
    assert cycle["facts"]["conflictKind"] == "short_cycle"
    assert cycle["facts"]["cycleDepth"] == 2
    assert cycle["facts"]["cyclePath"] == (
        "skill:LightningArrowPlayer>support:Scattershot>passive:pob:0_5:100"
    )


def test_directional_inverse_edge_conflict_names_existing_edge_endpoints(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )

    first = service.propose_semantic_edges(
        _edge_payload("skill:LightningArrowPlayer", "support:Scattershot", "enables_mechanic")
    )
    assert first["status"] == "accepted"

    inverse = service.propose_semantic_edges(
        _edge_payload("support:Scattershot", "skill:LightningArrowPlayer", "enables_mechanic")
    )

    assert inverse["status"] == "rejected"
    assert inverse["errorCode"] == "semantic_cycle_or_conflict"
    facts = inverse["facts"]
    assert facts["conflictKind"] == "inverse_edge"
    assert facts["conflictingExistingEdgeId"] == first["edgeIds"][0]
    assert facts["conflictingExistingSourceKey"] == "skill:LightningArrowPlayer"
    assert facts["conflictingExistingTargetKey"] == "support:Scattershot"
    assert facts["conflictSourceKey"] == "support:Scattershot"
    assert facts["conflictTargetKey"] == "skill:LightningArrowPlayer"


def test_non_valid_or_unsafe_semantic_edges_are_not_planner_visible(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    payload["semantic_edges"][0]["status"] = "needs_revalidation"
    payload["semantic_edges"][0]["copy_safety_state"] = "needs_review"

    accepted = service.propose_semantic_edges(payload)

    assert accepted["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT planner_visible FROM research_semantic_edges WHERE edge_id = ?",
            (accepted["edgeIds"][0],),
        ).fetchone()
        assert row["planner_visible"] == 0
    finally:
        con.close()


def test_patch_decay_can_be_revalidated_without_duplicate_successor(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    fragment_id = accepted["fragmentIds"][0]

    decay = service.apply_patch_decay(
        changed_component_keys=["skill:LightningArrowPlayer"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )
    renewed = service.submit_revalidation_result(
        target_kind="fragment",
        target_id=fragment_id,
        outcome="still_valid",
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
        safe_evidence_refs=["safe:revalidated"],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )

    assert decay["itemsUpdated"] == 1
    assert renewed["status"] == "accepted"
    assert renewed["targetId"] == fragment_id
    result = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )
    assert result["results"][0]["status"] == "valid"
    assert result["results"][0]["gamePatch"] == "0.6.0"


def test_semantic_edges_require_graph_service_endpoint_validation(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")

    result = service.propose_semantic_edges(
        _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "graph_service_unavailable"
    assert result["endpointAssessment"]["classification"] == "graph_snapshot_unavailable"
    assert result["endpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert result["endpointAssessment"]["candidateEndpointKeys"] == []
    assert result["endpointAssessment"]["missingEndpointKeys"] == []


def test_missing_endpoint_is_reported_as_source_coverage_gap_not_hallucination(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )

    result = service.propose_semantic_edges(
        _edge_payload("skill:VividStampedePlayer", "support:Scattershot")
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_endpoint"
    assert result["endpointAssessment"]["classification"] == "source_coverage_gap"
    assert result["endpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert result["endpointAssessment"]["candidateEndpointKeys"] == ["skill:VividStampedePlayer"]
    assert result["endpointAssessment"]["missingEndpointKeys"] == ["skill:VividStampedePlayer"]
    assert result["facts"]["missingEndpointKeys"] == ["skill:VividStampedePlayer"]


def test_append_and_revalidation_reject_copyable_evidence_refs(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    fragment_id = accepted["fragmentIds"][0]

    append_result = service.append_evidence_to_fragment(
        fragment_id=fragment_id,
        source_case_refs=["case:copyable"],
        safe_evidence_refs=["eNrt" + "A" * 80],
        game_patch="0.5.4",
        passive_tree_version="0_5",
        pob_version_or_commit="unknown",
        visibility="creator_visible",
        split="train_context",
        knowledge_scope="global_seed",
        confidence="medium",
    )
    revalidation_result = service.submit_revalidation_result(
        target_kind="fragment",
        target_id=fragment_id,
        outcome="still_valid",
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
        safe_evidence_refs=["eNrt" + "B" * 80],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )

    assert append_result["status"] == "rejected"
    assert append_result["errorCode"] == "copy_safety_violation"
    assert revalidation_result["status"] == "rejected"
    assert revalidation_result["errorCode"] == "copy_safety_violation"


def test_fragment_proposal_rejects_profile_urls_and_long_guide_prose(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    profile_url = _fragment_payload("Profile URL leak")
    profile_url["fragments"][0]["summary"] = (
        "See https://www.pathofexile.com/account/view-profile/example/characters"
    )
    ninja_url = _fragment_payload("Ninja URL leak")
    ninja_url["fragments"][0]["summary"] = (
        "See https://poe.ninja/poe2/builds/standard/character/Account/Character"
    )
    guide_prose = _fragment_payload("Long guide leak")
    guide_prose["fragments"][0]["summary"] = " ".join(f"guideword{i}" for i in range(230))

    profile_ref = service.query_research_memory("profile leak", component_keys=[])["dedupeQueryRef"]
    ninja_ref = service.query_research_memory("ninja leak", component_keys=[])["dedupeQueryRef"]
    prose_ref = service.query_research_memory("guide prose leak", component_keys=[])[
        "dedupeQueryRef"
    ]

    profile_result = service.propose_research_fragments(profile_url, dedupe_query_ref=profile_ref)
    ninja_result = service.propose_research_fragments(ninja_url, dedupe_query_ref=ninja_ref)
    prose_result = service.propose_research_fragments(guide_prose, dedupe_query_ref=prose_ref)

    assert profile_result["status"] == "rejected"
    assert profile_result["errorCode"] == "copy_safety_violation"
    assert ninja_result["status"] == "rejected"
    assert ninja_result["errorCode"] == "copy_safety_violation"
    assert prose_result["status"] == "rejected"
    assert prose_result["errorCode"] == "copy_safety_violation"


def test_append_and_revalidation_check_all_persisted_version_context(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    fragment_id = accepted["fragmentIds"][0]

    append_result = service.append_evidence_to_fragment(
        fragment_id=fragment_id,
        source_case_refs=["case:safe"],
        safe_evidence_refs=["safe:review"],
        game_patch="0.5.4",
        passive_tree_version="0_5",
        pob_version_or_commit="eNrt" + "C" * 80,
        visibility="creator_visible",
        split="train_context",
        knowledge_scope="global_seed",
        confidence="medium",
    )
    revalidation_result = service.submit_revalidation_result(
        target_kind="fragment",
        target_id=fragment_id,
        outcome="still_valid",
        new_version_context={"pob_version_or_commit": "eNrt" + "D" * 80},
        safe_evidence_refs=["safe:review"],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )

    assert append_result["status"] == "rejected"
    assert append_result["errorCode"] == "copy_safety_violation"
    assert revalidation_result["status"] == "rejected"
    assert revalidation_result["errorCode"] == "copy_safety_violation"


def test_non_dict_proposals_return_public_errors_without_traceback(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")

    query_ref = service.query_research_memory("schema validation", component_keys=[])[
        "dedupeQueryRef"
    ]
    fragments = service.propose_research_fragments([], dedupe_query_ref=query_ref)  # type: ignore[arg-type]
    edges = service.propose_semantic_edges([])  # type: ignore[arg-type]

    assert fragments["status"] == "error"
    assert fragments["errorCode"] == "invalid_schema"
    assert "Traceback" not in str(fragments)
    assert edges["status"] == "error"
    assert edges["errorCode"] == "invalid_schema"
    assert "Traceback" not in str(edges)


def test_revalidation_rejects_invalid_target_kind_and_outcome(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    fragment_id = accepted["fragmentIds"][0]

    bad_kind = service.submit_revalidation_result(
        target_kind="raw_sql",
        target_id=fragment_id,
        outcome="still_valid",
        new_version_context={"game_patch": "0.6.0"},
        safe_evidence_refs=["safe:review"],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )
    bad_outcome = service.submit_revalidation_result(
        target_kind="fragment",
        target_id=fragment_id,
        outcome="bless_forever",
        new_version_context={"game_patch": "0.6.0"},
        safe_evidence_refs=["safe:review"],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )

    assert bad_kind["status"] == "rejected"
    assert bad_kind["errorCode"] == "invalid_revalidation_target_kind"
    assert bad_outcome["status"] == "rejected"
    assert bad_outcome["errorCode"] == "invalid_revalidation_outcome"


def test_query_uses_fts_text_not_only_component_filter(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)

    hit = service.query_research_memory("projectile", component_keys=["skill:LightningArrowPlayer"])
    miss = service.query_research_memory(
        "mana flask", component_keys=["skill:LightningArrowPlayer"]
    )

    assert hit["results"]
    assert miss["results"] == []


def test_query_component_filter_uses_exact_stable_key_not_substring(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    payload = _fragment_payload("Projectile substring near miss")
    payload["fragments"][0]["component_keys"] = ["skill:LightningArrowPlayerExtra"]
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayerExtra"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(payload, dedupe_query_ref=query_ref)

    near_miss = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )
    exact = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayerExtra"]
    )

    assert accepted["status"] == "accepted"
    assert near_miss["results"] == []
    assert exact["results"]


def test_query_expands_graph_backed_gem_and_active_skill_identity(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _deep_record_payload()
    record = payload["deep_research_records"][0]
    record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        }
    ]
    accepted = service.propose_deep_research_records(payload)

    result = service.query_research_memory(
        "",
        component_keys=["gem:Metadata/Items/Gems/SkillGemLightningArrow"],
    )

    assert accepted["status"] == "accepted"
    assert result["deepResearchRecords"]
    assert result["buildFamilies"]
    assert result["requestedComponentKeys"] == ["gem:Metadata/Items/Gems/SkillGemLightningArrow"]
    assert result["componentKeyGroups"] == [
        [
            "gem:Metadata/Items/Gems/SkillGemLightningArrow",
            "skill:LightningArrowPlayer",
        ]
    ]


def test_query_hides_deprecated_fragments_after_changed_scope_revalidation(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    fragment_id = accepted["fragmentIds"][0]

    revalidated = service.submit_revalidation_result(
        target_kind="fragment",
        target_id=fragment_id,
        outcome="changed_scope",
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
        safe_evidence_refs=["safe:changed"],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )
    result = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )

    assert revalidated["status"] == "accepted"
    assert result["results"] == []


def test_patch_decay_updates_semantic_edges_by_affected_components(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    accepted = service.propose_semantic_edges(
        _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    )
    edge_id = accepted["edgeIds"][0]

    decay = service.apply_patch_decay(
        changed_component_keys=["support:Scattershot"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )

    assert decay["edgesUpdated"] == 1
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT status, current_version_context FROM research_semantic_edges WHERE edge_id = ?",
            (edge_id,),
        ).fetchone()
        assert row["status"] == "needs_revalidation"
        assert json.loads(row["current_version_context"])["game_patch"] == "0.6.0"
    finally:
        con.close()


def test_semantic_edge_lifecycle_changes_clear_planner_visibility(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    accepted = service.propose_semantic_edges(
        _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    )
    edge_id = accepted["edgeIds"][0]

    decay = service.apply_patch_decay(
        changed_component_keys=["support:Scattershot"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )
    changed = service.submit_revalidation_result(
        target_kind="semantic_edge",
        target_id=edge_id,
        outcome="changed_scope",
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
        safe_evidence_refs=["safe:changed"],
        affected_component_keys=["support:Scattershot"],
    )

    assert decay["edgesUpdated"] == 1
    assert changed["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT status, planner_visible FROM research_semantic_edges WHERE edge_id = ?",
            (edge_id,),
        ).fetchone()
        assert row["status"] == "deprecated"
        assert row["planner_visible"] == 0
    finally:
        con.close()


def test_still_valid_revalidation_does_not_promote_unsafe_semantic_edge(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    payload["semantic_edges"][0]["status"] = "needs_revalidation"
    payload["semantic_edges"][0]["copy_safety_state"] = "needs_review"
    accepted = service.propose_semantic_edges(payload)
    edge_id = accepted["edgeIds"][0]

    renewed = service.submit_revalidation_result(
        target_kind="semantic_edge",
        target_id=edge_id,
        outcome="still_valid",
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
        safe_evidence_refs=["safe:review"],
        affected_component_keys=["support:Scattershot"],
    )

    assert renewed["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT status, copy_safety_state, planner_visible FROM research_semantic_edges WHERE edge_id = ?",
            (edge_id,),
        ).fetchone()
        assert row["status"] == "valid"
        assert row["copy_safety_state"] == "needs_review"
        assert row["planner_visible"] == 0
    finally:
        con.close()


def _seed_family_discovery_service(tmp_path, count: int):
    skill_nodes = [
        pg.GraphNode(
            f"skill:FamilyDiscovery{i:02d}",
            "active_skill",
            f"Family Discovery Skill {i:02d}",
            ("fixture:phase4",),
        )
        for i in range(count)
    ]
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(
            extra_nodes=[
                pg.GraphNode("class:monk", "class", "Monk", ("fixture:phase4",)),
                *skill_nodes,
            ]
        ),
    )
    record_ids: list[str] = []
    for index, node in enumerate(skill_nodes):
        payload = _deep_record_payload(
            f"Family {index:02d} 的机制闭环条件必须在目标 Create 中独立验证。"
        )
        record = payload["deep_research_records"][0]
        record["research_group_id"] = f"research:family-discovery-{index:02d}"
        record["record_kind"] = "skill_package"
        record["title"] = f"Family discovery {index:02d}"
        record["summary"] = f"Family {index:02d} 的轻量候选证据。"
        record["component_keys"] = [node.stable_key]
        record["component_mentions"] = [
            {
                "candidate_name": node.display_name,
                "role": "primary_damage",
                "resolver_query": node.display_name,
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": node.stable_key,
                "resolution_status": "resolved",
            }
        ]
        record["source_case_refs"] = [f"case:family-discovery-{index:02d}"]
        record["safe_evidence_refs"] = [f"safe:family-discovery:{index:02d}"]
        record["conditions"] = [f"family {index:02d} premise"]
        record["failure_conditions"] = [f"family {index:02d} failure"]
        record["class_key"] = "class:monk"
        record["ascendancy_key"] = "ascendancy:monk:martial_artist"
        accepted = service.propose_deep_research_records(payload)
        assert accepted["status"] == "accepted", accepted
        record_ids.append(accepted["recordIds"][0])
    return service, record_ids


def test_family_discovery_returns_top_ten_and_persists_exact_typed_receipt(tmp_path):
    service, record_ids = _seed_family_discovery_service(tmp_path, 12)
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        for index, record_id in enumerate(record_ids):
            con.execute(
                "UPDATE deep_research_records SET evidence_count = ? WHERE record_id = ?",
                (index + 1, record_id),
            )
        con.commit()
    finally:
        con.close()

    result = service.query_research_memory(
        "",
        detail_level="family",
        class_key="class:monk",
        game_patch="0.5.4",
        passive_tree_version="0_5",
    )

    assert result["familyDiscovery"] == {
        "requestedCandidateCount": 10,
        "returnedCandidateCount": 10,
        "coverage": "sufficient",
        "exactVersionOnly": True,
        "didNotBackfillWithStaleFamilies": True,
    }
    assert [row["evidenceCount"] for row in result["buildFamilies"]] == list(range(12, 2, -1))
    assert all("content" not in row for row in result["buildFamilies"])
    receipt = service.read_query_receipt(result["dedupeQueryRef"])
    assert receipt is not None
    assert receipt["request"]["detailLevel"] == "family"
    assert receipt["request"]["classKey"] == "class:monk"
    assert receipt["request"]["gamePatch"] == "0.5.4"
    assert receipt["request"]["passiveTreeVersion"] == "0_5"
    assert {row["buildFamilyKey"] for row in receipt["result"]["buildFamilies"]} == {
        row["buildFamilyKey"] for row in result["buildFamilies"]
    }


def test_family_discovery_returns_all_when_database_has_fewer_than_ten(tmp_path):
    for count, expected_coverage in ((9, "sufficient"), (4, "limited"), (1, "insufficient")):
        service, _record_ids = _seed_family_discovery_service(tmp_path / str(count), count)
        result = service.query_research_memory(
            "",
            detail_level="family",
            class_key="class:monk",
            game_patch="0.5.4",
            passive_tree_version="0_5",
        )
        assert len(result["buildFamilies"]) == count
        assert result["familyDiscovery"]["returnedCandidateCount"] == count
        assert result["familyDiscovery"]["coverage"] == expected_coverage


def test_family_discovery_never_backfills_wrong_class_patch_or_status(tmp_path):
    service, record_ids = _seed_family_discovery_service(tmp_path, 5)
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        con.execute(
            "UPDATE deep_research_records SET game_patch = '0.5.3' WHERE record_id = ?",
            (record_ids[0],),
        )
        con.execute(
            "UPDATE deep_research_records SET passive_tree_version = '0_4' WHERE record_id = ?",
            (record_ids[1],),
        )
        con.execute(
            "UPDATE deep_research_records SET status = 'needs_revalidation' WHERE record_id = ?",
            (record_ids[2],),
        )
        con.execute(
            "UPDATE deep_research_records SET class_key = 'class:ranger' WHERE record_id = ?",
            (record_ids[3],),
        )
        con.commit()
    finally:
        con.close()

    result = service.query_research_memory(
        "",
        detail_level="family",
        class_key="class:monk",
        game_patch="0.5.4",
        passive_tree_version="0_5",
    )

    assert len(result["buildFamilies"]) == 1
    assert result["familyDiscovery"]["coverage"] == "insufficient"
    assert result["buildFamilies"][0]["primarySkillKey"] == "skill:FamilyDiscovery04"


def _family_deep_payload(
    *,
    title: str = "投射物覆盖机制链",
    group: str = "research:la-safe",
    sources: tuple[str, ...] = ("case:la-safe",),
) -> dict:
    payload = _deep_record_payload()
    record = payload["deep_research_records"][0]
    record["record_kind"] = "skill_package"
    record["ascendancy_key"] = "ascendancy:monk:martial_artist"
    record["research_group_id"] = group
    record["title"] = title
    record["source_case_refs"] = list(sources)
    record["component_mentions"] = [
        {
            "candidate_name": "Lightning Arrow",
            "role": "primary_damage",
            "resolver_query": "Lightning Arrow",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:LightningArrowPlayer",
            "resolution_status": "resolved",
        },
        {
            "candidate_name": "Scattershot",
            "role": "support_modifier",
            "resolver_query": "Scattershot",
            "expected_node_types": ["support_gem"],
            "scope": "any",
            "component_key": "support:Scattershot",
            "resolution_status": "resolved",
        },
    ]
    record["typed_payload"] = {
        "supportPackages": [
            {
                "skillKey": "skill:LightningArrowPlayer",
                "supportKeys": ["support:Scattershot"],
            }
        ]
    }
    return payload


def _drift_row_key(db_path: Path, record_id: str, drifted_key: str) -> None:
    """Simulate the historical backfill drift: knowledge_key rewritten in place, id untouched."""
    con = mature_learning.connect(db_path)
    try:
        con.execute(
            "UPDATE deep_research_records SET knowledge_key = ? WHERE record_id = ?",
            (drifted_key, record_id),
        )
        con.commit()
    finally:
        con.close()


def test_persist_adopts_drifted_anchor_row_by_record_id(tmp_path):
    """A row occupying id = hash(knowledge_key) with a drifted stored key is adopted and
    reconciled instead of crashing with a UNIQUE record_id violation."""
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = service.propose_deep_research_records(_family_deep_payload())
    record_id = first["recordIds"][0]
    key = first["knowledgeKeys"][0]
    _drift_row_key(db_path, record_id, "ku-" + "d" * 20)

    second = service.propose_deep_research_records(_family_deep_payload())

    assert second["status"] == "accepted"
    assert second["recordIds"] == [record_id]
    assert second["createdRecordCount"] == 0
    assert second["updatedRecordCount"] == 1
    assert second["knowledgeKeys"] == [key]
    con = mature_learning.connect(db_path)
    try:
        rows = con.execute(
            "SELECT knowledge_key, status, superseded_by_id FROM deep_research_records "
            "WHERE record_id = ?",
            (record_id,),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["knowledge_key"] == key
        assert rows[0]["status"] == "valid"
        assert rows[0]["superseded_by_id"] is None
    finally:
        con.close()


def test_persist_deletes_husk_with_active_head_and_inserts_fresh(tmp_path):
    """A deprecated husk occupying the anchor id whose superseding head is still active
    is removed; a fresh active row is inserted at the anchor with the submitted content."""
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = service.propose_deep_research_records(_family_deep_payload())
    anchor_id = first["recordIds"][0]
    key = first["knowledgeKeys"][0]
    con = mature_learning.connect(db_path)
    try:
        head_row = dict(
            con.execute(
                "SELECT * FROM deep_research_records WHERE record_id = ?", (anchor_id,)
            ).fetchone()
        )
        head_key = "ku-" + "e" * 20
        head_id = "drr-" + research_memory._stable_hash({"knowledge_key": head_key})[:16]
        head_row["record_id"] = head_id
        head_row["knowledge_key"] = head_key
        head_row["research_group_id"] = "research:superseding-case"
        columns = tuple(head_row)
        con.execute(
            f"INSERT INTO deep_research_records({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            tuple(head_row[column] for column in columns),
        )
        con.execute(
            "UPDATE deep_research_records SET status = 'deprecated', superseded_by_id = ? "
            "WHERE record_id = ?",
            (head_id, anchor_id),
        )
        # A second husk that chained through the anchor tombstone: its chain must be
        # re-pointed to the active head when the tombstone is removed.
        chained = dict(
            con.execute(
                "SELECT * FROM deep_research_records WHERE record_id = ?", (anchor_id,)
            ).fetchone()
        )
        chained_id = "drr-" + research_memory._stable_hash({"knowledge_key": "ku-" + "a" * 20})[:16]
        chained["record_id"] = chained_id
        chained["knowledge_key"] = "ku-" + "a" * 20
        chained["research_group_id"] = "research:chained-case"
        chained["status"] = "deprecated"
        chained["superseded_by_id"] = anchor_id
        chained_columns = tuple(chained)
        con.execute(
            f"INSERT INTO deep_research_records({', '.join(chained_columns)}) "
            f"VALUES ({', '.join('?' for _ in chained_columns)})",
            tuple(chained[column] for column in chained_columns),
        )
        con.commit()
    finally:
        con.close()

    second = service.propose_deep_research_records(_family_deep_payload())

    assert second["status"] == "accepted"
    assert second["recordIds"] == [anchor_id]
    assert second["createdRecordCount"] == 1
    con = mature_learning.connect(db_path)
    try:
        anchor = con.execute(
            "SELECT status, superseded_by_id, knowledge_key FROM deep_research_records "
            "WHERE record_id = ?",
            (anchor_id,),
        ).fetchone()
        assert anchor is not None
        assert anchor["status"] == "valid"
        assert anchor["superseded_by_id"] is None
        assert anchor["knowledge_key"] == key
        heads = con.execute(
            "SELECT status FROM deep_research_records WHERE record_id = ?", (head_id,)
        ).fetchall()
        assert len(heads) == 1
        assert heads[0]["status"] == "valid"
        chained = con.execute(
            "SELECT status, superseded_by_id FROM deep_research_records WHERE record_id = ?",
            (chained_id,),
        ).fetchone()
        assert chained is not None
        assert chained["status"] == "deprecated"
        assert chained["superseded_by_id"] == head_id
    finally:
        con.close()


def test_persist_revives_dangling_husk_at_anchor(tmp_path):
    """A husk whose supersession chain is dangling is adopted and revived through the
    update path instead of being INSERTed over."""
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = service.propose_deep_research_records(_family_deep_payload())
    anchor_id = first["recordIds"][0]
    key = first["knowledgeKeys"][0]
    con = mature_learning.connect(db_path)
    try:
        con.execute(
            "UPDATE deep_research_records SET status = 'deprecated', superseded_by_id = ? "
            "WHERE record_id = ?",
            ("drr-ffffffffffffffff", anchor_id),
        )
        con.commit()
    finally:
        con.close()

    second = service.propose_deep_research_records(_family_deep_payload())

    assert second["status"] == "accepted"
    assert second["recordIds"] == [anchor_id]
    assert second["createdRecordCount"] == 0
    assert second["updatedRecordCount"] == 1
    con = mature_learning.connect(db_path)
    try:
        rows = con.execute(
            "SELECT knowledge_key, status, superseded_by_id FROM deep_research_records "
            "WHERE record_id = ?",
            (anchor_id,),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["knowledge_key"] == key
        assert rows[0]["status"] == "valid"
        assert rows[0]["superseded_by_id"] is None
    finally:
        con.close()


def test_backfill_relocates_drifted_rows_to_anchor_ids(tmp_path):
    """Backfill keeps the record_id = hash(knowledge_key) invariant: a row whose stored
    identity recomputes to a different key is relocated to the new anchor id and the old
    id is deprecated toward it."""
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = service.propose_deep_research_records(_family_deep_payload())
    old_id = first["recordIds"][0]
    con = mature_learning.connect(db_path)
    try:
        # Change the stored role components so the recomputed identity (and thus the
        # canonical anchor id) differs from the creation-time one.
        mentions = [
            {"role": "primary_damage", "component_key": "skill:OtherPrimaryPlayer"},
            {"role": "clear_skill", "component_key": "skill:ClearSkillPlayer"},
            {"role": "support_modifier", "component_key": "support:Scattershot"},
        ]
        con.execute(
            "UPDATE deep_research_records SET component_mentions = ? WHERE record_id = ?",
            (json.dumps(mentions, ensure_ascii=False), old_id),
        )
        con.commit()
    finally:
        con.close()

    result = service.backfill_deep_research_knowledge(force=True)

    assert result["status"] == "applied"
    assert result["relocatedRecordCount"] == 1
    con = mature_learning.connect(db_path)
    try:
        active = con.execute(
            "SELECT record_id, knowledge_key, status, superseded_by_id "
            "FROM deep_research_records WHERE status IN ('valid', 'needs_revalidation')"
        ).fetchall()
        assert len(active) == 1
        active_id = str(active[0]["record_id"])
        assert active_id != old_id
        assert (
            active_id
            == "drr-"
            + research_memory._stable_hash({"knowledge_key": active[0]["knowledge_key"]})[:16]
        )
        tombstone = con.execute(
            "SELECT status, superseded_by_id FROM deep_research_records WHERE record_id = ?",
            (old_id,),
        ).fetchone()
        assert tombstone is not None
        assert tombstone["status"] == "deprecated"
        assert tombstone["superseded_by_id"] == active_id
    finally:
        con.close()


def test_query_deep_record_ids_resolve_superseded_chain(tmp_path):
    """Explicit deep reads resolve deprecated husk ids to their active superseding head."""
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = service.propose_deep_research_records(_family_deep_payload())
    old_id = first["recordIds"][0]
    con = mature_learning.connect(db_path)
    try:
        head_row = dict(
            con.execute(
                "SELECT * FROM deep_research_records WHERE record_id = ?", (old_id,)
            ).fetchone()
        )
        head_key = "ku-" + "a" * 20
        head_id = "drr-" + research_memory._stable_hash({"knowledge_key": head_key})[:16]
        head_row["record_id"] = head_id
        head_row["knowledge_key"] = head_key
        columns = tuple(head_row)
        con.execute(
            f"INSERT INTO deep_research_records({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            tuple(head_row[column] for column in columns),
        )
        con.execute(
            "UPDATE deep_research_records SET status = 'deprecated', superseded_by_id = ? "
            "WHERE record_id = ?",
            (head_id, old_id),
        )
        con.commit()
    finally:
        con.close()

    recalled = service.query_research_memory("", detail_level="record", record_ids=[old_id])[
        "deepResearchRecords"
    ]

    assert len(recalled) == 1
    assert recalled[0]["recordId"] == head_id


def test_backfill_adopts_live_head_when_deprecated_husk_occupies_anchor(tmp_path):
    """Backfill v6: a deprecated husk occupying the anchor id for a key is deleted and the
    cluster adopts its live head, instead of forming a deprecated cycle that hides the unit."""
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = service.propose_deep_research_records(_family_deep_payload())
    old_id = first["recordIds"][0]

    def _clone_row(con, source_id, record_id, knowledge_key, status, superseded_by_id, **overrides):
        row = dict(
            con.execute(
                "SELECT * FROM deep_research_records WHERE record_id = ?", (source_id,)
            ).fetchone()
        )
        row["record_id"] = record_id
        row["knowledge_key"] = knowledge_key
        row["status"] = status
        row["superseded_by_id"] = superseded_by_id
        row.update(overrides)
        columns = tuple(row)
        con.execute(
            f"INSERT INTO deep_research_records({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            tuple(row[column] for column in columns),
        )

    con = mature_learning.connect(db_path)
    try:
        # Drift the stored identity so the recomputed key differs from the creation-time key.
        mentions = [
            {
                "candidate_name": "Lightning Arrow",
                "role": "primary_damage",
                "resolver_query": "Lightning Arrow",
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": "skill:OtherPrimaryPlayer",
                "resolution_status": "resolved",
            },
            {
                "candidate_name": "Clear Skill",
                "role": "clear_skill",
                "resolver_query": "Clear Skill",
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": "skill:ClearSkillPlayer",
                "resolution_status": "resolved",
            },
            {
                "candidate_name": "Scattershot",
                "role": "support_modifier",
                "resolver_query": "Scattershot",
                "expected_node_types": ["support_gem"],
                "scope": "any",
                "component_key": "support:Scattershot",
                "resolution_status": "resolved",
            },
        ]
        con.execute(
            "UPDATE deep_research_records SET component_mentions = ? WHERE record_id = ?",
            (json.dumps(mentions, ensure_ascii=False), old_id),
        )
        con.commit()
    finally:
        con.close()

    # First pass relocates the drifted row onto its new anchor id.
    service.backfill_deep_research_knowledge(force=True)
    con = mature_learning.connect(db_path)
    try:
        anchor = con.execute(
            "SELECT * FROM deep_research_records "
            "WHERE status IN ('valid', 'needs_revalidation') AND record_id != ?",
            (old_id,),
        ).fetchone()
        assert anchor is not None
        anchor_id = str(anchor["record_id"])
        anchor_key = str(anchor["knowledge_key"])
        head_id = "drr-" + research_memory._stable_hash({"knowledge_key": "ku-head-probe"})[:16]
        # Turn the anchor occupant into a deprecated husk first so its unique key slot is
        # released, then insert the live head with the same key.
        con.execute(
            "UPDATE deep_research_records SET status = 'deprecated', superseded_by_id = ? "
            "WHERE record_id = ?",
            (head_id, anchor_id),
        )
        # Lower-quality live head sharing the anchor's key.
        _clone_row(
            con,
            anchor_id,
            head_id,
            anchor_key,
            "valid",
            None,
            content="x",
            conditions="[]",
            failure_conditions="[]",
        )
        # Revive the drifted row as an active candidate with a blanked key so the recompute
        # targets the same cluster without colliding with the live head's unique key.
        con.execute(
            "UPDATE deep_research_records SET status = 'valid', superseded_by_id = NULL, "
            "knowledge_key = NULL WHERE record_id = ?",
            (old_id,),
        )
        con.commit()
    finally:
        con.close()

    result = service.backfill_deep_research_knowledge(force=True)
    assert result["status"] == "applied"
    con = mature_learning.connect(db_path)
    try:
        husk = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = ?", (anchor_id,)
        ).fetchone()
        assert husk is None, "deprecated husk occupying the anchor must be deleted"
        head = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = ?", (head_id,)
        ).fetchone()
        assert head is not None
        assert head["status"] in {"valid", "needs_revalidation"}
        assert head["superseded_by_id"] is None
        drifted = con.execute(
            "SELECT status, superseded_by_id FROM deep_research_records WHERE record_id = ?",
            (old_id,),
        ).fetchone()
        assert drifted is not None
        assert drifted["status"] == "deprecated"
        assert drifted["superseded_by_id"] == head_id
        active = con.execute(
            "SELECT record_id FROM deep_research_records "
            "WHERE knowledge_key = ? AND status IN ('valid', 'needs_revalidation') "
            "AND superseded_by_id IS NULL",
            (anchor_key,),
        ).fetchall()
        assert len(active) == 1
        assert str(active[0]["record_id"]) == head_id
    finally:
        con.close()


def test_backfill_replaces_quarantined_anchor_occupant(tmp_path):
    """Backfill v6: a quarantined row occupying the anchor id is dropped and the drifted
    canonical row is relocated onto the anchor (mirrors the write-path handling)."""
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first = service.propose_deep_research_records(_family_deep_payload())
    old_id = first["recordIds"][0]

    con = mature_learning.connect(db_path)
    try:
        mentions = [
            {
                "candidate_name": "Lightning Arrow",
                "role": "primary_damage",
                "resolver_query": "Lightning Arrow",
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": "skill:OtherPrimaryPlayer",
                "resolution_status": "resolved",
            },
            {
                "candidate_name": "Clear Skill",
                "role": "clear_skill",
                "resolver_query": "Clear Skill",
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": "skill:ClearSkillPlayer",
                "resolution_status": "resolved",
            },
            {
                "candidate_name": "Scattershot",
                "role": "support_modifier",
                "resolver_query": "Scattershot",
                "expected_node_types": ["support_gem"],
                "scope": "any",
                "component_key": "support:Scattershot",
                "resolution_status": "resolved",
            },
        ]
        con.execute(
            "UPDATE deep_research_records SET component_mentions = ? WHERE record_id = ?",
            (json.dumps(mentions, ensure_ascii=False), old_id),
        )
        con.commit()
    finally:
        con.close()

    service.backfill_deep_research_knowledge(force=True)
    con = mature_learning.connect(db_path)
    try:
        anchor = con.execute(
            "SELECT * FROM deep_research_records "
            "WHERE status IN ('valid', 'needs_revalidation') AND record_id != ?",
            (old_id,),
        ).fetchone()
        assert anchor is not None
        anchor_id = str(anchor["record_id"])
        anchor_key = str(anchor["knowledge_key"])
        # Quarantine the anchor occupant and revive the drifted row (key blanked).
        con.execute(
            "UPDATE deep_research_records SET status = 'quarantined' WHERE record_id = ?",
            (anchor_id,),
        )
        con.execute(
            "UPDATE deep_research_records SET status = 'valid', superseded_by_id = NULL, "
            "knowledge_key = NULL WHERE record_id = ?",
            (old_id,),
        )
        con.commit()
    finally:
        con.close()

    result = service.backfill_deep_research_knowledge(force=True)
    assert result["status"] == "applied"
    con = mature_learning.connect(db_path)
    try:
        occupant = con.execute(
            "SELECT status, superseded_by_id FROM deep_research_records WHERE record_id = ?",
            (anchor_id,),
        ).fetchone()
        assert occupant is not None
        assert occupant["status"] != "quarantined", (
            "quarantined anchor occupant must be dropped and rebuilt"
        )
        assert occupant["status"] in {"valid", "needs_revalidation"}
        assert occupant["superseded_by_id"] is None
        active = con.execute(
            "SELECT record_id FROM deep_research_records "
            "WHERE knowledge_key = ? AND status IN ('valid', 'needs_revalidation') "
            "AND superseded_by_id IS NULL",
            (anchor_key,),
        ).fetchall()
        assert len(active) == 1
        assert str(active[0]["record_id"]) == anchor_id
    finally:
        con.close()
