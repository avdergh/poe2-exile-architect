"""Cheap, raw-free checks before a generation snapshot consumes a Judge attempt."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any
import xml.etree.ElementTree as ET

from server.compute import completeness
from server.judge import hard_legality, rules


def inspect_generation_preflight(
    engine: Any,
    *,
    strict_mode: bool = False,
) -> dict[str, Any]:
    try:
        xml = engine.get_xml()
    except Exception:  # noqa: BLE001 - public diagnostics must not expose engine internals.
        return _error("active_build_snapshot_failed")
    return project_feedback(
        inspect_generation_snapshot(engine, xml),
        strict_mode=strict_mode,
    )


def project_feedback(result: dict[str, Any], *, strict_mode: bool) -> dict[str, Any]:
    """Return one public preflight view without changing the internal hard audit."""

    projected = deepcopy(result)
    projected["feedbackMode"] = "strict" if strict_mode else "hard_only"
    projected["subjectiveFeedbackSuppressed"] = not strict_mode
    if strict_mode:
        return projected
    projected["qualityAdvisories"] = []
    projected["advisories"] = []
    if projected.get("readyForJudge"):
        projected["status"] = "ready"
    completeness_result = projected.get("completeness")
    if isinstance(completeness_result, dict):
        completeness_result["advisories"] = []
        completeness_result["status"] = (
            "complete" if not completeness_result.get("hardFailures") else "needs_attention"
        )
    return projected


def inspect_generation_snapshot(
    engine: Any,
    xml: str,
    *,
    completeness_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect the exact XML that will be sent to the dedicated Judge engine."""
    parsed = _parse_skill_groups(xml)
    if parsed.get("errorCode"):
        return _error(str(parsed["errorCode"]))

    blocking: list[str] = []
    group_diagnostics: list[dict[str, Any]] = []
    signatures: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for group in parsed["groups"]:
        issues: list[str] = []
        active_ids = list(group["activeIds"])
        support_ids = list(group["supportIds"])
        if len(active_ids) != 1:
            issues.append("invalid_socket_setup")
            blocking.append("invalid_socket_setup")
        if len(support_ids) != len(set(support_ids)):
            issues.append("duplicate_support_gem")
            blocking.append("duplicate_support_gem")
        signatures.append((tuple(sorted(active_ids)), tuple(sorted(support_ids))))
        group_diagnostics.append(
            {
                "groupIndex": group["groupIndex"],
                "role": group["role"],
                "activeSkills": group["activeNames"],
                "supports": group["supportNames"],
                "issues": issues,
            }
        )

    signature_counts = Counter(signatures)
    duplicate_indices = [
        group_diagnostics[index]["groupIndex"]
        for index, signature in enumerate(signatures)
        if signature_counts[signature] > 1
    ]
    if duplicate_indices:
        blocking.append("duplicate_enabled_skill_group")

    complete = (
        completeness_result
        if completeness_result is not None
        else completeness.inspect_build_completeness(engine, snapshot_xml=xml)
    )
    completeness_failures = [str(value) for value in complete.get("hardFailures") or []]
    try:
        build = hard_legality.augment_build_with_snapshot_gear(engine.get_build(), xml)
        legality = hard_legality.audit_build(build)
        get_defenses = getattr(engine, "get_defenses", None)
        defenses = get_defenses() if callable(get_defenses) else {}
    except Exception:  # noqa: BLE001 - preflight fails closed without exposing engine details.
        return _error("hard_legality_audit_failed")
    legality_failures = [str(value) for value in legality.get("hardFailures") or []]
    resistance_gate = rules.check_endgame_resistance_gate(
        level=build.get("level"),
        resistances=(defenses.get("resistances") or {}) if isinstance(defenses, dict) else {},
        keystones=build.get("keystones"),
    )
    readiness_failures = [str(value) for value in resistance_gate["hardFailures"]]
    mechanism_blockers = _dedupe(
        [
            *blocking,
            *[value for value in completeness_failures if value not in legality_failures],
        ]
    )
    blocking = _dedupe([*mechanism_blockers, *legality_failures, *readiness_failures])
    advisories = [str(value) for value in complete.get("advisories") or []]
    return {
        "status": "blocked" if blocking else ("needs_attention" if advisories else "ready"),
        "readyForJudge": not blocking,
        "blockingIssues": blocking,
        "hardLegality": legality,
        "hardLegalityReady": bool(legality.get("hardLegalityReady")),
        "mechanismReady": not mechanism_blockers,
        "mechanismBlockers": mechanism_blockers,
        "readinessReady": not readiness_failures,
        "readinessGates": {"endgameResistances": resistance_gate},
        "qualityAdvisories": advisories,
        "advisories": advisories,
        "duplicateGroupIndices": duplicate_indices,
        "skillGroups": group_diagnostics,
        "completeness": {
            "status": complete.get("status"),
            "hardFailures": complete.get("hardFailures") or [],
            "advisories": advisories,
        },
        "noRawMaterial": True,
    }


def inspect_main_skill_socketed(xml: str) -> dict[str, Any]:
    """Return bounded evidence that the active PoB main group has one enabled active gem.

    Lifecycle verification calls this against the exact XML snapshot whose hash it reports.
    Keeping the check here ensures the Phase 5 preflight and lifecycle gate interpret socket
    groups identically without accepting a caller-supplied boolean as proof.
    """
    parsed = _parse_skill_groups(xml)
    if parsed.get("errorCode"):
        return {
            "status": "failed",
            "socketed": False,
            "errorCode": str(parsed["errorCode"]),
            "activeSkillCount": 0,
        }
    main_group = next(
        (group for group in parsed["groups"] if group["role"] == "pob_main_group"),
        None,
    )
    active_count = len(main_group["activeIds"]) if main_group else 0
    socketed = active_count == 1
    return {
        "status": "passed" if socketed else "failed",
        "socketed": socketed,
        "groupIndex": main_group["groupIndex"] if main_group else None,
        "activeSkillCount": active_count,
        "activeSkills": list(main_group["activeNames"])[:2] if main_group else [],
    }


def inspect_lifecycle_skill_evidence(
    xml: str,
    *,
    single_target_skill_name: str | None = None,
) -> dict[str, Any]:
    """Read bounded lifecycle skill/ascendancy evidence from one active XML snapshot."""
    parsed = _parse_skill_groups(xml)
    if parsed.get("errorCode"):
        return {
            "status": "failed",
            "errorCode": str(parsed["errorCode"]),
            "ascendancyOrKeySupport": {"verified": False},
            "singleTargetDuty": {"verified": False},
        }
    main_group = next(
        (group for group in parsed["groups"] if group["role"] == "pob_main_group"),
        None,
    )
    ascendancy = str(parsed.get("ascendancy") or "").strip()
    ascendancy_active = bool(ascendancy and ascendancy.casefold() not in {"none", "unascended"})
    support_count = len(main_group["supportIds"]) if main_group else 0

    requested = str(single_target_skill_name or "").strip()
    matched_group = None
    matched_skill = ""
    if requested:
        for group in parsed["groups"]:
            for skill_name in group["activeNames"]:
                if str(skill_name).strip().casefold() == requested.casefold():
                    matched_group = group
                    matched_skill = str(skill_name).strip()
                    break
            if matched_group is not None:
                break

    return {
        "status": "passed",
        "ascendancyOrKeySupport": {
            "verified": ascendancy_active or support_count > 0,
            "ascendancy": ascendancy or "None",
            "ascendancyActive": ascendancy_active,
            "mainGroupSupportCount": support_count,
        },
        "singleTargetDuty": {
            "verified": matched_group is not None,
            "requestedSkillName": requested,
            "matchedSkillName": matched_skill,
            "groupIndex": matched_group["groupIndex"] if matched_group else None,
            "role": matched_group["role"] if matched_group else None,
        },
    }


# Engine-invisible resource layers that real builds carry but PoB cannot quantify. When a build
# enables these and still shows a mana deficit, the deficit may be covered by the unmodelled layer
# in-game; downstream gates must disclose instead of treating the engine gap as a build failure.
_UNMODELLED_MANA_SKILLS = {
    "mana_remnants": ("mana remnants",),
}
_UNMODELLED_MANA_GEAR = {
    "lavianga_spirits": ("lavianga's spirits",),
}


def inspect_resource_model_gap(xml: str, gear: Any) -> dict[str, Any]:
    """Detect engine-invisible resource mechanisms the evaluated build actually carries.

    ``xml`` is the exact active snapshot and ``gear`` the same build's equipped-gear readback, so
    the evidence cannot be forged by the caller. Returns the detected mechanism keys plus stable
    display names; an empty list means the build relies on no known unmodelled mana layer.
    """
    found: dict[str, str] = {}
    parsed = _parse_skill_groups(xml)
    if not parsed.get("errorCode"):
        for group in parsed["groups"]:
            for skill_name in group["activeNames"]:
                lowered = str(skill_name).strip().casefold()
                for key, names in _UNMODELLED_MANA_SKILLS.items():
                    if key not in found and lowered in names:
                        found[key] = str(skill_name).strip()
    if isinstance(gear, dict):
        for slot, item in gear.items():
            if not isinstance(item, dict):
                continue
            text = f"{item.get('name') or ''} {item.get('base') or ''}".casefold()
            for key, names in _UNMODELLED_MANA_GEAR.items():
                if key not in found and any(name in text for name in names):
                    found[key] = f"{item.get('name') or item.get('base') or ''}".strip()
    return {
        "detected": bool(found),
        "mechanismKeys": sorted(found),
        "mechanismNames": [found[key] for key in sorted(found)],
        "evidenceSource": "active_snapshot_and_gear_readback",
    }


def inspect_lifecycle_component_evidence(
    xml: str,
    *,
    component_kind: str | None,
    component_name: str | None,
) -> dict[str, Any]:
    """Match one declared build-defining component against the active XML snapshot."""
    kind = str(component_kind or "").strip()
    requested = str(component_name or "").strip()
    if not kind or not requested:
        return {"verified": False, "kind": kind, "requestedName": requested}

    parsed = _parse_skill_groups(xml)
    if parsed.get("errorCode"):
        return {
            "verified": False,
            "kind": kind,
            "requestedName": requested,
            "errorCode": str(parsed["errorCode"]),
        }
    if kind == "skill":
        for group in parsed["groups"]:
            for skill_name in group["activeNames"]:
                if str(skill_name).strip().casefold() == requested.casefold():
                    return {
                        "verified": True,
                        "kind": kind,
                        "requestedName": requested,
                        "matchedName": str(skill_name).strip(),
                        "groupIndex": group["groupIndex"],
                        "role": group["role"],
                    }
    elif kind == "ascendancy":
        ascendancy = str(parsed.get("ascendancy") or "").strip()
        if ascendancy.casefold() == requested.casefold():
            return {
                "verified": True,
                "kind": kind,
                "requestedName": requested,
                "matchedName": ascendancy,
            }
    elif kind == "item":
        matched_item = _match_equipped_item(xml, requested)
        if matched_item is not None:
            return {
                "verified": True,
                "kind": kind,
                "requestedName": requested,
                **matched_item,
            }
    return {
        "verified": False,
        "kind": kind,
        "requestedName": requested,
        "matchedName": "",
    }


def _match_equipped_item(xml: str, requested: str) -> dict[str, Any] | None:
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, TypeError, ValueError):
        return None
    items = root.find("Items")
    if items is None:
        return None
    active_set_id = str(items.get("activeItemSet") or "1")
    item_set = next(
        (node for node in items.findall("ItemSet") if str(node.get("id")) == active_set_id),
        None,
    )
    if item_set is None:
        return None
    item_text = {
        str(item.get("id") or ""): [
            line.strip() for line in str(item.text or "").splitlines() if line.strip()
        ]
        for item in items.findall("Item")
    }
    for slot in item_set.findall("Slot"):
        lines = item_text.get(str(slot.get("itemId") or ""), [])
        candidate_names = [
            line
            for line in lines[:4]
            if not line.casefold().startswith(("rarity:", "item level:", "levelreq:"))
        ]
        matched = next(
            (line for line in candidate_names if line.casefold() == requested.casefold()),
            None,
        )
        if matched:
            return {
                "matchedName": matched,
                "slot": str(slot.get("name") or ""),
            }
    return None


def _parse_skill_groups(xml: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, TypeError, ValueError):
        return {"errorCode": "active_build_snapshot_invalid"}
    build = root.find("Build")
    skills = root.find("Skills")
    if build is None or skills is None:
        return {"errorCode": "active_build_snapshot_invalid"}
    main_group = str(build.get("mainSocketGroup") or "1")
    active_set_id = str(skills.get("activeSkillSet") or "1")
    skill_set = next(
        (node for node in skills.findall("SkillSet") if str(node.get("id")) == active_set_id),
        None,
    )
    if skill_set is None:
        return {"errorCode": "missing_active_skill_group"}

    groups: list[dict[str, Any]] = []
    for index, group in enumerate(skill_set.findall("Skill"), start=1):
        if not _xml_bool(group.get("enabled"), default=True):
            continue
        gems = [gem for gem in group.findall("Gem") if _xml_bool(gem.get("enabled"), default=True)]
        active = [gem for gem in gems if not _is_support(gem)]
        supports = [gem for gem in gems if _is_support(gem)]
        if not active:
            continue
        groups.append(
            {
                "groupIndex": index,
                "role": "pob_main_group" if str(index) == main_group else "additional_skill_group",
                "activeIds": [_gem_identity(gem) for gem in active],
                "activeNames": [_gem_name(gem) for gem in active],
                "supportIds": [_gem_identity(gem) for gem in supports],
                "supportNames": [_gem_name(gem) for gem in supports],
            }
        )
    if not groups or not any(group["role"] == "pob_main_group" for group in groups):
        return {"errorCode": "missing_active_skill_group"}
    return {
        "groups": groups,
        "ascendancy": str(build.get("ascendClassName") or "None"),
    }


def _gem_identity(gem: ET.Element) -> str:
    return str(gem.get("gemId") or gem.get("skillId") or gem.get("nameSpec") or "unknown-gem")


def _gem_name(gem: ET.Element) -> str:
    return str(gem.get("nameSpec") or gem.get("skillId") or gem.get("gemId") or "unknown")


def _is_support(gem: ET.Element) -> bool:
    gem_id = str(gem.get("gemId") or "")
    skill_id = str(gem.get("skillId") or "")
    return "SupportGem" in gem_id or skill_id.startswith("Support")


def _xml_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.casefold() in {"1", "true"}


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output


def _error(error_code: str) -> dict[str, Any]:
    return {
        "status": "error",
        "readyForJudge": False,
        "hardLegalityReady": False,
        "mechanismReady": False,
        "blockingIssues": [error_code],
        "mechanismBlockers": [error_code],
        "qualityAdvisories": [],
        "advisories": [],
        "skillGroups": [],
        "noRawMaterial": True,
    }
