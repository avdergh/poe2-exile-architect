"""Defensive gear scaffold (thin engine+corpus coordinator).

Fills the active build's EMPTY armour/jewellery slots with transparent placeholder rares that
close the build's *actual* defensive gaps, so a from-scratch skeleton becomes engine-evaluable.

It is **gap-driven, not a fixed template** — it only adds a resistance that's below the target,
scaffolds Energy Shield instead of Life for an ES/CI build (or nothing, with `pool="none"`), and
fills only empty slots. The items are an explicit BASELINE — not the player's real gear and not
optimal; replace them with real drops. Weapons/offense are deliberately left to the assistant
(offense gear is build-specific; defensive completion is universal/mechanical).
"""

from __future__ import annotations

from typing import Any

from .compute import itemopt
from .compute.engine import PobEngine

# Defensive slots only (no weapons) -> the corpus item_class to pull a base from.
_SLOT_CLASS = {
    "Helmet": "Helmet",
    "Body Armour": "Body Armour",
    "Gloves": "Gloves",
    "Boots": "Boots",
    "Belt": "Belt",
    "Amulet": "Amulet",
    "Ring 1": "Ring",
    "Ring 2": "Ring",
}
_RES_PER_MOD = 35  # a realistic high single-element resistance roll
_POOL_TEXT = {"life": "maximum Life", "energy_shield": "maximum Energy Shield"}
_POOL_AMT = {"life": 90, "energy_shield": 80}
# Intelligence classes default to Energy Shield (their natural layer) when nothing else signals.
_INT_CLASSES = {"Sorceress", "Witch"}


def _base_for(item_class: str, level: int) -> str | None:
    return itemopt.pick_ordinary_base(item_class, max_drop_level=level)


def scaffold_gear(
    engine: PobEngine,
    pool: str = "auto",
    target_resist: int = 75,
    slots: list[str] | None = None,
) -> dict[str, Any]:
    """Fill empty defensive slots to close the build's resistance + pool gaps. See module docs."""
    before = engine.get_defenses()
    build = engine.get_build()
    level = max(1, int(build.get("level") or 1))
    filled = set((build.get("gear") or {}).keys())
    want = [s for s in (slots or list(_SLOT_CLASS)) if s in _SLOT_CLASS and s not in filled]
    if not want:
        return {"ok": True, "filled": [], "note": "No empty armour/jewellery slots to scaffold."}

    # Resistance gaps — only what's below target (a build already capping a resist gets nothing).
    res = before.get("resistances") or {}
    gaps = {el: max(0, target_resist - (res.get(el) or 0)) for el in ("fire", "cold", "lightning")}

    # Pool: auto -> Energy Shield for an ES/CI build or an intelligence class (Sorceress/Witch,
    # where ES is the natural layer), else Life. "none" adds no pool.
    if pool == "auto":
        life, es = before.get("life") or 0, before.get("energyShield") or 0
        cls = build.get("class") or ""
        if es > life or life <= 1:
            pool = "energy_shield"
        elif cls in _INT_CLASSES:
            pool = "energy_shield"
        else:
            pool = "life"
    pool_text = _POOL_TEXT.get(pool)
    pool_amt = _POOL_AMT.get(pool, 0)

    filled_out: list[dict[str, Any]] = []
    for slot in want:
        base = _base_for(_SLOT_CLASS[slot], level)
        if not base:
            continue
        mods: list[str] = []
        if pool_text and pool_amt:
            mods.append(f"+{pool_amt} to {pool_text}")
        for el in sorted(gaps, key=lambda e: -gaps[e]):  # close the largest gaps first
            if gaps[el] <= 0 or len(mods) >= (3 if pool_text else 2):
                continue
            roll = int(min(_RES_PER_MOD, gaps[el]))
            if roll <= 0:
                continue
            mods.append(f"+{roll}% to {el.capitalize()} Resistance")
            gaps[el] -= roll
        properties = itemopt._generated_item_property_lines(base, ilvl=level)
        property_text = "".join(f"{line}\n" for line in properties)
        implicits = itemopt._generated_item_implicit_lines(base, ilvl=level)
        implicit_text = (
            f"Implicits: {len(implicits)}\n" + "\n".join(implicits) + "\n"
            if implicits
            else "--------\n"
        )
        raw = "Rarity: Rare\nScaffold {}\n{}\nItem Level: {}\n{}{}{}".format(
            slot, base, level, property_text, implicit_text, "\n".join(mods)
        )
        r = engine.add_item(raw, slot=slot)
        if r.get("ok"):
            filled_out.append({"slot": slot, "base": base, "mods": mods})

    after = engine.get_defenses()
    chaos = (after.get("resistances") or {}).get("chaos")
    note = (
        f"Placeholder BASELINE gear to make the build engine-evaluable — NOT real items and "
        f"NOT optimal. It attempted to close the elemental resistance gaps (toward {target_resist}%; "
        f"re-check resistsAfter) and "
        f"added a {pool} pool. Replace each piece with real drops (search_mods/search_uniques) "
        f"and check cost with get_prices. Weapons/offense are left to you."
    )
    # Chaos resistance isn't scaffolded (slots are spent on the 3 elements + pool); flag it so it
    # isn't forgotten — it has no area penalty but matters in the endgame.
    if isinstance(chaos, (int, float)) and chaos <= 0:
        note += (
            f" Chaos resistance is {chaos} and was NOT scaffolded — add it on real gear (a suffix) "
            f"toward positive/capped."
        )
    return {
        "ok": True,
        "filled": filled_out,
        "pool": pool,
        "resistsAfter": after.get("resistances"),
        "chaosResAfter": chaos,
        "lifeAfter": after.get("life"),
        "energyShieldAfter": after.get("energyShield"),
        "totalEHPAfter": after.get("totalEHP"),
        "note": note,
    }
