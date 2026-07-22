"""Verified multi-stage progression routes built from trusted final-stage artifacts."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, ValidationError, field_validator, model_validator

from server import paths
from server.knowledge import copy_safety

from . import artifacts, models


PROGRESSION_SCHEMA_VERSION = 1
STAGE_ORDER = {
    "campaign_early": 0,
    "campaign_mid": 1,
    "campaign_late": 2,
    "maps_entry": 3,
    "endgame_budget": 4,
    "endgame_final": 5,
}
ChangeCategory = Literal[
    "skill",
    "support",
    "passive",
    "gear",
    "ascendancy",
    "configuration",
    "resource",
]
ChangeAction = Literal["add", "remove", "replace", "upgrade", "respec", "retain"]
RequirementKind = Literal[
    "level",
    "quest",
    "ascendancy_points",
    "skill_available",
    "item_available",
    "spirit",
    "attribute",
    "resistance",
    "budget",
    "judge_gate",
    "manual",
]
RequirementStatus = Literal["satisfied", "required", "unverified"]
_SAFE_REF = re.compile(r"^[A-Za-z0-9_.:/\-]{3,240}$")


class ProgressionChange(models.StrictModel):
    category: ChangeCategory
    action: ChangeAction
    subject: str = Field(min_length=1, max_length=160)
    replaces: str | None = Field(default=None, min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=320)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _replacement_is_consistent(self) -> "ProgressionChange":
        if self.action == "replace" and self.replaces is None:
            raise ValueError("replace progression change requires replaces")
        if self.action != "replace" and self.replaces is not None:
            raise ValueError("only replace progression change may carry replaces")
        _validate_safe_refs(self.evidence_refs)
        return self


class TransitionRequirement(models.StrictModel):
    kind: RequirementKind
    description: str = Field(min_length=1, max_length=320)
    status: RequirementStatus
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _evidence_is_consistent(self) -> "TransitionRequirement":
        _validate_safe_refs(self.evidence_refs)
        if self.status == "satisfied" and not self.evidence_refs:
            raise ValueError("satisfied transition requirement requires evidence")
        return self


class ProgressionStage(models.StrictModel):
    lifecycle_stage: models.LIFECYCLE_STAGE
    target_level: int = Field(ge=1, le=100)
    artifact_id: str = Field(pattern=r"^final-build:[A-Za-z0-9\-]{3,80}$")
    purpose: str = Field(min_length=1, max_length=320)
    play_pattern: str = Field(min_length=1, max_length=500)
    changes_from_previous: list[ProgressionChange] = Field(default_factory=list, max_length=24)
    transition_requirements: list[TransitionRequirement] = Field(
        default_factory=list, max_length=12
    )
    acquisition_priorities: list[str] = Field(default_factory=list, max_length=12)
    caveats: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("lifecycle_stage", mode="before")
    @classmethod
    def _normalize_stage(cls, value: Any) -> Any:
        normalized = models.normalize_lifecycle_stages([value])
        return normalized[0] if normalized else value


class ProgressionRouteProposal(models.VersionedSafeModel):
    route_name: str = Field(min_length=1, max_length=120)
    class_shell: str = Field(min_length=1, max_length=120)
    target_final_artifact_id: str = Field(pattern=r"^final-build:[A-Za-z0-9\-]{3,80}$")
    stages: list[ProgressionStage] = Field(min_length=2, max_length=8)
    route_summary: str = Field(min_length=1, max_length=800)

    @model_validator(mode="after")
    def _ordered_route(self) -> "ProgressionRouteProposal":
        names = [str(stage.lifecycle_stage) for stage in self.stages]
        levels = [stage.target_level for stage in self.stages]
        artifacts_seen = [stage.artifact_id for stage in self.stages]
        if len(names) != len(set(names)):
            raise ValueError("progression lifecycle stages must be unique")
        if names != sorted(names, key=lambda value: STAGE_ORDER[value]):
            raise ValueError("progression lifecycle stages must be strictly ordered")
        if levels != sorted(set(levels)):
            raise ValueError("progression target levels must be unique and increasing")
        if len(artifacts_seen) != len(set(artifacts_seen)):
            raise ValueError("each progression stage requires a distinct artifact")
        if self.stages[-1].artifact_id != self.target_final_artifact_id:
            raise ValueError("target_final_artifact_id must identify the last stage")
        if self.stages[0].changes_from_previous:
            raise ValueError("first progression stage cannot carry changes_from_previous")
        for stage in self.stages[1:]:
            if not stage.changes_from_previous or not stage.transition_requirements:
                raise ValueError(
                    "later progression stages require typed changes and transition gates"
                )
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


def progression_routes_dir() -> Path:
    return (paths.user_data_dir() / "build-progression-routes").resolve()


def save_progression_route(payload: dict[str, Any]) -> dict[str, Any]:
    """Bind an ordered route to separately trusted, loadable PoB artifacts."""

    try:
        proposal = ProgressionRouteProposal.model_validate(payload)
    except ValidationError as exc:
        return _validation_rejected(exc)
    facts: list[dict[str, Any]] = []
    for stage in proposal.stages:
        fact = _trusted_artifact_fact(stage.artifact_id)
        if fact is None:
            return models.rejected("progression_stage_artifact_not_trusted")
        if fact["level"] != stage.target_level:
            return models.rejected("progression_stage_level_mismatch")
        if fact["class"].casefold() != proposal.class_shell.casefold():
            return models.rejected("progression_class_shell_mismatch")
        facts.append(fact)
    if len({item["sourceHash"] for item in facts}) != len(facts):
        return models.rejected("progression_duplicate_snapshot")
    if any(
        item["gamePatch"] != proposal.version_context.game_patch
        or item["passiveTreeVersion"] != proposal.version_context.passive_tree_version
        or item["pobVersionOrCommit"] != proposal.version_context.pob_version_or_commit
        for item in facts
    ):
        return models.rejected("progression_version_context_mismatch")

    route_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schemaVersion": PROGRESSION_SCHEMA_VERSION,
        "routeId": route_id,
        "proposal": proposal.model_dump(mode="json", by_alias=True),
        "artifactFacts": facts,
        "createdAt": now,
        "localOnly": True,
        "containsRawPob": False,
    }
    root = progression_routes_dir()
    final_dir = root / route_id
    temp_dir = root / f".{route_id}.{uuid4().hex}.tmp"
    try:
        _ensure_safe(manifest)
        root.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir()
        (temp_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_dir.replace(final_dir)
    except (OSError, ValueError):
        shutil.rmtree(temp_dir, ignore_errors=True)
        return models.rejected("progression_route_write_failed")
    return {
        "status": "saved",
        "progressionRoute": _safe_manifest(manifest),
        "containsRawPob": False,
    }


def list_progression_routes() -> dict[str, Any]:
    manifests = _iter_manifests()
    manifests.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return {
        "status": "ok",
        "progressionRoutes": [_safe_manifest(item) for item in manifests],
        "containsRawPob": False,
    }


def load_progression_stage(
    active_engine: Any, *, route_id: str, lifecycle_stage: str
) -> dict[str, Any]:
    manifest = _read_manifest(route_id)
    if manifest is None:
        return models.rejected("progression_route_not_found")
    normalized = models.normalize_lifecycle_stages([lifecycle_stage])
    stage_name = normalized[0] if normalized else lifecycle_stage
    stage = next(
        (
            item
            for item in manifest["proposal"]["stages"]
            if item.get("lifecycleStage") == stage_name
        ),
        None,
    )
    if stage is None:
        return models.rejected("progression_stage_not_found")
    loaded = artifacts.load_final_build_artifact(active_engine, artifact_id=stage["artifactId"])
    if loaded.get("status") != "loaded":
        return models.rejected("progression_stage_artifact_not_trusted")
    return {
        "status": "loaded",
        "routeId": route_id,
        "stage": stage,
        "activeBuild": loaded.get("activeBuild", {}),
        "containsRawPob": False,
    }


def _trusted_artifact_fact(artifact_id: str) -> dict[str, Any] | None:
    verified = artifacts.read_final_build_artifact_for_export(artifact_id)
    if verified is None:
        return None
    manifest, _xml = verified
    try:
        level = int(manifest.safe_summary.get("level") or "0")
        class_shell = str(manifest.safe_summary.get("class") or "").strip()
    except (TypeError, ValueError):
        return None
    if not 1 <= level <= 100 or not class_shell:
        return None
    return {
        "artifactId": manifest.artifact_id,
        "sourceHash": manifest.source_hash,
        "class": class_shell,
        "ascendancy": str(manifest.safe_summary.get("ascendancy") or ""),
        "level": level,
        "mainSkill": str(manifest.safe_summary.get("mainSkill") or ""),
        "gamePatch": manifest.version_context.game_patch,
        "passiveTreeVersion": manifest.version_context.passive_tree_version,
        "pobVersionOrCommit": manifest.version_context.pob_version_or_commit,
        "judgePassed": True,
    }


def _iter_manifests() -> list[dict[str, Any]]:
    root = progression_routes_dir()
    if not root.is_dir():
        return []
    return [value for child in root.iterdir() if (value := _read_manifest(child.name)) is not None]


def _read_manifest(route_id: str) -> dict[str, Any] | None:
    try:
        canonical = str(UUID(route_id))
    except (AttributeError, TypeError, ValueError):
        return None
    if canonical != route_id:
        return None
    path = (progression_routes_dir() / canonical / "manifest.json").resolve()
    try:
        path.relative_to(progression_routes_dir())
        payload = json.loads(path.read_text(encoding="utf-8"))
        proposal = ProgressionRouteProposal.model_validate(payload.get("proposal"))
        _ensure_safe(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        return None
    if (
        payload.get("schemaVersion") != PROGRESSION_SCHEMA_VERSION
        or payload.get("routeId") != canonical
        or not isinstance(payload.get("artifactFacts"), list)
        or len(payload["artifactFacts"]) != len(proposal.stages)
    ):
        return None
    for stage, stored_fact in zip(proposal.stages, payload["artifactFacts"], strict=True):
        current_fact = _trusted_artifact_fact(stage.artifact_id)
        if current_fact is None or stored_fact != current_fact:
            return None
    payload["proposal"] = proposal.model_dump(mode="json", by_alias=True)
    return payload


def _safe_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    proposal = manifest["proposal"]
    return {
        "routeId": manifest["routeId"],
        "routeName": proposal["routeName"],
        "classShell": proposal["classShell"],
        "targetFinalArtifactId": proposal["targetFinalArtifactId"],
        "stages": proposal["stages"],
        "routeSummary": proposal["routeSummary"],
        "versionContext": proposal["versionContext"],
        "createdAt": manifest["createdAt"],
        "localOnly": True,
    }


def _validate_safe_refs(values: list[str]) -> None:
    if len(values) != len(set(values)) or any(not _SAFE_REF.fullmatch(value) for value in values):
        raise ValueError("evidence refs must be unique safe references")


def _ensure_safe(value: Any) -> None:
    if copy_safety.find_forbidden_paths(value) or copy_safety.durable_knowledge_flags(value):
        raise ValueError("unsafe progression payload")


def _validation_rejected(exc: ValidationError) -> dict[str, Any]:
    first: Any = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", ())) or "input"
    return models.rejected(
        "invalid_progression_route", caveats=[f"{loc}: {first.get('msg', '')}"[:240]]
    )
