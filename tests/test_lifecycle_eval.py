"""Lifecycle route evaluation harness tests.

Phase 3L evaluates route outputs for regression/development use. It must stay a verifier of
contracts and evidence boundaries, not a generator or a way to copy reference builds.
"""

from __future__ import annotations

import json

from server.knowledge import lifecycle_eval


def _stage(stage_id: str, *, endgame: bool = False) -> dict:
    stage = {
        "id": stage_id,
        "evidenceTags": ["lifecycle-research", "corpus"],
        "verification": {"ok": True, "status": "planned"},
        "memoryWarnings": [],
        "memoryRecommendedActions": [],
    }
    if endgame:
        stage["evidenceTags"].append("reference-calibration")
        stage["cohortHints"] = [
            "Common mature-build levers: +levels to skills, cast speed",
            "Common damage types: lightning",
            "Common delivery traits: spell, projectile",
            "Common defense identities: ES recharge",
        ]
    else:
        stage["cohortHints"] = []
    return stage


def _route() -> dict:
    return {
        "ok": True,
        "buildId": "life-eval",
        "goal": "给我一个新手能玩的闪电终局BD",
        "classification": "starter_then_transition",
        "stages": [
            _stage("campaign_early"),
            _stage("campaign_mid"),
            _stage("campaign_late"),
            _stage("maps_entry"),
            _stage("endgame_budget", endgame=True),
            _stage("endgame_final", endgame=True),
        ],
        "transitionGates": [
            {
                "fromStage": "maps_entry",
                "toStage": "endgame_budget",
                "requirements": {"level": 75, "items": ["build-defining unique"]},
                "evidenceTags": ["lifecycle-transition-gate"],
                "caveats": ["Verify with active PoB state before switching."],
            }
        ],
        "cohortAnalysis": {
            "ok": True,
            "sampleSize": 2,
            "commonLevers": [{"name": "+levels to skills", "count": 2}],
            "commonDamageTypes": [{"name": "lightning", "count": 2}],
            "commonDelivery": [{"name": "spell", "count": 2}],
            "commonDefenses": [{"name": "ES recharge", "count": 2}],
            "ascendancyContext": [{"ascendancy": "Stormweaver", "referenceCount": 2}],
            "evidenceTags": ["reference-cohort"],
        },
        "memoryContext": {
            "policy": {
                "advisoryOnly": True,
                "doesNotReplacePobVerification": True,
                "singleFeedbackIsEpisodicOnly": True,
                "noComputedNumbers": True,
            }
        },
        "memoryPolicy": "Feedback is advisory until promoted with patch-scoped evidence.",
        "freshness": {"decision": "verified_current", "blockers": [], "warnings": []},
    }


def test_evaluate_lifecycle_route_passes_structured_route_with_cohort_alignment():
    result = lifecycle_eval.evaluate_lifecycle_route(_route())

    assert result["ok"] is True
    assert result["pass"] is True
    assert result["grade"] == "pass"
    assert result["qualityGate"]["pass"] is True
    assert result["referenceComparison"]["alignmentStatus"] == "aligned"
    assert result["boundaries"] == {
        "ranPobCompute": False,
        "copiedReference": False,
        "runtimeNetwork": False,
        "writesMemory": False,
    }


def test_evaluate_lifecycle_route_marks_missing_reference_alignment_unknown():
    route = _route()
    route.pop("cohortAnalysis")

    result = lifecycle_eval.evaluate_lifecycle_route(route)

    assert result["pass"] is False
    assert "reference_alignment_unknown" in result["unknowns"]
    assert result["referenceComparison"]["alignmentStatus"] == "unknown"


def test_evaluate_lifecycle_route_rejects_cohort_present_but_not_used_by_route():
    route = _route()
    for stage in route["stages"]:
        stage["cohortHints"] = []

    result = lifecycle_eval.evaluate_lifecycle_route(route)

    assert result["pass"] is False
    assert "reference_alignment_mismatch" in result["issues"]
    assert result["referenceComparison"]["alignmentStatus"] == "mismatch"


def test_evaluate_lifecycle_route_fails_when_reference_profile_has_no_overlap():
    profile = {
        "sampleSize": 1,
        "commonLevers": [{"name": "poison magnitude"}],
        "commonDamageTypes": [{"name": "chaos"}],
        "commonDelivery": [{"name": "minion"}],
        "commonDefenses": [{"name": "armour"}],
    }

    result = lifecycle_eval.evaluate_lifecycle_route(_route(), reference_profile=profile)

    assert result["pass"] is False
    assert "reference_alignment_mismatch" in result["issues"]
    assert result["referenceComparison"]["alignmentStatus"] == "mismatch"


def test_evaluate_lifecycle_route_sanitizes_copyable_reference_fields():
    profile = {
        "sampleSize": 1,
        "commonLevers": [{"name": "+levels to skills"}],
        "commonDamageTypes": [{"name": "lightning"}],
        "commonDelivery": [{"name": "spell"}],
        "commonDefenses": [{"name": "ES recharge"}],
        "gear": ["secret item"],
        "items": ["secret unique"],
        "pobCode": "secret pob",
        "passiveTree": {"secret": True},
    }

    result = lifecycle_eval.evaluate_lifecycle_route(_route(), reference_profile=profile)

    serialized = json.dumps(result)
    assert "reference_raw_fields_sanitized" in result["warnings"]
    assert "gear" not in serialized
    assert "items" not in serialized
    assert "pobCode" not in serialized
    assert "passiveTree" not in serialized
    assert result["boundaries"]["copiedReference"] is False


def test_evaluate_lifecycle_route_rejects_unverified_numeric_claims():
    route = _route()
    route["stages"][0]["dpsEstimate"] = 123456
    route["stages"][1]["dps"] = {"value": 500000}
    route["stages"][2]["stats"] = {"TotalEHP": {"min": 20000}}
    route["stages"][3]["ehpEstimate"] = "22.5k"
    route["stages"][4]["risks"] = ["claims about 500k DPS before verification"]

    result = lifecycle_eval.evaluate_lifecycle_route(route)

    assert "unsupported_computed_claim" in result["issues"]
    assert result["pass"] is False
    assert result["evidenceReview"]["numericReview"]["status"] == "unsupported_claim"
    assert result["evidenceReview"]["numericReview"]["unsupportedClaimCount"] >= 5


def test_evaluate_lifecycle_route_uses_stage_local_engine_evidence_for_numeric_claims():
    route = _route()
    route["stages"][0]["evidenceTags"].append("engine-computed")
    route["stages"][0]["dpsEstimate"] = 123456
    route["stages"][1]["dpsEstimate"] = 654321

    result = lifecycle_eval.evaluate_lifecycle_route(route)

    assert "unsupported_computed_claim" in result["issues"]
    assert result["evidenceReview"]["numericReview"]["unsupportedClaimCount"] == 1


def test_evaluate_lifecycle_route_uses_subtree_engine_evidence_for_route_numeric_claims():
    route = _route()
    route["computedSummary"] = {
        "evidenceTags": ["engine-computed"],
        "dpsEstimate": 123456,
    }
    route["unverifiedNotes"] = {"dpsEstimate": 654321}

    result = lifecycle_eval.evaluate_lifecycle_route(route)

    assert "unsupported_computed_claim" in result["issues"]
    assert result["evidenceReview"]["numericReview"]["unsupportedClaimCount"] == 1


def test_evaluate_lifecycle_route_does_not_treat_dps_computable_bool_as_claim():
    route = _route()
    route["cohortAnalysis"]["referenceMatches"] = [{"mainSkill": "Spark", "dpsComputable": True}]

    result = lifecycle_eval.evaluate_lifecycle_route(route)

    assert "unsupported_computed_claim" not in result["issues"]
    assert result["evidenceReview"]["numericReview"]["status"] == "not_evaluated"


def test_evaluate_lifecycle_route_handles_invalid_reference_sample_size():
    profile = {
        "sampleSize": "unknown",
        "commonLevers": [{"name": "+levels to skills"}],
    }

    result = lifecycle_eval.evaluate_lifecycle_route(_route(), reference_profile=profile)

    assert result["pass"] is False
    assert "reference_sample_size_invalid" in result["warnings"]
    assert "reference_alignment_unknown" in result["unknowns"]
    assert result["referenceComparison"]["sampleSize"] == 0


def test_evaluate_lifecycle_route_rejects_non_advisory_memory_policy():
    route = _route()
    route["memoryContext"]["policy"]["advisoryOnly"] = False

    result = lifecycle_eval.evaluate_lifecycle_route(route)

    assert "memory_policy_not_advisory" in result["issues"]
    assert result["memoryReview"]["advisoryOnly"] is False


def test_evaluate_lifecycle_route_marks_missing_memory_policy_unknown():
    route = _route()
    route.pop("memoryContext")

    result = lifecycle_eval.evaluate_lifecycle_route(route)

    assert result["pass"] is False
    assert "memory_policy_unknown" in result["unknowns"]
    assert result["memoryReview"]["present"] is False


def test_evaluate_lifecycle_route_rejects_route_marked_not_ok():
    route = _route()
    route["ok"] = False

    result = lifecycle_eval.evaluate_lifecycle_route(route)

    assert result["pass"] is False
    assert "route_not_ok" in result["issues"]


def test_evaluate_lifecycle_route_reaudits_instead_of_trusting_embedded_quality_gate():
    route = _route()
    route["qualityGate"] = {"pass": True, "missing": []}
    route["transitionGates"] = []

    result = lifecycle_eval.evaluate_lifecycle_route(route)

    assert result["pass"] is False
    assert result["qualityGate"]["pass"] is False
    assert "quality_gate_failed" in result["issues"]


def test_evaluate_lifecycle_route_invalid_input_keeps_stable_shape():
    result = lifecycle_eval.evaluate_lifecycle_route("not a route")  # type: ignore[arg-type]

    assert result["ok"] is False
    assert result["pass"] is False
    assert result["grade"] == "fail"
    assert result["score"] == 0
    assert "invalid_route" in result["issues"]
    assert result["boundaries"]["ranPobCompute"] is False
