"""Support-gem set optimizer (engine search; needs no magnitude data).

Greedily picks the support gems that most raise a metric (or weighted goals) for the active main
skill, measuring each combination on the real engine. The corpus has support-gem identity but not
effect magnitudes, so the only honest way to value a support is to try it — this is a bounded
mechanical search over engine truth, like optimize_passives / optimize_item.
"""

from __future__ import annotations

from copy import deepcopy
import math
import threading
from typing import Any
from weakref import WeakKeyDictionary

from ..knowledge import db
from ..judge import modelability
from .engine import PobEngine
from .state import build_state_hash


_AUDIT_LOCK = threading.RLock()
_SUPPORT_AUDITS: WeakKeyDictionary[Any, dict[tuple[str, int], dict[str, Any]]] = WeakKeyDictionary()
_AUDIT_LIMIT_PER_ENGINE = 96
_SUPPORT_AUDIT_VERSION = "support_audit_v2"

_CHECKPOINT_AUDIT_METRIC_DIRECTIONS = {
    "TotalDPS": "higher",
    "FullDPS": "higher",
    "CombinedDPS": "higher",
    "AverageDamage": "higher",
    "Speed": "higher",
    "HitChance": "higher",
    "CritChance": "higher",
    "CritMultiplier": "higher",
    "TotalEHP": "higher",
    "LifeRegenRecovery": "higher",
    "EnergyShieldRegenRecovery": "higher",
    "ManaRegenRecovery": "higher",
    "MinionCombinedDPS": "higher",
    "MinionTotalDPS": "higher",
    "ManaCost": "lower",
    "SpiritReserved": "lower",
}

# These are authoritative PoB feasibility decisions, not failed measurements.  A broad tag-based
# corpus screen is expected to contain supports that the live source skill or selected Command
# rejects.  Resource and family conflicts likewise prove that a candidate/combination is currently
# infeasible.  Everything else remains an unexpected failure and keeps the audit inconclusive.
_EXPECTED_SOURCE_REJECTION_CODES = frozenset(
    {
        "source_support_not_applied",
        "source_command_unsupported",
        "spirit_over_reserved",
    }
)
_EXPECTED_SOURCE_COMBINATION_REJECTION_CODES = _EXPECTED_SOURCE_REJECTION_CODES | {
    "duplicate_support_family"
}


def support_audit_for_state(
    engine: Any,
    state_hash: str,
    group_index: int,
) -> dict[str, Any] | None:
    """Return a bounded engine-measured support decision for one unchanged skill group."""

    with _AUDIT_LOCK:
        value = (_SUPPORT_AUDITS.get(engine) or {}).get((state_hash, int(group_index)))
        return deepcopy(value) if value is not None else None


def support_audit_freshness(engine: Any, state_hash: str, group_index: int) -> str:
    """Return current/stale/missing without treating an old receipt as current evidence."""

    with _AUDIT_LOCK:
        try:
            audits = _SUPPORT_AUDITS.get(engine) or {}
        except TypeError:
            return "missing"
        if (state_hash, int(group_index)) in audits:
            return "current"
        if any(key[1] == int(group_index) for key in audits):
            return "stale"
        return "missing"


def _record_support_audit(
    *,
    engine: Any,
    state_hash: str,
    group_index: int,
    skill: str,
    current_supports: list[str],
    recommended_supports: list[str],
    constraints: dict[str, Any],
    measurement: dict[str, Any],
    active_skill_index: int = 1,
    capability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = sorted(set(current_supports))
    recommended = sorted(set(recommended_supports))
    missing = sorted(set(recommended) - set(current))
    measurement_copy = deepcopy(measurement)
    measurement_complete = (
        measurement_copy.get("status") == "complete"
        and measurement_copy.get("checkpointEligible") is True
        and measurement_copy.get("coverageComplete") is True
        and measurement_copy.get("classificationComplete") is True
        and measurement_copy.get("baseMeasurable") is True
        and int(measurement_copy.get("measuredCandidates") or 0) > 0
        and int(measurement_copy.get("classifiedCandidates") or 0)
        == int(measurement_copy.get("screenedCandidates") or 0)
        and int(measurement_copy.get("failedCandidates") or 0) == 0
        and int(measurement_copy.get("failedCombinations") or 0) == 0
        and measurement_copy.get("finalConstraintsSatisfied") is True
    )
    reason_codes = sorted(
        {
            str(value)
            for value in [
                *(measurement_copy.get("reasonCodes") or []),
                measurement_copy.get("reasonCode"),
                *(measurement_copy.get("candidateFailureCodes") or {}).keys(),
                *(measurement_copy.get("combinationFailureCodes") or {}).keys(),
            ]
            if value
        }
    )
    if measurement_complete:
        reason_class = "actionable_gap" if missing else "none"
        if missing:
            reason_codes.append("positive_gain_supports_missing")
    elif measurement_copy.get("reasonClass") in {
        "capability_gap",
        "evidence_gap",
        "measurement_error",
        "actionable_gap",
    }:
        reason_class = str(measurement_copy["reasonClass"])
    elif (
        int(measurement_copy.get("failedCandidates") or 0) > 0
        or int(measurement_copy.get("failedCombinations") or 0) > 0
        or measurement_copy.get("baseFailureCode")
    ):
        reason_class = "measurement_error"
    else:
        reason_class = "evidence_gap"
    status = (
        "passed"
        if reason_class == "none"
        else "failed"
        if reason_class == "actionable_gap"
        else "inconclusive"
    )
    audit = {
        "auditVersion": _SUPPORT_AUDIT_VERSION,
        "status": status,
        "reasonClass": reason_class,
        "reasonCodes": sorted(set(reason_codes)),
        "verificationRequired": reason_class == "capability_gap",
        "skill": skill,
        "groupIndex": int(group_index),
        "activeSkillIndex": int(active_skill_index),
        "currentSupports": current,
        "recommendedSupports": recommended,
        "positiveGainSupportsMissing": missing,
        "constraints": deepcopy(constraints),
        "measurement": measurement_copy,
        "capability": deepcopy(capability or {}),
        "stateHash": state_hash,
    }
    with _AUDIT_LOCK:
        engine_audits = _SUPPORT_AUDITS.setdefault(engine, {})
        existing = engine_audits.get((state_hash, int(group_index)))
        if (
            existing is not None
            and existing.get("status") == "failed"
            and audit["status"] != "failed"
        ):
            return audit
        engine_audits[(state_hash, int(group_index))] = deepcopy(audit)
        while len(engine_audits) > _AUDIT_LIMIT_PER_ENGINE:
            engine_audits.pop(next(iter(engine_audits)))
    return audit


def carry_support_audit_to_configured_state(
    *,
    engine: Any,
    before_state_hash: str,
    after_state_hash: str,
    group_index: int,
    applied_supports: list[str],
) -> dict[str, Any] | None:
    """Carry a measured recommendation only when the configured supports match it exactly."""

    previous = support_audit_for_state(engine, before_state_hash, group_index)
    if (
        previous is None
        or previous.get("status") not in {"passed", "failed"}
        or (previous.get("measurement") or {}).get("status") != "complete"
        or (previous.get("measurement") or {}).get("checkpointEligible") is not True
        or sorted(set(applied_supports)) != sorted(set(previous.get("recommendedSupports") or []))
    ):
        return None
    return _record_support_audit(
        engine=engine,
        state_hash=after_state_hash,
        group_index=group_index,
        skill=str(previous.get("skill") or ""),
        current_supports=applied_supports,
        recommended_supports=list(previous.get("recommendedSupports") or []),
        constraints=dict(previous.get("constraints") or {}),
        measurement=dict(previous.get("measurement") or {}),
        active_skill_index=int(previous.get("activeSkillIndex") or 1),
        capability=dict(previous.get("capability") or {}),
    )


def _support_evaluation_capability(
    engine: Any,
    *,
    group_index: int,
    active_skill_index: int,
    objective_keys: list[str],
    selected_group: dict[str, Any],
) -> dict[str, Any]:
    """Read target-bound PoB capability, using names only as a fail-closed legacy hint."""

    try:
        result = engine.call(
            "inspect_support_evaluation_capability",
            index=int(group_index),
            activeIndex=int(active_skill_index),
            objectiveKeys=list(objective_keys),
        )
    except Exception:  # noqa: BLE001 - an old bridge may not expose the internal method.
        result = None
    if isinstance(result, dict) and result.get("ok") is True:
        return dict(result)
    trigger_names = sorted(
        {
            str(gem.get("name") or "")
            for gem in selected_group.get("gems") or []
            if isinstance(gem, dict)
            and str(gem.get("name") or "") in modelability.CORE_META_TRIGGERS
        }
    )
    if trigger_names:
        return {
            "ok": True,
            "applicationCheck": "unknown",
            "numericRanking": "unsupported",
            "triggerRate": "unmodelled",
            "reasonCodes": ["trigger_rate_unmodelled", "support_application_unverified"],
            "capabilitySource": "legacy_name_fallback",
            "unmodelledMechanics": trigger_names,
        }
    return {
        "ok": False,
        "applicationCheck": "unknown",
        "numericRanking": "supported",
        "triggerRate": "unknown",
        "reasonCodes": [
            str((result or {}).get("errorCode") or "support_capability_inspection_failed")
        ],
        "capabilitySource": "pob_runtime",
    }


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _finite_num(x: Any) -> bool:
    return _num(x) and math.isfinite(float(x))


def _support_capacity(group: dict[str, Any]) -> int:
    gems = group.get("gems") if isinstance(group.get("gems"), list) else []
    root = gems[0] if gems and isinstance(gems[0], dict) else {}
    level = int(root.get("level") or 1)
    if level >= 20:
        return 5
    if level >= 15:
        return 4
    if level >= 10:
        return 3
    return 2


def _r2(x: Any) -> Any:
    return round(x, 2) if _num(x) else x


def _screen_set(skill: str, screen: int) -> list[str]:
    """Tag-relevant supports to solo-screen: recommended + on-element first, then delivery, deduped
    and bounded to `screen`.

    On-element supports (those sharing the skill's damage type) lead so they survive the bound — they
    include the premier levers (penetration, added/increased element damage) that a tag-COUNT ranking
    buries, because such a support often shares ONLY the element tag and so looks "least relevant".
    """
    info = db.find_supports_for(skill, limit=9999)
    rec = info.get("recommended") or []
    comp = info.get("compatible") or []
    on_elem = [c["name"] for c in comp if c.get("on_element")]
    delivery = [c["name"] for c in comp if not c.get("on_element")]
    out: list[str] = []
    seen: set[str] = set()
    for nm in (*rec, *on_elem, *delivery):
        if nm and nm not in seen:
            seen.add(nm)
            out.append(nm)
    return out[: max(screen, 1)]


def _optimize_supports_locked(
    engine: PobEngine,
    metric: str = "TotalDPS",
    goals: dict[str, float] | None = None,
    max_supports: int = 5,
    candidates: int = 9999,
    screen: int = 9999,
    group_index: int | None = None,
    expected_fingerprint: str | None = None,
    max_mana_cost: float | None = None,
    spirit_limit: float | None = None,
) -> dict[str, Any]:
    """Greedily choose the best support-gem set for the active main skill (engine-measured).

    `goals` (weighted, e.g. {"TotalDPS":.7,"TotalEHP":.3}) blends objectives; omit for single
    `metric`. Builds the candidate pool by MEASUREMENT, not tags: it solo-measures the skill's
    tag-relevant supports (`screen` of them; on-element supports — those sharing the skill's damage
    type, like penetration — are always included), keeps the strongest `candidates`, then greedily
    adds the support that most improves the goal each round until the sockets are full or nothing
    helps (over-cap gems are ignored, so they show no gain). Read-only: the build is restored.
    """
    snapshot = engine.get_xml()
    state_hash = build_state_hash(snapshot)
    listed = engine.call("list_skill_groups")
    selected_group_index = int(group_index or listed.get("mainGroupIndex") or 1)
    group = next(
        (
            item
            for item in listed.get("groups") or []
            if int(item.get("index") or 0) == selected_group_index
        ),
        None,
    )
    if group is None:
        return {"ok": False, "errorCode": "skill_group_not_found"}
    selected_group = dict(group)
    if expected_fingerprint:
        from .skillgroups import _decorate  # local import avoids a module cycle at import time

        decorated = _decorate(listed, state_hash=state_hash)
        decorated_group = next(
            item
            for item in decorated.get("groups") or []
            if int(item.get("index") or 0) == selected_group_index
        )
        if decorated_group.get("fingerprint") != expected_fingerprint:
            return {"ok": False, "errorCode": "skill_group_conflict"}
    if group_index is not None:
        selected = engine.call("set_skill_group_state", index=group_index, makeMain=True)
        if not isinstance(selected, dict) or selected.get("ok") is False:
            engine.load_build_xml(snapshot)
            return {"ok": False, "errorCode": "skill_group_selection_failed"}

    grp = engine.get_build().get("mainSkillGroup") or []
    if not grp:
        engine.load_build_xml(snapshot)
        return {"ok": False, "error": "No active main skill — set_skill first."}
    head = grp[0]
    source_skill = str(head["name"])
    lvl, qual = head.get("level", 20), head.get("quality", 0)
    source = str(selected_group.get("source") or "")
    source_kind = str(selected_group.get("sourceKind") or "").casefold()
    configurable_source = (source.startswith("Tree:") and source_kind == "tree") or (
        source.startswith("Item:") and source_kind == "item"
    )
    if selected_group.get("noSupports"):
        engine.load_build_xml(snapshot)
        return {
            "ok": False,
            "errorCode": "source_skill_no_supports",
            "source": source or None,
        }
    if source and not configurable_source:
        engine.load_build_xml(snapshot)
        return {
            "ok": False,
            "errorCode": "source_skill_supports_not_modelable",
            "source": source,
            "modelabilityBlocker": True,
        }
    skill = (
        str(selected_group.get("activeSkill") or source_skill)
        if configurable_source
        else source_skill
    )
    source_active_index = int(
        selected_group.get("mainActiveSkillCalcs") or selected_group.get("mainActiveSkill") or 1
    )
    current_supports = [
        str(gem.get("name"))
        for gem in selected_group.get("gems") or []
        if isinstance(gem, dict) and gem.get("isSupport") and gem.get("name")
    ]
    weights: dict[str, float] = {}
    if goals is not None:
        if not goals or any(
            not _finite_num(value) or float(value) <= 0 for value in goals.values()
        ):
            engine.load_build_xml(snapshot)
            return {
                "ok": False,
                "errorCode": "invalid_goals",
                "error": "goals must map stat names to finite positive weights",
            }
        weights = {str(key): float(value) for key, value in goals.items()}
    keys = list(weights) if weights else [metric]
    metric_directions = {key: _CHECKPOINT_AUDIT_METRIC_DIRECTIONS.get(key) for key in keys}
    checkpoint_objective_eligible = (
        all(direction == "higher" for direction in metric_directions.values())
        if weights
        else metric_directions.get(metric) in {"higher", "lower"}
    )
    single_metric_direction = metric_directions.get(metric) or "higher"
    measurement_keys = list(keys)
    if max_mana_cost is not None and "ManaCost" not in measurement_keys:
        measurement_keys.append("ManaCost")
    if spirit_limit is not None and "SpiritReserved" not in measurement_keys:
        measurement_keys.append("SpiritReserved")

    capability = _support_evaluation_capability(
        engine,
        group_index=selected_group_index,
        active_skill_index=source_active_index,
        objective_keys=keys,
        selected_group=selected_group,
    )
    if capability.get("numericRanking") in {"unsupported", "unknown"}:
        reason_codes = [str(value) for value in capability.get("reasonCodes") or [] if value]
        application_check = str(capability.get("applicationCheck") or "unknown")
        if application_check == "failed" or "trigger_rate_zero_or_inactive" in reason_codes:
            reason_class = "actionable_gap"
        elif (
            capability.get("numericRanking") == "unsupported"
            and capability.get("triggerRate") == "unmodelled"
            and application_check in {"verified", "not_applicable"}
            and capability.get("capabilitySource") == "pob_runtime"
        ):
            reason_class = "capability_gap"
        elif capability.get("numericRanking") == "unknown":
            reason_class = "measurement_error"
        else:
            reason_class = "evidence_gap"
        measurement = {
            "status": "inconclusive",
            "checkpointEligible": False,
            "policyReason": reason_codes[0] if reason_codes else "support_capability_incomplete",
            "reasonCode": reason_codes[0] if reason_codes else "support_capability_incomplete",
            "reasonCodes": reason_codes,
            "reasonClass": reason_class,
            "baseMeasurable": False,
            "coverageComplete": True,
            "classificationComplete": True,
            "supportCapacity": _support_capacity(selected_group),
            "maxSupports": max_supports,
            "candidateLimit": candidates,
            "totalRelevantCandidates": 0,
            "screenedCandidates": 0,
            "measuredCandidates": 0,
            "rejectedCandidates": 0,
            "classifiedCandidates": 0,
            "failedCandidates": 0,
            "rejectedCombinations": 0,
            "failedCombinations": 0,
            "changedCandidates": 0,
            "finalConstraintsSatisfied": application_check != "failed",
            "objectiveKeys": list(keys),
            "objectiveDirections": metric_directions,
            "measurementKeys": list(measurement_keys),
        }
        engine.load_build_xml(snapshot, name="support-capability-restore")
        restored_state_hash = build_state_hash(engine.get_xml())
        if restored_state_hash != state_hash:
            return {
                "ok": False,
                "errorCode": "support_optimizer_state_restore_failed",
                "expectedStateHash": state_hash,
                "actualStateHash": restored_state_hash,
            }
        audit = _record_support_audit(
            engine=engine,
            state_hash=restored_state_hash,
            group_index=selected_group_index,
            skill=str(skill),
            current_supports=current_supports,
            recommended_supports=current_supports,
            constraints={"maxManaCost": max_mana_cost, "spiritLimit": spirit_limit},
            measurement=measurement,
            active_skill_index=source_active_index,
            capability=capability,
        )
        return {
            "ok": False,
            "errorCode": "support_optimization_inconclusive",
            "reasonCode": measurement["reasonCode"],
            "reasonClass": reason_class,
            "skill": skill,
            "source": selected_group.get("source"),
            "groupIndex": selected_group_index,
            "activeSkillIndex": source_active_index,
            "stateHash": restored_state_hash,
            "capability": capability,
            "measurement": measurement,
            "supportAudit": audit,
        }

    all_screen_names = _screen_set(source_skill if configurable_source else skill, 999999)
    screen_names = all_screen_names[:screen]
    if not all_screen_names:
        engine.load_build_xml(snapshot)
        return {"ok": False, "error": f"No supports found for '{skill}'."}
    support_capacity = _support_capacity(selected_group)
    effective_max_supports = min(max_supports, support_capacity)

    try:

        def measure(supports: list[str]) -> tuple[dict[str, Any], str, str | None]:
            if configurable_source:
                support_ids: list[str] = []
                support_gems: list[dict[str, Any]] = []
                for name in supports:
                    gem = db.get_gem(name)
                    if gem is None or str(gem.get("gem_type") or "").lower() != "support":
                        return {}, "failed", "support_gem_lookup_failed"
                    support_ids.append(str(gem["id"]))
                    support_gems.append(gem)
                engine.load_build_xml(snapshot, name="source-support-measurement-reset")
                select_params: dict[str, Any] = {
                    "index": selected_group_index,
                    "makeMain": True,
                    "activeSkillIndex": source_active_index,
                }
                selected = engine.call("set_skill_group_state", **select_params)
                if not isinstance(selected, dict) or selected.get("ok") is False:
                    code = (
                        str(selected.get("errorCode") or "skill_group_selection_failed")
                        if isinstance(selected, dict)
                        else "invalid_skill_group_selection_result"
                    )
                    return {}, "failed", code
                configured = engine.call(
                    "configure_source_skill_supports",
                    index=select_params["index"],
                    supportGemIds=support_ids,
                )
                if not isinstance(configured, dict) or configured.get("ok") is False:
                    code = (
                        str(configured.get("errorCode") or "source_support_configuration_failed")
                        if isinstance(configured, dict)
                        else "invalid_source_support_configuration_result"
                    )
                    unavailable_solo_candidate = (
                        len(supports) == 1 and code == "invalid_support_gem"
                    )
                    known_topology_candidate = (
                        len(supports) == 1
                        and code == "source_group_count_changed"
                        and any(
                            "grants_active_skill" in (gem.get("tags") or []) for gem in support_gems
                        )
                    )
                    expected_codes = (
                        _EXPECTED_SOURCE_COMBINATION_REJECTION_CODES
                        if len(supports) > 1
                        else _EXPECTED_SOURCE_REJECTION_CODES
                    )
                    outcome = (
                        "rejected"
                        if bool(supports)
                        and (
                            code in expected_codes
                            or unavailable_solo_candidate
                            or known_topology_candidate
                        )
                        else "failed"
                    )
                    return {}, outcome, code
                measured = engine.get_stats(measurement_keys)
                stats = measured.get("stats") if isinstance(measured, dict) else None
                if not isinstance(stats, dict):
                    return {}, "failed", "support_stats_missing"
                return stats, "measured", None
            text = f"{skill} {lvl}/{qual} 1"
            if supports:
                text += "\n" + "\n".join(supports)
            r = engine.paste_skill(text)
            st = r.get("stats") if isinstance(r, dict) else None
            if not isinstance(st, dict):
                code = (
                    str(r.get("errorCode") or "support_stats_missing")
                    if isinstance(r, dict)
                    else "invalid_support_measurement_result"
                )
                return {}, "failed", code
            return st, "measured", None

        base_stats, base_outcome, base_error = measure([])  # skill alone = the baseline

        def measurement_valid(stats: dict[str, Any]) -> bool:
            return any(_finite_num(stats.get(key)) for key in keys)

        def audit_measurement_valid(stats: dict[str, Any]) -> bool:
            return all(_finite_num(stats.get(key)) for key in measurement_keys)

        def constraints_satisfied(stats: dict[str, Any]) -> bool:
            return (
                max_mana_cost is None
                or (
                    _finite_num(stats.get("ManaCost"))
                    and float(stats["ManaCost"]) <= float(max_mana_cost)
                )
            ) and (
                spirit_limit is None
                or (
                    _finite_num(stats.get("SpiritReserved"))
                    and float(stats["SpiritReserved"]) <= float(spirit_limit)
                )
            )

        denom = {k: max(abs(base_stats.get(k) or 0.0), 1.0) for k in keys}

        def score(st: dict[str, Any]) -> float:
            if not measurement_valid(st):
                return float("-inf")
            if max_mana_cost is not None:
                if not _finite_num(st.get("ManaCost")) or float(st["ManaCost"]) > float(
                    max_mana_cost
                ):
                    return float("-inf")
            if spirit_limit is not None:
                if not _finite_num(st.get("SpiritReserved")) or float(st["SpiritReserved"]) > float(
                    spirit_limit
                ):
                    return float("-inf")
            if weights:
                return sum(
                    w * ((st.get(k) or 0.0) - (base_stats.get(k) or 0.0)) / denom[k]
                    for k, w in weights.items()
                )
            v = st.get(metric)
            if _finite_num(v):
                return -float(v) if single_metric_direction == "lower" else float(v)
            return float("-inf")

        # Candidate pool by MEASUREMENT, not tag count. A support's shared-tag count is a poor proxy
        # for value — top DPS levers like penetration or added-damage often share only the element
        # tag and would be truncated out of a tag-ranked list. So solo-measure each tag-relevant
        # support and keep the strongest `candidates` for the combo-aware greedy below. This is what
        # lets the search find e.g. Lightning Penetration on a lightning skill.
        base_sc = score(base_stats)
        screened: list[tuple[float, str]] = []
        measured_candidate_count = 0
        fully_measured_candidate_count = 0
        rejected_candidate_count = 0
        failed_candidate_count = 0
        changed_candidate_count = 0
        candidate_rejection_codes: dict[str, int] = {}
        candidate_failure_codes: dict[str, int] = {}
        observed_objective_keys = {key for key in keys if _finite_num(base_stats.get(key))}

        def count_code(counts: dict[str, int], code: str | None, fallback: str) -> None:
            key = str(code or fallback)
            counts[key] = counts.get(key, 0) + 1

        for name in screen_names:
            measured_stats, outcome, error_code = measure([name])
            if outcome == "rejected":
                rejected_candidate_count += 1
                count_code(candidate_rejection_codes, error_code, "source_support_rejected")
                continue
            if outcome != "measured":
                failed_candidate_count += 1
                count_code(candidate_failure_codes, error_code, "support_measurement_failed")
                continue
            if measurement_valid(measured_stats):
                measured_candidate_count += 1
                observed_objective_keys.update(
                    key for key in keys if _finite_num(measured_stats.get(key))
                )
            if audit_measurement_valid(measured_stats):
                fully_measured_candidate_count += 1
                if audit_measurement_valid(base_stats) and any(
                    abs(float(measured_stats[key]) - float(base_stats[key])) > 1e-9 for key in keys
                ):
                    changed_candidate_count += 1
            else:
                failed_candidate_count += 1
                count_code(candidate_failure_codes, None, "incomplete_candidate_stats")
            screened.append((score(measured_stats), name))
        screened.sort(key=lambda item: item[0], reverse=True)
        base_measurable = all(key in observed_objective_keys for key in keys)
        pool = [nm for sc, nm in screened if sc > base_sc + 1e-9][:candidates]

        chosen: list[str] = []
        cur = base_sc
        progression: list[dict[str, Any]] = []
        rejected_combination_count = 0
        failed_combination_count = 0
        combination_rejection_codes: dict[str, int] = {}
        combination_failure_codes: dict[str, int] = {}
        while len(chosen) < effective_max_supports:
            best_nm, best_sc, best_st = None, cur, None
            for nm in pool:
                if nm in chosen:
                    continue
                st, outcome, error_code = measure(chosen + [nm])
                if outcome == "rejected":
                    rejected_combination_count += 1
                    count_code(
                        combination_rejection_codes,
                        error_code,
                        "source_support_combination_rejected",
                    )
                    continue
                if outcome != "measured":
                    failed_combination_count += 1
                    count_code(
                        combination_failure_codes,
                        error_code,
                        "support_combination_measurement_failed",
                    )
                    continue
                if not audit_measurement_valid(st):
                    failed_combination_count += 1
                    count_code(
                        combination_failure_codes,
                        None,
                        "incomplete_combination_stats",
                    )
                    continue
                sc = score(st)
                if sc > best_sc + 1e-9:
                    best_nm, best_sc, best_st = nm, sc, st
            if best_nm is None:
                break  # nothing improves, or sockets full (extra gems ignored -> no gain)
            chosen.append(best_nm)
            cur = best_sc
            progression.append({"added": best_nm, **{k: _r2((best_st or {}).get(k)) for k in keys}})
        final_stats, final_outcome, final_error = measure(chosen)
        if final_outcome != "measured" or not audit_measurement_valid(final_stats):
            failed_combination_count += 1
            count_code(
                combination_failure_codes,
                final_error,
                "incomplete_final_combination_stats",
            )
    finally:
        engine.load_build_xml(snapshot)
    restored_state_hash = build_state_hash(engine.get_xml())
    if restored_state_hash != state_hash:
        return {
            "ok": False,
            "errorCode": "support_optimizer_state_restore_failed",
            "expectedStateHash": state_hash,
            "actualStateHash": restored_state_hash,
        }

    coverage_complete = (
        max_supports >= support_capacity
        and len(screen_names) == len(all_screen_names)
        and candidates >= len(screen_names)
    )
    base_fully_measurable = base_outcome == "measured" and audit_measurement_valid(base_stats)
    classified_candidate_count = (
        fully_measured_candidate_count + rejected_candidate_count + failed_candidate_count
    )
    classification_complete = classified_candidate_count == len(screen_names)
    final_constraints_satisfied = constraints_satisfied(final_stats)
    checkpoint_eligible = (
        checkpoint_objective_eligible
        and coverage_complete
        and classification_complete
        and base_fully_measurable
        and fully_measured_candidate_count > 0
        and fully_measured_candidate_count + rejected_candidate_count == len(screen_names)
        and changed_candidate_count > 0
        and failed_candidate_count == 0
        and failed_combination_count == 0
        and final_constraints_satisfied
    )
    measurement = {
        "status": "complete" if checkpoint_eligible else "inconclusive",
        "checkpointEligible": checkpoint_eligible,
        "policyReason": None if checkpoint_eligible else "support_audit_policy_not_satisfied",
        "baseMeasurable": base_fully_measurable,
        "baseFailureCode": None if base_outcome == "measured" else base_error,
        "coverageComplete": coverage_complete,
        "classificationComplete": classification_complete,
        "supportCapacity": support_capacity,
        "maxSupports": max_supports,
        "candidateLimit": candidates,
        "totalRelevantCandidates": len(all_screen_names),
        "screenedCandidates": len(screen_names),
        "measuredCandidates": fully_measured_candidate_count,
        "rejectedCandidates": rejected_candidate_count,
        "classifiedCandidates": classified_candidate_count,
        "failedCandidates": failed_candidate_count,
        "candidateRejectionCodes": dict(sorted(candidate_rejection_codes.items())),
        "candidateFailureCodes": dict(sorted(candidate_failure_codes.items())),
        "rejectedCombinations": rejected_combination_count,
        "failedCombinations": failed_combination_count,
        "combinationRejectionCodes": dict(sorted(combination_rejection_codes.items())),
        "combinationFailureCodes": dict(sorted(combination_failure_codes.items())),
        "changedCandidates": changed_candidate_count,
        "finalConstraintsSatisfied": final_constraints_satisfied,
        "objectiveKeys": list(keys),
        "objectiveDirections": metric_directions,
        "measurementKeys": list(measurement_keys),
    }
    optimizer_measurable = base_measurable and measured_candidate_count > 0
    if not optimizer_measurable:
        audit = _record_support_audit(
            engine=engine,
            state_hash=restored_state_hash,
            group_index=selected_group_index,
            skill=str(skill),
            current_supports=current_supports,
            recommended_supports=chosen,
            constraints={"maxManaCost": max_mana_cost, "spiritLimit": spirit_limit},
            measurement=measurement,
            active_skill_index=source_active_index,
            capability=capability,
        )
        return {
            "ok": False,
            "errorCode": "support_optimization_inconclusive",
            "skill": skill,
            "source": selected_group.get("source"),
            "groupIndex": selected_group_index,
            "stateHash": restored_state_hash,
            "capability": capability,
            "measurement": measurement,
            "supportAudit": audit,
        }

    out: dict[str, Any] = {
        "ok": True,
        "skill": skill,
        "sourceSkill": source_skill if configurable_source else None,
        "source": selected_group.get("source"),
        "supports": chosen,
        "screened": len(screen_names),
        "candidatesTried": len(pool),
        "groupIndex": selected_group_index,
        "stateHash": restored_state_hash,
        "capability": capability,
        "constraints": {
            "maxManaCost": max_mana_cost,
            "spiritLimit": spirit_limit,
        },
        "progression": progression,
        "measurement": measurement,
        "note": (
            "Engine search — each support is valued empirically in the real source group. "
            "Apply the result with configure_source_skill_supports and its current fingerprint. "
            "Greedy, not a global optimum."
            if configurable_source
            else (
                "Engine search — each support is valued empirically (the corpus has no support "
                "magnitudes). The pool is chosen by MEASUREMENT not tags: every tag-relevant support "
                "is solo-measured and the strongest kept, then combined greedily. Stops when nothing "
                "helps or sockets are full. Apply with set_skill. Greedy, not a global optimum."
            )
        ),
    }
    if weights:
        out["goals"] = weights
        out["metricsBase"] = {k: _r2(base_stats.get(k)) for k in keys}
        out["metricsFinal"] = {k: _r2(final_stats.get(k)) for k in keys}
    else:
        out["metric"] = metric
        out["baseValue"] = _r2(base_stats.get(metric))
        out["finalValue"] = _r2(final_stats.get(metric))
    if not chosen:
        out["warning"] = (
            "No support improved the skill — its DPS may be uncomputable (e.g. an attack with no "
            "weapon equipped; equip a weapon first), or the candidates don't fit/help."
        )
    out["supportAudit"] = _record_support_audit(
        engine=engine,
        state_hash=restored_state_hash,
        group_index=selected_group_index,
        skill=str(skill),
        current_supports=current_supports,
        recommended_supports=chosen,
        constraints=out["constraints"],
        measurement=measurement,
        active_skill_index=source_active_index,
        capability=capability,
    )
    return out


def optimize_supports(
    engine: PobEngine,
    metric: str = "TotalDPS",
    goals: dict[str, float] | None = None,
    max_supports: int = 5,
    candidates: int = 9999,
    screen: int = 9999,
    group_index: int | None = None,
    expected_fingerprint: str | None = None,
    max_mana_cost: float | None = None,
    spirit_limit: float | None = None,
) -> dict[str, Any]:
    """Run one read-only support search under a build-wide transaction and restore guard."""

    if (
        isinstance(max_supports, bool)
        or not isinstance(max_supports, int)
        or not 1 <= max_supports <= 5
    ):
        return {
            "ok": False,
            "errorCode": "invalid_max_supports",
            "error": "max_supports must be between 1 and 5",
        }
    for name, value in (("candidates", candidates), ("screen", screen)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return {
                "ok": False,
                "errorCode": f"invalid_{name}",
                "error": f"{name} must be at least 1",
            }
    for name, value in (("max_mana_cost", max_mana_cost), ("spirit_limit", spirit_limit)):
        if value is not None and (not _finite_num(value) or float(value) < 0):
            return {
                "ok": False,
                "errorCode": f"invalid_{name}",
                "error": f"{name} must be a finite non-negative number",
            }

    with engine.transaction_lock():
        snapshot = engine.get_xml()
        expected_state_hash = build_state_hash(snapshot)
        try:
            result = _optimize_supports_locked(
                engine,
                metric=metric,
                goals=goals,
                max_supports=max_supports,
                candidates=candidates,
                screen=screen,
                group_index=group_index,
                expected_fingerprint=expected_fingerprint,
                max_mana_cost=max_mana_cost,
                spirit_limit=spirit_limit,
            )
        finally:
            if build_state_hash(engine.get_xml()) != expected_state_hash:
                engine.load_build_xml(snapshot, name="support-optimizer-outer-restore")
        actual_state_hash = build_state_hash(engine.get_xml())
        if actual_state_hash != expected_state_hash:
            return {
                "ok": False,
                "errorCode": "support_optimizer_state_restore_failed",
                "expectedStateHash": expected_state_hash,
                "actualStateHash": actual_state_hash,
            }
        return result
