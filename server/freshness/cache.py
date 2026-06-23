"""Validated, atomic storage for live freshness provider payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping, Protocol

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

    def load(self) -> CacheEnvelope | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as exc:
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


def run_cached(
    *,
    source: str,
    source_url: str,
    now: datetime,
    policy: CachePolicy,
    store: FileCacheStore,
    transport: Transport,
    parse: Callable[[bytes], Mapping[str, Any]],
    force_refresh: bool = False,
) -> CacheRunResult:
    """Run one conditional refresh without owning any concrete network implementation."""

    _require_aware(now, "now")
    diagnostics: list[str] = []
    try:
        envelope = store.load()
    except CacheError as exc:
        # Corrupt or unreadable cache is untrusted input, so refresh as if it did not exist.
        diagnostics.append(f"cache unavailable: {exc}")
        envelope = None

    if envelope is not None:
        age = now - envelope.checked_at
        if force_refresh and age < policy.minimum_force_interval:
            diagnostics.append("force refresh suppressed by minimum interval")
            return CacheRunResult(
                envelope=envelope,
                cache_state=CacheState.FRESH,
                hard_stale=False,
                diagnostics=tuple(diagnostics),
            )
        if not force_refresh and age < policy.refresh_after:
            return CacheRunResult(
                envelope=envelope,
                cache_state=CacheState.FRESH,
                hard_stale=False,
                diagnostics=tuple(diagnostics),
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
        except (json.JSONDecodeError, PayloadParseError) as exc:
            # Providers normalize expected shape changes; arbitrary code errors must still escape.
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
