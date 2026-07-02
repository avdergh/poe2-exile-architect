"""Generate the current Phase 2 physical-graph acceptance artifact.

This script intentionally uses a tiny deterministic in-repo fixture so it can
run offline and produce a stable acceptance JSON artifact for human review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


OUTPUT_PATH = REPO_ROOT / "phase2_acceptance_artifact.json"
REPORT_PATH = REPO_ROOT / "phase2_acceptance_report.md"

REQUIRED_COVERAGE = (
    ("gem -> active skill", "gem_grants_skill"),
    ("skill weapon hard constraint", "skill_weapon_requirement"),
    ("support candidate vs hard compatibility", "support_skill_candidate"),
    ("gem/support requirement fact", "requirements_for_component"),
    ("gem/support resource fact", "resource_profile_for_component"),
    ("socket/support hard constraint", "socket_support_legality"),
    ("base item + item level -> mod availability", "can_roll_mod"),
    ("unique -> base item", "unique_base_item"),
    ("passive -> official ID", "id_mapping_supported"),
    ("passive connected_to source provenance", "edge_provenance"),
    ("weapon set allocation overlay", "passive_allocation_overlay"),
    ("passive choice / allocation option", "passive_allocation_options"),
    ("ambiguous alias", "resolver_ambiguous_alias"),
    ("missing node", "resolver_missing_node"),
    ("unsupported official ID", "id_mapping_unsupported"),
    ("skill/support .build ID resolver", "build_resolver_skill_support"),
    ("modelability caveat component set", "caveat_component_set"),
)


def _fixture_source():
    from server.knowledge import physical_graph as pg

    return pg.GraphSource(
        source_id="fixture:phase2",
        kind="fixture",
        source_file="scripts/run_phase2_acceptance_artifact.py",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
        expected_count=12,
    )


def _inventory_source():
    from server.knowledge import physical_graph as pg

    return pg.GraphSource(
        source_id="ggg:developer_docs:inventories",
        kind="official_docs_fixture",
        source_file="data/raw/official/inventories.min.json",
        source_url="https://www.pathofexile.com/developer/docs/game",
        claims=(
            pg.SourceClaim("build_planner_field", "BuildInventorySlot.inventory_id"),
            pg.SourceClaim("source_scope", "official_doc_examples"),
        ),
        expected_count=2,
        confidence=0.85,
    )


def build_artifact(*, default_review_grade: str | None = None) -> dict[str, object]:
    from server.knowledge import physical_graph as pg

    snapshot, fixture_keys = build_snapshot_fixture_with_keys()
    return pg.build_phase2_acceptance_artifact(
        snapshot=snapshot,
        gem_key=fixture_keys["gem_key"],
        skill_key=fixture_keys["skill_key"],
        support_key=fixture_keys["support_key"],
        passive_key=fixture_keys["passive_key"],
        unique_key=fixture_keys["unique_key"],
        caveat_key=fixture_keys["caveat_key"],
        default_review_grade=default_review_grade,
    )


def build_snapshot_fixture():
    snapshot, _fixture_keys = build_snapshot_fixture_with_keys()
    return snapshot


def build_snapshot_fixture_with_keys():
    from server.knowledge import physical_graph as pg

    source = _fixture_source()
    inventory_source = _inventory_source()
    inventory_ingestion = pg.ingest_inventory_slots(
        REPO_ROOT / "data/raw/official/inventories.min.json",
        source=inventory_source,
    )
    gem = pg.GraphNode(
        stable_key="gem:Metadata/Items/Gems/SkillGemLightningArrow",
        node_type="skill_gem",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    support = pg.GraphNode(
        stable_key="support:Metadata/Items/Gems/SupportGemPierce",
        node_type="support_gem",
        display_name="Pierce",
        source_refs=(source.source_id,),
    )
    skill = pg.GraphNode(
        stable_key="skill:LightningArrowPlayer",
        node_type="active_skill",
        display_name="Lightning Arrow",
        source_refs=(source.source_id,),
    )
    weapon = pg.GraphNode(
        stable_key="weapon_type:bow",
        node_type="weapon_type",
        display_name="Bow",
        source_refs=(source.source_id,),
    )
    passive = pg.GraphNode(
        stable_key="passive:pob:0_5:100",
        node_type="passive",
        display_name="Attribute",
        source_refs=(source.source_id,),
    )
    passive_neighbor = pg.GraphNode(
        stable_key="passive:pob:0_5:101",
        node_type="passive",
        display_name="Path Node",
        source_refs=(source.source_id,),
    )
    caveat = pg.GraphNode(
        stable_key="caveat:dual_weapon_state_limited_caveat",
        node_type="caveat",
        display_name="dual_weapon_state_limited_caveat",
        source_refs=(source.source_id,),
    )
    unique = pg.GraphNode(
        stable_key="unique:pob:the_anvil",
        node_type="unique",
        display_name="The Anvil",
        source_refs=(source.source_id,),
    )
    base_item = pg.GraphNode(
        stable_key="item_base:Metadata/Items/Amulets/BloodstoneAmulet",
        node_type="item_base",
        display_name="Bloodstone Amulet",
        source_refs=(source.source_id,),
    )
    mod = pg.GraphNode(
        stable_key="mod:MovementSpeed1",
        node_type="mod",
        display_name="of Movement",
        source_refs=(source.source_id,),
    )
    item_tag = pg.GraphNode(
        stable_key="tag:item:default",
        node_type="item_tag",
        display_name="default",
        source_refs=(source.source_id,),
    )
    support_skill = pg.GraphNode(
        stable_key="skill:SupportPiercePlayer",
        node_type="active_skill",
        display_name="Support Pierce",
        source_refs=(source.source_id,),
    )
    projectile_type = pg.GraphNode(
        stable_key="skill_type:projectile",
        node_type="skill_type",
        display_name="Projectile",
        source_refs=(source.source_id,),
    )
    attack_type = pg.GraphNode(
        stable_key="skill_type:attack",
        node_type="skill_type",
        display_name="Attack",
        source_refs=(source.source_id,),
    )

    snapshot = pg.build_snapshot(
        sources=(source, inventory_source),
        nodes=(
            gem,
            support,
            skill,
            weapon,
            passive,
            passive_neighbor,
            caveat,
            unique,
            base_item,
            mod,
            item_tag,
            support_skill,
            projectile_type,
            attack_type,
        )
        + inventory_ingestion.nodes,
        edges=(
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=gem.stable_key,
                target_key=skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="grants_skill",
                source_key=support.stable_key,
                target_key=support_skill.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="granted_by",
                source_key=skill.stable_key,
                target_key=gem.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="connected_to",
                source_key=passive.stable_key,
                target_key=passive_neighbor.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_base",
                source_key=unique.stable_key,
                target_key=base_item.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_tag",
                source_key=base_item.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="applies_to_tag",
                source_key=mod.stable_key,
                target_key=item_tag.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="requires_weapon_type",
                source_key=skill.stable_key,
                target_key=weapon.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=projectile_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
            pg.GraphEdge(
                edge_type="has_type",
                source_key=skill.stable_key,
                target_key=attack_type.stable_key,
                evidence_refs=(source.source_id,),
            ),
        ),
        aliases=(
            pg.GraphAlias("Lightning Arrow", gem.stable_key, (source.source_id,)),
            pg.GraphAlias("Lightning Arrow", skill.stable_key, (source.source_id,)),
        ),
        id_mappings=(
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SkillGemLightningArrow",
                target_key=gem.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="repoe:gem_metadata",
                external_id="Metadata/Items/Gems/SupportGemPierce",
                target_key=support.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="pob:passive_skill_node_id",
                external_id="32183",
                target_key=passive.stable_key,
                source_refs=(source.source_id,),
            ),
            pg.GraphIdMapping(
                system="ggg:PassiveSkills",
                external_id="strength89",
                target_key=None,
                source_refs=(source.source_id,),
                status="unsupported",
                caveat="official_passive_string_id_not_vendored",
            ),
            pg.GraphIdMapping(
                system="ggg:Words:UniqueName",
                external_id="The Anvil",
                target_key=unique.stable_key,
                source_refs=(source.source_id,),
            ),
        )
        + inventory_ingestion.id_mappings,
        requirement_facts=(
            pg.RequirementFact(
                component_key=base_item.stable_key,
                level_or_stage="base",
                requirements={"domain": "item", "drop_level": 1},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=mod.stable_key,
                level_or_stage="base",
                requirements={
                    "domain": "item",
                    "required_level": 70,
                    "generation_type": "suffix",
                    "groups": ["MovementSpeed"],
                    "text": "increased Movement Speed",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=gem.stable_key,
                level_or_stage="base",
                requirements={"level": 1, "dex": 9},
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=support_skill.stable_key,
                level_or_stage="support_contract",
                requirements={
                    "allowed_types_expr": ["Projectile", "Attack", "AND"],
                    "excluded_types_expr": [],
                    "supports_gems_only": False,
                    "added_types": [],
                    "added_minion_types": [],
                    "support_family": "Pierce",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=skill.stable_key,
                level_or_stage="socket_context",
                requirements={
                    "max_support_count": 1,
                    "socketed_support_keys": [support.stable_key],
                    "socketed_support_families": ["Pierce"],
                    "duplicate_support_policy": "reject_same_support_key",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=caveat.stable_key,
                level_or_stage="component_set",
                requirements={
                    "component_keys": [passive.stable_key, skill.stable_key],
                    "trigger_condition": "weapon_set_passives_used_without_dual_state_scores",
                    "modelability_effect": "limited",
                    "reward_eligibility_effect": "limited",
                },
                source_refs=(source.source_id,),
            ),
            pg.RequirementFact(
                component_key=passive.stable_key,
                level_or_stage="weapon_set_overlay",
                requirements={
                    "allocation_states": ["weapon_set_1"],
                    "documented_weapon_set_indices": [0, 1, 2],
                    "weapon_set_point_conversion": 24,
                    "state_specific_reachability": True,
                },
                source_refs=(source.source_id,),
                status="ambiguous",
                confidence=0.5,
            ),
        )
        + inventory_ingestion.requirement_facts,
        resource_facts=(
            pg.ResourceFact(
                component_key=skill.stable_key,
                level_or_stage="1",
                costs={"mana": 6},
                reservations={},
                source_refs=(source.source_id,),
            ),
        ),
        passive_choices=(
            pg.PassiveChoice(
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                parent_passive_key=passive.stable_key,
                display_name="Attribute",
                source_refs=(source.source_id,),
            ),
        ),
        allocation_options=(
            pg.AllocationOption(
                option_key="allocation_option:passive:pob:0_5:100:26297",
                choice_key="passive_choice:passive:pob:0_5:100:32183",
                display_name="Strength",
                stat_text="+5 to Strength",
                source_refs=(source.source_id,),
            ),
        ),
    )
    return snapshot, {
        "gem_key": gem.stable_key,
        "skill_key": skill.stable_key,
        "support_key": support.stable_key,
        "passive_key": passive.stable_key,
        "unique_key": unique.stable_key,
        "caveat_key": caveat.stable_key,
    }


def render_markdown_report(artifact: dict[str, object]) -> str:
    bundle = artifact["bundle"]
    acceptance = artifact["acceptance_report"]
    assert isinstance(bundle, dict)
    assert isinstance(acceptance, dict)
    family_counts = bundle["family_counts"]
    assert isinstance(family_counts, dict)
    samples = bundle["samples"]
    assert isinstance(samples, list)
    review_counts = acceptance["review_counts"]
    assert isinstance(review_counts, dict)
    ready_for_exit = bool(acceptance["ready_for_phase2_exit"])
    exit_state = "可出关" if ready_for_exit else "待人工评分"

    lines = [
        "# Phase 2 E2E 样例人工验收报告",
        "",
        "## 摘要",
        "",
        f"- 样例总数：{bundle['sample_count']}",
        f"- Phase 2 出关状态：{exit_state}",
        f"- ready_for_human_review：{str(acceptance['ready_for_human_review']).lower()}",
        f"- ready_for_phase2_exit：{str(acceptance['ready_for_phase2_exit']).lower()}",
        "",
        "## 覆盖矩阵",
        "",
        "| 验收场景 | 状态 | family |",
        "| --- | --- | --- |",
    ]
    for label, family in REQUIRED_COVERAGE:
        status = "covered" if family_counts.get(family, 0) else "missing"
        lines.append(f"| {label} | {status} | {family} |")

    lines.extend(
        [
            "",
            "## 样例列表",
            "",
            "| # | family | status | caveat |",
            "| --- | --- | --- | --- |",
        ]
    )
    for index, sample in enumerate(samples, start=1):
        assert isinstance(sample, dict)
        result = sample.get("result", {})
        assert isinstance(result, dict)
        caveat = result.get("caveat") or ""
        lines.append(f"| {index} | {sample['family']} | {result.get('status', '')} | {caveat} |")

    lines.extend(["", "## 人工评分", ""])
    if review_counts:
        for grade, count in sorted(review_counts.items()):
            lines.append(f"- 已预填人工评分：{grade} x {count}")
    else:
        lines.append(
            "当前报告未预填人工评分。请按 pass / minor_issue / fail 审阅 JSON 样例结果后再出关。"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the Phase 2 physical-graph acceptance artifact."
    )
    parser.add_argument(
        "--default-review-grade",
        choices=("pass", "minor_issue", "fail"),
        default=None,
        help="Optionally prefill every sample with one human review grade.",
    )
    args = parser.parse_args()
    artifact = build_artifact(default_review_grade=args.default_review_grade)
    OUTPUT_PATH.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(render_markdown_report(artifact), encoding="utf-8")
    print(str(OUTPUT_PATH))
    print(str(REPORT_PATH))


if __name__ == "__main__":
    main()
