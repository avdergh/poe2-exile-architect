from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from server.compute import supportopt
from server.compute.engine import PobEngine
from server.compute.state import build_state_hash


def configured_group(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(95)
    engine.paste_skill("Spark 20/13 3\nComet 20/10 2")
    engine.add_skill_group("Arc 20/0 1")
    root = ET.fromstring(engine.get_xml())
    skill = root.find("./Skills/SkillSet/Skill")
    skill.set("mainActiveSkill", "2")
    skill.set("mainActiveSkillCalcs", "2")
    gem = skill.find("Gem")
    gem.set("enableGlobal1", "false")
    gem.set("skillPart", "1")
    gem.set("skillPartCalcs", "1")
    engine.load_build_xml(ET.tostring(root, encoding="unicode"))
    engine.call("set_skill_group_state", index=1, activeSkillIndex=2, makeMain=True)
    snapshot = engine.get_xml()
    group = engine.call("list_skill_groups")["groups"][0]
    identity = engine.call("resolve_support_gem_identity", runtimeName="Controlled Destruction")
    assert identity["status"] == "resolved"
    return snapshot, group, {identity["name"]: identity}


def test_group_local_probe_matches_full_pob_import_and_preserves_unrelated_state(engine):
    snapshot, group, identities = configured_group(engine)
    supports = list(identities)
    group_xml = supportopt._regular_probe_xml(
        snapshot, 1, group, supports, identities, group_only=True
    )
    result = engine.probe_regular_skill_group(
        group_index=1,
        group_xml=group_xml,
        active_skill_index=2,
        expected_skill_name="Comet",
        keys=["TotalDPS", "ManaCost"],
        objective_keys=["TotalDPS"],
    )
    assert result["ok"] is True, result
    assert result["state"]["groups"][0]["activeSkill"] == "Comet"
    assert [gem["name"] for gem in result["state"]["groups"][0]["gems"]] == [
        "Spark",
        "Comet",
        "Controlled Destruction",
    ]
    fast_xml = engine.get_xml()
    original_gems = ET.fromstring(snapshot).findall("./Skills/SkillSet/Skill/Gem")[:2]
    fast_gems = ET.fromstring(fast_xml).findall("./Skills/SkillSet/Skill/Gem")[:2]
    for before, after in zip(original_gems, fast_gems, strict=True):
        assert before.attrib == after.attrib
    reference = supportopt._regular_probe_xml(snapshot, 1, group, supports, identities)
    engine.load_build_xml(reference)
    engine.call("set_skill_group_state", index=1, activeSkillIndex=2, makeMain=True)
    assert result["stats"] == pytest.approx(engine.get_stats(["TotalDPS", "ManaCost"])["stats"])
    assert build_state_hash(fast_xml) == build_state_hash(engine.get_xml())


def test_wrong_selected_effect_rolls_back_entire_preprobe_state(engine):
    snapshot, group, identities = configured_group(engine)
    result = engine.probe_regular_skill_group(
        group_index=1,
        group_xml=supportopt._regular_probe_xml(
            snapshot, 1, group, list(identities), identities, group_only=True
        ),
        active_skill_index=2,
        expected_skill_name="Spark",
        expected_effect_id="CometPlayer",
        keys=["TotalDPS"],
        objective_keys=["TotalDPS"],
    )
    assert result["ok"] is False
    assert result["errorCode"] == "support_selected_effect_changed"
    assert result["rolledBack"] is True
    assert build_state_hash(engine.get_xml()) == build_state_hash(snapshot)


def test_invalid_group_probe_does_not_mutate_engine(engine):
    snapshot, group, identities = configured_group(engine)
    group_xml = ET.fromstring(
        supportopt._regular_probe_xml(
            snapshot, 1, group, list(identities), identities, group_only=True
        )
    )
    group_xml.set("source", "Tree:1")
    result = engine.probe_regular_skill_group(
        group_index=1,
        group_xml=ET.tostring(group_xml, encoding="unicode"),
        active_skill_index=2,
        expected_skill_name="Comet",
        keys=["TotalDPS"],
        objective_keys=["TotalDPS"],
    )
    assert result["ok"] is False
    assert result["errorCode"] == "support_probe_group_xml_invalid"
    assert build_state_hash(engine.get_xml()) == build_state_hash(snapshot)


def test_optimizer_does_not_reload_character_per_regular_candidate(engine, monkeypatch):
    snapshot, _, _ = configured_group(engine)
    monkeypatch.setattr(
        supportopt, "_screen_set", lambda *_: ["Controlled Destruction", "Zenith II"]
    )
    original_load = engine.load_build_xml
    reloads = []

    def load(xml, **kwargs):
        reloads.append(kwargs.get("name"))
        return original_load(xml, **kwargs)

    monkeypatch.setattr(engine, "load_build_xml", load)
    result = supportopt.optimize_supports(engine)
    assert result["ok"] is True, result
    assert result["measurement"]["probeMode"] == "group_local"
    assert result["measurement"]["screenedCandidates"] == 2
    assert len(reloads) <= 3
    assert build_state_hash(engine.get_xml()) == build_state_hash(snapshot)


@pytest.mark.parametrize("support_name", ["Crackling Barrier", "Morrigan's Insight"])
def test_generated_groups_rebuild_from_original_and_do_not_leak_to_next_probe(engine, support_name):
    snapshot, group, _ = configured_group(engine)
    reference = PobEngine(script=engine.script)
    try:
        for index, name in enumerate([support_name, "Zenith II", "Controlled Destruction"]):
            identity = engine.call("resolve_support_gem_identity", runtimeName=name)
            identities = {name: identity}
            candidate_xml = supportopt._regular_probe_xml(snapshot, 1, group, [name], identities)
            probe = engine.probe_regular_skill_group(
                group_index=1,
                group_xml=supportopt._regular_probe_xml(
                    snapshot, 1, group, [name], identities, group_only=True
                ),
                active_skill_index=2,
                expected_skill_name="Comet",
                expected_effect_id="CometPlayer",
                keys=["TotalDPS", "ManaCost"],
                objective_keys=["TotalDPS"],
            )
            assert probe["ok"] is True, probe
            assert probe.get("requiresFullRebuild", False) is (index < 2)
            if probe.get("requiresFullRebuild"):
                assert "stats" not in probe
                engine.load_build_xml(candidate_xml)
                target = supportopt._unique_output_index(
                    engine.call("list_skill_groups")["groups"][0], "Comet", "CometPlayer"
                )
                engine.call(
                    "set_skill_group_state", index=1, activeSkillIndex=target, makeMain=True
                )
            actual_xml = engine.get_xml()
            actual_stats = engine.get_stats(["TotalDPS", "ManaCost"])["stats"]
            actual_groups = engine.call("list_skill_groups")["groups"]
            assert [row["rootSkillId"] for row in actual_groups if not row.get("source")] == [
                "SparkPlayer",
                "ArcPlayer",
            ]
            assert [row.get("source") for row in actual_groups if row.get("source")] == (
                ["Thorns"] if index == 0 else []
            )
            reference.load_build_xml(candidate_xml)
            target = supportopt._unique_output_index(
                reference.call("list_skill_groups")["groups"][0], "Comet", "CometPlayer"
            )
            reference.call("set_skill_group_state", index=1, activeSkillIndex=target, makeMain=True)
            assert actual_stats == pytest.approx(
                reference.get_stats(["TotalDPS", "ManaCost"])["stats"]
            )
            assert build_state_hash(actual_xml) == build_state_hash(reference.get_xml())
    finally:
        reference.close()


def test_generated_effect_index_shift_preserves_output_and_rebases_carried_audit(
    engine, monkeypatch
):
    snapshot, group, _ = configured_group(engine)
    current_supports = [
        "Morrigan's Insight",
        "Controlled Destruction",
        "Rapid Casting II",
        "Concentrated Area",
        "Spell Echo",
    ]
    identities = {
        name: engine.call("resolve_support_gem_identity", runtimeName=name)
        for name in current_supports
    }
    root = ET.fromstring(
        supportopt._regular_probe_xml(snapshot, 1, group, current_supports, identities)
    )
    skill = root.find("./Skills/SkillSet/Skill")
    morrigan = next(
        gem for gem in skill.findall("Gem") if gem.get("nameSpec") == "Morrigan's Insight"
    )
    skill.remove(morrigan)
    skill.insert(1, morrigan)
    skill.set("mainActiveSkill", "3")
    skill.set("mainActiveSkillCalcs", "3")
    engine.load_build_xml(ET.tostring(root, encoding="unicode"))
    engine.set_config(
        custom_mods="+1000 to Strength\n+1000 to Dexterity\n+1000 to Intelligence\n+1000 to Spirit"
    )
    engine.call("set_skill_group_state", index=1, activeSkillIndex=3, makeMain=True)
    snapshot = engine.get_xml()
    group = engine.call("list_skill_groups")["groups"][0]
    assert [row["name"] for row in group["activeSkills"]] == ["Spark", "Nature's Exchange", "Comet"]
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Zenith II"])
    result = supportopt.optimize_supports(engine, metric="ManaCost")
    assert result["ok"] is True, result
    assert result["supports"] == ["Zenith II"], result
    comparison = result["measurement"]["combinationComparison"]
    assert comparison["baselineActiveSkillIndex"] == 3
    assert comparison["candidateActiveSkillIndex"] == 2
    assert comparison["selectedEffectId"] == "CometPlayer"
    assert result["supportAudit"]["activeSkillIndex"] == 3
    assert result["measurement"]["topologyRebuilds"] > 0
    identity = engine.call("resolve_support_gem_identity", runtimeName="Zenith II")
    engine.load_build_xml(
        supportopt._regular_probe_xml(snapshot, 1, group, ["Zenith II"], {"Zenith II": identity})
    )
    engine.call("set_skill_group_state", index=1, activeSkillIndex=2, makeMain=True)
    assert engine.get_stats(["ManaCost"])["stats"]["ManaCost"] == pytest.approx(
        comparison["candidateMetrics"]["ManaCost"]
    )
    carried = supportopt.carry_support_audit_to_configured_state(
        engine=engine,
        before_state_hash=result["stateHash"],
        after_state_hash=build_state_hash(engine.get_xml()),
        group_index=1,
        applied_supports=["Zenith II"],
    )
    assert carried is not None
    assert carried["activeSkillIndex"] == 2
    assert carried["measurement"]["combinationComparison"]["baselineActiveSkillIndex"] == 2


def test_duplicate_exact_output_is_ambiguous_and_rolls_back(engine):
    snapshot, group, _ = configured_group(engine)
    root = ET.fromstring(snapshot)
    target = root.find("./Skills/SkillSet/Skill")
    target.append(ET.fromstring(ET.tostring(target.findall("Gem")[1], encoding="unicode")))
    engine.load_build_xml(ET.tostring(root, encoding="unicode"))
    snapshot = engine.get_xml()
    group = engine.call("list_skill_groups")["groups"][0]
    probe = engine.probe_regular_skill_group(
        group_index=1,
        group_xml=supportopt._regular_probe_xml(snapshot, 1, group, [], group_only=True),
        active_skill_index=2,
        expected_skill_name="Comet",
        expected_effect_id="CometPlayer",
        keys=["TotalDPS"],
        objective_keys=["TotalDPS"],
    )
    assert probe["ok"] is False
    assert probe["errorCode"] == "support_selected_effect_ambiguous"
    assert probe["rolledBack"] is True
    assert build_state_hash(engine.get_xml()) == build_state_hash(snapshot)


def test_support_splice_preserves_literal_multiline_attributes_and_other_material():
    active = '<Gem nameSpec="Spark" level="20" quality="13" count="3"/>'
    retained = '<Gem nameSpec="Pair A" level="1" quality="7"><StatSetIndex grantedEffect="SupportPlayer" index="1"/></Gem>'
    config = '<Config><Input name="customMods" string="+1000 to Strength\n+1000 to Intelligence"/></Config>'
    items = (
        '<Items><Item id="1">Rarity: Rare\nSynthetic\nItem text &amp; punctuation</Item></Items>'
    )
    snapshot = (
        '<PathOfBuilding2><Skills><Skill label="甲\n乙">'
        + active
        + retained
        + "</Skill></Skills>"
        + config
        + items
        + "</PathOfBuilding2>"
    )
    group = {"gems": [{"name": "Spark", "isSupport": False}, {"name": "Pair A", "isSupport": True}]}
    candidate = supportopt._regular_probe_xml(snapshot, 1, group, ["Pair A", "Solo C"])
    assert config in candidate and items in candidate
    assert active in candidate and retained in candidate
    assert 'label="甲\n乙"' in candidate
    assert [
        gem.get("nameSpec") for gem in ET.fromstring(candidate).findall("./Skills/Skill/Gem")
    ] == ["Spark", "Pair A", "Solo C"]
