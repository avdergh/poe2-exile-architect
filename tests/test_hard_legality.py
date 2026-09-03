from copy import deepcopy

import pytest

from server.judge import hard_legality


def _legal_build() -> dict[str, object]:
    return {
        "class": "Monk",
        "ascendancy": "Martial Artist",
        "level": 85,
        "pointsUsed": 108,
        "pointsAvailable": 108,
        "spiritUsed": 100,
        "spiritAvailable": 100,
        "spiritReservedCapped": 100,
        "spiritUnreserved": 0,
        "spiritRequested": 100,
        "spiritOverBy": 0,
        "activeWeaponSet": 1,
        "attributes": {
            "strength": 90,
            "dexterity": 120,
            "intelligence": 80,
        },
        "attributeRequirements": {
            "strength": 80,
            "dexterity": 100,
            "intelligence": 80,
        },
        "mainSkillWeaponCheck": {
            "skillName": "Tempest Flurry",
            "weaponTypes": ["Quarterstaff"],
            "equippedWeaponTypes": ["Quarterstaff"],
            "compatible": True,
        },
        "activeSkillGemLevelViolations": [],
        "gear": {
            "Weapon 1": {
                "name": "Legal Quarterstaff",
                "levelRequirement": 78,
                "affixLegality": {"ok": True, "issues": []},
            },
            "Flask 1": {"name": "Unique Life Flask", "rarity": "UNIQUE"},
            "Flask 2": {
                "name": "Magic Mana Flask",
                "rarity": "MAGIC",
                "itemLevel": 82,
                "affixPrefixes": 1,
                "affixSuffixes": 0,
            },
        },
    }


def test_hard_legality_reports_exact_attribute_shortfall_before_judge():
    build = _legal_build()
    build["attributes"]["intelligence"] = 72

    result = hard_legality.audit_build(build)

    assert result["hardLegalityReady"] is False
    assert result["hardFailures"] == ["attribute_requirement_unmet"]
    assert result["checks"]["attributes"]["shortfalls"] == [
        {
            "attribute": "intelligence",
            "available": 72.0,
            "required": 80.0,
            "shortfall": 8.0,
        }
    ]


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        (
            lambda build: build["gear"]["Weapon 1"].update({"levelRequirement": 90}),
            "equipped_item_level_requirement_unmet",
        ),
        (
            lambda build: build.update(
                {
                    "activeSkillGemLevelViolations": [
                        {
                            "groupIndex": 1,
                            "name": "Tempest Flurry",
                            "gemLevel": 20,
                            "requiredLevel": 90,
                            "characterLevel": 85,
                            "maximumLegalLevel": 19,
                        }
                    ]
                }
            ),
            "active_skill_gem_level_requirement_unmet",
        ),
        (
            lambda build: build["mainSkillWeaponCheck"].update(
                {
                    "equippedWeaponTypes": ["Wand"],
                    "compatible": False,
                }
            ),
            "incompatible_weapon_skill_tags",
        ),
        (
            lambda build: build.update(
                {
                    "spiritUsed": 101,
                    "spiritRequested": 101,
                    "spiritReservedCapped": 100,
                    "spiritUnreserved": -1,
                    "spiritOverBy": 1,
                }
            ),
            "spirit_budget_exceeded",
        ),
        (
            lambda build: build.update({"pointsUsed": 109}),
            "passive_budget_exceeded",
        ),
        (
            lambda build: build["gear"]["Weapon 1"].update(
                {
                    "affixLegality": {
                        "ok": False,
                        "issues": ["prefix_limit_exceeded"],
                    }
                }
            ),
            "illegal_equipped_item_affixes",
        ),
    ],
)
def test_hard_legality_uses_one_shared_decision_for_deterministic_failures(
    mutation,
    failure,
):
    build = deepcopy(_legal_build())
    mutation(build)

    result = hard_legality.audit_build(build)

    assert result["hardLegalityReady"] is False
    assert failure in result["hardFailures"]


def test_hard_legality_accepts_a_fully_legal_candidate():
    result = hard_legality.audit_build(_legal_build())

    assert result["status"] == "passed"
    assert result["hardLegalityReady"] is True
    assert result["hardFailures"] == []


@pytest.mark.parametrize(
    "flask2",
    [
        None,
        {"rarity": "NORMAL"},
        {"rarity": "MAGIC"},
        {"rarity": "RARE", "itemLevel": 82, "affixPrefixes": 1, "affixSuffixes": 1},
    ],
)
def test_generated_endgame_requires_modified_flasks(flask2):
    build = _legal_build()
    if flask2 is None:
        build["gear"].pop("Flask 2")
    else:
        build["gear"]["Flask 2"] = flask2

    result = hard_legality.audit_build(build)

    assert "endgame_flask_loadout_incomplete" in result["hardFailures"]
    assert result["checks"]["generatedItemDelivery"]["flaskIssues"]


def test_hard_legality_blocks_capped_spirit_false_pass():
    build = _legal_build()
    build.update(
        {
            "spiritAvailable": 150,
            "spiritReservedCapped": 150,
            "spiritUnreserved": -227,
            "spiritRequested": 377,
            "spiritOverBy": 227,
            "spiritUsed": 377,
        }
    )

    result = hard_legality.audit_build(build)

    assert result["checks"]["spiritBudget"]["ledgerStatus"] == "consistent"
    assert result["checks"]["spiritBudget"]["reservedCapped"] == 150
    assert "spirit_budget_exceeded" in result["hardFailures"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda build: build.pop("spiritUnreserved"),
        lambda build: build.update({"spiritRequested": float("nan")}),
        lambda build: build.update({"spiritOverBy": 0, "spiritUnreserved": -1}),
        lambda build: build.update({"spiritAvailable": "100"}),
        lambda build: build.update({"spiritOverBy": False}),
        lambda build: build.update({"activeWeaponSet": "1"}),
        lambda build: build.update({"activeWeaponSet": 3}),
    ],
)
def test_hard_legality_fails_closed_on_unverified_spirit_ledger(mutation):
    build = _legal_build()
    mutation(build)

    result = hard_legality.audit_build(build)

    assert result["checks"]["spiritBudget"]["ledgerStatus"] != "consistent"
    assert "spirit_budget_unverified" in result["hardFailures"]


@pytest.mark.parametrize(
    ("item", "failure", "slot_key"),
    [
        (
            {
                "name": "Scaffold Body Armour",
                "rarity": "rare",
                "itemLevel": 85,
                "isScaffold": True,
                "affixLegality": {"ok": True, "issues": []},
            },
            "scaffold_gear_must_be_replaced",
            "scaffoldSlots",
        ),
        (
            {
                "name": "Generated Ring",
                "rarity": "rare",
                "itemLevel": None,
                "isScaffold": False,
                "affixLegality": {"ok": True, "issues": []},
            },
            "rare_or_magic_item_level_missing",
            "missingItemLevelSlots",
        ),
    ],
)
def test_generated_candidate_delivery_omissions_are_hard_failures(item, failure, slot_key):
    build = _legal_build()
    build["gear"]["Body Armour"] = item

    result = hard_legality.audit_build(build, source_context="generated_candidate")

    assert result["hardLegalityReady"] is False
    assert failure in result["hardFailures"]
    assert result["checks"]["generatedItemDelivery"][slot_key] == ["Body Armour"]


def test_reference_build_does_not_inherit_generated_delivery_metadata_gates():
    build = _legal_build()
    build["gear"]["Body Armour"] = {
        "name": "Scaffold Body Armour",
        "rarity": "rare",
        "itemLevel": None,
        "isScaffold": True,
        "affixLegality": {"ok": True, "issues": []},
    }

    result = hard_legality.audit_build(build, source_context="trusted_reference")

    assert "scaffold_gear_must_be_replaced" not in result["hardFailures"]
    assert "rare_or_magic_item_level_missing" not in result["hardFailures"]


def test_legality_regression_does_not_blame_an_unchanged_preexisting_shortfall():
    before_build = _legal_build()
    before_build["attributes"]["intelligence"] = 72
    after_build = deepcopy(before_build)
    after_build["gear"]["Amulet"] = {
        "name": "Damage Amulet",
        "levelRequirement": 70,
        "affixLegality": {"ok": True, "issues": []},
    }

    result = hard_legality.compare_audits_for_regression(
        hard_legality.audit_build(before_build),
        hard_legality.audit_build(after_build),
    )

    assert result["regressed"] is False
    assert result["reasons"] == []
    assert result["preExistingHardFailures"] == ["attribute_requirement_unmet"]


def test_legality_regression_rejects_a_candidate_that_worsens_attribute_shortfall():
    before_build = _legal_build()
    before_build["attributes"]["intelligence"] = 72
    after_build = deepcopy(before_build)
    after_build["attributes"]["intelligence"] = 70

    result = hard_legality.compare_audits_for_regression(
        hard_legality.audit_build(before_build),
        hard_legality.audit_build(after_build),
    )

    assert result["regressed"] is True
    assert result["reasons"] == [
        {
            "code": "attribute_requirement_unmet",
            "change": "worsened",
            "attribute": "intelligence",
            "beforeShortfall": 8.0,
            "afterShortfall": 10.0,
        }
    ]
