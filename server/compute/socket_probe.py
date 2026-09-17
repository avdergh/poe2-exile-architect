"""Local XML socket probes preserve item-owned skills and every other PoB input."""

from __future__ import annotations

import re
import hashlib
from copy import deepcopy
from typing import Any
from xml.sax.saxutils import escape

from .pob_xml_input import parse_pob_xml
from .state import _semantic_element, build_state_hash, canonical_payload_hash


class SocketProbeInputError(ValueError):
    def __init__(self, expected: str, observed: str):
        super().__init__("socket_probe_non_item_inputs_changed")
        self.details = {"inputDiff": semantic_input_diff(expected, observed)}


def semantic_input_diff(expected: str, observed: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Bounded semantic field differences, without copying item/XML bodies into diagnostics."""
    left, right = _semantic_element(parse_pob_xml(expected)), _semantic_element(parse_pob_xml(observed))
    result: list[dict[str, Any]] = []

    def safe(value):
        if value is None or isinstance(value, (int, float, bool)):
            return value
        value = str(value)
        if len(value) <= 96 and '\n' not in value:
            return value
        return 'sha256:' + hashlib.sha256(value.encode()).hexdigest()

    def walk(a, b, path):
        if a == b or len(result) >= limit:
            return
        if a is None or b is None or a[0] != b[0]:
            result.append({'path': path, 'change': 'node_identity', 'expected': a[0] if a else None, 'observed': b[0] if b else None})
            return
        aa, ba = dict(a[1]), dict(b[1])
        for key in sorted(aa.keys() | ba.keys()):
            if aa.get(key) != ba.get(key) and len(result) < limit:
                result.append({'path': path + '/@' + key, 'expected': safe(aa.get(key)), 'observed': safe(ba.get(key))})
        if a[2] != b[2] and len(result) < limit:
            result.append({'path': path + '/text()', 'expected': safe(a[2]), 'observed': safe(b[2])})
        counts: dict[str, int] = {}
        for index in range(max(len(a[3]), len(b[3]))):
            av = a[3][index] if index < len(a[3]) else None
            bv = b[3][index] if index < len(b[3]) else None
            tag = (av or bv)[0]
            counts[tag] = counts.get(tag, 0) + 1
            walk(av, bv, path + '/' + tag + '[' + str(counts[tag]) + ']')
    walk(left, right, '/' + left[0])
    return result


def has_source_groups(xml: str) -> bool:
    return any(node.get("source") for node in parse_pob_xml(xml).iter("Skill"))


def requires_source_snapshot_probe(xml: str) -> bool:
    """Keep the conservative path for item-owned or unknown source configurations.

    The native replacement evaluator already verifies every non-target source and
    the exact selected effect. A tree grant or unconfigured default attack must not
    force a whole-build reload for every Rune candidate. Item ownership keeps its
    established snapshot path, including interactions from a different equipment slot.
    """
    for group in parse_pob_xml(xml).iter("Skill"):
        source = group.get("source") or ""
        if not source or source.startswith("Tree:"):
            continue
        if source == "Default Attack" and len(group.findall("Gem")) <= 1:
            continue
        return True
    return False


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
    if build_state_hash(observed) != build_state_hash(expected):
        normalized = _item_grant_level_projection(engine, expected, observed)
        if normalized is not None:
            same = canonical_payload_hash(_semantic_element(normalized[0])) == canonical_payload_hash(_semantic_element(normalized[1]))
        else:
            same = False
        if not same and not _only_new_default_derived_groups(engine, *(normalized or (expected, observed))):
            raise SocketProbeInputError(expected, observed)


def _item_grant_level_projection(engine: Any, expected: str, observed: str) -> tuple[Any, Any] | None:
    """Allow only a real, same-owner item's native attribute-dependent root level.

    Supports and every other group field remain exact. This read-only projection is never loaded
    into PoB. Authority comes from the runtime's source-bound itemGrantedLevelForSocketGroup.
    """
    before, after = parse_pob_xml(expected), parse_pob_xml(observed)
    before_skills, after_skills = before.find('Skills'), after.find('Skills')
    if before_skills is None or after_skills is None:
        return None
    active_id = before_skills.get('activeSkillSet') or '1'
    if (after_skills.get('activeSkillSet') or '1') != active_id:
        return None
    old_active = next((node for node in before_skills.findall('SkillSet') if node.get('id') == active_id), None)
    new_active = next((node for node in after_skills.findall('SkillSet') if node.get('id') == active_id), None)
    if old_active is None or new_active is None:
        return None
    prior = list(before.iter('Skill'))
    current = list(after.iter('Skill'))
    if len(prior) != len(current):
        return None
    changed = []
    for old, new in zip(prior, current):
        og, ng = old.find('Gem'), new.find('Gem')
        if og is None or ng is None or og.get('level') == ng.get('level'):
            continue
        if not (old in list(old_active) and new in list(new_active)
                and old.get('source', '').startswith('Item:') and old.get('source') == new.get('source')
                and old.get('slot') == new.get('slot') and og.get('skillId') == ng.get('skillId')):
            return None
        changed.append((old, new, og, ng))
    if not changed:
        return None
    runtime = engine.call('list_skill_groups')
    for old, new, og, ng in changed:
        matches = [row for row in runtime.get('groups', []) if row.get('source') == new.get('source')
                   and row.get('slot') == new.get('slot') and row.get('rootSkillId') == ng.get('skillId')]
        if len(matches) != 1:
            return None
        group = matches[0]
        gems = group.get('gems') or []
        root = next((gem for gem in gems if gem.get('effectId') == ng.get('skillId') and not gem.get('isSupport')), None)
        if not (group.get('sourceKind') == 'item' and root and root.get('levelAuthority') == 'item_grant'
                and root.get('levelRequirementMet') is True and str(root.get('level')) == ng.get('level')):
            return None
        og.attrib.pop('level', None)
        ng.attrib.pop('level', None)
    return before, after


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
    before = parse_pob_xml(expected) if isinstance(expected, str) else deepcopy(expected)
    after = parse_pob_xml(observed) if isinstance(observed, str) else deepcopy(observed)
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
