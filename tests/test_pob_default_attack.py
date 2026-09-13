"""Native default attacks stay source-bound across selection, support edits and restore."""

from copy import deepcopy

import pytest

from server.compute import skillgroups
from server.compute.state import build_state_hash
from server.generation import preflight, validation_checkpoint


def _start(engine):
    engine.new_build()
    engine.set_class("Mercenary", "Tactician")
    engine.set_level(95)
    engine.set_config(custom_mods="+500 to Strength\n+500 to Dexterity\n+500 to Intelligence")
    assert engine.add_item("Rarity: Normal\nBombard Crossbow\nItem Level: 90", slot="Weapon 1")["ok"]


def _attack(engine, slot="Weapon 1"):
    matches = [g for g in skillgroups.list_skill_groups(engine)["groups"]
               if g.get("sourceKind") == "default_attack" and g.get("slot") == slot]
    assert len(matches) == 1
    return matches[0]


def test_native_attack_has_legal_level_and_keeps_supports_when_main_is_replaced(engine):
    _start(engine)
    group = _attack(engine)
    assert group["gems"][0]["levelAuthority"] == "default_attack"
    assert group["gems"][0]["levelRequirementMet"] is True
    result = skillgroups.configure_source_skill_supports(
        engine, source_group_index=group["index"], supports=["Rapid Attacks I"],
        expected_fingerprint=group["fingerprint"], expected_state_hash=build_state_hash(engine.get_xml()),
    )
    assert result["ok"], result
    assert result["sourceKind"] == "default_attack"
    assert result["supportApplication"][0]["activeSkills"]
    assert engine.paste_skill("Fireball 20/0  1")["mainSkill"] == "Fireball"
    assert [g["name"] for g in _attack(engine)["gems"]][1:] == ["Rapid Attacks I"]
    assert engine.add_skill_group("Flame Wall 20/0  1")["mainSkill"] == "Fireball"
    before = build_state_hash(engine.get_xml())
    engine.load_build_xml(engine.get_xml())
    assert build_state_hash(engine.get_xml()) == before
    assert engine.get_stats()["mainSkill"] == "Fireball"
    assert [g["name"] for g in _attack(engine)["gems"]][1:] == ["Rapid Attacks I"]


def test_native_attack_wrong_support_rolls_back_and_weapon_sets_keep_distinct_identity(engine):
    _start(engine)
    assert engine.add_item("Rarity: Normal\nBombard Crossbow\nItem Level: 90", slot="Weapon 1 Swap")["ok"]
    assert engine.paste_skill("Fireball 20/0  1")["mainSkill"] == "Fireball"
    first, second = _attack(engine), _attack(engine, "Weapon 1 Swap")
    assert first["index"] != second["index"]
    before = build_state_hash(engine.get_xml())
    result = skillgroups.configure_source_skill_supports(
        engine, source_group_index=first["index"], supports=["Bidding III"],
        expected_fingerprint=first["fingerprint"], expected_state_hash=before,
    )
    assert result["errorCode"] == "source_support_not_applied"
    assert build_state_hash(engine.get_xml()) == before
    inspected = preflight.inspect_generation_snapshot(engine, engine.get_xml())
    assert "duplicate_enabled_skill_group" not in inspected.get("hardFailures", [])
    assert [g["sourceKind"] for g in inspected["skillGroups"] if g.get("source") == "Default Attack"] == ["default_attack"] * 2


def _checklist(group, context=None):
    class AuditEngine:
        def get_xml(self):
            return "<PathOfBuilding2><Items activeItemSet='1'><ItemSet id='1'/></Items></PathOfBuilding2>"

    engine = AuditEngine()
    return validation_checkpoint._create_quality_checklist(
        engine=engine, xml=engine.get_xml(), state_hash="sha256:default-attack-test",
        build={"level": 95, "gear": {}}, stats={},
        completeness_result={"passiveJewels": {}, "runes": {}, "charms": {}, "flasks": {}},
        preflight_result={"skillGroups": [group]}, calculation_context=context,
    )


_INCIDENTAL = {
    "groupIndex": 2, "role": "additional_skill_group", "source": "Default Attack",
    "sourceKind": "default_attack", "supports": [], "socketedActiveCount": 1,
    "activeSkills": ["Crossbow Shot", "Basic Bolt"], "includeInFullDPS": False,
}


def test_incidental_native_attack_is_not_an_optimization_obligation():
    result = _checklist(deepcopy(_INCIDENTAL))
    assert result["skillSupportAudit"]["status"] == "not_applicable"
    assert result["mechanismDependencies"]["reasons"] == []


@pytest.mark.parametrize("change,context", [
    ({"role": "pob_main_group"}, None),
    ({"includeInFullDPS": True}, None),
    ({"supports": ["Martial Tempo I"]}, None),
    ({"socketedActiveCount": 2}, None),
    ({}, {"groupIndex": 2, "activeIndex": 2, "skillName": "Basic Bolt"}),
])
def test_adopted_default_attack_requires_current_support_audit(change, context):
    result = _checklist({**_INCIDENTAL, **change}, context)
    assert result["skillSupportAudit"]["status"] == "failed"
    assert result["skillSupportAudit"]["reasons"] == ["support_audit_missing:2"]


def test_default_attack_label_without_runtime_authority_is_not_trusted():
    result = _checklist({**_INCIDENTAL, "sourceKind": "other"})
    assert result["mechanismDependencies"]["status"] == "failed"
    assert result["mechanismDependencies"]["reasons"] == ["source_skill_supports_unverified:2"]


def test_default_attack_owner_must_match_actual_runtime_slot(engine):
    _start(engine)
    parsed = preflight._parse_skill_groups(engine.get_xml())
    group = next(g for g in parsed["groups"] if g["source"] == "Default Attack")
    group["slot"] = "Weapon 1 Swap"
    preflight._decorate_runtime_active_names(engine, parsed)
    assert group["activeSkillSelectionError"] == "runtime_skill_group_identity_mismatch"
    assert "sourceKind" not in group
