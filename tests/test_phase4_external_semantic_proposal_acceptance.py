from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from scripts import run_phase4_external_semantic_proposal_acceptance as acceptance
from server.knowledge import physical_graph as pg
from server.knowledge import research_memory


def test_external_semantic_proposal_acceptance_rejects_endpoint_outside_mapping(
    tmp_path, monkeypatch
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "reviewed-secondary-empty.json"
    proposal_path = tmp_path / "proposal.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_empty_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [
                    {
                        "source_key": "skill:MeleeCrossbowPlayer",
                        "target_key": "skill:HollowFocusPlayer",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=proposal_path,
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["status"] == "rejected_endpoint_not_accepted"
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["rejection"]["errorCode"] == "endpoint_not_in_accepted_mapping"
    assert "skill:MeleeCrossbowPlayer" in report["rejection"]["endpointKeys"]


@pytest.mark.parametrize(
    ("proposal", "error_code"),
    [
        (
            {"schema_version": 4, "fragments": [], "semantic_edges": {}},
            "invalid_semantic_edges_shape",
        ),
        (
            {"schema_version": 4, "fragments": [], "semantic_edges": ["not-an-object"]},
            "invalid_semantic_edge_shape",
        ),
        (
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [{"source_key": "skill:HollowFocusPlayer"}],
            },
            "missing_semantic_edge_endpoint",
        ),
        (
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [{"Source_Key": "skill:HollowFocusPlayer"}],
            },
            "missing_semantic_edge_endpoint",
        ),
        (
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [
                    {
                        "source_key": "skill:HollowFocusPlayer",
                        "target_key": "skill:MeleeCrossbowPlayer",
                    }
                ],
            },
            "endpoint_not_in_accepted_mapping",
        ),
    ],
)
def test_external_semantic_proposal_acceptance_rejects_malformed_endpoint_shape_before_service(
    tmp_path, monkeypatch, proposal, error_code
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "reviewed-secondary-empty.json"
    proposal_path = tmp_path / "proposal.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_empty_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    proposal_path.write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=proposal_path,
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["rejection"]["errorCode"] == error_code


def test_external_semantic_proposal_acceptance_defers_primary_only_proposal_without_secondary(
    tmp_path, monkeypatch
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "reviewed-secondary-empty.json"
    proposal_path = tmp_path / "proposal.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_empty_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [
                    {
                        "source_key": "skill:HollowFocusPlayer",
                        "target_key": "skill:VividStampedePlayer",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=proposal_path,
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["status"] == "deferred_secondary_endpoint_gap"
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["acceptedSecondaryEndpointCount"] == 0
    assert report["proposalEndpointCount"] == 2
    assert report["deferred"]["reason"] == "proposal_blocked_secondary_endpoint_gap"


def test_external_semantic_proposal_acceptance_rejects_primary_only_edge_even_with_secondary(
    tmp_path, monkeypatch
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "reviewed-secondary.json"
    proposal_path = tmp_path / "proposal.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [
                    {
                        "source_key": "skill:HollowFocusPlayer",
                        "target_key": "skill:VividStampedePlayer",
                        "edge_type": "has_modelability_caveat",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=proposal_path,
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["status"] == "rejected_invalid_endpoint_pair"
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["rejection"]["errorCode"] == "endpoint_pair_not_reviewed"


def test_external_semantic_proposal_acceptance_rejects_cross_sample_secondary_pair(
    tmp_path, monkeypatch
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "reviewed-secondary.json"
    proposal_path = tmp_path / "proposal.json"
    secondary = _reviewed_secondary_report()
    secondary["reviewItems"].append(
        _reviewed_secondary_item(
            sample_id="phase4_user_pob_004",
            primary_key="skill:VividStampedePlayer",
            candidate_name="Wild Protector",
            stable_key="skill:WildProtectorPlayer",
        )
    )
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(json.dumps(secondary, ensure_ascii=False), encoding="utf-8")
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [
                    {
                        "source_key": "skill:HollowFocusPlayer",
                        "target_key": "skill:WildProtectorPlayer",
                        "edge_type": "has_modelability_caveat",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=proposal_path,
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["status"] == "rejected_invalid_endpoint_pair"
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["rejection"]["errorCode"] == "endpoint_pair_not_reviewed"


def test_external_semantic_proposal_acceptance_rejects_non_advisory_edge_type(
    tmp_path, monkeypatch
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "reviewed-secondary.json"
    proposal_path = tmp_path / "proposal.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [
                    {
                        "source_key": "skill:HollowFocusPlayer",
                        "target_key": "skill:HeraldOfThunderPlayer",
                        "edge_type": "enables_mechanic",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=proposal_path,
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["status"] == "rejected_unsupported_real_edge_type"
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["rejection"]["errorCode"] == "unsupported_real_edge_type"


def test_external_semantic_proposal_acceptance_allows_resolved_secondary_endpoints(
    tmp_path, monkeypatch
):
    calls = []

    def fake_propose(self, payload):  # noqa: ARG001
        calls.append(payload)
        return {
            "status": "accepted",
            "edgeIds": ["rse-secondary"],
            "noRawMatureBuildMaterial": True,
        }

    monkeypatch.setattr(
        research_memory.ResearchMemoryService, "propose_semantic_edges", fake_propose
    )
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "reviewed-secondary.json"
    proposal_path = tmp_path / "proposal.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_reviewed_secondary_report(), ensure_ascii=False), encoding="utf-8"
    )
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [
                    {
                        "source_key": "skill:HollowFocusPlayer",
                        "target_key": "skill:HeraldOfThunderPlayer",
                        "edge_type": "has_modelability_caveat",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=proposal_path,
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["status"] == "accepted"
    assert report["acceptedSecondaryEndpointCount"] == 1
    assert report["acceptedSecondaryStableKeyCount"] == 1
    assert report["acceptedSecondaryMappingCount"] == 1
    assert report["semanticEdgeWrite"]["attempted"] is True
    assert calls and calls[0]["semantic_edges"][0]["target_key"] == "skill:HeraldOfThunderPlayer"


def test_external_semantic_proposal_acceptance_rechecks_secondary_against_primary_mapping(
    tmp_path, monkeypatch
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    mapping_path = tmp_path / "reviewed.json"
    secondary = _reviewed_secondary_report()
    secondary["reviewItems"][0]["primaryStableKey"] = "skill:WrongPrimary"
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
    secondary_path = tmp_path / "reviewed-secondary.json"
    proposal_path = tmp_path / "proposal.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(json.dumps(secondary, ensure_ascii=False), encoding="utf-8")
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [
                    {
                        "source_key": "skill:HollowFocusPlayer",
                        "target_key": "skill:CrossbowSecondaryShouldNotPass",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=proposal_path,
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["status"] == "rejected_endpoint_not_accepted"
    assert report["acceptedSecondaryEndpointCount"] == 0
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["rejection"]["endpointKeys"] == ["skill:CrossbowSecondaryShouldNotPass"]


def test_external_semantic_proposal_acceptance_rejects_stale_secondary_snapshot(tmp_path):
    mapping_path = tmp_path / "reviewed.json"
    secondary = _reviewed_secondary_report()
    secondary["snapshotId"] = "physical-graph-stale"
    secondary_path = tmp_path / "reviewed-secondary.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(json.dumps(secondary, ensure_ascii=False), encoding="utf-8")

    try:
        acceptance.build_external_semantic_proposal_acceptance_report(
            mapping_report=mapping_path,
            secondary_endpoint_report=secondary_path,
            proposal_file=None,
            db_path=tmp_path / "mature.sqlite",
        )
    except ValueError as exc:
        assert "snapshot" in str(exc)
    else:
        raise AssertionError("stale reviewed secondary report must be rejected")


def test_external_semantic_proposal_acceptance_rejects_primary_key_not_in_candidates(tmp_path):
    mapping = _mapping_report()
    mapping["reviewItems"][0]["acceptedStableKey"] = "skill:ForgedPrimary"
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "reviewed-secondary-empty.json"
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_empty_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )

    try:
        acceptance.build_external_semantic_proposal_acceptance_report(
            mapping_report=mapping_path,
            secondary_endpoint_report=secondary_path,
            proposal_file=None,
            db_path=tmp_path / "mature.sqlite",
        )
    except ValueError as exc:
        assert "candidates" in str(exc)
    else:
        raise AssertionError("reviewed primary key outside resolver candidates must be rejected")


def test_external_semantic_proposal_acceptance_rejects_graph_snapshot_mismatch(
    tmp_path, monkeypatch
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "reviewed-secondary.json"
    proposal_path = tmp_path / "proposal.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [
                    {
                        "source_key": "skill:HollowFocusPlayer",
                        "target_key": "skill:HeraldOfThunderPlayer",
                        "edge_type": "has_modelability_caveat",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=proposal_path,
        db_path=tmp_path / "mature.sqlite",
        graph_snapshot_index=_write_snapshot_index(tmp_path, snapshot_id="physical-graph-current"),
    )

    assert report["status"] == "rejected_stale_graph_snapshot"
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["rejection"]["errorCode"] == "graph_snapshot_mismatch"


def test_external_semantic_proposal_acceptance_rejects_empty_semantic_edges(tmp_path, monkeypatch):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "reviewed-secondary.json"
    proposal_path = tmp_path / "proposal.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_reviewed_secondary_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    proposal_path.write_text(
        json.dumps({"schema_version": 4, "fragments": [], "semantic_edges": []}),
        encoding="utf-8",
    )

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=proposal_path,
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["status"] == "rejected_invalid_endpoint_shape"
    assert report["rejection"]["errorCode"] == "empty_semantic_edges"


def test_external_semantic_proposal_acceptance_does_not_use_unreviewed_secondary_report(
    tmp_path, monkeypatch
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "secondary.json"
    proposal_path = tmp_path / "proposal.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(json.dumps(_secondary_report(), ensure_ascii=False), encoding="utf-8")
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "fragments": [],
                "semantic_edges": [
                    {
                        "source_key": "skill:HollowFocusPlayer",
                        "target_key": "skill:HeraldOfThunderPlayer",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=proposal_path,
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["status"] == "rejected_endpoint_not_accepted"
    assert report["acceptedSecondaryEndpointCount"] == 0
    assert report["semanticEdgeWrite"]["attempted"] is False


def test_external_semantic_proposal_acceptance_deferred_when_no_resolved_secondary_endpoints(
    tmp_path, monkeypatch
):
    _fail_if_semantic_edges_are_proposed(monkeypatch)
    mapping_path = tmp_path / "reviewed.json"
    secondary_path = tmp_path / "secondary.json"
    mapping_path.write_text(json.dumps(_mapping_report(), ensure_ascii=False), encoding="utf-8")
    secondary_path.write_text(
        json.dumps(_secondary_gap_report(), ensure_ascii=False),
        encoding="utf-8",
    )

    report = acceptance.build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_path,
        secondary_endpoint_report=secondary_path,
        proposal_file=None,
        db_path=tmp_path / "mature.sqlite",
    )

    assert report["status"] == "deferred_secondary_endpoint_gap"
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert report["semanticEdgeWrite"]["reason"] == "deferred_secondary_endpoint_gap"
    assert report["acceptedSecondaryEndpointCount"] == 0
    assert report["deferred"]["requiresManualEndpointMapping"] is True
    assert report["deferred"]["reason"] == "no_external_semantic_proposal_or_secondary_surface"


def _mapping_report():
    return {
        "reportId": "phase4-reviewed-endpoint-mapping-v1",
        "status": "partial_endpoint_mapping_accepted",
        "safeArtifactOnly": True,
        "snapshotId": "physical-graph-fixture",
        "reviewItems": [
            _accepted_primary("phase4_user_pob_001", "skill:HollowFocusPlayer"),
            {
                "sampleId": "phase4_user_pob_003",
                "reviewStatus": "pending_manual_review",
                "acceptedStableKey": None,
            },
            _accepted_primary("phase4_user_pob_004", "skill:VividStampedePlayer"),
        ],
    }


def _accepted_primary(sample_id, stable_key):
    return {
        "sampleId": sample_id,
        "reviewStatus": "accepted",
        "acceptedStableKey": stable_key,
        "candidates": [
            {
                "stableKey": stable_key,
                "nodeType": "active_skill",
                "sourceRefs": ["repoe:skills"],
            }
        ],
    }


def _secondary_report():
    return {
        "reportId": "phase4-secondary-endpoint-resolution-v1",
        "status": "secondary_endpoint_resolution_completed",
        "safeArtifactOnly": True,
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
            },
            {
                "sampleId": "phase4_user_pob_003",
                "sampleEndpointStatus": "pending_manual_review",
                "primaryStableKey": None,
                "candidateName": "Herald of Thunder",
                "candidateKind": "secondary_component",
                "resolverStatus": "resolved",
                "stableKey": "skill:CrossbowSecondaryShouldNotPass",
                "nodeType": "active_skill",
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
            _reviewed_secondary_item(
                sample_id="phase4_user_pob_001",
                primary_key="skill:HollowFocusPlayer",
                candidate_name="Herald of Thunder",
                stable_key="skill:HeraldOfThunderPlayer",
            ),
            {
                "sampleId": "phase4_user_pob_003",
                "sampleEndpointStatus": "pending_manual_review",
                "primaryStableKey": None,
                "candidateName": "Herald of Thunder",
                "candidateKind": "secondary_component",
                "resolverStatus": "ambiguous",
                "reviewStatus": "accepted",
                "acceptedStableKey": "skill:CrossbowSecondaryShouldNotPass",
                "nodeType": "active_skill",
                "semanticEdgeActionAfterReview": "ready_for_external_semantic_edge",
            },
        ],
    }


def _reviewed_secondary_item(sample_id, primary_key, candidate_name, stable_key):
    return {
        "sampleId": sample_id,
        "sampleEndpointStatus": "accepted",
        "primaryStableKey": primary_key,
        "candidateName": candidate_name,
        "candidateKind": "secondary_component",
        "resolverStatus": "ambiguous",
        "reviewStatus": "accepted",
        "acceptedStableKey": stable_key,
        "nodeType": "active_skill",
        "semanticEdgeActionAfterReview": "ready_for_external_semantic_edge",
        "candidates": [
            {
                "stableKey": stable_key,
                "nodeType": "active_skill",
                "sourceRefs": ["repoe:skills"],
            }
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


def _secondary_gap_report():
    return {
        "reportId": "phase4-secondary-endpoint-resolution-v1",
        "status": "secondary_endpoint_resolution_completed",
        "safeArtifactOnly": True,
        "secondaryEndpoints": [
            {
                "sampleId": "phase4_user_pob_001",
                "sampleEndpointStatus": "accepted",
                "candidateName": "Herald of Thunder",
                "candidateKind": "secondary_component",
                "resolverStatus": "ambiguous",
                "stableKey": None,
                "semanticEdgeAction": "requires_manual_endpoint_mapping",
            },
            {
                "sampleId": "phase4_user_pob_004",
                "sampleEndpointStatus": "accepted",
                "candidateName": "companion_layer",
                "candidateKind": "abstract_mechanism_tag",
                "resolverStatus": "not_graph_entity",
                "stableKey": None,
                "semanticEdgeAction": "verification_caveat_only",
            },
        ],
    }


def _fail_if_semantic_edges_are_proposed(monkeypatch):
    def fail(self, payload):  # noqa: ARG001
        raise AssertionError("invalid proposal must not call propose_semantic_edges")

    monkeypatch.setattr(research_memory.ResearchMemoryService, "propose_semantic_edges", fail)


def _write_snapshot_index(tmp_path, *, snapshot_id: str):
    source = pg.GraphSource(
        source_id="repoe:skills",
        kind="repoe_raw",
        source_file="skills.min.json",
        expected_count=2,
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
    )
    aliases = tuple(
        pg.GraphAlias(node.stable_key, node.stable_key, (source.source_id,)) for node in nodes
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id=snapshot_id,
        created_at=datetime(2026, 7, 4, tzinfo=UTC),
        sources=(source,),
        nodes=nodes,
        edges=(),
        aliases=aliases,
    )
    snapshot_path = tmp_path / f"{snapshot_id}.json"
    index_path = tmp_path / "snapshot_index.sqlite"
    pg.save_snapshot(snapshot, snapshot_path)
    pg.register_snapshot(index_path, snapshot, snapshot_path)
    return index_path
