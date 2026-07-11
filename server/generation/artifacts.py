"""Local-only storage for the final Agent-accepted PoB candidate."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4
import xml.etree.ElementTree as ET

from pydantic import ValidationError

from server import paths
from server.compute import completeness
from server.judge import evaluator

from . import models, run_store


ARTIFACT_SCHEMA_VERSION = 1


class FinalBuildArtifactManifest(models.StrictModel):
    schema_version: int = ARTIFACT_SCHEMA_VERSION
    artifact_id: str
    run_id: str
    candidate_id: str
    attempt_index: int
    snapshot_id: str
    source_hash: str
    trusted_evaluation_ref: str
    safe_summary: dict[str, str]
    tested_skill_groups: list[models.TestedSkillGroup]
    judge_report: models.JudgeAdvisoryReport
    version_context: models.VersionContext
    created_at: str
    local_only: bool = True
    no_chat_output: bool = True
    no_research_memory: bool = True


def artifacts_dir() -> Path:
    override = os.environ.get("POE_BD_FINAL_ARTIFACTS_DIR")
    return (
        Path(override).resolve()
        if override
        else (paths.user_data_dir() / "final-build-artifacts").resolve()
    )


def save_final_build_artifact(
    active_engine: Any,
    *,
    run_id: str,
    run_token: str,
    candidate_id: str,
    attempt_index: int,
) -> dict[str, Any]:
    """Persist exactly one passing, unchanged PoB snapshot for a generation run."""
    try:
        bound_run = run_store.load_bound_run(run_id, run_token)
    except run_store.RunStoreError as exc:
        return models.rejected(exc.code)
    receipts = run_store.read_trusted_evaluations(bound_run)
    if attempt_index < 0 or attempt_index >= len(receipts):
        return models.rejected("trusted_evaluation_not_found")
    if attempt_index != len(receipts) - 1:
        return models.rejected("final_attempt_required")
    receipt = receipts[attempt_index]
    if receipt.get("candidateId") != candidate_id:
        return models.rejected("trusted_evaluation_mismatch")
    try:
        state = models.TransientBuildStateRef.model_validate(receipt.get("transientBuildState"))
        judge = models.JudgeAdvisoryReport.model_validate(receipt.get("judgeAdvisoryReport"))
    except ValidationError:
        return models.rejected("trusted_evaluation_mismatch")
    if (
        judge.status != "evaluated"
        or judge.passed is not True
        or judge.hard_failures
        or state.status != "available"
    ):
        return models.rejected("final_candidate_not_passed")
    if (
        judge.evaluated_snapshot_id != state.snapshot_id
        or judge.evaluated_source_hash != state.source_hash
    ):
        return models.rejected("trusted_evaluation_mismatch")

    try:
        xml = active_engine.get_xml()
    except Exception:  # noqa: BLE001 - never expose engine internals through MCP.
        return models.rejected("active_build_snapshot_failed")
    if not _valid_pob_xml(xml):
        return models.rejected("active_build_snapshot_invalid")
    if evaluator.compute_source_hash(xml) != state.source_hash:
        return models.rejected("active_build_changed_after_evaluation")
    blockers = completeness.artifact_blockers(xml)
    if blockers:
        return models.rejected(blockers[0], caveats=blockers[1:])

    root = artifacts_dir()
    final_dir = root / bound_run.run_id
    if final_dir.exists():
        return models.rejected("final_artifact_already_exists")
    artifact_id = f"final-build:{uuid4()}"
    manifest = FinalBuildArtifactManifest(
        artifact_id=artifact_id,
        run_id=bound_run.run_id,
        candidate_id=candidate_id,
        attempt_index=attempt_index,
        snapshot_id=str(state.snapshot_id),
        source_hash=str(state.source_hash),
        trusted_evaluation_ref=f"run:{bound_run.run_id}:attempt:{attempt_index}",
        safe_summary=state.safe_summary,
        tested_skill_groups=state.tested_skill_groups,
        judge_report=judge,
        version_context=judge.version_context,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    temp_dir = root / f".{bound_run.run_id}.{uuid4().hex}.tmp"
    try:
        root.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir()
        (temp_dir / "build.xml").write_text(xml, encoding="utf-8")
        (temp_dir / "manifest.json").write_text(
            json.dumps(
                manifest.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        temp_dir.replace(final_dir)
    except OSError:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return models.rejected("final_artifact_write_failed")
    return {
        "status": "saved",
        "finalBuildArtifact": _safe_manifest(manifest),
        "containsRawPob": False,
    }


def list_final_build_artifacts() -> dict[str, Any]:
    manifests = [manifest for _, manifest in _iter_artifacts()]
    manifests.sort(key=lambda item: item.created_at, reverse=True)
    return {
        "status": "ok",
        "artifacts": [_safe_manifest(manifest) for manifest in manifests],
        "containsRawPob": False,
    }


def load_final_build_artifact(active_engine: Any, *, artifact_id: str) -> dict[str, Any]:
    found = _find_artifact(artifact_id)
    if found is None:
        return models.rejected("final_artifact_not_found")
    artifact_dir, manifest = found
    try:
        xml = (artifact_dir / "build.xml").read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return models.rejected("final_artifact_corrupt")
    if not _valid_pob_xml(xml) or evaluator.compute_source_hash(xml) != manifest.source_hash:
        return models.rejected("final_artifact_corrupt")
    try:
        loaded = active_engine.load_build_xml(xml, name=manifest.artifact_id)
    except Exception:  # noqa: BLE001 - never expose engine internals through MCP.
        return models.rejected("final_artifact_restore_failed")
    return {
        "status": "loaded",
        "finalBuildArtifact": _safe_manifest(manifest),
        "activeBuild": _safe_loaded_summary(loaded),
        "containsRawPob": False,
    }


def read_final_build_artifact_for_export(
    artifact_id: str,
) -> tuple[FinalBuildArtifactManifest, str] | None:
    """Return a verified artifact to the internal export layer without exposing it through MCP."""
    found = _find_artifact(artifact_id)
    if found is None:
        return None
    artifact_dir, manifest = found
    try:
        xml = (artifact_dir / "build.xml").read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    if (
        not _valid_pob_xml(xml)
        or evaluator.compute_source_hash(xml) != manifest.source_hash
        or manifest.judge_report.status != "evaluated"
        or manifest.judge_report.passed is not True
        or manifest.judge_report.hard_failures
        or manifest.judge_report.evaluated_snapshot_id != manifest.snapshot_id
        or manifest.judge_report.evaluated_source_hash != manifest.source_hash
    ):
        return None
    return manifest, xml


def _iter_artifacts() -> list[tuple[Path, FinalBuildArtifactManifest]]:
    root = artifacts_dir()
    if not root.is_dir():
        return []
    found: list[tuple[Path, FinalBuildArtifactManifest]] = []
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest = _read_manifest(child / "manifest.json")
        if manifest is not None:
            found.append((child, manifest))
    return found


def _find_artifact(artifact_id: str) -> tuple[Path, FinalBuildArtifactManifest] | None:
    if not isinstance(artifact_id, str) or not artifact_id.startswith("final-build:"):
        return None
    return next(
        (
            (artifact_dir, manifest)
            for artifact_dir, manifest in _iter_artifacts()
            if manifest.artifact_id == artifact_id
        ),
        None,
    )


def _read_manifest(path: Path) -> FinalBuildArtifactManifest | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = FinalBuildArtifactManifest.model_validate(payload)
    except (UnicodeDecodeError, OSError, json.JSONDecodeError, ValidationError):
        return None
    if manifest.schema_version != ARTIFACT_SCHEMA_VERSION:
        return None
    return manifest


def _safe_manifest(manifest: FinalBuildArtifactManifest) -> dict[str, Any]:
    return {
        "artifactId": manifest.artifact_id,
        "runId": manifest.run_id,
        "candidateId": manifest.candidate_id,
        "attemptIndex": manifest.attempt_index,
        "snapshotId": manifest.snapshot_id,
        "sourceHash": manifest.source_hash,
        "safeSummary": manifest.safe_summary,
        "testedSkillGroups": [
            group.model_dump(mode="json", by_alias=True) for group in manifest.tested_skill_groups
        ],
        "judgeStatus": manifest.judge_report.status,
        "judgePassed": manifest.judge_report.passed,
        "judgeCaveats": manifest.judge_report.caveats,
        "versionContext": manifest.version_context.model_dump(mode="json", by_alias=True),
        "createdAt": manifest.created_at,
        "localOnly": manifest.local_only,
    }


def _safe_loaded_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"loaded": True}
    return {
        key: payload[key]
        for key in ("mainSkill", "treeVersion")
        if key in payload and isinstance(payload[key], (str, int, float, bool))
    }


def _valid_pob_xml(xml: Any) -> bool:
    if not isinstance(xml, str) or not xml.strip():
        return False
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return False
    return root.tag in {"PathOfBuilding", "PathOfBuilding2"}
