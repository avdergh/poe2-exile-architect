"""Exercise exact punctuation-bearing gem identities through actual PoB mutation paths."""

from collections import Counter

import pytest

from server.compute import skillgroups
from server.compute.state import build_state_hash


@pytest.mark.parametrize("operation", ["set", "add", "replace"])
@pytest.mark.parametrize("class_name", ["Ranger", "Witch"])
def test_hyphenated_active_gem_survives_all_group_mutations(engine, operation, class_name):
    engine.new_build()
    engine.set_class(class_name)
    engine.set_level(99)
    assert skillgroups.set_main_skill(engine, "Fireball").get("ok") is not False
    text = "Ice-Tipped Arrows\nMagnified Area II\nElemental Armament II\nShort Fuse I"
    if operation == "set":
        result = skillgroups.set_main_skill(engine, text)
    elif operation == "add":
        result = skillgroups.add_skill_group(engine, text)
    else:
        listed = skillgroups.list_skill_groups(engine)
        group = listed["groups"][0]
        result = skillgroups.replace_skill_group(
            engine, group_index=group["index"], expected_fingerprint=group["fingerprint"],
            expected_state_hash=listed["stateHash"], skill=text,
        )
    assert result.get("ok") is not False, result
    groups = skillgroups.list_skill_groups(engine)["groups"]
    target = next(g for g in groups if any(x["name"] == "Ice-Tipped Arrows" for x in g["gems"]))
    assert Counter(g["name"] for g in target["gems"]) == Counter(text.splitlines())
    root = next(g for g in target["gems"] if g["name"] == "Ice-Tipped Arrows")
    assert root["effectId"] == "IceTippedArrowsPlayer"
    before = engine.get_xml()
    rejected = skillgroups.replace_skill_group(
        engine, group_index=target["index"], expected_fingerprint=target["fingerprint"],
        expected_state_hash=build_state_hash(before), skill=text + "\nDefinitely-Unknown Gem",
    )
    assert rejected["errorCode"] == "unknown_skill_gem"
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)


def test_hyphenated_support_is_not_dropped_and_overlevel_still_rolls_back(engine):
    engine.new_build()
    engine.set_class("Witch")
    engine.set_level(99)
    result = skillgroups.set_main_skill(engine, "Fireball\nUul-Netol's Embrace")
    assert result.get("ok") is not False, result
    group = skillgroups.list_skill_groups(engine)["groups"][0]
    assert [g["name"] for g in group["gems"]] == ["Fireball", "Uul-Netol's Embrace"]
    engine.set_level(10)
    before = engine.get_xml()
    result = skillgroups.add_skill_group(engine, "Ice-Tipped Arrows 20/0 1")
    assert result["errorCode"] == "active_skill_gem_level_requirement_unmet"
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)
