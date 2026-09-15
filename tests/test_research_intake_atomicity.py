"""普通采样跨 run 去重、提交边界恢复与历史完整 hash 回执的合成回归。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from scripts import research_mature_builds as research
from server import paths
from server.knowledge import research_intake_ledger as ledger
from server.knowledge import research_followups, research_memory, research_workflow
from test_phase45_researcher_batch import _FakeBrowser, _build_page, _sample_code
from test_research_v3_contracts import _graph_service, _record


LEAGUE = "runesofaldur"
LIST_URL = f"https://poe.ninja/poe2/builds/{LEAGUE}?min-level=95&max-level=95"


def _code(skill="LightningArrowPlayer"):
    return _sample_code(skill, ascendancy="Deadeye", level=95)


def _browser(*, first_code=None, second_code=None):
    def row(name):
        return (f'<tr><td><a href="/poe2/builds/{LEAGUE}/character/acct{name}/Char{name}">'
                f'Char{name}</a></td><td><div>95<img alt="Deadeye" /></div></td></tr>')
    return _FakeBrowser({
        LIST_URL: f"<html><body>{row('A')}</body></html>",
        LIST_URL + "&page=2": f"<html><body>{row('B')}</body></html>",
        f"https://poe.ninja/poe2/builds/{LEAGUE}/character/acctA/CharA": _build_page(first_code or _code()),
        f"https://poe.ninja/poe2/builds/{LEAGUE}/character/acctB/CharB": _build_page(second_code or _code("SparkPlayer")),
    })


def _queue(tmp_path, name, browser, **options):
    return research.queue_cases(
        league_url=LEAGUE, current_patch="0.5.4", passive_tree_version="tree-test",
        limit=1, level_min=95, level_max=95, output_dir=tmp_path / name,
        temp_root=tmp_path / (name + "-packets"), intake_ledger_path=tmp_path / "intake.sqlite",
        memory_db_path=tmp_path / "memory.sqlite", browser_driver=browser, **options,
    )


def test_concurrent_online_runs_recheck_ledger_and_fill_from_next_page(tmp_path, monkeypatch):
    first_browser, second_browser = _browser(), _browser()
    first_fetch, second_started, second_fetch, release = (threading.Event() for _ in range(4))
    first_original, second_original = first_browser.fetch_html, second_browser.fetch_html

    def first(url):
        first_fetch.set()
        assert release.wait(10)
        return first_original(url)

    def second(url):
        second_fetch.set()
        return second_original(url)

    monkeypatch.setattr(first_browser, "fetch_html", first)
    monkeypatch.setattr(second_browser, "fetch_html", second)

    def queue_second():
        second_started.set()
        return _queue(tmp_path, "second", second_browser)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(_queue, tmp_path, "first", first_browser)
        assert first_fetch.wait(10)
        second_result = pool.submit(queue_second)
        try:
            assert second_started.wait(10)
            assert not second_fetch.wait(0.2)
        finally:
            release.set()
        reports = [first_result.result(10), second_result.result(10)]
    assert [report["queuedCount"] for report in reports] == [1, 1]
    assert reports[1]["intakeSkippedAlreadyResearched"] == 1
    assert reports[1]["intakePagesFetched"] == 2
    assert not any("/character/acctA/" in url for url in second_browser.urls)
    assert ledger.summary(tmp_path / "intake.sqlite")["byStatus"] == {"queued": 2}


def test_current_alias_and_explicit_league_use_same_collection_lock(tmp_path, monkeypatch):
    lock_paths = []
    original = ledger.collection_lock_path
    monkeypatch.setattr(research.legacy_batch, "_resolve_league_url", lambda _: LEAGUE)
    monkeypatch.setattr(ledger, "collection_lock_path", lambda db, league: (
        lock_paths.append(original(db, league)) or lock_paths[-1]
    ))
    research.queue_cases(
        league_url="current", current_patch="0.5.4", limit=1, level_min=95, level_max=95,
        output_dir=tmp_path / "alias", temp_root=tmp_path / "alias-packets",
        intake_ledger_path=tmp_path / "intake.sqlite", browser_driver=_browser(),
    )
    _queue(tmp_path, "explicit", _browser())
    assert len(lock_paths) == 2 and lock_paths[0] == lock_paths[1]
    assert original(tmp_path / "intake.sqlite", "other-league") != lock_paths[0]


@pytest.mark.parametrize("failure", ["before_queue_commit", "after_queue_commit", "after_ledger_commit"])
def test_failure_retry_respects_durable_queue_commit(tmp_path, monkeypatch, failure):
    original_insert, original_record = research._insert_case_if_absent, ledger.record_case

    def fail_insert(db, row):
        if failure == "after_queue_commit":
            original_insert(db, row)
        raise RuntimeError("injected_queue_fault")

    def fail_record(*args, **kwargs):
        original_record(*args, **kwargs)
        raise RuntimeError("injected_ledger_fault")

    with monkeypatch.context() as patch:
        if failure == "after_ledger_commit":
            patch.setattr(ledger, "record_case", fail_record)
        else:
            patch.setattr(research, "_insert_case_if_absent", fail_insert)
        with pytest.raises(RuntimeError, match="injected_"):
            _queue(tmp_path, "failed", _browser())
    durable = failure == "after_queue_commit"
    assert ledger.summary(tmp_path / "intake.sqlite")["totalRecords"] == int(durable)
    assert research.has_committed_queue_cases(tmp_path / "failed" / research.QUEUE_DB_FILENAME) is durable
    retry_browser = _browser()
    retry = _queue(tmp_path, "retry", retry_browser)
    assert retry["queuedCount"] == 1
    expected = "B" if durable else "A"
    assert any(f"/character/acct{expected}/" in url for url in retry_browser.urls)


def test_failed_uncommitted_case_never_releases_accepted_history(tmp_path, monkeypatch):
    def accept_then_fail(db, row):
        ledger.mark_accepted(tmp_path / "intake.sqlite", league=LEAGUE, character_ref=row["characterRef"])
        raise RuntimeError("injected_after_accept")
    monkeypatch.setattr(research, "_insert_case_if_absent", accept_then_fail)
    with pytest.raises(RuntimeError, match="injected_after_accept"):
        _queue(tmp_path, "failed", _browser())
    assert ledger.summary(tmp_path / "intake.sqlite")["byStatus"] == {"accepted": 1}


def test_typed_start_retains_committed_queue_and_returns_recovery_ref(tmp_path, monkeypatch):
    runtime = tmp_path / "user-data" / "research"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: runtime)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(research, "DEFAULT_INTAKE_LEDGER_PATH", tmp_path / "intake.sqlite")
    monkeypatch.setattr(research_workflow, "_source_patch_for_run", lambda **_: ("0.5.4", LEAGUE))
    monkeypatch.setattr(research.legacy_batch.run_judge_ninja_samples, "PlaywrightHtmlDriver", _browser)
    original = research._insert_case_if_absent

    def fail_after_commit(db, row):
        original(db, row)
        raise RuntimeError("private exception text must not escape")
    monkeypatch.setattr(research, "_insert_case_if_absent", fail_after_commit)
    result = research_workflow.start_run(limit=1, level_min=95, level_max=95)
    assert result["status"] == "recovery_required" and result["recoveryRequired"]
    assert result["runRef"].startswith("research-run:")
    assert "private exception text" not in json.dumps(result)
    assert research.has_committed_queue_cases(runtime / "runs" / result["runId"] / research.QUEUE_DB_FILENAME)
    assert ledger.summary(tmp_path / "intake.sqlite")["byStatus"] == {"queued": 1}
    claim = research_workflow.claim_case(run_ref=result["runRef"])
    assert claim["status"] == "claimed"


@pytest.mark.parametrize("release_failure", ["exception", "ownership_mismatch"])
def test_failed_compensation_retains_typed_run_and_can_retry_exact_cleanup(tmp_path, monkeypatch, release_failure):
    runtime = tmp_path / "user-data" / "research"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: runtime)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(research, "DEFAULT_INTAKE_LEDGER_PATH", tmp_path / "intake.sqlite")
    monkeypatch.setattr(research_workflow, "_source_patch_for_run", lambda **_: ("0.5.4", LEAGUE))
    monkeypatch.setattr(research.legacy_batch.run_judge_ninja_samples, "PlaywrightHtmlDriver", _browser)

    def fail_before_commit(*args):
        raise RuntimeError("injected before queue commit")

    def fail_release(*args, **kwargs):
        if release_failure == "exception":
            raise sqlite3.OperationalError("injected release failure")
        return "ownership_mismatch"

    with monkeypatch.context() as patch:
        patch.setattr(research, "_insert_case_if_absent", fail_before_commit)
        patch.setattr(ledger, "release_queued_case", fail_release)
        started = research_workflow.start_run(limit=1, level_min=95, level_max=95)
        assert started["errorCode"] == "research_intake_release_recovery_required"
        assert started["recoveryRequired"]
        state = research_workflow.run_status(run_ref=started["runRef"])
        assert state["recoveryRequired"] and state["queuedCount"] == 0
        assert state["acceptedCount"] == 0
        assert ledger.summary(tmp_path / "intake.sqlite")["byStatus"] == {"queued": 1}
        blocked = research_workflow.cleanup_run(run_ref=started["runRef"])
        assert blocked["status"] == "rejected"
        failed = research_workflow.cleanup_run(run_ref=started["runRef"], abandon_incomplete=True)
        assert failed["errorCode"] == "research_intake_ledger_release_failed"
        assert (runtime / "runs" / started["runId"]).is_dir()
    cleaned = research_workflow.cleanup_run(run_ref=started["runRef"], abandon_incomplete=True)
    assert cleaned["status"] == "cleaned", cleaned
    assert cleaned["releasedIntakeLedgerCount"] == 1
    assert cleaned["removedTransientPacketCount"] == 1
    assert ledger.summary(tmp_path / "intake.sqlite")["totalRecords"] == 0
    audit = research.read_run_audit(output_dir=runtime, run_id=started["runId"])
    assert len(audit["intakeRecoveryCases"]) == 1
    assert audit["researchCompleteCount"] == 0
    retry = research_workflow.start_run(limit=1, level_min=95, level_max=95)
    assert retry["queuedCount"] == 1


@pytest.mark.parametrize("origin", ["queue", "recovery", "legacy_queue"])
def test_abandon_retry_cannot_release_new_registration_with_same_reusable_identity(tmp_path, monkeypatch, origin):
    runtime = tmp_path / "user-data" / "research"
    intake_path = tmp_path / "intake.sqlite"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: runtime)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(research, "DEFAULT_INTAKE_LEDGER_PATH", intake_path)
    monkeypatch.setattr(research_workflow, "_source_patch_for_run", lambda **_: ("0.5.4", LEAGUE))
    monkeypatch.setattr(research.legacy_batch.run_judge_ninja_samples, "PlaywrightHtmlDriver", _browser)

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("injected")

    with monkeypatch.context() as patch:
        if origin == "recovery":
            patch.setattr(research, "_insert_case_if_absent", fail)
            patch.setattr(ledger, "release_queued_case", fail)
        old = research_workflow.start_run(limit=1, level_min=95, level_max=95)
    old_db = runtime / "runs" / old["runId"] / research.QUEUE_DB_FILENAME
    if origin == "legacy_queue":
        with research._connect_queue(old_db) as con:
            con.execute("UPDATE cases SET intake_record_id=NULL")
        with sqlite3.connect(intake_path) as con:
            con.execute("UPDATE intake_records SET requires_instance_binding=0")
    old_row = (research._intake_recovery_rows(research._read_metadata(old_db))[0] if origin == "recovery"
               else research._fetch_cases(old_db)[0])
    old_instance = old_row["intakeRecordId"]
    replacement = {}

    def fail_delete_after_new_registration(*args):
        replacement.update(research_workflow.start_run(limit=1, level_min=95, level_max=95))
        return "deferred", {"recoveryRequired": False}

    with monkeypatch.context() as patch:
        patch.setattr(research, "_delete_run_directory", fail_delete_after_new_registration)
        failed_cleanup = research_workflow.cleanup_run(run_ref=old["runRef"], abandon_incomplete=True)
    assert failed_cleanup["status"] == "partial"
    if origin != "legacy_queue":
        assert failed_cleanup["recoveryRequired"]
    new_db = runtime / "runs" / replacement["runId"] / research.QUEUE_DB_FILENAME
    new_row = research._fetch_cases(new_db)[0]
    for key in ("league", "characterRef", "sourceHash", "sampleId"):
        assert old_row[key] == new_row[key]
    assert new_row["intakeRecordId"] != old_instance
    retry_old = research_workflow.cleanup_run(run_ref=old["runRef"], abandon_incomplete=True)
    assert retry_old["releaseOutcome"] == (
        "registration_binding_required" if origin == "legacy_queue" else "registration_mismatch"
    )
    assert ledger.registration_id(
        intake_path, league=new_row["league"], character_ref=new_row["characterRef"],
        source_hash=new_row["sourceHash"], sample_id=new_row["sampleId"],
    ) == new_row["intakeRecordId"]
    assert ledger.summary(intake_path)["byStatus"] == {"queued": 1}
    assert research_workflow.run_status(run_ref=replacement["runRef"])["queuedCount"] == 1


def _accept_hash(service, source_hash, *, scope="global_seed", context_changes=None, suffix="first",
                 mixed_states=False):
    record = _record()
    record["source_case_refs"] = ["source-hash:" + source_hash[:16]]
    record["knowledge_scope"] = scope
    context = {
        "sourceHash": source_hash, "sourceHashRef": record["source_case_refs"][0],
        "gamePatch": record["game_patch"], "passiveTreeVersion": record["passive_tree_version"],
        "knowledgeScope": scope,
    }
    context.update(context_changes or {})
    records = [record]
    if mixed_states:
        record["source_state_scope"] = "active_state"
        other = deepcopy(record)
        other["source_state_scope"] = "unknown"
        other["typed_payload"]["gearSubjects"] = ["gloves"]
        records.append(other)
    args = dict(
        run_ref="research-run:" + suffix, sample_id="case:hash", accept_attempt_key="raa-" + suffix,
        packet_safe_hash="packet-" + suffix, canonical_review_hash="review-" + suffix,
        contract_version="phase4-safe-review-v3", expected_origin_state="claimed",
        pattern_payload={"schema_version": 4}, deep_payload={"schema_version": 6, "deep_research_records": records},
        edge_payload={"schema_version": 4}, source_context=context,
    )
    result = service.accept_research_unit(**args)
    assert result["status"] == "accepted", result
    return result, args


def test_full_receipt_hash_skips_historical_source_and_backfills_target(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "memory.sqlite", graph_service=_graph_service())
    source_hash = hashlib.sha256(_code().encode()).hexdigest()
    result, args = _accept_hash(service, source_hash)
    replay = service.accept_research_unit(**args)
    assert replay["idempotentReplay"]
    assert replay["memoryRevision"] == result["memoryRevision"]
    assert research._studied_source_hashes(
        game_patch="0.5.4", passive_tree_version="tree-test", memory_db_path=service.db_path,
    ) == {source_hash}
    report = _queue(tmp_path, "online", _browser())
    assert report["queuedCount"] == 1
    assert report["intakeSkippedAlreadyStudied"] == 1
    assert report["intakePagesFetched"] == 2
    assert len(report["samples"]) == 1
    assert report["samples"][0]["sourceHashRef"] != "source-hash:" + source_hash[:16]
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        assert con.execute("SELECT count(*) FROM research_record_write_receipts").fetchone()[0] == 1
        assert con.execute("SELECT evidence_count FROM research_build_families").fetchone()[0] == 1
    finally:
        con.close()


@pytest.mark.parametrize("change", [
    "short_hash", "missing_hash", "wrong_hash", "wrong_patch", "wrong_tree", "local_scope",
    "legacy_provenance", "no_receipt", "missing_patch", "missing_tree",
])
def test_history_without_exact_public_transactional_identity_stays_unknown(tmp_path, change):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "memory.sqlite", graph_service=_graph_service())
    source_hash = hashlib.sha256(_code().encode()).hexdigest()
    changes = {
        "short_hash": {"sourceHash": source_hash[:16]}, "missing_hash": {"sourceHash": None},
        "wrong_hash": {"sourceHash": "f" * 64}, "wrong_patch": {"gamePatch": "0.5.5"},
        "wrong_tree": {"passiveTreeVersion": "other-tree"},
        "missing_patch": {"gamePatch": None}, "missing_tree": {"passiveTreeVersion": None},
    }.get(change, {})
    _accept_hash(service, source_hash, scope="local_user" if change == "local_scope" else "global_seed",
                 context_changes=changes)
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        if change == "legacy_provenance":
            con.execute("UPDATE research_record_write_receipts SET provenance='legacy_queue_backfill'")
        elif change == "no_receipt":
            con.execute("DELETE FROM research_record_write_receipts")
        con.commit()
    finally:
        con.close()
    assert research._studied_source_hashes(
        game_patch="0.5.4", passive_tree_version="tree-test", memory_db_path=service.db_path,
    ) == set()
    report = _queue(tmp_path, "online", _browser())
    assert report["queuedCount"] == 1 and report["intakeSkippedAlreadyStudied"] == 0


def test_receipt_version_is_not_relabelled_for_current_intake(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "memory.sqlite", graph_service=_graph_service())
    source_hash = hashlib.sha256(_code().encode()).hexdigest()
    _accept_hash(service, source_hash)
    assert research._studied_source_hashes(game_patch="0.5.5", memory_db_path=service.db_path) == set()
    assert research._studied_source_hashes(passive_tree_version="other-tree", memory_db_path=service.db_path) == set()


def test_accepted_unknown_diagnostics_dedupe_without_changing_gap_or_create_authority(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "memory.sqlite", graph_service=_graph_service())
    source_hash = hashlib.sha256(_code().encode()).hexdigest()
    accepted, args = _accept_hash(service, source_hash, mixed_states=True)
    followup_args = dict(
        db_path=tmp_path / "followups.sqlite", memory_db_path=service.db_path,
        run_ref=args["run_ref"], sample_id=args["sample_id"],
    )
    before = research_followups.inspect_followups(**followup_args)
    assert before["closureEligible"] is False
    family = accepted["deepRecordWrite"]["buildFamilyKeys"][0]
    query_args = dict(build_family_keys=[family], game_patch="0.5.4", passive_tree_version="tree-test",
                      detail_level="record", response_profile="create_compact")
    visible_before = service.query_research_memory("", **query_args)["deepResearchRecords"]
    assert len(visible_before) == 1 and visible_before[0]["sourceStateScope"] == "active_state"
    assert research._studied_source_hashes(
        game_patch="0.5.4", passive_tree_version="tree-test", memory_db_path=service.db_path,
    ) == {source_hash}
    assert research_followups.inspect_followups(**followup_args) == before
    visible_after = service.query_research_memory("", **query_args)["deepResearchRecords"]
    assert visible_after == visible_before
    with research_memory.mature_learning.connect(service.db_path) as con:
        assert con.execute(
            "SELECT count(*) FROM deep_research_records WHERE source_state_scope='unknown'"
        ).fetchone()[0] == 1


def test_known_history_does_not_block_explicit_local_input(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "memory.sqlite", graph_service=_graph_service())
    _accept_hash(service, hashlib.sha256(_code().encode()).hexdigest())
    source = tmp_path / "explicit-code.txt"
    source.write_text(_code(), encoding="utf-8")
    report = _queue(tmp_path, "local", _browser(), source_files=[source])
    assert report["queuedCount"] == 1
    assert report["intakeLedgerSummary"]["used"] is False


@pytest.mark.parametrize("scope", ["supplement", "full_case"])
def test_known_history_does_not_block_selected_same_source_revisit(tmp_path, scope):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "memory.sqlite", graph_service=_graph_service())
    _accept_hash(service, hashlib.sha256(_code().encode()).hexdigest())
    source = tmp_path / "explicit-code.txt"
    source.write_text(_code(), encoding="utf-8")
    original = _queue(tmp_path, "original", _browser(), source_files=[source])
    with research._connect_queue(tmp_path / "original" / research.QUEUE_DB_FILENAME) as con:
        con.execute("UPDATE cases SET status='accepted'")
    revisit = _queue(
        tmp_path, "revisit", _browser(), re_research_run_dir=tmp_path / "original",
        supplement_sample_ids=[original["samples"][0]["sampleId"]], re_research_scope=scope,
    )
    assert revisit["queuedCount"] == 1
    assert revisit["samples"][0]["sourceHashRef"] == original["samples"][0]["sourceHashRef"]


def test_unreadable_intake_ledger_fails_closed_before_fetch(tmp_path):
    (tmp_path / "intake.sqlite").write_bytes(b"not a SQLite ledger")
    browser = _browser()
    with pytest.raises(Exception, match="not a database"):
        _queue(tmp_path, "failed", browser)
    assert browser.urls == []


def test_release_compare_and_swap_rechecks_source_ownership_after_select(tmp_path, monkeypatch):
    intake = tmp_path / "intake.sqlite"
    identity = dict(league=LEAGUE, character_ref=ledger.character_ref("account", "character"),
                    source_hash="a" * 64, sample_id="case:original")
    ledger.record_case(intake, **identity)
    original_connect = sqlite3.connect
    mutated = False

    class RacingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            nonlocal mutated
            cursor = super().execute(sql, parameters)
            if not mutated and "SELECT id, status, source_hash, first_sample_id" in sql:
                row = cursor.fetchone()
                cursor.close()
                mutated = True
                with original_connect(intake) as writer:
                    writer.execute("UPDATE intake_records SET source_hash=? WHERE id=?", ("b" * 64, row[0]))
                return SimpleNamespace(fetchone=lambda: row)
            return cursor

    monkeypatch.setattr(ledger.sqlite3, "connect", lambda *args, **kwargs: original_connect(
        *args, **kwargs, factory=RacingConnection,
    ))
    assert ledger.release_queued_case(intake, **identity) == "concurrent_change"
    assert mutated
    with original_connect(intake) as con:
        assert con.execute("SELECT source_hash FROM intake_records").fetchone()[0] == "b" * 64


def test_legacy_schema_upgrade_serializes_concurrent_initializers(tmp_path, monkeypatch):
    intake = tmp_path / "legacy-intake.sqlite"
    original_connect = sqlite3.connect
    old_schema = ledger._SCHEMA_SQL.replace(
        "    requires_instance_binding INTEGER NOT NULL DEFAULT 0,\n", "",
    )
    with original_connect(intake) as con:
        con.executescript(old_schema)
        con.execute("INSERT INTO meta(key,value) VALUES('schema_version','1')")
        con.execute(
            "INSERT INTO intake_records(league,character_ref,source_hash,status,created_at,updated_at) "
            "VALUES('league-x','character-hash:legacy','legacy','accepted','original','original')"
        )
    start = threading.Barrier(2)

    class InitializingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql == "BEGIN IMMEDIATE":
                start.wait(10)
            if sql == "PRAGMA table_info(intake_records)":
                assert self.in_transaction
            return super().execute(sql, parameters)

    monkeypatch.setattr(ledger.sqlite3, "connect", lambda *args, **kwargs: original_connect(
        *args, **kwargs, factory=InitializingConnection,
    ))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(ledger.init_db, intake) for _ in range(2)]
        for future in futures:
            future.result(10)
    with original_connect(intake) as con:
        columns = [row[1] for row in con.execute("PRAGMA table_info(intake_records)")]
        assert columns.count("requires_instance_binding") == 1
        assert con.execute("SELECT status,requires_instance_binding FROM intake_records").fetchone() == ("accepted", 0)
        assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(ledger.SCHEMA_VERSION)


def test_empty_explicit_local_input_never_falls_through_to_unlocked_online_collection(tmp_path):
    source = tmp_path / "empty.txt"
    source.write_text("", encoding="utf-8")
    browser = _browser()
    report = _queue(tmp_path, "empty", browser, source_files=[source])
    assert report["queuedCount"] == 0 and report["status"] == "source_unavailable"
    assert report["intakeLedgerSummary"]["used"] is False
    assert browser.urls == []
