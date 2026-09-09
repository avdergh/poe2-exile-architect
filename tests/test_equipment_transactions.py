from __future__ import annotations

from contextlib import contextmanager, nullcontext
import xml.etree.ElementTree as ET

import pytest

from server.compute import equipment
from server.compute import completeness
from server.compute import itemopt
from server.compute.state import build_state_hash

JEWEL = "Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 80\n15% increased Mana Regeneration Rate"


PLAIN = "Rarity: Rare\nPlain Ring\nSapphire Ring\nItem Level: 80\n+40 to maximum Mana"


class _Engine:
    def __init__(self, *, rollback_fails: bool = False) -> None:
        self.xml = (
            '<PathOfBuilding><Items activeItemSet="1"><ItemSet id="1" /></Items></PathOfBuilding>'
        )
        self.initial = self.xml
        self.add_calls = 0
        self.rollback_fails = rollback_fails

    def transaction_lock(self):
        return nullcontext()

    def get_xml(self):
        return self.xml

    def load_build_xml(self, xml, name=""):
        if self.rollback_fails and "rollback" in name:
            raise RuntimeError("rollback failed")
        self.xml = xml
        return {"ok": True}

    def add_item(self, raw, slot=None):
        self.add_calls += 1
        if self.add_calls == 2:
            raise RuntimeError("second add failed")
        root = ET.fromstring(self.xml)
        items = root.find("Items")
        item = ET.SubElement(items, "Item", {"id": str(self.add_calls)})
        item.text = raw + "\nSockets: S\nRune: Iron Rune\nImplicits: 1\n{rune}+20 to Armour"
        item_set = items.find("ItemSet")
        for old in list(item_set.findall("Slot")):
            item_set.remove(old)
        ET.SubElement(item_set, "Slot", {"name": slot or "Ring 1", "itemId": item.get("id")})
        self.xml = ET.tostring(root, encoding="unicode")
        return {"ok": True, "slot": slot or "Ring 1"}

    def unequip_item(self, slot):
        root = ET.fromstring(self.xml)
        item_set = root.find("./Items/ItemSet")
        for old in list(item_set.findall("Slot")):
            if old.get("name") == slot:
                item_set.remove(old)
        self.xml = ET.tostring(root, encoding="unicode")
        return {"ok": True}


def test_clean_slot_retry_exception_restores_original_state():
    engine = _Engine()

    result = equipment.equip_item_verified(
        engine,
        raw=PLAIN,
        slot="Ring 1",
        craft_receipt_ref=None,
    )

    assert result["ok"] is False
    assert result["rolledBack"] is True
    assert result["recoveryRequired"] is False
    assert engine.get_xml() == engine.initial


def test_equipment_rollback_failure_is_reported_without_exception():
    engine = _Engine(rollback_fails=True)

    result = equipment.equip_item_verified(
        engine,
        raw=PLAIN,
        slot="Ring 1",
        craft_receipt_ref=None,
    )

    assert result["ok"] is False
    assert result["rolledBack"] is False
    assert result["recoveryRequired"] is True


class _JewelEngine(_Engine):
    def __init__(self, *, mismatch=False, rollback_fails=False):
        super().__init__(rollback_fails=rollback_fails)
        self.xml = (
            '<PathOfBuilding><Tree activeSpec="2"><Spec id="1" nodes="12"><Sockets>'
            '<Socket nodeId="12" itemId="1"/></Sockets></Spec>'
            '<Spec id="2" nodes="12"><Sockets/></Spec></Tree><Items activeItemSet="1">'
            '<Item id="1">' + JEWEL + '</Item><ItemSet id="1">'
            '<Slot name="Jewel 12" itemId="1"/></ItemSet></Items></PathOfBuilding>'
        )
        self.initial = self.xml
        self.mismatch = mismatch

    def list_jewel_sockets(self):
        return {"sockets": [{"socket": 12, "allocated": True}, {"socket": 13, "allocated": False}]}

    def equip_jewel(self, raw, socket=None):
        root = ET.fromstring(self.xml)
        item = ET.SubElement(root.find("Items"), "Item", {"id": "2"})
        item.text = raw.replace("15%", "14%") if self.mismatch else raw
        ET.SubElement(
            root.find("./Tree/Spec[@id='2']/Sockets"),
            "Socket",
            {"nodeId": str(socket), "itemId": "2"},
        )
        self.xml = ET.tostring(root, encoding="unicode")
        return {"ok": True, "socket": socket}


def test_jewel_fill_verifies_active_spec_and_never_picks_an_implicit_socket():
    engine = _JewelEngine()
    original_hash = build_state_hash(engine.get_xml())
    for socket, error in [
        (None, "explicit_jewel_socket_required"),
        (13, "jewel_socket_not_allocated"),
    ]:
        result = equipment.equip_jewel_verified(engine, raw=JEWEL, socket=socket)
        assert result["errorCode"] == error
        assert build_state_hash(engine.get_xml()) == original_hash
    result = equipment.equip_jewel_verified(
        engine, raw=JEWEL, socket=12, expected_state_hash=original_hash
    )
    assert result["ok"] and result["readbackVerified"]
    assert result["outputStateHash"] == build_state_hash(engine.get_xml())


def test_jewel_wrong_active_item_cannot_borrow_inactive_spec_or_itemset_readback():
    engine = _JewelEngine(mismatch=True)
    result = equipment.equip_jewel_verified(engine, raw=JEWEL, socket=12)
    assert result["ok"] is False and result["rolledBack"] is True
    assert engine.get_xml() == engine.initial


def test_jewel_restore_failure_blocks_all_equipment_writes():
    engine = _JewelEngine(mismatch=True, rollback_fails=True)
    result = equipment.equip_jewel_verified(engine, raw=JEWEL, socket=12)
    assert result["recoveryRequired"] and not result["rolledBack"]
    assert equipment.equip_jewel_verified(engine, raw=JEWEL, socket=12)["recoveryRequired"]
    assert equipment.equip_item_verified(engine, raw=PLAIN, slot="Ring 1", craft_receipt_ref=None)[
        "recoveryRequired"
    ]


def test_completeness_uses_active_spec_and_observed_free_socket_without_inactive_items():
    root = ET.fromstring(_JewelEngine().xml)
    active = root.find("./Tree/Spec[@id='2']")
    active.set("nodes", "")  # free item-granted sockets are omitted by pinned PoB Save
    ET.SubElement(active.find("Sockets"), "Socket", {"nodeId": "12", "itemId": "1"})
    xml = ET.tostring(root, encoding="unicode")
    assert "Jewel 12" not in completeness.equipped_item_metadata(xml)
    gear = completeness.equipped_item_metadata(xml, allocated_jewel_socket_ids=[12])
    assert gear["Jewel 12"]["affixLegality"]["ok"]
    engine = _JewelEngine()
    engine.xml = xml
    assert completeness.equipped_item_text_from_engine(engine, "Jewel 12") == JEWEL
    root.find("./Tree/Spec[@id='2']/Sockets/Socket").set("itemId", "999")
    xml = ET.tostring(root, encoding="unicode")
    gear = completeness.equipped_item_metadata(xml, allocated_jewel_socket_ids=[12])
    assert gear["Passive Jewel State"]["affixLegality"]["ok"] is False


@pytest.mark.parametrize("operation", ["probe", "apply"])
def test_additional_jewel_work_rechecks_recovery_after_waiting_for_lock(operation):
    class RecoveryDuringLock(_Engine):
        @contextmanager
        def transaction_lock(self):
            setattr(self, equipment._RECOVERY_ATTRIBUTE, True)
            yield

        def get_xml(self):
            raise AssertionError("must not probe a failed state after acquiring the lock")

    engine = RecoveryDuringLock()
    result = (
        itemopt.evaluate_next_jewel_socket(engine, raw=JEWEL, goals={"Mana": 1.0})
        if operation == "probe"
        else itemopt.apply_next_jewel_socket_decision(
            engine, decision_ref="jewel-decision:example", expected_state_hash="sha256:example"
        )
    )
    assert result["recoveryRequired"] and result["errorCode"] == "build_state_recovery_required"


def test_jewel_special_source_requires_explicit_receipt_and_shared_historic_limit():
    engine = _JewelEngine()
    result = equipment.equip_jewel_verified(engine, raw=JEWEL + "\nCorrupted", socket=12)
    assert result["errorCode"] == "special_source_provenance_required"
    assert engine.get_xml() == engine.initial
    gear = {
        f"Jewel {index}": {"name": name, "rarity": "Unique", "affixLegality": {"ok": True}}
        for index, name in enumerate(["Heroic Tragedy", "Undying Hate"], start=1)
    }
    completeness._audit_jewel_limits(gear)
    assert all(
        item["affixLegality"]["jewelLimit"] == {"group": "Historic", "limit": 1, "equippedCount": 2}
        for item in gear.values()
    )
