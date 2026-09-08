"""PoB-sourced augment quotas shared by probes, equipment transactions and Judge."""

from __future__ import annotations

from collections import Counter
from typing import Any
import xml.etree.ElementTree as ET

from server.knowledge import itemparse
from server.runtime import craft_receipts


def constraints(option: dict[str, Any]) -> list[dict[str, Any]]:
    result: dict[str, int] = {}
    for row in option.get("constraints") or []:
        if not isinstance(row, dict):
            raise ValueError("invalid_socket_limit")
        group, limit = row.get("group"), row.get("limit")
        if (
            not isinstance(group, str)
            or not group.strip()
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
        ):
            raise ValueError("invalid_socket_limit")
        result[group] = min(result.get(group, limit), limit)
    return [{"group": group, "limit": limit} for group, limit in sorted(result.items())]


def audit(
    xml: str, *, replacements: dict[str, list[dict[str, Any]]] | None = None
) -> dict[str, Any]:
    root = ET.fromstring(xml)
    items = root.find("Items")
    if items is None:
        return {"ok": True, "violations": []}
    by_id = {str(item.get("id")): item.text or "" for item in items.findall("Item")}
    active_id = str(items.get("activeItemSet") or "1")
    item_set = next(
        (item for item in items.findall("ItemSet") if item.get("id") == active_id), None
    )
    if item_set is None:
        return {"ok": True, "violations": []}
    sources: dict[str, list[dict[str, Any]]] = {}
    for slot in item_set.findall("Slot"):
        name = str(slot.get("name") or "")
        raw = by_id.get(str(slot.get("itemId") or ""))
        if not raw or not itemparse.semantic_item_structure(raw).get("runeNames"):
            continue
        receipt = craft_receipts.resolve_receipt(raw, slot=name)
        if receipt.get("status") == "verified":
            sources[name] = (receipt["receipt"].get("sources") or {}).get("runes") or []
    sources.update(replacements or {})
    violations = []
    for weapon_set in (1, 2):
        counts: Counter[str] = Counter()
        maxima: dict[str, int] = {}
        for slot, runes in sources.items():
            if slot.startswith("Weapon") and ("Swap" in slot) != (weapon_set == 2):
                continue
            for rune in runes:
                for quota in constraints(rune):
                    key, limit = quota["group"], quota["limit"]
                    counts[key] += 1
                    maxima[key] = min(maxima.get(key, limit), limit)
        for key, count in counts.items():
            if count > maxima[key]:
                violations.append(
                    {"group": key, "count": count, "limit": maxima[key], "weaponSet": weapon_set}
                )
    return {"ok": not violations, "violations": violations}
