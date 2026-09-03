"""Small engine-observable mechanism lock for Phase 5 Draft/Judge validation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from server.compute import skillgroups
from server.compute.state import build_state_hash


_COST_KEYS = {
    "mana": (
        "ManaCost",
        "ManaPercentCost",
        "ManaPerSecondCost",
        "ManaPercentPerSecondCost",
    ),
    "life": (
        "LifeCost",
        "LifePercentCost",
        "LifePerSecondCost",
        "LifePercentPerSecondCost",
    ),
}
_DAMAGE_KEYS = {
    "physical": "PhysicalHitAverage",
    "fire": "FireHitAverage",
    "cold": "ColdHitAverage",
    "lightning": "LightningHitAverage",
    "chaos": "ChaosHitAverage",
}
_STAT_KEYS = [
    *(key for values in _COST_KEYS.values() for key in values),
    *_DAMAGE_KEYS.values(),
]


def observe(engine: Any, target: dict[str, Any]) -> dict[str, Any]:
    """Observe one exact group under a single transaction and always restore the input XML."""

    group_index = int(target.get("offenseSkillGroupIndex") or 0)
    skill_name = str(target.get("activeSkillName") or target.get("expectedSkillName") or "")
    if group_index < 1 or not skill_name:
        return {"ok": False, "errorCode": "generation_mechanism_signature_invalid"}
    lock_factory = getattr(engine, "transaction_lock", None)
    if not callable(lock_factory):
        return {"ok": False, "errorCode": "generation_mechanism_signature_lock_unavailable"}
    with lock_factory():
        try:
            snapshot = engine.get_xml()
            state_hash = build_state_hash(snapshot)
        except Exception:  # noqa: BLE001
            return {"ok": False, "errorCode": "generation_mechanism_signature_snapshot_failed"}
        result = _observe_locked(
            engine,
            group_index=group_index,
            skill_name=skill_name,
            state_hash=state_hash,
        )
        try:
            engine.load_build_xml(snapshot, name="mechanism-signature-restore")
            restored_hash = build_state_hash(engine.get_xml())
        except Exception:  # noqa: BLE001
            return {
                "ok": False,
                "errorCode": "generation_mechanism_signature_restore_failed",
                "recoveryRequired": True,
            }
        if restored_hash != state_hash:
            return {
                "ok": False,
                "errorCode": "generation_mechanism_signature_restore_failed",
                "recoveryRequired": True,
            }
        return result


def _observe_locked(
    engine: Any,
    *,
    group_index: int,
    skill_name: str,
    state_hash: str,
) -> dict[str, Any]:
    try:
        listed = skillgroups.list_skill_groups(engine)
        group = next(
            (
                value
                for value in listed.get("groups") or []
                if isinstance(value, dict) and int(value.get("index") or 0) == group_index
            ),
            None,
        )
        active_skills = _active_skill_names(group)
        if not isinstance(group, dict) or not any(
            value.casefold() == skill_name.casefold() for value in active_skills
        ):
            return {"ok": False, "errorCode": "generation_mechanism_signature_skill_conflict"}
        selected = engine.select_judge_skill(
            offense_skill_group_index=group_index,
            expected_skill_name=skill_name,
        )
        if not isinstance(selected, dict) or selected.get("status") != "selected":
            return {"ok": False, "errorCode": "generation_mechanism_signature_skill_conflict"}
        stats_result = engine.get_stats(_STAT_KEYS)
        stats = stats_result.get("stats") if isinstance(stats_result, dict) else None
        if not isinstance(stats, dict):
            return {"ok": False, "errorCode": "generation_mechanism_signature_stats_missing"}
        supports = sorted(
            str(gem.get("name") or "")
            for gem in group.get("gems") or []
            if isinstance(gem, dict) and gem.get("isSupport") and gem.get("name")
        )
        resource_domains = sorted(
            resource
            for resource, keys in _COST_KEYS.items()
            if any(_positive(stats.get(key)) for key in keys)
        )
        damage_values = {
            damage_type: float(stats.get(key))
            for damage_type, key in _DAMAGE_KEYS.items()
            if _positive(stats.get(key))
        }
        total_hit = sum(damage_values.values())
        dominant_damage_types = sorted(
            damage_type
            for damage_type, value in damage_values.items()
            if total_hit > 0 and value / total_hit >= 0.20
        )
        if damage_values and not dominant_damage_types:
            dominant_damage_types = [max(damage_values, key=damage_values.get)]
        context = dict(selected.get("calculationContext") or {})
        signature = {
            "offenseSkillGroupIndex": group_index,
            "activeSkillName": skill_name,
            "supportNames": supports,
            "resourceCostDomains": resource_domains,
            "hitDamageTypes": dominant_damage_types,
            "hitDamageTypesModelled": any(key in stats for key in _DAMAGE_KEYS.values()),
        }
        return {
            "ok": True,
            "signature": signature,
            "signatureHash": signature_hash(signature),
            "calculationContext": {
                "groupIndex": int(context.get("groupIndex") or group_index),
                "activeIndex": int(context.get("activeIndex") or 1),
                "skillName": str(context.get("skillName") or skill_name),
            },
            "stateHash": state_hash,
        }
    except Exception:  # noqa: BLE001 - bounded public error; restore is handled by caller.
        return {"ok": False, "errorCode": "generation_mechanism_signature_inspection_failed"}


def matches(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    return normalized(expected) == normalized(observed)


def normalized(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "offenseSkillGroupIndex": int(value.get("offenseSkillGroupIndex") or 0),
        "activeSkillName": str(value.get("activeSkillName") or ""),
        "supportNames": sorted(str(item) for item in value.get("supportNames") or []),
        "resourceCostDomains": sorted(
            str(item) for item in value.get("resourceCostDomains") or []
        ),
        "hitDamageTypes": sorted(str(item) for item in value.get("hitDamageTypes") or []),
        "hitDamageTypesModelled": bool(value.get("hitDamageTypesModelled")),
    }


def signature_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(normalized(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _active_skill_names(group: Any) -> list[str]:
    if not isinstance(group, dict):
        return []
    names: list[str] = []
    for value in group.get("activeSkills") or []:
        name = value.get("name") if isinstance(value, dict) else value
        if name:
            names.append(str(name))
    if not names and group.get("activeSkill"):
        names.append(str(group["activeSkill"]))
    return names


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 0
