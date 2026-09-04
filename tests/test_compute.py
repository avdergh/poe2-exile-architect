"""Golden-value tests for the headless calculation engine + import codec.

Values are pinned to the PoB-PoE2 commit in pob/PINNED.md; if you bump the submodule and
these drift, re-verify against the GUI and update them in the same commit.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from server import main, paths
from server.compute import buildopt, craftopt, itemopt, mutation_batch
from server.compute.engine import PobEngine
from server.compute.pob_code import decode_code, encode_code
from server.compute.state import build_state_hash
from server.judge import hard_legality
from server.knowledge import db, itemparse, refbuilds

FIREBALL_DPS = 124.833
FIREBALL_AVG = 149.8


def test_ping(engine):
    assert engine.ping()["pong"] is True


def test_real_lifetap_signature_reads_life_cost_domain(engine):
    from server.generation import mechanism_signature

    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(95)
    engine.paste_skill("Spark 20/20 1 / Lifetap")

    result = mechanism_signature.observe(
        engine,
        {"offenseSkillGroupIndex": 1, "activeSkillName": "Spark"},
    )

    assert result["ok"] is True
    assert result["signature"]["resourceCostDomains"] == ["life"]
    assert "Lifetap" in result["signature"]["supportNames"]
    assert "lightning" in result["signature"]["hitDamageTypes"]
    assert engine.info["runtimeContract"] == paths.POB_RUNTIME_CONTRACT


def test_fireball_golden(fireball):
    s = fireball.get_stats(["TotalDPS", "AverageDamage", "Speed"])["stats"]
    assert s["TotalDPS"] == pytest.approx(FIREBALL_DPS, rel=1e-3)
    assert s["AverageDamage"] == pytest.approx(FIREBALL_AVG, rel=1e-3)
    assert s["Speed"] == pytest.approx(0.8333, rel=1e-2)


def test_import_code_roundtrip(fireball):
    xml = fireball.get_xml()
    assert "PathOfBuilding2" in xml
    assert decode_code(encode_code(xml)) == xml


def test_import_reproduces_stats(engine):
    engine.new_build()
    engine.paste_skill("Fireball 20/0  1")
    xml = engine.get_xml()
    engine.new_build()
    res = engine.load_build_xml(xml)
    assert res["mainSkill"] == "Fireball"
    assert res["treeVersion"]
    assert res["stats"]["TotalDPS"] == pytest.approx(FIREBALL_DPS, rel=1e-3)


def test_custom_mod_increases_dps(fireball):
    before = fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    after = fireball.set_config(custom_mods="100% increased Fire Damage")["stats"]["TotalDPS"]
    assert after > before


def test_public_combat_profile_true_then_false_restores_semantic_state(engine, monkeypatch):
    from server import main
    from server.compute.state import build_state_hash

    engine.new_build()
    engine.paste_skill("Fireball 20/0  1")
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    baseline = main.apply_combat_profile(
        tier="Pinnacle",
        shocked=False,
        cursed=False,
        power_charges=False,
        frenzy_charges=False,
        full_es=False,
        full_life=False,
    )
    enabled = main.apply_combat_profile(
        tier="Pinnacle",
        shocked=True,
        cursed=True,
        power_charges=True,
        frenzy_charges=True,
        full_es=True,
        full_life=True,
        expected_state_hash=baseline["stateHash"],
    )
    disabled = main.apply_combat_profile(
        tier="Pinnacle",
        shocked=False,
        cursed=False,
        power_charges=False,
        frenzy_charges=False,
        full_es=False,
        full_life=False,
        expected_state_hash=enabled["stateHash"],
    )

    assert disabled["stateHash"] == baseline["stateHash"]
    assert disabled["stateHash"] == build_state_hash(engine.get_xml())
    assert disabled["appliedProfile"]["cursed"] is False


def test_equip_item_returns_stats(fireball):
    res = fireball.add_item("New Item\nElementalist Robe")
    assert "TotalDPS" in res["stats"]


def test_equip_replaces_slot(fireball):
    craft = "Rarity: Rare\nWand\nAttuned Wand\n{}% increased Cast Speed".format
    fireball.add_item(craft(10))
    s1 = fireball.get_stats(["Speed"])["stats"]["Speed"]
    fireball.add_item(craft(25))  # same slot -> must replace, not be ignored
    s2 = fireball.get_stats(["Speed"])["stats"]["Speed"]
    assert s2 > s1


def test_import_code_fixture(engine):
    # A real build serialized through the actual codec; locks the import + codec + engine path.
    code = (Path(__file__).parent / "fixtures" / "witchhunter_detonate.pobcode").read_text().strip()
    engine.new_build()
    r = engine.load_build_code(code)
    assert r["mainSkill"] == "Detonate Living"
    b = engine.get_build()
    assert b["class"] == "Mercenary" and b["level"] == 90


def test_witchhunter_on_kill_explosion_is_supplemental_not_primary(engine):
    code = (Path(__file__).parent / "fixtures" / "witchhunter_detonate.pobcode").read_text().strip()
    engine.new_build()
    engine.load_build_code(code)

    build = engine.select_judge_skill(
        offense_skill_group_index=1,
        expected_skill_name="Detonate Living",
    )

    assert build["selectedSkill"]["skillName"] == "Detonate Living"
    assert build["selectedSkill"]["groupOrigin"] == "socketed"
    explosion = next(
        component
        for component in build["supplementalSkills"]
        if component["groupOrigin"] == "synthetic_on_kill"
    )
    assert explosion["skillName"] == "On Kill Monster Explosion"
    assert explosion["socketLegalityApplicable"] is False
    assert explosion["scenarioLimitations"] == ["requires_kill"]


def test_reactive_thorns_is_supplemental_not_primary(engine):
    engine.new_build()
    engine.set_class("Warrior")
    engine.paste_skill("Fireball 1/0  1")
    engine.add_item(
        "Rarity: Rare\n"
        "Test Shell\n"
        "Thane Mail\n"
        "--------\n"
        "Armour: 100\n"
        "Evasion Rating: 100\n"
        "--------\n"
        "101 to 220 Physical Thorns damage"
    )

    build = engine.select_judge_skill(
        offense_skill_group_index=1,
        expected_skill_name="Fireball",
    )

    assert build["selectedSkill"]["skillName"] == "Fireball"
    assert build["selectedSkill"]["groupOrigin"] == "socketed"
    thorns = next(
        component
        for component in build["supplementalSkills"]
        if component["groupOrigin"] == "synthetic_reactive"
    )
    assert thorns["skillName"] == "Thorns"
    assert thorns["socketLegalityApplicable"] is False
    assert thorns["scenarioLimitations"] == ["requires_enemy_hit"]


def test_import_build_rejects_garbage():
    from server.main import import_build

    r = import_build("@@@ not a valid build @@@")
    assert r.get("ok") is False and "error" in r


def test_solve_for_reaches_target(fireball):
    from server.compute import solver

    base = fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    r = solver.solve_for(fireball, "TotalDPS", base * 2, "increased fire damage")
    assert r["ok"] and r.get("reachable")
    assert r["requiredMagnitude"] > 0
    assert r["achievedValue"] >= base * 2 * 0.98  # within bisection tolerance
    # the build must be restored —no lingering custom mod from probing
    assert fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(base, rel=1e-6)


def test_damage_diagnostic_flags_buff_skill(engine):
    # A reservation/buff skill computes ~0 DPS by design; the diagnostic must say so (not silence).
    engine.new_build()
    engine.set_class("Witch", "Infernalist")
    engine.set_level(90)
    engine.paste_skill("Plague Bearer 20/20  1")
    r = engine.get_stats(["TotalDPS"])
    assert (r["stats"].get("TotalDPS") or 0) == 0
    assert r.get("warning") and "buff/reservation" in r["warning"]


def _spark_caster(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.add_item(
        "Rarity: Rare\nW\nDueling Wand\n+5 to Level of all Lightning Spell Skills\n"
        "Adds 1 to 85 Lightning Damage to Spells\n112% increased Spell Damage"
    )


def test_paste_tolerates_missing_count(engine):
    # Supports written without the trailing count must not be silently dropped (#4).
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20\nLightning Penetration 20/20")
    b = engine.get_build()
    names = [g["name"] for g in b["mainSkillGroup"]]
    assert "Controlled Destruction" in names and "Lightning Penetration" in names
    assert b["treeVersion"] and b["latestTreeVersion"]
    assert "normalPassivePointsUsed" in b
    assert "weaponSet1PointsUsed" in b
    assert "weaponSet2PointsUsed" in b
    assert "weaponSetPointsAvailable" in b
    assert set(b["attributes"]) == {"strength", "dexterity", "intelligence"}
    assert set(b["attributeRequirements"]) == {"strength", "dexterity", "intelligence"}
    assert "spiritUsed" in b
    assert "spiritAvailable" in b
    assert b["spiritUsed"] == b["spiritRequested"]
    assert b["spiritReservedCapped"] == min(b["spiritRequested"], b["spiritAvailable"])
    assert b["spiritRequested"] == b["spiritAvailable"] - b["spiritUnreserved"]
    assert b["spiritOverBy"] == max(0, -b["spiritUnreserved"])
    assert b["activeWeaponSet"] in {1, 2}
    by_name = {g["name"]: g for g in b["mainSkillGroup"]}
    assert by_name["Spark"]["isSupport"] is False
    assert by_name["Controlled Destruction"]["isSupport"] is True


def test_multiprojectile_dps_note(engine):
    # Hit DPS and projectile count need a per-skill overlap caveat, not a manual count multiplier.
    _spark_caster(engine)
    r = engine.paste_skill("Spark 20/20  1")
    assert (r["stats"].get("ProjectileCount") or 0) > 1
    assert r.get("dpsNote") and "projectile" in r["dpsNote"].lower()


def test_support_level_does_not_change_dps(engine):
    # PoE2 supports are fixed-effect (don't scale with gem level); level field is cosmetic (#3).
    _spark_caster(engine)
    lvl1 = engine.paste_skill("Spark 20/20  1\nControlled Destruction 1/20  1")["stats"]["TotalDPS"]
    _spark_caster(engine)
    lvl20 = engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")["stats"][
        "TotalDPS"
    ]
    assert lvl1 == pytest.approx(lvl20, rel=1e-6)


def test_add_skill_group_applies_aura_without_changing_main(engine):
    # A second enabled group (Archmage) must buff the main skill, not replace it (#1).
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")
    engine.set_config(custom_mods="+2000 to maximum Mana")
    before = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    engine.add_skill_group("Archmage 20/20  1")
    after = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    assert engine.get_build()["mainSkill"] == "Spark"  # main unchanged
    assert after > before * 1.2  # Archmage's mana-based damage applied


def test_optimize_passives_spends_more_via_small_pass(engine):
    # After the Notables pass plateaus, a second small/travel-node pass spends leftover budget the
    # old single pass stranded (#5). The greedy is deterministic now (stable candidate ordering),
    # so this is stable; remaining points on a gear-less skeleton are legitimately unplaceable.
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")
    r = engine.optimize_passives(metric="balanced", points=0)
    assert r["smallNodePoints"] >= 1  # the small-node pass placed points Notables-only would strand
    assert r["pointsUsed"] >= 60  # a solid majority of the build's worthwhile nodes


def test_optimize_passives_is_deterministic(engine):
    # Stable scoring/order -> identical node set and semantic state, not merely the same point count.
    from server.compute.state import build_state_hash

    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")
    first = engine.optimize_passives(metric="balanced", points=0)
    first_hash = build_state_hash(engine.get_xml())
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")
    second = engine.optimize_passives(metric="balanced", points=0)
    second_hash = build_state_hash(engine.get_xml())
    assert first["pointsUsed"] == second["pointsUsed"]
    assert first["allocatedNodeIds"] == second["allocatedNodeIds"]
    assert first_hash == second_hash


def test_eval_items_batches_and_restores(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    engine.add_item("Rarity: Rare\nOrig\nDueling Wand\n20% increased Spell Damage", slot="Weapon 1")
    base = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    cands = [
        "Rarity: Rare\nA\nDueling Wand\n150% increased Spell Damage",
        "Rarity: Rare\nB\nDueling Wand\n+5 to Level of all Lightning Spell Skills",
    ]
    res = engine.eval_items("Weapon 1", cands, keys=["TotalDPS"])["results"]
    assert all(r and r["TotalDPS"] > 0 for r in res)
    # build restored to the original item, not the last candidate
    assert engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(base, rel=1e-6)


def test_eval_items_jewel_socket_computes_radius_grants_and_restores(engine):
    engine.new_build()
    engine.set_class("Witch", "Blood Mage")
    engine.set_level(85)
    engine.paste_skill("Spark 19/0  1")
    engine.alloc_passive(2491)
    engine.alloc_passive(18157)  # Notable inside socket 2491's Large radius
    base = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    time_lost = (
        "Rarity: Unique\nTest Time-Lost Emerald\nTime-Lost Emerald\nItem Level: 84\nRadius: Large\n"
        "Small Passive Skills in Radius also grant 10% increased Spell Damage\n"
        "Notable Passive Skills in Radius also grant 8% increased Cast Speed"
    )
    res = engine.eval_items("Jewel 2491", [time_lost], keys=["TotalDPS"])["results"]
    assert res and res[0] and res[0]["TotalDPS"] > base * 1.05  # radius grants were computed
    assert engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(base, rel=1e-6)


def test_optimize_passives_weighted_goals(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.add_item("Rarity: Rare\nW\nDueling Wand\n100% increased Spell Damage")
    engine.paste_skill("Spark 20/20  1")
    r = engine.optimize_passives(goals={"TotalDPS": 0.5, "Life": 0.5}, points=40)
    assert r["metric"] == "weighted"
    m = r["metrics"]
    assert (
        m["Life"]["final"] >= m["Life"]["start"] and m["TotalDPS"]["final"] > m["TotalDPS"]["start"]
    )


def test_optimize_passives_require_forces_node(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    r = engine.optimize_passives(metric="TotalDPS", points=20, require=["Eldritch Battery"])
    assert any(a.get("required") and a["name"] == "Eldritch Battery" for a in r["allocated"])
    assert r.get("requiredPoints", 0) > 0


def test_optimize_item_improves_and_is_valid(engine):
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.add_item(
        "Rarity: Rare\nBasic\nDueling Wand\n20% increased Spell Damage", slot="Weapon 1"
    )
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")  # non-crit
    base = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    r = itemopt.optimize_item(engine, "Weapon 1", metric="TotalDPS", rolls="max", thorough=True)
    assert r["ok"] and r["metricAfter"] > r["metricBefore"]
    assert r["legalityCheck"]["ok"] is True
    assert len(r["affixes"]) <= 6  # respects 3 prefix / 3 suffix
    # build-aware: a non-crit lightning build's max-DPS wand uses a Lightning mod
    assert any("Lightning" in a for a in r["affixes"])
    # probing is restored
    assert engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(base, rel=1e-6)


@pytest.mark.parametrize("strategy", ["recovery", "sustain", "instant"])
def test_optimize_flask_round_trips_legal_magic_item_and_restores_build(engine, strategy):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(95)
    before = engine.get_xml()

    result = itemopt.optimize_flask(
        engine,
        "Flask 2",
        base="Ultimate Mana Flask",
        ilvl=82,
        strategy=strategy,
    )

    assert result["ok"] is True
    assert result["item"].startswith("Rarity: Magic\nUltimate Mana Flask\n")
    assert result["legalityCheck"]["ok"] is True
    parsed = itemparse.parse_item(result["item"])
    assert parsed["rarity"] == "Magic"
    assert parsed["base"] == "Ultimate Mana Flask"
    assert parsed["prefixes"] == 1
    assert parsed["suffixes"] == 1
    assert parsed["affixes"]
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)


def test_optimize_flask_rejects_utility_flask_charm_without_mutating_real_pob(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(95)
    before = build_state_hash(engine.get_xml())

    result = itemopt.optimize_flask(engine, "Flask 1", base="Grounding Charm")

    assert result["ok"] is False
    assert result["errorCode"] == "invalid_flask_base"
    assert build_state_hash(engine.get_xml()) == before


def test_optimize_item_on_empty_weapon_slot_for_attack_skill(engine):
    # Regression: a from-scratch attack build optimizes the WEAPON slot first, before any weapon is
    # equipped. The skill is then uncomputable (DPS ~0) and the engine returns stats=[] (an empty Lua
    # table serializes to JSON [], not {}), which crashed optimize_item with "'list' object has no
    # attribute 'get'". It must instead craft a weapon and make DPS computable.
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")  # attack, no weapon -> uncomputable
    # Keep this regression focused on empty-slot crafting. Attribute-invalid weapon candidates are
    # rejected separately by the shared whole-build legality audit.
    engine.set_config(custom_mods="+200 to Strength\n+200 to Dexterity")
    assert isinstance(
        engine.get_stats(["TotalDPS"])["stats"], dict
    )  # not [] even when uncomputable
    r = itemopt.optimize_item(engine, "Weapon 1", base="Grand Spear", metric="TotalDPS")
    assert r["ok"]
    assert r["metricBefore"] is None  # no weapon -> nothing to measure before
    assert isinstance(r["metricAfter"], (int, float)) and r["metricAfter"] > 0
    assert r["affixes"]  # crafted a real spear


def test_optimize_item_rejects_empty_weapon_candidate_with_new_attribute_shortfall(engine):
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")

    result = itemopt.optimize_item(engine, "Weapon 1", base="Grand Spear", metric="TotalDPS")

    assert result["ok"] is False
    assert result["errorCode"] == "whole_build_legality_check_failed"
    assert any(
        reason["code"] == "attribute_requirement_unmet"
        and reason["change"] in {"introduced", "worsened"}
        for reason in result["rejectionReasons"]
    )


def test_optimize_item_low_ilvl_weapon_passes_shared_legality_audit(engine):
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Monk", "Martial Artist")
    engine.set_level(18)
    engine.paste_skill("Glacial Cascade")

    r = itemopt.optimize_item(
        engine,
        "Weapon 1",
        base="Crackling Quarterstaff",
        ilvl=18,
        goals={"TotalDPS": 0.75, "TotalEHP": 0.25},
        keep_resists_capped=False,
    )

    assert r["ok"] is True
    assert r["itemLevel"] == 18
    assert r["legalityCheck"]["ok"] is True
    assert all(affix["ilvl"] <= 18 for affix in r["attainability"])


def test_optimize_item_warns_when_it_breaks_resist_cap(engine):
    # Regression: the break check uses resistMissing (gap below the real per-element cap), NOT the
    # floored *ResistOverCap. PoB floors over-cap at 0, so the old "over-cap goes negative" check was
    # dead and the "drops resistance below cap" warning never fired.
    from server import scaffold
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_item(
        "Rarity: Rare\nX\nGrand Spear\n--------\nAdds 40 to 80 Lightning Damage", slot="Weapon 1"
    )
    scaffold.scaffold_gear(engine, pool="life", target_resist=75)
    assert engine.get_defenses()["resistMissing"] == {"fire": 0, "cold": 0, "lightning": 0}
    # a max-DPS amulet carries no resistances, so replacing the scaffold amulet must break a cap
    r = itemopt.optimize_item(engine, "Amulet", metric="TotalDPS")
    assert any("below cap" in w for w in r["warnings"])


def test_optimize_item_blended_goals_balances_offense_and_defense(engine):
    # Weighted `goals` craft ONE piece carrying both damage and defense —the realistic-gear path,
    # vs a single-metric craft that strips the other axis.
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_item(
        "Rarity: Rare\nX\nGrand Spear\n--------\nAdds 40 to 80 Lightning Damage", slot="Weapon 1"
    )
    blend = itemopt.optimize_item(
        engine, "Amulet", base="Absent Amulet", goals={"TotalDPS": 0.6, "TotalEHP": 0.4}
    )
    assert blend["ok"] and "goals" in blend
    assert set(blend["metricsBefore"]) == {"TotalDPS", "TotalEHP"}
    # one craft lifts BOTH axes above the current state...
    assert blend["metricsAfter"]["TotalDPS"] > blend["metricsBefore"]["TotalDPS"]
    assert blend["metricsAfter"]["TotalEHP"] > blend["metricsBefore"]["TotalEHP"]
    # ...and carries a real defensive affix (life/resistance), which a pure-DPS craft would not
    assert any(("life" in a.lower() or "resist" in a.lower()) for a in blend["affixes"])
    # invalid goals are rejected, not silently treated as single-metric
    bad = itemopt.optimize_item(engine, "Amulet", base="Absent Amulet", goals={"TotalDPS": 0})
    assert bad["ok"] is False


def test_optimize_item_reports_attainability_and_craft(engine):
    # Attainability: each chosen affix carries its required ilvl + tier depth (top tier of N); craft:
    # a coarse effort rating. Tier-depth derived (the data has no usable spawn-weights).
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_item(
        "Rarity: Rare\nX\nGrand Spear\n--------\nAdds 40 to 80 Lightning Damage", slot="Weapon 1"
    )
    r = itemopt.optimize_item(engine, "Weapon 1", metric="TotalDPS")
    assert r["ok"] and r["attainability"]
    assert r["acquisitionProfile"] == "realistic_trade"
    assert len(r["affixes"]) <= 5
    assert sum(entry["tier"] == 1 and entry["totalTiers"] >= 4 for entry in r["attainability"]) <= 2
    for a in r["attainability"]:
        assert a["affix"] and a["ilvl"] >= 0 and a["tiers"] >= 1
    craft = r["craft"]
    assert craft["effort"] in {"trivial", "low", "moderate", "high", "very high"}
    assert craft["minItemLevel"] >= 1 and craft["prefixPool"] >= 1
    theoretical = itemopt.optimize_item(
        engine,
        "Weapon 1",
        metric="TotalDPS",
        acquisition_profile="theoretical",
    )
    assert theoretical["ok"] is True
    assert theoretical["acquisitionProfile"] == "theoretical"
    assert theoretical["attainabilityPolicy"]["maxExplicitAffixes"] == 6


def test_rank_upgrades_orders_slots_by_gain(engine):
    # The "what to upgrade next" tool: recrafts each slot and ranks by gain, high -> low, read-only.
    from server import scaffold
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_item(
        "Rarity: Rare\nX\nGrand Spear\n--------\nAdds 40 to 80 Lightning Damage", slot="Weapon 1"
    )
    scaffold.scaffold_gear(engine, pool="life", target_resist=75)  # give slots bases to rank
    r = itemopt.rank_upgrades(engine, metric="TotalDPS", top=5)
    assert r["ok"] and len(r["ranked"]) >= 3
    deltas = [e["delta"] for e in r["ranked"]]
    assert deltas == sorted(deltas, reverse=True)  # ranked high -> low
    assert all({"slot", "item", "delta"} <= set(e) for e in r["ranked"])
    assert engine.get_build()["mainSkill"] == "Lightning Spear"  # read-only: build unchanged
    g = itemopt.rank_upgrades(engine, goals={"TotalDPS": 0.6, "TotalEHP": 0.4}, top=3)
    assert g["ok"] and all("score" in e and "deltas" in e for e in g["ranked"])


def test_optimize_supports_picks_improving_set(engine):
    # Engine-measured greedy support selection (no magnitude data needed); read-only.
    from server.compute import supportopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_item(
        "Rarity: Rare\nX\nGrand Spear\n--------\nAdds 200 to 400 Lightning Damage\n"
        "100% increased Elemental Damage with Attacks",
        slot="Weapon 1",
    )
    r = supportopt.optimize_supports(engine, metric="TotalDPS", max_supports=5, candidates=16)
    assert r["ok"] and r["supports"]
    assert r["finalValue"] > r["baseValue"]  # the chosen set raises DPS
    dps = [p["TotalDPS"] for p in r["progression"]]
    assert dps == sorted(dps)  # greedy only adds improving supports -> monotonic
    # Regression: Lightning Penetration shares only the element tag (1 match), so the old tag-capped
    # pool dropped it entirely; the measurement-based pool must surface it and the greedy pick it.
    assert "Lightning Penetration" in r["supports"]
    assert r["screened"] >= 30  # solo-screened a broad pool, not a tiny tag-ranked slice
    assert r["supportAudit"]["status"] == "inconclusive"
    assert r["supportAudit"]["measurement"]["checkpointEligible"] is False
    assert r["supportAudit"]["positiveGainSupportsMissing"]
    assert engine.get_build()["mainSkill"] == "Lightning Spear"  # read-only: build restored


def test_optimize_supports_can_target_secondary_group_and_restore(engine):
    from server.compute import skillgroups, supportopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_skill_group("Fireball 20/20  1")
    groups_before = skillgroups.list_skill_groups(engine)
    target = next(group for group in groups_before["groups"] if group["index"] == 2)

    result = supportopt.optimize_supports(
        engine,
        metric="TotalDPS",
        max_supports=3,
        group_index=2,
        expected_fingerprint=target["fingerprint"],
    )

    assert result["ok"] is True
    assert result["skill"] == "Fireball"
    assert result["groupIndex"] == 2
    assert engine.get_build()["mainSkill"] == "Lightning Spear"
    assert skillgroups.list_skill_groups(engine)["groups"] == groups_before["groups"]


def test_trigger_support_capability_short_circuits_rate_dependent_but_not_hit_metric(engine):
    from server.compute import supportopt

    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(95)
    engine.paste_skill("Cast on Critical 20/20 1\nComet 20/20 1")

    rate_dependent = supportopt.optimize_supports(engine, metric="FullDPS")
    assert rate_dependent["ok"] is False
    assert rate_dependent["reasonClass"] == "capability_gap"
    assert rate_dependent["measurement"]["screenedCandidates"] == 0
    assert rate_dependent["capability"]["applicationCheck"] == "verified"

    per_hit = engine.call(
        "inspect_support_evaluation_capability",
        index=1,
        activeIndex=1,
        objectiveKeys=["AverageDamage"],
    )
    assert per_hit["numericRanking"] == "supported"
    assert per_hit["triggerRate"] == "not_applicable"


def test_support_pool_surfaces_on_element_levers():
    # Root-cause guard (corpus only, no engine): on-element supports like penetration must be flagged
    # and survive into the optimizer's screening set despite sharing only the element tag.
    from server.compute import supportopt
    from server.knowledge import db

    info = db.find_supports_for("Lightning Spear", limit=9999)
    pen = next(c for c in info["compatible"] if c["name"] == "Lightning Penetration")
    assert pen["on_element"] is True and pen["matches"] == ["lightning"]
    screen = supportopt._screen_set("Lightning Spear", 48)
    assert "Lightning Penetration" in screen and "Overcharge" in screen


def test_optimize_jewel_crafts_damage_jewel(engine):
    # Jewel crafter: marginal-ranks jewel mods (measured as real modifiers); non-jewel base rejected.
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_item(
        "Rarity: Rare\nX\nGrand Spear\n--------\nAdds 200 to 400 Lightning Damage\n"
        "100% increased Elemental Damage with Attacks",
        slot="Weapon 1",
    )
    r = itemopt.optimize_jewel(engine, metric="TotalDPS", base="Emerald")
    assert r["ok"] and r["affixes"]
    assert r["metricAfter"] > r["metricBefore"]  # the jewel raises DPS
    assert r["item"].startswith("Rarity: Rare") and "Emerald" in r["item"]
    assert "Item Level: 95" in r["item"]
    assert r["selectionMode"] == "automatic_global_marginal"
    assert itemopt.optimize_jewel(engine, base="Grand Spear")["ok"] is False  # not a jewel base
    assert engine.get_build()["mainSkill"] == "Lightning Spear"  # read-only


def test_optimize_radius_jewel_requires_and_validates_agent_selected_mods(engine):
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Witch", "Blood Mage")
    engine.set_level(90)
    engine.paste_skill("Spark 20/0 1")

    rejected = itemopt.optimize_jewel(engine, base="Time-Lost Sapphire")
    selected = itemopt.optimize_jewel(
        engine,
        base="Time-Lost Sapphire",
        selected_mod_ids=[
            "JewelRadiusLargeSize",
            "JewelRadiusColdDamage",
            "JewelRadiusCastSpeed",
        ],
        item_level=90,
    )
    unavailable = itemopt.optimize_jewel(
        engine,
        base="Time-Lost Sapphire",
        selected_mod_ids=["JewelRadiusAttackSpeed"],
        item_level=90,
    )

    assert rejected["errorCode"] == "radius_jewel_requires_agent_selection"
    assert unavailable["errorCode"] == "jewel_mod_not_available_for_base"
    assert selected["ok"] is True
    assert selected["selectionMode"] == "agent_selected_positional"
    assert selected["requiresPositionalEvaluation"] is True
    assert selected["modIds"] == [
        "JewelRadiusLargeSize",
        "JewelRadiusColdDamage",
        "JewelRadiusCastSpeed",
    ]
    assert "Item Level: 90" in selected["item"]
    assert "Radius: Small" in selected["item"]
    assert "Small Passive Skills in Radius also grant" in selected["item"]
    assert "Notable Passive Skills in Radius also grant" in selected["item"]

    engine.alloc_passive(2491)
    engine.alloc_passive(18157)
    before = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    measured = engine.eval_items("Jewel 2491", [selected["item"]], keys=["TotalDPS"])["results"][0]
    assert measured["TotalDPS"] > before


def test_plan_gear_meets_stage_resists_while_keeping_damage(engine):
    # Cross-slot budget allocation: offense slots damage-leaning, defense slots EHP-leaning (which
    # pulls resists onto the cheapest-DPS pieces). The default endgame target is 60/30, not a hidden
    # universal 75% requirement. Read-only; returns a coherent whole-set plan.
    from server import scaffold
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_item(
        "Rarity: Rare\nX\nGrand Spear\n--------\nAdds 100 to 200 Lightning Damage", slot="Weapon 1"
    )
    scaffold.scaffold_gear(engine, pool="life", target_resist=75)  # bases to plan over
    r = itemopt.plan_gear(
        engine,
        dps_weight=0.7,
        slots=["Amulet", "Body Armour", "Helmet", "Boots", "Belt", "Ring 2"],
    )
    assert r["ok"] and r["plan"]
    assert not r["rejectedIllegalCandidates"]
    assert all(item["legalityCheck"]["ok"] for item in r["plan"])
    pj = r["projected"]
    assert pj["resistanceTargetMet"] is True
    assert isinstance(pj["TotalDPS"], (int, float))
    assert engine.get_build()["mainSkill"] == "Lightning Spear"  # read-only: build restored


def test_new_build_resets(engine):
    # new_build clears gear/skills so a from-scratch build doesn't inherit a prior one's state.
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.paste_skill("Spark 20/20  1")
    engine.add_item("Rarity: Rare\nW\nDueling Wand\n100% increased Spell Damage", slot="Weapon 1")
    engine.new_build()
    b = engine.get_build()
    assert not b.get("gear") and not b.get("mainSkill")


def test_boss_tier_sets_enemy_resistance(engine):
    # Setting the boss tier applies that tier's enemy elemental resistance (PoB only sets it as a
    # GUI placeholder otherwise); harder tiers => lower computed DPS for an elemental skill.
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.add_item(
        "Rarity: Rare\nW\nDueling Wand\n+5 to Level of all Lightning Spell Skills\n"
        "Adds 1 to 85 Lightning Damage to Spells\n100% increased Spell Damage"
    )
    engine.paste_skill("Spark 20/20  1")
    r = engine.set_config(options={"enemyIsBoss": "Boss"})
    assert r.get("enemyResist", {}).get("lightning") == 30
    boss = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    engine.set_config(options={"enemyIsBoss": "Pinnacle"})  # 50% res
    pinn = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    assert pinn < boss  # a tankier tier computes lower DPS


def test_alloc_passive_warns_over_budget(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    engine.optimize_passives(metric="balanced", points=0)
    engine.set_level(40)  # filled tree now exceeds the smaller budget
    cand = [
        n
        for n in engine.search_passives(query="", node_type="Notable", limit=300)["results"]
        if not n.get("alloc") and (n.get("pathDist") or 99) <= 2
    ]
    a = engine.alloc_passive(cand[0]["id"])
    assert a.get("warning") and "over budget" in a["warning"]


def test_real_engine_lists_bounded_reallocation_leaf_candidates(engine):
    engine.new_build()
    engine.set_class("Mercenary", "Tactician")
    engine.set_level(95)
    candidates = [
        node
        for node in engine.search_passives(query="", node_type="Notable", limit=200)["results"]
        if not node.get("ascendancy")
        and isinstance(node.get("pathDist"), (int, float))
        and node["pathDist"] > 0
    ]
    assert candidates
    allocated = engine.alloc_passive(candidates[0]["id"])
    assert allocated["ok"] is True

    result = engine.list_reallocation_candidates(limit=12)

    assert result["boundedLimit"] == 12
    assert result["candidates"]
    assert all(entry["type"] in {"Normal", "Notable"} for entry in result["candidates"])
    assert all(entry["pointsFreed"] == 1 for entry in result["candidates"])


def test_unmodeled_skill_surfaced(engine):
    # Mana Tempest's empower isn't modeled by PoB; the engine must say so (DPS understated).
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    engine.add_skill_group("Mana Tempest 20/20  1")
    r = engine.get_stats(["TotalDPS"])
    assert r.get("engineNote") and "Mana Tempest" in r["engineNote"]


def test_equip_bad_base_returns_error_not_crash(engine):
    # An unrecognized base must not surface a raw Lua traceback (#7).
    engine.new_build()
    engine.set_class("Ranger", "Deadeye")
    r = engine.add_item(
        "Rarity: Rare\nPhantom String\nNot A Real Bow Base\nAdds 50 to 90 Physical Damage"
    )
    assert r.get("ok") is False and "base" in (r.get("error") or "").lower()


def test_attack_rate_binds_to_weapon(engine):
    # Regression for the friend's frozen-Speed report: a bow attack's Speed responds to +attack
    # speed (the weapon's rate binds to the skill). #1-3 were a broken-weapon downstream effect.
    engine.new_build()
    engine.set_class("Ranger", "Deadeye")
    engine.set_level(90)
    engine.add_item(
        "Rarity: Rare\nB\nFanatic Bow\nAdds 40 to 75 Physical Damage\n38% increased Attack Speed",
        slot="Weapon 1",
    )
    engine.paste_skill("Ice Shot 20/20  1")
    base = engine.get_stats(["Speed"])["stats"]["Speed"]
    fast = engine.set_config(custom_mods="100% increased Attack Speed")["stats"]["Speed"]
    assert base > 0 and fast == pytest.approx(base * 2, rel=0.05)


def test_multiprojectile_note_frames_shotgun_as_per_skill(engine):
    # The dpsNote must NOT claim PoE2 "has no shotgunning" (false —overlap is per-skill) and must
    # NOT tell users to multiply TotalDPS by projectile count. It should frame overlap as per-skill
    # and tell the reader to verify. (#4-5 wrong-advice regression guard.)
    _spark_caster(engine)
    r = engine.paste_skill("Spark 20/20  1")
    note = (r.get("dpsNote") or "").lower()
    assert note  # Spark fires many projectiles -> note present
    assert "multiple of this" not in note  # not the old "effective DPS is a multiple" advice
    assert "no shotgun" not in note  # must NOT claim PoE2 has no shotgunning
    assert "per-skill" in note  # frames overlap/shotgun as per-skill
    assert "verify" in note  # tells the reader to verify, not assume


def test_solver_levers(engine):
    from server.compute import solver

    # #6: no "increased increased" double-prefix; named levers expand correctly
    assert solver._template_for("increased projectile damage") == "{}% increased Projectile Damage"
    assert "{0}" in solver._template_for("added cold damage")
    assert "Critical Damage Bonus" in solver._template_for("critical strike multiplier")
    # PoE2 renamed crit chance -> "Critical Hit Chance"; the engine silently ignores the PoE1
    # "Critical Strike Chance" wording, so both the alias and the default scan must emit the PoE2
    # stat (otherwise rank_levers/solve_for report crit chance as a dead 0-gain lever).
    assert solver._template_for("critical strike chance") == "{}% increased Critical Hit Chance"
    assert solver._template_for("critical hit chance") == "{}% increased Critical Hit Chance"
    assert "{}% increased Critical Hit Chance" in solver._DEFAULT_LEVERS
    assert "{}% increased Critical Strike Chance" not in solver._DEFAULT_LEVERS
    names = solver.list_levers()["levers"]
    assert "increased projectile damage" in names and len(names) > 20


def test_crit_chance_lever_registers_on_engine(engine):
    # Regression: "increased Critical Hit Chance" (PoE2) must raise crit chance; the PoE1 wording
    # "Critical Strike Chance" is silently ignored by the engine —which had made the crit lever
    # invisible to rank_levers/solve_for and steered builds away from the crit (pinnacle) archetype.
    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_item(
        "Rarity: Rare\nX\nGrand Spear\n--------\nAdds 200 to 400 Lightning Damage", slot="Weapon 1"
    )
    base = engine.get_stats(["CritChance"])["stats"]["CritChance"]
    engine.set_config(custom_mods="100% increased Critical Hit Chance")
    raised = engine.get_stats(["CritChance"])["stats"]["CritChance"]
    engine.set_config(custom_mods="100% increased Critical Strike Chance")
    ignored = engine.get_stats(["CritChance"])["stats"]["CritChance"]
    engine.set_config(custom_mods="")
    assert raised > base  # PoE2 wording registers
    assert ignored == base  # PoE1 wording does nothing —documents the rename


def test_default_damage_levers_register_on_engine(engine):
    # Standing guard against PoE1->PoE2 terminology rot: every DAMAGE/crit lever in rank_levers'
    # default scan must actually move the engine. A renamed/ignored stat reads a silent 0 (which is
    # exactly how "Critical Strike Chance" hid the crit lever). Uses a crit-capable SPELL build so
    # damage/cast-speed/crit all apply, with a boss enemy so penetration has resistance to bite.
    from server.compute import solver

    engine.new_build()
    engine.set_class("Witch", "Infernalist")
    engine.set_level(90)
    engine.paste_skill("Fireball 20/20  1")
    engine.set_config(options={"enemyIsBoss": "Boss"})
    base = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    assert isinstance(base, (int, float)) and base > 0
    damage_levers = [
        t for t in solver._DEFAULT_LEVERS if "maximum Life" not in t and "Energy Shield" not in t
    ]
    assert (
        "{}% increased Attack Speed" in solver._DEFAULT_LEVERS
    )  # an attack-only lever; skip below
    for tmpl in damage_levers:
        if "Attack Speed" in tmpl:
            continue  # irrelevant to a spell; covered by the attack-build crit test above
        engine.set_config(custom_mods=tmpl.replace("{}", "200"))
        after = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
        engine.set_config(custom_mods="")
        assert after > base, (
            f"default lever does not register on the engine (terminology rot?): {tmpl}"
        )


def test_meta_trigger_guardrail_flags_unmodellable_triggers():
    # Gap C guardrail: the engine does NOT model energy-based meta triggers (Cast on Critical →a
    # socketed spell computes as a weak self-cast), so the tools must surface `engineLimitation` when
    # such a gem is present —and must NOT false-flag ordinary skills/supports.
    from server import main
    from server.knowledge import db

    assert db.meta_trigger_gems(["Cast on Critical", "Lightning Spear", "Comet"]) == [
        "Cast on Critical"
    ]
    assert db.meta_trigger_gems(["Lightning Spear", "Lightning Penetration"]) == []
    names = main._gem_names_in("Lightning Spear 20/20 1 / Cast on Critical / Comet 20/20 1")
    assert {"Lightning Spear", "Cast on Critical", "Comet"} <= set(names)  # level slash not split
    flagged = main._flag_meta_trigger({"ok": True}, names)
    assert "engineLimitation" in flagged and "Cast on Critical" in flagged["engineLimitation"]
    assert "engineLimitation" not in main._flag_meta_trigger({"ok": True}, ["Lightning Spear"])


def test_pick_base_prefers_attribute():
    # Auto-base picks attribute-appropriate gear: an int vs str body must differ (wearable + the right
    # defence layer); jewellery is attribute-agnostic but still returns a base.
    from server.knowledge import db

    int_body = db.pick_base("Body Armour", "int")
    str_body = db.pick_base("Body Armour", "str")
    assert int_body and str_body and int_body != str_body
    assert db.pick_base("Ring", "int") is not None


def test_relevant_uniques_ranks_by_keyword_match():
    # (b) build-aware unique discovery: ranks uniques by how many of the build's scaling keywords
    # their mods/name match (corpus relevance —the engine still verifies actual value).
    from server.knowledge import db

    rel = db.relevant_uniques(["lightning", "spell", "projectile"], limit=12)
    assert rel  # finds candidates
    assert all(u.get("matched") for u in rel)  # each records which keywords it matched
    counts = [len(u["matched"]) for u in rel]
    assert counts == sorted(counts, reverse=True)  # ranked most-relevant first
    assert any(len(u["matched"]) >= 2 for u in rel)  # at least one multi-keyword (synergistic) hit


def test_plan_gear_auto_bases_a_full_set_from_scratch(engine):
    # #1: plan_gear fills EMPTY armour/jewellery slots with attribute-appropriate bases so a
    # weapon-only from-scratch build gets a whole, resist-capped set; weapons stay caller-supplied.
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(95)
    engine.paste_skill("Spark 20/20  1")
    engine.add_item(
        "Rarity: Rare\nW\nDueling Wand\n+5 to Level of all Lightning Spell Skills\n"
        "Adds 40 to 600 Lightning Damage to Spells\n117% increased Spell Damage",
        slot="Weapon 1",
    )
    r = itemopt.plan_gear(engine, dps_weight=0.6, min_ehp=12000)
    planned = {p["slot"] for p in r["plan"]}
    for slot in ("Amulet", "Gloves", "Ring 1", "Ring 2", "Body Armour", "Helmet", "Boots", "Belt"):
        assert slot in planned, f"auto-base missed {slot}"
    assert r["projected"]["resistanceTargetMet"]
    assert "ehpFloorMet" in r["projected"]  # the min_ehp floor is evaluated + reported
    assert engine.get_build()["mainSkill"] == "Spark"  # read-only: build restored


def test_realistic_plan_replaces_normal_bootstrap_weapon(engine):
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Mercenary", "Tactician")
    engine.set_level(95)
    engine.paste_skill("Galvanic Shards 20/20  1")
    engine.add_item("Rarity: Normal\nMakeshift Crossbow\nItem Level: 1", slot="Weapon 1")

    result = itemopt.plan_gear(
        engine,
        slots=["Weapon 1"],
        acquisition_profile="realistic_trade",
    )

    assert result["replacedBootstrapSlots"] == ["Weapon 1"]
    assert result["plan"][0]["item"].splitlines()[2] != "Makeshift Crossbow"
    assert len(result["plan"][0]["affixes"]) <= 5
    assert all(entry["topTierAffixCount"] <= 2 for entry in result["plan"])


def test_campaign_plan_gear_does_not_keep_chasing_capped_chaos_resistance(engine):
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(58)
    engine.paste_skill("Spark")
    engine.add_item(
        "Rarity: Rare\nW\nDueling Wand\n+3 to Level of all Lightning Spell Skills\n"
        "Adds 20 to 250 Lightning Damage to Spells\n80% increased Spell Damage",
        slot="Weapon 1",
    )

    result = itemopt.plan_gear(engine, dps_weight=0.7, stage="campaign")
    chaos_affixes = [
        affix for item in result["plan"] for affix in item["affixes"] if "Chaos Resistance" in affix
    ]

    assert result["stageProfile"]["chaosResistTarget"] == 0
    assert result["projected"]["chaosTarget"] == 0
    assert result["projected"]["chaosTargetMet"] is True
    assert 0 <= result["projected"]["resistances"]["chaos"] < 75
    assert len(chaos_affixes) <= 3


def test_optimize_charm_returns_magic_one_prefix_one_suffix(engine):
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Mercenary", "Tactician")
    engine.set_level(95)
    engine.add_item(
        "Rarity: Rare\nTest Belt\nFine Belt\nItem Level: 82\nCharm Slots: 3\n"
        "Implicits: 1\nHas 3 Charm Slots",
        slot="Belt",
    )

    result = itemopt.optimize_charm(
        engine,
        "Charm 1",
        base="Amethyst Charm",
        prefix_strategy="guard",
        suffix_strategy="charges",
    )

    assert result["ok"] is True
    assert result["item"].startswith("Rarity: Magic")
    assert len(result["affixes"]) == 2
    assert result["legalityCheck"]["prefixes"] == 1
    assert result["legalityCheck"]["suffixes"] == 1


class _JewelMarginalEngine:
    def __init__(self) -> None:
        self.allocated = False
        self.equipped = False
        self.xml = (
            '<PathOfBuilding><Build className="Mercenary" level="95"/>'
            '<Tree activeSpec="1"><Spec><Sockets /></Spec></Tree>'
            '<Items activeItemSet="1"><ItemSet id="1" /></Items></PathOfBuilding>'
        )
        self.unspent_points = 5
        self.removed: set[int] = set()
        self.mutation_count = 0

    def get_xml(self):
        return self.xml

    def transaction_lock(self):
        return nullcontext()

    def _touch(self):
        self.mutation_count += 1
        while f"mutation{self.mutation_count}=" in self.xml:
            self.mutation_count += 1
        self.xml = self.xml.replace("/>", f' mutation{self.mutation_count}="true"/>', 1)

    def list_jewel_sockets(self):
        root = ET.fromstring(self.xml)
        filled = {int(value.get("nodeId")) for value in root.findall("./Tree/Spec/Sockets/Socket")}
        return {
            "sockets": [
                {
                    "socket": socket,
                    "allocated": socket in filled,
                    "filled": socket in filled,
                }
                for socket in (101, 102, 103)
            ]
        }

    def get_passive(self, node):
        node = int(node)
        filled = {
            int(value.get("nodeId"))
            for value in ET.fromstring(self.xml).findall("./Tree/Spec/Sockets/Socket")
        }
        return {
            "found": True,
            "alloc": node in filled or (node in {201, 202} and node not in self.removed),
            "pathDist": 2,
            "pathNodeIds": [301],
        }

    def get_build(self):
        return {"unspentPoints": self.unspent_points}

    def get_stats(self, _keys):
        value = 100 - 5 * len(self.removed)
        value += 20 * len(ET.fromstring(self.xml).findall("./Tree/Spec/Sockets/Socket"))
        return {"stats": {"Life": value}}

    def list_reallocation_candidates(self, limit=12):
        assert limit is None
        return {
            "candidates": [
                {"id": 201, "name": "Small Life", "type": "Normal", "pointsFreed": 1},
                {"id": 202, "name": "Small Armour", "type": "Normal", "pointsFreed": 1},
            ]
        }

    def dealloc_passive(self, node):
        self.removed.add(int(node))
        self._touch()
        return {"ok": True, "pointsFreed": 1}

    def alloc_passive(self, _node):
        self.allocated = True
        self._touch()
        return {"ok": True, "pointsSpent": 2}

    def equip_jewel(self, _raw, socket=None):
        assert socket in {101, 102, 103}
        self.equipped = True
        root = ET.fromstring(self.xml)
        items = root.find("Items")
        item_id = str(len(items.findall("Item")) + 1)
        item = ET.SubElement(items, "Item", {"id": item_id})
        item.text = _raw
        sockets = root.find("./Tree/Spec/Sockets")
        ET.SubElement(sockets, "Socket", {"nodeId": str(socket), "itemId": item_id})
        self.xml = ET.tostring(root, encoding="unicode")
        return {"ok": True}

    def load_build_xml(self, xml, name=""):
        del name
        self.xml = xml
        socket_count = len(ET.fromstring(xml).findall("./Tree/Spec/Sockets/Socket"))
        self.allocated = socket_count > 0
        self.equipped = socket_count > 0
        self.removed.clear()
        self.mutation_count = 0
        return {"ok": True}


def test_evaluate_next_jewel_socket_is_marginal_bounded_and_read_only():
    engine = _JewelMarginalEngine()
    before = engine.get_xml()

    result = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=1,
    )

    assert result["ok"] is True
    assert result["socket"] == 101
    assert result["pathPointCost"] == 2
    assert result["positiveNetBenefit"] is True
    assert result["decisionRef"].startswith("jewel-decision:")
    assert result["decision"] == "apply_best_socket"
    assert result["maxRounds"] is None
    assert result["socketFrontierComplete"] is True
    assert result["evaluatedSocketCount"] == 3
    assert engine.get_xml() == before
    assert engine.allocated is False and engine.equipped is False


def test_evaluate_next_jewel_socket_checks_all_sockets_and_selects_best():
    class PositionAwareEngine(_JewelMarginalEngine):
        def get_stats(self, _keys):
            root = ET.fromstring(self.xml)
            filled = {
                int(value.get("nodeId")) for value in root.findall("./Tree/Spec/Sockets/Socket")
            }
            gains = {101: 5, 102: 35, 103: 15}
            value = 100 - 5 * len(self.removed) + sum(gains.get(node, 0) for node in filled)
            return {"stats": {"Life": value}}

    engine = PositionAwareEngine()
    result = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[],
    )

    assert result["socket"] == 102
    assert [entry["socket"] for entry in result["socketEvaluations"]] == [101, 102, 103]
    assert result["evaluatedSocketCount"] == 3


def test_evaluate_next_jewel_socket_protects_agent_selected_nodes():
    engine = _JewelMarginalEngine()
    engine.unspent_points = 0

    result = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[201],
    )

    assert result["status"] == "inconclusive"
    assert result["positiveNetBenefit"] is None
    assert result["limitedSocketCount"] == 3
    assert all(entry["status"] == "policy_limited" for entry in result["socketEvaluations"])


def test_positive_jewel_decision_cannot_be_overwritten_by_another_candidate():
    engine = _JewelMarginalEngine()
    first = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nFirst Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[],
    )
    second = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nSecond Jewel\nRuby\nItem Level: 95\n+10 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[],
    )

    assert first["positiveNetBenefit"] is True
    assert second["errorCode"] == "jewel_socket_positive_decision_pending"
    current = itemopt.next_jewel_decision_for_state(engine, first["stateHash"])
    assert current is not None and current["decisionRef"] == first["decisionRef"]


def test_undeclared_jewel_protection_is_diagnostic_only():
    engine = _JewelMarginalEngine()
    diagnostic = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
    )

    assert diagnostic["positiveNetBenefit"] is True
    assert diagnostic["protectionDeclared"] is False
    assert diagnostic["decision"] == "declare_protection_before_apply"
    assert "decisionRef" not in diagnostic

    actionable = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[],
    )
    assert actionable["protectionDeclared"] is True
    assert actionable["decisionRef"].startswith("jewel-decision:")


def test_apply_rejects_a_decision_without_declared_protection():
    engine = _JewelMarginalEngine()
    evaluated = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[],
    )
    with itemopt._JEWEL_DECISION_LOCK:
        itemopt._JEWEL_APPLY_DECISIONS[engine][evaluated["decisionRef"]]["protectionDeclared"] = (
            False
        )

    rejected = itemopt.apply_next_jewel_socket_decision(
        engine,
        decision_ref=evaluated["decisionRef"],
        expected_state_hash=evaluated["stateHash"],
    )

    assert rejected["errorCode"] == "jewel_protection_not_declared"


def test_evaluate_next_jewel_socket_reports_restore_failure():
    class RestoreFailureEngine(_JewelMarginalEngine):
        def load_build_xml(self, xml, name=""):
            del xml, name
            raise RuntimeError("restore failed")

    engine = RestoreFailureEngine()
    result = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=1,
    )

    assert result["ok"] is False
    assert result["errorCode"] == "jewel_socket_probe_restore_failed"
    assert result["rolledBack"] is False
    assert result["recoveryRequired"] is True
    assert itemopt.next_jewel_decision_for_state(engine, build_state_hash(engine.get_xml())) is None


def test_evaluate_next_jewel_socket_full_tree_measures_equal_point_reallocation():
    engine = _JewelMarginalEngine()
    engine.unspent_points = 0

    result = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=1,
    )

    assert result["ok"] is True
    assert result["status"] == "evaluated"
    assert result["pointsReallocated"] == 2
    assert result["nodesToRemove"] == [201, 202]
    assert result["positiveNetBenefit"] is True
    assert result["metricsBefore"]["Life"] == 100
    assert result["metricsAfter"]["Life"] == 110
    assert engine.removed == set()


def test_apply_next_jewel_socket_decision_is_atomic_and_marks_round_progress():
    engine = _JewelMarginalEngine()
    evaluated = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=1,
    )

    applied = itemopt.apply_next_jewel_socket_decision(
        engine,
        decision_ref=evaluated["decisionRef"],
        expected_state_hash=evaluated["stateHash"],
    )

    assert applied["ok"] is True
    assert applied["reviewRequired"] is True
    assert applied["outputStateHash"] != evaluated["stateHash"]
    current = itemopt.next_jewel_decision_for_state(engine, applied["outputStateHash"])
    assert current is not None and current["status"] == "applied"


def test_apply_next_jewel_socket_decision_preserves_protected_nodes():
    engine = _JewelMarginalEngine()
    engine.unspent_points = 1
    evaluated = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[201],
    )

    applied = itemopt.apply_next_jewel_socket_decision(
        engine,
        decision_ref=evaluated["decisionRef"],
        expected_state_hash=evaluated["stateHash"],
    )

    assert applied["ok"] is True
    assert applied["protectedNodeIds"] == [201]
    assert engine.get_passive(201)["alloc"] is True


def test_apply_next_jewel_socket_decision_rejects_stale_state_without_mutation():
    engine = _JewelMarginalEngine()
    evaluated = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=1,
    )
    before = engine.get_xml()

    rejected = itemopt.apply_next_jewel_socket_decision(
        engine,
        decision_ref=evaluated["decisionRef"],
        expected_state_hash="sha256:stale",
    )

    assert rejected["errorCode"] == "build_state_conflict"
    assert engine.get_xml() == before


def test_round_index_is_compatibility_only():
    engine = _JewelMarginalEngine()

    evaluated = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=7,
    )

    assert evaluated["ok"] is True
    assert evaluated["roundIndex"] == 7


def test_jewel_review_can_apply_more_than_two_positive_sockets():
    engine = _JewelMarginalEngine()
    raw = "Rarity: Rare\nTest Jewel\nRuby\nItem Level: 95\n+20 to maximum Life"
    applied = None
    for index in range(1, 4):
        evaluated = itemopt.evaluate_next_jewel_socket(
            engine,
            raw=raw,
            goals={"Life": 1.0},
            protected_node_ids=[],
            round_index=index,
        )
        applied = itemopt.apply_next_jewel_socket_decision(
            engine,
            decision_ref=evaluated["decisionRef"],
            expected_state_hash=evaluated["stateHash"],
        )
        assert applied["ok"] is True

    assert applied is not None and applied["reviewRequired"] is True
    terminal = itemopt.evaluate_next_jewel_socket(
        engine,
        raw=raw,
        goals={"Life": 1.0},
        protected_node_ids=[],
    )
    assert terminal["status"] == "not_applicable"


def test_tactician_95_real_engine_selects_declared_boss_group(engine):
    engine.new_build()
    engine.set_class("Mercenary", "Tactician")
    engine.set_level(95)
    engine.add_item("Rarity: Normal\nMakeshift Crossbow\nItem Level: 1", slot="Weapon 1")
    engine.paste_skill("Galvanic Shards 20/20 1")
    engine.add_skill_group("Stormblast Bolts 20/20 1")

    selection = engine.select_judge_skill(
        offense_skill_group_index=2,
        expected_skill_name="Stormblast Bolts",
    )

    assert selection["status"] == "selected"
    assert selection["calculationContext"]["groupIndex"] == 2
    assert selection["calculationContext"]["skillName"] == "Stormblast Bolts"


class _SocketBatchEngine:
    def get_xml(self):
        return '<PathOfBuilding><Build className="Mercenary" level="95"/></PathOfBuilding>'


def test_plan_item_sockets_batch_returns_explicit_slot_decisions(monkeypatch):
    def fake_optimize(_engine, *, slot, **_kwargs):
        if slot == "Helmet":
            return {"ok": True, "changed": True, "item": "planned", "craftReceiptRef": "r"}
        return {"ok": True, "changed": False, "reason": "no_beneficial_socket_option"}

    monkeypatch.setattr(craftopt, "optimize_item_sockets", fake_optimize)
    result = craftopt.plan_item_sockets_batch(
        _SocketBatchEngine(),
        slot_socket_counts={"Helmet": 1, "Boots": 1},
        goals={"TotalEHP": 1.0},
    )

    assert result["ok"] is True
    assert result["decisions"] == {"Helmet": "socketed", "Boots": "no_positive"}
    assert result["readOnly"] is True


def test_partial_socket_plan_only_carries_to_immediate_equip_output_state(monkeypatch):
    engine = _SocketBatchEngine()
    fingerprint = "sha256:" + ("a" * 64)
    monkeypatch.setattr(
        craftopt,
        "optimize_item_sockets",
        lambda _engine, *, slot, **_kwargs: {
            "ok": True,
            "changed": True,
            "slot": slot,
            "item": "planned",
            "itemFingerprint": fingerprint,
            "acceptedItemFingerprints": [fingerprint],
            "remainingSocketCount": 1,
        },
    )

    result = craftopt.plan_item_sockets_batch(
        engine,
        slot_socket_counts={"Helmet": 2},
        goals={"TotalEHP": 1.0},
    )
    monkeypatch.setattr(
        craftopt.completeness,
        "equipped_item_metadata",
        lambda _xml: {"Helmet": {"itemFingerprint": fingerprint}},
    )

    assert result["decisions"] == {"Helmet": "partial_no_positive"}
    assert craftopt.socket_batch_decisions_for_state(engine, "post-equip-state") == {}
    carried = craftopt.carry_socket_decision_to_equipped_state(
        engine,
        input_state_hash=result["stateHash"],
        output_state_hash="post-equip-state",
        slot="Helmet",
        item_fingerprint=fingerprint,
    )
    assert carried == "partial_no_positive"
    assert craftopt.socket_batch_decisions_for_state(engine, "post-equip-state") == {
        "Helmet": "partial_no_positive"
    }
    assert craftopt.socket_batch_decisions_for_state(engine, "later-state") == {}


def test_multi_slot_socket_plan_carries_across_consecutive_equip_outputs(monkeypatch):
    engine = _SocketBatchEngine()
    fingerprints = {
        "Helmet": "sha256:" + ("a" * 64),
        "Boots": "sha256:" + ("b" * 64),
    }

    def fake_optimize(_engine, *, slot, **_kwargs):
        fingerprint = fingerprints[slot]
        return {
            "ok": True,
            "changed": True,
            "slot": slot,
            "item": "planned",
            "itemFingerprint": fingerprint,
            "acceptedItemFingerprints": [fingerprint],
            "remainingSocketCount": 1,
        }

    monkeypatch.setattr(craftopt, "optimize_item_sockets", fake_optimize)
    planned = craftopt.plan_item_sockets_batch(
        engine,
        slot_socket_counts={"Helmet": 2, "Boots": 2},
        goals={"TotalEHP": 1.0},
    )
    first = craftopt.carry_socket_decision_to_equipped_state(
        engine,
        input_state_hash=planned["stateHash"],
        output_state_hash="after-helmet",
        slot="Helmet",
        item_fingerprint=fingerprints["Helmet"],
    )
    second = craftopt.carry_socket_decision_to_equipped_state(
        engine,
        input_state_hash="after-helmet",
        output_state_hash="after-boots",
        slot="Boots",
        item_fingerprint=fingerprints["Boots"],
    )

    assert first == "partial_no_positive"
    assert second == "partial_no_positive"
    assert craftopt.socket_batch_decisions_for_state(engine, "after-boots") == {
        "Helmet": "partial_no_positive",
        "Boots": "partial_no_positive",
    }
    assert (
        craftopt.carry_socket_decision_to_equipped_state(
            engine,
            input_state_hash="unrelated-state",
            output_state_hash="unrelated-output",
            slot="Boots",
            item_fingerprint=fingerprints["Boots"],
        )
        is None
    )


def test_optimize_passives_respects_separate_ascendancy_budget(engine):
    # Ascendancy is a SEPARATE 8-point pool: optimize_passives must auto-allocate ascendancy notables
    # WITHOUT charging them to the passive budget (which had stranded passive points) and never exceed
    # 8; get_build reports the pool so over-allocation is visible.
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(95)
    engine.paste_skill("Spark 20/20  1")
    engine.add_item(
        "Rarity: Rare\nW\nDueling Wand\n+5 to Level of all Lightning Spell Skills\n"
        "Adds 40 to 600 Lightning Damage to Spells\n117% increased Spell Damage",
        slot="Weapon 1",
    )
    engine.optimize_passives(metric="TotalDPS", points=0)  # use all available passive points
    b = engine.get_build()
    assert b["ascendancyPointsMax"] == 8
    assert 0 < b["ascendancyPointsUsed"] <= 8  # auto-allocated, within the separate cap
    assert b["ascendancyNotables"]  # ascendancy notables were actually allocated
    assert b["pointsUsed"] <= b["pointsAvailable"]  # passive count excludes ascendancy
    assert "ascendancyNote" not in b  # not over budget -> no warning


def test_optimize_passives_default_full_and_honest_remaining(engine):
    # Footgun fix: the MCP tool defaults points=0 (allocate the WHOLE tree, the usual intent), and a
    # CAPPED `points` call reports the build's TRUE unspent passive points —not a budget-relative 0
    # that misreads as "tree fully allocated" (which had a bare call ship a 3-point tree).
    import inspect

    from server import main

    fn = getattr(main.optimize_passives, "__wrapped__", main.optimize_passives)
    assert inspect.signature(fn).parameters["points"].default == 0

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20 1")
    engine.add_item(
        "Rarity: Rare\nW\nGrand Spear\nAdds 50 to 400 Lightning Damage\n"
        "+4 to Level of all Projectile Skills",
        slot="Weapon 1",
    )
    capped = engine.optimize_passives(metric="TotalDPS", points=5)
    assert capped["pointsUsed"] == 5
    assert capped["pointsRemaining"] > 50  # TRUE unspent (~113 free), not a misleading 0


def test_optimize_passives_require_respects_budget_and_reset(engine):
    # Footgun fix: requiring nodes on an already-full tree must NOT over-allocate into an illegal
    # (>budget) tree —it skips + reports them. reset=True re-plans from scratch so the required
    # nodes (e.g. jewel sockets) fit within budget —the clean way to add sockets to a full tree.
    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(100)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_item(
        "Rarity: Rare\nW\nGrand Spear\nAdds 50 to 400 Lightning Damage\n"
        "+4 to Level of all Projectile Skills\n90% increased Elemental Damage with Attacks",
        slot="Weapon 1",
    )
    engine.optimize_passives(metric="TotalDPS", points=0)  # full tree

    # require on a FULL tree must skip (not over-allocate) and report what it skipped
    r = engine.optimize_passives(metric="TotalDPS", points=0, require=[2491, 7960, 21984])
    over = engine.get_build()
    assert over["pointsUsed"] <= over["pointsAvailable"]  # NOT over-budget (the footgun)
    assert r.get("requireSkipped")  # unfittable required nodes are surfaced

    # reset=True re-plans the whole tree, fitting the required jewel sockets within budget
    engine.optimize_passives(metric="TotalDPS", points=0, reset=True, require=[21984, 32763])
    after = engine.get_build()
    assert after["pointsUsed"] <= after["pointsAvailable"]
    socks = [s["socket"] for s in engine.call("list_jewel_sockets")["sockets"] if s["allocated"]]
    assert 21984 in socks and 32763 in socks  # the required sockets got allocated


def test_damage_diagnostic_silent_when_computable(engine):
    engine.new_build()
    engine.set_class("Witch", "Infernalist")
    engine.set_level(90)
    engine.paste_skill("Fireball 20/20  1")
    r = engine.get_stats(["TotalDPS"])
    assert (r["stats"].get("TotalDPS") or 0) > 0
    assert not r.get("warning")  # a computable build gets no false positive


def test_get_build_surfaces_unspent_points(engine):
    engine.new_build()
    engine.set_class("Witch", "Infernalist")
    engine.set_level(90)
    b = engine.get_build()
    assert b["pointsAvailable"] == 113  # 89 (level-1) + 24 campaign quest points
    assert b["unspentPoints"] == b["pointsAvailable"] - b["pointsUsed"]
    assert "pointsNote" in b  # a fresh tree flags its many unspent points


def test_get_build_counts_extra_passive_and_weapon_set_points(engine):
    # PoB's own progress estimator includes granted passive points in the normal passive budget.
    # Weapon-set cap follows PoB's UI budget: PassivePointsToWeaponSetPoints extends the cap;
    # WeaponSetPassivePoints is exposed for diagnostics but must not be treated as cap by itself.
    engine.new_build()
    engine.set_class("Witch", "Infernalist")
    engine.set_level(90)
    base = engine.get_build()
    engine.set_config(
        custom_mods="Grants 2 Passive Skill Points\n+2 Weapon Set Passive Skill Points"
    )
    b = engine.get_build()
    assert b["pointsAvailable"] == base["pointsAvailable"] + 2
    assert b["weaponSetPointsAvailable"] == base["weaponSetPointsAvailable"]
    assert b["stats"]["ExtraPoints"] == 2
    assert b["stats"]["WeaponSetPassivePoints"] == 2

    engine.set_config(custom_mods="100 Passive Skill Points become Weapon Set Skill Points")
    converted = engine.get_build()
    assert converted["weaponSetPointsAvailable"] == base["weaponSetPointsAvailable"] + 100
    assert converted["stats"]["PassivePointsToWeaponSetPoints"] == 100


def test_get_build_is_read_only_and_judge_selection_is_explicit(engine):
    engine.new_build()
    engine.set_class("Witch", "Infernalist")
    engine.set_level(90)
    engine.paste_skill("Plague Bearer 20/20  1")
    engine.add_skill_group("Fireball 20/20  1")

    b = engine.get_build()

    assert b["mainSkill"] == "Plague Bearer"
    assert "judgeSelectedSkill" not in b
    selection = engine.select_judge_skill(
        offense_skill_group_index=2,
        expected_skill_name="Fireball",
    )
    selected = selection["selectedSkill"]
    assert selected["skillName"] == "Fireball"
    assert selected["dps"] > 0
    selected_group_names = [g["name"] for g in selection["selectedSkillGroup"]]
    assert selected_group_names == ["Fireball"]


def test_get_build_exposes_weapon_requirement_mismatch_for_selected_skill(engine):
    engine.new_build()
    engine.set_class("Mercenary", "Witchhunter")
    engine.set_level(90)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_item(
        "Rarity: Rare\nW\nDueling Wand\n--------\nAdds 1 to 85 Lightning Damage to Spells",
        slot="Weapon 1",
    )

    selected = engine.select_judge_skill(
        offense_skill_group_index=1,
        expected_skill_name="Lightning Spear",
    )["selectedSkill"]

    assert selected["skillName"] == "Lightning Spear"
    assert selected["weaponCheck"]["weaponTypes"] == ["Spear"]
    assert selected["weaponCheck"]["equippedWeaponTypes"] == ["Wand"]
    assert "not usable with this skill" in selected["weaponCheck"]["disableReason"]


def test_judge_selected_skill_uses_isolated_full_dps_per_group(engine):
    # FullDPS is a build-level aggregation over groups marked includeInFullDPS. Judge must isolate
    # each candidate group during selection, or it will bind the global aggregate to one skill.
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1")
    single_full = engine.get_stats(["FullDPS"])["stats"]["FullDPS"]
    engine.add_skill_group("Spark 20/20  1", include_in_full_dps=True)
    global_full = engine.get_stats(["FullDPS"])["stats"]["FullDPS"]

    selected = engine.select_judge_skill(
        offense_skill_group_index=1,
        expected_skill_name="Spark",
    )["selectedSkill"]

    assert global_full > single_full * 1.5
    assert selected["sourceMetric"] != "FullDPS"
    assert selected["dps"] == pytest.approx(single_full, rel=0.05)
    assert selected["directDps"] == pytest.approx(selected["dps"], rel=1e-6)
    assert selected["fullDps"] == pytest.approx(single_full, rel=0.05)
    assert selected["dps"] < global_full * 0.75


def test_judge_selected_skill_exposes_active_skill_count_for_minion_math(engine):
    engine.new_build()
    engine.set_class("Witch", "Infernalist")
    engine.set_level(90)
    engine.paste_skill("Fireball 20/20  3")

    selected = engine.select_judge_skill(
        offense_skill_group_index=1,
        expected_skill_name="Fireball",
    )["selectedSkill"]

    assert selected["skillName"] == "Fireball"
    assert selected["activeSkillCount"] == 3
    assert selected["rawDps"] == pytest.approx(selected["dps"], rel=1e-6)
    assert selected["effectiveDps"] == pytest.approx(selected["dps"], rel=1e-6)


def test_get_build_does_not_change_full_dps_or_skill_flags(engine):
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1")
    engine.add_skill_group("Spark 20/20  1", include_in_full_dps=True)
    engine.add_skill_group("Attrition 20/20  1", include_in_full_dps=False)
    before_stats = engine.get_stats(["TotalDPS", "FullDPS", "ManaCost", "Speed"])["stats"]
    before_groups = engine.call("list_skill_groups")

    engine.get_build()
    engine.get_build()

    after_stats = engine.get_stats(["TotalDPS", "FullDPS", "ManaCost", "Speed"])["stats"]
    after_groups = engine.call("list_skill_groups")
    assert after_stats == pytest.approx(before_stats, rel=1e-9)
    assert [group["includeInFullDPS"] for group in after_groups["groups"]] == [
        group["includeInFullDPS"] for group in before_groups["groups"]
    ]
    assert after_groups["mainGroupIndex"] == before_groups["mainGroupIndex"]


def test_rank_levers_marginal_gain(fireball):
    from server.compute import solver

    base = fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    r = solver.rank_levers(fireball, metric="TotalDPS", unit=10)
    assert r["ok"] and r["levers"]
    gains = [lv["gain"] for lv in r["levers"]]
    assert gains == sorted(gains, reverse=True)  # ranked high -> low
    by = {lv["lever"]: lv["gain"] for lv in r["levers"]}
    # a damage lever helps DPS more than a pure-life lever
    assert by["{}% increased Damage"] > by["+{} to maximum Life"]
    # probing is restored
    assert fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(base, rel=1e-6)


def test_solve_for_already_met(fireball):
    from server.compute import solver

    base = fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    r = solver.solve_for(fireball, "TotalDPS", base * 0.5, "increased fire damage")
    assert r["ok"] and r["alreadyMet"] and r["requiredMagnitude"] == 0.0


def test_solve_for_noop_lever_detected(fireball):
    from server.compute import solver

    base = fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    # cold damage does nothing for a pure-fire Fireball —must be flagged, not "unreachable"
    r = solver.solve_for(fireball, "TotalDPS", base * 2, "increased cold damage")
    assert r["ok"] is False and "does not move" in r["error"]


def test_set_skill_accepts_inline_separators(engine):
    # The natural " / " (and ",") form must apply EVERY support, not just the first gem (the silent
    # support-drop / "Elemental Storm" corruption bug). Bare support names are tolerated too.
    _spark_caster(engine)
    r = engine.paste_skill("Spark 20/20 1 / Controlled Destruction / Lightning Penetration")
    names = [g["name"] for g in engine.get_build()["mainSkillGroup"]]
    assert r["mainSkill"] == "Spark"
    assert "Controlled Destruction" in names and "Lightning Penetration" in names


def test_set_skill_uses_highest_character_legal_active_gem_level_and_rolls_back_invalid(engine):
    engine.new_build()
    engine.set_class("Monk")
    engine.set_level(75)

    result = engine.paste_skill("Storm Wave")
    group = engine.get_build()["mainSkillGroup"]

    assert result.get("ok") is not False
    assert group[0]["level"] == 17
    assert group[0]["requiredLevel"] == 72
    assert group[0]["maximumLegalLevel"] == 17

    rejected = engine.paste_skill("Storm Wave 20/20 1")

    assert rejected["ok"] is False
    assert rejected["errorCode"] == "active_skill_gem_level_requirement_unmet"
    assert rejected["violations"][0]["requiredLevel"] == 90
    assert engine.get_build()["mainSkillGroup"][0]["level"] == 17

    engine.add_item(
        "Rarity: Rare\nLegal +Levels Staff\nSteelpoint Quarterstaff\nItem Level: 75\n"
        "+3 to Level of all Melee Skills",
        slot="Weapon 1",
    )
    readback = engine.get_build()
    assert readback["mainSkillGroup"][0]["level"] == 17
    assert readback["activeSkillGemLevelViolations"] == []


def test_set_skill_replaces_main_group(engine):
    # set_skill REPLACES the main group (no pile-up) yet preserves aura groups from add_skill_group.
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20 1")
    engine.add_skill_group("Archmage 20/20 1")
    n_after_aura = engine.get_build()["skillGroupCount"]
    for _ in range(3):
        engine.paste_skill("Spark 20/20 1 / Controlled Destruction")
    b = engine.get_build()
    assert b["skillGroupCount"] == n_after_aura  # repeated calls did not accumulate stale groups
    assert b["mainSkill"] == "Spark"


def test_set_skill_unknown_gem_leaves_build_unchanged(engine):
    # A bogus gem name must not silently corrupt the main skill —roll back + report (#set_skill).
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20 1")
    before = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    r = engine.paste_skill("Notaskill Foobar 20/20 1")
    assert r.get("ok") is False
    after = engine.get_build()
    assert after["mainSkill"] == "Spark"  # unchanged
    assert engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(before, rel=1e-6)


def test_complete_skill_mutation_rolls_back_silently_dropped_support(engine):
    from contextlib import nullcontext

    from server.compute import skillgroups
    from server.compute.state import build_state_hash

    class DroppingEngine:
        def __init__(self):
            self.xml = "<PathOfBuilding2><Skills /></PathOfBuilding2>"
            self.mutated = False

        def transaction_lock(self):
            return nullcontext()

        def get_xml(self):
            return self.xml

        def call(self, method, **_params):
            assert method == "list_skill_groups"
            if not self.mutated:
                return {"mainGroupIndex": 0, "groups": []}
            return {
                "mainGroupIndex": 1,
                "groups": [
                    {
                        "index": 1,
                        "gems": [{"name": "Lightning Arrow"}],
                    }
                ],
            }

        def paste_skill(self, _skill):
            self.xml = (
                "<PathOfBuilding2><Skills><Skill><Gem nameSpec='Lightning Arrow' />"
                "</Skill></Skills></PathOfBuilding2>"
            )
            self.mutated = True
            return {"ok": True}

        def load_build_xml(self, xml, **_params):
            self.xml = xml
            self.mutated = False

    dropping_engine = DroppingEngine()
    before = build_state_hash(dropping_engine.get_xml())

    result = skillgroups.set_main_skill(dropping_engine, "Lightning Arrow\nVolt")

    assert result["ok"] is False
    assert result["errorCode"] == "skill_group_incomplete"
    assert result["droppedGemNames"] == ["Volt"]
    assert build_state_hash(dropping_engine.get_xml()) == before


def test_set_skill_recovers_after_bad_input(engine):
    # The exact failure path from the test session: a bad paste must not wedge set_skill —a
    # subsequent good paste recovers the main skill with all supports.
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20 1")
    engine.paste_skill("Notaskill 20/20 1")  # rejected, build unchanged
    r = engine.paste_skill("Spark 20/20 1 / Controlled Destruction / Lightning Penetration")
    names = [g["name"] for g in engine.get_build()["mainSkillGroup"]]
    assert r["mainSkill"] == "Spark"
    assert "Controlled Destruction" in names and "Lightning Penetration" in names


def test_jewel_sockets_and_equip(engine):
    # list_jewel_sockets enumerates tree sockets; equip_jewel into an ALLOCATED socket applies its
    # mods (mana rises), and auto-pick fails cleanly when nothing is allocated.
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    socks = engine.list_jewel_sockets()["sockets"]
    assert socks and all({"socket", "allocated", "filled"} <= set(s) for s in socks)
    # nothing allocated yet -> auto-pick reports cleanly instead of wasting the jewel
    assert engine.equip_jewel("Rarity: Rare\nTJ\nSapphire\n+50 to maximum Mana")["ok"] is False
    sid = socks[0]["socket"]
    assert engine.call("alloc_passive", node=sid).get("ok")
    mana0 = engine.get_stats(["Mana"])["stats"]["Mana"]
    r = engine.equip_jewel("Rarity: Rare\nTJ\nSapphire\n+50 to maximum Mana", socket=sid)
    assert r["ok"] and not r.get("warning")
    assert engine.get_stats(["Mana"])["stats"]["Mana"] > mana0  # jewel's mana applied


def test_equip_jewel_warns_on_unallocated_socket(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    sid = engine.list_jewel_sockets()["sockets"][0]["socket"]  # unallocated
    r = engine.equip_jewel("Rarity: Rare\nTJ\nSapphire\n+50 to maximum Mana", socket=sid)
    assert r["ok"] and r.get("warning") and "not allocated" in r["warning"].lower()


def test_add_skill_group_in_full_dps_aggregates(engine):
    # A second DAMAGE skill flagged in_full_dps aggregates into FullDPS (clear+boss); without the
    # flag (auras) it would not. Here a second Spark roughly doubles FullDPS over one skill.
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.add_item(
        "Rarity: Rare\nW\nDueling Wand\nAdds 1 to 85 Lightning Damage to Spells\n"
        "100% increased Spell Damage"
    )
    engine.paste_skill("Spark 20/20  1")
    total = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    engine.add_skill_group("Spark 20/20  1", include_in_full_dps=True)
    full = engine.get_stats(["FullDPS"])["stats"]["FullDPS"]
    assert full > total * 1.5  # the second damage skill aggregated into FullDPS


def test_set_skill_computes_full_dps(engine):
    # FullDPS is off by default in PoB (only summed for groups flagged "include in Full DPS").
    # set_skill now flags the main group, so FullDPS is computed —equal to TotalDPS for a single
    # skill, and the basis for an apples-to-apples comparison against imported multi-skill builds.
    _spark_caster(engine)
    s = engine.paste_skill("Spark 20/20  1")["stats"]
    assert (s.get("FullDPS") or 0) > 0
    assert s["FullDPS"] == pytest.approx(s["TotalDPS"], rel=1e-2)


def test_rank_levers_tolerates_multi_placeholder(fireball):
    # A lever template with TWO "{}" (e.g. "Adds {} to {} ... Damage") must not crash (#rank_levers).
    from server.compute import solver

    r = solver.rank_levers(
        fireball,
        metric="TotalDPS",
        unit=10,
        levers=["Adds {} to {} Fire Damage to Spells", "{}% increased Fire Damage"],
    )
    assert r["ok"] and len(r["levers"]) == 2


def test_blank_luajit_override_is_ignored(monkeypatch):
    # A manifest user-config left blank arrives as a non-existent path (e.g. the literal
    # "${user_config.luajit_path}"); it must not shadow the bundled/system LuaJIT.
    monkeypatch.setenv("POB_LUAJIT", "${user_config.luajit_path}")
    eng = PobEngine()
    try:
        assert eng.ping()["pong"] is True
    finally:
        eng.close()


# -- optimize_build (holistic whole-build optimizer) ---------------------------------------


def test_buildopt_lever_mapping():
    # Reference topLever names map to the right tree-cluster query (the seed commitment); a
    # gear/gem-driven lever (+levels) maps to None (≈the balanced pass).
    assert buildopt._lever_tree_query("+N% to Critical Damage Bonus", ["lightning"]) == "critical"
    assert buildopt._lever_tree_query("N% increased Attack Speed", []) == "attack speed"
    assert (
        buildopt._lever_tree_query("Damage Penetrates N% Lightning Resistance", ["lightning"])
        == "lightning penetration"
    )
    assert buildopt._lever_tree_query("+N to Level of all Skills", ["fire"]) is None


def test_buildopt_unique_item_text():
    # The corpus `text` leads with name/base (and maybe a League line); the builder must not
    # duplicate them into the mod block, and must drop the League line.
    txt = buildopt._unique_item_text(
        {
            "name": "Foo",
            "base": "Bar Hat",
            "text": "Foo\nBar Hat\nLeague: X\n+10 to maximum Life\n20% increased Fire Damage",
        }
    )
    assert txt.startswith("Rarity: Unique\nFoo\nBar Hat\n--------\n")
    assert "League:" not in txt
    assert txt.count("Foo") == 1  # name not doubled into the mods
    assert "+10 to maximum Life" in txt


def test_archetype_levers_seeds_from_reference_set():
    # The reference set seeds optimize_build's candidate levers; +levels is the dominant one.
    levs = refbuilds.archetype_levers(["spell"])
    assert levs and "+N to Level of all Skills" in levs


def test_optimize_build_rejects_unset_build(engine):
    # Guards: no main skill, and a level too low to allocate a tree (an empty tree is misleading).
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(90)
    r = buildopt.optimize_build(engine, levers=[], passes=1)
    assert not r["ok"] and "skill" in r["error"].lower()

    engine.set_level(5)
    engine.paste_skill("Fireball")
    r = buildopt.optimize_build(engine, levers=[], passes=1)
    assert not r["ok"] and "level" in r["error"].lower()


def test_optimize_build_smoke(engine):
    # Integration: the holistic optimizer assembles a whole build (tree + gear + jewels + supports)
    # that beats the bare skill, meets stage resist targets, and is left LOADED. Slow (~30s).
    _spark_caster(engine)
    bare = engine.paste_skill("Spark 20/20  1")["stats"]["TotalDPS"]
    r = buildopt.optimize_build(engine, levers=[], passes=1, max_jewel_sockets=1, min_ehp=None)
    assert r["ok"], r
    assert r["committed"] == "balanced"  # levers=[] -> only the balanced candidate
    res = r["result"]
    assert (res["TotalDPS"] or 0) > bare  # synthesis added real DPS over the bare skill
    assert res["resistanceTargetMet"] is True  # the stage defensive constraint held
    # the winner is loaded in the session, so the live engine matches the reported result
    live = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    assert live == pytest.approx(res["TotalDPS"], rel=1e-3)


# -- crafting system (runes + essences + corruptions, from PoB's own data) ------------------


def test_craft_item_text_format():
    # The item-text builder lays out runes (Sockets/Rune + {rune} implicits) and a corruption
    # (implicit line + Corrupted) in the order PoB's parser accepts.
    t = craftopt._build_item(
        "Vaal Regalia",
        ["+100 to maximum Life"],
        [("Soul Core of X", ["+5% to all Elemental Resistances"])],
        "+1 to Level of all Skills",
    )
    assert "Sockets: S" in t and "Rune: Soul Core of X" in t
    assert "{rune}+5% to all Elemental Resistances" in t
    assert "Implicits: 2" in t  # one rune line + one corruption implicit
    assert t.strip().endswith("Corrupted")


def test_crafting_options_surfaces_pob_data(engine):
    # The shim surfaces PoB's own crafting data for a base: runes, corrupted implicits, and essences
    # (including the beyond-pool Perfect essences) —all as ready item-text lines.
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(92)
    engine.paste_skill("Fireball 20/20  1")
    base = db.pick_base("Body Armour", "int")
    engine.add_item(f"Rarity: Rare\nA\n{base}\n--------\n+50 to maximum Life", slot="Body Armour")
    co = engine.crafting_options("Body Armour")
    assert co["ok"]
    assert co["runes"] and co["corruptions"] and co["essences"]
    assert any(e.get("special") for e in co["essences"])  # Perfect (beyond-pool) essences present


def test_optimize_item_sockets_preserves_item_and_returns_receipt(engine, tmp_path, monkeypatch):
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(92)
    engine.paste_skill("Fireball 20/20  1")
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    base = db.pick_base("Body Armour", "int")
    original_line = "+50 to maximum Life"
    engine.add_item(
        f"Rarity: Rare\nSocket Target\n{base}\nItem Level: 82\n--------\n{original_line}",
        slot="Body Armour",
    )

    result = craftopt.optimize_item_sockets(
        engine,
        slot="Body Armour",
        goals={"TotalEHP": 1.0},
        socket_count=1,
    )

    assert result["ok"], result
    assert result["changed"] is True
    assert original_line in result["item"]
    assert result["socketCount"] == 1
    assert result["craftReceiptRef"].startswith("craft-legality:")
    equipped = main.equip_item(
        result["item"],
        slot="Body Armour",
        craft_receipt_ref=result["craftReceiptRef"],
    )
    assert equipped["ok"] is True, equipped


def test_generated_endgame_belt_round_trips_three_charm_slots(engine):
    engine.new_build()
    engine.set_class("Ranger", "Deadeye")
    engine.set_level(90)
    raw = itemopt._item_text("Fine Belt", ["+30 to Dexterity"], "Belt", ilvl=90)

    equipped = engine.add_item(raw, slot="Belt")
    build = engine.get_build()

    assert equipped["ok"] is True
    assert build["gear"]["Belt"]["charmSlots"] == 3
    assert build["charmLimit"] == 3


@pytest.mark.timeout(1800)
def test_optimize_build_crafting_keeps_resistance_target_met(engine):
    # The crafting post-pass re-crafts every slot independently, which can strip the cross-slot resist
    # balance plan_gear set up. The repair pass must restore the configured stage target.
    # Slow on Windows/PoB headless (about 15 min on the current pinned runtime, and slower after
    # earlier tests reuse the session engine): full crafting on a whole gear set. Match the
    # explicit compute profile's 30-minute heavy-test budget while ordinary tests remain strict.
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1")
    r = buildopt.optimize_build(
        engine, levers=[], passes=1, max_jewel_sockets=0, min_ehp=None, crafting=True
    )
    assert r["ok"], r
    res = r["result"]
    assert res["craftedGear"]  # crafting actually ran on the gear
    assert res["resistanceTargetMet"] is True


def test_craft_item_beats_plain_rare_and_round_trips_source_receipt(
    engine,
    tmp_path,
    monkeypatch,
):
    # craft_item adds the crafting system on top of the best rare, so it must not be worse than a
    # plain optimize_item rare, and should actually engage at least one crafting method. Slow (~15s).
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(92)
    engine.paste_skill("Fireball 20/20  1")
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    base = db.pick_base("Body Armour", "int")
    plain = itemopt.optimize_item(engine, "Body Armour", metric="TotalEHP", base=base)
    crafted = craftopt.craft_item(
        engine, "Body Armour", metric="TotalEHP", base=base, rune_sockets=2
    )
    assert crafted["ok"], crafted
    assert (crafted["metricCrafted"] or 0) >= (plain["metricAfter"] or 0)
    c = crafted["crafting"]
    assert c["runes"] or c["essencesUsed"] or c["corruptedImplicit"]  # crafting actually engaged
    assert crafted["craftReceiptRef"].startswith("craft-legality:")
    assert crafted["legalityCheck"]["ok"] is True

    before_hash = build_state_hash(engine.get_xml())
    equipped = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="required_gear",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw=crafted["item"],
                slot="Body Armour",
                craft_receipt_ref=crafted["craftReceiptRef"],
            )
        ],
        expected_state_hash=before_hash,
        result_decorator=main._decorate_batch_mutation_result,
    )
    assert equipped["ok"] is True, equipped
    legality = hard_legality.audit_active_build(engine)
    assert "illegal_equipped_item_affixes" not in legality["hardFailures"]
