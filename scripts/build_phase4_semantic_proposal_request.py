"""Build a safe request for external Phase 4 semantic edge proposals.

The request only includes endpoints that have passed the reviewed mapping gate.
Pending samples remain hidden from the proposal surface so an external
Researcher cannot accidentally use an unresolved endpoint.
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

from server.knowledge import copy_safety  # noqa: E402

INPUT_REPORT = REPO_ROOT / "phase4_reviewed_endpoint_mapping_report.json"
REVIEWED_SECONDARY_ENDPOINT_REPORT = (
    REPO_ROOT / "phase4_reviewed_secondary_endpoint_mapping_report.json"
)
JSON_OUTPUT = REPO_ROOT / "phase4_semantic_proposal_request.json"
MD_OUTPUT = REPO_ROOT / "phase4_semantic_proposal_request.md"
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
RESEARCHER_SOP = (
    "STEP 1: call query_research_memory before proposing any new fragment or edge. "
    "STEP 2: for each accepted endpoint below, call graph_tool_query with "
    "tool_name=resolve_graph_component and query=<acceptedStableKey> to obtain fresh resolver "
    "evidence. Resolve every secondary endpoint you use in a semantic edge as well; use only "
    "the reviewed same-sample primary -> secondary pairs listed in allowedEdgePairs. STEP 3: call "
    "propose_research_fragments and propose_semantic_edges only with "
    "typed schema_version=4 payloads. STEP 4: handle rejection envelopes and retry at most twice. "
    "DO NOT output final JSON as plain text; submit findings through the proposal tools. "
    "Do not use pending endpoints, ambiguous endpoints, missing endpoints, abstract mechanism tags, "
    "or safe metadata labels as stable keys."
)


def build_semantic_proposal_request(
    *,
    input_report: str | Path = INPUT_REPORT,
    secondary_endpoint_report: str | Path | None = None,
    reviewed_secondary_endpoint_report: str | Path | None = None,
) -> dict[str, Any]:
    mapping = json.loads(Path(input_report).read_text(encoding="utf-8"))
    _validate_mapping_report(mapping)
    snapshot_id = _safe_text(mapping.get("snapshotId"))
    accepted: list[dict[str, Any]] = []
    pending_count = 0
    for item in mapping.get("reviewItems", []):
        if not isinstance(item, dict):
            continue
        if item.get("reviewStatus") == "accepted":
            accepted.append(_accepted_endpoint(item))
        elif item.get("reviewStatus") in {"pending_manual_review", "unreviewed"}:
            pending_count += 1
    accepted_primary_by_sample = {
        item["sampleId"]: item["acceptedStableKey"] for item in accepted if item.get("sampleId")
    }
    secondary = _load_secondary_endpoints(
        reviewed_secondary_endpoint_report
        if reviewed_secondary_endpoint_report is not None
        else secondary_endpoint_report,
        accepted_primary_by_sample=accepted_primary_by_sample,
        primary_snapshot_id=snapshot_id,
    )
    allowed_edge_pairs = _allowed_edge_pairs(secondary)

    report = {
        "reportId": "phase4-semantic-proposal-request-v1",
        "inputReportId": str(mapping.get("reportId")),
        "status": (
            "ready_for_external_researcher_semantic_proposal"
            if accepted
            else "blocked_no_accepted_endpoints"
        ),
        "safeArtifactOnly": True,
        "snapshotId": snapshot_id,
        "acceptedEndpointCount": len(accepted),
        "pendingEndpointCount": pending_count,
        "acceptedEndpoints": accepted,
        "resolvedSecondaryEndpointCount": len(secondary),
        "resolvedSecondaryEndpoints": secondary,
        "allowedEdgePairCount": len(allowed_edge_pairs),
        "allowedEdgePairs": allowed_edge_pairs,
        "researcherSop": RESEARCHER_SOP,
        "allowedEdgeTypes": ["has_modelability_caveat"],
        "semanticEdgeWrite": {
            "attempted": False,
            "reason": "external_researcher_proposal_required",
        },
        "caveats": [
            "This request contains only accepted endpoint mappings and safe ids.",
            "Resolved secondary endpoints are included only when the primary sample endpoint was accepted.",
            "External Researcher output must still be submitted through proposal tools.",
            "Pending endpoint mappings are excluded from this request.",
            "Phase 4 real closeout accepts only advisory has_modelability_caveat edges.",
        ],
    }
    _assert_safe_report(report)
    return report


def write_semantic_proposal_request(
    *,
    input_report: str | Path = INPUT_REPORT,
    secondary_endpoint_report: str | Path | None = None,
    reviewed_secondary_endpoint_report: str | Path | None = None,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_semantic_proposal_request(
        input_report=input_report,
        secondary_endpoint_report=secondary_endpoint_report,
        reviewed_secondary_endpoint_report=reviewed_secondary_endpoint_report,
    )
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _accepted_endpoint(item: dict[str, Any]) -> dict[str, Any]:
    stable_key = _safe_text(item.get("acceptedStableKey"))
    if not stable_key:
        raise ValueError("accepted endpoint missing stable key")
    if stable_key not in _candidate_keys(item):
        raise ValueError("accepted primary endpoint key is not present in resolver candidates")
    return {
        "sampleId": _safe_text(item.get("sampleId")),
        "candidateName": _safe_text(item.get("candidateName")),
        "acceptedStableKey": stable_key,
        "resolverStatusAtReview": _safe_text(item.get("resolverStatus")),
        "nextAction": "external_researcher_must_resolve_stable_key_before_edge",
    }


def _load_secondary_endpoints(
    path: str | Path | None,
    *,
    accepted_primary_by_sample: dict[str, str],
    primary_snapshot_id: str | None,
) -> list[dict[str, Any]]:
    if path is None:
        default = REVIEWED_SECONDARY_ENDPOINT_REPORT
        if not default.exists():
            return []
        path = default
    reviewed_secondary = json.loads(Path(path).read_text(encoding="utf-8"))
    _assert_safe_report(reviewed_secondary)
    if reviewed_secondary.get("safeArtifactOnly") is not True:
        raise ValueError("reviewed secondary endpoint report must be safe-only")
    if reviewed_secondary.get("reportId") != REVIEWED_SECONDARY_MAPPING_REPORT_ID:
        return []
    if reviewed_secondary.get("inputReportId") != SECONDARY_REVIEW_REPORT_ID:
        raise ValueError("reviewed secondary endpoint report inputReportId is stale")
    secondary_snapshot_id = _safe_text(reviewed_secondary.get("snapshotId"))
    if not secondary_snapshot_id:
        raise ValueError("reviewed secondary endpoint report missing snapshotId")
    if primary_snapshot_id and secondary_snapshot_id != primary_snapshot_id:
        raise ValueError(
            "reviewed secondary endpoint report snapshot does not match primary mapping"
        )
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in reviewed_secondary.get("reviewItems", []):
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
        matched_candidate = _matching_candidate(item, stable_key)
        dedupe_key = (str(item.get("sampleId")), stable_key)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(
            {
                "sampleId": sample_id,
                "primaryStableKey": accepted_primary_by_sample[sample_id],
                "candidateName": _safe_text(item.get("candidateName")),
                "stableKey": stable_key,
                "nodeType": _safe_text(item.get("nodeType") or matched_candidate.get("nodeType")),
                "resolverStatus": _safe_text(item.get("resolverStatus")),
                "semanticUse": "secondary_endpoint_allowed_for_edge",
            }
        )
    return out


def _matching_candidate(item: dict[str, Any], stable_key: str) -> dict[str, Any]:
    for candidate in item.get("candidates", []):
        if isinstance(candidate, dict) and _safe_text(candidate.get("stableKey")) == stable_key:
            return candidate
    return {}


def _candidate_keys(item: dict[str, Any]) -> set[str | None]:
    return {
        _safe_text(candidate.get("stableKey"))
        for candidate in item.get("candidates", [])
        if isinstance(candidate, dict)
    }


def _allowed_edge_pairs(secondary: list[dict[str, Any]]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in secondary:
        sample_id = str(item.get("sampleId") or "")
        source_key = str(item.get("primaryStableKey") or "")
        target_key = str(item.get("stableKey") or "")
        key = (sample_id, source_key, target_key)
        if not all(key) or key in seen:
            continue
        seen.add(key)
        pairs.append(
            {
                "sampleId": sample_id,
                "sourceKey": source_key,
                "targetKey": target_key,
                "edgeType": "has_modelability_caveat",
            }
        )
    return pairs


def _validate_mapping_report(mapping: dict[str, Any]) -> None:
    if mapping.get("safeArtifactOnly") is not True:
        raise ValueError("reviewed endpoint mapping report must be safe-only")
    if mapping.get("reportId") != PRIMARY_MAPPING_REPORT_ID:
        raise ValueError("reviewed endpoint mapping reportId is stale")
    if not _safe_text(mapping.get("snapshotId")):
        raise ValueError("reviewed endpoint mapping report missing snapshotId")
    if not isinstance(mapping.get("reviewItems"), list):
        raise ValueError("reviewed endpoint mapping report reviewItems must be a list")
    _assert_safe_report(mapping)


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())[:180]
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
        "# Phase 4 Semantic Proposal Request",
        "",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Accepted endpoints: `{report['acceptedEndpointCount']}`",
        f"- Resolved secondary endpoints: `{report['resolvedSecondaryEndpointCount']}`",
        f"- Pending endpoints excluded: `{report['pendingEndpointCount']}`",
        f"- Semantic edge write attempted: `{report['semanticEdgeWrite']['attempted']}`",
        "",
        "## Accepted Endpoints",
        "",
    ]
    for item in report["acceptedEndpoints"]:
        lines.append(
            f"- `{item['sampleId']}` / `{item['candidateName']}` -> `{item['acceptedStableKey']}`"
        )
    if report.get("resolvedSecondaryEndpoints"):
        lines.extend(["", "## Resolved Secondary Endpoints", ""])
        for item in report["resolvedSecondaryEndpoints"]:
            lines.append(
                f"- `{item['sampleId']}` / `{item['candidateName']}` -> `{item['stableKey']}`"
            )
    lines.extend(["", "## SOP", "", report["researcherSop"], "", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-report", default=str(INPUT_REPORT))
    parser.add_argument("--secondary-endpoint-report", default=None)
    parser.add_argument("--reviewed-secondary-endpoint-report", default=None)
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    report = write_semantic_proposal_request(
        input_report=args.input_report,
        secondary_endpoint_report=args.secondary_endpoint_report,
        reviewed_secondary_endpoint_report=args.reviewed_secondary_endpoint_report,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["acceptedEndpointCount"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
