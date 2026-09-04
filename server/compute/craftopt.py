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

from copy import deepcopy
import threading
from typing import Any
from weakref import WeakKeyDictionary

from ..judge import hard_legality
from ..knowledge import item_legality, itemparse
from ..runtime import craft_receipts
from . import completeness, itemopt
from .engine import PobEngine
from .state import build_state_hash

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
    parts.extend(itemopt._generated_item_property_lines(base, ilvl=item_level))
    implicits: list[str] = itemopt._generated_item_implicit_lines(base, ilvl=item_level)
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
    properties = "".join(
        f"{line}\n" for line in itemopt._generated_item_property_lines(base, ilvl=item_level)
    )
    implicit_lines = itemopt._generated_item_implicit_lines(base, ilvl=item_level)
    implicit_text = (
        f"Implicits: {len(implicit_lines)}\n" + "\n".join(implicit_lines) + "\n"
        if implicit_lines
        else "--------\n"
    )
    return f"Rarity: Rare\nCrafted Item\n{base}\n{level_line}{properties}{implicit_text}"


def _without_socketed_runes(raw: str) -> str:
    """Remove only socket/rune declarations while preserving every ordinary item line."""

    lines = str(raw or "").replace("\r\n", "\n").splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        value = lines[index].strip()
        if value.startswith("Sockets:") or value.startswith("Rune:"):
            index += 1
            continue
        if value.startswith("Implicits:"):
            try:
                count = int(value.split(":", 1)[1].strip())
            except ValueError:
                count = 0
            implicits = lines[index + 1 : index + 1 + count]
            kept = [line for line in implicits if not line.strip().startswith("{rune}")]
            if kept:
                output.append(f"Implicits: {len(kept)}")
                output.extend(kept)
            else:
                output.append("--------")
            index += 1 + count
            continue
        if value.startswith("{rune}"):
            index += 1
            continue
        output.append(lines[index])
        index += 1
    return "\n".join(output)


def _augment_item_with_runes(
    raw: str,
    runes: list[tuple[str, list[str]]],
    *,
    socket_capacity: int | None = None,
) -> str:
    existing_capacity = int(itemparse.semantic_item_structure(raw).get("runeSockets") or 0)
    capacity = max(existing_capacity, len(runes), int(socket_capacity or 0))
    base = _without_socketed_runes(raw)
    lines = base.splitlines()
    insertion = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip().startswith("Implicits:") or set(line.strip()) == {"-"}
        ),
        len(lines),
    )
    declarations = ["Sockets: " + " ".join("S" for _ in range(capacity))]
    declarations.extend(f"Rune: {name}" for name, _mods in runes)
    lines[insertion:insertion] = declarations
    rune_lines = ["{rune}" + mod for _name, mods in runes for mod in mods]
    implicit_index = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("Implicits:")),
        None,
    )
    if implicit_index is not None:
        current = int(lines[implicit_index].split(":", 1)[1].strip())
        lines[implicit_index] = f"Implicits: {current + len(rune_lines)}"
        lines[implicit_index + 1 + current : implicit_index + 1 + current] = rune_lines
    else:
        separator = next(
            (index for index, line in enumerate(lines) if set(line.strip()) == {"-"}),
            len(lines),
        )
        replacement = [f"Implicits: {len(rune_lines)}", *rune_lines, "--------"]
        lines[separator : separator + (1 if separator < len(lines) else 0)] = replacement
    return "\n".join(lines)


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
    elemental_resist_target: int | None = None,
    chaos_resist_target: int | None = None,
    acquisition_profile: str = "realistic_trade",
) -> dict[str, Any]:
    """Craft the best-in-slot item using the full crafting system (runes + essences + corruption).

    Builds on `optimize_item` (the best rare, with Perfect-essence mods injected into the affix pool),
    then sockets the best rune(s) and applies the best corrupted implicit — each valued on the engine.
    `rune_sockets` is how many rune sockets the base is assumed to have (Artificer's Orb; martial
    weapons/armour typically allow up to 2). The build is restored; only a raw-free legality receipt
    for the returned item is persisted. See the module docstring.
    """
    slot = itemopt._canonical_slot(slot)
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
        essence_by_line: dict[str, dict[str, Any]] = {}
        if use_essences:
            for e in co.get("essences") or []:
                if not e.get("special"):
                    continue
                mt = str(e.get("modType") or "").lower()
                if mt not in ("prefix", "suffix"):
                    continue
                stat = str(e.get("stat") or "")
                rolled_line = _roll(stat, rolls)
                extra[mt + "es"].append(
                    {
                        "group": e.get("group") or e.get("name"),
                        "text": stat,
                        "tiers": 1,
                        "required_level": e.get("tier") or 0,
                    }
                )
                required_level = e.get("requiredLevel") or e.get("required_level")
                essence_by_line[rolled_line] = {
                    "line": rolled_line,
                    "name": str(e.get("name") or ""),
                    "group": str(e.get("group") or e.get("name") or ""),
                    "affixType": mt,
                    "requiredLevel": (
                        int(required_level) if isinstance(required_level, int) else None
                    ),
                    "option": dict(e),
                }

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
            special_affix_sources=essence_by_line or None,
            ilvl=ilvl,
            elemental_resist_target=elemental_resist_target,
            chaos_resist_target=chaos_resist_target,
            acquisition_profile=acquisition_profile,
        )
        essence_candidates_rejected = bool(
            not opt.get("ok")
            and opt.get("errorCode") == "generated_item_legality_check_failed"
            and (extra["prefixes"] or extra["suffixes"])
        )
        if not opt.get("ok"):
            return opt
        affix_lines: list[str] = list(opt.get("affixes") or [])
        selected_essences = [
            essence_by_line[line] for line in affix_lines if line in essence_by_line
        ]
        essences_used = sorted({str(entry.get("name") or "") for entry in selected_essences})

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
        rune_options: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
        rune_cands: list[tuple[str, list[str]]] = []
        resistance_profile = itemopt.gear_stage_profile(
            build.get("level"),
            stage="auto",
            elemental_resist_target=elemental_resist_target,
            chaos_resist_target=chaos_resist_target,
        )
        current_resists = engine.get_defenses().get("resistances") or {}
        for r in co.get("runes") or []:
            mod_lines = [
                ml for ml in (r.get("mods") or []) if not str(ml).lower().startswith("bonded:")
            ]
            remaining = itemopt._without_satisfied_resistances(
                [{"text": line} for line in mod_lines],
                current=current_resists,
                elemental_target=int(resistance_profile["elementalResistTarget"]),
                chaos_target=int(resistance_profile["chaosResistTarget"]),
            )
            if mod_lines and not remaining:
                continue
            if mod_lines:
                candidate = (str(r.get("name")), mod_lines)
                rune_cands.append(candidate)
                rune_options[(candidate[0], tuple(candidate[1]))] = dict(r)
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
            corruption_options = {
                _roll(str(candidate.get("line")), rolls): dict(candidate)
                for candidate in co["corruptions"]
            }
            corr_lines = list(corruption_options)
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
        selected_rune_sources = [
            {
                "name": name,
                "lines": mod_lines,
                "option": rune_options[(name, tuple(mod_lines))],
            }
            for name, mod_lines in chosen_runes
        ]
        selected_corruption_source = (
            {
                "line": chosen_corruption,
                "option": corruption_options[chosen_corruption],
            }
            if chosen_corruption
            else None
        )
        receipt_runtime_context = craft_receipts.current_runtime_context(
            getattr(engine, "info", None)
        )
        prepared_receipt = craft_receipts.prepare_receipt(
            final,
            slot=slot,
            item_level=ilvl,
            perfect_essences=selected_essences,
            runes=selected_rune_sources,
            corruption=selected_corruption_source,
            runtime_context=receipt_runtime_context,
        )
        final_legality = item_legality.audit_item(
            final,
            slot=slot,
            require_special_provenance=True,
            prepared_receipt=prepared_receipt,
        )
        if not final_legality.get("ok"):
            return {
                "ok": False,
                "errorCode": "generated_item_legality_check_failed",
                "error": "The final crafted item failed the shared source-aware legality audit.",
                "slot": slot,
                "base": base,
                "legalityCheck": final_legality,
            }
        engine.add_item(final, slot=slot)
        final_xml = engine.get_xml()
        canonical_final = completeness.equipped_item_text(final_xml, slot) or final
        prepared_receipt = craft_receipts.prepare_receipt(
            final,
            canonical_item_text=canonical_final,
            slot=slot,
            item_level=ilvl,
            perfect_essences=selected_essences,
            runes=selected_rune_sources,
            corruption=selected_corruption_source,
            runtime_context=receipt_runtime_context,
        )
        final_legality = item_legality.audit_item(
            final,
            slot=slot,
            require_special_provenance=True,
            prepared_receipt=prepared_receipt,
        )
        canonical_legality = item_legality.audit_item(
            canonical_final,
            slot=slot,
            require_special_provenance=True,
            prepared_receipt=prepared_receipt,
        )
        if not final_legality.get("ok") or not canonical_legality.get("ok"):
            return {
                "ok": False,
                "errorCode": "generated_item_roundtrip_legality_check_failed",
                "error": "PoB changed the crafted item into a state the source receipt cannot verify.",
                "slot": slot,
                "base": base,
                "legalityCheck": final_legality,
                "roundTripLegalityCheck": canonical_legality,
            }
        final_build = engine.get_build()
        final_whole_build_legality = hard_legality.audit_build(
            hard_legality.augment_build_with_snapshot_gear(
                final_build,
                final_xml,
                item_legality_overrides={slot: canonical_legality},
            )
        )
        baseline_whole_build_legality = hard_legality.audit_build(
            hard_legality.augment_build_with_snapshot_gear(build, snapshot)
        )
        legality_regression = hard_legality.compare_audits_for_regression(
            baseline_whole_build_legality,
            final_whole_build_legality,
        )
        if legality_regression["regressed"]:
            return {
                "ok": False,
                "errorCode": "whole_build_legality_check_failed",
                "error": "The final crafted item made the complete character illegal.",
                "slot": slot,
                "base": base,
                "legalityCheck": final_legality,
                "wholeBuildLegality": final_whole_build_legality,
                "rejectionReasons": legality_regression["reasons"],
            }
        final_stats = engine.get_stats(keys)["stats"]
    finally:
        engine.load_build_xml(snapshot)

    receipt_result = craft_receipts.persist_receipt(prepared_receipt)
    if receipt_result.get("status") != "recorded":
        return {
            "ok": False,
            "errorCode": receipt_result.get("errorCode") or "craft_receipt_write_failed",
            "error": "The crafted item was measured but its trusted source receipt could not be saved.",
        }

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
        "acquisitionProfile": acquisition_profile,
        "attainabilityPolicy": opt.get("attainabilityPolicy"),
        "affixes": affix_lines,
        "crafting": {
            "essencesUsed": essences_used,
            "essenceCandidatesRejectedByLegality": essence_candidates_rejected,
            "runes": [n for n, _ in chosen_runes],
            "runeSocketsAssumed": len(chosen_runes),
            "corruptedImplicit": chosen_corruption,
        },
        "craftSteps": steps,
        "craftReceiptRef": receipt_result["craftReceiptRef"],
        "itemFingerprint": receipt_result["itemFingerprint"],
        "legalityCheck": final_legality,
        "roundTripLegalityCheck": canonical_legality,
        "wholeBuildLegality": final_whole_build_legality,
        "note": (
            "Best-in-slot using the full crafting system, every option valued on the engine. Runes "
            "socket on top of affixes; Perfect essences add mods the normal pool can't roll; the "
            "corrupted implicit is a Vaal gamble (it can brick the item — craft it LAST). Idealized "
            f"rolls + assumes {len(chosen_runes) or rune_sockets} rune socket(s); a theoretical "
            "target — price the steps. 'Bonded' rune set-bonuses aren't modelled."
        ),
    }
    if weights:
        out["goals"] = weights
        out["metricsBefore"] = {k: r2(rare_stats.get(k)) for k in keys}
        out["metricsAfter"] = {k: r2(final_stats.get(k)) for k in keys}
    else:
        out["metric"] = metric
        out["metricBare"] = r2(rare_stats.get(metric))
        out["metricCrafted"] = r2(final_stats.get(metric))
    return out


def optimize_item_sockets(
    engine: PobEngine,
    *,
    slot: str,
    goals: dict[str, float],
    socket_count: int,
    elemental_resist_target: int | None = None,
    chaos_resist_target: int | None = None,
) -> dict[str, Any]:
    """Preserve one equipped ordinary item and optimize only its rune/soul-core sockets."""

    slot = itemopt._canonical_slot(slot)
    if socket_count not in {1, 2}:
        return {"ok": False, "errorCode": "socket_count_out_of_range"}
    weights = {str(key): float(value) for key, value in goals.items() if _num(value) and value > 0}
    if not weights:
        return {"ok": False, "error": "goals must map stat names to positive weights"}
    keys = list(weights)
    build = engine.get_build()
    snapshot = engine.get_xml()
    raw = completeness.equipped_item_text(snapshot, slot)
    if not raw:
        return {"ok": False, "errorCode": "equipped_item_not_found", "slot": slot}
    structure = itemparse.semantic_item_structure(raw)
    if structure.get("corrupted"):
        return {
            "ok": False,
            "errorCode": "incremental_socket_corrupted_item_unsupported",
            "slot": slot,
        }
    item_level = structure.get("itemLevel")
    if not isinstance(item_level, int):
        return {"ok": False, "errorCode": "equipped_item_level_missing", "slot": slot}

    base_raw = _without_socketed_runes(raw)
    prepared_receipt: dict[str, Any] | None = None
    final = base_raw
    selected_sources: list[dict[str, Any]] = []
    baseline_audit = hard_legality.audit_build(
        hard_legality.augment_build_with_snapshot_gear(build, snapshot)
    )
    try:
        engine.add_item(base_raw, slot=slot)
        options = engine.crafting_options(slot)
        if not isinstance(options, dict):
            return {
                "ok": False,
                "errorCode": "invalid_crafting_options_result",
                "slot": slot,
            }
        if not options.get("ok"):
            return options
        profile = itemopt.gear_stage_profile(
            build.get("level"),
            stage="auto",
            elemental_resist_target=elemental_resist_target,
            chaos_resist_target=chaos_resist_target,
        )
        current_resists = engine.get_defenses().get("resistances") or {}
        candidates: list[tuple[str, list[str], dict[str, Any]]] = []
        for option in options.get("runes") or []:
            mods = [
                str(line)
                for line in (option.get("mods") or [])
                if line and not str(line).casefold().startswith("bonded:")
            ]
            remaining = itemopt._without_satisfied_resistances(
                [{"text": line} for line in mods],
                current=current_resists,
                elemental_target=int(profile["elementalResistTarget"]),
                chaos_target=int(profile["chaosResistTarget"]),
            )
            if mods and not remaining:
                continue
            if mods:
                candidates.append((str(option.get("name") or ""), mods, dict(option)))
        if not candidates:
            return {"ok": True, "changed": False, "slot": slot, "reason": "no_socket_options"}

        baseline_stats = engine.get_stats(keys)["stats"]
        denom = {key: max(abs(baseline_stats.get(key) or 0.0), 1.0) for key in keys}

        def score(stats: dict[str, Any]) -> float:
            return sum(
                weight * (stats.get(key) or 0.0) / denom[key] for key, weight in weights.items()
            )

        chosen: list[tuple[str, list[str], dict[str, Any]]] = []
        current_score = score(baseline_stats)
        for _ in range(socket_count):
            texts = [
                _augment_item_with_runes(
                    base_raw,
                    [(name, mods) for name, mods, _option in [*chosen, candidate]],
                    socket_capacity=socket_count,
                )
                for candidate in candidates
            ]
            results = engine.eval_items(slot, texts, keys=keys).get("results") or []
            ranked = [
                (score(stats if isinstance(stats, dict) else {}), candidate)
                for stats, candidate in zip(results, candidates)
            ]
            if not ranked:
                break
            best_score, best = max(ranked, key=lambda value: value[0])
            if best_score <= current_score + 1e-9:
                break
            chosen.append(best)
            current_score = best_score
        if not chosen:
            return {
                "ok": True,
                "changed": False,
                "slot": slot,
                "reason": "no_beneficial_socket_option",
            }

        final = _augment_item_with_runes(
            base_raw,
            [(name, mods) for name, mods, _option in chosen],
            socket_capacity=socket_count,
        )
        selected_sources = [
            {"name": name, "lines": mods, "option": option} for name, mods, option in chosen
        ]
        runtime_context = craft_receipts.current_runtime_context(getattr(engine, "info", None))
        prepared_receipt = craft_receipts.prepare_receipt(
            final,
            slot=slot,
            item_level=item_level,
            perfect_essences=[],
            runes=selected_sources,
            corruption=None,
            runtime_context=runtime_context,
        )
        legality = item_legality.audit_item(
            final,
            slot=slot,
            require_special_provenance=True,
            prepared_receipt=prepared_receipt,
        )
        if not legality.get("ok"):
            return {
                "ok": False,
                "errorCode": "generated_item_legality_check_failed",
                "slot": slot,
                "legalityCheck": legality,
            }
        engine.add_item(final, slot=slot)
        final_xml = engine.get_xml()
        canonical_final = completeness.equipped_item_text(final_xml, slot) or final
        prepared_receipt = craft_receipts.prepare_receipt(
            final,
            canonical_item_text=canonical_final,
            slot=slot,
            item_level=item_level,
            perfect_essences=[],
            runes=selected_sources,
            corruption=None,
            runtime_context=runtime_context,
        )
        canonical_legality = item_legality.audit_item(
            canonical_final,
            slot=slot,
            require_special_provenance=True,
            prepared_receipt=prepared_receipt,
        )
        final_audit = hard_legality.audit_build(
            hard_legality.augment_build_with_snapshot_gear(
                engine.get_build(),
                final_xml,
                item_legality_overrides={slot: canonical_legality},
            )
        )
        regression = hard_legality.compare_audits_for_regression(baseline_audit, final_audit)
        if not canonical_legality.get("ok") or regression["regressed"]:
            return {
                "ok": False,
                "errorCode": "whole_build_legality_check_failed",
                "slot": slot,
                "roundTripLegalityCheck": canonical_legality,
                "rejectionReasons": regression["reasons"],
            }
        final_stats = engine.get_stats(keys)["stats"]
    finally:
        engine.load_build_xml(snapshot)

    if prepared_receipt is None:
        return {"ok": False, "errorCode": "craft_receipt_prepare_failed"}
    receipt = craft_receipts.persist_receipt(prepared_receipt)
    if receipt.get("status") != "recorded":
        return {"ok": False, "errorCode": receipt.get("errorCode") or "craft_receipt_write_failed"}
    return {
        "ok": True,
        "changed": True,
        "slot": slot,
        "socketCount": len(selected_sources),
        "socketCapacity": socket_count,
        "filledSocketCount": len(selected_sources),
        "remainingSocketCount": max(0, socket_count - len(selected_sources)),
        "remainingDisposition": (
            "no_positive" if len(selected_sources) < socket_count else "filled"
        ),
        "runes": [entry["name"] for entry in selected_sources],
        "item": final,
        "craftReceiptRef": receipt["craftReceiptRef"],
        "itemFingerprint": receipt["itemFingerprint"],
        "acceptedItemFingerprints": list(
            (prepared_receipt or {}).get("acceptedItemFingerprints") or []
        ),
        "goals": weights,
        "metricsBefore": {key: baseline_stats.get(key) for key in keys},
        "metricsAfter": {key: final_stats.get(key) for key in keys},
    }


_SOCKET_DECISION_LOCK = threading.RLock()
_SOCKET_BATCH_DECISIONS: WeakKeyDictionary[Any, dict[str, dict[str, str]]] = WeakKeyDictionary()
_SOCKET_ITEM_DECISIONS: WeakKeyDictionary[Any, dict[str, dict[str, dict[str, str]]]] = (
    WeakKeyDictionary()
)
_SOCKET_CARRY_STATES: WeakKeyDictionary[Any, dict[str, dict[str, Any]]] = WeakKeyDictionary()
_SOCKET_DECISION_LIMIT_PER_ENGINE = 64


def socket_batch_decisions_for_state(engine: Any, state_hash: str) -> dict[str, str]:
    with _SOCKET_DECISION_LOCK:
        try:
            return deepcopy((_SOCKET_BATCH_DECISIONS.get(engine) or {}).get(state_hash) or {})
        except TypeError:
            return {}


def carry_socket_decision_to_equipped_state(
    engine: Any,
    *,
    input_state_hash: str,
    output_state_hash: str,
    slot: str,
    item_fingerprint: str,
) -> str | None:
    """Carry one planned socket result only across its immediate item equip mutation."""

    canonical = itemopt._canonical_slot(str(slot))
    with _SOCKET_DECISION_LOCK:
        pending_by_slot = (_SOCKET_ITEM_DECISIONS.get(engine) or {}).get(canonical) or {}
        pending = pending_by_slot.get(str(item_fingerprint))
        if not isinstance(pending, dict):
            return None
        source_state_hash = str(pending.get("sourceStateHash") or "")
        if input_state_hash == source_state_hash:
            accumulated: dict[str, str] = {}
        else:
            lineage = (_SOCKET_CARRY_STATES.get(engine) or {}).get(input_state_hash)
            if not isinstance(lineage, dict) or lineage.get("sourceStateHash") != source_state_hash:
                return None
            accumulated = dict(lineage.get("decisions") or {})
        decision = str(pending.get("decision") or "")
        if not decision:
            return None
        accumulated[canonical] = decision
        states = _SOCKET_BATCH_DECISIONS.setdefault(engine, {})
        states[output_state_hash] = dict(accumulated)
        while len(states) > _SOCKET_DECISION_LIMIT_PER_ENGINE:
            states.pop(next(iter(states)))
        carry_states = _SOCKET_CARRY_STATES.setdefault(engine, {})
        carry_states[output_state_hash] = {
            "sourceStateHash": source_state_hash,
            "decisions": dict(accumulated),
        }
        while len(carry_states) > _SOCKET_DECISION_LIMIT_PER_ENGINE:
            carry_states.pop(next(iter(carry_states)))
        return decision


def socket_decision_freshness(engine: Any, state_hash: str, slot: str) -> str:
    """Return current/stale/missing for one slot's state- or item-bound socket decision."""

    canonical = itemopt._canonical_slot(str(slot))
    if canonical in socket_batch_decisions_for_state(engine, state_hash):
        return "current"
    with _SOCKET_DECISION_LOCK:
        try:
            state_decisions = _SOCKET_BATCH_DECISIONS.get(engine) or {}
            item_decisions = _SOCKET_ITEM_DECISIONS.get(engine) or {}
        except TypeError:
            return "missing"
        seen = any(canonical in values for values in state_decisions.values()) or bool(
            item_decisions.get(canonical)
        )
    return "stale" if seen else "missing"


def plan_item_sockets_batch(
    engine: PobEngine,
    *,
    slot_socket_counts: dict[str, int],
    goals: dict[str, float],
    elemental_resist_target: int | None = None,
    chaos_resist_target: int | None = None,
) -> dict[str, Any]:
    """Plan all requested ordinary-item sockets in one bounded MCP call."""

    if not slot_socket_counts or len(slot_socket_counts) > 8:
        return {"ok": False, "errorCode": "socket_batch_scope_invalid"}
    snapshot_hash = build_state_hash(engine.get_xml())
    results: list[dict[str, Any]] = []
    decisions: dict[str, str] = {}
    for raw_slot, count in slot_socket_counts.items():
        slot = itemopt._canonical_slot(str(raw_slot))
        result = optimize_item_sockets(
            engine,
            slot=slot,
            goals=goals,
            socket_count=int(count),
            elemental_resist_target=elemental_resist_target,
            chaos_resist_target=chaos_resist_target,
        )
        if not result.get("ok"):
            decision = "failed"
        elif result.get("changed"):
            decision = (
                "partial_no_positive"
                if int(result.get("remainingSocketCount") or 0) > 0
                else "socketed"
            )
        elif result.get("reason") == "no_beneficial_socket_option":
            decision = "no_positive"
        else:
            decision = "not_applicable"
        decisions[slot] = decision
        results.append({"slot": slot, "decision": decision, **result})
    with _SOCKET_DECISION_LOCK:
        engine_decisions = _SOCKET_BATCH_DECISIONS.setdefault(engine, {})
        engine_decisions[snapshot_hash] = dict(decisions)
        while len(engine_decisions) > _SOCKET_DECISION_LIMIT_PER_ENGINE:
            engine_decisions.pop(next(iter(engine_decisions)))
        item_decisions = _SOCKET_ITEM_DECISIONS.setdefault(engine, {})
        for result in results:
            fingerprints = {
                str(value)
                for value in (
                    result.get("acceptedItemFingerprints") or [result.get("itemFingerprint")]
                )
                if value
            }
            if not fingerprints:
                continue
            slot_decisions = item_decisions.setdefault(str(result["slot"]), {})
            for fingerprint in fingerprints:
                slot_decisions[fingerprint] = {
                    "decision": str(result["decision"]),
                    "sourceStateHash": snapshot_hash,
                }
            while len(slot_decisions) > _SOCKET_DECISION_LIMIT_PER_ENGINE:
                slot_decisions.pop(next(iter(slot_decisions)))
    return {
        "ok": all(result.get("ok") for result in results),
        "stateHash": snapshot_hash,
        "results": results,
        "decisions": decisions,
        "readOnly": True,
    }
