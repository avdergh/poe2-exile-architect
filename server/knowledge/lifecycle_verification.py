"""Stage verification budgets for lifecycle build research.

These plans tell the assistant what to verify with PoB for each lifecycle stage. They are
not computed results; the engine still owns all DPS/EHP/resistance numbers.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from server.compute import sustain
from server.knowledge import copy_safety, research_contracts

_ELEMENTAL_RESISTS = ("fire", "cold", "lightning")
_ELEMENTAL_RESISTANCE_BANDS: tuple[tuple[int, int, float], ...] = (
    (45, 64, 30.0),
    (65, 79, 50.0),
    (80, 89, 60.0),
)
_DEFENSE_FLOORS: dict[str, dict[str, float]] = {
    "campaign_early": {"pool": 300, "ehp": 600},
    "campaign_mid": {"pool": 800, "ehp": 1500},
    "campaign_late": {"pool": 1500, "ehp": 4000},
    "maps_entry": {"pool": 2500, "ehp": 8000},
    "endgame_budget": {"pool": 3500, "ehp": 12000},
    "endgame_final": {"pool": 4500, "ehp": 18000},
}
_SAFE_EVIDENCE_REF = re.compile(research_contracts.SAFE_BOUNDED_REFERENCE_PATTERN)


class LifecycleStageVerificationState(BaseModel):
    """Typed external evidence accepted by the lifecycle verification MCP boundary."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    level: int | None = Field(default=None, ge=1, le=100)
    mana_flask_equipped: bool | None = Field(
        default=None,
        alias="manaFlaskEquipped",
        description=(
            "Legacy compatibility hint. The public verifier replaces it with flask presence "
            "derived from the evaluated build, so callers cannot authorize sustain."
        ),
    )
    single_target_skill_name: str | None = Field(
        default=None,
        alias="singleTargetSkillName",
        min_length=1,
        max_length=160,
        description=(
            "Exact enabled active-skill name expected in the current PoB XML for the stage's "
            "single-target duty."
        ),
    )
    single_target_evidence_refs: list[str] = Field(
        default_factory=list,
        alias="singleTargetEvidenceRefs",
        max_length=8,
        description=(
            "Safe graph/mechanic/Research refs supporting the named skill's single-target duty."
        ),
    )
    build_defining_component_kind: Literal["skill", "ascendancy", "item"] | None = Field(
        default=None,
        alias="buildDefiningComponentKind",
    )
    build_defining_component_name: str | None = Field(
        default=None,
        alias="buildDefiningComponentName",
        min_length=1,
        max_length=160,
    )
    build_defining_component_key: str | None = Field(
        default=None,
        alias="buildDefiningComponentKey",
        min_length=3,
        max_length=240,
    )
    build_defining_evidence_refs: list[str] = Field(
        default_factory=list,
        alias="buildDefiningEvidenceRefs",
        max_length=8,
    )

    @field_validator("single_target_evidence_refs", "build_defining_evidence_refs")
    @classmethod
    def _safe_refs(cls, value: list[str]) -> list[str]:
        if (
            len(value) != len(set(value))
            or any(not _SAFE_EVIDENCE_REF.fullmatch(item) for item in value)
            or copy_safety.contains_raw_url(value)
        ):
            raise ValueError("lifecycle evidence refs must be unique safe refs")
        return value

    @field_validator("build_defining_component_key")
    @classmethod
    def _safe_component_key(cls, value: str | None) -> str | None:
        if value is not None and (
            not _SAFE_EVIDENCE_REF.fullmatch(value) or copy_safety.contains_raw_url(value)
        ):
            raise ValueError("build-defining component key must be a safe stable key")
        return value

    @model_validator(mode="after")
    def _complete_build_defining_component(self) -> "LifecycleStageVerificationState":
        single_target_values = (
            self.single_target_skill_name is not None,
            bool(self.single_target_evidence_refs),
        )
        if any(single_target_values) and not all(single_target_values):
            raise ValueError(
                "single-target evidence requires both an exact skill name and evidence refs"
            )
        component_values = (
            self.build_defining_component_kind is not None,
            self.build_defining_component_name is not None,
            self.build_defining_component_key is not None,
            bool(self.build_defining_evidence_refs),
        )
        if any(component_values) and not all(component_values):
            raise ValueError(
                "build-defining component evidence requires kind, name, key and evidence refs"
            )
        if self.build_defining_component_kind and self.build_defining_component_key:
            allowed_prefixes = {
                "skill": ("skill:",),
                "ascendancy": ("ascendancy:",),
                "item": ("unique:", "item_base:", "item:"),
            }[self.build_defining_component_kind]
            if not self.build_defining_component_key.startswith(allowed_prefixes):
                raise ValueError(
                    "build-defining component key type must match the declared component kind"
                )
        return self


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
        "requiredChecks": ["main_skill_socketed", "sustain_ok"],
        "advisoryChecks": ["pob_model_supported"],
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
        "requiredChecks": [
            "first_ascendancy_or_key_support",
            "single_target_feels_ok",
            "sustain_ok",
        ],
        "advisoryChecks": ["pob_model_supported"],
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
        "requiredChecks": ["resists_near_cap", "basic_defense_online", "single_target_feels_ok"],
        "advisoryChecks": ["pob_model_supported"],
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
        "requiredChecks": [
            "resists_capped",
            "basic_defense_online",
            "sustain_ok",
        ],
        "advisoryChecks": ["pob_model_supported"],
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
        "requiredChecks": [
            "build_defining_component_online",
            "resists_capped",
            "sustain_ok",
        ],
        "advisoryChecks": ["pob_model_supported"],
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
        "requiredChecks": [
            "main_skill_socketed",
            "basic_defense_online",
            "sustain_ok",
        ],
        "advisoryChecks": [
            "pob_model_supported",
            "core_threshold_met",
            "upgrade_budget_ready",
            "pinnacle_ready",
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
    required_checks = list(plan.get("requiredChecks") or plan.get("targetChecks") or [])
    advisory_checks = list(plan.get("advisoryChecks") or [])
    plan["requiredChecks"] = required_checks
    plan["advisoryChecks"] = advisory_checks
    # Compatibility view for existing clients that display the whole verification plan.
    plan["targetChecks"] = required_checks + advisory_checks
    planned_level = _lifecycle_level((state or {}).get("level"), fallback=plan["levelTarget"])
    resistance_minimum = lifecycle_elemental_resistance_minimum(planned_level)
    plan.update(
        {
            "ok": True,
            "stage": stage,
            "status": "planned",
            "source": "stage-verification-budget",
            "stateSnapshot": state or {},
            "elementalResistanceMinimum": resistance_minimum,
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
    unmodelled_mana_mechanisms: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate the active build snapshot against a lifecycle stage budget.

    This function is deliberately pure and read-only: `main.verify_lifecycle_stage` gathers PoB
    values, while this helper translates those values into stage-readiness checks. Checks that need
    non-engine evidence stay unknown so the caller cannot accidentally overclaim a stage.

    ``unmodelled_mana_mechanisms`` must come from the evaluated build itself (see
    ``preflight.inspect_resource_model_gap``). Their presence prevents an engine blind spot from
    becoming a lifecycle blocker, while the result still requires non-PoB verification before a
    numeric sustain claim is made.
    """
    plan = plan_stage_verification(stage, state=state)
    if not plan.get("ok"):
        return {**plan, "status": "unknown", "pass": False}

    observations = _observations(
        stats or {},
        defenses or {},
        state=state or {},
        fallback_level=plan["levelTarget"],
        unmodelled_mana_mechanisms=unmodelled_mana_mechanisms,
    )
    required_names = list(plan.get("requiredChecks") or plan.get("targetChecks") or [])
    advisory_names = list(plan.get("advisoryChecks") or [])
    required_checks = _evaluate_known_checks(stage, required_names, observations, engine_warning)
    advisory_checks = _evaluate_known_checks(stage, advisory_names, observations, engine_warning)
    checks = required_checks + advisory_checks
    failed = [row["check"] for row in required_checks if row["status"] == "failed"]
    unknown = [row["check"] for row in required_checks if row["status"] == "unknown"]
    advisory_failed = [row["check"] for row in advisory_checks if row["status"] == "failed"]
    advisory_unknown = [row["check"] for row in advisory_checks if row["status"] == "unknown"]
    passed = not failed and not unknown
    verification_required = any(
        bool(row.get("verificationRequired")) for row in required_checks
    )

    result_caveats = list(plan.get("caveats") or [])
    if engine_warning:
        result_caveats.append(engine_warning)
    result_caveats.extend(caveats or [])
    mana_sustain = observations.get("manaSustain") or {}
    if mana_sustain.get("classification") == "model_gap_flask_assisted":
        gap_names = ", ".join(mana_sustain.get("unmodelledManaMechanisms") or [])
        result_caveats.append(
            "unmodelled_mana_recovery_requires_verification: "
            + (gap_names or "detected recovery mechanism")
        )

    return {
        "ok": True,
        "stage": stage,
        "status": "passed" if passed else "failed" if failed else "unknown",
        "pass": passed,
        "verificationRequired": verification_required,
        "plan": plan,
        "stateSnapshot": state or {},
        "observations": observations,
        "checks": checks,
        "requiredChecks": required_checks,
        "advisoryChecks": advisory_checks,
        "failedChecks": failed,
        "unknownChecks": unknown,
        "advisoryFailedChecks": advisory_failed,
        "advisoryUnknownChecks": advisory_unknown,
        "recommendedActions": _recommended_actions(stage, checks, failed, unknown),
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
    # Sustain needs rate evidence; pool size alone cannot establish whether a skill is sustainable.
    keys.extend(
        [
            "TotalEHP",
            "Life",
            "LifeUnreserved",
            "LifeUnreservedPercent",
            "EnergyShield",
            "Mana",
            "ManaUnreserved",
            "ManaUnreservedPercent",
            "ManaCost",
            "ManaPercentCost",
            "ManaPerSecondCost",
            "ManaPercentPerSecondCost",
            "LifeCost",
            "LifePercentCost",
            "LifePerSecondCost",
            "LifePercentPerSecondCost",
            "ManaRegenRecovery",
            "ManaLeechGainRate",
            "ManaOnHitRate",
            "NetManaRegen",
            "LifeRegenRecovery",
            "LifeLeechGainRate",
            "LifeOnHitRate",
            "NetLifeRegen",
            "Speed",
        ]
    )
    return sorted(set(keys))


def _observations(
    stats: dict[str, Any],
    defenses: dict[str, Any],
    *,
    state: dict[str, Any],
    fallback_level: int | None = None,
    unmodelled_mana_mechanisms: list[str] | None = None,
) -> dict[str, Any]:
    resists = _resistances(stats, defenses)
    life = _number(stats.get("Life") or defenses.get("life"))
    es = _number(stats.get("EnergyShield") or defenses.get("energyShield"))
    total_ehp = _number(defenses.get("totalEHP") or stats.get("TotalEHP"))
    mana = _number(stats.get("Mana") or defenses.get("mana"))
    mana_unreserved = _number(stats.get("ManaUnreserved"))
    mana_cost = _number(stats.get("ManaCost"))
    net_mana_regen = _number(stats.get("NetManaRegen"))
    mana_regen_recovery = _number(stats.get("ManaRegenRecovery"))
    mana_leech_gain_rate = _number(stats.get("ManaLeechGainRate"))
    mana_on_hit_rate = _number(stats.get("ManaOnHitRate"))
    speed = _number(stats.get("Speed"))
    spirit = _number(stats.get("Spirit") or defenses.get("spirit"))
    resource_sustain = sustain.classify_resource_sustain(
        stats,
        mana_flask_equipped=_optional_bool(state.get("manaFlaskEquipped")),
        unmodelled_mana_mechanisms=unmodelled_mana_mechanisms,
    )
    mana_sustain = dict(resource_sustain["manaSustain"])
    life_sustain = dict(resource_sustain["lifeSustain"])
    return {
        "level": _lifecycle_level(state.get("level"), fallback=fallback_level),
        "resistances": resists,
        "life": life,
        "energyShield": es,
        "totalPool": _sum_known(life, es),
        "totalEHP": total_ehp,
        "mana": mana,
        "manaUnreserved": mana_unreserved,
        "manaCost": mana_cost,
        "netManaRegen": net_mana_regen,
        "manaRegenRecovery": mana_regen_recovery,
        "manaLeechGainRate": mana_leech_gain_rate,
        "manaOnHitRate": mana_on_hit_rate,
        "skillUseRate": speed,
        "manaSustain": mana_sustain,
        "lifeSustain": life_sustain,
        "resourceSustain": resource_sustain,
        "mainSkillSocketed": _optional_bool(state.get("mainSkillSocketed")),
        "mainSkillSocketEvidence": (
            dict(state["mainSkillSocketEvidence"])
            if isinstance(state.get("mainSkillSocketEvidence"), dict)
            else {}
        ),
        "ascendancyOrKeySupport": (
            dict(state["ascendancyOrKeySupport"])
            if isinstance(state.get("ascendancyOrKeySupport"), dict)
            else {}
        ),
        "singleTargetDuty": (
            dict(state["singleTargetDuty"])
            if isinstance(state.get("singleTargetDuty"), dict)
            else {}
        ),
        "buildDefiningComponent": (
            dict(state["buildDefiningComponent"])
            if isinstance(state.get("buildDefiningComponent"), dict)
            else {}
        ),
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
        if check == "main_skill_socketed":
            rows.append(_main_skill_socketed_check(observations))
        elif check == "first_ascendancy_or_key_support":
            rows.append(_ascendancy_or_key_support_check(observations))
        elif check == "single_target_feels_ok":
            rows.append(_single_target_duty_check(observations))
        elif check == "build_defining_component_online":
            rows.append(_build_defining_component_check(observations))
        elif check in {"resists_capped", "resists_near_cap"}:
            rows.append(
                _resist_check(
                    check,
                    observations,
                    minimum=lifecycle_elemental_resistance_minimum(observations.get("level")),
                )
            )
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
                    "scope": "numeric_evidence_coverage_only",
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


def _build_defining_component_check(observations: dict[str, Any]) -> dict[str, Any]:
    evidence = dict(observations.get("buildDefiningComponent") or {})
    verified = evidence.get("verified")
    return {
        "check": "build_defining_component_online",
        "status": "passed" if verified is True else "failed" if verified is False else "unknown",
        "ok": verified if isinstance(verified, bool) else None,
        "detail": evidence,
        "target": (
            "a named skill, ascendancy or equipped item matched in the active XML with a stable "
            "component key and external evidence refs"
        ),
    }


def _ascendancy_or_key_support_check(observations: dict[str, Any]) -> dict[str, Any]:
    evidence = dict(observations.get("ascendancyOrKeySupport") or {})
    verified = evidence.get("verified")
    return {
        "check": "first_ascendancy_or_key_support",
        "status": "passed" if verified is True else "failed" if verified is False else "unknown",
        "ok": verified if isinstance(verified, bool) else None,
        "detail": evidence,
        "target": "an active ascendancy or at least one support in the active PoB main group",
    }


def _single_target_duty_check(observations: dict[str, Any]) -> dict[str, Any]:
    evidence = dict(observations.get("singleTargetDuty") or {})
    modeled_offense = observations.get("offense") or {}
    damage_values = [modeled_offense.get(key) for key in ("TotalDPS", "FullDPS", "AverageDamage")]
    known_damage = [value for value in damage_values if isinstance(value, (int, float))]
    positive_damage = any(value > 0 for value in known_damage)
    verified = evidence.get("verified")
    if verified is True and positive_damage:
        status = "passed"
        ok: bool | None = True
    elif verified is True and known_damage:
        status = "failed"
        ok = False
    elif verified is False:
        status = "failed"
        ok = False
    else:
        status = "unknown"
        ok = None
    return {
        "check": "single_target_feels_ok",
        "status": status,
        "ok": ok,
        "detail": {
            **evidence,
            "positiveModelledOffense": positive_damage,
            "scope": "single_target_duty_present_not_gameplay_feel_certification",
        },
        "target": (
            "an enabled active skill matched to external mechanic evidence plus positive PoB "
            "offense; actual gameplay feel remains an Agent judgment"
        ),
    }


def _main_skill_socketed_check(observations: dict[str, Any]) -> dict[str, Any]:
    socketed = observations.get("mainSkillSocketed")
    evidence = dict(observations.get("mainSkillSocketEvidence") or {})
    if socketed is True:
        return {
            "check": "main_skill_socketed",
            "status": "passed",
            "ok": True,
            "detail": evidence or {"socketed": True},
            "target": "a legal enabled active composition in the PoB main socket group",
        }
    if socketed is False:
        return {
            "check": "main_skill_socketed",
            "status": "failed",
            "ok": False,
            "detail": evidence or {"socketed": False},
            "target": "a legal enabled active composition in the PoB main socket group",
        }
    return {
        "check": "main_skill_socketed",
        "status": "unknown",
        "ok": None,
        "detail": evidence or {"socketed": None},
        "target": "requires evidence from the active PoB XML snapshot",
    }


def _resistances(stats: dict[str, Any], defenses: dict[str, Any]) -> dict[str, float | None]:
    raw = defenses.get("resistances") if isinstance(defenses.get("resistances"), dict) else {}
    return {
        "fire": _first_number(raw.get("fire"), stats.get("FireResist")),
        "cold": _first_number(raw.get("cold"), stats.get("ColdResist")),
        "lightning": _first_number(raw.get("lightning"), stats.get("LightningResist")),
        "chaos": _first_number(raw.get("chaos"), stats.get("ChaosResist")),
    }


def lifecycle_elemental_resistance_minimum(level: Any) -> float | None:
    """Return the lifecycle-only elemental resistance floor for the actual build level."""

    numeric_level = _lifecycle_level(level)
    if numeric_level is None:
        return None
    for minimum_level, maximum_level, minimum in _ELEMENTAL_RESISTANCE_BANDS:
        if minimum_level <= numeric_level <= maximum_level:
            return minimum
    return None


def _lifecycle_level(value: Any, *, fallback: int | None = None) -> int | None:
    if isinstance(value, bool):
        return fallback
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return fallback
    return numeric if 1 <= numeric <= 100 else fallback


def _resist_check(
    check: str,
    observations: dict[str, Any],
    *,
    minimum: float | None,
) -> dict[str, Any]:
    resists = observations.get("resistances") or {}
    values = {name: resists.get(name) for name in _ELEMENTAL_RESISTS}
    if minimum is None:
        return {
            "check": check,
            "status": "not_applicable",
            "ok": True,
            "detail": values,
            "target": None,
        }
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
    detail = dict(observations.get("resourceSustain") or {})
    if not detail and isinstance(observations.get("manaSustain"), dict):
        # Direct helper callers from the v1 Mana-only contract retain their policy semantics.
        detail = dict(observations["manaSustain"])
    classification = detail.get("classification")
    if classification == "sustainable_baseline":
        return {
            "check": "sustain_ok",
            "status": "passed",
            "ok": True,
            "detail": detail,
            "target": "continuous Mana and Life costs are payable and covered",
        }
    if classification == "model_gap_flask_assisted":
        # The build carries engine-invisible resource layers (e.g. Mana Remnants pickup,
        # Lavianga's Spirits permanent recovery) whose game-real values PoB cannot quantify.
        # The numeric deficit stays fully disclosed below; the engine gap is not treated as a
        # stage-blocking build failure, matching the Judge's warning-only handling of the plain
        # flask-dependency case.
        return {
            "check": "sustain_ok",
            "status": "passed",
            "ok": True,
            "detail": detail,
            "verificationRequired": True,
            "target": (
                "engine-invisible mana mechanisms are present; verify that their recovery covers "
                "the actual skill rotation; any deterministic Life failure remains blocking"
            ),
        }
    if classification == "flask_assisted_required":
        return {
            "check": "sustain_ok",
            "status": "failed",
            "ok": False,
            "detail": detail,
            "target": (
                "continuous use depends on an unclosed Mana or Life recovery source"
            ),
        }
    if classification == "unsustainable":
        return {
            "check": "sustain_ok",
            "status": "failed",
            "ok": False,
            "detail": detail,
            "target": "continuous Mana or Life demand requires a recovery solution",
        }
    return {
        "check": "sustain_ok",
        "status": "unknown",
        "ok": None,
        "detail": detail,
        "target": (
            "requires use rate, unreserved pools and recovery evidence for both Mana and Life"
        ),
    }


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _recommended_actions(
    stage: str,
    checks: list[dict[str, Any]],
    failed: list[str],
    unknown: list[str],
) -> list[str]:
    actions: list[str] = []
    if failed:
        actions.append("Do not transition yet; failed stage checks: " + ", ".join(sorted(failed)))
    if "resists_capped" in failed or "resists_near_cap" in failed:
        actions.append("Cap or repair elemental resistances before progressing this route.")
    if "basic_defense_online" in failed:
        actions.append(
            "Raise the current stage's life/ES/EHP layer before trading defense for damage."
        )
    if "sustain_ok" in failed:
        actions.append("Fix resource sustain before switching stages.")
    elif "sustain_ok" in unknown:
        actions.append(
            "Verify sustain with use rate, recovery, flasks and the real skill rotation; do not "
            "remove supports from mana-pool size alone."
        )
    modelability_row = next(
        (row for row in checks if row.get("check") == "pob_model_supported"),
        None,
    )
    if modelability_row and modelability_row.get("status") == "failed":
        actions.append(
            "PoB reports a modeling limitation. Preserve any game-valid mechanic and use current "
            "mechanic/Research or in-game evidence; do not present the computed number as its true value."
        )
    if "main_skill_socketed" in failed:
        actions.append(
            "Socket one ordinary active, or one valid meta/invocation host with its payload, in the "
            "active PoB main skill group."
        )
    if "first_ascendancy_or_key_support" in failed:
        actions.append("Activate the stage ascendancy or socket a support in the PoB main group.")
    if "single_target_feels_ok" in failed:
        actions.append(
            "Add a real enabled single-target duty and verify it with graph/mechanic evidence."
        )
    if "build_defining_component_online" in failed:
        actions.append(
            "Bring the declared build-defining component online in the active PoB snapshot."
        )

    for check in unknown:
        if check == "build_defining_component_online":
            actions.append(
                "Confirm the build-defining item, gem, or rare affix is actually online before "
                "claiming this endgame stage."
            )
        elif check == "core_threshold_met":
            actions.append("Verify the core threshold directly; do not infer it from guide text.")
        elif check == "upgrade_budget_ready":
            actions.append("Confirm the final upgrade budget/gear assumptions before switching.")
        elif check == "pinnacle_ready":
            actions.append(
                "Run pinnacle readiness or equivalent endgame checks before presenting final form."
            )
        elif check not in {"sustain_ok"}:
            actions.append(
                f"Gather explicit evidence for `{check}` before marking the stage ready."
            )

    if stage == "maps_entry" and failed:
        actions.append(
            "For maps_entry, hold the current setup until resistances, basic defense, and sustain "
            "are stable."
        )
    if not actions:
        actions.append("Stage checks passed; snapshot the PoB before making further changes.")
    return _dedupe(actions)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


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
