"""既有重验事件对深度知识的精确 hold：不改原记录或证据，不借旧回执恢复。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
import sqlite3

import pytest

from server.knowledge import mature_learning, physical_graph, research_contracts
from server.knowledge import research_memory, research_runtime
from test_patch_reviews import seeded


SOURCE_A = "case:la-safe"
SOURCE_B = "case:independent-safe"
HASH_A = "a" * 64
HASH_B = "b" * 64


def _row(con, record_id):
    return con.execute("SELECT * FROM deep_research_records WHERE record_id=?", (record_id,)).fetchone()


def _receipt(row, *, source=SOURCE_A, source_hash=HASH_A, revision=0, suffix="initial"):
    return {
        "receipt_ref": "rwr-" + research_runtime.stable_hash(suffix)[:20],
        "run_ref": "research-run:" + suffix,
        "sample_id": source,
        "accept_attempt_key": "raa-" + suffix,
        "packet_safe_hash": "packet-" + suffix,
        "canonical_review_hash": "review-" + suffix,
        "contract_version": research_contracts.SAFE_REVIEW_CONTRACT_VERSION,
        "expected_origin_state": "claimed",
        "acceptance_summary": {
            "sourceContext": {
                "sourceHashRef": source, "sourceHash": source_hash,
                "knowledgeScope": row["knowledge_scope"],
                "gamePatch": row["game_patch"],
                "passiveTreeVersion": row["passive_tree_version"],
                "pobVersionOrCommit": row["pob_version_or_commit"],
                "reResearchScope": "full_case",
            },
            "acceptanceMode": "clean", "researchCompletion": "complete",
            "completionScope": "case", "deferredCandidateCount": 0,
            "unresolvedDeepRecordMentionCount": 0, "caseCoverageGapCount": 0,
            "memoryRevisionAfter": revision,
            "supportCompatibility": {
                "contractVersion": physical_graph.SUPPORT_COMPATIBILITY_VERSION,
                "scope": "static_type_compatibility", "graphSnapshotId": "physical-graph-test",
                "records": [],
            },
        },
        "record_writes_json": [{
            "recordId": row["record_id"], "knowledgeScope": row["knowledge_scope"],
            "knowledgeKey": row["knowledge_key"], "afterProjectionHash": row["projection_hash"],
            "writtenSourceCaseRefs": [source], "sourceClaimKey": "default",
            "sourceGamePatch": row["game_patch"],
            "sourcePassiveTreeVersion": row["passive_tree_version"],
            "sourcePobVersionOrCommit": row["pob_version_or_commit"],
        }],
        "pattern_ids": "[]", "semantic_edge_ids": "[]", "provenance": "transactional",
        # Deliberately identical timestamps: revision order, not wall-clock order, governs release.
        "created_at": "2026-09-14T12:00:00+00:00",
    }


def _insert_receipt(con, receipt):
    values = dict(receipt)
    for key in ("acceptance_summary", "record_writes_json"):
        values[key] = json.dumps(values[key], ensure_ascii=False)
    keys = list(values)
    con.execute(
        f"INSERT INTO research_record_write_receipts({','.join(keys)}) "
        f"VALUES ({','.join('?' for _ in keys)})", tuple(values.values()),
    )


def _seed(tmp_path, *, original_receipt=True):
    service, payload, accepted = seeded(tmp_path)
    record_id = accepted["recordIds"][0]
    with closing(mature_learning.connect(service.db_path)) as con:
        row = _row(con, record_id)
        if original_receipt:
            _insert_receipt(con, _receipt(row, revision=research_runtime.get_memory_revision(con)))
            con.commit()
        request = {
            "target_kind": "deep_research_record", "target_id": record_id,
            "outcome": "needs_review", "expected_projection_hash": row["projection_hash"],
            "new_version_context": {key: row[key] for key in
                                    ("game_patch", "passive_tree_version", "pob_version_or_commit")},
            "safe_evidence_refs": ["review:support-contract-correction"],
            "affected_component_keys": [],
        }
    return service, payload, request


@pytest.mark.parametrize("outcome", ["needs_review", "invalidated"])
def test_hold_is_append_only_idempotent_and_preserves_record_and_evidence(tmp_path, outcome):
    service, _, request = _seed(tmp_path)
    request["outcome"] = outcome
    with closing(mature_learning.connect(service.db_path)) as con:
        before = dict(_row(con, request["target_id"]))
        evidence = [dict(row) for row in con.execute("SELECT * FROM deep_research_record_evidence")]
        revision = research_runtime.get_memory_revision(con)
    first = service.submit_revalidation_result(**request)
    again = service.submit_revalidation_result(**request)
    assert first["status"] == again["status"] == "accepted"
    assert first["eventId"] == again["eventId"]
    assert again["idempotentReplay"] is True
    with closing(mature_learning.connect(service.db_path)) as con:
        assert dict(_row(con, request["target_id"])) == before
        assert [dict(row) for row in con.execute("SELECT * FROM deep_research_record_evidence")] == evidence
        assert research_runtime.get_memory_revision(con) == revision + 1
        assert con.execute("SELECT count(*) FROM research_revalidation_events").fetchone()[0] == 1
        pending = research_memory.pending_hold_for_record(con, _row(con, request["target_id"]), SOURCE_A)
        assert pending["adoptionAllowed"] is False


@pytest.mark.parametrize("change,error", [
    ({"outcome": "still_valid"}, "invalid_deep_revalidation_outcome"),
    ({"outcome": "changed_scope"}, "invalid_deep_revalidation_outcome"),
    ({"expected_projection_hash": None}, "deep_revalidation_projection_required"),
    ({"expected_projection_hash": "0" * 64}, "deep_revalidation_projection_conflict"),
    ({"safe_evidence_refs": []}, "deep_revalidation_evidence_required"),
    ({"safe_evidence_refs": [""]}, "deep_revalidation_evidence_required"),
    ({"new_version_context": {}}, "deep_revalidation_original_version_required"),
    ({"affected_component_keys": ["skill:NotThisRecord"]}, "deep_revalidation_component_mismatch"),
])
def test_hold_rejects_unbound_requests_without_writing(tmp_path, change, error):
    service, _, request = _seed(tmp_path)
    result = service.submit_revalidation_result(**{**request, **change})
    assert result["errorCode"] == error
    with closing(mature_learning.connect(service.db_path)) as con:
        assert con.execute("SELECT count(*) FROM research_revalidation_events").fetchone()[0] == 0


def test_hold_resolves_default_database_for_both_lock_and_transaction(tmp_path, monkeypatch):
    service, _, request = _seed(tmp_path)
    path = service.db_path
    service.db_path = None
    monkeypatch.setattr(mature_learning, "mature_learning_path", lambda: path)
    original_lock_path = research_runtime.research_write_lock_path
    locked = []

    def lock_path(value):
        locked.append(value)
        return original_lock_path(value)

    monkeypatch.setattr(research_runtime, "research_write_lock_path", lock_path)
    result = service.submit_revalidation_result(**request)
    assert result["status"] == "accepted"
    assert locked == [path]
    with closing(mature_learning.connect(path)) as con:
        assert con.execute("SELECT count(*) FROM research_revalidation_events").fetchone()[0] == 1


def test_hold_requires_exact_original_version_and_current_projection(tmp_path):
    service, _, request = _seed(tmp_path)
    changed_version = {**request["new_version_context"], "game_patch": "0.5.5"}
    assert service.submit_revalidation_result(
        **{**request, "new_version_context": changed_version},
    )["errorCode"] == "deep_revalidation_version_conflict"
    with closing(mature_learning.connect(service.db_path)) as con:
        con.execute("UPDATE deep_research_records SET content='已经被另一项研究修订' WHERE record_id=?",
                    (request["target_id"],))
        con.commit()
    assert service.submit_revalidation_result(**request)["errorCode"] == "deep_revalidation_projection_conflict"


def test_event_insert_failure_rolls_back_revision(tmp_path):
    service, _, request = _seed(tmp_path)
    with closing(mature_learning.connect(service.db_path)) as con:
        before = research_runtime.get_memory_revision(con)
        con.execute(
            "CREATE TRIGGER reject_hold BEFORE INSERT ON research_revalidation_events "
            "BEGIN SELECT RAISE(ABORT, 'injected_event_failure'); END"
        )
        con.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected_event_failure"):
        service.submit_revalidation_result(**request)
    with closing(mature_learning.connect(service.db_path)) as con:
        assert research_runtime.get_memory_revision(con) == before
        assert con.execute("SELECT count(*) FROM research_revalidation_events").fetchone()[0] == 0


def test_concurrent_identical_requests_record_one_event(tmp_path):
    service, _, request = _seed(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.submit_revalidation_result(**request), range(2)))
    assert all(result["status"] == "accepted" for result in results)
    assert sorted(result["idempotentReplay"] for result in results) == [False, True]


def test_old_receipt_and_plain_proposal_do_not_release_hold_or_new_source(tmp_path):
    service, payload, request = _seed(tmp_path)
    service.submit_revalidation_result(**request)
    assert service.propose_deep_research_records(payload)["status"] == "accepted"
    other = deepcopy(payload)
    other["deep_research_records"][0]["source_case_refs"] = [SOURCE_B]
    other["deep_research_records"][0]["research_group_id"] = "research:independent-safe"
    assert service.propose_deep_research_records(other)["status"] == "accepted"
    with closing(mature_learning.connect(service.db_path)) as con:
        row = _row(con, request["target_id"])
        assert research_memory.pending_hold_for_record(con, row, SOURCE_A)
        assert research_memory.pending_hold_for_record(con, row, SOURCE_B)


@pytest.mark.parametrize("mutation", [
    "old_revision", "old_contract", "partial", "supplement", "ordinary_case", "other_hash",
    "other_record", "other_projection", "other_source", "other_branch", "other_pob", "legacy",
])
def test_inexact_or_incomplete_new_receipt_cannot_release_hold(tmp_path, mutation):
    service, _, request = _seed(tmp_path)
    held = service.submit_revalidation_result(**request)
    with closing(mature_learning.connect(service.db_path)) as con:
        row = _row(con, request["target_id"])
        receipt = _receipt(row, revision=held["memoryRevision"] + 1, suffix=mutation)
        summary = receipt["acceptance_summary"]
        context = summary["sourceContext"]
        write = receipt["record_writes_json"][0]
        if mutation == "old_revision":
            summary["memoryRevisionAfter"] = held["memoryRevision"]
        elif mutation == "old_contract":
            summary["supportCompatibility"]["contractVersion"] = "old"
        elif mutation == "partial":
            summary["deferredCandidateCount"] = 1
        elif mutation == "supplement":
            summary["completionScope"] = "supplement"
        elif mutation == "ordinary_case":
            context["reResearchScope"] = "case"
        elif mutation == "other_hash":
            context["sourceHash"] = HASH_B
        elif mutation == "other_record":
            write["recordId"] = "drr-other"
        elif mutation == "other_projection":
            write["afterProjectionHash"] = "0" * 64
        elif mutation == "other_source":
            context["sourceHashRef"] = SOURCE_B
            write["writtenSourceCaseRefs"] = [SOURCE_B]
        elif mutation == "other_branch":
            write["sourceClaimKey"] = "different"
        elif mutation == "other_pob":
            context["pobVersionOrCommit"] = "different"
        elif mutation == "legacy":
            receipt["provenance"] = "legacy"
        assert not research_memory.receipt_releases_pending_hold(con, receipt)
        _insert_receipt(con, receipt)
        assert research_memory.pending_hold_for_record(con, row, SOURCE_A)


def test_full_case_receipt_releases_only_its_original_source_and_invalidates_sql_cache(tmp_path):
    service, payload, request = _seed(tmp_path)
    other = deepcopy(payload)
    other["deep_research_records"][0]["source_case_refs"] = [SOURCE_B]
    other["deep_research_records"][0]["research_group_id"] = "research:independent-safe"
    assert service.propose_deep_research_records(other)["status"] == "accepted"
    with closing(mature_learning.connect(service.db_path)) as con:
        row = _row(con, request["target_id"])
        _insert_receipt(con, _receipt(row, source=SOURCE_B, source_hash=HASH_B, suffix="baseline-b"))
        con.commit()
    held = service.submit_revalidation_result(**request)
    with closing(mature_learning.connect(service.db_path)) as con:
        research_memory.register_deep_revalidation_sql(con)
        sql = "SELECT research_deep_revalidation_pending(?, ?)"
        assert con.execute(sql, (request["target_id"], SOURCE_A)).fetchone()[0] == 1
        row = _row(con, request["target_id"])
        receipt = _receipt(row, revision=held["memoryRevision"] + 1, suffix="full-a")
        assert research_memory.receipt_releases_pending_hold(con, receipt)
        _insert_receipt(con, receipt)
        assert con.execute(sql, (request["target_id"], SOURCE_A)).fetchone()[0] == 0
        assert con.execute(sql, (request["target_id"], SOURCE_B)).fetchone()[0] == 1
        assert research_memory.pending_hold_for_record(con, row)
        assert not research_memory.receipt_releases_pending_hold(con, receipt)


def test_missing_original_full_hash_is_never_fabricated_from_short_source_ref(tmp_path):
    service, _, request = _seed(tmp_path, original_receipt=False)
    held = service.submit_revalidation_result(**request)
    with closing(mature_learning.connect(service.db_path)) as con:
        row = _row(con, request["target_id"])
        receipt = _receipt(row, revision=held["memoryRevision"] + 1, suffix="new-unknown-source")
        assert not research_memory.receipt_releases_pending_hold(con, receipt)
        _insert_receipt(con, receipt)
        assert research_memory.pending_hold_for_record(con, row, SOURCE_A)


@pytest.mark.parametrize("late_source,late_branch", [(SOURCE_B, "default"), (SOURCE_A, "late-branch")])
def test_late_source_or_branch_stays_held_globally_and_is_not_released_in_seed(
    tmp_path, late_source, late_branch,
):
    from scripts import build_research_release_seed

    service, payload, request = _seed(tmp_path)
    held = service.submit_revalidation_result(**request)
    later = deepcopy(payload)
    later["deep_research_records"][0].update(
        source_case_refs=[late_source], source_claim_key=late_branch,
        research_group_id="research:late-source",
    )
    accepted = service.propose_deep_research_records(later)
    assert accepted["status"] == "accepted", accepted
    assert accepted["recordIds"] == [request["target_id"]]
    with closing(mature_learning.connect(service.db_path)) as con:
        row = _row(con, request["target_id"])
        receipt = _receipt(row, revision=held["memoryRevision"] + 10, suffix="only-original-a-rechecked")
        assert research_memory.receipt_releases_pending_hold(con, receipt)
        _insert_receipt(con, receipt)
        con.commit()
        if late_source == SOURCE_B:
            assert research_memory.pending_hold_for_record(con, row, SOURCE_A) is None
        assert research_memory.pending_hold_for_record(con, row, late_source)
        global_pending = research_memory.pending_hold_for_record(con, row)
        assert global_pending and global_pending["sourceCaseRefs"] == [late_source]
        assert con.execute(
            "SELECT research_deep_revalidation_pending(?, NULL)", (request["target_id"],),
        ).fetchone()[0] == 1
    seed = tmp_path / "held-source-seed.sqlite"
    with closing(sqlite3.connect(service.db_path)) as source, closing(sqlite3.connect(seed)) as target:
        source.backup(target)
    build_research_release_seed._prune_to_creator_safe_seed(seed, release_version="test")
    with closing(sqlite3.connect(seed)) as con:
        assert con.execute(
            "SELECT count(*) FROM deep_research_records WHERE record_id=?", (request["target_id"],),
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT count(*) FROM deep_research_record_evidence WHERE source_case_ref=?",
            (late_source,),
        ).fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM research_revalidation_events").fetchone()[0] == 0
    with closing(mature_learning.connect(service.db_path)) as con:
        assert research_memory.pending_hold_for_record(con, _row(con, request["target_id"]))
        assert con.execute("SELECT count(*) FROM research_revalidation_events").fetchone()[0] == 1


def test_hold_follows_same_projection_on_variant_id_but_not_corrected_content(tmp_path):
    service, _, request = _seed(tmp_path)
    service.submit_revalidation_result(**request)
    with closing(mature_learning.connect(service.db_path)) as con:
        row = dict(_row(con, request["target_id"]))
        row["record_id"] = "drr-same-projection-variant"
        assert research_memory.pending_hold_for_record(con, row, SOURCE_A)
        row["content"] = "该结论经本来源修订，改为精确模型范围并保留验证任务。"
        row["projection_hash"] = research_runtime.projection_hash(row)
        assert research_memory.pending_hold_for_record(con, row, SOURCE_A) is None
