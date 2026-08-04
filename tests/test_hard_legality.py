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
            }
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
            lambda build: build.update({"spiritUsed": 101}),
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
