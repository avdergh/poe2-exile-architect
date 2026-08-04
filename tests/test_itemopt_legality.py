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
