"""Real PoB process/session recovery using transient synthetic builds only."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from server.compute.engine import PobEngine
from server.compute.engine_pool import SessionEnginePool
from server.compute.state import build_state_hash
from server.generation import validation_checkpoint as checkpoint


@pytest.fixture
def pool():
    script = Path(__file__).resolve().parents[1] / "pob" / "pob_headless.lua"
    instance = SessionEnginePool(factory=lambda: PobEngine(script=script), max_engines=2)
    checkpoint.clear_validation_checkpoint_cache()
    try:
        yield instance
    finally:
        instance.close_all()
        checkpoint.clear_validation_checkpoint_cache()


def prepare(engine):
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(18)
    engine.paste_skill("Spark 1/0 1")


def inspect(engine):
    result = checkpoint.inspect_generation_checkpoint(
        engine, offense_skill_group_index=1, expected_skill_name="Spark"
    )
    assert result["status"] != "error", result
    assert result["stateHash"] == build_state_hash(engine.get_xml())
    return result


@pytest.mark.parametrize("restart", ["runtime_swap", "process_exit"])
def test_real_pob_recovery_rechecks_same_build_in_new_process(pool, restart):
    owner = object()
    old = pool.get(owner)
    prepare(old)
    before = inspect(old)
    assert not before["cacheHit"]
    assert inspect(old)["cacheHit"] is True
    xml = old.get_xml()
    if restart == "runtime_swap":
        with pool.preserve_sessions():
            assert old.proc.poll() is not None
    else:
        # Terminate only the exact child created by this isolated test, never a user MCP service.
        old.proc.terminate()
        old.proc.wait(timeout=10)
    new = pool.get(owner)
    assert new is not old
    if restart == "process_exit":
        # Pool replacement does not promise to recover unsaved memory after a crash.
        new.load_build_xml(xml, name="isolated-recovery")
    after = inspect(new)
    assert after["stateHash"] == before["stateHash"]
    assert not after["cacheHit"]
    assert after["validationRef"] != before["validationRef"]
    actual = new.get_stats(["TotalDPS", "Life"])["stats"]
    for key in ("TotalDPS", "Life"):
        assert after["stats"][key] == actual[key] == before["stats"][key]
    assert actual["Life"] > 0 and actual["TotalDPS"] > 0
    assert inspect(new)["cacheHit"] is True


def test_real_pob_two_sessions_keep_independent_checkpoints_during_changes(pool):
    first, second = pool.get(object()), pool.get(object())
    prepare(first)
    a = inspect(first)
    second.load_build_xml(first.get_xml(), name="isolated-second-session")
    b = inspect(second)
    assert a["stateHash"] == b["stateHash"]
    assert not b["cacheHit"] and a["validationRef"] != b["validationRef"]
    second.set_level(19)
    with ThreadPoolExecutor(max_workers=2) as workers:
        pending_a = workers.submit(inspect, first)
        pending_b = workers.submit(inspect, second)
        unchanged, changed = pending_a.result(timeout=30), pending_b.result(timeout=30)
    assert unchanged["cacheHit"] is True
    assert not changed["cacheHit"]
    assert unchanged["stateHash"] == a["stateHash"] != changed["stateHash"]
    assert changed["stats"]["Life"] == second.get_stats(["Life"])["stats"]["Life"]
