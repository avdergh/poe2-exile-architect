"""Parse a Path of Exile 2 item (in-game clipboard or PoB item text) and enrich it.

For each explicit affix we identify its mod group and the *tier* it rolled (T1 = best),
using the bundled corpus' per-tier ranges, and we report open prefix/suffix slots. Tiers and
ranges are looked-up corpus facts — to see how an item affects a build, equip it in the engine
(`equip_item`). This is offline and engine-independent.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
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
_PREFIX_MARKER = re.compile(
    r"^\{(implicit|crafted|fractured|enchant|rune|scourge|veiled|desecrated)\}",
    re.I,
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


def _display_ranges(text: str) -> list[dict[str, float]]:
    """Read the human-facing ranges from a corpus mod template.

    Most RePoE ranges use the same units as the displayed item line, but a few weapon stats use
    internal fixed-point units (for example 4.41-5% local critical chance is stored as 441-500).
    The template itself remains the authoritative display range for matching clipboard text.
    """
    out: list[dict[str, float]] = []
    for token in _NUM.findall(text):
        raw = token.replace(",", "").strip()
        outer_sign = -1.0 if raw.startswith("-(") else 1.0
        if len(raw) > 1 and raw[0] in "+-" and raw[1] == "(":
            raw = raw[1:]
        raw = raw.strip("()")
        match = re.fullmatch(
            r"([+\-]?\d+(?:\.\d+)?)\s*-\s*([+\-]?\d+(?:\.\d+)?)",
            raw,
        )
        try:
            if match:
                values = [outer_sign * float(match.group(1)), outer_sign * float(match.group(2))]
            else:
                values = [outer_sign * float(raw)]
        except ValueError:
            continue
        out.append({"min": min(values), "max": max(values)})
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


def classify_affix(line: str, *, base_name: str | None = None) -> dict[str, Any] | None:
    """Match one affix line to its mod group + tier (T1 = best). None if not recognized.

    When a base is known, restrict tier candidates to mods that can actually roll on that base.
    Several weapon families share display text while using different, overlapping tier ranges; a
    base-agnostic match can otherwise assign a legal low-level roll to a higher-level tier from a
    different weapon family.
    """
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
    if base_name:
        base_matches = [
            c
            for c in matches
            if db.mod_tags_match_base(
                base_name,
                c.get("tags") or [],
                mod_domain=str(c.get("domain") or "") or None,
            )
        ]
        # Unknown/legacy bases retain the conservative generic classifier. For a recognized base,
        # use only its real spawn-tag candidates so overlapping weapon-family tiers cannot leak in.
        if db.get_item(base_name) is not None:
            matches = base_matches
        if not matches:
            return None
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
            matched_ranges = m["ranges"]
            matched = _roll_in(matched_ranges, nums)
            display_ranges = _display_ranges(m["text"])
            # Some corpus mods contain hidden/internal values that do not appear in the rendered
            # item text (for example an instant-recovery flag plus one visible recovery penalty).
            # Once the normalized display template is an exact match, its visible ranges are the
            # authoritative comparison for clipboard/PoB text even when the internal range count
            # differs.
            if not matched and display_ranges and _roll_in(display_ranges, nums):
                matched_ranges = display_ranges
                matched = True
            # Fixed display affixes can encode an internal numeric value while rendering no
            # number at all (for example "Upgrades Radius to Large").  The exact normalized
            # text match above is sufficient for these lines; requiring the hidden value to be
            # present in clipboard text incorrectly marks the known affix as out of range.
            if not matched and not nums and not display_ranges:
                matched_ranges = []
                matched = True
            if matched:
                return {
                    "type": m["type"],
                    "tier": idx + 1,
                    "totalTiers": len(mods),
                    "tierRange": _range_str(matched_ranges),
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
            if set(ln) == {"-"} or not ln or ":" in ln:
                break
            after.append(ln)
        if after:
            info["name"] = after[0]
            info["base"] = after[1] if len(after) > 1 else after[0]
    return info


def line_fingerprint(text: str) -> str:
    """Return an exact-roll, whitespace-stable fingerprint for one item effect line."""

    normalized = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def semantic_item_structure(text: str) -> dict[str, Any]:
    """Parse the structural sources in PoB item text without persisting the raw text."""

    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").split("\n")]
    stripped = [line.strip() for line in lines]
    info = _header(stripped)
    effects = _structured_effect_lines(lines, info)
    rune_names = [
        value for line in stripped if (value := _property_value(line, r"^Rune:\s*(.+)")) is not None
    ]
    socket_line = next(
        (
            value
            for line in stripped
            if (value := _property_value(line, r"^Sockets:\s*(.*)")) is not None
        ),
        "",
    )
    corrupted = any(line.casefold() == "corrupted" for line in stripped)
    canonical = {
        "schemaVersion": 1,
        "rarity": str(info.get("rarity") or "").strip().casefold(),
        "base": str(info.get("base") or "").strip().casefold(),
        "itemLevel": info.get("itemLevel"),
        "corrupted": corrupted,
        "runeSockets": sum(1 for token in socket_line.split() if token == "S"),
        "runeNames": sorted(re.sub(r"\s+", " ", name).strip().casefold() for name in rune_names),
        "effects": sorted(
            [
                {
                    "kind": str(entry["kind"]),
                    "lineFingerprint": line_fingerprint(str(entry["text"])),
                }
                for entry in effects
            ],
            key=lambda entry: (entry["kind"], entry["lineFingerprint"]),
        ),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "rarity": info.get("rarity"),
        "base": info.get("base"),
        "itemLevel": info.get("itemLevel"),
        "corrupted": corrupted,
        "runeSockets": canonical["runeSockets"],
        "runeNames": rune_names,
        "effects": [
            {
                **entry,
                "lineFingerprint": line_fingerprint(str(entry["text"])),
            }
            for entry in effects
        ],
        "itemFingerprint": "sha256:" + hashlib.sha256(encoded).hexdigest(),
    }


def _structured_effect_lines(
    lines: list[str],
    info: dict[str, Any],
) -> list[dict[str, str]]:
    stripped = [line.strip() for line in lines]
    implicit_indices: set[int] = set()
    remaining = 0
    for index, value in enumerate(stripped):
        match = re.match(r"^Implicits:\s*(\d+)\s*$", value, re.IGNORECASE)
        if match:
            remaining = int(match.group(1))
            continue
        if remaining and value and set(value) != {"-"}:
            implicit_indices.add(index)
            remaining -= 1

    skip = {str(info.get("name") or ""), str(info.get("base") or "")}
    output: list[dict[str, str]] = []
    for index, raw_line in enumerate(lines):
        value = raw_line.strip()
        if not value or set(value) == {"-"} or value in skip:
            continue
        if value.casefold() == "corrupted":
            continue

        kind = "implicit" if index in implicit_indices else "explicit"
        prefix = _PREFIX_MARKER.match(value)
        if prefix:
            kind = prefix.group(1).lower()
            value = _PREFIX_MARKER.sub("", value).strip()
        suffix = _MARKER.search(value)
        if suffix:
            kind = suffix.group(1).lower()
            value = _MARKER.sub("", value).strip()

        if index not in implicit_indices and ":" in value and prefix is None and suffix is None:
            continue
        if not value:
            continue
        output.append({"text": value, "kind": kind})
    return output


def _property_value(line: str, pattern: str) -> str | None:
    match = re.match(pattern, line, re.IGNORECASE)
    return match.group(1).strip() if match else None


def parse_item(text: str) -> dict[str, Any]:
    """Parse + enrich an item's clipboard/PoB text. Returns affix tiers and open slots."""
    if not (text or "").strip():
        return {"ok": False, "error": "empty item text"}
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    info = _header([ln.strip() for ln in lines])
    rarity = (info.get("rarity") or "").lower()

    affix_lines = [
        (str(entry["text"]), str(entry["kind"])) for entry in _structured_effect_lines(lines, info)
    ]

    # Some real PoE2 affixes are two or three display lines backed by one mod group.  Parsing each
    # line independently can turn one legal hybrid prefix into two prefixes (or assign a sub-line
    # to the wrong tier/group), causing completeness to reject gear generated from the real pool.
    # Prefer the longest consecutive corpus match, then fall back to a single-line match.
    affixes: list[dict[str, Any]] = []
    unrecognized: list[str] = []
    pre = suf = 0
    index = 0
    while index < len(affix_lines):
        info_affix = None
        matched_text = affix_lines[index][0]
        matched_kind = affix_lines[index][1]
        matched_width = 1
        for width in range(min(3, len(affix_lines) - index), 0, -1):
            chunk = affix_lines[index : index + width]
            if any(kind != matched_kind for _text, kind in chunk):
                continue
            combined = "\n".join(text for text, _kind in chunk)
            classified = classify_affix(combined, base_name=info.get("base"))
            # A numeric miss on a multi-line template can mean two independent adjacent affixes
            # merely share the same words as a hybrid mod.  Only merge multi-line text when the
            # rolls fit one real tier; retain the single-line fallback so true out-of-range rolls
            # are still reported.
            if classified and (width == 1 or classified.get("tier") is not None):
                info_affix = classified
                matched_text = combined
                matched_width = width
                break
        if not info_affix:
            unrecognized.append(matched_text)
            index += 1
            continue
        entry = {
            "text": matched_text,
            "kind": matched_kind,
            "lineFingerprint": line_fingerprint(matched_text),
            **info_affix,
        }
        affixes.append(entry)
        if matched_kind not in _NON_AFFIX:
            if info_affix["type"] == "prefix":
                pre += 1
            elif info_affix["type"] == "suffix":
                suf += 1
        index += matched_width

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


def audit_item_legality(
    text: str,
    *,
    trusted_provenance: dict[str, Any] | None = None,
    require_special_provenance: bool = False,
) -> dict[str, Any]:
    """Audit rare/magic item legality with optional PoB-issued special-source evidence."""

    parsed = parse_item(text)
    if not parsed.get("ok"):
        return {"ok": False, "issues": ["item_parse_failed"]}
    rarity = str(parsed.get("rarity") or "").lower()

    craft_profile = db.craft_profile(str(parsed.get("base") or ""))
    domain_rarity_issue = bool(
        craft_profile
        and str(craft_profile.get("domain") or "") == "flask"
        and rarity != str(craft_profile.get("rarity") or "").casefold()
    )

    structure = semantic_item_structure(text)
    provenance = trusted_provenance if isinstance(trusted_provenance, dict) else None
    source_issues: list[str] = []
    sources = provenance.get("sources") if provenance is not None else None
    if not isinstance(sources, dict):
        sources = {}
    accepted_fingerprints = (
        {str(value) for value in (provenance.get("acceptedItemFingerprints") or []) if value}
        if provenance is not None
        else set()
    )
    if provenance is not None and not accepted_fingerprints:
        accepted_fingerprints = {str(provenance.get("itemFingerprint") or "")}
    if provenance is not None and structure["itemFingerprint"] not in accepted_fingerprints:
        source_issues.append("craft_receipt_item_mismatch")

    essence_entries = [
        entry for entry in (sources.get("perfectEssences") or []) if isinstance(entry, dict)
    ]
    essence_hashes = {
        str(entry.get("lineFingerprint") or "")
        for entry in essence_entries
        if entry.get("lineFingerprint")
    }
    effects = [entry for entry in structure.get("effects") or [] if isinstance(entry, dict)]
    all_effect_hashes = [str(entry.get("lineFingerprint") or "") for entry in effects]
    rune_hashes = sorted(
        str(entry.get("lineFingerprint") or "") for entry in effects if entry.get("kind") == "rune"
    )
    if essence_hashes - set(all_effect_hashes):
        source_issues.append("craft_receipt_essence_effect_missing")

    receipt_runes = [entry for entry in (sources.get("runes") or []) if isinstance(entry, dict)]
    receipt_rune_hashes = sorted(
        str(fingerprint)
        for entry in receipt_runes
        for fingerprint in (entry.get("lineFingerprints") or [])
    )
    canonical_receipt_rune_hashes = sorted(
        str(fingerprint) for fingerprint in (sources.get("canonicalRuneLineFingerprints") or [])
    )
    receipt_rune_names = sorted(
        str(entry.get("name") or "").strip().casefold() for entry in receipt_runes
    )
    actual_rune_names = sorted(
        str(name).strip().casefold() for name in structure.get("runeNames") or []
    )
    original_runes_match = all(
        count <= Counter(all_effect_hashes)[fingerprint]
        for fingerprint, count in Counter(receipt_rune_hashes).items()
    )
    canonical_runes_match = bool(canonical_receipt_rune_hashes) and all(
        count <= Counter(all_effect_hashes)[fingerprint]
        for fingerprint, count in Counter(canonical_receipt_rune_hashes).items()
    )
    if provenance is not None and (
        (receipt_runes and not (original_runes_match or canonical_runes_match))
        or (actual_rune_names and actual_rune_names != receipt_rune_names)
    ):
        source_issues.append("craft_receipt_rune_mismatch")

    corruption = sources.get("corruption")
    if corruption is not None and not isinstance(corruption, dict):
        source_issues.append("craft_receipt_corruption_invalid")
        corruption = None
    if isinstance(corruption, dict):
        corruption_hash = str(corruption.get("lineFingerprint") or "")
        if (
            not corruption_hash
            or corruption_hash not in set(all_effect_hashes)
            or structure.get("corrupted") is not True
        ):
            source_issues.append("craft_receipt_corruption_mismatch")
    elif provenance is not None and structure.get("corrupted"):
        source_issues.append("craft_receipt_corruption_missing")

    has_structural_special = bool(rune_hashes or actual_rune_names or structure.get("corrupted"))
    if provenance is None and require_special_provenance and has_structural_special:
        source_issues.append("special_source_provenance_required")

    receipt_corruption_hash = (
        str(corruption.get("lineFingerprint") or "") if isinstance(corruption, dict) else ""
    )
    special_non_affix_hashes = {
        *receipt_rune_hashes,
        *canonical_receipt_rune_hashes,
        *([receipt_corruption_hash] if receipt_corruption_hash else []),
    }
    all_source_hashes = essence_hashes | special_non_affix_hashes

    issues: list[str] = list(source_issues)
    if domain_rarity_issue:
        issues.append("rarity_not_allowed_for_base_domain")
    if rarity not in {"rare", "magic"}:
        issues = list(dict.fromkeys(issues))
        result = {
            "ok": not issues,
            "issues": issues,
            "prefixes": 0,
            "suffixes": 0,
            "duplicateGroups": [],
            "overItemLevelAffixes": [],
            "outOfRangeGroups": [],
            "baseIllegalAffixCount": 0,
            "unrecognizedAffixCount": 0,
        }
        if provenance is not None:
            result["craftReceiptRef"] = provenance.get("receiptRef")
            result["provenanceStatus"] = "verified" if not source_issues else "rejected"
            result["specialSources"] = {
                "perfectEssenceCount": len(essence_entries),
                "runeCount": len(receipt_runes),
                "corruptionVerified": isinstance(corruption, dict),
            }
        elif has_structural_special:
            result["provenanceStatus"] = "unverified"
            result["unverifiedSpecialSources"] = [
                *([] if not (rune_hashes or actual_rune_names) else ["rune"]),
                *([] if not structure.get("corrupted") else ["corruption"]),
            ]
        return result
    limits = _AFFIX_LIMITS[rarity]
    parsed_affixes = [
        affix
        for affix in (parsed.get("affixes") or [])
        if isinstance(affix, dict)
        and affix.get("kind") not in _NON_AFFIX
        and str(affix.get("lineFingerprint") or "") not in all_source_hashes
    ]
    prefixes = sum(1 for affix in parsed_affixes if affix.get("type") == "prefix")
    suffixes = sum(1 for affix in parsed_affixes if affix.get("type") == "suffix")
    prefixes += sum(1 for entry in essence_entries if entry.get("affixType") == "prefix")
    suffixes += sum(1 for entry in essence_entries if entry.get("affixType") == "suffix")
    if prefixes > limits[0]:
        issues.append("prefix_limit_exceeded")
    if suffixes > limits[1]:
        issues.append("suffix_limit_exceeded")

    groups: dict[str, int] = defaultdict(int)
    item_level = parsed.get("itemLevel")
    over_item_level: list[dict[str, Any]] = []
    for affix in parsed_affixes:
        group = str(affix.get("group") or "").strip()
        if group:
            groups[group] += 1
        required = affix.get("requiredLevel")
        if isinstance(item_level, int) and isinstance(required, int) and required > item_level:
            over_item_level.append({"group": group or "unknown", "requiredLevel": required})
    for entry in essence_entries:
        group = str(entry.get("group") or "").strip()
        if group:
            groups[group] += 1
        required = entry.get("requiredLevel")
        if isinstance(item_level, int) and isinstance(required, int) and required > item_level:
            over_item_level.append({"group": group or "unknown", "requiredLevel": required})
    duplicate_groups = sorted(group for group, count in groups.items() if count > 1)
    if duplicate_groups:
        issues.append("duplicate_affix_group")
    if over_item_level:
        issues.append("affix_item_level_requirement_unmet")
    out_of_range = [
        str(affix.get("group") or "unknown")
        for affix in parsed_affixes
        if affix.get("tier") is None
    ]
    if out_of_range:
        issues.append("affix_roll_outside_known_tiers")

    base = str(parsed.get("base") or "").strip()
    natural_explicit_lines = [
        str(entry.get("text") or "")
        for entry in effects
        if entry.get("kind") == "explicit"
        and str(entry.get("lineFingerprint") or "") not in all_source_hashes
        and str(entry.get("text") or "")
    ]
    base_illegal = (
        db.illegal_affixes(base, natural_explicit_lines) if base and natural_explicit_lines else []
    )
    if base_illegal:
        issues.append("affix_not_allowed_on_base")

    unrecognized = [
        value
        for value in (parsed.get("unrecognized") or [])
        if line_fingerprint(str(value)) not in all_source_hashes
    ]
    issues = list(dict.fromkeys(issues))
    result = {
        "ok": not issues,
        "issues": issues,
        "prefixes": prefixes,
        "suffixes": suffixes,
        "duplicateGroups": duplicate_groups,
        "overItemLevelAffixes": over_item_level,
        "outOfRangeGroups": out_of_range,
        "baseIllegalAffixCount": len(base_illegal),
        "unrecognizedAffixCount": len(unrecognized),
    }
    if provenance is not None:
        result["craftReceiptRef"] = provenance.get("receiptRef")
        result["provenanceStatus"] = "verified" if not source_issues else "rejected"
        result["specialSources"] = {
            "perfectEssenceCount": len(essence_entries),
            "runeCount": len(receipt_runes),
            "corruptionVerified": isinstance(corruption, dict),
        }
    elif has_structural_special:
        result["provenanceStatus"] = "unverified"
        result["unverifiedSpecialSources"] = [
            *([] if not (rune_hashes or actual_rune_names) else ["rune"]),
            *([] if not structure.get("corrupted") else ["corruption"]),
        ]
    return result
