"""部分文件删除后仍须保留原队列，供 typed cleanup 重新核对同一接受证据。"""

from pathlib import Path

import pytest

from scripts import research_mature_builds as research
from server import paths
from server.knowledge import research_workflow
from test_research_completion_cleanup import (
    RUN_ID,
    _audit,
    _clean_summary,
    _partial_summary,
    _queue_case,
)


@pytest.mark.parametrize("partial", [False, True], ids=["clean", "explicit-abandon"])
@pytest.mark.parametrize("rename_back_fails", [False, True], ids=["restored-run", "retained-staging"])
def test_partial_directory_removal_preserves_exact_queue_for_typed_retry(
    tmp_path, monkeypatch, partial, rename_back_fails
):
    runtime_root = tmp_path / "research"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: runtime_root)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(
        research, "_preserve_legacy_write_receipts",
        lambda **_kwargs: {"status": "ok", "writeReceiptRefs": []},
    )
    monkeypatch.setattr(
        research.research_packet, "cleanup_packets_by_safe_hashes",
        lambda *_args, **_kwargs: {"removed": 0},
    )
    summary = _partial_summary() if partial else _clean_summary()
    run_dir, queue = _queue_case(runtime_root, summary)
    queue_snapshot = queue.read_bytes()
    staging = run_dir.with_name(f"{RUN_ID}.cleanup-staging")
    source_dir = run_dir / "quarantine"
    source_dir.mkdir()
    (source_dir / "already-removed.json").write_text("synthetic disposable source")
    (source_dir / "locked.json").write_text("synthetic retained source")
    real_rmtree = research.shutil.rmtree
    real_rename = Path.rename

    def partially_remove_then_fail(directory):
        assert Path(directory) == staging
        (staging / research.QUEUE_DB_FILENAME).unlink(missing_ok=True)
        (staging / "quarantine" / "already-removed.json").unlink(missing_ok=True)
        raise OSError(5, "synthetic locked quarantine file")

    def maybe_fail_rename_back(source, destination):
        if rename_back_fails and source == staging and Path(destination) == run_dir:
            raise OSError(5, "synthetic staging directory lock")
        return real_rename(source, destination)

    monkeypatch.setattr(research.shutil, "rmtree", partially_remove_then_fail)
    monkeypatch.setattr(Path, "rename", maybe_fail_rename_back)
    first = research_workflow.cleanup_run(
        run_ref=f"research-run:{RUN_ID}", abandon_incomplete=partial,
    )
    assert first["status"] == "partial", first
    assert first["detail"]["reason"] == "staging_removal_failed"
    assert first["detail"]["queueRestored"] is True
    assert first["detail"]["queuePreserved"] is True
    assert first["detail"]["runtimeMayBePartiallyRemoved"] is True
    retained_root = staging if rename_back_fails else run_dir
    assert (retained_root / research.QUEUE_DB_FILENAME).read_bytes() == queue_snapshot
    assert not (retained_root / "quarantine" / "already-removed.json").exists()
    assert (retained_root / "quarantine" / "locked.json").is_file()
    assert _audit(runtime_root)["samples"][0]["researchCompletion"] == (
        "needs_followup" if partial else "complete"
    )
    status = research_workflow.run_status(run_ref=f"research-run:{RUN_ID}")
    assert status["status"] != "archived"

    monkeypatch.setattr(research.shutil, "rmtree", real_rmtree)
    monkeypatch.setattr(Path, "rename", real_rename)
    if partial:
        blocked = research_workflow.cleanup_run(run_ref=f"research-run:{RUN_ID}")
        assert blocked["errorCode"] == "research_followup_required"
        assert run_dir.exists()
    second = research_workflow.cleanup_run(
        run_ref=f"research-run:{RUN_ID}", abandon_incomplete=partial,
    )
    assert second["status"] == "cleaned", second
    assert not run_dir.exists()
    assert not staging.exists()
    status = research_workflow.run_status(run_ref=f"research-run:{RUN_ID}")
    assert status["status"] == "archived"
    assert status["samples"][0]["researchCompletion"] == (
        "needs_followup" if partial else "complete"
    )


def test_queue_snapshot_failure_does_not_start_directory_removal(tmp_path, monkeypatch):
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    marker = run_dir / "quarantine.json"
    marker.write_text("synthetic retained source")
    deletes = []
    monkeypatch.setattr(research.shutil, "rmtree", lambda path: deletes.append(path))

    outcome, detail = research._delete_run_directory(
        run_dir, run_dir.with_name(f"{RUN_ID}.cleanup-staging"),
    )

    assert outcome == "deferred"
    assert detail["reason"] == "queue_snapshot_unavailable"
    assert marker.is_file()
    assert deletes == []


def test_failed_queue_restore_reports_recovery_required(tmp_path, monkeypatch):
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    queue = run_dir / research.QUEUE_DB_FILENAME
    queue.write_bytes(b"exact safe synthetic queue bytes")
    retained = run_dir / "quarantine.json"
    retained.write_text("synthetic retained source")
    staging = run_dir.with_name(f"{RUN_ID}.cleanup-staging")
    real_open = Path.open

    def partially_remove_then_fail(directory):
        (Path(directory) / research.QUEUE_DB_FILENAME).unlink(missing_ok=True)
        raise OSError(5, "synthetic locked source")

    def fail_queue_restore(path, *args, **kwargs):
        if path.name.endswith(".restore"):
            raise OSError(5, "synthetic denied queue restore")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(research.shutil, "rmtree", partially_remove_then_fail)
    monkeypatch.setattr(Path, "open", fail_queue_restore)

    outcome, detail = research._delete_run_directory(run_dir, staging)

    assert outcome == "deferred"
    assert detail["queueRestored"] is False
    assert detail["queuePreserved"] is False
    assert detail["queueRestoreError"]
    assert detail["recoveryRequired"] is True
    assert not queue.exists()
    assert retained.is_file()
