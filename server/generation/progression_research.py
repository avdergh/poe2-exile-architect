"""Safe, patch-scoped starter research packets for Phase 8.

The external Agent owns network search and interpretation.  This module only validates a
bounded structured submission, converts source URLs to opaque references immediately, derives
an evidence status, and caches the safe packet locally.  It never downloads a page or calls a
model.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator, model_validator

from server import paths
from server.knowledge import copy_safety

from . import models


CACHE_SCHEMA_VERSION = 2
CACHE_TTL = timedelta(days=7)
SourceKind = Literal[
    "structured_guide",
    "official_forum",
    "creator_guide",
    "aggregator",
    "comment",
    "other",
]
ClaimKind = Literal[
    "skill_package",
    "ascendancy_choice",
    "passive_anchor",
    "weapon_direction",
    "resource_loop",
    "clear_duty",
    "boss_duty",
    "switch_signal",
    "gear_assumption",
    "failure_warning",
]
EvidenceStatus = Literal["supported", "limited", "limited_offline_inference"]
PacketStatus = Literal["active", "deprecated"]
Decision = Literal["adopted", "caveated", "rejected"]
StarterSkillDuty = Literal[
    "clear",
    "boss",
    "setup",
    "payoff",
    "mobility",
    "defense",
    "recovery",
    "resource",
]
_SAFE_REF = re.compile(r"^[A-Za-z0-9_.:/\-]{3,240}$")


class StarterSourceInput(models.StrictModel):
    """Transient source descriptor. ``source_url`` is never serialized to cache."""

    source_id: str = Field(pattern=r"^source:[A-Za-z0-9\-]{3,80}$")
    source_url: str = Field(min_length=8, max_length=1000)
    source_kind: SourceKind
    title: str = Field(min_length=1, max_length=160)
    claimed_patch: str = Field(default="", max_length=40)
    updated_at: str = Field(default="", max_length=40)
    explicit_level_bands: bool = False
    summary: str = Field(min_length=1, max_length=360)

    @field_validator("source_url")
    @classmethod
    def _http_source(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("starter source must be an http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("starter source URL cannot contain credentials")
        return value


class StarterSource(models.StrictModel):
    source_ref: str
    host: str = Field(min_length=1, max_length=120)
    source_kind: SourceKind
    title: str = Field(min_length=1, max_length=160)
    claimed_patch: str = Field(default="", max_length=40)
    updated_at: str = Field(default="", max_length=40)
    exact_patch: bool
    explicit_level_bands: bool
    summary: str = Field(min_length=1, max_length=360)

    @model_validator(mode="after")
    def _safe(self) -> "StarterSource":
        _safe_ref(self.source_ref)
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


class StarterSkillRole(models.StrictModel):
    component_key: str = Field(min_length=3, max_length=240)
    skill_name: str = Field(min_length=1, max_length=160)
    duties: list[StarterSkillDuty] = Field(min_length=1, max_length=8)
    provides: list[str] = Field(default_factory=list, max_length=8)
    requires: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _consistent(self) -> "StarterSkillRole":
        _safe_ref(self.component_key)
        if not self.component_key.startswith("skill:"):
            raise ValueError("starter skill roles require resolved active-skill keys")
        if len(self.duties) != len(set(self.duties)):
            raise ValueError("starter skill duties must be unique")
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


class StarterClaim(models.StrictModel):
    claim_id: str = Field(pattern=r"^starter-claim:[A-Za-z0-9\-]{3,100}$")
    claim_kind: ClaimKind
    level_min: int = Field(ge=1, le=100)
    level_max: int = Field(ge=1, le=100)
    summary: str = Field(min_length=1, max_length=360)
    component_keys: list[str] = Field(default_factory=list, max_length=12)
    skill_roles: list[StarterSkillRole] = Field(default_factory=list, max_length=8)
    applicability_conditions: list[str] = Field(default_factory=list, max_length=8)
    exclusion_conditions: list[str] = Field(default_factory=list, max_length=8)
    source_refs: list[str] = Field(default_factory=list, max_length=6)
    verification_tasks: list[str] = Field(default_factory=list, max_length=8)
    evidence_status: EvidenceStatus = "limited"

    @model_validator(mode="after")
    def _consistent(self) -> "StarterClaim":
        if self.level_min > self.level_max:
            raise ValueError("starter claim level range must be increasing")
        _unique_safe_refs(self.component_keys)
        _unique_safe_refs(self.source_refs)
        role_keys = [item.component_key for item in self.skill_roles]
        if len(role_keys) != len(set(role_keys)):
            raise ValueError("starter skill roles must be unique per skill")
        if self.skill_roles and not set(role_keys).issubset(set(self.component_keys)):
            raise ValueError("starter skill roles must reference claim component keys")
        _ensure_safe(self.model_dump(mode="json", by_alias=True))
        return self


class StarterResearchSubmission(models.StrictModel):
    base_class: str = Field(min_length=1, max_length=80)
    game_patch: str = Field(min_length=1, max_length=40)
    passive_tree_version: str = Field(min_length=1, max_length=80)
    level_min: int = Field(default=1, ge=1, le=100)
    level_max: int = Field(ge=2, le=100)
    sources: list[StarterSourceInput] = Field(default_factory=list, max_length=6)
    claims: list[StarterClaim] = Field(min_length=1, max_length=24)
    contradictions: list[str] = Field(default_factory=list, max_length=8)
    unresolved_checks: list[str] = Field(default_factory=list, max_length=12)
    network_status: Literal["available", "unavailable"] = "available"

    @model_validator(mode="after")
    def _consistent(self) -> "StarterResearchSubmission":
        if self.level_min >= self.level_max:
            raise ValueError("starter research level range must be increasing")
        if self.network_status == "available" and not self.sources:
            raise ValueError("available starter research requires at least one source")
        if self.network_status == "unavailable" and self.sources:
            raise ValueError("unavailable network status cannot carry sources")
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("starter source ids must be unique")
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("starter claim ids must be unique")
        if any(
            claim.level_min < self.level_min or claim.level_max > self.level_max
            for claim in self.claims
        ):
            raise ValueError("starter claims must stay within the packet level range")
        if any(
            claim.claim_kind == "skill_package" and not claim.skill_roles for claim in self.claims
        ):
            raise ValueError("starter skill-package claims require structured skill roles")
        _ensure_safe(
            {
                "baseClass": self.base_class,
                "claims": [item.model_dump(mode="json", by_alias=True) for item in self.claims],
                "contradictions": self.contradictions,
                "unresolvedChecks": self.unresolved_checks,
            }
        )
        return self


class StarterEvidenceDecision(models.StrictModel):
    claim_id: str = Field(pattern=r"^starter-claim:[A-Za-z0-9\-]{3,100}$")
    decision: Decision
    application: str = Field(min_length=1, max_length=360)
    verification_refs: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _safe(self) -> "StarterEvidenceDecision":
        _unique_safe_refs(self.verification_refs)
        if self.decision == "adopted" and not self.verification_refs:
            raise ValueError("adopted starter evidence requires verification refs")
        _ensure_safe({"application": self.application})
        return self


class StarterEvidenceUse(models.StrictModel):
    packet_id: str = Field(pattern=r"^starter-research:[A-Za-z0-9\-]{3,100}$")
    decisions: list[StarterEvidenceDecision] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def _complete_unique_decisions(self) -> "StarterEvidenceUse":
        ids = [item.claim_id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("starter evidence decisions must be unique per claim")
        return self


class StarterResearchPacket(models.VersionedSafeModel):
    packet_schema_version: int = Field(default=1, ge=1, le=CACHE_SCHEMA_VERSION)
    packet_id: str = Field(pattern=r"^starter-research:[A-Za-z0-9\-]{3,100}$")
    base_class: str = Field(min_length=1, max_length=80)
    game_patch: str = Field(min_length=1, max_length=40)
    passive_tree_version: str = Field(min_length=1, max_length=80)
    level_min: int = Field(ge=1, le=100)
    level_max: int = Field(ge=2, le=100)
    sources: list[StarterSource] = Field(default_factory=list, max_length=6)
    claims: list[StarterClaim] = Field(min_length=1, max_length=24)
    contradictions: list[str] = Field(default_factory=list, max_length=8)
    unresolved_checks: list[str] = Field(default_factory=list, max_length=12)
    evidence_status: EvidenceStatus
    packet_status: PacketStatus = "active"
    created_at: str
    expires_at: str

    @model_validator(mode="after")
    def _consistent(self) -> "StarterResearchPacket":
        if self.version_context.game_patch != self.game_patch:
            raise ValueError("packet and version context patches must match")
        if self.version_context.passive_tree_version != self.passive_tree_version:
            raise ValueError("packet and version context tree versions must match")
        if self.level_min >= self.level_max:
            raise ValueError("starter packet level range must be increasing")
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("starter packet claim ids must be unique")
        if any(
            claim.level_min < self.level_min or claim.level_max > self.level_max
            for claim in self.claims
        ):
            raise ValueError("starter packet claims must stay within the packet level range")
        if self.packet_schema_version >= 2 and any(
            claim.claim_kind == "skill_package" and not claim.skill_roles for claim in self.claims
        ):
            raise ValueError("v2 starter skill-package claims require structured skill roles")
        refs = {source.source_ref for source in self.sources}
        if len(refs) != len(self.sources):
            raise ValueError("starter packet sources must be unique")
        for claim in self.claims:
            if not set(claim.source_refs).issubset(refs):
                raise ValueError("starter claim references an unknown source")
        if self.evidence_status == "limited_offline_inference":
            if self.sources or any(claim.source_refs for claim in self.claims):
                raise ValueError("offline inference cannot carry source-backed claims")
            if any(claim.evidence_status != "limited_offline_inference" for claim in self.claims):
                raise ValueError("offline packet claims must use offline evidence status")
        elif not self.sources:
            raise ValueError("online evidence status requires sources")
        else:
            sources_by_ref = {source.source_ref: source for source in self.sources}
            derived = [
                _evidence_status(
                    [sources_by_ref[reference] for reference in claim.source_refs],
                    network_status="available",
                )
                for claim in self.claims
            ]
            if any(
                claim.evidence_status != expected for claim, expected in zip(self.claims, derived)
            ):
                raise ValueError("starter claim evidence status does not match its sources")
            packet_evidence = (
                "supported"
                if derived and all(item == "supported" for item in derived)
                else "limited"
            )
            if self.evidence_status != packet_evidence:
                raise ValueError("starter packet evidence status does not match its claims")
        try:
            created = _parse_time(self.created_at)
            expires = _parse_time(self.expires_at)
        except ValueError as exc:
            raise ValueError("starter packet timestamps must be ISO-8601") from exc
        if expires <= created:
            raise ValueError("starter packet expiry must follow creation")
        _ensure_packet_safe(self.model_dump(mode="json", by_alias=True))
        return self


def intake_starter_research_packet(
    payload: dict[str, Any],
    *,
    version_context: dict[str, Any],
) -> dict[str, Any]:
    """Validate, sanitize and cache one external-Agent research packet."""

    try:
        submission = StarterResearchSubmission.model_validate(payload)
        version = models.VersionContext.model_validate(version_context)
    except ValidationError as exc:
        return _validation_rejected(exc)
    if (
        version.game_patch != submission.game_patch
        or version.passive_tree_version != submission.passive_tree_version
    ):
        return models.rejected("starter_research_version_mismatch")

    safe_sources: list[StarterSource] = []
    source_ref_map: dict[str, str] = {}
    for source in submission.sources:
        source_ref = copy_safety.safe_url_ref(source.source_url)
        host = _safe_host(source.source_url)
        try:
            safe_sources.append(
                StarterSource(
                    source_ref=source_ref,
                    host=host,
                    source_kind=source.source_kind,
                    title=source.title,
                    claimed_patch=source.claimed_patch,
                    updated_at=source.updated_at,
                    exact_patch=source.claimed_patch == submission.game_patch,
                    explicit_level_bands=source.explicit_level_bands,
                    summary=source.summary,
                )
            )
        except ValidationError as exc:
            return _validation_rejected(exc)
        source_ref_map[source.source_id] = source_ref

    safe_claims: list[StarterClaim] = []
    submitted_refs = {reference for claim in submission.claims for reference in claim.source_refs}
    valid_refs = {item.source_ref for item in safe_sources}
    # Accept either transient source ids or already-hashed refs at this boundary.
    sources_by_ref = {source.source_ref: source for source in safe_sources}
    for claim in submission.claims:
        remapped = [source_ref_map.get(reference, reference) for reference in claim.source_refs]
        claim_sources = [
            sources_by_ref[reference] for reference in remapped if reference in sources_by_ref
        ]
        safe_claims.append(
            claim.model_copy(
                update={
                    "source_refs": remapped,
                    "evidence_status": _evidence_status(
                        claim_sources,
                        network_status=submission.network_status,
                    ),
                }
            )
        )
    if submitted_refs and any(
        reference not in valid_refs and reference not in source_ref_map
        for reference in submitted_refs
    ):
        return models.rejected("starter_research_unknown_source_ref")

    evidence_status: EvidenceStatus = (
        "limited_offline_inference"
        if submission.network_status == "unavailable"
        else (
            "supported"
            if safe_claims and all(claim.evidence_status == "supported" for claim in safe_claims)
            else "limited"
        )
    )
    now = datetime.now(timezone.utc)
    try:
        packet = StarterResearchPacket(
            packet_schema_version=CACHE_SCHEMA_VERSION,
            packet_id=f"starter-research:{uuid4()}",
            base_class=submission.base_class,
            game_patch=submission.game_patch,
            passive_tree_version=submission.passive_tree_version,
            level_min=submission.level_min,
            level_max=submission.level_max,
            sources=safe_sources,
            claims=safe_claims,
            contradictions=submission.contradictions,
            unresolved_checks=submission.unresolved_checks,
            evidence_status=evidence_status,
            packet_status="active",
            created_at=now.isoformat(),
            expires_at=(now + CACHE_TTL).isoformat(),
            version_context=version,
            no_raw_material=True,
        )
    except ValidationError as exc:
        return _validation_rejected(exc)
    if not _write_packet(packet):
        return models.rejected("starter_research_cache_write_failed")
    return {
        "status": "accepted",
        "starterResearchPacket": packet.model_dump(mode="json", by_alias=True),
        "cacheStatus": "fresh",
        "containsRawWebMaterial": False,
        "containsFullUrls": False,
    }


def lookup_starter_research_cache(
    *,
    base_class: str,
    game_patch: str,
    passive_tree_version: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return an exact fresh packet, or a safe stale hint from the same season."""

    current = now or datetime.now(timezone.utc)
    candidates = _iter_packets()
    exact = [
        packet
        for packet in candidates
        if packet.base_class.casefold() == base_class.casefold()
        and packet.game_patch == game_patch
        and packet.passive_tree_version == passive_tree_version
        and packet.packet_status == "active"
    ]
    exact.sort(key=lambda item: item.created_at, reverse=True)
    if exact:
        packet = exact[0]
        schema_current = packet.packet_schema_version == CACHE_SCHEMA_VERSION
        fresh = _parse_time(packet.expires_at) > current and schema_current
        return {
            "status": "hit" if fresh else "stale",
            "cacheStatus": (
                "fresh"
                if fresh
                else (
                    "starter_role_schema_revalidation_required"
                    if not schema_current
                    else "expired_revalidation_required"
                )
            ),
            "starterResearchPacket": packet.model_dump(mode="json", by_alias=True),
            "mayAdoptWithoutRevalidation": fresh,
            "containsRawWebMaterial": False,
            "containsFullUrls": False,
        }

    same_class = [
        packet
        for packet in candidates
        if packet.base_class.casefold() == base_class.casefold()
        and packet.packet_status == "active"
    ]
    same_season = [
        packet
        for packet in same_class
        if _season_family(packet.game_patch) == _season_family(game_patch)
    ]
    if same_season:
        same_season.sort(key=lambda item: item.created_at, reverse=True)
        return {
            "status": "stale",
            "cacheStatus": "same_season_revalidation_required",
            "starterResearchPacket": same_season[0].model_dump(mode="json", by_alias=True),
            "mayAdoptWithoutRevalidation": False,
            "containsRawWebMaterial": False,
            "containsFullUrls": False,
        }
    return {
        "status": "miss",
        "cacheStatus": "cross_season_rejected" if same_class else "not_found",
        "mayAdoptWithoutRevalidation": False,
        "containsRawWebMaterial": False,
        "containsFullUrls": False,
    }


def deprecate_starter_research_packet(packet_id: str, reason: str) -> dict[str, Any]:
    """Mark a cached packet unusable without deleting its safe audit record."""

    if not _SAFE_REF.fullmatch(packet_id) or not reason.strip() or len(reason) > 320:
        return models.rejected("invalid_starter_research_deprecation")
    try:
        _ensure_safe({"reason": reason})
    except ValueError:
        return models.rejected("invalid_starter_research_deprecation")
    for path, packet in _iter_packet_files():
        if packet.packet_id != packet_id:
            continue
        updated = packet.model_copy(update={"packet_status": "deprecated"})
        payload = updated.model_dump(mode="json", by_alias=True)
        payload["deprecation"] = {
            "reason": copy_safety.safe_text(reason, limit=320),
            "deprecatedAt": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _atomic_json_write(path, payload)
        except OSError:
            return models.rejected("starter_research_cache_write_failed")
        return {
            "status": "deprecated",
            "packetId": packet_id,
            "containsRawWebMaterial": False,
        }
    return models.rejected("starter_research_packet_not_found")


def _evidence_status(
    sources: list[StarterSource],
    *,
    network_status: str,
) -> EvidenceStatus:
    if network_status == "unavailable":
        return "limited_offline_inference"
    qualifying_hosts = {
        source.host
        for source in sources
        if source.exact_patch and source.source_kind not in {"aggregator", "comment"}
    }
    complete_exact = any(
        source.exact_patch
        and source.explicit_level_bands
        and source.source_kind in {"structured_guide", "official_forum", "creator_guide"}
        for source in sources
    )
    return "supported" if len(qualifying_hosts) >= 2 or complete_exact else "limited"


def _write_packet(packet: StarterResearchPacket) -> bool:
    key = _cache_key(packet.base_class, packet.game_patch, packet.passive_tree_version)
    path = paths.starter_research_cache_dir() / f"{key}-{packet.packet_id.rsplit(':', 1)[-1]}.json"
    try:
        _atomic_json_write(path, packet.model_dump(mode="json", by_alias=True))
    except OSError:
        return False
    return True


def _iter_packets() -> list[StarterResearchPacket]:
    return [packet for _path, packet in _iter_packet_files()]


def _iter_packet_files() -> list[tuple[Path, StarterResearchPacket]]:
    root = paths.starter_research_cache_dir()
    if not root.is_dir():
        return []
    result: list[tuple[Path, StarterResearchPacket]] = []
    for path in root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.pop("deprecation", None)
            packet = StarterResearchPacket.model_validate(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError):
            continue
        result.append((path, packet))
    return result


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


def _safe_host(url: str) -> str:
    host = (urlparse(url).hostname or "unknown-host").casefold()
    if host.startswith("www."):
        host = host[4:]
    return re.sub(r"[^a-z0-9.-]", "-", host)[:120]


def _cache_key(base_class: str, game_patch: str, tree: str) -> str:
    raw = "\0".join((base_class.casefold(), game_patch, tree))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _season_family(patch: str) -> str:
    match = re.match(r"^\s*(\d+)\.(\d+)", patch)
    return f"{match.group(1)}.{match.group(2)}" if match else patch.strip().casefold()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _safe_ref(value: str) -> None:
    if not _SAFE_REF.fullmatch(value):
        raise ValueError("invalid safe reference")


def _unique_safe_refs(values: list[str]) -> None:
    if len(values) != len(set(values)):
        raise ValueError("safe references must be unique")
    for value in values:
        _safe_ref(value)


def _ensure_safe(value: Any) -> None:
    if (
        copy_safety.find_forbidden_paths(value)
        or copy_safety.copyability_flags(value)
        or copy_safety.contains_raw_url(value)
    ):
        raise ValueError("unsafe starter research payload")


def _ensure_packet_safe(value: Any) -> None:
    # UUID-backed safe ids look like a long hyphen chain to the generic gem-link detector.
    # Nested source and claim fragments already pass the stricter check above.
    if (
        copy_safety.find_forbidden_paths(value)
        or copy_safety.durable_knowledge_flags(value)
        or copy_safety.contains_raw_url(value)
    ):
        raise ValueError("unsafe starter research payload")


def _validation_rejected(exc: ValidationError) -> dict[str, Any]:
    first: Any = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", ())) or "input"
    return models.rejected(
        "invalid_starter_research_packet",
        caveats=[f"{loc}: {first.get('msg', '')}"[:240]],
    )
