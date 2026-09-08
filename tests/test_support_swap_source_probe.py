"""Real PoB coverage for a source skill while another group remains main."""

from server.compute import skillgroups, supportopt
from server.compute.state import build_state_hash


def test_nonmain_swap_source_support_comparison_activates_then_selects(engine, monkeypatch):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(95)
    engine.paste_skill("Spark 20/20 1")
    engine.set_config(custom_mods="+500 to Strength\n+500 to Dexterity\n+500 to Intelligence")
    assert engine.add_item(
        "Rarity: Unique\nAdonia's Ego\nSiphoning Wand\nItem Level: 90\n"
        "Grants Skill: Level 20 Power Siphon\nGrants Skill: Pinnacle of Power\n"
        "+100 to maximum Mana\n+3 to Level of all Spell Skills\n"
        "15% increased Cast Speed\n-10% to all Elemental Resistances per Power Charge",
        slot="Weapon 1 Swap",
    )["ok"]
    listed = skillgroups.list_skill_groups(engine)
    spark = next(g for g in listed["groups"] if g.get("rootSkillId") == "SparkPlayer")
    assert engine.call("set_skill_group_state", index=spark["index"], makeMain=True)["ok"]
    snapshot = engine.get_xml()
    engine.load_build_xml(snapshot)
    listed = skillgroups.list_skill_groups(engine)
    source = next(g for g in listed["groups"] if g.get("rootSkillId") == "PowerSiphonPlayer")
    assert source["activeSkills"] == []
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Efficiency II"])

    result = supportopt.optimize_supports(
        engine,
        group_index=source["index"],
        expected_fingerprint=source["fingerprint"],
        metric="ManaCost",
    )

    assert result["ok"] is True, result
    comparison = result["measurement"]["combinationComparison"]
    assert comparison["status"] == "complete"
    assert comparison["selectedEffectId"] == "PowerSiphonPlayer"
    assert comparison["sameContext"] is True
    assert comparison["baselineMeasurable"] is True
    assert comparison["candidateMeasurable"] is True
    assert 0 <= comparison["candidateMetrics"]["ManaCost"] <= comparison["baselineMetrics"]["ManaCost"]
    assert result["measurement"]["failedCandidates"] == 0
    assert result["measurement"]["failedCombinations"] == 0
    assert build_state_hash(engine.get_xml()) == build_state_hash(snapshot)
    assert engine.call("list_skill_groups")["mainGroupIndex"] == spark["index"]
