"""Historical Draft marker consumption keeps the ordinary Research validators active."""

from copy import deepcopy
import json

import pytest

from scripts import create_build
from server.generation import models
from server.knowledge import research_execution
from tests.test_research_execution_contract import (
    AUTH_PACKAGE,
    COMPARE_PACKAGE,
    CONTRACT_REF,
    PLAN_ID,
    _contract,
    _cross_case_plan,
    _decision,
)


@pytest.fixture
def research_case(tmp_path, monkeypatch):
    plan = models.ResearchExecutionPlan.model_validate(
        {
            "contractRef": CONTRACT_REF,
            "selectedDesignCaseRef": "case:authoritative",
            "selectedVariantRationale": "Use the source case whose resource and defense duties match this candidate's target level and verified mechanical commitments after comparison.",
            "coherenceSummary": "Keep the authoritative shell and verify the complete transferred mechanism with its companions.",
            "packageDecisions": [
                _decision(AUTH_PACKAGE, adopted=True),
                _decision(COMPARE_PACKAGE, adopted=True, plan_ref=PLAN_ID),
            ],
            "crossCaseMechanismPlans": [_cross_case_plan()],
        }
    ).model_dump(mode="json", by_alias=True)
    payload = {
        "prototypeBuildCandidate": {
            "researchMemoryUse": {"retrievalOutcome": "matched"},
            "versionContext": {"gamePatch": "0.5.5", "passiveTreeVersion": "0_5"},
            "researchExecutionPlan": plan,
            "toolReferences": [
                _reviewed_ref("inspect_generation_checkpoint", "checkpoint:test-state"),
                _reviewed_ref("search_mechanics", "mechanic:test-mechanism"),
            ],
        }
    }
    # Source/receipt validation has its own fixtures; this seam checks it is still mandatory
    # while the real execution-plan validator and historic/current marker choice run unchanged.
    provenance_calls = []

    def provenance(**kwargs):
        provenance_calls.append(kwargs)
        return None, {}, []

    monkeypatch.setattr(
        create_build.progression_provenance, "validate_research_use_receipts", provenance
    )
    monkeypatch.setattr(
        research_execution, "construct_from_research_use", lambda *_a, **_k: _contract()
    )
    context = {
        "draftMarker": {
            "researchExecutionContractRef": CONTRACT_REF,
            "researchExecutionStructureHash": research_execution.stable_plan_structure_hash(plan),
        }
    }
    current = {
        "researchExecutionContractRef": "rec-new-design",
        "researchExecutionStructureHash": "new-structure",
    }
    marker = tmp_path / "draft-validation.json"
    marker.write_text(json.dumps(current), encoding="utf-8")
    return payload, context, marker, provenance_calls


def _reviewed_ref(tool, ref):
    return {"toolName": tool, "queryRef": ref, "summary": "Synthetic reviewed test evidence.",
            "evidenceKind": "agent_reviewed",
            "reviewBasis": "Agent inspected the exact synthetic result and verified its stated conditions."}


def validate(case, *, context=True):
    payload, historical, marker, _calls = case
    return create_build._validate_candidate_research_use(
        payload,
        receipt_reader=lambda _ref: None,
        not_before="2026-09-07T00:00:00+00:00",
        run_dir=marker.parent,
        evidence_context=historical if context else None,
    )


def test_historical_context_reuses_structure_without_changing_current_marker(research_case):
    before = research_case[2].read_bytes()
    assert (
        validate(research_case, context=False)[0] == "research_execution_plan_changed_after_draft"
    )
    assert validate(research_case) == (None, [])
    assert research_case[2].read_bytes() == before
    assert research_case[3][-1]["not_before"] == "2026-09-07T00:00:00+00:00"


def test_historical_marker_does_not_relax_execution_structure_binding(research_case):
    research_case[1]["draftMarker"]["researchExecutionStructureHash"] = "another-draft"
    assert validate(research_case)[0] == "research_execution_plan_changed_after_draft"


def test_historical_context_allows_supported_post_judge_evidence(research_case):
    candidate = research_case[0]["prototypeBuildCandidate"]
    candidate["researchExecutionPlan"]["packageDecisions"][0]["verificationEvidenceRefs"].append(
        "judge:final"
    )
    candidate["researchExecutionPlan"]["packageDecisions"][0]["buildApplication"] += (
        " Confirmed on the final evaluated state."
    )
    candidate["toolReferences"].append(
        _reviewed_ref("evaluate_generation_candidate", "judge:final")
    )
    assert validate(research_case) == (None, [])


def test_historical_context_still_checks_selected_source_case(research_case):
    candidate = research_case[0]["prototypeBuildCandidate"]
    candidate["researchExecutionPlan"]["selectedDesignCaseRef"] = "case:other"
    error, _ = validate(research_case)
    assert error == "research_execution_selected_case_mismatch"


@pytest.mark.parametrize(
    "code",
    [
        "progression_research_receipt_not_current_run",
        "progression_research_resolution_not_deep_read",
    ],
)
def test_historical_context_cannot_authorize_invalid_research_receipts(
    research_case, monkeypatch, code
):
    monkeypatch.setattr(
        create_build.progression_provenance,
        "validate_research_use_receipts",
        lambda **_k: (code, {}, []),
    )
    assert validate(research_case) == (code, [])


def test_historical_context_still_runs_unique_subject_decisions(research_case, monkeypatch):
    monkeypatch.setattr(
        research_execution,
        "validate_insight_decision_subjects",
        lambda *_a: ("research_insight_subject_decision_missing", []),
    )
    assert validate(research_case) == ("research_insight_subject_decision_missing", [])


def test_context_input_is_not_modified_by_research_validation(research_case):
    before = deepcopy(research_case[1])
    assert validate(research_case)[0] is None
    assert research_case[1] == before
