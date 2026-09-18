from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timezone
import json

import pytest

from scripts import create_build
from server.compute.state import build_state_hash
from server.generation import (
    artifacts,
    evaluation,
    evaluation_snapshots,
    evidence_authority,
    mechanism_evidence,
    mechanism_signature,
    models,
    run_store,
)
from tests.test_generation_blueprint import EVIDENCE_REF, _blueprint
from tests.test_phase5_generation_evaluation import (
    BUILD_XML,
    _ActiveEngine,
    _JudgeEngine,
    _judge_result,
    _version_context,
)
from tests.test_phase5_prototype_models import agent_submission_payload
from tests.test_phase6_final_artifacts import _bound_run


def _candidate(bound_run):
    payload = agent_submission_payload()["prototypeBuildCandidate"]
    version = _version_context()
    version["research_memory_ref"] = "disabled:no_memory_baseline"
    blueprint = _blueprint()
    blueprint_hash = models.mechanism_blueprint_hash(blueprint)
    payload.update(
        {
            "candidate_id": "candidate:baseline",
            "prompt_ref": bound_run.manifest["promptId"],
            "version_context": version,
            "research_memory_use": None,
            "research_execution_plan": None,
            "memory_references": [],
            "mechanism_blueprint_ref": f"gbp-{blueprint_hash[:16]}",
            "mechanism_blueprint": blueprint,
            "tool_references": [
                {
                    "tool_name": "search_graph_components", "query_ref": EVIDENCE_REF,
                    "summary": "Synthetic graph evidence inspected by the test Agent.",
                    "evidence_kind": "agent_reviewed",
                    "review_basis": "Agent inspected the synthetic graph result and its mechanism conditions.",
                },
                {
                    "tool_name": "get_freshness_report",
                    "query_ref": "freshness:baseline",
                    "summary": "已核对目标版本。",
                },
                {
                    "tool_name": "validate_generation_blueprint",
                    "query_ref": f"gbp-{blueprint_hash[:16]}",
                    "summary": "已验证基础机制。",
                },
            ],
        }
    )
    return models.PrototypeBuildCandidate.model_validate(payload)


def _freeze(bound_run, candidate, *, xml=BUILD_XML, supports=None):
    blueprint_hash = models.mechanism_blueprint_hash(candidate.mechanism_blueprint)
    blueprint_marker = {
        "schemaVersion": 1,
        "candidateId": candidate.candidate_id,
        "researchMemoryRef": candidate.version_context.research_memory_ref,
        "researchExecutionContractRef": None,
        "researchExecutionStructureHash": None,
        "blueprintRef": candidate.mechanism_blueprint_ref,
        "blueprintHash": blueprint_hash,
        "validatedAt": datetime.now(timezone.utc).isoformat(),
        "noRawMaterial": True,
    }
    _add_evidence_audit(blueprint_marker, candidate)
    signature = {
        "offenseSkillGroupIndex": 1,
        "activeSkillName": "Lightning Arrow",
        "supportNames": supports or ["Martial Tempo"],
        "resourceCostDomains": ["mana"],
        "hitDamageTypes": ["lightning"],
        "hitDamageTypesModelled": True,
    }
    draft_marker = {
        "schemaVersion": 2,
        "candidateId": candidate.candidate_id,
        "researchMemoryRef": candidate.version_context.research_memory_ref,
        "researchPremiseAuditReady": False,
        "researchExecutionContractRef": None,
        "researchExecutionStructureHash": None,
        "mechanismBlueprintRef": candidate.mechanism_blueprint_ref,
        "mechanismBlueprintHash": blueprint_hash,
        "mechanismSignatureHash": mechanism_signature.signature_hash(signature),
        "mechanismSignature": signature,
        "calculationContext": {"groupIndex": 1, "activeIndex": 1, "skillName": "Lightning Arrow"},
        "buildStateHash": build_state_hash(xml),
        "validatedAt": datetime.now(timezone.utc).isoformat(),
        "noRawMaterial": True,
    }
    draft_marker.update(evidenceAuditHash=blueprint_marker["evidenceAuditHash"],
                        designToolsHash=evidence_authority.design_tools_hash(candidate),
                        designToolRefs=[row["queryRef"] for row in evidence_authority.design_tool_refs(candidate)])
    evidence_uses = evidence_authority.design_evidence_uses(candidate.research_execution_plan)
    draft_marker.update(designEvidenceUses=evidence_uses,
                        designEvidenceUsesHash=evidence_authority.audit_hash(evidence_uses))
    for name, payload in (
        ("draft-validation.json", draft_marker),
        ("mechanism-blueprint-validation.json", blueprint_marker),
    ):
        (bound_run.run_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    mechanism_evidence.remember_validated_draft(
        bound_run, candidate, draft_marker, blueprint_marker
    )
    return draft_marker, blueprint_marker


def _add_evidence_audit(marker, candidate):
    error, audit = evidence_authority.blueprint_audit(
        candidate.mechanism_blueprint, candidate.tool_references, set())
    assert error is None, error
    marker.update(evidenceAudit=audit, evidenceAuditHash=evidence_authority.audit_hash(audit))


def _baseline(tmp_path, monkeypatch, *, level=68):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)
    manifest_path = run_dir / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["experimentContext"] = {"memoryMode": "no_memory", "mechanismBlueprintRequired": True}
    manifest["agentOutputContractVersion"] = run_store.CURRENT_AGENT_OUTPUT_CONTRACT_VERSION
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    bound_run = run_store.load_bound_run(run_id, token)
    candidate = _candidate(bound_run)
    xml = BUILD_XML.replace('level="68"', f'level="{level}"')
    marker, _ = _freeze(bound_run, candidate, xml=xml)
    monkeypatch.setattr(
        evaluation.mechanism_signature,
        "observe",
        lambda *_args, **_kwargs: {
            "ok": True,
            "signature": marker["mechanismSignature"],
            "signatureHash": marker["mechanismSignatureHash"],
        },
    )

    def fake_safe(factory, *, snapshot_id, **_kwargs):
        factory()
        return _judge_result(snapshot_id)

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)

    class LevelJudge(_JudgeEngine):
        def get_build(self):
            return {**super().get_build(), "level": level}

    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(
            xml,
            build={
                "level": level,
                "ascendancy": "Deadeye",
                "gear": {
                    "Flask 1": {"name": "Fixture Unique Life Flask", "rarity": "unique"},
                    "Flask 2": {"name": "Fixture Unique Mana Flask", "rarity": "unique"},
                }
                if level >= 80
                else {},
            },
        ),
        run_id=run_id,
        run_token=token,
        candidate_id=candidate.candidate_id,
        version_context=candidate.version_context.model_dump(mode="json", by_alias=True),
        engine_factory=LevelJudge,
    )
    assert result["status"] == "evaluated", result
    assert "mechanismEvidence" not in result
    assert len(result["mechanismEvidenceHash"]) == 64
    return bound_run, token, candidate, result


def _revise(bound_run, candidate):
    changed = candidate.model_copy(deep=True)
    changed.mechanism_blueprint.document += "\n后续质量探索修改辅助和资源机制。"
    changed.mechanism_blueprint_ref = (
        "gbp-" + models.mechanism_blueprint_hash(changed.mechanism_blueprint)[:16]
    )
    _freeze(bound_run, changed, supports=["Longshot"])


def _save(
    bound_run,
    token,
    candidate,
    *,
    scope="candidate_delta_only",
    reason="后续辅助探索仅影响新增候选，保留原先通过的基础版本。",
):
    return artifacts.save_final_build_artifact(
        _ActiveEngine(),
        run_id=bound_run.run_id,
        run_token=token,
        candidate_id=candidate.candidate_id,
        attempt_index=0,
        selection_reason=reason,
        later_findings_scope=scope,
    )


def test_restores_exact_bundle_after_blueprint_and_draft_revision(tmp_path, monkeypatch):
    bound_run, token, candidate, result = _baseline(tmp_path, monkeypatch)
    original = run_store.read_trusted_evaluations_strict(bound_run)[0]
    _revise(bound_run, candidate)
    current_marker = (bound_run.run_dir / "draft-validation.json").read_bytes()

    saved = _save(bound_run, token, candidate)

    assert saved["status"] == "saved", saved
    assert saved["artifactSelection"]["restoredPassingBaseline"] is True
    design = saved["selectedDesignEvidence"]
    assert set(design) == {
        "toolReferences", "evidenceAudit",
        "mechanismEvidenceHash",
        "mechanismBlueprintRef",
        "mechanismBlueprint",
        "researchMemoryUse",
        "researchExecutionPlan",
    }
    assert design["mechanismBlueprintRef"] == candidate.mechanism_blueprint_ref
    assert design["mechanismBlueprint"] == candidate.mechanism_blueprint.model_dump(
        mode="json", by_alias=True
    )
    assert design["mechanismEvidenceHash"] == original["mechanismEvidence"]["bundleHash"]
    assert models.validate_no_raw_or_hidden_reasoning(design)["status"] == "accepted"
    design["mechanismBlueprint"]["document"] += " local response edit"
    assert run_store.read_trusted_evaluations_strict(bound_run)[0] == original
    selection = run_store.read_artifact_selection(bound_run)
    context = mechanism_evidence.review_context(bound_run, [original], selection, candidate)
    assert context["mechanismBinding"] == original["mechanismBinding"]
    assert context["draftMarker"] == original["mechanismEvidence"]["draftMarker"]
    assert (bound_run.run_dir / "draft-validation.json").read_bytes() == current_marker
    assert (
        evaluation_snapshots.read(
            run_id=bound_run.run_id,
            attempt_index=0,
            candidate_id=candidate.candidate_id,
            source_hash=result["transientBuildState"]["sourceHash"],
        )
        is None
    )


@pytest.mark.parametrize("scope", ["not_applicable", "baseline_affected", "unknown"])
def test_revised_mechanism_requires_explicit_delta_scope(tmp_path, monkeypatch, scope):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    _revise(bound_run, candidate)
    result = _save(bound_run, token, candidate, scope=scope)
    assert result["status"] == "rejected"
    assert not bound_run.artifact_selection_path.exists()


def test_revised_mechanism_requires_selection_reason(tmp_path, monkeypatch):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    _revise(bound_run, candidate)
    assert (
        _save(bound_run, token, candidate, reason=None)["errorCode"]
        == "baseline_selection_reason_required"
    )


def test_baseline_bundle_requires_live_judge_snapshot(tmp_path, monkeypatch):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    _revise(bound_run, candidate)
    evaluation_snapshots.forget(run_id=bound_run.run_id)
    assert (
        _save(bound_run, token, candidate)["errorCode"] == "trusted_evaluation_snapshot_unavailable"
    )


def test_bundle_tampering_cannot_replace_snapshot_anchor(tmp_path, monkeypatch):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    _revise(bound_run, candidate)
    receipt = run_store.read_trusted_evaluations_strict(bound_run)[0]
    receipt["mechanismEvidence"]["draftMarker"]["validatedAt"] = datetime.now(
        timezone.utc
    ).isoformat()
    evidence = receipt["mechanismEvidence"]
    evidence["bundleHash"] = mechanism_evidence._hash(
        {key: value for key, value in evidence.items() if key != "bundleHash"}
    )
    for path in (
        bound_run.trusted_evaluation_path,
        bound_run.trusted_evaluations_dir / "attempt-0.json",
    ):
        path.write_text(json.dumps(receipt), encoding="utf-8")
    assert _save(bound_run, token, candidate)["errorCode"] == "trusted_mechanism_evidence_mismatch"


@pytest.mark.parametrize(
    "field,value",
    [
        ("runId", "other-run"),
        ("candidateId", "candidate:other"),
        ("attemptIndex", 1),
        ("sourceHash", "0" * 16),
        ("semanticStateHash", "sha256:" + "0" * 64),
    ],
)
def test_bundle_identity_cannot_drift_from_receipt(tmp_path, monkeypatch, field, value):
    bound_run, _, _, _ = _baseline(tmp_path, monkeypatch)
    receipt = run_store.read_trusted_evaluations_strict(bound_run)[0]
    evidence = receipt["mechanismEvidence"]
    evidence[field] = value
    evidence["bundleHash"] = mechanism_evidence._hash(
        {key: item for key, item in evidence.items() if key != "bundleHash"}
    )
    assert mechanism_evidence.valid_evaluation_evidence(receipt) is False


def test_review_context_cannot_select_another_candidate(tmp_path, monkeypatch):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    _revise(bound_run, candidate)
    assert _save(bound_run, token, candidate)["status"] == "saved"
    other = candidate.model_copy(update={"candidate_id": "candidate:other"})
    with pytest.raises(run_store.RunStoreError, match="generation_baseline_candidate_mismatch"):
        mechanism_evidence.review_context(
            bound_run,
            run_store.read_trusted_evaluations_strict(bound_run),
            run_store.read_artifact_selection(bound_run),
            other,
        )


def test_review_context_rejects_forged_selection_without_artifact(tmp_path, monkeypatch):
    bound_run, _, candidate, _ = _baseline(tmp_path, monkeypatch)
    receipt = run_store.read_trusted_evaluations_strict(bound_run)[0]
    evidence = receipt["mechanismEvidence"]
    assert run_store.write_artifact_selection(
        bound_run,
        {
            "artifactId": "final-build:forged",
            "candidateId": candidate.candidate_id,
            "selectedAttemptIndex": 0,
            "selectedEvaluationRef": f"run:{bound_run.run_id}:attempt:0",
            "selectionOutcome": "baseline_restored_after_regression",
            "selectionReason": "仅候选增量失败。",
            "laterFindingsScope": "candidate_delta_only",
            "mechanismEvidenceHash": evidence["bundleHash"],
            "sourceHash": evidence["sourceHash"],
            "semanticStateHash": evidence["semanticStateHash"],
        },
    )
    with pytest.raises(run_store.RunStoreError, match="final_artifact_corrupt"):
        mechanism_evidence.review_context(
            bound_run, [receipt], run_store.read_artifact_selection(bound_run), candidate
        )


def test_validated_draft_freeze_uses_deepcopy(tmp_path, monkeypatch):
    bound_run, _, candidate, _ = _baseline(tmp_path, monkeypatch)
    marker, blueprint = _freeze(bound_run, candidate)
    original = deepcopy(marker)
    marker["calculationContext"]["activeIndex"] = 2
    blueprint["blueprintHash"] = "tampered"
    candidate.mechanism_blueprint.document += " changed after freeze"
    frozen = mechanism_evidence.read_validated_draft(bound_run, candidate_id=candidate.candidate_id)
    assert frozen["draftMarker"] == original


def test_baseline_output_and_review_use_the_saved_historical_bundle(tmp_path, monkeypatch):
    bound_run, token, candidate, result = _baseline(tmp_path, monkeypatch)
    _revise(bound_run, candidate)
    assert _save(bound_run, token, candidate)["status"] == "saved"
    prompt = agent_submission_payload()["agentRefinedBuildPrompt"]
    prompt.update(
        {
            "prompt_id": bound_run.manifest["promptId"],
            "request_ref": bound_run.manifest["requestRef"],
            "version_context": candidate.version_context.model_dump(mode="json", by_alias=True),
        }
    )
    payload = {
        "schemaVersion": 2,
        "runContext": bound_run.manifest["runContext"],
        "packetId": bound_run.manifest["packetId"],
        "agentRefinedBuildPrompt": prompt,
        "prototypeBuildCandidate": candidate.model_dump(mode="json", by_alias=True),
        "toolFeedbackEvents": [],
        "generationAttempts": [
            {
                "attemptIndex": 0,
                "prototypeBuildCandidate": {"candidateId": candidate.candidate_id},
                "failureAudit": {
                    "auditId": "audit:baseline",
                    "attemptIndex": 0,
                    "candidateId": candidate.candidate_id,
                    "snapshotId": result["transientBuildState"]["snapshotId"],
                    "classification": "no_material_failure",
                    "retryDecision": "accept",
                    "summary": "后续修改仅影响新候选，原基础构筑仍合法并通过Judge。",
                    "plannedChanges": [],
                    "retainedCaveats": ["机制恢复采用已保存的精确历史验证证据。"],
                    "versionContext": candidate.version_context.model_dump(
                        mode="json", by_alias=True
                    ),
                    "noRawMaterial": True,
                },
            }
        ],
    }
    validated = create_build.validate_generation_output(bound_run.run_id, token, payload)
    assert validated["status"] == "accepted", validated
    assert not (bound_run.run_dir / "review-consumed").exists()
    reviewed = create_build.complete_generation_review(bound_run.run_id, token, payload)
    assert reviewed["status"] == "accepted", reviewed
    assert (bound_run.run_dir / "review-consumed").is_file()


def test_artifact_save_keeps_existing_judge_lock(tmp_path, monkeypatch):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    lock = bound_run.run_dir / "evaluation-lock"
    lock.write_text("owned-by-running-judge", encoding="utf-8")
    result = _save(bound_run, token, candidate)
    assert result["errorCode"] == "generation_evaluation_in_progress"
    assert lock.read_text(encoding="utf-8") == "owned-by-running-judge"


def test_artifact_publication_excludes_new_judge_attempt(tmp_path, monkeypatch):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    observed = []

    def concurrent_judge(_engine, _xml):
        observed.append(
            evaluation.evaluate_generation_candidate(
                _ActiveEngine(),
                run_id=bound_run.run_id,
                run_token=token,
                candidate_id=candidate.candidate_id,
                version_context=candidate.version_context.model_dump(mode="json", by_alias=True),
                engine_factory=_JudgeEngine,
            )
        )
        return {"status": "passed"}

    monkeypatch.setattr(artifacts, "_validate_pob_round_trip", concurrent_judge)
    assert _save(bound_run, token, candidate)["status"] == "saved"
    assert observed[0]["errorCode"] == "generation_evaluation_in_progress"
    assert len(run_store.read_trusted_evaluations_strict(bound_run)) == 1
    after = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=bound_run.run_id,
        run_token=token,
        candidate_id=candidate.candidate_id,
        version_context=candidate.version_context.model_dump(mode="json", by_alias=True),
        engine_factory=_JudgeEngine,
    )
    assert after["errorCode"] == "final_artifact_already_exists"
    assert after["attemptConsumed"] is False


class _LifecycleEngine(_ActiveEngine):
    def transaction_lock(self):
        return nullcontext()

    def load_build_xml(self, xml, name=""):
        self.xml = xml

    def get_stats(self, _keys=None):
        return {"stats": {}}


def test_artifact_refreshes_lifecycle_without_upgrading_other_quality_limits(tmp_path, monkeypatch):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    original_receipt = run_store.read_trusted_evaluations_strict(bound_run)[0]
    state_hash = original_receipt["transientBuildState"]["semanticStateHash"]
    target = {"groupIndex": 1, "activeIndex": 1, "skillName": "Lightning Arrow"}
    newer = {"status": "passed", "pass": True, "stateHash": state_hash, "observationTarget": target}
    monkeypatch.setattr(
        artifacts.validation_checkpoint,
        "inspect_generation_checkpoint",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "stateHash": state_hash,
            "calculationContext": target,
            "lifecycleVerification": newer,
        },
    )
    engine = _LifecycleEngine()
    saved = artifacts.save_final_build_artifact(
        engine,
        run_id=bound_run.run_id,
        run_token=token,
        candidate_id=candidate.candidate_id,
        attempt_index=0,
    )
    assert saved["status"] == "saved", saved
    manifest = saved["finalBuildArtifact"]
    assert manifest["lifecycleVerification"]["pass"] is True
    assert manifest["deliveryStatus"] == "candidate"
    assert manifest["createQualityChecklist"] == original_receipt["createQualityChecklist"]
    assert run_store.read_trusted_evaluations_strict(bound_run)[0] == original_receipt
    assert engine.get_xml() == BUILD_XML


@pytest.mark.parametrize("failure", ["wrong_target", "wrong_hash", "restore_failed"])
def test_artifact_lifecycle_refresh_fails_closed(tmp_path, monkeypatch, failure):
    bound_run, token, candidate, _ = _baseline(tmp_path, monkeypatch)
    state_hash = build_state_hash(BUILD_XML)
    target = {
        "groupIndex": 1,
        "activeIndex": 2 if failure == "wrong_target" else 1,
        "skillName": "Lightning Arrow",
    }
    returned_hash = "sha256:" + "0" * 64 if failure == "wrong_hash" else state_hash
    monkeypatch.setattr(
        artifacts.validation_checkpoint,
        "inspect_generation_checkpoint",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "stateHash": returned_hash,
            "calculationContext": target,
            "lifecycleVerification": {
                "status": "passed",
                "pass": True,
                "stateHash": returned_hash,
                "observationTarget": target,
            },
        },
    )
    engine = _LifecycleEngine()
    if failure == "restore_failed":
        original_load = engine.load_build_xml

        def broken_restore(xml, name=""):
            if name == "final-artifact-lifecycle-restore":
                raise RuntimeError("restore failed")
            return original_load(xml, name)

        monkeypatch.setattr(engine, "load_build_xml", broken_restore)
    saved = artifacts.save_final_build_artifact(
        engine,
        run_id=bound_run.run_id,
        run_token=token,
        candidate_id=candidate.candidate_id,
        attempt_index=0,
    )
    assert saved["status"] == "rejected"
    assert not bound_run.artifact_selection_path.exists()
    if failure == "restore_failed":
        assert saved["recoveryRequired"] is True
        assert saved["errorCode"] == "final_lifecycle_restore_failed"
    else:
        assert saved["errorCode"] == "final_lifecycle_snapshot_mismatch"


@pytest.mark.parametrize("level", [80, 90])
@pytest.mark.parametrize("restore_failure", ["exception", "wrong_state"])
def test_round_trip_restore_failure_blocks_artifact_at_every_level(
    tmp_path, monkeypatch, level, restore_failure
):
    bound_run, token, candidate, result = _baseline(tmp_path, monkeypatch, level=level)
    assert int(result["transientBuildState"]["safeSummary"]["level"]) == level
    original_xml = BUILD_XML.replace('level="68"', f'level="{level}"')
    engine = _LifecycleEngine(original_xml)
    original_load = engine.load_build_xml

    def broken_restore(xml, name=""):
        if name == "final-artifact-round-trip-restore":
            if restore_failure == "exception":
                raise RuntimeError("restore failed")
            xml = xml.replace(f'level="{level}"', f'level="{level + 1}"')
        return original_load(xml, name)

    monkeypatch.setattr(engine, "load_build_xml", broken_restore)
    saved = artifacts.save_final_build_artifact(
        engine,
        run_id=bound_run.run_id,
        run_token=token,
        candidate_id=candidate.candidate_id,
        attempt_index=0,
    )
    assert saved["errorCode"] == "final_pob_round_trip_restore_failed"
    assert saved["recoveryRequired"] is True
    assert not bound_run.artifact_selection_path.exists()
    assert not (artifacts.artifacts_dir() / bound_run.run_id).exists()


def test_round_trip_proves_restored_original_state_hash():
    original_xml = BUILD_XML.replace('level="68"', 'level="80"')
    engine = _LifecycleEngine(original_xml)
    checked = artifacts._validate_pob_round_trip(engine, BUILD_XML)
    assert checked["status"] == "passed"
    assert checked["stateRestored"] is True
    assert checked["restoredStateHash"] == build_state_hash(original_xml)
    assert engine.get_xml() == original_xml


def test_public_draft_validation_freezes_once_without_refreshing_unchanged_marker(
    tmp_path, monkeypatch
):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)
    manifest_path = run_dir / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["experimentContext"] = {"memoryMode": "no_memory", "mechanismBlueprintRequired": True}
    manifest["agentOutputContractVersion"] = run_store.CURRENT_AGENT_OUTPUT_CONTRACT_VERSION
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    bound_run = run_store.load_bound_run(run_id, token)
    candidate = _candidate(bound_run)
    blueprint_marker = {
        "schemaVersion": 1,
        "candidateId": candidate.candidate_id,
        "researchMemoryRef": candidate.version_context.research_memory_ref,
        "blueprintRef": candidate.mechanism_blueprint_ref,
        "blueprintHash": models.mechanism_blueprint_hash(candidate.mechanism_blueprint),
        "noRawMaterial": True,
    }
    _add_evidence_audit(blueprint_marker, candidate)
    blueprint_path = run_dir / "mechanism-blueprint-validation.json"
    blueprint_path.write_text(json.dumps(blueprint_marker), encoding="utf-8")
    blueprint_bytes = blueprint_path.read_bytes()
    signature = {
        "offenseSkillGroupIndex": 1,
        "activeSkillName": "Lightning Arrow",
        "supportNames": ["Martial Tempo"],
        "resourceCostDomains": ["mana"],
        "hitDamageTypes": ["lightning"],
        "hitDamageTypesModelled": True,
    }
    observed = {
        "ok": True,
        "signature": signature,
        "signatureHash": mechanism_signature.signature_hash(signature),
        "calculationContext": {"groupIndex": 1, "activeIndex": 1, "skillName": "Lightning Arrow"},
        "stateHash": build_state_hash(BUILD_XML),
    }
    monkeypatch.setattr(
        create_build.mechanism_signature, "observe", lambda *_args, **_kwargs: observed
    )
    remember = mechanism_evidence.remember_validated_draft
    calls = []

    def counted_remember(*args, **kwargs):
        calls.append(True)
        return remember(*args, **kwargs)

    monkeypatch.setattr(mechanism_evidence, "remember_validated_draft", counted_remember)
    prompt = agent_submission_payload()["agentRefinedBuildPrompt"]
    prompt.update(
        {
            "prompt_id": manifest["promptId"],
            "request_ref": manifest["requestRef"],
            "version_context": candidate.version_context.model_dump(mode="json", by_alias=True),
        }
    )
    payload = {
        "runContext": manifest["runContext"],
        "packetId": manifest["packetId"],
        "agentRefinedBuildPrompt": prompt,
        "prototypeBuildCandidate": candidate.model_dump(mode="json", by_alias=True),
    }
    arguments = {
        "active_engine": _ActiveEngine(),
        "offense_skill_group_index": 1,
        "expected_skill_name": "Lightning Arrow",
    }
    accepted = create_build.validate_generation_draft(run_id, token, payload, **arguments)
    assert accepted["status"] == "accepted", accepted
    frozen = mechanism_evidence.read_validated_draft(bound_run, candidate_id=candidate.candidate_id)
    assert frozen is not None
    assert frozen["mechanismBlueprint"] == payload["prototypeBuildCandidate"]["mechanismBlueprint"]
    marker_path = run_dir / "draft-validation.json"
    marker_bytes = marker_path.read_bytes()
    assert frozen["draftMarker"] == json.loads(marker_bytes)
    unchanged = create_build.validate_generation_draft(run_id, token, payload, **arguments)
    assert unchanged["status"] == "already_validated"
    assert len(calls) == 1
    assert marker_path.read_bytes() == marker_bytes
    assert blueprint_path.read_bytes() == blueprint_bytes
    frozen_before = deepcopy(frozen)
    frozen["draftMarker"]["calculationContext"]["activeIndex"] = 2
    payload["prototypeBuildCandidate"]["mechanismBlueprint"]["document"] += "后续调用者修改。"
    signature["supportNames"].append("Longshot")
    assert (
        mechanism_evidence.read_validated_draft(bound_run, candidate_id=candidate.candidate_id)
        == frozen_before
    )
    assert not bound_run.trusted_evaluations_dir.exists()
