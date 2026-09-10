from __future__ import annotations

import pytest

from server.knowledge import db, itemparse
from server.knowledge.unique_variants import parse_unique_source
from server.compute import equipment


def _item(name: str, modifiers: list[str]) -> str:
    unique = db.get_unique(name)
    assert unique
    return "\n".join(["Rarity: Unique", name, unique["base"], "--------", *modifiers])


def _mageblood(*legacies: str, effect: int = 40, charms: int = 3) -> str:
    return _item(
        "Mageblood",
        [
            "Implicits: 2",
            f"Has {charms} Charm Slot",
            "20% of Flask Recovery applied Instantly",
            *(f"Legacy of {legacy}" for legacy in legacies),
            f"All Mage's Legacies have {effect}% increased effect per duplicate Mage's Legacy you have",
        ],
    )


def test_public_unique_contract_preserves_choices_without_exposing_source():
    mageblood = db.get_unique("Mageblood")
    assert "pobSource" not in mageblood
    contract = mageblood["variantSelection"]
    assert contract["requiredSelections"] == 4
    assert contract["allowDuplicateVariants"] is True
    assert len(contract["options"]) == 14
    assert contract["options"][2] == {"id": 3, "name": "Legacy of Bismuth"}
    assert (
        len([entry for entry in contract["modifierTemplates"] if entry["kind"] == "implicit"]) == 2
    )
    assert db.get_unique("Rite of Passage")["variantSelection"]["requiredSelections"] == 1


@pytest.mark.parametrize(
    "legacies",
    [
        ("Bismuth", "Amethyst", "Quicksilver", "Silver"),
        ("Bismuth", "Bismuth", "Bismuth", "Bismuth"),
    ],
)
def test_mageblood_accepts_four_complete_variants_including_duplicates(legacies):
    result = itemparse.audit_item_legality(_mageblood(*legacies))
    assert result["ok"], result


@pytest.mark.parametrize(
    "raw",
    [
        _mageblood("Bismuth", "Amethyst", "Silver"),
        _mageblood("Bismuth", "Amethyst", "Silver", "Quicksilver", "Gold"),
        _mageblood("Bismuth", "Amethyst", "Silver", "Unknown"),
        _mageblood("Bismuth", "Amethyst", "Silver", "Quicksilver", effect=51),
        _mageblood("Bismuth", "Amethyst", "Silver", "Quicksilver", charms=4),
        _mageblood("Bismuth", "Amethyst", "Silver", "Quicksilver")
        + "\n+9999 to maximum Mana (implicit)",
    ],
)
def test_mageblood_rejects_illegal_choice_counts_modifiers_and_rolls(raw):
    result = itemparse.audit_item_legality(raw)
    assert result["ok"] is False
    assert "unique_modifier_mismatch" in result["issues"]


def test_rite_accepts_one_spirit_and_rejects_flattened_all_choices():
    raw = _item(
        "Rite of Passage",
        [
            "Implicits: 1",
            "Used when you kill a Rare or Unique enemy",
            "Possessed by Spirit Of The Wolf for 15 seconds on use",
        ],
    )
    assert itemparse.audit_item_legality(raw)["ok"]
    assert not itemparse.audit_item_legality(
        raw + "\nPossessed by Spirit Of The Owl for 15 seconds on use"
    )["ok"]
    unique = db.get_unique("Rite of Passage")
    assert not itemparse.audit_item_legality("Rarity: Unique\n" + unique["text"])["ok"]


def test_tagged_pob_choices_use_selected_variant_and_reject_caller_capacity_override():
    unique = db.get_unique("Mageblood", include_source=True)
    raw = "Rarity: Unique\n" + unique["pobSource"]
    assert itemparse.audit_item_legality(raw)["ok"]
    assert itemparse.audit_item_legality(
        raw.replace("Selected Alt Variant: 2", "Selected Alt Variant: 1")
    )["ok"]
    for invalid in [
        raw.replace("Selected Variant: 1\n", "Selected Variant: 99\n"),
        raw + "\nHas Alt Variant Four: true\nSelected Alt Variant Four: 5",
        raw.replace("Allow Duplicate Variants: true", "Allow Duplicate Variants: false"),
    ]:
        result = itemparse.audit_item_legality(invalid)
        assert "unique_variant_selection_invalid" in result["issues"]


def test_complete_variant_groups_cannot_be_spliced_or_doubled_without_permission():
    source = parse_unique_source(
        """Test
Ring
Has Alt Variant: true
Variant: A
Variant: B
Variant: C
{variant:1,2}+10 to maximum Life
{variant:1}+20 to maximum Mana
{variant:2}+30 to maximum Mana
{variant:3}+40 to maximum Mana
""",
        name="Test",
        base="Ring",
    )
    matches = itemparse._unique_variant_combination_matches
    assert matches(["+10 to maximum Life", "+20 to maximum Mana", "+30 to maximum Mana"], source)
    assert not matches(["+20 to maximum Mana", "+30 to maximum Mana"], source)
    assert not matches(
        ["+10 to maximum Life", "+20 to maximum Mana", "+20 to maximum Mana"], source
    )


def test_large_generated_jewel_prunes_to_real_selected_choices():
    raw = _item(
        "Megalomaniac",
        ["Allocates Abasement", "Allocates Acceleration", "Allocates Adaptable Assault", "Corrupted"],
    )
    assert itemparse.audit_item_legality(raw)["ok"]
    assert not itemparse.audit_item_legality(raw + "\nAllocates Adaptive Skin")["ok"]
    unique = db.get_unique("Megalomaniac")
    assert not itemparse.audit_item_legality("Rarity: Unique\n" + unique["text"])["ok"]


_HEART_MODIFIERS = [
    "Gain 10% of Damage as Extra Chaos Damage",
    "Gain 12% of Damage as Extra Cold Damage",
    "Recover 2% of maximum Mana on Kill",
    "6% increased Mana Regeneration Rate",
]


@pytest.mark.parametrize("marker", ["plain", "prefix", "suffix"])
def test_generated_jewel_source_markers_match_clipboard_effects(marker):
    unique = db.get_unique("Heart of the Well", include_source=True)
    assert "{desecrated}" in unique["pobSource"]
    modifiers = [
        "{desecrated}" + line
        if marker == "prefix"
        else line + " (desecrated)"
        if marker == "suffix"
        else line
        for line in _HEART_MODIFIERS
    ]
    raw = _item("Heart of the Well", modifiers)
    result = itemparse.audit_item_legality(raw, require_special_provenance=True)
    assert result["ok"], result
    # Matching intrinsic effects must not rewrite the original provenance projection.
    kinds = {entry["kind"] for entry in itemparse.semantic_item_structure(raw)["effects"]}
    assert kinds == ({"explicit"} if marker == "plain" else {"desecrated"})


@pytest.mark.parametrize(
    "modifiers",
    [
        _HEART_MODIFIERS[:-1],
        _HEART_MODIFIERS + ["+9999 to maximum Mana"],
        [line.replace("Gain 10%", "Gain 14%") for line in _HEART_MODIFIERS],
        [*_HEART_MODIFIERS[:3], _HEART_MODIFIERS[2]],
        ["{unknown}" + line for line in _HEART_MODIFIERS],
    ],
)
def test_generated_jewel_marker_matching_keeps_complete_choices_and_roll_limits(modifiers):
    result = itemparse.audit_item_legality(_item("Heart of the Well", modifiers))
    assert not result["ok"]
    assert "unique_modifier_mismatch" in result["issues"]


def test_generated_jewel_matching_does_not_authorize_external_special_sources():
    raw = _item("Heart of the Well", _HEART_MODIFIERS)
    for extra in ["\nCorrupted", "\nRune: Iron Rune\n{rune}+20 to Armour"]:
        result = itemparse.audit_item_legality(raw + extra, require_special_provenance=True)
        assert "special_source_provenance_required" in result["issues"]
    assert not equipment._same_unique_identity(raw, raw.replace("Gain 10%", "Gain 11%"))


def test_tagged_generated_source_and_clipboard_share_only_the_selected_effects():
    unique = db.get_unique("Heart of the Well", include_source=True)
    source = parse_unique_source(unique["pobSource"], name=unique["name"], base=unique["base"])
    raw_source = "Rarity: Unique\n" + unique["pobSource"]
    clipboard = _item(
        unique["name"],
        [line.removeprefix("{desecrated}") for line in source.project(source.selected)],
    )
    assert itemparse.audit_item_legality(raw_source)["ok"]
    assert itemparse.audit_item_legality(clipboard)["ok"]
    assert equipment._same_unique_identity(raw_source, clipboard)
    assert not equipment._same_unique_identity(raw_source, _item(unique["name"], _HEART_MODIFIERS))


@pytest.mark.parametrize(
    "class_name,ascendancy", [("Huntress", "Amazon"), ("Sorceress", "Stormweaver")]
)
@pytest.mark.parametrize("tagged", [False, True])
def test_pob_generated_unique_jewel_verifies_existing_slot(
    fireball, class_name, ascendancy, tagged
):
    from server.compute import completeness
    from server.compute.state import build_state_hash

    fireball.set_level(95)
    fireball.set_class(class_name, ascendancy)
    fireball.alloc_passive(61834, path_attribute="Intelligence")
    modifiers = [("{desecrated}" if tagged else "") + line for line in _HEART_MODIFIERS]
    raw = _item("Heart of the Well", modifiers)
    before = fireball.get_build()
    result = equipment.equip_jewel_verified(
        fireball, raw=raw, socket=61834, expected_state_hash=build_state_hash(fireball.get_xml())
    )
    assert result["ok"] and result["readbackVerified"], result
    assert result["socketOperation"] == "existing_allocated_socket"
    after = fireball.get_build()
    assert after["normalPassivePointsUsed"] == before["normalPassivePointsUsed"]
    actual = completeness.equipped_item_text_from_engine(fireball, "Jewel 61834")
    assert actual and equipment._same_unique_identity(raw, actual)
    assert itemparse.audit_item_legality(actual, require_special_provenance=True)["ok"]
    stable_hash = build_state_hash(fireball.get_xml())
    rejected = equipment.equip_jewel_verified(
        fireball, raw=raw.replace("Gain 10%", "Gain 14%"), socket=61834
    )
    assert rejected["errorCode"] == "item_legality_check_failed"
    assert build_state_hash(fireball.get_xml()) == stable_hash


def test_fixed_unique_implicit_and_tagged_source_still_match_actual_rolls():
    raw = _item(
        "Andvarius",
        [
            "Implicits: 1",
            "10% increased Rarity of Items found",
            "60% increased Rarity of Items found",
            "+10 to Dexterity",
            "-20% to all Elemental Resistances",
        ],
    )
    assert itemparse.audit_item_legality(raw)["ok"]
    assert not itemparse.audit_item_legality(raw.replace("60% increased", "71% increased"))["ok"]


def test_overlapping_modifier_ranges_are_order_independent():
    assert itemparse._unique_modifiers_match(
        ["+15 to maximum Mana", "+30 to maximum Mana"],
        ["+(10-40) to maximum Mana", "+(10-20) to maximum Mana"],
    )


def test_readback_cannot_change_selected_unique_variant_or_implicit_roll():
    unique = db.get_unique("Mageblood", include_source=True)
    raw = "Rarity: Unique\n" + unique["pobSource"]
    assert not equipment._same_unique_identity(
        raw, raw.replace("Selected Variant: 1\n", "Selected Variant: 5\n")
    )
    raw = _mageblood("Bismuth", "Amethyst", "Quicksilver", "Silver", charms=2)
    assert not equipment._same_unique_identity(
        raw, raw.replace("Has 2 Charm Slot", "Has 3 Charm Slot")
    )


def test_pob_equipment_accepts_variant_and_verifies_actual_slot(fireball):
    fireball.set_level(95)
    raw = _mageblood("Bismuth", "Amethyst", "Quicksilver", "Silver")
    result = equipment.equip_item_verified(fireball, raw=raw, slot="Belt", craft_receipt_ref=None)
    assert result["ok"], result
    assert result["readbackVerified"]
    assert fireball.get_build()["gear"]["Belt"]["name"] == "Mageblood"


def test_unique_corruption_requires_exact_verified_source_even_with_valid_variants():
    raw = _mageblood("Bismuth", "Amethyst", "Quicksilver", "Silver")
    raw += "\n+1 to Level of all Skills (implicit)\nCorrupted"
    fingerprint = itemparse.semantic_item_structure(raw)["itemFingerprint"]
    provenance = {
        "itemFingerprint": fingerprint,
        "sources": {
            "corruption": {
                "lineFingerprint": itemparse.line_fingerprint("+1 to Level of all Skills")
            }
        },
    }
    assert itemparse.audit_item_legality(
        raw, trusted_provenance=provenance, require_special_provenance=True
    )["ok"]
    assert not itemparse.audit_item_legality(raw, require_special_provenance=True)["ok"]
    assert not itemparse.audit_item_legality(
        raw.replace("have 40%", "have 45%"), trusted_provenance=provenance
    )["ok"]


ADONIA = """Rarity: UNIQUE
Adonia's Ego
Siphoning Wand
Requires Level 65
Implicits: 1
Grants Skill: Level 20 Power Siphon
Grants Skill: Pinnacle of Power
+125 to maximum Mana
+3 to Level of all Spell Skills
23% increased Cast Speed
-10% to all Elemental Resistances per Power Charge
-1 to Maximum Power Charges"""


def test_unique_granted_skills_are_modifiers_not_metadata():
    assert itemparse.audit_item_legality(ADONIA)["ok"]
    for wrong in [
        ADONIA.replace("Level 20 Power Siphon", "Level 21 Power Siphon"),
        ADONIA.replace("Power Siphon", "Spark"),
        ADONIA.replace("Grants Skill: Pinnacle of Power\n", ""),
        ADONIA + "\nGrants Skill: Fireball",
    ]:
        assert not itemparse.audit_item_legality(wrong)["ok"]


def test_pob_unique_granted_skill_roundtrip(fireball):
    fireball.set_level(95)
    result = equipment.equip_item_verified(
        fireball, raw=ADONIA, slot="Weapon 1", craft_receipt_ref=None
    )
    assert result["ok"], result
    assert result["readbackVerified"]
