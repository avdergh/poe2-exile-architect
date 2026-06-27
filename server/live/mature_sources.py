"""Copy-safe mature build source probing helpers.

Phase 3N.3 first needs to know whether a source exposes build-level mature samples at all.
This module summarizes response *shape* only; it must not persist or return raw build payloads,
PoB codes, full item tables, passive trees, gem links, or copied guide text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from server.knowledge import copy_safety


BUILD_LEVEL_ROW_KEYS = ("builds", "characters", "rows", "samples")
AGGREGATE_ROW_KEYS = ("archetypes", "skills", "skillStats", "archetypeStats")
POE_NINJA_SOURCE = "poe_ninja"


def shape_build_level_probe(*, url: str, status_code: int, payload: Any) -> dict[str, Any]:
    """Return a copy-safe probe report for a possible mature build source.

    The report intentionally contains only response metadata and key names. Returning values from
    provider rows would risk leaking exact gear, passive, gem, or account/build details before the
    sanitizer and evaluator split have a chance to run.
    """
    source_type = _source_type(url)
    base = {
        "sourceType": source_type,
        "url": copy_safety.safe_url_ref(url),
        "httpStatus": status_code,
        "hasBuildLevelRows": False,
    }
    if status_code != 200:
        return {
            **base,
            "ok": False,
            "unavailableReason": f"HTTP {status_code}",
        }
    if not isinstance(payload, Mapping):
        return {
            **base,
            "ok": False,
            "unavailableReason": "payload is not a JSON object",
        }

    response_shape = sorted(str(key) for key in payload.keys())
    build_rows = _candidate_rows(payload, BUILD_LEVEL_ROW_KEYS)
    if build_rows:
        return {
            **base,
            "ok": True,
            "hasBuildLevelRows": True,
            "rowKind": "build_level",
            "rowCount": len(build_rows),
            "responseShape": response_shape,
            "rowShape": _row_shape(build_rows[0]),
            "rawContentPersisted": False,
        }

    aggregate_rows = _candidate_rows(payload, AGGREGATE_ROW_KEYS)
    if aggregate_rows:
        return {
            **base,
            "ok": False,
            "hasAggregateRows": True,
            "responseShape": response_shape,
            "rowShape": _row_shape(aggregate_rows[0]),
            "unavailableReason": (
                "payload exposes aggregate archetype/skill rows, not build-level mature samples"
            ),
            "rawContentPersisted": False,
        }

    nested = _nested_league_shapes(payload)
    reason = (
        "payload appears to expose ascendancy or league metadata only; "
        "no explicit build-level sample rows were found"
    )
    return {
        **base,
        "ok": False,
        "hasAggregateRows": False,
        "responseShape": response_shape,
        "nestedLeagueShapes": nested,
        "unavailableReason": reason,
        "rawContentPersisted": False,
    }


def _source_type(url: str) -> str:
    if "poe.ninja" in url.lower():
        return POE_NINJA_SOURCE
    if "pobb.in" in url.lower():
        return "pobb_in"
    return "external"


def _candidate_rows(payload: Mapping[str, Any], keys: tuple[str, ...]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, Mapping))
    return rows


def _row_shape(row: Mapping[str, Any]) -> list[str]:
    return sorted(str(key) for key in row.keys())


def _nested_league_shapes(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Summarize nested league rows without including row values.

    poe.ninja's known build-index payload places league metadata under ``leagueBuilds``. Capturing
    the nested key names makes source-probe reports useful while still avoiding raw sample leakage.
    """
    league_builds = payload.get("leagueBuilds")
    if not isinstance(league_builds, list):
        return []
    shapes: list[dict[str, Any]] = []
    for row in league_builds[:5]:
        if not isinstance(row, Mapping):
            continue
        shapes.append(
            {
                "rowShape": _row_shape(row),
                "statisticsShape": _first_nested_row_shape(row.get("statistics")),
            }
        )
    return shapes


def _first_nested_row_shape(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    for row in value:
        if isinstance(row, Mapping):
            return _row_shape(row)
    return []
