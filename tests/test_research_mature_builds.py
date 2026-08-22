from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import multiprocessing
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from server.compute import pob_code
from server import paths


RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
    "transientPacketPath",
    "transientPromptPath",
    "packet.json",
    "researcher_prompt.txt",
)


def _hold_research_accept_file_lock(
    lock_path: str,
    start_event,
    active,
    max_active,
    counter_lock,
) -> None:
    from server.learning.file_lock import interprocess_file_lock

    if not start_event.wait(timeout=10):
        raise RuntimeError("accept-lock test start event timed out")
    with interprocess_file_lock(Path(lock_path)):
        with counter_lock:
            active.value += 1
            max_active.value = max(max_active.value, active.value)
        try:
            time.sleep(0.25)
        finally:
            with counter_lock:
                active.value -= 1


def test_research_queue_defaults_to_runtime_memory_store():
    from scripts import research_mature_builds

    assert research_mature_builds.DEFAULT_MEMORY_DB_PATH == paths.mature_learning_path()
    assert research_mature_builds.DEFAULT_WORKER_COUNT == 5
    assert research_mature_builds._effective_worker_count(None) == 5
    assert research_mature_builds._effective_worker_count(0) == 1
    assert research_mature_builds._effective_worker_count(6) == 5


def test_queue_cli_allocates_a_distinct_default_run_directory_per_invocation(
    tmp_path, capsys, monkeypatch
):
    from scripts import research_mature_builds

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        research_mature_builds,
        "DEFAULT_OUTPUT_DIR",
        tmp_path / ".poe-bd-research",
    )
    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )

    reports = []
    for _ in range(2):
        code = research_mature_builds.main(["queue", "--source-file", str(source_file)])
        assert code == 0
        reports.append(json.loads(capsys.readouterr().out))

    first, second = reports
    assert first["runId"] != second["runId"]
    assert first["runDir"] != second["runDir"]
    assert first["nextCommandArgs"] == {"outputDir": first["runDir"]}
    assert second["nextCommandArgs"] == {"outputDir": second["runDir"]}
    for report in reports:
        run_dir = tmp_path / Path(report["runDir"])
        assert run_dir.parent.parent == tmp_path / ".poe-bd-research"
        assert (run_dir / research_mature_builds.QUEUE_DB_FILENAME).exists()
        assert research_mature_builds.queue_status(output_dir=run_dir)["queuedCount"] == 1
        packet_root = run_dir / research_mature_builds.DEFAULT_TEMP_DIRNAME
        assert list(packet_root.glob("poe-bd-creator-research-packet-*/packet.json"))
        claim = research_mature_builds.claim_case(output_dir=run_dir, lease_seconds=1800)
        inspected = research_mature_builds.inspect_case(
            output_dir=run_dir,
            lease_token=claim["leaseToken"],
        )
        assert inspected["status"] == "ok"
        assert inspected["sampleId"] == claim["sampleId"]


def test_queue_refuses_to_overwrite_an_existing_queue(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-no-overwrite"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=temp_root,
    )
    db_path = output_dir / research_mature_builds.QUEUE_DB_FILENAME
    original_db = db_path.read_bytes()

    with pytest.raises(FileExistsError, match="already exists"):
        research_mature_builds.queue_cases(
            source_files=[source_file],
            output_dir=output_dir,
            temp_root=temp_root,
        )

    assert db_path.read_bytes() == original_db
    assert research_mature_builds.queue_status(output_dir=output_dir)["queuedCount"] == 1


def test_queue_re_research_rebuilds_prior_run_cases_as_supplement(tmp_path, capsys, monkeypatch):
    from scripts import research_mature_builds

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        research_mature_builds,
        "DEFAULT_OUTPUT_DIR",
        tmp_path / ".poe-bd-research",
    )
    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    code = research_mature_builds.main(["queue", "--source-file", str(source_file)])
    assert code == 0
    prior_report = json.loads(capsys.readouterr().out)
    prior_run_dir = tmp_path / Path(prior_report["runDir"])
    with sqlite3.connect(prior_run_dir / research_mature_builds.QUEUE_DB_FILENAME) as conn:
        prior_sample_id = conn.execute("SELECT sample_id FROM cases").fetchone()[0]

    code = research_mature_builds.main(
        [
            "queue",
            "--re-research",
            str(prior_run_dir),
            "--supplement-focus",
            "补录骷髅军团配装与资源账本",
        ]
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["reSupplementCaseCount"] == 1
    assert report["reSupplementSkippedUnrecoverableCount"] == 0
    run_dir = tmp_path / Path(report["runDir"])
    assert run_dir != prior_run_dir
    status = research_mature_builds.queue_status(output_dir=run_dir)
    assert status["queuedCount"] == 1
    with sqlite3.connect(run_dir / research_mature_builds.QUEUE_DB_FILENAME) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT supplement, supplement_context, source_hash, sample_id FROM cases"
        ).fetchone()
    assert row["supplement"] == 1
    assert row["supplement_context"] == "补录骷髅军团配装与资源账本"
    assert row["source_hash"]
    assert row["sample_id"] == prior_sample_id


def test_queue_re_research_requires_prior_queue_db(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        research_mature_builds,
        "DEFAULT_OUTPUT_DIR",
        tmp_path / ".poe-bd-research",
    )
    with pytest.raises(ValueError, match="re-research run directory has no"):
        research_mature_builds.queue_cases(
            re_research_run_dir=tmp_path / "missing",
            output_dir=tmp_path / "out",
            temp_root=tmp_path / "temp",
        )
    with pytest.raises(ValueError, match="cannot be combined"):
        research_mature_builds.queue_cases(
            re_research_run_dir=tmp_path / "missing",
            source_files=[tmp_path / "sample.txt"],
            output_dir=tmp_path / "out2",
            temp_root=tmp_path / "temp2",
        )


def test_cli_targeted_supplement_preflight_does_not_allocate_run(tmp_path, capsys, monkeypatch):
    from scripts import research_mature_builds

    output_root = tmp_path / ".poe-bd-research"
    monkeypatch.setattr(research_mature_builds, "DEFAULT_OUTPUT_DIR", output_root)

    code = research_mature_builds.main(["queue", "--supplement-sample-id", "case:fixture"])

    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "collector_failed"
    runs_root = output_root / research_mature_builds.RUNS_DIRNAME
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


def test_cases_from_prior_run_skips_rows_without_quarantine_material(tmp_path):
    from scripts import research_mature_builds

    prior = tmp_path / "prior"
    prior.mkdir()
    raw_source = _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
    source_hash = hashlib.sha256(raw_source.encode("utf-8")).hexdigest()
    source_hash_ref = f"source-hash:{source_hash[:16]}"
    db_path = prior / research_mature_builds.QUEUE_DB_FILENAME
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_hash TEXT NOT NULL UNIQUE,
                source_hash_ref TEXT NOT NULL,
                character_ref TEXT NOT NULL DEFAULT '',
                league TEXT NOT NULL,
                level INTEGER NOT NULL,
                class_name TEXT NOT NULL,
                ascendancy TEXT NOT NULL,
                main_skill TEXT NOT NULL,
                safe_error TEXT NOT NULL,
                packet_id TEXT NOT NULL,
                packet_safe_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO cases(sample_id, status, source_type, source_hash, source_hash_ref, "
            "league, level, class_name, ascendancy, main_skill, safe_error, packet_id, "
            "packet_safe_hash, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "case:with-quarantine",
                "accepted",
                "local_pob_code_file",
                source_hash,
                source_hash_ref,
                "league-x",
                95,
                "Ranger",
                "Deadeye",
                "LightningArrowPlayer",
                "",
                "packet-id",
                "packet-hash",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO cases(sample_id, status, source_type, source_hash, source_hash_ref, "
            "league, level, class_name, ascendancy, main_skill, safe_error, packet_id, "
            "packet_safe_hash, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "case:without-quarantine",
                "accepted",
                "local_pob_code_file",
                "hash-without-material",
                "source-hash:hash-without",
                "league-x",
                95,
                "Ranger",
                "Deadeye",
                "LightningArrowPlayer",
                "",
                "packet-id",
                "packet-hash",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            ),
        )
    quarantine = prior / "quarantine"
    quarantine.mkdir()
    payload = {
        "sampleId": "case:with-quarantine",
        "sourceHash": source_hash,
        "sourceHashRef": source_hash_ref,
        "rawImportCode": raw_source,
    }
    (quarantine / f"{source_hash}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    cases, skipped = research_mature_builds._cases_from_prior_run(
        prior, supplement_focus="聚焦清单"
    )
    assert skipped == 1
    assert len(cases) == 1
    assert cases[0]["sampleId"] == "case:with-quarantine"
    assert cases[0]["supplement"] is True
    assert cases[0]["supplementContext"] == "聚焦清单"
    assert cases[0]["sourceHash"] == source_hash

    selected, selected_skipped = research_mature_builds._cases_from_prior_run(
        prior,
        supplement_sample_ids=["case:with-quarantine", "case:with-quarantine"],
        supplement_focus="定向聚焦",
    )
    assert selected_skipped == 0
    assert [case["sampleId"] for case in selected] == ["case:with-quarantine"]
    assert selected[0]["supplementContext"] == "定向聚焦"

    quarantine_path = quarantine / f"{source_hash}.json"
    for field, value in (
        ("sampleId", "case:other"),
        ("sourceHash", "0" * 64),
        ("rawImportCode", raw_source + "tampered"),
    ):
        tampered = dict(payload)
        tampered[field] = value
        quarantine_path.write_text(json.dumps(tampered), encoding="utf-8")
        selection = research_mature_builds.inspect_supplement_selection(
            prior, ["case:with-quarantine"]
        )
        assert selection["status"] == "invalid"
        assert selection["unrecoverableSupplementSampleIds"] == ["case:with-quarantine"]
    quarantine_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid targeted supplement selection"):
        research_mature_builds._cases_from_prior_run(
            prior,
            supplement_sample_ids=["case:missing"],
        )
    with pytest.raises(ValueError, match="invalid targeted supplement selection"):
        research_mature_builds._cases_from_prior_run(
            prior,
            supplement_sample_ids=["case:without-quarantine"],
        )
    with pytest.raises(ValueError, match="at least one sampleId"):
        research_mature_builds._cases_from_prior_run(
            prior,
            supplement_sample_ids=[],
        )


def test_queue_forwards_optional_ninja_class_filter(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    captured: dict = {}

    def fake_cases_from_ninja(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        research_mature_builds.legacy_batch,
        "_cases_from_ninja",
        fake_cases_from_ninja,
    )
    output_dir = tmp_path / "research"
    queued = research_mature_builds.queue_cases(
        league_url="runesofaldur",
        limit=3,
        level_min=95,
        level_max=95,
        ninja_classes=["Blood+Mage"],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-ninja-class-filter",
    )

    assert captured["ninja_classes"] == ["Blood Mage"]
    with sqlite3.connect(output_dir / research_mature_builds.QUEUE_DB_FILENAME) as conn:
        stored = conn.execute("SELECT value FROM metadata WHERE key = 'ninjaClasses'").fetchone()[0]
    assert json.loads(stored) == ["Blood Mage"]
    assert queued["status"] == "source_unavailable"
    assert queued["errorKind"] == "source_unavailable"
    assert queued["requestedSampleCount"] == 3
    assert queued["availableSampleCount"] == 0
    assert queued["sampleShortfallCount"] == 3
    assert queued["queueCreated"] is True
    assert research_mature_builds.queue_status(output_dir=output_dir)["status"] == (
        "source_unavailable"
    )
    with sqlite3.connect(output_dir / research_mature_builds.QUEUE_DB_FILENAME) as conn:
        conn.execute("DELETE FROM metadata WHERE key IN ('queueStatus', 'requestedSampleCount')")
        conn.commit()
    legacy_status = research_mature_builds.queue_status(output_dir=output_dir)
    assert legacy_status["status"] == "source_unavailable"
    assert legacy_status["requestedSampleCount"] == 3
    assert legacy_status["sampleShortfallCount"] == 3


def _ninja_case_for_queue(
    *, source: str, account: str = "acctA", name: str = "CharA", league: str = "runesofaldur"
) -> dict:
    from scripts import run_phase45_researcher_batch as legacy_batch
    from server.knowledge import research_intake_ledger

    return legacy_batch._case_from_source(
        source,
        source_hash=legacy_batch._safe_hash(source),
        sample_id="case:phase45-researcher-001",
        source_type="poe_ninja_import_code",
        league=league,
        row={"account": account, "name": name},
        character_ref=research_intake_ledger.character_ref(account, name),
    )


def test_queue_records_intake_ledger_and_reports_intake_counts(tmp_path, monkeypatch):
    from scripts import research_mature_builds
    from server.knowledge import research_intake_ledger

    ledger_path = tmp_path / "intake-ledger.sqlite"
    captured: dict = {}
    character_ref = research_intake_ledger.character_ref("acctA", "CharA")

    def fake_cases_from_ninja(**kwargs):
        captured.update(kwargs)
        return [
            _ninja_case_for_queue(
                source=_sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
            )
        ]

    monkeypatch.setattr(
        research_mature_builds.legacy_batch,
        "_cases_from_ninja",
        fake_cases_from_ninja,
    )
    output_dir = tmp_path / "research"
    queued = research_mature_builds.queue_cases(
        league_url="runesofaldur",
        limit=1,
        level_min=95,
        level_max=95,
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-intake",
        intake_ledger_path=ledger_path,
    )

    assert captured["intake_ledger_path"] == ledger_path
    assert queued["status"] == "queued"
    assert queued["queuedCount"] == 1
    assert queued["intakePagesFetched"] == 0
    assert queued["intakeSkippedAlreadyResearched"] == 0
    assert queued["intakeLedgerRecordedCount"] == 1
    assert queued["intakeLedgerSummary"]["used"] is True
    assert queued["intakeLedgerSummary"]["totalRecords"] == 1
    assert research_intake_ledger.seen_character_refs(ledger_path, "runesofaldur") == {
        character_ref
    }
    assert (
        research_mature_builds.queue_status(output_dir=output_dir)["intakeLedgerRecordedCount"] == 1
    )
    _assert_safe_payload(queued, tmp_path.parent)


def test_queue_dry_run_reports_intake_but_never_writes_ledger(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    ledger_path = tmp_path / "intake-ledger-dry-run.sqlite"
    stats_capture: dict = {}

    def fake_cases_from_ninja(**kwargs):
        stats = kwargs.get("collector_stats") or {}
        stats["pagesFetched"] = 2
        stats["pageRowsSeen"] = 5
        stats["skippedAlreadyResearched"] = 3
        stats_capture.update(stats)
        return []

    monkeypatch.setattr(
        research_mature_builds.legacy_batch,
        "_cases_from_ninja",
        fake_cases_from_ninja,
    )
    queued = research_mature_builds.queue_cases(
        league_url="runesofaldur",
        limit=2,
        level_min=95,
        level_max=95,
        output_dir=tmp_path / "dry-run-dir",
        temp_root=tmp_path.parent / "poe-research-temp-intake-dry",
        dry_run=True,
        intake_ledger_path=ledger_path,
    )

    assert queued["status"] == "dry_run"
    assert queued["intakePagesFetched"] == 2
    assert queued["intakePageRowsSeen"] == 5
    assert queued["intakeSkippedAlreadyResearched"] == 3
    assert queued["intakeLedgerRecordedCount"] == 0
    assert not ledger_path.exists()


def test_queue_local_sources_never_touch_intake_ledger(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    ledger_path = tmp_path / "intake-ledger-local.sqlite"
    queued = research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=tmp_path / "research-local",
        temp_root=tmp_path.parent / "poe-research-temp-intake-local",
        intake_ledger_path=ledger_path,
    )

    assert queued["queuedCount"] == 1
    assert queued["intakeLedgerRecordedCount"] == 0
    assert queued["intakeLedgerSummary"] == {
        "used": False,
        "reason": "local_source_input",
        "totalRecords": 0,
        "byStatus": {},
        "league": "",
    }
    assert not ledger_path.exists()


def test_queue_accept_promotes_intake_ledger_record(tmp_path, monkeypatch):
    from scripts import research_mature_builds
    from server.knowledge import research_intake_ledger

    ledger_path = tmp_path / "intake-ledger-accept.sqlite"
    character_ref = research_intake_ledger.character_ref("acctA", "CharA")

    def fake_cases_from_ninja(**kwargs):
        return [
            _ninja_case_for_queue(
                source=_sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
            )
        ]

    monkeypatch.setattr(
        research_mature_builds.legacy_batch,
        "_cases_from_ninja",
        fake_cases_from_ninja,
    )
    output_dir = tmp_path / "research-accept"
    research_mature_builds.queue_cases(
        league_url="runesofaldur",
        limit=1,
        level_min=95,
        level_max=95,
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-intake-accept",
        intake_ledger_path=ledger_path,
    )
    assert research_intake_ledger.summary(ledger_path, league="runesofaldur")["byStatus"] == {
        "queued": 1
    }

    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)

    def fake_accept_deep_review_candidates(**kwargs):
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "acceptedSemanticEdgeCount": 2,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory.sqlite",
        intake_ledger_path=ledger_path,
    )

    assert accepted["status"] == "accepted"
    assert accepted["acceptedSemanticEdgeCount"] == 2
    import sqlite3

    queue_db = research_mature_builds._queue_db_path(output_dir, None)
    with sqlite3.connect(queue_db) as conn:
        row = conn.execute(
            "SELECT accepted_semantic_edge_count FROM cases WHERE sample_id = ?",
            (claimed["sampleId"],),
        ).fetchone()
        assert row[0] == 2
    assert research_intake_ledger.summary(ledger_path, league="runesofaldur")["byStatus"] == {
        "accepted": 1
    }
    assert research_intake_ledger.seen_character_refs(ledger_path, "runesofaldur") == {
        character_ref
    }


def test_queue_intake_summary_uses_resolved_league_for_current(tmp_path, monkeypatch):
    from scripts import research_mature_builds
    from server.knowledge import research_intake_ledger

    ledger_path = tmp_path / "intake-ledger-current.sqlite"
    character_ref = research_intake_ledger.character_ref("acctA", "CharA")
    research_intake_ledger.record_case(
        ledger_path,
        league="runesofaldur",
        character_ref=character_ref,
        source_hash="old-run",
    )

    def fake_cases_from_ninja(**kwargs):
        stats = kwargs.get("collector_stats") or {}
        stats["resolvedLeague"] = "runesofaldur"
        return []

    monkeypatch.setattr(
        research_mature_builds.legacy_batch,
        "_cases_from_ninja",
        fake_cases_from_ninja,
    )
    queued = research_mature_builds.queue_cases(
        league_url="current",
        limit=2,
        level_min=95,
        level_max=95,
        output_dir=tmp_path / "research-current",
        temp_root=tmp_path.parent / "poe-research-temp-current",
        intake_ledger_path=ledger_path,
    )

    assert queued["intakeLedgerSummary"]["used"] is True
    assert queued["intakeLedgerSummary"]["league"] == "runesofaldur"
    assert queued["intakeLedgerSummary"]["totalRecords"] == 1
    assert queued["intakeLedgerSummary"]["byStatus"] == {"queued": 1}


def test_queue_status_returns_persisted_intake_ledger_summary_and_tolerates_old_db(
    tmp_path, monkeypatch
):
    from scripts import research_mature_builds

    ledger_path = tmp_path / "intake-ledger-status.sqlite"

    def fake_cases_from_ninja(**kwargs):
        stats = kwargs.get("collector_stats") or {}
        stats["resolvedLeague"] = "runesofaldur"
        return [
            _ninja_case_for_queue(
                source=_sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
            )
        ]

    monkeypatch.setattr(
        research_mature_builds.legacy_batch,
        "_cases_from_ninja",
        fake_cases_from_ninja,
    )
    output_dir = tmp_path / "research-status"
    research_mature_builds.queue_cases(
        league_url="current",
        limit=1,
        level_min=95,
        level_max=95,
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-status",
        intake_ledger_path=ledger_path,
    )

    status = research_mature_builds.queue_status(output_dir=output_dir)
    assert status["intakeLedgerSummary"]["used"] is True
    assert status["intakeLedgerSummary"]["league"] == "runesofaldur"
    assert status["intakeLedgerSummary"]["totalRecords"] == 1
    assert status["intakeLedgerRecordedCount"] == 1

    with sqlite3.connect(output_dir / research_mature_builds.QUEUE_DB_FILENAME) as conn:
        conn.execute("DELETE FROM metadata WHERE key = 'intakeLedgerSummary'")
        conn.commit()
    legacy_status = research_mature_builds.queue_status(output_dir=output_dir)
    # The queue-time snapshot is gone, but the live ledger re-read still reports the
    # promoted rows (accepts never touched this ledger, so the row stays queued).
    assert legacy_status["intakeLedgerSummary"] == {
        "used": True,
        "league": "runesofaldur",
        "totalRecords": 1,
        "byStatus": {"queued": 1},
    }
    assert legacy_status["intakeLedgerSource"] == "live"


def test_research_quality_summary_persists_deferred_reason_counts_for_status(tmp_path):
    from scripts import research_mature_builds

    summary = research_mature_builds._research_quality_summary(
        {
            "acceptanceMode": "partial_with_deferred",
            "deferredReasonCounts": {"invalid_schema": 1, "insufficient_gear_context": 2},
        }
    )
    assert summary["deferredReasonCounts"] == {
        "invalid_schema": 1,
        "insufficient_gear_context": 2,
    }

    # The stored summary is merged into every per-sample status row, so the reason
    # breakdown survives the accept -> status round trip without any schema change.
    db_path = tmp_path / "queue-status-deferred.sqlite"
    research_mature_builds._init_db(db_path)
    now = "2026-08-18T00:00:00+00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO cases (
                sample_id, status, source_type, source_hash, source_hash_ref, league,
                level, class_name, ascendancy, main_skill, safe_error, packet_id,
                packet_safe_hash, created_at, updated_at, research_quality_summary
            ) VALUES (?, 'accepted', 'local', 'h', 'h', 'runesofaldur', 97, 'Witch',
                'Abyssal Lich', 'Thrashing Vines', '', 'p', 's', ?, ?, ?)
            """,
            (
                "case:deferred-snapshot",
                now,
                now,
                json.dumps(summary, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.commit()
    rows = research_mature_builds._fetch_cases(db_path)
    assert rows[0]["deferredReasonCounts"] == {
        "invalid_schema": 1,
        "insufficient_gear_context": 2,
    }


def test_queue_cli_stops_when_live_source_has_no_usable_samples(tmp_path, capsys, monkeypatch):
    from scripts import research_mature_builds

    monkeypatch.setattr(
        research_mature_builds.legacy_batch,
        "_cases_from_ninja",
        lambda **kwargs: [],
    )

    code = research_mature_builds.main(
        [
            "queue",
            "--output-dir",
            str(tmp_path / "research"),
            "--limit",
            "5",
            "--class",
            "Gemling+Legionnaire",
            "--level-min",
            "81",
            "--level-max",
            "81",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["status"] == "source_unavailable"
    assert payload["errorKind"] == "source_unavailable"
    assert payload["sampleCount"] == 0
    assert payload["requestedSampleCount"] == 5
    assert payload["availableSampleCount"] == 0
    assert payload["sampleShortfallCount"] == 5
    assert payload["queuedCount"] == 0
    assert payload["queueCreated"] is True
    assert "claim" in payload["nextStep"]
    _assert_safe_payload(payload, tmp_path.parent)


def test_research_sample_id_is_stable_across_separate_queue_runs(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    first = research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=tmp_path / "first",
        temp_root=tmp_path.parent / "poe-research-temp-stable-id-first",
        dry_run=True,
    )
    second = research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=tmp_path / "second",
        temp_root=tmp_path.parent / "poe-research-temp-stable-id-second",
        sample_start_index=99,
        dry_run=True,
    )

    assert first["samples"][0]["sampleId"] == second["samples"][0]["sampleId"]
    assert first["samples"][0]["sampleId"].startswith("case:poe-bd-research-")


def test_queue_claim_and_prompt_expose_only_safe_bounded_navigation(tmp_path):
    from scripts import research_mature_builds

    batch_file = tmp_path / "samples.txt"
    batch_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
        + "\n---POB-SAMPLE---\n"
        + _sample_code("SparkPlayer", ascendancy="Stormweaver", level=96),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp"

    queued = research_mature_builds.queue_cases(
        source_batch_files=[batch_file],
        output_dir=output_dir,
        temp_root=temp_root,
        worker_count=5,
        ttl_seconds=3600,
    )

    assert queued["status"] == "queued"
    assert queued["queueKind"] == "poe_bd_research_external_agent_queue"
    assert queued["sampleCount"] == 2
    assert queued["requestedWorkerCount"] == 5
    assert queued["workerCountSemantics"] == "parallel_subagents_one_case_each"
    assert "preparedCount" not in queued
    _assert_safe_payload(queued, tmp_path.parent)

    queue_db = output_dir / "poe_bd_research_queue.sqlite"
    db_bytes = queue_db.read_bytes()
    assert not any(marker.encode("utf-8") in db_bytes for marker in RAW_MARKERS)
    assert str(temp_root).encode("utf-8") not in db_bytes

    first = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    second = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    assert first["status"] == "claimed"
    assert second["status"] == "claimed"
    assert second["sampleId"] != first["sampleId"]
    assert first["mainSkillAuthority"] == "programmatic_snapshot_non_authoritative"
    assert first["packetSafeHash"]
    assert first["reviewFile"].startswith("reviews/")
    assert "这是当前案例的安全导航 brief" in first["workerPrompt"]
    assert "当前 lease 的唯一 worker" in first["workerPrompt"]
    assert "不得领取第二个案例" in first["workerPrompt"]
    assert "--output-dir <runDir>" in first["workerPrompt"]
    assert first["leaseToken"] in first["workerPrompt"]
    _assert_safe_payload(first, tmp_path.parent)
    _assert_safe_payload(second, tmp_path.parent)

    prompt_text = research_mature_builds.render_claim_prompt(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=first["leaseToken"],
    )

    prompt_payload = json.loads(prompt_text)
    assert prompt_payload["deprecatedRawPrompt"] is True
    assert prompt_payload["recommendedReadOrder"] == [
        "skills",
        "gear",
        "jewels",
        "passives",
        "config",
        "build",
    ]
    _assert_safe_payload(prompt_payload, tmp_path.parent)

    status = research_mature_builds.queue_status(output_dir=output_dir)
    assert status["claimedCount"] == 2
    assert status["acceptingCount"] == 0
    assert status["queuedCount"] == 0
    assert all("acceptedDeepRecordCount" in sample for sample in status["samples"])
    assert all(
        sample["mainSkillAuthority"] == "programmatic_snapshot_non_authoritative"
        for sample in status["samples"]
    )
    assert all("unresolvedDeepRecordComponentCount" in sample for sample in status["samples"])
    assert all("unresolvedDeepRecordMentionCount" in sample for sample in status["samples"])
    assert all("unresolvedUniqueComponentCount" in sample for sample in status["samples"])
    _assert_safe_payload(status, tmp_path.parent)


def test_queue_claim_capacity_releases_after_one_case_is_accepted(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    batch_file = tmp_path / "seven-samples.txt"
    batch_file.write_text(
        "\n---POB-SAMPLE---\n".join(
            _sample_code(f"ConcurrentPlayer{index}", ascendancy="Deadeye", level=95)
            for index in range(7)
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research-capacity"
    research_mature_builds.queue_cases(
        source_batch_files=[batch_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-capacity",
        worker_count=5,
    )

    claimed = [
        research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
        for _ in range(5)
    ]
    capacity = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    assert {item["status"] for item in claimed} == {"claimed"}
    assert len({item["sampleId"] for item in claimed}) == 5
    assert len({item["leaseToken"] for item in claimed}) == 5
    assert capacity == {
        "status": "worker_capacity_reached",
        "queueKind": "poe_bd_research_external_agent_queue",
        "activeCaseCount": 5,
        "workerCount": 5,
        "noRawMatureBuildMaterial": True,
    }

    first = claimed[0]
    review_file = output_dir / first["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, first)

    def fake_accept_deep_review_candidates(**kwargs):
        status = research_mature_builds.queue_status(output_dir=output_dir)
        assert status["acceptingCount"] == 1
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        research_mature_builds.acceptance,
        "accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=first["leaseToken"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory-capacity.sqlite",
    )
    replacement = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    status = research_mature_builds.queue_status(output_dir=output_dir)

    assert replacement["status"] == "claimed"
    assert replacement["sampleId"] not in {item["sampleId"] for item in claimed}
    assert status["acceptedCount"] == 1
    assert status["claimedCount"] == 5
    assert status["acceptingCount"] == 0
    assert status["queuedCount"] == 1


def test_concurrent_claims_are_atomic_and_bounded_to_five_workers(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    batch_file = tmp_path / "ten-samples.txt"
    batch_file.write_text(
        "\n---POB-SAMPLE---\n".join(
            _sample_code(f"AtomicPlayer{index}", ascendancy="Deadeye", level=95)
            for index in range(10)
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research-atomic-claim"
    research_mature_builds.queue_cases(
        source_batch_files=[batch_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-atomic-claim",
        worker_count=5,
    )
    monkeypatch.setattr(research_mature_builds, "_identity_resolvability_hint", lambda **_: {})
    barrier = threading.Barrier(8)

    def claim_once():
        barrier.wait(timeout=5)
        return research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: claim_once(), range(8)))

    claimed = [item for item in results if item["status"] == "claimed"]
    at_capacity = [item for item in results if item["status"] == "worker_capacity_reached"]
    status = research_mature_builds.queue_status(output_dir=output_dir)

    assert len(claimed) == 5
    assert len(at_capacity) == 3
    assert len({item["sampleId"] for item in claimed}) == 5
    assert len({item["leaseToken"] for item in claimed}) == 5
    assert status["claimedCount"] == 5
    assert status["queuedCount"] == 5


def test_worker_brief_is_safe_inline_and_explains_tool_fallback(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    monkeypatch.chdir(tmp_path)
    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("MirageDeadeyePlayer", ascendancy="Pathfinder", level=100),
        encoding="utf-8",
    )
    output_dir = Path(".poe-bd-research")
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-worker-brief",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    assert claimed["reviewFile"].startswith("reviews/")
    assert claimed["workerPrompt"]

    brief = research_mature_builds.render_worker_brief(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
    )

    assert brief["status"] == "ok"
    assert brief["sampleId"] == claimed["sampleId"]
    assert brief["reviewFile"].startswith("reviews/")
    prompt = brief["workerPrompt"]
    assert "这是当前案例的安全导航 brief" in prompt
    assert "当前 lease 的唯一 worker" in prompt
    assert "不得领取第二个案例" in prompt
    assert "inspect" in prompt
    assert "read" in prompt
    assert "programmatic mainSkill candidate" in prompt
    assert "非权威快照线索" in prompt
    assert "tool discovery / tool search" in prompt
    assert "工具可能采用延迟发现" in prompt
    assert "lookup_mechanic" in prompt
    assert "mechanicAudit" in prompt
    assert "revision-pinned sourceRef" in prompt
    assert "不得拼接 `A / B`" in prompt
    assert "最强因果结论" in prompt
    assert "不要读源码或临时构造 service" in prompt
    assert "safeReviewFile" in prompt
    assert "review-contract" in prompt
    assert "accept --output-dir <runDir> --lease-token" in prompt
    assert "--validate-only" in prompt
    assert "不得自造枚举" in prompt
    assert "componentKey" in prompt
    assert "两空格缩进的多行 JSON" in prompt
    assert "fullyResolvedForAccept" in prompt
    assert "partial_with_deferred" in prompt
    assert "DeepResearchRecord" in prompt
    assert "完整保留该机制包" in prompt
    assert "以下 16 项是提交前的强制自检" in prompt
    for index, check in enumerate(research_mature_builds.RESEARCH_MANDATORY_CHECKS, start=1):
        assert f"{index}. {check}" in prompt
    assert "以下十五项" not in prompt
    assert '"patternType": "build_archetype"' not in prompt
    assert "SKILL.md" not in prompt
    _assert_safe_payload(brief, tmp_path.parent)


def test_review_contract_discloses_exact_enums_just_before_writing(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("MirageDeadeyePlayer", ascendancy="Pathfinder", level=100),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-review-contract",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    contract = research_mature_builds.render_review_contract(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
    )

    assert contract["status"] == "ok"
    assert contract["reviewFile"] == claimed["reviewFile"]
    assert contract["topLevelTemplate"]["artifactIdentity"] == {
        "sampleId": claimed["sampleId"],
        "caseRef": claimed["sourceHashRef"],
        "safeEvidenceRef": f"evidence:{claimed['packetSafeHash'][:16]}",
        "packetSafeHash": claimed["packetSafeHash"],
    }
    assert contract["topLevelTemplate"]["caseCoverage"]["supports"] == "evidence_missing"
    assert contract["topLevelTemplate"]["mechanicAudit"] == []
    assert contract["mechanicAuditTemplate"]["wiki"]["sourceRef"].startswith("poe2wiki:page:")
    assert contract["mechanicAuditTemplate"]["wiki"]["matchKind"].startswith("direct")
    assert "Research Agent" in contract["mechanicAuditTemplate"]["wiki"]["relevanceReason"]
    assert contract["mechanicAuditTemplate"]["decision"] == "keep"
    assert "contradicts" in contract["allowedValues"]["mechanicAuditWikiStatus"]
    assert "source_artifact" in contract["allowedValues"]["mechanicAuditCorroboration"]
    assert "search_candidate" in contract["allowedValues"]["mechanicAuditMatchKind"]
    assert contract["candidateTemplate"]["claimScopeReview"]["verdict"] == "supported"
    assert any("mechanic_chain 和 resource_engine" in rule for rule in contract["rules"])
    assert any("A / B" in rule for rule in contract["rules"])
    family_rules = [rule for rule in contract["rules"] if "BuildFamily" in rule]
    assert family_rules
    assert any(
        "trigger_host" in rule and "不自动进入" in rule and "不改变 key" in rule
        for rule in family_rules
    )
    assert not any(
        "trigger_host 由程序自动参与" in rule or "trigger_host roles" in rule
        for rule in contract["rules"]
    )
    assert (
        "clear/boss/triggered_payload"
        in contract["typedPayloadSchema"]["familyCoreSkillKeys"]["rule"]
    )
    assert "trigger hosts" in contract["typedPayloadSchema"]["familyCoreSkillKeys"]["rule"]
    assert "support_modifier" in contract["allowedValues"]["componentRole"]
    assert "burst_window" not in contract["allowedValues"]["componentRole"]
    assert contract["artifactEncoding"] == {
        "format": "json",
        "encoding": "utf-8",
        "prettyPrinted": True,
        "indent": 2,
    }
    assert "notable" in contract["componentRoleNodeTypeCompatibility"]["payoff"]
    assert contract["componentRoleNodeTypeCompatibility"]["gear_base"] == ["item_base"]
    assert "unique" in contract["componentRoleNodeTypeCompatibility"]["weapon_base"]
    assert contract["recordTemplate"]["components"][0]["componentKey"] is None
    assert "sampleId" not in contract["recordTemplate"]
    assert "caseRef" not in contract["candidateTemplate"]
    assert contract["allowedValues"]["transferScope"] == ["family", "component"]
    assert contract["allowedValues"]["gearResponsibilityType"] == [
        "budget_substitute",
        "defense",
        "identity_enabler",
        "optional_upgrade",
        "primary_skill_source",
        "recovery",
        "resource_or_spirit",
        "scaling",
        "utility",
    ]
    assert contract["candidateTemplate"]["transferScope"] == "family"
    assert contract["mandatoryChecks"] == list(research_mature_builds.RESEARCH_MANDATORY_CHECKS)
    assert len(contract["mandatoryChecks"]) == 16
    assert "wiki 缺页强制新增" in contract["mandatoryChecks"][9]
    assert "semantic edge" in contract["mandatoryChecks"][14]
    assert "memoryUse" in contract["mandatoryChecks"][15]
    assert "skill:..." in contract["memoryUseQuerySchema"]["primarySkillKey"]
    assert "gem:..." in contract["memoryUseQuerySchema"]["primarySkillKey"]
    assert "bf-..." in contract["memoryUseQuerySchema"]["buildFamilyKeys"]
    assert "never place skill:/gem:" in contract["memoryUseQuerySchema"]["buildFamilyKeys"]
    assert "gearResponsibilities" in contract["allowedValues"]["typedIdentityFields"]
    gear_rule = contract["typedPayloadSchema"]["gearResponsibilities"]["rule"]
    assert "explicitly set gearResponsibilities=[]" in gear_rule
    assert "missing or null field is not this declaration" in gear_rule
    assert "supportCoverageExceptions" in contract["allowedValues"]["typedIdentityFields"]
    assert (
        "skillName/supportNames"
        in contract["allowedValues"]["typedIdentityFields"]["supportPackages"]
    )
    assert "applicabilityRequirements" in contract["candidateTemplate"]
    assert "exclusionConditions" in contract["candidateTemplate"]
    assert "不得自造 role" in contract["rules"][0]
    assert any(
        "support_modifier 等非主动技能组件不改变该豁免" in rule for rule in contract["rules"]
    )
    assert any("字段缺失/null 不算声明" in rule for rule in contract["rules"])
    assert contract["nextActions"] == [
        "init-review",
        "edit_review",
        "accept --validate-only",
        "accept",
    ]
    _assert_safe_payload(contract, tmp_path.parent)


def test_init_review_creates_pretty_utf8_skeleton_and_never_overwrites(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("MirageDeadeyePlayer", ascendancy="Pathfinder", level=100),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-init-review",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    initialized = research_mature_builds.init_review(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
    )
    review_path = output_dir / claimed["reviewFile"]
    raw = review_path.read_bytes()
    text = raw.decode("utf-8")
    payload = json.loads(text)

    assert initialized["status"] == "initialized"
    assert initialized["created"] is True
    assert initialized["reviewFile"] == claimed["reviewFile"]
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert text.endswith("\n")
    assert '\n  "caseCoverage": {' in text
    assert payload["reportId"] == "poe_bd_research_review"
    assert payload["reviewContractVersion"] == "phase4-safe-review-v2"
    assert payload["safeArtifactOnly"] is True
    assert payload["artifactIdentity"] == {
        "sampleId": claimed["sampleId"],
        "caseRef": claimed["sourceHashRef"],
        "safeEvidenceRef": f"evidence:{claimed['packetSafeHash'][:16]}",
        "packetSafeHash": claimed["packetSafeHash"],
    }
    assert payload["deepResearchRecords"] == []
    assert payload["candidateReviews"] == []
    assert payload["semanticEdges"] == []
    assert payload["mechanicAudit"] == []

    review_path.write_text(text.replace("evidence_missing", "covered", 1), encoding="utf-8")
    existing = research_mature_builds.init_review(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
    )
    assert existing["status"] == "already_exists"
    assert existing["created"] is False
    assert (
        json.loads(review_path.read_text(encoding="utf-8"))["caseCoverage"]["supports"] == "covered"
    )
    _assert_safe_payload(initialized, tmp_path.parent)
    _assert_safe_payload(existing, tmp_path.parent)


def test_init_review_rejects_wrong_or_expired_lease(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-init-review-lease",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    with pytest.raises(ValueError, match="lease"):
        research_mature_builds.init_review(output_dir=output_dir, lease_token="wrong-token")
    _expire_case_lease(output_dir / "poe_bd_research_queue.sqlite", claimed["sampleId"])
    with pytest.raises(ValueError, match="lease"):
        research_mature_builds.init_review(
            output_dir=output_dir,
            lease_token=claimed["leaseToken"],
        )
    assert not (output_dir / claimed["reviewFile"]).exists()


def test_init_review_cli_returns_safe_bounded_metadata(tmp_path, capsys):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-init-review-cli",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    code = research_mature_builds.main(
        [
            "init-review",
            "--output-dir",
            str(output_dir),
            "--lease-token",
            claimed["leaseToken"],
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "initialized"
    assert payload["reviewFile"] == claimed["reviewFile"]
    assert payload["noRawMatureBuildMaterial"] is True
    _assert_safe_payload(payload, tmp_path.parent)


def test_claim_lease_token_is_argparse_safe(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-lease-token-prefix",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    token = claimed["leaseToken"]
    assert token[0].isalnum(), "lease token must never start with '-' (argparse option clash)"
    # urlsafe alphabet + a letter prefix keeps the token slug-stable for review/acceptance names.
    assert research_mature_builds._slug(token) == token


def test_lease_token_argv_rewrite_only_touches_lease_token():
    from scripts import research_mature_builds

    rewritten = research_mature_builds._rewrite_lease_token_argv(
        ["read", "--output-dir", "r", "--lease-token", "-dash-led", "--section", "skills"]
    )
    assert rewritten == [
        "read",
        "--output-dir",
        "r",
        "--lease-token=-dash-led",
        "--section",
        "skills",
    ]
    # Equals-form and non-lease options must pass through untouched.
    assert research_mature_builds._rewrite_lease_token_argv(
        ["read", "--lease-token=-abc", "--section", "skills"]
    ) == ["read", "--lease-token=-abc", "--section", "skills"]
    untouched = research_mature_builds._rewrite_lease_token_argv(
        ["read", "--output-dir", "-weird-dir", "--section", "skills"]
    )
    assert untouched == ["read", "--output-dir", "-weird-dir", "--section", "skills"]
    assert research_mature_builds._rewrite_lease_token_argv(None) is None


def test_read_cli_parses_dash_leading_lease_token_without_argparse_error(
    tmp_path, capsys, monkeypatch
):
    from scripts import research_mature_builds

    # A dash-leading token must reach lease validation (and fail there as a safe JSON error),
    # never be rejected by argparse as "expected one argument". Exercise ``main()`` with
    # no explicit argv so this pins the production CLI path through ``sys.argv``.
    monkeypatch.setattr(
        research_mature_builds.sys,
        "argv",
        [
            "research_mature_builds.py",
            "read",
            "--output-dir",
            str(tmp_path / "research"),
            "--lease-token",
            "-dash-led-token",
            "--section",
            "skills",
        ],
    )
    code = research_mature_builds.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 1
    assert payload["status"] == "runtime_failed"
    assert "expected one argument" not in captured.out
    assert "expected one argument" not in captured.err
    _assert_safe_payload(payload, tmp_path.parent)


def test_validate_only_keeps_current_lease_and_skips_durable_acceptance(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-validate-only",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    calls: list[dict] = []

    def fake_validate(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "deferredReasonCounts": {},
            "patternWrite": {"status": "accepted", "validationOnly": True},
            "deepRecordWrite": {"status": "accepted", "validationOnly": True},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_validate,
    )
    result = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
        validation_only=True,
    )

    assert result["status"] == "validation_passed"
    assert result["readyForAccept"] is True
    assert result["fullyResolvedForAccept"] is True
    assert result["acceptanceMode"] == "clean"
    assert result["durableWritePerformed"] is False
    assert result["queueStateChanged"] is False
    assert calls[0]["validation_only"] is True
    status = research_mature_builds.queue_status(output_dir=output_dir)
    assert status["claimedCount"] == 1
    assert status["acceptedCount"] == 0


def test_validate_only_structural_errors_return_validation_failed_not_runtime_failed(
    tmp_path, monkeypatch
):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-structural-validate",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    payload = {
        "reviewContractVersion": "phase4-safe-review-v2",
        "safeArtifactOnly": True,
        "candidateReviews": [
            {
                "sampleId": claimed["sampleId"],
                "caseRef": claimed["sourceHashRef"],
                "safeEvidenceRef": f"evidence:{claimed['packetSafeHash'][:16]}",
                "patternType": "cooccurrence",
                "title": "结构测试候选",
                "summary": "verificationTasks 为空时应返回可修复 issues",
                "axes": ["mechanic_engine"],
                "components": [],
                "plannerHint": "仅测试结构预检",
                "verificationGate": "测试 gate",
                "verificationTasks": [],
                "transferScope": "family",
                "claimScopeReview": {
                    "evidenceScope": "current_case",
                    "claimScope": "case_only",
                    "verdict": "supported",
                    "reason": "The Agent confirmed this is a current-case claim.",
                    "safeEvidenceRefs": [f"evidence:{claimed['packetSafeHash'][:16]}"],
                },
            }
        ],
        "deepResearchRecords": [],
    }
    review_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance._graph_service",
        lambda: None,
    )
    result = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
        validation_only=True,
    )

    assert result["status"] == "validation_failed"
    issues = list(result.get("validationIssues") or [])
    assert any(
        issue.get("loc") == ["candidateReviews", 0, "verificationTasks"]
        and "non-empty list" in str(issue.get("msg") or "")
        for issue in issues
    )


def test_validation_only_distinguishes_partial_acceptance_from_clean_acceptance():
    from scripts import research_mature_builds

    result = research_mature_builds._validation_only_result(
        {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 3,
            "unresolvedDeepRecordComponentCount": 2,
            "unresolvedDeepRecordMentionCount": 2,
            "unresolvedUniqueComponentCount": 1,
            "unkeyedDeepRecordCount": 1,
            "deepRecordsWithoutKnowledgeIdentity": [
                {"titleZh": "无身份资源记录", "recordKind": "resource_engine"}
            ],
            "deepRecordsWithUnresolvedComponents": [
                {
                    "titleZh": "待修复记录",
                    "recordKind": "mechanic_chain",
                    "unresolvedComponentCount": 2,
                }
            ],
            "deferredCandidateCount": 1,
            "deferredReasonCounts": {"component_type_mismatch": 1},
            "deferredCandidates": [{"reason": "component_type_mismatch"}],
            "patternWrite": {"status": "accepted", "validationOnly": True},
            "deepRecordWrite": {"status": "accepted", "validationOnly": True},
        },
        sample_id="case:partial",
    )

    assert result["status"] == "validation_passed"
    assert result["readyForAccept"] is True
    assert result["fullyResolvedForAccept"] is False
    assert result["acceptanceMode"] == "partial_with_deferred"
    assert result["unresolvedDeepRecordMentionCount"] == 2
    assert result["unresolvedUniqueComponentCount"] == 1
    assert result["unkeyedDeepRecordCount"] == 1
    assert result["deepRecordsWithoutKnowledgeIdentity"][0]["recordKind"] == "resource_engine"
    assert result["deepRecordsWithUnresolvedComponents"][0]["titleZh"] == "待修复记录"


def test_validation_only_redacts_copyable_diagnostics_and_returns_safe_paths():
    from scripts import research_mature_builds

    support_caveat = "Supports: A, B, C, D, E"
    long_caveat = "机制说明" * 500
    raw_account_url = "https://pathofexile.com/account/view-profile/private-character"
    unsafe_dynamic_key = "rawImportCode:eNrt-sensitive-key"
    result = research_mature_builds._validation_only_result(
        {
            "status": "accepted",
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "deferredReasonCounts": {},
            "caveats": [support_caveat, long_caveat],
            "mechanicAudit": {"entries": [{"claim": long_caveat}]},
            "patternWrite": {"status": "accepted", "validationOnly": True},
            "deepRecordWrite": {
                "status": "accepted",
                "validationOnly": True,
                "facts": {
                    "validationIssues": [
                        {
                            "submittedValue": raw_account_url,
                            "message": support_caveat,
                        }
                    ],
                    unsafe_dynamic_key: "safe value",
                },
            },
        },
        sample_id="case:copy-safety-diagnostic",
    )

    assert result["status"] == "validation_failed"
    assert result["readyForAccept"] is False
    assert result["deferredReasonCounts"] == {}
    assert result["copySafetyBlockingIssueCount"] == 3
    diagnostics = result["copySafetyDiagnostics"]
    by_loc = {tuple(item["loc"]): item for item in diagnostics}
    assert by_loc[("caveats", 0)]["blockingFlags"] == []
    assert by_loc[("caveats", 1)]["blockingFlags"] == ["long_guide_prose_like"]
    assert by_loc[("mechanicAudit", "entries", 0, "claim")]["blockingFlags"] == [
        "long_guide_prose_like"
    ]
    assert by_loc[("deepRecordWrite", "facts", "validationIssues", 0, "submittedValue")][
        "blockingFlags"
    ] == ["raw_account_or_character_url"]
    assert any(
        issue["loc"] == ["caveats", 1] and issue["type"] == "copy_safety"
        for issue in result["validationIssues"]
    )
    assert support_caveat not in str(result)
    assert long_caveat not in str(result)
    assert raw_account_url not in str(result)
    assert unsafe_dynamic_key not in str(result)
    research_mature_builds._assert_safe_payload(result)


def test_accept_case_validation_returns_copy_safety_failure_instead_of_runtime_error(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-copy-safety-validation",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True, exist_ok=True)
    _write_claim_review(review_file, claimed)
    unsafe_claim = "机制说明" * 500
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["mechanicAudit"] = [{"claim": unsafe_claim}]
    review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    result = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
        validation_only=True,
    )

    assert result["status"] == "validation_failed"
    assert result["copySafetyBlockingIssueCount"] == 1
    assert result["copySafetyDiagnostics"][0]["loc"] == [
        "mechanicAudit",
        0,
        "claim",
    ]
    assert [issue["type"] for issue in result["validationIssues"]].count("copy_safety") == 1
    assert result["durableWritePreflight"]["checkedWithoutMutation"] is True
    assert not (tmp_path / "memory.sqlite").exists()
    assert unsafe_claim not in str(result)


def test_validation_only_counts_forbidden_field_failures_as_blocking():
    from scripts import research_mature_builds

    report = research_mature_builds.acceptance._copy_safety_validation_failure_report(
        {"nested": {"accountName": "private-account"}}
    )
    result = research_mature_builds._validation_only_result(
        report,
        sample_id="case:forbidden-field",
    )

    assert result["status"] == "validation_failed"
    assert result["copySafetyBlockingIssueCount"] == 1
    assert result["copySafetyDiagnostics"] == [
        {
            "loc": ["nested", "accountName"],
            "flags": ["forbidden_copyable_field"],
            "blockingFlags": ["forbidden_copyable_field"],
        }
    ]
    assert "private-account" not in str(result)


def test_copy_safety_validation_failure_maps_derived_path_to_safe_origin():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    report = acceptance._copy_safety_validation_failure_report(
        {"deferredCandidates": [{"caveats": ["机制说明" * 500]}]},
        origin_sidecar={
            ("deferredCandidates", "0"): {
                "originLoc": ["deepResearchRecords", 3, "content"],
                "originKind": "deep_research_record",
                "safeTitle": "资源闭环",
            }
        },
    )

    issue = report["deferredCandidates"][0]["validationIssues"][0]
    assert issue["originLoc"] == ["deepResearchRecords", 3, "content"]
    assert issue["originKind"] == "deep_research_record"
    assert issue["safeTitle"] == "资源闭环"
    assert issue["flags"] == ["long_guide_prose_like"]
    assert "机制说明" not in str(report)


def test_copy_safety_origin_sidecar_does_not_guess_between_duplicate_titles():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    sidecar = acceptance._diagnostic_origin_sidecar(
        {
            "deepResearchRecords": [
                {"title": "同名记录", "recordKind": "resource_engine"},
                {"title": "同名记录", "recordKind": "mechanic_chain"},
            ]
        },
        {
            "deferredCandidates": [
                {
                    "titleZh": "同名记录",
                    "candidateKind": "deep_research_record",
                    "caveats": ["机制说明" * 500],
                }
            ]
        },
    )

    assert sidecar == {}


def test_validation_transport_report_id_exemption_rejects_raw_markers_and_pob_codes():
    from scripts import research_mature_builds

    normal_id = "phase4-deep-review-acceptance-v3"
    safe, diagnostics = research_mature_builds._safe_validation_transport_report(
        {"reportId": normal_id}
    )
    assert safe["reportId"] == normal_id
    assert diagnostics == []

    raw_marker = "rawimportcode:eNrt-sensitive"
    pob_blob = _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
    unsafe, diagnostics = research_mature_builds._safe_validation_transport_report(
        {"reportId": raw_marker, "nested": {"reportId": pob_blob}}
    )
    assert raw_marker not in str(unsafe)
    assert pob_blob not in str(unsafe)
    assert {tuple(item["loc"]) for item in diagnostics} == {
        ("reportId",),
        ("nested", "reportId"),
    }
    assert any("raw_pob_xml_marker" in item["flags"] for item in diagnostics)
    assert any("pob_code_like_blob" in item["flags"] for item in diagnostics)


def test_durable_write_preflight_reports_permission_without_mutating(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    memory_root = tmp_path / "memory-root"
    ledger_root = tmp_path / "ledger-root"
    memory_root.mkdir()
    ledger_root.mkdir()
    memory_db = memory_root / "memory.sqlite"
    ledger = ledger_root / "ledger.sqlite"
    lock = research_mature_builds._accept_lock_path(memory_db)
    memory_db.write_bytes(b"memory")
    lock.write_bytes(b"lock")
    ledger.write_bytes(b"ledger")
    denied = {memory_db.resolve(), lock.resolve()}
    real_open = Path.open

    def guarded_open(path: Path, *args, **kwargs):
        if path.resolve() in denied:
            raise PermissionError("simulated sandbox write denial")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    result = research_mature_builds._durable_write_preflight(
        memory_db_path=memory_db,
        intake_ledger_path=ledger,
        requires_intake_ledger=True,
    )

    assert result == {
        "status": "permission_required",
        "memoryDbWritable": False,
        "acceptLockWritable": False,
        "intakeLedgerRequired": True,
        "intakeLedgerWritable": True,
        "unknownTargets": [],
        "requiresWriteApproval": True,
        "advisoryOnly": True,
        "scope": "existing_file_handles_only",
        "sqliteSidecarCreationUnverified": True,
        "checkedWithoutMutation": True,
    }
    with real_open(memory_db, "rb") as handle:
        assert handle.read() == b"memory"
    with real_open(lock, "rb") as handle:
        assert handle.read() == b"lock"
    with real_open(ledger, "rb") as handle:
        assert handle.read() == b"ledger"


def test_durable_write_preflight_reports_ready_and_unknown_without_mutating(tmp_path):
    from scripts import research_mature_builds

    memory_db = tmp_path / "memory.sqlite"
    lock = research_mature_builds._accept_lock_path(memory_db)
    ledger = tmp_path / "ledger.sqlite"
    for path, payload in (
        (memory_db, b"memory"),
        (lock, b"lock"),
        (ledger, b"ledger"),
    ):
        path.write_bytes(payload)
    before = {
        path: (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in (memory_db, lock, ledger)
    }

    ready = research_mature_builds._durable_write_preflight(
        memory_db_path=memory_db,
        intake_ledger_path=ledger,
        requires_intake_ledger=True,
    )
    unknown = research_mature_builds._durable_write_preflight(
        memory_db_path=tmp_path / "missing-memory.sqlite",
        intake_ledger_path=tmp_path / "missing-ledger.sqlite",
        requires_intake_ledger=True,
    )

    assert ready["status"] == "write_handle_ready"
    assert ready["requiresWriteApproval"] is False
    assert ready["sqliteSidecarCreationUnverified"] is True
    assert ready["unknownTargets"] == []
    assert unknown["status"] == "permission_required"
    assert unknown["requiresWriteApproval"] is True
    assert unknown["unknownTargets"] == ["memoryDb", "acceptLock", "intakeLedger"]
    assert {
        path: (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in (memory_db, lock, ledger)
    } == before


def test_durable_write_preflight_treats_generic_oserror_as_unknown(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    memory_db = tmp_path / "memory.sqlite"
    lock = research_mature_builds._accept_lock_path(memory_db)
    ledger = tmp_path / "ledger.sqlite"
    for path in (memory_db, lock, ledger):
        path.write_bytes(b"safe")
    real_open = Path.open

    def guarded_open(path: Path, *args, **kwargs):
        if path.resolve() == ledger.resolve():
            raise OSError("simulated transient handle failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    result = research_mature_builds._durable_write_preflight(
        memory_db_path=memory_db,
        intake_ledger_path=ledger,
        requires_intake_ledger=True,
    )

    assert result["status"] == "permission_required"
    assert result["memoryDbWritable"] is True
    assert result["acceptLockWritable"] is True
    assert result["intakeLedgerWritable"] is None
    assert result["unknownTargets"] == ["intakeLedger"]


def test_validation_readiness_is_independent_from_durable_write_permission(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-write-preflight-independent",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True, exist_ok=True)
    _write_claim_review(review_file, claimed)
    permission_required = {
        "status": "permission_required",
        "memoryDbWritable": False,
        "acceptLockWritable": False,
        "intakeLedgerRequired": False,
        "intakeLedgerWritable": True,
        "unknownTargets": [],
        "requiresWriteApproval": True,
        "advisoryOnly": True,
        "scope": "existing_file_handles_only",
        "sqliteSidecarCreationUnverified": True,
        "checkedWithoutMutation": True,
    }
    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        lambda **_kwargs: {
            "status": "accepted",
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "deferredReasonCounts": {},
            "patternWrite": {"status": "accepted", "validationOnly": True},
            "deepRecordWrite": {"status": "accepted", "validationOnly": True},
        },
    )
    monkeypatch.setattr(
        research_mature_builds,
        "_durable_write_preflight",
        lambda **_kwargs: permission_required,
    )

    result = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
        validation_only=True,
    )

    assert result["status"] == "validation_passed"
    assert result["readyForAccept"] is True
    assert result["fullyResolvedForAccept"] is True
    assert result["durableWritePreflight"] == permission_required


def test_validation_only_treats_case_coverage_gap_as_partial_acceptance():
    from scripts import research_mature_builds

    result = research_mature_builds._validation_only_result(
        {
            "status": "accepted",
            "acceptedDeepRecordCount": 3,
            "deferredCandidateCount": 0,
            "caseCoverageGapCount": 1,
            "caseCoverageGaps": ["gearRoles"],
            "patternWrite": {"status": "accepted", "validationOnly": True},
            "deepRecordWrite": {"status": "accepted", "validationOnly": True},
        },
        sample_id="case:coverage-gap",
    )

    assert result["status"] == "validation_passed"
    assert result["readyForAccept"] is True
    assert result["fullyResolvedForAccept"] is False
    assert result["acceptanceMode"] == "partial_with_deferred"
    assert result["caseCoverageGaps"] == ["gearRoles"]


def test_bounded_case_reader_pages_all_sections_and_finds_non_main_skill(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "rich-sample.txt"
    source_file.write_text(pob_code.encode_code(_rich_sample_xml()), encoding="utf-8")
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-rich-reader"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=temp_root,
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    inspected = research_mature_builds.inspect_case(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
    )

    assert inspected["sections"]["skills"]["itemCount"] == 3
    assert inspected["sections"]["gear"]["itemCount"] == 2
    assert inspected["sections"]["passives"]["itemCount"] > 50
    _assert_safe_payload(inspected, tmp_path.parent)

    all_passives: list[dict] = []
    cursor = 0
    while True:
        page = research_mature_builds.read_case_section(
            output_dir=output_dir,
            temp_root=temp_root,
            lease_token=claimed["leaseToken"],
            section="passives",
            cursor=cursor,
            limit=7,
        )
        assert len(json.dumps(page, ensure_ascii=False, indent=2)) <= 12_000
        all_passives.extend(page["items"])
        if page["complete"]:
            break
        cursor = page["nextCursor"]

    allocated = [item["nodeId"] for item in all_passives if item["kind"] == "allocated_node"]
    assert allocated == [str(value) for value in range(100, 160)]
    assert len(allocated) == len(set(allocated))

    skills = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="skills",
        limit=50,
    )
    names = [gem["name"] for group in skills["items"] for gem in group["gems"]]
    assert "Plasma Blast" in names
    assert "Bonestorm" in names
    assert "Blasphemy" in names
    assert "Controlled Destruction" in names

    search = research_mature_builds.search_case(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        query="Bonestorm",
        section="skills",
    )
    assert search["totalMatchCount"] == 1
    assert search["matches"][0]["item"]["gems"][0]["name"] == "Bonestorm"
    _assert_safe_payload(search, tmp_path.parent)


def test_passive_reader_enriches_known_nodes_from_pinned_tree(tmp_path):
    from scripts import research_mature_builds

    xml = _sample_xml("SparkPlayer", ascendancy="Stormweaver", level=90).replace(
        "</PathOfBuilding2>",
        '<Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="57513,45918" /></Tree></PathOfBuilding2>',
    )
    source_file = tmp_path / "passive-sample.txt"
    source_file.write_text(pob_code.encode_code(xml), encoding="utf-8")
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-passive-enrichment"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="passives",
        limit=50,
    )

    nodes = {item.get("nodeId"): item for item in page["items"] if item["kind"] == "allocated_node"}
    assert nodes["57513"]["name"] == "Eldritch Battery"
    assert nodes["57513"]["nodeTypes"] == ["keystone"]
    assert nodes["45918"]["name"] == "Mind Over Matter"


def test_passive_reader_exposes_ascendancy_ownership(tmp_path):
    from scripts import research_mature_builds

    xml = _sample_xml("SparkPlayer", ascendancy="Oracle", level=90).replace(
        "</PathOfBuilding2>",
        '<Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="55135" /></Tree></PathOfBuilding2>',
    )
    source_file = tmp_path / "oracle-passive-sample.txt"
    source_file.write_text(pob_code.encode_code(xml), encoding="utf-8")
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-oracle-passive"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="passives",
        limit=50,
    )

    node = next(item for item in page["items"] if item.get("nodeId") == "55135")
    assert node["name"] == "Forced Outcome"
    assert node["ascendancyName"] == "Oracle"
    assert node["isAscendancyPassive"] is True


def test_passive_reader_filters_by_node_type(tmp_path):
    from scripts import research_mature_builds

    xml = _sample_xml("SparkPlayer", ascendancy="Stormweaver", level=90).replace(
        "</PathOfBuilding2>",
        '<Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="57513,45918,100" /></Tree></PathOfBuilding2>',
    )
    source_file = tmp_path / "passive-filter-sample.txt"
    source_file.write_text(pob_code.encode_code(xml), encoding="utf-8")
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-passive-filter"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    keystone_page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="passives",
        node_type="keystone",
        limit=50,
    )
    keystone_nodes = [item for item in keystone_page["items"] if item["kind"] == "allocated_node"]
    assert [item["nodeId"] for item in keystone_nodes] == ["57513", "45918"]
    assert keystone_page["totalCount"] == 2
    assert keystone_page["complete"] is True

    normal_page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="passives",
        node_type="normal",
        limit=50,
    )
    normal_nodes = [item for item in normal_page["items"] if item["kind"] == "allocated_node"]
    assert [item["nodeId"] for item in normal_nodes] == ["100"]

    unfiltered = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="passives",
        limit=50,
    )
    unfiltered_allocated = [
        item for item in unfiltered["items"] if item["kind"] == "allocated_node"
    ]
    assert sorted(item["nodeId"] for item in unfiltered_allocated) == ["100", "45918", "57513"]


def test_case_reader_reports_cross_axis_rare_cooccurrence_advisory(tmp_path):
    from scripts import research_mature_builds

    xml = _sample_xml("SparkPlayer", ascendancy="Stormweaver", level=90).replace(
        "</PathOfBuilding2>",
        (
            '<Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="57513" /></Tree>'
            '<Items activeItemSet="1">'
            '<Item id="7">Rarity: RARE\nThorns of Chaos\nHelmet\nItem Level: 82\n'
            "+30 to maximum Life\n50% increased Chaos Damage\n40 to 60 Physical Thorns damage</Item>"
            '<ItemSet id="1"><Slot name="Helmet" itemId="7" /></ItemSet></Items>'
            "</PathOfBuilding2>"
        ),
    )
    source_file = tmp_path / "advisory-sample.txt"
    source_file.write_text(pob_code.encode_code(xml), encoding="utf-8")
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-advisory"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="gear",
        limit=50,
    )
    assert page["advisories"]
    assert "chaos" in page["advisories"][0]
    assert "thorns" in page["advisories"][0]


def test_case_reader_omits_advisory_without_rare_axis_cooccurrence(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "clean-sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-clean-advisory"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="skills",
        limit=50,
    )
    assert page["advisories"] == []


def test_case_reader_rejects_wrong_or_expired_lease(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-reader-lease"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1)

    with pytest.raises(ValueError, match="lease"):
        research_mature_builds.inspect_case(
            output_dir=output_dir,
            temp_root=temp_root,
            lease_token="wrong-token",
        )

    with sqlite3.connect(output_dir / "poe_bd_research_queue.sqlite") as con:
        con.execute(
            "UPDATE cases SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE sample_id = ?",
            (claimed["sampleId"],),
        )
        con.commit()
    with pytest.raises(ValueError, match="lease"):
        research_mature_builds.read_case_section(
            output_dir=output_dir,
            temp_root=temp_root,
            lease_token=claimed["leaseToken"],
            section="skills",
        )


def test_accept_resolves_review_file_relative_to_output_dir(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-relative-review",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "recordKindCounts": {"rotation": 1},
            "caseCoverage": {
                "supports": "covered",
                "rotation": "covered",
                "passiveAscendancy": "evidence_missing",
                "gearRoles": "evidence_missing",
                "resourceDefense": "evidence_missing",
            },
            "caseCoverageGapCount": 3,
            "caseCoverageGaps": [
                "passiveAscendancy",
                "gearRoles",
                "resourceDefense",
            ],
            "singleComponentObservationCount": 1,
            "createdBuildFamilyCount": 1,
            "addedBuildFamilyEvidenceCount": 1,
            "recordKindAdvisories": ["fixture advisory"],
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert calls[0]["review_file"] == review_file
    assert accepted["recordKindCounts"] == {"rotation": 1}
    assert accepted["caseCoverageGapCount"] == 3
    assert accepted["singleComponentObservationCount"] == 1
    assert accepted["createdBuildFamilyCount"] == 1
    assert accepted["addedBuildFamilyEvidenceCount"] == 1
    status_sample = research_mature_builds.queue_status(output_dir=output_dir)["samples"][0]
    assert status_sample["createdBuildFamilyCount"] == 1
    assert status_sample["addedBuildFamilyEvidenceCount"] == 1
    assert status_sample["caseCoverage"]["rotation"] == "covered"
    assert status_sample["caseCoverageGaps"] == [
        "passiveAscendancy",
        "gearRoles",
        "resourceDefense",
    ]
    assert status_sample["recordKindAdvisories"] == ["fixture advisory"]


def test_accept_resolves_lease_review_basename_from_reviews_directory(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-review-basename",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
            "deepRecordWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=review_file.name,
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert calls[0]["review_file"] == review_file


def test_accept_allows_full_current_lease_token_in_review_filename(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-full-lease-review",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    sample_slug = research_mature_builds._slug(claimed["sampleId"])
    review_file = output_dir / "reviews" / f"{sample_slug}-{claimed['leaseToken']}-safe-review.json"
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
            "deepRecordWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=review_file.name,
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert calls[0]["review_file"] == review_file


def test_accept_rejects_matching_lease_filename_with_wrong_case_identity(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-wrong-review-identity",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed, case_ref="source-hash:wrong")
    calls: list[dict] = []
    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        lambda **kwargs: calls.append(kwargs),
    )

    with pytest.raises(ValueError, match="identity"):
        research_mature_builds.accept_case(
            output_dir=output_dir,
            lease_token=claimed["leaseToken"],
            review_file=review_file.name,
            memory_db_path=tmp_path / "memory.sqlite",
        )

    assert calls == []


def test_accept_canonicalizes_repeated_record_identity_from_lease(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-canonical-review-identity",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    payload = json.loads(review_file.read_text(encoding="utf-8"))
    payload["deepResearchRecords"][0]["sampleId"] = claimed["sampleId"] + "-typo"
    payload["deepResearchRecords"][0]["researchGroupId"] = "research:copied-by-agent"
    review_file.write_text(json.dumps(payload), encoding="utf-8")
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
            "deepRecordWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    canonical = calls[0]["review_payload"]["deepResearchRecords"][0]
    assert canonical["sampleId"] == claimed["sampleId"]
    assert canonical["researchGroupId"] == f"research:{claimed['sampleId']}"
    assert canonical["caseRef"] == claimed["sourceHashRef"]
    assert canonical["safeEvidenceRef"] == f"evidence:{claimed['packetSafeHash'][:16]}"


def test_queue_cli_stops_when_local_attachment_count_does_not_match(tmp_path, capsys):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"

    code = research_mature_builds.main(
        [
            "queue",
            "--output-dir",
            str(output_dir),
            "--source-file",
            str(source_file),
            "--expected-source-count",
            "5",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["status"] == "source_input_count_mismatch"
    assert payload["expectedSourceCount"] == 5
    assert payload["localSourceInputCount"] == 1
    assert payload["queueCreated"] is False
    assert not (output_dir / "poe_bd_research_queue.sqlite").exists()


def test_accept_identity_allows_plural_safe_evidence_refs(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-plural-evidence",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    payload = {
        "reviewContractVersion": "phase4-safe-review-v2",
        "safeArtifactOnly": True,
        "deepResearchRecords": [
            {
                "sampleId": claimed["sampleId"],
                "caseRef": claimed["sourceHashRef"],
                "safeEvidenceRefs": [f"evidence:{claimed['packetSafeHash'][:16]}"],
            }
        ],
        "candidateReviews": [],
    }
    review_file.write_text(json.dumps(payload), encoding="utf-8")
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
            "deepRecordWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert calls[0]["review_file"] == review_file


def test_v1_contract_upgrade_keeps_claimed_lease_and_reuses_ordinary_accept(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-contract-upgrade",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    legacy = json.loads(review_file.read_text(encoding="utf-8"))
    legacy.pop("reviewContractVersion")
    review_file.write_text(json.dumps(legacy), encoding="utf-8")

    upgrade = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert upgrade["status"] == "validation_failed"
    assert upgrade["errorCode"] == "review_contract_upgrade_required"
    assert upgrade["queueStateChanged"] is False
    assert "ordinary accept" in upgrade["nextAction"]
    assert research_mature_builds.queue_status(output_dir=output_dir)["claimedCount"] == 1

    legacy["reviewContractVersion"] = "phase4-safe-review-v2"
    review_file.write_text(json.dumps(legacy), encoding="utf-8")
    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        lambda **_kwargs: {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 1,
            "acceptedSemanticEdgeCount": 0,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
            "deepRecordWrite": {"status": "accepted"},
            "semanticEdgeWrite": {"status": "accepted"},
        },
    )

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert research_mature_builds.queue_status(output_dir=output_dir)["acceptedCount"] == 1


def test_retry_accept_rejected_case_without_lease(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-retry-accept",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    calls: list[dict] = []

    def fake_reject_then_accept(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "status": "rejected",
                "acceptedPatternCount": 0,
                "deferredCandidateCount": 0,
                "patternWrite": {"status": "error"},
            }
        return {
            "status": "accepted",
            "acceptedPatternCount": 2,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_reject_then_accept,
    )

    rejected = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory.sqlite",
    )
    assert rejected["status"] == "acceptance_rejected"
    assert research_mature_builds.queue_status(output_dir=output_dir)["rejectedCount"] == 1

    retried = research_mature_builds.retry_accept_case(
        output_dir=output_dir,
        sample_id=claimed["sampleId"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert retried["status"] == "accepted"
    assert retried["acceptedPatternCount"] == 2
    assert len(calls) == 2
    status = research_mature_builds.queue_status(output_dir=output_dir)
    assert status["acceptedCount"] == 1
    assert status["rejectedCount"] == 0


def test_retry_accept_exception_restores_rejected_state(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("RetryFailurePlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research-retry-failure"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-retry-failure",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    monkeypatch.setattr(
        research_mature_builds.acceptance,
        "accept_deep_review_candidates",
        lambda **_: {
            "status": "rejected",
            "acceptedPatternCount": 0,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "error"},
        },
    )
    research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory-retry-failure.sqlite",
    )

    def fail_acceptance(**kwargs):
        raise RuntimeError("simulated durable failure")

    monkeypatch.setattr(
        research_mature_builds.acceptance,
        "accept_deep_review_candidates",
        fail_acceptance,
    )
    with pytest.raises(RuntimeError, match="simulated durable failure"):
        research_mature_builds.retry_accept_case(
            output_dir=output_dir,
            sample_id=claimed["sampleId"],
            review_file=review_file,
            memory_db_path=tmp_path / "memory-retry-failure.sqlite",
        )

    status = research_mature_builds.queue_status(output_dir=output_dir)
    assert status["rejectedCount"] == 1
    assert status["acceptingCount"] == 0


def test_expired_lease_can_reclaim_and_old_lease_cannot_accept(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-reclaim",
    )
    first = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    _expire_case_lease(output_dir / "poe_bd_research_queue.sqlite", first["sampleId"])
    expired_status = research_mature_builds.queue_status(output_dir=output_dir)
    assert expired_status["queuedCount"] == 0
    assert expired_status["claimedCount"] == 1
    assert expired_status["expiredClaimedCount"] == 1
    assert expired_status["dispatchableCount"] == 1
    second = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    assert second["sampleId"] == first["sampleId"]
    assert second["leaseToken"] != first["leaseToken"]
    assert second["reviewFile"] != first["reviewFile"]

    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    review_file = output_dir / second["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, second)

    with pytest.raises(ValueError, match="lease"):
        research_mature_builds.accept_case(
            output_dir=output_dir,
            lease_token=first["leaseToken"],
            review_file=review_file,
            memory_db_path=tmp_path / "memory.sqlite",
        )
    assert calls == []

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=second["leaseToken"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert accepted["sampleId"] == second["sampleId"]
    assert accepted["acceptedPatternCount"] == 1
    assert len(calls) == 1
    assert research_mature_builds.queue_status(output_dir=output_dir)["acceptedCount"] == 1


def test_accept_holds_exact_lease_before_running_durable_acceptance(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-accept-lock",
        worker_count=1,
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    reclaim_attempts: list[dict] = []
    stale_accepting_counts: list[int] = []

    def fake_accept_deep_review_candidates(**kwargs):
        _expire_case_lease(output_dir / "poe_bd_research_queue.sqlite", claimed["sampleId"])
        stale_accepting_counts.append(
            research_mature_builds.queue_status(output_dir=output_dir)["staleAcceptingCount"]
        )
        reclaim_attempts.append(
            research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
        )
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert stale_accepting_counts == [1]
    assert reclaim_attempts == [
        {
            "status": "worker_capacity_reached",
            "queueKind": "poe_bd_research_external_agent_queue",
            "activeCaseCount": 1,
            "workerCount": 1,
            "noRawMatureBuildMaterial": True,
        }
    ]
    assert research_mature_builds.queue_status(output_dir=output_dir)["acceptedCount"] == 1


def test_claim_packet_failure_releases_lease_and_returns_sample_id(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("PacketFailurePlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research-packet-failure"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-packet-failure",
    )

    def fail_packet_rebuild(**kwargs):
        raise OSError("simulated packet failure")

    monkeypatch.setattr(
        research_mature_builds,
        "_rebuild_packet_for_claim",
        fail_packet_rebuild,
    )
    result = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    status = research_mature_builds.queue_status(output_dir=output_dir)

    assert result["status"] == "claim_packet_failed"
    assert result["sampleId"].startswith("case:poe-bd-research-")
    assert result["leaseReleased"] is True
    assert result["retryable"] is True
    assert result["recoveryRequired"] is False
    assert status["queuedCount"] == 1
    assert status["claimedCount"] == 0
    assert status["dispatchableCount"] == 1


def test_formal_accepts_for_one_memory_store_are_serialized(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    batch_file = tmp_path / "accept-samples.txt"
    batch_file.write_text(
        _sample_code("AcceptPlayerA", ascendancy="Deadeye", level=95)
        + "\n---POB-SAMPLE---\n"
        + _sample_code("AcceptPlayerB", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research-concurrent-accept"
    research_mature_builds.queue_cases(
        source_batch_files=[batch_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-concurrent-accept",
        worker_count=2,
    )
    claims = [
        research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
        for _ in range(2)
    ]
    for claim in claims:
        review_file = output_dir / claim["reviewFile"]
        review_file.parent.mkdir(parents=True, exist_ok=True)
        _write_claim_review(review_file, claim)

    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_accept_deep_review_candidates(**kwargs):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.1)
            return {
                "status": "accepted",
                "acceptedPatternCount": 1,
                "deferredCandidateCount": 0,
                "patternWrite": {"status": "accepted"},
            }
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(
        research_mature_builds.acceptance,
        "accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    memory_db = tmp_path / "shared-memory.sqlite"

    def accept_one(claim):
        return research_mature_builds.accept_case(
            output_dir=output_dir,
            lease_token=claim["leaseToken"],
            review_file=output_dir / claim["reviewFile"],
            memory_db_path=memory_db,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(accept_one, claims))

    status = research_mature_builds.queue_status(output_dir=output_dir)
    assert max_active == 1
    assert [item["status"] for item in results] == ["accepted", "accepted"]
    assert status["acceptedCount"] == 2
    assert status["claimedCount"] == 0
    assert status["acceptingCount"] == 0
    assert research_mature_builds._accept_lock_path(memory_db) == (
        research_mature_builds._accept_lock_path(memory_db.resolve())
    )


def test_research_accept_file_lock_serializes_spawned_processes(tmp_path):
    from scripts import research_mature_builds

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    active = context.Value("i", 0)
    max_active = context.Value("i", 0)
    counter_lock = context.Lock()
    lock_path = str(research_mature_builds._accept_lock_path(tmp_path / "shared.sqlite"))
    processes = [
        context.Process(
            target=_hold_research_accept_file_lock,
            args=(lock_path, start_event, active, max_active, counter_lock),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start_event.set()
    for process in processes:
        process.join(timeout=15)
        assert not process.is_alive()
        assert process.exitcode == 0

    assert max_active.value == 1
    assert active.value == 0


def test_legacy_phase45_wrappers_warn_on_stderr_without_polluting_json_stdout(
    tmp_path, capsys, monkeypatch
):
    from scripts import phase45_accept_single_review, run_phase45_researcher_batch

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    code = run_phase45_researcher_batch.main(
        [
            "--source-file",
            str(source_file),
            "--output-dir",
            str(tmp_path / "legacy-queue"),
            "--temp-root",
            str(tmp_path.parent / "legacy-temp"),
            "--dry-run",
            "--json-output",
            str(tmp_path / "legacy.json"),
            "--md-output",
            str(tmp_path / "legacy.md"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "deprecated" in captured.err.lower()
    assert json.loads(captured.out)["status"] == "dry_run"

    review_file = tmp_path / "safe-review.json"
    review_file.write_text('{"safeArtifactOnly": true}', encoding="utf-8")

    def fake_accept_deep_review_candidates(**kwargs):
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {},
        }

    monkeypatch.setattr(
        "scripts.phase45_accept_single_review.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    code = phase45_accept_single_review.main(
        [
            "--review-file",
            str(review_file),
            "--case-id",
            "case:legacy-001",
            "--output-dir",
            str(tmp_path / "legacy-accept"),
            "--db-path",
            str(tmp_path / "memory.sqlite"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "deprecated" in captured.err.lower()
    assert json.loads(captured.out)["status"] == "accepted"


def test_queue_cli_reports_collector_failure_as_safe_json(tmp_path, capsys, monkeypatch):
    from scripts import research_mature_builds

    def fail_collect(**kwargs):
        raise RuntimeError("HTTP Error 403: Forbidden while fetching poe.ninja")

    monkeypatch.setattr(research_mature_builds.legacy_batch, "_cases_from_ninja", fail_collect)

    code = research_mature_builds.main(
        [
            "queue",
            "--output-dir",
            str(tmp_path / "research"),
            "--limit",
            "1",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 1
    assert payload["status"] == "collector_failed"
    assert payload["command"] == "queue"
    assert payload["noRawMatureBuildMaterial"] is True
    assert "HTTP Error 403" in payload["safeError"]
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err
    _assert_safe_payload(payload, tmp_path.parent)


def _expire_case_lease(db_path: Path, sample_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE cases
               SET lease_expires_at = '2000-01-01T00:00:00+00:00'
             WHERE sample_id = ?
            """,
            (sample_id,),
        )
        conn.commit()


def _write_claim_review(path: Path, claimed: dict, *, case_ref: str | None = None) -> None:
    payload = {
        "reviewContractVersion": "phase4-safe-review-v2",
        "safeArtifactOnly": True,
        "deepResearchRecords": [
            {
                "sampleId": claimed["sampleId"],
                "caseRef": case_ref or claimed["sourceHashRef"],
                "safeEvidenceRef": f"evidence:{claimed['packetSafeHash'][:16]}",
            }
        ],
        "candidateReviews": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _assert_safe_payload(payload: dict, transient_parent: Path) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)
    assert str(transient_parent) not in serialized


def _sample_code(skill_id: str, *, ascendancy: str, level: int) -> str:
    return pob_code.encode_code(_sample_xml(skill_id, ascendancy=ascendancy, level=level))


def _sample_xml(skill_id: str, *, ascendancy: str, level: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="{level}" className="Ranger" ascendClassName="{ascendancy}" mainSocketGroup="1" />
  <Skills>
    <Skill mainActiveSkillCalcs="{skill_id}">
      <Gem nameSpec="{skill_id}" skillId="{skill_id}" enabled="true" />
    </Skill>
  </Skills>
</PathOfBuilding2>
"""


def _rich_sample_xml() -> str:
    nodes = ",".join(str(value) for value in range(100, 160))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Witch" ascendClassName="Blood Mage" mainSocketGroup="1" />
  <Skills activeSkillSet="1">
    <SkillSet id="1">
      <Skill enabled="true"><Gem nameSpec="Plasma Blast" skillId="PlasmaBlastPlayer" enabled="true" /><Gem nameSpec="Controlled Destruction" skillId="SupportControlledDestruction" gemId="SupportGemControlledDestruction" enabled="true" /></Skill>
      <Skill enabled="true"><Gem nameSpec="Bonestorm" skillId="BonestormPlayer" enabled="true" /><Gem nameSpec="Arcane Tempo" skillId="SupportArcaneTempo" gemId="SupportGemArcaneTempo" enabled="true" /></Skill>
      <Skill enabled="true"><Gem nameSpec="Blasphemy" skillId="BlasphemyPlayer" enabled="true" /></Skill>
    </SkillSet>
  </Skills>
  <Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="{nodes}" nodes1="201,202" nodes2="301"><Sockets></Sockets></Spec></Tree>
  <Items activeItemSet="1">
    <Item id="1">Rarity: RARE\nResearch Wand\nAttuned Wand\nItem Level: 90\n+3 to Level of all Spell Skills\n80% increased Spell Damage</Item>
    <Item id="2">Rarity: UNIQUE\nResearch Armour\nSilk Robe\nItem Level: 90\nGain a defensive state while casting</Item>
    <ItemSet id="1"><Slot name="Weapon 1" itemId="1" /><Slot name="Body Armour" itemId="2" /></ItemSet>
  </Items>
  <Config><Input name="conditionEnemyBoss" string="Pinnacle" /><Input name="conditionCritRecently" boolean="true" /></Config>
</PathOfBuilding2>
"""


def test_research_packet_marks_mutated_item_modifiers_without_raw_xml():
    from server.knowledge import research_packet

    parsed = research_packet._parse_item_text(
        """Rarity: UNIQUE
Rathpith Globe
Omen Crest Shield
Item Level: 90
{mutated} 20% increased Spell Damage per 100 Maximum Mana
10% increased Critical Hit Chance per 100 Maximum Life"""
    )

    assert parsed["itemStates"] == ["mutated"]
    assert parsed["mutatedModifiers"] == ["20% increased Spell Damage per 100 Maximum Mana"]
    assert "rawXml" not in parsed


def test_research_packet_builds_safe_active_skill_evidence_manifest():
    from server.knowledge import research_packet

    manifest = research_packet.build_skill_evidence_manifest(
        {"rawContext": {"rawXml": _rich_sample_xml()}}
    )

    assert [
        [skill["name"] for skill in item["activeSkills"]] for item in manifest["activeSkillGroups"]
    ] == [
        ["Plasma Blast"],
        ["Bonestorm"],
        ["Blasphemy"],
    ]
    assert manifest["activeSkillGroups"][0]["supports"] == [
        {
            "name": "Controlled Destruction",
            "gemId": "SupportGemControlledDestruction",
            "nameSource": "gem_name",
            "enableGlobal1": True,
            "enableGlobal2": False,
        }
    ]
    assert manifest["activeSkillGroups"][0]["weaponSetScope"] == "global"
    assert manifest["noRawMatureBuildMaterial"] is True
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert "<Skills" not in serialized
    assert "rawXml" not in serialized


def test_compact_accept_report_only_for_clean_results():
    from scripts import research_mature_builds as rmb

    clean = {
        "status": "accepted",
        "deferredCandidateCount": 0,
        "caseCoverageGapCount": 0,
        "unresolvedDeepRecordMentionCount": 0,
        "unresolvedUniqueComponentCount": 0,
    }
    assert rmb._should_compact_report(clean) is True
    assert rmb._should_compact_report({**clean, "deferredCandidateCount": 1}) is False
    assert rmb._should_compact_report({**clean, "status": "validation_failed"}) is False
    assert rmb._should_compact_report({**clean, "unresolvedDeepRecordComponentCount": 2}) is False
    assert rmb._should_compact_report({**clean, "caseCoverageGapCount": 1}) is False
    assert rmb._should_compact_report({**clean, "status": "validation_passed"}) is True


def test_compact_accept_result_strips_bulk_blocks_and_keeps_quality_summary():
    from scripts import research_mature_builds as rmb

    result = {
        "status": "accepted",
        "sampleId": "case:fixture",
        "acceptedDeepRecordCount": 2,
        "deferredReasonCounts": {},
        "mechanicAudit": {
            "entryCount": 10,
            "pinnedRevisionCount": 6,
            "liveEvidenceStatus": "partial",
            "schemaIssueCount": 0,
            "unauditedHighRiskRecordCount": 0,
            "entries": [{"index": 0, "claim": "long claim body"}],
        },
        "sourceEvidenceDiagnostics": {"available": True, "unstructuredSourceSupportMentions": []},
        "patternWrite": {"status": "accepted", "patternIds": ["bdp-1"]},
        "deepRecordWrite": {
            "status": "accepted",
            "recordWrites": [
                {
                    "title": "long canonical",
                    "crossFamilyDuplicateAdvisories": ["safe duplicate advisory"],
                }
            ],
        },
        "deferredCandidates": [],
        "noRawMatureBuildMaterial": True,
    }
    compact = rmb._compact_accept_result(result)

    assert compact["mechanicAudit"] == {
        "entryCount": 10,
        "pinnedRevisionCount": 6,
        "liveEvidenceStatus": "partial",
        "schemaIssueCount": 0,
        "unauditedHighRiskRecordCount": 0,
    }
    assert "entries" not in compact["mechanicAudit"]
    assert "sourceEvidenceDiagnostics" not in compact
    assert "patternWrite" not in compact
    assert "deepRecordWrite" not in compact
    assert "deferredCandidates" not in compact
    assert compact["acceptedDeepRecordCount"] == 2
    assert compact["writeAdvisoryCounts"] == {"crossFamilyDuplicate": 1}
    assert compact["status"] == "accepted"
    assert compact["noRawMatureBuildMaterial"] is True


def test_research_packet_captures_tree_jewels_via_sockets_mapping():
    from server.knowledge import research_packet

    metadata = research_packet._passive_node_metadata("0_5")
    socket_ids = [
        node_id
        for node_id, meta in metadata.items()
        if "jewel_socket" in (meta.get("nodeTypes") or [])
    ]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="1">
    <Spec treeVersion="0_5" nodes="{socket_ids[0]}">
      <Sockets><Socket nodeId="{socket_ids[0]}" itemId="1"/></Sockets>
    </Spec>
  </Tree>
  <Items activeItemSet="1">
    <Item id="1">Rarity: RARE\nRapture Curio\nTime-Lost Ruby\nItem Level: 80\nLevelReq: 0\nRadius: Large\nUpgrades Radius to Large\nNotable Passive Skills in Radius also grant 5% increased Life Regeneration rate\nSmall Passive Skills in Radius also grant 2% increased Fire Damage\nSmall Passive Skills in Radius also grant 3% increased Warcry Speed</Item>
    <Item id="2">Rarity: RARE\nFate Core\nSiege Crossbow\nItem Level: 80\nLevelReq: 79\nAdds 92 to 143 Fire Damage</Item>
    <Item id="3">Rarity: NORMAL\nSpare Staff\nGnarled Branch\nItem Level: 5\n20% increased Spell Damage</Item>
    <ItemSet id="1"><Slot name="Weapon 1 Swap" itemId="2" /></ItemSet>
  </Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}
    sections = research_packet._packet_sections(packet)
    jewel_items = [item for item in sections["gear"] if "Time-Lost" in str(item.get("base") or "")]
    assert len(jewel_items) == 1
    assert jewel_items[0]["slot"] == f"Jewel {socket_ids[0]}"
    assert jewel_items[0]["socketSource"] == "tree_socket"
    assert jewel_items[0]["name"] == "Rapture Curio"
    assert any(
        "Notable Passive Skills in Radius also grant" in mod for mod in jewel_items[0]["modifiers"]
    )
    assert any(
        "Small Passive Skills in Radius also grant 2% increased Fire Damage" in mod
        for mod in jewel_items[0]["modifiers"]
    )
    # The spare staff is inventory, not equipped gear: it never enters the gear section.
    assert not any("Gnarled Branch" in str(item.get("name") or "") for item in sections["gear"])
    counts = research_packet.jewel_counts(packet, sections=sections)
    assert counts["status"] == "ok"
    assert counts["allocatedJewelSocketCount"] == 1
    assert counts["treeSocketedJewelCount"] == 1
    assert counts["embeddedJewelCount"] == 0
    assert counts["socketedJewelCount"] == 1
    assert [item["nodeId"] for item in counts["activeAllocatedFilled"]] == [socket_ids[0]]
    assert counts["activeAllocatedEmpty"] == []
    assert counts["activeSocketedUnallocated"] == []
    assert counts["otherSpecSocketed"] == []
    assert isinstance(counts["countNotes"], list)
    assert any("active passive spec" in note for note in counts["countNotes"])
    assert any("tree socket" in note for note in counts["countNotes"])
    assert research_packet.jewel_advisories(packet, sections=sections) == []
    assert len(sections["jewels"]) == 1
    assert sections["jewels"][0]["name"] == "Rapture Curio"
    assert sections["jewels"][0]["socketSource"] == "tree_socket"
    assert sections["jewels"][0]["slot"] == f"Jewel {socket_ids[0]}"
    assert research_packet.RESEARCH_SECTIONS.index("jewels") == 2
    inspected = research_packet.inspect_packet(packet)
    assert inspected["unslottedItemCount"] == 1
    assert "Spare Staff" in inspected["unslottedItemNames"]


def test_research_packet_counts_ascendancy_granted_jewel_socket():
    from server.knowledge import research_packet

    node_id = "17788"
    metadata = research_packet._passive_node_metadata("0_5")
    assert "granted_jewel_socket" in metadata[node_id]["nodeTypes"]
    filled_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Witch" ascendClassName="Abyssal Lich" />
  <Tree activeSpec="1">
    <Spec treeVersion="0_5" nodes="{node_id}">
      <Sockets><Socket nodeId="{node_id}" itemId="1"/></Sockets>
    </Spec>
  </Tree>
  <Items activeItemSet="1">
    <Item id="1">Rarity: RARE\nPhylactery Jewel\nEmerald\nItem Level: 80</Item>
    <ItemSet id="1" />
  </Items>
</PathOfBuilding2>
"""
    filled = research_packet.jewel_counts({"rawContext": {"rawXml": filled_xml}})
    assert filled["allocatedJewelSocketCount"] == 1
    assert filled["activeAllocatedFilled"] == [
        {
            "nodeId": node_id,
            "specId": "1",
            "itemId": "1",
            "activeSpec": True,
            "socketKind": "granted_jewel_socket",
        }
    ]
    assert filled["activeSocketedUnallocated"] == []

    empty_xml = filled_xml.replace(f'<Socket nodeId="{node_id}" itemId="1"/>', "")
    empty = research_packet.jewel_counts({"rawContext": {"rawXml": empty_xml}})
    assert empty["allocatedJewelSocketCount"] == 1
    assert empty["activeAllocatedEmpty"] == [
        {
            "nodeId": node_id,
            "specId": "1",
            "socketKind": "granted_jewel_socket",
        }
    ]


def test_research_packet_uses_unknown_socket_kind_without_tree_metadata():
    from server.knowledge import research_packet

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Witch" ascendClassName="Abyssal Lich" />
  <Tree activeSpec="1">
    <Spec treeVersion="missing" nodes="123">
      <Sockets><Socket nodeId="123" itemId="1"/></Sockets>
    </Spec>
  </Tree>
  <Items activeItemSet="1">
    <Item id="1">Rarity: RARE\nUnknown Socket Jewel\nEmerald</Item>
    <ItemSet id="1" />
  </Items>
</PathOfBuilding2>
"""
    counts = research_packet.jewel_counts({"rawContext": {"rawXml": xml}})
    assert counts["status"] == "tree_data_missing"
    assert counts["activeSocketedUnallocated"][0]["socketKind"] == "unknown"


def test_research_packet_distinguishes_global_effect_flags_from_group_weapon_set():
    from server.knowledge import research_packet

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Ranger" ascendClassName="Deadeye" />
  <Skills activeSkillSet="1">
    <SkillSet id="1">
      <Skill enabled="true" mainActiveSkill="1" slot="Weapon 1">
        <Gem nameSpec="Spark" skillId="SparkPlayer" enabled="true" />
        <Gem nameSpec="Both Support" gemId="Metadata/Items/Gems/SupportGemBoth" enabled="true" enableGlobal1="true" enableGlobal2="true" />
      </Skill>
      <Skill enabled="true" mainActiveSkill="1" slot="Weapon 1 Swap">
        <Gem nameSpec="Arc" skillId="ArcPlayer" enabled="true" enableGlobal1="false" enableGlobal2="true" />
      </Skill>
      <Skill enabled="true" mainActiveSkill="1" slot="Helmet">
        <Gem nameSpec="Ice Nova" skillId="IceNovaPlayer" enabled="true" />
        <Gem nameSpec="Disabled Support" gemId="Metadata/Items/Gems/SupportGemDisabled" enabled="true" enableGlobal1="false" enableGlobal2="false" />
      </Skill>
    </SkillSet>
  </Skills>
  <Tree activeSpec="1"><Spec treeVersion="0_5" nodes=""><Sockets /></Spec></Tree>
  <Items activeItemSet="1"><ItemSet id="1" /></Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}
    groups = research_packet._packet_sections(packet)["skills"]
    gems = {gem["name"]: gem for group in groups for gem in group["gems"]}
    assert (
        gems["Spark"]["enableGlobal1"],
        gems["Spark"]["enableGlobal2"],
    ) == (True, False)
    assert (
        gems["Arc"]["enableGlobal1"],
        gems["Arc"]["enableGlobal2"],
    ) == (False, True)
    assert "weaponSetScope" not in gems["Spark"]
    assert "weaponSetScope" not in gems["Both Support"]
    assert [group["weaponSetScope"] for group in groups] == [
        "weapon_set_1",
        "weapon_set_2",
        "global",
    ]

    manifest = research_packet.build_skill_evidence_manifest(packet)["activeSkillGroups"]
    assert [group["weaponSetScope"] for group in manifest] == [
        "weapon_set_1",
        "weapon_set_2",
        "global",
    ]
    manifest_gems = {
        item["name"]: item
        for group in manifest
        for key in ("activeSkills", "supports")
        for item in group[key]
    }
    assert manifest_gems["Arc"]["enableGlobal2"] is True
    assert manifest_gems["Disabled Support"]["enableGlobal1"] is False
    assert "weaponSetScope" not in manifest_gems["Arc"]


def test_research_packet_jewel_counts_counts_embedded_item_sockets():
    from server.knowledge import research_packet

    metadata = research_packet._passive_node_metadata("0_5")
    socket_ids = [
        node_id
        for node_id, meta in metadata.items()
        if "jewel_socket" in (meta.get("nodeTypes") or [])
    ]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="1">
    <Spec treeVersion="0_5" nodes="{socket_ids[0]}"><Sockets></Sockets></Spec>
  </Tree>
  <Items activeItemSet="1">
    <Item id="3">Rarity: RARE\nResearch Jewel\nEmerald\nItem Level: 82\n12% increased Attack Speed</Item>
    <Item id="4">Rarity: RARE\nOffhand Jewel\nEmerald\nItem Level: 82\n8% increased Attack Speed</Item>
    <ItemSet id="1">
      <Slot name="Body Armour Jewel Socket 1" itemId="3" />
      <Slot name="Body Armour" itemId="0" />
    </ItemSet>
    <ItemSet id="2">
      <Slot name="Body Armour Jewel Socket 1" itemId="4" />
    </ItemSet>
  </Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}
    counts = research_packet.jewel_counts(packet)

    assert counts["status"] == "ok"
    assert counts["allocatedJewelSocketCount"] == 1
    assert counts["treeSocketedJewelCount"] == 0
    assert counts["embeddedJewelCount"] == 1  # only the active item set's embedded jewel
    assert counts["socketedJewelCount"] == 1
    assert any("equipment jewel socket" in note for note in counts["countNotes"])
    assert any("cannot fill an empty tree socket" in note for note in counts["countNotes"])
    # Empty tree socket with only embedded jewels still needs a declaration.
    assert any("jewel socket" in item for item in research_packet.jewel_advisories(packet))


def test_research_packet_jewel_counts_allocated_scope_is_active_spec_only():
    from server.knowledge import research_packet

    metadata = research_packet._passive_node_metadata("0_5")
    socket_ids = [
        node_id
        for node_id, meta in metadata.items()
        if "jewel_socket" in (meta.get("nodeTypes") or [])
    ]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="2">
    <Spec treeVersion="0_5" nodes="{socket_ids[0]}"><Sockets></Sockets></Spec>
    <Spec treeVersion="0_5" nodes="{socket_ids[0]},{socket_ids[1]}"><Sockets></Sockets></Spec>
  </Tree>
  <Items activeItemSet="1"><ItemSet id="1" /></Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}
    counts = research_packet.jewel_counts(packet)

    assert counts["status"] == "ok"
    assert counts["allocatedJewelSocketCount"] == 2  # active spec 2 only
    assert counts["treeSocketedJewelCount"] == 0
    assert any("carry no socketed tree jewel" in note for note in counts["countNotes"])
    assert any("jewel socket" in item for item in research_packet.jewel_advisories(packet))


def test_research_packet_jewel_counts_classifies_active_and_other_specs_per_socket():
    from server.knowledge import research_packet

    metadata = research_packet._passive_node_metadata("0_5")
    socket_ids = [
        node_id
        for node_id, meta in metadata.items()
        if "jewel_socket" in (meta.get("nodeTypes") or [])
    ]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="2">
    <Spec treeVersion="0_5" nodes="{socket_ids[0]}"><Sockets><Socket nodeId="{socket_ids[0]}" itemId="1"/></Sockets></Spec>
    <Spec treeVersion="0_5" nodes="{socket_ids[0]},{socket_ids[1]}">
      <Sockets>
        <Socket nodeId="{socket_ids[0]}" itemId="2"/>
        <Socket nodeId="{socket_ids[2]}" itemId="3"/>
      </Sockets>
    </Spec>
  </Tree>
  <Items activeItemSet="1">
    <Item id="1">Rarity: RARE\nOther Spec Jewel\nEmerald\nItem Level: 80</Item>
    <Item id="2">Rarity: RARE\nActive Jewel\nEmerald\nItem Level: 80</Item>
    <Item id="3">Rarity: RARE\nUnallocated Jewel\nEmerald\nItem Level: 80</Item>
    <ItemSet id="1" />
  </Items>
</PathOfBuilding2>
"""
    counts = research_packet.jewel_counts({"rawContext": {"rawXml": xml}})

    assert [item["nodeId"] for item in counts["activeAllocatedFilled"]] == [socket_ids[0]]
    assert [item["nodeId"] for item in counts["activeAllocatedEmpty"]] == [socket_ids[1]]
    assert [item["nodeId"] for item in counts["activeSocketedUnallocated"]] == [socket_ids[2]]
    assert [item["nodeId"] for item in counts["otherSpecSocketed"]] == [socket_ids[0]]


def test_research_packet_jewel_counts_drops_stale_socket_references():
    from server.knowledge import research_packet

    metadata = research_packet._passive_node_metadata("0_5")
    socket_ids = [
        node_id
        for node_id, meta in metadata.items()
        if "jewel_socket" in (meta.get("nodeTypes") or [])
    ]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="1">
    <Spec treeVersion="0_5" nodes="{socket_ids[0]}">
      <Sockets>
        <Socket nodeId="{socket_ids[0]}" itemId="99"/>
        <Socket nodeId="{socket_ids[0]}" itemId="0"/>
        <Socket nodeId="" itemId="1"/>
      </Sockets>
    </Spec>
  </Tree>
  <Items activeItemSet="1">
    <Item id="1">Rarity: RARE\nResearch Jewel\nEmerald\nItem Level: 82\n12% increased Attack Speed</Item>
    <ItemSet id="1" />
  </Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}
    sections = research_packet._packet_sections(packet)
    counts = research_packet.jewel_counts(packet, sections=sections)

    # All three stale entries are dropped: missing item, non-positive id, empty node id.
    assert counts["treeSocketedJewelCount"] == 0
    assert counts["allocatedJewelSocketCount"] == 1
    assert any("jewel socket" in item for item in research_packet.jewel_advisories(packet))


def test_research_packet_extracts_weapon_set_passives_without_double_count():
    from server.knowledge import research_packet

    # A plain allocated node plus a weapon-set member (WeaponSet1 child element).
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="1">
    <Spec treeVersion="0_5" nodes="100,101">
      <Sockets></Sockets>
      <WeaponSet1 nodes="101" />
    </Spec>
  </Tree>
  <Items activeItemSet="1"><ItemSet id="1" /></Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}
    sections = research_packet._packet_sections(packet)
    allocated = [item for item in sections["passives"] if item.get("kind") == "allocated_node"]
    weapon_set = [item for item in sections["passives"] if item.get("kind") == "weapon_set_node"]
    assert len(allocated) == 2
    assert weapon_set == []
    node_101 = next(item for item in allocated if item.get("nodeId") == "101")
    assert node_101["weaponSet"] == 1
    assert node_101["activeSpec"] is True
    node_100 = next(item for item in allocated if item.get("nodeId") == "100")
    assert node_100["weaponSet"] is None
    spec = next(item for item in sections["passives"] if item.get("kind") == "spec")
    assert spec["weaponSet1NodeCount"] == 1


def test_research_packet_jewel_counts_flags_tree_data_missing():
    from server.knowledge import research_packet

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="1"><Spec id="1" treeVersion="0_5_unknown_tree" nodes="2491" /></Tree>
  <Items activeItemSet="1"><ItemSet id="1" /></Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}
    counts = research_packet.jewel_counts(packet)

    assert counts["status"] == "tree_data_missing"
    assert any("node metadata" in item for item in research_packet.jewel_advisories(packet))


def test_research_packet_inspect_exposes_jewel_counts_without_raw_xml():
    from server.knowledge import research_packet

    packet = {"rawContext": {"rawXml": _rich_sample_xml()}}
    inspected = research_packet.inspect_packet(packet)

    assert inspected["jewelCounts"]["status"] == "ok"
    assert isinstance(inspected["jewelCounts"]["allocatedJewelSocketCount"], int)
    assert isinstance(inspected["jewelAdvisories"], list)
    serialized = json.dumps(inspected, ensure_ascii=False)
    assert "<Tree" not in serialized
    assert "rawXml" not in serialized


def test_queue_persists_quarantine_and_resume_rebuilds_missing_packets(tmp_path):
    from scripts import research_mature_builds

    batch_file = tmp_path / "samples.txt"
    batch_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
        + "\n---POB-SAMPLE---\n"
        + _sample_code("SparkPlayer", ascendancy="Stormweaver", level=96),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp"

    queued = research_mature_builds.queue_cases(
        source_batch_files=[batch_file],
        output_dir=output_dir,
        temp_root=temp_root,
        worker_count=5,
        ttl_seconds=24 * 60 * 60,
    )
    assert queued["status"] == "queued"
    assert queued["sampleCount"] == 2

    quarantine = output_dir / "quarantine"
    quarantine_files = list(quarantine.glob("*.json"))
    assert len(quarantine_files) == 2
    for file in quarantine_files:
        payload = json.loads(file.read_text(encoding="utf-8"))
        assert payload["rawImportCode"]
        assert payload["sampleId"]
        assert payload["sourceHash"]

    db_path = output_dir / "poe_bd_research_queue.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        hashes_before = {
            str(row["packet_safe_hash"])
            for row in conn.execute("SELECT packet_safe_hash FROM cases")
            if str(row["packet_safe_hash"])
        }
        conn.execute("UPDATE metadata SET value = '1' WHERE key = 'requestedWorkerCount'")
        conn.execute(
            "UPDATE metadata SET value = 'serial_one_case_at_a_time' "
            "WHERE key = 'workerCountSemantics'"
        )
        conn.commit()
    assert len(hashes_before) == 2

    # Destroy every transient packet, then resume: packets must be rebuilt from quarantine
    # without fetching new samples.
    for packet_dir in temp_root.glob("poe-bd-creator-research-packet-*"):
        for child in packet_dir.rglob("*"):
            if child.is_file():
                child.unlink()
    resumed = research_mature_builds.queue_cases(
        output_dir=output_dir,
        temp_root=temp_root,
        worker_count=5,
        ttl_seconds=24 * 60 * 60,
        resume=True,
    )
    assert resumed["status"] == "resumed"
    assert resumed["resumeSummary"]["packetRebuiltCount"] == 2
    assert resumed["resumeSummary"]["packetIntactCount"] == 0
    assert resumed["resumeSummary"]["unrecoverableCaseCount"] == 0
    assert resumed["sampleCount"] == 2
    assert resumed["requestedWorkerCount"] == 5
    assert resumed["workerCountSemantics"] == "parallel_subagents_one_case_each"

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        hashes_after = {
            str(row["packet_safe_hash"])
            for row in conn.execute("SELECT packet_safe_hash FROM cases")
            if str(row["packet_safe_hash"])
        }
    assert hashes_after == hashes_before


def test_resume_drops_unrecoverable_cases_without_quarantine(tmp_path):
    from scripts import research_mature_builds

    batch_file = tmp_path / "samples.txt"
    batch_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
        + "\n---POB-SAMPLE---\n"
        + _sample_code("SparkPlayer", ascendancy="Stormweaver", level=96),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-drop"

    queued = research_mature_builds.queue_cases(
        source_batch_files=[batch_file],
        output_dir=output_dir,
        temp_root=temp_root,
        worker_count=5,
        ttl_seconds=24 * 60 * 60,
    )
    assert queued["sampleCount"] == 2

    # Remove the quarantine AND all packets: the raw material is unrecoverable.
    for file in (output_dir / "quarantine").glob("*.json"):
        file.unlink()
    for packet_dir in temp_root.glob("poe-bd-creator-research-packet-*"):
        for child in packet_dir.rglob("*"):
            if child.is_file():
                child.unlink()

    resumed = research_mature_builds.queue_cases(
        output_dir=output_dir,
        temp_root=temp_root,
        worker_count=5,
        ttl_seconds=24 * 60 * 60,
        resume=True,
    )
    assert resumed["status"] == "resumed"
    assert resumed["resumeSummary"]["unrecoverableCaseCount"] == 2
    assert resumed["sampleCount"] == 0

    db_path = output_dir / "poe_bd_research_queue.sqlite"
    with sqlite3.connect(db_path) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    assert remaining == 0


def test_accept_removes_transient_packet_after_success(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    batch_file = tmp_path / "samples.txt"
    batch_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-accept-cleanup"

    queued = research_mature_builds.queue_cases(
        source_batch_files=[batch_file],
        output_dir=output_dir,
        temp_root=temp_root,
        worker_count=5,
        ttl_seconds=24 * 60 * 60,
    )
    assert queued["sampleCount"] == 1

    claim = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claim["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claim)

    def fake_accept_deep_review_candidates(**kwargs):
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "recordKindCounts": {},
            "caseCoverage": {
                "supports": "covered",
                "rotation": "covered",
                "passiveAscendancy": "covered",
                "gearRoles": "covered",
                "resourceDefense": "covered",
            },
            "caseCoverageGapCount": 0,
            "caseCoverageGaps": [],
            "singleComponentObservationCount": 0,
            "createdBuildFamilyCount": 1,
            "addedBuildFamilyEvidenceCount": 1,
            "recordKindAdvisories": [],
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
            "deepRecordWrite": {"status": "accepted"},
            "acceptedDeepRecordCount": 0,
            "acceptedBuildFamilyKeys": ["bf-fixture"],
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claim["leaseToken"],
        review_file=review_file,
    )
    assert accepted["status"] == "accepted"

    remaining = [
        p
        for p in temp_root.glob("poe-bd-creator-research-packet-*/packet.json")
        if claim["packetSafeHash"] in p.read_text(encoding="utf-8")
    ]
    assert remaining == []


def test_cleanup_expired_packets_removes_expired_packets(tmp_path):
    from server.knowledge import research_packet
    from datetime import datetime, timedelta, timezone

    temp_root = tmp_path / "packets"
    temp_root.mkdir(parents=True, exist_ok=True)
    research_packet.build_research_packet(
        {"safeMetadata": {}, "rawContext": {}},
        persist_for_transport=True,
        ttl_seconds=1,
        temp_root=temp_root,
    )
    later = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(timespec="seconds")

    # An expired packet is removed.
    cleaned = research_packet.cleanup_expired_packets(temp_root=temp_root, now=later)
    assert cleaned["removed"] == 1
    assert not list(temp_root.glob("poe-bd-creator-research-packet-*"))

    # A not-yet-expired packet survives when cleaned at the current time.
    research_packet.build_research_packet(
        {"safeMetadata": {}, "rawContext": {}},
        persist_for_transport=True,
        ttl_seconds=3600,
        temp_root=temp_root,
    )
    kept = research_packet.cleanup_expired_packets(temp_root=temp_root)
    assert kept["removed"] == 0
    assert list(temp_root.glob("poe-bd-creator-research-packet-*"))  # packet2 survives


def test_packet_publication_hides_incomplete_staging_directory(tmp_path, monkeypatch):
    from server.knowledge import research_packet

    temp_root = tmp_path / "packets"
    temp_root.mkdir(parents=True, exist_ok=True)
    real_write_text = Path.write_text
    staging_names: list[str] = []

    def reject_restrictive_mkdtemp(*args, **kwargs):
        raise AssertionError("packet staging must inherit the private run root ACL")

    def write_while_cleanup_runs(path: Path, data: str, **kwargs):
        if path.name == "packet.json" and path.parent.parent == temp_root:
            staging_names.append(path.parent.name)
            assert path.parent.name.startswith(f".{research_packet.PACKET_PREFIX}")
            assert research_packet.cleanup_expired_packets(temp_root=temp_root)["removed"] == 0
        return real_write_text(path, data, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_while_cleanup_runs)
    monkeypatch.setattr(research_packet.tempfile, "mkdtemp", reject_restrictive_mkdtemp)
    result = research_packet.build_research_packet(
        {"safeMetadata": {}, "rawContext": {}},
        persist_for_transport=True,
        ttl_seconds=3600,
        temp_root=temp_root,
    )

    packet_path = Path(result["packetPath"])
    assert packet_path.is_file()
    assert packet_path.parent.name.startswith(research_packet.PACKET_PREFIX)
    if research_packet.os.name != "nt":
        assert packet_path.parent.stat().st_mode & 0o777 == 0o700
    assert staging_names
    assert not list(temp_root.glob(f".{research_packet.PACKET_PREFIX}*"))


def test_claim_rebuilds_missing_packet_from_quarantine(tmp_path):
    from scripts import research_mature_builds

    batch_file = tmp_path / "samples.txt"
    batch_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-claim-rebuild"

    research_mature_builds.queue_cases(
        source_batch_files=[batch_file],
        output_dir=output_dir,
        temp_root=temp_root,
        worker_count=5,
        ttl_seconds=24 * 60 * 60,
    )

    # Destroy the queued packet; claim must rebuild it from quarantine with lease TTL.
    for packet_dir in temp_root.glob("poe-bd-creator-research-packet-*"):
        for child in packet_dir.rglob("*"):
            if child.is_file():
                child.unlink()

    claimed = research_mature_builds.claim_case(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_seconds=1800,
    )
    assert claimed["status"] == "claimed"
    assert claimed["packetSafeHash"]

    rebuilt = [
        p
        for p in temp_root.glob("poe-bd-creator-research-packet-*/packet.json")
        if claimed["packetSafeHash"] in p.read_text(encoding="utf-8")
    ]
    assert len(rebuilt) == 1
    packet = json.loads(rebuilt[0].read_text(encoding="utf-8"))
    assert packet["safeHash"] == claimed["packetSafeHash"]


def test_claim_rewrites_existing_packet_expiry_to_lease_ttl(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from scripts import research_mature_builds

    batch_file = tmp_path / "samples.txt"
    batch_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-claim-expiry"

    research_mature_builds.queue_cases(
        source_batch_files=[batch_file],
        output_dir=output_dir,
        temp_root=temp_root,
        worker_count=5,
        ttl_seconds=24 * 60 * 60,
    )

    # The queued packet exists with a 24h TTL; claim must rewrite its expiry to the lease TTL.
    queued_packets = list(temp_root.glob("poe-bd-creator-research-packet-*/packet.json"))
    assert len(queued_packets) == 1
    queued = json.loads(queued_packets[0].read_text(encoding="utf-8"))
    real_replace = research_mature_builds.os.replace
    replace_observations: list[dict] = []

    def replace_after_observing_complete_old_packet(source, destination):
        replace_observations.append(json.loads(Path(destination).read_text(encoding="utf-8")))
        assert Path(source).name != "packet.json"
        real_replace(source, destination)

    monkeypatch.setattr(
        research_mature_builds.os,
        "replace",
        replace_after_observing_complete_old_packet,
    )

    claimed = research_mature_builds.claim_case(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_seconds=1800,
    )
    assert claimed["status"] == "claimed"

    packets = list(temp_root.glob("poe-bd-creator-research-packet-*/packet.json"))
    assert len(packets) == 1  # expiry rewritten in place, no duplicate packet dir
    packet = json.loads(packets[0].read_text(encoding="utf-8"))
    assert packet["safeHash"] == queued["safeHash"]
    assert packet["safeHash"] == claimed["packetSafeHash"]
    assert replace_observations[0]["safeHash"] == queued["safeHash"]

    expires = datetime.fromisoformat(packet["expiresAt"])
    now = datetime.now(timezone.utc)
    remaining = (expires - now).total_seconds()
    # Lease is 1800s; allow a few seconds of execution slack on either side.
    assert 1700 <= remaining <= 1900


def test_empty_support_coverage_exceptions_list_is_treated_as_absent():
    from server.knowledge import research_models

    record = research_models.DeepResearchRecordProposal(
        research_group_id="research:fixture",
        record_kind="mechanic_chain",
        title="聚焦机制链",
        summary="只记录一个机制问题。",
        content="这条记录只解释一个主要机制问题及其成立条件。",
        content_language="zh-CN",
        length_exception_reason=None,
        component_keys=["skill:SparkPlayer"],
        component_mentions=[
            {
                "candidate_name": "Spark",
                "component_key": "skill:SparkPlayer",
                "resolver_query": "skill:SparkPlayer",
                "resolution_status": "resolved",
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "role": "primary_damage",
            }
        ],
        source_case_refs=["source-hash:fixture"],
        safe_evidence_refs=["evidence:fixture"],
        conditions=[],
        failure_conditions=[],
        typed_payload={
            "knowledgeShape": "state_causal_chain",
            "supportCoverageExceptions": [],
        },
        class_key="class:sorceress",
        ascendancy_key="ascendancy:sorceress:stormweaver",
        extraction_method_version="deep_research_mvp_v1",
        record_schema_version=1,
        game_patch="0.5.4",
        passive_tree_version="0_5",
        pob_version_or_commit="0.22.0",
        visibility="creator_visible",
        split="train_context",
        knowledge_scope="global_seed",
        status="valid",
        copy_safety_state="passed",
    )
    assert record.typed_payload["supportCoverageExceptions"] == []


def test_canonical_review_artifact_identity_reports_mismatch_details(tmp_path):
    from scripts import research_mature_builds as rmb

    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "safeArtifactOnly": True,
                "artifactIdentity": {
                    "sampleId": "case:other",
                    "caseRef": "source-hash:other",
                    "safeEvidenceRef": "evidence:deadbeefdeadbeef",
                    "packetSafeHash": "deadbeef" * 8,
                },
                "deepResearchRecords": [],
                "candidateReviews": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc:
        rmb._canonical_review_artifact_identity(
            review_file=review,
            sample_id="case:target",
            source_hash_ref="source-hash:target",
            packet_safe_hash="a" * 64,
            version_context={
                "gamePatch": "0.5.4",
                "passiveTreeVersion": "0_5",
                "pobVersionOrCommit": "0.22.0",
            },
        )
    message = str(exc.value)
    assert "artifactIdentity does not match the current lease" in message
    assert "sampleId expected='case:target' actual='case:other'" in message
    assert "caseRef expected='source-hash:target' actual='source-hash:other'" in message
    assert "packetSafeHash" in message


def test_canonical_review_artifact_identity_binds_semantic_edges_to_lease(tmp_path):
    from scripts import research_mature_builds as rmb

    packet_hash = "a" * 64
    review = tmp_path / "semantic-edge-review.json"
    review.write_text(
        json.dumps(
            {
                "safeArtifactOnly": True,
                "artifactIdentity": {
                    "sampleId": "case:target",
                    "caseRef": "source-hash:target",
                    "safeEvidenceRef": "evidence:" + packet_hash[:16],
                    "packetSafeHash": packet_hash,
                },
                "deepResearchRecords": [{}],
                "candidateReviews": [],
                "semanticEdges": [
                    {
                        "source_case_refs": ["source-hash:<case>"],
                        "safe_evidence_refs": ["evidence:<packet>"],
                        "game_patch": "old-patch",
                        "passive_tree_version": "old-tree",
                        "pob_version_or_commit": "old-pob",
                        "context_requirements": [
                            {
                                "context_type": "version_context",
                                "game_patch": "old-patch",
                                "passive_tree_version": "old-tree",
                                "pob_version": "old-pob",
                            },
                            {
                                "context_type": "lifecycle_stage_requirement",
                                "stages": ["endgame_budget"],
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    canonical = rmb._canonical_review_artifact_identity(
        review_file=review,
        sample_id="case:target",
        source_hash_ref="source-hash:target",
        packet_safe_hash=packet_hash,
        version_context={
            "gamePatch": "0.5.4",
            "passiveTreeVersion": "0_5",
            "pobVersionOrCommit": "0.22.0",
        },
    )

    edge = canonical["semanticEdges"][0]
    assert edge["source_case_refs"] == ["source-hash:target"]
    assert edge["safe_evidence_refs"] == ["evidence:" + packet_hash[:16]]
    assert edge["game_patch"] == "0.5.4"
    assert edge["passive_tree_version"] == "0_5"
    assert edge["pob_version_or_commit"] == "0.22.0"
    assert edge["context_requirements"][0] == {
        "context_type": "version_context",
        "game_patch": "0.5.4",
        "passive_tree_version": "0_5",
        "pob_version": "0.22.0",
    }
    assert edge["context_requirements"][1]["context_type"] == ("lifecycle_stage_requirement")


def test_identity_resolvability_hint_resolves_renamed_ascendancy(tmp_path):
    from scripts import research_mature_builds as rmb

    hint = rmb._identity_resolvability_hint(ascendancy="Lich", main_skill="Chaos Bolt")
    assert hint["ascendancyCanonicalKey"] == "ascendancy:witch:abyssal_lich"
    assert hint["ascendancyResolvable"] is True

    unknown = rmb._identity_resolvability_hint(ascendancy="No Such Ascendancy 42", main_skill="")
    assert unknown["ascendancyResolvable"] is False
    assert unknown["ascendancyCanonicalKey"] is None
    assert unknown["primarySkillResolvable"] is False


def test_accept_only_record_slices_validation_payload(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-temp-only-record",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["artifactIdentity"] = {
        "sampleId": claimed["sampleId"],
        "caseRef": claimed["sourceHashRef"],
        "safeEvidenceRef": f"evidence:{claimed['packetSafeHash'][:16]}",
        "packetSafeHash": claimed["packetSafeHash"],
    }
    review["deepResearchRecords"] = [
        {**review["deepResearchRecords"][0], "title": "Selected record"},
        {**review["deepResearchRecords"][0], "title": "Other record"},
    ]
    review["candidateReviews"] = [{"title": "Excluded candidate"}]
    review["semanticEdges"] = [{"edge_type": "synergizes_with"}]
    review["mechanicAudit"] = [
        {
            "affectedRecords": ["Selected record", "Other record"],
            "affectedCandidates": ["Excluded candidate"],
        },
        {"affectedRecords": ["Other record"], "affectedCandidates": []},
    ]
    review_file.write_text(json.dumps(review), encoding="utf-8")
    calls: list[dict] = []

    def fake_accept(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedDeepRecordCount": 1,
            "recordKindCounts": {},
            "caseCoverage": {
                "supports": "covered",
                "rotation": "covered",
                "passiveAscendancy": "covered",
                "gearRoles": "covered",
                "resourceDefense": "covered",
            },
            "caseCoverageGapCount": 0,
            "caseCoverageGaps": [],
            "deferredCandidateCount": 0,
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept,
    )

    result = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
        validation_only=True,
        only_record=0,
    )

    assert result["singleRecordValidation"]["recordIndex"] == 0
    assert "note" in result["singleRecordValidation"]
    payload = calls[0]["review_payload"]
    assert len(payload["deepResearchRecords"]) == 1
    assert payload["candidateReviews"] == []
    assert payload["semanticEdges"] == []
    assert payload["mechanicAudit"] == [
        {"affectedRecords": ["Selected record"], "affectedCandidates": []}
    ]
    assert result["sliceContext"] == {
        "recordIndex": 0,
        "recordTitle": "Selected record",
        "excludedMechanicAuditCount": 1,
        "excludedCandidateCount": 1,
        "excludedSemanticEdgeCount": 1,
        "outOfSliceReferences": ["Excluded candidate", "Other record"],
    }


def test_only_record_slice_excludes_audit_when_record_title_is_ambiguous():
    from scripts import research_mature_builds

    sliced, context = research_mature_builds._slice_review_for_record(
        {
            "deepResearchRecords": [
                {"title": "Shared title", "recordKind": "resource_engine"},
                {"title": "Shared title", "recordKind": "mechanic_chain"},
            ],
            "candidateReviews": [],
            "semanticEdges": [],
            "mechanicAudit": [
                {
                    "affectedRecords": ["Shared title"],
                    "affectedCandidates": [],
                }
            ],
        },
        0,
    )

    assert sliced["mechanicAudit"] == []
    assert context["ambiguousRecordTitle"] == "Shared title"
    assert context["ambiguousMechanicAuditCount"] == 1
    assert context["outOfSliceReferences"] == ["Shared title"]


def test_accept_only_record_guards_out_of_range_and_non_validation(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-temp-only-record-guard",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)

    with pytest.raises(ValueError, match="out of range"):
        research_mature_builds.accept_case(
            output_dir=output_dir,
            lease_token=claimed["leaseToken"],
            review_file=claimed["reviewFile"],
            memory_db_path=tmp_path / "m1.sqlite",
            validation_only=True,
            only_record=5,
        )
    with pytest.raises(ValueError, match="only supported together with --validate-only"):
        research_mature_builds.accept_case(
            output_dir=output_dir,
            lease_token=claimed["leaseToken"],
            review_file=claimed["reviewFile"],
            memory_db_path=tmp_path / "m2.sqlite",
            validation_only=False,
            only_record=0,
        )


def test_review_contract_discloses_semantic_edge_template(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("MirageDeadeyePlayer", ascendancy="Pathfinder", level=100),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research-edge-contract"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-edge-contract",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    contract = research_mature_builds.render_review_contract(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
    )

    template = contract["semanticEdgeTemplate"]
    assert template["source_key"]
    assert template["target_key"]
    assert "enables_mechanic" in template["edge_type"]
    assert "synergizes_with" in template["edge_type"]
    assert template["source_resolution"]["tool_name"] == "resolve_graph_component"
    assert template["source_resolution"]["status"] == "resolved"
    assert "stable_key" in template["source_resolution"]
    assert "evidence_path_nodes" in template["source_resolution"]
    assert "snapshot_id" in template["source_resolution"]
    assert "source_refs" in template["source_resolution"]
    assert "target_resolution" in template
    assert template["source_case_refs"] == [contract["artifactIdentity"]["caseRef"]]
    assert template["safe_evidence_refs"] == [contract["artifactIdentity"]["safeEvidenceRef"]]
    assert template["game_patch"] == contract["versionContext"]["gamePatch"]
    assert template["passive_tree_version"] == contract["versionContext"]["passiveTreeVersion"]
    assert template["pob_version_or_commit"] == contract["versionContext"]["pobVersionOrCommit"]
    assert template["context_requirements"][0]["game_patch"] == template["game_patch"]
    assert "affected_component_keys" in template
    assert "directionality" in template


def test_read_packet_section_skill_groups_from_rich_xml():
    from server.knowledge import research_packet

    packet = {"rawContext": {"rawXml": _rich_sample_xml()}}
    groups = research_packet.read_packet_section(packet, section="skill-groups")

    assert groups["status"] == "ok"
    assert groups["section"] == "skill-groups"
    active_names = {
        str(item["activeSkills"][0]["name"]) for item in groups["items"] if item["activeSkills"]
    }
    assert {"Plasma Blast", "Bonestorm", "Blasphemy"} <= active_names


def test_read_packet_section_continuity_warning_and_gap_free_chaining():
    from server.knowledge import research_packet

    # A 20k-char modifier guarantees the character budget truncates any page that contains it,
    # which used to make callers that resume at cursor+limit silently skip items.
    huge_mod = "X" * 20_000
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="1"><Spec treeVersion="0_5" nodes=""></Spec></Tree>
  <Items activeItemSet="1">
    <Item id="1">Rarity: RARE\nSmall Helm\nIron Circlet\nItem Level: 82\n+10 to maximum Life</Item>
    <Item id="2">Rarity: RARE\nBig Body\nPlate Vest\nItem Level: 82\n{huge_mod}</Item>
    <Item id="3">Rarity: RARE\nSmall Boots\nWool Shoes\nItem Level: 82\n+10% increased Movement Speed</Item>
    <ItemSet id="1">
      <Slot name="Helmet" itemId="1" />
      <Slot name="Body Armour" itemId="2" />
      <Slot name="Boots" itemId="3" />
    </ItemSet>
  </Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}

    seen: list[str] = []
    cursor = 0
    warning_count = 0
    while True:
        page = research_packet.read_packet_section(packet, section="gear", cursor=cursor, limit=50)
        assert page["status"] == "ok"
        seen.extend(str(item.get("name") or "") for item in page["items"])
        if "continuityWarning" in page:
            warning_count += 1
            assert page["nextCursor"] < cursor + page["limit"]
            assert "never at cursor+limit" in page["continuityWarning"]
        if page["complete"]:
            break
        cursor = page["nextCursor"]

    # Chaining by nextCursor covers every item exactly once, with no gaps and no overlaps.
    assert sorted(seen) == ["Big Body", "Small Boots", "Small Helm"]
    assert len(seen) == len(set(seen))
    assert warning_count >= 1


def test_is_pure_routing_passive():
    from server.knowledge import research_packet

    assert research_packet._is_pure_routing_passive({"stats": ["+5 to any Attribute"]}) is True
    assert research_packet._is_pure_routing_passive({"stats": []}) is True
    assert (
        research_packet._is_pure_routing_passive({"stats": ["10% increased Damage with Spears"]})
        is False
    )
