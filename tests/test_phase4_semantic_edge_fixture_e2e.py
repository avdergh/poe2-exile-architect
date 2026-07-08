from __future__ import annotations

import json

from scripts import run_phase4_semantic_edge_fixture_e2e as fixture_e2e


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
)


def test_semantic_edge_fixture_e2e_accepts_resolver_backed_edge(tmp_path):
    report = fixture_e2e.build_fixture_semantic_edge_report(
        db_path=tmp_path / "mature.sqlite",
        work_dir=tmp_path / "graph",
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["status"] == "pass"
    assert report["safeArtifactOnly"] is True
    assert report["edgeSubmission"]["status"] == "accepted"
    assert report["edgeSubmission"]["plannerVisible"] is True
    assert report["metrics"]["resolverBackedEdgesAccepted"] == 1
    assert report["metrics"]["fabricatedResolverEvidenceRejected"] is True
    assert report["metrics"]["missingEndpointNotHallucinated"] is True
    assert {item["status"] for item in report["resolverResults"]} == {"resolved"}
    assert report["forgedEvidenceCheck"]["errorCode"] == "endpoint_resolution_mismatch"
    assert report["missingEndpointCheck"]["errorCode"] == "missing_endpoint"
    assert (
        report["missingEndpointCheck"]["endpointAssessment"]["classification"]
        == "source_coverage_gap"
    )
    assert (
        report["missingEndpointCheck"]["endpointAssessment"]["hallucinationVerdict"]
        == "not_assessed"
    )
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_semantic_edge_fixture_e2e_writes_safe_json_and_markdown(tmp_path):
    output_json = tmp_path / "semantic-edge.json"
    output_md = tmp_path / "semantic-edge.md"

    report = fixture_e2e.write_fixture_semantic_edge_report(
        db_path=tmp_path / "mature.sqlite",
        work_dir=tmp_path / "graph",
        json_output=output_json,
        md_output=output_md,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    markdown = output_md.read_text(encoding="utf-8")
    assert "phase4-semantic-edge-fixture-e2e-v1" in markdown
    assert "accepted" in markdown
    assert "source_coverage_gap" in markdown
    assert "not_assessed" in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)
