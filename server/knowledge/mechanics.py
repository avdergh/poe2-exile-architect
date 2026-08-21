"""Curated, concise Path of Exile 2 mechanics references.

Short reference notes for common mechanics. These are intentionally brief — the in-game
tooltips and PoB's Calcs breakdown remain authoritative for exact interactions.
"""

from __future__ import annotations

from . import db

MECHANICS: dict[str, str] = {
    "resistances": (
        "Elemental resistances (fire/cold/lightning) reduce elemental damage taken; the cap is "
        "75% (raisable with +maximum resistance). The endgame area penalty is -60% to elemental "
        "resistances (smaller in earlier acts), so you need well over +100% from gear/tree to "
        "reach the 75% cap. Chaos resistance is separate and has no area penalty. 'Over-cap' "
        "(resistance above 75%) is a buffer against enemy penetration and resistance-reducing "
        "curses/exposure."
    ),
    "ailments": (
        "Ailments are debuffs caused by damage. Ignite (fire) burns over time; Shock (lightning) "
        "increases damage the enemy takes; Chill (cold) slows and Freeze locks; Bleed (physical) "
        "and Poison (chaos+physical) are stacking damage-over-time. Magnitude scales with the "
        "hit's size relative to the enemy's ailment threshold."
    ),
    "armour": (
        "Armour mitigates physical hits, with mitigation relative to the hit size — very effective "
        "against many small hits, much weaker against single large hits. It does not reduce "
        "damage-over-time."
    ),
    "evasion": (
        "Evasion gives a chance to avoid being hit by attacks (not spells, not damage-over-time). "
        "PoE uses an 'entropy' system, so evasion is consistent rather than streaky."
    ),
    "energy_shield": (
        "Energy Shield is a buffer depleted before Life; it starts recharging after a short delay "
        "without taking damage. Many builds use it as the main defensive layer (usually on "
        "intelligence gear)."
    ),
    "spirit": (
        "Spirit is a Path of Exile 2 resource used to reserve persistent skills — auras, heralds, "
        "persistent buffs, and some minions/meta-gems. More Spirit lets you run more reservations."
    ),
    "critical_strike": (
        "Critical strikes deal extra damage equal to your Critical Damage Bonus. Scaling crit "
        "needs both Critical Hit Chance and Critical Damage Bonus; some builds skip crit entirely "
        "(e.g. with Controlled Destruction)."
    ),
    "ehp": (
        "Effective HP (EHP) is total survivable damage: Life + Energy Shield + Ward scaled by your "
        "mitigation (armour, resistances, block, evasion). PoB's TotalEHP estimates this against a "
        "mixed damage profile — higher is tankier."
    ),
    "accuracy": (
        "Accuracy sets your chance to land attacks (spells always hit). Low accuracy means misses; "
        "attack builds want hit chance near 100%. It doesn't affect spells or damage-over-time."
    ),
    "recovery": (
        "Recovery comes from Life/ES/Mana regeneration, leech (a % of damage dealt returned over "
        "time, capped by a rate), and flasks. Sustain matters as much as raw EHP for survival."
    ),
}

_NOTE = "Concise reference — verify exact interactions in-game or via PoB's Calcs breakdown."


def _curated(norm: str) -> tuple[str, str] | None:
    """Match a normalized topic to an exact Tier-1 evergreen note."""
    if norm in MECHANICS:
        return norm, MECHANICS[norm]
    return None


def explain(topic: str) -> dict:
    """Explain a mechanic. Combines our evergreen 'principle' (Tier 1, hand-authored) with the
    auto-refreshed, attributed wiki page (Tier 2) when one matches."""
    raw = (topic or "").strip()
    norm = raw.lower().replace(" ", "_").replace("-", "_")
    curated = _curated(norm)

    wiki = db.get_mechanic(raw, fuzzy=False) if raw else None

    if not curated and not wiki:
        hits = db.search_mechanics(raw, limit=8) if raw else []
        curated_candidates = [
            key for key in sorted(MECHANICS) if norm and (norm in key or key in norm)
        ]
        return {
            "topic": raw,
            "found": False,
            "resultKind": "search_candidates",
            "candidates": [
                {
                    "title": hit["title"],
                    "id": hit["id"],
                    "snippet": hit["snippet"],
                    "url": hit["url"],
                    "matchKind": "local_corpus",
                }
                for hit in hits
            ],
            "curatedCandidates": curated_candidates,
            "available_topics": sorted(MECHANICS),
            "hint": (
                "No exact bundled entry. Candidates are discovery only: fetch one by exact title "
                "and let the Agent judge supports/contradicts/silent. Use lookup_mechanic for "
                "a live page not present in the corpus."
            ),
        }

    label = curated[0] if curated else wiki["title"]  # type: ignore[index]  # one is non-None here
    out: dict = {
        "topic": label,
        "requestedTopic": raw,
        "found": True,
        "resultKind": "curated_exact" if curated else "local_corpus",
        "matchKind": "local_corpus",
        "note": _NOTE,
    }
    if curated:
        out["principle"] = curated[1]
    if wiki:
        out["wiki"] = {k: wiki[k] for k in ("title", "text", "url", "license", "source")}
        out["attribution"] = f"{wiki['source']}, {wiki['license']} — {wiki['url']}"
    return out


def topics() -> list[str]:
    return sorted(MECHANICS)


# Damage-type tag -> the ailment it builds, so a build's element points at the right page.
_TAG_AILMENT = {
    "fire": "ignite",
    "cold": "freeze",
    "lightning": "shock",
    "chaos": "poison",
    "physical": "bleeding",
}
# Always-relevant staples worth surfacing for any build.
_STAPLES = ["resistance", "ailment"]
# Tags that aren't mechanics (attributes, gem bookkeeping) — skip to cut noise.
_SKIP_TAGS = {"strength", "dexterity", "intelligence", "gem", "grants_active_skill", "skill"}


def relevant(
    skill: str | None = None,
    tags: list[str] | None = None,
    keystones: list[str] | None = None,
    ascendancy: list[str] | None = None,
    limit: int = 8,
) -> list[dict]:
    """Map an active build's signals to the mechanics pages worth reading for it.

    Each signal (skill tags, the element's ailment, keystones, ascendancy notables, plus a couple
    of staples) is resolved to its best-matching corpus mechanics page, deduped, with a `why`.
    """
    out: list[dict] = []
    seen: set[str] = set()

    def add(term: str, why: str) -> None:
        if not term or len(out) >= limit:
            return
        hits = db.search_mechanics(term, limit=1)
        if not hits or hits[0]["id"] in seen:
            return
        h = hits[0]
        # relevance guard: the query's key word must appear in the matched page title, so a tag
        # without a dedicated page (e.g. "lightning"→"Damage conversion") doesn't surface noise.
        key = term.split()[0].lower()
        if key and key not in h["title"].lower():
            return
        seen.add(h["id"])
        out.append({"topic": term, "title": h["title"], "url": h["url"], "why": why})

    for t in tags or []:
        tl = t.lower()
        if tl in _SKIP_TAGS:
            continue
        if tl in _TAG_AILMENT:
            # damage-type tags have no dedicated page — surface the ailment they build, not the raw element
            add(_TAG_AILMENT[tl], f"{skill or 'skill'} is {tl} → its ailment")
            continue
        add(tl, f"{skill or 'skill'} tag: {tl}")
    for k in keystones or []:
        add(k, f"keystone: {k}")
    for a in ascendancy or []:
        add(a, f"ascendancy: {a}")
    for s in _STAPLES:
        add(s, "universal staple")
    return out[:limit]
