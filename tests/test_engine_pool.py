from __future__ import annotations

import asyncio
import gc

import pytest

from server.compute import buildopt, engine as engine_module, engine_pool


class _Proc:
    def __init__(self) -> None:
        self.returncode = None

    def poll(self):
        return self.returncode


class _Engine:
    def __init__(self, identifier: int) -> None:
        self.identifier = identifier
        self.proc = _Proc()
        self.closed = False
        self.xml = f"<build id='{identifier}'/>"
        self.loaded_xml = ""

    def close(self) -> None:
        self.closed = True
        self.proc.returncode = 0

    def get_xml(self) -> str:
        return self.xml

    def load_build_xml(self, xml: str, name: str) -> None:
        self.loaded_xml = xml


class _Session:
    pass


def test_failed_engine_start_always_releases_global_capacity(monkeypatch):
    available_before = engine_module.available_engine_slots()

    def fail_start(*_args, **_kwargs):
        raise RuntimeError("engine startup failed")

    def fail_cleanup(_self):
        raise OSError("process cleanup failed")

    monkeypatch.setattr(engine_module.PobEngine, "_start", fail_start)
    monkeypatch.setattr(engine_module.PobEngine, "_terminate_failed_start", fail_cleanup)

    with pytest.raises(RuntimeError, match="engine startup failed"):
        engine_module.PobEngine()

    assert engine_module.available_engine_slots() == available_before


def test_session_engine_pool_isolates_sessions_and_enforces_limit():
    created: list[_Engine] = []

    def factory():
        engine = _Engine(len(created))
        created.append(engine)
        return engine

    pool = engine_pool.SessionEnginePool(factory=factory, max_engines=2)  # type: ignore[arg-type]
    first = _Session()
    second = _Session()

    assert pool.get(first) is pool.get(first)
    assert pool.get(second) is not pool.get(first)
    with pytest.raises(engine_pool.EnginePoolExhausted):
        pool.get(_Session())


def test_session_engine_pool_reclaims_closed_session_capacity():
    created: list[_Engine] = []

    def factory():
        engine = _Engine(len(created))
        created.append(engine)
        return engine

    pool = engine_pool.SessionEnginePool(factory=factory, max_engines=1)  # type: ignore[arg-type]
    session = _Session()
    first_engine = pool.get(session)
    del session
    gc.collect()

    assert first_engine.closed is True
    replacement = pool.get(_Session())

    assert replacement is not first_engine


def test_session_engine_pool_preserves_builds_across_runtime_swap():
    created: list[_Engine] = []

    def factory():
        engine = _Engine(len(created))
        created.append(engine)
        return engine

    pool = engine_pool.SessionEnginePool(factory=factory, max_engines=2)  # type: ignore[arg-type]
    first_session = _Session()
    second_session = _Session()
    first = pool.get(first_session)
    second = pool.get(second_session)

    with pool.preserve_sessions():
        assert first.closed is True
        assert second.closed is True
        assert pool.active_count() == 0

    restored_first = pool.get(first_session)
    restored_second = pool.get(second_session)
    assert restored_first.loaded_xml == first.xml
    assert restored_second.loaded_xml == second.xml


def test_session_call_gate_serializes_one_session_but_allows_other_sessions():
    gate = engine_pool.SessionCallGate()
    same = _Session()
    other = _Session()
    entered: list[str] = []
    release = asyncio.Event()

    async def first():
        async with gate.hold(same):
            entered.append("first")
            await release.wait()

    async def second():
        async with gate.hold(same):
            entered.append("second")

    async def independent():
        async with gate.hold(other):
            entered.append("other")

    async def scenario():
        first_task = asyncio.create_task(first())
        await asyncio.sleep(0)
        second_task = asyncio.create_task(second())
        other_task = asyncio.create_task(independent())
        await asyncio.sleep(0.05)
        assert entered == ["first", "other"]
        release.set()
        await asyncio.gather(first_task, second_task, other_task)

    asyncio.run(scenario())
    assert entered == ["first", "other", "second"]


def test_parallel_optimizer_degrades_to_one_engine_when_process_pool_is_full(monkeypatch):
    seen: list[str | None] = []
    engine = _Engine(0)
    engine.script = "pob_headless.lua"
    monkeypatch.setattr(buildopt, "available_engine_slots", lambda: 0)
    monkeypatch.setattr(
        buildopt,
        "commit_and_max",
        lambda _engine, _snapshot, lever, **_kwargs: seen.append(lever) or {"lever": lever},
    )

    result = buildopt._run_levers(  # noqa: SLF001 - focused regression for capacity fallback.
        engine,  # type: ignore[arg-type]
        "snapshot",
        ["crit", "speed"],
        parallel=True,
        max_workers=3,
    )

    assert result == [{"lever": "crit"}, {"lever": "speed"}]
    assert seen == ["crit", "speed"]
