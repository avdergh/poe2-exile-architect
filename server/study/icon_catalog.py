"""Exact static gem/effect identities and their game-declared skill icon paths."""

from __future__ import annotations

import json
import re
from server import paths
from server.knowledge import db
from .storage import fingerprint
from .icons import icon_url


def _effect_icons(text: str) -> list[tuple[str, dict | None]]:
    """Read exact icon declarations in the pinned generator's effect layout.

    Keep malformed declarations as unknown so another definition cannot hide an
    ambiguous identity. This reads static literals and never executes Lua.
    """
    declaration = r'^skills\["([^"\r\n]+)"\][ \t]*=[ \t]*\{'
    block = re.compile(
        declaration + r"[ \t]*\r?$((?:(?!^skills\[|^\}).)*?)^\}[ \t]*(?:end[ \t]*)?\r?$",
        re.M | re.S,
    )
    result = []
    for start in re.finditer(declaration, text, re.M):
        match = block.match(text, start.start())
        fields = {}
        for field in ("name", "icon"):
            lines = re.findall(rf"^\t{field}\s*=([^\n]*)$", match[2], re.M) if match else []
            try:
                value = (
                    json.loads(lines[0].strip()[:-1])
                    if len(lines) == 1 and lines[0].strip().endswith(",")
                    else None
                )
            except ValueError:
                value = None
            fields[field] = value if isinstance(value, str) else None
        result.append((start[1], fields if all(fields.values()) else None))
    return result


def load_catalog() -> dict[str, dict]:
    result = {}
    effects = {}
    for file in sorted((paths.pob_runtime_pair().src_dir / "Data" / "Skills").glob("*.lua")):
        raw = file.read_bytes()
        for key, fields in _effect_icons(raw.decode("utf-8")):
            effects.setdefault(key, []).append(
                {
                    "name": fields["name"],
                    "iconPath": fields["icon"],
                    "sourceRef": "pob-static:sha256:" + fingerprint(raw),
                }
                if fields
                else None
            )
    con = db._conn()
    rows = con.execute("SELECT id,name,raw FROM gems ORDER BY id").fetchall()
    canonical_names = {row["name"] for row in rows}
    for row in rows:
        raw = json.loads(row["raw"])
        identity = row["id"]
        entry = {
            "identity": identity,
            "name": row["name"],
            "kind": raw.get("gem_type"),
            "iconPath": raw.get("icon_dds_file"),
            "sourceRef": "corpus-gem:sha256:" + fingerprint(raw),
        }
        if not icon_url(entry["iconPath"]):
            # Some unique supports declare no UI icon. Their exact gem item supplies its own art.
            item = con.execute("SELECT id,name,raw FROM items WHERE id=?", (identity,)).fetchone()
            if item and item["name"] == row["name"]:
                item_raw = json.loads(item["raw"])
                entry["iconPath"] = item_raw.get("visual_identity", {}).get("dds_file")
                entry["iconKind"] = "exact_gem_item"
                entry["itemSourceRef"] = "corpus-item:sha256:" + fingerprint(item_raw)
        entry["bindingHash"] = fingerprint(entry)
        result[identity] = entry
        # A granted child may have its own exact name/icon. Never borrow a parent's picture.
        for effect_id in raw.get("grants_skills", []):
            matches = effects.get(effect_id, [])
            if len(matches) != 1 or not matches[0] or matches[0]["name"] in canonical_names:
                continue
            child = {
                "identity": "skill:" + effect_id,
                "kind": "granted_skill",
                **matches[0],
                "grantingGemId": identity,
            }
            child["bindingHash"] = fingerprint(child)
            result[child["identity"]] = child
    return result
