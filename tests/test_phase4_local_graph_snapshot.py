from __future__ import annotations

import json

from scripts import build_local_physical_graph_snapshot as local_snapshot
from server.knowledge import copy_safety
from server.knowledge import physical_graph as pg


RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
    "transientPacketPath",
    "transientPromptPath",
    "pobb.in/",
    "poe.ninja/",
)


def test_local_graph_snapshot_installer_builds_registers_and_reports_safe_fixture(tmp_path):
    raw_dir = tmp_path / "raw"
    (raw_dir / "official").mkdir(parents=True)
    pob_root = tmp_path / "pob"
    tree_dir = pob_root / "TreeData" / "0_5"
    unique_dir = pob_root / "Data" / "Uniques"
    tree_dir.mkdir(parents=True)
    unique_dir.mkdir(parents=True)
    (raw_dir / "wiki").mkdir()
    _write_json(
        raw_dir / "skill_gems.min.json",
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
        },
    )
    _write_json(
        raw_dir / "skills.min.json",
        {
            "LightningArrowPlayer": {
                "display_name": "Lightning Arrow",
                "skill_types": ["Attack", "Projectile"],
                "weapon_restrictions": ["Bow"],
            }
        },
    )
    _write_json(
        raw_dir / "base_items.min.json",
        {
            "Metadata/Items/Weapons/Bows/Bow1": {
                "name": "Shortbow",
                "item_class": "Bow",
                "domain": "item",
                "drop_level": 1,
                "tags": ["bow", "weapon", "default"],
                "requirements": {"level": 1, "dexterity": 0},
            }
        },
    )
    _write_json(
        raw_dir / "mods.min.json",
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
        },
    )
    _write_json(
        raw_dir / "official" / "inventories.min.json",
        {"Weapon1": {"inventory_id": "Weapon1", "display_name": "Weapon 1"}},
    )
    _write_json(
        tree_dir / "tree.json",
        {
            "classes": [
                {
                    "name": "Ranger",
                    "integerId": 2,
                    "ascendancies": [{"name": "Deadeye", "id": "Deadeye", "internalId": "Deadeye"}],
                }
            ],
            "nodes": {
                "1": {
                    "name": "Ranger Start",
                    "skill": 1,
                    "classesStart": ["Ranger"],
                    "out": [2],
                    "stats": ["+5 to Dexterity"],
                },
                "2": {
                    "name": "Projectile Focus",
                    "skill": 2,
                    "isNotable": True,
                    "out": [1, 3],
                    "stats": ["10% increased Projectile Damage"],
                },
                "3": {
                    "name": "Resonance",
                    "skill": 3,
                    "isKeystone": True,
                    "out": [2],
                    "stats": ["Gain Power Charges instead of Frenzy Charges"],
                },
                "4": {
                    "name": "Deadeye Start",
                    "skill": 4,
                    "ascendancyName": "Deadeye",
                    "stats": ["Ascendancy passive"],
                },
            },
        },
    )
    (unique_dir / "amulet.lua").write_text(
        "return [[\nThe Anvil\nShortbow\nVariant: Pre 0.1.0\nAdds 1 to 2 Lightning Damage\n]]\n",
        encoding="utf-8",
    )
    _write_json(raw_dir / "ascendancies.min.json", {"Deadeye": {"name": "Deadeye"}})
    _write_json(raw_dir / "wiki" / "skill.json", {"title": "Do not ingest wiki"})
    _write_json(
        raw_dir / "passive_tree.min.json",
        {"nodes": {"123": {"name": "Do Not Ingest Passive"}}},
    )
    _write_json(
        raw_dir / "mature_sample_report.json",
        {
            "safeMetadata": {
                "mainSkill": "Do Not Create Skill",
                "ascendancy": "Do Not Create Ascendancy",
            }
        },
    )

    report = local_snapshot.build_local_snapshot_report(
        raw_data_dir=raw_dir,
        pob_src_dir=pob_root,
        output_dir=tmp_path / "physical_graph",
    )

    assert report["status"] == "installed"
    assert report["safeArtifactOnly"] is True
    assert report["snapshot"]["nodeCount"] > 0
    assert report["snapshot"]["edgeCount"] > 0
    assert report["snapshot"]["sourceCount"] == 7
    assert report["coverageGate"]["readyForMaturePatternBootstrap"] is True
    for required_type in (
        "active_skill",
        "support_gem",
        "passive",
        "notable",
        "keystone",
        "ascendancy",
        "unique",
        "item_base",
        "mod",
    ):
        assert report["nodeTypeCounts"][required_type] > 0
    assert report["snapshot"]["resourceFactCount"] >= 0
    assert report["registeredSnapshot"]["isLatest"] is True
    assert "data/raw/wiki" in report["excludedSources"]
    assert "mature_sample_metadata" in report["excludedSources"]

    snapshot = pg.load_latest_snapshot(tmp_path / "physical_graph" / "snapshot_index.sqlite")
    allowed_source_ids = {
        "repoe:skill_gems",
        "repoe:skills",
        "repoe:base_items",
        "repoe:mods",
        "ggg:developer_docs:inventories",
        "pob:passive_tree:0_5",
        "pob:uniques",
    }
    assert {source.source_id for source in snapshot.sources} == allowed_source_ids
    assert {source["sourceId"] for source in report["sourceInventory"]} == allowed_source_ids
    assert all(set(node.source_refs) <= allowed_source_ids for node in snapshot.nodes)
    assert all(set(edge.evidence_refs) <= allowed_source_ids for edge in snapshot.edges)
    node_keys = {node.stable_key for node in snapshot.nodes}
    assert "skill:LightningArrowPlayer" in node_keys
    assert any(key.startswith("ascendancy:ranger:deadeye") for key in node_keys)
    assert any(key.startswith("notable:") for key in node_keys)
    assert any(key.startswith("keystone:") for key in node_keys)
    assert "unique:pob:the_anvil" in node_keys
    assert not any("wiki" in key.lower() for key in node_keys)
    assert not any("Do Not Create" in node.display_name for node in snapshot.nodes)

    serialized = json.dumps(report, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)
    flags = set(copy_safety.copyability_flags(report))
    flags.discard("full_gem_link_like")
    assert flags == set()


def test_local_graph_snapshot_installer_writes_safe_json_and_markdown(tmp_path):
    raw_dir = tmp_path / "raw"
    (raw_dir / "official").mkdir(parents=True)
    _write_json(raw_dir / "skill_gems.min.json", {})
    _write_json(raw_dir / "skills.min.json", {})
    _write_json(raw_dir / "base_items.min.json", {})
    _write_json(raw_dir / "mods.min.json", {})
    _write_json(raw_dir / "official" / "inventories.min.json", {})

    output_json = tmp_path / "snapshot-report.json"
    output_md = tmp_path / "snapshot-report.md"
    report = local_snapshot.write_local_snapshot_report(
        raw_data_dir=raw_dir,
        pob_src_dir=tmp_path / "missing-pob",
        output_dir=tmp_path / "physical_graph",
        json_output=output_json,
        md_output=output_md,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    assert report["status"] == "source_coverage_gap"
    assert report["coverageGate"]["readyForMaturePatternBootstrap"] is False
    assert report["registeredSnapshot"] is None
    assert report["coverageGate"]["endpointAssessment"]["classification"] == "source_coverage_gap"
    assert report["coverageGate"]["endpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert report["coverageGate"]["endpointAssessment"]["requiresStaticSourceReview"] is True
    assert not (tmp_path / "physical_graph" / "snapshot_index.sqlite").exists()
    markdown = output_md.read_text(encoding="utf-8")
    assert "Phase 4 Local Physical Graph Snapshot" in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_local_snapshot_collects_pinned_support_flags_with_payload_types(tmp_path):
    skill_dir = tmp_path / "Data" / "Skills"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "fixture.lua"
    text = '''skills["SummonFixture"] = {
    minionSkillTypes = { [SkillType.Spell] = true, },
}
skills["SupportFixture"] = {
    support = true,
    ignoreMinionTypes = true,
}
'''
    skill_path.write_text(text, encoding="utf-8")
    ingestions, reports, _ = local_snapshot._pob_static_ingestions(
        pob_root=tmp_path, base_ingestion=pg.GraphIngestionResult(),
        known_skill_keys={"skill:SummonFixture", "skill:SupportFixture"},
    )
    facts = {(fact.component_key, fact.level_or_stage): fact
             for ingestion in ingestions for fact in ingestion.requirement_facts}
    assert facts[("skill:SummonFixture", "minion_payload_types")].requirements["skill_types"] == ["Spell"]
    flags = facts[("skill:SupportFixture", "pob_support_flags")]
    assert flags.requirements == {"ignore_minion_types": True}
    source = next(source for source, _, _ in reports
                  if source.source_id == local_snapshot.POB_SKILL_PAYLOAD_TYPES_SOURCE_ID)
    assert source.schema_version == "pob_generated_skill_lua_v2"
    assert flags.source_refs == (source.source_id,)

    skill_path.write_text(text.replace("ignoreMinionTypes = true,", "ignoreMinionTypes = false,"), encoding="utf-8")
    _, changed_reports, _ = local_snapshot._pob_static_ingestions(
        pob_root=tmp_path, base_ingestion=pg.GraphIngestionResult(),
        known_skill_keys={"skill:SummonFixture", "skill:SupportFixture"},
    )
    changed = next(item for item, _, _ in changed_reports if item.source_id == source.source_id)
    assert source.claim("content_sha256") != changed.claim("content_sha256")
