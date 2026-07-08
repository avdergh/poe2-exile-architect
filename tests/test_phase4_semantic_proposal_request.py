from __future__ import annotations

import json

from scripts import build_phase4_semantic_proposal_request as request_builder


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


def test_semantic_proposal_request_includes_only_accepted_endpoint_mappings(tmp_path):
    mapping_path = tmp_path / "reviewed-mapping.json"
    secondary_path = tmp_path / "reviewed-secondary-empty.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_empty_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )

    report = request_builder.build_semantic_proposal_request(
        input_report=mapping_path,
        secondary_endpoint_report=secondary_path,
    )

    assert report["status"] == "ready_for_external_researcher_semantic_proposal"
    assert report["safeArtifactOnly"] is True
    assert report["acceptedEndpointCount"] == 3
    assert report["pendingEndpointCount"] == 1
    assert {item["sampleId"] for item in report["acceptedEndpoints"]} == {
        "phase4_user_pob_001",
        "phase4_user_pob_002",
        "phase4_user_pob_004",
    }
    assert "phase4_user_pob_003" not in json.dumps(report["acceptedEndpoints"])
    assert "query_research_memory" in report["researcherSop"]
    assert "propose_semantic_edges" in report["researcherSop"]
    assert "DO NOT output final JSON as plain text" in report["researcherSop"]
    assert report["semanticEdgeWrite"]["attempted"] is False

    serialized = json.dumps(report, ensure_ascii=False)
    assert "Crossbow Shot" not in serialized
    assert "skill:MeleeCrossbowPlayer" not in serialized
    assert "skill:MeleeCrossbowRogueExile" not in serialized
    assert "SkillGemPlayerDefaultCrossbow" not in serialized
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_semantic_proposal_request_includes_resolved_secondary_endpoints(tmp_path):
    mapping_path = tmp_path / "reviewed-mapping.json"
    secondary_path = tmp_path / "reviewed-secondary.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )

    report = request_builder.build_semantic_proposal_request(
        input_report=mapping_path,
        secondary_endpoint_report=secondary_path,
    )

    assert report["acceptedEndpointCount"] == 3
    assert report["resolvedSecondaryEndpointCount"] == 2
    assert {item["stableKey"] for item in report["resolvedSecondaryEndpoints"]} == {
        "skill:HeraldOfThunderPlayer",
        "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
    }
    assert all(
        item["sampleId"] != "phase4_user_pob_003" for item in report["resolvedSecondaryEndpoints"]
    )
    assert "secondary endpoint" in report["researcherSop"]
    serialized = json.dumps(report, ensure_ascii=False)
    assert "elemental_ailment_layer" not in serialized
    assert "Crossbow Shot" not in serialized
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_semantic_proposal_request_rejects_stale_secondary_primary_mapping(tmp_path):
    mapping_path = tmp_path / "reviewed-mapping.json"
    secondary = _reviewed_secondary_report()
    secondary["reviewItems"].append(
        {
            "sampleId": "phase4_user_pob_003",
            "sampleEndpointStatus": "accepted",
            "primaryStableKey": "skill:MeleeCrossbowPlayer",
            "candidateName": "Forged Crossbow Helper",
            "candidateKind": "secondary_component",
            "resolverStatus": "ambiguous",
            "reviewStatus": "accepted",
            "acceptedStableKey": "skill:CrossbowSecondaryShouldNotPass",
            "nodeType": "active_skill",
            "semanticEdgeActionAfterReview": "ready_for_external_semantic_edge",
        }
    )
    secondary["reviewItems"][0]["primaryStableKey"] = "skill:WrongPrimary"
    secondary_path = tmp_path / "reviewed-secondary.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(json.dumps(secondary, ensure_ascii=False), encoding="utf-8")

    report = request_builder.build_semantic_proposal_request(
        input_report=mapping_path,
        secondary_endpoint_report=secondary_path,
    )

    assert report["resolvedSecondaryEndpointCount"] == 1
    assert {item["stableKey"] for item in report["resolvedSecondaryEndpoints"]} == {
        "support:Metadata/Items/Gems/SupportGemIngenuityTwo"
    }
    serialized = json.dumps(report, ensure_ascii=False)
    assert "skill:CrossbowSecondaryShouldNotPass" not in serialized
    assert "skill:HeraldOfThunderPlayer" not in serialized


def test_semantic_proposal_request_rejects_stale_secondary_snapshot(tmp_path):
    mapping_path = tmp_path / "reviewed-mapping.json"
    secondary = _reviewed_secondary_report()
    secondary["snapshotId"] = "physical-graph-stale"
    secondary_path = tmp_path / "reviewed-secondary.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(json.dumps(secondary, ensure_ascii=False), encoding="utf-8")

    try:
        request_builder.build_semantic_proposal_request(
            input_report=mapping_path,
            secondary_endpoint_report=secondary_path,
        )
    except ValueError as exc:
        assert "snapshot" in str(exc)
    else:
        raise AssertionError("stale reviewed secondary report must be rejected")


def test_semantic_proposal_request_rejects_secondary_key_not_in_candidates(tmp_path):
    mapping_path = tmp_path / "reviewed-mapping.json"
    secondary = _reviewed_secondary_report()
    secondary["reviewItems"][0]["acceptedStableKey"] = "skill:ForgedSecondary"
    secondary_path = tmp_path / "reviewed-secondary.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(json.dumps(secondary, ensure_ascii=False), encoding="utf-8")

    try:
        request_builder.build_semantic_proposal_request(
            input_report=mapping_path,
            secondary_endpoint_report=secondary_path,
        )
    except ValueError as exc:
        assert "candidates" in str(exc)
    else:
        raise AssertionError("reviewed secondary key outside resolver candidates must be rejected")


def test_semantic_proposal_request_rejects_primary_key_not_in_candidates(tmp_path):
    mapping = _mapping_report()
    mapping["reviewItems"][0]["acceptedStableKey"] = "skill:ForgedPrimary"
    mapping_path = tmp_path / "reviewed-mapping.json"
    secondary_path = tmp_path / "reviewed-secondary-empty.json"
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_empty_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )

    try:
        request_builder.build_semantic_proposal_request(
            input_report=mapping_path,
            secondary_endpoint_report=secondary_path,
        )
    except ValueError as exc:
        assert "candidates" in str(exc)
    else:
        raise AssertionError("reviewed primary key outside resolver candidates must be rejected")


def test_semantic_proposal_request_exposes_allowed_same_sample_edge_pairs(tmp_path):
    mapping_path = tmp_path / "reviewed-mapping.json"
    secondary_path = tmp_path / "reviewed-secondary.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )

    report = request_builder.build_semantic_proposal_request(
        input_report=mapping_path,
        secondary_endpoint_report=secondary_path,
    )

    assert report["allowedEdgePairCount"] == 2
    assert {
        (item["sampleId"], item["sourceKey"], item["targetKey"])
        for item in report["allowedEdgePairs"]
    } == {
        ("phase4_user_pob_001", "skill:HollowFocusPlayer", "skill:HeraldOfThunderPlayer"),
        (
            "phase4_user_pob_001",
            "skill:HollowFocusPlayer",
            "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
        ),
    }
    assert "fresh resolver-returned stable keys" not in report["researcherSop"]


def test_semantic_proposal_request_derives_secondary_node_type_from_candidate(tmp_path):
    mapping_path = tmp_path / "reviewed-mapping.json"
    secondary = _reviewed_secondary_report()
    secondary["reviewItems"][0].pop("nodeType")
    secondary_path = tmp_path / "reviewed-secondary.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(json.dumps(secondary, ensure_ascii=False), encoding="utf-8")

    report = request_builder.build_semantic_proposal_request(
        input_report=mapping_path,
        secondary_endpoint_report=secondary_path,
    )

    herald = next(
        item
        for item in report["resolvedSecondaryEndpoints"]
        if item["stableKey"] == "skill:HeraldOfThunderPlayer"
    )
    assert herald["nodeType"] == "active_skill"


def test_semantic_proposal_request_does_not_use_unreviewed_secondary_report(tmp_path):
    mapping_path = tmp_path / "reviewed-mapping.json"
    secondary_path = tmp_path / "secondary.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )

    report = request_builder.build_semantic_proposal_request(
        input_report=mapping_path,
        reviewed_secondary_endpoint_report=secondary_path,
    )

    assert report["resolvedSecondaryEndpointCount"] == 0
    assert report["resolvedSecondaryEndpoints"] == []


def test_semantic_proposal_request_writes_safe_json_and_markdown(tmp_path):
    mapping_path = tmp_path / "reviewed-mapping.json"
    secondary_path = tmp_path / "reviewed-secondary-empty.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_empty_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    output_json = tmp_path / "request.json"
    output_md = tmp_path / "request.md"

    report = request_builder.write_semantic_proposal_request(
        input_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        json_output=output_json,
        md_output=output_md,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    markdown = output_md.read_text(encoding="utf-8")
    assert "Phase 4 Semantic Proposal Request" in markdown
    assert "ready_for_external_researcher_semantic_proposal" in markdown
    assert "Crossbow Shot" not in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)


def _secondary_report():
    return {
        "reportId": "phase4-secondary-endpoint-resolution-v1",
        "status": "secondary_endpoint_resolution_completed",
        "safeArtifactOnly": True,
        "snapshotId": "physical-graph-fixture",
        "secondaryEndpoints": [
            {
                "sampleId": "phase4_user_pob_001",
                "sampleEndpointStatus": "accepted",
                "primaryStableKey": "skill:HollowFocusPlayer",
                "candidateName": "Herald of Thunder",
                "candidateKind": "secondary_component",
                "resolverStatus": "resolved",
                "stableKey": "skill:HeraldOfThunderPlayer",
                "nodeType": "active_skill",
                "semanticEdgeAction": "ready_for_external_semantic_edge",
                "resolverEvidence": {
                    "tool_name": "resolve_graph_component",
                    "status": "resolved",
                    "stable_key": "skill:HeraldOfThunderPlayer",
                    "snapshot_id": "physical-graph-fixture",
                    "evidence_path_nodes": ["skill:HeraldOfThunderPlayer"],
                    "source_refs": ["repoe:skills"],
                },
            },
            {
                "sampleId": "phase4_user_pob_001",
                "sampleEndpointStatus": "accepted",
                "primaryStableKey": "skill:HollowFocusPlayer",
                "candidateName": "Cooldown Recovery II",
                "candidateKind": "secondary_component",
                "resolverStatus": "resolved",
                "stableKey": "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
                "nodeType": "support_gem",
                "semanticEdgeAction": "ready_for_external_semantic_edge",
                "resolverEvidence": {
                    "tool_name": "resolve_graph_component",
                    "status": "resolved",
                    "stable_key": "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
                    "snapshot_id": "physical-graph-fixture",
                    "evidence_path_nodes": ["support:Metadata/Items/Gems/SupportGemIngenuityTwo"],
                    "source_refs": ["repoe:skill_gems"],
                },
            },
            {
                "sampleId": "phase4_user_pob_001",
                "sampleEndpointStatus": "accepted",
                "candidateName": "elemental_ailment_layer",
                "candidateKind": "abstract_mechanism_tag",
                "resolverStatus": "not_graph_entity",
                "stableKey": None,
                "semanticEdgeAction": "verification_caveat_only",
            },
            {
                "sampleId": "phase4_user_pob_003",
                "sampleEndpointStatus": "pending_manual_review",
                "candidateName": "Herald of Thunder",
                "candidateKind": "secondary_component",
                "resolverStatus": "resolved",
                "stableKey": "skill:HeraldOfThunderPlayer",
                "semanticEdgeAction": "blocked_primary_endpoint_pending",
            },
        ],
    }


def _reviewed_secondary_report():
    return {
        "reportId": "phase4-reviewed-secondary-endpoint-mapping-v1",
        "inputReportId": "phase4-secondary-endpoint-review-v1",
        "status": "secondary_endpoint_mapping_accepted",
        "safeArtifactOnly": True,
        "snapshotId": "physical-graph-fixture",
        "reviewItems": [
            {
                "sampleId": "phase4_user_pob_001",
                "sampleEndpointStatus": "accepted",
                "primaryStableKey": "skill:HollowFocusPlayer",
                "candidateName": "Herald of Thunder",
                "candidateKind": "secondary_component",
                "resolverStatus": "ambiguous",
                "reviewStatus": "accepted",
                "acceptedStableKey": "skill:HeraldOfThunderPlayer",
                "nodeType": "active_skill",
                "semanticEdgeActionAfterReview": "ready_for_external_semantic_edge",
                "candidates": [
                    {
                        "stableKey": "skill:HeraldOfThunderPlayer",
                        "nodeType": "active_skill",
                        "sourceRefs": ["repoe:skills"],
                    }
                ],
            },
            {
                "sampleId": "phase4_user_pob_001",
                "sampleEndpointStatus": "accepted",
                "primaryStableKey": "skill:HollowFocusPlayer",
                "candidateName": "Cooldown Recovery II",
                "candidateKind": "secondary_component",
                "resolverStatus": "ambiguous",
                "reviewStatus": "accepted",
                "acceptedStableKey": "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
                "nodeType": "support_gem",
                "semanticEdgeActionAfterReview": "ready_for_external_semantic_edge",
                "candidates": [
                    {
                        "stableKey": "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
                        "nodeType": "support_gem",
                        "sourceRefs": ["repoe:skill_gems"],
                    }
                ],
            },
            {
                "sampleId": "phase4_user_pob_003",
                "sampleEndpointStatus": "pending_manual_review",
                "primaryStableKey": None,
                "candidateName": "Forged Crossbow Helper",
                "candidateKind": "secondary_component",
                "resolverStatus": "ambiguous",
                "reviewStatus": "accepted",
                "acceptedStableKey": "skill:CrossbowSecondaryShouldNotPass",
                "nodeType": "active_skill",
                "semanticEdgeActionAfterReview": "ready_for_external_semantic_edge",
            },
        ],
    }


def _empty_reviewed_secondary_report():
    return {
        "reportId": "phase4-reviewed-secondary-endpoint-mapping-v1",
        "inputReportId": "phase4-secondary-endpoint-review-v1",
        "status": "partial_secondary_endpoint_mapping_accepted",
        "safeArtifactOnly": True,
        "snapshotId": "physical-graph-fixture",
        "reviewItems": [],
    }


def _mapping_report():
    return {
        "reportId": "phase4-reviewed-endpoint-mapping-v1",
        "status": "partial_endpoint_mapping_accepted",
        "safeArtifactOnly": True,
        "snapshotId": "physical-graph-fixture",
        "reviewItems": [
            _accepted("phase4_user_pob_001", "Hollow Focus", "skill:HollowFocusPlayer"),
            _accepted(
                "phase4_user_pob_002",
                "Mirage Deadeye",
                "skill:MetaMirageDeadeyePlayer",
            ),
            {
                "sampleId": "phase4_user_pob_003",
                "candidateName": "Crossbow Shot",
                "reviewStatus": "pending_manual_review",
                "acceptedStableKey": None,
                "semanticEdgeActionAfterReview": "blocked_until_review_acceptance",
            },
            _accepted("phase4_user_pob_004", "Vivid Stampede", "skill:VividStampedePlayer"),
        ],
    }


def _accepted(sample_id, candidate_name, stable_key):
    return {
        "sampleId": sample_id,
        "candidateName": candidate_name,
        "reviewStatus": "accepted",
        "acceptedStableKey": stable_key,
        "resolverStatus": "ambiguous",
        "semanticEdgeActionAfterReview": "ready_for_researcher_semantic_review",
        "candidates": [
            {
                "stableKey": stable_key,
                "nodeType": "active_skill",
                "sourceRefs": ["repoe:skills"],
            }
        ],
    }
