"""Support-gem set optimizer (engine search; needs no magnitude data).

Greedily picks the support gems that most raise a metric (or weighted goals) for the active main
skill, measuring each combination on the real engine. The corpus has support-gem identity but not
effect magnitudes. This bounded mechanical search ranks only engine-modelled objectives.
Unmodelled capabilities retain the current package for Agent mechanism review; they do not mean
zero benefit or lower adoption value. Agent scenario estimates remain separate from these metrics.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math
import threading
from typing import Any
from weakref import WeakKeyDictionary
from xml.etree import ElementTree as ET
from xml.parsers import expat

from ..knowledge import db
from ..knowledge.skill_equivalence import SkillEquivalenceIndex
from ..judge import hard_legality, modelability
from .engine import PobEngine
from .state import build_state_hash, canonical_payload_hash


_AUDIT_LOCK = threading.RLock()
_SUPPORT_AUDITS: WeakKeyDictionary[Any, dict[tuple[str, int], dict[str, Any]]] = WeakKeyDictionary()
_AUDIT_LIMIT_PER_ENGINE = 96
_SUPPORT_AUDIT_VERSION = "support_audit_v3"

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
        "support_usage_condition_changed",
    }
)
_EXPECTED_SOURCE_COMBINATION_REJECTION_CODES = _EXPECTED_SOURCE_REJECTION_CODES | {
    "duplicate_support_family"
}


def support_capability_is_rate_only_gap(capability: Any) -> bool:
    """Recognize the rate-only subset of native model gaps."""
    if not isinstance(capability, dict):
        return False
    reasons = capability.get("reasonCodes")
    return (
        capability.get("capabilitySource") == "pob_runtime"
        and capability.get("applicationCheck") in {"verified", "not_applicable"}
        and capability.get("numericRanking") == "unsupported"
        and capability.get("triggerRate") == "unmodelled"
        and isinstance(reasons, list)
        and all(isinstance(reason, str) for reason in reasons)
        and set(reasons) == {"trigger_rate_unmodelled"}
        and capability.get("declaredDamageModel") in (None, "not_flagged_incomplete")
    )


def support_capability_is_model_gap(capability: Any) -> bool:
    """Known native model gaps permit candidate review, never numeric ranking or a pass."""
    if support_capability_is_rate_only_gap(capability):
        return True
    if not isinstance(capability, dict):
        return False
    reasons = capability.get("reasonCodes")
    if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
        return False
    rate = capability.get("triggerRate")
    expected = {"declared_duration_dot_model_missing"}
    if rate == "unmodelled":
        expected.add("trigger_rate_unmodelled")
    return (
        capability.get("capabilitySource") == "pob_runtime"
        and capability.get("applicationCheck") in {"verified", "not_applicable"}
        and capability.get("numericRanking") == "unsupported"
        and capability.get("declaredDamageModel") == "incomplete"
        and rate in {"not_applicable", "unmodelled"}
        and set(reasons) == expected
    )


def support_audit_for_state(
    engine: Any,
    state_hash: str,
    group_index: int,
) -> dict[str, Any] | None:
    """Return a bounded engine-measured support decision for one unchanged skill group."""

    with _AUDIT_LOCK:
        value = (_SUPPORT_AUDITS.get(engine) or {}).get((state_hash, int(group_index)))
        return (
            deepcopy(value)
            if value is not None and value.get("auditVersion") == _SUPPORT_AUDIT_VERSION
            else None
        )


def support_audit_freshness(engine: Any, state_hash: str, group_index: int) -> str:
    """Return current/stale/missing without treating an old receipt as current evidence."""

    with _AUDIT_LOCK:
        try:
            audits = _SUPPORT_AUDITS.get(engine) or {}
        except TypeError:
            return "missing"
        if (
            audits.get((state_hash, int(group_index)), {}).get("auditVersion")
            == _SUPPORT_AUDIT_VERSION
        ):
            return "current"
        if any(key[1] == int(group_index) for key in audits):
            return "stale"
        return "missing"


def support_audit_is_complete(audit: dict[str, Any]) -> bool:
    """Shared checkpoint gate: screening coverage never substitutes for a whole-set comparison."""

    measurement = audit.get("measurement") or {}
    comparison = measurement.get("combinationComparison") or {}
    baseline_score = comparison.get("baselineScore")
    candidate_score = comparison.get("candidateScore")
    net_gain = comparison.get("netGain")
    return (
        audit.get("auditVersion") == _SUPPORT_AUDIT_VERSION
        and audit.get("authorizationRevoked") is not True
        and measurement.get("status") == "complete"
        and measurement.get("checkpointEligible") is True
        and measurement.get("coverageComplete") is True
        and measurement.get("classificationComplete") is True
        and _usage_condition_contract(measurement) is not None
        and measurement.get("currentCombinationMeasurable") is True
        and int(measurement.get("measuredCandidates") or 0) > 0
        and int(measurement.get("classifiedCandidates") or 0)
        == int(measurement.get("screenedCandidates") or 0)
        and int(measurement.get("failedCandidates") or 0) == 0
        and int(measurement.get("failedCombinations") or 0) == 0
        and measurement.get("finalConstraintsSatisfied") is True
        and comparison.get("status") == "complete"
        and comparison.get("baselineMeasurable") is True
        and comparison.get("candidateMeasurable") is True
        and comparison.get("candidateConstraintsSatisfied") is True
        and comparison.get("candidateLegalityNonRegressing") is True
        and comparison.get("sameContext") is True
        and all(_finite_num(value) for value in (baseline_score, candidate_score, net_gain))
        and math.isclose(
            float(net_gain), float(candidate_score) - float(baseline_score), abs_tol=1e-9
        )
        and float(net_gain) >= -1e-9
        and comparison.get("positiveGainProven") is (float(net_gain) > 1e-9)
        and Counter(comparison.get("baselineSupports") or [])
        == Counter(audit.get("currentSupports") or [])
        and Counter(comparison.get("candidateSupports") or [])
        == Counter(audit.get("recommendedSupports") or [])
    )


def _same_support_audit_context(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Compare the exact calculation and objective, not merely the cache's group key."""

    before_measurement = before.get("measurement") or {}
    after_measurement = after.get("measurement") or {}
    objective = before_measurement.get("objectiveSpecification")
    return (
        before.get("auditVersion") == after.get("auditVersion")
        and before.get("stateHash") == after.get("stateHash")
        and before.get("groupIndex") == after.get("groupIndex")
        and before.get("activeSkillIndex") == after.get("activeSkillIndex")
        and before.get("skill") == after.get("skill")
        and objective is not None
        and objective == after_measurement.get("objectiveSpecification")
        and {
            key: (before.get("constraints") or {}).get(key)
            for key in ("maxManaCost", "spiritLimit")
        }
        == {
            key: (after.get("constraints") or {}).get(key) for key in ("maxManaCost", "spiritLimit")
        }
    )


def _supersedes_support_audit(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if not _same_support_audit_context(before, after):
        return False
    previous = before.get("measurement") or {}
    latest = after.get("measurement") or {}
    # An exact current-effect capability failure invalidates its old numerical evidence even
    # before discovery can run. It must not leave the earlier recommendation eligible for carry.
    if latest.get("scopeKind") == "current_effect_capability":
        return True
    if (
        latest.get("coverageComplete") is not True
        or latest.get("classificationComplete") is not True
    ):
        return False
    if previous.get("scopeKind") == "current_effect_capability":
        return True
    return bool(previous.get("searchScopeHash")) and previous.get("searchScopeHash") == latest.get(
        "searchScopeHash"
    )


def _support_audit_diagnostic(audit: dict[str, Any]) -> dict[str, Any]:
    measurement = audit.get("measurement") or {}
    comparison = measurement.get("combinationComparison") or {}
    return {
        "status": audit.get("status"),
        "reasonClass": audit.get("reasonClass"),
        "reasonCodes": list(audit.get("reasonCodes") or []),
        "recommendedSupports": list(audit.get("recommendedSupports") or []),
        "measurementStatus": measurement.get("status"),
        "baselineScore": comparison.get("baselineScore"),
        "candidateScore": comparison.get("candidateScore"),
        "netGain": comparison.get("netGain"),
    }


def _revoke_derived_support_audits(
    audits: dict[tuple[str, int], dict[str, Any]], old_ref: str, replacement_ref: str
) -> None:
    """Withdraw already-carried receipts when their original measurement is superseded."""

    revoked = {old_ref}
    changed = True
    while changed:
        changed = False
        for value in audits.values():
            if (
                value.get("carriedFromAuditRef") not in revoked
                or value.get("auditRef") in revoked
                or (
                    value.get("authorizationRevoked") is True
                    and value.get("revokedByAuditRef") == replacement_ref
                )
            ):
                continue
            if value.get("auditRef"):
                revoked.add(value["auditRef"])
            value["authorizationRevoked"] = True
            value["revokedByAuditRef"] = replacement_ref
            value["status"] = "inconclusive"
            value["reasonClass"] = "measurement_error"
            value["reasonCodes"] = sorted(
                set([*(value.get("reasonCodes") or []), "support_origin_audit_superseded"])
            )
            value["measurement"]["status"] = "inconclusive"
            value["measurement"]["checkpointEligible"] = False
            changed = True


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
    carried_from_ref: str | None = None,
) -> dict[str, Any]:
    current = sorted(current_supports)
    recommended = sorted(recommended_supports)
    measurement_copy = deepcopy(measurement)
    measurement_complete = support_audit_is_complete(
        {
            "auditVersion": _SUPPORT_AUDIT_VERSION,
            "measurement": measurement_copy,
            "currentSupports": current,
            "recommendedSupports": recommended,
        }
    )
    comparison = measurement_copy.get("combinationComparison") or {}
    positive_gain = measurement_complete and comparison.get("positiveGainProven") is True
    missing = sorted((Counter(recommended) - Counter(current)).elements()) if positive_gain else []
    reason_codes = sorted(
        {
            str(value)
            for value in [
                *(measurement_copy.get("reasonCodes") or []),
                measurement_copy.get("reasonCode"),
                measurement_copy.get("currentCombinationFailureCode"),
                *(measurement_copy.get("candidateFailureCodes") or {}).keys(),
                *(measurement_copy.get("combinationFailureCodes") or {}).keys(),
            ]
            if value
        }
    )
    if measurement_complete:
        reason_class = "actionable_gap" if positive_gain else "none"
        if positive_gain:
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
        or measurement_copy.get("currentCombinationFailureCode")
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
        "positiveGainCombinationAvailable": positive_gain,
        "supportsToRemove": (
            sorted((Counter(current) - Counter(recommended)).elements()) if positive_gain else []
        ),
        "constraints": deepcopy(constraints),
        "measurement": measurement_copy,
        "capability": deepcopy(capability or {}),
        "stateHash": state_hash,
    }
    if carried_from_ref is not None:
        audit["carriedFromAuditRef"] = carried_from_ref
    audit["auditRef"] = canonical_payload_hash(audit, prefix="support-audit")
    with _AUDIT_LOCK:
        engine_audits = _SUPPORT_AUDITS.setdefault(engine, {})
        existing = engine_audits.get((state_hash, int(group_index)))
        supersedes = existing is not None and _supersedes_support_audit(existing, audit)
        if (
            existing is not None
            and existing.get("auditVersion") == _SUPPORT_AUDIT_VERSION
            and existing.get("status") == "failed"
            and not supersedes
            and (
                existing.get("positiveGainCombinationAvailable") is True
                or audit["status"] != "failed"
            )
        ):
            return audit
        if supersedes:
            if existing.get("auditRef") and existing["auditRef"] != audit["auditRef"]:
                _revoke_derived_support_audits(
                    engine_audits, existing["auditRef"], audit["auditRef"]
                )
            audit["supersededAuditDiagnostics"] = [
                _support_audit_diagnostic(existing),
                *(existing.get("supersededAuditDiagnostics") or []),
            ][:4]
            audit["supersessionReason"] = (
                "current_effect_capability_rechecked"
                if measurement_copy.get("scopeKind") == "current_effect_capability"
                else "same_context_complete_search_rechecked"
            )
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
        or not support_audit_is_complete(previous)
        or Counter(applied_supports) != Counter(previous.get("recommendedSupports") or [])
    ):
        return None
    measurement = deepcopy(previous["measurement"])
    comparison = measurement["combinationComparison"]
    if build_state_hash(engine.get_xml()) != after_state_hash:
        return None
    listed = engine.call("list_skill_groups")
    configured_group = next(
        (
            group
            for group in listed.get("groups") or []
            if int(group.get("index") or 0) == group_index
        ),
        {},
    )
    if not comparison.get("candidateGroupFingerprint") or (
        _comparison_group_fingerprint(configured_group) != comparison["candidateGroupFingerprint"]
    ):
        return None
    comparison.update(
        baselineSupports=list(applied_supports),
        baselineMetrics=deepcopy(comparison["candidateMetrics"]),
        baselineScore=comparison["candidateScore"],
        baselineConstraintsSatisfied=True,
        netGain=0.0,
        positiveGainProven=False,
        baselineActiveSkillIndex=comparison.get("candidateActiveSkillIndex")
        or previous.get("activeSkillIndex"),
    )
    return _record_support_audit(
        engine=engine,
        state_hash=after_state_hash,
        group_index=group_index,
        skill=str(previous.get("skill") or ""),
        current_supports=applied_supports,
        recommended_supports=list(previous.get("recommendedSupports") or []),
        constraints=dict(previous.get("constraints") or {}),
        measurement=measurement,
        active_skill_index=int(
            comparison.get("candidateActiveSkillIndex") or previous.get("activeSkillIndex") or 1
        ),
        capability=dict(previous.get("capability") or {}),
        carried_from_ref=previous.get("auditRef"),
    )


def _comparison_group_fingerprint(group: dict[str, Any]) -> str:
    # The optimizer temporarily selects the group as main, but does not change its contents.
    normalized = deepcopy(group)
    for gem in normalized.get("gems") or []:
        if gem.get("count") is None:
            gem["count"] = 1
    return canonical_payload_hash(
        {
            key: value
            for key, value in normalized.items()
            if key not in {"index", "isMain", "fingerprint"}
        },
        prefix="support-comparison-group",
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


def _usage_condition_contract(capability: dict[str, Any]) -> tuple[tuple[str, str], ...] | None:
    if capability.get("usageConditionContractVersion") != 1:
        return None
    entries = capability.get("usageConditionContracts")
    if not isinstance(entries, list):
        return None
    if any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("effectId"), str)
        or not entry["effectId"]
        or not isinstance(entry.get("supportEffectId"), str)
        or not entry["supportEffectId"]
        for entry in entries
    ):
        return None
    return tuple(sorted({(entry["effectId"], entry["supportEffectId"]) for entry in entries}))


def _unique_output_index(group: dict[str, Any], skill: str, effect_id: str | None) -> int:
    matches = [
        int(effect.get("index") or 0)
        for effect in group.get("activeSkills") or []
        if effect.get("name") == skill
        and (effect_id is None or effect.get("effectId") == effect_id)
    ]
    if len(matches) != 1 or matches[0] < 1:
        raise ValueError(
            "support_selected_effect_ambiguous"
            if len(matches) > 1
            else "support_selected_effect_changed"
        )
    return matches[0]


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _finite_num(x: Any) -> bool:
    return _num(x) and math.isfinite(float(x))


def _inspect_current_support_constraints(
    engine: Any, *, max_mana_cost: float | None, spirit_limit: float | None
) -> dict[str, Any]:
    """Read known costs at the already-selected exact output even when rate is unmodelled."""

    limits = {
        key: value
        for key, value in (("ManaCost", max_mana_cost), ("SpiritReserved", spirit_limit))
        if value is not None
    }
    result: dict[str, Any] = {
        "status": "not_applicable" if not limits else "passed",
        "satisfied": True,
        "reasonClass": "none",
        "reasonCodes": [],
        "metrics": {},
        "limits": limits,
    }
    if not limits:
        return result
    try:
        measured = engine.get_stats(list(limits))
    except Exception:  # noqa: BLE001 - retain a bounded failure, never exception text.
        measured = None
    if (
        not isinstance(measured, dict)
        or measured.get("ok") is False
        or measured.get("errorCode")
        or measured.get("error")
        or not isinstance(measured.get("stats"), dict)
    ):
        return {
            **result,
            "status": "error",
            "satisfied": False,
            "reasonClass": "measurement_error",
            "reasonCodes": ["support_constraint_measurement_failed"],
        }
    stats = measured["stats"]
    missing = [key for key in limits if stats.get(key) is None]
    invalid = [key for key in limits if key not in missing and not _finite_num(stats[key])]
    result["metrics"] = {key: stats[key] for key in limits if _finite_num(stats.get(key))}
    exceeded = [
        key for key, value in result["metrics"].items() if float(value) > float(limits[key])
    ]
    result["reasonCodes"] = [
        *[f"support_constraint_exceeded:{key}" for key in exceeded],
        *[f"support_constraint_invalid:{key}" for key in invalid],
        *[f"support_constraint_missing:{key}" for key in missing],
    ]
    if exceeded:
        result.update(status="failed", satisfied=False, reasonClass="actionable_gap")
    elif invalid:
        result.update(status="error", satisfied=False, reasonClass="measurement_error")
    elif missing:
        result.update(status="unknown", satisfied=False, reasonClass="evidence_gap")
    return result


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
    return round(x, 2) if _finite_num(x) else None if _num(x) else x


def _regular_probe_xml(
    snapshot: str,
    group_index: int,
    group: dict[str, Any],
    supports: list[str],
    identities: dict[str, dict[str, Any]] | None = None,
    *,
    group_only: bool = False,
) -> str:
    """Change only supports in the original group, preserving every active-gem/config setting.

    PoB resolves the new support names on import; the caller must verify the complete readback.
    Existing support gems retain their exact quality, enabled state and other persisted settings.
    """

    root = ET.fromstring(snapshot)
    skills = root.find("Skills")
    if skills is None:
        raise ValueError("support_group_snapshot_missing")
    sets = skills.findall("SkillSet")
    if sets:
        active_id = int(skills.get("activeSkillSet") or "1")
        active_sets = [item for item in sets if int(item.get("id") or "0") == active_id]
        if len(active_sets) != 1:
            raise ValueError("support_group_snapshot_ambiguous")
        skills = active_sets[0]
    groups = skills.findall("Skill")
    if not 1 <= group_index <= len(groups):
        raise ValueError("support_group_snapshot_missing")
    target = groups[group_index - 1]
    gems = target.findall("Gem")
    observed = group.get("gems") or []
    if [gem.get("nameSpec") for gem in gems] != [gem.get("name") for gem in observed]:
        raise ValueError("support_group_snapshot_mismatch")
    # PoB stores literal attribute newlines (notably customMods), while ElementTree would
    # normalize them and PoB's XML reader drops numeric entities. Splice only support Gem
    # elements in the original bytes; all other inputs, including active gems, stay exact.
    raw = snapshot.encode("utf-8")
    ordinal = list(root.iter("Skill")).index(target)
    span = _skill_xml_span(raw, ordinal)
    gem_spans = [child for child in span["children"] if child["tag"] == "Gem"]
    if len(gem_spans) != len(observed) or span.get("close") is None:
        raise ValueError("support_group_snapshot_mismatch")
    current: dict[str, list[bytes]] = {}
    pieces: list[bytes] = []
    cursor = span["start"]
    for node_span, gem in zip(gem_spans, observed, strict=True):
        if gem.get("isSupport"):
            current.setdefault(str(gem["name"]), []).append(
                raw[node_span["start"] : node_span["end"]]
            )
            pieces.append(raw[cursor : node_span["start"]])
            cursor = node_span["end"]
    pieces.append(raw[cursor : span["close"]])
    for name in supports:
        retained = current.get(name) or []
        if retained:
            pieces.append(retained.pop(0))
        else:
            identity = (identities or {}).get(name) or {}
            node = ET.Element(
                "Gem",
                nameSpec=name,
                level=str(identity.get("naturalMaxLevel") or 1),
                quality="20",
                enabled="true",
                count="1",
                enableGlobal1="true",
                enableGlobal2="true",
            )
            if identity.get("gemId"):
                node.set("gemId", str(identity["gemId"]))
            pieces.append(ET.tostring(node, encoding="utf-8"))
    pieces.append(raw[span["close"] : span["end"]])
    replacement = b"".join(pieces)
    return (
        replacement if group_only else raw[: span["start"]] + replacement + raw[span["end"] :]
    ).decode("utf-8")


def _skill_xml_span(raw: bytes, ordinal: int) -> dict[str, Any]:
    """Use a standard parser's byte offsets, never a textual guess about XML nesting."""
    parser = expat.ParserCreate("utf-8")
    stack: list[dict[str, Any]] = []
    skills: list[dict[str, Any]] = []

    def start(tag: str, _attributes: dict[str, str]) -> None:
        node = {"tag": tag, "start": parser.CurrentByteIndex, "children": []}
        if stack:
            stack[-1]["children"].append(node)
        stack.append(node)
        if tag == "Skill":
            skills.append(node)

    def end(tag: str) -> None:
        node = stack.pop()
        position = parser.CurrentByteIndex
        closing_prefix = b"</" + tag.encode("utf-8")
        explicit_close = raw.startswith(closing_prefix, position) and raw[
            position + len(closing_prefix) : position + len(closing_prefix) + 1
        ] in {b">", b" ", b"\t", b"\r", b"\n"}
        node["close"] = position if explicit_close else None
        node["end"] = raw.index(b">", position) + 1 if explicit_close else position

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(raw, True)
    return skills[ordinal]


def _support_identity_subject(name: str) -> dict[str, Any]:
    index = SkillEquivalenceIndex.shared()
    return {
        "gemIds": list(index.gem_ids(name)),
        "effectIds": list(index.granted_skills_by_gem().get(name) or []),
    }


def _runtime_support_identity(engine: Any, name: str) -> dict[str, Any]:
    subject = _support_identity_subject(name)
    if not subject["gemIds"] and not subject["effectIds"]:
        return {"status": "error", "reasonCode": "support_identity_subject_missing", **subject}
    try:
        result = engine.call("resolve_support_gem_identity", requestedName=name, **subject)
    except Exception:  # noqa: BLE001 - older runtimes cannot authorize identity substitutions.
        result = None
    if not isinstance(result, dict) or result.get("ok") is not True:
        return {"status": "error", "reasonCode": "support_identity_resolution_failed", **subject}
    if result.get("status") == "resolved" and (
        not result.get("name")
        or not result.get("gemId")
        or not result.get("effectId")
        or not _finite_num(result.get("naturalMaxLevel"))
        or result["naturalMaxLevel"] < 1
    ):
        return {
            "status": "error",
            "reasonCode": "support_identity_resolution_incomplete",
            **subject,
        }
    return {**result, **subject, "requestedName": name}


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
    """Compare complete support sets with the installed set as an immutable search baseline.

    `goals` (weighted, e.g. {"TotalDPS":.7,"TotalEHP":.3}) blends objectives; omit for single
    `metric`. Builds the candidate pool by MEASUREMENT, not tags: it solo-measures the skill's
    tag-relevant supports (`screen` of them; on-element supports — those sharing the skill's damage
    type, like penetration — are always included), keeps the strongest `candidates`, then greedily
    adds supports from the installed mechanism and a usage-preserving minimal seed. Neutral supports are
    retained for contextual trials. This is a heuristic, not an exhaustive combination search.
    Only a complete, same-context improvement can require a change. The build is restored.
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
    source_active_index = int(
        selected_group.get("mainActiveSkillCalcs") or selected_group.get("mainActiveSkill") or 1
    )
    skill = next(
        (
            str(effect.get("name"))
            for effect in selected_group.get("activeSkills") or []
            if int(effect.get("index") or 0) == source_active_index and effect.get("name")
        ),
        str(selected_group.get("activeSkill") or source_skill),
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
    objective_specification = (
        {"mode": "weighted", "weights": dict(weights), "directions": dict(metric_directions)}
        if weights
        else {"mode": "metric", "metric": metric, "direction": single_metric_direction}
    )
    measurement_keys = list(keys)
    if max_mana_cost is not None and "ManaCost" not in measurement_keys:
        measurement_keys.append("ManaCost")
    if spirit_limit is not None and "SpiritReserved" not in measurement_keys:
        measurement_keys.append("SpiritReserved")

    selected = engine.call(
        "set_skill_group_state",
        index=selected_group_index,
        makeMain=True,
        activeSkillIndex=source_active_index,
    )
    if not isinstance(selected, dict) or selected.get("ok") is False:
        engine.load_build_xml(snapshot)
        return {"ok": False, "errorCode": "skill_group_selection_failed"}

    capability = _support_evaluation_capability(
        engine,
        group_index=selected_group_index,
        active_skill_index=source_active_index,
        objective_keys=keys,
        selected_group=selected_group,
    )
    selected_effect_id = capability.get("selectedEffectId")
    if capability.get("numericRanking") in {"unsupported", "unknown"}:
        reason_codes = [str(value) for value in capability.get("reasonCodes") or [] if value]
        application_check = str(capability.get("applicationCheck") or "unknown")
        if application_check == "failed" or "trigger_rate_zero_or_inactive" in reason_codes:
            reason_class = "actionable_gap"
        elif support_capability_is_model_gap(capability):
            reason_class = "capability_gap"
        elif capability.get("numericRanking") == "unknown":
            reason_class = "measurement_error"
        else:
            reason_class = "evidence_gap"
        constraint_check = _inspect_current_support_constraints(
            engine, max_mana_cost=max_mana_cost, spirit_limit=spirit_limit
        )
        if not constraint_check["satisfied"]:
            # Known failures remain actionable even if another requested stat is unavailable.
            # Otherwise a missing/failed cost read prevents declaring a pure rate capability gap.
            severity = {
                "capability_gap": 0,
                "evidence_gap": 1,
                "measurement_error": 2,
                "actionable_gap": 3,
            }
            constraint_reason_class = str(constraint_check["reasonClass"])
            if severity[constraint_reason_class] > severity[reason_class]:
                reason_class = constraint_reason_class
            reason_codes = [*constraint_check["reasonCodes"], *reason_codes]
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
            "finalConstraintsSatisfied": constraint_check["satisfied"],
            "currentConstraintCheck": constraint_check,
            "objectiveKeys": list(keys),
            "objectiveDirections": metric_directions,
            "measurementKeys": list(measurement_keys),
            "objectiveSpecification": objective_specification,
            "scopeKind": "current_effect_capability",
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

    discovery_skills = list(
        dict.fromkeys(
            [
                source_skill,
                skill,
                *(
                    str(gem["name"])
                    for gem in selected_group.get("gems") or []
                    if not gem.get("isSupport") and gem.get("name")
                ),
            ]
        )
    )
    all_screen_names = list(
        dict.fromkeys(
            name
            for discovery_skill in discovery_skills
            for name in _screen_set(discovery_skill, 999999)
        )
    )
    screen_names = all_screen_names[:screen]
    if not all_screen_names:
        engine.load_build_xml(snapshot)
        return {"ok": False, "error": f"No supports found for '{skill}'."}
    support_capacity = _support_capacity(selected_group)
    effective_max_supports = min(max_supports, support_capacity)
    resolved_identities = {name: _runtime_support_identity(engine, name) for name in screen_names}
    identities_by_canonical_name = {
        str(identity["name"]): identity
        for identity in resolved_identities.values()
        if identity.get("status") == "resolved" and identity.get("name")
    }
    usage_contract = _usage_condition_contract(capability)
    condition_effect_ids = {entry[1] for entry in usage_contract or ()}
    condition_supports = []
    for name in current_supports:
        identity = identities_by_canonical_name.get(name) or _runtime_support_identity(engine, name)
        if identity.get("effectId") in condition_effect_ids:
            condition_supports.append(name)
    search_scope_hash = canonical_payload_hash(
        {
            "discoverySkills": sorted(discovery_skills),
            "candidateSubjects": [
                {
                    "name": name,
                    "gemIds": sorted(identity.get("gemIds") or []),
                    "effectIds": sorted(identity.get("effectIds") or []),
                }
                for name, identity in sorted(resolved_identities.items())
            ],
            "supportCapacity": support_capacity,
        },
        prefix="support-search-scope",
    )

    try:
        last_measured_group: dict[str, Any] = {}
        topology_rebuilds = 0

        def activate_source_probe() -> str | None:
            # Inactive item/weapon-swap sources have no runtime active effects after an
            # import. PoB checks activeSkillIndex before makeMain, so first activate the
            # real source group, then retain the exact index/effect checks below.
            selected = engine.call(
                "set_skill_group_state", index=selected_group_index, makeMain=True
            )
            if not isinstance(selected, dict) or selected.get("ok") is not True:
                return (
                    str(selected.get("errorCode") or "skill_group_selection_failed")
                    if isinstance(selected, dict)
                    else "invalid_skill_group_selection_result"
                )
            return None

        def measure(
            supports: list[str], *, original: bool = False
        ) -> tuple[dict[str, Any], str, str | None]:
            nonlocal last_measured_group, topology_rebuilds
            last_measured_group = {}
            local_probe: dict[str, Any] | None = None
            measured_active_index = source_active_index
            if len(supports) > support_capacity or len(set(supports)) != len(supports):
                return {}, "rejected", "duplicate_or_excess_supports"
            if original:
                engine.load_build_xml(snapshot, name="support-current-combination-reset")
                if configurable_source and (error := activate_source_probe()):
                    return {}, "failed", error
            elif configurable_source:
                support_ids: list[str] = []
                support_gems: list[dict[str, Any]] = []
                for name in supports:
                    identity = identities_by_canonical_name.get(name) or {}
                    if not identity and name in current_supports:
                        # A bounded discovery screen must not discard an already installed
                        # canonical support whose corpus label differs from PoB's label.
                        current_identity = engine.call(
                            "resolve_support_gem_identity", runtimeName=name
                        )
                        if (
                            isinstance(current_identity, dict)
                            and current_identity.get("ok") is True
                            and current_identity.get("status") == "resolved"
                            and current_identity.get("name") == name
                        ):
                            identity = current_identity
                    gem = db.get_gem(str(identity.get("requestedName") or name))
                    if identity.get("status") == "resolved" and identity.get("gemId"):
                        support_ids.append(str(identity["gemId"]))
                        support_gems.append(gem or {})
                        continue
                    if gem is None or str(gem.get("gem_type") or "").lower() != "support":
                        return {}, "failed", "support_gem_lookup_failed"
                    support_ids.append(str(identity.get("gemId") or gem["id"]))
                    support_gems.append(gem)
                engine.load_build_xml(snapshot, name="source-support-measurement-reset")
                if error := activate_source_probe():
                    return {}, "failed", error
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
            else:
                try:
                    probe_xml = _regular_probe_xml(
                        snapshot,
                        selected_group_index,
                        selected_group,
                        supports,
                        identities=identities_by_canonical_name,
                        group_only=True,
                    )
                except (ET.ParseError, ValueError) as exc:
                    return {}, "failed", str(exc)
                local_probe = engine.probe_regular_skill_group(
                    group_index=selected_group_index,
                    group_xml=probe_xml,
                    active_skill_index=source_active_index,
                    expected_skill_name=skill,
                    keys=measurement_keys,
                    objective_keys=keys,
                    expected_effect_id=selected_effect_id,
                )
                if not isinstance(local_probe, dict) or local_probe.get("ok") is not True:
                    if isinstance(local_probe, dict) and local_probe.get("recoveryRequired"):
                        raise RuntimeError("support_probe_recovery_required")
                    return (
                        {},
                        "failed",
                        str((local_probe or {}).get("errorCode") or "support_probe_failed"),
                    )
                if local_probe.get("requiresFullRebuild") is True:
                    # The original complete snapshot, not the preceding probe, authorizes
                    # every non-target input. PoB alone recreates/removes generated groups.
                    engine.load_build_xml(
                        _regular_probe_xml(
                            snapshot,
                            selected_group_index,
                            selected_group,
                            supports,
                            identities=identities_by_canonical_name,
                        ),
                        name="support-topology-probe",
                    )
                    topology_rebuilds += 1
                    local_probe = None
                else:
                    measured_active_index = int(
                        local_probe.get("activeSkillIndex") or source_active_index
                    )
            if local_probe is None:
                if not original:
                    candidate_groups = engine.call("list_skill_groups")
                    candidate_group = next(
                        (
                            group
                            for group in candidate_groups.get("groups") or []
                            if int(group.get("index") or 0) == selected_group_index
                        ),
                        {},
                    )
                    try:
                        measured_active_index = _unique_output_index(
                            candidate_group, skill, selected_effect_id
                        )
                    except ValueError as exc:
                        return {}, "failed", str(exc)
                selected = engine.call(
                    "set_skill_group_state",
                    index=selected_group_index,
                    makeMain=True,
                    activeSkillIndex=measured_active_index,
                )
                if not isinstance(selected, dict) or selected.get("ok") is False:
                    return {}, "failed", "support_target_selection_failed"
            readback = (
                local_probe.get("state")
                if local_probe is not None
                else engine.call("list_skill_groups")
            )
            if not isinstance(readback, dict):
                return {}, "failed", "support_probe_state_missing"
            actual = next(
                (
                    item
                    for item in readback.get("groups") or []
                    if int(item.get("index") or 0) == selected_group_index
                ),
                {},
            )
            actual_supports = [
                str(gem.get("name"))
                for gem in actual.get("gems") or []
                if gem.get("isSupport") and gem.get("name")
            ]
            if Counter(actual_supports) != Counter(supports):
                return {}, "failed", "support_group_incomplete"
            if (
                int(readback.get("mainGroupIndex") or 0) != selected_group_index
                or int(actual.get("mainActiveSkillCalcs") or actual.get("mainActiveSkill") or 1)
                != measured_active_index
                or str(actual.get("activeSkill") or "") != skill
            ):
                return {}, "failed", "support_selected_effect_changed"
            probe_capability = (
                local_probe.get("capability") or {}
                if local_probe is not None
                else _support_evaluation_capability(
                    engine,
                    group_index=selected_group_index,
                    active_skill_index=measured_active_index,
                    objective_keys=keys,
                    selected_group=actual,
                )
            )
            if (
                selected_effect_id is not None
                and probe_capability.get("selectedEffectId") != selected_effect_id
            ):
                return {}, "failed", "support_selected_effect_changed"
            if probe_capability.get("applicationCheck") == "failed":
                return {}, "rejected", "source_support_not_applied"
            probe_usage_contract = _usage_condition_contract(probe_capability)
            if usage_contract is None or probe_usage_contract is None:
                return {}, "failed", "support_usage_condition_evidence_missing"
            if usage_contract != probe_usage_contract:
                return {}, "rejected", "support_usage_condition_changed"
            if (
                probe_capability.get("ok") is not True
                or probe_capability.get("numericRanking") != "supported"
                or probe_capability.get("applicationCheck") not in {"verified", "not_applicable"}
            ):
                return {}, "failed", "support_combination_capability_incomplete"
            measured = (
                local_probe if local_probe is not None else engine.get_stats(measurement_keys)
            )
            stats = measured.get("stats") if isinstance(measured, dict) else None
            if not isinstance(stats, dict) or measured.get("ok") is False:
                return {}, "failed", "support_stats_missing"
            last_measured_group = deepcopy(actual)
            return stats, "measured", None

        current_stats, current_outcome, current_error = measure(current_supports, original=True)
        current_legality = hard_legality.audit_build(
            hard_legality.augment_build_with_snapshot_gear(engine.get_build(), engine.get_xml())
        )
        base_stats, base_outcome, base_error = measure(
            condition_supports
        )  # Preserve runtime usage conditions even in the minimal search seed.

        def measurement_valid(stats: dict[str, Any]) -> bool:
            return any(_finite_num(stats.get(key)) for key in keys)

        def audit_measurement_valid(stats: dict[str, Any]) -> bool:
            return all(_finite_num(stats.get(key)) for key in measurement_keys)

        def objective_score(stats: dict[str, Any]) -> float:
            if not all(_finite_num(stats.get(key)) for key in keys):
                return float("-inf")
            if weights:
                if not all(_finite_num(current_stats.get(key)) for key in keys):
                    return float("-inf")
                return sum(
                    weight
                    * (float(stats[key]) - float(current_stats[key]))
                    / max(abs(float(current_stats[key])), 1.0)
                    for key, weight in weights.items()
                )
            value = float(stats[metric])
            return -value if single_metric_direction == "lower" else value

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

        def score(st: dict[str, Any]) -> float:
            return objective_score(st) if constraints_satisfied(st) else float("-inf")

        # Candidate pool by MEASUREMENT, not tag count. A support's shared-tag count is a poor proxy
        # for value — top DPS levers like penetration or added-damage often share only the element
        # tag and would be truncated out of a tag-ranked list. So solo-measure each tag-relevant
        # support and keep the strongest `candidates` for the combo-aware greedy below. This is what
        # lets the search find e.g. Lightning Penetration on a lightning skill.
        screened: list[tuple[float, str]] = []
        measured_candidate_count = 0
        fully_measured_candidate_count = 0
        rejected_candidate_count = 0
        failed_candidate_count = 0
        changed_candidate_count = 0
        candidate_rejection_codes: dict[str, int] = {}
        candidate_failure_codes: dict[str, int] = {}
        candidate_failure_details: list[dict[str, str]] = []
        unavailable_candidates: list[dict[str, Any]] = []
        screen_measurements: dict[tuple[str, ...], tuple[dict[str, Any], str, str | None]] = {}
        observed_objective_keys = {key for key in keys if _finite_num(base_stats.get(key))}

        def count_code(counts: dict[str, int], code: str | None, fallback: str) -> None:
            key = str(code or fallback)
            counts[key] = counts.get(key, 0) + 1

        for name in screen_names:
            identity = resolved_identities[name]
            if identity.get("status") == "model_unavailable":
                rejected_candidate_count += 1
                count_code(candidate_rejection_codes, "support_model_unavailable", "")
                unavailable_candidates.append(
                    {
                        "requestedName": name,
                        "status": "model_unavailable",
                        "gemIds": identity.get("gemIds") or [],
                        "effectIds": identity.get("effectIds") or [],
                    }
                )
                continue
            if identity.get("status") != "resolved" or not identity.get("name"):
                failed_candidate_count += 1
                count_code(candidate_failure_codes, "support_identity_unresolved", "")
                candidate_failure_details.append(
                    {"support": name, "reasonCode": "support_identity_unresolved"}
                )
                continue
            canonical_name = str(identity["name"])
            screened_set = list(dict.fromkeys([*condition_supports, canonical_name]))
            measured_stats, outcome, error_code = measure(screened_set)
            screen_measurements[tuple(sorted(screened_set))] = measured_stats, outcome, error_code
            if outcome == "rejected":
                rejected_candidate_count += 1
                count_code(candidate_rejection_codes, error_code, "source_support_rejected")
                continue
            if outcome != "measured":
                failed_candidate_count += 1
                count_code(candidate_failure_codes, error_code, "support_measurement_failed")
                candidate_failure_details.append(
                    {"support": name, "reasonCode": str(error_code or "support_measurement_failed")}
                )
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
            screened.append((score(measured_stats), canonical_name))
        screened.sort(key=lambda item: item[0], reverse=True)
        base_measurable = all(key in observed_objective_keys for key in keys)
        # Solo measurements rank a bounded search pool, never discard the installed synergy set.
        # Even a solo-neutral support can help when added to a complete, existing mechanism.
        pool = list(dict.fromkeys(nm for sc, nm in screened if math.isfinite(sc)))[:candidates]

        chosen = list(current_supports)
        cur = objective_score(current_stats)
        progression: list[dict[str, Any]] = []
        rejected_combination_count = 0
        # A numerically unmodelled bare skill is a valid search seed; an explicit failed
        # reset/probe is not. Keep the operation error even if complete sets are measurable.
        failed_combination_count = int(base_outcome == "failed")
        combination_rejection_codes: dict[str, int] = {}
        combination_failure_codes: dict[str, int] = {}
        if base_outcome == "failed":
            count_code(combination_failure_codes, base_error, "support_empty_seed_probe_failed")
        measured_combinations: dict[tuple[str, ...], tuple[dict[str, Any], str, str | None]] = dict(
            screen_measurements
        )

        def greedy(
            seed: list[str], seed_stats: dict[str, Any]
        ) -> tuple[list[str], dict[str, Any], list[dict[str, Any]]]:
            nonlocal rejected_combination_count, failed_combination_count
            picked = list(seed)
            picked_stats = seed_stats
            steps: list[dict[str, Any]] = []
            while len(picked) < effective_max_supports:
                best_name, best_score, best_stats = None, score(picked_stats), None
                for name in pool:
                    if name in picked:
                        continue
                    combination = tuple(sorted([*picked, name]))
                    if combination not in measured_combinations:
                        probe = measure([*picked, name])
                        measured_combinations[combination] = probe
                        stats, outcome, error_code = probe
                        if outcome == "rejected":
                            rejected_combination_count += 1
                            count_code(
                                combination_rejection_codes,
                                error_code,
                                "support_combination_rejected",
                            )
                        elif outcome != "measured" or not audit_measurement_valid(stats):
                            failed_combination_count += 1
                            count_code(
                                combination_failure_codes,
                                error_code,
                                "incomplete_combination_stats",
                            )
                    stats, outcome, _ = measured_combinations[combination]
                    if outcome != "measured" or not audit_measurement_valid(stats):
                        continue
                    candidate_score = score(stats)
                    if candidate_score > best_score + 1e-9:
                        best_name, best_score, best_stats = name, candidate_score, stats
                if best_name is None:
                    break
                picked.append(best_name)
                picked_stats = best_stats or {}
                steps.append(
                    {"added": best_name, **{key: _r2(picked_stats.get(key)) for key in keys}}
                )
            return picked, picked_stats, steps

        seeds = [(list(current_supports), current_stats)]
        if current_supports:
            seeds.append((list(condition_supports), base_stats))
        for seed, seed_stats in seeds:
            candidate_set, candidate_stats, candidate_steps = greedy(seed, seed_stats)
            candidate_score = score(candidate_stats)
            if candidate_score > cur + 1e-9:
                chosen, cur, progression = candidate_set, candidate_score, candidate_steps
        final_stats, final_outcome, final_error = measure(
            chosen, original=Counter(chosen) == Counter(current_supports)
        )
        if final_outcome != "measured" or not audit_measurement_valid(final_stats):
            failed_combination_count += 1
            count_code(
                combination_failure_codes,
                final_error,
                "incomplete_final_combination_stats",
            )
        final_legality = hard_legality.audit_build(
            hard_legality.augment_build_with_snapshot_gear(engine.get_build(), engine.get_xml())
        )
        rejected_recommendation = None
        initial_regression = hard_legality.compare_audits_for_regression(
            current_legality, final_legality
        )
        if Counter(chosen) != Counter(current_supports) and initial_regression["regressed"]:
            rejected_recommendation = {
                "supports": list(chosen),
                "reasonCode": "support_combination_legality_regression",
                "legalityComparison": initial_regression,
            }
            rejected_combination_count += 1
            count_code(combination_rejection_codes, "support_combination_legality_regression", "")
            chosen = list(current_supports)
            progression = []
            final_stats, final_outcome, final_error = measure(chosen, original=True)
            if final_outcome != "measured" or not audit_measurement_valid(final_stats):
                failed_combination_count += 1
                count_code(
                    combination_failure_codes, final_error, "incomplete_current_combination_stats"
                )
            final_legality = hard_legality.audit_build(
                hard_legality.augment_build_with_snapshot_gear(engine.get_build(), engine.get_xml())
            )
        candidate_group_fingerprint = (
            _comparison_group_fingerprint(last_measured_group) if last_measured_group else None
        )
        candidate_support_settings = [
            {key: gem.get(key) for key in ("name", "level", "quality", "enabled", "count")}
            for gem in last_measured_group.get("gems") or []
            if gem.get("isSupport")
        ]
        candidate_active_settings = [
            {key: gem.get(key) for key in ("name", "level", "quality", "enabled", "count")}
            for gem in last_measured_group.get("gems") or []
            if not gem.get("isSupport")
        ]
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
    current_measurable = current_outcome == "measured" and audit_measurement_valid(current_stats)
    final_measurable = final_outcome == "measured" and audit_measurement_valid(final_stats)
    baseline_score = objective_score(current_stats)
    candidate_score = objective_score(final_stats)
    numeric_comparison = all(_finite_num(value) for value in (baseline_score, candidate_score))
    net_gain = candidate_score - baseline_score if numeric_comparison else None
    legality_comparison = hard_legality.compare_audits_for_regression(
        current_legality, final_legality
    )
    candidate_legal = legality_comparison["regressed"] is False
    comparison_complete = (
        checkpoint_objective_eligible
        and current_measurable
        and final_measurable
        and numeric_comparison
        and _finite_num(net_gain)
        and final_constraints_satisfied
        and candidate_legal
        and float(net_gain) >= -1e-9
    )
    comparison = {
        "status": "complete" if comparison_complete else "inconclusive",
        "baselineSupports": list(current_supports),
        "candidateSupports": list(chosen),
        "baselineActiveSkillIndex": source_active_index,
        "candidateActiveSkillIndex": int(
            last_measured_group.get("mainActiveSkillCalcs")
            or last_measured_group.get("mainActiveSkill")
            or source_active_index
        )
        if last_measured_group
        else None,
        "selectedEffectId": selected_effect_id,
        "baselineMetrics": {
            key: current_stats.get(key) if _finite_num(current_stats.get(key)) else None
            for key in measurement_keys
        },
        "candidateMetrics": {
            key: final_stats.get(key) if _finite_num(final_stats.get(key)) else None
            for key in measurement_keys
        },
        "baselineScore": baseline_score if _finite_num(baseline_score) else None,
        "candidateScore": candidate_score if _finite_num(candidate_score) else None,
        "netGain": net_gain if _finite_num(net_gain) else None,
        "baselineMeasurable": current_measurable,
        "candidateMeasurable": final_measurable,
        "baselineConstraintsSatisfied": constraints_satisfied(current_stats),
        "candidateConstraintsSatisfied": final_constraints_satisfied,
        "candidateLegalityNonRegressing": candidate_legal,
        "finalHardLegalityReady": final_legality.get("status") == "passed",
        "legalityComparison": legality_comparison,
        "sameContext": current_outcome == "measured" and final_outcome == "measured",
        "candidateGroupFingerprint": candidate_group_fingerprint,
        "positiveGainProven": comparison_complete and float(net_gain) > 1e-9,
    }
    checkpoint_eligible = (
        checkpoint_objective_eligible
        and coverage_complete
        and classification_complete
        and current_measurable
        and fully_measured_candidate_count > 0
        and fully_measured_candidate_count + rejected_candidate_count == len(screen_names)
        and failed_candidate_count == 0
        and failed_combination_count == 0
        and final_constraints_satisfied
        and comparison_complete
    )
    measurement = {
        "status": "complete" if checkpoint_eligible else "inconclusive",
        "checkpointEligible": checkpoint_eligible,
        "policyReason": None if checkpoint_eligible else "support_audit_policy_not_satisfied",
        "baseMeasurable": base_fully_measurable,
        "currentCombinationMeasurable": current_measurable,
        "baseFailureCode": None if base_outcome == "measured" else base_error,
        "currentCombinationFailureCode": None if current_outcome == "measured" else current_error,
        "coverageComplete": coverage_complete,
        "classificationComplete": classification_complete,
        "supportCapacity": support_capacity,
        "maxSupports": max_supports,
        "candidateLimit": candidates,
        "totalRelevantCandidates": len(all_screen_names),
        "discoverySkills": discovery_skills,
        "screenedCandidates": len(screen_names),
        "measuredCandidates": fully_measured_candidate_count,
        "rejectedCandidates": rejected_candidate_count,
        "classifiedCandidates": classified_candidate_count,
        "failedCandidates": failed_candidate_count,
        "candidateRejectionCodes": dict(sorted(candidate_rejection_codes.items())),
        "candidateFailureCodes": dict(sorted(candidate_failure_codes.items())),
        "candidateFailureDetails": candidate_failure_details,
        "modelUnavailableCandidates": len(unavailable_candidates),
        "uncoveredCandidates": unavailable_candidates,
        "modelCoverageComplete": not unavailable_candidates,
        "rejectedCombinations": rejected_combination_count,
        "failedCombinations": failed_combination_count,
        "combinationRejectionCodes": dict(sorted(combination_rejection_codes.items())),
        "combinationFailureCodes": dict(sorted(combination_failure_codes.items())),
        "changedCandidates": changed_candidate_count,
        "finalConstraintsSatisfied": final_constraints_satisfied,
        "objectiveKeys": list(keys),
        "objectiveDirections": metric_directions,
        "measurementKeys": list(measurement_keys),
        "objectiveSpecification": objective_specification,
        "usageConditionContractVersion": capability.get("usageConditionContractVersion"),
        "usageConditionContracts": deepcopy(capability.get("usageConditionContracts")),
        "preservedUsageConditionSupports": list(condition_supports),
        "searchScopeHash": search_scope_hash,
        "combinationComparison": comparison,
        "searchMethod": "greedy_current_and_usage_preserving_seeds",
        "probeMode": "full_snapshot_source" if configurable_source else "group_local",
        "topologyRebuilds": topology_rebuilds,
        "searchCoverage": "screened_candidates_and_visited_combinations",
        "searchCoverageScope": "runtime_resolvable_support_identities",
        "globalOptimalityProven": False,
        "visitedCombinations": len(measured_combinations),
        "rejectedRecommendation": rejected_recommendation,
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
        "supportGemSettings": candidate_support_settings,
        "activeGemSettings": candidate_active_settings,
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
                "magnitudes). The current complete combination is retained as a measured baseline. "
                "Greedy search starts from current and usage-preserving minimal support sets; only a measured "
                "whole-set improvement can require a change. Preserve the selected group's active "
                "gems and settings when applying. Screening is not proof of a global optimum."
            )
        ),
    }
    if weights:
        out["goals"] = weights
        out["metricsBase"] = {k: _r2(base_stats.get(k)) for k in keys}
        out["metricsCurrent"] = {k: _r2(current_stats.get(k)) for k in keys}
        out["metricsFinal"] = {k: _r2(final_stats.get(k)) for k in keys}
    else:
        out["metric"] = metric
        out["baseValue"] = _r2(base_stats.get(metric))
        out["currentValue"] = _r2(current_stats.get(metric))
        out["finalValue"] = _r2(final_stats.get(metric))
    if not chosen:
        out["warning"] = (
            "No measured complete support combination improved the current selection within "
            "this search. See measurement for coverage and unresolved evidence."
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
