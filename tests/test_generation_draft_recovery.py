"""CR06/CR07 public producer-to-consumer regressions with isolated runtime data.

Only receipt lookup, execution-contract construction and numerical engine observations are
controlled. Blueprint, Draft, provenance/premise checks, Judge binding, artifact and review
remain the production paths. No real PoB process or Research run is started.
"""

from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from server import main
from server.compute.state import build_state_hash
from server.generation import (
    evaluation,
    evaluation_snapshots,
    mechanism_evidence,
    mechanism_signature,
    models,
    run_store,
)
from server.knowledge import research_execution, research_memory
from tests.test_create_quality_and_research_cases import _receipt
from tests.test_generation_blueprint import EVIDENCE_REF
from tests.test_generation_mechanism_baseline import _candidate
from tests.test_phase5_generation_evaluation import (
    BUILD_XML,
    _ActiveEngine,
    _JudgeEngine,
    _judge_result,
)
from tests.test_phase5_prototype_models import agent_submission_payload
from tests.test_phase6_final_artifacts import _bound_run
from tests.test_research_execution_contract import AUTH_PACKAGE, CONTRACT_REF, _decision


AUTH = "dq-1111111111111111"
DEEP = "dq-2222222222222222"
DISCOVERY = "dq-3333333333333333"
FAMILY = "bf-test-family"
RECORD = "drr-1111111111111111"
SOLUTION = "drr-2222222222222222"
PREMISE = "rp-3333333333333333"
CASE = "case:authoritative"


class DraftEngine(_ActiveEngine):
    def transaction_lock(self):
        return nullcontext()

    def load_build_xml(self, xml, name=""):
        self.xml = xml
        return {"ok": True}

def _usage(*, resolved=False):
    return {
        "retrievalOutcome": "matched",
        "dedupeQueryRefs": [AUTH, DEEP] if resolved else [AUTH],
        "selectedKnowledgeScope": "global_seed",
        "selectedSourceCaseRef": CASE,
        "buildFamilyKeys": [FAMILY],
        "componentKeys": ["skill:LightningArrowPlayer"],
        "deepRecordIds": [RECORD, SOLUTION] if resolved else [RECORD],
        "insightDecisions": [
            {
                "sourceRefs": [RECORD],
                "decision": "adopted",
                "summary": "保留授权来源的资源机制。",
                "application": "使用原蓝图已经设计的恢复组件。",
            }
        ],
        "premiseAuditVersion": 1,
        "premiseDecisions": [
            {
                "premiseId": PREMISE,
                "decision": "resolved" if resolved else "caveated",
                "resolutionRefs": [SOLUTION] if resolved else [],
                "application": "同来源解决记录确认原机制的恢复条件。",
                **({} if resolved else {"caveat": "尚未取得该条件的本轮深读解决记录。"}),
            }
        ],
    }


def _receipts():
    result = {}
    for ref in (AUTH, DEEP, DISCOVERY):
        row = _receipt(ref, "retrieval:" + ref, CASE)
        row["lastSeenAt"] = datetime.now(timezone.utc).isoformat()
        row["request"] = {"detailLevel": "family" if ref == DISCOVERY else "record"}
        row["result"].update(
            {
                "requestedGamePatch": "0.5.4",
                "familyAvailableSourceCaseLanes": [
                    {"knowledgeScope": "global_seed", "sourceCaseRef": CASE}
                ],
                "comparisonRequiredCount": 0,
                "buildFamilies": [
                    {"buildFamilyKey": FAMILY, "createEligibility": {"status": "authorized"}}
                ],
                "deepRecordIds": [SOLUTION] if ref == DEEP else [RECORD],
                "deepReadRecordIds": [SOLUTION] if ref == DEEP else [RECORD],
                "familyRecordCoverage": [
                    {"buildFamilyKey": FAMILY, "requiredDeepReadRecordIds": [RECORD]}
                ],
                "premiseAuditVersion": 1,
                "familyPremiseCatalog": [
                    {
                        "buildFamilyKey": FAMILY,
                        "premiseId": PREMISE,
                        "premiseType": "failure_condition",
                    }
                ],
            }
        )
        result[ref] = row
    return result


def _blueprint_payload(candidate):
    return {
        key: deepcopy(candidate[key])
        for key in (
            "candidateId",
            "versionContext",
            "researchMemoryUse",
            "researchExecutionPlan",
            "toolReferences",
            "mechanismBlueprint",
            "noRawMaterial",
        )
    }


def _setup(tmp_path, monkeypatch, *, memory=True):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)
    path = run_dir / "run-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["agentOutputContractVersion"] = run_store.CURRENT_AGENT_OUTPUT_CONTRACT_VERSION
    manifest["experimentContext"] = {
        "memoryMode": "memory_assisted" if memory else "no_memory",
        "mechanismBlueprintRequired": True,
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    bound = run_store.load_bound_run(run_id, token)
    catalog = _receipts()
    monkeypatch.setattr(
        research_memory.ResearchMemoryService,
        "read_query_receipt",
        lambda _s, ref: deepcopy(catalog.get(ref)),
    )
    contract = {
        "status": "ready",
        "contractRef": CONTRACT_REF,
        "selectedDesignCaseRef": CASE,
        "comparisonCaseRefs": [],
        "authoritativeDeepReadRecordIds": [RECORD],
        "comparisonDeepReadRecordIds": [],
        "reviewRequiredPackageIds": [AUTH_PACKAGE],
        "packages": [
            {
                "packageId": AUTH_PACKAGE,
                "recordId": RECORD,
                "authority": "authoritative",
                "sourceCaseRefs": [CASE],
            }
        ],
    }
    monkeypatch.setattr(
        research_execution, "construct_from_research_use", lambda *_a, **_k: deepcopy(contract)
    )
    candidate = _candidate(bound).model_dump(mode="json", by_alias=True)
    refs = [
        {
            "toolName": "get_freshness_report",
            "queryRef": "freshness:baseline",
            "summary": "隔离版本事实。",
        },
        {
            "toolName": "search_graph_components",
            "queryRef": EVIDENCE_REF,
            "summary": "隔离图身份事实。",
            "evidenceKind": "agent_reviewed",
            "reviewBasis": "Agent inspected the synthetic graph result and its mechanism conditions.",
        },
        {
            "toolName": "inspect_generation_checkpoint",
            "queryRef": "checkpoint:test-state",
            "summary": "隔离PoB观察事实。",
            "evidenceKind": "agent_reviewed",
            "reviewBasis": "Agent inspected the synthetic checkpoint output under the exact selected state.",
        },
    ]
    if memory:
        discovery = main.record_generation_family_discovery(run_id, token, DISCOVERY, FAMILY)
        assert discovery["status"] == "recorded", discovery
        candidate["versionContext"]["researchMemoryRef"] = AUTH
        candidate["researchMemoryUse"] = _usage()
        candidate["researchExecutionPlan"] = {
            "contractRef": CONTRACT_REF,
            "selectedDesignCaseRef": CASE,
            "selectedVariantRationale": "Retain the selected source case because its class, resource, defense and encounter duties match this target. The later deep read only verifies the condition of the already selected design.",
            "coherenceSummary": "Preserve the authoritative mechanism shell and verify its resource recovery under the same skill, equipment, passive and encounter responsibilities without replacing the selected variant.",
            "packageDecisions": [_decision(AUTH_PACKAGE, adopted=True)],
            "crossCaseMechanismPlans": [],
        }
        refs.extend(
            [
                {
                    "toolName": "construct_research_execution_contract",
                    "queryRef": CONTRACT_REF,
                    "summary": "隔离来源执行合同。",
                },
                {
                    "toolName": "query_research_memory",
                    "queryRef": AUTH,
                    "summary": "同run同lane的合成深读回执。",
                },
            ]
        )
    candidate["toolReferences"] = refs
    blueprint = main.validate_generation_blueprint(run_id, token, _blueprint_payload(candidate))
    assert blueprint["status"] == "accepted", blueprint
    candidate["mechanismBlueprintRef"] = blueprint["blueprintRef"]
    refs.append(
        {
            "toolName": "validate_generation_blueprint",
            "queryRef": blueprint["blueprintRef"],
            "summary": "原机制蓝图通过。",
        }
    )
    candidate = models.PrototypeBuildCandidate.model_validate(candidate).model_dump(
        mode="json", by_alias=True
    )
    prompt = agent_submission_payload()["agentRefinedBuildPrompt"]
    prompt.update(
        prompt_id=manifest["promptId"],
        request_ref=manifest["requestRef"],
        version_context=candidate["versionContext"],
    )
    payload = {
        "runContext": manifest["runContext"],
        "packetId": manifest["packetId"],
        "agentRefinedBuildPrompt": prompt,
        "prototypeBuildCandidate": candidate,
    }
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
    monkeypatch.setattr(mechanism_signature, "observe", lambda *_a, **_k: deepcopy(observed))
    monkeypatch.setattr(main, "get_engine", lambda: DraftEngine())
    # Keep the public Judge wrapper intact, replacing only its numerical engine factory.
    monkeypatch.setitem(
        evaluation.evaluate_generation_candidate.__kwdefaults__, "engine_factory", _JudgeEngine
    )

    def fake_judge(factory, *, snapshot_id, **_kwargs):
        factory()
        return _judge_result(snapshot_id)

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_judge)
    accepted = _draft(bound, token, payload)
    assert accepted["status"] == "accepted", accepted
    return bound, token, payload, catalog


def _draft(bound, token, payload):
    return main.validate_generation_draft(bound.run_id, token, payload, 1, "Lightning Arrow")


def _judge(bound, token, payload):
    candidate = payload["prototypeBuildCandidate"]
    return main.evaluate_generation_candidate(
        bound.run_id, token, candidate["candidateId"], candidate["versionContext"]
    )


def _resolved(payload):
    result = deepcopy(payload)
    candidate = result["prototypeBuildCandidate"]
    candidate["researchMemoryUse"] = _usage(resolved=True)
    candidate["toolReferences"].append(
        {
            "toolName": "query_research_memory",
            "queryRef": DEEP,
            "summary": "本轮新增同来源解决记录的深读。",
        }
    )
    candidate["memoryReferences"] = []
    result["prototypeBuildCandidate"] = models.PrototypeBuildCandidate.model_validate(
        candidate
    ).model_dump(mode="json", by_alias=True)
    return result


def _review_payload(payload, evaluated):
    candidate = payload["prototypeBuildCandidate"]
    return {
        **deepcopy(payload),
        "schemaVersion": 2,
        "toolFeedbackEvents": [],
        "generationAttempts": [
            {
                "attemptIndex": 0,
                "prototypeBuildCandidate": {"candidateId": candidate["candidateId"]},
                "failureAudit": {
                    "auditId": "audit:draft-recovery",
                    "attemptIndex": 0,
                    "candidateId": candidate["candidateId"],
                    "snapshotId": evaluated["transientBuildState"]["snapshotId"],
                    "classification": "no_material_failure",
                    "retryDecision": "accept",
                    "summary": "基础构筑通过共享硬合法性与Judge，使用所选轮次的精确设计证据。",
                    "plannedChanges": [],
                    "retainedCaveats": ["机制条件继续使用所选轮次的安全证据。"],
                    "versionContext": candidate["versionContext"],
                    "noRawMaterial": True,
                },
            }
        ],
    }


def _save_and_review(bound, token, payload, evaluated, *, restoring=False):
    saved = main.save_final_build_artifact(
        bound.run_id,
        token,
        payload["prototypeBuildCandidate"]["candidateId"],
        0,
        selection_reason="后续验证仅涉及候选增量，保留原先通过的设计。" if restoring else None,
        later_findings_scope="candidate_delta_only" if restoring else "not_applicable",
    )
    assert saved["status"] == "saved", saved
    output = _review_payload(payload, evaluated)
    validated = main.validate_generation_output(bound.run_id, token, output)
    assert validated["status"] == "accepted", validated
    reviewed = main.complete_generation_review(bound.run_id, token, output)
    assert reviewed["status"] == "accepted", reviewed
    return saved


def test_new_current_deep_read_revises_draft_without_pob_or_blueprint_change(tmp_path, monkeypatch):
    bound, token, payload, _ = _setup(tmp_path, monkeypatch)
    before = mechanism_evidence.read_validated_draft(
        bound, candidate_id=payload["prototypeBuildCandidate"]["candidateId"]
    )
    blueprint_bytes = (bound.run_dir / "mechanism-blueprint-validation.json").read_bytes()
    revised_payload = _resolved(payload)
    revised = _draft(bound, token, revised_payload)
    assert revised["status"] == "accepted", revised
    assert revised["evidenceRebuilt"] is False
    after = mechanism_evidence.read_validated_draft(
        bound, candidate_id=payload["prototypeBuildCandidate"]["candidateId"]
    )
    for key in ("mechanismBlueprintHash", "mechanismSignatureHash", "buildStateHash"):
        assert before["draftMarker"][key] == after["draftMarker"][key]
    assert (
        before["draftMarker"]["researchDecisionHash"]
        != after["draftMarker"]["researchDecisionHash"]
    )
    assert before["researchMemoryUse"]["premiseDecisions"][0]["decision"] == "caveated"
    assert after["researchMemoryUse"]["premiseDecisions"][0]["decision"] == "resolved"
    assert (bound.run_dir / "mechanism-blueprint-validation.json").read_bytes() == blueprint_bytes
    evaluated = _judge(bound, token, revised_payload)
    assert evaluated["status"] == "evaluated", evaluated
    assert evaluated["attemptIndex"] == 0 and evaluated["attemptConsumed"] is True
    _save_and_review(bound, token, revised_payload, evaluated)


@pytest.mark.parametrize("memory", [False, True])
def test_lost_bundle_blocks_judge_then_same_draft_rebuilds_original_marker(
    tmp_path, monkeypatch, memory
):
    bound, token, payload, _ = _setup(tmp_path, monkeypatch, memory=memory)
    key = mechanism_evidence._draft_key(bound)
    original_time, original_bundle = deepcopy(mechanism_evidence._DRAFTS[key])
    marker = bound.run_dir / "draft-validation.json"
    before = marker.read_bytes()
    mechanism_evidence._DRAFTS.pop(key)
    rejected = _judge(bound, token, payload)
    assert rejected["errorCode"] == "generation_draft_evidence_required", rejected
    assert rejected["attemptConsumed"] is False and rejected["attemptCount"] == 0
    assert not bound.trusted_evaluations_dir.exists()
    rebuilt = _draft(bound, token, payload)
    assert rebuilt["status"] == "accepted" and rebuilt["evidenceRebuilt"] is True, rebuilt
    assert marker.read_bytes() == before
    assert mechanism_evidence._DRAFTS[key] == (original_time, original_bundle)
    assert _draft(bound, token, payload)["status"] == "already_validated"
    evaluated = _judge(bound, token, payload)
    assert evaluated["status"] == "evaluated" and evaluated["attemptConsumed"] is True, evaluated
    assert len(evaluated["mechanismEvidenceHash"]) == 64
    # A later valid mechanism revision must still allow the original passing snapshot to save.
    changed = deepcopy(payload)
    candidate = changed["prototypeBuildCandidate"]
    candidate["mechanismBlueprint"]["document"] += "\n后续候选的资源机制意图修订。"
    blueprint = main.validate_generation_blueprint(
        bound.run_id, token, _blueprint_payload(candidate)
    )
    assert blueprint["status"] == "accepted", blueprint
    candidate["mechanismBlueprintRef"] = blueprint["blueprintRef"]
    candidate["toolReferences"].append(
        {
            "toolName": "validate_generation_blueprint",
            "queryRef": blueprint["blueprintRef"],
            "summary": "后续机制已验证。",
        }
    )
    assert _draft(bound, token, changed)["status"] == "accepted"
    saved = _save_and_review(bound, token, payload, evaluated, restoring=True)
    assert (
        saved["selectedDesignEvidence"]["mechanismBlueprint"]
        == original_bundle["mechanismBlueprint"]
    )


def test_narrative_and_reference_order_changes_never_refresh_design(tmp_path, monkeypatch):
    bound, token, payload, _ = _setup(tmp_path, monkeypatch)
    changed = _resolved(payload)
    assert _draft(bound, token, changed)["status"] == "accepted"
    marker = bound.run_dir / "draft-validation.json"
    before = marker.read_bytes()
    key = mechanism_evidence._draft_key(bound)
    original = deepcopy(mechanism_evidence._DRAFTS[key])
    candidate = changed["prototypeBuildCandidate"]
    use = candidate["researchMemoryUse"]
    use["insightDecisions"][0]["summary"] += "补充叙述。"
    use["insightDecisions"][0]["application"] += "补充落实细节。"
    use["premiseDecisions"][0]["application"] += "补充验证说明。"
    use["dedupeQueryRefs"].reverse()
    use["deepRecordIds"].reverse()
    candidate["researchExecutionPlan"]["coherenceSummary"] += " Additional implementation detail."
    unchanged = _draft(bound, token, changed)
    assert unchanged["status"] == "already_validated", unchanged
    assert unchanged["changed"] is False
    assert unchanged["evidenceRebuilt"] is False
    assert unchanged["validatedAt"] == json.loads(before)["validatedAt"]
    assert marker.read_bytes() == before and mechanism_evidence._DRAFTS[key] == original


@pytest.mark.parametrize("defect", ["stale", "missing"])
def test_duplicate_draft_rechecks_receipts_even_when_validated_bundle_exists(
    tmp_path, monkeypatch, defect
):
    bound, token, payload, catalog = _setup(tmp_path, monkeypatch)
    marker = bound.run_dir / "draft-validation.json"
    before = marker.read_bytes()
    if defect == "stale":
        catalog[AUTH]["lastSeenAt"] = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
    else:
        catalog.pop(AUTH)
    result = _draft(bound, token, payload)
    assert result["status"] == "rejected"
    assert marker.read_bytes() == before
    assert not bound.trusted_evaluations_dir.exists()


@pytest.mark.parametrize(
    "defect", ["stale", "missing", "wrong_lane", "not_authorizing", "not_deep_read"]
)
def test_rebuild_and_revision_revalidate_receipt_authority(tmp_path, monkeypatch, defect):
    bound, token, payload, catalog = _setup(tmp_path, monkeypatch)
    changed = _resolved(payload)
    assert _draft(bound, token, changed)["status"] == "accepted"
    marker = bound.run_dir / "draft-validation.json"
    before = marker.read_bytes()
    key = mechanism_evidence._draft_key(bound)
    mechanism_evidence._DRAFTS.pop(key)
    if defect == "stale":
        catalog[DEEP]["lastSeenAt"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    elif defect == "missing":
        catalog.pop(DEEP)
    elif defect == "wrong_lane":
        catalog[DEEP]["result"]["selectedSourceCaseRef"] = "case:unrelated"
    elif defect == "not_authorizing":
        catalog[DEEP]["result"]["createAuthorizing"] = False
    else:
        catalog[DEEP]["request"]["detailLevel"] = "family"
        catalog[DEEP]["result"]["deepReadRecordIds"] = []
    rejected = _draft(bound, token, changed)
    assert rejected["status"] == "rejected", rejected
    assert marker.read_bytes() == before and key not in mechanism_evidence._DRAFTS
    assert not bound.trusted_evaluations_dir.exists()


def test_research_revision_after_judge_keeps_historical_decisions_immutable(tmp_path, monkeypatch):
    bound, token, payload, _ = _setup(tmp_path, monkeypatch)
    evaluated = _judge(bound, token, payload)
    assert evaluated["status"] == "evaluated", evaluated
    original = run_store.read_trusted_evaluations_strict(bound)[0]
    revised = _resolved(payload)
    assert _draft(bound, token, revised)["status"] == "accepted"
    saved = main.save_final_build_artifact(
        bound.run_id,
        token,
        payload["prototypeBuildCandidate"]["candidateId"],
        0,
        selection_reason="新增深读仅用于后续候选决定，原通过版本保留其原风险。",
        later_findings_scope="candidate_delta_only",
    )
    assert saved["status"] == "saved", saved
    assert (
        saved["selectedDesignEvidence"]["researchMemoryUse"]["premiseDecisions"][0]["decision"]
        == "caveated"
    )
    assert run_store.read_trusted_evaluations_strict(bound)[0] == original
    invalid = main.validate_generation_output(
        bound.run_id, token, _review_payload(revised, evaluated)
    )
    assert invalid["errorCode"] == "generation_baseline_candidate_mismatch", invalid
    valid = main.complete_generation_review(
        bound.run_id, token, _review_payload(payload, evaluated)
    )
    assert valid["status"] == "accepted", valid


def test_new_judge_bundle_cannot_be_stripped_and_rebuild_does_not_reset_budget(
    tmp_path, monkeypatch
):
    bound, token, payload, _ = _setup(tmp_path, monkeypatch, memory=False)
    for index in range(3):
        result = _judge(bound, token, payload)
        assert result["status"] == "evaluated" and result["attemptIndex"] == index, result
        if index == 0:
            mechanism_evidence._DRAFTS.pop(mechanism_evidence._draft_key(bound))
            rejected = _judge(bound, token, payload)
            assert rejected["attemptConsumed"] is False and rejected["attemptCount"] == 1
            assert _draft(bound, token, payload)["evidenceRebuilt"] is True
    receipt = run_store.read_trusted_evaluations_strict(bound)[0]
    receipt.pop("mechanismEvidence")
    assert not run_store._valid_trusted_evaluation_receipt(
        receipt, run_id=bound.run_id, attempt_index=0
    )
    assert _judge(bound, token, payload)["errorCode"] == "retry_limit_reached"
    assert len(run_store.read_trusted_evaluations_strict(bound)) == 3


def test_changed_research_after_cache_loss_is_a_revision_not_a_rebuild(tmp_path, monkeypatch):
    bound, token, payload, _ = _setup(tmp_path, monkeypatch)
    marker_path = bound.run_dir / "draft-validation.json"
    before = json.loads(marker_path.read_text(encoding="utf-8"))
    mechanism_evidence._DRAFTS.pop(mechanism_evidence._draft_key(bound))
    changed = _resolved(payload)
    result = _draft(bound, token, changed)
    assert result["status"] == "accepted" and result["evidenceRebuilt"] is False, result
    after = json.loads(marker_path.read_text(encoding="utf-8"))
    assert before["researchDecisionHash"] != after["researchDecisionHash"]
    assert before["buildStateHash"] == after["buildStateHash"]


def test_execution_structure_change_revises_same_pob_draft(tmp_path, monkeypatch):
    bound, token, payload, _ = _setup(tmp_path, monkeypatch)
    before = json.loads((bound.run_dir / "draft-validation.json").read_text(encoding="utf-8"))
    changed = deepcopy(payload)
    changed["prototypeBuildCandidate"]["researchExecutionPlan"]["packageDecisions"] = [
        {**_decision(AUTH_PACKAGE, adopted=True), "decision": "tested_and_rejected"}
    ]
    result = _draft(bound, token, changed)
    assert result["status"] == "accepted" and result["evidenceRebuilt"] is False, result
    assert result["researchExecutionStructureHash"] != before["researchExecutionStructureHash"]
    assert result["researchDecisionHash"] != before["researchDecisionHash"]
    assert result["buildStateHash"] == before["buildStateHash"]


@pytest.mark.parametrize("blocked_by", ["lock", "expired_run"])
def test_rebuild_never_bypasses_run_lock_or_extends_expired_run(tmp_path, monkeypatch, blocked_by):
    bound, token, payload, _ = _setup(tmp_path, monkeypatch, memory=False)
    key = mechanism_evidence._draft_key(bound)
    mechanism_evidence._DRAFTS.pop(key)
    marker_path = bound.run_dir / "draft-validation.json"
    before = marker_path.read_bytes()
    if blocked_by == "lock":
        lock_path = bound.run_dir / "evaluation-lock"
        lock_path.write_text("owned-by-another-action", encoding="utf-8")
    else:
        manifest = deepcopy(bound.manifest)
        manifest["startedAt"] = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        (bound.run_dir / "run-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    rejected = _draft(bound, token, payload)
    assert rejected["errorCode"] == (
        "generation_evaluation_in_progress" if blocked_by == "lock" else "run_expired"
    ), rejected
    assert marker_path.read_bytes() == before and key not in mechanism_evidence._DRAFTS
    if blocked_by == "lock":
        assert lock_path.read_text(encoding="utf-8") == "owned-by-another-action"


def test_rebuilding_design_evidence_does_not_recreate_lost_judge_xml(tmp_path, monkeypatch):
    bound, token, payload, _ = _setup(tmp_path, monkeypatch, memory=False)
    evaluated = _judge(bound, token, payload)
    assert evaluated["status"] == "evaluated", evaluated
    original = run_store.read_trusted_evaluations_strict(bound)[0]
    mechanism_evidence._DRAFTS.pop(mechanism_evidence._draft_key(bound))
    evaluation_snapshots.forget(run_id=bound.run_id)
    assert _draft(bound, token, payload)["evidenceRebuilt"] is True
    saved = main.save_final_build_artifact(
        bound.run_id, token, payload["prototypeBuildCandidate"]["candidateId"], 0
    )
    assert saved["errorCode"] == "trusted_evaluation_snapshot_unavailable", saved
    assert not bound.artifact_selection_path.exists()
    assert run_store.read_trusted_evaluations_strict(bound)[0] == original
