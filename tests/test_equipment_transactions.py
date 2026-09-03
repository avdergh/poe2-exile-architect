from __future__ import annotations

from contextlib import nullcontext
import xml.etree.ElementTree as ET

from server.compute import equipment


PLAIN = "Rarity: Rare\nPlain Ring\nSapphire Ring\nItem Level: 80\n+40 to maximum Mana"


class _Engine:
    def __init__(self, *, rollback_fails: bool = False) -> None:
        self.xml = (
            '<PathOfBuilding><Items activeItemSet="1">'
            '<ItemSet id="1" /></Items></PathOfBuilding>'
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
        item.text = (
            raw
            + "\nSockets: S\nRune: Iron Rune\nImplicits: 1\n{rune}+20 to Armour"
        )
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
