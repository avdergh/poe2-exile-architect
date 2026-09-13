"""Local XML socket probes preserve item-owned skills and every other PoB input."""

from __future__ import annotations

import re
from typing import Any
from xml.sax.saxutils import escape

from .pob_xml_input import parse_pob_xml
from .state import _semantic_element, build_state_hash, canonical_payload_hash


def has_source_groups(xml: str) -> bool:
    return any(node.get("source") for node in parse_pob_xml(xml).iter("Skill"))


def replace_equipped_item(xml: str, slot: str, raw: str, *, _mask_contents: bool = False) -> str:
    """Replace exactly one item's text; never serialize the read-only XML projection."""
    root = parse_pob_xml(xml)
    items = root.findall("Items")
    if len(items) != 1:
        raise ValueError("socket_probe_item_identity_ambiguous")
    sets = [
        node
        for node in items[0].findall("ItemSet")
        if node.get("id") == (items[0].get("activeItemSet") or "1")
    ]
    slots = [
        node for item_set in sets for node in item_set.findall("Slot") if node.get("name") == slot
    ]
    if len(sets) != 1 or len(slots) != 1 or slots[0].get("itemId") in {None, "", "0"}:
        raise ValueError("socket_probe_item_identity_ambiguous")
    item_id = slots[0].get("itemId")
    owned = [node for node in items[0].findall("Item") if node.get("id") == item_id]
    if len(owned) != 1:
        raise ValueError("socket_probe_item_identity_ambiguous")
    matches = []
    for match in re.finditer(r"(<Item\b[^>]*>)(.*?)(</Item>)", xml, re.DOTALL):
        node = parse_pob_xml(match.group())
        if node.get("id") == item_id:
            matches.append(match)
    if len(matches) != 1:
        raise ValueError("socket_probe_item_identity_ambiguous")
    match = matches[0]
    if _mask_contents:
        return xml[: match.start(2)] + xml[match.end(2) :]
    # Item text precedes PoB's child metadata (for example unique ModRange entries).
    # Those nodes are inputs too, and must not disappear during the text splice.
    text_end = match.start(2) + len(match[2].split("<", 1)[0])
    return xml[: match.start(2)] + "\n" + escape(raw) + "\n" + xml[text_end:]


def load_candidate(engine: Any, snapshot: str, slot: str, raw: str) -> None:
    candidate = replace_equipped_item(snapshot, slot, raw)
    result = engine.load_build_xml(candidate)
    if not isinstance(result, dict) or result.get("ok") is False:
        raise ValueError("socket_probe_equip_failed")
    # PoB can canonicalize the Rune text. Mask only that exact item to prove all other
    # inputs survived, including inactive sets, source supports and source item IDs.
    observed = replace_equipped_item(engine.get_xml(), slot, "", _mask_contents=True)
    expected = replace_equipped_item(snapshot, slot, "", _mask_contents=True)
    if build_state_hash(observed) != build_state_hash(
        expected
    ) and not _only_new_default_derived_groups(engine, expected, observed):
        raise ValueError("socket_probe_non_item_inputs_changed")


# Pinned CalcSetup's item-derived, non-supportable effect groups. These are engine
# identities, not fuzzy display-name allowances or caller-declared source kinds.
_DERIVED_GROUPS = {
    "Thorns": ("ThornsPlayer", "Thorns"),
    "Explode": ("EnemyExplode", "On Kill Monster Explosion"),
}


def _default_derived_xml(group: Any, source: str, effect_id: str, label: str) -> bool:
    group_defaults = {
        "label": label,
        "source": source,
        "enabled": "true",
        "includeInFullDPS": "false",
        "mainActiveSkill": "1",
        "mainActiveSkillCalcs": "1",
        "set1": "true",
        "set2": "true",
    }
    if any(
        value != "nil" and group_defaults.get(key) != value for key, value in group.attrib.items()
    ):
        return False
    if not len(group) or (source == "Thorns" and len(group) != 1) or (group.text or "").strip():
        return False
    gem_defaults = {
        "skillId": effect_id,
        "nameSpec": "",
        "level": "1",
        "quality": "0",
        "enabled": "true",
        "count": "1",
        "corruptLevel": "0",
        "corrupted": "false",
        "enableGlobal1": "false",
        "enableGlobal2": "false",
    }
    for gem in group:
        if (
            gem.tag != "Gem"
            or gem.get("skillId") != effect_id
            or len(gem)
            or (gem.text or "").strip()
        ):
            return False
        if any(
            value != "nil" and gem_defaults.get(key) != value for key, value in gem.attrib.items()
        ):
            return False
    return True


def _only_new_default_derived_groups(engine: Any, expected: str, observed: str) -> bool:
    """Allow only freshly derived default groups confirmed by the actual PoB runtime.

    Item-provided thorns/explosions can introduce non-supportable level-1 effects.
    No existing group is masked, and no selected or full-DPS group can be exempted.
    This private hash projection is never serialized back to the active build.
    """
    before, after = parse_pob_xml(expected), parse_pob_xml(observed)
    existing_sources = {group.get("source") for group in before.iter("Skill")}
    additions = [
        group
        for group in after.iter("Skill")
        if group.get("source") in _DERIVED_GROUPS and group.get("source") not in existing_sources
    ]
    if not additions or len({group.get("source") for group in additions}) != len(additions):
        return False
    skills = after.findall("Skills")
    if len(skills) != 1:
        return False
    active_sets = [
        node
        for node in skills[0].findall("SkillSet")
        if node.get("id") == (skills[0].get("activeSkillSet") or "1")
    ]
    if len(active_sets) != 1:
        return False
    groups = list(active_sets[0])
    runtime = engine.call("list_skill_groups")
    for group in additions:
        source = group.get("source")
        effect_id, label = _DERIVED_GROUPS[source]
        if group not in groups or not _default_derived_xml(group, source, effect_id, label):
            return False
        group_index = groups.index(group) + 1
        matches = [node for node in runtime.get("groups", []) if node.get("index") == group_index]
        if len(matches) != 1:
            return False
        actual = matches[0]
        effects = [
            {"index": index + 1, "name": label, "effectId": effect_id, "effectiveLevel": 1}
            for index in range(len(group))
        ]
        if not (
            actual.get("source") == source
            and actual.get("sourceKind") == "other"
            and actual.get("rootSkillId") == effect_id
            and actual.get("noSupports") is True
            and actual.get("mutable") is False
            and actual.get("isMain") is False
            and actual.get("includeInFullDPS") is False
            and actual.get("enabled") is True
            and actual.get("activeSkills") == effects
            and actual.get("gems") == []
        ):
            return False
    for group in additions:
        active_sets[0].remove(group)
    return canonical_payload_hash(_semantic_element(before)) == canonical_payload_hash(
        _semantic_element(after)
    )
