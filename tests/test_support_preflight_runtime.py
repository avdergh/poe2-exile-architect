"""真实 PoB 输出序号、资源约束与最终辅助 gate 的交叉回归。"""

from copy import deepcopy

import pytest

from server.compute import supportopt
from server.compute.state import build_state_hash
from server.generation import evaluation, preflight, validation_checkpoint


def _meta_group(engine, *, secondary=False):
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(95)
    text = "Cast on Critical 20/20 1 / Energy Retention\nComet 20/20 1 / Controlled Destruction"
    if secondary:
        engine.paste_skill("Spark 20/20 1")
        engine.add_skill_group(text)
    else:
        engine.paste_skill(text)
    index = 2 if secondary else 1
    selected = engine.call("set_skill_group_state", index=index, activeSkillIndex=2)
    assert selected["ok"] is True
    engine.call("set_skill_group_state", index=1, makeMain=True)
    return build_state_hash(engine.get_xml())


def _support_result(engine, *, skill="Comet"):
    checkpoint = validation_checkpoint.inspect_generation_checkpoint(
        engine, offense_skill_group_index=1, expected_skill_name=skill
    )
    assert "errorCode" not in checkpoint, checkpoint
    checklist = checkpoint["createQualityChecklist"]
    return checklist["skillSupportAudit"], [
        reason for reason in evaluation._final_check_blockers(checklist)
        if reason.startswith("skillSupportAudit:")
    ]


def test_real_default_command_stats_keep_runtime_calculation_index(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Disciple of Varashta")
    engine.set_level(95)
    engine.alloc_passive(34207)
    engine.call("set_skill_group_state", index=1, activeSkillIndex=2, makeMain=True)
    state_hash = build_state_hash(engine.get_xml())
    actual = engine.call("list_skill_groups")["groups"][0]
    assert actual["activeSkills"][1]["name"] == "Command"
    assert actual["mainActiveSkillCalcs"] == 2
    stats = engine.get_stats(["ManaCost"])["stats"]
    assert stats["ManaCost"] > 0

    projected = preflight.inspect_generation_snapshot(engine, engine.get_xml())
    assert projected["skillGroups"][0]["mainActiveSkillCalcs"] == 2
    assert projected["skillGroups"][0]["activeSkills"] == [
        "Ruzhan, the Blazing Sword", "Command",
    ]
    assert projected["skillGroups"][0]["activeSkillSelectionError"] is None
    implicit = validation_checkpoint.inspect_generation_checkpoint(engine)
    explicit = validation_checkpoint.inspect_generation_checkpoint(
        engine, offense_skill_group_index=1, expected_skill_name="Command"
    )
    assert implicit["calculationContext"] == explicit["calculationContext"] == {
        "groupIndex": 1, "activeIndex": 2, "skillName": "Command", "source": "pob_main_group",
    }
    assert implicit["stats"]["ManaCost"] == explicit["stats"]["ManaCost"] == stats["ManaCost"]
    assert build_state_hash(engine.get_xml()) == state_hash


def test_real_secondary_comet_audit_retains_selection_through_preflight_and_judge_gate(engine):
    state_hash = _meta_group(engine, secondary=True)
    result = supportopt.optimize_supports(engine, metric="FullDPS", group_index=2)
    assert result["supportAudit"]["reasonClass"] == "capability_gap"
    assert result["supportAudit"]["activeSkillIndex"] == 2
    assert result["supportAudit"]["skill"] == "Comet"
    projected = preflight.inspect_generation_snapshot(engine, engine.get_xml())
    assert projected["skillGroups"][1]["mainActiveSkillCalcs"] == 2
    support, blockers = _support_result(engine, skill="Spark")
    second = next(row for row in support["groupResults"] if row["groupIndex"] == 2)
    assert second["status"] == "unknown", support
    assert second["freshness"] == "current"
    assert second["activeSkillIndex"] == 2
    # Spark still needs its own final audit; the independently verified Comet must not acquire
    # a false selector mismatch just because checkpoint measures the Spark offense group.
    assert "skillSupportAudit:support_audit_calculation_context_mismatch:2" not in blockers
    assert build_state_hash(engine.get_xml()) == state_hash


@pytest.mark.parametrize("limit_kind", ["none", "equal", "mana", "spirit", "both"])
def test_real_rate_gap_does_not_override_known_resource_constraints(engine, limit_kind):
    state_hash = _meta_group(engine)
    stats = engine.get_stats(["ManaCost", "SpiritReserved"])["stats"]
    assert stats["ManaCost"] > 0 and stats["SpiritReserved"] > 0
    limits = {
        "none": {},
        "equal": {"max_mana_cost": stats["ManaCost"], "spirit_limit": stats["SpiritReserved"]},
        "mana": {"max_mana_cost": 0},
        "spirit": {"spirit_limit": 0},
        "both": {"max_mana_cost": 0, "spirit_limit": 0},
    }[limit_kind]
    result = supportopt.optimize_supports(engine, metric="FullDPS", **limits)
    measurement = result["measurement"]
    violated = limit_kind in {"mana", "spirit", "both"}
    assert result["supportAudit"]["activeSkillIndex"] == 2
    assert result["supportAudit"]["skill"] == "Comet"
    assert result["reasonClass"] == ("actionable_gap" if violated else "capability_gap")
    assert measurement["finalConstraintsSatisfied"] is (not violated)
    check = measurement["currentConstraintCheck"]
    assert check["status"] == ("failed" if violated else "not_applicable" if not limits else "passed")
    assert check["metrics"] == {key: stats[key] for key in check["limits"]}
    support, blockers = _support_result(engine)
    assert support["status"] == ("failed" if violated else "unknown"), support
    assert bool(blockers) is violated, blockers
    assert build_state_hash(engine.get_xml()) == state_hash


@pytest.mark.parametrize("fault,reason_class,reason_code", [
    ("exception", "measurement_error", "support_constraint_measurement_failed"),
    ("failed", "measurement_error", "support_constraint_measurement_failed"),
    ("no_stats", "measurement_error", "support_constraint_measurement_failed"),
    ("missing", "evidence_gap", "support_constraint_missing:ManaCost"),
    ("null", "evidence_gap", "support_constraint_missing:ManaCost"),
    ("nan", "measurement_error", "support_constraint_invalid:ManaCost"),
    ("infinity", "measurement_error", "support_constraint_invalid:ManaCost"),
    ("text", "measurement_error", "support_constraint_invalid:ManaCost"),
    ("bool", "measurement_error", "support_constraint_invalid:ManaCost"),
    ("missing_and_exceeded", "actionable_gap", "support_constraint_exceeded:SpiritReserved"),
])
def test_real_rate_gap_constraint_read_failures_cannot_become_unknown_exception(
    engine, monkeypatch, fault, reason_class, reason_code
):
    state_hash = _meta_group(engine)
    original_get_stats = engine.get_stats
    observed_targets = []

    def get_stats(keys=None):
        group = engine.call("list_skill_groups")["groups"][0]
        observed_targets.append((group["mainActiveSkillCalcs"], group["activeSkills"][1]["name"]))
        assert keys == ["ManaCost", "SpiritReserved"]
        if fault == "exception":
            raise RuntimeError("synthetic constraint read failure")
        if fault == "failed":
            return {"ok": False, "stats": {"ManaCost": 0, "SpiritReserved": 0}}
        if fault == "no_stats":
            return {"ok": True}
        measured = deepcopy(original_get_stats(keys))
        if fault in {"missing", "missing_and_exceeded"}:
            measured["stats"].pop("ManaCost")
        else:
            measured["stats"]["ManaCost"] = {
                "null": None, "nan": float("nan"), "infinity": float("inf"),
                "text": "0", "bool": False,
            }[fault]
        return measured

    with monkeypatch.context() as patch:
        patch.setattr(engine, "get_stats", get_stats)
        result = supportopt.optimize_supports(
            engine, metric="FullDPS", max_mana_cost=10000,
            spirit_limit=0 if fault == "missing_and_exceeded" else 10000,
        )
    assert observed_targets == [(2, "Comet")]
    assert result["reasonClass"] == reason_class
    assert reason_code in result["supportAudit"]["reasonCodes"]
    assert result["measurement"]["finalConstraintsSatisfied"] is False
    support, blockers = _support_result(engine)
    assert support["status"] == "failed", support
    assert blockers
    assert build_state_hash(engine.get_xml()) == state_hash
