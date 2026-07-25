"""Verified multi-stage progression routes built from trusted Phase 5 artifacts."""

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

from . import artifacts, models, progression_costs, progression_models


PROGRESSION_SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
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
QualityStatus = Literal["verified", "limited"]
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
        _ensure_authored_text(
            {
                "subject": self.subject,
                "replaces": self.replaces,
                "reason": self.reason,
            }
        )
        return self


class ProgressionStageV2(models.StrictModel):
    stage_id: str = Field(pattern=r"^stage:[A-Za-z0-9\-]{3,100}$")
    lifecycle_stage: models.LIFECYCLE_STAGE
    route_role: progression_models.RouteRole
    target_level: int = Field(ge=1, le=100)
    artifact_id: str = Field(pattern=r"^final-build:[A-Za-z0-9\-]{3,100}$")
    purpose: str = Field(min_length=1, max_length=320)
    play_pattern: str = Field(min_length=1, max_length=500)
    evidence_status: progression_models.EvidenceStatus
    source_refs: list[str] = Field(default_factory=list, max_length=12)
    changes_from_previous: list[ProgressionChange] = Field(default_factory=list, max_length=24)
    transition_bridge: progression_models.TransitionBridge | None = None
    acquisition_priorities: list[str] = Field(default_factory=list, max_length=12)
    caveats: list[str] = Field(default_factory=list, max_length=12)
    cost_profile_ref: str | None = Field(default=None, max_length=240)
    cost_profile: progression_models.StageCostSummary | None = None

    @field_validator("lifecycle_stage", mode="before")
    @classmethod
    def _normalize_stage(cls, value: Any) -> Any:
        normalized = models.normalize_lifecycle_stages([value])
        return normalized[0] if normalized else value

    @model_validator(mode="after")
    def _safe(self) -> "ProgressionStageV2":
        _validate_safe_refs(self.source_refs)
        if self.cost_profile_ref is not None:
            _validate_safe_refs([self.cost_profile_ref])
        if (self.cost_profile_ref is None) != (self.cost_profile is None):
            raise ValueError("stage cost profile ref and summary must appear together")
        if (
            self.cost_profile is not None
            and self.cost_profile_ref != self.cost_profile.cost_profile_ref
        ):
            raise ValueError("stage cost profile ref mismatch")
        _ensure_authored_text(
            {
                "purpose": self.purpose,
                "playPattern": self.play_pattern,
                "acquisitionPriorities": self.acquisition_priorities,
                "caveats": self.caveats,
            }
        )
        return self


class ProgressionRouteProposalV2(models.VersionedSafeModel):
    route_name: str = Field(min_length=1, max_length=120)
    class_shell: str = Field(min_length=1, max_length=120)
    target_artifact_id: str = Field(pattern=r"^final-build:[A-Za-z0-9\-]{3,100}$")
    stages: list[ProgressionStageV2] = Field(min_length=2, max_length=5)
    route_summary: str = Field(min_length=1, max_length=800)
    starter_research_packet_id: str | None = Field(
        default=None,
        pattern=r"^starter-research:[A-Za-z0-9\-]{3,100}$",
    )

    @model_validator(mode="after")
    def _ordered_route(self) -> "ProgressionRouteProposalV2":
        stage_ids = [stage.stage_id for stage in self.stages]
        levels = [stage.target_level for stage in self.stages]
        artifacts_seen = [stage.artifact_id for stage in self.stages]
        order = [STAGE_ORDER[str(stage.lifecycle_stage)] for stage in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("progression stage ids must be unique")
        if order != sorted(order):
            raise ValueError("progression lifecycle stages must be non-decreasing")
        if levels != sorted(set(levels)):
            raise ValueError("progression target levels must be unique and increasing")
        if len(artifacts_seen) != len(set(artifacts_seen)):
            raise ValueError("each progression stage requires a distinct artifact")
        if self.stages[-1].artifact_id != self.target_artifact_id:
            raise ValueError("target_artifact_id must identify the last stage")
        if self.stages[0].changes_from_previous or self.stages[0].transition_bridge:
            raise ValueError("first progression stage cannot carry transition details")
        role_order = {
            "starter_bootstrap": 0,
            "starter_established": 1,
            "transition": 2,
            "target": 3,
        }
        roles = [role_order[stage.route_role] for stage in self.stages]
        if (
            self.stages[0].route_role not in {"starter_bootstrap", "starter_established"}
            or self.stages[-1].route_role not in {"transition", "target"}
            or roles != sorted(roles)
            or any(stage.route_role == "target" for stage in self.stages[:-1])
        ):
            raise ValueError("route roles must progress from starter to transition/target")
        for stage in self.stages[1:]:
            if not stage.changes_from_previous or stage.transition_bridge is None:
                raise ValueError(
                    "later progression stages require typed changes and a transition bridge"
                )
        _ensure_authored_text(
            {
                "routeName": self.route_name,
                "classShell": self.class_shell,
                "routeSummary": self.route_summary,
            }
        )
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


# Read-only compatibility contracts for manifests written before Route v2.
class _LegacyTransitionRequirement(models.StrictModel):
    kind: Literal[
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
    description: str = Field(min_length=1, max_length=320)
    status: Literal["satisfied", "required", "unverified"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _valid(self) -> "_LegacyTransitionRequirement":
        _validate_safe_refs(self.evidence_refs)
        if self.status == "satisfied" and not self.evidence_refs:
            raise ValueError("satisfied transition requirement requires evidence")
        return self


class _LegacyProgressionStage(models.StrictModel):
    lifecycle_stage: models.LIFECYCLE_STAGE
    target_level: int = Field(ge=1, le=100)
    artifact_id: str = Field(pattern=r"^final-build:[A-Za-z0-9\-]{3,100}$")
    purpose: str = Field(min_length=1, max_length=320)
    play_pattern: str = Field(min_length=1, max_length=500)
    changes_from_previous: list[ProgressionChange] = Field(default_factory=list, max_length=24)
    transition_requirements: list[_LegacyTransitionRequirement] = Field(
        default_factory=list, max_length=12
    )
    acquisition_priorities: list[str] = Field(default_factory=list, max_length=12)
    caveats: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("lifecycle_stage", mode="before")
    @classmethod
    def _normalize_stage(cls, value: Any) -> Any:
        normalized = models.normalize_lifecycle_stages([value])
        return normalized[0] if normalized else value


class _LegacyProgressionRouteProposal(models.VersionedSafeModel):
    route_name: str = Field(min_length=1, max_length=120)
    class_shell: str = Field(min_length=1, max_length=120)
    target_final_artifact_id: str = Field(pattern=r"^final-build:[A-Za-z0-9\-]{3,100}$")
    stages: list[_LegacyProgressionStage] = Field(min_length=2, max_length=8)
    route_summary: str = Field(min_length=1, max_length=800)

    @model_validator(mode="after")
    def _ordered(self) -> "_LegacyProgressionRouteProposal":
        names = [str(stage.lifecycle_stage) for stage in self.stages]
        levels = [stage.target_level for stage in self.stages]
        if len(names) != len(set(names)):
            raise ValueError("legacy progression lifecycle stages must be unique")
        if names != sorted(names, key=lambda value: STAGE_ORDER[value]):
            raise ValueError("legacy progression stages must be strictly ordered")
        if levels != sorted(set(levels)):
            raise ValueError("legacy progression levels must increase")
        if self.stages[-1].artifact_id != self.target_final_artifact_id:
            raise ValueError("legacy target artifact must identify last stage")
        if self.stages[0].changes_from_previous:
            raise ValueError("legacy first stage cannot carry changes")
        for stage in self.stages[1:]:
            if not stage.changes_from_previous or not stage.transition_requirements:
                raise ValueError("legacy later stages require changes and transition requirements")
        return self


# Keep the public Python name available for older integrations.
ProgressionRouteProposal = ProgressionRouteProposalV2
ProgressionStage = ProgressionStageV2
TransitionRequirement = progression_models.TransitionRequirement


def progression_routes_dir() -> Path:
    return (paths.user_data_dir() / "build-progression-routes").resolve()


def save_progression_route(
    payload: dict[str, Any],
    *,
    route_id: str | None = None,
) -> dict[str, Any]:
    """Write a Route v2 manifest bound to separately trusted milestone artifacts."""

    normalized = _normalize_submission(payload)
    try:
        proposal = ProgressionRouteProposalV2.model_validate(normalized)
    except ValidationError as exc:
        return _validation_rejected(exc)
    for stage in proposal.stages:
        if stage.cost_profile is None:
            continue
        receipt = progression_costs.read_trusted_cost_profile(
            stage.cost_profile.cost_profile_ref,
            stage_id=stage.stage_id,
            allow_expired=True,
        )
        if receipt is None:
            return models.rejected("progression_cost_profile_not_trusted")
        expected = stage.cost_profile.model_dump(mode="json", by_alias=True)
        if {key: receipt.get(key) for key in expected} != expected:
            return models.rejected("progression_cost_profile_mismatch")
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
        item["league"] != proposal.version_context.league
        or item["ruleset"] != proposal.version_context.ruleset
        or item["gamePatch"] != proposal.version_context.game_patch
        or item["passiveTreeVersion"] != proposal.version_context.passive_tree_version
        or item["pobVersionOrCommit"] != proposal.version_context.pob_version_or_commit
        or item["graphSnapshotId"] != proposal.version_context.graph_snapshot_id
        for item in facts
    ):
        return models.rejected("progression_version_context_mismatch")

    if route_id is None:
        route_id = str(uuid4())
    else:
        try:
            canonical_route_id = str(UUID(route_id))
        except (AttributeError, TypeError, ValueError):
            return models.rejected("invalid_progression_route_id")
        if canonical_route_id != route_id:
            return models.rejected("invalid_progression_route_id")
    now = datetime.now(timezone.utc).isoformat()
    quality_status: QualityStatus = (
        "limited"
        if (
            any(item["qualityLimited"] for item in facts)
            or any(stage.evidence_status != "supported" for stage in proposal.stages)
            or any(stage.cost_profile is None for stage in proposal.stages)
            or proposal.stages[-1].route_role != "target"
        )
        else "verified"
    )
    manifest = {
        "schemaVersion": PROGRESSION_SCHEMA_VERSION,
        "routeId": route_id,
        "proposal": proposal.model_dump(mode="json", by_alias=True),
        "artifactFacts": facts,
        "qualityStatus": quality_status,
        "createdAt": now,
        "localOnly": True,
        "containsRawPob": False,
    }
    root = progression_routes_dir()
    final_dir = root / route_id
    if final_dir.exists():
        existing = _read_manifest(route_id)
        if (
            existing is not None
            and existing.get("proposal") == manifest["proposal"]
            and existing.get("artifactFacts") == manifest["artifactFacts"]
            and existing.get("qualityStatus") == manifest["qualityStatus"]
        ):
            return {
                "status": "saved",
                "idempotent": True,
                "progressionRoute": _safe_manifest(existing),
                "containsRawPob": False,
            }
        return models.rejected("progression_route_id_conflict")
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
    active_engine: Any,
    *,
    route_id: str,
    stage_id: str | None = None,
    lifecycle_stage: str | None = None,
) -> dict[str, Any]:
    """Load by stable stage id; lifecycle selection remains for unique legacy-style matches."""

    manifest = _read_manifest(route_id)
    if manifest is None:
        return models.rejected("progression_route_not_found")
    stages = manifest["proposal"]["stages"]
    if stage_id:
        matches = [item for item in stages if item.get("stageId") == stage_id]
    elif lifecycle_stage:
        normalized = models.normalize_lifecycle_stages([lifecycle_stage])
        stage_name = normalized[0] if normalized else lifecycle_stage
        matches = [item for item in stages if item.get("lifecycleStage") == stage_name]
        if len(matches) > 1:
            return models.rejected("progression_stage_ambiguous")
    else:
        return models.rejected("progression_stage_selector_required")
    if not matches:
        return models.rejected("progression_stage_not_found")
    stage = matches[0]
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


def read_progression_route(route_id: str) -> dict[str, Any] | None:
    """Internal verified route read for progression delivery."""

    manifest = _read_manifest(route_id)
    return _safe_manifest(manifest) if manifest is not None else None


def _trusted_artifact_fact(artifact_id: str) -> dict[str, Any] | None:
    verified = artifacts.read_final_build_artifact_for_export(artifact_id)
    if verified is None:
        return None
    manifest, _xml = verified
    try:
        level = int(manifest.safe_summary.get("level") or "0")
        class_shell = str(manifest.safe_summary.get("class") or "").strip()
        run_id = str(manifest.run_id)
    except (AttributeError, TypeError, ValueError):
        return None
    if not 1 <= level <= 100 or not class_shell or not run_id:
        return None
    judge = getattr(manifest, "judge_report", None)
    playability = list(getattr(judge, "playability_failures", []) or [])
    quality_warnings = list(getattr(judge, "quality_warnings", []) or [])
    caveats = list(getattr(judge, "caveats", []) or [])
    score_applicability = str(getattr(judge, "score_applicability", "unknown") or "unknown")
    modelability = str(getattr(judge, "modelability_status", "") or "")
    quality_limited = bool(
        playability or score_applicability != "applicable" or modelability.casefold() != "full"
    )
    return {
        "artifactId": manifest.artifact_id,
        "runId": run_id,
        "sourceHash": manifest.source_hash,
        "class": class_shell,
        "ascendancy": str(manifest.safe_summary.get("ascendancy") or ""),
        "level": level,
        "mainSkill": str(manifest.safe_summary.get("mainSkill") or ""),
        "league": manifest.version_context.league,
        "ruleset": manifest.version_context.ruleset,
        "gamePatch": manifest.version_context.game_patch,
        "passiveTreeVersion": manifest.version_context.passive_tree_version,
        "pobVersionOrCommit": manifest.version_context.pob_version_or_commit,
        "graphSnapshotId": manifest.version_context.graph_snapshot_id,
        "researchMemoryRef": manifest.version_context.research_memory_ref,
        "judgePassed": True,
        "judgePlayabilityFailures": playability,
        "judgeQualityWarnings": quality_warnings,
        "judgeCaveats": caveats,
        "judgeScoreApplicability": score_applicability,
        "judgeModelabilityStatus": modelability or None,
        "qualityLimited": quality_limited,
    }


def _legacy_artifact_fact(artifact_id: str) -> dict[str, Any] | None:
    fact = _trusted_artifact_fact(artifact_id)
    if fact is None:
        return None
    return {
        key: fact[key]
        for key in (
            "artifactId",
            "sourceHash",
            "class",
            "ascendancy",
            "level",
            "mainSkill",
            "gamePatch",
            "passiveTreeVersion",
            "pobVersionOrCommit",
            "judgePassed",
        )
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
        _ensure_safe(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    schema = payload.get("schemaVersion")
    if schema == PROGRESSION_SCHEMA_VERSION:
        return _read_v2_manifest(payload, canonical)
    if schema == LEGACY_SCHEMA_VERSION:
        return _read_legacy_manifest(payload, canonical)
    return None


def _read_v2_manifest(payload: dict[str, Any], route_id: str) -> dict[str, Any] | None:
    try:
        proposal = ProgressionRouteProposalV2.model_validate(payload.get("proposal"))
    except ValidationError:
        return None
    if (
        payload.get("routeId") != route_id
        or not isinstance(payload.get("artifactFacts"), list)
        or len(payload["artifactFacts"]) != len(proposal.stages)
    ):
        return None
    for stage, stored_fact in zip(proposal.stages, payload["artifactFacts"], strict=True):
        current_fact = _trusted_artifact_fact(stage.artifact_id)
        if current_fact is None or stored_fact != current_fact:
            return None
    normalized = dict(payload)
    normalized["proposal"] = proposal.model_dump(mode="json", by_alias=True)
    return normalized


def _read_legacy_manifest(payload: dict[str, Any], route_id: str) -> dict[str, Any] | None:
    try:
        proposal = _LegacyProgressionRouteProposal.model_validate(payload.get("proposal"))
    except ValidationError:
        return None
    if (
        payload.get("routeId") != route_id
        or not isinstance(payload.get("artifactFacts"), list)
        or len(payload["artifactFacts"]) != len(proposal.stages)
    ):
        return None
    for stage, stored_fact in zip(proposal.stages, payload["artifactFacts"], strict=True):
        current_fact = _legacy_artifact_fact(stage.artifact_id)
        if current_fact is None or stored_fact != current_fact:
            return None
    return _normalize_legacy_manifest(payload, proposal)


def _safe_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    proposal = manifest["proposal"]
    return {
        "schemaVersion": manifest["schemaVersion"],
        "routeId": manifest["routeId"],
        "routeName": proposal["routeName"],
        "classShell": proposal["classShell"],
        "targetArtifactId": proposal["targetArtifactId"],
        "stages": proposal["stages"],
        "routeSummary": proposal["routeSummary"],
        "starterResearchPacketId": proposal.get("starterResearchPacketId"),
        "versionContext": proposal["versionContext"],
        "artifactFacts": manifest["artifactFacts"],
        "qualityStatus": manifest.get("qualityStatus", "limited"),
        "createdAt": manifest["createdAt"],
        "localOnly": True,
    }


def _normalize_submission(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept the old proposal spelling at the boundary, but always write Route v2."""

    if "targetArtifactId" in payload:
        return payload
    if "targetFinalArtifactId" not in payload:
        return payload
    converted = dict(payload)
    converted["targetArtifactId"] = converted.pop("targetFinalArtifactId")
    stages: list[dict[str, Any]] = []
    raw_stages = payload.get("stages")
    if not isinstance(raw_stages, list):
        return converted
    for index, raw in enumerate(raw_stages):
        if not isinstance(raw, dict):
            stages.append(raw)
            continue
        stage = dict(raw)
        lifecycle = str(stage.get("lifecycleStage") or "unknown")
        stage.setdefault("stageId", _legacy_stage_id(index, lifecycle))
        stage.setdefault(
            "routeRole",
            "starter_bootstrap"
            if index == 0
            else ("target" if index == len(raw_stages) - 1 else "transition"),
        )
        stage.setdefault("evidenceStatus", "limited")
        stage.setdefault("sourceRefs", [])
        requirements = stage.pop("transitionRequirements", None)
        if index > 0 and "transitionBridge" not in stage and isinstance(requirements, list):
            converted_requirements = []
            for req_index, requirement in enumerate(requirements):
                if not isinstance(requirement, dict):
                    continue
                kind = str(requirement.get("kind") or "manual")
                kind = {
                    "item_available": "required_item_owned",
                    "resistance": "defense_gate",
                }.get(kind, kind)
                converted_requirements.append(
                    {
                        "requirementId": f"gate:legacy-{index}-{req_index}",
                        "kind": kind,
                        "description": requirement.get("description"),
                        "status": requirement.get("status", "required"),
                        "blocking": kind not in {"budget", "price"},
                        "evidenceRefs": requirement.get("evidenceRefs") or [],
                    }
                )
            stage["transitionBridge"] = {
                "bridgeId": f"bridge:legacy-{index}",
                "summary": f"Legacy transition into milestone {index + 1}.",
                "requirements": converted_requirements,
                "fallbackPlan": "Remain on the previous verified stage until the gates are met.",
            }
        stages.append(stage)
    converted["stages"] = stages
    return converted


def _normalize_legacy_manifest(
    payload: dict[str, Any],
    proposal: _LegacyProgressionRouteProposal,
) -> dict[str, Any]:
    converted = _normalize_submission(proposal.model_dump(mode="json", by_alias=True))
    return {
        "schemaVersion": LEGACY_SCHEMA_VERSION,
        "routeId": payload["routeId"],
        "proposal": converted,
        "artifactFacts": payload["artifactFacts"],
        "qualityStatus": "limited",
        "createdAt": payload["createdAt"],
        "localOnly": True,
        "containsRawPob": False,
    }


def _legacy_stage_id(index: int, lifecycle_stage: str) -> str:
    safe = re.sub(r"[^a-z0-9-]", "-", lifecycle_stage.casefold().replace("_", "-"))
    return f"stage:legacy-{index}-{safe[:40]}"


def _validate_safe_refs(values: list[str]) -> None:
    if len(values) != len(set(values)) or any(not _SAFE_REF.fullmatch(value) for value in values):
        raise ValueError("evidence refs must be unique safe references")


def _ensure_safe(value: Any) -> None:
    if (
        copy_safety.find_forbidden_paths(value)
        or copy_safety.durable_knowledge_flags(value)
        or copy_safety.contains_raw_url(value)
    ):
        raise ValueError("unsafe progression payload")


def _ensure_authored_text(value: Any) -> None:
    if copy_safety.copyability_flags(value) or copy_safety.contains_raw_url(value):
        raise ValueError("copyable material is forbidden in progression text")


def _validation_rejected(exc: ValidationError) -> dict[str, Any]:
    first: Any = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", ())) or "input"
    return models.rejected(
        "invalid_progression_route", caveats=[f"{loc}: {first.get('msg', '')}"[:240]]
    )
