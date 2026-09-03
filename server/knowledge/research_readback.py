"""Isolated, raw-free PoB readback for one claimed Research source."""

from __future__ import annotations

from typing import Any

from server.compute.engine import PobEngine
from server.compute.state import build_state_hash


READBACK_SCHEMA_VERSION = "research_pob_readback_v3"
METRIC_SET_VERSION = 2
STAT_KEYS = (
    "Life",
    "LifeUnreserved",
    "EnergyShield",
    "Ward",
    "Mana",
    "ManaUnreserved",
    "Spirit",
    "SpiritReserved",
    "SpiritUnreserved",
    "ManaCost",
    "ManaPerSecondCost",
    "ManaRegen",
    "TotalEHP",
    "FireResist",
    "ColdResist",
    "LightningResist",
    "ChaosResist",
)


def build_safe_readback(
    xml: str, *, source_hash_ref: str, version_context: dict[str, str]
) -> dict[str, Any]:
    """Recompute one active source snapshot without exposing its XML or whole build."""

    if not str(xml or "").strip():
        return _unavailable("missing_source_xml", version_context=version_context)
    try:
        with PobEngine(show_engine_logs=False) as engine:
            engine.load_build_xml(xml, name="research-readback")
            stats_result = engine.get_stats(list(STAT_KEYS))
            stats = stats_result.get("stats") if isinstance(stats_result, dict) else {}
            stats = stats if isinstance(stats, dict) else {}
            build = engine.get_build()
            state_hash = build_state_hash(engine.get_xml())
    except Exception as exc:
        return _unavailable(
            "pob_readback_failed",
            version_context=version_context,
            detail=type(exc).__name__,
        )
    bounded_stats = {
        key: _finite_number(stats.get(key))
        for key in STAT_KEYS
        if _finite_number(stats.get(key)) is not None
    }
    spirit_available = _build_number(build, "spiritAvailable")
    spirit_reserved_capped = _build_number(build, "spiritReservedCapped")
    spirit_unreserved = _build_number(build, "spiritUnreserved")
    spirit_requested = _build_number(build, "spiritRequested")
    spirit_over_by = _build_number(build, "spiritOverBy")
    spirit_used = _build_number(build, "spiritUsed")
    active_weapon_set = _build_integer(build, "activeWeaponSet")
    ledger_status = _spirit_ledger_status(
        available=spirit_available,
        reserved_capped=spirit_reserved_capped,
        unreserved=spirit_unreserved,
        requested=spirit_requested,
        over_by=spirit_over_by,
        used=spirit_used,
    )
    return {
        "status": "available",
        "schemaVersion": READBACK_SCHEMA_VERSION,
        "metricSetVersion": METRIC_SET_VERSION,
        "snapshotRef": f"pob-readback:{state_hash[:20]}",
        "stateRef": f"pob-state:{state_hash[:20]}:active",
        "sourceHashRef": source_hash_ref,
        "stateBinding": {
            "semanticBuildStateHash": state_hash,
            "weaponSetState": "active",
            "activeWeaponSet": active_weapon_set,
            "configScope": "source_active_snapshot",
        },
        "versionContext": dict(version_context),
        "stats": bounded_stats,
        "resources": {
            "spiritAvailable": spirit_available,
            "spiritReservedCapped": spirit_reserved_capped,
            "spiritUsed": spirit_used,
            "spiritUnreserved": spirit_unreserved,
            "spiritRequested": spirit_requested,
            "spiritOverBy": spirit_over_by,
            "ledgerStatus": ledger_status,
        },
        "modelability": {
            "status": "partial",
            "caveats": [
                "Active-snapshot numbers do not prove Boss uptime or alternate weapon state.",
                "Meta-trigger FullDPS may remain unmodelled by the pinned engine.",
            ],
        },
        "noRawMatureBuildMaterial": True,
    }


def _unavailable(
    code: str,
    *,
    version_context: dict[str, str],
    detail: str = "",
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "schemaVersion": READBACK_SCHEMA_VERSION,
        "metricSetVersion": METRIC_SET_VERSION,
        "errorCode": code,
        "errorKind": detail,
        "versionContext": dict(version_context),
        "noRawMatureBuildMaterial": True,
    }


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _build_number(build: Any, key: str) -> float | None:
    return _finite_number(build.get(key)) if isinstance(build, dict) else None


def _build_integer(build: Any, key: str) -> int | None:
    number = _build_number(build, key)
    if number is None or not number.is_integer():
        return None
    value = int(number)
    return value if value in {1, 2} else None


def _spirit_ledger_status(
    *,
    available: float | None,
    reserved_capped: float | None,
    unreserved: float | None,
    requested: float | None,
    over_by: float | None,
    used: float | None,
) -> str:
    values = (available, reserved_capped, unreserved, requested, over_by, used)
    if any(value is None for value in values):
        return "unavailable"
    assert available is not None
    assert reserved_capped is not None
    assert unreserved is not None
    assert requested is not None
    assert over_by is not None
    assert used is not None
    expected_requested = available - unreserved
    expected_over_by = max(0.0, -unreserved)
    expected_capped = min(expected_requested, available)
    if any(value < 0 for value in (available, requested, over_by, reserved_capped)):
        return "inconsistent"
    if not all(
        _close(left, right)
        for left, right in (
            (requested, expected_requested),
            (over_by, expected_over_by),
            (reserved_capped, expected_capped),
            (used, requested),
        )
    ):
        return "inconsistent"
    return "consistent"


def _close(left: float, right: float, *, tolerance: float = 1e-6) -> bool:
    return abs(left - right) <= tolerance
