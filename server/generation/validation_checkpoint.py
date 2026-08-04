"""State-hash keyed generation checks that collapse repeated read-only validation calls."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from copy import deepcopy
from typing import Any

from server.compute import completeness
from server.compute.state import build_state_hash

from . import preflight


CHECKPOINT_VERSION = "generation_checkpoint_v3"
_CACHE_LIMIT = 48
_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_LOCK = threading.RLock()
_STAT_KEYS = [
    "CombinedDPS",
    "TotalDPS",
    "FullDPS",
    "TotalEHP",
    "Life",
    "EnergyShield",
    "Mana",
    "Spirit",
    "Accuracy",
    "HitChance",
    "ManaCost",
    "Speed",
]


def inspect_generation_checkpoint(
    engine: Any,
    *,
    strict_mode: bool = False,
) -> dict[str, Any]:
    """Inspect one semantic build state once, then reuse the bounded result for identical states."""

    with engine.transaction_lock():
        try:
            xml = engine.get_xml()
        except Exception:  # noqa: BLE001
            return _project_result(
                _error("generation_checkpoint_snapshot_failed"),
                strict_mode=strict_mode,
            )
        state_hash = build_state_hash(xml)
        cache_key = f"{CHECKPOINT_VERSION}:{state_hash}"
        with _LOCK:
            cached = _CACHE.get(cache_key)
            if cached is not None:
                _CACHE.move_to_end(cache_key)
                result = deepcopy(cached)
                result["cacheHit"] = True
                return _project_result(result, strict_mode=strict_mode)

        try:
            complete = completeness.inspect_build_completeness(engine, snapshot_xml=xml)
            preflight_result = preflight.inspect_generation_snapshot(
                engine,
                xml,
                completeness_result=complete,
            )
            build = engine.get_build()
            stats_result = engine.get_stats(_STAT_KEYS)
            defenses = engine.get_defenses()
            after_hash = build_state_hash(engine.get_xml())
        except Exception:  # noqa: BLE001
            return _project_result(
                _error("generation_checkpoint_inspection_failed", state_hash=state_hash),
                strict_mode=strict_mode,
            )
        if after_hash != state_hash:
            return _project_result(
                _error(
                    "generation_checkpoint_state_changed",
                    state_hash=state_hash,
                    actual_state_hash=after_hash,
                ),
                strict_mode=strict_mode,
            )

        stats = stats_result.get("stats") if isinstance(stats_result, dict) else {}
        if not isinstance(stats, dict):
            stats = {}
        build = build if isinstance(build, dict) else {}
        result = {
            "status": "ready" if preflight_result.get("readyForJudge") else "blocked",
            "checkpointVersion": CHECKPOINT_VERSION,
            "validationRef": _validation_ref(state_hash),
            "stateHash": state_hash,
            "cacheHit": False,
            "buildSummary": {
                "class": build.get("class"),
                "ascendancy": build.get("ascendancy"),
                "level": build.get("level"),
                "mainSkill": build.get("mainSkill"),
            },
            "stats": {key: stats.get(key) for key in _STAT_KEYS if key in stats},
            "defenses": defenses if isinstance(defenses, dict) else {},
            "completeness": complete,
            "preflight": preflight_result,
            "hardLegality": preflight_result.get("hardLegality"),
            "hardLegalityReady": bool(preflight_result.get("hardLegalityReady")),
            "mechanismReady": bool(preflight_result.get("mechanismReady")),
            "readinessReady": bool(preflight_result.get("readinessReady", True)),
            "readinessGates": deepcopy(preflight_result.get("readinessGates") or {}),
            "qualityAdvisories": list(preflight_result.get("qualityAdvisories") or []),
            "readyForJudge": bool(preflight_result.get("readyForJudge")),
            "sameStateVerified": True,
            "noRawMaterial": True,
        }
        with _LOCK:
            _CACHE[cache_key] = deepcopy(result)
            _CACHE.move_to_end(cache_key)
            while len(_CACHE) > _CACHE_LIMIT:
                _CACHE.popitem(last=False)
        return _project_result(result, strict_mode=strict_mode)


def clear_validation_checkpoint_cache() -> None:
    """Test/runtime maintenance helper."""

    with _LOCK:
        _CACHE.clear()


def _project_result(result: dict[str, Any], *, strict_mode: bool) -> dict[str, Any]:
    projected = deepcopy(result)
    projected["feedbackMode"] = "strict" if strict_mode else "hard_only"
    projected["subjectiveFeedbackSuppressed"] = not strict_mode
    nested_preflight = projected.get("preflight")
    if isinstance(nested_preflight, dict):
        projected["preflight"] = preflight.project_feedback(
            nested_preflight,
            strict_mode=strict_mode,
        )
    if strict_mode:
        return projected
    projected["qualityAdvisories"] = []
    completeness_result = projected.get("completeness")
    if isinstance(completeness_result, dict):
        completeness_result["advisories"] = []
        completeness_result["status"] = (
            "complete" if not completeness_result.get("hardFailures") else "needs_attention"
        )
    return projected


def _validation_ref(state_hash: str) -> str:
    digest = hashlib.sha256(f"{CHECKPOINT_VERSION}|{state_hash}".encode()).hexdigest()[:24]
    return f"generation-checkpoint:{digest}"


def _error(
    error_code: str,
    *,
    state_hash: str | None = None,
    actual_state_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "error",
        "errorCode": error_code,
        "stateHash": state_hash,
        "actualStateHash": actual_state_hash,
        "readyForJudge": False,
        "hardLegalityReady": False,
        "mechanismReady": False,
        "qualityAdvisories": [],
        "sameStateVerified": False,
        "noRawMaterial": True,
    }
