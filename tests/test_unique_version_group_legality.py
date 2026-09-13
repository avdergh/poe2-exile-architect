"""Pinned PoB version/group choices: static legality, not numerical certification."""

from pathlib import Path
import re
import sqlite3

import pytest

from server.knowledge import db, itemparse
from server.knowledge.unique_variants import parse_unique_source


@pytest.fixture
def unique_sources(monkeypatch):
    raw = (
        Path(__file__).with_name("fixtures").joinpath("unique_selection_055.lua").read_text("utf-8")
    )
    sources = {block.splitlines()[0]: block for block in re.findall(r"\[\[(.*?)\]\]", raw, re.S)}
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE uniques(name, base, item_type, text, raw)")
    for name, block in sources.items():
        con.execute(
            "INSERT INTO uniques VALUES(?,?,?,?,?)",
            (name, block.splitlines()[1], "test", block, block),
        )
    monkeypatch.setattr(db, "_conn", lambda: con)
    monkeypatch.setattr(db, "mods_for_text", lambda *args, **kwargs: [])
    monkeypatch.setattr(db, "craft_profile", lambda *args: None)
    monkeypatch.setattr(db, "illegal_affixes", lambda *args: [])
    yield sources
    con.close()


def _item(name, lines):
    return "\n".join(["Rarity: Unique", name, db.get_unique(name)["base"], *lines])


OLROTH_CURRENT = [
    "125% increased Charges per use",
    "Regenerate 4% of maximum Runic Ward per second during Effect",
    "Gain Guard equal to Current Runic Ward for 10 seconds when Effect ends",
]


def test_current_olroth_complete_instance_is_legal(unique_sources):
    result = itemparse.audit_item_legality(_item("Olroth's Resolve", OLROTH_CURRENT))
    assert result["ok"], result


def test_olroth_version_contract_and_default_exclude_history(unique_sources):
    unique = db.get_unique("Olroth's Resolve")
    contract = unique["variantSelection"]
    assert contract["defaultSelection"]["versionId"] == 3
    assert contract["versions"] == [
        {"id": 1, "name": "Pre 0.4.0"},
        {"id": 2, "name": "Pre 0.5.0"},
        {"id": 3, "name": "Current"},
    ]
    assert "Instant Recovery" not in unique["defaultSelectionText"]
    assert "Excess Life Recovery" not in unique["defaultSelectionText"]
    assert "Version: Pre 0.4.0" in unique["text"]
    assert "pobSource" not in unique


@pytest.mark.parametrize(
    "extra", ["Instant Recovery", "Excess Life Recovery added as Guard for 20 seconds"]
)
def test_olroth_cannot_mix_current_and_history(unique_sources, extra):
    assert not itemparse.audit_item_legality(_item("Olroth's Resolve", OLROTH_CURRENT + [extra]))[
        "ok"
    ]


def test_separate_complete_historical_versions_remain_legal(unique_sources):
    for duration in (10, 20):
        lines = [
            "Instant Recovery",
            "125% increased Charges per use",
            f"Excess Life Recovery added as Guard for {duration} seconds",
        ]
        assert itemparse.audit_item_legality(_item("Olroth's Resolve", lines))["ok"]
    assert not itemparse.audit_item_legality(
        _item("Olroth's Resolve", lines + ["Excess Life Recovery added as Guard for 10 seconds"])
    )["ok"]


def test_version_and_independent_variant_apply_together(unique_sources):
    raw = unique_sources["Controlled Metamorphosis"]
    source = parse_unique_source(raw, name="Controlled Metamorphosis", base="Diamond")
    current = source.project(source.selected)
    assert "Only affects Passives in Medium Ring" in current
    assert not any("Chaos Resistance" in line for line in current)
    assert "Limited to: 1" in db.get_unique("Controlled Metamorphosis")["text"]
    assert "Radius: Variable" in db.get_unique("Controlled Metamorphosis")["text"]
    assert itemparse.audit_item_legality(_item("Controlled Metamorphosis", current))["ok"]
    assert not itemparse.audit_item_legality(
        _item("Controlled Metamorphosis", current + ["Only affects Passives in Massive Ring"])
    )["ok"]


def test_two_independent_groups_require_one_whole_option_each(unique_sources):
    unique = db.get_unique("Atziri's Splendour", include_source=True)
    groups = unique["variantSelection"]["groups"]
    assert "Sockets: S S S S S S" in unique["text"]
    assert [group["id"] for group in groups] == [1, 2]
    assert [entry["id"] for entry in groups[0]["options"]] == [1, 2, 3, 4]
    assert [entry["id"] for entry in groups[1]["options"]] == list(range(5, 12))
    source = parse_unique_source(unique["pobSource"], name=unique["name"], base=unique["base"])
    lines = source.project(source.selected)
    assert all("{group:" not in line for line in lines)
    assert itemparse.audit_item_legality(_item(unique["name"], lines))["ok"]
    defense = next(line for line in lines if "increased Armour, Evasion" in line)
    crossed = [line for line in lines if line != defense] + [
        "This item gains bonuses from Socketed Soul Cores as though it was also Gloves"
    ]
    assert not itemparse.audit_item_legality(_item(unique["name"], crossed))["ok"]
    assert not itemparse.audit_item_legality(_item(unique["name"], lines + [defense]))["ok"]


def test_tagged_version_and_group_choices_cannot_override_source(unique_sources):
    raw = "Rarity: Unique\n" + unique_sources["Atziri's Splendour"]
    assert itemparse.audit_item_legality(raw)["ok"]
    for extra in [
        "Selected Variant Group: 1=6",
        "Selected Variant Group: 3=1",
        "Selected Variant Group: 1=1\nSelected Variant Group: 2=1",
    ]:
        assert not itemparse.audit_item_legality(raw + "\n" + extra)["ok"]
    olroth = "Rarity: Unique\n" + unique_sources["Olroth's Resolve"]
    assert itemparse.audit_item_legality(olroth)["ok"]
    assert not itemparse.audit_item_legality(olroth + "\nSelected Version: 99")["ok"]


def test_pob_writeout_replaces_legacy_alt_metadata_with_groups(unique_sources):
    # Item.lua WriteRaw emits group choices, omitting obsolete alt slots in modern mode.
    raw = "Rarity: Unique\n" + unique_sources["Atziri's Splendour"]
    raw = "\n".join(
        line
        for line in raw.splitlines()
        if not line.startswith(("Has Alt Variant:", "Selected Variant:", "Selected Alt Variant:"))
    )
    raw += "\nSelected Variant Group: 1=3\nSelected Variant Group: 2=7"
    assert itemparse.audit_item_legality(raw)["ok"]


def _synthetic(raw):
    return parse_unique_source("Synthetic\nRing\n" + raw, name="Synthetic", base="Ring")


def test_version_restricts_group_options_and_inactive_group_is_not_required():
    source = _synthetic("""Version: Historical
Version: Current
Variant: Old Life
Variant: New Life
Variant: New Mana
Variant: New Shield
+5 to Strength
{version:1}{variant:1}{group:1}+10 to maximum Life
{version:2}{variant:2}{group:1}+20 to maximum Life
{version:2}{variant:3}{group:2}+30 to maximum Mana
{version:2}{variant:4}{group:2}+40 to maximum Energy Shield""")
    matches = itemparse._unique_variant_combination_matches
    assert source.selected_version == 2
    assert source.selected_groups == ((1, 2), (2, 3))
    assert source.groups[0].eligible(1) == (1,)
    assert source.groups[0].eligible(2) == (2,)
    assert matches(["+5 to Strength", "+10 to maximum Life"], source)
    assert matches(
        ["+5 to Strength", "+20 to maximum Life", "+40 to maximum Energy Shield"], source
    )
    assert not matches(["+5 to Strength", "+10 to maximum Life", "+30 to maximum Mana"], source)
    assert not matches(["+5 to Strength", "+20 to maximum Life"], source)
    assert not matches(
        [
            "+5 to Strength",
            "+20 to maximum Life",
            "+30 to maximum Mana",
            "+40 to maximum Energy Shield",
        ],
        source,
    )


def test_shared_multi_group_effect_is_or_once_and_same_choice_cannot_fill_two_groups():
    source = _synthetic("""Variant: A
Variant: B
Allow Duplicate Variants: true
{variant:1,2}{group:1,2}+10 to maximum Life
{variant:1}{group:1}+20 to maximum Mana
{variant:2}{group:2}+30 to maximum Energy Shield""")
    matches = itemparse._unique_variant_combination_matches
    expected = ["+10 to maximum Life", "+20 to maximum Mana", "+30 to maximum Energy Shield"]
    assert source.project(source.selected) == expected
    assert matches(expected, source)
    assert not matches(expected + ["+10 to maximum Life"], source)
    # A is eligible in both groups, but using it twice is forbidden even with old duplicate metadata.
    assert not matches(["+10 to maximum Life", "+20 to maximum Mana"], source)
    assert source.public_contract()["allowDuplicateVariants"] is False


def test_explicit_group_choices_are_preserved_before_filling_missing_groups():
    source = _synthetic("""Variant: A
Variant: B
Selected Variant Group: 2=1
{variant:1,2}{group:1,2}+10 to maximum Life""")
    assert source.selection_valid
    assert source.selected_groups == ((1, 2), (2, 1))


def test_legacy_generator_unselectable_sentinel_does_not_expand_choices():
    # Against the Darkness's generated source retains an out-of-list shared variant ID.
    source = _synthetic("""Variant: A
Variant: B
Selected Variant: 1
{variant:1,28}+10 to maximum Life
{variant:2,28}+20 to maximum Mana""")
    matches = itemparse._unique_variant_combination_matches
    assert matches(["+10 to maximum Life"], source)
    assert matches(["+20 to maximum Mana"], source)
    assert not matches(["+10 to maximum Life", "+20 to maximum Mana"], source)


@pytest.mark.parametrize(
    "raw",
    [
        "Version: Current\n{version:2}+10 to maximum Life",
        "Version: Current\n{version:}+10 to maximum Life",
        "Variant: A\n{variant:2}{group:1}+10 to maximum Life",
        "Variant: A\n{group:1}+10 to maximum Life",
        "Variant: A\nSelected Variant Group: 1=1\nSelected Variant Group: 1=1\n{variant:1}{group:1}+10 to maximum Life",
    ],
)
def test_invalid_condition_source_fails_closed(raw):
    with pytest.raises(ValueError):
        _synthetic(raw)


@pytest.mark.parametrize("name", ["Idol of Uldurn", "Wulfsbane"])
def test_remaining_pinned_versioned_unique_sources_are_legal(unique_sources, name):
    assert itemparse.audit_item_legality("Rarity: Unique\n" + unique_sources[name])["ok"]
