from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.compute.pob_code import decode_code
from server.generation import artifacts, pob_exports
from server.knowledge import research_memory

from tests.test_phase5_generation_evaluation import BUILD_XML, _ActiveEngine
from tests.test_phase6_final_artifacts import _evaluate_passing


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


def test_export_final_pob_artifact_writes_xml_and_import_code(tmp_path, monkeypatch):
    artifact_id = _saved_artifact(tmp_path, monkeypatch)
    monkeypatch.setenv("POE_BD_POB_EXPORTS_DIR", str(tmp_path / "pob-exports"))

    result = pob_exports.export_final_pob_artifact(
        artifact_id,
        format="both",
        name="Spark Starter",
    )

    assert result["status"] == "exported"
    assert result["responseContainsRawPob"] is False
    assert result["localFilesContainPobMaterial"] is True
    outputs = {item["format"]: Path(item["outputPath"]) for item in result["outputs"]}
    assert outputs["xml"].name.startswith("Spark-Starter-")
    assert outputs["xml"].read_text(encoding="utf-8") == BUILD_XML
    code = outputs["import_code"].read_text(encoding="utf-8").strip()
    assert decode_code(code) == BUILD_XML
    assert "PathOfBuilding" not in json.dumps(result)
    assert code not in json.dumps(result)


def test_export_final_pob_artifact_supports_one_format(tmp_path, monkeypatch):
    artifact_id = _saved_artifact(tmp_path, monkeypatch)
    monkeypatch.setenv("POE_BD_POB_EXPORTS_DIR", str(tmp_path / "pob-exports"))

    result = pob_exports.export_final_pob_artifact(artifact_id, format="xml")

    assert [item["format"] for item in result["outputs"]] == ["xml"]
    assert Path(result["outputs"][0]["outputPath"]).suffix == ".xml"


def test_export_final_pob_artifact_rejects_corrupt_artifact(tmp_path, monkeypatch):
    artifact_id = _saved_artifact(tmp_path, monkeypatch)
    artifact_dir = next((tmp_path / "artifacts").iterdir())
    (artifact_dir / "build.xml").write_text("<broken>", encoding="utf-8")

    result = pob_exports.export_final_pob_artifact(artifact_id)

    assert result == {
        "status": "rejected",
        "errorCode": "final_artifact_not_found_or_corrupt",
    }
    assert not (tmp_path / "pob-exports").exists()
