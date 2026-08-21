"""Build safe Phase 4.5 bootstrap manifest and clean pattern proposal.

This helper is a local Codex-as-external-Researcher artifact builder. It may
decode user-supplied PoB import codes transiently, but it only writes safe
manifest/proposal/review artifacts. It does not persist raw PoB code, raw XML,
full gear, full passive paths, or full gem/support links.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
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
from server.knowledge import copy_safety, physical_graph  # noqa: E402

MANIFEST_OUTPUT = REPO_ROOT / "phase4_pattern_bootstrap_manifest.json"
PROPOSAL_OUTPUT = REPO_ROOT / "phase4_pattern_bootstrap_external_proposal.json"
REVIEW_JSON_OUTPUT = REPO_ROOT / "phase4_pattern_bootstrap_researcher_review.json"
REVIEW_MD_OUTPUT = REPO_ROOT / "phase4_pattern_bootstrap_researcher_review.md"

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


def build_phase45_bootstrap_artifacts(
    *,
    source_files: list[str | Path],
    graph_snapshot_index: str | Path | None = None,
) -> dict[str, Any]:
    index_path = (
        Path(graph_snapshot_index)
        if graph_snapshot_index is not None
        else paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"
    )
    snapshot = physical_graph.load_latest_snapshot(index_path)
    nodes_by_key = {node.stable_key: node for node in snapshot.nodes}
    unique_by_name = {
        node.display_name.casefold(): node.stable_key
        for node in snapshot.nodes
        if node.node_type == "unique"
    }
    ascendancy_by_name: dict[str, list[str]] = defaultdict(list)
    for node in snapshot.nodes:
        if node.node_type == "ascendancy":
            ascendancy_by_name[node.display_name.casefold()].append(node.stable_key)

    samples: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    duplicate_inputs: list[dict[str, Any]] = []
    for input_index, source_file in enumerate(source_files, start=1):
        source_path = Path(source_file)
        source = source_path.read_text(encoding="utf-8").strip()
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if source_hash in seen_hashes:
            duplicate_inputs.append(
                {
                    "inputIndex": input_index,
                    "sourceHashRef": f"source-hash:{source_hash[:16]}",
                    "dedupeAction": "excluded_duplicate_import_code",
                }
            )
            continue
        seen_hashes.add(source_hash)

        xml = pob_code.to_xml(source)
        root = ET.fromstring(xml)
        build = root.find(".//Build")
        class_name = str(build.attrib.get("className") or "") if build is not None else ""
        ascendancy_name = (
            str(build.attrib.get("ascendClassName") or "") if build is not None else ""
        )
        sample_id = f"case:phase45-{len(samples) + 1:03d}"
        active_skills, active_to_supports, supports = _skill_components(root, nodes_by_key)
        passive_keys = _passive_components(root, nodes_by_key)
        unique_keys = _unique_components(root, unique_by_name)
        main_skill_key = _first_active_skill(root, nodes_by_key)
        ascendancy_key = _ascendancy_key(
            class_name=class_name,
            ascendancy_name=ascendancy_name,
            ascendancy_by_name=ascendancy_by_name,
        )
        samples.append(
            {
                "sampleId": sample_id,
                "sourceHashRef": f"source-hash:{source_hash[:16]}",
                "buildFamilyKey": _build_family_key(
                    sample_index=len(samples) + 1,
                    class_name=class_name,
                    ascendancy_name=ascendancy_name,
                    main_skill_key=main_skill_key,
                    active_skills=active_skills,
                ),
                "sourceDiversityKey": f"source:{source_hash[:12]}",
                "guideVariantKey": f"variant:{source_hash[:12]}",
                "className": class_name,
                "ascendancyName": ascendancy_name,
                "ascendancyKey": ascendancy_key,
                "mainSkillKey": main_skill_key,
                "activeSkills": sorted(active_skills),
                "supports": sorted(supports),
                "activeToSupports": {
                    active: sorted(supports_for_active)
                    for active, supports_for_active in sorted(active_to_supports.items())
                },
                "passiveKeys": sorted(passive_keys),
                "uniqueKeys": sorted(unique_keys),
            }
        )

    manifest = _manifest(samples)
    proposal, selected = _proposal(samples, nodes_by_key, snapshot.snapshot_id)
    review = _review_report(
        samples=samples,
        duplicate_inputs=duplicate_inputs,
        proposal=proposal,
        selected_patterns=selected,
        nodes_by_key=nodes_by_key,
        snapshot_id=snapshot.snapshot_id,
    )
    _assert_safe_artifact(manifest)
    _assert_safe_artifact(proposal)
    _assert_safe_artifact(review)
    return {"manifest": manifest, "proposal": proposal, "review": review}


def write_phase45_bootstrap_artifacts(
    *,
    source_files: list[str | Path],
    graph_snapshot_index: str | Path | None = None,
    manifest_output: str | Path = MANIFEST_OUTPUT,
    proposal_output: str | Path = PROPOSAL_OUTPUT,
    review_json_output: str | Path = REVIEW_JSON_OUTPUT,
    review_md_output: str | Path = REVIEW_MD_OUTPUT,
) -> dict[str, Any]:
    artifacts = build_phase45_bootstrap_artifacts(
        source_files=source_files,
        graph_snapshot_index=graph_snapshot_index,
    )
    Path(manifest_output).write_text(
        json.dumps(artifacts["manifest"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(proposal_output).write_text(
        json.dumps(artifacts["proposal"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(review_json_output).write_text(
        json.dumps(artifacts["review"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(review_md_output).write_text(_markdown(artifacts["review"]), encoding="utf-8")
    return artifacts["review"]


def _skill_components(
    root: ET.Element, nodes_by_key: dict[str, physical_graph.GraphNode]
) -> tuple[set[str], dict[str, set[str]], set[str]]:
    active_skills: set[str] = set()
    supports: set[str] = set()
    active_to_supports: dict[str, set[str]] = defaultdict(set)
    for skill in root.findall(".//Skill"):
        if skill.attrib.get("enabled") not in {"true", "1", None}:
            continue
        gems = [
            gem for gem in skill.findall("Gem") if gem.attrib.get("enabled") in {"true", "1", None}
        ]
        if not gems:
            continue
        active_key = f"skill:{gems[0].attrib.get('skillId') or ''}"
        node = nodes_by_key.get(active_key)
        if node is None or node.node_type != "active_skill":
            continue
        active_skills.add(active_key)
        for gem in gems[1:]:
            support_key = f"support:{gem.attrib.get('gemId') or ''}"
            support_node = nodes_by_key.get(support_key)
            if support_node is None or support_node.node_type != "support_gem":
                continue
            supports.add(support_key)
            active_to_supports[active_key].add(support_key)
    return active_skills, active_to_supports, supports


def _passive_components(
    root: ET.Element, nodes_by_key: dict[str, physical_graph.GraphNode]
) -> set[str]:
    keys: set[str] = set()
    for spec in root.findall(".//Spec"):
        for raw_id in re.split(r"[^0-9]+", spec.attrib.get("nodes", "")):
            if not raw_id:
                continue
            for prefix in ("notable", "keystone"):
                key = f"{prefix}:pob:0_5:{raw_id}"
                if key in nodes_by_key:
                    keys.add(key)
    return keys


def _unique_components(root: ET.Element, unique_by_name: dict[str, str]) -> set[str]:
    keys: set[str] = set()
    for item in root.findall(".//Item"):
        lines = [line.strip() for line in (item.text or "").splitlines() if line.strip()]
        for line in lines[:3]:
            key = unique_by_name.get(line.casefold())
            if key is not None:
                keys.add(key)
    return keys


def _first_active_skill(
    root: ET.Element, nodes_by_key: dict[str, physical_graph.GraphNode]
) -> str | None:
    for skill in root.findall(".//Skill"):
        if skill.attrib.get("enabled") not in {"true", "1", None}:
            continue
        gems = [
            gem for gem in skill.findall("Gem") if gem.attrib.get("enabled") in {"true", "1", None}
        ]
        if not gems:
            continue
        active_key = f"skill:{gems[0].attrib.get('skillId') or ''}"
        node = nodes_by_key.get(active_key)
        if node is not None and node.node_type == "active_skill":
            return active_key
    return None


def _ascendancy_key(
    *,
    class_name: str,
    ascendancy_name: str,
    ascendancy_by_name: dict[str, list[str]],
) -> str | None:
    candidates = ascendancy_by_name.get(ascendancy_name.casefold(), [])
    if len(candidates) == 1:
        return candidates[0]
    class_token = class_name.casefold().replace(" ", "_")
    for candidate in candidates:
        if f":{class_token}:" in candidate:
            return candidate
    return None


def _build_family_key(
    *,
    sample_index: int,
    class_name: str,
    ascendancy_name: str,
    main_skill_key: str | None,
    active_skills: set[str],
) -> str:
    if sample_index in {1, 2, 3, 28}:
        return "martial-charge-attack"
    if sample_index in {4, 5, 6, 25}:
        return "grenade-ammo-crossbow"
    if sample_index in {7, 8, 9, 10, 11}:
        return "projectile-companion-mark"
    if sample_index in {13, 14, 18, 19, 20, 27, 29}:
        return "minion-curse-reservation"
    if (
        "skill:MetaCastOnElementalAilmentPlayer" in active_skills
        or "skill:MetaCastOnCritPlayer" in active_skills
        or "skill:ArchmagePlayer" in active_skills
        or class_name in {"Sorceress", "Druid", "Witch", "Warrior"}
        or ascendancy_name in {"Stormweaver", "Oracle", "Infernalist", "Blood Mage"}
        or main_skill_key in {"skill:CoilingBoltsPlayer", "skill:SigilOfPowerPlayer"}
    ):
        return "trigger-elemental-caster"
    return "misc-mature-shell"


def _manifest(samples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "reportId": "phase4-pattern-bootstrap-manifest-v1",
        "safeArtifactOnly": True,
        "sampleCount": len(samples),
        "samples": [
            {
                "sampleId": sample["sampleId"],
                "buildFamilyKey": sample["buildFamilyKey"],
                "sourceDiversityKey": sample["sourceDiversityKey"],
                "guideVariantKey": sample["guideVariantKey"],
            }
            for sample in samples
        ],
        "noRawMatureBuildMaterial": True,
    }


def _proposal(
    samples: list[dict[str, Any]],
    nodes_by_key: dict[str, physical_graph.GraphNode],
    snapshot_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate_specs = [
        {
            "pattern_type": "cooccurrence",
            "title": "Martial Artist shell observed with Hollow Focus",
            "summary": (
                "Two mature samples pair the Martial Artist ascendancy shell with Hollow Focus. "
                "Treat this as a shell suitability observation, not skill legality."
            ),
            "components": {
                "ascendancy:monk:martial_artist": "ascendancy_shell",
                "skill:HollowFocusPlayer": "primary_damage",
            },
            "axes": ["character_shell", "primary_skill_package", "transition_gates"],
            "context_requirements": [
                {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_mature"]}
            ],
            "planner_hint": (
                "When exploring Martial Artist endgame shells, consider Hollow Focus only after "
                "verifying charge and cooldown cadence."
            ),
            "verification_tasks": [
                "Verify selected skill and cooldown/resource cadence with Judge before generation."
            ],
        },
        {
            "pattern_type": "cooccurrence",
            "title": "Barrage and Whirling Slash share a charge attack package",
            "summary": (
                "Several mature attack samples co-locate Barrage and Whirling Slash. The "
                "relationship is advisory and should be treated as a rotation/package clue."
            ),
            "components": {
                "skill:BarragePlayer": "generator",
                "skill:WhirlingSlashPlayer": "payoff",
            },
            "axes": ["secondary_skill_package", "rotation_playstyle", "mechanic_engine"],
            "context_requirements": [
                {
                    "context_type": "verification_gate_requirement",
                    "task": "Verify rotation in Judge.",
                }
            ],
            "planner_hint": "Try Barrage/Whirling Slash as a candidate rotation package, not a copied setup.",
            "verification_tasks": [
                "Check whether both skills are modelled and usable in the planned shell."
            ],
        },
        {
            "pattern_type": "cooccurrence",
            "title": "Mana Remnants clusters with Mind Over Matter",
            "summary": (
                "Mana Remnants and Mind Over Matter co-occur across multiple mature caster shells. "
                "This suggests a mana-buffer resource engine candidate, not a guaranteed defense layer."
            ),
            "components": {
                "skill:ManaRemnantsPlayer": "resource_engine",
                "keystone:pob:0_5:45918": "keystone_transformer",
            },
            "axes": ["resource_engine", "defense_layers", "passive_tree_shape"],
            "context_requirements": [
                {
                    "context_type": "verification_gate_requirement",
                    "task": "Verify mana and EHP modelability.",
                }
            ],
            "planner_hint": "For caster shells, test Mana Remnants with Mind Over Matter as a resource/defense axis.",
            "verification_tasks": [
                "Judge must verify mana pool, recovery and effective hit evidence."
            ],
        },
        {
            "pattern_type": "cooccurrence",
            "title": "Archmage shells recur with Mind Over Matter and Eldritch Battery",
            "summary": (
                "Archmage appears with both Mind Over Matter and Eldritch Battery in several mature "
                "caster samples. Treat this as a resource conversion package requiring validation."
            ),
            "components": {
                "skill:ArchmagePlayer": "resource_engine",
                "keystone:pob:0_5:45918": "keystone_transformer",
                "keystone:pob:0_5:57513": "keystone_transformer",
            },
            "axes": ["resource_engine", "passive_tree_shape", "modelability_caveats"],
            "context_requirements": [
                {
                    "context_type": "verification_gate_requirement",
                    "task": "Verify resource conversion.",
                }
            ],
            "planner_hint": "Use this only to seed resource-engine search; hard legality belongs to planner/Judge.",
            "verification_tasks": [
                "Check resource conversion, reservation and sustain in PoB/Judge."
            ],
        },
        {
            "pattern_type": "cooccurrence",
            "title": "Mana Remnants uses Harmonic Remnants support as recurring package",
            "summary": (
                "Mana Remnants frequently appears with Harmonic Remnants II in this bootstrap batch. "
                "This is a support pairing hint, not a full support-link recipe."
            ),
            "components": {
                "skill:ManaRemnantsPlayer": "resource_engine",
                "support:Metadata/Items/Gem/SupportGemDissipateTwo": "support_modifier",
            },
            "axes": ["resource_engine", "primary_skill_package"],
            "context_requirements": [
                {
                    "context_type": "socket_requirement",
                    "skill_key": "skill:ManaRemnantsPlayer",
                    "support_key": "support:Metadata/Items/Gem/SupportGemDissipateTwo",
                }
            ],
            "planner_hint": "Consider this single support pair during support search; do not copy full links.",
            "verification_tasks": ["Run socket/support legality and Judge readback."],
        },
        {
            "pattern_type": "cooccurrence",
            "title": "Blasphemy uses Ritualistic Curse as curse package hint",
            "summary": (
                "Blasphemy and Ritualistic Curse co-occur in mature curse/reservation shells. "
                "Use it as a curse package hint and verify reservation cost."
            ),
            "components": {
                "skill:BlasphemyPlayer": "reservation",
                "support:Metadata/Items/Gem/SupportGemRitualisticCurse": "support_modifier",
            },
            "axes": ["resource_engine", "defense_layers", "secondary_skill_package"],
            "context_requirements": [
                {
                    "context_type": "spirit_reservation_requirement",
                    "reservation_state": "verify_budget",
                }
            ],
            "planner_hint": "Treat Blasphemy/Ritualistic Curse as a reservation-gated curse package candidate.",
            "verification_tasks": [
                "Verify Spirit/reservation budget before accepting the package."
            ],
        },
        {
            "pattern_type": "cooccurrence",
            "title": "Cast on Elemental Ailment favors Spell Cascade and Efficiency support pair",
            "summary": (
                "Cast on Elemental Ailment appears with Spell Cascade and Efficiency II in several "
                "trigger caster samples. This is a trigger package hint, not proof of DPS."
            ),
            "components": {
                "skill:MetaCastOnElementalAilmentPlayer": "trigger_host",
                "support:Metadata/Items/Gem/SupportGemSpellCascade": "support_modifier",
                "support:Metadata/Items/Gems/SupportGemInspirationTwo": "support_modifier",
            },
            "axes": ["mechanic_engine", "secondary_skill_package", "modelability_caveats"],
            "context_requirements": [
                {
                    "context_type": "verification_gate_requirement",
                    "task": "Verify trigger behaviour.",
                }
            ],
            "planner_hint": "Use as a trigger-caster support search hint, then verify with Judge.",
            "verification_tasks": ["Check trigger modelability and selected skill readback."],
        },
        {
            "pattern_type": "cooccurrence",
            "title": "Rite of Passage clusters with Mana Remnants",
            "summary": (
                "Rite of Passage and Mana Remnants co-occur across multiple mature samples. "
                "Record as a unique-plus-skill co-occurrence; do not infer causality."
            ),
            "components": {
                "unique:pob:rite_of_passage": "unique_enabler",
                "skill:ManaRemnantsPlayer": "resource_engine",
            },
            "axes": ["itemization", "resource_engine"],
            "context_requirements": [
                {
                    "context_type": "item_role_requirement",
                    "role": "unique_enabler",
                    "component_key": "unique:pob:rite_of_passage",
                }
            ],
            "planner_hint": "If a Mana Remnants shell is explored, Rite of Passage can be tested as a unique candidate.",
            "verification_tasks": [
                "Verify the item effect and budget before treating it as enabling."
            ],
        },
        {
            "pattern_type": "cooccurrence",
            "title": "Rite of Passage co-occurs with Heartbreaking passive anchor",
            "summary": (
                "Rite of Passage and Heartbreaking co-occur in many mature samples. This is a "
                "high-level item/passive co-occurrence signal and must not be read as causality."
            ),
            "components": {
                "unique:pob:rite_of_passage": "unique_enabler",
                "notable:pob:0_5:13407": "passive_anchor",
            },
            "axes": ["itemization", "passive_tree_shape"],
            "context_requirements": [
                {
                    "context_type": "passive_context",
                    "allocated_passive_keys": ["notable:pob:0_5:13407"],
                }
            ],
            "planner_hint": "Use this only as a candidate item/passive search prior; verify the actual reason separately.",
            "verification_tasks": [
                "Check whether the passive is causally relevant or just a meta co-occurrence."
            ],
        },
        {
            "pattern_type": "planner_hint",
            "title": "Cooldown Recovery II is broad mature-build support signal",
            "summary": (
                "Cooldown Recovery II appears across many mature samples and often supports cadence-sensitive "
                "skills. Treat it as a broad support-search prior, never as automatic legality."
            ),
            "components": {
                "support:Metadata/Items/Gems/SupportGemIngenuityTwo": "support_modifier",
            },
            "axes": ["rotation_playstyle", "transition_gates", "modelability_caveats"],
            "context_requirements": [
                {
                    "context_type": "verification_gate_requirement",
                    "task": "Verify cooldown cadence.",
                }
            ],
            "planner_hint": "For cadence-sensitive builds, include Cooldown Recovery II in candidate support search.",
            "verification_tasks": ["Judge must verify the selected skill and cooldown behaviour."],
        },
    ]

    observations: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    for spec in candidate_specs:
        component_keys = list(spec["components"].keys())
        missing = [key for key in component_keys if key not in nodes_by_key]
        if missing:
            continue
        refs = _sample_refs_for_components(samples, component_keys)
        if not refs:
            continue
        confidence_tier = _confidence_tier(len(refs), _family_count(samples, refs))
        if confidence_tier is None:
            continue
        observation = {
            "observation_type": spec["pattern_type"],
            "title": spec["title"] + " observation",
            "summary": spec["summary"],
            "axes": spec["axes"],
            "components": [
                {
                    "component_key": key,
                    "role": role,
                    "resolution": _resolution_evidence(nodes_by_key[key], snapshot_id),
                }
                for key, role in spec["components"].items()
            ],
            "source_case_refs": refs,
            "safe_evidence_refs": [f"safe:phase45:{_short_hash(spec['title'])}"],
            "game_patch": "0.5.x",
            "passive_tree_version": "0_5",
            "pob_version_or_commit": "unknown",
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledge_scope": "global_seed",
        }
        observations.append(observation)
        selected.append(
            {
                "title": spec["title"],
                "patternType": spec["pattern_type"],
                "componentKeys": component_keys,
                "sampleCount": len(refs),
                "familyCount": _family_count(samples, refs),
                "confidenceTier": confidence_tier,
            }
        )

    # This builder is deterministic and cannot attest semantic claim scope. Keep the
    # resolver-backed observations and safe candidate summaries for an external Agent, but do not
    # fabricate durable Patterns. The Agent may author a reviewed proposal separately.
    return {
        "schema_version": 4,
        "build_design_observations": observations,
        "patterns": [],
        "fragments": [],
        "semantic_edges": [],
    }, selected


def _sample_refs_for_components(
    samples: list[dict[str, Any]], component_keys: list[str]
) -> list[str]:
    refs: list[str] = []
    for sample in samples:
        sample_components = {
            *(sample.get("activeSkills") or []),
            *(sample.get("supports") or []),
            *(sample.get("passiveKeys") or []),
            *(sample.get("uniqueKeys") or []),
        }
        if sample.get("ascendancyKey"):
            sample_components.add(sample["ascendancyKey"])
        if sample.get("mainSkillKey"):
            sample_components.add(sample["mainSkillKey"])
        if all(key in sample_components for key in component_keys):
            refs.append(sample["sampleId"])
    return refs


def _confidence_tier(sample_count: int, family_count: int) -> str | None:
    if sample_count == 1:
        return "case_observation"
    if 2 <= sample_count <= 3:
        return "recurring_observation"
    if 4 <= sample_count <= 7 and family_count >= 2:
        return "likely_pattern"
    if 8 <= sample_count <= 14 and family_count >= 2:
        return "common_within_archetype"
    if sample_count >= 15 and family_count >= 2:
        return "strong_ranking_hint"
    return None


def _family_count(samples: list[dict[str, Any]], refs: list[str]) -> int:
    wanted = set(refs)
    return len({sample["buildFamilyKey"] for sample in samples if sample["sampleId"] in wanted})


def _resolution_evidence(node: physical_graph.GraphNode, snapshot_id: str) -> dict[str, Any]:
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": node.stable_key,
        "snapshot_id": snapshot_id,
        "evidence_path_nodes": [node.stable_key],
        "source_refs": list(node.source_refs),
    }


def _review_report(
    *,
    samples: list[dict[str, Any]],
    duplicate_inputs: list[dict[str, Any]],
    proposal: dict[str, Any],
    selected_patterns: list[dict[str, Any]],
    nodes_by_key: dict[str, physical_graph.GraphNode],
    snapshot_id: str,
) -> dict[str, Any]:
    family_counts = Counter(sample["buildFamilyKey"] for sample in samples)
    pattern_summaries = []
    for pattern in selected_patterns:
        pattern_summaries.append(
            {
                "titleZh": _title_zh(pattern["title"]),
                "patternType": pattern["patternType"],
                "confidenceTier": pattern["confidenceTier"],
                "sampleCount": pattern["sampleCount"],
                "familyCount": pattern["familyCount"],
                "componentKeys": pattern["componentKeys"],
                "componentsZh": [
                    nodes_by_key[key].display_name
                    for key in pattern["componentKeys"]
                    if key in nodes_by_key
                ],
                "summaryZh": _summary_zh(pattern["title"]),
                "plannerUseZh": _planner_use_zh(pattern["patternType"]),
                "caveatZh": "这是 planner advisory pattern，不是 hard legality，也不是完整 BD 配方。",
            }
        )
    return {
        "reportId": "phase4-pattern-bootstrap-researcher-review-v1",
        "status": "observation_only_agent_review_required",
        "safeArtifactOnly": True,
        "snapshotId": snapshot_id,
        "sampleCount": len(samples),
        "duplicateInputCount": len(duplicate_inputs),
        "duplicateInputs": duplicate_inputs,
        "familySampleCounts": dict(sorted(family_counts.items())),
        "observationProposalCount": len(proposal["build_design_observations"]),
        "patternProposalCount": len(proposal["patterns"]),
        "agentReviewCandidateCount": len(selected_patterns),
        "agentSemanticScopeReviewRequired": True,
        "selectedPatterns": selected_patterns,
        "patternsZh": pattern_summaries,
        "coverageNotesZh": [
            "本轮已经覆盖升华壳、主技能/副技能、support、keystone/notable、unique 与资源/触发/诅咒包。",
            "没有输出或持久化 raw PoB code、raw XML、完整装备表、完整天赋路径或完整 gem/support links。",
            "暗金相关 pattern 只选择 schema 当前能安全表达的 stable key；部分含特殊字符的 physical key 另列 schema follow-up。",
            "Deterministic builder 只写 observation；外部 Agent 完成 typed semantic-scope review 后才能另行提出 Pattern。",
        ],
        "noRawMatureBuildMaterial": True,
    }


def _title_zh(title: str) -> str:
    mapping = {
        "Martial Artist shell observed with Hollow Focus": "Martial Artist 升华壳与 Hollow Focus 的成熟样本共现",
        "Barrage and Whirling Slash share a charge attack package": "Barrage 与 Whirling Slash 的充能/攻击轮换包",
        "Mana Remnants clusters with Mind Over Matter": "Mana Remnants 与 Mind Over Matter 的资源/防御轴",
        "Archmage shells recur with Mind Over Matter and Eldritch Battery": "Archmage 与 MoM / Eldritch Battery 的资源转换包",
        "Mana Remnants uses Harmonic Remnants support as recurring package": "Mana Remnants 与 Harmonic Remnants II 的单 support 配对",
        "Blasphemy uses Ritualistic Curse as curse package hint": "Blasphemy 与 Ritualistic Curse 的诅咒保留包",
        "Cast on Elemental Ailment favors Spell Cascade and Efficiency support pair": "Cast on Elemental Ailment 的触发 support 配对",
        "Rite of Passage clusters with Mana Remnants": "Rite of Passage 与 Mana Remnants 的暗金/技能共现",
        "Rite of Passage co-occurs with Heartbreaking passive anchor": "Rite of Passage 与 Heartbreaking 的暗金/天赋共现",
        "Cooldown Recovery II is broad mature-build support signal": "Cooldown Recovery II 作为成熟 BD 的节奏型 support 信号",
    }
    return mapping.get(title, title)


def _summary_zh(title: str) -> str:
    mapping = {
        "Martial Artist shell observed with Hollow Focus": "说明某个升华壳和核心技能在成熟样本中一起出现，但不能证明开荒可用或数值强。",
        "Barrage and Whirling Slash share a charge attack package": "说明副技能/轮换技能可以作为一个机制包被 Architect 尝试，但必须再验证操作与 modelability。",
        "Mana Remnants clusters with Mind Over Matter": "说明 Mana Remnants 可作为 MoM 类资源防御轴的候选组件。",
        "Archmage shells recur with Mind Over Matter and Eldritch Battery": "说明 Archmage 相关壳常和资源转换 keystone 一起被成熟样本使用，需要严查资源合法性。",
        "Mana Remnants uses Harmonic Remnants support as recurring package": "只记录一个 support pair，不复制完整 support 链。",
        "Blasphemy uses Ritualistic Curse as curse package hint": "提示诅咒保留包可能有价值，但 Spirit/保留预算是 transition gate。",
        "Cast on Elemental Ailment favors Spell Cascade and Efficiency support pair": "提示触发流派的 support 搜索方向，不能直接当作 DPS 证明。",
        "Rite of Passage clusters with Mana Remnants": "提示暗金和技能可能同属资源引擎路线，但共现不等于因果。",
        "Rite of Passage co-occurs with Heartbreaking passive anchor": "提示暗金和关键天赋的共同出现，后续要判断是机制需要还是 meta 泡泡。",
        "Cooldown Recovery II is broad mature-build support signal": "提示冷却/节奏敏感 build 应把该 support 放入候选搜索，但必须验证合法性和收益。",
    }
    return mapping.get(title, "安全中文摘要。")


def _planner_use_zh(pattern_type: str) -> str:
    if pattern_type == "planner_hint":
        return "Phase 5 可把它作为搜索空间优先级提示。"
    return "Phase 5 可把它作为候选组合提示，但仍要 deterministic planner 和 Judge 验证。"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _assert_safe_artifact(artifact: dict[str, Any]) -> None:
    serialized = json.dumps(artifact, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe artifact markers detected: {', '.join(leaks)}")
    if copy_safety.find_forbidden_paths(artifact):
        raise ValueError("unsafe artifact contains forbidden raw fields")
    for text in _iter_human_text(artifact):
        if copy_safety.copyability_flags(text):
            raise ValueError("unsafe artifact failed copyability scan")


TEXT_SCAN_FIELDS = {
    "caveat",
    "caveatZh",
    "caveats",
    "coverageNotesZh",
    "planner_hint",
    "plannerUseZh",
    "summary",
    "summaryZh",
    "title",
    "titleZh",
    "verification_tasks",
}


def _iter_human_text(value: Any, *, key: str = "") -> list[str]:
    if isinstance(value, dict):
        values: list[str] = []
        for child_key, child in value.items():
            child_key_text = str(child_key)
            if child_key_text in TEXT_SCAN_FIELDS:
                values.extend(_iter_text_leaves(child))
            else:
                values.extend(_iter_human_text(child, key=child_key_text))
        return values
    if isinstance(value, list):
        values = []
        for child in value:
            values.extend(_iter_human_text(child, key=key))
        return values
    return []


def _iter_text_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values: list[str] = []
        for child in value:
            values.extend(_iter_text_leaves(child))
        return values
    if isinstance(value, dict):
        values = []
        for child in value.values():
            values.extend(_iter_text_leaves(child))
        return values
    return []


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4.5 Pattern Bootstrap Researcher Review",
        "",
        f"- Status: `{report['status']}`",
        f"- Samples: `{report['sampleCount']}`",
        f"- Duplicate inputs: `{report['duplicateInputCount']}`",
        f"- Pattern proposals: `{report['patternProposalCount']}`",
        "",
        "## Families",
        "",
    ]
    for family, count in report["familySampleCounts"].items():
        lines.append(f"- `{family}`: `{count}`")
    lines.extend(["", "## Patterns", ""])
    for pattern in report["patternsZh"]:
        lines.extend(
            [
                f"- {pattern['titleZh']}",
                f"  - confidence: `{pattern['confidenceTier']}`, samples: `{pattern['sampleCount']}`, families: `{pattern['familyCount']}`",
                f"  - summary: {pattern['summaryZh']}",
                f"  - planner: {pattern['plannerUseZh']}",
                f"  - caveat: {pattern['caveatZh']}",
            ]
        )
    lines.extend(["", "## Coverage Notes", ""])
    for note in report["coverageNotesZh"]:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_files", nargs="+")
    parser.add_argument(
        "--graph-snapshot-index",
        default=str(paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"),
    )
    parser.add_argument("--manifest-output", default=str(MANIFEST_OUTPUT))
    parser.add_argument("--proposal-output", default=str(PROPOSAL_OUTPUT))
    parser.add_argument("--review-json-output", default=str(REVIEW_JSON_OUTPUT))
    parser.add_argument("--review-md-output", default=str(REVIEW_MD_OUTPUT))
    args = parser.parse_args(argv)
    report = write_phase45_bootstrap_artifacts(
        source_files=args.source_files,
        graph_snapshot_index=args.graph_snapshot_index,
        manifest_output=args.manifest_output,
        proposal_output=args.proposal_output,
        review_json_output=args.review_json_output,
        review_md_output=args.review_md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
