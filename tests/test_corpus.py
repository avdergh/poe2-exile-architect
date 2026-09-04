"""Corpus query tests. Skipped if the corpus DB hasn't been built."""

from __future__ import annotations

import sqlite3

import pytest

from server.knowledge import db, mechanics

pytestmark = pytest.mark.skipif(
    not db.db_path().exists(),
    reason="corpus not built (run: uv run python -m pipeline.build_corpus)",
)


def test_counts():
    counts = db.corpus_info()["counts"]
    # items dropped from ~5200 after filtering unique-only base types out of the base-item search
    assert counts["items"] > 4500
    assert counts["gems"] > 1000
    assert counts["mods"] > 5000
    assert counts["uniques"] > 300
    assert counts["mechanics"] > 20  # wiki mechanics tier (schema_version 4)


def test_unique_parse_skips_source_line_for_base():
    # Regression: a "Source:" drop line must be filtered, not mistaken for the unique's base — the
    # real base (e.g. Hand of Wisdom and Action -> "Furtive Wraps") follows it in the PoB block.
    from pipeline.build_corpus import UNIQUE_META_RE, clean_mod_line

    block = (
        "Hand of Wisdom and Action\n"
        "Variant: Current\n"
        "Source: Drops from unique{Xesht, We That Are One} in normal{Twisted Domain}\n"
        "{variant:1}Furtive Wraps\n"
        "+(15-25) to Dexterity\n"
    )
    lines = [
        ln
        for ln in (x.rstrip() for x in block.strip("\n").split("\n"))
        if ln.strip() and not UNIQUE_META_RE.match(ln.strip())
    ]
    assert clean_mod_line(lines[0]) == "Hand of Wisdom and Action"
    assert clean_mod_line(lines[1]) == "Furtive Wraps"  # the base, not the Source: line
    assert UNIQUE_META_RE.match("Source: anything")  # the filter that prevents the regression
    assert not UNIQUE_META_RE.match("Furtive Wraps")  # a real base must pass through


def test_radius_jewel_mod_text_matches_pinned_pob_node_scope():
    from pipeline.build_corpus import apply_radius_jewel_scope, parse_radius_jewel_node_types

    node_types = parse_radius_jewel_node_types()
    assert node_types["JewelRadiusColdDamage"] == 1
    assert node_types["JewelRadiusAttackSpeed"] == 2
    assert node_types["AbyssModRadiusJewelPrefixDamageTakenRecoupLife"] == 2
    assert apply_radius_jewel_scope(
        "JewelRadiusColdDamage",
        "(1-2)% increased Cold Damage",
        node_types,
    ).startswith("Small Passive Skills in Radius also grant")
    assert apply_radius_jewel_scope(
        "JewelRadiusAttackSpeed",
        "(1-2)% increased Attack Speed",
        node_types,
    ).startswith("Notable Passive Skills in Radius also grant")
    assert (
        apply_radius_jewel_scope(
            "JewelRadiusLargeSize",
            "Upgrades Radius to Large",
            node_types,
        )
        == "Upgrades Radius to Large"
    )


def test_generated_unique_blocks_are_included_in_corpus_input():
    from pipeline.build_corpus import DB_PATH, parse_uniques

    by_name = {item["name"]: item for item in parse_uniques()}
    assert by_name["Against the Darkness"]["item_type"] == "jewel"
    assert by_name["Heart of the Well"]["item_type"] == "jewel"
    with sqlite3.connect(DB_PATH) as con:
        stored = {
            row[0]
            for row in con.execute(
                "SELECT name FROM uniques WHERE name IN (?, ?)",
                ("Against the Darkness", "Heart of the Well"),
            )
        }
    assert stored == {"Against the Darkness", "Heart of the Well"}


def test_get_gem_fireball():
    g = db.get_gem("Fireball")
    assert g and g["gem_type"] == "active"
    assert "fire" in g["tags"]
    assert g["supports"]


def test_find_skills_by_tag():
    minions = db.find_skills(tag="minion", limit=5)
    assert minions


def test_search_mods_life_on_ring():
    mods = db.search_mods("maximum life", item_tag="ring", mod_type="prefix", limit=5)
    assert mods
    assert all(m["type"] == "prefix" for m in mods)
    assert all(m["id"] for m in mods)
    assert any("life" in m["text"].lower() for m in mods)


def test_radius_jewel_mods_are_stored_with_small_and_notable_scope():
    small = next(
        mod
        for mod in db.search_mods("cold damage", item_tag="int_radius_jewel", limit=200)
        if mod["id"] == "JewelRadiusColdDamage"
    )
    notable = next(
        mod
        for mod in db.search_mods("attack speed", item_tag="dex_radius_jewel", limit=200)
        if mod["id"] == "JewelRadiusAttackSpeed"
    )

    assert small["text"].startswith("Small Passive Skills in Radius also grant")
    assert notable["text"].startswith("Notable Passive Skills in Radius also grant")


def test_reverse_lookup():
    rl = db.reverse_lookup("increased fire damage", limit=5)
    assert rl["mods"] or rl["gems"]


def test_get_unique():
    u = db.get_unique("Andvarius")
    assert u and "Gold Ring" in u["base"]
    assert "Rarity" in u["text"]


def test_find_supports_for():
    fs = db.find_supports_for("Detonate Living")
    assert fs["recommended"]
    assert isinstance(fs["compatible"], list)


def test_explain_mechanic():
    assert "75%" in mechanics.explain("resistances")["principle"]  # Tier-1 evergreen note
    assert mechanics.explain("Spirit")["topic"] == "spirit"  # case/fuzzy
    assert mechanics.explain("nonsense").get("found") is False


def test_explain_mechanic_returns_full_text_hits_as_candidates(monkeypatch):
    from server.knowledge import mechanics

    monkeypatch.setattr(mechanics.db, "get_mechanic", lambda _topic, fuzzy=False: None)
    monkeypatch.setattr(
        mechanics.db,
        "search_mechanics",
        lambda _topic, limit=8: [
            {
                "id": "chaos-inoculation",
                "title": "Chaos Inoculation",
                "snippet": "The page only mentions Mind Over Matter in its body.",
                "url": "https://example.invalid/ci",
                "license": "CC BY-NC-SA 3.0",
                "source": "fixture",
            }
        ],
    )

    result = mechanics.explain("Mind Over Matter")

    assert result["found"] is False
    assert result["resultKind"] == "search_candidates"
    assert result["candidates"][0]["title"] == "Chaos Inoculation"


def test_classify_affix_phys_damage():
    from server.knowledge import itemparse as ip

    r = ip.classify_affix("118% increased Physical Damage")
    assert r and r["type"] == "prefix" and r["tierRange"] == "110-134"


def test_classify_fixed_display_affix_with_hidden_internal_value():
    from server.knowledge import itemparse as ip

    result = ip.classify_affix("Upgrades Radius to Large", base_name="Time-Lost Sapphire")

    assert result is not None
    assert result["type"] == "prefix"
    assert result["tier"] is not None
    assert result["group"] == "JewelRadiusLargerRadius"


def test_corpus_filters_dev_and_special():
    import sqlite3

    con = sqlite3.connect(f"file:{db.db_path()}?mode=ro", uri=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM gems WHERE name LIKE '%DNT%'").fetchone()[0] == 0
        assert (
            con.execute("SELECT COUNT(*) FROM items WHERE tags LIKE '%demigods%'").fetchone()[0]
            == 0
        )
    finally:
        con.close()


def test_parse_item_resist_group_labels():
    from server.knowledge import itemparse as ip

    # single-element resists are stored generically in the corpus; we relabel by actual element
    assert ip.classify_affix("+27% to Cold Resistance")["group"] == "ColdResistance"
    assert ip.classify_affix("+18% to Lightning Resistance")["group"] == "LightningResistance"


def test_parse_item_tiers_and_open_slots():
    from server.knowledge import itemparse as ip

    item = (
        "Item Class: Body Armours\nRarity: Rare\nTest Plate\nAdvanced Vaal Cuirass\n"
        "--------\nItem Level: 81\n--------\n+87 to maximum Life\n+35% to Fire Resistance"
    )
    r = ip.parse_item(item)
    assert r["ok"] and r["rarity"] == "Rare" and r["itemLevel"] == 81
    by = {a["text"]: a for a in r["affixes"]}
    assert by["+87 to maximum Life"]["type"] == "prefix"
    assert "85-99" in (by["+87 to maximum Life"]["tierRange"] or "")
    assert by["+35% to Fire Resistance"]["type"] == "suffix"
    # rare = 3 prefix / 3 suffix; 1 prefix + 1 suffix used -> 2 / 2 open
    assert r["prefixes"] == 1 and r["suffixes"] == 1
    assert r["openPrefixes"] == 2 and r["openSuffixes"] == 2


def test_parse_item_recognizes_energy_shield():
    # Regression: the corpus stored "...maximum EnergyShield" (markup reference, one word) so ES
    # affixes landed in `unrecognized`. The LINK_RE display-side fix restores "Energy Shield".
    from server.knowledge import itemparse as ip

    c = ip.classify_affix("+90 to maximum Energy Shield")
    assert c is not None and c["type"] == "prefix"  # recognized (was landing in `unrecognized`)
    item = (
        "Item Class: Body Armours\nRarity: Rare\nTest Hexshield\nVaal Carapace\n"
        "--------\nItem Level: 81\n--------\n+90 to maximum Energy Shield\n+35% to Fire Resistance"
    )
    r = ip.parse_item(item)
    by = {a["text"]: a for a in r["affixes"]}
    assert by["+90 to maximum Energy Shield"]["type"] == "prefix"
    assert r["prefixes"] == 1  # ES counts as a real prefix, not unrecognized


def test_mechanics_tier_search_and_explain():
    from server.knowledge import mechanics

    # the wiki tier is bundled (schema_version >= 4)
    hits = db.search_mechanics("energy shield recharge", limit=3)
    assert hits and any("Energy" in h["title"] for h in hits)
    assert all(h["license"] == "CC BY-NC-SA 3.0" and h["url"] for h in hits)  # attributed

    # explain combines our evergreen principle (Tier 1) with the attributed wiki page (Tier 2)
    r = mechanics.explain("energy shield")
    assert r["found"] and "principle" in r and "wiki" in r
    assert "CC BY-NC-SA" in r["attribution"]

    # a curated-only topic returns the principle without a bogus wiki match
    r2 = mechanics.explain("ehp")
    assert r2["found"] and "principle" in r2 and "wiki" not in r2

    # unknown topic points at search/lookup
    r3 = mechanics.explain("zzz-not-a-real-topic")
    assert r3["found"] is False and "lookup_mechanic" in r3["hint"]


def test_relevant_mechanics_maps_build_signals():
    from server.knowledge import mechanics

    rel = mechanics.relevant(skill="Spark", tags=["lightning", "spell", "projectile", "duration"])
    titles = {r["title"] for r in rel}
    assert "Shock" in titles  # lightning -> its ailment
    assert "Spell" in titles and "Projectile" in titles
    assert any(r["topic"] == "resistance" for r in rel)  # universal staple
    # relevance guard: tags without a dedicated page must not surface noisy fuzzy matches (#8)
    assert "Damage conversion" not in titles  # was matched by the raw "lightning" tag
    assert "Exposure" not in titles  # was matched by "duration"
    # attribute tags are filtered out as non-mechanics
    rel2 = mechanics.relevant(skill="X", tags=["intelligence", "strength"])
    assert all(r["topic"] not in ("intelligence", "strength") for r in rel2)


def test_wiki_extract_trimmed_of_empty_sections():
    # Full-page wiki extracts must not carry hollow template section headers (#7).
    m = db.get_mechanic("shock")
    assert m and "Related skills" not in m["text"]  # empty section header dropped at ingest


def test_affix_pool_keeps_per_element_variants():
    # The gear optimizer needs every craftable variant; per-element mods sharing a group must not
    # collapse to one (a lightning build must be able to pick +Lightning levels, not just +Fire).
    pool = db.affix_pool("Dueling Wand")
    suf_text = [m["text"] for m in pool["suffixes"]]
    assert any("Lightning Spell Skills" in t for t in suf_text)
    assert any("Fire Spell Skills" in t for t in suf_text)
    # real corpus mods only, with a group for exclusivity
    assert all(m.get("group") for m in pool["prefixes"] + pool["suffixes"])


def test_illegal_affixes_flags_mana_on_body_armour():
    # The integrity check: a "% increased maximum Mana" affix can't roll on a body armour, so a
    # hand-crafted "mana chest" is flagged (its computed DPS would include invented mods).
    bad = db.illegal_affixes(
        "Sacramental Robe",
        ["60% increased maximum Mana", "109% increased Energy Shield", "+40% to Fire Resistance"],
    )
    flagged = {b["affix"] for b in bad}
    assert "60% increased maximum Mana" in flagged
    assert "109% increased Energy Shield" not in flagged  # %ES IS legal on an ES body
    assert "+40% to Fire Resistance" not in flagged


def test_illegal_affixes_clean_on_legit_gear():
    # No false positives on real, craftable rolls.
    assert (
        db.illegal_affixes(
            "Sapphire Ring", ["+140 to maximum Mana", "+42% to Lightning Resistance"]
        )
        == []
    )
    assert (
        db.illegal_affixes("Ancestral Tiara", ["+170 to maximum Mana"]) == []
    )  # mana legal on helmet
    assert db.illegal_affixes("Totally Fake Base", ["anything"]) == []  # unknown base → no warnings


def test_get_unique_disambiguates_base_type():
    # A base type name returns a clear message, not a confusing null (#8).
    from server.main import get_unique

    r = get_unique("Warmonger Bow")  # a base, not a unique
    assert r["found"] is False and "base" in r["note"].lower()


def test_search_mods_precision():
    # Column-scoped match: a stat-text query must not match unrelated mods via stat ids
    # (e.g. "physical damage" was wrongly returning Armour mods).
    mods = db.search_mods("physical damage", limit=10)
    assert mods
    assert all("physical" in m["text"].lower() for m in mods)
    inc = db.search_mods("increased physical damage", limit=5)
    assert any("physical damage" in m["text"].lower() for m in inc)
