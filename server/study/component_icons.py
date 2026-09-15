"""Presentation identities for equipment, augments and exact passive nodes."""

from __future__ import annotations

import json
import re
from pathlib import Path

from server import paths
from server.knowledge import db
from .storage import fingerprint


def extend_catalog(catalog: dict, components: dict, extra_refs=()) -> dict:
    result = dict(catalog)
    wanted = {c["identity"] for c in components.values()} | set(extra_refs)
    for c in components.values():
        wanted.update(c.get("augmentIconRefs", []))
    con = db._conn()
    for identity in sorted(wanted):
        if identity in result or identity.startswith(("passive:", "unique:")):
            continue
        row = con.execute("SELECT id,name,raw FROM items WHERE id=?", (identity,)).fetchone()
        if row:
            raw = json.loads(row["raw"])
            entry = {
                "identity": identity,
                "name": row["name"],
                "kind": "socketable" if raw.get("item_class") == "SoulCore" else "gear",
                "iconKind": "item_base",
                "iconPath": raw.get("visual_identity", {}).get("dds_file"),
                "itemClass": raw.get("item_class"),
                "sourceRef": "corpus-item:sha256:" + fingerprint(raw),
            }
            entry["bindingHash"] = fingerprint(entry)
            result[identity] = entry
    source = Path(__file__).with_name("data") / "unique_icons.json"
    if source.is_file():
        dataset = json.loads(source.read_text("utf-8"))
        for raw in dataset["entries"]:
            if raw["identity"] not in wanted:
                continue
            entry = {
                **raw,
                "sourceRef": "repoe-uniques:sha256:" + dataset["sourceSha256"],
                "sourceCommit": dataset["sourceCommit"],
            }
            entry["bindingHash"] = fingerprint(entry)
            result[entry["identity"]] = entry
    versions = {}
    for identity in wanted:
        match = re.fullmatch(r"passive:([0-9_]+):([0-9]+)", identity)
        if match:
            versions.setdefault(match[1], set()).add(match[2])
    for version, node_ids in versions.items():
        file = paths.pob_src_dir() / "TreeData" / version / "tree.json"
        if not file.is_file():
            continue
        raw = file.read_bytes()
        tree = json.loads(raw)
        nodes = tree.get("nodes", {})
        sprite_map = {}
        for filename, coordinates in tree.get("ddsCoords", {}).items():
            if not re.fullmatch(r"skills_[0-9]+_[0-9]+_BC1\.dds\.zst", filename):
                continue
            texture = file.parent / filename
            if texture.is_file():
                digest = fingerprint(texture.read_bytes())
                for icon_path, layer in coordinates.items():
                    sprite_map[icon_path] = {
                        "treeVersion": version,
                        "file": filename,
                        "layer": layer,
                        "sha256": digest,
                    }
        for node_id in node_ids:
            node = nodes.get(node_id)
            if not node or node.get("isAscendancyStart") or node.get("classStartIndex") is not None:
                continue
            identity = f"passive:{version}:{node_id}"
            entry = {
                "identity": identity,
                "name": node.get("name", node_id),
                "kind": "ascendancy" if node.get("ascendancyName") else "passive",
                "iconPath": node.get("icon"),
                "nodeId": node_id,
                "treeVersion": version,
                "sourceRef": "pob-tree:sha256:" + fingerprint(raw),
                "atlas": sprite_map.get(node.get("icon")),
            }
            entry["bindingHash"] = fingerprint(entry)
            result[identity] = entry
    for component in components.values():
        identity = component["identity"]
        if component["kind"] in {"gear", "jewel"} and identity not in result:
            missing = {
                "identity": identity,
                "name": component["name"]["en"],
                "kind": "gear",
                "iconPath": None,
                "sourceRef": "source-item:" + component["ref"],
            }
            missing["bindingHash"] = fingerprint(missing)
            result[identity] = missing
    return result


def missing_base_names(xml: str, items: list[dict]) -> dict:
    """Use disposable PoB readback when a magic item has no separate base header."""
    missing = [item for item in items if not item.get("base") and item.get("activeItemSet")]
    if not missing:
        return {}
    from server.compute.engine import PobEngine
    from server.knowledge.research_packet import _packet_sections

    try:
        with PobEngine(show_engine_logs=False) as engine:
            engine.load_build_xml(xml, name="study-item-identities")
            gear = engine.get_build().get("gear", {})
            reread = _packet_sections(
                {
                    "packetId": "study-item-identities",
                    "safeHash": "readback",
                    "safeMetadata": {},
                    "rawContext": {"rawXml": engine.get_xml()},
                }
            )["gear"]
        # Magic items have no it.title in PoB. Bind the serialized name, slot and item ID instead.
        result = {}
        for item in missing:
            observed = gear.get(item["slot"], {}) if isinstance(gear, dict) else {}
            same_item = [
                r
                for r in reread
                if r.get("activeItemSet")
                and all(
                    r.get(key) == item.get(key) for key in ("slot", "itemId", "itemSetId", "name")
                )
            ]
            if len(same_item) == 1 and observed.get("base"):
                result[item["slot"]] = observed["base"]
        return result
    except (OSError, RuntimeError, ValueError):
        return {}
