"""Structured Mana/Life sustain diagnostics derived from pinned PoB metrics."""

from __future__ import annotations

from typing import Any


_COST_SUFFIXES = ("Cost", "PercentCost", "PerSecondCost", "PercentPerSecondCost")


def classify_resource_sustain(
    stats: dict[str, Any],
    *,
    mana_flask_equipped: bool | None,
    unmodelled_mana_mechanisms: list[str] | None = None,
) -> dict[str, Any]:
    """Classify the selected skill's modelled Mana and Life payment domains.

    This deliberately covers only Mana and Life. PoB exposes additional cost domains, but they
    require different recovery semantics and are not implied by this result.
    """

    mana = _classify_pool_sustain(
        stats,
        resource="Mana",
        flask_equipped=mana_flask_equipped,
        unmodelled_mechanisms=unmodelled_mana_mechanisms,
    )
    life = _classify_pool_sustain(
        stats,
        resource="Life",
        flask_equipped=None,
        unmodelled_mechanisms=None,
    )
    classifications = {mana["classification"], life["classification"]}
    if "unsustainable" in classifications or "flask_assisted_required" in classifications:
        classification = "unsustainable"
        status = "failed"
    elif "unknown" in classifications:
        classification = "unknown"
        status = "unknown"
    elif "model_gap_flask_assisted" in classifications:
        classification = "model_gap_flask_assisted"
        status = "passed"
    else:
        classification = "sustainable_baseline"
        status = "passed"
    return {
        "classification": classification,
        "status": status,
        "manaSustain": mana,
        "lifeSustain": life,
        "verificationRequired": classification == "model_gap_flask_assisted",
        "coveredResources": ["mana", "life"],
        "excludedResources": ["energy_shield", "rage", "soul", "divinity"],
    }


def classify_mana_sustain(
    stats: dict[str, Any],
    *,
    mana_flask_equipped: bool | None,
    unmodelled_mana_mechanisms: list[str] | None = None,
) -> dict[str, Any]:
    """Backward-compatible Mana-only view used by older callers and receipts."""

    return _classify_pool_sustain(
        stats,
        resource="Mana",
        flask_equipped=mana_flask_equipped,
        unmodelled_mechanisms=unmodelled_mana_mechanisms,
    )


def _classify_pool_sustain(
    stats: dict[str, Any],
    *,
    resource: str,
    flask_equipped: bool | None,
    unmodelled_mechanisms: list[str] | None,
) -> dict[str, Any]:
    resource_key = resource.casefold()
    costs = {suffix: _number(stats.get(resource + suffix)) for suffix in _COST_SUFFIXES}
    use_rate = _number(stats.get("Speed"))
    pool = _number(stats.get(resource))
    unreserved = _first_number(stats.get(resource + "Unreserved"), pool)
    unreserved_percent = _number(stats.get(resource + "UnreservedPercent"))
    regen = _first_number(
        stats.get("Net" + resource + "Regen"),
        stats.get(resource + "RegenRecovery"),
    )
    # Pinned PoB's *LeechGainRate already includes on-hit gain. OnHitRate is only a fallback.
    gain_rate = _first_number(
        stats.get(resource + "LeechGainRate"),
        stats.get(resource + "OnHitRate"),
    )
    recovery_known = regen is not None or gain_rate is not None
    recovery = float(regen or 0.0) + float(gain_rate or 0.0) if recovery_known else None
    mechanisms = list(
        dict.fromkeys(str(value) for value in (unmodelled_mechanisms or []) if value)
    )
    flat = costs["Cost"]
    percent = costs["PercentCost"]
    per_second = costs["PerSecondCost"]
    percent_per_second = costs["PercentPerSecondCost"]
    any_cost_metric = any(value is not None for value in costs.values())
    has_upfront_cost = bool((flat or 0.0) > 0 or (percent or 0.0) > 0)
    has_per_second_cost = bool(
        (per_second or 0.0) > 0 or (percent_per_second or 0.0) > 0
    )
    has_cost = has_upfront_cost or has_per_second_cost
    upfront_payable: bool | None = True
    if (flat or 0.0) > 0:
        upfront_payable = None if unreserved is None else unreserved >= float(flat or 0.0)
    if upfront_payable is not False and (percent or 0.0) > 0:
        percent_payable = (
            None
            if unreserved_percent is None
            else unreserved_percent >= float(percent or 0.0)
        )
        if percent_payable is False:
            upfront_payable = False
        elif upfront_payable is True and percent_payable is None:
            upfront_payable = None
    if upfront_payable is not False and (percent or 0.0) > 0:
        if pool is None or unreserved is None:
            upfront_payable = None
        else:
            combined_upfront = float(flat or 0.0) + pool * float(percent or 0.0) / 100.0
            if combined_upfront > unreserved:
                upfront_payable = False

    result: dict[str, Any] = {
        "resource": resource_key,
        "classification": "unknown",
        "evidenceStatus": "incomplete",
        resource_key + "CostPerUse": flat,
        resource_key + "PercentCostPerUse": percent,
        resource_key + "PerSecondCost": per_second,
        resource_key + "PercentPerSecondCost": percent_per_second,
        resource_key + "Pool": pool,
        resource_key + "Unreserved": unreserved,
        resource_key + "UnreservedPercent": unreserved_percent,
        resource_key + "FlaskEquipped": flask_equipped,
        "skillUseRate": use_rate,
        "upfrontPayable": upfront_payable,
        "combinedUpfrontCost": (
            None
            if pool is None and (percent or 0.0) > 0
            else float(flat or 0.0) + float(pool or 0.0) * float(percent or 0.0) / 100.0
        ),
        "recoveryPerSecond": recovery,
        "recoveryComponents": {"regen": regen, "leechAndOnHit": gain_rate},
        "grossDemandPerSecond": None,
        "netDeficitPerSecond": None,
        "secondsFromFull": None,
        "bossRisk": "unknown",
        "unmodelledManaMechanisms": mechanisms if resource == "Mana" else [],
    }
    if upfront_payable is False:
        result.update(
            classification="unsustainable",
            evidenceStatus="complete",
            bossRisk=f"single_use_cannot_be_paid_from_unreserved_{resource_key}",
        )
        return result
    if not has_cost:
        # Life cost outputs are normally absent when the skill does not pay Life. Mana preserves
        # the historical unknown result when PoB supplied no Mana cost output at all.
        if resource == "Mana" and not any_cost_metric:
            if mechanisms:
                result.update(
                    classification="model_gap_flask_assisted",
                    bossRisk="unmodelled_recovery_requires_verification",
                )
            return result
        result.update(
            classification="sustainable_baseline",
            evidenceStatus="complete",
            grossDemandPerSecond=0.0,
            netDeficitPerSecond=0.0,
            bossRisk=f"none_from_{resource_key}_cost",
        )
        return result
    if upfront_payable is None:
        return result
    absolute_rate_supplied = (per_second or 0.0) > 0
    percent_rate_supplied = (percent_per_second or 0.0) > 0
    needs_use_rate = (
        ((flat or 0.0) > 0 and not absolute_rate_supplied)
        or ((percent or 0.0) > 0 and not percent_rate_supplied)
    )
    if needs_use_rate and (use_rate is None or use_rate <= 0):
        if resource == "Mana" and mechanisms:
            result.update(
                classification="model_gap_flask_assisted",
                bossRisk="unmodelled_recovery_requires_verification",
            )
        return result
    if ((percent or 0.0) > 0 or (percent_per_second or 0.0) > 0) and pool is None:
        return result
    if recovery is None:
        if resource == "Mana" and mechanisms:
            result.update(
                classification="model_gap_flask_assisted",
                bossRisk="unmodelled_recovery_requires_verification",
            )
        return result

    # PoB's *PerSecondCost is authoritative when present. For ordinary skills it already
    # contains Cost multiplied by the real use rate (including cooldowns/repeats/reload); adding
    # Cost * Speed again double-counts the same payment. Only derive a rate from the per-use field
    # when PoB did not provide the corresponding per-second value.
    absolute_demand = (
        float(per_second or 0.0)
        if absolute_rate_supplied
        else float(flat or 0.0) * float(use_rate or 0.0)
    )
    percent_rate = (
        float(percent_per_second or 0.0)
        if percent_rate_supplied
        else float(percent or 0.0) * float(use_rate or 0.0)
    )
    demand = absolute_demand + float(pool or 0.0) * percent_rate / 100.0
    deficit = max(0.0, demand - recovery)
    seconds = unreserved / deficit if deficit > 0 and unreserved is not None else None
    result.update(
        evidenceStatus="complete",
        grossDemandPerSecond=demand,
        netDeficitPerSecond=deficit,
        secondsFromFull=seconds,
    )
    if deficit <= 1e-9:
        result.update(
            classification="sustainable_baseline",
            bossRisk=f"none_from_continuous_{resource_key}_demand",
        )
    elif resource == "Mana" and mechanisms:
        result.update(
            classification="model_gap_flask_assisted",
            bossRisk="unmodelled_recovery_requires_verification",
        )
    elif resource == "Mana" and flask_equipped is True:
        result.update(
            classification="flask_assisted_required",
            bossRisk="long_boss_fight_can_run_out_of_mana",
        )
    else:
        result.update(
            classification="unsustainable",
            bossRisk=f"continuous_use_runs_out_of_{resource_key}",
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
