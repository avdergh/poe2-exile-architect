"""Base capacity must agree across crafting, parsing and final legality gates."""

from __future__ import annotations

import pytest

from server.compute import itemopt
from server.knowledge import db, itemparse

pytestmark = pytest.mark.skipif(not db.db_path().exists(), reason="corpus not built")


@pytest.mark.parametrize(
    ("base", "capacity"),
    [
        ("Emerald", 2),
        ("Ruby", 2),
        ("Sapphire", 2),
        ("Diamond", 2),
        ("Time-Lost Ruby", 2),
        ("Time-Lost Emerald", 2),
        ("Time-Lost Sapphire", 2),
        ("Time-Lost Diamond", 2),
        ("Grand Spear", 3),
        ("Fine Belt", 3),
        ("Ultimate Mana Flask", 1),
    ],
)
def test_static_base_capacity_is_shared_with_empty_item_readback(base, capacity):
    # Pinned PoB Item.lua gives ordinary/radius rare Jewels four affixes. Ordinary
    # rares retain six; flask domains retain their existing magic-only contract.
    profile = db.craft_profile(base)
    assert profile["prefixLimit"] == profile["suffixLimit"] == capacity
    raw = itemopt._item_text(base, [], "Jewel", ilvl=95)
    parsed = itemparse.parse_item(raw)
    assert parsed["openPrefixes"] == parsed["openSuffixes"] == capacity


def _distinct_mods(base, side, count):
    pool = db.affix_pool(base, ilvl=95)[side]
    selected = []
    groups = set()
    for mod in pool:
        if mod["group"] not in groups:
            selected.append(mod)
            groups.add(mod["group"])
        if len(selected) == count:
            return selected
    raise AssertionError(f"fixture needs {count} distinct {side} for {base}")


@pytest.mark.parametrize("base", ["Emerald", "Sapphire", "Time-Lost Sapphire"])
@pytest.mark.parametrize(
    ("side", "issue"),
    [("prefixes", "prefix_limit_exceeded"), ("suffixes", "suffix_limit_exceeded")],
)
def test_extra_jewel_affix_rejected_by_shared_audit_and_explicit_selection(base, side, issue):
    mods = _distinct_mods(base, side, 3)
    lines = [itemopt._roll(mod["text"], "realistic") for mod in mods]
    raw = itemopt._item_text(base, lines, "Jewel", ilvl=95)
    audit = itemparse.audit_item_legality(raw)
    assert issue in audit["issues"]
    assert not audit["ok"]

    class SelectionEngine:
        def get_build(self):
            return {"level": 95}

    result = itemopt.optimize_jewel(
        SelectionEngine(), base=base, selected_mod_ids=[mod["id"] for mod in mods]
    )
    assert result["ok"] is False
    assert result["errorCode"] == "jewel_affix_limit_exceeded"


@pytest.mark.parametrize("base", ["Ruby", "Emerald", "Sapphire", "Diamond"])
def test_automatic_jewel_selection_respects_base_capacity_and_restores_state(base):
    class MarginalEngine:
        custom_mods = "existing modifier"

        def get_build(self):
            return {"level": 95, "customMods": self.custom_mods}

        def get_xml(self):
            return self.custom_mods

        def set_config(self, *, custom_mods):
            self.custom_mods = custom_mods
            return {"stats": {"TotalDPS": float(len(custom_mods.splitlines()))}}

        def load_build_xml(self, snapshot):
            self.custom_mods = snapshot

    engine = MarginalEngine()
    before = engine.get_xml()
    result = itemopt.optimize_jewel(engine, base=base)
    assert engine.get_xml() == before
    assert result["ok"] is True
    parsed = itemparse.parse_item(result["item"])
    assert parsed["prefixes"] <= 2
    assert parsed["suffixes"] <= 2
    assert parsed["prefixes"] + parsed["suffixes"] == 4
    assert itemparse.audit_item_legality(result["item"])["ok"] is True


def test_magic_jewels_keep_one_affix_per_side():
    raw = "Rarity: Magic\nEmerald\nItem Level: 95\n--------\n"
    parsed = itemparse.parse_item(raw)
    assert parsed["openPrefixes"] == parsed["openSuffixes"] == 1
