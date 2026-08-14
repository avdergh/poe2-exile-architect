from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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
from server.freshness.models import ClaimDimension, Component, SourceStatus
from server.freshness.ninja import (
    NINJA_BUILD_INDEX_URL,
    NINJA_INDEX_URL,
    NINJA_POLICY,
    NinjaParseError,
    NinjaSnapshotProvider,
    parse_ninja_snapshot,
)
from server.freshness.provider_models import CacheState


FIXTURES = Path(__file__).parent / "fixtures" / "freshness"
NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
NINJA_BUILD_URL = "https://poe.ninja/poe2/builds/runesofaldur"


def read_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def read_json(name: str) -> Any:
    return json.loads(read_text(name))


def snapshot_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    return read_json("ninja-index.json"), read_json("ninja-build-index.json")


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


def make_ninja_envelope(*, checked_at: datetime) -> CacheEnvelope:
    return CacheEnvelope.create(
        source="poe-ninja",
        source_url=NINJA_INDEX_URL,
        fetched_at=checked_at,
        checked_at=checked_at,
        etag=None,
        last_modified=None,
        payload={
            "league": "Runes of Aldur",
            "league_url": "runesofaldur",
            "version": "0137-20260624-38624",
            "passive_tree": "PassiveTree-0.5",
            "sample_size": 124302,
        },
    )


def make_ninja_index_envelope(*, checked_at: datetime) -> CacheEnvelope:
    index_json, _build_index_json = snapshot_fixture()
    return CacheEnvelope.create(
        source="poe-ninja-index",
        source_url=NINJA_INDEX_URL,
        fetched_at=checked_at,
        checked_at=checked_at,
        etag='"index-v1"',
        last_modified=None,
        payload={
            "buildLeagues": index_json["buildLeagues"],
            "oldBuildLeagues": index_json["oldBuildLeagues"],
            "snapshotVersions": index_json["snapshotVersions"],
        },
    )


def make_ninja_build_index_envelope(*, checked_at: datetime) -> CacheEnvelope:
    _index_json, build_index_json = snapshot_fixture()
    return CacheEnvelope.create(
        source="poe-ninja-build-index",
        source_url=NINJA_BUILD_INDEX_URL,
        fetched_at=checked_at,
        checked_at=checked_at,
        etag='"build-v1"',
        last_modified=None,
        payload={"leagueBuilds": build_index_json["leagueBuilds"]},
    )


def make_provider(
    tmp_path: Path,
    transport: RouteTransport,
) -> NinjaSnapshotProvider:
    return NinjaSnapshotProvider(
        index_store=FileCacheStore(tmp_path / "ninja-index.json"),
        build_index_store=FileCacheStore(tmp_path / "ninja-build-index.json"),
        transport=transport,
        attempt_throttle=RefreshAttemptThrottle(),
        refresh_coordinator=RefreshCoordinator(),
    )


def test_parse_ninja_snapshot_selects_current_softcore_trade_league():
    index_json, build_index_json = snapshot_fixture()

    snapshot = parse_ninja_snapshot(index_json, build_index_json)

    assert snapshot.league == "Runes of Aldur"
    assert snapshot.league_url == "runesofaldur"
    assert snapshot.version == "0137-20260624-38624"
    assert snapshot.snapshot_date == date(2026, 6, 24)
    assert snapshot.passive_tree == "PassiveTree-0.5"
    assert snapshot.passive_tree_claim == "0_5"
    assert snapshot.sample_size == 124302


def test_parse_ninja_snapshot_does_not_assume_first_selectable_league_is_current():
    index_json, build_index_json = snapshot_fixture()
    dawn_league = next(
        league for league in index_json["buildLeagues"] if league["url"] == "dawnofthehunt"
    )
    index_json["buildLeagues"] = [
        dawn_league,
        *[league for league in index_json["buildLeagues"] if league["url"] != "dawnofthehunt"],
    ]
    index_json["snapshotVersions"] = [
        snapshot
        for snapshot in index_json["snapshotVersions"]
        if snapshot["url"] != "dawnofthehunt"
    ]

    snapshot = parse_ninja_snapshot(index_json, build_index_json)

    assert snapshot.league == "Runes of Aldur"
    assert snapshot.league_url == "runesofaldur"
    assert snapshot.snapshot_date == date(2026, 6, 24)
    assert snapshot.sample_size == 124302


def test_parse_ninja_snapshot_rejects_missing_current_snapshot_without_old_league_fallback():
    index_json, build_index_json = snapshot_fixture()
    index_json["snapshotVersions"] = [
        snapshot for snapshot in index_json["snapshotVersions"] if snapshot["url"] != "runesofaldur"
    ]

    with pytest.raises(ValueError, match="snapshot|current|league"):
        parse_ninja_snapshot(index_json, build_index_json)


def test_parse_ninja_snapshot_ignores_old_league_first_when_current_snapshot_is_valid():
    index_json, build_index_json = snapshot_fixture()
    dawn_league = next(
        league for league in index_json["buildLeagues"] if league["url"] == "dawnofthehunt"
    )
    index_json["buildLeagues"] = [
        dawn_league,
        *[league for league in index_json["buildLeagues"] if league["url"] != "dawnofthehunt"],
    ]
    index_json["snapshotVersions"] = [
        snapshot
        for snapshot in index_json["snapshotVersions"]
        if snapshot["url"] != "dawnofthehunt"
    ]

    snapshot = parse_ninja_snapshot(index_json, build_index_json)

    assert snapshot.league == "Runes of Aldur"
    assert snapshot.league_url == "runesofaldur"


def test_parse_ninja_snapshot_ignores_private_league_url_markers():
    index_json, build_index_json = snapshot_fixture()
    private_league = next(
        league for league in index_json["buildLeagues"] if league["url"] == "pl81609"
    )
    private_league["name"] = "Runes of Aldur Guild Event"
    private_league["displayName"] = "Runes of Aldur Guild Event"

    snapshot = parse_ninja_snapshot(index_json, build_index_json)

    assert snapshot.league == "Runes of Aldur"


def test_parse_ninja_snapshot_ignores_archival_snapshot_urls_outside_selectable_leagues():
    index_json, build_index_json = snapshot_fixture()
    assert any(
        snapshot["url"] == "0.4.0act4bosskillrace3ssf"
        for snapshot in index_json["snapshotVersions"]
    )
    assert all(
        league["url"] != "0.4.0act4bosskillrace3ssf" for league in index_json["buildLeagues"]
    )

    snapshot = parse_ninja_snapshot(index_json, build_index_json)

    assert snapshot.league_url == "runesofaldur"


def test_parse_ninja_snapshot_rejects_ambiguous_newest_current_candidates():
    index_json, build_index_json = snapshot_fixture()
    index_json["buildLeagues"].append(
        {"name": "Secrets of the Atlas", "displayName": "Secrets of the Atlas", "url": "secrets"}
    )
    index_json["snapshotVersions"].append(
        {
            "name": "Secrets of the Atlas",
            "url": "secrets",
            "version": "0137-20260624-11111",
            "passiveTree": "PassiveTree-0.5",
        }
    )
    build_index_json["leagueBuilds"].append(
        {"leagueName": "Secrets of the Atlas", "leagueUrl": "secrets", "total": 77}
    )

    with pytest.raises(ValueError, match=r"ambiguous.*Secrets of the Atlas \(secrets\)"):
        parse_ninja_snapshot(index_json, build_index_json)


def test_parse_ninja_snapshot_excludes_event_qualifier_league_from_newest_selection():
    index_json, build_index_json = snapshot_fixture()
    index_json["buildLeagues"].append(
        {
            "name": "Exilecon 2026 PoE2 Qualifier #2",
            "displayName": "Exilecon 2026 PoE2 Qualifier #2",
            "url": "eventssf",
            "hardcore": False,
        }
    )
    index_json["snapshotVersions"].append(
        {
            "name": "Exilecon 2026 PoE2 Qualifier #2",
            "url": "eventssf",
            "version": "1710-20260624-25922",
            "passiveTree": "PassiveTree-0.5",
        }
    )
    build_index_json["leagueBuilds"].append(
        {"leagueName": "Exilecon 2026 PoE2 Qualifier #2", "leagueUrl": "eventssf", "total": 77}
    )

    snapshot = parse_ninja_snapshot(index_json, build_index_json)

    assert snapshot.league_url == "runesofaldur"
    assert snapshot.sample_size == 124302


def test_parse_ninja_snapshot_excludes_race_event_league_from_newest_selection():
    index_json, build_index_json = snapshot_fixture()
    index_json["buildLeagues"].append(
        {
            "name": "0.4.0 Act 4 Boss Kill Race",
            "displayName": "0.4.0 Act 4 Boss Kill Race",
            "url": "act4bosskillrace2ssf",
            "hardcore": False,
        }
    )
    index_json["snapshotVersions"].append(
        {
            "name": "0.4.0 Act 4 Boss Kill Race",
            "url": "act4bosskillrace2ssf",
            "version": "0328-20260624-40125",
            "passiveTree": "PassiveTree-0.5",
        }
    )
    build_index_json["leagueBuilds"].append(
        {
            "leagueName": "0.4.0 Act 4 Boss Kill Race",
            "leagueUrl": "act4bosskillrace2ssf",
            "total": 218,
        }
    )

    snapshot = parse_ninja_snapshot(index_json, build_index_json)

    assert snapshot.league_url == "runesofaldur"


def test_parse_ninja_snapshot_rejects_missing_snapshot_for_only_candidate():
    index_json, build_index_json = snapshot_fixture()
    index_json["buildLeagues"] = [index_json["buildLeagues"][0]]
    index_json["snapshotVersions"] = []
    build_index_json["leagueBuilds"] = [build_index_json["leagueBuilds"][0]]

    with pytest.raises(ValueError, match="snapshot"):
        parse_ninja_snapshot(index_json, build_index_json)


def test_parse_ninja_snapshot_rejects_missing_build_for_newest_candidate_without_fallback():
    index_json, build_index_json = snapshot_fixture()
    build_index_json["leagueBuilds"] = [
        build for build in build_index_json["leagueBuilds"] if build["leagueUrl"] != "runesofaldur"
    ]

    with pytest.raises(NinjaParseError, match="build|sample"):
        parse_ninja_snapshot(index_json, build_index_json)


def test_parse_ninja_snapshot_rejects_zero_total_for_newest_candidate_without_fallback():
    index_json, build_index_json = snapshot_fixture()
    runes_build = next(
        build for build in build_index_json["leagueBuilds"] if build["leagueUrl"] == "runesofaldur"
    )
    runes_build["total"] = 0

    with pytest.raises(NinjaParseError, match="sample"):
        parse_ninja_snapshot(index_json, build_index_json)


def test_parse_ninja_snapshot_rejects_missing_snapshot_when_no_selectable_snapshot_remains():
    index_json, build_index_json = snapshot_fixture()
    index_json["snapshotVersions"] = [
        snapshot
        for snapshot in index_json["snapshotVersions"]
        if snapshot["url"] not in {"runesofaldur", "dawnofthehunt"}
    ]

    with pytest.raises(NinjaParseError, match="snapshot"):
        parse_ninja_snapshot(index_json, build_index_json)


def test_parse_ninja_snapshot_rejects_malformed_version():
    index_json, build_index_json = snapshot_fixture()
    index_json["snapshotVersions"][0]["version"] = "0137-2026-38624"

    with pytest.raises(ValueError, match="version"):
        parse_ninja_snapshot(index_json, build_index_json)


@pytest.mark.parametrize("total", [None, 0])
def test_parse_ninja_snapshot_rejects_missing_or_zero_total_for_only_candidate(total):
    index_json, build_index_json = snapshot_fixture()
    index_json["buildLeagues"] = [index_json["buildLeagues"][0]]
    index_json["snapshotVersions"] = [index_json["snapshotVersions"][0]]
    build_index_json["leagueBuilds"] = [build_index_json["leagueBuilds"][0]]
    if total is None:
        del build_index_json["leagueBuilds"][0]["total"]
    else:
        build_index_json["leagueBuilds"][0]["total"] = total

    with pytest.raises(ValueError, match="sample"):
        parse_ninja_snapshot(index_json, build_index_json)


def test_parse_ninja_snapshot_rejects_tree_version_mismatch_on_selected_date():
    index_json, build_index_json = snapshot_fixture()
    index_json["snapshotVersions"].append(
        {
            "name": "Runes of Aldur",
            "url": "runesofaldur",
            "version": "0137-20260624-38625",
            "passiveTree": "PassiveTree-0.6",
        }
    )

    with pytest.raises(ValueError, match="passive"):
        parse_ninja_snapshot(index_json, build_index_json)


def test_parse_ninja_snapshot_rejects_malformed_passive_tree_token():
    index_json, build_index_json = snapshot_fixture()
    index_json["snapshotVersions"][0]["passiveTree"] = "Tree-0.5"

    with pytest.raises(ValueError, match="passive"):
        parse_ninja_snapshot(index_json, build_index_json)


def test_ninja_provider_refreshes_and_emits_meta_snapshot_evidence(tmp_path):
    transport = RouteTransport(
        {
            NINJA_INDEX_URL: TransportResponse(
                status_code=200,
                body=json.dumps(read_json("ninja-index.json")).encode(),
            ),
            NINJA_BUILD_INDEX_URL: TransportResponse(
                status_code=200,
                body=json.dumps(read_json("ninja-build-index.json")).encode(),
            ),
        }
    )
    provider = make_provider(tmp_path, transport)

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.REFRESHED
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.component is Component.META_SNAPSHOT
    assert evidence.source == "poe-ninja"
    assert evidence.source_url == NINJA_BUILD_URL
    assert evidence.observed_at == NOW
    assert evidence.version == "0137-20260624-38624"
    assert evidence.status is SourceStatus.CURRENT
    assert [(claim.key, claim.value) for claim in evidence.claims] == [
        (ClaimDimension.LEAGUE, "runes-of-aldur"),
        (ClaimDimension.PASSIVE_TREE, "0_5"),
    ]
    assert [request.url for request in transport.requests] == [
        NINJA_INDEX_URL,
        NINJA_BUILD_INDEX_URL,
    ]
    assert (tmp_path / "ninja-index.json").exists()
    assert (tmp_path / "ninja-build-index.json").exists()
    assert "sample_size=124302" in result.diagnostics
    assert "snapshot_date=2026-06-24" in result.diagnostics
    assert NINJA_POLICY.refresh_after == timedelta(minutes=30)
    assert NINJA_POLICY.reject_after == timedelta(hours=2)


def test_ninja_provider_maps_hard_stale_fallback_to_stale_meta_snapshot(tmp_path):
    checked_at = NOW - timedelta(hours=3)
    index_store = FileCacheStore(tmp_path / "ninja-index.json")
    build_index_store = FileCacheStore(tmp_path / "ninja-build-index.json")
    index_store.save(make_ninja_index_envelope(checked_at=checked_at))
    build_index_store.save(make_ninja_build_index_envelope(checked_at=checked_at))
    provider = make_provider(
        tmp_path,
        RouteTransport(
            {
                NINJA_INDEX_URL: TransportError("offline"),
                NINJA_BUILD_INDEX_URL: TransportError("offline"),
            }
        ),
    )

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.FALLBACK
    evidence = result.evidence[0]
    assert evidence.status is SourceStatus.STALE
    assert evidence.observed_at == checked_at
    assert evidence.source_url == NINJA_BUILD_URL


def test_ninja_provider_revalidates_cached_payload_with_real_league_url_shape(tmp_path):
    FileCacheStore(tmp_path / "ninja-index.json").save(make_ninja_index_envelope(checked_at=NOW))
    FileCacheStore(tmp_path / "ninja-build-index.json").save(
        make_ninja_build_index_envelope(checked_at=NOW)
    )
    provider = make_provider(tmp_path, RouteTransport({}))

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.FRESH
    evidence = result.evidence[0]
    assert evidence.source_url == NINJA_BUILD_URL


def test_ninja_provider_maps_missing_cache_fetch_failure_to_unknown(tmp_path):
    provider = make_provider(
        tmp_path,
        RouteTransport(
            {
                NINJA_INDEX_URL: TransportError("offline"),
                NINJA_BUILD_INDEX_URL: TransportError("offline"),
            }
        ),
    )

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.MISSING
    assert len(result.evidence) == 1
    assert result.evidence[0].component is Component.META_SNAPSHOT
    assert result.evidence[0].source_url == NINJA_INDEX_URL
    assert result.evidence[0].status is SourceStatus.UNKNOWN
    assert result.evidence[0].version is None
    assert result.evidence[0].claims == ()


def test_ninja_provider_maps_build_index_fetch_failure_to_unknown(tmp_path):
    transport = RouteTransport(
        {
            NINJA_INDEX_URL: TransportResponse(
                status_code=200,
                body=json.dumps(read_json("ninja-index.json")).encode(),
            ),
            NINJA_BUILD_INDEX_URL: TransportError("offline"),
        }
    )
    provider = make_provider(tmp_path, transport)

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.MISSING
    assert result.evidence[0].status is SourceStatus.UNKNOWN
    assert any("build-index: transport failed" in diagnostic for diagnostic in result.diagnostics)


def test_ninja_provider_uses_independent_build_index_cache_on_transport_failure(tmp_path):
    build_store = FileCacheStore(tmp_path / "ninja-build-index.json")
    build_store.save(make_ninja_build_index_envelope(checked_at=NOW - timedelta(minutes=40)))
    transport = RouteTransport(
        {
            NINJA_INDEX_URL: TransportResponse(
                status_code=200,
                body=json.dumps(read_json("ninja-index.json")).encode(),
            ),
            NINJA_BUILD_INDEX_URL: TransportError("offline"),
        }
    )
    provider = make_provider(tmp_path, transport)

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.FALLBACK
    assert result.evidence[0].status is SourceStatus.CURRENT
    assert "sample_size=124302" in result.diagnostics


def test_ninja_provider_revalidates_cached_snapshot_payload(tmp_path):
    payload = make_ninja_index_envelope(checked_at=NOW).payload
    payload["version"] = "0137-2026-38624"

    def cache_runner(**kwargs):
        return CacheRunResult(
            envelope=CacheEnvelope.create(
                source="poe-ninja-index",
                source_url=NINJA_INDEX_URL,
                fetched_at=NOW,
                checked_at=NOW,
                etag=None,
                last_modified=None,
                payload=payload,
            ),
            cache_state=CacheState.FRESH,
            hard_stale=False,
            diagnostics=(),
        )

    provider = NinjaSnapshotProvider(
        index_store=FileCacheStore(tmp_path / "ninja-index.json"),
        build_index_store=FileCacheStore(tmp_path / "ninja-build-index.json"),
        transport=RouteTransport({}),
        attempt_throttle=RefreshAttemptThrottle(),
        refresh_coordinator=RefreshCoordinator(),
        cache_runner=cache_runner,
    )

    result = provider.collect(now=NOW)

    assert result.evidence[0].status is SourceStatus.UNKNOWN
    assert result.evidence[0].source_url == NINJA_INDEX_URL
    assert result.evidence[0].version is None
    assert result.evidence[0].claims == ()
    assert any("cached payload invalid" in diagnostic for diagnostic in result.diagnostics)


def test_ninja_provider_rejects_cached_league_url_path_smuggling(tmp_path):
    payload = make_ninja_index_envelope(checked_at=NOW).payload
    payload["league_url"] = "runesofaldur/../../evil"

    def cache_runner(**kwargs):
        return CacheRunResult(
            envelope=CacheEnvelope.create(
                source="poe-ninja-index",
                source_url=NINJA_INDEX_URL,
                fetched_at=NOW,
                checked_at=NOW,
                etag=None,
                last_modified=None,
                payload=payload,
            ),
            cache_state=CacheState.FRESH,
            hard_stale=False,
            diagnostics=(),
        )

    provider = NinjaSnapshotProvider(
        index_store=FileCacheStore(tmp_path / "ninja-index.json"),
        build_index_store=FileCacheStore(tmp_path / "ninja-build-index.json"),
        transport=RouteTransport({}),
        attempt_throttle=RefreshAttemptThrottle(),
        refresh_coordinator=RefreshCoordinator(),
        cache_runner=cache_runner,
    )

    result = provider.collect(now=NOW)

    assert result.evidence[0].status is SourceStatus.UNKNOWN
    assert result.evidence[0].source_url == NINJA_INDEX_URL
    assert any("cached payload invalid" in diagnostic for diagnostic in result.diagnostics)
