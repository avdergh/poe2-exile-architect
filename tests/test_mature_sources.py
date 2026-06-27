from __future__ import annotations

from server.live import mature_sources


def test_probe_reports_ascendancy_only_payload_as_unavailable():
    payload = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "leagueUrl": "runesofaldur",
                "total": 124302,
                "statistics": [{"class": "Stormweaver", "percentage": 22.0}],
            }
        ]
    }

    report = mature_sources.shape_build_level_probe(
        url="https://poe.ninja/poe2/api/data/build-index-state",
        status_code=200,
        payload=payload,
    )

    assert report["ok"] is False
    assert report["sourceType"] == "poe_ninja"
    assert report["hasBuildLevelRows"] is False
    assert "ascendancy" in report["unavailableReason"].lower()
    assert report["nestedLeagueShapes"] == [
        {
            "rowShape": ["leagueName", "leagueUrl", "statistics", "total"],
            "statisticsShape": ["class", "percentage"],
        }
    ]
    assert "rawPayload" not in report
    assert "Stormweaver" not in str(report)


def test_probe_report_summarizes_shape_without_raw_payload():
    payload = {
        "builds": [
            {
                "skill": "Spark",
                "items": ["raw item must not leak"],
                "passiveTree": {"nodes": [1, 2, 3]},
            }
        ]
    }

    report = mature_sources.shape_build_level_probe(
        url="https://example.test/builds",
        status_code=200,
        payload=payload,
    )

    assert report["ok"] is True
    assert report["sourceType"] == "external"
    assert report["hasBuildLevelRows"] is True
    assert report["rowKind"] == "build_level"
    assert report["rowShape"] == ["items", "passiveTree", "skill"]
    assert report["rawContentPersisted"] is False
    assert "raw item must not leak" not in str(report)
    assert "nodes" not in str(report)
    assert "rawPayload" not in report


def test_probe_distinguishes_aggregate_rows_from_build_level_samples():
    payload = {
        "archetypes": [
            {
                "skill": "Spark",
                "ascendancy": "Stormweaver",
                "sampleCount": 40,
            }
        ]
    }

    report = mature_sources.shape_build_level_probe(
        url="https://poe.ninja/poe2/api/data/build-index-state",
        status_code=200,
        payload=payload,
    )

    assert report["ok"] is False
    assert report["hasBuildLevelRows"] is False
    assert report["hasAggregateRows"] is True
    assert report["rowShape"] == ["ascendancy", "sampleCount", "skill"]
    assert "Stormweaver" not in str(report)


def test_probe_reports_http_or_payload_failures_without_raw_content():
    http_report = mature_sources.shape_build_level_probe(
        url="https://poe.ninja/poe2/builds/runesofaldur",
        status_code=404,
        payload="<html>not persisted</html>",
    )
    payload_report = mature_sources.shape_build_level_probe(
        url="https://poe.ninja/poe2/builds/runesofaldur",
        status_code=200,
        payload=["not", "an", "object"],
    )

    assert http_report["ok"] is False
    assert http_report["unavailableReason"] == "HTTP 404"
    assert "not persisted" not in str(http_report)
    assert payload_report["ok"] is False
    assert payload_report["unavailableReason"] == "payload is not a JSON object"


def test_probe_redacts_copyable_source_url():
    report = mature_sources.shape_build_level_probe(
        url="https://pobb.in/abc123",
        status_code=404,
        payload="",
    )

    assert report["ok"] is False
    assert report["url"].startswith("source-url:pobb.in:")
    assert "abc123" not in str(report)


def test_probe_redacts_account_or_character_source_urls():
    report = mature_sources.shape_build_level_probe(
        url=(
            "https://www.pathofexile.com/account/view-profile/SecretAccount/"
            "characters?characterName=SecretCharacter"
        ),
        status_code=404,
        payload="",
    )
    ninja_report = mature_sources.shape_build_level_probe(
        url="https://poe.ninja/builds/poe2/character/SecretAccount/SecretCharacter",
        status_code=404,
        payload="",
    )

    assert report["url"].startswith("source-url:www.pathofexile.com:")
    assert ninja_report["url"].startswith("source-url:poe.ninja:")
    assert "SecretAccount" not in str(report)
    assert "SecretCharacter" not in str(report)
    assert "SecretAccount" not in str(ninja_report)
    assert "SecretCharacter" not in str(ninja_report)
