"""Source observations only: analysis and explanations remain the external Agent's work."""

from __future__ import annotations

import json

from server.compute.pob_xml_input import parse_pob_xml
from server.knowledge import db, research_packet
from . import localization
from .storage import fingerprint


def packet(xml: str, meta: dict) -> dict:
    return {
        "packetId": "study-" + meta["sourceHash"][:16],
        "safeHash": meta["sourceHash"],
        "safeMetadata": {"gamePatch": meta["sourcePatch"], "sourceType": meta["sourceType"]},
        "rawContext": {"rawXml": xml},
    }


def _exact(table: str, name: str, identity: str = "") -> dict | None:
    # Table names are internal constants, never caller-authored query syntax.
    con = db._conn()
    rows = (
        con.execute(f"SELECT id, name, raw FROM {table} WHERE id = ?", (identity,)).fetchall()
        if identity
        else []
    )
    if not rows:
        rows = con.execute(f"SELECT id, name, raw FROM {table} WHERE name = ?", (name,)).fetchall()
    if len(rows) != 1:
        return None
    try:
        raw = json.loads(rows[0]["raw"])
    except (ValueError, TypeError):
        raw = {}
    return {"id": rows[0]["id"], "name": rows[0]["name"], "raw": raw}


def inventory(xml: str, meta: dict) -> dict:
    from .component_icons import missing_base_names

    source = packet(xml, meta)
    sections = research_packet._packet_sections(source)
    root = parse_pob_xml(xml)
    identity = research_packet.active_set_identity(root)
    components: dict[str, dict] = {}
    locators: dict[str, dict] = {}

    def add(kind: str, name: str, key: str, source_id: str, **extra):
        ref = (
            "c-"
            + fingerprint({"source": meta["sourceHash"], "kind": kind, "sourceId": source_id})[:20]
        )
        components[ref] = {
            "ref": ref,
            "kind": kind,
            "identity": key,
            "name": localization.resolve_name(name, key, meta["sourcePatch"]),
            "sourceId": source_id,
            **extra,
        }
        return ref

    for group in sections["skills"]:
        if not group["activeSkillSet"] or not group["enabled"]:
            continue
        group_id = f"skill-set:{group['skillSetId']}:group:{group['groupIndex']}"
        for index, gem in enumerate(group["gems"], 1):
            if not gem["enabled"]:
                continue
            exact = _exact("gems", gem["name"], gem["gemId"])
            key = exact["id"] if exact else gem["gemId"] or gem["skillId"] or gem["name"]
            ref = add(
                "support" if gem["isSupport"] else "skill",
                gem["name"]
                if gem["nameSource"] == "gem_name"
                else exact["name"]
                if exact
                else gem["name"],
                key,
                f"{group_id}:gem:{index}",
                groupRef=group_id,
                level=gem.get("level"),
                quality=gem.get("quality"),
                effectId=gem.get("skillId"),
                enableGlobal1=gem.get("enableGlobal1"),
                enableGlobal2=gem.get("enableGlobal2"),
                weaponSetScope=group["weaponSetScope"],
            )
            locators[ref] = {
                "kind": "gem",
                "skillSetId": group["skillSetId"],
                "groupIndex": group["groupIndex"],
                "gemIndex": index,
                "name": gem["name"],
                "isSupport": gem["isSupport"],
            }
    observed_bases = missing_base_names(xml, sections["gear"])
    for item in sections["gear"]:
        if not item["activeItemSet"]:
            continue
        unique = item["rarity"].lower() == "unique"
        base_name = item["base"] or observed_bases.get(item["slot"], "")
        base = _exact("items", base_name)
        name = item["name"] if unique else base_name or item["name"]
        key = ("unique:" + item["name"]) if unique else (base or {}).get("id", name)
        ref = add(
            "jewel" if item.get("socketSource") == "tree_socket" else "gear",
            name,
            key,
            f"item-set:{item['itemSetId']}:slot:{item['slot']}:item:{item['itemId']}",
            slot=item["slot"],
            rarity=item["rarity"],
            sourceDisplayName=item["name"],
            baseName=base_name,
            displayAliases=[item["name"]] if item["name"] != name else [],
            augmentIconRefs=[
                record["id"]
                for line in item.get("modifiers", [])
                if line.startswith("Rune: ")
                and (record := _exact("items", line[6:].strip())) is not None
                and record["raw"].get("item_class") == "SoulCore"
            ],
        )
        locators[ref] = {
            "kind": "item",
            "slot": item["slot"],
            "itemId": item["itemId"],
            "itemSetId": item["itemSetId"],
            "base": item["base"],
            "unique": unique,
        }
    specs = [x for x in sections["passives"] if x.get("kind") == "spec" and x.get("activeSpec")]
    tree_version = specs[0]["treeVersion"] if len(specs) == 1 else ""
    for node in sections["passives"]:
        if not node.get("activeSpec") or node.get("kind") not in {
            "allocated_node",
            "weapon_set_node",
        }:
            continue
        ref = add(
            "ascendancy" if node.get("isAscendancyPassive") else "passive",
            node.get("name") or node["nodeId"],
            f"passive:{tree_version}:{node['nodeId']}",
            f"spec:{node['specId']}:node:{node['nodeId']}",
            stats=node.get("stats", []),
            nodeTypes=node.get("nodeTypes", []),
            nodeId=node["nodeId"],
            weaponSet=node.get("weaponSet"),
            routing=research_packet._is_pure_routing_passive(node),
        )
        locators[ref] = {"kind": "passive", "nodeId": node["nodeId"], "specId": node["specId"]}
    build = sections["build"][0] if sections["build"] else {}
    return {
        "components": components,
        "locators": locators,
        "activeSets": identity["activeSets"],
        "build": {key: build.get(key) for key in ("className", "ascendancy", "level")},
        "treeVersion": tree_version,
    }
