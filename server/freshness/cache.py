"""Validated, atomic storage for live freshness provider payloads."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from threading import Event, Lock
from typing import Any, Callable, Iterator, Protocol

from .provider_models import CachePolicy, CacheState


SCHEMA_VERSION = 1
DEFAULT_REFRESH_WAIT_TIMEOUT_SECONDS = 5.0


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
            if previous is not None:
                elapsed = now - previous
                if elapsed < timedelta(0):
                    # Wall clocks can move backwards; restart the window at the new clock value.
                    self._last_attempts[key] = now
                    return True
                if elapsed < minimum_interval:
                    return False
            # Record before transport so failures and concurrent callers are throttled too.
            self._last_attempts[key] = now
            return True


class RefreshCoordinator:
    """Coordinate one in-flight refresh per source/cache key."""

    def __init__(
        self,
        wait_timeout_seconds: float = DEFAULT_REFRESH_WAIT_TIMEOUT_SECONDS,
    ) -> None:
        if (
            not isinstance(wait_timeout_seconds, (int, float))
            or isinstance(wait_timeout_seconds, bool)
            or not math.isfinite(wait_timeout_seconds)
            or wait_timeout_seconds <= 0
        ):
            raise ValueError("wait_timeout_seconds must be a positive finite number")
        self._lock = Lock()
        self._flights: dict[tuple[str, str], Event] = {}
        self._wait_timeout_seconds = float(wait_timeout_seconds)

    @contextmanager
    def flight(
        self,
        *,
        source: str,
        cache_key: str,
        wait_timeout_seconds: float | None = None,
    ) -> Iterator[bool | None]:
        timeout = self._wait_timeout_seconds
        if wait_timeout_seconds is not None:
            if (
                not isinstance(wait_timeout_seconds, (int, float))
                or isinstance(wait_timeout_seconds, bool)
                or not math.isfinite(wait_timeout_seconds)
                or wait_timeout_seconds <= 0
            ):
                raise ValueError("wait_timeout_seconds must be a positive finite number")
            timeout = float(wait_timeout_seconds)
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
            if not event.wait(timeout=timeout):
                yield None
                return
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


def _normalize_json_value(
    value: Any,
    *,
    path: str,
    containers: set[int],
) -> Any:
    value_type = type(value)
    if value is None or value_type in (str, bool, int):
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise CacheFormatError(f"cache payload contains a non-finite JSON number at {path}")
        return value
    if value_type is list:
        identity = id(value)
        if identity in containers:
            raise CacheFormatError(f"cache payload contains a cycle at {path}")
        containers.add(identity)
        try:
            return [
                _normalize_json_value(item, path=f"{path}[{index}]", containers=containers)
                for index, item in enumerate(value)
            ]
        finally:
            containers.remove(identity)
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in containers:
            raise CacheFormatError(f"cache payload contains a cycle at {path}")
        containers.add(identity)
        try:
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise CacheFormatError(
                        f"cache payload contains a non-string JSON object key at {path}"
                    )
                normalized[key] = _normalize_json_value(
                    item,
                    path=f"{path}.{key}",
                    containers=containers,
                )
            return normalized
        finally:
            containers.remove(identity)
    raise CacheFormatError(
        f"cache payload contains a non-JSON value at {path}: {value_type.__name__}"
    )


def _normalize_json_object(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise CacheFormatError("cache payload must be a JSON object")
    normalized = _normalize_json_value(payload, path="$", containers=set())
    assert isinstance(normalized, dict)
    return normalized


def _canonical_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    normalized = _normalize_json_object(payload)
    try:
        return json.dumps(
            normalized,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        # Keep encoder-specific failures inside the cache error vocabulary.
        raise CacheFormatError(f"cache payload is not valid JSON: {exc}") from exc


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload_bytes(payload)).hexdigest()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True, init=False)
class CacheEnvelope:
    schema_version: int
    source: str
    source_url: str
    fetched_at: datetime
    checked_at: datetime
    etag: str | None
    last_modified: str | None
    content_sha256: str
    _payload: dict[str, Any] = field(repr=False)

    def __init__(
        self,
        *,
        schema_version: int,
        source: str,
        source_url: str,
        fetched_at: datetime,
        checked_at: datetime,
        etag: str | None,
        last_modified: str | None,
        content_sha256: str,
        payload: Mapping[str, Any],
    ) -> None:
        if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported cache schema_version: {schema_version}")
        if not isinstance(source, str):
            raise TypeError("cache source must be a string")
        if not source.strip():
            raise ValueError("cache source must be non-empty")
        if not isinstance(source_url, str):
            raise TypeError("cache source_url must be a string")
        if not source_url.strip():
            raise ValueError("cache source_url must be non-empty")
        if not isinstance(fetched_at, datetime):
            raise TypeError("fetched_at must be a datetime")
        if not isinstance(checked_at, datetime):
            raise TypeError("checked_at must be a datetime")
        _require_aware(fetched_at, "fetched_at")
        _require_aware(checked_at, "checked_at")
        if checked_at < fetched_at:
            raise ValueError("checked_at must be greater than or equal to fetched_at")
        if etag is not None and not isinstance(etag, str):
            raise TypeError("cache etag must be a string or null")
        if last_modified is not None and not isinstance(last_modified, str):
            raise TypeError("cache last_modified must be a string or null")
        if not isinstance(content_sha256, str):
            raise TypeError("cache content_sha256 must be a string")
        normalized_payload = _normalize_json_object(payload)
        expected_hash = canonical_payload_sha256(normalized_payload)
        if content_sha256 != expected_hash:
            raise ValueError("cache content_sha256 does not match payload")
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(self, "fetched_at", fetched_at)
        object.__setattr__(self, "checked_at", checked_at)
        object.__setattr__(self, "etag", etag)
        object.__setattr__(self, "last_modified", last_modified)
        object.__setattr__(self, "content_sha256", content_sha256)
        object.__setattr__(self, "_payload", normalized_payload)

    @property
    def payload(self) -> dict[str, Any]:
        # Never expose the mutable object whose bytes are covered by content_sha256.
        return _normalize_json_object(self._payload)

    def validate_integrity(self) -> None:
        expected_hash = canonical_payload_sha256(self._payload)
        if self.content_sha256 != expected_hash:
            raise CacheFormatError("cache content_sha256 does not match payload")

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
        stored_payload = _normalize_json_object(payload)
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
            raise CacheIOError("unable to read cache") from exc
        if not isinstance(raw, dict):
            raise CacheFormatError("cache envelope must be a JSON object")
        return CacheEnvelope.from_dict(raw)

    def save(self, envelope: CacheEnvelope) -> None:
        temporary_path: Path | None = None
        try:
            # Recheck immediately before serialization so stale validation cannot bless mutation.
            envelope.validate_integrity()
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
                    allow_nan=False,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        except (TypeError, ValueError) as exc:
            raise CacheFormatError(f"unable to encode cache: {exc}") from exc
        except OSError as exc:
            raise CacheIOError("unable to write cache") from exc
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
    *,
    source: str,
    source_url: str,
    now: datetime,
) -> CacheEnvelope | None:
    try:
        envelope = store.load()
    except CacheError as exc:
        diagnostics.append(f"cache unavailable: {_cache_error_diagnostic(exc)}")
        return None
    if envelope is None:
        return None
    try:
        # Stores can be substituted in tests or by callers, so do not trust load() alone.
        envelope.validate_integrity()
    except CacheError as exc:
        diagnostics.append(f"cache unavailable: {_cache_error_diagnostic(exc)}")
        return None
    if envelope.source != source or envelope.source_url != source_url:
        diagnostics.append("cache identity mismatch; cached payload ignored")
        return None
    if envelope.checked_at > now:
        diagnostics.append("cache checked_at is in the future; cached payload ignored")
        return None
    return envelope


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
    wait_timeout_seconds: float | None = None,
) -> CacheRunResult:
    """Run one conditional refresh without owning any concrete network implementation."""

    _require_aware(now, "now")
    diagnostics: list[str] = []
    # Corrupt, mismatched, or future-dated cache is untrusted input.
    envelope = _load_available_cache(
        store,
        diagnostics,
        source=source,
        source_url=source_url,
        now=now,
    )

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

    with refresh_coordinator.flight(
        source=source,
        cache_key=store.cache_key,
        wait_timeout_seconds=wait_timeout_seconds,
    ) as leader:
        if leader is None:
            diagnostics.append("refresh wait timed out")
            return _fallback_result(
                envelope,
                now=now,
                policy=policy,
                diagnostics=diagnostics,
            )
        if not leader:
            reloaded = _load_available_cache(
                store,
                diagnostics,
                source=source,
                source_url=source_url,
                now=now,
            )
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
        reloaded = _load_available_cache(
            store,
            diagnostics,
            source=source,
            source_url=source_url,
            now=now,
        )
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

        conditional_headers = _conditional_headers(envelope)
        request = TransportRequest(
            url=source_url,
            headers=conditional_headers,
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
            if envelope is None or not conditional_headers:
                diagnostics.append("transport returned 304 without a sent cache validator")
                return _fallback_result(
                    envelope,
                    now=now,
                    policy=policy,
                    diagnostics=diagnostics,
                )
            try:
                # Validate again after I/O so a 304 cannot recalculate and bless altered content.
                envelope.validate_integrity()
            except CacheError as exc:
                diagnostics.append(
                    f"cache unavailable during 304 revalidation: {_cache_error_diagnostic(exc)}"
                )
                return _fallback_result(
                    None,
                    now=now,
                    policy=policy,
                    diagnostics=diagnostics,
                )
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
            try:
                refreshed = CacheEnvelope.create(
                    source=source,
                    source_url=source_url,
                    fetched_at=now,
                    checked_at=now,
                    etag=_response_header(response, "ETag"),
                    last_modified=_response_header(response, "Last-Modified"),
                    payload=payload,
                )
            except CacheFormatError as exc:
                diagnostics.append(f"payload is not valid JSON: {exc}")
                return _fallback_result(
                    envelope,
                    now=now,
                    policy=policy,
                    diagnostics=diagnostics,
                )
            state = CacheState.REFRESHED
        else:
            if (
                response.status_code == 403
                and _response_header(response, "X-RateLimit-Remaining") == "0"
            ):
                diagnostics.append("github_rate_limited")
            diagnostics.append(f"transport returned HTTP {response.status_code}")
            return _fallback_result(
                envelope,
                now=now,
                policy=policy,
                diagnostics=diagnostics,
            )

        try:
            store.save(refreshed)
        except CacheError as exc:
            diagnostics.append(f"cache write failed: {_cache_error_diagnostic(exc)}")
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


def _cache_error_diagnostic(exc: CacheError) -> str:
    if isinstance(exc, CacheIOError):
        return "cache I/O error"
    return str(exc)
