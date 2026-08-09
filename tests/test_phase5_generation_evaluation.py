from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from server.compute.state import build_state_hash
from server.generation import evaluation, evaluation_snapshots, run_store
from server.knowledge import research_memory


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
        "research_memory_ref": "dq-0123456789abcdef",
    }


@pytest.fixture(autouse=True)
def _fresh_research_receipts(monkeypatch):
    """Evaluate now fail-fasts on run-fresh dq- receipts; default every test to a fresh one."""

    def fake_reader(_self, _ref: str) -> dict[str, object]:
        return {"lastSeenAt": datetime.now(timezone.utc).isoformat()}

    monkeypatch.setattr(
        research_memory.ResearchMemoryService,
        "read_query_receipt",
        fake_reader,
    )


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
    def __init__(
        self,
        xml: str = BUILD_XML,
        *,
        build: dict[str, object] | None = None,
        resistances: dict[str, float] | None = None,
    ) -> None:
        self.xml = xml
        self.get_xml_calls = 0
        self.build = build or {"class": "Ranger", "level": 68, "gear": {}}
        self.resistances = resistances or {
            "fire": 75,
            "cold": 75,
            "lightning": 75,
            "chaos": 75,
        }

    def get_xml(self) -> str:
        self.get_xml_calls += 1
        return self.xml

    def get_build(self) -> dict[str, object]:
        return self.build

    def list_jewel_sockets(self) -> dict[str, object]:
        return {"sockets": []}

    def get_defenses(self) -> dict[str, object]:
        return {"resistances": self.resistances}


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
        result = _judge_result(snapshot_id)
        result["rewardLimitReasons"] = ["limited_evidence", "offense_delivery_evidence"]
        result["scoreBreakdown"] = {
            "offense": {
                "rawValue": 42_000,
                "rawDps": 42_000,
                "effectiveDps": 42_000,
                "directDps": 42_000,
                "fullDps": 42_000,
                "sourceMetricDetail": "FullDPS",
                "evidenceLevel": "limited",
                "metricStatus": "available",
                "observedValue": 0.0,
                "floorProgress": 0.84,
                "floorStatus": "unverified",
                "deliveryEvidenceStatus": "limited",
                "scoreConfidenceFactor": 0.5,
                "scorePolicy": "stage_curve_confidence_adjusted",
            }
        }
        return result

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)

    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:1",
        version_context=_version_context(),
        strict_mode=True,
        engine_factory=_JudgeEngine,
    )

    assert result["status"] == "evaluated"
    assert result["attemptIndex"] == 0
    assert result["trustedEvaluation"] is True
    assert result["trustedEvaluationScope"] == "snapshot_and_judge_only"
    assert result["versionContextTrusted"] is False
    assert result["transientBuildState"]["semanticStateHash"] == build_state_hash(BUILD_XML)
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
    assert result["judgeAdvisoryReport"]["playabilityFailures"] == []
    assert result["judgeAdvisoryReport"]["qualityWarnings"] == []
    assert result["judgeAdvisoryReport"]["scoreApplicability"] == "applicable"
    assert result["judgeAdvisoryReport"]["rewardStrength"] == "limited"
    assert result["judgeAdvisoryReport"]["rewardLimitReasons"] == [
        "limited_evidence",
        "offense_delivery_evidence",
    ]
    assert result["judgeAdvisoryReport"]["offenseEvidence"] == {
        "rawDps": 42_000.0,
        "effectiveDps": 42_000.0,
        "directDps": 42_000.0,
        "fullDps": 42_000.0,
        "sourceMetric": "FullDPS",
        "evidenceLevel": "limited",
        "metricStatus": "available",
        "observedValue": 0.0,
        "floorProgress": 0.84,
        "floorStatus": "unverified",
        "deliveryEvidenceStatus": "limited",
        "scoreConfidenceFactor": 0.5,
        "scorePolicy": "stage_curve_confidence_adjusted",
    }
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
    assert result["judgeAdvisoryReport"]["feedbackMode"] == "strict"
    assert result["judgeAdvisoryReport"]["subjectiveFeedbackSuppressed"] is False
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
    remembered = evaluation_snapshots.read(
        run_id=run_id,
        attempt_index=0,
        candidate_id="candidate:test:1",
        source_hash=result["transientBuildState"]["sourceHash"],
    )
    assert remembered is not None
    assert remembered.xml == BUILD_XML
    assert not list(run_dir.rglob("*.xml"))


def test_evaluate_generation_candidate_defaults_to_hard_only_feedback(tmp_path, monkeypatch):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        factory()
        result = _judge_result(snapshot_id)
        result["playabilityFailures"] = ["subjective_playability_failure"]
        result["qualityWarnings"] = ["subjective_quality_warning"]
        result["rewardLimitReasons"] = ["limited_evidence"]
        return result

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)

    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:hard-only",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )

    report = result["judgeAdvisoryReport"]
    assert result["feedbackMode"] == "hard_only"
    assert result["subjectiveFeedbackSuppressed"] is True
    assert report["feedbackMode"] == "hard_only"
    assert report["subjectiveFeedbackSuppressed"] is True
    assert report["passed"] is True
    assert report["hardFailures"] == []
    assert report["aggregateScore"] is None
    assert report["playabilityFailures"] == []
    assert report["qualityWarnings"] == []
    assert report["caveats"] == []
    assert report["rewardStrength"] == "unknown"
    assert report["rewardLimitReasons"] == []
    assert report["qualityBand"] is None
    assert report["scoreVector"] is None
    assert report["offenseEvidence"] is None
    assert report["modelabilityStatus"] is None
    assert report["scoreApplicability"] == "unknown"
    assert report["selectedSkill"]["skillName"] == "Lightning Arrow"
    receipt_text = (run_dir / "trusted-evaluation.json").read_text(encoding="utf-8")
    assert "subjective_playability_failure" not in receipt_text
    assert "subjective_quality_warning" not in receipt_text
    assert "projectile_count_lower_bound_caveat" not in receipt_text


def test_evaluate_generation_candidate_rejects_feedback_mode_change_without_consuming_attempt(
    tmp_path,
    monkeypatch,
):
    run_id, token, _ = _bound_run(tmp_path, monkeypatch)
    monkeypatch.setattr(
        evaluation.runner,
        "safe_evaluate_active_build",
        lambda factory, **kwargs: _judge_result(kwargs["snapshot_id"]),
    )
    first = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:mode-lock",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )
    assert first["attemptIndex"] == 0

    mismatch = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:mode-lock:strict",
        version_context=_version_context(),
        strict_mode=True,
        engine_factory=_JudgeEngine,
    )

    assert mismatch["status"] == "rejected"
    assert mismatch["errorCode"] == "judge_feedback_mode_mismatch"
    assert mismatch["expectedFeedbackMode"] == "hard_only"
    assert mismatch["actualFeedbackMode"] == "strict"
    assert mismatch["attemptConsumed"] is False
    assert mismatch["attemptCount"] == 1


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
    assert result["errorCode"] == "generation_preflight_failed"
    assert result["preflight"]["blockingIssues"] == ["missing_active_skill_group"]
    assert not (run_dir / "trusted-evaluation.json").exists()


def test_generation_preflight_blocks_duplicate_group_without_consuming_attempt(
    tmp_path, monkeypatch
):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)
    duplicate = BUILD_XML.replace(
        "</SkillSet>",
        """<Skill enabled="true">
        <Gem nameSpec="Lightning Arrow" gemId="Metadata/Items/Gem/SkillGemLightningArrow" skillId="LightningArrowPlayer" />
        <Gem nameSpec="Martial Tempo" gemId="Metadata/Items/Gems/SupportGemMartialTempo" skillId="SupportMartialTempoPlayer" />
      </Skill></SkillSet>""",
    )
    active = _ActiveEngine(duplicate)
    factory_called = False

    def factory():
        nonlocal factory_called
        factory_called = True
        return _JudgeEngine()

    result = evaluation.evaluate_generation_candidate(
        active,
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:duplicate",
        version_context=_version_context(),
        engine_factory=factory,
    )

    assert result["errorCode"] == "generation_preflight_failed"
    assert result["preflight"]["blockingIssues"] == ["duplicate_enabled_skill_group"]
    assert active.get_xml_calls == 1
    assert factory_called is False
    assert not (run_dir / "trusted-evaluations").exists()


def test_attribute_shortfall_is_blocked_without_consuming_a_judge_attempt(
    tmp_path,
    monkeypatch,
):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)
    active = _ActiveEngine(
        build={
            "class": "Ranger",
            "ascendancy": "Deadeye",
            "level": 68,
            "gear": {},
            "attributes": {
                "strength": 50,
                "dexterity": 120,
                "intelligence": 72,
            },
            "attributeRequirements": {
                "strength": 50,
                "dexterity": 120,
                "intelligence": 80,
            },
        }
    )
    factory_called = False

    def factory():
        nonlocal factory_called
        factory_called = True
        return _JudgeEngine()

    first = evaluation.evaluate_generation_candidate(
        active,
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:attribute-shortfall",
        version_context=_version_context(),
        engine_factory=factory,
    )
    second = evaluation.evaluate_generation_candidate(
        active,
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:attribute-shortfall",
        version_context=_version_context(),
        engine_factory=factory,
    )

    for result in (first, second):
        assert result["errorCode"] == "generation_preflight_failed"
        assert result["attemptConsumed"] is False
        assert result["attemptCount"] == 0
        assert result["preflight"]["hardLegalityReady"] is False
        assert result["preflight"]["mechanismReady"] is True
        assert result["preflight"]["blockingIssues"] == ["attribute_requirement_unmet"]
    assert factory_called is False
    assert not (run_dir / "trusted-evaluations").exists()


def test_generated_delivery_omissions_are_blocked_before_judge_without_consuming_attempt(
    tmp_path,
    monkeypatch,
):
    cases = [
        (
            "scaffold",
            "Rarity: RARE\nScaffold Weapon 1\nAdvanced Dualstring Bow\n"
            "Item Level: 68\nLevelReq: 60",
            "scaffold_gear_must_be_replaced",
        ),
        (
            "missing-item-level",
            "Rarity: RARE\nGenerated Weapon\nAdvanced Dualstring Bow\nLevelReq: 60",
            "rare_or_magic_item_level_missing",
        ),
    ]
    for suffix, item_text, expected_failure in cases:
        run_id, token, run_dir = _bound_run(tmp_path / suffix, monkeypatch)
        xml = BUILD_XML.replace(
            '  <Items activeItemSet="1">',
            f'  <Items activeItemSet="1">\n    <Item id="1">{item_text}</Item>',
        )
        factory_called = False

        def factory():
            nonlocal factory_called
            factory_called = True
            return _JudgeEngine()

        result = evaluation.evaluate_generation_candidate(
            _ActiveEngine(xml),
            run_id=run_id,
            run_token=token,
            candidate_id=f"candidate:test:{suffix}",
            version_context=_version_context(),
            engine_factory=factory,
        )

        assert result["errorCode"] == "generation_preflight_failed"
        assert result["attemptConsumed"] is False
        assert result["attemptCount"] == 0
        assert expected_failure in result["preflight"]["blockingIssues"]
        assert expected_failure in result["preflight"]["hardLegality"]["hardFailures"]
        assert factory_called is False
        assert not (run_dir / "trusted-evaluations").exists()


def test_endgame_resistance_shortfall_is_blocked_without_consuming_a_judge_attempt(
    tmp_path,
    monkeypatch,
):
    run_id, token, run_dir = _bound_run(tmp_path, monkeypatch)
    active = _ActiveEngine(
        build={
            "class": "Ranger",
            "ascendancy": "Deadeye",
            "level": 85,
            "gear": {},
        },
        resistances={"fire": 60, "cold": 59, "lightning": 60, "chaos": 29},
    )
    factory_called = False

    def factory():
        nonlocal factory_called
        factory_called = True
        return _JudgeEngine()

    result = evaluation.evaluate_generation_candidate(
        active,
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:endgame-resistance-shortfall",
        version_context=_version_context(),
        engine_factory=factory,
    )

    assert result["errorCode"] == "generation_preflight_failed"
    assert result["attemptConsumed"] is False
    assert result["attemptCount"] == 0
    assert result["preflight"]["readinessReady"] is False
    assert result["preflight"]["blockingIssues"] == [
        "endgame_elemental_resistance_below_60",
        "endgame_chaos_resistance_below_30",
    ]
    assert factory_called is False
    assert not (run_dir / "trusted-evaluations").exists()


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
    bound = run_store.BoundRun(run_id=run_id, run_dir=run_dir, manifest={})
    version = _version_context()
    for index in range(3):
        snapshot = f"generation:test:{index}"
        source_hash = f"source-hash-{index}"
        assert (
            run_store.write_trusted_evaluation(
                bound,
                {
                    "candidateId": f"candidate:{index}",
                    "transientBuildState": {
                        "status": "available",
                        "snapshotId": snapshot,
                        "sourceHash": source_hash,
                        "safeSummary": {},
                        "testedSkillGroups": [
                            {
                                "groupIndex": 1,
                                "role": "pob_main_group",
                                "activeSkill": "Lightning Arrow",
                                "activeSkills": ["Lightning Arrow"],
                                "activeSkillCount": 1,
                                "supports": [],
                                "enabled": True,
                            }
                        ],
                        "missingReasons": [],
                        "versionContext": version,
                        "noRawMaterial": True,
                    },
                    "judgeAdvisoryReport": {
                        "reportId": f"judge:{snapshot}",
                        "status": "evaluated",
                        "hardFailures": [],
                        "caveats": [],
                        "aggregateScore": 0.5,
                        "rewardStrength": "limited",
                        "evaluatedSnapshotId": snapshot,
                        "evaluatedSourceHash": source_hash,
                        "passed": True,
                        "versionContext": version,
                        "noRawMaterial": True,
                    },
                },
            )
            == index
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


def test_evaluate_generation_candidate_reports_attribute_shortfall(tmp_path, monkeypatch):
    run_id, token, _ = _bound_run(tmp_path, monkeypatch)

    class ShortfallJudgeEngine(_JudgeEngine):
        def get_build(self) -> dict[str, object]:
            build = super().get_build()
            build["judgeSelectedSkill"] = {
                "skillName": "Lightning Arrow",
                "groupIndex": 1,
                "activeSkillCount": 1,
            }
            build["judgeSelectedSkillGroup"] = [
                {"name": "Lightning Arrow", "isSupport": False},
                {"name": "Martial Tempo", "isSupport": True},
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
                "hardFailures": ["attribute_requirement_unmet"],
                "qualityBand": "invalid",
                "aggregateScore": {"value": 0.0},
            }
        )
        return result

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)
    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:diagnostics",
        version_context=_version_context(),
        engine_factory=ShortfallJudgeEngine,
    )

    report = result["judgeAdvisoryReport"]
    assert report["selectedSkill"]["activeSkillCount"] == 1
    assert report["skillGroupDiagnostics"][0]["activeSkills"] == ["Lightning Arrow"]
    assert report["skillGroupDiagnostics"][0]["singleActiveSkillValid"] is True
    assert report["attributeShortfalls"] == [
        {"attribute": "strength", "current": 20.0, "required": 35.0, "shortfall": 15.0},
        {
            "attribute": "intelligence",
            "current": 40.0,
            "required": 55.0,
            "shortfall": 15.0,
        },
    ]


def test_evaluate_rejects_missing_research_receipt_before_consuming_attempt(tmp_path, monkeypatch):
    run_id, token, _run_dir = _bound_run(tmp_path, monkeypatch)

    def missing_reader(_self, _ref: str) -> dict[str, object] | None:
        return None

    monkeypatch.setattr(
        research_memory.ResearchMemoryService,
        "read_query_receipt",
        missing_reader,
    )

    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:missing-receipt",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )

    assert result["errorCode"] == "research_memory_receipt_missing"
    assert result["attemptConsumed"] is False


def test_evaluate_rejects_stale_research_receipt_before_consuming_attempt(tmp_path, monkeypatch):
    run_id, token, _run_dir = _bound_run(tmp_path, monkeypatch)

    def stale_reader(_self, _ref: str) -> dict[str, object]:
        return {"lastSeenAt": "2000-01-01T00:00:00+00:00"}

    monkeypatch.setattr(
        research_memory.ResearchMemoryService,
        "read_query_receipt",
        stale_reader,
    )

    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:stale-receipt",
        version_context=_version_context(),
        engine_factory=_JudgeEngine,
    )

    assert result["errorCode"] == "research_memory_receipt_not_current_run"
    assert result["attemptConsumed"] is False


def test_evaluate_rejects_non_dq_research_ref(tmp_path, monkeypatch):
    run_id, token, _run_dir = _bound_run(tmp_path, monkeypatch)
    context = _version_context()
    context["research_memory_ref"] = "memory:test"

    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:bad-ref",
        version_context=context,
        engine_factory=_JudgeEngine,
    )

    assert result["errorCode"] == "invalid_research_memory_ref"
    assert result["attemptConsumed"] is False


def test_evaluate_allows_disabled_no_memory_ref(tmp_path, monkeypatch):
    run_id, token, _run_dir = _bound_run(tmp_path, monkeypatch)
    context = _version_context()
    context["research_memory_ref"] = "disabled:no_memory_baseline"

    def fail_if_called(_self, _ref: str) -> dict[str, object]:
        raise AssertionError("no_memory baseline must skip receipt lookup")

    monkeypatch.setattr(
        research_memory.ResearchMemoryService,
        "read_query_receipt",
        fail_if_called,
    )

    def fake_safe(factory, *, snapshot_id, timeout_seconds, source_context):
        factory()
        return _judge_result(snapshot_id)

    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", fake_safe)

    result = evaluation.evaluate_generation_candidate(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:no-memory",
        version_context=context,
        engine_factory=_JudgeEngine,
    )

    assert result["status"] == "evaluated"
    assert result["attemptIndex"] == 0
