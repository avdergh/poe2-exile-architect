from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

import pytest

from server.freshness.cache import (
    CacheEnvelope,
    CacheRunResult,
    FileCacheStore,
    RefreshAttemptThrottle,
    RefreshCoordinator,
    TransportError,
    TransportRequest,
    TransportResponse,
)
from server.freshness.ggg import (
    GGGOfficialTreeProvider,
    GGGPatchProvider,
    PATCH_INDEX_URL,
    PATCH_POLICY,
    TREE_MAIN_COMMIT_API_URL,
    TREE_POLICY,
    parse_official_tree,
    parse_patch_index,
    parse_patch_thread,
    tree_data_commit_api_url,
)
from server.freshness.models import ClaimDimension, Component, SourceStatus
from server.freshness.provider_models import CacheState


FIXTURES = Path(__file__).parent / "fixtures" / "freshness"
NOW = datetime(2026, 6, 23, 8, 30, tzinfo=UTC)
PATCH_THREAD_URL = "https://www.pathofexile.com/forum/view-thread/3973617"
TREE_RELEASE_API_URL = (
    "https://api.github.com/repos/grindinggear/poe2-skilltree-export/releases/latest"
)
TREE_SHA = "1e9eb2d8c1946398c3aaaacfbaead5c75c0d1fa6"
TREE_COMMIT_URL = (
    "https://github.com/grindinggear/poe2-skilltree-export/commit/"
    "1e9eb2d8c1946398c3aaaacfbaead5c75c0d1fa6"
)


def read_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def read_json(name: str) -> Any:
    return json.loads(read_text(name))


class RouteTransport:
    def __init__(self, outcomes: dict[str, TransportResponse | Exception]) -> None:
        self.outcomes = outcomes
        self.requests: list[TransportRequest] = []

    def __call__(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        outcome = self.outcomes[request.url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_patch_envelope(*, checked_at: datetime) -> CacheEnvelope:
    return CacheEnvelope.create(
        source="ggg-patch",
        source_url=PATCH_INDEX_URL,
        fetched_at=checked_at,
        checked_at=checked_at,
        etag=None,
        last_modified=None,
        payload={
            "title": "0.5.3 Hotfix 9",
            "base_patch": "0.5.3",
            "thread_url": PATCH_THREAD_URL,
            "posted_at_raw": "Jun 23, 2026, 2:03:40 PM",
        },
    )


def make_tree_envelope(*, checked_at: datetime) -> CacheEnvelope:
    return CacheEnvelope.create(
        source="ggg-tree",
        source_url=TREE_MAIN_COMMIT_API_URL,
        fetched_at=checked_at,
        checked_at=checked_at,
        etag='"main-etag"',
        last_modified=None,
        payload={
            "league": "Runes of Aldur",
            "tree_series": "0_5",
            "commit": TREE_SHA,
            "main_commit": TREE_SHA,
            "release_url": (
                "https://github.com/grindinggear/poe2-skilltree-export/releases/tag/0.5.2"
            ),
            "commit_url": TREE_COMMIT_URL,
        },
    )


def test_patch_index_selects_first_strict_version_topic_in_document_order():
    patch = parse_patch_index(read_text("ggg-patch-index.html"))

    assert patch.title == "0.5.3 Hotfix 9"
    assert patch.base_patch == "0.5.3"
    assert patch.thread_url == PATCH_THREAD_URL


@pytest.mark.parametrize(
    "title",
    [
        "0.5.3 Hotfix",
        "Patch 0.5.3",
        "0.5.3 Hotfix 9 notes",
        "0.5",
    ],
)
def test_patch_index_rejects_malformed_version_titles(title):
    html = f'<a href="/forum/view-thread/1">{title}</a>'

    with pytest.raises(ValueError, match="version topic"):
        parse_patch_index(html)


def test_patch_thread_validates_title_and_reads_first_staff_post_date():
    thread = parse_patch_thread(
        read_text("ggg-patch-thread.html"),
        expected_title="0.5.3 Hotfix 9",
    )

    assert thread.posted_at_raw == "Jun 23, 2026, 2:03:40 PM"


def test_patch_thread_rejects_mismatched_og_title():
    with pytest.raises(ValueError, match="title"):
        parse_patch_thread(
            read_text("ggg-patch-thread.html"),
            expected_title="0.5.3 Hotfix 8",
        )


def test_patch_thread_ignores_non_staff_post_dates():
    html = """
    <meta property="og:title"
          content="Early Access Patch Notes - 0.5.3 - Forum - Path of Exile">
    <table>
      <tr><td><span class="profile-link post_by_account">Player</span>
          <span class="post_date">wrong</span></td></tr>
      <tr><td><span class="profile-link staff post_by_account">Developer_GGG</span>
          <span class="post_date">Jun 23, 2026, 1:00:00 PM</span></td></tr>
      <tr><td><span class="profile-link staff post_by_account">Other_GGG</span>
          <span class="post_date">later</span></td></tr>
    </table>
    """

    thread = parse_patch_thread(html, expected_title="0.5.3")

    assert thread.posted_at_raw == "Jun 23, 2026, 1:00:00 PM"


def test_official_tree_parses_release_main_and_data_commit():
    tree = parse_official_tree(
        read_json("ggg-tree-release.json"),
        read_json("ggg-tree-commit.json"),
        read_json("ggg-tree-data-commit.json"),
    )

    assert tree.league == "Runes of Aldur"
    assert tree.tree_series == "0_5"
    assert tree.commit == TREE_SHA
    assert tree.main_commit == TREE_SHA
    assert tree.release_url.endswith("/releases/tag/0.5.2")
    assert tree.commit_url == TREE_COMMIT_URL


def test_official_tree_rejects_missing_release_league():
    release = read_json("ggg-tree-release.json")
    release["name"] = "Path of Exile 2"

    with pytest.raises(ValueError, match="league"):
        parse_official_tree(
            release,
            read_json("ggg-tree-commit.json"),
            read_json("ggg-tree-data-commit.json"),
        )


def test_official_tree_rejects_non_version_data_commit_message():
    data_commit = read_json("ggg-tree-data-commit.json")
    data_commit[0]["commit"]["message"] = "Update data.json"

    with pytest.raises(ValueError, match="version"):
        parse_official_tree(
            read_json("ggg-tree-release.json"),
            read_json("ggg-tree-commit.json"),
            data_commit,
        )


def test_official_tree_rejects_non_version_main_commit_message():
    main_commit = read_json("ggg-tree-commit.json")
    main_commit["commit"]["message"] = "Update repository metadata"

    with pytest.raises(ValueError, match="version"):
        parse_official_tree(
            read_json("ggg-tree-release.json"),
            main_commit,
            read_json("ggg-tree-data-commit.json"),
        )


def test_patch_provider_refreshes_and_emits_game_patch_evidence(tmp_path):
    transport = RouteTransport(
        {
            PATCH_INDEX_URL: TransportResponse(
                status_code=200,
                body=read_text("ggg-patch-index.html").encode(),
            ),
            PATCH_THREAD_URL: TransportResponse(
                status_code=200,
                body=read_text("ggg-patch-thread.html").encode(),
            ),
        }
    )
    provider = GGGPatchProvider(
        store=FileCacheStore(tmp_path / "ggg-patch.json"),
        transport=transport,
        attempt_throttle=RefreshAttemptThrottle(),
        refresh_coordinator=RefreshCoordinator(),
    )

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.REFRESHED
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.component is Component.GAME_PATCH
    assert evidence.version == "0.5.3 Hotfix 9"
    assert evidence.status is SourceStatus.CURRENT
    assert [(claim.key, claim.value) for claim in evidence.claims] == [
        (ClaimDimension.GAME_PATCH, "0.5.3")
    ]
    assert [request.url for request in transport.requests] == [
        PATCH_INDEX_URL,
        PATCH_THREAD_URL,
    ]


def test_official_tree_provider_emits_league_and_tree_without_game_patch_claim(tmp_path):
    data_url = tree_data_commit_api_url(TREE_SHA)
    transport = RouteTransport(
        {
            TREE_MAIN_COMMIT_API_URL: TransportResponse(
                status_code=200,
                body=json.dumps(read_json("ggg-tree-commit.json")).encode(),
            ),
            TREE_RELEASE_API_URL: TransportResponse(
                status_code=200,
                body=json.dumps(read_json("ggg-tree-release.json")).encode(),
            ),
            data_url: TransportResponse(
                status_code=200,
                body=json.dumps(read_json("ggg-tree-data-commit.json")).encode(),
            ),
        }
    )
    provider = GGGOfficialTreeProvider(
        store=FileCacheStore(tmp_path / "ggg-tree.json"),
        transport=transport,
        attempt_throttle=RefreshAttemptThrottle(),
        refresh_coordinator=RefreshCoordinator(),
    )

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.REFRESHED
    by_component = {evidence.component: evidence for evidence in result.evidence}
    assert set(by_component) == {Component.LEAGUE, Component.PASSIVE_TREE}
    assert by_component[Component.LEAGUE].version == "Runes of Aldur"
    assert [(claim.key, claim.value) for claim in by_component[Component.LEAGUE].claims] == [
        (ClaimDimension.LEAGUE, "runes-of-aldur")
    ]
    tree = by_component[Component.PASSIVE_TREE]
    assert tree.version == TREE_SHA
    assert [(claim.key, claim.value) for claim in tree.claims] == [
        (ClaimDimension.PASSIVE_TREE, "0_5")
    ]
    assert all(
        claim.key is not ClaimDimension.GAME_PATCH
        for evidence in result.evidence
        for claim in evidence.claims
    )


def test_official_tree_refresh_rechecks_all_composite_sources_after_ttl(tmp_path):
    data_url = tree_data_commit_api_url(TREE_SHA)

    class ConditionalMainTransport(RouteTransport):
        def __call__(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            if request.url == TREE_MAIN_COMMIT_API_URL and request.headers:
                return TransportResponse(status_code=304)
            outcome = self.outcomes[request.url]
            assert isinstance(outcome, TransportResponse)
            return outcome

    transport = ConditionalMainTransport(
        {
            TREE_MAIN_COMMIT_API_URL: TransportResponse(
                status_code=200,
                body=json.dumps(read_json("ggg-tree-commit.json")).encode(),
            ),
            TREE_RELEASE_API_URL: TransportResponse(
                status_code=200,
                body=json.dumps(read_json("ggg-tree-release.json")).encode(),
            ),
            data_url: TransportResponse(
                status_code=200,
                body=json.dumps(read_json("ggg-tree-data-commit.json")).encode(),
            ),
        }
    )
    store = FileCacheStore(tmp_path / "ggg-tree.json")
    store.save(make_tree_envelope(checked_at=NOW - timedelta(hours=2)))
    provider = GGGOfficialTreeProvider(
        store=store,
        transport=transport,
        attempt_throttle=RefreshAttemptThrottle(),
        refresh_coordinator=RefreshCoordinator(),
    )

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.REFRESHED
    assert [request.url for request in transport.requests] == [
        TREE_MAIN_COMMIT_API_URL,
        TREE_RELEASE_API_URL,
        data_url,
    ]
    assert transport.requests[0].headers == {}


@pytest.mark.parametrize(
    ("age", "expected_cache_state", "expected_status"),
    [
        (timedelta(minutes=10), CacheState.FRESH, SourceStatus.CURRENT),
        (timedelta(minutes=20), CacheState.FALLBACK, SourceStatus.CURRENT),
        (timedelta(hours=3), CacheState.FALLBACK, SourceStatus.STALE),
    ],
)
def test_patch_provider_maps_fresh_fallback_and_hard_stale_cache(
    tmp_path,
    age,
    expected_cache_state,
    expected_status,
):
    store = FileCacheStore(tmp_path / "ggg-patch.json")
    store.save(make_patch_envelope(checked_at=NOW - age))
    transport = RouteTransport({PATCH_INDEX_URL: TransportError("offline")})
    provider = GGGPatchProvider(
        store=store,
        transport=transport,
        attempt_throttle=RefreshAttemptThrottle(),
        refresh_coordinator=RefreshCoordinator(),
    )

    result = provider.collect(now=NOW)

    assert result.cache_state is expected_cache_state
    assert result.evidence[0].status is expected_status
    if expected_cache_state is CacheState.FRESH:
        assert transport.requests == []
    else:
        assert len(transport.requests) == 1


def test_patch_provider_maps_missing_cache_failure_to_unknown(tmp_path):
    provider = GGGPatchProvider(
        store=FileCacheStore(tmp_path / "ggg-patch.json"),
        transport=RouteTransport({PATCH_INDEX_URL: TransportError("offline")}),
        attempt_throttle=RefreshAttemptThrottle(),
        refresh_coordinator=RefreshCoordinator(),
    )

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.MISSING
    assert len(result.evidence) == 1
    assert result.evidence[0].component is Component.GAME_PATCH
    assert result.evidence[0].status is SourceStatus.UNKNOWN
    assert result.evidence[0].version is None
    assert result.evidence[0].claims == ()


def test_provider_injects_cache_transport_store_throttle_and_coordinator(tmp_path):
    store = FileCacheStore(tmp_path / "ggg-patch.json")
    transport = RouteTransport({})
    throttle = RefreshAttemptThrottle()
    coordinator = RefreshCoordinator()
    captured: dict[str, Any] = {}

    def cache_runner(**kwargs):
        captured.update(kwargs)
        return CacheRunResult(
            envelope=make_patch_envelope(checked_at=NOW),
            cache_state=CacheState.FRESH,
            hard_stale=False,
            diagnostics=(),
        )

    provider = GGGPatchProvider(
        store=store,
        transport=transport,
        attempt_throttle=throttle,
        refresh_coordinator=coordinator,
        cache_runner=cache_runner,
    )

    provider.collect(now=NOW)

    assert captured["store"] is store
    assert captured["transport"] is transport
    assert captured["attempt_throttle"] is throttle
    assert captured["refresh_coordinator"] is coordinator
    assert captured["policy"] is PATCH_POLICY
    assert TREE_POLICY.refresh_after == timedelta(hours=1)
    assert TREE_POLICY.reject_after == timedelta(hours=6)
