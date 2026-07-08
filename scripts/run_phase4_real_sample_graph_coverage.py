"""Probe real Phase 4 sample endpoint coverage through the Phase 3 graph resolver.

This script does not run an LLM, does not read transient packet files, and does
not synthesize semantic edges from safe metadata. It only classifies whether the
current local physical graph snapshot can resolve safe main-skill labels from a
safe Phase 4 packet report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server import paths  # noqa: E402
from server.knowledge import copy_safety, graph_tools, mature_learning, physical_graph  # noqa: E402

JSON_OUTPUT = REPO_ROOT / "phase4_real_sample_graph_coverage_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_real_sample_graph_coverage_report.md"
PACKET_REPORT = REPO_ROOT / "phase4_researcher_e2e_report.json"
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
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def build_real_sample_graph_coverage_report(
    *,
    input_report: str | Path = PACKET_REPORT,
    graph_snapshot_index: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    source_report = json.loads(Path(input_report).read_text(encoding="utf-8"))
    _validate_input_report(source_report)
    mature_learning.initialize_store(Path(db_path) if db_path is not None else _ephemeral_db_path())

    index_path = (
        Path(graph_snapshot_index)
        if graph_snapshot_index is not None
        else paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"
    )
    graph_status, graph_caveats, service = _graph_service(index_path)
    probes: list[dict[str, Any]] = []
    for sample in source_report.get("samples", []):
        if not isinstance(sample, dict) or sample.get("status") != "packet_ready":
            continue
        probes.append(_probe_sample(sample, service=service, graph_status=graph_status))

    status = (
        "coverage_probe_completed" if graph_status == "available" else "graph_snapshot_unavailable"
    )
    metrics = {
        "sampleCount": len(probes),
        "resolvedCount": sum(1 for probe in probes if probe["resolverStatus"] == "resolved"),
        "ambiguousCount": sum(1 for probe in probes if probe["resolverStatus"] == "ambiguous"),
        "missingCount": sum(1 for probe in probes if probe["resolverStatus"] == "missing"),
        "graphUnavailableCount": sum(
            1 for probe in probes if probe["resolverStatus"] == "graph_unavailable"
        ),
        "semanticEdgeWritesAttempted": 0,
    }
    report = {
        "reportId": "phase4-real-sample-graph-coverage-v1",
        "inputReportId": _safe_token_field("reportId", source_report.get("reportId")),
        "status": status,
        "safeArtifactOnly": True,
        "graphSnapshotIndex": _safe_relative(index_path),
        "snapshotId": service.snapshot.snapshot_id if service is not None else None,
        "probes": probes,
        "semanticEdgeWrite": {
            "attempted": False,
            "reason": "external_researcher_proposal_required",
            "policy": (
                "Safe metadata labels are resolver coverage probes only. Real semantic edge "
                "writes require an external Researcher clean proposal with resolver evidence."
            ),
        },
        "metrics": metrics,
        "caveats": [
            "This coverage run used only safe Phase 4 packet report metadata.",
            "Missing graph coverage is not mature-build hallucination evidence.",
            "No semantic edge was created or proposed from safeMetadata labels.",
            *graph_caveats,
        ],
    }
    _assert_safe_report(report)
    return report


def write_real_sample_graph_coverage_report(
    *,
    input_report: str | Path = PACKET_REPORT,
    graph_snapshot_index: str | Path | None = None,
    db_path: str | Path | None = None,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_real_sample_graph_coverage_report(
        input_report=input_report,
        graph_snapshot_index=graph_snapshot_index,
        db_path=db_path,
    )
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _probe_sample(
    sample: dict[str, Any],
    *,
    service: graph_tools.GraphQueryService | None,
    graph_status: str,
) -> dict[str, Any]:
    metadata = sample.get("safeMetadata") if isinstance(sample.get("safeMetadata"), dict) else {}
    sample_id = _safe_token(sample.get("sampleId") or metadata.get("case_id") or "unknown")
    candidate_name = _metadata_value(metadata, "mainSkill", "unknown")
    base = {
        "sampleId": sample_id,
        "safeSourceRef": _safe_ref("source-hash", sample.get("sourceHash")),
        "packetSafeHashRef": _safe_ref("packet-safe-hash", sample.get("packetSafeHash")),
        "candidateName": candidate_name,
        "queryName": candidate_name,
        "queryProvenance": "safe_metadata_unresolved_label",
        "class": _metadata_value(metadata, "class", ""),
        "ascendancy": _metadata_value(metadata, "ascendancy", ""),
        "gamePatch": _metadata_value(metadata, "gamePatch", "unknown"),
        "passiveTreeVersion": _metadata_value(metadata, "passiveTreeVersion", "unknown"),
        "pobModelability": _metadata_value(metadata, "pobModelability", "unknown"),
    }
    if service is None or graph_status != "available":
        assessment = _endpoint_assessment(
            "graph_snapshot_unavailable",
            "No local Phase 3 graph snapshot was available for resolver checks.",
        )
        return {
            **base,
            "resolverStatus": "graph_unavailable",
            "snapshotId": None,
            "candidateCount": 0,
            "candidates": [],
            "sourceRefs": [],
            "evidencePathNodes": [],
            "endpointAssessment": assessment,
            "requiresStaticSourceReview": True,
            "semanticEdgeAction": "deferred_source_coverage_gap",
            "noRawMatureBuildMaterial": True,
        }

    result = service.run_tool("resolve_graph_component", {"query": candidate_name})
    resolver_status = str(result.get("status") or "missing")
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    candidates = facts.get("candidates") if isinstance(facts.get("candidates"), list) else []
    evidence_path = (
        result.get("evidencePath") if isinstance(result.get("evidencePath"), dict) else {}
    )
    resolved = (
        result.get("resolvedSubject") if isinstance(result.get("resolvedSubject"), dict) else {}
    )
    assessment = result.get("endpointAssessment")

    if resolver_status == "resolved":
        action = "ready_for_researcher_semantic_review"
        requires_review = False
    elif resolver_status == "ambiguous":
        action = "requires_manual_endpoint_mapping"
        requires_review = True
    else:
        action = "deferred_source_coverage_gap"
        requires_review = True
        if not isinstance(assessment, dict):
            assessment = _endpoint_assessment(
                "source_coverage_gap",
                "Current static graph snapshot did not resolve this safe metadata label.",
            )

    probe = {
        **base,
        "resolverStatus": resolver_status,
        "snapshotId": result.get("snapshotId"),
        "stableKey": resolved.get("stableKey"),
        "nodeType": resolved.get("nodeType"),
        "candidateCount": len(candidates),
        "candidates": [_candidate_summary(candidate) for candidate in candidates],
        "sourceRefs": list(result.get("sourceRefs") or []),
        "evidencePathNodes": list(evidence_path.get("nodes") or []),
        "endpointAssessment": assessment,
        "requiresStaticSourceReview": requires_review,
        "semanticEdgeAction": action,
        "noRawMatureBuildMaterial": True,
    }
    if probe["endpointAssessment"] is None:
        probe.pop("endpointAssessment")
    return probe


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


def _validate_input_report(source_report: dict[str, Any]) -> None:
    if source_report.get("safeArtifactOnly") is not True:
        raise ValueError("input report must be safe-only before graph coverage probing")
    if source_report.get("status") != "ready_for_external_researcher":
        raise ValueError("input report must be ready_for_external_researcher")
    if not isinstance(source_report.get("samples"), list):
        raise ValueError("input report samples must be a list")
    _safe_token_field("reportId", source_report.get("reportId"))
    for index, sample in enumerate(source_report["samples"]):
        if not isinstance(sample, dict):
            raise ValueError(f"samples[{index}] must be an object")
        _safe_token_field(f"samples[{index}].sampleId", sample.get("sampleId"))
        _safe_hash_field(f"samples[{index}].sourceHash", sample.get("sourceHash"))
        _safe_hash_field(f"samples[{index}].packetSafeHash", sample.get("packetSafeHash"))
    _assert_safe_report(source_report)


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "stableKey": str(candidate.get("stableKey") or ""),
        "nodeType": str(candidate.get("nodeType") or ""),
        "sourceRefs": list(candidate.get("sourceRefs") or []),
    }


def _endpoint_assessment(classification: str, reason: str) -> dict[str, Any]:
    return {
        "classification": classification,
        "hallucinationVerdict": "not_assessed",
        "reason": reason,
        "requiresStaticSourceReview": True,
    }


def _metadata_value(metadata: dict[str, Any], key: str, default: str) -> str:
    value = metadata.get(key, default)
    text = " ".join(str(value).split())
    _reject_token_copyable(f"metadata field {key}", text)
    return text[:120] if text else default


def _safe_ref(prefix: str, value: Any) -> str:
    text = "".join(ch for ch in str(value or "unknown").lower() if ch.isalnum())[:16]
    return f"{prefix}:{text or 'unknown'}"


def _safe_token(value: Any) -> str:
    text = str(value or "unknown").strip()
    _reject_token_copyable("token", text)
    safe = "".join(ch if ch.isalnum() or ch in "_:-." else "-" for ch in text)
    return safe[:80] or "unknown"


def _safe_token_field(field: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    _reject_token_copyable(field, text)
    if not TOKEN_RE.fullmatch(text):
        raise ValueError(f"{field} must be a safe token")
    return text


def _safe_hash_field(field: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    _reject_token_copyable(field, text)
    if not re.fullmatch(r"[A-Fa-f0-9]{16,128}", text):
        raise ValueError(f"{field} must be a hex safe hash")
    return text.lower()


def _reject_token_copyable(field: str, text: str) -> None:
    lower = text.lower()
    if any(marker.lower() in lower for marker in RAW_MARKERS):
        raise ValueError(f"{field} failed copy-safety scan")
    if re.search(
        r"(?:https?://|www\.|pobb\.in|pastebin\.com|poe\.ninja|pathofexile\.com)",
        lower,
    ):
        raise ValueError(f"{field} failed copy-safety scan")
    flags = set(copy_safety.copyability_flags(text))
    flags.discard("full_gem_link_like")
    if flags:
        raise ValueError(f"{field} failed copy-safety scan")


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


def _ephemeral_db_path() -> Path:
    root = Path(tempfile.mkdtemp(prefix="poe-bd-creator-phase4-coverage-"))
    return root / "mature_learning_coverage.sqlite"


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4 Real Sample Graph Coverage",
        "",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Snapshot: `{report.get('snapshotId')}`",
        f"- Semantic edge write attempted: `{report['semanticEdgeWrite']['attempted']}`",
        f"- Semantic edge write reason: `{report['semanticEdgeWrite']['reason']}`",
        "",
        "## Probes",
        "",
    ]
    for probe in report["probes"]:
        lines.append(
            f"- `{probe['sampleId']}` / `{probe['candidateName']}`: `{probe['resolverStatus']}` -> `{probe['semanticEdgeAction']}`"
        )
        if probe.get("stableKey"):
            lines.append(f"  - stable key: `{probe['stableKey']}`")
        assessment = probe.get("endpointAssessment")
        if isinstance(assessment, dict):
            lines.append(
                f"  - endpoint assessment: `{assessment.get('classification')}` / `{assessment.get('hallucinationVerdict')}`"
            )
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-report", default=str(PACKET_REPORT))
    parser.add_argument(
        "--graph-snapshot-index",
        default=str(paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"),
    )
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    report = write_real_sample_graph_coverage_report(
        input_report=args.input_report,
        graph_snapshot_index=args.graph_snapshot_index,
        db_path=Path(args.db_path) if args.db_path else None,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["probes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
