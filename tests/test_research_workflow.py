from __future__ import annotations

from pathlib import Path
import sqlite3

from scripts import research_mature_builds
from server import paths
from server.compute import pob_code
from server.knowledge import research_workflow


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


def test_typed_worker_keeps_review_in_memory_and_binds_accept_to_validation_hash(
    tmp_path, monkeypatch
):
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
    rejected = research_workflow.accept_review(
        run_ref=queued["runRef"],
        lease_token=claimed["leaseToken"],
        expected_review_hash="review-sha256:" + "0" * 64,
    )
    accepted = research_workflow.accept_review(
        run_ref=queued["runRef"],
        lease_token=claimed["leaseToken"],
        expected_review_hash=validated["reviewHash"],
    )

    assert validated["status"] == "validation_passed"
    assert rejected["errorCode"] == "review_changed_after_validation"
    assert accepted["status"] == "accepted"
    assert len(calls) == 2
    assert calls[0]["validation_only"] is True
    assert calls[0]["memory_db_path"] == tmp_path / "memory.sqlite"
    assert calls[1]["memory_db_path"] == tmp_path / "memory.sqlite"


def test_legacy_run_adoption_waits_for_active_lease_then_copies_without_deleting_source(
    tmp_path, monkeypatch
):
    runtime = _configure_user_data(monkeypatch, tmp_path)
    source_file = tmp_path / "sample.txt"
    source_file.write_text(_sample_code(), encoding="utf-8")
    legacy_base = tmp_path / "legacy" / ".poe-bd-research"
    run_id, legacy_run = research_mature_builds._allocate_run_output_dir(legacy_base)
    research_mature_builds.queue_cases(
        source_files=[source_file],
        expected_source_count=1,
        limit=1,
        output_dir=legacy_run,
    )
    queue_db = legacy_run / research_mature_builds.QUEUE_DB_FILENAME
    with sqlite3.connect(queue_db) as con:
        sample_id = str(con.execute("SELECT sample_id FROM cases LIMIT 1").fetchone()[0])
        con.execute(
            "UPDATE cases SET status = 'claimed', lease_token = 'fixture', "
            "lease_owner = 'fixture', lease_expires_at = ? WHERE sample_id = ?",
            ("2999-01-01T00:00:00+00:00", sample_id),
        )
        con.commit()

    blocked = research_workflow.adopt_legacy_run(legacy_run_dir=str(legacy_run))
    assert blocked["status"] == "legacy_run_active"
    assert blocked["activeLeaseCount"] == 1

    with sqlite3.connect(queue_db) as con:
        con.execute(
            "UPDATE cases SET lease_expires_at = ? WHERE sample_id = ?",
            ("2000-01-01T00:00:00+00:00", sample_id),
        )
        con.commit()

    adopted = research_workflow.adopt_legacy_run(legacy_run_dir=str(legacy_run))
    adopted_dir = runtime / "runs" / run_id

    assert adopted["status"] == "adopted"
    assert adopted["runRef"] == f"research-run:{run_id}"
    assert adopted["sourcePreserved"] is True
    assert legacy_run.is_dir()
    assert (adopted_dir / research_mature_builds.QUEUE_DB_FILENAME).is_file()
    assert research_workflow.run_status(run_ref=adopted["runRef"])["claimedCount"] == 1
    adopted_quarantine = sorted((adopted_dir / "quarantine").glob("*.json"))
    legacy_quarantine = sorted((legacy_run / "quarantine").glob("*.json"))
    assert len(adopted_quarantine) == len(legacy_quarantine) == 1
    assert adopted_quarantine[0].read_bytes() == legacy_quarantine[0].read_bytes()
