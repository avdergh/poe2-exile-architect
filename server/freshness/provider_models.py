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
