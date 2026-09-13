"""真实 PoB 输出序号、资源约束与最终辅助 gate 的交叉回归。"""

from copy import deepcopy

import pytest

from server.compute import supportopt
from server.compute.state import build_state_hash
from server.generation import evaluation, preflight, validation_checkpoint


def _runtime_output(engine, root_skill, skill, *, source=None):
    matches = [
        (group, effect)
        for group in engine.call("list_skill_groups")["groups"]
        if group.get("source") == source and group["gems"][0]["name"] == root_skill
        for effect in group["activeSkills"]
        if effect.get("name") == skill
    ]
    assert len(matches) == 1, {"rootSkill": root_skill, "skill": skill, "source": source, "matches": matches}
    return matches[0]


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
    group, payload = _runtime_output(engine, "Cast on Critical", "Comet")
    selected = engine.call("set_skill_group_state", index=group["index"], activeSkillIndex=payload["index"])
    assert selected["ok"] is True
    main_group = _runtime_output(engine, "Spark", "Spark")[0] if secondary else group
    assert engine.call("set_skill_group_state", index=main_group["index"], makeMain=True)["ok"]
    return build_state_hash(engine.get_xml())


def _support_result(engine, *, skill="Comet"):
    group, _ = _runtime_output(engine, "Cast on Critical" if skill == "Comet" else skill, skill)
    checkpoint = validation_checkpoint.inspect_generation_checkpoint(
        engine, offense_skill_group_index=group["index"], expected_skill_name=skill
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
    group, command = _runtime_output(engine, "Ruzhan, the Blazing Sword", "Command", source="Tree:34207")
    assert engine.call("set_skill_group_state", index=group["index"], activeSkillIndex=command["index"], makeMain=True)["ok"]
    state_hash = build_state_hash(engine.get_xml())
    actual, actual_command = _runtime_output(engine, "Ruzhan, the Blazing Sword", "Command", source="Tree:34207")
    assert actual_command["name"] == "Command"
    assert actual["mainActiveSkillCalcs"] == command["index"]
    stats = engine.get_stats(["ManaCost"])["stats"]
    assert stats["ManaCost"] > 0

    projected = preflight.inspect_generation_snapshot(engine, engine.get_xml())
    projected_group = next(row for row in projected["skillGroups"] if row["groupIndex"] == group["index"])
    assert projected_group["mainActiveSkillCalcs"] == command["index"]
    assert projected_group["activeSkills"] == [
        "Ruzhan, the Blazing Sword", "Command",
    ]
    assert projected_group["activeSkillSelectionError"] is None
    implicit = validation_checkpoint.inspect_generation_checkpoint(engine)
    explicit = validation_checkpoint.inspect_generation_checkpoint(
        engine, offense_skill_group_index=group["index"], expected_skill_name="Command"
    )
    assert implicit["calculationContext"] == explicit["calculationContext"] == {
        "groupIndex": group["index"], "activeIndex": command["index"], "skillName": "Command", "source": "pob_main_group",
    }
    assert implicit["stats"]["ManaCost"] == explicit["stats"]["ManaCost"] == stats["ManaCost"]
    assert build_state_hash(engine.get_xml()) == state_hash


def test_real_secondary_comet_audit_retains_selection_through_preflight_and_judge_gate(engine):
    state_hash = _meta_group(engine, secondary=True)
    group, payload = _runtime_output(engine, "Cast on Critical", "Comet")
    result = supportopt.optimize_supports(engine, metric="FullDPS", group_index=group["index"])
    assert result["supportAudit"]["reasonClass"] == "capability_gap"
    assert result["supportAudit"]["activeSkillIndex"] == payload["index"]
    assert result["supportAudit"]["skill"] == "Comet"
    projected = preflight.inspect_generation_snapshot(engine, engine.get_xml())
    projected_group = next(row for row in projected["skillGroups"] if row["groupIndex"] == group["index"])
    assert projected_group["mainActiveSkillCalcs"] == payload["index"]
    support, blockers = _support_result(engine, skill="Spark")
    second = next(row for row in support["groupResults"] if row["groupIndex"] == group["index"])
    assert second["status"] == "unknown", support
    assert second["freshness"] == "current"
    assert second["activeSkillIndex"] == payload["index"]
    # Spark still needs its own final audit; the independently verified Comet must not acquire
    # a false selector mismatch just because checkpoint measures the Spark offense group.
    assert f"skillSupportAudit:support_audit_calculation_context_mismatch:{group['index']}" not in blockers
    assert build_state_hash(engine.get_xml()) == state_hash


@pytest.mark.parametrize("payload", ["Ice Shot", "Lightning Arrow"])
def test_real_unnamed_internal_effect_does_not_detach_mirage_payload_audit(engine, payload):
    engine.new_build()
    engine.set_class("Ranger", "Deadeye")
    engine.set_level(95)
    engine.paste_skill(f"{payload} 20/20 1")
    engine.add_item("Rarity: Normal\nGemini Bow\nItem Level: 82", slot="Weapon 1")
    engine.set_config(custom_mods="+300 to Dexterity")
    engine.add_skill_group(f"Mirage Archer 20/20 1\n{payload} 20/20 1\nElemental Focus")
    group, output = _runtime_output(engine, "Mirage Archer", payload)
    assert any(not effect.get("name") and effect["index"] < output["index"] for effect in group["activeSkills"])
    assert engine.call("set_skill_group_state", index=group["index"], activeSkillIndex=output["index"])["ok"]
    state_hash = build_state_hash(engine.get_xml())
    result = supportopt.optimize_supports(engine, metric="FullDPS", group_index=group["index"])
    assert result["supportAudit"]["activeSkillIndex"] == output["index"]
    assert result["supportAudit"]["skill"] == payload
    assert result["reasonClass"] == "capability_gap", result
    assert result["capability"]["triggerRate"] == "unmodelled"
    assert result["measurement"]["screenedCandidates"] == 0
    assert not supportopt.support_audit_is_complete(result["supportAudit"])
    support, blockers = _support_result(engine, skill=payload)
    second = next(row for row in support["groupResults"] if row["groupIndex"] == group["index"])
    assert second["freshness"] == "current", second
    assert second["activeSkillIndex"] == output["index"]
    assert second["status"] == "unknown"
    assert f"skillSupportAudit:support_audit_calculation_context_mismatch:{group['index']}" not in blockers
    assert build_state_hash(engine.get_xml()) == state_hash


@pytest.mark.parametrize("limit_kind", ["none", "equal", "mana", "spirit", "both"])
def test_real_rate_gap_does_not_override_known_resource_constraints(engine, limit_kind):
    state_hash = _meta_group(engine)
    _, payload = _runtime_output(engine, "Cast on Critical", "Comet")
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
    assert result["supportAudit"]["activeSkillIndex"] == payload["index"]
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
    _, payload = _runtime_output(engine, "Cast on Critical", "Comet")
    original_get_stats = engine.get_stats
    observed_targets = []

    def get_stats(keys=None):
        group, output = _runtime_output(engine, "Cast on Critical", "Comet")
        observed_targets.append((group["mainActiveSkillCalcs"], output["name"]))
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
    assert observed_targets == [(payload["index"], "Comet")]
    assert result["reasonClass"] == reason_class
    assert reason_code in result["supportAudit"]["reasonCodes"]
    assert result["measurement"]["finalConstraintsSatisfied"] is False
    support, blockers = _support_result(engine)
    assert support["status"] == "failed", support
    assert blockers
    assert build_state_hash(engine.get_xml()) == state_hash
