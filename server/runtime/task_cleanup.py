"""Small, fail-closed cleanup boundary for completed product tasks."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Literal

from scripts import research_mature_builds
from server import paths
from server.generation import artifacts, evaluation_snapshots, run_store
from server.learning import service as learning_service


TaskKind = Literal["generation", "research", "learning_campaign"]


def cleanup_completed_task_runtime(
    *,
    task_kind: TaskKind,
    task_id: str,
    allow_rejected: bool = False,
) -> dict[str, Any]:
    """Remove private task state while preserving memories, seeds, and exported files.

    ``allow_rejected`` is a research-run opt-in that permits cleanup when the run also
    contains ``acceptance_rejected`` cases blocked by source-data gaps; the default stays
    strict (all cases accepted).
    """

    if task_kind == "generation":
        return _cleanup_generation(task_id)
    if task_kind == "research":
        return research_mature_builds.cleanup_completed_run(
            run_id=task_id, allow_rejected=allow_rejected
        )
    if task_kind == "learning_campaign":
        return _cleanup_learning_campaign(task_id)
    return _rejected("invalid_task_kind")


def _cleanup_generation(artifact_id: str) -> dict[str, Any]:
    verified = artifacts.read_final_build_artifact_for_export(artifact_id)
    if verified is None:
        return _rejected("final_artifact_not_found")
    manifest, _xml = verified
    artifact_dir = artifacts.artifacts_dir() / manifest.run_id
    marker = _read_json(artifact_dir / "delivery-complete.json")
    if (
        marker is None
        or marker.get("artifactId") != artifact_id
        or marker.get("runId") != manifest.run_id
    ):
        return _rejected("final_delivery_required_before_cleanup")
    if _artifact_is_referenced(artifact_id):
        return _rejected("task_runtime_still_referenced")
    run_error = _completed_generation_run_error(manifest.run_id, artifact_id)
    if run_error:
        return _rejected(run_error)
    removed, failures = _remove_artifact_and_run(artifact_id, manifest.run_id)
    return _cleanup_result("generation", artifact_id, removed, failures)


def _cleanup_learning_campaign(campaign_id: str) -> dict[str, Any]:
    campaign = learning_service._read_campaign(campaign_id)
    if campaign is None:
        return _rejected("learning_campaign_not_found")
    if campaign.get("status") != "completed":
        return _rejected("completed_learning_campaign_required")

    # Reference check runs BEFORE any deletion: a case artifact still referenced by another
    # campaign must fail the whole cleanup closed, or the earlier quarantine deletions would
    # already have happened by the time the artifact check rejected the run.
    for case in campaign.get("cases", []):
        artifact_id = str(case.get("artifactId") or "")
        if not artifact_id:
            continue
        if _artifact_is_referenced(artifact_id, exclude_campaign_id=campaign_id):
            return _rejected("task_runtime_still_referenced")

    removed: list[str] = []
    failures: list[str] = []
    for case in campaign.get("cases", []):
        case_id = str(case.get("caseId") or "")
        if case_id:
            _remove_tree(
                paths.comparative_learning_dir() / "quarantine" / case_id,
                paths.comparative_learning_dir() / "quarantine",
                f"learning-quarantine:{case_id}",
                removed,
                failures,
            )
        artifact_id = str(case.get("artifactId") or "")
        if artifact_id:
            verified = artifacts.read_final_build_artifact_for_export(artifact_id)
            if verified is not None:
                manifest, _xml = verified
                item_removed, item_failures = _remove_artifact_and_run(artifact_id, manifest.run_id)
                removed.extend(item_removed)
                failures.extend(item_failures)

    campaign_path = learning_service._campaign_path(campaign_id)
    if not failures and campaign_path is not None:
        _remove_file(campaign_path, f"learning-campaign:{campaign_id}", removed, failures)
    return _cleanup_result("learning_campaign", campaign_id, removed, failures)


def _completed_generation_run_error(run_id: str, artifact_id: str) -> str | None:
    run_dir = run_store.runs_dir() / run_id
    if not run_dir.exists():
        return None
    if not (run_dir / "review-consumed").is_file():
        return "completed_generation_review_required"
    selection = _read_json(run_dir / "artifact-selection.json")
    if selection is None or selection.get("artifactId") != artifact_id:
        return "artifact_selection_receipt_required"
    return None


def _remove_artifact_and_run(artifact_id: str, run_id: str) -> tuple[list[str], list[str]]:
    removed: list[str] = []
    failures: list[str] = []
    evaluation_snapshots.forget(run_id=run_id)
    _remove_tree(
        run_store.runs_dir() / run_id,
        run_store.runs_dir(),
        f"generation-run:{run_id}",
        removed,
        failures,
    )
    if not failures:
        _remove_tree(
            artifacts.artifacts_dir() / run_id,
            artifacts.artifacts_dir(),
            f"final-artifact:{artifact_id}",
            removed,
            failures,
        )
    return removed, failures


def _artifact_is_referenced(artifact_id: str, *, exclude_campaign_id: str | None = None) -> bool:
    campaign_root = learning_service.campaigns_dir()
    for campaign_path in campaign_root.glob("*.json") if campaign_root.is_dir() else ():
        payload = _read_json(campaign_path)
        if not payload:
            continue
        if exclude_campaign_id is not None and payload.get("campaignId") == exclude_campaign_id:
            # The campaign being cleaned references its own case artifacts; those references
            # are removed together with the campaign and must not block the cleanup.
            continue
        if payload and any(
            case.get("artifactId") == artifact_id for case in payload.get("cases", [])
        ):
            return True
    return False


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _remove_tree(
    path: Path,
    root: Path,
    label: str,
    removed: list[str],
    failures: list[str],
) -> None:
    try:
        candidate = path.resolve()
        safe_root = root.resolve()
        candidate.relative_to(safe_root)
        if candidate == safe_root:
            raise ValueError
    except (OSError, ValueError):
        failures.append(label)
        return
    if not candidate.exists():
        return
    try:
        shutil.rmtree(candidate)
    except OSError as exc:
        errno_value = getattr(exc, "errno", None)
        winerror = getattr(exc, "winerror", None)
        detail = f" (errno={errno_value}, winerror={winerror})" if errno_value or winerror else ""
        failures.append(
            f"{label} 清理失败{detail}：目录可能被其他进程/工具持有句柄，"
            "请关闭占用它的进程后重试，或手动删除该目录"
        )
    else:
        removed.append(label)


def _remove_file(
    path: Path,
    label: str,
    removed: list[str],
    failures: list[str],
) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError:
        failures.append(label)
    else:
        removed.append(label)


def _cleanup_result(
    task_kind: str,
    task_id: str,
    removed: list[str],
    failures: list[str],
) -> dict[str, Any]:
    return {
        "status": "cleaned" if not failures else "partial",
        "taskKind": task_kind,
        "taskId": task_id,
        "removed": removed,
        "failedToRemove": failures,
        "memoriesPreserved": True,
        "userExportsPreserved": True,
        "containsRawMaterial": False,
    }


def _rejected(error_code: str) -> dict[str, Any]:
    return {
        "status": "rejected",
        "errorCode": error_code,
        "memoriesPreserved": True,
        "userExportsPreserved": True,
        "containsRawMaterial": False,
    }
