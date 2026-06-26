from __future__ import annotations

from typing import Any

import pytest

from scripts import smoke_freshness


@pytest.mark.parametrize(
    "decision",
    ["verified_current", "blocked_stale", "blocked_unknown", "blocked_conflict"],
)
def test_main_returns_zero_for_report_decisions_and_sanitizes_output(
    monkeypatch,
    capsys,
    decision: str,
) -> None:
    long_diagnostic = (
        "upstream response line 1\nline 2 "
        "Authorization: Bearer super-secret-token "
        "https://example.test/path?token=abc123&signature=signed "
        "\x1b[31m" + ("x" * 400)
    )

    def fake_report(*, force_refresh: bool) -> dict[str, Any]:
        assert force_refresh is True
        return {
            "decision": decision,
            "evaluated_at": "2026-06-25T08:30:00+08:00",
            "blockers": ["local PoB pin is behind upstream"],
            "warnings": ["cache warning\nwith newline"],
            "provider_status": [
                {
                    "source": "pob",
                    "cache_state": "fallback",
                    "duration_ms": 123,
                    "diagnostics": [long_diagnostic],
                }
            ],
            "evidence": [
                {
                    "component": "pob_engine",
                    "source": "Path of Building",
                    "status": "stale",
                    "version": "v0.21.1",
                    "claims": [
                        {"key": "game_patch", "value": "0.3.0"},
                        {"key": "passive_tree", "value": "0_3_0"},
                    ],
                }
            ],
        }

    monkeypatch.setattr(smoke_freshness.service, "get_freshness_report", fake_report)

    assert smoke_freshness.main() == 0

    output = capsys.readouterr().out
    assert f"decision: {decision}" in output
    assert "evaluated_at: 2026-06-25T08:30:00+08:00" in output
    assert "cache_state=fallback" in output
    assert "component=pob_engine" in output
    assert "claims=[game_patch=0.3.0, passive_tree=0_3_0]" in output
    assert "upstream response line 1 line 2" in output
    assert "upstream response line 1\nline 2" not in output
    assert "super-secret-token" not in output
    assert "abc123" not in output
    assert "signed" not in output
    assert "\x1b" not in output
    diagnostic_line = next(line for line in output.splitlines() if "upstream response" in line)
    assert "[truncated]" in diagnostic_line
    assert len(diagnostic_line) < 260


def test_main_returns_nonzero_only_for_internal_errors(monkeypatch, capsys) -> None:
    def fail_report(*, force_refresh: bool) -> dict[str, Any]:
        assert force_refresh is True
        raise RuntimeError("service failed\nwith verbose body " + ("y" * 400))

    monkeypatch.setattr(smoke_freshness.service, "get_freshness_report", fail_report)

    assert smoke_freshness.main() == 1

    error = capsys.readouterr().err
    assert "RuntimeError" in error
    assert "service failed with verbose body" in error
    assert "service failed\nwith verbose body" not in error
    assert "[truncated]" in error
