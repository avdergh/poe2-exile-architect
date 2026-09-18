from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import gc
import json
import threading
from types import SimpleNamespace
import weakref

import pytest

from server import main
from server.compute.engine_pool import SessionCallGate, SessionComputeBusy, SessionEnginePool
from server.runtime.compute_control import (
    ComputeControl, ComputeStopped, check_compute_budget, publication_guard, use_compute_control,
)
from server.runtime.compute_operations import ComputeOperations


class Session:
    pass


class Engine:
    def __init__(self):
        self.xml = '<PathOfBuilding><Build level="98"/></PathOfBuilding>'
        self.reads = 0
        self.proc = SimpleNamespace(poll=lambda: None)
        self.info = {"runtimeContract": 14}

    def get_xml(self):
        self.reads += 1
        return self.xml

    def close(self):
        pass


def payload(result):
    if isinstance(result, tuple):
        return result[1]
    if isinstance(result, dict):
        return result
    return json.loads(result[0].text)


async def terminal(manager, owner, operation_id):
    for _ in range(1000):
        result = manager.get(owner, operation_id)
        if "computationComplete" in result:
            return result
        await asyncio.sleep(.002)
    pytest.fail("background operation did not complete")


@pytest.fixture
def setup(monkeypatch):
    manager = ComputeOperations()
    gate = SessionCallGate()
    pool = SessionEnginePool(factory=Engine)
    monkeypatch.setattr(main, "_compute_operations", manager)
    monkeypatch.setattr(main, "_session_call_gate", gate)
    monkeypatch.setattr(main, "_engine_pool", pool)
    monkeypatch.setattr(main, "_compute_runtime_context", lambda _engine: {"version": "test"})
    return manager, gate, pool


def submit(manager, owner, function, gate, pool, **kwargs):
    return manager.submit(
        owner, tool="optimize_supports", arguments={}, function=function, gate=gate, pool=pool,
        runtime_context=lambda _engine: {"version": "test"}, **kwargs,
    )


def test_mcp_result_survives_request_end_deduplicates_and_keeps_metadata_responsive(setup, monkeypatch):
    manager, gate, pool = setup
    owner = Session()
    server = main._SessionIsolatedFastMCP("background-test")
    monkeypatch.setattr(server, "get_context", lambda: SimpleNamespace(session=owner))
    entered, release = threading.Event(), threading.Event()
    calls = []

    @server.tool()
    def optimize_supports(marker: int = 1, background: bool = False) -> dict:
        assert not background
        engine = main.get_engine()
        snapshot = engine.xml
        try:
            calls.append(marker)
            engine.xml = '<PathOfBuilding><Build level="1"/></PathOfBuilding>'
            entered.set()
            assert release.wait(3)
            check_compute_budget()
            with publication_guard():
                return {"ok": True, "recommendedSupports": ["whole", "set"]}
        finally:
            engine.xml = snapshot

    @server.tool()
    def mutation() -> dict:
        pytest.fail("a mutation entered the leased PoB")

    @server.tool()
    def apply_updates() -> dict:
        pytest.fail("updates entered a background lease")

    server.add_tool(main.get_compute_operation)
    server.add_tool(main.cancel_compute_operation)

    async def scenario():
        first = payload(await asyncio.wait_for(
            server.call_tool("optimize_supports", {"background": True}), .5,
        ))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            reads = pool.get(owner).reads
            repeat = payload(await asyncio.wait_for(
                server.call_tool("optimize_supports", {"background": True}), .5,
            ))
            assert repeat["operationId"] == first["operationId"] and repeat["deduplicated"]
            assert pool.get(owner).reads == reads  # no temporary-state hash read
            assert payload(await server.call_tool("mutation", {}))["errorCode"] == "compute_busy"
            assert payload(await server.call_tool("apply_updates", {}))["errorCode"] == "compute_busy"
            polled = payload(await server.call_tool(
                "get_compute_operation", {"operation_id": first["operationId"]},
            ))
            assert polled["status"] == "running"
            assert pool.get(owner).reads == reads
            assert manager.get(Session(), first["operationId"])["errorCode"] == "result_unavailable"
        finally:
            release.set()
        done = await terminal(manager, owner, first["operationId"])
        assert done["status"] == "completed" and done["resultOk"] is True
        assert done["result"]["recommendedSupports"] == ["whole", "set"]
        assert calls == [1] and gate.operation_busy(owner) is None
        assert manager.get(owner, first["operationId"])["result"] == done["result"]

    asyncio.run(scenario())


@pytest.mark.parametrize("stop", ["cancelled", "budget_exceeded"])
def test_cooperative_stop_restores_before_publishing_terminal_and_preserves_partial(setup, stop):
    manager, gate, pool = setup
    owner = Session()
    entered, release = threading.Event(), threading.Event()
    engine = pool.get(owner)
    original = engine.xml
    published = []

    def work():
        try:
            engine.xml = "<temporary/>"
            entered.set()
            assert release.wait(3)
            try:
                check_compute_budget()
            except ComputeStopped as exc:
                exc.partial_result = {"ok": False, "batchComplete": False, "results": ["completed-slot"]}
                raise
            with publication_guard():
                published.append(True)
            return {"ok": True}
        finally:
            engine.xml = original

    async def scenario():
        first = await submit(manager, owner, work, gate, pool)
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            if stop == "cancelled":
                response = manager.cancel(owner, first["operationId"])
                assert response["status"] == "cancel_requested" and response["cancelAccepted"]
            else:
                bucket = manager._bucket(owner)
                bucket.records[first["operationId"]].control.deadline = 0
            assert "computationComplete" not in manager.get(owner, first["operationId"])
        finally:
            release.set()
        result = await terminal(manager, owner, first["operationId"])
        assert result["status"] == stop
        assert result["result"]["batchComplete"] is False
        assert engine.xml == original and not published
        assert not getattr(engine, "_poe2_mutation_batch_recovery_required", False)

    asyncio.run(scenario())


def test_recovery_failure_wins_cancellation_and_blocks_reuse(setup):
    manager, gate, pool = setup
    owner = Session()
    engine = pool.get(owner)

    def work():
        engine.xml = "<corrupted/>"
        raise ComputeStopped("cancelled")

    async def scenario():
        first = await submit(manager, owner, work, gate, pool)
        done = await terminal(manager, owner, first["operationId"])
        assert done["status"] == "recovery_required"
        assert engine._poe2_mutation_batch_recovery_required is True
        with pytest.raises(RuntimeError, match="build_state_recovery_required"):
            await submit(manager, owner, work, gate, pool)
        assert gate.operation_busy(owner) is None

    asyncio.run(scenario())


def test_publication_wins_late_cancel_but_terminal_waits_for_restore(setup):
    manager, gate, pool = setup
    owner = Session()
    published, release = threading.Event(), threading.Event()

    def work():
        with publication_guard():
            published.set()
        assert release.wait(3)  # represents the existing finally restoration
        return {"ok": True}

    async def scenario():
        first = await submit(manager, owner, work, gate, pool)
        try:
            assert await asyncio.to_thread(published.wait, 1)
            response = manager.cancel(owner, first["operationId"])
            assert response["cancelAccepted"] is False
            assert response["status"] == "running"
        finally:
            release.set()
        assert (await terminal(manager, owner, first["operationId"]))["status"] == "completed"

    asyncio.run(scenario())


def test_other_session_isolated_and_existing_sync_call_has_no_background_queue(setup):
    manager, gate, pool = setup
    first, second = Session(), Session()

    async def scenario():
        async with gate.hold(first):
            response = await submit(manager, first, lambda: {"ok": True}, gate, pool)
            assert response["errorCode"] == "compute_busy"
            other = await submit(manager, second, lambda: {"ok": True}, gate, pool)
        assert (await terminal(manager, second, other["operationId"]))["status"] == "completed"
        assert pool.active_count() == 1  # busy first never starts an engine

    asyncio.run(scenario())


def test_completed_fifo_restart_and_business_failure_are_not_success(setup):
    _, gate, pool = setup
    manager, owner = ComputeOperations(completed_limit=2), Session()

    async def scenario():
        ids = []
        for _ in range(3):
            response = await submit(manager, owner, lambda: {"ok": False, "errorCode": "expected"}, gate, pool)
            done = await terminal(manager, owner, response["operationId"])
            assert done["status"] == "completed" and done["resultOk"] is False
            ids.append(response["operationId"])
        assert manager.get(owner, ids[0])["errorCode"] == "result_unavailable"
        assert manager.get(owner, ids[1])["result"]["errorCode"] == "expected"
        assert ComputeOperations().get(owner, ids[2])["errorCode"] == "result_unavailable"

    asyncio.run(scenario())


def test_worker_rechecks_input_and_does_not_poison_unmodified_conflicting_state(setup):
    manager, gate, pool = setup
    owner = Session()
    executed = []

    async def scenario():
        response = await submit(manager, owner, lambda: executed.append(True), gate, pool)
        engine = pool.get(owner)
        engine.xml = "<changed-before-worker/>"
        done = await terminal(manager, owner, response["operationId"])
        assert done["errorCode"] == "build_state_conflict"
        assert not executed and not getattr(engine, "_poe2_mutation_batch_recovery_required", False)

    asyncio.run(scenario())


def test_session_exit_requests_cancel_waits_for_restore_and_releases_references(setup):
    manager, gate, pool = setup
    owner = Session()
    owner._exit_stack = AsyncExitStack()
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        assert release.wait(3)
        check_compute_budget()
        return {"ok": True}

    async def scenario():
        response = await submit(manager, owner, work, gate, pool)
        assert await asyncio.to_thread(entered.wait, 1)
        closing = asyncio.create_task(owner._exit_stack.aclose())
        await asyncio.sleep(.01)
        assert not closing.done()
        assert manager.get(owner, response["operationId"])["status"] == "cancel_requested"
        release.set()
        await closing
        assert manager.get(owner, response["operationId"])["errorCode"] == "result_unavailable"

    asyncio.run(scenario())
    ref = weakref.ref(owner)
    owner = None
    gc.collect()
    assert ref() is None


def test_batch_children_do_not_seal_final_publication():
    control = ComputeControl(100)
    with use_compute_control(control):
        with publication_guard(final=False):
            pass
        assert control.cancel()
        with pytest.raises(ComputeStopped):
            with publication_guard():
                pytest.fail("cancelled batch published a complete receipt")


def test_maintenance_cannot_slip_into_submit_worker_handoff(setup):
    manager, gate, pool = setup
    owner = Session()

    async def scenario():
        first = await submit(manager, owner, lambda: {"ok": True}, gate, pool)
        with pytest.raises(SessionComputeBusy):
            with gate.maintenance_sync(wait=False):
                pytest.fail("runtime replacement entered an operation handoff")
        await terminal(manager, owner, first["operationId"])
        with gate.maintenance_sync(wait=False):
            assert True

    asyncio.run(scenario())


def test_exception_is_observable_and_session_lease_is_released(setup):
    manager, gate, pool = setup
    owner = Session()

    def work():
        raise ValueError("secret item text must not appear")

    async def scenario():
        response = await submit(manager, owner, work, gate, pool)
        done = await terminal(manager, owner, response["operationId"])
        assert done["status"] == "failed"
        assert done["result"] == {"ok": False, "errorType": "ValueError"}
        assert gate.operation_busy(owner) is None

    asyncio.run(scenario())


def test_finished_worker_is_not_visible_as_completed_before_gate_release(setup, monkeypatch):
    manager, gate, pool = setup
    owner = Session()
    finished, release = threading.Event(), threading.Event()
    execute = manager._execute

    def pause_after_execute(*args):
        execute(*args)
        finished.set()
        assert release.wait(3)

    monkeypatch.setattr(manager, "_execute", pause_after_execute)

    async def scenario():
        response = await submit(manager, owner, lambda: {"ok": True}, gate, pool)
        try:
            assert await asyncio.to_thread(finished.wait, 1)
            observed = manager.get(owner, response["operationId"])
            assert observed["status"] == "finalizing"
            assert "result" not in observed and "computationComplete" not in observed
            assert gate.operation_busy(owner) == response["operationId"]
        finally:
            release.set()
        assert (await terminal(manager, owner, response["operationId"]))["status"] == "completed"
        assert gate.operation_busy(owner) is None

    asyncio.run(scenario())


def test_disconnect_during_admission_does_not_lose_reserved_operation(setup, monkeypatch):
    manager, gate, pool = setup
    owner = Session()
    engine = pool.get(owner)
    entered, release = threading.Event(), threading.Event()
    read = engine.get_xml
    executions = []

    def paused_first_read():
        if engine.reads == 0:
            entered.set()
            assert release.wait(3)
        return read()

    monkeypatch.setattr(engine, "get_xml", paused_first_read)
    def work():
        executions.append(True)
        return {"ok": True}

    async def scenario():
        request = asyncio.create_task(submit(manager, owner, work, gate, pool))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            request.cancel()  # original response is lost while the input capture finishes
            retry = await submit(manager, owner, work, gate, pool)
            assert retry["deduplicated"] and retry["status"] == "starting"
        finally:
            release.set()
        await request
        done = await terminal(manager, owner, retry["operationId"])
        assert done["status"] == "completed" and executions == [True]

    asyncio.run(scenario())


def test_restore_requires_calcs_identity_even_when_semantic_hash_is_unchanged(setup):
    manager, gate, pool = setup
    owner = Session()
    engine = pool.get(owner)
    engine.info = {"runtimeContract": 15}
    selection = {"main": {"effectId": "main"}, "calcs": {"effectId": "main"}}

    def call(method):
        assert method == "item_replacement_selection"
        return json.loads(json.dumps(selection))

    engine.call = call

    def work():
        selection["calcs"]["effectId"] = "wrong"
        return {"ok": True}

    async def scenario():
        response = await submit(manager, owner, work, gate, pool)
        done = await terminal(manager, owner, response["operationId"])
        assert done["status"] == "recovery_required"
        assert engine._poe2_mutation_batch_recovery_required

    asyncio.run(scenario())
