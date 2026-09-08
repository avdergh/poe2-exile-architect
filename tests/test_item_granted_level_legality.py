from __future__ import annotations

from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET

import pytest

from server.compute import equipment
from server.compute.engine import _find_luajit
from server.compute.state import build_state_hash


ADONIA = """Rarity: UNIQUE
Adonia's Ego
Siphoning Wand
Requires Level 65
Implicits: 1
Grants Skill: Level 20 Power Siphon
Grants Skill: Pinnacle of Power
+125 to maximum Mana
+3 to Level of all Spell Skills
23% increased Cast Speed
-10% to all Elemental Resistances per Power Charge
-1 to Maximum Power Charges"""


@pytest.mark.parametrize("slot", ["Weapon 1", "Weapon 1 Swap"])
def test_fixed_item_grant_uses_pob_level_and_preserves_readback(engine, slot):
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(95)
    engine.paste_skill("Spark 20/20 1")
    result = equipment.equip_item_verified(engine, raw=ADONIA, slot=slot, craft_receipt_ref=None)
    assert result["ok"], result
    state = build_state_hash(engine.get_xml())
    for reload in (False, True):
        if reload:
            engine.load_build_xml(engine.get_xml())
        groups = engine.call("list_skill_groups")["groups"]
        pinnacle = next(g for g in groups if g["gems"][0]["name"] == "Pinnacle of Power")
        gem = pinnacle["gems"][0]
        assert pinnacle["source"].startswith("Item:")
        assert gem["level"] == 20
        assert gem["naturalMaxLevel"] == 1
        assert gem["maximumLegalLevel"] == 20
        assert gem["levelAuthority"] == "item_grant"
        assert gem["levelRequirementMet"] is True
        assert engine.get_build()["activeSkillGemLevelViolations"] == []
        assert build_state_hash(engine.get_xml()) == state


def test_manually_socketed_item_skill_cannot_borrow_item_level_authority(engine):
    engine.new_build()
    engine.set_level(95)
    engine.paste_skill("Spark 20/20 1")
    before = build_state_hash(engine.get_xml())
    rejected = engine.add_skill_group("Pinnacle of Power 20/0 1")
    assert rejected["ok"] is False
    assert rejected["errorCode"] == "active_skill_gem_level_requirement_unmet"
    assert rejected["violations"][0]["reason"] == "base_gem_level_exceeds_natural_maximum"
    assert rejected["violations"][0]["levelAuthority"] == "gem"
    assert build_state_hash(engine.get_xml()) == before


def test_xml_source_and_from_item_flags_cannot_forge_item_grant(engine):
    engine.new_build()
    engine.set_level(95)
    engine.paste_skill("Spark 20/20 1")
    root = ET.fromstring(engine.get_xml())
    skill = root.find(".//Skills/SkillSet/Skill")
    assert skill is not None
    skill.set("source", "Item:999999:Adonia's Ego")
    skill.set("slot", "Weapon 1")
    gem = skill.find("Gem")
    gem.set("fromItem", "true")
    engine.load_build_xml(ET.tostring(root, encoding="unicode"))
    groups = engine.call("list_skill_groups")["groups"]
    assert all(
        gem.get("levelAuthority") != "item_grant"
        for group in groups
        for gem in group.get("gems", [])
    )


def test_item_grant_audit_fails_closed_on_lost_binding_or_model(tmp_path):
    bridge = (Path(__file__).parents[1] / "pob/pob_headless.lua").read_text(encoding="utf-8")
    helpers = bridge[
        bridge.index("local function itemGrantedLevelForSocketGroup") : bridge.index(
            "local function activeGemLevelViolations()"
        )
    ]
    harness = """
local function asNumber(value) return tonumber(value) or 0 end
calcLib = { validateGemLevel = function(gem) return gem end }
local effect = { levels = { [20] = { levelRequirement = 0 } } }
local grant = { source = 'Item:1', skillId = 'FixedGrant', level = 20 }
local item = { grantedSkills = { grant } }
local gem = { nameSpec = 'Fixed Grant', skillId = 'FixedGrant', level = 20,
    fromItem = true, gemData = { grantedEffect = effect, naturalMaxLevel = 1 } }
local group = { source = 'Item:1', slot = 'Weapon 1', sourceItem = item, gemList = { gem } }
local build = { characterLevel = 95, data = { skills = { FixedGrant = effect } },
    skillsTab = { socketGroupList = { group } },
    itemsTab = { items = { item }, slots = { ['Weapon 1'] = { selItemId = 1 } } } }
"""
    assertions = """
assert(gemSummaryForSocketGroup(1)[1].levelRequirementMet == true)
local function rejected()
    local violations = activeGemLevelViolationsForSocketGroup(1)
    assert(#violations == 1)
    assert(violations[1].reason == 'item_granted_skill_source_unverified')
end
group.source = 'Item:2'; rejected(); group.source = 'Item:1'
build.itemsTab.items[1] = {}; rejected(); build.itemsTab.items[1] = item
grant.skillId = 'OtherSkill'; rejected(); grant.skillId = 'FixedGrant'
grant.level = 19; rejected(); grant.level = 20
effect.levels = {}; rejected()
"""
    script = tmp_path / "item-grant-audit.lua"
    script.write_text(harness + helpers + assertions, encoding="utf-8")
    subprocess.run([_find_luajit(), str(script)], check=True, capture_output=True, timeout=30)
