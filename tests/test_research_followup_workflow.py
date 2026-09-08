"""R3b typed 缺口处置、原队列和安全清理之间的完整集成回归。"""

from contextlib import closing
import json
import sqlite3

import pytest

from scripts import research_mature_builds as runs
from server import paths
from server.knowledge import research_followup_workflow as workflow
from server.knowledge import research_memory, research_workflow
from test_research_acceptance_diagnostics import _clean, _partial
from test_research_v3_contracts import _graph_service, _record


PARENT = "20260906-101010-a001"
SUPPORT = "20260906-101011-a002"
REVISION = "20260906-101012-a003"
SOURCE = "source-hash:" + "a" * 16


def test_followup_transport_pages_large_unicode_diagnostics_without_omission(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: tmp_path / "research")
    items = [{"gapRef": f"rgap-{index:024x}", "rationale": "恢复条件" * 400} for index in range(90)]

    def inspect(**kwargs):
        offset, limit = kwargs["offset"], kwargs["limit"]
        return {"status": "ok", "gaps": items[offset:offset + limit], "offset": offset,
                "total": len(items), "nextOffset": offset + limit if offset + limit < len(items) else None}

    monkeypatch.setattr(workflow.gaps, "inspect_followups", inspect)
    cursor, seen = 0, []
    while True:
        page = workflow.get_followup_status(run_ref=f"research-run:{PARENT}", sample_id=f"case:{PARENT}", cursor=cursor, limit=200)
        assert len(json.dumps(page, ensure_ascii=False).encode("utf-8")) <= 65536
        seen.extend(item["gapRef"] for item in page["gaps"])
        if page["nextOffset"] is None:
            break
        assert page["nextOffset"] > cursor
        cursor = page["nextOffset"]
    assert seen == [item["gapRef"] for item in items]


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / "user-data" / "research"
    memory = tmp_path / "user-data" / "memory.sqlite"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: root)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: memory)
    monkeypatch.setattr(runs, "DEFAULT_OUTPUT_DIR", root)
    monkeypatch.setattr(runs, "DEFAULT_INTAKE_LEDGER_PATH", root / "intake.sqlite")
    # 模拟已有 quarantine packet 的清理入口；实际 run/quarantine 目录仍由真实清理器删除。
    monkeypatch.setattr(runs.research_packet, "cleanup_packets_by_safe_hashes", lambda *_args, **_kwargs: {"removed": 0})
    service = research_memory.ResearchMemoryService(db_path=memory, graph_service=_graph_service())

    def accept(run_id, diagnostics, *, content=None):
        sample = f"case:{run_id}"
        record = _record()
        record.update(source_case_refs=[SOURCE], pob_version_or_commit="0.23.1",
                      content=content or "资源恢复需与当前活动条件一致并逐项验证。")
        receipt = service.accept_research_unit(
            run_ref=f"research-run:{run_id}", sample_id=sample,
            accept_attempt_key="raa-" + run_id, packet_safe_hash="packet-" + run_id,
            canonical_review_hash="review-" + run_id, contract_version="phase4-safe-review-v3",
            expected_origin_state="claimed", pattern_payload={"schema_version": 4},
            deep_payload={"schema_version": 6, "deep_research_records": [record]},
            edge_payload={"schema_version": 4}, acceptance_diagnostics=diagnostics,
            source_context={"sourceHashRef": SOURCE, "sourceHash": "a" * 64, "gamePatch": "0.5.4",
                            "passiveTreeVersion": "tree-test", "pobVersionOrCommit": "0.23.1",
                            "knowledgeScope": "local_user", "sourceSnapshotHash": "b" * 64,
                            "activeSets": {"skillSet": "1", "itemSet": "1", "passiveSpec": "1", "configSet": "1"}},
        )
        assert receipt["status"] == "accepted", receipt
        run_dir = root / "runs" / run_id
        db = run_dir / runs.QUEUE_DB_FILENAME
        runs._init_db(db)
        runs._write_metadata(db, {"currentPatch": "0.5.4", "passiveTreeVersion": "tree-test", "league": "test-league"})
        runs._insert_case_if_absent(db, {
            "sampleId": sample, "status": "accepted", "sourceType": "poe_ninja_import_code",
            "sourceHash": "a" * 64, "sourceHashRef": SOURCE,
            "characterRef": "character-hash:" + "c" * 16, "league": "test-league",
            "level": 95, "className": "Witch", "ascendancy": "Blood Mage",
            "mainSkill": "Comet", "safeError": "", "packetId": "packet:" + run_id,
            "packetSafeHash": "packet-" + run_id,
        })
        with closing(sqlite3.connect(db)) as con, con:
            con.execute(
                "UPDATE cases SET research_quality_summary=?, accepted_deep_record_count=1, "
                "deferred_candidate_count=?, write_receipt_ref=?, finalization_status='complete'",
                (json.dumps(runs._research_quality_summary(receipt)),
                 receipt["deferredCandidateCount"], receipt["writeReceiptRef"]),
            )
        quarantine = run_dir / "quarantine"
        quarantine.mkdir()
        (quarantine / "test-material.txt").write_text("private-quarantine-integration-marker", encoding="utf-8")
        return receipt

    parent = accept(PARENT, _partial())
    support = accept(SUPPORT, {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    return {"root": root, "memory": memory, "service": service, "accept": accept,
            "parent": parent, "support": support,
            "params": {"run_ref": f"research-run:{PARENT}", "sample_id": f"case:{PARENT}"}}


def _gaps(runtime):
    result = workflow.get_followup_status(**runtime["params"])
    assert result["status"] == "ok", result
    return result


def _decision(runtime, gap, disposition="resolved"):
    result = {"gapRef": gap["gapRef"], "disposition": disposition,
              "rationale": "已独立深读新增记录，确认本项原条件缺口的处置范围。"}
    if disposition != "reopen":
        result.update(supportingWriteReceiptRef=runtime["support"]["writeReceiptRef"],
                      supportingRecordIds=runtime["support"]["deepRecordWrite"]["recordIds"])
    return result


def _submit(runtime, gaps, *, revision=0, request="close", disposition="resolved"):
    return workflow.submit_gap_review(**runtime["params"], expected_revision=revision,
                                     request_id=request, decisions=[_decision(runtime, gap, disposition) for gap in gaps])


def _close_all(runtime):
    state = _gaps(runtime)
    result = _submit(runtime, state["gaps"], revision=state["revision"])
    assert result["status"] == "accepted", result
    assert result["effectiveResearchCompletion"] == "complete"
    return state["gaps"]


def _original_summary(runtime):
    return runtime["service"].get_research_write_receipt(runtime["parent"]["writeReceiptRef"])["acceptanceSummary"]


def _cleanup(runtime):
    return research_workflow.cleanup_run(run_ref=runtime["params"]["run_ref"])


def test_partial_gap_closure_only_unlocks_cleanup_after_all_explicit_decisions(runtime):
    before = _original_summary(runtime)
    gaps = _gaps(runtime)["gaps"]
    first = _submit(runtime, gaps[:1])
    assert first["openGapCount"] == 1
    denied = _cleanup(runtime)
    assert denied["errorCode"] == "research_followup_required"
    run_dir = runtime["root"] / "runs" / PARENT
    assert (run_dir / "quarantine" / "test-material.txt").is_file()
    second = _submit(runtime, gaps[1:], revision=1, request="close-remaining")
    assert second["effectiveResearchCompletion"] == "complete"
    status = research_workflow.run_status(run_ref=runtime["params"]["run_ref"])
    assert status["researchCompleteCount"] == 0
    assert status["effectiveResearchCompleteCount"] == 1
    assert status["samples"][0]["researchCompletion"] == "needs_followup"
    assert status["samples"][0]["effectiveResearchCompletion"] == "complete"
    cleaned = _cleanup(runtime)
    assert cleaned["status"] == "cleaned", cleaned
    assert not run_dir.exists()
    assert _original_summary(runtime) == before


def test_archive_preserves_original_partial_and_keeps_typed_gap_event_inspection(runtime):
    _close_all(runtime)
    assert _cleanup(runtime)["status"] == "cleaned"
    audit = json.loads((runtime["root"] / "run-audits" / f"{PARENT}.json").read_text(encoding="utf-8"))
    assert audit["samples"][0]["researchCompletion"] == "needs_followup"
    assert audit["samples"][0]["effectiveResearchCompletion"] == "complete"
    assert "private-quarantine-integration-marker" not in json.dumps(audit)
    status = research_workflow.run_status(run_ref=runtime["params"]["run_ref"])
    assert status["status"] == "archived" and status["rawMaterialAvailable"] is False
    assert status["researchCompleteCount"] == 0 and status["effectiveResearchCompleteCount"] == 1
    assert _gaps(runtime)["closedGapCount"] == 2
    first = workflow.get_followup_status(**runtime["params"], view="events", limit=1)
    second = workflow.get_followup_status(**runtime["params"], view="events", cursor=1, limit=1)
    assert first["total"] == 2 and first["nextOffset"] == 1
    assert second["nextOffset"] is None
    assert first["events"][0]["eventId"] != second["events"][0]["eventId"]


def test_explicit_reopen_blocks_default_cleanup_again(runtime):
    gaps = _close_all(runtime)
    reopened = _submit(runtime, gaps[:1], revision=1, request="reopen", disposition="reopen")
    assert reopened["openGapCount"] == 1
    denied = _cleanup(runtime)
    assert denied["errorCode"] == "research_followup_required"
    assert (runtime["root"] / "runs" / PARENT / runs.QUEUE_DB_FILENAME).is_file()
    assert _original_summary(runtime)["acceptanceMode"] == "partial_with_deferred"


def test_support_projection_revision_reopens_effective_status_and_reblocks_cleanup(runtime):
    _close_all(runtime)
    runtime["accept"](REVISION, _clean(), content="后续证据修订结论，因此需要复查旧缺口的关闭。")
    status = research_workflow.run_status(run_ref=runtime["params"]["run_ref"])
    assert status["effectiveResearchCompleteCount"] == 0
    assert status["samples"][0]["effectiveResearchCompletion"] == "needs_followup"
    assert _gaps(runtime)["openGapCount"] == 2
    assert _gaps(runtime)["eventCount"] == 2
    assert _cleanup(runtime)["errorCode"] == "research_followup_required"


def test_support_revision_after_archive_keeps_safe_history_and_reports_reopened_work(runtime):
    _close_all(runtime)
    assert _cleanup(runtime)["status"] == "cleaned"
    runtime["accept"](REVISION, _clean(), content="后来更新使旧支持失效；归档不能让旧闭合永久有效。")
    status = research_workflow.run_status(run_ref=runtime["params"]["run_ref"])
    assert status["status"] == "archived" and status["rawMaterialAvailable"] is False
    assert status["effectiveResearchCompleteCount"] == 0
    assert _gaps(runtime)["openGapCount"] == 2
    events = workflow.get_followup_status(**runtime["params"], view="events")
    assert events["total"] == 2
    assert all(event["disposition"] == "resolved" for event in events["events"])


@pytest.mark.parametrize("change", ["new_gap_event", "support_projection", "unversioned_support_projection"])
def test_pending_cleanup_revalidates_new_events_and_memory_mutations(runtime, monkeypatch, change):
    gaps = _close_all(runtime)
    original_delete = runs._delete_run_directory
    monkeypatch.setattr(runs, "_delete_run_directory",
                        lambda *_args: ("deferred", {"reason": "directory_rename_failed"}))
    pending = _cleanup(runtime)
    assert pending["queuedDelayedRetry"] is True
    queued = runs._read_pending_cleanups(runtime["root"] / "runs")
    assert len(queued) == 1
    assert queued[0]["evidence"]["followupStateHash"]
    assert isinstance(queued[0]["evidence"]["memoryRevision"], int)
    if change == "new_gap_event":
        assert _submit(runtime, gaps[:1], revision=1, request="reopen", disposition="reopen")["status"] == "accepted"
    elif change == "unversioned_support_projection":
        with closing(sqlite3.connect(runtime["memory"])) as con, con:
            con.execute("UPDATE deep_research_records SET projection_hash=? WHERE record_id=?",
                        ("f" * 64, runtime["support"]["deepRecordWrite"]["recordIds"][0]))
    else:
        runtime["accept"](REVISION, _clean(), content="提交新修订导致支持正文与旧receipt的精确指纹不同。")
    deletion_calls = []

    def delete_checked(*args):
        deletion_calls.append(args)
        return original_delete(*args)

    monkeypatch.setattr(runs, "_delete_run_directory", delete_checked)
    result = _cleanup(runtime)
    assert result["errorCode"] == "research_followup_required", result
    assert deletion_calls == []
    assert (runtime["root"] / "runs" / PARENT / runs.QUEUE_DB_FILENAME).is_file()
    assert len(runs._read_pending_cleanups(runtime["root"] / "runs")) == 1


def test_unchanged_pending_cleanup_can_resume_without_replaying_knowledge_writes(runtime, monkeypatch):
    _close_all(runtime)
    before = _original_summary(runtime)
    original_delete = runs._delete_run_directory
    monkeypatch.setattr(runs, "_delete_run_directory",
                        lambda *_args: ("deferred", {"reason": "directory_rename_failed"}))
    assert _cleanup(runtime)["queuedDelayedRetry"] is True
    monkeypatch.setattr(runs, "_delete_run_directory", original_delete)
    result = _cleanup(runtime)
    assert result["status"] == "cleaned", result
    assert result["delayedRetry"]["retriedIds"] == [PARENT]
    assert not (runtime["root"] / "runs" / PARENT).exists()
    assert _original_summary(runtime) == before
    assert _gaps(runtime)["eventCount"] == 2
