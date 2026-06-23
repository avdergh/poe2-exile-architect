"""Shared contracts for live freshness evidence providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from .models import FreshnessEvidence


class CacheState(StrEnum):
    FRESH = "fresh"
    REFRESHED = "refreshed"
    REVALIDATED = "revalidated"
    FALLBACK = "fallback"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class CachePolicy:
    refresh_after: timedelta
    reject_after: timedelta
    minimum_force_interval: timedelta = timedelta(seconds=60)

    def __post_init__(self) -> None:
        for field_name in ("refresh_after", "reject_after", "minimum_force_interval"):
            value = getattr(self, field_name)
            if not isinstance(value, timedelta):
                raise TypeError(f"{field_name} must be a timedelta")
        if self.refresh_after < timedelta(0):
            raise ValueError("refresh_after must be non-negative")
        if self.reject_after < self.refresh_after:
            raise ValueError("reject_after must be greater than or equal to refresh_after")
        if self.minimum_force_interval <= timedelta(0):
            raise ValueError("minimum_force_interval must be positive")


@dataclass(frozen=True, slots=True)
class ProviderResult:
    source: str
    evidence: tuple[FreshnessEvidence, ...]
    cache_state: CacheState
    diagnostics: tuple[str, ...]
    duration_ms: int


class EvidenceProvider(Protocol):
    name: str
    policy: CachePolicy

    def collect(
        self,
        *,
        now: datetime,
        force_refresh: bool = False,
    ) -> ProviderResult: ...
