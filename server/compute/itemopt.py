"""Gear slot min-maxer (thin engine + corpus coordinator).

Searches a slot's real craftable affix pool for the best-in-slot rare. It maximizes either a
single `metric` (e.g. TotalDPS on a weapon) or a weighted blend of metrics via `goals`
(e.g. {"TotalDPS": .6, "TotalEHP": .4}) so one craft can carry both damage AND defense —
respecting crafting reality: prefix/suffix limits, mod-group exclusivity, and the base's mod
restrictions. Every candidate is engine-evaluated (batched via eval_items) — nothing is estimated.
The result is a *theoretical best-in-slot target* with idealized rolls; verify attainability and
price with get_prices.

Like solve_for/optimize_passives, this is a bounded mechanical search over engine truth — it
optimizes a goal the caller gives, it does not decide the goal.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from ..knowledge import db, item_legality
from ..judge import hard_legality
from ..runtime import craft_receipts
from .engine import PobEngine

_RANGE = re.compile(r"\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)")
_RES_KEYS = ("fire", "cold", "lightning")
_CHAOS_RESIST_RE = re.compile(r"chaos resistance", re.IGNORECASE)
GearStage = Literal["auto", "campaign", "maps_entry", "endgame"]


def gear_stage_profile(
    level: int | float | None,
    *,
    stage: GearStage = "auto",
    chaos_resist_target: int | None = None,
) -> dict[str, Any]:
    """Return stage-aware gear goals without treating pinnacle defenses as a universal baseline."""
    if stage not in {"auto", "campaign", "maps_entry", "endgame"}:
        raise ValueError("stage must be auto, campaign, maps_entry, or endgame")
    resolved = stage
    if resolved == "auto":
        lvl = int(level or 0)
        resolved = "campaign" if lvl < 70 else "maps_entry" if lvl < 80 else "endgame"
    profiles = {
        "campaign": {"defenseWeight": 0.65, "chaosResistTarget": 0},
        "maps_entry": {"defenseWeight": 0.72, "chaosResistTarget": 30},
        "endgame": {"defenseWeight": 0.78, "chaosResistTarget": 60},
    }
    profile = dict(profiles[resolved])
    if chaos_resist_target is not None:
        profile["chaosResistTarget"] = max(-60, min(75, int(chaos_resist_target)))
    profile["stage"] = resolved
    profile["elementalResistTarget"] = 75
    return profile


def _without_unneeded_chaos_resistance(
    mods: list[dict[str, Any]], *, current_chaos: float, target_chaos: int
) -> list[dict[str, Any]]:
    if current_chaos < target_chaos:
        return mods
    return [mod for mod in mods if not _CHAOS_RESIST_RE.search(str(mod.get("text") or ""))]


def _num(x: Any) -> bool:
    """True for a real number (bool excluded — JSON true/false must not count as 1/0)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _canonical_slot(slot: str) -> str:
    """Map caller-friendly slot aliases onto the engine's slot names.

    PoB models the Quiver as the off-hand weapon slot ("Weapon 2"); crafting/optimizing with the
    display name "Quiver" silently fails inside eval_items/add_item unless normalized here.
    """
    if str(slot).strip() in {"Quiver", "Arrow Quiver"}:
        return "Weapon 2"
    return slot


_ATTRIBUTE_MOD_QUERIES = {
    "strength": "to Strength",
    "dexterity": "to Dexterity",
    "intelligence": "to Intelligence",
}


def _attribute_bridge_suggestions(
    shortfalls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Suggest a real +attribute suffix that bridges a projected whole-build shortfall.

    Planning-mode helper: when an optimized item is legal in isolation but the current character
    cannot equip it yet (attribute chicken-and-egg), name the smallest real bridge mod so the
    caller can order gear assembly instead of guessing.
    """
    suggestions: list[dict[str, Any]] = []
    for shortfall in shortfalls:
        attribute = str(shortfall.get("attribute") or "")
        missing = shortfall.get("shortfall")
        query = _ATTRIBUTE_MOD_QUERIES.get(attribute)
        if not query or not isinstance(missing, (int, float)) or missing <= 0:
            continue
        best: tuple[int, str, str] | None = None
        for mod in db.search_mods(query, mod_type="suffix", limit=30):
            text = str(mod.get("text") or "")
            match = re.search(r"\+(\d+)\s*to\s*" + re.escape(attribute.capitalize()), text)
            if match:
                amount = int(match.group(1))
                if best is None or amount > best[0]:
                    best = (amount, text, str(mod.get("name") or ""))
        if best is not None:
            suggestions.append(
                {
                    "attribute": attribute,
                    "shortfall": round(float(missing), 1),
                    "suggestedMod": best[1],
                    "suggestedModName": best[2],
                    "bridgeNote": (
                        f"equip a {best[1]} bridge piece (or allocate an attribute node) before "
                        "crafting/equipping the high-requirement item; then re-run this craft"
                    ),
                }
            )
    return suggestions


def _round2(x: Any) -> Any:
    return round(x, 2) if _num(x) else x


def _roll(text: str, rolls: str) -> str:
    """Turn a range mod ("+(80-90) to maximum Life") into a concrete roll."""

    def sub(m: re.Match[str]) -> str:
        a, b = float(m.group(1)), float(m.group(2))
        v = b if rolls == "max" else round(a + 0.85 * (b - a))
        return str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:g}"

    return _RANGE.sub(sub, text)


def _item_text(base: str, lines: list[str], slot: str, *, ilvl: int | None = None) -> str:
    body = "\n".join(lines)
    level_line = f"Item Level: {int(ilvl)}\n" if ilvl is not None else ""
    return f"Rarity: Rare\nOptimized {slot}\n{base}\n{level_line}--------\n{body}"


def _generated_item_legality(
    raw: str,
    *,
    prepared_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the exact deterministic legality audit used by completeness and final artifacts."""
    return item_legality.audit_item(
        raw,
        prepared_receipt=prepared_receipt,
        require_special_provenance=True,
    )


def _craft_summary(
    chosen: list[dict[str, Any]], prefix_pool: int, suffix_pool: int
) -> dict[str, Any]:
    """A coarse craft-effort / attainability estimate (NOT a market price).

    The data has no usable spawn-weights (all 1), so 'effort' is inferred from how many specific
    affixes the craft needs, how many are a TOP tier of several (rarer rolls), and the item level
    required — a rough realism check, not a probability or a divine cost.
    """
    n = len(chosen)
    deep = sum(1 for c in chosen if (c.get("tiers") or 1) >= 4)
    min_ilvl = max((c.get("ilvl") or 0 for c in chosen), default=0)
    score = n + deep
    if n == 0:
        effort = "trivial"
    elif score <= 3:
        effort = "low"
    elif score <= 6:
        effort = "moderate"
    elif score <= 9:
        effort = "high"
    else:
        effort = "very high"
    return {
        "effort": effort,
        "minItemLevel": min_ilvl,
        "prefixPool": prefix_pool,
        "suffixPool": suffix_pool,
        "topTierAffixesNeeded": deep,
        "note": (
            f"~{effort} craft: {n} specific affix(es)"
            + (f" ({deep} a top tier of several)" if deep else "")
            + f" on an ilvl {min_ilvl}+ base, competing in a pool of {prefix_pool} prefix / "
            f"{suffix_pool} suffix mods. Rough heuristic from tier depth + pool size (no spawn-weight "
            "data); essence/bench crafts can make specific mods deterministic and cheaper."
        ),
    }


def optimize_item(
    engine: PobEngine,
    slot: str,
    metric: str = "TotalDPS",
    base: str | None = None,
    ilvl: int = 82,
    rolls: str = "realistic",
    thorough: bool = False,
    keep_resists_capped: bool = True,
    goals: dict[str, float] | None = None,
    extra_mods: dict[str, list[dict[str, Any]]] | None = None,
    special_affix_sources: dict[str, dict[str, Any]] | None = None,
    planning: bool = False,
) -> dict[str, Any]:
    """Craft the best-in-slot rare for a single `metric`, or a weighted blend via `goals`.

    `goals` (e.g. {"TotalDPS": .6, "TotalEHP": .4}) scores each candidate by the weighted sum of
    *relative* gains vs the bare base, so a single craft balances offense and defense (real endgame
    gear is blended, not pure-DPS or pure-EHP). Omit `goals` for the single-`metric` behaviour.
    `extra_mods` ({"prefixes":[...], "suffixes":[...]} of affix_pool-shaped dicts) injects extra
    candidate affixes beyond the base's natural pool — used by the crafting layer to offer
    essence-only mods (e.g. a Perfect Essence's % Life on body armour). See the module docstring.
    """
    slot = _canonical_slot(slot)
    build = engine.get_build()
    gear = build.get("gear") or {}
    if not base:
        cur_item = gear.get(slot)
        base = cur_item.get("base") if isinstance(cur_item, dict) else None
    if not base:
        return {
            "ok": False,
            "error": f"No base for slot '{slot}'. Equip an item there first, or pass base=.",
        }

    # `goals` = weighted multi-objective (blended gear); falls back to the single `metric`.
    weights: dict[str, float] = {}
    if goals:
        weights = {str(k): float(v) for k, v in goals.items() if _num(v) and float(v) > 0}
        if not weights:
            return {
                "ok": False,
                "error": "goals must map stat names to positive weights, "
                'e.g. {"TotalDPS": 0.6, "TotalEHP": 0.4}.',
            }
    keys = list(weights) if weights else [metric]

    pool = db.affix_pool(base, ilvl=ilvl)
    # Inject extra candidate affixes (e.g. essence-only mods the natural pool can't roll) so the same
    # greedy values them against the pool, respecting prefix/suffix caps + group exclusivity.
    if extra_mods:
        pool["prefixes"] = list(pool["prefixes"]) + list(extra_mods.get("prefixes") or [])
        pool["suffixes"] = list(pool["suffixes"]) + list(extra_mods.get("suffixes") or [])
    pre = [
        {
            "group": m["group"],
            "line": _roll(m["text"], rolls),
            "type": "prefix",
            "tiers": m.get("tiers", 1),
            "ilvl": m.get("required_level", 0),
        }
        for m in pool["prefixes"]
    ]
    suf = [
        {
            "group": m["group"],
            "line": _roll(m["text"], rolls),
            "type": "suffix",
            "tiers": m.get("tiers", 1),
            "ilvl": m.get("required_level", 0),
        }
        for m in pool["suffixes"]
    ]
    if not pre and not suf:
        return {"ok": False, "error": f"No craftable affixes found for base '{base}'."}

    snapshot = engine.get_xml()
    before_equipped_slots = _equipped_slots(build)
    before_whole_build_legality = hard_legality.audit_build(
        hard_legality.augment_build_with_snapshot_gear(build, snapshot)
    )
    try:
        before_vals = engine.get_stats(keys)["stats"]
        before_missing = (
            (engine.get_defenses().get("resistMissing") or {}) if keep_resists_capped else {}
        )

        chosen_pre: list[dict[str, str]] = []
        chosen_suf: list[dict[str, str]] = []
        used: set[str] = set()

        def lines() -> list[str]:
            return [x["line"] for x in chosen_pre + chosen_suf]

        def stats_of(line_sets: list[list[str]]) -> list[dict[str, Any]]:
            res = engine.eval_items(
                slot, [_item_text(base, ls, slot, ilvl=ilvl) for ls in line_sets], keys=keys
            )["results"]
            # A candidate that failed to parse/equip comes back as `false` from the engine bridge.
            # Do NOT silently treat it as "no change": an all-failed batch means the slot/base is
            # not craftable here and the caller must hear that instead of receiving a blank item.
            failed = sum(1 for r in res if not isinstance(r, dict))
            if failed:
                raise ValueError(
                    f"eval_items failed to equip {failed}/{len(res)} candidate(s) for slot "
                    f"'{slot}' on base '{base}' — the slot may not be craftable via this tool"
                )
            return res

        # Bare base = the craft's starting point; relative gains in `goals` mode are measured from it.
        base_stats = stats_of([[]])[0]
        denom = {k: max(abs(base_stats.get(k) or 0.0), 1.0) for k in keys}

        def score(st: dict[str, Any]) -> float:
            """Weighted relative gain vs the bare base (goals mode), else the raw metric value."""
            if weights:
                return sum(
                    w * ((st.get(k) or 0.0) - (base_stats.get(k) or 0.0)) / denom[k]
                    for k, w in weights.items()
                )
            v = st.get(metric)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
            return float("-inf")

        def best_of(opts: list[dict[str, str]], base_lines: list[str]) -> tuple[int | None, float]:
            if not opts:
                return None, float("-inf")
            sts = stats_of([base_lines + [c["line"]] for c in opts])
            bi, bv = None, float("-inf")
            for i, st in enumerate(sts):
                s = score(st)
                if s > bv:
                    bi, bv = i, s
            return bi, bv

        # Greedy: each round add the affix (respecting 3 prefix / 3 suffix + group exclusivity) that
        # most improves the score, until full or no candidate helps.
        cur = score(base_stats)
        while len(chosen_pre) < 3 or len(chosen_suf) < 3:
            opts: list[dict[str, str]] = []
            if len(chosen_pre) < 3:
                opts += [c for c in pre if c["group"] not in used]
            if len(chosen_suf) < 3:
                opts += [c for c in suf if c["group"] not in used]
            bi, bv = best_of(opts, lines())
            if bi is None or bv <= cur + 1e-9:
                break
            c = opts[bi]
            (chosen_pre if c["type"] == "prefix" else chosen_suf).append(c)
            used.add(c["group"])
            cur = bv

        # Optional swap pass: replace each chosen affix with an unused one OF THE SAME TYPE if it
        # improves — catches greedy local optima without breaking the prefix/suffix split.
        if thorough:
            improved = True
            while improved:
                improved = False
                for grp_list, poolside in ((chosen_pre, pre), (chosen_suf, suf)):
                    for idx in range(len(grp_list)):
                        rest = grp_list[:idx] + grp_list[idx + 1 :]
                        rest_used = used - {grp_list[idx]["group"]}
                        swaps = [c for c in poolside if c["group"] not in rest_used]
                        other = [x["line"] for x in (chosen_suf if poolside is pre else chosen_pre)]
                        base_lines = [x["line"] for x in rest] + other
                        bi, bv = best_of(swaps, base_lines)
                        if bi is not None and bv > cur + 1e-9:
                            grp_list[idx] = swaps[bi]
                            used = {x["group"] for x in chosen_pre + chosen_suf}
                            cur = bv
                            improved = True
                if improved:
                    continue

        chosen = chosen_pre + chosen_suf
        final = _item_text(base, lines(), slot, ilvl=ilvl)
        selected_special_sources = [
            special_affix_sources[line]
            for line in lines()
            if special_affix_sources and line in special_affix_sources
        ]
        prepared_receipt = (
            craft_receipts.prepare_receipt(
                final,
                slot=slot,
                item_level=ilvl,
                perfect_essences=selected_special_sources,
                runtime_context=craft_receipts.current_runtime_context(
                    getattr(engine, "info", None)
                ),
            )
            if selected_special_sources
            else None
        )
        legality = (
            _generated_item_legality(
                final,
                prepared_receipt=prepared_receipt,
            )
            if prepared_receipt is not None
            else _generated_item_legality(final)
        )
        if not legality.get("ok"):
            return {
                "ok": False,
                "errorCode": "generated_item_legality_check_failed",
                "error": (
                    "The optimized candidate failed the same affix legality audit used by "
                    "build completeness and was discarded."
                ),
                "slot": slot,
                "base": base,
                "legalityCheck": legality,
            }
        add_result = engine.add_item(final, slot=slot)
        if not isinstance(add_result, dict) or not add_result.get("ok"):
            return {
                "ok": False,
                "errorCode": "optimized_item_equip_failed",
                "error": (
                    "The optimized candidate could not be equipped into slot '{slot}' "
                    "(engine rejected the item text or the slot). "
                    + str((add_result or {}).get("error") or "no engine detail")
                ),
                "slot": slot,
                "base": base,
                "rejectedCandidate": final,
            }
        candidate_xml = engine.get_xml()
        candidate_build = engine.get_build()
        after_equipped_slots = _equipped_slots(candidate_build)
        slot_regressions = sorted(before_equipped_slots - after_equipped_slots)
        whole_build_legality = hard_legality.audit_build(
            hard_legality.augment_build_with_snapshot_gear(
                candidate_build,
                candidate_xml,
                item_legality_overrides={slot: legality},
            )
        )
        legality_regression = hard_legality.compare_audits_for_regression(
            before_whole_build_legality,
            whole_build_legality,
        )
        rejection_reasons = [
            *(
                [{"code": "equipped_slot_regression", "slots": slot_regressions}]
                if slot_regressions
                else []
            ),
            *legality_regression["reasons"],
        ]
        if rejection_reasons:
            attribute_only = all(
                isinstance(reason, dict) and reason.get("code") == "attribute_requirement_unmet"
                for reason in rejection_reasons
            )
            if planning and attribute_only:
                shortfalls = (
                    (whole_build_legality.get("checks") or {}).get("attributes") or {}
                ).get("shortfalls") or []
                return {
                    "ok": False,
                    "errorCode": "whole_build_legality_check_failed",
                    "planning": True,
                    "error": (
                        "The optimized item needs attribute bridging before the current character "
                        "can equip it (planning mode: the candidate is preserved for chain "
                        "planning, not equipped)."
                    ),
                    "slot": slot,
                    "base": base,
                    "rejectedCandidate": final,
                    "rejectionReasons": rejection_reasons,
                    "projectedShortfalls": shortfalls,
                    "bridgeAffixSuggestions": _attribute_bridge_suggestions(shortfalls),
                    "wholeBuildLegality": whole_build_legality,
                    "legalityRegression": legality_regression,
                }
            return {
                "ok": False,
                "errorCode": "whole_build_legality_check_failed",
                "error": (
                    "The optimized item made the complete character illegal and was discarded."
                ),
                "slot": slot,
                "base": base,
                "rejectedCandidate": final,
                "rejectionReasons": rejection_reasons,
                "wholeBuildLegality": whole_build_legality,
                "legalityRegression": legality_regression,
                "slotRegression": {
                    "beforeCount": len(before_equipped_slots),
                    "afterCount": len(after_equipped_slots),
                    "missingSlots": slot_regressions,
                },
            }
        after_vals = engine.get_stats(keys)["stats"]
        warnings = []
        if whole_build_legality.get("hardFailures") and not legality_regression["regressed"]:
            warnings.append(
                "the candidate did not introduce or worsen deterministic legality failures, "
                "but the diagnostic baseline already has unresolved hard-legality blockers"
            )
        if keep_resists_capped:
            after_missing = engine.get_defenses().get("resistMissing") or {}
            # A resist "broke" if it was at/above cap before (0 points missing) and is below cap
            # after (>0 missing). `resistMissing` uses PoB's real per-element cap, so this is correct
            # for raised max-res too — not a hard-coded 75. (PoB floors *ResistOverCap at 0, so the
            # old over-cap-goes-negative check could never fire.)
            broke = [
                el
                for el in _RES_KEYS
                if (before_missing.get(el) or 0) <= 0 < (after_missing.get(el) or 0)
            ]
            if broke:
                warnings.append(
                    "this craft drops {} resistance below cap — re-cap on another slot, or add "
                    "TotalEHP to `goals` so the craft keeps resistances itself.".format(
                        "/".join(broke)
                    )
                )
        if not chosen:
            warnings.append(
                "no affix in this base's pool improved the goal — the active skill likely doesn't "
                "scale off this slot (e.g. damage that doesn't use this item's stats). The crafted "
                "item is blank; pick a slot/metric the skill actually moves, or optimize a defensive "
                "metric (e.g. TotalEHP) on this slot instead."
            )
    except ValueError as exc:
        return {
            "ok": False,
            "errorCode": "optimized_item_eval_failed",
            "error": str(exc),
            "slot": slot,
            "base": base,
        }
    finally:
        engine.load_build_xml(snapshot)

    goal_desc = (
        "blend " + ", ".join(f"{k}×{w:g}" for k, w in weights.items()) if weights else metric
    )
    out: dict[str, Any] = {
        "ok": True,
        "slot": slot,
        "base": base,
        "itemLevel": ilvl,
        "item": final,
        "legalityCheck": legality,
        "wholeBuildLegality": whole_build_legality,
        "legalityRegression": legality_regression,
        "slotRegression": {
            "beforeCount": len(before_equipped_slots),
            "afterCount": len(after_equipped_slots),
            "missingSlots": [],
        },
        "affixes": [x["line"] for x in chosen],
        "attainability": [
            {"affix": c["line"], "ilvl": c.get("ilvl", 0), "tiers": c.get("tiers", 1)}
            for c in chosen
        ],
        "craft": _craft_summary(chosen, len(pre), len(suf)),
        "warnings": warnings,
        "note": (
            f"Theoretical best-in-slot for {goal_desc} ({rolls} rolls) from this base's real mod "
            "pool — equip it with equip_item, then verify attainability/price with get_prices. "
            "Greedy search; pass thorough=true for a swap pass. Ignores un-modelled mechanics."
        ),
    }
    if weights:
        out["goals"] = weights
        out["metricsBefore"] = {k: _round2(before_vals.get(k)) for k in keys}
        out["metricsAfter"] = {k: _round2(after_vals.get(k)) for k in keys}
    else:
        out["metric"] = metric
        out["metricBefore"] = _round2(before_vals.get(metric))
        out["metricAfter"] = _round2(after_vals.get(metric))
    return out


def _equipped_slots(build: dict[str, Any]) -> set[str]:
    gear = build.get("gear") if isinstance(build, dict) else None
    if not isinstance(gear, dict):
        return set()
    return {
        str(slot)
        for slot, item in gear.items()
        if (isinstance(item, dict) and bool(item)) or (isinstance(item, str) and bool(item.strip()))
    }


_UPGRADE_SLOTS = (
    "Weapon 1",
    "Weapon 2",
    "Helmet",
    "Body Armour",
    "Gloves",
    "Boots",
    "Belt",
    "Amulet",
    "Ring 1",
    "Ring 2",
)


def rank_upgrades(
    engine: PobEngine,
    metric: str = "TotalDPS",
    goals: dict[str, float] | None = None,
    slots: list[str] | None = None,
    rolls: str = "realistic",
    top: int = 8,
) -> dict[str, Any]:
    """Rank gear slots by how much recrafting each would gain — 'what should I upgrade next'.

    Recrafts each candidate slot independently (via optimize_item, single `metric` or weighted
    `goals`) to its best, measures the gain over the CURRENT item there, and ranks high→low.
    Read-only: every probe is snapshotted and restored. Gains are NOT additive — recrafting one slot
    shifts the others — so upgrade the top slot, then re-run. Empty slots with no base are skipped
    (optimize that slot directly with a `base` to explore them).
    """
    candidate_slots = list(slots) if slots else list(_UPGRADE_SLOTS)
    ranked: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    rejected: list[dict[str, Any]] = []
    for slot in candidate_slots:
        r = optimize_item(
            engine, slot, metric=metric, goals=goals, rolls=rolls, keep_resists_capped=True
        )
        if not r.get("ok"):
            if r.get("errorCode") == "whole_build_legality_check_failed":
                rejected.append(
                    {
                        "slot": slot,
                        "errorCode": r["errorCode"],
                        "rejectionReasons": r.get("rejectionReasons") or [],
                        "wholeBuildLegality": r.get("wholeBuildLegality"),
                        "slotRegression": r.get("slotRegression"),
                    }
                )
            skipped.append({"slot": slot, "reason": str(r.get("error", "no craftable affixes"))})
            continue
        entry: dict[str, Any] = {"slot": slot, "affixes": r["affixes"], "item": r["item"]}
        if r.get("warnings"):
            entry["warnings"] = r["warnings"]
        if goals:
            mb, ma = r["metricsBefore"], r["metricsAfter"]
            entry["deltas"] = {k: _round2((ma.get(k) or 0) - (mb.get(k) or 0)) for k in ma}
            entry["score"] = round(
                sum(
                    w * (((ma.get(k) or 0) - (mb.get(k) or 0)) / max(abs(mb.get(k) or 0), 1.0))
                    for k, w in goals.items()
                    if _num(w)
                ),
                4,
            )
            entry["_sort"] = entry["score"]
        else:
            mb, ma = r.get("metricBefore"), r.get("metricAfter")
            if isinstance(ma, (int, float)) and isinstance(mb, (int, float)):
                delta = float(ma) - float(mb)  # gain from recrafting this slot
            else:
                delta = float(ma) if isinstance(ma, (int, float)) else 0.0  # empty slot = full add
            entry["metric"] = metric
            entry["before"], entry["after"], entry["delta"] = mb, ma, _round2(delta)
            entry["_sort"] = delta
        ranked.append(entry)
    ranked.sort(key=lambda x: x["_sort"] if _num(x.get("_sort")) else 0.0, reverse=True)
    for e in ranked:
        e.pop("_sort", None)
    return {
        "ok": True,
        "metric": "blend" if goals else metric,
        "goals": goals or None,
        "ranked": ranked[:top],
        "skipped": skipped,
        "rejected": rejected,
        "note": (
            "Each slot recrafted independently to its best for the goal, ranked by the gain over "
            "your CURRENT item there — upgrade the top slot first. Gains are NOT additive (crafting "
            "one slot shifts the rest); re-run after each real change. Targets are theoretical — "
            "price them with get_prices."
        ),
    }


def optimize_jewel(
    engine: PobEngine,
    metric: str = "TotalDPS",
    base: str = "Emerald",
    goals: dict[str, float] | None = None,
    rolls: str = "realistic",
) -> dict[str, Any]:
    """Craft the best-in-slot rare JEWEL for the active build (marginal-ranked).

    A jewel's explicit mods apply globally, so each candidate mod is measured as a custom modifier
    on the REAL build (merged with existing custom mods) and ranked by marginal gain — jewel mods are
    largely independent, so the top picks ≈ the best jewel, far cheaper than a full re-search. Pick a
    `base` matching the socket's attribute (Emerald=dex, Ruby=str, Sapphire=int, Diamond=all).
    Returns a jewel to socket with equip_jewel into an ALLOCATED socket. Radius/Time-Lost jewels
    aren't modelled this way (their effect is positional).
    """
    bi = db.get_item(base)
    if not bi or "jewel" not in (bi.get("tags") or []):
        return {
            "ok": False,
            "error": f"'{base}' is not a jewel base — use Emerald/Ruby/Sapphire/Diamond.",
        }
    pool = db.affix_pool(base)
    pre, suf = pool["prefixes"], pool["suffixes"]
    if not pre and not suf:
        return {"ok": False, "error": f"No craftable jewel affixes for base '{base}'."}

    weights: dict[str, float] = {}
    if goals:
        weights = {str(k): float(v) for k, v in goals.items() if _num(v) and float(v) > 0}
        if not weights:
            return {"ok": False, "error": "goals must map stat names to positive weights."}
    keys = list(weights) if weights else [metric]

    existing = (engine.get_build().get("customMods") or "").strip()
    snapshot = engine.get_xml()
    try:

        def measure(extra: list[str]) -> dict[str, Any]:
            mods = (existing + "\n" + "\n".join(extra)).strip() if extra else existing
            r = engine.set_config(custom_mods=mods)
            st = r.get("stats") if isinstance(r, dict) else None
            return st if isinstance(st, dict) else {}

        base_stats = measure([])
        denom = {k: max(abs(base_stats.get(k) or 0.0), 1.0) for k in keys}

        def score(st: dict[str, Any]) -> float:
            if weights:
                return sum(
                    w * ((st.get(k) or 0.0) - (base_stats.get(k) or 0.0)) / denom[k]
                    for k, w in weights.items()
                )
            v = st.get(metric)
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0

        base_score = score(base_stats)

        def ranked_side(side: list[dict[str, Any]]) -> list[tuple[float, str, dict[str, Any]]]:
            scored = []
            for m in side:
                line = _roll(m["text"], rolls)
                gain = score(measure([line])) - base_score
                if gain > 1e-9:
                    scored.append((gain, line, m))
            scored.sort(key=lambda x: -x[0])
            return scored

        chosen: list[dict[str, Any]] = []
        used: set[str] = set()
        for side, cap in ((ranked_side(pre), 3), (ranked_side(suf), 3)):
            n = 0
            for _gain, line, m in side:
                if n >= cap:
                    break
                if m["group"] in used:
                    continue
                chosen.append(
                    {
                        "line": line,
                        "group": m["group"],
                        "type": m["type"],
                        "tiers": m.get("tiers", 1),
                        "ilvl": m.get("required_level", 0),
                    }
                )
                used.add(m["group"])
                n += 1
        final_lines = [c["line"] for c in chosen]
        final_stats = measure(final_lines)
    finally:
        engine.load_build_xml(snapshot)

    out: dict[str, Any] = {
        "ok": True,
        "base": base,
        "item": f"Rarity: Rare\nOptimized Jewel\n{base}\n--------\n" + "\n".join(final_lines),
        "affixes": final_lines,
        "attainability": [
            {"affix": c["line"], "ilvl": c["ilvl"], "tiers": c["tiers"]} for c in chosen
        ],
        "craft": _craft_summary(chosen, len(pre), len(suf)),
        "note": (
            "Best jewel by marginal gain (jewel mods are ~independent). Socket it with equip_jewel "
            "into an ALLOCATED tree socket (list_jewel_sockets). Verify your jewel base's affix limit "
            "— some hold fewer than 3 prefix / 3 suffix. Radius/Time-Lost jewels aren't modelled "
            "here — evaluate them positionally with evaluate_jewel_socket."
        ),
    }
    if weights:
        out["goals"] = weights
        out["metricsBefore"] = {k: _round2(base_stats.get(k)) for k in keys}
        out["metricsAfter"] = {k: _round2(final_stats.get(k)) for k in keys}
    else:
        out["metric"] = metric
        out["metricBefore"] = _round2(base_stats.get(metric))
        out["metricAfter"] = _round2(final_stats.get(metric))
    return out


_OFFENSE_SLOTS = ("Weapon 1", "Amulet", "Gloves", "Ring 1")
_DEFENSE_SLOTS = ("Body Armour", "Helmet", "Boots", "Belt", "Ring 2", "Weapon 2")

# Armour/jewellery slots plan_gear can AUTO-BASE for a from-scratch set -> the corpus item_class to
# pull a base from. Weapons (and the off-hand) are archetype-defining, so they're left to the caller.
_AUTO_BASE_CLASS = {
    "Helmet": "Helmet",
    "Body Armour": "Body Armour",
    "Gloves": "Gloves",
    "Boots": "Boots",
    "Belt": "Belt",
    "Amulet": "Amulet",
    "Ring 1": "Ring",
    "Ring 2": "Ring",
}


def _attr_bias(engine: PobEngine) -> str:
    """The build's dominant attribute ('str'/'dex'/'int') — picks wearable, layer-appropriate bases."""
    st = engine.get_stats(["Str", "Dex", "Int"]).get("stats") or {}
    by = {"str": st.get("Str") or 0, "dex": st.get("Dex") or 0, "int": st.get("Int") or 0}
    return max(by, key=lambda k: by[k])


# Allocated passives whose value depends on the BASE TYPE of a gear slot. plan_gear must respect
# these when auto-basing a from-scratch set, or it plans a coherent-but-wrong defence layer
# (e.g. an armour chest that starves Spectral Ward's evasion→ES conversion).
_DEFENSE_LAYER_NOTABLE_BIAS = {
    "Spectral Ward": {"Body Armour": "dex"},  # evasion chest feeds the conversion
    "Subterfuge Mask": {"Helmet": "int"},  # ES helmet feeds evasion conversion
    "Iron Reflexes": {"Body Armour": "str", "Helmet": "str"},
}


def _defense_layer_bias(build: dict[str, Any]) -> dict[str, str]:
    """Map allocated passives onto per-slot base-attribute preferences ({slot: 'str'|'dex'|'int'})."""
    notables = {str(name) for name in build.get("notables") or []}
    keystones = {str(name) for name in build.get("keystones") or []}
    triggers = notables | keystones
    bias: dict[str, str] = {}
    for passive_name, slot_attr in _DEFENSE_LAYER_NOTABLE_BIAS.items():
        if passive_name in triggers:
            bias.update(slot_attr)
    return bias


def _marginal_craft(
    engine: PobEngine,
    slot: str,
    base: str,
    weights: dict[str, float],
    rolls: str,
    *,
    chaos_resist_target: int,
    ilvl: int,
) -> str | None:
    """Fast per-slot craft: rank each affix by its marginal weighted gain (TWO batched evals — bare
    base, then all single-affix candidates), then take the top 3 prefix + 3 suffix (group-exclusive).
    Approximate (ignores affix interaction) but ~6x cheaper than the full greedy — used by plan_gear
    so a whole-set plan fits in one call."""
    pool = db.affix_pool(base, ilvl=ilvl)
    current_chaos = float((engine.get_defenses().get("resistances") or {}).get("chaos") or 0)
    pre = _without_unneeded_chaos_resistance(
        pool["prefixes"], current_chaos=current_chaos, target_chaos=chaos_resist_target
    )
    suf = _without_unneeded_chaos_resistance(
        pool["suffixes"], current_chaos=current_chaos, target_chaos=chaos_resist_target
    )
    if not pre and not suf:
        return None
    keys = list(weights)
    meta = [(m, _roll(m["text"], rolls)) for m in pre + suf]
    base_res = engine.eval_items(slot, [_item_text(base, [], slot, ilvl=ilvl)], keys=keys)[
        "results"
    ]
    base_stats = base_res[0] if base_res and isinstance(base_res[0], dict) else {}
    denom = {k: max(abs(base_stats.get(k) or 0.0), 1.0) for k in keys}
    results = engine.eval_items(
        slot, [_item_text(base, [ln], slot, ilvl=ilvl) for _m, ln in meta], keys=keys
    )["results"]
    scored: list[tuple[float, dict[str, Any], str]] = []
    for (m, line), st in zip(meta, results):
        st = st if isinstance(st, dict) else {}
        gain = sum(
            w * ((st.get(k) or 0.0) - (base_stats.get(k) or 0.0)) / denom[k]
            for k, w in weights.items()
        )
        scored.append((gain, m, line))
    chosen_lines: list[str] = []
    used: set[str] = set()
    for typ in ("prefix", "suffix"):
        side = sorted((s for s in scored if s[1]["type"] == typ), key=lambda x: -x[0])
        n = 0
        for gain, m, line in side:
            if n >= 3:
                break
            if gain <= 1e-9 or m["group"] in used:
                continue
            chosen_lines.append(line)
            used.add(m["group"])
            n += 1
    return _item_text(base, chosen_lines, slot, ilvl=ilvl) if chosen_lines else None


def plan_gear(
    engine: PobEngine,
    dps_weight: float = 0.7,
    rolls: str = "realistic",
    slots: list[str] | None = None,
    auto_base: bool = True,
    min_ehp: float | None = None,
    stage: GearStage = "auto",
    chaos_resist_target: int | None = None,
) -> dict[str, Any]:
    """Plan a whole gear set that maximizes damage while capping resists (budget-allocation heuristic).

    The cross-slot trade-off: there are only so many suffix slots for resistances, so put them where
    they cost the least damage. This crafts OFFENSE slots damage-leaning and DEFENSE slots EHP-leaning
    (which naturally pulls the missing resists onto the defensive pieces), building each slot on top
    of the previous so the plan is coherent — not the order-independent, per-slot view of
    rank_upgrades.

    `auto_base` (default on) equips a sensible, attribute-appropriate base into EMPTY armour/jewellery
    slots so a from-scratch build gets a WHOLE set (weapons stay caller-supplied — they're archetype-
    defining). `min_ehp` adds a floor: after the damage/resist plan, defensive slots are re-crafted
    toward pure EHP (the cheapest DPS to give up) until TotalEHP reaches it. Read-only: returns the
    per-slot plan + projected whole-build DPS/EHP/resists; equip the items yourself. Greedy heuristic.
    """
    dps_weight = min(max(float(dps_weight), 0.0), 1.0)
    build = engine.get_build()
    profile = gear_stage_profile(
        build.get("level"), stage=stage, chaos_resist_target=chaos_resist_target
    )
    character_level = max(1, int(build.get("level") or 1))
    item_level = min(100, character_level)
    off_goal = (
        {"TotalDPS": dps_weight, "TotalEHP": round(1.0 - dps_weight, 3)}
        if dps_weight < 1.0
        else {"TotalDPS": 1.0}
    )
    defense_weight = float(profile["defenseWeight"])
    def_goal = {"TotalEHP": defense_weight, "TotalDPS": round(1.0 - defense_weight, 3)}
    order = (
        [_canonical_slot(str(s)) for s in slots]
        if slots
        else list(_OFFENSE_SLOTS) + list(_DEFENSE_SLOTS)
    )
    gear = build.get("gear") or {}

    snapshot = engine.get_xml()
    plan: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    rejected_illegal: list[dict[str, Any]] = []
    slot_base: dict[str, str] = {}
    base_direction: dict[str, str] = {}
    try:
        dominant_attr = _attr_bias(engine) if auto_base else "int"
        layer_bias = _defense_layer_bias(build)
        for slot in order:
            cur = gear.get(slot)
            if isinstance(cur, dict) and cur.get("base"):
                base: str | None = cur["base"]
            elif auto_base and slot in _AUTO_BASE_CLASS:
                # AUTO-BASE an empty armour/jewellery slot so a from-scratch build gets a whole set.
                # Allocated defence passives (Spectral Ward / Subterfuge Mask / Iron Reflexes) can
                # override the dominant-attribute base so the planned layer actually feeds them.
                slot_attr = layer_bias.get(slot, dominant_attr)
                base = db.pick_base(
                    _AUTO_BASE_CLASS[slot], slot_attr, max_drop_level=character_level
                )
                if base:
                    base_direction[slot] = slot_attr
                    engine.add_item(
                        _item_text(base, [], slot, ilvl=item_level), slot=slot
                    )  # bare base; crafted below
            else:
                base = None
            if not base:
                reason = (
                    "empty weapon slot — equip a base first (archetype-defining)"
                    if slot in ("Weapon 1", "Weapon 2")
                    else "empty (no base) — equip a base first"
                )
                skipped.append({"slot": slot, "reason": reason})
                continue
            slot_base[slot] = base
            goal = off_goal if slot in _OFFENSE_SLOTS else def_goal
            item = _marginal_craft(
                engine,
                slot,
                base,
                goal,
                rolls,
                chaos_resist_target=int(profile["chaosResistTarget"]),
                ilvl=item_level,
            )
            if not item:
                skipped.append({"slot": slot, "reason": "no improving affix in pool"})
                continue
            legality = _generated_item_legality(item)
            if not legality.get("ok"):
                skipped.append(
                    {"slot": slot, "reason": "generated item failed the shared legality audit"}
                )
                rejected_illegal.append(
                    {
                        "slot": slot,
                        "errorCode": "generated_item_legality_check_failed",
                        "issues": list(legality.get("issues") or []),
                    }
                )
                continue
            engine.add_item(item, slot=slot)  # persist so the next slot is crafted coherently
            affixes = [ln for ln in item.split("--------\n")[-1].split("\n") if ln.strip()]
            plan.append(
                {
                    "slot": slot,
                    "item": item,
                    "itemLevel": item_level,
                    "affixes": affixes,
                    "legalityCheck": legality,
                }
            )
        # EHP-floor recovery: if short of `min_ehp`, re-craft DEFENSE slots toward pure EHP (which
        # PoB's effective-HP also credits resists for) — the cheapest DPS to give up — until met.
        ehp_floor_met: bool | None = None
        if min_ehp:
            for slot in [s for s in order if s in _DEFENSE_SLOTS and s in slot_base]:
                if (engine.get_defenses().get("totalEHP") or 0) >= min_ehp:
                    break
                item = _marginal_craft(
                    engine,
                    slot,
                    slot_base[slot],
                    {"TotalEHP": 1.0},
                    rolls,
                    chaos_resist_target=int(profile["chaosResistTarget"]),
                    ilvl=item_level,
                )
                if not item:
                    continue
                legality = _generated_item_legality(item)
                if not legality.get("ok"):
                    rejected_illegal.append(
                        {
                            "slot": slot,
                            "errorCode": "generated_item_legality_check_failed",
                            "issues": list(legality.get("issues") or []),
                        }
                    )
                    continue
                engine.add_item(item, slot=slot)
                affixes = [ln for ln in item.split("--------\n")[-1].split("\n") if ln.strip()]
                plan[:] = [p for p in plan if p["slot"] != slot]
                plan.append(
                    {
                        "slot": slot,
                        "item": item,
                        "itemLevel": item_level,
                        "affixes": affixes,
                        "legalityCheck": legality,
                    }
                )
            ehp_floor_met = (engine.get_defenses().get("totalEHP") or 0) >= min_ehp
        stats = engine.get_stats(["TotalDPS", "FullDPS"])["stats"]
        d = engine.get_defenses()
    finally:
        engine.load_build_xml(snapshot)

    res = d.get("resistances") or {}
    missing = d.get("resistMissing") or {}
    res_capped = all((missing.get(e) or 0) <= 0 for e in _RES_KEYS)
    chaos_capped = (res.get("chaos") or 0) >= 75
    projected: dict[str, Any] = {
        "TotalDPS": _round2(stats.get("TotalDPS")),
        "FullDPS": _round2(stats.get("FullDPS")),
        "TotalEHP": _round2(d.get("totalEHP")),
        "resistances": res,
        "resistsCapped": res_capped,
        "chaosCapped": chaos_capped,
        "chaosTarget": profile["chaosResistTarget"],
        "chaosTargetMet": (res.get("chaos") or 0) >= profile["chaosResistTarget"],
    }
    if min_ehp:
        projected["minEHP"] = min_ehp
        projected["ehpFloorMet"] = ehp_floor_met
    conflict_warnings: list[str] = []
    if layer_bias:
        tree_triggers = sorted(
            name
            for name in {
                *{str(n) for n in build.get("notables") or []},
                *{str(k) for k in build.get("keystones") or []},
            }
            if name in _DEFENSE_LAYER_NOTABLE_BIAS
        )
        for slot_name, biased_attr in sorted(layer_bias.items()):
            if biased_attr != dominant_attr:
                conflict_warnings.append(
                    f"{slot_name} planned with {biased_attr} bases because the tree allocates "
                    f"{tree_triggers} — the build's dominant attribute is {dominant_attr}"
                )
    return {
        "ok": True,
        "plan": plan,
        "skipped": skipped,
        "rejectedIllegalCandidates": rejected_illegal,
        "autoBased": [s for s in slot_base if not (gear.get(s) or {}).get("base")],
        "baseDirection": base_direction,
        "conflictWarnings": conflict_warnings,
        "stageProfile": profile,
        "itemLevel": item_level,
        "projected": projected,
        "note": (
            "Budget-allocation heuristic: offense slots crafted damage-leaning, defense slots EHP-"
            "leaning (which pulls missing elemental resists onto the cheapest-DPS pieces), built "
            "slot-by-slot so it's coherent. Chaos resistance stops competing for suffixes once the "
            f"{profile['stage']} target ({profile['chaosResistTarget']}%) is met; pass an explicit "
            "chaos_resist_target only when the content or build identity warrants it. Read-only — "
            "equip the plan's items with equip_item. Greedy, not a global optimum."
        ),
    }


def evaluate_jewel_socket(
    engine: PobEngine,
    *,
    socket: int,
    raw: str,
    keys: list[str] | None = None,
) -> dict[str, Any]:
    """Read-only: measure ONE candidate jewel (raw PoB item text) placed in ONE tree socket.

    Unlike optimize_jewel (rare-only, global mods), this evaluates the actual equipped state:
    radius/Time-Lost jewels are placed in the socket and their positional grants over the
    radius' allocated passives are computed by the engine. The build is restored afterwards.
    `keys` defaults to damage + pool stats; deltas are vs the CURRENT build (so re-run after
    equipping a chosen jewel to compare against the new baseline).
    """
    keys = list(keys) if keys else ["TotalDPS", "TotalEHP", "Life", "EnergyShield"]
    slot = f"Jewel {socket}"
    base = engine.get_stats(keys)
    base_stats = base.get("stats") if isinstance(base, dict) else {}
    if not isinstance(base_stats, dict):
        return {
            "ok": False,
            "error": "engine returned no stats for the current build",
            "socket": socket,
        }
    result = engine.eval_items(slot=slot, items=[raw], keys=keys)
    results = result.get("results") if isinstance(result, dict) else None
    candidate = results[0] if results else None
    if not isinstance(candidate, dict):
        return {
            "ok": False,
            "error": "candidate jewel failed to parse or equip in this socket",
            "socket": socket,
        }
    deltas: dict[str, float] = {}
    for key in keys:
        before = base_stats.get(key)
        after = candidate.get(key)
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            deltas[key] = round(float(after) - float(before), 6)
    return {
        "ok": True,
        "socket": socket,
        "keys": keys,
        "baseStats": {k: base_stats.get(k) for k in keys},
        "candidateStats": {k: candidate.get(k) for k in keys},
        "deltas": deltas,
        "note": (
            "Read-only probe: the build was restored. Radius/Time-Lost grants are computed over "
            "the socket radius' allocated passives; an UNALLOCATED socket yields deltas near 0 — "
            "allocate the socket (alloc_passive) first, then evaluate. Deltas are vs the current "
            "build state."
        ),
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }
