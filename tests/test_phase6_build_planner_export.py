from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.build_planner import exporter
from server.generation import artifacts
from server.knowledge import research_memory

from tests.test_phase6_final_artifacts import _evaluate_passing
from tests.test_phase5_generation_evaluation import _ActiveEngine


@pytest.fixture(autouse=True)
def _fresh_research_receipts(monkeypatch):
    """Evaluate fail-fasts on run-fresh dq- receipts; default every test to a fresh one."""

    def fake_reader(_self, _ref: str) -> dict[str, object]:
        return {"lastSeenAt": datetime.now(timezone.utc).isoformat()}

    monkeypatch.setattr(
        research_memory.ResearchMemoryService,
        "read_query_receipt",
        fake_reader,
    )


def _saved_artifact(tmp_path: Path, monkeypatch) -> str:
    run_id, token, result = _evaluate_passing(tmp_path, monkeypatch)
    saved = artifacts.save_final_build_artifact(
        _ActiveEngine(),
        run_id=run_id,
        run_token=token,
        candidate_id="candidate:test:final",
        attempt_index=int(result["attemptIndex"]),
    )
    return str(saved["finalBuildArtifact"]["artifactId"])


def test_export_writes_single_stage_build_without_exposing_xml(tmp_path, monkeypatch):
    artifact_id = _saved_artifact(tmp_path, monkeypatch)
    monkeypatch.setenv("POE_BD_BUILD_EXPORTS_DIR", str(tmp_path / "exports"))
    monkeypatch.setattr(
        exporter.converter,
        "convert_pob_xml",
        lambda xml, **kwargs: {
            "status": "ok",
            "provider": {"providerId": "test-provider"},
            "build": {
                "name": "Agent Spark",
                "passives": ["witch1"],
                "skills": ["Metadata/Items/Gems/SkillGemSpark"],
            },
            "serializedBuild": json.dumps(
                {
                    "name": "Agent Spark",
                    "passives": ["witch1"],
                    "skills": ["Metadata/Items/Gems/SkillGemSpark"],
                },
                indent=4,
            )
            + "\n",
            "warnings": [{"level": "warn", "code": "limited", "message": "Review in game"}],
            "stats": {"passiveCount": 1, "skillCount": 1},
            "schemaValidation": {"status": "passed", "errors": []},
        },
    )

    result = exporter.export_final_build_artifact(artifact_id, name="Agent Spark")

    assert result["status"] == "exported"
    assert result["containsRawPob"] is False
    output = Path(result["outputPath"])
    assert output.suffix == ".build"
    assert json.loads(output.read_text(encoding="utf-8"))["name"] == "Agent Spark"
    assert "PathOfBuilding" not in json.dumps(result)


def test_export_blocks_error_warning(tmp_path, monkeypatch):
    artifact_id = _saved_artifact(tmp_path, monkeypatch)
    monkeypatch.setattr(
        exporter.converter,
        "convert_pob_xml",
        lambda xml, **kwargs: {
            "status": "ok",
            "provider": {"providerId": "test-provider"},
            "build": {"name": "Blocked"},
            "serializedBuild": '{"name":"Blocked"}\n',
            "warnings": [{"level": "error", "code": "missing-id", "message": "Missing id"}],
            "stats": {},
            "schemaValidation": {"status": "passed", "errors": []},
        },
    )

    result = exporter.export_final_build_artifact(artifact_id)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "converter_error_warning"


def test_export_rejects_corrupt_artifact(tmp_path, monkeypatch):
    artifact_id = _saved_artifact(tmp_path, monkeypatch)
    artifact_dir = next((tmp_path / "artifacts").iterdir())
    (artifact_dir / "build.xml").write_text("<broken>", encoding="utf-8")

    result = exporter.export_final_build_artifact(artifact_id)

    assert result == {
        "status": "rejected",
        "errorCode": "final_artifact_not_found_or_corrupt",
    }
