"""Live PoE2 build meta via poe.ninja's public build-index API.

This is a *usage snapshot* of logged top-ladder characters by ascendancy — popularity, NOT a
recommendation (popular != optimal). It covers ascendancy distribution only; poe.ninja's
per-skill/per-item breakdown lives behind a protobuf endpoint we don't consume. The archetype-trend
adapter below is intentionally a safe seam: it returns unavailable unless a provider payload
explicitly contains aggregate build-level rows. Read-only; refreshes upstream roughly hourly.
Degrades gracefully if poe.ninja is unreachable.
"""

from __future__ import annotations

import json
import math
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .. import paths
from .league_tokens import normalize_league_token

URL = "https://poe.ninja/poe2/api/data/build-index-state"
# poe.ninja's edge rejects some non-browser clients, so present a browser-like UA.
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120 Safari/537.36 poe2-build-mcp"
    ),
    "Accept": "application/json",
    "Referer": "https://poe.ninja/poe2/builds",
}


class MetaError(RuntimeError):
    """Raised when the meta API can't be reached or returns an error."""


def _fetch() -> Any:
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=20) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001 - normalize to one error type
        raise MetaError(f"poe.ninja build-index request failed: {e}") from e


def _trend(v: Any) -> str:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return "flat"
    return "rising" if n > 0 else "falling" if n < 0 else "flat"


def _is_main_league(name: str) -> bool:
    """True for the main softcore challenge league (not HC/SSF/Standard/Ruthless).

    Token-based so a future league whose name merely *contains* one of these words as a
    substring (e.g. "Substandard") isn't misclassified.
    """
    n = (name or "").lower().strip()
    if n in ("standard", "hardcore", "ruthless"):
        return False
    tokens = set(n.replace("(", " ").replace(")", " ").split())
    return not (tokens & {"hc", "ssf", "hardcore", "ruthless"})


def _select(leagues: list[dict], override: str | None) -> dict | None:
    if override:
        token = normalize_league_token(override)
        return next(
            (
                lb
                for lb in leagues
                if token
                in {
                    normalize_league_token(lb.get("leagueName")),
                    normalize_league_token(lb.get("leagueUrl")),
                }
            ),
            None,
        )
    for lb in leagues:  # default: the main softcore challenge league
        if _is_main_league(lb.get("leagueName") or ""):
            return lb
    return leagues[0] if leagues else None


def shape(data: Any, league: str | None = None, limit: int = 15) -> dict[str, Any]:
    """Format raw build-index-state into an ascendancy-popularity summary (no network)."""
    leagues = (data or {}).get("leagueBuilds") or []
    available = [lb.get("leagueName") for lb in leagues]
    if not leagues:
        return {"ok": False, "error": "no league build data available"}
    chosen = _select(leagues, league)
    if chosen is None:
        return {"ok": False, "error": f"league {league!r} not found", "leaguesAvailable": available}
    stats = sorted(
        (chosen.get("statistics") or []), key=lambda s: s.get("percentage") or 0, reverse=True
    )
    return {
        "ok": True,
        "source": "poe.ninja",
        "kind": "ascendancy_popularity",
        "league": chosen.get("leagueName"),
        "sampleSize": chosen.get("total"),
        "ascendancies": [
            {
                "ascendancy": s.get("class"),
                "percentage": round(s.get("percentage") or 0, 2),
                "trend": _trend(s.get("trend")),
            }
            for s in stats[: max(1, limit)]
        ],
        "leaguesAvailable": available,
        "note": (
            "Popularity among logged top-ladder characters — NOT a recommendation. Popular is "
            "not the same as optimal or right for the player's goal. Use it as context only; "
            "this is ascendancy distribution ONLY (no skill/item/build data). For a build-level "
            "meta comparison, find one (web-search a pobb.in/pastebin link), load it with "
            "import_build, and compare numbers on the engine. Verify any build with the engine."
        ),
    }


def shape_archetype_trends(data: Any, league: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Format aggregate build-archetype rows when a provider explicitly supplies them.

    The current poe.ninja build-index payload normally contains ascendancy popularity only. This
    helper is therefore intentionally conservative: if no aggregate skill/archetype rows are
    present, it returns an unavailable result instead of inventing build-level meta.
    """
    leagues = (data or {}).get("leagueBuilds") or []
    available = [lb.get("leagueName") for lb in leagues]
    if not leagues:
        return _archetype_unavailable(
            None,
            available,
            "no league build data available",
        )
    chosen = _select(leagues, league)
    if chosen is None:
        return _archetype_unavailable(
            None,
            available,
            f"league {league!r} not found",
        )

    raw_rows = _aggregate_archetype_rows(chosen)
    if not raw_rows:
        return _archetype_unavailable(
            chosen.get("leagueName"),
            available,
            (
                "no aggregate skill/archetype sample rows were present in this payload; "
                "the source currently exposes ascendancy popularity only"
            ),
            sample_size=chosen.get("total"),
        )

    sample_size = _int_or_none(chosen.get("total"))
    shaped = [
        row
        for row in (_shape_archetype_row(row, sample_size=sample_size) for row in raw_rows)
        if row is not None
    ]
    if not shaped:
        return _archetype_unavailable(
            chosen.get("leagueName"),
            available,
            (
                "no valid aggregate sample rows were present; each archetype row must include "
                "a skill plus sampleCount/count or share/percentage"
            ),
            sample_size=sample_size,
        )
    shaped.sort(key=_archetype_sort_key)
    return {
        "ok": bool(shaped),
        "source": "poe.ninja",
        "kind": "archetype_trends",
        "league": chosen.get("leagueName"),
        "sampleSize": sample_size,
        "archetypes": shaped[: max(1, limit)],
        "leaguesAvailable": available,
        "evidenceTags": ["live-meta", "archetype-trend"],
        "note": (
            "Aggregate archetype trends are discovery context only, not proof of build power. "
            "Use them to choose samples to investigate, then verify the route with PoB."
        ),
    }


def _archetype_unavailable(
    league_name: str | None,
    leagues_available: list[Any],
    reason: str,
    *,
    sample_size: Any = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "source": "poe.ninja",
        "kind": "archetype_trends",
        "league": league_name,
        "sampleSize": _int_or_none(sample_size),
        "archetypes": [],
        "leaguesAvailable": leagues_available,
        "unavailableReason": reason,
        "evidenceTags": ["live-meta", "unavailable"],
        "note": (
            "No build-level trend evidence is available from this payload. Do not infer skill, "
            "item, or archetype popularity from ascendancy-only statistics."
        ),
    }


def _aggregate_archetype_rows(league_build: dict[str, Any]) -> list[dict[str, Any]]:
    """Return provider-supplied aggregate rows only, never raw character/build dumps."""
    aggregate_rows: list[dict[str, Any]] = []
    for key in ("archetypes", "skills", "skillStats", "archetypeStats"):
        rows = league_build.get(key)
        if isinstance(rows, list):
            aggregate_rows.extend(row for row in rows if isinstance(row, dict))
    return aggregate_rows


def _shape_archetype_row(row: dict[str, Any], *, sample_size: int | None) -> dict[str, Any] | None:
    skill = _first_text(row, "skill", "mainSkill", "name", "gem")
    ascendancy = _first_text(row, "ascendancy", "class", "className")
    if not skill:
        return None
    sample_count = _sample_count_value(row)
    if _has_any(row, "sampleCount", "count") and sample_count is None:
        return None
    if sample_count is not None and sample_size and sample_size > 0 and sample_count > sample_size:
        return None
    share = _share_value(row, sample_count=sample_count, sample_size=sample_size)
    if _has_any(row, "share", "percentage") and share is None:
        return None
    # A name alone can be a skill directory entry rather than a sampled meta trend. Require an
    # aggregate metric before labeling a row as build-level evidence.
    if sample_count is None and share is None:
        return None
    return {
        "skill": skill,
        "ascendancy": ascendancy,
        "sampleCount": sample_count,
        "share": share,
        "trend": _trend(row.get("trend")),
        "evidenceTags": _tag_list(row.get("evidenceTags"), "live-meta", "archetype-trend"),
    }


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _has_any(row: dict[str, Any], *keys: str) -> bool:
    return any(row.get(key) is not None for key in keys)


def _first_text(row: dict[str, Any], *keys: str) -> str | None:
    value = _first_value(row, *keys)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(n) or not n.is_integer():
        return None
    return int(n)


def _sample_count_value(row: dict[str, Any]) -> int | None:
    """Return a row-level sample count from explicitly supported count fields only.

    League-level fields such as ``total`` or raw-character-list fields such as ``characters`` are
    intentionally excluded; treating them as per-archetype evidence would turn non-trend payloads
    into misleading build meta.
    """
    sample_count = _int_or_none(_first_value(row, "sampleCount", "count"))
    if sample_count is None or sample_count < 0:
        return None
    return sample_count


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(n):
        return None
    return n


def _share_value(
    row: dict[str, Any], *, sample_count: int | None, sample_size: int | None
) -> float | None:
    if row.get("share") is not None:
        raw_share = _float_or_none(row.get("share"))
        if raw_share is None or raw_share < 0 or raw_share > 1:
            return None
        return round(raw_share, 3)
    if row.get("percentage") is not None:
        raw_percentage = _float_or_none(row.get("percentage"))
        if raw_percentage is None or raw_percentage < 0 or raw_percentage > 100:
            return None
        return round(raw_percentage / 100, 3)
    if sample_count is not None and sample_size and sample_size > 0:
        return round(sample_count / sample_size, 3)
    return None


def _tag_list(raw: Any, *required: str) -> list[str]:
    # Provider-supplied tags are not trusted. A live trend row must never be able to label itself
    # as engine-computed, PoB-verified, or reference-cohort evidence.
    tags: list[str] = []
    for tag in required:
        if tag not in tags:
            tags.append(tag)
    return tags


def _archetype_sort_key(row: dict[str, Any]) -> tuple[float, float, str]:
    """Rank normalized popularity first; fall back to count when a provider omits share."""
    share = row.get("share")
    count = row.get("sampleCount")
    share_rank = float(share) if isinstance(share, (int, float)) else -1.0
    count_rank = float(count) if isinstance(count, (int, float)) else -1.0
    return (-share_rank, -count_rank, str(row.get("skill") or ""))


def shape_meta_context(
    data: Any,
    league: str | None = None,
    *,
    ascendancy_limit: int = 15,
    archetype_limit: int = 10,
) -> dict[str, Any]:
    """Shape ascendancy popularity and archetype trends from the same provider snapshot."""
    context = shape(data, league=league, limit=ascendancy_limit)
    if isinstance(context, dict):
        context["archetypeTrends"] = shape_archetype_trends(
            data, league=league, limit=archetype_limit
        )
    return context


def _cache_path():
    return paths.user_data_dir() / "meta_cache.json"


def _write_cache(data: Any) -> None:
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "data": data,
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def _read_cache() -> dict | None:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def get_meta_builds(league: str | None = None, limit: int = 15) -> dict[str, Any]:
    """Ascendancy popularity for a league (default the current challenge league).

    On a successful fetch the snapshot is cached; if poe.ninja is later unreachable we fall back
    to that last-good snapshot (flagged `stale`) instead of returning nothing.
    """
    try:
        data = _fetch()
    except MetaError:
        cached = _read_cache()
        if cached and cached.get("data"):
            r = shape(cached["data"], league=league, limit=limit)
            if r.get("ok"):
                r["stale"] = True
                r["fetchedAt"] = cached.get("fetched_at")
                r["note"] = "poe.ninja unreachable — last cached snapshot (may be stale). " + r.get(
                    "note", ""
                )
            return r
        raise
    _write_cache(data)
    return shape(data, league=league, limit=limit)


def get_archetype_trends(league: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Aggregate skill/archetype trends when the live provider exposes them.

    The current build-index endpoint may only contain ascendancy statistics. In that case callers
    receive an explicit unavailable result, which is safer than treating popularity by ascendancy as
    build-level meta.
    """
    try:
        data = _fetch()
    except MetaError:
        cached = _read_cache()
        if cached and cached.get("data"):
            r = shape_archetype_trends(cached["data"], league=league, limit=limit)
            r["stale"] = True
            r["fetchedAt"] = cached.get("fetched_at")
            r["note"] = "poe.ninja unreachable — last cached snapshot (may be stale). " + r.get(
                "note", ""
            )
            return r
        raise
    _write_cache(data)
    return shape_archetype_trends(data, league=league, limit=limit)


def get_meta_context(
    league: str | None = None,
    *,
    ascendancy_limit: int = 15,
    archetype_limit: int = 10,
) -> dict[str, Any]:
    """Fetch poe.ninja once and shape all live meta slices from the same snapshot."""
    try:
        data = _fetch()
    except MetaError:
        cached = _read_cache()
        if cached and cached.get("data"):
            result = shape_meta_context(
                cached["data"],
                league=league,
                ascendancy_limit=ascendancy_limit,
                archetype_limit=archetype_limit,
            )
            result["stale"] = True
            result["fetchedAt"] = cached.get("fetched_at")
            result["note"] = "poe.ninja unreachable — last cached snapshot (may be stale). " + (
                result.get("note") or ""
            )
            trends = result.get("archetypeTrends")
            if isinstance(trends, dict):
                trends["stale"] = True
                trends["fetchedAt"] = cached.get("fetched_at")
            return result
        raise
    _write_cache(data)
    return shape_meta_context(
        data,
        league=league,
        ascendancy_limit=ascendancy_limit,
        archetype_limit=archetype_limit,
    )
