"""Shared, score-free hard legality audit for generated PoB states.

The audit is intentionally deterministic and raw-free.  It is used before Judge, by Judge itself,
by candidate item probes and by artifact selection so the same build state cannot be considered
legal in one layer and illegal in another.
"""

from __future__ import annotations

import json
from typing import Any

from server.compute import completeness

from . import rules, scoring


AUDIT_VERSION = "hard_legality_v1"


def audit_active_build(
    engine: Any,
    *,
    snapshot_xml: str | None = None,
    source_context: str = "generated_candidate",
) -> dict[str, Any]:
    xml = snapshot_xml if snapshot_xml is not None else engine.get_xml()
    build = engine.get_build()
    return audit_build(
        augment_build_with_snapshot_gear(build, xml),
        source_context=source_context,
    )


def audit_build(
    build: dict[str, Any],
    *,
    source_context: str = "generated_candidate",
) -> dict[str, Any]:
    """Evaluate only deterministic legality; no strength scoring or quality threshold."""

    build = build if isinstance(build, dict) else {}
    failures: list[str] = []
    caveats: list[str] = []
    band = scoring.level_band(int(_num(build.get("level")) or 0))

    class_check = rules.check_class_ascendancy(
        build.get("class"),
        build.get("ascendancy"),
        level_band=band,
    )
    if not class_check.get("ok"):
        failures.append(str(class_check.get("failureCode")))
    if class_check.get("caveat"):
        caveats.append(str(class_check["caveat"]))

    weapon_check = rules.check_weapon_skill_compatibility(evaluation_weapon_check(build))
    if not weapon_check.get("ok"):
        failures.append(str(weapon_check.get("failureCode")))

    passive_budget = check_passive_budget(build, source_context=source_context)
    if passive_budget.get("failure"):
        failures.append("passive_budget_exceeded")
    if passive_budget.get("caveat"):
        caveats.append(str(passive_budget["caveat"]))

    weapon_set_budget = check_weapon_set_budget(build, source_context=source_context)
    if weapon_set_budget.get("failure"):
        failures.append("weapon_set_budget_exceeded")
    if weapon_set_budget.get("caveat"):
        caveats.append(str(weapon_set_budget["caveat"]))

    shortfalls = attribute_shortfalls(build)
    if shortfalls:
        failures.append("attribute_requirement_unmet")

    item_requirements = rules.check_equipped_item_requirements(build)
    if not item_requirements.get("ok"):
        failures.append("equipped_item_level_requirement_unmet")

    active_gem_requirements = rules.check_active_skill_gem_requirements(build)
    if not active_gem_requirements.get("ok"):
        failures.append("active_skill_gem_level_requirement_unmet")

    item_affixes = rules.check_equipped_item_affixes(build)
    if not item_affixes.get("ok"):
        failures.append("illegal_equipped_item_affixes")

    spirit_used = _num(build.get("spiritUsed")) if build.get("spiritUsed") is not None else None
    spirit_available = (
        _num(build.get("spiritAvailable")) if build.get("spiritAvailable") is not None else None
    )
    spirit_ok = (
        True if spirit_used is None or spirit_available is None else spirit_used <= spirit_available
    )
    if not spirit_ok:
        failures.append("spirit_budget_exceeded")

    if source_context == "trusted_reference":
        relaxed = {
            "passive_budget_exceeded": "external_passive_budget_anomaly_caveat",
            "weapon_set_budget_exceeded": "external_weapon_set_budget_anomaly_caveat",
            "attribute_requirement_unmet": (
                "trusted_reference_attribute_requirement_mismatch_caveat"
            ),
        }
        for failure, caveat in relaxed.items():
            if failure in failures:
                failures = [item for item in failures if item != failure]
                caveats.append(caveat)

    failures = _dedupe(failures)
    caveats = _dedupe(caveats)
    return {
        "auditVersion": AUDIT_VERSION,
        "status": "passed" if not failures else "blocked",
        "hardLegalityReady": not failures,
        "hardFailures": failures,
        "caveats": caveats,
        "checks": {
            "classAscendancy": class_check,
            "attributes": {
                "ok": not shortfalls,
                "shortfalls": shortfalls,
            },
            "equippedItemRequirements": item_requirements,
            "activeGemRequirements": active_gem_requirements,
            "weaponCompatibility": weapon_check,
            "spiritBudget": {
                "ok": spirit_ok,
                "used": spirit_used,
                "available": spirit_available,
                "over": (
                    max(0.0, spirit_used - spirit_available)
                    if spirit_used is not None and spirit_available is not None
                    else None
                ),
            },
            "passiveBudget": passive_budget,
            "weaponSetBudget": weapon_set_budget,
            "equippedItemAffixes": item_affixes,
        },
        "sourceContext": source_context,
        "noRawMaterial": True,
    }


def compare_audits_for_regression(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Return deterministic legality failures introduced or worsened by a candidate delta.

    Item probes often run against a deliberately incomplete diagnostic build.  A pre-existing
    failure must stay visible, but it must not be misattributed to an unrelated item candidate.
    Conversely, a candidate that introduces a new failure or worsens an existing measurable
    shortfall is rejected.
    """

    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    before_failures = {str(value) for value in before.get("hardFailures") or []}
    after_failures = [str(value) for value in after.get("hardFailures") or []]
    reasons: list[dict[str, Any]] = []

    for failure in after_failures:
        if failure not in before_failures:
            reasons.append({"code": failure, "change": "introduced"})

    before_checks = before.get("checks") if isinstance(before.get("checks"), dict) else {}
    after_checks = after.get("checks") if isinstance(after.get("checks"), dict) else {}

    if "attribute_requirement_unmet" in before_failures and (
        "attribute_requirement_unmet" in after_failures
    ):
        before_shortfalls = _attribute_shortfall_map(before_checks)
        after_shortfalls = _attribute_shortfall_map(after_checks)
        for attribute, after_shortfall in after_shortfalls.items():
            before_shortfall = before_shortfalls.get(attribute, 0.0)
            if after_shortfall > before_shortfall + 1e-9:
                reasons.append(
                    {
                        "code": "attribute_requirement_unmet",
                        "change": "worsened",
                        "attribute": attribute,
                        "beforeShortfall": before_shortfall,
                        "afterShortfall": after_shortfall,
                    }
                )

    measurable_failures = {
        "spirit_budget_exceeded": ("spiritBudget", "over"),
        "passive_budget_exceeded": ("passiveBudget", "over"),
        "weapon_set_budget_exceeded": ("weaponSetBudget", "overMax"),
    }
    for failure, (check_name, value_name) in measurable_failures.items():
        if failure not in before_failures or failure not in after_failures:
            continue
        before_over = _num(_check_value(before_checks, check_name, value_name))
        after_over = _num(_check_value(after_checks, check_name, value_name))
        if after_over > before_over + 1e-9:
            reasons.append(
                {
                    "code": failure,
                    "change": "worsened",
                    "beforeOver": before_over,
                    "afterOver": after_over,
                }
            )

    list_failures = {
        "equipped_item_level_requirement_unmet": (
            "equippedItemRequirements",
            "underlevelledSlots",
        ),
        "active_skill_gem_level_requirement_unmet": (
            "activeGemRequirements",
            "violations",
        ),
        "illegal_equipped_item_affixes": (
            "equippedItemAffixes",
            "invalidSlots",
        ),
    }
    for failure, (check_name, value_name) in list_failures.items():
        if failure not in before_failures or failure not in after_failures:
            continue
        before_entries = _stable_entry_set(_check_value(before_checks, check_name, value_name))
        after_entries = _stable_entry_set(_check_value(after_checks, check_name, value_name))
        introduced = sorted(after_entries - before_entries)
        if introduced:
            reasons.append(
                {
                    "code": failure,
                    "change": "worsened",
                    "introducedViolations": introduced,
                }
            )

    weapon_failures = {
        failure
        for failure in after_failures
        if "weapon" in failure or failure == "physical_skill_invalid"
    }
    for failure in sorted(weapon_failures & before_failures):
        before_weapon = before_checks.get("weaponCompatibility")
        after_weapon = after_checks.get("weaponCompatibility")
        if _stable_json(before_weapon) != _stable_json(after_weapon):
            reasons.append({"code": failure, "change": "worsened"})

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for reason in reasons:
        marker = _stable_json(reason)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(reason)
    return {
        "regressed": bool(deduped),
        "reasons": deduped,
        "preExistingHardFailures": sorted(before_failures),
        "remainingHardFailures": after_failures,
    }


def augment_build_with_snapshot_gear(
    build: Any,
    xml: str,
    *,
    item_legality_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    output = dict(build) if isinstance(build, dict) else {}
    try:
        gear = completeness.equipped_item_metadata(
            xml,
            require_special_provenance=True,
        )
    except Exception:  # noqa: BLE001 - missing metadata remains unknown, never guessed.
        gear = {}
    if gear and item_legality_overrides:
        for slot, legality in item_legality_overrides.items():
            if slot in gear and isinstance(legality, dict):
                gear[slot] = {**gear[slot], "affixLegality": dict(legality)}
    if gear:
        output["gear"] = gear
    return output


def evaluation_skill_group(build: dict[str, Any]) -> list[dict[str, Any]] | None:
    selected = build.get("judgeSelectedSkill") or {}
    selected_group = build.get("judgeSelectedSkillGroup")
    if (
        isinstance(selected, dict)
        and _has_judge_selected_skill(selected)
        and selected.get("socketLegalityApplicable") is not False
        and isinstance(selected_group, list)
    ):
        return selected_group
    return build.get("mainSkillGroup")


def evaluation_weapon_check(build: dict[str, Any]) -> dict[str, Any] | None:
    selected = build.get("judgeSelectedSkill") or {}
    if isinstance(selected, dict) and _has_judge_selected_skill(selected):
        check = selected.get("weaponCheck")
        if isinstance(check, dict):
            return check
    check = build.get("mainSkillWeaponCheck") or build.get("weaponCheck")
    return check if isinstance(check, dict) else None


def attribute_shortfalls(build: dict[str, Any]) -> list[dict[str, Any]]:
    attrs = build.get("attributes") or build.get("attributeTotals") or {}
    reqs = build.get("attributeRequirements") or {}
    if not isinstance(attrs, dict) or not isinstance(reqs, dict):
        return []
    aliases = {
        "strength": ("strength", "str", "Str"),
        "dexterity": ("dexterity", "dex", "Dex"),
        "intelligence": ("intelligence", "int", "Int"),
    }
    output: list[dict[str, Any]] = []
    for attribute, keys in aliases.items():
        required = _first_present_number(reqs, keys)
        if required <= 0:
            continue
        available = _first_present_number(attrs, keys)
        if available < required:
            output.append(
                {
                    "attribute": attribute,
                    "available": available,
                    "required": required,
                    "shortfall": required - available,
                }
            )
    return output


def check_passive_budget(
    build: dict[str, Any],
    *,
    source_context: str = "generated_candidate",
) -> dict[str, Any]:
    used = _normal_passive_points_used(build)
    available = _num(build.get("pointsAvailable"))
    base = {"used": used, "available": available, "over": max(0.0, used - available)}
    if used <= available:
        return {"ok": True, **base}
    over = used - available
    if _allows_current_league_extra_passive_point(build, over):
        return {
            "ok": True,
            **base,
            "over": over,
            "leagueExtraApplied": 1,
            "caveat": "league_extra_passive_point_caveat",
        }
    if _allows_imported_tree_budget_mismatch(build, over, source_context):
        return {
            "ok": True,
            **base,
            "over": over,
            "importedMismatchAllowed": int(over),
            "caveat": "imported_tree_budget_mismatch_caveat",
        }
    return {"ok": False, **base, "failure": "passive_budget_exceeded"}


def check_weapon_set_budget(
    build: dict[str, Any],
    *,
    source_context: str = "generated_candidate",
) -> dict[str, Any]:
    available = build.get("weaponSetPointsAvailable")
    if available is None:
        return {"ok": True, "available": None}
    cap = _num(available)
    set1 = _num(build.get("weaponSet1PointsUsed"))
    set2 = _num(build.get("weaponSet2PointsUsed"))
    over_max = max(0.0, set1 - cap, set2 - cap)
    base = {
        "available": cap,
        "weaponSet1Used": set1,
        "weaponSet2Used": set2,
        "overMax": over_max,
    }
    if over_max > 0 and _allows_imported_weapon_set_budget_mismatch(
        build, over_max, source_context
    ):
        return {
            "ok": True,
            **base,
            "importedMismatchAllowed": int(round(over_max)),
            "caveat": "imported_weapon_set_budget_mismatch_caveat",
        }
    return {
        "ok": over_max <= 0,
        **base,
        **({"failure": "weapon_set_budget_exceeded"} if over_max > 0 else {}),
    }


def _has_judge_selected_skill(selected: dict[str, Any]) -> bool:
    if _num(selected.get("dps")) > 0 or selected.get("weaponCheck"):
        return True
    tags = {str(tag) for tag in selected.get("tags") or []}
    return bool(tags & {"Attack", "Spell", "Damage", "DamageOverTime", "Minion"})


def _normal_passive_points_used(build: dict[str, Any]) -> float:
    if build.get("normalPassivePointsUsed") is not None:
        return _num(build.get("normalPassivePointsUsed"))
    used = _num(build.get("pointsUsed"))
    weapon_1 = _num(build.get("weaponSet1PointsUsed"))
    weapon_2 = _num(build.get("weaponSet2PointsUsed"))
    if weapon_1 or weapon_2:
        return used - min(weapon_1, weapon_2)
    return used


def _allows_current_league_extra_passive_point(build: dict[str, Any], over: float) -> bool:
    if abs(over - 1.0) > 1e-9 or int(_num(build.get("level"))) < 91:
        return False
    tree_version = str(build.get("treeVersion") or "")
    latest_tree_version = str(build.get("latestTreeVersion") or "")
    return tree_version == "0_5" and not (
        latest_tree_version and tree_version != latest_tree_version
    )


def _allows_imported_tree_budget_mismatch(
    build: dict[str, Any],
    over: float,
    source_context: str,
) -> bool:
    if source_context != "trusted_reference" or int(_num(build.get("level"))) < 100:
        return False
    if abs(over - round(over)) > 1e-9 or over <= 0 or over > 2:
        return False
    tree_version = build.get("treeVersion")
    latest_tree_version = build.get("latestTreeVersion")
    return not (tree_version and latest_tree_version and tree_version != latest_tree_version)


def _allows_imported_weapon_set_budget_mismatch(
    build: dict[str, Any],
    over: float,
    source_context: str,
) -> bool:
    return _allows_imported_tree_budget_mismatch(build, over, source_context)


def _first_present_number(values: dict[str, Any], keys: tuple[str, ...]) -> float:
    for key in keys:
        if key in values:
            return _num(values.get(key))
    return 0.0


def _attribute_shortfall_map(checks: dict[str, Any]) -> dict[str, float]:
    attributes = checks.get("attributes") if isinstance(checks, dict) else None
    rows = attributes.get("shortfalls") if isinstance(attributes, dict) else None
    output: dict[str, float] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("attribute"):
            continue
        output[str(row["attribute"])] = _num(row.get("shortfall"))
    return output


def _check_value(checks: dict[str, Any], check_name: str, value_name: str) -> Any:
    check = checks.get(check_name) if isinstance(checks, dict) else None
    return check.get(value_name) if isinstance(check, dict) else None


def _stable_entry_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {_stable_json(row) for row in value}


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
