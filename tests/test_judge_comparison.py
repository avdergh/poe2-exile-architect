from __future__ import annotations

from server.judge import comparison


def _evaluation(snapshot_id: str, **overrides):
    base = {
        "snapshotId": snapshot_id,
        "pass": True,
        "hardFailures": [],
        "modelability": {"status": "full", "coreBlocked": False},
        "aggregateScore": {"value": 0.5, "weightProfile": "judge_v2_reality_calibrated"},
        "scoreVector": {"offense": {"value": 0.5}, "defense": {"value": 0.5}},
        "rewardEligible": True,
    }
    base.update(overrides)
    return base


def test_legal_candidate_beats_invalid_reference_for_selection_only():
    candidate = _evaluation(
        "candidate", aggregateScore={"value": 0.2, "weightProfile": "judge_v2_reality_calibrated"}
    )
    reference = _evaluation(
        "reference",
        **{
            "pass": False,
            "hardFailures": ["invalid_socket_setup"],
            "aggregateScore": {"value": 0.9, "weightProfile": "judge_v2_reality_calibrated"},
            "rewardEligible": False,
        },
    )

    result = comparison.compare_evaluations(candidate, reference)

    assert result["selectionWinner"] == "candidate"
    assert result["rewardWinner"] == "unknown"
    assert result["comparisonStatus"] == "reference_invalid"
    assert result["rewardEligible"] is False
    assert result["rewardStrength"] == "none"


def test_both_legal_full_modelability_chooses_reward_winner():
    candidate = _evaluation(
        "candidate", aggregateScore={"value": 0.8, "weightProfile": "judge_v2_reality_calibrated"}
    )
    reference = _evaluation(
        "reference", aggregateScore={"value": 0.6, "weightProfile": "judge_v2_reality_calibrated"}
    )

    result = comparison.compare_evaluations(candidate, reference)

    assert result["selectionWinner"] == "candidate"
    assert result["rewardWinner"] == "candidate"
    assert result["comparisonStatus"] == "comparable"
    assert result["rewardEligible"] is True
    assert result["rewardStrength"] == "strong"


def test_partial_modelability_is_limited_reward():
    candidate = _evaluation(
        "candidate",
        modelability={"status": "partial", "coreBlocked": False},
        aggregateScore={"value": 0.8, "weightProfile": "judge_v2_reality_calibrated"},
    )
    reference = _evaluation(
        "reference", aggregateScore={"value": 0.6, "weightProfile": "judge_v2_reality_calibrated"}
    )

    result = comparison.compare_evaluations(candidate, reference)

    assert result["selectionWinner"] == "candidate"
    assert result["comparisonStatus"] == "partial_modelability"
    assert result["rewardEligible"] == "limited"
    assert result["rewardWinner"] == "unknown"
    assert result["rewardStrength"] == "limited"


def test_metric_unavailable_caveat_is_limited_reward():
    candidate = _evaluation(
        "candidate",
        caveats=["metric_unavailable_caveat"],
        rewardEligible="limited",
        aggregateScore={"value": 0.8, "weightProfile": "judge_v2_reality_calibrated"},
    )
    reference = _evaluation(
        "reference", aggregateScore={"value": 0.6, "weightProfile": "judge_v2_reality_calibrated"}
    )

    result = comparison.compare_evaluations(candidate, reference)

    assert result["selectionWinner"] == "candidate"
    assert result["comparisonStatus"] == "limited_evidence"
    assert result["rewardEligible"] == "limited"
    assert result["rewardWinner"] == "unknown"
    assert result["rewardStrength"] == "limited"


def test_full_dps_rollup_caveat_limits_reward_strength():
    candidate = _evaluation(
        "candidate",
        caveats=["full_dps_rollup_caveat"],
        rewardEligible="limited",
        aggregateScore={"value": 0.8, "weightProfile": "judge_v2_reality_calibrated"},
    )
    reference = _evaluation(
        "reference", aggregateScore={"value": 0.6, "weightProfile": "judge_v2_reality_calibrated"}
    )

    result = comparison.compare_evaluations(candidate, reference)

    assert result["selectionWinner"] == "candidate"
    assert result["rewardWinner"] == "unknown"
    assert result["rewardEligible"] == "limited"
    assert result["rewardStrength"] == "limited"


def test_core_unmodelled_blocks_reward_winner():
    candidate = _evaluation(
        "candidate",
        modelability={"status": "not_modelable", "coreBlocked": True},
        aggregateScore={"value": 0.8, "weightProfile": "judge_v2_reality_calibrated"},
    )
    reference = _evaluation(
        "reference", aggregateScore={"value": 0.6, "weightProfile": "judge_v2_reality_calibrated"}
    )

    result = comparison.compare_evaluations(candidate, reference)

    assert result["selectionWinner"] == "unknown"
    assert result["comparisonStatus"] == "incomparable"
    assert result["rewardWinner"] == "unknown"
    assert result["rewardEligible"] is False
    assert result["rewardStrength"] == "none"


def test_same_limited_evidence_score_is_not_biased_by_source_context():
    candidate = _evaluation(
        "candidate",
        caveats=["full_dps_rollup_caveat"],
        rewardEligible="limited",
        aggregateScore={"value": 0.415383, "weightProfile": "judge_v3_evidence_aware"},
    )
    reference = _evaluation(
        "reference",
        caveats=["full_dps_rollup_caveat"],
        rewardEligible="limited",
        aggregateScore={"value": 0.415383, "weightProfile": "judge_v3_evidence_aware"},
    )

    result = comparison.compare_evaluations(candidate, reference)

    assert result["selectionWinner"] == "tie"
    assert result["rewardWinner"] == "unknown"
    assert result["comparisonStatus"] == "limited_evidence"
    assert result["rewardStrength"] == "limited"


def test_external_budget_anomaly_caveat_forces_limited_reward():
    candidate = _evaluation(
        "candidate",
        caveats=["external_passive_budget_anomaly_caveat"],
        rewardEligible="limited",
        aggregateScore={"value": 0.7, "weightProfile": "judge_v3_evidence_aware"},
    )
    reference = _evaluation(
        "reference",
        aggregateScore={"value": 0.6, "weightProfile": "judge_v3_evidence_aware"},
    )

    result = comparison.compare_evaluations(candidate, reference)

    assert result["selectionWinner"] == "candidate"
    assert result["rewardWinner"] == "unknown"
    assert result["comparisonStatus"] == "limited_evidence"
    assert result["rewardStrength"] == "limited"


def test_explicit_reward_limit_reason_prevents_reward_winner_without_caveat():
    candidate = _evaluation(
        "candidate",
        rewardLimitReasons=["non_endgame_scope"],
        aggregateScore={"value": 0.8, "weightProfile": "judge_v5_evidence_separated"},
    )
    reference = _evaluation(
        "reference",
        aggregateScore={"value": 0.6, "weightProfile": "judge_v5_evidence_separated"},
    )

    result = comparison.compare_evaluations(candidate, reference)

    assert result["selectionWinner"] == "candidate"
    assert result["rewardWinner"] == "unknown"
    assert result["comparisonStatus"] == "limited_evidence"
    assert result["rewardStrength"] == "limited"
