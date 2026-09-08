"""C3/C4 independent boundary checks over the public and saved-evidence paths."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from scripts import create_build
from server import main
from server.generation import artifacts, mechanism_evidence, run_store, validation_checkpoint
from tests import test_checkpoint_lifecycle_observation as observation_fixtures
from tests.test_checkpoint_lifecycle_observation import (
    DECLARATION,
    TARGET,
    ObservationEngine,
)
from tests.test_generation_mechanism_baseline import _baseline, _revise, _save
from tests.test_phase5_generation_evaluation import _ActiveEngine
from tests.test_phase5_prototype_models import agent_submission_payload


@pytest.fixture
def isolated_checkpoints(monkeypatch):
    yield from observation_fixtures.isolated_checkpoints.__wrapped__(monkeypatch)


class PublicObservationEngine(ObservationEngine):
    def select_judge_skill(self, *, offense_skill_group_index, expected_skill_name):
        assert offense_skill_group_index == TARGET["groupIndex"]
        assert expected_skill_name == TARGET["skillName"]
        return {"status": "selected", "calculationContext": deepcopy(TARGET)}


@pytest.mark.usefixtures("isolated_checkpoints")
@pytest.mark.parametrize(
    "replacement, expected_status",
    [({}, "unknown"), ({**DECLARATION, "buildDefiningComponentName": "Missing Skill"}, "failed")],
)
def test_public_lifecycle_replacement_revokes_cached_success(
    monkeypatch, replacement, expected_status
):
    engine = PublicObservationEngine(90)
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    first = validation_checkpoint.inspect_generation_checkpoint(engine)
    assert first["lifecycleVerification"]["status"] == "unknown"

    verified = main.verify_lifecycle_stage(
        "endgame_budget",
        state=deepcopy(DECLARATION),
        offense_skill_group_index=TARGET["groupIndex"],
        expected_skill_name=TARGET["skillName"],
    )
    assert verified["pass"] is True
    refreshed = validation_checkpoint.inspect_generation_checkpoint(engine)
    assert refreshed["cacheHit"] is True
    assert refreshed["lifecycleVerification"]["pass"] is True

    replaced = main.verify_lifecycle_stage(
        "endgame_budget",
        state=replacement,
        offense_skill_group_index=TARGET["groupIndex"],
        expected_skill_name=TARGET["skillName"],
    )
    assert replaced["status"] == expected_status
    final = validation_checkpoint.inspect_generation_checkpoint(engine)
    assert final["cacheHit"] is True
    assert final["lifecycleVerification"]["status"] == expected_status
    assert final["deliveryStatus"] == "candidate"


@pytest.mark.parametrize(
    "field,value",
    [("groupIndex", 2), ("activeIndex", 2), ("skillName", "lightning arrow")],
)
def test_bundle_requires_full_exact_judge_calculation_context(
    tmp_path, monkeypatch, field, value
):
    bound_run, _, _, _ = _baseline(tmp_path, monkeypatch)
    receipt = run_store.read_trusted_evaluations_strict(bound_run)[0]
    receipt["judgeAdvisoryReport"]["calculationContext"][field] = value
    assert mechanism_evidence.valid_evaluation_evidence(receipt) is False


def test_bundle_cannot_use_optional_selected_skill_as_target_authority(tmp_path, monkeypatch):
    bound_run, _, _, _ = _baseline(tmp_path, monkeypatch)
    receipt = run_store.read_trusted_evaluations_strict(bound_run)[0]
    receipt["judgeAdvisoryReport"]["selectedSkill"] = None
    receipt["judgeAdvisoryReport"]["calculationContext"] = None
    assert mechanism_evidence.valid_evaluation_evidence(receipt) is False


def test_deleted_current_markers_do_not_destroy_protected_baseline(tmp_path, monkeypatch):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    original = run_store.read_trusted_evaluations_strict(bound_run)[0]
    for name in ("draft-validation.json", "mechanism-blueprint-validation.json"):
        (bound_run.run_dir / name).unlink()

    saved = _save(bound_run, token, candidate)
    assert saved["status"] == "saved", saved
    context = mechanism_evidence.review_context(
        bound_run, [original], run_store.read_artifact_selection(bound_run), candidate
    )
    assert context["draftMarker"] == original["mechanismEvidence"]["draftMarker"]
    assert not (bound_run.run_dir / "draft-validation.json").exists()
    assert not (bound_run.run_dir / "mechanism-blueprint-validation.json").exists()


@pytest.mark.parametrize("after_save", [False, True])
def test_deleting_bundle_cannot_downgrade_to_legacy_trust(tmp_path, monkeypatch, after_save):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    if after_save:
        assert _save(bound_run, token, candidate)["status"] == "saved"
    receipt = run_store.read_trusted_evaluations_strict(bound_run)[0]
    receipt.pop("mechanismEvidence")
    for path in (
        bound_run.trusted_evaluation_path,
        bound_run.trusted_evaluations_dir / "attempt-0.json",
    ):
        path.write_text(json.dumps(receipt), encoding="utf-8")
    if after_save:
        with pytest.raises(run_store.RunStoreError, match="trusted_mechanism_evidence_mismatch"):
            mechanism_evidence.review_context(
                bound_run, [receipt], run_store.read_artifact_selection(bound_run), candidate
            )
    else:
        assert _save(bound_run, token, candidate)["errorCode"] == "trusted_mechanism_evidence_mismatch"


def test_saved_selection_bundle_hash_cannot_be_replaced(tmp_path, monkeypatch):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    _revise(bound_run, candidate)
    assert _save(bound_run, token, candidate)["status"] == "saved"
    selection = run_store.read_artifact_selection(bound_run)
    selection["mechanismEvidenceHash"] = "0" * 64
    bound_run.artifact_selection_path.write_text(json.dumps(selection), encoding="utf-8")
    with pytest.raises(run_store.RunStoreError, match="artifact_selection_receipt_mismatch"):
        mechanism_evidence.review_context(
            bound_run,
            run_store.read_trusted_evaluations_strict(bound_run),
            run_store.read_artifact_selection(bound_run),
            candidate,
        )


def _baseline_output(bound_run, candidate, evaluated):
    prompt = agent_submission_payload()["agentRefinedBuildPrompt"]
    prompt.update(
        prompt_id=bound_run.manifest["promptId"],
        request_ref=bound_run.manifest["requestRef"],
        version_context=candidate.version_context.model_dump(mode="json", by_alias=True),
    )
    audit = {
        "auditId": "audit:review-boundary",
        "attemptIndex": 0,
        "candidateId": candidate.candidate_id,
        "snapshotId": evaluated["transientBuildState"]["snapshotId"],
        "classification": "no_material_failure",
        "retryDecision": "accept",
        "summary": "后续机制探索仅影响新增候选，接受原先通过的基础版本。",
        "plannedChanges": [],
        "retainedCaveats": ["仍需实际游戏验证。"],
        "versionContext": candidate.version_context.model_dump(mode="json", by_alias=True),
        "noRawMaterial": True,
    }
    return {
        "schemaVersion": 2,
        "runContext": bound_run.manifest["runContext"],
        "packetId": bound_run.manifest["packetId"],
        "agentRefinedBuildPrompt": prompt,
        "prototypeBuildCandidate": candidate.model_dump(mode="json", by_alias=True),
        "failureAudit": audit,
        "generationAttempts": [
            {
                "attemptIndex": 0,
                "prototypeBuildCandidate": {"candidateId": candidate.candidate_id},
                "failureAudit": deepcopy(audit),
            }
        ],
    }


def test_historical_review_recovers_without_current_markers_and_rejects_tampering(
    tmp_path, monkeypatch
):
    bound_run, token, candidate, evaluated = _baseline(tmp_path, monkeypatch)
    _revise(bound_run, candidate)
    marker_paths = [
        bound_run.run_dir / "draft-validation.json",
        bound_run.run_dir / "mechanism-blueprint-validation.json",
    ]
    for path in marker_paths:
        path.unlink()
    output = _baseline_output(bound_run, candidate, evaluated)

    before_save = create_build.validate_generation_output(bound_run.run_id, token, output)
    assert before_save["status"] == "rejected", before_save
    assert before_save["errorCode"] == "generation_blueprint_validation_required"
    assert not (bound_run.run_dir / "review-consumed").exists()
    assert _save(bound_run, token, candidate)["status"] == "saved"

    validated = create_build.validate_generation_output(bound_run.run_id, token, output)
    assert validated["status"] == "accepted", validated
    assert validated["validationOnly"] is True
    assert not (bound_run.run_dir / "review-consumed").exists()
    assert all(not path.exists() for path in marker_paths)

    tampered = deepcopy(output)
    tampered["prototypeBuildCandidate"]["mechanismBlueprint"]["document"] += "篡改历史机制。"
    rejected = create_build.complete_generation_review(bound_run.run_id, token, tampered)
    assert rejected["errorCode"] == "generation_baseline_candidate_mismatch", rejected
    assert not (bound_run.run_dir / "review-consumed").exists()

    completed = create_build.complete_generation_review(bound_run.run_id, token, output)
    assert completed["status"] == "accepted", completed
    assert completed["validationOnly"] is False
    assert (bound_run.run_dir / "review-consumed").exists()
    persisted = json.loads((bound_run.run_dir / "review-result.json").read_text(encoding="utf-8"))
    assert persisted["humanReviewPacket"]["prototypeBuildCandidate"]["mechanismBlueprint"] == (
        candidate.mechanism_blueprint.model_dump(mode="json", by_alias=True)
    )
    assert all(not path.exists() for path in marker_paths)


def test_draft_revision_during_artifact_save_cannot_strand_published_selection(
    tmp_path, monkeypatch
):
    bound_run, token, candidate, evaluated = _baseline(tmp_path, monkeypatch)
    output = _baseline_output(bound_run, candidate, evaluated)
    marker = json.loads((bound_run.run_dir / "draft-validation.json").read_text(encoding="utf-8"))
    observed = []

    def concurrent_draft(_engine, _xml):
        monkeypatch.setattr(
            create_build.mechanism_signature,
            "observe",
            lambda *_args, **_kwargs: {
                "ok": True,
                "signature": marker["mechanismSignature"],
                "signatureHash": marker["mechanismSignatureHash"],
                "calculationContext": marker["calculationContext"],
                "stateHash": "sha256:" + "a" * 64,
            },
        )
        observed.append(
            create_build.validate_generation_draft(
                bound_run.run_id,
                token,
                output,
                active_engine=_ActiveEngine(),
                offense_skill_group_index=1,
                expected_skill_name="Lightning Arrow",
            )
        )
        return {"status": "passed"}

    monkeypatch.setattr(artifacts, "_validate_pob_round_trip", concurrent_draft)
    saved = _save(bound_run, token, candidate, scope="not_applicable", reason=None)
    assert observed
    if observed[0]["status"] == "accepted":
        assert saved["status"] == "rejected", saved
        assert not bound_run.artifact_selection_path.exists()
    else:
        assert observed[0]["errorCode"] == "generation_evaluation_in_progress"
        assert saved["status"] == "saved", saved
        validated = create_build.validate_generation_output(bound_run.run_id, token, output)
        assert validated["status"] == "accepted", validated
