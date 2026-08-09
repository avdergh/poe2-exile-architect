from server.compute import itemopt


class _SlotRegressionEngine:
    def __init__(self) -> None:
        self.changed = False
        self.restored = False
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
        return "<PathOfBuilding><Build/></PathOfBuilding>"

    def get_stats(self, keys):
        return {"stats": {key: 100.0 for key in keys}}

    def get_defenses(self):
        return {"resistMissing": {}}

    def eval_items(self, slot, items, keys):
        del slot
        return {
            "results": [
                {key: (200.0 if "increased Damage" in raw else 100.0) for key in keys}
                for raw in items
            ]
        }

    def add_item(self, raw, slot=None):
        del raw, slot
        self.changed = True
        return {"ok": True}

    def load_build_xml(self, xml):
        del xml
        self.changed = False
        self.restored = True


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

    result = itemopt.rank_upgrades(object(), slots=["Amulet"], top=1)

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
