"""Holistic whole-build optimizer (`optimize_build`) — archetype-seeded commit-and-max.

The greedy per-slot/per-node tools are each locally optimal but myopic: they won't over-commit a
multiplier (crit, +levels, attack speed) before it pays off, so a from-scratch build caps far below
what the same chassis can compute once the lever is present. This does the synthesis they can't —
it commits an archetype's dominant lever as a *structure* across tree + gear + jewels + supports and
searches the commitment space on the engine, keeping the best constraint-satisfying build.

It is pure orchestration of tested primitives — `optimize_passives` (reset/require/goals), `plan_gear`
(auto_base/min_ehp), `optimize_jewel`, `optimize_supports`, `optimize_item`, plus the reference set
(`refbuilds`) for seeding and `benchmark` for placement. It invents no number; every figure is the
engine's. It does NOT bypass the inherent ceilings: perfect gear needs crafting-system modelling and
the 1M trigger meta needs the upstream PoB calc — it reaches the *gear-quality* ceiling for the
archetype, and says so.

Unlike the read-only optimizers, this is a STATE tool: it leaves the best build LOADED in the session
(so you can export_build / get_build / tweak from there) and reports what it committed + the
reference-set placement so the choice is transparent, not a black box.
"""

from __future__ import annotations

import concurrent.futures as cf
from typing import Any

from .defense_state import has_chaos_inoculation

from ..knowledge import db as corpus
from ..knowledge import refbuilds
from . import craftopt, itemopt, supportopt
from .engine import PobEngine, PobEngineError, available_engine_slots

_RES_KEYS = ("fire", "cold", "lightning")
_DAMAGE = {"fire", "cold", "lightning", "chaos", "physical"}
_DELIVERY = (
    "attack",
    "spell",
    "projectile",
    "melee",
    "minion",
    "totem",
    "trap",
    "mine",
    "brand",
    "slam",
    "channelling",
    "area",
)
# Jewel base by the build's dominant attribute (Diamond = all-attribute, the safe default).
_JEWEL_BASE = {"str": "Ruby", "dex": "Emerald", "int": "Sapphire"}
# Unique-pass target slots (gear only; jewels go through sockets, weapons are archetype-defining).
_UNIQUE_SLOTS = {
    "helmet": "Helmet",
    "body": "Body Armour",
    "gloves": "Gloves",
    "boots": "Boots",
    "belt": "Belt",
    "amulet": "Amulet",
    "ring": "Ring 1",
}


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _r2(x: Any) -> Any:
    return round(x, 2) if _num(x) else x


def _gem_tags(engine: PobEngine) -> set[str]:
    skill = str(engine.get_build().get("mainSkill") or "")
    gem = corpus.get_gem(skill) if skill else None
    return set(gem["tags"]) if gem and isinstance(gem.get("tags"), list) else set()


def _delivery_tags(engine: PobEngine) -> list[str]:
    tags = _gem_tags(engine)
    return [t for t in _DELIVERY if t in tags]


def _damage_types(engine: PobEngine) -> list[str]:
    tags = _gem_tags(engine)
    return [t for t in ("lightning", "fire", "cold", "chaos", "physical") if t in tags]


def _attr_bias(engine: PobEngine) -> str:
    st = engine.get_stats(["Str", "Dex", "Int"]).get("stats") or {}
    by = {"str": st.get("Str") or 0, "dex": st.get("Dex") or 0, "int": st.get("Int") or 0}
    return max(by, key=lambda k: by[k])


def _lever_tree_query(lever: str, damage_types: list[str]) -> str | None:
    """Map a reference `topLevers` name -> a passive-tree search query whose top notables we REQUIRE
    (the seed over-commitment). None = a gear/gem-driven lever (e.g. +levels) with no special tree
    cluster — handled by optimizing gear/supports for the metric (≈ the balanced pass)."""
    low = lever.lower()
    if "crit" in low or "critical" in low:
        return "critical"
    if "attack speed" in low:
        return "attack speed"
    if "cast speed" in low:
        return "cast speed"
    if "penetrat" in low or "exposure" in low:
        return (damage_types[0] + " penetration") if damage_types else "penetration"
    if "more damage" in low or ("increased" in low and "damage" in low):
        return (damage_types[0] + " damage") if damage_types else "damage"
    return None


def _require_tree_nodes(engine: PobEngine, query: str, top: int = 2) -> list[int]:
    """Up to `top` reachable notable ids for `query` — search_passives already orders by relevance
    then nearest pathDist, so the head is the most relevant, cheapest-to-path cluster."""
    r = engine.search_passives(query=query, node_type="Notable", limit=12)
    out: list[int] = []
    for n in r.get("nodes") or r.get("results") or []:
        if n.get("alloc"):
            continue
        if not _num(n.get("pathDist")):
            continue
        nid = n.get("id")
        if _num(nid):
            out.append(int(nid))
        if len(out) >= top:
            break
    return out


def _near_jewel_sockets(engine: PobEngine, n: int) -> list[int]:
    """The `n` nearest UNALLOCATED jewel sockets (by pathDist) — requiring far ones wastes the point
    budget that should go to damage, so we sort nearest-first and cap."""
    if n <= 0:
        return []
    socks = engine.list_jewel_sockets().get("sockets") or []
    cands: list[tuple[float, int]] = []
    for s in socks:
        if s.get("allocated"):
            continue
        sid = s.get("socket")
        if not _num(sid):
            continue
        info = engine.get_passive(int(sid))
        node = info.get("node") if isinstance(info.get("node"), dict) else info
        pd = node.get("pathDist") if isinstance(node, dict) else None
        if isinstance(pd, (int, float)) and not isinstance(pd, bool):
            cands.append((float(pd), int(sid)))
    cands.sort()
    return [sid for _, sid in cands[:n]]


def _resistance_target_status(
    build: dict[str, Any], defenses: dict[str, Any]
) -> tuple[bool, bool, int, int]:
    profile = itemopt.gear_stage_profile(build.get("level"), stage="auto")
    missing = defenses.get("resistMissing") or {}
    resistances = defenses.get("resistances") or {}
    res_capped = all((missing.get(e) or 0) <= 0 for e in _RES_KEYS)
    elemental_target = int(profile["elementalResistTarget"])
    chaos_target = int(profile["chaosResistTarget"])
    ci = has_chaos_inoculation(build)
    resistance_target_met = all(
        (resistances.get(element) or 0) >= elemental_target for element in _RES_KEYS
    ) and (ci or (resistances.get("chaos") or 0) >= chaos_target)
    return res_capped, resistance_target_met, elemental_target, chaos_target


def _result(engine: PobEngine, metric: str, min_ehp: float | None) -> dict[str, Any]:
    """Whole-build snapshot for ranking: the metric + defensive constraint flags."""
    st = engine.get_stats(["TotalDPS", "FullDPS"]).get("stats") or {}
    d = engine.get_defenses() or {}
    build = engine.get_build()
    res_capped, resistance_target_met, elemental_target, chaos_target = (
        _resistance_target_status(build, d)
    )
    ehp = d.get("totalEHP")
    ehp_ok = (ehp or 0) >= min_ehp if min_ehp else True
    val = st.get(metric)
    if not _num(val):
        val = st.get("TotalDPS")
    score = float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else 0.0
    return {
        "metricValue": _r2(val),
        "TotalDPS": _r2(st.get("TotalDPS")),
        "FullDPS": _r2(st.get("FullDPS")),
        "TotalEHP": _r2(ehp),
        "resistsCapped": res_capped,
        "resistanceTargetMet": resistance_target_met,
        "elementalResistTarget": elemental_target,
        "chaosResistTarget": chaos_target,
        "ehpFloorMet": ehp_ok,
        "constraintsMet": bool(resistance_target_met and ehp_ok),
        "score": score,
    }


def _equip_plan(engine: PobEngine, plan: list[dict[str, Any]]) -> None:
    for p in plan:
        item, slot = p.get("item"), p.get("slot")
        if item and slot:
            engine.add_item(item, slot=slot)


def _craft_weapon(engine: PobEngine, metric: str) -> None:
    """Polish the main-hand to pure metric (the single biggest lever) — plan_gear leaves weapons
    blended; this maxes them. No-op if the slot has no base."""
    r = itemopt.optimize_item(engine, "Weapon 1", metric=metric, thorough=True)
    if r.get("ok") and r.get("item"):
        engine.add_item(r["item"], slot="Weapon 1")


def _fill_jewels(engine: PobEngine, metric: str, base: str) -> int:
    """Socket every ALLOCATED jewel socket with its best metric-raising rare jewel. Re-optimizes
    filled sockets too, so a later pass improves them on the now-stronger build. Returns count."""
    socks = engine.list_jewel_sockets().get("sockets") or []
    filled = 0
    for s in socks:
        if not s.get("allocated"):
            continue
        sid = s.get("socket")
        if not _num(sid):
            continue
        j = itemopt.optimize_jewel(engine, metric=metric, base=base)
        if j.get("ok") and j.get("item"):
            engine.equip_jewel(j["item"], socket=int(sid))
            filled += 1
    return filled


def _apply_supports(engine: PobEngine, metric: str) -> None:
    r = supportopt.optimize_supports(engine, metric=metric)
    if not r.get("ok"):
        return
    skill = r.get("skill")
    if not skill:
        return
    sup = r.get("supports") or []
    text = f"{skill} 20/20 1" + ("\n" + "\n".join(sup) if sup else "")
    engine.paste_skill(text)


def _unique_item_text(full: dict[str, Any]) -> str:
    """Build canonical PoB item text from a corpus unique. The stored `text` already leads with
    name/base (and sometimes a `League:` line) before the mods, so we take name/base from their own
    fields and keep only the mod lines — otherwise the name/base get duplicated into the mod block."""
    name = str(full.get("name") or "")
    base = str(full.get("base") or "")
    mods = [
        ln
        for ln in str(full.get("text") or "").splitlines()
        if ln.strip()
        and ln.strip() != name
        and ln.strip() != base
        and not ln.lower().startswith("league:")
    ]
    return f"Rarity: Unique\n{name}\n{base}\n--------\n" + "\n".join(mods)


def _unique_pass(engine: PobEngine, metric: str, min_ehp: float | None) -> list[dict[str, Any]]:
    """v2 — try the build-relevant uniques per gear slot: equip each, keep it only if it raises the
    metric without breaking the defensive constraints. Best-effort and bounded; a unique that ENABLES
    a mechanic (rather than just adding stats) won't always show its value here — those are flagged
    for manual review. Read-only per candidate (snapshot/restore), persists only kept upgrades."""
    skill = str(engine.get_build().get("mainSkill") or "")
    tags = _gem_tags(engine)
    keywords = sorted(
        (tags & _DAMAGE) | (tags & {"spell", "attack", "projectile", "minion", "melee", "area"})
    )
    if skill:
        keywords.append(skill)
    if not keywords:
        return []
    cands = corpus.relevant_uniques(keywords, limit=24)
    swapped: list[dict[str, Any]] = []
    base = _result(engine, metric, min_ehp)
    cur = base["score"]
    for u in cands:
        itype = str(u.get("item_type") or "").lower()
        slot = next((s for key, s in _UNIQUE_SLOTS.items() if key in itype), None)
        if not slot:
            continue
        full = corpus.get_unique(str(u.get("name") or ""))
        if not full or not full.get("text"):
            continue
        raw = _unique_item_text(full)
        snap = engine.get_xml()
        try:
            engine.add_item(raw, slot=slot)
            r = _result(engine, metric, min_ehp)
            keep = r["score"] > cur + 1e-9 and r["constraintsMet"] >= base["constraintsMet"]
        except Exception:
            keep = False
            r = base
        if keep:
            cur = r["score"]
            swapped.append(
                {"slot": slot, "unique": full.get("name"), "metricValue": r["metricValue"]}
            )
        else:
            engine.load_build_xml(snap)
    return swapped


def commit_and_max(
    engine: PobEngine,
    snapshot: str,
    lever: str | None,
    *,
    metric: str,
    min_ehp: float | None,
    passes: int,
    max_jewel_sockets: int,
    try_uniques: bool,
    damage_types: list[str],
    combat: dict[str, Any],
) -> dict[str, Any]:
    """Build the version that maximally commits `lever` (None = balanced) across tree+gear+jewels+
    supports, evaluated as the whole build. Starts fresh from `snapshot`; returns the metrics + the
    build XML + what it committed. The over-commitment lives in REQUIRING the lever's tree clusters
    (which greedy alone won't take) + filling jewel sockets — once those make the lever valuable, the
    metric-greedy gear/jewels/supports pile onto it naturally, breaking the per-slot chicken-egg."""
    engine.load_build_xml(snapshot)

    require: list[str | int] = []
    tree_query = _lever_tree_query(lever, damage_types) if lever else None
    if tree_query:
        require += _require_tree_nodes(engine, tree_query)
    require += _near_jewel_sockets(engine, max_jewel_sockets)

    # When an EHP floor is set, the tree must carry some defence — gear alone caps ~10k EHP, short of
    # a pinnacle ~20k. A light EHP weight makes the tree pick life/ES/resist clusters too (a real
    # pinnacle build is hybrid, not a pure-DPS tree); pure DPS otherwise.
    tree_goals = {"TotalDPS": 0.75, "TotalEHP": 0.25} if min_ehp else None
    tree = engine.optimize_passives(
        metric=metric, points=0, reset=True, require=require or None, goals=tree_goals
    )
    engine.set_config(options=combat)

    jewel_base = _JEWEL_BASE.get(_attr_bias(engine), "Diamond")
    jewels = 0
    for _ in range(max(1, passes)):
        plan = itemopt.plan_gear(engine, dps_weight=0.85, min_ehp=min_ehp)
        _equip_plan(engine, plan.get("plan") or [])
        _craft_weapon(engine, metric)
        jewels = _fill_jewels(engine, metric, jewel_base)
        _apply_supports(engine, metric)

    uniques: list[dict[str, Any]] = []
    if try_uniques:
        uniques = _unique_pass(engine, metric, min_ehp)

    res = _result(engine, metric, min_ehp)
    res["lever"] = lever or "balanced"
    res["treeRequired"] = require
    res["jewelsSocketed"] = jewels
    res["uniquesEquipped"] = uniques
    res["requireSkipped"] = tree.get("requireSkipped") or []
    res["xml"] = engine.get_xml()
    return res


def _setup_archetype(engine: PobEngine, base: str, arch: dict[str, Any]) -> str | None:
    """Produce a starting snapshot for a candidate archetype (v3 multi-archetype). `arch` keys:
    class, ascendancy, skill, weapon (full PoB item text for the main hand). Returns the snapshot
    XML, or None if it couldn't be set up."""
    try:
        engine.load_build_xml(base)
        if arch.get("class"):
            engine.set_class(str(arch["class"]), arch.get("ascendancy"))
        if arch.get("weapon"):
            engine.add_item(str(arch["weapon"]), slot="Weapon 1")
        if arch.get("skill"):
            engine.paste_skill(f"{arch['skill']} 20/20 1")
        return engine.get_xml()
    except Exception:
        return None


def _run_levers(
    engine: PobEngine,
    snapshot: str,
    levers: list[str | None],
    *,
    parallel: bool,
    max_workers: int,
    **kw: Any,
) -> list[dict[str, Any]]:
    """Run commit_and_max for each lever. Sequential by default; with `parallel`, spread the levers
    across a small pool of independent engine subprocesses (each used by exactly one thread, so the
    sync stdio stays safe). The engine bottleneck is one subprocess, so this is the real speedup."""
    if not parallel or len(levers) <= 1:
        return [commit_and_max(engine, snapshot, lev, **kw) for lev in levers]

    n = min(max(2, max_workers), len(levers), 1 + available_engine_slots())
    if n <= 1:
        return [commit_and_max(engine, snapshot, lev, **kw) for lev in levers]
    extras: list[PobEngine] = []
    for _ in range(n - 1):
        try:
            extras.append(PobEngine(script=engine.script))
        except PobEngineError:
            break
    n = 1 + len(extras)
    if n <= 1:
        return [commit_and_max(engine, snapshot, lev, **kw) for lev in levers]
    engines = [engine, *extras]
    chunks: list[list[str | None]] = [levers[i::n] for i in range(n)]

    def work(eng: PobEngine, chunk: list[str | None]) -> list[dict[str, Any]]:
        return [commit_and_max(eng, snapshot, lev, **kw) for lev in chunk]

    try:
        with cf.ThreadPoolExecutor(max_workers=n) as ex:
            futs = [ex.submit(work, engines[i], chunks[i]) for i in range(n)]
            out: list[dict[str, Any]] = []
            for f in futs:
                out += f.result()
        return out
    finally:
        for e in extras:
            e.close()


_CRAFT_OFFENSE = ("Weapon 1", "Amulet", "Gloves", "Ring 1", "Ring 2")
_CRAFT_DEFENSE = ("Body Armour", "Helmet", "Boots", "Belt", "Weapon 2")


def _resistance_target_met(engine: PobEngine) -> bool:
    _capped, target_met, _elemental_target, _chaos_target = _resistance_target_status(
        engine.get_build(), engine.get_defenses() or {}
    )
    return target_met


def _craft_gear(engine: PobEngine, metric: str) -> list[dict[str, Any]]:
    """'Awesome gear' post-pass: re-craft every equipped gear slot with the FULL crafting system
    (runes + Perfect essences + corruption). Each slot keeps a resist/EHP weight (offense damage-heavy,
    defense EHP-heavy) so it doesn't strip its resistances, then a repair pass restores any cross-slot
    stage-target balance the per-slot crafting disturbed. Crafted on the live build so gains compound. Heavy."""
    gear = engine.get_build().get("gear") or {}
    craftable = [
        s
        for s, cur in gear.items()
        if isinstance(cur, dict) and cur.get("base") and "Jewel" not in s
    ]
    crafted: dict[str, dict[str, Any]] = {}

    def do(slot: str, goals: dict[str, float]) -> None:
        r = craftopt.craft_item(engine, slot, goals=goals)
        if r.get("ok") and r.get("item"):
            engine.add_item(r["item"], slot=slot)
            c = r.get("crafting") or {}
            if c.get("runes") or c.get("essencesUsed") or c.get("corruptedImplicit"):
                crafted[slot] = {"slot": slot, **c}

    for slot in craftable:
        if slot in _CRAFT_OFFENSE:
            do(slot, {metric: 0.85, "TotalEHP": 0.15})  # keep resists/EHP, don't go pure-DPS
        else:
            do(slot, {"TotalEHP": 0.8, metric: 0.2})

    # Per-slot crafting can disturb plan_gear's cross-slot resist allocation; recraft defence slots
    # toward pure EHP until the configured stage resistance target is met again.
    if not _resistance_target_met(engine):
        for slot in [s for s in _CRAFT_DEFENSE if s in craftable]:
            if _resistance_target_met(engine):
                break
            do(slot, {"TotalEHP": 1.0})

    return list(crafted.values())


_CEILING_NOTE = (
    "Best found (engine-verified), not a global optimum. Reaches the gear-quality ceiling for this "
    "archetype — committed lever across tree + gear + jewels + supports. Pass crafting=true to also "
    "apply the full crafting system (runes + Perfect essences + corruption) to every slot. The one "
    "thing it CANNOT model is energy-meta TRIGGERS (e.g. Cast on Critical → Comet) — upstream PoB. "
    "Run apply_combat_profile with the conditions THIS build actually produces (shock/curse/charges) "
    "for the in-fight DPS, and validate_build before presenting."
)


def optimize_build(
    engine: PobEngine,
    *,
    metric: str = "TotalDPS",
    min_ehp: float | None = 20000,
    levers: list[str] | None = None,
    tier: str = "Pinnacle",
    passes: int = 2,
    max_jewel_sockets: int = 3,
    try_uniques: bool = False,
    crafting: bool = False,
    combat: dict[str, Any] | None = None,
    archetypes: list[dict[str, Any]] | None = None,
    parallel: bool = False,
    max_workers: int = 3,
) -> dict[str, Any]:
    """Assemble a complete, verified, high-`metric` build for the ACTIVE archetype (class+ascendancy+
    skill+weapon already set) via archetype-seeded commit-and-max. Leaves the best build LOADED.

    `levers` auto-seeds from the reference set for the build's delivery when omitted; pass explicit
    reference lever names to force the search. `min_ehp` is the EHP floor (hard constraint, with
    stage resistance targets). `try_uniques` adds the v2 unique pass. `archetypes` (v3) evaluates alternative
    class/skill/weapon configs too and keeps the best — the LLM proposes archetypes, the optimizer
    picks. `parallel` spreads the lever search across engine subprocesses. See the module docstring.
    """
    b = engine.get_build()
    skill = str(b.get("mainSkill") or "")
    if not skill:
        return {
            "ok": False,
            "error": "No active main skill — set_class + set_skill (or import a build) first.",
        }
    level = b.get("level")
    if isinstance(level, int) and level < 30:
        return {
            "ok": False,
            "error": f"Build is level {level} — too few passive points to optimize a tree (an empty "
            "tree gives a weak, misleading result). set_level to an endgame level (~90+) first, or "
            "import a real build.",
        }

    delivery = _delivery_tags(engine)
    damage_types = _damage_types(engine)
    if "attack" in delivery and not (b.get("gear") or {}).get("Weapon 1"):
        return {
            "ok": False,
            "error": "Attack skill with no main-hand weapon — equip a weapon base first (it's "
            "archetype-defining, so the optimizer won't pick it). Spell skills don't need one.",
        }

    seeded = list(levers) if levers is not None else refbuilds.archetype_levers(delivery)
    # Candidate set: the balanced build (no forced lever) + each seeded lever. Dedup by tree-query so
    # two levers that commit the same cluster (e.g. "crit damage" / "crit chance") don't both run.
    candidates: list[str | None] = [None]
    seen_q: set[str | None] = set()
    for lev in seeded:
        q = _lever_tree_query(lev, damage_types)
        if q is None or q in seen_q:
            continue  # gear/gem-driven (≈ balanced) or duplicate cluster — skip the redundant run
        seen_q.add(q)
        candidates.append(lev)

    profile = combat or {"enemyIsBoss": tier, "conditionFullEnergyShield": True}
    snapshot = engine.get_xml()
    kw: dict[str, Any] = dict(
        metric=metric,
        min_ehp=min_ehp,
        passes=passes,
        max_jewel_sockets=max_jewel_sockets,
        try_uniques=try_uniques,
        damage_types=damage_types,
        combat=profile,
    )

    results = _run_levers(
        engine, snapshot, candidates, parallel=parallel, max_workers=max_workers, **kw
    )
    for r in results:
        r["archetype"] = "active"

    # v3 multi-archetype: evaluate each proposed config from the same base, keep all results.
    for arch in archetypes or []:
        arch_snap = _setup_archetype(engine, snapshot, arch)
        if arch_snap is None:
            continue
        ares = _run_levers(
            engine, arch_snap, candidates, parallel=parallel, max_workers=max_workers, **kw
        )
        label = arch.get("skill") or arch.get("ascendancy") or arch.get("class") or "archetype"
        for r in ares:
            r["archetype"] = str(label)
        results += ares

    if not results:
        return {"ok": False, "error": "Optimizer produced no candidate builds."}

    # Objective: best metric among constraint-satisfying builds; fall back to best metric + flag.
    satisfying = [r for r in results if r.get("constraintsMet")]
    best = max(satisfying or results, key=lambda r: r["score"])
    engine.load_build_xml(best["xml"])  # leave the winner loaded in the session

    # 'Awesome gear' post-pass: apply the full crafting system to the winner's gear, then re-measure.
    crafted_gear: list[dict[str, Any]] = []
    if crafting:
        crafted_gear = _craft_gear(engine, metric)
        post = _result(engine, metric, min_ehp)
        for k in (
            "TotalDPS",
            "FullDPS",
            "TotalEHP",
            "resistsCapped",
            "resistanceTargetMet",
            "elementalResistTarget",
            "chaosResistTarget",
            "ehpFloorMet",
        ):
            best[k] = post[k]

    bench = refbuilds.benchmark(
        best.get("TotalDPS"), best.get("FullDPS"), best.get("TotalEHP"), delivery
    )

    def _slim(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "lever": r.get("lever"),
            "archetype": r.get("archetype"),
            "metricValue": r.get("metricValue"),
            "TotalEHP": r.get("TotalEHP"),
            "constraintsMet": r.get("constraintsMet"),
            "jewelsSocketed": r.get("jewelsSocketed"),
        }

    return {
        "ok": True,
        "metric": metric,
        "committed": best.get("lever"),
        "committedArchetype": best.get("archetype"),
        "result": {
            "TotalDPS": best.get("TotalDPS"),
            "FullDPS": best.get("FullDPS"),
            "TotalEHP": best.get("TotalEHP"),
            "resistsCapped": best.get("resistsCapped"),
            "resistanceTargetMet": best.get("resistanceTargetMet"),
            "elementalResistTarget": best.get("elementalResistTarget"),
            "chaosResistTarget": best.get("chaosResistTarget"),
            "ehpFloorMet": best.get("ehpFloorMet"),
            "jewelsSocketed": best.get("jewelsSocketed"),
            "uniquesEquipped": best.get("uniquesEquipped") or [],
            "craftedGear": crafted_gear,
        },
        "constraints": {
            "minEHP": min_ehp,
            "resistanceTargetMet": True,
            "satisfied": bool(satisfying),
        },
        "leverResults": sorted(
            (_slim(r) for r in results), key=lambda r: r.get("metricValue") or 0, reverse=True
        ),
        "benchmark": bench,
        "combatProfile": profile,
        "note": _CEILING_NOTE,
    }
