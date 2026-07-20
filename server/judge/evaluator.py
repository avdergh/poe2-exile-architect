"""Evaluation orchestration for active PoB builds."""

from __future__ import annotations

import hashlib
from typing import Any

from server.compute import completeness

from . import modelability, models, rules, scoring


def evaluate_active_build(
    engine: Any,
    snapshot_id: str,
    *,
    source_context: str = "generated_candidate",
) -> dict[str, Any]:
    build = engine.get_build()
    try:
        equipped_items = completeness.equipped_item_metadata(engine.get_xml())
    except Exception:  # noqa: BLE001 - item metadata augments, but must not break, Judge readback.
        equipped_items = {}
    if equipped_items:
        build = dict(build)
        build["gear"] = equipped_items
    stats_response = engine.get_stats(keys=models.JUDGE_METRIC_KEYS)
    stats = stats_response.get("stats") if isinstance(stats_response, dict) else {}
    if not isinstance(stats, dict):
        stats = {}
    defenses = engine.get_defenses()
    if isinstance(stats_response, dict):
        defenses = dict(defenses or {})
        warnings = list(defenses.get("warnings") or [])
        for key in ("warning", "engineNote", "dpsNote"):
            if stats_response.get(key):
                warnings.append(str(stats_response[key]))
        if warnings:
            defenses["warnings"] = warnings

    return evaluate_readback(
        build,
        stats,
        defenses,
        snapshot_id=snapshot_id,
        source_context=source_context,
    )


def evaluate_readback(
    build: dict[str, Any],
    metrics: dict[str, Any],
    defenses: dict[str, Any] | None,
    *,
    snapshot_id: str,
    source_hash: str | None = None,
    source_context: str = "generated_candidate",
) -> dict[str, Any]:
    defenses = defenses or {}
    metrics = _metrics_with_judge_selection(metrics, build)
    hard_failures: list[str] = []
    caveats: list[str] = []
    band = scoring.level_band(int(_num(build.get("level")) or 0))

    class_check = rules.check_class_ascendancy(
        build.get("class"),
        build.get("ascendancy"),
        level_band=band,
    )
    if not class_check.get("ok"):
        hard_failures.append(str(class_check["failureCode"]))
    if class_check.get("caveat"):
        caveats.append(str(class_check["caveat"]))

    evaluation_skill_group = _evaluation_skill_group(build)
    socket_failures, socket_caveats = rules.check_main_skill_group(
        evaluation_skill_group,
        strict_active_skill_count=(source_context != "trusted_reference"),
    )
    hard_failures.extend(socket_failures)
    caveats.extend(socket_caveats)
    caveats.extend(
        rules.support_completeness_caveats(
            evaluation_skill_group,
            level=int(_num(build.get("level")) or 0),
            source_context=source_context,
        )
    )
    supplemental_components = _supplemental_damage_components(build)
    if supplemental_components:
        caveats.append("conditional_supplemental_damage_caveat")
    weapon_check = rules.check_weapon_skill_compatibility(_evaluation_weapon_check(build))
    if not weapon_check.get("ok"):
        hard_failures.append(str(weapon_check["failureCode"]))

    passive_budget = _check_passive_budget(build, source_context=source_context)
    if passive_budget.get("failure"):
        hard_failures.append("passive_budget_exceeded")
    if passive_budget.get("caveat"):
        caveats.append(str(passive_budget["caveat"]))
    weapon_set_budget = _check_weapon_set_budget(build, source_context=source_context)
    if weapon_set_budget.get("failure"):
        hard_failures.append("weapon_set_budget_exceeded")
    if weapon_set_budget.get("caveat"):
        caveats.append(str(weapon_set_budget["caveat"]))
    if _uses_dual_weapon_state(build):
        caveats.append("dual_weapon_state_limited_caveat")
    attribute_shortfall = _has_attribute_shortfall(build)
    if attribute_shortfall:
        hard_failures.append("attribute_requirement_unmet")
    item_requirements = rules.check_equipped_item_requirements(build)
    if not item_requirements.get("ok"):
        hard_failures.append("equipped_item_level_requirement_unmet")
    active_gem_requirements = rules.check_active_skill_gem_requirements(build)
    if not active_gem_requirements.get("ok"):
        hard_failures.append("active_skill_gem_level_requirement_unmet")
    item_affixes = rules.check_equipped_item_affixes(build)
    if not item_affixes.get("ok"):
        hard_failures.append("illegal_equipped_item_affixes")
    if (
        build.get("spiritUsed") is not None
        and build.get("spiritAvailable") is not None
        and _num(build.get("spiritUsed")) > _num(build.get("spiritAvailable"))
    ):
        hard_failures.append("spirit_budget_exceeded")

    if source_context == "trusted_reference":
        if "passive_budget_exceeded" in hard_failures:
            hard_failures = [f for f in hard_failures if f != "passive_budget_exceeded"]
            caveats.append("external_passive_budget_anomaly_caveat")
        if "weapon_set_budget_exceeded" in hard_failures:
            hard_failures = [f for f in hard_failures if f != "weapon_set_budget_exceeded"]
            caveats.append("external_weapon_set_budget_anomaly_caveat")
        if "attribute_requirement_unmet" in hard_failures:
            hard_failures = [f for f in hard_failures if f != "attribute_requirement_unmet"]
            caveats.append("trusted_reference_attribute_requirement_mismatch_caveat")

    warning_text = " ".join(_collect_warnings(build, defenses))
    active_weapon_check = _evaluation_weapon_check(build)
    if (
        (
            not isinstance(active_weapon_check, dict)
            or active_weapon_check.get("compatible") is not True
        )
        and "Attack" in warning_text
        and "no weapon" in warning_text
    ):
        hard_failures.append("attack_skill_without_weapon")

    engine_warnings = _collect_warnings(build, defenses)
    modelability_result = modelability.evaluate_modelability(
        _build_with_evaluation_skill_group(build, evaluation_skill_group),
        warnings=engine_warnings,
    )
    hard_failures.extend(modelability_result.get("failureCodes") or [])
    caveats.extend(modelability_result.get("caveats") or [])

    physical_invalid = rules.physical_invalid_failures(hard_failures)
    blocked_dimensions = rules.blocked_score_dimensions(physical_invalid)
    if modelability_result.get("coreBlocked"):
        blocked_dimensions.add("offense")
    score = scoring.score_metrics(
        metrics,
        level=int(_num(build.get("level")) or 0),
        resistances=defenses.get("resistances") or {},
        blocked_dimensions=blocked_dimensions,
        keystones=build.get("keystones"),
        source_context=source_context,
    )
    playability_failures = list(score.get("playabilityFailures") or score.get("failures") or [])
    quality_warnings = list(score.get("qualityWarnings") or [])
    caveats.extend(score["caveats"])
    physical_invalid = rules.physical_invalid_failures(hard_failures)

    tree_version = build.get("treeVersion")
    latest_tree_version = build.get("latestTreeVersion")
    if tree_version and latest_tree_version and tree_version != latest_tree_version:
        caveats.append("version_mismatch_caveat")

    passed = not hard_failures
    reward_eligible: bool | str = bool(
        passed
        and not physical_invalid
        and not playability_failures
        and not modelability_result.get("coreBlocked")
    )
    reward_limit_reasons: list[str] = []
    if _has_limited_reward_caveat(caveats) and reward_eligible:
        reward_eligible = "limited"
        reward_limit_reasons.append("limited_evidence")
    if modelability_result.get("status") == "partial" and reward_eligible:
        reward_eligible = "limited"
        reward_limit_reasons.append("partial_modelability")
    offense_evidence = (score.get("scoreBreakdown") or {}).get("offense") or {}
    if offense_evidence.get("deliveryEvidenceStatus") != "established" and reward_eligible:
        reward_eligible = "limited"
        reward_limit_reasons.append("offense_delivery_evidence")
    reward_strength = _reward_strength(reward_eligible)
    score_review_needed, score_review_reasons = _score_review_state(
        passed=passed,
        aggregate_score=score["aggregateScore"],
        score_vector=score["scoreVector"],
    )

    summary = {
        "class": build.get("class"),
        "ascendancy": build.get("ascendancy"),
        "mainSkill": build.get("mainSkill"),
        "level": build.get("level"),
    }
    selected = build.get("judgeSelectedSkill") or {}
    if selected.get("skillName") and selected.get("skillName") != build.get("mainSkill"):
        summary["judgeSelectedSkill"] = selected.get("skillName")
    score_applicable = not bool(modelability_result.get("coreBlocked"))
    result = {
        "snapshotId": snapshot_id,
        "sourceHash": source_hash,
        "summary": summary,
        "pass": bool(passed),
        "rewardEligible": reward_eligible,
        "rewardStrength": reward_strength,
        "rewardLimitReasons": _dedupe(reward_limit_reasons),
        "scoreReviewNeeded": score_review_needed,
        "hardFailures": _dedupe(hard_failures),
        "physicalInvalidFailures": physical_invalid,
        "playabilityFailures": _dedupe(playability_failures),
        "qualityWarnings": _dedupe(quality_warnings),
        "scoreApplicability": {
            "status": "applicable" if score_applicable else "unavailable",
            "reason": None if score_applicable else "core_mechanic_not_modelable",
        },
        "caveats": _dedupe(caveats),
        "modelability": modelability_result,
        "defenseModel": _defense_model(build, metrics, defenses, score),
        "legality": {
            "passiveBudget": passive_budget,
            "weaponSetBudget": weapon_set_budget,
            "itemRequirements": item_requirements,
            "activeSkillGemRequirements": active_gem_requirements,
            "itemAffixes": item_affixes,
        },
        "supplementalDamageComponents": supplemental_components,
        "scoreVector": score["scoreVector"],
        "scoreBreakdown": score.get("scoreBreakdown"),
        "scoreScale": score.get("scoreScale"),
        "scenarioFit": score.get("scenarioFit"),
        "qualityBand": score.get("qualityBand") if score_applicable else "unmodelled",
        "aggregateScore": score["aggregateScore"],
        "levelBand": score["levelBand"],
        "metricProvenance": score["metricProvenance"],
        "reproducibility": {
            "evaluatorVersion": models.EVALUATOR_VERSION,
            "treeVersion": tree_version,
            "latestTreeVersion": latest_tree_version,
        },
    }
    if score_review_reasons:
        result["scoreReviewReasons"] = score_review_reasons
    if source_hash:
        result["sourceHash"] = source_hash
    return result


def compute_source_hash(source: str) -> str:
    return hashlib.sha256((source or "").encode("utf-8")).hexdigest()[:16]


def _has_limited_reward_caveat(caveats: list[str]) -> bool:
    return bool(set(caveats) & models.LIMITED_REWARD_CAVEATS)


def _metrics_with_judge_selection(metrics: dict[str, Any], build: dict[str, Any]) -> dict[str, Any]:
    out = dict(metrics)
    out["ManaFlaskEquipped"] = _mana_flask_equipped(build.get("gear"))
    selected = build.get("judgeSelectedSkill") or {}
    selected_dps = _num(selected.get("effectiveDps")) or _num(selected.get("dps"))
    if not isinstance(selected, dict) or selected_dps <= 0:
        return out
    out["JudgeDPS"] = selected_dps
    out["JudgeRawDPS"] = _num(selected.get("rawDps")) or _num(selected.get("dps")) or selected_dps
    out["JudgeEffectiveDPS"] = selected_dps
    out["JudgeDirectDPS"] = _num(selected.get("directDps"))
    out["JudgeFullDPS"] = _num(selected.get("fullDps"))
    out["JudgeDPSMetric"] = selected.get("sourceMetric") or "unknown"
    out["JudgeSkillName"] = selected.get("skillName") or build.get("mainSkill")
    out["JudgeMainSkill"] = build.get("mainSkill")
    out["JudgeSkillGroupIndex"] = selected.get("groupIndex")
    out["JudgeProjectileCount"] = selected.get("projectileCount")
    out["JudgeIsMinion"] = bool(selected.get("isMinion"))
    out["JudgeActiveSkillCount"] = selected.get("activeSkillCount")
    out["JudgeActiveMinionLimit"] = selected.get("activeMinionLimit")
    out["JudgeSkillCaveats"] = list(selected.get("caveats") or [])
    return out


def _mana_flask_equipped(gear: Any) -> bool:
    if not isinstance(gear, dict):
        return False
    for slot, item in gear.items():
        if not str(slot).casefold().startswith("flask") or not isinstance(item, dict):
            continue
        text = f"{item.get('name') or ''} {item.get('base') or ''}".casefold()
        if "mana flask" in text:
            return True
    return False


def _reward_strength(reward_eligible: bool | str) -> str:
    if reward_eligible is True:
        return "strong"
    if reward_eligible == "limited":
        return "limited"
    return "none"


def _score_review_state(
    *,
    passed: bool,
    aggregate_score: dict[str, Any],
    score_vector: dict[str, dict[str, Any]],
) -> tuple[bool, list[str]]:
    if not passed:
        return False, []

    reasons: list[str] = []
    aggregate = float(aggregate_score.get("value") or 0.0)
    if aggregate < 0.5:
        reasons.append("aggregate_below_0_5")
    for key in ("offense", "defense", "recovery", "mobility"):
        value = float((score_vector.get(key) or {}).get("value") or 0.0)
        if value < 0.5:
            reasons.append(f"{key}_below_0_5")
    return bool(reasons), reasons


def _defense_model(
    build: dict[str, Any],
    metrics: dict[str, Any],
    defenses: dict[str, Any],
    score: dict[str, Any],
) -> dict[str, Any]:
    keystones = {str(k) for k in (build.get("keystones") or [])}
    life = _first_available_metric(metrics, "LifeUnreserved", "Life")
    life_total = _num(metrics.get("Life"))
    life_unreserved_percent = metrics.get("LifeUnreservedPercent")
    es = _num(metrics.get("EnergyShield"))
    mana = _first_available_metric(metrics, "ManaUnreserved", "Mana")
    ward = _num(metrics.get("Ward"))
    total_ehp = _num(metrics.get("TotalEHP"))

    has_ci = "Chaos Inoculation" in keystones
    has_eb = "Eldritch Battery" in keystones
    has_mom = "Mind Over Matter" in keystones
    pool_model = "unknown"
    confidence = "limited"
    caveats: list[str] = []

    if has_eb and has_mom and mana > max(life, es):
        pool_model = "eb_mom_mana"
        confidence = "partial"
        caveats.append("mom_mana_primary_pool_caveat")
    elif has_mom and mana > max(life, es):
        pool_model = "mom"
        confidence = "partial"
        caveats.append("mom_mana_primary_pool_caveat")
    elif has_ci:
        pool_model = "ci"
        confidence = "partial" if has_eb or has_mom else "full"
    elif es > life and es > 0:
        if _is_low_life(life_unreserved_percent, life, life_total):
            pool_model = "low_life"
            confidence = "partial"
        else:
            pool_model = "es"
            confidence = "full"
    elif ward > max(life, es):
        pool_model = "ward"
        confidence = "partial"
    elif life > 0 and es > 0:
        pool_model = "hybrid"
        confidence = "full"
    elif life > 0:
        pool_model = "life"
        confidence = "full"

    if "metric_unavailable_caveat" in (score.get("caveats") or []):
        confidence = "limited"
    recovery = (score.get("scoreBreakdown") or {}).get("recovery") or {}
    return {
        "poolModel": pool_model,
        "hitMitigationModel": {
            "physicalMaxHit": _num(metrics.get("PhysicalMaximumHitTaken")),
            "fireMaxHit": _num(metrics.get("FireMaximumHitTaken")),
            "coldMaxHit": _num(metrics.get("ColdMaximumHitTaken")),
            "lightningMaxHit": _num(metrics.get("LightningMaximumHitTaken")),
            "chaosMaxHit": _num(metrics.get("ChaosMaximumHitTaken")),
            "totalEHP": total_ehp,
            "armour": _num(metrics.get("Armour")),
            "ward": ward,
        },
        "avoidanceModel": {
            "evasion": _num(metrics.get("Evasion")),
            "evadeChance": _num(metrics.get("EvadeChance")),
            "meleeEvadeChance": _num(metrics.get("MeleeEvadeChance")),
            "projectileEvadeChance": _num(metrics.get("ProjectileEvadeChance")),
            "spellEvadeChance": _num(metrics.get("SpellEvadeChance")),
            "spellProjectileEvadeChance": _num(metrics.get("SpellProjectileEvadeChance")),
            "avoidAllDamageFromHitsChance": _num(metrics.get("AvoidAllDamageFromHitsChance")),
            "avoidPhysicalDamageChance": _num(metrics.get("AvoidPhysicalDamageChance")),
            "avoidProjectilesChance": _num(metrics.get("AvoidProjectilesChance")),
            "effectiveBlockChance": _num(metrics.get("EffectiveBlockChance")),
            "effectiveSpellBlockChance": _num(metrics.get("EffectiveSpellBlockChance")),
            "effectiveAverageBlockChance": _num(metrics.get("EffectiveAverageBlockChance")),
            "effectiveSpellSuppressionChance": _num(metrics.get("EffectiveSpellSuppressionChance")),
            "diagnosticOnly": True,
        },
        "sustainModel": {
            "primaryPool": _num(recovery.get("primaryPool")),
            "primaryPoolSource": (recovery.get("diagnostics") or {}).get("primaryPoolSource"),
            "rawRecovery": _num(recovery.get("rawValue")),
            "lifeRecoup": _num(metrics.get("LifeRecoup")),
            "energyShieldRecoup": _num(metrics.get("EnergyShieldRecoup")),
            "manaRecoup": _num(metrics.get("ManaRecoup")),
            "netLifeRegen": _num(metrics.get("NetLifeRegen")),
            "netEnergyShieldRegen": _num(metrics.get("NetEnergyShieldRegen")),
        },
        "confidence": confidence,
        "caveats": _dedupe(caveats),
    }


def _first_available_metric(metrics: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if metrics.get(key) is not None:
            return _num(metrics.get(key))
    return 0.0


def _is_low_life(percent: Any, life: float, life_total: float) -> bool:
    if percent is not None:
        return _num(percent) <= 50
    return life_total > 0 and life <= life_total * 0.5


def _evaluation_skill_group(build: dict[str, Any]) -> list[dict[str, Any]] | None:
    selected = build.get("judgeSelectedSkill") or {}
    selected_group = build.get("judgeSelectedSkillGroup")
    if (
        isinstance(selected, dict)
        and _has_judge_selected_skill(selected)
        and selected.get("socketLegalityApplicable") is not False
        and isinstance(selected_group, list)
    ):
        return selected_group
    return build.get("mainSkillGroup")


def _supplemental_damage_components(build: dict[str, Any]) -> list[dict[str, Any]]:
    components = build.get("judgeSupplementalSkills") or []
    if not isinstance(components, list):
        return []
    output: list[dict[str, Any]] = []
    for component in components:
        if not isinstance(component, dict):
            continue
        name = str(component.get("skillName") or "").strip()
        if not name:
            continue
        output.append(
            {
                "skillName": name,
                "groupIndex": component.get("groupIndex"),
                "groupOrigin": str(component.get("groupOrigin") or "unknown"),
                "scenarioLimitations": [
                    str(value) for value in component.get("scenarioLimitations") or [] if value
                ],
            }
        )
    return output


def _evaluation_weapon_check(build: dict[str, Any]) -> dict[str, Any] | None:
    selected = build.get("judgeSelectedSkill") or {}
    if isinstance(selected, dict) and _has_judge_selected_skill(selected):
        check = selected.get("weaponCheck")
        if isinstance(check, dict):
            return check
    check = build.get("mainSkillWeaponCheck") or build.get("weaponCheck")
    return check if isinstance(check, dict) else None


def _has_judge_selected_skill(selected: dict[str, Any]) -> bool:
    if _num(selected.get("dps")) > 0:
        return True
    if selected.get("weaponCheck"):
        return True
    tags = {str(tag) for tag in selected.get("tags") or []}
    return bool(tags & {"Attack", "Spell", "Damage", "DamageOverTime", "Minion"})


def _build_with_evaluation_skill_group(
    build: dict[str, Any],
    skill_group: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    out = dict(build)
    out["mainSkillGroup"] = skill_group
    return out


def _collect_warnings(build: dict[str, Any], defenses: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for container in (build, defenses):
        for key in ("warning", "warnings", "dpsNote", "note"):
            value = container.get(key)
            if isinstance(value, list):
                out.extend(str(v) for v in value)
            elif value:
                out.append(str(value))
    return out


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _has_attribute_shortfall(build: dict[str, Any]) -> bool:
    attrs = build.get("attributes") or build.get("attributeTotals") or {}
    reqs = build.get("attributeRequirements") or {}
    if not isinstance(attrs, dict) or not isinstance(reqs, dict):
        return False
    aliases = {
        "strength": ("strength", "str", "Str"),
        "dexterity": ("dexterity", "dex", "Dex"),
        "intelligence": ("intelligence", "int", "Int"),
    }
    for attr, keys in aliases.items():
        req = _first_present_number(reqs, keys)
        if req <= 0:
            continue
        have = _first_present_number(attrs, keys)
        if have < req:
            return True
    return False


def _normal_passive_points_used(build: dict[str, Any]) -> float:
    if build.get("normalPassivePointsUsed") is not None:
        return _num(build.get("normalPassivePointsUsed"))
    used = _num(build.get("pointsUsed"))
    weapon_1 = _num(build.get("weaponSet1PointsUsed"))
    weapon_2 = _num(build.get("weaponSet2PointsUsed"))
    if weapon_1 or weapon_2:
        return used - min(weapon_1, weapon_2)
    return used


def _check_passive_budget(
    build: dict[str, Any],
    *,
    source_context: str = "generated_candidate",
) -> dict[str, Any]:
    used = _normal_passive_points_used(build)
    available = _num(build.get("pointsAvailable"))
    base = {"used": used, "available": available, "over": max(0.0, used - available)}
    if used <= available:
        return {"ok": True, **base}
    over = used - available
    if _allows_current_league_extra_passive_point(build, over):
        return {
            "ok": True,
            **base,
            "over": over,
            "leagueExtraApplied": 1,
            "caveat": "league_extra_passive_point_caveat",
        }
    if _allows_imported_tree_budget_mismatch(build, over, source_context):
        return {
            "ok": True,
            **base,
            "over": over,
            "importedMismatchAllowed": int(over),
            "caveat": "imported_tree_budget_mismatch_caveat",
        }
    return {"ok": False, **base, "failure": "passive_budget_exceeded"}


def _allows_current_league_extra_passive_point(build: dict[str, Any], over: float) -> bool:
    if abs(over - 1.0) > 1e-9:
        return False
    if int(_num(build.get("level"))) < 91:
        return False
    tree_version = str(build.get("treeVersion") or "")
    latest_tree_version = str(build.get("latestTreeVersion") or "")
    if tree_version != "0_5":
        return False
    if latest_tree_version and tree_version != latest_tree_version:
        return False
    return True


def _allows_imported_tree_budget_mismatch(
    build: dict[str, Any],
    over: float,
    source_context: str,
) -> bool:
    if source_context != "trusted_reference":
        return False
    if int(_num(build.get("level"))) < 100:
        return False
    if abs(over - round(over)) > 1e-9 or over <= 0 or over > 2:
        return False
    tree_version = build.get("treeVersion")
    latest_tree_version = build.get("latestTreeVersion")
    if tree_version and latest_tree_version and tree_version != latest_tree_version:
        return False
    return True


def _check_weapon_set_budget(
    build: dict[str, Any],
    *,
    source_context: str = "generated_candidate",
) -> dict[str, Any]:
    available = build.get("weaponSetPointsAvailable")
    if available is None:
        return {"ok": True, "available": None}
    cap = _num(available)
    set1 = _num(build.get("weaponSet1PointsUsed"))
    set2 = _num(build.get("weaponSet2PointsUsed"))
    over_max = max(0.0, set1 - cap, set2 - cap)
    base = {
        "available": cap,
        "weaponSet1Used": set1,
        "weaponSet2Used": set2,
        "overMax": over_max,
    }
    if over_max > 0 and _allows_imported_weapon_set_budget_mismatch(
        build, over_max, source_context
    ):
        return {
            "ok": True,
            **base,
            "importedMismatchAllowed": int(round(over_max)),
            "caveat": "imported_weapon_set_budget_mismatch_caveat",
        }
    return {
        "ok": over_max <= 0,
        **base,
        **({"failure": "weapon_set_budget_exceeded"} if over_max > 0 else {}),
    }


def _allows_imported_weapon_set_budget_mismatch(
    build: dict[str, Any],
    over: float,
    source_context: str,
) -> bool:
    if source_context != "trusted_reference":
        return False
    if int(_num(build.get("level"))) < 100:
        return False
    if abs(over - round(over)) > 1e-9 or over <= 0 or over > 2:
        return False
    tree_version = build.get("treeVersion")
    latest_tree_version = build.get("latestTreeVersion")
    return not (tree_version and latest_tree_version and tree_version != latest_tree_version)


def _uses_dual_weapon_state(build: dict[str, Any]) -> bool:
    return (
        _num(build.get("weaponSet1PointsUsed")) > 0 or _num(build.get("weaponSet2PointsUsed")) > 0
    )


def _first_present_number(values: dict[str, Any], keys: tuple[str, ...]) -> float:
    for key in keys:
        if key in values:
            return _num(values.get(key))
    return 0.0


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
