"""C1：完整辅助组合的实测回执必须贯通到最终 Checkpoint。"""

from copy import deepcopy

import pytest

from server.compute import supportopt
from server.compute.state import build_state_hash
from server.generation import validation_checkpoint
from test_support_combination_comparison import (
    CombinationOracle,
    oracle_subjects as oracle_subjects,
    run_oracle,
)


def _support_check(engine, *, calculation_context=None):
    group = engine.call("list_skill_groups")["groups"][0]
    checklist = validation_checkpoint._create_quality_checklist(
        engine=engine,
        xml=engine.get_xml(),
        state_hash=build_state_hash(engine.get_xml()),
        build={"level": 80, "gear": {}},
        stats={"ManaCost": 0, "LifeCost": 0, "Mana": 100, "Life": 1000},
        completeness_result={"runes": {"decisionRequiredSlots": []}},
        preflight_result={"skillGroups": [{
            "groupIndex": 1, "role": "pob_main_group", "source": None,
            "mainActiveSkillCalcs": group["mainActiveSkillCalcs"],
            "activeSkills": [skill["name"] for skill in group["activeSkills"]],
        }]},
        calculation_context=calculation_context,
    )
    return checklist["skillSupportAudit"]


def _stored_audit(engine):
    return supportopt._SUPPORT_AUDITS[engine][(build_state_hash(engine.get_xml()), 1)]


def test_checkpoint_accepts_measured_current_complete_combination(monkeypatch):
    engine, result = run_oracle(monkeypatch)
    comparison = result["measurement"]["combinationComparison"]
    assert ("Pair A", "Pair B") in engine.probes
    assert comparison["baselineSupports"] == comparison["candidateSupports"] == ["Pair A", "Pair B"]
    assert comparison["baselineScore"] == comparison["candidateScore"]
    assert supportopt.support_audit_is_complete(result["supportAudit"])
    check = _support_check(engine)
    assert check["status"] == "passed", check
    assert check["reasons"] == []
    assert check["evidenceFreshness"] == {"1": "current"}


@pytest.mark.parametrize("change", [
    {"combinationComparison": {}},
    {"comparison": {"sameContext": False}},
    {"comparison": {"baselineMeasurable": False}},
    {"comparison": {"candidateLegalityNonRegressing": False}},
    {"comparison": {"netGain": None}},
    {"comparison": {"baselineSupports": ["Pair A"]}},
    {"comparison": {"candidateSupports": ["Solo C"]}},
])
def test_screening_complete_cannot_replace_complete_combination_evidence(monkeypatch, change):
    engine, _ = run_oracle(monkeypatch)
    audit = _stored_audit(engine)
    assert audit["status"] == "passed"
    measurement = audit["measurement"]
    if "comparison" in change:
        measurement["combinationComparison"].update(deepcopy(change["comparison"]))
    else:
        measurement.update(deepcopy(change))
    assert measurement["checkpointEligible"] is True
    assert measurement["coverageComplete"] is True
    assert not supportopt.support_audit_is_complete(audit)
    check = _support_check(engine)
    assert check["status"] == "failed", check
    assert "support_audit_invalid:1" in check["reasons"]


def test_checkpoint_treats_v2_audit_as_stale_even_for_unchanged_state(monkeypatch):
    engine, _ = run_oracle(monkeypatch)
    audit = _stored_audit(engine)
    audit["auditVersion"] = "support_audit_v2"
    assert not supportopt.support_audit_is_complete(audit)
    check = _support_check(engine)
    assert check["status"] == "failed", check
    assert check["evidenceFreshness"] == {"1": "stale"}
    assert check["reasons"] == ["support_audit_stale:1"]


@pytest.mark.parametrize("audit_change", [{"activeSkillIndex": 2}, {"skill": "Comet"}])
def test_checkpoint_rejects_complete_audit_for_different_active_effect(monkeypatch, audit_change):
    engine, _ = run_oracle(monkeypatch)
    audit = _stored_audit(engine)
    audit.update(audit_change)
    assert supportopt.support_audit_is_complete(audit)
    check = _support_check(engine)
    assert check["status"] == "failed", check
    assert check["reasons"] == ["support_audit_calculation_context_mismatch:1"]


def test_checkpoint_accepts_complete_audit_bound_to_second_active_effect(monkeypatch):
    engine = CombinationOracle({(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 110}, selected_index=2)
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Pair A", "Pair B", "Solo C"])
    result = supportopt.optimize_supports(engine)
    assert result["supportAudit"]["activeSkillIndex"] == 2
    assert result["supportAudit"]["skill"] == "Comet"
    check = _support_check(engine)
    assert check["status"] == "passed", check
    assert check["groupResults"][0]["activeSkillIndex"] == 2
    mismatch = _support_check(engine, calculation_context={
        "groupIndex": 1, "activeIndex": 1, "skillName": "Spark",
    })
    assert mismatch["status"] == "failed", mismatch
    assert mismatch["reasons"] == ["support_audit_calculation_context_mismatch:1"]


def test_removal_only_positive_gain_blocks_checkpoint_with_actionable_support_names(monkeypatch):
    engine, result = run_oracle(monkeypatch, {
        (): {"ManaCost": 10}, ("Pair A", "Pair B"): {"ManaCost": 30},
        ("Solo C",): {"ManaCost": 20}, ("Pair A", "Pair B", "Solo C"): {"ManaCost": 40},
    }, metric="ManaCost")
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []
    assert result["supportAudit"]["supportsToRemove"] == ["Pair A", "Pair B"]
    assert supportopt.support_audit_is_complete(result["supportAudit"])
    check = _support_check(engine)
    assert check["status"] == "failed", check
    assert check["reasons"] == ["positive_gain_supports_to_remove:1:Pair A,Pair B"]


@pytest.mark.parametrize("explicit_group", [None, 1])
def test_checkpoint_default_stats_selector_uses_main_active_skill_calcs(explicit_group):
    engine = CombinationOracle({("Pair A", "Pair B"): 300}, selected_index=2)
    before = engine.get_xml()
    stats, context = validation_checkpoint._read_target_skill_stats(
        engine, xml=before,
        preflight_result={"skillGroups": [{
            "groupIndex": 1, "role": "pob_main_group", "activeSkills": ["Spark", "Comet"],
            "mainActiveSkillCalcs": 2,
        }]},
        offense_skill_group_index=explicit_group,
        expected_skill_name=None,
    )
    assert "errorCode" not in stats
    assert context == {"groupIndex": 1, "activeIndex": 2, "skillName": "Comet", "source": "pob_main_group"}
    assert engine.selected_index == 2
    assert engine.get_xml() == before
