"""Path of Building release, local pin, and compatibility freshness provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import sqlite3
import re
import string
from pathlib import Path
from time import monotonic
from typing import Any, Protocol

from .cache import (
    CacheRunResult,
    FileCacheStore,
    PayloadParseError,
    RefreshAttemptThrottle,
    RefreshCoordinator,
    Transport,
    TransportError,
    TransportRequest,
    TransportResponse,
    run_cached,
)
from .models import (
    ClaimDimension,
    Component,
    FreshnessEvidence,
    SourceStatus,
    VersionClaim,
)
from .provider_models import CachePolicy, ProviderResult


POB_RELEASE_API_URL = (
    "https://api.github.com/repos/PathOfBuildingCommunity/PathOfBuilding-PoE2/releases/latest"
)
POB_RELEASE_COMMIT_API_URL_BASE = (
    "https://api.github.com/repos/PathOfBuildingCommunity/PathOfBuilding-PoE2/commits"
)
POB_RELEASE_URL_BASE = "https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/releases/tag"
POB_COMMIT_URL_BASE = "https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/commit"
POB_POLICY = CachePolicy(
    refresh_after=timedelta(hours=1),
    reject_after=timedelta(hours=6),
)
DEFAULT_COMPATIBILITY_MANIFEST = (
    Path(__file__).resolve().parents[2] / "data" / "compatibility" / "pob.json"
)
DEFAULT_PINNED_PATH = Path(__file__).resolve().parents[2] / "pob" / "PINNED.md"

_SAFE_TAG = re.compile(r"^[A-Za-z0-9._-]+$")
_PINNED_COMMIT_LABEL = re.compile(r"pinned\s+commit", re.IGNORECASE)
_PINNED_COMMIT_TOKEN = re.compile(r"\b([0-9a-fA-F]{7,40})\b")


class PobParseError(PayloadParseError, ValueError):
    """An expected PoB release or manifest shape failure."""


class CacheRunner(Protocol):
    def __call__(
        self,
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
    ) -> CacheRunResult: ...


@dataclass(frozen=True, slots=True)
class PobRelease:
    tag: str
    name: str
    version: str
    published_at: datetime
    commit: str
    url: str
    commit_url: str


@dataclass(frozen=True, slots=True)
class CompatibilityEntry:
    commit: str
    pob_version: str
    game_patch: str
    passive_tree: str
    verified_by: tuple[str, ...]
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class CompatibilityManifest:
    schema_version: int
    entries: tuple[CompatibilityEntry, ...]


def pob_release_commit_api_url(tag: str) -> str:
    tag = _tag_token(tag, "release tag")
    return f"{POB_RELEASE_COMMIT_API_URL_BASE}/{tag}"


def parse_pob_release(release_json: Any, commit_json: Any) -> PobRelease:
    """Parse the latest GitHub release and its resolved full commit SHA."""

    release = _mapping(release_json, "release")
    commit = _mapping(commit_json, "release commit")
    tag = _tag_token(release.get("tag_name"), "release tag")
    version = tag.removeprefix("v").removeprefix("V")
    if not version:
        raise PobParseError("release version is missing")
    release_commit = _full_sha(commit.get("sha"), "release commit")
    published_at = _aware_datetime(release.get("published_at"), "release published_at")
    # Canonical URLs are built from validated tag/SHA rather than trusting API html_url fields.
    return PobRelease(
        tag=tag,
        name=_nonempty_string(release.get("name"), "release name"),
        version=version,
        published_at=published_at,
        commit=release_commit,
        url=f"{POB_RELEASE_URL_BASE}/{tag}",
        commit_url=f"{POB_COMMIT_URL_BASE}/{release_commit}",
    )


def load_compatibility_manifest(path: str | Path) -> CompatibilityManifest:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PobParseError(f"compatibility manifest is unavailable: {exc}") from exc
    manifest = _mapping(raw, "compatibility manifest")
    schema_version = manifest.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise PobParseError("compatibility manifest schema_version must be 1")
    raw_entries = _sequence(manifest.get("entries"), "compatibility entries")
    entries: list[CompatibilityEntry] = []
    commits: set[str] = set()
    for index, raw_entry in enumerate(raw_entries):
        entry = _compatibility_entry(raw_entry, index)
        if entry.commit in commits:
            raise PobParseError(f"duplicate compatibility commit: {entry.commit}")
        commits.add(entry.commit)
        entries.append(entry)
    return CompatibilityManifest(schema_version=1, entries=tuple(entries))


def resolve_compatibility(
    local_commit: str | None,
    manifest: CompatibilityManifest,
) -> CompatibilityEntry | None:
    if local_commit is None or not local_commit.strip():
        return None
    commit = local_commit.strip().lower()
    if any(character not in string.hexdigits for character in commit):
        raise PobParseError("local PoB commit is not hexadecimal")
    if len(commit) > 40:
        raise PobParseError("local PoB commit is longer than a full hash")

    exact = [entry for entry in manifest.entries if entry.commit == commit]
    if exact:
        return exact[0]
    if len(commit) == 40:
        return None

    # Short local pins are common in installed metadata. They are accepted only when the
    # compatibility manifest resolves them to exactly one full verified commit.
    prefix_matches = [entry for entry in manifest.entries if entry.commit.startswith(commit)]
    if len(prefix_matches) > 1:
        raise PobParseError(f"ambiguous local PoB commit prefix: {local_commit}")
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return None


def shape_pob_evidence(
    *,
    local_commit: str | None,
    local_version: str | None,
    remote_release: PobRelease | None,
    compatibility: CompatibilityEntry | None,
    observed_at: datetime,
    diagnostics: Sequence[str] = (),
    compatibility_error: str | None = None,
) -> tuple[tuple[FreshnessEvidence, ...], tuple[str, ...]]:
    """Shape local PoB engine/data evidence without deriving claims from release notes."""

    shaped_diagnostics = list(diagnostics)
    normalized_local_commit = _optional_commit(local_commit)
    normalized_local_version = _optional_string(local_version)
    if normalized_local_commit is None:
        shaped_diagnostics.append("local PoB commit unavailable")
        return _pob_records(
            status=SourceStatus.UNKNOWN,
            observed_at=observed_at,
            source_url=_evidence_url(remote_release),
            version=None,
            claims=(),
        ), tuple(shaped_diagnostics)

    if compatibility_error is not None:
        shaped_diagnostics.append(compatibility_error)
        return _pob_records(
            status=SourceStatus.UNKNOWN,
            observed_at=observed_at,
            source_url=_evidence_url(remote_release),
            version=normalized_local_version or normalized_local_commit,
            claims=(),
        ), tuple(shaped_diagnostics)

    claims = _compatibility_claims(compatibility) if compatibility is not None else ()
    # Short local pins are normalized through the manifest before freshness comparison.
    # Otherwise a remote full SHA that shares the same prefix can be mistaken as current.
    effective_local_commit = (
        compatibility.commit if compatibility is not None else normalized_local_commit
    )
    remote_newer = _remote_release_supersedes_local(
        effective_local_commit,
        remote_release,
        compatibility,
    )
    if remote_newer:
        assert remote_release is not None
        shaped_diagnostics.append(
            "local PoB "
            f"version={normalized_local_version or 'unknown'} "
            f"commit={effective_local_commit}; "
            f"latest release={remote_release.tag} commit={remote_release.commit[:12]}"
        )
    elif compatibility is None:
        shaped_diagnostics.append(
            f"local PoB commit {normalized_local_commit} is not in compatibility manifest"
        )
    else:
        shaped_diagnostics.append(
            f"compatibility manifest matched PoB commit {compatibility.commit}"
        )

    # A newer upstream PoB release is an update signal, not proof that a certified local
    # runtime became incompatible. Game-patch and passive-tree claims decide compatibility;
    # otherwise harmless same-season PoB releases would disable generation every few weeks.
    if compatibility is not None:
        status = SourceStatus.CURRENT
        if remote_newer:
            shaped_diagnostics.append(
                "newer upstream PoB release available; certified local compatibility retained"
            )
    elif remote_newer:
        status = SourceStatus.STALE
    else:
        status = SourceStatus.UNKNOWN

    evidence_version = (
        compatibility.commit
        if compatibility is not None
        else normalized_local_version or normalized_local_commit
    )
    return _pob_records(
        status=status,
        observed_at=observed_at,
        source_url=_evidence_url(remote_release),
        version=evidence_version,
        claims=claims,
    ), tuple(shaped_diagnostics)


class PobProvider:
    name = "pob"
    policy = POB_POLICY

    def __init__(
        self,
        *,
        store: FileCacheStore,
        transport: Transport,
        attempt_throttle: RefreshAttemptThrottle,
        refresh_coordinator: RefreshCoordinator,
        manifest_path: str | Path = DEFAULT_COMPATIBILITY_MANIFEST,
        local_metadata: Callable[[], Mapping[str, Any]] | None = None,
        cache_runner: CacheRunner = run_cached,
        timer: Callable[[], float] = monotonic,
    ) -> None:
        self._store = store
        self._transport = transport
        self._attempt_throttle = attempt_throttle
        self._refresh_coordinator = refresh_coordinator
        self._manifest_path = Path(manifest_path)
        self._local_metadata = local_metadata or _default_local_metadata
        self._cache_runner = cache_runner
        self._timer = timer

    def collect(
        self,
        now: datetime,
        force_refresh: bool = False,
    ) -> ProviderResult:
        started = self._timer()
        cache_result = self._cache_runner(
            source=self.name,
            source_url=POB_RELEASE_API_URL,
            now=now,
            policy=self.policy,
            store=self._store,
            transport=self._transport,
            parse=self._parse_refresh,
            attempt_throttle=self._attempt_throttle,
            refresh_coordinator=self._refresh_coordinator,
            force_refresh=force_refresh,
        )
        evidence, diagnostics = self._shape_evidence(cache_result, now=now)
        return ProviderResult(
            source=self.name,
            evidence=evidence,
            cache_state=cache_result.cache_state,
            diagnostics=diagnostics,
            duration_ms=_duration_ms(started, self._timer()),
        )

    def _parse_refresh(self, body: bytes) -> Mapping[str, Any]:
        release_json = _json_value(body, "release")
        release = _mapping(release_json, "release")
        tag = _tag_token(release.get("tag_name"), "release tag")
        response = _successful_response(
            transport=self._transport,
            url=pob_release_commit_api_url(tag),
            label="release commit",
        )
        parsed = parse_pob_release(
            release_json,
            _json_value(response.body, "release commit"),
        )
        return {
            "tag": parsed.tag,
            "name": parsed.name,
            "version": parsed.version,
            "published_at": parsed.published_at.isoformat(),
            "commit": parsed.commit,
        }

    def _shape_evidence(
        self,
        cache_result: CacheRunResult,
        *,
        now: datetime,
    ) -> tuple[tuple[FreshnessEvidence, ...], tuple[str, ...]]:
        diagnostics = list(cache_result.diagnostics)
        remote_release: PobRelease | None = None
        observed_at = now
        if cache_result.envelope is not None:
            if cache_result.hard_stale:
                diagnostics.append(
                    "hard-stale remote PoB release cache exceeded reject_after; "
                    "ignoring cached remote release"
                )
            else:
                observed_at = cache_result.envelope.checked_at
                try:
                    remote_release = _release_from_payload(cache_result.envelope.payload)
                except PobParseError as exc:
                    diagnostics.append(f"cached payload invalid: {exc}")

        try:
            metadata = self._local_metadata()
        except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error):
            diagnostics.append("local PoB metadata unavailable")
            metadata = {}
        local_commit = _metadata_string(metadata.get("pob_commit"))
        local_version = _metadata_string(metadata.get("version"))

        compatibility: CompatibilityEntry | None = None
        compatibility_error: str | None = None
        try:
            manifest = load_compatibility_manifest(self._manifest_path)
        except PobParseError as exc:
            compatibility_error = f"compatibility manifest invalid: {exc}"
        else:
            try:
                compatibility = resolve_compatibility(local_commit, manifest)
            except PobParseError as exc:
                compatibility_error = f"local PoB commit invalid: {exc}"

        return shape_pob_evidence(
            local_commit=local_commit,
            local_version=local_version,
            remote_release=remote_release,
            compatibility=compatibility,
            observed_at=observed_at,
            diagnostics=diagnostics,
            compatibility_error=compatibility_error,
        )


def _compatibility_entry(raw_entry: Any, index: int) -> CompatibilityEntry:
    entry = _mapping(raw_entry, f"compatibility entry {index}")
    verified_by = _verified_by(entry.get("verified_by"), index)
    return CompatibilityEntry(
        commit=_full_sha(entry.get("commit"), f"compatibility entry {index} commit"),
        pob_version=_nonempty_string(
            entry.get("pob_version"),
            f"compatibility entry {index} pob_version",
        ),
        game_patch=_nonempty_string(
            entry.get("game_patch"),
            f"compatibility entry {index} game_patch",
        ),
        passive_tree=_nonempty_string(
            entry.get("passive_tree"),
            f"compatibility entry {index} passive_tree",
        ),
        verified_by=verified_by,
        verified_at=_aware_datetime(
            entry.get("verified_at"),
            f"compatibility entry {index} verified_at",
        ),
    )


def _verified_by(value: Any, index: int) -> tuple[str, ...]:
    raw_items = _sequence(value, f"compatibility entry {index} verified_by")
    if not raw_items:
        raise PobParseError(f"compatibility entry {index} verified_by is empty")
    items = tuple(
        _nonempty_string(item, f"compatibility entry {index} verified_by item")
        for item in raw_items
    )
    return items


def _release_from_payload(payload: Mapping[str, Any]) -> PobRelease:
    tag = _tag_token(payload.get("tag"), "cached release tag")
    commit = _full_sha(payload.get("commit"), "cached release commit")
    return PobRelease(
        tag=tag,
        name=_nonempty_string(payload.get("name"), "cached release name"),
        version=_nonempty_string(payload.get("version"), "cached release version"),
        published_at=_aware_datetime(
            payload.get("published_at"),
            "cached release published_at",
        ),
        commit=commit,
        url=f"{POB_RELEASE_URL_BASE}/{tag}",
        commit_url=f"{POB_COMMIT_URL_BASE}/{commit}",
    )


def _compatibility_claims(
    compatibility: CompatibilityEntry | None,
) -> tuple[VersionClaim, ...]:
    if compatibility is None:
        return ()
    # The manifest is the only compatibility authority. Release notes, tag names, and commit
    # messages are deliberately ignored when producing these patch/tree claims.
    return (
        VersionClaim(ClaimDimension.GAME_PATCH, compatibility.game_patch),
        VersionClaim(ClaimDimension.PASSIVE_TREE, compatibility.passive_tree),
    )


def _remote_release_differs_from_local(
    local_commit: str,
    remote_release: PobRelease | None,
) -> bool:
    if remote_release is None:
        return False
    if len(local_commit) < 40:
        return not remote_release.commit.startswith(local_commit)
    return local_commit != remote_release.commit


def _remote_release_supersedes_local(
    local_commit: str,
    remote_release: PobRelease | None,
    compatibility: CompatibilityEntry | None,
) -> bool:
    if not _remote_release_differs_from_local(local_commit, remote_release):
        return False
    if remote_release is None or compatibility is None:
        return True
    # Tagged releases are the normal freshness authority. A certified dev-export candidate is
    # the narrow exception: it may intentionally be ahead of the latest tag until PoB cuts the
    # next release, but a later tagged release will supersede it and force recertification.
    if (
        "pob-dev-export" in compatibility.verified_by
        and compatibility.verified_at > remote_release.published_at
    ):
        return False
    return True


def _pob_records(
    *,
    status: SourceStatus,
    observed_at: datetime,
    source_url: str,
    version: str | None,
    claims: tuple[VersionClaim, ...],
) -> tuple[FreshnessEvidence, ...]:
    return (
        FreshnessEvidence(
            component=Component.POB_ENGINE,
            source="pob",
            source_url=source_url,
            observed_at=observed_at,
            version=version,
            status=status,
            claims=claims,
        ),
        FreshnessEvidence(
            component=Component.POB_DATA,
            source="pob",
            source_url=source_url,
            observed_at=observed_at,
            version=version,
            status=status,
            claims=claims,
        ),
    )


def _evidence_url(remote_release: PobRelease | None) -> str:
    return remote_release.url if remote_release is not None else POB_RELEASE_API_URL


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PobParseError(f"{label} must be a JSON object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise PobParseError(f"{label} must be a JSON array")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PobParseError(f"{label} is missing")
    return " ".join(value.split())


def _optional_string(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return " ".join(value.split())


def _metadata_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    return None


def _optional_commit(value: str | None) -> str | None:
    commit = _optional_string(value)
    return commit.lower() if commit is not None else None


def _tag_token(value: Any, label: str) -> str:
    tag = _nonempty_string(value, label)
    if _SAFE_TAG.fullmatch(tag) is None:
        raise PobParseError(f"{label} is not a safe GitHub tag token")
    return tag


def _full_sha(value: Any, label: str) -> str:
    sha = _nonempty_string(value, f"{label} SHA").lower()
    if len(sha) != 40 or any(character not in string.hexdigits for character in sha):
        raise PobParseError(f"{label} SHA is not a full commit hash")
    return sha


def _aware_datetime(value: Any, label: str) -> datetime:
    text = _nonempty_string(value, label)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PobParseError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PobParseError(f"{label} must be timezone-aware")
    return parsed


def _json_value(body: bytes, label: str) -> Any:
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PobParseError(f"{label} response is not valid JSON: {exc}") from exc


def _successful_response(
    *,
    transport: Transport,
    url: str,
    label: str,
) -> TransportResponse:
    try:
        response = transport(TransportRequest(url=url))
    except TransportError as exc:
        raise PobParseError(f"{label} request failed: {exc}") from exc
    if response.status_code != 200:
        raise PobParseError(f"{label} request returned HTTP {response.status_code}")
    return response


def read_pinned_commit(path: str | Path) -> str | None:
    """Read the development-time PoB pin from pob/PINNED.md if present."""

    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        if _PINNED_COMMIT_LABEL.search(line) is None:
            continue
        match = _PINNED_COMMIT_TOKEN.search(line)
        if match is not None:
            return match.group(1).lower()
    return None


def _local_metadata_with_pinned_fallback(
    *,
    installed: Mapping[str, Any],
    pinned_path: str | Path = DEFAULT_PINNED_PATH,
) -> Mapping[str, Any]:
    metadata = dict(installed)
    if _metadata_string(metadata.get("pob_commit")) is None:
        # Development checkouts may not have installed metadata yet; PINNED.md is the
        # documented local pin source and does not require a runtime PoB git checkout.
        pinned_commit = read_pinned_commit(pinned_path)
        if pinned_commit is not None:
            metadata["pob_commit"] = pinned_commit
    return metadata


def _default_local_metadata() -> Mapping[str, Any]:
    from ..live.update import installed_meta

    return _local_metadata_with_pinned_fallback(installed=installed_meta())


def _duration_ms(started: float, finished: float) -> int:
    return int(max(0.0, finished - started) * 1000)
