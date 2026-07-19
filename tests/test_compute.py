"""Golden-value tests for the headless calculation engine + import codec.

Values are pinned to the PoB-PoE2 commit in pob/PINNED.md; if you bump the submodule and
these drift, re-verify against the GUI and update them in the same commit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.compute import buildopt, craftopt, itemopt
from server.compute.engine import PobEngine
from server.compute.pob_code import decode_code, encode_code
from server.knowledge import db, refbuilds

FIREBALL_DPS = 124.833
FIREBALL_AVG = 149.8


def test_ping(engine):
    assert engine.ping()["pong"] is True


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

    build = engine.get_build()

    assert build["judgeSelectedSkill"]["skillName"] == "Detonate Living"
    assert build["judgeSelectedSkill"]["groupOrigin"] == "socketed"
    explosion = next(
        component
        for component in build["judgeSupplementalSkills"]
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

    build = engine.get_build()

    assert build["judgeSelectedSkill"]["skillName"] == "Fireball"
    assert build["judgeSelectedSkill"]["groupOrigin"] == "socketed"
    thorns = next(
        component
        for component in build["judgeSupplementalSkills"]
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
    # the build must be restored — no lingering custom mod from probing
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
    # Stable candidate ordering -> identical allocation across runs (no pairs()-order drift). (#5)
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")
    first = engine.optimize_passives(metric="balanced", points=0)["pointsUsed"]
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")
    second = engine.optimize_passives(metric="balanced", points=0)["pointsUsed"]
    assert first == second


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
    assert len(r["affixes"]) <= 6  # respects 3 prefix / 3 suffix
    # build-aware: a non-crit lightning build's max-DPS wand uses a Lightning mod
    assert any("Lightning" in a for a in r["affixes"])
    # probing is restored
    assert engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(base, rel=1e-6)


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
    assert isinstance(
        engine.get_stats(["TotalDPS"])["stats"], dict
    )  # not [] even when uncomputable
    r = itemopt.optimize_item(engine, "Weapon 1", base="Grand Spear", metric="TotalDPS")
    assert r["ok"]
    assert r["metricBefore"] is None  # no weapon -> nothing to measure before
    assert isinstance(r["metricAfter"], (int, float)) and r["metricAfter"] > 0
    assert r["affixes"]  # crafted a real spear


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
    # Weighted `goals` craft ONE piece carrying both damage and defense — the realistic-gear path,
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
    for a in r["attainability"]:
        assert a["affix"] and a["ilvl"] >= 0 and a["tiers"] >= 1
    craft = r["craft"]
    assert craft["effort"] in {"trivial", "low", "moderate", "high", "very high"}
    assert craft["minItemLevel"] >= 1 and craft["prefixPool"] >= 1


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
    assert engine.get_build()["mainSkill"] == "Lightning Spear"  # read-only: build restored


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
    assert itemopt.optimize_jewel(engine, base="Grand Spear")["ok"] is False  # not a jewel base
    assert engine.get_build()["mainSkill"] == "Lightning Spear"  # read-only


def test_plan_gear_caps_resists_while_keeping_damage(engine):
    # Cross-slot budget allocation: offense slots damage-leaning, defense slots EHP-leaning (which
    # pulls resists onto the cheapest-DPS pieces). Read-only; returns a coherent whole-set plan.
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
    pj = r["projected"]
    assert pj["resistsCapped"] is True  # defense slots pull resists to cap
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
    # The dpsNote must NOT claim PoE2 "has no shotgunning" (false — overlap is per-skill) and must
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
    # "Critical Strike Chance" is silently ignored by the engine — which had made the crit lever
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
    assert ignored == base  # PoE1 wording does nothing — documents the rename


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
    # Gap C guardrail: the engine does NOT model energy-based meta triggers (Cast on Critical → a
    # socketed spell computes as a weak self-cast), so the tools must surface `engineLimitation` when
    # such a gem is present — and must NOT false-flag ordinary skills/supports.
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
    # their mods/name match (corpus relevance — the engine still verifies actual value).
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
    assert r["projected"]["resistsCapped"]  # a whole auto-based set caps resists
    assert "ehpFloorMet" in r["projected"]  # the min_ehp floor is evaluated + reported
    assert engine.get_build()["mainSkill"] == "Spark"  # read-only: build restored


def test_campaign_plan_gear_does_not_keep_chasing_capped_chaos_resistance(engine):
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(58)
    engine.paste_skill("Spark 20/20 1")
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
    # CAPPED `points` call reports the build's TRUE unspent passive points — not a budget-relative 0
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
    # (>budget) tree — it skips + reports them. reset=True re-plans from scratch so the required
    # nodes (e.g. jewel sockets) fit within budget — the clean way to add sockets to a full tree.
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


def test_get_build_auto_selects_best_damage_skill_when_main_group_is_buff(engine):
    # Imported poe.ninja/PoB samples often preserve the last-clicked UI skill as main.
    # A buff main group must not force Judge to score offense as 0 when another enabled
    # damage group is computable.
    engine.new_build()
    engine.set_class("Witch", "Infernalist")
    engine.set_level(90)
    engine.paste_skill("Plague Bearer 20/20  1")
    engine.add_skill_group("Fireball 20/20  1")

    b = engine.get_build()

    assert b["mainSkill"] == "Plague Bearer"
    selected = b["judgeSelectedSkill"]
    assert selected["skillName"] == "Fireball"
    assert selected["dps"] > 0
    assert "auto_selected_damage_skill_caveat" in selected["caveats"]
    selected_group_names = [g["name"] for g in b["judgeSelectedSkillGroup"]]
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

    selected = engine.get_build()["judgeSelectedSkill"]

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

    selected = engine.get_build()["judgeSelectedSkill"]

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

    selected = engine.get_build()["judgeSelectedSkill"]

    assert selected["skillName"] == "Fireball"
    assert selected["activeSkillCount"] == 3
    assert selected["rawDps"] == pytest.approx(selected["dps"], rel=1e-6)
    assert selected["effectiveDps"] == pytest.approx(selected["dps"], rel=1e-6)


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
    # cold damage does nothing for a pure-fire Fireball — must be flagged, not "unreachable"
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
    # A bogus gem name must not silently corrupt the main skill — roll back + report (#set_skill).
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20 1")
    before = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    r = engine.paste_skill("Notaskill Foobar 20/20 1")
    assert r.get("ok") is False
    after = engine.get_build()
    assert after["mainSkill"] == "Spark"  # unchanged
    assert engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(before, rel=1e-6)


def test_set_skill_recovers_after_bad_input(engine):
    # The exact failure path from the test session: a bad paste must not wedge set_skill — a
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
    # set_skill now flags the main group, so FullDPS is computed — equal to TotalDPS for a single
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
    # gear/gem-driven lever (+levels) maps to None (≈ the balanced pass).
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
    engine.paste_skill("Fireball 20/20  1")
    r = buildopt.optimize_build(engine, levers=[], passes=1)
    assert not r["ok"] and "level" in r["error"].lower()


def test_optimize_build_smoke(engine):
    # Integration: the holistic optimizer assembles a whole build (tree + gear + jewels + supports)
    # that beats the bare skill, caps resistances, and is left LOADED in the session. Slow (~30s).
    _spark_caster(engine)
    bare = engine.paste_skill("Spark 20/20  1")["stats"]["TotalDPS"]
    r = buildopt.optimize_build(engine, levers=[], passes=1, max_jewel_sockets=1, min_ehp=None)
    assert r["ok"], r
    assert r["committed"] == "balanced"  # levers=[] -> only the balanced candidate
    res = r["result"]
    assert (res["TotalDPS"] or 0) > bare  # synthesis added real DPS over the bare skill
    assert res["resistsCapped"] is True  # the defensive constraint held
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
    # (including the beyond-pool Perfect essences) — all as ready item-text lines.
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


@pytest.mark.timeout(900)
def test_optimize_build_crafting_keeps_resists_capped(engine):
    # The crafting post-pass re-crafts every slot independently, which can strip the cross-slot resist
    # balance plan_gear set up. The re-cap pass must restore it — a crafted build must stay capped.
    # Slow on Windows/PoB headless (~7 min observed during PoB v0.21.1 certification):
    # full crafting on a whole gear set. Keep an explicit timeout so the global certification
    # gate can stay strict for ordinary tests while this end-to-end path must still finish.
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1")
    r = buildopt.optimize_build(
        engine, levers=[], passes=1, max_jewel_sockets=0, min_ehp=None, crafting=True
    )
    assert r["ok"], r
    res = r["result"]
    assert res["craftedGear"]  # crafting actually ran on the gear
    assert res["resistsCapped"] is True  # crafting must NOT break the resist cap


def test_craft_item_beats_plain_rare(engine):
    # craft_item adds the crafting system on top of the best rare, so it must not be worse than a
    # plain optimize_item rare, and should actually engage at least one crafting method. Slow (~15s).
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(92)
    engine.paste_skill("Fireball 20/20  1")
    base = db.pick_base("Body Armour", "int")
    plain = itemopt.optimize_item(engine, "Body Armour", metric="TotalEHP", base=base)
    crafted = craftopt.craft_item(
        engine, "Body Armour", metric="TotalEHP", base=base, rune_sockets=2
    )
    assert crafted["ok"], crafted
    assert (crafted["metricCrafted"] or 0) >= (plain["metricAfter"] or 0)
    c = crafted["crafting"]
    assert c["runes"] or c["essencesUsed"] or c["corruptedImplicit"]  # crafting actually engaged
