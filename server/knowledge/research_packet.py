"""Transient Phase 4 research packet construction."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from .. import paths

PACKET_PREFIX = "poe-bd-creator-research-packet-"
MAX_TTL_SECONDS = 24 * 60 * 60
RESEARCH_SECTIONS = ("skills", "gear", "passives", "config", "build")
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
MAX_RESPONSE_CHARS = 12_000
SAFE_METADATA_KEYS = (
    "case_id",
    "sourceType",
    "sourceRef",
    "league",
    "class",
    "ascendancy",
    "level",
    "mainSkill",
    "gamePatch",
    "passiveTreeVersion",
    "pobVersionOrCommit",
    "visibility",
    "split",
    "knowledgeScope",
    "evidenceType",
    "freshnessStatus",
    "compatibilityStatus",
)


def build_research_packet(
    case: dict[str, Any],
    *,
    persist_for_transport: bool = False,
    ttl_seconds: int = 60 * 60,
    temp_root: Path | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    ttl = max(1, min(int(ttl_seconds), MAX_TTL_SECONDS))
    expires = now + timedelta(seconds=ttl)
    safe_metadata = dict(case.get("safeMetadata") or {})
    raw_context = dict(case.get("rawContext") or {})
    packet_core = {
        "safeMetadata": safe_metadata,
        "rawContext": raw_context,
        "copySafetyRules": [
            "Final output must not contain raw PoB code/XML, account identity, copied guide prose, or a third-party whole-character mirror.",
            "Complete core skill/support, local passive, and item interaction packages are allowed as focused knowledge records.",
            "Durable artifacts may contain only safe hashes and safe evidence refs.",
        ],
        "requestedOutputSchema": "ResearcherOutput schema_version=5",
    }
    safe_hash = _safe_hash(packet_core)
    packet = {
        "packetId": f"rp-{safe_hash[:16]}",
        "createdAt": now.isoformat(timespec="seconds"),
        "expiresAt": expires.isoformat(timespec="seconds"),
        "safeHash": safe_hash,
        **packet_core,
    }
    result: dict[str, Any] = {"ok": True, "packet": packet}
    if persist_for_transport:
        root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
        directory = Path(tempfile.mkdtemp(prefix=PACKET_PREFIX, dir=root))
        path = directory / "packet.json"
        path.write_text(json.dumps(packet, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        result["packetPath"] = str(path)
    return result


def cleanup_expired_packets(
    *,
    temp_root: Path | None = None,
    now: str | datetime | None = None,
) -> dict[str, Any]:
    root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
    current = _parse_time(now) if now is not None else datetime.now(timezone.utc)
    removed = 0
    if not root.exists():
        return {"removed": 0}
    for child in root.iterdir():
        if not child.is_dir() or not child.name.startswith(PACKET_PREFIX):
            continue
        packet_path = child / "packet.json"
        expired = True
        if packet_path.exists():
            try:
                payload = json.loads(packet_path.read_text(encoding="utf-8"))
                expired = _parse_time(payload.get("expiresAt")) <= current
            except (OSError, ValueError, TypeError):
                expired = True
        if expired:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return {"removed": removed}


def cleanup_packets_by_safe_hashes(
    safe_hashes: set[str],
    *,
    temp_root: Path | None = None,
) -> dict[str, int]:
    """Immediately remove the exact transient packets owned by a completed Research run."""

    requested = {str(value) for value in safe_hashes if str(value)}
    root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
    removed = 0
    if not requested or not root.exists():
        return {"removed": 0}
    for child in root.iterdir():
        if not child.is_dir() or not child.name.startswith(PACKET_PREFIX):
            continue
        try:
            payload = json.loads((child / "packet.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if str(payload.get("safeHash") or "") in requested:
            shutil.rmtree(child, ignore_errors=True)
            if not child.exists():
                removed += 1
    return {"removed": removed}


def _tree_metadata_status(root: ET.Element) -> str:
    """Return whether passive-node metadata (tree.json) is available for the active spec.

    ``ok`` means the tree version resolved and node metadata parsed; ``tree_data_missing``
    means the packet cannot tell allocated jewel sockets apart, so a zero count is not
    trustworthy. A packet without Tree/Spec has no socket concept and returns ``ok``.
    """
    tree = root.find("Tree")
    if tree is None:
        return "ok"
    active_spec = str(tree.get("activeSpec") or "1")
    spec = next(
        (s for s in tree.findall("Spec") if str(s.get("id") or "") == active_spec),
        None,
    )
    if spec is None:
        spec = next(iter(tree.findall("Spec")), None)
    if spec is None:
        return "ok"
    tree_version = str(spec.get("treeVersion") or "")
    if not tree_version:
        return "tree_data_missing"
    return "ok" if _passive_node_metadata(tree_version) else "tree_data_missing"


def jewel_counts(
    packet: dict[str, Any],
    sections: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Count allocated jewel sockets vs socketed jewels in the packet's active spec.

    Derived view, never persisted: computed from the same raw XML ``_packet_sections``
    parses, so safeHash is unaffected and old packets compute it identically. Callers
    that already parsed ``_packet_sections`` may pass ``sections`` to avoid re-parsing.
    """
    normalized = _unwrap_packet(packet)
    if sections is None:
        sections = _packet_sections(normalized)
    allocated = sum(
        1
        for item in sections["passives"]
        if item.get("kind") == "allocated_node" and "jewel_socket" in (item.get("nodeTypes") or [])
    )
    socketed = sum(
        1 for item in sections["gear"] if str(item.get("slot") or "").startswith("Jewel")
    )
    raw_context = normalized.get("rawContext")
    raw_context = raw_context if isinstance(raw_context, dict) else {}
    xml = str(raw_context.get("rawXml") or "")
    status = "ok"
    if xml:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            root = None
        if root is not None:
            status = _tree_metadata_status(root)
    return {
        "allocatedJewelSocketCount": allocated,
        "socketedJewelCount": socketed,
        "status": status,
    }


def jewel_advisories(
    packet: dict[str, Any],
    sections: dict[str, list[dict[str, Any]]] | None = None,
) -> list[str]:
    counts = jewel_counts(packet, sections=sections)
    if counts["status"] == "tree_data_missing":
        return [
            "passive-tree node metadata is unavailable for this packet, so allocated jewel "
            "sockets cannot be counted; state the jewel situation explicitly in the review"
        ]
    allocated = int(counts["allocatedJewelSocketCount"] or 0)
    socketed = int(counts["socketedJewelCount"] or 0)
    if allocated > 0 and socketed == 0:
        return [
            f"{allocated} allocated jewel socket(s) carry no socketed jewel (empty or extraction "
            "gap); the review must declare the jewel state explicitly"
        ]
    return []


def inspect_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded manifest for a transient packet without exposing raw transport data."""
    normalized = _unwrap_packet(packet)
    sections = _packet_sections(normalized)
    metadata = normalized.get("safeMetadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    safe_metadata = {
        key: metadata[key]
        for key in SAFE_METADATA_KEYS
        if key in metadata and metadata[key] not in (None, "")
    }
    return {
        "status": "ok",
        "packetId": str(normalized.get("packetId") or ""),
        "packetSafeHash": str(normalized.get("safeHash") or ""),
        "safeMetadata": safe_metadata,
        "sections": {
            name: {"itemCount": len(sections[name]), "available": bool(sections[name])}
            for name in RESEARCH_SECTIONS
        },
        "activeSets": _active_sets(normalized),
        "jewelCounts": jewel_counts(packet, sections=sections),
        "jewelAdvisories": jewel_advisories(packet, sections=sections),
        "recommendedReadOrder": list(RESEARCH_SECTIONS),
        "requiredCoverage": [
            "supports",
            "rotation",
            "passiveAscendancy",
            "gearRoles",
            "resourceDefense",
        ],
        "noRawMatureBuildMaterial": True,
    }


def build_skill_evidence_manifest(packet: dict[str, Any]) -> dict[str, Any]:
    """Return active skill-group identities for acceptance diagnostics."""
    groups: list[dict[str, Any]] = []
    for item in _packet_sections(_unwrap_packet(packet))["skills"]:
        if not item.get("activeSkillSet") or not item.get("enabled"):
            continue
        enabled_gems = [gem for gem in item.get("gems") or [] if gem.get("enabled")]
        active_skills = [
            {"name": str(gem.get("name") or ""), "skillId": str(gem.get("skillId") or "")}
            for gem in enabled_gems
            if not gem.get("isSupport") and str(gem.get("name") or "")
        ]
        supports = [
            {"name": str(gem.get("name") or ""), "gemId": str(gem.get("gemId") or "")}
            for gem in enabled_gems
            if gem.get("isSupport") and str(gem.get("name") or "")
        ]
        if not active_skills:
            continue
        skill_set_id = str(item.get("skillSetId") or "")
        group_index = int(item.get("groupIndex") or 0)
        groups.append(
            {
                "groupRef": f"skill-set:{skill_set_id}:group:{group_index}",
                "slot": str(item.get("slot") or ""),
                "mainActiveSkill": str(item.get("mainActiveSkill") or ""),
                "mainActiveSkillCalcs": str(item.get("mainActiveSkillCalcs") or ""),
                "activeSkills": active_skills,
                "supports": supports,
            }
        )
    return {
        "activeSkillGroups": groups,
        "noRawMatureBuildMaterial": True,
    }


def read_packet_section(
    packet: dict[str, Any],
    *,
    section: str,
    cursor: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
    node_type: str | None = None,
) -> dict[str, Any]:
    """Read one structured packet section with stable, character-bounded pagination.

    ``node_type`` filters the passives section by node kind (keystone/notable/jewel_socket/
    ascendancy/mastery, or ``normal`` for small nodes); it is ignored for other sections.
    """
    normalized_section = str(section or "").strip().lower()
    if normalized_section not in RESEARCH_SECTIONS:
        raise ValueError("section must be one of: " + ", ".join(RESEARCH_SECTIONS))
    start = max(0, int(cursor or 0))
    page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    items = _packet_sections(_unwrap_packet(packet))[normalized_section]
    if normalized_section == "passives" and str(node_type or "").strip():
        items = _filter_passive_items(items, str(node_type).strip())
    page, next_cursor = _bounded_page(items, start=start, limit=page_size)
    result: dict[str, Any] = {
        "status": "ok",
        "section": normalized_section,
        "cursor": start,
        "limit": page_size,
        "items": page,
        "returnedCount": len(page),
        "totalCount": len(items),
        "nextCursor": next_cursor,
        "complete": next_cursor is None,
        "noRawMatureBuildMaterial": True,
    }
    if normalized_section in {"passives", "gear", "skills"}:
        result["advisories"] = [*_cross_axis_advisories(packet), *jewel_advisories(packet)]
    return result


def _filter_passive_items(items: list[dict[str, Any]], node_type: str) -> list[dict[str, Any]]:
    wanted = node_type.strip().casefold()
    if wanted == "normal":
        return [
            item
            for item in items
            if item.get("kind") in {"allocated_node", "weapon_set_node"}
            and not (item.get("nodeTypes") or [])
        ]
    return [
        item
        for item in items
        if any(str(label).strip().casefold() == wanted for label in item.get("nodeTypes") or [])
    ]


_RARE_DESIGN_AXES: dict[str, tuple[str, ...]] = {
    "chaos": ("chaos damage", "chaos resistance", "poison"),
    "thorns": ("thorns",),
    "low_life": ("low life",),
    "minion": ("minions", "companion"),
    "totem": ("totem",),
    "runic_ward": ("runic ward",),
    "trap": ("trapped", "trap damage", "trap skills"),
    "mark": ("marks enemies", "mark on hit", "voltaic mark", "freezing mark"),
}


def _cross_axis_advisories(packet: dict[str, Any]) -> list[str]:
    """Advisory-only hint for rare design-axis co-occurrences (chaos+thorns+low-life etc.).

    The heuristic is deliberately generic: it counts independent rare axes visible across the
    case's passives/gear/skills and flags when several co-occur, so the Researcher checks whether
    they form a designed layer or leftover components. It never gates acceptance.
    """
    sections = _packet_sections(_unwrap_packet(packet))
    corpus: list[str] = []
    for section_name in ("passives", "gear", "skills"):
        for item in sections[section_name]:
            searchable = json.dumps(item, ensure_ascii=False, sort_keys=True).casefold()
            corpus.append(searchable)
    joined = " ".join(corpus).casefold()
    present = sorted(
        axis
        for axis, keywords in _RARE_DESIGN_AXES.items()
        if any(keyword in joined for keyword in keywords)
    )
    if len(present) < 2:
        return []
    return [
        "rare design axes co-occur: "
        + ", ".join(present)
        + "; verify whether this is a designed layer or leftover components, and close it with "
        "an open_question record when it cannot be resolved"
    ]


def search_packet(
    packet: dict[str, Any],
    *,
    query: str,
    section: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Search structured transient evidence without fuzzy inference or raw XML output."""
    needle = str(query or "").strip().casefold()
    if not needle:
        raise ValueError("query must not be empty")
    selected_sections = RESEARCH_SECTIONS
    if section:
        normalized_section = str(section).strip().lower()
        if normalized_section not in RESEARCH_SECTIONS:
            raise ValueError("section must be one of: " + ", ".join(RESEARCH_SECTIONS))
        selected_sections = (normalized_section,)
    max_results = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    sections = _packet_sections(_unwrap_packet(packet))
    matches: list[dict[str, Any]] = []
    for section_name in selected_sections:
        for index, item in enumerate(sections[section_name]):
            searchable = json.dumps(item, ensure_ascii=False, sort_keys=True).casefold()
            if needle in searchable:
                matches.append({"section": section_name, "index": index, "item": item})
    page, _ = _bounded_page(matches, start=0, limit=max_results)
    return {
        "status": "ok",
        "query": str(query).strip(),
        "section": str(section or "all"),
        "matches": page,
        "returnedCount": len(page),
        "totalMatchCount": len(matches),
        "truncated": len(page) < len(matches),
        "noRawMatureBuildMaterial": True,
    }


def _unwrap_packet(packet: dict[str, Any]) -> dict[str, Any]:
    nested = packet.get("packet")
    return nested if isinstance(nested, dict) else packet


def _packet_sections(packet: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    raw_context = packet.get("rawContext")
    raw_context = raw_context if isinstance(raw_context, dict) else {}
    xml = str(raw_context.get("rawXml") or "")
    if not xml:
        return {name: [] for name in RESEARCH_SECTIONS}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("transient research packet contains invalid PoB XML") from exc
    return {
        "skills": _skill_items(root),
        "gear": _gear_items(root),
        "passives": _passive_items(root),
        "config": _config_items(root),
        "build": _build_items(root),
    }


def _skill_items(root: ET.Element) -> list[dict[str, Any]]:
    skills = root.find("Skills")
    if skills is None:
        return []
    active_set = str(skills.get("activeSkillSet") or "1")
    skill_sets = skills.findall("SkillSet")
    containers: list[tuple[str, bool, list[ET.Element]]] = []
    if skill_sets:
        containers = [
            (
                str(skill_set.get("id") or index),
                str(skill_set.get("id") or index) == active_set,
                skill_set.findall("Skill"),
            )
            for index, skill_set in enumerate(skill_sets, start=1)
        ]
    else:
        containers = [(active_set, True, skills.findall("Skill"))]
    result: list[dict[str, Any]] = []
    for skill_set_id, active, groups in containers:
        for group_index, group in enumerate(groups, start=1):
            gems = []
            for gem in group.findall("Gem"):
                name = str(
                    gem.get("nameSpec") or gem.get("skillId") or gem.get("gemId") or ""
                ).strip()
                if not name:
                    continue
                gems.append(
                    {
                        "name": name,
                        "skillId": str(gem.get("skillId") or ""),
                        "gemId": str(gem.get("gemId") or ""),
                        "level": _optional_int(gem.get("level")),
                        "quality": _optional_int(gem.get("quality")),
                        "enabled": _xml_bool(gem.get("enabled"), default=True),
                        "isSupport": _is_support_gem(gem),
                    }
                )
            result.append(
                {
                    "skillSetId": skill_set_id,
                    "activeSkillSet": active,
                    "groupIndex": group_index,
                    "enabled": _xml_bool(group.get("enabled"), default=True),
                    "slot": str(group.get("slot") or ""),
                    "mainActiveSkill": str(group.get("mainActiveSkill") or ""),
                    "mainActiveSkillCalcs": str(group.get("mainActiveSkillCalcs") or ""),
                    "gems": gems,
                }
            )
    return result


def _gear_items(root: ET.Element) -> list[dict[str, Any]]:
    items = root.find("Items")
    if items is None:
        return []
    active_set = str(items.get("activeItemSet") or "1")
    by_id = {str(item.get("id")): item for item in items.findall("Item") if item.get("id")}
    item_sets = items.findall("ItemSet")
    if not item_sets:
        item_sets = [items]
    result: list[dict[str, Any]] = []
    for set_index, item_set in enumerate(item_sets, start=1):
        set_id = str(item_set.get("id") or set_index)
        for slot in item_set.findall("Slot"):
            item_id = str(slot.get("itemId") or "0")
            node = by_id.get(item_id)
            if node is None:
                continue
            parsed = _parse_item_text(node.text or "")
            result.append(
                {
                    "itemSetId": set_id,
                    "activeItemSet": set_id == active_set,
                    "slot": str(slot.get("name") or ""),
                    "itemId": item_id,
                    **parsed,
                }
            )
    return result


def _parse_item_text(raw: str) -> dict[str, Any]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    rarity = _matched_value(lines, r"^Rarity:\s*(.+)$") or ""
    header_offset = 1 if lines and lines[0].lower().startswith("rarity:") else 0
    name = lines[header_offset] if len(lines) > header_offset else ""
    base = lines[header_offset + 1] if len(lines) > header_offset + 1 else ""
    metadata_prefixes = (
        "rarity:",
        "item level:",
        "levelreq:",
        "quality:",
        "sockets:",
        "limited to:",
        "unique id:",
        "league:",
        "source:",
        "crafted:",
        "corrupted:",
        "mirrored:",
    )
    modifiers = [
        line
        for line in lines[header_offset + 2 :]
        if line != "--------" and not line.casefold().startswith(metadata_prefixes)
    ]
    mutated_modifiers = [
        re.sub(r"^\{mutated\}\s*", "", line, flags=re.IGNORECASE)
        for line in modifiers
        if line.casefold().startswith("{mutated}")
    ]
    return {
        "rarity": rarity,
        "name": name,
        "base": base,
        "itemLevel": _matched_int(lines, r"^Item Level:\s*(\d+)$"),
        "levelRequirement": _matched_int(lines, r"^LevelReq:\s*(\d+)$"),
        "sockets": _matched_value(lines, r"^Sockets:\s*(.+)$") or "",
        "modifiers": modifiers,
        "itemStates": ["mutated"] if mutated_modifiers else [],
        "mutatedModifiers": mutated_modifiers,
    }


def _passive_items(root: ET.Element) -> list[dict[str, Any]]:
    tree = root.find("Tree")
    if tree is None:
        return []
    active_spec = str(tree.get("activeSpec") or "1")
    result: list[dict[str, Any]] = []
    for index, spec in enumerate(tree.findall("Spec"), start=1):
        spec_id = str(spec.get("id") or index)
        tree_version = str(spec.get("treeVersion") or "")
        node_metadata = _passive_node_metadata(tree_version)
        result.append(
            {
                "kind": "spec",
                "specId": spec_id,
                "activeSpec": spec_id == active_spec,
                "treeVersion": tree_version,
                "classId": str(spec.get("classId") or ""),
                "ascendClassId": str(spec.get("ascendClassId") or ""),
                "allocatedNodeCount": len(_csv_values(spec.get("nodes"))),
                "weaponSet1NodeCount": len(_csv_values(spec.get("nodes1"))),
                "weaponSet2NodeCount": len(_csv_values(spec.get("nodes2"))),
            }
        )
        for node_id in _csv_values(spec.get("nodes")):
            result.append(
                {
                    "kind": "allocated_node",
                    "specId": spec_id,
                    "nodeId": node_id,
                    **node_metadata.get(node_id, {}),
                }
            )
        for node_id in _csv_values(spec.get("nodes1")):
            result.append(
                {
                    "kind": "weapon_set_node",
                    "specId": spec_id,
                    "weaponSet": 1,
                    "nodeId": node_id,
                    **node_metadata.get(node_id, {}),
                }
            )
        for node_id in _csv_values(spec.get("nodes2")):
            result.append(
                {
                    "kind": "weapon_set_node",
                    "specId": spec_id,
                    "weaponSet": 2,
                    "nodeId": node_id,
                    **node_metadata.get(node_id, {}),
                }
            )
        for mastery in _csv_values(spec.get("masteryEffects")):
            result.append({"kind": "mastery_effect", "specId": spec_id, "value": mastery})
    return result


@lru_cache(maxsize=8)
def _passive_node_metadata(tree_version: str) -> dict[str, dict[str, Any]]:
    normalized = str(tree_version or "").strip()
    if not normalized:
        return {}
    tree_path = paths.pob_src_dir() / "TreeData" / normalized / "tree.json"
    try:
        payload = json.loads(tree_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    nodes = payload.get("nodes")
    if not isinstance(nodes, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        node_types = [
            label
            for field, label in (
                ("isKeystone", "keystone"),
                ("isNotable", "notable"),
                ("isAscendancy", "ascendancy"),
                ("isJewelSocket", "jewel_socket"),
                ("isMastery", "mastery"),
            )
            if node.get(field) is True
        ]
        result[str(node_id)] = {
            "name": str(node.get("name") or ""),
            "nodeTypes": node_types,
            "ascendancyName": str(node.get("ascendancyName") or ""),
            "isAscendancyPassive": bool(str(node.get("ascendancyName") or "").strip()),
            "stats": [str(value) for value in (node.get("stats") or []) if str(value).strip()],
        }
    return result


def _config_items(root: ET.Element) -> list[dict[str, Any]]:
    config = root.find("Config")
    if config is None:
        return []
    result: list[dict[str, Any]] = []
    for input_node in config.findall(".//Input"):
        value = next(
            (
                input_node.get(key)
                for key in ("boolean", "number", "string")
                if input_node.get(key) is not None
            ),
            "",
        )
        result.append(
            {
                "name": str(input_node.get("name") or ""),
                "value": str(value),
            }
        )
    return result


def _build_items(root: ET.Element) -> list[dict[str, Any]]:
    build = root.find("Build")
    skills = root.find("Skills")
    items = root.find("Items")
    tree = root.find("Tree")
    if build is None:
        return []
    return [
        {
            "className": str(build.get("className") or ""),
            "ascendancy": str(build.get("ascendClassName") or ""),
            "level": _optional_int(build.get("level")),
            "mainSocketGroup": str(build.get("mainSocketGroup") or ""),
            "activeSkillSet": str(skills.get("activeSkillSet") or "") if skills is not None else "",
            "activeItemSet": str(items.get("activeItemSet") or "") if items is not None else "",
            "activeSpec": str(tree.get("activeSpec") or "") if tree is not None else "",
        }
    ]


def _active_sets(packet: dict[str, Any]) -> dict[str, str]:
    sections = _packet_sections(packet)
    build = sections["build"][0] if sections["build"] else {}
    return {
        "skillSet": str(build.get("activeSkillSet") or ""),
        "itemSet": str(build.get("activeItemSet") or ""),
        "passiveSpec": str(build.get("activeSpec") or ""),
    }


def _bounded_page(
    items: list[dict[str, Any]], *, start: int, limit: int
) -> tuple[list[dict[str, Any]], int | None]:
    page: list[dict[str, Any]] = []
    index = min(start, len(items))
    while index < len(items) and len(page) < limit:
        candidate = [*page, items[index]]
        envelope = {"items": candidate, "nextCursor": index + 1}
        if (
            len(json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2))
            > MAX_RESPONSE_CHARS - 750
        ):
            if not page:
                page.append(_truncate_item(items[index]))
                index += 1
            break
        page.append(items[index])
        index += 1
    return page, index if index < len(items) else None


def _truncate_item(item: dict[str, Any]) -> dict[str, Any]:
    def trim(value: Any) -> Any:
        if isinstance(value, str):
            return value if len(value) <= 800 else value[:797] + "..."
        if isinstance(value, list):
            return [trim(child) for child in value[:40]]
        if isinstance(value, dict):
            return {key: trim(child) for key, child in value.items()}
        return value

    return trim(item)


def _xml_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return str(value).casefold() in {"1", "true"}


def _is_support_gem(gem: ET.Element) -> bool:
    gem_id = str(gem.get("gemId") or "")
    skill_id = str(gem.get("skillId") or "")
    return "SupportGem" in gem_id or skill_id.startswith("Support")


def _optional_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _csv_values(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _matched_value(lines: list[str], pattern: str) -> str | None:
    for line in lines:
        match = re.match(pattern, line, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _matched_int(lines: list[str], pattern: str) -> int | None:
    value = _matched_value(lines, pattern)
    return int(value) if value is not None else None


def _safe_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_time(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value or "")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)
