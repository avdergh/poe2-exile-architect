from __future__ import annotations

from server.compute import completeness
from server.judge import rules


class _CompletenessEngine:
    def __init__(self, build, sockets=None, xml="<PathOfBuilding2 />"):
        self._build = build
        self._sockets = sockets or []
        self._xml = xml

    def get_build(self):
        return self._build

    def list_jewel_sockets(self):
        return {"sockets": self._sockets}

    def get_xml(self):
        return self._xml


def test_completeness_reports_scaffold_and_missing_real_build_systems():
    engine = _CompletenessEngine(
        {
            "level": 58,
            "gear": {
                "Body Armour": {
                    "name": "Scaffold Body Armour",
                    "base": "Warlord Cuirass",
                    "rarity": "RARE",
                    "levelRequirement": 80,
                    "runeSockets": 0,
                    "isScaffold": True,
                },
                "Belt": {
                    "name": "Optimized Belt",
                    "base": "Stalking Belt",
                    "rarity": "RARE",
                    "itemLevel": 58,
                    "levelRequirement": 50,
                    "charmSlots": 1,
                },
                "Flask 1": {"base": "Transcendent Life Flask", "rarity": "NORMAL"},
            },
        },
        sockets=[{"socket": 1, "allocated": True, "filled": False}],
    )

    report = completeness.inspect_build_completeness(engine)

    assert report["status"] == "needs_attention"
    assert report["hardFailures"] == ["equipped_item_level_requirement_unmet"]
    assert report["missingItemLevelSlots"] == ["Body Armour"]
    assert report["scaffoldSlots"] == ["Body Armour"]
    assert "flask_loadout_incomplete" in report["advisories"]
    assert "available_charm_slots_unfilled" in report["advisories"]
    assert "allocated_passive_jewel_socket_empty" in report["advisories"]


def test_completeness_accepts_filled_stage_loadout_without_forcing_jewel_socket():
    engine = _CompletenessEngine(
        {
            "level": 58,
            "gear": {
                "Weapon 1": {
                    "name": "Optimized Weapon 1",
                    "rarity": "RARE",
                    "itemLevel": 58,
                    "levelRequirement": 50,
                    "runeSockets": 1,
                    "runes": ["Iron Rune"],
                },
                "Belt": {
                    "name": "Optimized Belt",
                    "rarity": "RARE",
                    "itemLevel": 58,
                    "levelRequirement": 50,
                    "charmSlots": 1,
                },
                "Flask 1": {"base": "Transcendent Life Flask", "rarity": "NORMAL"},
                "Flask 2": {"base": "Transcendent Mana Flask", "rarity": "NORMAL"},
                "Charm 1": {"base": "Grounding Charm", "rarity": "NORMAL"},
            },
        }
    )

    report = completeness.inspect_build_completeness(engine)

    assert not report["hardFailures"]
    assert "flask_loadout_incomplete" not in report["advisories"]
    assert "available_charm_slots_unfilled" not in report["advisories"]
    assert report["passiveJewels"]["allocatedSockets"] == 0


def test_equipped_item_requirement_check_blocks_overlevel_base():
    result = rules.check_equipped_item_requirements(
        {
            "level": 58,
            "gear": {
                "Helmet": {"levelRequirement": 80},
                "Ring 1": {"levelRequirement": 40},
            },
        }
    )

    assert result["ok"] is False
    assert result["underlevelledSlots"] == [
        {"slot": "Helmet", "requiredLevel": 80, "characterLevel": 58}
    ]


def test_equipped_item_metadata_reads_active_item_set_without_returning_raw_text():
    xml = """<PathOfBuilding2><Items activeItemSet="1">
    <Item id="1">Rarity: RARE\nOptimized Belt\nStalking Belt\nCharm Slots: 1\nItem Level: 58\nLevelReq: 50</Item>
    <Item id="2">Rarity: RARE\nOld Belt\nFine Belt\nItem Level: 82\nLevelReq: 62</Item>
    <ItemSet id="1"><Slot name="Belt" itemId="1" /></ItemSet>
    <ItemSet id="2"><Slot name="Belt" itemId="2" /></ItemSet>
    </Items></PathOfBuilding2>"""

    gear = completeness.equipped_item_metadata(xml)

    assert gear == {
        "Belt": {
            "name": "Optimized Belt",
            "base": "Stalking Belt",
            "rarity": "RARE",
            "itemLevel": 58,
            "levelRequirement": 50,
            "runeSockets": 0,
            "runes": [],
            "charmSlots": 1,
            "isScaffold": False,
        }
    }


def test_artifact_blockers_reject_scaffold_and_missing_item_level():
    xml = """<PathOfBuilding2><Items activeItemSet="1">
    <Item id="1">Rarity: RARE\nScaffold Helmet\nIron Crown\nLevelReq: 10</Item>
    <ItemSet id="1"><Slot name="Helmet" itemId="1" /></ItemSet>
    </Items></PathOfBuilding2>"""

    assert completeness.artifact_blockers(xml) == [
        "final_artifact_contains_scaffold_gear",
        "final_artifact_item_level_missing",
    ]
