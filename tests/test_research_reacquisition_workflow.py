from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from scripts import research_mature_builds as runs, run_phase45_researcher_batch as collector
from server import paths
from server.compute import pob_code
from server.knowledge import research_followup_workflow as followup
from server.knowledge import research_intake_ledger as intake
from server.knowledge import research_reacquisition as reservations
from server.knowledge import research_workflow as workflow


def _code(skill="Lightning Arrow"):
    return pob_code.encode_code(f'''<PathOfBuilding2>
      <Build level="95" className="Ranger" ascendClassName="Deadeye" mainSocketGroup="1" />
      <Skills><Skill><Gem nameSpec="{skill}" skillId="LightningArrowPlayer" enabled="true" /></Skill></Skills>
      <Tree activeSpec="1"><Spec treeVersion="0_5" nodes=""><Sockets /></Spec></Tree>
      <Items activeItemSet="1"><ItemSet id="1" /></Items>
    </PathOfBuilding2>''')


@pytest.fixture
def context(tmp_path, monkeypatch):
    runtime = tmp_path / "user-data" / "research"
    ledger = tmp_path / "user-data" / "research_intake.sqlite"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: runtime)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(runs, "DEFAULT_INTAKE_LEDGER_PATH", ledger)
    monkeypatch.setattr(runs, "_identity_resolvability_hint", lambda **_: {})
    monkeypatch.setattr(runs, "_studied_source_hashes", lambda **_: set())
    monkeypatch.setattr(workflow, "_source_patch_for_run", lambda **_: ("0.5.5", "runesofaldur"))
    monkeypatch.setattr(followup, "_accepted_receipt_matches", lambda *args, **kwargs: True, raising=False)
    identity = intake.character_ref("fixture-account", "fixture-character")
    code = _code()

    def make_case(code=code, character_ref=identity, league="runesofaldur"):
        return collector._case_from_source(
            code, source_hash=collector._safe_hash(code), sample_id="case:fixture-001",
            source_type="poe_ninja_import_code", league=league, character_ref=character_ref, row={},
        )

    monkeypatch.setattr(collector, "_cases_from_ninja", lambda **_: [make_case()])
    parent = workflow.start_run(limit=1, worker_count=1)
    parent_dir = workflow._run_dir(parent["runRef"])
    parent_db = parent_dir / runs.QUEUE_DB_FILENAME
    origin = runs._fetch_cases(parent_db)[0]
    with sqlite3.connect(parent_db) as conn:
        conn.execute("UPDATE cases SET status='accepted',finalization_status='complete'")
    intake.mark_accepted(ledger, league="runesofaldur", character_ref=identity)
    parent_args = dict(run_ref=parent["runRef"], sample_id=origin["sampleId"], request_id="retry-001")
    followup_state = {
        "status": "ok", "openGapCount": 1, "originFingerprint": "b" * 64,
        "sourceIdentity": {"sourceHashRef": origin["sourceHashRef"], "gamePatch": "0.5.5"},
    }
    monkeypatch.setattr(followup, "get_followup_status", lambda **_: deepcopy(followup_state))
    calls = []
    responses = [make_case()]

    def collect(**kwargs):
        calls.append(kwargs)
        return deepcopy(responses)

    monkeypatch.setattr(collector, "_cases_from_ninja", collect)
    return SimpleNamespace(runtime=runtime, ledger=ledger, parent=parent, args=parent_args,
                           origin=origin, calls=calls, responses=responses, make_case=make_case,
                           followup_state=followup_state, identity=identity)


def _request(ctx):
    return reservations.get_request(ctx.runtime / "reacquisition.sqlite", request_id=ctx.args["request_id"])


def _child_db(ctx):
    return workflow._run_dir(_request(ctx)["newRunRef"], require_queue=False) / runs.QUEUE_DB_FILENAME


def test_reacquisition_uses_exact_target_and_preserves_accepted_ledger(context):
    before = context.ledger.read_bytes()
    result = followup.reacquire_source(**context.args)
    assert result["status"] == "queued"
    assert result["reacquisition"]["sourceRelation"] == "exact_source"
    assert result["runRef"] != context.parent["runRef"]
    assert len(context.calls) == 1
    assert context.calls[0]["target_character_refs"] == {context.identity}
    assert context.calls[0]["league_url"] == "runesofaldur"
    assert context.ledger.read_bytes() == before
    metadata = runs._read_metadata(_child_db(context))
    assert metadata["reacquisitionParentRunRef"] == context.parent["runRef"]
    assert metadata["reacquisitionParentSampleId"] == context.args["sample_id"]
    assert metadata["reacquisitionRequestId"] == context.args["request_id"]


@pytest.mark.parametrize("change_patch", [False, True])
def test_changed_snapshot_keeps_origin_binding_and_is_a_successor(context, monkeypatch, change_patch):
    if change_patch:
        monkeypatch.setattr(workflow, "_source_patch_for_run", lambda **_: ("0.5.6", "runesofaldur"))
    else:
        context.responses[:] = [context.make_case(code=_code("Spark"))]
    result = followup.reacquire_source(**context.args)
    reservation = result["reacquisition"]
    assert reservation["sourceRelation"] == "successor_snapshot"
    assert reservation["originPatch"] == "0.5.5"
    assert reservation["originSourceHash"] == context.origin["sourceHash"]
    assert reservation["sourcePatch"] == ("0.5.6" if change_patch else "0.5.5")


def test_same_request_never_repeats_collection(context):
    first = followup.reacquire_source(**context.args)
    repeated = followup.reacquire_source(**context.args)
    status = followup.reacquire_source(**context.args, action="status")
    assert repeated["idempotent"] is True and status["idempotent"] is True
    assert repeated["newRunRef"] == first["runRef"] == status["newRunRef"]
    assert len(context.calls) == 1


def test_concurrent_same_request_returns_one_child_and_collects_once(context, monkeypatch):
    original = reservations.get_request
    barrier = threading.Barrier(2)
    local = threading.local()

    def synchronize_initial_lookup(*args, **kwargs):
        result = original(*args, **kwargs)
        if not getattr(local, "initial_lookup_done", False):
            local.initial_lookup_done = True
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(reservations, "get_request", synchronize_initial_lookup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: followup.reacquire_source(**context.args), (1, 2)))
    assert len(context.calls) == 1
    child_refs = {result.get("runRef") or result.get("newRunRef") for result in responses}
    assert len(child_refs) == 1 and None not in child_refs
    assert sum(result.get("idempotent") is True for result in responses) == 1


@pytest.mark.parametrize("changed_field", ["run_ref", "sample_id"])
def test_same_request_cannot_change_parent_or_sample(context, changed_field):
    followup.reacquire_source(**context.args)
    args = {**context.args, changed_field: "research-run:20260906-123456-aaff" if changed_field == "run_ref" else "case:other"}
    result = followup.reacquire_source(**args)
    assert result["errorCode"] == "reacquisition_request_conflict"
    assert len(context.calls) == 1


def test_missing_target_does_not_fill_with_another_source(context):
    context.responses.clear()
    before = context.ledger.read_bytes()
    result = followup.reacquire_source(**context.args)
    assert result["status"] == "failed"
    assert result["searchOutcome"] == "not_found_within_search_scope"
    assert _request(context)["status"] == "failed"
    assert runs._fetch_cases(_child_db(context)) == []
    assert context.ledger.read_bytes() == before
    repeated = followup.reacquire_source(**context.args)
    assert repeated["status"] == "failed"
    assert len(context.calls) == 1


def test_mismatched_collector_character_stays_unbound(context):
    context.responses[:] = [context.make_case(character_ref="character-hash:" + "f" * 16)]
    result = followup.reacquire_source(**context.args)
    assert result["errorCode"] == "research_reacquisition_interrupted"
    assert result["recoveryRequired"] is True
    assert _request(context)["status"] == "reserved"
    assert not _child_db(context).exists()
    assert not (_child_db(context).parent / "quarantine").exists()
    recovered = followup.reacquire_source(**context.args, action="status")
    assert recovered["recoveryRequired"] is True
    assert _request(context)["status"] == "reserved"


def test_reserved_queue_commit_can_be_reconciled_after_mark_failure(context, monkeypatch):
    original = reservations.mark_queued

    def interrupted(*args, **kwargs):
        raise RuntimeError("synthetic committed queue response failure")

    monkeypatch.setattr(reservations, "mark_queued", interrupted)
    failed = followup.reacquire_source(**context.args)
    assert failed["errorCode"] == "research_reacquisition_interrupted"
    assert _request(context)["status"] == "reserved"
    assert len(runs._fetch_cases(_child_db(context))) == 1
    monkeypatch.setattr(reservations, "mark_queued", original)
    recovered = followup.reacquire_source(**context.args, action="status")
    assert recovered["status"] == "queued"
    assert recovered["sourceRelation"] == "exact_source"
    assert len(context.calls) == 1


def test_collector_failure_requires_explicit_release_before_new_request(context, monkeypatch):
    def failed_collector(**kwargs):
        context.calls.append(kwargs)
        raise RuntimeError("fixture unavailable")

    monkeypatch.setattr(collector, "_cases_from_ninja", failed_collector)
    failed = followup.reacquire_source(**context.args)
    assert failed["errorCode"] == "research_reacquisition_interrupted"
    assert _request(context)["status"] == "reserved"
    repeated = followup.reacquire_source(**context.args)
    assert repeated["recoveryRequired"] is True and len(context.calls) == 1
    conflict = followup.reacquire_source(**{**context.args, "request_id": "retry-002"})
    assert conflict["errorCode"] == "reacquisition_scope_reserved"
    released = followup.reacquire_source(**context.args, action="release")
    assert released["status"] == "failed"
    assert released["reasonCode"] == "explicit_release"


@pytest.mark.parametrize("status", ["pending", "claimed", "accepting"])
def test_live_child_queue_blocks_release(context, status):
    followup.reacquire_source(**context.args)
    with sqlite3.connect(_child_db(context)) as conn:
        conn.execute("UPDATE cases SET status=?", (status,))
    result = followup.reacquire_source(**context.args, action="release")
    assert result["errorCode"] == "reacquisition_child_cleanup_required"
    assert _request(context)["status"] == "queued"


def test_disposed_child_releases_scope_through_its_safe_archive(context):
    started = followup.reacquire_source(**context.args)
    cleaned = workflow.cleanup_run(run_ref=started["runRef"], abandon_incomplete=True)
    assert cleaned["status"] == "cleaned"
    result = followup.reacquire_source(**context.args, action="release")
    assert result["status"] == "failed"
    assert result["reasonCode"] == "child_disposed"


def test_accepted_finalized_child_finishes_without_closing_parent_gaps(context):
    followup.reacquire_source(**context.args)
    with sqlite3.connect(_child_db(context)) as conn:
        conn.execute("UPDATE cases SET status='accepted', finalization_status='complete'")
    result = followup.reacquire_source(**context.args, action="status")
    assert result["status"] == "completed"
    assert context.followup_state["openGapCount"] == 1


def test_accepted_child_without_matching_receipt_cannot_finalize(context, monkeypatch):
    followup.reacquire_source(**context.args)
    with sqlite3.connect(_child_db(context)) as conn:
        conn.execute("UPDATE cases SET status='accepted', finalization_status='complete'")
    monkeypatch.setattr(followup, "_accepted_receipt_matches", lambda *args, **kwargs: False)
    result = followup.reacquire_source(**context.args, action="status")
    assert result.get("recoveryRequired") is True or result.get("status") == "rejected"
    assert _request(context)["status"] == "queued"


@pytest.mark.parametrize(("column", "value"), [
    ("source_hash", "e" * 64), ("league", "standard"),
])
def test_queue_identity_drift_cannot_finalize_a_bound_request(context, column, value):
    followup.reacquire_source(**context.args)
    with sqlite3.connect(_child_db(context)) as conn:
        conn.execute(f"UPDATE cases SET {column}=?,status='accepted',finalization_status='complete'", (value,))
    result = followup.reacquire_source(**context.args, action="status")
    assert result.get("recoveryRequired") is True or result.get("status") == "rejected"
    assert _request(context)["status"] == "queued"


@pytest.mark.parametrize(("key", "value"), [
    ("reacquisitionParentRunRef", "research-run:20260906-123456-aaff"),
    ("reacquisitionParentSampleId", "case:wrong-parent"),
    ("reacquisitionRequestId", "wrong-request"), ("currentPatch", "0.5.6"),
    ("leagueUrl", "standard"),
])
def test_child_metadata_drift_cannot_finalize_a_request(context, key, value):
    followup.reacquire_source(**context.args)
    db = _child_db(context)
    runs._write_metadata(db, {key: value})
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE cases SET status='accepted',finalization_status='complete'")
    result = followup.reacquire_source(**context.args, action="status")
    assert result.get("recoveryRequired") is True or result.get("status") == "rejected"
    assert _request(context)["status"] == "queued"


def test_collector_league_mismatch_cannot_authorize_a_different_scope(context):
    context.responses[:] = [context.make_case(league="standard")]
    result = followup.reacquire_source(**context.args)
    assert result.get("recoveryRequired") is True or result.get("status") == "rejected"
    assert _request(context)["status"] == "reserved"
    assert not _child_db(context).exists()
    assert not (_child_db(context).parent / "quarantine").exists()


@pytest.mark.parametrize("issue", ["no_open_gap", "wrong_source"])
def test_missing_gap_or_mismatched_origin_receipt_never_starts_collection(context, issue):
    if issue == "no_open_gap":
        context.followup_state["openGapCount"] = 0
    else:
        context.followup_state["sourceIdentity"]["sourceHashRef"] = "source-hash:" + "f" * 16
    result = followup.reacquire_source(**context.args)
    assert result["errorCode"] == ("open_research_gap_required" if issue == "no_open_gap" else "reacquisition_origin_source_mismatch")
    assert context.calls == [] and _request(context) is None


@pytest.mark.parametrize("changed_field", ["lineage", "character", "source_hash", "source_ref", "patch"])
@pytest.mark.parametrize("action", ["status", "release"])
def test_disposed_child_archive_cannot_release_a_different_binding(context, changed_field, action):
    started = followup.reacquire_source(**context.args)
    cleaned = workflow.cleanup_run(run_ref=started["runRef"], abandon_incomplete=True)
    assert cleaned["status"] == "cleaned"
    audit_path = runs._run_audit_path(context.runtime, started["runId"])
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if changed_field == "lineage":
        audit["reacquisitionRequestId"] = "wrong-request"
    elif changed_field == "character":
        audit["samples"][0]["characterRef"] = "character-hash:" + "e" * 16
    elif changed_field == "source_hash":
        audit["samples"][0]["sourceHash"] = "e" * 64
    elif changed_field == "source_ref":
        audit["samples"][0]["sourceHashRef"] = "source-hash:" + "e" * 16
    else:
        audit["sourceGamePatch"] = "0.5.6"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    result = followup.reacquire_source(**context.args, action=action)
    assert result.get("recoveryRequired") is True or result.get("status") == "rejected"
    assert _request(context)["status"] == "queued"


def test_release_winning_the_child_lock_prevents_the_original_collector(context, monkeypatch):
    original_lock = followup.interprocess_file_lock
    interleaved = []

    @contextmanager
    def let_release_win(path):
        if not interleaved:
            interleaved.append(True)
            released = followup.reacquire_source(**context.args, action="release")
            assert released["status"] == "failed"
        with original_lock(path):
            yield

    monkeypatch.setattr(followup, "interprocess_file_lock", let_release_win)
    result = followup.reacquire_source(**context.args)
    assert result["status"] == "failed"
    assert context.calls == []
    assert _request(context)["status"] == "failed"
    assert not _child_db(context).exists()
