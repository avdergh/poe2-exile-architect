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


def _engine_verification(
    *,
    total_dps: float = 250_000,
    full_dps: float | None = 500_000,
    total_ehp: float = 20_000,
) -> dict:
    offense = {"TotalDPS": total_dps}
    if full_dps is not None:
        offense["FullDPS"] = full_dps
    return {
        "ok": True,
        "status": "passed",
        "pass": True,
        "observations": {
            "totalEHP": total_ehp,
            "offense": offense,
        },
        "evidenceTags": ["engine-computed", "stage-verification"],
    }


def _numeric_ranges() -> dict:
    return {
        "numericRanges": {
            "TotalDPS": {"min": 100_000, "median": 500_000, "max": 1_000_000, "n": 8},
            "TotalEHP": {"min": 12_000, "median": 22_000, "max": 40_000, "n": 8},
        }
    }


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


def test_evaluate_lifecycle_route_compares_engine_computed_endgame_numeric_ranges():
    route = _route()
    route["stages"][-1]["verification"] = _engine_verification(
        total_dps=80_000,
        full_dps=900_000,
        total_ehp=15_000,
    )

    result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=_numeric_ranges())
    review = result["evidenceReview"]["numericRangeReview"]
    by_metric = {row["metric"]: row for row in review["stageComparisons"]}

    assert result["pass"] is True
    assert result["grade"] == "needs_review"
    assert "numeric_range_below_reference" in result["warnings"]
    assert "numeric_range_below_reference" not in result["issues"]
    assert result["referenceComparison"]["alignmentStatus"] == "aligned"
    assert review["status"] == "compared"
    assert by_metric["TotalDPS"]["placement"] == "below_range"
    assert by_metric["TotalDPS"]["observedMetric"] == "TotalDPS"
    assert by_metric["TotalDPS"]["referenceMetric"] == "TotalDPS"
    assert by_metric["TotalDPS"]["referenceMin"] == 100_000
    assert by_metric["TotalDPS"]["referenceMax"] == 1_000_000
    assert by_metric["TotalDPS"]["referenceN"] == 8
    assert by_metric["TotalEHP"]["placement"] == "within_range"
    assert "FullDPS" not in by_metric


def test_evaluate_lifecycle_route_compares_explicit_fulldps_range_only():
    route = _route()
    route["stages"][-1]["verification"] = _engine_verification(full_dps=900_000)
    profile = _numeric_ranges()
    profile["numericRanges"]["FullDPS"] = {
        "min": 200_000,
        "median": 800_000,
        "max": 1_500_000,
        "n": 4,
    }

    result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=profile)
    metrics = {
        row["metric"] for row in result["evidenceReview"]["numericRangeReview"]["stageComparisons"]
    }

    assert "FullDPS" in metrics


def test_evaluate_lifecycle_route_accepts_benchmark_shape_without_breaking_alignment():
    route = _route()
    route["stages"][-1]["verification"] = _engine_verification(
        total_dps=250_000,
        full_dps=9_000_000,
        total_ehp=20_000,
    )
    profile = {
        "dps": {"reference": {"min": 100_000, "median": 500_000, "max": 1_000_000, "n": 8}},
        "ehp": {"reference": {"min": 12_000, "median": 22_000, "max": 40_000, "n": 8}},
    }

    result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=profile)
    review = result["evidenceReview"]["numericRangeReview"]
    metrics = {row["metric"] for row in review["stageComparisons"]}

    assert result["referenceComparison"]["alignmentStatus"] == "aligned"
    assert review["status"] == "compared"
    assert metrics == {"TotalDPS", "TotalEHP"}


def test_evaluate_lifecycle_route_skips_numeric_ranges_without_engine_verification():
    route = _route()

    result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=_numeric_ranges())

    assert result["evidenceReview"]["numericRangeReview"]["status"] == "not_evaluated"
    assert result["evidenceReview"]["numericRangeReview"]["stageComparisons"] == []


def test_evaluate_lifecycle_route_compares_only_verified_endgame_stage_ranges():
    route = _route()
    route["stages"][0]["verification"] = _engine_verification(total_dps=1, total_ehp=1)
    route["stages"][4]["verification"] = _engine_verification(
        total_dps=150_000,
        total_ehp=18_000,
    )

    result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=_numeric_ranges())
    compared_stages = {
        row["stage"] for row in result["evidenceReview"]["numericRangeReview"]["stageComparisons"]
    }

    assert compared_stages == {"endgame_budget"}


def test_evaluate_lifecycle_route_requires_verification_local_engine_evidence_for_ranges():
    route = _route()
    route["evidenceTags"] = ["engine-computed"]
    route["stages"][-1]["evidenceTags"].append("engine-computed")
    route["stages"][-1]["verification"] = {
        "ok": True,
        "status": "planned",
        "observations": {"totalEHP": 20_000, "offense": {"TotalDPS": 250_000}},
    }

    result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=_numeric_ranges())

    assert result["evidenceReview"]["numericRangeReview"]["status"] == "not_evaluated"
    assert result["evidenceReview"]["numericRangeReview"]["stageComparisons"] == []


def test_evaluate_lifecycle_route_reports_invalid_numeric_reference_ranges():
    route = _route()
    route["stages"][-1]["verification"] = _engine_verification()
    profile = {
        "numericRanges": {
            "TotalDPS": {"min": True, "max": 1_000_000},
            "TotalEHP": {"min": 40_000, "max": 12_000},
        }
    }

    result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=profile)
    review = result["evidenceReview"]["numericRangeReview"]

    assert review["status"] == "invalid_reference"
    assert review["stageComparisons"] == []
    assert "numeric_range_reference_invalid" in result["warnings"]


def test_evaluate_lifecycle_route_rejects_mixed_invalid_numeric_ranges():
    route = _route()
    route["stages"][-1]["verification"] = _engine_verification()
    profile = {
        "numericRanges": {
            "TotalDPS": {"min": 100_000, "max": 1_000_000},
            "TotalEHP": {"min": 40_000, "max": 12_000},
        }
    }

    result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=profile)
    review = result["evidenceReview"]["numericRangeReview"]

    assert review["status"] == "invalid_reference"
    assert review["stageComparisons"] == []
    assert "numeric_range_reference_invalid" in result["warnings"]


def test_evaluate_lifecycle_route_rejects_malformed_numeric_ranges_container():
    route = _route()
    route["stages"][-1]["verification"] = _engine_verification()

    result = lifecycle_eval.evaluate_lifecycle_route(
        route,
        reference_profile={"numericRanges": ["not", "a", "distribution"]},
    )
    review = result["evidenceReview"]["numericRangeReview"]

    assert review["status"] == "invalid_reference"
    assert review["stageComparisons"] == []
    assert "numeric_range_reference_invalid" in result["warnings"]


def test_evaluate_lifecycle_route_empty_alignment_fields_do_not_override_route_cohort():
    route = _route()
    route["stages"][-1]["verification"] = _engine_verification()
    profile = {
        **_numeric_ranges(),
        "commonLevers": [],
        "commonDamageTypes": [],
        "commonDelivery": [],
        "commonDefenses": [],
        "ascendancyContext": [],
    }

    result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=profile)

    assert result["referenceComparison"]["source"] == "route.cohortAnalysis"
    assert result["referenceComparison"]["alignmentStatus"] == "aligned"


def test_evaluate_lifecycle_route_sanitizes_additional_raw_reference_field_names():
    route = _route()
    route["stages"][-1]["verification"] = _engine_verification()
    profile = {
        **_numeric_ranges(),
        "itemSets": [{"name": "secret item set"}],
        "skillGroups": [{"name": "secret skill group"}],
        "configs": {"secret": "config"},
        "configTab": {"secret": "config tab"},
    }

    result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=profile)

    serialized = json.dumps(result)
    assert "reference_raw_fields_sanitized" in result["warnings"]
    assert "secret item set" not in serialized
    assert "secret skill group" not in serialized
    assert "config tab" not in serialized


def test_evaluate_lifecycle_route_invalid_input_includes_numeric_range_review():
    result = lifecycle_eval.evaluate_lifecycle_route("not a route")  # type: ignore[arg-type]

    assert result["evidenceReview"]["numericRangeReview"]["status"] == "not_evaluated"
    assert result["evidenceReview"]["numericRangeReview"]["stageComparisons"] == []


def test_evaluate_lifecycle_route_does_not_leak_raw_reference_fields_with_numeric_ranges():
    route = _route()
    route["stages"][-1]["verification"] = _engine_verification()
    profile = {
        **_numeric_ranges(),
        "gear": ["secret item"],
        "pobCode": "secret pob",
        "passiveTree": {"secret": True},
    }

    result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=profile)

    serialized = json.dumps(result)
    assert "reference_raw_fields_sanitized" in result["warnings"]
    assert "secret item" not in serialized
    assert "secret pob" not in serialized
    assert "passiveTree" not in serialized


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
