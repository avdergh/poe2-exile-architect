"""Public freshness-domain API."""

from .evaluator import evaluate_freshness
from .models import (
    ClaimDimension,
    Component,
    FreshnessDecision,
    FreshnessEvidence,
    FreshnessManifest,
    FreshnessReport,
    SourceStatus,
    VersionClaim,
)

__all__ = [
    "Component",
    "ClaimDimension",
    "FreshnessDecision",
    "FreshnessEvidence",
    "FreshnessManifest",
    "FreshnessReport",
    "SourceStatus",
    "VersionClaim",
    "evaluate_freshness",
]
