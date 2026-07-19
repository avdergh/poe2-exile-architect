"""GGG patch-forum and official passive-tree freshness providers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
import json
import re
import string
from time import monotonic
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

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


GGG_BASE_URL = "https://www.pathofexile.com"
PATCH_INDEX_URL = f"{GGG_BASE_URL}/forum/view-forum/2212"
TREE_REPOSITORY = "grindinggear/poe2-skilltree-export"
TREE_API_BASE_URL = f"https://api.github.com/repos/{TREE_REPOSITORY}"
TREE_RELEASE_API_URL = f"{TREE_API_BASE_URL}/releases/latest"
TREE_MAIN_COMMIT_API_URL = f"{TREE_API_BASE_URL}/commits/main"
TREE_COMMITS_API_URL = f"{TREE_API_BASE_URL}/commits"

PATCH_POLICY = CachePolicy(
    refresh_after=timedelta(minutes=15),
    reject_after=timedelta(hours=2),
)
TREE_POLICY = CachePolicy(
    refresh_after=timedelta(hours=1),
    reject_after=timedelta(days=7),
)

_PATCH_TITLE = re.compile(r"^(\d+\.\d+\.\d+)(?: Hotfix \d+)?$")
_THREAD_PATH = re.compile(r"^/forum/view-thread/(\d+)$")
_TREE_SERIES = re.compile(r"^\d+_\d+$")
_THREAD_TITLE_PREFIX = "Early Access Patch Notes - "
_THREAD_TITLE_SUFFIX = " - Forum - Path of Exile"
_RELEASE_NAME_PREFIX = "Path of Exile 2:"


class GGGParseError(PayloadParseError, ValueError):
    """An expected GGG or GitHub response-shape failure."""


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


class _UnconditionalTransport:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def __call__(self, request: TransportRequest) -> TransportResponse:
        # A 304 for one endpoint cannot prove that the other endpoints in a composite payload
        # are unchanged, so TTL refreshes deliberately re-read the primary response body.
        return self._transport(TransportRequest(url=request.url))


@dataclass(frozen=True, slots=True)
class PatchTopic:
    title: str
    base_patch: str
    thread_url: str


@dataclass(frozen=True, slots=True)
class PatchThread:
    posted_at_raw: str


@dataclass(frozen=True, slots=True)
class OfficialTree:
    league: str
    tree_series: str
    commit: str
    main_commit: str
    release_tag: str
    release_url: str
    commit_url: str


class _PatchIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._active_href: str | None = None
        self._active_text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag != "a" or self._active_href is not None:
            return
        href = _attribute(attrs, "href")
        if href is None or "/forum/view-thread/" not in href:
            return
        self._active_href = href
        self._active_text = []

    def handle_data(self, data: str) -> None:
        if self._active_href is not None:
            self._active_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._active_href is None:
            return
        title = " ".join("".join(self._active_text).split())
        self.links.append((self._active_href, title))
        self._active_href = None
        self._active_text = []


class _PatchThreadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og_title: str | None = None
        self.first_staff_post_date: str | None = None
        self._staff_seen_in_post = False
        self._collecting_date = False
        self._date_text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "meta" and _attribute(attrs, "property") == "og:title":
            self.og_title = _attribute(attrs, "content")
            return
        if tag == "tr":
            self._staff_seen_in_post = False
            self._collecting_date = False
            self._date_text = []
            return
        if tag != "span":
            return
        classes = set((_attribute(attrs, "class") or "").split())
        if {"profile-link", "staff"}.issubset(classes):
            self._staff_seen_in_post = True
        if (
            "post_date" in classes
            and self._staff_seen_in_post
            and self.first_staff_post_date is None
        ):
            self._collecting_date = True
            self._date_text = []

    def handle_data(self, data: str) -> None:
        if self._collecting_date:
            self._date_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._collecting_date:
            posted_at = " ".join("".join(self._date_text).split())
            if posted_at:
                self.first_staff_post_date = posted_at
            self._collecting_date = False
            self._date_text = []
        elif tag == "tr":
            self._staff_seen_in_post = False


def _attribute(attrs: Sequence[tuple[str, str | None]], name: str) -> str | None:
    for key, value in attrs:
        if key == name:
            return value
    return None


def parse_patch_index(html: str) -> PatchTopic:
    """Select the first strict version topic in source document order."""

    parser = _PatchIndexParser()
    parser.feed(html)
    parser.close()
    for href, title in parser.links:
        match = _PATCH_TITLE.fullmatch(title)
        if match is not None:
            return PatchTopic(
                title=title,
                base_patch=match.group(1),
                thread_url=_canonical_thread_url(href),
            )
    raise GGGParseError("patch index contains no strict version topic")


def parse_patch_thread(html: str, *, expected_title: str) -> PatchThread:
    """Validate the canonical Open Graph title and read the first staff post date."""

    parser = _PatchThreadParser()
    parser.feed(html)
    parser.close()
    wanted_title = f"{_THREAD_TITLE_PREFIX}{expected_title}{_THREAD_TITLE_SUFFIX}"
    if parser.og_title != wanted_title:
        raise GGGParseError("patch thread title does not match the index title")
    if parser.first_staff_post_date is None:
        raise GGGParseError("patch thread contains no GGG staff post date")
    return PatchThread(posted_at_raw=parser.first_staff_post_date)


def parse_official_tree(
    release_json: Any,
    main_commit_json: Any,
    data_commit_json: Any,
) -> OfficialTree:
    """Parse official release and commit facts without claiming a game patch."""

    release = _mapping(release_json, "release")
    main_commit = _mapping(main_commit_json, "main commit")
    data_commits = _sequence(data_commit_json, "data.json commits")
    if not data_commits:
        raise GGGParseError("data.json commits response is empty")
    data_commit = _mapping(data_commits[0], "data.json commit")

    release_name = _nonempty_string(release.get("name"), "release league")
    if not release_name.startswith(_RELEASE_NAME_PREFIX):
        raise GGGParseError("release league name has an unexpected format")
    league = release_name.removeprefix(_RELEASE_NAME_PREFIX).strip()
    if not league:
        raise GGGParseError("release league is missing")

    release_tag = _nonempty_string(release.get("tag_name"), "release tag")
    release_version = _three_part_version(release_tag, "release tag")
    data_version = _commit_version(data_commit, "data.json commit") or release_version
    data_sha = _full_sha(data_commit.get("sha"), "data.json commit")
    main_sha = _full_sha(main_commit.get("sha"), "main commit")

    return OfficialTree(
        league=league,
        tree_series=f"{data_version[0]}_{data_version[1]}",
        commit=data_sha,
        main_commit=main_sha,
        release_tag=release_tag,
        # Evidence URLs are reconstructed from validated official facts rather than
        # trusting unstructured html_url fields returned by an external API payload.
        release_url=_canonical_tree_release_url(release_tag),
        commit_url=_canonical_tree_commit_url(data_sha),
    )


def tree_data_commit_api_url(main_sha: str) -> str:
    """Pin the path query to the observed main SHA so GitHub proves ancestry."""

    return (
        f"{TREE_COMMITS_API_URL}?{urlencode({'path': 'data.json', 'sha': main_sha, 'per_page': 1})}"
    )


def _canonical_thread_url(href: str) -> str:
    parsed = urlsplit(href.strip())
    if parsed.scheme or parsed.netloc:
        if parsed.scheme != "https" or parsed.netloc not in {
            "pathofexile.com",
            "www.pathofexile.com",
        }:
            raise GGGParseError("patch thread URL is not an official thread")
    if parsed.query or parsed.fragment:
        raise GGGParseError("patch thread URL must not contain query or fragment")

    match = _THREAD_PATH.fullmatch(parsed.path)
    if match is None:
        raise GGGParseError("patch thread URL path is not canonical")
    return f"{GGG_BASE_URL}/forum/view-thread/{match.group(1)}"


def _canonical_tree_release_url(release_tag: str) -> str:
    # _three_part_version has already restricted the tag to a semver-like token,
    # so interpolating it cannot smuggle a different GitHub path or host.
    return f"https://github.com/{TREE_REPOSITORY}/releases/tag/{release_tag}"


def _canonical_tree_commit_url(commit_sha: str) -> str:
    return f"https://github.com/{TREE_REPOSITORY}/commit/{commit_sha}"


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GGGParseError(f"{label} response must be a JSON object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise GGGParseError(f"{label} response must be a JSON array")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GGGParseError(f"{label} is missing")
    return value.strip()


def _commit_message(commit: Mapping[str, Any], label: str) -> str:
    details = _mapping(commit.get("commit"), f"{label} details")
    message = _nonempty_string(details.get("message"), f"{label} message")
    return message.splitlines()[0].strip()


def _commit_version(
    commit: Mapping[str, Any],
    label: str,
) -> tuple[str, str, str] | None:
    message = _commit_message(commit, label)
    try:
        return _three_part_version(message, f"{label} version")
    except GGGParseError:
        return None


def _three_part_version(value: str, label: str) -> tuple[str, str, str]:
    parts = value.strip().removeprefix("v").split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise GGGParseError(f"{label} is not a three-part version")
    return parts[0], parts[1], parts[2]


def _full_sha(value: Any, label: str) -> str:
    sha = _nonempty_string(value, f"{label} SHA").lower()
    if len(sha) != 40 or any(character not in string.hexdigits for character in sha):
        raise GGGParseError(f"{label} SHA is not a full commit hash")
    return sha


def _json_value(body: bytes, label: str) -> Any:
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GGGParseError(f"{label} response is not valid JSON: {exc}") from exc


def _successful_response(
    *,
    transport: Transport,
    url: str,
    label: str,
) -> TransportResponse:
    try:
        response = transport(TransportRequest(url=url))
    except TransportError as exc:
        # Nested requests run inside the cache parser, so normalize them into parser failures
        # that the shared cache runner can safely degrade to fallback.
        raise GGGParseError(f"{label} request failed: {exc}") from exc
    if response.status_code != 200:
        raise GGGParseError(f"{label} request returned HTTP {response.status_code}")
    return response


def _patch_from_payload(payload: Mapping[str, Any]) -> tuple[PatchTopic, PatchThread]:
    title = _nonempty_string(payload.get("title"), "cached patch title")
    title_match = _PATCH_TITLE.fullmatch(title)
    if title_match is None:
        raise GGGParseError("cached patch title is not a strict version topic")
    topic = PatchTopic(
        title=title,
        base_patch=title_match.group(1),
        thread_url=_canonical_thread_url(
            _nonempty_string(payload.get("thread_url"), "cached patch thread URL")
        ),
    )
    thread = PatchThread(
        posted_at_raw=_nonempty_string(payload.get("posted_at_raw"), "cached staff post date")
    )
    return topic, thread


def _tree_from_payload(payload: Mapping[str, Any]) -> OfficialTree:
    release_tag = _nonempty_string(payload.get("release_tag"), "cached release tag")
    _three_part_version(release_tag, "cached release tag")
    tree_series = _nonempty_string(payload.get("tree_series"), "cached tree series")
    if _TREE_SERIES.fullmatch(tree_series) is None:
        raise GGGParseError("cached tree series is not a major_minor token")
    commit = _full_sha(payload.get("commit"), "cached data.json commit")
    main_commit = _full_sha(payload.get("main_commit"), "cached main commit")
    return OfficialTree(
        league=_nonempty_string(payload.get("league"), "cached league"),
        tree_series=tree_series,
        commit=commit,
        main_commit=main_commit,
        release_tag=release_tag,
        release_url=_canonical_tree_release_url(release_tag),
        commit_url=_canonical_tree_commit_url(commit),
    )


class GGGPatchProvider:
    name = "ggg-patch"
    policy = PATCH_POLICY

    def __init__(
        self,
        *,
        store: FileCacheStore,
        transport: Transport,
        attempt_throttle: RefreshAttemptThrottle,
        refresh_coordinator: RefreshCoordinator,
        cache_runner: CacheRunner = run_cached,
        timer: Callable[[], float] = monotonic,
    ) -> None:
        self._store = store
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
        cache_result = self._cache_runner(
            source=self.name,
            source_url=PATCH_INDEX_URL,
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
        topic = parse_patch_index(body.decode("utf-8"))
        # The index is the conditional cache source. Only a changed index needs a thread fetch,
        # and the cached payload stores facts rather than copyrighted page HTML.
        response = _successful_response(
            transport=self._transport,
            url=topic.thread_url,
            label="patch thread",
        )
        thread = parse_patch_thread(
            response.body.decode("utf-8"),
            expected_title=topic.title,
        )
        return {
            "title": topic.title,
            "base_patch": topic.base_patch,
            "thread_url": topic.thread_url,
            "posted_at_raw": thread.posted_at_raw,
        }

    def _shape_evidence(
        self,
        cache_result: CacheRunResult,
        *,
        now: datetime,
    ) -> tuple[tuple[FreshnessEvidence, ...], tuple[str, ...]]:
        diagnostics = list(cache_result.diagnostics)
        if cache_result.envelope is None:
            return (
                (
                    FreshnessEvidence(
                        component=Component.GAME_PATCH,
                        source=self.name,
                        source_url=PATCH_INDEX_URL,
                        observed_at=now,
                        version=None,
                        status=SourceStatus.UNKNOWN,
                    ),
                ),
                tuple(diagnostics),
            )
        try:
            topic, _thread = _patch_from_payload(cache_result.envelope.payload)
        except GGGParseError as exc:
            diagnostics.append(f"cached payload invalid: {exc}")
            return (
                (
                    FreshnessEvidence(
                        component=Component.GAME_PATCH,
                        source=self.name,
                        source_url=PATCH_INDEX_URL,
                        observed_at=now,
                        version=None,
                        status=SourceStatus.UNKNOWN,
                    ),
                ),
                tuple(diagnostics),
            )
        status = SourceStatus.STALE if cache_result.hard_stale else SourceStatus.CURRENT
        return (
            (
                FreshnessEvidence(
                    component=Component.GAME_PATCH,
                    source=self.name,
                    source_url=topic.thread_url,
                    observed_at=cache_result.envelope.checked_at,
                    version=topic.title,
                    status=status,
                    claims=(VersionClaim(ClaimDimension.GAME_PATCH, topic.base_patch),),
                ),
            ),
            tuple(diagnostics),
        )


class GGGOfficialTreeProvider:
    name = "ggg-tree"
    policy = TREE_POLICY

    def __init__(
        self,
        *,
        store: FileCacheStore,
        transport: Transport,
        attempt_throttle: RefreshAttemptThrottle,
        refresh_coordinator: RefreshCoordinator,
        cache_runner: CacheRunner = run_cached,
        timer: Callable[[], float] = monotonic,
    ) -> None:
        self._store = store
        self._transport = transport
        self._cache_transport = _UnconditionalTransport(transport)
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
        cache_result = self._cache_runner(
            source=self.name,
            source_url=TREE_MAIN_COMMIT_API_URL,
            now=now,
            policy=self.policy,
            store=self._store,
            transport=self._cache_transport,
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
        main_commit = _mapping(_json_value(body, "main commit"), "main commit")
        main_sha = _full_sha(main_commit.get("sha"), "main commit")
        release_response = _successful_response(
            transport=self._transport,
            url=TREE_RELEASE_API_URL,
            label="tree release",
        )
        # Supplying sha=<observed main> makes GitHub select the latest data.json commit in that
        # exact history, instead of accidentally accepting a commit from an old release branch.
        data_response = _successful_response(
            transport=self._transport,
            url=tree_data_commit_api_url(main_sha),
            label="data.json commit",
        )
        tree = parse_official_tree(
            _json_value(release_response.body, "tree release"),
            main_commit,
            _json_value(data_response.body, "data.json commit"),
        )
        return {
            "league": tree.league,
            "tree_series": tree.tree_series,
            "commit": tree.commit,
            "main_commit": tree.main_commit,
            "release_tag": tree.release_tag,
            "release_url": tree.release_url,
            "commit_url": tree.commit_url,
        }

    def _shape_evidence(
        self,
        cache_result: CacheRunResult,
        *,
        now: datetime,
    ) -> tuple[tuple[FreshnessEvidence, ...], tuple[str, ...]]:
        diagnostics = list(cache_result.diagnostics)
        if cache_result.envelope is None:
            return self._unknown_evidence(now), tuple(diagnostics)
        try:
            tree = _tree_from_payload(cache_result.envelope.payload)
        except GGGParseError as exc:
            diagnostics.append(f"cached payload invalid: {exc}")
            return self._unknown_evidence(now), tuple(diagnostics)
        status = SourceStatus.STALE if cache_result.hard_stale else SourceStatus.CURRENT
        observed_at = cache_result.envelope.checked_at
        return (
            (
                FreshnessEvidence(
                    component=Component.LEAGUE,
                    source=self.name,
                    source_url=tree.release_url,
                    observed_at=observed_at,
                    version=tree.league,
                    status=status,
                    claims=(VersionClaim(ClaimDimension.LEAGUE, tree.league),),
                ),
                FreshnessEvidence(
                    component=Component.PASSIVE_TREE,
                    source=self.name,
                    source_url=tree.commit_url,
                    observed_at=observed_at,
                    version=tree.commit,
                    status=status,
                    claims=(VersionClaim(ClaimDimension.PASSIVE_TREE, tree.tree_series),),
                ),
            ),
            tuple(diagnostics),
        )

    def _unknown_evidence(self, observed_at: datetime) -> tuple[FreshnessEvidence, ...]:
        return (
            FreshnessEvidence(
                component=Component.LEAGUE,
                source=self.name,
                source_url=TREE_RELEASE_API_URL,
                observed_at=observed_at,
                version=None,
                status=SourceStatus.UNKNOWN,
            ),
            FreshnessEvidence(
                component=Component.PASSIVE_TREE,
                source=self.name,
                source_url=TREE_MAIN_COMMIT_API_URL,
                observed_at=observed_at,
                version=None,
                status=SourceStatus.UNKNOWN,
            ),
        )


def _duration_ms(started: float, finished: float) -> int:
    return int(max(0.0, finished - started) * 1000)
