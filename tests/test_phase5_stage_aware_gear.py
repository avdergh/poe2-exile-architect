from __future__ import annotations

import pytest

from server.compute import itemopt


@pytest.mark.parametrize(
    (
        "level",
        "stage",
        "expected_stage",
        "elemental_target",
        "chaos_target",
        "defense_weight",
    ),
    [
        (58, "auto", "campaign", 30, 0, 0.65),
        (75, "auto", "maps_entry", 50, 30, 0.72),
        (90, "auto", "endgame", 60, 30, 0.78),
        (58, "endgame", "endgame", 60, 30, 0.78),
    ],
)
def test_gear_stage_profile(
    level, stage, expected_stage, elemental_target, chaos_target, defense_weight
):
    profile = itemopt.gear_stage_profile(level, stage=stage)

    assert profile == {
        "stage": expected_stage,
        "elementalResistTarget": elemental_target,
        "chaosResistTarget": chaos_target,
        "defenseWeight": defense_weight,
    }


def test_gear_stage_profile_allows_deliberate_chaos_target_override():
    profile = itemopt.gear_stage_profile(58, chaos_resist_target=75)

    assert profile["stage"] == "campaign"
    assert profile["chaosResistTarget"] == 75


def test_gear_stage_profile_rejects_unknown_stage():
    with pytest.raises(ValueError, match="stage must be"):
        itemopt.gear_stage_profile(58, stage="bossing")  # type: ignore[arg-type]


def test_chaos_affixes_stop_competing_after_stage_target():
    mods = [
        {"text": "+(20-30)% to Chaos Resistance", "group": "chaos"},
        {"text": "+(40-50)% to Fire Resistance", "group": "fire"},
    ]

    filtered = itemopt._without_unneeded_chaos_resistance(mods, current_chaos=0, target_chaos=0)

    assert [mod["group"] for mod in filtered] == ["fire"]


def test_chaos_affixes_remain_available_below_stage_target():
    mods = [{"text": "+(20-30)% to Chaos Resistance", "group": "chaos"}]

    filtered = itemopt._without_unneeded_chaos_resistance(mods, current_chaos=0, target_chaos=30)

    assert filtered == mods


def test_item_text_keeps_the_affix_pool_item_level():
    item = itemopt._item_text("Fine Belt", ["+30 to maximum Life"], "Belt", ilvl=58)

    assert "Item Level: 58" in item
    assert "Charm Slots: 1" in item
    assert "Implicits: 2" in item
    assert "Has 1 Charm Slot" in item
    assert "Flasks gain 0.17 charges per Second" in item
    assert item.index("Item Level: 58") < item.index("Implicits: 2")
