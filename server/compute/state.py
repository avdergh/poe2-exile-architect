"""Stable hashes for mutable Path of Building state and typed compute requests."""

from __future__ import annotations

import hashlib
import json
from typing import Any
import xml.etree.ElementTree as ET


def build_state_hash(xml: str) -> str:
    """Bind a mutation/plan to the semantic PoB inputs that were observed.

    PoB's serializer emits mapping attributes/children in unstable order and may add/remove derived
    PlayerStat, placeholder and UI nodes after an XML round trip. Hashing raw XML therefore creates
    false conflicts for identical builds. This projection keeps calculation inputs and ordered
    skill groups while dropping derived output and presentation-only state.
    """

    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        payload: Any = {"invalidXml": xml}
    else:
        payload = _semantic_element(root)
    return canonical_payload_hash(payload)


def canonical_payload_hash(payload: Any, *, prefix: str = "sha256") -> str:
    """Hash a JSON-compatible payload independently of mapping insertion order."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(encoded).hexdigest()}"


_ROOT_IGNORED = {"Notes", "TreeView", "Import", "Calcs", "Party"}
_BUILD_DERIVED = {"PlayerStat", "FullDPSSkill", "Buffs", "TimelessData"}
_ORDER_SENSITIVE_PARENTS = {"Skills", "SkillSet", "Skill"}
_DEFAULT_ATTRIBUTES: dict[str, dict[str, str]] = {
    "Items": {"useSecondWeaponSet": "false"},
    "ItemSet": {"title": "Default", "useSecondWeaponSet": "false"},
    "ConfigSet": {"title": "Default"},
    "Skill": {
        "includeInFullDPS": "false",
        "mainActiveSkill": "1",
        "mainActiveSkillCalcs": "1",
    },
    "Gem": {
        "count": "1",
        "corruptLevel": "0",
        "corrupted": "false",
        "enableGlobal2": "false",
    },
}


def _semantic_element(node: ET.Element) -> list[Any]:
    attrs = {key: value for key, value in node.attrib.items() if value != "nil"}
    for key, default in _DEFAULT_ATTRIBUTES.get(node.tag, {}).items():
        if attrs.get(key, default) == default:
            attrs.pop(key, None)
    if node.tag == "Items":
        attrs.pop("showStatDifferences", None)
    elif node.tag == "Skills":
        attrs = {key: value for key, value in attrs.items() if key == "activeSkillSet"}
    elif node.tag == "Build":
        attrs.pop("viewMode", None)
    elif node.tag == "Spec" and "nodes" in attrs:
        attrs["nodes"] = _sorted_csv_numbers(attrs["nodes"])

    children: list[list[Any]] = []
    for child in node:
        if node.tag == "PathOfBuilding2" and child.tag in _ROOT_IGNORED:
            continue
        if node.tag == "Build" and child.tag in _BUILD_DERIVED:
            continue
        if node.tag == "ConfigSet" and child.tag == "Placeholder":
            continue
        if child.tag == "TradeSearchWeights":
            continue
        if node.tag == "Spec" and child.tag == "URL":
            continue
        children.append(_semantic_element(child))
    if node.tag not in _ORDER_SENSITIVE_PARENTS:
        children.sort(key=_canonical_sort_key)

    text = (node.text or "").replace("\r\n", "\n").strip()
    return [node.tag, sorted(attrs.items()), text, children]


def _canonical_sort_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sorted_csv_numbers(value: str) -> str:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    try:
        return ",".join(str(number) for number in sorted({int(part) for part in parts}))
    except ValueError:
        return ",".join(sorted(set(parts)))
