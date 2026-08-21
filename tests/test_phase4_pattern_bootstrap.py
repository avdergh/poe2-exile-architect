from __future__ import annotations

from datetime import UTC, datetime
import json

from scripts import build_phase45_pattern_bootstrap_proposal as proposal_builder
from scripts import run_phase4_pattern_bootstrap as pattern_bootstrap
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


def test_deterministic_pattern_builder_emits_observations_until_agent_scope_review():
    nodes = {
        "ascendancy:monk:martial_artist": pg.GraphNode(
            "ascendancy:monk:martial_artist",
            "ascendancy",
            "Martial Artist",
            ("fixture:phase45",),
        ),
        "skill:HollowFocusPlayer": pg.GraphNode(
            "skill:HollowFocusPlayer",
            "active_skill",
            "Hollow Focus",
            ("fixture:phase45",),
        ),
    }
    samples = [
        {
            "sampleId": f"case:builder-{index}",
            "buildFamilyKey": "bf-builder",
            "sourceDiversityKey": f"source:{index}",
            "guideVariantKey": f"variant:{index}",
            "ascendancyKey": "ascendancy:monk:martial_artist",
            "mainSkillKey": "skill:HollowFocusPlayer",
            "activeSkills": ["skill:HollowFocusPlayer"],
            "supports": [],
            "passiveKeys": [],
            "uniqueKeys": [],
        }
        for index in range(1, 3)
    ]

    proposal, selected = proposal_builder._proposal(samples, nodes, "snapshot:phase45")
    review = proposal_builder._review_report(
        samples=samples,
        duplicate_inputs=[],
        proposal=proposal,
        selected_patterns=selected,
        nodes_by_key=nodes,
        snapshot_id="snapshot:phase45",
    )

    assert len(proposal["build_design_observations"]) == 1
    assert proposal["patterns"] == []
    assert research_models.validate_researcher_output(proposal)["status"] == "accepted"
    assert review["status"] == "observation_only_agent_review_required"
    assert review["agentReviewCandidateCount"] == 1
    assert review["agentSemanticScopeReviewRequired"] is True


def test_pattern_bootstrap_accepts_safe_manifest_and_external_pattern_proposal(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    proposal_path = tmp_path / "proposal.json"
    coverage_path = tmp_path / "coverage.json"
    output_json = tmp_path / "bootstrap.json"
    output_md = tmp_path / "bootstrap.md"
    _write_json(manifest_path, _manifest())
    _write_json(proposal_path, _proposal())
    _write_json(coverage_path, _coverage_report())

    report = pattern_bootstrap.write_phase4_pattern_bootstrap_report(
        manifest_file=manifest_path,
        proposal_file=proposal_path,
        source_coverage_report=coverage_path,
        db_path=tmp_path / "memory.sqlite",
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        json_output=output_json,
        md_output=output_md,
        min_samples=8,
        max_samples=10,
        min_families=2,
        max_families=3,
        min_samples_per_family=1,
    )

    assert report["status"] == "accepted"
    assert report["sampleCount"] == 8
    assert report["familyCount"] == 2
    assert report["patternWrite"]["status"] == "accepted"
    assert report["patternWrite"]["patternIds"]
    assert report["metrics"]["acceptedPatternCount"] == 1
    assert report["metrics"]["commonPatternCount"] == 1
    markdown = output_md.read_text(encoding="utf-8")
    assert "Phase 4.5 Pattern Bootstrap" in markdown
    assert "common_within_archetype" in markdown
    serialized = json.dumps(json.loads(output_json.read_text(encoding="utf-8")), ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_pattern_bootstrap_blocks_when_source_coverage_not_ready(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    proposal_path = tmp_path / "proposal.json"
    coverage_path = tmp_path / "coverage.json"
    _write_json(manifest_path, _manifest())
    _write_json(proposal_path, _proposal())
    coverage = _coverage_report()
    coverage["coverageGate"]["readyForMaturePatternBootstrap"] = False
    coverage["coverageGate"]["missingCoverage"] = ["unique"]
    _write_json(coverage_path, coverage)

    report = pattern_bootstrap.build_phase4_pattern_bootstrap_report(
        manifest_file=manifest_path,
        proposal_file=proposal_path,
        source_coverage_report=coverage_path,
        db_path=tmp_path / "memory.sqlite",
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        min_samples=8,
        max_samples=10,
        min_families=2,
        max_families=3,
        min_samples_per_family=1,
    )

    assert report["status"] == "blocked_source_coverage_gap"
    assert report["patternWrite"]["attempted"] is False
    assert report["coverageGate"]["missingCoverage"] == ["unique"]


def test_pattern_bootstrap_rejects_proposal_sample_count_beyond_manifest_support(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    proposal_path = tmp_path / "proposal.json"
    coverage_path = tmp_path / "coverage.json"
    _write_json(manifest_path, _manifest())
    proposal = _proposal()
    proposal["patterns"][0]["sample_count"] = 9
    _write_json(proposal_path, proposal)
    _write_json(coverage_path, _coverage_report())

    report = pattern_bootstrap.build_phase4_pattern_bootstrap_report(
        manifest_file=manifest_path,
        proposal_file=proposal_path,
        source_coverage_report=coverage_path,
        db_path=tmp_path / "memory.sqlite",
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        min_samples=8,
        max_samples=10,
        min_families=2,
        max_families=3,
        min_samples_per_family=1,
    )

    assert report["status"] == "rejected_bootstrap_evidence_mismatch"
    assert report["patternWrite"]["attempted"] is False
    assert report["errorCode"] == "pattern_sample_count_exceeds_pattern_refs"


def test_pattern_bootstrap_rejects_pattern_claims_not_supported_by_own_refs(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    proposal_path = tmp_path / "proposal.json"
    coverage_path = tmp_path / "coverage.json"
    _write_json(manifest_path, _manifest())
    proposal = _proposal()
    proposal["build_design_observations"][0]["source_case_refs"] = ["case:poison-bow-1"]
    proposal["patterns"][0]["source_case_refs"] = ["case:poison-bow-1"]
    _write_json(proposal_path, proposal)
    _write_json(coverage_path, _coverage_report())

    report = pattern_bootstrap.build_phase4_pattern_bootstrap_report(
        manifest_file=manifest_path,
        proposal_file=proposal_path,
        source_coverage_report=coverage_path,
        db_path=tmp_path / "memory.sqlite",
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        min_samples=8,
        max_samples=10,
        min_families=2,
        max_families=3,
        min_samples_per_family=1,
    )

    assert report["status"] == "rejected_bootstrap_evidence_mismatch"
    assert report["patternWrite"]["attempted"] is False
    assert report["errorCode"] == "pattern_sample_count_exceeds_pattern_refs"


def test_pattern_bootstrap_rejects_raw_markers_in_manifest(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    proposal_path = tmp_path / "proposal.json"
    coverage_path = tmp_path / "coverage.json"
    manifest = _manifest()
    manifest["samples"][0]["sampleId"] = "https://pobb.in/copy"
    _write_json(manifest_path, manifest)
    _write_json(proposal_path, _proposal())
    _write_json(coverage_path, _coverage_report())

    report = pattern_bootstrap.build_phase4_pattern_bootstrap_report(
        manifest_file=manifest_path,
        proposal_file=proposal_path,
        source_coverage_report=coverage_path,
        db_path=tmp_path / "memory.sqlite",
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        min_samples=8,
        max_samples=10,
        min_families=2,
        max_families=3,
        min_samples_per_family=1,
    )

    assert report["status"] == "rejected_unsafe_bootstrap_manifest"
    assert report["patternWrite"]["attempted"] is False


def _manifest():
    return {
        "reportId": "phase4-pattern-bootstrap-manifest-v1",
        "safeArtifactOnly": True,
        "samples": [
            *_samples("poison-bow", 1, 4),
            *_samples("minion-spirit", 5, 8),
        ],
    }


def _samples(family: str, first: int, last: int):
    return [
        {
            "sampleId": f"case:{family}-{index}",
            "buildFamilyKey": family,
            "sourceDiversityKey": f"source:author-{index}",
            "guideVariantKey": f"variant:{family}-{index}",
        }
        for index in range(first, last + 1)
    ]


def _proposal():
    return {
        "schema_version": 4,
        "build_design_observations": [
            {
                "observation_type": "cooccurrence",
                "title": "Poison bow shell observation",
                "summary": "Observed bow shell with active skill and support modifier.",
                "axes": ["character_shell", "primary_skill_package", "scaling_axis"],
                "components": [
                    {
                        "component_key": "skill:LightningArrowPlayer",
                        "role": "primary_damage",
                        "resolution": _resolution("skill:LightningArrowPlayer"),
                    },
                    {
                        "component_key": "support:Scattershot",
                        "role": "support_modifier",
                        "resolution": _resolution("support:Scattershot"),
                    },
                ],
                "source_case_refs": [
                    "case:poison-bow-1",
                    "case:poison-bow-2",
                    "case:poison-bow-3",
                    "case:poison-bow-4",
                    "case:minion-spirit-5",
                    "case:minion-spirit-6",
                    "case:minion-spirit-7",
                    "case:minion-spirit-8",
                ],
                "safe_evidence_refs": ["safe:bootstrap-pattern"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
        "patterns": [
            {
                "pattern_type": "cooccurrence",
                "title": "Projectile primary plus support modifier",
                "summary": "Common within archetype only when the manifest count supports it.",
                "component_keys": ["skill:LightningArrowPlayer", "support:Scattershot"],
                "component_roles": {
                    "skill:LightningArrowPlayer": "primary_damage",
                    "support:Scattershot": "support_modifier",
                },
                "confidence_tier": "common_within_archetype",
                "sample_count": 8,
                "family_count": 2,
                "source_diversity_count": 8,
                "denominator": 8,
                "source_case_refs": [
                    "case:poison-bow-1",
                    "case:poison-bow-2",
                    "case:poison-bow-3",
                    "case:poison-bow-4",
                    "case:minion-spirit-5",
                    "case:minion-spirit-6",
                    "case:minion-spirit-7",
                    "case:minion-spirit-8",
                ],
                "safe_evidence_refs": ["safe:bootstrap-pattern"],
                "context_requirements": [
                    {"context_type": "verification_gate_requirement", "task": "Verify in Judge."},
                    {
                        "context_type": "agent_semantic_scope_review",
                        "evidence_scope": "multi_family",
                        "claim_scope": "population_pattern",
                        "verdict": "supported",
                        "reason": "The external reviewer confirmed the manifest supports this population-level wording.",
                        "safe_evidence_refs": ["safe:bootstrap-pattern"],
                    },
                ],
                "planner_hint": "Try this only as advisory search-space guidance.",
                "verification_tasks": ["Verify in Judge."],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
    }


def _coverage_report():
    return {
        "reportId": "phase4-local-physical-graph-snapshot-v1",
        "safeArtifactOnly": True,
        "coverageGate": {
            "readyForMaturePatternBootstrap": True,
            "missingCoverage": [],
            "requiredNodeTypes": [
                "active_skill",
                "ascendancy",
                "keystone",
                "notable",
                "passive",
                "support_gem",
                "unique",
            ],
        },
        "nodeTypeCounts": {
            "active_skill": 2,
            "ascendancy": 1,
            "keystone": 1,
            "notable": 1,
            "passive": 1,
            "support_gem": 1,
            "unique": 1,
        },
    }


def _resolution(stable_key):
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": stable_key,
        "snapshot_id": "snapshot:phase45",
        "evidence_path_nodes": [stable_key],
        "source_refs": ["fixture:phase45"],
    }


def _write_snapshot_index(tmp_path):
    source = pg.GraphSource(
        source_id="fixture:phase45",
        kind="test_fixture",
        source_file="tests/test_phase4_pattern_bootstrap.py",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
    )
    nodes = (
        pg.GraphNode(
            "skill:LightningArrowPlayer", "active_skill", "Lightning Arrow", (source.source_id,)
        ),
        pg.GraphNode("support:Scattershot", "support_gem", "Scattershot", (source.source_id,)),
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="snapshot:phase45",
        created_at=datetime(2026, 7, 6, tzinfo=UTC),
        sources=(source,),
        nodes=nodes,
        edges=(),
    )
    snapshot_path = tmp_path / "snapshot.json"
    index_path = tmp_path / "snapshot_index.sqlite"
    pg.save_snapshot(snapshot, snapshot_path)
    pg.register_snapshot(index_path, snapshot, snapshot_path)
    return index_path


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
