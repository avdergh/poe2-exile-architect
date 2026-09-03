"""Hard legality checks for the Phase 1 judge."""

from __future__ import annotations

from collections import Counter
from typing import Any

MAX_SUPPORTS_PER_SKILL_V1 = 5
ENDGAME_RESISTANCE_MIN_LEVEL = 80
ENDGAME_ELEMENTAL_RESISTANCE_MINIMUM = 60.0
ENDGAME_CHAOS_RESISTANCE_MINIMUM = 30.0
SPIRIT_OPPORTUNITY_REVIEW_THRESHOLD = 0.80

CLASS_ASCENDANCY_PAIRS_V1: dict[str, set[str]] = {
    "Ranger": {"Deadeye", "Pathfinder"},
    "Huntress": {"Amazon", "Spirit Walker", "Ritualist"},
    "Warrior": {"Titan", "Warbringer", "Smith of Kitava"},
    "Mercenary": {"Tactician", "Witchhunter", "Gemling Legionnaire"},
    "Druid": {"Oracle", "Shaman"},
    "Witch": {"Infernalist", "Blood Mage", "Lich", "Abyssal Lich"},
    "Sorceress": {"Stormweaver", "Chronomancer", "Disciple of Varashta"},
    "Monk": {"Martial Artist", "Invoker", "Acolyte of Chayula"},
}

DEFAULT_KNOWN_SUPPORTS_V1 = {
    "Arcane Tempo",
    "Brutality",
    "Controlled Destruction",
    "Considered Casting",
    "Concentrated Effect",
    "Elemental Focus",
    "Execute",
    "Fast Forward",
    "Glaciation",
    "Heft",
    "Inspiration",
    "Lightning Infusion",
    "Martial Tempo",
    "Overabundance",
    "Persistence",
    "Primal Armament",
    "Scattershot",
    "Unleash",
    "Wildshards",
}

# PoE2 meta/invocation hosts intentionally share a socket group with one or more payload active
# skills. Treating every multi-active group as malformed silently rewrites valid in-game builds to
# fit PoB's simpler calculation model. This list is a structural legality allow-list only; it does
# not claim that PoB can calculate the host's trigger rate or the payload's true damage.
META_SKILL_HOSTS_V1 = {
    "Ancestral Warrior Totem",
    "Animus Splinters",
    "Cast on Critical",
    "Cast on Block",
    "Cast on Charm Use",
    "Cast on Death",
    "Cast on Dodge",
    "Cast on Elemental Ailment",
    "Cast on Freeze",
    "Cast on Ignite",
    "Cast on Melee Kill",
    "Cast on Melee Stun",
    "Cast on Minion Death",
    "Cast on Shock",
    "Cast when Damage Taken",
    "Cast when Stunned",
    "Cast while Channelling",
    "Barrier Invocation",
    "Blasphemy",
    "Called Shots",
    "Curse on Block",
    "Demon Magus",
    "Elemental Invocation",
    "Feral Invocation",
    "Ferocious Roar",
    "Fire Spell on Hit",
    "Hand of Chayula",
    "Hollow Form",
    "Hydra Familiar",
    "Mirage Archer",
    "Mirage Deadeye",
    "Mortar Cannon",
    "Pounce",
    "Reaper's Invocation",
    "Spell Totem",
    "Spellslinger",
    "Spirit Vessel",
    "Summon Companion",
    "Thundergod's Wrath",
}

PHYSICAL_INVALID_FAILURES = {
    "invalid_class_ascendancy_pairing",
    "invalid_socket_setup",
    "support_limit_exceeded",
    "duplicate_support_gem",
    "invalid_support_gem",
    "attribute_requirement_unmet",
    "equipped_item_level_requirement_unmet",
    "active_skill_gem_level_requirement_unmet",
    "illegal_equipped_item_affixes",
    "incompatible_weapon_skill_tags",
    "attack_skill_without_weapon",
    "passive_budget_exceeded",
    "weapon_set_budget_exceeded",
    "spirit_budget_exceeded",
}


def check_endgame_resistance_gate(
    *,
    level: int | float | None,
    resistances: dict[str, Any] | None,
    keystones: list[str] | None = None,
    source_context: str = "generated_candidate",
) -> dict[str, Any]:
    """Return the deterministic generated-candidate resistance gate for level 80+ builds."""

    numeric_level = int(level or 0)
    applicable = source_context == "generated_candidate" and numeric_level >= (
        ENDGAME_RESISTANCE_MIN_LEVEL
    )
    values = {
        key: _resistance_value((resistances or {}).get(key))
        for key in ("fire", "cold", "lightning", "chaos")
    }
    ci_active = "chaos inoculation" in {
        str(keystone).strip().casefold() for keystone in (keystones or [])
    }
    below_elemental = [
        key
        for key in ("fire", "cold", "lightning")
        if values[key] is None or values[key] < ENDGAME_ELEMENTAL_RESISTANCE_MINIMUM
    ]
    chaos_below = not ci_active and (
        values["chaos"] is None or values["chaos"] < ENDGAME_CHAOS_RESISTANCE_MINIMUM
    )
    failures: list[str] = []
    if applicable and below_elemental:
        failures.append("endgame_elemental_resistance_below_60")
    if applicable and chaos_below:
        failures.append("endgame_chaos_resistance_below_30")
    return {
        "status": "not_applicable" if not applicable else ("blocked" if failures else "passed"),
        "applicable": applicable,
        "minimumLevel": ENDGAME_RESISTANCE_MIN_LEVEL,
        "thresholds": {
            "fire": ENDGAME_ELEMENTAL_RESISTANCE_MINIMUM,
            "cold": ENDGAME_ELEMENTAL_RESISTANCE_MINIMUM,
            "lightning": ENDGAME_ELEMENTAL_RESISTANCE_MINIMUM,
            "chaos": ENDGAME_CHAOS_RESISTANCE_MINIMUM,
        },
        "observed": values,
        "belowElemental": below_elemental if applicable else [],
        "chaosInoculation": ci_active,
        "chaosBelowMinimum": bool(applicable and chaos_below),
        "hardFailures": failures,
    }


def check_equipped_item_requirements(build: dict[str, Any]) -> dict[str, Any]:
    """Check requirements PoB exposes for equipped items without guessing item legality."""
    level = int(build.get("level") or 0)
    gear = build.get("gear") or {}
    if not isinstance(gear, dict):
        return {"ok": True, "underlevelledSlots": []}
    underlevelled: list[dict[str, Any]] = []
    for slot, item in gear.items():
        if not isinstance(item, dict):
            continue
        required = item.get("levelRequirement")
        if isinstance(required, (int, float)) and required > level:
            underlevelled.append(
                {"slot": str(slot), "requiredLevel": int(required), "characterLevel": level}
            )
    return {"ok": not underlevelled, "underlevelledSlots": underlevelled}


def check_active_skill_gem_requirements(build: dict[str, Any]) -> dict[str, Any]:
    """Check base active-gem levels against pinned PoB's character-level requirements.

    The bridge reports the socketed base gem level, so item/passive ``+levels`` do not create a
    false failure.  Older/synthetic readbacks without this field remain unknown instead of being
    guessed from skill names.
    """
    raw = build.get("activeSkillGemLevelViolations") or []
    violations = (
        [dict(row) for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    )
    return {"ok": not violations, "violations": violations}


def check_equipped_item_affixes(build: dict[str, Any]) -> dict[str, Any]:
    """Reject deterministic rare/magic affix impossibilities reported by completeness parsing."""
    gear = build.get("gear") or {}
    invalid: list[dict[str, Any]] = []
    if isinstance(gear, dict):
        for slot, item in gear.items():
            legality = item.get("affixLegality") if isinstance(item, dict) else None
            if isinstance(legality, dict) and legality.get("ok") is False:
                invalid.append({"slot": str(slot), "issues": list(legality.get("issues") or [])})
    return {"ok": not invalid, "invalidSlots": invalid}


def support_completeness_caveats(
    group: list[dict[str, Any]] | None,
    *,
    level: int,
    source_context: str,
) -> list[str]:
    """Flag suspiciously sparse late-campaign links without declaring them illegal."""
    if source_context != "generated_candidate" or level < 50:
        return []
    supports = [gem for gem in group or [] if _is_support(gem, DEFAULT_KNOWN_SUPPORTS_V1)]
    return ["main_skill_support_setup_incomplete_caveat"] if len(supports) <= 1 else []


def check_class_ascendancy(
    class_name: str | None,
    ascendancy: str | None,
    *,
    level_band: str = "endgame",
) -> dict[str, Any]:
    cls = (class_name or "").strip()
    asc = (ascendancy or "").strip()
    if asc.casefold() in {"none", "nil"}:
        asc = ""
    if not cls:
        return {
            "ok": False,
            "failureCode": "invalid_class_ascendancy_pairing",
            "detail": "class is required for judge evaluation",
        }
    if not asc:
        if level_band != "endgame":
            return {"ok": True, "caveat": "missing_ascendancy_non_endgame_caveat"}
        return {
            "ok": False,
            "failureCode": "invalid_class_ascendancy_pairing",
            "detail": "ascendancy is required for endgame judge evaluation",
        }
    allowed = CLASS_ASCENDANCY_PAIRS_V1.get(cls)
    if not allowed or asc not in allowed:
        return {
            "ok": False,
            "failureCode": "invalid_class_ascendancy_pairing",
            "detail": f"{asc} is not a known PoE2 ascendancy for {cls}",
        }
    return {"ok": True}


def _is_support(gem: dict[str, Any], known_supports: set[str]) -> bool:
    if str(gem.get("name") or "").strip() in META_SKILL_HOSTS_V1:
        return False
    if "isSupport" in gem:
        return bool(gem.get("isSupport"))
    name = str(gem.get("name") or "")
    return name in known_supports or "support" in name.lower()


def check_main_skill_group(
    group: list[dict[str, Any]] | None,
    *,
    known_supports: set[str] | None = None,
    strict_active_skill_count: bool = True,
) -> tuple[list[str], list[str]]:
    known = known_supports or DEFAULT_KNOWN_SUPPORTS_V1
    gems = list(group or [])
    failures: list[str] = []
    # Structural checks below do not prove support applicability, but an unconditional caveat on
    # every valid group is not actionable. Concrete unknown/duplicate/disabled states are reported
    # by their specific failures or PoB readback diagnostics.
    caveats: list[str] = []

    active = [g for g in gems if not _is_support(g, known)]
    supports = [g for g in gems if _is_support(g, known)]
    active_names = [str(g.get("name") or "").strip() for g in active]
    valid_active_composition = is_valid_active_skill_group(active_names)
    if not valid_active_composition and strict_active_skill_count:
        failures.append("invalid_socket_setup")
    elif not valid_active_composition:
        caveats.append("external_multi_active_socket_group_caveat")
    if len(supports) > MAX_SUPPORTS_PER_SKILL_V1:
        failures.append("support_limit_exceeded")

    names = [str(g.get("name") or "").strip() for g in supports]
    support_counts = Counter(n for n in names if n)
    if any(count > 1 for count in support_counts.values()):
        failures.append("duplicate_support_gem")
    if any(not _support_known(g, known) for g in supports):
        failures.append("invalid_support_gem")

    return _dedupe(failures), caveats


def is_valid_active_skill_group(active_names: list[str] | tuple[str, ...] | None) -> bool:
    """Accept one ordinary active or one current payload host plus its socketed active(s).

    This checks the socket-group shape only, not every host-to-payload tag restriction. PoB
    modelability is reported separately and must never be used to delete a valid composition.
    """

    names = [str(name).strip() for name in (active_names or []) if str(name).strip()]
    if len(names) == 1:
        return True
    hosts = [name for name in names if name in META_SKILL_HOSTS_V1]
    return len(names) >= 2 and len(hosts) == 1


def check_weapon_skill_compatibility(check: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(check, dict) or not check:
        return {"ok": True}
    reason = str(check.get("disableReason") or "").strip()
    compatible = check.get("compatible")
    if reason or compatible is False:
        skill = str(check.get("skillName") or "selected skill")
        required = _string_list(check.get("weaponTypes"))
        equipped = _string_list(check.get("equippedWeaponTypes"))
        return {
            "ok": False,
            "failureCode": "incompatible_weapon_skill_tags",
            "detail": (
                f"{skill} is not usable with equipped weapons"
                f" (requires {required or 'unknown'}, equipped {equipped or 'none'}"
                f"{': ' + reason if reason else ''})"
            ),
        }
    return {"ok": True}


def blocked_score_dimensions(failures: set[str] | list[str]) -> set[str]:
    if set(failures) & PHYSICAL_INVALID_FAILURES:
        return {"offense", "defense", "recovery", "mobility"}
    return set()


def physical_invalid_failures(failures: list[str]) -> list[str]:
    return [f for f in _dedupe(failures) if f in PHYSICAL_INVALID_FAILURES]


def _support_known(gem: dict[str, Any], known_supports: set[str]) -> bool:
    name = str(gem.get("name") or "").strip()
    return bool(gem.get("supportKnown") or name in known_supports)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _resistance_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if value:
        return [str(value)]
    return []
