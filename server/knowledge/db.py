"""Read-only access to the bundled PoE2 corpus (SQLite + FTS5).

This layer is independent of the calculation engine: it answers "what is / find me"
queries straight from the bundled database, no PoB process required.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .. import paths

_con: sqlite3.Connection | None = None
_con_file_key: tuple[object, ...] | None = None


def db_path() -> Path:
    """Active corpus DB path: the auto-updated user copy if present, else the bundled seed."""
    return paths.corpus_path()


def _conn() -> sqlite3.Connection:
    from .corpus_certification import corpus_guard

    global _con, _con_file_key
    # Keep an immutable in-memory read snapshot, not a file handle that prevents other
    # MCP domains from replacing corpus.sqlite on Windows. A selected-file change reloads it.
    with corpus_guard():
        p = db_path().resolve()
        if not p.exists():
            raise FileNotFoundError(
                f"corpus DB not found at {p}. Build it with: uv run python -m pipeline.build_corpus"
            )
        stat = p.stat()
        key = (str(p), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
        if _con is None or _con_file_key != key:
            snapshot = sqlite3.connect(":memory:", check_same_thread=False)
            try:
                with closing(sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)) as source:
                    source.backup(snapshot)
                snapshot.execute("PRAGMA query_only=ON")
                snapshot.row_factory = sqlite3.Row
            except BaseException:
                snapshot.close()
                raise
            # Existing readers own their previous immutable connection until they finish;
            # replacing the cache reference must not close a connection in use by a thread.
            _con = snapshot
            _con_file_key = key
        return _con


def reset() -> None:
    """Drop the cached connection so a freshly-built/updated corpus is picked up."""
    from .corpus_certification import corpus_guard

    global _con, _con_file_key
    with corpus_guard():
        _con = None
        _con_file_key = None


def _match(text: str) -> str:
    """Turn free text into an FTS5 prefix-AND query (safe against punctuation)."""
    terms = re.findall(r"\w+", text.lower())
    return " ".join(f"{t}*" for t in terms) if terms else '""'


def _match_cols(text: str, cols: tuple[str, ...]) -> str:
    """FTS5 prefix-AND query restricted to specific columns.

    Mod rows index readable name/text plus internal stat-id tokens; scoping a stat-text query
    to {name text} stops it matching unrelated mods via their stat ids (e.g. "physical damage"
    hitting an Armour mod whose stat id contains "physical_damage_reduction").
    """
    terms = re.findall(r"\w+", text.lower())
    if not terms:
        return '""'
    inner = " ".join(f"{t}*" for t in terms)
    return "{" + " ".join(cols) + "} : (" + inner + ")"


def corpus_info() -> dict[str, Any]:
    con = _conn()
    meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
    if "counts" in meta:
        meta["counts"] = json.loads(meta["counts"])
    return meta


def search_items(
    query: str = "",
    item_class: str | None = None,
    limit: int = 20,
    max_drop_level: int | None = None,
    order: str = "drop_desc",
) -> list[dict]:
    """Search item bases by name/tags/class.

    `max_drop_level` filters to bases obtainable by a character level (SQL-side, so low-level
    bases are NOT truncated by the LIMIT — this is what pick_base relies on for campaign gear).
    `order` is "drop_desc" (highest tier first, default) or "drop_asc" (campaign-friendly).
    """
    con = _conn()
    params: list[Any] = []
    if query:
        sql = (
            "SELECT i.id, i.name, i.item_class, i.drop_level, i.tags "
            "FROM items_fts f JOIN items i ON i.id = f.item_id WHERE items_fts MATCH ? "
        )
        params.append(_match(query))
    else:
        sql = "SELECT i.id, i.name, i.item_class, i.drop_level, i.tags FROM items i WHERE 1=1 "
    if item_class:
        sql += "AND i.item_class = ? "
        params.append(item_class)
    if max_drop_level is not None:
        sql += "AND i.drop_level <= ? "
        params.append(int(max_drop_level))
    if order == "drop_asc":
        sql += "ORDER BY i.drop_level ASC LIMIT ?"
    else:
        # highest-tier (endgame) bases first — what build crafting usually wants
        sql += "ORDER BY i.drop_level DESC LIMIT ?"
    params.append(limit)
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "item_class": r["item_class"],
            "drop_level": r["drop_level"],
            "tags": json.loads(r["tags"]),
        }
        for r in con.execute(sql, params)
    ]


def get_item(name_or_id: str) -> dict | None:
    con = _conn()
    row = con.execute(
        "SELECT raw FROM items WHERE id = ? OR lower(name) = lower(?) LIMIT 1",
        (name_or_id, name_or_id),
    ).fetchone()
    if not row:
        return None
    data = json.loads(row["raw"])
    # Contract is dict | None: a malformed (e.g. list-shaped) raw must not leak out and crash
    # callers with "'list' object has no attribute 'get'" (e.g. affix_pool). Degrade to None.
    return data if isinstance(data, dict) else None


# Body/helmet/gloves/boots gate on an attribute and supply a matching defence layer; belt/amulet/ring
# are attribute-agnostic. So when auto-basing a from-scratch set we match the build's main attribute
# (int→ES, dex→evasion, str→armour) for the gated pieces, and just take the best base otherwise.
_ATTR_GATED_CLASSES = {"Body Armour", "Helmet", "Gloves", "Boots"}


def pick_base(
    item_class: str,
    attr: str | None = None,
    *,
    max_drop_level: int | None = None,
) -> str | None:
    """Pick the strongest available base that is obtainable by the requested stage.

    `max_drop_level` prevents campaign planners from silently using endgame-only bases. Attribute-
    gated armour still prefers the build's dominant attribute within the eligible base set.
    """
    rows = search_items(
        item_class=item_class, limit=100, max_drop_level=max_drop_level
    )  # highest drop_level first, filtered in SQL so low-level bases survive the LIMIT
    if not rows:
        return None
    if attr and item_class in _ATTR_GATED_CLASSES:
        tag = f"{attr}_armour"
        for r in rows:
            if tag in (r.get("tags") or []):
                return str(r["name"])
    return str(rows[0]["name"])


def _gem_crafting_meta(raw: str | None) -> dict[str, Any]:
    """Extract crafting metadata from a gem's raw RePoE entry (fail-soft).

    ``crafting_level`` is the RePoE *crafting* tier (0-14), NOT the character level at which the
    gem becomes usable — gem level requirements live in the PoB engine and are queried through
    the engine, not here. The field is surfaced only as an acquisition reference, and callers
    must not treat it as a level gate.

    ``is_lineage`` marks lineage support gems (a unique/special acquisition family, e.g.
    Bhatair's Vengeance / Ailith's Chimes / Uhtred's series). It is tri-state: True/False when
    the raw entry carries the field, None when the raw entry is missing or unparseable.
    """
    if not raw:
        return {
            "crafting_level": None,
            "crafting_types": None,
            "craftingTypesUnknown": True,
            "is_lineage": None,
        }
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {
            "crafting_level": None,
            "crafting_types": None,
            "craftingTypesUnknown": True,
            "is_lineage": None,
        }
    level = data.get("crafting_level")
    types = data.get("crafting_types")
    lineage = data.get("is_lineage")
    return {
        "crafting_level": int(level) if isinstance(level, int) else None,
        "crafting_types": list(types) if isinstance(types, list) else None,
        "craftingTypesUnknown": not isinstance(types, list),
        "is_lineage": bool(lineage) if isinstance(lineage, bool) else None,
    }


def find_skills(
    query: str = "",
    gem_type: str | None = None,
    tag: str | None = None,
    color: str | None = None,
    limit: int = 30,
) -> list[dict]:
    con = _conn()
    params: list[Any] = []
    if query:
        sql = (
            "SELECT g.id, g.name, g.color, g.gem_type, g.tags, g.supports, g.description, g.raw "
            "FROM gems_fts f JOIN gems g ON g.id = f.gem_id WHERE gems_fts MATCH ? "
        )
        params.append(_match(query))
    else:
        sql = (
            "SELECT g.id, g.name, g.color, g.gem_type, g.tags, g.supports, g.description, g.raw "
            "FROM gems g WHERE 1=1 "
        )
    if gem_type:
        sql += "AND g.gem_type = ? "
        params.append(gem_type)
    if color:
        sql += "AND g.color = ? "
        params.append(color)
    if tag:
        sql += "AND g.tags LIKE ? "
        params.append(f'%"{tag}"%')
    sql += "LIMIT ?"
    params.append(limit)
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "color": r["color"],
            "gem_type": r["gem_type"],
            "tags": json.loads(r["tags"]),
            "supports": json.loads(r["supports"]),
            "description": r["description"],
            **_gem_crafting_meta(r["raw"]),
        }
        for r in con.execute(sql, params)
    ]


# Damage-type/element tags. A support that shares one of these with the skill (lightning ↔ lightning)
# is far more likely to be a real DPS lever — penetration, added/increased element damage, exposure —
# than one sharing only a delivery tag (projectile/area). find_supports_for ranks these matches
# highest so they survive the cap; the support optimizer's candidate pool depends on it.
_DAMAGE_TYPE_TAGS = {"fire", "cold", "lightning", "chaos", "physical", "elemental"}


def find_supports_for(skill: str, limit: int = 25) -> dict:
    """Find support gems for a skill: its curated recommendations plus tag-compatible supports."""
    gem = get_gem(skill)
    if not gem:
        return {"skill": skill, "found": False}
    generic = {"support", "grants_active_skill"}
    skill_tags = set(gem["tags"]) - generic
    con = _conn()
    compatible = []
    for r in con.execute("SELECT name, tags FROM gems WHERE gem_type = 'support' ORDER BY name"):
        shared = skill_tags & (set(json.loads(r["tags"])) - generic)
        if shared:
            compatible.append(
                {
                    "name": r["name"],
                    "matches": sorted(shared),
                    "on_element": any(m in _DAMAGE_TYPE_TAGS for m in shared),
                }
            )

    # Most relevant first so a capped list keeps the supports worth trying (the support optimizer
    # searches this pool). A shared *damage-type* tag signals far more value than a delivery tag —
    # penetration/added-damage supports often share only the element, so rank element matches above
    # raw match count or they get truncated away (e.g. Lightning Penetration on a lightning skill).
    def _relevance(c: dict) -> tuple[int, int, str]:
        type_hits = sum(1 for m in c["matches"] if m in _DAMAGE_TYPE_TAGS)
        return (-type_hits, -len(c["matches"]), c["name"])

    compatible.sort(key=_relevance)
    return {
        "skill": gem["name"],
        "tags": sorted(skill_tags),
        "recommended": gem["supports"],
        "compatible": compatible[:limit],
    }


def get_gem(name_or_id: str) -> dict | None:
    con = _conn()
    row = con.execute(
        "SELECT id, name, color, gem_type, tags, grants, supports, description, types, raw "
        "FROM gems WHERE id = ? OR lower(name) = lower(?) LIMIT 1",
        (name_or_id, name_or_id),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "color": row["color"],
        "gem_type": row["gem_type"],
        "tags": json.loads(row["tags"]),
        "grants": json.loads(row["grants"]),
        "supports": json.loads(row["supports"]),
        "description": row["description"],
        "types": json.loads(row["types"]),
        "requirement_weights": _requirement_weights(row["raw"]),
        **_gem_crafting_meta(row["raw"]),
    }


# Energy-based META-TRIGGER gems (Cast on Critical, the Invocations, Spell-on-Hit, etc.): they
# reserve spirit and fire SOCKETED spells via an energy/condition mechanic. The pinned PoB-PoE2
# calc has the gem DATA but NOT a handler that turns "energy generated on crit/hit" into a trigger
# rate — so a socketed spell is computed as a weak SELF-CAST, never as the triggered nuke it is in
# game. We can't fake the number (engine = source of truth), so tools must SURFACE this limitation.
_META_TRIGGER_TAGS = {"meta", "trigger"}


def meta_trigger_gems(names: Iterable[str]) -> list[str]:
    """Of `names`, the ones that are energy-based meta-trigger gems whose triggered-spell DPS the
    engine does not model (see `_META_TRIGGER_TAGS`). Returns canonical gem names (deduped)."""
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        gem = get_gem(n) if n else None
        if gem and _META_TRIGGER_TAGS <= set(gem.get("tags") or []) and gem["name"] not in seen:
            seen.add(gem["name"])
            out.append(gem["name"])
    return out


# The corpus has no class table (only ascendancies with name/class/flavour), so the base-class →
# dominant-attribute mapping is a static fact sourced from the official class descriptions:
# Warrior=Strength, Ranger=Dexterity, Sorceress=Intelligence, Monk=Dexterity, Mercenary=Strength,
# Witch=Intelligence, Huntress=Dexterity, Druid=Strength. "full" names match gem
# `requirement_weights` keys; "short" names match db.pick_base's `{attr}_armour` tag convention.
_CLASS_ATTRIBUTE_MAP: dict[str, tuple[str, str]] = {
    "Warrior": ("strength", "str"),
    "Ranger": ("dexterity", "dex"),
    "Sorceress": ("intelligence", "int"),
    "Monk": ("dexterity", "dex"),
    "Mercenary": ("strength", "str"),
    "Witch": ("intelligence", "int"),
    "Huntress": ("dexterity", "dex"),
    "Druid": ("strength", "str"),
}


def class_attribute_mapping() -> dict[str, dict[str, str]]:
    """Eight base classes → dominant attribute, in both full and short naming."""
    return {
        name: {"attribute": full, "short": short}
        for name, (full, short) in _CLASS_ATTRIBUTE_MAP.items()
    }


def _requirement_weights(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    weights = data.get("requirement_weights")
    return weights if isinstance(weights, dict) else None


def attribute_compatible(weights: dict[str, Any] | None, attribute: str) -> bool:
    """Whether a gem's attribute weights admit the given dominant attribute.

    All-zero weights (no preference, ~20% of gems) pass through; mixed weights (e.g. 50/50)
    admit any dominant attribute that has a positive share.
    """
    if not weights:
        return True
    total = sum(
        int(value) for value in weights.values() if isinstance(value, (int, float)) and value > 0
    )
    if total <= 0:
        return True
    return int(weights.get(attribute) or 0) > 0


def list_gems_for_level(
    level: int,
    gem_type: str | None = None,
    class_key: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """List gems usable as acquisition references at `level`, optionally class/type-filtered.

    NOTE on the level semantics: the corpus has NO reliable character-level requirement for gems
    (``crafting_level`` is the RePoE crafting tier, 0-14, not a character level). This query only
    applies a SOFT filter — gems with a crafting level at or below `level`, plus gems whose
    crafting level is unknown — and every returned entry carries ``craftingLevelIsReference``.
    TRUE level availability must be verified through the PoB engine (``gem_level_requirements`` /
    ``validate_level_availability``); treat this list as a candidate pool, not a gate.
    """
    con = _conn()
    params: list[Any] = []
    sql = (
        "SELECT id, name, color, gem_type, tags, grants, supports, description, types, raw "
        "FROM gems WHERE 1=1 "
    )
    if gem_type:
        sql += "AND gem_type = ? "
        params.append(gem_type)
    rows = con.execute(sql, params).fetchall()

    attribute = None
    if class_key:
        entry = _CLASS_ATTRIBUTE_MAP.get(str(class_key))
        attribute = entry[0] if entry else None

    out: list[dict[str, Any]] = []
    for r in rows:
        meta = _gem_crafting_meta(r["raw"])
        crafting_level = meta["crafting_level"]
        if crafting_level is not None and crafting_level > int(level):
            continue
        weights = _requirement_weights(r["raw"])
        if attribute is not None and not attribute_compatible(weights, attribute):
            continue
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "color": r["color"],
                "gem_type": r["gem_type"],
                "tags": json.loads(r["tags"]),
                "grants": json.loads(r["grants"]),
                "supports": json.loads(r["supports"]),
                "description": r["description"],
                "types": json.loads(r["types"]),
                **meta,
                "requirement_weights": weights,
                "craftingLevelIsReference": True,
            }
        )
    # Stable, campaign-friendly order: gems with a known crafting level first (ascending), then
    # unknown/zero (ascendancy-exclusive and missing-data entries) — so a level filter is not
    # swamped by crafting_level=0 entries before regular skills like Lightning Arrow.
    out.sort(
        key=lambda item: (
            0 if (item.get("crafting_level") or 0) > 0 else 1,
            int(item.get("crafting_level") or 0),
            str(item.get("name") or "").casefold(),
        )
    )
    return out[: int(limit)]


def list_ascendancies(character: str | None = None) -> list[dict]:
    con = _conn()
    if character:
        rows = con.execute(
            "SELECT name, class, flavour FROM ascendancies WHERE lower(class) = lower(?) "
            "ORDER BY class, name",
            (character,),
        )
    else:
        rows = con.execute("SELECT name, class, flavour FROM ascendancies ORDER BY class, name")
    return [{"name": r["name"], "class": r["class"], "flavour": r["flavour"]} for r in rows]


def search_mods(
    query: str = "",
    item_tag: str | None = None,
    mod_type: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """Search affixes/modifiers by readable text. `item_tag` filters by what it rolls on
    (e.g. "ring", "amulet", "body_armour"); `mod_type` is "prefix" or "suffix"."""
    con = _conn()
    params: list[Any] = []
    if query:
        sql = (
            "SELECT m.id, m.name, m.text, m.type, m.tags, m.required_level "
            "FROM mods_fts f JOIN mods m ON m.id = f.mod_id WHERE mods_fts MATCH ? "
        )
        params.append(_match_cols(query, ("name", "text")))
    else:
        sql = "SELECT m.id, m.name, m.text, m.type, m.tags, m.required_level FROM mods m WHERE 1=1 "
    if item_tag:
        sql += "AND m.tags LIKE ? "
        params.append(f'%"{item_tag}"%')
    if mod_type:
        sql += "AND m.type = ? "
        params.append(mod_type)
    sql += "LIMIT ?"
    params.append(limit)
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "text": r["text"],
            "type": r["type"],
            "required_level": r["required_level"],
            "rolls_on": json.loads(r["tags"]),
        }
        for r in con.execute(sql, params)
    ]


def get_mods_by_ids(mod_ids: list[str]) -> list[dict[str, Any]]:
    """Return exact craftable modifier records in caller order.

    This is the typed/static lookup used when an Agent selects concrete jewel modifiers.  It does
    not fuzzy-match names or text, and therefore cannot silently substitute a different modifier.
    Missing ids are omitted so the caller can fail closed against the requested id set.
    """

    requested = [str(value) for value in mod_ids if str(value).strip()]
    if not requested:
        return []
    placeholders = ",".join("?" for _ in requested)
    rows = (
        _conn()
        .execute(
            "SELECT id, name, text, type, domain, required_level, tags, groups, ranges "
            f"FROM mods WHERE id IN ({placeholders})",
            requested,
        )
        .fetchall()
    )
    by_id = {
        str(row["id"]): {
            "id": str(row["id"]),
            "name": row["name"],
            "text": row["text"],
            "type": row["type"],
            "domain": row["domain"],
            "required_level": row["required_level"],
            "rolls_on": json.loads(row["tags"] or "[]"),
            "groups": json.loads(row["groups"] or "[]"),
            "ranges": json.loads(row["ranges"] or "[]"),
        }
        for row in rows
    }
    return [by_id[value] for value in requested if value in by_id]


def mods_for_text(query: str, limit: int = 80) -> list[dict]:
    """Candidate affixes matching the readable words in `query`, with tier ranges.

    Used by the item parser to find a rolled affix's tier ladder. Returns each mod's text,
    type (prefix/suffix), required_level, groups, spawn tags, and per-stat ranges.
    """
    con = _conn()
    # `ranges` was added in schema v3; detect the column directly rather than catching
    # OperationalError around the query (which would also swallow real FTS/SQL errors).
    has_ranges = any(row[1] == "ranges" for row in con.execute("PRAGMA table_info(mods)"))
    cols = ", m.ranges" if has_ranges else ""
    rows = con.execute(
        "SELECT m.id, m.text, m.type, m.required_level, m.groups, m.tags, m.domain" + cols + " "
        "FROM mods_fts f JOIN mods m ON m.id = f.mod_id WHERE mods_fts MATCH ? LIMIT ?",
        (_match_cols(query, ("text",)), limit),
    )
    return [
        {
            "id": r["id"],
            "text": r["text"],
            "type": r["type"],
            "required_level": r["required_level"],
            "groups": json.loads(r["groups"] or "[]"),
            "tags": json.loads(r["tags"] or "[]"),
            "domain": r["domain"],
            "ranges": json.loads(r["ranges"] or "[]") if has_ranges else [],
        }
        for r in rows
    ]


def mod_tags_match_base(
    base_name: str,
    mod_tags: list[str] | set[str],
    *,
    mod_domain: str | None = None,
) -> bool:
    """Whether a craftable mod's spawn tags permit it on ``base_name``.

    Family-specific tags take precedence so an overlapping roll from another weapon family cannot
    leak in through a shared ``weapon`` tag.  A mod whose *only* applicability tag is a broad weapon
    shape (for example local critical chance tagged simply ``weapon``) may still match that shape.
    For ordinary item/misc domains, ``default`` alone remains too broad and empty tags stay
    unknown. Inside the Flask domain, empty/default-only tags are the corpus-wide Flask marker;
    life/mana subtype tags must still match the base exactly.
    """
    base = get_item(base_name)
    if not base:
        return False
    base_domain = str(base.get("domain") or "")
    if mod_domain is not None and str(mod_domain) not in _mod_domains_for_base(base_domain):
        return False
    base_tags = set(base.get("tags") or [])
    candidate_tags = set(mod_tags)
    if base_domain == "flask":
        # RePoE uses empty/default-only tags for flask-wide affixes and life_flask/mana_flask
        # for subtype-specific ones.  ``default`` is too broad for ordinary item-domain mods,
        # but it is the explicit all-flask marker inside the flask domain.
        specific_flask_tags = candidate_tags - {"default"}
        return not specific_flask_tags or bool(specific_flask_tags & base_tags)
    specific_tags = candidate_tags - _GENERIC_TAGS
    if specific_tags:
        return bool(specific_tags & base_tags)
    broad_weapon_tags = {"weapon", "onehand", "twohand", "ranged"}
    return bool(candidate_tags & base_tags & broad_weapon_tags)


def reverse_lookup(stat: str, limit: int = 30) -> dict[str, list[dict]]:
    """Find sources of a stat across mods, gems, and uniques (by readable text)."""
    con = _conn()
    q = _match(stat)
    qm = _match_cols(stat, ("name", "text"))
    out: dict[str, list[dict]] = {"mods": [], "gems": [], "uniques": []}
    for r in con.execute(
        "SELECT m.name, m.text, m.type, m.tags FROM mods_fts f JOIN mods m ON m.id = f.mod_id "
        "WHERE mods_fts MATCH ? LIMIT ?",
        (qm, limit),
    ):
        out["mods"].append(
            {
                "name": r["name"],
                "text": r["text"],
                "type": r["type"],
                "rolls_on": json.loads(r["tags"]),
            }
        )
    for r in con.execute(
        "SELECT g.name, g.gem_type, g.description FROM gems_fts f JOIN gems g ON g.id = f.gem_id "
        "WHERE gems_fts MATCH ? LIMIT ?",
        (q, limit),
    ):
        out["gems"].append(
            {"name": r["name"], "gem_type": r["gem_type"], "description": r["description"]}
        )
    for r in con.execute(
        "SELECT u.name, u.base FROM uniques_fts f JOIN uniques u ON u.id = f.unique_id "
        "WHERE uniques_fts MATCH ? LIMIT ?",
        (q, limit),
    ):
        out["uniques"].append({"name": r["name"], "base": r["base"]})
    return out


def search_uniques(query: str = "", item_type: str | None = None, limit: int = 20) -> list[dict]:
    """Search unique items by name/base/mod text. `item_type` filters by slot family
    (e.g. "ring", "body", "bow")."""
    con = _conn()
    params: list[Any] = []
    if query:
        sql = (
            "SELECT u.id, u.name, u.base, u.item_type "
            "FROM uniques_fts f JOIN uniques u ON u.id = f.unique_id WHERE uniques_fts MATCH ? "
        )
        params.append(_match(query))
    else:
        sql = "SELECT u.id, u.name, u.base, u.item_type FROM uniques u WHERE 1=1 "
    if item_type:
        sql += "AND u.item_type = ? "
        params.append(item_type)
    sql += "LIMIT ?"
    params.append(limit)
    return [
        {"name": r["name"], "base": r["base"], "item_type": r["item_type"]}
        for r in con.execute(sql, params)
    ]


def relevant_uniques(keywords: list[str], limit: int = 15) -> list[dict]:
    """Uniques whose name/base/mod text matches the MOST of a build's scaling `keywords` (e.g. its
    damage type + skill type + skill name), ranked by how many match. Corpus relevance only — these
    are CANDIDATES (a unique often ENABLES a mechanic, not just adds a stat); the caller must read the
    text and equip + measure on the engine to value them."""
    scored: dict[str, dict[str, Any]] = {}
    for kw in keywords:
        if not kw:
            continue
        for u in search_uniques(query=kw, limit=40):
            e = scored.setdefault(u["name"], {**u, "matched": set()})
            matched = e["matched"]
            if isinstance(matched, set):
                matched.add(kw)
    ranked = sorted(scored.values(), key=lambda e: (-len(e["matched"]), str(e["name"])))
    return [
        {
            "name": e["name"],
            "base": e["base"],
            "item_type": e["item_type"],
            "matched": sorted(e["matched"]),
        }
        for e in ranked[:limit]
    ]


def get_unique(name: str, *, include_source: bool = False) -> dict | None:
    """Return readable text and authoritative PoB choices; raw source is internal opt-in."""
    from .unique_variants import parse_unique_source

    con = _conn()
    row = con.execute(
        "SELECT name, base, item_type, text, raw FROM uniques WHERE lower(name) = lower(?) LIMIT 1",
        (name,),
    ).fetchone()
    if not row:
        return None
    result = {
        "name": row["name"],
        "base": row["base"],
        "item_type": row["item_type"],
        "text": row["text"],
    }
    if row["raw"]:
        source = parse_unique_source(row["raw"], name=row["name"], base=row["base"])
        if source.labels:
            result["variantSelection"] = source.public_contract()
        if include_source:
            result["pobSource"] = row["raw"]
    return result


# Tags shared by almost every base — too generic to mean "this mod rolls here".
_GENERIC_TAGS = {"default", "onehand", "twohand", "weapon", "ranged"}


def _mod_domains_for_base(base_domain: str) -> tuple[str, ...]:
    """Return the craftable mod domains that belong to one base-item domain."""

    return ("flask",) if base_domain == "flask" else ("item", "misc")


def craft_profile(base_name: str) -> dict[str, Any] | None:
    """Return the deterministic rarity/affix contract for one craftable base domain."""

    base = get_item(base_name)
    if not isinstance(base, dict):
        return None
    domain = str(base.get("domain") or "")
    if domain == "flask":
        return {"domain": domain, "rarity": "Magic", "prefixLimit": 1, "suffixLimit": 1}
    return {"domain": domain, "rarity": "Rare", "prefixLimit": 3, "suffixLimit": 3}


def canonical_mod_tier_ladder(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one deterministic entry per real tier, collapsing corpus item-class duplicates."""

    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for value in records:
        record = dict(value)
        ranges = list(record.get("ranges") or [])
        range_key = tuple(
            (
                str(item.get("id") or ""),
                item.get("min"),
                item.get("max"),
            )
            for item in ranges
            if isinstance(item, dict)
        )
        identity = (
            int(record.get("required_level") or 0),
            range_key,
            str(record.get("text") or ""),
        )
        current = unique.get(identity)
        if current is None or str(record.get("id") or "") < str(current.get("id") or ""):
            unique[identity] = record

    def strength(record: dict[str, Any]) -> tuple[Any, ...]:
        numeric: list[float] = []
        for item in record.get("ranges") or []:
            if not isinstance(item, dict):
                continue
            for key in ("max", "min"):
                value = item.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric.append(float(value))
        return (
            -int(record.get("required_level") or 0),
            tuple(-value for value in numeric),
            str(record.get("text") or ""),
            str(record.get("id") or ""),
        )

    ordered = sorted(unique.values(), key=strength)
    total = len(ordered)
    return [
        {
            **record,
            "tier": index,
            "totalTiers": total,
        }
        for index, record in enumerate(ordered, start=1)
    ]


def affix_pool(base_name: str, ilvl: int = 82) -> dict[str, list[dict[str, Any]]]:
    """Craftable prefixes/suffixes for a base — the best available tier per mod group at `ilvl`.

    Used by the gear optimizer. A mod is included when its spawn tags intersect the base's
    (non-generic) tags. Each entry has the mod group (for exclusivity), type, the range text
    (e.g. "+(80-90) to maximum Life"), required_level, and `tiers` (how many ilvl tiers of that
    exact mod can roll here — the returned one is the top/best, so it's "tier 1 of `tiers`", a
    rough rarity/attainability signal). Returns only real corpus mods.

    NOTE: the data source has no usable spawn-weights (all normalized to 1), so attainability is
    inferred from tier depth + required level, not roll probability.
    """
    base = get_item(base_name)
    if not base:
        return {"prefixes": [], "suffixes": []}
    base_domain = str(base.get("domain") or "")
    domains = _mod_domains_for_base(base_domain)
    con = _conn()
    # 'item' = normal gear mods; 'misc' = craftable jewel mods (the only misc mods ingested). Tag
    # matching below keeps jewel mods off gear and gear mods off jewels.
    placeholders = ",".join("?" for _ in domains)
    rows = con.execute(
        "SELECT id, text, type, groups, ranges, tags, required_level, domain FROM mods "
        f"WHERE domain IN ({placeholders}) AND type IN ('prefix','suffix') "
        "AND (required_level IS NULL OR required_level <= ?)",
        (*domains, ilvl),
    ).fetchall()
    tier_options: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        mtags = set(json.loads(r["tags"] or "[]"))
        if not mod_tags_match_base(base_name, mtags, mod_domain=str(r["domain"] or "")):
            continue
        # keep both range mods ("+(80-90) to Life") and fixed mods ("+5 to Level of all ... Skills");
        # the latter are already a concrete roll. Skip flag/socket lines with no number at all.
        if not re.search(r"\d", r["text"] or ""):
            continue
        groups = json.loads(r["groups"] or "[]")
        group = groups[0] if groups else r["text"]
        # Dedup by (type, group, number-stripped text): collapses tier duplicates of the SAME mod
        # but KEEPS per-variant mods that share a group (e.g. +Fire vs +Lightning Spell Levels), so
        # the optimizer can pick the variant matching the build. Group exclusivity still applies.
        norm = _norm_mod_line(r["text"] or "")
        key = (r["type"], group, norm)
        rl = r["required_level"] or 0
        tier_options.setdefault(key, []).append(
            {
                "id": str(r["id"]),
                "group": group,
                "type": r["type"],
                "text": r["text"],
                "required_level": rl,
                "ranges": json.loads(r["ranges"] or "[]"),
            }
        )
    best: list[dict[str, Any]] = []
    for options in tier_options.values():
        ladder = canonical_mod_tier_ladder(options)
        if not ladder:
            continue
        top = dict(ladder[0])
        top["tiers"] = len(ladder)
        top["tier_options"] = ladder
        best.append(top)
    pre = sorted((m for m in best if m["type"] == "prefix"), key=lambda m: m["group"])
    suf = sorted((m for m in best if m["type"] == "suffix"), key=lambda m: m["group"])
    return {"prefixes": pre, "suffixes": suf}


def _norm_mod_line(s: str) -> str:
    """Normalize a mod/affix line for matching: lowercase, ranges/numbers → '#', collapse space."""
    s = (s or "").lower().replace("(", "").replace(")", "")
    s = re.sub(r"[+\-]?\d+(?:\.\d+)?", "#", s)
    s = re.sub(r"#\s*-\s*#", "#", s)  # a "#-#" range collapses to a single "#"
    s = re.sub(r"#+", "#", s)
    return re.sub(r"\s+", " ", s).strip()


def illegal_affixes(base_name: str, affix_lines: list[str]) -> list[dict[str, Any]]:
    """Affix lines that name a real craftable mod which CANNOT roll on this base type.

    Conservative on purpose (so it never cries wolf on real gear): a line is flagged only when its
    normalized text matches a known craftable item prefix/suffix in the corpus AND none of that
    mod's tier variants can roll on the base's type. Lines that match no craftable mod (uniques,
    implicits, unusual phrasings) are left alone, and only the affix *type* is checked, not whether a
    roll's magnitude is within tier range. Returns [] when the base is unknown.
    """
    base = get_item(base_name)
    if not base:
        return []
    con = _conn()
    rows = con.execute(
        "SELECT text, tags, domain FROM mods "
        "WHERE domain IN ('item','misc','flask') AND type IN ('prefix','suffix')"
    ).fetchall()
    index: dict[str, list[tuple[str, set[str]]]] = {}
    for r in rows:
        tags = set(json.loads(r["tags"] or "[]"))
        for ln in (r["text"] or "").split("\n"):
            n = _norm_mod_line(ln)
            if n:
                index.setdefault(n, []).append((str(r["domain"] or ""), tags))
    out: list[dict[str, Any]] = []
    for line in affix_lines:
        n = _norm_mod_line(line)
        variants = index.get(n)
        if variants and not any(
            mod_tags_match_base(base_name, tags, mod_domain=domain) for domain, tags in variants
        ):
            out.append(
                {"affix": line.strip(), "reason": f"this affix does not roll on a {base_name}"}
            )
    return out


def _has_mechanics() -> bool:
    """Mechanics table exists only in schema_version >= 4 corpora (graceful on older data)."""
    con = _conn()
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mechanics' LIMIT 1"
    ).fetchone()
    return row is not None


def search_mechanics(query: str, limit: int = 8) -> list[dict]:
    """Full-text search the wiki-sourced mechanics tier. Returns titles + a snippet + source."""
    if not query or not _has_mechanics():
        return []
    con = _conn()
    rows = con.execute(
        "SELECT m.id, m.title, m.url, m.license, m.source, "
        "snippet(mechanics_fts, 2, '', '', ' … ', 12) AS snip "
        "FROM mechanics_fts f JOIN mechanics m ON m.id = f.mech_id "
        "WHERE mechanics_fts MATCH ? ORDER BY rank LIMIT ?",
        (_match_cols(query, ("title", "text")), limit),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "snippet": r["snip"],
            "url": r["url"],
            "license": r["license"],
            "source": r["source"],
        }
        for r in rows
    ]


def get_mechanic(title_or_id: str, fuzzy: bool = True) -> dict | None:
    """Return one mechanics page (full text + attribution) by id, exact title, or best FTS hit.

    fuzzy=False restricts to an exact id/title match (no FTS fallback).
    """
    if not title_or_id or not _has_mechanics():
        return None
    con = _conn()
    row = con.execute(
        "SELECT id, title, text, url, license, source FROM mechanics "
        "WHERE id = ? OR lower(title) = lower(?) LIMIT 1",
        (title_or_id, title_or_id),
    ).fetchone()
    if not row:
        if not fuzzy:
            return None
        hits = search_mechanics(title_or_id, limit=1)
        if not hits:
            return None
        row = con.execute(
            "SELECT id, title, text, url, license, source FROM mechanics WHERE id = ? LIMIT 1",
            (hits[0]["id"],),
        ).fetchone()
        if not row:
            return None
    return {
        "id": row["id"],
        "title": row["title"],
        "text": row["text"],
        "url": row["url"],
        "license": row["license"],
        "source": row["source"],
    }
