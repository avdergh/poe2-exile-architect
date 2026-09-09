from __future__ import annotations

import itertools
import math
import random
from fractions import Fraction

import pytest

from server.compute.affix_selection import ScoredAffix, select_affix_subset
from server.compute.attainability import GearAttainabilityPolicy, policy_for


def _affix(
    gain: float, kind: str, group: str, *, deep: bool = False, line: str | None = None
) -> ScoredAffix:
    text = line or f"{kind}:{group}:{deep}"
    return gain, {"type": kind, "group": group, "line": text, "_deepTopTier": deep}, text


def _score(entries: list[ScoredAffix]) -> Fraction:
    return sum((Fraction(entry[0]) for entry in entries), start=Fraction(0))


def _valid(entries: list[ScoredAffix], policy: GearAttainabilityPolicy) -> bool:
    return (
        len(entries) <= policy.maxExplicitAffixes
        and sum(entry[1]["type"] == "prefix" for entry in entries) <= 3
        and sum(entry[1]["type"] == "suffix" for entry in entries) <= 3
        and len({entry[1]["group"] for entry in entries}) == len(entries)
        and (
            policy.maxDeepTopTierAffixes is None
            or sum(entry[1]["_deepTopTier"] for entry in entries) <= policy.maxDeepTopTierAffixes
        )
    )


def _exhaustive_score(entries: list[ScoredAffix], policy: GearAttainabilityPolicy) -> Fraction:
    return max(
        _score(list(subset))
        for size in range(len(entries) + 1)
        for subset in itertools.combinations(entries, size)
        if _valid(list(subset), policy)
    )


def test_shared_five_affix_budget_does_not_prefer_prefixes() -> None:
    prefixes = [_affix(1, "prefix", f"p{index}") for index in range(3)]
    suffixes = [_affix(100, "suffix", f"s{index}") for index in range(3)]
    policy = policy_for("realistic_trade")

    # The old prefix-first allocation consumed three slots for +3, leaving only two for +200.
    assert _score((prefixes + suffixes)[: policy.maxExplicitAffixes]) == 203
    selected = select_affix_subset(prefixes + suffixes, policy)

    assert _score(selected) == 302
    assert len(selected) == 5
    assert sum(entry[1]["type"] == "prefix" for entry in selected) == 2
    assert _valid(selected, policy)


@pytest.mark.parametrize(("prefix_limit", "suffix_limit"), [(2, 2), (1, 1), (0, 2), (3, 3)])
def test_base_capacity_bounds_each_side_before_spending_shared_budget(prefix_limit, suffix_limit):
    entries = [
        _affix(gain, kind, f"{kind}{index}")
        for kind, gain in (("prefix", 1), ("suffix", 100))
        for index in range(3)
    ]
    policy = policy_for("realistic_trade")
    selected = select_affix_subset(
        entries, policy, prefix_limit=prefix_limit, suffix_limit=suffix_limit
    )
    expected = max(
        _score(list(subset))
        for size in range(len(entries) + 1)
        for subset in itertools.combinations(entries, size)
        if _valid(list(subset), policy)
        and sum(item[1]["type"] == "prefix" for item in subset) <= prefix_limit
        and sum(item[1]["type"] == "suffix" for item in subset) <= suffix_limit
    )
    assert _score(selected) == expected


@pytest.mark.parametrize("capacity", [-1, True, 2.5, None])
def test_invalid_base_capacity_is_rejected(capacity):
    with pytest.raises(ValueError, match="invalid_affix_selection_capacity"):
        select_affix_subset([], policy_for("theoretical"), prefix_limit=capacity)


def test_deep_tier_budget_keeps_lower_tier_alternative_of_same_group() -> None:
    entries = [
        _affix(100, "prefix", "a", deep=True, line="a:T1"),
        _affix(99, "prefix", "a", line="a:T2"),
        _affix(98, "prefix", "b", deep=True, line="b:T1"),
        _affix(1, "prefix", "b", line="b:T2"),
        _affix(97, "suffix", "c", deep=True),
    ]

    selected = select_affix_subset(entries, policy_for("realistic_trade"))

    assert _score(selected) == 294
    assert {entry[2] for entry in selected} == {"a:T2", "b:T1", "suffix:c:True"}


def test_group_conflict_applies_across_prefix_and_suffix_pools() -> None:
    entries = [
        _affix(9, "prefix", "shared"),
        _affix(10, "suffix", "shared"),
        *[_affix(100, "suffix", f"s{index}") for index in range(3)],
    ]

    selected = select_affix_subset(entries, policy_for("realistic_trade"))

    assert _score(selected) == 309
    assert entries[0] in selected
    assert entries[1] not in selected


def test_same_group_different_tiers_cannot_spend_two_slots() -> None:
    entries = [
        _affix(7, "prefix", "one", line="T1", deep=True),
        _affix(6, "prefix", "one", line="T2"),
    ]
    assert select_affix_subset(entries, policy_for("theoretical")) == [entries[0]]


def test_theoretical_policy_allows_six_affixes_and_more_than_two_deep_tiers() -> None:
    entries = [
        _affix(index + 1, kind, f"{kind}{index}", deep=True)
        for kind in ("prefix", "suffix")
        for index in range(4)
    ]
    selected = select_affix_subset(entries, policy_for("theoretical"))
    assert len(selected) == 6
    assert _score(selected) == 18
    assert _valid(selected, policy_for("theoretical"))


@pytest.mark.parametrize("policy_name", ["realistic_trade", "theoretical"])
def test_empty_or_nonpositive_nonfinite_pool_produces_no_selection(policy_name: str) -> None:
    policy = policy_for(policy_name)
    assert select_affix_subset([], policy) == []
    entries = [
        _affix(gain, "prefix", str(index))
        for index, gain in enumerate((0, -1, math.nan, math.inf, -math.inf, True, False))
    ]
    assert select_affix_subset(entries, policy) == []


def test_invalid_measurements_do_not_discard_valid_alternatives() -> None:
    valid = _affix(12, "prefix", "same")
    entries = [_affix(math.nan, "prefix", "same"), valid, _affix(math.inf, "suffix", "s")]
    assert select_affix_subset(entries, policy_for("realistic_trade")) == [valid]


def test_positive_finite_scores_remain_comparable_when_their_sum_overflows_float() -> None:
    entries = [
        _affix(1e308, "prefix", "a"),
        _affix(1e308, "prefix", "b"),
        _affix(9e307, "suffix", "c"),
    ]
    policy = GearAttainabilityPolicy("test", 2, None)
    assert select_affix_subset(entries, policy) == entries[:2]


def test_tiny_positive_gain_is_not_discarded_after_large_gain_rounding() -> None:
    entries = [_affix(1e100, "prefix", "a"), _affix(1e-100, "suffix", "b")]
    assert select_affix_subset(entries, policy_for("realistic_trade")) == entries


def test_zero_deep_tier_budget_uses_lower_alternatives_and_zero_affix_budget_stays_empty() -> None:
    entries = [
        _affix(100, "prefix", "p", deep=True),
        _affix(90, "prefix", "p"),
        _affix(10, "suffix", "s"),
    ]
    assert select_affix_subset(entries, GearAttainabilityPolicy("test", 5, 0)) == entries[1:]
    assert select_affix_subset(entries, GearAttainabilityPolicy("test", 0, None)) == []


@pytest.mark.parametrize("limits", [(-1, 2), (5, -1), (True, 2), (5, True)])
def test_invalid_policy_limits_are_rejected(limits) -> None:
    with pytest.raises(ValueError, match="invalid_affix_selection_policy"):
        select_affix_subset([], GearAttainabilityPolicy("test", *limits))


def test_equal_scores_are_stable_across_input_order_and_preserve_original_objects() -> None:
    entries = [
        _affix(10, kind, f"{kind}{index}", line=f"line {index}")
        for kind in ("prefix", "suffix")
        for index in range(4)
    ]
    policy = policy_for("realistic_trade")
    expected = select_affix_subset(entries, policy)
    unchanged = [(gain, dict(candidate), line) for gain, candidate, line in entries]
    rng = random.Random(517)
    for _ in range(40):
        reordered = list(entries)
        rng.shuffle(reordered)
        selected = select_affix_subset(iter(reordered), policy)
        assert selected == expected
        assert all(any(entry is original for original in entries) for entry in selected)
    assert entries == unchanged


def test_no_fixed_candidate_cutoff_hides_late_high_gain_affixes() -> None:
    entries = [_affix(1, "prefix", f"p{index:04}") for index in range(350)]
    winners = [_affix(100, "suffix", f"z{index}") for index in range(3)]
    selected = select_affix_subset(entries + winners, policy_for("realistic_trade"))
    assert _score(selected) == 302
    assert all(winner in selected for winner in winners)


@pytest.mark.parametrize("policy_name", ["realistic_trade", "theoretical"])
def test_random_small_pools_match_exhaustive_oracle(policy_name: str) -> None:
    rng = random.Random(602)
    policy = policy_for(policy_name)
    for _ in range(100):
        entries = [
            _affix(
                rng.randint(1, 50) / 7,
                rng.choice(("prefix", "suffix")),
                f"group{rng.randrange(6)}",
                deep=rng.choice((True, False)),
                line=f"line{index}",
            )
            for index in range(rng.randrange(1, 11))
        ]
        selected = select_affix_subset(entries, policy)
        assert _valid(selected, policy)
        assert _score(selected) == _exhaustive_score(entries, policy)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("type", "implicit", "invalid_affix_selection_type"),
        ("group", None, "invalid_affix_selection_group"),
        ("_deepTopTier", None, "affix_selection_requires_actual_tier_evidence"),
        ("_deepTopTier", 1, "affix_selection_requires_actual_tier_evidence"),
    ],
)
def test_missing_structural_evidence_is_not_silently_accepted(field, value, error) -> None:
    entry = _affix(1, "prefix", "p")
    entry[1][field] = value
    with pytest.raises(ValueError, match=error):
        select_affix_subset([entry], policy_for("realistic_trade"))
