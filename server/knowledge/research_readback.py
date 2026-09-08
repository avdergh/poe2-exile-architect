"""Isolated, raw-free PoB readback for one claimed Research source."""

from __future__ import annotations

from typing import Any
import xml.etree.ElementTree as ET

from server.compute.engine import PobEngine
from server.compute.state import build_state_hash
from server.compute.pob_xml_input import XML_INPUT_SEMANTICS_VERSION, parse_pob_xml
from server.knowledge.research_packet import (
    active_set_identity,
    config_set_identity,
    source_snapshot_hash,
)


READBACK_SCHEMA_VERSION = "research_pob_readback_v4"
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


def normalize_version_context(value: dict[str, str]) -> dict[str, str]:
    """Carry source and certified model identities separately, including unknown models."""
    result = {key: str(value.get(key) or "") for key in (
        "gamePatch", "passiveTreeVersion", "pobVersionOrCommit", "modelGamePatch"
    )}
    model = result["modelGamePatch"]
    if not model or model.casefold() == "unknown":
        result["modelGamePatch"] = ""
        result["status"] = "model_version_unknown"
    elif result["gamePatch"] != model:
        result["status"] = "source_patch_model_mismatch"
    else:
        result["status"] = "certified_local_runtime"
    return result


def _version_caveats(context: dict[str, str]) -> list[str]:
    if context["status"] == "source_patch_model_mismatch":
        return [f"Source patch {context['gamePatch']} is evaluated with model patch "
                f"{context['modelGamePatch']}; numbers are not certified for the source patch."]
    if context["status"] == "model_version_unknown":
        return ["The model patch is unknown; verify source-patch model support before adopting numbers."]
    return []


def build_safe_readback(
    xml: str, *, source_hash_ref: str, version_context: dict[str, str]
) -> dict[str, Any]:
    """Recompute one active source snapshot without exposing its XML or whole build."""

    version_context = normalize_version_context(version_context)
    if not str(xml or "").strip():
        return _unavailable("missing_source_xml", version_context=version_context)
    try:
        source_root = parse_pob_xml(xml)
        source_config = config_set_identity(source_root)
        source_sets = active_set_identity(source_root)
    except ET.ParseError:
        return _unavailable("invalid_source_xml", version_context=version_context)
    if source_config["activeConfigSet"] is None:
        return _unavailable(
            "source_config_identity_invalid", version_context=version_context,
            detail=",".join(source_config["issues"]),
        )
    if source_sets["issues"]:
        return _unavailable(
            "source_active_set_identity_invalid", version_context=version_context,
            detail=",".join(source_sets["issues"]),
        )
    try:
        with PobEngine(show_engine_logs=False) as engine:
            engine.load_build_xml(xml, name="research-readback")
            stats_result = engine.get_stats(list(STAT_KEYS))
            stats = stats_result.get("stats") if isinstance(stats_result, dict) else {}
            stats = stats if isinstance(stats, dict) else {}
            build = engine.get_build()
            observed_xml = engine.get_xml()
            observed_root = parse_pob_xml(observed_xml)
            observed_config = config_set_identity(observed_root)
            observed_sets = active_set_identity(observed_root)
            if (
                observed_config["activeConfigSet"] is None
                or observed_config["activeConfigSet"] != source_config["activeConfigSet"]
                or (
                    source_config["status"] == "resolved"
                    and observed_config["status"] != "resolved"
                )
            ):
                return _unavailable(
                    "pob_active_config_set_mismatch", version_context=version_context
                )
            if observed_sets["issues"] or observed_sets["activeSets"] != source_sets["activeSets"]:
                return _unavailable(
                    "pob_active_set_mismatch", version_context=version_context
                )
            state_hash = build_state_hash(observed_xml)
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
            "configScope": "source_active_config_set",
            "activeConfigSet": observed_config["activeConfigSet"],
            "sourceActiveConfigSet": source_config["activeConfigSet"],
            "sourceConfigIdentityStatus": source_config["status"],
            "activeSets": observed_sets["activeSets"],
            "sourceActiveSets": source_sets["activeSets"],
            "sourceSnapshotHash": source_snapshot_hash(xml),
            "xmlInputSemanticsVersion": XML_INPUT_SEMANTICS_VERSION,
            "sourceInputStateHash": build_state_hash(xml),
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
                *_version_caveats(version_context),
                "Active-snapshot numbers do not prove Boss uptime or alternate weapon state.",
                "Only the bound active ConfigSet supplies these numbers; other sets are separate scenarios.",
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
        "versionCaveats": _version_caveats(normalize_version_context(version_context)),
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
