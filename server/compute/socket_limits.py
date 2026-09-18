"""PoB-sourced augment quotas shared by probes, equipment transactions and Judge."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
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
    return prepare(xml).audit(replacements=replacements)


@dataclass(frozen=True)
class _InvalidQuota:
    code: str


@dataclass(frozen=True)
class SocketQuotaLedger:
    """Immutable quotas resolved once for one exact search snapshot, never a global cache."""

    active_item_set: bool
    sources: tuple[tuple[str, tuple[tuple[tuple[str, int], ...], ...] | _InvalidQuota], ...] = ()

    def audit(
        self, *, replacements: dict[str, list[dict[str, Any]]] | None = None
    ) -> dict[str, Any]:
        if not self.active_item_set:
            return {"ok": True, "violations": []}
        sources = dict(self.sources)
        for slot, runes in (replacements or {}).items():
            sources[slot] = _quotas(runes)
        violations = []
        for weapon_set in (1, 2):
            counts: Counter[str] = Counter()
            maxima: dict[str, int] = {}
            for slot, runes in sources.items():
                if slot.startswith("Weapon") and ("Swap" in slot) != (weapon_set == 2):
                    continue
                if isinstance(runes, _InvalidQuota):
                    raise ValueError(runes.code)
                for rune in runes:
                    for key, limit in rune:
                        counts[key] += 1
                        maxima[key] = min(maxima.get(key, limit), limit)
            for key, count in counts.items():
                if count > maxima[key]:
                    violations.append(
                        {
                            "group": key,
                            "count": count,
                            "limit": maxima[key],
                            "weaponSet": weapon_set,
                        }
                    )
        return {"ok": not violations, "violations": violations}


def _quotas(runes: list[dict[str, Any]]) -> tuple[tuple[tuple[str, int], ...], ...]:
    return tuple(tuple((q["group"], q["limit"]) for q in constraints(rune)) for rune in runes)


def prepare(xml: str) -> SocketQuotaLedger:
    """Resolve receipts only at the start of a locked, snapshot-bound search."""
    root = ET.fromstring(xml)
    items = root.find("Items")
    if items is None:
        return SocketQuotaLedger(False)
    by_id = {str(item.get("id")): item.text or "" for item in items.findall("Item")}
    active_id = str(items.get("activeItemSet") or "1")
    item_set = next(
        (item for item in items.findall("ItemSet") if item.get("id") == active_id), None
    )
    if item_set is None:
        return SocketQuotaLedger(False)
    sources = []
    for slot in item_set.findall("Slot"):
        name = str(slot.get("name") or "")
        raw = by_id.get(str(slot.get("itemId") or ""))
        if not raw or not itemparse.semantic_item_structure(raw).get("runeNames"):
            continue
        receipt = craft_receipts.resolve_receipt(raw, slot=name)
        if receipt.get("status") == "verified":
            try:
                quotas = _quotas((receipt["receipt"].get("sources") or {}).get("runes") or [])
            except ValueError as exc:
                # The original audit overwrote the target slot before validating constraints.
                # Keep that repair path: malformed quotas still fail unless that slot is replaced.
                quotas = _InvalidQuota(str(exc))
            sources.append((name, quotas))
    return SocketQuotaLedger(True, tuple(sources))
