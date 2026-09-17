"""Provider restrictions are exact reviewed facts, not inferred from an uncarvable gem."""

import pytest

from server.compute import skillgroups
from server.judge import hard_legality
from server.knowledge import db, gem_availability

DISCIPLINE = "Metadata/Items/Gems/SkillGemDiscipline"


def test_exact_provider_identity_patch_and_unknown_are_separate():
    known = gem_availability.inspect_acquisition(["gem:" + DISCIPLINE])
    assert known["ordinaryGemAllowed"] is False
    assert known["allowedSourceKinds"] == ["item"]
    assert db.get_gem(DISCIPLINE)["acquisition"] == known
    assert gem_availability.inspect_ids([DISCIPLINE])["status"] == "not_flagged_unavailable"
    for ids, patch in [(["Discipline"], "0.5.5"), ([DISCIPLINE + "Two"], "0.5.5"),
                       ([DISCIPLINE], "0.6.0"), ([DISCIPLINE], "0.4.0"),
                       ([DISCIPLINE], "0.5.5a"), ([DISCIPLINE], "0.5.5a1")]:
        assert gem_availability.inspect_acquisition(ids, target_patch=patch)["status"] == "unknown"
    lineage = db.get_gem("Eonyr's Thunder")
    assert lineage["crafting_level"] == 0
    assert lineage["acquisition"]["ordinaryGemAllowed"] is None
    assert gem_availability.validate_corpus_bindings(db._conn())["checkedSourceBindings"] == 1


@pytest.mark.parametrize("operation", ["set", "add", "replace"])
def test_provider_only_gem_is_rejected_before_engine_mutation(operation):
    class NoMutation:
        def call(self, *args, **kwargs):
            raise AssertionError("source rejection must not query or modify PoB")

    engine = NoMutation()
    if operation == "set":
        result = skillgroups.set_main_skill(engine, "Discipline 20/20")
    elif operation == "add":
        result = skillgroups.add_skill_group(engine, "Discipline 20/20")
    else:
        result = skillgroups.replace_skill_group(
            engine, group_index=1, expected_fingerprint="unused", skill="Discipline 20/20"
        )
    assert result["errorCode"] == "skill_requires_provider"
    assert result["restrictedSkills"][0]["componentKey"] == "gem:" + DISCIPLINE


@pytest.mark.parametrize(
    "provenance,invalid",
    [({"sourceKind": "ordinary"}, 1), ({"source": ""}, 1),
     ({"sourceKind": "item", "source": "Item:1:Discipline"}, 0),
     ({"source": "Item:1:Discipline"}, 0), ({}, 0)],
)
def test_hard_check_does_not_confuse_missing_provenance_with_ordinary(provenance, invalid):
    build = {"gemAvailabilitySubjects": [
        {"groupIndex": 1, "gemId": DISCIPLINE, "name": "Discipline", **provenance}
    ]}
    assert hard_legality.check_gem_availability(build)["invalidSourceCount"] == invalid


def test_native_bypass_is_visible_to_hard_check_and_item_source_is_allowed(engine):
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(98)
    engine.paste_skill("Discipline 20/20")
    assert hard_legality.check_gem_availability(engine.get_build())["invalidSourceCount"] == 1
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(98)
    engine.add_item(
        "Rarity: Normal\nStoic Sceptre\nItem Level: 84\n"
        "Grants Skill: Level 19 Discipline", slot="Weapon 1"
    )
    assert hard_legality.check_gem_availability(engine.get_build())["invalidSourceCount"] == 0
