"""Real PoB socket candidate order must not leak Rune slots or modifier caches."""

from server.compute import craftopt
from server.compute.engine import PobEngine
from server.compute.state import build_state_hash


def test_isolated_socket_candidates_are_order_independent_and_restore_snapshot():
    engine = PobEngine()
    try:
        engine.new_build()
        engine.set_class("Sorceress")
        engine.set_level(92)
        raw = "Rarity: Rare\nSocket Target\nSacramental Robe\nItem Level: 82\n--------\n+50 to maximum Life"
        engine.add_item(raw, slot="Body Armour")
        options = engine.crafting_options("Body Armour")["runes"]
        iron = next(option for option in options if option["name"] == "Iron Rune")
        perfect = next(option for option in options if option["name"] == "Perfect Iron Rune")
        original = craftopt._augment_item_with_runes(raw, [(iron["name"], iron["mods"])] * 2, socket_capacity=2)
        better = craftopt._augment_item_with_runes(raw, [(perfect["name"], perfect["mods"])] * 2, socket_capacity=2)
        engine.add_item(original, slot="Body Armour")
        snapshot_hash = build_state_hash(engine.get_xml())
        items = [better, raw, original, raw]
        forward = engine.eval_items("Body Armour", items, ["EnergyShield"], isolate_each_item=True)["results"]
        backward = engine.eval_items("Body Armour", list(reversed(items)), ["EnergyShield"], isolate_each_item=True)["results"]
        assert forward == list(reversed(backward))
        assert forward[0]["EnergyShield"] > forward[2]["EnergyShield"] > forward[1]["EnergyShield"]
        assert forward[1] == forward[3]
        assert build_state_hash(engine.get_xml()) == snapshot_hash
    finally:
        engine.close()
