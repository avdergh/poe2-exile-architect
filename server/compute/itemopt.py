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

from copy import deepcopy
import hashlib
import json
import re
import threading
from typing import Any, Literal
from weakref import WeakKeyDictionary
import xml.etree.ElementTree as ET

from ..knowledge import db, item_legality, itemparse
from ..judge import hard_legality
from ..runtime import craft_receipts
from . import attainability, pob_structure
from .engine import PobEngine
from .state import build_state_hash, canonical_payload_hash

_RANGE = re.compile(r"\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)")
_RES_KEYS = ("fire", "cold", "lightning")
_CHAOS_RESIST_RE = re.compile(r"chaos resistance", re.IGNORECASE)
_ALL_ELEMENTAL_RESIST_RE = re.compile(r"all elemental resistances", re.IGNORECASE)
_ELEMENT_RESIST_RE = {
    element: re.compile(rf"\b{element} resistance\b", re.IGNORECASE) for element in _RES_KEYS
}
GearStage = Literal["auto", "campaign", "maps_entry", "endgame"]

_JEWEL_DECISION_LOCK = threading.RLock()
_JEWEL_DECISIONS: WeakKeyDictionary[Any, dict[str, dict[str, Any]]] = WeakKeyDictionary()
_JEWEL_APPLY_DECISIONS: WeakKeyDictionary[Any, dict[str, dict[str, Any]]] = WeakKeyDictionary()
_JEWEL_DECISION_LIMIT_PER_ENGINE = 64
_JEWEL_REVIEW_POLICY_VERSION = "jewel_socket_review_v2"
_JEWEL_REVIEW_SCOPE = "selected_candidate_x_reachable_sockets_with_current_safe_leaves"


def next_jewel_decision_for_state(engine: Any, state_hash: str) -> dict[str, Any] | None:
    with _JEWEL_DECISION_LOCK:
        value = (_JEWEL_DECISIONS.get(engine) or {}).get(state_hash)
        return deepcopy(value) if value is not None else None


def next_jewel_decision_freshness(engine: Any, state_hash: str) -> str:
    with _JEWEL_DECISION_LOCK:
        try:
            decisions = _JEWEL_DECISIONS.get(engine) or {}
        except TypeError:
            return "missing"
        if state_hash in decisions:
            return "current"
        return "stale" if decisions else "missing"


def _record_next_jewel_decision(
    engine: Any,
    state_hash: str,
    decision: dict[str, Any],
) -> None:
    with _JEWEL_DECISION_LOCK:
        engine_decisions = _JEWEL_DECISIONS.setdefault(engine, {})
        engine_decisions[state_hash] = deepcopy(decision)
        while len(engine_decisions) > _JEWEL_DECISION_LIMIT_PER_ENGINE:
            engine_decisions.pop(next(iter(engine_decisions)))


def _record_jewel_apply_decision(engine: Any, payload: dict[str, Any]) -> str:
    stable = {
        "reviewPolicyVersion": payload["reviewPolicyVersion"],
        "stateHash": payload["stateHash"],
        "candidateJewelFingerprint": payload["candidateJewelFingerprint"],
        "goalsFingerprint": payload["goalsFingerprint"],
        "protectedNodeIds": payload["protectedNodeIds"],
        "socket": payload["socket"],
        "pathPointCost": payload["pathPointCost"],
        "nodesToRemove": payload["nodesToRemove"],
    }
    decision_ref = (
        "jewel-decision:"
        + hashlib.sha256(
            json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
    )
    with _JEWEL_DECISION_LOCK:
        decisions = _JEWEL_APPLY_DECISIONS.setdefault(engine, {})
        decisions[decision_ref] = deepcopy(payload)
        while len(decisions) > _JEWEL_DECISION_LIMIT_PER_ENGINE:
            decisions.pop(next(iter(decisions)))
    return decision_ref


def _jewel_recovery_required(engine: Any) -> bool:
    return bool(getattr(engine, "_poe2_mutation_batch_recovery_required", False))


def _passive_allocated(engine: Any, node_id: int) -> bool:
    value = engine.get_passive(int(node_id))
    if not isinstance(value, dict) or value.get("found") is False:
        return False
    node = value.get("node") if isinstance(value.get("node"), dict) else value
    return bool(node.get("alloc")) if isinstance(node, dict) else False


def _whole_build_legality(engine: Any, xml: str) -> dict[str, Any]:
    return hard_legality.audit_build(
        hard_legality.augment_build_with_snapshot_gear(engine.get_build(), xml)
    )


def apply_next_jewel_socket_decision(
    engine: PobEngine,
    *,
    decision_ref: str,
    expected_state_hash: str,
) -> dict[str, Any]:
    """Atomically apply one previously measured positive jewel-socket decision."""

    if _jewel_recovery_required(engine):
        return {
            "ok": False,
            "errorCode": "build_state_recovery_required",
            "recoveryRequired": True,
        }
    with engine.transaction_lock():
        snapshot = engine.get_xml()
        state_hash = build_state_hash(snapshot)
        if state_hash != expected_state_hash:
            return {
                "ok": False,
                "errorCode": "build_state_conflict",
                "expectedStateHash": expected_state_hash,
                "actualStateHash": state_hash,
            }
        with _JEWEL_DECISION_LOCK:
            decision = deepcopy((_JEWEL_APPLY_DECISIONS.get(engine) or {}).get(decision_ref))
        if not isinstance(decision, dict):
            return {"ok": False, "errorCode": "jewel_socket_decision_not_found"}
        if decision.get("stateHash") != state_hash:
            return {"ok": False, "errorCode": "jewel_socket_decision_stale"}
        if decision.get("positiveNetBenefit") is not True:
            return {"ok": False, "errorCode": "jewel_socket_decision_not_positive"}
        if not str(decision.get("candidateJewelFingerprint") or ""):
            return {"ok": False, "errorCode": "jewel_socket_decision_fingerprint_missing"}
        if decision.get("protectionDeclared") is not True:
            return {"ok": False, "errorCode": "jewel_protection_not_declared"}
        before_legality = _whole_build_legality(engine, snapshot)
        try:
            for node_id in decision.get("nodesToRemove") or []:
                removed = engine.dealloc_passive(int(node_id))
                if not isinstance(removed, dict) or not removed.get("ok"):
                    raise ValueError("jewel_reallocation_failed")
            allocated = engine.alloc_passive(int(decision["socket"]))
            if (
                not isinstance(allocated, dict)
                or not allocated.get("ok")
                or allocated.get("warning")
            ):
                raise ValueError("jewel_socket_path_allocation_failed")
            equipped = engine.equip_jewel(
                str(decision["raw"]),
                socket=int(decision["socket"]),
            )
            if not isinstance(equipped, dict) or not equipped.get("ok"):
                raise ValueError("candidate_jewel_equip_failed")
            output_state_hash = build_state_hash(engine.get_xml())
            if output_state_hash == state_hash:
                raise ValueError("jewel_socket_decision_not_applied")
            if not _passive_allocated(engine, int(decision["socket"])):
                raise ValueError("jewel_socket_readback_mismatch")
            if any(
                _passive_allocated(engine, int(node_id))
                for node_id in decision.get("nodesToRemove") or []
            ):
                raise ValueError("jewel_reallocation_readback_mismatch")
            if any(
                not _passive_allocated(engine, int(node_id))
                for node_id in decision.get("protectedNodeIds") or []
            ):
                raise ValueError("protected_passive_regression")
            try:
                root = ET.fromstring(engine.get_xml())
            except (ET.ParseError, TypeError, ValueError) as exc:
                raise ValueError("jewel_socket_readback_mismatch") from exc
            assignments = pob_structure.active_spec_passive_jewels(root)
            expected_assignment = (
                str(decision["socket"]),
                str(decision["candidateJewelFingerprint"]),
            )
            if assignments is None or expected_assignment not in assignments:
                raise ValueError("jewel_socket_readback_mismatch")
            after_legality = _whole_build_legality(engine, engine.get_xml())
            legality_regression = hard_legality.compare_audits_for_regression(
                before_legality,
                after_legality,
            )
            if legality_regression.get("reasons"):
                raise ValueError("jewel_socket_legality_regression")
        except Exception as exc:  # noqa: BLE001 - restore first, return stable error only.
            restored = _restore_jewel_state(engine, snapshot, state_hash)
            setattr(engine, "_poe2_mutation_batch_recovery_required", not restored)
            return {
                "ok": False,
                "errorCode": str(exc)
                if isinstance(exc, ValueError)
                else "jewel_socket_apply_failed",
                "rolledBack": restored,
                "recoveryRequired": not restored,
            }
        applied = {
            "status": "applied",
            "reviewPolicyVersion": _JEWEL_REVIEW_POLICY_VERSION,
            "reviewScope": _JEWEL_REVIEW_SCOPE,
            "roundIndex": decision.get("roundIndex"),
            "socket": int(decision["socket"]),
            "positiveNetBenefit": True,
            "decisionRef": decision_ref,
            "candidateJewelFingerprint": decision["candidateJewelFingerprint"],
            "goalsFingerprint": decision["goalsFingerprint"],
            "reviewContextFingerprint": decision["reviewContextFingerprint"],
            "protectionDeclared": decision["protectionDeclared"],
            "protectedNodeIds": list(decision["protectedNodeIds"]),
            "reviewRequired": True,
            "inputStateHash": state_hash,
            "stateHash": output_state_hash,
        }
        _record_next_jewel_decision(engine, output_state_hash, applied)
        setattr(engine, "_poe2_mutation_batch_recovery_required", False)
        return {
            "ok": True,
            **applied,
            "outputStateHash": output_state_hash,
            "rolledBack": False,
        }


def _restore_jewel_state(engine: Any, xml: str, state_hash: str) -> bool:
    try:
        engine.load_build_xml(xml, name="jewel-socket-decision-rollback")
        return build_state_hash(engine.get_xml()) == state_hash
    except Exception:  # noqa: BLE001
        return False


def gear_stage_profile(
    level: int | float | None,
    *,
    stage: GearStage = "auto",
    chaos_resist_target: int | None = None,
    elemental_resist_target: int | None = None,
) -> dict[str, Any]:
    """Return stage-aware gear goals without treating pinnacle defenses as a universal baseline."""
    if stage not in {"auto", "campaign", "maps_entry", "endgame"}:
        raise ValueError("stage must be auto, campaign, maps_entry, or endgame")
    resolved = stage
    if resolved == "auto":
        lvl = int(level or 0)
        resolved = "campaign" if lvl < 70 else "maps_entry" if lvl < 80 else "endgame"
    profiles = {
        "campaign": {
            "defenseWeight": 0.65,
            "chaosResistTarget": 0,
            "elementalResistTarget": 30,
        },
        "maps_entry": {
            "defenseWeight": 0.72,
            "chaosResistTarget": 30,
            "elementalResistTarget": 50,
        },
        "endgame": {
            "defenseWeight": 0.78,
            "chaosResistTarget": 30,
            "elementalResistTarget": 60,
        },
    }
    profile = dict(profiles[resolved])
    if chaos_resist_target is not None:
        profile["chaosResistTarget"] = max(-60, min(75, int(chaos_resist_target)))
    if elemental_resist_target is not None:
        profile["elementalResistTarget"] = max(-60, min(75, int(elemental_resist_target)))
    profile["stage"] = resolved
    return profile


def _without_unneeded_chaos_resistance(
    mods: list[dict[str, Any]], *, current_chaos: float, target_chaos: int
) -> list[dict[str, Any]]:
    if current_chaos < target_chaos:
        return mods
    return [mod for mod in mods if not _CHAOS_RESIST_RE.search(str(mod.get("text") or ""))]


def _without_satisfied_resistances(
    mods: list[dict[str, Any]],
    *,
    current: dict[str, Any],
    elemental_target: int,
    chaos_target: int,
) -> list[dict[str, Any]]:
    """Stop buying ordinary resistance affixes after the configured stage target is met."""

    output: list[dict[str, Any]] = []
    elemental_met = {
        element: float(current.get(element) or 0) >= elemental_target for element in _RES_KEYS
    }
    for mod in mods:
        text = str(mod.get("text") or "")
        lowered = text.casefold()
        if "maximum" in lowered:
            output.append(mod)
            continue
        if _CHAOS_RESIST_RE.search(text) and float(current.get("chaos") or 0) >= chaos_target:
            continue
        if _ALL_ELEMENTAL_RESIST_RE.search(text) and all(elemental_met.values()):
            continue
        if any(
            elemental_met[element] and pattern.search(text)
            for element, pattern in _ELEMENT_RESIST_RE.items()
        ):
            continue
        output.append(mod)
    return output


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


def _generated_belt_charm_slots(base: str, *, ilvl: int | None) -> int | None:
    item = db.get_item(base)
    if not isinstance(item, dict) or item.get("item_class") != "Belt":
        return None
    level = int(ilvl or 1)
    return 1 if level < 70 else 2 if level < 80 else 3


def _generated_item_property_lines(base: str, *, ilvl: int | None) -> list[str]:
    """Materialize variable item properties that PoB cannot infer from the base placeholder."""

    charm_slots = _generated_belt_charm_slots(base, ilvl=ilvl)
    if charm_slots is None:
        return []
    return [f"Charm Slots: {charm_slots}"]


def _generated_item_implicit_lines(base: str, *, ilvl: int | None) -> list[str]:
    charm_slots = _generated_belt_charm_slots(base, ilvl=ilvl)
    if charm_slots is None:
        return []
    noun = "Slot" if charm_slots == 1 else "Slots"
    return [f"Has {charm_slots} Charm {noun}"]


def _generated_item_radius_line(base: str) -> str:
    item = db.get_item(base)
    if isinstance(item, dict) and "radius_jewel" in set(item.get("tags") or []):
        return "Radius: Small\n"
    return ""


def _craft_profile(base: str) -> dict[str, Any]:
    return db.craft_profile(base) or {
        "domain": "item",
        "rarity": "Rare",
        "prefixLimit": 3,
        "suffixLimit": 3,
    }


def _is_life_or_mana_flask_base(base: str) -> bool:
    item = db.get_item(base)
    return isinstance(item, dict) and item.get("item_class") in {"LifeFlask", "ManaFlask"}


def _item_text(
    base: str,
    lines: list[str],
    slot: str,
    *,
    ilvl: int | None = None,
    profile: dict[str, Any] | None = None,
) -> str:
    profile = profile or _craft_profile(base)
    body = "\n".join(lines)
    level_line = f"Item Level: {int(ilvl)}\n" if ilvl is not None else ""
    radius_line = _generated_item_radius_line(base)
    property_lines = _generated_item_property_lines(base, ilvl=ilvl)
    property_text = "".join(f"{line}\n" for line in property_lines)
    implicit_lines = _generated_item_implicit_lines(base, ilvl=ilvl)
    implicit_text = (
        f"Implicits: {len(implicit_lines)}\n" + "\n".join(implicit_lines) + "\n"
        if implicit_lines
        else "--------\n"
    )
    rarity = str(profile.get("rarity") or "Rare")
    header = (
        f"Rarity: Magic\n{base}\n"
        if rarity.casefold() == "magic"
        else f"Rarity: Rare\nOptimized {slot}\n{base}\n"
    )
    return f"{header}{level_line}{radius_line}{property_text}{implicit_text}{body}"


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


def _explicit_item_lines(raw: str) -> list[str]:
    structure = itemparse.semantic_item_structure(raw)
    return [
        str(effect.get("text"))
        for effect in structure.get("effects", [])
        if isinstance(effect, dict) and effect.get("kind") == "explicit" and effect.get("text")
    ]


def _craft_summary(
    chosen: list[dict[str, Any]], prefix_pool: int, suffix_pool: int
) -> dict[str, Any]:
    """A coarse craft-effort / attainability estimate (NOT a market price).

    The data has no usable spawn-weights (all 1), so 'effort' is inferred from how many specific
    affixes the craft needs, how many are a TOP tier of several (rarer rolls), and the item level
    required — a rough realism check, not a probability or a divine cost.
    """
    n = len(chosen)
    deep = sum(
        1
        for c in chosen
        if int(c.get("tier") or 1) == 1 and int(c.get("totalTiers") or c.get("tiers") or 1) >= 4
    )
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


def _affix_candidates_for_policy(
    source: dict[str, Any],
    *,
    rolls: str,
    policy: attainability.GearAttainabilityPolicy,
) -> list[dict[str, Any]]:
    """Return the top tier plus the first real lower tier needed by a realistic policy."""

    options = [dict(value) for value in source.get("tier_options") or [] if isinstance(value, dict)]
    if not options:
        options = [dict(source)]
    total = int(source.get("totalTiers") or source.get("tiers") or len(options) or 1)
    selected = [options[0]]
    deep_top = int(options[0].get("tier") or 1) == 1 and total >= 4
    if policy.maxDeepTopTierAffixes is not None and deep_top:
        lower = next((value for value in options if int(value.get("tier") or 1) > 1), None)
        if lower is not None:
            selected.append(lower)
    return [
        {
            "group": str(source.get("group") or value.get("group") or ""),
            "line": _roll(str(value.get("text") or source.get("text") or ""), rolls),
            "type": str(source.get("type") or value.get("type") or ""),
            "tiers": total,
            "totalTiers": total,
            "tier": int(value.get("tier") or 1),
            "ilvl": int(value.get("required_level") or source.get("required_level") or 0),
            "_deepTopTier": int(value.get("tier") or 1) == 1 and total >= 4,
        }
        for value in selected
    ]


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
    elemental_resist_target: int | None = None,
    chaos_resist_target: int | None = None,
    acquisition_profile: str = "realistic_trade",
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
    try:
        acquisition_policy = attainability.policy_for(acquisition_profile)
    except ValueError:
        return {"ok": False, "errorCode": "invalid_acquisition_profile"}
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

    base_profile = _craft_profile(base)
    if str(base_profile.get("domain") or "") == "flask":
        if _is_life_or_mana_flask_base(base):
            return {
                "ok": False,
                "errorCode": "use_optimize_flask",
                "error": "Life/Mana Flask bases use Magic 1/1 crafting; call optimize_flask.",
                "slot": slot,
                "base": base,
            }
        return {
            "ok": False,
            "errorCode": "unsupported_flask_item_class",
            "error": "This Flask-domain base is not a Life or Mana Flask and is not supported by optimize_item.",
            "slot": slot,
            "base": base,
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
    profile = gear_stage_profile(
        build.get("level"),
        stage="auto",
        elemental_resist_target=elemental_resist_target,
        chaos_resist_target=chaos_resist_target,
    )
    resistance_snapshot = engine.get_xml()
    can_probe_without_slot = callable(getattr(engine, "unequip_item", None))
    try:
        if can_probe_without_slot and isinstance(gear.get(slot), dict):
            engine.unequip_item(slot)
        current_resists = engine.get_defenses().get("resistances") or {}
    finally:
        if can_probe_without_slot:
            try:
                engine.load_build_xml(resistance_snapshot, name="item-resistance-target-restore")
            except TypeError:
                engine.load_build_xml(resistance_snapshot)
    pool["prefixes"] = _without_satisfied_resistances(
        list(pool["prefixes"]),
        current=current_resists,
        elemental_target=int(profile["elementalResistTarget"]),
        chaos_target=int(profile["chaosResistTarget"]),
    )
    pool["suffixes"] = _without_satisfied_resistances(
        list(pool["suffixes"]),
        current=current_resists,
        elemental_target=int(profile["elementalResistTarget"]),
        chaos_target=int(profile["chaosResistTarget"]),
    )
    prefix_family_count = len(pool["prefixes"])
    suffix_family_count = len(pool["suffixes"])
    pre = [
        candidate
        for source in pool["prefixes"]
        for candidate in _affix_candidates_for_policy(
            source,
            rolls=rolls,
            policy=acquisition_policy,
        )
    ]
    suf = [
        candidate
        for source in pool["suffixes"]
        for candidate in _affix_candidates_for_policy(
            source,
            rolls=rolls,
            policy=acquisition_policy,
        )
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
        while (len(chosen_pre) < 3 or len(chosen_suf) < 3) and len(chosen_pre) + len(
            chosen_suf
        ) < acquisition_policy.maxExplicitAffixes:
            opts: list[dict[str, str]] = []
            if len(chosen_pre) < 3:
                opts += [c for c in pre if c["group"] not in used]
            if len(chosen_suf) < 3:
                opts += [c for c in suf if c["group"] not in used]
            if acquisition_policy.maxDeepTopTierAffixes is not None:
                deep_count = sum(bool(item.get("_deepTopTier")) for item in chosen_pre + chosen_suf)
                if deep_count >= acquisition_policy.maxDeepTopTierAffixes:
                    opts = [item for item in opts if not item.get("_deepTopTier")]
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
                        if acquisition_policy.maxDeepTopTierAffixes is not None:
                            existing_deep = sum(
                                bool(item.get("_deepTopTier"))
                                for item in rest + (chosen_suf if poolside is pre else chosen_pre)
                            )
                            if existing_deep >= acquisition_policy.maxDeepTopTierAffixes:
                                swaps = [item for item in swaps if not item.get("_deepTopTier")]
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
            {
                "affix": c["line"],
                "ilvl": c.get("ilvl", 0),
                "tier": c.get("tier", 1),
                "totalTiers": c.get("totalTiers", c.get("tiers", 1)),
                "tiers": c.get("totalTiers", c.get("tiers", 1)),
            }
            for c in chosen
        ],
        "craft": _craft_summary(chosen, prefix_family_count, suffix_family_count),
        "acquisitionProfile": acquisition_profile,
        "attainabilityPolicy": attainability.public_policy(acquisition_profile),
        "warnings": warnings,
        "note": (
            f"{('Realistic trade target' if acquisition_profile == 'realistic_trade' else 'Theoretical best-in-slot')} "
            f"for {goal_desc} ({rolls} rolls) from this base's real mod "
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


_FLASK_STRATEGY_GROUPS = {
    "recovery": {
        "prefix": ("FlaskRecoverySpeed", "FlaskRecoveryAmount", "FlaskBuffWhileHealing"),
        "suffix": ("FlaskRechargeRate", "FlaskNumCharges", "FlaskChargesUsed", "FlaskGainCharge"),
    },
    "sustain": {
        "prefix": ("FlaskRecoveryAmount", "FlaskRecoverySpeed", "FlaskBuffWhileHealing"),
        "suffix": ("FlaskGainCharge", "FlaskChargesUsed", "FlaskNumCharges", "FlaskRechargeRate"),
    },
    "instant": {
        "prefix": ("FlaskBuffWhileHealing", "FlaskRecoveryAmount", "FlaskRecoverySpeed"),
        "suffix": ("FlaskChargesUsed", "FlaskGainCharge", "FlaskNumCharges", "FlaskRechargeRate"),
    },
}


def _pick_flask_affix(
    candidates: list[dict[str, Any]], priorities: tuple[str, ...]
) -> dict[str, Any] | None:
    for group in priorities:
        matches = [item for item in candidates if str(item.get("group") or "") == group]
        if matches:
            return max(matches, key=lambda item: int(item.get("required_level") or 0))
    return max(candidates, key=lambda item: int(item.get("required_level") or 0), default=None)


def optimize_flask(
    engine: PobEngine,
    slot: str,
    *,
    base: str | None = None,
    ilvl: int = 82,
    rolls: str = "realistic",
    strategy: Literal["recovery", "sustain", "instant"] = "recovery",
) -> dict[str, Any]:
    """Build one legal Magic life/mana Flask using the shared corpus and legality pipeline."""

    slot = _canonical_slot(slot)
    if slot not in {"Flask 1", "Flask 2"}:
        return {"ok": False, "errorCode": "invalid_flask_slot", "slot": slot}
    if strategy not in _FLASK_STRATEGY_GROUPS:
        return {"ok": False, "errorCode": "invalid_flask_strategy", "strategy": strategy}
    build = engine.get_build()
    gear = build.get("gear") if isinstance(build.get("gear"), dict) else {}
    if not base:
        current = gear.get(slot) if isinstance(gear, dict) else None
        base = current.get("base") if isinstance(current, dict) else None
    profile = _craft_profile(str(base or ""))
    if (
        not base
        or str(profile.get("domain") or "") != "flask"
        or not _is_life_or_mana_flask_base(base)
    ):
        return {
            "ok": False,
            "errorCode": "invalid_flask_base",
            "slot": slot,
            "base": base,
        }

    pool = db.affix_pool(base, ilvl=ilvl)
    priorities = _FLASK_STRATEGY_GROUPS[strategy]
    prefix = _pick_flask_affix(list(pool["prefixes"]), priorities["prefix"])
    suffix = _pick_flask_affix(list(pool["suffixes"]), priorities["suffix"])
    chosen = [item for item in (prefix, suffix) if item is not None]
    if not chosen:
        return {
            "ok": False,
            "errorCode": "flask_affix_pool_empty",
            "slot": slot,
            "base": base,
        }
    lines = [_roll(str(item["text"]), rolls) for item in chosen]
    raw = _item_text(base, lines, slot, ilvl=ilvl, profile=profile)
    legality = _generated_item_legality(raw)
    if not legality.get("ok"):
        return {
            "ok": False,
            "errorCode": "generated_item_legality_check_failed",
            "slot": slot,
            "base": base,
            "legalityCheck": legality,
        }

    snapshot = engine.get_xml()
    before_slots = _equipped_slots(build)
    before_audit = hard_legality.audit_build(
        hard_legality.augment_build_with_snapshot_gear(build, snapshot)
    )
    try:
        add_result = engine.add_item(raw, slot=slot)
        if not isinstance(add_result, dict) or not add_result.get("ok"):
            return {
                "ok": False,
                "errorCode": "optimized_item_equip_failed",
                "slot": slot,
                "base": base,
            }
        candidate_xml = engine.get_xml()
        candidate_build = engine.get_build()
        after_slots = _equipped_slots(candidate_build)
        missing_slots = sorted(before_slots - after_slots)
        after_audit = hard_legality.audit_build(
            hard_legality.augment_build_with_snapshot_gear(
                candidate_build,
                candidate_xml,
                item_legality_overrides={slot: legality},
            )
        )
        regression = hard_legality.compare_audits_for_regression(before_audit, after_audit)
        if missing_slots or regression["regressed"]:
            return {
                "ok": False,
                "errorCode": "whole_build_legality_check_failed",
                "slot": slot,
                "base": base,
                "slotRegression": {"missingSlots": missing_slots},
                "wholeBuildLegality": after_audit,
                "legalityRegression": regression,
            }
    finally:
        engine.load_build_xml(snapshot)

    return {
        "ok": True,
        "slot": slot,
        "base": base,
        "itemLevel": ilvl,
        "strategy": strategy,
        "item": raw,
        "affixes": lines,
        "affixGroups": [str(item.get("group") or "") for item in chosen],
        "attainability": [
            {
                "affix": line,
                "ilvl": int(item.get("required_level") or 0),
                "tiers": int(item.get("tiers") or 1),
            }
            for item, line in zip(chosen, lines)
        ],
        "legalityCheck": legality,
        "wholeBuildLegality": after_audit,
        "legalityRegression": regression,
        "note": (
            "Magic Flask target from the current corpus flask domain. Family/rotation chooses "
            "the strategy; equip the returned item with equip_item."
        ),
    }


_CHARM_PREFIX_STRATEGIES = {
    "guard": ("FlaskRecoveryAmount",),
    "recovery": ("FlaskRecoveryAmount",),
    "duration": ("FlaskRecoverySpeed",),
}
_CHARM_SUFFIX_STRATEGIES = {
    "charges": ("FlaskGainCharge", "FlaskChargesUsed", "FlaskNumCharges", "FlaskRechargeRate"),
    "ailment": (
        "FlaskBleedingAndCorruptedBloodImmunityDuringEffect",
        "FlaskFreezeAndChillImmunityDuringEffect",
        "FlaskIgniteImmunityDuringEffect",
        "FlaskPoisonImmunityDuringEffect",
        "FlaskShockImmunityDuringEffect",
    ),
}


def optimize_charm(
    engine: PobEngine,
    slot: str,
    *,
    base: str,
    ilvl: int = 82,
    rolls: str = "realistic",
    prefix_strategy: Literal["guard", "recovery", "duration"] = "guard",
    suffix_strategy: Literal["charges", "ailment"] = "charges",
) -> dict[str, Any]:
    """Create one legal Magic Charm with a focused prefix and suffix."""

    slot = _canonical_slot(slot)
    if slot not in {"Charm 1", "Charm 2", "Charm 3"}:
        return {"ok": False, "errorCode": "invalid_charm_slot", "slot": slot}
    item = db.get_item(base)
    if (
        not isinstance(item, dict)
        or item.get("item_class") != "UtilityFlask"
        or "Charm" not in base
    ):
        return {"ok": False, "errorCode": "invalid_charm_base", "base": base}
    if prefix_strategy not in _CHARM_PREFIX_STRATEGIES:
        return {"ok": False, "errorCode": "invalid_charm_prefix_strategy"}
    if suffix_strategy not in _CHARM_SUFFIX_STRATEGIES:
        return {"ok": False, "errorCode": "invalid_charm_suffix_strategy"}
    pool = db.affix_pool(base, ilvl=ilvl)
    prefixes = list(pool.get("prefixes") or [])
    suffixes = list(pool.get("suffixes") or [])
    prefix = _pick_flask_affix(prefixes, _CHARM_PREFIX_STRATEGIES[prefix_strategy])
    if prefix_strategy == "guard":
        guard = [entry for entry in prefixes if "Guard" in str(entry.get("text") or "")]
        if guard:
            prefix = max(guard, key=lambda entry: int(entry.get("required_level") or 0))
    suffix = _pick_flask_affix(suffixes, _CHARM_SUFFIX_STRATEGIES[suffix_strategy])
    chosen = [entry for entry in (prefix, suffix) if entry is not None]
    if len(chosen) < 2:
        return {"ok": False, "errorCode": "charm_affix_pool_incomplete", "base": base}
    lines = [_roll(str(entry["text"]), rolls) for entry in chosen]
    profile = _craft_profile(base)
    raw = _item_text(base, lines, slot, ilvl=ilvl, profile=profile)
    legality = _generated_item_legality(raw)
    if not legality.get("ok"):
        return {
            "ok": False,
            "errorCode": "generated_item_legality_check_failed",
            "legalityCheck": legality,
        }
    snapshot = engine.get_xml()
    try:
        equipped = engine.add_item(raw, slot=slot)
        if not isinstance(equipped, dict) or not equipped.get("ok"):
            return {"ok": False, "errorCode": "optimized_item_equip_failed", "slot": slot}
    finally:
        engine.load_build_xml(snapshot)
    return {
        "ok": True,
        "slot": slot,
        "base": base,
        "itemLevel": ilvl,
        "item": raw,
        "affixes": lines,
        "prefixStrategy": prefix_strategy,
        "suffixStrategy": suffix_strategy,
        "legalityCheck": legality,
        "note": "Legal Magic Charm target; equip explicitly and re-run lifecycle/quality checks.",
    }


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
    acquisition_profile: str = "realistic_trade",
) -> dict[str, Any]:
    """Rank gear slots by how much recrafting each would gain — 'what should I upgrade next'.

    Recrafts each candidate slot independently (via optimize_item, single `metric` or weighted
    `goals`) to its best, measures the gain over the CURRENT item there, and ranks high→low.
    Read-only: every probe is snapshotted and restored. Gains are NOT additive — recrafting one slot
    shifts the others — so upgrade the top slot, then re-run. Empty slots with no base are skipped
    (optimize that slot directly with a `base` to explore them).
    """
    try:
        acquisition_policy = attainability.public_policy(acquisition_profile)
    except ValueError:
        return {"ok": False, "errorCode": "invalid_acquisition_profile"}
    candidate_slots = list(slots) if slots else list(_UPGRADE_SLOTS)
    ranked: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    rejected: list[dict[str, Any]] = []
    for slot in candidate_slots:
        r = optimize_item(
            engine,
            slot,
            metric=metric,
            goals=goals,
            rolls=rolls,
            keep_resists_capped=True,
            acquisition_profile=acquisition_profile,
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
        "acquisitionProfile": acquisition_profile,
        "attainabilityPolicy": acquisition_policy,
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
    selected_mod_ids: list[str] | None = None,
    item_level: int | None = None,
) -> dict[str, Any]:
    """Craft the best-in-slot rare JEWEL for the active build (marginal-ranked).

    Ordinary jewel modifiers are measured as custom modifiers on the real build and ranked by
    marginal gain. Radius/Time-Lost bases instead require Agent-selected exact modifier ids; this
    function validates and formats that static selection without pretending its effect is global.
    Every generated rare jewel carries an Item Level. Position radius candidates with
    evaluate_next_jewel_socket before equipping them.
    """
    bi = db.get_item(base)
    if not bi or "jewel" not in (bi.get("tags") or []):
        return {
            "ok": False,
            "error": f"'{base}' is not a jewel base — use Emerald/Ruby/Sapphire/Diamond.",
        }
    character_level = max(1, int(engine.get_build().get("level") or 1))
    ilvl = max(1, min(100, int(item_level if item_level is not None else character_level)))
    is_radius_jewel = "radius_jewel" in set(bi.get("tags") or [])
    if is_radius_jewel and selected_mod_ids is None:
        return {
            "ok": False,
            "errorCode": "radius_jewel_requires_agent_selection",
            "error": (
                "Radius/Time-Lost jewel modifiers are positional. Select exact current-corpus "
                "modifier ids, then evaluate the constructed jewel in every relevant tree socket."
            ),
            "base": base,
            "requiredTools": ["search_mods", "optimize_jewel", "evaluate_next_jewel_socket"],
            "stateChanged": False,
        }

    if selected_mod_ids is not None:
        requested_ids = [str(value).strip() for value in selected_mod_ids if str(value).strip()]
        if not requested_ids:
            return {
                "ok": False,
                "errorCode": "jewel_mod_not_found",
                "error": "selected_mod_ids must contain at least one exact modifier id",
                "stateChanged": False,
            }
        if len(requested_ids) != len(set(requested_ids)):
            return {
                "ok": False,
                "errorCode": "jewel_mod_group_conflict",
                "error": "selected_mod_ids must not repeat a modifier",
                "stateChanged": False,
            }
        selected_records = db.get_mods_by_ids(requested_ids)
        found_ids = {str(item["id"]) for item in selected_records}
        missing_ids = [value for value in requested_ids if value not in found_ids]
        if missing_ids:
            return {
                "ok": False,
                "errorCode": "jewel_mod_not_found",
                "error": "one or more selected modifier ids are absent from the current corpus",
                "missingModIds": missing_ids,
                "stateChanged": False,
            }
        unavailable = [
            str(item["id"])
            for item in selected_records
            if item.get("type") not in {"prefix", "suffix"}
            or not db.mod_tags_match_base(
                base,
                set(item.get("rolls_on") or []),
                mod_domain=str(item.get("domain") or ""),
            )
        ]
        if unavailable:
            return {
                "ok": False,
                "errorCode": "jewel_mod_not_available_for_base",
                "error": "one or more selected modifiers cannot roll on this jewel base",
                "unavailableModIds": unavailable,
                "stateChanged": False,
            }
        underlevelled = [
            str(item["id"])
            for item in selected_records
            if int(item.get("required_level") or 0) > ilvl
        ]
        if underlevelled:
            return {
                "ok": False,
                "errorCode": "jewel_mod_level_unavailable",
                "error": "one or more selected modifiers require a higher item level",
                "unavailableModIds": underlevelled,
                "itemLevel": ilvl,
                "stateChanged": False,
            }
        chosen: list[dict[str, Any]] = []
        used_groups: set[str] = set()
        for item in selected_records:
            groups = [str(value) for value in item.get("groups") or [] if str(value)]
            group = groups[0] if groups else str(item["id"])
            if group in used_groups:
                return {
                    "ok": False,
                    "errorCode": "jewel_mod_group_conflict",
                    "error": "selected modifiers contain mutually exclusive modifier groups",
                    "conflictingGroup": group,
                    "stateChanged": False,
                }
            used_groups.add(group)
            chosen.append(
                {
                    "id": str(item["id"]),
                    "line": _roll(str(item.get("text") or ""), rolls),
                    "group": group,
                    "type": str(item["type"]),
                    "tiers": 1,
                    "ilvl": int(item.get("required_level") or 0),
                }
            )
        profile = _craft_profile(base)
        prefix_count = sum(item["type"] == "prefix" for item in chosen)
        suffix_count = sum(item["type"] == "suffix" for item in chosen)
        if prefix_count > int(profile.get("prefixLimit") or 0) or suffix_count > int(
            profile.get("suffixLimit") or 0
        ):
            return {
                "ok": False,
                "errorCode": "jewel_affix_limit_exceeded",
                "error": "selected modifiers exceed this jewel base's prefix/suffix limit",
                "prefixCount": prefix_count,
                "suffixCount": suffix_count,
                "stateChanged": False,
            }
        selected_lines = [str(item["line"]) for item in chosen]
        selected_item = _item_text(base, selected_lines, "Jewel", ilvl=ilvl, profile=profile)
        legality = _generated_item_legality(selected_item)
        if not legality.get("ok"):
            return {
                "ok": False,
                "errorCode": "generated_jewel_legality_check_failed",
                "error": "the selected jewel modifiers failed the shared generated-item audit",
                "legalityCheck": legality,
                "stateChanged": False,
            }
        fingerprint = str(
            itemparse.semantic_item_structure(selected_item).get("itemFingerprint") or ""
        )
        return {
            "ok": True,
            "base": base,
            "itemLevel": ilvl,
            "item": selected_item,
            "itemFingerprint": fingerprint,
            "modIds": requested_ids,
            "affixes": selected_lines,
            "selectionMode": (
                "agent_selected_positional" if is_radius_jewel else "agent_selected_static"
            ),
            "requiresPositionalEvaluation": is_radius_jewel,
            "stateChanged": False,
            "legalityCheck": legality,
        }

    pool = db.affix_pool(base, ilvl=ilvl)
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

    item = _item_text(base, final_lines, "Jewel", ilvl=ilvl)
    legality = _generated_item_legality(item)
    if not legality.get("ok"):
        return {
            "ok": False,
            "errorCode": "generated_jewel_legality_check_failed",
            "error": "the optimized jewel failed the shared generated-item audit",
            "legalityCheck": legality,
            "stateChanged": False,
        }
    out: dict[str, Any] = {
        "ok": True,
        "base": base,
        "itemLevel": ilvl,
        "item": item,
        "itemFingerprint": str(
            itemparse.semantic_item_structure(item).get("itemFingerprint") or ""
        ),
        "affixes": final_lines,
        "attainability": [
            {"affix": c["line"], "ilvl": c["ilvl"], "tiers": c["tiers"]} for c in chosen
        ],
        "craft": _craft_summary(chosen, len(pre), len(suf)),
        "selectionMode": "automatic_global_marginal",
        "requiresPositionalEvaluation": False,
        "stateChanged": False,
        "legalityCheck": legality,
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
    elemental_resist_target: int,
    ilvl: int,
    acquisition_policy: attainability.GearAttainabilityPolicy,
) -> str | None:
    """Fast per-slot craft: rank each affix by its marginal weighted gain (TWO batched evals — bare
    base, then all single-affix candidates), then take the top 3 prefix + 3 suffix (group-exclusive).
    Approximate (ignores affix interaction) but ~6x cheaper than the full greedy — used by plan_gear
    so a whole-set plan fits in one call."""
    pool = db.affix_pool(base, ilvl=ilvl)
    current_resists = engine.get_defenses().get("resistances") or {}
    pre = _without_satisfied_resistances(
        pool["prefixes"],
        current=current_resists,
        elemental_target=elemental_resist_target,
        chaos_target=chaos_resist_target,
    )
    suf = _without_satisfied_resistances(
        pool["suffixes"],
        current=current_resists,
        elemental_target=elemental_resist_target,
        chaos_target=chaos_resist_target,
    )
    if not pre and not suf:
        return None
    keys = list(weights)
    meta: list[tuple[dict[str, Any], str]] = []
    for source in pre + suf:
        for candidate in _affix_candidates_for_policy(
            source,
            rolls=rolls,
            policy=acquisition_policy,
        ):
            meta.append((candidate, str(candidate["line"])))
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
    deep_affixes = 0
    for typ in ("prefix", "suffix"):
        side = sorted((s for s in scored if s[1]["type"] == typ), key=lambda x: -x[0])
        n = 0
        for gain, m, line in side:
            if n >= 3 or len(chosen_lines) >= acquisition_policy.maxExplicitAffixes:
                break
            if gain <= 1e-9 or m["group"] in used:
                continue
            is_deep = bool(m.get("_deepTopTier"))
            if (
                acquisition_policy.maxDeepTopTierAffixes is not None
                and is_deep
                and deep_affixes >= acquisition_policy.maxDeepTopTierAffixes
            ):
                continue
            chosen_lines.append(line)
            used.add(m["group"])
            deep_affixes += int(is_deep)
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
    elemental_resist_target: int | None = None,
    acquisition_profile: str = "realistic_trade",
    locked_slots: list[str] | None = None,
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
    try:
        acquisition_policy = attainability.policy_for(acquisition_profile)
    except ValueError:
        return {"ok": False, "errorCode": "invalid_acquisition_profile"}
    locked = {_canonical_slot(str(slot)) for slot in locked_slots or []}
    build = engine.get_build()
    profile = gear_stage_profile(
        build.get("level"),
        stage=stage,
        chaos_resist_target=chaos_resist_target,
        elemental_resist_target=elemental_resist_target,
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
    replaced_bootstrap_slots: list[str] = []
    try:
        dominant_attr = _attr_bias(engine) if auto_base else "int"
        layer_bias = _defense_layer_bias(build)
        for slot in order:
            if slot in locked:
                skipped.append({"slot": slot, "reason": "locked by selected mechanism/unique"})
                continue
            cur = gear.get(slot)
            if isinstance(cur, dict) and cur.get("base"):
                base: str | None = cur["base"]
                if (
                    acquisition_profile == "realistic_trade"
                    and slot in {"Weapon 1", "Weapon 2"}
                    and (
                        str(cur.get("rarity") or "").casefold() == "normal"
                        or bool(cur.get("isScaffold"))
                    )
                ):
                    base_info = db.get_item(base)
                    item_class = (
                        str(base_info.get("item_class"))
                        if isinstance(base_info, dict) and base_info.get("item_class")
                        else ""
                    )
                    replacement = (
                        db.pick_base(item_class, max_drop_level=character_level)
                        if item_class
                        else None
                    )
                    if replacement and replacement != base:
                        base = replacement
                        replaced_bootstrap_slots.append(slot)
                        engine.add_item(_item_text(base, [], slot, ilvl=item_level), slot=slot)
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
                elemental_resist_target=int(profile["elementalResistTarget"]),
                ilvl=item_level,
                acquisition_policy=acquisition_policy,
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
            affixes = _explicit_item_lines(item)
            parsed_item = itemparse.parse_item(item)
            plan.append(
                {
                    "slot": slot,
                    "item": item,
                    "itemLevel": item_level,
                    "affixes": affixes,
                    "topTierAffixCount": sum(
                        1
                        for affix in parsed_item.get("affixes") or []
                        if isinstance(affix, dict)
                        and affix.get("tier") == 1
                        and int(affix.get("totalTiers") or 0) >= 4
                    ),
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
                before_recraft_xml = engine.get_xml()
                before_resists = engine.get_defenses().get("resistances") or {}
                before_resist_gap = sum(
                    max(
                        0,
                        int(profile["elementalResistTarget"])
                        - float(before_resists.get(element) or 0),
                    )
                    for element in _RES_KEYS
                ) + max(
                    0,
                    int(profile["chaosResistTarget"]) - float(before_resists.get("chaos") or 0),
                )
                item = _marginal_craft(
                    engine,
                    slot,
                    slot_base[slot],
                    {"TotalEHP": 1.0},
                    rolls,
                    chaos_resist_target=int(profile["chaosResistTarget"]),
                    elemental_resist_target=int(profile["elementalResistTarget"]),
                    ilvl=item_level,
                    acquisition_policy=acquisition_policy,
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
                after_resists = engine.get_defenses().get("resistances") or {}
                after_resist_gap = sum(
                    max(
                        0,
                        int(profile["elementalResistTarget"])
                        - float(after_resists.get(element) or 0),
                    )
                    for element in _RES_KEYS
                ) + max(
                    0,
                    int(profile["chaosResistTarget"]) - float(after_resists.get("chaos") or 0),
                )
                if after_resist_gap > before_resist_gap + 1e-9:
                    engine.load_build_xml(before_recraft_xml)
                    continue
                affixes = _explicit_item_lines(item)
                parsed_item = itemparse.parse_item(item)
                plan[:] = [p for p in plan if p["slot"] != slot]
                plan.append(
                    {
                        "slot": slot,
                        "item": item,
                        "itemLevel": item_level,
                        "affixes": affixes,
                        "topTierAffixCount": sum(
                            1
                            for affix in parsed_item.get("affixes") or []
                            if isinstance(affix, dict)
                            and affix.get("tier") == 1
                            and int(affix.get("totalTiers") or 0) >= 4
                        ),
                        "legalityCheck": legality,
                    }
                )
            ehp_floor_met = (engine.get_defenses().get("totalEHP") or 0) >= min_ehp
        stats = engine.get_stats(["TotalDPS", "FullDPS"])["stats"]
        d = engine.get_defenses()
        planned_xml = engine.get_xml()
        whole_build_legality = hard_legality.audit_build(
            hard_legality.augment_build_with_snapshot_gear(engine.get_build(), planned_xml)
        )
    finally:
        engine.load_build_xml(snapshot)

    res = d.get("resistances") or {}
    missing = d.get("resistMissing") or {}
    res_capped = all((missing.get(e) or 0) <= 0 for e in _RES_KEYS)
    resistance_target_met = (
        all((res.get(element) or 0) >= profile["elementalResistTarget"] for element in _RES_KEYS)
        and (res.get("chaos") or 0) >= profile["chaosResistTarget"]
    )
    chaos_capped = (res.get("chaos") or 0) >= 75
    projected: dict[str, Any] = {
        "TotalDPS": _round2(stats.get("TotalDPS")),
        "FullDPS": _round2(stats.get("FullDPS")),
        "TotalEHP": _round2(d.get("totalEHP")),
        "resistances": res,
        "resistsCapped": res_capped,
        "resistanceTargetMet": resistance_target_met,
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
        "status": ("planned" if whole_build_legality.get("hardLegalityReady") else "planning_only"),
        "plan": plan,
        "skipped": skipped,
        "rejectedIllegalCandidates": rejected_illegal,
        "autoBased": [s for s in slot_base if not (gear.get(s) or {}).get("base")],
        "baseDirection": base_direction,
        "acquisitionProfile": acquisition_profile,
        "attainabilityPolicy": attainability.public_policy(acquisition_profile),
        "lockedSlots": sorted(locked),
        "replacedBootstrapSlots": replaced_bootstrap_slots,
        "conflictWarnings": conflict_warnings,
        "stageProfile": profile,
        "itemLevel": item_level,
        "projected": projected,
        "wholeBuildLegality": whole_build_legality,
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


def evaluate_next_jewel_socket(
    engine: PobEngine,
    *,
    raw: str,
    goals: dict[str, float],
    protected_node_ids: list[int] | None = None,
    round_index: int | None = None,
) -> dict[str, Any]:
    """Compare one Agent-selected jewel across every currently reachable empty tree socket."""

    if _jewel_recovery_required(engine):
        return {
            "ok": False,
            "errorCode": "build_state_recovery_required",
            "recoveryRequired": True,
        }
    with engine.transaction_lock():
        try:
            snapshot = engine.get_xml()
            state_hash = build_state_hash(snapshot)
        except Exception:  # noqa: BLE001
            return {"ok": False, "errorCode": "jewel_socket_probe_snapshot_failed"}
        try:
            result, apply_payload = _evaluate_next_jewel_socket_locked(
                engine,
                snapshot=snapshot,
                state_hash=state_hash,
                raw=raw,
                goals=goals,
                protected_node_ids=protected_node_ids,
                round_index=round_index,
            )
        except Exception as exc:  # noqa: BLE001 - restore before returning a stable error.
            restored = _restore_jewel_state(engine, snapshot, state_hash)
            setattr(engine, "_poe2_mutation_batch_recovery_required", not restored)
            return {
                "ok": False,
                "errorCode": (
                    "jewel_socket_probe_restore_failed"
                    if str(exc) == "jewel_socket_probe_restore_failed"
                    else "jewel_socket_probe_failed"
                ),
                "rolledBack": restored,
                "recoveryRequired": not restored,
            }
        restored = _restore_jewel_state(engine, snapshot, state_hash)
        setattr(engine, "_poe2_mutation_batch_recovery_required", not restored)
        if not restored:
            return {
                "ok": False,
                "errorCode": "jewel_socket_probe_restore_failed",
                "rolledBack": False,
                "recoveryRequired": True,
            }
        if result.get("ok") is False:
            return result
        if apply_payload is not None:
            result["decisionRef"] = _record_jewel_apply_decision(engine, apply_payload)
        _record_next_jewel_decision(engine, state_hash, result)
        return result


def _protected_jewel_nodes(
    engine: Any,
    protected_node_ids: list[int] | None,
) -> tuple[list[int], bool, dict[str, Any] | None]:
    if protected_node_ids is None:
        return [], False, None
    protected = sorted({int(value) for value in protected_node_ids})
    missing: list[int] = []
    unallocated: list[int] = []
    for node_id in protected:
        value = engine.get_passive(node_id)
        if not isinstance(value, dict) or value.get("found") is False:
            missing.append(node_id)
            continue
        node = value.get("node") if isinstance(value.get("node"), dict) else value
        if not isinstance(node, dict) or not node.get("alloc"):
            unallocated.append(node_id)
    if missing:
        return (
            protected,
            True,
            {
                "ok": False,
                "errorCode": "protected_passive_not_found",
                "missingProtectedNodeIds": missing,
            },
        )
    if unallocated:
        return (
            protected,
            True,
            {
                "ok": False,
                "errorCode": "protected_passive_not_allocated",
                "unallocatedProtectedNodeIds": unallocated,
            },
        )
    return protected, True, None


def _jewel_review_context_fingerprint(
    *,
    state_hash: str,
    jewel_fingerprint: str,
    goals_fingerprint: str,
    protected_node_ids: list[int],
    protection_declared: bool,
) -> str:
    return canonical_payload_hash(
        {
            "stateHash": state_hash,
            "candidateJewelFingerprint": jewel_fingerprint,
            "goalsFingerprint": goals_fingerprint,
            "protectedNodeIds": protected_node_ids,
            "protectionDeclared": protection_declared,
        },
        prefix="jewel-review",
    )


def _jewel_review_pending_result(
    current: dict[str, Any] | None,
    review_context_fingerprint: str,
) -> dict[str, Any] | None:
    if not isinstance(current, dict) or current.get("status") == "applied":
        return None
    same_context = current.get("reviewContextFingerprint") == review_context_fingerprint
    if current.get("positiveNetBenefit") is True:
        if same_context:
            return {**deepcopy(current), "reused": True}
        if current.get("decisionRef"):
            return {
                "ok": False,
                "errorCode": "jewel_socket_positive_decision_pending",
                "decisionRef": current.get("decisionRef"),
                "stateHash": current.get("stateHash"),
            }
        return None
    if current.get("status") == "inconclusive" and not same_context:
        return {
            "ok": False,
            "errorCode": "jewel_socket_inconclusive_review_pending",
            "stateHash": current.get("stateHash"),
        }
    return None


def _restore_jewel_probe_or_raise(engine: Any, snapshot: str, state_hash: str) -> None:
    if not _restore_jewel_state(engine, snapshot, state_hash):
        raise RuntimeError("jewel_socket_probe_restore_failed")


def _evaluate_next_jewel_socket_locked(
    engine: PobEngine,
    *,
    snapshot: str,
    state_hash: str,
    raw: str,
    goals: dict[str, float],
    protected_node_ids: list[int] | None,
    round_index: int | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Build an unregistered review draft; the caller registers it only after final restore."""

    weights = {
        str(key): float(value) for key, value in goals.items() if _num(value) and float(value) > 0
    }
    if not weights:
        return ({"ok": False, "error": "goals must map stat names to positive weights"}, None)
    jewel_fingerprint = str(itemparse.semantic_item_structure(raw).get("itemFingerprint") or "")
    if not jewel_fingerprint:
        return ({"ok": False, "errorCode": "candidate_jewel_fingerprint_missing"}, None)
    protected, protection_declared, protected_error = _protected_jewel_nodes(
        engine, protected_node_ids
    )
    if protected_error is not None:
        return (protected_error, None)
    goals_fingerprint = canonical_payload_hash(weights, prefix="jewel-goals")
    review_context_fingerprint = _jewel_review_context_fingerprint(
        state_hash=state_hash,
        jewel_fingerprint=jewel_fingerprint,
        goals_fingerprint=goals_fingerprint,
        protected_node_ids=protected,
        protection_declared=protection_declared,
    )
    pending = _jewel_review_pending_result(
        next_jewel_decision_for_state(engine, state_hash),
        review_context_fingerprint,
    )
    if pending is not None:
        return (pending, None)

    reachable: list[dict[str, Any]] = []
    for entry in engine.list_jewel_sockets().get("sockets") or []:
        if not isinstance(entry, dict) or entry.get("allocated") or entry.get("filled"):
            continue
        socket_id = entry.get("socket")
        if not isinstance(socket_id, (int, float)):
            continue
        passive = engine.get_passive(int(socket_id))
        path_cost = passive.get("pathDist") if isinstance(passive, dict) else None
        if (
            not isinstance(path_cost, (int, float))
            or path_cost <= 0
            or passive.get("reachable") is False
        ):
            continue
        reachable.append(
            {
                **entry,
                "socket": int(socket_id),
                "pathPointCost": int(path_cost),
                "pathNodeIds": sorted(
                    int(value)
                    for value in (passive.get("pathNodeIds") or [])
                    if isinstance(value, (int, float))
                ),
            }
        )

    common = {
        "ok": True,
        "reviewPolicyVersion": _JEWEL_REVIEW_POLICY_VERSION,
        "reviewScope": _JEWEL_REVIEW_SCOPE,
        "stateHash": state_hash,
        "candidateJewelFingerprint": jewel_fingerprint,
        "goalsFingerprint": goals_fingerprint,
        "reviewContextFingerprint": review_context_fingerprint,
        "protectionDeclared": protection_declared,
        "protectedNodeIds": protected,
        "roundIndex": round_index,
        "maxRounds": None,
        "goals": weights,
        "readOnly": True,
    }
    if not reachable:
        return (
            {
                **common,
                "status": "not_applicable",
                "positiveNetBenefit": False,
                "reason": "no_reachable_unallocated_jewel_socket",
                "decision": "not_applicable",
                "reachableSocketCount": 0,
                "evaluatedSocketCount": 0,
                "limitedSocketCount": 0,
                "inconclusiveSocketCount": 0,
                "socketFrontierComplete": True,
                "socketEvaluations": [],
            },
            None,
        )

    build = engine.get_build()
    unspent = int(build.get("unspentPoints") or 0)
    keys = list(weights)
    before = engine.get_stats(keys).get("stats") or {}
    denom = {key: max(abs(float(before.get(key) or 0.0)), 1.0) for key in keys}
    before_legality = _whole_build_legality(engine, snapshot)

    candidate_result = engine.list_reallocation_candidates(limit=None)
    protected_set = set(protected)
    leaf_candidates = [
        dict(entry)
        for entry in candidate_result.get("candidates") or []
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), (int, float))
        and int(entry["id"]) not in protected_set
    ]
    reallocation_probes: list[dict[str, Any]] = []
    for entry in leaf_candidates:
        try:
            removed = engine.dealloc_passive(int(entry["id"]))
            if not isinstance(removed, dict) or not removed.get("ok"):
                continue
            points_freed = int(removed.get("pointsFreed") or 0)
            if points_freed != 1:
                continue
            without = engine.get_stats(keys).get("stats") or {}
            loss = sum(
                weight
                * ((float(before.get(key) or 0.0) - float(without.get(key) or 0.0)) / denom[key])
                for key, weight in weights.items()
            )
            reallocation_probes.append(
                {
                    "nodeId": int(entry["id"]),
                    "name": str(entry.get("name") or ""),
                    "type": str(entry.get("type") or ""),
                    "pointsFreed": 1,
                    "weightedRelativeLoss": round(loss, 6),
                    "metricDeltas": {
                        key: round(
                            float(without.get(key) or 0.0) - float(before.get(key) or 0.0),
                            6,
                        )
                        for key in keys
                    },
                }
            )
        finally:
            _restore_jewel_probe_or_raise(engine, snapshot, state_hash)
    reallocation_probes.sort(
        key=lambda entry: (float(entry["weightedRelativeLoss"]), int(entry["nodeId"]))
    )

    socket_evaluations: list[dict[str, Any]] = []
    for socket_entry in sorted(reachable, key=lambda item: int(item["socket"])):
        socket_id = int(socket_entry["socket"])
        path_cost = int(socket_entry["pathPointCost"])
        points_to_reallocate = max(0, path_cost - unspent)
        route_ids = set(socket_entry.get("pathNodeIds") or [])
        available_reallocations = [
            entry for entry in reallocation_probes if int(entry["nodeId"]) not in route_ids
        ]
        selected_reallocations = available_reallocations[:points_to_reallocate]
        base_evaluation = {
            "socket": socket_id,
            "pathPointCost": path_cost,
            "pointsToReallocate": points_to_reallocate,
            "pointsReallocated": len(selected_reallocations),
            "nodesToRemove": [int(entry["nodeId"]) for entry in selected_reallocations],
        }
        if len(selected_reallocations) < points_to_reallocate:
            socket_evaluations.append(
                {
                    **base_evaluation,
                    "status": "policy_limited",
                    "reason": "current_safe_leaf_points_insufficient",
                }
            )
            continue
        try:
            for entry in selected_reallocations:
                removed = engine.dealloc_passive(int(entry["nodeId"]))
                if not isinstance(removed, dict) or not removed.get("ok"):
                    raise ValueError("jewel_reallocation_failed")
            refreshed = engine.get_passive(socket_id)
            refreshed_cost = refreshed.get("pathDist") if isinstance(refreshed, dict) else None
            refreshed_path = sorted(
                int(value)
                for value in (refreshed.get("pathNodeIds") or [])
                if isinstance(value, (int, float))
            )
            if int(refreshed_cost or -1) != path_cost or refreshed_path != list(
                socket_entry.get("pathNodeIds") or []
            ):
                socket_evaluations.append(
                    {
                        **base_evaluation,
                        "status": "policy_limited",
                        "reason": "socket_path_changed_after_reallocation",
                    }
                )
                continue
            allocated = engine.alloc_passive(socket_id)
            if (
                not isinstance(allocated, dict)
                or not allocated.get("ok")
                or allocated.get("warning")
            ):
                raise ValueError("jewel_socket_path_allocation_failed")
            actual_points = int(allocated.get("pointsSpent") or 0)
            if actual_points != path_cost:
                socket_evaluations.append(
                    {
                        **base_evaluation,
                        "status": "policy_limited",
                        "reason": "socket_path_cost_changed_after_reallocation",
                        "actualPointsSpent": actual_points,
                    }
                )
                continue
            equipped = engine.equip_jewel(raw, socket=socket_id)
            if not isinstance(equipped, dict) or not equipped.get("ok"):
                raise ValueError("candidate_jewel_equip_failed")
            if any(not _passive_allocated(engine, node_id) for node_id in protected):
                socket_evaluations.append(
                    {
                        **base_evaluation,
                        "status": "rejected_illegal",
                        "reason": "protected_passive_regression",
                        "actualPointsSpent": actual_points,
                        "legalityRegressionCodes": ["protected_passive_regression"],
                    }
                )
                continue
            candidate_xml = engine.get_xml()
            after_legality = _whole_build_legality(engine, candidate_xml)
            legality_regression = hard_legality.compare_audits_for_regression(
                before_legality,
                after_legality,
            )
            regression_codes = sorted(
                {
                    str(item.get("code") or "unknown")
                    for item in legality_regression.get("reasons") or []
                }
            )
            if regression_codes:
                socket_evaluations.append(
                    {
                        **base_evaluation,
                        "status": "rejected_illegal",
                        "reason": "whole_build_legality_regression",
                        "actualPointsSpent": actual_points,
                        "legalityRegressionCodes": regression_codes,
                    }
                )
                continue
            after = engine.get_stats(keys).get("stats") or {}
            score = sum(
                weight
                * ((float(after.get(key) or 0.0) - float(before.get(key) or 0.0)) / denom[key])
                for key, weight in weights.items()
            )
            socket_evaluations.append(
                {
                    **base_evaluation,
                    "status": "evaluated",
                    "reason": None,
                    "actualPointsSpent": actual_points,
                    "weightedRelativeGain": round(score, 6),
                    "metricDeltas": {
                        key: round(
                            float(after.get(key) or 0.0) - float(before.get(key) or 0.0),
                            6,
                        )
                        for key in keys
                    },
                    "metricsAfter": {key: after.get(key) for key in keys},
                    "legalityRegressionCodes": [],
                }
            )
        except ValueError as exc:
            socket_evaluations.append(
                {
                    **base_evaluation,
                    "status": "inconclusive",
                    "reason": str(exc),
                }
            )
        finally:
            _restore_jewel_probe_or_raise(engine, snapshot, state_hash)

    evaluated = [item for item in socket_evaluations if item.get("status") == "evaluated"]
    evaluated.sort(
        key=lambda item: (
            -float(item.get("weightedRelativeGain") or 0.0),
            int(item.get("pathPointCost") or 0),
            int(item["socket"]),
        )
    )
    best = evaluated[0] if evaluated else None
    limited_count = sum(item.get("status") == "policy_limited" for item in socket_evaluations)
    inconclusive_count = sum(item.get("status") == "inconclusive" for item in socket_evaluations)
    frontier_complete = limited_count == 0 and inconclusive_count == 0
    positive = bool(best and float(best.get("weightedRelativeGain") or 0.0) > 1e-9)
    status = "evaluated" if positive or frontier_complete else "inconclusive"
    positive_result: bool | None = positive if positive or frontier_complete else None
    result: dict[str, Any] = {
        **common,
        "status": status,
        "reachableSocketCount": len(reachable),
        "evaluatedSocketCount": len(evaluated),
        "limitedSocketCount": limited_count,
        "inconclusiveSocketCount": inconclusive_count,
        "socketFrontierComplete": frontier_complete,
        "socketEvaluations": socket_evaluations,
        "reallocationCandidates": reallocation_probes,
        "positiveNetBenefit": positive_result,
        "decision": (
            "declare_protection_before_apply"
            if positive and not protection_declared
            else "apply_best_socket"
            if positive
            else "keep_current_tree"
            if frontier_complete
            else "review_inconclusive"
        ),
        "metricsBefore": {key: before.get(key) for key in keys},
    }
    apply_payload: dict[str, Any] | None = None
    if best is not None:
        result.update(
            {
                "socket": int(best["socket"]),
                "pathPointCost": int(best["pathPointCost"]),
                "pointsReallocated": int(best["pointsReallocated"]),
                "nodesToRemove": list(best["nodesToRemove"]),
                "weightedRelativeGain": float(best["weightedRelativeGain"]),
                "metricsAfter": dict(best.get("metricsAfter") or {}),
            }
        )
    if positive and best is not None and protection_declared:
        apply_payload = {**result, "raw": raw}
    return result, apply_payload
