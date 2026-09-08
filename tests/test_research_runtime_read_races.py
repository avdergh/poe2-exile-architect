"""V05/V09相邻入口：查询和被拒绝的恢复请求不能复活/清理任务。"""

from contextlib import contextmanager
import json

import pytest

from scripts import research_mature_builds as runs
from server.knowledge import research_workflow as workflow
from tests import test_research_resume_protection as resume_helpers

run_case = resume_helpers.run_case


def test_status_waiting_for_lock_reads_archive_after_cleanup_wins(run_case, monkeypatch):
    directory, db, run_ref = run_case
    original_lock = workflow.interprocess_file_lock
    interleaved = []

    @contextmanager
    def cleanup_first(path):
        if not interleaved:
            interleaved.append(True)
            assert workflow.cleanup_run(run_ref=run_ref, abandon_incomplete=True)["status"] == "cleaned"
        with original_lock(path):
            yield

    monkeypatch.setattr(workflow, "interprocess_file_lock", cleanup_first)
    result = workflow.run_status(run_ref=run_ref)
    assert result["status"] == "archived"
    assert len(result["samples"]) == 1
    assert result["cleanupReason"] == "explicit_abandonment"
    assert not db.exists() and not directory.exists()


@pytest.mark.parametrize("operation", ["status", "metadata", "cases", "write_metadata"])
def test_missing_queue_is_never_created_by_existing_runtime_access(run_case, operation):
    directory, db, run_ref = run_case
    assert workflow.cleanup_run(run_ref=run_ref, abandon_incomplete=True)["status"] == "cleaned"
    methods = {
        "status": lambda: runs.queue_status(output_dir=directory),
        "metadata": lambda: runs._read_metadata(db),
        "cases": lambda: runs._fetch_cases(db),
        "write_metadata": lambda: runs._write_metadata(db, {"unexpected": "value"}),
    }
    with pytest.raises(FileNotFoundError):
        methods[operation]()
    assert not db.exists() and not directory.exists()


@pytest.mark.parametrize("options,error", [
    ({"resume": True, "dry_run": True}, ValueError),
    ({"resume": False, "dry_run": False}, FileExistsError),
    ({"resume": False, "dry_run": True}, FileExistsError),
])
def test_rejected_queue_request_does_not_sweep_existing_packets(run_case, options, error):
    directory, db, _ = run_case
    packet = next((directory / runs.DEFAULT_TEMP_DIRNAME).glob("*/packet.json"))
    data = json.loads(packet.read_text(encoding="utf-8"))
    data["expiresAt"] = "2000-01-01T00:00:00Z"
    packet.write_text(json.dumps(data), encoding="utf-8")
    before = packet.read_bytes(), db.read_bytes()
    with pytest.raises(error):
        runs.queue_cases(output_dir=directory, **options)
    assert (packet.read_bytes(), db.read_bytes()) == before
