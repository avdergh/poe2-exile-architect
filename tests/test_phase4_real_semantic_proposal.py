from __future__ import annotations

from datetime import UTC, datetime
import json

from scripts import build_phase4_real_semantic_proposal as proposal_builder
from server.knowledge import physical_graph as pg
from server.knowledge import research_models


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


def test_real_semantic_proposal_builds_resolver_backed_advisory_edges(tmp_path):
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request_report(), ensure_ascii=False), encoding="utf-8")

    report = proposal_builder.build_real_semantic_proposal(
        request_report=request_path,
        graph_snapshot_index=_write_snapshot_index(tmp_path),
    )

    assert report["schema_version"] == 4
    assert report["fragments"] == []
    assert len(report["semantic_edges"]) == 2
    validation = research_models.validate_researcher_output(report)
    assert validation["status"] == "accepted"
    for edge in report["semantic_edges"]:
        assert edge["source_resolution"]["stable_key"] == edge["source_key"]
        assert edge["target_resolution"]["stable_key"] == edge["target_key"]
        assert edge["copy_safety_state"] == "passed"
        assert edge["context_requirements"]
        assert edge["directionality"] == "directional"
        assert edge["edge_type"] == "has_modelability_caveat"

    serialized = json.dumps(report, ensure_ascii=False)
    assert "Crossbow" not in serialized
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_real_semantic_proposal_writes_safe_artifact(tmp_path):
    request_path = tmp_path / "request.json"
    output_json = tmp_path / "proposal.json"
    request_path.write_text(json.dumps(_request_report(), ensure_ascii=False), encoding="utf-8")

    report = proposal_builder.write_real_semantic_proposal(
        request_report=request_path,
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        json_output=output_json,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    assert not any(marker in output_json.read_text(encoding="utf-8") for marker in RAW_MARKERS)


def _request_report():
    return {
        "reportId": "phase4-semantic-proposal-request-v1",
        "status": "ready_for_external_researcher_semantic_proposal",
        "safeArtifactOnly": True,
        "acceptedEndpoints": [
            {
                "sampleId": "phase4_user_pob_001",
                "candidateName": "Hollow Focus",
                "acceptedStableKey": "skill:HollowFocusPlayer",
            },
            {
                "sampleId": "phase4_user_pob_004",
                "candidateName": "Vivid Stampede",
                "acceptedStableKey": "skill:VividStampedePlayer",
            },
        ],
        "resolvedSecondaryEndpoints": [
            {
                "sampleId": "phase4_user_pob_001",
                "candidateName": "Cooldown Recovery II",
                "stableKey": "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
                "nodeType": "support_gem",
            },
            {
                "sampleId": "phase4_user_pob_004",
                "candidateName": "Herald of Thunder",
                "stableKey": "skill:HeraldOfThunderPlayer",
                "nodeType": "active_skill",
            },
        ],
    }


def _write_snapshot_index(tmp_path):
    source = pg.GraphSource(
        source_id="repoe:skills",
        kind="repoe_raw",
        source_file="skills.min.json",
        expected_count=4,
    )
    nodes = (
        pg.GraphNode(
            stable_key="skill:HollowFocusPlayer",
            node_type="active_skill",
            display_name="Hollow Focus",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="support:Metadata/Items/Gems/SupportGemIngenuityTwo",
            node_type="support_gem",
            display_name="Cooldown Recovery II",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="skill:VividStampedePlayer",
            node_type="active_skill",
            display_name="Vivid Stampede",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="skill:HeraldOfThunderPlayer",
            node_type="active_skill",
            display_name="Herald of Thunder",
            source_refs=(source.source_id,),
        ),
    )
    aliases = tuple(
        pg.GraphAlias(node.stable_key, node.stable_key, (source.source_id,)) for node in nodes
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="physical-graph-real-semantic-proposal-fixture",
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
