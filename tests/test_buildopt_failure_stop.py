"""Legacy 编排的失败停机回归；全程 mock，禁止真实 PoB/优化器进程。"""

from __future__ import annotations

import json
import threading

import pytest

from server.compute import buildopt


RAW = "<PathOfBuilding><Notes>private fixture material</Notes></PathOfBuilding>"


class Engine:
    script = "mock-only"

    def __init__(self):
        self.calls = []
        self.closed = False

    def get_build(self):
        self.calls.append("get_build")
        return {"mainSkill": "Fixture", "level": 90, "gear": {"Weapon 1": {"base": "fixture"}}}

    def get_xml(self):
        self.calls.append("get_xml")
        return RAW

    def load_build_xml(self, _xml):
        self.calls.append("load_build_xml")

    def optimize_passives(self, **_kwargs):
        self.calls.append("optimize_passives")
        return {}

    def set_config(self, **_kwargs):
        self.calls.append("set_config")

    def add_item(self, _item, **_kwargs):
        self.calls.append("add_item")
        return {"ok": True}

    def paste_skill(self, _text):
        self.calls.append("paste_skill")

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def no_real_engines(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("this regression must never start a real PoB process")

    monkeypatch.setattr(buildopt, "PobEngine", forbidden)


@pytest.fixture
def orchestration(monkeypatch):
    engine = Engine()
    monkeypatch.setattr(buildopt, "_delivery_tags", lambda _engine: ["spell"])
    monkeypatch.setattr(buildopt, "_damage_types", lambda _engine: ["cold"])
    monkeypatch.setattr(buildopt, "_attr_bias", lambda _engine: "int")
    monkeypatch.setattr(buildopt, "_near_jewel_sockets", lambda *_args: [])
    monkeypatch.setattr(buildopt, "_require_tree_nodes", lambda *_args: [])
    monkeypatch.setattr(
        buildopt.itemopt, "plan_gear", lambda *_args, **_kwargs: {"ok": True, "plan": []}
    )
    monkeypatch.setattr(
        buildopt, "_fill_jewels", lambda *_args, **_kwargs: engine.calls.append("fill_jewels") or 0
    )
    monkeypatch.setattr(
        buildopt, "_apply_supports", lambda *_args, **_kwargs: engine.calls.append("apply_supports")
    )
    monkeypatch.setattr(
        buildopt, "_unique_pass", lambda *_args, **_kwargs: engine.calls.append("unique_pass") or []
    )
    monkeypatch.setattr(
        buildopt, "_craft_gear", lambda *_args, **_kwargs: engine.calls.append("craft_gear") or []
    )
    monkeypatch.setattr(
        buildopt.refbuilds, "benchmark", lambda *_args: engine.calls.append("benchmark") or {}
    )
    monkeypatch.setattr(
        buildopt,
        "_result",
        lambda *_args: {
            "score": 1,
            "constraintsMet": True,
            "TotalDPS": 1,
            "FullDPS": 1,
            "TotalEHP": 1,
            "resistanceTargetMet": True,
        },
    )
    return engine


def _options():
    return {
        "levers": ["critical strike"],
        "passes": 2,
        "max_jewel_sockets": 1,
        "min_ehp": None,
        "try_uniques": True,
        "crafting": True,
        "archetypes": [{"skill": "must not be attempted"}],
    }


@pytest.mark.parametrize(
    "failure",
    [
        {
            "ok": False,
            "errorCode": "item_search_restore_failed",
            "recoveryRequired": True,
            "rolledBack": False,
        },
        {"ok": False, "errorCode": "item_probe_failed", "rolledBack": False},
        {
            "ok": False,
            "errorCode": "fatal_probe_failure",
            "recoverable": False,
            "rolledBack": True,
            "recoveryRequired": False,
        },
        {
            "ok": True,
            "errorCode": "inconsistent_step_result",
            "item": RAW,
            "recoveryRequired": True,
        },
    ],
)
def test_weapon_failure_stops_all_later_work_and_reaches_public_result(
    monkeypatch, orchestration, failure
):
    attempts = []
    monkeypatch.setattr(
        buildopt.itemopt, "optimize_item", lambda *_args, **_kwargs: attempts.append(1) or failure
    )
    result = buildopt.optimize_build(orchestration, **_options())
    assert result["ok"] is False and result["stopped"] is True
    assert result["errorCode"] == failure["errorCode"]
    assert result["firstFailure"]["errorCode"] == failure["errorCode"]
    assert result["failedStage"] == "craft_weapon"
    assert result["rolledBack"] == failure.get("rolledBack")
    assert len(attempts) == 1
    assert orchestration.calls.count("load_build_xml") == 1
    assert not set(orchestration.calls) & {
        "fill_jewels",
        "apply_supports",
        "unique_pass",
        "craft_gear",
        "benchmark",
        "add_item",
    }
    assert "xml" not in result and "private fixture" not in json.dumps(result)


def test_nested_first_failure_and_recovery_diagnostics_survive_without_raw_text(
    monkeypatch, orchestration
):
    failure = {
        "ok": False,
        "errorCode": "item_search_restore_failed",
        "recoveryRequired": True,
        "rolledBack": False,
        "firstFailure": {
            "stage": "search",
            "errorCode": "item_measurement_incomplete",
            "errorType": "PobEngineError",
            "error": RAW,
        },
        "recovery": {
            "status": "failed",
            "restoreAttempted": True,
            "snapshotVerified": False,
            "expectedStateHash": "sha256:" + "a" * 64,
            "actualStateHash": None,
            "initialStateReadFailure": {
                "stage": "state_inspection",
                "errorCode": "engine_exited",
                "errorType": "PobEngineError",
            },
            "errors": [
                {
                    "stage": "snapshot_restore",
                    "errorCode": "engine_exited",
                    "errorType": "PobEngineError",
                    "xml": RAW,
                }
            ],
        },
        "failureChain": [
            {"stage": "search", "errorCode": "item_measurement_incomplete", "message": RAW}
        ],
        "failureChainTruncated": False,
        "rejectedCandidate": RAW,
    }
    monkeypatch.setattr(buildopt.itemopt, "optimize_item", lambda *_args, **_kwargs: failure)
    result = buildopt.optimize_build(orchestration, **_options())
    assert result["firstFailure"] == {
        "stage": "search",
        "errorCode": "item_measurement_incomplete",
        "errorType": "PobEngineError",
    }
    assert result["recovery"]["errors"][0]["stage"] == "snapshot_restore"
    assert result["recovery"]["expectedStateHash"] == "sha256:" + "a" * 64
    assert result["failureChain"] == [
        {"stage": "search", "errorCode": "item_measurement_incomplete"}
    ]
    assert result["failureChainTruncated"] is False
    assert "private fixture" not in json.dumps(result)


@pytest.mark.parametrize(
    "outcome",
    [
        {"ok": False, "error": "No base for this slot."},
        {"ok": False, "errorCode": "no_gain", "rolledBack": True, "recoveryRequired": False},
        {
            "ok": False,
            "errorCode": "no_gain",
            "recoverable": False,
            "rolledBack": True,
            "recoveryRequired": False,
        },
        {
            "ok": False,
            "errorCode": "generated_item_legality_check_failed",
            "rolledBack": True,
            "recoveryRequired": False,
        },
        {"ok": True},
    ],
)
def test_safe_optional_refinement_outcomes_keep_existing_behavior(
    monkeypatch, orchestration, outcome
):
    monkeypatch.setattr(buildopt.itemopt, "optimize_item", lambda *_args, **_kwargs: outcome)
    result = buildopt.optimize_build(orchestration, levers=[], passes=1, min_ehp=None)
    assert result["ok"] is True
    assert "fill_jewels" in orchestration.calls and "apply_supports" in orchestration.calls
    assert "benchmark" in orchestration.calls


def test_weapon_exception_is_safe_and_no_false_rollback_is_claimed(monkeypatch, orchestration):
    def fail(*_args, **_kwargs):
        raise buildopt.PobEngineError(RAW)

    monkeypatch.setattr(buildopt.itemopt, "optimize_item", fail)
    result = buildopt.optimize_build(orchestration, **_options())
    assert result["errorCode"] == "weapon_optimization_failed"
    assert result["firstFailure"]["errorKind"] == "PobEngineError"
    assert result["rolledBack"] is None and result["recoveryRequired"] is True
    assert "private fixture" not in json.dumps(result)


def test_shared_recovery_flag_prevents_work_before_any_engine_read(orchestration):
    orchestration._poe2_mutation_batch_recovery_required = True
    result = buildopt.optimize_build(orchestration, **_options())
    assert result["errorCode"] == "build_state_recovery_required"
    assert orchestration.calls == []


def test_unavailable_input_snapshot_stops_without_inventing_a_rollback(monkeypatch, orchestration):
    monkeypatch.setattr(
        buildopt.itemopt,
        "optimize_item",
        lambda *_args, **_kwargs: {
            "ok": False,
            "errorCode": "item_search_snapshot_failed",
        },
    )
    result = buildopt.optimize_build(orchestration, **_options())
    assert result["ok"] is False and result["stopped"] is True
    assert result["safeToContinue"] is False and result["stateStatus"] == "unconfirmed"
    assert result["rolledBack"] is None and result["recoveryRequired"] is None
    assert result["firstFailure"]["errorCode"] == "item_search_snapshot_failed"
    assert "fill_jewels" not in orchestration.calls


def test_equipping_selected_weapon_failure_does_not_reach_jewels(monkeypatch, orchestration):
    monkeypatch.setattr(
        buildopt.itemopt, "optimize_item", lambda *_args, **_kwargs: {"ok": True, "item": RAW}
    )
    monkeypatch.setattr(
        orchestration,
        "add_item",
        lambda *_args, **_kwargs: {
            "ok": False,
            "errorCode": "item_write_failed",
            "recoveryRequired": True,
        },
    )
    result = buildopt.optimize_build(orchestration, **_options())
    assert result["failedStage"] == "equip_weapon" and result["errorCode"] == "item_write_failed"
    assert "fill_jewels" not in orchestration.calls


def test_completed_candidate_is_not_restored_after_later_terminal_failure(
    monkeypatch, orchestration
):
    attempts = []

    def candidate(_engine, _snapshot, lever, **_kwargs):
        attempts.append(lever)
        if lever is None:
            return {"score": 1, "constraintsMet": True, "xml": RAW}
        buildopt._stop_optimization(
            {"errorCode": "probe_failed", "recoveryRequired": True},
            stage="craft_weapon",
            default_code="unused",
        )

    monkeypatch.setattr(buildopt, "commit_and_max", candidate)
    result = buildopt.optimize_build(orchestration, **_options())
    assert result["errorCode"] == "probe_failed"
    assert attempts == [None, "critical strike"]
    assert "load_build_xml" not in orchestration.calls and "benchmark" not in orchestration.calls


def test_parallel_failure_stops_sibling_at_boundary_and_closes_extra(monkeypatch):
    primary, extra = Engine(), Engine()
    sibling_started, failure_set = threading.Event(), threading.Event()
    calls = []
    monkeypatch.setattr(buildopt, "available_engine_slots", lambda: 1)
    monkeypatch.setattr(buildopt, "PobEngine", lambda **_kwargs: extra)

    def candidate(engine, _snapshot, lever, _stop_event=None, **_kwargs):
        calls.append(lever)
        if engine is primary:
            assert sibling_started.wait(2)
            try:
                buildopt._stop_optimization(
                    {"errorCode": "first_probe_failed", "recoveryRequired": True},
                    stage="craft_weapon",
                    default_code="unused",
                )
            finally:
                failure_set.set()
        sibling_started.set()
        assert failure_set.wait(2)
        assert _stop_event.wait(2)
        buildopt._check_phase_boundary(engine, _stop_event)
        pytest.fail("a sibling must not append work after observing cancellation")

    monkeypatch.setattr(buildopt, "commit_and_max", candidate)
    with pytest.raises(buildopt._OptimizationStopped) as caught:
        buildopt._run_levers(primary, RAW, ["a", "b", "c", "d"], parallel=True, max_workers=2)
    assert caught.value.failure["errorCode"] == "first_probe_failed"
    assert sorted(calls) == ["a", "b"] and extra.closed


def test_support_failure_uses_same_safe_stop_contract(monkeypatch):
    engine = Engine()
    monkeypatch.setattr(
        buildopt.supportopt,
        "optimize_supports",
        lambda *_args, **_kwargs: {
            "ok": False,
            "errorCode": "support_restore_failed",
            "recoveryRequired": True,
            "firstFailure": {
                "stage": "search",
                "errorCode": "support_probe_failed",
                "errorType": "PobEngineError",
            },
        },
    )
    with pytest.raises(buildopt._OptimizationStopped) as caught:
        buildopt._apply_supports(engine, "TotalDPS")
    assert caught.value.failure["firstFailure"]["errorCode"] == "support_probe_failed"
    assert engine.calls == []
