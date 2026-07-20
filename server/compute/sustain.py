"""Structured resource-sustain diagnostics derived from pinned PoB rate metrics."""

from __future__ import annotations

from typing import Any


def classify_mana_sustain(
    stats: dict[str, Any],
    *,
    mana_flask_equipped: bool | None,
) -> dict[str, Any]:
    """Classify continuous main-skill mana sustain without inventing flask recovery rates."""
    mana_cost = _number(stats.get("ManaCost"))
    use_rate = _number(stats.get("Speed"))
    mana_pool = _first_number(stats.get("ManaUnreserved"), stats.get("Mana"))
    # Prefer PoB's net regeneration when available (it can account for ongoing mana degeneration),
    # then fall back to the raw regeneration recovery metric used by older readbacks.
    regen = _first_number(stats.get("NetManaRegen"), stats.get("ManaRegenRecovery"))
    leech = _number(stats.get("ManaLeechGainRate"))
    on_hit = _number(stats.get("ManaOnHitRate"))
    recovery_known = any(value is not None for value in (regen, leech, on_hit))
    recovery = None
    if recovery_known:
        recovery = sum(float(value or 0.0) for value in (regen, leech, on_hit))

    result: dict[str, Any] = {
        "classification": "unknown",
        "evidenceStatus": "incomplete",
        "manaCostPerUse": mana_cost,
        "skillUseRate": use_rate,
        "manaPool": mana_pool,
        "manaFlaskEquipped": mana_flask_equipped,
        "recoveryPerSecond": recovery,
        "recoveryComponents": {
            "regen": regen,
            "leech": leech,
            "onHit": on_hit,
        },
        "grossDemandPerSecond": None,
        "netDeficitPerSecond": None,
        "secondsFromFull": None,
        "bossRisk": "unknown",
    }
    if mana_cost is None:
        return result
    if mana_cost <= 0:
        result.update(
            {
                "classification": "sustainable_baseline",
                "evidenceStatus": "complete",
                "grossDemandPerSecond": 0.0,
                "netDeficitPerSecond": 0.0,
                "bossRisk": "none_from_mana_cost",
            }
        )
        return result
    if use_rate is None or use_rate <= 0 or recovery is None:
        return result

    demand = mana_cost * use_rate
    deficit = max(0.0, demand - recovery)
    seconds = None
    if deficit > 0 and mana_pool is not None and mana_pool >= 0:
        seconds = mana_pool / deficit
    result.update(
        {
            "evidenceStatus": "complete",
            "grossDemandPerSecond": demand,
            "netDeficitPerSecond": deficit,
            "secondsFromFull": seconds,
        }
    )
    if deficit <= 1e-9:
        result.update(
            {
                "classification": "sustainable_baseline",
                "bossRisk": "none_from_continuous_mana_demand",
            }
        )
    elif mana_flask_equipped is True:
        result.update(
            {
                "classification": "flask_assisted_required",
                "bossRisk": "long_boss_fight_can_run_out_of_mana",
            }
        )
    elif mana_flask_equipped is False:
        result.update(
            {
                "classification": "unsustainable",
                "bossRisk": "continuous_use_runs_out_of_mana",
            }
        )
    return result


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None
