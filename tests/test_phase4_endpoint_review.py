from __future__ import annotations

import json

from scripts import run_phase4_endpoint_review as endpoint_review


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


def test_endpoint_review_template_preserves_ambiguity_without_auto_accepting(tmp_path):
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            {
                "reportId": "phase4-real-sample-graph-coverage-v1",
                "status": "coverage_probe_completed",
                "safeArtifactOnly": True,
                "snapshotId": "physical-graph-fixture",
                "probes": [
                    {
                        "sampleId": "phase4_user_pob_001",
                        "safeSourceRef": "source-hash:aaaaaaaaaaaaaaaa",
                        "packetSafeHashRef": "packet-safe-hash:bbbbbbbbbbbbbbbb",
                        "candidateName": "Hollow Focus",
                        "queryName": "Hollow Focus",
                        "queryProvenance": "safe_metadata_unresolved_label",
                        "resolverStatus": "ambiguous",
                        "snapshotId": "physical-graph-fixture",
                        "candidateCount": 3,
                        "candidates": [
                            {
                                "stableKey": "gem:Metadata/Items/Gem/SkillGemAscendancyHollowFocus",
                                "nodeType": "skill_gem",
                                "sourceRefs": ["repoe:skill_gems"],
                            },
                            {
                                "stableKey": "item_base:Metadata/Items/Gem/SkillGemAscendancyHollowFocus",
                                "nodeType": "item_base",
                                "sourceRefs": ["repoe:base_items"],
                            },
                            {
                                "stableKey": "skill:HollowFocusPlayer",
                                "nodeType": "active_skill",
                                "sourceRefs": ["repoe:skill_gems", "repoe:skills"],
                            },
                        ],
                        "semanticEdgeAction": "requires_manual_endpoint_mapping",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = endpoint_review.build_endpoint_review_report(input_report=coverage_path)

    assert report["status"] == "needs_manual_endpoint_review"
    assert report["safeArtifactOnly"] is True
    assert report["autoAcceptedCount"] == 0
    assert report["reviewItemCount"] == 1
    item = report["reviewItems"][0]
    assert item["reviewStatus"] == "needs_manual_review"
    assert item["recommendedStableKey"] == "skill:HollowFocusPlayer"
    assert item["recommendationBasis"] == "active_skill_candidate_preferred_for_mainSkill"
    assert item["acceptedStableKey"] is None
    assert item["requiresUserDecision"] is True
    assert item["semanticEdgeActionAfterReview"] == "blocked_until_review_acceptance"

    serialized = json.dumps(report, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_endpoint_review_template_does_not_recommend_when_multiple_active_skill_candidates(
    tmp_path,
):
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            {
                "reportId": "phase4-real-sample-graph-coverage-v1",
                "status": "coverage_probe_completed",
                "safeArtifactOnly": True,
                "snapshotId": "physical-graph-fixture",
                "probes": [
                    {
                        "sampleId": "phase4_user_pob_003",
                        "candidateName": "Crossbow Shot",
                        "queryProvenance": "safe_metadata_unresolved_label",
                        "resolverStatus": "ambiguous",
                        "snapshotId": "physical-graph-fixture",
                        "candidateCount": 4,
                        "candidates": [
                            {
                                "stableKey": "gem:Metadata/Items/Gem/SkillGemPlayerDefaultCrossbow",
                                "nodeType": "skill_gem",
                                "sourceRefs": ["repoe:skill_gems"],
                            },
                            {
                                "stableKey": "skill:MeleeCrossbowPlayer",
                                "nodeType": "active_skill",
                                "sourceRefs": ["repoe:skill_gems", "repoe:skills"],
                            },
                            {
                                "stableKey": "skill:MeleeCrossbowRogueExile",
                                "nodeType": "active_skill",
                                "sourceRefs": ["repoe:skills"],
                            },
                        ],
                        "semanticEdgeAction": "requires_manual_endpoint_mapping",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = endpoint_review.build_endpoint_review_report(input_report=coverage_path)

    item = report["reviewItems"][0]
    assert item["reviewStatus"] == "needs_manual_review"
    assert item["recommendedStableKey"] is None
    assert item["recommendationBasis"] == "multiple_active_skill_candidates_no_recommendation"
    assert item["acceptedStableKey"] is None
    assert item["requiresUserDecision"] is True


def test_endpoint_review_rejects_unsafe_nested_endpoint_assessment(tmp_path):
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            {
                "reportId": "phase4-real-sample-graph-coverage-v1",
                "status": "coverage_probe_completed",
                "safeArtifactOnly": True,
                "snapshotId": "physical-graph-fixture",
                "probes": [
                    {
                        "sampleId": "phase4_user_pob_001",
                        "candidateName": "Hollow Focus",
                        "queryProvenance": "safe_metadata_unresolved_label",
                        "resolverStatus": "missing",
                        "snapshotId": "physical-graph-fixture",
                        "candidates": [],
                        "endpointAssessment": {
                            "classification": "source_coverage_gap",
                            "hallucinationVerdict": "not_assessed",
                            "reason": "see https://example.com/build",
                        },
                        "semanticEdgeAction": "deferred_source_coverage_gap",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        endpoint_review.build_endpoint_review_report(input_report=coverage_path)
    except ValueError as exc:
        assert "copy-safety" in str(exc)
    else:
        raise AssertionError("unsafe nested endpointAssessment should be rejected")


def test_endpoint_review_template_writes_safe_json_and_markdown(tmp_path):
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            {
                "reportId": "phase4-real-sample-graph-coverage-v1",
                "status": "coverage_probe_completed",
                "safeArtifactOnly": True,
                "snapshotId": "physical-graph-fixture",
                "probes": [
                    {
                        "sampleId": "phase4_user_pob_001",
                        "candidateName": "Hollow Focus",
                        "queryProvenance": "safe_metadata_unresolved_label",
                        "resolverStatus": "resolved",
                        "stableKey": "skill:HollowFocusPlayer",
                        "nodeType": "active_skill",
                        "snapshotId": "physical-graph-fixture",
                        "sourceRefs": ["repoe:skills"],
                        "evidencePathNodes": ["skill:HollowFocusPlayer"],
                        "semanticEdgeAction": "ready_for_researcher_semantic_review",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_json = tmp_path / "endpoint-review.json"
    output_md = tmp_path / "endpoint-review.md"

    report = endpoint_review.write_endpoint_review_report(
        input_report=coverage_path,
        json_output=output_json,
        md_output=output_md,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    markdown = output_md.read_text(encoding="utf-8")
    assert "Phase 4 Endpoint Review" in markdown
    assert "ready_for_researcher_semantic_review" in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)
