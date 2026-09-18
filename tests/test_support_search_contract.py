from __future__ import annotations

from copy import deepcopy
import time

import pytest

from server.compute import supportopt
from server.compute.engine import PobEngine
from server.compute.state import build_state_hash
from server.compute.support_objectives import inspect_objectives
from server.runtime.compute_control import ComputeControl, ComputeStopped, use_compute_control
from test_support_combination_comparison import CombinationOracle
from test_tree_source_skill_supports import _RuntimeTriggerAuditEngine


@pytest.fixture(autouse=True)
def identities(monkeypatch):
    monkeypatch.setattr(supportopt, "_support_identity_subject", lambda name: {
        "gemIds": ["oracle:" + name], "effectIds": ["effect:" + name],
    })
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Pair A", "Pair B", "Solo C"])


def oracle():
    return CombinationOracle({
        (): 100, ("Pair A",): 90, ("Pair B",): 100,
        ("Solo C",): 110, ("Pair A", "Pair B"): 300,
    })


def objective_capability(*, actor="player", role="duration", effect="SyntheticEffect"):
    return {
        "capabilitySource": "pob_runtime", "selectedEffectId": effect,
        "objectiveContext": {
            "version": 1, "selectedEffectId": effect, "actor": actor,
            "roles": {role: True},
        },
    }


@pytest.mark.parametrize("limits", [{"candidates": 1}, {"screen": 1}, {"max_supports": 1}])
def test_final_rejects_insufficient_coverage_without_candidate_probes(limits):
    engine = oracle()
    before = engine.get_xml()
    result = supportopt.optimize_supports(engine, **limits)
    assert result["errorCode"] == "support_final_audit_coverage_insufficient"
    assert result["candidateProbes"] == 0
    assert engine.probes == []
    assert engine.get_xml() == before
    assert supportopt.support_audit_for_state(engine, build_state_hash(before), 1) is None


def test_native_model_gap_precedes_final_search_coverage(monkeypatch):
    engine = _RuntimeTriggerAuditEngine()
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: pytest.fail("must not enumerate"))
    result = supportopt.optimize_supports(
        engine, metric="FullDPS", max_supports=1, candidates=1, screen=1,
    )
    assert result["supportAudit"]["reasonClass"] == "capability_gap"
    assert result["measurement"]["screenedCandidates"] == 0


def test_exploratory_model_gap_cannot_use_final_gate_exception():
    engine = _RuntimeTriggerAuditEngine()
    result = supportopt.optimize_supports(engine, metric="FullDPS", purpose="exploration")
    audit = supportopt.support_audit_for_state(engine, result["stateHash"], 1)
    assert audit["explorationOnly"] is True
    assert audit["reasonClass"] == "evidence_gap"
    assert "exploration_not_final_audit" in audit["reasonCodes"]
    final = supportopt.optimize_supports(engine, metric="FullDPS")
    assert final["supportAudit"]["reasonClass"] == "capability_gap"


def test_native_gap_and_current_failure_are_not_hidden_by_actor_diagnostic(monkeypatch):
    engine = _RuntimeTriggerAuditEngine()
    original = engine.call

    def call(method, **kwargs):
        result = original(method, **kwargs)
        if method == "inspect_support_evaluation_capability":
            result.update(objective_capability(actor="minion"))
        return result

    monkeypatch.setattr(engine, "call", call)
    result = supportopt.optimize_supports(engine, metric="TotalDPS", candidates=1)
    assert result["errorCode"] == "support_optimization_inconclusive"
    assert result["reasonClass"] == "capability_gap"
    assert result["measurement"]["objectiveDiagnostic"]["errorCode"] == "support_objective_actor_mismatch"
    engine.trigger_rate = "zero_or_inactive"
    failed = supportopt.optimize_supports(engine, metric="TotalDPS", candidates=1)
    assert failed["reasonClass"] == "actionable_gap"
    assert "trigger_rate_zero_or_inactive" in failed["measurement"]["reasonCodes"]
    invalid = supportopt.optimize_supports(engine, metric="Unregistered", candidates=1)
    assert invalid["errorCode"] == "unsupported_support_objective"
    assert invalid["candidateProbes"] == 0


def test_no_supports_precedes_final_search_coverage(monkeypatch):
    engine = oracle()
    original = engine.call

    def call(method, **kwargs):
        result = original(method, **kwargs)
        if method == "list_skill_groups":
            result["groups"][0]["noSupports"] = True
        return result

    monkeypatch.setattr(engine, "call", call)
    result = supportopt.optimize_supports(engine, max_supports=1, candidates=1)
    assert result["errorCode"] == "source_skill_no_supports"
    assert not engine.probes


def test_exploration_does_not_replace_current_final_pass():
    engine = oracle()
    baseline = supportopt.optimize_supports(engine)
    assert baseline["supportAudit"]["status"] == "passed"
    result = supportopt.optimize_supports(engine, purpose="exploration")
    assert result["supportAudit"]["explorationOnly"] is True
    assert result["measurement"]["checkpointEligible"] is False
    assert not supportopt.support_audit_is_complete(result["supportAudit"])
    retained = supportopt.support_audit_for_state(engine, baseline["stateHash"], 1)
    assert retained["auditRef"] == baseline["supportAudit"]["auditRef"]


def test_exploration_current_failure_retains_adverse_evidence(monkeypatch):
    engine = oracle()
    baseline = supportopt.optimize_supports(engine)
    original = engine.load_build_xml

    def load(xml, **kwargs):
        result = original(xml, **kwargs)
        if kwargs.get("name") == "support-current-combination-reset":
            engine.drop_support = "Pair A"
        return result

    monkeypatch.setattr(engine, "load_build_xml", load)
    result = supportopt.optimize_supports(engine, purpose="exploration")
    assert result["measurement"]["currentCombinationFailureCode"]
    retained = supportopt.support_audit_for_state(engine, baseline["stateHash"], 1)
    assert retained["status"] != "passed"
    assert retained["measurement"]["checkpointEligible"] is False


@pytest.mark.parametrize("metric,role", [
    ("Duration", "duration"), ("AreaOfEffectMod", "area"), ("CurseEffectMod", "curse"),
])
def test_utility_needs_exact_runtime_role_and_present_output(metric, role):
    capability = objective_capability(role=role)
    assert inspect_objectives([metric], weighted=False, capability=capability,
                              utility_stats={metric: 2.5}) is None
    wrong_effect = deepcopy(capability)
    wrong_effect["objectiveContext"]["selectedEffectId"] = "OtherEffect"
    assert inspect_objectives([metric], weighted=False, capability=wrong_effect,
                              utility_stats={metric: 2.5})["errorCode"] == "support_objective_role_mismatch"
    capability["objectiveContext"]["roles"] = {}
    assert inspect_objectives([metric], weighted=False, capability=capability,
                              utility_stats={metric: 2.5})["errorCode"] == "support_objective_role_mismatch"
    missing = inspect_objectives([metric], weighted=False,
                                 capability=objective_capability(role=role), utility_stats={})
    assert missing["errorCode"] == "support_objective_output_missing"


def test_wrong_player_damage_actor_rejected_before_candidate_probes(monkeypatch):
    engine = oracle()
    original = engine.call

    def call(method, **kwargs):
        result = original(method, **kwargs)
        if method == "inspect_support_evaluation_capability":
            result.update(objective_capability(actor="minion"))
        return result

    monkeypatch.setattr(engine, "call", call)
    result = supportopt.optimize_supports(engine)
    assert result["errorCode"] == "support_objective_actor_mismatch"
    assert engine.probes == []
    assert inspect_objectives(["TotalDPS"], weighted=False,
                              capability=objective_capability(actor="player"),
                              utility_stats={"TotalDPS": 0}) is None
    assert inspect_objectives(["TotalDPS"], weighted=False,
                              capability=objective_capability(actor="mixed")) is None


def test_preserved_seed_is_memoized_but_final_combination_is_remeasured(monkeypatch):
    engine = oracle()
    original = engine.call

    def call(method, **kwargs):
        result = original(method, **kwargs)
        if method == "inspect_support_evaluation_capability":
            result["usageConditionContracts"] = [{
                "effectId": "SparkPlayer", "supportEffectId": "effect:Pair A",
            }]
        return result

    monkeypatch.setattr(engine, "call", call)
    result = supportopt.optimize_supports(engine)
    assert result["ok"]
    assert engine.probes.count(("Pair A",)) == 1
    assert engine.probes.count(("Pair A", "Pair B")) >= 2


@pytest.mark.parametrize("reason", ["cancelled", "budget_exceeded"])
def test_stop_at_probe_boundary_restores_and_never_publishes(monkeypatch, reason):
    engine = oracle()
    before = engine.get_xml()
    control = ComputeControl(300)
    original = engine.probe_regular_skill_group

    def probe(**kwargs):
        result = original(**kwargs)
        if reason == "cancelled":
            control.cancel()
        else:
            control.deadline = time.monotonic() - 1
        return result

    monkeypatch.setattr(engine, "probe_regular_skill_group", probe)
    with use_compute_control(control), pytest.raises(ComputeStopped) as stopped:
        supportopt.optimize_supports(engine)
    assert stopped.value.reason == reason
    assert engine.get_xml() == before
    assert supportopt.support_audit_for_state(engine, build_state_hash(before), 1) is None


def test_cancellation_before_publication_does_not_sign_final_receipt(monkeypatch):
    engine = oracle()
    before = engine.get_xml()
    control = ComputeControl(300)
    original = engine.load_build_xml

    def load(xml, **kwargs):
        result = original(xml, **kwargs)
        if not kwargs:  # The inner search's final restore, before receipt publication.
            control.cancel()
        return result

    monkeypatch.setattr(engine, "load_build_xml", load)
    with use_compute_control(control), pytest.raises(ComputeStopped):
        supportopt.optimize_supports(engine)
    assert engine.get_xml() == before
    assert supportopt.support_audit_for_state(engine, build_state_hash(before), 1) is None


def test_source_probe_facade_keeps_exact_target_and_single_rpc():
    engine = object.__new__(PobEngine)
    calls = []
    engine.call = lambda method, **kwargs: calls.append((method, kwargs)) or {"ok": True}
    result = engine.probe_source_skill_group(
        group_index=2, source="Tree:123", support_ids=["gem:one"], active_skill_index=3,
        expected_skill_name="Exact Command", expected_effect_id="ExactEffect",
        keys=["MinionTotalDPS"], objective_keys=["MinionTotalDPS"],
    )
    assert result["ok"] and len(calls) == 1
    method, params = calls[0]
    assert method == "probe_source_skill_group"
    assert params["expectedSource"] == "Tree:123"
    assert params["expectedEffectId"] == "ExactEffect"
    assert params["activeSkillIndex"] == 3
