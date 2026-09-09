"""Exact constrained selection of already measured, additive affix scores.

This only optimizes the supplied linear approximation. It neither models PoE stats nor proves
that the assembled item's measured gain equals the sum of its individual affix gains. Callers
must still measure the complete item in PoB and audit its actual legality and attainability.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .attainability import GearAttainabilityPolicy


ScoredAffix = tuple[float, dict[str, Any], str]


@dataclass(frozen=True)
class _Selection:
    score: Fraction
    indexes: tuple[int, ...]


def _prefer(candidate: _Selection, current: _Selection | None) -> bool:
    if current is None or candidate.score != current.score:
        return current is None or candidate.score > current.score
    return (len(candidate.indexes), candidate.indexes) < (len(current.indexes), current.indexes)


def select_affix_subset(
    scored: Iterable[ScoredAffix],
    policy: GearAttainabilityPolicy,
    *,
    prefix_limit: int = 3,
    suffix_limit: int = 3,
) -> list[ScoredAffix]:
    """Return original entries maximizing their positive finite marginal-score sum.

    Each global affix group can contribute at most one entry, including when its alternatives
    span both prefix and suffix pools. Counts are bounded by the supplied base capacities
    and the policy's explicit-affix and deep-top-tier limits. Candidates must carry
    their actual-roll ``_deepTopTier`` classification; this function does not infer tier quality.

    All candidates are considered. A sparse dynamic program processes complete groups instead
    of greedily spending the shared budget on prefixes first. Canonical JSON metadata breaks
    score ties deterministically, independent of input order; exact duplicate entries remain
    interchangeable. The returned tuples and dictionaries are not copied or mutated.
    """
    max_explicit = policy.maxExplicitAffixes
    max_deep = policy.maxDeepTopTierAffixes
    if any(type(limit) is not int or limit < 0 for limit in (prefix_limit, suffix_limit)):
        raise ValueError("invalid_affix_selection_capacity")
    if (
        isinstance(max_explicit, bool)
        or not isinstance(max_explicit, int)
        or max_explicit < 0
        or (
            max_deep is not None
            and (isinstance(max_deep, bool) or not isinstance(max_deep, int) or max_deep < 0)
        )
    ):
        raise ValueError("invalid_affix_selection_policy")
    max_explicit = min(max_explicit, prefix_limit + suffix_limit)
    max_deep = min(max_deep if max_deep is not None else max_explicit, max_explicit)

    prepared: list[tuple[str, str, str, str, ScoredAffix]] = []
    for entry in scored:
        gain, candidate, line = entry
        if isinstance(gain, bool) or not isinstance(gain, (int, float)):
            continue
        if not math.isfinite(gain) or gain <= 0:
            continue
        if candidate.get("type") not in {"prefix", "suffix"}:
            raise ValueError("invalid_affix_selection_type")
        if not isinstance(candidate.get("group"), str):
            raise ValueError("invalid_affix_selection_group")
        if not isinstance(candidate.get("_deepTopTier"), bool):
            raise ValueError("affix_selection_requires_actual_tier_evidence")
        key = json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        prepared.append((candidate["group"], key, line, float(gain).hex(), entry))
    prepared.sort(key=lambda value: value[:4])

    groups: dict[str, list[int]] = {}
    entries: list[ScoredAffix] = []
    exact_scores: list[Fraction] = []
    for group, _, _, _, entry in prepared:
        groups.setdefault(group, []).append(len(entries))
        entries.append(entry)
        # Exact rational addition avoids overflow and order-sensitive rounding during selection.
        # These are the supplied measured scores, not a new model of the game's statistics.
        exact_scores.append(Fraction(entry[0]))

    states: dict[tuple[int, int, int], _Selection] = {(0, 0, 0): _Selection(Fraction(0), ())}
    for group_indexes in groups.values():
        next_states = dict(states)  # Choosing no candidate from this group is always permitted.
        for (prefixes, suffixes, deep), prior in states.items():
            if prefixes + suffixes >= max_explicit:
                continue
            for index in group_indexes:
                candidate = entries[index][1]
                new_prefixes = prefixes + (candidate["type"] == "prefix")
                new_suffixes = suffixes + (candidate["type"] == "suffix")
                new_deep = deep + candidate["_deepTopTier"]
                if (
                    new_prefixes > prefix_limit
                    or new_suffixes > suffix_limit
                    or new_deep > max_deep
                ):
                    continue
                state_key = (new_prefixes, new_suffixes, new_deep)
                selection = _Selection(prior.score + exact_scores[index], (*prior.indexes, index))
                if _prefer(selection, next_states.get(state_key)):
                    next_states[state_key] = selection
        states = next_states

    best: _Selection | None = None
    for selection in states.values():
        if _prefer(selection, best):
            best = selection
    return [entries[index] for index in best.indexes] if best is not None else []
