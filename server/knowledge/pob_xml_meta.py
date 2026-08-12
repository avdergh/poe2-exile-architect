"""Shared Path of Building 2 XML metadata parsing.

The authoritative main-skill semantics come from the engine bridge
(``pob/pob_headless.lua`` ``mainSkillName()``): the skill group selected by the
``Build`` element's ``mainSocketGroup`` attribute within the active skill set,
then that group's ``mainActiveSkill`` gem.  The collector scripts historically
read the first ``nameSpec`` in document order instead, which frequently labels
auras or passive-provided skills as the main skill.
"""

from __future__ import annotations

import re

_BUILD_ATTR = re.compile(r"<Build\b([^>]*)>", re.IGNORECASE)
_ATTR = re.compile(r'(\w+)="([^"]*)"')
_SKILLS_TAG = re.compile(r"<Skills\b([^>]*)>", re.IGNORECASE)
_SKILL_SET = re.compile(r"<SkillSet\b([^>]*)>(.*?)</SkillSet>", re.IGNORECASE | re.DOTALL)
_SKILL_GROUP = re.compile(r"<Skill\b([^>]*)>(.*?)</Skill>", re.IGNORECASE | re.DOTALL)
_GEM_TAG = re.compile(r"<Gem\b([^>]*)>", re.IGNORECASE)
_NAME_SPEC = re.compile(r'nameSpec="([^"]+)"', re.IGNORECASE)


def _build_attributes(xml: str) -> dict[str, str]:
    match = _BUILD_ATTR.search(xml)
    if not match:
        return {}
    return {key: value for key, value in _ATTR.findall(match.group(1))}


def _tag_attributes(tag: str) -> dict[str, str]:
    return {key: value for key, value in _ATTR.findall(tag)}


def _active_set_groups(xml: str) -> list[tuple[str, str]]:
    """Return the skill groups of the active skill set in engine group order.

    The engine builds its socket group list from the active skill set only
    (``Skills activeSkillSet="N"``).  With ``SkillSet`` containers only the
    matching set's ``<Skill>`` elements count; without containers all
    ``<Skill>`` elements belong to the single implicit set.
    """
    skills_match = _SKILLS_TAG.search(xml)
    active_set = _tag_attributes(skills_match.group(1) if skills_match else "").get(
        "activeSkillSet"
    )
    sets = _SKILL_SET.findall(xml)
    if sets:
        for tag, body in sets:
            set_id = _tag_attributes(tag).get("id")
            if set_id == active_set or (active_set is None and len(sets) == 1):
                return _SKILL_GROUP.findall(body)
        return []
    return _SKILL_GROUP.findall(xml)


def _active_name_specs(body: str) -> list[str]:
    """Group's enabled, non-support gem nameSpecs in document order.

    Mirrors the engine's active-only ``displaySkillList``: it contains only
    enabled, non-support gems; support gems carry ``SupportGem`` in their gem
    id or a ``Support``-prefixed skill id (the same heuristic as
    ``research_packet._is_support_gem``).
    """
    specs: list[str] = []
    for tag in _GEM_TAG.findall(body):
        attrs = _tag_attributes(tag)
        name = str(attrs.get("nameSpec") or "").strip()
        if not name:
            continue
        if "SupportGem" in str(attrs.get("gemId") or "") or str(
            attrs.get("skillId") or ""
        ).startswith("Support"):
            continue
        enabled_value = attrs.get("enabled")
        if enabled_value is not None and str(enabled_value).casefold() not in {"1", "true"}:
            continue
        specs.append(name)
    return specs


def main_skill_from_pob_xml(xml: str) -> str | None:
    """Return the main skill gem name following the engine's group semantics.

    Resolution order:

    1. ``<Build mainSocketGroup="N">`` selects a skill group (1-based) within
       the active skill set.  A group with an explicit ``id`` matching ``N``
       wins; otherwise the ``N``-th ``<Skill>`` element in active-set document
       order is used.
    2. Inside that group the ``mainActiveSkill`` / ``mainActiveSkillCalcs``
       attributes name the selected gem: a numeric value is a 1-based index
       over the group's **active** (enabled, non-support) gems — mirroring the
       engine's active-only ``displaySkillList`` — and a non-numeric value
       matches the gem's ``nameSpec`` or ``skillId`` (case-insensitive).
       Without either attribute the group's first active gem name is used.
    3. If the group cannot be determined or contains no active gem, fall back
       to the legacy behavior: the first ``nameSpec`` in document order.

    Known deliberate deviations from the engine (documented, real PoB2 exports
    never hit them): a non-numeric ``mainActiveSkill`` is matched by name
    instead of the engine's ``tonumber(...) or 1`` clamp; an out-of-range
    numeric selector inside a resolved group returns ``None`` instead of the
    engine's clamp; gems without a ``nameSpec`` are skipped; the legacy
    ``mainSkillIndex`` attribute is not read.
    """
    if not isinstance(xml, str) or not xml.strip():
        return None
    build_attrs = _build_attributes(xml)
    group_value = build_attrs.get("mainSocketGroup", "").strip()
    groups = _active_set_groups(xml)
    if not groups:
        return _first_name_spec(xml)
    selected: tuple[str, str] | None = None
    if group_value:
        if group_value.isdigit():
            positional = int(group_value)
            if 1 <= positional <= len(groups):
                selected = groups[positional - 1]
        if selected is None:
            for tag, body in groups:
                if _tag_attributes(tag).get("id") == group_value:
                    selected = (tag, body)
                    break
        if selected is None:
            return _first_name_spec(xml)
    else:
        selected = groups[0]
    name = _selected_gem_name(_tag_attributes(selected[0]), selected[1])
    if name:
        return name
    # A resolved group with a failed selector (e.g. numeric active index
    # out of range over active gems) must not fall back to a support-gem
    # name; only an unresolvable group uses the legacy document-order path.
    return None


def _selected_gem_name(tag_attrs: dict[str, str], body: str) -> str | None:
    selector = str(
        tag_attrs.get("mainActiveSkill") or tag_attrs.get("mainActiveSkillCalcs") or ""
    ).strip()
    name_specs = _active_name_specs(body)
    if not name_specs:
        return None
    if not selector:
        return name_specs[0]
    if selector.isdigit():
        index = int(selector)
        if 1 <= index <= len(name_specs):
            return name_specs[index - 1]
        return None
    wanted = selector.casefold()
    for attrs in (_tag_attributes(tag) for tag in _GEM_TAG.findall(body)):
        name = str(attrs.get("nameSpec") or "").strip()
        if not name:
            continue
        if name.casefold() == wanted or str(attrs.get("skillId") or "").casefold() == wanted:
            return name
    return None


def _first_name_spec(xml: str) -> str | None:
    for value in _NAME_SPEC.findall(xml):
        text = value.strip()
        if text:
            return text
    return None
