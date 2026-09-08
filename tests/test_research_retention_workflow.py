from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from scripts import research_mature_builds as research
from server import paths
from server.compute import pob_code
from server.knowledge import research_intake_ledger, research_retention, research_workflow


RUN_ID = "20260906-010203-abcd"
RUN_REF = f"research-run:{RUN_ID}"
CREATED = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
EXPIRED = CREATED + timedelta(days=7)
SOURCE_HASH = "a" * 64
CHARACTER_REF = "character-hash:" + "b" * 16
OTHER_CHARACTER_REF = "character-hash:" + "c" * 16
LEAGUE = "test-league"
RAW_SENTINEL = "private-source-sentinel-retention-test"


def _partial_summary():
    return {
        "acceptanceMode": "partial_with_deferred",
        "deferredCandidateCount": 1,
        "unresolvedDeepRecordMentionCount": 0,
        "caseCoverageGapCount": 1,
        "deferredReasonCounts": {"mechanic_evidence_missing": 1},
        "caseCoverageGaps": ["resourceDefense"],
    }


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    root = tmp_path / "user-data" / "research"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: root)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(research, "DEFAULT_OUTPUT_DIR", root)
    monkeypatch.setattr(research, "DEFAULT_INTAKE_LEDGER_PATH", tmp_path / "intake.sqlite")
    monkeypatch.setattr(research, "_now", lambda: EXPIRED)
    monkeypatch.setattr(research, "_identity_resolvability_hint", lambda **_: {})
    monkeypatch.setattr(
        research_workflow, "_source_patch_for_run", lambda **_: ("0.5.4", "runesofaldur")
    )
    # These tests exercise cleanup policy and transactional filesystem/ledger
    # behavior. Durable receipt migration has its own integration tests.
    monkeypatch.setattr(
        research, "_preserve_legacy_write_receipts",
        lambda **_: {"status": "ok", "writeReceiptRefs": []},
    )
    return root


def _seed_case(runtime, *, status="accepted", legacy=False, character_ref=""):
    run_dir = runtime / "runs" / RUN_ID
    db_path = run_dir / research.QUEUE_DB_FILENAME
    research._init_db(db_path)
    research._insert_case_if_absent(
        db_path,
        {
            "sampleId": f"case:{RUN_ID}", "status": status,
            "sourceType": "poe_ninja_import_code", "sourceHash": SOURCE_HASH,
            "sourceHashRef": f"source-hash:{SOURCE_HASH}", "characterRef": character_ref,
            "league": LEAGUE, "level": 95, "className": "Ranger",
            "ascendancy": "Deadeye", "mainSkill": "Lightning Arrow", "safeError": "",
            "packetId": "packet:retention-test", "packetSafeHash": "d" * 64,
        },
    )
    summary = _partial_summary() if status == "accepted" else {}
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "UPDATE cases SET research_quality_summary=?, accepted_deep_record_count=?, "
            "deferred_candidate_count=?",
            (json.dumps(summary), int(status == "accepted"), summary.get("deferredCandidateCount", 0)),
        )
    metadata = {"intakeLedgerPath": str(research.DEFAULT_INTAKE_LEDGER_PATH)}
    if not legacy:
        metadata["retentionPolicy"] = json.dumps(research_retention.create_policy(now=CREATED))
    research._write_metadata(db_path, metadata)
    (run_dir / "private-quarantine-marker.txt").write_text(RAW_SENTINEL, encoding="utf-8")
    return run_dir, db_path


def _audit(runtime):
    return json.loads((runtime / "run-audits" / f"{RUN_ID}.json").read_text(encoding="utf-8"))


def _reserve(*, character_ref=CHARACTER_REF, sample_id=f"case:{RUN_ID}"):
    research_intake_ledger.record_case(
        research.DEFAULT_INTAKE_LEDGER_PATH, league=LEAGUE,
        character_ref=character_ref, source_hash=SOURCE_HASH, sample_id=sample_id,
    )


def test_expired_partial_cleanup_archives_gaps_without_claiming_completion(runtime):
    run_dir, _ = _seed_case(runtime)

    result = research_workflow.cleanup_run(run_ref=RUN_REF)

    assert result["status"] == "cleaned", result
    assert result["retentionExpired"] is True
    assert not run_dir.exists()
    audit = _audit(runtime)
    assert audit["cleanupReason"] == "retention_expired"
    assert audit["samples"][0]["researchCompletion"] == "needs_followup"
    assert audit["researchCompleteCount"] == 0
    assert audit["researchNeedsFollowupCount"] == 1
    assert audit["abandonedIncomplete"] is False
    assert RAW_SENTINEL not in json.dumps(audit)
    status = research_workflow.run_status(run_ref=RUN_REF)
    assert status["status"] == "archived"
    assert status["rawMaterialAvailable"] is False
    assert status["samples"][0]["researchCompletion"] == "needs_followup"


def test_expired_queued_cleanup_releases_only_the_exact_intake_reservation(runtime):
    run_dir, _ = _seed_case(runtime, status="queued", character_ref=CHARACTER_REF)
    _reserve()
    # Two characters may export identical sources. Cleanup cannot release by
    # source hash alone or erase a different run's queued reservation.
    _reserve(character_ref=OTHER_CHARACTER_REF, sample_id="case:other-run")

    result = research_workflow.cleanup_run(run_ref=RUN_REF)

    assert result["status"] == "cleaned", result
    assert result["retentionExpired"] is True
    assert not run_dir.exists()
    remaining = research_intake_ledger.seen_character_refs(research.DEFAULT_INTAKE_LEDGER_PATH, LEAGUE)
    assert remaining == {OTHER_CHARACTER_REF}
    assert _audit(runtime)["samples"][0]["researchCompletion"] == "unknown"


def test_expiry_preserves_accepted_intake_history(runtime):
    _seed_case(runtime, character_ref=CHARACTER_REF)
    _reserve()
    research_intake_ledger.mark_accepted(
        research.DEFAULT_INTAKE_LEDGER_PATH, league=LEAGUE, character_ref=CHARACTER_REF
    )

    result = research_workflow.cleanup_run(run_ref=RUN_REF)

    assert result["status"] == "cleaned", result
    with closing(sqlite3.connect(research.DEFAULT_INTAKE_LEDGER_PATH)) as con:
        assert con.execute("SELECT status FROM intake_records").fetchone()[0] == "accepted"


def test_partial_run_is_not_discarded_before_the_locked_deadline(runtime, monkeypatch):
    run_dir, _ = _seed_case(runtime)
    monkeypatch.setattr(research, "_now", lambda: EXPIRED - timedelta(seconds=1))

    result = research_workflow.cleanup_run(run_ref=RUN_REF)

    assert result["errorCode"] == "research_followup_required"
    assert run_dir.is_dir()
    assert not (runtime / "run-audits" / f"{RUN_ID}.json").exists()


@pytest.mark.parametrize("abandon", [False, True])
def test_expiry_and_explicit_abandonment_preserve_live_worker_lease(runtime, abandon):
    run_dir, db_path = _seed_case(runtime, status="claimed")
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "UPDATE cases SET lease_token='active-retention-test', lease_expires_at=?",
            ((EXPIRED + timedelta(seconds=1)).isoformat(),),
        )
    before = research._fetch_cases(db_path)

    result = research_workflow.cleanup_run(run_ref=RUN_REF, abandon_incomplete=abandon)

    assert result["errorCode"] == "research_active_claim_lease"
    assert run_dir.is_dir()
    assert research._fetch_cases(db_path) == before
    assert not (runtime / "run-audits" / f"{RUN_ID}.json").exists()


@pytest.mark.parametrize("status,finalization", [("accepting", ""), ("accepted", "ledger_conflict")])
def test_expiry_cannot_bypass_acceptance_recovery(runtime, status, finalization):
    run_dir, db_path = _seed_case(runtime, status=status)
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("UPDATE cases SET finalization_status=?", (finalization,))

    result = research_workflow.cleanup_run(run_ref=RUN_REF, abandon_incomplete=True)

    assert result["errorCode"] == "research_acceptance_recovery_required"
    assert run_dir.is_dir()


def test_expired_claim_does_not_lease_or_rebuild_quarantined_material(runtime, monkeypatch):
    _, db_path = _seed_case(runtime, status="queued")
    rebuilds = []
    monkeypatch.setattr(research, "_rebuild_packet_for_claim", lambda **_: rebuilds.append(True))
    before = research._fetch_cases(db_path)

    result = research_workflow.claim_case(run_ref=RUN_REF)

    assert result["status"] == "retention_expired"
    assert "leaseToken" not in result
    assert research._fetch_cases(db_path) == before
    assert rebuilds == []


@pytest.mark.parametrize("requested_seconds,expected_seconds", [(None, 7200), (10 * 365 * 86400, 86400)])
def test_claim_lease_bound_is_shared_by_queue_packet_and_expiry_grace(
    runtime, monkeypatch, requested_seconds, expected_seconds
):
    _, db_path = _seed_case(runtime, status="queued")
    claimed_at = EXPIRED - timedelta(seconds=1)
    monkeypatch.setattr(research, "_now", lambda: claimed_at)
    rebuilds = []
    monkeypatch.setattr(research, "_rebuild_packet_for_claim", lambda **kw: rebuilds.append(kw))
    options = {} if requested_seconds is None else {"lease_seconds": requested_seconds}

    result = research_workflow.claim_case(run_ref=RUN_REF, **options)

    assert result["status"] == "claimed", result
    lease_deadline = claimed_at + timedelta(seconds=expected_seconds)
    assert datetime.fromisoformat(result["leaseExpiresAt"]) == lease_deadline
    assert len(rebuilds) == 1
    assert rebuilds[0]["lease_seconds"] == expected_seconds
    assert research._fetch_cases(db_path)[0]["leaseExpiresAt"] == result["leaseExpiresAt"]
    monkeypatch.setattr(research, "_now", lambda: lease_deadline - timedelta(seconds=1))
    assert research_workflow.cleanup_run(run_ref=RUN_REF)["errorCode"] == "research_active_claim_lease"
    monkeypatch.setattr(research, "_now", lambda: lease_deadline)
    assert research_workflow.cleanup_run(run_ref=RUN_REF)["status"] == "cleaned"


def test_expired_worker_lease_can_be_cleaned_but_cannot_be_reclaimed(runtime):
    _, db_path = _seed_case(runtime, status="claimed")
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("UPDATE cases SET lease_expires_at=?", (EXPIRED.isoformat(),))

    assert research_workflow.claim_case(run_ref=RUN_REF)["status"] == "retention_expired"
    assert research_workflow.cleanup_run(run_ref=RUN_REF)["status"] == "cleaned"


def test_live_worker_can_read_its_existing_lease_after_deadline(runtime, tmp_path, monkeypatch):
    monkeypatch.setattr(research, "_now", lambda: CREATED)
    source = tmp_path / "synthetic-leased-source.txt"
    source.write_text(_sample_code(), encoding="utf-8")
    queued = research_workflow.start_run(
        source_files=[str(source)], expected_source_count=1, limit=1
    )
    monkeypatch.setattr(research, "_now", lambda: EXPIRED - timedelta(hours=1))
    claimed = research_workflow.claim_case(run_ref=queued["runRef"], lease_seconds=7200)
    assert claimed["status"] == "claimed", claimed
    monkeypatch.setattr(research, "_now", lambda: EXPIRED)

    inspected = research_workflow.inspect_case(
        run_ref=queued["runRef"], lease_token=claimed["leaseToken"]
    )

    assert inspected["status"] == "ok", inspected
    assert research_workflow.claim_case(run_ref=queued["runRef"])["status"] == "retention_expired"
    assert research_workflow.cleanup_run(run_ref=queued["runRef"])["errorCode"] == (
        "research_active_claim_lease"
    )


def test_legacy_partial_does_not_expire_based_on_file_age_or_run_id(runtime):
    run_dir, _ = _seed_case(runtime, legacy=True)

    result = research_workflow.cleanup_run(run_ref=RUN_REF)

    assert result["errorCode"] == "research_followup_required"
    assert run_dir.is_dir()
    status = research_workflow.run_status(run_ref=RUN_REF)
    assert status["retention"]["status"] == "unconfigured"


def test_legacy_queue_can_still_be_claimed_without_inventing_a_retention_policy(runtime, monkeypatch):
    _, db_path = _seed_case(runtime, status="queued", legacy=True)
    monkeypatch.setattr(research, "_rebuild_packet_for_claim", lambda **_: None)

    result = research_workflow.claim_case(run_ref=RUN_REF)

    assert result["status"] == "claimed", result
    assert "retentionPolicy" not in research._read_metadata(db_path)


def test_expired_cleanup_audit_is_persisted_before_any_raw_deletion(runtime, monkeypatch):
    run_dir, _ = _seed_case(runtime)

    def clean_packets(*_args, **_kwargs):
        assert run_dir.is_dir()
        audit = _audit(runtime)
        assert audit["cleanupReason"] == "retention_expired"
        assert audit["samples"][0]["researchCompletion"] == "needs_followup"
        return {"removed": 0}

    monkeypatch.setattr(research.research_packet, "cleanup_packets_by_safe_hashes", clean_packets)
    assert research_workflow.cleanup_run(run_ref=RUN_REF)["status"] == "cleaned"


def test_expired_cleanup_audit_failure_preserves_raw_and_ledger(runtime, monkeypatch):
    run_dir, _ = _seed_case(runtime, status="queued", character_ref=CHARACTER_REF)
    _reserve()
    original_replace = Path.replace

    def fail_audit_write(path, target):
        if path.parent.name == "run-audits":
            raise OSError("injected retention audit persistence failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_audit_write)

    with pytest.raises(OSError, match="retention audit persistence failure"):
        research_workflow.cleanup_run(run_ref=RUN_REF)

    assert run_dir.is_dir()
    assert research_intake_ledger.seen_character_refs(research.DEFAULT_INTAKE_LEDGER_PATH, LEAGUE) == {
        CHARACTER_REF
    }


def test_expired_cleanup_delete_failure_restores_queued_reservation(runtime, monkeypatch):
    run_dir, _ = _seed_case(runtime, status="queued", character_ref=CHARACTER_REF)
    _reserve()
    monkeypatch.setattr(
        research, "_delete_run_directory",
        lambda *_: ("deferred", {"reason": "directory_rename_failed"}),
    )

    result = research_workflow.cleanup_run(run_ref=RUN_REF)

    assert result["status"] == "partial", result
    assert run_dir.is_dir()
    assert research_intake_ledger.seen_character_refs(research.DEFAULT_INTAKE_LEDGER_PATH, LEAGUE) == {
        CHARACTER_REF
    }
    status = research_workflow.run_status(run_ref=RUN_REF)
    assert status["status"] != "archived"
    assert status["samples"][0]["researchCompletion"] == "unknown"


def _sample_code():
    return pob_code.encode_code(
        '<PathOfBuilding2><Build level="95" className="Ranger" ascendClassName="Deadeye" '
        'mainSocketGroup="1"/><Skills><Skill mainActiveSkillCalcs="LightningArrowPlayer">'
        '<Gem nameSpec="Lightning Arrow" skillId="LightningArrowPlayer" enabled="true"/>'
        '</Skill></Skills><Tree activeSpec="1"><Spec treeVersion="0_5" nodes="">'
        '<Sockets/></Spec></Tree><Items activeItemSet="1"><ItemSet id="1"/></Items>'
        '</PathOfBuilding2>'
    )


@pytest.mark.parametrize("retention_days", [None, 1, 30])
def test_typed_start_persists_selected_policy_and_resume_does_not_renew_it(
    runtime, tmp_path, monkeypatch, retention_days
):
    monkeypatch.setattr(research, "_now", lambda: CREATED)
    source = tmp_path / "synthetic-source.txt"
    source.write_text(_sample_code(), encoding="utf-8")
    options = {} if retention_days is None else {"retention_days": retention_days}

    result = research_workflow.start_run(
        source_files=[str(source)], expected_source_count=1, limit=1, **options
    )

    assert result["status"] == "queued", result
    run_dir = runtime / "runs" / result["runId"]
    db_path = run_dir / research.QUEUE_DB_FILENAME
    original = research._read_metadata(db_path)["retentionPolicy"]
    policy = json.loads(original)
    days = retention_days if retention_days is not None else 7
    assert policy == research_retention.create_policy(now=CREATED, retention_days=days)
    monkeypatch.setattr(research, "_now", lambda: CREATED + timedelta(hours=6))

    resumed = research.queue_cases(output_dir=run_dir, resume=True, retention_days=30)

    assert resumed["status"] not in {"resume_failed", "retention_expired"}, resumed
    assert research._read_metadata(db_path)["retentionPolicy"] == original
    claimed = research_workflow.claim_case(run_ref=result["runRef"])
    assert claimed["status"] == "claimed", claimed
    assert research._read_metadata(db_path)["retentionPolicy"] == original
