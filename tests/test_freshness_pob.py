from __future__ import annotations

from datetime import UTC, datetime
from datetime import timedelta
import json
from pathlib import Path
import re
from typing import Any

import pytest

from server.freshness import pob as pob_module
from server.freshness.cache import (
    FileCacheStore,
    RefreshAttemptThrottle,
    RefreshCoordinator,
    TransportError,
    TransportRequest,
    TransportResponse,
)
from server.freshness.models import ClaimDimension, Component, SourceStatus
from server.freshness.pob import (
    POB_RELEASE_API_URL,
    CompatibilityEntry,
    PobProvider,
    load_compatibility_manifest,
    parse_pob_release,
    pob_release_commit_api_url,
    resolve_compatibility,
)
from server.freshness.provider_models import CacheState


FIXTURES = Path(__file__).parent / "fixtures" / "freshness"
NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
LOCAL_PIN = "a82a33b4"
REMOTE_COMMIT = "dc409a7073e4e2752e9a642db7544af53551d006"
POB_054_CANDIDATE = "7d1aa43c8c938d7be150d197ed9cdec8a4c1c620"
POB_022_RELEASE = "860f4268299739ce9df87c4f373abe35824101cf"
POB_023_RELEASE = "7d6f530cbdab20389ff8bc6ba97a37ac27f74e41"
POB_055_CANDIDATE = "ce566eac45ea8a86477f513c7ee65a1ebe60014e"
VERIFIED_COMMIT = "1234567890abcdef1234567890abcdef12345678"
REPO_ROOT = Path(__file__).resolve().parents[1]


def read_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def read_json(name: str) -> Any:
    return json.loads(read_text(name))


def test_pinned_pob_commit_is_consistent_across_release_inputs():
    pinned = (REPO_ROOT / "pob" / "PINNED.md").read_text(encoding="utf-8")
    pinned_match = re.search(r"Pinned commit \| `([0-9a-f]{40})`", pinned)
    assert pinned_match is not None
    pinned_commit = pinned_match.group(1)

    compatibility = json.loads(
        (REPO_ROOT / "data" / "compatibility" / "pob.json").read_text(encoding="utf-8")
    )
    certified_commits = {entry["commit"] for entry in compatibility["entries"]}
    assert pinned_commit in certified_commits

    for workflow in ("ci.yml", "release.yml"):
        content = (REPO_ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        workflow_match = re.search(r"POB_COMMIT:\s*([0-9a-f]{40})", content)
        assert workflow_match is not None
        assert workflow_match.group(1) == pinned_commit


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


def write_manifest(
    path: Path,
    entries: list[dict[str, Any]],
    *,
    current_pob_version: str | None = None,
) -> Path:
    payload: dict[str, Any] = {"schema_version": 1, "entries": entries}
    if current_pob_version is not None:
        payload["current_pob_version"] = current_pob_version
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    return path


def compatibility_entry(
    commit: str = VERIFIED_COMMIT,
    *,
    pob_version: str = "0.21.1",
    game_patch: str = "0.5.3",
    passive_tree: str = "0_5",
) -> dict[str, Any]:
    return {
        "commit": commit,
        "pob_version": pob_version,
        "game_patch": game_patch,
        "passive_tree": passive_tree,
        "verified_by": ["golden-tests", "GGG-patch"],
        "verified_at": "2026-06-24T00:00:00+00:00",
    }


def test_compatibility_manifest_uses_explicit_current_pob_version(tmp_path):
    entries = [
        compatibility_entry(commit="a" * 40, pob_version="0.21.1"),
        compatibility_entry(commit="b" * 40, pob_version="0.22.0"),
    ]
    manifest = load_compatibility_manifest(
        write_manifest(
            tmp_path / "manifest.json",
            entries,
            current_pob_version="0.22.0",
        )
    )

    assert manifest.current_pob_version == "0.22.0"


def test_compatibility_manifest_rejects_unknown_current_pob_version(tmp_path):
    path = write_manifest(
        tmp_path / "manifest.json",
        [compatibility_entry()],
        current_pob_version="99.99.99",
    )

    with pytest.raises(pob_module.PobParseError, match="current_pob_version"):
        load_compatibility_manifest(path)


def make_provider(
    tmp_path: Path,
    *,
    manifest_entries: list[dict[str, Any]],
    local_metadata: dict[str, Any],
    transport: RouteTransport | None = None,
) -> tuple[PobProvider, RouteTransport]:
    if transport is None:
        release = read_json("pob-release.json")
        transport = RouteTransport(
            {
                POB_RELEASE_API_URL: TransportResponse(
                    status_code=200,
                    body=json.dumps(release).encode(),
                ),
                pob_release_commit_api_url(release["tag_name"]): TransportResponse(
                    status_code=200,
                    body=json.dumps(read_json("pob-release-commit.json")).encode(),
                ),
            }
        )
    manifest_path = write_manifest(tmp_path / "pob-compatibility.json", manifest_entries)
    provider = PobProvider(
        store=FileCacheStore(tmp_path / "pob-release-cache.json"),
        transport=transport,
        attempt_throttle=RefreshAttemptThrottle(),
        refresh_coordinator=RefreshCoordinator(),
        manifest_path=manifest_path,
        local_metadata=lambda: local_metadata,
    )
    return provider, transport


def by_component(result) -> dict[Component, Any]:
    return {evidence.component: evidence for evidence in result.evidence}


def claim_pairs(evidence) -> list[tuple[ClaimDimension, str]]:
    return [(claim.key, claim.value) for claim in evidence.claims]


def test_parse_pob_release_uses_release_and_commit_fixtures():
    release = parse_pob_release(
        read_json("pob-release.json"),
        read_json("pob-release-commit.json"),
    )

    assert release.tag == "v0.21.1"
    assert release.name == "Release 0.21.1"
    assert release.version == "0.21.1"
    assert release.published_at == datetime(2026, 6, 23, 5, 51, 33, tzinfo=UTC)
    assert release.commit == REMOTE_COMMIT
    assert release.url.endswith("/releases/tag/v0.21.1")


def test_local_commit_absent_from_manifest_never_receives_patch_or_tree_claims(tmp_path):
    provider, _transport = make_provider(
        tmp_path,
        manifest_entries=[],
        local_metadata={"version": "v0.1.39", "pob_commit": LOCAL_PIN},
    )

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.REFRESHED
    records = by_component(result)
    assert set(records) == {Component.POB_ENGINE, Component.POB_DATA}
    assert records[Component.POB_ENGINE].status is SourceStatus.STALE
    assert records[Component.POB_DATA].status is SourceStatus.STALE
    assert all(evidence.claims == () for evidence in result.evidence)


def test_matching_verified_commit_receives_game_patch_and_passive_tree_claims(tmp_path):
    release = read_json("pob-release.json")
    release["tag_name"] = "v0.21.1-certified"
    release["name"] = "Release 0.21.1 certified"
    commit = read_json("pob-release-commit.json")
    commit["sha"] = VERIFIED_COMMIT
    transport = RouteTransport(
        {
            POB_RELEASE_API_URL: TransportResponse(
                status_code=200,
                body=json.dumps(release).encode(),
            ),
            pob_release_commit_api_url(release["tag_name"]): TransportResponse(
                status_code=200,
                body=json.dumps(commit).encode(),
            ),
        }
    )
    provider, _transport = make_provider(
        tmp_path,
        manifest_entries=[compatibility_entry()],
        local_metadata={"version": "v0.21.1", "pob_commit": VERIFIED_COMMIT},
        transport=transport,
    )

    result = provider.collect(now=NOW)

    for evidence in result.evidence:
        assert evidence.status is SourceStatus.CURRENT
        assert claim_pairs(evidence) == [
            (ClaimDimension.GAME_PATCH, "0.5.3"),
            (ClaimDimension.PASSIVE_TREE, "0_5"),
        ]


def test_certified_dev_export_candidate_is_not_stale_behind_older_release(tmp_path):
    release = read_json("pob-release.json")
    release["published_at"] = "2026-06-23T05:51:33Z"
    commit = read_json("pob-release-commit.json")
    commit["sha"] = REMOTE_COMMIT
    transport = RouteTransport(
        {
            POB_RELEASE_API_URL: TransportResponse(
                status_code=200,
                body=json.dumps(release).encode(),
            ),
            pob_release_commit_api_url(release["tag_name"]): TransportResponse(
                status_code=200,
                body=json.dumps(commit).encode(),
            ),
        }
    )
    candidate = compatibility_entry(
        commit=POB_054_CANDIDATE,
        pob_version="0.21.1-dev.20260625",
        game_patch="0.5.4",
    )
    candidate["verified_by"] = [
        "golden-tests",
        "GGG-patch",
        "GGG-tree",
        "ninja-tree",
        "pob-dev-export",
    ]
    candidate["verified_at"] = "2026-06-26T02:59:55Z"
    provider, _transport = make_provider(
        tmp_path,
        manifest_entries=[candidate],
        local_metadata={"version": "0.21.1-dev.20260625", "pob_commit": POB_054_CANDIDATE},
        transport=transport,
    )

    result = provider.collect(now=NOW)

    assert all(evidence.status is SourceStatus.CURRENT for evidence in result.evidence)
    assert all(
        claim_pairs(evidence)
        == [
            (ClaimDimension.GAME_PATCH, "0.5.4"),
            (ClaimDimension.PASSIVE_TREE, "0_5"),
        ]
        for evidence in result.evidence
    )


def test_newer_release_does_not_invalidate_certified_same_season_runtime(tmp_path):
    release = read_json("pob-release.json")
    release["published_at"] = "2026-06-26T02:59:55Z"
    commit = read_json("pob-release-commit.json")
    commit["sha"] = REMOTE_COMMIT
    transport = RouteTransport(
        {
            POB_RELEASE_API_URL: TransportResponse(
                status_code=200,
                body=json.dumps(release).encode(),
            ),
            pob_release_commit_api_url(release["tag_name"]): TransportResponse(
                status_code=200,
                body=json.dumps(commit).encode(),
            ),
        }
    )
    candidate = compatibility_entry(
        commit=POB_054_CANDIDATE,
        pob_version="0.21.1-dev.20260625",
        game_patch="0.5.4",
    )
    candidate["verified_by"] = [
        "golden-tests",
        "GGG-patch",
        "GGG-tree",
        "ninja-tree",
        "pob-dev-export",
    ]
    candidate["verified_at"] = "2026-06-26T02:59:55Z"
    provider, _transport = make_provider(
        tmp_path,
        manifest_entries=[candidate],
        local_metadata={"version": "0.21.1-dev.20260625", "pob_commit": POB_054_CANDIDATE},
        transport=transport,
    )

    result = provider.collect(now=NOW)

    assert all(evidence.status is SourceStatus.CURRENT for evidence in result.evidence)
    assert any("compatibility retained" in diagnostic for diagnostic in result.diagnostics)


def test_remote_release_ahead_of_local_pin_marks_engine_and_data_stale(tmp_path):
    provider, _transport = make_provider(
        tmp_path,
        manifest_entries=[],
        local_metadata={"version": "v0.1.39", "pob_commit": LOCAL_PIN},
    )

    result = provider.collect(now=NOW)

    assert [evidence.status for evidence in result.evidence] == [
        SourceStatus.STALE,
        SourceStatus.STALE,
    ]
    assert any(LOCAL_PIN in diagnostic for diagnostic in result.diagnostics)
    assert any(REMOTE_COMMIT[:12] in diagnostic for diagnostic in result.diagnostics)


def test_release_note_text_alone_cannot_grant_compatibility_claims(tmp_path):
    release = read_json("pob-release.json")
    assert "0.5.3" in release["body"]
    assert "0_5" in release["body"]
    provider, _transport = make_provider(
        tmp_path,
        manifest_entries=[],
        local_metadata={"version": "v0.1.39", "pob_commit": LOCAL_PIN},
    )

    result = provider.collect(now=NOW)

    assert all(evidence.claims == () for evidence in result.evidence)


@pytest.mark.parametrize(
    "entry_patch",
    [
        {"commit": "abc123"},
        {"game_patch": ""},
        {"passive_tree": ""},
        {"verified_by": []},
        {"verified_by": ["golden-tests", ""]},
        {"verified_at": "2026-06-24T00:00:00"},
    ],
)
def test_malformed_compatibility_entries_are_rejected(tmp_path, entry_patch):
    entry = compatibility_entry()
    entry.update(entry_patch)
    manifest_path = write_manifest(tmp_path / "pob-compatibility.json", [entry])

    with pytest.raises(ValueError):
        load_compatibility_manifest(manifest_path)


def test_duplicate_compatibility_commits_are_rejected(tmp_path):
    manifest_path = write_manifest(
        tmp_path / "pob-compatibility.json",
        [compatibility_entry(), compatibility_entry()],
    )

    with pytest.raises(ValueError, match="duplicate"):
        load_compatibility_manifest(manifest_path)


def test_unambiguous_local_short_prefix_commit_matches_full_manifest_commit(tmp_path):
    manifest_path = write_manifest(
        tmp_path / "pob-compatibility.json",
        [compatibility_entry(commit=VERIFIED_COMMIT)],
    )
    manifest = load_compatibility_manifest(manifest_path)

    match = resolve_compatibility(VERIFIED_COMMIT[:12], manifest)

    assert isinstance(match, CompatibilityEntry)
    assert match.commit == VERIFIED_COMMIT


def test_ambiguous_local_short_prefix_commits_reject(tmp_path):
    manifest_path = write_manifest(
        tmp_path / "pob-compatibility.json",
        [
            compatibility_entry(commit="abcdef1111111111111111111111111111111111"),
            compatibility_entry(commit="abcdef2222222222222222222222222222222222"),
        ],
    )
    manifest = load_compatibility_manifest(manifest_path)

    with pytest.raises(ValueError, match="ambiguous"):
        resolve_compatibility("abcdef", manifest)


def test_ambiguous_local_short_prefix_in_provider_emits_unknown(tmp_path):
    provider, _transport = make_provider(
        tmp_path,
        manifest_entries=[
            compatibility_entry(commit="abcdef1111111111111111111111111111111111"),
            compatibility_entry(commit="abcdef2222222222222222222222222222222222"),
        ],
        local_metadata={"version": "v0.1.0", "pob_commit": "abcdef"},
    )

    result = provider.collect(now=NOW)

    assert all(evidence.status is SourceStatus.UNKNOWN for evidence in result.evidence)
    assert all(evidence.claims == () for evidence in result.evidence)
    assert any("ambiguous" in diagnostic for diagnostic in result.diagnostics)


def test_resolved_certified_short_prefix_remains_current_when_remote_is_newer(tmp_path):
    local_manifest_commit = "abcdef1111111111111111111111111111111111"
    remote_commit = "abcdef2222222222222222222222222222222222"
    release = read_json("pob-release.json")
    release["tag_name"] = "v0.22.0"
    release["name"] = "Release 0.22.0"
    commit = read_json("pob-release-commit.json")
    commit["sha"] = remote_commit
    transport = RouteTransport(
        {
            POB_RELEASE_API_URL: TransportResponse(
                status_code=200,
                body=json.dumps(release).encode(),
            ),
            pob_release_commit_api_url(release["tag_name"]): TransportResponse(
                status_code=200,
                body=json.dumps(commit).encode(),
            ),
        }
    )
    provider, _transport = make_provider(
        tmp_path,
        manifest_entries=[compatibility_entry(commit=local_manifest_commit)],
        local_metadata={"pob_commit": "abcdef"},
        transport=transport,
    )

    result = provider.collect(now=NOW)

    assert all(evidence.status is SourceStatus.CURRENT for evidence in result.evidence)
    assert all(evidence.version == local_manifest_commit for evidence in result.evidence)
    assert any(local_manifest_commit in diagnostic for diagnostic in result.diagnostics)
    assert any("compatibility retained" in diagnostic for diagnostic in result.diagnostics)


def test_missing_local_commit_emits_unknown_without_claims(tmp_path):
    provider, _transport = make_provider(
        tmp_path,
        manifest_entries=[compatibility_entry()],
        local_metadata={"version": "v0.1.39"},
    )

    result = provider.collect(now=NOW)

    assert all(evidence.status is SourceStatus.UNKNOWN for evidence in result.evidence)
    assert all(evidence.version is None for evidence in result.evidence)
    assert all(evidence.claims == () for evidence in result.evidence)


def test_remote_fetch_failure_with_no_cache_emits_unknown_without_crash(tmp_path):
    transport = RouteTransport({POB_RELEASE_API_URL: TransportError("offline")})
    provider, _transport = make_provider(
        tmp_path,
        manifest_entries=[],
        local_metadata={"version": "v0.1.39", "pob_commit": LOCAL_PIN},
        transport=transport,
    )

    result = provider.collect(now=NOW)

    assert result.cache_state is CacheState.MISSING
    assert all(evidence.status is SourceStatus.UNKNOWN for evidence in result.evidence)
    assert all(evidence.claims == () for evidence in result.evidence)
    assert any("offline" in diagnostic for diagnostic in result.diagnostics)


def test_hard_stale_remote_cache_with_transport_failure_does_not_mark_unknown_manifest_commit_stale(
    tmp_path,
):
    provider, transport = make_provider(
        tmp_path,
        manifest_entries=[],
        local_metadata={"version": "v0.1.39", "pob_commit": LOCAL_PIN},
    )
    provider.collect(now=NOW)
    transport.outcomes[POB_RELEASE_API_URL] = TransportError("offline")

    result = provider.collect(now=NOW + timedelta(hours=7))

    assert result.cache_state is CacheState.FALLBACK
    assert all(evidence.status is SourceStatus.UNKNOWN for evidence in result.evidence)
    assert all(evidence.claims == () for evidence in result.evidence)
    assert all(evidence.source_url == POB_RELEASE_API_URL for evidence in result.evidence)
    assert any(
        "hard-stale" in diagnostic or "reject_after" in diagnostic
        for diagnostic in result.diagnostics
    )
    assert any(
        "remote" in diagnostic and "cache" in diagnostic for diagnostic in result.diagnostics
    )


def test_hard_stale_remote_cache_with_transport_failure_keeps_manifest_claims_without_remote_url(
    tmp_path,
):
    provider, transport = make_provider(
        tmp_path,
        manifest_entries=[compatibility_entry()],
        local_metadata={"version": "v0.21.1", "pob_commit": VERIFIED_COMMIT},
    )
    provider.collect(now=NOW)
    transport.outcomes[POB_RELEASE_API_URL] = TransportError("offline")

    result = provider.collect(now=NOW + timedelta(hours=7))

    assert result.cache_state is CacheState.FALLBACK
    for evidence in result.evidence:
        assert evidence.status is SourceStatus.CURRENT
        assert evidence.source_url == POB_RELEASE_API_URL
        assert claim_pairs(evidence) == [
            (ClaimDimension.GAME_PATCH, "0.5.3"),
            (ClaimDimension.PASSIVE_TREE, "0_5"),
        ]
    assert any(
        "hard-stale" in diagnostic or "reject_after" in diagnostic
        for diagnostic in result.diagnostics
    )


def test_overlong_hex_local_commit_emits_unknown_without_claims(tmp_path):
    overlong_commit = "a" * 41
    provider, _transport = make_provider(
        tmp_path,
        manifest_entries=[compatibility_entry(commit="a" * 40)],
        local_metadata={"version": "v0.21.1", "pob_commit": overlong_commit},
    )

    result = provider.collect(now=NOW)

    assert all(evidence.status is SourceStatus.UNKNOWN for evidence in result.evidence)
    assert all(evidence.claims == () for evidence in result.evidence)
    assert any(
        "longer than full hash" in diagnostic or "longer than a full hash" in diagnostic
        for diagnostic in result.diagnostics
    )


def test_repository_manifest_authorizes_only_the_certified_pob_pin():
    manifest = load_compatibility_manifest(Path("data/compatibility/pob.json"))

    assert manifest.schema_version == 1
    assert len(manifest.entries) == 5
    assert manifest.current_pob_version == "0.23.1-dev.20260910"

    entries = {entry.commit: entry for entry in manifest.entries}
    release_entry = entries[REMOTE_COMMIT]
    assert release_entry.pob_version == "0.21.1"
    assert release_entry.game_patch == "0.5.3"
    assert release_entry.passive_tree == "0_5"
    assert release_entry.verified_by == ("golden-tests", "GGG-patch", "GGG-tree", "ninja-tree")
    assert release_entry.verified_at.tzinfo is UTC

    candidate_entry = entries[POB_054_CANDIDATE]
    assert candidate_entry.pob_version == "0.21.1-dev.20260625"
    assert candidate_entry.game_patch == "0.5.4"
    assert candidate_entry.passive_tree == "0_5"
    assert candidate_entry.verified_by == (
        "golden-tests",
        "GGG-patch",
        "GGG-tree",
        "ninja-tree",
        "pob-dev-export",
    )
    assert candidate_entry.verified_at.tzinfo is UTC

    current_entry = entries[POB_022_RELEASE]
    assert current_entry.pob_version == "0.22.0"
    assert current_entry.game_patch == "0.5.4"
    assert current_entry.passive_tree == "0_5"
    assert current_entry.verified_at.tzinfo is UTC

    historical_release = entries[POB_023_RELEASE]
    assert historical_release.pob_version == "0.23.1"
    assert historical_release.game_patch == "0.5.4"
    assert historical_release.passive_tree == "0_5"

    current_candidate = entries[POB_055_CANDIDATE]
    assert current_candidate.pob_version == manifest.current_pob_version
    assert current_candidate.game_patch == "0.5.5"
    assert current_candidate.passive_tree == "0_5"
    assert "pob-dev-export" in current_candidate.verified_by
    assert current_candidate.verified_at.tzinfo is UTC

    assert resolve_compatibility(POB_054_CANDIDATE, manifest) == candidate_entry
    assert resolve_compatibility(POB_022_RELEASE, manifest) == current_entry
    assert resolve_compatibility(POB_023_RELEASE, manifest) == historical_release
    assert resolve_compatibility(POB_055_CANDIDATE, manifest) == current_candidate

    # Certification remains exact: nearby or older PoB commits must not inherit these claims.
    assert resolve_compatibility(LOCAL_PIN, manifest) is None


def test_read_pinned_commit_parses_pinned_markdown_table(tmp_path):
    pinned_path = tmp_path / "PINNED.md"
    pinned_path.write_text(
        "| Key | Value |\n| --- | --- |\n| Pinned commit | `a82a33b` |\n",
        encoding="utf-8",
    )

    assert pob_module.read_pinned_commit(pinned_path) == "a82a33b"


def test_local_metadata_falls_back_to_pinned_commit_when_installed_lacks_commit(tmp_path):
    pinned_path = tmp_path / "PINNED.md"
    pinned_path.write_text("Pinned commit | `a82a33b`\n", encoding="utf-8")

    metadata = pob_module._local_metadata_with_pinned_fallback(
        installed={"version": "v0.1.39"},
        pinned_path=pinned_path,
    )

    assert metadata == {"version": "v0.1.39", "pob_commit": "a82a33b"}
