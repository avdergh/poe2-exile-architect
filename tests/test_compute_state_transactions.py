from __future__ import annotations

import pytest

from server import main
from server.compute import completeness, equipment, mutation_batch, passiveopt, skillgroups
from server.compute.engine import PobEngineError
from server.compute.state import build_state_hash
from server.judge import hard_legality


@pytest.mark.parametrize(
    "class_name,attribute", [("Warrior", "Intelligence"), ("Sorceress", "Dexterity")]
)
def test_public_jewel_transaction_and_shared_snapshot_audit(
    engine, monkeypatch, class_name, attribute
):
    engine.new_build()
    engine.set_class(class_name)
    engine.set_level(90)
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    sockets = engine.list_jewel_sockets()["sockets"]
    socket = min(sockets, key=lambda row: engine.get_passive(row["socket"]).get("pathDist", 999))[
        "socket"
    ]
    prism = "Rarity: Unique\nPrism of Belief\nDiamond\n+3 to Level of all Fireball Skills"
    original = build_state_hash(engine.get_xml())
    assert main.equip_jewel(prism, socket)["errorCode"] == "jewel_socket_not_allocated"
    assert build_state_hash(engine.get_xml()) == original
    allocated = main.alloc_passive(socket, path_attribute=attribute, expected_state_hash=original)
    assert allocated["ok"]
    result = main.equip_jewel(prism, socket, expected_state_hash=allocated["outputStateHash"])
    assert result["ok"] and result["readbackVerified"]
    assert result["outputStateHash"] == build_state_hash(engine.get_xml())
    other = next(
        row["socket"] for row in engine.list_jewel_sockets()["sockets"] if not row["allocated"]
    )
    engine.alloc_passive(other)
    before_duplicate = build_state_hash(engine.get_xml())
    duplicate = main.equip_jewel(prism.replace("Fireball", "Spark"), other)
    assert duplicate["errorCode"] == "jewel_limit_exceeded" and duplicate["rolledBack"]
    assert build_state_hash(engine.get_xml()) == before_duplicate
    # The generic equipment route shares the same allocated-slot and item-source authority.
    raw = "Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 80\n15% increased Mana Regeneration Rate"
    result = main.equip_item(raw, slot=f"Jewel {socket}")
    assert result["ok"] and result["readbackVerified"]
    illegal = raw.replace("15%", "999%")
    before_illegal = build_state_hash(engine.get_xml())
    assert main.equip_jewel(illegal, socket)["ok"] is False
    assert build_state_hash(engine.get_xml()) == before_illegal
    # Imported / low-level material is still caught at the shared Judge/artifact boundary.
    assert engine.equip_jewel(illegal, socket=socket)["ok"]
    gear = completeness.equipped_item_metadata(engine.get_xml())
    assert gear[f"Jewel {socket}"]["affixLegality"]["ok"] is False
    assert "final_artifact_illegal_affixes" in completeness.artifact_blockers(engine.get_xml())
    audit = hard_legality.audit_active_build(engine)
    assert "illegal_equipped_item_affixes" in audit["hardFailures"]


def test_passive_attribute_batch_rolls_back_earlier_edits_and_rejects_stale_hash(
    engine, monkeypatch
):
    engine.new_build()
    engine.set_class("Mercenary")
    engine.set_level(90)
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    nodes = engine.search_passives(node_type="Notable", limit=6000)["results"]
    target = next(n for n in nodes if n.get("pathDist", 0) >= 7)
    attribute_target = next(
        n
        for n in engine.search_passives(limit=6000)["results"]
        if n["isAttribute"] and n.get("pathDist")
    )
    engine.alloc_passive(attribute_target["id"], path_attribute="Intelligence")
    attribute = next(
        n["id"]
        for n in engine.search_passives(limit=6000)["results"]
        if n["alloc"] and n["isAttribute"]
    )
    before = build_state_hash(engine.get_xml())
    assert (
        main.set_passive_attribute(attribute, "Dexterity", expected_state_hash="sha256:stale")[
            "errorCode"
        ]
        == "build_state_conflict"
    )
    result = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="passive_delta",
        expected_state_hash=before,
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="set_passive_attribute", node=attribute, attribute="Dexterity"
            ),
            mutation_batch.BuildMutationOperation(
                operation="set_passive_attribute", node=target["id"], attribute="Strength"
            ),
        ],
    )
    assert not result["ok"] and result["rolledBack"]
    assert build_state_hash(engine.get_xml()) == before
    assert engine.get_passive(attribute)["attribute"] == "Intelligence"


def _monk_with_two_groups(engine):
    engine.new_build()
    engine.set_class("Monk", "Invoker")
    engine.set_level(80)
    engine.add_item(
        "Rarity: Rare\nTransaction Staff\nSteelpoint Quarterstaff\nItem Level: 80\n"
        "120% increased Physical Damage",
        slot="Weapon 1",
    )
    engine.paste_skill("Storm Wave")
    engine.add_skill_group("Herald of Thunder")


def test_semantic_state_hash_ignores_pob_serialization_noise():
    first = """<PathOfBuilding2><Build className="Monk" level="80">
    <PlayerStat stat="TotalDPS" value="100"/></Build>
    <Tree activeSpec="1"><Spec nodes="3,1,2" classId="10"><URL>old</URL>
    <AttributeOverride strNodes="6,4,5" dexNodes="9,7,8" intNodes="12,10,11"/>
    </Spec></Tree>
    <Skills activeSkillSet="1" sortGemsByDPS="true"><SkillSet id="1">
    <Skill label="" includeInFullDPS="nil" mainActiveSkill="nil"/>
    </SkillSet></Skills></PathOfBuilding2>"""
    second = """<PathOfBuilding2><Skills sortGemsByDPS="false" activeSkillSet="1">
    <SkillSet id="1"><Skill mainActiveSkill="1" includeInFullDPS="false" label=""
    mainActiveSkillCalcs="1"/></SkillSet></Skills>
    <Tree activeSpec="1"><Spec classId="10" nodes="2,3,1"><URL>new</URL>
    <AttributeOverride intNodes="11,12,10" strNodes="4,6,5" dexNodes="8,9,7"/>
    </Spec></Tree>
    <Build level="80" className="Monk"><PlayerStat value="999" stat="TotalDPS"/></Build>
    </PathOfBuilding2>"""

    assert build_state_hash(first) == build_state_hash(second)
    assert build_state_hash(first) != build_state_hash(first.replace('level="80"', 'level="79"'))
    repeated_first = first.replace('strNodes="6,4,5"', 'strNodes="6,4,5,5"')
    repeated_second = second.replace('strNodes="4,6,5"', 'strNodes="5,4,6,5"')
    assert build_state_hash(repeated_first) == build_state_hash(repeated_second)
    assert build_state_hash(first) != build_state_hash(repeated_first)
    assert build_state_hash(first) != build_state_hash(
        first.replace('strNodes="6,4,5"', 'strNodes="6,4"')
    )


def test_functional_mutation_batches_chain_and_rollback_on_real_engine(engine):
    bootstrap = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="bootstrap",
        operations=[
            mutation_batch.BuildMutationOperation(operation="new_build"),
            mutation_batch.BuildMutationOperation(
                operation="set_class",
                class_name="Monk",
                ascendancy="Invoker",
            ),
            mutation_batch.BuildMutationOperation(operation="set_level", level=20),
        ],
    )
    assert bootstrap["ok"] is True
    assert bootstrap["postconditions"] == {
        "status": "passed",
        "class": "Monk",
        "ascendancy": "Invoker",
        "level": 20,
    }

    mechanism = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="mechanism_shell",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="set_main_skill",
                skill="Storm Wave",
            ),
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw=("Rarity: Normal\nSteelpoint Quarterstaff\nItem Level: 20"),
                slot="Weapon 1",
            ),
        ],
        expected_state_hash=bootstrap["outputStateHash"],
    )
    assert mechanism["ok"] is True
    assert mechanism["postconditions"]["weaponCompatibility"] == "compatible"

    before_failed_gear = mechanism["outputStateHash"]
    failed_gear = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="required_gear",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw="Rarity: Rare\nTransaction Ring\nRuby Ring\nItem Level: 20",
                slot="Ring 1",
            ),
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw="this is not a real PoE2 item",
                slot="Ring 2",
            ),
        ],
        expected_state_hash=before_failed_gear,
    )
    assert failed_gear["ok"] is False
    assert failed_gear["rolledBack"] is True
    assert failed_gear["persistedOperationCount"] == 0
    assert build_state_hash(engine.get_xml()) == before_failed_gear
    assert "Ring 1" not in engine.get_build()["gear"]


def test_public_batch_equip_rolls_back_unverified_special_source_item(engine):
    engine.new_build()
    engine.set_class("Monk", "Invoker")
    engine.set_level(80)
    before_hash = build_state_hash(engine.get_xml())
    unverified_rune_item = (
        "Rarity: Rare\nUnverified Rune Staff\nSteelpoint Quarterstaff\n"
        "Item Level: 80\nSockets: S\nRune: Iron Rune\nImplicits: 1\n"
        "{rune}+20 to Armour\n120% increased Physical Damage"
    )

    result = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="required_gear",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw=unverified_rune_item,
                slot="Weapon 1",
            )
        ],
        expected_state_hash=before_hash,
        result_decorator=main._decorate_batch_mutation_result,
    )

    assert result["ok"] is False
    assert result["rolledBack"] is True
    assert result["errorCode"] == "special_source_provenance_required"
    assert build_state_hash(engine.get_xml()) == before_hash


def test_verified_equip_clears_inherited_rune_from_same_slot(engine):
    engine.new_build()
    old = (
        "Rarity: Rare\nOld Rune Staff\nSteelpoint Quarterstaff\n"
        "Item Level: 80\nSockets: S\nRune: Iron Rune\nImplicits: 1\n"
        "{rune}+20 to Armour\n120% increased Physical Damage"
    )
    plain = (
        "Rarity: Rare\nPlain Staff\nSteelpoint Quarterstaff\n"
        "Item Level: 80\n120% increased Physical Damage"
    )
    assert engine.add_item(old, slot="Weapon 1")["ok"] is True

    result = equipment.equip_item_verified(
        engine,
        raw=plain,
        slot="Weapon 1",
        craft_receipt_ref=None,
    )

    assert result["ok"] is True
    assert result["readbackVerified"] is True
    actual = completeness.equipped_item_text(engine.get_xml(), "Weapon 1") or ""
    assert "Rune:" not in actual
    assert "{rune}" not in actual


def test_batch_equip_clears_inherited_rune_from_same_slot(engine):
    engine.new_build()
    old = (
        "Rarity: Rare\nOld Rune Staff\nSteelpoint Quarterstaff\n"
        "Item Level: 80\nSockets: S\nRune: Iron Rune\nImplicits: 1\n"
        "{rune}+20 to Armour\n120% increased Physical Damage"
    )
    plain = (
        "Rarity: Rare\nPlain Staff\nSteelpoint Quarterstaff\n"
        "Item Level: 80\n120% increased Physical Damage"
    )
    assert engine.add_item(old, slot="Weapon 1")["ok"] is True
    before = build_state_hash(engine.get_xml())

    result = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="required_gear",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw=plain,
                slot="Weapon 1",
            )
        ],
        expected_state_hash=before,
        result_decorator=main._decorate_batch_mutation_result,
    )

    assert result["ok"] is True
    actual = completeness.equipped_item_text(engine.get_xml(), "Weapon 1") or ""
    assert "Rune:" not in actual


def test_quiver_equip_is_rejected_in_batches():
    quiver_item = (
        "Rarity: Rare\nBatch Quiver\nVerdant Quiver\n"
        "Item Level: 82\nItem Class: Quiver\n+40 to maximum Life"
    )
    result = mutation_batch.apply_build_mutation_batch(
        engine=None,
        batch_kind="required_gear",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw=quiver_item,
                slot="Weapon 2",
            )
        ],
    )

    assert result["ok"] is False
    assert result["errorCode"] == "mutation_batch_quiver_requires_direct_equip"


def test_skill_group_replace_remove_and_stale_selector_fail_closed(engine):
    _monk_with_two_groups(engine)
    before = skillgroups.list_skill_groups(engine)
    main_fingerprint = before["groups"][0]["fingerprint"]
    secondary = before["groups"][1]

    replaced = skillgroups.replace_skill_group(
        engine,
        group_index=2,
        expected_fingerprint=secondary["fingerprint"],
        expected_state_hash=before["stateHash"],
        skill="Combat Frenzy",
    )

    assert replaced["ok"] is True
    assert replaced["mainGroupIndex"] == 1
    assert replaced["groups"][0]["fingerprint"] == main_fingerprint
    assert replaced["groups"][1]["activeSkill"] == "Combat Frenzy"

    state_after_replace = skillgroups.list_skill_groups(engine)
    stale = skillgroups.remove_skill_group(
        engine,
        group_index=2,
        expected_fingerprint=secondary["fingerprint"],
    )

    assert stale["ok"] is False
    assert stale["errorCode"] == "skill_group_conflict"
    assert skillgroups.list_skill_groups(engine)["stateHash"] == state_after_replace["stateHash"]

    current_secondary = state_after_replace["groups"][1]
    removed = skillgroups.remove_skill_group(
        engine,
        group_index=2,
        expected_fingerprint=current_secondary["fingerprint"],
        expected_state_hash=state_after_replace["stateHash"],
    )

    assert removed["ok"] is True
    assert len(removed["groups"]) == 1
    assert engine.get_build()["mainSkill"] == "Storm Wave"


def test_skill_group_main_invariants_and_rollback(engine):
    _monk_with_two_groups(engine)
    before = skillgroups.list_skill_groups(engine)
    main = before["groups"][0]

    disabled = skillgroups.set_skill_group_state(
        engine,
        group_index=1,
        expected_fingerprint=main["fingerprint"],
        enabled=False,
        expected_state_hash=before["stateHash"],
    )
    assert disabled["ok"] is False
    assert disabled["errorCode"] == "main_skill_group_cannot_be_disabled"
    assert skillgroups.list_skill_groups(engine)["stateHash"] == before["stateHash"]

    missing_replacement = skillgroups.remove_skill_group(
        engine,
        group_index=1,
        expected_fingerprint=main["fingerprint"],
        expected_state_hash=before["stateHash"],
    )
    assert missing_replacement["ok"] is False
    assert missing_replacement["errorCode"] == "replacement_main_group_required"
    assert skillgroups.list_skill_groups(engine)["stateHash"] == before["stateHash"]

    removed = skillgroups.remove_skill_group(
        engine,
        group_index=1,
        expected_fingerprint=main["fingerprint"],
        replacement_main_group_index=2,
        expected_state_hash=before["stateHash"],
    )
    assert removed["ok"] is True
    assert removed["mainGroupIndex"] == 1
    assert removed["groups"][0]["activeSkill"] == "Herald of Thunder"
    assert engine.get_build()["mainSkill"] == "Herald of Thunder"


def test_passive_optimizer_v2_preview_is_reproducible_and_commit_is_cas(engine):
    _monk_with_two_groups(engine)
    initial_hash = build_state_hash(engine.get_xml())

    first = passiveopt.optimize_passives(
        engine,
        metric="balanced",
        points=12,
        goals={"TotalEHP": 0.5, "TotalDPS": 0.5},
        preview=True,
        expected_state_hash=initial_hash,
    )
    second = passiveopt.optimize_passives(
        engine,
        metric="balanced",
        points=12,
        goals={"TotalDPS": 0.5, "TotalEHP": 0.5},
        preview=True,
        expected_state_hash=initial_hash,
    )

    assert first["ok"] is True and second["ok"] is True
    assert build_state_hash(engine.get_xml()) == initial_hash
    assert first["optimizerVersion"] == passiveopt.OPTIMIZER_VERSION
    assert first["requestHash"] == second["requestHash"]
    assert first["resultHash"] == second["resultHash"]
    assert first["allocatedNodeIds"] == second["allocatedNodeIds"]
    assert first["outputStateHash"] == second["outputStateHash"]
    assert first["metrics"] == second["metrics"]
    assert all("pathNodeIds" in step for step in first["allocated"])

    committed = passiveopt.optimize_passives(
        engine,
        metric="balanced",
        points=12,
        goals={"TotalDPS": 0.5, "TotalEHP": 0.5},
        expected_state_hash=initial_hash,
    )
    assert committed["ok"] is True
    assert committed["committed"] is True
    assert committed["committedStateHash"] == first["outputStateHash"]
    assert build_state_hash(engine.get_xml()) == first["outputStateHash"]

    conflict = passiveopt.optimize_passives(
        engine,
        points=1,
        preview=True,
        expected_state_hash=initial_hash,
    )
    assert conflict["ok"] is False
    assert conflict["errorCode"] == "build_state_conflict"


def test_passive_optimizer_preview_falls_back_safely_when_process_cap_is_full(engine, monkeypatch):
    _monk_with_two_groups(engine)
    initial_hash = build_state_hash(engine.get_xml())

    def no_capacity(**_kwargs):
        raise PobEngineError("PoB engine process limit reached (5)")

    monkeypatch.setattr(passiveopt, "PobEngine", no_capacity)
    result = passiveopt.optimize_passives(
        engine,
        metric="TotalDPS",
        points=3,
        preview=True,
        expected_state_hash=initial_hash,
    )

    assert result["ok"] is True
    assert result["executionMode"] == "active_snapshot_fallback"
    assert result["committed"] is False
    assert build_state_hash(engine.get_xml()) == initial_hash


def test_passive_optimizer_reset_required_plan_commits_previewed_snapshot(engine):
    engine.new_build()
    engine.set_class("Monk", "Martial Artist")
    engine.set_level(85)
    engine.paste_skill("Whirling Assault")
    initial_hash = build_state_hash(engine.get_xml())
    required = [
        1739,
        19370,
        17356,
        39595,
        34324,
        51707,
        34300,
        25362,
    ]

    preview = passiveopt.optimize_passives(
        engine,
        metric="TotalDPS",
        points=60,
        candidates=32,
        goals={"TotalDPS": 1.0, "TotalEHP": 0.65},
        require=required,
        reset=True,
        preview=True,
        expected_state_hash=initial_hash,
    )
    committed = passiveopt.optimize_passives(
        engine,
        metric="TotalDPS",
        points=60,
        candidates=32,
        goals={"TotalDPS": 1.0, "TotalEHP": 0.65},
        require=required,
        reset=True,
        expected_state_hash=preview["inputStateHash"],
    )

    assert preview["ok"] is True
    failure = {
        key: committed.get(key)
        for key in (
            "errorCode",
            "expectedStateHash",
            "actualStateHash",
            "expectedOutputStateHash",
            "actualOutputStateHash",
        )
    }
    assert committed["ok"] is True, failure
    assert committed["committed"] is True
    assert committed["committedStateHash"] == preview["outputStateHash"]
