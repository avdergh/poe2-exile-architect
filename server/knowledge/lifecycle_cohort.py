"""Cohort evidence for lifecycle build research.

The lifecycle agent needs mature-build patterns, but it must not copy builds. This module
therefore aggregates non-copyable calibration slices from the reference library and annotates them
with live meta context when available.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from . import refbuilds

_GOAL_QUERY_ALIASES = {
    "闪电": "lightning",
    "雷": "lightning",
    "火": "fire",
    "冰": "cold",
    "冰霜": "cold",
    "混沌": "chaos",
    "物理": "physical",
    "召唤": "minion",
    "投射物": "projectile",
    "远程": "projectile",
    "近战": "melee",
}
_STOPWORDS = {"bd", "build", "poe2", "强力", "终局", "毕业", "新手", "开荒", "低预算"}


def analyze_goal_cohort(
    *,
    goal: str,
    skill_candidates: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Aggregate reference-build and live-meta patterns for a lifecycle goal.

    The output is deliberately archetype-shaped: common levers, common delivery traits, and
    ascendancy context. It omits raw build codes, tree paths, gear lists, and anything else that
    would encourage the assistant to clone a mature build instead of verifying its own route.
    """
    goal = (goal or "").strip()
    skill_candidates = skill_candidates or []
    meta = meta or {}
    queries = _queries(goal, skill_candidates)
    matches = _reference_matches(queries, limit=max(1, limit))
    archetype_trend_context = _archetype_trend_context(queries, meta)
    evidence_tags = ["reference-cohort"]
    warnings: list[str] = []

    if meta.get("ok"):
        evidence_tags.append("live-meta")
    else:
        warnings.append("Live meta context unavailable; cohort uses reference calibration only.")
    if archetype_trend_context:
        evidence_tags.append("live-archetype-trends")
    elif isinstance(meta.get("archetypeTrends"), dict) and not meta["archetypeTrends"].get("ok"):
        reason = meta["archetypeTrends"].get("unavailableReason") or meta["archetypeTrends"].get(
            "error"
        )
        if reason:
            warnings.append(f"Build-level archetype trends unavailable: {reason}")
    if not matches:
        warnings.append("No matching reference-build samples found for this goal.")

    return {
        "ok": True,
        "goal": goal,
        "queries": queries,
        "sampleSize": len(matches),
        "referenceMatches": matches,
        "commonLevers": _lever_rows(matches),
        "commonDamageTypes": _counter_rows(_count_list_field(matches, "damageTypes"), len(matches)),
        "commonDelivery": _counter_rows(_count_list_field(matches, "delivery"), len(matches)),
        "commonDefenses": _counter_rows(
            _count_scalar_field(matches, "defenseIdentity"), len(matches)
        ),
        "ascendancyContext": _ascendancy_context(matches, meta),
        "archetypeTrendContext": archetype_trend_context,
        "warnings": warnings,
        "evidenceTags": evidence_tags,
        "note": (
            "Cohort evidence is calibration only. Use it to choose what to verify with PoB, "
            "not to copy a reference build."
        ),
    }


def _queries(goal: str, skill_candidates: list[dict[str, Any]]) -> list[str]:
    queries: list[str] = []
    for candidate in skill_candidates:
        for value in (candidate.get("name"), candidate.get("query")):
            if value:
                _append_unique(queries, str(value))
    for zh, query in _GOAL_QUERY_ALIASES.items():
        if zh in goal:
            _append_unique(queries, query)
    for term in re.findall(r"[\w\u4e00-\u9fff]+", goal.lower()):
        if len(term) > 2 and term not in _STOPWORDS:
            _append_unique(queries, term)
    if goal:
        _append_unique(queries, goal)
    return queries[:6]


def _append_unique(rows: list[str], value: str) -> None:
    value = " ".join(value.split())
    if value and value.lower() not in {row.lower() for row in rows}:
        rows.append(value)


def _reference_matches(queries: list[str], *, limit: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for query in queries or [""]:
        try:
            result = refbuilds.search(query=query, limit=limit)
        except Exception:  # noqa: BLE001 - reference evidence is advisory, not route-blocking
            continue
        for build in result.get("builds") or []:
            slim = _sanitize_reference(build)
            key = (
                str(slim.get("ascendancy") or ""),
                str(slim.get("mainSkill") or ""),
                str(slim.get("dominantLever") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            matches.append(slim)
            if len(matches) >= limit:
                return matches
    return matches


def _sanitize_reference(build: dict[str, Any]) -> dict[str, Any]:
    """Keep only calibration fields that are safe to expose as cohort evidence."""
    return {
        "class": build.get("class"),
        "ascendancy": build.get("ascendancy"),
        "mainSkill": build.get("mainSkill"),
        "damageTypes": list(build.get("damageTypes") or []),
        "delivery": list(build.get("delivery") or []),
        "defenseIdentity": build.get("defenseIdentity"),
        "dominantLever": build.get("dominantLever"),
        "topLevers": [
            {"lever": row.get("lever")}
            for row in (build.get("topLevers") or [])
            if isinstance(row, dict) and row.get("lever")
        ],
        "dpsComputable": build.get("dpsComputable", True),
    }


def _lever_rows(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for build in matches:
        # Count a lever at most once per reference build; repeated appearances inside the same
        # build are still one mature-build vote, not multiple votes.
        levers = {str(build.get("dominantLever") or "")}
        levers.update(
            str(row.get("lever") or "")
            for row in (build.get("topLevers") or [])
            if isinstance(row, dict)
        )
        for lever in levers:
            if lever:
                counter[lever] += 1
    return _counter_rows(counter, len(matches))


def _count_list_field(matches: list[dict[str, Any]], field: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for build in matches:
        for value in build.get(field) or []:
            if value:
                counter[str(value)] += 1
    return counter


def _count_scalar_field(matches: list[dict[str, Any]], field: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for build in matches:
        value = build.get(field)
        if value:
            counter[str(value)] += 1
    return counter


def _counter_rows(counter: Counter[str], denominator: int) -> list[dict[str, Any]]:
    denom = max(1, denominator)
    return [
        {"name": name, "count": count, "share": round(count / denom, 3)}
        for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:6]
    ]


def _ascendancy_context(
    matches: list[dict[str, Any]], meta: dict[str, Any]
) -> list[dict[str, Any]]:
    ref_counts = _count_scalar_field(matches, "ascendancy")
    live_by_name = {
        str(row.get("ascendancy") or "").lower(): row for row in (meta.get("ascendancies") or [])
    }
    rows: list[dict[str, Any]] = []
    for ascendancy, count in ref_counts.items():
        live = live_by_name.get(ascendancy.lower())
        rows.append(
            {
                "ascendancy": ascendancy,
                "referenceCount": count,
                "liveMeta": (
                    {
                        "percentage": live.get("percentage"),
                        "trend": live.get("trend"),
                        "league": meta.get("league"),
                        "source": meta.get("source"),
                    }
                    if live
                    else None
                ),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            -row["referenceCount"],
            -(row["liveMeta"] or {}).get("percentage", 0),
            row["ascendancy"],
        ),
    )


def _archetype_trend_context(
    queries: list[str], meta: dict[str, Any], limit: int = 5
) -> list[dict[str, Any]]:
    """Attach sanitized live archetype rows that match the goal/search queries.

    The rows have already been reduced by `server.live.meta`, but this layer still copies only the
    public-safe fields so cohort analysis never leaks raw gear, passive trees, or build codes.
    """
    trends = meta.get("archetypeTrends") if isinstance(meta, dict) else None
    if not isinstance(trends, dict) or not trends.get("ok"):
        return []
    query_text = [q.lower() for q in queries if q]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in trends.get("archetypes") or []:
        if not isinstance(row, dict):
            continue
        skill = str(row.get("skill") or "").strip()
        ascendancy = str(row.get("ascendancy") or "").strip()
        sample_count = row.get("sampleCount")
        share = row.get("share")
        sample_count = sample_count if _nonnegative_number(sample_count) else None
        share = share if _valid_share(share) else None
        if not skill or (sample_count is None and share is None):
            continue
        searchable = f"{skill} {ascendancy}".lower()
        if query_text and not any(q in searchable for q in query_text):
            continue
        key = (skill.lower(), ascendancy.lower())
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "skill": skill,
                "ascendancy": ascendancy,
                "sampleCount": sample_count,
                "share": share,
                "trend": row.get("trend"),
                "evidenceTags": [
                    tag for tag in (row.get("evidenceTags") or []) if isinstance(tag, str) and tag
                ],
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _nonnegative_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _valid_share(value: Any) -> bool:
    return _nonnegative_number(value) and value <= 1
