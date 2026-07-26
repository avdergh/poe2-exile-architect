"""Trusted artifact-bound lifecycle receipts for Phase 8 progression.

PoB does not guarantee byte-identical XML after an import/save round trip and refreshes derived
output nodes during otherwise read-only calls. A receipt therefore binds the lifecycle computation
to the immutable source artifact while separately recording the engine's semantic restored-state
hash used for the no-mutation check. No XML is persisted here.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from server import paths
from server.knowledge import copy_safety

from . import artifacts, models


LIFECYCLE_RECEIPT_SCHEMA_VERSION = 1
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:\-]{1,240}$")
_LIFECYCLE_STAGES = {
    "campaign_early",
    "campaign_mid",
    "campaign_late",
    "maps_entry",
    "endgame_budget",
    "endgame_final",
}


class ArtifactLifecycleReceipt(models.StrictModel):
    schema_version: Literal[1] = LIFECYCLE_RECEIPT_SCHEMA_VERSION
    verification_ref: str = Field(pattern=r"^lifecycle-verification:[a-f0-9]{16}$")
    artifact_id: str = Field(pattern=r"^final-build:[A-Za-z0-9\-]{3,100}$")
    source_hash: str = Field(min_length=1, max_length=120)
    restored_engine_source_hash: str = Field(min_length=1, max_length=120)
    stage: str = Field(min_length=1, max_length=80)
    status: Literal["passed", "failed", "unknown"]
    passed: bool = Field(validation_alias="pass", serialization_alias="pass")
    failed_checks: list[str] = Field(default_factory=list, max_length=24)
    unknown_checks: list[str] = Field(default_factory=list, max_length=24)
    caveats: list[str] = Field(default_factory=list, max_length=12)
    evidence_tags: list[str] = Field(default_factory=list, max_length=8)
    build_id: str | None = Field(default=None, max_length=120)
    created_at: str
    artifact_bound: Literal[True] = True
    no_raw_material: Literal[True] = True

    @model_validator(mode="after")
    def _consistent_and_safe(self) -> "ArtifactLifecycleReceipt":
        if self.passed is not (self.status == "passed"):
            raise ValueError("lifecycle pass and status must agree")
        if self.stage not in _LIFECYCLE_STAGES:
            raise ValueError("lifecycle receipt stage is invalid")
        if any(not item.strip() or len(item) > 500 for item in self.caveats):
            raise ValueError("lifecycle receipt caveat is invalid")
        tokens = [
            self.source_hash,
            self.restored_engine_source_hash,
            self.stage,
            *self.failed_checks,
            *self.unknown_checks,
            *self.evidence_tags,
        ]
        if self.build_id:
            tokens.append(self.build_id)
        if any(not _SAFE_TOKEN.fullmatch(value) for value in tokens):
            raise ValueError("lifecycle receipt contains an invalid token")
        try:
            parsed = datetime.fromisoformat(self.created_at)
        except ValueError as exc:
            raise ValueError("lifecycle receipt timestamp is invalid") from exc
        if parsed.tzinfo is None:
            raise ValueError("lifecycle receipt timestamp requires a timezone")
        payload = self.model_dump(mode="json", by_alias=True)
        if (
            copy_safety.find_forbidden_paths(payload)
            or copy_safety.durable_knowledge_flags(payload)
            or copy_safety.contains_raw_url(payload)
        ):
            raise ValueError("lifecycle receipt is not copy-safe")
        return self


def save_artifact_lifecycle_receipt(
    *,
    artifact_id: str,
    source_hash: str,
    restored_engine_source_hash: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Persist one safe receipt after evaluating an immutable private artifact."""

    selected = _select_result(result)
    if selected is None or selected["evaluatedSourceHash"] != source_hash:
        return models.rejected("invalid_artifact_lifecycle_result")
    verification_ref = _verification_ref(
        artifact_id=artifact_id,
        source_hash=source_hash,
        restored_engine_source_hash=restored_engine_source_hash,
        selected=selected,
    )
    try:
        receipt = ArtifactLifecycleReceipt(
            verification_ref=verification_ref,
            artifact_id=artifact_id,
            source_hash=source_hash,
            restored_engine_source_hash=restored_engine_source_hash,
            stage=selected["stage"],
            status=selected["status"],
            passed=selected["pass"],
            failed_checks=selected["failedChecks"],
            unknown_checks=selected["unknownChecks"],
            caveats=selected["caveats"],
            evidence_tags=selected["evidenceTags"],
            build_id=selected["buildId"],
            created_at=datetime.now(timezone.utc).isoformat(),
            artifact_bound=True,
            no_raw_material=True,
        )
    except ValueError:
        return models.rejected("invalid_artifact_lifecycle_result")
    root = paths.build_progression_lifecycle_receipts_dir()
    final_path = root / f"{verification_ref.split(':', 1)[1]}.json"
    temp_path = root / f".{final_path.name}.{uuid4().hex}.tmp"
    payload = receipt.model_dump(mode="json", by_alias=True)
    try:
        root.mkdir(parents=True, exist_ok=True)
        if final_path.is_file():
            existing = _read_path(final_path)
            if existing is None or _stable_fields(existing) != _stable_fields(payload):
                return models.rejected("artifact_lifecycle_receipt_conflict")
        else:
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(final_path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        return models.rejected("artifact_lifecycle_receipt_write_failed")
    return {
        "status": "recorded",
        "verificationRef": verification_ref,
        "artifactId": artifact_id,
        "evaluatedSourceHash": source_hash,
        "restoredEngineSourceHash": restored_engine_source_hash,
        "artifactBound": True,
        "containsRawPob": False,
    }


def read_trusted_artifact_lifecycle_receipt(
    verification_ref: str,
    *,
    artifact_id: str,
    stage: str,
) -> dict[str, Any] | None:
    """Resolve and revalidate one receipt against its immutable final artifact."""

    if not re.fullmatch(r"lifecycle-verification:[a-f0-9]{16}", verification_ref):
        return None
    path = (
        paths.build_progression_lifecycle_receipts_dir()
        / f"{verification_ref.split(':', 1)[1]}.json"
    )
    payload = _read_path(path)
    if payload is None:
        return None
    try:
        receipt = ArtifactLifecycleReceipt.model_validate(payload)
    except ValueError:
        return None
    if (
        receipt.verification_ref != verification_ref
        or receipt.artifact_id != artifact_id
        or receipt.stage != stage
        or receipt.verification_ref
        != _verification_ref(
            artifact_id=receipt.artifact_id,
            source_hash=receipt.source_hash,
            restored_engine_source_hash=receipt.restored_engine_source_hash,
            selected={
                "stage": receipt.stage,
                "status": receipt.status,
                "pass": receipt.passed,
                "failedChecks": receipt.failed_checks,
                "unknownChecks": receipt.unknown_checks,
                "caveats": receipt.caveats,
                "evidenceTags": receipt.evidence_tags,
                "evaluatedSourceHash": receipt.source_hash,
                "buildId": receipt.build_id,
            },
        )
    ):
        return None
    verified = artifacts.read_final_build_artifact_for_export(artifact_id)
    if verified is None:
        return None
    manifest, _xml = verified
    if manifest.source_hash != receipt.source_hash:
        return None
    return receipt.model_dump(mode="json", by_alias=True)


def _select_result(result: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    stage = result.get("stage")
    status = result.get("status")
    passed = result.get("pass")
    source_hash = result.get("evaluatedSourceHash")
    if (
        not isinstance(stage, str)
        or status not in {"passed", "failed", "unknown"}
        or not isinstance(passed, bool)
        or not isinstance(source_hash, str)
    ):
        return None

    def tokens(key: str, limit: int) -> list[str] | None:
        value = result.get(key, [])
        if (
            not isinstance(value, list)
            or len(value) > limit
            or any(not isinstance(item, str) for item in value)
        ):
            return None
        return list(value)

    failed = tokens("failedChecks", 24)
    unknown = tokens("unknownChecks", 24)
    evidence = tokens("evidenceTags", 8)
    caveats = result.get("caveats", [])
    build_id = result.get("buildId")
    if (
        failed is None
        or unknown is None
        or evidence is None
        or not isinstance(caveats, list)
        or len(caveats) > 12
        or any(not isinstance(item, str) or not item.strip() or len(item) > 500 for item in caveats)
        or (build_id is not None and not isinstance(build_id, str))
    ):
        return None
    return {
        "stage": stage,
        "status": status,
        "pass": passed,
        "failedChecks": failed,
        "unknownChecks": unknown,
        "caveats": list(caveats),
        "evidenceTags": evidence,
        "evaluatedSourceHash": source_hash,
        "buildId": build_id,
    }


def _read_path(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _stable_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "createdAt"}


def _verification_ref(
    *,
    artifact_id: str,
    source_hash: str,
    restored_engine_source_hash: str,
    selected: dict[str, Any],
) -> str:
    stable = {
        "artifactId": artifact_id,
        "sourceHash": source_hash,
        "restoredEngineSourceHash": restored_engine_source_hash,
        **selected,
        "artifactBound": True,
        "noRawMaterial": True,
    }
    return (
        "lifecycle-verification:"
        + hashlib.sha256(
            json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
    )
