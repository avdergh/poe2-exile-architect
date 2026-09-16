from __future__ import annotations

import pytest

from server.compute import mutation_batch, skillgroups
from server.compute.state import build_state_hash


MIRAGE_LOADOUT = (
    "Mirage Deadeye\nIce Shot\nElemental Armament II\n"
    "Rapid Attacks II\nDeliberation\nCooldown Recovery II"
)


def _source(engine, source):
    listed = skillgroups.list_skill_groups(engine)
    matches = [group for group in listed["groups"] if group.get("source") == source]
    assert len(matches) == 1
    return listed, matches[0]


def _deadeye(engine):
    engine.new_build()
    engine.set_class("Ranger", "Deadeye")
    engine.set_level(98)
    engine.alloc_passive(5817)
    engine.add_item("Rarity: Normal\nDualstring Bow", slot="Weapon 1")
    assert skillgroups.set_main_skill(engine, "Ice Shot").get("ok") is not False


def _add_mirage(engine):
    _deadeye(engine)
    before = skillgroups.list_skill_groups(engine)
    result = skillgroups.add_skill_group(engine, MIRAGE_LOADOUT)
    assert result.get("ok") is not False, result
    listed, group = _source(engine, "Tree:5817")
    assert len(listed["groups"]) == len(before["groups"])
    assert result["groupIndex"] == group["index"]
    assert [gem["name"] for gem in group["gems"]] == MIRAGE_LOADOUT.splitlines()
    assert not group["mutable"]
    assert engine.get_build()["mainSkill"] == "Ice Shot"
    return listed, group


def test_add_adopts_real_tree_source_and_preserves_main(engine):
    listed, group = _add_mirage(engine)
    assert listed["mainGroupIndex"] != group["index"]
    engine.load_build_xml(engine.get_xml(), name="source-loadout-roundtrip")
    engine.get_stats()
    after, restored = _source(engine, "Tree:5817")
    assert len(after["groups"]) == len(listed["groups"])
    assert restored["gems"] == group["gems"]
    assert engine.get_build()["mainSkill"] == "Ice Shot"


def test_batch_records_source_adoption_and_rolls_back_later_failure(engine):
    _deadeye(engine)
    before = build_state_hash(engine.get_xml())
    result = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="skill_loadout",
        expected_state_hash=before,
        operations=[
            mutation_batch.BuildMutationOperation(operation="add_skill_group", skill=MIRAGE_LOADOUT)
        ],
    )
    assert result["ok"], result
    assert result["postconditions"]["configuredGroupCount"] == 1
    assert result["postconditions"]["addedGroupCount"] == 0
    before = build_state_hash(engine.get_xml())
    failed = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="skill_loadout",
        expected_state_hash=before,
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="add_skill_group", skill=MIRAGE_LOADOUT
            ),
            mutation_batch.BuildMutationOperation(
                operation="add_skill_group", skill="Not A Real Skill"
            ),
        ],
    )
    assert not failed["ok"] and failed["rolledBack"]
    assert build_state_hash(engine.get_xml()) == before


def test_source_support_edit_keeps_payload_and_enforces_shared_capacity(engine):
    listed, group = _add_mirage(engine)
    selected = skillgroups.set_skill_group_state(
        engine,
        group_index=group["index"],
        expected_fingerprint=group["fingerprint"],
        expected_state_hash=listed["stateHash"],
        active_skill_index=next(
            a["index"] for a in group["activeSkills"] if a["name"] == "Ice Shot"
        ),
    )
    assert selected["ok"], selected
    listed, group = _source(engine, "Tree:5817")
    payload = next(gem for gem in group["gems"] if gem["name"] == "Ice Shot")
    supports = [
        "Elemental Armament II",
        "Rapid Attacks II",
        "Cold Attunement",
        "Cooldown Recovery II",
    ]
    configured = skillgroups.configure_source_skill_supports(
        engine,
        source_group_index=group["index"],
        supports=supports,
        expected_fingerprint=group["fingerprint"],
        expected_state_hash=listed["stateHash"],
    )
    assert configured["ok"], configured
    assert configured["supportCapacity"] == 4
    assert configured["group"]["gems"][1] == payload
    assert all(row["activeSkills"] for row in configured["supportApplication"])
    assert any("Ice Shot" in row["activeSkills"] for row in configured["supportApplication"])
    cooldown = next(
        row for row in configured["supportApplication"] if row["name"] == "Cooldown Recovery II"
    )
    assert "MirageDeadeyeSpawnPlayer" in cooldown["rootedActiveEffectIds"], cooldown

    listed, group = _source(engine, "Tree:5817")
    before = build_state_hash(engine.get_xml())
    failed = skillgroups.configure_source_skill_supports(
        engine,
        source_group_index=group["index"],
        supports=[*supports, "Fork"],
        expected_fingerprint=group["fingerprint"],
        expected_state_hash=listed["stateHash"],
    )
    assert failed["errorCode"] == "source_support_capacity_exceeded"
    assert build_state_hash(engine.get_xml()) == before

    failed = skillgroups.configure_source_skill_supports(
        engine,
        source_group_index=group["index"],
        supports=["Rapid Casting II"],
        expected_fingerprint=group["fingerprint"],
        expected_state_hash=listed["stateHash"],
    )
    assert failed["errorCode"] == "source_support_not_applied"
    assert build_state_hash(engine.get_xml()) == before
    engine.load_build_xml(engine.get_xml(), name="configured-payload-roundtrip")
    assert _source(engine, "Tree:5817")[1]["gems"][1] == payload


def test_source_merge_cannot_smuggle_previous_gems_into_new_request(engine):
    _add_mirage(engine)
    before = build_state_hash(engine.get_xml())
    result = skillgroups.add_skill_group(engine, "Mirage Deadeye\nIce Shot\nFork")
    assert result["errorCode"] == "skill_group_incomplete"
    assert build_state_hash(engine.get_xml()) == before
    assert _source(engine, "Tree:5817")[1]["gems"][1]["name"] == "Ice Shot"


def test_repeated_source_loadout_keeps_selected_payload(engine):
    listed, group = _add_mirage(engine)
    active = next(a["index"] for a in group["activeSkills"] if a["name"] == "Ice Shot")
    assert skillgroups.set_skill_group_state(
        engine,
        group_index=group["index"],
        expected_fingerprint=group["fingerprint"],
        active_skill_index=active,
        make_main=True,
    )["ok"]
    result = skillgroups.add_skill_group(engine, MIRAGE_LOADOUT)
    assert result.get("ok") is not False, result
    _, group = _source(engine, "Tree:5817")
    assert group["isMain"]
    assert group["mainActiveSkill"] == active
    assert group["mainActiveSkillCalcs"] == active
    assert [g["name"] for g in group["gems"]] == MIRAGE_LOADOUT.splitlines()


def test_secondary_add_keeps_nonfirst_active_effect(engine):
    _deadeye(engine)
    result = skillgroups.add_skill_group(engine, "Mirage Archer\nIce Shot")
    assert result.get("ok") is not False
    listed = skillgroups.list_skill_groups(engine)
    target = next(g for g in listed["groups"] if g["index"] == result["groupIndex"])
    active = next(a["index"] for a in target["activeSkills"] if a["name"] == "Ice Shot")
    assert active > 1
    assert skillgroups.set_skill_group_state(
        engine,
        group_index=target["index"],
        expected_fingerprint=target["fingerprint"],
        active_skill_index=active,
        make_main=True,
    )["ok"]
    assert skillgroups.add_skill_group(engine, "Ghost Dance").get("ok") is not False
    main = next(g for g in skillgroups.list_skill_groups(engine)["groups"] if g["isMain"])
    assert main["rootSkillId"] == "MetaMirageArcherPlayer"
    assert main["mainActiveSkill"] == active
    assert main["mainActiveSkillCalcs"] == active


@pytest.mark.parametrize("source_kind", ["tree", "item"])
def test_adoption_is_not_specific_to_deadeye(engine, source_kind):
    engine.new_build()
    engine.set_level(98)
    if source_kind == "tree":
        engine.set_class("Sorceress", "Stormweaver")
        engine.alloc_passive(12882)
        support = "Elemental Focus"
    else:
        engine.set_class("Witch", "Infernalist")
        assert engine.add_item(
            "Rarity: Unique\nThe Coming Calamity\nHeroic Armour\n"
            "Grants Skill: Level 20 Herald of Ice",
            slot="Body Armour",
        )["ok"]
        support = "Elemental Focus"
    skillgroups.set_main_skill(engine, "Spark")
    before = skillgroups.list_skill_groups(engine)
    source = next(g for g in before["groups"] if g.get("sourceKind") == source_kind)
    result = skillgroups.add_skill_group(engine, source["gems"][0]["name"] + "\n" + support)
    assert result.get("ok") is not False, result
    after, adopted = _source(engine, source["source"])
    if source_kind == "tree":
        assert result["groupIndex"] == adopted["index"]
        assert len(after["groups"]) == len(before["groups"])
    else:
        # A normal Herald gem is independently legal; PoB must not silently convert
        # it into a different item grant just because the display names coincide.
        assert result["groupIndex"] != adopted["index"]
        assert len(after["groups"]) == len(before["groups"]) + 1
        assert adopted["gems"] == source["gems"]
    assert adopted["sourceKind"] == source_kind
    assert engine.get_build()["mainSkill"] == "Spark"
