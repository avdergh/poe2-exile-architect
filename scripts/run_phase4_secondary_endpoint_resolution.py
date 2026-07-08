"""Resolve secondary Phase 4 mechanism endpoints for semantic edge proposals.

This script consumes only safe Phase 4 extraction reports. It does not read raw
PoB/XML, does not create graph nodes, and does not write semantic edges.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server import paths  # noqa: E402
from server.knowledge import copy_safety, graph_tools, physical_graph  # noqa: E402

INPUT_REPORT = REPO_ROOT / "phase4_real_research_extraction_report.json"
JSON_OUTPUT = REPO_ROOT / "phase4_secondary_endpoint_resolution_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_secondary_endpoint_resolution_report.md"

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
    "pobb.in/",
    "poe.ninja/",
)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
SECONDARY_NAME_PATTERNS = (
    "Barrage",
    "Combat Frenzy",
    "Cooldown Recovery II",
    "Herald of Ice",
    "Herald of Thunder",
    "Wild Protector",
)
MECHANISM_CAVEAT_PATTERNS = (
    "Freeze",
    "Overcharge",
    "Shock",
)


def build_secondary_endpoint_resolution_report(
    *,
    input_report: str | Path = INPUT_REPORT,
    graph_snapshot_index: str | Path | None = None,
) -> dict[str, Any]:
    extraction = json.loads(Path(input_report).read_text(encoding="utf-8"))
    _validate_extraction_report(extraction)
    index_path = (
        Path(graph_snapshot_index)
        if graph_snapshot_index is not None
        else paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"
    )
    graph_status, graph_caveats, service = _graph_service(index_path)
    endpoints: list[dict[str, Any]] = []
    for sample in extraction.get("samples", []):
        if not isinstance(sample, dict):
            continue
        endpoints.extend(
            _resolve_sample_secondaries(sample, service=service, graph_status=graph_status)
        )

    metrics = {
        "sampleCount": len(
            [item for item in extraction.get("samples", []) if isinstance(item, dict)]
        ),
        "candidateCount": len(endpoints),
        "resolvedCount": sum(1 for item in endpoints if item["resolverStatus"] == "resolved"),
        "ambiguousCount": sum(1 for item in endpoints if item["resolverStatus"] == "ambiguous"),
        "missingCount": sum(1 for item in endpoints if item["resolverStatus"] == "missing"),
        "notGraphEntityCount": sum(
            1 for item in endpoints if item["resolverStatus"] == "not_graph_entity"
        ),
        "graphUnavailableCount": sum(
            1 for item in endpoints if item["resolverStatus"] == "graph_unavailable"
        ),
        "semanticEdgeWritesAttempted": 0,
    }
    report = {
        "reportId": "phase4-secondary-endpoint-resolution-v1",
        "inputReportId": _safe_token_field("reportId", extraction.get("reportId")),
        "status": (
            "secondary_endpoint_resolution_completed"
            if graph_status == "available"
            else "graph_snapshot_unavailable"
        ),
        "safeArtifactOnly": True,
        "graphSnapshotIndex": _safe_relative(index_path),
        "snapshotId": service.snapshot.snapshot_id if service is not None else None,
        "secondaryEndpoints": endpoints,
        "semanticEdgeWrite": {
            "attempted": False,
            "reason": "resolution_probe_only_external_semantic_proposal_required",
        },
        "metrics": metrics,
        "caveats": [
            "Secondary endpoints are resolver probes only; this report does not create nodes or edges.",
            "Abstract mechanism tags are kept as verification caveats, not physical graph endpoints.",
            "Pending primary endpoints cannot contribute ready semantic edge endpoints.",
            *graph_caveats,
        ],
    }
    _assert_safe_report(report)
    return report


def write_secondary_endpoint_resolution_report(
    *,
    input_report: str | Path = INPUT_REPORT,
    graph_snapshot_index: str | Path | None = None,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_secondary_endpoint_resolution_report(
        input_report=input_report,
        graph_snapshot_index=graph_snapshot_index,
    )
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _resolve_sample_secondaries(
    sample: dict[str, Any],
    *,
    service: graph_tools.GraphQueryService | None,
    graph_status: str,
) -> list[dict[str, Any]]:
    sample_id = _safe_token(sample.get("sampleId"))
    primary_key = (
        _safe_stable_key(sample.get("acceptedStableKey"))
        if sample.get("acceptedStableKey")
        else None
    )
    primary_status = "accepted" if primary_key else "pending_manual_review"
    candidate_names, abstract_tags = _secondary_candidates(sample)
    endpoints: list[dict[str, Any]] = []
    for tag in abstract_tags:
        endpoints.append(
            _base_endpoint(
                sample_id=sample_id,
                primary_key=primary_key,
                primary_status=primary_status,
                candidate_name=tag,
                candidate_kind="abstract_mechanism_tag",
                resolver_status="not_graph_entity",
                semantic_action="verification_caveat_only",
            )
        )
    for name in candidate_names:
        endpoints.append(
            _resolve_candidate(
                sample_id=sample_id,
                primary_key=primary_key,
                primary_status=primary_status,
                candidate_name=name,
                service=service,
                graph_status=graph_status,
            )
        )
    return endpoints


def _secondary_candidates(sample: dict[str, Any]) -> tuple[list[str], list[str]]:
    names: set[str] = set()
    abstract_tags: set[str] = set()
    signals = (
        sample.get("observedSafeSignals")
        if isinstance(sample.get("observedSafeSignals"), dict)
        else {}
    )
    for tag in signals.get("mechanicTags") or []:
        text = _safe_text(tag)
        if text:
            abstract_tags.add(text)
    for name in signals.get("primarySkillPreview") or []:
        text = _safe_text(name)
        if text and text != _safe_text(sample.get("mainSkill")):
            if text in MECHANISM_CAVEAT_PATTERNS:
                abstract_tags.add(text)
            else:
                names.add(text)
    for fragment in sample.get("extractedFragments") or []:
        if not isinstance(fragment, dict):
            continue
        haystack = " ".join(
            str(item)
            for key in ("summaryZh", "conditionsZh", "risksZh", "verificationTasksZh")
            for item in (
                fragment.get(key) if isinstance(fragment.get(key), list) else [fragment.get(key)]
            )
            if item
        )
        _reject_copyable(haystack)
        for pattern in SECONDARY_NAME_PATTERNS:
            if pattern.casefold() in haystack.casefold():
                names.add(pattern)
        for pattern in MECHANISM_CAVEAT_PATTERNS:
            if pattern.casefold() in haystack.casefold():
                abstract_tags.add(pattern)
    names.discard(_safe_text(sample.get("mainSkill")))
    return sorted(names), sorted(abstract_tags)


def _resolve_candidate(
    *,
    sample_id: str,
    primary_key: str | None,
    primary_status: str,
    candidate_name: str,
    service: graph_tools.GraphQueryService | None,
    graph_status: str,
) -> dict[str, Any]:
    if service is None or graph_status != "available":
        endpoint = _base_endpoint(
            sample_id=sample_id,
            primary_key=primary_key,
            primary_status=primary_status,
            candidate_name=candidate_name,
            candidate_kind="secondary_component",
            resolver_status="graph_unavailable",
            semantic_action="deferred_source_coverage_gap",
        )
        endpoint["endpointAssessment"] = _endpoint_assessment(
            "graph_snapshot_unavailable",
            "No local graph snapshot was available for secondary endpoint resolution.",
        )
        return endpoint
    first = service.run_tool("resolve_graph_component", {"query": candidate_name})
    resolved = _resolved_endpoint_from_result(first)
    if resolved is not None:
        return _endpoint_from_resolution(
            sample_id=sample_id,
            primary_key=primary_key,
            primary_status=primary_status,
            candidate_name=candidate_name,
            candidate_kind="secondary_component",
            result=first,
            resolution_method="direct_resolver",
        )
    status = str(first.get("status") or "missing")
    if status not in {"ambiguous", "missing"}:
        status = "missing"
    action = (
        "requires_manual_endpoint_mapping"
        if status == "ambiguous"
        else "deferred_source_coverage_gap"
    )
    endpoint = _base_endpoint(
        sample_id=sample_id,
        primary_key=primary_key,
        primary_status=primary_status,
        candidate_name=candidate_name,
        candidate_kind="secondary_component",
        resolver_status=status,
        semantic_action=action,
    )
    facts = first.get("facts") if isinstance(first.get("facts"), dict) else {}
    endpoint["candidateCount"] = len(facts.get("candidates") or [])
    endpoint["candidates"] = [_candidate_summary(item) for item in facts.get("candidates") or []]
    assessment = first.get("endpointAssessment")
    if isinstance(assessment, dict):
        endpoint["endpointAssessment"] = _safe_json(assessment)
    elif status == "ambiguous":
        endpoint["endpointAssessment"] = _endpoint_assessment(
            "ambiguous_endpoint",
            "Resolver returned multiple source-backed candidates; manual endpoint mapping is required.",
        )
    elif status == "missing":
        endpoint["endpointAssessment"] = _endpoint_assessment(
            "source_coverage_gap",
            "Resolver did not find a source-backed endpoint for this secondary concept.",
        )
    return endpoint


def _endpoint_from_resolution(
    *,
    sample_id: str,
    primary_key: str | None,
    primary_status: str,
    candidate_name: str,
    candidate_kind: str,
    result: dict[str, Any],
    resolution_method: str,
) -> dict[str, Any]:
    resolved = _resolved_endpoint_from_result(result)
    assert resolved is not None
    evidence = _resolver_evidence(result, resolved["stableKey"])
    action = (
        "ready_for_external_semantic_edge"
        if primary_status == "accepted"
        else "blocked_primary_endpoint_pending"
    )
    return {
        **_base_endpoint(
            sample_id=sample_id,
            primary_key=primary_key,
            primary_status=primary_status,
            candidate_name=candidate_name,
            candidate_kind=candidate_kind,
            resolver_status="resolved",
            semantic_action=action,
        ),
        "stableKey": resolved["stableKey"],
        "nodeType": resolved["nodeType"],
        "sourceRefs": evidence["source_refs"],
        "evidencePathNodes": evidence["evidence_path_nodes"],
        "resolverEvidence": evidence,
        "resolutionMethod": resolution_method,
    }


def _base_endpoint(
    *,
    sample_id: str,
    primary_key: str | None,
    primary_status: str,
    candidate_name: str,
    candidate_kind: str,
    resolver_status: str,
    semantic_action: str,
) -> dict[str, Any]:
    return {
        "sampleId": sample_id,
        "sampleEndpointStatus": primary_status,
        "primaryStableKey": primary_key,
        "candidateName": _safe_text(candidate_name),
        "candidateKind": candidate_kind,
        "resolverStatus": resolver_status,
        "stableKey": None,
        "nodeType": None,
        "candidateCount": 0,
        "candidates": [],
        "sourceRefs": [],
        "evidencePathNodes": [],
        "semanticEdgeAction": semantic_action,
        "noRawMatureBuildMaterial": True,
    }


def _resolved_endpoint_from_result(result: dict[str, Any]) -> dict[str, str] | None:
    if result.get("status") != "resolved":
        return None
    subject = result.get("resolvedSubject")
    if not isinstance(subject, dict):
        return None
    stable_key = subject.get("stableKey")
    node_type = subject.get("nodeType")
    if not isinstance(stable_key, str) or not isinstance(node_type, str):
        return None
    return {"stableKey": _safe_stable_key(stable_key), "nodeType": _safe_text(node_type)}


def _resolver_evidence(result: dict[str, Any], stable_key: str) -> dict[str, Any]:
    evidence_path = (
        result.get("evidencePath") if isinstance(result.get("evidencePath"), dict) else {}
    )
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": _safe_stable_key(stable_key),
        "snapshot_id": _safe_text(result.get("snapshotId")),
        "evidence_path_nodes": [_safe_stable_key(item) for item in evidence_path.get("nodes", [])],
        "source_refs": [_safe_text(item) for item in result.get("sourceRefs", [])],
    }


def _graph_service(
    index_path: Path,
) -> tuple[str, list[str], graph_tools.GraphQueryService | None]:
    rows = physical_graph.list_registered_snapshots(index_path)
    if not rows:
        return "unavailable", ["missing registered snapshot index"], None
    latest = next((row for row in rows if row["is_latest"]), rows[0])
    snapshot_path = Path(str(latest.get("snapshot_path") or ""))
    if not snapshot_path.exists():
        return "unavailable", ["registered snapshot file is missing"], None
    graph_tools.clear_service_cache()
    return "available", [], graph_tools.service_from_snapshot_index(str(index_path))


def _validate_extraction_report(extraction: dict[str, Any]) -> None:
    if extraction.get("safeArtifactOnly") is not True:
        raise ValueError("input extraction report must be safe-only")
    if not isinstance(extraction.get("samples"), list):
        raise ValueError("input extraction report samples must be a list")
    _safe_token_field("reportId", extraction.get("reportId"))
    _assert_safe_report(extraction)


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "stableKey": _safe_text(candidate.get("stableKey")),
        "nodeType": _safe_text(candidate.get("nodeType")),
        "sourceRefs": [_safe_text(item) for item in candidate.get("sourceRefs", [])],
    }


def _endpoint_assessment(classification: str, reason: str) -> dict[str, Any]:
    return {
        "classification": classification,
        "hallucinationVerdict": "not_assessed",
        "reason": reason,
        "requiresStaticSourceReview": True,
    }


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(_safe_text(key)): _safe_json(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_safe_json(child) for child in value]
    if isinstance(value, str):
        return _safe_text(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _safe_text(value)


def _safe_text(value: Any) -> str:
    text = " ".join(str(value or "").split())[:180]
    _reject_copyable(text)
    return text


def _safe_token(value: Any) -> str:
    text = str(value or "unknown").strip()
    _reject_copyable(text)
    safe = "".join(ch if ch.isalnum() or ch in "_:-." else "-" for ch in text)
    return safe[:80] or "unknown"


def _safe_token_field(field: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    _reject_copyable(text)
    if not TOKEN_RE.fullmatch(text):
        raise ValueError(f"{field} must be a safe token")
    return text


def _safe_stable_key(value: Any) -> str:
    text = str(value or "").strip()
    _reject_copyable(text)
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,180}", text):
        raise ValueError("stable key must be safe")
    return text


def _reject_copyable(text: str) -> None:
    lower = text.lower()
    if any(marker.lower() in lower for marker in RAW_MARKERS):
        raise ValueError("copy-safety marker detected")
    if re.search(
        r"(?:https?://|www\.|pobb\.in|pastebin\.com|poe\.ninja|pathofexile\.com)",
        lower,
    ):
        raise ValueError("copy-safety URL marker detected")
    flags = set(copy_safety.copyability_flags(text))
    flags.discard("full_gem_link_like")
    if flags:
        raise ValueError(f"copy-safety flags detected: {', '.join(sorted(flags))}")


def _assert_safe_report(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe durable report markers detected: {', '.join(leaks)}")
    flags = set(copy_safety.copyability_flags(report))
    flags.discard("full_gem_link_like")
    if flags:
        raise ValueError(f"durable report failed copy-safety scan: {', '.join(sorted(flags))}")
    forbidden = copy_safety.find_forbidden_paths(report)
    if forbidden:
        raise ValueError("durable report contains forbidden raw fields")


def _safe_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4 Secondary Endpoint Resolution",
        "",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Snapshot: `{report.get('snapshotId')}`",
        f"- Resolved endpoints: `{report['metrics']['resolvedCount']}`",
        f"- Semantic edge write attempted: `{report['semanticEdgeWrite']['attempted']}`",
        "",
        "## Secondary Endpoints",
        "",
    ]
    for item in report["secondaryEndpoints"]:
        if item["sampleEndpointStatus"] != "accepted":
            continue
        lines.append(
            f"- `{item['sampleId']}` / `{item['candidateName']}`: `{item['resolverStatus']}` -> `{item['semanticEdgeAction']}`"
        )
        if item.get("stableKey"):
            lines.append(f"  - stable key: `{item['stableKey']}`")
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.append("")
    text = "\n".join(lines)
    for marker in RAW_MARKERS:
        if marker in text:
            raise ValueError(f"unsafe markdown marker detected: {marker}")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-report", default=str(INPUT_REPORT))
    parser.add_argument(
        "--graph-snapshot-index",
        default=str(paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"),
    )
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    report = write_secondary_endpoint_resolution_report(
        input_report=args.input_report,
        graph_snapshot_index=args.graph_snapshot_index,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["secondaryEndpoints"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
