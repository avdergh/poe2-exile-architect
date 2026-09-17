"""Cheap, raw-free checks before a generation snapshot consumes a Judge attempt."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any
import xml.etree.ElementTree as ET

from server.compute import completeness, supportopt
from server.compute.defense_state import defense_keystones
from server.judge import hard_legality, rules


_OBJECTIVE_COMPLETENESS_ADVISORIES = frozenset({"spirit_opportunity_review_required"})


def final_check_blockers(checklist: dict[str, Any]) -> list[str]:
    """Shared deterministic final-evidence gate for checkpoints and formal evaluation.

    Unknown is not a blanket exemption: only the same current, typed capability/policy gaps
    accepted by the formal gate can continue. This function does not inspect or mutate PoB.
    """

    blockers: list[str] = []
    for name in ("skillSupportAudit", "jewelDecision", "itemSockets"):
        item = checklist.get(name) if isinstance(checklist, dict) else None
        if not isinstance(item, dict):
            blockers.append(f"{name}:missing_result")
            continue
        status = item.get("status")
        if status in {"passed", "not_applicable"}:
            continue
        if status not in {"failed", "unknown"}:
            blockers.append(f"{name}:invalid_status")
            continue
        if name == "skillSupportAudit" and status == "unknown":
            groups = item.get("groupResults") or []
            if groups and all(
                isinstance(group, dict)
                and (
                    group.get("status") == "passed"
                    or (
                        group.get("status") == "unknown"
                        and group.get("freshness") == "current"
                        and group.get("auditVersion") == "support_audit_v5"
                        and group.get("reasonClass") == "capability_gap"
                        and group.get("verificationRequired") is True
                        and supportopt.support_capability_is_model_gap(group.get("capability"))
                    )
                )
                for group in groups
            ):
                continue
        if name == "jewelDecision" and status == "unknown":
            jewel_reasons = {str(value) for value in item.get("reasons") or []}
            allowed_reasons = {
                "selected_candidate_socket_policy_limited",
                "selected_candidate_socket_probe_inconclusive",
            }
            executed = sum(
                int(item.get(key) or 0)
                for key in (
                    "evaluatedSocketCount",
                    "limitedSocketCount",
                    "inconclusiveSocketCount",
                )
            )
            if (
                item.get("evidenceFreshness") == "current"
                and item.get("reviewPolicyVersion") == "jewel_socket_review_v2"
                and item.get("protectionDeclared") is True
                and bool(jewel_reasons)
                and jewel_reasons <= allowed_reasons
                and executed > 0
            ):
                continue
        reasons = [str(value) for value in item.get("reasons") or []]
        if not reasons:
            reasons = ["failed_without_reason"]
        blockers.extend(f"{name}:{value}" for value in reasons)
    sustain_item = checklist.get("sustain") if isinstance(checklist, dict) else None
    if not isinstance(sustain_item, dict):
        blockers.append("sustain:missing_result")
    elif sustain_item.get("status") == "failed":
        blockers.extend(
            f"sustain:{value}" for value in sustain_item.get("reasons") or ["unsustainable"]
        )
    elif sustain_item.get("status") not in {"passed", "unknown", "not_applicable"}:
        blockers.append("sustain:invalid_status")
    return sorted(set(blockers))


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
    retained_advisories = [
        str(value)
        for value in projected.get("advisories") or []
        if str(value) in _OBJECTIVE_COMPLETENESS_ADVISORIES
    ]
    projected["qualityAdvisories"] = retained_advisories
    projected["advisories"] = retained_advisories
    if projected.get("readyForJudge"):
        projected["status"] = "needs_attention" if retained_advisories else "ready"
    completeness_result = projected.get("completeness")
    if isinstance(completeness_result, dict):
        completeness_result["advisories"] = retained_advisories
        completeness_result["status"] = (
            "complete"
            if not completeness_result.get("hardFailures") and not retained_advisories
            else "needs_attention"
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
    _decorate_runtime_active_names(engine, parsed)

    blocking: list[str] = []
    group_diagnostics: list[dict[str, Any]] = []
    signatures: list[tuple[Any, ...]] = []
    for group in parsed["groups"]:
        issues: list[str] = []
        active_ids = list(group["activeIds"])
        support_ids = list(group["supportIds"])
        if not _socket_composition_valid(group):
            issues.append("invalid_socket_setup")
            blocking.append("invalid_socket_setup")
        if len(support_ids) != len(set(support_ids)):
            issues.append("duplicate_support_gem")
            blocking.append("duplicate_support_gem")
        signature: tuple[Any, ...] = (tuple(sorted(active_ids)), tuple(sorted(support_ids)))
        if group.get("sourceKind") == "default_attack":
            # PoB creates one native attack per weapon set. Distinct, verified
            # owners are not duplicate socketed groups with the same gem names.
            signature += ("default_attack", group.get("slot"))
        signatures.append(signature)
        group_diagnostics.append(
            {
                "groupIndex": group["groupIndex"],
                "role": group["role"],
                "activeSkills": group["activeNames"],
                "mainActiveSkillCalcs": group.get("mainActiveSkillCalcs"),
                "activeSkillSelectionError": group.get("activeSkillSelectionError"),
                "supports": group["supportNames"],
                "socketedActiveCount": len(active_ids),
                "source": group.get("source"),
                "sourceKind": group.get("sourceKind"),
                "includeInFullDPS": bool(group.get("includeInFullDPS")),
                "noSupports": bool(group.get("noSupports")),
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
        build["passiveJewels"] = dict(complete.get("passiveJewels") or {})
        legality = hard_legality.audit_build(
            build,
            require_create_completion=True,
        )
        get_defenses = getattr(engine, "get_defenses", None)
        defenses = get_defenses() if callable(get_defenses) else {}
    except Exception:  # noqa: BLE001 - preflight fails closed without exposing engine details.
        return _error("hard_legality_audit_failed")
    legality_failures = [str(value) for value in legality.get("hardFailures") or []]
    resistance_gate = rules.check_endgame_resistance_gate(
        level=build.get("level"),
        resistances=(defenses.get("resistances") or {}) if isinstance(defenses, dict) else {},
        keystones=defense_keystones(build),
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
        "readinessScope": "structural_preflight_only",
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


def inspect_main_skill_socketed(
    xml: str,
    *,
    offense_skill_group_index: int | None = None,
) -> dict[str, Any]:
    """Return bounded evidence that the main group has a legal enabled active composition.

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
        (
            group
            for group in parsed["groups"]
            if group["groupIndex"] == offense_skill_group_index
        )
        if offense_skill_group_index is not None
        else (group for group in parsed["groups"] if group["role"] == "pob_main_group"),
        None,
    )
    active_count = len(main_group["activeIds"]) if main_group else 0
    socketed = bool(main_group and _socket_composition_valid(main_group))
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
    offense_skill_group_index: int | None = None,
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
        (
            group
            for group in parsed["groups"]
            if group["groupIndex"] == offense_skill_group_index
        )
        if offense_skill_group_index is not None
        else (group for group in parsed["groups"] if group["role"] == "pob_main_group"),
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
                "rootSkillId": str(
                    active[0].get("skillId")
                    or active[0].get("gemId")
                    or active[0].get("nameSpec")
                    or ""
                ),
                "activeNames": [_gem_name(gem) for gem in active],
                # Runtime display effects may expose multiple calculation choices for one socketed
                # gem (for example Ruzhan + Command). Preserve raw XML names for structure checks;
                # activeNames may be decorated later for display/selection only.
                "socketedActiveNames": [_gem_name(gem) for gem in active],
                "supportIds": [_gem_identity(gem) for gem in supports],
                "supportNames": [_gem_name(gem) for gem in supports],
                "source": str(group.get("source") or "") or None,
                "slot": str(group.get("slot") or ""),
                "includeInFullDPS": _xml_bool(group.get("includeInFullDPS")),
            }
        )
    if not groups or not any(group["role"] == "pob_main_group" for group in groups):
        return {"errorCode": "missing_active_skill_group"}
    return {
        "groups": groups,
        "ascendancy": str(build.get("ascendClassName") or "None"),
    }


def _socket_composition_valid(group: dict[str, Any]) -> bool:
    active_ids = list(group.get("activeIds") or [])
    if len(active_ids) == 1:
        return True
    names = group.get("socketedActiveNames") or group.get("activeNames") or []
    return rules.is_valid_active_skill_group(names)


def _decorate_runtime_active_names(engine: Any, parsed: dict[str, Any]) -> None:
    """Project complete runtime effect order and selection only after matching XML identity."""

    for group in parsed.get("groups") or []:
        group["mainActiveSkillCalcs"] = None
        group["activeSkillSelectionError"] = "runtime_skill_group_unavailable"
    try:
        runtime = engine.call("list_skill_groups")
    except Exception:  # noqa: BLE001 - preflight keeps XML evidence when runtime readback fails.
        return
    if not isinstance(runtime, dict) or runtime.get("ok") is False:
        return
    runtime_groups: dict[int, list[dict[str, Any]]] = {}
    for runtime_group in runtime.get("groups") or []:
        if isinstance(runtime_group, dict):
            index = _positive_runtime_index(runtime_group.get("index"))
            if index is not None:
                runtime_groups.setdefault(index, []).append(runtime_group)
    for group in parsed.get("groups") or []:
        matches = runtime_groups.get(group["groupIndex"]) or []
        if len(matches) != 1:
            if matches:
                group["activeSkillSelectionError"] = "runtime_skill_group_ambiguous"
            continue
        runtime_group = matches[0]
        parsed_source = str(group.get("source") or "")
        runtime_source = str(runtime_group.get("source") or "")
        parsed_root_id = str(group.get("rootSkillId") or "").strip()
        runtime_root_id = str(runtime_group.get("rootSkillId") or "").strip()
        if (
            parsed_source != runtime_source
            or not parsed_root_id
            or not runtime_root_id
            or parsed_root_id != runtime_root_id
            or str(group.get("slot") or "") != str(runtime_group.get("slot") or "")
            or runtime_group.get("enabled") is False
        ):
            group["activeSkillSelectionError"] = "runtime_skill_group_identity_mismatch"
            continue
        effects = runtime_group.get("activeSkills")
        if runtime_source == "Default Attack" and runtime_group.get("sourceKind") == "default_attack":
            # The inactive weapon set has a native root without a calculated
            # effect list. Preserve only its already matched source identity;
            # selecting it for an audit still requires valid effect evidence.
            group["sourceKind"] = "default_attack"
        if not isinstance(effects, list) or not effects:
            group["activeSkillSelectionError"] = "runtime_active_skills_missing"
            continue
        indexed_names: dict[int, str] = {}
        for effect in effects:
            index = _positive_runtime_index(effect.get("index")) if isinstance(effect, dict) else None
            name = str(effect.get("name") or "").strip() if isinstance(effect, dict) else ""
            effect_id = effect.get("effectId") if isinstance(effect, dict) else None
            # PoB includes unnamed internal effects in the same ordered list as selectable
            # outputs. Keep an identified entry's position; removing it would shift the payload.
            identified_internal = isinstance(effect_id, str) and bool(effect_id.strip())
            if index is None or index in indexed_names or (not name and not identified_internal):
                break
            indexed_names[index] = name
        if set(indexed_names) != set(range(1, len(effects) + 1)):
            group["activeSkillSelectionError"] = "runtime_active_skills_invalid"
            continue
        # Duplicate display names still occupy separate effect indices. Removing either would
        # shift the exact PoB selector; explicit name-only consumers must reject ambiguity.
        group["activeNames"] = [indexed_names[index] for index in range(1, len(effects) + 1)]
        active_index = _positive_runtime_index(runtime_group.get("mainActiveSkillCalcs"))
        if active_index not in indexed_names or not indexed_names[active_index]:
            group["activeSkillSelectionError"] = "runtime_active_skill_selection_invalid"
            continue
        group["mainActiveSkillCalcs"] = active_index
        group["activeSkillSelectionError"] = None
        if "noSupports" in runtime_group:
            group["noSupports"] = bool(runtime_group.get("noSupports"))
        if runtime_group.get("sourceKind"):
            group["sourceKind"] = str(runtime_group["sourceKind"])


def _positive_runtime_index(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


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
