"""紧凑回执不改变写入证明；映射、摘要、诊断和实时资格可完整分页读回。"""

from copy import deepcopy
import json

import pytest

from server import main
from server.knowledge import research_receipt_view as view


def _receipt():
    writes = [
        {
            "recordId": f"drr-{index}",
            "afterProjectionHash": str(index) * 64,
            "sourceClaimKey": "default",
            "sourceGamePatch": "0.5.5",
            "canonicalContentMatchesSubmitted": True,
            "canonicalRecord": {
                "summary": "已保存的机制摘要",
                "sourceCaseRefs": ["source-hash:fixture"],
            },
            "crossFamilyDuplicateAdvisories": [{"index": j} for j in range(105)],
        }
        for index in range(5)
    ]
    return {
        "status": "ok",
        "writeReceiptRef": "rwr-example",
        "createAuthorizing": False,
        "noRawMatureBuildMaterial": True,
        "acceptanceSummary": {
            "acceptedDeepRecordCount": 5,
            "acceptanceMode": "clean",
            "researchCompletion": "complete",
            "caseCoverage": {"supports": "covered"},
            "deepRecordWrite": {"createdRecordCount": 5, "recordWrites": deepcopy(writes)},
            "supportCompatibility": {"contractVersion": "fixture", "records": [{"index": 2}]},
        },
        "writtenMapping": writes,
        "currentProjection": [
            {
                "writtenRecordId": w["recordId"],
                "writtenMappingIndex": index,
                "sourceClaimKey": "default",
                "currentEligibility": False,
                "claimBindingStatus": "diagnostic_only",
                "bindingIssue": "source_state_unknown",
            }
            for index, w in enumerate(writes)
        ],
    }


def test_default_summary_avoids_duplicate_details_and_preserves_exact_mapping():
    original = _receipt()
    before = deepcopy(original)
    result = view.project_receipt(original)
    assert "canonicalRecord" not in result["writtenMapping"][0]
    assert "recordWrites" not in result["acceptanceSummary"]["deepRecordWrite"]
    assert result["writtenMapping"][0]["afterProjectionHash"] == "0" * 64
    assert result["currentProjection"] == original["currentProjection"]
    assert result["acceptanceSummary"]["researchCompletion"] == "complete"
    assert result["recordCount"] == 5
    assert result["createAuthorizing"] is False
    assert len(json.dumps(result)) < len(json.dumps(original)) / 3
    result["writtenMapping"][0]["sourceClaimKey"] = "changed"
    assert original == before


def test_record_pages_cover_all_written_records_and_matching_current_projection():
    original = _receipt()
    records = []
    cursor = 0
    while True:
        page = view.project_receipt(original, detail="records", cursor=cursor, limit=2)
        records.extend(page["writtenMapping"])
        assert {r["recordId"] for r in page["writtenMapping"]} == {
            p["writtenRecordId"] for p in page["currentProjection"]
        }
        cursor = page["pagination"]["nextCursor"]
        if cursor is None:
            break
    assert [r["canonicalRecord"] for r in records] == [
        r["canonicalRecord"] for r in original["writtenMapping"]
    ]


def test_shared_record_pages_keep_each_source_claims_own_eligibility():
    original = _receipt()
    original["writtenMapping"][1]["recordId"] = original["writtenMapping"][0]["recordId"]
    original["writtenMapping"][1]["sourceClaimKey"] = "boss-window"
    original["currentProjection"][1].update(
        writtenRecordId=original["writtenMapping"][0]["recordId"],
        sourceClaimKey="boss-window",
        currentEligibility=True,
    )
    first = view.project_receipt(original, cursor=0, limit=1)
    second = view.project_receipt(original, cursor=1, limit=1)
    assert [p["sourceClaimKey"] for p in first["currentProjection"]] == ["default"]
    assert first["currentProjection"][0]["currentEligibility"] is False
    assert [p["sourceClaimKey"] for p in second["currentProjection"]] == ["boss-window"]
    assert second["currentProjection"][0]["currentEligibility"] is True
    assert first["projectionMappingComplete"] is True


def test_missing_mapping_index_is_reported_without_borrowing_another_claim():
    original = _receipt()
    del original["currentProjection"][0]["writtenMappingIndex"]
    result = view.project_receipt(original, cursor=0, limit=1)
    assert result["currentProjection"] == []
    assert result["projectionMappingComplete"] is False


def test_diagnostic_section_is_discoverable_and_exhaustively_paginated():
    original = _receipt()
    section = "writtenMapping[0].crossFamilyDuplicateAdvisories"
    summary = view.project_receipt(original)
    assert {"section": section, "count": 105} in summary["diagnosticSections"]
    first = view.project_receipt(original, detail="diagnostics", section=section, limit=100)
    last = view.project_receipt(original, detail="diagnostics", section=section, cursor=100)
    assert (
        first["entries"] + last["entries"]
        == original["writtenMapping"][0]["crossFamilyDuplicateAdvisories"]
    )
    assert first["pagination"]["nextCursor"] == 100
    assert last["pagination"]["complete"] is True
    assert "writtenMapping" not in first
    assert "recordWrites" not in first["acceptanceSummary"]["deepRecordWrite"]
    invalid = view.project_receipt(original, detail="diagnostics", section="unknown")
    assert invalid["errorCode"] == "receipt_diagnostic_section_required"


@pytest.mark.parametrize(
    "params",
    [{"cursor": -1}, {"limit": 0}, {"limit": 101}, {"detail": "unknown"}, {"section": "x"}],
)
def test_invalid_page_fails_explicitly(params):
    with pytest.raises(ValueError):
        view.project_receipt(_receipt(), **params)


def test_real_receipt_exposes_saved_summary_without_inventing_a_body_snapshot(tmp_path):
    from server.knowledge import research_memory
    from test_research_acceptance_diagnostics import _clean, _unit_kwargs
    from test_research_v3_contracts import _graph_service

    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite",
        graph_service=_graph_service(),
    )
    accepted = service.accept_research_unit(**_unit_kwargs(), acceptance_diagnostics=_clean())
    assert accepted["status"] == "accepted", accepted
    original = service.get_research_write_receipt(accepted["writeReceiptRef"])
    page = view.project_receipt(original, detail="records")
    assert page["canonicalRecordScope"] == "persisted_summary_not_full_content"
    canonical = page["writtenMapping"][0]["canonicalRecord"]
    assert canonical["summary"]
    assert "content" not in canonical
    assert page["recordContentRead"]["tool"] == "query_research_memory"
    assert (
        page["writtenMapping"][0]["afterProjectionHash"]
        == original["writtenMapping"][0]["afterProjectionHash"]
    )


def test_public_tool_uses_summary_and_allows_canonical_record_page(monkeypatch):
    class Service:
        def get_research_write_receipt(self, _ref):
            return _receipt()

    monkeypatch.setattr(main, "_research_memory_service", Service)
    assert (
        "canonicalRecord" not in main.get_research_write_receipt("rwr-example")["writtenMapping"][0]
    )
    assert (
        "canonicalRecord"
        in main.get_research_write_receipt(
            "rwr-example",
            detail="records",
            cursor=2,
            limit=1,
        )["writtenMapping"][0]
    )
