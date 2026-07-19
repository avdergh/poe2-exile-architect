"""Modelability classification for PoB/PoE2 gaps."""

from __future__ import annotations

from typing import Any

CORE_META_TRIGGERS = {
    "Cast on Critical",
    "Cast on Shock",
    "Cast on Freeze",
    "Cast on Ignite",
    "Cast on Minion Death",
}

WHITELISTED_LIGHT_CAVEATS = {
    "projectile overlap",
}


def evaluate_modelability(
    build: dict[str, Any],
    *,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    caveats: list[str] = []
    failure_codes: list[str] = []
    warnings = warnings or []

    main_group = build.get("mainSkillGroup") or []
    for gem in main_group:
        if gem.get("isSupport") and str(gem.get("name") or "") in CORE_META_TRIGGERS:
            return {
                "status": "not_modelable",
                "coreBlocked": True,
                "failureCodes": [],
                "unmodelledMechanics": [str(gem.get("name") or "")],
                "caveats": [
                    "main_socket_group_core_unmodelled",
                    "trigger_rate_unmodelled_caveat",
                ],
            }

    status = "full"
    for warning in warnings:
        low = str(warning).lower()
        if any(token in low for token in WHITELISTED_LIGHT_CAVEATS):
            status = "partial"
            caveats.append("non_core_unmodelled_whitelist")
        elif (
            "not model" in low
            or "not modelled" in low
            or "unmodel" in low
            or "engine limitation" in low
        ):
            status = "partial"
            caveats.append("modelability_penalty")

    return {
        "status": status,
        "coreBlocked": False,
        "failureCodes": failure_codes,
        "unmodelledMechanics": [],
        "caveats": _dedupe(caveats),
    }


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
