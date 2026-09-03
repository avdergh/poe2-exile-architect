"""Shared XML structure helpers for active passive specs and socketed jewels."""

from __future__ import annotations

from typing import Any
import xml.etree.ElementTree as ET

from server.knowledge import itemparse


def spec_id(spec: ET.Element, index: int) -> str:
    return str(spec.get("id") or index)


def active_spec_id(tree: ET.Element) -> str:
    return str(tree.get("activeSpec") or "1")


def active_spec_passive_jewels(root: ET.Element) -> tuple[tuple[str, str], ...] | None:
    """Return ``(nodeId, semantic item fingerprint)`` for the exact active Spec.

    ``None`` means the round-trip structure is not trustworthy. An explicit empty ``Sockets``
    element is the sole valid zero-jewel representation for generated artifacts.
    """

    tree = root.find("Tree")
    items = root.find("Items")
    if tree is None or items is None:
        return None
    active = active_spec_id(tree)
    spec = next(
        (
            value
            for index, value in enumerate(tree.findall("Spec"), start=1)
            if spec_id(value, index) == active
        ),
        None,
    )
    if spec is None:
        return None
    sockets = spec.find("Sockets")
    if sockets is None:
        return None
    by_id = {
        str(item.get("id")): item.text or ""
        for item in items.findall("Item")
        if item.get("id")
    }
    assignments: list[tuple[str, str]] = []
    for socket in sockets.findall("Socket"):
        node_id = str(socket.get("nodeId") or "").strip()
        item_id = str(socket.get("itemId") or "").strip()
        if not node_id or not item_id:
            return None
        try:
            if int(item_id) <= 0:
                return None
        except ValueError:
            return None
        raw = by_id.get(item_id)
        if raw is None:
            return None
        structure: dict[str, Any] = itemparse.semantic_item_structure(raw)
        fingerprint = str(structure.get("itemFingerprint") or "")
        if not fingerprint:
            return None
        assignments.append((node_id, fingerprint))
    return tuple(sorted(assignments))
