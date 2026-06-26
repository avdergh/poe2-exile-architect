"""Deterministic lifecycle-route evaluation harness.

This module evaluates an already-produced lifecycle route for development/regression use. It is
deliberately not a planner, optimizer, live-data provider, PoB verifier, or memory writer: callers
get a contract/evidence report, not a new build.
"""

from __future__ import annotations

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
    "xml",
    "pobcode",
    "pob",
    "gear",
    "items",
    "itemlist",
    "passivetree",
    "tree",
    "passives",
    "nodes",
    "skills",
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
    _add_check(checks, "stage_evidence_tags", evidence_review["stageEvidenceComplete"])
    _add_check(checks, "stage_verification_plans", evidence_review["stageVerificationPlanned"])
    for code in evidence_review["issues"]:
        _append_unique(issues, code)

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
    source = "reference_profile" if reference_profile is not None else "route.cohortAnalysis"
    raw_profile = (
        reference_profile if reference_profile is not None else route.get("cohortAnalysis")
    )
    profile, sanitized_count, invalid_sample_size = _sanitize_reference_profile(raw_profile)
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


def _sanitize_reference_profile(raw_profile: Any) -> tuple[dict[str, Any], int, bool]:
    if not isinstance(raw_profile, dict):
        return {}, 0, False
    sanitized_count = sum(1 for key in raw_profile if key.lower() in _COPYABLE_REFERENCE_KEYS)
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
