from __future__ import annotations

from server.judge import rules


def test_class_ascendancy_pairing_rejects_cross_class_ascendancy():
    result = rules.check_class_ascendancy("Witch", "Witchhunter")

    assert result["ok"] is False
    assert result["failureCode"] == "invalid_class_ascendancy_pairing"
    assert "Witchhunter" in result["detail"]


def test_class_ascendancy_pairing_accepts_known_poe2_pair():
    result = rules.check_class_ascendancy("Mercenary", "Witchhunter")

    assert result == {"ok": True}


def test_class_ascendancy_pairing_treats_pob_none_as_unascended_campaign_character():
    result = rules.check_class_ascendancy("Witch", "None", level_band="campaign")

    assert result == {"ok": True, "caveat": "missing_ascendancy_non_endgame_caveat"}


def test_class_ascendancy_pairing_allows_non_endgame_missing_ascendancy_with_caveat():
    result = rules.check_class_ascendancy("Mercenary", "", level_band="campaign")

    assert result["ok"] is True
    assert result["caveat"] == "missing_ascendancy_non_endgame_caveat"


def test_socket_rules_require_exactly_one_active_skill():
    group = [
        {"name": "Spark", "isSupport": False},
        {"name": "Fireball", "isSupport": False},
        {"name": "Controlled Destruction", "isSupport": True},
    ]

    failures, caveats = rules.check_main_skill_group(group)

    assert "invalid_socket_setup" in failures
    assert caveats == ["support_conflict_unverified_caveat"]


def test_socket_rules_allow_multi_active_reference_group_with_caveat():
    group = [
        {"name": "Comet", "isSupport": False},
        {"name": "Frost Bomb", "isSupport": False},
        {"name": "Controlled Destruction", "isSupport": True},
    ]

    failures, caveats = rules.check_main_skill_group(group, strict_active_skill_count=False)

    assert "invalid_socket_setup" not in failures
    assert "external_multi_active_socket_group_caveat" in caveats
    assert "support_conflict_unverified_caveat" in caveats


def test_socket_rules_reject_support_limit_duplicate_and_unknown_support():
    group = [{"name": "Spark", "isSupport": False}]
    group += [{"name": f"Known Support {idx}", "isSupport": True} for idx in range(5)]
    group += [{"name": "Known Support 1", "isSupport": True}]
    group += [{"name": "Mystery Support", "isSupport": True}]

    failures, _caveats = rules.check_main_skill_group(
        group,
        known_supports={
            "Known Support 0",
            "Known Support 1",
            "Known Support 2",
            "Known Support 3",
            "Known Support 4",
        },
    )

    assert "support_limit_exceeded" in failures
    assert "duplicate_support_gem" in failures
    assert "invalid_support_gem" in failures


def test_socket_rules_accept_pob_recognized_support_outside_seed_list():
    group = [
        {"name": "Spark", "isSupport": False},
        {"name": "Lightning Penetration", "isSupport": True, "supportKnown": True},
    ]

    failures, _caveats = rules.check_main_skill_group(group, known_supports=set())

    assert "invalid_support_gem" not in failures


def test_weapon_skill_check_rejects_pob_disable_reason():
    result = rules.check_weapon_skill_compatibility(
        {
            "skillName": "Lightning Spear",
            "weaponTypes": ["Spear"],
            "equippedWeaponTypes": ["Wand"],
            "disableReason": "Main Hand weapon is not usable with this skill",
        }
    )

    assert result["ok"] is False
    assert result["failureCode"] == "incompatible_weapon_skill_tags"
    assert "Lightning Spear" in result["detail"]


def test_physical_invalid_failures_block_scoring():
    failures = {"invalid_socket_setup", "uncapped_resistance", "weapon_set_budget_exceeded"}

    blocked = rules.blocked_score_dimensions(failures)

    assert "offense" in blocked
    assert "defense" in blocked
    assert "recovery" in blocked
    assert "mobility" in blocked
    assert "uncapped_resistance" not in rules.PHYSICAL_INVALID_FAILURES
    assert "weapon_set_budget_exceeded" in rules.PHYSICAL_INVALID_FAILURES
