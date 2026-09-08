"""独立 CR 反例：来源必须留在原 package/plan，不能用全局并集替代。"""

from copy import deepcopy

import pytest

from server import main
from server.generation import evidence_authority, models, run_store
from tests import test_generation_draft_recovery as helper
from tests.test_generation_blueprint import EVIDENCE_REF
from tests.test_research_execution_contract import (
    AUTH_PACKAGE,
    COMPARE_PACKAGE,
    CONTRACT_REF,
    PLAN_ID,
    _cross_case_plan,
    _decision,
)


def _setup_shared_source(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path / "isolated-data"))
    original_candidate = helper._candidate

    def shared_source_candidate(bound):
        candidate = original_candidate(bound)
        candidate.mechanism_blueprint.claims[0].source_refs.append("checkpoint:test-state")
        return candidate

    monkeypatch.setattr(helper, "_candidate", shared_source_candidate)
    return helper._setup(tmp_path, monkeypatch)


@pytest.mark.parametrize("restore_baseline", [False, True])
def test_original_package_evidence_cannot_be_replaced_after_judge(
    tmp_path,
    monkeypatch,
    restore_baseline,
):
    bound, token, payload, _ = _setup_shared_source(tmp_path, monkeypatch)
    judged = helper._judge(bound, token, payload)
    assert judged["status"] == "evaluated", judged
    if restore_baseline:
        new_design = deepcopy(payload)
        new_design["prototypeBuildCandidate"]["researchExecutionPlan"]["packageDecisions"][0][
            "verificationEvidenceRefs"
        ] = [EVIDENCE_REF]
        assert helper._draft(bound, token, new_design)["status"] == "accepted"
    saved = main.save_final_build_artifact(
        bound.run_id,
        token,
        payload["prototypeBuildCandidate"]["candidateId"],
        0,
        **(
            {
                "selection_reason": "Later Research changes concern only the candidate delta.",
                "later_findings_scope": "candidate_delta_only",
            }
            if restore_baseline
            else {}
        ),
    )
    assert saved["status"] == "saved", saved
    if restore_baseline:
        assert saved["selectedDesignEvidence"]["researchExecutionPlan"]["packageDecisions"][0][
            "verificationEvidenceRefs"
        ] == ["checkpoint:test-state"]
    original = run_store.read_trusted_evaluations_strict(bound)[0]
    revised = deepcopy(payload)
    revised["prototypeBuildCandidate"]["researchExecutionPlan"]["packageDecisions"][0][
        "verificationEvidenceRefs"
    ] = [EVIDENCE_REF]
    output = helper._review_payload(revised, judged)
    for submit in (main.validate_generation_output, main.complete_generation_review):
        result = submit(bound.run_id, token, output)
        assert result["status"] == "rejected", result
    assert not (bound.run_dir / "review-consumed").exists()
    assert run_store.read_trusted_evaluations_strict(bound)[0] == original


def test_changing_subject_evidence_requires_new_draft_even_when_union_is_unchanged(
    tmp_path, monkeypatch
):
    bound, token, payload, _ = _setup_shared_source(tmp_path, monkeypatch)
    previous = helper.mechanism_evidence.read_validated_draft(
        bound, candidate_id=payload["prototypeBuildCandidate"]["candidateId"]
    )
    revised = deepcopy(payload)
    revised["prototypeBuildCandidate"]["researchExecutionPlan"]["packageDecisions"][0][
        "verificationEvidenceRefs"
    ] = [EVIDENCE_REF]
    result = helper._draft(bound, token, revised)
    assert result["status"] == "accepted", result
    current = helper.mechanism_evidence.read_validated_draft(
        bound, candidate_id=payload["prototypeBuildCandidate"]["candidateId"]
    )
    assert previous["draftMarker"]["designToolsHash"] == current["draftMarker"]["designToolsHash"]
    assert (
        previous["draftMarker"]["designEvidenceUsesHash"]
        != current["draftMarker"]["designEvidenceUsesHash"]
    )


def _plan():
    first = _decision(AUTH_PACKAGE, adopted=True)
    second = _decision(COMPARE_PACKAGE, adopted=True, plan_ref=PLAN_ID)
    first["verificationEvidenceRefs"] = ["checkpoint:first"]
    second["verificationEvidenceRefs"] = ["checkpoint:second"]
    cross = _cross_case_plan()
    cross["evidenceRefs"] = ["mechanic:cross"]
    return models.ResearchExecutionPlan.model_validate(
        {
            "contractRef": CONTRACT_REF,
            "selectedDesignCaseRef": "case:authoritative",
            "selectedVariantRationale": "Preserve the selected authoritative mechanism and verify each separate component responsibility with its exact source evidence.",
            "coherenceSummary": "The selected packages and cross-case mechanism have separate evidence duties whose original associations remain meaningful through final review.",
            "packageDecisions": [first, second],
            "crossCaseMechanismPlans": [cross],
        }
    )


@pytest.mark.parametrize(
    "mutation", ["swap_packages", "move_into_plan", "move_from_plan", "remove_subject"]
)
def test_evidence_cannot_move_between_subjects(mutation):
    original = _plan()
    uses = evidence_authority.design_evidence_uses(original)
    changed = original.model_copy(deep=True)
    first, second = changed.package_decisions
    cross = changed.cross_case_mechanism_plans[0]
    if mutation == "swap_packages":
        first.verification_evidence_refs, second.verification_evidence_refs = (
            second.verification_evidence_refs,
            first.verification_evidence_refs,
        )
    elif mutation == "move_into_plan":
        cross.evidence_refs.extend(first.verification_evidence_refs)
        first.verification_evidence_refs = list(second.verification_evidence_refs)
    elif mutation == "move_from_plan":
        first.verification_evidence_refs.extend(cross.evidence_refs)
        cross.evidence_refs = list(second.verification_evidence_refs)
    else:
        changed.package_decisions.pop()
    assert not evidence_authority.evidence_uses_preserved(changed, uses)


def test_per_subject_append_and_order_only_changes_are_allowed():
    original = _plan()
    uses = evidence_authority.design_evidence_uses(original)
    assert evidence_authority.design_evidence_uses(original.model_dump(by_alias=False)) == uses
    changed = original.model_copy(deep=True)
    changed.package_decisions.reverse()
    for item in changed.package_decisions:
        item.verification_evidence_refs.insert(0, "judge:corroboration")
    changed.cross_case_mechanism_plans[0].evidence_refs.append("judge:corroboration")
    assert evidence_authority.evidence_uses_preserved(changed, uses)


def test_legacy_marker_needs_authenticated_original_uses_and_never_the_new_candidate(
    tmp_path, monkeypatch
):
    bound, _token, payload, _ = _setup_shared_source(tmp_path, monkeypatch)
    candidate = models.PrototypeBuildCandidate.model_validate(payload["prototypeBuildCandidate"])
    frozen = helper.mechanism_evidence.read_validated_draft(
        bound, candidate_id=candidate.candidate_id
    )
    marker = deepcopy(frozen["draftMarker"])
    marker.pop("designEvidenceUses")
    marker.pop("designEvidenceUsesHash")
    assert not evidence_authority.design_tools_match(candidate, marker)
    uses = evidence_authority.design_evidence_uses(frozen["researchExecutionPlan"])
    assert evidence_authority.design_tools_match(candidate, marker, original_evidence_uses=uses)
    candidate.research_execution_plan.package_decisions[0].verification_evidence_refs = [
        EVIDENCE_REF
    ]
    assert not evidence_authority.design_tools_match(candidate, marker, original_evidence_uses=uses)


def test_frozen_bundle_checks_ownership_against_its_original_plan(tmp_path, monkeypatch):
    bound, _token, payload, _ = _setup_shared_source(tmp_path, monkeypatch)
    frozen = helper.mechanism_evidence.read_validated_draft(
        bound, candidate_id=payload["prototypeBuildCandidate"]["candidateId"]
    )
    assert helper.mechanism_evidence._valid_draft(frozen)
    for subject in frozen["draftMarker"]["designEvidenceUses"]["packages"]:
        frozen["draftMarker"]["designEvidenceUses"]["packages"][subject] = [EVIDENCE_REF]
    frozen["draftMarker"]["designEvidenceUsesHash"] = evidence_authority.audit_hash(
        frozen["draftMarker"]["designEvidenceUses"]
    )
    assert not helper.mechanism_evidence._valid_draft(frozen)


def test_old_active_marker_requires_full_draft_revalidation_before_judge(tmp_path, monkeypatch):
    import json

    bound, token, payload, _ = _setup_shared_source(tmp_path, monkeypatch)
    path = bound.run_dir / "draft-validation.json"
    marker = json.loads(path.read_text(encoding="utf-8"))
    marker.pop("designEvidenceUses")
    marker.pop("designEvidenceUsesHash")
    path.write_text(json.dumps(marker), encoding="utf-8")
    helper.mechanism_evidence._DRAFTS.pop(helper.mechanism_evidence._draft_key(bound))
    rejected = helper._judge(bound, token, payload)
    assert rejected["errorCode"] == "generation_draft_validation_required"
    assert rejected["attemptConsumed"] is False
    assert not bound.trusted_evaluations_dir.exists()
    assert helper._draft(bound, token, payload)["status"] == "accepted"
    assert helper._judge(bound, token, payload)["status"] == "evaluated"
