"""Assemble safe Phase 4 research context for Phase 5 Architect planning."""

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

from server.knowledge import copy_safety, mature_learning, research_memory  # noqa: E402

JSON_OUTPUT = REPO_ROOT / "phase4_architect_research_context_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_architect_research_context_report.md"
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


def build_architect_research_context_report(
    *,
    db_path: str | Path | None = None,
    query: str,
    component_keys: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    component_keys = sorted({str(key) for key in component_keys or [] if str(key).strip()})
    service = research_memory.ResearchMemoryService(db_path=Path(db_path) if db_path else None)
    retrieval = service.query_research_memory(query, component_keys=component_keys, limit=limit)
    fragment_ids = [
        str(result.get("fragmentId"))
        for result in retrieval.get("results", [])
        if result.get("fragmentId")
    ]
    con = mature_learning.connect(Path(db_path) if db_path else None)
    try:
        fragments = _dedupe_fragment_rows(_fragment_rows(con, fragment_ids))
        if not fragments and component_keys:
            fragments = _dedupe_fragment_rows(
                _fragment_rows_by_component_keys(con, component_keys, limit)
            )
        edge_scope_keys = component_keys or _component_keys_from_fragments(fragments)
        edges = _planner_visible_edges(con, edge_scope_keys) if edge_scope_keys else []
        patterns = _planner_visible_patterns(con, edge_scope_keys) if edge_scope_keys else []
        stale_edge_count = _stale_edge_count(con, edge_scope_keys) if edge_scope_keys else 0
        stale_pattern_count = _stale_pattern_count(con, edge_scope_keys) if edge_scope_keys else 0
    finally:
        con.close()

    research_fragments = [_fragment_context(row) for row in fragments]
    semantic_edges = [_edge_context(row) for row in edges]
    build_patterns = [_pattern_context(row) for row in patterns]
    used_fragment_ids = [item["fragmentId"] for item in research_fragments]
    used_edge_ids = [item["edgeId"] for item in semantic_edges]
    used_pattern_ids = [item["patternId"] for item in build_patterns]
    context_caveats = [
        "advisory_research_context_only_not_planner_legality",
        "judge_verification_required_before_numeric_claims",
    ]
    if stale_edge_count:
        context_caveats.append("stale_or_revalidation_edges_excluded")
    if stale_pattern_count:
        context_caveats.append("stale_or_revalidation_patterns_excluded")
    report = {
        "reportId": "phase4-architect-research-context-v1",
        "status": "ready_for_phase5_architect_context",
        "safeArtifactOnly": True,
        "queryRef": retrieval.get("dedupeQueryRef"),
        "queryPreview": _safe_text(query),
        "componentKeys": component_keys,
        "researchFragments": research_fragments,
        "semanticEdges": semantic_edges,
        "buildPatterns": build_patterns,
        "transitionGates": _transition_gates(research_fragments, semantic_edges, build_patterns),
        "modelabilityCaveats": _modelability_caveats(research_fragments, semantic_edges),
        "plannerHints": _planner_hints(build_patterns),
        "verificationTasks": _verification_tasks(
            research_fragments, semantic_edges, build_patterns
        ),
        "usedMemoryItemIds": used_fragment_ids,
        "usedFragmentIds": used_fragment_ids,
        "usedSemanticEdgeIds": used_edge_ids,
        "usedPatternIds": used_pattern_ids,
        "contextCaveats": context_caveats,
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_report(report)
    return report


def write_architect_research_context_report(
    *,
    db_path: str | Path | None = None,
    query: str,
    component_keys: list[str] | None = None,
    limit: int = 8,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_architect_research_context_report(
        db_path=db_path,
        query=query,
        component_keys=component_keys,
        limit=limit,
    )
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _fragment_rows(con: Any, fragment_ids: list[str]) -> list[Any]:
    if not fragment_ids:
        return []
    placeholders = ",".join("?" for _ in fragment_ids)
    rows = con.execute(
        f"""
        SELECT * FROM research_fragments
        WHERE fragment_id IN ({placeholders})
          AND visibility = 'creator_visible'
          AND split = 'train_context'
          AND status = 'valid'
          AND copy_safety_state = 'passed'
        ORDER BY fragment_id
        """,
        fragment_ids,
    ).fetchall()
    order = {fragment_id: index for index, fragment_id in enumerate(fragment_ids)}
    return sorted(rows, key=lambda row: order.get(row["fragment_id"], 9999))


def _fragment_rows_by_component_keys(con: Any, component_keys: list[str], limit: int) -> list[Any]:
    wanted = set(component_keys)
    rows = con.execute(
        """
        SELECT * FROM research_fragments
        WHERE visibility = 'creator_visible'
          AND split = 'train_context'
          AND status = 'valid'
          AND copy_safety_state = 'passed'
        ORDER BY last_seen_at DESC, fragment_id
        """
    ).fetchall()
    matched = [
        row
        for row in rows
        if wanted.intersection(set(_loads(row["component_keys"], [])))
        or wanted.intersection(set(_loads(row["affected_component_keys"], [])))
    ]
    return matched[:limit]


def _dedupe_fragment_rows(rows: list[Any]) -> list[Any]:
    deduped: list[Any] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for row in rows:
        component_keys = tuple(
            sorted(
                {
                    *(str(item) for item in _loads(row["component_keys"], [])),
                    *(str(item) for item in _loads(row["affected_component_keys"], [])),
                }
            )
        )
        if not component_keys:
            deduped.append(row)
            continue
        key = (str(row["fragment_type"]), component_keys)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _planner_visible_edges(con: Any, component_keys: list[str]) -> list[Any]:
    rows = con.execute(
        """
        SELECT * FROM research_semantic_edges
        WHERE visibility = 'creator_visible'
          AND split = 'train_context'
          AND status = 'valid'
          AND copy_safety_state = 'passed'
          AND planner_visible = 1
        ORDER BY edge_id
        """
    ).fetchall()
    if not component_keys:
        return rows
    wanted = set(component_keys)
    return [
        row
        for row in rows
        if row["source_key"] in wanted
        or row["target_key"] in wanted
        or wanted.intersection(set(_loads(row["affected_component_keys"], [])))
    ]


def _stale_edge_count(con: Any, component_keys: list[str]) -> int:
    rows = con.execute(
        """
        SELECT source_key, target_key, affected_component_keys
        FROM research_semantic_edges
        WHERE visibility = 'creator_visible'
          AND split = 'train_context'
          AND (status != 'valid' OR planner_visible = 0)
        """
    ).fetchall()
    if not component_keys:
        return len(rows)
    wanted = set(component_keys)
    return sum(
        1
        for row in rows
        if row["source_key"] in wanted
        or row["target_key"] in wanted
        or wanted.intersection(set(_loads(row["affected_component_keys"], [])))
    )


def _planner_visible_patterns(con: Any, component_keys: list[str]) -> list[Any]:
    rows = con.execute(
        """
        SELECT * FROM research_build_patterns
        WHERE visibility = 'creator_visible'
          AND split = 'train_context'
          AND status = 'valid'
          AND copy_safety_state = 'passed'
          AND planner_visible = 1
        ORDER BY pattern_id
        """
    ).fetchall()
    if not component_keys:
        return rows
    wanted = set(component_keys)
    return [row for row in rows if wanted.intersection(set(_loads(row["component_keys"], [])))]


def _stale_pattern_count(con: Any, component_keys: list[str]) -> int:
    rows = con.execute(
        """
        SELECT component_keys
        FROM research_build_patterns
        WHERE visibility = 'creator_visible'
          AND split = 'train_context'
          AND (status != 'valid' OR planner_visible = 0)
        """
    ).fetchall()
    if not component_keys:
        return len(rows)
    wanted = set(component_keys)
    return sum(1 for row in rows if wanted.intersection(set(_loads(row["component_keys"], []))))


def _fragment_context(row: Any) -> dict[str, Any]:
    return {
        "memoryItemId": _safe_text(row["fragment_id"]),
        "fragmentId": _safe_text(row["fragment_id"]),
        "fragmentType": _safe_text(row["fragment_type"]),
        "title": _safe_text(row["title"]),
        "summary": _safe_text(row["summary"]),
        "reusablePrinciple": _safe_text(row["reusable_principle"]),
        "componentKeys": [_safe_text(item) for item in _loads(row["component_keys"], [])],
        "conditions": [_safe_text(item) for item in _loads(row["conditions"], [])],
        "risks": [_safe_text(item) for item in _loads(row["risks"], [])],
        "verificationTasks": [_safe_text(item) for item in _loads(row["verification_tasks"], [])],
        "confidence": _safe_text(row["confidence"]),
        "modelability": _safe_text(row["modelability"]),
        "gamePatch": _safe_text(row["game_patch"]),
        "passiveTreeVersion": _safe_text(row["passive_tree_version"]),
        "status": _safe_text(row["status"]),
    }


def _edge_context(row: Any) -> dict[str, Any]:
    context_requirements = _loads(row["context_requirements"], [])
    return {
        "edgeId": _safe_text(row["edge_id"]),
        "sourceKey": _safe_text(row["source_key"]),
        "targetKey": _safe_text(row["target_key"]),
        "edgeType": _safe_text(row["edge_type"]),
        "rationale": _safe_text(row["rationale"]),
        "confidence": _safe_text(row["confidence"]),
        "modelability": _safe_text(row["modelability"]),
        "gamePatch": _safe_text(row["game_patch"]),
        "passiveTreeVersion": _safe_text(row["passive_tree_version"]),
        "pobVersionOrCommit": _safe_text(row["pob_version_or_commit"]),
        "currentVersionContext": _safe_json(_loads(row["current_version_context"], {})),
        "contextRequirements": _safe_json(context_requirements),
        "affectedComponentKeys": [
            _safe_text(item) for item in _loads(row["affected_component_keys"], [])
        ],
        "plannerVisible": bool(row["planner_visible"]),
        "status": _safe_text(row["status"]),
    }


def _pattern_context(row: Any) -> dict[str, Any]:
    return {
        "patternId": _safe_text(row["pattern_id"]),
        "patternType": _safe_text(row["pattern_type"]),
        "title": _safe_text(row["title"]),
        "summary": _safe_text(row["summary"]),
        "componentKeys": [_safe_text(item) for item in _loads(row["component_keys"], [])],
        "componentRoles": _safe_json(_loads(row["component_roles"], {})),
        "confidenceTier": _safe_text(row["confidence_tier"]),
        "sampleCount": int(row["sample_count"]),
        "familyCount": int(row["family_count"]),
        "sourceDiversityCount": int(row["source_diversity_count"]),
        "denominator": row["denominator"],
        "contextRequirements": _safe_json(_loads(row["context_requirements"], [])),
        "plannerHint": _safe_text(row["planner_hint"] or ""),
        "verificationTasks": [_safe_text(item) for item in _loads(row["verification_tasks"], [])],
        "gamePatch": _safe_text(row["game_patch"]),
        "passiveTreeVersion": _safe_text(row["passive_tree_version"]),
        "pobVersionOrCommit": _safe_text(row["pob_version_or_commit"]),
    }


def _component_keys_from_fragments(fragments: list[Any]) -> list[str]:
    keys: set[str] = set()
    for row in fragments:
        keys.update(str(item) for item in _loads(row["component_keys"], []))
    return sorted(keys)


def _transition_gates(
    fragments: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> list[str]:
    gates: list[str] = []
    for fragment in fragments:
        gates.extend(item for item in fragment.get("conditions", []) if "gate" in item.casefold())
    for edge in edges:
        if edge.get("edgeType") == "requires_transition_gate":
            gates.append(str(edge.get("rationale")))
    for pattern in patterns:
        if pattern.get("patternType") == "transition_gate":
            gates.append(str(pattern.get("summary") or pattern.get("title") or ""))
    return _unique_safe(gates)


def _modelability_caveats(
    fragments: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[str]:
    caveats: list[str] = []
    for fragment in fragments:
        if fragment.get("modelability") != "full":
            caveats.append(f"fragment:{fragment['fragmentId']}:{fragment.get('modelability')}")
    for edge in edges:
        if edge.get("modelability") != "full" or edge.get("edgeType") == "has_modelability_caveat":
            caveats.append(f"edge:{edge['edgeId']}:{edge.get('modelability')}")
    return _unique_safe(caveats)


def _verification_tasks(
    fragments: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> list[str]:
    tasks: list[str] = []
    for fragment in fragments:
        tasks.extend(fragment.get("verificationTasks", []))
    for edge in edges:
        for requirement in edge.get("contextRequirements", []):
            if (
                isinstance(requirement, dict)
                and requirement.get("context_type") == "verification_gate_requirement"
            ):
                tasks.append(str(requirement.get("task") or ""))
    for pattern in patterns:
        tasks.extend(pattern.get("verificationTasks", []))
    return _unique_safe(tasks)


def _planner_hints(patterns: list[dict[str, Any]]) -> list[str]:
    return _unique_safe([str(pattern.get("plannerHint") or "") for pattern in patterns])


def _unique_safe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        safe = _safe_text(value)
        if safe and safe not in seen:
            seen.add(safe)
            out.append(safe)
    return out


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


def _safe_text(value: Any) -> str:
    text = " ".join(str(value or "").split())[:320]
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


def _loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4 Architect Research Context",
        "",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Used fragments: `{len(report['usedFragmentIds'])}`",
        f"- Used semantic edges: `{len(report['usedSemanticEdgeIds'])}`",
        f"- Used build patterns: `{len(report['usedPatternIds'])}`",
        "",
        "## Fragments",
        "",
    ]
    for fragment in report["researchFragments"]:
        lines.append(f"- `{fragment['fragmentId']}`: {fragment['title']}")
    lines.extend(["", "## Semantic Edges", ""])
    for edge in report["semanticEdges"]:
        lines.append(f"- `{edge['edgeId']}`: `{edge['edgeType']}`")
    lines.extend(["", "## Build Patterns", ""])
    for pattern in report["buildPatterns"]:
        lines.append(
            "- "
            f"`{pattern['patternId']}`: {pattern['title']} "
            f"(`{pattern['patternType']}`, `{pattern['confidenceTier']}`, "
            f"samples `{pattern['sampleCount']}`)"
        )
    lines.extend(["", "## Planner Hints", ""])
    for hint in report["plannerHints"]:
        lines.append(f"- {hint}")
    lines.extend(["", "## Verification Tasks", ""])
    for task in report["verificationTasks"]:
        lines.append(f"- {task}")
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report["contextCaveats"])
    lines.append("")
    text = "\n".join(lines)
    for marker in RAW_MARKERS:
        if marker in text:
            raise ValueError(f"unsafe markdown marker detected: {marker}")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--query", required=True)
    parser.add_argument("--component-key", action="append", default=[])
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    report = write_architect_research_context_report(
        db_path=Path(args.db_path) if args.db_path else None,
        query=args.query,
        component_keys=list(args.component_key or []),
        limit=args.limit,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return (
        0
        if report["researchFragments"] or report["semanticEdges"] or report["buildPatterns"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
