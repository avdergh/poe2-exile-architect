"""Conservative source-text evidence extraction for lifecycle build analysis.

Forum guides and user notes often contain useful lifecycle hints before they contain a clean PoB
code. This module extracts only explicit signals and corpus-confirmed candidates; it never turns
guide prose into computed build claims.
"""

from __future__ import annotations

import re
from typing import Any

from . import db as corpus

_STAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "campaign_early": (
        "level with",
        "leveling",
        "levelling",
        "league start",
        "starter",
        "campaign",
        "act 1",
        "act1",
        "开荒",
        "剧情",
        "新手",
    ),
    "campaign_mid": ("first ascendancy", "act 3", "act 4", "中期", "第一次升华"),
    "campaign_late": ("act 5", "act 6", "act 7", "late campaign", "剧情后期"),
    "maps_entry": ("maps", "mapping", "atlas", "early maps", "异界", "进图"),
    "endgame_budget": ("budget", "cheap", "low budget", "first divine", "低预算", "廉价"),
    "endgame_final": ("endgame", "final", "pinnacle", "bossing", "毕业", "终局"),
}
_TRANSITION_WORDS = (
    "switch",
    "transition",
    "respec",
    "swap",
    "convert",
    "change to",
    "转型",
    "转",
    "换",
    "洗点",
)
_REQUIRED_UNIQUE_WORDS = (
    "required unique",
    "requires unique",
    "must have",
    "mandatory",
    "build-defining unique",
    "key unique",
    "关键暗金",
    "必备暗金",
    "需要暗金",
)
_NOT_STARTER_PATTERNS = (
    "not a starter",
    "not league starter",
    "endgame only",
    "cannot level",
    "不能开荒",
    "无法开荒",
    "不适合开荒",
)
_CANDIDATE_STOPWORDS = {
    "act",
    "atlas",
    "boss",
    "campaign",
    "endgame",
    "final",
    "level",
    "maps",
    "spark through",
    "switch",
}


def extract_lifecycle_source_evidence(source: str) -> dict[str, Any]:
    """Extract lifecycle hints from guide/source text without claiming computed truth."""
    text = (source or "")[:20000]
    normalized = " ".join(text.split())
    lower = normalized.lower()
    stage_signals = _stage_signals(lower)
    transition_hints = _transition_hints(normalized)
    skill_candidates, unique_candidates = _corpus_candidates(normalized)
    lifecycle_hints = _lifecycle_hints(lower, stage_signals, transition_hints)
    risk_flags = _risk_flags(lower, lifecycle_hints, unique_candidates)

    return {
        "ok": True,
        "stageSignals": stage_signals,
        "lifecycleHints": lifecycle_hints,
        "skillCandidates": skill_candidates,
        "uniqueCandidates": unique_candidates,
        "transitionHints": transition_hints,
        "riskFlags": risk_flags,
        "evidenceTags": ["external-guide", "corpus", "lifecycle-source-extraction"],
        "note": (
            "Source evidence is guide/corpus evidence only. Use it to form lifecycle hypotheses, "
            "then verify active build numbers with the PoB engine."
        ),
    }


def _stage_signals(lower: str) -> list[str]:
    return [
        stage
        for stage, keywords in _STAGE_KEYWORDS.items()
        if any(keyword in lower for keyword in keywords)
    ]


def _transition_hints(text: str) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for sentence in _sentences(text):
        lower = sentence.lower()
        if not any(word in lower for word in _TRANSITION_WORDS):
            continue
        hints.append(
            {
                "snippet": sentence[:240],
                "level": _level_in(sentence),
                "evidence": "transition-language",
            }
        )
    return hints[:5]


def _lifecycle_hints(
    lower: str, stage_signals: list[str], transition_hints: list[dict[str, Any]]
) -> list[str]:
    hints: list[str] = []
    if any(stage.startswith("campaign") for stage in stage_signals) or any(
        word in lower for word in ("starter", "leveling", "levelling", "开荒")
    ):
        hints.append("starter_route")
    if transition_hints:
        hints.append("transition_required")
    if "endgame_final" in stage_signals or any(
        word in lower for word in ("endgame", "终局", "毕业")
    ):
        hints.append("endgame_form")
    if any(pattern in lower for pattern in _NOT_STARTER_PATTERNS):
        hints.append("endgame_not_direct_starter")
    return hints


def _risk_flags(
    lower: str, lifecycle_hints: list[str], unique_candidates: list[dict[str, Any]]
) -> list[str]:
    flags: list[str] = []
    unique_language = any(word in lower for word in _REQUIRED_UNIQUE_WORDS) or bool(
        re.search(
            r"(?:when|once|after).{0,80}(?:equip|equipped|wear|have|obtain|acquire|拿到|装备)",
            lower,
        )
    )
    if unique_candidates and unique_language:
        flags.append("required_unique_language")
    if "endgame_not_direct_starter" in lifecycle_hints:
        flags.append("not_direct_starter_language")
    if "endgame_form" in lifecycle_hints and "starter_route" not in lifecycle_hints:
        flags.append("endgame_without_starter_evidence")
    return flags


def _corpus_candidates(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    skill_candidates: list[dict[str, Any]] = []
    unique_candidates: list[dict[str, Any]] = []
    seen_skills: set[str] = set()
    seen_uniques: set[str] = set()

    for phrase in _candidate_phrases(text):
        for row in _safe_find_skills(phrase):
            name = str(row.get("name") or "")
            if name and name.lower() not in seen_skills:
                seen_skills.add(name.lower())
                skill_candidates.append(
                    {
                        "name": name,
                        "gemType": row.get("gem_type"),
                        "tags": row.get("tags") or [],
                        "matchedText": phrase,
                        "source": "corpus-skill-search",
                    }
                )
        for row in _safe_search_uniques(phrase):
            name = str(row.get("name") or "")
            if name and name.lower() not in seen_uniques:
                seen_uniques.add(name.lower())
                unique_candidates.append(
                    {
                        "name": name,
                        "base": row.get("base"),
                        "itemType": row.get("item_type"),
                        "matchedText": phrase,
                        "source": "corpus-unique-search",
                    }
                )
        if len(skill_candidates) >= 8 and len(unique_candidates) >= 8:
            break
    return skill_candidates[:8], unique_candidates[:8]


def _candidate_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    quoted = re.findall(r"[`\"'“”‘’]([^`\"'“”‘’]{2,60})[`\"'“”‘’]", text)
    title_case = re.findall(r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\b", text)
    for phrase in [*quoted, *title_case]:
        phrase = " ".join(phrase.split())
        if not phrase or phrase.lower() in _CANDIDATE_STOPWORDS:
            continue
        if len(phrase) < 3 or phrase.lower() in {p.lower() for p in phrases}:
            continue
        phrases.append(phrase)
    return phrases[:30]


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+|[\n\r]+", text) if part.strip()]


def _level_in(text: str) -> int | None:
    for pattern in (
        r"\b(?:level|lvl|lv)\s*(\d{1,3})\b",
        r"\b(\d{1,3})\s*(?:级|等)\b",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            level = int(match.group(1))
            if 1 <= level <= 100:
                return level
    return None


def _safe_find_skills(query: str) -> list[dict[str, Any]]:
    try:
        return list(corpus.find_skills(query=query, limit=5))
    except Exception:  # noqa: BLE001 - source extraction is advisory
        return []


def _safe_search_uniques(query: str) -> list[dict[str, Any]]:
    try:
        return list(corpus.search_uniques(query=query, limit=5))
    except Exception:  # noqa: BLE001 - source extraction is advisory
        return []
