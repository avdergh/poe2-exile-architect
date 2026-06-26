"""Deterministic lifecycle-route evaluation harness.

This module evaluates an already-produced lifecycle route for development/regression use. It is
deliberately not a planner, optimizer, live-data provider, PoB verifier, or memory writer: callers
get a contract/evidence report, not a new build.
"""

from __future__ import annotations

import math
import re
from typing import Any

from . import lifecycle_quality

_REQUIRED_CHAIN = (
    "campaign_early",
    "campaign_mid",
    "campaign_late",
    "maps_entry",
)
_ENDGAME_STAGES = {"endgame_budget", "endgame_final"}
_REFERENCE_FIELDS = (
    "commonLevers",
    "commonDamageTypes",
    "commonDelivery",
    "commonDefenses",
    "ascendancyContext",
)
_COPYABLE_REFERENCE_KEYS = {
    "code",
    "config",
    "configs",
    "configtab",
    "configuration",
    "configurations",
    "xml",
    "pobcode",
    "pob",
    "gear",
    "items",
    "itemsets",
    "itemlist",
    "passivetree",
    "tree",
    "passives",
    "nodes",
    "skills",
    "skillgroups",
    "supportgems",
    "supports",
}
_NUMERIC_CLAIM_KEYWORDS = (
    "dps",
    "ehp",
    "damagepersecond",
    "totaldamage",
)
_NUMERIC_TEXT_RE = re.compile(
    r"(?i)(?:\b\d+(?:\.\d+)?\s*(?:k|m|thousand|million)?\s*(?:dps|ehp|totaldps|fulldps)\b|"
    r"\b(?:dps|ehp|totaldps|fulldps)\b\D{0,24}\d)"
)
_NUMERIC_LIKE_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*(?:k|m|thousand|million)?\s*$", re.I)


def evaluate_lifecycle_route(
    route: dict[str, Any],
    reference_profile: dict[str, Any] | None = None,
    goal: str | None = None,
) -> dict[str, Any]:
    """Evaluate a lifecycle route without generating, copying, computing, fetching, or writing.

    The evaluator uses stable issue/warning/unknown codes so it can be used by regression tests.
    Reference data is treated as calibration only and is sanitized before comparison.
    """
    if not isinstance(route, dict):
        return _invalid_route_result("route must be a dictionary")

    issues: list[str] = []
    warnings: list[str] = []
    unknowns: list[str] = []
    checks: list[dict[str, Any]] = []

    quality_gate = lifecycle_quality.audit_lifecycle_route(route)
    _add_check(checks, "quality_gate", bool(quality_gate.get("pass")))
    if not quality_gate.get("pass"):
        _append_unique(issues, "quality_gate_failed")
        for code in quality_gate.get("missing") or []:
            _append_unique(issues, str(code))
    if route.get("ok") is False:
        _append_unique(issues, "route_not_ok")

    stages = [stage for stage in route.get("stages") or [] if isinstance(stage, dict)]
    stage_ids = [str(stage.get("id") or "") for stage in stages]
    stage_id_set = set(stage_ids)

    has_campaign_chain = all(stage_id in stage_id_set for stage_id in _REQUIRED_CHAIN)
    _add_check(checks, "campaign_chain", has_campaign_chain)
    if not has_campaign_chain:
        _append_unique(issues, "missing_campaign_chain")

    has_endgame = bool(stage_id_set & _ENDGAME_STAGES)
    _add_check(checks, "endgame_stage", has_endgame)
    if not has_endgame:
        _append_unique(issues, "missing_endgame_stage")

    has_transition = _has_endgame_transition(route.get("transitionGates") or [])
    _add_check(checks, "transition_gate", has_transition)
    if not has_transition:
        _append_unique(issues, "missing_transition_gate")

    evidence_review = _review_evidence(route, stages)
    numeric_range_review = _review_numeric_ranges(stages, reference_profile)
    evidence_review["numericRangeReview"] = numeric_range_review
    _add_check(checks, "stage_evidence_tags", evidence_review["stageEvidenceComplete"])
    _add_check(checks, "stage_verification_plans", evidence_review["stageVerificationPlanned"])
    for code in evidence_review["issues"]:
        _append_unique(issues, code)
    for code in numeric_range_review["warnings"]:
        _append_unique(warnings, code)

    memory_review = _review_memory(route.get("memoryContext"))
    _add_check(checks, "memory_policy_advisory", memory_review["advisoryOnly"])
    for code in memory_review["issues"]:
        _append_unique(issues, code)
    for code in memory_review["warnings"]:
        _append_unique(warnings, code)
    for code in memory_review["unknowns"]:
        _append_unique(unknowns, code)

    reference_comparison = _compare_reference(route, stages, reference_profile)
    _add_check(
        checks,
        "reference_alignment",
        reference_comparison["alignmentStatus"] == "aligned",
        status="unknown" if reference_comparison["alignmentStatus"] == "unknown" else None,
    )
    for code in reference_comparison["warnings"]:
        _append_unique(warnings, code)
    for code in reference_comparison["issues"]:
        _append_unique(issues, code)
    for code in reference_comparison["unknowns"]:
        _append_unique(unknowns, code)

    score = _score(issues, warnings, unknowns)
    passed = not issues and not unknowns
    grade = "fail" if issues else "needs_review" if unknowns or warnings or score < 85 else "pass"

    return {
        "ok": True,
        "kind": "lifecycle_route_evaluation",
        "pass": passed,
        "score": score,
        "grade": grade,
        "issues": issues,
        "warnings": warnings,
        "unknowns": unknowns,
        "checks": checks,
        "routeSummary": {
            "buildId": route.get("buildId"),
            "goal": goal or route.get("goal"),
            "classification": route.get("classification"),
            "stageIds": stage_ids,
        },
        "qualityGate": quality_gate,
        "referenceComparison": reference_comparison,
        "evidenceReview": evidence_review,
        "memoryReview": memory_review,
        "boundaries": {
            "ranPobCompute": False,
            "copiedReference": False,
            "runtimeNetwork": False,
            "writesMemory": False,
        },
        "evidenceTags": ["lifecycle-route-evaluation", "lifecycle-quality-gate"],
        "note": "Evaluation only; not a build recommendation and not PoB verification.",
    }


def _review_evidence(route: dict[str, Any], stages: list[dict[str, Any]]) -> dict[str, Any]:
    stage_evidence_complete = bool(stages) and all(
        bool(stage.get("evidenceTags")) for stage in stages
    )
    stage_verification_planned = bool(stages) and all(
        isinstance(stage.get("verification"), dict) and bool(stage["verification"].get("ok"))
        for stage in stages
    )
    route_without_stages = {key: value for key, value in route.items() if key != "stages"}
    numeric_claim_paths = _numeric_claim_paths(
        route_without_stages,
        honor_engine_evidence=True,
        is_root=True,
    )
    for index, stage in enumerate(stages):
        numeric_claim_paths.extend(
            _numeric_claim_paths(
                stage,
                path=f"stages[{index}]",
                honor_engine_evidence=True,
            )
        )
    issues: list[str] = []
    numeric_status = "not_evaluated"
    if numeric_claim_paths:
        issues.append("unsupported_computed_claim")
        numeric_status = "unsupported_claim"

    return {
        "stageEvidenceComplete": stage_evidence_complete,
        "stageVerificationPlanned": stage_verification_planned,
        "numericReview": {
            "status": numeric_status,
            "unsupportedClaimCount": len(numeric_claim_paths)
            if numeric_status == "unsupported_claim"
            else 0,
            "note": (
                "No DPS/EHP closeness judgment is made without engine-computed stage evidence."
            ),
        },
        "issues": issues,
    }


def _review_memory(memory_context: Any) -> dict[str, Any]:
    if not isinstance(memory_context, dict):
        return {
            "present": False,
            "advisoryOnly": False,
            "doesNotReplacePobVerification": False,
            "noComputedNumbers": False,
            "issues": [],
            "warnings": ["memory_policy_missing"],
            "unknowns": ["memory_policy_unknown"],
        }
    policy = memory_context.get("policy") if isinstance(memory_context.get("policy"), dict) else {}
    advisory = bool(policy.get("advisoryOnly"))
    no_pob_replace = bool(policy.get("doesNotReplacePobVerification"))
    no_numbers = bool(policy.get("noComputedNumbers"))
    issues: list[str] = []
    if not advisory:
        issues.append("memory_policy_not_advisory")
    if not no_pob_replace:
        issues.append("memory_policy_can_replace_pob")
    if not no_numbers:
        issues.append("memory_policy_can_compute_numbers")
    return {
        "present": True,
        "advisoryOnly": advisory,
        "doesNotReplacePobVerification": no_pob_replace,
        "noComputedNumbers": no_numbers,
        "issues": issues,
        "warnings": [],
        "unknowns": [],
    }


def _compare_reference(
    route: dict[str, Any],
    stages: list[dict[str, Any]],
    reference_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    external_raw_field_count = _copyable_reference_key_count(reference_profile)
    if _has_alignment_profile(reference_profile):
        source = "reference_profile"
        raw_profile = reference_profile
    else:
        source = "route.cohortAnalysis"
        raw_profile = route.get("cohortAnalysis")
    profile, sanitized_count, invalid_sample_size = _sanitize_reference_profile(raw_profile)
    sanitized_count += external_raw_field_count if raw_profile is not reference_profile else 0
    warnings: list[str] = []
    issues: list[str] = []
    unknowns: list[str] = []
    if sanitized_count:
        warnings.append("reference_raw_fields_sanitized")
    if invalid_sample_size:
        warnings.append("reference_sample_size_invalid")

    if not profile or not profile.get("sampleSize"):
        unknowns.append("reference_alignment_unknown")
        return {
            "source": source,
            "alignmentStatus": "unknown",
            "sampleSize": 0,
            "overlaps": {},
            "sanitizedRawFieldCount": sanitized_count,
            "warnings": warnings,
            "issues": issues,
            "unknowns": unknowns,
            "note": "No usable non-copyable reference/cohort profile was available.",
        }

    hint_text = _endgame_hint_text(stages)
    overlaps: dict[str, list[str]] = {}
    for key in _REFERENCE_FIELDS:
        names = _row_names(profile.get(key) or [])
        # Alignment must be visible in the route itself. Cohort data alone only proves evidence was
        # collected; it does not prove the recommended lifecycle actually adopted that evidence.
        matched = [name for name in names if _name_in_text(name, hint_text)]
        if matched:
            overlaps[key] = matched

    if overlaps:
        status = "aligned"
    elif hint_text or profile.get("sampleSize"):
        status = "mismatch"
        issues.append("reference_alignment_mismatch")
    else:
        status = "unknown"
        unknowns.append("reference_alignment_unknown")

    return {
        "source": source,
        "alignmentStatus": status,
        "sampleSize": int(profile.get("sampleSize") or 0),
        "overlaps": overlaps,
        "sanitizedRawFieldCount": sanitized_count,
        "warnings": warnings,
        "issues": issues,
        "unknowns": unknowns,
        "note": "Reference comparison uses calibration fields only; it is not permission to copy.",
    }


def _review_numeric_ranges(
    stages: list[dict[str, Any]],
    reference_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    ranges, range_warnings = _normalize_numeric_ranges(reference_profile)
    if range_warnings:
        # A mixed valid/invalid reference profile is still unsafe as a calibration source. Returning
        # no rows keeps malformed external inputs from partially influencing lifecycle judgments.
        return _numeric_range_result(status="invalid_reference", warnings=range_warnings)
    if not ranges:
        return _numeric_range_result(status="not_evaluated")

    comparisons: list[dict[str, Any]] = []
    for stage in stages:
        if str(stage.get("id") or "") not in _ENDGAME_STAGES:
            continue
        verification = stage.get("verification")
        if not _has_direct_evidence_tag(verification, "engine-computed"):
            continue
        observations = verification.get("observations") if isinstance(verification, dict) else {}
        if not isinstance(observations, dict):
            continue
        offense = (
            observations.get("offense") if isinstance(observations.get("offense"), dict) else {}
        )
        candidates = [
            ("TotalDPS", "TotalDPS", offense.get("TotalDPS")),
            ("TotalEHP", "TotalEHP", observations.get("totalEHP")),
        ]
        if "FullDPS" in ranges:
            candidates.append(("FullDPS", "FullDPS", offense.get("FullDPS")))
        for observed_metric, reference_metric, raw_value in candidates:
            value = _finite_number(raw_value)
            reference_range = ranges.get(reference_metric)
            if value is None or reference_range is None:
                continue
            # Numeric range evaluation is calibration only: it helps the agent notice a weak
            # verified stage, but it never turns reference builds into templates to copy.
            row = {
                "stage": stage.get("id"),
                "metric": observed_metric,
                "observedMetric": observed_metric,
                "referenceMetric": reference_metric,
                "value": value,
                "referenceMin": reference_range["min"],
                "referenceMax": reference_range["max"],
                "placement": _range_placement(value, reference_range),
            }
            if "n" in reference_range:
                row["referenceN"] = reference_range["n"]
            comparisons.append(row)

    warnings = list(range_warnings)
    if any(row.get("placement") == "below_range" for row in comparisons):
        warnings.append("numeric_range_below_reference")
    status = "compared" if comparisons else "not_evaluated"
    return _numeric_range_result(status=status, comparisons=comparisons, warnings=warnings)


def _numeric_range_result(
    *,
    status: str,
    comparisons: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "stageComparisons": comparisons or [],
        "warnings": _dedupe(warnings or []),
        "unknowns": [],
        "evidenceTags": ["reference-numeric-range"] if comparisons else [],
        "note": (
            "Calibration only: range comparison uses already-computed stage metrics and safe "
            "reference distributions; it does not run PoB or permit copying reference builds."
        ),
    }


def _normalize_numeric_ranges(raw_profile: Any) -> tuple[dict[str, dict[str, float]], list[str]]:
    if not isinstance(raw_profile, dict):
        return {}, []

    ranges: dict[str, dict[str, float]] = {}
    invalid = False
    numeric_ranges = raw_profile.get("numericRanges")
    if "numericRanges" in raw_profile and not isinstance(numeric_ranges, dict):
        invalid = True
    elif isinstance(numeric_ranges, dict):
        for metric in ("TotalDPS", "FullDPS", "TotalEHP"):
            normalized, row_invalid = _normalize_range(numeric_ranges.get(metric))
            if normalized is not None:
                ranges[metric] = normalized
            invalid = invalid or row_invalid

    benchmark_sources = {
        "TotalDPS": _nested_reference(raw_profile, "dps"),
        "TotalEHP": _nested_reference(raw_profile, "ehp"),
    }
    for metric, raw_range in benchmark_sources.items():
        if metric in ranges:
            continue
        normalized, row_invalid = _normalize_range(raw_range)
        if normalized is not None:
            ranges[metric] = normalized
        invalid = invalid or row_invalid

    warnings = ["numeric_range_reference_invalid"] if invalid else []
    return ranges, warnings


def _nested_reference(raw_profile: dict[str, Any], key: str) -> Any:
    row = raw_profile.get(key)
    if not isinstance(row, dict):
        return None
    return row.get("reference")


def _normalize_range(raw_range: Any) -> tuple[dict[str, float] | None, bool]:
    if raw_range is None:
        return None, False
    if not isinstance(raw_range, dict):
        return None, True
    min_value = _finite_number(raw_range.get("min"))
    max_value = _finite_number(raw_range.get("max"))
    if min_value is None or max_value is None or min_value > max_value:
        return None, True
    normalized: dict[str, float] = {"min": min_value, "max": max_value}
    for key in ("p25", "median", "p75", "n"):
        value = _finite_number(raw_range.get(key))
        if value is not None:
            normalized[key] = value
    return normalized, False


def _range_placement(value: float, reference_range: dict[str, float]) -> str:
    if value < reference_range["min"]:
        return "below_range"
    if value > reference_range["max"]:
        return "above_range"
    return "within_range"


def _sanitize_reference_profile(raw_profile: Any) -> tuple[dict[str, Any], int, bool]:
    if not isinstance(raw_profile, dict):
        return {}, 0, False
    sanitized_count = _copyable_reference_key_count(raw_profile)
    sample_size, invalid_sample_size = _safe_sample_size(raw_profile.get("sampleSize"))
    profile: dict[str, Any] = {"sampleSize": sample_size}
    for key in _REFERENCE_FIELDS:
        value = raw_profile.get(key)
        if isinstance(value, list):
            profile[key] = [
                row
                for row in value
                if isinstance(row, dict) and (row.get("name") or row.get("ascendancy"))
            ]
        else:
            profile[key] = []
    return profile, sanitized_count, invalid_sample_size


def _copyable_reference_key_count(raw_profile: Any) -> int:
    if not isinstance(raw_profile, dict):
        return 0
    return sum(1 for key in raw_profile if _reference_key_token(key) in _COPYABLE_REFERENCE_KEYS)


def _has_alignment_profile(raw_profile: Any) -> bool:
    if not isinstance(raw_profile, dict):
        return False
    profile, _, _ = _sanitize_reference_profile(raw_profile)
    # Empty placeholder arrays in a numeric-only profile must not replace route.cohortAnalysis, but
    # a profile with at least one safe alignment row is intentional input even if sampleSize is bad.
    return any(profile.get(key) for key in _REFERENCE_FIELDS)


def _reference_key_token(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _safe_sample_size(value: Any) -> tuple[int, bool]:
    if value is None:
        return 0, False
    if isinstance(value, bool):
        return 0, True
    if isinstance(value, int | float):
        if value < 0:
            return 0, True
        return int(value), False
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip()), False
    return 0, True


def _has_endgame_transition(gates: Any) -> bool:
    return any(
        isinstance(gate, dict) and str(gate.get("toStage") or "") in _ENDGAME_STAGES
        for gate in gates
    )


def _endgame_hint_text(stages: list[dict[str, Any]]) -> str:
    hints: list[str] = []
    for stage in stages:
        if str(stage.get("id") or "") not in _ENDGAME_STAGES:
            continue
        hints.extend(str(hint) for hint in stage.get("cohortHints") or [] if hint)
    return " ".join(hints).lower()


def _row_names(rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for row in rows:
        value = row.get("name") or row.get("ascendancy")
        if value:
            names.append(str(value))
    return names


def _name_in_text(name: str, text: str) -> bool:
    normalized = name.lower()
    return bool(normalized and normalized in text)


def _numeric_claim_paths(
    value: Any,
    path: str = "",
    *,
    inside_numeric_claim_key: bool = False,
    honor_engine_evidence: bool = False,
    is_root: bool = False,
) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        if (
            honor_engine_evidence
            and not is_root
            and _has_direct_evidence_tag(value, "engine-computed")
        ):
            return paths
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            key_is_claim = _looks_like_numeric_claim_key(key_text)
            if key_is_claim and _is_numeric_scalar(child):
                paths.append(child_path)
                continue
            elif key_is_claim and isinstance(child, str) and _is_numeric_like_text(child):
                paths.append(child_path)
                continue
            paths.extend(
                _numeric_claim_paths(
                    child,
                    child_path,
                    inside_numeric_claim_key=inside_numeric_claim_key or key_is_claim,
                    honor_engine_evidence=honor_engine_evidence,
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(
                _numeric_claim_paths(
                    child,
                    f"{path}[{index}]",
                    inside_numeric_claim_key=inside_numeric_claim_key,
                    honor_engine_evidence=honor_engine_evidence,
                )
            )
    elif inside_numeric_claim_key and (_is_numeric_scalar(value) or _is_numeric_like_text(value)):
        paths.append(path)
    elif isinstance(value, str) and _contains_numeric_claim_text(value):
        paths.append(path)
    return paths


def _looks_like_numeric_claim_key(key: str) -> bool:
    lowered = key.lower()
    if lowered.endswith("computable"):
        return False
    return any(token in lowered for token in _NUMERIC_CLAIM_KEYWORDS)


def _is_numeric_scalar(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _is_numeric_like_text(value: str) -> bool:
    return bool(_NUMERIC_LIKE_RE.match(value))


def _contains_numeric_claim_text(value: str) -> bool:
    return bool(_NUMERIC_TEXT_RE.search(value))


def _has_direct_evidence_tag(value: Any, tag: str) -> bool:
    if not isinstance(value, dict):
        return False
    evidence = value.get("evidenceTags")
    return isinstance(evidence, list) and tag in evidence


def _has_evidence_tag(value: Any, tag: str) -> bool:
    if isinstance(value, dict):
        evidence = value.get("evidenceTags")
        if isinstance(evidence, list) and tag in evidence:
            return True
        return any(_has_evidence_tag(child, tag) for child in value.values())
    if isinstance(value, list):
        return any(_has_evidence_tag(child, tag) for child in value)
    return False


def _add_check(
    checks: list[dict[str, Any]],
    name: str,
    ok: bool,
    *,
    status: str | None = None,
) -> None:
    checks.append({"check": name, "ok": bool(ok), "status": status or ("pass" if ok else "fail")})


def _append_unique(rows: list[str], code: str) -> None:
    if code not in rows:
        rows.append(code)


def _score(issues: list[str], warnings: list[str], unknowns: list[str]) -> int:
    score = 100 - len(issues) * 20 - len(unknowns) * 8 - len(warnings) * 5
    return max(0, min(100, score))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _invalid_route_result(error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": "lifecycle_route_evaluation",
        "pass": False,
        "score": 0,
        "grade": "fail",
        "issues": ["invalid_route"],
        "warnings": [],
        "unknowns": [],
        "checks": [{"check": "route_is_dict", "ok": False, "status": "fail"}],
        "routeSummary": {"buildId": None, "goal": None, "classification": None, "stageIds": []},
        "qualityGate": {"ok": False, "pass": False, "missing": ["invalid_route"]},
        "referenceComparison": {
            "source": "none",
            "alignmentStatus": "unknown",
            "sampleSize": 0,
            "overlaps": {},
            "sanitizedRawFieldCount": 0,
            "warnings": [],
            "issues": [],
            "unknowns": ["reference_alignment_unknown"],
            "note": "No route was available to compare.",
        },
        "evidenceReview": {
            "stageEvidenceComplete": False,
            "stageVerificationPlanned": False,
            "numericReview": {
                "status": "not_evaluated",
                "unsupportedClaimCount": 0,
                "note": "No DPS/EHP closeness judgment is made without engine-computed stage evidence.",
            },
            "numericRangeReview": _numeric_range_result(status="not_evaluated"),
            "issues": ["invalid_route"],
        },
        "memoryReview": {
            "present": False,
            "advisoryOnly": False,
            "doesNotReplacePobVerification": False,
            "noComputedNumbers": False,
            "issues": [],
            "warnings": [],
            "unknowns": ["memory_policy_unknown"],
        },
        "boundaries": {
            "ranPobCompute": False,
            "copiedReference": False,
            "runtimeNetwork": False,
            "writesMemory": False,
        },
        "evidenceTags": ["lifecycle-route-evaluation"],
        "note": "Evaluation only; not a build recommendation and not PoB verification.",
        "error": error,
    }
