"""Blueprint evidence identities are not receipts merely because the caller names them."""

from scripts import create_build
from copy import deepcopy
import json

import pytest

from server.generation import evidence_authority, models, run_store
from test_generation_blueprint import _blueprint, _version_context


def test_unexecuted_tool_reference_cannot_ground_blueprint(monkeypatch, tmp_path):
    monkeypatch.setenv("POE_BD_CREATE_RUNS_DIR", str(tmp_path))
    run = create_build.start_generation_run("no_memory")["runContext"]
    result = create_build.validate_generation_blueprint(
        run["runId"],
        run["runToken"],
        {
            "candidateId": "candidate:evidence-test",
            "versionContext": _version_context(),
            "noRawMaterial": True,
            "toolReferences": [
                {
                    "toolName": "nonexistent_tool",
                    "queryRef": "forged:never-executed",
                    "summary": "Synthetic unexecuted reference.",
                }
            ],
            "mechanismBlueprint": _blueprint(evidence_ref="forged:never-executed"),
        },
    )
    assert result["status"] == "rejected"
    assert result["errorCode"] == "mechanism_blueprint_evidence_unverified"


def test_arbitrary_tool_name_is_not_external_review_evidence():
    assert not create_build._execution_external_evidence_refs(
        [{"toolName": "nonexistent_tool", "queryRef": "forged:never-executed", "summary": "Test"}]
    )


def _reference(**changes):
    return {
        "toolName": "get_gem",
        "queryRef": "gem:reviewed",
        "summary": "Safe synthetic summary",
        "evidenceKind": "agent_reviewed",
        "reviewBasis": "Agent read the selected gem content and checked the stated conditions.",
        **changes,
    }


def _draft(ref):
    return {
        "candidateId": "candidate:evidence-test",
        "versionContext": _version_context(),
        "noRawMaterial": True,
        "toolReferences": [ref],
        "mechanismBlueprint": _blueprint(evidence_ref=ref["queryRef"]),
    }


def test_reviewed_external_evidence_remains_agent_assertion(monkeypatch, tmp_path):
    monkeypatch.setenv("POE_BD_CREATE_RUNS_DIR", str(tmp_path))
    run = create_build.start_generation_run("no_memory")["runContext"]
    draft = _draft(_reference())
    result = create_build.validate_generation_blueprint(run["runId"], run["runToken"], draft)
    assert result["status"] == "accepted"
    assert {row["evidenceKind"] for row in result["evidenceAudit"]["sources"]} == {"agent_reviewed"}
    assert result["evidenceAudit"]["semanticTruthVerified"] is False
    assert result["evidenceAudit"]["numericLegalityVerified"] is False
    path = tmp_path / run["runId"]
    manifest = json.loads((path / "run-manifest.json").read_text(encoding="utf-8"))
    candidate = {**draft, "mechanismBlueprintRef": result["blueprintRef"]}
    arguments = dict(run_dir=path, manifest=manifest, require_draft_binding=False)
    assert create_build._validate_candidate_blueprint_use(candidate, **arguments)[0] is None
    candidate["toolReferences"][0]["summary"] = "Rephrased narrative does not change authority."
    assert create_build._validate_candidate_blueprint_use(candidate, **arguments)[0] is None
    candidate["toolReferences"][0]["reviewBasis"] = (
        "Different source review conditions must be revalidated first."
    )
    assert (
        create_build._validate_candidate_blueprint_use(candidate, **arguments)[0]
        == "generation_blueprint_evidence_binding_mismatch"
    )


@pytest.mark.parametrize("tool", ["get_gem", "query_research_memory", "nonexistent_tool"])
def test_internal_receipt_requires_validated_research_source(tool):
    ref = _reference(toolName=tool, evidenceKind="internal_receipt", reviewBasis=None)
    blueprint = models.MechanismBlueprint.model_validate(_blueprint(evidence_ref=ref["queryRef"]))
    assert (
        evidence_authority.blueprint_audit(blueprint, [ref], set())[0]
        == "tool_evidence_receipt_unverified"
    )


def test_verified_research_source_is_separate_from_external_review():
    ref = _reference(
        toolName="query_research_memory",
        queryRef="dq-tested",
        evidenceKind="internal_receipt",
        reviewBasis=None,
    )
    blueprint = models.MechanismBlueprint.model_validate(_blueprint(evidence_ref=ref["queryRef"]))
    error, audit = evidence_authority.blueprint_audit(blueprint, [ref], {"dq-tested"})
    assert error is None
    assert audit["sources"][0]["evidenceKind"] == "internal_receipt"
    assert not evidence_authority.external_refs([ref])
    wrong_tool = {**ref, "toolName": "construct_research_execution_contract"}
    assert (
        evidence_authority.validate_internal_claims([wrong_tool], {"dq-tested"})
        == "tool_evidence_receipt_unverified"
    )


def test_unverified_inputs_only_support_explicit_hypotheses_with_verification():
    ref = _reference(evidenceKind="unverified", reviewBasis=None)
    value = _blueprint(evidence_ref=ref["queryRef"])
    for row in value["claims"]:
        row["status"] = "hypothesis"
    blueprint = models.MechanismBlueprint.model_validate(value)
    error, audit = evidence_authority.blueprint_audit(blueprint, [ref], set())
    assert error is None
    assert audit["sources"][0]["evidenceKind"] == "unverified"
    blueprint.claims[0].verification_tasks = []
    assert (
        evidence_authority.blueprint_audit(blueprint, [ref], set())[0]
        == "mechanism_blueprint_hypothesis_verification_required"
    )


@pytest.mark.parametrize("basis", [None, " " * 50])
def test_agent_review_requires_substantive_review_basis(basis):
    with pytest.raises(models.ValidationError):
        models.ToolReference.model_validate(_reference(reviewBasis=basis))


def test_conflicting_duplicate_citation_cannot_select_stronger_authority():
    ref = _reference()
    other = {**ref, "evidenceKind": "internal_receipt", "reviewBasis": None}
    assert (
        evidence_authority.validate_internal_claims([ref, other], {ref["queryRef"]})
        == "invalid_tool_evidence_reference"
    )


def test_legacy_marker_and_tampered_audit_cannot_authorize_current_blueprint():
    ref = _reference()
    blueprint = models.MechanismBlueprint.model_validate(_blueprint(evidence_ref=ref["queryRef"]))
    _, audit = evidence_authority.blueprint_audit(blueprint, [ref], set())
    assert not evidence_authority.audit_matches({"schemaVersion": 1}, blueprint, [ref])
    marker = dict(
        evidenceAudit=deepcopy(audit), evidenceAuditHash=evidence_authority.audit_hash(audit)
    )
    marker["evidenceAudit"]["sources"][0]["evidenceKind"] = "internal_receipt"
    assert not evidence_authority.audit_matches(marker, blueprint, [ref])


def test_no_memory_legacy_run_cannot_upgrade_evidence_authority():
    assert run_store.generation_contract_upgrade_required(
        {
            "agentOutputContractVersion": "generation-agent-output-v4",
            "experimentContext": {"memoryMode": "no_memory", "mechanismBlueprintRequired": True},
        }
    )


@pytest.mark.parametrize("sources", [None, "malformed", [None], [{"sourceRef": 1}]])
def test_malformed_marker_fails_closed(sources):
    ref = _reference()
    blueprint = models.MechanismBlueprint.model_validate(_blueprint(evidence_ref=ref["queryRef"]))
    marker = dict(
        evidenceAudit={"version": evidence_authority.AUDIT_VERSION, "sources": sources},
        evidenceAuditHash="forged",
    )
    assert not evidence_authority.audit_matches(marker, blueprint, [ref])


def test_saved_review_allows_new_corroboration_without_rewriting_original_authority(
    tmp_path, monkeypatch
):
    from server import main
    from tests.test_generation_draft_recovery import _setup, _judge, _review_payload

    bound, token, payload, _ = _setup(tmp_path, monkeypatch)
    judged = _judge(bound, token, payload)
    assert judged["status"] == "evaluated", judged
    original = run_store.read_trusted_evaluations_strict(bound)[0]
    marker_path = bound.run_dir / "draft-validation.json"
    marker_bytes = marker_path.read_bytes()
    saved = main.save_final_build_artifact(
        bound.run_id, token, payload["prototypeBuildCandidate"]["candidateId"], 0
    )
    assert saved["status"] == "saved", saved
    revised = deepcopy(payload)
    candidate = revised["prototypeBuildCandidate"]
    candidate["toolReferences"].append(
        _reference(toolName="evaluate_generation_candidate", queryRef="judge:corroboration")
    )
    candidate["researchExecutionPlan"]["packageDecisions"][0]["verificationEvidenceRefs"].append(
        "judge:corroboration"
    )
    result = main.validate_generation_output(bound.run_id, token, _review_payload(revised, judged))
    assert result["status"] == "accepted", result
    for mutation in (
        {"evidenceKind": "internal_receipt", "reviewBasis": None},
        {
            "reviewBasis": "Changed conditions for the original evidence cannot authorize this baseline."
        },
    ):
        changed = deepcopy(revised)
        ref = next(
            row
            for row in changed["prototypeBuildCandidate"]["toolReferences"]
            if row["queryRef"] == "checkpoint:test-state"
        )
        ref.update(mutation)
        rejected = main.validate_generation_output(
            bound.run_id, token, _review_payload(changed, judged)
        )
        assert rejected["status"] == "rejected", rejected
    accepted = main.complete_generation_review(
        bound.run_id, token, _review_payload(revised, judged)
    )
    assert accepted["status"] == "accepted", accepted
    assert marker_path.read_bytes() == marker_bytes
    assert run_store.read_trusted_evaluations_strict(bound)[0] == original
