from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from server.generation import evaluation


BUILD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding>
  <Build className="Ranger" ascendClassName="Deadeye" level="68" mainSocketGroup="1" />
  <Skills activeSkillSet="1">
    <SkillSet id="1">
      <Skill enabled="true" mainActiveSkill="1" mainActiveSkillCalcs="1">
        <Gem nameSpec="Lightning Arrow" gemId="Metadata/Items/Gem/SkillGemLightningArrow" skillId="LightningArrowPlayer" />
        <Gem nameSpec="Martial Tempo" gemId="Metadata/Items/Gems/SupportGemMartialTempo" skillId="SupportMartialTempoPlayer" />
      </Skill>
      <Skill enabled="true">
        <Gem nameSpec="Herald of Thunder" gemId="Metadata/Items/Gem/SkillGemHeraldOfThunder" skillId="HeraldOfThunderPlayer" />
      </Skill>
    </SkillSet>
  </Skills>
  <Items activeItemSet="1">
    <ItemSet id="1"><Slot name="Weapon 1" itemId="1" /></ItemSet>
  </Items>
</PathOfBuilding>
"""


def _version_context() -> dict[str, str]:
    return {
        "league": "Dawn of the Hunt",
        "ruleset": "softcore_trade",
        "game_patch": "0.5.4",
        "passive_tree_version": "0_5",
        "pob_version_or_commit": "test",
        "graph_snapshot_id": "graph:test",
        "research_memory_ref": "memory:test",
    }


def _bound_run(tmp_path: Path, monkeypatch) -> tuple[str, str, Path]:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("POE_BD_CREATE_RUNS_DIR", str(runs_dir))
    run_id = str(uuid4())
    token = "test-token"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    output_path = run_dir / "agent-output.json"
    manifest = {
        "schemaVersion": 1,
        "state": "active",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "runContext": {"runId": run_id, "runToken": token},
        "requestRef": f"request:{run_id}",
        "promptId": f"prompt:{run_id}",
        "packetId": f"human-review:{run_id}",
        "agentOutputFile": str(output_path),
    }
    (run_dir / "run-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_id, token, run_dir


class _ActiveEngine:
    def __init__(self, xml: str = BUILD_XML) -> None:
        self.xml = xml

    def get_xml(self) -> str:
        return self.xml


class _JudgeEngine:
    def __init__(self) -> None:
        self.loaded = ""

    def load_build_xml(self, xml: str, name: str) -> None:
        self.loaded = xml

    def get_build(self) -> dict[str, object]:
        return {
            "class": "Ranger",
            "ascendancy": "Deadeye",
            "level": 68,
            "mainSkill": "Lightning Arrow",
            "pointsUsed": 72,
            "pointsAvailable": 76,
            "spiritUsed": 30,
            "spiritAvailable": 100,
            "judgeSelectedSkill": {
                "skillName": "Lightning Arrow",
                "groupIndex": 1,
                "activeSkillCount": 1,
            },
            "judgeSelectedSkillGroup": [
                {"name": "Lightning Arrow", "isSupport": False},
                {"name": "Martial Tempo", "isSupport": True},
            ],
            "attributes": {"strength": 50, "dexterity": 120, "intelligence": 40},
            "attributeRequirements": {
                "strength": 50,
                "dexterity": 120,
                "intelligence": 40,
            },
            "judgeSupplementalSkills": [
                {
                    "skillName": "On Kill Monster Explosion",
                    "groupIndex": 3,
                    "groupOrigin": "synthetic_on_kill",
                    "groupSource": "Explode",
                    "socketLegalityApplicable": False,
                    "scenarioLimitations": ["requires_kill"],
                }
            ],
        }

    def close(self) -> None:
        pass


def _judge_result(snapshot_id: str) -> dict[str, object]:
    return {
        "snapshotId": snapshot_id,
        "pass": True,
        "rewardStrength": "strong",
        "hardFailures": [],
        "caveats": ["projectile_count_lower_bound_caveat"],
        "modelability": {"status": "partial"},
        "scoreVector": {
            "offense": {"value": 0.7, "blocked": False},
            "defense": {"value": 0.6, "blocked": False},
            "recovery": {"value": 0.5, "blocked": False},
            "mobility": {"value": 0.8, "blocked": False},
        },
        "qualityBand": "viable",
        "aggregateScore": {"value": 0.65},
        "levelBand": "maps_entry",
        "reproducibility": {"evaluatorVersion": "judge-test"},
    }


def test_evaluate_generation_candidate_writes_trusted_raw_free_receipt(tmp_path, monkeypatch):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        engine = factory()
        assert engine.loaded == BUILD_XML
        assert source_context == "generated_candidate"
        return _judge_result(snapshot_id)

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)

    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:1",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )

    assert result["status"] == "evaluated"
    assert result["attemptIndex"] == 0
    assert result["trustedEvaluation"] is True
    assert result["trustedEvaluationScope"] == "snapshot_and_judge_only"
    assert result["versionContextTrusted"] is False
    assert result["transientBuildState"]["safeSummary"]["passivePointsUsed"] == "72"
    assert result["transientBuildState"]["testedSkillGroups"][0] == {
        "groupIndex": 1,
        "role": "pob_main_group",
        "activeSkill": "Lightning Arrow",
        "activeSkills": ["Lightning Arrow"],
        "activeSkillCount": 1,
        "supports": ["Martial Tempo"],
        "enabled": True,
    }
    assert result["judgeAdvisoryReport"]["aggregateScore"] == 0.65
    assert result["judgeAdvisoryReport"]["rewardStrength"] == "limited"
    assert result["judgeAdvisoryReport"]["selectedSkill"] == {
        "skillName": "Lightning Arrow",
        "groupIndex": 1,
        "activeSkillCount": 1,
        "groupOrigin": "unknown",
        "groupSource": None,
        "socketLegalityApplicable": True,
        "scenarioLimitations": [],
    }
    assert result["judgeAdvisoryReport"]["skillGroupDiagnostics"][0] == {
        "groupIndex": 1,
        "activeSkills": ["Lightning Arrow"],
        "activeSkillCount": 1,
        "supports": ["Martial Tempo"],
        "supportCount": 1,
        "singleActiveSkillValid": True,
        "groupOrigin": "unknown",
        "groupSource": None,
        "selectedByJudge": True,
    }
    assert result["judgeAdvisoryReport"]["attributeShortfalls"] == []
    assert result["judgeAdvisoryReport"]["supplementalSkills"] == [
        {
            "skillName": "On Kill Monster Explosion",
            "groupIndex": 3,
            "groupOrigin": "synthetic_on_kill",
            "scenarioLimitations": ["requires_kill"],
        }
    ]
    receipt_text = (run_dir / "trusted-evaluation.json").read_text(encoding="utf-8")
    assert "PathOfBuilding" not in receipt_text
    assert "Lightning Arrow" in receipt_text
    assert (run_dir / "trusted-evaluations" / "attempt-0.json").is_file()


def test_evaluate_generation_candidate_rejects_snapshot_without_main_skill(tmp_path, monkeypatch):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)
    xml = BUILD_XML.replace(' mainActiveSkill="1" mainActiveSkillCalcs="1"', "").replace(
        ' mainSocketGroup="1"', ' mainSocketGroup="9"'
    )

    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(xml),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:missing-main",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_active_skill_group"
    assert not (run_dir / "trusted-evaluation.json").exists()


def test_snapshot_roles_only_follow_main_socket_group():
    xml = BUILD_XML.replace(
        '<Skill enabled="true">\n        <Gem nameSpec="Herald of Thunder"',
        '<Skill enabled="true" mainActiveSkill="1" mainActiveSkillCalcs="1">\n        <Gem nameSpec="Herald of Thunder"',
    )

    parsed = evaluation._parse_build_snapshot(xml)

    assert [group["role"] for group in parsed["testedSkillGroups"]] == [
        "pob_main_group",
        "additional_skill_group",
    ]


def test_evaluate_generation_candidate_records_sanitized_judge_error(tmp_path, monkeypatch):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)
    monkeypatch.setattr(
        evaluation.runner,
        "safe_evaluate_active_build",
        lambda *args, **kwargs: {
            "snapshotId": kwargs["snapshot_id"],
            "hardFailures": ["pob_compute_failed"],
            "caveats": ["engine_respawn_required"],
            "errorKind": "TimeoutError",
        },
    )

    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:timeout",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )

    assert result["status"] == "error"
    assert result["judgeAdvisoryReport"]["errorCode"] == "judge_timeout"
    assert result["judgeAdvisoryReport"]["hardFailures"] == []
    assert (run_dir / "trusted-evaluation.json").is_file()


def test_evaluate_generation_candidate_recovers_stale_lock(tmp_path, monkeypatch):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)
    lock_path = run_dir / "evaluation-lock"
    lock_path.write_text("abandoned", encoding="utf-8")
    old_timestamp = datetime.now(timezone.utc).timestamp() - 3600
    os.utime(lock_path, (old_timestamp, old_timestamp))

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        factory()
        return _judge_result(snapshot_id)

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)

    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:stale-lock",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
        timeout_seconds=1.0,
    )

    assert result["status"] == "evaluated"
    assert not lock_path.exists()


def test_evaluate_generation_candidate_rejects_fourth_attempt_before_snapshot(
    tmp_path, monkeypatch
):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)
    receipts_dir = run_dir / "trusted-evaluations"
    receipts_dir.mkdir()
    for index in range(3):
        (receipts_dir / f"attempt-{index}.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "runId": run_id,
                    "attemptIndex": index,
                    "candidateId": f"candidate:{index}",
                    "transientBuildState": {},
                    "judgeAdvisoryReport": {},
                }
            ),
            encoding="utf-8",
        )

    class SnapshotMustNotRun:
        def get_xml(self) -> str:
            raise AssertionError("fourth attempt must be rejected before snapshot")

    result = evaluation.evaluate_generation_candidate(
        SnapshotMustNotRun(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:fourth",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "retry_limit_reached"


def test_evaluate_generation_candidate_reports_multi_active_group_and_attribute_shortfall(
    tmp_path, monkeypatch
):
    run_id, token, _ = _bound_run(tmp_path, monkeypatch)
    xml = BUILD_XML.replace(
        '<Gem nameSpec="Martial Tempo" gemId="Metadata/Items/Gems/SupportGemMartialTempo" skillId="SupportMartialTempoPlayer" />',
        '<Gem nameSpec="Freezing Salvo" gemId="Metadata/Items/Gem/SkillGemFreezingSalvo" skillId="FreezingSalvoPlayer" />',
    )

    class ShortfallJudgeEngine(_JudgeEngine):
        def get_build(self) -> dict[str, object]:
            build = super().get_build()
            build["judgeSelectedSkill"] = {
                "skillName": "Lightning Arrow",
                "groupIndex": 1,
                "activeSkillCount": 2,
            }
            build["judgeSelectedSkillGroup"] = [
                {"name": "Lightning Arrow", "isSupport": False},
                {"name": "Freezing Salvo", "isSupport": False},
            ]
            build["attributes"] = {"strength": 20, "dexterity": 100, "intelligence": 40}
            build["attributeRequirements"] = {
                "strength": 35,
                "dexterity": 100,
                "intelligence": 55,
            }
            return build

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        factory()
        result = _judge_result(snapshot_id)
        result.update(
            {
                "pass": False,
                "hardFailures": ["invalid_socket_setup", "attribute_requirement_unmet"],
                "qualityBand": "invalid",
                "aggregateScore": {"value": 0.0},
            }
        )
        return result

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)
    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(xml),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:diagnostics",
        version_context=_version_context(),
        engine_factory=ShortfallJudgeEngine,
    )

    report = result["judgeAdvisoryReport"]
    assert report["selectedSkill"]["activeSkillCount"] == 2
    assert report["skillGroupDiagnostics"][0]["activeSkills"] == [
        "Lightning Arrow",
        "Freezing Salvo",
    ]
    assert report["skillGroupDiagnostics"][0]["singleActiveSkillValid"] is False
    assert report["attributeShortfalls"] == [
        {"attribute": "strength", "current": 20.0, "required": 35.0, "shortfall": 15.0},
        {
            "attribute": "intelligence",
            "current": 40.0,
            "required": 55.0,
            "shortfall": 15.0,
        },
    ]
