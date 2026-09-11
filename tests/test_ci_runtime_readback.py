from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from server import main
from server.compute import buildopt, equipment
from server.compute.defense_state import defense_keystones, has_chaos_inoculation
from server.compute.engine import PobEngine
from server.compute.state import build_state_hash
from server.generation import preflight
from server.judge import evaluator


FLESH = """Rarity: Unique
Flesh Crucible
Diamond
Limited to: 1
10% less maximum Life
Chaos Inoculation
Corrupted"""
OBSERVED = {
    "schemaVersion": 1,
    "source": "pob_main_output",
    "status": "observed",
    "chaosInoculation": True,
}


@pytest.mark.parametrize(
    "observation",
    [
        {**OBSERVED, "chaosInoculation": False},
        {**OBSERVED, "chaosInoculation": 1},
        {**OBSERVED, "chaosInoculation": "true"},
        {**OBSERVED, "status": "unavailable"},
        {**OBSERVED, "source": "caller"},
        {**OBSERVED, "schemaVersion": 2},
        {**OBSERVED, "schemaVersion": True},
        {},
        None,
    ],
)
def test_current_observation_overrides_allocated_ci_without_pool_or_item_guessing(observation):
    build = {
        "keystones": ["Chaos Inoculation", "Mind Over Matter"],
        "defenseMechanics": observation,
        "stats": {"Life": 1, "ChaosResist": 100},
        "gear": {"Jewel 61834": {"name": "Flesh Crucible"}},
    }
    before = deepcopy(build)
    assert not has_chaos_inoculation(build)
    assert defense_keystones(build) == ["Mind Over Matter"]
    assert build == before


def test_observed_ci_supplements_but_does_not_rewrite_tree_metadata():
    build = {"keystones": [], "defenseMechanics": OBSERVED}
    assert defense_keystones(build) == ["Chaos Inoculation"]
    assert build["keystones"] == []
    assert has_chaos_inoculation({"keystones": ["Chaos Inoculation"]})  # Old static fixtures.


def _assert_gates(engine, expected):
    snapshot = build_state_hash(engine.get_xml())
    before = preflight.inspect_generation_preflight(engine)
    judged = evaluator.evaluate_active_build(engine, "ci-runtime-regression")
    for response in (before, judged):
        gate = response["readinessGates"]["endgameResistances"]
        assert gate["chaosInoculation"] is expected, gate
        assert ("endgame_chaos_resistance_below_30" in gate["hardFailures"]) is not expected
        # CI grants no elemental exemption.
        assert "endgame_elemental_resistance_below_60" in gate["hardFailures"]
    if expected:
        assert judged["defenseModel"]["poolModel"] == "ci"
    assert build_state_hash(engine.get_xml()) == snapshot
    return judged


@pytest.mark.parametrize(
    "class_name,ascendancy", [("Mercenary", "Gemling Legionnaire"), ("Sorceress", "Stormweaver")]
)
def test_native_jewel_ci_reaches_preflight_judge_and_revokes_after_unequip(
    fireball,
    class_name,
    ascendancy,
    monkeypatch,
):
    fireball.set_class(class_name, ascendancy)
    fireball.set_level(95)
    fireball.alloc_passive(61834, path_attribute="Intelligence")
    monkeypatch.setattr(main, "get_engine", lambda: fireball)
    assert main.equip_jewel(FLESH, 61834)["ok"]
    build = fireball.get_build()
    assert "Chaos Inoculation" not in build["keystones"]
    assert build["defenseMechanics"] == OBSERVED
    assert fireball.get_defenses()["defenseMechanics"] == OBSERVED
    assert fireball.get_stats(["Life"])["stats"]["Life"] == 1
    _assert_gates(fireball, True)
    readiness = main.pinnacle_readiness()
    assert next(c for c in readiness["checks"] if c["check"] == "chaos handled")["ok"]
    assert not any("chaos 0" in c for c in main._import_caveats(fireball))
    d = fireball.get_defenses()
    d["resistances"] = {"fire": 60, "cold": 60, "lightning": 60, "chaos": 0}
    assert buildopt._resistance_target_status(build, d)[1]
    assert fireball.unequip_item("Jewel 61834")["ok"]
    assert "Chaos Inoculation" in fireball.get_xml()  # Still in the item pool, no active grant.
    assert not fireball.get_build()["defenseMechanics"]["chaosInoculation"]
    _assert_gates(fireball, False)


def test_native_tree_ci_and_one_life_without_ci_are_distinguished(fireball):
    fireball.set_level(95)
    fireball.set_config(custom_mods="100% less maximum Life")
    assert fireball.get_stats(["Life"])["stats"]["Life"] == 1
    assert not fireball.get_build()["defenseMechanics"]["chaosInoculation"]
    _assert_gates(fireball, False)
    assert fireball.alloc_passive("Chaos Inoculation", path_attribute="Intelligence")["ok"]
    assert "Chaos Inoculation" in fireball.get_build()["keystones"]
    _assert_gates(fireball, True)


def test_native_ci_disabled_socket_and_import_restore_follow_actual_snapshot(fireball):
    fireball.set_level(95)
    fireball.alloc_passive(61834, path_attribute="Intelligence")
    assert equipment.equip_jewel_verified(fireball, raw=FLESH, socket=61834)["ok"]
    original = fireball.get_xml()
    assert fireball.dealloc_passive(61834)["ok"]
    assert not fireball.get_build()["defenseMechanics"]["chaosInoculation"]
    _assert_gates(fireball, False)
    fireball.load_build_xml(original)
    _assert_gates(fireball, True)
    with PobEngine(script=Path(__file__).resolve().parents[1] / "pob/pob_headless.lua") as judge:
        judge.load_build_xml(original)
        assert judge.get_build()["defenseMechanics"] == OBSERVED
        _assert_gates(judge, True)
