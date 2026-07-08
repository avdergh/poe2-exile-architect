from __future__ import annotations

from datetime import UTC, datetime
import json

from scripts import run_phase4_secondary_endpoint_resolution as secondary
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


def test_secondary_endpoint_resolution_resolves_entities_and_keeps_abstract_tags_safe(tmp_path):
    extraction_path = tmp_path / "extraction.json"
    extraction_path.write_text(
        json.dumps(_real_extraction_report(), ensure_ascii=False),
        encoding="utf-8",
    )

    report = secondary.build_secondary_endpoint_resolution_report(
        input_report=extraction_path,
        graph_snapshot_index=_write_snapshot_index(tmp_path),
    )

    assert report["status"] == "secondary_endpoint_resolution_completed"
    assert report["safeArtifactOnly"] is True
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["metrics"]["notGraphEntityCount"] == 6
    assert report["metrics"]["resolvedCount"] == 1
    assert report["metrics"]["ambiguousCount"] >= 1
    assert report["metrics"]["missingCount"] == 1

    by_key = {
        (item["sampleId"], item["candidateName"]): item for item in report["secondaryEndpoints"]
    }
    herald = by_key[("phase4_user_pob_001", "Herald of Thunder")]
    assert herald["resolverStatus"] == "ambiguous"
    assert herald["stableKey"] is None
    assert herald["semanticEdgeAction"] == "requires_manual_endpoint_mapping"
    assert herald["endpointAssessment"]["classification"] == "ambiguous_endpoint"
    assert herald["endpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert herald["endpointAssessment"]["requiresStaticSourceReview"] is True

    cooldown = by_key[("phase4_user_pob_001", "Cooldown Recovery II")]
    assert cooldown["resolverStatus"] == "missing"
    assert cooldown["endpointAssessment"]["classification"] == "source_coverage_gap"
    assert cooldown["endpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert cooldown["endpointAssessment"]["requiresStaticSourceReview"] is True

    shock = by_key[("phase4_user_pob_001", "Shock")]
    assert shock["resolverStatus"] == "not_graph_entity"
    assert shock["stableKey"] is None
    assert shock["semanticEdgeAction"] == "verification_caveat_only"

    resolved = by_key[("phase4_user_pob_001", "Combat Frenzy")]
    assert resolved["resolverStatus"] == "resolved"
    assert resolved["stableKey"] == "skill:CombatFrenzyPlayer"
    assert resolved["semanticEdgeAction"] == "ready_for_external_semantic_edge"

    abstract = by_key[("phase4_user_pob_001", "elemental_ailment_layer")]
    assert abstract["resolverStatus"] == "not_graph_entity"
    assert abstract["stableKey"] is None
    assert abstract["semanticEdgeAction"] == "verification_caveat_only"

    crossbow = [
        item for item in report["secondaryEndpoints"] if item["sampleId"] == "phase4_user_pob_003"
    ]
    assert crossbow
    assert all(item["sampleEndpointStatus"] == "pending_manual_review" for item in crossbow)
    assert all(
        item["semanticEdgeAction"] != "ready_for_external_semantic_edge" for item in crossbow
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_secondary_endpoint_resolution_reports_unknown_mechanic_tags_as_not_graph_entities(
    tmp_path,
):
    extraction = _real_extraction_report()
    extraction["samples"][0]["observedSafeSignals"]["mechanicTags"].append("new_abstract_layer")
    extraction_path = tmp_path / "extraction.json"
    extraction_path.write_text(json.dumps(extraction, ensure_ascii=False), encoding="utf-8")

    report = secondary.build_secondary_endpoint_resolution_report(
        input_report=extraction_path,
        graph_snapshot_index=_write_snapshot_index(tmp_path),
    )

    unknown = [
        item
        for item in report["secondaryEndpoints"]
        if item["candidateName"] == "new_abstract_layer"
    ]
    assert unknown
    assert unknown[0]["resolverStatus"] == "not_graph_entity"


def test_secondary_endpoint_resolution_writes_safe_json_and_markdown(tmp_path):
    extraction_path = tmp_path / "extraction.json"
    extraction_path.write_text(
        json.dumps(_real_extraction_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    output_json = tmp_path / "secondary.json"
    output_md = tmp_path / "secondary.md"

    report = secondary.write_secondary_endpoint_resolution_report(
        input_report=extraction_path,
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        json_output=output_json,
        md_output=output_md,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    markdown = output_md.read_text(encoding="utf-8")
    assert "Phase 4 Secondary Endpoint Resolution" in markdown
    assert "Herald of Thunder" in markdown
    assert "Crossbow Shot" not in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)


def _write_snapshot_index(tmp_path):
    source = pg.GraphSource(
        source_id="repoe:skills",
        kind="repoe_raw",
        source_file="skills.min.json",
        expected_count=8,
    )
    nodes = (
        pg.GraphNode(
            stable_key="skill:HollowFocusPlayer",
            node_type="active_skill",
            display_name="Hollow Focus",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="skill:HeraldOfThunderPlayer",
            node_type="active_skill",
            display_name="Herald of Thunder",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="gem:Metadata/Items/Gems/SkillGemHeraldOfThunder",
            node_type="skill_gem",
            display_name="Herald of Thunder",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="skill:BarragePlayer",
            node_type="active_skill",
            display_name="Barrage",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="skill:BarrageRogueExile",
            node_type="active_skill",
            display_name="Barrage",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="skill:VividStampedePlayer",
            node_type="active_skill",
            display_name="Vivid Stampede",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="skill:CombatFrenzyPlayer",
            node_type="active_skill",
            display_name="Combat Frenzy",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="mechanic:Shock",
            node_type="mechanic",
            display_name="Shock",
            source_refs=(source.source_id,),
        ),
    )
    aliases = tuple(
        pg.GraphAlias(node.display_name, node.stable_key, (source.source_id,)) for node in nodes
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="physical-graph-secondary-fixture",
        created_at=datetime(2026, 7, 4, tzinfo=UTC),
        sources=(source,),
        nodes=nodes,
        edges=(),
        aliases=aliases,
    )
    snapshot_path = tmp_path / "snapshot.json"
    index_path = tmp_path / "snapshot_index.sqlite"
    pg.save_snapshot(snapshot, snapshot_path)
    pg.register_snapshot(index_path, snapshot, snapshot_path)
    return index_path


def _real_extraction_report():
    return {
        "reportId": "phase4_real_research_extraction_v1",
        "status": "real_research_extraction_completed",
        "safeArtifactOnly": True,
        "samples": [
            {
                "sampleId": "phase4_user_pob_001",
                "mainSkill": "Hollow Focus",
                "acceptedStableKey": "skill:HollowFocusPlayer",
                "observedSafeSignals": {
                    "mechanicTags": ["elemental_ailment_layer", "companion_layer"],
                    "primarySkillPreview": ["Hollow Focus", "Barrage", "Herald of Thunder"],
                },
                "extractedFragments": [
                    {
                        "verificationTasksZh": [
                            "解析 Herald of Thunder、Cooldown Recovery II 与 Combat Frenzy。"
                        ],
                        "conditionsZh": [
                            "包含 Herald 清图层，以及 Shock、Freeze、Overcharge 机制线索。"
                        ],
                    }
                ],
            },
            {
                "sampleId": "phase4_user_pob_003",
                "mainSkill": "Crossbow Shot",
                "acceptedStableKey": None,
                "observedSafeSignals": {
                    "mechanicTags": ["ammo_rotation"],
                    "primarySkillPreview": ["Crossbow Shot", "Herald of Thunder"],
                },
                "extractedFragments": [
                    {
                        "verificationTasksZh": ["先完成 Crossbow Shot endpoint mapping。"],
                        "conditionsZh": ["Crossbow Shot endpoint pending manual review。"],
                    }
                ],
            },
        ],
    }
