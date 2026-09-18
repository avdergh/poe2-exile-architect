"""C5/C6 oracle: replacement context, complete-item comparison and plan replay."""

from contextlib import nullcontext
from copy import deepcopy
from html import escape
from xml.etree import ElementTree as ET

import pytest
from types import SimpleNamespace

from server.compute import attainability, itemopt, item_search
from server.compute.state import build_state_hash


def raw_item(lines=(), base="Gold Ring"):
    return "\n".join(["Rarity: Rare", "Test Item", base, "Item Level: 90", "--------", *lines])


@pytest.mark.parametrize(
    "violation",
    [None, "nan", "bool", "defense", "occupied", "swap", "context", "compatible", "types"],
)
def test_unavailable_baseline_requires_empty_active_weapon_and_exact_pob_check(violation):
    build = {
        "activeWeaponSet": 1,
        "gear": {},
        "mainSkillWeaponCheck": {
            "skillName": "Fixture Attack",
            "compatible": False,
            "weaponTypes": ["Spear"],
            "equippedWeaponTypes": [],
        },
    }
    context = {"skillName": "Fixture Attack"}
    stats = {"Life": 100}
    if violation == "nan":
        stats["TotalDPS"] = float("nan")
    elif violation == "bool":
        stats["TotalDPS"] = False
    elif violation == "defense":
        stats["Life"] = None
    elif violation == "occupied":
        build["gear"] = {"Weapon 1": {"base": "Wand"}}
    elif violation == "swap":
        build["activeWeaponSet"] = 2
    elif violation == "context":
        context["skillName"] = "Another Output"
    elif violation == "compatible":
        build["mainSkillWeaponCheck"]["compatible"] = True
    elif violation == "types":
        build["mainSkillWeaponCheck"]["equippedWeaponTypes"] = ["Wand"]
    engine = SimpleNamespace(
        get_stats=lambda _keys: {"stats": stats}, get_xml=lambda: "<PathOfBuilding/>"
    )
    if violation:
        with pytest.raises(item_search.ItemSearchError, match="item_measurement_incomplete"):
            item_search.baseline_stats(engine, "Weapon 1", ["TotalDPS", "Life"], build, context)
    else:
        assert item_search.baseline_stats(
            engine, "Weapon 1", ["TotalDPS", "Life"], build, context
        ) == {"TotalDPS": None, "Life": 100}


@pytest.mark.parametrize("weighted", [False, True])
def test_upgrade_rank_cannot_replace_missing_baseline_with_zero(monkeypatch, weighted):
    engine = SimpleNamespace(get_xml=lambda: "<PathOfBuilding/>")
    monkeypatch.setattr(
        itemopt,
        "optimize_item",
        lambda *_a, **_k: {
            "ok": True,
            "metricBefore": None,
            "metricAfter": 100,
            "metricsBefore": {"TotalDPS": None},
            "metricsAfter": {"TotalDPS": 100},
            "affixes": [],
            "item": "candidate",
        },
    )
    result = itemopt.rank_upgrades(
        engine, slots=["Weapon 1"], goals={"TotalDPS": 1} if weighted else None
    )
    assert result["ranked"] == []
    assert result["rejected"] == [
        {"slot": "Weapon 1", "errorCode": "item_upgrade_comparison_unavailable"}
    ]


class ItemOracle:
    def __init__(self, items=None, gains=None):
        self.items = dict(items or {})
        self.gains = dict(gains or {})
        self.base_gains = {}
        self.probes = []
        self.override_batch = None
        self.combined_override = None
        self.clear_result = {"ok": True}
        self.restore_fails = False
        self.drop_slot = None

    def transaction_lock(self):
        return nullcontext()

    def get_xml(self):
        entries = "".join(
            f'<Item id="{i}">{escape(raw)}</Item>'
            for i, (_, raw) in enumerate(sorted(self.items.items()), 1)
        )
        slots = "".join(
            f'<Slot name="{slot}" itemId="{i}"/>'
            for i, (slot, _) in enumerate(sorted(self.items.items()), 1)
        )
        sockets = "".join(
            f'<Socket nodeId="{slot.split()[1]}" itemId="{i}"/>'
            for i, (slot, _) in enumerate(sorted(self.items.items()), 1)
            if slot.startswith("Jewel ")
        )
        # Match PoB's active-Spec authority; the ItemSet mirror above is not jewel evidence.
        tree = f'<Tree activeSpec="1"><Spec nodes="1"><Sockets>{sockets}</Sockets></Spec></Tree>'
        return f'<PathOfBuilding2><Build level="90"/>{tree}<Items activeItemSet="1">{entries}<ItemSet id="1">{slots}</ItemSet></Items><Config/></PathOfBuilding2>'

    def list_jewel_sockets(self):
        return {"sockets": [{"socket": 1, "allocated": True, "filled": "Jewel 1" in self.items}]}

    def load_build_xml(self, xml, **_kwargs):
        if self.restore_fails:
            raise OSError("fixture restore failure")
        root = ET.fromstring(xml).find("Items")
        by_id = {node.get("id"): node.text or "" for node in root.findall("Item")}
        self.items = {
            slot.get("name"): by_id[slot.get("itemId")] for slot in root.findall("./ItemSet/Slot")
        }

    def get_build(self):
        return {
            "level": 90,
            "class": "Sorceress",
            "gear": {
                slot: {"base": raw.splitlines()[2], "rarity": "rare"}
                for slot, raw in self.items.items()
            },
        }

    def get_stats(self, keys):
        value = 100 + sum(
            self.gains.get(line, 0) for raw in self.items.values() for line in raw.splitlines()
        )
        value += sum(self.base_gains.get(raw.splitlines()[2], 0) for raw in self.items.values())
        if self.combined_override and self.combined_override[0].issubset(
            {line for raw in self.items.values() for line in raw.splitlines()}
        ):
            value = self.combined_override[1]
        return {"stats": {key: value for key in keys}}

    def get_defenses(self):
        fire = 30 + sum(30 for raw in self.items.values() if "+30% to Fire Resistance" in raw)
        return {
            "resistances": {"fire": fire, "cold": 60, "lightning": 60, "chaos": 30},
            "resistMissing": {"fire": max(0, 75 - fire), "cold": 15, "lightning": 15},
            "totalEHP": self.get_stats(["TotalEHP"])["stats"]["TotalEHP"],
        }

    def unequip_item(self, slot):
        if self.clear_result.get("ok"):
            self.items.pop(slot, None)
        return self.clear_result

    def add_item(self, raw, slot):
        self.items[slot] = raw
        if self.drop_slot:
            self.items.pop(self.drop_slot, None)
        return {"ok": True, "slot": slot}

    def inspect_item_replacement_context(self, expected_context=None):
        return {"ok": True, "contextStatus": "no_active_output"}

    def eval_items(self, slot, items, keys, *, replacement_context=False):
        assert replacement_context
        self.probes.extend(items)
        if self.override_batch is not None:
            return {
                "contextVersion": "item_replacement_context_v1",
                "rolledBack": True,
                **self.override_batch,
            }
        saved = deepcopy(self.items)
        values = []
        for raw in items:
            self.items = {**saved, slot: raw}
            values.append(self.get_stats(keys)["stats"])
        self.items = saved
        return {
            "results": values,
            "rolledBack": True,
            "recoveryRequired": False,
            "contextVersion": "item_replacement_context_v1",
        }


@pytest.fixture
def pools(monkeypatch):
    pool = {
        "prefixes": [{"text": "+10 to maximum Life", "type": "prefix", "group": "life"}],
        "suffixes": [{"text": "+30% to Fire Resistance", "type": "suffix", "group": "fire"}],
    }
    monkeypatch.setattr(itemopt.db, "affix_pool", lambda *_args, **_kwargs: pool)
    monkeypatch.setattr(
        itemopt,
        "_affix_candidates_for_policy",
        lambda source, **_kwargs: [{**source, "line": source["text"], "_deepTopTier": False}],
    )
    monkeypatch.setattr(
        itemopt, "_item_text", lambda base, lines, *_args, **_kwargs: raw_item(lines, base)
    )
    monkeypatch.setattr(itemopt, "_item_attainability_reasons", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(itemopt, "_generated_item_legality", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(
        itemopt.hard_legality,
        "audit_build",
        lambda *_args, **_kwargs: {
            "status": "passed",
            "hardLegalityReady": True,
            "hardFailures": [],
            "checks": {},
        },
    )
    return pool


def craft(engine):
    return itemopt._marginal_craft(
        engine,
        "Ring 1",
        "Gold Ring",
        {"TotalEHP": 1},
        "realistic",
        chaos_resist_target=30,
        elemental_resist_target=60,
        ilvl=90,
        acquisition_policy=attainability.policy_for("realistic_trade"),
    )


def test_replacement_pruning_excludes_old_ring_resistance(pools):
    engine = ItemOracle(
        {"Ring 1": raw_item(["+30% to Fire Resistance"])},
        {"+30% to Fire Resistance": 30, "+10 to maximum Life": 10},
    )
    before = engine.get_xml()
    result = craft(engine)
    assert "+30% to Fire Resistance" in result
    assert "+10 to maximum Life" in result
    assert engine.get_xml() == before
    assert any("Fire Resistance" in value for value in engine.probes)


def test_prefix_and_suffix_share_budget_by_measured_value(pools):
    pools["prefixes"] = [{"text": f"P{i}", "type": "prefix", "group": f"p{i}"} for i in range(3)]
    pools["suffixes"] = [{"text": f"S{i}", "type": "suffix", "group": f"s{i}"} for i in range(3)]
    engine = ItemOracle(
        gains={**{f"P{i}": 1 for i in range(3)}, **{f"S{i}": 100 for i in range(3)}}
    )
    result = craft(engine)
    chosen = [line for line in result.splitlines() if line in engine.gains]
    assert sum(engine.gains[line] for line in chosen) == 302
    assert len(chosen) == 5
    pools["prefixes"].reverse()
    pools["suffixes"].reverse()
    assert craft(engine) == result


@pytest.mark.parametrize("entrypoint", ["plan", "optimize"])
def test_item_search_uses_static_base_capacity_in_all_probes(pools, entrypoint):
    pools["prefixes"] = [{"text": f"P{i}", "type": "prefix", "group": f"p{i}"} for i in range(3)]
    pools["suffixes"] = [{"text": f"S{i}", "type": "suffix", "group": f"s{i}"} for i in range(3)]
    engine = ItemOracle(gains={**{f"P{i}": 1 for i in range(3)}, **{f"S{i}": 100 for i in range(3)}})
    before = engine.get_xml()
    if entrypoint == "plan":
        item = itemopt._marginal_craft(
            engine, "Jewel 1", "Ruby", {"TotalEHP": 1}, "realistic",
            chaos_resist_target=30, elemental_resist_target=60, ilvl=90,
            acquisition_policy=attainability.policy_for("realistic_trade"),
        )
    else:
        result = itemopt.optimize_item(engine, "Jewel 1", base="Ruby", metric="TotalEHP")
        assert result["ok"] is True, result
        item = result["item"]
    assert engine.get_xml() == before
    assert sum(line in engine.gains for line in item.splitlines()) == 4
    for probe in [*engine.probes, item]:
        assert sum(line in {"P0", "P1", "P2"} for line in probe.splitlines()) <= 2
        assert sum(line in {"S0", "S1", "S2"} for line in probe.splitlines()) <= 2


def test_whole_candidate_must_improve_the_actual_original_item(pools):
    engine = ItemOracle(
        {"Ring 1": raw_item(["Original"])},
        {"Original": 100, "+30% to Fire Resistance": 30, "+10 to maximum Life": 10},
    )
    assert craft(engine) is None
    assert "Original" in engine.items["Ring 1"]


def test_linear_score_does_not_override_negative_full_combination(pools):
    engine = ItemOracle(gains={"+30% to Fire Resistance": 30, "+10 to maximum Life": 10})
    engine.combined_override = ({"+30% to Fire Resistance", "+10 to maximum Life"}, 90)
    assert craft(engine) is None


@pytest.mark.parametrize(
    "batch",
    [
        {},
        {"results": []},
        {"results": [False]},
        {"results": [{}]},
        {"results": [{"TotalEHP": True}]},
        {"results": [{"TotalEHP": float("nan")}]},
        {"results": [{"TotalEHP": float("inf")}]},
        {"results": [{"TotalEHP": 100}, {"TotalEHP": 110}]},
    ],
)
def test_incomplete_measurement_cannot_be_no_improvement(batch, pools):
    engine = ItemOracle({"Ring 1": raw_item()})
    engine.override_batch = batch
    before = engine.get_xml()
    with pytest.raises(item_search.ItemSearchError):
        craft(engine)
    assert engine.get_xml() == before


def test_clear_failure_does_not_prune_against_old_item(pools):
    engine = ItemOracle({"Ring 1": raw_item(["+30% to Fire Resistance"])})
    engine.clear_result = {"ok": False}
    with pytest.raises(item_search.ItemSearchError, match="item_slot_clear_failed"):
        craft(engine)
    assert not engine.probes


def test_legacy_finite_results_do_not_prove_replacement_context(pools, monkeypatch):
    engine = ItemOracle({"Ring 1": raw_item()})
    monkeypatch.setattr(
        engine, "eval_items", lambda *_args, **_kwargs: {"results": [{"TotalEHP": 100}]}
    )
    result = itemopt.optimize_item(engine, "Ring 1", metric="TotalEHP")
    assert result["errorCode"] == "item_candidate_evaluation_unverified"
    assert result["rolledBack"] is True


def test_positive_values_cannot_override_explicit_candidate_failure(pools):
    engine = ItemOracle({"Ring 1": raw_item()})
    engine.override_batch = {
        "results": [{"TotalEHP": 200}],
        "failureCodes": ["item_replacement_context_mismatch"],
    }
    result = itemopt.optimize_item(engine, "Ring 1", metric="TotalEHP")
    assert result["errorCode"] == "item_measurement_incomplete"
    assert result["failureCodes"] == ["item_replacement_context_mismatch"]


def test_restore_failure_stops_public_search(pools):
    engine = ItemOracle({"Ring 1": raw_item()})
    engine.restore_fails = True
    result = itemopt.optimize_item(engine, "Ring 1", metric="TotalEHP")
    assert result["ok"] is False
    assert result["recoveryRequired"] is True
    assert result["rolledBack"] is False
    assert itemopt.optimize_item(engine, "Ring 1")["errorCode"] == "build_state_recovery_required"


def test_plan_replays_only_returned_items_and_restores_input(pools):
    engine = ItemOracle(
        {"Ring 1": raw_item(["+30% to Fire Resistance"])},
        {"+30% to Fire Resistance": 30, "+10 to maximum Life": 10},
    )
    before = engine.get_xml()
    result = itemopt.plan_gear(engine, slots=["Ring 1"], auto_base=False, dps_weight=0)
    assert result["ok"], result
    assert result["planReplayVerified"] is True
    assert result["projected"]["resistanceTargetMet"] is True
    assert len(result["plan"]) == 1
    assert engine.get_xml() == before
    assert result["stateHash"] == build_state_hash(before)


def test_skipped_autobase_cannot_affect_projected_character(pools, monkeypatch):
    engine = ItemOracle()
    engine.base_gains["Golden Visage"] = 50
    monkeypatch.setattr(itemopt, "_attr_bias", lambda *_: "int")
    monkeypatch.setattr(itemopt, "pick_ordinary_base", lambda *_args, **_kwargs: "Golden Visage")
    result = itemopt.plan_gear(engine, slots=["Helmet"], auto_base=True)
    assert result["ok"], result
    assert result["plan"] == []
    assert result["autoBased"] == []
    assert result["projected"]["TotalEHP"] == 100
    assert not engine.items


def test_plan_rejects_candidate_that_removes_another_equipped_slot(pools):
    engine = ItemOracle(
        {"Ring 1": raw_item(), "Helmet": raw_item(base="Fixture Base")},
        {"+30% to Fire Resistance": 30, "+10 to maximum Life": 10},
    )
    before = engine.get_xml()
    engine.drop_slot = "Helmet"
    result = itemopt.plan_gear(engine, slots=["Ring 1"], auto_base=False)
    assert result["plan"] == []
    assert result["rejectedIllegalCandidates"][0]["missingSlots"] == ["Helmet"]
    assert engine.get_xml() == before
