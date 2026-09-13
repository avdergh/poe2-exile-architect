"""One lightweight workflow-error recovery check; Judge/engine use existing test doubles."""

from datetime import datetime, timezone
from pathlib import Path

from server.compute.pob_code import decode_code
from server.generation import artifacts, pob_exports, run_store
from server.knowledge import research_memory
from tests.test_phase5_generation_evaluation import BUILD_XML, _ActiveEngine
from tests.test_phase6_final_artifacts import _RestoreEngine, _evaluate_passing


def test_save_write_error_resumes_same_attempt_and_exports_exact_build(tmp_path, monkeypatch):
    monkeypatch.setattr(
        research_memory.ResearchMemoryService,
        "read_query_receipt",
        lambda _self, _ref: {"lastSeenAt": datetime.now(timezone.utc).isoformat()},
    )
    run_id, token, evaluated = _evaluate_passing(tmp_path, monkeypatch)
    bound = run_store.load_bound_run(run_id, token)
    before = run_store.read_trusted_evaluations_strict(bound)
    assert len(before) == 1
    selection = {
        "run_id": run_id,
        "run_token": token,
        "candidate_id": "candidate:test:final",
        "attempt_index": int(evaluated["attemptIndex"]),
    }
    write_text = Path.write_text

    def interrupted_write(path, *args, **kwargs):
        if path.name == "manifest.json" and path.parent.name.endswith(".tmp"):
            raise OSError("isolated save interruption")
        return write_text(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Path, "write_text", interrupted_write)
        failed = artifacts.save_final_build_artifact(_ActiveEngine(), **selection)
    assert failed["errorCode"] == "final_artifact_write_failed"
    assert artifacts.list_final_build_artifacts()["artifacts"] == []
    assert not list((tmp_path / "artifacts").iterdir())

    # Resume the same candidate/attempt after correcting the tool fault, without another Judge.
    saved = artifacts.save_final_build_artifact(_ActiveEngine(), **selection)
    assert saved["status"] == "saved"
    assert run_store.read_trusted_evaluations_strict(bound) == before
    del saved  # Resume from retained run identity, without relying on the last save reply.
    listed = [item for item in artifacts.list_final_build_artifacts()["artifacts"]
              if item["runId"] == run_id and item["candidateId"] == selection["candidate_id"]
              and item["attemptIndex"] == selection["attempt_index"]]
    assert len(listed) == 1
    artifact_id = listed[0]["artifactId"]

    # Existing discovery/load/export tools continue from the saved artifact's exact identity.
    restored_engine = _RestoreEngine()
    restored = artifacts.load_final_build_artifact(restored_engine, artifact_id=artifact_id)
    assert restored["status"] == "loaded" and restored_engine.loaded_xml == BUILD_XML
    monkeypatch.setenv("POE_BD_POB_EXPORTS_DIR", str(tmp_path / "exports"))
    exported = pob_exports.export_final_pob_artifact(artifact_id, format="both")
    assert exported["status"] == "exported"
    outputs = {item["format"]: Path(item["outputPath"]) for item in exported["outputs"]}
    assert outputs["xml"].read_text(encoding="utf-8") == BUILD_XML
    assert decode_code(outputs["import_code"].read_text(encoding="utf-8").strip()) == BUILD_XML
    assert run_store.read_trusted_evaluations_strict(bound) == before
