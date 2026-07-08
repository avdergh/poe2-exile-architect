"""Run a resolver-backed Phase 4 semantic-edge fixture E2E.

This script does not run an LLM and does not read mature build raw material. It builds a tiny
Phase 2 physical-graph snapshot fixture, registers it through the normal snapshot index, resolves
semantic-edge endpoints through the Phase 3 graph tool service, and only then proposes a Phase 4
semantic edge.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_phase2_acceptance_artifact as phase2  # noqa: E402
from server.knowledge import graph_tools, mature_learning, physical_graph, research_memory  # noqa: E402

JSON_OUTPUT = REPO_ROOT / "phase4_semantic_edge_fixture_e2e_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_semantic_edge_fixture_e2e_report.md"
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
)


def build_fixture_semantic_edge_report(
    *,
    db_path: str | Path | None = None,
    work_dir: str | Path | None = None,
) -> dict[str, Any]:
    if work_dir is not None:
        return _build_fixture_semantic_edge_report(
            db_path=Path(db_path) if db_path is not None else Path(work_dir) / "mature.sqlite",
            work_dir=Path(work_dir),
        )
    with tempfile.TemporaryDirectory(prefix="poe-phase4-semantic-edge-fixture-") as temp_dir:
        root = Path(temp_dir)
        return _build_fixture_semantic_edge_report(
            db_path=Path(db_path) if db_path is not None else root / "mature.sqlite",
            work_dir=root,
        )


def write_fixture_semantic_edge_report(
    *,
    db_path: str | Path | None = None,
    work_dir: str | Path | None = None,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_fixture_semantic_edge_report(db_path=db_path, work_dir=work_dir)
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _build_fixture_semantic_edge_report(*, db_path: Path, work_dir: Path) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    snapshot, keys = phase2.build_snapshot_fixture_with_keys()
    snapshot_path = work_dir / "phase2_fixture_snapshot.json"
    index_path = work_dir / "snapshot_index.sqlite"
    physical_graph.save_snapshot(snapshot, snapshot_path)
    physical_graph.register_snapshot(index_path, snapshot, snapshot_path)
    graph_tools.clear_service_cache()
    graph_service = graph_tools.service_from_snapshot_index(str(index_path))

    skill_key = str(keys["skill_key"])
    support_key = str(keys["support_key"])
    skill_resolution = graph_service.run_tool("resolve_graph_component", {"query": skill_key})
    support_resolution = graph_service.run_tool("resolve_graph_component", {"query": support_key})
    payload = _semantic_edge_payload(
        skill_key=skill_key,
        support_key=support_key,
        skill_resolution=_endpoint_evidence(skill_resolution),
        support_resolution=_endpoint_evidence(support_resolution),
    )

    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=graph_service)
    edge_submission = service.propose_semantic_edges(payload)
    edge_id = _first(edge_submission.get("edgeIds"))
    planner_visible = _planner_visible(db_path, edge_id)

    forged_payload = deepcopy(payload)
    forged_payload["semantic_edges"][0]["source_resolution"]["source_refs"] = [
        *_endpoint_evidence(skill_resolution)["source_refs"],
        "fixture:forged",
    ]
    forged_check = service.propose_semantic_edges(forged_payload)

    missing_payload = deepcopy(payload)
    missing_key = "skill:VividStampedePlayer"
    missing_payload["semantic_edges"][0]["source_key"] = missing_key
    missing_payload["semantic_edges"][0]["affected_component_keys"] = [missing_key, support_key]
    missing_payload["semantic_edges"][0]["source_resolution"] = {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": missing_key,
        "snapshot_id": graph_service.snapshot.snapshot_id,
        "evidence_path_nodes": [missing_key],
        "source_refs": [],
    }
    missing_check = service.propose_semantic_edges(missing_payload)

    report = {
        "reportId": "phase4-semantic-edge-fixture-e2e-v1",
        "status": _status(edge_submission, planner_visible, forged_check, missing_check),
        "safeArtifactOnly": True,
        "snapshotId": graph_service.snapshot.snapshot_id,
        "resolverResults": [
            _resolver_summary("source", skill_resolution),
            _resolver_summary("target", support_resolution),
        ],
        "edgeSubmission": {
            "status": edge_submission.get("status"),
            "edgeIds": edge_submission.get("edgeIds", []),
            "edgeType": "synergizes_with",
            "sourceKey": skill_key,
            "targetKey": support_key,
            "plannerVisible": planner_visible,
            "noRawMatureBuildMaterial": edge_submission.get("noRawMatureBuildMaterial"),
        },
        "forgedEvidenceCheck": {
            "status": forged_check.get("status"),
            "errorCode": forged_check.get("errorCode"),
            "caveats": forged_check.get("caveats", []),
        },
        "missingEndpointCheck": {
            "status": missing_check.get("status"),
            "errorCode": missing_check.get("errorCode"),
            "endpointAssessment": missing_check.get("endpointAssessment"),
        },
        "metrics": {
            "resolverBackedEdgesAccepted": 1 if edge_submission.get("status") == "accepted" else 0,
            "plannerVisibleAcceptedEdges": 1 if planner_visible else 0,
            "fabricatedResolverEvidenceRejected": forged_check.get("errorCode")
            == "endpoint_resolution_mismatch",
            "missingEndpointNotHallucinated": (
                missing_check.get("endpointAssessment", {}).get("hallucinationVerdict")
                == "not_assessed"
            ),
            "noRawMatureBuildMaterial": True,
        },
        "caveats": [
            "Fixture E2E only: this proves resolver-backed semantic-edge ingestion, not real mature-build semantic promotion.",
            "Real user mature-build semantic edges still require a local Phase 3 graph snapshot covering the sampled endpoints.",
        ],
    }
    _assert_safe_report(report)
    return report


def _endpoint_evidence(result: dict[str, Any]) -> dict[str, Any]:
    subject = result.get("resolvedSubject")
    if result.get("status") != "resolved" or not isinstance(subject, dict):
        raise ValueError(f"endpoint was not resolved: {result.get('status')}")
    stable_key = str(subject["stableKey"])
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": stable_key,
        "snapshot_id": str(result["snapshotId"]),
        "evidence_path_nodes": list(result.get("evidencePath", {}).get("nodes") or [stable_key]),
        "source_refs": list(result.get("sourceRefs") or []),
    }


def _semantic_edge_payload(
    *,
    skill_key: str,
    support_key: str,
    skill_resolution: dict[str, Any],
    support_resolution: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 4,
        "fragments": [],
        "semantic_edges": [
            {
                "source_key": skill_key,
                "target_key": support_key,
                "source_resolution": skill_resolution,
                "target_resolution": support_resolution,
                "edge_type": "synergizes_with",
                "rationale": (
                    "Phase 2 fixture evidence resolves both endpoints before recording this "
                    "safe support-skill relationship."
                ),
                "source_case_refs": ["case:phase4-semantic-edge-fixture"],
                "safe_evidence_refs": ["safe:phase2-fixture:support-skill"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "status": "valid",
                "confidence": "medium",
                "modelability": "partial",
                "copy_safety_state": "passed",
                "context_requirements": [
                    {
                        "context_type": "socket_context",
                        "socketed_support_keys": [support_key],
                        "socketed_support_families": ["Pierce"],
                        "current_support_count": 1,
                        "max_support_count": 1,
                        "duplicate_support_policy": "reject_same_support_key",
                    }
                ],
                "affected_component_keys": [skill_key, support_key],
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
                "directionality": "associative",
            }
        ],
    }


def _planner_visible(db_path: Path, edge_id: str | None) -> bool:
    if not edge_id:
        return False
    con = mature_learning.connect(db_path)
    try:
        row = con.execute(
            "SELECT planner_visible FROM research_semantic_edges WHERE edge_id = ?",
            (edge_id,),
        ).fetchone()
        return bool(row and row["planner_visible"])
    finally:
        con.close()


def _status(
    edge_submission: dict[str, Any],
    planner_visible: bool,
    forged_check: dict[str, Any],
    missing_check: dict[str, Any],
) -> str:
    if (
        edge_submission.get("status") == "accepted"
        and planner_visible
        and forged_check.get("errorCode") == "endpoint_resolution_mismatch"
        and missing_check.get("errorCode") == "missing_endpoint"
        and missing_check.get("endpointAssessment", {}).get("hallucinationVerdict")
        == "not_assessed"
    ):
        return "pass"
    return "fail"


def _resolver_summary(role: str, result: dict[str, Any]) -> dict[str, Any]:
    evidence = _endpoint_evidence(result)
    return {
        "role": role,
        "toolName": result.get("toolName"),
        "status": result.get("status"),
        "stableKey": evidence["stable_key"],
        "snapshotId": evidence["snapshot_id"],
        "evidencePathNodes": evidence["evidence_path_nodes"],
        "sourceRefs": evidence["source_refs"],
        "noRawQuery": result.get("noRawQuery"),
    }


def _first(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    return None


def _assert_safe_report(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe durable report markers detected: {', '.join(leaks)}")


def _markdown(report: dict[str, Any]) -> str:
    assessment = report.get("missingEndpointCheck", {}).get("endpointAssessment") or {}
    lines = [
        "# Phase 4 Semantic Edge Fixture E2E",
        "",
        f"- Report: `{report['reportId']}`",
        f"- Status: `{report['status']}`",
        f"- Snapshot: `{report['snapshotId']}`",
        f"- Edge submission: `{report['edgeSubmission']['status']}`",
        f"- Planner visible: `{report['edgeSubmission']['plannerVisible']}`",
        f"- Forged evidence check: `{report['forgedEvidenceCheck']['errorCode']}`",
        f"- Missing endpoint assessment: `{assessment.get('classification')}` / `{assessment.get('hallucinationVerdict')}`",
        "",
        "## Resolved Endpoints",
        "",
    ]
    for item in report["resolverResults"]:
        lines.append(
            f"- `{item['role']}`: `{item['stableKey']}` via `{item['toolName']}` / `{item['status']}`"
        )
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    report = write_fixture_semantic_edge_report(
        db_path=Path(args.db_path) if args.db_path else None,
        work_dir=Path(args.work_dir) if args.work_dir else None,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
