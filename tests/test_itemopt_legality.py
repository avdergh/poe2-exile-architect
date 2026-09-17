from server.compute import itemopt
from server.knowledge import db, itemparse
from html import escape
from types import SimpleNamespace


class _SlotRegressionEngine:
    def __init__(self) -> None:
        self.changed = False
        self.restored = False
        self.item = None
        self.before_gear = {
            slot: {"base": f"{slot} Base"}
            for slot in (
                "Weapon 1",
                "Weapon 2",
                "Helmet",
                "Body Armour",
                "Gloves",
                "Boots",
                "Belt",
                "Amulet",
                "Ring 1",
                "Ring 2",
            )
        }
        self.before_gear['Amulet']['base'] = 'Gold Amulet'

    def get_build(self):
        gear = dict(self.before_gear)
        if self.changed:
            gear.pop("Ring 2")
        return {
            "class": "Monk",
            "ascendancy": "Martial Artist",
            "level": 85,
            "gear": gear,
        }

    def get_xml(self):
        if self.changed and self.item:
            return (
                '<PathOfBuilding><Build/><Items activeItemSet="1"><Item id="1">'
                + escape(self.item)
                + '</Item><ItemSet id="1"><Slot name="Amulet" itemId="1"/></ItemSet></Items></PathOfBuilding>'
            )
        return "<PathOfBuilding><Build/></PathOfBuilding>"

    def get_stats(self, keys):
        return {"stats": {key: 100.0 for key in keys}}

    def get_defenses(self):
        return {
            "resistMissing": {},
            "resistances": {"fire": 0, "cold": 0, "lightning": 0, "chaos": 0},
        }

    def eval_items(self, slot, items, keys, *, replacement_context=False):
        del slot
        return {
            "contextVersion": "item_replacement_context_v1",
            "rolledBack": True,
            "results": [
                {key: (200.0 if "increased Damage" in raw else 100.0) for key in keys}
                for raw in items
            ],
        }

    def add_item(self, raw, slot=None):
        del slot
        self.item = raw
        self.changed = True
        return {"ok": True}

    def unequip_item(self, slot):
        self.changed = False
        self.item = None
        return {"ok": True}

    def inspect_item_replacement_context(self, expected_context=None):
        return {"ok": True, "contextStatus": "no_active_output"}

    def load_build_xml(self, xml):
        del xml
        self.changed = False
        self.restored = True
        self.item = None


def test_optimize_item_rejects_a_candidate_that_drops_an_equipped_slot(monkeypatch):
    engine = _SlotRegressionEngine()
    monkeypatch.setattr(
        itemopt.db,
        "affix_pool",
        lambda base, ilvl: {
            "prefixes": [
                {
                    "group": "fixture_damage",
                    "text": "10% increased Damage",
                    "tiers": 1,
                    "required_level": 1,
                }
            ],
            "suffixes": [],
        },
    )
    monkeypatch.setattr(
        itemopt,
        "_generated_item_legality",
        lambda _raw: {"ok": True, "issues": []},
    )
    monkeypatch.setattr(
        itemopt.hard_legality,
        "audit_build",
        lambda _build: {
            "hardLegalityReady": True,
            "hardFailures": [],
        },
    )

    result = itemopt.optimize_item(
        engine,
        "Amulet",
        metric="TotalDPS",
        keep_resists_capped=False,
    )

    assert result["ok"] is False
    assert result["errorCode"] == "whole_build_legality_check_failed"
    assert result["rejectionReasons"] == [{"code": "equipped_slot_regression", "slots": ["Ring 2"]}]
    assert result["slotRegression"] == {
        "beforeCount": 10,
        "afterCount": 9,
        "missingSlots": ["Ring 2"],
    }
    assert engine.restored is True
    assert engine.changed is False


def test_rank_upgrades_keeps_rejected_illegal_candidates_in_the_response(monkeypatch):
    monkeypatch.setattr(
        itemopt,
        "optimize_item",
        lambda *_args, **_kwargs: {
            "ok": False,
            "errorCode": "whole_build_legality_check_failed",
            "error": "candidate rejected",
            "rejectionReasons": [{"code": "attribute_requirement_unmet"}],
            "wholeBuildLegality": {
                "hardLegalityReady": False,
                "hardFailures": ["attribute_requirement_unmet"],
            },
            "slotRegression": {
                "beforeCount": 10,
                "afterCount": 10,
                "missingSlots": [],
            },
        },
    )

    result = itemopt.rank_upgrades(
        SimpleNamespace(get_xml=lambda: "<PathOfBuilding/>"), slots=["Amulet"], top=1
    )

    assert result["ranked"] == []
    assert result["rejected"] == [
        {
            "slot": "Amulet",
            "errorCode": "whole_build_legality_check_failed",
            "rejectionReasons": [{"code": "attribute_requirement_unmet"}],
            "wholeBuildLegality": {
                "hardLegalityReady": False,
                "hardFailures": ["attribute_requirement_unmet"],
            },
            "slotRegression": {
                "beforeCount": 10,
                "afterCount": 10,
                "missingSlots": [],
            },
        }
    ]


class _JewelProbeEngine:
    """Minimal engine double for itemopt.evaluate_jewel_socket branches."""

    def __init__(self, results):
        self.results = results
        self.eval_calls = []

    def get_stats(self, keys):
        return {"stats": {key: 100.0 for key in keys}}

    def eval_items(self, slot, items, keys):
        self.eval_calls.append((slot, items, keys))
        return {"results": self.results}


def test_evaluate_jewel_socket_reports_deltas_and_build_restored_note():
    engine = _JewelProbeEngine([{"TotalDPS": 140.0, "TotalEHP": 110.0, "Life": 120.0}])
    out = itemopt.evaluate_jewel_socket(
        engine,
        socket=2491,
        raw="Rarity: Unique\nTest Time-Lost Emerald\nTime-Lost Emerald\nItem Level: 84\nRadius: Large\nSmall Passive Skills in Radius also grant 10% increased Spell Damage",
        keys=["TotalDPS", "TotalEHP", "Life", "EnergyShield"],
    )
    assert out["ok"] is True
    assert out["socket"] == 2491
    assert out["deltas"] == {"TotalDPS": 40.0, "TotalEHP": 10.0, "Life": 20.0}
    assert out["baseStats"]["TotalDPS"] == 100.0
    assert out["candidateStats"]["TotalDPS"] == 140.0
    assert engine.eval_calls == [
        (
            "Jewel 2491",
            [
                "Rarity: Unique\nTest Time-Lost Emerald\nTime-Lost Emerald\nItem Level: 84\nRadius: Large\nSmall Passive Skills in Radius also grant 10% increased Spell Damage"
            ],
            ["TotalDPS", "TotalEHP", "Life", "EnergyShield"],
        )
    ]
    assert "restored" in out["note"]


def test_evaluate_jewel_socket_skips_non_numeric_keys_in_deltas():
    engine = _JewelProbeEngine([{"TotalDPS": 150.0, "HitChance": "low"}])
    out = itemopt.evaluate_jewel_socket(
        engine,
        socket=3367,
        raw="Rarity: Magic\nTest Emerald\nEmerald\nItem Level: 84\n10% increased Spell Damage",
        keys=["TotalDPS", "HitChance"],
    )
    assert out["ok"] is True
    assert out["deltas"] == {"TotalDPS": 50.0}
    assert "HitChance" not in out["deltas"]


def test_evaluate_jewel_socket_reports_failed_candidate():
    engine = _JewelProbeEngine([False])
    out = itemopt.evaluate_jewel_socket(engine, socket=2491, raw="garbage")
    assert out["ok"] is False
    assert "failed to parse or equip" in out["error"]


def test_evaluate_jewel_socket_reports_empty_results():
    engine = _JewelProbeEngine([])
    out = itemopt.evaluate_jewel_socket(engine, socket=2491, raw="anything")
    assert out["ok"] is False
    assert "failed to parse or equip" in out["error"]


def test_resistance_candidates_saturate_at_stage_targets():
    mods = [
        {"text": "+44% to Fire Resistance"},
        {"text": "+44% to Cold Resistance"},
        {"text": "+16% to all Elemental Resistances"},
        {"text": "+27% to Chaos Resistance"},
        {"text": "16% increased Attack Speed"},
    ]

    remaining = itemopt._without_satisfied_resistances(
        mods,
        current={"fire": 60, "cold": 40, "lightning": 60, "chaos": 30},
        elemental_target=60,
        chaos_target=30,
    )

    texts = {item["text"] for item in remaining}
    assert "+44% to Fire Resistance" not in texts
    assert "+27% to Chaos Resistance" not in texts
    assert "+44% to Cold Resistance" in texts
    assert "+16% to all Elemental Resistances" in texts
    assert "16% increased Attack Speed" in texts

    explicit_cap = itemopt._without_satisfied_resistances(
        mods,
        current={"fire": 60, "cold": 60, "lightning": 60, "chaos": 30},
        elemental_target=75,
        chaos_target=75,
    )
    assert {item["text"] for item in explicit_cap} == {item["text"] for item in mods}


def test_flask_affix_pool_includes_subtype_and_domain_wide_mods():
    pool = db.affix_pool("Ultimate Mana Flask", ilvl=82)

    prefix_groups = {item["group"] for item in pool["prefixes"]}
    suffix_groups = {item["group"] for item in pool["suffixes"]}
    texts = {item["text"] for item in pool["prefixes"] + pool["suffixes"]}
    assert {"FlaskRecoveryAmount", "FlaskRecoverySpeed"} <= prefix_groups
    assert {"FlaskGainCharge", "FlaskChargesUsed"} <= suffix_groups
    assert not any("Low Life" in text for text in texts)


def test_flask_domain_empty_default_and_subtype_tags_share_one_applicability_rule():
    assert db.mod_tags_match_base("Ultimate Mana Flask", [], mod_domain="flask") is True
    assert db.mod_tags_match_base("Ultimate Mana Flask", ["default"], mod_domain="flask") is True
    assert db.mod_tags_match_base("Ultimate Mana Flask", ["mana_flask"], mod_domain="flask") is True
    assert (
        db.mod_tags_match_base("Ultimate Mana Flask", ["life_flask"], mod_domain="flask") is False
    )
    assert db.mod_tags_match_base("Ultimate Mana Flask", ["default"], mod_domain="item") is False


def test_magic_flask_single_line_header_round_trips_and_rare_is_rejected():
    body = (
        "Ultimate Mana Flask\nItem Level: 82\n--------\n"
        "70% increased Recovery rate\nGains 0.25 Charges per Second"
    )
    magic = itemparse.parse_item("Rarity: Magic\n" + body)
    rare = itemparse.audit_item_legality("Rarity: Rare\nOptimized Flask\n" + body)

    assert magic["name"] == "Ultimate Mana Flask"
    assert magic["base"] == "Ultimate Mana Flask"
    assert magic["prefixes"] == 1
    assert magic["suffixes"] == 1
    assert rare["ok"] is False
    assert "rarity_not_allowed_for_base_domain" in rare["issues"]


def test_optimize_item_routes_flask_bases_to_specialized_tool():
    class Engine:
        def get_xml(self):
            return "<PathOfBuilding/>"

        def get_build(self):
            return {"gear": {}}

    result = itemopt.optimize_item(Engine(), "Flask 2", base="Ultimate Mana Flask")

    assert result["errorCode"] == "use_optimize_flask"


def test_utility_flask_charm_is_not_routed_or_accepted_as_recovery_flask():
    class Engine:
        def get_xml(self):
            return "<PathOfBuilding/>"

        def get_build(self):
            return {"gear": {}}

    routed = itemopt.optimize_item(Engine(), "Charm 1", base="Grounding Charm")
    optimized = itemopt.optimize_flask(Engine(), "Flask 1", base="Grounding Charm")

    assert routed["errorCode"] == "unsupported_flask_item_class"
    assert optimized["errorCode"] == "invalid_flask_base"
