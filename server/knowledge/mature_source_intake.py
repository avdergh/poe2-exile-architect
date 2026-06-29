"""Mature-source intake helpers."""

from __future__ import annotations

from typing import Any


def group_source_variants(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    invalid_rows: list[dict[str, Any]] = []

    for index, row in enumerate(rows):
        key = _normalized_required_value(row.get("buildFamilyKey"))
        if key is None:
            invalid_rows.append({"index": index, "reason": "missing_build_family_key"})
            continue

        if key not in groups:
            groups[key] = {
                "buildFamilyKey": key,
                "discoverySources": [],
                "payloadSources": [],
                "sourceRefs": [],
            }
            ordered_keys.append(key)

        bucket = groups[key]
        discovery_source = _normalized_required_value(row.get("discoverySource"))
        payload_source = _normalized_required_value(row.get("payloadSource"))
        source_ref = _normalized_required_value(row.get("sourceRef"))

        if discovery_source and discovery_source not in bucket["discoverySources"]:
            bucket["discoverySources"].append(discovery_source)
        if payload_source and payload_source not in bucket["payloadSources"]:
            bucket["payloadSources"].append(payload_source)
        if source_ref and source_ref not in bucket["sourceRefs"]:
            bucket["sourceRefs"].append(source_ref)

    if invalid_rows:
        return {
            "ok": False,
            "error": "invalid_build_family_key",
            "invalidRows": invalid_rows,
        }

    return {
        "ok": True,
        "groupCount": len(ordered_keys),
        "groups": [groups[key] for key in ordered_keys],
    }


def build_rich_brief_metadata(
    *,
    build_family_key: str,
    summary: str,
    source_refs: list[str] | None = None,
    payload_sources: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "briefType": "rich_brief",
        "buildFamilyKey": build_family_key,
        "summary": summary,
        "sourceRefs": _deduped_non_empty_values(source_refs),
        "payloadSources": _deduped_non_empty_values(payload_sources),
        "visibility": "quarantined",
        "split": "quarantine",
        "creatorVisible": False,
    }


def build_raw_rich_case(
    *,
    build_family_key: str,
    discovery_row: dict[str, Any],
    payload_row: dict[str, Any],
) -> dict[str, Any]:
    """Build one extractor-ready raw-rich case from discovery and payload rows."""
    if not _normalized_required_value(build_family_key):
        return {"ok": False, "error": "build_family_key_required"}
    if not isinstance(discovery_row, dict):
        return {"ok": False, "error": "discovery_row_must_be_object"}
    if not isinstance(payload_row, dict):
        return {"ok": False, "error": "payload_row_must_be_object"}

    source_ref = (
        _normalized_required_value(payload_row.get("sourceRef"))
        or _normalized_required_value(discovery_row.get("sourceRef"))
        or f"case://{build_family_key}"
    )
    safe_metadata = {
        "case_id": source_ref,
        "sourceType": _normalized_required_value(payload_row.get("sourceType"))
        or _normalized_required_value(discovery_row.get("sourceType"))
        or "unknown",
        "sourceRef": source_ref,
        "league": _normalized_required_value(payload_row.get("league"))
        or _normalized_required_value(discovery_row.get("league"))
        or "unknown",
        "gamePatch": _normalized_required_value(payload_row.get("gamePatch"))
        or _normalized_required_value(discovery_row.get("gamePatch"))
        or "unknown",
        "passiveTreeVersion": _normalized_required_value(payload_row.get("passiveTreeVersion"))
        or _normalized_required_value(discovery_row.get("passiveTreeVersion"))
        or "unknown",
        "class": _normalized_required_value(payload_row.get("class"))
        or _normalized_required_value(discovery_row.get("class"))
        or "",
        "ascendancy": _normalized_required_value(payload_row.get("ascendancy"))
        or _normalized_required_value(discovery_row.get("ascendancy"))
        or "",
        "mainSkill": _normalized_required_value(payload_row.get("mainSkill"))
        or _normalized_required_value(discovery_row.get("mainSkill"))
        or "",
        "damageTypes": _normalized_list(payload_row.get("damageTypes"))
        or _normalized_list(discovery_row.get("damageTypes")),
        "deliveryTags": _normalized_list(payload_row.get("deliveryTags"))
        or _normalized_list(discovery_row.get("deliveryTags")),
        "defenseTags": _normalized_list(payload_row.get("defenseTags"))
        or _normalized_list(discovery_row.get("defenseTags")),
        "mechanicTags": _normalized_list(payload_row.get("mechanicTags"))
        or _normalized_list(discovery_row.get("mechanicTags")),
        "lifecycleStage": _normalized_required_value(payload_row.get("lifecycleStage"))
        or _normalized_required_value(discovery_row.get("lifecycleStage"))
        or "unknown_lifecycle",
        "budgetBand": _normalized_required_value(payload_row.get("budgetBand"))
        or _normalized_required_value(discovery_row.get("budgetBand"))
        or "unknown",
        "popularityRank": payload_row.get("popularityRank", discovery_row.get("popularityRank")),
        "sampleWeight": payload_row.get("sampleWeight", discovery_row.get("sampleWeight", 1.0)),
        "pobModelability": _normalized_required_value(payload_row.get("pobModelability"))
        or _normalized_required_value(discovery_row.get("pobModelability"))
        or "unknown",
        "keypoints": _normalized_list(payload_row.get("keypoints"))
        or _normalized_list(discovery_row.get("keypoints")),
        "numericRangesOrMetrics": payload_row.get("numericRangesOrMetrics")
        if isinstance(payload_row.get("numericRangesOrMetrics"), dict)
        else discovery_row.get("numericRangesOrMetrics")
        if isinstance(discovery_row.get("numericRangesOrMetrics"), dict)
        else {},
        "visibility": _normalized_required_value(discovery_row.get("visibility"))
        or "creator_visible",
        "split": _normalized_required_value(discovery_row.get("split")) or "train_context",
        "knowledgeScope": _normalized_required_value(discovery_row.get("knowledgeScope"))
        or "global_seed",
        "evidenceType": _normalized_required_value(payload_row.get("evidenceType"))
        or _normalized_required_value(discovery_row.get("evidenceType"))
        or "manual_fixture",
        "freshnessStatus": _normalized_required_value(payload_row.get("freshnessStatus"))
        or _normalized_required_value(discovery_row.get("freshnessStatus"))
        or "unknown",
        "compatibilityStatus": _normalized_required_value(payload_row.get("compatibilityStatus"))
        or _normalized_required_value(discovery_row.get("compatibilityStatus"))
        or "unknown",
        "diversityBucket": build_family_key,
    }
    raw_context = {
        key: value
        for key, value in payload_row.items()
        if key not in safe_metadata and value not in (None, "", [], {})
    }
    if "sourcePayload" not in raw_context and payload_row:
        raw_context["sourcePayload"] = {
            "sourceType": _normalized_required_value(payload_row.get("sourceType")) or "unknown",
            "sourceRef": source_ref,
        }
    return {
        "ok": True,
        "case": {
            "buildFamilyKey": build_family_key,
            "discoverySource": _normalized_required_value(discovery_row.get("discoverySource"))
            or "unknown",
            "payloadSource": _normalized_required_value(payload_row.get("payloadSource"))
            or "unknown",
            "safeMetadata": safe_metadata,
            "rawContext": raw_context,
        },
    }


def _normalized_required_value(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized


def _deduped_non_empty_values(values: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

    for value in values or []:
        normalized = _normalized_required_value(value)
        if normalized is None or normalized in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized)

    return deduped


def _normalized_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _normalized_required_value(item)
        if text:
            normalized.append(text)
    return normalized
