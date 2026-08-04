from __future__ import annotations

import pytest

from server.judge import scoring


def test_level_band_uses_non_endgame_floor_for_lower_level_build():
    band = scoring.level_band(75)

    assert band == "maps_entry"
    assert scoring.floor_caveats(75) == []


def test_level_69_to_70_offense_floor_boundary_remains_explicit_for_future_calibration():
    metrics = {
        "TotalDPS": 10_000,
        "PhysicalMaximumHitTaken": 10_000,
        "FireMaximumHitTaken": 20_000,
        "ColdMaximumHitTaken": 20_000,
        "LightningMaximumHitTaken": 20_000,
        "ChaosMaximumHitTaken": 12_000,
        "LifeUnreserved": 4_000,
    }
    resistances = {"fire": 75, "cold": 75, "lightning": 75, "chaos": 75}

    level_69 = scoring.score_metrics(metrics, level=69, resistances=resistances)
    level_70 = scoring.score_metrics(metrics, level=70, resistances=resistances)

    assert level_69["scoreBreakdown"]["offense"]["hardFloor"] == 5_000
    assert level_70["scoreBreakdown"]["offense"]["hardFloor"] == 50_000
    assert level_69["levelBand"] == "campaign"
    assert level_70["levelBand"] == "maps_entry"


def test_log_score_has_diminishing_returns():
    low = scoring.target_log_score(600_000, quality_floor=300_000, target=2_500_000)
    mid = scoring.target_log_score(1_200_000, quality_floor=300_000, target=2_500_000)
    high = scoring.target_log_score(10_000_000, quality_floor=300_000, target=2_500_000)

    assert 0 < low < mid < high <= 1
    assert high == 1.0


def test_below_floor_triggers_critical_failure():
    result = scoring.score_metrics(
        {
            "TotalDPS": 10_000,
            "PhysicalMaximumHitTaken": 10_000,
            "FireMaximumHitTaken": 20_000,
            "ColdMaximumHitTaken": 20_000,
            "LightningMaximumHitTaken": 20_000,
            "ChaosMaximumHitTaken": 12_000,
            "LifeUnreserved": 4_000,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    assert "below_playability_floor" in result["failures"]
    assert result["scoreVector"]["offense"]["blocked"] is True
    offense = result["scoreBreakdown"]["offense"]
    assert offense["metricStatus"] == "available"
    assert offense["floorStatus"] == "missed"
    assert offense["deliveryEvidenceStatus"] == "established"
    assert offense["floorProgress"] == pytest.approx(0.2)
    assert offense["scorePolicy"] == "stage_curve"
    assert "offense_delivery_not_established" not in result["qualityWarnings"]


def test_zero_full_dps_falls_back_to_total_dps():
    result = scoring.score_metrics(
        {
            "FullDPS": 0,
            "TotalDPS": 205_000,
            "PhysicalMaximumHitTaken": 10_000,
            "FireMaximumHitTaken": 20_000,
            "ColdMaximumHitTaken": 20_000,
            "LightningMaximumHitTaken": 20_000,
            "ChaosMaximumHitTaken": 12_000,
            "LifeUnreserved": 4_000,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    assert "below_playability_floor" not in result["failures"]
    assert result["scoreVector"]["offense"]["value"] > 0
    assert "offense_quality_target_missed" in result["qualityWarnings"]
    assert result["scoreBreakdown"]["offense"]["scoreFloor"] == 50_000
    assert result["scoreBreakdown"]["offense"]["qualityFloor"] == 300_000


def test_quality_floor_is_diagnostic_not_zero_score_cutoff():
    result = scoring.score_metrics(
        {
            "TotalDPS": 180_000,
            "PhysicalMaximumHitTaken": 5_500,
            "FireMaximumHitTaken": 8_000,
            "ColdMaximumHitTaken": 8_000,
            "LightningMaximumHitTaken": 8_000,
            "ChaosMaximumHitTaken": 4_000,
            "LifeUnreserved": 4_000,
            "TotalEHP": 42_000,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 30},
    )

    assert result["scoreVector"]["offense"]["value"] > 0
    assert result["scoreVector"]["defense"]["value"] > 0
    assert "below_playability_floor" not in result["failures"]
    assert "catastrophic_defense_shortboard" not in result["failures"]
    assert "offense_quality_target_missed" in result["qualityWarnings"]


def test_single_chaos_shortboard_lowers_defense_without_forcing_catastrophic_failure():
    result = scoring.score_metrics(
        {
            "TotalDPS": 500_000,
            "PhysicalMaximumHitTaken": 20_000,
            "FireMaximumHitTaken": 20_000,
            "ColdMaximumHitTaken": 20_000,
            "LightningMaximumHitTaken": 20_000,
            "ChaosMaximumHitTaken": 500,
            "LifeUnreserved": 4_000,
            "TotalEHP": 50_000,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 0},
    )

    assert "catastrophic_defense_shortboard" not in result["failures"]
    assert result["scoreVector"]["defense"]["value"] < 0.5


def test_campaign_nonnegative_chaos_does_not_dominate_defense_score():
    metrics = {
        "TotalDPS": 50_000,
        "PhysicalMaximumHitTaken": 3_000,
        "FireMaximumHitTaken": 5_000,
        "ColdMaximumHitTaken": 5_000,
        "LightningMaximumHitTaken": 5_000,
        "ChaosMaximumHitTaken": 600,
        "LifeUnreserved": 3_000,
        "TotalEHP": 10_000,
    }

    result = scoring.score_metrics(
        metrics,
        level=58,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 0},
    )

    assert "severe_elemental_resistance_shortfall" not in result["playabilityFailures"]
    assert result["scoreVector"]["defense"]["value"] == 1.0
    assert result["scoreBreakdown"]["chaos"]["excludedFromDefenseShortboard"] is True
    assert result["scoreBreakdown"]["defense"]["scoreComponents"] == [
        "physical",
        "fire",
        "cold",
        "lightning",
    ]
    assert "campaign_chaos_resistance_opportunity_cost_caveat" in result["caveats"]


def test_campaign_negative_chaos_is_quality_warning_not_playability_failure():
    result = scoring.score_metrics(
        {
            "TotalDPS": 50_000,
            "PhysicalMaximumHitTaken": 3_000,
            "FireMaximumHitTaken": 5_000,
            "ColdMaximumHitTaken": 5_000,
            "LightningMaximumHitTaken": 5_000,
            "ChaosMaximumHitTaken": 400,
            "LifeUnreserved": 3_000,
            "TotalEHP": 10_000,
        },
        level=58,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": -1},
    )

    assert "severe_elemental_resistance_shortfall" not in result["playabilityFailures"]
    assert "negative_chaos_resistance" in result["qualityWarnings"]
    assert "campaign_chaos_resistance_opportunity_cost_caveat" not in result["caveats"]


def test_ci_keystone_scores_chaos_as_immune_without_chaos_max_hit():
    result = scoring.score_metrics(
        {
            "TotalDPS": 500_000,
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 0,
            "LifeUnreserved": 1,
            "EnergyShield": 9_000,
            "TotalEHP": 30_000,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": -60},
        keystones=["Chaos Inoculation"],
    )

    assert "catastrophic_defense_shortboard" not in result["failures"]
    assert "severe_elemental_resistance_shortfall" not in result["playabilityFailures"]
    assert result["scoreBreakdown"]["chaos"]["value"] == 1.0
    assert result["scoreBreakdown"]["chaos"]["sourceMetric"] == "ChaosInoculation"


def test_recovery_uses_life_unreserved_for_life_reservation_builds():
    result = scoring.score_metrics(
        {
            "TotalDPS": 500_000,
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "Life": 5_000,
            "LifeUnreserved": 1_000,
            "EnergyShield": 500,
            "LifeRegenRecovery": 150,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    recovery = result["scoreBreakdown"]["recovery"]
    assert recovery["primaryPool"] == 1_000
    assert recovery["qualityFloor"] == 15
    assert recovery["target"] == 80
    assert result["scoreVector"]["recovery"]["value"] == 1.0


def test_recovery_falls_back_to_life_when_life_unreserved_missing():
    result = scoring.score_metrics(
        {
            "TotalDPS": 500_000,
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "Life": 5_000,
            "LifeRegenRecovery": 150,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    assert result["scoreBreakdown"]["recovery"]["primaryPool"] == 5_000
    assert "life_unreserved_missing_caveat" in result["caveats"]


def test_judge_reports_measured_mana_flask_dependency():
    result = scoring.score_metrics(
        {
            "TotalDPS": 500_000,
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "Life": 5_000,
            "LifeUnreserved": 5_000,
            "LifeRegenRecovery": 150,
            "Mana": 533,
            "ManaUnreserved": 533,
            "ManaCost": 45.384615,
            "Speed": 2.1375,
            "ManaRegenRecovery": 58.4,
            "ManaLeechGainRate": 0,
            "ManaOnHitRate": 0,
            "ManaFlaskEquipped": True,
        },
        level=75,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 30},
    )

    mana = result["scoreBreakdown"]["recovery"]["manaSustain"]
    assert mana["classification"] == "flask_assisted_required"
    assert mana["secondsFromFull"] == pytest.approx(13.8049, rel=1e-4)
    assert "mana_flask_dependency" in result["qualityWarnings"]
    assert "long_boss_mana_sustain_risk_caveat" in result["caveats"]


def test_ehp_compensates_low_physical_shortboard_only_upward():
    result = scoring.score_metrics(
        {
            "TotalDPS": 500_000,
            "PhysicalMaximumHitTaken": 7_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
            "TotalEHP": 60_000,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    physical = result["scoreBreakdown"]["physical"]
    assert physical["ehpMultiplier"] == 1.5
    assert physical["value"] > physical["baseValue"]


def test_high_ehp_allows_slightly_low_physical_max_hit_with_caveat():
    result = scoring.score_metrics(
        {
            "TotalDPS": 500_000,
            "PhysicalMaximumHitTaken": 4_557,
            "FireMaximumHitTaken": 18_000,
            "ColdMaximumHitTaken": 18_000,
            "LightningMaximumHitTaken": 18_000,
            "ChaosMaximumHitTaken": 12_000,
            "LifeUnreserved": 1_500,
            "EnergyShield": 2_600,
            "TotalEHP": 45_000,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    assert "catastrophic_defense_shortboard" not in result["failures"]
    assert "physical_shortboard_ehp_compensated_caveat" in result["caveats"]
    assert result["scoreBreakdown"]["physical"]["value"] == 0.0
    assert result["scoreVector"]["defense"]["value"] > 0


def test_avoidance_can_lift_defense_for_high_evasion_mature_builds():
    result = scoring.score_metrics(
        {
            "TotalDPS": 430_000,
            "PhysicalMaximumHitTaken": 4_557,
            "FireMaximumHitTaken": 18_000,
            "ColdMaximumHitTaken": 18_000,
            "LightningMaximumHitTaken": 18_000,
            "ChaosMaximumHitTaken": 12_000,
            "LifeUnreserved": 1_500,
            "EnergyShield": 2_600,
            "TotalEHP": 45_000,
            "EvadeChance": 64,
            "EffectiveMovementSpeedMod": 1.4,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    assert "catastrophic_defense_shortboard" not in result["failures"]
    assert result["scoreBreakdown"]["defense"]["scorePolicy"] == "avoidance_evasion_hybrid"
    assert result["scoreVector"]["defense"]["value"] >= 0.5


def test_trusted_reference_suspect_ci_defense_state_does_not_hard_fail_catastrophic():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 2_122_246.1256786,
            "JudgeDPSMetric": "FullDPS",
            "JudgeSkillName": "Lightning Warp",
            "JudgeSkillCaveats": [],
            "PhysicalMaximumHitTaken": 756,
            "FireMaximumHitTaken": 2_017,
            "ColdMaximumHitTaken": 2_017,
            "LightningMaximumHitTaken": 2_017,
            "ChaosMaximumHitTaken": 0,
            "Life": 1,
            "LifeUnreserved": 1,
            "EnergyShield": 16,
            "Mana": 1_021,
            "ManaUnreserved": 1_021,
            "TotalEHP": 1_663.6074558569,
            "EnergyShieldRecharge": 2.0,
            "EffectiveMovementSpeedMod": 1.283,
        },
        level=97,
        resistances={"fire": 48, "cold": 42, "lightning": 75, "chaos": 5},
        keystones=["Chaos Inoculation"],
        source_context="trusted_reference",
    )

    assert "catastrophic_defense_shortboard" not in result["failures"]
    assert "defense_state_unverified_caveat" in result["caveats"]
    assert "state_or_import_suspect_caveat" in result["caveats"]


def test_missing_max_hit_uses_ehp_fallback_with_caveat():
    result = scoring.score_metrics(
        {"TotalDPS": 500_000, "TotalEHP": 25_000, "LifeUnreserved": 4_000},
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    assert "metric_unavailable_caveat" in result["caveats"]
    assert result["metricProvenance"]["TotalEHP"] == "pob_computed"
    assert result["scoreVector"]["defense"]["value"] > 0


@pytest.mark.parametrize("level", [18, 38, 58, 75, 90])
def test_elemental_resistance_percentages_are_diagnostic_only_for_every_stage(level):
    metrics = {
        "TotalDPS": 20_000_000,
        "PhysicalMaximumHitTaken": 50_000,
        "FireMaximumHitTaken": 50_000,
        "ColdMaximumHitTaken": 50_000,
        "LightningMaximumHitTaken": 50_000,
        "ChaosMaximumHitTaken": 50_000,
        "LifeUnreserved": 4_000,
    }
    result = scoring.score_metrics(
        metrics,
        level=level,
        resistances={"fire": -60, "cold": -60, "lightning": -60, "chaos": -60},
    )
    capped = scoring.score_metrics(
        metrics,
        level=level,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": -60},
    )

    assert "severe_elemental_resistance_shortfall" not in result["playabilityFailures"]
    assert "elemental_resistance_below_cap" not in result["qualityWarnings"]
    assert result["aggregateScore"]["value"] > 0.45
    assert result["aggregateScore"] == capped["aggregateScore"]
    assert result["scoreVector"]["defense"] == capped["scoreVector"]["defense"]
    assert (
        result["judgmentPolicy"]["elementalResistances"]
        == "endgame_hard_gate_60_otherwise_diagnostic"
    )


def test_trusted_reference_uncapped_resistance_can_be_flagged_as_source_data_problem():
    result = scoring.score_metrics(
        {
            "TotalDPS": 500_000,
            "PhysicalMaximumHitTaken": 58_219,
            "FireMaximumHitTaken": 61_923,
            "ColdMaximumHitTaken": 58_208,
            "LightningMaximumHitTaken": 76_588,
            "ChaosMaximumHitTaken": 45_343,
            "Life": 2_595,
            "LifeUnreserved": 2_595,
            "EnergyShield": 54_746,
            "TotalEHP": 60_324,
            "EnergyShieldRecharge": 6_845,
            "EffectiveMovementSpeedMod": 1.2,
        },
        level=100,
        resistances={"fire": 9, "cold": 0, "lightning": 27, "chaos": 32},
        source_context="trusted_reference",
    )

    assert "severe_elemental_resistance_shortfall" not in result["playabilityFailures"]
    assert "source_data_problem_caveat" in result["caveats"]
    assert "state_or_import_suspect_caveat" in result["caveats"]


def test_trusted_reference_limited_offense_and_strong_defense_can_downgrade_uncapped_resistance():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 892_213.77949873,
            "JudgeDPSMetric": "FullDPS",
            "JudgeSkillName": "Starfall",
            "JudgeSkillCaveats": [],
            "PhysicalMaximumHitTaken": 9_845,
            "FireMaximumHitTaken": 25_908,
            "ColdMaximumHitTaken": 22_375,
            "LightningMaximumHitTaken": 22_895,
            "ChaosMaximumHitTaken": 0,
            "Life": 1,
            "LifeUnreserved": 1,
            "EnergyShield": 8_555,
            "TotalEHP": 19_239,
            "EnergyShieldRecharge": 1_069.4,
            "EffectiveMovementSpeedMod": 1.31,
        },
        level=98,
        resistances={"fire": 74, "cold": 74, "lightning": 74, "chaos": 100},
        keystones=["Chaos Inoculation"],
        source_context="trusted_reference",
    )

    assert "uncapped_resistance" not in result["failures"]
    assert "elemental_resistance_below_cap" not in result["qualityWarnings"]
    assert (
        result["judgmentPolicy"]["elementalResistances"]
        == "endgame_hard_gate_60_otherwise_diagnostic"
    )


def test_trusted_reference_tiny_limited_offense_can_downgrade_uncapped_resistance_with_mature_defense():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 672.48944145269,
            "JudgeDPSMetric": "FullDPS",
            "JudgeSkillName": "Rend",
            "JudgeSkillCaveats": [],
            "PhysicalMaximumHitTaken": 6_625,
            "FireMaximumHitTaken": 12_500,
            "ColdMaximumHitTaken": 23_661,
            "LightningMaximumHitTaken": 23_661,
            "ChaosMaximumHitTaken": 0,
            "Life": 1,
            "LifeUnreserved": 1,
            "EnergyShield": 6_624,
            "TotalEHP": 54_452.618341824,
            "EnergyShieldRecharge": 828,
            "EffectiveMovementSpeedMod": 1.824,
        },
        level=98,
        resistances={"fire": 50, "cold": 75, "lightning": 75, "chaos": 45},
        keystones=["Chaos Inoculation"],
        source_context="trusted_reference",
    )

    assert "severe_elemental_resistance_shortfall" not in result["playabilityFailures"]
    assert "elemental_resistance_below_cap" not in result["qualityWarnings"]
    assert (
        result["judgmentPolicy"]["elementalResistances"]
        == "endgame_hard_gate_60_otherwise_diagnostic"
    )


def test_trusted_reference_strong_low_floor_can_downgrade_to_floor_unverified():
    result = scoring.score_metrics(
        {
            "CombinedDPS": 20_058.059855386,
            "PhysicalMaximumHitTaken": 4_548,
            "FireMaximumHitTaken": 15_379,
            "ColdMaximumHitTaken": 15_379,
            "LightningMaximumHitTaken": 15_379,
            "ChaosMaximumHitTaken": 4_153,
            "Life": 1_508,
            "LifeUnreserved": 1_508,
            "EnergyShield": 2_798,
            "TotalEHP": 37_203.526765248,
            "LifeRegenRecovery": 349.8,
            "Speed": 2.4,
            "EffectiveMovementSpeedMod": 0.97,
            "EvadeChance": 70,
        },
        level=98,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 20},
        source_context="trusted_reference",
    )

    assert "below_playability_floor" not in result["failures"]
    assert "trusted_reference_floor_unverified_caveat" in result["caveats"]


def test_trusted_reference_proxy_output_can_downgrade_floor_from_judge_dps_even_when_combined_is_zero():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 4_799.6256,
            "JudgeRawDPS": 4_799.6256,
            "JudgeEffectiveDPS": 4_799.6256,
            "JudgeDPSMetric": "CombinedDPS",
            "JudgeSkillName": "On Kill Monster Explosion",
            "JudgeMainSkill": "Blasphemy",
            "JudgeSkillCaveats": ["auto_selected_damage_skill_caveat"],
            "CombinedDPS": 0,
            "TotalDPS": 0,
            "PhysicalMaximumHitTaken": 8_496,
            "FireMaximumHitTaken": 13_016,
            "ColdMaximumHitTaken": 28_358,
            "LightningMaximumHitTaken": 29_360,
            "Life": 1,
            "LifeUnreserved": 1,
            "EnergyShield": 8_133,
            "Mana": 1_093,
            "ManaUnreserved": 1_093,
            "TotalEHP": 49_161.520560694,
            "EnergyShieldRecharge": 1_016.6,
            "EffectiveMovementSpeedMod": 1.296,
            "EvadeChance": 49,
        },
        level=100,
        resistances={"fire": 39, "cold": 74, "lightning": 75, "chaos": 10},
        keystones=["Chaos Inoculation", "Mind Over Matter"],
        source_context="trusted_reference",
    )

    assert "below_playability_floor" not in result["failures"]
    assert "trusted_reference_floor_unverified_caveat" in result["caveats"]


def test_trusted_reference_lower_bound_offense_does_not_hard_fail_floor():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 15_925.544123561,
            "JudgeDPSMetric": "WithPoisonDPS",
            "JudgeSkillName": "Cluster Grenade",
            "JudgeProjectileCount": 4,
            "JudgeSkillCaveats": ["lower_bound_dps_caveat"],
            "PhysicalMaximumHitTaken": 3_090,
            "FireMaximumHitTaken": 8_982,
            "ColdMaximumHitTaken": 8_982,
            "LightningMaximumHitTaken": 9_264,
            "ChaosMaximumHitTaken": 8_836,
            "Life": 2_209,
            "LifeUnreserved": 2_209,
            "TotalEHP": 10_725.762310857,
            "LifeRegenRecovery": 97.4,
            "EffectiveMovementSpeedMod": 1.235,
        },
        level=92,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )

    assert "below_playability_floor" not in result["failures"]
    assert "limited_offense_floor_unverified_caveat" in result["caveats"]


def test_flat_aggregate_does_not_include_scenario_fit():
    result = scoring.score_metrics(
        {
            "TotalDPS": 2_500_000,
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 1_000,
            "LifeRegenRecovery": 150,
            "Speed": 2.5,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    assert result["scoreScale"] == "0_to_1"
    assert result["aggregateScore"]["weightProfile"] == "judge_v6_evidence_separated"
    assert result["aggregateScore"]["value"] == pytest.approx(1.0)
    assert "mappingFit" in result["scenarioFit"]
    assert "scenarioFit" not in result["scoreVector"]


def test_campaign_aggregate_uses_stage_aware_smoothness_weights():
    result = scoring.score_metrics(
        {
            "TotalDPS": 80_000,
            "PhysicalMaximumHitTaken": 3_000,
            "FireMaximumHitTaken": 5_000,
            "ColdMaximumHitTaken": 5_000,
            "LightningMaximumHitTaken": 5_000,
            "ChaosMaximumHitTaken": 4_000,
            "LifeUnreserved": 2_000,
            "LifeRegenRecovery": 300,
            "EffectiveMovementSpeedMod": 1.5,
        },
        level=68,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 0},
    )

    assert result["aggregateScore"]["weights"] == {
        "offense": 0.35,
        "defense": 0.30,
        "recovery": 0.20,
        "mobility": 0.15,
    }


def test_mobility_can_use_skill_speed_when_walk_speed_is_baselineish():
    result = scoring.score_metrics(
        {
            "TotalDPS": 800_000,
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
            "EffectiveMovementSpeedMod": 0.999,
            "Speed": 2.5,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    assert result["scoreVector"]["mobility"]["value"] >= 0.5
    assert "skill_speed_mobility_fallback_caveat" in result["caveats"]


def test_offense_prefers_judge_selected_damage_metric_and_marks_provenance():
    result = scoring.score_metrics(
        {
            "TotalDPS": 0,
            "JudgeDPS": 750_000,
            "JudgeDPSMetric": "TotalDPS",
            "JudgeSkillName": "Fireball",
            "JudgeSkillGroupIndex": 2,
            "JudgeSkillCaveats": ["auto_selected_damage_skill_caveat"],
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    offense = result["scoreBreakdown"]["offense"]
    assert "below_playability_floor" not in result["failures"]
    assert "auto_selected_damage_skill_caveat" in result["caveats"]
    assert offense["rawValue"] == 750_000
    assert offense["sourceMetric"] == "JudgeDPS"
    assert offense["skillName"] == "Fireball"
    assert offense["skillGroupIndex"] == 2
    assert offense["provenance"] == "direct_pob_dps"
    assert offense["evidenceLevel"] == "strong"


def test_judge_full_dps_provenance_is_marked_as_socket_group_rollup():
    result = scoring.score_metrics(
        {
            "TotalDPS": 0,
            "JudgeDPS": 750_000,
            "JudgeDPSMetric": "FullDPS",
            "JudgeSkillName": "Fireball",
            "JudgeSkillGroupIndex": 2,
            "JudgeSkillCaveats": [],
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    offense = result["scoreBreakdown"]["offense"]
    assert offense["sourceMetric"] == "JudgeDPS"
    assert offense["sourceMetricDetail"] == "FullDPS"
    assert offense["provenanceDetail"] == "socket_group_full_dps_rollup"
    assert offense["provenance"] == "isolated_full_dps_rollup"
    assert offense["evidenceLevel"] == "limited"
    assert "full_dps_rollup_caveat" in result["caveats"]


def test_minion_judge_dps_uses_effective_dps_and_limited_evidence():
    result = scoring.score_metrics(
        {
            "TotalDPS": 0,
            "JudgeDPS": 40_000,
            "JudgeRawDPS": 10_000,
            "JudgeEffectiveDPS": 40_000,
            "JudgeDPSMetric": "MinionTotalDPS",
            "JudgeSkillName": "Skeletal Warrior",
            "JudgeSkillGroupIndex": 2,
            "JudgeIsMinion": True,
            "JudgeActiveSkillCount": 4,
            "JudgeActiveMinionLimit": 6,
            "JudgeSkillCaveats": ["minion_dps_unverified_caveat"],
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    offense = result["scoreBreakdown"]["offense"]
    assert "below_playability_floor" not in result["failures"]
    assert "limited_offense_floor_unverified_caveat" in result["caveats"]
    assert offense["provenance"] == "minion_pob_output"
    assert offense["evidenceLevel"] == "limited"
    assert offense["rawDps"] == 10_000
    assert offense["effectiveDps"] == 40_000
    assert offense["activeSkillCount"] == 4
    assert offense["activeMinionLimit"] == 6
    assert offense["isMinion"] is True
    assert "minion_dps_unverified_caveat" in result["caveats"]


def test_trusted_reference_limited_offense_does_not_hard_fail_floor():
    result = scoring.score_metrics(
        {
            "TotalDPS": 0,
            "JudgeDPS": 2_500,
            "JudgeDPSMetric": "FullDPS",
            "JudgeSkillName": "Molten Crash",
            "JudgeSkillCaveats": ["full_dps_rollup_caveat"],
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )

    assert "below_playability_floor" not in result["failures"]
    assert "limited_offense_floor_unverified_caveat" in result["caveats"]
    assert result["scoreBreakdown"]["offense"]["evidenceLevel"] == "limited"


def test_limited_offense_keeps_observed_score_visible_without_source_prior():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 2_500,
            "JudgeDPSMetric": "FullDPS",
            "JudgeSkillName": "Molten Crash",
            "JudgeSkillCaveats": ["full_dps_rollup_caveat"],
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )

    offense = result["scoreBreakdown"]["offense"]
    assert offense["observedValue"] == 0.0
    assert offense["value"] == 0.0
    assert offense["scorePolicy"] == "stage_curve_confidence_adjusted"
    assert "trusted_reference_limited_offense_prior_caveat" not in result["caveats"]
    assert "limited_offense_floor_unverified_caveat" in result["caveats"]


def test_generated_limited_offense_stays_strict():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 2_500,
            "JudgeDPSMetric": "FullDPS",
            "JudgeSkillName": "Molten Crash",
            "JudgeSkillCaveats": ["full_dps_rollup_caveat"],
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    assert "below_playability_floor" not in result["failures"]
    assert "limited_offense_floor_unverified_caveat" in result["caveats"]
    offense = result["scoreBreakdown"]["offense"]
    assert offense["value"] == 0.0
    assert offense["floorProgress"] == pytest.approx(0.05)
    assert "floorProgressCredit" not in offense
    assert offense["floorStatus"] == "unverified"
    assert offense["deliveryEvidenceStatus"] == "limited"
    assert offense["scorePolicy"] == "stage_curve_confidence_adjusted"
    assert "offense_delivery_not_established" in result["qualityWarnings"]
    assert result["aggregateScore"]["value"] <= 0.34
    assert result["qualityBand"] == "prototype_only"


def test_trusted_reference_zero_limited_offense_is_not_reclassified_as_generated_failure():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 2_500,
            "JudgeDPSMetric": "FullDPS",
            "JudgeSkillName": "Molten Crash",
            "JudgeSkillCaveats": ["full_dps_rollup_caveat"],
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )

    assert "offense_delivery_not_established" not in result["qualityWarnings"]


def test_limited_full_dps_evidence_is_source_agnostic():
    metrics = {
        "JudgeDPS": 108_793.0756074,
        "JudgeDPSMetric": "FullDPS",
        "JudgeSkillName": "Lightning Spear",
        "JudgeSkillGroupIndex": 8,
        "JudgeProjectileCount": 2,
        "JudgeSkillCaveats": [],
        "PhysicalMaximumHitTaken": 2_020,
        "FireMaximumHitTaken": 6_785,
        "ColdMaximumHitTaken": 7_036,
        "LightningMaximumHitTaken": 6_785,
        "ChaosMaximumHitTaken": 7_300,
        "LifeUnreserved": 1_898,
        "LifeRegenRecovery": 184.67028443087,
        "EffectiveMovementSpeedMod": 1.45,
    }
    resistances = {"fire": 75, "cold": 76, "lightning": 75, "chaos": 74}

    trusted = scoring.score_metrics(
        metrics,
        level=94,
        resistances=resistances,
        source_context="trusted_reference",
    )
    generated = scoring.score_metrics(
        metrics,
        level=94,
        resistances=resistances,
        source_context="generated_candidate",
    )

    assert trusted["scoreBreakdown"]["offense"]["provenance"] == "isolated_full_dps_rollup"
    assert generated["scoreBreakdown"]["offense"]["provenance"] == "isolated_full_dps_rollup"
    assert trusted["scoreBreakdown"]["offense"]["evidenceLevel"] == "limited"
    assert generated["scoreBreakdown"]["offense"]["evidenceLevel"] == "limited"
    assert (
        trusted["scoreBreakdown"]["offense"]["value"]
        == generated["scoreBreakdown"]["offense"]["value"]
    )
    assert trusted["aggregateScore"]["value"] == generated["aggregateScore"]["value"]
    assert "trusted_reference_limited_offense_prior_caveat" not in trusted["caveats"]
    assert "trusted_reference_limited_offense_prior_caveat" not in generated["caveats"]


def test_limited_full_dps_uses_reality_calibrated_quality_target():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 193_573.01556456,
            "JudgeDPSMetric": "FullDPS",
            "JudgeSkillName": "Comet",
            "PhysicalMaximumHitTaken": 6_419,
            "FireMaximumHitTaken": 22_510,
            "ColdMaximumHitTaken": 22_510,
            "LightningMaximumHitTaken": 22_510,
            "ChaosMaximumHitTaken": 5_712,
            "LifeUnreserved": 1_426,
            "EnergyShield": 2_986,
            "TotalEHP": 31_018.180536675,
        },
        level=98,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )

    offense = result["scoreBreakdown"]["offense"]
    assert offense["qualityFloor"] == 150_000
    assert offense["target"] == 750_000
    assert result["scoreVector"]["offense"]["value"] >= 0.24
    assert offense["scoreConfidenceFactor"] == 0.5


def test_low_pool_recovery_uses_gentler_reference_ratios():
    result = scoring.score_metrics(
        {
            "TotalDPS": 800_000,
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "Life": 1_712,
            "LifeUnreserved": 1_712,
            "LifeRegenRecovery": 0,
            "EnergyShield": 0,
            "Mana": 9_580,
            "ManaUnreserved": 9_580,
        },
        level=98,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )

    recovery = result["scoreBreakdown"]["recovery"]
    assert recovery["qualityFloor"] == pytest.approx(25.68)
    assert recovery["target"] == pytest.approx(136.96)


def test_ci_elemental_resistance_percentages_are_also_diagnostic_only():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 53_621.124821625,
            "JudgeDPSMetric": "FullDPS",
            "JudgeSkillName": "Kelari, the Tainted Sands",
            "JudgeIsMinion": True,
            "PhysicalMaximumHitTaken": 9_536,
            "FireMaximumHitTaken": 34_057,
            "ColdMaximumHitTaken": 12_384,
            "LightningMaximumHitTaken": 13_820,
            "ChaosMaximumHitTaken": 0,
            "Life": 1,
            "LifeUnreserved": 1,
            "EnergyShield": 9_535,
            "TotalEHP": 15_086.979971954,
            "EnergyShieldRecharge": 1_895.1,
            "EffectiveMovementSpeedMod": 1.45,
        },
        level=91,
        resistances={"fire": 75, "cold": 26, "lightning": 34, "chaos": 13},
        keystones=["Chaos Inoculation"],
        source_context="generated_candidate",
    )

    assert "severe_elemental_resistance_shortfall" not in result["playabilityFailures"]
    assert "elemental_resistance_below_cap" not in result["qualityWarnings"]
    assert (
        result["judgmentPolicy"]["elementalResistances"]
        == "endgame_hard_gate_60_otherwise_diagnostic"
    )
    assert result["scoreBreakdown"]["chaos"]["sourceMetric"] == "ChaosInoculation"


def test_metric_evidence_is_not_upgraded_to_trusted_reference_mobility_prior():
    metrics = {
        "JudgeDPS": 200_000,
        "JudgeDPSMetric": "FullDPS",
        "JudgeSkillName": "Lightning Spear",
        "PhysicalMaximumHitTaken": 12_000,
        "FireMaximumHitTaken": 25_000,
        "ColdMaximumHitTaken": 25_000,
        "LightningMaximumHitTaken": 25_000,
        "ChaosMaximumHitTaken": 18_000,
        "LifeUnreserved": 4_000,
        "LifeRegenRecovery": 600,
        "EffectiveMovementSpeedMod": 1.038,
    }
    trusted = scoring.score_metrics(
        metrics,
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )
    generated = scoring.score_metrics(
        metrics,
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="generated_candidate",
    )

    assert (
        trusted["scoreBreakdown"]["mobility"]["value"]
        == generated["scoreBreakdown"]["mobility"]["value"]
    )
    assert (
        trusted["scoreBreakdown"]["mobility"]["scorePolicy"]
        == generated["scoreBreakdown"]["mobility"]["scorePolicy"]
    )
    assert "trusted_reference_mobility_prior_caveat" not in trusted["caveats"]


def test_high_evasion_build_is_fragile_but_not_catastrophic_by_phys_max_hit_alone():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 108_793.0756074,
            "JudgeDPSMetric": "FullDPS",
            "JudgeSkillName": "Lightning Spear",
            "JudgeSkillGroupIndex": 8,
            "JudgeProjectileCount": 2,
            "PhysicalMaximumHitTaken": 2_020,
            "FireMaximumHitTaken": 6_785,
            "ColdMaximumHitTaken": 7_036,
            "LightningMaximumHitTaken": 6_785,
            "ChaosMaximumHitTaken": 7_300,
            "LifeUnreserved": 1_898,
            "LifeRegenRecovery": 184.67028443087,
            "TotalEHP": 15_567.99653705,
            "EvadeChance": 59,
            "EffectiveMovementSpeedMod": 1.45,
        },
        level=94,
        resistances={"fire": 75, "cold": 76, "lightning": 75, "chaos": 74},
        source_context="generated_candidate",
    )

    assert "catastrophic_defense_shortboard" not in result["failures"]
    assert result["scoreVector"]["defense"]["value"] < 0.25


def test_reference_uncapped_resistance_remains_diagnostic_only():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 80_000,
            "JudgeDPSMetric": "TotalDPS",
            "PhysicalMaximumHitTaken": 7_500,
            "FireMaximumHitTaken": 12_500,
            "ColdMaximumHitTaken": 12_500,
            "LightningMaximumHitTaken": 12_000,
            "ChaosMaximumHitTaken": 8_000,
            "TotalEHP": 12_500,
            "LifeUnreserved": 2_500,
            "EnergyShield": 1_500,
        },
        level=100,
        resistances={"fire": 70, "cold": 70, "lightning": 74, "chaos": 10},
        source_context="trusted_reference",
    )

    assert "uncapped_resistance" not in result["failures"]
    assert "elemental_resistance_below_cap" not in result["qualityWarnings"]
    assert (
        result["judgmentPolicy"]["elementalResistances"]
        == "endgame_hard_gate_60_otherwise_diagnostic"
    )


def test_reference_context_does_not_soften_single_physical_shortboard_score():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 200_000,
            "JudgeDPSMetric": "FullDPS",
            "PhysicalMaximumHitTaken": 5_044,
            "FireMaximumHitTaken": 19_400,
            "ColdMaximumHitTaken": 18_681,
            "LightningMaximumHitTaken": 18_014,
            "ChaosMaximumHitTaken": 12_127,
            "LifeUnreserved": 1_497,
            "EnergyShield": 3_297,
            "TotalEHP": 71_818,
            "LifeRegenRecovery": 471,
            "EffectiveMovementSpeedMod": 1.4,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )

    defense = result["scoreBreakdown"]["defense"]
    assert defense["observedValue"] < 0.4
    assert defense["value"] == defense["observedValue"]
    assert defense["scorePolicy"] == "max_hit_shortboard"
    assert "trusted_reference_ehp_defense_prior_caveat" not in result["caveats"]


def test_reference_context_does_not_soften_layered_avoidance_defense():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 760_000,
            "JudgeDPSMetric": "FullDPS",
            "PhysicalMaximumHitTaken": 6_394,
            "FireMaximumHitTaken": 22_014,
            "ColdMaximumHitTaken": 22_014,
            "LightningMaximumHitTaken": 22_014,
            "ChaosMaximumHitTaken": 15_788,
            "LifeUnreserved": 1_730,
            "EnergyShield": 4_434,
            "TotalEHP": 30_467,
            "EvadeChance": 48,
            "EnergyShieldRecharge": 554,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )

    defense = result["scoreBreakdown"]["defense"]
    assert defense["observedValue"] < 0.6
    assert defense["value"] == defense["observedValue"]
    assert defense["scorePolicy"] == "max_hit_shortboard"
    assert "trusted_reference_layered_defense_prior_caveat" not in result["caveats"]


def test_reference_context_does_not_soften_special_pool_defense():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 850_000,
            "JudgeDPSMetric": "FullDPS",
            "PhysicalMaximumHitTaken": 9_228,
            "FireMaximumHitTaken": 32_807,
            "ColdMaximumHitTaken": 32_807,
            "LightningMaximumHitTaken": 32_807,
            "ChaosMaximumHitTaken": 0,
            "LifeUnreserved": 1,
            "EnergyShield": 0,
            "ManaUnreserved": 9_185,
            "ManaRegenRecovery": 1_532,
            "TotalEHP": 23_628,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": -7},
        keystones=["Chaos Inoculation", "Eldritch Battery", "Mind Over Matter"],
        source_context="trusted_reference",
    )

    defense = result["scoreBreakdown"]["defense"]
    assert defense["observedValue"] < 0.9
    assert defense["value"] == defense["observedValue"]
    assert defense["scorePolicy"] == "max_hit_shortboard"
    assert "trusted_reference_special_pool_defense_prior_caveat" not in result["caveats"]


def test_generated_high_ehp_physical_shortboard_keeps_observed_defense_score():
    result = scoring.score_metrics(
        {
            "TotalDPS": 500_000,
            "PhysicalMaximumHitTaken": 5_044,
            "FireMaximumHitTaken": 19_400,
            "ColdMaximumHitTaken": 18_681,
            "LightningMaximumHitTaken": 18_014,
            "ChaosMaximumHitTaken": 12_127,
            "LifeUnreserved": 1_497,
            "EnergyShield": 3_297,
            "TotalEHP": 71_818,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    assert result["scoreBreakdown"]["defense"]["value"] < 0.4
    assert "trusted_reference_ehp_defense_prior_caveat" not in result["caveats"]


def test_projectile_damage_marks_overlap_unknown_without_calling_hit_dps_a_lower_bound():
    result = scoring.score_metrics(
        {
            "TotalDPS": 750_000,
            "ProjectileCount": 6,
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    assert "below_playability_floor" not in result["failures"]
    assert "projectile_overlap_unverified_caveat" in result["caveats"]
    assert result["scoreBreakdown"]["offense"]["projectileCount"] == 6
    assert result["scoreVector"]["offense"]["value"] > 0


def test_mobility_prefers_effective_movement_speed_over_skill_speed():
    result = scoring.score_metrics(
        {
            "TotalDPS": 2_500_000,
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
            "LifeRegenRecovery": 600,
            "Speed": 0.17,
            "EffectiveMovementSpeedMod": 1.45,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
    )

    mobility = result["scoreBreakdown"]["mobility"]
    assert mobility["sourceMetric"] == "EffectiveMovementSpeedMod"
    assert mobility["rawValue"] == 1.45
    assert result["scoreVector"]["mobility"]["value"] > 0


def test_missing_movement_metric_uses_skill_speed_fallback_even_for_reference_context():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 8,
            "JudgeDPSMetric": "FullDPS",
            "PhysicalMaximumHitTaken": 58_000,
            "FireMaximumHitTaken": 61_000,
            "ColdMaximumHitTaken": 58_000,
            "LightningMaximumHitTaken": 76_000,
            "ChaosMaximumHitTaken": 45_000,
            "LifeUnreserved": 2_500,
            "EnergyShield": 54_000,
            "LifeRegenRecovery": 6_800,
            "Speed": 0.17,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )

    mobility = result["scoreBreakdown"]["mobility"]
    assert mobility["sourceMetric"] == "Speed"
    assert mobility["rawValue"] == 0.17
    assert mobility["value"] == 0.0
    assert "skill_speed_mobility_fallback_caveat" in result["caveats"]


def test_reference_context_does_not_raise_low_movement_speed():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 200_000,
            "JudgeDPSMetric": "FullDPS",
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 18_000,
            "LifeUnreserved": 4_000,
            "LifeRegenRecovery": 600,
            "EffectiveMovementSpeedMod": 1.038,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )

    mobility = result["scoreBreakdown"]["mobility"]
    assert mobility["observedValue"] < 0.2
    assert mobility["value"] == mobility["observedValue"]
    assert mobility["scorePolicy"] == "movement_speed"
    assert "trusted_reference_mobility_prior_caveat" not in result["caveats"]


def test_reference_context_does_not_raise_low_recovery():
    result = scoring.score_metrics(
        {
            "JudgeDPS": 2_500,
            "JudgeDPSMetric": "FullDPS",
            "PhysicalMaximumHitTaken": 6_704,
            "FireMaximumHitTaken": 5_552,
            "ColdMaximumHitTaken": 12_032,
            "LightningMaximumHitTaken": 9_403,
            "ChaosMaximumHitTaken": 13_818,
            "LifeUnreserved": 3_819,
            "EnergyShield": 724,
            "TotalEHP": 45_073,
            "LifeRegenRecovery": 90.5,
        },
        level=100,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75},
        source_context="trusted_reference",
    )

    recovery = result["scoreBreakdown"]["recovery"]
    assert recovery["observedValue"] == 0.0
    assert recovery["value"] == 0.0
    assert recovery["scorePolicy"] == "dynamic_recovery_pool"
    assert "trusted_reference_recovery_prior_caveat" not in result["caveats"]


def test_mom_eb_build_uses_unreserved_mana_as_primary_recovery_pool():
    result = scoring.score_metrics(
        {
            "TotalDPS": 500_000,
            "PhysicalMaximumHitTaken": 12_000,
            "FireMaximumHitTaken": 25_000,
            "ColdMaximumHitTaken": 25_000,
            "LightningMaximumHitTaken": 25_000,
            "ChaosMaximumHitTaken": 0,
            "Life": 1,
            "LifeUnreserved": 1,
            "EnergyShield": 0,
            "Mana": 9_000,
            "ManaUnreserved": 9_000,
            "ManaRegenRecovery": 1_350,
            "TotalEHP": 25_000,
        },
        level=90,
        resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": -60},
        keystones=["Chaos Inoculation", "Eldritch Battery", "Mind Over Matter"],
    )

    recovery = result["scoreBreakdown"]["recovery"]
    assert recovery["primaryPool"] == 9_000
    assert recovery["sourceMetric"] == "dynamic_recovery_pool"
    assert recovery["diagnostics"]["primaryPoolSource"] == "ManaUnreserved"
    assert result["scoreVector"]["recovery"]["value"] == 1.0
    assert "mom_mana_primary_pool_caveat" in result["caveats"]
