"""Tests for live-meta shaping helpers.

These stay network-free. They protect the boundary between real aggregate sample evidence and
payloads that only contain ascendancy popularity.
"""

from __future__ import annotations

from server.live import meta


def test_archetype_trends_are_unavailable_for_ascendancy_only_payload():
    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "leagueUrl": "runesofaldur",
                "total": 124269,
                "statistics": [
                    {"class": "Stormweaver", "percentage": 22.0, "trend": 1},
                ],
            }
        ]
    }

    result = meta.shape_archetype_trends(sample)

    assert result["ok"] is False
    assert result["kind"] == "archetype_trends"
    assert result["league"] == "Runes of Aldur"
    assert result["archetypes"] == []
    assert "aggregate" in result["unavailableReason"].lower()
    assert "unavailable" in result["evidenceTags"]


def test_archetype_trends_shape_controlled_aggregate_rows_only():
    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "total": 400,
                "archetypes": [
                    {
                        "mainSkill": "Spark",
                        "ascendancy": "Stormweaver",
                        "sampleCount": 40,
                        "percentage": 12.5,
                        "trend": 1,
                        "items": ["raw gear must not leak"],
                        "passives": ["raw tree must not leak"],
                        "evidenceTags": ["fixture"],
                    },
                    {
                        "skill": "Lightning Spear",
                        "class": "Deadeye",
                        "count": 10,
                        "share": 0.025,
                        "trend": -1,
                    },
                ],
            }
        ]
    }

    result = meta.shape_archetype_trends(sample, limit=5)

    assert result["ok"] is True
    assert result["kind"] == "archetype_trends"
    assert result["sampleSize"] == 400
    first = result["archetypes"][0]
    assert first == {
        "skill": "Spark",
        "ascendancy": "Stormweaver",
        "sampleCount": 40,
        "share": 0.125,
        "trend": "rising",
        "evidenceTags": ["live-meta", "archetype-trend"],
    }
    assert set(first) == {"skill", "ascendancy", "sampleCount", "share", "trend", "evidenceTags"}
    assert result["archetypes"][1]["trend"] == "falling"


def test_archetype_trends_sort_by_share_before_sample_count():
    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "total": 1000,
                "archetypes": [
                    {
                        "skill": "Tiny But Counted",
                        "ascendancy": "Stormweaver",
                        "sampleCount": 500,
                        "share": 0.01,
                    },
                    {
                        "skill": "Dominant Share",
                        "ascendancy": "Deadeye",
                        "percentage": 25,
                    },
                ],
            }
        ]
    }

    result = meta.shape_archetype_trends(sample)

    assert result["archetypes"][0]["skill"] == "Dominant Share"


def test_meta_context_shapes_ascendancy_and_archetypes_from_one_payload():
    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "total": 1000,
                "statistics": [{"class": "Stormweaver", "percentage": 22.0, "trend": 1}],
                "archetypes": [
                    {
                        "skill": "Spark",
                        "ascendancy": "Stormweaver",
                        "sampleCount": 100,
                        "share": 0.1,
                    }
                ],
            }
        ]
    }

    result = meta.shape_meta_context(sample, ascendancy_limit=5, archetype_limit=5)

    assert result["ok"] is True
    assert result["ascendancies"][0]["ascendancy"] == "Stormweaver"
    assert result["archetypeTrends"]["archetypes"][0]["skill"] == "Spark"


def test_archetype_trends_require_sample_count_or_share():
    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "skills": [{"name": "Spark", "ascendancy": "Stormweaver"}],
            }
        ]
    }

    result = meta.shape_archetype_trends(sample)

    assert result["ok"] is False
    assert result["archetypes"] == []
    assert "valid aggregate" in result["unavailableReason"].lower()
    assert "unavailable" in result["evidenceTags"]
    assert "archetype-trend" not in result["evidenceTags"]


def test_archetype_trends_unavailable_when_aggregate_key_has_no_valid_rows():
    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "archetypes": [{"ascendancy": "Stormweaver", "percentage": 12.5}],
            }
        ]
    }

    result = meta.shape_archetype_trends(sample)

    assert result["ok"] is False
    assert result["archetypes"] == []
    assert "valid aggregate" in result["unavailableReason"].lower()
    assert "unavailable" in result["evidenceTags"]


def test_archetype_trends_do_not_treat_league_totals_as_row_sample_counts():
    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "archetypes": [
                    {"skill": "Spark", "total": 100},
                    {"skill": "Lightning Spear", "characters": 25},
                ],
            }
        ]
    }

    result = meta.shape_archetype_trends(sample)

    assert result["ok"] is False
    assert result["archetypes"] == []
    assert "valid aggregate" in result["unavailableReason"].lower()
    assert "unavailable" in result["evidenceTags"]
    assert "archetype-trend" not in result["evidenceTags"]


def test_archetype_trends_reject_invalid_aggregate_metrics():
    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "total": 1000,
                "archetypes": [
                    {"skill": "Bool Count", "sampleCount": True},
                    {"skill": "Negative Count", "sampleCount": -1},
                    {"skill": "Share Percent Confusion", "share": 2},
                    {"skill": "Negative Share", "share": -0.1},
                    {"skill": "Impossible Percentage", "percentage": 125},
                    {"skill": "Bool Percentage", "percentage": False},
                ],
            }
        ]
    }

    result = meta.shape_archetype_trends(sample)

    assert result["ok"] is False
    assert result["archetypes"] == []
    assert "valid aggregate" in result["unavailableReason"].lower()
    assert "unavailable" in result["evidenceTags"]
    assert "archetype-trend" not in result["evidenceTags"]


def test_archetype_trends_reject_sample_count_larger_than_sample_size():
    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "total": 1000,
                "archetypes": [{"skill": "Spark", "sampleCount": 2000}],
            }
        ]
    }

    result = meta.shape_archetype_trends(sample)

    assert result["ok"] is False
    assert result["archetypes"] == []
    assert "valid aggregate" in result["unavailableReason"].lower()


def test_archetype_trends_reject_nested_skill_values():
    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "total": 100,
                "archetypes": [
                    {
                        "skill": {"name": "Spark", "items": ["raw gear must not leak"]},
                        "sampleCount": 10,
                    }
                ],
            }
        ]
    }

    result = meta.shape_archetype_trends(sample)

    assert result["ok"] is False
    assert result["archetypes"] == []


def test_archetype_trends_sanitizes_nested_ascendancy_and_provider_tags():
    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "total": 100,
                "archetypes": [
                    {
                        "skill": "Spark",
                        "ascendancy": {"name": "Stormweaver", "buildCode": "must not leak"},
                        "sampleCount": 10,
                        "evidenceTags": ["engine-computed", "pob-verified", "fixture"],
                    }
                ],
            }
        ]
    }

    result = meta.shape_archetype_trends(sample)

    row = result["archetypes"][0]
    assert row["ascendancy"] is None
    assert row["evidenceTags"] == ["live-meta", "archetype-trend"]
    assert "must not leak" not in str(result)
    assert "engine-computed" not in row["evidenceTags"]
