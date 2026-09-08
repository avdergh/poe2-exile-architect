"""Transient Phase 4 research packet construction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from .. import paths
from ..compute.pob_xml_input import (
    XML_INPUT_SEMANTICS_VERSION,
    parse_pob_xml,
    requires_preserved_input_semantics,
)
from ..compute.state import build_state_hash

PACKET_PREFIX = "poe-bd-creator-research-packet-"
MAX_TTL_SECONDS = 24 * 60 * 60
RESEARCH_SECTIONS = (
    "skills",
    "gear",
    "jewels",
    "passives",
    "config",
    "config-sets",
    "build",
    "pob-readback",
)
RESEARCH_READ_ORDER = (
    "skills",
    "skill-groups",
    "gear",
    "jewels",
    "passives",
    "config",
    "config-sets",
    "build",
    "pob-readback",
)
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
    "modelGamePatch",
    "versionContextStatus",
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
        "pobReadback": dict(case.get("pobReadback") or {}),
        "copySafetyRules": [
            "Final output must not contain raw PoB code/XML, account identity, copied guide prose, or a third-party whole-character mirror.",
            "Complete core skill/support, local passive, and item interaction packages are allowed as focused knowledge records.",
            "Durable artifacts may contain only safe hashes and safe evidence refs.",
        ],
        "requestedOutputSchema": "ResearcherOutput schema_version=6 / DeepResearchRecord schema 2",
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
        root.mkdir(parents=True, exist_ok=True)
        for _attempt in range(32):
            staging = root / f".{PACKET_PREFIX}{secrets.token_hex(8)}"
            try:
                if os.name == "nt":
                    staging.mkdir()
                else:
                    staging.mkdir(mode=0o700)
                break
            except FileExistsError:
                continue
        else:
            raise FileExistsError("could not allocate a unique research packet staging directory")
        directory = root / staging.name[1:]
        try:
            staging_path = staging / "packet.json"
            staging_path.write_text(
                json.dumps(packet, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            staging.rename(directory)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        result["packetPath"] = str(directory / "packet.json")
    return result


def cleanup_expired_packets(
    *,
    temp_root: Path | None = None,
    now: str | datetime | None = None,
) -> dict[str, Any]:
    """Remove expired transient packets.

    Packets are short-lived by design: queued packets get a long TTL (24h) so they survive
    waiting time; claimed packets are rebuilt on claim with the lease's own TTL, so an
    expired packet simply means the case lease expired too and the case can be reclaimed.
    The caller chooses the private packet root; Research defaults it inside the shared run.
    """
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
    axis = _selection_axis(root, "passiveSpec")
    if axis["issues"]:
        return "tree_data_missing"
    spec = next((s for s, _sid, active in axis["containers"] if active), None)
    if spec is None:
        return "ok"
    tree_version = str(spec.get("treeVersion") or "")
    if not tree_version:
        return "tree_data_missing"
    if not _passive_node_metadata(tree_version):
        return "tree_data_missing"
    # Real PoB always writes a <Sockets> element (even empty); its absence means a
    # third-party/legacy export whose socket mapping cannot be trusted.
    if spec.find("Sockets") is None:
        return "sockets_absent"
    return "ok"


def _jewel_socket_map(root: ET.Element) -> dict[str, dict[str, Any]]:
    """Map socketed jewel item ids to their tree socket (itemId -> nodeId) from <Sockets>.

    ``<Spec><Sockets><Socket nodeId itemId/></Sockets>`` is PoB's authoritative socket
    contract (Save/Load symmetric, PassiveSpec.lua). Only entries with a positive item id
    that actually exists in the item list are kept (mirrors the loader's stale defence).
    When the same item id is referenced by several specs, the active spec wins.
    """
    items = root.find("Items")
    if items is None:
        return {}
    item_ids = {_config_id(item.get("id")) for item in items.findall("Item") if item.get("id")}
    item_map: dict[str, dict[str, Any]] = {}
    for spec, spec_id, is_active in _selection_axis(root, "passiveSpec")["containers"]:
        sockets = spec.find("Sockets")
        if sockets is None:
            continue
        for socket in sockets.findall("Socket"):
            node_id = str(socket.get("nodeId") or "").strip()
            item_id = _config_id(socket.get("itemId"))
            if not node_id or not item_id:
                continue
            try:
                if int(item_id) <= 0:
                    continue
            except ValueError:
                continue
            if item_id not in item_ids:
                continue
            existing = item_map.get(item_id)
            if existing is not None:
                if is_active and not existing["activeSpec"]:
                    item_map[item_id] = {
                        "nodeId": node_id,
                        "specId": spec_id,
                        "activeSpec": True,
                    }
                continue
            item_map[item_id] = {
                "nodeId": node_id,
                "specId": spec_id,
                "activeSpec": is_active,
            }
    return item_map


def _jewel_socket_assignments(root: ET.Element) -> list[dict[str, Any]]:
    """Return every valid tree-jewel socket assignment without collapsing passive specs."""

    items = root.find("Items")
    if items is None:
        return []
    item_ids = {_config_id(item.get("id")) for item in items.findall("Item") if item.get("id")}
    assignments: list[dict[str, Any]] = []
    for spec, spec_id, is_active in _selection_axis(root, "passiveSpec")["containers"]:
        sockets = spec.find("Sockets")
        if sockets is None:
            continue
        for socket in sockets.findall("Socket"):
            node_id = str(socket.get("nodeId") or "").strip()
            item_id = _config_id(socket.get("itemId"))
            if not node_id or not item_id or item_id not in item_ids:
                continue
            try:
                if int(item_id) <= 0:
                    continue
            except ValueError:
                continue
            assignments.append(
                {
                    "nodeId": node_id,
                    "specId": spec_id,
                    "itemId": item_id,
                    "activeSpec": is_active,
                }
            )
    return sorted(
        assignments,
        key=lambda item: (not item["activeSpec"], item["specId"], item["nodeId"], item["itemId"]),
    )


def _jewel_socket_kinds(root: ET.Element) -> dict[tuple[str, str], str]:
    kinds: dict[tuple[str, str], str] = {}
    for spec, spec_id, _is_active in _selection_axis(root, "passiveSpec")["containers"]:
        metadata = _passive_node_metadata(str(spec.get("treeVersion") or ""))
        sockets = spec.find("Sockets")
        if sockets is None:
            continue
        for socket in sockets.findall("Socket"):
            node_id = str(socket.get("nodeId") or "").strip()
            if not node_id:
                continue
            node_types = (metadata.get(node_id) or {}).get("nodeTypes") or []
            kinds[(spec_id, node_id)] = (
                "granted_jewel_socket"
                if "granted_jewel_socket" in node_types
                else "tree_socket"
                if "jewel_socket" in node_types
                else "unknown"
            )
    return kinds


def jewel_counts(
    packet: dict[str, Any],
    sections: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Count allocated jewel sockets vs socketed jewels in the packet's active spec.

    Tree sockets are counted from the authoritative ``<Sockets>`` mapping resolved onto the
    gear section; embedded jewel sockets on items ("X Jewel Socket N") are counted
    separately. ``allocated`` covers only the active spec. Derived view, never persisted:
    computed from the same raw XML ``_packet_sections`` parses, so safeHash is unaffected
    and old packets compute it identically. Callers that already parsed ``_packet_sections``
    may pass ``sections`` to avoid re-parsing. ``countNotes`` explains how the four counts
    relate (active-spec scope, tree vs equipment sockets, and the allocated-without-socketed
    gap) so consumers do not have to reconcile them manually.
    """
    normalized = _unwrap_packet(packet)
    if sections is None:
        sections = _packet_sections(normalized)
    active_allocated_node_ids = {
        str(item.get("nodeId") or "")
        for item in sections["passives"]
        if item.get("kind") == "allocated_node"
        and item.get("activeSpec") is True
        and any(
            node_type in (item.get("nodeTypes") or [])
            for node_type in ("jewel_socket", "granted_jewel_socket")
        )
        and str(item.get("nodeId") or "")
    }
    active_socket_kind_by_node = {
        str(item.get("nodeId") or ""): (
            "granted_jewel_socket"
            if "granted_jewel_socket" in (item.get("nodeTypes") or [])
            else "tree_socket"
        )
        for item in sections["passives"]
        if item.get("kind") == "allocated_node"
        and item.get("activeSpec") is True
        and str(item.get("nodeId") or "") in active_allocated_node_ids
    }
    allocated = len(active_allocated_node_ids)
    embedded = sum(
        1
        for item in sections["gear"]
        if item.get("activeItemSet") is True
        and re.search(r"Jewel Socket \d+$", str(item.get("slot") or ""))
    )
    raw_context = normalized.get("rawContext")
    raw_context = raw_context if isinstance(raw_context, dict) else {}
    xml = str(raw_context.get("rawXml") or "")
    status = "ok"
    assignments: list[dict[str, Any]] = []
    assignment_socket_kinds: dict[tuple[str, str], str] = {}
    root: ET.Element | None = None
    if xml:
        try:
            root = parse_pob_xml(xml)
        except ET.ParseError:
            root = None
        if root is not None:
            status = _tree_metadata_status(root)
            assignments = _jewel_socket_assignments(root)
            assignment_socket_kinds = _jewel_socket_kinds(root)
    active_assignments = [item for item in assignments if item["activeSpec"]]
    active_socketed_node_ids = {str(item["nodeId"]) for item in active_assignments}
    active_filled = [
        {
            **item,
            "socketKind": active_socket_kind_by_node.get(str(item["nodeId"]), "unknown"),
        }
        for item in active_assignments
        if str(item["nodeId"]) in active_allocated_node_ids
    ]
    active_unallocated = [
        {
            **item,
            "socketKind": assignment_socket_kinds.get(
                (str(item["specId"]), str(item["nodeId"])), "unknown"
            ),
        }
        for item in active_assignments
        if str(item["nodeId"]) not in active_allocated_node_ids
    ]
    active_empty = [
        {
            "nodeId": node_id,
            "specId": next(
                (
                    str(item.get("specId") or "")
                    for item in sections["passives"]
                    if str(item.get("nodeId") or "") == node_id and item.get("activeSpec") is True
                ),
                "",
            ),
            "socketKind": active_socket_kind_by_node.get(node_id, "unknown"),
        }
        for node_id in sorted(active_allocated_node_ids - active_socketed_node_ids)
    ]
    other_spec_socketed = [
        {
            **item,
            "socketKind": assignment_socket_kinds.get(
                (str(item["specId"]), str(item["nodeId"])), "unknown"
            ),
        }
        for item in assignments
        if not item["activeSpec"]
    ]
    tree_socketed = len(active_assignments)
    notes: list[str] = []
    if status != "ok":
        notes.append(
            "counts may be unreliable: passive-tree node metadata or the jewel socket mapping "
            "is unavailable for this packet"
        )
    if allocated:
        notes.append(
            "allocatedJewelSocketCount counts only the active passive spec's allocated "
            "jewel-socket nodes"
        )
    if tree_socketed:
        notes.append(
            "treeSocketedJewelCount counts jewels whose source socket is a passive-tree "
            "socket (resolved from the tree <Sockets> mapping)"
        )
    if embedded:
        notes.append(
            "embeddedJewelCount counts jewels in equipment jewel sockets of the active item "
            "set; an embedded jewel cannot fill an empty tree socket"
        )
    if allocated and tree_socketed < allocated:
        notes.append(
            f"{allocated - tree_socketed} allocated tree socket(s) carry no socketed tree "
            "jewel (empty or extraction gap); the review must declare the jewel state"
        )
    return {
        "allocatedJewelSocketCount": allocated,
        "treeSocketedJewelCount": tree_socketed,
        "embeddedJewelCount": embedded,
        "socketedJewelCount": tree_socketed + embedded,
        "activeAllocatedFilled": active_filled,
        "activeAllocatedEmpty": active_empty,
        "activeSocketedUnallocated": active_unallocated,
        "otherSpecSocketed": other_spec_socketed,
        "countNotes": notes,
        "status": status,
    }


def jewel_advisories(
    packet: dict[str, Any],
    sections: dict[str, list[dict[str, Any]]] | None = None,
) -> list[str]:
    counts = jewel_counts(packet, sections=sections)
    if counts["status"] in {"tree_data_missing", "sockets_absent"}:
        return [
            "passive-tree node metadata or the jewel socket mapping is unavailable for this "
            "packet, so allocated jewel sockets cannot be counted reliably; state the jewel "
            "situation explicitly in the review"
        ]
    advisories: list[str] = []
    if counts.get("activeAllocatedEmpty"):
        advisories.append(
            f"{len(counts['activeAllocatedEmpty'])} active-spec allocated jewel socket(s) are "
            "empty; the review must declare their state"
        )
    if counts.get("activeSocketedUnallocated"):
        advisories.append(
            f"{len(counts['activeSocketedUnallocated'])} active-spec jewel assignment(s) point "
            "at unallocated socket nodes; treat their effects as unverified"
        )
    if counts.get("otherSpecSocketed"):
        advisories.append(
            f"{len(counts['otherSpecSocketed'])} jewel assignment(s) belong to non-active passive "
            "specs and cannot satisfy active-spec jewel closure"
        )
    return advisories


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
    skill_groups = build_skill_evidence_manifest(normalized).get("activeSkillGroups") or []
    section_counts = {
        **{name: len(sections[name]) for name in RESEARCH_SECTIONS},
        "skill-groups": len(skill_groups),
    }
    return {
        "status": "ok",
        "packetId": str(normalized.get("packetId") or ""),
        "packetSafeHash": str(normalized.get("safeHash") or ""),
        "safeMetadata": safe_metadata,
        "sections": {
            name: {"itemCount": section_counts[name], "available": bool(section_counts[name])}
            for name in RESEARCH_READ_ORDER
        },
        "activeSets": _active_sets(normalized),
        "configIdentity": _configuration_summary(normalized),
        "jewelCounts": jewel_counts(packet, sections=sections),
        "jewelAdvisories": jewel_advisories(packet, sections=sections),
        **_unslotted_summary(normalized),
        "recommendedReadOrder": list(RESEARCH_READ_ORDER),
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
    """Return each root skill gem and the items physically socketed into it.

    PoB calls the container a ``socketGroup`` and serializes its gems as a flat list, but the
    character import builds that list from one root ``skillData`` followed by its
    ``socketedItems``.  Preserve that physical hierarchy instead of treating sibling active
    effects as competing support owners.
    """
    normalized = _unwrap_packet(packet)
    groups: list[dict[str, Any]] = []
    for item in _packet_sections(normalized)["skills"]:
        if not item.get("activeSkillSet") or not item.get("enabled"):
            continue
        skill_set_id = str(item.get("skillSetId") or "")
        group_index = int(item.get("groupIndex") or 0)
        group_ref = f"skill-set:{skill_set_id}:group:{group_index}"
        all_gems: list[tuple[int, dict[str, Any]]] = [
            (gem_index, gem)
            for gem_index, gem in enumerate(item.get("gems") or [], start=1)
        ]
        if not all_gems:
            continue
        root_gem_index, root_gem = all_gems[0]
        if root_gem.get("isSupport") or not str(root_gem.get("name") or ""):
            continue
        root_skill_ref = f"{group_ref}:root:{root_gem_index}"
        root_skill = {
            **_skill_manifest_entry(
                root_gem,
                gem_index=root_gem_index,
                active_skill_ref=f"{group_ref}:active:{root_gem_index}",
            ),
            "rootSkillRef": root_skill_ref,
            "physicalRole": "root_skill",
        }
        socketed_items = [
            {
                "name": str(gem.get("name") or ""),
                "skillId": str(gem.get("skillId") or ""),
                "gemId": str(gem.get("gemId") or ""),
                "gemIndex": gem_index,
                "socketedItemRef": f"{group_ref}:socketed:{gem_index}",
                "socketedUnderSkillRef": root_skill_ref,
                "itemKind": "support" if gem.get("isSupport") else "skill",
                "enabled": bool(gem.get("enabled")),
                "nameSource": str(gem.get("nameSource") or "gem_name"),
                "enableGlobal1": bool(gem.get("enableGlobal1")),
                "enableGlobal2": bool(gem.get("enableGlobal2")),
            }
            for gem_index, gem in all_gems[1:]
            if str(gem.get("name") or "")
        ]
        active_skills = [
            {
                **_skill_manifest_entry(
                    gem,
                    gem_index=gem_index,
                    active_skill_ref=f"{group_ref}:active:{gem_index}",
                ),
                "physicalRole": "root_skill" if gem_index == root_gem_index else "socketed_skill",
                **(
                    {}
                    if gem_index == root_gem_index
                    else {"socketedUnderSkillRef": root_skill_ref}
                ),
            }
            for gem_index, gem in all_gems
            if gem.get("enabled") and not gem.get("isSupport") and str(gem.get("name") or "")
        ]
        supports = [
            {
                "name": str(gem.get("name") or ""),
                "gemId": str(gem.get("gemId") or ""),
                "gemIndex": gem_index,
                "socketedItemRef": f"{group_ref}:socketed:{gem_index}",
                "socketedUnderSkillRef": root_skill_ref,
                "nameSource": str(gem.get("nameSource") or "gem_name"),
                "enableGlobal1": bool(gem.get("enableGlobal1")),
                "enableGlobal2": bool(gem.get("enableGlobal2")),
            }
            for gem_index, gem in all_gems[1:]
            if gem.get("enabled") and gem.get("isSupport") and str(gem.get("name") or "")
        ]
        groups.append(
            {
                "groupRef": group_ref,
                "rootSkillRef": root_skill_ref,
                "rootSkill": root_skill,
                "socketedItems": socketed_items,
                "slot": str(item.get("slot") or ""),
                "weaponSetScope": str(item.get("weaponSetScope") or "global"),
                "mainActiveSkill": str(item.get("mainActiveSkill") or ""),
                "mainActiveSkillCalcs": str(item.get("mainActiveSkillCalcs") or ""),
                "activeSkills": active_skills,
                "supports": supports,
            }
        )
    return {
        "activeSkillGroups": groups,
        "socketHierarchyPolicyVersion": 1,
        "noRawMatureBuildMaterial": True,
    }


def _skill_manifest_entry(
    gem: dict[str, Any], *, gem_index: int, active_skill_ref: str
) -> dict[str, Any]:
    return {
        "name": str(gem.get("name") or ""),
        "skillId": str(gem.get("skillId") or ""),
        "gemId": str(gem.get("gemId") or ""),
        "gemIndex": gem_index,
        "activeSkillRef": active_skill_ref,
        "nameSource": str(gem.get("nameSource") or "gem_name"),
        "enableGlobal1": bool(gem.get("enableGlobal1")),
        "enableGlobal2": bool(gem.get("enableGlobal2")),
        "enabled": bool(gem.get("enabled")),
    }


def _public_skill_group(group: dict[str, Any]) -> dict[str, Any]:
    """Project one socket group into the non-duplicated Researcher-facing hierarchy.

    ``activeSkills`` and ``supports`` are internal derived indexes over the same gems.  They
    remain available to acceptance diagnostics, but returning them beside ``rootSkill`` and
    ``socketedItems`` makes every gem appear twice and obscures the physical socket layout.
    """

    root = group.get("rootSkill")
    root = dict(root) if isinstance(root, dict) else {}
    root.pop("activeSkillRef", None)
    root.pop("physicalRole", None)
    root["itemKind"] = "skill"
    socketed_items = [
        dict(item) for item in group.get("socketedItems") or [] if isinstance(item, dict)
    ]
    return {
        "groupRef": str(group.get("groupRef") or ""),
        "rootSkillRef": str(group.get("rootSkillRef") or ""),
        "rootSkill": root,
        "socketedItems": socketed_items,
        "slot": str(group.get("slot") or ""),
        "weaponSetScope": str(group.get("weaponSetScope") or "global"),
    }


def read_packet_section(
    packet: dict[str, Any],
    *,
    section: str,
    cursor: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
    node_type: str | None = None,
    exclude_routing: bool = False,
    response_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read one structured packet section with stable, character-bounded pagination.

    ``node_type`` filters the passives section by node kind (keystone/notable/jewel_socket/
    granted_jewel_socket/ascendancy/mastery, or ``normal`` for small nodes); it is ignored
    for other sections.
    ``exclude_routing`` (passives + normal only) drops pure routing/attribute nodes whose
    stats add no build signal (e.g. "+5 to any Attribute"), to cut low-information pagination.
    """
    normalized_section = str(section or "").strip().lower()
    if normalized_section not in RESEARCH_SECTIONS and normalized_section != "skill-groups":
        raise ValueError("section must be one of: " + ", ".join(RESEARCH_READ_ORDER))
    start = max(0, int(cursor or 0))
    page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    if normalized_section == "skill-groups":
        manifest = build_skill_evidence_manifest(packet)
        items = [
            _public_skill_group(group)
            for group in manifest.get("activeSkillGroups") or []
            if isinstance(group, dict)
        ]
    else:
        items = _packet_sections(_unwrap_packet(packet))[normalized_section]
    if normalized_section == "passives" and str(node_type or "").strip():
        items = _filter_passive_items(items, str(node_type).strip())
    if (
        normalized_section == "passives"
        and str(node_type or "").strip() == "normal"
        and exclude_routing
    ):
        items = [item for item in items if not _is_pure_routing_passive(item)]
    source_count = len(items)
    if normalized_section in {"config", "config-sets"}:
        items = _fragment_configuration_items(items)
    envelope: dict[str, Any] = {
        **(response_metadata or {}),
        "status": "ok",
        "section": normalized_section,
        "cursor": start,
        "limit": page_size,
        "totalCount": len(items),
        "noRawMatureBuildMaterial": True,
    }
    if normalized_section in {"config", "config-sets", "build", "pob-readback"}:
        envelope["configIdentity"] = _configuration_summary(packet)
    if source_count != len(items):
        envelope["sourceItemCount"] = source_count
        envelope["fragmentPolicy"] = (
            "For evidence_fragment rows, concatenate jsonFragment by sourceItemIndex and "
            "fragmentIndex, then parse JSON to recover the exact source item. Follow nextCursor."
        )
    if normalized_section in {"passives", "gear", "skills"}:
        envelope["advisories"] = [*_cross_axis_advisories(packet), *jewel_advisories(packet)]
    elif normalized_section == "skill-groups":
        envelope["advisories"] = _cross_axis_advisories(packet)
    return _bounded_response(
        items, start=start, limit=page_size, envelope=envelope,
        allow_item_truncation=normalized_section not in {"config", "config-sets"},
    )


def _bounded_response(
    items: list[dict[str, Any]], *, start: int, limit: int, envelope: dict[str, Any],
    allow_item_truncation: bool = True,
) -> dict[str, Any]:
    """Budget the final response, including metadata, identity summaries and warnings."""
    def response(page: list[dict[str, Any]], index: int) -> dict[str, Any]:
        next_cursor = index if index < len(items) else None
        result = {
            **envelope, "items": page, "returnedCount": len(page),
            "nextCursor": next_cursor, "complete": next_cursor is None,
        }
        _attach_continuity_warning(result, start=start, limit=limit, next_cursor=next_cursor)
        return result

    page: list[dict[str, Any]] = []
    index = min(start, len(items))
    while index < len(items) and len(page) < limit:
        candidate = response([*page, items[index]], index + 1)
        if _response_chars(candidate) > MAX_RESPONSE_CHARS:
            if not page:
                # Legacy sections retain their existing single-item bounded view. Config
                # sections were losslessly fragmented before pagination and never use it.
                if not allow_item_truncation:
                    raise ValueError("transient research response metadata exceeds the bounded output limit")
                truncated = _truncate_item(items[index])
                candidate = response([truncated], index + 1)
                candidate["itemDetailTruncated"] = True
                if _response_chars(candidate) > MAX_RESPONSE_CHARS:
                    raise ValueError("transient research response metadata exceeds the bounded output limit")
                return candidate
            break
        page.append(items[index])
        index += 1
    result = response(page, index)
    if _response_chars(result) > MAX_RESPONSE_CHARS:
        raise ValueError("transient research response metadata exceeds the bounded output limit")
    return result


def _response_chars(value: dict[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def _fragment_configuration_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Losslessly page oversized config identities or inputs without limiting set count."""
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if _response_chars(item) <= 4_000:
            result.append(item)
            continue
        serialized = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fragments = [serialized[offset:offset + 1_200] for offset in range(0, len(serialized), 1_200)]
        result.extend({
            "kind": "evidence_fragment", "sourceItemIndex": index,
            "fragmentIndex": fragment_index, "fragmentCount": len(fragments),
            "jsonFragment": fragment,
        } for fragment_index, fragment in enumerate(fragments))
    return result


def _attach_continuity_warning(
    result: dict[str, Any], *, start: int, limit: int, next_cursor: int | None
) -> None:
    """Attach ``continuityWarning`` (only when the character budget truncated the page)."""
    warning = _continuity_warning(start=start, limit=limit, next_cursor=next_cursor)
    if warning:
        result["continuityWarning"] = warning


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


def _is_pure_routing_passive(item: dict[str, Any]) -> bool:
    """True for normal nodes whose stats carry no build signal (pure routing/attribute nodes)."""
    stats = [str(value) for value in (item.get("stats") or []) if str(value).strip()]
    if not stats:
        return True
    return all(_is_any_attribute_stat(stat) for stat in stats)


def _is_any_attribute_stat(stat: str) -> bool:
    lowered = stat.strip().casefold()
    return lowered == "+5 to any attribute" or lowered.startswith("+5 to any attribute")


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
    response_metadata: dict[str, Any] | None = None,
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
    result = _bounded_response(matches, start=0, limit=max_results, envelope={
        **(response_metadata or {}),
        "status": "ok",
        "query": str(query).strip(),
        "section": str(section or "all"),
        "totalMatchCount": len(matches),
        "noRawMatureBuildMaterial": True,
    })
    result["matches"] = result.pop("items")
    result["truncated"] = not result.pop("complete")
    result.pop("nextCursor", None)
    return result


def _unwrap_packet(packet: dict[str, Any]) -> dict[str, Any]:
    nested = packet.get("packet")
    return nested if isinstance(nested, dict) else packet


def _packet_sections(packet: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    raw_context = packet.get("rawContext")
    raw_context = raw_context if isinstance(raw_context, dict) else {}
    xml = str(raw_context.get("rawXml") or "")
    readback = validated_pob_readback(packet)
    readback_items = [dict(readback)] if isinstance(readback, dict) and readback else []
    if not xml:
        return {
            **{name: [] for name in RESEARCH_SECTIONS},
            "pob-readback": readback_items,
        }
    try:
        root = parse_pob_xml(xml)
    except ET.ParseError as exc:
        raise ValueError("transient research packet contains invalid PoB XML") from exc
    gear_items = _gear_items(root)
    return {
        "skills": _skill_items(root),
        "gear": gear_items,
        "passives": _passive_items(root),
        "config": _config_items(root),
        "config-sets": config_set_identity(root)["configSets"],
        "build": _build_items(root),
        "jewels": _tree_socket_jewels(gear_items),
        "pob-readback": readback_items,
    }


def _tree_socket_jewels(gear_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tree-socketed jewels (socketSource == "tree_socket") as a dedicated section.

    The gear section keeps these items too (jewel_counts relies on them); this view is a
    convenience for researchers who only need the tree jewels and their affix text.
    """
    return [item for item in gear_items if item.get("socketSource") == "tree_socket"]


def _skill_items(root: ET.Element) -> list[dict[str, Any]]:
    skills = root.find("Skills")
    if skills is None:
        return []
    result: list[dict[str, Any]] = []
    for skill_set, skill_set_id, active in _selection_axis(root, "skillSet")["containers"]:
        for group_index, group in enumerate(skill_set.findall("Skill"), start=1):
            gems = []
            for gem in group.findall("Gem"):
                name = str(
                    gem.get("nameSpec") or gem.get("skillId") or gem.get("gemId") or ""
                ).strip()
                if not name:
                    continue
                name_source = (
                    "gem_name"
                    if gem.get("nameSpec")
                    else "internal_id"
                    if gem.get("skillId")
                    else "gem_id"
                )
                gems.append(
                    {
                        "name": name,
                        "skillId": str(gem.get("skillId") or ""),
                        "gemId": str(gem.get("gemId") or ""),
                        "nameSource": name_source,
                        "level": _optional_int(gem.get("level")),
                        "quality": _optional_int(gem.get("quality")),
                        "enabled": _xml_bool(gem.get("enabled"), default=True),
                        "isSupport": _is_support_gem(gem),
                        "enableGlobal1": _xml_bool(gem.get("enableGlobal1"), default=True),
                        "enableGlobal2": _xml_bool(gem.get("enableGlobal2"), default=False),
                    }
                )
            result.append(
                {
                    "skillSetId": skill_set_id,
                    "sourceSkillSetId": str(skill_set.get("id") or ""),
                    "activeSkillSet": active,
                    "groupIndex": group_index,
                    "enabled": _xml_bool(group.get("enabled"), default=True),
                    "slot": str(group.get("slot") or ""),
                    "weaponSetScope": _skill_group_weapon_set_scope(str(group.get("slot") or "")),
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
    by_id = {_config_id(item.get("id")): item for item in items.findall("Item") if _config_id(item.get("id"))}
    referenced: set[str] = set()
    result: list[dict[str, Any]] = []
    for item_set, set_id, active in _selection_axis(root, "itemSet")["containers"]:
        for slot in item_set.findall("Slot"):
            item_id = _config_id(slot.get("itemId")) or "0"
            referenced.add(item_id)
            node = by_id.get(item_id)
            if node is None:
                continue
            parsed = _parse_item_text(node.text or "")
            result.append(
                {
                    "itemSetId": set_id,
                    "sourceItemSetId": str(item_set.get("id") or ""),
                    "activeItemSet": active,
                    "slot": str(slot.get("name") or ""),
                    "itemId": item_id,
                    **parsed,
                }
            )
    # Tree jewels are bare <Item> elements referenced only by <Spec><Sockets> (their
    # socket is a passive-tree node), so a slot-based walk drops them. Resolve them via
    # the authoritative socket mapping; items outside the active spec's sockets are other
    # trees' configuration and are ignored entirely, and unslotted inventory items are
    # counted separately (see _unslotted_items) instead of polluting the gear section.
    socket_map = _jewel_socket_map(root)
    for item_id, node in sorted(by_id.items()):
        if item_id in referenced:
            continue
        mapping = socket_map.get(item_id)
        if mapping is None or not mapping["activeSpec"]:
            continue
        parsed = _parse_item_text(node.text or "")
        result.append(
            {
                "itemSetId": "",
                "activeItemSet": True,
                "socketSource": "tree_socket",
                "slot": f"Jewel {mapping['nodeId']}",
                "specId": mapping["specId"],
                "itemId": item_id,
                **parsed,
            }
        )
    return result


def _unslotted_summary(normalized: dict[str, Any]) -> dict[str, Any]:
    """Summarize inventory items that are neither equipped in an ItemSet slot nor socketed
    as a tree jewel. Bounded name list keeps the summary small; full items never enter the
    gear section so Researcher gear analysis stays about the equipped build.
    """
    raw_xml = str((normalized.get("rawContext") or {}).get("rawXml") or "")
    if not raw_xml:
        return {"unslottedItemCount": 0, "unslottedItemNames": []}
    try:
        root = parse_pob_xml(raw_xml)
    except ET.ParseError:
        return {"unslottedItemCount": 0, "unslottedItemNames": []}
    items = root.find("Items")
    if items is None:
        return {"unslottedItemCount": 0, "unslottedItemNames": []}
    by_id = {_config_id(item.get("id")): item for item in items.findall("Item") if _config_id(item.get("id"))}
    referenced: set[str] = set()
    for item_set, _set_id, _active in _selection_axis(root, "itemSet")["containers"]:
        for slot in item_set.findall("Slot"):
            referenced.add(_config_id(slot.get("itemId")) or "0")
    socket_map = _jewel_socket_map(root)
    unslotted: list[dict[str, str]] = []
    for item_id, node in sorted(by_id.items()):
        if item_id in referenced or item_id in socket_map:
            continue
        parsed = _parse_item_text(node.text or "")
        name = str(parsed.get("name") or str(parsed.get("base") or "") or f"item-{item_id}")
        unslotted.append({"itemId": item_id, "name": name})
    return {
        "unslottedItemCount": len(unslotted),
        "unslottedItemNames": [str(item["name"]) for item in unslotted[:10]],
    }


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
    result: list[dict[str, Any]] = []
    for spec, spec_id, is_active in _selection_axis(root, "passiveSpec")["containers"]:
        tree_version = str(spec.get("treeVersion") or "")
        node_metadata = _passive_node_metadata(tree_version)
        # Weapon-set members come from the <WeaponSet1/2 nodes=...> child elements that
        # PoB actually writes (PassiveSpec:Save); the nodes1/nodes2 attributes it never
        # writes are not read. Nodes allocated to a weapon set appear BOTH in the spec's
        # `nodes` attribute and the WeaponSet element, so the allocated rows carry a
        # weaponSet marker instead of duplicating rows.
        weapon_set_members: dict[int, set[str]] = {}
        for weapon_elem in spec:
            tag = str(weapon_elem.tag or "")
            if tag in {"WeaponSet1", "WeaponSet2"}:
                weapon_set = 1 if tag == "WeaponSet1" else 2
                weapon_set_members.setdefault(weapon_set, set()).update(
                    _csv_values(weapon_elem.get("nodes"))
                )
        allocated_ids: set[str] = set()
        result.append(
            {
                "kind": "spec",
                "specId": spec_id,
                "sourceSpecId": str(spec.get("id") or ""),
                "activeSpec": is_active,
                "treeVersion": tree_version,
                "classId": str(spec.get("classId") or ""),
                "ascendClassId": str(spec.get("ascendClassId") or ""),
                "allocatedNodeCount": len(_csv_values(spec.get("nodes"))),
                "weaponSet1NodeCount": len(weapon_set_members.get(1, set())),
                "weaponSet2NodeCount": len(weapon_set_members.get(2, set())),
            }
        )
        for node_id in _csv_values(spec.get("nodes")):
            allocated_ids.add(node_id)
            weapon_set = (
                1
                if node_id in weapon_set_members.get(1, set())
                else 2
                if node_id in weapon_set_members.get(2, set())
                else None
            )
            result.append(
                {
                    "kind": "allocated_node",
                    "specId": spec_id,
                    "activeSpec": is_active,
                    "nodeId": node_id,
                    "weaponSet": weapon_set,
                    **node_metadata.get(node_id, {}),
                }
            )
        for weapon_set, members in sorted(weapon_set_members.items()):
            for node_id in sorted(members):
                if node_id in allocated_ids:
                    continue
                result.append(
                    {
                        "kind": "weapon_set_node",
                        "specId": spec_id,
                        "activeSpec": is_active,
                        "weaponSet": weapon_set,
                        "nodeId": node_id,
                        **node_metadata.get(node_id, {}),
                    }
                )
        for mastery in _csv_values(spec.get("masteryEffects")):
            result.append(
                {
                    "kind": "mastery_effect",
                    "specId": spec_id,
                    "activeSpec": is_active,
                    "value": mastery,
                }
            )
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
                ("containJewelSocket", "granted_jewel_socket"),
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


def config_set_identity(root: ET.Element) -> dict[str, Any]:
    """Describe source configuration identity without applying PoB's fallback selection.

    ConfigTab.Load maps legacy inputs to set 1, while explicit ConfigSets are identified
    numerically. Its fallback to the first set is not evidence of author intent.
    """
    configs = root.findall("Config")
    config = configs[0] if configs else None
    containers = config.findall("ConfigSet") if config is not None else []
    explicit = bool(containers)
    issues: list[str] = []
    if len(configs) > 1:
        issues.append("multiple_config_sections")
    declared = str(config.get("activeConfigSet") or "") if config is not None else ""
    if explicit and not declared:
        issues.append("missing_active_config_set")
    active = _config_id(declared) if declared else (None if explicit else "1")
    if declared and active is None:
        issues.append("invalid_active_config_set")
    if explicit and any(child.tag in {"Input", "Placeholder"} for child in config):
        issues.append("mixed_legacy_and_config_sets")
    if not explicit:
        containers = [config] if config is not None else []
    sets: list[dict[str, Any]] = []
    for index, container in enumerate(containers, start=1):
        set_id = _config_id(container.get("id")) if explicit else "1"
        if set_id is None:
            issues.append("invalid_config_set_id")
        sets.append({
            "configSetId": set_id,
            "configSetIndex": index,
            "title": str(container.get("title") or "Default") if explicit else "Default",
        })
        seen: set[tuple[str, str]] = set()
        for child in container:
            if child.tag not in {"Input", "Placeholder"}:
                continue
            name = str(child.get("name") or "")
            key = (child.tag, name)
            if not name:
                issues.append("missing_config_input_name")
            if key in seen:
                issues.append("duplicate_config_input")
            seen.add(key)
            value_type, value = _config_value(child)
            if value_type == "unknown":
                issues.append("invalid_config_input_type")
            elif value_type == "boolean" and value not in {"true", "false"}:
                issues.append("invalid_config_boolean")
            elif value_type == "number":
                try:
                    finite = math.isfinite(float(value))
                except ValueError:
                    finite = False
                if not finite:
                    issues.append("invalid_config_number")
    ids = [item["configSetId"] for item in sets]
    if len(ids) != len(set(ids)):
        issues.append("duplicate_config_set_id")
    if active is not None and active not in (ids or ["1"]):
        issues.append("active_config_set_not_found")
    status = "resolved" if explicit else "legacy_default" if config is not None else "implicit_default"
    if issues:
        active = None
        status = "invalid"
    for item in sets:
        item["isActive"] = item["configSetId"] == active if active is not None else None
    return {
        "status": status,
        "activeConfigSet": active,
        "issues": sorted(set(issues)),
        "configSets": sets,
    }


def _config_id(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not re.fullmatch(r"[0-9]{1,9}", text) or int(text) < 1:
        return None
    return str(int(text))


def _config_value(node: ET.Element) -> tuple[str, str]:
    types = [key for key in ("number", "string", "boolean") if node.get(key) is not None]
    if len(types) != 1:
        return "unknown", ""
    value_type = types[0]
    return value_type, str(node.get(value_type) or "")


def configuration_manifest(packet: dict[str, Any]) -> dict[str, Any]:
    normalized = _unwrap_packet(packet)
    raw = normalized.get("rawContext") or {}
    xml = str(raw.get("rawXml") or "") if isinstance(raw, dict) else ""
    if not xml:
        return {"status": "unavailable", "activeConfigSet": None, "issues": ["missing_source_xml"], "configSets": []}
    try:
        return config_set_identity(parse_pob_xml(xml))
    except ET.ParseError as exc:
        raise ValueError("transient research packet contains invalid PoB XML") from exc


def _configuration_summary(packet: dict[str, Any]) -> dict[str, Any]:
    identity = configuration_manifest(packet)
    return {
        key: value for key, value in identity.items() if key != "configSets"
    } | {
        "configSetCount": len(identity["configSets"]),
        "configSetsSection": "config-sets",
    }


def active_set_identity(root: ET.Element) -> dict[str, Any]:
    """Bind independent PoB selection axes; Spec identity is its one-based list position."""
    config = config_set_identity(root)
    active: dict[str, str | None] = {"configSet": config["activeConfigSet"]}
    issues = [f"config:{issue}" for issue in config["issues"]]
    for field in ("skillSet", "itemSet", "passiveSpec"):
        axis = _selection_axis(root, field)
        active[field] = axis["activeId"]
        issues.extend(f"{field}:{issue}" for issue in axis["issues"])
    return {"activeSets": active, "issues": issues}


def _selection_axis(root: ET.Element, field: str) -> dict[str, Any]:
    """Locate source instances using the same identities as the pinned PoB loaders.

    Explicit skill/item sets use numeric IDs. TreeTab appends Specs in document order
    and ignores their extra id attributes; the legacy root Spec is its only first spec.
    Invalid selectors preserve readable containers, but never mark one authoritative.
    """
    section, child_tag, selector = {
        "skillSet": ("Skills", "SkillSet", "activeSkillSet"),
        "itemSet": ("Items", "ItemSet", "activeItemSet"),
        "passiveSpec": ("Tree", "Spec", "activeSpec"),
    }[field]
    parents = root.findall(section)
    parent = parents[0] if parents else None
    children = parent.findall(child_tag) if parent is not None else []
    explicit = bool(children)
    declared = str(parent.get(selector) or "") if parent is not None else ""
    chosen = _config_id(declared) if declared else "1"
    issues: list[str] = []
    if len(parents) > 1:
        issues.append("multiple_sections")
    if len(children) > 1 and not declared:
        issues.append("missing_active_selector")
    if field == "passiveSpec":
        legacy = root.findall("Spec")
        if len(legacy) > 1 or (legacy and parent is not None):
            issues.append("ambiguous_legacy_spec")
        if parent is None:
            children = legacy
        ids = [str(index) for index in range(1, len(children) + 1)]
    else:
        ids = [_config_id(child.get("id")) for child in children]
        if None in ids or len(ids) != len(set(ids)):
            issues.append("invalid_or_duplicate_set_id")
        legacy_tag = "Skill" if field == "skillSet" else "Slot"
        if explicit and parent.findall(legacy_tag):
            issues.append("mixed_legacy_and_sets")
        if not explicit and parent is not None:
            children, ids = [parent], ["1"]
    if chosen is None or chosen not in (ids or ["1"]):
        issues.append("active_selector_not_found")
    active_id = None if issues else chosen
    return {
        "activeId": active_id,
        "issues": issues,
        "containers": [
            (child, set_id, active_id is not None and set_id == active_id)
            for child, set_id in zip(children, ids, strict=True)
        ],
    }


def source_snapshot_hash(xml: str) -> str:
    """Fingerprint the exact transient source, including configuration placeholders."""
    return "sha256:" + hashlib.sha256(xml.encode("utf-8")).hexdigest()


def validated_pob_readback(packet: dict[str, Any]) -> dict[str, Any] | None:
    """Keep old or mismatched numeric receipts from being treated as active-config evidence."""
    normalized = _unwrap_packet(packet)
    readback = normalized.get("pobReadback")
    if not isinstance(readback, dict) or not readback:
        return None
    if readback.get("status") != "available":
        return dict(readback)
    identity = configuration_manifest(normalized)
    binding = readback.get("stateBinding") or {}
    raw = normalized.get("rawContext") or {}
    xml = str(raw.get("rawXml") or "") if isinstance(raw, dict) else ""
    sets = active_set_identity(parse_pob_xml(xml)) if xml else {"activeSets": {}, "issues": ["missing_source_xml"]}
    metadata = normalized.get("safeMetadata") or {}
    source_ref = str(metadata.get("sourceRef") or "") if isinstance(metadata, dict) else ""
    if (
        identity["activeConfigSet"] is None
        or not isinstance(binding, dict)
        or binding.get("activeConfigSet") != identity["activeConfigSet"]
        or binding.get("sourceActiveConfigSet") != identity["activeConfigSet"]
        or binding.get("configScope") != "source_active_config_set"
        or sets["issues"]
        or binding.get("activeSets") != sets["activeSets"]
        or binding.get("sourceActiveSets") != sets["activeSets"]
        or binding.get("sourceSnapshotHash") != source_snapshot_hash(xml)
        or (
            requires_preserved_input_semantics(xml)
            and (
                binding.get("xmlInputSemanticsVersion") != XML_INPUT_SEMANTICS_VERSION
                or binding.get("sourceInputStateHash") != build_state_hash(xml)
            )
        )
        or not source_ref
        or readback.get("sourceHashRef") != source_ref
    ):
        return {
            "status": "unavailable",
            "errorCode": "config_readback_binding_missing_or_mismatched",
            "noRawMatureBuildMaterial": True,
        }
    return dict(readback)


def _config_items(root: ET.Element) -> list[dict[str, Any]]:
    config = root.find("Config")
    if config is None:
        return []
    identity = config_set_identity(root)
    containers = config.findall("ConfigSet") or [config]
    result: list[dict[str, Any]] = []
    for container, set_identity in zip(containers, identity["configSets"], strict=True):
        for input_node in container:
            if input_node.tag not in {"Input", "Placeholder"}:
                continue
            value_type, value = _config_value(input_node)
            result.append({
                **set_identity,
                "kind": input_node.tag.lower(),
                "name": str(input_node.get("name") or ""),
                "value": value,
                "valueType": value_type,
            })
    return result


def _build_items(root: ET.Element) -> list[dict[str, Any]]:
    build = root.find("Build")
    active_sets = active_set_identity(root)["activeSets"]
    if build is None:
        return []
    return [
        {
            "className": str(build.get("className") or ""),
            "ascendancy": str(build.get("ascendClassName") or ""),
            "level": _optional_int(build.get("level")),
            "mainSocketGroup": str(build.get("mainSocketGroup") or ""),
            "activeSkillSet": active_sets["skillSet"],
            "activeItemSet": active_sets["itemSet"],
            "activeSpec": active_sets["passiveSpec"],
            "activeConfigSet": active_sets["configSet"],
        }
    ]


def _active_sets(packet: dict[str, Any]) -> dict[str, str | None]:
    normalized = _unwrap_packet(packet)
    raw = normalized.get("rawContext") or {}
    xml = str(raw.get("rawXml") or "") if isinstance(raw, dict) else ""
    if not xml:
        return dict.fromkeys(("skillSet", "itemSet", "passiveSpec", "configSet"))
    return active_set_identity(parse_pob_xml(xml))["activeSets"]


def _continuity_warning(*, start: int, limit: int, next_cursor: int | None) -> str | None:
    """Return an explicit warning when the character budget truncated a page.

    ``_bounded_response`` stops as soon as the next item would exceed the response budget, so
    a page can return fewer than ``limit`` items with ``complete=false`` and a
    ``nextCursor`` strictly below ``cursor + limit``. Callers that resume at
    ``cursor + limit`` (instead of the returned ``nextCursor``) silently skip the items in
    between; the warning makes that failure mode visible instead of silent.
    """
    if next_cursor is None or next_cursor >= start + limit:
        return None
    return (
        f"page truncated by the response character budget: {next_cursor - start} of up to "
        f"{limit} item(s) fit this page (cursor {start} -> nextCursor {next_cursor}). Resume "
        "at nextCursor only — never at cursor+limit, which would skip the truncated items."
    )


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


def _skill_group_weapon_set_scope(slot: str) -> str:
    normalized = str(slot or "").strip()
    if re.match(r"^Weapon [12] Swap(?:\s|$)", normalized, re.IGNORECASE):
        return "weapon_set_2"
    if re.match(r"^Weapon [12](?:\s|$)", normalized, re.IGNORECASE):
        return "weapon_set_1"
    return "global"


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
