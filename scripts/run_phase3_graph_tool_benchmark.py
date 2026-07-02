"""Generate the Phase 3 typed graph tool deterministic benchmark artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


OUTPUT_PATH = REPO_ROOT / "phase3_graph_tool_benchmark.json"
REPORT_PATH = REPO_ROOT / "phase3_graph_tool_benchmark.md"
TOPOLOGY_LIMITS = {
    "max_tool_calls": 1,
    "max_hops": 6,
    "max_nodes": 200,
    "max_payload_bytes": 65536,
}


def build_benchmark(*, default_review_grade: str | None = None) -> dict[str, Any]:
    from scripts import run_phase2_acceptance_artifact as phase2
    from server.knowledge import graph_tools as gt

    snapshot = _snapshot_with_benchmark_support_negatives(phase2.build_snapshot_fixture())
    service = gt.GraphQueryService.from_snapshot(snapshot)
    cases = _benchmark_cases()
    samples = []
    status_matches = 0
    fact_mismatches = 0
    provenance_complete = 0
    structured_returns = 0
    hallucinated_compatibility_count = 0
    topology_limit_failures = []

    for case in cases:
        result = service.run_tool(str(case["tool_name"]), dict(case["payload"]))
        expected_status = str(case["expected_status"])
        status_match = result["status"] == expected_status
        if status_match:
            status_matches += 1
        expected_candidate_status = case.get("expected_candidate_status")
        fact_match = True
        if expected_candidate_status is not None:
            fact_match = (
                result.get("facts", {}).get("candidate_status") == expected_candidate_status
            )
            if not fact_match:
                fact_mismatches += 1
        if _requires_provenance(result["status"]) and result["sourceRefs"]:
            provenance_complete += 1
        if result["status"] in {"missing_context", "ambiguous", "unsupported", "unknown"}:
            structured_returns += 1
        if case.get("checks_no_hard_compatibility") and (
            result.get("facts", {}).get("candidate_status") == "hard_compatible"
        ):
            hallucinated_compatibility_count += 1
        if case["tool_name"] in {"find_passive_topology_path", "get_passive_subgraph_in_radius"}:
            payload_bytes = len(
                json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
            )
            if payload_bytes > TOPOLOGY_LIMITS["max_payload_bytes"]:
                topology_limit_failures.append(f"{case['id']}: payload bytes {payload_bytes}")
            if result.get("facts", {}).get("node_count", 0) > TOPOLOGY_LIMITS["max_nodes"]:
                topology_limit_failures.append(f"{case['id']}: node limit exceeded")
            hop_count = result.get("facts", {}).get("hop_count")
            if isinstance(hop_count, int) and hop_count > TOPOLOGY_LIMITS["max_hops"]:
                topology_limit_failures.append(f"{case['id']}: hop limit exceeded")
        sample = {
            "id": case["id"],
            "tool_name": case["tool_name"],
            "expected_status": expected_status,
            "status_match": status_match,
            "fact_match": fact_match,
            "result": result,
        }
        if expected_candidate_status is not None:
            sample["expected_candidate_status"] = expected_candidate_status
        if default_review_grade is not None:
            sample["review"] = {"grade": default_review_grade}
        samples.append(sample)

    status_counts: dict[str, int] = {}
    for sample in samples:
        status = str(sample["result"]["status"])
        status_counts[status] = status_counts.get(status, 0) + 1

    provenance_required = sum(
        1 for sample in samples if _requires_provenance(str(sample["result"]["status"]))
    )
    structured_required = sum(
        1
        for sample in samples
        if sample["result"]["status"] in {"missing_context", "ambiguous", "unsupported", "unknown"}
    )
    review_counts: dict[str, int] = {}
    for sample in samples:
        review = sample.get("review")
        if isinstance(review, dict):
            grade = str(review.get("grade", ""))
            if grade:
                review_counts[grade] = review_counts.get(grade, 0) + 1

    pass_fail = (
        status_matches == len(samples)
        and (provenance_required == 0 or provenance_complete == provenance_required)
        and (structured_required == 0 or structured_returns == structured_required)
        and fact_mismatches == 0
        and hallucinated_compatibility_count == 0
        and not topology_limit_failures
    )
    return {
        "benchmark_id": "phase3_typed_graph_tools_v1",
        "snapshot_id": snapshot.snapshot_id,
        "tool_families_covered": sorted({str(case["tool_name"]) for case in cases}),
        "case_counts_by_status": dict(sorted(status_counts.items())),
        "expected_status_match_rate": status_matches / len(samples),
        "provenance_completeness_rate": (
            1.0 if provenance_required == 0 else provenance_complete / provenance_required
        ),
        "hallucinated_compatibility_count": hallucinated_compatibility_count,
        "fact_mismatch_count": fact_mismatches,
        "structured_return_rate": (
            1.0 if structured_required == 0 else structured_returns / structured_required
        ),
        "topology_macro_limits": TOPOLOGY_LIMITS,
        "topology_limit_failures": topology_limit_failures,
        "pass": pass_fail,
        "review_counts": dict(sorted(review_counts.items())),
        "ready_for_human_review": pass_fail and review_counts.get("fail", 0) == 0,
        "ready_for_phase3_exit": pass_fail
        and len(samples) > 0
        and review_counts.get("pass", 0) == len(samples),
        "samples": samples,
    }


def render_markdown_report(artifact: dict[str, Any]) -> str:
    exit_state = "可人工验收" if artifact["pass"] else "未通过"
    lines = [
        "# Phase 3 Typed Graph Tool Benchmark",
        "",
        "## 摘要",
        "",
        f"- benchmark id：{artifact['benchmark_id']}",
        f"- snapshot id：{artifact['snapshot_id']}",
        f"- 样例总数：{len(artifact['samples'])}",
        f"- benchmark 状态：{exit_state}",
        f"- expected_status_match_rate：{artifact['expected_status_match_rate']:.2f}",
        f"- provenance_completeness_rate：{artifact['provenance_completeness_rate']:.2f}",
        f"- structured_return_rate：{artifact['structured_return_rate']:.2f}",
        f"- hallucinated_compatibility_count：{artifact['hallucinated_compatibility_count']}",
        "",
        "## 样例列表",
        "",
        "| # | tool | expected | actual | status match | caveats |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for index, sample in enumerate(artifact["samples"], start=1):
        caveats = ", ".join(sample["result"].get("caveats", []))
        lines.append(
            "| "
            f"{index} | {sample['tool_name']} | {sample['expected_status']} | "
            f"{sample['result']['status']} | {str(sample['status_match']).lower()} | {caveats} |"
        )
    lines.extend(["", "## 人工评分", ""])
    review_counts = artifact["review_counts"]
    if review_counts:
        for grade, count in review_counts.items():
            lines.append(f"- 已预填人工评分：{grade} x {count}")
    else:
        lines.append("当前报告未预填人工评分。请按 pass / minor_issue / fail 审阅 JSON 样例结果。")
    lines.append("")
    return "\n".join(lines)


def _benchmark_cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "resolve_ambiguous_alias",
            "tool_name": "resolve_graph_component",
            "payload": {"query": "Lightning Arrow"},
            "expected_status": "ambiguous",
        },
        {
            "id": "requirements_known",
            "tool_name": "requirements_for_component",
            "payload": {
                "component_key": "gem:Metadata/Items/Gems/SkillGemLightningArrow",
                "level_or_stage": "base",
            },
            "expected_status": "known",
        },
        {
            "id": "resource_known",
            "tool_name": "resource_profile_for_component",
            "payload": {"component_key": "skill:LightningArrowPlayer", "level_or_stage": "1"},
            "expected_status": "known",
        },
        {
            "id": "resource_unknown_stage",
            "tool_name": "resource_profile_for_component",
            "payload": {"component_key": "skill:LightningArrowPlayer", "level_or_stage": "999"},
            "expected_status": "unknown",
        },
        {
            "id": "requirements_stale_context",
            "tool_name": "requirements_for_component",
            "payload": {
                "component_key": "gem:Metadata/Items/Gems/SkillGemLightningArrow",
                "level_or_stage": "base",
                "context": {
                    "context_type": "version_context",
                    "passive_tree_version": "wrong_version",
                },
            },
            "expected_status": "stale",
        },
        {
            "id": "socket_missing_context",
            "tool_name": "socket_support_legality",
            "payload": {
                "skill_key": "skill:LightningArrowPlayer",
                "support_key": "support:Metadata/Items/Gems/SupportGemPierce",
            },
            "expected_status": "missing_context",
        },
        {
            "id": "socket_known",
            "tool_name": "socket_support_legality",
            "payload": {
                "skill_key": "skill:LightningArrowPlayer",
                "support_key": "support:Metadata/Items/Gems/SupportGemPierce",
                "context": {
                    "context_type": "socket_context",
                    "socketed_support_keys": [],
                    "socketed_support_families": [],
                    "current_support_count": 0,
                    "max_support_count": 2,
                },
            },
            "expected_status": "known",
        },
        {
            "id": "can_roll_missing_context",
            "tool_name": "can_roll_mod",
            "payload": {
                "base_item_key": "item_base:Metadata/Items/Amulets/BloodstoneAmulet",
                "mod_key": "mod:MovementSpeed1",
            },
            "expected_status": "missing_context",
        },
        {
            "id": "can_roll_known",
            "tool_name": "can_roll_mod",
            "payload": {
                "base_item_key": "item_base:Metadata/Items/Amulets/BloodstoneAmulet",
                "mod_key": "mod:MovementSpeed1",
                "context": {"context_type": "item_context", "item_level": 70},
            },
            "expected_status": "known",
        },
        {
            "id": "support_candidate_known",
            "tool_name": "support_skill_candidate",
            "payload": {
                "support_key": "support:Metadata/Items/Gems/SupportGemPierce",
                "skill_key": "skill:LightningArrowPlayer",
            },
            "expected_status": "known",
            "checks_no_hard_compatibility": False,
        },
        {
            "id": "support_candidate_unsupported",
            "tool_name": "support_skill_candidate",
            "payload": {
                "support_key": "support:Metadata/Items/Gems/SupportGemPierce",
                "skill_key": "skill:BenchmarkSpellOnly",
            },
            "expected_status": "unsupported",
            "expected_candidate_status": "unsupported",
            "checks_no_hard_compatibility": True,
        },
        {
            "id": "support_candidate_recommended",
            "tool_name": "support_skill_candidate",
            "payload": {
                "support_key": "support:Metadata/Items/Gems/SupportGemPierce",
                "skill_key": "skill:BenchmarkRecommendedProjectileAttack",
            },
            "expected_status": "known",
            "expected_candidate_status": "recommended",
            "checks_no_hard_compatibility": True,
        },
        {
            "id": "support_candidate_missing_contract",
            "tool_name": "support_skill_candidate",
            "payload": {
                "support_key": "support:BenchmarkMissingContract",
                "skill_key": "skill:LightningArrowPlayer",
            },
            "expected_status": "error",
            "checks_no_hard_compatibility": True,
        },
        {
            "id": "passive_path_known",
            "tool_name": "find_passive_topology_path",
            "payload": {
                "start_key": "passive:pob:0_5:100",
                "end_key": "passive:pob:0_5:101",
                "context": {"context_type": "passive_context", "active_weapon_set": 1},
            },
            "expected_status": "known",
        },
        {
            "id": "passive_subgraph_known",
            "tool_name": "get_passive_subgraph_in_radius",
            "payload": {
                "node_key": "passive:pob:0_5:100",
                "hop_limit": 6,
                "node_limit": 200,
                "context": {"context_type": "passive_context", "active_weapon_set": 1},
            },
            "expected_status": "known",
        },
        {
            "id": "id_mapping_unsupported",
            "tool_name": "build_planner_id_resolve",
            "payload": {"system": "ggg:PassiveSkills", "external_id": "strength89"},
            "expected_status": "unsupported",
        },
        {
            "id": "raw_query_rejected",
            "tool_name": "resolve_graph_component",
            "payload": {"query": "Lightning Arrow", "sql": "select * from graph"},
            "expected_status": "error",
        },
    ]


def _snapshot_with_benchmark_support_negatives(snapshot):
    from server.knowledge import physical_graph as pg

    source_id = snapshot.sources[0].source_id
    benchmark_nodes = (
        pg.GraphNode(
            stable_key="skill:BenchmarkSpellOnly",
            node_type="active_skill",
            display_name="Benchmark Spell Only",
            source_refs=(source_id,),
        ),
        pg.GraphNode(
            stable_key="skill_type:spell",
            node_type="skill_type",
            display_name="Spell",
            source_refs=(source_id,),
        ),
        pg.GraphNode(
            stable_key="gem:BenchmarkRecommendedProjectileAttack",
            node_type="skill_gem",
            display_name="Benchmark Recommended Projectile Attack",
            source_refs=(source_id,),
        ),
        pg.GraphNode(
            stable_key="skill:BenchmarkRecommendedProjectileAttack",
            node_type="active_skill",
            display_name="Benchmark Recommended Projectile Attack",
            source_refs=(source_id,),
        ),
        pg.GraphNode(
            stable_key="support:BenchmarkMissingContract",
            node_type="support_gem",
            display_name="Benchmark Missing Contract Support",
            source_refs=(source_id,),
        ),
        pg.GraphNode(
            stable_key="skill:BenchmarkMissingContractSupport",
            node_type="active_skill",
            display_name="Benchmark Missing Contract Support Skill",
            source_refs=(source_id,),
        ),
    )
    benchmark_edges = (
        pg.GraphEdge(
            edge_type="has_type",
            source_key="skill:BenchmarkSpellOnly",
            target_key="skill_type:spell",
            evidence_refs=(source_id,),
        ),
        pg.GraphEdge(
            edge_type="grants_skill",
            source_key="gem:BenchmarkRecommendedProjectileAttack",
            target_key="skill:BenchmarkRecommendedProjectileAttack",
            evidence_refs=(source_id,),
        ),
        pg.GraphEdge(
            edge_type="granted_by",
            source_key="skill:BenchmarkRecommendedProjectileAttack",
            target_key="gem:BenchmarkRecommendedProjectileAttack",
            evidence_refs=(source_id,),
        ),
        pg.GraphEdge(
            edge_type="has_type",
            source_key="skill:BenchmarkRecommendedProjectileAttack",
            target_key="skill_type:projectile",
            evidence_refs=(source_id,),
        ),
        pg.GraphEdge(
            edge_type="has_type",
            source_key="skill:BenchmarkRecommendedProjectileAttack",
            target_key="skill_type:attack",
            evidence_refs=(source_id,),
        ),
        pg.GraphEdge(
            edge_type="recommended_for",
            source_key="support:Metadata/Items/Gems/SupportGemPierce",
            target_key="gem:BenchmarkRecommendedProjectileAttack",
            evidence_refs=(source_id,),
        ),
        pg.GraphEdge(
            edge_type="grants_skill",
            source_key="support:BenchmarkMissingContract",
            target_key="skill:BenchmarkMissingContractSupport",
            evidence_refs=(source_id,),
        ),
    )
    return pg.GraphSnapshot(
        snapshot_id=snapshot.snapshot_id,
        created_at=snapshot.created_at,
        sources=snapshot.sources,
        nodes=snapshot.nodes + benchmark_nodes,
        edges=snapshot.edges + benchmark_edges,
        aliases=snapshot.aliases,
        id_mappings=snapshot.id_mappings,
        capabilities=snapshot.capabilities,
        requirement_facts=snapshot.requirement_facts,
        resource_facts=snapshot.resource_facts,
        passive_choices=snapshot.passive_choices,
        allocation_options=snapshot.allocation_options,
        computed_results=snapshot.computed_results,
    )


def _requires_provenance(status: str) -> bool:
    return status in {"known", "ambiguous", "unsupported"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the Phase 3 typed graph tool benchmark artifact."
    )
    parser.add_argument(
        "--default-review-grade",
        choices=("pass", "minor_issue", "fail"),
        default=None,
        help="Optionally prefill every sample with one human review grade.",
    )
    args = parser.parse_args()
    artifact = build_benchmark(default_review_grade=args.default_review_grade)
    OUTPUT_PATH.write_bytes(json.dumps(artifact, ensure_ascii=False, indent=2).encode("utf-8"))
    REPORT_PATH.write_bytes(render_markdown_report(artifact).encode("utf-8"))
    print(str(OUTPUT_PATH))
    print(str(REPORT_PATH))


if __name__ == "__main__":
    main()
