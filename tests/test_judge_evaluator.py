from __future__ import annotations

from server.judge import evaluator, models


class _StubEngine:
    def __init__(self, build, stats, defenses):
        self._build = build
        self._stats = stats
        self._defenses = defenses
        self.requested_keys = None

    def get_build(self):
        return self._build

    def get_xml(self):
        return """<PathOfBuilding>
  <Build className="Mercenary" ascendClassName="Witchhunter" level="90" mainSocketGroup="1" />
  <Skills activeSkillSet="1"><SkillSet id="1" /></Skills>
  <Items activeItemSet="1"><ItemSet id="1" /></Items>
</PathOfBuilding>"""

    def list_jewel_sockets(self):
        return {"sockets": []}

    def get_stats(self, keys=None):
        self.requested_keys = keys
        if "warning" in self._stats:
            warning = self._stats["warning"]
            stats = dict(self._stats)
            del stats["warning"]
            return {"stats": stats, "warning": warning}
        return {"stats": self._stats}

    def get_defenses(self):
        return self._defenses


def _build(**overrides):
    base = {
        "class": "Mercenary",
        "ascendancy": "Witchhunter",
        "level": 90,
        "mainSkill": "Spark",
        "mainSkillGroup": [{"name": "Spark", "isSupport": False}],
        "pointsUsed": 90,
        "pointsAvailable": 113,
        "stats": {"TotalDPS": 500_000},
        "treeVersion": "0_5",
        "latestTreeVersion": "0_5",
        "spiritAvailable": 100,
        "spiritReservedCapped": 81,
        "spiritUnreserved": 19,
        "spiritRequested": 81,
        "spiritOverBy": 0,
        "spiritUsed": 81,
        "activeWeaponSet": 1,
        "unspentPoints": 0,
        "gear": {
            "Flask 1": {"name": "Fixture Unique Life Flask", "rarity": "unique"},
            "Flask 2": {
                "name": "Fixture Magic Mana Flask",
                "rarity": "magic",
                "itemLevel": 82,
                "affixPrefixes": 1,
                "affixSuffixes": 1,
                "affixLegality": {"ok": True, "issues": []},
            },
        },
    }
    base.update(overrides)
    return base


def _stats(**overrides):
    base = {
        "TotalDPS": 500_000,
        "FullDPS": 500_000,
        "Speed": 1.5,
        "HitChance": 100,
        "ProjectileCount": 1,
        "PhysicalMaximumHitTaken": 10_000,
        "FireMaximumHitTaken": 10_000,
        "ColdMaximumHitTaken": 10_000,
        "LightningMaximumHitTaken": 10_000,
        "ChaosMaximumHitTaken": 10_000,
        "Life": 4_000,
        "LifeUnreserved": 4_000,
        "LifeReserved": 0,
        "LifeUnreservedPercent": 100,
        "EnergyShield": 0,
        "TotalEHP": 20_000,
    }
    base.update(overrides)
    return base


def _defenses(**overrides):
    base = {"resistances": {"fire": 75, "cold": 75, "lightning": 75, "chaos": 75}}
    base.update(overrides)
    return base


def test_evaluator_requests_judge_metric_keys():
    engine = _StubEngine(_build(), _stats(), _defenses())

    result = evaluator.evaluate_active_build(engine, "legal")

    assert result["snapshotId"] == "legal"
    assert "PhysicalMaximumHitTaken" in engine.requested_keys
    assert "LifeRegenRecovery" in engine.requested_keys
    assert "LifeUnreserved" in engine.requested_keys
    assert "EnergyShieldRecharge" in engine.requested_keys
    assert "ReqStr" in engine.requested_keys
    assert "SpiritReserved" in engine.requested_keys
    assert result["scoreScale"] == "0_to_1"
    assert "scoreBreakdown" in result
    assert result["aggregateScore"]["weightProfile"] == "judge_v6_evidence_separated"
    assert result["defenseModel"]["poolModel"] == "life"
    assert result["defenseModel"]["confidence"] == "full"
    assert result["pass"] is True


def test_endgame_generated_candidate_blocks_resistances_below_60_and_30():
    engine = _StubEngine(
        _build(level=85),
        _stats(),
        _defenses(resistances={"fire": 59, "cold": 60, "lightning": 75, "chaos": 29}),
    )

    result = evaluator.evaluate_active_build(engine, "endgame-low-resists")

    assert result["pass"] is False
    assert "endgame_elemental_resistance_below_60" in result["hardFailures"]
    assert "endgame_chaos_resistance_below_30" in result["hardFailures"]
    gate = result["readinessGates"]["endgameResistances"]
    assert gate["belowElemental"] == ["fire"]
    assert gate["chaosBelowMinimum"] is True


def test_endgame_generated_candidate_accepts_exact_resistance_minimums():
    engine = _StubEngine(
        _build(level=85),
        _stats(),
        _defenses(resistances={"fire": 60, "cold": 60, "lightning": 60, "chaos": 30}),
    )

    result = evaluator.evaluate_active_build(engine, "endgame-resists-at-minimum")

    assert result["pass"] is True
    assert result["readinessGates"]["endgameResistances"]["status"] == "passed"


def test_generated_candidate_evaluator_enforces_final_create_completion_gates():
    engine = _StubEngine(
        _build(
            spiritReservedCapped=80,
            spiritUnreserved=20,
            spiritRequested=80,
            spiritUsed=80,
            unspentPoints=1,
        ),
        _stats(),
        _defenses(),
    )
    engine.list_jewel_sockets = lambda: {
        "sockets": [{"socket": 1, "allocated": True, "filled": False}]
    }

    result = evaluator.evaluate_active_build(engine, "incomplete-create")

    assert "spirit_utilization_not_above_80_percent" not in result["hardFailures"]
    assert "unspent_passive_points_remaining" in result["hardFailures"]
    assert "allocated_passive_jewel_socket_empty" in result["hardFailures"]
    assert result["pass"] is False


def test_non_endgame_resistances_remain_diagnostic_only():
    engine = _StubEngine(
        _build(level=79),
        _stats(),
        _defenses(resistances={"fire": -60, "cold": -60, "lightning": -60, "chaos": -60}),
    )

    result = evaluator.evaluate_active_build(engine, "maps-entry-low-resists")

    assert "endgame_elemental_resistance_below_60" not in result["hardFailures"]
    assert "endgame_chaos_resistance_below_30" not in result["hardFailures"]
    assert result["readinessGates"]["endgameResistances"]["status"] == "not_applicable"


def test_endgame_ci_is_exempt_from_chaos_resistance_minimum():
    engine = _StubEngine(
        _build(level=90, keystones=["Chaos Inoculation"]),
        _stats(),
        _defenses(resistances={"fire": 60, "cold": 60, "lightning": 60, "chaos": -60}),
    )

    result = evaluator.evaluate_active_build(engine, "endgame-ci-resists")

    assert "endgame_chaos_resistance_below_30" not in result["hardFailures"]
    assert result["pass"] is True
    assert result["readinessGates"]["endgameResistances"]["chaosInoculation"] is True


def test_evaluator_flags_no_weapon_attack_warning_as_physical_invalid():
    engine = _StubEngine(
        _build(),
        _stats(TotalDPS=0, warning="Main skill is an Attack but no weapon is equipped"),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "no-weapon")

    assert "attack_skill_without_weapon" in result["hardFailures"]
    assert result["pass"] is False
    assert result["rewardEligible"] is False


def test_evaluator_flags_passive_over_budget():
    engine = _StubEngine(_build(pointsUsed=120, pointsAvailable=113), _stats(), _defenses())

    result = evaluator.evaluate_active_build(engine, "over-budget")

    assert "passive_budget_exceeded" in result["hardFailures"]
    assert result["pass"] is False
    assert result["legality"]["passiveBudget"]["over"] == 7


def test_evaluator_blocks_active_gem_level_requirement_violation():
    build = _build(
        level=75,
        activeSkillGemLevelViolations=[
            {
                "groupIndex": 1,
                "name": "Storm Wave",
                "gemLevel": 20,
                "requiredLevel": 90,
                "characterLevel": 75,
                "maximumLegalLevel": 17,
            }
        ],
    )

    result = evaluator.evaluate_readback(
        build,
        _stats(),
        _defenses(),
        snapshot_id="illegal-active-gem",
    )

    assert "active_skill_gem_level_requirement_unmet" in result["hardFailures"]
    assert "active_skill_gem_level_requirement_unmet" in result["physicalInvalidFailures"]
    assert result["pass"] is False
    assert result["scoreVector"]["offense"]["blocked"] is True


def test_evaluator_allows_current_league_extra_passive_point_with_caveat():
    engine = _StubEngine(
        _build(
            level=100,
            pointsUsed=148,
            normalPassivePointsUsed=124,
            pointsAvailable=123,
            weaponSet1PointsUsed=24,
            weaponSet2PointsUsed=24,
            weaponSetPointsAvailable=24,
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "league-extra-point")

    assert "passive_budget_exceeded" not in result["hardFailures"]
    assert "league_extra_passive_point_caveat" in result["caveats"]
    assert result["pass"] is True
    assert result["legality"]["passiveBudget"]["leagueExtraApplied"] == 1


def test_evaluator_still_rejects_more_than_one_extra_passive_point():
    engine = _StubEngine(
        _build(
            level=100,
            pointsUsed=149,
            normalPassivePointsUsed=125,
            pointsAvailable=123,
            weaponSet1PointsUsed=24,
            weaponSet2PointsUsed=24,
            weaponSetPointsAvailable=24,
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "too-many-extra-points")

    assert "passive_budget_exceeded" in result["hardFailures"]
    assert "league_extra_passive_point_caveat" not in result["caveats"]
    assert result["pass"] is False


def test_trusted_reference_allows_small_imported_tree_budget_mismatch_as_limited():
    engine = _StubEngine(
        _build(
            level=100,
            pointsUsed=151,
            normalPassivePointsUsed=127,
            pointsAvailable=125,
            weaponSet1PointsUsed=24,
            weaponSet2PointsUsed=24,
            weaponSetPointsAvailable=24,
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_readback(
        engine.get_build(),
        engine.get_stats(models.JUDGE_METRIC_KEYS)["stats"],
        engine.get_defenses(),
        snapshot_id="trusted-budget-drift",
        source_context="trusted_reference",
    )

    assert "passive_budget_exceeded" not in result["hardFailures"]
    assert "imported_tree_budget_mismatch_caveat" in result["caveats"]
    assert result["pass"] is True
    assert result["rewardEligible"] == "limited"
    assert result["legality"]["passiveBudget"]["importedMismatchAllowed"] == 2


def test_generated_build_still_rejects_small_imported_tree_budget_mismatch():
    engine = _StubEngine(
        _build(
            level=100,
            pointsUsed=151,
            normalPassivePointsUsed=127,
            pointsAvailable=125,
            weaponSet1PointsUsed=24,
            weaponSet2PointsUsed=24,
            weaponSetPointsAvailable=24,
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "generated-budget-over")

    assert "passive_budget_exceeded" in result["hardFailures"]
    assert "imported_tree_budget_mismatch_caveat" not in result["caveats"]
    assert result["pass"] is False


def test_trusted_reference_large_passive_budget_anomaly_is_warning_not_hard_fail():
    engine = _StubEngine(
        _build(
            level=98,
            pointsUsed=123,
            normalPassivePointsUsed=123,
            pointsAvailable=121,
        ),
        _stats(
            TotalDPS=500_000,
            FullDPS=500_000,
            PhysicalMaximumHitTaken=10_000,
            FireMaximumHitTaken=20_000,
            ColdMaximumHitTaken=20_000,
            LightningMaximumHitTaken=20_000,
            ChaosMaximumHitTaken=12_000,
            Life=4_000,
            LifeUnreserved=4_000,
            TotalEHP=20_000,
        ),
        _defenses(resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75}),
    )

    result = evaluator.evaluate_readback(
        engine.get_build(),
        engine.get_stats(models.JUDGE_METRIC_KEYS)["stats"],
        engine.get_defenses(),
        snapshot_id="trusted-large-passive-anomaly",
        source_context="trusted_reference",
    )

    assert "passive_budget_exceeded" not in result["hardFailures"]
    assert "external_passive_budget_anomaly_caveat" in result["caveats"]
    assert result["pass"] is True
    assert result["rewardEligible"] == "limited"


def test_trusted_reference_allows_small_weapon_set_budget_mismatch_as_limited():
    engine = _StubEngine(
        _build(
            level=100,
            pointsUsed=150,
            normalPassivePointsUsed=125,
            pointsAvailable=123,
            weaponSet1PointsUsed=25,
            weaponSet2PointsUsed=25,
            weaponSetPointsAvailable=24,
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_readback(
        engine.get_build(),
        engine.get_stats(models.JUDGE_METRIC_KEYS)["stats"],
        engine.get_defenses(),
        snapshot_id="trusted-weapon-budget-drift",
        source_context="trusted_reference",
    )

    assert "passive_budget_exceeded" not in result["hardFailures"]
    assert "weapon_set_budget_exceeded" not in result["hardFailures"]
    assert "imported_tree_budget_mismatch_caveat" in result["caveats"]
    assert "imported_weapon_set_budget_mismatch_caveat" in result["caveats"]
    assert result["pass"] is True
    assert result["rewardEligible"] == "limited"


def test_generated_build_still_rejects_small_weapon_set_budget_mismatch():
    engine = _StubEngine(
        _build(
            level=100,
            pointsUsed=150,
            normalPassivePointsUsed=125,
            pointsAvailable=123,
            weaponSet1PointsUsed=25,
            weaponSet2PointsUsed=25,
            weaponSetPointsAvailable=24,
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "generated-weapon-budget-drift")

    assert "passive_budget_exceeded" in result["hardFailures"]
    assert "weapon_set_budget_exceeded" in result["hardFailures"]


def test_trusted_reference_weapon_set_budget_anomaly_is_warning_not_hard_fail():
    engine = _StubEngine(
        _build(
            level=100,
            pointsUsed=130,
            normalPassivePointsUsed=123,
            pointsAvailable=123,
            weaponSet1PointsUsed=27,
            weaponSet2PointsUsed=26,
            weaponSetPointsAvailable=24,
        ),
        _stats(
            TotalDPS=500_000,
            FullDPS=500_000,
            PhysicalMaximumHitTaken=10_000,
            FireMaximumHitTaken=20_000,
            ColdMaximumHitTaken=20_000,
            LightningMaximumHitTaken=20_000,
            ChaosMaximumHitTaken=12_000,
            Life=4_000,
            LifeUnreserved=4_000,
            TotalEHP=20_000,
        ),
        _defenses(resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75}),
    )

    result = evaluator.evaluate_readback(
        engine.get_build(),
        engine.get_stats(models.JUDGE_METRIC_KEYS)["stats"],
        engine.get_defenses(),
        snapshot_id="trusted-weapon-anomaly",
        source_context="trusted_reference",
    )

    assert "weapon_set_budget_exceeded" not in result["hardFailures"]
    assert "external_weapon_set_budget_anomaly_caveat" in result["caveats"]
    assert result["pass"] is True
    assert result["rewardEligible"] == "limited"


def test_evaluator_uses_normal_passive_count_when_weapon_sets_are_split():
    engine = _StubEngine(
        _build(
            pointsUsed=145,
            normalPassivePointsUsed=123,
            pointsAvailable=123,
            weaponSet1PointsUsed=22,
            weaponSet2PointsUsed=22,
            weaponSetPointsAvailable=24,
        ),
        _stats(TotalDPS=205_000, FullDPS=0),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "weapon-set-split")

    assert "passive_budget_exceeded" not in result["hardFailures"]
    assert result["pass"] is True


def test_evaluator_limits_reward_when_weapon_state_budget_is_used():
    engine = _StubEngine(
        _build(
            pointsUsed=145,
            normalPassivePointsUsed=123,
            pointsAvailable=123,
            weaponSet1PointsUsed=22,
            weaponSet2PointsUsed=22,
            weaponSetPointsAvailable=24,
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "dual-state")

    assert result["pass"] is True
    assert "dual_weapon_state_limited_caveat" in result["caveats"]
    assert result["rewardEligible"] == "limited"


def test_evaluator_flags_weapon_set_budget_exceeded():
    engine = _StubEngine(
        _build(
            pointsUsed=126,
            normalPassivePointsUsed=123,
            pointsAvailable=123,
            weaponSet1PointsUsed=27,
            weaponSet2PointsUsed=3,
            weaponSetPointsAvailable=24,
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "weapon-set-over")

    assert "weapon_set_budget_exceeded" in result["hardFailures"]
    assert "weapon_set_budget_exceeded" in result["physicalInvalidFailures"]
    assert result["legality"]["weaponSetBudget"]["overMax"] == 3


def test_evaluator_flags_attribute_requirement_shortfall():
    engine = _StubEngine(
        _build(
            attributes={"strength": 20, "dexterity": 80, "intelligence": 80},
            attributeRequirements={"strength": 95},
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "attribute-shortfall")

    assert "attribute_requirement_unmet" in result["hardFailures"]
    assert "attribute_requirement_unmet" in result["physicalInvalidFailures"]
    assert result["scoreVector"]["offense"]["blocked"] is True
    assert result["scoreVector"]["defense"]["blocked"] is True
    assert result["scoreVector"]["recovery"]["blocked"] is True
    assert result["scoreVector"]["mobility"]["blocked"] is True
    assert result["rewardEligible"] is False


def test_evaluator_flags_spirit_over_budget():
    engine = _StubEngine(
        _build(
            spiritUsed=120,
            spiritRequested=120,
            spiritAvailable=100,
            spiritReservedCapped=100,
            spiritUnreserved=-20,
            spiritOverBy=20,
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "spirit-shortfall")

    assert "spirit_budget_exceeded" in result["hardFailures"]
    assert result["pass"] is False


def test_evaluator_blocks_uncapped_endgame_resistances():
    engine = _StubEngine(
        _build(),
        _stats(TotalDPS=20_000_000),
        _defenses(resistances={"fire": -60, "cold": -60, "lightning": -60, "chaos": -60}),
    )

    result = evaluator.evaluate_active_build(engine, "uncapped")

    assert result["hardFailures"] == [
        "endgame_elemental_resistance_below_60",
        "endgame_chaos_resistance_below_30",
    ]
    assert "severe_elemental_resistance_shortfall" not in result["playabilityFailures"]
    assert "elemental_resistance_below_cap" not in result["qualityWarnings"]
    assert result["pass"] is False
    assert (
        result["judgmentPolicy"]["elementalResistances"]
        == "endgame_hard_gate_60_otherwise_diagnostic"
    )


def test_trusted_reference_can_downgrade_uncapped_resistance_when_other_evidence_is_mature():
    engine = _StubEngine(
        _build(
            **{"class": "Druid"},
            ascendancy="Oracle",
            level=98,
            keystones=["Chaos Inoculation"],
            judgeSelectedSkill={
                "skillName": "Starfall",
                "groupIndex": 11,
                "dps": 892_213.77949873,
                "sourceMetric": "FullDPS",
                "caveats": [],
            },
        ),
        _stats(
            TotalDPS=0,
            FullDPS=0,
            PhysicalMaximumHitTaken=9_845,
            FireMaximumHitTaken=25_908,
            ColdMaximumHitTaken=22_375,
            LightningMaximumHitTaken=22_895,
            ChaosMaximumHitTaken=0,
            Life=1,
            LifeUnreserved=1,
            EnergyShield=8_555,
            TotalEHP=19_239.746211945,
            EnergyShieldRecharge=1_069.4,
            EffectiveMovementSpeedMod=1.31,
        ),
        _defenses(resistances={"fire": 74, "cold": 74, "lightning": 74, "chaos": 100}),
    )

    result = evaluator.evaluate_readback(
        engine.get_build(),
        engine.get_stats(models.JUDGE_METRIC_KEYS)["stats"],
        engine.get_defenses(),
        snapshot_id="trusted-reference-uncapped-res-downgrade",
        source_context="trusted_reference",
    )

    assert result["pass"] is True
    assert "severe_elemental_resistance_shortfall" not in result["playabilityFailures"]
    assert "elemental_resistance_below_cap" not in result["qualityWarnings"]
    assert (
        result["judgmentPolicy"]["elementalResistances"]
        == "endgame_hard_gate_60_otherwise_diagnostic"
    )
    assert result["rewardEligible"] == "limited"


def test_trusted_reference_auto_selected_secondary_skill_can_downgrade_floor():
    engine = _StubEngine(
        _build(
            **{"class": "Warrior"},
            ascendancy="Smith of Kitava",
            level=92,
            mainSkill="Molten Crash",
            judgeSelectedSkill={
                "skillName": "Meteors",
                "groupIndex": 1,
                "dps": 44_630.243443963,
                "rawDps": 44_630.243443963,
                "effectiveDps": 44_630.243443963,
                "sourceMetric": "WithIgniteDPS",
                "caveats": ["auto_selected_damage_skill_caveat"],
            },
        ),
        _stats(
            TotalDPS=25_912.714373192,
            CombinedDPS=31_470.477232663,
            WithIgniteDPS=31_470.477232663,
            FullDPS=18_230.382875871,
            PhysicalMaximumHitTaken=5_598,
            FireMaximumHitTaken=12_782,
            ColdMaximumHitTaken=8_105,
            LightningMaximumHitTaken=9_439,
            ChaosMaximumHitTaken=11_597,
            Life=1_966,
            LifeUnreserved=1_966,
            EnergyShield=113,
            TotalEHP=18_279.825133083,
            LifeRegenRecovery=87.3,
            EffectiveMovementSpeedMod=1.43,
        ),
        _defenses(resistances={"fire": 76, "cold": 52, "lightning": 62, "chaos": 75}),
    )

    result = evaluator.evaluate_readback(
        engine.get_build(),
        engine.get_stats(models.JUDGE_METRIC_KEYS)["stats"],
        engine.get_defenses(),
        snapshot_id="trusted-reference-auto-selected-floor",
        source_context="trusted_reference",
    )

    assert result["pass"] is True
    assert "below_playability_floor" not in result["hardFailures"]
    assert "trusted_reference_floor_unverified_caveat" in result["caveats"]
    assert result["rewardEligible"] == "limited"


def test_evaluator_ci_keeps_uncapped_elemental_resistance_diagnostic_only():
    engine = _StubEngine(
        _build(
            **{"class": "Sorceress"},
            ascendancy="Disciple of Varashta",
            level=91,
            keystones=["Chaos Inoculation"],
        ),
        _stats(
            TotalDPS=53_621.124821625,
            FullDPS=53_621.124821625,
            PhysicalMaximumHitTaken=9_536,
            FireMaximumHitTaken=34_057,
            ColdMaximumHitTaken=12_384,
            LightningMaximumHitTaken=13_820,
            ChaosMaximumHitTaken=0,
            Life=1,
            LifeUnreserved=1,
            EnergyShield=9_535,
            TotalEHP=15_086.979971954,
            EnergyShieldRecharge=1_895.1,
        ),
        _defenses(resistances={"fire": 75, "cold": 26, "lightning": 34, "chaos": 13}),
    )

    result = evaluator.evaluate_active_build(engine, "ci-ele-uncapped")

    assert "severe_elemental_resistance_shortfall" not in result["playabilityFailures"]
    assert "elemental_resistance_below_cap" not in result["qualityWarnings"]
    assert result["hardFailures"] == ["endgame_elemental_resistance_below_60"]
    assert result["scoreBreakdown"]["chaos"]["sourceMetric"] == "ChaosInoculation"
    assert (
        result["judgmentPolicy"]["elementalResistances"]
        == "endgame_hard_gate_60_otherwise_diagnostic"
    )


def test_evaluator_reports_non_endgame_scope_without_score_or_reward_penalty():
    engine = _StubEngine(
        _build(
            level=75,
            mainSkillGroup=[
                {"name": "Spark", "isSupport": False},
                {"name": "Arcane Tempo", "isSupport": True},
                {"name": "Controlled Destruction", "isSupport": True},
            ],
        ),
        _stats(
            JudgeDPS=100_000,
            JudgeDPSMetric="TotalDPS",
            JudgeRawDPS=100_000,
            JudgeEffectiveDPS=100_000,
            JudgeSkillName="Spark",
            TotalDPS=100_000,
            FullDPS=100_000,
            EffectiveMovementSpeedMod=1.3,
        ),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "level-75")

    assert "non_endgame_sample_caveat" not in result["caveats"]
    assert "non_endgame_scope" not in result["rewardLimitReasons"]
    assert result["levelBand"] == "maps_entry"
    assert result["rewardEligible"] is True
    assert result["rewardStrength"] == "strong"


def test_evaluator_treats_strong_dps_below_floor_as_stage_failure_not_evidence_gap():
    engine = _StubEngine(
        _build(
            mainSkillGroup=[
                {"name": "Spark", "isSupport": False},
                {"name": "Arcane Tempo", "isSupport": True},
                {"name": "Controlled Destruction", "isSupport": True},
            ]
        ),
        _stats(
            JudgeDPS=10_000,
            JudgeDPSMetric="TotalDPS",
            JudgeRawDPS=10_000,
            JudgeEffectiveDPS=10_000,
            JudgeSkillName="Spark",
            TotalDPS=10_000,
            FullDPS=10_000,
            EffectiveMovementSpeedMod=1.3,
        ),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "strong-below-floor")

    assert "below_playability_floor" in result["playabilityFailures"]
    assert "offense_delivery_not_established" not in result["qualityWarnings"]
    assert result["scoreBreakdown"]["offense"]["metricStatus"] == "available"
    assert result["scoreBreakdown"]["offense"]["floorStatus"] == "missed"
    assert result["scoreBreakdown"]["offense"]["deliveryEvidenceStatus"] == "established"
    assert result["rewardEligible"] is False
    assert result["rewardStrength"] == "none"


def test_evaluator_allows_campaign_missing_ascendancy_with_caveat():
    engine = _StubEngine(_build(level=60, ascendancy=""), _stats(TotalDPS=80_000), _defenses())

    result = evaluator.evaluate_active_build(engine, "campaign-unascended")

    assert "invalid_class_ascendancy_pairing" not in result["hardFailures"]
    assert "missing_ascendancy_non_endgame_caveat" in result["caveats"]
    assert result["pass"] is True


def test_evaluator_allows_one_point_passive_budget_drift_for_high_level_reference_samples():
    engine = _StubEngine(
        _build(
            **{"class": "Monk"},
            ascendancy="Martial Artist",
            level=91,
            pointsUsed=115,
            normalPassivePointsUsed=115,
            pointsAvailable=114,
        ),
        _stats(
            TotalDPS=424_353.9274452,
            FullDPS=424_353.9274452,
            PhysicalMaximumHitTaken=7_164,
            FireMaximumHitTaken=22_212,
            ColdMaximumHitTaken=26_483,
            LightningMaximumHitTaken=24_592,
            ChaosMaximumHitTaken=4_353,
            Life=1_594,
            LifeUnreserved=1_594,
            EnergyShield=5_065,
            TotalEHP=14_963.991458922,
            LifeRegenRecovery=633.1,
        ),
        _defenses(resistances={"fire": 72, "cold": 77, "lightning": 75, "chaos": 0}),
    )

    result = evaluator.evaluate_readback(
        engine.get_build(),
        engine.get_stats(models.JUDGE_METRIC_KEYS)["stats"],
        engine.get_defenses(),
        snapshot_id="high-level-reference-plus-one",
        source_context="trusted_reference",
    )

    assert "passive_budget_exceeded" not in result["hardFailures"]
    assert "league_extra_passive_point_caveat" in result["caveats"]
    assert result["legality"]["passiveBudget"]["leagueExtraApplied"] == 1


def test_evaluator_flags_meta_trigger_core_blocker():
    engine = _StubEngine(
        _build(
            mainSkillGroup=[
                {"name": "Spark", "isSupport": False},
                {"name": "Cast on Critical", "isSupport": True},
            ]
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "meta-trigger")

    assert result["modelability"]["coreBlocked"] is False
    assert result["hardFailures"] == []
    assert result["pass"] is True
    assert result["rewardEligible"] == "limited"


def test_evaluator_flags_tree_version_mismatch_caveat():
    engine = _StubEngine(_build(treeVersion="0_4", latestTreeVersion="0_5"), _stats(), _defenses())

    result = evaluator.evaluate_active_build(engine, "version-drift")

    assert "version_mismatch_caveat" in result["caveats"]


def test_evaluator_passes_keystones_for_ci_chaos_scoring():
    engine = _StubEngine(
        _build(keystones=["Chaos Inoculation"]),
        _stats(
            Life=1,
            LifeUnreserved=1,
            EnergyShield=9_000,
            ChaosMaximumHitTaken=0,
            TotalEHP=30_000,
        ),
        _defenses(resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": -60}),
    )

    result = evaluator.evaluate_active_build(engine, "ci")

    assert result["pass"] is True
    assert "uncapped_resistance" not in result["hardFailures"]
    assert result["scoreBreakdown"]["chaos"]["sourceMetric"] == "ChaosInoculation"


def test_evaluator_reports_low_life_primary_pool_breakdown():
    engine = _StubEngine(
        _build(),
        _stats(
            Life=5_000,
            LifeUnreserved=1_000,
            LifeReserved=4_000,
            LifeUnreservedPercent=20,
            EnergyShield=500,
            LifeRegenRecovery=150,
        ),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "low-life")

    recovery = result["scoreBreakdown"]["recovery"]
    assert recovery["primaryPool"] == 1_000
    assert recovery["diagnostics"]["Life"] == 5_000
    assert recovery["diagnostics"]["LifeReserved"] == 4_000


def test_evaluator_uses_judge_selected_skill_for_offense_summary_and_scoring():
    engine = _StubEngine(
        _build(
            mainSkill="Dread Banner",
            judgeSelectedSkill={
                "skillName": "Molten Blast",
                "groupIndex": 3,
                "dps": 750_000,
                "sourceMetric": "TotalDPS",
                "caveats": ["auto_selected_damage_skill_caveat"],
            },
        ),
        _stats(TotalDPS=0, FullDPS=0),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "auto-selected")

    assert "below_playability_floor" not in result["hardFailures"]
    assert result["summary"]["mainSkill"] == "Dread Banner"
    assert result["summary"]["judgeSelectedSkill"] == "Molten Blast"
    assert result["scoreBreakdown"]["offense"]["rawValue"] == 750_000
    assert result["scoreBreakdown"]["offense"]["provenance"] == "direct_pob_dps"
    assert result["scoreBreakdown"]["offense"]["evidenceLevel"] == "strong"
    assert "auto_selected_damage_skill_caveat" in result["caveats"]


def test_evaluator_limits_reward_for_full_dps_rollup_offense():
    engine = _StubEngine(
        _build(
            mainSkill="Dread Banner",
            judgeSelectedSkill={
                "skillName": "Molten Crash",
                "groupIndex": 3,
                "dps": 750_000,
                "sourceMetric": "FullDPS",
                "caveats": [],
            },
        ),
        _stats(TotalDPS=0, FullDPS=0),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "full-dps-rollup")

    assert result["pass"] is True
    assert result["rewardEligible"] == "limited"
    offense = result["scoreBreakdown"]["offense"]
    assert offense["provenance"] == "isolated_full_dps_rollup"
    assert offense["evidenceLevel"] == "limited"
    assert "full_dps_rollup_caveat" in result["caveats"]


def test_evaluator_reports_minion_effective_dps_from_selected_skill():
    engine = _StubEngine(
        _build(
            mainSkill="Raise Skeletons",
            mainSkillGroup=[{"name": "Raise Skeletons", "isSupport": False}],
            judgeSelectedSkill={
                "skillName": "Raise Skeletons",
                "groupIndex": 1,
                "dps": 60_000,
                "rawDps": 15_000,
                "effectiveDps": 60_000,
                "sourceMetric": "MinionTotalDPS",
                "isMinion": True,
                "activeSkillCount": 4,
                "activeMinionLimit": 6,
                "caveats": ["minion_dps_unverified_caveat"],
            },
            judgeSelectedSkillGroup=[{"name": "Raise Skeletons", "isSupport": False}],
        ),
        _stats(TotalDPS=0, FullDPS=0),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "minion-selected")

    offense = result["scoreBreakdown"]["offense"]
    assert result["rewardEligible"] == "limited"
    assert offense["provenance"] == "minion_pob_output"
    assert offense["rawDps"] == 15_000
    assert offense["effectiveDps"] == 60_000
    assert offense["activeSkillCount"] == 4
    assert offense["activeMinionLimit"] == 6


def test_evaluator_checks_selected_damage_group_socket_legality():
    engine = _StubEngine(
        _build(
            mainSkill="Dread Banner",
            mainSkillGroup=[{"name": "Dread Banner", "isSupport": False}],
            judgeSelectedSkill={
                "skillName": "Molten Blast",
                "groupIndex": 3,
                "dps": 750_000,
                "sourceMetric": "TotalDPS",
            },
            judgeSelectedSkillGroup=[
                {"name": "Molten Blast", "isSupport": False},
                {"name": "Martial Tempo", "isSupport": True, "supportKnown": True},
                {"name": "Martial Tempo", "isSupport": True, "supportKnown": True},
            ],
        ),
        _stats(TotalDPS=0, FullDPS=0),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "selected-duplicate-support")

    assert "duplicate_support_gem" in result["hardFailures"]
    assert "duplicate_support_gem" in result["physicalInvalidFailures"]
    assert result["scoreVector"]["offense"]["blocked"] is True
    assert result["rewardEligible"] is False


def test_evaluator_keeps_conditional_on_kill_damage_as_supplemental_evidence():
    engine = _StubEngine(
        _build(
            mainSkill="Galvanic Shards",
            mainSkillGroup=[
                {"name": "Galvanic Shards", "isSupport": False},
                {"name": "Rapid Attacks I", "isSupport": True, "supportKnown": True},
            ],
            judgeSelectedSkill={
                "skillName": "Galvanic Shards",
                "groupIndex": 1,
                "dps": 500_000,
                "sourceMetric": "TotalDPS",
                "groupOrigin": "socketed",
                "socketLegalityApplicable": True,
            },
            judgeSelectedSkillGroup=[
                {"name": "Galvanic Shards", "isSupport": False},
                {"name": "Rapid Attacks I", "isSupport": True, "supportKnown": True},
            ],
            judgeSupplementalSkills=[
                {
                    "skillName": "On Kill Monster Explosion",
                    "groupIndex": 3,
                    "groupOrigin": "synthetic_on_kill",
                    "socketLegalityApplicable": False,
                    "scenarioLimitations": ["requires_kill"],
                }
            ],
        ),
        _stats(),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "conditional-supplemental")

    assert "invalid_socket_setup" not in result["hardFailures"]
    assert "conditional_supplemental_damage_caveat" in result["caveats"]
    assert result["supplementalDamageComponents"] == [
        {
            "skillName": "On Kill Monster Explosion",
            "groupIndex": 3,
            "groupOrigin": "synthetic_on_kill",
            "scenarioLimitations": ["requires_kill"],
        }
    ]


def test_trusted_reference_attribute_shortfall_is_still_hard_failure():
    engine = _StubEngine(
        _build(
            **{"class": "Witch"},
            ascendancy="Infernalist",
            level=95,
            attributes={"strength": 166, "dexterity": 95, "intelligence": 168},
            attributeRequirements={"strength": 121, "dexterity": 126, "intelligence": 157},
        ),
        _stats(
            TotalDPS=283_452.77068363,
            FullDPS=283_452.77068363,
            PhysicalMaximumHitTaken=7_105,
            FireMaximumHitTaken=17_732,
            ColdMaximumHitTaken=18_645,
            LightningMaximumHitTaken=13_249,
            ChaosMaximumHitTaken=9_682,
            Life=1_927,
            LifeUnreserved=1_927,
            EnergyShield=73,
            TotalEHP=16_329.5032762439,
        ),
        _defenses(resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 75}),
    )

    result = evaluator.evaluate_readback(
        engine.get_build(),
        engine.get_stats(models.JUDGE_METRIC_KEYS)["stats"],
        engine.get_defenses(),
        snapshot_id="trusted-attribute-shortfall",
        source_context="trusted_reference",
    )

    assert "attribute_requirement_unmet" not in result["hardFailures"]
    assert "attribute_requirement_unmet" not in result["physicalInvalidFailures"]
    assert "trusted_reference_attribute_requirement_mismatch_caveat" in result["caveats"]
    assert result["rewardEligible"] == "limited"


def test_trusted_reference_multi_active_selected_group_becomes_caveat_not_hard_failure():
    engine = _StubEngine(
        _build(
            mainSkill="Comet",
            mainSkillGroup=[{"name": "Comet", "isSupport": False}],
            judgeSelectedSkill={
                "skillName": "Comet",
                "groupIndex": 2,
                "dps": 900_000,
                "sourceMetric": "FullDPS",
            },
            judgeSelectedSkillGroup=[
                {"name": "Comet", "isSupport": False},
                {"name": "Frost Bomb", "isSupport": False},
                {"name": "Controlled Destruction", "isSupport": True, "supportKnown": True},
            ],
        ),
        _stats(TotalDPS=0, FullDPS=0),
        _defenses(),
    )

    result = evaluator.evaluate_readback(
        engine.get_build(),
        engine.get_stats(models.JUDGE_METRIC_KEYS)["stats"],
        engine.get_defenses(),
        snapshot_id="trusted-multi-active-group",
        source_context="trusted_reference",
    )

    assert "invalid_socket_setup" not in result["hardFailures"]
    assert "invalid_socket_setup" not in result["physicalInvalidFailures"]
    assert "external_multi_active_socket_group_caveat" in result["caveats"]
    assert result["rewardEligible"] == "limited"


def test_evaluator_checks_selected_damage_group_modelability():
    engine = _StubEngine(
        _build(
            mainSkill="Dread Banner",
            mainSkillGroup=[{"name": "Dread Banner", "isSupport": False}],
            judgeSelectedSkill={
                "skillName": "Spark",
                "groupIndex": 3,
                "dps": 750_000,
                "sourceMetric": "TotalDPS",
            },
            judgeSelectedSkillGroup=[
                {"name": "Spark", "isSupport": False},
                {"name": "Cast on Critical", "isSupport": True, "supportKnown": True},
            ],
        ),
        _stats(TotalDPS=0, FullDPS=0),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "selected-meta-trigger")

    assert result["modelability"]["coreBlocked"] is False
    assert "unmodelled_mechanic" not in result["hardFailures"]
    assert result["pass"] is True
    assert result["rewardEligible"] == "limited"


def test_evaluator_flags_selected_skill_weapon_requirement_mismatch():
    engine = _StubEngine(
        _build(
            mainSkill="Dread Banner",
            mainSkillGroup=[{"name": "Dread Banner", "isSupport": False}],
            judgeSelectedSkill={
                "skillName": "Lightning Spear",
                "groupIndex": 3,
                "dps": 0,
                "sourceMetric": "TotalDPS",
                "weaponCheck": {
                    "skillName": "Lightning Spear",
                    "weaponTypes": ["Spear"],
                    "equippedWeaponTypes": ["Wand"],
                    "disableReason": "Main Hand weapon is not usable with this skill",
                },
            },
            judgeSelectedSkillGroup=[{"name": "Lightning Spear", "isSupport": False}],
        ),
        _stats(TotalDPS=0, FullDPS=0),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "selected-weapon-mismatch")

    assert "incompatible_weapon_skill_tags" in result["hardFailures"]
    assert "incompatible_weapon_skill_tags" in result["physicalInvalidFailures"]
    assert result["scoreVector"]["offense"]["blocked"] is True
    assert result["rewardEligible"] is False


def test_evaluator_does_not_use_warning_fallback_when_selected_weapon_check_is_compatible():
    engine = _StubEngine(
        _build(
            mainSkill="Lightning Spear",
            judgeSelectedSkill={
                "skillName": "Lightning Spear",
                "groupIndex": 5,
                "dps": 500_000,
                "sourceMetric": "FullDPS",
                "weaponCheck": {
                    "skillName": "Lightning Spear",
                    "weaponTypes": ["Spear"],
                    "equippedWeaponTypes": ["Sceptre", "Spear"],
                    "compatible": True,
                },
            },
            mainSkillWeaponCheck={
                "skillName": "Lightning Spear",
                "weaponTypes": ["Spear"],
                "equippedWeaponTypes": ["Sceptre", "Spear"],
                "compatible": True,
            },
        ),
        _stats(TotalDPS=0, FullDPS=0, warning="Attack skill has no weapon"),
        _defenses(warnings=["Attack skill has no weapon"]),
    )

    result = evaluator.evaluate_active_build(engine, "warning-fallback-compatible")

    assert "attack_skill_without_weapon" not in result["hardFailures"]


def test_metric_unavailable_keeps_selection_but_limits_reward_eligibility():
    engine = _StubEngine(
        _build(),
        _stats(
            PhysicalMaximumHitTaken=None,
            FireMaximumHitTaken=None,
            ColdMaximumHitTaken=None,
            LightningMaximumHitTaken=None,
            ChaosMaximumHitTaken=None,
            TotalEHP=25_000,
        ),
        _defenses(),
    )

    result = evaluator.evaluate_active_build(engine, "missing-max-hit")

    assert result["pass"] is True
    assert "metric_unavailable_caveat" in result["caveats"]
    assert result["rewardEligible"] == "limited"


def test_trusted_reference_suspect_defense_state_limits_reward_strength():
    engine = _StubEngine(
        _build(level=100),
        _stats(
            TotalDPS=900_000,
            FullDPS=0,
            EffectiveMovementSpeedMod=2.5,
            PhysicalMaximumHitTaken=10_000,
            FireMaximumHitTaken=25_000,
            ColdMaximumHitTaken=25_000,
            LightningMaximumHitTaken=25_000,
            ChaosMaximumHitTaken=18_000,
            Life=1,
            LifeUnreserved=1,
            EnergyShield=0,
            TotalEHP=50_000,
        ),
        _defenses(),
    )

    result = evaluator.evaluate_readback(
        engine.get_build(),
        engine.get_stats(models.JUDGE_METRIC_KEYS)["stats"],
        engine.get_defenses(),
        snapshot_id="trusted-suspect-defense-state",
        source_context="trusted_reference",
    )

    assert result["pass"] is True
    assert "defense_state_unverified_caveat" in result["caveats"]
    assert "state_or_import_suspect_caveat" in result["caveats"]
    assert result["rewardEligible"] == "limited"
    assert result["rewardStrength"] == "limited"


def test_evaluator_marks_passed_low_scoring_reference_as_needing_score_review():
    engine = _StubEngine(
        _build(level=98),
        _stats(
            TotalDPS=90_000,
            FullDPS=90_000,
            PhysicalMaximumHitTaken=3_400,
            FireMaximumHitTaken=7_000,
            ColdMaximumHitTaken=7_000,
            LightningMaximumHitTaken=7_000,
            ChaosMaximumHitTaken=7_500,
            Life=1_652,
            LifeUnreserved=1_652,
            TotalEHP=24_482.954231424,
            LifeRegenRecovery=234.51792,
            EffectiveMovementSpeedMod=1.5,
            EvadeChance=56,
            EffectiveAverageBlockChance=20,
        ),
        _defenses(resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": 74}),
    )

    result = evaluator.evaluate_readback(
        engine.get_build(),
        engine.get_stats(models.JUDGE_METRIC_KEYS)["stats"],
        engine.get_defenses(),
        snapshot_id="low-score-pass",
        source_context="trusted_reference",
    )

    assert result["pass"] is True
    assert result["scoreReviewNeeded"] is True
    assert "aggregate_below_0_5" in result["scoreReviewReasons"]
    assert "offense_below_0_5" in result["scoreReviewReasons"]
    assert "defense_below_0_5" in result["scoreReviewReasons"]


def test_evaluator_requests_mana_metrics_for_mom_eb_recovery():
    engine = _StubEngine(
        _build(keystones=["Chaos Inoculation", "Eldritch Battery", "Mind Over Matter"]),
        _stats(
            Life=1,
            LifeUnreserved=1,
            EnergyShield=0,
            Mana=9_000,
            ManaUnreserved=9_000,
            ManaRegenRecovery=1_350,
            ChaosMaximumHitTaken=0,
        ),
        _defenses(resistances={"fire": 75, "cold": 75, "lightning": 75, "chaos": -60}),
    )

    result = evaluator.evaluate_active_build(engine, "mom-eb")

    assert "ManaUnreserved" in engine.requested_keys
    assert "ManaLeechGainRate" in engine.requested_keys
    assert result["scoreBreakdown"]["recovery"]["primaryPool"] == 9_000
    assert result["defenseModel"]["poolModel"] == "eb_mom_mana"
    assert result["defenseModel"]["confidence"] == "partial"
    assert "mom_mana_primary_pool_caveat" in result["caveats"]
