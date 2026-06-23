"""Application service shared by MCP, CLI and future background jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import providers
from .evaluator import evaluate_freshness
from .models import FreshnessManifest


def get_freshness_report(observed_at: datetime | None = None) -> dict[str, Any]:
    """Return the strict local report without upgrading absent live evidence."""

    now = observed_at or datetime.now(UTC)
    manifest = FreshnessManifest(
        evidence=providers.collect_local_evidence(now),
        evaluated_at=now,
    )
    return evaluate_freshness(manifest).to_dict()
