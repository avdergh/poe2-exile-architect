from __future__ import annotations

import time

from server.compute.engine import PobEngineError
from server.judge import runner


class _ExplodingEngine:
    def __init__(self):
        self.closed = False

    def get_build(self):
        raise PobEngineError("engine exited (code=1) before responding")

    def close(self):
        self.closed = True


def test_safe_evaluate_converts_engine_error_to_pob_compute_failed():
    engines: list[_ExplodingEngine] = []

    def factory():
        eng = _ExplodingEngine()
        engines.append(eng)
        return eng

    result = runner.safe_evaluate_active_build(factory, snapshot_id="boom")

    assert result["pass"] is False
    assert result["hardFailures"] == []
    assert result["scoreApplicability"]["reason"] == "pob_compute_failed"
    assert engines[0].closed is True


def test_safe_evaluate_converts_factory_error_to_pob_compute_failed():
    def factory():
        raise PobEngineError("invalid import")

    result = runner.safe_evaluate_active_build(factory, snapshot_id="bad-import")

    assert result["pass"] is False
    assert result["hardFailures"] == []
    assert result["scoreApplicability"]["reason"] == "pob_compute_failed"
    assert "errorDetail" not in result
    assert result["errorKind"] == "PobEngineError"


def test_safe_evaluate_closes_engine_after_threaded_success():
    engines = []

    class _SuccessfulEngine:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    def factory():
        engine = _SuccessfulEngine()
        engines.append(engine)
        return engine

    original_eval = runner.evaluator.evaluate_active_build

    try:

        def fake_eval(engine, snapshot_id, source_context):
            return {"snapshotId": snapshot_id, "pass": True, "hardFailures": []}

        runner.evaluator.evaluate_active_build = fake_eval
        result = runner.safe_evaluate_active_build(factory, snapshot_id="ok")
    finally:
        runner.evaluator.evaluate_active_build = original_eval

    assert result["snapshotId"] == "ok"
    assert engines[0].closed is True


def test_safe_evaluate_closes_engine_after_non_timeout_success():
    engines = []

    class _SuccessfulEngine:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    def factory():
        engine = _SuccessfulEngine()
        engines.append(engine)
        return engine

    original_eval = runner.evaluator.evaluate_active_build

    try:

        def fake_eval(engine, snapshot_id, source_context):
            return {"snapshotId": snapshot_id, "pass": True, "hardFailures": []}

        runner.evaluator.evaluate_active_build = fake_eval
        result = runner.safe_evaluate_active_build(
            factory,
            snapshot_id="ok-no-thread",
            timeout_seconds=None,
        )
    finally:
        runner.evaluator.evaluate_active_build = original_eval

    assert result["snapshotId"] == "ok-no-thread"
    assert engines[0].closed is True


def test_safe_evaluate_times_out_factory():
    def factory():
        time.sleep(0.2)
        raise AssertionError("factory returned after deadline")

    result = runner.safe_evaluate_active_build(
        factory,
        snapshot_id="slow-factory",
        timeout_seconds=0.01,
    )

    assert result["pass"] is False
    assert result["hardFailures"] == []
    assert result["scoreApplicability"]["reason"] == "pob_compute_failed"
    assert "errorDetail" not in result
    assert result["errorKind"] == "TimeoutError"


def test_safe_evaluate_default_timeout_is_extended():
    seen = {}

    original_eval = runner.evaluator.evaluate_active_build

    try:

        def fake_eval(engine, snapshot_id, source_context):
            seen["engine"] = engine
            seen["snapshot_id"] = snapshot_id
            seen["source_context"] = source_context
            return {"snapshotId": snapshot_id, "pass": True, "hardFailures": []}

        runner.evaluator.evaluate_active_build = fake_eval

        class _SlowFactoryEngine:
            def close(self):
                pass

        original_thread = runner.threading.Thread

        class _FakeThread:
            def __init__(self, target, daemon):
                self._target = target
                self.daemon = daemon
                self._alive = False

            def start(self):
                self._target()
                self._alive = False

            def join(self, timeout):
                seen["timeout"] = timeout

            def is_alive(self):
                return False

        runner.threading.Thread = _FakeThread
        try:

            def factory():
                return _SlowFactoryEngine()

            result = runner.safe_evaluate_active_build(factory, snapshot_id="default-timeout")
        finally:
            runner.threading.Thread = original_thread
    finally:
        runner.evaluator.evaluate_active_build = original_eval

    assert seen["timeout"] == 900.0
    assert result["snapshotId"] == "default-timeout"


def test_safe_evaluate_respawns_after_failure():
    calls = 0

    class _GoodEngine:
        def get_build(self):
            return {
                "class": "Mercenary",
                "ascendancy": "Witchhunter",
                "level": 90,
                "mainSkill": "Spark",
                "mainSkillGroup": [{"name": "Spark", "isSupport": False}],
                "pointsUsed": 0,
                "pointsAvailable": 113,
                "stats": {"TotalDPS": 100_000},
                "treeVersion": "0_5",
                "latestTreeVersion": "0_5",
            }

        def get_stats(self, keys=None):
            return {
                "stats": {
                    "TotalDPS": 100_000,
                    "PhysicalMaximumHitTaken": 10_000,
                    "FireMaximumHitTaken": 10_000,
                    "ColdMaximumHitTaken": 10_000,
                    "LightningMaximumHitTaken": 10_000,
                    "ChaosMaximumHitTaken": 10_000,
                }
            }

        def get_defenses(self):
            return {"resistances": {"fire": 75, "cold": 75, "lightning": 75, "chaos": 75}}

    def factory():
        nonlocal calls
        calls += 1
        if calls == 1:
            return _ExplodingEngine()
        return _GoodEngine()

    first = runner.safe_evaluate_active_build(factory, snapshot_id="first")
    second = runner.safe_evaluate_active_build(factory, snapshot_id="second")

    assert first["pass"] is False
    assert second["snapshotId"] == "second"
    assert "pob_compute_failed" not in second["hardFailures"]


def test_safe_evaluate_times_out_and_closes_engine():
    class _SlowEngine:
        def __init__(self):
            self.closed = False

        def get_build(self):
            time.sleep(0.2)
            return {}

        def close(self):
            self.closed = True

    engines: list[_SlowEngine] = []

    def factory():
        eng = _SlowEngine()
        engines.append(eng)
        return eng

    result = runner.safe_evaluate_active_build(
        factory,
        snapshot_id="slow",
        timeout_seconds=0.01,
    )

    assert result["pass"] is False
    assert result["hardFailures"] == []
    assert result["scoreApplicability"]["reason"] == "pob_compute_failed"
    assert "errorDetail" not in result
    assert result["errorKind"] == "TimeoutError"
    assert engines[0].closed is True
