"""辅助授予效果须有合法宿主；生命保留不得用 Spirit 收益抵消。"""

from copy import deepcopy

import pytest

from server.compute import supportopt
from server.compute.state import build_state_hash
from server.generation import preflight
from server.judge import evaluator, hard_legality


def capability(engine, text):
    engine.paste_skill(text)
    assert engine.call("set_skill_group_state", index=1, makeMain=True, activeSkillIndex=1)["ok"]
    return engine.call(
        "inspect_support_evaluation_capability", index=1, activeIndex=1, objectiveKeys=["TotalEHP"]
    )


@pytest.mark.parametrize(
    "class_name,host",
    [
        ("Mercenary", "Ghost Dance"),
        ("Sorceress", "Wind Dancer"),
        ("Ranger", "Ice Shot"),
    ],
)
def test_support_cannot_authorize_its_own_plant_child(engine, class_name, host):
    engine.new_build()
    engine.set_class(class_name)
    engine.set_level(95)
    observed = capability(engine, f"{host} 20/20 1\nPoison Spores")
    assert observed["applicationCheck"] == "failed"
    row = observed["supportApplication"][0]
    assert row["supportEffectId"] == "SupportPoisonSpores"
    assert row["activeSkills"] == []
    assert row["rootedActiveEffectIds"] == []
    assert row["unrootedActiveEffectIds"] == ["TriggeredPoisonSporesPustule"]


def test_unlicensed_child_does_not_authorize_other_supports(engine):
    engine.new_build()
    engine.set_class("Mercenary")
    engine.set_level(95)
    observed = capability(engine, "Ghost Dance 20/20 1\nPoison Spores\nBursting Plague\nWind Wave")
    assert observed["applicationCheck"] == "failed"
    assert all(not row["activeSkills"] for row in observed["supportApplication"])


@pytest.mark.parametrize("host", ["Toxic Growth", "Vine Arrow"])
def test_plant_host_authorizes_support_and_its_granted_effect(engine, host):
    engine.new_build()
    engine.set_class("Ranger")
    engine.set_level(95)
    observed = capability(engine, f"{host} 20/20 1\nPoison Spores")
    assert observed["applicationCheck"] == "verified"
    row = observed["supportApplication"][0]
    assert "TriggeredPoisonSporesPustule" in row["rootedActiveEffectIds"]
    assert len(row["rootedActiveEffectIds"]) >= 2
    assert row["unrootedActiveEffectIds"] == []


def test_native_wind_counterattack_remains_a_valid_host(engine):
    engine.new_build()
    engine.set_class("Ranger")
    engine.set_level(95)
    observed = capability(
        engine,
        "Wind Dancer 20/20 1\nBlind II\nBursting Plague\nEonyr's Thunder\nFrozen Spite\nWind Wave",
    )
    assert observed["applicationCheck"] == "verified"
    assert all(row["activeSkills"] for row in observed["supportApplication"])
    assert any(
        effect_id != "WindDancerPlayer"
        for row in observed["supportApplication"]
        for effect_id in row["rootedActiveEffectIds"]
    )


def test_ci_life_reservation_blocks_preflight_and_judge_without_mutation(engine):
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(95)
    engine.alloc_passive("Chaos Inoculation", path_attribute="Intelligence")
    capability(engine, "Elemental Conflux 20/20 1\nAtziri's Communion\nDirestrike II")
    before = build_state_hash(engine.get_xml())
    build = engine.get_build()
    assert build["stats"]["Life"] == build["stats"]["LifeReserved"] == 1
    assert build["stats"]["LifeUnreserved"] == 0
    checked = preflight.inspect_generation_preflight(engine)
    assert "life_reservation_exhausts_life" in checked["blockingIssues"]
    judged = evaluator.evaluate_active_build(engine, "ci-reservation-test")
    assert "life_reservation_exhausts_life" in judged["hardFailures"]
    assert build_state_hash(engine.get_xml()) == before


def test_non_ci_life_reservation_retains_available_life(engine):
    engine.new_build()
    engine.set_class("Mercenary")
    engine.set_level(95)
    capability(engine, "Elemental Conflux 20/20 1\nAtziri's Communion")
    checked = hard_legality.life_reservation_check(engine.get_build())
    assert checked["reserved"] > 0
    assert checked["unreserved"] >= 1
    assert checked["status"] == "passed"


@pytest.mark.parametrize(
    "life,reserved,unreserved,status",
    [
        (1, 1, 0, "failed"),
        (100, 100, -10, "failed"),
        (100, 99, 1, "passed"),
        (1, 0, 1, "passed"),
        (None, 1, 0, "unknown"),
        (True, 1, 0, "unknown"),
    ],
)
def test_life_reservation_uses_observed_pool_without_ci_guess(life, reserved, unreserved, status):
    build = {"stats": {"Life": life, "LifeReserved": reserved, "LifeUnreserved": unreserved}}
    before = deepcopy(build)
    assert hard_legality.life_reservation_check(build)["status"] == status
    assert build == before


def test_life_reservation_regression_retains_existing_failure_and_detects_worsening():
    def audit(remaining):
        return hard_legality.audit_build(
            {"stats": {"Life": 100, "LifeReserved": 100, "LifeUnreserved": remaining}}
        )

    result = hard_legality.compare_audits_for_regression(audit(0), audit(-5))
    assert any(
        row["code"] == "life_reservation_exhausts_life" and row["change"] == "worsened"
        for row in result["reasons"]
    )


def test_old_support_receipt_cannot_be_current_evidence():
    assert not supportopt.support_audit_is_complete({"auditVersion": "support_audit_v3"})
