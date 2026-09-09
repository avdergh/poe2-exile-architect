"""Real PoB regressions for the opt-in rare-item replacement measurement kernel."""

from __future__ import annotations

import re
from unittest.mock import Mock

import pytest

from server.compute import completeness, craftopt, equipment, item_search, itemopt, skillgroups
from server.compute.engine import PobEngine
from server.compute.state import build_state_hash
from server.knowledge import db


KEYS = ["TotalDPS", "ManaCost", "Life", "Str", "Dex", "Int", "FireResist", "ColdResist"]
STAFF = (
    "Rarity: Rare\nSource Context Staff\nAshen Staff\nItem Level: 90\n"
    "Implicits: 1\nGrants Skill: Level 20 Firebolt\n50% increased Spell Damage"
)


def _raw(base="Golden Visage", mods=(), slot="Helmet"):
    return itemopt._item_text(base, list(mods), slot, ilvl=90)


@pytest.fixture
def replacement_engine(fireball):
    fireball.set_class("Sorceress", "Stormweaver")
    fireball.set_level(90)
    fireball.set_config(custom_mods="+70 to Strength\n+70 to Dexterity\n+30% to Fire Resistance")
    return fireball


def _compare(engine, slot, candidates, *, all_measured=True):
    snapshot = engine.get_xml()
    before_hash = build_state_hash(snapshot)
    reference = engine.eval_items(slot, candidates, keys=KEYS, isolate_each_item=True)
    assert build_state_hash(engine.get_xml()) == before_hash
    fast = engine.eval_items(slot, candidates, keys=KEYS, replacement_context=True)
    assert fast["ok"], fast
    assert fast["rolledBack"] and not fast["recoveryRequired"]
    assert build_state_hash(engine.get_xml()) == before_hash
    assert len(fast["failureCodes"]) == len(candidates)
    assert len(fast["resolvedContexts"]) == len(candidates)
    for index, result in enumerate(fast["results"]):
        if not result:
            assert not all_measured, fast["failureCodes"]
            assert fast["failureCodes"][index]
            continue
        assert result == pytest.approx(reference["results"][index], rel=1e-8, abs=1e-6)
        assert fast["failureCodes"][index] is False
        assert fast["resolvedContexts"][index]["effectId"] == fast["calculationContext"]["effectId"]
    return fast


def test_engine_opt_in_preserves_existing_eval_parameters():
    engine = object.__new__(PobEngine)
    engine.call = Mock(return_value={})
    engine.eval_items("Helmet", ["item"], replacement_context=True)
    engine.call.assert_called_once_with(
        "eval_items", slot="Helmet", items=["item"], keys=None, replacementContext=True
    )
    engine.call.reset_mock()
    engine.eval_items("Helmet", ["item"], isolate_each_item=True)
    engine.call.assert_called_once_with(
        "eval_items", slot="Helmet", items=["item"], keys=None, isolateEachItem=True
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_alternating_complete_runes_equal_full_reload(replacement_engine, reverse):
    engine = replacement_engine
    bare = _raw()
    assert engine.add_item(bare, slot="Helmet")["ok"]
    rune = next(
        r
        for r in engine.crafting_options("Helmet")["runes"]
        if r["mods"] and not any(m.startswith("Bonded:") for m in r["mods"])
    )
    socketed = craftopt._build_item("Golden Visage", [], [(rune["name"], rune["mods"])], None, 90)
    assert engine.add_item(socketed, slot="Helmet")["ok"]
    candidates = [bare, socketed, _raw(mods=["+50 to Intelligence", "+30% to Cold Resistance"])] * 2
    if reverse:
        candidates.reverse()
    result = _compare(engine, "Helmet", candidates)
    assert result["fallbackCount"] == 0


def test_attribute_candidates_preserve_other_equipment_and_config(replacement_engine):
    engine = replacement_engine
    helmet = _raw(mods=["+100 to Strength"])
    assert engine.add_item(helmet, slot="Helmet")["ok"]
    base = db.pick_base("Body Armour", "str", max_drop_level=90)
    assert engine.add_item(_raw(base, slot="Body Armour"), slot="Body Armour")["ok"]
    _compare(engine, "Helmet", [_raw(), helmet, _raw(), helmet])


def test_wrong_parse_does_not_contaminate_following_candidate(replacement_engine):
    engine = replacement_engine
    result = _compare(
        engine,
        "Helmet",
        [_raw(), "not a valid item", _raw(mods=["+40% to Fire Resistance"]), _raw()],
        all_measured=False,
    )
    assert result["results"][1] is False
    assert result["failureCodes"][1] == "item_replacement_equip_failed"
    assert result["results"][0] == result["results"][3]


def _source(engine, supports=True):
    assert engine.add_item(STAFF, slot="Weapon 1")["ok"]
    listed = skillgroups.list_skill_groups(engine)
    target = next(group for group in listed["groups"] if group.get("sourceKind") == "item")
    if supports:
        result = skillgroups.configure_source_skill_supports(
            engine,
            source_group_index=target["index"],
            supports=["Rapid Casting II"],
            expected_fingerprint=target["fingerprint"],
            expected_state_hash=listed["stateHash"],
        )
        assert result["ok"], result
    engine.select_judge_skill(
        offense_skill_group_index=target["index"], expected_skill_name="Firebolt"
    )


def test_source_weapon_lost_support_cannot_return_other_skill_dps(replacement_engine):
    engine = replacement_engine
    _source(engine)
    snapshot = engine.get_xml()
    expected = engine.inspect_item_replacement_context()["calculationContext"]
    result = engine.eval_items(
        "Weapon 1", [STAFF, STAFF.replace("50%", "100%")], keys=KEYS, replacement_context=True
    )
    assert result["ok"] and result["rolledBack"], result
    assert result["results"] == [False, False]
    assert all(
        code in {"item_replacement_input_changed", "item_replacement_group_config_changed"}
        for code in result["failureCodes"]
    )
    assert build_state_hash(engine.get_xml()) == build_state_hash(snapshot)
    assert engine.inspect_item_replacement_context(expected)["ok"]


def test_other_slot_preserves_selected_source_supports(replacement_engine):
    engine = replacement_engine
    _source(engine)
    result = _compare(engine, "Helmet", [_raw(), _raw(mods=["+50 to Intelligence"]), _raw()])
    assert result["calculationContext"]["skillName"] == "Firebolt"
    assert result["calculationContext"]["ownerSlot"] == "Weapon 1"


def test_exact_effect_and_second_ordinary_group_survive_weapon_grants(replacement_engine):
    engine = replacement_engine
    engine.add_skill_group("Spark 20/0 1")
    engine.select_judge_skill(offense_skill_group_index=2, expected_skill_name="Spark")
    result = _compare(engine, "Weapon 1", [STAFF, _raw("Attuned Wand", slot="Weapon 1"), STAFF])
    assert result["calculationContext"]["ordinaryGroupOrdinal"] == 2
    assert all(c["skillName"] == "Spark" for c in result["resolvedContexts"])


def test_inspection_rejects_support_changes_and_resolves_unselected_owner(replacement_engine):
    engine = replacement_engine
    engine.add_skill_group("Spark 20/0 1")
    engine.select_judge_skill(offense_skill_group_index=2, expected_skill_name="Spark")
    context = engine.inspect_item_replacement_context()["calculationContext"]
    engine.call("set_main_socket_group", index=1, activeIndex=1)
    resolved = engine.inspect_item_replacement_context(context)
    assert resolved["ok"]
    assert resolved["calculationContext"]["groupIndex"] == 2
    assert engine.call("list_skill_groups")["mainGroupIndex"] == 1
    corrupted = dict(context, effectId="FireballPlayer", skillName="Fireball")
    assert not engine.inspect_item_replacement_context(corrupted)["ok"]

    # Selecting another Judge target also rewrites FullDPS membership; that is a real
    # configuration change and must not be silently repaired by context resolution.
    engine.select_judge_skill(offense_skill_group_index=1, expected_skill_name="Fireball")
    assert not engine.inspect_item_replacement_context(context)["ok"]


def test_non_first_effect_in_same_group_is_bound(replacement_engine):
    engine = replacement_engine
    engine.paste_skill("Fireball 20/0 1\nSpark 20/0 1\nRapid Casting II 1/0 1")
    engine.select_judge_skill(offense_skill_group_index=1, expected_skill_name="Spark")
    result = _compare(engine, "Helmet", [_raw(), _raw(mods=["+60 to Intelligence"]), _raw()])
    assert result["calculationContext"]["activeSkillIndex"] == 2
    assert result["calculationContext"]["skillName"] == "Spark"


def test_no_skill_allows_defense_only_but_not_unknown_offense(engine):
    engine.new_build()
    assert engine.inspect_item_replacement_context() == {
        "ok": True,
        "contextStatus": "no_active_output",
    }
    initial_hash = build_state_hash(engine.get_xml())
    measured = engine.eval_items(
        "Helmet", [_raw()], keys=["Life", "EnergyShield", "FireResist"], replacement_context=True
    )
    assert measured["ok"] and measured["rolledBack"], measured
    assert measured["results"][0]["Life"] > 0
    assert "calculationContext" not in measured
    failed = engine.eval_items("Helmet", [_raw()], keys=["TotalDPS"], replacement_context=True)
    assert failed["results"] == [False]
    assert failed["failureCodes"] == ["item_replacement_context_missing"]
    assert failed["rolledBack"]
    assert build_state_hash(engine.get_xml()) == initial_hash


def test_source_root_level_change_does_not_weaken_manual_support_binding(replacement_engine):
    engine = replacement_engine
    _source(engine)
    expected = engine.inspect_item_replacement_context()["calculationContext"]
    snapshot = engine.get_xml()
    changed = snapshot.replace("Grants Skill: Level 20 Firebolt", "Grants Skill: Level 19 Firebolt")
    changed = re.sub(
        r'<Gem\b[^>]*\bskillId="FireboltPlayer"[^>]*/>',
        lambda match: match.group().replace('level="20"', 'level="19"'),
        changed,
    )
    engine.load_build_xml(changed)
    resolved = engine.inspect_item_replacement_context(expected)
    assert resolved["ok"], resolved
    assert resolved["calculationContext"]["rootLevel"] == 19
    # User support quality/enable flags remain exact even when the root level can change.
    changed = re.sub(
        r'<Gem\b[^>]*\bskillId="SupportRapidCastingPlayerTwo"[^>]*/>',
        lambda match: match.group().replace('quality="20"', 'quality="0"'),
        changed,
    )
    engine.load_build_xml(changed)
    assert not engine.inspect_item_replacement_context(expected)["ok"]


def test_tree_source_command_stays_on_its_owner(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Disciple of Varashta")
    engine.set_level(95)
    assert engine.alloc_passive(34207)["ok"]
    listed = skillgroups.list_skill_groups(engine)
    target = listed["groups"][0]
    selected = skillgroups.set_skill_group_state(
        engine,
        group_index=target["index"],
        expected_fingerprint=target["fingerprint"],
        expected_state_hash=listed["stateHash"],
        active_skill_index=2,
        make_main=True,
    )
    assert selected["ok"]
    result = _compare(engine, "Helmet", [_raw(), _raw(mods=["+60 to Intelligence"]), _raw()])
    assert result["calculationContext"]["sourceKind"] == "tree"
    assert result["calculationContext"]["sourceIdentity"] == "Tree:34207"
    assert result["calculationContext"]["activeSkillIndex"] == 2


@pytest.mark.parametrize("starts_derived", [False, True])
def test_native_unconfigured_derived_group_can_appear_and_disappear(
    replacement_engine, starts_derived
):
    engine = replacement_engine
    plain = _raw("Feathered Raiment", slot="Body Armour")
    thorns = _raw("Feathered Raiment", ["144 to 210 Physical Thorns damage"], "Body Armour")
    assert engine.add_item(thorns if starts_derived else plain, slot="Body Armour")["ok"]
    result = _compare(engine, "Body Armour", [thorns, plain, thorns, plain])
    assert all(row["skillName"] == "Fireball" for row in result["resolvedContexts"])
    assert result["fallbackCount"] == 0


@pytest.mark.parametrize(
    "settings",
    [{"enabled": False}, {"includeInFullDPS": True}, {"label": "User configured derived output"}],
)
def test_manual_derived_configuration_cannot_be_discarded(replacement_engine, settings):
    engine = replacement_engine
    plain = _raw("Feathered Raiment", slot="Body Armour")
    thorns = _raw("Feathered Raiment", ["144 to 210 Physical Thorns damage"], "Body Armour")
    assert engine.add_item(thorns, slot="Body Armour")["ok"]
    groups = engine.call("list_skill_groups")["groups"]
    target = next(group for group in groups if group.get("sourceKind") == "other")
    assert engine.call("set_skill_group_state", index=target["index"], **settings)["ok"]
    initial_hash = build_state_hash(engine.get_xml())
    result = engine.eval_items("Body Armour", [plain, thorns], keys=KEYS, replacement_context=True)
    assert result["ok"] and result["rolledBack"], result
    assert result["results"][0] is False
    assert isinstance(result["results"][1], dict)
    assert result["failureCodes"] == ["item_replacement_input_changed", False]
    assert build_state_hash(engine.get_xml()) == initial_hash
    preserved = next(
        group
        for group in engine.call("list_skill_groups")["groups"]
        if group.get("sourceKind") == "other"
    )
    assert all(preserved[key] == value for key, value in settings.items())


def test_original_derived_target_must_still_exist(replacement_engine):
    engine = replacement_engine
    plain = _raw("Feathered Raiment", slot="Body Armour")
    thorns = _raw("Feathered Raiment", ["144 to 210 Physical Thorns damage"], "Body Armour")
    assert engine.add_item(thorns, slot="Body Armour")["ok"]
    target = next(
        group
        for group in engine.call("list_skill_groups")["groups"]
        if group.get("sourceKind") == "other"
    )
    # Select only: keep native FullDPS/label settings so the input guard may ignore this
    # default derived group; the separate numerical target contract must reject its loss.
    engine.call("set_main_socket_group", index=target["index"], activeIndex=1)
    initial_hash = build_state_hash(engine.get_xml())
    result = engine.eval_items("Body Armour", [plain, thorns], keys=KEYS, replacement_context=True)
    assert result["ok"] and result["rolledBack"], result
    assert result["results"][0] is False
    assert result["failureCodes"][0] == "item_replacement_context_mismatch"
    assert isinstance(result["results"][1], dict), result
    assert result["resolvedContexts"][1]["effectId"] == result["calculationContext"]["effectId"]
    assert build_state_hash(engine.get_xml()) == initial_hash


def test_manual_derived_configuration_can_be_preserved_by_another_source(replacement_engine):
    engine = replacement_engine
    thorns = _raw(mods=["144 to 210 Physical Thorns damage"])
    assert engine.add_item(thorns, slot="Helmet")["ok"]
    target = next(
        group
        for group in engine.call("list_skill_groups")["groups"]
        if group.get("sourceKind") == "other"
    )
    assert engine.call(
        "set_skill_group_state",
        index=target["index"],
        enabled=False,
        includeInFullDPS=True,
        label="Preserve user configuration",
    )["ok"]
    plain = _raw("Feathered Raiment", slot="Body Armour")
    extra = _raw("Feathered Raiment", ["144 to 210 Physical Thorns damage"], "Body Armour")
    result = _compare(engine, "Body Armour", [plain, extra, plain])
    assert result["fallbackCount"] == 0


def test_unselected_secondary_curse_default_does_not_fake_restore_failure(engine):
    engine.new_build()
    engine.set_class("Witch", "Lich")
    engine.set_level(90)
    engine.paste_skill("Essence Drain 20/0 1")
    engine.add_skill_group("Despair 20/0 1")
    engine.select_judge_skill(offense_skill_group_index=1, expected_skill_name="Essence Drain")
    engine.set_config(
        options={"conditionEnemyCursed": True},
        custom_mods="+80% to Chaos Resistance\n+110% to all Elemental Resistances",
    )
    bare = _raw()
    assert engine.add_item(bare, slot="Helmet")["ok"]
    rune = next(
        option
        for option in engine.crafting_options("Helmet")["runes"]
        if option["name"] == "Tacati's Soul Core of Affliction"
    )
    socketed = craftopt._augment_item_with_runes(bare, [(rune["name"], rune["mods"])])
    before = engine.get_xml()
    assert 'mainActiveSkill="nil"' in before
    context = engine.inspect_item_replacement_context()["calculationContext"]
    keys = ["TotalDPS", "FullDPS", "ChaosResist", "CombinedDPS"]
    # Do not first call the full-reload oracle: that would normalise the secondary group's
    # unset defaults and hide the regression in the first real replacement batch.
    result = engine.eval_items("Helmet", [bare, socketed], keys=keys, replacement_context=True)
    assert result["ok"] and result["rolledBack"] and not result["recoveryRequired"], result
    assert result["failureCodes"] == [False, False]
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)
    assert engine.inspect_item_replacement_context(context)["ok"]
    assert all(row["effectId"] == "EssenceDrainPlayer" for row in result["resolvedContexts"])
    reference = engine.eval_items("Helmet", [bare, socketed], keys=keys, isolate_each_item=True)
    assert result["results"] == reference["results"]


def _bow_with_quiver(engine, character="Huntress", ascendancy="Amazon", skill="Ice Shot"):
    engine.new_build()
    engine.set_class(character, ascendancy)
    engine.set_level(95)
    engine.paste_skill(f"{skill} 20/0 1")
    engine.set_config(custom_mods="+300 to Dexterity")
    bow = _raw("Gemini Bow", ["100% increased Physical Damage"], "Weapon 1")
    stronger = _raw("Gemini Bow", ["150% increased Physical Damage"], "Weapon 1")
    quiver = "Rarity: Unique\nCadiro's Gambit\nPrimed Quiver\n9% increased Attack Speed\nEach Arrow fired is a Crescendo, Splinter, Reversing, Diamond, Covetous, or Blunt Arrow"
    assert engine.add_item(bow, slot="Weapon 1")["ok"]
    assert engine.add_item(quiver, slot="Weapon 2")["ok"]
    return bow, stronger


@pytest.mark.parametrize(
    "character,ascendancy,skill",
    [("Huntress", "Amazon", "Ice Shot"), ("Ranger", "Deadeye", "Lightning Arrow")],
)
def test_bow_replacement_keeps_existing_quiver(engine, character, ascendancy, skill):
    bow, stronger = _bow_with_quiver(engine, character, ascendancy, skill)
    before = engine.get_xml()
    initial_stats = engine.get_stats(KEYS)["stats"]
    result = engine.eval_items(
        "Weapon 1", [bow, stronger, bow], keys=KEYS, replacement_context=True
    )
    assert result["ok"] and result["rolledBack"] and not result["recoveryRequired"], result
    assert result["failureCodes"] == [False, False, False], result
    assert result["results"][0] == pytest.approx(initial_stats)
    assert result["results"][2] == pytest.approx(initial_stats)
    assert result["results"][1]["TotalDPS"] > initial_stats["TotalDPS"]
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)
    assert engine.get_build()["gear"]["Weapon 2"]["name"] == "Cadiro's Gambit"
    reference = engine.eval_items(
        "Weapon 1", [bow, stronger, bow], keys=KEYS, isolate_each_item=True
    )
    assert reference["results"] == result["results"]


def test_incompatible_weapon_cannot_drop_quiver_and_contaminate_next_probe(engine):
    bow, _ = _bow_with_quiver(engine)
    before = engine.get_xml()
    stats = engine.get_stats(KEYS)["stats"]
    result = engine.eval_items("Weapon 1", [STAFF, bow], keys=KEYS, replacement_context=True)
    assert result["ok"] and result["rolledBack"] and not result["recoveryRequired"], result
    assert result["failureCodes"] == ["item_replacement_input_changed", False]
    assert result["results"][0] is False
    assert result["results"][1] == pytest.approx(stats)
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)


def test_complete_bow_writes_and_socket_probes_never_inherit_old_runes(engine):
    bow, stronger = _bow_with_quiver(engine)
    quiver = completeness.equipped_item_text_from_engine(engine, "Weapon 2")
    rune = next(
        option
        for option in engine.crafting_options("Weapon 1")["runes"]
        if option["mods"] and not any(mod.startswith("Bonded:") for mod in option["mods"])
    )
    socketed = craftopt._augment_item_with_runes(bow, [(rune["name"], rune["mods"])])
    context = item_search.capture_context(engine)
    for raw in [socketed, stronger, socketed, bow]:
        craftopt._socket_add_item(engine, raw, "Weapon 1")
        assert craftopt._socket_item_readback_matches(
            raw, completeness.equipped_item_text_from_engine(engine, "Weapon 1")
        )
        assert completeness.equipped_item_text_from_engine(engine, "Weapon 2") == quiver
    item_search.equip_candidate(engine, stronger, "Weapon 1", context)
    assert completeness.equipped_item_text_from_engine(engine, "Weapon 2") == quiver
    # Exercise the public/batch shared write after a socketed old weapon as well.
    assert engine.add_item(socketed, slot="Weapon 1")["ok"]
    result = equipment.equip_item_verified(engine, raw=bow, slot="Weapon 1", craft_receipt_ref=None)
    assert result["ok"] and result["readbackVerified"], result
    assert completeness.equipped_item_text_from_engine(engine, "Weapon 2") == quiver
    assert "Rune:" not in completeness.equipped_item_text_from_engine(engine, "Weapon 1")


def test_gear_plan_replays_bow_with_the_original_quiver(engine):
    _bow_with_quiver(engine)
    snapshot = engine.get_xml()
    result = itemopt.plan_gear(
        engine, slots=["Weapon 1"], locked_slots=["Weapon 2"], auto_base=False, stage="endgame"
    )
    assert result["ok"] and result["planReplayVerified"], result
    assert len(result["plan"]) == 1 and result["plan"][0]["slot"] == "Weapon 1"
    assert build_state_hash(engine.get_xml()) == build_state_hash(snapshot)
    entry = result["plan"][0]
    assert engine.add_item(entry["item"], slot=entry["slot"])["ok"]
    assert engine.get_build()["gear"]["Weapon 2"]["name"] == "Cadiro's Gambit"
    assert engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(
        result["projected"]["TotalDPS"], abs=0.01
    )
