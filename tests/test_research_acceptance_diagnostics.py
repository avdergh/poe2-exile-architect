"""接受子集后的缺口必须与 Memory 写入原子保存，且不能携带原始材料。"""

from copy import deepcopy
import json
import sqlite3
from contextlib import closing

import pytest

from scripts import research_mature_builds, run_phase4_deep_review_acceptance as acceptance
from server.knowledge import research_completion, research_memory, research_runtime
from test_phase4_deep_review_acceptance import _write_review, _graph_service as _review_graph
from test_research_v3_contracts import _graph_service, _record


def _clean():
    return {
        "acceptanceMode": "clean",
        "deferredCandidateCount": 0,
        "unresolvedDeepRecordMentionCount": 0,
        "unresolvedUniqueComponentCount": 0,
        "caseCoverageGapCount": 0,
        "unkeyedDeepRecordCount": 0,
    }


def _partial():
    return {
        **_clean(),
        "acceptanceMode": "partial_with_deferred",
        "deferredCandidateCount": 1,
        "deferredReasonCounts": {"source_coverage_gap": 1},
        "deferredCandidates": [{
            "reason": "source_coverage_gap",
            "candidateKind": "deep_research_record",
            "recordKind": "resource_engine",
            "componentKeys": ["skill:CometPlayer"],
            "titleZh": "不应进入持久诊断的标题",
            "suggestedRepair": "不应进入持久诊断的说明",
        }],
        "caseCoverage": {"resourceDefense": "evidence_missing"},
        "caseCoverageGapCount": 1,
        "caseCoverageGaps": ["resourceDefense"],
    }


def _unit_kwargs():
    return {
        "run_ref": "research-run:completion",
        "sample_id": "case:completion",
        "accept_attempt_key": "raa-completion",
        "packet_safe_hash": "packet-completion",
        "canonical_review_hash": "review-completion",
        "contract_version": "phase4-safe-review-v3",
        "expected_origin_state": "claimed",
        "pattern_payload": {"schema_version": 4},
        "deep_payload": {"schema_version": 6, "deep_research_records": [_record()]},
        "edge_payload": {"schema_version": 4},
    }


def test_static_support_contract_is_bound_to_original_write_receipt(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    support_diagnostics = {
        "contractVersion": "fixture-support-v2",
        "graphSnapshotId": "physical-graph-fixture",
        "scope": "static_type_compatibility",
        "records": [{"recordIndex": 0, "packages": []}],
    }
    accepted = service.accept_research_unit(
        **_unit_kwargs(),
        acceptance_diagnostics={**_clean(), "supportCompatibility": support_diagnostics},
    )
    assert accepted["status"] == "accepted"
    receipt = service.get_research_write_receipt(accepted["writeReceiptRef"])
    assert receipt["acceptanceSummary"]["supportCompatibility"] == support_diagnostics
    assert receipt["writtenMapping"][0]["recordId"]

    replay = service.accept_research_unit(
        **_unit_kwargs(),
        acceptance_diagnostics={
            **_clean(),
            "supportCompatibility": {**support_diagnostics, "contractVersion": "newer"},
        },
    )
    assert replay["idempotentReplay"] is True
    assert replay["supportCompatibility"] == support_diagnostics


@pytest.mark.parametrize("queue_summary,expected", [(_partial(), "needs_followup"), (_clean(), "unknown")])
def test_legacy_receipt_preservation_keeps_known_gaps_without_promoting_completion(
    tmp_path, queue_summary, expected,
):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    run_id = "20260906-010203-abcd"
    kwargs = {**_unit_kwargs(), "run_ref": f"research-run:{run_id}"}
    receipt = service.accept_research_unit(**kwargs, acceptance_diagnostics=_partial())
    legacy = json.dumps({"acceptedDeepRecordCount": 1})
    with closing(sqlite3.connect(service.db_path)) as con, con:
        con.execute("UPDATE research_record_write_receipts SET acceptance_summary=?", (legacy,))
    row = {
        "sampleId": kwargs["sample_id"], "status": "accepted",
        "acceptedDeepRecordCount": 1, **queue_summary,
    }
    result = research_mature_builds._preserve_legacy_write_receipts(
        output_root=tmp_path / "run", run_id=run_id, rows=[row], memory_db_path=service.db_path,
    )
    assert result["writeReceiptRefs"] == [receipt["writeReceiptRef"]]
    assert row["researchCompletion"] == expected
    assert row["completionEvidence"] == "legacy_queue_and_safe_reports"
    if expected == "needs_followup":
        assert row["caseCoverageGaps"] == ["resourceDefense"]
        assert row["deferredReasonCounts"] == {"source_coverage_gap": 1}
    with closing(sqlite3.connect(service.db_path)) as con:
        assert con.execute("SELECT acceptance_summary FROM research_record_write_receipts").fetchone()[0] == legacy


@pytest.mark.parametrize("diagnostics,expected", [
    (None, "unknown"),
    ({}, "unknown"),
    ({"acceptanceMode": "clean"}, "unknown"),
    ({"acceptanceMode": "partial_with_deferred"}, "needs_followup"),
    ({**_clean(), "deferredCandidateCount": None}, "unknown"),
    ({**_clean(), "deferredCandidateCount": False}, "unknown"),
    ({**_clean(), "caseCoverage": {"supports": []}}, "unknown"),
    ({**_clean(), "deferredCandidates": ["unreadable diagnostic"]}, "unknown"),
    ({**_clean(), "caseCoverageGapCount": 1}, "needs_followup"),
    ({**_clean(), "caseCoverage": {"supports": "evidence_missing"}}, "needs_followup"),
    ({**_clean(), "deferredReasonCounts": {"missing_knowledge_identity": 1}}, "needs_followup"),
    (_clean(), "complete"),
])
def test_completion_requires_explicit_clean_and_known_zero_gap_counts(diagnostics, expected):
    result = research_completion.completion_summary(diagnostics)
    assert result["researchCompletion"] == expected
    assert research_completion.completion_summary(result) == result


def test_completion_projection_preserves_only_safe_gap_locations():
    diagnostics = _partial()
    diagnostics["rawXml"] = "<PathOfBuilding><Build/></PathOfBuilding>"
    diagnostics["deferredCandidates"][0]["validationIssues"] = [
        {"msg": "rawImportCode: eNrt unsafe source"}
    ]
    result = research_completion.completion_summary(diagnostics)
    assert result["deferredGapSummaries"] == [{
        "diagnosticIndex": 0,
        "reason": "source_coverage_gap",
        "candidateKind": "deep_research_record",
        "recordKind": "resource_engine",
        "componentKeys": ["skill:CometPlayer"],
    }]
    serialized = json.dumps(result, ensure_ascii=False)
    for forbidden in ("rawXml", "PathOfBuilding", "rawImportCode", "eNrt", "持久诊断的"):
        assert forbidden not in serialized


def test_completion_preserves_coverage_order_and_unresolved_record_positions():
    projection = acceptance._acceptance_completion_diagnostics(
        accepted_record_summaries=[{
            "recordKind": "resource_engine",
            "unresolvedComponents": [{"candidateName": "未绑定组件", "resolverQuery": "unknown"}],
        }],
        deferred=[],
        case_coverage={
            "passiveAscendancy": "evidence_missing", "gearRoles": "evidence_missing",
            "resourceDefense": "evidence_missing",
        },
    )
    assert projection["caseCoverageGaps"] == ["passiveAscendancy", "gearRoles", "resourceDefense"]
    assert projection["unresolvedComponentGapSummaries"] == [{
        "acceptedRecordIndex": 0, "unresolvedComponentIndex": 0, "recordKind": "resource_engine",
    }]
    assert projection["researchCompletion"] == "needs_followup"
    assert projection["unresolvedDeepRecordMentionCount"] == 1
    assert "未绑定组件" not in json.dumps(projection, ensure_ascii=False)
    assert research_completion.completion_summary(projection) == projection


def test_partial_receipt_survives_commit_fault_and_cannot_be_promoted_by_replay(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    kwargs = _unit_kwargs()
    with pytest.raises(RuntimeError, match="acceptance_fault:commit"):
        service.accept_research_unit(
            **kwargs, acceptance_diagnostics=_partial(), _fault_after_step="commit"
        )
    with sqlite3.connect(service.db_path) as con:
        original = con.execute(
            "SELECT acceptance_summary FROM research_record_write_receipts"
        ).fetchone()[0]
    assert json.loads(original)["researchCompletion"] == "needs_followup"
    assert "不应进入" not in original
    replay = service.accept_research_unit(**kwargs, acceptance_diagnostics=_clean())
    assert replay["idempotentReplay"] is True
    assert replay["researchCompletion"] == "needs_followup"
    receipt = service.get_research_write_receipt(replay["writeReceiptRef"])
    assert receipt["acceptanceSummary"]["caseCoverageGaps"] == ["resourceDefense"]
    with sqlite3.connect(service.db_path) as con:
        assert con.execute(
            "SELECT acceptance_summary FROM research_record_write_receipts"
        ).fetchone()[0] == original


def test_diagnostics_receipt_rolls_back_with_failed_memory_transaction(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    with pytest.raises(RuntimeError, match="acceptance_fault:receipt"):
        service.accept_research_unit(
            **_unit_kwargs(), acceptance_diagnostics=_partial(), _fault_after_step="receipt"
        )
    with sqlite3.connect(service.db_path) as con:
        assert con.execute("SELECT count(*) FROM research_record_write_receipts").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 0


def test_legacy_receipt_projects_unknown_without_rewriting_saved_truth(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    result = service.accept_research_unit(**_unit_kwargs())
    legacy = json.dumps({"acceptedDeepRecordCount": 1})
    with sqlite3.connect(service.db_path) as con:
        con.execute("UPDATE research_record_write_receipts SET acceptance_summary=?", (legacy,))
    receipt = service.get_research_write_receipt(result["writeReceiptRef"])
    assert receipt["acceptanceSummary"]["researchCompletion"] == "unknown"
    assert receipt["acceptanceSummary"]["deferredCandidateCount"] is None
    replay = service.accept_research_unit(**_unit_kwargs(), acceptance_diagnostics=_clean())
    assert replay["researchCompletion"] == "unknown"
    with sqlite3.connect(service.db_path) as con:
        assert con.execute(
            "SELECT acceptance_summary FROM research_record_write_receipts"
        ).fetchone()[0] == legacy


def test_clean_supplement_has_own_completion_scope_and_does_not_close_parent(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    first = service.accept_research_unit(**_unit_kwargs(), acceptance_diagnostics=_partial())
    supplement = deepcopy(_unit_kwargs())
    supplement.update(run_ref="research-run:supplement", accept_attempt_key="raa-supplement")
    supplement["deep_payload"]["deep_research_records"][0]["content"] = "补充复核装备预算的适用条件。"
    second = service.accept_research_unit(
        **supplement, acceptance_diagnostics=_clean(), supplement=True
    )
    assert second["status"] == "accepted"
    assert second["researchCompletion"] == "complete"
    assert second["completionScope"] == "supplement"
    parent = service.get_research_write_receipt(first["writeReceiptRef"])
    assert parent["acceptanceSummary"]["researchCompletion"] == "needs_followup"
    assert parent["acceptanceSummary"]["completionScope"] == "case"


def test_pipeline_persists_gap_diagnostics_before_presentation_artifact_write(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.sqlite"
    graph = _review_graph()
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=graph)
    review_file = _write_review(
        tmp_path,
        components=[{
            "candidateName": "Resolved Only", "componentKey": "skill:ResolvedOnlyPlayer",
            "role": "primary_damage", "resolverQuery": "Resolved Only",
        }, {
            "candidateName": "未解析组件定位", "role": "gear_base",
            "resolverQuery": "未解析组件定位",
        }],
        include_deep_record=True,
    )
    def artifact_write_failed(*_):
        raise OSError("simulated post-commit local report failure")
    monkeypatch.setattr(acceptance, "_write_safe_report", artifact_write_failed)
    report = acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=graph,
        acceptance_context={
            "runRef": "research-run:pipeline", "sampleId": "fixture_sample_001",
            "acceptAttemptKey": "raa-pipeline", "packetSafeHash": "packet-pipeline",
            "canonicalReviewHash": "review-pipeline", "contractVersion": "phase4-safe-review-v3",
            "expectedOriginState": "claimed",
        },
    )
    assert report["status"] == "accepted", report
    assert report["acceptanceArtifactWriteStatus"] == "best_effort_failed"
    assert report["researchCompletion"] == "needs_followup"
    receipt = service.get_research_write_receipt(report["writeReceiptRef"])
    stored = receipt["acceptanceSummary"]
    assert stored["researchCompletion"] == report["researchCompletion"]
    assert stored["caseCoverageGaps"] == report["caseCoverageGaps"]
    assert stored["caseCoverageGapCount"] > 0
    gap = stored["unresolvedComponentGapSummaries"][0]
    assert len(gap["recordSubjectHash"]) == len(gap["componentSubjectHash"]) == 64
    assert "未解析组件定位" not in json.dumps(stored, ensure_ascii=False)
    with research_memory.mature_learning.connect(db_path) as con:
        assert research_runtime.get_memory_revision(con) == 1
