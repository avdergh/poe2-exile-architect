"""Build a safe manual endpoint review template from Phase 4 graph coverage.

This script does not accept mappings automatically. Ambiguous resolver results
can include a recommended stable key, but the accepted stable key remains null
until a human or later explicit review tool records that decision.
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

INPUT_REPORT = REPO_ROOT / "phase4_real_sample_graph_coverage_report.json"
JSON_OUTPUT = REPO_ROOT / "phase4_endpoint_review_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_endpoint_review_report.md"
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


def build_endpoint_review_report(
    *,
    input_report: str | Path = INPUT_REPORT,
) -> dict[str, Any]:
    coverage = json.loads(Path(input_report).read_text(encoding="utf-8"))
    _validate_coverage_report(coverage)
    review_items = [_review_item(probe) for probe in coverage.get("probes", [])]
    needs_review_count = sum(
        1 for item in review_items if item["reviewStatus"] == "needs_manual_review"
    )
    report = {
        "reportId": "phase4-endpoint-review-v1",
        "inputReportId": str(coverage.get("reportId")),
        "status": "needs_manual_endpoint_review"
        if needs_review_count
        else "ready_for_researcher_semantic_review",
        "safeArtifactOnly": True,
        "snapshotId": coverage.get("snapshotId"),
        "reviewItemCount": len(review_items),
        "needsManualReviewCount": needs_review_count,
        "autoAcceptedCount": 0,
        "reviewItems": review_items,
        "policy": {
            "autoAcceptMappings": False,
            "requiresUserDecisionForAmbiguous": True,
            "noSemanticEdgeWrite": True,
        },
        "caveats": [
            "This report is a manual endpoint mapping aid only.",
            "Recommended stable keys are not accepted mappings.",
            "Semantic edge proposals remain blocked until external Researcher output and accepted endpoint mapping are available.",
        ],
    }
    _assert_safe_report(report)
    return report


def write_endpoint_review_report(
    *,
    input_report: str | Path = INPUT_REPORT,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_endpoint_review_report(input_report=input_report)
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _review_item(probe: dict[str, Any]) -> dict[str, Any]:
    resolver_status = str(probe.get("resolverStatus") or "missing")
    if resolver_status == "resolved":
        stable_key = str(probe.get("stableKey") or "")
        return {
            "sampleId": _safe_text(probe.get("sampleId")),
            "candidateName": _safe_text(probe.get("candidateName")),
            "queryProvenance": "safe_metadata_unresolved_label",
            "resolverStatus": "resolved",
            "reviewStatus": "already_resolved",
            "recommendedStableKey": stable_key,
            "recommendationBasis": "resolver_status_resolved",
            "acceptedStableKey": stable_key,
            "nodeType": _safe_text(probe.get("nodeType")),
            "sourceRefs": _safe_list(probe.get("sourceRefs")),
            "evidencePathNodes": _safe_list(probe.get("evidencePathNodes")),
            "requiresUserDecision": False,
            "semanticEdgeActionAfterReview": "ready_for_researcher_semantic_review",
        }
    candidates = probe.get("candidates") if isinstance(probe.get("candidates"), list) else []
    recommended = _recommended_candidate(candidates)
    assessment = (
        _safe_json(probe.get("endpointAssessment"))
        if isinstance(probe.get("endpointAssessment"), dict)
        else None
    )
    return {
        "sampleId": _safe_text(probe.get("sampleId")),
        "candidateName": _safe_text(probe.get("candidateName")),
        "queryProvenance": "safe_metadata_unresolved_label",
        "resolverStatus": resolver_status,
        "reviewStatus": "needs_manual_review",
        "recommendedStableKey": recommended.get("stableKey"),
        "recommendationBasis": _recommendation_basis(recommended),
        "acceptedStableKey": None,
        "candidateCount": len(candidates),
        "candidates": [_candidate_summary(candidate) for candidate in candidates],
        "endpointAssessment": assessment,
        "requiresUserDecision": True,
        "semanticEdgeActionAfterReview": "blocked_until_review_acceptance",
    }


def _recommended_candidate(candidates: list[Any]) -> dict[str, Any]:
    summaries = [
        _candidate_summary(candidate) for candidate in candidates if isinstance(candidate, dict)
    ]
    active = [candidate for candidate in summaries if candidate["nodeType"] == "active_skill"]
    if len(active) == 1:
        return active[0]
    if len(active) > 1:
        return {
            "stableKey": None,
            "nodeType": "multiple_active_skill_candidates",
            "sourceRefs": [],
        }
    if summaries:
        return {
            "stableKey": None,
            "nodeType": "no_active_skill_candidate",
            "sourceRefs": [],
        }
    return {"stableKey": None, "nodeType": None, "sourceRefs": []}


def _recommendation_basis(candidate: dict[str, Any]) -> str:
    if candidate.get("nodeType") == "active_skill":
        return "active_skill_candidate_preferred_for_mainSkill"
    if candidate.get("nodeType") == "multiple_active_skill_candidates":
        return "multiple_active_skill_candidates_no_recommendation"
    if candidate.get("nodeType") == "no_active_skill_candidate":
        return "no_active_skill_candidate_no_recommendation"
    if candidate.get("stableKey"):
        return "first_candidate_only_not_accepted"
    return "no_candidate_available"


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "stableKey": _safe_text(candidate.get("stableKey")),
        "nodeType": _safe_text(candidate.get("nodeType")),
        "sourceRefs": _safe_list(candidate.get("sourceRefs")),
    }


def _validate_coverage_report(coverage: dict[str, Any]) -> None:
    if coverage.get("safeArtifactOnly") is not True:
        raise ValueError("coverage report must be safe-only")
    if not isinstance(coverage.get("probes"), list):
        raise ValueError("coverage report probes must be a list")
    _assert_safe_report(coverage)


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())[:160]
    _reject_copyable(text)
    return text


def _safe_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    safe: list[str] = []
    for item in value:
        text = _safe_text(item)
        if text:
            safe.append(text)
    return safe


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
        "# Phase 4 Endpoint Review",
        "",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Snapshot: `{report.get('snapshotId')}`",
        f"- Review items: `{report['reviewItemCount']}`",
        f"- Needs manual review: `{report['needsManualReviewCount']}`",
        f"- Auto accepted: `{report['autoAcceptedCount']}`",
        "",
        "## Items",
        "",
    ]
    for item in report["reviewItems"]:
        lines.append(
            f"- `{item['sampleId']}` / `{item['candidateName']}`: `{item['resolverStatus']}` -> `{item['reviewStatus']}`"
        )
        lines.append(f"  - recommended: `{item.get('recommendedStableKey')}`")
        lines.append(f"  - accepted: `{item.get('acceptedStableKey')}`")
        lines.append(f"  - next: `{item['semanticEdgeActionAfterReview']}`")
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-report", default=str(INPUT_REPORT))
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    report = write_endpoint_review_report(
        input_report=args.input_report,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["reviewItemCount"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
