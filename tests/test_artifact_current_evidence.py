"""Public artifact saving keeps adverse evidence and protects the shared active engine."""

from contextlib import contextmanager
from copy import deepcopy
from threading import Event, RLock, Thread

import pytest

from server import main
from server.compute import craftopt
from server.compute.state import build_state_hash
from server.generation import artifacts, lifecycle_observation, preflight, run_store
from tests import test_generation_mechanism_baseline as baseline_tests
from tests.test_generation_mechanism_baseline import _LifecycleEngine
from tests.test_phase5_generation_evaluation import BUILD_XML, _ActiveEngine


TARGET = {"groupIndex": 1, "activeIndex": 1, "skillName": "Lightning Arrow"}
CHECKS = (
    "skillSupportAudit", "mechanismDependencies", "bootstrapItems", "gearAttainability",
    "charmLoadout", "jewelDecision", "itemSockets", "sustain",
)
RECOVERY = "_poe2_mutation_batch_recovery_required"


def _passing_baseline(tmp_path, monkeypatch, *, initial_sustain="passed"):
    state_hash = build_state_hash(BUILD_XML)
    checked = {
        "status": "ready",
        "stateHash": state_hash,
        "calculationContext": TARGET,
        "preflight": preflight.inspect_generation_snapshot(_ActiveEngine(), BUILD_XML),
        "createQualityChecklist": {
            key: {"status": "passed", "reasons": []} for key in CHECKS
        },
        "deliveryStatus": "recommended" if initial_sustain == "passed" else "candidate",
        "lifecycleVerification": {
            "status": "passed", "pass": True, "stateHash": state_hash,
            "observationTarget": TARGET, "requiredChecks": [], "advisoryChecks": [],
        },
    }
    if initial_sustain != "passed":
        checked["createQualityChecklist"]["sustain"] = {
            "status": initial_sustain, "reasons": ["unmodelled_recovery"],
        }
    assert checked["preflight"]["readyForJudge"]
    monkeypatch.setattr(baseline_tests, "_ActiveEngine", _LifecycleEngine)
    monkeypatch.setattr(
        artifacts.validation_checkpoint, "inspect_generation_checkpoint",
        lambda *_args, **_kwargs: deepcopy(checked),
    )
    bound, token, candidate, evaluated = baseline_tests._baseline(tmp_path, monkeypatch)
    assert evaluated["deliveryStatus"] == checked["deliveryStatus"]
    engine = _LifecycleEngine()
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    return bound, token, candidate, engine, checked


def _public_save(bound, token, candidate, **kwargs):
    return main.save_final_build_artifact(
        bound.run_id, token, candidate.candidate_id, 0, **kwargs
    )


@pytest.mark.parametrize("check_name", ["skillSupportAudit", "jewelDecision", "itemSockets"])
@pytest.mark.parametrize("status", ["failed", "unknown"])
def test_public_save_tightens_current_adverse_quality(
    tmp_path, monkeypatch, check_name, status
):
    bound, token, candidate, engine, checked = _passing_baseline(tmp_path, monkeypatch)
    original_receipt = run_store.read_trusted_evaluations_strict(bound)[0]
    checked["createQualityChecklist"][check_name] = {
        "status": status, "reasons": ["same_state_remeasurement_revoked"],
        "currentAdverseEvidence": True, "evidenceFreshness": {"1": "current"},
    }
    saved = _public_save(bound, token, candidate)
    assert saved["status"] == "saved", saved
    final = saved["finalBuildArtifact"]
    assert final["deliveryStatus"] == "candidate"
    assert final["createQualityChecklist"][check_name]["status"] == status
    assert run_store.read_trusted_evaluations_strict(bound)[0] == original_receipt
    assert engine.get_xml() == BUILD_XML


@pytest.mark.parametrize("freshness", ["missing", "stale"])
@pytest.mark.parametrize("restore_baseline", [False, True])
def test_public_save_keeps_passing_baseline_when_only_quality_cache_is_unavailable(
    tmp_path, monkeypatch, freshness, restore_baseline
):
    bound, token, candidate, engine, checked = _passing_baseline(tmp_path, monkeypatch)
    original = deepcopy(checked["createQualityChecklist"])
    for name in ("skillSupportAudit", "jewelDecision", "itemSockets"):
        checked["createQualityChecklist"][name] = {
            "status": "failed", "reasons": [f"audit_{freshness}"],
            "currentAdverseEvidence": False, "evidenceFreshness": {"1": freshness},
        }
    selection = {}
    if restore_baseline:
        engine.xml = BUILD_XML.replace('level="68"', 'level="69"')
        selection = {
            "selection_reason": "新增候选的变更不影响所选基线。",
            "later_findings_scope": "candidate_delta_only",
        }
    saved = _public_save(bound, token, candidate, **selection)
    assert saved["status"] == "saved", saved
    assert saved["finalBuildArtifact"]["deliveryStatus"] == "recommended"
    assert saved["finalBuildArtifact"]["createQualityChecklist"] == original
    assert saved["artifactSelection"]["restoredPassingBaseline"] is restore_baseline


def test_public_save_does_not_promote_previous_unknown_quality(tmp_path, monkeypatch):
    bound, token, candidate, _engine, checked = _passing_baseline(
        tmp_path, monkeypatch, initial_sustain="unknown"
    )
    checked["createQualityChecklist"]["sustain"] = {
        "status": "passed", "reasons": [], "currentAdverseEvidence": False,
    }
    saved = _public_save(bound, token, candidate)
    assert saved["status"] == "saved", saved
    assert saved["finalBuildArtifact"]["deliveryStatus"] == "candidate"
    assert saved["finalBuildArtifact"]["createQualityChecklist"]["sustain"] == {
        "status": "unknown", "reasons": ["unmodelled_recovery"],
    }


def test_public_socket_remeasurement_revocation_reaches_saved_artifact(tmp_path, monkeypatch):
    bound, token, candidate, engine, checked = _passing_baseline(tmp_path, monkeypatch)
    measurement = {
        "ok": True, "changed": False, "reason": "no_beneficial_socket_option",
        "measurementStatus": "no_positive", "measurementComplete": True,
    }
    monkeypatch.setattr(
        craftopt, "_optimize_item_sockets_locked",
        lambda *_args, **_kwargs: deepcopy(measurement),
    )
    first = craftopt.optimize_item_sockets(
        engine, slot="Helmet", goals={"Life": 1}, socket_count=1
    )
    assert first["ok"] is True
    measurement.update(ok=False, errorCode="socket_probe_failed", measurementStatus="measurement_error")
    retried = craftopt.optimize_item_sockets(
        engine, slot="Helmet", goals={"Life": 1}, socket_count=1
    )
    assert retried["ok"] is False and retried["rolledBack"] is True
    quality = artifacts.validation_checkpoint._create_quality_checklist(
        engine=engine, xml=BUILD_XML, state_hash=build_state_hash(BUILD_XML),
        build={"level": 68, "gear": {"Helmet": {"rarity": "rare"}}},
        stats={"ManaCost": 0},
        completeness_result={"runes": {"decisionRequiredSlots": ["Helmet"]}},
        preflight_result={}, calculation_context=TARGET,
    )
    assert quality["itemSockets"]["status"] == "failed"
    assert quality["itemSockets"]["currentAdverseEvidence"] is True
    checked["createQualityChecklist"]["itemSockets"] = quality["itemSockets"]
    saved = _public_save(bound, token, candidate)
    assert saved["status"] == "saved", saved
    assert saved["finalBuildArtifact"]["deliveryStatus"] == "candidate"
    assert saved["finalBuildArtifact"]["createQualityChecklist"]["itemSockets"] == quality["itemSockets"]


def test_public_save_rejects_current_hard_legality_failure(tmp_path, monkeypatch):
    bound, token, candidate, _engine, checked = _passing_baseline(tmp_path, monkeypatch)
    checked["hardLegality"] = {
        "status": "failed", "stateHash": build_state_hash(BUILD_XML),
        "hardFailures": ["spirit_budget_exceeded"],
    }
    checked["hardLegalityReady"] = False
    saved = _public_save(bound, token, candidate)
    assert saved["errorCode"] == "final_candidate_hard_legality_not_verified"
    assert not bound.artifact_selection_path.exists()


def test_explicit_lifecycle_declaration_revocation_tightens_saved_artifact(tmp_path, monkeypatch):
    bound, token, candidate, engine, checked = _passing_baseline(tmp_path, monkeypatch)
    declarations = {
        "buildDefiningComponentKind": "skill",
        "buildDefiningComponentName": "Lightning Arrow",
        "buildDefiningComponentKey": "skill:lightning-arrow",
        "buildDefiningEvidenceRefs": ["graph:lightning-arrow"],
    }
    state_hash = build_state_hash(BUILD_XML)
    stats = {"Life": 5000, "Mana": 600, "ManaUnreserved": 600, "ManaCost": 20,
             "Speed": 2, "NetManaRegen": 60, "TotalDPS": 10000}
    defenses = {"resistances": {"fire": 75, "cold": 75, "lightning": 75}, "totalEHP": 25000}

    def observe():
        return artifacts.validation_checkpoint.recheck_lifecycle_verification(
            engine, xml=BUILD_XML, build=engine.get_build(), stats=stats,
            defenses=defenses, observation_target=TARGET,
        )

    assert lifecycle_observation.remember_state(
        engine, state_hash=state_hash, observation_target=TARGET, state=declarations,
    )
    assert observe()["pass"] is True
    assert lifecycle_observation.remember_state(
        engine, state_hash=state_hash, observation_target=TARGET, state={},
    )
    revoked = observe()
    assert revoked["pass"] is False
    assert revoked["unknownChecks"] == ["build_defining_component_online"]
    checked["lifecycleVerification"] = revoked
    saved = _public_save(bound, token, candidate)
    assert saved["status"] == "saved", saved
    assert saved["finalBuildArtifact"]["deliveryStatus"] == "candidate"
    assert saved["finalBuildArtifact"]["lifecycleVerification"]["pass"] is False
    manifest, xml = artifacts.read_final_build_artifact_for_export(
        saved["finalBuildArtifact"]["artifactId"]
    )
    assert artifacts.read_artifact_lifecycle_declarations(manifest, xml) == (
        lifecycle_observation.declaration_payload({})
    )


@pytest.mark.parametrize("step", ["round-trip", "lifecycle"])
@pytest.mark.parametrize("failure", ["exception", "wrong_hash"])
def test_public_save_restore_failure_blocks_following_socket_and_save(
    tmp_path, monkeypatch, step, failure
):
    bound, token, candidate, engine, _checked = _passing_baseline(tmp_path, monkeypatch)
    original_load = engine.load_build_xml

    def broken_restore(xml, name=""):
        if name == f"final-artifact-{step}-restore":
            if failure == "exception":
                raise RuntimeError("injected restore failure")
            xml = xml.replace('level="68"', 'level="69"')
        original_load(xml, name)

    monkeypatch.setattr(engine, "load_build_xml", broken_restore)
    saved = _public_save(bound, token, candidate)
    assert saved["recoveryRequired"] is True
    assert getattr(engine, RECOVERY) is True
    assert not bound.artifact_selection_path.exists()
    assert not (artifacts.artifacts_dir() / bound.run_id).exists()

    def forbidden_probe(*_args, **_kwargs):
        pytest.fail("residual state cannot become a socket measurement input")

    monkeypatch.setattr(craftopt, "_optimize_item_sockets_locked", forbidden_probe)
    following = craftopt.optimize_item_sockets(
        engine, slot="Helmet", goals={"Life": 1}, socket_count=1
    )
    assert following["errorCode"] == "build_state_recovery_required"
    assert _public_save(bound, token, candidate)["errorCode"] == "build_state_recovery_required"
    assert getattr(engine, RECOVERY) is True


def test_public_save_rechecks_recovery_after_waiting_for_engine_lock(tmp_path, monkeypatch):
    bound, token, candidate, _engine, _checked = _passing_baseline(tmp_path, monkeypatch)

    class WaitingEngine(_LifecycleEngine):
        def __init__(self):
            super().__init__()
            self.lock = RLock()
            self.waiting = Event()

        @contextmanager
        def transaction_lock(self):
            self.waiting.set()
            with self.lock:
                yield

    engine = WaitingEngine()
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    responses = []
    with engine.lock:
        worker = Thread(target=lambda: responses.append(_public_save(bound, token, candidate)))
        worker.start()
        assert engine.waiting.wait(5)
        setattr(engine, RECOVERY, True)
    worker.join(5)
    assert not worker.is_alive()
    assert responses[0]["errorCode"] == "build_state_recovery_required"
    assert engine.get_xml_calls == 0
    assert not bound.artifact_selection_path.exists()


def test_artifact_saves_typed_declarations_and_returns_checked_copy(tmp_path, monkeypatch):
    bound, token, candidate, engine, _checked = _passing_baseline(tmp_path, monkeypatch)
    declaration = {
        "buildDefiningComponentKind": "skill",
        "buildDefiningComponentName": "Lightning Arrow",
        "buildDefiningComponentKey": "skill:lightning-arrow",
        "buildDefiningEvidenceRefs": ["graph:lightning-arrow"],
    }
    assert lifecycle_observation.remember_state(
        engine, state_hash=build_state_hash(BUILD_XML), observation_target=TARGET,
        state=declaration,
    )
    saved = _public_save(bound, token, candidate)
    assert saved["status"] == "saved", saved
    manifest, xml = artifacts.read_final_build_artifact_for_export(
        saved["finalBuildArtifact"]["artifactId"]
    )
    binding = manifest.lifecycle_declaration_binding
    assert binding["stateHash"] == build_state_hash(xml)
    assert binding["observationTarget"] == TARGET
    assert "pass" not in binding and "xml" not in binding
    expected = lifecycle_observation.declaration_payload(declaration)
    assert artifacts.read_artifact_lifecycle_declarations(manifest, xml) == expected
    assert "lifecycleDeclarationBinding" not in saved["finalBuildArtifact"]
    assert artifacts.read_artifact_lifecycle_declarations(
        manifest, xml.replace('level="68"', 'level="69"')
    ) is None
    for change in (
        {"stateHash": "sha256:" + "0" * 64},
        {"observationTarget": {**TARGET, "activeIndex": 2}},
        {"declarations": {"pass": True}},
        {"observationVersion": "legacy"},
    ):
        invalid = manifest.model_copy(update={"lifecycle_declaration_binding": {**binding, **change}})
        assert artifacts.read_artifact_lifecycle_declarations(invalid, xml) is None
    legacy = manifest.model_copy(update={"lifecycle_declaration_binding": None})
    assert artifacts.read_artifact_lifecycle_declarations(legacy, xml) is None
