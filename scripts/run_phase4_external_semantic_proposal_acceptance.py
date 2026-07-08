"""Accept an external Researcher semantic proposal through the Phase 4 gate.

The gate first ensures every semantic edge endpoint belongs to the reviewed
accepted endpoint mapping. Only then does it delegate to ResearchMemoryService,
which performs schema, copy-safety, resolver-evidence, and graph endpoint checks.
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
from server.knowledge import copy_safety, graph_tools, research_memory  # noqa: E402

MAPPING_REPORT = REPO_ROOT / "phase4_reviewed_endpoint_mapping_report.json"
REVIEWED_SECONDARY_ENDPOINT_REPORT = (
    REPO_ROOT / "phase4_reviewed_secondary_endpoint_mapping_report.json"
)
JSON_OUTPUT = REPO_ROOT / "phase4_external_semantic_proposal_acceptance_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_external_semantic_proposal_acceptance_report.md"
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
PRIMARY_MAPPING_REPORT_ID = "phase4-reviewed-endpoint-mapping-v1"
REVIEWED_SECONDARY_MAPPING_REPORT_ID = "phase4-reviewed-secondary-endpoint-mapping-v1"
SECONDARY_REVIEW_REPORT_ID = "phase4-secondary-endpoint-review-v1"
PHASE4_REAL_EDGE_TYPES = {"has_modelability_caveat"}


def build_external_semantic_proposal_acceptance_report(
    *,
    mapping_report: str | Path = MAPPING_REPORT,
    secondary_endpoint_report: str | Path | None = None,
    proposal_file: str | Path | None,
    db_path: str | Path | None = None,
    graph_snapshot_index: str | Path | None = None,
) -> dict[str, Any]:
    mapping = json.loads(Path(mapping_report).read_text(encoding="utf-8"))
    _validate_mapping_report(mapping)
    primary_snapshot_id = _safe_text(mapping.get("snapshotId"))
    accepted_primary_by_sample = _accepted_primary_by_sample(mapping)
    accepted_primary_keys = set(accepted_primary_by_sample.values())
    secondary_surface = _secondary_endpoint_surface(
        secondary_endpoint_report,
        accepted_primary_by_sample=accepted_primary_by_sample,
        primary_snapshot_id=primary_snapshot_id,
    )
    accepted_secondary_keys = secondary_surface["acceptedSecondaryKeys"]
    allowed_pairs = secondary_surface["allowedPairs"]
    accepted_keys = accepted_primary_keys | accepted_secondary_keys
    if proposal_file is None:
        report = _deferred_report(
            accepted_endpoint_count=len(accepted_keys),
            accepted_primary_endpoint_count=len(accepted_primary_keys),
            accepted_secondary_endpoint_count=len(accepted_secondary_keys),
            accepted_secondary_mapping_count=len(allowed_pairs),
            allowed_edge_pair_count=len(allowed_pairs),
            proposal_endpoint_count=0,
            secondary_endpoint_report=secondary_endpoint_report,
            reason_code="no_external_semantic_proposal_or_secondary_surface",
        )
        _assert_safe_report(report)
        return report

    proposal = json.loads(Path(proposal_file).read_text(encoding="utf-8"))
    _assert_safe_report(proposal)
    endpoint_gate = _proposal_endpoint_gate(proposal)
    if endpoint_gate["status"] != "ok":
        report = _rejected_report(
            status="rejected_invalid_endpoint_shape",
            accepted_endpoint_count=len(accepted_keys),
            accepted_primary_endpoint_count=len(accepted_primary_keys),
            accepted_secondary_endpoint_count=len(accepted_secondary_keys),
            accepted_secondary_mapping_count=len(allowed_pairs),
            allowed_edge_pair_count=len(allowed_pairs),
            proposal_endpoint_count=0,
            error_code=str(endpoint_gate["errorCode"]),
            endpoint_keys=[],
            suggested_repair=str(endpoint_gate["suggestedRepair"]),
        )
        _assert_safe_report(report)
        return report
    endpoint_keys = set(endpoint_gate["endpointKeys"])
    outside = sorted(endpoint_keys - accepted_keys)
    if outside:
        report = _rejected_report(
            status="rejected_endpoint_not_accepted",
            accepted_endpoint_count=len(accepted_keys),
            accepted_primary_endpoint_count=len(accepted_primary_keys),
            accepted_secondary_endpoint_count=len(accepted_secondary_keys),
            accepted_secondary_mapping_count=len(allowed_pairs),
            allowed_edge_pair_count=len(allowed_pairs),
            proposal_endpoint_count=len(endpoint_keys),
            error_code="endpoint_not_in_accepted_mapping",
            endpoint_keys=outside,
            suggested_repair=(
                "Use only accepted endpoint mappings, or complete manual endpoint review first."
            ),
        )
        _assert_safe_report(report)
        return report
    if not accepted_secondary_keys:
        report = _deferred_report(
            accepted_endpoint_count=len(accepted_keys),
            accepted_primary_endpoint_count=len(accepted_primary_keys),
            accepted_secondary_endpoint_count=0,
            accepted_secondary_mapping_count=0,
            allowed_edge_pair_count=0,
            proposal_endpoint_count=len(endpoint_keys),
            secondary_endpoint_report=secondary_endpoint_report,
            reason_code="proposal_blocked_secondary_endpoint_gap",
        )
        _assert_safe_report(report)
        return report
    edge_type_gate = _proposal_edge_type_gate(proposal)
    if edge_type_gate["status"] != "ok":
        report = _rejected_report(
            status="rejected_unsupported_real_edge_type",
            accepted_endpoint_count=len(accepted_keys),
            accepted_primary_endpoint_count=len(accepted_primary_keys),
            accepted_secondary_endpoint_count=len(accepted_secondary_keys),
            accepted_secondary_mapping_count=len(allowed_pairs),
            allowed_edge_pair_count=len(allowed_pairs),
            proposal_endpoint_count=len(endpoint_keys),
            error_code=str(edge_type_gate["errorCode"]),
            endpoint_keys=[],
            suggested_repair=str(edge_type_gate["suggestedRepair"]),
        )
        _assert_safe_report(report)
        return report
    pair_gate = _proposal_allowed_pair_gate(proposal, allowed_pairs=allowed_pairs)
    if pair_gate["status"] != "ok":
        report = _rejected_report(
            status="rejected_invalid_endpoint_pair",
            accepted_endpoint_count=len(accepted_keys),
            accepted_primary_endpoint_count=len(accepted_primary_keys),
            accepted_secondary_endpoint_count=len(accepted_secondary_keys),
            accepted_secondary_mapping_count=len(allowed_pairs),
            allowed_edge_pair_count=len(allowed_pairs),
            proposal_endpoint_count=len(endpoint_keys),
            error_code=str(pair_gate["errorCode"]),
            endpoint_keys=list(pair_gate["endpointKeys"]),
            suggested_repair=str(pair_gate["suggestedRepair"]),
        )
        _assert_safe_report(report)
        return report

    graph_service = None
    if graph_snapshot_index is not None:
        graph_tools.clear_service_cache()
        graph_service = graph_tools.service_from_snapshot_index(str(graph_snapshot_index))
        graph_snapshot_id = _safe_text(graph_service.snapshot.snapshot_id)
        if primary_snapshot_id and graph_snapshot_id != primary_snapshot_id:
            report = _rejected_report(
                status="rejected_stale_graph_snapshot",
                accepted_endpoint_count=len(accepted_keys),
                accepted_primary_endpoint_count=len(accepted_primary_keys),
                accepted_secondary_endpoint_count=len(accepted_secondary_keys),
                accepted_secondary_mapping_count=len(allowed_pairs),
                allowed_edge_pair_count=len(allowed_pairs),
                proposal_endpoint_count=len(endpoint_keys),
                error_code="graph_snapshot_mismatch",
                endpoint_keys=[
                    f"mappingSnapshot:{primary_snapshot_id}",
                    f"currentSnapshot:{graph_snapshot_id}",
                ],
                suggested_repair=(
                    "Regenerate reviewed endpoint mapping artifacts against the current physical "
                    "graph snapshot before writing real semantic edges."
                ),
            )
            _assert_safe_report(report)
            return report
    service = research_memory.ResearchMemoryService(
        db_path=Path(db_path) if db_path is not None else None,
        graph_service=graph_service,
    )
    result = service.propose_semantic_edges(proposal)
    report = {
        "reportId": "phase4-external-semantic-proposal-acceptance-v1",
        "status": str(result.get("status") or "unknown"),
        "safeArtifactOnly": True,
        "acceptedEndpointCount": len(accepted_keys),
        "acceptedPrimaryEndpointCount": len(accepted_primary_keys),
        "acceptedSecondaryEndpointCount": len(accepted_secondary_keys),
        "acceptedSecondaryStableKeyCount": len(accepted_secondary_keys),
        "acceptedSecondaryMappingCount": len(allowed_pairs),
        "allowedEdgePairCount": len(allowed_pairs),
        "proposalEndpointCount": len(endpoint_keys),
        "semanticEdgeWrite": {
            "attempted": True,
            "resultStatus": result.get("status"),
            "edgeIds": result.get("edgeIds", []),
            "errorCode": result.get("errorCode"),
        },
        "serviceResult": _safe_service_summary(result),
    }
    _assert_safe_report(report)
    return report


def write_external_semantic_proposal_acceptance_report(
    *,
    mapping_report: str | Path = MAPPING_REPORT,
    secondary_endpoint_report: str | Path | None = None,
    proposal_file: str | Path | None,
    db_path: str | Path | None = None,
    graph_snapshot_index: str | Path | None = None,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_external_semantic_proposal_acceptance_report(
        mapping_report=mapping_report,
        secondary_endpoint_report=secondary_endpoint_report,
        proposal_file=proposal_file,
        db_path=db_path,
        graph_snapshot_index=graph_snapshot_index,
    )
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _accepted_primary_by_sample(mapping: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in mapping.get("reviewItems", []):
        if (
            isinstance(item, dict)
            and item.get("reviewStatus") == "accepted"
            and item.get("acceptedStableKey")
            and item.get("sampleId")
        ):
            sample_id = _safe_text(item.get("sampleId"))
            stable_key = _safe_text(item.get("acceptedStableKey"))
            if sample_id and stable_key:
                if stable_key not in _candidate_keys(item):
                    raise ValueError(
                        "accepted primary endpoint key is not present in resolver candidates"
                    )
                out[sample_id] = stable_key
    return out


def _secondary_endpoint_surface(
    path: str | Path | None,
    *,
    accepted_primary_by_sample: dict[str, str],
    primary_snapshot_id: str | None,
) -> dict[str, Any]:
    if path is None:
        default = REVIEWED_SECONDARY_ENDPOINT_REPORT
        if not default.exists():
            return {"acceptedSecondaryKeys": set(), "allowedPairs": set()}
        path = default
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    _assert_safe_report(report)
    if report.get("safeArtifactOnly") is not True:
        raise ValueError("reviewed secondary endpoint report must be safe-only")
    if report.get("reportId") != REVIEWED_SECONDARY_MAPPING_REPORT_ID:
        return {"acceptedSecondaryKeys": set(), "allowedPairs": set()}
    if report.get("inputReportId") != SECONDARY_REVIEW_REPORT_ID:
        raise ValueError("reviewed secondary endpoint report inputReportId is stale")
    secondary_snapshot_id = _safe_text(report.get("snapshotId"))
    if not secondary_snapshot_id:
        raise ValueError("reviewed secondary endpoint report missing snapshotId")
    if primary_snapshot_id and secondary_snapshot_id != primary_snapshot_id:
        raise ValueError(
            "reviewed secondary endpoint report snapshot does not match primary mapping"
        )
    keys: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for item in report.get("reviewItems", []):
        if not isinstance(item, dict):
            continue
        sample_id = _safe_text(item.get("sampleId"))
        if not sample_id or sample_id not in accepted_primary_by_sample:
            continue
        if _safe_text(item.get("primaryStableKey")) != accepted_primary_by_sample[sample_id]:
            continue
        if item.get("sampleEndpointStatus") != "accepted":
            continue
        if item.get("reviewStatus") != "accepted":
            continue
        if item.get("semanticEdgeActionAfterReview") != "ready_for_external_semantic_edge":
            continue
        stable_key = _safe_text(item.get("acceptedStableKey"))
        if not stable_key:
            continue
        candidate_keys = {
            _safe_text(candidate.get("stableKey"))
            for candidate in item.get("candidates", [])
            if isinstance(candidate, dict)
        }
        if stable_key not in candidate_keys:
            raise ValueError(
                "accepted secondary endpoint key is not present in resolver candidates"
            )
        primary_key = accepted_primary_by_sample[sample_id]
        keys.add(stable_key)
        pairs.add((primary_key, stable_key))
    return {"acceptedSecondaryKeys": keys, "allowedPairs": pairs}


def _rejected_report(
    *,
    status: str,
    accepted_endpoint_count: int,
    accepted_primary_endpoint_count: int,
    accepted_secondary_endpoint_count: int,
    accepted_secondary_mapping_count: int,
    allowed_edge_pair_count: int,
    proposal_endpoint_count: int,
    error_code: str,
    endpoint_keys: list[str],
    suggested_repair: str,
) -> dict[str, Any]:
    return {
        "reportId": "phase4-external-semantic-proposal-acceptance-v1",
        "status": status,
        "safeArtifactOnly": True,
        "acceptedEndpointCount": accepted_endpoint_count,
        "acceptedPrimaryEndpointCount": accepted_primary_endpoint_count,
        "acceptedSecondaryEndpointCount": accepted_secondary_endpoint_count,
        "acceptedSecondaryStableKeyCount": accepted_secondary_endpoint_count,
        "acceptedSecondaryMappingCount": accepted_secondary_mapping_count,
        "allowedEdgePairCount": allowed_edge_pair_count,
        "proposalEndpointCount": proposal_endpoint_count,
        "semanticEdgeWrite": {
            "attempted": False,
            "reason": error_code,
        },
        "rejection": {
            "errorCode": error_code,
            "endpointKeys": endpoint_keys,
            "suggestedRepair": suggested_repair,
        },
    }


def _deferred_report(
    *,
    accepted_endpoint_count: int,
    accepted_primary_endpoint_count: int,
    accepted_secondary_endpoint_count: int,
    accepted_secondary_mapping_count: int,
    allowed_edge_pair_count: int,
    proposal_endpoint_count: int,
    secondary_endpoint_report: str | Path | None,
    reason_code: str,
) -> dict[str, Any]:
    summary = _secondary_gap_summary(secondary_endpoint_report)
    return {
        "reportId": "phase4-external-semantic-proposal-acceptance-v1",
        "status": "deferred_secondary_endpoint_gap",
        "safeArtifactOnly": True,
        "acceptedEndpointCount": accepted_endpoint_count,
        "acceptedPrimaryEndpointCount": accepted_primary_endpoint_count,
        "acceptedSecondaryEndpointCount": accepted_secondary_endpoint_count,
        "acceptedSecondaryStableKeyCount": accepted_secondary_endpoint_count,
        "acceptedSecondaryMappingCount": accepted_secondary_mapping_count,
        "allowedEdgePairCount": allowed_edge_pair_count,
        "proposalEndpointCount": proposal_endpoint_count,
        "semanticEdgeWrite": {
            "attempted": False,
            "reason": "deferred_secondary_endpoint_gap",
        },
        "deferred": {
            "reason": reason_code,
            "detail": _deferred_detail(reason_code),
            "requiresManualEndpointMapping": summary["ambiguousCount"] > 0,
            "requiresStaticSourceRefresh": summary["missingCount"] > 0,
            "secondaryEndpointMetrics": summary,
            "nextAction": "Complete manual secondary endpoint mapping or Phase 2/3 source refresh before proposing real semantic edges.",
        },
    }


def _deferred_detail(reason_code: str) -> str:
    if reason_code == "proposal_blocked_secondary_endpoint_gap":
        return (
            "An external proposal was supplied, but no reviewed secondary endpoint mapping is "
            "available for safe real edge writing."
        )
    return (
        "No external semantic proposal was supplied and no reviewed secondary endpoint surface is "
        "available for safe real edge writing."
    )


def _secondary_gap_summary(path: str | Path | None) -> dict[str, int]:
    if path is None:
        default = REVIEWED_SECONDARY_ENDPOINT_REPORT
        if not default.exists():
            return {
                "candidateCount": 0,
                "resolvedCount": 0,
                "ambiguousCount": 0,
                "missingCount": 0,
                "notGraphEntityCount": 0,
            }
        path = default
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    _assert_safe_report(report)
    if report.get("reportId") == "phase4-reviewed-secondary-endpoint-mapping-v1":
        items = [item for item in report.get("reviewItems", []) if isinstance(item, dict)]
        return {
            "candidateCount": len(items),
            "resolvedCount": sum(1 for item in items if item.get("reviewStatus") == "accepted"),
            "ambiguousCount": sum(
                1 for item in items if item.get("reviewStatus") == "pending_manual_review"
            ),
            "missingCount": 0,
            "notGraphEntityCount": 0,
        }
    endpoints = [item for item in report.get("secondaryEndpoints", []) if isinstance(item, dict)]
    return {
        "candidateCount": len(endpoints),
        "resolvedCount": sum(1 for item in endpoints if item.get("resolverStatus") == "resolved"),
        "ambiguousCount": sum(1 for item in endpoints if item.get("resolverStatus") == "ambiguous"),
        "missingCount": sum(1 for item in endpoints if item.get("resolverStatus") == "missing"),
        "notGraphEntityCount": sum(
            1 for item in endpoints if item.get("resolverStatus") == "not_graph_entity"
        ),
    }


def _proposal_endpoint_gate(proposal: dict[str, Any]) -> dict[str, Any]:
    edges = proposal.get("semantic_edges")
    if not isinstance(edges, list):
        return {
            "status": "error",
            "errorCode": "invalid_semantic_edges_shape",
            "suggestedRepair": "semantic_edges must be a list of typed edge objects.",
        }
    if not edges:
        return {
            "status": "error",
            "errorCode": "empty_semantic_edges",
            "suggestedRepair": "semantic_edges must contain at least one reviewed advisory edge.",
        }
    keys: set[str] = set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            return {
                "status": "error",
                "errorCode": "invalid_semantic_edge_shape",
                "suggestedRepair": f"semantic_edges[{index}] must be an object.",
            }
        if "source_key" not in edge or "target_key" not in edge:
            return {
                "status": "error",
                "errorCode": "missing_semantic_edge_endpoint",
                "suggestedRepair": (
                    f"semantic_edges[{index}] must include source_key and target_key."
                ),
            }
        for field in ("source_key", "target_key"):
            value = edge.get(field)
            if not isinstance(value, str) or not value.strip():
                return {
                    "status": "error",
                    "errorCode": "missing_semantic_edge_endpoint",
                    "suggestedRepair": (
                        f"semantic_edges[{index}].{field} must be a non-empty stable key."
                    ),
                }
            safe = _safe_text(value)
            if safe:
                keys.add(safe)
    return {"status": "ok", "endpointKeys": keys}


def _proposal_edge_type_gate(proposal: dict[str, Any]) -> dict[str, Any]:
    for index, edge in enumerate(proposal.get("semantic_edges", [])):
        edge_type = _safe_text(edge.get("edge_type")) if isinstance(edge, dict) else None
        if edge_type not in PHASE4_REAL_EDGE_TYPES:
            return {
                "status": "error",
                "errorCode": "unsupported_real_edge_type",
                "suggestedRepair": (
                    "Phase 4 real closeout accepts only has_modelability_caveat edges. "
                    f"semantic_edges[{index}] used {edge_type or 'missing'}."
                ),
            }
    return {"status": "ok"}


def _proposal_allowed_pair_gate(
    proposal: dict[str, Any],
    *,
    allowed_pairs: set[tuple[str, str]],
) -> dict[str, Any]:
    bad_pairs: list[str] = []
    for edge in proposal.get("semantic_edges", []):
        if not isinstance(edge, dict):
            continue
        source_key = _safe_text(edge.get("source_key"))
        target_key = _safe_text(edge.get("target_key"))
        if not source_key or not target_key:
            continue
        if (source_key, target_key) not in allowed_pairs:
            bad_pairs.append(f"{source_key} -> {target_key}")
    if bad_pairs:
        return {
            "status": "error",
            "errorCode": "endpoint_pair_not_reviewed",
            "endpointKeys": bad_pairs,
            "suggestedRepair": (
                "Use only reviewed same-sample primary -> secondary endpoint pairs from the "
                "semantic proposal request."
            ),
        }
    return {"status": "ok"}


def _candidate_keys(item: dict[str, Any]) -> set[str | None]:
    return {
        _safe_text(candidate.get("stableKey"))
        for candidate in item.get("candidates", [])
        if isinstance(candidate, dict)
    }


def _validate_mapping_report(mapping: dict[str, Any]) -> None:
    _assert_safe_report(mapping)
    if mapping.get("safeArtifactOnly") is not True:
        raise ValueError("reviewed endpoint mapping report must be safe-only")
    if mapping.get("reportId") != PRIMARY_MAPPING_REPORT_ID:
        raise ValueError("reviewed endpoint mapping reportId is stale")
    if not _safe_text(mapping.get("snapshotId")):
        raise ValueError("reviewed endpoint mapping report missing snapshotId")
    if not isinstance(mapping.get("reviewItems"), list):
        raise ValueError("reviewed endpoint mapping report reviewItems must be a list")


def _safe_service_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "status": result.get("status"),
        "edgeIds": result.get("edgeIds", []),
        "errorCode": result.get("errorCode"),
        "caveats": result.get("caveats", []),
        "noRawMatureBuildMaterial": result.get("noRawMatureBuildMaterial"),
    }
    return _safe_json(summary)


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


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())[:240]
    _reject_copyable(text)
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


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4 External Semantic Proposal Acceptance",
        "",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Semantic edge write attempted: `{report['semanticEdgeWrite']['attempted']}`",
    ]
    edge_ids = report["semanticEdgeWrite"].get("edgeIds") or []
    if edge_ids:
        lines.append(f"- Edge ids: `{', '.join(edge_ids)}`")
    rejection = report.get("rejection")
    if isinstance(rejection, dict):
        lines.append(f"- Rejection: `{rejection.get('errorCode')}`")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping-report", default=str(MAPPING_REPORT))
    parser.add_argument("--secondary-endpoint-report", default=None)
    parser.add_argument("--reviewed-secondary-endpoint-report", default=None)
    parser.add_argument("--proposal-file", default=None)
    parser.add_argument("--db-path", default=None)
    parser.add_argument(
        "--graph-snapshot-index",
        default=str(paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"),
    )
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    report = write_external_semantic_proposal_acceptance_report(
        mapping_report=args.mapping_report,
        secondary_endpoint_report=args.reviewed_secondary_endpoint_report
        or args.secondary_endpoint_report,
        proposal_file=args.proposal_file,
        db_path=args.db_path,
        graph_snapshot_index=args.graph_snapshot_index,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
