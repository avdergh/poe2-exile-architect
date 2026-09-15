"""Build and register a local physical graph snapshot from vendored static raw data.

This script is intentionally source-boundary conservative. It only uses existing
physical-graph ingesters for explicit static facts and never creates graph nodes
from mature build samples, safe metadata, wiki text, or inferred labels.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server import paths  # noqa: E402
from server.knowledge import copy_safety, physical_graph  # noqa: E402
from pipeline import repoe_snapshot  # noqa: E402

JSON_OUTPUT = REPO_ROOT / "phase4_local_physical_graph_snapshot_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_local_physical_graph_snapshot_report.md"
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

ALLOWED_SOURCE_SPECS: tuple[physical_graph.SourceInventorySpec, ...] = (
    physical_graph.SourceInventorySpec(
        source_id="repoe:base_items",
        kind="repoe_raw",
        relative_path="base_items.min.json",
        schema_version="repoe_min_json_v1",
    ),
    physical_graph.SourceInventorySpec(
        source_id="repoe:mods",
        kind="repoe_raw",
        relative_path="mods.min.json",
        schema_version="repoe_min_json_v1",
    ),
    physical_graph.SourceInventorySpec(
        source_id="repoe:skill_gems",
        kind="repoe_raw",
        relative_path="skill_gems.min.json",
        schema_version="repoe_min_json_v1",
    ),
    physical_graph.SourceInventorySpec(
        source_id="repoe:skills",
        kind="repoe_raw",
        relative_path="skills.min.json",
        schema_version="repoe_min_json_v1",
    ),
    physical_graph.SourceInventorySpec(
        source_id="ggg:developer_docs:inventories",
        kind="official_docs_fixture",
        relative_path="official/inventories.min.json",
        schema_version="phase2_fixture_v1",
        claims=(
            physical_graph.SourceClaim(
                "build_planner_field",
                "BuildInventorySlot.inventory_id",
            ),
            physical_graph.SourceClaim("source_scope", "official_doc_examples"),
        ),
        source_url="https://www.pathofexile.com/developer/docs/game",
        confidence=0.85,
    ),
)

POB_PASSIVE_TREE_VERSION = "0_5"
POB_PASSIVE_TREE_SOURCE_ID = f"pob:passive_tree:{POB_PASSIVE_TREE_VERSION}"
POB_UNIQUES_SOURCE_ID = "pob:uniques"
POB_SKILL_PAYLOAD_TYPES_SOURCE_ID = "pob:skill_payload_types"

INGESTERS: dict[
    str, Callable[[Path, physical_graph.GraphSource], physical_graph.GraphIngestionResult]
] = {
    "repoe:base_items": lambda path, source: physical_graph.ingest_base_items(path, source=source),
    "repoe:mods": lambda path, source: physical_graph.ingest_mods(path, source=source),
    "repoe:skill_gems": lambda path, source: physical_graph.ingest_skill_gems(path, source=source),
    "repoe:skills": lambda path, source: physical_graph.ingest_skills(path, source=source),
    "ggg:developer_docs:inventories": lambda path, source: physical_graph.ingest_inventory_slots(
        path, source=source
    ),
}


def build_local_snapshot_report(
    *,
    raw_data_dir: str | Path = REPO_ROOT / "data" / "raw",
    pob_src_dir: str | Path = REPO_ROOT / "pob" / "PathOfBuilding-PoE2" / "src",
    output_dir: str | Path | None = None,
    generated_uniques_dir: str | Path | None = None,
) -> dict[str, Any]:
    with repoe_snapshot.snapshot_guard(Path(raw_data_dir)):
        return _build_local_snapshot_report(
            raw_data_dir=raw_data_dir, pob_src_dir=pob_src_dir, output_dir=output_dir,
            generated_uniques_dir=generated_uniques_dir,
        )


def _build_local_snapshot_report(
    *,
    raw_data_dir: str | Path,
    pob_src_dir: str | Path,
    output_dir: str | Path | None,
    generated_uniques_dir: str | Path | None,
) -> dict[str, Any]:
    raw_root = Path(raw_data_dir)
    pob_root = Path(pob_src_dir)
    graph_root = Path(output_dir) if output_dir is not None else _default_graph_dir()
    snapshots_dir = graph_root / "snapshots"
    index_path = graph_root / "snapshot_index.sqlite"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    bound_export = repoe_snapshot.verify_snapshot(raw_root)
    specs = ALLOWED_SOURCE_SPECS
    if bound_export is not None:
        bindings = {item["localFile"]: item for item in bound_export["files"]}
        specs = tuple(
            replace(spec, source_url=bindings[spec.relative_path]["sourceUrl"], claims=(
                *spec.claims,
                physical_graph.SourceClaim("source_commit", bound_export["sourceCommit"]),
                physical_graph.SourceClaim("exported_version", bound_export["exportedVersion"]),
                physical_graph.SourceClaim("content_sha256", bindings[spec.relative_path]["sha256"]),
            )) if spec.kind == "repoe_raw" else spec for spec in specs
        )
    sources = physical_graph.build_source_inventory(
        raw_data_dir=raw_root,
        specs=specs,
        include_missing=False,
    )
    sources_by_id = {source.source_id: source for source in sources}
    ingestion_results: list[physical_graph.GraphIngestionResult] = []
    ingested_sources: list[dict[str, Any]] = []

    for spec in specs:
        source = sources_by_id[spec.source_id]
        source_path = raw_root / spec.relative_path
        result = INGESTERS[spec.source_id](source_path, source)
        ingestion_results.append(result)
        ingested_sources.append(
            {
                "sourceId": source.source_id,
                "relativePath": spec.relative_path,
                "kind": source.kind,
                "expectedCount": source.expected_count,
                "emitted": _ingestion_counts(result),
            }
        )

    static_sources = list(sources)
    static_ingestions, static_source_reports, excluded_static_sources = _pob_static_ingestions(
        pob_root=pob_root,
        base_ingestion=ingestion_results[0],
        known_skill_keys={
            node.stable_key
            for result in ingestion_results
            for node in result.nodes
            if node.node_type == "active_skill"
        },
        generated_uniques_dir=Path(generated_uniques_dir) if generated_uniques_dir is not None else None,
    )
    ingestion_results.extend(static_ingestions)
    static_sources.extend(source for source, _result, _report in static_source_reports)
    ingested_sources.extend(report for _source, _result, report in static_source_reports)

    merged = physical_graph.merge_ingestion_results(*ingestion_results)
    snapshot = physical_graph.build_snapshot(
        sources=tuple(static_sources),
        nodes=merged.nodes,
        edges=merged.edges,
        aliases=merged.aliases,
        id_mappings=merged.id_mappings,
        requirement_facts=merged.requirement_facts,
        resource_facts=merged.resource_facts,
        passive_choices=merged.passive_choices,
        allocation_options=merged.allocation_options,
    )
    node_type_counts = _node_type_counts(snapshot)
    coverage_gate = _coverage_gate(node_type_counts)
    snapshot_path = snapshots_dir / f"{snapshot.snapshot_id}.json"
    latest = None
    if coverage_gate["readyForMaturePatternBootstrap"]:
        physical_graph.save_snapshot(snapshot, snapshot_path)
        physical_graph.register_snapshot(index_path, snapshot, snapshot_path)
        latest = _latest_registration(index_path, snapshot.snapshot_id)
    report = {
        "reportId": "phase4-local-physical-graph-snapshot-v1",
        "status": "installed"
        if coverage_gate["readyForMaturePatternBootstrap"]
        else "source_coverage_gap",
        "safeArtifactOnly": True,
        "snapshot": {
            "snapshotId": snapshot.snapshot_id,
            "snapshotPath": _safe_relative(snapshot_path)
            if coverage_gate["readyForMaturePatternBootstrap"]
            else None,
            "indexPath": _safe_relative(index_path),
            "nodeCount": len(snapshot.nodes),
            "edgeCount": len(snapshot.edges),
            "sourceCount": len(snapshot.sources),
            "aliasCount": len(snapshot.aliases),
            "idMappingCount": len(snapshot.id_mappings),
            "requirementFactCount": len(snapshot.requirement_facts),
            "resourceFactCount": len(snapshot.resource_facts),
            "passiveChoiceCount": len(snapshot.passive_choices),
            "allocationOptionCount": len(snapshot.allocation_options),
            "createdAt": snapshot.created_at.isoformat(),
        },
        "nodeTypeCounts": node_type_counts,
        "coverageGate": coverage_gate,
        "sourceInventory": ingested_sources,
        "excludedSources": {
            **excluded_static_sources,
            "data/raw/wiki": (
                "excluded: mechanics/reference text is not a physical graph source without "
                "a typed ingester and source contract"
            ),
            "mature_sample_metadata": (
                "excluded: mature build labels and safe metadata cannot create physical nodes"
            ),
        },
        "registeredSnapshot": latest,
        "caveats": [
            "This report is built only from allowlisted static raw sources and existing physical graph ingesters.",
            "Missing coverage is a source coverage issue, not mature-build hallucination evidence.",
            "Mature build labels and safe metadata cannot create physical nodes.",
        ],
    }
    _assert_safe_report(report)
    return report


def write_local_snapshot_report(
    *,
    raw_data_dir: str | Path = REPO_ROOT / "data" / "raw",
    pob_src_dir: str | Path = REPO_ROOT / "pob" / "PathOfBuilding-PoE2" / "src",
    output_dir: str | Path | None = None,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
    generated_uniques_dir: str | Path | None = None,
) -> dict[str, Any]:
    report = build_local_snapshot_report(
        raw_data_dir=raw_data_dir,
        pob_src_dir=pob_src_dir,
        output_dir=output_dir,
        generated_uniques_dir=generated_uniques_dir,
    )
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _default_graph_dir() -> Path:
    return paths.user_data_dir() / "physical_graph"


def _ingestion_counts(result: physical_graph.GraphIngestionResult) -> dict[str, int]:
    return {
        "nodes": len(result.nodes),
        "edges": len(result.edges),
        "aliases": len(result.aliases),
        "idMappings": len(result.id_mappings),
        "requirementFacts": len(result.requirement_facts),
        "resourceFacts": len(result.resource_facts),
        "passiveChoices": len(result.passive_choices),
        "allocationOptions": len(result.allocation_options),
    }


def _pob_static_ingestions(
    *,
    pob_root: Path,
    base_ingestion: physical_graph.GraphIngestionResult,
    known_skill_keys: set[str],
    generated_uniques_dir: Path | None = None,
) -> tuple[
    list[physical_graph.GraphIngestionResult],
    list[tuple[physical_graph.GraphSource, physical_graph.GraphIngestionResult, dict[str, Any]]],
    dict[str, str],
]:
    ingestions: list[physical_graph.GraphIngestionResult] = []
    reports: list[
        tuple[physical_graph.GraphSource, physical_graph.GraphIngestionResult, dict[str, Any]]
    ] = []
    excluded: dict[str, str] = {}

    passive_tree_path = pob_root / "TreeData" / POB_PASSIVE_TREE_VERSION / "tree.json"
    if passive_tree_path.exists():
        source = physical_graph.GraphSource(
            source_id=POB_PASSIVE_TREE_SOURCE_ID,
            kind="pinned_pob_passive_tree",
            source_file=_safe_pob_relative(passive_tree_path, pob_root=pob_root),
            claims=(
                physical_graph.SourceClaim("passive_tree_version", POB_PASSIVE_TREE_VERSION),
                physical_graph.SourceClaim("source_scope", "pinned_pob_tree_data"),
                physical_graph.SourceClaim("content_sha256", hashlib.sha256(passive_tree_path.read_bytes()).hexdigest()),
            ),
            expected_count=None,
            confidence=0.95,
            schema_version="pob_tree_json_v1",
        )
        result = physical_graph.ingest_passive_tree(
            passive_tree_path,
            source=source,
            tree_version=POB_PASSIVE_TREE_VERSION,
        )
        ingestions.append(result)
        reports.append(
            (
                source,
                result,
                _source_report_for_relative(
                    source,
                    _safe_pob_relative(passive_tree_path, pob_root=pob_root),
                    result,
                ),
            )
        )
    else:
        excluded["pob:passive_tree"] = (
            "excluded: pinned PoB passive tree source was not found at "
            f"{_safe_relative(passive_tree_path)}"
        )

    skill_paths = sorted((pob_root / "Data" / "Skills").glob("*.lua"))
    if skill_paths:
        source = physical_graph.GraphSource(
            source_id=POB_SKILL_PAYLOAD_TYPES_SOURCE_ID,
            kind="pinned_pob_skill_payload_types",
            source_file=_safe_pob_relative(pob_root / "Data" / "Skills", pob_root=pob_root),
            claims=(
                physical_graph.SourceClaim("passive_tree_version", "not_applicable"),
                physical_graph.SourceClaim("source_scope", "pinned_pob_skill_data"),
                physical_graph.SourceClaim("type_context", "minion_payload_and_support_flags"),
                physical_graph.SourceClaim("content_sha256", _static_file_set_hash(skill_paths, pob_root)),
            ),
            expected_count=len(skill_paths),
            confidence=0.95,
            schema_version="pob_generated_skill_lua_v2",
        )
        result = physical_graph.merge_ingestion_results(
            physical_graph.ingest_pob_minion_payload_types(
                skill_paths, source=source, known_skill_keys=known_skill_keys,
            ),
            physical_graph.ingest_pob_support_flags(
                skill_paths, source=source, known_skill_keys=known_skill_keys,
            ),
        )
        ingestions.append(result)
        reports.append(
            (
                source,
                result,
                _source_report_for_relative(
                    source,
                    _safe_pob_relative(pob_root / "Data" / "Skills", pob_root=pob_root),
                    result,
                ),
            )
        )
    else:
        excluded["pob:skill_payload_types"] = (
            "excluded: pinned PoB generated skill source directory is missing or empty at "
            f"{_safe_relative(pob_root / 'Data' / 'Skills')}"
        )

    unique_paths = sorted((pob_root / "Data" / "Uniques").glob("**/*.lua"))
    exported_uniques_dir = generated_uniques_dir if generated_uniques_dir is not None else REPO_ROOT / "data" / "physical_graph" / "uniques"
    if exported_uniques_dir.is_dir():
        unique_paths = sorted([*unique_paths, *exported_uniques_dir.glob("*.lua")])
    if unique_paths:
        source = physical_graph.GraphSource(
            source_id=POB_UNIQUES_SOURCE_ID,
            kind="pinned_pob_unique_text",
            source_file=_safe_pob_relative(pob_root / "Data" / "Uniques", pob_root=pob_root),
            claims=(
                physical_graph.SourceClaim("passive_tree_version", "not_applicable"),
                physical_graph.SourceClaim("source_scope", "pinned_pob_unique_text"),
                physical_graph.SourceClaim("content_sha256", _static_file_set_hash(unique_paths, pob_root)),
            ),
            expected_count=len(unique_paths),
            confidence=0.9,
            schema_version="pob_unique_lua_text_v1",
        )
        unique_results = [
            physical_graph.ingest_uniques(
                path,
                source=source,
                known_base_nodes=base_ingestion.nodes,
                known_base_aliases=base_ingestion.aliases,
            )
            for path in unique_paths
        ]
        result = physical_graph.merge_ingestion_results(*unique_results)
        ingestions.append(result)
        reports.append(
            (
                source,
                result,
                _source_report_for_relative(
                    source,
                    _safe_pob_relative(pob_root / "Data" / "Uniques", pob_root=pob_root),
                    result,
                ),
            )
        )
    else:
        excluded["pob:uniques"] = (
            "excluded: pinned PoB unique item source directory is missing or empty at "
            f"{_safe_relative(pob_root / 'Data' / 'Uniques')}"
        )

    return ingestions, reports, excluded


def _static_file_set_hash(files: list[Path], pob_root: Path) -> str:
    entries = [
        {"path": path.relative_to(pob_root).as_posix() if path.is_relative_to(pob_root)
         else "generated_uniques/" + path.name,
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in files
    ]
    return hashlib.sha256(json.dumps(sorted(entries, key=lambda item: item["path"]), sort_keys=True).encode()).hexdigest()


def _source_report(
    source: physical_graph.GraphSource,
    source_path: Path,
    result: physical_graph.GraphIngestionResult,
) -> dict[str, Any]:
    return {
        "sourceId": source.source_id,
        "relativePath": _safe_relative(source_path),
        "kind": source.kind,
        "expectedCount": source.expected_count,
        "emitted": _ingestion_counts(result),
    }


def _source_report_for_relative(
    source: physical_graph.GraphSource,
    relative_path: str,
    result: physical_graph.GraphIngestionResult,
) -> dict[str, Any]:
    return {
        "sourceId": source.source_id,
        "relativePath": relative_path,
        "kind": source.kind,
        "expectedCount": source.expected_count,
        "emitted": _ingestion_counts(result),
    }


def _safe_pob_relative(path: Path, *, pob_root: Path) -> str:
    try:
        return "pinned_pob/" + path.resolve().relative_to(pob_root.resolve()).as_posix()
    except ValueError:
        return _safe_relative(path)


def _node_type_counts(snapshot: physical_graph.GraphSnapshot) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in snapshot.nodes:
        counts[node.node_type] = counts.get(node.node_type, 0) + 1
    counts["resource_fact"] = len(snapshot.resource_facts)
    counts["requirement_fact"] = len(snapshot.requirement_facts)
    return dict(sorted(counts.items()))


def _coverage_gate(node_type_counts: dict[str, int]) -> dict[str, Any]:
    required = {
        "active_skill": "skill",
        "support_gem": "support",
        "passive": "passive",
        "notable": "notable",
        "keystone": "keystone",
        "ascendancy": "ascendancy",
        "unique": "unique",
    }
    missing = [
        label
        for node_type, label in required.items()
        if int(node_type_counts.get(node_type, 0)) <= 0
    ]
    assessment = {
        "classification": "ready" if not missing else "source_coverage_gap",
        "hallucinationVerdict": "not_assessed",
        "missingCoverage": missing,
        "requiresStaticSourceReview": bool(missing),
    }
    return {
        "readyForMaturePatternBootstrap": not missing,
        "missingCoverage": missing,
        "requiredNodeTypes": sorted(required),
        "endpointAssessment": assessment,
    }


def _latest_registration(index_path: Path, snapshot_id: str) -> dict[str, Any]:
    rows = physical_graph.list_registered_snapshots(index_path)
    match = next((row for row in rows if row.get("snapshot_id") == snapshot_id), None)
    if match is None:
        raise ValueError("registered snapshot missing after install")
    return {
        "snapshotId": str(match["snapshot_id"]),
        "snapshotPath": _safe_relative(Path(str(match["snapshot_path"]))),
        "nodeCount": int(match["node_count"]),
        "edgeCount": int(match["edge_count"]),
        "sourceCount": int(match["source_count"]),
        "isLatest": bool(match["is_latest"]),
    }


def _safe_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _assert_safe_report(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe durable report markers detected: {', '.join(leaks)}")
    flags = _copyability_flags_for_safe_text(report)
    if flags:
        raise ValueError(f"durable report failed copy-safety scan: {', '.join(flags)}")


def _copyability_flags_for_safe_text(value: Any) -> list[str]:
    flags: set[str] = set()
    for text in _iter_text_leaves(value):
        flags.update(copy_safety.copyability_flags(text))
    # Snapshot reports contain hyphenated safe ids such as
    # phase3-local-physical-graph-snapshot-v1. They are not mature-build gem
    # links and are already covered by explicit raw/link marker checks above.
    flags.discard("full_gem_link_like")
    return sorted(flags)


def _iter_text_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        if re.fullmatch(r"[A-Za-z0-9_.:/\\ -]{0,240}", value):
            return [value]
        return []
    if isinstance(value, dict):
        values: list[str] = []
        for child in value.values():
            values.extend(_iter_text_leaves(child))
        return values
    if isinstance(value, list):
        values = []
        for child in value:
            values.extend(_iter_text_leaves(child))
        return values
    return []


def _markdown(report: dict[str, Any]) -> str:
    snapshot = report["snapshot"]
    lines = [
        "# Phase 4 Local Physical Graph Snapshot",
        "",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Snapshot: `{snapshot['snapshotId']}`",
        f"- Nodes / edges / sources: `{snapshot['nodeCount']}` / `{snapshot['edgeCount']}` / `{snapshot['sourceCount']}`",
        f"- Snapshot file: `{snapshot['snapshotPath']}`",
        f"- Index: `{snapshot['indexPath']}`",
        "",
        "## Coverage Gate",
        "",
        f"- Ready for mature pattern bootstrap: `{report['coverageGate']['readyForMaturePatternBootstrap']}`",
        f"- Missing coverage: `{', '.join(report['coverageGate']['missingCoverage']) or 'none'}`",
        "",
        "## Node Type Counts",
        "",
    ]
    for node_type, count in report["nodeTypeCounts"].items():
        lines.append(f"- `{node_type}`: `{count}`")
    lines.extend(
        [
            "",
            "## Sources",
            "",
        ]
    )
    for source in report["sourceInventory"]:
        emitted = source["emitted"]
        lines.append(
            f"- `{source['sourceId']}`: `{source['relativePath']}` -> nodes `{emitted['nodes']}`, edges `{emitted['edges']}`"
        )
    lines.extend(["", "## Excluded Coverage", ""])
    for key, reason in report["excludedSources"].items():
        lines.append(f"- `{key}`: {reason}")
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-data-dir", default=str(REPO_ROOT / "data" / "raw"))
    parser.add_argument(
        "--pob-src-dir",
        default=str(REPO_ROOT / "pob" / "PathOfBuilding-PoE2" / "src"),
    )
    parser.add_argument("--output-dir", default=str(_default_graph_dir()))
    parser.add_argument("--generated-uniques-dir")
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    report = write_local_snapshot_report(
        raw_data_dir=args.raw_data_dir,
        pob_src_dir=args.pob_src_dir,
        output_dir=args.output_dir,
        generated_uniques_dir=args.generated_uniques_dir,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "installed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
