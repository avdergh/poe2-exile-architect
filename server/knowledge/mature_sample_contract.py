"""Contracts for mature-build sample manifests.

Phase 3N.3 needs small, inspectable manifests proving why a sanitized case is a useful mature
build sample. A manifest may describe provenance, popularity, freshness, and diversity; it must
never become a hiding place for raw PoB codes, full gear, passive trees, gem links, or guide text.
"""

from __future__ import annotations

from typing import Any
import hashlib

from . import copy_safety

VALID_SAMPLE_SOURCE_TYPES = {
    "poe_ninja",
    "forum",
    "external_forum_guide",
    "pobb_in",
    "pob_archive",
    "manual_fixture",
    "reference_cohort",
}

REQUIRED_SAMPLE_MANIFEST_KEYS = {
    "sourceType": "sourceType",
    "sourceRef": "sourceRef",
    "popularity": "popularity",
    "freshness": "freshness",
    "diversityBucket": "diversityBucket",
}


def validate_sample_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate a copy-safe manifest for a mature-build sample.

    The validator is deliberately stricter than ordinary metadata parsing: if a manifest contains
    copyable build material, it is rejected before later fixture import or LLM extraction can see it.
    """
    if not isinstance(manifest, dict):
        return {"ok": False, "error": "sample_manifest_must_be_object"}

    forbidden_paths = copy_safety.find_forbidden_paths(manifest)
    if forbidden_paths:
        return {
            "ok": False,
            "error": "copyable_manifest_field",
            "paths": forbidden_paths,
        }

    copyability_flags = copy_safety.copyability_flags(manifest, long_text_limit=1600)
    if copyability_flags:
        return {
            "ok": False,
            "error": "copyability_guard_failed",
            "flags": copyability_flags,
        }

    missing = [
        label
        for key, label in REQUIRED_SAMPLE_MANIFEST_KEYS.items()
        if copy_safety.is_empty(manifest.get(key))
    ]
    if missing:
        return {"ok": False, "error": "sample_manifest_incomplete", "missing": missing}

    source_type = str(manifest["sourceType"])
    if source_type not in VALID_SAMPLE_SOURCE_TYPES:
        return {
            "ok": False,
            "error": "invalid_sample_source_type",
            "sourceTypeHash": _fingerprint(source_type),
        }

    popularity_error = _validate_popularity(manifest["popularity"])
    if popularity_error:
        return popularity_error

    freshness_error = _validate_freshness(manifest["freshness"])
    if freshness_error:
        return freshness_error

    return {
        "ok": True,
        "sourceType": source_type,
        "diversityBucket": copy_safety.safe_text(manifest["diversityBucket"]),
    }


def _validate_popularity(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return {"ok": False, "error": "popularity_must_be_object"}
    basis = value.get("basis") or value.get("kind") or value.get("signal")
    has_strength = any(
        not copy_safety.is_empty(value.get(key)) for key in ("rank", "count", "share", "weight")
    )
    if copy_safety.is_empty(basis) or not has_strength:
        return {
            "ok": False,
            "error": "popularity_incomplete",
            "missing": [
                label
                for missing, label in (
                    (copy_safety.is_empty(basis), "basis"),
                    (not has_strength, "rank/count/share/weight"),
                )
                if missing
            ],
        }
    return None


def _validate_freshness(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return {"ok": False, "error": "freshness_must_be_object"}
    required = {
        "league": value.get("league"),
        "gamePatch": value.get("gamePatch") or value.get("game_patch"),
        "passiveTreeVersion": (
            value.get("passiveTreeVersion")
            or value.get("passive_tree_version")
            or value.get("tree")
        ),
    }
    missing = [key for key, cell in required.items() if copy_safety.is_empty(cell)]
    if missing:
        return {"ok": False, "error": "freshness_incomplete", "missing": missing}
    return None


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
