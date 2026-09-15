from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import timedelta
import json
from pathlib import Path
import sqlite3

import pytest

from scripts import research_mature_builds as runs
from server import paths
from server.knowledge import research_memory, research_workflow as workflow
from tests.test_research_workflow import _sample_code


@pytest.fixture
def run_case(tmp_path, monkeypatch):
    runtime = tmp_path / "user-data" / "research"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: runtime)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(runs, "DEFAULT_INTAKE_LEDGER_PATH", tmp_path / "intake.sqlite")
    monkeypatch.setattr(runs, "_identity_resolvability_hint", lambda **_: {})
    monkeypatch.setattr(runs, "_studied_source_hashes", lambda **_: set())
    monkeypatch.setattr(runs.research_readback, "build_safe_readback", lambda *_, **__: {
        "status": "unavailable", "reason": "synthetic_readback",
    })
    source = tmp_path / "synthetic-source.txt"
    source.write_text(_sample_code(), encoding="utf-8")
    queued = workflow.start_run(source_files=[str(source)], source_game_patch="0.5.4", limit=1)
    directory = runtime / "runs" / queued["runId"]
    return directory, directory / runs.QUEUE_DB_FILENAME, queued["runRef"]


def _row(db):
    with closing(sqlite3.connect(db)) as con:
        con.row_factory = sqlite3.Row
        return dict(con.execute("SELECT * FROM cases").fetchone())


def _discard_material(directory, db, *, raw=True):
    row = _row(db)
    runs.research_packet.cleanup_packets_by_safe_hashes(
        {row["packet_safe_hash"]}, temp_root=directory / runs.DEFAULT_TEMP_DIRNAME,
    )
    if raw:
        (directory / "quarantine" / f"{row['source_hash']}.json").unlink()


def test_claim_losing_to_cleanup_does_not_recreate_run_or_hide_audit(run_case, monkeypatch):
    directory, db, run_ref = run_case
    original_lock = runs.interprocess_file_lock
    interleaved = []

    @contextmanager
    def cleanup_before_claim_lock(path):
        if not interleaved and Path(path) == runs._run_lock_path(db):
            interleaved.append(True)
            assert workflow.cleanup_run(run_ref=run_ref, abandon_incomplete=True)["status"] == "cleaned"
            assert not db.exists()
        with original_lock(path):
            yield

    monkeypatch.setattr(runs, "interprocess_file_lock", cleanup_before_claim_lock)
    result = workflow.claim_case(run_ref=run_ref)
    assert result["errorCode"] == "research_run_not_found"
    assert not db.exists()
    assert not directory.exists()
    audit = runs.read_run_audit(output_dir=directory.parent.parent, run_id=directory.name)
    assert audit["status"] == "archived"
    assert audit["runtimeDirectoryPreserved"] is False
    assert workflow.run_status(run_ref=run_ref)["cleanupReason"] == "explicit_abandonment"


@pytest.mark.parametrize("entry", [runs.claim_case, runs._claim_case_locked])
def test_claim_requires_existing_queue(tmp_path, entry):
    directory = tmp_path / "runs" / "20260906-010203-abcd"
    assert entry(output_dir=directory)["errorCode"] == "research_run_not_found"
    assert not directory.exists()


@pytest.mark.parametrize("remove_raw", [False, True])
@pytest.mark.parametrize("state", ["accepting", "claimed", "accepted"])
def test_resume_never_changes_protected_case_binding(run_case, remove_raw, state):
    directory, db, run_ref = run_case
    workflow.claim_case(run_ref=run_ref)
    if state != "claimed":
        with closing(sqlite3.connect(db)) as con, con:
            con.execute(
                "UPDATE cases SET status=?, accept_attempt_key='unchanged-attempt', "
                "finalization_status='pending', accept_origin_state='claimed'", (state,),
            )
    before = _row(db)
    _discard_material(directory, db, raw=remove_raw)
    result = runs.queue_cases(output_dir=directory, resume=True)
    assert result["status"] == "resumed_partial"
    assert _row(db) == before
    assert result["resumeSummary"]["packetRebuiltCount"] == 0
    assert result["resumeSummary"]["removedCaseCount"] == 0
    if state == "claimed":
        assert result["resumeSummary"]["protectedLeaseCount"] == 1
    else:
        assert result["recoveryRequired"] is True
        assert result["resumeSummary"]["acceptanceRecoveryRequiredCount"] == 1


def test_resume_missing_material_keeps_diagnostic_row_and_can_recover(run_case):
    directory, db, _ = run_case
    before = _row(db)
    quarantine = directory / "quarantine" / f"{before['source_hash']}.json"
    backup = quarantine.read_bytes()
    _discard_material(directory, db)
    result = runs.queue_cases(output_dir=directory, resume=True)
    after = _row(db)
    assert result["status"] == "resumed_partial"
    assert result["resumeSummary"]["unrecoverableCaseCount"] == 1
    assert after["safe_error"] == "resume_source_material_unavailable"
    for key in ("source_hash", "source_hash_ref", "packet_safe_hash", "status", "sample_id"):
        assert after[key] == before[key]
    quarantine.write_bytes(backup)
    recovered = runs.queue_cases(output_dir=directory, resume=True)
    assert recovered["status"] == "resumed"
    assert recovered["resumeSummary"]["packetRebuiltCount"] == 1
    assert _row(db)["safe_error"] == ""


@pytest.mark.parametrize("policy_case", ["active", "expired", "malformed"])
def test_resume_respects_locked_retention_and_never_renews_deadline(run_case, monkeypatch, policy_case):
    directory, db, _ = run_case
    now = runs._now()
    if policy_case == "malformed":
        policy = {"policyVersion": 1}
    else:
        created = now - timedelta(days=8) if policy_case == "expired" else now - timedelta(hours=23)
        policy = runs.research_retention.create_policy(now=created, retention_days=1)
    serialized = json.dumps(policy)
    runs._write_metadata(db, {"retentionPolicy": serialized})
    _discard_material(directory, db, raw=False)
    before = _row(db)
    original_prepare = runs._prepare_packet
    ttls = []

    def prepare(*args, **kwargs):
        ttls.append(kwargs["ttl_seconds"])
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(runs, "_prepare_packet", prepare)
    result = runs.queue_cases(output_dir=directory, resume=True)
    assert runs._read_metadata(db)["retentionPolicy"] == serialized
    if policy_case == "active":
        assert result["status"] == "resumed"
        assert 0 < ttls[0] <= 3600
    else:
        assert result["status"] == "resume_blocked"
        assert _row(db) == before
        assert ttls == []


def test_resume_uses_cleanup_memory_then_run_lock_order(run_case, monkeypatch):
    directory, db, _ = run_case
    original_lock = runs.interprocess_file_lock
    acquired = []

    @contextmanager
    def record_lock(path):
        acquired.append(Path(path))
        with original_lock(path):
            yield

    monkeypatch.setattr(runs, "interprocess_file_lock", record_lock)
    assert runs.queue_cases(output_dir=directory, resume=True)["status"] == "resumed"
    assert acquired == [runs._accept_lock_path(paths.mature_learning_path()), runs._run_lock_path(db)]


def test_resume_losing_to_cleanup_keeps_safe_archive_visible(run_case, monkeypatch):
    directory, db, run_ref = run_case
    original_lock = runs.interprocess_file_lock
    interleaved = []

    @contextmanager
    def cleanup_before_resume_lock(path):
        if not interleaved and Path(path) == runs._accept_lock_path(paths.mature_learning_path()):
            interleaved.append(True)
            assert workflow.cleanup_run(run_ref=run_ref, abandon_incomplete=True)["status"] == "cleaned"
        with original_lock(path):
            yield

    monkeypatch.setattr(runs, "interprocess_file_lock", cleanup_before_resume_lock)
    result = runs.queue_cases(output_dir=directory, resume=True)
    assert result["errorCode"] == "research_run_not_found"
    assert not directory.exists()
    assert not db.exists()
    assert workflow.run_status(run_ref=run_ref)["cleanupReason"] == "explicit_abandonment"


def test_resume_does_not_sweep_accepting_packet_while_checking_another_case(run_case):
    directory, db, run_ref = run_case
    workflow.claim_case(run_ref=run_ref)
    with closing(sqlite3.connect(db)) as con, con:
        con.execute("UPDATE cases SET status='accepting', accept_attempt_key='unchanged-attempt'")
    second = runs._fetch_cases(db)[0]
    second.update({
        "sampleId": "case:second", "status": "queued", "sourceHash": "b" * 64,
        "sourceHashRef": "source-hash:" + "b" * 16, "packetId": "second-packet",
        "packetSafeHash": "second-packet-hash",
    })
    runs._insert_case_if_absent(db, second)
    packet_path = next((directory / runs.DEFAULT_TEMP_DIRNAME).glob("*/packet.json"))
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["expiresAt"] = (runs._now() - timedelta(hours=1)).isoformat()
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    before = packet_path.read_bytes()
    result = runs.queue_cases(output_dir=directory, resume=True)
    assert result["resumeSummary"]["acceptanceRecoveryRequiredCount"] == 1
    assert result["resumeSummary"]["unrecoverableCaseCount"] == 1
    assert packet_path.read_bytes() == before


def test_resume_without_material_preserves_exact_committed_accept_recovery(run_case):
    directory, db, run_ref = run_case
    claimed = workflow.claim_case(run_ref=run_ref)
    review = workflow.initialize_review(run_ref=run_ref, lease_token=claimed["leaseToken"])["review"]
    review["deepResearchRecords"] = [{
        "sampleId": claimed["sampleId"], "caseRef": review["artifactIdentity"]["caseRef"],
        "safeEvidenceRef": review["artifactIdentity"]["safeEvidenceRef"],
    }]
    saved = runs.save_review_payload(output_dir=directory, lease_token=claimed["leaseToken"], review_payload=review)
    review_file = directory / saved["reviewFile"]
    row = _row(db)
    canonical = runs._assert_review_file_for_lease(
        review_file=review_file, output_root=directory, sample_id=row["sample_id"],
        lease_token=claimed["leaseToken"], source_hash_ref=row["source_hash_ref"],
        packet_safe_hash=row["packet_safe_hash"], version_context=runs._queue_version_context(db),
    )
    canonical_hash = runs.research_runtime.stable_hash(canonical)
    attempt = runs.research_runtime.accept_attempt_key(
        run_id=directory.name, sample_id=row["sample_id"], packet_safe_hash=row["packet_safe_hash"],
        canonical_review_hash=canonical_hash, contract_version=canonical["reviewContractVersion"],
        expected_origin_state="claimed",
    )
    unit = research_memory.ResearchMemoryService(db_path=paths.mature_learning_path()).accept_research_unit(
        run_ref=run_ref, sample_id=row["sample_id"], accept_attempt_key=attempt,
        packet_safe_hash=row["packet_safe_hash"], canonical_review_hash=canonical_hash,
        contract_version=canonical["reviewContractVersion"], expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": []},
        edge_payload={"schema_version": 4},
    )
    with closing(sqlite3.connect(db)) as con, con:
        con.execute("UPDATE cases SET status='accepting', accept_origin_state='claimed', accept_attempt_key=?", (attempt,))
    _discard_material(directory, db)
    before = _row(db)
    assert runs.queue_cases(output_dir=directory, resume=True)["recoveryRequired"] is True
    assert _row(db) == before
    recovered = runs.accept_case(
        output_dir=directory, lease_token=claimed["leaseToken"], review_file=review_file,
        memory_db_path=paths.mature_learning_path(), intake_ledger_path=runs.DEFAULT_INTAKE_LEDGER_PATH,
    )
    assert recovered["status"] == "accepted"
    assert recovered["idempotentRecovery"] is True
    assert recovered["writeReceiptRef"] == unit["writeReceiptRef"]
    assert _row(db)["packet_safe_hash"] == before["packet_safe_hash"]
