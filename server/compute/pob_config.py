"""Read-only projection of the pinned ConfigTab custom-modifier load semantics."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from .state import canonical_payload_hash


CUSTOM_MODIFIER_SEMANTICS_VERSION = "pob_custom_modifier_blocks_v1"
_LUA_WHITESPACE = " \t\n\r\v\f"


def custom_modifier_projection(container: ET.Element) -> dict[str, Any]:
    """Preserve authored blocks and separately identify modifiers active after XML Load.

    Explicit ConfigSets reset the initial default block; legacy flat Config appends to
    it. Load migrates legacy Input only when there are no blocks or one empty block,
    then removes that Input. BuildModList's in-memory fallback consequently cannot
    resurrect ignored legacy text from a source XML containing disabled modern blocks.
    """
    blocks = [
        {
            "blockIndex": index,
            "blockTitle": node.get("title", "Default"),
            "enabled": node.get("enabled") in {None, "true"},
            "value": node.text or "",
        }
        for index, node in enumerate(container.findall("CustomModifierBlock"), start=1)
    ]
    loaded = ([{"blockTitle": "Default", "enabled": True, "value": ""}]
              if container.tag == "Config" else []) + blocks
    legacy_source = next(((index, node) for index, node in reversed(list(enumerate(container)))
                          if node.get("name") == "customMods" and (node.tag == "Input" or (
                              node.tag == "Placeholder" and node.get("string") is not None))), None)
    legacy = legacy_source[1].get("string", "") if legacy_source else ""
    migrated = bool(legacy) and (not loaded or (len(loaded) == 1 and loaded[0]["value"] == ""))
    if migrated:
        loaded = [{"blockTitle": "Default", "enabled": True, "value": legacy}]
    effective = [block for block in loaded if block["enabled"] and block["value"]]
    return {
        "blocks": [dict(block, effectiveInConfigSet=not migrated and block["enabled"] and bool(block["value"]))
                   for block in blocks],
        "legacyEffectiveInConfigSet": migrated,
        "legacySourceIndex": legacy_source[0] if legacy_source else None,
        "effectiveBlocks": effective,
    }


def active_custom_modifier_hash(root: ET.Element, active_config_set: str) -> str:
    """Bind effective source text/ordering; do not claim PoB parsed every modifier line."""
    config = root.find("Config")
    container = config
    if config is not None and config.findall("ConfigSet"):
        container = next((node for node in config.findall("ConfigSet")
                          if str(int(node.get("id", "0"))) == active_config_set), None)
    blocks = custom_modifier_projection(container)["effectiveBlocks"] if container is not None else []
    # PoB strips each modifier line before parsing. The serializer can add surrounding
    # indentation to block text; line normalization keeps legacy -> block migration valid.
    payload = []
    for block in blocks:
        lines = [line.strip(_LUA_WHITESPACE) for line in block["value"].split("\n")
                 if line.strip(_LUA_WHITESPACE)]
        if lines:
            payload.append([block["blockTitle"], lines])
    return canonical_payload_hash(payload)
