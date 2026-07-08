"""Build a safe external-style semantic proposal from resolved Phase 4 endpoints.

This script is a local acceptance helper: it consumes safe proposal request
artifacts, re-resolves endpoints through the graph tool, and emits typed
ResearcherOutput schema_version=4. It does not read raw mature build material.
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
from server.knowledge import copy_safety, graph_tools, research_models  # noqa: E402

REQUEST_REPORT = REPO_ROOT / "phase4_semantic_proposal_request.json"
JSON_OUTPUT = REPO_ROOT / "phase4_real_semantic_proposal.json"
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


def build_real_semantic_proposal(
    *,
    request_report: str | Path = REQUEST_REPORT,
    graph_snapshot_index: str | Path | None = None,
) -> dict[str, Any]:
    request = json.loads(Path(request_report).read_text(encoding="utf-8"))
    _assert_safe_report(request)
    if request.get("safeArtifactOnly") is not True:
        raise ValueError("semantic proposal request must be safe-only")
    index_path = (
        Path(graph_snapshot_index)
        if graph_snapshot_index is not None
        else paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"
    )
    graph_tools.clear_service_cache()
    service = graph_tools.service_from_snapshot_index(str(index_path))
    primary_by_sample = {
        str(item.get("sampleId")): str(item.get("acceptedStableKey"))
        for item in request.get("acceptedEndpoints", [])
        if isinstance(item, dict) and item.get("sampleId") and item.get("acceptedStableKey")
    }
    secondary_by_sample: dict[str, list[dict[str, Any]]] = {}
    for item in request.get("resolvedSecondaryEndpoints", []):
        if not isinstance(item, dict):
            continue
        sample_id = str(item.get("sampleId") or "")
        stable_key = str(item.get("stableKey") or "")
        if sample_id in primary_by_sample and stable_key:
            secondary_by_sample.setdefault(sample_id, []).append(item)

    edges: list[dict[str, Any]] = []
    for sample_id, primary_key in sorted(primary_by_sample.items()):
        for secondary in secondary_by_sample.get(sample_id, []):
            candidate_name = str(secondary.get("candidateName") or "")
            edge = _edge_for_secondary(
                service=service,
                sample_id=sample_id,
                primary_key=primary_key,
                secondary_key=str(secondary["stableKey"]),
                secondary_name=candidate_name,
            )
            if edge is not None:
                edges.append(edge)

    proposal = {"schema_version": 4, "fragments": [], "semantic_edges": edges}
    validation = research_models.validate_researcher_output(proposal)
    if validation.get("status") != "accepted":
        raise ValueError(f"generated proposal failed validation: {validation.get('errorCode')}")
    _assert_safe_report(proposal)
    return proposal


def write_real_semantic_proposal(
    *,
    request_report: str | Path = REQUEST_REPORT,
    graph_snapshot_index: str | Path | None = None,
    json_output: str | Path = JSON_OUTPUT,
) -> dict[str, Any]:
    proposal = build_real_semantic_proposal(
        request_report=request_report,
        graph_snapshot_index=graph_snapshot_index,
    )
    Path(json_output).write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return proposal


def _edge_for_secondary(
    *,
    service: graph_tools.GraphQueryService,
    sample_id: str,
    primary_key: str,
    secondary_key: str,
    secondary_name: str,
) -> dict[str, Any] | None:
    primary_resolution = service.run_tool("resolve_graph_component", {"query": primary_key})
    secondary_resolution = service.run_tool("resolve_graph_component", {"query": secondary_key})
    if (
        primary_resolution.get("status") != "resolved"
        or secondary_resolution.get("status") != "resolved"
    ):
        return None
    primary_evidence = _endpoint_evidence(primary_resolution)
    secondary_evidence = _endpoint_evidence(secondary_resolution)
    edge_type, rationale, context_requirements = _edge_shape(
        primary_key=primary_key,
        secondary_key=secondary_key,
        secondary_name=secondary_name,
    )
    return {
        "source_key": primary_key,
        "target_key": secondary_key,
        "source_resolution": primary_evidence,
        "target_resolution": secondary_evidence,
        "edge_type": edge_type,
        "rationale": rationale,
        "source_case_refs": [f"case:{sample_id}"],
        "safe_evidence_refs": [f"external-proposal:{sample_id}:semantic-edge-v1"],
        "game_patch": "0.5.4",
        "passive_tree_version": "0_5",
        "pob_version_or_commit": "unknown",
        "status": "valid",
        "confidence": "medium",
        "modelability": "partial",
        "copy_safety_state": "passed",
        "context_requirements": context_requirements,
        "affected_component_keys": sorted({primary_key, secondary_key}),
        "visibility": "creator_visible",
        "split": "train_context",
        "knowledge_scope": "global_seed",
        "directionality": "directional",
    }


def _edge_shape(
    *,
    primary_key: str,
    secondary_key: str,
    secondary_name: str,
) -> tuple[str, str, list[dict[str, Any]]]:
    if secondary_key.startswith("support:"):
        return (
            "has_modelability_caveat",
            (
                "External Researcher proposal: use this secondary support-like endpoint only as "
                "an advisory mature-engine caveat, not as unconditional legality."
            ),
            [
                {
                    "context_type": "verification_gate_requirement",
                    "task": f"Verify {secondary_name or secondary_key} support/cooldown gate with Judge before planner use.",
                },
                {
                    "context_type": "socket_requirement",
                    "skill_key": primary_key,
                    "support_key": secondary_key,
                },
            ],
        )
    return (
        "has_modelability_caveat",
        (
            "External Researcher proposal: this secondary skill layer is an advisory mature-engine "
            "context and requires PoB/Judge modelability review before numeric claims."
        ),
        [
            {
                "context_type": "verification_gate_requirement",
                "task": f"Verify {secondary_name or secondary_key} layer and modelability before planner promotion.",
            },
            {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_final"]},
        ],
    )


def _endpoint_evidence(result: dict[str, Any]) -> dict[str, Any]:
    subject = result.get("resolvedSubject")
    if result.get("status") != "resolved" or not isinstance(subject, dict):
        raise ValueError("endpoint is not resolved")
    stable_key = _safe_stable_key(subject.get("stableKey"))
    evidence_path = (
        result.get("evidencePath") if isinstance(result.get("evidencePath"), dict) else {}
    )
    nodes = evidence_path.get("nodes") or [stable_key]
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": stable_key,
        "snapshot_id": _safe_text(result.get("snapshotId")),
        "evidence_path_nodes": [_safe_stable_key(item) for item in nodes],
        "source_refs": [_safe_text(item) for item in result.get("sourceRefs", [])],
    }


def _safe_stable_key(value: Any) -> str:
    text = str(value or "").strip()
    _reject_copyable(text)
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,180}", text):
        raise ValueError("stable key must be safe")
    return text


def _safe_text(value: Any) -> str:
    text = " ".join(str(value or "").split())[:240]
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-report", default=str(REQUEST_REPORT))
    parser.add_argument(
        "--graph-snapshot-index",
        default=str(paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"),
    )
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    args = parser.parse_args(argv)
    proposal = write_real_semantic_proposal(
        request_report=args.request_report,
        graph_snapshot_index=args.graph_snapshot_index,
        json_output=args.json_output,
    )
    print(json.dumps(proposal, ensure_ascii=False, sort_keys=True))
    return 0 if proposal["semantic_edges"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
