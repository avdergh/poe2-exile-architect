"""Run Phase 4.5 programmatic component bootstrap pattern acceptance.

This fallback helper accepts many local PoB-code files, but it processes each
unique source independently. It transiently decodes PoB import codes only to
discover resolver-backed component candidates, then writes low-trust safe
BuildDesignObservation / BuildPattern rows through ResearchMemoryService gates.

It is not a Deep Researcher pass: no LLM/agent analyzes the full build, and all
accepted rows must stay case_observation confidence only.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server import paths  # noqa: E402
from server.compute import pob_code  # noqa: E402
from server.knowledge import copy_safety, graph_tools, research_memory  # noqa: E402

try:  # noqa: SIM105 - keep optional helper import explicit for tests/import errors.
    from scripts import build_phase45_pattern_bootstrap_proposal as bootstrap_helpers  # noqa: E402
except ImportError:  # pragma: no cover - repository layout issue.
    bootstrap_helpers = None  # type: ignore[assignment]


MANIFEST = REPO_ROOT / "phase4_pattern_bootstrap_manifest.json"
JSON_OUTPUT = REPO_ROOT / "phase45_component_bootstrap_batch_report.json"
MD_OUTPUT = REPO_ROOT / "phase45_component_bootstrap_batch_report.md"
DB_PATH = REPO_ROOT / "phase4_real_research_memory.sqlite"

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

ROLE_BY_NODE_TYPE = {
    "active_skill": "primary_damage",
    "support_gem": "support_modifier",
    "ascendancy": "ascendancy_shell",
    "keystone": "keystone_transformer",
    "notable": "passive_anchor",
    "unique": "unique_enabler",
}


def write_phase45_component_bootstrap_batch_report(
    *,
    source_files: list[str | Path],
    manifest_file: str | Path = MANIFEST,
    graph_snapshot_index: str | Path | None = None,
    db_path: str | Path | None = DB_PATH,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_phase45_component_bootstrap_batch_report(
        source_files=source_files,
        manifest_file=manifest_file,
        graph_snapshot_index=graph_snapshot_index,
        db_path=db_path,
    )
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def build_phase45_component_bootstrap_batch_report(
    *,
    source_files: list[str | Path],
    manifest_file: str | Path = MANIFEST,
    graph_snapshot_index: str | Path | None = None,
    db_path: str | Path | None = DB_PATH,
) -> dict[str, Any]:
    index_path = (
        Path(graph_snapshot_index)
        if graph_snapshot_index is not None
        else paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"
    )
    try:
        graph_service = graph_tools.service_from_snapshot_index(str(index_path))
    except Exception as exc:  # pragma: no cover - path/platform dependent.
        report = _terminal_report(
            status="blocked_graph_snapshot_unavailable",
            error_code="graph_snapshot_unavailable",
            caveats=[_safe_caveat(exc)],
        )
        _assert_safe_report(report)
        return report

    try:
        manifest = json.loads(Path(manifest_file).read_text(encoding="utf-8"))
        _assert_safe_report(manifest)
    except (OSError, ValueError, TypeError) as exc:
        report = _terminal_report(
            status="rejected_invalid_manifest",
            error_code="invalid_manifest",
            caveats=[_safe_caveat(exc)],
        )
        _assert_safe_report(report)
        return report

    manifest_by_source = _manifest_by_source_hash(manifest)
    service = research_memory.ResearchMemoryService(
        db_path=Path(db_path) if db_path else None,
        graph_service=graph_service,
    )

    seen_identity_hashes: set[str] = set()
    duplicate_inputs: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    accepted_pattern_count = 0
    accepted_observation_count = 0
    deferred_count = 0

    for input_index, source_file in enumerate(source_files, start=1):
        source_path = Path(source_file)
        source = source_path.read_text(encoding="utf-8").strip()
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        identity_hash = _source_identity_hash(source, fallback_hash=source_hash)
        source_hash_ref = f"source-hash:{source_hash[:16]}"
        if identity_hash in seen_identity_hashes:
            duplicate_inputs.append(
                {
                    "inputIndex": input_index,
                    "sourceHashRef": source_hash_ref,
                    "dedupeAction": "excluded_duplicate_import_code",
                }
            )
            continue
        seen_identity_hashes.add(identity_hash)

        manifest_sample = manifest_by_source.get(source_hash[:12], {})
        sample_id = _safe_sample_id(
            manifest_sample.get("sampleId"),
            fallback=f"case:phase45-component-bootstrap-{len(samples) + 1:03d}",
        )
        sample_result = _process_one_source(
            source=source,
            source_hash=source_hash,
            sample_id=sample_id,
            manifest_sample=manifest_sample,
            graph_service=graph_service,
            service=service,
        )
        samples.append(sample_result)
        if sample_result["status"] == "accepted":
            accepted_pattern_count += len(sample_result.get("patternIds", []))
            accepted_observation_count += len(sample_result.get("observationIds", []))
        else:
            deferred_count += 1

    family_counts = Counter(
        sample.get("buildFamilyKey", "unknown-family")
        for sample in samples
        if sample.get("buildFamilyKey")
    )
    report = {
        "reportId": "phase45-component-bootstrap-batch-v1",
        "status": "accepted" if accepted_pattern_count > 0 and deferred_count == 0 else "partial",
        "safeArtifactOnly": True,
        "snapshotId": graph_service.snapshot.snapshot_id,
        "sampleCount": len(samples),
        "acceptedPatternCount": accepted_pattern_count,
        "acceptedObservationCount": accepted_observation_count,
        "deferredSampleCount": deferred_count,
        "duplicateInputCount": len(duplicate_inputs),
        "duplicateInputs": duplicate_inputs,
        "familySampleCounts": dict(sorted(family_counts.items())),
        "samples": samples,
        "caveats": [
            "Batch input was processed one unique source at a time.",
            "All accepted rows are case_observation confidence only.",
            "This is programmatic component bootstrap, not an external Deep Researcher pass.",
            "Transient decode was used only to find resolver-backed component candidates.",
        ],
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_report(report)
    return report


def _process_one_source(
    *,
    source: str,
    source_hash: str,
    sample_id: str,
    manifest_sample: dict[str, Any],
    graph_service: graph_tools.GraphQueryService,
    service: research_memory.ResearchMemoryService,
) -> dict[str, Any]:
    safe_ref = f"safe:phase45-component-bootstrap:{source_hash[:12]}"
    try:
        xml = pob_code.to_xml(source)
        root = ET.fromstring(xml)
    except Exception as exc:
        return {
            "sampleId": sample_id,
            "status": "deferred",
            "deferReason": "transient_decode_failed",
            "sourceHashRef": f"source-hash:{source_hash[:16]}",
            "caveats": [_safe_caveat(exc)],
        }

    component_queries = _candidate_component_queries(root, graph_service)
    resolved_components = []
    unresolved_components = []
    for query, fallback_role in component_queries:
        resolution = graph_service.run_tool("resolve_graph_component", {"query": query})
        if resolution.get("status") != "resolved" or not resolution.get("resolvedSubject"):
            unresolved_components.append(
                {
                    "queryRef": _safe_query_ref(query),
                    "resolverStatus": _safe_text(resolution.get("status")),
                }
            )
            continue
        subject = resolution["resolvedSubject"]
        key = str(subject["stableKey"])
        node_type = str(subject.get("nodeType") or "")
        role = ROLE_BY_NODE_TYPE.get(node_type, fallback_role)
        resolved_components.append(
            {
                "component_key": key,
                "role": role,
                "displayName": _safe_text(subject.get("displayName")),
                "nodeType": node_type,
                "resolution": _resolution_evidence(resolution, key),
            }
        )

    resolved_components = _dedupe_components(resolved_components)
    if not resolved_components:
        return {
            "sampleId": sample_id,
            "status": "deferred",
            "deferReason": "no_resolved_components",
            "sourceHashRef": f"source-hash:{source_hash[:16]}",
            "unresolvedComponents": unresolved_components[:8],
        }

    dedupe_query = _dedupe_query_text(resolved_components)
    query_result = service.query_research_memory(
        dedupe_query,
        component_keys=[component["component_key"] for component in resolved_components],
        limit=5,
    )
    dedupe_ref = str(query_result["dedupeQueryRef"])
    payload = _proposal_payload(
        sample_id=sample_id,
        safe_ref=safe_ref,
        manifest_sample=manifest_sample,
        components=resolved_components,
    )
    write_result = service.propose_build_patterns(payload)
    if write_result.get("status") != "accepted":
        return {
            "sampleId": sample_id,
            "status": "deferred",
            "deferReason": "proposal_rejected",
            "sourceHashRef": f"source-hash:{source_hash[:16]}",
            "dedupeQueryRef": dedupe_ref,
            "errorCode": _safe_text(write_result.get("errorCode")),
            "caveats": [_safe_text(item) for item in write_result.get("caveats", [])],
            "componentKeys": [component["component_key"] for component in resolved_components],
            "unresolvedComponents": unresolved_components[:8],
        }

    return {
        "sampleId": sample_id,
        "status": "accepted",
        "sourceHashRef": f"source-hash:{source_hash[:16]}",
        "buildFamilyKey": _safe_text(
            manifest_sample.get("buildFamilyKey") or _fallback_family_key(resolved_components)
        ),
        "confidenceTier": "case_observation",
        "dedupeQueryRef": dedupe_ref,
        "observationIds": list(write_result.get("observationIds", [])),
        "patternIds": list(write_result.get("patternIds", [])),
        "componentKeys": [component["component_key"] for component in resolved_components],
        "componentRoles": {
            component["component_key"]: component["role"] for component in resolved_components
        },
        "unresolvedComponentCount": len(unresolved_components),
    }


def _candidate_component_queries(
    root: ET.Element,
    graph_service: graph_tools.GraphQueryService,
) -> list[tuple[str, str]]:
    nodes_by_key = getattr(graph_service, "_nodes_by_key", {})
    queries: list[tuple[str, str]] = []
    build = root.find(".//Build")
    if build is not None:
        class_name = str(build.attrib.get("className") or "")
        ascendancy_name = str(build.attrib.get("ascendClassName") or "")
        if ascendancy_name:
            queries.append((ascendancy_name, "ascendancy_shell"))
            if class_name:
                token = class_name.casefold().replace(" ", "_")
                stable_key = f"ascendancy:{token}:{ascendancy_name.casefold().replace(' ', '_')}"
                queries.append((stable_key, "ascendancy_shell"))

    if bootstrap_helpers is not None:
        active_skills, active_to_supports, supports = bootstrap_helpers._skill_components(
            root, nodes_by_key
        )
        for active in sorted(active_skills):
            queries.append((active, "primary_damage"))
            for support in sorted(active_to_supports.get(active, []))[:2]:
                queries.append((support, "support_modifier"))
        for support in sorted(supports)[:4]:
            queries.append((support, "support_modifier"))
        for passive in sorted(bootstrap_helpers._passive_components(root, nodes_by_key))[:4]:
            role = "keystone_transformer" if passive.startswith("keystone:") else "passive_anchor"
            queries.append((passive, role))
        unique_by_name = {
            node.display_name.casefold(): node.stable_key
            for node in nodes_by_key.values()
            if node.node_type == "unique"
        }
        for unique in sorted(bootstrap_helpers._unique_components(root, unique_by_name))[:3]:
            queries.append((unique, "unique_enabler"))
    return _dedupe_query_pairs(queries)


def _proposal_payload(
    *,
    sample_id: str,
    safe_ref: str,
    manifest_sample: dict[str, Any],
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    component_keys = [component["component_key"] for component in components]
    component_roles = {component["component_key"]: component["role"] for component in components}
    title = _case_title(components, sample_id=sample_id)
    summary = _case_summary(components)
    axes = _axes_for_components(components)
    context_requirements = [
        {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_mature"]},
        {"context_type": "verification_gate_requirement", "task": "Verify with planner and Judge."},
    ]
    return {
        "schema_version": 4,
        "fragments": [],
        "semantic_edges": [],
        "build_design_observations": [
            {
                "observation_type": "build_archetype",
                "title": title,
                "summary": summary,
                "axes": axes,
                "components": [
                    {
                        "component_key": component["component_key"],
                        "role": component["role"],
                        "resolution": component["resolution"],
                    }
                    for component in components
                ],
                "source_case_refs": [sample_id],
                "safe_evidence_refs": [safe_ref],
                "game_patch": "0.5.x",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
        "patterns": [
            {
                "pattern_type": "build_archetype",
                "title": title,
                "summary": summary,
                "component_keys": component_keys,
                "component_roles": component_roles,
                "confidence_tier": "case_observation",
                "sample_count": 1,
                "family_count": 1,
                "source_diversity_count": 1,
                "denominator": 1,
                "source_case_refs": [sample_id],
                "safe_evidence_refs": [safe_ref],
                "context_requirements": context_requirements,
                "planner_hint": _planner_hint(components),
                "verification_tasks": [
                    "Resolve and verify selected main damage skill before generation.",
                    "Run deterministic planner and Judge before treating this observation as usable.",
                ],
                "game_patch": "0.5.x",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
    }


def _resolution_evidence(resolution: dict[str, Any], stable_key: str) -> dict[str, Any]:
    evidence_path = resolution.get("evidencePath") or {}
    nodes = list(evidence_path.get("nodes") or [])
    if stable_key not in nodes:
        nodes.append(stable_key)
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": stable_key,
        "snapshot_id": str(resolution.get("snapshotId") or ""),
        "evidence_path_nodes": nodes,
        "source_refs": list(resolution.get("sourceRefs") or evidence_path.get("sourceRefs") or []),
    }


def _case_title(components: list[dict[str, Any]], *, sample_id: str) -> str:
    names = [component["displayName"] for component in components[:3]]
    return f"Case observation {sample_id}: " + " + ".join(names)


def _case_summary(components: list[dict[str, Any]]) -> str:
    roles = sorted({component["role"] for component in components})
    return (
        "One mature sample contains resolver-backed components with roles: "
        + ", ".join(roles)
        + ". Treat as a safe case observation, not a reusable trend."
    )


def _planner_hint(components: list[dict[str, Any]]) -> str:
    roles = sorted({component["role"] for component in components})
    return (
        "Use this case observation only as a candidate component set for Phase 5 search; "
        + "verify roles "
        + ", ".join(roles)
        + " before generation."
    )


def _axes_for_components(components: list[dict[str, Any]]) -> list[str]:
    axes = {"identity"}
    roles = {component["role"] for component in components}
    if "ascendancy_shell" in roles:
        axes.add("character_shell")
    if "primary_damage" in roles:
        axes.add("primary_skill_package")
    if roles & {"support_modifier", "generator", "payoff", "reservation", "movement"}:
        axes.add("secondary_skill_package")
    if roles & {"passive_anchor", "keystone_transformer"}:
        axes.add("passive_tree_shape")
    if "unique_enabler" in roles:
        axes.add("itemization")
    axes.add("modelability_caveats")
    return sorted(axes)


def _dedupe_query_text(components: list[dict[str, Any]]) -> str:
    parts = [component["component_key"] for component in components[:6]]
    return "phase45 component bootstrap case observation " + " ".join(parts)


def _dedupe_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    priority = {
        "ascendancy_shell": 0,
        "primary_damage": 1,
        "support_modifier": 2,
        "keystone_transformer": 3,
        "passive_anchor": 4,
        "unique_enabler": 5,
    }
    for component in sorted(components, key=lambda item: priority.get(item["role"], 99)):
        key = component["component_key"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(component)
        if len(deduped) >= 8:
            break
    return deduped


def _dedupe_query_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for query, role in pairs:
        if not query or query in seen:
            continue
        seen.add(query)
        deduped.append((query, role))
    return deduped


def _manifest_by_source_hash(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_hash: dict[str, dict[str, Any]] = {}
    samples = manifest.get("samples") if isinstance(manifest, dict) else []
    if not isinstance(samples, list):
        return by_hash
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        source_key = str(sample.get("sourceDiversityKey") or "")
        match = re.search(r"([0-9a-f]{12})$", source_key)
        if match:
            by_hash[match.group(1)] = sample
    return by_hash


def _fallback_family_key(components: list[dict[str, Any]]) -> str:
    ascendancy = next(
        (
            component["component_key"]
            for component in components
            if component["role"] == "ascendancy_shell"
        ),
        "unknown-shell",
    )
    skill = next(
        (
            component["component_key"]
            for component in components
            if component["role"] == "primary_damage"
        ),
        "unknown-skill",
    )
    return f"case-observation:{_safe_slug(ascendancy)}:{_safe_slug(skill)}"


def _safe_sample_id(value: Any, *, fallback: str) -> str:
    text = _safe_text(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", text) else fallback


def _safe_query_ref(query: str) -> str:
    return "query-hash:" + hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]


def _source_identity_hash(source: str, *, fallback_hash: str) -> str:
    try:
        xml = pob_code.to_xml(source)
    except Exception:
        return "raw:" + fallback_hash
    return "xml:" + hashlib.sha256(xml.encode("utf-8")).hexdigest()


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value)[:64]


def _terminal_report(*, status: str, error_code: str, caveats: list[str]) -> dict[str, Any]:
    return {
        "reportId": "phase45-component-bootstrap-batch-v1",
        "status": status,
        "safeArtifactOnly": True,
        "errorCode": error_code,
        "sampleCount": 0,
        "acceptedPatternCount": 0,
        "acceptedObservationCount": 0,
        "deferredSampleCount": 0,
        "duplicateInputCount": 0,
        "samples": [],
        "caveats": caveats,
        "noRawMatureBuildMaterial": True,
    }


def _safe_text(value: Any) -> str:
    text = " ".join(str(value or "").split())[:320]
    lower = text.casefold()
    if any(marker.casefold() in lower for marker in RAW_MARKERS):
        raise ValueError("copy-safety marker detected")
    if re.search(r"(?:https?://|www\.|pobb\.in|poe\.ninja|pastebin\.com)", lower):
        raise ValueError("copy-safety URL marker detected")
    return text


def _safe_caveat(exc: BaseException | str) -> str:
    try:
        return _safe_text(exc)
    except ValueError:
        return "input could not be decoded; raw error text was redacted by copy-safety guard"


def _assert_safe_report(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe report markers detected: {', '.join(leaks)}")
    forbidden = copy_safety.find_forbidden_paths(report)
    if forbidden:
        raise ValueError("unsafe report contains forbidden raw fields")
    flags = set(copy_safety.copyability_flags(report))
    flags.discard("full_gem_link_like")
    if flags:
        raise ValueError(f"report failed copy-safety scan: {', '.join(sorted(flags))}")


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4.5 Programmatic Component Bootstrap",
        "",
        f"- Status: `{report['status']}`",
        f"- Samples: `{report.get('sampleCount', 0)}`",
        f"- Accepted patterns: `{report.get('acceptedPatternCount', 0)}`",
        f"- Accepted observations: `{report.get('acceptedObservationCount', 0)}`",
        f"- Deferred samples: `{report.get('deferredSampleCount', 0)}`",
        f"- Duplicate inputs: `{report.get('duplicateInputCount', 0)}`",
        "",
        "## Families",
        "",
    ]
    for family, count in sorted(report.get("familySampleCounts", {}).items()):
        lines.append(f"- `{family}`: `{count}`")
    lines.extend(["", "## Samples", ""])
    for sample in report.get("samples", []):
        lines.append(
            f"- `{sample.get('sampleId')}`: `{sample.get('status')}`, "
            f"components `{len(sample.get('componentKeys', []))}`"
        )
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report.get("caveats", []))
    lines.append("")
    text = "\n".join(lines)
    for marker in RAW_MARKERS:
        if marker in text:
            raise ValueError(f"unsafe markdown marker detected: {marker}")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_files", nargs="+")
    parser.add_argument("--manifest-file", default=str(MANIFEST))
    parser.add_argument(
        "--graph-snapshot-index",
        default=str(paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"),
    )
    parser.add_argument("--db-path", default=str(DB_PATH))
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    report = write_phase45_component_bootstrap_batch_report(
        source_files=[Path(path) for path in args.source_files],
        manifest_file=args.manifest_file,
        graph_snapshot_index=args.graph_snapshot_index,
        db_path=args.db_path,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] in {"accepted", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
