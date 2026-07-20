"""Deterministic scoring heuristics for Phase 1 judge evaluation."""

from __future__ import annotations

import math
from typing import Any

from server.compute import sustain

from . import models

CRITICAL_FAILURE_PENALTIES_V1 = {
    "SEVERE_RESISTANCE_SCORE_CAP": 0.45,
    "CATASTROPHIC_DEFENSE_SCORE_CAP": 0.35,
    "UNESTABLISHED_OFFENSE_SCORE_CAP": 0.34,
}

ELEMENTAL_RESISTANCE_SEVERE_FLOOR = {
    "campaign": 30.0,
    "maps_entry": 60.0,
    "endgame": 60.0,
}
ELEMENTAL_RESISTANCE_QUALITY_TARGET = 75.0

SCORING_TARGETS_V1: dict[str, dict[str, float]] = {
    "campaign": {
        "dps_hard_floor": 5_000,
        "dps_quality_floor": 20_000,
        "dps_target": 80_000,
        "physical_hard_floor": 1_000,
        "physical_quality_floor": 1_500,
        "physical_target": 3_000,
        "elemental_hard_floor": 1_500,
        "elemental_quality_floor": 2_500,
        "elemental_target": 5_000,
        "chaos_hard_floor": 500,
        "chaos_quality_floor": 1_500,
        "chaos_target": 4_000,
        "ehp_quality_floor": 4_000,
        "ehp_target": 10_000,
    },
    "maps_entry": {
        "dps_hard_floor": 50_000,
        "dps_quality_floor": 100_000,
        "dps_target": 600_000,
        "physical_hard_floor": 3_000,
        "physical_quality_floor": 4_000,
        "physical_target": 8_000,
        "elemental_hard_floor": 5_000,
        "elemental_quality_floor": 8_000,
        "elemental_target": 18_000,
        "chaos_hard_floor": 2_000,
        "chaos_quality_floor": 5_000,
        "chaos_target": 12_000,
        "ehp_quality_floor": 10_000,
        "ehp_target": 18_000,
    },
    "endgame": {
        "dps_hard_floor": 50_000,
        "dps_quality_floor": 300_000,
        "dps_target": 2_500_000,
        "physical_hard_floor": 5_000,
        "physical_quality_floor": 6_000,
        "physical_target": 12_000,
        "elemental_hard_floor": 5_000,
        "elemental_quality_floor": 12_000,
        "elemental_target": 25_000,
        "chaos_hard_floor": 1_000,
        "chaos_quality_floor": 8_000,
        "chaos_target": 18_000,
        "ehp_quality_floor": 12_000,
        "ehp_target": 24_000,
    },
}

LIMITED_EVIDENCE_DPS_QUALITY_FLOOR = {
    "campaign": 15_000.0,
    "maps_entry": 80_000.0,
    "endgame": 150_000.0,
}

LIMITED_EVIDENCE_DPS_TARGET = {
    "campaign": 60_000.0,
    "maps_entry": 350_000.0,
    "endgame": 750_000.0,
}

MAX_HIT_KEYS = [
    "PhysicalMaximumHitTaken",
    "FireMaximumHitTaken",
    "ColdMaximumHitTaken",
    "LightningMaximumHitTaken",
    "ChaosMaximumHitTaken",
]

DAMAGE_BREAKDOWN = {
    "physical": (
        "PhysicalMaximumHitTaken",
        "physical_hard_floor",
        "physical_quality_floor",
        "physical_target",
    ),
    "fire": (
        "FireMaximumHitTaken",
        "elemental_hard_floor",
        "elemental_quality_floor",
        "elemental_target",
    ),
    "cold": (
        "ColdMaximumHitTaken",
        "elemental_hard_floor",
        "elemental_quality_floor",
        "elemental_target",
    ),
    "lightning": (
        "LightningMaximumHitTaken",
        "elemental_hard_floor",
        "elemental_quality_floor",
        "elemental_target",
    ),
    "chaos": ("ChaosMaximumHitTaken", "chaos_hard_floor", "chaos_quality_floor", "chaos_target"),
}

AGGREGATE_WEIGHTS_BY_BAND_V3 = {
    # Campaign smoothness depends materially on recovery and movement, not only PoB damage/EHP.
    "campaign": {"offense": 0.35, "defense": 0.30, "recovery": 0.20, "mobility": 0.15},
    "maps_entry": {"offense": 0.375, "defense": 0.35, "recovery": 0.175, "mobility": 0.10},
    "endgame": {"offense": 0.40, "defense": 0.40, "recovery": 0.15, "mobility": 0.05},
}

SPEED_QUALITY_FLOOR = 1.0
SPEED_TARGET = 2.5
MOVEMENT_SPEED_QUALITY_FLOOR = 1.0
MOVEMENT_SPEED_TARGET = 1.5
RECOVERY_FLOOR_RATIO = 0.03
RECOVERY_TARGET_RATIO = 0.15
LOW_POOL_RECOVERY_FLOOR_RATIO = 0.015
LOW_POOL_RECOVERY_TARGET_RATIO = 0.08
LOW_POOL_RECOVERY_THRESHOLD = 3_000.0
EHP_COMPENSATION_BASE = 40_000.0
EHP_COMPENSATION_MAX = 1.5
EHP_COMPENSATED_PHYSICAL_HARD_FLOOR_RATIO = 0.85


def level_band(level: int | None) -> str:
    lvl = int(level or 0)
    if lvl < 70:
        return "campaign"
    if lvl < 80:
        return "maps_entry"
    return "endgame"


def floor_caveats(level: int | None) -> list[str]:
    # Evaluation scope is already explicit in levelBand. Reward limitations are handled by the
    # evaluator instead of presenting non-endgame scope as a build defect.
    return []


def target_log_score(value: Any, *, quality_floor: float, target: float) -> float:
    value_f = _num(value)
    if value_f <= quality_floor or quality_floor <= 0 or target <= quality_floor:
        return 0.0
    if value_f >= target:
        return 1.0
    return _clamp(math.log10(value_f / quality_floor) / math.log10(target / quality_floor))


def log_score(value: Any, *, floor: float) -> float:
    """Backward-compatible floor-only score helper."""

    return target_log_score(value, quality_floor=floor, target=floor * 10)


def score_metrics(
    metrics: dict[str, Any],
    *,
    level: int | None,
    resistances: dict[str, Any] | None,
    blocked_dimensions: set[str] | None = None,
    keystones: list[str] | None = None,
    source_context: str = "generated_candidate",
) -> dict[str, Any]:
    blocked = set(blocked_dimensions or set())
    band = level_band(level)
    targets = SCORING_TARGETS_V1[band]
    caveats = floor_caveats(level)
    playability_failures: list[str] = []
    quality_warnings: list[str] = []
    provenance = {key: "pob_computed" for key in metrics if metrics.get(key) is not None}
    breakdown: dict[str, Any] = {}

    dps, dps_key, offense_meta = _offense_metric(metrics)
    offense_floor = targets["dps_hard_floor"]
    offense_quality_floor = targets["dps_quality_floor"]
    offense_target = targets["dps_target"]
    if offense_meta.get("evidenceLevel") == "limited":
        offense_quality_floor = LIMITED_EVIDENCE_DPS_QUALITY_FLOOR[band]
        offense_target = LIMITED_EVIDENCE_DPS_TARGET[band]
    offense_observed = target_log_score(
        dps,
        quality_floor=offense_floor,
        target=offense_target,
    )
    metric_status = "available" if dps > 0 else "unavailable"
    offense_evidence = str(offense_meta.get("evidenceLevel") or "none")
    floor_progress = _clamp(dps / offense_floor) if dps > 0 and offense_floor > 0 else 0.0
    confidence_factor = {"strong": 1.0, "limited": 0.5}.get(offense_evidence, 0.0)
    offense_value = offense_observed * confidence_factor
    if dps <= 0:
        floor_status = "unavailable"
        delivery_evidence_status = "unavailable"
    else:
        floor_status = (
            "met"
            if dps >= offense_floor
            else ("unverified" if offense_evidence == "limited" else "missed")
        )
        delivery_evidence_status = {
            "strong": "established",
            "limited": "limited",
        }.get(offense_evidence, "unavailable")
    score_policy = {
        "strong": "stage_curve",
        "limited": "stage_curve_confidence_adjusted",
    }.get(offense_evidence, "unavailable")
    offense_blocked = "offense" in blocked
    limited_offense = offense_meta.get("evidenceLevel") == "limited"
    offense_meta_caveats = list(offense_meta.get("caveats") or [])
    lower_bound_offense = "lower_bound_dps_caveat" in offense_meta_caveats
    if dps < targets["dps_hard_floor"]:
        if limited_offense or lower_bound_offense:
            caveats.append("limited_offense_floor_unverified_caveat")
        elif offense_evidence in {"none", "unknown"}:
            caveats.append("offense_metric_unavailable_caveat")
        elif source_context == "trusted_reference" and _allow_reference_floor_downgrade(
            metrics, breakdown, offense_meta, offense_meta_caveats
        ):
            caveats.append("trusted_reference_floor_unverified_caveat")
        else:
            playability_failures.append("below_playability_floor")
            offense_blocked = True
    elif dps < offense_quality_floor:
        quality_warnings.append("offense_quality_target_missed")
    caveats.extend(offense_meta.pop("caveats", []))
    breakdown["offense"] = {
        "value": round(_clamp(offense_value), 6),
        "observedValue": round(_clamp(offense_observed), 6),
        "rawValue": dps,
        "hardFloor": offense_floor,
        "scoreFloor": offense_floor,
        "qualityFloor": offense_quality_floor,
        "target": offense_target,
        "metricStatus": metric_status,
        "floorProgress": round(floor_progress, 6),
        "floorStatus": floor_status,
        "deliveryEvidenceStatus": delivery_evidence_status,
        "scoreConfidenceFactor": confidence_factor,
        "scorePolicy": score_policy,
        "sourceMetric": dps_key,
        **offense_meta,
    }

    defense_value = _score_defense(
        metrics,
        targets,
        keystones,
        resistances,
        playability_failures,
        quality_warnings,
        caveats,
        breakdown,
        source_context,
        band,
    )
    recovery_value = _score_recovery(metrics, caveats, breakdown, keystones, source_context, band)
    mana_sustain = (breakdown.get("recovery") or {}).get("manaSustain") or {}
    if mana_sustain.get("classification") == "flask_assisted_required":
        quality_warnings.append("mana_flask_dependency")
        caveats.append("long_boss_mana_sustain_risk_caveat")
    elif mana_sustain.get("classification") == "unsustainable":
        playability_failures.append("mana_sustain_unsustainable")
    mobility_value = _score_mobility(metrics, caveats, breakdown, source_context, band)
    mobility_blocked = "mobility" in blocked
    if "mobility" in blocked:
        mobility_value = 0.0
    if "mobility" not in breakdown:
        breakdown["mobility"] = {
            "value": round(_clamp(mobility_value), 6),
            "rawValue": 0.0,
            "sourceMetric": "unavailable",
        }

    res = resistances or {}
    ci_active = _has_chaos_inoculation(keystones, res)
    if source_context == "trusted_reference" and _resistance_state_suspect(metrics, res, ci_active):
        caveats.append("source_data_problem_caveat")
        caveats.append("state_or_import_suspect_caveat")
    elemental_values = [_num(res.get(k)) for k in ("fire", "cold", "lightning")]
    resistance_floor = ELEMENTAL_RESISTANCE_SEVERE_FLOOR[band]
    severe_resistance_shortfall = any(value < resistance_floor for value in elemental_values)
    below_resistance_target = any(
        value < ELEMENTAL_RESISTANCE_QUALITY_TARGET for value in elemental_values
    )
    if severe_resistance_shortfall:
        playability_failures.append("severe_elemental_resistance_shortfall")
    if below_resistance_target:
        quality_warnings.append("elemental_resistance_below_cap")
    if (not ci_active) and _num(res.get("chaos")) < 0:
        quality_warnings.append("negative_chaos_resistance")
    if severe_resistance_shortfall and source_context == "trusted_reference":
        playability_failures = [
            failure
            for failure in playability_failures
            if failure != "severe_elemental_resistance_shortfall"
        ]
        caveats.append("trusted_reference_uncapped_resistance_caveat")

    score_vector = {
        "offense": {
            "value": 0.0 if offense_blocked else _clamp(offense_value),
            "blocked": offense_blocked,
        },
        "defense": {"value": _clamp(defense_value), "blocked": "defense" in blocked},
        "recovery": {"value": _clamp(recovery_value), "blocked": "recovery" in blocked},
        "mobility": {"value": _clamp(mobility_value), "blocked": mobility_blocked},
    }
    for dimension in blocked:
        if dimension in score_vector:
            score_vector[dimension]["value"] = 0.0
            score_vector[dimension]["blocked"] = True

    aggregate_weights = AGGREGATE_WEIGHTS_BY_BAND_V3[band]
    aggregate = sum(
        score_vector[key]["value"] * weight for key, weight in aggregate_weights.items()
    )
    if source_context == "generated_candidate" and delivery_evidence_status != "established":
        # Limited PoB evidence must not become a false low-DPS legality failure. It also must not
        # let unrelated dimensions average an unproven damage package into a finished build.
        quality_warnings.append("offense_delivery_not_established")
        aggregate = min(
            aggregate,
            CRITICAL_FAILURE_PENALTIES_V1["UNESTABLISHED_OFFENSE_SCORE_CAP"],
        )
    if "severe_elemental_resistance_shortfall" in playability_failures:
        aggregate = min(aggregate, CRITICAL_FAILURE_PENALTIES_V1["SEVERE_RESISTANCE_SCORE_CAP"])
    if "catastrophic_defense_shortboard" in playability_failures:
        aggregate = min(aggregate, CRITICAL_FAILURE_PENALTIES_V1["CATASTROPHIC_DEFENSE_SCORE_CAP"])
    if blocked:
        aggregate = 0.0

    scenario_fit = _scenario_fit(score_vector)

    return {
        "levelBand": band,
        "playabilityFailures": _dedupe(playability_failures),
        "qualityWarnings": _dedupe(quality_warnings),
        # Deprecated compatibility alias. Callers must not merge these into legality failures.
        "failures": _dedupe(playability_failures),
        "caveats": _dedupe(caveats),
        "scoreVector": _round_score_vector(score_vector),
        "scoreBreakdown": breakdown,
        "scoreScale": "0_to_1",
        "scenarioFit": scenario_fit,
        "qualityBand": _quality_band(
            aggregate,
            playability_failures,
            blocked,
            delivery_evidence_status=delivery_evidence_status,
        ),
        "aggregateScore": {
            "value": round(_clamp(aggregate), 6),
            "weightProfile": models.WEIGHT_PROFILE,
            "weights": aggregate_weights,
        },
        "metricProvenance": provenance,
    }


def _score_defense(
    metrics: dict[str, Any],
    targets: dict[str, float],
    keystones: list[str] | None,
    resistances: dict[str, Any] | None,
    playability_failures: list[str],
    quality_warnings: list[str],
    caveats: list[str],
    breakdown: dict[str, Any],
    source_context: str,
    band: str,
) -> float:
    values: dict[str, float] = {}
    scores: dict[str, float] = {}
    ci_active, ci_via_resist = _ci_status(keystones, resistances)
    if ci_active:
        caveats.append("ci_chaos_immunity_caveat")
    if ci_via_resist:
        caveats.append("ci_resist_fallback_caveat")

    suspicious_defense_state = _suspicious_defense_state(metrics, ci_active)
    if suspicious_defense_state:
        caveats.append("defense_state_unverified_caveat")
        if _num(metrics.get("TotalEHP")) > 0:
            caveats.append("state_or_import_suspect_caveat")

    missing = False
    for name, (metric_key, hard_floor_key, floor_key, target_key) in DAMAGE_BREAKDOWN.items():
        hard_floor = targets[hard_floor_key]
        quality_floor = targets[floor_key]
        target = targets[target_key]
        if name == "chaos" and ci_active:
            scores[name] = 1.0
            values[name] = _num(metrics.get(metric_key))
            breakdown[name] = {
                "value": 1.0,
                "baseValue": 1.0,
                "rawValue": values[name],
                "hardFloor": hard_floor,
                "qualityFloor": quality_floor,
                "target": target,
                "sourceMetric": "ChaosInoculation",
            }
            continue
        if metrics.get(metric_key) is None:
            missing = True
            continue
        value = _num(metrics.get(metric_key))
        score = target_log_score(value, quality_floor=hard_floor, target=target)
        values[name] = value
        scores[name] = score
        breakdown[name] = {
            "value": round(score, 6),
            "baseValue": round(score, 6),
            "rawValue": value,
            "hardFloor": hard_floor,
            "scoreFloor": hard_floor,
            "qualityFloor": quality_floor,
            "target": target,
            "sourceMetric": metric_key,
        }

    if scores and "physical" in scores:
        min_name = min(scores, key=scores.get)
        if min_name == "physical":
            ehp = _num(metrics.get("TotalEHP"))
            multiplier = _clamp(ehp / EHP_COMPENSATION_BASE, 1.0, EHP_COMPENSATION_MAX)
            if multiplier > 1.0:
                base = scores["physical"]
                scores["physical"] = min(1.0, base * multiplier)
                breakdown["physical"]["baseValue"] = round(base, 6)
                breakdown["physical"]["value"] = round(scores["physical"], 6)
                breakdown["physical"]["ehpMultiplier"] = round(multiplier, 6)

    if scores:
        chaos_resist = _num((resistances or {}).get("chaos"))
        shortboard_scores = dict(scores)
        if band == "campaign" and not ci_active and chaos_resist >= 0:
            # Campaign gear should make chaos resistance non-negative, not sacrifice every suffix
            # to cap it. Keep the chaos Max Hit diagnostic, but do not let it dominate 60% of the
            # defense score once the campaign legality baseline is met.
            shortboard_scores.pop("chaos", None)
            caveats.append("campaign_chaos_resistance_opportunity_cost_caveat")
            breakdown["chaos"]["excludedFromDefenseShortboard"] = True
        avoidance_proof = _has_avoidance_proof(metrics)
        low_elemental_count = 0
        for name, value in values.items():
            if name == "chaos" and ci_active:
                continue
            hard_floor = breakdown[name]["hardFloor"]
            if name in {"fire", "cold", "lightning"} and value < hard_floor:
                low_elemental_count += 1
            if value < hard_floor:
                if _physical_shortboard_compensated(name, value, hard_floor, metrics):
                    caveats.append("physical_shortboard_ehp_compensated_caveat")
                    continue
                if _is_catastrophic_shortboard(
                    name=name,
                    value=value,
                    metrics=metrics,
                    ci_active=ci_active,
                    low_elemental_count=low_elemental_count,
                    avoidance_proof=avoidance_proof,
                    suspicious_defense_state=suspicious_defense_state
                    and source_context == "trusted_reference",
                ):
                    playability_failures.append("catastrophic_defense_shortboard")
                    break
            if value < breakdown[name]["qualityFloor"]:
                quality_warnings.append(f"{name}_max_hit_quality_target_missed")
        if missing:
            caveats.append("metric_unavailable_caveat")
        score_basis = shortboard_scores or scores
        min_score = min(score_basis.values())
        mean_score = sum(score_basis.values()) / len(score_basis)
        observed_defense = (0.6 * min_score) + (0.4 * mean_score)
        defense = observed_defense
        score_policy = "max_hit_shortboard"
        if _avoidance_evasion_profile(metrics, scores):
            defense = max(defense, min(0.72, (mean_score * 0.60) + 0.12))
            score_policy = "avoidance_evasion_hybrid"
        breakdown["defense"] = {
            "value": round(_clamp(defense), 6),
            "observedValue": round(_clamp(observed_defense), 6),
            "minScore": round(min_score, 6),
            "meanScore": round(mean_score, 6),
            "sourceMetric": "MaximumHitTaken",
            "scorePolicy": score_policy,
            "scoreComponents": list(score_basis),
        }
        return defense

    caveats.append("metric_unavailable_caveat")
    ehp = _num(metrics.get("TotalEHP"))
    defense = target_log_score(
        ehp,
        quality_floor=targets["ehp_quality_floor"],
        target=targets["ehp_target"],
    )
    if ehp < targets["ehp_quality_floor"]:
        playability_failures.append("catastrophic_defense_shortboard")
    breakdown["defense"] = {
        "value": round(_clamp(defense), 6),
        "observedValue": round(_clamp(defense), 6),
        "rawValue": ehp,
        "qualityFloor": targets["ehp_quality_floor"],
        "target": targets["ehp_target"],
        "sourceMetric": "TotalEHP",
        "scorePolicy": "total_ehp_fallback",
    }
    return defense


def _physical_shortboard_compensated(
    name: str, value: float, hard_floor: float, metrics: dict[str, Any]
) -> bool:
    if name != "physical":
        return False
    if value < hard_floor * EHP_COMPENSATED_PHYSICAL_HARD_FLOOR_RATIO:
        return False
    return _num(metrics.get("TotalEHP")) >= EHP_COMPENSATION_BASE


def _is_catastrophic_shortboard(
    *,
    name: str,
    value: float,
    metrics: dict[str, Any],
    ci_active: bool,
    low_elemental_count: int,
    avoidance_proof: bool,
    suspicious_defense_state: bool = False,
) -> bool:
    if suspicious_defense_state:
        return False
    phys = _num(metrics.get("PhysicalMaximumHitTaken"))
    total_ehp = _num(metrics.get("TotalEHP"))
    chaos = _num(metrics.get("ChaosMaximumHitTaken"))
    if phys >= 5_000:
        return False
    if total_ehp >= 12_000:
        return False
    if avoidance_proof:
        return False
    if phys < 3_000:
        return True
    if low_elemental_count >= 2:
        return True
    if (not ci_active) and chaos < 1_000:
        return True
    return name != "physical" and value <= 0


def _has_avoidance_proof(metrics: dict[str, Any]) -> bool:
    if _num(metrics.get("EvadeChance")) >= 55:
        return True
    if _num(metrics.get("EffectiveAverageBlockChance")) >= 20:
        return True
    if _num(metrics.get("EffectiveSpellSuppressionChance")) >= 75:
        return True
    if _num(metrics.get("AvoidAllDamageFromHitsChance")) >= 15:
        return True
    return False


def _avoidance_evasion_profile(metrics: dict[str, Any], scores: dict[str, float]) -> bool:
    evade = _num(metrics.get("EvadeChance"))
    if evade < 55:
        return False
    if _num(metrics.get("EffectiveAverageBlockChance")) >= 20:
        return False
    phys = _num(metrics.get("PhysicalMaximumHitTaken"))
    total_ehp = _num(metrics.get("TotalEHP"))
    if phys <= 0 or phys >= 6_500:
        return False
    if total_ehp < 17_000:
        return False
    if scores.get("physical", 0.0) >= 0.5:
        return False
    elemental_mean = (
        scores.get("fire", 0.0) + scores.get("cold", 0.0) + scores.get("lightning", 0.0)
    ) / 3.0
    return elemental_mean >= 0.35


def _suspicious_defense_state(metrics: dict[str, Any], ci_active: bool) -> bool:
    primary_candidates = [
        _num(metrics.get("LifeUnreserved")),
        _num(metrics.get("EnergyShield")),
        _num(metrics.get("ManaUnreserved")),
    ]
    primary_pool = max(primary_candidates)
    total_ehp = _num(metrics.get("TotalEHP"))
    max_hits = [
        _num(metrics.get("PhysicalMaximumHitTaken")),
        _num(metrics.get("FireMaximumHitTaken")),
        _num(metrics.get("ColdMaximumHitTaken")),
        _num(metrics.get("LightningMaximumHitTaken")),
    ]
    low_max_hits = sum(1 for value in max_hits if 0 < value < 2_000)
    if ci_active and _num(metrics.get("EnergyShield")) <= 50 and total_ehp < 5_000:
        return True
    if ci_active and primary_pool <= 1 and total_ehp < 2_000:
        return True
    if primary_pool <= 1 and total_ehp >= 5_000:
        return True
    if total_ehp < 2_000 and low_max_hits >= 3:
        return True
    return False


def _resistance_state_suspect(
    metrics: dict[str, Any],
    resistances: dict[str, Any],
    ci_active: bool,
) -> bool:
    elemental = [_num(resistances.get(k)) for k in ("fire", "cold", "lightning")]
    low_elemental = sum(1 for value in elemental if value < 75)
    min_elemental = min(elemental) if elemental else 75
    total_ehp = _num(metrics.get("TotalEHP"))
    phys = _num(metrics.get("PhysicalMaximumHitTaken"))
    fire = _num(metrics.get("FireMaximumHitTaken"))
    cold = _num(metrics.get("ColdMaximumHitTaken"))
    lightning = _num(metrics.get("LightningMaximumHitTaken"))
    strong_hits = sum(1 for value in (phys, fire, cold, lightning) if value >= 20_000)
    if low_elemental >= 2 and min_elemental <= 30 and strong_hits >= 3:
        return True
    if low_elemental >= 2 and min_elemental <= 10 and total_ehp >= 25_000:
        return True
    if (
        (not ci_active)
        and _num(resistances.get("chaos")) < 0
        and total_ehp >= 25_000
        and strong_hits >= 3
    ):
        return True
    return False


def _score_recovery(
    metrics: dict[str, Any],
    caveats: list[str],
    breakdown: dict[str, Any],
    keystones: list[str] | None,
    source_context: str,
    band: str,
) -> float:
    life_unreserved = _maybe_num(metrics.get("LifeUnreserved"))
    life = _maybe_num(metrics.get("Life"))
    energy_shield = _num(metrics.get("EnergyShield"))
    mana_unreserved = _maybe_num(metrics.get("ManaUnreserved"))
    mana = _maybe_num(metrics.get("Mana"))
    life_pool_source = "LifeUnreserved"
    if life_unreserved is None:
        if life is not None:
            life_unreserved = life
            life_pool_source = "Life"
            caveats.append("life_unreserved_missing_caveat")
        else:
            life_unreserved = 0.0
    mana_pool = 0.0
    mana_pool_source = "ManaUnreserved"
    if _has_keystone(keystones, "Mind Over Matter"):
        if mana_unreserved is not None:
            mana_pool = mana_unreserved
        elif mana is not None:
            mana_pool = mana
            mana_pool_source = "Mana"
            caveats.append("mana_unreserved_missing_caveat")
        if mana_pool > max(float(life_unreserved), energy_shield):
            caveats.append("mom_mana_primary_pool_caveat")
    pool_candidates = [
        (float(life_unreserved), life_pool_source),
        (energy_shield, "EnergyShield"),
        (float(mana_pool), mana_pool_source),
    ]
    primary_pool, primary_pool_source = max(pool_candidates, key=lambda item: item[0])
    if primary_pool <= 0:
        caveats.append("primary_pool_unavailable_caveat")
        breakdown["recovery"] = {
            "value": 0.0,
            "rawValue": 0.0,
            "primaryPool": 0.0,
            "qualityFloor": 0.0,
            "target": 0.0,
            "sourceMetric": "unavailable",
            "diagnostics": _recovery_diagnostics(metrics, life_pool_source),
        }
        return 0.0

    life_leech = _num(metrics.get("LifeLeechGainRate"))
    if life_leech <= 0:
        life_leech = _num(metrics.get("LifeOnHitRate"))
    es_leech = _num(metrics.get("EnergyShieldLeechGainRate"))
    if es_leech <= 0:
        es_leech = _num(metrics.get("EnergyShieldOnHitRate"))
    if metrics.get("EnergyShieldRecharge") is None and energy_shield > 0:
        caveats.append("recharge_metric_unavailable_caveat")
    life_recovery = max(
        _num(metrics.get("LifeRegenRecovery")),
        life_leech,
        _num(metrics.get("LifeRecharge")),
    )
    es_recovery = max(
        _num(metrics.get("EnergyShieldRegenRecovery")),
        es_leech,
        _num(metrics.get("EnergyShieldRecharge")),
    )
    mana_leech = _num(metrics.get("ManaLeechGainRate"))
    if mana_leech <= 0:
        mana_leech = _num(metrics.get("ManaOnHitRate"))
    mana_recovery = max(
        _num(metrics.get("ManaRegenRecovery")),
        _num(metrics.get("NetManaRegen")),
        mana_leech,
    )
    total_recovery = (
        life_recovery
        + es_recovery
        + (mana_recovery if primary_pool_source in {"ManaUnreserved", "Mana"} else 0.0)
    )
    floor_ratio = RECOVERY_FLOOR_RATIO
    target_ratio = RECOVERY_TARGET_RATIO
    if primary_pool <= LOW_POOL_RECOVERY_THRESHOLD:
        floor_ratio = LOW_POOL_RECOVERY_FLOOR_RATIO
        target_ratio = LOW_POOL_RECOVERY_TARGET_RATIO
    quality_floor = primary_pool * floor_ratio
    target = primary_pool * target_ratio
    observed_score = target_log_score(total_recovery, quality_floor=quality_floor, target=target)
    score = observed_score
    score_policy = "dynamic_recovery_pool"
    mana_sustain = sustain.classify_mana_sustain(
        metrics,
        mana_flask_equipped=(
            metrics.get("ManaFlaskEquipped")
            if isinstance(metrics.get("ManaFlaskEquipped"), bool)
            else None
        ),
    )
    breakdown["recovery"] = {
        "value": round(_clamp(score), 6),
        "observedValue": round(_clamp(observed_score), 6),
        "rawValue": total_recovery,
        "primaryPool": primary_pool,
        "qualityFloor": quality_floor,
        "target": target,
        "sourceMetric": "dynamic_recovery_pool",
        "scorePolicy": score_policy,
        "diagnostics": _recovery_diagnostics(metrics, life_pool_source, primary_pool_source),
        "manaSustain": mana_sustain,
    }
    return score


def _allow_reference_floor_downgrade(
    metrics: dict[str, Any],
    breakdown: dict[str, Any],
    offense_meta: dict[str, Any],
    offense_meta_caveats: list[str] | None = None,
) -> bool:
    caveats = set(offense_meta_caveats or offense_meta.get("caveats") or [])
    raw_dps = (
        _num(metrics.get("JudgeRawDPS"))
        or _num(metrics.get("JudgeDPS"))
        or _num(metrics.get("CombinedDPS"))
        or _num(metrics.get("TotalDPS"))
        or _num((breakdown.get("offense") or {}).get("rawValue"))
    )
    main_skill = str(metrics.get("JudgeMainSkill") or "")
    selected_skill = str(metrics.get("JudgeSkillName") or "")
    if "auto_selected_damage_skill_caveat" in caveats:
        total_ehp = _num(metrics.get("TotalEHP"))
        evade = _num(metrics.get("EvadeChance"))
        phys = _num(metrics.get("PhysicalMaximumHitTaken"))
        return bool(
            main_skill
            and selected_skill
            and main_skill != selected_skill
            and raw_dps > 0
            and (total_ehp >= 40_000 or evade >= 50 or phys >= 4_500)
        )
    if (
        main_skill
        and selected_skill
        and main_skill != selected_skill
        and raw_dps > 0
        and (offense_meta.get("evidenceLevel") == "strong")
    ):
        total_ehp = _num(metrics.get("TotalEHP"))
        evade = _num(metrics.get("EvadeChance"))
        phys = _num(metrics.get("PhysicalMaximumHitTaken"))
        if total_ehp >= 15_000 or evade >= 50 or phys >= 4_500:
            return True
    if offense_meta.get("evidenceLevel") != "strong":
        return False
    total_ehp = _num(metrics.get("TotalEHP"))
    evade = _num(metrics.get("EvadeChance"))
    phys = _num(metrics.get("PhysicalMaximumHitTaken"))
    if raw_dps <= 0:
        return False
    return total_ehp >= 20_000 and (evade >= 55 or phys >= 4_500)


def _score_mobility(
    metrics: dict[str, Any],
    caveats: list[str],
    breakdown: dict[str, Any],
    source_context: str,
    band: str,
) -> float:
    value, key = _first_number_with_key(
        metrics,
        "EffectiveMovementSpeedMod",
        "MovementSpeedMod",
        "MovementSpeedWhileUsingSkill",
    )
    if value > 0:
        observed_score = target_log_score(
            value,
            quality_floor=MOVEMENT_SPEED_QUALITY_FLOOR,
            target=MOVEMENT_SPEED_TARGET,
        )
        skill_speed = _num(metrics.get("Speed"))
        if observed_score == 0.0 and skill_speed > SPEED_QUALITY_FLOOR:
            observed_score = target_log_score(
                skill_speed,
                quality_floor=SPEED_QUALITY_FLOOR,
                target=SPEED_TARGET,
            )
            caveats.append("skill_speed_mobility_fallback_caveat")
            key = "Speed"
            score_policy = "skill_speed_overlay"
        else:
            score_policy = "movement_speed"
        score = observed_score
        breakdown["mobility"] = {
            "value": round(_clamp(score), 6),
            "observedValue": round(_clamp(observed_score), 6),
            "rawValue": value,
            "qualityFloor": MOVEMENT_SPEED_QUALITY_FLOOR,
            "target": MOVEMENT_SPEED_TARGET,
            "sourceMetric": key,
            "scorePolicy": score_policy,
        }
        return score

    skill_speed = _num(metrics.get("Speed"))
    score = target_log_score(
        skill_speed,
        quality_floor=SPEED_QUALITY_FLOOR,
        target=SPEED_TARGET,
    )
    caveats.append("skill_speed_mobility_fallback_caveat")
    breakdown["mobility"] = {
        "value": round(_clamp(score), 6),
        "rawValue": skill_speed,
        "qualityFloor": SPEED_QUALITY_FLOOR,
        "target": SPEED_TARGET,
        "sourceMetric": "Speed",
        "scorePolicy": "skill_speed_fallback",
    }
    return score


def _scenario_fit(score_vector: dict[str, dict[str, Any]]) -> dict[str, float]:
    offense = _num(score_vector["offense"]["value"])
    defense = _num(score_vector["defense"]["value"])
    recovery = _num(score_vector["recovery"]["value"])
    mobility = _num(score_vector["mobility"]["value"])
    return {
        "mappingFit": round(
            _clamp((offense * 0.35) + (defense * 0.25) + (recovery * 0.10) + (mobility * 0.30)), 6
        ),
        "bossingFit": round(
            _clamp((offense * 0.45) + (defense * 0.35) + (recovery * 0.15) + (mobility * 0.05)), 6
        ),
        "hybridFit": round(
            _clamp((offense * 0.40) + (defense * 0.35) + (recovery * 0.15) + (mobility * 0.10)), 6
        ),
    }


def _quality_band(
    aggregate: float,
    failures: list[str],
    blocked: set[str],
    *,
    delivery_evidence_status: str = "established",
) -> str:
    if blocked:
        return "invalid"
    if any(
        f in failures
        for f in (
            "below_playability_floor",
            "catastrophic_defense_shortboard",
            "uncapped_resistance",
        )
    ):
        return "barely_playable"
    if delivery_evidence_status != "established":
        return "prototype_only"
    if aggregate >= 0.80:
        return "strong"
    if aggregate >= 0.55:
        return "solid"
    if aggregate >= 0.30:
        return "entry_endgame"
    return "barely_playable"


def _ci_status(
    keystones: list[str] | None,
    resistances: dict[str, Any] | None,
) -> tuple[bool, bool]:
    if keystones is not None:
        return "Chaos Inoculation" in {str(k) for k in keystones}, False
    if _num((resistances or {}).get("chaos")) >= 100:
        return True, True
    return False, False


def _has_chaos_inoculation(keystones: list[str] | None, resistances: dict[str, Any] | None) -> bool:
    return _ci_status(keystones, resistances)[0]


def _recovery_diagnostics(
    metrics: dict[str, Any], life_pool_source: str, primary_pool_source: str | None = None
) -> dict[str, float | str]:
    return {
        "Life": _num(metrics.get("Life")),
        "LifeUnreserved": _num(metrics.get("LifeUnreserved")),
        "LifeReserved": _num(metrics.get("LifeReserved")),
        "LifeUnreservedPercent": _num(metrics.get("LifeUnreservedPercent")),
        "EnergyShield": _num(metrics.get("EnergyShield")),
        "Mana": _num(metrics.get("Mana")),
        "ManaUnreserved": _num(metrics.get("ManaUnreserved")),
        "ManaUnreservedPercent": _num(metrics.get("ManaUnreservedPercent")),
        "lifePoolSource": life_pool_source,
        "primaryPoolSource": primary_pool_source or life_pool_source,
    }


def _offense_metric(metrics: dict[str, Any]) -> tuple[float, str, dict[str, Any]]:
    meta: dict[str, Any] = {}
    if _num(metrics.get("JudgeDPS")) > 0:
        value = _num(metrics.get("JudgeDPS"))
        metric_detail = str(metrics.get("JudgeDPSMetric") or "unknown")
        raw_dps = _num(metrics.get("JudgeRawDPS")) or value
        effective_dps = _num(metrics.get("JudgeEffectiveDPS")) or value
        is_minion = bool(metrics.get("JudgeIsMinion")) or metric_detail in {
            "MinionCombinedDPS",
            "MinionTotalDPS",
        }
        meta["sourceMetricDetail"] = metric_detail
        caveats = _string_list(metrics.get("JudgeSkillCaveats"))
        if metric_detail == "FullDPS":
            meta["provenanceDetail"] = "socket_group_full_dps_rollup"
            meta["provenance"] = "isolated_full_dps_rollup"
            meta["evidenceLevel"] = "limited"
            caveats.append("full_dps_rollup_caveat")
        elif is_minion:
            meta["provenance"] = "minion_pob_output"
            meta["evidenceLevel"] = "limited"
            caveats.append("minion_dps_unverified_caveat")
        else:
            meta["provenance"] = "direct_pob_dps"
            meta["evidenceLevel"] = "strong"
            caveats = [value for value in caveats if value != "full_dps_rollup_caveat"]
        if metrics.get("JudgeSkillName"):
            meta["skillName"] = str(metrics.get("JudgeSkillName"))
        if metrics.get("JudgeSkillGroupIndex") is not None:
            meta["skillGroupIndex"] = int(_num(metrics.get("JudgeSkillGroupIndex")))
        if metrics.get("JudgeProjectileCount") is not None:
            meta["projectileCount"] = _num(metrics.get("JudgeProjectileCount"))
        if metrics.get("JudgeActiveSkillCount") is not None:
            meta["activeSkillCount"] = _num(metrics.get("JudgeActiveSkillCount"))
        if metrics.get("JudgeActiveMinionLimit") is not None:
            meta["activeMinionLimit"] = _num(metrics.get("JudgeActiveMinionLimit"))
        meta["isMinion"] = is_minion
        meta["rawDps"] = raw_dps
        meta["effectiveDps"] = effective_dps
        meta["directDps"] = _num(metrics.get("JudgeDirectDPS"))
        meta["fullDps"] = _num(metrics.get("JudgeFullDPS"))
        meta["caveats"] = caveats
        return value, "JudgeDPS", meta
    value, key = _first_number_with_key(
        metrics,
        "FullDPS",
        "CombinedDPS",
        "WithPoisonDPS",
        "WithIgniteDPS",
        "WithBleedDPS",
        "WithImpaleDPS",
        "WithDotDPS",
        "TotalDPS",
        "MinionCombinedDPS",
        "MinionTotalDPS",
    )
    projectile_count = _num(metrics.get("ProjectileCount"))
    caveats: list[str] = []
    if projectile_count > 1 and key != "FullDPS":
        caveats.append("projectile_overlap_unverified_caveat")
        meta["projectileCount"] = projectile_count
    if key in {"MinionCombinedDPS", "MinionTotalDPS"}:
        meta["provenance"] = "minion_pob_output"
        meta["evidenceLevel"] = "limited"
        meta["isMinion"] = True
        caveats.append("minion_dps_unverified_caveat")
    elif key == "FullDPS":
        meta["provenance"] = "isolated_full_dps_rollup"
        meta["evidenceLevel"] = "limited"
        meta["provenanceDetail"] = "socket_group_full_dps_rollup"
        caveats.append("full_dps_rollup_caveat")
    elif value > 0:
        meta["provenance"] = "direct_pob_dps"
        meta["evidenceLevel"] = "strong"
        meta["isMinion"] = False
    else:
        meta["provenance"] = "unknown_or_unavailable"
        meta["evidenceLevel"] = "none"
        meta["isMinion"] = False
    meta["rawDps"] = value
    meta["effectiveDps"] = value
    meta["sourceMetricDetail"] = key
    meta["caveats"] = caveats
    return value, key, meta


def _has_keystone(keystones: list[str] | None, name: str) -> bool:
    return name in {str(k) for k in (keystones or [])}


def _first_number_with_key(values: dict[str, Any], *keys: str) -> tuple[float, str]:
    for key in keys:
        value = _num(values.get(key))
        if value > 0:
            return value, key
    return 0.0, keys[0] if keys else "unknown"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if value:
        return [str(value)]
    return []


def _num(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _maybe_num(value: Any) -> float | None:
    if value is None:
        return None
    return _num(value)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _round_score_vector(vector: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, value in vector.items():
        out[key] = dict(value)
        out[key]["value"] = round(_clamp(_num(value.get("value"))), 6)
    return out
