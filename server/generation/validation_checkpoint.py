"""State-hash keyed generation checks that collapse repeated read-only validation calls."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from copy import deepcopy
from typing import Any

from server.compute import completeness, craftopt, itemopt, supportopt, sustain
from server.compute.state import build_state_hash
from server.knowledge import lifecycle_verification

from . import preflight


CHECKPOINT_VERSION = "generation_checkpoint_v4"
_CACHE_LIMIT = 48
_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_LOCK = threading.RLock()
_STAT_KEYS = [
    "CombinedDPS",
    "TotalDPS",
    "FullDPS",
    "TotalEHP",
    "Life",
    "LifeUnreserved",
    "LifeUnreservedPercent",
    "EnergyShield",
    "Mana",
    "ManaUnreserved",
    "ManaUnreservedPercent",
    "Spirit",
    "Accuracy",
    "HitChance",
    "ManaCost",
    "ManaPercentCost",
    "ManaPerSecondCost",
    "ManaPercentPerSecondCost",
    "LifeCost",
    "LifePercentCost",
    "LifePerSecondCost",
    "LifePercentPerSecondCost",
    "NetManaRegen",
    "ManaRegenRecovery",
    "ManaLeechGainRate",
    "ManaOnHitRate",
    "NetLifeRegen",
    "LifeRegenRecovery",
    "LifeLeechGainRate",
    "LifeOnHitRate",
    "Speed",
]


def inspect_generation_checkpoint(
    engine: Any,
    *,
    strict_mode: bool = False,
    offense_skill_group_index: int | None = None,
    expected_skill_name: str | None = None,
) -> dict[str, Any]:
    """Inspect one semantic build state once, then reuse the bounded result for identical states."""

    with engine.transaction_lock():
        try:
            xml = engine.get_xml()
        except Exception:  # noqa: BLE001
            return _project_result(
                _error("generation_checkpoint_snapshot_failed"),
                strict_mode=strict_mode,
            )
        state_hash = build_state_hash(xml)
        calculation_selector = (
            f"{int(offense_skill_group_index or 0)}:"
            f"{str(expected_skill_name or '').strip().casefold()}"
        )
        cache_key = f"{CHECKPOINT_VERSION}:{state_hash}:{calculation_selector}"
        with _LOCK:
            cached = _CACHE.get(cache_key)
            if cached is not None:
                _CACHE.move_to_end(cache_key)
                result = deepcopy(cached)
                result["cacheHit"] = True
                _refresh_dynamic_quality(
                    result,
                    engine=engine,
                    xml=xml,
                    state_hash=state_hash,
                )
                return _project_result(result, strict_mode=strict_mode)

        try:
            complete = completeness.inspect_build_completeness(engine, snapshot_xml=xml)
            preflight_result = preflight.inspect_generation_snapshot(
                engine,
                xml,
                completeness_result=complete,
            )
            build = engine.get_build()
            stats_result, calculation_context = _read_target_skill_stats(
                engine,
                xml=xml,
                preflight_result=preflight_result,
                offense_skill_group_index=offense_skill_group_index,
                expected_skill_name=expected_skill_name,
            )
            if stats_result.get("errorCode"):
                return _project_result(stats_result, strict_mode=strict_mode)
            defenses = engine.get_defenses()
            after_hash = build_state_hash(engine.get_xml())
        except Exception:  # noqa: BLE001
            return _project_result(
                _error("generation_checkpoint_inspection_failed", state_hash=state_hash),
                strict_mode=strict_mode,
            )
        if after_hash != state_hash:
            return _project_result(
                _error(
                    "generation_checkpoint_state_changed",
                    state_hash=state_hash,
                    actual_state_hash=after_hash,
                ),
                strict_mode=strict_mode,
            )

        stats = stats_result.get("stats") if isinstance(stats_result, dict) else {}
        if not isinstance(stats, dict):
            stats = {}
        build = build if isinstance(build, dict) else {}
        result = {
            "status": "ready" if preflight_result.get("readyForJudge") else "blocked",
            "checkpointVersion": CHECKPOINT_VERSION,
            "validationRef": _validation_ref(state_hash),
            "stateHash": state_hash,
            "cacheHit": False,
            "buildSummary": {
                "class": build.get("class"),
                "ascendancy": build.get("ascendancy"),
                "level": build.get("level"),
                "mainSkill": build.get("mainSkill"),
            },
            "stats": {key: stats.get(key) for key in _STAT_KEYS if key in stats},
            "calculationContext": calculation_context,
            "defenses": defenses if isinstance(defenses, dict) else {},
            "completeness": complete,
            "preflight": preflight_result,
            "hardLegality": preflight_result.get("hardLegality"),
            "hardLegalityReady": bool(preflight_result.get("hardLegalityReady")),
            "mechanismReady": bool(preflight_result.get("mechanismReady")),
            "readinessReady": bool(preflight_result.get("readinessReady", True)),
            "readinessGates": deepcopy(preflight_result.get("readinessGates") or {}),
            "qualityAdvisories": list(preflight_result.get("qualityAdvisories") or []),
            "readyForJudge": bool(preflight_result.get("readyForJudge")),
            "sameStateVerified": True,
            "noRawMaterial": True,
            "_checkpointInputs": {
                "build": deepcopy(build),
                "stats": deepcopy(stats),
            },
        }
        lifecycle_stage = (
            "endgame_final" if int(build.get("level") or 0) >= 92 else "endgame_budget"
        )
        resource_gap = preflight.inspect_resource_model_gap(
            xml,
            completeness.equipped_item_metadata(xml)
            or (build.get("gear") if isinstance(build.get("gear"), dict) else {}),
        )
        lifecycle_result = lifecycle_verification.verify_stage_metrics(
            lifecycle_stage,
            stats=stats,
            defenses=defenses if isinstance(defenses, dict) else {},
            state={
                "level": int(build.get("level") or 0),
                "mainSkillSocketed": bool(
                    preflight.inspect_main_skill_socketed(xml).get("socketed")
                ),
            },
            engine_warning=(
                str(stats_result.get("warning"))
                if isinstance(stats_result, dict) and stats_result.get("warning")
                else None
            ),
            unmodelled_mana_mechanisms=list(resource_gap.get("mechanismKeys") or []),
        )
        result["lifecycleVerification"] = {
            "stage": lifecycle_stage,
            "status": lifecycle_result.get("status"),
            "pass": bool(lifecycle_result.get("pass")),
            "requiredChecks": list(lifecycle_result.get("requiredChecks") or []),
            "advisoryChecks": list(lifecycle_result.get("advisoryChecks") or []),
            "failedChecks": list(lifecycle_result.get("failedChecks") or []),
            "unknownChecks": list(lifecycle_result.get("unknownChecks") or []),
        }
        _refresh_dynamic_quality(
            result,
            engine=engine,
            xml=xml,
            state_hash=state_hash,
        )
        with _LOCK:
            _CACHE[cache_key] = deepcopy(result)
            _CACHE.move_to_end(cache_key)
            while len(_CACHE) > _CACHE_LIMIT:
                _CACHE.popitem(last=False)
        return _project_result(result, strict_mode=strict_mode)


def clear_validation_checkpoint_cache() -> None:
    """Test/runtime maintenance helper."""

    with _LOCK:
        _CACHE.clear()


def _read_target_skill_stats(
    engine: Any,
    *,
    xml: str,
    preflight_result: dict[str, Any],
    offense_skill_group_index: int | None,
    expected_skill_name: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    groups = [
        dict(group)
        for group in preflight_result.get("skillGroups") or []
        if isinstance(group, dict)
    ]
    expected = str(expected_skill_name or "").strip()
    if not groups and offense_skill_group_index is None and not expected:
        return engine.get_stats(_STAT_KEYS), {
            "groupIndex": None,
            "activeIndex": None,
            "skillName": None,
            "source": "pob_main_group",
        }
    if offense_skill_group_index is not None:
        selected = next(
            (
                group
                for group in groups
                if int(group.get("groupIndex") or 0) == int(offense_skill_group_index)
            ),
            None,
        )
    elif expected:
        matches = [
            group
            for group in groups
            if any(
                str(name).casefold() == expected.casefold()
                for name in group.get("activeSkills") or []
            )
        ]
        selected = matches[0] if len(matches) == 1 else None
    else:
        selected = next((group for group in groups if group.get("role") == "pob_main_group"), None)
    if selected is None:
        return _error("selected_skill_conflict", state_hash=build_state_hash(xml)), {}
    active_skills = [str(name) for name in selected.get("activeSkills") or []]
    if expected:
        active_index = next(
            (
                index
                for index, name in enumerate(active_skills, start=1)
                if name.casefold() == expected.casefold()
            ),
            None,
        )
        if active_index is None:
            return _error("selected_skill_conflict", state_hash=build_state_hash(xml)), {}
    else:
        active_index = 1
        expected = active_skills[0] if active_skills else ""
    context = {
        "groupIndex": int(selected.get("groupIndex") or 0),
        "activeIndex": active_index,
        "skillName": expected,
        "source": "pob_main_group"
        if selected.get("role") == "pob_main_group"
        else "explicit_offense_group",
    }
    explicit_target = offense_skill_group_index is not None or bool(expected_skill_name)
    if selected.get("role") == "pob_main_group" and not explicit_target:
        return engine.get_stats(_STAT_KEYS), context
    original_hash = build_state_hash(xml)
    selection_error: dict[str, Any] | None = None
    stats_result: dict[str, Any] = {}
    try:
        changed = engine.call(
            "set_skill_group_state",
            index=context["groupIndex"],
            makeMain=True,
            activeSkillIndex=active_index,
        )
        if not isinstance(changed, dict) or changed.get("ok") is False:
            selection_error = _error("selected_skill_conflict", state_hash=original_hash)
        else:
            stats_result = engine.get_stats(_STAT_KEYS)
    except Exception:  # noqa: BLE001 - restore below, then return a bounded error.
        selection_error = _error(
            "generation_checkpoint_skill_read_failed",
            state_hash=original_hash,
        )
    restored = _restore_checkpoint_state(engine, xml, original_hash)
    if not restored:
        setattr(engine, "_poe2_mutation_batch_recovery_required", True)
        return (
            _error(
                "generation_checkpoint_restore_failed",
                state_hash=original_hash,
                recovery_required=True,
            ),
            {},
        )
    if selection_error is not None:
        return selection_error, {}
    return stats_result, context


def _restore_checkpoint_state(engine: Any, xml: str, expected_hash: str) -> bool:
    try:
        engine.load_build_xml(xml, name="checkpoint-offense-group-restore")
    except Exception:  # noqa: BLE001 - verify the actual state even when the RPC raised.
        pass
    try:
        return build_state_hash(engine.get_xml()) == expected_hash
    except Exception:  # noqa: BLE001
        return False


def _create_quality_checklist(
    *,
    engine: Any,
    xml: str,
    state_hash: str,
    build: dict[str, Any],
    stats: dict[str, Any],
    completeness_result: dict[str, Any],
    preflight_result: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    level = int(build.get("level") or 0)
    support_reasons: list[str] = []
    support_freshness: dict[str, str] = {}
    support_audit_applicable = False
    mechanism_advisories: list[str] = []
    for group in preflight_result.get("skillGroups") or []:
        source = str(group.get("source") or "")
        source_kind = str(group.get("sourceKind") or "").casefold()
        trusted_source = (source.startswith("Tree:") and source_kind == "tree") or (
            source.startswith("Item:") and source_kind == "item"
        )
        trusted_other_source = (
            bool(source)
            and source_kind == "other"
            and not source.startswith(("Tree:", "Item:"))
        )
        if group.get("noSupports") and (
            trusted_source or trusted_other_source
        ):
            continue
        if source and not trusted_source:
            mechanism_advisories.append(
                f"source_skill_supports_unverified:{group.get('groupIndex')}"
            )
            continue
        if level < 80:
            continue
        support_audit_applicable = True
        group_index = int(group.get("groupIndex") or 0)
        freshness = supportopt.support_audit_freshness(engine, state_hash, group_index)
        support_freshness[str(group_index)] = freshness
        audit = supportopt.support_audit_for_state(engine, state_hash, group_index)
        if audit is None:
            support_reasons.append(f"support_audit_{freshness}:{group_index}")
        elif (
            audit.get("status") != "passed"
            or (audit.get("measurement") or {}).get("status") != "complete"
            or (audit.get("measurement") or {}).get("checkpointEligible") is not True
            or (audit.get("measurement") or {}).get("coverageComplete") is not True
            or (audit.get("measurement") or {}).get("classificationComplete") is not True
            or int((audit.get("measurement") or {}).get("measuredCandidates") or 0) < 1
            or int((audit.get("measurement") or {}).get("classifiedCandidates") or 0)
            != int((audit.get("measurement") or {}).get("screenedCandidates") or 0)
            or int((audit.get("measurement") or {}).get("failedCandidates") or 0) > 0
            or int((audit.get("measurement") or {}).get("failedCombinations") or 0) > 0
            or (audit.get("measurement") or {}).get("finalConstraintsSatisfied") is not True
        ):
            missing = ",".join(audit.get("positiveGainSupportsMissing") or []) or "unknown"
            if audit.get("status") == "inconclusive" or (
                audit.get("measurement") or {}
            ).get("status") != "complete":
                support_reasons.append(f"support_audit_inconclusive:{group_index}")
            else:
                support_reasons.append(f"positive_gain_supports_missing:{group_index}:{missing}")

    gear = completeness.equipped_item_metadata(xml)
    if not gear:
        gear = build.get("gear") if isinstance(build.get("gear"), dict) else {}
    bootstrap_reasons = list(completeness_result.get("scaffoldSlots") or [])
    attainability_reasons: list[str] = []
    if level >= 80:
        for slot in ("Weapon 1", "Weapon 2"):
            item = gear.get(slot) if isinstance(gear, dict) else None
            if isinstance(item, dict) and str(item.get("rarity") or "").casefold() == "normal":
                bootstrap_reasons.append(f"normal_endgame_weapon:{slot}")
        for slot, equipped in gear.items():
            if not isinstance(equipped, dict):
                continue
            if str(equipped.get("rarity") or "").casefold() != "rare":
                continue
            affix_count = int(equipped.get("affixPrefixes") or 0) + int(
                equipped.get("affixSuffixes") or 0
            )
            if affix_count > 5:
                attainability_reasons.append(f"theoretical_six_affix_rare:{slot}")
            if int(equipped.get("topTierAffixes") or 0) > 2:
                attainability_reasons.append(f"too_many_top_tier_affixes:{slot}")
        attainability_reasons.extend(
            f"special_source_unverified:{slot}"
            for slot in completeness_result.get("unverifiedSpecialSourceSlots") or []
        )

    charm_reasons: list[str] = []
    charm_state = completeness_result.get("charms") or {}
    for slot in ("Charm 1", "Charm 2", "Charm 3"):
        equipped = gear.get(slot)
        if not isinstance(equipped, dict):
            continue
        rarity = str(equipped.get("rarity") or "").casefold()
        if rarity == "normal":
            charm_reasons.append(f"normal_endgame_charm:{slot}")
        elif rarity == "magic" and (
            int(equipped.get("affixPrefixes") or 0) < 1
            or int(equipped.get("affixSuffixes") or 0) < 1
        ):
            charm_reasons.append(f"incomplete_magic_charm:{slot}")
    capacity = charm_state.get("beltCapacity")
    equipped_charms = list(charm_state.get("equippedSlots") or [])
    if level >= 90 and isinstance(capacity, int) and len(equipped_charms) < capacity:
        charm_reasons.append(f"unfilled_charm_slots:{capacity - len(equipped_charms)}")
    flask_state = completeness_result.get("flasks") or {}
    missing_flasks = sorted(
        set(flask_state.get("expectedSlots") or []) - set(flask_state.get("equippedSlots") or [])
    )
    charm_reasons.extend(f"missing_flask:{slot}" for slot in missing_flasks)
    for flask in flask_state.get("details") or []:
        if level >= 80 and flask.get("rarity") == "normal":
            charm_reasons.append(f"normal_endgame_flask:{flask.get('slot')}")
        if (
            level >= 80
            and flask.get("rarity") == "magic"
            and (int(flask.get("prefixes") or 0) < 1 or int(flask.get("suffixes") or 0) < 1)
        ):
            charm_reasons.append(f"incomplete_magic_flask:{flask.get('slot')}")

    jewel_state = completeness_result.get("passiveJewels") or {}
    allocated = int(jewel_state.get("allocatedSockets") or 0)
    filled = int(jewel_state.get("filledSockets") or 0)
    jewel_reasons = [] if filled >= allocated else [f"unfilled_jewel_sockets:{allocated - filled}"]
    jewel_freshness = "current"
    if level >= 90 and int(jewel_state.get("availableSockets") or 0) > allocated:
        jewel_freshness = itemopt.next_jewel_decision_freshness(engine, state_hash)
        decision = itemopt.next_jewel_decision_for_state(engine, state_hash)
        if decision is None:
            jewel_reasons.append(f"next_jewel_socket_{jewel_freshness}")
        elif decision.get("status") == "requires_reallocation":
            jewel_reasons.append("next_jewel_socket_reallocation_required")
        elif decision.get("status") == "applied" and int(decision.get("roundIndex") or 0) == 1:
            jewel_reasons.append("next_jewel_socket_second_round_required")
        elif decision.get("status") == "applied" and int(
            decision.get("roundsCompleted") or 0
        ) >= 2:
            pass
        elif decision.get("positiveNetBenefit"):
            jewel_reasons.append("positive_next_jewel_socket_not_applied")
    socket_state = completeness_result.get("runes") or {}
    batch_decisions = craftopt.socket_batch_decisions_for_state(engine, state_hash)
    socket_reasons: list[str] = []
    socket_freshness: dict[str, str] = {}
    for slot in socket_state.get("decisionRequiredSlots") or []:
        freshness = craftopt.socket_decision_freshness(engine, state_hash, str(slot))
        socket_freshness[str(slot)] = freshness
        decision = batch_decisions.get(str(slot))
        if decision in {"no_positive", "partial_no_positive", "not_applicable"}:
            continue
        if decision == "socketed":
            socket_reasons.append(f"planned_socket_not_applied:{slot}")
        elif decision == "failed":
            socket_reasons.append(f"socket_plan_failed:{slot}")
        else:
            socket_reasons.append(f"socket_decision_{freshness}:{slot}")
    mana_flask = any(
        isinstance(item, dict)
        and str(slot).casefold().startswith("flask")
        and "mana flask" in f"{item.get('name') or ''} {item.get('base') or ''}".casefold()
        for slot, item in gear.items()
    )
    sustain_result = sustain.classify_resource_sustain(
        stats,
        mana_flask_equipped=mana_flask,
        unmodelled_mana_mechanisms=list(
            preflight.inspect_resource_model_gap(xml, gear).get("mechanismKeys") or []
        ),
    )
    sustain_classification = str(sustain_result.get("classification") or "sustain_unknown")
    sustain_status = str(sustain_result.get("status") or "unknown")
    sustain_reasons = (
        []
        if sustain_status == "passed"
        else [sustain_classification]
    )

    def item(reasons: list[str], *, applicable: bool = True) -> dict[str, Any]:
        return {
            "status": "not_applicable" if not applicable else "failed" if reasons else "passed",
            "reasons": reasons,
        }

    return {
        "skillSupportAudit": {
            **item(support_reasons, applicable=support_audit_applicable),
            "evidenceFreshness": support_freshness,
        },
        "mechanismDependencies": {
            "status": "failed" if mechanism_advisories else "passed",
            "reasons": mechanism_advisories,
            "verificationRequired": bool(mechanism_advisories),
        },
        "bootstrapItems": item(sorted(set(bootstrap_reasons))),
        "gearAttainability": item(sorted(set(attainability_reasons))),
        "charmLoadout": item(sorted(set(charm_reasons)) if level >= 80 else []),
        "jewelDecision": {
            **item(jewel_reasons),
            "evidenceFreshness": jewel_freshness,
        },
        "itemSockets": {
            **item(socket_reasons),
            "evidenceFreshness": socket_freshness,
        },
        "sustain": {
            "status": sustain_status,
            "reasons": sustain_reasons,
            "verificationRequired": bool(sustain_result.get("verificationRequired")),
            "resourceSustain": sustain_result,
        },
    }


def _refresh_dynamic_quality(
    result: dict[str, Any],
    *,
    engine: Any,
    xml: str,
    state_hash: str,
) -> None:
    """Refresh cheap session-local audit decisions without repeating PoB calculations."""

    inputs = result.get("_checkpointInputs") or {}
    build = inputs.get("build") if isinstance(inputs.get("build"), dict) else {}
    stats = inputs.get("stats") if isinstance(inputs.get("stats"), dict) else {}
    completeness_result = (
        result.get("completeness") if isinstance(result.get("completeness"), dict) else {}
    )
    preflight_result = result.get("preflight") if isinstance(result.get("preflight"), dict) else {}
    checklist = _create_quality_checklist(
        engine=engine,
        xml=xml,
        state_hash=state_hash,
        build=build,
        stats=stats,
        completeness_result=completeness_result,
        preflight_result=preflight_result,
    )
    result["createQualityChecklist"] = checklist
    quality_failed = any(value.get("status") == "failed" for value in checklist.values())
    lifecycle_passed = bool((result.get("lifecycleVerification") or {}).get("pass"))
    result["deliveryStatus"] = (
        "blocked"
        if not result.get("readyForJudge")
        else "candidate"
        if quality_failed or not lifecycle_passed
        else "recommended"
    )
    result["qualityRepairPlan"] = _quality_repair_plan(checklist)
    result["qualityRepairAttemptLimit"] = 2


def _quality_repair_plan(checklist: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    tools = {
        "skillSupportAudit": [
            "optimize_supports",
            "replace_skill_group",
            "configure_source_skill_supports",
        ],
        "mechanismDependencies": ["configure_source_skill_supports", "equip_item"],
        "bootstrapItems": ["plan_gear", "equip_item"],
        "gearAttainability": ["plan_gear", "optimize_item"],
        "charmLoadout": ["optimize_charm", "optimize_flask", "equip_item"],
        "jewelDecision": [
            "evaluate_next_jewel_socket",
            "apply_next_jewel_socket_decision",
        ],
        "itemSockets": ["plan_item_sockets_batch", "equip_item"],
        "sustain": ["optimize_supports", "optimize_flask", "plan_gear"],
    }
    return [
        {
            "check": name,
            "reasons": list(value.get("reasons") or []),
            "suggestedTools": tools[name],
        }
        for name, value in checklist.items()
        if value.get("status") == "failed"
    ]


def _project_result(result: dict[str, Any], *, strict_mode: bool) -> dict[str, Any]:
    projected = deepcopy(result)
    projected.pop("_checkpointInputs", None)
    projected["feedbackMode"] = "strict" if strict_mode else "hard_only"
    projected["subjectiveFeedbackSuppressed"] = not strict_mode
    nested_preflight = projected.get("preflight")
    if isinstance(nested_preflight, dict):
        projected["preflight"] = preflight.project_feedback(
            nested_preflight,
            strict_mode=strict_mode,
        )
    if strict_mode:
        return projected
    # Objective Create-quality checks and delivery status are factual and must never be hidden by
    # hard-only feedback mode.
    projected["qualityAdvisories"] = []
    completeness_result = projected.get("completeness")
    if isinstance(completeness_result, dict):
        completeness_result["advisories"] = []
        completeness_result["status"] = (
            "complete" if not completeness_result.get("hardFailures") else "needs_attention"
        )
    return projected


def _validation_ref(state_hash: str) -> str:
    digest = hashlib.sha256(f"{CHECKPOINT_VERSION}|{state_hash}".encode()).hexdigest()[:24]
    return f"generation-checkpoint:{digest}"


def _error(
    error_code: str,
    *,
    state_hash: str | None = None,
    actual_state_hash: str | None = None,
    recovery_required: bool = False,
) -> dict[str, Any]:
    result = {
        "status": "error",
        "errorCode": error_code,
        "stateHash": state_hash,
        "actualStateHash": actual_state_hash,
        "readyForJudge": False,
        "hardLegalityReady": False,
        "mechanismReady": False,
        "qualityAdvisories": [],
        "sameStateVerified": False,
        "noRawMaterial": True,
    }
    if recovery_required:
        result["recoveryRequired"] = True
    return result
