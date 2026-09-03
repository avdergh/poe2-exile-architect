"""Leveled-build kernel: verify a direction against the target level (constraint layer).

Three-layer design for Create with sparse Research recall:
  - DIRECTION layer (external Agent web research + model knowledge) picks the playstyle and
    skill/gear direction — this module never invents direction.
  - CONSTRAINT layer (this module) verifies the direction at the target level: gem level
    requirements come from the PoB engine (the corpus has no reliable gem level data), base
    drop levels and affix required levels come from the corpus.
  - NUMERIC layer (PoB readback / Judge) remains the authority for every number.

The engine calls here are read-only (snapshot/restore inside the bridge); this module never
mutates the active build.
"""

from __future__ import annotations

from typing import Any

from ..knowledge import db
from ..knowledge.skill_equivalence import SkillEquivalenceIndex

_GEAR_CLASSES = {
    "Body Armour": "Body Armour",
    "Helmet": "Helmet",
    "Gloves": "Gloves",
    "Boots": "Boots",
    "Belt": "Belt",
    "Amulet": "Amulet",
    "Ring 1": "Ring",
    "Ring 2": "Ring",
}


def _gem_identity_for_key(key: str) -> dict[str, Any]:
    """Resolve display, gem and active-skill identities at the level-verification boundary."""

    key = str(key or "").strip()
    if not key:
        return {"status": "unavailable", "reason": "empty_skill_identity"}
    index = SkillEquivalenceIndex.shared()
    gem: dict[str, Any] | None = None
    if key.startswith("gem:"):
        gem = db.get_gem(key[len("gem:") :])
    elif key.startswith("skill:"):
        gem_ids = index.gem_ids_for_skill_key(key)
        if len(gem_ids) > 1:
            return {
                "status": "ambiguous",
                "reason": "active_skill_granted_by_multiple_gems",
                "candidateGemKeys": [f"gem:{gem_id}" for gem_id in gem_ids],
            }
        gem = db.get_gem(gem_ids[0]) if gem_ids else None
    else:
        gem_ids = index.gem_ids(key)
        if len(gem_ids) > 1:
            return {
                "status": "ambiguous",
                "reason": "gem_display_name_is_ambiguous",
                "candidateGemKeys": [f"gem:{gem_id}" for gem_id in gem_ids],
            }
        gem = db.get_gem(gem_ids[0]) if gem_ids else db.get_gem(key)
    if gem is None:
        return {
            "status": "unavailable",
            "reason": (
                "unresolvable_skill_identity"
                if key.startswith("skill:")
                else "gem_not_found_in_corpus"
            ),
        }
    active_keys = [f"skill:{value}" for value in (gem.get("grants") or []) if value]
    return {
        "status": "resolved",
        "gemName": str(gem["name"]),
        "gemKey": f"gem:{gem['id']}",
        "activeSkillKeys": active_keys,
    }


def _gem_level_curve(engine: Any, gem_name: str) -> dict[str, Any] | None:
    try:
        result = engine.gem_level_requirements(gem_name)
    except Exception:
        return None
    if not isinstance(result, dict) or not result.get("found"):
        return None
    return result


def gem_level_availability(engine: Any, gem_name: str, level: int) -> dict[str, Any]:
    """Whether one gem is usable at `level` (ok / partial / unavailable) per the PoB curve."""
    target = int(level)
    curve = _gem_level_curve(engine, gem_name)
    if curve is None:
        return {
            "skill": gem_name,
            "status": "unavailable",
            "reason": "gem_not_found_in_engine",
        }
    max_legal_level: int | None = None
    for entry in curve.get("levels") or []:
        if not isinstance(entry, dict):
            continue
        requirement = entry.get("levelRequirement")
        if isinstance(requirement, (int, float)) and int(requirement) <= target:
            candidate = int(entry.get("level") or 0)
            if max_legal_level is None or candidate > max_legal_level:
                max_legal_level = candidate
    natural_max = int(curve.get("naturalMaxLevel") or 0)
    if max_legal_level is None or max_legal_level <= 0:
        return {
            "skill": gem_name,
            "status": "unavailable",
            "reason": "level_requirement_exceeds_target",
            "naturalMaxLevel": natural_max or None,
        }
    return {
        "skill": gem_name,
        "status": "ok" if natural_max == 0 or max_legal_level >= natural_max else "partial",
        "maxLegalLevel": max_legal_level,
        "naturalMaxLevel": natural_max or None,
    }


def _attribute_compatible_for_class(gem_name: str, class_key: str) -> bool:
    """Corpus-level attribute check (requirement_weights vs class dominant attribute)."""
    mapping = db.class_attribute_mapping()
    entry = mapping.get(str(class_key))
    if entry is None:
        return True
    gem = db.get_gem(gem_name)
    if not gem:
        return True
    return db.attribute_compatible(gem.get("requirement_weights"), entry["attribute"])


def validate_level_availability(
    engine: Any,
    skill_keys: list[str],
    level: int,
    class_key: str | None = None,
) -> dict[str, Any]:
    """Verify each candidate skill at `level`. Reference for the direction layer, not a hard gate.

    Every number here is a constraint-layer hint: the PoB readback / Judge remain authoritative.
    """
    results: list[dict[str, Any]] = []
    for key in skill_keys or []:
        identity = _gem_identity_for_key(key)
        if identity.get("status") != "resolved":
            results.append(
                {
                    "skill": str(key),
                    **identity,
                }
            )
            continue
        gem_name = str(identity["gemName"])
        entry = gem_level_availability(engine, gem_name, level)
        entry["skill"] = str(key)
        entry.update({name: value for name, value in identity.items() if name != "status"})
        entry["attributeCompatible"] = (
            _attribute_compatible_for_class(gem_name, class_key) if class_key else True
        )
        if entry["status"] == "ok" and not entry["attributeCompatible"]:
            entry["status"] = "partial"
            entry["reason"] = "attribute_mismatch"
        results.append(entry)
    return {
        "level": int(level),
        "classKey": class_key,
        "results": results,
        "note": (
            "Constraint-layer reference only: gem level curves come from PoB, attribute "
            "compatibility from the corpus; final legality and numbers come from PoB readback."
        ),
    }


def leveled_skill_pool(
    engine: Any,
    level: int,
    class_key: str | None = None,
    gem_type: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """Candidate skills usable at `level`: corpus soft filter + engine level verification."""
    candidates: list[dict[str, Any]] = []
    for gem in db.list_gems_for_level(
        level=level, gem_type=gem_type, class_key=class_key, limit=limit
    ):
        name = str(gem.get("name") or "")
        if not name:
            continue
        entry = gem_level_availability(engine, name, int(level))
        if entry["status"] == "unavailable":
            continue
        entry["craftingLevel"] = gem.get("crafting_level")
        entry["craftingTypes"] = gem.get("crafting_types")
        entry["supports"] = gem.get("supports") or []
        entry["attributeCompatible"] = (
            _attribute_compatible_for_class(name, class_key) if class_key else True
        )
        candidates.append(entry)
        if len(candidates) >= int(limit):
            break
    return {
        "level": int(level),
        "classKey": class_key,
        "gemType": gem_type,
        "candidates": candidates,
        "note": (
            "Candidate pool for the direction layer; true level legality is re-verified by PoB "
            "during assembly (set_skill auto-selects the legal gem level)."
        ),
    }


def level_gear_scope(level: int) -> dict[str, Any]:
    """Eligible item bases per armour/jewellery slot at `level` (drop_level ≤ level).

    Note: corpus base tags are composite (e.g. ``str_dex_armour``), so attribute-preference base
    selection mostly falls back to the highest drop_level — scope is intentionally drop-level only.
    Affix availability is handled by ``db.affix_pool(base, ilvl=level)`` which already filters
    ``required_level <= ilvl``.
    """
    target = int(level)
    scope: dict[str, Any] = {}
    for slot, item_class in _GEAR_CLASSES.items():
        bases = db.search_items(item_class=item_class, limit=100, max_drop_level=target)
        eligible = [
            {"name": str(base.get("name") or ""), "dropLevel": int(base.get("drop_level") or 0)}
            for base in bases
        ]
        scope[slot] = {
            "itemClass": item_class,
            "baseCount": len(eligible),
            "eligibleBases": eligible[:5],
        }
    return {
        "level": target,
        "slots": scope,
        "affixNote": "affix required_level ≤ level is enforced by db.affix_pool(base, ilvl=level)",
        "note": (
            "Drop-level filter only; the corpus has no per-class attribute base preference that "
            "reliably holds (composite tags). Numbers come from PoB readback."
        ),
    }
