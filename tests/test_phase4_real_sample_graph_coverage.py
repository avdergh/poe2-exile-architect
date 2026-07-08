from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from scripts import run_phase4_real_sample_graph_coverage as coverage
from server.knowledge import mature_learning
from server.knowledge import physical_graph as pg
from server.knowledge import research_memory


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


def test_real_sample_graph_coverage_classifies_resolved_ambiguous_and_missing_without_edge_write(
    tmp_path,
    monkeypatch,
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    input_report.write_text(
        json.dumps(
            _safe_packet_report(
                [
                    _sample("phase4_user_pob_001", "Lightning Arrow", "a" * 64, "b" * 64),
                    _sample("phase4_user_pob_002", "Spark", "c" * 64, "d" * 64),
                    _sample("phase4_user_pob_003", "Hollow Focus", "e" * 64, "f" * 64),
                ]
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    index_path = _write_snapshot_index(tmp_path)
    db_path = tmp_path / "mature.sqlite"

    report = coverage.build_real_sample_graph_coverage_report(
        input_report=input_report,
        graph_snapshot_index=index_path,
        db_path=db_path,
    )

    assert report["status"] == "coverage_probe_completed"
    assert report["safeArtifactOnly"] is True
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["semanticEdgeWrite"]["reason"] == "external_researcher_proposal_required"

    probes = {probe["sampleId"]: probe for probe in report["probes"]}
    assert probes["phase4_user_pob_001"]["resolverStatus"] == "resolved"
    assert probes["phase4_user_pob_001"]["stableKey"] == "skill:LightningArrowPlayer"
    assert (
        probes["phase4_user_pob_001"]["semanticEdgeAction"]
        == "ready_for_researcher_semantic_review"
    )
    assert probes["phase4_user_pob_002"]["resolverStatus"] == "ambiguous"
    assert probes["phase4_user_pob_002"]["candidateCount"] == 2
    assert probes["phase4_user_pob_002"]["semanticEdgeAction"] == "requires_manual_endpoint_mapping"
    assert probes["phase4_user_pob_003"]["resolverStatus"] == "missing"
    assert (
        probes["phase4_user_pob_003"]["endpointAssessment"]["classification"]
        == "source_coverage_gap"
    )
    assert (
        probes["phase4_user_pob_003"]["endpointAssessment"]["hallucinationVerdict"]
        == "not_assessed"
    )
    assert probes["phase4_user_pob_003"]["requiresStaticSourceReview"] is True
    assert probes["phase4_user_pob_003"]["semanticEdgeAction"] == "deferred_source_coverage_gap"

    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT COUNT(*) FROM research_semantic_edges").fetchone()[0] == 0
    finally:
        con.close()

    serialized = json.dumps(report, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_real_sample_graph_coverage_reports_graph_unavailable_without_hallucination(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    input_report.write_text(
        json.dumps(
            _safe_packet_report([_sample("phase4_user_pob_001", "Lightning Arrow")]),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = coverage.build_real_sample_graph_coverage_report(
        input_report=input_report,
        graph_snapshot_index=tmp_path / "missing.sqlite",
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["status"] == "graph_snapshot_unavailable"
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["probes"][0]["resolverStatus"] == "graph_unavailable"
    assert (
        report["probes"][0]["endpointAssessment"]["classification"] == "graph_snapshot_unavailable"
    )
    assert report["probes"][0]["endpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert report["probes"][0]["semanticEdgeAction"] == "deferred_source_coverage_gap"


def test_real_sample_graph_coverage_never_proposes_edges_when_graph_unavailable(
    tmp_path, monkeypatch
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    input_report.write_text(
        json.dumps(
            _safe_packet_report([_sample("phase4_user_pob_001", "Lightning Arrow")]),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = coverage.build_real_sample_graph_coverage_report(
        input_report=input_report,
        graph_snapshot_index=tmp_path / "missing.sqlite",
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["metrics"]["semanticEdgeWritesAttempted"] == 0


def test_real_sample_graph_coverage_rejects_plain_url_metadata(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    sample = _sample("phase4_user_pob_001", "https://example.com/build")
    input_report.write_text(
        json.dumps(_safe_packet_report([sample]), ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="copy-safety|failed"):
        coverage.build_real_sample_graph_coverage_report(
            input_report=input_report,
            graph_snapshot_index=tmp_path / "missing.sqlite",
            db_path=tmp_path / "mature.sqlite",
        )


def test_real_sample_graph_coverage_writes_safe_json_and_markdown(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    input_report.write_text(
        json.dumps(
            _safe_packet_report([_sample("phase4_user_pob_001", "Lightning Arrow")]),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_json = tmp_path / "coverage.json"
    output_md = tmp_path / "coverage.md"

    report = coverage.write_real_sample_graph_coverage_report(
        input_report=input_report,
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        db_path=tmp_path / "mature.sqlite",
        json_output=output_json,
        md_output=output_md,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    markdown = output_md.read_text(encoding="utf-8")
    assert "Phase 4 Real Sample Graph Coverage" in markdown
    assert "ready_for_researcher_semantic_review" in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)


def _write_snapshot_index(tmp_path):
    source = pg.GraphSource(
        source_id="repoe:skill_gems",
        kind="repoe_raw",
        source_file="skill_gems.min.json",
        expected_count=3,
    )
    nodes = (
        pg.GraphNode(
            stable_key="skill:LightningArrowPlayer",
            node_type="active_skill",
            display_name="Lightning Arrow",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="skill:SparkPlayer",
            node_type="active_skill",
            display_name="Spark",
            source_refs=(source.source_id,),
        ),
        pg.GraphNode(
            stable_key="gem:Metadata/Items/Gems/SkillGemSpark",
            node_type="skill_gem",
            display_name="Spark",
            source_refs=(source.source_id,),
        ),
    )
    aliases = (
        pg.GraphAlias("Lightning Arrow", "skill:LightningArrowPlayer", (source.source_id,)),
        pg.GraphAlias("Spark", "skill:SparkPlayer", (source.source_id,)),
        pg.GraphAlias("Spark", "gem:Metadata/Items/Gems/SkillGemSpark", (source.source_id,)),
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="physical-graph-real-sample-coverage-fixture",
        created_at=datetime(2026, 7, 3, tzinfo=UTC),
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


def _safe_packet_report(samples):
    return {
        "reportId": "phase4-researcher-e2e-user-pob-v1",
        "status": "ready_for_external_researcher",
        "safeArtifactOnly": True,
        "sampleCount": len(samples),
        "readyCount": len(samples),
        "samples": samples,
    }


def _sample(sample_id, main_skill, source_hash=None, packet_hash=None):
    source_hash = source_hash or "a" * 64
    packet_hash = packet_hash or "b" * 64
    return {
        "sampleId": sample_id,
        "status": "packet_ready",
        "sourceHash": source_hash,
        "packetSafeHash": packet_hash,
        "safeMetadata": {
            "case_id": sample_id,
            "class": "Ranger",
            "ascendancy": "Deadeye",
            "mainSkill": main_skill,
            "gamePatch": "0.5.4",
            "passiveTreeVersion": "0_5",
            "pobModelability": "partial",
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledgeScope": "global_seed",
        },
        "noRawMatureBuildMaterial": True,
    }


def _fail_if_semantic_edges_are_proposed(monkeypatch):
    def fail(self, payload):  # noqa: ARG001
        raise AssertionError("coverage probe must not call propose_semantic_edges")

    monkeypatch.setattr(research_memory.ResearchMemoryService, "propose_semantic_edges", fail)
