from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from server.freshness import Component, VersionClaim, FreshnessManifest, evaluate_freshness
from server.freshness import leagues, ninja
from test_freshness import current_manifest


def test_same_tree_new_league_cannot_certify_old_model():
    records = []
    for row in current_manifest().evidence:
        claims = tuple(
            VersionClaim(claim.key, "Forbidden Rites")
            if claim.key == "league"
            else VersionClaim(claim.key, "0.5.5")
            if row.component is Component.GAME_PATCH
            else VersionClaim(claim.key, "0.5.4")
            if claim.key == "game_patch"
            else claim
            for claim in row.claims
        )
        records.append(replace(row, claims=claims))
    assert evaluate_freshness(FreshnessManifest(tuple(records))).decision == "blocked_conflict"


def test_explicit_league_disambiguates_concurrent_same_day_snapshots():
    root = Path(__file__).parent / "fixtures" / "freshness"
    index = json.loads((root / "ninja-index.json").read_text())
    builds = json.loads((root / "ninja-build-index.json").read_text())
    index["buildLeagues"].append(
        {"name": "Forbidden Rites", "url": "forbiddenrites", "hardcore": False}
    )
    existing = next(row for row in index["snapshotVersions"] if row["url"] == "runesofaldur")
    index["snapshotVersions"].append(
        {**existing, "url": "forbiddenrites", "name": "Forbidden Rites"}
    )
    old_build = next(row for row in builds["leagueBuilds"] if row["leagueUrl"] == "runesofaldur")
    builds["leagueBuilds"].append({**old_build, "leagueUrl": "forbiddenrites"})
    assert (
        ninja.parse_ninja_snapshot(index, builds, target_league="Forbidden Rites").league
        == "Forbidden Rites"
    )
    assert (
        ninja.parse_ninja_snapshot(index, builds, target_league="Runes of Aldur").league
        == "Runes of Aldur"
    )
    with pytest.raises(ninja.NinjaParseError):
        ninja.parse_ninja_snapshot(index, builds, target_league="Unknown League")


def test_reviewed_league_registry_has_time_and_patch_boundaries():
    assert leagues.default_league(datetime(2026, 9, 5, tzinfo=timezone.utc)) == "Forbidden Rites"
    assert leagues.default_league(datetime(2026, 9, 3, tzinfo=timezone.utc)) is None
    assert leagues.default_league(datetime(2027, 1, 1, tzinfo=timezone.utc)) is None
    assert leagues.ruleset(datetime(2026, 9, 5, tzinfo=timezone.utc), "0.6.0") is None
