"""Apply explicit human decisions to Phase 4 secondary endpoint mappings."""

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

INPUT_REPORT = REPO_ROOT / "phase4_secondary_endpoint_review_report.json"
JSON_OUTPUT = REPO_ROOT / "phase4_reviewed_secondary_endpoint_mapping_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_reviewed_secondary_endpoint_mapping_report.md"
DEFAULT_ACCEPTED_MAPPINGS = {
    "phase4_user_pob_001|Barrage": "skill:BarragePlayer",
    "phase4_user_pob_001|Whirling Slash": "skill:WhirlingSlashPlayer",
    "phase4_user_pob_002|Barrage": "skill:BarragePlayer",
    "phase4_user_pob_002|Pounce": "skill:WolfPouncePlayer",
    "phase4_user_pob_003|Escape Shot": "skill:EscapeShotPlayer",
    "phase4_user_pob_003|Mirage Archer": "skill:MetaMirageArcherPlayer",
    "phase4_user_pob_004|Herald of Thunder": "skill:HeraldOfThunderPlayer",
    "phase4_user_pob_004|Wild Protector": "skill:WildProtectorPlayer",
}
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


def build_reviewed_secondary_endpoint_mapping_report(
    *,
    input_report: str | Path = INPUT_REPORT,
    accepted_mappings: dict[str, str] | None = None,
) -> dict[str, Any]:
    accepted_mappings = dict(
        DEFAULT_ACCEPTED_MAPPINGS if accepted_mappings is None else accepted_mappings
    )
    review = json.loads(Path(input_report).read_text(encoding="utf-8"))
    _validate_review_report(review)
    reviewed_items = [
        _apply_decision(item, accepted_mappings=accepted_mappings)
        for item in review.get("reviewItems", [])
    ]
    blocked_primary_items = [
        _blocked_primary_summary(item) for item in review.get("blockedPrimaryItems", [])
    ]
    accepted_count = sum(1 for item in reviewed_items if item["reviewStatus"] == "accepted")
    pending_count = sum(
        1 for item in reviewed_items if item["reviewStatus"] == "pending_manual_review"
    )
    status = (
        "secondary_endpoint_mapping_accepted"
        if accepted_count == len(reviewed_items) and pending_count == 0
        else "partial_secondary_endpoint_mapping_accepted"
    )
    report = {
        "reportId": "phase4-reviewed-secondary-endpoint-mapping-v1",
        "inputReportId": _safe_text(review.get("reportId")),
        "status": status,
        "safeArtifactOnly": True,
        "snapshotId": _safe_text(review.get("snapshotId")),
        "acceptedCount": accepted_count,
        "pendingCount": pending_count,
        "blockedPrimaryCount": len(blocked_primary_items),
        "reviewItemCount": len(reviewed_items),
        "reviewItems": reviewed_items,
        "blockedPrimaryItems": blocked_primary_items,
        "semanticEdgeWrite": {
            "attempted": False,
            "reason": "secondary_endpoint_mapping_gate_only",
        },
        "caveats": [
            "This artifact records explicit secondary endpoint mapping decisions only.",
            "Pending secondary endpoints remain blocked until a later manual review accepts an endpoint.",
            "Semantic edge writes still require external Researcher clean proposals and resolver evidence.",
        ],
    }
    _assert_safe_report(report)
    return report


def write_reviewed_secondary_endpoint_mapping_report(
    *,
    input_report: str | Path = INPUT_REPORT,
    accepted_mappings: dict[str, str] | None = None,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_reviewed_secondary_endpoint_mapping_report(
        input_report=input_report,
        accepted_mappings=accepted_mappings,
    )
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def parse_accepted_mapping_args(values: list[str] | None) -> dict[str, str]:
    accepted: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError("--accept must use sampleId|candidateName=stableKey")
        key, stable_key = value.split("=", 1)
        key = _safe_text(key)
        stable_key = _safe_text(stable_key)
        if not key or "|" not in key or not stable_key:
            raise ValueError("--accept must use sampleId|candidateName=stableKey")
        accepted[key] = stable_key
    return accepted


def _apply_decision(
    item: dict[str, Any],
    *,
    accepted_mappings: dict[str, str],
) -> dict[str, Any]:
    key = _decision_key(item)
    candidates = item.get("candidates") if isinstance(item.get("candidates"), list) else []
    candidate_keys = {
        str(candidate.get("stableKey"))
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("stableKey")
    }
    base = {
        "sampleId": _safe_text(item.get("sampleId")),
        "sampleEndpointStatus": _safe_text(item.get("sampleEndpointStatus")),
        "primaryStableKey": _safe_text(item.get("primaryStableKey")),
        "candidateName": _safe_text(item.get("candidateName")),
        "candidateKind": _safe_text(item.get("candidateKind")),
        "resolverStatus": _safe_text(item.get("resolverStatus")),
        "recommendedStableKey": _safe_text(item.get("recommendedStableKey")),
        "candidateCount": len(candidates),
        "candidates": [
            _candidate_summary(candidate) for candidate in candidates if isinstance(candidate, dict)
        ],
    }
    if key in accepted_mappings:
        accepted = _safe_text(accepted_mappings[key])
        if accepted not in candidate_keys:
            raise ValueError(f"accepted stable key is not a reviewed candidate: {key}")
        return {
            **base,
            "reviewStatus": "accepted",
            "acceptedStableKey": accepted,
            "requiresUserDecision": False,
            "semanticEdgeActionAfterReview": "ready_for_external_semantic_edge",
        }
    return {
        **base,
        "reviewStatus": "pending_manual_review",
        "acceptedStableKey": None,
        "requiresUserDecision": True,
        "semanticEdgeActionAfterReview": "blocked_until_secondary_review_acceptance",
    }


def _decision_key(item: dict[str, Any]) -> str:
    return f"{_safe_text(item.get('sampleId'))}|{_safe_text(item.get('candidateName'))}"


def _blocked_primary_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "sampleId": _safe_text(item.get("sampleId")),
        "primaryStableKey": _safe_text(item.get("primaryStableKey")),
        "candidateName": _safe_text(item.get("candidateName")),
        "resolverStatus": _safe_text(item.get("resolverStatus")),
        "semanticEdgeActionAfterReview": "blocked_primary_endpoint_pending",
    }


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "stableKey": _safe_text(candidate.get("stableKey")),
        "nodeType": _safe_text(candidate.get("nodeType")),
        "sourceRefs": _safe_list(candidate.get("sourceRefs")),
    }


def _validate_review_report(report: dict[str, Any]) -> None:
    if report.get("safeArtifactOnly") is not True:
        raise ValueError("secondary endpoint review report must be safe-only")
    if not isinstance(report.get("reviewItems"), list):
        raise ValueError("secondary endpoint review report reviewItems must be a list")
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
        "# Phase 4 Reviewed Secondary Endpoint Mapping",
        "",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Accepted / pending: `{report['acceptedCount']}` / `{report['pendingCount']}`",
        f"- Blocked primary items: `{report['blockedPrimaryCount']}`",
        f"- Semantic edge write attempted: `{report['semanticEdgeWrite']['attempted']}`",
        "",
        "## Items",
        "",
    ]
    for item in report["reviewItems"]:
        lines.append(
            f"- `{item['sampleId']}` / `{item['candidateName']}`: `{item['reviewStatus']}`"
        )
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
    parser.add_argument(
        "--accept",
        action="append",
        default=[],
        help="Repeatable mapping in sampleId|candidateName=stableKey format.",
    )
    args = parser.parse_args(argv)
    cli_mappings = parse_accepted_mapping_args(args.accept)
    accepted_mappings = {**DEFAULT_ACCEPTED_MAPPINGS, **cli_mappings} if args.accept else None
    report = write_reviewed_secondary_endpoint_mapping_report(
        input_report=args.input_report,
        accepted_mappings=accepted_mappings,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["reviewItemCount"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
