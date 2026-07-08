"""Build a safe manual review template for Phase 4 secondary endpoints."""

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

INPUT_REPORT = REPO_ROOT / "phase4_secondary_endpoint_resolution_report.json"
JSON_OUTPUT = REPO_ROOT / "phase4_secondary_endpoint_review_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_secondary_endpoint_review_report.md"
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


def build_secondary_endpoint_review_report(
    *,
    input_report: str | Path = INPUT_REPORT,
) -> dict[str, Any]:
    secondary = json.loads(Path(input_report).read_text(encoding="utf-8"))
    _validate_secondary_report(secondary)
    review_items: list[dict[str, Any]] = []
    blocked_primary_items: list[dict[str, Any]] = []
    for item in secondary.get("secondaryEndpoints", []):
        if not isinstance(item, dict):
            continue
        if item.get("candidateKind") != "secondary_component":
            continue
        if item.get("sampleEndpointStatus") != "accepted":
            blocked_primary_items.append(_blocked_primary_item(item))
            continue
        if item.get("resolverStatus") in {"ambiguous", "missing", "resolved"}:
            review_items.append(_review_item(item))

    needs_review_count = sum(
        1 for item in review_items if item["reviewStatus"] == "needs_manual_review"
    )
    already_resolved_count = sum(
        1 for item in review_items if item["reviewStatus"] == "already_resolved"
    )
    report = {
        "reportId": "phase4-secondary-endpoint-review-v1",
        "inputReportId": _safe_text(secondary.get("reportId")),
        "status": (
            "needs_manual_secondary_endpoint_review"
            if needs_review_count
            else "ready_for_secondary_endpoint_decisions"
        ),
        "safeArtifactOnly": True,
        "snapshotId": _safe_text(secondary.get("snapshotId")),
        "reviewItemCount": len(review_items),
        "needsManualReviewCount": needs_review_count,
        "alreadyResolvedCount": already_resolved_count,
        "blockedPrimaryCount": len(blocked_primary_items),
        "autoAcceptedCount": 0,
        "reviewItems": review_items,
        "blockedPrimaryItems": blocked_primary_items,
        "policy": {
            "autoAcceptMappings": False,
            "requiresUserDecisionForAmbiguous": True,
            "noSemanticEdgeWrite": True,
        },
        "caveats": [
            "This report is a secondary endpoint mapping aid only.",
            "Recommended stable keys are not accepted mappings.",
            "Blocked primary samples cannot contribute secondary semantic edge endpoints.",
        ],
    }
    _assert_safe_report(report)
    return report


def write_secondary_endpoint_review_report(
    *,
    input_report: str | Path = INPUT_REPORT,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_secondary_endpoint_review_report(input_report=input_report)
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _review_item(item: dict[str, Any]) -> dict[str, Any]:
    resolver_status = _safe_text(item.get("resolverStatus"))
    candidates = item.get("candidates") if isinstance(item.get("candidates"), list) else []
    if resolver_status == "resolved":
        stable_key = _safe_text(item.get("stableKey"))
        return {
            **_base_item(item),
            "resolverStatus": "resolved",
            "reviewStatus": "already_resolved",
            "recommendedStableKey": stable_key,
            "recommendationBasis": "resolver_status_resolved",
            "acceptedStableKey": stable_key,
            "candidateCount": len(candidates),
            "candidates": [_candidate_summary(candidate) for candidate in candidates],
            "requiresUserDecision": False,
            "semanticEdgeActionAfterReview": "ready_for_external_semantic_edge",
        }
    recommended = _recommended_candidate(candidates)
    return {
        **_base_item(item),
        "resolverStatus": resolver_status,
        "reviewStatus": "needs_manual_review",
        "recommendedStableKey": recommended.get("stableKey"),
        "recommendationBasis": _recommendation_basis(recommended),
        "acceptedStableKey": None,
        "candidateCount": len(candidates),
        "candidates": [_candidate_summary(candidate) for candidate in candidates],
        "endpointAssessment": _safe_json(item.get("endpointAssessment"))
        if isinstance(item.get("endpointAssessment"), dict)
        else None,
        "requiresUserDecision": True,
        "semanticEdgeActionAfterReview": "blocked_until_secondary_review_acceptance",
    }


def _blocked_primary_item(item: dict[str, Any]) -> dict[str, Any]:
    candidates = item.get("candidates") if isinstance(item.get("candidates"), list) else []
    return {
        **_base_item(item),
        "resolverStatus": _safe_text(item.get("resolverStatus")),
        "reviewStatus": "blocked_primary_endpoint_pending",
        "recommendedStableKey": None,
        "acceptedStableKey": None,
        "candidateCount": len(candidates),
        "candidates": [_candidate_summary(candidate) for candidate in candidates],
        "requiresUserDecision": False,
        "semanticEdgeActionAfterReview": "blocked_primary_endpoint_pending",
    }


def _base_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "sampleId": _safe_text(item.get("sampleId")),
        "sampleEndpointStatus": _safe_text(item.get("sampleEndpointStatus")),
        "primaryStableKey": _safe_text(item.get("primaryStableKey")),
        "candidateName": _safe_text(item.get("candidateName")),
        "candidateKind": _safe_text(item.get("candidateKind")),
    }


def _recommended_candidate(candidates: list[Any]) -> dict[str, Any]:
    summaries = [
        _candidate_summary(candidate) for candidate in candidates if isinstance(candidate, dict)
    ]
    active = [candidate for candidate in summaries if candidate["nodeType"] == "active_skill"]
    if len(active) == 1:
        return active[0]
    if len(active) > 1:
        return {"stableKey": None, "nodeType": "multiple_active_skill_candidates"}
    if summaries:
        return {"stableKey": None, "nodeType": "no_active_skill_candidate"}
    return {"stableKey": None, "nodeType": None}


def _recommendation_basis(candidate: dict[str, Any]) -> str:
    if candidate.get("nodeType") == "active_skill":
        return "single_active_skill_candidate"
    if candidate.get("nodeType") == "multiple_active_skill_candidates":
        return "multiple_active_skill_candidates_no_recommendation"
    if candidate.get("nodeType") == "no_active_skill_candidate":
        return "no_active_skill_candidate_no_recommendation"
    return "no_candidate_available"


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "stableKey": _safe_text(candidate.get("stableKey")),
        "nodeType": _safe_text(candidate.get("nodeType")),
        "sourceRefs": _safe_list(candidate.get("sourceRefs")),
    }


def _validate_secondary_report(report: dict[str, Any]) -> None:
    if report.get("safeArtifactOnly") is not True:
        raise ValueError("secondary endpoint report must be safe-only")
    if not isinstance(report.get("secondaryEndpoints"), list):
        raise ValueError("secondary endpoint report secondaryEndpoints must be a list")
    _assert_safe_report(report)


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())[:180]
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
        "# Phase 4 Secondary Endpoint Review",
        "",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Review items: `{report['reviewItemCount']}`",
        f"- Needs manual review: `{report['needsManualReviewCount']}`",
        f"- Blocked primary items: `{report['blockedPrimaryCount']}`",
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
    lines.extend(["", "## Blocked Primary Items", ""])
    for item in report["blockedPrimaryItems"]:
        lines.append(
            f"- `{item['sampleId']}` / `{item['candidateName']}`: `{item['semanticEdgeActionAfterReview']}`"
        )
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
    report = write_secondary_endpoint_review_report(
        input_report=args.input_report,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["reviewItemCount"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
