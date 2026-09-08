from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest

from scripts import research_mature_builds
from server import paths
from server.knowledge import research_workflow


RUN_ID = "20260906-010203-abcd"
OTHER_RUN_ID = "20260906-040506-ef01"
MISSING_RUN_ID = "20260906-070809-fedc"


def _clean_summary():
    return {
        "acceptanceMode": "clean",
        "deferredCandidateCount": 0,
        "unresolvedDeepRecordMentionCount": 0,
        "caseCoverageGapCount": 0,
    }


def _partial_summary():
    return {
        **_clean_summary(),
        "acceptanceMode": "partial_with_deferred",
        "deferredCandidateCount": 1,
        "deferredReasonCounts": {"mechanic_evidence_missing": 1},
        "caseCoverageGaps": ["resourceDefense"],
    }


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    runtime_root = tmp_path / "user-data" / "research"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: runtime_root)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(research_mature_builds, "DEFAULT_OUTPUT_DIR", runtime_root)
    # Receipt migration is tested separately. These tests isolate cleanup decisions
    # and filesystem transitions without touching the user's durable Memory store.
    monkeypatch.setattr(
        research_mature_builds,
        "_preserve_legacy_write_receipts",
        lambda **_kwargs: {"status": "ok", "writeReceiptRefs": []},
    )
    return runtime_root


def _queue_case(runtime_root, summary, *, run_id=RUN_ID, status="accepted", supplement=False):
    run_dir = runtime_root / "runs" / run_id
    db_path = run_dir / research_mature_builds.QUEUE_DB_FILENAME
    sample_id = f"case:{run_id}"
    research_mature_builds._init_db(db_path)
    research_mature_builds._insert_case_if_absent(
        db_path,
        {
            "sampleId": sample_id,
            "status": status,
            "sourceType": "poe_ninja_import_code",
            "sourceHash": f"source-{run_id}",
            "sourceHashRef": f"source-hash:{run_id}",
            "characterRef": "",
            "league": "test-league",
            "level": 95,
            "className": "Ranger",
            "ascendancy": "Deadeye",
            "mainSkill": "Lightning Arrow",
            "safeError": "",
            "packetId": f"packet:{run_id}",
            "packetSafeHash": f"packet-hash:{run_id}",
            "supplement": supplement,
        },
    )
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "UPDATE cases SET research_quality_summary=?, accepted_deep_record_count=1, "
            "deferred_candidate_count=? WHERE sample_id=?",
            (json.dumps(summary), summary.get("deferredCandidateCount", 0), sample_id),
        )
    return run_dir, db_path


def _audit(runtime_root, run_id=RUN_ID):
    return json.loads((runtime_root / "run-audits" / f"{run_id}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "summary",
    [
        {},
        _partial_summary(),
        {**_clean_summary(), "deferredCandidateCount": 1},
        {key: value for key, value in _clean_summary().items() if key != "caseCoverageGapCount"},
        {key: value for key, value in _clean_summary().items() if key != "deferredCandidateCount"},
        {
            key: value
            for key, value in _clean_summary().items()
            if key != "unresolvedDeepRecordMentionCount"
        },
        {**_clean_summary(), "unresolvedUniqueComponentCount": 1},
        {**_clean_summary(), "caseCoverage": {"rotation": "evidence_missing"}},
    ],
    ids=[
        "legacy_unknown", "partial", "deferred", "missing_coverage_count", "missing_deferred_count",
        "missing_unresolved_count", "unique_gap", "coverage_gap",
    ],
)
def test_cleanup_requires_proven_completion_before_removing_raw_material(
    runtime, monkeypatch, summary
):
    run_dir, _ = _queue_case(runtime, summary)
    cleanup_calls = []
    monkeypatch.setattr(
        research_mature_builds.research_packet,
        "cleanup_packets_by_safe_hashes",
        lambda *_args, **_kwargs: cleanup_calls.append(True) or {"removed": 1},
    )

    result = research_mature_builds.cleanup_completed_run(run_id=RUN_ID)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "research_followup_required"
    assert run_dir.is_dir()
    assert cleanup_calls == []


@pytest.mark.parametrize(
    "missing_count",
    ["deferredCandidateCount", "unresolvedDeepRecordMentionCount", "caseCoverageGapCount"],
)
def test_status_does_not_infer_missing_diagnostics_from_database_defaults(runtime, missing_count):
    summary = {key: value for key, value in _clean_summary().items() if key != missing_count}
    _queue_case(runtime, summary)

    status = research_workflow.run_status(run_ref=f"research-run:{RUN_ID}")

    assert status["samples"][0]["researchCompletion"] == "unknown"


@pytest.mark.parametrize("abandon_incomplete", [False, True])
def test_cleanup_never_abandons_an_inflight_accept(runtime, monkeypatch, abandon_incomplete):
    run_dir, db_path = _queue_case(runtime, _clean_summary(), status="accepting")
    before = db_path.read_bytes()
    cleanup_calls = []
    monkeypatch.setattr(
        research_mature_builds.research_packet,
        "cleanup_packets_by_safe_hashes",
        lambda *_args, **_kwargs: cleanup_calls.append(True) or {"removed": 1},
    )

    result = research_mature_builds.cleanup_completed_run(
        run_id=RUN_ID, abandon_incomplete=abandon_incomplete
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "research_acceptance_recovery_required"
    assert run_dir.is_dir()
    assert db_path.read_bytes() == before
    assert cleanup_calls == []
    assert not (runtime / "run-audits" / f"{RUN_ID}.json").exists()


@pytest.mark.parametrize(
    "summary, completion", [({}, "unknown"), (_partial_summary(), "needs_followup")]
)
def test_explicit_abandon_preserves_raw_free_gaps_and_archived_typed_status(
    runtime, monkeypatch, summary, completion
):
    unsafe_marker = "private-raw-review-sentinel"
    summary = {**summary, "rawXml": unsafe_marker, "privatePath": "C:/private/source.xml"}
    run_dir, _ = _queue_case(runtime, summary)
    (run_dir / "raw-private-review.json").write_text(unsafe_marker, encoding="utf-8")
    monkeypatch.setattr(
        research_mature_builds.research_packet,
        "cleanup_packets_by_safe_hashes",
        lambda *_args, **_kwargs: {"removed": 1},
    )

    result = research_workflow.cleanup_run(
        run_ref=f"research-run:{RUN_ID}", abandon_incomplete=True
    )

    assert result["status"] == "cleaned", result
    assert not run_dir.exists()
    archive = _audit(runtime)
    assert archive["samples"][0]["researchCompletion"] == completion
    serialized = json.dumps(archive)
    assert unsafe_marker not in serialized
    assert "C:/private" not in serialized
    assert "rawXml" not in serialized

    status = research_workflow.run_status(run_ref=f"research-run:{RUN_ID}")
    assert status["status"] == "archived"
    assert status["rawMaterialAvailable"] is False
    assert status["sourceSnapshotRecovery"] == "unavailable"
    assert status["samples"][0]["researchCompletion"] == completion
    assert status["acceptedCount"] == status["acceptedDeepRecordCount"] == 1
    assert status["researchCompleteCount"] == 0
    assert status["researchNeedsFollowupCount"] + status["researchCompletionUnknownCount"] == 1
    for operation in (
        lambda: research_workflow.claim_case(run_ref=f"research-run:{RUN_ID}"),
        lambda: research_workflow.read_case(
            run_ref=f"research-run:{RUN_ID}", lease_token="stale-lease", section="build"
        ),
    ):
        with pytest.raises(ValueError, match="not found"):
            operation()


def test_cleanup_audit_is_written_before_packets_or_run_are_deleted(runtime, monkeypatch):
    run_dir, _ = _queue_case(runtime, _clean_summary())

    def clean_packets(*_args, **_kwargs):
        assert run_dir.is_dir()
        assert _audit(runtime)["samples"][0]["researchCompletion"] == "complete"
        return {"removed": 0}

    monkeypatch.setattr(
        research_mature_builds.research_packet, "cleanup_packets_by_safe_hashes", clean_packets
    )

    result = research_mature_builds.cleanup_completed_run(run_id=RUN_ID)

    assert result["status"] == "cleaned", result
    assert not run_dir.exists()

    status = research_workflow.run_status(run_ref=f"research-run:{RUN_ID}")
    assert status["acceptedCount"] == status["researchCompleteCount"] == 1
    assert status["researchNeedsFollowupCount"] == status["researchCompletionUnknownCount"] == 0


def test_audit_write_failure_preserves_the_run_and_packets(runtime, monkeypatch):
    run_dir, _ = _queue_case(runtime, _partial_summary())
    original_replace = Path.replace
    cleanup_calls = []

    def fail_audit_write(path, target):
        if path.parent.name == "run-audits":
            raise OSError("injected audit persistence failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_audit_write)
    monkeypatch.setattr(
        research_mature_builds.research_packet,
        "cleanup_packets_by_safe_hashes",
        lambda *_args, **_kwargs: cleanup_calls.append(True) or {"removed": 1},
    )

    with pytest.raises(OSError, match="audit persistence failure"):
        research_mature_builds.cleanup_completed_run(run_id=RUN_ID, abandon_incomplete=True)

    assert run_dir.is_dir()
    assert cleanup_calls == []
    assert not (runtime / "run-audits" / f"{RUN_ID}.json").exists()


def test_failed_abandon_keeps_original_gap_state_and_does_not_claim_archived(runtime, monkeypatch):
    run_dir, _ = _queue_case(runtime, _partial_summary())
    monkeypatch.setattr(
        research_mature_builds.research_packet,
        "cleanup_packets_by_safe_hashes",
        lambda *_args, **_kwargs: {"removed": 0},
    )
    monkeypatch.setattr(
        research_mature_builds,
        "_delete_run_directory",
        lambda *_args: ("deferred", {"reason": "directory_rename_failed"}),
    )

    result = research_workflow.cleanup_run(
        run_ref=f"research-run:{RUN_ID}", abandon_incomplete=True
    )

    assert result["status"] == "partial"
    assert run_dir.is_dir()
    assert _audit(runtime)["samples"][0]["researchCompletion"] == "needs_followup"
    status = research_workflow.run_status(run_ref=f"research-run:{RUN_ID}")
    assert status["status"] != "archived"
    assert status["samples"][0]["researchCompletion"] == "needs_followup"


def test_legacy_pending_cleanup_cannot_bypass_followup_gate(runtime):
    run_dir, _ = _queue_case(runtime, _partial_summary())
    research_mature_builds._queue_pending_cleanup(
        runtime / "runs",
        run_id=RUN_ID,
        evidence={"caseCount": 1, "acceptedDeepRecordCount": 1},
    )

    result = research_mature_builds.cleanup_completed_run(run_id=MISSING_RUN_ID)

    assert result["errorCode"] == "research_run_not_found"
    assert run_dir.is_dir()
    pending = research_mature_builds._read_pending_cleanups(runtime / "runs")
    assert [item["runId"] for item in pending] == [RUN_ID]


@pytest.mark.parametrize("mutation", ["completion", "queue_metadata", "audit"])
def test_pending_cleanup_requires_unchanged_queue_and_audit(
    runtime, monkeypatch, mutation
):
    run_dir, db_path = _queue_case(runtime, _clean_summary())
    monkeypatch.setattr(
        research_mature_builds.research_packet,
        "cleanup_packets_by_safe_hashes",
        lambda *_args, **_kwargs: {"removed": 0},
    )
    original_delete = research_mature_builds._delete_run_directory
    monkeypatch.setattr(
        research_mature_builds,
        "_delete_run_directory",
        lambda *_args: ("deferred", {"reason": "directory_rename_failed"}),
    )
    first = research_mature_builds.cleanup_completed_run(run_id=RUN_ID)
    assert first["status"] == "partial"
    assert first["queuedDelayedRetry"] is True

    if mutation == "audit":
        audit_path = runtime / "run-audits" / f"{RUN_ID}.json"
        altered_audit = _audit(runtime)
        altered_audit["sourceGamePatch"] = "changed-after-cleanup-prepared"
        audit_path.write_text(json.dumps(altered_audit), encoding="utf-8")
    else:
        with closing(sqlite3.connect(db_path)) as con, con:
            if mutation == "completion":
                con.execute(
                    "UPDATE cases SET research_quality_summary=?", (json.dumps(_partial_summary()),)
                )
            else:
                con.execute("UPDATE cases SET safe_error='queue changed after cleanup was prepared'")
    monkeypatch.setattr(research_mature_builds, "_delete_run_directory", original_delete)

    research_mature_builds.cleanup_completed_run(run_id=MISSING_RUN_ID)

    assert run_dir.is_dir()
    pending = research_mature_builds._read_pending_cleanups(runtime / "runs")
    assert [item["runId"] for item in pending] == [RUN_ID]


def test_clean_supplement_cleanup_does_not_close_parent_case_gaps(runtime, monkeypatch):
    parent_dir, _ = _queue_case(runtime, _partial_summary())
    child_dir, _ = _queue_case(runtime, _clean_summary(), run_id=OTHER_RUN_ID, supplement=True)
    monkeypatch.setattr(
        research_mature_builds.research_packet,
        "cleanup_packets_by_safe_hashes",
        lambda *_args, **_kwargs: {"removed": 0},
    )

    result = research_workflow.cleanup_run(run_ref=f"research-run:{OTHER_RUN_ID}")

    assert result["status"] == "cleaned", result
    assert not child_dir.exists()
    assert parent_dir.is_dir()
    archive = _audit(runtime, OTHER_RUN_ID)
    assert archive["samples"][0]["researchCompletion"] == "complete"
    assert archive["samples"][0]["completionScope"] == "supplement"
    parent = research_workflow.run_status(run_ref=f"research-run:{RUN_ID}")
    assert parent["samples"][0]["researchCompletion"] == "needs_followup"
    blocked = research_workflow.cleanup_run(run_ref=f"research-run:{RUN_ID}")
    assert blocked["errorCode"] == "research_followup_required"
