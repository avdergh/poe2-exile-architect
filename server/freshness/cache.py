"""Validated, atomic storage for live freshness provider payloads."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import Event, Lock
from typing import Any, Callable, Iterator, Mapping, Protocol

from .provider_models import CachePolicy, CacheState


SCHEMA_VERSION = 1


class CacheError(Exception):
    """Base class for expected cache failures."""


class CacheFormatError(CacheError):
    """The cache file is syntactically valid data but violates the envelope contract."""


class CacheIOError(CacheError):
    """The cache could not be read or atomically written."""


class TransportError(Exception):
    """A normalized, expected failure from an injected network transport."""


class PayloadParseError(Exception):
    """A normalized failure caused by an upstream response shape change."""


class RefreshAttemptThrottle:
    """Thread-safe refresh-attempt tracking with caller-supplied time."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._last_attempts: dict[tuple[str, str], datetime] = {}

    def claim(
        self,
        *,
        source: str,
        cache_key: str,
        now: datetime,
        minimum_interval: timedelta,
    ) -> bool:
        _require_aware(now, "now")
        key = (source, cache_key)
        with self._lock:
            previous = self._last_attempts.get(key)
            if previous is not None and now - previous < minimum_interval:
                return False
            # Record before transport so failures and concurrent callers are throttled too.
            self._last_attempts[key] = now
            return True


class RefreshCoordinator:
    """Coordinate one in-flight refresh per source/cache key."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._flights: dict[tuple[str, str], Event] = {}

    @contextmanager
    def flight(self, *, source: str, cache_key: str) -> Iterator[bool]:
        key = (source, cache_key)
        with self._lock:
            event = self._flights.get(key)
            leader = event is None
            if leader:
                event = Event()
                self._flights[key] = event

        assert event is not None
        if not leader:
            # Waiting never holds the coordinator lock, so unrelated keys remain independent.
            event.wait()
            yield False
            return

        try:
            yield True
        finally:
            with self._lock:
                self._flights.pop(key, None)
                event.set()


@dataclass(frozen=True, slots=True)
class TransportRequest:
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status_code: int
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)


class Transport(Protocol):
    def __call__(self, request: TransportRequest) -> TransportResponse: ...


@dataclass(frozen=True, slots=True)
class CacheRunResult:
    envelope: CacheEnvelope | None
    cache_state: CacheState
    hard_stale: bool
    diagnostics: tuple[str, ...]


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CacheEnvelope:
    schema_version: int
    source: str
    source_url: str
    fetched_at: datetime
    checked_at: datetime
    etag: str | None
    last_modified: str | None
    content_sha256: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported cache schema_version: {self.schema_version}")
        if not isinstance(self.source, str):
            raise TypeError("cache source must be a string")
        if not self.source.strip():
            raise ValueError("cache source must be non-empty")
        if not isinstance(self.source_url, str):
            raise TypeError("cache source_url must be a string")
        if not self.source_url.strip():
            raise ValueError("cache source_url must be non-empty")
        if not isinstance(self.fetched_at, datetime):
            raise TypeError("fetched_at must be a datetime")
        if not isinstance(self.checked_at, datetime):
            raise TypeError("checked_at must be a datetime")
        _require_aware(self.fetched_at, "fetched_at")
        _require_aware(self.checked_at, "checked_at")
        if self.etag is not None and not isinstance(self.etag, str):
            raise TypeError("cache etag must be a string or null")
        if self.last_modified is not None and not isinstance(self.last_modified, str):
            raise TypeError("cache last_modified must be a string or null")
        if not isinstance(self.content_sha256, str):
            raise TypeError("cache content_sha256 must be a string")
        if not isinstance(self.payload, dict):
            raise TypeError("cache payload must be a JSON object")
        expected_hash = canonical_payload_sha256(self.payload)
        if self.content_sha256 != expected_hash:
            raise ValueError("cache content_sha256 does not match payload")

    @classmethod
    def create(
        cls,
        *,
        source: str,
        source_url: str,
        fetched_at: datetime,
        checked_at: datetime,
        etag: str | None,
        last_modified: str | None,
        payload: Mapping[str, Any],
    ) -> CacheEnvelope:
        stored_payload = dict(payload)
        return cls(
            schema_version=SCHEMA_VERSION,
            source=source,
            source_url=source_url,
            fetched_at=fetched_at,
            checked_at=checked_at,
            etag=etag,
            last_modified=last_modified,
            content_sha256=canonical_payload_sha256(stored_payload),
            payload=stored_payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at.isoformat(),
            "checked_at": self.checked_at.isoformat(),
            "etag": self.etag,
            "last_modified": self.last_modified,
            "content_sha256": self.content_sha256,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CacheEnvelope:
        try:
            return cls(
                schema_version=raw["schema_version"],
                source=raw["source"],
                source_url=raw["source_url"],
                fetched_at=datetime.fromisoformat(raw["fetched_at"]),
                checked_at=datetime.fromisoformat(raw["checked_at"]),
                etag=raw["etag"],
                last_modified=raw["last_modified"],
                content_sha256=raw["content_sha256"],
                payload=raw["payload"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CacheFormatError(f"invalid cache envelope: {exc}") from exc


class FileCacheStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def cache_key(self) -> str:
        return os.path.normcase(str(self.path.resolve()))

    def load(self) -> CacheEnvelope | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CacheFormatError(f"invalid cache JSON: {exc}") from exc
        except OSError as exc:
            raise CacheIOError(f"unable to read cache {self.path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise CacheFormatError("cache envelope must be a JSON object")
        return CacheEnvelope.from_dict(raw)

    def save(self, envelope: CacheEnvelope) -> None:
        temporary_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # A sibling temporary file keeps os.replace on one filesystem, preserving atomicity.
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(
                    envelope.to_dict(),
                    temporary,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        except OSError as exc:
            raise CacheIOError(f"unable to write cache {self.path}: {exc}") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _response_header(response: TransportResponse, name: str) -> str | None:
    wanted = name.casefold()
    for key, value in response.headers.items():
        if key.casefold() == wanted:
            return value
    return None


def _conditional_headers(envelope: CacheEnvelope | None) -> dict[str, str]:
    if envelope is None:
        return {}
    headers = {}
    if envelope.etag:
        headers["If-None-Match"] = envelope.etag
    if envelope.last_modified:
        headers["If-Modified-Since"] = envelope.last_modified
    return headers


def _fallback_result(
    envelope: CacheEnvelope | None,
    *,
    now: datetime,
    policy: CachePolicy,
    diagnostics: list[str],
) -> CacheRunResult:
    if envelope is None:
        return CacheRunResult(
            envelope=None,
            cache_state=CacheState.MISSING,
            hard_stale=False,
            diagnostics=tuple(diagnostics),
        )
    # checked_at is the last successful confirmation, including 304 revalidation.
    hard_stale = now - envelope.checked_at >= policy.reject_after
    return CacheRunResult(
        envelope=envelope,
        cache_state=CacheState.FALLBACK,
        hard_stale=hard_stale,
        diagnostics=tuple(diagnostics),
    )


def _suppressed_attempt_result(
    envelope: CacheEnvelope | None,
    *,
    now: datetime,
    policy: CachePolicy,
    diagnostics: list[str],
) -> CacheRunResult:
    if envelope is not None and now - envelope.checked_at < policy.refresh_after:
        return CacheRunResult(
            envelope=envelope,
            cache_state=CacheState.FRESH,
            hard_stale=False,
            diagnostics=tuple(diagnostics),
        )
    return _fallback_result(
        envelope,
        now=now,
        policy=policy,
        diagnostics=diagnostics,
    )


def _load_available_cache(
    store: FileCacheStore,
    diagnostics: list[str],
) -> CacheEnvelope | None:
    try:
        return store.load()
    except CacheError as exc:
        diagnostics.append(f"cache unavailable: {exc}")
        return None


def _fresh_result(
    envelope: CacheEnvelope,
    diagnostics: list[str],
) -> CacheRunResult:
    return CacheRunResult(
        envelope=envelope,
        cache_state=CacheState.FRESH,
        hard_stale=False,
        diagnostics=tuple(diagnostics),
    )


def run_cached(
    *,
    source: str,
    source_url: str,
    now: datetime,
    policy: CachePolicy,
    store: FileCacheStore,
    transport: Transport,
    parse: Callable[[bytes], Mapping[str, Any]],
    attempt_throttle: RefreshAttemptThrottle,
    refresh_coordinator: RefreshCoordinator,
    force_refresh: bool = False,
) -> CacheRunResult:
    """Run one conditional refresh without owning any concrete network implementation."""

    _require_aware(now, "now")
    diagnostics: list[str] = []
    # Corrupt or unreadable cache is untrusted input, so refresh as if it did not exist.
    envelope = _load_available_cache(store, diagnostics)

    if envelope is not None:
        age = now - envelope.checked_at
        if force_refresh and age < policy.minimum_force_interval:
            diagnostics.append("refresh attempt suppressed by minimum interval")
            return _suppressed_attempt_result(
                envelope,
                now=now,
                policy=policy,
                diagnostics=diagnostics,
            )
        if not force_refresh and age < policy.refresh_after:
            return _fresh_result(envelope, diagnostics)

    with refresh_coordinator.flight(source=source, cache_key=store.cache_key) as leader:
        if not leader:
            reloaded = _load_available_cache(store, diagnostics)
            if reloaded is not None and now - reloaded.checked_at < policy.refresh_after:
                return _fresh_result(reloaded, diagnostics)
            return _fallback_result(
                reloaded,
                now=now,
                policy=policy,
                diagnostics=diagnostics,
            )

        # Re-read after claiming leadership: a preceding flight may have completed after our
        # initial stale read but before this flight was registered.
        reloaded = _load_available_cache(store, diagnostics)
        if reloaded is not None:
            age = now - reloaded.checked_at
            if force_refresh and age < policy.minimum_force_interval:
                diagnostics.append("refresh attempt suppressed by minimum interval")
                return _suppressed_attempt_result(
                    reloaded,
                    now=now,
                    policy=policy,
                    diagnostics=diagnostics,
                )
            if not force_refresh and age < policy.refresh_after:
                return _fresh_result(reloaded, diagnostics)
        envelope = reloaded

        if not attempt_throttle.claim(
            source=source,
            cache_key=store.cache_key,
            now=now,
            minimum_interval=policy.minimum_force_interval,
        ):
            diagnostics.append("refresh attempt suppressed by minimum interval")
            return _suppressed_attempt_result(
                envelope,
                now=now,
                policy=policy,
                diagnostics=diagnostics,
            )

        request = TransportRequest(
            url=source_url,
            headers=_conditional_headers(envelope),
        )
        try:
            response = transport(request)
        except TransportError as exc:
            # Only normalized transport failures degrade to cache; programming errors stay visible.
            diagnostics.append(f"transport failed: {exc}")
            return _fallback_result(
                envelope,
                now=now,
                policy=policy,
                diagnostics=diagnostics,
            )

        if response.status_code == 304:
            if envelope is None:
                raise ValueError("transport returned 304 without a cache validator")
            revalidated = CacheEnvelope.create(
                source=envelope.source,
                source_url=envelope.source_url,
                fetched_at=envelope.fetched_at,
                checked_at=now,
                etag=envelope.etag,
                last_modified=envelope.last_modified,
                payload=envelope.payload,
            )
            state = CacheState.REVALIDATED
            refreshed = revalidated
        elif response.status_code == 200:
            try:
                payload = parse(response.body)
            except (UnicodeDecodeError, json.JSONDecodeError, PayloadParseError) as exc:
                # Providers normalize expected shape changes; arbitrary code errors must escape.
                diagnostics.append(f"payload parse failed: {exc}")
                return _fallback_result(
                    envelope,
                    now=now,
                    policy=policy,
                    diagnostics=diagnostics,
                )
            refreshed = CacheEnvelope.create(
                source=source,
                source_url=source_url,
                fetched_at=now,
                checked_at=now,
                etag=_response_header(response, "ETag"),
                last_modified=_response_header(response, "Last-Modified"),
                payload=payload,
            )
            state = CacheState.REFRESHED
        else:
            raise ValueError(f"transport returned unsupported status {response.status_code}")

        try:
            store.save(refreshed)
        except CacheError as exc:
            diagnostics.append(f"cache write failed: {exc}")
            return _fallback_result(
                envelope,
                now=now,
                policy=policy,
                diagnostics=diagnostics,
            )
        return CacheRunResult(
            envelope=refreshed,
            cache_state=state,
            hard_stale=False,
            diagnostics=tuple(diagnostics),
        )
