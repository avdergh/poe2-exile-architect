"""poe.ninja popularity-snapshot freshness provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import re
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
from .provider_models import CachePolicy, CacheState, ProviderResult


NINJA_INDEX_URL = "https://poe.ninja/poe2/api/data/index-state"
NINJA_BUILD_INDEX_URL = "https://poe.ninja/poe2/api/data/build-index-state"
NINJA_INDEX_SOURCE = "poe-ninja-index"
NINJA_BUILD_INDEX_SOURCE = "poe-ninja-build-index"
NINJA_POLICY = CachePolicy(
    refresh_after=timedelta(minutes=30),
    reject_after=timedelta(hours=2),
)

_VERSION = re.compile(r"^\d{4}-(\d{8})-\d{5}$")
_PASSIVE_TREE = re.compile(r"^PassiveTree-(\d+)\.(\d+)$")
_LEAGUE_URL = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PRIVATE_NAME = re.compile(r"PL\d+", re.IGNORECASE)
_PRIVATE_URL = re.compile(r"pl\d+", re.IGNORECASE)
_EXCLUDED_TOKENS = {"HC", "SSF", "RUTHLESS", "STANDARD"}


class NinjaParseError(PayloadParseError, ValueError):
    """An expected poe.ninja response-shape or selection failure."""


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
class NinjaSnapshot:
    league: str
    league_url: str
    version: str
    snapshot_date: date
    passive_tree: str
    passive_tree_claim: str
    sample_size: int


@dataclass(frozen=True, slots=True)
class _SnapshotEntry:
    version: str
    snapshot_date: date
    passive_tree: str
    passive_tree_claim: str


@dataclass(frozen=True, slots=True)
class _SelectableLeague:
    name: str
    url: str


def parse_ninja_snapshot(index_json: Any, build_index_json: Any) -> NinjaSnapshot:
    """Select the newest current softcore trade snapshot from poe.ninja indexes."""

    index = _mapping(index_json, "index")
    build_index = _mapping(build_index_json, "build index")
    leagues = _sequence(index.get("buildLeagues"), "buildLeagues")
    old_urls = _old_build_league_urls(index)
    snapshots = _sequence(index.get("snapshotVersions"), "snapshotVersions")
    league_builds = _sequence(build_index.get("leagueBuilds"), "leagueBuilds")

    selectable_leagues: list[_SelectableLeague] = []
    for raw_league in leagues:
        league = _mapping(raw_league, "build league")
        league_name = _league_name(league)
        display_name = _optional_string(league.get("displayName"))
        league_url = _league_url_token(league.get("url"), "build league URL")

        # Exclusion rules intentionally run before parsing snapshots so HC/SSF/Ruthless,
        # Standard, private-league, and old-league rows cannot win merely by having
        # newer or remaining versions.
        if league_url in old_urls:
            continue
        if _is_excluded_league(
            name=league_name,
            display_name=display_name,
            url=league_url,
            hardcore=league.get("hardcore"),
        ):
            continue

        selectable_leagues.append(_SelectableLeague(name=league_name, url=league_url))

    selectable_urls = {league.url for league in selectable_leagues}
    snapshots_by_url: dict[str, list[_SnapshotEntry]] = {}
    for raw_snapshot in snapshots:
        snapshot = _mapping(raw_snapshot, "snapshot")
        raw_url = _url_lookup_key(snapshot.get("url"))
        if raw_url not in selectable_urls:
            continue
        url = _league_url_token(snapshot.get("url"), "snapshot URL")
        snapshots_by_url.setdefault(url, []).append(_snapshot_entry(snapshot))

    builds_by_url: dict[str, Mapping[str, Any]] = {}
    for raw_build in league_builds:
        build = _mapping(raw_build, "league build")
        raw_url = _url_lookup_key(build.get("leagueUrl"))
        if raw_url not in selectable_urls:
            continue
        url = _league_url_token(build.get("leagueUrl"), "league build URL")
        builds_by_url.setdefault(url, build)

    if not selectable_leagues:
        raise NinjaParseError("index contains no selectable current league")

    # Stage 1: choose the newest selectable league/date using league descriptors and
    # snapshot metadata only. Build/sample validation happens after selection so an
    # incomplete current league cannot silently fall back to a historical league.
    dated_candidates: list[tuple[_SelectableLeague, _SnapshotEntry]] = []
    for selectable_league in selectable_leagues:
        entries = snapshots_by_url.get(selectable_league.url)
        if not entries:
            continue
        dated_candidates.append(
            (
                selectable_league,
                max(entries, key=lambda entry: (entry.snapshot_date, entry.version)),
            )
        )

    if not dated_candidates:
        raise NinjaParseError("snapshot is missing for selectable league")

    newest_date = max(entry.snapshot_date for _, entry in dated_candidates)
    newest = [
        (league, entry) for league, entry in dated_candidates if entry.snapshot_date == newest_date
    ]
    newest_names = {league.name.casefold() for league, _ in newest}
    if len(newest_names) > 1:
        raise NinjaParseError("ambiguous newest poe.ninja league candidates")
    selected_league, selected_entry = max(
        newest,
        key=lambda candidate: (candidate[1].version, candidate[0].url),
    )

    # Stage 2: strictly validate the selected latest league. Missing build/sample
    # data is a provider parse failure, not permission to emit an older snapshot.
    selected_entries = snapshots_by_url[selected_league.url]
    _reject_tree_mismatch(
        league_url=selected_league.url,
        entries=selected_entries,
        snapshot_date=selected_entry.snapshot_date,
    )
    current_build = builds_by_url.get(selected_league.url)
    if current_build is None:
        raise NinjaParseError("build sample count is missing for selectable league")
    sample_size = _positive_int(current_build.get("total"), "sample size")
    if sample_size <= 0:
        raise NinjaParseError("sample size is zero or missing for selectable league")
    return NinjaSnapshot(
        league=selected_league.name,
        league_url=selected_league.url,
        version=selected_entry.version,
        snapshot_date=selected_entry.snapshot_date,
        passive_tree=selected_entry.passive_tree,
        passive_tree_claim=selected_entry.passive_tree_claim,
        sample_size=sample_size,
    )


def _snapshot_entry(snapshot: Mapping[str, Any]) -> _SnapshotEntry:
    version = _nonempty_string(snapshot.get("version"), "snapshot version")
    # Version date parse is strict: poe.ninja's middle YYYYMMDD segment is the
    # UTC snapshot day used for newest-candidate selection.
    snapshot_date = _snapshot_date(version)
    passive_tree = _nonempty_string(snapshot.get("passiveTree"), "passive tree")
    passive_tree_claim = _passive_tree_claim(passive_tree)
    return _SnapshotEntry(
        version=version,
        snapshot_date=snapshot_date,
        passive_tree=passive_tree,
        passive_tree_claim=passive_tree_claim,
    )


def _old_build_league_urls(index: Mapping[str, Any]) -> set[str]:
    if "oldBuildLeagues" not in index:
        return set()
    old_leagues = _sequence(index.get("oldBuildLeagues"), "oldBuildLeagues")
    old_urls: set[str] = set()
    for raw_league in old_leagues:
        league = _mapping(raw_league, "old build league")
        try:
            old_urls.add(_league_url_token(league.get("url"), "old build league URL"))
        except NinjaParseError:
            continue
    return old_urls


def _reject_tree_mismatch(
    *,
    league_url: str,
    entries: Sequence[_SnapshotEntry],
    snapshot_date: date,
) -> None:
    claims_by_date: dict[date, set[str]] = {}
    for entry in entries:
        if entry.snapshot_date != snapshot_date:
            continue
        claims_by_date.setdefault(entry.snapshot_date, set()).add(entry.passive_tree_claim)
    for claims in claims_by_date.values():
        if len(claims) > 1:
            raise NinjaParseError(f"passive tree mismatch for league {league_url}")


def _index_payload(index: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "buildLeagues": list(_sequence(index.get("buildLeagues"), "buildLeagues")),
        "oldBuildLeagues": list(_sequence(index.get("oldBuildLeagues", []), "oldBuildLeagues")),
        "snapshotVersions": list(_sequence(index.get("snapshotVersions"), "snapshotVersions")),
    }


def _build_index_payload(build_index: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "leagueBuilds": list(_sequence(build_index.get("leagueBuilds"), "leagueBuilds")),
    }


def _index_from_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    # Cache payload revalidation: cached compact API facts are still untrusted, so replay
    # the same structural checks before combining index-state with build-index-state.
    return _index_payload(payload)


def _build_index_from_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return _build_index_payload(payload)


def _league_name(league: Mapping[str, Any]) -> str:
    name = league.get("name")
    if isinstance(name, str) and name.strip():
        return " ".join(name.split())
    return _nonempty_string(league.get("displayName"), "league name")


def _is_excluded_league(
    *,
    name: str,
    display_name: str | None,
    url: str,
    hardcore: Any,
) -> bool:
    if hardcore is True:
        return True
    names = " ".join(part for part in (name, display_name or "") if part)
    if _PRIVATE_NAME.search(names) or _PRIVATE_URL.search(url):
        return True
    token_text = f"{names} {url.replace('-', ' ')}"
    tokens = {token.upper() for token in re.findall(r"[A-Za-z0-9]+", token_text)}
    return bool(tokens & _EXCLUDED_TOKENS)


def _snapshot_date(version: str) -> date:
    match = _VERSION.fullmatch(version)
    if match is None:
        raise NinjaParseError("snapshot version has unexpected format")
    raw_date = match.group(1)
    try:
        return date(
            int(raw_date[0:4]),
            int(raw_date[4:6]),
            int(raw_date[6:8]),
        )
    except ValueError as exc:
        raise NinjaParseError("snapshot version date is invalid") from exc


def _passive_tree_claim(value: str) -> str:
    match = _PASSIVE_TREE.fullmatch(value)
    if match is None:
        raise NinjaParseError("passive tree token has unexpected format")
    return f"{match.group(1)}_{match.group(2)}"


def _league_url_token(value: Any, label: str) -> str:
    url = _nonempty_string(value, label).casefold()
    if _LEAGUE_URL.fullmatch(url) is None:
        raise NinjaParseError(f"{label} is not a canonical league URL token")
    return url


def _url_lookup_key(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(value.split()).casefold()


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise NinjaParseError(f"{label} is missing")
    if value < 0:
        raise NinjaParseError(f"{label} is negative")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NinjaParseError(f"{label} response must be a JSON object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise NinjaParseError(f"{label} response must be a JSON array")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NinjaParseError(f"{label} is missing")
    return " ".join(value.split())


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    return None


def _json_value(body: bytes, label: str) -> Any:
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NinjaParseError(f"{label} response is not valid JSON: {exc}") from exc


def _successful_response(
    *,
    transport: Transport,
    url: str,
    label: str,
) -> TransportResponse:
    try:
        response = transport(TransportRequest(url=url))
    except TransportError as exc:
        raise NinjaParseError(f"{label} request failed: {exc}") from exc
    if response.status_code != 200:
        raise NinjaParseError(f"{label} request returned HTTP {response.status_code}")
    return response


class NinjaSnapshotProvider:
    name = "poe-ninja"
    policy = NINJA_POLICY

    def __init__(
        self,
        *,
        index_store: FileCacheStore,
        build_index_store: FileCacheStore,
        transport: Transport,
        attempt_throttle: RefreshAttemptThrottle,
        refresh_coordinator: RefreshCoordinator,
        cache_runner: CacheRunner = run_cached,
        timer: Callable[[], float] = monotonic,
    ) -> None:
        self._index_store = index_store
        self._build_index_store = build_index_store
        self._transport = transport
        self._attempt_throttle = attempt_throttle
        self._refresh_coordinator = refresh_coordinator
        self._cache_runner = cache_runner
        self._timer = timer

    def collect(
        self,
        *,
        now: datetime,
        force_refresh: bool = False,
    ) -> ProviderResult:
        started = self._timer()
        index_result = self._cache_runner(
            source=NINJA_INDEX_SOURCE,
            source_url=NINJA_INDEX_URL,
            now=now,
            policy=self.policy,
            store=self._index_store,
            transport=self._transport,
            parse=self._parse_index_refresh,
            attempt_throttle=self._attempt_throttle,
            refresh_coordinator=self._refresh_coordinator,
            force_refresh=force_refresh,
        )
        build_index_result = self._cache_runner(
            source=NINJA_BUILD_INDEX_SOURCE,
            source_url=NINJA_BUILD_INDEX_URL,
            now=now,
            policy=self.policy,
            store=self._build_index_store,
            transport=self._transport,
            parse=self._parse_build_index_refresh,
            attempt_throttle=self._attempt_throttle,
            refresh_coordinator=self._refresh_coordinator,
            force_refresh=force_refresh,
        )
        evidence, diagnostics = self._shape_evidence(
            index_result,
            build_index_result,
            now=now,
        )
        return ProviderResult(
            source=self.name,
            evidence=evidence,
            cache_state=_combined_cache_state(
                index_result.cache_state, build_index_result.cache_state
            ),
            diagnostics=diagnostics,
            duration_ms=_duration_ms(started, self._timer()),
        )

    def _parse_index_refresh(self, body: bytes) -> Mapping[str, Any]:
        index_json = _json_value(body, "index")
        return _index_payload(_mapping(index_json, "index"))

    def _parse_build_index_refresh(self, body: bytes) -> Mapping[str, Any]:
        build_index_json = _json_value(body, "build index")
        return _build_index_payload(_mapping(build_index_json, "build index"))

    def _shape_evidence(
        self,
        index_result: CacheRunResult,
        build_index_result: CacheRunResult,
        *,
        now: datetime,
    ) -> tuple[tuple[FreshnessEvidence, ...], tuple[str, ...]]:
        diagnostics = [
            *[f"index: {diagnostic}" for diagnostic in index_result.diagnostics],
            *[f"build-index: {diagnostic}" for diagnostic in build_index_result.diagnostics],
        ]
        if index_result.envelope is None or build_index_result.envelope is None:
            return self._unknown_evidence(now), tuple(diagnostics)
        try:
            snapshot = parse_ninja_snapshot(
                _index_from_payload(index_result.envelope.payload),
                _build_index_from_payload(build_index_result.envelope.payload),
            )
        except NinjaParseError as exc:
            diagnostics.append(f"cached payload invalid: {exc}")
            return self._unknown_evidence(now), tuple(diagnostics)

        diagnostics.append(f"sample_size={snapshot.sample_size}")
        diagnostics.append(f"snapshot_date={snapshot.snapshot_date.isoformat()}")
        status = (
            SourceStatus.STALE
            if index_result.hard_stale or build_index_result.hard_stale
            else SourceStatus.CURRENT
        )
        observed_at = min(
            index_result.envelope.checked_at,
            build_index_result.envelope.checked_at,
        )
        return (
            (
                FreshnessEvidence(
                    component=Component.META_SNAPSHOT,
                    source=self.name,
                    source_url=f"https://poe.ninja/poe2/builds/{snapshot.league_url}",
                    observed_at=observed_at,
                    version=snapshot.version,
                    status=status,
                    claims=(
                        VersionClaim(ClaimDimension.LEAGUE, snapshot.league),
                        VersionClaim(
                            ClaimDimension.PASSIVE_TREE,
                            snapshot.passive_tree_claim,
                        ),
                    ),
                ),
            ),
            tuple(diagnostics),
        )

    def _unknown_evidence(self, observed_at: datetime) -> tuple[FreshnessEvidence, ...]:
        return (
            FreshnessEvidence(
                component=Component.META_SNAPSHOT,
                source=self.name,
                source_url=NINJA_INDEX_URL,
                observed_at=observed_at,
                version=None,
                status=SourceStatus.UNKNOWN,
            ),
        )


def _duration_ms(started: float, finished: float) -> int:
    return int(max(0.0, finished - started) * 1000)


def _combined_cache_state(first: CacheState, second: CacheState) -> CacheState:
    priority = {
        CacheState.MISSING: 5,
        CacheState.FALLBACK: 4,
        CacheState.REFRESHED: 3,
        CacheState.REVALIDATED: 2,
        CacheState.FRESH: 1,
    }
    return first if priority[first] >= priority[second] else second
