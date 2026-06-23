from __future__ import annotations

from datetime import UTC, datetime
import sqlite3

from server.freshness import (
    Component,
    FreshnessDecision,
    SourceStatus,
)
from server.freshness import providers, service


NOW = datetime(2026, 6, 23, 9, 0, tzinfo=UTC)


def test_validated_release_is_shaped_as_local_component_evidence():
    records = providers.shape_validated_release(
        installed={
            "version": "v0.1.39",
            "app_version": "0.1.39",
            "pob_commit": "a82a33b4",
            "game_patch": "0.5.3",
        },
        corpus_info={"schema_version": 4, "built_at": "2026-06-23T04:00:00+00:00"},
        observed_at=NOW,
    )

    by_component = {record.component: record for record in records}
    assert set(by_component) == {
        Component.POB_ENGINE,
        Component.POB_DATA,
        Component.CORPUS,
    }
    assert by_component[Component.POB_ENGINE].version == "a82a33b4"
    assert by_component[Component.CORPUS].status is SourceStatus.CURRENT
    assert any(
        claim.key == "passive_tree" and claim.value == "0_5"
        for claim in by_component[Component.POB_DATA].claims
    )
    assert any(
        claim.key == "game_patch" and claim.value == "0.5.3"
        for claim in by_component[Component.POB_DATA].claims
    )


def test_local_report_refuses_to_infer_missing_official_and_meta_sources(monkeypatch):
    records = providers.shape_validated_release(
        installed={
            "version": "v0.1.39",
            "app_version": "0.1.39",
            "pob_commit": "a82a33b4",
        },
        corpus_info={"schema_version": 4, "built_at": "2026-06-23T04:00:00+00:00"},
        observed_at=NOW,
    )
    monkeypatch.setattr(providers, "collect_local_evidence", lambda observed_at: records)

    report = service.get_freshness_report(observed_at=NOW)

    assert report["decision"] == FreshnessDecision.BLOCKED_UNKNOWN.value
    assert any("game_patch" in reason for reason in report["blockers"])
    assert any("meta_snapshot" in reason for reason in report["blockers"])


def test_legacy_version_tool_cannot_promote_single_source_to_current(monkeypatch):
    from server import main

    strict = {
        "decision": FreshnessDecision.BLOCKED_UNKNOWN.value,
        "evidence": [],
        "blockers": ["required component game_patch has no evidence"],
        "warnings": [],
        "evaluated_at": NOW.isoformat(),
    }
    monkeypatch.setattr(main.freshness_service, "get_freshness_report", lambda: strict)
    monkeypatch.setattr(
        main.live_version,
        "check_data_version",
        lambda: {
            "local": {"built_at": "2026-06-23T04:00:00+00:00"},
            "upstream_last_modified": "Tue, 23 Jun 2026 04:00:00 GMT",
            "current_league": "Runes of Aldur",
            "recommendation": "up_to_date",
        },
    )

    result = main.check_data_version()

    assert result["recommendation"] == FreshnessDecision.BLOCKED_UNKNOWN.value
    assert result["freshness"] == strict
    assert result["legacy_corpus_probe"]["recommendation"] == "up_to_date"


def test_local_provider_degrades_on_sqlite_read_error(monkeypatch):
    monkeypatch.setattr(providers.live_update, "installed_meta", lambda: {})

    def fail_corpus_read():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(providers.db, "corpus_info", fail_corpus_read)

    assert providers.collect_local_evidence(NOW) == ()
