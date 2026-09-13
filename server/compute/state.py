"""Stable hashes for mutable Path of Building state and typed compute requests."""

from __future__ import annotations

import hashlib
import json
from typing import Any
import xml.etree.ElementTree as ET

from .pob_xml_input import parse_pob_xml


def build_state_hash(xml: str) -> str:
    """Bind a mutation/plan to the semantic PoB inputs that were observed.

    PoB's serializer emits mapping attributes/children in unstable order and may add/remove derived
    PlayerStat, placeholder and UI nodes after an XML round trip. Hashing raw XML therefore creates
    false conflicts for identical builds. This projection keeps calculation inputs and ordered
    skill groups while dropping derived output and presentation-only state.
    """

    try:
        root = parse_pob_xml(xml)
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
    attrs = {key: value for key, value in node.attrib.items()
             if value != "nil" or node.tag == "CustomModifierBlock"}
    if node.tag == "CustomModifierBlock":
        attrs["enabled"] = "true" if node.get("enabled") in {None, "true"} else "false"
        attrs["title"] = node.get("title", "Default")
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
    elif node.tag == "AttributeOverride":
        for key in ("strNodes", "dexNodes", "intNodes"):
            if key in attrs:
                attrs[key] = _sorted_csv_numbers_preserving_multiplicity(attrs[key])

    children: list[list[Any]] = []
    custom_blocks: list[list[Any]] = []
    ordered_legacy_custom = node.tag in {"Config", "ConfigSet"} and sum(
        child.get("name") == "customMods" and (
            child.tag == "Input" or (child.tag == "Placeholder" and child.get("string") is not None)
        ) for child in node
    ) > 1
    for child in node:
        if node.tag == "PathOfBuilding2" and child.tag in _ROOT_IGNORED:
            continue
        if node.tag == "Build" and child.tag in _BUILD_DERIVED:
            continue
        if node.tag == "ConfigSet" and child.tag == "Placeholder" and not (
            child.get("name") == "customMods" and child.get("string") is not None
        ):
            continue
        if child.tag == "TradeSearchWeights":
            continue
        if node.tag == "Spec" and child.tag == "URL":
            continue
        if node.tag in {"Config", "ConfigSet"} and child.tag == "CustomModifierBlock":
            # ConfigTab adds modifier sources in block order. Preserve that ordering,
            # while ordinary config mapping inputs remain independent of serialization.
            custom_blocks.append(_semantic_element(child))
            continue
        if ordered_legacy_custom and child.get("name") == "customMods" and (
            child.tag == "Input" or (child.tag == "Placeholder" and child.get("string") is not None)
        ):
            # A legacy string Placeholder writes input too: the last assignment wins.
            custom_blocks.append(_semantic_element(child))
            continue
        children.append(_semantic_element(child))
    if node.tag not in _ORDER_SENSITIVE_PARENTS:
        children.sort(key=_canonical_sort_key)
    children.extend(custom_blocks)

    text = (node.text or "").replace("\r\n", "\n")
    # PoB's modifier parser trims only Lua ASCII whitespace. NBSP/EM SPACE
    # can make a modifier unrecognized and must not collide with a working line.
    text = text.strip(" \t\n\r\v\f") if node.tag == "CustomModifierBlock" else text.strip()
    return [node.tag, sorted(attrs.items()), text, children]


def _canonical_sort_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sorted_csv_numbers(value: str) -> str:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    try:
        return ",".join(str(number) for number in sorted({int(part) for part in parts}))
    except ValueError:
        return ",".join(sorted(set(parts)))


def _sorted_csv_numbers_preserving_multiplicity(value: str) -> str:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    try:
        return ",".join(str(number) for number in sorted(int(part) for part in parts))
    except ValueError:
        return ",".join(sorted(parts))
