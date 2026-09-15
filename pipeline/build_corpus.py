"""Build the bundled PoE2 corpus (SQLite + FTS5) from the RePoE PoE2 data export.

Fetches a small set of RePoE JSON files (cached under data/raw/), normalizes them, and
writes data/corpus.sqlite with full-text search over item bases, skill/support gems, and
ascendancies. Mods + stat-translation resolution are a follow-up (M2.1).

Run:  uv run python -m pipeline.build_corpus  [--refresh | --reviewed-source]
"""

from __future__ import annotations

import argparse
import json
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import repoe_snapshot, wiki

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
DB_PATH = REPO_ROOT / "data" / "corpus.sqlite"
REVIEWED_SOURCE_PATH = REPO_ROOT / "data" / "compatibility" / "corpus.json"
BASE = "https://repoe-fork.github.io/poe2/"
SOURCE_FILES = list(repoe_snapshot.SOURCE_FILES)
# Uniques (with full readable mods) come from the vendored PoB data, not RePoE.
UNIQUES_DIR = REPO_ROOT / "pob" / "PathOfBuilding-PoE2" / "src" / "Data" / "Uniques"
GENERATED_UNIQUES_FILE = REPO_ROOT / "data" / "physical_graph" / "uniques" / "generated_uniques.lua"
POB_JEWEL_MOD_FILES = (
    REPO_ROOT / "pob" / "PathOfBuilding-PoE2" / "src" / "Data" / "ModJewel.lua",
    REPO_ROOT / "pob" / "PathOfBuilding-PoE2" / "src" / "Data" / "ModVeiled.lua",
)
# Build-relevant mod domains (skip monster/area/heist/etc.).
MOD_DOMAINS = {"item", "flask"}

SCHEMA = """
CREATE TABLE items(
    id TEXT PRIMARY KEY, name TEXT, item_class TEXT, drop_level INTEGER, tags TEXT, raw TEXT);
CREATE VIRTUAL TABLE items_fts USING fts5(item_id UNINDEXED, name, item_class, tags);

CREATE TABLE gems(
    id TEXT PRIMARY KEY, name TEXT, color TEXT, gem_type TEXT, tags TEXT,
    grants TEXT, supports TEXT, description TEXT, types TEXT, raw TEXT);
CREATE VIRTUAL TABLE gems_fts USING fts5(gem_id UNINDEXED, name, tags, description);

CREATE TABLE ascendancies(id TEXT PRIMARY KEY, name TEXT, class TEXT, flavour TEXT, raw TEXT);

CREATE TABLE mods(
    id TEXT PRIMARY KEY, name TEXT, text TEXT, type TEXT, domain TEXT,
    required_level INTEGER, tags TEXT, stat_ids TEXT, groups TEXT, ranges TEXT);
CREATE VIRTUAL TABLE mods_fts USING fts5(mod_id UNINDEXED, name, text, tags, stat_ids);

CREATE TABLE uniques(
    id TEXT PRIMARY KEY, name TEXT, base TEXT, item_type TEXT, text TEXT, raw TEXT);
CREATE VIRTUAL TABLE uniques_fts USING fts5(unique_id UNINDEXED, name, base, text);

-- Wiki-sourced mechanics (CC BY-NC-SA 3.0; attributed via url/license/source columns). This is
-- the auto-refreshable "how mechanics work" tier, kept segregated from our own prose.
-- Revision columns are optional additive metadata; legacy schema-4 corpora remain readable.
CREATE TABLE mechanics(
    id TEXT PRIMARY KEY, title TEXT, text TEXT, url TEXT, license TEXT, source TEXT,
    page_id INTEGER, revision_id INTEGER, revision_timestamp TEXT);
CREATE VIRTUAL TABLE mechanics_fts USING fts5(mech_id UNINDEXED, title, text);

CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""


def _seg(metadata_id: str) -> str:
    return metadata_id.rsplit("/", 1)[-1]


# PoE markup is [reference|display]; keep the *display* (post-pipe) text, or the lone term.
# (Keeping the reference side turned "[EnergyShield|Energy Shield]" into "EnergyShield".)
LINK_RE = re.compile(r"\[(?:[^\]|]*\|)?([^\]]+)\]")
CURLY_RE = re.compile(r"\{[^}]*\}")
BLOCK_RE = re.compile(r"\[\[(.*?)\]\]", re.DOTALL)
# PoB metadata lines inside a unique block that aren't readable mods (drop from the text). `Source:`
# is a drop-location line that, unfiltered, was mistaken for the base on items whose base follows it
# (e.g. Hand of Wisdom and Action -> its real base "Furtive Wraps" sits after the Source line).
UNIQUE_META_RE = re.compile(
    r"^(Variant:|Version:|Selected Version:|Selected Variant(?: Group)?:|Implicits:|Has Alt Variant|Source:)"
)
JEWEL_NODE_TYPE_RE = re.compile(
    r'^\s*\["(?P<id>[^"]+)"\]\s*=\s*\{.*?\bnodeType\s*=\s*(?P<node_type>[12])\b'
)


def clean_text(t: str) -> str:
    """Strip PoE [display|link] markup, leaving the display text."""
    return LINK_RE.sub(r"\1", t or "")


def clean_mod_line(t: str) -> str:
    """Strip PoB {tags:...}/{variant:...} and [display|link] markup from an item line."""
    return clean_text(CURLY_RE.sub("", t or "")).strip()


def parse_uniques() -> list[dict]:
    """Parse PoB's Uniques/*.lua [[ ... ]] blocks into readable unique records."""
    from server.knowledge.unique_variants import parse_unique_source

    out: list[dict] = []
    paths = list(sorted(UNIQUES_DIR.glob("*.lua")))
    if GENERATED_UNIQUES_FILE.exists():
        # The generated export carries the complete variant blocks; prefer it if a future static
        # file also exposes a reduced entry with the same display name.
        paths.insert(0, GENERATED_UNIQUES_FILE)
    for path in paths:
        generated = path == GENERATED_UNIQUES_FILE
        for block in BLOCK_RE.findall(path.read_text("utf-8")):
            lines = [
                ln
                for ln in (x.rstrip() for x in block.strip("\n").split("\n"))
                if ln.strip() and not UNIQUE_META_RE.match(ln.strip())
            ]
            if len(lines) < 2:
                continue
            name = clean_mod_line(lines[0])
            base = clean_mod_line(lines[1])
            item_type = (
                "jewel"
                if generated and "diamond" in base.casefold()
                else "generated"
                if generated
                else path.stem
            )
            text = "\n".join(clean_mod_line(ln) for ln in lines)
            source = parse_unique_source(block, name=name, base=base)
            if source.uses_modern_selection:
                text = source.readable_text(name=name, base=base)
            out.append(
                {
                    "id": name,
                    "name": name,
                    "base": base,
                    "item_type": item_type,
                    "text": text,
                    "raw": block.strip("\n"),
                }
            )
    return out


def parse_radius_jewel_node_types() -> dict[str, int]:
    """Read the exact Small/Notable scope that pinned PoB applies to radius-jewel mods."""

    result: dict[str, int] = {}
    for path in POB_JEWEL_MOD_FILES:
        if not path.exists():
            raise FileNotFoundError(f"pinned PoB jewel modifier source is missing: {path}")
        for line in path.read_text("utf-8").splitlines():
            match = JEWEL_NODE_TYPE_RE.match(line)
            if not match:
                continue
            mod_id = match.group("id")
            if not mod_id.startswith(("JewelRadius", "AbyssModRadiusJewel")):
                continue
            result[mod_id] = int(match.group("node_type"))
    return result


def apply_radius_jewel_scope(mod_id: str, text: str, node_types: dict[str, int]) -> str:
    """Mirror Modules/Data.lua's exact-id nodeType expansion for readable corpus text."""

    node_type = node_types.get(mod_id)
    if node_type == 1:
        return "Small Passive Skills in Radius also grant " + text
    if node_type == 2:
        return "Notable Passive Skills in Radius also grant " + text
    return text


def _source_commit(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{40}", value) is None:
        raise ValueError("reviewed corpus repoeSourceCommit must be a full immutable SHA")
    return value


def reviewed_source_commit() -> str:
    certificate = json.loads(REVIEWED_SOURCE_PATH.read_text(encoding="utf-8"))
    return _source_commit(certificate.get("repoeSourceCommit") if isinstance(certificate, dict) else None)


def fetch_all(refresh: bool = False, *, expected_commit: str | None = None) -> None:
    if expected_commit is not None:
        expected_commit = _source_commit(expected_commit)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    needs_fetch = refresh or any(not (RAW_DIR / name).is_file() for name in SOURCE_FILES)
    if expected_commit is not None and not needs_fetch:
        with repoe_snapshot.snapshot_guard(RAW_DIR):
            try:
                binding = repoe_snapshot.verify_snapshot(RAW_DIR)
            except (OSError, ValueError):
                binding = None
            needs_fetch = binding is None or binding["sourceCommit"] != expected_commit
    if needs_fetch:
        print("fetching one pinned RePoE export ...")
        repoe_snapshot.fetch_snapshot(RAW_DIR, commit=expected_commit)
    else:
        # Cached legacy files remain unbound; a newer remote marker cannot upgrade them.
        with repoe_snapshot.snapshot_guard(RAW_DIR):
            repoe_snapshot.verify_snapshot(RAW_DIR)
    print("fetching wiki mechanics ...")
    print("  wiki:", wiki.fetch_all(refresh=refresh))


def _load(name: str) -> dict:
    return json.loads((RAW_DIR / name).read_text("utf-8"))


def build(*, expected_commit: str | None = None) -> dict[str, int]:
    if expected_commit is not None:
        expected_commit = _source_commit(expected_commit)
    with repoe_snapshot.snapshot_guard(RAW_DIR):
        source_binding = repoe_snapshot.verify_snapshot(RAW_DIR)
        if expected_commit is not None and (
            source_binding is None or source_binding["sourceCommit"] != expected_commit
        ):
            raise ValueError("RePoE source does not match the reviewed corpus repoeSourceCommit")
        source_manifest = (
            json.loads((RAW_DIR / "source-manifest.json").read_text(encoding="utf-8"))
            if (RAW_DIR / "source-manifest.json").is_file() else {"exportedVersion": "unknown"}
        )
        base_items = _load("base_items.min.json")
        skill_gems = _load("skill_gems.min.json")
        skills = _load("skills.min.json")
        ascendancies = _load("ascendancies.min.json")
        mods_data = _load("mods.min.json")
    radius_jewel_node_types = parse_radius_jewel_node_types()

    # Resolve recommended_supports metadata ids -> human display names (ids vary Gem/Gems).
    gem_name_by_seg = {_seg(k): g["base_item"]["display_name"] for k, g in skill_gems.items()}

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    cur = con.cursor()

    n_items = 0
    for mid, it in base_items.items():
        name = it.get("name") or _seg(mid)
        item_class = it.get("item_class", "") or ""
        tags = it.get("tags") or []
        # drop noise bases: demigod/unreleased, and unique-only base types ("...Unique..." ids)
        # that duplicate the normal base in searches.
        if "demigods" in tags or it.get("release_state") == "unreleased" or "Unique" in mid:
            continue
        cur.execute(
            "INSERT INTO items(id,name,item_class,drop_level,tags,raw) VALUES(?,?,?,?,?,?)",
            (mid, name, item_class, it.get("drop_level"), json.dumps(tags), json.dumps(it)),
        )
        cur.execute(
            "INSERT INTO items_fts(item_id,name,item_class,tags) VALUES(?,?,?,?)",
            (mid, name, item_class, " ".join(tags)),
        )
        n_items += 1

    n_gems = 0
    for mid, g in skill_gems.items():
        name = g["base_item"]["display_name"]
        # skip dev/placeholder ("[DNT...]"), unreleased, and unique-item-granted ("...Unique...")
        # skills — none are normal socketable gems, they just duplicate names in search.
        if (
            name.upper().startswith("[DNT")
            or g["base_item"].get("release_state") == "unreleased"
            or "Unique" in mid
        ):
            continue
        tags = g.get("tags") or []
        grants = g.get("grants_skills") or []
        supports = [
            gem_name_by_seg.get(_seg(s), _seg(s)) for s in (g.get("recommended_supports") or [])
        ]
        desc: str = ""
        types: list[str] = []
        for sid in grants:
            sk = skills.get(sid)
            if sk and sk.get("active_skill"):
                active = sk["active_skill"]
                desc = active.get("description") or desc
                types = active.get("types") or types
                if desc:
                    break
        cur.execute(
            "INSERT INTO gems(id,name,color,gem_type,tags,grants,supports,description,types,raw) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                mid,
                name,
                g.get("color"),
                g.get("gem_type"),
                json.dumps(tags),
                json.dumps(grants),
                json.dumps(supports),
                desc,
                json.dumps(types),
                json.dumps(g),
            ),
        )
        cur.execute(
            "INSERT INTO gems_fts(gem_id,name,tags,description) VALUES(?,?,?,?)",
            (mid, name, " ".join(tags), desc),
        )
        n_gems += 1

    n_asc = 0
    for aid, a in ascendancies.items():
        asc_name = a.get("name") or ""
        if a.get("disabled") or asc_name.startswith("["):  # skip dev/unused placeholders
            continue
        # "character" is a big list of metadata paths; the plain class name is the lone
        # entry that isn't a Metadata/ path (e.g. "Druid").
        chars = a.get("character")
        cls = None
        if isinstance(chars, list):
            cls = next(
                (c for c in chars if isinstance(c, str) and not c.startswith("Metadata/")), None
            )
        elif isinstance(chars, str):
            cls = chars
        slim = {
            "name": a.get("name"),
            "class": cls,
            "flavour": a.get("flavour_text"),
            "class_number": a.get("class_number"),
        }
        cur.execute(
            "INSERT INTO ascendancies(id,name,class,flavour,raw) VALUES(?,?,?,?,?)",
            (aid, a.get("name"), cls, a.get("flavour_text"), json.dumps(slim)),
        )
        n_asc += 1

    n_mods = 0
    for mid, m in mods_data.items():
        text = clean_text(m.get("text") or "")
        if not text:
            continue
        text = apply_radius_jewel_scope(mid, text, radius_jewel_node_types)
        tags = sorted(
            {w["tag"] for w in (m.get("spawn_weights") or []) if w.get("weight") and w.get("tag")}
        )
        # Build-relevant: item/flask mods, plus craftable JEWEL mods — which live in the 'misc'
        # domain (not 'item'), so the gear optimizer can craft jewels too. (Desecrated/strongbox
        # jewel mods are corrupted/special, not normal craftable rolls — excluded.)
        is_craftable_jewel = m.get("domain") == "misc" and any("jewel" in t for t in tags)
        if m.get("domain") not in MOD_DOMAINS and not is_craftable_jewel:
            continue
        stats = m.get("stats") or []
        stat_ids = [s.get("id") for s in stats if s.get("id")]
        ranges = [
            {"id": s.get("id"), "min": s.get("min"), "max": s.get("max")}
            for s in stats
            if s.get("id")
        ]
        cur.execute(
            "INSERT INTO mods(id,name,text,type,domain,required_level,tags,stat_ids,groups,ranges) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                mid,
                m.get("name"),
                text,
                m.get("generation_type"),
                m.get("domain"),
                m.get("required_level"),
                json.dumps(tags),
                json.dumps(stat_ids),
                json.dumps(m.get("groups") or []),
                json.dumps(ranges),
            ),
        )
        cur.execute(
            "INSERT INTO mods_fts(mod_id,name,text,tags,stat_ids) VALUES(?,?,?,?,?)",
            (mid, m.get("name") or "", text, " ".join(tags), " ".join(stat_ids)),
        )
        n_mods += 1

    n_uniques = 0
    seen_uniques: set[str] = set()
    for u in parse_uniques():
        if u["name"] in seen_uniques:
            continue
        seen_uniques.add(u["name"])
        cur.execute(
            "INSERT INTO uniques(id,name,base,item_type,text,raw) VALUES(?,?,?,?,?,?)",
            (u["id"], u["name"], u["base"], u["item_type"], u["text"], u["raw"]),
        )
        cur.execute(
            "INSERT INTO uniques_fts(unique_id,name,base,text) VALUES(?,?,?,?)",
            (u["id"], u["name"], u["base"], u["text"]),
        )
        n_uniques += 1

    n_mech = 0
    for m in wiki.load_pages():
        cur.execute(
            "INSERT INTO mechanics(id,title,text,url,license,source,page_id,revision_id,revision_timestamp) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (m["id"], m["title"], m["text"], m["url"], m["license"], m["source"],
             m.get("pageId"), m.get("revisionId"), m.get("revisionTimestamp")),
        )
        cur.execute(
            "INSERT INTO mechanics_fts(mech_id,title,text) VALUES(?,?,?)",
            (m["id"], m["title"], m["text"]),
        )
        n_mech += 1

    counts = {
        "items": n_items,
        "gems": n_gems,
        "ascendancies": n_asc,
        "mods": n_mods,
        "uniques": n_uniques,
        "mechanics": n_mech,
    }
    from server.knowledge import gem_availability
    availability = gem_availability.validate_corpus_bindings(con)
    for key, value in {
        "source": (f"{repoe_snapshot.REPOSITORY}/{source_binding['sourceCommit']}/data/"
                   if source_binding is not None else BASE),
        "schema_version": "4",
        "gem_availability_catalog": availability["catalogRef"],
        "counts": json.dumps(counts),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_manifest": json.dumps({
            "repoe": source_manifest,
            "pobUniqueFiles": [{"path": "pinned_pob/Data/Uniques/" + path.name,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                               for path in sorted(UNIQUES_DIR.glob("*.lua"))],
            "generatedUniqueFile": ({"path": "generated_uniques/" + GENERATED_UNIQUES_FILE.name,
                                     "sha256": hashlib.sha256(GENERATED_UNIQUES_FILE.read_bytes()).hexdigest()}
                                    if GENERATED_UNIQUES_FILE.is_file() else None),
            "wiki": {"certification": "reference_only"},
        }),
    }.items():
        cur.execute("INSERT INTO meta(key,value) VALUES(?,?)", (key, value))

    con.commit()
    con.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--refresh", action="store_true", help="Fetch the latest upstream export")
    mode.add_argument("--reviewed-source", action="store_true",
                      help="Rebuild from the immutable RePoE commit in data/compatibility/corpus.json")
    args = parser.parse_args(argv)
    expected_commit = reviewed_source_commit() if args.reviewed_source else None
    fetch_all(refresh=args.refresh, expected_commit=expected_commit)
    counts = build(expected_commit=expected_commit)
    print(f"built {DB_PATH}")
    print("counts:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
