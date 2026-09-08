"""R3b：逐缺口闭合、同快照证据、并发和追加历史的隔离回归。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
import sqlite3

import pytest

from server.knowledge import research_followups as followups
from server.knowledge import research_memory
from scripts import run_phase4_deep_review_acceptance as acceptance
from test_research_acceptance_diagnostics import _clean, _partial
from test_research_v3_contracts import _graph_service, _record


SOURCE_HASH = "a" * 64
SOURCE = "source-hash:" + SOURCE_HASH[:16]


@pytest.fixture
def case(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    params = {"db_path": tmp_path / "followups.sqlite", "memory_db_path": service.db_path,
              "run_ref": "research-run:followup-parent", "sample_id": "case:parent"}

    def accept(name, diagnostics=None, *, record_change=None, context_change=None, supplement=False):
        record = _record()
        record.update(source_case_refs=[SOURCE], content="资源恢复需要按实际条件逐项验证。")
        record.update(record_change or {})
        source = record["source_case_refs"][0]
        source_suffix = source.removeprefix("source-hash:")
        context = {"sourceHashRef": source, "sourceHash": source_suffix if len(source_suffix) == 64 else SOURCE_HASH,
                   "gamePatch": record["game_patch"],
                   "passiveTreeVersion": record["passive_tree_version"],
                   "pobVersionOrCommit": record["pob_version_or_commit"],
                   "knowledgeScope": record["knowledge_scope"],
                   "sourceSnapshotHash": "b" * 64,
                   "activeSets": {"skillSet": 1, "itemSet": 1, "passiveSpec": 1, "configSet": 1}}
        context.update(context_change or {})
        outcome = service.accept_research_unit(
            run_ref=f"research-run:followup-{name}", sample_id=f"case:{name}",
            accept_attempt_key="raa-" + name, packet_safe_hash="packet-" + name,
            canonical_review_hash="review-" + name, contract_version="phase4-safe-review-v3",
            expected_origin_state="claimed", pattern_payload={"schema_version": 4},
            deep_payload={"schema_version": 6, "deep_research_records": [record]},
            edge_payload={"schema_version": 4},
            acceptance_diagnostics=diagnostics if diagnostics is not None else _clean(),
            source_context=context, supplement=supplement,
        )
        assert outcome["status"] == "accepted", outcome
        return outcome

    parent = accept("parent", _partial())
    return params, service, accept, parent


def _status(case, **kwargs):
    return followups.inspect_followups(**case[0], **kwargs)


def _decision(gap, support, *, disposition="resolved"):
    return {"gapRef": gap["gapRef"], "disposition": disposition,
            "rationale": "已阅读新增记录并确认它覆盖该缺口的具体条件。",
            "supportingWriteReceiptRef": support["writeReceiptRef"],
            "supportingRecordIds": support["deepRecordWrite"]["recordIds"]}


def _submit(case, decisions, *, revision=0, request="request-1"):
    return followups.submit_followup_decisions(
        **case[0], expected_revision=revision, request_id=request, decisions=decisions
    )


def _coverage(case):
    return next(gap for gap in _status(case)["gaps"] if gap["kind"] == "coverage")


def _write_receipt(case, ref, *, summary=None, writes=None, fields=None):
    with closing(sqlite3.connect(case[0]["memory_db_path"])) as con, con:
        if summary is not None:
            con.execute("UPDATE research_record_write_receipts SET acceptance_summary=? WHERE receipt_ref=?",
                        (json.dumps(summary), ref))
        if writes is not None:
            con.execute("UPDATE research_record_write_receipts SET record_writes_json=? WHERE receipt_ref=?",
                        (json.dumps(writes), ref))
        for field, value in (fields or {}).items():
            assert field in {"provenance", "created_at"}
            con.execute(f"UPDATE research_record_write_receipts SET {field}=? WHERE receipt_ref=?", (value, ref))


def test_catalog_retains_each_gap_and_paginates_without_copying_candidate_prose(case):
    first = _status(case, limit=1)
    second = _status(case, offset=1, limit=1)
    assert first["total"] == 2
    assert first["nextOffset"] == 1 and second["nextOffset"] is None
    assert first["gaps"][0]["gapRef"] != second["gaps"][0]["gapRef"]
    assert first["revision"] == 0 and first["closureEligible"] is True
    assert first["sourceIdentity"]["sourceHashRef"] == SOURCE
    assert first["sourceIdentity"]["sourceHash"] == SOURCE_HASH
    assert first["sourceIdentity"]["sourceStateScopes"] == ["state_agnostic"]
    assert first["originalResearchCompletion"] == first["effectiveResearchCompletion"] == "needs_followup"
    assert "不应进入" not in json.dumps(first, ensure_ascii=False)
    assert _status(case, limit=1) == first


def test_closing_one_gap_never_closes_the_other_and_does_not_change_origin(case):
    parent_before = case[1].get_research_write_receipt(case[3]["writeReceiptRef"])
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    result = _submit(case, [_decision(_coverage(case), support)])
    assert result["status"] == "accepted", result
    assert result["openGapCount"] == 1 and result["closedGapCount"] == 1
    assert result["effectiveResearchCompletion"] == "needs_followup"
    assert result["originalResearchCompletion"] == "needs_followup"
    parent_after = case[1].get_research_write_receipt(case[3]["writeReceiptRef"])
    assert parent_after["acceptanceSummary"] == parent_before["acceptanceSummary"]


def test_all_explicit_decisions_can_complete_and_reopen_preserves_history(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    gaps = _status(case)["gaps"]
    result = _submit(case, [_decision(gap, support) for gap in gaps])
    assert result["effectiveResearchCompletion"] == "complete"
    assert result["originalResearchCompletion"] == "needs_followup"
    fingerprint = followups.state_fingerprint(case[0]["db_path"], case[0]["run_ref"])
    reopened = _submit(case, [{"gapRef": gaps[0]["gapRef"], "disposition": "reopen",
                              "rationale": "后续复核发现该条件仍需独立验证。"}], revision=1, request="reopen")
    assert reopened["openGapCount"] == 1 and reopened["revision"] == 2
    assert followups.state_fingerprint(case[0]["db_path"], case[0]["run_ref"]) != fingerprint
    events = followups.inspect_followup_events(**case[0], limit=2)
    assert events["total"] == 3 and events["nextOffset"] == 2
    assert all(event["disposition"] == "resolved" for event in events["events"])
    last = followups.inspect_followup_events(**case[0], offset=2)
    assert last["events"][0]["disposition"] == "reopen"


def test_replay_is_idempotent_and_request_reuse_conflicts(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    decision = _decision(_coverage(case), support)
    first = _submit(case, [decision])
    replay = _submit(case, [decision])
    assert replay == {**first, "idempotentReplay": True}
    changed = _submit(case, [{**decision, "rationale": "这是不同的处置正文。"}])
    assert changed["errorCode"] == "followup_request_conflict"
    assert _status(case)["eventCount"] == 1


def test_concurrent_cas_only_accepts_one_append(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    decision = _decision(_coverage(case), support)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda key: _submit(case, [decision], request=key), ["one", "two"]))
    assert sorted(result["status"] for result in results) == ["accepted", "rejected"]
    assert next(result for result in results if result["status"] == "rejected")["errorCode"] == "followup_revision_conflict"
    assert _status(case)["eventCount"] == 1


@pytest.mark.parametrize("record_change,context_change", [
    ({"source_case_refs": ["source-hash:" + "c" * 64]}, {}),
    ({"game_patch": "0.5.5"}, {}),
    ({"passive_tree_version": "tree-new"}, {}),
    ({"knowledge_scope": "global_seed"}, {}),
    ({}, {"sourceSnapshotHash": "c" * 64}),
    ({}, {"activeSets": {"skillSet": 2, "itemSet": 1, "passiveSpec": 1, "configSet": 1}}),
])
def test_changed_source_only_records_successor_and_keeps_gap_open(case, record_change, context_change):
    gap = _coverage(case)
    support = case[2]("successor", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}},
                      record_change=record_change, context_change=context_change)
    result = _submit(case, [_decision(gap, support)])
    assert result["errorCode"] == "followup_source_mismatch_use_successor_evidence", result
    successor = _submit(case, [_decision(gap, support, disposition="successor_evidence")], request="successor")
    assert successor["status"] == "accepted", successor
    assert successor["openGapCount"] == 2 and successor["closedGapCount"] == 0


@pytest.mark.parametrize("coverage,disposition", [("evidence_missing", "resolved"), ("covered", "not_applicable"), ("not_applicable", "resolved")])
def test_coverage_disposition_requires_corresponding_new_typed_coverage(case, coverage, disposition):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": coverage}})
    result = _submit(case, [_decision(_coverage(case), support, disposition=disposition)])
    assert result["errorCode"] == "followup_support_coverage_unproven"


def test_not_applicable_with_new_evidence_is_an_explicit_close(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "not_applicable"}})
    result = _submit(case, [_decision(_coverage(case), support, disposition="not_applicable")])
    assert result["status"] == "accepted" and result["closedGapCount"] == 1


def test_same_receipt_cannot_support_itself(case):
    result = _submit(case, [_decision(_coverage(case), case[3])])
    assert result["errorCode"] == "followup_support_must_be_later"


@pytest.mark.parametrize("fields,error", [
    ({"created_at": "2000-01-01T00:00:00+00:00"}, "followup_support_must_be_later"),
    ({"created_at": "invalid"}, "followup_support_must_be_later"),
    ({"created_at": "2029-01-01T00:00:00"}, "followup_support_must_be_later"),
    ({"provenance": "legacy_cleanup_backfill"}, "followup_support_identity_incomplete"),
])
def test_support_requires_transactional_later_receipt(case, fields, error):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    _write_receipt(case, support["writeReceiptRef"], fields=fields)
    assert _submit(case, [_decision(_coverage(case), support)])["errorCode"] == error


def test_exact_written_projection_does_not_follow_a_later_record_head(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    gap = _coverage(case)
    case[2]("later-revision", record_change={"content": "后续修订改变原结论，旧支持回执不再授权闭合。"})
    result = _submit(case, [_decision(gap, support)])
    assert result["errorCode"] == "followup_support_projection_stale", result


def test_closed_gap_effectively_reopens_if_support_is_revised(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    result = _submit(case, [_decision(_coverage(case), support)])
    assert result["closedGapCount"] == 1
    case[2]("later-revision", record_change={"content": "新条件需要重新验证，不能继续沿用旧证据。"})
    state = _status(case)
    assert state["openGapCount"] == 2
    stale = next(gap for gap in state["gaps"] if gap.get("closureEvidenceStatus") == "stale")
    assert stale["disposition"] == "resolved" and stale["status"] == "open"
    assert state["revision"] == 1 and state["eventCount"] == 1


def test_receipt_mutation_after_closure_invalidates_evidence_without_erasing_event(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    assert _submit(case, [_decision(_coverage(case), support)])["status"] == "accepted"
    receipt = case[1].get_research_write_receipt(support["writeReceiptRef"])
    _write_receipt(case, support["writeReceiptRef"], summary={**receipt["acceptanceSummary"], "extra": True})
    state = _status(case)
    assert state["closedGapCount"] == 0
    assert next(gap for gap in state["gaps"] if gap["kind"] == "coverage")["reopenReason"] == "followup_support_receipt_changed"


def test_origin_mutation_is_detected_and_cannot_replace_gap_catalog(case):
    state = _status(case)
    _write_receipt(case, case[3]["writeReceiptRef"], summary=_clean())
    result = _status(case)
    assert result["errorCode"] == "followup_origin_receipt_changed"
    with closing(sqlite3.connect(case[0]["db_path"])) as con:
        assert con.execute("SELECT COUNT(*) FROM followup_gaps").fetchone()[0] == state["total"]


def test_record_not_in_support_mapping_cannot_be_borrowed(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    decision = _decision(_coverage(case), support)
    decision["supportingRecordIds"] = ["drr-" + "0" * 16]
    assert _submit(case, [decision])["errorCode"] == "followup_support_record_not_written"


def test_changed_source_claim_binding_cannot_support_closure(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    with closing(sqlite3.connect(case[0]["memory_db_path"])) as con, con:
        con.execute("UPDATE deep_research_record_evidence SET binding_issue='record_projection_mismatch'")
    result = _submit(case, [_decision(_coverage(case), support)])
    assert result["errorCode"] == "followup_support_projection_stale"


def test_unresolved_gap_requires_original_record_source_state(case):
    receipt = case[1].get_research_write_receipt(case[3]["writeReceiptRef"])
    summary = {**receipt["acceptanceSummary"], "unresolvedDeepRecordMentionCount": 1,
               "unresolvedComponentGapSummaries": [{"acceptedRecordIndex": 0, "unresolvedComponentIndex": 0}]}
    _write_receipt(case, case[3]["writeReceiptRef"], summary=summary)
    gap = next(gap for gap in _status(case)["gaps"] if gap["kind"] == "unresolved_component")
    support = case[2]("repair", record_change={"source_state_scope": "active_state"})
    assert _submit(case, [_decision(gap, support)])["errorCode"] == "followup_source_state_mismatch"


def test_missing_diagnostics_produce_unknown_gap_requiring_a_complete_new_case(case):
    receipt = case[1].get_research_write_receipt(case[3]["writeReceiptRef"])
    _write_receipt(case, case[3]["writeReceiptRef"], summary={"sourceContext": receipt["acceptanceSummary"]["sourceContext"]})
    gap = _status(case)["gaps"][0]
    assert gap["kind"] == "unknown"
    partial = case[2]("partial", _partial())
    result = _submit(case, [_decision(gap, partial)])
    assert result["errorCode"] == "followup_complete_acceptance_required"
    clean = case[2]("full", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    assert _submit(case, [_decision(gap, clean)])["effectiveResearchCompletion"] == "complete"


def test_legacy_missing_immutable_state_cannot_be_promoted_by_caller_context(case):
    receipt = case[1].get_research_write_receipt(case[3]["writeReceiptRef"])
    writes = deepcopy(receipt["writtenMapping"])
    for write in writes:
        write.pop("sourceStateScope")
    _write_receipt(case, case[3]["writeReceiptRef"], writes=writes)
    state = _status(case, source_context={"sourceStateScope": "state_agnostic"})
    assert state["closureEligible"] is False and state["closureIneligibleReason"]
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    assert _submit(case, [_decision(_coverage(case), support)])["errorCode"] == "followup_origin_identity_incomplete"


def test_counts_without_details_remain_explicit_aggregate_gaps(case):
    receipt = case[1].get_research_write_receipt(case[3]["writeReceiptRef"])
    summary = {**receipt["acceptanceSummary"], "deferredCandidateCount": 3,
               "unresolvedDeepRecordMentionCount": 2, "unkeyedDeepRecordCount": 1,
               "unresolvedUniqueComponentCount": 1, "caseCoverageGapCount": 2}
    _write_receipt(case, case[3]["writeReceiptRef"], summary=summary)
    gaps = _status(case)["gaps"]
    aggregate = {gap["countField"]: gap["count"] for gap in gaps if gap["kind"] == "aggregate"}
    assert aggregate == {"deferredCandidateCount": 2, "unresolvedDeepRecordMentionCount": 2,
                         "unkeyedDeepRecordCount": 1, "unresolvedUniqueComponentCount": 1,
                         "caseCoverageGapCount": 1}


@pytest.mark.parametrize("rationale", ["", "x" * 601, "<PathOfBuilding><Build/></PathOfBuilding>", "https://pobb.in/abcdef"])
def test_unsafe_or_unbounded_rationale_does_not_enter_ledger(case, rationale):
    gap = _coverage(case)
    before = followups.state_fingerprint(case[0]["db_path"], case[0]["run_ref"])
    result = _submit(case, [{"gapRef": gap["gapRef"], "disposition": "reopen", "rationale": rationale}])
    assert result["status"] == "rejected"
    assert followups.state_fingerprint(case[0]["db_path"], case[0]["run_ref"]) == before


def test_batch_validation_is_atomic_when_one_gap_fails(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    decisions = [_decision(_coverage(case), support), {"gapRef": "rgap-" + "0" * 24,
                 "disposition": "reopen", "rationale": "不存在的原案缺口不能插入。"}]
    assert _submit(case, decisions)["errorCode"] == "followup_gap_not_in_origin"
    assert _status(case)["eventCount"] == 0 and _status(case)["revision"] == 0


def test_unknown_diagnostics_cannot_be_closed_by_clean_supplement(case):
    receipt = case[1].get_research_write_receipt(case[3]["writeReceiptRef"])
    _write_receipt(case, case[3]["writeReceiptRef"], summary={"sourceContext": receipt["acceptanceSummary"]["sourceContext"]})
    gap = _status(case)["gaps"][0]
    supplement = case[2]("supplement", _clean(), supplement=True,
                         record_change={"content": "本次只补录局部恢复条件，不表示整案已全部完成。"})
    assert _submit(case, [_decision(gap, supplement)])["errorCode"] == "followup_complete_acceptance_required"


def test_idempotent_replay_rechecks_effective_state_after_support_revision(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    decisions = [_decision(_coverage(case), support)]
    assert _submit(case, decisions)["closedGapCount"] == 1
    case[2]("revision", record_change={"content": "后来修订导致旧支持失效。"})
    replay = _submit(case, decisions)
    assert replay["idempotentReplay"] is True and replay["closedGapCount"] == 0
    assert replay["eventCount"] == 1


def test_mixed_immutable_source_states_remain_distinct(case):
    receipt = case[1].get_research_write_receipt(case[3]["writeReceiptRef"])
    writes = deepcopy(receipt["writtenMapping"])
    alternate = {**writes[0], "sourceStateScope": "alternate_weapon_state"}
    _write_receipt(case, case[3]["writeReceiptRef"], writes=[*writes, alternate])
    state = _status(case)
    assert state["closureEligible"] is True
    assert state["sourceIdentity"]["sourceStateScopes"] == ["alternate_weapon_state", "state_agnostic"]
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    assert _submit(case, [_decision(_coverage(case), support)])["status"] == "accepted"


def test_changed_gap_catalog_cannot_drop_a_persisted_gap(case):
    _status(case)
    with closing(sqlite3.connect(case[0]["db_path"])) as con, con:
        con.execute("DELETE FROM followup_gaps WHERE location='deferred/0'")
    assert _status(case)["errorCode"] == "followup_gap_catalog_changed"


def test_missing_memory_is_reported_without_creating_a_database(tmp_path):
    params = {"db_path": tmp_path / "runtime" / "followups.sqlite",
              "memory_db_path": tmp_path / "missing.sqlite", "run_ref": "research-run:none", "sample_id": "case:none"}
    assert followups.inspect_followups(**params)["errorCode"] == "followup_memory_missing"
    assert not params["db_path"].exists() and not params["memory_db_path"].exists()
    assert followups.state_fingerprint(params["db_path"], params["run_ref"])
    assert not params["db_path"].exists()


@pytest.mark.parametrize("disposition", [[], {}, None, True])
def test_untyped_disposition_is_rejected_without_an_exception(case, disposition):
    result = _submit(case, [{"gapRef": _coverage(case)["gapRef"], "disposition": disposition,
                            "rationale": "必须使用规定的处置类型。"}])
    assert result["errorCode"] == "followup_disposition_invalid"


def test_same_short_prefix_but_different_complete_hash_only_allows_successor(case):
    gap = _coverage(case)
    support = case[2]("prefix-collision", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}},
                      context_change={"sourceHash": "a" * 16 + "c" * 48})
    rejected = _submit(case, [_decision(gap, support)])
    assert rejected["errorCode"] == "followup_source_mismatch_use_successor_evidence"
    accepted = _submit(case, [_decision(gap, support, disposition="successor_evidence")])
    assert accepted["status"] == "accepted" and accepted["closedGapCount"] == 0


def test_legacy_short_reference_without_complete_hash_cannot_be_filled_from_caller(case):
    receipt = case[1].get_research_write_receipt(case[3]["writeReceiptRef"])
    summary = deepcopy(receipt["acceptanceSummary"])
    summary["sourceContext"].pop("sourceHash")
    _write_receipt(case, case[3]["writeReceiptRef"], summary=summary)
    status = _status(case, source_context={"sourceHash": SOURCE_HASH})
    assert status["closureEligible"] is False
    assert status["sourceIdentity"]["sourceHashRef"] == SOURCE
    assert "sourceHash" not in status["sourceIdentity"]
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    assert _submit(case, [_decision(_coverage(case), support)])["errorCode"] == "followup_origin_identity_incomplete"


@pytest.mark.parametrize("source_hash", ["b" * 64, "a" * 16, "unknown"])
def test_short_reference_must_match_immutable_complete_hash(case, source_hash):
    receipt = case[1].get_research_write_receipt(case[3]["writeReceiptRef"])
    summary = deepcopy(receipt["acceptanceSummary"])
    summary["sourceContext"]["sourceHash"] = source_hash
    _write_receipt(case, case[3]["writeReceiptRef"], summary=summary)
    assert _status(case)["errorCode"] == "followup_source_identity_conflict"


def test_complete_legacy_reference_can_match_normal_short_reference_without_rewriting_it(case):
    legacy = case[2]("legacy", _partial(), record_change={"source_case_refs": ["source-hash:" + SOURCE_HASH]},
                     context_change={"sourceHash": None})
    params = {**case[0], "run_ref": "research-run:followup-legacy", "sample_id": "case:legacy"}
    state = followups.inspect_followups(**params)
    assert state["closureEligible"] is True and state["sourceIdentity"]["sourceHash"] == SOURCE_HASH
    assert state["sourceIdentity"]["sourceHashRef"] == "source-hash:" + SOURCE_HASH
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}})
    before = case[1].get_research_write_receipt(legacy["writeReceiptRef"])
    closed = followups.submit_followup_decisions(
        **params, expected_revision=0, request_id="alias-close",
        decisions=[_decision(gap, support) for gap in state["gaps"]],
    )
    assert closed["effectiveResearchCompletion"] == "complete", closed
    after = case[1].get_research_write_receipt(legacy["writeReceiptRef"])
    assert before["writtenMapping"] == after["writtenMapping"]
    assert after["writtenMapping"][0]["writtenSourceCaseRefs"] == ["source-hash:" + SOURCE_HASH]


def test_support_short_reference_without_full_hash_is_not_sufficient(case):
    support = case[2]("repair", {**_clean(), "caseCoverage": {"resourceDefense": "covered"}},
                      context_change={"sourceHash": None})
    assert _submit(case, [_decision(_coverage(case), support)])["errorCode"] == "followup_support_identity_incomplete"


@pytest.mark.parametrize("kind", ["unresolved_component", "missing_knowledge_identity"])
def test_legacy_ordinal_diagnostics_require_complete_case_instead_of_clean_supplement(case, kind):
    diagnostics = acceptance._acceptance_completion_diagnostics(
        accepted_record_summaries=[{
            "recordKind": "gear_synergy", "unresolvedComponents": [
                {"candidateName": "待解析组件", "resolverQuery": "未解析关联"}
            ] if kind == "unresolved_component" else [],
        }],
        deferred=[{"reason": "missing_knowledge_identity", "candidateKind": "deep_research_record",
                   "recordKind": "resource_engine"}] if kind == "missing_knowledge_identity" else [],
        case_coverage={"resourceDefense": "covered"},
    )
    case[2]("located", diagnostics)
    params = {**case[0], "run_ref": "research-run:followup-located", "sample_id": "case:located"}
    state = followups.inspect_followups(**params)
    assert state["total"] == 1 and state["openGapCount"] == 1, state
    assert state["gaps"][0]["kind"] == ("unresolved_component" if kind == "unresolved_component" else "deferred")
    supplement = case[2]("supplement", _clean(), supplement=True,
                         record_change={"content": "本次定向补录已修复这项有明确位置的条件缺口。"})
    result = followups.submit_followup_decisions(
        **params, expected_revision=0, request_id="close-located-gap",
        decisions=[_decision(state["gaps"][0], supplement)],
    )
    assert result["errorCode"] == "followup_complete_acceptance_required", result
    complete = case[2]("complete", _clean())
    result = followups.submit_followup_decisions(
        **params, expected_revision=0, request_id="close-by-complete-case",
        decisions=[_decision(state["gaps"][0], complete)],
    )
    if kind == "unresolved_component":
        assert result["errorCode"] == "followup_target_identity_missing", result
        result = followups.submit_followup_decisions(
            **params, expected_revision=0, request_id="not-applicable-by-complete-case",
            decisions=[_decision(state["gaps"][0], complete, disposition="not_applicable")],
        )
    assert result["effectiveResearchCompletion"] == "complete", result
    assert result["originalResearchCompletion"] == "needs_followup"


@pytest.mark.parametrize("count_field,summary", [
    ("unresolvedUniqueComponentCount", {
        "unresolvedDeepRecordMentionCount": 2, "unresolvedUniqueComponentCount": 1,
        "unresolvedComponentGapSummaries": [{"acceptedRecordIndex": 0, "unresolvedComponentIndex": 0}],
    }),
    ("unkeyedDeepRecordCount", {
        "deferredCandidateCount": 2, "unkeyedDeepRecordCount": 2,
        "deferredGapSummaries": [{"diagnosticIndex": 0, "reason": "missing_knowledge_identity"}],
    }),
])
def test_incompletely_located_secondary_counts_keep_remainder_and_require_full_case(case, count_field, summary):
    case[2]("incomplete", {**_clean(), **summary, "acceptanceMode": "partial_with_deferred"})
    params = {**case[0], "run_ref": "research-run:followup-incomplete", "sample_id": "case:incomplete"}
    state = followups.inspect_followups(**params)
    gap = next(gap for gap in state["gaps"] if gap.get("countField") == count_field)
    assert gap["count"] == 1
    supplement = case[2]("supplement", _clean(), supplement=True,
                         record_change={"content": "补录只证明局部修复，缺失定位的计数不能由它整体关闭。"})
    result = followups.submit_followup_decisions(
        **params, expected_revision=0, request_id="close-unknown-remainder", decisions=[_decision(gap, supplement)],
    )
    assert result["errorCode"] == "followup_complete_acceptance_required"


def _component_record(*, resolved=False, another_missing=False):
    record = _record()
    record["source_case_refs"] = [SOURCE]
    record["component_mentions"].append({
        "candidate_name": "Blood Mage", "role": "ascendancy_shell", "scope": "player",
        "resolver_query": "ascendancy:witch:blood_mage", "expected_node_types": ["ascendancy"],
        "component_key": "ascendancy:witch:blood_mage" if resolved else None,
        "resolution_status": "resolved" if resolved else "missing",
    })
    if resolved:
        record["component_keys"].append("ascendancy:witch:blood_mage")
    if another_missing:
        record["component_mentions"].append({
            "candidate_name": "另一项未解析组件", "role": "gear_base", "scope": "player",
            "resolver_query": "item:UnresolvedOther", "expected_node_types": ["item"],
            "component_key": None, "resolution_status": "missing",
        })
    return record


def _component_diagnostics(record):
    return acceptance._acceptance_completion_diagnostics(
        accepted_record_summaries=[{
            "recordKind": record["record_kind"],
            "unresolvedComponents": [
                {"candidateName": mention["candidate_name"], "resolverQuery": mention["resolver_query"]}
                for mention in record["component_mentions"] if not mention["component_key"]
            ],
        }],
        accepted_records=[record], deferred=[], case_coverage={},
    )


def _subject_origin(case, record, diagnostics=None):
    case[2]("subject", diagnostics or _component_diagnostics(record),
            record_change={**record, "source_case_refs": [SOURCE]})
    params = {**case[0], "run_ref": "research-run:followup-subject", "sample_id": "case:subject"}
    return params, followups.inspect_followups(**params)


def _close_subject(params, gap, support, *, disposition="resolved"):
    return followups.submit_followup_decisions(
        **params, expected_revision=0, request_id="close-subject",
        decisions=[_decision(gap, support, disposition=disposition)],
    )


@pytest.mark.parametrize("report_clean", [False, True])
def test_same_missing_component_cannot_close_even_with_falsely_clean_diagnostics(case, report_clean):
    record = _component_record()
    params, state = _subject_origin(case, record)
    support = case[2]("still-missing", _clean() if report_clean else _component_diagnostics(record),
                      record_change=record)
    result = _close_subject(params, state["gaps"][0], support)
    assert result["errorCode"] == (
        "followup_component_still_unresolved" if report_clean else "followup_target_still_unresolved"
    ), result
    after = followups.inspect_followups(**params)
    assert after["eventCount"] == 0 and after["openGapCount"] == 1


def test_resolved_component_can_close_while_another_component_remains_missing(case):
    record = _component_record(another_missing=True)
    params, state = _subject_origin(case, record)
    repaired = _component_record(resolved=True, another_missing=True)
    support = case[2]("component-repair", _component_diagnostics(repaired),
                      record_change=repaired, supplement=True)
    target = next(gap for gap in state["gaps"] if gap["unresolvedComponentIndex"] == 0)
    result = _close_subject(params, target, support)
    assert result["status"] == "accepted", result
    assert result["openGapCount"] == 1 and result["closedGapCount"] == 1
    assert support["researchCompletion"] == "needs_followup"


@pytest.mark.parametrize("change", [{"title": "另一主题"}, {"conditions": ["只有另一种条件成立"]},
                                   {"source_claim_key": "alternative"}])
def test_component_resolution_in_different_condition_needs_complete_case(case, change):
    record = _component_record()
    params, state = _subject_origin(case, record)
    repaired = {**_component_record(resolved=True), **change}
    support = case[2]("wrong-branch", _component_diagnostics(repaired),
                      record_change=repaired, supplement=True)
    assert _close_subject(params, state["gaps"][0], support)["errorCode"] == "followup_target_resolution_unproven"
    complete = case[2]("full-branch-review", _component_diagnostics(repaired), record_change=repaired)
    assert _close_subject(params, state["gaps"][0], complete)["effectiveResearchCompletion"] == "complete"


def _deferred_diagnostics(record):
    candidate = {
        "title": record["title"], "recordKind": record["record_kind"], "sampleId": "sample:deferred",
        "conditions": record["conditions"], "failureConditions": record["failure_conditions"],
        "sourceStateScope": record["source_state_scope"], "components": record["component_mentions"],
    }
    return acceptance._acceptance_completion_diagnostics(
        accepted_record_summaries=[], accepted_records=[], candidate_reviews=[candidate],
        deferred=[{"titleZh": candidate["title"], "recordKind": candidate["recordKind"],
                   "sampleId": candidate["sampleId"], "candidateKind": "deep_research_record",
                   "reason": "invalid_schema"}], case_coverage={},
    )


def test_same_deferred_candidate_cannot_close_by_later_partial_receipt(case):
    record = _record()
    diagnostics = _deferred_diagnostics(record)
    params, state = _subject_origin(case, record, diagnostics)
    support = case[2]("deferred-still-missing", diagnostics)
    assert _close_subject(params, state["gaps"][0], support)["errorCode"] == "followup_target_still_unresolved"


def test_typed_accepted_subject_can_close_deferred_while_other_gap_remains(case):
    record = _record()
    params, state = _subject_origin(case, record, _deferred_diagnostics(record))
    support = case[2]("deferred-repaired", {
        **_clean(), "acceptanceMode": "partial_with_deferred",
        "caseCoverageGapCount": 1, "caseCoverage": {"supports": "evidence_missing"},
    }, supplement=True)
    result = _close_subject(params, state["gaps"][0], support)
    assert result["effectiveResearchCompletion"] == "complete", result
    assert support["researchCompletion"] == "needs_followup"


def test_located_not_applicable_requires_full_case_and_remains_available(case):
    record = _component_record()
    params, state = _subject_origin(case, record)
    support = case[2]("not-applicable-supplement", _clean(), supplement=True)
    rejected = _close_subject(params, state["gaps"][0], support, disposition="not_applicable")
    assert rejected["errorCode"] == "followup_complete_acceptance_required"
    complete = case[2]("not-applicable-complete", _clean())
    result = _close_subject(params, state["gaps"][0], complete, disposition="not_applicable")
    assert result["effectiveResearchCompletion"] == "complete", result


@pytest.mark.parametrize("change", [{}, {"title": "完整复核后的主题"},
                                   {"conditions": ["完整复核后的适用条件"]}])
def test_complete_case_cannot_resolve_component_omitted_from_support_records(case, change):
    params, state = _subject_origin(case, _component_record())
    without_target = {**_record(), **change}
    support = case[2]("target-omitted", _component_diagnostics(without_target),
                      record_change={**without_target, "source_case_refs": [SOURCE]})
    result = _close_subject(params, state["gaps"][0], support)
    assert result["errorCode"] == "followup_target_resolution_unproven", result
    after = followups.inspect_followups(**params)
    assert after["eventCount"] == 0 and after["openGapCount"] == 1
    explicit = _close_subject(params, state["gaps"][0], support, disposition="not_applicable")
    assert explicit["effectiveResearchCompletion"] == "complete", explicit


def test_complete_case_cannot_replace_component_identity_with_same_display_name(case):
    params, state = _subject_origin(case, _component_record())
    repaired = _component_record(resolved=True)
    repaired["component_mentions"][1]["resolver_query"] = "Blood Mage"
    support = case[2]("different-component-declaration", _component_diagnostics(repaired),
                      record_change=repaired)
    result = _close_subject(params, state["gaps"][0], support)
    assert result["errorCode"] == "followup_target_resolution_unproven", result


def test_legacy_component_gap_without_identity_cannot_infer_resolution_from_clean_case(case):
    original = _component_record()
    diagnostics = _component_diagnostics(original)
    for gap in diagnostics["unresolvedComponentGapSummaries"]:
        gap.pop("componentSubjectHash")
        gap.pop("recordSubjectHash")
    params, state = _subject_origin(case, original, diagnostics)
    repaired = _component_record(resolved=True)
    support = case[2]("legacy-clean-review", _component_diagnostics(repaired), record_change=repaired)
    result = _close_subject(params, state["gaps"][0], support)
    assert result["errorCode"] == "followup_target_identity_missing", result
    explicit = _close_subject(params, state["gaps"][0], support, disposition="not_applicable")
    assert explicit["effectiveResearchCompletion"] == "complete", explicit
