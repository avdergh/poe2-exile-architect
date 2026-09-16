"""A tree-granted host must not force per-candidate full-build reloads."""

from xml.sax.saxutils import escape

import pytest

from server.compute import craftopt, skillgroups, socket_probe
from server.compute.state import build_state_hash


@pytest.mark.parametrize(
    "source,gem_count,expected",
    [("Tree:5817", 6, False), ("Default Attack", 1, False),
     ("Default Attack", 2, True), ("Item:1", 1, True), ("Unknown", 1, True)],
)
def test_source_probe_path_is_selected_by_ownership(source, gem_count, expected):
    gems = '<Gem nameSpec="Fireball"/>' * gem_count
    xml = f'<PathOfBuilding2><Skills><Skill source="{escape(source)}">{gems}</Skill></Skills></PathOfBuilding2>'
    assert socket_probe.requires_source_snapshot_probe(xml) is expected


def test_tree_host_rune_candidates_use_native_batch_and_match_full_reload(engine, monkeypatch):
    engine.new_build()
    engine.set_class("Ranger", "Deadeye")
    engine.set_level(99)
    engine.set_config(custom_mods="+500 to Strength\n+500 to Dexterity\n+500 to Intelligence")
    engine.call("alloc_passive", node=5817)
    skillgroups.set_main_skill(engine, "Ice Shot\nElemental Armament II")
    added = skillgroups.add_skill_group(
        engine, "Mirage Deadeye\nIce Shot\nElemental Armament II\nRapid Attacks II"
    )
    assert added.get("ok") is not False, added
    raw = "Rarity: Rare\nRune Path Probe\nWarmonger Bow\nItem Level: 82\n100% increased Physical Damage"
    assert engine.add_item(raw, slot="Weapon 1")["ok"]
    before = engine.get_xml()
    all_options = engine.crafting_options("Weapon 1")
    options = [r for r in all_options["runes"] if r["name"] in {"Iron Rune", "Glacial Rune"}]
    assert len(options) == 2
    monkeypatch.setattr(engine, "crafting_options", lambda slot: {**all_options, "runes": options})
    eval_items = engine.eval_items
    batches = []

    def measured_batch(slot, items, keys=None, **kwargs):
        batches.append(list(items))
        response = eval_items(slot, items, keys=keys, **kwargs)
        assert response["rolledBack"]
        # The slow XML path remains an independent numerical and identity oracle.
        baseline = engine.get_xml()
        try:
            for candidate, measured in zip(items, response["results"], strict=True):
                socket_probe.load_candidate(engine, baseline, slot, candidate)
                expected = engine.get_stats(keys)["stats"]
                assert measured == pytest.approx(expected)
        finally:
            engine.load_build_xml(baseline)
        return response

    monkeypatch.setattr(engine, "eval_items", measured_batch)
    result = craftopt.optimize_item_sockets(
        engine, slot="Weapon 1", socket_count=2, goals={"TotalDPS": 1}
    )
    assert result["ok"], result
    assert result["measurementComplete"]
    assert len(batches) == 2 and all(len(batch) == 2 for batch in batches)
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)
