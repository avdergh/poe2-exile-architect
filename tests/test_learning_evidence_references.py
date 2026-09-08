"""独立 CR 反例及生产者/消费者共享的安全证据引用合同。"""

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest

from server.learning import comparison, models, service
from tests.test_phase7_comparative_learning import FAMILY_RECORDS, _evidence, _report, _version


def test_case_owned_canonical_unique_ref_remains_citable():
    reference = _evidence("reference", "case-review")
    generated = _evidence("generated", "case-review")
    key = "unique:pob:kalandra's_touch"
    generated["safeEvidenceRefs"].append(key)
    accepted_evidence = models.SafeBuildEvidence.model_validate(generated)
    assert key in accepted_evidence.safe_evidence_refs
    report = _report("case-review")
    report["dimensions"][0]["generatedEvidenceRefs"] = [key]
    result = comparison.validate_report(
        report,
        expected_case_id="case-review",
        reference_evidence=reference,
        generated_evidence=generated,
    )
    print(result)
    assert result["status"] == "accepted", result


def test_generated_submit_and_comparison_accept_same_canonical_reference(monkeypatch):
    # Pre-existing synthetic claims/receipts; no real campaign or database is started.
    key = "unique:pob:kalandra's_touch"
    family = service.research_identity.infer_build_family(FAMILY_RECORDS, allow_multi_primary=False)
    query_ref = "learning-query:" + "1" * 20
    case = {
        "caseId": "case-review",
        "phase": "create_running",
        "activeClaim": {
            "claimId": "claim:create",
            "threadId": "thread:create",
            "phase": "create",
            "claimedAt": models.utc_now(),
        },
        "familyTarget": {
            "buildFamilyKey": family.key,
            "ascendancyKey": family.ascendancy_key,
            "primarySkillKey": family.primary_skill_key,
            "secondarySkillKeys": list(family.secondary_skill_keys),
            "targetLevel": 80,
        },
        "memoryQueryReceipt": {"queryRef": query_ref, "recalledLessonIds": []},
        "referenceEvidence": _evidence("reference", "case-review"),
        "metrics": {},
        "phaseDurationsSeconds": {},
    }
    campaign = {"cases": [case], "revision": 1, "operations": []}
    saved = []
    monkeypatch.setattr(service, "_locked_campaign_state", nullcontext)
    monkeypatch.setattr(service, "_load_for_mutation", lambda *a: campaign)
    monkeypatch.setattr(
        service, "_write_campaign", lambda value: saved.append(deepcopy(value)) or True
    )
    monkeypatch.setattr(
        service, "_artifact_metadata", lambda ref: {"level": 80, "sourceHash": "fixture:source"}
    )
    monkeypatch.setattr(
        service.learning_memory, "validate_references", lambda **kw: {"status": "ok"}
    )
    monkeypatch.setattr(
        service.research_memory,
        "ResearchMemoryService",
        lambda: SimpleNamespace(read_query_receipt=lambda ref: None),
    )
    monkeypatch.setattr(
        service.progression_provenance,
        "validate_research_use_receipts",
        lambda **kw: (None, {"fixture": "accepted prior research"}, []),
    )
    evidence = _evidence("generated", "case-review")
    evidence["safeEvidenceRefs"].append(key)
    created = service.submit_create_result(
        campaign_id="campaign:fixture",
        case_id="case-review",
        claim_id="claim:create",
        thread_id="thread:create",
        expected_revision=1,
        operation_id="submit-fixture-create",
        identity_records=FAMILY_RECORDS,
        target_level=80,
        artifact_id="final-build:fixture",
        generated_evidence=evidence,
        learning_memory_use={"queryRef": query_ref, "recalledLessonIds": [], "decisions": []},
        research_memory_use={},
    )
    assert created["status"] == "create_accepted", created
    assert key in saved[-1]["cases"][0]["generatedEvidence"]["safeEvidenceRefs"]
    case["phase"] = "compare_running"
    case["activeClaim"] = {
        "claimId": "claim:compare",
        "threadId": "thread:reference",
        "phase": "compare",
        "claimedAt": models.utc_now(),
    }
    report = _report("case-review")
    report["dimensions"][0]["generatedEvidenceRefs"] = [key]
    result = service.submit_comparison(
        campaign_id="campaign:fixture",
        case_id="case-review",
        claim_id="claim:compare",
        thread_id="thread:reference",
        expected_revision=2,
        operation_id="submit-fixture-comparison",
        report=report,
    )
    print({"createStatus": created["status"], "storedGeneratedRef": key, "comparison": result})
    assert result["status"] == "comparison_accepted", result


def _reference_model(kind, ref):
    if kind in {"packet_id", "packet_sources"}:
        payload = _evidence("generated", "case-review")
        payload["evidenceRef" if kind == "packet_id" else "safeEvidenceRefs"] = (
            ref if kind == "packet_id" else [ref]
        )
        return models.SafeBuildEvidence.model_validate(payload)
    if kind == "dimension":
        return models.DimensionComparison(
            dimension=models.COMPARISON_DIMENSIONS[0],
            verdict="tie",
            rationale="Fixture source evidence",
            generated_evidence_refs=[ref],
            reference_evidence_refs=["safe:reference:test"],
        )
    if kind == "gap":
        return models.ComparisonGap(
            gap_id="gap:fixture",
            dimension=models.COMPARISON_DIMENSIONS[0],
            root_cause="insufficient_evidence",
            summary="Fixture gap",
            critical=True,
            safe_evidence_refs=[ref],
        )
    return models.FamilyTarget(
        build_family_key="bf-" + "a" * 20,
        ascendancy_key="ascendancy:invoker",
        primary_skill_key="skill:LightningArrowPlayer",
        target_level=80,
        version_context=models.LearningVersionContext.model_validate(_version()),
        safe_evidence_refs=[ref],
    )


@pytest.mark.parametrize("kind", ["packet_id", "packet_sources", "dimension", "gap", "family"])
def test_evidence_models_share_canonical_reference_grammar(kind):
    _reference_model(kind, "unique:pob:kalandra's_touch")
    _reference_model(kind, "ref:" + "a" * 236)
    for bad in ("bad key", "bad\nkey", 'bad"key', "bad;key", "x" * 241, "xy"):
        with pytest.raises(ValueError):
            _reference_model(kind, bad)


@pytest.mark.parametrize(
    "invalid_binding", ["missing", "wrong_side", "different_case", "duplicate"]
)
def test_apostrophe_does_not_relax_exact_membership(invalid_binding):
    key = "unique:pob:kalandra's_touch"
    reference = _evidence("reference", "case-review")
    generated = _evidence("generated", "case-review")
    generated["safeEvidenceRefs"].append(key)
    report = _report("case-review")
    report["dimensions"][0]["generatedEvidenceRefs"] = [key]
    if invalid_binding == "missing":
        generated["safeEvidenceRefs"].remove(key)
    elif invalid_binding == "wrong_side":
        generated["safeEvidenceRefs"].remove(key)
        reference["safeEvidenceRefs"].append(key)
    elif invalid_binding == "different_case":
        generated = _evidence("generated", "different-case")
    else:
        report["dimensions"][0]["generatedEvidenceRefs"].append(key)
    assert (
        comparison.validate_report(
            report,
            expected_case_id="case-review",
            reference_evidence=reference,
            generated_evidence=generated,
        )["status"]
        == "rejected"
    )
