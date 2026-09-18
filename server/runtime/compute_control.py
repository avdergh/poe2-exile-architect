"""Cooperative controls shared by one compute operation and all of its probes.

Stopping is intentionally a BaseException: existing measurement error handlers must not
turn a cancelled probe into a rejected candidate. Existing finally blocks still restore PoB.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import threading
import time
from typing import Any, Iterator


class ComputeStopped(BaseException):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ComputeControl:
    def __init__(self, budget_seconds: float) -> None:
        self.lock = threading.RLock()
        self.started_at = time.monotonic()
        self.deadline = self.started_at + budget_seconds
        self.stop_reason: str | None = None
        self.publication_started = False
        self.terminal = False
        self.finished_at: float | None = None
        self.progress: dict[str, Any] = {"phase": "starting", "completed": 0}

    def check(self) -> None:
        with self.lock:
            if self.publication_started:
                return
            if self.stop_reason is None and time.monotonic() >= self.deadline:
                self.stop_reason = "budget_exceeded"
            if self.stop_reason:
                raise ComputeStopped(self.stop_reason)

    def cancel(self) -> bool:
        with self.lock:
            if self.publication_started or self.terminal:
                return False
            self.stop_reason = self.stop_reason or "cancelled"
            return True

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "cancelRequested": self.stop_reason == "cancelled",
                "stopReason": self.stop_reason,
                "publicationStarted": self.publication_started,
                "elapsedSeconds": round((self.finished_at or time.monotonic()) - self.started_at, 3),
                "budgetSeconds": self.deadline - self.started_at,
                "progress": dict(self.progress),
                "cancellationMode": "cooperative_candidate_boundary",
            }


_CURRENT: ContextVar[ComputeControl | None] = ContextVar("poe_compute_control", default=None)


def current_compute_control() -> ComputeControl | None:
    return _CURRENT.get()


@contextmanager
def use_compute_control(control: ComputeControl) -> Iterator[None]:
    token = _CURRENT.set(control)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def check_compute_budget() -> None:
    if control := _CURRENT.get():
        control.check()


def report_compute_progress(phase: str, completed: int, total: int | None = None) -> None:
    if control := _CURRENT.get():
        with control.lock:
            control.progress = {"phase": phase, "completed": completed}
            if total is not None:
                control.progress["total"] = total


@contextmanager
def publication_guard(*, final: bool = True) -> Iterator[None]:
    """Arbitrate cancellation before publishing, never mark the operation restored/completed.

Batch child decisions use final=False. Only the complete batch seals publication. A
late cancellation after final publication starts is rejected; restoration still runs.
"""
    control = _CURRENT.get()
    if control is None:
        yield
        return
    with control.lock:
        control.check()
        if final:
            control.publication_started = True
        yield
