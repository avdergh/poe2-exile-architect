"""Domain models for cross-source data freshness.

These types deliberately contain no network or MCP concerns. Providers can change without
changing the conservative decision contract consumed by build research.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import re
from typing import Any


class Component(StrEnum):
    GAME_PATCH = "game_patch"
    LEAGUE = "league"
    PASSIVE_TREE = "passive_tree"
    POB_ENGINE = "pob_engine"
    POB_DATA = "pob_data"
    CORPUS = "corpus"
    META_SNAPSHOT = "meta_snapshot"
    WIKI = "wiki"


class SourceStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    CONFLICTED = "conflicted"
    UNKNOWN = "unknown"


class ClaimDimension(StrEnum):
    GAME_PATCH = "game_patch"
    LEAGUE = "league"
    PASSIVE_TREE = "passive_tree"


class FreshnessDecision(StrEnum):
    VERIFIED_CURRENT = "verified_current"
    CURRENT_UNMODELLED = "current_unmodelled"
    BLOCKED_STALE = "blocked_stale"
    BLOCKED_CONFLICT = "blocked_conflict"
    BLOCKED_UNKNOWN = "blocked_unknown"


DEFAULT_REQUIRED_COMPONENTS = frozenset(
    {
        Component.GAME_PATCH,
        Component.LEAGUE,
        Component.PASSIVE_TREE,
        Component.POB_ENGINE,
        Component.POB_DATA,
        Component.CORPUS,
        Component.META_SNAPSHOT,
    }
)

REQUIRED_CLAIMS = {
    Component.GAME_PATCH: frozenset({ClaimDimension.GAME_PATCH}),
    Component.LEAGUE: frozenset({ClaimDimension.LEAGUE}),
    # Official tree evidence proves the tree/league snapshot, while the patch index proves the
    # live game patch. Requiring every tree record to also assert game_patch would reject real
    # provider output even when the separate GGG patch source and certified local sources agree.
    Component.PASSIVE_TREE: frozenset({ClaimDimension.PASSIVE_TREE}),
    Component.POB_ENGINE: frozenset({ClaimDimension.GAME_PATCH, ClaimDimension.PASSIVE_TREE}),
    Component.POB_DATA: frozenset({ClaimDimension.GAME_PATCH, ClaimDimension.PASSIVE_TREE}),
    Component.CORPUS: frozenset({ClaimDimension.GAME_PATCH, ClaimDimension.PASSIVE_TREE}),
    Component.META_SNAPSHOT: frozenset({ClaimDimension.LEAGUE, ClaimDimension.PASSIVE_TREE}),
}


@dataclass(frozen=True, slots=True)
class VersionClaim:
    """One compatibility dimension asserted by a source."""

    key: ClaimDimension
    value: str

    def __post_init__(self) -> None:
        try:
            key = (
                self.key
                if isinstance(self.key, ClaimDimension)
                else ClaimDimension(str(self.key).strip())
            )
        except ValueError as exc:
            raise ValueError(f"unknown claim dimension: {self.key!r}") from exc
        value = " ".join(self.value.split())
        if not value:
            raise ValueError("version claim key and value must be non-empty")
        if key is ClaimDimension.GAME_PATCH:
            value = value.lower().removeprefix("v")
        elif key is ClaimDimension.PASSIVE_TREE:
            value = value.lower().removeprefix("v").replace(".", "_").replace("-", "_")
        elif key is ClaimDimension.LEAGUE:
            value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
        if not value:
            raise ValueError("version claim key and value must be non-empty after normalization")
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "value", value)

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key.value, "value": self.value}


@dataclass(frozen=True, slots=True)
class FreshnessEvidence:
    component: Component
    source: str
    source_url: str
    observed_at: datetime
    version: str | None
    status: SourceStatus
    claims: tuple[VersionClaim, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.component, Component):
            raise TypeError("freshness evidence component must be a Component")
        if not isinstance(self.status, SourceStatus):
            raise TypeError("freshness evidence status must be a SourceStatus")
        claims = tuple(self.claims)
        if any(not isinstance(claim, VersionClaim) for claim in claims):
            raise TypeError("freshness evidence claims must contain VersionClaim values")
        if not self.source.strip():
            raise ValueError("freshness evidence source must be non-empty")
        if not self.source_url.strip():
            raise ValueError("freshness evidence source_url must be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("freshness evidence observed_at must be timezone-aware")
        version = self.version.strip() if self.version is not None else None
        object.__setattr__(self, "version", version or None)
        object.__setattr__(self, "claims", claims)
        keys = [claim.key for claim in claims]
        if len(keys) != len(set(keys)):
            raise ValueError("freshness evidence cannot repeat a claim key")

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component.value,
            "source": self.source,
            "source_url": self.source_url,
            "observed_at": self.observed_at.isoformat(),
            "version": self.version,
            "status": self.status.value,
            "claims": [claim.to_dict() for claim in self.claims],
        }


@dataclass(frozen=True, slots=True)
class FreshnessManifest:
    evidence: tuple[FreshnessEvidence, ...]
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    required_components: frozenset[Component] = DEFAULT_REQUIRED_COMPONENTS
    unmodelled_mechanics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        evidence = tuple(self.evidence)
        if any(not isinstance(item, FreshnessEvidence) for item in evidence):
            raise TypeError("freshness manifest evidence must contain FreshnessEvidence values")
        object.__setattr__(self, "evidence", evidence)
        if self.evaluated_at.tzinfo is None:
            raise ValueError("freshness manifest evaluated_at must be timezone-aware")
        required_components = frozenset(self.required_components)
        object.__setattr__(self, "required_components", required_components)
        if not required_components:
            raise ValueError("freshness manifest required_components must not be empty")
        if any(not isinstance(component, Component) for component in required_components):
            raise TypeError("required_components must contain Component values")
        missing_defaults = DEFAULT_REQUIRED_COMPONENTS - required_components
        if missing_defaults:
            names = ", ".join(sorted(component.value for component in missing_defaults))
            raise ValueError(f"required_components cannot omit safety baseline: {names}")
        if isinstance(self.unmodelled_mechanics, str):
            raise TypeError("unmodelled_mechanics must be a sequence of strings")
        mechanics = tuple(self.unmodelled_mechanics)
        if any(not isinstance(item, str) or not item.strip() for item in mechanics):
            raise TypeError("unmodelled_mechanics must contain non-empty strings")
        object.__setattr__(
            self,
            "unmodelled_mechanics",
            tuple(item.strip() for item in mechanics),
        )


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    decision: FreshnessDecision
    evidence: tuple[FreshnessEvidence, ...]
    active_evidence: tuple[FreshnessEvidence, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evaluated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "evidence": [item.to_dict() for item in self.evidence],
            "active_evidence": [item.to_dict() for item in self.active_evidence],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "evaluated_at": self.evaluated_at.isoformat(),
        }
