from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading
import time

import pytest

from scripts import research_mature_builds
from server import paths
from server.compute import pob_code
from server.knowledge import research_workflow
from server.knowledge import research_memory


def _sample_code() -> str:
    return pob_code.encode_code(
        """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="98" className="Ranger" ascendClassName="Deadeye" mainSocketGroup="1" />
  <Skills><Skill mainActiveSkillCalcs="LightningArrowPlayer"><Gem nameSpec="Lightning Arrow" skillId="LightningArrowPlayer" enabled="true" /></Skill></Skills>
  <Tree activeSpec="1"><Spec treeVersion="0_5" nodes=""><Sockets /></Spec></Tree>
  <Items activeItemSet="1"><ItemSet id="1" /></Items>
</PathOfBuilding2>
"""
    )


def _configure_user_data(monkeypatch, tmp_path: Path) -> Path:
    runtime = tmp_path / "user-data" / "research"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: runtime)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(research_mature_builds, "_identity_resolvability_hint", lambda **_: {})
    return runtime


def test_typed_research_run_never_uses_checkout_or_plugin_cache(tmp_path, monkeypatch):
    runtime = _configure_user_data(monkeypatch, tmp_path)
    source = tmp_path / "sample.txt"
    source.write_text(_sample_code(), encoding="utf-8")
    foreign_project = tmp_path / "unrelated-project"
    foreign_project.mkdir()
    monkeypatch.chdir(foreign_project)

    queued = research_workflow.start_run(
        source_files=[str(source)],
        expected_source_count=1,
        limit=1,
        level_min=98,
        level_max=98,
    )

    assert queued["status"] == "queued"
    assert queued["runRef"].startswith("research-run:")
    assert "runDir" not in queued
    run_id = queued["runId"]
    run_dir = runtime / "runs" / run_id
    assert (run_dir / research_mature_builds.QUEUE_DB_FILENAME).is_file()
    assert paths.BUNDLE_ROOT.resolve() not in run_dir.resolve().parents
    status = research_workflow.run_status(run_ref=queued["runRef"])
    assert status["queuedCount"] == 1
    assert status["runRef"] == queued["runRef"]
    assert list(foreign_project.iterdir()) == []
    cleanup_calls: list[dict] = []

    def fake_cleanup_completed_run(**kwargs):
        cleanup_calls.append(kwargs)
        return {
            "status": "cleaned",
            "taskKind": "research",
            "taskId": run_id,
            "memoriesPreserved": True,
            "ledgerPath": "C:/private/intake.sqlite",
            "detail": {
                "lockedFiles": ["C:/private/queue.sqlite"],
                "hint": "staging directory is preserved at C:/private/staging",
            },
        }

    monkeypatch.setattr(research_mature_builds, "cleanup_completed_run", fake_cleanup_completed_run)
    cleaned = research_workflow.cleanup_run(run_ref=queued["runRef"], abandon_incomplete=True)
    assert cleaned["status"] == "cleaned"
    assert cleaned["runRef"] == queued["runRef"]
    assert "runDir" not in cleaned
    assert "ledgerPath" not in cleaned
    assert "lockedFiles" not in cleaned["detail"]
    assert "C:/private" not in cleaned["detail"]["hint"]
    assert cleanup_calls == [
        {
            "run_id": run_id,
            "output_dir": runtime,
            "allow_rejected": False,
            "abandon_incomplete": True,
        }
    ]


def test_typed_research_run_targets_valid_supplement_sample_ids_before_allocating(
    tmp_path, monkeypatch
):
    runtime = _configure_user_data(monkeypatch, tmp_path)
    source = tmp_path / "sample.txt"
    source.write_text(_sample_code(), encoding="utf-8")
    prior = research_workflow.start_run(
        source_files=[str(source)], expected_source_count=1, limit=1
    )
    prior_dir = runtime / "runs" / prior["runId"]
    queue_db = prior_dir / research_mature_builds.QUEUE_DB_FILENAME
    with sqlite3.connect(queue_db) as con:
        sample_id = str(con.execute("SELECT sample_id FROM cases").fetchone()[0])

    before = sorted((runtime / "runs").iterdir())
    missing_ref = research_workflow.start_run(supplement_sample_ids=[sample_id])
    assert missing_ref["errorCode"] == "supplement_sample_ids_require_re_research_run_ref"
    assert sorted((runtime / "runs").iterdir()) == before

    not_accepted = research_workflow.start_run(
        re_research_run_ref=prior["runRef"],
        supplement_sample_ids=[sample_id],
    )
    assert not_accepted["status"] == "supplement_selection_invalid"
    assert not_accepted["notAcceptedSupplementSampleIds"] == [sample_id]
    assert sorted((runtime / "runs").iterdir()) == before

    unknown = research_workflow.start_run(
        re_research_run_ref=prior["runRef"],
        supplement_sample_ids=["case:missing"],
    )
    assert unknown["status"] == "supplement_selection_invalid"
    assert unknown["missingSupplementSampleIds"] == ["case:missing"]
    assert sorted((runtime / "runs").iterdir()) == before

    with sqlite3.connect(queue_db) as con:
        con.execute("UPDATE cases SET status = 'accepted' WHERE sample_id = ?", (sample_id,))
        con.commit()
    source_conflict = research_workflow.start_run(
        re_research_run_ref=prior["runRef"],
        supplement_sample_ids=[sample_id],
        source_files=[str(source)],
    )
    assert source_conflict["errorCode"] == "re_research_source_input_conflict"
    assert sorted((runtime / "runs").iterdir()) == before
    count_conflict = research_workflow.start_run(
        re_research_run_ref=prior["runRef"],
        supplement_sample_ids=[sample_id],
        expected_source_count=1,
    )
    assert count_conflict["errorCode"] == "re_research_expected_source_count_conflict"
    assert sorted((runtime / "runs").iterdir()) == before

    selected = research_workflow.start_run(
        re_research_run_ref=prior["runRef"],
        supplement_sample_ids=[sample_id, sample_id],
        supplement_focus="只更正目标机制",
    )
    assert selected["status"] == "queued"
    assert selected["requestedSupplementSampleCount"] == 1
    assert selected["selectedSupplementSampleCount"] == 1
    assert selected["requestedSampleCount"] == 1
    assert selected["selectedSupplementSampleIds"] == [sample_id]
    assert selected["missingSupplementSampleCount"] == 0
    assert selected["notAcceptedSupplementSampleCount"] == 0
    assert selected["unrecoverableSupplementSampleCount"] == 0
    assert [sample["sampleId"] for sample in selected["samples"]] == [sample_id]
    assert "runDir" not in selected
    selected_status = research_workflow.run_status(run_ref=selected["runRef"])
    assert selected_status["requestedSampleCount"] == 1
    assert selected_status["selectedSupplementSampleIds"] == [sample_id]

    after_selected = sorted((runtime / "runs").iterdir())
    empty = research_workflow.start_run(
        re_research_run_ref=prior["runRef"], supplement_sample_ids=[]
    )
    assert empty["errorCode"] == "invalid_supplement_sample_ids"
    assert sorted((runtime / "runs").iterdir()) == after_selected

    original_queue_cases = research_mature_builds.queue_cases

    def fail_after_allocation(**_kwargs):
        raise RuntimeError("synthetic queue failure")

    monkeypatch.setattr(research_mature_builds, "queue_cases", fail_after_allocation)
    with pytest.raises(RuntimeError, match="synthetic queue failure"):
        research_workflow.start_run(
            re_research_run_ref=prior["runRef"],
            supplement_sample_ids=[sample_id],
        )
    assert sorted((runtime / "runs").iterdir()) == after_selected
    monkeypatch.setattr(research_mature_builds, "queue_cases", original_queue_cases)

    quarantine_file = next((prior_dir / "quarantine").glob("*.json"))
    quarantine_file.unlink()
    unrecoverable = research_workflow.start_run(
        re_research_run_ref=prior["runRef"], supplement_sample_ids=[sample_id]
    )
    assert unrecoverable["status"] == "supplement_selection_invalid"
    assert unrecoverable["unrecoverableSupplementSampleIds"] == [sample_id]
    assert sorted((runtime / "runs").iterdir()) == after_selected


def test_legacy_cli_default_remains_repo_local():
    assert research_mature_builds.DEFAULT_OUTPUT_DIR == paths.BUNDLE_ROOT / ".poe-bd-research"


def test_typed_worker_keeps_review_in_memory_for_validate_and_accept(tmp_path, monkeypatch):
    _configure_user_data(monkeypatch, tmp_path)
    source = tmp_path / "sample.txt"
    source.write_text(_sample_code(), encoding="utf-8")
    queued = research_workflow.start_run(
        source_files=[str(source)], expected_source_count=1, limit=1
    )
    claimed = research_workflow.claim_case(run_ref=queued["runRef"])

    assert claimed["status"] == "claimed"
    assert "reviewFile" not in claimed
    assert "workerPrompt" not in claimed
    initialized = research_workflow.initialize_review(
        run_ref=queued["runRef"], lease_token=claimed["leaseToken"]
    )
    review = initialized["review"]
    review["deepResearchRecords"] = [
        {
            "sampleId": claimed["sampleId"],
            "caseRef": initialized["review"]["artifactIdentity"]["caseRef"],
            "safeEvidenceRef": initialized["review"]["artifactIdentity"]["safeEvidenceRef"],
        }
    ]
    calls: list[dict] = []

    def fake_accept_case(**kwargs):
        calls.append(kwargs)
        if kwargs.get("validation_only"):
            return {
                "status": "validation_passed",
                "deferredCandidateCount": 0,
                "unresolvedDeepRecordComponentCount": 0,
                "caseCoverageGapCount": 0,
            }
        return {
            "status": "accepted",
            "deferredCandidateCount": 0,
            "unresolvedDeepRecordComponentCount": 0,
            "caseCoverageGapCount": 0,
        }

    monkeypatch.setattr(research_mature_builds, "accept_case", fake_accept_case)
    validated = research_workflow.validate_review(
        run_ref=queued["runRef"],
        lease_token=claimed["leaseToken"],
        review=review,
    )
    accepted = research_workflow.accept_review(
        run_ref=queued["runRef"],
        lease_token=claimed["leaseToken"],
        review=review,
    )

    assert validated["status"] == "validation_passed"
    assert accepted["status"] == "accepted"
    assert len(calls) == 2
    assert calls[0]["validation_only"] is True
    assert calls[0]["memory_db_path"] == tmp_path / "memory.sqlite"
    assert calls[1]["memory_db_path"] == tmp_path / "memory.sqlite"
    assert "reviewHash" not in validated
    assert "reviewHash" not in accepted


def test_typed_accept_replay_reaches_recovery_before_claimed_only_guards(
    tmp_path, monkeypatch
):
    runtime = _configure_user_data(monkeypatch, tmp_path)
    source = tmp_path / "sample.txt"
    source.write_text(_sample_code(), encoding="utf-8")
    queued = research_workflow.start_run(
        source_files=[str(source)], expected_source_count=1, limit=1
    )
    run_dir = runtime / "runs" / queued["runId"]
    queue_db = run_dir / research_mature_builds.QUEUE_DB_FILENAME
    claimed = research_workflow.claim_case(run_ref=queued["runRef"])
    review = research_workflow.initialize_review(
        run_ref=queued["runRef"], lease_token=claimed["leaseToken"]
    )["review"]
    review["deepResearchRecords"] = [
        {
            "sampleId": claimed["sampleId"],
            "caseRef": review["artifactIdentity"]["caseRef"],
            "safeEvidenceRef": review["artifactIdentity"]["safeEvidenceRef"],
        }
    ]
    saved = research_mature_builds.save_review_payload(
        output_dir=run_dir,
        lease_token=claimed["leaseToken"],
        review_payload=review,
    )
    review_path = run_dir / saved["reviewFile"]
    with sqlite3.connect(queue_db) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM cases WHERE sample_id = ?", (claimed["sampleId"],)
        ).fetchone()
        canonical = research_mature_builds._canonical_review_artifact_identity(
            review_file=review_path,
            sample_id=claimed["sampleId"],
            source_hash_ref=str(row["source_hash_ref"]),
            packet_safe_hash=str(row["packet_safe_hash"]),
            version_context=research_mature_builds._queue_version_context(queue_db),
        )
        research_mature_builds._bind_authoritative_review_scope(
            canonical,
            row=row,
            mismatch_error="fixture scope mismatch",
        )
        attempt_key = research_mature_builds.research_runtime.accept_attempt_key(
            run_id=queued["runId"],
            sample_id=claimed["sampleId"],
            packet_safe_hash=str(row["packet_safe_hash"]),
            canonical_review_hash=research_mature_builds.research_runtime.stable_hash(canonical),
            contract_version=str(canonical["reviewContractVersion"]),
            expected_origin_state="claimed",
        )
        con.execute(
            "UPDATE cases SET status='accepting', accept_attempt_key=?, "
            "accept_origin_state='claimed' WHERE sample_id=?",
            (attempt_key, claimed["sampleId"]),
        )
        con.commit()

    calls: list[dict] = []

    def fake_recovery(**kwargs):
        calls.append(kwargs)
        return {"status": "accepted", "idempotentRecovery": True}

    monkeypatch.setattr(research_mature_builds, "accept_case", fake_recovery)
    replay = research_workflow.accept_review(
        run_ref=queued["runRef"],
        lease_token=claimed["leaseToken"],
        review=review,
    )
    assert replay["status"] == "accepted"
    assert calls[0]["review_file"] == review_path

    changed = deepcopy(review)
    changed["pobReadbackAudit"] = [{"disposition": "unavailable"}]
    with pytest.raises(ValueError, match="review hash"):
        research_workflow.accept_review(
            run_ref=queued["runRef"],
            lease_token=claimed["leaseToken"],
            review=changed,
        )
    assert len(calls) == 1


@pytest.mark.parametrize("first_attempt_commits", [True, False])
def test_public_accept_replay_waits_for_inflight_memory_commit_or_rollback(
    tmp_path, monkeypatch, first_attempt_commits
):
    runtime = _configure_user_data(monkeypatch, tmp_path)
    source = tmp_path / "sample.txt"
    source.write_text(_sample_code(), encoding="utf-8")
    queued = research_workflow.start_run(
        source_files=[str(source)], expected_source_count=1, limit=1
    )
    run_dir = runtime / "runs" / queued["runId"]
    queue_db = run_dir / research_mature_builds.QUEUE_DB_FILENAME
    memory_db = tmp_path / "memory.sqlite"
    claimed = research_workflow.claim_case(run_ref=queued["runRef"])
    review = research_workflow.initialize_review(
        run_ref=queued["runRef"], lease_token=claimed["leaseToken"]
    )["review"]
    review["deepResearchRecords"] = [
        {
            "sampleId": claimed["sampleId"],
            "caseRef": review["artifactIdentity"]["caseRef"],
            "safeEvidenceRef": review["artifactIdentity"]["safeEvidenceRef"],
        }
    ]

    entered = threading.Event()
    release = threading.Event()
    call_count = 0

    def committed_report(acceptance_context: dict) -> dict:
        unit = research_memory.ResearchMemoryService(
            db_path=memory_db, initialize_store=False
        ).accept_research_unit(
            run_ref=str(acceptance_context["runRef"]),
            sample_id=str(acceptance_context["sampleId"]),
            accept_attempt_key=str(acceptance_context["acceptAttemptKey"]),
            packet_safe_hash=str(acceptance_context["packetSafeHash"]),
            canonical_review_hash=str(acceptance_context["canonicalReviewHash"]),
            contract_version=str(acceptance_context["contractVersion"]),
            expected_origin_state=str(acceptance_context["expectedOriginState"]),
            pattern_payload={"schema_version": 4},
            deep_payload={"schema_version": 6, "deep_research_records": []},
            edge_payload={"schema_version": 4},
        )
        return {
            "status": "accepted",
            "writeReceiptRef": unit["writeReceiptRef"],
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 0,
            "acceptedSemanticEdgeCount": 0,
            "deferredCandidateCount": 0,
        }

    def controlled_acceptance(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            entered.set()
            assert release.wait(timeout=10)
            if not first_attempt_commits:
                raise RuntimeError("injected rollback before Memory commit")
        return committed_report(kwargs["acceptance_context"])

    monkeypatch.setattr(
        research_mature_builds.acceptance,
        "accept_deep_review_candidates",
        controlled_acceptance,
    )

    def invoke_accept():
        return research_workflow.accept_review(
            run_ref=queued["runRef"],
            lease_token=claimed["leaseToken"],
            review=review,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(invoke_accept)
        assert entered.wait(timeout=10)
        second = executor.submit(invoke_accept)
        time.sleep(0.1)
        assert not second.done()
        with sqlite3.connect(queue_db) as con:
            assert con.execute(
                "SELECT status FROM cases WHERE sample_id = ?", (claimed["sampleId"],)
            ).fetchone()[0] == "accepting"
        release.set()
        if first_attempt_commits:
            assert first.result(timeout=15)["status"] == "accepted"
            assert second.result(timeout=15)["status"] == "accepted"
            assert call_count == 1
        else:
            with pytest.raises(RuntimeError, match="injected rollback"):
                first.result(timeout=15)
            assert second.result(timeout=15)["status"] == "accepted"
            assert call_count == 2

    con = research_memory.mature_learning.connect(memory_db)
    try:
        assert con.execute("SELECT count(*) FROM research_record_write_receipts").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM deep_research_record_evidence").fetchone()[0] == 0
        assert research_mature_builds.research_runtime.get_memory_revision(con) == 0
    finally:
        con.close()
    with sqlite3.connect(queue_db) as con:
        assert con.execute(
            "SELECT status FROM cases WHERE sample_id = ?", (claimed["sampleId"],)
        ).fetchone()[0] == "accepted"


def test_typed_product_rejects_relative_local_source_paths(tmp_path, monkeypatch):
    _configure_user_data(monkeypatch, tmp_path)

    try:
        research_workflow.start_run(source_files=["sample.txt"], expected_source_count=1)
    except ValueError as exc:
        assert str(exc) == "source_files entries must be absolute paths"
    else:
        raise AssertionError("relative product source path should be rejected")


def test_typed_product_rejects_relative_runtime_root(monkeypatch):
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: Path("relative-research-root"))

    try:
        research_workflow.start_run(dry_run=True)
    except ValueError as exc:
        assert str(exc) == "Research user-data runtime root must be an absolute path"
    else:
        raise AssertionError("relative product runtime root should be rejected")


def test_typed_claim_preserves_safe_supplement_context(tmp_path, monkeypatch):
    _configure_user_data(monkeypatch, tmp_path)
    source = tmp_path / "sample.txt"
    source.write_text(_sample_code(), encoding="utf-8")
    queued = research_workflow.start_run(
        source_files=[str(source)], expected_source_count=1, limit=1
    )
    monkeypatch.setattr(
        research_mature_builds,
        "claim_case",
        lambda **_kwargs: {
            "status": "claimed",
            "sampleId": "case:fixture",
            "leaseToken": "lease-fixture",
            "supplement": True,
            "supplementContext": "补齐资源闭环",
            "reviewFile": "reviews/private.json",
            "workerPrompt": "private CLI prompt",
        },
    )

    result = research_workflow.claim_case(run_ref=queued["runRef"])

    assert result["supplement"] is True
    assert result["supplementContext"] == "补齐资源闭环"
    assert "reviewFile" not in result
    assert "workerPrompt" not in result


def test_typed_retry_resolves_review_inside_run_not_current_directory(tmp_path, monkeypatch):
    runtime = _configure_user_data(monkeypatch, tmp_path)
    source = tmp_path / "sample.txt"
    source.write_text(_sample_code(), encoding="utf-8")
    queued = research_workflow.start_run(
        source_files=[str(source)], expected_source_count=1, limit=1
    )
    run_dir = runtime / "runs" / queued["runId"]
    claimed = research_workflow.claim_case(run_ref=queued["runRef"])
    initialized = research_workflow.initialize_review(
        run_ref=queued["runRef"], lease_token=claimed["leaseToken"]
    )
    review = initialized["review"]
    review["deepResearchRecords"] = [
        {
            "sampleId": claimed["sampleId"],
            "caseRef": review["artifactIdentity"]["caseRef"],
            "safeEvidenceRef": review["artifactIdentity"]["safeEvidenceRef"],
        }
    ]
    queue_db = run_dir / research_mature_builds.QUEUE_DB_FILENAME
    with sqlite3.connect(queue_db) as con:
        con.execute(
            "UPDATE cases SET status = 'acceptance_rejected', lease_token = NULL, "
            "lease_owner = NULL, lease_expires_at = NULL WHERE sample_id = ?",
            (claimed["sampleId"],),
        )
        con.commit()
    authoritative_review = next((run_dir / "reviews").glob("*-safe-review.json"))
    relative_review = authoritative_review.relative_to(run_dir)
    foreign_project = tmp_path / "foreign-project"
    conflicting_review = foreign_project / relative_review
    conflicting_review.parent.mkdir(parents=True)
    conflicting_review.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(foreign_project)
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 0,
            "acceptedSemanticEdgeCount": 0,
            "deferredCandidateCount": 0,
        }

    monkeypatch.setattr(
        research_mature_builds.acceptance,
        "accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    result = research_workflow.retry_review(
        run_ref=queued["runRef"],
        sample_id=claimed["sampleId"],
        review=review,
    )

    assert result["status"] == "accepted"
    assert calls[0]["review_file"] == authoritative_review
    assert calls[0]["review_payload"]["safeArtifactOnly"] is True
    assert calls[0]["review_payload"]["artifactIdentity"] == review["artifactIdentity"]
    with sqlite3.connect(queue_db) as con:
        assert (
            con.execute(
                "SELECT status FROM cases WHERE sample_id = ?", (claimed["sampleId"],)
            ).fetchone()[0]
            == "accepted"
        )
