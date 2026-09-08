"""Reviewed, patch-bound league identities; tree releases do not identify live leagues."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from .models import ClaimDimension, Component, FreshnessEvidence, SourceStatus, VersionClaim

MANIFEST = Path(__file__).resolve().parents[2] / "data" / "compatibility" / "leagues.json"


def league_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def ruleset(now: datetime, game_patch: str | None = None) -> dict[str, Any] | None:
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        matches = [
            row
            for row in data["rulesets"]
            if datetime.fromisoformat(row["validFrom"].replace("Z", "+00:00"))
            <= now
            < datetime.fromisoformat(row["validUntil"].replace("Z", "+00:00"))
            and (game_patch is None or row["gamePatch"] == game_patch)
        ]
        return matches[0] if len(matches) == 1 else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def default_league(now: datetime) -> str | None:
    row = ruleset(now)
    return str(row["defaultLeague"]) if row is not None else None


def bind_league_evidence(
    evidence: tuple[FreshnessEvidence, ...], *, now: datetime, target_league: str | None = None
) -> tuple[FreshnessEvidence, ...]:
    """Use reviewed identities only when a current official patch corroborates the ruleset."""
    patches = {
        claim.value
        for item in evidence
        if item.source == "ggg-patch" and item.status is SourceStatus.CURRENT
        for claim in item.claims
        if claim.key is ClaimDimension.GAME_PATCH
    }
    if len(patches) != 1:
        return evidence
    row = ruleset(now, next(iter(patches)))
    if row is None:
        return evidence
    requested = target_league or str(row["defaultLeague"])
    matches = [
        name for name in row["activeLeagues"] if league_token(name) == league_token(requested)
    ]
    # An unsupported selection remains explicit unknown evidence, never a default fallback.
    selected = matches[0] if len(matches) == 1 else None
    kept = tuple(
        item
        for item in evidence
        if not (item.source == "ggg-tree" and item.component is Component.LEAGUE)
    )
    return (
        *kept,
        FreshnessEvidence(
            component=Component.LEAGUE,
            source="reviewed-ggg-league",
            source_url=str(row["sourceUrl"]),
            observed_at=datetime.fromisoformat(row["verifiedAt"].replace("Z", "+00:00")),
            version=selected,
            status=SourceStatus.CURRENT if selected else SourceStatus.UNKNOWN,
            claims=(VersionClaim(ClaimDimension.LEAGUE, selected),) if selected else (),
        ),
    )
