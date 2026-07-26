"""Server-surface tests: the assistant-facing cohesion layer (instructions + prompts).

These guard the MCP `instructions` channel and the workflow prompts — the only guidance the
LLM client receives beyond per-tool docstrings. They run without booting the engine.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from server.main import mcp


def test_instructions_are_delivered():
    instr = mcp.instructions or ""
    # Sourced from server/ASSISTANT_GUIDE.md; must actually reach the client, not be empty.
    assert len(instr) > 500
    assert "Path of Exile 2" in instr
    # The cardinal rule has to survive — it's why answers stay grounded in the engine.
    assert "never" in instr.lower() and "engine" in instr.lower()
    # Phase 3 lifecycle guidance must reach the client: strong endgame builds may need a
    # separate starter route and explicit transition gates.
    assert "lifecycle" in instr.lower()
    assert "transition gate" in instr.lower()


def test_workflow_prompts_registered():
    prompts = {p.name for p in asyncio.run(mcp.list_prompts())}
    assert {
        "start_build_session",
        "analyze_build",
        "build_from_goal",
        "audit_defenses",
        "research_mature_build_case",
    } <= prompts


def test_research_mature_build_case_prompt_is_tool_driven():
    from server import main

    packet = {
        "packetId": "rp-test",
        "safeHash": "abc123",
        "safeMetadata": {"case_id": "case-lightning-arrow"},
        "rawContext": {"pobCode": "eNrt" + "A" * 180},
        "requestedOutputSchema": "ResearcherOutput schema_version=5",
    }

    text = main.research_mature_build_case(
        packet_json=json.dumps(packet),
        current_patch="0.5.4",
        passive_tree_version="0_5",
    )

    assert "MUST NOT output the final JSON as regular text" in text
    assert "Independently Reconstruct the Current Build" in text
    assert "Do not query durable memory until that initial working model is complete" in text
    assert "query_research_memory" in text
    assert "graph_tool_query" in text
    assert "resolve_graph_component" in text
    assert "propose_research_fragments" in text
    assert "propose_deep_research_records" in text
    assert "propose_semantic_edges" in text


def test_research_mature_build_case_requires_real_packet_json():
    from server import main

    text = main.research_mature_build_case()

    assert "Call build_research_packet first" in text
    assert "Begin immediately with STEP 1" not in text


def test_tool_surface_intact():
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 140
    names = {t.name for t in tools}
    assert {
        "list_jewel_sockets",
        "list_skill_groups",
        "replace_skill_group",
        "remove_skill_group",
        "set_skill_group_state",
        "inspect_build_completeness",
        "inspect_generation_preflight",
        "equip_jewel",
        "apply_combat_profile",
        "pinnacle_readiness",
        "evaluate_generation_candidate",
        "save_final_build_artifact",
        "list_final_build_artifacts",
        "load_final_build_artifact",
        "export_final_pob_artifact",
        "export_final_build_package",
        "save_build_progression_route",
        "list_build_progression_routes",
        "load_build_progression_stage",
        "start_build_progression",
        "intake_starter_research_packet",
        "submit_build_progression_blueprint",
        "revise_future_build_progression_stages",
        "claim_build_progression_stage",
        "bind_build_progression_stage_run",
        "complete_build_progression_stage",
        "fail_build_progression_stage",
        "retry_build_progression_stage",
        "pause_build_progression",
        "resume_build_progression",
        "get_build_progression_status",
        "classify_build_progression_costs",
        "finalize_build_progression",
        "export_build_progression_package",
        "get_build_planner_converter_status",
        "export_final_build_artifact",
        "list_reference_builds",
        "benchmark_build",
        "rank_upgrades",
        "optimize_supports",
        "optimize_jewel",
        "plan_gear",
        "relevant_uniques",
        "optimize_build",
        "craft_item",
        "get_freshness_report",
        "suggest_build_lifecycle",
        "analyze_build_lifecycle",
        "compare_lifecycle_routes",
        "list_transition_gates",
        "record_build_feedback",
        "promote_technique_memory",
        "analyze_lifecycle_cohort",
        "evaluate_transition_readiness",
        "plan_lifecycle_stage_verification",
        "verify_lifecycle_stage",
        "audit_lifecycle_route",
        "evaluate_lifecycle_route",
        "get_meta_archetype_trends",
        "graph_tool_query",
        "build_research_packet",
        "validate_researcher_output",
        "query_research_memory",
        "propose_research_fragments",
        "propose_deep_research_records",
        "append_evidence_to_fragment",
        "propose_semantic_edges",
        "propose_build_patterns",
        "submit_revalidation_result",
        "inspect_rejected_research_proposals",
        "start_learning_campaign",
        "intake_learning_case",
        "claim_learning_phase",
        "load_learning_reference_case",
        "submit_learning_profile",
        "get_learning_create_packet",
        "query_learning_memory",
        "submit_learning_create_result",
        "submit_learning_comparison",
        "propose_learning_lesson",
        "append_learning_memory_correction",
        "complete_learning_case_feedback",
        "submit_learning_rereview",
        "fail_learning_phase",
        "retry_learning_phase",
        "pause_learning_campaign",
        "resume_learning_campaign",
        "get_learning_campaign_status",
    } <= names


def test_progression_tools_publish_nested_typed_input_schemas():
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    start_schema = tools["start_build_progression"].inputSchema
    assert start_schema["properties"]["version_context"] == {"$ref": "#/$defs/VersionContext"}
    version_properties = start_schema["$defs"]["VersionContext"]["properties"]
    assert "trade/SSF mode belongs" in version_properties["ruleset"]["description"]
    assert (
        "StageCreatePacket value verbatim" in version_properties["researchMemoryRef"]["description"]
    )
    packet_schema = tools["intake_starter_research_packet"].inputSchema
    assert packet_schema["properties"]["packet"] == {"$ref": "#/$defs/StarterResearchSubmission"}
    assert (
        packet_schema["$defs"]["StarterSourceInput"]["properties"]["explicitLevelBands"]["type"]
        == "boolean"
    )
    blueprint_schema = tools["submit_build_progression_blueprint"].inputSchema
    assert blueprint_schema["properties"]["blueprint"] == {"$ref": "#/$defs/ProgressionBlueprint"}
    assert "targetIntent" in blueprint_schema["$defs"]["ProgressionBlueprint"]["properties"]
    cost_schema = tools["classify_build_progression_costs"].inputSchema
    assert cost_schema["properties"]["cost_request"] == {"$ref": "#/$defs/CostRequest"}
    completion_schema = tools["complete_build_progression_stage"].inputSchema
    assert completion_schema["properties"]["completion_report"] == {
        "$ref": "#/$defs/StageCompletionReport"
    }
    lifecycle_schema = tools["verify_lifecycle_stage"].inputSchema
    assert lifecycle_schema["properties"]["state"] == {
        "anyOf": [
            {"$ref": "#/$defs/LifecycleStageVerificationState"},
            {"type": "null"},
        ],
        "default": None,
    }
    lifecycle_state = lifecycle_schema["$defs"]["LifecycleStageVerificationState"]
    assert "singleTargetSkillName" in lifecycle_state["properties"]
    assert "singleTargetEvidenceRefs" in lifecycle_state["properties"]
    assert "buildDefiningComponentKind" in lifecycle_state["properties"]
    assert "buildDefiningComponentName" in lifecycle_state["properties"]
    assert "buildDefiningComponentKey" in lifecycle_state["properties"]
    assert "buildDefiningEvidenceRefs" in lifecycle_state["properties"]


def test_graph_tool_query_exposes_typed_payload_schema():
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    schema = tools["graph_tool_query"].inputSchema

    assert schema["properties"]["tool_name"]["type"] == "string"
    assert schema["properties"]["payload"]["type"] == "object"
    assert set(schema["required"]) == {"tool_name", "payload"}


def test_freshness_report_tool_exposes_force_refresh_schema():
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    schema = tools["get_freshness_report"].inputSchema

    assert schema["properties"]["force_refresh"]["type"] == "boolean"
    assert schema["properties"]["force_refresh"]["default"] is False


def test_mcp_tool_call_routes_compute_to_current_session(monkeypatch):
    from server import main

    session = type("Session", (), {})()
    captured: dict[str, object] = {}

    class Pool:
        def get(self, owner):
            captured["session"] = owner
            return type("Engine", (), {"get_stats": lambda self, keys: {"stats": {}}})()

    monkeypatch.setattr(main, "_engine_pool", Pool())
    monkeypatch.setattr(main.mcp, "get_context", lambda: SimpleNamespace(session=session))

    asyncio.run(main.mcp.call_tool("get_build_stats", {}))

    assert captured["session"] is session


def test_graph_tool_query_forwards_to_cached_service(monkeypatch):
    from server import main

    captured: dict[str, object] = {}

    class FakeGraphService:
        def run_tool(self, tool_name, payload):
            captured["tool_name"] = tool_name
            captured["payload"] = payload
            return {"status": "known", "noRawQuery": True}

    monkeypatch.setattr(main, "_graph_query_service", lambda: FakeGraphService())

    result = main.graph_tool_query("resolve_graph_component", {"query": "Lightning Arrow"})

    assert result == {"status": "known", "noRawQuery": True}
    assert captured == {
        "tool_name": "resolve_graph_component",
        "payload": {"query": "Lightning Arrow"},
    }


def test_research_memory_tools_expose_public_schemas():
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    assert tools["build_research_packet"].inputSchema["properties"]["case"]["type"] == "object"
    assert (
        tools["validate_researcher_output"].inputSchema["properties"]["payload"]["type"] == "object"
    )
    assert tools["query_research_memory"].inputSchema["properties"]["query"]["type"] == "string"
    assert (
        tools["query_research_memory"].inputSchema["properties"]["detail_level"]["type"] == "string"
    )
    assert {
        "ascendancy_key",
        "primary_skill_key",
        "build_family_keys",
        "record_kinds",
    } <= set(tools["query_research_memory"].inputSchema["properties"])
    assert (
        tools["propose_deep_research_records"].inputSchema["properties"]["payload"]["type"]
        == "object"
    )
    assert (
        tools["propose_research_fragments"].inputSchema["properties"]["payload"]["type"] == "object"
    )
    assert (
        tools["append_evidence_to_fragment"].inputSchema["properties"]["fragment_id"]["type"]
        == "string"
    )
    assert tools["propose_semantic_edges"].inputSchema["properties"]["payload"]["type"] == "object"
    assert tools["propose_build_patterns"].inputSchema["properties"]["payload"]["type"] == "object"
    assert (
        tools["submit_revalidation_result"].inputSchema["properties"]["target_kind"]["type"]
        == "string"
    )


def test_research_memory_tool_adapters_forward_to_service(monkeypatch):
    from server import main

    calls: list[tuple[str, object]] = []

    class FakeResearchService:
        def query_research_memory(
            self,
            query,
            *,
            component_keys=None,
            limit=10,
            detail_level="summary",
            record_ids=None,
            include_transferable=False,
            research_axes=None,
            ascendancy_key=None,
            primary_skill_key=None,
            build_family_keys=None,
            record_kinds=None,
        ):
            calls.append(
                (
                    "query",
                    (
                        query,
                        component_keys,
                        limit,
                        detail_level,
                        record_ids,
                        include_transferable,
                        research_axes,
                        ascendancy_key,
                        primary_skill_key,
                        build_family_keys,
                        record_kinds,
                    ),
                )
            )
            return {"status": "known", "noRawMatureBuildMaterial": True}

        def validate_deep_research_records(self, payload):
            calls.append(("deep_records", payload))
            return {"status": "accepted", "noRawMatureBuildMaterial": True}

        def validate_research_fragments(self, payload, *, dedupe_query_ref=None):
            calls.append(("fragments", (payload, dedupe_query_ref)))
            return {"status": "accepted", "noRawMatureBuildMaterial": True}

        def append_evidence_to_fragment(self, **kwargs):
            calls.append(("append", kwargs))
            return {"status": "accepted", "noRawMatureBuildMaterial": True}

        def validate_semantic_edges(self, payload):
            calls.append(("edges", payload))
            return {"status": "accepted", "noRawMatureBuildMaterial": True}

        def validate_build_patterns(self, payload):
            calls.append(("patterns", payload))
            return {"status": "accepted", "noRawMatureBuildMaterial": True}

        def submit_revalidation_result(self, **kwargs):
            calls.append(("revalidate", kwargs))
            return {"status": "accepted", "noRawMatureBuildMaterial": True}

    monkeypatch.setattr(main, "_research_memory_service", lambda: FakeResearchService())
    monkeypatch.setattr(main, "_research_memory_service_with_graph", lambda: FakeResearchService())

    assert (
        main.query_research_memory(
            "projectile",
            ["skill:LightningArrowPlayer"],
            5,
            ascendancy_key="ascendancy:monk:martial_artist",
            primary_skill_key="skill:LightningArrowPlayer",
            build_family_keys=["bf-1234567890abcdef"],
            record_kinds=["skill_package"],
        )["status"]
        == "known"
    )
    assert main.propose_research_fragments({"schema_version": 4}, "dq-1")["status"] == "accepted"
    assert main.propose_deep_research_records({"schema_version": 5})["status"] == "accepted"
    assert (
        main.append_evidence_to_fragment(
            "rf-1",
            ["case:1"],
            ["safe:1"],
            "0.5.4",
            "0_5",
            "unknown",
            "creator_visible",
            "train_context",
            "global_seed",
            "medium",
        )["status"]
        == "accepted"
    )
    assert main.propose_semantic_edges({"schema_version": 4})["status"] == "accepted"
    assert main.propose_build_patterns({"schema_version": 4})["status"] == "accepted"
    assert (
        main.submit_revalidation_result(
            "fragment",
            "rf-1",
            "still_valid",
            {"game_patch": "0.6.0"},
            ["safe:review"],
            ["skill:LightningArrowPlayer"],
        )["status"]
        == "accepted"
    )
    assert [name for name, _payload in calls] == [
        "query",
        "fragments",
        "deep_records",
        "append",
        "edges",
        "patterns",
        "revalidate",
    ]
    assert calls[0][1][-4:] == (
        "ascendancy:monk:martial_artist",
        "skill:LightningArrowPlayer",
        ["bf-1234567890abcdef"],
        ["skill_package"],
    )


def test_research_memory_fragment_tools_do_not_require_graph_snapshot(monkeypatch, tmp_path):
    from server import main

    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))

    def missing_graph():
        raise ValueError("missing latest snapshot")

    monkeypatch.setattr(main, "_graph_query_service", missing_graph)

    fragment_query = main.query_research_memory("projectile", ["skill:LightningArrowPlayer"], 5)
    edge_payload = {
        "schema_version": 4,
        "fragments": [],
        "semantic_edges": [
            {
                "source_key": "skill:LightningArrowPlayer",
                "target_key": "support:Scattershot",
                "edge_type": "synergizes_with",
                "rationale": "Safe mechanism-level relationship.",
                "source_case_refs": ["case:safe"],
                "safe_evidence_refs": ["safe:edge"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "status": "valid",
                "confidence": "medium",
                "modelability": "partial",
                "copy_safety_state": "passed",
                "context_requirements": [
                    {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_budget"]}
                ],
                "affected_component_keys": ["skill:LightningArrowPlayer", "support:Scattershot"],
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
                "directionality": "associative",
            }
        ],
    }
    edge_write = main.propose_semantic_edges(edge_payload)

    assert fragment_query["status"] == "known"
    assert edge_write["status"] == "rejected"
    assert edge_write["errorCode"] == "graph_service_unavailable"


def test_evaluate_lifecycle_route_tool_schema():
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    schema = tools["evaluate_lifecycle_route"].inputSchema

    assert "route" in schema["required"]
    assert schema["properties"]["route"]["type"] == "object"
    assert schema["properties"]["reference_profile"]["anyOf"][0]["type"] == "object"
    assert schema["properties"]["goal"]["anyOf"][0]["type"] == "string"


def test_get_freshness_report_forwards_force_refresh(monkeypatch):
    from server import main

    captured: dict[str, bool] = {}

    def fake_report(*, force_refresh: bool = False):
        captured["force_refresh"] = force_refresh
        return {"decision": "verified_current"}

    monkeypatch.setattr(main.freshness_service, "get_freshness_report", fake_report)

    assert main.get_freshness_report(force_refresh=True) == {"decision": "verified_current"}
    assert captured == {"force_refresh": True}


def test_server_startup_runs_research_packet_gc_before_mcp(monkeypatch):
    from server import main

    events: list[str] = []

    monkeypatch.setattr(
        main.research_packet,
        "cleanup_expired_packets",
        lambda: events.append("packet_gc") or {"removed": 0},
    )
    monkeypatch.setattr(
        main.threading,
        "Thread",
        lambda *args, **kwargs: type(
            "FakeThread", (), {"start": lambda self: events.append("thread")}
        )(),
    )
    monkeypatch.setattr(main.mcp, "run", lambda: events.append("mcp"))

    main.main()

    assert events == ["packet_gc", "thread", "mcp"]


def test_suggest_build_lifecycle_uses_freshness_and_meta(monkeypatch, tmp_path):
    from server import main

    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))
    monkeypatch.setattr(
        main.freshness_service,
        "get_freshness_report",
        lambda: {"decision": "verified_current", "blockers": [], "warnings": []},
    )
    monkeypatch.setattr(
        main.live_meta,
        "get_meta_context",
        lambda ascendancy_limit=5, archetype_limit=5: {
            "ok": True,
            "source": "poe.ninja",
            "limit": ascendancy_limit,
            "archetypeTrends": {
                "ok": False,
                "kind": "archetype_trends",
                "archetypes": [],
            },
        },
    )

    result = main.suggest_build_lifecycle("给我一个新手能玩的强力终局BD")

    assert result["ok"] is True
    assert result["freshness"]["decision"] == "verified_current"
    assert result["metaContext"]["source"] == "poe.ninja"
    assert result["metaContext"]["archetypeTrends"]["kind"] == "archetype_trends"
    assert result["buildId"] in main.lifecycle.load_memory()["lifecycle_builds"]


def test_analyze_lifecycle_cohort_tool_uses_meta(monkeypatch):
    from server import main

    monkeypatch.setattr(
        main.live_meta,
        "get_meta_context",
        lambda ascendancy_limit=8, archetype_limit=8: {
            "ok": True,
            "source": "poe.ninja",
            "ascendancies": [],
            "archetypeTrends": {
                "ok": False,
                "kind": "archetype_trends",
                "archetypes": [],
            },
        },
    )
    monkeypatch.setattr(
        main.lifecycle.lifecycle_cohort,
        "analyze_goal_cohort",
        lambda **kwargs: {
            "ok": True,
            "goal": kwargs["goal"],
            "sampleSize": 0,
            "referenceMatches": [],
            "evidenceTags": ["reference-cohort"],
        },
    )

    result = main.analyze_lifecycle_cohort("闪电终局BD")

    assert result["ok"] is True
    assert result["goal"] == "闪电终局BD"


def test_lifecycle_tools_use_single_combined_meta_fetch(monkeypatch, tmp_path):
    from server import main

    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))
    monkeypatch.setattr(
        main.freshness_service,
        "get_freshness_report",
        lambda: {"decision": "verified_current", "blockers": [], "warnings": []},
    )
    calls: list[tuple[int, int]] = []

    def fake_context(*, ascendancy_limit: int = 15, archetype_limit: int = 10):
        calls.append((ascendancy_limit, archetype_limit))
        return {
            "ok": True,
            "source": "poe.ninja",
            "ascendancies": [],
            "archetypeTrends": {"ok": False, "kind": "archetype_trends", "archetypes": []},
        }

    monkeypatch.setattr(main.live_meta, "get_meta_context", fake_context, raising=False)
    monkeypatch.setattr(
        main.live_meta,
        "get_meta_builds",
        lambda **_kwargs: pytest.fail("get_meta_builds should not be called separately"),
    )
    monkeypatch.setattr(
        main.live_meta,
        "get_archetype_trends",
        lambda **_kwargs: pytest.fail("get_archetype_trends should not be called separately"),
    )

    assert main.suggest_build_lifecycle("给我一个新手能玩的强力终局BD")["ok"] is True

    assert calls == [(5, 5)]


def test_get_meta_archetype_trends_tool_returns_adapter_result(monkeypatch):
    from server import main

    monkeypatch.setattr(
        main.live_meta,
        "get_archetype_trends",
        lambda league=None, limit=10: {
            "ok": False,
            "league": league,
            "limit": limit,
            "kind": "archetype_trends",
            "archetypes": [],
        },
    )

    result = main.get_meta_archetype_trends(league="Runes", limit=3)

    assert result["ok"] is False
    assert result["league"] == "Runes"
    assert result["limit"] == 3


def test_get_meta_archetype_trends_tool_reports_unavailable_reason(monkeypatch):
    from server import main

    def fail_meta(**_kwargs):
        raise main.live_meta.MetaError("network unavailable")

    monkeypatch.setattr(main.live_meta, "get_archetype_trends", fail_meta)

    result = main.get_meta_archetype_trends(league="Runes", limit=3)

    assert result["ok"] is False
    assert "network unavailable" in result["unavailableReason"]
    assert "unavailable" in result["evidenceTags"]


def test_evaluate_transition_readiness_tool_forwards_state(monkeypatch):
    from server import main

    monkeypatch.setattr(
        main.lifecycle,
        "evaluate_transition_readiness",
        lambda **kwargs: {"ok": True, "state": kwargs["state"], "from": kwargs["from_stage"]},
    )

    result = main.evaluate_transition_readiness(
        from_stage="maps_entry",
        to_stage="endgame_budget",
        state={"level": 70},
    )

    assert result["ok"] is True
    assert result["state"]["level"] == 70
    assert result["from"] == "maps_entry"


def test_plan_lifecycle_stage_verification_tool_forwards_state(monkeypatch):
    from server import main

    monkeypatch.setattr(
        main.lifecycle.lifecycle_verification,
        "plan_stage_verification",
        lambda stage, state=None: {"ok": True, "stage": stage, "state": state},
    )

    result = main.plan_lifecycle_stage_verification("maps_entry", state={"level": 68})

    assert result["ok"] is True
    assert result["stage"] == "maps_entry"
    assert result["state"]["level"] == 68


def test_verify_lifecycle_stage_collects_active_build_metrics(monkeypatch):
    from server import main

    class _Stub:
        def get_xml(self):
            return "<PathOfBuilding><Build/></PathOfBuilding>"

        def get_stats(self, keys=None):
            return {
                "stats": {
                    "Life": 2600,
                    "Mana": 500,
                    "ManaUnreserved": 420,
                    "ManaCost": 40,
                    "Speed": 2,
                    "NetManaRegen": 85,
                    "TotalDPS": 90000,
                }
            }

        def get_defenses(self):
            return {
                "resistances": {"fire": 75, "cold": 79, "lightning": 76},
                "totalEHP": 12000,
            }

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())

    result = main.verify_lifecycle_stage("maps_entry", state={"level": 68})

    assert result["ok"] is True
    assert result["stage"] == "maps_entry"
    assert result["pass"] is True
    assert result["stateSnapshot"]["level"] == 68
    assert "engine-computed" in result["evidenceTags"]
    assert result["evaluatedSourceHash"]


def test_verify_lifecycle_stage_binds_immutable_artifact_hash_and_ignores_flask_claim(
    monkeypatch,
):
    from server import main

    artifact_id = "final-build:artifact-lifecycle-test"
    artifact_source_hash = "original-artifact-hash"
    artifact_xml = """<PathOfBuilding>
  <Build className="Monk" level="80" mainSocketGroup="1" />
  <Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true">
    <Gem nameSpec="Flicker Strike" gemId="Metadata/Items/Gems/SkillGemFlickerStrike"
      skillId="FlickerStrikePlayer" />
  </Skill></SkillSet></Skills>
</PathOfBuilding>"""
    restored_xml = '<PathOfBuilding><Build level="80"/></PathOfBuilding>'
    recorded: dict[str, object] = {}

    class _Stub:
        def load_build_xml(self, xml, name=None):
            assert xml == artifact_xml
            assert name == artifact_id
            return {"loaded": True}

        def get_xml(self):
            return restored_xml

        def get_build(self):
            return {"gear": {}}

        def get_stats(self, keys=None):
            return {
                "stats": {
                    "Life": 3000,
                    "Mana": 540,
                    "ManaUnreserved": 540,
                    "ManaCost": 221,
                    "Speed": 6.454,
                    "NetManaRegen": 28.1,
                    "TotalDPS": 329791,
                }
            }

        def get_defenses(self):
            return {
                "resistances": {"fire": 75, "cold": 75, "lightning": 75},
                "totalEHP": 16000,
            }

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    monkeypatch.setattr(
        main.generation_artifacts,
        "read_final_build_artifact_for_export",
        lambda requested_id: (
            (
                SimpleNamespace(
                    artifact_id=artifact_id,
                    source_hash=artifact_source_hash,
                ),
                artifact_xml,
            )
            if requested_id == artifact_id
            else None
        ),
    )

    def save_receipt(**kwargs):
        recorded.update(kwargs)
        return {
            "status": "recorded",
            "verificationRef": "lifecycle-verification:0123456789abcdef",
        }

    monkeypatch.setattr(
        main.generation_progression_lifecycle,
        "save_artifact_lifecycle_receipt",
        save_receipt,
    )

    result = main.verify_lifecycle_stage(
        "maps_entry",
        state={"manaFlaskEquipped": True},
        artifact_id=artifact_id,
    )

    assert result["pass"] is False
    assert "sustain_ok" in result["failedChecks"]
    assert result["stateSnapshot"]["manaFlaskEquipped"] is False
    assert result["evaluatedSourceHash"] == artifact_source_hash
    assert result["restoredEngineSourceHash"] != artifact_source_hash
    assert result["artifactBound"] is True
    assert recorded["source_hash"] == artifact_source_hash
    assert recorded["restored_engine_source_hash"] == result["restoredEngineSourceHash"]
    assert recorded["result"]["evaluatedSourceHash"] == artifact_source_hash


def test_verify_artifact_lifecycle_ignores_derived_pob_output_churn(monkeypatch):
    from server import main

    artifact_id = "final-build:artifact-derived-output-test"
    artifact_source_hash = "original-artifact-hash"
    artifact_xml = """<PathOfBuilding>
  <Build className="Monk" level="80" mainSocketGroup="1" />
  <Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true">
    <Gem nameSpec="Storm Wave" gemId="Metadata/Items/Gems/SkillGemStormWave"
      skillId="StormWavePlayer" />
  </Skill></SkillSet></Skills>
</PathOfBuilding>"""
    restored_before = """<PathOfBuilding>
  <Build className="Monk" level="80" mainSocketGroup="1">
    <PlayerStat stat="TotalDPS" value="100" />
  </Build>
  <Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true">
    <Gem nameSpec="Storm Wave" gemId="Metadata/Items/Gems/SkillGemStormWave"
      skillId="StormWavePlayer" />
  </Skill></SkillSet></Skills>
</PathOfBuilding>"""
    restored_after = restored_before.replace('value="100"', 'value="999"')

    class _Stub:
        refreshed = False

        def load_build_xml(self, xml, name=None):
            assert xml == artifact_xml
            assert name == artifact_id
            return {"loaded": True}

        def get_xml(self):
            return restored_after if self.refreshed else restored_before

        def get_build(self):
            self.refreshed = True
            return {"gear": {}}

        def get_stats(self, keys=None):
            return {
                "stats": {
                    "Life": 3000,
                    "Mana": 540,
                    "ManaUnreserved": 540,
                    "ManaCost": 20,
                    "Speed": 2,
                    "NetManaRegen": 60,
                    "TotalDPS": 100000,
                }
            }

        def get_defenses(self):
            return {
                "resistances": {"fire": 75, "cold": 75, "lightning": 75},
                "totalEHP": 16000,
            }

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    monkeypatch.setattr(
        main.generation_artifacts,
        "read_final_build_artifact_for_export",
        lambda requested_id: (
            (
                SimpleNamespace(
                    artifact_id=artifact_id,
                    source_hash=artifact_source_hash,
                ),
                artifact_xml,
            )
            if requested_id == artifact_id
            else None
        ),
    )
    monkeypatch.setattr(
        main.generation_progression_lifecycle,
        "save_artifact_lifecycle_receipt",
        lambda **kwargs: {
            "status": "recorded",
            "verificationRef": "lifecycle-verification:0123456789abcdef",
        },
    )

    result = main.verify_lifecycle_stage(
        "maps_entry",
        state={"level": 80},
        artifact_id=artifact_id,
    )

    assert result["ok"] is True
    assert result["pass"] is True
    assert result["artifactBound"] is True
    assert result["evaluatedSourceHash"] == artifact_source_hash
    assert result["restoredEngineSourceHash"].startswith("sha256:")


def test_verify_artifact_lifecycle_rejects_semantic_state_mutation(monkeypatch):
    from server import main

    artifact_id = "final-build:artifact-semantic-mutation-test"
    artifact_source_hash = "original-artifact-hash"
    artifact_xml = """<PathOfBuilding>
  <Build className="Monk" level="80" mainSocketGroup="1" />
  <Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true">
    <Gem nameSpec="Storm Wave" gemId="Metadata/Items/Gems/SkillGemStormWave"
      skillId="StormWavePlayer" />
  </Skill></SkillSet></Skills>
</PathOfBuilding>"""
    restored_after = artifact_xml.replace('level="80"', 'level="79"')

    class _Stub:
        mutated = False

        def load_build_xml(self, xml, name=None):
            return {"loaded": True}

        def get_xml(self):
            return restored_after if self.mutated else artifact_xml

        def get_build(self):
            self.mutated = True
            return {"gear": {}}

        def get_stats(self, keys=None):
            return {"stats": {}}

        def get_defenses(self):
            return {}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    monkeypatch.setattr(
        main.generation_artifacts,
        "read_final_build_artifact_for_export",
        lambda requested_id: (
            (
                SimpleNamespace(
                    artifact_id=artifact_id,
                    source_hash=artifact_source_hash,
                ),
                artifact_xml,
            )
            if requested_id == artifact_id
            else None
        ),
    )

    result = main.verify_lifecycle_stage(
        "maps_entry",
        state={"level": 80},
        artifact_id=artifact_id,
    )

    assert result["ok"] is False
    assert result["status"] == "unknown"
    assert result["errorCode"] == "lifecycle_snapshot_changed_during_verification"


def test_verify_campaign_early_derives_main_skill_from_same_xml_snapshot(monkeypatch):
    from server import main

    xml = """<PathOfBuilding>
  <Build className="Monk" level="22" mainSocketGroup="1" />
  <Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true">
    <Gem nameSpec="Glacial Cascade" gemId="Metadata/Items/Gems/SkillGemGlacialCascade"
      skillId="GlacialCascadePlayer" />
  </Skill></SkillSet></Skills>
</PathOfBuilding>"""

    class _Stub:
        def get_xml(self):
            return xml

        def get_build(self):
            return {"gear": {}}

        def get_stats(self, keys=None):
            return {
                "stats": {
                    "Life": 900,
                    "Mana": 400,
                    "ManaUnreserved": 400,
                    "ManaCost": 10,
                    "Speed": 1.5,
                    "NetManaRegen": 20,
                }
            }

        def get_defenses(self):
            return {"totalEHP": 2500}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())

    result = main.verify_lifecycle_stage(
        "campaign_early",
        state={"mainSkillSocketed": False},
    )

    assert result["pass"] is True
    assert result["stateSnapshot"]["mainSkillSocketed"] is True
    assert result["stateSnapshot"]["mainSkillSocketEvidence"]["activeSkills"] == ["Glacial Cascade"]
    assert result["evaluatedSourceHash"]


def test_verify_campaign_mid_matches_named_single_target_skill_to_same_xml(monkeypatch):
    from server import main

    xml = """<PathOfBuilding>
  <Build className="Monk" ascendClassName="Martial Artist" level="40"
    mainSocketGroup="1" />
  <Skills activeSkillSet="1"><SkillSet id="1">
    <Skill enabled="true">
      <Gem nameSpec="Storm Wave" gemId="Metadata/Items/Gems/SkillGemStormWave"
        skillId="StormWavePlayer" />
      <Gem nameSpec="Close Combat" gemId="Metadata/Items/Gems/SupportGemCloseCombat"
        skillId="SupportCloseCombatPlayer" />
    </Skill>
    <Skill enabled="true">
      <Gem nameSpec="Tempest Bell" gemId="Metadata/Items/Gems/SkillGemTempestBell"
        skillId="TempestBellPlayer" />
    </Skill>
  </SkillSet></Skills>
</PathOfBuilding>"""

    class _Stub:
        def get_xml(self):
            return xml

        def get_build(self):
            return {"gear": {}}

        def get_stats(self, keys=None):
            return {
                "stats": {
                    "TotalDPS": 5000,
                    "Life": 1400,
                    "Mana": 500,
                    "ManaUnreserved": 500,
                    "ManaCost": 20,
                    "Speed": 2,
                    "NetManaRegen": 50,
                }
            }

        def get_defenses(self):
            return {"totalEHP": 8000}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())

    result = main.verify_lifecycle_stage(
        "campaign_mid",
        state={
            "singleTargetSkillName": "Tempest Bell",
            "singleTargetEvidenceRefs": [
                "gem:TempestBellPlayer",
                "mechanic:bell_single_target",
            ],
        },
    )

    assert result["pass"] is True
    assert result["stateSnapshot"]["ascendancyOrKeySupport"]["verified"] is True
    assert result["stateSnapshot"]["singleTargetDuty"]["verified"] is True
    assert result["stateSnapshot"]["singleTargetDuty"]["matchedSkillName"] == "Tempest Bell"
    assert result["evaluatedSourceHash"]


def test_verify_endgame_budget_matches_build_defining_skill_to_same_xml(monkeypatch):
    from server import main

    xml = """<PathOfBuilding>
  <Build className="Monk" ascendClassName="Martial Artist" level="82"
    mainSocketGroup="1" />
  <Skills activeSkillSet="1"><SkillSet id="1">
    <Skill enabled="true">
      <Gem nameSpec="Whirling Assault"
        gemId="Metadata/Items/Gems/SkillGemWhirlingAssault"
        skillId="WhirlingAssaultPlayer" />
      <Gem nameSpec="Close Combat" gemId="Metadata/Items/Gems/SupportGemCloseCombat"
        skillId="SupportCloseCombatPlayer" />
    </Skill>
  </SkillSet></Skills>
</PathOfBuilding>"""

    class _Stub:
        def get_xml(self):
            return xml

        def get_build(self):
            return {"gear": {}}

        def get_stats(self, keys=None):
            return {
                "stats": {
                    "TotalDPS": 10000,
                    "Life": 4000,
                    "Mana": 600,
                    "ManaUnreserved": 600,
                    "ManaCost": 20,
                    "Speed": 2,
                    "NetManaRegen": 50,
                }
            }

        def get_defenses(self):
            return {
                "resistances": {"fire": 75, "cold": 75, "lightning": 75},
                "totalEHP": 14000,
            }

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())

    result = main.verify_lifecycle_stage(
        "endgame_budget",
        state={
            "buildDefiningComponentKind": "skill",
            "buildDefiningComponentName": "Whirling Assault",
            "buildDefiningComponentKey": "skill:WhirlingAssaultPlayer",
            "buildDefiningEvidenceRefs": [
                "skill:WhirlingAssaultPlayer",
                "dq-0123456789abcdef",
            ],
        },
    )

    assert result["pass"] is True
    assert result["stateSnapshot"]["buildDefiningComponent"]["verified"] is True
    assert result["stateSnapshot"]["buildDefiningComponent"]["matchedName"] == "Whirling Assault"
    assert result["evaluatedSourceHash"]


def test_audit_lifecycle_route_tool_forwards_route(monkeypatch):
    from server import main

    monkeypatch.setattr(
        main.lifecycle.lifecycle_quality,
        "audit_lifecycle_route",
        lambda route: {"pass": False, "route": route},
    )

    result = main.audit_lifecycle_route({"stages": []})

    assert result["pass"] is False
    assert result["route"]["stages"] == []


def test_evaluate_lifecycle_route_tool_forwards_route(monkeypatch):
    from server import main

    monkeypatch.setattr(
        main.lifecycle_eval,
        "evaluate_lifecycle_route",
        lambda route, reference_profile=None, goal=None: {
            "kind": "lifecycle_route_evaluation",
            "route": route,
            "referenceProfile": reference_profile,
            "goal": goal,
        },
    )

    result = main.evaluate_lifecycle_route(
        {"stages": []},
        reference_profile={"sampleSize": 1},
        goal="eval goal",
    )

    assert result["kind"] == "lifecycle_route_evaluation"
    assert result["route"]["stages"] == []
    assert result["referenceProfile"]["sampleSize"] == 1
    assert result["goal"] == "eval goal"


def test_check_data_version_calls_service_once_and_nests_legacy_probe(monkeypatch):
    from server import main

    calls = 0
    strict = {
        "decision": "blocked_unknown",
        "evidence": [],
        "active_evidence": [],
        "blockers": ["required component game_patch has no evidence"],
        "warnings": [],
        "evaluated_at": "2026-06-24T12:00:00+00:00",
        "providers": [],
        "provider_status": [],
    }

    def fake_report():
        nonlocal calls
        calls += 1
        return strict

    monkeypatch.setattr(main.freshness_service, "get_freshness_report", fake_report)
    monkeypatch.setattr(
        main.live_version,
        "check_data_version",
        lambda: {"recommendation": "up_to_date"},
    )

    result = main.check_data_version()

    assert calls == 1
    assert result["recommendation"] == "blocked_unknown"
    assert result["freshness"] == strict
    assert result["legacy_corpus_probe"] == {"recommendation": "up_to_date"}


def test_apply_combat_profile_sets_conditions(monkeypatch):
    from server import main

    captured: dict = {}

    class _Stub:
        def set_config(self, options=None, custom_mods=None):
            captured["options"] = options
            return {"stats": {"TotalDPS": 1}}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    r = main.apply_combat_profile(tier="Pinnacle", shocked=True, cursed=False)
    opts = captured["options"]
    assert opts["enemyIsBoss"] == "Pinnacle"
    assert opts.get("conditionEnemyShocked") is True
    assert "conditionEnemyCursed" not in opts  # cursed=False omitted
    assert r["assumptions"] and any("Shocked" in a for a in r["assumptions"])


def test_pinnacle_readiness_gate(monkeypatch):
    from server import main

    class _Stub:
        def get_defenses(self):
            return {
                "resistances": {"fire": 75, "cold": 75, "lightning": 75, "chaos": 40},
                "resistOverCap": {"fire": 10, "cold": 8, "lightning": 12},
                "totalEHP": 30000,
            }

        def get_build(self):
            return {"keystones": [], "stats": {"FullDPS": 600000, "TotalDPS": 50000}}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    r = main.pinnacle_readiness(min_ehp=25000, min_dps=500000)
    assert r["pass"] is False  # chaos 40, not CI -> fails the chaos check
    checks = {c["check"]: c for c in r["checks"]}
    assert checks["elemental resists capped (75%)"]["ok"]  # DPS uses FullDPS (600k >= 500k)

    class _CI(_Stub):
        def get_build(self):
            d = _Stub.get_build(self)
            d["keystones"] = ["Chaos Inoculation"]
            return d

    monkeypatch.setattr(main, "get_engine", lambda: _CI())
    assert main.pinnacle_readiness(min_ehp=25000, min_dps=500000)["pass"] is True


def test_equip_item_flags_illegal_affixes(monkeypatch):
    # The legality wiring: a body-armour "% maximum Mana" affix surfaces a warning (engine stubbed,
    # so this tests the corpus check + merge, not the calc).
    from server import main

    class _Stub:
        def add_item(self, raw, slot=None):
            return {"ok": True, "slot": slot or "Body Armour", "stats": {"TotalDPS": 1.0}}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    monkeypatch.setattr(
        main.corpus,
        "get_item",
        lambda name: {"name": name} if name == "Sacramental Robe" else None,
    )
    monkeypatch.setattr(
        main.corpus,
        "illegal_affixes",
        lambda base, affixes: [{"text": affixes[0]}],
    )
    raw = (
        "Rarity: Rare\nFantasy Plate\nSacramental Robe\n--------\n"
        "60% increased maximum Mana\n+40% to Fire Resistance"
    )
    res = main.equip_item(raw, slot="Body Armour")
    assert res.get("illegalAffixes")
    assert "Sacramental Robe" in (res.get("legalityWarning") or "")


def test_equip_item_clean_gear_has_no_warning(monkeypatch):
    from server import main

    class _Stub:
        def add_item(self, raw, slot=None):
            return {"ok": True, "slot": slot or "Ring 1", "stats": {}}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    monkeypatch.setattr(
        main.corpus,
        "get_item",
        lambda name: {"name": name} if name == "Sapphire Ring" else None,
    )
    monkeypatch.setattr(main.corpus, "illegal_affixes", lambda base, affixes: [])
    raw = (
        "Rarity: Rare\nGood Ring\nSapphire Ring\n--------\n"
        "+140 to maximum Mana\n+42% to Lightning Resistance"
    )
    res = main.equip_item(raw, slot="Ring 1")
    assert "illegalAffixes" not in res and "legalityWarning" not in res


def test_import_caveats_flag_aspirational_pob():
    from server import main

    class _Stub:
        def get_build(self):
            return {
                "customMods": "+111% to Fire Resistance",
                "pointsUsed": 140,
                "pointsAvailable": 116,
                "level": 93,
                "keystones": [],
            }

        def get_defenses(self):
            return {"resistances": {"fire": 66, "cold": 66, "lightning": 66, "chaos": 33}}

    joined = " ".join(main._import_caveats(_Stub())).lower()
    assert "custom mods" in joined
    assert "over budget" in joined
    assert "below the 75% cap" in joined and "chaos 33" in joined

    class _CI(_Stub):
        def get_build(self):
            d = _Stub.get_build(self)
            d["keystones"] = ["Chaos Inoculation"]
            return d

    ci = " ".join(main._import_caveats(_CI())).lower()
    assert "chaos" not in ci  # chaos resist is irrelevant under Chaos Inoculation


def test_meta_builds_shape():
    # Network-free: exercise the league selection + formatting on a sample payload.
    from server.live import meta

    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "leagueUrl": "runesofaldur",
                "total": 124269,
                "statistics": [
                    {"class": "Martial Artist", "percentage": 24.5, "trend": 1},
                    {"class": "Spirit Walker", "percentage": 17.7, "trend": -1},
                ],
            },
            {"leagueName": "HC Runes of Aldur", "total": 5000, "statistics": []},
            {"leagueName": "Standard", "total": 999999, "statistics": []},
        ]
    }
    r = meta.shape(sample, limit=5)
    # defaults to the main softcore challenge league, not Standard/HC (despite Standard's total)
    assert r["ok"] and r["league"] == "Runes of Aldur" and r["sampleSize"] == 124269
    assert r["ascendancies"][0]["ascendancy"] == "Martial Artist"
    assert r["ascendancies"][0]["trend"] == "rising" and r["ascendancies"][1]["trend"] == "falling"
    assert meta.shape(sample, league="Standard")["league"] == "Standard"  # explicit override
    assert meta.shape(sample, league="Nope")["ok"] is False  # not found


def test_build_advice_sections():
    from server.knowledge import advice

    overview = advice.advise()
    assert overview["topics"]
    assert "engine" in overview["intro"].lower()  # framing: numbers come from the engine
    defense = advice.advise("defense")
    # Planning guidance remains useful, but current data has explicit authority over patch facts.
    assert "75%" in defense["text"]
    assert "current 0.5 `chaos inoculation`" in defense["text"].lower()
    assert "chaos damage" in defense["text"].lower()
    assert "bleeding" in defense["text"].lower()
    assert "pinned pob" in defense["authority"].lower()
    # fuzzy keyword match resolves a query that isn't a section title
    assert advice.advise("crit").get("topic")


def test_server_version_reads_utf8_manifest(monkeypatch):
    import json
    from pathlib import Path

    from server import paths
    from server.main import _server_version

    manifest = paths.BUNDLE_ROOT / "manifest.json"
    expected = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    original_read_text = Path.read_text
    observed_encoding = None

    def recording_read_text(path, *args, **kwargs):
        nonlocal observed_encoding
        if path == manifest:
            observed_encoding = kwargs.get("encoding") or (args[0] if args else None)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", recording_read_text)
    assert _server_version() == expected
    assert observed_encoding == "utf-8"
