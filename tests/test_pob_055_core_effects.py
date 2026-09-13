"""0.5.5 real-model probes; exact native effects, not a whole-build DPS claim."""

from pathlib import Path
import re

import pytest

from server.compute import craftopt, skillgroups, socket_limits


# Each target is independently bound to its tag in the pinned Gem export below.
LEVEL_CORES = [
    ("Abundance", "plant", "Vine Arrow", "Crude Bow"),
    ("Automation", "totem", "Shockwave Totem", "Crumbling Maul"),
    ("Malediction", "curse", "Temporal Chains", "Attuned Wand"),
    ("Munitions", "grenade", "Explosive Grenade", "Bombard Crossbow"),
    ("Quaking", "slam", "Earthquake", "Crumbling Maul"),
    ("Radiance", "herald", "Herald of Ash", "Bombard Crossbow"),
    ("Rallying", "warcry", "Infernal Cry", "Crumbling Maul"),
    ("Rippling", "nova", "Ice Nova", "Attuned Wand"),
    ("Severing", "strike", "Boneshatter", "Crumbling Maul"),
    ("Snares", "hazard", "Spearfield", "Hardwood Spear"),
    ("Squalls", "wind", "Twister", "Hardwood Spear"),
    ("Targeting", "mark", "Sniper's Mark", "Crude Bow"),
    ("Thundering", "storm", "Firestorm", "Attuned Wand"),
]


def _start(engine, skill="Fireball", base="Attuned Wand"):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(95)
    engine.set_config(custom_mods="+500 to Strength\n+500 to Dexterity\n+500 to Intelligence")
    result = engine.paste_skill(f"{skill} 19/0  1")
    assert result.get("mainSkill") == skill, result
    raw = f"Rarity: Normal\n{base}\nItem Level: 90"
    assert engine.add_item(raw, slot="Weapon 1")["ok"]
    return raw


def _root(engine, skill):
    groups = skillgroups.list_skill_groups(engine)["groups"]
    selected = [group for group in groups if group["gems"][0]["name"] == skill]
    assert len(selected) == 1, [(g["index"], g.get("activeSkill")) for g in groups]
    group = selected[0]
    effects = [effect for effect in group["activeSkills"] if effect["effectId"] == group["gems"][0]["effectId"]]
    assert len(effects) == 1
    return group, effects[0]


@pytest.mark.parametrize("suffix,tag,skill,base", LEVEL_CORES)
def test_new_jiquani_core_increases_only_matching_native_effect_level(engine, suffix, tag, skill, base):
    export = (Path(__file__).resolve().parents[1] / "pob/PathOfBuilding-PoE2/src/Data/Gems.lua").read_text(encoding="utf-8")
    blocks = [b for b in re.split(r"\n\t\[", export) if f'name = "{skill}"' in b]
    assert len(blocks) == 1
    assert re.search(rf"\b{tag} = true", blocks[0]), (tag, skill)
    raw = _start(engine, skill, base)
    group, before = _root(engine, skill)
    assert before["effectiveLevel"] == 19
    unrelated = engine.add_skill_group("Fireball 19/0  1" if skill != "Fireball" else "Spark 19/0  1")
    assert unrelated.get("mainSkill") == skill
    name = f"Jiquani's Soul Core of {suffix}"
    options = [o for o in engine.crafting_options("Weapon 1")["runes"] if o["name"] == name]
    assert len(options) == 1, name
    option = options[0]
    assert socket_limits.constraints(option) == [{"group": name, "limit": 1}]
    augmented = craftopt._augment_item_with_runes(raw, [(name, option["mods"])], socket_capacity=1)
    assert engine.add_item(augmented, slot="Weapon 1")["ok"]
    after_group, after = _root(engine, skill)
    assert after_group["gems"][0]["level"] == 19  # natural gem legality stays separate
    assert after["effectiveLevel"] == 20
    assert _root(engine, "Fireball")[1]["effectiveLevel"] == 19
    assert engine.get_stats()["mainSkill"] == skill
    xml = engine.get_xml()
    engine.load_build_xml(xml)
    assert _root(engine, skill)[1]["effectiveLevel"] == 20


@pytest.mark.parametrize("suffix,slot,base,metric,unit,modifier", [
    ("Alacrity", "Gloves", "Ringmail Gauntlets", "Speed", 1, "{n}% increased Skill Speed"),
    ("Devotion", "Helmet", "Imperial Greathelm", "Spirit", 1, "{n}% increased Spirit"),
    ("Inoculation", "Boots", "Iron Greaves", "ChaosResist", 2, "+{n}% to Chaos Resistance"),
    ("Vitality", "Body Armour", "Heroic Armour", "Life", 1, "{n}% increased Maximum Life"),
])
def test_new_atziri_core_scales_with_actual_corrupted_equipment(engine, suffix, slot, base, metric, unit, modifier):
    _start(engine)
    raw = f"Rarity: Normal\n{base}\nItem Level: 90"
    assert engine.add_item(raw, slot=slot)["ok"]
    before = engine.get_stats([metric])["stats"][metric]
    name = f"Atziri's Soul Core of {suffix}"
    option = next(o for o in engine.crafting_options(slot)["runes"] if o["name"] == name)
    assert socket_limits.constraints(option) == [{"group": name, "limit": 1}]
    augmented = craftopt._augment_item_with_runes(raw, [(name, option["mods"])], socket_capacity=1)
    assert engine.add_item(augmented, slot=slot)["ok"]
    assert engine.get_stats([metric])["stats"][metric] == before
    original_mods = engine.get_build()["customMods"]
    for count in (1, 2):
        assert engine.add_item("Rarity: Normal\nIron Ring\nItem Level: 90\nCorrupted", slot=f"Ring {count}")["ok"]
        observed = engine.get_stats([metric])["stats"][metric]
        assert observed > before
        snapshot = engine.get_xml()
        # Native unconditional-mod oracle: PoB owns additive scaling and integer
        # rounding; the test binds the documented per-item quantity and condition.
        assert engine.add_item(raw, slot=slot)["ok"]
        engine.set_config(custom_mods=original_mods + "\n" + modifier.format(n=count * unit))
        assert engine.get_stats([metric])["stats"][metric] == pytest.approx(observed)
        engine.load_build_xml(snapshot)
        assert engine.get_stats([metric])["stats"][metric] == observed
