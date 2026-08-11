from __future__ import annotations

import json

from server import paths
from server.runtime import tool_telemetry


def test_tool_telemetry_records_only_safe_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    secret = "https://example.invalid/private-build"
    result = {
        "status": "ok",
        "largeToolPayload": "x" * 2_000,
        "private": secret,
    }

    tool_telemetry.record_tool_call(
        tool_name="query_research_memory",
        arguments={
            "progression_id": "00000000-0000-0000-0000-000000000001",
            "query": secret,
            "checkpoint": {"hidden": secret},
        },
        result=result,
        duration_ms=123.4567,
        failed=False,
    )

    text = tool_telemetry.telemetry_path().read_text(encoding="utf-8")
    row = json.loads(text)
    assert row["toolName"] == "query_research_memory"
    assert row["durationMs"] == 123.457
    assert row["responseBytes"] >= 2_000
    assert row["correlation"] == {}
    assert secret not in text
    assert "largeToolPayload" not in text


def test_response_size_estimator_is_bounded():
    assert tool_telemetry.estimate_response_bytes({"payload": "x" * 100}, cap=50) == 50


def test_tool_telemetry_log_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(tool_telemetry, "MAX_TELEMETRY_BYTES", 180)

    for index in range(6):
        tool_telemetry.record_tool_call(
            tool_name=f"bounded_tool_{index}",
            arguments={},
            result={"payload": "x" * 100},
            duration_ms=1,
            failed=False,
        )

    text = tool_telemetry.telemetry_path().read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) <= 180
    assert "bounded_tool_5" in text
