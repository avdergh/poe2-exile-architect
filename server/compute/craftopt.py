"""Crafting-system optimizer (engine + PoB's own crafting data).

Beyond the standard rare affix pool, real PoE2 gear gets its power from the CRAFTING SYSTEM:
- **runes / soul cores** — mods socketed on top of the six affixes,
- **essences** — force a specific mod; *Perfect* essences grant mods the normal pool can't roll
  (e.g. % increased Life on body armour, "damage as extra" on weapons),
- **corruptions** — a corrupted implicit.

`craft_item` builds the best-in-slot item using all three, valuing every option on the engine. PoB
owns the crafting data (via `crafting_options`) and the math, so nothing is invented. Like
`optimize_item` it idealizes rolls — it's a *theoretical best-in-slot target*; each step is a real
craft (socket a rune, hit with an essence, Vaal for the corruption), so treat attainability/cost as
the sum of those steps.
"""

from __future__ import annotations

from typing import Any

from . import itemopt
from .engine import PobEngine

_num = itemopt._num
_roll = itemopt._roll


def _build_item(
    base: str,
    affix_lines: list[str],
    runes: list[tuple[str, list[str]]],
    corruption_line: str | None,
    item_level: int | None = None,
) -> str:
    """Assemble PoB item text from affixes + socketed runes + an optional corrupted implicit.

    Runes apply via the `Sockets:`/`Rune:` declaration plus their `{rune}` implicit lines (PoB
    re-derives them on parse); a corruption is an implicit line on a `Corrupted` item.
    """
    parts = ["Rarity: Rare", "Crafted Item", base]
    if item_level is not None:
        parts.append(f"Item Level: {int(item_level)}")
    implicits: list[str] = []
    if runes:
        parts.append("Sockets: " + " ".join("S" for _ in runes))
        for name, _ in runes:
            parts.append("Rune: " + name)
        for _, mod_lines in runes:
            implicits.extend("{rune}" + ml for ml in mod_lines)
    if corruption_line:
        implicits.append(corruption_line)
    if implicits:
        parts.append("Implicits: " + str(len(implicits)))
        parts.extend(implicits)
    else:
        parts.append("--------")
    parts.extend(affix_lines)
    if corruption_line:
        parts.append("Corrupted")
    return "\n".join(parts)


def _bare(base: str, item_level: int | None = None) -> str:
    level_line = f"Item Level: {int(item_level)}\n" if item_level is not None else ""
    return f"Rarity: Rare\nCrafted Item\n{base}\n{level_line}--------\n"


def craft_item(
    engine: PobEngine,
    slot: str,
    metric: str = "TotalDPS",
    base: str | None = None,
    goals: dict[str, float] | None = None,
    rolls: str = "realistic",
    rune_sockets: int = 2,
    ilvl: int = 82,
    use_essences: bool = True,
    use_corruption: bool = True,
    keep_resists_capped: bool = True,
) -> dict[str, Any]:
    """Craft the best-in-slot item using the full crafting system (runes + essences + corruption).

    Builds on `optimize_item` (the best rare, with Perfect-essence mods injected into the affix pool),
    then sockets the best rune(s) and applies the best corrupted implicit — each valued on the engine.
    `rune_sockets` is how many rune sockets the base is assumed to have (Artificer's Orb; martial
    weapons/armour typically allow up to 2). Read-only: the build is restored. See the module docstring.
    """
    weights: dict[str, float] = {}
    if goals:
        weights = {str(k): float(v) for k, v in goals.items() if _num(v) and float(v) > 0}
        if not weights:
            return {"ok": False, "error": "goals must map stat names to positive weights."}
    keys = list(weights) if weights else [metric]

    build = engine.get_build()
    gear = build.get("gear") or {}
    if not base:
        cur = gear.get(slot)
        base = cur.get("base") if isinstance(cur, dict) else None
    if not base:
        return {
            "ok": False,
            "error": f"No base for slot '{slot}'. Equip a base there, or pass base=.",
        }

    snapshot = engine.get_xml()
    try:
        engine.add_item(_bare(base, ilvl), slot=slot)  # so crafting_options can read the base
        co = engine.crafting_options(slot)
        if not co.get("ok"):
            return co

        # 1) Essences -> extra affix candidates. Only the SPECIAL (Perfect) essence mods matter for
        # power — normal essences just guarantee a mod already in the pool. Injected so the same greedy
        # values them against the natural pool, respecting prefix/suffix caps + group exclusivity.
        extra: dict[str, list[dict[str, Any]]] = {"prefixes": [], "suffixes": []}
        essence_by_line: dict[str, str] = {}
        if use_essences:
            for e in co.get("essences") or []:
                if not e.get("special"):
                    continue
                mt = str(e.get("modType") or "").lower()
                if mt not in ("prefix", "suffix"):
                    continue
                stat = str(e.get("stat") or "")
                extra[mt + "es"].append(
                    {
                        "group": e.get("group") or e.get("name"),
                        "text": stat,
                        "tiers": 1,
                        "required_level": e.get("tier") or 0,
                    }
                )
                essence_by_line[_roll(stat, rolls)] = str(e.get("name"))

        # 2) Best rare (with essence mods available in the pool).
        opt = itemopt.optimize_item(
            engine,
            slot,
            metric=metric,
            base=base,
            goals=goals,
            rolls=rolls,
            thorough=True,
            keep_resists_capped=keep_resists_capped,
            extra_mods=extra if (extra["prefixes"] or extra["suffixes"]) else None,
            ilvl=ilvl,
        )
        essence_candidates_rejected = False
        if (
            not opt.get("ok")
            and opt.get("errorCode") == "generated_item_legality_check_failed"
            and (extra["prefixes"] or extra["suffixes"])
        ):
            # Perfect-essence affixes can sit outside the ordinary base pool, but the final PoB
            # item text does not carry trustworthy essence provenance for completeness to verify.
            # Fall back to the normal legal pool instead of returning an item that our own final
            # artifact audit would reject.
            essence_candidates_rejected = True
            opt = itemopt.optimize_item(
                engine,
                slot,
                metric=metric,
                base=base,
                goals=goals,
                rolls=rolls,
                thorough=True,
                keep_resists_capped=keep_resists_capped,
                extra_mods=None,
                ilvl=ilvl,
            )
        if not opt.get("ok"):
            return opt
        affix_lines: list[str] = list(opt.get("affixes") or [])
        essences_used = sorted({essence_by_line[ln] for ln in affix_lines if ln in essence_by_line})

        # scoring: single metric = its value; goals = weighted gain relative to the rare baseline.
        engine.add_item(_build_item(base, affix_lines, [], None, ilvl), slot=slot)
        rare_stats = engine.get_stats(keys)["stats"]
        denom = {k: max(abs(rare_stats.get(k) or 0.0), 1.0) for k in keys}

        def score(st: dict[str, Any]) -> float:
            if weights:
                return sum(w * (st.get(k) or 0.0) / denom[k] for k, w in weights.items())
            v = st.get(metric)
            return (
                float(v)
                if isinstance(v, (int, float)) and not isinstance(v, bool)
                else float("-inf")
            )

        rare_score = score(rare_stats)

        # 3) Runes: pre-rank applicable runes by single-socket gain, then fill the sockets GREEDILY
        # from the top few — each socket takes the rune that most helps GIVEN the ones already in, so
        # the result can mix runes (e.g. damage + attack speed) or stack one, whichever the engine
        # prefers, and handles diminishing returns. Skip "Bonded:" set-bonus lines (need matching runes).
        chosen_runes: list[tuple[str, list[str]]] = []
        rune_cands: list[tuple[str, list[str]]] = []
        for r in co.get("runes") or []:
            mod_lines = [
                ml for ml in (r.get("mods") or []) if not str(ml).lower().startswith("bonded:")
            ]
            if mod_lines:
                rune_cands.append((str(r.get("name")), mod_lines))
        if rune_cands and rune_sockets > 0:
            ranked = engine.eval_items(
                slot,
                [_build_item(base, affix_lines, [rc], None, ilvl) for rc in rune_cands],
                keys=keys,
            )["results"]
            top = [
                rc
                for _, rc in sorted(
                    (
                        (score(s if isinstance(s, dict) else {}), rc)
                        for s, rc in zip(ranked, rune_cands)
                    ),
                    key=lambda x: x[0],
                    reverse=True,
                )[:8]  # bound the greedy fill to the strongest candidates
            ]
            cur = rare_score
            for _ in range(rune_sockets):
                texts = [
                    _build_item(base, affix_lines, [*chosen_runes, rc], None, ilvl) for rc in top
                ]
                res = engine.eval_items(slot, texts, keys=keys)["results"]
                best_score, best_rune = max(
                    ((score(s if isinstance(s, dict) else {}), rc) for s, rc in zip(res, top)),
                    key=lambda x: x[0],
                )
                if best_score <= cur + 1e-9:
                    break  # no remaining rune helps -> leave the socket empty
                chosen_runes.append(best_rune)
                cur = best_score

        # 4) Corruption: the best corrupted implicit on top of the (runed) item.
        chosen_corruption: str | None = None
        runed_base = _build_item(base, affix_lines, chosen_runes, None, ilvl)
        runed_score = score(engine.eval_items(slot, [runed_base], keys=keys)["results"][0] or {})
        if use_corruption and (co.get("corruptions") or []):
            corr_lines = [_roll(str(c.get("line")), rolls) for c in co["corruptions"]]
            texts = [_build_item(base, affix_lines, chosen_runes, cl, ilvl) for cl in corr_lines]
            cres = engine.eval_items(slot, texts, keys=keys)["results"]
            cbest_score, cbest_line = max(
                ((score(s if isinstance(s, dict) else {}), cl) for s, cl in zip(cres, corr_lines)),
                key=lambda x: x[0],
            )
            if cbest_score > runed_score:
                chosen_corruption = cbest_line

        # 5) Final item + measured stats.
        final = _build_item(base, affix_lines, chosen_runes, chosen_corruption, ilvl)
        engine.add_item(final, slot=slot)
        final_stats = engine.get_stats(keys)["stats"]
    finally:
        engine.load_build_xml(snapshot)

    def r2(x: Any) -> Any:
        return round(x, 2) if _num(x) else x

    steps: list[str] = [f"craft the rare ({len(affix_lines)} affixes)"]
    if essences_used:
        steps.append("force " + ", ".join(essences_used) + " with the matching essence")
    if chosen_runes:
        steps.append(f"socket {len(chosen_runes)}× {chosen_runes[0][0]}")
    if chosen_corruption:
        steps.append(f"corrupt for '{chosen_corruption}' (RISKY — Vaal Orb can brick the item)")

    out: dict[str, Any] = {
        "ok": True,
        "slot": slot,
        "base": base,
        "itemLevel": ilvl,
        "item": final,
        "affixes": affix_lines,
        "crafting": {
            "essencesUsed": essences_used,
            "essenceCandidatesRejectedByLegality": essence_candidates_rejected,
            "runes": [n for n, _ in chosen_runes],
            "runeSocketsAssumed": len(chosen_runes),
            "corruptedImplicit": chosen_corruption,
        },
        "craftSteps": steps,
        "note": (
            "Best-in-slot using the full crafting system, every option valued on the engine. Runes "
            "socket on top of affixes; Perfect essences add mods the normal pool can't roll; the "
            "corrupted implicit is a Vaal gamble (it can brick the item — craft it LAST). Idealized "
            f"rolls + assumes {len(chosen_runes) or rune_sockets} rune socket(s); a theoretical "
            "target — price the steps. 'Bonded' rune set-bonuses aren't modelled."
        ),
    }
    if essence_candidates_rejected:
        out["note"] += (
            " Perfect-essence-only affixes were omitted because the final item text did not carry "
            "enough provenance for the shared legality audit to verify them."
        )
    if weights:
        out["goals"] = weights
        out["metricsBefore"] = {k: r2(rare_stats.get(k)) for k in keys}
        out["metricsAfter"] = {k: r2(final_stats.get(k)) for k in keys}
    else:
        out["metric"] = metric
        out["metricBare"] = r2(rare_stats.get(metric))
        out["metricCrafted"] = r2(final_stats.get(metric))
    return out
