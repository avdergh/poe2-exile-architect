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


RELEASES_URL = "https://github.com/avdergh/poe2-exile-architect/releases"


@dataclass(frozen=True, slots=True)
class LocalCompatibility:
    game_patch: str
    passive_tree: str
    pob_version: str = ""
    pob_commit: str = ""


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


def current_local_compatibility() -> LocalCompatibility | None:
    """Return the application-managed current PoB compatibility enum and season context."""
    try:
        manifest = load_compatibility_manifest(DEFAULT_COMPATIBILITY_MANIFEST)
    except (OSError, ValueError, PobParseError):
        manifest = None
    if manifest is not None and manifest.current_pob_version:
        current = next(
            (
                entry
                for entry in manifest.entries
                if entry.pob_version == manifest.current_pob_version
            ),
            None,
        )
        if current is not None:
            return LocalCompatibility(
                game_patch=current.game_patch,
                passive_tree=current.passive_tree,
                pob_version=current.pob_version,
                pob_commit=current.commit,
            )
    try:
        installed = live_update.installed_meta()
    except (OSError, ValueError):
        installed = {}
    resolved = _resolve_local_compatibility(installed)
    if resolved is not None:
        return resolved
    if manifest is None:
        return None
    if not manifest.entries:
        return None
    current_version = manifest.current_pob_version
    latest = next(
        (entry for entry in manifest.entries if entry.pob_version == current_version),
        manifest.entries[-1],
    )
    return LocalCompatibility(
        game_patch=latest.game_patch,
        passive_tree=latest.passive_tree,
        pob_version=latest.pob_version,
        pob_commit=latest.commit,
    )


def known_pob_versions() -> frozenset[str]:
    """Return application-managed PoB version enum values."""
    try:
        manifest = load_compatibility_manifest(DEFAULT_COMPATIBILITY_MANIFEST)
    except (OSError, ValueError, PobParseError):
        return frozenset()
    return frozenset(entry.pob_version for entry in manifest.entries)


def resolve_pob_version_enum(value: str | None) -> str | None:
    """Normalize unknown, version, or certified commit input to the stored PoB version enum."""
    normalized = str(value or "").strip()
    if normalized.casefold() in {"", "unknown", "none", "null"}:
        current = current_local_compatibility()
        return current.pob_version if current is not None else None
    try:
        manifest = load_compatibility_manifest(DEFAULT_COMPATIBILITY_MANIFEST)
    except (OSError, ValueError, PobParseError):
        return None
    version_matches = [entry for entry in manifest.entries if entry.pob_version == normalized]
    if version_matches:
        return version_matches[-1].pob_version
    try:
        commit_match = resolve_compatibility(normalized, manifest)
    except PobParseError:
        return None
    return commit_match.pob_version if commit_match is not None else None


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
        pob_version=match.pob_version,
        pob_commit=match.commit,
    )
