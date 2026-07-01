from __future__ import annotations

import subprocess
import sys

from scripts import run_judge_user_samples


def test_user_sample_report_sanitizes_raw_source(tmp_path, monkeypatch):
    sample = tmp_path / "samples.txt"
    sample.write_text("fake-pob-code\n", encoding="utf-8")

    def fake_evaluate_source(source: str, snapshot_id: str):
        assert source == "fake-pob-code"
        return {
            "snapshotId": snapshot_id,
            "sourceHash": "abc123",
            "summary": {
                "class": "Mercenary",
                "ascendancy": "Witchhunter",
                "mainSkill": "Dread Banner",
                "judgeSelectedSkill": "Molten Crash",
                "level": 100,
            },
            "scoreVector": {},
            "scoreBreakdown": {"offense": {"rawValue": 1}},
            "scoreScale": "0_to_1",
            "qualityBand": "entry_endgame",
            "hardFailures": [],
            "defenseModel": {"poolModel": "life", "confidence": "full"},
            "modelability": {"status": "full"},
            "caveats": [],
            "rewardStrength": "strong",
        }

    monkeypatch.setattr(run_judge_user_samples, "evaluate_source", fake_evaluate_source)

    report = run_judge_user_samples.build_report(sample)

    assert report["samples"][0]["sourceHash"] == "abc123"
    assert report["samples"][0]["summary"]["judgeSelectedSkill"] == "Molten Crash"
    assert report["samples"][0]["scoreScale"] == "0_to_1"
    assert report["samples"][0]["scoreBreakdown"]["offense"]["rawValue"] == 1
    assert report["samples"][0]["defenseModel"]["poolModel"] == "life"
    assert report["samples"][0]["rewardStrength"] == "strong"
    serialized = str(report)
    assert "fake-pob-code" not in serialized
    assert "rawXml" not in serialized


def test_user_sample_report_includes_sanitized_regression_matrix(tmp_path, monkeypatch):
    sample = tmp_path / "samples.txt"
    sample.write_text("fake-pob-code\n", encoding="utf-8")

    def fake_evaluate_source(_source: str, snapshot_id: str):
        return {
            "snapshotId": snapshot_id,
            "sourceHash": "abc123",
            "summary": {
                "class": "Witch",
                "ascendancy": "Infernalist",
                "mainSkill": "Raise Skeletons",
                "judgeSelectedSkill": "Raise Skeletons",
                "level": 100,
            },
            "scoreBreakdown": {
                "offense": {
                    "provenance": "minion_pob_output",
                    "evidenceLevel": "limited",
                    "skillName": "Raise Skeletons",
                    "sourceMetricDetail": "MinionTotalDPS",
                }
            },
            "defenseModel": {"poolModel": "hybrid", "confidence": "partial"},
            "hardFailures": [],
            "physicalInvalidFailures": [],
            "caveats": ["minion_dps_unverified_caveat"],
            "pass": True,
            "rewardEligible": "limited",
            "rewardStrength": "limited",
            "aggregateScore": {"value": 0.72},
            "scoreVector": {
                "offense": {"value": 0.65},
                "defense": {"value": 0.74},
                "recovery": {"value": 0.83},
                "mobility": {"value": 0.55},
            },
            "scoreReviewNeeded": False,
        }

    monkeypatch.setattr(run_judge_user_samples, "evaluate_source", fake_evaluate_source)

    report = run_judge_user_samples.build_report(sample)

    assert report["regressionMatrix"] == [
        {
            "snapshotId": "user_sample_001",
            "sourceHash": "abc123",
            "summary": {
                "class": "Witch",
                "ascendancy": "Infernalist",
                "mainSkill": "Raise Skeletons",
                "judgeSelectedSkill": "Raise Skeletons",
                "level": 100,
            },
            "offense": {
                "provenance": "minion_pob_output",
                "evidenceLevel": "limited",
                "skillName": "Raise Skeletons",
                "sourceMetricDetail": "MinionTotalDPS",
            },
            "defenseModel": {"poolModel": "hybrid", "confidence": "partial"},
            "hardFailures": [],
            "physicalInvalidFailures": [],
            "caveats": ["minion_dps_unverified_caveat"],
            "pass": True,
            "rewardEligible": "limited",
            "rewardStrength": "limited",
            "scoreReviewNeeded": False,
        }
    ]


def test_evaluate_source_failure_report_omits_raw_source(monkeypatch):
    def fake_safe(_factory, *, snapshot_id, source_context, timeout_seconds):
        assert source_context == "trusted_reference"
        assert snapshot_id == "bad"
        assert timeout_seconds == 900.0
        return {
            "snapshotId": snapshot_id,
            "pass": False,
            "hardFailures": ["pob_compute_failed"],
            "modelability": {"status": "not_modelable"},
            "caveats": [],
            "errorKind": "PobEngineError",
        }

    monkeypatch.setattr(run_judge_user_samples.runner, "safe_evaluate_active_build", fake_safe)

    report = run_judge_user_samples.evaluate_source("very-secret-pob-code", "bad")

    serialized = str(report)
    assert report["sourceHash"]
    assert report["errorKind"] == "PobEngineError"
    assert "very-secret-pob-code" not in serialized


def test_evaluate_source_uses_extended_timeout_for_compute(monkeypatch):
    seen = {}

    def fake_safe(_factory, *, snapshot_id, source_context, timeout_seconds):
        seen["snapshot_id"] = snapshot_id
        seen["source_context"] = source_context
        seen["timeout_seconds"] = timeout_seconds
        return {
            "snapshotId": snapshot_id,
            "pass": False,
            "hardFailures": ["pob_compute_failed"],
            "modelability": {"status": "not_modelable"},
            "caveats": [],
            "errorKind": "TimeoutError",
        }

    monkeypatch.setattr(run_judge_user_samples.runner, "safe_evaluate_active_build", fake_safe)

    run_judge_user_samples.evaluate_source("some-code", "slow")

    assert seen == {
        "snapshot_id": "slow",
        "source_context": "trusted_reference",
        "timeout_seconds": 900.0,
    }


def test_user_sample_report_marks_low_scoring_pass_sample_for_review(tmp_path, monkeypatch):
    sample = tmp_path / "samples.txt"
    sample.write_text("fake-pob-code\n", encoding="utf-8")

    def fake_evaluate_source(_source: str, snapshot_id: str):
        return {
            "snapshotId": snapshot_id,
            "sourceHash": "abc123",
            "summary": {
                "class": "Ranger",
                "ascendancy": "Deadeye",
                "mainSkill": "Ice Shot",
                "level": 100,
            },
            "pass": True,
            "rewardEligible": "limited",
            "rewardStrength": "limited",
            "aggregateScore": {"value": 0.42},
            "scoreVector": {
                "offense": {"value": 0.62},
                "defense": {"value": 0.41},
                "recovery": {"value": 0.77},
                "mobility": {"value": 0.58},
            },
            "scoreBreakdown": {"offense": {"rawValue": 123}},
            "hardFailures": [],
            "physicalInvalidFailures": [],
            "caveats": [],
            "defenseModel": {"poolModel": "life", "confidence": "full"},
            "modelability": {"status": "full"},
            "scoreReviewNeeded": True,
            "scoreReviewReasons": ["aggregate_below_0_5", "defense_below_0_5"],
        }

    monkeypatch.setattr(run_judge_user_samples, "evaluate_source", fake_evaluate_source)

    report = run_judge_user_samples.build_report(sample)

    assert report["samples"][0]["scoreReviewNeeded"] is True
    assert report["samples"][0]["scoreReviewReasons"] == [
        "aggregate_below_0_5",
        "defense_below_0_5",
    ]


def test_user_sample_report_does_not_mark_failing_sample_for_score_review(tmp_path, monkeypatch):
    sample = tmp_path / "samples.txt"
    sample.write_text("fake-pob-code\n", encoding="utf-8")

    def fake_evaluate_source(_source: str, snapshot_id: str):
        return {
            "snapshotId": snapshot_id,
            "sourceHash": "abc123",
            "summary": {
                "class": "Witch",
                "ascendancy": "Infernalist",
                "mainSkill": "Spark",
                "level": 100,
            },
            "pass": False,
            "rewardEligible": False,
            "rewardStrength": "none",
            "aggregateScore": {"value": 0.1},
            "scoreVector": {
                "offense": {"value": 0.1},
                "defense": {"value": 0.1},
                "recovery": {"value": 0.1},
                "mobility": {"value": 0.1},
            },
            "hardFailures": ["uncapped_resistance"],
            "physicalInvalidFailures": [],
            "caveats": [],
            "defenseModel": {"poolModel": "life", "confidence": "full"},
            "modelability": {"status": "full"},
            "scoreReviewNeeded": False,
        }

    monkeypatch.setattr(run_judge_user_samples, "evaluate_source", fake_evaluate_source)

    report = run_judge_user_samples.build_report(sample)

    assert report["samples"][0]["scoreReviewNeeded"] is False


def test_summary_sanitizer_preserves_judge_selected_skill_without_links():
    summary = run_judge_user_samples._sanitize_summary(
        {
            "class": "Mercenary",
            "ascendancy": "Tactician",
            "mainSkill": "Dread Banner",
            "judgeSelectedSkill": "Molten Crash",
            "level": 100,
            "mainSkillGroup": [
                {"name": "Molten Crash"},
                {"name": "Martial Tempo"},
            ],
            "gear": {"Weapon 1": {"name": "Secret Weapon"}},
        }
    )

    assert summary == {
        "class": "Mercenary",
        "ascendancy": "Tactician",
        "mainSkill": "Dread Banner",
        "judgeSelectedSkill": "Molten Crash",
        "level": 100,
    }


def test_user_sample_script_runs_when_invoked_by_file_path():
    result = subprocess.run(
        [sys.executable, "scripts/run_judge_user_samples.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--source-file" in result.stdout


def test_source_file_xml_sample_is_not_split_on_blank_lines(tmp_path, monkeypatch):
    sample = tmp_path / "samples.xml"
    sample.write_text(
        '<PathOfBuilding>\n\n<Build level="100" />\n</PathOfBuilding>\n', encoding="utf-8"
    )
    seen: list[str] = []

    def fake_evaluate_source(source: str, snapshot_id: str):
        seen.append(source)
        return {"snapshotId": snapshot_id, "sourceHash": "h", "summary": {}, "hardFailures": []}

    monkeypatch.setattr(run_judge_user_samples, "evaluate_source", fake_evaluate_source)

    report = run_judge_user_samples.build_report(sample)

    assert report["sampleCount"] == 1
    assert seen == ['<PathOfBuilding>\n\n<Build level="100" />\n</PathOfBuilding>']
