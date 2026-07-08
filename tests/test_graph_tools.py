from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess

from server import main
from server.knowledge import graph_tools as gt
from server.knowledge import physical_graph as pg


def _source() -> pg.GraphSource:
    return pg.GraphSource(
        source_id="fixture:graph_tools",
        kind="test_fixture",
        source_file="tests/test_graph_tools.py",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
    )


def _snapshot() -> pg.GraphSnapshot:
    source = _source()
    gem = pg.GraphNode(
        stable_key="gem:LightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Pierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support_skill = pg.GraphNode(
        stable_key="skill:SupportPiercePlayer",
        node_type="active_skill",
        display_name="Support Pierce",
        source_refs=(source.source_id,),
    )
    projectile_type = pg.GraphNode(
        stable_key="skill_type:projectile",
        node_type="skill_type",
        display_name="Projectile",
        source_refs=(source.source_id,),
    )
    item_base = pg.GraphNode(
        stable_key="item_base:LongBow",
        node_type="item_base",
        display_name="Long Bow",
        source_refs=(source.source_id,),
    )
    item_tag = pg.GraphNode(
        stable_key="tag:item:bow",
        node_type="item_tag",
        display_name="bow",
        source_refs=(source.source_id,),
    )
    mod = pg.GraphNode(
        stable_key="mod:BowDamage1",
        node_type="mod",
        display_name="Serrated",
        source_refs=(source.source_id,),
    )
    passive_a = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Weapon Set A",
        source_refs=(source.source_id,),
    )
    passive_mid = pg.GraphNode(
        stable_key="passive:pob:0_5:101",
        node_type="passive",
        display_name="Shared Middle",
        source_refs=(source.source_id,),
    )
    passive_b = pg.GraphNode(
        stable_key="passive:pob:0_5:102",
        node_type="passive",
        display_name="Weapon Set B",
        source_refs=(source.source_id,),
    )
    caveat = pg.GraphNode(
        stable_key="caveat:dual_weapon_state_limited_caveat",
        node_type="caveat",
        display_name="dual_weapon_state_limited_caveat",
        source_refs=(source.source_id,),
    )
    return pg.GraphSnapshot(
        snapshot_id="snapshot:graph-tools",
        created_at=datetime(2026, 7, 2, tzinfo=UTC),
        sources=(source,),
        nodes=(
            caveat,
            gem,
            item_base,
            item_tag,
            mod,
            passive_a,
            passive_b,
            passive_mid,
            projectile_type,
            skill,
            support,
            support_skill,
        ),
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=gem.stable_key,
                target_key=skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=support.stable_key,
                target_key=support_skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="granted_by",
                source_key=skill.stable_key,
                target_key=gem.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=projectile_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_tag",
                source_key=item_base.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="applies_to_tag",
                source_key=mod.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="connected_to",
                source_key=passive_a.stable_key,
                target_key=passive_mid.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="connected_to",
                source_key=passive_mid.stable_key,
                target_key=passive_b.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        aliases=(
            pg.GraphAlias("Lightning Arrow", gem.stable_key, (source.source_id,)),
            pg.GraphAlias("Lightning Arrow", skill.stable_key, (source.source_id,)),
        ),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:PassiveSkills",
                external_id="unsupported-passive",
                target_key=None,
                source_refs=(source.source_id,),
                status="unsupported",
                caveat="unsupported_official_id",
            ),
        ),
        requirement_facts=(
            pg.RequirementFact(
                component_key=gem.stable_key,
                level_or_stage="base",
                requirements={"level": 1, "dex": 9},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=item_base.stable_key,
                level_or_stage="base",
                requirements={"domain": "item"},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=mod.stable_key,
                level_or_stage="base",
                requirements={
                    "domain": "item",
                    "generation_type": "prefix",
                    "required_level": 1,
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=support_skill.stable_key,
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Projectile"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                    "support_family": "Pierce",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=passive_a.stable_key,
                level_or_stage="weapon_set_overlay",
                requirements={"allocation_states": ["weapon_set_1"]},
                source_refs=(source.source_id,),
                status="known",
            ),
            pg.RequirementFact(
                component_key=passive_b.stable_key,
                level_or_stage="weapon_set_overlay",
                requirements={"allocation_states": ["weapon_set_2"]},
                source_refs=(source.source_id,),
                status="known",
            ),
            pg.RequirementFact(
                component_key=caveat.stable_key,
                level_or_stage="component_set",
                requirements={
                    "component_keys": [passive_a.stable_key, passive_b.stable_key],
                    "trigger_condition": "cross_weapon_set_topology_request",
                    "modelability_effect": "limited",
                    "reward_eligibility_effect": "limited",
                },
                source_refs=(source.source_id,),
            ),
        ),
        resource_facts=(
            pg.ResourceFact(
                component_key=skill.stable_key,
                level_or_stage="1",
                costs={"mana": 6},
                reservations={},
                source_refs=(source.source_id,),
            ),
        ),
    )


def _service() -> gt.GraphQueryService:
    return gt.GraphQueryService.from_snapshot(_snapshot())


def test_resolve_graph_component_returns_ambiguous_with_source_backed_candidates():
    result = _service().run_tool(
        "resolve_graph_component",
        {"query": "Lightning Arrow"},
    )

    assert result["status"] == "ambiguous"
    assert result["snapshotId"] == "snapshot:graph-tools"
    assert result["noRawQuery"] is True
    assert {candidate["stableKey"] for candidate in result["facts"]["candidates"]} == {
        "gem:LightningArrow",
        "skill:LightningArrowPlayer",
    }
    assert result["sourceRefs"] == ["fixture:graph_tools"]


def test_resolve_graph_component_unknown_is_not_assessed_not_hallucinated():
    result = _service().run_tool(
        "resolve_graph_component",
        {"query": "Vivid Stampede"},
    )

    assert result["status"] == "missing"
    assert result["endpointAssessment"]["classification"] == "source_coverage_gap"
    assert result["endpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert result["facts"]["endpointAssessment"] == result["endpointAssessment"]


def test_invalid_schema_is_returned_as_public_error_without_traceback():
    result = _service().run_tool(
        "resolve_graph_component",
        {"query": "Lightning Arrow", "thought": "I should inspect this first"},
    )

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"
    assert result["noRawQuery"] is True
    assert "Traceback" not in str(result)
    assert "thought" in result["caveats"][0]


def test_socket_support_legality_requires_discriminated_socket_context():
    missing = _service().run_tool(
        "socket_support_legality",
        {"skill_key": "skill:LightningArrowPlayer", "support_key": "support:Pierce"},
    )
    invalid = _service().run_tool(
        "socket_support_legality",
        {
            "skill_key": "skill:LightningArrowPlayer",
            "support_key": "support:Pierce",
            "context": {"context_type": "passive_context", "active_weapon_set": 1},
        },
    )
    known = _service().run_tool(
        "socket_support_legality",
        {
            "skill_key": "skill:LightningArrowPlayer",
            "support_key": "support:Pierce",
            "context": {
                "context_type": "socket_context",
                "socketed_support_keys": [],
                "current_support_count": 0,
                "max_support_count": 2,
            },
        },
    )

    assert missing["status"] == "missing_context"
    assert missing["missingContext"] == ["socket_context"]
    assert invalid["status"] == "missing_context"
    assert invalid["contextCaveats"] == ["expected_socket_context"]
    assert known["status"] == "known"
    assert known["facts"]["legality_status"] == "socket_compatible"
    assert known["contextUsed"]["context_type"] == "socket_context"


def test_can_roll_mod_requires_item_context_and_rejects_raw_query_fields():
    missing = _service().run_tool(
        "can_roll_mod",
        {"base_item_key": "item_base:LongBow", "mod_key": "mod:BowDamage1"},
    )
    invalid = _service().run_tool(
        "can_roll_mod",
        {
            "base_item_key": "item_base:LongBow",
            "mod_key": "mod:BowDamage1",
            "raw_query": "MATCH (n) RETURN n",
            "context": {"context_type": "item_context", "item_level": 10},
        },
    )
    known = _service().run_tool(
        "can_roll_mod",
        {
            "base_item_key": "item_base:LongBow",
            "mod_key": "mod:BowDamage1",
            "context": {"context_type": "item_context", "item_level": 10},
        },
    )

    assert missing["status"] == "missing_context"
    assert missing["missingContext"] == ["item_context.item_level"]
    assert invalid["status"] == "error"
    assert invalid["errorCode"] == "invalid_schema"
    assert known["status"] == "known"
    assert known["facts"]["can_roll"] is True


def test_strict_schema_rejects_string_numbers_as_invalid_schema():
    result = _service().run_tool(
        "can_roll_mod",
        {
            "base_item_key": "item_base:LongBow",
            "mod_key": "mod:BowDamage1",
            "context": {"context_type": "item_context", "item_level": "10"},
        },
    )

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"
    assert "Traceback" not in str(result)


def test_nested_raw_query_keys_are_rejected_before_context_echo():
    result = _service().run_tool(
        "can_roll_mod",
        {
            "base_item_key": "item_base:LongBow",
            "mod_key": "mod:BowDamage1",
            "context": {
                "context_type": "build_state_context",
                "spirit_reservation_summary": {"SQL": "select * from graph"},
            },
        },
    )

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"
    assert "select * from graph" not in str(result)


def test_context_policy_rejects_wrong_context_slice_for_none_and_version_only_tools():
    none_policy = _service().run_tool(
        "resolve_graph_component",
        {
            "query": "Lightning Arrow",
            "context": {"context_type": "item_context", "item_level": 10},
        },
    )
    version_policy = _service().run_tool(
        "requirements_for_component",
        {
            "component_key": "gem:LightningArrow",
            "level_or_stage": "base",
            "context": {"context_type": "item_context", "item_level": 10},
        },
    )
    version_context = _service().run_tool(
        "requirements_for_component",
        {
            "component_key": "gem:LightningArrow",
            "level_or_stage": "base",
            "context": {"context_type": "version_context", "passive_tree_version": "0_5"},
        },
    )

    assert none_policy["status"] == "missing_context"
    assert none_policy["contextCaveats"] == ["unexpected_context"]
    assert version_policy["status"] == "missing_context"
    assert version_policy["contextCaveats"] == ["expected_version_context"]
    assert version_context["status"] == "known"
    assert version_context["contextUsed"]["context_type"] == "version_context"


def test_version_context_mismatch_returns_stale_result():
    result = _service().run_tool(
        "requirements_for_component",
        {
            "component_key": "gem:LightningArrow",
            "level_or_stage": "base",
            "context": {
                "context_type": "version_context",
                "passive_tree_version": "wrong_version",
            },
        },
    )

    assert result["status"] == "stale"
    assert result["contextCaveats"] == ["version_context_mismatch:passive_tree_version"]
    assert "version_context_mismatch" in result["caveats"]


def test_passive_topology_path_is_bounded_cached_and_reports_weapon_set_conflict():
    service = _service()
    path = service.run_tool(
        "find_passive_topology_path",
        {
            "start_key": "passive:pob:0_5:100",
            "end_key": "passive:pob:0_5:101",
            "hop_limit": 6,
            "context": {"context_type": "passive_context", "active_weapon_set": 1},
        },
    )
    conflict = service.run_tool(
        "find_passive_topology_path",
        {
            "start_key": "passive:pob:0_5:100",
            "end_key": "passive:pob:0_5:102",
            "hop_limit": 6,
            "context": {
                "context_type": "passive_context",
                "active_weapon_set": 1,
                "target_weapon_set": 2,
            },
        },
    )

    assert service.topology_build_count == 1
    assert path["status"] == "known"
    assert path["facts"]["path_keys"] == [
        "passive:pob:0_5:100",
        "passive:pob:0_5:101",
    ]
    assert "topology_only_path" in path["caveats"]
    assert conflict["status"] == "unsupported"
    assert conflict["facts"]["path_keys"] == []
    assert "conflicting_weapon_set_caveat" in conflict["caveats"]


def test_passive_topology_path_uses_bounded_search(monkeypatch):
    calls: dict[str, object] = {}

    def fail_unbounded_shortest_path(*args, **kwargs):
        raise AssertionError("unbounded shortest_path must not be used")

    original_single_source = gt.nx.single_source_shortest_path

    def record_single_source(*args, **kwargs):
        calls["cutoff"] = kwargs.get("cutoff")
        return original_single_source(*args, **kwargs)

    monkeypatch.setattr(gt.nx, "shortest_path", fail_unbounded_shortest_path)
    monkeypatch.setattr(gt.nx, "single_source_shortest_path", record_single_source)

    result = _service().run_tool(
        "find_passive_topology_path",
        {
            "start_key": "passive:pob:0_5:100",
            "end_key": "passive:pob:0_5:101",
            "hop_limit": 1,
            "context": {"context_type": "passive_context", "active_weapon_set": 1},
        },
    )

    assert result["status"] == "known"
    assert calls["cutoff"] == 1


def test_passive_subgraph_respects_node_limit_and_payload_limit():
    result = _service().run_tool(
        "get_passive_subgraph_in_radius",
        {
            "node_key": "passive:pob:0_5:101",
            "hop_limit": 6,
            "node_limit": 2,
            "context": {"context_type": "passive_context", "active_weapon_set": 1},
        },
    )

    assert result["status"] == "known"
    assert result["facts"]["truncated"] is True
    assert result["facts"]["node_count"] == 2
    assert result["facts"]["payload_bytes"] <= 65536


def test_passive_subgraph_payload_limit_applies_to_public_envelope():
    source = _source()
    nodes = [
        pg.GraphNode(
            stable_key=f"passive:pob:0_5:{index}",
            node_type="passive",
            display_name="Long Passive Node Name " + ("x" * 500),
            source_refs=(source.source_id,),
        )
        for index in range(1, 151)
    ]
    edges = [
        pg.GraphEdge(
            edge_type="connected_to",
            source_key=nodes[0].stable_key,
            target_key=nodes[index].stable_key,
            evidence_refs=(source.source_id,),
        )
        for index in range(1, len(nodes))
    ]
    service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:large-subgraph",
            created_at=datetime(2026, 7, 2, tzinfo=UTC),
            sources=(source,),
            nodes=tuple(nodes),
            edges=tuple(edges),
        )
    )

    result = service.run_tool(
        "get_passive_subgraph_in_radius",
        {
            "node_key": nodes[0].stable_key,
            "hop_limit": 1,
            "node_limit": 150,
            "context": {"context_type": "passive_context", "active_weapon_set": 1},
        },
    )
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")

    assert result["status"] == "known"
    assert len(encoded) <= 65536
    assert result["facts"]["truncated"] is True
    assert result["evidencePath"]["nodes"] == [
        node["stableKey"] for node in result["facts"]["nodes"]
    ]


def test_build_planner_id_resolve_reports_unsupported_mapping_structurally():
    result = _service().run_tool(
        "build_planner_id_resolve",
        {"system": "ggg:PassiveSkills", "external_id": "unsupported-passive"},
    )

    assert result["status"] == "unsupported"
    assert result["resolvedSubject"] is None
    assert result["caveats"] == ["unsupported_official_id"]


def test_graph_tool_query_wraps_snapshot_load_failures(monkeypatch):
    def fail_service():
        raise FileNotFoundError("missing snapshot json")

    monkeypatch.setattr(main, "_graph_query_service", fail_service)

    result = main.graph_tool_query("resolve_graph_component", {"query": "Lightning Arrow"})

    assert result["status"] == "error"
    assert result["errorCode"] == "graph_snapshot_unavailable"
    assert result["endpointAssessment"]["classification"] == "graph_snapshot_unavailable"
    assert result["endpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert result["facts"]["endpointAssessment"] == result["endpointAssessment"]
    assert result["noRawQuery"] is True
    assert "Traceback" not in str(result)


def test_cached_service_refreshes_when_latest_snapshot_registration_changes(tmp_path):
    source = _source()
    first = pg.GraphSnapshot(
        snapshot_id="snapshot:first",
        created_at=datetime(2026, 7, 2, tzinfo=UTC),
        sources=(source,),
        nodes=(
            pg.GraphNode(
                stable_key="gem:First",
                node_type="skill_gem",
                display_name="First",
                source_refs=(source.source_id,),
            ),
        ),
        edges=(),
    )
    second = pg.GraphSnapshot(
        snapshot_id="snapshot:second",
        created_at=datetime(2026, 7, 2, 1, tzinfo=UTC),
        sources=(source,),
        nodes=(
            pg.GraphNode(
                stable_key="gem:Second",
                node_type="skill_gem",
                display_name="Second",
                source_refs=(source.source_id,),
            ),
        ),
        edges=(),
    )
    index_path = tmp_path / "snapshots.sqlite"
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    pg.save_snapshot(first, first_path)
    pg.save_snapshot(second, second_path)
    pg.register_snapshot(index_path, first, first_path)
    gt.clear_service_cache()
    first_service = gt.service_from_snapshot_index(str(index_path))
    pg.register_snapshot(index_path, second, second_path)
    second_service = gt.service_from_snapshot_index(str(index_path))

    assert first_service.snapshot.snapshot_id == "snapshot:first"
    assert second_service.snapshot.snapshot_id == "snapshot:second"
    assert first_service is not second_service


def test_run_phase3_graph_tool_benchmark_script_writes_artifacts():
    repo_root = Path(__file__).resolve().parents[1]
    output_path = repo_root / "phase3_graph_tool_benchmark.json"
    report_path = repo_root / "phase3_graph_tool_benchmark.md"
    previous_payload = output_path.read_text(encoding="utf-8") if output_path.exists() else None
    previous_report = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    try:
        result = subprocess.run(
            [
                str(repo_root / ".tools" / "uv" / "uv.exe"),
                "run",
                "python",
                "scripts/run_phase3_graph_tool_benchmark.py",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )

        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["benchmark_id"] == "phase3_typed_graph_tools_v1"
        assert payload["pass"] is True
        assert payload["expected_status_match_rate"] == 1.0
        assert payload["case_counts_by_status"]["unknown"] >= 1
        assert payload["case_counts_by_status"]["stale"] >= 1
        assert payload["hallucinated_compatibility_count"] == 0
        sample_by_id = {sample["id"]: sample for sample in payload["samples"]}
        assert sample_by_id["support_candidate_unsupported"]["result"]["status"] == "unsupported"
        assert sample_by_id["resource_unknown_stage"]["result"]["status"] == "unknown"
        assert sample_by_id["requirements_stale_context"]["result"]["status"] == "stale"
        assert (
            sample_by_id["support_candidate_unsupported"]["result"]["facts"]["candidate_status"]
            == "unsupported"
        )
        assert payload["topology_limit_failures"] == []
        assert payload["ready_for_human_review"] is True
        assert payload["ready_for_phase3_exit"] is False
        report_text = report_path.read_text(encoding="utf-8")
        assert "# Phase 3 Typed Graph Tool Benchmark" in report_text
        assert "hallucinated_compatibility_count：0" in report_text
        assert str(output_path) in result.stdout
        assert str(report_path) in result.stdout
    finally:
        if previous_payload is None:
            if output_path.exists():
                output_path.unlink()
        else:
            output_path.write_bytes(previous_payload.encode("utf-8"))
        if previous_report is None:
            if report_path.exists():
                report_path.unlink()
        else:
            report_path.write_bytes(previous_report.encode("utf-8"))
