"""Accept safe Phase 4.5 deep-review candidates into durable pattern memory.

The fallback subagent deep-review pass returns safe candidate reviews, not final
durable knowledge. This controller accepts only candidates that are backed by a
structured safe review artifact and public resolver evidence. Ambiguous names
must also reference an explicit reviewed endpoint mapping decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server import paths  # noqa: E402
from server.knowledge import copy_safety, graph_tools, research_memory, research_models  # noqa: E402

JSON_OUTPUT = REPO_ROOT / "phase4_deep_review_acceptance_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_deep_review_acceptance_report.md"
DB_PATH = REPO_ROOT / "phase4_real_research_memory.sqlite"
REVIEW_FILE = REPO_ROOT / "phase4_deep_researcher_candidate_review.json"
PRIMARY_MAPPING_REPORT = REPO_ROOT / "phase4_reviewed_endpoint_mapping_report.json"
SECONDARY_MAPPING_REPORT = REPO_ROOT / "phase4_reviewed_secondary_endpoint_mapping_report.json"
DEEP_COMPONENT_MAPPING_REPORT = REPO_ROOT / "phase4_deep_reviewed_component_mapping_report.json"

RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
    "transientPacketPath",
    "transientPromptPath",
    "packet.json",
    "deep_researcher_prompt.txt",
    "pobb.in/",
    "poe.ninja/",
)

PATTERN_TYPE_VALUES = {
    "build_archetype",
    "cooccurrence",
    "transition_gate",
    "failure_pattern",
    "planner_hint",
}

AXIS_ALIASES = {
    "modelability_caveat": "modelability_caveats",
    "modelability_caveats": "modelability_caveats",
    "variant_relation": "variant_relations",
    "variant_relations": "variant_relations",
}

DESIGN_AXIS_VALUES = {
    "identity",
    "character_shell",
    "primary_skill_package",
    "secondary_skill_package",
    "passive_tree_shape",
    "itemization",
    "scaling_axis",
    "resource_engine",
    "defense_layers",
    "mechanic_engine",
    "rotation_playstyle",
    "transition_gates",
    "failure_modes",
    "variant_relations",
    "modelability_caveats",
}


def accept_deep_review_candidates(
    *,
    db_path: str | Path = DB_PATH,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
    review_file: str | Path = REVIEW_FILE,
    primary_mapping_report: str | Path | None = PRIMARY_MAPPING_REPORT,
    secondary_mapping_report: str | Path | None = SECONDARY_MAPPING_REPORT,
    component_mapping_reports: list[str | Path] | None = None,
    graph_service: graph_tools.GraphQueryService | None = None,
) -> dict[str, Any]:
    graph_service = graph_service or _graph_service()
    review = _load_safe_json(Path(review_file), expected_safe=True)
    reviewed_mappings = _reviewed_mappings(
        primary_mapping_report=Path(primary_mapping_report) if primary_mapping_report else None,
        secondary_mapping_report=Path(secondary_mapping_report)
        if secondary_mapping_report
        else None,
        component_mapping_reports=[Path(item) for item in component_mapping_reports or []],
    )
    payload, accepted_summaries, deferred = _build_payload(
        graph_service=graph_service,
        review=review,
        reviewed_mappings=reviewed_mappings,
    )
    service = research_memory.ResearchMemoryService(
        db_path=Path(db_path), graph_service=graph_service
    )
    result = (
        service.propose_build_patterns(payload)
        if payload["build_design_observations"] or payload["patterns"]
        else {
            "status": "accepted",
            "observationIds": [],
            "patternIds": [],
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }
    )
    report = {
        "reportId": "phase4-deep-review-acceptance-v2",
        "status": "accepted" if result.get("status") == "accepted" else "rejected",
        "safeArtifactOnly": True,
        "inputKind": "safe_deep_researcher_candidate_review",
        "inputReviewReportId": str(review.get("reportId") or ""),
        "patternWrite": result,
        "acceptedPatternCount": len(result.get("patternIds") or [])
        if result.get("status") == "accepted"
        else 0,
        "acceptedObservationCount": len(result.get("observationIds") or [])
        if result.get("status") == "accepted"
        else 0,
        "acceptedPatterns": accepted_summaries if result.get("status") == "accepted" else [],
        "deferredCandidateCount": len(deferred),
        "deferredCandidates": deferred,
        "caveats": [
            "Only structured safe candidate reviews were considered.",
            "Resolver evidence came from public resolve_graph_component output.",
            "Ambiguous resolver results require explicit reviewed endpoint mapping.",
            "All accepted deep-review patterns are case_observation, not common/usually claims.",
            "Subagent text was not trusted directly; ResearchMemoryService performed typed acceptance.",
        ],
    }
    _write_safe_report(report, Path(json_output), Path(md_output))
    return report


def _build_payload(
    *,
    graph_service: graph_tools.GraphQueryService,
    review: dict[str, Any],
    reviewed_mappings: dict[tuple[str, str, str], dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    observations: list[dict[str, Any]] = []
    patterns: list[dict[str, Any]] = []
    accepted_summaries: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for candidate in _candidate_reviews(review):
        sample_id = str(candidate["sampleId"])
        components = list(candidate["components"])
        resolved_components = []
        component_roles: dict[str, str] = {}
        component_keys: list[str] = []
        component_resolution_summaries: list[dict[str, Any]] = []
        candidate_deferred: list[dict[str, Any]] = []
        for component in components:
            resolution = _resolve_component(
                graph_service=graph_service,
                sample_id=sample_id,
                component=component,
                reviewed_mappings=reviewed_mappings,
            )
            if resolution["status"] != "accepted":
                candidate_deferred.append(resolution)
                continue
            component_key = str(component["componentKey"])
            role = str(component["role"])
            resolved_components.append(
                {
                    "component_key": component_key,
                    "role": role,
                    "resolution": resolution["evidence"],
                }
            )
            component_keys.append(component_key)
            component_roles[component_key] = role
            component_resolution_summaries.append(
                {
                    "componentKey": component_key,
                    "candidateName": str(component.get("candidateName") or ""),
                    "resolverStatus": resolution["resolverStatus"],
                    "resolutionSource": resolution["resolutionSource"],
                }
            )
        if candidate_deferred:
            deferred.append(
                {
                    "titleZh": candidate["title"],
                    "sampleId": sample_id,
                    "reason": candidate_deferred[0]["reason"],
                    "componentKeys": [item["componentKey"] for item in candidate_deferred],
                    "componentReasons": candidate_deferred,
                }
            )
            continue
        base = {
            "source_case_refs": [candidate["caseRef"]],
            "safe_evidence_refs": [candidate["safeEvidenceRef"]],
            "game_patch": str(candidate.get("gamePatch") or "0.5.4"),
            "passive_tree_version": str(candidate.get("passiveTreeVersion") or "0_5"),
            "pob_version_or_commit": str(candidate.get("pobVersionOrCommit") or "unknown"),
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledge_scope": "global_seed",
        }
        observation = {
            "observation_type": candidate["patternType"],
            "title": candidate["title"],
            "summary": candidate["summary"],
            "axes": candidate["axes"],
            "components": resolved_components,
            **base,
        }
        pattern = {
            "pattern_type": candidate["patternType"],
            "title": candidate["title"],
            "summary": candidate["summary"],
            "component_keys": component_keys,
            "component_roles": component_roles,
            "confidence_tier": "case_observation",
            "sample_count": 1,
            "family_count": 1,
            "source_diversity_count": 1,
            "denominator": 1,
            "context_requirements": [
                {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_mature"]},
                {
                    "context_type": "verification_gate_requirement",
                    "task": candidate["verificationGate"],
                },
            ],
            "planner_hint": candidate["plannerHint"],
            "verification_tasks": candidate["verificationTasks"],
            **base,
        }
        candidate_validation = research_models.validate_researcher_output(
            {
                "schema_version": 4,
                "build_design_observations": [observation],
                "patterns": [pattern],
            }
        )
        if candidate_validation.get("status") == "error":
            deferred.append(
                {
                    "titleZh": candidate["title"],
                    "sampleId": sample_id,
                    "reason": str(candidate_validation.get("errorCode") or "invalid_candidate"),
                    "componentKeys": component_keys,
                    "caveats": list(candidate_validation.get("caveats") or []),
                }
            )
            continue
        observations.append(observation)
        patterns.append(pattern)
        accepted_summaries.append(
            {
                "titleZh": candidate["title"],
                "summaryZh": candidate["summary"],
                "confidenceTier": "case_observation",
                "sampleId": sample_id,
                "componentKeys": component_keys,
                "componentResolutions": component_resolution_summaries,
            }
        )
    return (
        {"schema_version": 4, "build_design_observations": observations, "patterns": patterns},
        accepted_summaries,
        deferred,
    )


def _resolve_component(
    *,
    graph_service: graph_tools.GraphQueryService,
    sample_id: str,
    component: dict[str, Any],
    reviewed_mappings: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    component_key = str(component["componentKey"])
    candidate_name = str(component.get("candidateName") or "")
    resolver_query = str(component.get("resolverQuery") or candidate_name or component_key)
    result = graph_service.run_tool("resolve_graph_component", {"query": resolver_query})
    status = str(result.get("status") or "")
    if status == "resolved":
        resolved_key = str((result.get("resolvedSubject") or {}).get("stableKey") or "")
        if resolved_key == component_key:
            return {
                "status": "accepted",
                "resolverStatus": status,
                "resolutionSource": "direct_resolver",
                "evidence": _evidence_from_resolver(result, component_key),
            }
        return {
            "status": "deferred",
            "reason": "resolver_key_mismatch",
            "componentKey": component_key,
            "candidateName": candidate_name,
            "resolverStatus": status,
            "resolvedKey": resolved_key,
        }
    if status == "ambiguous":
        current_candidate = _resolver_candidate(result, component_key)
        if current_candidate is None:
            return {
                "status": "deferred",
                "reason": "ambiguous_endpoint_not_in_current_resolver_candidates",
                "componentKey": component_key,
                "candidateName": candidate_name,
                "resolverStatus": status,
            }
        reviewed = _matching_reviewed_mapping(
            sample_id=sample_id,
            candidate_name=candidate_name,
            component_key=component_key,
            reviewed_mappings=reviewed_mappings,
        )
        if reviewed is None:
            return {
                "status": "deferred",
                "reason": "ambiguous_endpoint_requires_reviewed_mapping",
                "componentKey": component_key,
                "candidateName": candidate_name,
                "resolverStatus": status,
            }
        return {
            "status": "accepted",
            "resolverStatus": status,
            "resolutionSource": "reviewed_mapping",
            "evidence": _evidence_from_reviewed_mapping(result, reviewed, current_candidate),
        }
    reason = "source_coverage_gap" if status in {"missing", "unknown"} else f"resolver_{status}"
    return {
        "status": "deferred",
        "reason": reason,
        "componentKey": component_key,
        "candidateName": candidate_name,
        "resolverStatus": status,
    }


def _evidence_from_resolver(result: dict[str, Any], component_key: str) -> dict[str, Any]:
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": component_key,
        "snapshot_id": str(result["snapshotId"]),
        "evidence_path_nodes": [component_key],
        "source_refs": list(result.get("sourceRefs") or []),
    }


def _evidence_from_reviewed_mapping(
    result: dict[str, Any],
    reviewed: dict[str, Any],
    current_candidate: dict[str, Any],
) -> dict[str, Any]:
    component_key = str(reviewed["acceptedStableKey"])
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": component_key,
        "snapshot_id": str(result["snapshotId"]),
        "evidence_path_nodes": [component_key],
        "source_refs": list(current_candidate.get("sourceRefs") or []),
    }


def _resolver_candidate(result: dict[str, Any], component_key: str) -> dict[str, Any] | None:
    candidates = list((result.get("facts") or {}).get("candidates") or [])
    return next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and str(item.get("stableKey") or "") == component_key
        ),
        None,
    )


def _matching_reviewed_mapping(
    *,
    sample_id: str,
    candidate_name: str,
    component_key: str,
    reviewed_mappings: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    return reviewed_mappings.get((sample_id, candidate_name.casefold(), component_key))


def _reviewed_mappings(
    *,
    primary_mapping_report: Path | None,
    secondary_mapping_report: Path | None,
    component_mapping_reports: list[Path],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    mappings: dict[tuple[str, str, str], dict[str, Any]] = {}
    paths = [primary_mapping_report, secondary_mapping_report, *component_mapping_reports]
    for path in paths:
        if path is None or not path.exists():
            continue
        payload = _load_safe_json(path, expected_safe=True)
        if str(payload.get("safeArtifactOnly")).casefold() != "true":
            continue
        for item in payload.get("reviewItems") or []:
            if not isinstance(item, dict) or item.get("reviewStatus") != "accepted":
                continue
            sample_id = str(item.get("sampleId") or "")
            candidate_name = str(item.get("candidateName") or "")
            accepted_key = str(item.get("acceptedStableKey") or "")
            if not sample_id or not candidate_name or not accepted_key:
                continue
            candidate = next(
                (
                    candidate
                    for candidate in item.get("candidates") or []
                    if isinstance(candidate, dict)
                    and str(candidate.get("stableKey") or "") == accepted_key
                ),
                None,
            )
            if candidate is None:
                continue
            mappings[(sample_id, candidate_name.casefold(), accepted_key)] = {
                "sampleId": sample_id,
                "candidateName": candidate_name,
                "acceptedStableKey": accepted_key,
                "sourceRefs": list(candidate.get("sourceRefs") or []),
                "reportId": str(payload.get("reportId") or ""),
                "snapshotId": str(payload.get("snapshotId") or ""),
            }
    return mappings


def _candidate_reviews(review: dict[str, Any]) -> list[dict[str, Any]]:
    if str(review.get("safeArtifactOnly")).casefold() != "true":
        raise ValueError("deep review artifact must be safeArtifactOnly=true")
    candidates = review.get("candidateReviews") or []
    if not isinstance(candidates, list):
        raise ValueError("deep review candidateReviews must be a list")
    normalized: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("deep review candidate must be an object")
        components = candidate.get("components") or []
        if not isinstance(components, list):
            raise ValueError("deep review components must be a list")
        normalized.append(
            {
                "sampleId": _required(candidate, "sampleId"),
                "caseRef": _required(candidate, "caseRef"),
                "safeEvidenceRef": _required(candidate, "safeEvidenceRef"),
                "patternType": _normalize_pattern_type(_required(candidate, "patternType")),
                "title": _required(candidate, "title"),
                "summary": _required(candidate, "summary"),
                "axes": _normalize_axes(_string_list(candidate, "axes")),
                "components": [_component_payload(component) for component in components],
                "plannerHint": _required(candidate, "plannerHint"),
                "verificationGate": _required(candidate, "verificationGate"),
                "verificationTasks": _string_list(candidate, "verificationTasks"),
                "gamePatch": str(candidate.get("gamePatch") or "0.5.4"),
                "passiveTreeVersion": str(candidate.get("passiveTreeVersion") or "0_5"),
                "pobVersionOrCommit": str(candidate.get("pobVersionOrCommit") or "unknown"),
            }
        )
    return normalized


def _normalize_pattern_type(value: str) -> str:
    match = _canonical_enum_match(value, PATTERN_TYPE_VALUES)
    return match or value


def _normalize_axes(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        token = _enum_token(value)
        normalized_value = AXIS_ALIASES.get(
            token, _canonical_enum_match(value, DESIGN_AXIS_VALUES) or token
        )
        normalized.append(normalized_value)
    return normalized


def _canonical_enum_match(value: str, allowed_values: set[str]) -> str | None:
    compact_value = _compact_enum_token(value)
    matches = [
        allowed
        for allowed in sorted(allowed_values)
        if (compact_allowed := _compact_enum_token(allowed))
        and (compact_value == compact_allowed or compact_allowed in compact_value)
    ]
    return matches[0] if len(matches) == 1 else None


def _compact_enum_token(value: str) -> str:
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def _enum_token(value: str) -> str:
    text = str(value or "").strip()
    if "_" in text:
        return "_".join(part for part in text.casefold().split("_") if part)
    if "-" in text:
        return "_".join(part for part in text.casefold().split("-") if part)
    return "".join(char for char in text.casefold() if char.isalnum() or char == "_")


def _component_payload(component: Any) -> dict[str, str]:
    if not isinstance(component, dict):
        raise ValueError("deep review component must be an object")
    return {
        "candidateName": _required(component, "candidateName"),
        "componentKey": _required(component, "componentKey"),
        "role": _required(component, "role"),
        "resolverQuery": str(
            component.get("resolverQuery") or component.get("candidateName") or ""
        ),
    }


def _required(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"deep review missing required field: {key}")
    return value


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    values = payload.get(key) or []
    if not isinstance(values, list) or not values:
        raise ValueError(f"deep review field must be a non-empty list: {key}")
    return [str(item) for item in values]


def _load_safe_json(path: Path, *, expected_safe: bool) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"safe artifact must be a JSON object: {path}")
    if expected_safe:
        _assert_safe(payload)
    return payload


def _graph_service() -> graph_tools.GraphQueryService:
    index_path = paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"
    return graph_tools.service_from_snapshot_index(str(index_path))


def _write_safe_report(report: dict[str, Any], json_output: Path, md_output: Path) -> None:
    _assert_safe(report)
    json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_output.write_text(_markdown(report), encoding="utf-8")


def _assert_safe(report: dict[str, Any]) -> None:
    _assert_valid_unicode(report)
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe deep review acceptance report markers: {', '.join(leaks)}")
    if copy_safety.find_forbidden_paths(report):
        raise ValueError("unsafe deep review acceptance report contains forbidden raw fields")
    flags = _copyability_flags_for_safe_text(report)
    if flags:
        raise ValueError(f"unsafe deep review acceptance report failed copy-safety: {flags}")


def _assert_valid_unicode(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _assert_valid_unicode(child, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_valid_unicode(child, path=f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError(f"invalid unicode surrogate in deep review artifact at {path}")
    mojibake_markers = ("鍚", "鏃", "鐢", "鑳", "璇", "锛", "绛", "嬪", "熸", "浣")
    if sum(value.count(marker) for marker in mojibake_markers) >= 3:
        raise ValueError(f"invalid unicode mojibake in deep review artifact at {path}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"invalid unicode in deep review artifact at {path}") from exc


def _copyability_flags_for_safe_text(value: Any, *, key: str = "") -> list[str]:
    text_fields = {
        "title",
        "summary",
        "titleZh",
        "summaryZh",
        "reason",
        "caveats",
        "plannerHint",
        "planner_hint",
        "verificationTasks",
        "verification_tasks",
        "verificationGate",
        "verification_gate",
        "deferredCandidates",
    }
    flags: set[str] = set()
    if isinstance(value, dict):
        for child_key, child in value.items():
            flags.update(_copyability_flags_for_safe_text(child, key=str(child_key)))
    elif isinstance(value, list):
        for child in value:
            flags.update(_copyability_flags_for_safe_text(child, key=key))
    elif isinstance(value, str) and key in text_fields:
        flags.update(copy_safety.copyability_flags(value))
    return sorted(flags)


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4.5 Deep Review Acceptance",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Accepted patterns: `{report.get('acceptedPatternCount')}`",
        f"- Deferred candidates: `{report.get('deferredCandidateCount')}`",
        "",
        "## Caveats",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("caveats", []))
    lines.extend(["", "## Accepted Patterns", ""])
    for pattern in report.get("acceptedPatterns", []):
        lines.extend(
            [
                f"- {pattern.get('titleZh')}",
                f"  - confidence: `{pattern.get('confidenceTier')}`",
                f"  - sample: `{pattern.get('sampleId')}`",
                f"  - components: `{', '.join(pattern.get('componentKeys') or [])}`",
            ]
        )
    lines.extend(["", "## Deferred", ""])
    for item in report.get("deferredCandidates", []):
        lines.append(f"- {item.get('titleZh')}: `{item.get('reason')}`")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=str(DB_PATH))
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    parser.add_argument("--review-file", default=str(REVIEW_FILE))
    parser.add_argument("--primary-mapping-report", default=str(PRIMARY_MAPPING_REPORT))
    parser.add_argument("--secondary-mapping-report", default=str(SECONDARY_MAPPING_REPORT))
    parser.add_argument(
        "--component-mapping-report",
        action="append",
        default=[str(DEEP_COMPONENT_MAPPING_REPORT)]
        if DEEP_COMPONENT_MAPPING_REPORT.exists()
        else [],
    )
    args = parser.parse_args(argv)
    report = accept_deep_review_candidates(
        db_path=args.db_path,
        json_output=args.json_output,
        md_output=args.md_output,
        review_file=args.review_file,
        primary_mapping_report=args.primary_mapping_report,
        secondary_mapping_report=args.secondary_mapping_report,
        component_mapping_reports=list(args.component_mapping_report or []),
    )
    print(
        json.dumps(
            {"status": report["status"], "acceptedPatternCount": report["acceptedPatternCount"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
