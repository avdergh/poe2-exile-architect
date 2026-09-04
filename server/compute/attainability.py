"""Shared quality policy for generated rare equipment candidates.

This is deliberately separate from item legality: imported or theoretical legal items remain
equipable, while ordinary Create delivery can consistently distinguish a realistic trade target.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


AcquisitionProfile = Literal["realistic_trade", "theoretical"]
POLICY_VERSION = "gear_attainability_v1"


@dataclass(frozen=True)
class GearAttainabilityPolicy:
    policyVersion: str
    maxExplicitAffixes: int
    maxDeepTopTierAffixes: int | None


_POLICIES: dict[str, GearAttainabilityPolicy] = {
    "realistic_trade": GearAttainabilityPolicy(POLICY_VERSION, 5, 2),
    "theoretical": GearAttainabilityPolicy(POLICY_VERSION, 6, None),
}


def policy_for(profile: str) -> GearAttainabilityPolicy:
    try:
        return _POLICIES[str(profile)]
    except KeyError as exc:
        raise ValueError("invalid_acquisition_profile") from exc


def public_policy(profile: str) -> dict[str, Any]:
    return asdict(policy_for(profile))


def rare_item_reasons(item: dict[str, Any], *, profile: str = "realistic_trade") -> list[str]:
    policy = policy_for(profile)
    affix_count = int(item.get("affixPrefixes") or 0) + int(item.get("affixSuffixes") or 0)
    top_tier_count = int(item.get("topTierAffixes") or 0)
    reasons: list[str] = []
    if affix_count > policy.maxExplicitAffixes:
        reasons.append("theoretical_six_affix_rare")
    if policy.maxDeepTopTierAffixes is not None and top_tier_count > policy.maxDeepTopTierAffixes:
        reasons.append("too_many_top_tier_affixes")
    return reasons
