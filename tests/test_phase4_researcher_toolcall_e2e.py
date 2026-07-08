from __future__ import annotations

import json

from scripts import run_phase4_researcher_toolcall_e2e

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


def _safe_packet_report() -> dict[str, object]:
    return {
        "reportId": "phase4-researcher-e2e-user-pob-v1",
        "status": "ready_for_external_researcher",
        "sampleCount": 2,
        "readyCount": 2,
        "safeArtifactOnly": True,
        "samples": [
            {
                "sampleId": "phase4_user_pob_001",
                "status": "packet_ready",
                "sourceHash": "a" * 64,
                "packetId": "rp-safe-001",
                "packetSafeHash": "b" * 64,
                "transientPacketPath": "C:/tmp/raw-packet/packet.json",
                "transientPromptPath": "C:/tmp/raw-packet/researcher_prompt.txt",
                "safeMetadata": {
                    "case_id": "phase4_user_pob_001",
                    "class": "Ranger",
                    "ascendancy": "Deadeye",
                    "mainSkill": "Lightning Arrow",
                    "gamePatch": "0.5.4",
                    "passiveTreeVersion": "0_5",
                    "visibility": "creator_visible",
                    "split": "train_context",
                    "knowledgeScope": "global_seed",
                    "pobModelability": "partial",
                    "lifecycleStage": "unknown_lifecycle",
                },
            },
            {
                "sampleId": "phase4_user_pob_002",
                "status": "packet_ready",
                "sourceHash": "c" * 64,
                "packetId": "rp-safe-002",
                "packetSafeHash": "d" * 64,
                "safeMetadata": {
                    "case_id": "phase4_user_pob_002",
                    "class": "Mercenary",
                    "ascendancy": "Tactician",
                    "mainSkill": "Crossbow Shot",
                    "gamePatch": "0.5.4",
                    "passiveTreeVersion": "0_5",
                    "visibility": "creator_visible",
                    "split": "train_context",
                    "knowledgeScope": "global_seed",
                    "pobModelability": "partial",
                    "lifecycleStage": "unknown_lifecycle",
                },
            },
        ],
    }


def test_toolcall_e2e_accepts_fragments_rejects_duplicates_and_blocks_edges(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    input_report.write_text(json.dumps(_safe_packet_report()), encoding="utf-8")

    report = run_phase4_researcher_toolcall_e2e.build_toolcall_acceptance_report(
        input_report=input_report,
        db_path=tmp_path / "mature.sqlite",
        graph_snapshot_index_path=tmp_path / "missing-snapshot-index.sqlite",
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["safeArtifactOnly"] is True
    assert report["status"] == "fragment_only_toolcall_acceptance_completed"
    assert report["acceptedFragmentCount"] == 2
    assert report["duplicateRejectionCount"] == 2
    assert report["appendedEvidenceCount"] == 2
    assert report["semanticEdgeStatus"] == "blocked_graph_snapshot"
    assert report["semanticEndpointAssessment"]["classification"] == "graph_snapshot_unavailable"
    assert report["semanticEndpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert report["semanticEndpointAssessment"]["safeMetadataCandidateNames"] == [
        "Crossbow Shot",
        "Lightning Arrow",
    ]
    assert (
        report["semanticEndpointAssessment"]["candidateNameProvenance"]
        == "safe_metadata_unresolved_label"
    )
    assert "candidateEndpointNames" not in report["semanticEndpointAssessment"]
    assert report["samples"][0]["queryStatus"] == "known"
    assert report["samples"][0]["initialProposalStatus"] == "accepted"
    assert report["samples"][0]["duplicateErrorCode"] == "duplicate_fragment_candidate"
    assert report["samples"][0]["appendEvidenceStatus"] == "accepted"
    assert report["samples"][0]["evidenceCountAfterAppend"] == 2
    assert "dedupeQueryRef" in report["samples"][0]
    assert "fragmentId" in report["samples"][0]
    assert "transientPacketPath" not in serialized
    assert "transientPromptPath" not in serialized
    assert "eNrt" not in serialized
    assert "rawXml" not in serialized
    assert "rawImportCode" not in serialized
    assert "PathOfBuilding" not in serialized


def test_toolcall_e2e_writes_safe_json_and_markdown_reports(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    output_json = tmp_path / "toolcall.json"
    output_md = tmp_path / "toolcall.md"
    input_report.write_text(json.dumps(_safe_packet_report()), encoding="utf-8")

    report = run_phase4_researcher_toolcall_e2e.write_toolcall_acceptance_report(
        input_report=input_report,
        db_path=tmp_path / "mature.sqlite",
        graph_snapshot_index_path=tmp_path / "missing-snapshot-index.sqlite",
        json_output=output_json,
        md_output=output_md,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    markdown = output_md.read_text(encoding="utf-8")
    assert "fragment_only_toolcall_acceptance_completed" in markdown
    assert "blocked_graph_snapshot" in markdown
    assert "not_assessed" in markdown
    assert "safe_metadata_unresolved_label" in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)


def test_toolcall_e2e_rejects_non_safe_input_report(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    poisoned = _safe_packet_report()
    poisoned["safeArtifactOnly"] = False
    input_report.write_text(json.dumps(poisoned), encoding="utf-8")

    try:
        run_phase4_researcher_toolcall_e2e.build_toolcall_acceptance_report(
            input_report=input_report,
            db_path=tmp_path / "mature.sqlite",
            graph_snapshot_index_path=tmp_path / "missing-snapshot-index.sqlite",
        )
    except ValueError as exc:
        assert "safe-only" in str(exc)
    else:
        raise AssertionError("unsafe input report was accepted")


def test_toolcall_e2e_rejects_copyable_metadata_before_writing(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    poisoned = _safe_packet_report()
    poisoned["samples"][0]["safeMetadata"]["mainSkill"] = "https://pobb.in/abcd1234"
    input_report.write_text(json.dumps(poisoned), encoding="utf-8")

    try:
        run_phase4_researcher_toolcall_e2e.write_toolcall_acceptance_report(
            input_report=input_report,
            db_path=tmp_path / "mature.sqlite",
            graph_snapshot_index_path=tmp_path / "missing-snapshot-index.sqlite",
            json_output=tmp_path / "toolcall.json",
            md_output=tmp_path / "toolcall.md",
        )
    except ValueError as exc:
        assert "copy-safety" in str(exc)
    else:
        raise AssertionError("copyable metadata was accepted")

    assert not (tmp_path / "toolcall.json").exists()
    assert not (tmp_path / "toolcall.md").exists()


def test_toolcall_e2e_rejects_copyable_report_id(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    poisoned = _safe_packet_report()
    poisoned["reportId"] = "https://pobb.in/abcd1234"
    input_report.write_text(json.dumps(poisoned), encoding="utf-8")

    try:
        run_phase4_researcher_toolcall_e2e.build_toolcall_acceptance_report(
            input_report=input_report,
            db_path=tmp_path / "mature.sqlite",
            graph_snapshot_index_path=tmp_path / "missing-snapshot-index.sqlite",
        )
    except ValueError as exc:
        assert "reportId" in str(exc)
    else:
        raise AssertionError("copyable report id was accepted")


def test_toolcall_e2e_rejects_copyable_sample_id(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    poisoned = _safe_packet_report()
    poisoned["samples"][0]["sampleId"] = "https://pobb.in/abcd1234"
    input_report.write_text(json.dumps(poisoned), encoding="utf-8")

    try:
        run_phase4_researcher_toolcall_e2e.build_toolcall_acceptance_report(
            input_report=input_report,
            db_path=tmp_path / "mature.sqlite",
            graph_snapshot_index_path=tmp_path / "missing-snapshot-index.sqlite",
        )
    except ValueError as exc:
        assert "sampleId" in str(exc)
    else:
        raise AssertionError("copyable sample id was accepted")
