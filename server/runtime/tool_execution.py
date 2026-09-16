"""Run synchronous MCP work without blocking transport or abandoning its transaction."""

from __future__ import annotations

import asyncio
from functools import wraps
import inspect
from typing import Any, Callable

import anyio


def threaded_tool(function: Callable[..., Any]) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(function):
        return function

    @wraps(function)
    async def run(*args: Any, **kwargs: Any) -> Any:
        worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        cancelled: asyncio.CancelledError | None = None
        # MCP uses level-triggered AnyIO cancellation. Shield that scope as well as
        # the worker task; otherwise every await would immediately cancel and spin.
        with anyio.CancelScope(shield=True):
            while True:
                try:
                    result = await asyncio.shield(worker)
                    break
                except asyncio.CancelledError as exc:
                    if worker.cancelled():
                        raise
                    # Cancelling a request cannot cancel a running Python thread. Retain the
                    # session gate until its own finally/rollback completes, even on repeated
                    # cancellation, so another request never observes temporary probe state.
                    cancelled = exc
        if cancelled is not None:
            raise cancelled
        return result

    # Resolve postponed annotations in the original function's namespace. FastMCP
    # otherwise attempts to resolve them in this helper module after decoration.
    run.__signature__ = inspect.signature(function, eval_str=True)  # type: ignore[attr-defined]
    return run
