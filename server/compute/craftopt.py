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
from contextlib import nullcontext
import math
import threading
from typing import Any
from weakref import WeakKeyDictionary

from ..judge import hard_legality
from ..knowledge import item_legality, itemparse
from ..knowledge.item_socket_text import without_socketed_runes as _without_socketed_runes
from ..runtime import craft_receipts
from ..runtime.compute_control import (
    ComputeStopped,
    check_compute_budget,
    publication_guard,
    report_compute_progress,
)
from . import attainability, completeness, itemopt, item_search, socket_limits, socket_probe
from .engine import PobEngine
from .state import build_state_hash, canonical_payload_hash

_num = itemopt._num
_roll = itemopt._roll


def _build_item(
    base: str,
    affix_lines: list[str],
    runes: list[tuple[str, list[str]]],
    corruption_line: str | None,
    item_level: int | None = None,
    reference_raw: str | None = None,
    *,
    _base_lines: tuple[tuple[str, ...], tuple[str, ...]] | None = None,
) -> str:
    """Assemble PoB item text from affixes + socketed runes + an optional corrupted implicit.

    Runes apply via the `Sockets:`/`Rune:` declaration plus their `{rune}` implicit lines (PoB
    re-derives them on parse); a corruption is an implicit line on a `Corrupted` item.
    """
    parts = ["Rarity: Rare", "Crafted Item", base]
    if item_level is not None:
        parts.append(f"Item Level: {int(item_level)}")
    properties, implicit_lines = _base_lines or (
        tuple(itemopt._generated_item_property_lines(base, ilvl=item_level)),
        tuple(
            itemopt._generated_item_implicit_lines(
                base, ilvl=item_level, reference_raw=reference_raw
            )
        ),
    )
    parts.extend(properties)
    implicits = list(implicit_lines)
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


def _bare(
    base: str,
    item_level: int | None = None,
    reference_raw: str | None = None,
    *,
    _base_lines: tuple[tuple[str, ...], tuple[str, ...]] | None = None,
) -> str:
    level_line = f"Item Level: {int(item_level)}\n" if item_level is not None else ""
    property_lines, implicit_lines = _base_lines or (
        tuple(itemopt._generated_item_property_lines(base, ilvl=item_level)),
        tuple(
            itemopt._generated_item_implicit_lines(
                base, ilvl=item_level, reference_raw=reference_raw
            )
        ),
    )
    properties = "".join(f"{line}\n" for line in property_lines)
    implicit_text = (
        f"Implicits: {len(implicit_lines)}\n" + "\n".join(implicit_lines) + "\n"
        if implicit_lines
        else "--------\n"
    )
    return f"Rarity: Rare\nCrafted Item\n{base}\n{level_line}{properties}{implicit_text}"


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
    # Pinned PoB needs an explicit entry for every socket. Omitting empty entries
    # can make a partial load reclassify Rune effects as enchants on round-trip.
    declarations.extend("Rune: None" for _ in range(capacity - len(runes)))
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


@item_search.read_only_search
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
    """Measure a crafting candidate using runes, essences and corruption.

    Builds on `optimize_item` (the best rare, with Perfect-essence mods injected into the affix pool),
    then sockets the best rune(s) and applies the best corrupted implicit — each valued on the engine.
    `rune_sockets` is how many rune sockets the base is assumed to have (Artificer's Orb; martial
    weapons/armour typically allow up to 2). The build is restored; only a raw-free legality receipt
    for the returned item is persisted. See the module docstring.
    """
    slot = itemopt._canonical_slot(slot)
    check_compute_budget()
    weights: dict[str, float] = {}
    if goals:
        weights = {
            str(k): float(v)
            for k, v in goals.items()
            if _num(v) and math.isfinite(v) and float(v) > 0
        }
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
    reference_raw = completeness.equipped_item_text_from_engine(engine, slot, snapshot_xml=snapshot)
    if reference_raw and base not in [line.strip() for line in reference_raw.splitlines()[:8]]:
        reference_raw = None
    base_lines = (
        tuple(itemopt._generated_item_property_lines(base, ilvl=ilvl)),
        tuple(itemopt._generated_item_implicit_lines(base, ilvl=ilvl, reference_raw=reference_raw)),
    )
    calculation_context = item_search.capture_context(engine)
    current_stats = item_search.baseline_stats(engine, slot, keys, build, calculation_context)
    baseline_complete = all(current_stats.get(key) is not None for key in keys)

    def stage_item(raw: str, *, check_context: bool = True) -> str:
        added = engine.add_item(raw, slot=slot)
        if not isinstance(added, dict) or added.get("ok") is not True:
            raise item_search.ItemSearchError("item_candidate_equip_failed", slot=slot)
        actual = completeness.equipped_item_text_from_engine(engine, slot)
        if not actual or not _socket_item_readback_matches(raw, actual):
            raise item_search.ItemSearchError("item_candidate_readback_mismatch", slot=slot)
        if check_context:
            item_search.verify_context(engine, calculation_context, slot=slot)
        return actual

    with item_search.preserved_state(engine):
        # Reading base-specific options is a counterfactual, not the optimize_item baseline.
        with item_search.preserved_state(engine):
            stage_item(
                _bare(base, ilvl, reference_raw, _base_lines=base_lines), check_context=False
            )
            co = engine.crafting_options(slot)
            if not isinstance(co, dict) or co.get("ok") is not True:
                return {
                    "ok": False,
                    "errorCode": (co.get("errorCode") if isinstance(co, dict) else None)
                    or "crafting_options_unavailable",
                }

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
        def candidate_text(runes, corruption=None):
            return _build_item(
                base, affix_lines, runes, corruption, ilvl, reference_raw, _base_lines=base_lines
            )

        stage_item(candidate_text([]))
        rare_stats = item_search.finite_stats(engine.get_stats(keys).get("stats"), keys)
        denom = {k: max(abs(rare_stats[k]), 1.0) for k in keys}

        def score(st: dict[str, Any]) -> float:
            item_search.finite_stats(st, keys)
            if weights:
                value = sum(w * st[k] / denom[k] for k, w in weights.items())
            else:
                value = float(st[metric])
            if not math.isfinite(value):
                raise item_search.ItemSearchError("item_measurement_nonfinite_score", slot=slot)
            return value

        rare_score = score(rare_stats)

        # All measurements below replace the same rare in one locked snapshot/context.
        # Exact text keeps Rune names distinct even when their numeric lines are identical.
        measurement_hash = build_state_hash(engine.get_xml())
        measurement_selection = item_search.capture_selection(engine)
        measurement_basis = (
            measurement_hash,
            slot,
            tuple(keys),
            canonical_payload_hash(calculation_context),
            canonical_payload_hash(measurement_selection),
            canonical_payload_hash(
                craft_receipts.current_runtime_context(getattr(engine, "info", None))
            ),
        )
        measured: dict[tuple[Any, ...], dict[str, Any]] = {}
        quota_ledger = socket_limits.prepare(snapshot)

        def measure(texts: list[str]) -> list[dict[str, Any]]:
            check_compute_budget()
            if build_state_hash(
                engine.get_xml()
            ) != measurement_hash or not item_search.selection_matches(
                engine, measurement_selection
            ):
                raise item_search.ItemSearchError("item_candidate_cache_context_changed", slot=slot)
            item_search.verify_context(engine, calculation_context, slot=slot)
            missing = list(
                dict.fromkeys(text for text in texts if (*measurement_basis, text) not in measured)
            )
            if missing:
                report_compute_progress(
                    "craft_candidates", len(measured), len(measured) + len(missing)
                )
                values = item_search.evaluate_items(engine, slot, missing, keys)
                # Publish to the local cache only after the complete batch has been validated.
                complete = [dict(item_search.finite_stats(value, keys)) for value in values]
                if len(complete) != len(missing):
                    raise item_search.ItemSearchError("item_measurement_count_mismatch", slot=slot)
                item_search.verify_context(engine, calculation_context, slot=slot)
                check_compute_budget()
                measured.update(
                    ((*measurement_basis, text), value) for text, value in zip(missing, complete)
                )
            return [dict(measured[(*measurement_basis, text)]) for text in texts]

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
        current_resists = item_search.finite_stats(
            engine.get_defenses().get("resistances"), ["fire", "cold", "lightning", "chaos"]
        )
        for r in co.get("runes") or []:
            check_compute_budget()
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
            ranked = measure([candidate_text([rc]) for rc in rune_cands])
            top = [
                rc
                for _, rc in sorted(
                    ((score(s), rc) for s, rc in zip(ranked, rune_cands)),
                    key=lambda x: x[0],
                    reverse=True,
                )
            ]
            cur = rare_score
            for _ in range(rune_sockets):
                check_compute_budget()
                eligible = [
                    rc
                    for rc in top
                    if quota_ledger.audit(
                        replacements={
                            slot: [
                                rune_options[(name, tuple(mods))]
                                for name, mods in [*chosen_runes, rc]
                            ]
                        },
                    )["ok"]
                ]
                if not eligible:
                    break
                texts = [candidate_text([*chosen_runes, rc]) for rc in eligible]
                res = measure(texts)
                best_score, best_rune = max(
                    ((score(s), rc) for s, rc in zip(res, eligible)),
                    key=lambda x: x[0],
                )
                if best_score <= cur + 1e-9:
                    break  # no remaining rune helps -> leave the socket empty
                chosen_runes.append(best_rune)
                cur = best_score

        # 4) Corruption: the best corrupted implicit on top of the (runed) item.
        chosen_corruption: str | None = None
        runed_base = candidate_text(chosen_runes)
        expected_final_stats = measure([runed_base])[0]
        runed_score = score(expected_final_stats)
        if use_corruption and (co.get("corruptions") or []):
            corruption_options = {
                _roll(str(candidate.get("line")), rolls): dict(candidate)
                for candidate in co["corruptions"]
            }
            corr_lines = list(corruption_options)
            texts = [candidate_text(chosen_runes, cl) for cl in corr_lines]
            cres = measure(texts)
            cbest_score, cbest_line, cbest_stats = max(
                ((score(s), cl, s) for s, cl in zip(cres, corr_lines)),
                key=lambda x: x[0],
            )
            if cbest_score > runed_score:
                chosen_corruption = cbest_line
                expected_final_stats = cbest_stats

        # 5) Final item + measured stats.
        final = candidate_text(chosen_runes, chosen_corruption)
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
        canonical_final = stage_item(final)
        final_xml = engine.get_xml()
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
        attainability_reasons = itemopt._item_attainability_reasons(
            canonical_final,
            attainability.policy_for(acquisition_profile),
            legality=canonical_legality,
        )
        if attainability_reasons:
            return {
                "ok": False,
                "errorCode": "generated_item_attainability_check_failed",
                "slot": slot,
                "reasons": attainability_reasons,
            }
        final_build = engine.get_build()
        if (
            not baseline_complete
            and (final_build.get("mainSkillWeaponCheck") or {}).get("compatible") is not True
        ):
            raise item_search.ItemSearchError("item_calculation_context_mismatch", slot=slot)
        missing_slots = sorted(
            itemopt._equipped_slots(build) - itemopt._equipped_slots(final_build)
        )
        if missing_slots:
            return {
                "ok": False,
                "errorCode": "whole_build_legality_check_failed",
                "slot": slot,
                "missingEquippedSlots": missing_slots,
            }
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
        final_stats = item_search.finite_stats(engine.get_stats(keys).get("stats"), keys)
        if any(
            not math.isclose(
                final_stats[key], expected_final_stats[key], rel_tol=1e-7, abs_tol=1e-8
            )
            for key in keys
        ):
            raise item_search.ItemSearchError("item_candidate_measurement_mismatch", slot=slot)
        baseline_score = score(current_stats) if baseline_complete else None
        candidate_score = score(final_stats)

    # The context manager has verified restoration before a durable source receipt is authorized.
    with publication_guard():
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
        "calculationContext": calculation_context,
        "measurementComplete": True,
        "comparison": {
            "baseline": "current_equipped_item",
            "baselineStatus": "measured" if baseline_complete else "unavailable_empty_weapon",
            "comparisonAvailable": baseline_complete,
            "sameContext": True,
            "baselineScore": baseline_score,
            "candidateScore": candidate_score,
            "netGain": candidate_score - baseline_score if baseline_complete else None,
            "positiveGainProven": baseline_complete and candidate_score > baseline_score + 1e-9,
        },
        "note": (
            "Measured crafting candidate; compare against the current item before applying. Runes "
            "socket on top of affixes; Perfect essences add mods the normal pool can't roll; the "
            "corrupted implicit is a Vaal gamble (it can brick the item — craft it LAST). Idealized "
            f"rolls + assumes {len(chosen_runes) or rune_sockets} rune socket(s); a theoretical "
            "search with greedy Rune selection, not a global optimum. 'Bonded' set-bonuses aren't modelled."
        ),
    }
    if weights:
        out["goals"] = weights
        out["metricsBefore"] = {k: r2(current_stats[k]) for k in keys}
        out["metricsBare"] = {k: r2(rare_stats[k]) for k in keys}
        out["metricsAfter"] = {k: r2(final_stats.get(k)) for k in keys}
    else:
        out["metric"] = metric
        out["metricBefore"] = r2(current_stats[metric])
        out["metricAfter"] = r2(final_stats[metric])
        out["metricBare"] = r2(rare_stats.get(metric))
        out["metricCrafted"] = r2(final_stats.get(metric))
    return out


_SOCKET_REVIEW_POLICY_VERSION = "item_socket_review_v2"


class _SocketMeasurementError(ValueError):
    def __init__(
        self, code: str, *, capability_gap: bool = False, details: dict[str, Any] | None = None
    ):
        super().__init__(code)
        self.code = code
        self.status = "capability_gap" if capability_gap else "measurement_error"
        self.details = details or {}


def _socket_stats(value: Any, keys: list[str], *, baseline: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _SocketMeasurementError("socket_measurement_invalid_stats")
    missing = [key for key in keys if key not in value or value[key] is None]
    if missing:
        raise _SocketMeasurementError("socket_measurement_missing_stats", capability_gap=baseline)
    if any(not _num(value[key]) or not math.isfinite(value[key]) for key in keys):
        raise _SocketMeasurementError("socket_measurement_nonfinite_stats")
    return value


def _socket_stage_item(
    engine: Any,
    raw: str,
    slot: str,
    context: Any,
    *,
    source_snapshot: str | None = None,
) -> None:
    if source_snapshot is not None:
        try:
            socket_probe.load_candidate(engine, source_snapshot, slot, raw)
        except ValueError as exc:
            details = getattr(exc, "details", {})
            raise _SocketMeasurementError(
                str(exc),
                details={"inputDiff": details["inputDiff"]} if "inputDiff" in details else None,
            ) from exc
        actual = completeness.equipped_item_text_from_engine(engine, slot)
        if not actual or not _socket_item_readback_matches(raw, actual):
            raise _SocketMeasurementError("socket_probe_readback_mismatch")
        item_search.verify_context(engine, context, slot=slot)
        return
    _socket_add_item(engine, raw, slot)
    item_search.verify_context(engine, context, slot=slot)


def _socket_add_item(engine: Any, raw: str, slot: str) -> None:
    result = engine.add_item(raw, slot=slot)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise _SocketMeasurementError("socket_probe_equip_failed")
    written_xml = engine.get_xml()
    engine.load_build_xml(written_xml)
    if build_state_hash(engine.get_xml()) != build_state_hash(written_xml):
        raise _SocketMeasurementError("socket_probe_readback_state_changed")
    actual = completeness.equipped_item_text_from_engine(engine, slot)
    if not actual or not _socket_item_readback_matches(raw, actual):
        raise _SocketMeasurementError("socket_probe_readback_mismatch")


def _socket_item_readback_matches(requested: str, actual: str) -> bool:
    expected = itemparse.semantic_item_structure(requested)
    observed = itemparse.semantic_item_structure(actual)
    if expected["itemFingerprint"] == observed["itemFingerprint"]:
        return True
    # PoB merges repeated Rune effects and emits conditional Bonded lines. Only this
    # source-bound normalization is allowed; the final provenance audit still owns the effects.
    return bool(
        expected["runeNames"]
        and sorted(name.casefold() for name in expected["runeNames"])
        == sorted(name.casefold() for name in observed["runeNames"])
        and expected["runeSockets"] == observed["runeSockets"]
        and itemparse.semantic_item_structure(_without_socketed_runes(requested))["itemFingerprint"]
        == itemparse.semantic_item_structure(_without_socketed_runes(actual))["itemFingerprint"]
    )


def optimize_item_sockets(
    engine: PobEngine,
    *,
    slot: str,
    goals: dict[str, float],
    socket_count: int,
    elemental_resist_target: int | None = None,
    chaos_resist_target: int | None = None,
    _publish_final: bool = True,
    _quota_ledger: socket_limits.SocketQuotaLedger | None = None,
) -> dict[str, Any]:
    """Measure socket candidates transactionally; incomplete probes never authorize a decision."""
    if getattr(engine, "_poe2_mutation_batch_recovery_required", False):
        _clear_socket_decisions(engine)
        return {"ok": False, "errorCode": "build_state_recovery_required", "recoveryRequired": True}
    lock = engine.transaction_lock() if hasattr(engine, "transaction_lock") else nullcontext()
    with lock:
        if getattr(engine, "_poe2_mutation_batch_recovery_required", False):
            _clear_socket_decisions(engine)
            return {
                "ok": False,
                "errorCode": "build_state_recovery_required",
                "recoveryRequired": True,
            }
        snapshot = engine.get_xml()
        snapshot_hash = build_state_hash(snapshot)
        snapshot_selection = item_search.capture_selection(engine)
        stopped: ComputeStopped | None = None
        try:
            check_compute_budget()
            result = _optimize_item_sockets_locked(
                engine,
                slot=slot,
                goals=goals,
                socket_count=socket_count,
                elemental_resist_target=elemental_resist_target,
                chaos_resist_target=chaos_resist_target,
                quota_ledger=_quota_ledger,
            )
        except ComputeStopped as exc:
            stopped = exc
            result = {
                "ok": False,
                "errorCode": exc.reason,
                "measurementStatus": "measurement_error",
                "measurementComplete": False,
            }
        except _SocketMeasurementError as exc:
            result = {
                "ok": False,
                "errorCode": exc.code,
                "measurementStatus": exc.status,
                **exc.details,
            }
        except item_search.ItemSearchError as exc:
            result = {"ok": False, "errorCode": exc.code, "measurementStatus": "measurement_error"}
        except Exception:  # noqa: BLE001 - never cache a partial/exceptional probe as no gain.
            result = {
                "ok": False,
                "errorCode": "socket_probe_failed",
                "measurementStatus": "measurement_error",
            }
        finally:
            try:
                engine.load_build_xml(snapshot)
                restored = build_state_hash(
                    engine.get_xml()
                ) == snapshot_hash and item_search.selection_matches(engine, snapshot_selection)
            except Exception:  # noqa: BLE001 - state identity, not a caller boolean, proves recovery.
                restored = False
        setattr(engine, "_poe2_mutation_batch_recovery_required", not restored)
        if not restored:
            _clear_socket_decisions(engine)
            return {
                "ok": False,
                "errorCode": "socket_probe_restore_failed",
                "measurementStatus": "measurement_error",
                "rolledBack": False,
                "recoveryRequired": True,
            }
        prepared = result.pop("_preparedReceipt", None)
        result.update(
            {
                "stateHash": snapshot_hash,
                "rolledBack": True,
                "recoveryRequired": False,
                "reviewPolicyVersion": _SOCKET_REVIEW_POLICY_VERSION,
            }
        )
        try:
            if stopped is not None:
                raise stopped
            with publication_guard(final=_publish_final):
                if result.get("ok") and result.get("changed"):
                    try:
                        receipt = craft_receipts.persist_receipt(prepared)
                    except Exception:  # noqa: BLE001 - persistence cannot erase proven restoration.
                        receipt = {}
                    if (
                        not isinstance(receipt, dict)
                        or receipt.get("status") != "recorded"
                        or not receipt.get("craftReceiptRef")
                        or not receipt.get("itemFingerprint")
                    ):
                        result = {
                            "ok": False,
                            "errorCode": (
                                receipt.get("errorCode") if isinstance(receipt, dict) else None
                            )
                            or "craft_receipt_write_failed",
                            "stateHash": snapshot_hash,
                            "rolledBack": True,
                            "recoveryRequired": False,
                            "reviewPolicyVersion": _SOCKET_REVIEW_POLICY_VERSION,
                        }
                    else:
                        result.update(
                            craftReceiptRef=receipt["craftReceiptRef"],
                            itemFingerprint=receipt["itemFingerprint"],
                        )
                return _record_socket_result(engine, snapshot_hash, slot, result)
        except ComputeStopped as exc:
            # Revoke this slot's earlier pending recommendation, without authorizing any new item.
            _record_socket_result(
                engine,
                snapshot_hash,
                slot,
                {
                    "ok": False,
                    "errorCode": exc.reason,
                    "measurementStatus": "measurement_error",
                    "measurementComplete": False,
                    "rolledBack": True,
                    "recoveryRequired": False,
                },
            )
            raise


def _optimize_item_sockets_locked(
    engine: PobEngine,
    *,
    slot: str,
    goals: dict[str, float],
    socket_count: int,
    elemental_resist_target: int | None = None,
    chaos_resist_target: int | None = None,
    quota_ledger: socket_limits.SocketQuotaLedger | None = None,
) -> dict[str, Any]:
    """Preserve one equipped ordinary item and optimize only its rune/soul-core sockets."""

    slot = itemopt._canonical_slot(slot)
    if socket_count not in {1, 2}:
        return {"ok": False, "errorCode": "socket_count_out_of_range"}
    if not goals or any(
        not _num(value) or not math.isfinite(value) or value <= 0 for value in goals.values()
    ):
        return {"ok": False, "error": "goals must map stat names to positive weights"}
    weights = {str(key): float(value) for key, value in goals.items()}
    keys = list(weights)
    build = engine.get_build()
    snapshot = engine.get_xml()
    quota_ledger = quota_ledger or socket_limits.prepare(snapshot)
    raw = completeness.equipped_item_text_from_engine(engine, slot, snapshot_xml=snapshot)
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
    socket_count = max(socket_count, int(structure.get("runeSockets") or 0))
    if socket_count > 2:
        return {"ok": False, "errorCode": "socket_count_out_of_range"}

    base_raw = _without_socketed_runes(raw)
    calculation_context = item_search.capture_context(engine)
    source_snapshot = snapshot if socket_probe.has_source_groups(snapshot) else None
    reload_source_candidates = socket_probe.requires_source_snapshot_probe(snapshot)
    prepared_receipt: dict[str, Any] | None = None
    final = base_raw
    selected_sources: list[dict[str, Any]] = []
    baseline_audit = hard_legality.audit_build(
        hard_legality.augment_build_with_snapshot_gear(build, snapshot)
    )
    original_result = engine.get_stats(keys)
    original_stats = _socket_stats(
        original_result.get("stats") if isinstance(original_result, dict) else None,
        keys,
        baseline=True,
    )
    _socket_stage_item(engine, base_raw, slot, calculation_context, source_snapshot=source_snapshot)
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
    defense_result = engine.get_defenses()
    current_resists = _socket_stats(
        defense_result.get("resistances") if isinstance(defense_result, dict) else None,
        ["fire", "cold", "lightning", "chaos"],
    )
    candidates: list[tuple[str, list[str], dict[str, Any]]] = []
    if not isinstance(options.get("runes"), list):
        raise _SocketMeasurementError("socket_options_incomplete")
    for option in options["runes"]:
        check_compute_budget()
        if (
            not isinstance(option, dict)
            or not option.get("name")
            or not isinstance(option.get("mods"), list)
        ):
            raise _SocketMeasurementError("socket_options_incomplete")
        if any(not isinstance(line, str) or not line.strip() for line in option["mods"]):
            raise _SocketMeasurementError("socket_options_incomplete")
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
        return {
            "ok": True,
            "changed": False,
            "slot": slot,
            "reason": "no_socket_options",
            "measurementStatus": "not_applicable",
            "measurementComplete": True,
            "calculationContext": calculation_context,
        }

    baseline_result = engine.get_stats(keys)
    baseline_stats = _socket_stats(
        baseline_result.get("stats") if isinstance(baseline_result, dict) else None, keys
    )
    denom = {key: max(abs(original_stats[key]), 1.0) for key in keys}

    def score(stats: dict[str, Any]) -> float:
        value = sum(weight * stats[key] / denom[key] for key, weight in weights.items())
        if not math.isfinite(value):
            raise _SocketMeasurementError("socket_measurement_nonfinite_score")
        return value

    chosen: list[tuple[str, list[str], dict[str, Any]]] = []
    chosen_stats = baseline_stats
    current_score = score(baseline_stats)
    measurement_basis = (
        build_state_hash(snapshot),
        slot,
        tuple(keys),
        canonical_payload_hash(calculation_context),
        canonical_payload_hash(item_search.capture_selection(engine)),
        canonical_payload_hash(
            craft_receipts.current_runtime_context(getattr(engine, "info", None))
        ),
    )
    measured: dict[tuple[Any, ...], dict[str, Any]] = {}
    for _ in range(socket_count):
        check_compute_budget()
        eligible = [
            candidate
            for candidate in candidates
            if quota_ledger.audit(
                replacements={slot: [option for _name, _mods, option in [*chosen, candidate]]},
            )["ok"]
        ]
        if not eligible:
            break
        texts = [
            _augment_item_with_runes(
                base_raw,
                [(name, mods) for name, mods, _option in [*chosen, candidate]],
                socket_capacity=socket_count,
            )
            for candidate in eligible
        ]
        missing = list(
            dict.fromkeys(text for text in texts if (*measurement_basis, text) not in measured)
        )
        fresh_results = []
        if source_snapshot is not None and reload_source_candidates:
            for index, text in enumerate(missing):
                check_compute_budget()
                report_compute_progress("socket_candidates", index, len(missing))
                _socket_stage_item(
                    engine, text, slot, calculation_context, source_snapshot=source_snapshot
                )
                response = engine.get_stats(keys)
                fresh_results.append(
                    _socket_stats(
                        response.get("stats") if isinstance(response, dict) else None, keys
                    )
                )
        elif missing:
            check_compute_budget()
            report_compute_progress("socket_candidates", 0, len(missing))
            fresh_results = item_search.evaluate_items(engine, slot, missing, keys)
            item_search.verify_context(engine, calculation_context, slot=slot)
        if len(fresh_results) != len(missing):
            raise _SocketMeasurementError("socket_measurement_count_mismatch")
        validated = [dict(_socket_stats(stats, keys)) for stats in fresh_results]
        check_compute_budget()
        measured.update(
            ((*measurement_basis, text), stats) for text, stats in zip(missing, validated)
        )
        results = [dict(measured[(*measurement_basis, text)]) for text in texts]
        ranked = [
            (score(_socket_stats(stats, keys)), candidate, stats)
            for stats, candidate in zip(results, eligible)
        ]
        if not ranked:
            break
        best_score, best, best_stats = max(ranked, key=lambda value: value[0])
        if best_score <= current_score + 1e-9:
            break
        chosen.append(best)
        chosen_stats = best_stats
        current_score = best_score
    if not chosen or current_score <= score(original_stats) + 1e-9:
        return {
            "ok": True,
            "changed": False,
            "slot": slot,
            "reason": "no_beneficial_socket_option",
            "measurementStatus": "no_positive",
            "measurementComplete": True,
            "calculationContext": calculation_context,
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
    prepared_receipt = craft_receipts.derive_socket_receipt(
        raw,
        final,
        slot=slot,
        item_level=item_level,
        runes=selected_sources,
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
    _socket_stage_item(engine, final, slot, calculation_context, source_snapshot=source_snapshot)
    final_xml = engine.get_xml()
    canonical_final = completeness.equipped_item_text_from_engine(
        engine, slot, snapshot_xml=final_xml
    )
    if not canonical_final:
        raise _SocketMeasurementError("socket_final_item_missing")
    prepared_receipt = craft_receipts.derive_socket_receipt(
        raw,
        final,
        canonical_item_text=canonical_final,
        slot=slot,
        item_level=item_level,
        runes=selected_sources,
        runtime_context=runtime_context,
    )
    canonical_legality = item_legality.audit_item(
        canonical_final,
        slot=slot,
        require_special_provenance=True,
        prepared_receipt=prepared_receipt,
    )
    final_build = engine.get_build()
    missing_slots = set(build.get("gear") or {}) - set(final_build.get("gear") or {})
    if missing_slots:
        return {
            "ok": False,
            "errorCode": "whole_build_legality_check_failed",
            "slot": slot,
            "missingEquippedSlots": sorted(missing_slots),
        }
    final_audit = hard_legality.audit_build(
        hard_legality.augment_build_with_snapshot_gear(
            final_build,
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
    final_result = engine.get_stats(keys)
    final_stats = _socket_stats(
        final_result.get("stats") if isinstance(final_result, dict) else None, keys
    )
    if score(final_stats) <= score(original_stats) + 1e-9:
        raise _SocketMeasurementError("socket_final_gain_not_reproduced")
    if any(
        not math.isclose(final_stats[key], chosen_stats[key], rel_tol=1e-7, abs_tol=1e-6)
        for key in keys
    ):
        raise _SocketMeasurementError("socket_final_metrics_not_reproduced")

    if prepared_receipt is None:
        return {"ok": False, "errorCode": "craft_receipt_prepare_failed"}
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
        "_preparedReceipt": prepared_receipt,
        "measurementStatus": "positive",
        "measurementComplete": True,
        "calculationContext": calculation_context,
        "acceptedItemFingerprints": list(
            (prepared_receipt or {}).get("acceptedItemFingerprints") or []
        ),
        "goals": weights,
        "metricsBefore": {key: original_stats.get(key) for key in keys},
        "metricsAfter": {key: final_stats.get(key) for key in keys},
    }


_SOCKET_DECISION_LOCK = threading.RLock()
_SOCKET_BATCH_DECISIONS: WeakKeyDictionary[Any, dict[str, dict[str, Any]]] = WeakKeyDictionary()
_SOCKET_ITEM_DECISIONS: WeakKeyDictionary[Any, dict[str, dict[str, dict[str, Any]]]] = (
    WeakKeyDictionary()
)
_SOCKET_CARRY_STATES: WeakKeyDictionary[Any, dict[str, dict[str, Any]]] = WeakKeyDictionary()
_SOCKET_DECISION_LIMIT_PER_ENGINE = 64


def _clear_socket_decisions(engine: Any) -> None:
    with _SOCKET_DECISION_LOCK:
        _SOCKET_BATCH_DECISIONS.pop(engine, None)
        _SOCKET_ITEM_DECISIONS.pop(engine, None)
        _SOCKET_CARRY_STATES.pop(engine, None)


def _record_socket_result(
    engine: Any,
    state_hash: str,
    slot: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """One publication path for direct and batch probes, replacing only this slot's evidence."""
    slot = itemopt._canonical_slot(str(slot))
    result = dict(result)
    complete = (
        result.get("measurementComplete") is True
        and result.get("reviewPolicyVersion") == _SOCKET_REVIEW_POLICY_VERSION
    )
    if not result.get("ok") or not complete:
        decision = result.get("measurementStatus")
        if decision not in {"measurement_error", "capability_gap"}:
            decision = "failed"
        result["ok"] = False
    elif result.get("changed"):
        decision = (
            "partial_socketed" if int(result.get("remainingSocketCount") or 0) > 0 else "socketed"
        )
    elif result.get("reason") == "no_beneficial_socket_option":
        decision = "no_positive"
    else:
        decision = "not_applicable"
    if not _socket_decision_evidence_valid(decision, result):
        decision = "measurement_error"
        result.update(
            ok=False,
            measurementStatus="measurement_error",
            errorCode="socket_measurement_evidence_incomplete",
        )
    result.update(slot=slot, decision=decision)
    with _SOCKET_DECISION_LOCK:
        # Reassessment supersedes the old pending plan and any evidence already carried from it.
        # Retain other slots and other source states; they are independent observations.
        carry_states = _SOCKET_CARRY_STATES.get(engine) or {}
        superseded_sources = {state_hash}
        ancestor = (carry_states.get(state_hash) or {}).get("sourceStateHash")
        if ancestor:
            superseded_sources.add(str(ancestor))
        item_decisions = _SOCKET_ITEM_DECISIONS.setdefault(engine, {})
        pending = item_decisions.get(slot) or {}
        for fingerprint, entry in list(pending.items()):
            if entry.get("sourceStateHash") in superseded_sources:
                pending.pop(fingerprint, None)
        if not pending:
            item_decisions.pop(slot, None)
        states = _SOCKET_BATCH_DECISIONS.setdefault(engine, {})
        for carried_hash, lineage in carry_states.items():
            if lineage.get("sourceStateHash") not in superseded_sources:
                continue
            lineage.get("decisions", {}).pop(slot, None)
            lineage.get("measurements", {}).pop(slot, None)
            carried = states.get(carried_hash) or {}
            carried.get("decisions", {}).pop(slot, None)
            carried.get("measurements", {}).pop(slot, None)
        entry = states.get(state_hash) or {}
        if entry.get("reviewPolicyVersion") != _SOCKET_REVIEW_POLICY_VERSION:
            entry = {
                "reviewPolicyVersion": _SOCKET_REVIEW_POLICY_VERSION,
                "decisions": {},
                "measurements": {},
            }
        entry["decisions"][slot] = decision
        entry["measurements"][slot] = {
            "measurementStatus": result.get("measurementStatus"),
            "measurementComplete": result.get("measurementComplete") is True,
            "applied": False,
        }
        states[state_hash] = entry
        while len(states) > _SOCKET_DECISION_LIMIT_PER_ENGINE:
            states.pop(next(iter(states)))
        if result.get("ok") and decision in {"socketed", "partial_socketed"}:
            fingerprints = {
                str(value)
                for value in (
                    result.get("acceptedItemFingerprints") or [result.get("itemFingerprint")]
                )
                if value
            }
            if fingerprints:
                pending = item_decisions.setdefault(slot, {})
                for fingerprint in fingerprints:
                    pending[fingerprint] = {
                        "decision": decision,
                        "sourceStateHash": state_hash,
                        "reviewPolicyVersion": _SOCKET_REVIEW_POLICY_VERSION,
                        "measurementStatus": "positive",
                        "measurementComplete": True,
                    }
                while len(pending) > _SOCKET_DECISION_LIMIT_PER_ENGINE:
                    pending.pop(next(iter(pending)))
    return result


def socket_batch_decisions_for_state(engine: Any, state_hash: str) -> dict[str, str]:
    with _SOCKET_DECISION_LOCK:
        try:
            entry = (_SOCKET_BATCH_DECISIONS.get(engine) or {}).get(state_hash) or {}
            if entry.get("reviewPolicyVersion") != _SOCKET_REVIEW_POLICY_VERSION:
                return {}
            measurements = entry.get("measurements") or {}
            return {
                slot: decision
                for slot, decision in (entry.get("decisions") or {}).items()
                if _socket_decision_evidence_valid(decision, measurements.get(slot) or {})
            }
        except TypeError:
            return {}


def socket_pending_slots_for_state(engine: Any, state_hash: str) -> list[str]:
    """List current positive plans which still need trusted equipment application."""
    with _SOCKET_DECISION_LOCK:
        decisions = socket_batch_decisions_for_state(engine, state_hash)
        if not decisions:
            return []
        entry = (_SOCKET_BATCH_DECISIONS.get(engine) or {}).get(state_hash) or {}
        measurements = entry.get("measurements") or {}
        return sorted(
            slot
            for slot, decision in decisions.items()
            if decision in {"socketed", "partial_socketed"}
            and (measurements.get(slot) or {}).get("applied") is not True
        )


def socket_reviewed_slots(engine: Any) -> list[str]:
    """Read historical review scope only; callers must still check current-state freshness."""
    with _SOCKET_DECISION_LOCK:
        try:
            states = _SOCKET_BATCH_DECISIONS.get(engine) or {}
            pending = _SOCKET_ITEM_DECISIONS.get(engine) or {}
        except TypeError:
            return []
        return sorted(
            set(pending)
            | {slot for entry in states.values() for slot in (entry.get("decisions") or {})}
        )


def _socket_decision_evidence_valid(decision: str, evidence: dict[str, Any]) -> bool:
    if decision in {"failed", "measurement_error", "capability_gap"}:
        return True  # Negative evidence can block, but can never authorize completion.
    expected_status = {
        "no_positive": "no_positive",
        "not_applicable": "not_applicable",
        "socketed": "positive",
        "partial_socketed": "positive",
        "partial_no_positive": "positive",
    }.get(decision)
    return bool(
        expected_status
        and evidence.get("measurementComplete") is True
        and evidence.get("measurementStatus") == expected_status
        and (decision != "partial_no_positive" or evidence.get("applied") is True)
    )


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
        blocked_decisions = {"failed", "measurement_error", "capability_gap"}
        input_decisions = socket_batch_decisions_for_state(engine, input_state_hash)
        output_decisions = socket_batch_decisions_for_state(engine, output_state_hash)
        if (
            input_decisions.get(canonical) in blocked_decisions
            or output_decisions.get(canonical) in blocked_decisions
        ):
            return None
        pending_by_slot = (_SOCKET_ITEM_DECISIONS.get(engine) or {}).get(canonical) or {}
        pending = pending_by_slot.get(str(item_fingerprint))
        if (
            not isinstance(pending, dict)
            or pending.get("reviewPolicyVersion") != _SOCKET_REVIEW_POLICY_VERSION
        ):
            return None
        if (
            pending.get("measurementComplete") is not True
            or pending.get("measurementStatus") != "positive"
        ):
            return None
        source_state_hash = str(pending.get("sourceStateHash") or "")
        if input_state_hash == source_state_hash:
            accumulated: dict[str, str] = {}
            measurements: dict[str, Any] = {}
        else:
            lineage = (_SOCKET_CARRY_STATES.get(engine) or {}).get(input_state_hash)
            if (
                not isinstance(lineage, dict)
                or lineage.get("sourceStateHash") != source_state_hash
                or lineage.get("reviewPolicyVersion") != _SOCKET_REVIEW_POLICY_VERSION
            ):
                return None
            accumulated = dict(lineage.get("decisions") or {})
            measurements = deepcopy(lineage.get("measurements") or {})
        decision = str(pending.get("decision") or "")
        if decision not in {"socketed", "partial_socketed"}:
            return None
        if decision == "partial_socketed":
            decision = "partial_no_positive"
        states = _SOCKET_BATCH_DECISIONS.setdefault(engine, {})
        existing_measurements = (states.get(output_state_hash) or {}).get("measurements") or {}
        # Exact output-state observations remain valid, including failures in other slots.
        accumulated.update(output_decisions)
        measurements.update(
            {
                known_slot: deepcopy(existing_measurements.get(known_slot) or {})
                for known_slot in output_decisions
            }
        )
        accumulated[canonical] = decision
        measurements[canonical] = {
            "measurementStatus": "positive",
            "measurementComplete": True,
            "applied": True,
        }
        states[output_state_hash] = {
            "reviewPolicyVersion": _SOCKET_REVIEW_POLICY_VERSION,
            "decisions": dict(accumulated),
            "measurements": measurements,
        }
        while len(states) > _SOCKET_DECISION_LIMIT_PER_ENGINE:
            states.pop(next(iter(states)))
        carry_states = _SOCKET_CARRY_STATES.setdefault(engine, {})
        carry_states[output_state_hash] = {
            "sourceStateHash": source_state_hash,
            "decisions": dict(accumulated),
            "reviewPolicyVersion": _SOCKET_REVIEW_POLICY_VERSION,
            "measurements": deepcopy(measurements),
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
        seen = any(
            canonical in (values.get("decisions") or values) for values in state_decisions.values()
        ) or bool(item_decisions.get(canonical))
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
    lock = engine.transaction_lock() if hasattr(engine, "transaction_lock") else nullcontext()
    with lock:
        if getattr(engine, "_poe2_mutation_batch_recovery_required", False):
            _clear_socket_decisions(engine)
            return {
                "ok": False,
                "errorCode": "build_state_recovery_required",
                "recoveryRequired": True,
            }
        return _plan_item_sockets_batch_locked(
            engine,
            slot_socket_counts=slot_socket_counts,
            goals=goals,
            elemental_resist_target=elemental_resist_target,
            chaos_resist_target=chaos_resist_target,
        )


def _plan_item_sockets_batch_locked(
    engine: PobEngine,
    *,
    slot_socket_counts: dict[str, int],
    goals: dict[str, float],
    elemental_resist_target: int | None = None,
    chaos_resist_target: int | None = None,
) -> dict[str, Any]:

    if not slot_socket_counts or len(slot_socket_counts) > 8:
        return {"ok": False, "errorCode": "socket_batch_scope_invalid"}
    snapshot = engine.get_xml()
    snapshot_hash = build_state_hash(snapshot)
    snapshot_selection = item_search.capture_selection(engine)
    quota_ledger = socket_limits.prepare(snapshot)
    results: list[dict[str, Any]] = []
    decisions: dict[str, str] = {}
    try:
        for index, (raw_slot, count) in enumerate(slot_socket_counts.items()):
            check_compute_budget()
            report_compute_progress("socket_slots", index, len(slot_socket_counts))
            slot = itemopt._canonical_slot(str(raw_slot))
            result = optimize_item_sockets(
                engine,
                slot=slot,
                goals=goals,
                socket_count=int(count),
                elemental_resist_target=elemental_resist_target,
                chaos_resist_target=chaos_resist_target,
                _publish_final=False,
                _quota_ledger=quota_ledger,
            )
            if (
                build_state_hash(engine.get_xml()) != snapshot_hash
                or not item_search.selection_matches(engine, snapshot_selection)
                or result.get("recoveryRequired")
            ):
                _clear_socket_decisions(engine)
                setattr(engine, "_poe2_mutation_batch_recovery_required", True)
                return {
                    "ok": False,
                    "errorCode": "socket_batch_state_changed",
                    "recoveryRequired": True,
                    "results": results,
                    "decisions": {},
                    "readOnly": False,
                }
            # Injected legacy implementations still use the same observation publisher.
            if "decision" not in result:
                with publication_guard(final=False):
                    result = _record_socket_result(engine, snapshot_hash, slot, result)
            decisions[slot] = result["decision"]
            results.append(result)
        with publication_guard():
            return {
                "ok": all(result.get("ok") for result in results),
                "stateHash": snapshot_hash,
                "results": results,
                "decisions": decisions,
                "readOnly": True,
                "batchComplete": True,
                "reviewPolicyVersion": _SOCKET_REVIEW_POLICY_VERSION,
            }
    except ComputeStopped as exc:
        # Completed child slots retain their exact evidence; the batch never becomes complete.
        exc.partial_result = {
            "ok": False,
            "errorCode": exc.reason,
            "stopReason": exc.reason,
            "partial": True,
            "batchComplete": False,
            "stateHash": snapshot_hash,
            "completedSlots": list(decisions),
            "results": results,
            "decisions": decisions,
            "readOnly": True,
            "rolledBack": True,
            "recoveryRequired": False,
        }
        raise
