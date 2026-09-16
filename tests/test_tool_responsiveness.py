"""Busy diagnostics must remain responsive without exposing a temporary PoB state."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
from types import SimpleNamespace
import threading

import anyio

from server import main
from server.compute.engine_pool import SessionCallGate, SessionEnginePool, current_session


def _payload(result):
    if isinstance(result, tuple):
        return result[1]
    if isinstance(result, dict):
        return result
    return json.loads(result[0].text)


def test_long_sync_tool_keeps_transport_live_and_cancelled_transaction_owned(monkeypatch):
    gate = SessionCallGate()
    pool = SessionEnginePool(factory=lambda: (_ for _ in ()).throw(AssertionError("must not start")))
    monkeypatch.setattr(main, "_session_call_gate", gate)
    monkeypatch.setattr(main, "_engine_pool", pool)
    server = main._SessionIsolatedFastMCP("responsiveness-test")
    owner = object()
    monkeypatch.setattr(server, "get_context", lambda: SimpleNamespace(session=owner))
    started, release, finished, second_entered = (threading.Event() for _ in range(4))

    @server.tool()
    def slow_probe() -> dict:
        assert current_session() is owner
        started.set()
        try:
            assert release.wait(5)
            return {"restored": True}
        finally:
            finished.set()

    @server.tool()
    def following_mutation() -> dict:
        assert finished.is_set()
        second_entered.set()
        return {"ok": True}

    server.add_tool(main.engine_health)

    async def scenario():
        first = asyncio.create_task(server.call_tool("slow_probe", {}))
        second = None
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 2), 3)
            health = _payload(await asyncio.wait_for(server.call_tool("engine_health", {}), 1))
            assert health["status"] == "busy"
            assert health["activeTool"] == "slow_probe"
            assert health["readOnly"] is True
            assert pool.active_count() == 0
            first.cancel()
            second = asyncio.create_task(server.call_tool("following_mutation", {}))
            await asyncio.sleep(0.05)
            assert not first.done() and not second_entered.is_set()
            first.cancel()  # repeated cancellation must not release the session gate
            await asyncio.sleep(0.02)
            assert not second_entered.is_set()
            release.set()
            with suppress(asyncio.CancelledError):
                await first
            assert _payload(await asyncio.wait_for(second, 2))["ok"]
            assert gate.status(owner)["busy"] is False
        finally:
            release.set()
            with suppress(asyncio.CancelledError):
                await first
            if second is not None:
                await second

    asyncio.run(scenario())


def test_engine_health_does_not_ping_or_replace_an_exited_engine(monkeypatch):
    class Process:
        pid = 123

        def poll(self):
            return 7

    from server.compute.engine import PobEngine

    engine = object.__new__(PobEngine)
    engine.proc = Process()
    engine._lock = threading.RLock()
    engine.info = {"treeVersion": "0_5", "runtimeContract": 13}
    monkeypatch.setattr(main._engine_pool, "peek", lambda session: (engine, False))
    result = main.engine_health()
    assert result["status"] == "exited"
    assert result["processRunning"] is False
    assert result["observationScope"] == "process_and_activity_only"


def test_mcp_level_cancellation_waits_for_worker_without_blocking_other_tasks():
    from server.runtime.tool_execution import threaded_tool

    started, release, finished = (threading.Event() for _ in range(3))
    scopes = []

    @threaded_tool
    def work() -> dict:
        started.set()
        assert release.wait(5)
        finished.set()
        return {"ok": True}

    async def caller():
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            await work()
        assert finished.is_set()

    async def scenario():
        async with anyio.create_task_group() as group:
            group.start_soon(caller)
            assert await anyio.to_thread.run_sync(started.wait, 2)
            scopes[0].cancel()
            try:
                with anyio.fail_after(1):
                    await anyio.sleep(0.02)
                    assert not finished.is_set()
            finally:
                release.set()

    anyio.run(scenario)
