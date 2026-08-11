from __future__ import annotations

import json
from types import SimpleNamespace

from scripts import research_mature_builds
from server.runtime import task_cleanup


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_generation_cleanup_requires_delivery_marker(monkeypatch, tmp_path):
    run_id = "11111111-1111-1111-1111-111111111111"
    artifact_id = "final-build:test"
    artifact_root = tmp_path / "artifacts"
    run_root = tmp_path / "runs"
    artifact_dir = artifact_root / run_id
    run_dir = run_root / run_id
    artifact_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(task_cleanup.artifacts, "artifacts_dir", lambda: artifact_root)
    monkeypatch.setattr(task_cleanup.run_store, "runs_dir", lambda: run_root)
    monkeypatch.setattr(
        task_cleanup.artifacts,
        "read_final_build_artifact_for_export",
        lambda _artifact_id: (SimpleNamespace(run_id=run_id), "<PathOfBuilding/>"),
    )

    result = task_cleanup.cleanup_completed_task_runtime(
        task_kind="generation", task_id=artifact_id
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "final_delivery_required_before_cleanup"
    assert artifact_dir.is_dir()
    assert run_dir.is_dir()


def test_generation_cleanup_removes_private_state_but_preserves_exports(monkeypatch, tmp_path):
    run_id = "22222222-2222-2222-2222-222222222222"
    artifact_id = "final-build:test"
    artifact_root = tmp_path / "artifacts"
    run_root = tmp_path / "runs"
    artifact_dir = artifact_root / run_id
    run_dir = run_root / run_id
    export_file = tmp_path / "exports" / "build.build"
    _write_json(
        artifact_dir / "delivery-complete.json",
        {"artifactId": artifact_id, "runId": run_id},
    )
    _write_json(run_dir / "artifact-selection.json", {"artifactId": artifact_id})
    (run_dir / "review-consumed").write_text("", encoding="utf-8")
    export_file.parent.mkdir(parents=True)
    export_file.write_text("user delivery", encoding="utf-8")
    monkeypatch.setattr(task_cleanup.artifacts, "artifacts_dir", lambda: artifact_root)
    monkeypatch.setattr(task_cleanup.run_store, "runs_dir", lambda: run_root)
    monkeypatch.setattr(
        task_cleanup.artifacts,
        "read_final_build_artifact_for_export",
        lambda _artifact_id: (SimpleNamespace(run_id=run_id), "<PathOfBuilding/>"),
    )
    monkeypatch.setattr(task_cleanup, "_artifact_is_referenced", lambda _artifact_id: False)
    monkeypatch.setattr(task_cleanup.evaluation_snapshots, "forget", lambda **_kwargs: None)

    result = task_cleanup.cleanup_completed_task_runtime(
        task_kind="generation", task_id=artifact_id
    )

    assert result["status"] == "cleaned"
    assert result["memoriesPreserved"] is True
    assert result["userExportsPreserved"] is True
    assert not artifact_dir.exists()
    assert not run_dir.exists()
    assert export_file.read_text(encoding="utf-8") == "user delivery"


def test_research_cleanup_dispatches_by_safe_run_id(monkeypatch):
    monkeypatch.setattr(
        task_cleanup.research_mature_builds,
        "cleanup_completed_run",
        lambda *, run_id: {"status": "cleaned", "taskId": run_id},
    )

    result = task_cleanup.cleanup_completed_task_runtime(
        task_kind="research", task_id="20260805-010203-abcd"
    )

    assert result == {"status": "cleaned", "taskId": "20260805-010203-abcd"}


def test_research_cleanup_removes_run_and_exact_transient_packets(monkeypatch, tmp_path):
    run_id = "20260805-010203-abcd"
    output_root = tmp_path / ".poe-bd-research" / "runs" / run_id
    db_path = output_root / research_mature_builds.QUEUE_DB_FILENAME
    db_path.parent.mkdir(parents=True)
    db_path.write_text("fixture", encoding="utf-8")
    accept_dir = output_root / "acceptance"
    accept_dir.mkdir(parents=True)
    (accept_dir / "sample-acceptance.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        research_mature_builds,
        "DEFAULT_OUTPUT_DIR",
        tmp_path / ".poe-bd-research",
    )
    monkeypatch.setattr(
        research_mature_builds,
        "_fetch_cases",
        lambda _db_path: [
            {
                "status": "accepted",
                "packetSafeHash": "safe-hash",
                "accepted_deep_record_count": 1,
            }
        ],
    )
    packet_calls = []
    monkeypatch.setattr(
        research_mature_builds.research_packet,
        "cleanup_packets_by_safe_hashes",
        lambda hashes, *, temp_root: packet_calls.append((hashes, temp_root)) or {"removed": 1},
    )

    result = research_mature_builds.cleanup_completed_run(run_id=run_id)

    assert result["status"] == "cleaned"
    assert result["removedTransientPacketCount"] == 1
    assert packet_calls[0][0] == {"safe-hash"}
    assert not output_root.exists()


def test_completed_learning_cleanup_preserves_learning_memory(monkeypatch, tmp_path):
    campaign_id = "44444444-4444-4444-4444-444444444444"
    case_id = "55555555-5555-5555-5555-555555555555"
    learning_root = tmp_path / "comparative-learning"
    campaign_path = learning_root / "campaigns" / f"{campaign_id}.json"
    quarantine_dir = learning_root / "quarantine" / case_id
    memory_path = learning_root / "learning-memory.jsonl"
    _write_json(campaign_path, {"campaignId": campaign_id})
    _write_json(quarantine_dir / "source.json", {"rawXml": "private"})
    memory_path.write_text('{"eventType":"lesson"}\n', encoding="utf-8")
    campaign = {
        "campaignId": campaign_id,
        "status": "completed",
        "cases": [{"caseId": case_id, "artifactId": None}],
    }
    monkeypatch.setattr(task_cleanup.learning_service, "_read_campaign", lambda _task_id: campaign)
    monkeypatch.setattr(
        task_cleanup.learning_service, "_campaign_path", lambda _task_id: campaign_path
    )
    monkeypatch.setattr(task_cleanup.paths, "comparative_learning_dir", lambda: learning_root)

    result = task_cleanup.cleanup_completed_task_runtime(
        task_kind="learning_campaign", task_id=campaign_id
    )

    assert result["status"] == "cleaned"
    assert not campaign_path.exists()
    assert not quarantine_dir.exists()
    assert memory_path.read_text(encoding="utf-8") == '{"eventType":"lesson"}\n'


def test_completed_learning_cleanup_rejects_when_artifact_referenced_elsewhere(
    monkeypatch, tmp_path
):
    campaign_id = "66666666-6666-6666-6666-666666666666"
    other_campaign_id = "77777777-7777-7777-7777-777777777777"
    case_id = "88888888-8888-8888-8888-888888888888"
    learning_root = tmp_path / "comparative-learning"
    campaign_path = learning_root / "campaigns" / f"{campaign_id}.json"
    quarantine_dir = learning_root / "quarantine" / case_id
    _write_json(quarantine_dir / "source.json", {"rawXml": "private"})
    campaign = {
        "campaignId": campaign_id,
        "status": "completed",
        "cases": [
            {"caseId": case_id, "artifactId": "final-build:shared-artifact"},
        ],
    }
    _write_json(campaign_path, campaign)
    _write_json(
        learning_root / "campaigns" / f"{other_campaign_id}.json",
        {
            "campaignId": other_campaign_id,
            "status": "active",
            "cases": [
                {
                    "caseId": "99999999-9999-9999-9999-999999999999",
                    "artifactId": "final-build:shared-artifact",
                }
            ],
        },
    )
    monkeypatch.setattr(task_cleanup.learning_service, "_read_campaign", lambda _task_id: campaign)
    monkeypatch.setattr(
        task_cleanup.learning_service, "_campaign_path", lambda _task_id: campaign_path
    )
    monkeypatch.setattr(
        task_cleanup.learning_service, "campaigns_dir", lambda: learning_root / "campaigns"
    )
    monkeypatch.setattr(task_cleanup.paths, "comparative_learning_dir", lambda: learning_root)

    result = task_cleanup.cleanup_completed_task_runtime(
        task_kind="learning_campaign", task_id=campaign_id
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "task_runtime_still_referenced"
    # Nothing is deleted: the reference check runs before any removal.
    assert campaign_path.exists()
    assert quarantine_dir.exists()


def test_completed_learning_cleanup_allows_own_artifact_reference(monkeypatch, tmp_path):
    campaign_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    case_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    learning_root = tmp_path / "comparative-learning"
    campaign_path = learning_root / "campaigns" / f"{campaign_id}.json"
    quarantine_dir = learning_root / "quarantine" / case_id
    _write_json(campaign_path, {"campaignId": campaign_id})
    _write_json(quarantine_dir / "source.json", {"rawXml": "private"})
    campaign = {
        "campaignId": campaign_id,
        "status": "completed",
        "cases": [
            {"caseId": case_id, "artifactId": "final-build:self-artifact"},
        ],
    }
    monkeypatch.setattr(task_cleanup.learning_service, "_read_campaign", lambda _task_id: campaign)
    monkeypatch.setattr(
        task_cleanup.learning_service, "_campaign_path", lambda _task_id: campaign_path
    )
    monkeypatch.setattr(
        task_cleanup.learning_service, "campaigns_dir", lambda: learning_root / "campaigns"
    )
    monkeypatch.setattr(task_cleanup.paths, "comparative_learning_dir", lambda: learning_root)
    # No stored artifact backs "final-build:self-artifact", so the artifact removal is skipped.
    monkeypatch.setattr(
        task_cleanup.artifacts, "read_final_build_artifact_for_export", lambda _id: None
    )

    result = task_cleanup.cleanup_completed_task_runtime(
        task_kind="learning_campaign", task_id=campaign_id
    )

    assert result["status"] == "cleaned"
    assert not campaign_path.exists()
    assert not quarantine_dir.exists()
