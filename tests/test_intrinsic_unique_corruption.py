from __future__ import annotations

import json

import pytest

from server.compute import completeness, equipment
from server.compute.state import build_state_hash
from server.knowledge import db, item_legality, itemparse
from server.knowledge.unique_variants import parse_unique_source
from server.runtime import craft_receipts


FLESH = """Rarity: Unique
Flesh Crucible
Diamond
Limited to: 1
10% less maximum Life
Chaos Inoculation
Corrupted"""


@pytest.mark.parametrize(
    "name,modifiers",
    [
        ("Flesh Crucible", ["10% less maximum Life", "Chaos Inoculation"]),
        ("Flesh Crucible", ["20% less maximum Life", "Mind Over Matter"]),
        ("Split Personality", ["Can Allocate Passive Skills from the Sorceress's starting point"]),
        ("Voices", ["Allocates 3 Sinister Jewel sockets"]),
    ],
)
def test_intrinsic_corruption_uses_complete_static_unique_source(name, modifiers):
    unique = db.get_unique(name, include_source=True)
    raw = "\n".join(["Rarity: Unique", name, unique["base"], *modifiers, "Corrupted"])
    source = parse_unique_source(unique["pobSource"], name=name, base=unique["base"])
    assert source.intrinsic_corrupted
    assert unique["variantSelection"]["intrinsicCorrupted"] is True
    audit = item_legality.audit_jewel_input(raw)["itemLegality"]
    assert audit["ok"], audit
    evidence = audit["intrinsicCorruption"]
    assert evidence["status"] == "verified_static_source"
    assert evidence["uniqueName"] == name
    assert evidence["itemFingerprint"] == itemparse.semantic_item_structure(raw)["itemFingerprint"]
    assert evidence["sourceFingerprint"].startswith("sha256:")
    assert "craftReceiptRef" not in audit and "provenanceStatus" not in audit
    assert "Corrupted" not in json.dumps(evidence)


@pytest.mark.parametrize(
    "raw,issue",
    [
        (FLESH.replace("\nCorrupted", ""), "unique_intrinsic_corruption_missing"),
        (FLESH.replace("10% less maximum Life\n", ""), "unique_modifier_mismatch"),
        (FLESH.replace("10% less", "9% less"), "unique_modifier_mismatch"),
        (FLESH + "\nMind Over Matter", "unique_modifier_mismatch"),
        (FLESH.replace("Chaos Inoculation", "10% less maximum Life"), "unique_modifier_mismatch"),
        (FLESH.replace("Diamond", "Sapphire"), "unique_item_base_mismatch"),
        (FLESH + "\n+1 to Level of all Skills (implicit)", "unique_modifier_mismatch"),
        (FLESH + "\nRune: Iron Rune\n{rune}+20 to Armour", "special_source_provenance_required"),
        (FLESH + "\nRune: Iron Rune", "special_source_provenance_required"),
    ],
)
def test_intrinsic_corruption_does_not_authorize_modified_items(raw, issue):
    audit = item_legality.audit_item(raw, require_special_provenance=True)
    assert not audit["ok"]
    assert issue in audit["issues"]


@pytest.mark.parametrize("source_change", ["missing", "remove_flag", "tag_flag"])
def test_intrinsic_authority_is_rederived_from_current_source(monkeypatch, source_change):
    unique = db.get_unique("Flesh Crucible", include_source=True)
    if source_change == "missing":
        unique.pop("pobSource")
    else:
        unique["pobSource"] = unique["pobSource"].replace(
            "\nCorrupted", "" if source_change == "remove_flag" else "\n{variant:5}Corrupted"
        )
    monkeypatch.setattr(db, "get_unique", lambda *a, **k: unique)
    audit = item_legality.audit_item(FLESH, require_special_provenance=True)
    assert not audit["ok"]
    assert "special_source_provenance_required" in audit["issues"]
    assert "intrinsicCorruption" not in audit


def test_intrinsic_item_still_rejects_explicit_invalid_crafting_receipt():
    result = item_legality.audit_jewel_input(FLESH, craft_receipt_ref="craft:not-real")
    assert not result["ok"]
    assert result["itemLegality"]["provenanceStatus"] == "rejected"


def test_writes_do_not_infer_receipts_for_added_special_sources(monkeypatch):
    raw = FLESH + "\n+1 to Level of all Skills (implicit)"
    provenance = {
        "itemFingerprint": itemparse.semantic_item_structure(raw)["itemFingerprint"],
        "sources": {
            "corruption": {
                "lineFingerprint": itemparse.line_fingerprint("+1 to Level of all Skills")
            }
        },
    }
    monkeypatch.setattr(
        craft_receipts,
        "resolve_receipt",
        lambda *a, **k: {"status": "verified", "receipt": provenance},
    )
    assert item_legality.audit_item(raw, require_special_provenance=True)["ok"]
    result = item_legality.audit_jewel_input(raw)
    assert not result["ok"]
    assert result["errorCode"] == "special_source_provenance_required"


@pytest.mark.parametrize("method", ["jewel", "item"])
def test_pob_flesh_crucible_public_write_and_shared_legality(fireball, monkeypatch, method):
    from server import main
    from server.judge import hard_legality

    monkeypatch.setattr(main, "get_engine", lambda: fireball)
    fireball.set_level(95)
    fireball.set_class("Mercenary", "Gemling Legionnaire")
    fireball.alloc_passive(61834, path_attribute="Intelligence")
    before = fireball.get_build()
    if method == "jewel":
        result = main.equip_jewel(
            FLESH, socket=61834, expected_state_hash=build_state_hash(fireball.get_xml())
        )
    else:
        result = main.equip_item(FLESH, slot="Jewel 61834")
    assert result["ok"] and result["readbackVerified"], result
    assert result["itemLegality"]["intrinsicCorruption"]["status"] == "verified_static_source"
    after = fireball.get_build()
    assert after["normalPassivePointsUsed"] == before["normalPassivePointsUsed"]
    assert fireball.get_stats(["Life"])["stats"]["Life"] == 1  # Native Chaos Inoculation.
    actual = completeness.equipped_item_text_from_engine(fireball, "Jewel 61834")
    assert equipment._same_unique_identity(FLESH, actual)
    assert item_legality.audit_item(actual, require_special_provenance=True)["ok"]
    metadata = completeness._parse_item_text(actual, slot="Jewel 61834")
    assert metadata["affixLegality"]["ok"]
    assert metadata["affixLegality"].get("provenanceStatus") != "unverified"
    audit = hard_legality.audit_build(
        hard_legality.augment_build_with_snapshot_gear(after, fireball.get_xml())
    )
    assert "special_source_provenance_required" not in json.dumps(audit)


@pytest.mark.parametrize("change", ["strip_flag", "switch_variant", "add_rune"])
def test_unique_readback_normalization_cannot_change_special_structure(change):
    actual = (
        FLESH.replace("\nCorrupted", "")
        if change == "strip_flag"
        else FLESH.replace("Chaos Inoculation", "Mind Over Matter")
        if change == "switch_variant"
        else FLESH + "\nRune: Iron Rune"
    )
    assert not equipment._same_unique_identity(FLESH, actual)


def test_pob_readback_missing_intrinsic_corruption_rolls_back(fireball, monkeypatch):
    fireball.set_level(95)
    fireball.alloc_passive(61834, path_attribute="Intelligence")
    snapshot = fireball.get_xml()
    reader = completeness.equipped_item_text

    def changed_readback(*args, **kwargs):
        raw = reader(*args, **kwargs)
        return raw.replace("\nCorrupted", "") if raw else raw

    monkeypatch.setattr(completeness, "equipped_item_text", changed_readback)
    result = equipment.equip_jewel_verified(fireball, raw=FLESH, socket=61834)
    assert not result["ok"] and result["rolledBack"] and not result["recoveryRequired"], result
    assert build_state_hash(fireball.get_xml()) == build_state_hash(snapshot)
