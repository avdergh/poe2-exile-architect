from __future__ import annotations

import json

import pytest

from server import paths
from server.compute import craftopt, equipment
from server.knowledge import item_legality, itemparse
from server.runtime import craft_receipts


ITEM = """Rarity: Rare
Source-aware Body Armour
Sacramental Robe
Item Level: 82
Sockets: S
Rune: Iron Rune
Implicits: 2
{rune}+20 to Armour
+1 to Level of all Skills
25% increased maximum Life
+100 to maximum Life
Corrupted"""


def test_equipment_write_requires_explicit_special_source_receipt():
    result = equipment.equip_item_verified(
        object(),
        raw=ITEM,
        slot="Body Armour",
        craft_receipt_ref=None,
    )

    assert result["errorCode"] == "special_source_provenance_required"


def test_incremental_socket_text_preserves_existing_affixes():
    raw = """Rarity: Rare
Existing Bow
Obliterator Bow
Item Level: 82
--------
Adds 10 to 229 Lightning Damage
+33 to Dexterity"""

    augmented = craftopt._augment_item_with_runes(
        raw,
        [("Test Rune", ["5% increased Attack Speed"])],
    )

    assert "Adds 10 to 229 Lightning Damage" in augmented
    assert "+33 to Dexterity" in augmented
    assert "Sockets: S" in augmented
    assert "Rune: Test Rune" in augmented
    assert "{rune}5% increased Attack Speed" in augmented


def test_incremental_socket_text_preserves_capacity_when_only_one_rune_is_beneficial():
    raw = """Rarity: Rare
Existing Bow
Obliterator Bow
Item Level: 82
Sockets: S S
--------
Adds 10 to 229 Lightning Damage"""

    augmented = craftopt._augment_item_with_runes(
        raw,
        [("Test Rune", ["5% increased Attack Speed"])],
        socket_capacity=2,
    )

    assert "Sockets: S S" in augmented
    assert augmented.count("Rune: Test Rune") == 1
    assert augmented.count("{rune}5% increased Attack Speed") == 1


def test_incremental_socket_optimizer_propagates_crafting_options_failure(monkeypatch):
    raw = """Rarity: Rare
Socket Target
Sacramental Robe
Item Level: 82
--------
+50 to maximum Life"""

    class UnavailableEngine:
        info = {}

        def __init__(self):
            self.restored = False
            self.equipped = True

        def get_build(self):
            return {
                "level": 90,
                "gear": {"Body Armour": {"base": "Sacramental Robe"}},
            }

        def get_xml(self):
            return "<PathOfBuilding2 />"

        def get_stats(self, _keys):
            return {"stats": {"TotalEHP": 100}}

        def inspect_item_replacement_context(self, expected_context=None):
            return {"ok": True, "contextStatus": "no_active_output"}

        def add_item(self, _raw, slot=None):
            self.equipped = True
            return {"ok": True, "slot": slot}

        def unequip_item(self, _slot):
            self.equipped = False
            return {"ok": True}

        def crafting_options(self, _slot):
            return {
                "ok": False,
                "errorCode": "crafting_options_unavailable",
                "error": "fixture provider unavailable",
            }

        def load_build_xml(self, _xml):
            self.restored = True

    engine = UnavailableEngine()
    monkeypatch.setattr(
        craftopt.completeness,
        "equipped_item_text",
        lambda _xml, _slot: raw if engine.equipped else None,
    )
    monkeypatch.setattr(
        craftopt.hard_legality,
        "augment_build_with_snapshot_gear",
        lambda build, _xml: build,
    )
    monkeypatch.setattr(
        craftopt.hard_legality,
        "audit_build",
        lambda _build: {"hardLegalityReady": True, "hardFailures": []},
    )

    result = craftopt.optimize_item_sockets(
        engine,
        slot="Body Armour",
        goals={"TotalEHP": 1.0},
        socket_count=1,
    )

    assert result["ok"] is False
    assert result["errorCode"] == "crafting_options_unavailable"
    assert engine.restored is True


def _prepared() -> dict[str, object]:
    return craft_receipts.prepare_receipt(
        ITEM,
        slot="Body Armour",
        item_level=82,
        perfect_essences=[
            {
                "line": "25% increased maximum Life",
                "name": "Perfect Essence of Life",
                "group": "PerfectEssenceLife",
                "affixType": "prefix",
                "requiredLevel": 1,
                "option": {
                    "name": "Perfect Essence of Life",
                    "special": True,
                    "modType": "prefix",
                },
            }
        ],
        runes=[
            {
                "name": "Iron Rune",
                "lines": ["+20 to Armour"],
                "option": {"name": "Iron Rune", "mods": ["+20 to Armour"]},
            }
        ],
        corruption={
            "line": "+1 to Level of all Skills",
            "option": {"line": "+1 to Level of all Skills"},
        },
        runtime_context={
            "dataVersion": "test-data",
            "pobCommit": "test-pob",
            "pobVersion": "test-version",
            "passiveTreeVersion": "test-tree",
            "engineSha256": "test-engine",
        },
    )


def test_parser_separates_runes_corruption_and_explicit_affixes():
    structure = itemparse.semantic_item_structure(ITEM)
    kinds = [entry["kind"] for entry in structure["effects"]]

    assert kinds.count("rune") == 1
    assert kinds.count("implicit") == 1
    assert kinds.count("explicit") == 2
    assert structure["corrupted"] is True
    assert structure["runeNames"] == ["Iron Rune"]


@pytest.mark.parametrize("side", ["receipt", "current", "both"])
@pytest.mark.parametrize("missing", [None, "unknown", ""])
def test_persisted_receipt_requires_known_model_on_both_sides(tmp_path, monkeypatch, side, missing):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    original = _prepared()
    previous = dict(original["runtimeVersion"])
    current = dict(previous)
    if side in {"receipt", "both"}:
        previous["pobCommit"] = missing
    if side in {"current", "both"}:
        current["pobCommit"] = missing
    receipt = craft_receipts.prepare_receipt(
        ITEM, slot="Body Armour", item_level=82, runtime_context=previous
    )
    assert craft_receipts.persist_receipt(receipt)["status"] == "recorded"
    # Exercise both explicit references and the implicit by-item lookup used
    # when equipment-wide limits collect each equipped Rune's quota group.
    for ref in (receipt["receiptRef"], None):
        resolved = craft_receipts.resolve_receipt(
            ITEM, slot="Body Armour", receipt_ref=ref, runtime_context=current
        )
        assert resolved == {"status": "rejected", "errorCode": "craft_receipt_version_mismatch"}


def test_upgrade_rejects_old_pinned_model_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    previous = {**_prepared()["runtimeVersion"], "pobCommit": "7d6f530cbdab20389ff8bc6ba97a37ac27f74e41"}
    receipt = craft_receipts.prepare_receipt(ITEM, slot="Body Armour", item_level=82, runtime_context=previous)
    assert craft_receipts.persist_receipt(receipt)["status"] == "recorded"
    current = {**previous, "pobCommit": "ce566eac45ea8a86477f513c7ee65a1ebe60014e"}
    assert craft_receipts.resolve_receipt(ITEM, runtime_context=current)["errorCode"] == "craft_receipt_version_mismatch"


def test_prepared_receipt_authorizes_exact_special_sources(monkeypatch):
    prepared = _prepared()
    seen_lines: list[str] = []

    def illegal_affixes(_base: str, lines: list[str]):
        seen_lines.extend(lines)
        return []

    monkeypatch.setattr(itemparse.db, "illegal_affixes", illegal_affixes)
    legality = item_legality.audit_item(
        ITEM,
        slot="Body Armour",
        prepared_receipt=prepared,
        require_special_provenance=True,
    )

    assert legality["ok"] is True
    assert legality["provenanceStatus"] == "verified"
    assert legality["specialSources"] == {
        "perfectEssenceCount": 1,
        "runeCount": 1,
        "corruptionVerified": True,
    }
    assert "25% increased maximum Life" not in seen_lines
    assert "+100 to maximum Life" in seen_lines


def test_special_sources_without_receipt_fail_generated_audit():
    legality = item_legality.audit_item(
        ITEM,
        slot="Body Armour",
        require_special_provenance=True,
    )

    assert legality["ok"] is False
    assert "special_source_provenance_required" in legality["issues"]


def test_hollow_rune_declaration_requires_provenance_and_is_not_counted_as_filled():
    hollow = """Rarity: Rare
Hollow Rune Item
Sacramental Robe
Item Level: 82
Sockets: S S
Rune: Iron Rune
--------
+100 to maximum Life"""

    legality = item_legality.audit_item(
        hollow,
        slot="Body Armour",
        require_special_provenance=True,
    )
    metadata = craftopt.completeness._parse_item_text(hollow, slot="Body Armour")

    assert legality["ok"] is False
    assert "special_source_provenance_required" in legality["issues"]
    assert legality["provenanceStatus"] == "unverified"
    assert metadata["runeSockets"] == 2
    assert metadata["verifiedRuneCount"] == 0

    unique_legality = item_legality.audit_item(
        hollow.replace("Rarity: Rare", "Rarity: Unique"),
        slot="Body Armour",
        require_special_provenance=True,
    )
    assert unique_legality["ok"] is False
    assert "special_source_provenance_required" in unique_legality["issues"]


def test_receipt_persists_raw_free_and_resolves_after_store_reopen(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    prepared = _prepared()

    recorded = craft_receipts.persist_receipt(prepared)
    resolved = craft_receipts.resolve_receipt(
        ITEM,
        receipt_ref=recorded["craftReceiptRef"],
        slot="Body Armour",
        runtime_context=prepared["runtimeVersion"],
    )

    assert recorded["status"] == "recorded"
    assert resolved["status"] == "verified"
    stored = json.dumps(resolved["receipt"], ensure_ascii=False)
    assert "25% increased maximum Life" not in stored
    assert "+1 to Level of all Skills" not in stored
    assert "Source-aware Body Armour" not in stored
    assert resolved["receipt"]["containsRawItem"] is False


def test_receipt_rejects_changed_roll_slot_version_and_forgery(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    prepared = _prepared()
    recorded = craft_receipts.persist_receipt(prepared)
    receipt_ref = recorded["craftReceiptRef"]

    changed = craft_receipts.resolve_receipt(
        ITEM.replace("+100 to maximum Life", "+101 to maximum Life"),
        receipt_ref=receipt_ref,
        slot="Body Armour",
        runtime_context=prepared["runtimeVersion"],
    )
    wrong_slot = craft_receipts.resolve_receipt(
        ITEM,
        receipt_ref=receipt_ref,
        slot="Helmet",
        runtime_context=prepared["runtimeVersion"],
    )
    wrong_version = craft_receipts.resolve_receipt(
        ITEM,
        receipt_ref=receipt_ref,
        slot="Body Armour",
        runtime_context={**prepared["runtimeVersion"], "dataVersion": "other"},
    )
    forged = craft_receipts.resolve_receipt(
        ITEM,
        receipt_ref="craft-legality:" + ("0" * 64),
        slot="Body Armour",
        runtime_context=prepared["runtimeVersion"],
    )

    assert changed["errorCode"] == "craft_receipt_item_mismatch"
    assert wrong_slot["errorCode"] == "craft_receipt_slot_mismatch"
    assert wrong_version["errorCode"] == "craft_receipt_version_mismatch"
    assert forged["errorCode"] == "craft_receipt_not_trusted"


def test_prepared_receipt_rejects_rune_count_and_corruption_marker_drift(monkeypatch):
    prepared = _prepared()
    monkeypatch.setattr(itemparse.db, "illegal_affixes", lambda _base, _lines: [])
    extra_rune = ITEM.replace(
        "Sockets: S",
        "Sockets: S S",
    ).replace(
        "{rune}+20 to Armour",
        "{rune}+20 to Armour\n{rune}+20 to Armour",
    )
    missing_corrupted = ITEM.replace("\nCorrupted", "")

    rune_legality = item_legality.audit_item(
        extra_rune,
        slot="Body Armour",
        prepared_receipt=prepared,
        require_special_provenance=True,
    )
    corruption_legality = item_legality.audit_item(
        missing_corrupted,
        slot="Body Armour",
        prepared_receipt=prepared,
        require_special_provenance=True,
    )

    assert rune_legality["ok"] is False
    assert "craft_receipt_item_mismatch" in rune_legality["issues"]
    assert corruption_legality["ok"] is False
    assert "craft_receipt_corruption_mismatch" in corruption_legality["issues"]


def test_socket_derivation_carries_exact_verified_non_rune_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(itemparse.db, "illegal_affixes", lambda *_: [])
    original = _prepared()
    assert craft_receipts.persist_receipt(original)["status"] == "recorded"
    changed = ITEM.replace("Iron Rune", "Other Rune").replace(
        "{rune}+20 to Armour", "{rune}+30 to Armour"
    )
    derived = craft_receipts.derive_socket_receipt(
        ITEM,
        changed,
        slot="Body Armour",
        item_level=82,
        runes=[
            {"name": "Other Rune", "lines": ["+30 to Armour"], "option": {"name": "Other Rune"}}
        ],
        runtime_context=original["runtimeVersion"],
    )
    assert derived["sources"]["perfectEssences"] == original["sources"]["perfectEssences"]
    assert derived["sources"]["corruption"] == original["sources"]["corruption"]
    assert derived["sources"]["runes"] != original["sources"]["runes"]
    assert derived["acceptedItemFingerprints"] != original["acceptedItemFingerprints"]
    assert derived["sourceDerivation"]["sourceReceiptRef"] == original["receiptRef"]
    assert craft_receipts.persist_receipt(derived)["status"] == "recorded"
    assert item_legality.audit_item(
        changed, prepared_receipt=derived, require_special_provenance=True
    )["ok"]
    stored = json.dumps(derived)
    assert "25% increased maximum Life" not in stored
    assert "+1 to Level of all Skills" not in stored


def test_socket_derivation_never_guesses_unrecorded_special_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    original = _prepared()  # Deliberately never persist the source receipt.
    derived = craft_receipts.derive_socket_receipt(
        ITEM,
        ITEM,
        slot="Body Armour",
        item_level=82,
        runes=[{"name": "Iron Rune", "lines": ["+20 to Armour"], "option": {"name": "Iron Rune"}}],
        runtime_context=original["runtimeVersion"],
    )
    assert derived["sources"]["perfectEssences"] == []
    assert derived["sources"]["corruption"] is None
    assert "sourceDerivation" not in derived
    assert (
        item_legality.audit_item(ITEM, prepared_receipt=derived, require_special_provenance=True)[
            "ok"
        ]
        is False
    )


@pytest.mark.parametrize(
    "change",
    ["affix", "implicit", "base", "level", "slot", "version", "unknown_version", "canonical"],
)
def test_socket_derivation_cannot_extend_original_item_or_version_authority(
    change, tmp_path, monkeypatch
):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(itemparse.db, "illegal_affixes", lambda *_: [])
    original = _prepared()
    craft_receipts.persist_receipt(original)
    changed = ITEM
    canonical = None
    slot = "Body Armour"
    context = dict(original["runtimeVersion"])
    if change == "affix":
        changed = ITEM.replace("25% increased maximum Life", "26% increased maximum Life")
    elif change == "implicit":
        changed = ITEM.replace("+1 to Level of all Skills", "+2 to Level of all Skills")
    elif change == "base":
        changed = ITEM.replace("Sacramental Robe", "Elegant Robe")
    elif change == "level":
        changed = ITEM.replace("Item Level: 82", "Item Level: 83")
    elif change == "slot":
        slot = "Helmet"
    elif change == "version":
        context["dataVersion"] = "different"
    elif change == "unknown_version":
        context["pobCommit"] = None
    else:
        canonical = ITEM.replace("+100 to maximum Life", "+101 to maximum Life")
    with pytest.raises(ValueError):
        craft_receipts.derive_socket_receipt(
            ITEM,
            changed,
            canonical_item_text=canonical,
            slot=slot,
            item_level=82,
            runes=[],
            runtime_context=context,
        )
