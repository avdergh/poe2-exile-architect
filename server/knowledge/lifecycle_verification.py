"""Stage verification budgets for lifecycle build research.

These plans tell the assistant what to verify with PoB for each lifecycle stage. They are
not computed results; the engine still owns all DPS/EHP/resistance numbers.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

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
