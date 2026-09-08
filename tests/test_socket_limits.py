import pytest

from server.compute import socket_limits
from server.judge import hard_legality


XML = '<PathOfBuilding><Items activeItemSet="1"><ItemSet id="1"/></Items></PathOfBuilding>'


def rune(name="Limited Core", group="Limited Core", limit=1):
    return {"name": name, "constraints": [{"group": group, "limit": limit}]}


def test_same_slot_and_cross_slot_shared_limits():
    duplicate = socket_limits.audit(XML, replacements={"Helmet": [rune(), rune()]})
    cross = socket_limits.audit(
        XML,
        replacements={
            "Helmet": [rune("Core A", "shared")],
            "Body Armour": [rune("Core B", "shared")],
        },
    )
    assert not duplicate["ok"] and not cross["ok"]
    assert cross["violations"][0]["count"] == 2
    assert cross["violations"][0]["group"] == "shared"


def test_alternate_weapons_do_not_double_count_but_armour_is_shared():
    assert socket_limits.audit(
        XML,
        replacements={
            "Weapon 1": [rune()],
            "Weapon 1 Swap": [rune()],
        },
    )["ok"]
    result = socket_limits.audit(
        XML,
        replacements={
            "Weapon 1": [rune()],
            "Weapon 1 Swap": [rune()],
            "Helmet": [rune()],
        },
    )
    assert {row["weaponSet"] for row in result["violations"]} == {1, 2}


def test_distinct_groups_and_duplicate_metadata_are_not_double_counted():
    option = rune()
    option["constraints"] *= 2
    assert socket_limits.audit(XML, replacements={"Helmet": [option, rune(group="another")]})["ok"]


@pytest.mark.parametrize("limit", [0, -1, True, "1"])
def test_invalid_limit_metadata_is_rejected(limit):
    with pytest.raises(ValueError):
        socket_limits.constraints(rune(limit=limit))


def test_shared_hard_audit_includes_augment_quota_failure():
    from test_hard_legality import _legal_build

    build = _legal_build()
    build["socketLimits"] = {
        "ok": False,
        "violations": [{"group": "shared", "count": 2, "limit": 1}],
    }
    result = hard_legality.audit_build(build)
    assert "augment_limit_exceeded" in result["hardFailures"]
