from __future__ import annotations

from datetime import UTC, datetime
import json

from scripts import build_phase4_architect_research_context as architect_context
from server.knowledge import graph_tools as gt
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


def test_architect_context_returns_safe_fragments_edges_and_used_ids(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        graph_service=_graph_service(),
    )
    query_ref = service.query_research_memory(
        "Hollow Focus cooldown gate",
        component_keys=["skill:HollowFocusPlayer"],
    )["dedupeQueryRef"]
    fragment_result = service.propose_research_fragments(
        _fragment_payload(),
        dedupe_query_ref=query_ref,
    )
    edge_result = service.propose_semantic_edges(_edge_payload())
    pattern_result = service.propose_build_patterns(_pattern_payload())

    report = architect_context.build_architect_research_context_report(
        db_path=db_path,
        query="Hollow Focus cooldown gate",
        component_keys=["skill:HollowFocusPlayer"],
    )

    assert report["status"] == "ready_for_phase5_architect_context"
    assert report["safeArtifactOnly"] is True
    assert report["usedMemoryItemIds"] == fragment_result["fragmentIds"]
    assert report["usedFragmentIds"] == fragment_result["fragmentIds"]
    assert report["usedSemanticEdgeIds"] == edge_result["edgeIds"]
    assert report["usedPatternIds"] == pattern_result["patternIds"]
    assert report["buildPatterns"][0]["patternType"] == "cooccurrence"
    assert report["buildPatterns"][0]["confidenceTier"] == "case_observation"
    assert report["plannerHints"]
    assert report["researchFragments"][0]["title"] == "Hollow Focus cooldown gate"
    assert report["semanticEdges"][0]["edgeType"] == "requires_transition_gate"
    assert report["semanticEdges"][0]["plannerVisible"] is True
    assert report["semanticEdges"][0]["contextRequirements"]
    assert report["semanticEdges"][0]["gamePatch"] == "0.5.4"
    assert report["semanticEdges"][0]["passiveTreeVersion"] == "0_5"
    assert report["semanticEdges"][0]["pobVersionOrCommit"] == "unknown"
    assert report["semanticEdges"][0]["currentVersionContext"]["game_patch"] == "0.5.4"
    assert report["modelabilityCaveats"]
    assert report["transitionGates"]
    assert report["verificationTasks"]

    serialized = json.dumps(report, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_architect_context_keeps_stale_edges_as_caveats_not_used_ids(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        graph_service=_graph_service(),
    )
    service.propose_semantic_edges(_edge_payload())
    service.apply_patch_decay(
        changed_component_keys=["support:Metadata/Items/Gems/SupportGemIngenuityTwo"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )

    report = architect_context.build_architect_research_context_report(
        db_path=db_path,
        query="Hollow Focus cooldown gate",
        component_keys=["skill:HollowFocusPlayer"],
    )

    assert report["usedSemanticEdgeIds"] == []
    assert report["semanticEdges"] == []
    assert "stale_or_revalidation_edges_excluded" in report["contextCaveats"]


def test_architect_context_excludes_retired_programmatic_patterns(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        graph_service=_graph_service(),
    )
    accepted = service.propose_build_patterns(_pattern_payload())
    service.apply_patch_decay(
        changed_component_keys=["skill:HollowFocusPlayer"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )

    report = architect_context.build_architect_research_context_report(
        db_path=db_path,
        query="Hollow Focus cooldown package",
        component_keys=["skill:HollowFocusPlayer"],
    )

    assert accepted["patternIds"]
    assert report["usedPatternIds"] == []
    assert report["buildPatterns"] == []
    assert "stale_or_revalidation_patterns_excluded" in report["contextCaveats"]


def test_architect_context_does_not_return_all_edges_for_empty_context_scope(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        graph_service=_graph_service(),
    )
    accepted = service.propose_semantic_edges(_edge_payload())

    report = architect_context.build_architect_research_context_report(
        db_path=db_path,
        query="unmatched architect handoff phrase",
        component_keys=[],
    )

    assert accepted["edgeIds"]
    assert report["usedSemanticEdgeIds"] == []
    assert report["semanticEdges"] == []


def test_architect_context_uses_component_key_fallback_when_query_has_no_text_hit(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        graph_service=_graph_service(),
    )
    query_ref = service.query_research_memory(
        "Hollow Focus cooldown gate",
        component_keys=["skill:HollowFocusPlayer"],
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(
        _fragment_payload(),
        dedupe_query_ref=query_ref,
    )

    report = architect_context.build_architect_research_context_report(
        db_path=db_path,
        query="unmatched architect handoff phrase",
        component_keys=["skill:HollowFocusPlayer"],
    )

    assert report["usedFragmentIds"] == accepted["fragmentIds"]
    assert report["researchFragments"][0]["componentKeys"] == ["skill:HollowFocusPlayer"]


def test_architect_context_adds_component_key_fragments_even_when_query_hits_other_text(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    hollow_ref = service.query_research_memory(
        "Hollow Focus cooldown gate",
        component_keys=["skill:HollowFocusPlayer"],
    )["dedupeQueryRef"]
    hollow = service.propose_research_fragments(
        _fragment_payload(title="Hollow Focus cooldown gate"),
        dedupe_query_ref=hollow_ref,
    )
    crossbow_ref = service.query_research_memory(
        "Crossbow Shot ammo rotation",
        component_keys=["skill:MeleeCrossbowPlayer"],
    )["dedupeQueryRef"]
    crossbow = service.propose_research_fragments(
        _fragment_payload(
            title="Crossbow Shot ammo rotation",
            component_keys=["skill:MeleeCrossbowPlayer"],
        ),
        dedupe_query_ref=crossbow_ref,
    )

    report = architect_context.build_architect_research_context_report(
        db_path=db_path,
        query="Hollow Focus cooldown gate",
        component_keys=["skill:HollowFocusPlayer", "skill:MeleeCrossbowPlayer"],
    )

    assert set(report["usedFragmentIds"]) == set(hollow["fragmentIds"] + crossbow["fragmentIds"])
    assert {tuple(item["componentKeys"]) for item in report["researchFragments"]} == {
        ("skill:HollowFocusPlayer",),
        ("skill:MeleeCrossbowPlayer",),
    }


def test_architect_context_dedupes_fragments_by_component_and_type(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    first_ref = service.query_research_memory(
        "Hollow Focus cooldown gate first",
        component_keys=["skill:HollowFocusPlayer"],
    )["dedupeQueryRef"]
    first = service.propose_research_fragments(
        _fragment_payload(title="Hollow Focus cooldown gate first"),
        dedupe_query_ref=first_ref,
    )
    second_ref = service.query_research_memory(
        "Hollow Focus cooldown gate second",
        component_keys=["skill:HollowFocusPlayer"],
    )["dedupeQueryRef"]
    second = service.propose_research_fragments(
        _fragment_payload(title="Hollow Focus cooldown gate second"),
        dedupe_query_ref=second_ref,
    )

    report = architect_context.build_architect_research_context_report(
        db_path=db_path,
        query="Hollow Focus cooldown gate first second",
        component_keys=["skill:HollowFocusPlayer"],
    )

    assert first["fragmentIds"]
    assert second["fragmentIds"]
    assert len(report["usedFragmentIds"]) == 1
    assert report["researchFragments"][0]["componentKeys"] == ["skill:HollowFocusPlayer"]


def test_architect_context_writes_safe_json_and_markdown(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    query_ref = service.query_research_memory("Hollow Focus cooldown", component_keys=[])[
        "dedupeQueryRef"
    ]
    service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    output_json = tmp_path / "context.json"
    output_md = tmp_path / "context.md"

    report = architect_context.write_architect_research_context_report(
        db_path=db_path,
        query="Hollow Focus cooldown",
        component_keys=[],
        json_output=output_json,
        md_output=output_md,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    markdown = output_md.read_text(encoding="utf-8")
    assert "Phase 4 Architect Research Context" in markdown
    assert "Hollow Focus cooldown gate" in markdown
    assert "Build Patterns" in markdown
    assert "Planner Hints" in markdown
    assert "Verification Tasks" in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)


def test_architect_context_cli_succeeds_with_pattern_only_context(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    pattern_result = service.propose_build_patterns(_pattern_payload())
    output_json = tmp_path / "context.json"
    output_md = tmp_path / "context.md"

    exit_code = architect_context.main(
        [
            "--db-path",
            str(db_path),
            "--query",
            "Hollow Focus cooldown package",
            "--component-key",
            "skill:HollowFocusPlayer",
            "--json-output",
            str(output_json),
            "--md-output",
            str(output_md),
        ]
    )

    assert exit_code == 0
    report = json.loads(output_json.read_text(encoding="utf-8"))
    assert report["usedPatternIds"] == pattern_result["patternIds"]
    assert report["usedFragmentIds"] == []
    assert report["usedSemanticEdgeIds"] == []


def _fragment_payload(
    title: str = "Hollow Focus cooldown gate",
    component_keys: list[str] | None = None,
):
    component_keys = component_keys or ["skill:HollowFocusPlayer"]
    return {
        "schema_version": 4,
        "fragments": [
            {
                "fragment_type": "mechanism_pattern",
                "title": title,
                "summary": "Use Hollow Focus only after cooldown and charge cadence are verified.",
                "reusable_principle": "Treat mature Hollow Focus as a gated endgame mechanism.",
                "source_case_refs": ["case:phase4_user_pob_001"],
                "safe_evidence_refs": ["safe:architect-context"],
                "confidence": "medium",
                "copyability_risk": "low",
                "lifecycle_stages": ["endgame_final"],
                "modelability": "partial",
                "verification_tasks": ["Verify cooldown and charge cadence in Judge."],
                "component_keys": component_keys,
                "conditions": ["Transition requires cooldown gate."],
                "risks": ["Do not use as starter proof."],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
        "semantic_edges": [],
    }


def _edge_payload():
    return {
        "schema_version": 4,
        "fragments": [],
        "semantic_edges": [
            {
                "source_key": "skill:HollowFocusPlayer",
                "target_key": "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
                "source_resolution": _resolution("skill:HollowFocusPlayer"),
                "target_resolution": _resolution(
                    "support:Metadata/Items/Gems/SupportGemIngenuityTwo"
                ),
                "edge_type": "requires_transition_gate",
                "rationale": "Cooldown support-like endpoint is a gated mature-engine requirement.",
                "source_case_refs": ["case:phase4_user_pob_001"],
                "safe_evidence_refs": ["safe:architect-context-edge"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "status": "valid",
                "confidence": "medium",
                "modelability": "partial",
                "copy_safety_state": "passed",
                "context_requirements": [
                    {
                        "context_type": "verification_gate_requirement",
                        "task": "Verify cooldown gate before planner use.",
                    }
                ],
                "affected_component_keys": [
                    "skill:HollowFocusPlayer",
                    "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
                ],
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
                "directionality": "directional",
            }
        ],
    }


def _pattern_payload():
    return {
        "schema_version": 4,
        "fragments": [],
        "semantic_edges": [],
        "build_design_observations": [
            {
                "observation_type": "cooccurrence",
                "title": "Hollow Focus cooldown package",
                "summary": "Hollow Focus appears with a cooldown support-like endpoint as an observed gated package.",
                "axes": ["primary_skill_package", "mechanic_engine", "transition_gates"],
                "components": [
                    {
                        "component_key": "skill:HollowFocusPlayer",
                        "role": "primary_damage",
                        "resolution": _resolution("skill:HollowFocusPlayer"),
                    },
                    {
                        "component_key": "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
                        "role": "support_modifier",
                        "resolution": _resolution(
                            "support:Metadata/Items/Gems/SupportGemIngenuityTwo"
                        ),
                    },
                ],
                "source_case_refs": ["case:phase4_user_pob_001"],
                "safe_evidence_refs": ["safe:architect-context-pattern"],
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
                "title": "Hollow Focus cooldown package",
                "summary": "Observed case-level co-occurrence for planner exploration.",
                "component_keys": [
                    "skill:HollowFocusPlayer",
                    "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
                ],
                "component_roles": {
                    "skill:HollowFocusPlayer": "primary_damage",
                    "support:Metadata/Items/Gems/SupportGemIngenuityTwo": "support_modifier",
                },
                "confidence_tier": "case_observation",
                "sample_count": 1,
                "family_count": 1,
                "source_diversity_count": 1,
                "denominator": 1,
                "source_case_refs": ["case:phase4_user_pob_001"],
                "safe_evidence_refs": ["safe:architect-context-pattern"],
                "context_requirements": [
                    {
                        "context_type": "verification_gate_requirement",
                        "task": "Check cooldown package before treating as a mature pattern.",
                    }
                ],
                "planner_hint": "Try Hollow Focus cooldown package only as an advisory candidate.",
                "verification_tasks": [
                    "Check cooldown package before treating as a mature pattern."
                ],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
    }


def _resolution(stable_key):
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": stable_key,
        "snapshot_id": "snapshot:architect-context",
        "evidence_path_nodes": [stable_key],
        "source_refs": ["fixture:phase4"],
    }


def _graph_service() -> gt.GraphQueryService:
    source = pg.GraphSource(
        source_id="fixture:phase4",
        kind="test_fixture",
        source_file="tests/test_phase4_architect_context.py",
    )
    nodes = (
        pg.GraphNode(
            "skill:HollowFocusPlayer",
            "active_skill",
            "Hollow Focus",
            (source.source_id,),
        ),
        pg.GraphNode(
            "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
            "support_gem",
            "Cooldown Recovery II",
            (source.source_id,),
        ),
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="snapshot:architect-context",
        created_at=datetime(2026, 7, 4, tzinfo=UTC),
        sources=(source,),
        nodes=nodes,
        edges=(),
    )
    return gt.GraphQueryService.from_snapshot(snapshot)
