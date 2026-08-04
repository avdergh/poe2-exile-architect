from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from server.generation import artifacts, evaluation, evaluation_snapshots, progression, run_store

from tests.test_phase5_generation_evaluation import (
    BUILD_XML,
    _ActiveEngine,
    _JudgeEngine,
    _judge_result,
    _version_context,
)


def _bound_run(tmp_path: Path, monkeypatch) -> tuple[str, str, Path]:
    runs_dir = tmp_path / "runs"
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setenv("POE_BD_CREATE_RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("POE_BD_FINAL_ARTIFACTS_DIR", str(artifacts_dir))
    run_id = str(uuid4())
    token = "test-token"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "schemaVersion": 1,
        "state": "active",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "runContext": {"runId": run_id, "runToken": token},
        "requestRef": f"request:{run_id}",
        "promptId": f"prompt:{run_id}",
        "packetId": f"human-review:{run_id}",
        "agentOutputFile": str(run_dir / "agent-output.json"),
    }
    (run_dir / "run-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_id, token, run_dir


def _evaluate_passing(tmp_path: Path, monkeypatch) -> tuple[str, str, dict[str, object]]:
    run_id, token, _ = _bound_run(tmp_path, monkeypatch)

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        factory()
        return _judge_result(snapshot_id)

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)
    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )
    return run_id, token, result


class _RestoreEngine:
    def __init__(self) -> None:
        self.loaded_xml = ""

    def load_build_xml(self, xml: str, name: str) -> dict[str, object]:
        self.loaded_xml = xml
        return {"mainSkill": "Lightning Arrow", "treeVersion": "0_5", "stats": {"Life": 1}}


def test_save_list_and_restore_final_build_artifact(tmp_path, monkeypatch):
    run_id, token, evaluation_result = _evaluate_passing(tmp_path, monkeypatch)

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        attempt_index=int(evaluation_result["attemptIndex"]),
    )

    assert saved["status"] == "saved"
    assert saved["containsRawPob"] is False
    assert saved["finalBuildArtifact"]["judgeFeedbackMode"] == "hard_only"
    assert saved["finalBuildArtifact"]["judgeSubjectiveFeedbackSuppressed"] is True
    assert "judgeQualityBand" not in saved["finalBuildArtifact"]
    assert "judgeQualityWarnings" not in saved["finalBuildArtifact"]
    artifact_id = saved["finalBuildArtifact"]["artifactId"]
    progression_fact = progression._trusted_artifact_fact(artifact_id)
    assert progression_fact is not None
    assert progression_fact["judgeFeedbackMode"] == "hard_only"
    assert progression_fact["qualityLimited"] is False
    assert "PathOfBuilding" not in json.dumps(saved)
    artifact_dir = tmp_path / "artifacts" / run_id
    assert (artifact_dir / "build.xml").read_text(encoding="utf-8") == BUILD_XML
    assert "PathOfBuilding" not in (artifact_dir / "manifest.json").read_text(encoding="utf-8")

    listed = artifacts.list_final_build_artifacts()
    assert [item["artifactId"] for item in listed["artifacts"]] == [artifact_id]
    assert "PathOfBuilding" not in json.dumps(listed)

    restore_engine = _RestoreEngine()
    restored = artifacts.load_final_build_artifact(restore_engine, artifact_id=artifact_id)
    assert restored["status"] == "loaded"
    assert restored["activeBuild"] == {
        "mainSkill": "Lightning Arrow",
        "treeVersion": "0_5",
    }
    assert restore_engine.loaded_xml == BUILD_XML
    assert "PathOfBuilding" not in json.dumps(restored)


def test_save_recovers_when_review_was_consumed_before_artifact(tmp_path, monkeypatch):
    run_id, token, evaluation_result = _evaluate_passing(tmp_path, monkeypatch)
    (tmp_path / "runs" / run_id / "review-consumed").write_text(
        "consumed",
        encoding="utf-8",
    )

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        attempt_index=int(evaluation_result["attemptIndex"]),
    )

    assert saved["status"] == "saved"
    assert saved["orderingRecovery"] == {
        "reviewAlreadyConsumed": True,
        "normalOrder": "save_artifact_before_review",
    }
    assert (tmp_path / "artifacts" / run_id / "build.xml").read_text(encoding="utf-8") == BUILD_XML


def test_consumed_review_does_not_weaken_artifact_state_hash_check(tmp_path, monkeypatch):
    run_id, token, evaluation_result = _evaluate_passing(tmp_path, monkeypatch)
    (tmp_path / "runs" / run_id / "review-consumed").write_text(
        "consumed",
        encoding="utf-8",
    )
    changed = BUILD_XML.replace('level="68"', 'level="69"')

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(changed),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        attempt_index=int(evaluation_result["attemptIndex"]),
    )

    assert saved["status"] == "rejected"
    assert saved["errorCode"] == "active_build_changed_after_evaluation"
    assert not (tmp_path / "artifacts").exists()


def test_save_rejects_changed_active_build(tmp_path, monkeypatch):
    run_id, token, result = _evaluate_passing(tmp_path, monkeypatch)
    changed = BUILD_XML.replace('level="68"', 'level="69"')

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(changed),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        attempt_index=int(result["attemptIndex"]),
    )

    assert saved["status"] == "rejected"
    assert saved["errorCode"] == "active_build_changed_after_evaluation"
    assert saved["caveats"] == []
    assert not (tmp_path / "artifacts").exists()


def test_save_restores_latest_passing_snapshot_after_preflight_regression(
    tmp_path,
    monkeypatch,
):
    run_id, token, result = _evaluate_passing(tmp_path, monkeypatch)
    changed = BUILD_XML.replace('level="68"', 'level="69"')

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(changed),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        attempt_index=int(result["attemptIndex"]),
        selection_reason=(
            "The unsaved quality-pass delta failed deterministic preflight after this baseline."
        ),
        later_findings_scope="candidate_delta_only",
    )

    assert saved["status"] == "saved"
    assert saved["artifactSelection"] == {
        "selectionRef": f"artifact-selection:{run_id}:0",
        "selectedAttemptIndex": 0,
        "selectionOutcome": "baseline_restored_after_regression",
        "restoredEarlierBaseline": False,
        "restoredPassingBaseline": True,
    }
    assert (tmp_path / "artifacts" / run_id / "build.xml").read_text(encoding="utf-8") == BUILD_XML


def test_save_uses_exact_judge_snapshot_when_pob_refreshes_derived_output(
    tmp_path,
    monkeypatch,
):
    run_id, token, result = _evaluate_passing(tmp_path, monkeypatch)
    derived_refresh = BUILD_XML.replace(
        '  <Build className="Ranger" ascendClassName="Deadeye" level="68" mainSocketGroup="1" />',
        '  <Build className="Ranger" ascendClassName="Deadeye" level="68" '
        'mainSocketGroup="1"><PlayerStat stat="TotalDPS" value="999" /></Build>',
    )

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(derived_refresh),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        attempt_index=int(result["attemptIndex"]),
    )

    assert saved["status"] == "saved"
    assert (tmp_path / "artifacts" / run_id / "build.xml").read_text(encoding="utf-8") == BUILD_XML


def test_save_fails_closed_when_exact_snapshot_is_gone_and_raw_xml_changed(
    tmp_path,
    monkeypatch,
):
    run_id, token, result = _evaluate_passing(tmp_path, monkeypatch)
    evaluation_snapshots.forget(run_id=run_id)
    derived_refresh = BUILD_XML.replace(
        '  <Build className="Ranger" ascendClassName="Deadeye" level="68" mainSocketGroup="1" />',
        '  <Build className="Ranger" ascendClassName="Deadeye" level="68" '
        'mainSocketGroup="1"><PlayerStat stat="TotalDPS" value="999" /></Build>',
    )

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(derived_refresh),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        attempt_index=int(result["attemptIndex"]),
    )

    assert saved["status"] == "rejected"
    assert saved["errorCode"] == "trusted_evaluation_snapshot_unavailable"
    assert not (tmp_path / "artifacts").exists()


def test_save_rejects_failed_judge_and_does_not_persist_xml(tmp_path, monkeypatch):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        factory()
        result = _judge_result(snapshot_id)
        result["pass"] = False
        result["hardFailures"] = ["invalid_socket_setup"]
        result["aggregateScore"] = {"value": 0.0}
        return result

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)
    evaluated = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:failed",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:failed",
        attempt_index=int(evaluated["attemptIndex"]),
    )

    assert saved["errorCode"] == "final_candidate_not_passed"
    assert "PathOfBuilding" not in (run_dir / "trusted-evaluation.json").read_text(encoding="utf-8")
    assert not (tmp_path / "artifacts").exists()


def test_save_allows_legal_candidate_with_playability_failure(tmp_path, monkeypatch):
    run_id, token, _ = _bound_run(tmp_path, monkeypatch)

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        factory()
        result = _judge_result(snapshot_id)
        result["playabilityFailures"] = ["severe_elemental_resistance_shortfall"]
        result["qualityWarnings"] = ["elemental_resistance_below_cap"]
        return result

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)
    evaluated = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:playability-failed",
        version_context=_version_context(),
        strict_mode=True,
        engine_factory=_JudgeEngine,
    )

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:playability-failed",
        attempt_index=int(evaluated["attemptIndex"]),
    )

    assert evaluated["judgeAdvisoryReport"]["passed"] is True
    assert saved["status"] == "saved"
    assert saved["finalBuildArtifact"]["judgePlayabilityFailures"] == [
        "severe_elemental_resistance_shortfall"
    ]
    assert saved["finalBuildArtifact"]["judgeQualityWarnings"] == ["elemental_resistance_below_cap"]


def test_save_allows_legal_barely_playable_candidate_with_zero_offense(tmp_path, monkeypatch):
    run_id, token, _ = _bound_run(tmp_path, monkeypatch)

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        factory()
        result = _judge_result(snapshot_id)
        result["scoreVector"]["offense"] = {"value": 0.0, "blocked": False}
        result["aggregateScore"] = {"value": 0.29}
        result["qualityBand"] = "barely_playable"
        result["qualityWarnings"] = ["offense_delivery_not_established"]
        return result

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)
    evaluated = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:zero-offense",
        version_context=_version_context(),
        strict_mode=True,
        engine_factory=_JudgeEngine,
    )

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:zero-offense",
        attempt_index=int(evaluated["attemptIndex"]),
    )

    assert evaluated["judgeAdvisoryReport"]["qualityBand"] == "barely_playable"
    assert saved["status"] == "saved"
    assert saved["finalBuildArtifact"]["judgeQualityBand"] == "barely_playable"
    assert saved["finalBuildArtifact"]["judgeQualityWarnings"] == [
        "offense_delivery_not_established"
    ]


def test_save_allows_legal_candidate_when_score_is_unavailable(tmp_path, monkeypatch):
    run_id, token, _ = _bound_run(tmp_path, monkeypatch)

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        factory()
        result = _judge_result(snapshot_id)
        result["modelability"] = {"status": "not_modelable"}
        result["scoreApplicability"] = {"status": "unavailable"}
        return result

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)
    evaluated = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:score-unavailable",
        version_context=_version_context(),
        strict_mode=True,
        engine_factory=_JudgeEngine,
    )

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:score-unavailable",
        attempt_index=int(evaluated["attemptIndex"]),
    )

    assert saved["status"] == "saved"
    assert saved["finalBuildArtifact"]["judgeScoreApplicability"] == "unavailable"


def test_save_rejects_second_artifact_for_same_run(tmp_path, monkeypatch):
    run_id, token, result = _evaluate_passing(tmp_path, monkeypatch)
    args = {
        "run_id": run_id,
        "run_token": token,
        "candidate_id": "candidate:test:final",
        "attempt_index": int(result["attemptIndex"]),
    }

    first = artifacts.save_final_build_artifact(_ActiveEngine(), **args)
    second = artifacts.save_final_build_artifact(_ActiveEngine(), **args)

    assert first["status"] == "saved"
    assert second["errorCode"] == "final_artifact_already_exists"


def test_artifact_selection_receipt_fails_closed_after_binding_tamper(tmp_path, monkeypatch):
    run_id, token, result = _evaluate_passing(tmp_path, monkeypatch)
    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        attempt_index=int(result["attemptIndex"]),
    )
    bound_run = run_store.load_bound_run(run_id, token, require_unconsumed=False)
    selection_path = bound_run.artifact_selection_path
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["selectedEvaluationRef"] = f"run:{run_id}:attempt:2"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")

    assert saved["status"] == "saved"
    assert run_store.read_artifact_selection(bound_run) is None


def test_save_restores_an_older_passing_attempt_after_regression(tmp_path, monkeypatch):
    run_id, token, first = _evaluate_passing(tmp_path, monkeypatch)
    second_xml = BUILD_XML.replace('level="68"', 'level="69"')

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        factory()
        result = _judge_result(snapshot_id)
        result.update(
            {
                "pass": False,
                "hardFailures": ["attribute_requirement_unmet"],
                "qualityBand": "invalid",
            }
        )
        return result

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)
    second = evaluation.evaluate_generation_candidate(
        _ActiveEngine(second_xml),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:second",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(second_xml),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        attempt_index=int(first["attemptIndex"]),
        selection_reason="The quality-pass item delta introduced the later legality regression.",
        later_findings_scope="candidate_delta_only",
    )

    assert second["attemptIndex"] == 1
    assert saved["status"] == "saved"
    assert saved["artifactSelection"]["selectionOutcome"] == "baseline_restored_after_regression"
    assert saved["finalBuildArtifact"]["attemptIndex"] == 0


def test_restore_rejects_corrupt_xml(tmp_path, monkeypatch):
    run_id, token, result = _evaluate_passing(tmp_path, monkeypatch)
    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        attempt_index=int(result["attemptIndex"]),
    )
    artifact_id = saved["finalBuildArtifact"]["artifactId"]
    (tmp_path / "artifacts" / run_id / "build.xml").write_text("<broken>", encoding="utf-8")

    restored = artifacts.load_final_build_artifact(_RestoreEngine(), artifact_id=artifact_id)

    assert restored["errorCode"] == "final_artifact_corrupt"


def test_save_rejects_scaffold_gear_even_after_passing_judge(tmp_path, monkeypatch):
    scaffold_xml = BUILD_XML.replace(
        '  <Items activeItemSet="1">',
        '  <Items activeItemSet="1">\n'
        '    <Item id="1">Rarity: RARE\nScaffold Weapon 1\nAdvanced Dualstring Bow\n'
        "Item Level: 68\nLevelReq: 65</Item>",
    )
    run_id, token, _ = _bound_run(tmp_path, monkeypatch)

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        factory()
        return _judge_result(snapshot_id)

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)
    evaluated = evaluation.evaluate_generation_candidate(
        _ActiveEngine(scaffold_xml),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:scaffold",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )

    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(scaffold_xml),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:scaffold",
        attempt_index=int(evaluated["attemptIndex"]),
    )

    assert saved["errorCode"] == "final_artifact_contains_scaffold_gear"
