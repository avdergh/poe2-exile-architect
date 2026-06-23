from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import os

import pytest

from server.freshness import cache as cache_module
from server.freshness.cache import (
    CacheEnvelope,
    CacheFormatError,
    CacheIOError,
    FileCacheStore,
    TransportError,
    TransportRequest,
    TransportResponse,
    canonical_payload_sha256,
    run_cached,
)
from server.freshness.provider_models import CachePolicy, CacheState, ProviderResult


NOW = datetime(2026, 6, 23, 8, 30, tzinfo=UTC)
POLICY = CachePolicy(
    refresh_after=timedelta(minutes=15),
    reject_after=timedelta(hours=2),
)


def make_envelope(**changes: object) -> CacheEnvelope:
    values = {
        "source": "ggg-patch",
        "source_url": "https://example.test/patch-notes",
        "fetched_at": NOW,
        "checked_at": NOW,
        "etag": '"patch-1"',
        "last_modified": "Tue, 23 Jun 2026 08:00:00 GMT",
        "payload": {"patch": "0.5.3", "league": "Runes of Aldur"},
    }
    values.update(changes)
    return CacheEnvelope.create(**values)


class RecordingTransport:
    def __init__(self, outcome: TransportResponse | Exception) -> None:
        self.outcome = outcome
        self.requests: list[TransportRequest] = []

    def __call__(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def parse_json_object(body: bytes) -> dict[str, object]:
    value = json.loads(body)
    assert isinstance(value, dict)
    return value


def run(
    store: FileCacheStore,
    transport: RecordingTransport,
    *,
    now: datetime = NOW,
    force_refresh: bool = False,
):
    return run_cached(
        source="ggg-patch",
        source_url="https://example.test/patch-notes",
        now=now,
        policy=POLICY,
        store=store,
        transport=transport,
        parse=parse_json_object,
        force_refresh=force_refresh,
    )


def test_valid_cache_envelope_round_trips(tmp_path):
    path = tmp_path / "ggg-patch.json"
    store = FileCacheStore(path)
    expected = make_envelope()

    store.save(expected)

    assert store.load() == expected


def test_cache_store_atomically_replaces_from_sibling_temp_file(tmp_path, monkeypatch):
    path = tmp_path / "ggg-patch.json"
    calls = []
    real_replace = os.replace

    def record_replace(source, destination):
        calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(cache_module.os, "replace", record_replace)

    FileCacheStore(path).save(make_envelope())

    assert len(calls) == 1
    temporary, destination = map(type(path), calls[0])
    assert temporary.parent == path.parent
    assert temporary != path
    assert destination == path
    assert not temporary.exists()


def test_cache_store_normalizes_parent_creation_errors(tmp_path):
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("occupied", encoding="utf-8")

    with pytest.raises(CacheIOError, match="unable to write cache"):
        FileCacheStore(parent_file / "cache.json").save(make_envelope())


def test_cache_envelope_rejects_mismatched_content_hash():
    raw = make_envelope().to_dict()
    raw["content_sha256"] = "0" * 64

    with pytest.raises(CacheFormatError, match="content_sha256"):
        CacheEnvelope.from_dict(raw)


@pytest.mark.parametrize("field", ["fetched_at", "checked_at"])
def test_cache_envelope_rejects_timezone_naive_timestamps(field):
    values = {
        "fetched_at": NOW,
        "checked_at": NOW,
    }
    values[field] = NOW.replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        make_envelope(**values)


def test_payload_hash_uses_canonical_utf8_json():
    payload = {"z": "雪", "a": [2, {"β": True}]}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert canonical_payload_sha256(payload) == hashlib.sha256(canonical).hexdigest()
    assert canonical_payload_sha256({"a": [2, {"β": True}], "z": "雪"}) == hashlib.sha256(
        canonical
    ).hexdigest()


def test_provider_contracts_preserve_policy_and_result_values():
    policy = CachePolicy(
        refresh_after=timedelta(minutes=15),
        reject_after=timedelta(hours=2),
    )
    result = ProviderResult(
        source="ggg-patch",
        evidence=(),
        cache_state=CacheState.FRESH,
        diagnostics=(),
        duration_ms=7,
    )

    assert policy.minimum_force_interval == timedelta(seconds=60)
    assert result.cache_state.value == "fresh"
    assert result.duration_ms == 7


def test_fresh_cache_skips_transport(tmp_path):
    store = FileCacheStore(tmp_path / "ggg-patch.json")
    store.save(make_envelope(fetched_at=NOW - timedelta(minutes=10), checked_at=NOW - timedelta(minutes=10)))
    transport = RecordingTransport(AssertionError("transport must not be called"))

    result = run(store, transport)

    assert result.cache_state is CacheState.FRESH
    assert result.envelope == store.load()
    assert result.hard_stale is False
    assert transport.requests == []


def test_200_refreshes_payload_and_sends_conditional_headers(tmp_path):
    store = FileCacheStore(tmp_path / "ggg-patch.json")
    old = make_envelope(
        fetched_at=NOW - timedelta(hours=1),
        checked_at=NOW - timedelta(minutes=20),
    )
    store.save(old)
    transport = RecordingTransport(
        TransportResponse(
            status_code=200,
            body=b'{"patch":"0.5.4"}',
            headers={
                "ETag": '"patch-2"',
                "Last-Modified": "Tue, 23 Jun 2026 08:20:00 GMT",
            },
        )
    )

    result = run(store, transport)

    assert result.cache_state is CacheState.REFRESHED
    assert result.envelope == store.load()
    assert result.envelope is not None
    assert result.envelope.payload == {"patch": "0.5.4"}
    assert result.envelope.fetched_at == NOW
    assert result.envelope.checked_at == NOW
    assert result.envelope.etag == '"patch-2"'
    assert transport.requests == [
        TransportRequest(
            url=old.source_url,
            headers={
                "If-None-Match": '"patch-1"',
                "If-Modified-Since": "Tue, 23 Jun 2026 08:00:00 GMT",
            },
        )
    ]


def test_304_updates_only_checked_at(tmp_path):
    store = FileCacheStore(tmp_path / "ggg-patch.json")
    old = make_envelope(
        fetched_at=NOW - timedelta(hours=1),
        checked_at=NOW - timedelta(minutes=20),
    )
    store.save(old)
    transport = RecordingTransport(TransportResponse(status_code=304))

    result = run(store, transport)

    assert result.cache_state is CacheState.REVALIDATED
    assert result.envelope == CacheEnvelope.create(
        source=old.source,
        source_url=old.source_url,
        fetched_at=old.fetched_at,
        checked_at=NOW,
        etag=old.etag,
        last_modified=old.last_modified,
        payload=old.payload,
    )
    assert store.load() == result.envelope


def test_network_failure_before_reject_after_uses_fallback(tmp_path):
    store = FileCacheStore(tmp_path / "ggg-patch.json")
    old = make_envelope(
        fetched_at=NOW - timedelta(hours=1),
        checked_at=NOW - timedelta(minutes=20),
    )
    store.save(old)
    transport = RecordingTransport(TransportError("timeout"))

    result = run(store, transport)

    assert result.cache_state is CacheState.FALLBACK
    assert result.envelope == old
    assert result.hard_stale is False
    assert result.diagnostics == ("transport failed: timeout",)


def test_network_failure_after_reject_after_exposes_hard_stale(tmp_path):
    store = FileCacheStore(tmp_path / "ggg-patch.json")
    old = make_envelope(
        fetched_at=NOW - timedelta(hours=3),
        checked_at=NOW - timedelta(hours=3),
    )
    store.save(old)
    transport = RecordingTransport(TransportError("timeout"))

    result = run(store, transport)

    assert result.cache_state is CacheState.FALLBACK
    assert result.envelope == old
    assert result.hard_stale is True


def test_response_json_error_uses_fallback_without_replacing_cache(tmp_path):
    store = FileCacheStore(tmp_path / "ggg-patch.json")
    old = make_envelope(
        fetched_at=NOW - timedelta(hours=1),
        checked_at=NOW - timedelta(minutes=20),
    )
    store.save(old)
    transport = RecordingTransport(TransportResponse(status_code=200, body=b"{broken"))

    result = run(store, transport)

    assert result.cache_state is CacheState.FALLBACK
    assert result.envelope == old
    assert store.load() == old
    assert result.diagnostics and result.diagnostics[0].startswith("payload parse failed:")


def test_corrupt_cache_behaves_as_missing_and_is_replaced(tmp_path):
    path = tmp_path / "ggg-patch.json"
    path.write_text("{broken", encoding="utf-8")
    store = FileCacheStore(path)
    transport = RecordingTransport(
        TransportResponse(status_code=200, body=b'{"patch":"0.5.4"}')
    )

    result = run(store, transport)

    assert result.cache_state is CacheState.REFRESHED
    assert result.envelope == store.load()
    assert result.envelope is not None
    assert result.envelope.payload == {"patch": "0.5.4"}
    assert transport.requests == [
        TransportRequest(
            url="https://example.test/patch-notes",
            headers={},
        )
    ]
    assert result.diagnostics and result.diagnostics[0].startswith("cache unavailable:")


def test_cache_with_invalid_field_type_behaves_as_missing(tmp_path):
    path = tmp_path / "ggg-patch.json"
    raw = make_envelope().to_dict()
    raw["source"] = 7
    path.write_text(json.dumps(raw), encoding="utf-8")
    store = FileCacheStore(path)
    transport = RecordingTransport(TransportError("offline"))

    result = run(store, transport)

    assert result.cache_state is CacheState.MISSING
    assert result.envelope is None
    assert result.diagnostics[0].startswith("cache unavailable:")


def test_missing_cache_and_transport_failure_returns_missing(tmp_path):
    store = FileCacheStore(tmp_path / "ggg-patch.json")
    transport = RecordingTransport(TransportError("offline"))

    result = run(store, transport)

    assert result.cache_state is CacheState.MISSING
    assert result.envelope is None
    assert result.hard_stale is False
    assert result.diagnostics == ("transport failed: offline",)


def test_force_refresh_respects_minimum_interval(tmp_path):
    store = FileCacheStore(tmp_path / "ggg-patch.json")
    store.save(
        make_envelope(
            fetched_at=NOW - timedelta(seconds=30),
            checked_at=NOW - timedelta(seconds=30),
        )
    )
    transport = RecordingTransport(AssertionError("transport must not be called"))

    result = run(store, transport, force_refresh=True)

    assert result.cache_state is CacheState.FRESH
    assert transport.requests == []
    assert result.diagnostics == ("force refresh suppressed by minimum interval",)


def test_force_refresh_bypasses_refresh_after_once_minimum_interval_elapsed(tmp_path):
    store = FileCacheStore(tmp_path / "ggg-patch.json")
    store.save(
        make_envelope(
            fetched_at=NOW - timedelta(minutes=2),
            checked_at=NOW - timedelta(minutes=2),
        )
    )
    transport = RecordingTransport(TransportResponse(status_code=304))

    result = run(store, transport, force_refresh=True)

    assert result.cache_state is CacheState.REVALIDATED
    assert len(transport.requests) == 1
