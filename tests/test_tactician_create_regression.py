from __future__ import annotations

from datetime import UTC, datetime

from scripts import create_build
from server import main as server_main
from server.compute import completeness
from server.generation import artifacts
from server.knowledge import graph_tools as gt
from server.knowledge import physical_graph as pg
from server.knowledge import research_memory


def _tool(function):
    return getattr(function, "__wrapped__", function)


def _tactician_memory_service(root) -> research_memory.ResearchMemoryService:
    source = pg.GraphSource(
        source_id="fixture:tactician-create",
        kind="test_fixture",
        source_file="tests/test_tactician_create_regression.py",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
    )
    nodes = (
        pg.GraphNode("class:mercenary", "class", "Mercenary", (source.source_id,)),
        pg.GraphNode(
            "ascendancy:mercenary:tactician",
            "ascendancy",
            "Tactician",
            (source.source_id,),
        ),
        pg.GraphNode(
            "skill:GalvanicShardsPlayer",
            "active_skill",
            "Galvanic Shards",
            (source.source_id,),
        ),
        pg.GraphNode(
            "skill:StormblastBoltsPlayer",
            "active_skill",
            "Stormblast Bolts",
            (source.source_id,),
        ),
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="snapshot:tactician-create",
        created_at=datetime(2026, 8, 31, tzinfo=UTC),
        sources=(source,),
        nodes=nodes,
        aliases=(),
        edges=(),
    )
    service = research_memory.ResearchMemoryService(
        db_path=root / "mature.sqlite",
        graph_service=gt.GraphQueryService.from_snapshot(snapshot),
    )
    payload = {
        "schema_version": 5,
        "deep_research_records": [
            {
                "research_group_id": "research:tactician-create-golden",
                "record_kind": "skill_package",
                "title": "Tactician Galvanic and Stormblast package",
                "summary": "Family-first fixture for a two-skill crossbow package.",
                "content": (
                    "Galvanic Shards handles clear while Stormblast Bolts is the declared boss "
                    "calculation group; both groups require independent support and sustain checks."
                ),
                "content_language": "en",
                "length_exception_reason": None,
                "component_keys": [
                    "skill:GalvanicShardsPlayer",
                    "skill:StormblastBoltsPlayer",
                ],
                "component_mentions": [
                    {
                        "candidate_name": "Galvanic Shards",
                        "role": "primary_damage",
                        "resolver_query": "Galvanic Shards",
                        "expected_node_types": ["active_skill"],
                        "scope": "player",
                        "component_key": "skill:GalvanicShardsPlayer",
                        "resolution_status": "resolved",
                    },
                    {
                        "candidate_name": "Stormblast Bolts",
                        "role": "boss_skill",
                        "resolver_query": "Stormblast Bolts",
                        "expected_node_types": ["active_skill"],
                        "scope": "player",
                        "component_key": "skill:StormblastBoltsPlayer",
                        "resolution_status": "resolved",
                    },
                ],
                "source_case_refs": ["case:tactician-create-golden"],
                "safe_evidence_refs": ["safe:tactician-create-golden"],
                "conditions": ["crossbow equipped"],
                "failure_conditions": ["boss group or supports not independently checked"],
                "typed_payload": {"roles": ["clear", "boss"]},
                "class_key": "class:mercenary",
                "ascendancy_key": "ascendancy:mercenary:tactician",
                "extraction_method_version": "deep_research_mvp_v1",
                "record_schema_version": 1,
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "0.22.0",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
    }
    accepted = service.propose_deep_research_records(payload)
    assert accepted["status"] == "accepted", accepted
    return service


def _complete_compact_family_query():
    query = _tool(server_main.query_research_memory)
    page = query(
        "",
        detail_level="family",
        class_key="class:mercenary",
        ascendancy_key="ascendancy:mercenary:tactician",
        game_patch="0.5.4",
        passive_tree_version="0_5",
        response_profile="create_compact",
    )
    while not page["retrieval"]["complete"]:
        page = query("", continuation_cursor=page["retrieval"]["nextCursor"])
    return page


def test_tactician_95_real_create_toolchain_regression(tmp_path, monkeypatch, engine):
    monkeypatch.setenv("POE_BD_CREATE_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("POE_BD_FINAL_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    service = _tactician_memory_service(tmp_path / "memory")
    monkeypatch.setattr(server_main, "_research_memory_service_with_graph", lambda: service)
    monkeypatch.setattr(create_build.research_memory, "ResearchMemoryService", lambda: service)
    monkeypatch.setattr(server_main, "get_engine", lambda: engine)

    assert _tool(server_main.new_build)().get("ok") is not False
    run = _tool(server_main.start_generation_run)("memory_assisted")
    page = _complete_compact_family_query()
    assert page["retrieval"]["complete"] is True
    assert page["buildFamilies"]
    family_key = page["buildFamilies"][0]["buildFamilyKey"]
    family = _tool(server_main.record_generation_family_discovery)(
        str(run["runContext"]["runId"]),
        str(run["runContext"]["runToken"]),
        page["dedupeQueryRef"],
        family_key,
    )
    assert family["status"] == "recorded"
    assert engine.get_build().get("mainSkill") is None

    assert _tool(server_main.set_class)("Mercenary", "Tactician").get("ok") is not False
    assert _tool(server_main.set_level)(95).get("ok") is not False
    weapon = "Rarity: Normal\nSiege Crossbow\nItem Level: 82"
    assert _tool(server_main.equip_item)(weapon, "Weapon 1").get("ok") is not False
    assert _tool(server_main.set_skill)(
        "Galvanic Shards 20/20 1\nDouble Barrel I\nShock"
    ).get("ok") is not False
    assert _tool(server_main.add_skill_group)(
        "Stormblast Bolts 20/20 1\nMagnified Area I\nElemental Armament I",
        True,
    ).get("ok") is not False

    rune_plan = _tool(server_main.plan_item_sockets_batch)(
        {"Weapon 1": 2},
        {"TotalDPS": 1.0},
    )
    assert rune_plan["ok"] is True, rune_plan
    rune_result = rune_plan["results"][0]
    assert rune_result["changed"] is True, rune_result
    assert rune_result["socketCapacity"] == 2
    assert _tool(server_main.equip_item)(
        rune_result["item"],
        "Weapon 1",
        rune_result["craftReceiptRef"],
    )["ok"]

    belt = """Rarity: Rare
Regression Belt
Fine Belt
Item Level: 82
Charm Slots: 1
Implicits: 1
Has 1 Charm Slot"""
    assert _tool(server_main.equip_item)(belt, "Belt")["ok"]
    charm = _tool(server_main.optimize_charm)("Charm 1", "Amethyst Charm")
    assert charm["ok"] is True, charm
    assert _tool(server_main.equip_item)(charm["item"], "Charm 1")["ok"]
    life_flask = _tool(server_main.optimize_flask)(
        "Flask 1", "Ultimate Life Flask", strategy="sustain"
    )
    mana_flask = _tool(server_main.optimize_flask)(
        "Flask 2", "Ultimate Mana Flask", strategy="sustain"
    )
    assert life_flask["ok"] is True and mana_flask["ok"] is True
    assert _tool(server_main.equip_item)(life_flask["item"], "Flask 1")["ok"]
    assert _tool(server_main.equip_item)(mana_flask["item"], "Flask 2")["ok"]

    reachable = []
    for socket in engine.list_jewel_sockets()["sockets"]:
        if socket.get("allocated") or socket.get("filled"):
            continue
        passive = engine.get_passive(int(socket["socket"]))
        if isinstance(passive.get("pathDist"), (int, float)) and passive["pathDist"] > 0:
            reachable.append((int(passive["pathDist"]), int(socket["socket"])))
    _, jewel_socket = min(reachable)
    assert engine.alloc_passive(jewel_socket)["ok"] is True
    jewel = _tool(server_main.optimize_jewel)(goals={"TotalDPS": 0.7, "Life": 0.3})
    assert jewel["ok"] is True, jewel
    assert _tool(server_main.equip_jewel)(jewel["item"], jewel_socket)["ok"]
    marginal = _tool(server_main.evaluate_next_jewel_socket)(
        jewel["item"],
        {"TotalDPS": 0.7, "Life": 0.3},
        1,
    )
    assert marginal["ok"] is True

    def ordinary_group(current, name):
        matches = [
            group for group in current["groups"]
            if not group.get("source") and group["gems"][0]["name"] == name
        ]
        assert len(matches) == 1, {"skill": name, "groups": current["groups"]}
        return matches[0]

    current = _tool(server_main.list_skill_groups)()
    skills = ("Galvanic Shards", "Stormblast Bolts")
    groups = [ordinary_group(current, name) for name in skills]
    assert [
        sum(1 for gem in group["gems"] if gem.get("isSupport")) for group in groups
    ] == [2, 2]
    assert any(group.get("source") == "Default Attack" for group in current["groups"])
    for name in skills:
        current = _tool(server_main.list_skill_groups)()
        group = ordinary_group(current, name)
        group_index = group["index"]
        audit = _tool(server_main.optimize_supports)(
            max_supports=2,
            candidates=6,
            group_index=group_index,
            expected_fingerprint=group["fingerprint"],
        )
        assert audit["ok"] is True
        assert audit["supportAudit"]["groupIndex"] == group_index

    boss_group = ordinary_group(_tool(server_main.list_skill_groups)(), "Stormblast Bolts")
    selection = engine.select_judge_skill(
        offense_skill_group_index=boss_group["index"],
        expected_skill_name="Stormblast Bolts",
    )
    checkpoint = _tool(server_main.inspect_generation_checkpoint)(
        True,
        boss_group["index"],
        "Stormblast Bolts",
    )
    assert selection["status"] == "selected"
    assert selection["calculationContext"]["groupIndex"] == boss_group["index"]
    assert checkpoint["calculationContext"]["groupIndex"] == boss_group["index"]
    assert checkpoint["calculationContext"]["skillName"] == "Stormblast Bolts"
    assert checkpoint["lifecycleVerification"]["stage"] == "endgame_final"

    gear = completeness.equipped_item_metadata(engine.get_xml())
    assert gear["Weapon 1"]["runeSockets"] == 2
    assert gear["Weapon 1"]["verifiedRuneCount"] == rune_result["filledSocketCount"]
    assert gear["Charm 1"]["rarity"].casefold() == "magic"
    jewel_state = completeness.inspect_build_completeness(engine)["passiveJewels"]
    assert jewel_state["allocatedSockets"] >= 1
    assert jewel_state["filledSockets"] >= 1

    xml = engine.get_xml()
    round_trip = artifacts._validate_pob_round_trip(engine, xml)
    assert round_trip["status"] == "passed", round_trip
    after = completeness.equipped_item_metadata(engine.get_xml())
    assert after["Weapon 1"]["runeSockets"] == 2
    assert after["Weapon 1"]["verifiedRuneCount"] == rune_result["filledSocketCount"]
