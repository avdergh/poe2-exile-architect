"""C5/C6 public planner regressions on pinned PoB, with a bounded real affix pool."""

import pytest

from server.compute import itemopt, item_search, skillgroups, craftopt
from server.compute.state import build_state_hash


RING = "Rarity: Rare\nReplacement Baseline\nGold Ring\nItem Level: 90\n--------\n+30% to Fire Resistance"


@pytest.fixture
def ring_case(fireball, monkeypatch):
    engine = fireball
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    initial = engine.get_defenses()["resistances"]
    engine.set_config(
        custom_mods="\n".join(
            [
                f"+{30 - initial['fire']}% to Fire Resistance",
                f"+{60 - initial['cold']}% to Cold Resistance",
                f"+{60 - initial['lightning']}% to Lightning Resistance",
                f"+{30 - initial['chaos']}% to Chaos Resistance",
                "+500 to Strength",
                "+500 to Dexterity",
                "+500 to Intelligence",
            ]
        )
    )
    assert engine.add_item(RING, slot="Ring 1")["ok"]
    assert engine.get_defenses()["resistances"]["fire"] == 60
    pool = {
        "prefixes": [
            {
                "text": "+50 to maximum Life",
                "type": "prefix",
                "group": "IncreasedLife",
                "tier": 3,
                "totalTiers": 10,
            }
        ],
        "suffixes": [
            {
                "text": "+30% to Fire Resistance",
                "type": "suffix",
                "group": "FireResistance",
                "tier": 3,
                "totalTiers": 10,
            }
        ],
    }
    monkeypatch.setattr(itemopt.db, "affix_pool", lambda *_args, **_kwargs: pool)
    return engine


def test_plan_gear_retains_needed_resistance_from_replaced_ring(ring_case):
    engine = ring_case
    before = build_state_hash(engine.get_xml())
    missing_slot = item_search.resistances_without_slot(engine, "Ring 1")
    assert missing_slot["fire"] == 30
    result = itemopt.plan_gear(engine, slots=["Ring 1"], auto_base=False, dps_weight=0)
    assert result["ok"], result
    assert result["planReplayVerified"]
    assert len(result["plan"]) == 1, result
    assert "+30% to Fire Resistance" in result["plan"][0]["item"]
    assert result["projected"]["resistances"]["fire"] == 60
    assert result["projected"]["resistanceTargetMet"]
    assert build_state_hash(engine.get_xml()) == before


def test_single_item_uses_same_missing_slot_context_and_full_item(ring_case):
    engine = ring_case
    before = build_state_hash(engine.get_xml())
    result = itemopt.optimize_item(engine, "Ring 1", metric="TotalEHP", ilvl=90)
    assert result["ok"], result
    assert "+30% to Fire Resistance" in result["item"]
    assert result["metricAfter"] > result["metricBefore"]
    assert build_state_hash(engine.get_xml()) == before


def test_source_target_disappearance_cannot_rank_another_skill(fireball, monkeypatch):
    engine = fireball
    engine.set_level(90)
    staff = "Rarity: Rare\nSource Target\nAshen Staff\nItem Level: 90\nImplicits: 1\nGrants Skill: Level 20 Firebolt\n50% increased Spell Damage"
    assert engine.add_item(staff, slot="Weapon 1")["ok"]
    listed = skillgroups.list_skill_groups(engine)
    group = next(group for group in listed["groups"] if group.get("sourceKind") == "item")
    engine.call("set_skill_group_state", index=group["index"], activeSkillIndex=1, makeMain=True)
    snapshot_hash = build_state_hash(engine.get_xml())
    pool = {
        "prefixes": [
            {
                "text": "100% increased Spell Damage",
                "type": "prefix",
                "group": "SpellDamage",
                "tier": 2,
                "totalTiers": 3,
            }
        ],
        "suffixes": [],
    }
    monkeypatch.setattr(itemopt.db, "affix_pool", lambda *_args, **_kwargs: pool)
    result = itemopt.optimize_item(engine, "Weapon 1", ilvl=90)
    assert result["ok"] is False, result
    assert result["errorCode"] == "item_measurement_incomplete"
    assert result["failureCodes"]
    assert result["rolledBack"] is True
    assert build_state_hash(engine.get_xml()) == snapshot_hash


@pytest.mark.parametrize("wrong_weapon", [False, True])
def test_attack_craft_unknown_baseline_is_limited_to_empty_weapon(
    engine, monkeypatch, wrong_weapon
):
    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.set_config(custom_mods="+200 to Strength\n+200 to Dexterity")
    if wrong_weapon:
        assert engine.add_item("Rarity: Normal\nAttuned Wand\nItem Level: 82", slot="Weapon 1")[
            "ok"
        ]
    before = build_state_hash(engine.get_xml())
    pool = {
        "prefixes": [
            {
                "text": "50% increased Physical Damage",
                "type": "prefix",
                "group": "LocalPhysicalDamagePercent",
                "tier": 3,
                "totalTiers": 10,
            }
        ],
        "suffixes": [],
    }
    monkeypatch.setattr(itemopt.db, "affix_pool", lambda *_a, **_k: pool)
    result = craftopt.craft_item(
        engine,
        "Weapon 1",
        base="Grand Spear",
        metric="TotalDPS",
        use_essences=False,
        rune_sockets=0,
        use_corruption=False,
    )
    if wrong_weapon:
        assert result["ok"] is False, result
        assert result["errorCode"] == "item_measurement_incomplete"
    else:
        assert result["ok"], result
        assert result["metricBefore"] is None
        assert result["metricAfter"] > 0
        assert result["comparison"]["baselineStatus"] == "unavailable_empty_weapon"
        assert result["comparison"]["comparisonAvailable"] is False
        assert result["comparison"]["netGain"] is None
        assert result["comparison"]["positiveGainProven"] is False
    assert result["rolledBack"] is True
    assert build_state_hash(engine.get_xml()) == before
