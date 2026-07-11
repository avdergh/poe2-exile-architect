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

from ..knowledge import db
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
) -> dict[str, Any]:
    """Craft the best-in-slot rare for a single `metric`, or a weighted blend via `goals`.

    `goals` (e.g. {"TotalDPS": .6, "TotalEHP": .4}) scores each candidate by the weighted sum of
    *relative* gains vs the bare base, so a single craft balances offense and defense (real endgame
    gear is blended, not pure-DPS or pure-EHP). Omit `goals` for the single-`metric` behaviour.
    `extra_mods` ({"prefixes":[...], "suffixes":[...]} of affix_pool-shaped dicts) injects extra
    candidate affixes beyond the base's natural pool — used by the crafting layer to offer
    essence-only mods (e.g. a Perfect Essence's % Life on body armour). See the module docstring.
    """
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
            return [r if isinstance(r, dict) else {} for r in res]

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
        engine.add_item(final, slot=slot)
        after_vals = engine.get_stats(keys)["stats"]
        warnings = []
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
    for slot in candidate_slots:
        r = optimize_item(
            engine, slot, metric=metric, goals=goals, rolls=rolls, keep_resists_capped=True
        )
        if not r.get("ok"):
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
            "— some hold fewer than 3 prefix / 3 suffix. Radius/Time-Lost jewels aren't modelled here."
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
    order = list(slots) if slots else list(_OFFENSE_SLOTS) + list(_DEFENSE_SLOTS)
    gear = build.get("gear") or {}

    snapshot = engine.get_xml()
    plan: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    slot_base: dict[str, str] = {}
    try:
        attr = _attr_bias(engine) if auto_base else "int"
        for slot in order:
            cur = gear.get(slot)
            if isinstance(cur, dict) and cur.get("base"):
                base: str | None = cur["base"]
            elif auto_base and slot in _AUTO_BASE_CLASS:
                # AUTO-BASE an empty armour/jewellery slot so a from-scratch build gets a whole set.
                base = db.pick_base(_AUTO_BASE_CLASS[slot], attr, max_drop_level=character_level)
                if base:
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
            engine.add_item(item, slot=slot)  # persist so the next slot is crafted coherently
            affixes = [ln for ln in item.split("--------\n")[-1].split("\n") if ln.strip()]
            plan.append({"slot": slot, "item": item, "itemLevel": item_level, "affixes": affixes})
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
                engine.add_item(item, slot=slot)
                affixes = [ln for ln in item.split("--------\n")[-1].split("\n") if ln.strip()]
                plan[:] = [p for p in plan if p["slot"] != slot]
                plan.append(
                    {"slot": slot, "item": item, "itemLevel": item_level, "affixes": affixes}
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
    return {
        "ok": True,
        "plan": plan,
        "skipped": skipped,
        "autoBased": [s for s in slot_base if not (gear.get(s) or {}).get("base")],
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
