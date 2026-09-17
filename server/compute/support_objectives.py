"""Bounded support objectives; runtime effect evidence authorizes utility metrics."""

from __future__ import annotations

import math
from typing import Any


METRIC_DIRECTIONS = {
    "TotalDPS": "higher", "FullDPS": "higher", "CombinedDPS": "higher",
    "AverageDamage": "higher", "Speed": "higher", "HitChance": "higher",
    "CritChance": "higher", "CritMultiplier": "higher", "TotalEHP": "higher",
    "LifeRegenRecovery": "higher", "EnergyShieldRegenRecovery": "higher",
    "ManaRegenRecovery": "higher", "MinionCombinedDPS": "higher",
    "MinionTotalDPS": "higher", "ManaCost": "lower", "SpiritReserved": "lower",
    "Duration": "higher", "AreaOfEffectMod": "higher", "CurseEffectMod": "higher",
}
UTILITY_ROLES = {
    "Duration": "duration", "AreaOfEffectMod": "area", "CurseEffectMod": "curse",
}
PLAYER_DAMAGE_METRICS = frozenset({"TotalDPS", "CombinedDPS"})


def inspect_objective_names(keys: list[str], *, weighted: bool) -> dict[str, Any] | None:
    """Parameter errors are independent of runtime model coverage."""
    unknown = [key for key in keys if key not in METRIC_DIRECTIONS]
    lower_weighted = [key for key in keys if weighted and METRIC_DIRECTIONS.get(key) == "lower"]
    if unknown or lower_weighted:
        return {
            "ok": False, "errorCode": "unsupported_support_objective",
            "unsupportedObjectives": unknown, "unsupportedWeightedObjectives": lower_weighted,
            "supportedObjectives": dict(METRIC_DIRECTIONS),
        }
    return None


def inspect_objectives(
    keys: list[str], *, weighted: bool, capability: dict[str, Any],
    utility_stats: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Reject unsupported goals before any candidate probes, without rejecting all zeroes.

    Utility authorization requires an exact selected native effect with the corresponding
    runtime skill role and a present PoB output. A finite value on its own is insufficient.
    Existing non-utility objectives retain their modelability checks in the optimizer.
    """

    if error := inspect_objective_names(keys, weighted=weighted):
        return error
    context = capability.get("objectiveContext") or {}
    if not isinstance(context, dict):
        context = {}
    roles = context.get("roles") or {}
    if not isinstance(roles, dict):
        roles = {}
    attested = (
        capability.get("capabilitySource") == "pob_runtime"
        and context.get("version") == 1
        and bool(capability.get("selectedEffectId"))
        and context.get("selectedEffectId") == capability.get("selectedEffectId")
    )
    if attested and context.get("actor") == "minion":
        mismatched = sorted(PLAYER_DAMAGE_METRICS.intersection(keys))
        if mismatched:
            return {
                "ok": False, "errorCode": "support_objective_actor_mismatch",
                "objectives": mismatched, "actor": "minion",
                "selectedEffectId": capability["selectedEffectId"],
                "suggestedObjectives": ["MinionTotalDPS", "MinionCombinedDPS"],
            }
    for key in keys:
        role = UTILITY_ROLES.get(key)
        if role is None:
            continue
        if not attested or roles.get(role) is not True:
            return {
                "ok": False, "errorCode": "support_objective_role_mismatch",
                "objective": key, "requiredRole": role,
                "selectedEffectId": capability.get("selectedEffectId"),
            }
        value = (utility_stats or {}).get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            return {
                "ok": False, "errorCode": "support_objective_output_missing",
                "objective": key, "selectedEffectId": capability["selectedEffectId"],
            }
    return None
