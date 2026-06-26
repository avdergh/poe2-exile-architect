"""Adapters that shape local installation metadata into freshness evidence."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..knowledge import db
from ..live import update as live_update
from .models import (
    ClaimDimension,
    Component,
    FreshnessEvidence,
    SourceStatus,
    VersionClaim,
)
from .pob import (
    DEFAULT_COMPATIBILITY_MANIFEST,
    PobParseError,
    load_compatibility_manifest,
    resolve_compatibility,
)


RELEASES_URL = "https://github.com/MaxWilk/poe2-build-mcp/releases"


@dataclass(frozen=True, slots=True)
class LocalCompatibility:
    game_patch: str
    passive_tree: str


def shape_validated_release(
    *,
    installed: dict[str, Any],
    corpus_info: dict[str, Any],
    observed_at: datetime,
    compatibility: LocalCompatibility | None = None,
) -> tuple[FreshnessEvidence, ...]:
    """Shape one checksum-validated local release without inferring live-game currency."""

    release_version = str(installed.get("version") or installed.get("app_version") or "").strip()
    pob_commit = str(installed.get("pob_commit") or "").strip()
    if not release_version and not pob_commit:
        return ()

    release_url = (
        f"{RELEASES_URL}/tag/{release_version}" if release_version.startswith("v") else RELEASES_URL
    )
    # Compatibility claims are authorized by data/compatibility/pob.json. The installed
    # metadata records what the release published, but it cannot grant claims by itself.
    release_claims = (
        (
            VersionClaim(ClaimDimension.PASSIVE_TREE, compatibility.passive_tree),
            VersionClaim(ClaimDimension.GAME_PATCH, compatibility.game_patch),
        )
        if compatibility is not None
        else ()
    )
    engine_status = SourceStatus.CURRENT if pob_commit else SourceStatus.UNKNOWN
    corpus_version = release_version or str(corpus_info.get("built_at") or "").strip()
    corpus_status = (
        SourceStatus.CURRENT
        if corpus_version and corpus_info.get("schema_version") is not None
        else SourceStatus.UNKNOWN
    )

    return (
        FreshnessEvidence(
            component=Component.POB_ENGINE,
            source="validated-release-engine",
            source_url=release_url,
            observed_at=observed_at,
            version=pob_commit or None,
            status=engine_status,
            claims=release_claims,
        ),
        FreshnessEvidence(
            component=Component.POB_DATA,
            source="validated-release-pob-data",
            source_url=release_url,
            observed_at=observed_at,
            version=pob_commit or None,
            status=engine_status,
            claims=release_claims,
        ),
        FreshnessEvidence(
            component=Component.CORPUS,
            source="validated-release-corpus",
            source_url=release_url,
            observed_at=observed_at,
            version=corpus_version or None,
            status=corpus_status,
            claims=release_claims,
        ),
    )


def collect_local_evidence(observed_at: datetime) -> tuple[FreshnessEvidence, ...]:
    """Read best-effort local evidence; missing metadata remains missing and blocks the gate."""

    try:
        installed = live_update.installed_meta()
    except (OSError, ValueError):
        installed = {}
    try:
        corpus_info = db.corpus_info()
    except (OSError, ValueError, sqlite3.Error):
        corpus_info = {}
    compatibility = _resolve_local_compatibility(installed)
    return shape_validated_release(
        installed=installed,
        corpus_info=corpus_info,
        observed_at=observed_at,
        compatibility=compatibility,
    )


def _resolve_local_compatibility(installed: dict[str, Any]) -> LocalCompatibility | None:
    pob_commit = str(installed.get("pob_commit") or "").strip()
    if not pob_commit:
        return None
    try:
        manifest = load_compatibility_manifest(DEFAULT_COMPATIBILITY_MANIFEST)
        match = resolve_compatibility(pob_commit, manifest)
    except (OSError, ValueError, PobParseError):
        return None
    if match is None:
        return None
    return LocalCompatibility(
        game_patch=match.game_patch,
        passive_tree=match.passive_tree,
    )
