"""Bounded, session-aware ownership for mutable Headless PoB engines."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
import os
import threading
from typing import Any, AsyncIterator, Callable, Iterator
import weakref

from .engine import PobEngine, PobEngineError, max_engine_processes


DEFAULT_MAX_ENGINES = 5
_DEFAULT_SESSION = object()
_current_session: ContextVar[object | None] = ContextVar(
    "poe2_build_mcp_engine_session", default=None
)


class EnginePoolExhausted(PobEngineError):
    """Raised when every allowed session engine is still owned by a live session."""


@dataclass
class _SessionRef:
    weak: weakref.ReferenceType[object] | None
    strong: object | None

    @classmethod
    def create(
        cls,
        session: object,
        callback: Callable[[weakref.ReferenceType[object]], None] | None = None,
    ) -> "_SessionRef":
        try:
            return cls(weak=weakref.ref(session, callback), strong=None)
        except TypeError:
            return cls(weak=None, strong=session)

    def get(self) -> object | None:
        return self.weak() if self.weak is not None else self.strong


@dataclass
class _EngineEntry:
    session: _SessionRef
    engine: PobEngine


@dataclass
class _GateEntry:
    session: _SessionRef
    lock: asyncio.Lock


def configured_max_engines() -> int:
    default_sessions = max(1, max_engine_processes() - 1)
    raw = os.environ.get("POE2_MCP_MAX_SESSION_ENGINES", str(default_sessions))
    try:
        value = int(raw)
    except ValueError:
        return default_sessions
    return max(1, min(value, max_engine_processes()))


def set_current_session(session: object | None) -> Token[object | None]:
    return _current_session.set(session)


def reset_current_session(token: Token[object | None]) -> None:
    _current_session.reset(token)


def current_session() -> object | None:
    return _current_session.get()


class SessionEnginePool:
    """Own at most one mutable engine per live MCP session, up to a fixed cap."""

    def __init__(
        self,
        *,
        factory: Callable[[], PobEngine] = PobEngine,
        max_engines: int | None = None,
    ) -> None:
        self._factory = factory
        self._max_engines = max_engines or configured_max_engines()
        self._entries: dict[int, _EngineEntry] = {}
        self._lock = threading.RLock()

    def get(self, session: object | None = None) -> PobEngine:
        owner = session if session is not None else _DEFAULT_SESSION
        key = id(owner)
        with self._lock:
            for stale in self._prune_locked():
                _close_engine(stale)
            entry = self._entries.get(key)
            if entry is not None and entry.session.get() is owner:
                if _engine_running(entry.engine):
                    engine = entry.engine
                else:
                    self._entries.pop(key, None)
                    _close_engine(entry.engine)
                    engine = self._create_locked(key, owner)
            else:
                if entry is not None:
                    self._entries.pop(key, None)
                    _close_engine(entry.engine)
                engine = self._create_locked(key, owner)
        return engine

    def close_all(self) -> None:
        with self._lock:
            engines = [entry.engine for entry in self._entries.values()]
            self._entries.clear()
        for engine in engines:
            _close_engine(engine)

    @contextmanager
    def preserve_sessions(self) -> Iterator[None]:
        """Restart live session engines after a runtime swap while preserving their build XML."""

        snapshots: list[tuple[_SessionRef, str]] = []
        with self._lock:
            for entry in self._entries.values():
                if entry.session.get() is None:
                    continue
                try:
                    snapshots.append((entry.session, entry.engine.get_xml()))
                except Exception:
                    pass
            engines = [entry.engine for entry in self._entries.values()]
            self._entries.clear()
            for engine in engines:
                _close_engine(engine)
        try:
            yield
        finally:
            for session_ref, xml in snapshots:
                owner = session_ref.get()
                if owner is None:
                    continue
                try:
                    engine = self.get(owner)
                    engine.load_build_xml(xml, name="restored-after-runtime-update")
                except Exception:
                    with self._lock:
                        failed_entry = self._entries.get(id(owner))
                        if failed_entry is not None:
                            self._entries.pop(id(owner))
                    if failed_entry is not None:
                        _close_engine(failed_entry.engine)

    def active_count(self) -> int:
        stale: list[PobEngine] = []
        with self._lock:
            stale.extend(self._prune_locked())
            count = len(self._entries)
        for engine in stale:
            _close_engine(engine)
        return count

    def _create_locked(self, key: int, owner: object) -> PobEngine:
        if len(self._entries) >= self._max_engines:
            raise EnginePoolExhausted(
                f"PoB session engine limit reached ({self._max_engines}); "
                "close an existing MCP session before starting another compute session"
            )
        engine = self._factory()
        pool_ref = weakref.ref(self)

        def collected(session_ref: weakref.ReferenceType[object]) -> None:
            pool = pool_ref()
            if pool is not None:
                pool._discard_collected(key, session_ref)

        self._entries[key] = _EngineEntry(
            session=_SessionRef.create(owner, collected),
            engine=engine,
        )
        return engine

    def _prune_locked(self) -> list[PobEngine]:
        stale_keys = [key for key, entry in self._entries.items() if entry.session.get() is None]
        return [self._entries.pop(key).engine for key in stale_keys]

    def _discard_collected(
        self,
        key: int,
        session_ref: weakref.ReferenceType[object],
    ) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.session.weak is not session_ref:
                return
            self._entries.pop(key, None)
        _close_engine(entry.engine)


class SessionCallGate:
    """Serialize complete MCP tool calls within one session, not merely individual RPC frames."""

    def __init__(self) -> None:
        self._entries: dict[int, _GateEntry] = {}
        self._lock = threading.Lock()
        self._maintenance_lock = _ThreadRWLock()

    @asynccontextmanager
    async def hold(self, session: object | None) -> AsyncIterator[None]:
        owner = session if session is not None else _DEFAULT_SESSION
        key = id(owner)
        with self._lock:
            self._prune_locked()
            entry = self._entries.get(key)
            if entry is None or entry.session.get() is not owner:
                entry = _GateEntry(session=_SessionRef.create(owner), lock=asyncio.Lock())
                self._entries[key] = entry
        await asyncio.to_thread(self._maintenance_lock.acquire_read)
        try:
            async with entry.lock:
                yield
        finally:
            self._maintenance_lock.release_read()

    @asynccontextmanager
    async def maintenance(self) -> AsyncIterator[None]:
        await asyncio.to_thread(self._maintenance_lock.acquire_write)
        try:
            yield
        finally:
            self._maintenance_lock.release_write()

    def maintenance_sync(self) -> "_SynchronousMaintenance":
        return _SynchronousMaintenance(self._maintenance_lock)

    def _prune_locked(self) -> None:
        stale_keys = [key for key, entry in self._entries.items() if entry.session.get() is None]
        for key in stale_keys:
            self._entries.pop(key, None)


def _engine_running(engine: Any) -> bool:
    proc = getattr(engine, "proc", None)
    poll = getattr(proc, "poll", None)
    return not callable(poll) or poll() is None


def _close_engine(engine: Any) -> None:
    close = getattr(engine, "close", None)
    if callable(close):
        close()


class _ThreadRWLock:
    """Writer-preferring RW lock shared by async MCP calls and maintenance threads."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._readers = 0
        self._writer = False
        self._writers_waiting = 0

    def acquire_read(self) -> None:
        with self._condition:
            while self._writer or self._writers_waiting:
                self._condition.wait()
            self._readers += 1

    def release_read(self) -> None:
        with self._condition:
            self._readers -= 1
            if self._readers == 0:
                self._condition.notify_all()

    def acquire_write(self) -> None:
        with self._condition:
            self._writers_waiting += 1
            try:
                while self._writer or self._readers:
                    self._condition.wait()
                self._writer = True
            finally:
                self._writers_waiting -= 1

    def release_write(self) -> None:
        with self._condition:
            self._writer = False
            self._condition.notify_all()


class _SynchronousMaintenance:
    def __init__(self, lock: _ThreadRWLock) -> None:
        self._lock = lock

    def __enter__(self) -> None:
        self._lock.acquire_write()

    def __exit__(self, *exc: object) -> None:
        self._lock.release_write()
