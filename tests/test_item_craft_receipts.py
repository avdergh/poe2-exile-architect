from __future__ import annotations

import json

from server import paths
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
