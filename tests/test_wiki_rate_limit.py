from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
from urllib.error import HTTPError

import pytest

from server.live import wiki


NOW = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


@pytest.mark.parametrize(
    ("header", "seconds", "source"),
    [
        ("120", 120, "retry_after_header"),
        ("0", 0, "retry_after_header"),
        (format_datetime(NOW + timedelta(seconds=90), usegmt=True), 90, "retry_after_header"),
        (format_datetime(NOW - timedelta(seconds=5), usegmt=True), 0, "retry_after_header"),
        (None, 60, "default_suggestion"),
        ("garbage", 60, "default_suggestion"),
        ("-1", 60, "default_suggestion"),
        ("9" * 100, 60, "default_suggestion"),
    ],
)
def test_429_returns_retry_advice_without_another_request(monkeypatch, header, seconds, source):
    headers = Message()
    if header is not None:
        headers["Retry-After"] = header
    calls = []

    def refuse(_params, timeout=12.0):
        calls.append(_params)
        raise HTTPError(wiki.API, 429, "Too Many Requests", headers, None)

    monkeypatch.setattr(wiki, "datetime", FixedDatetime)
    monkeypatch.setattr(wiki, "_api", refuse)
    result = wiki.lookup_mechanic("A mechanic")

    assert len(calls) == 1
    assert result["available"] is False
    assert result["errorCode"] == "rate_limited"
    assert result["retryAfterSeconds"] == seconds
    assert result["retryAfterSource"] == source
    assert result["retryAt"] == (NOW + timedelta(seconds=seconds)).isoformat().replace(
        "+00:00", "Z"
    )
    assert result["topic"] == "A mechanic"


def test_search_fallback_429_keeps_retry_advice(monkeypatch):
    monkeypatch.setattr(wiki, "_extract", lambda _: None)

    def refuse(*args, **kwargs):
        raise HTTPError(wiki.API, 429, "Too Many Requests", None, None)

    monkeypatch.setattr(wiki, "_api", refuse)
    assert wiki.lookup_mechanic("Missing exact title")["errorCode"] == "rate_limited"


def test_non_rate_limit_http_error_keeps_existing_unavailable_result(monkeypatch):
    def fail(*args, **kwargs):
        raise HTTPError(wiki.API, 503, "Unavailable", None, None)

    monkeypatch.setattr(wiki, "_api", fail)
    result = wiki.lookup_mechanic("A mechanic")
    assert result["available"] is False
    assert "503" in result["error"]
    assert "retryAt" not in result
    assert "rate_limited" not in result.values()
