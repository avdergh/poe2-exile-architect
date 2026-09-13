"""Engine/process-local generation checks that reuse unchanged semantic build states."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4
from weakref import WeakKeyDictionary

from server.compute import attainability, completeness, craftopt, itemopt, supportopt, sustain
from server.compute.state import build_state_hash
from server.knowledge import lifecycle_verification

from . import lifecycle_observation, preflight


CHECKPOINT_VERSION = "generation_checkpoint_v11"
_CACHE_LIMIT = 48


@dataclass
class _EngineCache:
    # PoB loads runtime data once per process. Keep the process object, not its reusable OS pid.
    process: Any
    scope: str = field(default_factory=lambda: uuid4().hex)
    entries: OrderedDict[str, dict[str, Any]] = field(default_factory=OrderedDict)


_CACHE: WeakKeyDictionary[Any, _EngineCache] = WeakKeyDictionary()
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
    """Reuse identical states only within the same engine and live process lifetime."""

    with engine.transaction_lock():
        with _LOCK:
            engine_cache = _cache_for_engine(engine)
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
        availability_context = supportopt._availability_context(engine)
        cache_key = f"{CHECKPOINT_VERSION}:{state_hash}:{calculation_selector}:{availability_context['fingerprint']}"
        with _LOCK:
            cached = engine_cache.entries.get(cache_key)
            if cached is not None:
                engine_cache.entries.move_to_end(cache_key)
                result = deepcopy(cached)
        if cached is not None:
            # Dynamic session evidence can perform engine work. Never hold the global cache lock
            # while refreshing it: another session must remain able to inspect its own engine.
            result["cacheHit"] = True
            _refresh_lifecycle(result, engine=engine, xml=xml)
            _refresh_dynamic_quality(result, engine=engine, xml=xml, state_hash=state_hash)
            with _LOCK:
                if not _cache_is_current(engine, engine_cache):
                    return _project_result(
                        _error("generation_checkpoint_context_changed", state_hash=state_hash),
                        strict_mode=strict_mode,
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
            defenses = stats_result.pop("_checkpointDefenses", None)
            if defenses is None:
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
            "availabilityContextRef": availability_context["fingerprint"],
            "validationRef": _validation_ref(f"{engine_cache.scope}:{cache_key}"),
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
                "engineWarning": stats_result.get("warning")
                or stats_result.get("engineLimitation"),
            },
        }
        _refresh_lifecycle(result, engine=engine, xml=xml)
        _refresh_dynamic_quality(
            result,
            engine=engine,
            xml=xml,
            state_hash=state_hash,
        )
        with _LOCK:
            if not _cache_is_current(engine, engine_cache):
                return _project_result(
                    _error("generation_checkpoint_context_changed", state_hash=state_hash),
                    strict_mode=strict_mode,
                )
            engine_cache.entries[cache_key] = deepcopy(result)
            engine_cache.entries.move_to_end(cache_key)
            while len(engine_cache.entries) > _CACHE_LIMIT:
                engine_cache.entries.popitem(last=False)
        return _project_result(result, strict_mode=strict_mode)


def _cache_for_engine(engine: Any) -> _EngineCache:
    """Caller holds _LOCK; fake engines without a process still have separate object lifetimes."""
    process = getattr(engine, "proc", None)
    cached = _CACHE.get(engine)
    if cached is None or cached.process is not process:
        cached = _EngineCache(process=process)
        _CACHE[engine] = cached
    return cached


def _cache_is_current(engine: Any, cached: _EngineCache) -> bool:
    """Reject reads that straddle process replacement, process exit or explicit invalidation."""
    process = getattr(engine, "proc", None)
    poll = getattr(process, "poll", None)
    return (
        _CACHE.get(engine) is cached
        and cached.process is process
        and (not callable(poll) or poll() is None)
    )


def clear_validation_checkpoint_cache() -> None:
    """Invalidate every engine, including in-flight reads that must not repopulate old entries."""

    with _LOCK:
        _CACHE.clear()


def recheck_lifecycle_verification(
    engine: Any,
    *,
    xml: str,
    build: dict[str, Any],
    stats: dict[str, Any],
    defenses: dict[str, Any],
    observation_target: dict[str, Any],
    engine_warning: str | None = None,
) -> dict[str, Any]:
    """Re-evaluate lifecycle using same-state numeric reads and fresh mechanism declarations.

    The caller holds the engine transaction and binds these readbacks to ``xml`` and the exact
    offense target. This refresh never upgrades other quality checks or a trusted Judge result.
    """
    state_hash = build_state_hash(xml)
    target = lifecycle_observation.normalize_target(observation_target)
    declared = lifecycle_observation.state_for_target(
        engine, state_hash=state_hash, observation_target=target
    )
    effective_state = lifecycle_observation.observe_state(
        xml, build=build, observation_target=target, state=declared
    )
    lifecycle_stage = (
        "endgame_final" if int(effective_state.get("level") or 0) >= 92 else "endgame_budget"
    )
    gear = completeness.equipped_item_metadata(
        xml, allocated_jewel_socket_ids=build.get("allocatedPassiveJewelSocketIds")
    ) or (build.get("gear") if isinstance(build.get("gear"), dict) else {})
    resource_gap = preflight.inspect_resource_model_gap(xml, gear)
    verified = lifecycle_verification.verify_stage_metrics(
        lifecycle_stage,
        stats=stats,
        defenses=defenses,
        state=effective_state,
        engine_warning=engine_warning,
        unmodelled_mana_mechanisms=list(resource_gap.get("mechanismNames") or []),
    )
    return {
        "stage": lifecycle_stage,
        "status": verified.get("status"),
        "pass": bool(verified.get("pass")),
        "verificationRequired": bool(verified.get("verificationRequired")),
        "requiredChecks": list(verified.get("requiredChecks") or []),
        "advisoryChecks": list(verified.get("advisoryChecks") or []),
        "failedChecks": list(verified.get("failedChecks") or []),
        "unknownChecks": list(verified.get("unknownChecks") or []),
        "stateHash": state_hash,
        "observationTarget": target,
        "mechanismObservationVersion": lifecycle_observation.OBSERVATION_VERSION,
        "mechanismDeclarationAvailable": declared is not None,
    }


def _refresh_lifecycle(result: dict[str, Any], *, engine: Any, xml: str) -> None:
    inputs = result.get("_checkpointInputs") or {}
    result["lifecycleVerification"] = recheck_lifecycle_verification(
        engine,
        xml=xml,
        build=inputs.get("build") or {},
        stats=inputs.get("stats") or {},
        defenses=result.get("defenses") or {},
        observation_target=result.get("calculationContext") or {},
        engine_warning=inputs.get("engineWarning"),
    )


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
    if selected.get("activeSkillSelectionError"):
        return _error("selected_skill_conflict", state_hash=build_state_hash(xml)), {}
    if expected:
        matches = [
            index
            for index, name in enumerate(active_skills, start=1)
            if name.casefold() == expected.casefold()
        ]
        if len(matches) != 1:
            return _error("selected_skill_conflict", state_hash=build_state_hash(xml)), {}
        active_index = matches[0]
    else:
        active_index = _projected_active_index(selected)
        if active_index is None:
            return _error("selected_skill_conflict", state_hash=build_state_hash(xml)), {}
        expected = active_skills[active_index - 1] if active_skills else ""
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
            read_defenses = getattr(engine, "get_defenses", None)
            if callable(read_defenses):
                # Defensive readbacks can depend on the chosen active effect as well. Gather
                # them before restoring the selector, as the formal lifecycle verifier does.
                stats_result["_checkpointDefenses"] = read_defenses()
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


def _projected_active_index(group: dict[str, Any]) -> int | None:
    """Use the verified runtime selection; a legacy singleton is the only unique fallback."""
    if group.get("activeSkillSelectionError"):
        return None
    names = group.get("activeSkills") or []
    value = group.get("mainActiveSkillCalcs")
    if "mainActiveSkillCalcs" not in group and len(names) == 1:
        return 1
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= len(names):
        return None
    return value


def _create_quality_checklist(
    *,
    engine: Any,
    xml: str,
    state_hash: str,
    build: dict[str, Any],
    stats: dict[str, Any],
    completeness_result: dict[str, Any],
    preflight_result: dict[str, Any],
    calculation_context: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    level = int(build.get("level") or 0)
    support_reasons: list[str] = []
    support_freshness: dict[str, str] = {}
    support_group_results: list[dict[str, Any]] = []
    support_audit_applicable = False
    mechanism_advisories: list[str] = []
    for group in preflight_result.get("skillGroups") or []:
        source = str(group.get("source") or "")
        source_kind = str(group.get("sourceKind") or "").casefold()
        trusted_source = (source.startswith("Tree:") and source_kind == "tree") or (
            source.startswith("Item:") and source_kind == "item"
        )
        trusted_other_source = (
            bool(source) and source_kind == "other" and not source.startswith(("Tree:", "Item:"))
        )
        if group.get("noSupports") and (trusted_source or trusted_other_source):
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
            reason = f"support_audit_{freshness}:{group_index}"
            support_reasons.append(reason)
            support_group_results.append(
                {
                    "groupIndex": group_index,
                    "activeSkillIndex": _projected_active_index(group),
                    "freshness": freshness,
                    "status": "failed",
                    "reasonClass": "evidence_gap",
                    "reasonCodes": [reason],
                    "verificationRequired": False,
                    "currentAdverseEvidence": False,
                }
            )
            continue

        target_index = _projected_active_index(group)
        context = calculation_context or {}
        if context.get("groupIndex") == group_index:
            target_index = context.get("activeIndex")
        names = group.get("activeSkills") or []
        target_valid = (
            not group.get("activeSkillSelectionError")
            and isinstance(target_index, int)
            and not isinstance(target_index, bool)
            and 1 <= target_index <= len(names)
        )
        target_name = str(names[target_index - 1]) if target_valid else ""
        if context.get("groupIndex") == group_index and context.get("skillName"):
            target_name = str(context["skillName"])
        context_matches = (
            target_valid
            and int(audit.get("groupIndex") or 0) == group_index
            and int(audit.get("activeSkillIndex") or 0) == target_index
            and (
                not target_name
                or str(audit.get("skill") or "").casefold() == target_name.casefold()
            )
        )
        measurement = audit.get("measurement") or {}
        complete = (
            context_matches
            and audit.get("status") == "passed"
            and supportopt.support_audit_is_complete(audit)
        )
        capability = audit.get("capability") or {}
        supported_model_gap = (
            context_matches
            and audit.get("auditVersion") == "support_audit_v5"
            and audit.get("status") == "inconclusive"
            and audit.get("reasonClass") == "capability_gap"
            and supportopt.support_capability_is_model_gap(capability)
            and measurement.get("coverageComplete") is True
            and measurement.get("classificationComplete") is True
            and int(measurement.get("failedCandidates") or 0) == 0
            and int(measurement.get("failedCombinations") or 0) == 0
            and measurement.get("finalConstraintsSatisfied") is True
            and not audit.get("positiveGainSupportsMissing")
        )
        if not context_matches:
            group_status = "failed"
            group_reasons = [f"support_audit_calculation_context_mismatch:{group_index}"]
        elif complete:
            group_status = "passed"
            group_reasons: list[str] = []
        elif supported_model_gap:
            group_status = "unknown"
            detail = ",".join(str(value) for value in audit.get("reasonCodes") or [])
            group_reasons = [f"support_audit_capability_gap:{group_index}:{detail or 'unmodelled'}"]
        elif (
            audit.get("status") != "passed"
            or measurement.get("status") != "complete"
            or measurement.get("checkpointEligible") is not True
        ):
            missing = ",".join(audit.get("positiveGainSupportsMissing") or []) or "unknown"
            if audit.get("status") == "inconclusive" or measurement.get("status") != "complete":
                group_reasons = [f"support_audit_inconclusive:{group_index}"]
            elif audit.get("supportsToRemove") and not audit.get("positiveGainSupportsMissing"):
                removed = ",".join(audit["supportsToRemove"])
                group_reasons = [f"positive_gain_supports_to_remove:{group_index}:{removed}"]
            else:
                group_reasons = [f"positive_gain_supports_missing:{group_index}:{missing}"]
            group_status = "failed"
        else:
            group_status = "failed"
            group_reasons = [f"support_audit_invalid:{group_index}"]
        support_reasons.extend(group_reasons)
        support_group_results.append(
            {
                "groupIndex": group_index,
                "activeSkillIndex": int(audit.get("activeSkillIndex") or 1),
                "freshness": freshness,
                "auditVersion": audit.get("auditVersion"),
                "status": group_status,
                "reasonClass": str(audit.get("reasonClass") or "evidence_gap"),
                "reasonCodes": list(audit.get("reasonCodes") or []),
                "verificationRequired": bool(group_status == "unknown"),
                "capability": deepcopy(capability),
                "currentAdverseEvidence": bool(
                    context_matches
                    and freshness == "current"
                    and group_status in {"failed", "unknown"}
                ),
            }
        )

    gear = completeness.equipped_item_metadata(
        xml, allocated_jewel_socket_ids=build.get("allocatedPassiveJewelSocketIds")
    )
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
            attainability_reasons.extend(
                f"{reason}:{slot}"
                for reason in attainability.rare_item_reasons(
                    equipped,
                    profile="realistic_trade",
                )
            )
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
    jewel_freshness: str | None = None
    jewel_decision: dict[str, Any] | None = None
    jewel_review_applicable = (
        level >= 90 and int(jewel_state.get("availableSockets") or 0) > allocated
    )
    if jewel_review_applicable:
        jewel_freshness = itemopt.next_jewel_decision_freshness(engine, state_hash)
        jewel_decision = itemopt.next_jewel_decision_for_state(engine, state_hash)
        if jewel_decision is None:
            jewel_reasons.append(f"next_jewel_socket_{jewel_freshness}")
        elif jewel_decision.get("reviewPolicyVersion") != "jewel_socket_review_v2":
            jewel_reasons.append("next_jewel_socket_review_policy_outdated")
        elif not jewel_decision.get("protectionDeclared"):
            jewel_reasons.append("jewel_protection_not_declared")
        elif jewel_decision.get("status") == "applied":
            jewel_reasons.append("next_jewel_socket_review_required_after_apply")
        elif jewel_decision.get("positiveNetBenefit") is True:
            jewel_reasons.append("positive_next_jewel_socket_not_applied")
        elif jewel_decision.get("status") == "inconclusive":
            if int(jewel_decision.get("limitedSocketCount") or 0):
                jewel_reasons.append("selected_candidate_socket_policy_limited")
            if int(jewel_decision.get("inconclusiveSocketCount") or 0):
                jewel_reasons.append("selected_candidate_socket_probe_inconclusive")
            if not jewel_reasons:
                jewel_reasons.append("selected_candidate_socket_probe_inconclusive")
    socket_state = completeness_result.get("runes") or {}
    batch_decisions = craftopt.socket_batch_decisions_for_state(engine, state_hash)
    pending_socket_slots = set(craftopt.socket_pending_slots_for_state(engine, state_hash))
    socket_reasons: list[str] = []
    socket_freshness: dict[str, str] = {}
    checked_socket_slots = (
        set(socket_state.get("decisionRequiredSlots") or [])
        | {
            slot
            for slot, decision in batch_decisions.items()
            if decision in {"failed", "measurement_error", "capability_gap"}
        }
        | pending_socket_slots
    )
    equipped_socket_slots = {
        str(row["slot"])
        for row in socket_state.get("details") or []
        if isinstance(row, dict) and row.get("slot") and str(row["slot"]) in gear
    }
    checked_socket_slots |= set(craftopt.socket_reviewed_slots(engine)) & equipped_socket_slots
    current_socket_adverse = False
    for slot in sorted(checked_socket_slots):
        freshness = craftopt.socket_decision_freshness(engine, state_hash, str(slot))
        socket_freshness[str(slot)] = freshness
        decision = batch_decisions.get(str(slot))
        if decision in {"no_positive", "partial_no_positive", "not_applicable"}:
            continue
        if decision in {"socketed", "partial_socketed"}:
            if freshness == "current" and slot not in pending_socket_slots:
                continue
            socket_reasons.append(f"planned_socket_not_applied:{slot}")
        elif decision == "failed":
            socket_reasons.append(f"socket_plan_failed:{slot}")
        elif decision in {"measurement_error", "capability_gap"}:
            socket_reasons.append(f"socket_{decision}:{slot}")
        else:
            socket_reasons.append(f"socket_decision_{freshness}:{slot}")
        if freshness == "current" and decision in {
            "socketed",
            "partial_socketed",
            "failed",
            "measurement_error",
            "capability_gap",
        }:
            current_socket_adverse = True
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
    sustain_reasons = [] if sustain_status == "passed" else [sustain_classification]

    def item(reasons: list[str], *, applicable: bool = True) -> dict[str, Any]:
        return {
            "status": "not_applicable" if not applicable else "failed" if reasons else "passed",
            "reasons": reasons,
            "currentAdverseEvidence": bool(applicable and reasons),
        }

    return {
        "skillSupportAudit": {
            "status": (
                "not_applicable"
                if not support_audit_applicable
                else "failed"
                if any(value["status"] == "failed" for value in support_group_results)
                else "unknown"
                if any(value["status"] == "unknown" for value in support_group_results)
                else "passed"
            ),
            "reasons": support_reasons,
            "evidenceFreshness": support_freshness,
            "groupResults": support_group_results,
            "verificationRequired": any(
                bool(value.get("verificationRequired")) for value in support_group_results
            ),
            "currentAdverseEvidence": any(
                row.get("currentAdverseEvidence") is True for row in support_group_results
            ),
        },
        "mechanismDependencies": {
            "status": "failed" if mechanism_advisories else "passed",
            "reasons": mechanism_advisories,
            "verificationRequired": bool(mechanism_advisories),
            "currentAdverseEvidence": bool(mechanism_advisories),
        },
        "bootstrapItems": item(sorted(set(bootstrap_reasons))),
        "gearAttainability": item(sorted(set(attainability_reasons))),
        "charmLoadout": item(sorted(set(charm_reasons)) if level >= 80 else []),
        "jewelDecision": {
            "status": (
                "failed"
                if filled < allocated
                or (
                    jewel_review_applicable
                    and jewel_reasons
                    and not (
                        jewel_decision
                        and jewel_decision.get("status") == "inconclusive"
                        and jewel_decision.get("protectionDeclared")
                    )
                )
                else "unknown"
                if jewel_review_applicable
                and jewel_decision
                and jewel_decision.get("status") == "inconclusive"
                else "not_applicable"
                if not jewel_review_applicable
                else "passed"
            ),
            "reasons": jewel_reasons,
            "evidenceFreshness": jewel_freshness,
            "reviewPolicyVersion": (
                jewel_decision.get("reviewPolicyVersion") if jewel_decision else None
            ),
            "candidateJewelFingerprint": (
                jewel_decision.get("candidateJewelFingerprint") if jewel_decision else None
            ),
            "protectionDeclared": (
                jewel_decision.get("protectionDeclared") if jewel_decision else None
            ),
            "socketFrontierComplete": (
                jewel_decision.get("socketFrontierComplete") if jewel_decision else None
            ),
            "evaluatedSocketCount": int((jewel_decision or {}).get("evaluatedSocketCount") or 0),
            "limitedSocketCount": int((jewel_decision or {}).get("limitedSocketCount") or 0),
            "inconclusiveSocketCount": int(
                (jewel_decision or {}).get("inconclusiveSocketCount") or 0
            ),
            "verificationRequired": bool(
                jewel_decision and jewel_decision.get("status") == "inconclusive"
            ),
            "currentAdverseEvidence": bool(
                filled < allocated
                or (jewel_freshness == "current" and jewel_decision is not None and jewel_reasons)
            ),
        },
        "itemSockets": {
            **item(socket_reasons),
            "evidenceFreshness": socket_freshness,
            "currentAdverseEvidence": current_socket_adverse,
        },
        "sustain": {
            "status": sustain_status,
            "reasons": sustain_reasons,
            "verificationRequired": bool(sustain_result.get("verificationRequired")),
            "resourceSustain": sustain_result,
            "currentAdverseEvidence": sustain_status == "failed",
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
        calculation_context=result.get("calculationContext"),
    )
    result["createQualityChecklist"] = checklist
    quality_unresolved = any(
        value.get("status") in {"failed", "unknown"} for value in checklist.values()
    )
    lifecycle_passed = bool((result.get("lifecycleVerification") or {}).get("pass"))
    result["deliveryStatus"] = (
        "blocked"
        if not result.get("readyForJudge")
        else "candidate"
        if quality_unresolved or not lifecycle_passed
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


def _validation_ref(context_key: str) -> str:
    digest = hashlib.sha256(context_key.encode()).hexdigest()[:24]
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
