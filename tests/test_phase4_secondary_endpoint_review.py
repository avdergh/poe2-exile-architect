from __future__ import annotations

import json

from scripts import run_phase4_secondary_endpoint_review as secondary_review


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


def test_secondary_endpoint_review_preserves_ambiguity_without_auto_accepting(tmp_path):
    secondary_path = tmp_path / "secondary.json"
    secondary_path.write_text(json.dumps(_secondary_report(), ensure_ascii=False), encoding="utf-8")

    report = secondary_review.build_secondary_endpoint_review_report(
        input_report=secondary_path,
    )

    assert report["status"] == "needs_manual_secondary_endpoint_review"
    assert report["safeArtifactOnly"] is True
    assert report["reviewItemCount"] == 2
    assert report["blockedPrimaryCount"] == 1
    assert report["autoAcceptedCount"] == 0

    by_name = {item["candidateName"]: item for item in report["reviewItems"]}
    wild = by_name["Wild Protector"]
    assert wild["reviewStatus"] == "needs_manual_review"
    assert wild["recommendedStableKey"] == "skill:WildProtectorPlayer"
    assert wild["recommendationBasis"] == "single_active_skill_candidate"
    assert wild["acceptedStableKey"] is None
    assert wild["endpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert wild["semanticEdgeActionAfterReview"] == "blocked_until_secondary_review_acceptance"

    herald = by_name["Herald of Thunder"]
    assert herald["recommendedStableKey"] is None
    assert herald["recommendationBasis"] == "multiple_active_skill_candidates_no_recommendation"

    blocked = report["blockedPrimaryItems"][0]
    assert blocked["sampleId"] == "phase4_user_pob_003"
    assert blocked["semanticEdgeActionAfterReview"] == "blocked_primary_endpoint_pending"

    serialized = json.dumps(report, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_secondary_endpoint_review_writes_safe_json_and_markdown(tmp_path):
    secondary_path = tmp_path / "secondary.json"
    secondary_path.write_text(json.dumps(_secondary_report(), ensure_ascii=False), encoding="utf-8")
    output_json = tmp_path / "review.json"
    output_md = tmp_path / "review.md"

    report = secondary_review.write_secondary_endpoint_review_report(
        input_report=secondary_path,
        json_output=output_json,
        md_output=output_md,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    markdown = output_md.read_text(encoding="utf-8")
    assert "Phase 4 Secondary Endpoint Review" in markdown
    assert "Wild Protector" in markdown
    assert "accepted: `None`" in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)


def _secondary_report():
    return {
        "reportId": "phase4-secondary-endpoint-resolution-v1",
        "status": "secondary_endpoint_resolution_completed",
        "safeArtifactOnly": True,
        "snapshotId": "physical-graph-fixture",
        "secondaryEndpoints": [
            {
                "sampleId": "phase4_user_pob_004",
                "sampleEndpointStatus": "accepted",
                "primaryStableKey": "skill:VividStampedePlayer",
                "candidateName": "Wild Protector",
                "candidateKind": "secondary_component",
                "resolverStatus": "ambiguous",
                "stableKey": None,
                "nodeType": None,
                "candidateCount": 3,
                "candidates": [
                    {
                        "stableKey": "gem:Metadata/Items/Gem/SkillGemWildProtector",
                        "nodeType": "skill_gem",
                        "sourceRefs": ["repoe:skill_gems"],
                    },
                    {
                        "stableKey": "item_base:Metadata/Items/Gem/SkillGemWildProtector",
                        "nodeType": "item_base",
                        "sourceRefs": ["repoe:base_items"],
                    },
                    {
                        "stableKey": "skill:WildProtectorPlayer",
                        "nodeType": "active_skill",
                        "sourceRefs": ["repoe:skills"],
                    },
                ],
                "endpointAssessment": {
                    "classification": "ambiguous_endpoint",
                    "hallucinationVerdict": "not_assessed",
                    "requiresStaticSourceReview": True,
                },
                "semanticEdgeAction": "requires_manual_endpoint_mapping",
            },
            {
                "sampleId": "phase4_user_pob_004",
                "sampleEndpointStatus": "accepted",
                "primaryStableKey": "skill:VividStampedePlayer",
                "candidateName": "Herald of Thunder",
                "candidateKind": "secondary_component",
                "resolverStatus": "ambiguous",
                "stableKey": None,
                "candidateCount": 2,
                "candidates": [
                    {
                        "stableKey": "skill:HeraldOfThunderPlayer",
                        "nodeType": "active_skill",
                        "sourceRefs": ["repoe:skills"],
                    },
                    {
                        "stableKey": "skill:UniqueHeraldOfThunderPlayer",
                        "nodeType": "active_skill",
                        "sourceRefs": ["repoe:skills"],
                    },
                ],
                "endpointAssessment": {
                    "classification": "ambiguous_endpoint",
                    "hallucinationVerdict": "not_assessed",
                    "requiresStaticSourceReview": True,
                },
                "semanticEdgeAction": "requires_manual_endpoint_mapping",
            },
            {
                "sampleId": "phase4_user_pob_004",
                "sampleEndpointStatus": "accepted",
                "primaryStableKey": "skill:VividStampedePlayer",
                "candidateName": "companion_layer",
                "candidateKind": "abstract_mechanism_tag",
                "resolverStatus": "not_graph_entity",
                "stableKey": None,
                "semanticEdgeAction": "verification_caveat_only",
            },
            {
                "sampleId": "phase4_user_pob_003",
                "sampleEndpointStatus": "pending_manual_review",
                "primaryStableKey": None,
                "candidateName": "Escape Shot",
                "candidateKind": "secondary_component",
                "resolverStatus": "ambiguous",
                "stableKey": None,
                "candidateCount": 1,
                "candidates": [
                    {
                        "stableKey": "skill:EscapeShotPlayer",
                        "nodeType": "active_skill",
                        "sourceRefs": ["repoe:skills"],
                    }
                ],
                "semanticEdgeAction": "requires_manual_endpoint_mapping",
            },
        ],
    }
