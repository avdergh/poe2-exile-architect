"""Stage verification budgets for lifecycle build research.

These plans tell the assistant what to verify with PoB for each lifecycle stage. They are
not computed results; the engine still owns all DPS/EHP/resistance numbers.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_ELEMENTAL_RESISTS = ("fire", "cold", "lightning")
_DEFENSE_FLOORS: dict[str, dict[str, float]] = {
    "campaign_early": {"pool": 300, "ehp": 600},
    "campaign_mid": {"pool": 800, "ehp": 1500},
    "campaign_late": {"pool": 1500, "ehp": 4000},
    "maps_entry": {"pool": 2500, "ehp": 8000},
    "endgame_budget": {"pool": 3500, "ehp": 12000},
    "endgame_final": {"pool": 4500, "ehp": 18000},
}

_BUDGETS: dict[str, dict[str, Any]] = {
    "campaign_early": {
        "levelTarget": 18,
        "passivePointBudget": 18,
        "gearAssumption": "vendor/quest rares, no required unique, low socket pressure",
        "engineTools": ["set_level", "set_skill", "get_stats", "evaluate_build"],
        "metricGroups": {
            "offense": ["TotalDPS", "AverageDamage", "Speed"],
            "defense": ["Life", "EnergyShield"],
            "sustain": ["Mana", "ManaCost"],
        },
        "targetChecks": ["main_skill_socketed", "sustain_ok", "pob_model_supported"],
        "failureModes": [
            "skill unavailable",
            "mana cost too high",
            "damage only works with later gear",
        ],
        "caveats": ["Campaign early numbers are coarse; prioritize availability and feel."],
    },
    "campaign_mid": {
        "levelTarget": 38,
        "passivePointBudget": 40,
        "gearAssumption": "campaign rares, first ascendancy or key support may be online",
        "engineTools": [
            "set_level",
            "set_skill",
            "optimize_supports",
            "get_stats",
            "evaluate_build",
        ],
        "metricGroups": {
            "offense": ["TotalDPS", "FullDPS", "Speed"],
            "defense": ["Life", "EnergyShield"],
            "sustain": ["Mana", "ManaCost"],
        },
        "targetChecks": [
            "first_ascendancy_or_key_support",
            "single_target_feels_ok",
            "sustain_ok",
            "pob_model_supported",
        ],
        "failureModes": ["single target falls behind", "support setup breaks sustain"],
        "caveats": ["Do not assume endgame uniques or late clusters exist yet."],
    },
    "campaign_late": {
        "levelTarget": 58,
        "passivePointBudget": 62,
        "gearAssumption": "campaign-capped rares, basic life/ES and resist pressure",
        "engineTools": ["set_level", "get_stats", "get_defenses", "evaluate_build"],
        "metricGroups": {
            "offense": ["TotalDPS", "FullDPS"],
            "defense": [
                "TotalEHP",
                "Life",
                "EnergyShield",
                "FireResist",
                "ColdResist",
                "LightningResist",
            ],
            "sustain": ["Mana", "ManaCost"],
        },
        "targetChecks": ["resists_near_cap", "basic_defense_online", "single_target_feels_ok"],
        "failureModes": [
            "uncapped resists",
            "boss damage too low",
            "defense sacrificed for damage",
        ],
        "caveats": ["Prepare for maps; do not switch to a fragile final-form tree yet."],
    },
    "maps_entry": {
        "levelTarget": 68,
        "passivePointBudget": 76,
        "gearAssumption": "cheap rares or very cheap uniques; elemental resistances capped first",
        "engineTools": ["set_level", "get_stats", "get_defenses", "evaluate_build"],
        "metricGroups": {
            "offense": ["TotalDPS", "FullDPS"],
            "defense": [
                "TotalEHP",
                "Life",
                "EnergyShield",
                "FireResist",
                "ColdResist",
                "LightningResist",
            ],
            "sustain": ["Mana", "ManaCost", "Spirit"],
        },
        "targetChecks": [
            "resists_capped",
            "basic_defense_online",
            "sustain_ok",
            "pob_model_supported",
        ],
        "failureModes": ["resists not capped", "recovery missing", "mana/spirit sustain fails"],
        "caveats": ["Hold this stage until the first endgame transition gate is satisfied."],
    },
    "endgame_budget": {
        "levelTarget": 82,
        "passivePointBudget": 96,
        "gearAssumption": "budget trade gear plus build-defining unique or equivalent rare affix",
        "engineTools": [
            "set_level",
            "optimize_supports",
            "rank_upgrades",
            "get_stats",
            "get_defenses",
            "evaluate_build",
            "benchmark_build",
        ],
        "metricGroups": {
            "offense": ["TotalDPS", "FullDPS", "Speed"],
            "defense": [
                "TotalEHP",
                "Life",
                "EnergyShield",
                "FireResist",
                "ColdResist",
                "LightningResist",
            ],
            "sustain": ["Mana", "ManaCost", "Spirit"],
            "calibration": ["reference_range", "dominant_levers"],
        },
        "targetChecks": [
            "build_defining_component_online",
            "resists_capped",
            "sustain_ok",
            "pob_model_supported",
        ],
        "failureModes": [
            "missing key item",
            "budget gear cannot sustain supports",
            "below reference range",
        ],
        "caveats": ["Verify the mechanism directly; meta popularity is not proof."],
    },
    "endgame_final": {
        "levelTarget": 92,
        "passivePointBudget": 116,
        "gearAssumption": "near-final gear, expensive uniques/jewels allowed if budget says so",
        "engineTools": [
            "set_level",
            "optimize_build",
            "rank_upgrades",
            "get_stats",
            "get_defenses",
            "evaluate_build",
            "pinnacle_readiness",
            "benchmark_build",
        ],
        "metricGroups": {
            "offense": ["TotalDPS", "FullDPS", "Speed"],
            "defense": ["TotalEHP", "Life", "EnergyShield", "ChaosResist"],
            "sustain": ["Mana", "ManaCost", "Spirit"],
            "calibration": ["reference_range", "pinnacle_readiness", "dominant_levers"],
        },
        "targetChecks": [
            "core_threshold_met",
            "upgrade_budget_ready",
            "pinnacle_ready",
            "pob_model_supported",
        ],
        "failureModes": [
            "unmodelled trigger or threshold",
            "over-budget tree",
            "aspirational gear assumptions",
        ],
        "caveats": ["Unmodelled mechanics must be stated instead of converted into fake DPS."],
    },
}


def plan_stage_verification(stage: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the PoB verification budget for a lifecycle stage."""
    budget = _BUDGETS.get(stage)
    if budget is None:
        return {"ok": False, "error": "unknown lifecycle stage", "stage": stage}
    plan = deepcopy(budget)
    plan.update(
        {
            "ok": True,
            "stage": stage,
            "status": "planned",
            "source": "stage-verification-budget",
            "stateSnapshot": state or {},
            "note": (
                "This is a verification plan, not a computed result. Run the listed engine tools "
                "before presenting DPS/EHP/resistance claims."
            ),
        }
    )
    return plan


def known_stages() -> list[str]:
    return list(_BUDGETS.keys())


def verify_stage_metrics(
    stage: str,
    *,
    stats: dict[str, Any] | None = None,
    defenses: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    engine_warning: str | None = None,
    caveats: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate the active build snapshot against a lifecycle stage budget.

    This function is deliberately pure and read-only: `main.verify_lifecycle_stage` gathers PoB
    values, while this helper translates those values into stage-readiness checks. Checks that need
    non-engine evidence stay unknown so the caller cannot accidentally overclaim a stage.
    """
    plan = plan_stage_verification(stage, state=state)
    if not plan.get("ok"):
        return {**plan, "status": "unknown", "pass": False}

    observations = _observations(stats or {}, defenses or {})
    checks = _evaluate_known_checks(stage, plan["targetChecks"], observations, engine_warning)
    failed = [row["check"] for row in checks if row["status"] == "failed"]
    unknown = [row["check"] for row in checks if row["status"] == "unknown"]
    passed = not failed and not unknown

    result_caveats = list(plan.get("caveats") or [])
    if engine_warning:
        result_caveats.append(engine_warning)
    result_caveats.extend(caveats or [])

    return {
        "ok": True,
        "stage": stage,
        "status": "passed" if passed else "failed" if failed else "unknown",
        "pass": passed,
        "plan": plan,
        "stateSnapshot": state or {},
        "observations": observations,
        "checks": checks,
        "failedChecks": failed,
        "unknownChecks": unknown,
        "caveats": result_caveats,
        "evidenceTags": ["engine-computed", "stage-verification"],
    }


def requested_metric_keys(stage: str) -> list[str]:
    """Return a stable list of stat keys needed for a stage verification read."""
    plan = plan_stage_verification(stage)
    if not plan.get("ok"):
        return []
    keys: list[str] = []
    for group in (plan.get("metricGroups") or {}).values():
        for key in group:
            if key not in {"reference_range", "dominant_levers", "pinnacle_readiness"}:
                keys.append(str(key))
    # Add core pool/cost stats used by v1 checks even when a stage budget omits one.
    keys.extend(["TotalEHP", "Life", "EnergyShield", "Mana", "ManaCost"])
    return sorted(set(keys))


def _observations(stats: dict[str, Any], defenses: dict[str, Any]) -> dict[str, Any]:
    resists = _resistances(stats, defenses)
    life = _number(stats.get("Life") or defenses.get("life"))
    es = _number(stats.get("EnergyShield") or defenses.get("energyShield"))
    total_ehp = _number(defenses.get("totalEHP") or stats.get("TotalEHP"))
    mana = _number(stats.get("Mana") or defenses.get("mana"))
    mana_cost = _number(stats.get("ManaCost"))
    spirit = _number(stats.get("Spirit") or defenses.get("spirit"))
    return {
        "resistances": resists,
        "life": life,
        "energyShield": es,
        "totalPool": _sum_known(life, es),
        "totalEHP": total_ehp,
        "mana": mana,
        "manaCost": mana_cost,
        "spirit": spirit,
        "offense": {
            "TotalDPS": _number(stats.get("TotalDPS")),
            "FullDPS": _number(stats.get("FullDPS")),
            "AverageDamage": _number(stats.get("AverageDamage")),
            "Speed": _number(stats.get("Speed")),
        },
    }


def _evaluate_known_checks(
    stage: str,
    target_checks: list[str],
    observations: dict[str, Any],
    engine_warning: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for check in target_checks:
        if check == "resists_capped":
            rows.append(_resist_check(check, observations, minimum=75))
        elif check == "resists_near_cap":
            rows.append(_resist_check(check, observations, minimum=60))
        elif check == "basic_defense_online":
            rows.append(_basic_defense_check(stage, observations))
        elif check == "sustain_ok":
            rows.append(_sustain_check(observations))
        elif check == "pob_model_supported":
            rows.append(
                {
                    "check": check,
                    "status": "failed" if engine_warning else "passed",
                    "ok": not bool(engine_warning),
                    "detail": engine_warning or "no engine warning supplied",
                }
            )
        else:
            rows.append(
                {
                    "check": check,
                    "status": "unknown",
                    "ok": None,
                    "detail": "requires stage-specific evidence not inferred from current engine stats",
                }
            )
    return rows


def _resistances(stats: dict[str, Any], defenses: dict[str, Any]) -> dict[str, float | None]:
    raw = defenses.get("resistances") if isinstance(defenses.get("resistances"), dict) else {}
    return {
        "fire": _first_number(raw.get("fire"), stats.get("FireResist")),
        "cold": _first_number(raw.get("cold"), stats.get("ColdResist")),
        "lightning": _first_number(raw.get("lightning"), stats.get("LightningResist")),
        "chaos": _first_number(raw.get("chaos"), stats.get("ChaosResist")),
    }


def _resist_check(check: str, observations: dict[str, Any], *, minimum: float) -> dict[str, Any]:
    resists = observations.get("resistances") or {}
    values = {name: resists.get(name) for name in _ELEMENTAL_RESISTS}
    if any(value is None for value in values.values()):
        return {
            "check": check,
            "status": "unknown",
            "ok": None,
            "detail": values,
            "target": minimum,
        }
    ok = all(float(value) >= minimum for value in values.values() if value is not None)
    return {
        "check": check,
        "status": "passed" if ok else "failed",
        "ok": ok,
        "detail": values,
        "target": minimum,
    }


def _basic_defense_check(stage: str, observations: dict[str, Any]) -> dict[str, Any]:
    floor = _DEFENSE_FLOORS.get(stage, _DEFENSE_FLOORS["maps_entry"])
    pool_floor = floor.get("pool", _DEFENSE_FLOORS["maps_entry"]["pool"])
    ehp_floor = floor.get("ehp", _DEFENSE_FLOORS["maps_entry"]["ehp"])
    pool = observations.get("totalPool")
    ehp = observations.get("totalEHP")
    if pool is None and ehp is None:
        return {
            "check": "basic_defense_online",
            "status": "unknown",
            "ok": None,
            "detail": {"totalPool": pool, "totalEHP": ehp},
            "target": {"totalPool": pool_floor, "totalEHP": ehp_floor},
        }
    ok = (isinstance(pool, (int, float)) and pool >= pool_floor) or (
        isinstance(ehp, (int, float)) and ehp >= ehp_floor
    )
    return {
        "check": "basic_defense_online",
        "status": "passed" if ok else "failed",
        "ok": ok,
        "detail": {"totalPool": pool, "totalEHP": ehp},
        "target": {"totalPool": pool_floor, "totalEHP": ehp_floor},
    }


def _sustain_check(observations: dict[str, Any]) -> dict[str, Any]:
    mana = observations.get("mana")
    mana_cost = observations.get("manaCost")
    if mana_cost is None:
        return {
            "check": "sustain_ok",
            "status": "unknown",
            "ok": None,
            "detail": {"mana": mana, "manaCost": mana_cost},
            "target": "manaCost must be known for sustain verification",
        }
    if mana_cost == 0:
        return {
            "check": "sustain_ok",
            "status": "passed",
            "ok": True,
            "detail": {"mana": mana, "manaCost": mana_cost},
            "target": "manaCost is zero",
        }
    if mana is None:
        return {
            "check": "sustain_ok",
            "status": "unknown",
            "ok": None,
            "detail": {"mana": mana, "manaCost": mana_cost},
            "target": "mana must be known when manaCost is non-zero",
        }
    ok = mana >= mana_cost * 5
    return {
        "check": "sustain_ok",
        "status": "passed" if ok else "failed",
        "ok": ok,
        "detail": {"mana": mana, "manaCost": mana_cost},
        "target": "available mana at least 5x main skill mana cost",
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _sum_known(*values: float | None) -> float | None:
    known = [value for value in values if isinstance(value, (int, float))]
    return sum(known) if known else None
