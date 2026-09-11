"""Project observed PoB defense mechanics without changing allocated-tree metadata."""

from __future__ import annotations

from typing import Any


def defense_keystones(build: dict[str, Any]) -> list[str] | None:
    """Use native CI state when present; retain tree-only compatibility for old readbacks.

    A present but incomplete runtime observation cannot fall back to an allocated node, a
    one-Life pool, resistance values, item names, or text in inactive equipment.
    """
    allocated = build.get("keystones")
    names = [str(name) for name in allocated] if isinstance(allocated, list) else []
    if "defenseMechanics" not in build:
        return names if allocated is not None else None
    observation = build.get("defenseMechanics")
    names = [name for name in names if name.strip().casefold() != "chaos inoculation"]
    if (
        isinstance(observation, dict)
        and type(observation.get("schemaVersion")) is int
        and observation.get("schemaVersion") == 1
        and observation.get("source") == "pob_main_output"
        and observation.get("status") == "observed"
        and observation.get("chaosInoculation") is True
    ):
        names.append("Chaos Inoculation")
    return names


def has_chaos_inoculation(build: dict[str, Any]) -> bool:
    return "chaos inoculation" in {
        name.strip().casefold() for name in (defense_keystones(build) or [])
    }
