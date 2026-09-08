"""Create 的 Family 覆盖、精确深读和持久分页回执必须使用同一资格。"""

from copy import deepcopy
import json

import pytest

from server import main
from server.generation import progression_provenance
from server.knowledge import mature_learning, research_contracts, research_memory
from test_patch_reviews import query, seeded


def _two_records(tmp_path):
    service, payload, first = seeded(tmp_path)
    second_payload = deepcopy(payload)
    second_payload["deep_research_records"][0].update(
        record_kind="mechanic_chain",
        title="配套资源机制的独立条件",
        content="配套资源机制需要独立恢复来源，单体场景必须验证持续支付条件。",
    )
    second = service.propose_deep_research_records(second_payload)
    assert second["status"] == "accepted", second
    first_id, second_id = first["recordIds"][0], second["recordIds"][0]
    assert first_id != second_id
    return service, first["buildFamilyKeys"][0], first_id, second_id


def _pages(service, raw):
    page = service.start_retrieval_session(
        main._compact_create_research_response(raw),
        response_profile="create_compact", run_ref=None, claim_ref=None,
    )
    assert page.get("retrieval"), page
    pages = [page]
    while not page["retrieval"]["complete"]:
        page = service.continue_retrieval_session(page["retrieval"]["nextCursor"])
        assert page.get("retrieval"), page
        pages.append(page)
    return pages


@pytest.mark.parametrize(
    "change",
    ["needs_revalidation", "superseded", "unsupported_availability", "future_schema"],
)
def test_create_coverage_contains_only_readable_authorizing_records(tmp_path, change):
    service, family, readable_id, excluded_id = _two_records(tmp_path)
    con = mature_learning.connect(service.db_path)
    try:
        if change == "needs_revalidation":
            con.execute(
                "UPDATE deep_research_records SET status='needs_revalidation' WHERE record_id=?",
                (excluded_id,),
            )
        elif change == "superseded":
            con.execute(
                "UPDATE deep_research_records SET superseded_by_id=? WHERE record_id=?",
                (readable_id, excluded_id),
            )
        elif change == "future_schema":
            con.execute(
                "UPDATE deep_research_records SET record_schema_version=3 WHERE record_id=?",
                (excluded_id,),
            )
        else:
            row = con.execute(
                "SELECT typed_payload FROM deep_research_records WHERE record_id=?", (excluded_id,)
            ).fetchone()
            typed = json.loads(row["typed_payload"])
            typed["availability"] = "unsupported_future_availability"
            con.execute(
                "UPDATE deep_research_records SET typed_payload=? WHERE record_id=?",
                (json.dumps(typed), excluded_id),
            )
        con.commit()
    finally:
        con.close()

    result = query(service, family, detail_level="record", response_profile="create_compact")
    readable = {record["recordId"] for record in result["deepResearchRecords"]}
    assert readable == {readable_id}
    coverage = result["familyRecordCoverage"][0]
    assert coverage["eligibleRecordCount"] == len(readable)
    assert set(coverage["requiredDeepReadRecordIds"]) <= readable
    assert not any(row["recordId"] == excluded_id for row in result["familyRecordIndex"])
    assert not any(row["evidenceRef"] == excluded_id for row in result["familyPremiseCatalog"])
    assert coverage["excludedRecordCount"] == (0 if change == "superseded" else 1)


def test_full_research_keeps_revalidation_record_available_for_diagnosis(tmp_path):
    service, family, _, stale_id = _two_records(tmp_path)
    con = mature_learning.connect(service.db_path)
    try:
        con.execute(
            "UPDATE deep_research_records SET status='needs_revalidation' WHERE record_id=?",
            (stale_id,),
        )
        con.commit()
    finally:
        con.close()
    diagnostic = query(service, family, detail_level="record", record_ids=[stale_id])
    assert [record["recordId"] for record in diagnostic["deepResearchRecords"]] == [stale_id]
    authorizing = query(
        service, family, detail_level="record", record_ids=[stale_id],
        response_profile="create_compact",
    )
    assert authorizing["deepResearchRecords"] == []


def test_every_delivered_coverage_page_is_preserved_in_its_trusted_receipt(tmp_path, monkeypatch):
    service, family, _, _ = _two_records(tmp_path)
    raw = query(service, family, detail_level="summary", limit=1, response_profile="create_compact")
    # The transport envelope must force a split without manufacturing oversized records.
    compact_bytes = len(json.dumps(main._compact_create_research_response(raw), ensure_ascii=False).encode("utf-8"))
    monkeypatch.setattr(research_contracts, "RESEARCH_QUERY_RESPONSE_BUDGET_BYTES", compact_bytes)
    pages = _pages(service, raw)
    assert len(pages) > 1
    assert any(page["familyRecordCoverage"] for page in pages)
    for page in pages:
        receipt = service.read_query_receipt(page["dedupeQueryRef"])
        assert receipt is not None
        assert receipt["result"]["familyRecordCoverage"] == page["familyRecordCoverage"]
    assert {
        record_id
        for page in pages
        for row in page["familyRecordCoverage"]
        for record_id in row["requiredDeepReadRecordIds"]
    } == set(raw["familyRecordCoverage"][0]["requiredDeepReadRecordIds"])


def test_create_requires_deep_reads_and_decisions_from_complete_public_pages(tmp_path):
    service, family, _, _ = _two_records(tmp_path)
    raw = query(service, family, detail_level="summary", limit=1, response_profile="create_compact")
    pages = _pages(service, raw)
    usage = {
        "retrievalOutcome": "matched",
        "dedupeQueryRefs": [page["dedupeQueryRef"] for page in pages],
        "buildFamilyKeys": [family],
        "selectedKnowledgeScope": raw["selectedKnowledgeScope"],
        "selectedSourceCaseRef": raw["selectedSourceCaseRef"],
        "insightDecisions": [{
            "sourceRefs": [family], "decision": "caveated",
            "summary": "选择同一来源变体，尚未完成记录深读。",
            "application": "深读并验证各机制条件后再应用。",
        }],
        "premiseAuditVersion": 1,
        "premiseDecisions": [{
            "premiseId": premise["premiseId"], "decision": "caveated",
            "application": "按来源场景保留机制验证任务。", "caveat": "尚未验证该失败条件。",
        } for page in pages for premise in page["familyPremiseCatalog"]
            if premise["premiseType"] == "failure_condition"],
    }

    def validate():
        return progression_provenance.validate_research_use_receipts(
            research_memory_use=usage, receipt_reader=service.read_query_receipt,
        )[0]

    assert validate() == "research_required_records_not_read"
    required = raw["familyRecordCoverage"][0]["requiredDeepReadRecordIds"]
    assert required
    deep = query(
        service, family, detail_level="record", record_ids=required,
        response_profile="create_compact",
    )
    usage["dedupeQueryRefs"].extend(page["dedupeQueryRef"] for page in _pages(service, deep))
    usage["deepRecordIds"] = required
    assert validate() == "research_required_records_not_decided"
    usage["insightDecisions"].append({
        "sourceRefs": required, "decision": "caveated",
        "summary": "已完整深读所选来源的机制和资源前提。",
        "application": "实装前保留同场景的资源和机制验证任务。",
    })
    assert validate() is None


@pytest.mark.parametrize("missing", ["deepRecordEligibilityVersion", "familyRecordCoverage"])
def test_old_page_receipts_require_a_new_query_instead_of_permission_backfill(tmp_path, missing):
    service, family, _, _ = _two_records(tmp_path)
    raw = query(service, family, detail_level="record", response_profile="create_compact")
    page = _pages(service, raw)[0]
    receipt = service.read_query_receipt(page["dedupeQueryRef"])
    result = deepcopy(receipt["result"])
    result.pop(missing)
    con = mature_learning.connect(service.db_path)
    try:
        con.execute(
            "UPDATE research_dedupe_queries SET result_contract=? WHERE dedupe_query_ref=?",
            (json.dumps(result), page["dedupeQueryRef"]),
        )
        con.commit()
    finally:
        con.close()
    assert service.read_query_receipt(page["dedupeQueryRef"]) is None
    refreshed = query(service, family, detail_level="record", response_profile="create_compact")
    new_page = _pages(service, refreshed)[0]
    assert service.read_query_receipt(new_page["dedupeQueryRef"]) is not None
    assert service.read_query_receipt(page["dedupeQueryRef"]) is None


def test_old_raw_snapshot_cannot_gain_new_eligibility_from_caller_marker(tmp_path):
    service, family, _, _ = _two_records(tmp_path)
    raw = query(service, family, detail_level="record", response_profile="create_compact")
    con = mature_learning.connect(service.db_path)
    try:
        row = con.execute(
            "SELECT result_contract FROM research_dedupe_queries WHERE dedupe_query_ref=?",
            (raw["dedupeQueryRef"],),
        ).fetchone()
        result = json.loads(row["result_contract"])
        result.pop("deepRecordEligibilityVersion")
        con.execute(
            "UPDATE research_dedupe_queries SET result_contract=? WHERE dedupe_query_ref=?",
            (json.dumps(result), raw["dedupeQueryRef"]),
        )
        con.commit()
    finally:
        con.close()
    raw["deepRecordEligibilityVersion"] = research_memory.DEEP_RECORD_ELIGIBILITY_VERSION
    rejected = service.start_retrieval_session(
        main._compact_create_research_response(raw),
        response_profile="create_compact", run_ref=None, claim_ref=None,
    )
    assert rejected["errorCode"] == "research_query_session_stale"


def test_old_session_continuation_cannot_issue_new_authority(tmp_path, monkeypatch):
    service, family, _, _ = _two_records(tmp_path)
    raw = query(service, family, detail_level="record", response_profile="create_compact")
    monkeypatch.setattr(research_contracts, "RESEARCH_QUERY_RESPONSE_BUDGET_BYTES", 6500)
    page = service.start_retrieval_session(
        main._compact_create_research_response(raw),
        response_profile="create_compact", run_ref=None, claim_ref=None,
    )
    cursor = page["retrieval"]["nextCursor"]
    assert cursor
    con = mature_learning.connect(service.db_path)
    try:
        row = con.execute(
            "SELECT request_contract FROM research_query_sessions WHERE retrieval_ref=?",
            (page["retrieval"]["retrievalRef"],),
        ).fetchone()
        request = json.loads(row["request_contract"])
        request.pop("deepRecordEligibilityVersion")
        con.execute(
            "UPDATE research_query_sessions SET request_contract=? WHERE retrieval_ref=?",
            (json.dumps(request), page["retrieval"]["retrievalRef"]),
        )
        con.commit()
    finally:
        con.close()
    rejected = service.continue_retrieval_session(cursor)
    assert rejected["errorCode"] == "research_query_continuation_stale"
