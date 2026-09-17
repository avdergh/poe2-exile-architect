"""Session-owned, process-local results for the three long read-only compute tools.

This is deliberately not a queue or persistent scheduler. The ordinary session PoB is
leased until the worker has restored it. Metadata calls never inspect that mutable PoB.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import threading
import time
from typing import Any, Callable
from uuid import uuid4
import weakref

import anyio

from server.compute.engine_pool import (
    SessionCallGate, SessionComputeBusy, SessionEnginePool, _SessionRef,
    reset_current_session, set_current_session,
)
from server.compute.state import build_state_hash
from server.compute.item_search import capture_selection, selection_matches
from .compute_control import ComputeControl, ComputeStopped, use_compute_control
from .tool_execution import threaded_tool
from .compute_runtime_lock import RuntimeLease, RuntimeLeaseBusy, runtime_read_lease


COMPUTE_BUDGETS = {
    "optimize_supports": 1500.0,
    "optimize_item_sockets": 600.0,
    "plan_item_sockets_batch": 1500.0,
}
_RECOVERY = "_poe2_mutation_batch_recovery_required"
_DEFAULT_OWNER = object()


@dataclass
class _Operation:
    operation_id: str
    tool: str
    request_key: str
    control: ComputeControl
    state: str = "starting"
    input_hash: str | None = None
    input_selection: dict[str, Any] | None = None
    engine_generation: str | None = None
    runtime: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error_code: str | None = None
    task: asyncio.Task | None = None
    runtime_lease: RuntimeLease | None = None


@dataclass
class _SessionOperations:
    owner: _SessionRef
    records: OrderedDict[str, _Operation] = field(default_factory=OrderedDict)
    active_id: str | None = None
    closing: bool = False


def _json_default(value: Any) -> Any:
    if callable(getattr(value, "model_dump", None)):
        return value.model_dump(mode="json")
    raise TypeError("unsupported_compute_argument")


def _request_key(tool: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps([tool, arguments], sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _generation(engine: Any) -> str:
    value = getattr(engine, "_poe_compute_generation", None)
    if value is None:
        value = uuid4().hex
        setattr(engine, "_poe_compute_generation", value)
    return value


async def _finish_admission(function: Callable[[], Any]) -> Any:
    """A reserved ID must not disappear just because its submitting request disconnected."""
    worker = asyncio.create_task(asyncio.to_thread(function))
    with anyio.CancelScope(shield=True):
        while True:
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                if worker.cancelled():
                    raise


class ComputeOperations:
    def __init__(self, *, completed_limit: int = 32) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[int, _SessionOperations] = {}
        self._tasks: set[asyncio.Task] = set()
        self.completed_limit = completed_limit

    def _bucket(self, owner: object, *, create: bool = False) -> _SessionOperations | None:
        bucket = self._sessions.get(id(owner))
        if bucket is not None and bucket.owner.get() is owner:
            return bucket
        if not create:
            return None
        key = id(owner)

        def collected(_ref: Any) -> None:
            with self._lock:
                current = self._sessions.get(key)
                if current and current.owner.get() is None:
                    self._sessions.pop(key, None)

        bucket = _SessionOperations(_SessionRef.create(owner, collected))
        self._sessions[key] = bucket
        # MCP's session exit stack closes before its request task group. Do not
        # let session GC close an engine still being restored by its background task.
        stack = getattr(owner, "_exit_stack", None)
        if stack is not None and hasattr(stack, "push_async_callback"):
            stack.push_async_callback(self._close_ref, weakref.ref(owner))
        return bucket

    async def _close_ref(self, owner_ref: Any) -> None:
        if (owner := owner_ref()) is not None:
            await self.close_session(owner)

    async def close_session(self, session: object | None) -> None:
        owner = session if session is not None else _DEFAULT_OWNER
        with self._lock:
            bucket = self._bucket(owner)
            if bucket is None:
                return
            bucket.closing = True
            operation = bucket.records.get(bucket.active_id or "")
            if operation:
                operation.control.cancel()
            task = operation.task if operation else None
        if task is not None:
            with anyio.CancelScope(shield=True):
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
        with self._lock:
            self._sessions.pop(id(owner), None)

    def _view(self, operation: _Operation) -> dict[str, Any]:
        control = operation.control.snapshot()
        state = operation.state
        if not operation.control.terminal and state not in {"starting", "running"}:
            state = "finalizing"
        if state in {"starting", "running"} and control["stopReason"]:
            state = "cancel_requested" if control["cancelRequested"] else "budget_exceeded_requested"
        out = {
            "operationId": operation.operation_id,
            "tool": operation.tool,
            "status": state,
            "inputStateHash": operation.input_hash,
            "inputSelection": deepcopy(operation.input_selection),
            "engineGeneration": operation.engine_generation,
            "runtimeContext": deepcopy(operation.runtime),
            "resultRetention": "current_process_and_session_completed_fifo_32",
            "requiresStateHashRecheck": True,
            **control,
        }
        if operation.error_code:
            out["errorCode"] = operation.error_code
        if operation.control.terminal:
            out["result"] = deepcopy(operation.result)
            out["computationComplete"] = operation.state == "completed"
            out["resultOk"] = (
                operation.result.get("ok") if isinstance(operation.result, dict) else None
            )
        return out

    def get(self, session: object | None, operation_id: str) -> dict[str, Any]:
        owner = session if session is not None else _DEFAULT_OWNER
        with self._lock:
            bucket = self._bucket(owner)
            operation = bucket.records.get(operation_id) if bucket else None
            if operation is None:
                return {"ok": False, "errorCode": "result_unavailable"}
            return self._view(operation)

    def cancel(self, session: object | None, operation_id: str) -> dict[str, Any]:
        owner = session if session is not None else _DEFAULT_OWNER
        with self._lock:
            bucket = self._bucket(owner)
            operation = bucket.records.get(operation_id) if bucket else None
            if operation is None:
                return {"ok": False, "errorCode": "result_unavailable"}
            accepted = operation.control.cancel()
            return {**self._view(operation), "cancelAccepted": accepted}

    async def submit(
        self, session: object | None, *, tool: str, arguments: dict[str, Any],
        function: Callable[..., Any], gate: SessionCallGate, pool: SessionEnginePool,
        runtime_context: Callable[[Any], dict[str, Any]], budget_seconds: float | None = None,
    ) -> dict[str, Any]:
        owner = session if session is not None else _DEFAULT_OWNER
        request_key = _request_key(tool, arguments)
        with self._lock:
            bucket = self._bucket(owner, create=True)
            assert bucket is not None
            if bucket.closing:
                return {"ok": False, "errorCode": "compute_session_closed"}
            active = bucket.records.get(bucket.active_id or "")
            if active:
                if active.request_key == request_key:
                    return {**self._view(active), "deduplicated": True}
                return {"ok": False, "errorCode": "compute_busy", "operationId": active.operation_id}
        try:
            async with gate.hold(session, tool_name="submit_" + tool, wait=False):
                operation = _Operation(
                    "compute-" + uuid4().hex, tool, request_key,
                    ComputeControl(COMPUTE_BUDGETS[tool] if budget_seconds is None else budget_seconds),
                )
                gate.reserve_operation(session, operation.operation_id)
                with self._lock:
                    bucket.records[operation.operation_id] = operation
                    bucket.active_id = operation.operation_id
                try:
                    operation.runtime_lease = runtime_read_lease()
                    def capture() -> Any:
                        engine = pool.get(session)
                        if getattr(engine, _RECOVERY, False):
                            raise RuntimeError("build_state_recovery_required")
                        operation.input_hash = build_state_hash(engine.get_xml())
                        operation.input_selection = capture_selection(engine)
                        operation.engine_generation = _generation(engine)
                        operation.runtime = deepcopy(runtime_context(engine))
                        return engine

                    engine = await _finish_admission(capture)
                    task = asyncio.create_task(self._run(
                        owner, session, operation, engine, function, arguments, gate, pool, runtime_context,
                    ))
                    operation.task = task
                    self._tasks.add(task)
                    task.add_done_callback(self._task_done)
                except BaseException:
                    if operation.runtime_lease:
                        operation.runtime_lease.close()
                        operation.runtime_lease = None
                    gate.release_operation(session, operation.operation_id)
                    with self._lock:
                        bucket.active_id = None
                        bucket.records.pop(operation.operation_id, None)
                    raise
                return self._view(operation)
        except SessionComputeBusy as exc:
            return {"ok": False, "errorCode": "compute_busy", "operationId": exc.operation_id}
        except RuntimeLeaseBusy:
            return {"ok": False, "errorCode": "compute_busy", "reason": "runtime_update_in_progress"}

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        # Retrieve exceptions even if the client never polls. The worker normally
        # normalizes them; cancellation during service shutdown must not log raw data.
        if not task.cancelled():
            task.exception()

    async def _run(
        self, owner: object, session: object | None, operation: _Operation, engine: Any,
        function: Callable[..., Any], arguments: dict[str, Any], gate: SessionCallGate,
        pool: SessionEnginePool, runtime_context: Callable[[Any], dict[str, Any]],
    ) -> None:
        token = set_current_session(session)
        try:
            with anyio.CancelScope(shield=True):
                async with gate.hold(session, tool_name=operation.tool, operation_id=operation.operation_id):
                    operation.state = "running"
                    await threaded_tool(self._execute)(
                        operation, engine, function, arguments, pool, session, runtime_context,
                    )
        except BaseException as exc:
            with operation.control.lock:
                operation.state = "recovery_required"
                operation.error_code = "compute_worker_interrupted"
                operation.result = {"ok": False, "errorType": type(exc).__name__, "recoveryRequired": True}
                setattr(engine, _RECOVERY, True)
        finally:
            gate.release_operation(session, operation.operation_id)
            if operation.runtime_lease:
                operation.runtime_lease.close()
                operation.runtime_lease = None
            with self._lock:
                with operation.control.lock:
                    operation.control.finished_at = time.monotonic()
                    operation.control.terminal = True
                bucket = self._bucket(owner)
                if bucket:
                    if bucket.active_id == operation.operation_id:
                        bucket.active_id = None
                    # Completion order is FIFO; an active record is never evicted.
                    bucket.records.move_to_end(operation.operation_id)
                    completed = [key for key, item in bucket.records.items() if item.control.terminal]
                    for key in completed[:-self.completed_limit] if self.completed_limit else completed:
                        bucket.records.pop(key, None)
                operation.task = None
            reset_current_session(token)

    def _execute(
        self, operation: _Operation, engine: Any, function: Callable[..., Any],
        arguments: dict[str, Any], pool: SessionEnginePool, session: object | None,
        runtime_context: Callable[[Any], dict[str, Any]],
    ) -> None:
        control = operation.control
        result: Any = None
        status = "completed"
        error_code = None
        entered_compute = False
        with use_compute_control(control):
            try:
                current, busy = pool.peek(session)
                if busy or current is not engine or _generation(engine) != operation.engine_generation:
                    status, error_code = "failed", "compute_engine_changed"
                elif runtime_context(engine) != operation.runtime:
                    status, error_code = "failed", "compute_runtime_changed"
                elif build_state_hash(engine.get_xml()) != operation.input_hash:
                    status, error_code = "failed", "build_state_conflict"
                elif not selection_matches(engine, operation.input_selection):
                    status, error_code = "failed", "compute_selection_changed"
                elif getattr(engine, _RECOVERY, False):
                    status, error_code = "recovery_required", "build_state_recovery_required"
                else:
                    control.check()
                    entered_compute = True
                    result = function(**arguments)
            except ComputeStopped as exc:
                status, error_code = exc.reason, exc.reason
                result = getattr(exc, "partial_result", None)
            except Exception as exc:
                status, error_code = "failed", "compute_execution_failed"
                result = {"ok": False, "errorType": type(exc).__name__}
            finally:
                # The operation owns no XML recovery store: the compute layer's own
                # finally restores. Verify that restoration before any terminal success.
                restored = True
                if entered_compute:
                    try:
                        restored = (
                            build_state_hash(engine.get_xml()) == operation.input_hash
                            and selection_matches(engine, operation.input_selection)
                        )
                    except Exception:
                        restored = False
                recovery_required = (
                    not restored or bool(getattr(engine, _RECOVERY, False))
                    or (isinstance(result, dict) and result.get("recoveryRequired") is True)
                )
                with control.lock:
                    if recovery_required:
                        setattr(engine, _RECOVERY, True)
                        status, error_code = "recovery_required", "build_state_recovery_required"
                    elif status == "completed":
                        try:
                            control.check()
                        except ComputeStopped as exc:
                            status, error_code = exc.reason, exc.reason
                    operation.state, operation.error_code, operation.result = status, error_code, result
                    # Terminal visibility is published by the async owner only after it
                    # releases the session gate and lease. Seal late cancellation here.
                    control.publication_started = True
