"""Advisory completeness diagnostics for Agent-created active builds."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from server.knowledge import item_legality, itemparse
from server.judge import rules

from .engine import PobEngine

_FLASK_SLOTS = ("Flask 1", "Flask 2")
_CHARM_SLOTS = ("Charm 1", "Charm 2", "Charm 3")
_EQUIPMENT_SLOTS = {
    "Weapon 1",
    "Weapon 2",
    "Helmet",
    "Body Armour",
    "Gloves",
    "Boots",
    "Belt",
    "Amulet",
    "Ring 1",
    "Ring 2",
}
_RUNE_RELEVANT_SLOTS = {
    "Weapon 1",
    "Weapon 2",
    "Helmet",
    "Body Armour",
    "Gloves",
    "Boots",
}
def spirit_opportunity_review_required(build: dict[str, Any]) -> bool:
    """Return a factual low-utilization signal without deciding what the build should reserve."""

    available = build.get("spiritAvailable")
    requested = build.get("spiritRequested")
    if isinstance(available, bool) or not isinstance(available, int | float) or available <= 0:
        return False
    if isinstance(requested, bool) or not isinstance(requested, int | float):
        return False
    return (
        max(0.0, float(requested)) / float(available)
        <= rules.SPIRIT_OPPORTUNITY_REVIEW_THRESHOLD
    )


def inspect_build_completeness(
    engine: PobEngine,
    *,
    snapshot_xml: str | None = None,
) -> dict[str, Any]:
    """Describe omitted real-build systems without deciding the build on the Agent's behalf."""
    build = engine.get_build()
    gear = equipped_item_metadata(snapshot_xml if snapshot_xml is not None else engine.get_xml())
    if not gear:
        fallback = build.get("gear") or {}
        gear = fallback if isinstance(fallback, dict) else {}
    level = int(build.get("level") or 0)
    active_gem_level_violations = [
        dict(row)
        for row in (build.get("activeSkillGemLevelViolations") or [])
        if isinstance(row, dict)
    ]

    rarity_counts: dict[str, int] = {}
    missing_item_levels: list[str] = []
    underlevelled: list[dict[str, Any]] = []
    scaffold_slots: list[str] = []
    rune_socketed_slots: list[str] = []
    rune_decision_slots: list[str] = []
    illegal_affix_slots: list[dict[str, Any]] = []
    unverified_special_source_slots: list[str] = []
    for slot, item in gear.items():
        if not isinstance(item, dict):
            continue
        rarity = str(item.get("rarity") or "unknown").lower()
        rarity_counts[rarity] = rarity_counts.get(rarity, 0) + 1
        if (
            slot in _EQUIPMENT_SLOTS
            and rarity in {"rare", "magic"}
            and item.get("itemLevel") is None
        ):
            missing_item_levels.append(str(slot))
        required = item.get("levelRequirement")
        if isinstance(required, (int, float)) and required > level:
            underlevelled.append(
                {"slot": str(slot), "requiredLevel": int(required), "characterLevel": level}
            )
        if item.get("isScaffold"):
            scaffold_slots.append(str(slot))
        legality = item.get("affixLegality")
        if isinstance(legality, dict) and legality.get("ok") is False:
            illegal_affix_slots.append(
                {"slot": str(slot), "issues": list(legality.get("issues") or [])}
            )
        if isinstance(legality, dict) and legality.get("provenanceStatus") == "unverified":
            unverified_special_source_slots.append(str(slot))
        if slot in _RUNE_RELEVANT_SLOTS:
            socket_capacity = int(item.get("runeSockets") or 0)
            filled_sockets = int(item.get("verifiedRuneCount") or 0)
            if socket_capacity > 0 and filled_sockets >= socket_capacity:
                rune_socketed_slots.append(str(slot))
            else:
                rune_decision_slots.append(str(slot))

    sockets = engine.list_jewel_sockets().get("sockets") or []
    allocated_sockets = [
        entry for entry in sockets if isinstance(entry, dict) and entry.get("allocated")
    ]
    filled_sockets = [entry for entry in allocated_sockets if entry.get("filled")]

    belt = gear.get("Belt") if isinstance(gear.get("Belt"), dict) else {}
    belt_charm_capacity = (belt or {}).get("charmSlots")
    effective_charm_capacity = build.get("charmLimit")
    if not isinstance(effective_charm_capacity, (int, float)):
        effective_charm_capacity = belt_charm_capacity
    charm_capacity = (
        max(0, min(3, int(effective_charm_capacity)))
        if isinstance(effective_charm_capacity, (int, float))
        else None
    )
    equipped_charms = [slot for slot in _CHARM_SLOTS if slot in gear]
    equipped_flasks = [slot for slot in _FLASK_SLOTS if slot in gear]
    flask_details = [
        {
            "slot": slot,
            "rarity": str((gear.get(slot) or {}).get("rarity") or "unknown").lower(),
            "prefixes": int((gear.get(slot) or {}).get("affixPrefixes") or 0),
            "suffixes": int((gear.get(slot) or {}).get("affixSuffixes") or 0),
        }
        for slot in equipped_flasks
        if isinstance(gear.get(slot), dict)
    ]

    advisories: list[str] = []
    if scaffold_slots:
        advisories.append("scaffold_gear_must_be_replaced")
    if missing_item_levels:
        advisories.append("rare_or_magic_item_level_missing")
    if rune_decision_slots:
        advisories.append("rune_or_soul_core_decision_missing")
    if not allocated_sockets:
        advisories.append("passive_jewel_not_planned")
    elif len(filled_sockets) < len(allocated_sockets):
        advisories.append("allocated_passive_jewel_socket_empty")
    if len(equipped_flasks) < len(_FLASK_SLOTS):
        advisories.append("flask_loadout_incomplete")
    if level >= 80 and any(
        item["rarity"] == "magic" and (item["prefixes"] == 0 or item["suffixes"] == 0)
        for item in flask_details
    ):
        advisories.append("endgame_flask_affix_slot_open")
    if "Belt" in gear and belt_charm_capacity is None:
        advisories.append("charm_capacity_missing_property")
    if charm_capacity is not None and charm_capacity > len(equipped_charms):
        advisories.append("available_charm_slots_unfilled")
    if level >= 90 and charm_capacity is not None and charm_capacity < 3:
        advisories.append("endgame_charm_capacity_below_target")
    if charm_capacity is not None and equipped_charms and charm_capacity < len(equipped_charms):
        advisories.append("equipped_charms_exceed_effective_capacity")
    if unverified_special_source_slots:
        advisories.append("special_item_source_unverified")
    if spirit_opportunity_review_required(build):
        advisories.append("spirit_opportunity_review_required")

    hard_failures = ["equipped_item_level_requirement_unmet"] if underlevelled else []
    if active_gem_level_violations:
        hard_failures.append("active_skill_gem_level_requirement_unmet")
    if illegal_affix_slots:
        hard_failures.append("illegal_equipped_item_affixes")
    if charm_capacity is not None and len(equipped_charms) > charm_capacity:
        hard_failures.append("equipped_charms_exceed_effective_capacity")
    return {
        "status": "complete" if not hard_failures and not advisories else "needs_attention",
        "hardFailures": hard_failures,
        "advisories": advisories,
        "rarityCounts": rarity_counts,
        "missingItemLevelSlots": missing_item_levels,
        "underlevelledItems": underlevelled,
        "activeSkillGemLevelViolations": active_gem_level_violations,
        "illegalAffixItems": illegal_affix_slots,
        "unverifiedSpecialSourceSlots": unverified_special_source_slots,
        "scaffoldSlots": scaffold_slots,
        "runes": {
            "socketedSlots": rune_socketed_slots,
            "decisionRequiredSlots": rune_decision_slots,
            "details": [
                {
                    "slot": str(slot),
                    "socketCapacity": int(item.get("runeSockets") or 0),
                    "declaredRuneCount": len(item.get("runes") or []),
                    "filledSockets": int(item.get("verifiedRuneCount") or 0),
                    "runeProvenanceStatus": item.get("runeProvenanceStatus"),
                }
                for slot, item in gear.items()
                if slot in _RUNE_RELEVANT_SLOTS and isinstance(item, dict)
            ],
        },
        "passiveJewels": {
            "availableSockets": len(sockets),
            "allocatedSockets": len(allocated_sockets),
            "filledSockets": len(filled_sockets),
        },
        "flasks": {
            "equippedSlots": equipped_flasks,
            "expectedSlots": list(_FLASK_SLOTS),
            "details": flask_details,
        },
        "charms": {
            "beltCapacity": charm_capacity,
            "beltPropertyCapacity": belt_charm_capacity,
            "equippedSlots": equipped_charms,
        },
        "note": (
            "Advisory completeness report. Explicit item, active-gem, and affix legality "
            "violations are hard "
            "failures; rune, jewel, flask and charm choices remain Agent design decisions."
        ),
    }


def equipped_item_metadata(
    xml: str,
    *,
    require_special_provenance: bool = False,
) -> dict[str, dict[str, Any]]:
    """Read only active-slot item metadata from PoB XML; raw item text never leaves this module."""
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, TypeError):
        return {}
    items = root.find("Items")
    if items is None:
        return {}
    by_id = {
        str(item.get("id")): item.text or "" for item in items.findall("Item") if item.get("id")
    }
    active_id = str(items.get("activeItemSet") or "1")
    item_set = next(
        (node for node in items.findall("ItemSet") if str(node.get("id")) == active_id),
        None,
    )
    if item_set is None:
        return {}
    gear: dict[str, dict[str, Any]] = {}
    for slot in item_set.findall("Slot"):
        item_id = str(slot.get("itemId") or "0")
        slot_name = str(slot.get("name") or "")
        if item_id != "0" and slot_name and item_id in by_id:
            gear[slot_name] = _parse_item_text(
                by_id[item_id],
                slot=slot_name,
                require_special_provenance=require_special_provenance,
            )
    return gear


def equipped_item_text(xml: str, slot_name: str) -> str | None:
    """Return one private active-slot item text for internal receipt canonicalization only."""

    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, TypeError):
        return None
    items = root.find("Items")
    if items is None:
        return None
    active_id = str(items.get("activeItemSet") or "1")
    item_set = next(
        (node for node in items.findall("ItemSet") if str(node.get("id")) == active_id),
        None,
    )
    if item_set is None:
        return None
    slot = next(
        (node for node in item_set.findall("Slot") if str(node.get("name") or "") == slot_name),
        None,
    )
    if slot is None:
        return None
    item_id = str(slot.get("itemId") or "0")
    item = next(
        (node for node in items.findall("Item") if str(node.get("id") or "") == item_id),
        None,
    )
    return item.text or "" if item is not None else None


def artifact_blockers(xml: str) -> list[str]:
    """Return structural equipment omissions that can never be a final playable artifact."""
    gear = equipped_item_metadata(xml, require_special_provenance=True)
    blockers: list[str] = []
    if any(item.get("isScaffold") for item in gear.values()):
        blockers.append("final_artifact_contains_scaffold_gear")
    if any(
        str(item.get("rarity") or "").lower() in {"rare", "magic"} and item.get("itemLevel") is None
        for slot, item in gear.items()
        if slot in _EQUIPMENT_SLOTS
    ):
        blockers.append("final_artifact_item_level_missing")
    if any(item.get("affixLegality", {}).get("ok") is False for item in gear.values()):
        blockers.append("final_artifact_illegal_affixes")
    belt = gear.get("Belt")
    if isinstance(belt, dict) and belt.get("charmSlots") is None:
        blockers.append("final_artifact_charm_slots_missing")
    return blockers


def _parse_item_text(
    raw: str,
    *,
    slot: str | None = None,
    require_special_provenance: bool = False,
) -> dict[str, Any]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    parsed = itemparse.parse_item(raw)
    rarity = parsed.get("rarity") or _matched_value(lines, r"^Rarity:\s*(\S+)")
    name = str(parsed.get("name") or "")
    base = str(parsed.get("base") or "")
    item_level = parsed.get("itemLevel")
    required_level = _matched_int(lines, r"^LevelReq:\s*(\d+)")
    charm_slots = _matched_int(lines, r"^Charm Slots:\s*(\d+)")
    socket_line = _matched_value(lines, r"^Sockets:\s*(.*)") or ""
    runes = [value for line in lines if (value := _line_value(line, r"^Rune:\s*(.+)"))]
    legality = item_legality.audit_item(
        raw,
        slot=slot,
        require_special_provenance=require_special_provenance,
    )
    verified_rune_count = (
        min(
            len(runes),
            int((legality.get("specialSources") or {}).get("runeCount") or 0),
        )
        if legality.get("provenanceStatus") == "verified"
        else 0
    )
    top_tier_affixes = sum(
        1
        for affix in parsed.get("affixes") or []
        if isinstance(affix, dict)
        and affix.get("tier") == 1
        and int(affix.get("totalTiers") or 0) >= 4
    )
    return {
        "name": name,
        "base": base,
        "rarity": rarity,
        "itemLevel": item_level,
        "levelRequirement": required_level,
        "runeSockets": sum(1 for token in socket_line.split() if token == "S"),
        "runes": runes,
        "verifiedRuneCount": verified_rune_count,
        "runeProvenanceStatus": legality.get("provenanceStatus"),
        "itemFingerprint": itemparse.semantic_item_structure(raw).get("itemFingerprint"),
        "charmSlots": charm_slots,
        "isScaffold": name.startswith("Scaffold "),
        "affixPrefixes": int(legality.get("prefixes") or 0),
        "affixSuffixes": int(legality.get("suffixes") or 0),
        "affixLegality": legality,
        "topTierAffixes": top_tier_affixes,
    }


def _matched_value(lines: list[str], pattern: str) -> str | None:
    for line in lines:
        value = _line_value(line, pattern)
        if value is not None:
            return value
    return None


def _line_value(line: str, pattern: str) -> str | None:
    match = re.match(pattern, line, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _matched_int(lines: list[str], pattern: str) -> int | None:
    value = _matched_value(lines, pattern)
    return int(value) if value is not None else None
