"""Parse a Path of Exile 2 item (in-game clipboard or PoB item text) and enrich it.

For each explicit affix we identify its mod group and the *tier* it rolled (T1 = best),
using the bundled corpus' per-tier ranges, and we report open prefix/suffix slots. Tiers and
ranges are looked-up corpus facts — to see how an item affects a build, equip it in the engine
(`equip_item`). This is offline and engine-independent.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from . import db

# A numeric roll or a (signed) "(min-max)" range token -> a single placeholder, so an item line
# like "118% increased Physical Damage" normalizes to the same template as the corpus mod
# "(110-134)% ...", and "+87 to maximum Life" matches "+(70-84) to maximum Life" (the sign may
# sit outside the paren in corpus text, so allow it both before and after "(").
_NUM = re.compile(r"[+\-]?\(?[+\-]?\d[\d.,]*(?:\s*-\s*[+\-]?\d[\d.,]*)?\)?")
_VALUE = re.compile(r"[+\-]?\d[\d.,]*")
# Common words dropped from the candidate-retrieval query (recall only; exact match still uses
# the full normalized text). Keeps discriminative words like "increased"/"reduced".
_STOP = {"to", "of", "the", "a", "an", "and", "per", "with", "you", "your", "is", "are", "on"}
# Affix-kind markers the game appends, e.g. "... (implicit)".
_MARKER = re.compile(
    r"\((implicit|crafted|fractured|enchant|rune|scourge|veiled|desecrated)\)\s*$", re.I
)

# Max prefixes/suffixes by rarity (PoE2). Uniques have fixed mods (no craftable slots).
_AFFIX_LIMITS = {"normal": (0, 0), "magic": (1, 1), "rare": (3, 3)}
# Marker kinds that do NOT consume a prefix/suffix slot.
_NON_AFFIX = {"implicit", "enchant", "rune"}


# RePoE's PoE2 mod text is templated and can drift from in-game wording in case/plural. Bridge
# the common high-value cases so the in-game text matches the corpus template (applied to both
# sides). (Single-element resists used to be stored generically; the corpus now keeps them
# per-element — "+#% to Fire Resistance" — so no resist alias is needed.)
_ALIASES = [
    (re.compile(r"\bto attacks\b"), "to attack"),
]


def _normalize(text: str) -> str:
    t = re.sub(r"\s+", " ", _NUM.sub("#", text)).strip().lower()
    for rx, repl in _ALIASES:
        t = rx.sub(repl, t)
    return t


def _values(text: str) -> list[float]:
    out = []
    for tok in _VALUE.findall(text):
        try:
            out.append(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def _roll_in(ranges: list[dict], nums: list[float]) -> bool:
    rs = [r for r in ranges if r.get("min") is not None and r.get("max") is not None]
    if not rs or len(nums) < len(rs):
        return False
    return all(r["min"] <= n <= r["max"] for r, n in zip(rs, nums))


def _resist_group(line: str) -> str | None:
    """The real group label for a resistance line (the corpus stores single-element resists
    generically, so without this all three would report as 'FireResistance')."""
    low = line.lower()
    if "all elemental resistance" in low:
        return "AllElementalResistance"
    for el in ("fire", "cold", "lightning", "chaos"):
        if f"{el} resistance" in low:
            return el.capitalize() + "Resistance"
    return None


def _range_str(ranges: list[dict]) -> str | None:
    parts = [f"{r['min']}-{r['max']}" for r in ranges if r.get("min") is not None and r.get("max")]
    return " / ".join(parts) if parts else None


def classify_affix(line: str) -> dict[str, Any] | None:
    """Match one affix line to its mod group + tier (T1 = best). None if not recognized."""
    norm = _normalize(line)
    words = [w for w in re.findall(r"[a-z]+", norm) if w not in _STOP] or re.findall(
        r"[a-z]+", norm
    )
    if not words:
        return None
    matches = [
        c for c in db.mods_for_text(" ".join(words), limit=400) if _normalize(c["text"]) == norm
    ]
    if not matches:
        return None
    # craftable affixes only when present (ignore unique-only mods that share the stat text)
    matches = [c for c in matches if c["type"] in ("prefix", "suffix")] or matches
    # collapse RePoE's per-item-class duplicate tiers: one entry per (group, req level, ranges)
    by_group: dict[str, dict[tuple, dict]] = defaultdict(dict)
    for c in matches:
        gkey = (c["groups"] or [""])[0]
        rk = (c["required_level"], tuple((r.get("min"), r.get("max")) for r in c["ranges"]))
        by_group[gkey].setdefault(rk, c)
    nums = _values(line)
    label = _resist_group(line)  # use the real element for resist lines (corpus stores generic)
    fallback: dict[str, Any] | None = None
    for gkey, uniq in by_group.items():
        mods = sorted(uniq.values(), key=lambda m: -(m["required_level"] or 0))  # T1 = highest req
        for idx, m in enumerate(mods):
            if _roll_in(m["ranges"], nums):
                return {
                    "type": m["type"],
                    "tier": idx + 1,
                    "totalTiers": len(mods),
                    "tierRange": _range_str(m["ranges"]),
                    "requiredLevel": m["required_level"],
                    "group": label or gkey,
                }
        if fallback is None and mods:  # recognized but roll out of known ranges (e.g. quality)
            top = mods[0]
            fallback = {
                "type": top["type"],
                "tier": None,
                "totalTiers": len(mods),
                "tierRange": None,
                "requiredLevel": top["required_level"],
                "group": label or gkey,
            }
    return fallback


def _header(lines: list[str]) -> dict[str, Any]:
    info: dict[str, Any] = {
        "rarity": None,
        "name": None,
        "base": None,
        "itemLevel": None,
        "itemClass": None,
    }
    rarity_idx = None
    for i, ln in enumerate(lines):
        low = ln.lower()
        if low.startswith("item class:"):
            info["itemClass"] = ln.split(":", 1)[1].strip()
        elif low.startswith("rarity:"):
            info["rarity"] = ln.split(":", 1)[1].strip()
            rarity_idx = i
        elif low.startswith("item level:") and info["itemLevel"] is None:
            mt = re.search(r"\d+", ln)
            info["itemLevel"] = int(mt.group()) if mt else None
    # name/base = the 1-2 content lines right after "Rarity:" (before the next separator)
    if rarity_idx is not None:
        after = []
        for ln in lines[rarity_idx + 1 :]:
            if set(ln) == {"-"} or not ln:
                break
            after.append(ln)
        if after:
            info["name"] = after[0]
            if len(after) > 1:
                info["base"] = after[1]
            else:
                info["base"] = after[0]
    return info


def parse_item(text: str) -> dict[str, Any]:
    """Parse + enrich an item's clipboard/PoB text. Returns affix tiers and open slots."""
    if not (text or "").strip():
        return {"ok": False, "error": "empty item text"}
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    info = _header([ln.strip() for ln in lines])
    rarity = (info.get("rarity") or "").lower()

    skip = {info.get("name"), info.get("base")}
    affixes: list[dict[str, Any]] = []
    unrecognized: list[str] = []
    pre = suf = 0
    for ln in lines:
        s = ln.strip()
        if not s or set(s) == {"-"} or ":" in s or s in skip:
            continue  # separators, properties/requirements, and the name/base lines
        kind = "explicit"
        mk = _MARKER.search(s)
        if mk:
            kind = mk.group(1).lower()
            s = _MARKER.sub("", s).strip()
        info_affix = classify_affix(s)
        if not info_affix:
            unrecognized.append(s)
            continue
        entry = {"text": s, "kind": kind, **info_affix}
        affixes.append(entry)
        if kind not in _NON_AFFIX:
            if info_affix["type"] == "prefix":
                pre += 1
            elif info_affix["type"] == "suffix":
                suf += 1

    out: dict[str, Any] = {
        "ok": True,
        "rarity": info.get("rarity"),
        "name": info.get("name"),
        "base": info.get("base"),
        "itemClass": info.get("itemClass"),
        "itemLevel": info.get("itemLevel"),
        "affixes": affixes,
        "note": (
            "Tier (T1 = best) and ranges are corpus facts; equip_item to see the actual build "
            "impact. Affix detection is best-effort — see `unrecognized` for unmatched lines."
        ),
    }
    if unrecognized:
        out["unrecognized"] = unrecognized
    limits = _AFFIX_LIMITS.get(rarity)
    if limits:
        out["prefixes"], out["suffixes"] = pre, suf
        out["openPrefixes"], out["openSuffixes"] = max(0, limits[0] - pre), max(0, limits[1] - suf)
    if rarity == "unique" and info.get("name"):
        u = db.get_unique(info["name"])
        if u:
            out["unique"] = {"base": u["base"], "text": u["text"]}
    return out


def audit_item_legality(text: str) -> dict[str, Any]:
    """Audit deterministic rare/magic affix constraints without exposing raw item text."""
    parsed = parse_item(text)
    if not parsed.get("ok"):
        return {"ok": False, "issues": ["item_parse_failed"]}
    rarity = str(parsed.get("rarity") or "").lower()
    if rarity not in {"rare", "magic"}:
        return {"ok": True, "issues": []}

    issues: list[str] = []
    limits = _AFFIX_LIMITS[rarity]
    prefixes = int(parsed.get("prefixes") or 0)
    suffixes = int(parsed.get("suffixes") or 0)
    if prefixes > limits[0]:
        issues.append("prefix_limit_exceeded")
    if suffixes > limits[1]:
        issues.append("suffix_limit_exceeded")

    groups: dict[str, int] = defaultdict(int)
    item_level = parsed.get("itemLevel")
    over_item_level: list[dict[str, Any]] = []
    for affix in parsed.get("affixes") or []:
        if affix.get("kind") in _NON_AFFIX:
            continue
        group = str(affix.get("group") or "").strip()
        if group:
            groups[group] += 1
        required = affix.get("requiredLevel")
        if isinstance(item_level, int) and isinstance(required, int) and required > item_level:
            over_item_level.append({"group": group or "unknown", "requiredLevel": required})
    duplicate_groups = sorted(group for group, count in groups.items() if count > 1)
    if duplicate_groups:
        issues.append("duplicate_affix_group")
    if over_item_level:
        issues.append("affix_item_level_requirement_unmet")
    out_of_range = [
        str(affix.get("group") or "unknown")
        for affix in parsed.get("affixes") or []
        if affix.get("kind") not in _NON_AFFIX and affix.get("tier") is None
    ]
    if out_of_range:
        issues.append("affix_roll_outside_known_tiers")

    base = str(parsed.get("base") or "").strip()
    affix_lines = [
        str(affix.get("text") or "")
        for affix in parsed.get("affixes") or []
        if affix.get("kind") not in _NON_AFFIX
    ]
    base_illegal = db.illegal_affixes(base, affix_lines) if base and affix_lines else []
    if base_illegal:
        issues.append("affix_not_allowed_on_base")

    return {
        "ok": not issues,
        "issues": issues,
        "prefixes": prefixes,
        "suffixes": suffixes,
        "duplicateGroups": duplicate_groups,
        "overItemLevelAffixes": over_item_level,
        "outOfRangeGroups": out_of_range,
        "baseIllegalAffixCount": len(base_illegal),
        "unrecognizedAffixCount": len(parsed.get("unrecognized") or []),
    }
