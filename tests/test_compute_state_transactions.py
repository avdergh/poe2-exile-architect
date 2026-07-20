from __future__ import annotations

from server.compute import passiveopt, skillgroups
from server.compute.engine import PobEngineError
from server.compute.state import build_state_hash


def _monk_with_two_groups(engine):
    engine.new_build()
    engine.set_class("Monk", "Invoker")
    engine.set_level(80)
    engine.add_item(
        "Rarity: Rare\nTransaction Staff\nSteelpoint Quarterstaff\nItem Level: 80\n"
        "120% increased Physical Damage",
        slot="Weapon 1",
    )
    engine.paste_skill("Storm Wave")
    engine.add_skill_group("Herald of Thunder")


def test_semantic_state_hash_ignores_pob_serialization_noise():
    first = """<PathOfBuilding2><Build className="Monk" level="80">
    <PlayerStat stat="TotalDPS" value="100"/></Build>
    <Tree activeSpec="1"><Spec nodes="3,1,2" classId="10"><URL>old</URL></Spec></Tree>
    <Skills activeSkillSet="1" sortGemsByDPS="true"><SkillSet id="1">
    <Skill label="" includeInFullDPS="nil" mainActiveSkill="nil"/>
    </SkillSet></Skills></PathOfBuilding2>"""
    second = """<PathOfBuilding2><Skills sortGemsByDPS="false" activeSkillSet="1">
    <SkillSet id="1"><Skill mainActiveSkill="1" includeInFullDPS="false" label=""
    mainActiveSkillCalcs="1"/></SkillSet></Skills>
    <Tree activeSpec="1"><Spec classId="10" nodes="2,3,1"><URL>new</URL></Spec></Tree>
    <Build level="80" className="Monk"><PlayerStat value="999" stat="TotalDPS"/></Build>
    </PathOfBuilding2>"""

    assert build_state_hash(first) == build_state_hash(second)
    assert build_state_hash(first) != build_state_hash(first.replace('level="80"', 'level="79"'))


def test_skill_group_replace_remove_and_stale_selector_fail_closed(engine):
    _monk_with_two_groups(engine)
    before = skillgroups.list_skill_groups(engine)
    main_fingerprint = before["groups"][0]["fingerprint"]
    secondary = before["groups"][1]

    replaced = skillgroups.replace_skill_group(
        engine,
        group_index=2,
        expected_fingerprint=secondary["fingerprint"],
        expected_state_hash=before["stateHash"],
        skill="Combat Frenzy",
    )

    assert replaced["ok"] is True
    assert replaced["mainGroupIndex"] == 1
    assert replaced["groups"][0]["fingerprint"] == main_fingerprint
    assert replaced["groups"][1]["activeSkill"] == "Combat Frenzy"

    state_after_replace = skillgroups.list_skill_groups(engine)
    stale = skillgroups.remove_skill_group(
        engine,
        group_index=2,
        expected_fingerprint=secondary["fingerprint"],
    )

    assert stale["ok"] is False
    assert stale["errorCode"] == "skill_group_conflict"
    assert skillgroups.list_skill_groups(engine)["stateHash"] == state_after_replace["stateHash"]

    current_secondary = state_after_replace["groups"][1]
    removed = skillgroups.remove_skill_group(
        engine,
        group_index=2,
        expected_fingerprint=current_secondary["fingerprint"],
        expected_state_hash=state_after_replace["stateHash"],
    )

    assert removed["ok"] is True
    assert len(removed["groups"]) == 1
    assert engine.get_build()["mainSkill"] == "Storm Wave"


def test_skill_group_main_invariants_and_rollback(engine):
    _monk_with_two_groups(engine)
    before = skillgroups.list_skill_groups(engine)
    main = before["groups"][0]

    disabled = skillgroups.set_skill_group_state(
        engine,
        group_index=1,
        expected_fingerprint=main["fingerprint"],
        enabled=False,
        expected_state_hash=before["stateHash"],
    )
    assert disabled["ok"] is False
    assert disabled["errorCode"] == "main_skill_group_cannot_be_disabled"
    assert skillgroups.list_skill_groups(engine)["stateHash"] == before["stateHash"]

    missing_replacement = skillgroups.remove_skill_group(
        engine,
        group_index=1,
        expected_fingerprint=main["fingerprint"],
        expected_state_hash=before["stateHash"],
    )
    assert missing_replacement["ok"] is False
    assert missing_replacement["errorCode"] == "replacement_main_group_required"
    assert skillgroups.list_skill_groups(engine)["stateHash"] == before["stateHash"]

    removed = skillgroups.remove_skill_group(
        engine,
        group_index=1,
        expected_fingerprint=main["fingerprint"],
        replacement_main_group_index=2,
        expected_state_hash=before["stateHash"],
    )
    assert removed["ok"] is True
    assert removed["mainGroupIndex"] == 1
    assert removed["groups"][0]["activeSkill"] == "Herald of Thunder"
    assert engine.get_build()["mainSkill"] == "Herald of Thunder"


def test_passive_optimizer_v2_preview_is_reproducible_and_commit_is_cas(engine):
    _monk_with_two_groups(engine)
    initial_hash = build_state_hash(engine.get_xml())

    first = passiveopt.optimize_passives(
        engine,
        metric="balanced",
        points=12,
        goals={"TotalEHP": 0.5, "TotalDPS": 0.5},
        preview=True,
        expected_state_hash=initial_hash,
    )
    second = passiveopt.optimize_passives(
        engine,
        metric="balanced",
        points=12,
        goals={"TotalDPS": 0.5, "TotalEHP": 0.5},
        preview=True,
        expected_state_hash=initial_hash,
    )

    assert first["ok"] is True and second["ok"] is True
    assert build_state_hash(engine.get_xml()) == initial_hash
    assert first["optimizerVersion"] == passiveopt.OPTIMIZER_VERSION
    assert first["requestHash"] == second["requestHash"]
    assert first["resultHash"] == second["resultHash"]
    assert first["allocatedNodeIds"] == second["allocatedNodeIds"]
    assert first["outputStateHash"] == second["outputStateHash"]
    assert first["metrics"] == second["metrics"]
    assert all("pathNodeIds" in step for step in first["allocated"])

    committed = passiveopt.optimize_passives(
        engine,
        metric="balanced",
        points=12,
        goals={"TotalDPS": 0.5, "TotalEHP": 0.5},
        expected_state_hash=initial_hash,
    )
    assert committed["ok"] is True
    assert committed["committed"] is True
    assert committed["committedStateHash"] == first["outputStateHash"]
    assert build_state_hash(engine.get_xml()) == first["outputStateHash"]

    conflict = passiveopt.optimize_passives(
        engine,
        points=1,
        preview=True,
        expected_state_hash=initial_hash,
    )
    assert conflict["ok"] is False
    assert conflict["errorCode"] == "build_state_conflict"


def test_passive_optimizer_preview_falls_back_safely_when_process_cap_is_full(engine, monkeypatch):
    _monk_with_two_groups(engine)
    initial_hash = build_state_hash(engine.get_xml())

    def no_capacity(**_kwargs):
        raise PobEngineError("PoB engine process limit reached (5)")

    monkeypatch.setattr(passiveopt, "PobEngine", no_capacity)
    result = passiveopt.optimize_passives(
        engine,
        metric="TotalDPS",
        points=3,
        preview=True,
        expected_state_hash=initial_hash,
    )

    assert result["ok"] is True
    assert result["executionMode"] == "active_snapshot_fallback"
    assert result["committed"] is False
    assert build_state_hash(engine.get_xml()) == initial_hash
