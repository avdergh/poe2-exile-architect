"""Passive-tree search + allocation tests."""

from __future__ import annotations

import pytest

from server.compute.state import build_state_hash


@pytest.mark.parametrize(
    "class_name,attribute", [("Warrior", "Intelligence"), ("Sorceress", "Dexterity")]
)
def test_explicit_attribute_path_and_local_switch_survive_reload(engine, class_name, attribute):
    engine.new_build()
    engine.set_class(class_name)
    engine.set_level(90)
    # A long path can remain wholly inside the class's nonattribute starting cluster.
    # Choose by actual PoB path membership so this exercises at least two switchable nodes.
    attribute_ids = {
        n["id"] for n in engine.search_passives(limit=6000)["results"] if n["isAttribute"]
    }
    candidates = engine.search_passives(node_type="Notable", limit=6000)["results"]
    target = min(
        (
            n for n in candidates
            if n.get("pathDist", 0) >= 6 and len(attribute_ids.intersection(n["pathNodeIds"])) >= 2
        ),
        key=lambda n: (n["pathDist"], n["id"]),
    )
    result = engine.alloc_passive(target["id"], path_attribute=attribute)
    assert result["ok"]
    nodes = engine.search_passives(limit=6000)["results"]
    attributes = [n for n in nodes if n["alloc"] and n["isAttribute"]]
    assert attributes and all(n["attribute"] == attribute for n in attributes)
    assert all(
        n["attributeOptions"] == ["Strength", "Dexterity", "Intelligence"] for n in attributes
    )
    assert all(
        engine.get_passive(n["id"])["attributeOptions"] == n["attributeOptions"] for n in attributes
    )
    allocated_ids = {n["id"] for n in nodes if n["alloc"]}
    selected = attributes[0]["id"]
    before = engine.get_stats(["Str", "Dex", "Int"])["stats"]
    changed = engine.set_passive_attribute(selected, "Strength")
    assert changed["ok"] and changed["pointsSpent"] == 0
    after = engine.get_stats(["Str", "Dex", "Int"])["stats"]
    assert after["Str"] > before["Str"]
    unchanged = [n for n in attributes if n["id"] != selected]
    assert all(engine.get_passive(n["id"])["attribute"] == attribute for n in unchanged)
    xml = engine.get_xml()
    saved_hash = build_state_hash(xml)
    engine.load_build_xml(xml, name="attribute-roundtrip")
    assert build_state_hash(engine.get_xml()) == saved_hash
    assert engine.get_passive(selected)["attribute"] == "Strength"
    assert {
        n["id"] for n in engine.search_passives(limit=6000)["results"] if n["alloc"]
    } == allocated_ids
    assert engine.set_passive_attribute(selected, "Strength")["already"]
    assert build_state_hash(engine.get_xml()) == saved_hash
    # Invalid, nonattribute and unallocated nodes must never write a new override.
    for node_id, value, code in [
        (selected, "Magic", "invalid_passive_attribute"),
        (target["id"], "Dexterity", "passive_node_not_attribute"),
        (
            next(n["id"] for n in nodes if n["isAttribute"] and not n["alloc"]),
            "Intelligence",
            "passive_node_not_allocated",
        ),
    ]:
        assert engine.set_passive_attribute(node_id, value)["errorCode"] == code
        assert build_state_hash(engine.get_xml()) == saved_hash


def test_keystones_listed(fireball):
    ks = fireball.search_passives(node_type="Keystone", limit=5)["results"]
    assert ks
    assert all(n["type"] == "Keystone" for n in ks)


def test_alloc_then_dealloc(fireball):
    notables = fireball.search_passives(node_type="Notable", limit=400)["results"]
    reachable = [n for n in notables if n.get("pathDist")]
    assert reachable, "no reachable notables"
    target = min(reachable, key=lambda n: n["pathDist"])

    res = fireball.alloc_passive(target["id"])
    assert res["ok"] and res["pointsSpent"] >= 1
    assert res["statsDelta"]

    de = fireball.dealloc_passive(target["id"])
    assert de["ok"] and de["pointsFreed"] >= 1


def test_optimize_improves_dps(fireball):
    res = fireball.optimize_passives(metric="TotalDPS", points=5)
    assert res["allocated"], "optimizer allocated nothing"
    assert res["finalValue"] > res["startValue"]


def test_split_personality_jewel_opens_other_class_regions(engine):
    # "Split Personality" grants "allocate Passive Skills from <class>'s starting point" for several
    # classes. Socketing it must register in the tree (spec.jewels) AND rebuild paths so each
    # granted class-start becomes a path ROOT — making far regions cheaper for optimize_passives /
    # alloc_passive. Regression for the dynamic-jewel pathing fix (shim socket-sync + fork
    # multi-start). Uses classes that are NOT last in the list to prove ALL granted starts apply,
    # not just PoB's single (last-overwritten) jewelData.alternateClassStart.
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(90)
    engine.alloc_passive(2491)  # allocate a jewel socket so a socketed jewel actually applies

    def cheap_notables(k=20):
        nodes = engine.search_passives(node_type="Notable", limit=4000)["results"]
        return sum(1 for n in nodes if (n.get("pathDist") or 1000) <= k)

    before = cheap_notables()
    raw = (
        "Rarity: Unique\nSplit Personality\nRuby\nLimited to: 1\n"
        "Can Allocate Passive Skills from the Mercenary's starting point\n"
        "Can Allocate Passive Skills from the Ranger's starting point\n"
        "Can Allocate Passive Skills from the Warrior's starting point\n"
        "Can Allocate Passive Skills from the Shadow's starting point\nCorrupted"
    )
    engine.call("equip_jewel", socket=2491, raw=raw)
    after = cheap_notables()
    assert after > before + 25, f"jewel opened too few cheap notables: {before} -> {after}"

    # Unequipping reverts the tree pathing (no stale jewel state left behind).
    engine.call("unequip_item", slot="Jewel 2491")
    assert cheap_notables() == before


def test_set_class_and_ascendancy(engine):
    engine.new_build()
    r = engine.set_class("Mercenary", "Witchhunter")
    assert r["ok"] and r["class"] == "Mercenary" and r["ascendancy"] == "Witchhunter"

    # a Witchhunter ascendancy node should now exist and be reachable
    nodes = engine.search_passives(node_type=None, limit=6000)["results"]
    wh = [n for n in nodes if (n.get("ascendancy") or "") == "Witchhunter" and n.get("pathDist")]
    assert wh, "no reachable Witchhunter ascendancy nodes after set_class"

    # optimize now paths from the correct class start
    op = engine.optimize_passives(metric="Life", points=5)
    assert op["finalValue"] > op["startValue"]


def test_search_passives_ascendancy_and_partial(engine):
    engine.new_build()
    engine.set_class("Mercenary", "Witchhunter")
    # ascendancy name is now searchable -> returns that ascendancy's nodes
    asc = engine.search_passives(query="Witchhunter")["results"]
    assert asc and all(n.get("ascendancy") == "Witchhunter" for n in asc)
    # multi-word/conceptual query returns ranked partial matches (used to AND to []):
    multi = engine.search_passives(query="explode on death fire damage", limit=10)["results"]
    assert multi


def test_search_passives_reachable_first(fireball):
    # with no query, browse mode ranks reachable nodes (lowest pathDist) first
    res = fireball.search_passives(node_type="Notable", limit=50)["results"]
    dists = [n["pathDist"] for n in res if n.get("pathDist") is not None]
    assert dists == sorted(dists)


def test_set_class_unknown_lists_valid_options(engine):
    engine.new_build()
    bad_cls = engine.set_class("Notaclass")
    assert bad_cls["ok"] is False
    # the error must help the model self-correct by naming the real classes
    assert "Valid classes" in bad_cls["error"] and "Witch" in bad_cls["error"]

    bad_asc = engine.set_class("Witch", "Witchhunter")  # Witchhunter belongs to Mercenary
    assert bad_asc["ok"] is False
    assert "Valid ascendancies" in bad_asc["error"]


def test_set_level(engine):
    engine.new_build()
    base = engine.get_stats(["Life"])["stats"]["Life"]
    r = engine.set_level(90)
    assert r["ok"] and r["level"] == 90
    assert r["stats"]["Life"] > base  # higher level => more life (auto-leveling disabled)


def test_get_build_readback(engine):
    engine.new_build()
    engine.set_class("Mercenary", "Witchhunter")
    engine.set_level(90)
    engine.paste_skill("Detonate Living 20/0  1")
    b = engine.get_build()
    assert b["class"] == "Mercenary" and b["ascendancy"] == "Witchhunter" and b["level"] == 90
    assert b["mainSkill"] == "Detonate Living"


def test_list_config_options(engine):
    opts = engine.list_config_options(query="boss")["options"]
    assert any(o["var"] == "enemyIsBoss" for o in opts)


def test_equip_then_unequip(engine):
    engine.new_build()
    engine.paste_skill("Fireball 20/0  1")
    engine.add_item("Rarity: Rare\nR\nRuby Ring\n+50 to maximum Life")
    assert "Ring 1" in engine.get_build()["gear"]
    engine.unequip_item("Ring 1")
    assert "Ring 1" not in engine.get_build()["gear"]


def test_get_defenses(engine):
    engine.new_build()
    engine.set_class("Mercenary", "Witchhunter")
    engine.set_level(90)
    engine.paste_skill("Detonate Living 20/0  1")
    d = engine.get_defenses()
    assert d["life"] and d.get("note")
    assert set(d["resistances"]) == {"fire", "cold", "lightning", "chaos"}
    # The note must report the *actual* penalty (config default -60), not a hard-coded guess.
    # PoB nets that against a +10% elemental baseline, so a fresh elemental resist = penalty + 10.
    assert d["resistPenalty"] == -60
    assert d["resistances"]["fire"] == d["resistPenalty"] + 10


def test_points_available_scales_with_level(engine):
    engine.new_build()
    engine.set_level(90)
    a90 = engine.get_build()["pointsAvailable"]
    engine.set_level(20)
    a20 = engine.get_build()["pointsAvailable"]
    assert a90 > a20 > 0


def test_attack_skill_no_weapon_warning(engine):
    engine.new_build()
    engine.set_class("Monk", "Martial Artist")
    r = engine.paste_skill("Tempest Flurry 20/0  1")  # attack skill, no weapon
    assert r.get("warning") and "weapon" in r["warning"].lower()
    engine.add_item("Rarity: Rare\nX\nSteelpoint Quarterstaff\n120% increased Physical Damage")
    assert engine.get_stats(["TotalDPS"]).get("warning") is None  # cleared once armed


def test_optimize_balanced_raises_offense_and_defense(engine):
    engine.new_build()
    engine.set_class("Monk", "Martial Artist")
    engine.set_level(90)
    engine.paste_skill("Tempest Flurry 20/0  1")
    engine.add_item("Rarity: Rare\nX\nSteelpoint Quarterstaff\n120% increased Physical Damage")
    r = engine.optimize_passives(metric="balanced", points=12)
    assert r["finalDPS"] > r["startDPS"] and r["finalEHP"] > r["startEHP"]


def test_scaffold_gear_caps_resists_gap_driven(engine):
    from server import scaffold

    engine.new_build()
    engine.set_class("Monk", "Martial Artist")
    engine.set_level(90)
    engine.paste_skill("Tempest Flurry 20/0  1")
    engine.add_item("Rarity: Rare\nX\nSteelpoint Quarterstaff\n120% increased Physical Damage")
    before_life = engine.get_defenses()["life"]
    r = scaffold.scaffold_gear(engine)
    assert r["ok"] and r["filled"]
    ra = r["resistsAfter"]
    assert ra["fire"] >= 75 and ra["cold"] >= 75 and ra["lightning"] >= 75  # capped
    assert r["lifeAfter"] > before_life  # life pool added (auto)
    # pool="none" -> resists only, no life/ES
    engine.new_build()
    engine.set_class("Witch")
    r2 = scaffold.scaffold_gear(engine, pool="none")
    assert all(
        "Life" not in m and "Energy Shield" not in m for f in r2["filled"] for m in f["mods"]
    )


def test_scaffold_gear_es_default_for_int_class(engine):
    from server import scaffold

    # an intelligence class (Sorceress) auto-defaults to Energy Shield, not Life (#9)
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/0  1")
    r = scaffold.scaffold_gear(engine)
    assert r["pool"] == "energy_shield"
    assert (r["energyShieldAfter"] or 0) > 0
    # chaos resistance isn't scaffolded -> surfaced + flagged in the note (#9)
    assert "chaosResAfter" in r
    if (r["chaosResAfter"] or 0) <= 0:
        assert "Chaos resistance" in r["note"]


def test_engine_reports_tree_version(engine):
    # the ready frame surfaces the passive-tree data version (used by engine_health)
    assert engine.info.get("treeVersion")


def test_engine_health_reports_versions():
    from server.main import engine_health

    h = engine_health()
    assert h["pong"] is True
    assert h["serverVersion"] and h["dataSource"] in {"bundled", "user-data"}
    assert h["treeVersion"]
