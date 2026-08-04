"""Safe MCP response-size and latency telemetry.

Only tool names, bounded correlation ids, duration and estimated response bytes are persisted.
Arguments and result content are never written.  The log helps identify context amplification
without retaining PoB material, prompts, URLs, build details or hidden reasoning.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server import paths
from server.learning.file_lock import interprocess_file_lock


_LOCK = threading.RLock()
MAX_TELEMETRY_BYTES = 5_000_000
_SAFE_CORRELATION = re.compile(r"^[A-Za-z0-9_.:\-]{3,160}$")
_CORRELATION_KEYS = (
    "progression_id",
    "progressionId",
    "run_id",
    "runId",
    "stage_id",
    "stageId",
    "campaign_id",
    "campaignId",
    "case_id",
    "caseId",
)


def record_tool_call(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
    duration_ms: float,
    failed: bool,
) -> None:
    """Best-effort telemetry; failures must never affect the MCP call."""

    try:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "toolName": str(tool_name)[:160],
            "durationMs": round(max(0.0, float(duration_ms)), 3),
            "responseBytes": estimate_response_bytes(result),
            "failed": bool(failed),
            "correlation": _safe_correlation(arguments),
        }
        _append(row)
    except Exception:  # noqa: BLE001 - telemetry must remain non-blocking and best effort.
        return


def estimate_response_bytes(value: Any, *, cap: int = 20_000_000) -> int:
    """Estimate serialized response size without retaining or returning its content."""

    seen: set[int] = set()

    def visit(item: Any) -> int:
        if item is None:
            return 4
        if isinstance(item, bool):
            return 4 if item else 5
        if isinstance(item, int | float):
            return len(str(item))
        if isinstance(item, str):
            return len(item.encode("utf-8")) + 2
        identity = id(item)
        if identity in seen:
            return 0
        seen.add(identity)
        dump = getattr(item, "model_dump", None)
        if callable(dump):
            try:
                return visit(dump(mode="json", by_alias=True))
            except TypeError:
                return visit(dump())
        if isinstance(item, dict):
            total = 2
            for key, child in item.items():
                total += visit(str(key)) + 1 + visit(child) + 1
                if total >= cap:
                    return cap
            return total
        if isinstance(item, list | tuple | set):
            total = 2
            for child in item:
                total += visit(child) + 1
                if total >= cap:
                    return cap
            return total
        return min(cap, len(str(item).encode("utf-8")) + 2)

    return min(cap, visit(value))


def telemetry_path() -> Path:
    return paths.user_data_dir() / "runtime" / "tool-context-telemetry.jsonl"


def _safe_correlation(arguments: dict[str, Any]) -> dict[str, str]:
    selected: dict[str, str] = {}
    for key in _CORRELATION_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and _SAFE_CORRELATION.fullmatch(value):
            selected[key] = value
    return selected


def _append(row: dict[str, Any]) -> None:
    path = telemetry_path()
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _LOCK:
        with interprocess_file_lock(path.with_suffix(".lock")):
            path.parent.mkdir(parents=True, exist_ok=True)
            # This is diagnostic telemetry, not durable history.  Bound it so a long-running MCP
            # server cannot turn context optimization into an unbounded local log.
            mode = (
                "w"
                if path.is_file()
                and path.stat().st_size + len(line.encode("utf-8")) > MAX_TELEMETRY_BYTES
                else "a"
            )
            with path.open(mode, encoding="utf-8") as handle:
                handle.write(line)
