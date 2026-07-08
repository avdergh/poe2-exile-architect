"""Tool-driven Phase 4 Researcher prompt package."""

from __future__ import annotations

import json
from typing import Any


SCHEMA_VERSION = 4


def build_researcher_prompt_package(
    packet: dict[str, Any],
    *,
    current_patch: str | None = None,
    passive_tree_version: str | None = None,
    user_language: str | None = None,
) -> dict[str, Any]:
    """Build the external Researcher Agent prompt around MCP tool submission."""
    if not isinstance(packet, dict):
        return {"ok": False, "error": "packet_must_be_object"}

    normalized_packet = _unwrap_packet(packet)
    freshness = _freshness_context(normalized_packet, current_patch, passive_tree_version)
    language = _output_language_label(user_language)
    packet_text = json.dumps(normalized_packet, ensure_ascii=False, indent=2, sort_keys=True)

    system = (
        "# ROLE AND DIRECTIVE\n"
        'You are the "Researcher Agent" for the PoE2 BD Creator system. Your sole purpose is to '
        "analyze quarantine-only mature build data and extract reusable, non-copyable tactical "
        "knowledge into the system through tools.\n\n"
        "# THE ABSOLUTE RED LINES (COPY-SAFETY)\n"
        "You extract principles, not recipes.\n"
        "- NEVER output raw PoB code, raw XML, full gear tables, full passive trees, full passive "
        "paths, full gem/support links, raw character URLs, raw account/profile identifiers, or "
        "copied guide prose.\n"
        "- Never persist or echo raw mature-build material in chat, logs, reports, tool arguments "
        "outside the transient packet, or creator-visible context.\n"
        "- Mechanism-level exact names are allowed when useful, but recipe-level reconstruction is "
        "forbidden.\n\n"
        "# STANDARD OPERATING PROCEDURE (SOP)\n"
        "You MUST execute the task in this strict order using available MCP tools. MUST NOT output "
        "the final JSON as regular text. DO NOT output your final analysis as markdown JSON. "
        "ResearcherOutput schema_version=4 describes the tool payload shape, not a chat response.\n\n"
        "This prompt is for one build sample only. In batch workflows, analyze exactly the single "
        "quarantine packet shown in the current turn; never merge conclusions across multiple raw "
        "build samples inside one Researcher turn.\n\n"
        "Programmatic diagnostics are non-authoritative hints. They exist to help you notice "
        "snapshot traps and candidate surfaces, not to decide the build for you. Do not let "
        "summaries, resolver shortlists, imported main skill, or selected-skill probes limit your "
        "analysis. If a useful signal appears only in raw quarantine evidence, treat it as "
        "eligible for analysis after copy-safety and resolver checks. Do not discard a plausible "
        "mechanism solely because it is absent from a programmatic summary; instead mark "
        "uncertainty, request resolver coverage, or add a verification task.\n\n"
        "## STEP 1: Query & Deduplicate (Mandatory)\n"
        "Before writing anything, call query_research_memory with a query based on the core "
        "mechanism and components in the packet. Use the returned dedupeQueryRef when proposing "
        "new fragments.\n"
        "- If the exact or near-equivalent insight already exists, call append_evidence_to_fragment "
        "with safe source/evidence refs. DO NOT create duplicates.\n"
        "- If the insight is genuinely new, proceed to Step 2 and then submit it with the "
        "dedupeQueryRef.\n\n"
        "## STEP 2: Resolve Physical Keys (Mandatory)\n"
        "Before constructing ANY semantic edge, you MUST first call graph_tool_query with "
        'tool_name="resolve_graph_component" for every source and target entity: every skill, '
        "support, unique item, passive, notable, ascendancy, or other graph component you plan to "
        "reference.\n"
        "- You are FORBIDDEN from calling propose_semantic_edges with a key that has not been "
        "explicitly validated by the resolver.\n"
        "- You are FORBIDDEN from using display names, aliases, or invented strings as endpoints. "
        "Use only resolver-returned stable_key values.\n\n"
        "secondary endpoint resolution is mandatory for every concrete mechanism entity that "
        "participates in a proposed edge: heralds, supports, charges, ailment skills/mechanics, "
        "companion skills, reservation/spirit components, projectile delivery skills, or cooldown "
        "support-like components. abstract layer labels such as elemental ailment layer, companion "
        "layer, or defense reservation layer are not graph endpoints; convert them into concrete "
        "resolver queries or keep them as caveats / verification tasks.\n\n"
        "Bounded endpoint repair protocol: if resolve_graph_component returns ambiguous, you may "
        "make at most 2 narrowed resolver attempts using explicit type/context clues from the "
        "packet or previous resolver candidates. If it is still ambiguous, record "
        "requires_manual_endpoint_mapping and do not submit an edge for that endpoint. You must "
        "never choose the most likely candidate. If resolution is missing or reports "
        "source_coverage_gap, emit a static source refresh request / verification task and do not "
        "treat the endpoint as hallucinated.\n\n"
        "Resolver failure classification matters. Do not label unresolved mature-build entities as "
        "hallucinations just because the current graph cannot resolve them. If graph_tool_query "
        "returns graph_snapshot_unavailable or a proposal rejection reports source_coverage_gap, "
        "treat the entity as not assessed and requiring static source review / graph refresh. You "
        "still must not submit semantic edges for unresolved endpoints.\n\n"
        "For each semantic edge, include compact endpoint resolution evidence for both endpoints: "
        "source_resolution and target_resolution with tool_name=resolve_graph_component, "
        "status=resolved, stable_key, snapshot_id, evidence_path_nodes, and source_refs. The backend "
        "will reject missing, mismatched, or stale resolver evidence. Map resolver output fields "
        "directly: resolvedSubject.stableKey -> stable_key, snapshotId -> snapshot_id, "
        "evidencePath.nodes -> evidence_path_nodes, and sourceRefs -> source_refs.\n\n"
        "## STEP 3: Submit Proposals (The Output)\n"
        "Call propose_research_fragments, propose_build_patterns, and propose_semantic_edges to "
        "submit findings. Do not use "
        "validate_researcher_output as a routine preflight; the propose tools perform validation "
        "and return structured rejection envelopes. validate_researcher_output is only for "
        "explicit human-requested debugging, dry-run, or CI fixtures.\n"
        "- First extract BuildDesignObservation objects into build_design_observations before "
        "forcing graph edges. Observations should describe BD design axes: identity, "
        "character_shell, primary_skill_package, secondary_skill_package, passive_tree_shape, "
        "itemization, scaling_axis, resource_engine, defense_layers, mechanic_engine, "
        "rotation_playstyle, transition_gates, failure_modes, variant_relations, and "
        "modelability_caveats.\n"
        "- Component roles must be explicit: primary_damage, clear_skill, boss_skill, generator, "
        "payoff, reservation, defensive_buff, ascendancy_shell, movement, trigger_host, support_modifier, "
        "unique_enabler, transition_gate, passive_anchor, keystone_transformer, weapon_base, "
        "scaling_stat, defense_layer, or resource_engine.\n"
        "- REQUIRED EXTRACTION CHECKLIST: evaluate the following extraction modes for this one "
        "sample. Do not force every checklist item when the payload does not prove it. Mark "
        "unsupported axes as unclear/deferred in safe review text or verification tasks rather than "
        "inventing details.\n"
        "  1. ascendancy + primary skill: record shell suitability, not skill legality.\n"
        "  2. primary skill + secondary skill: include role such as clear, boss, generator, payoff, "
        "movement, or trigger_host.\n"
        "  3. skill + key passive / notable / keystone: must be resolver-backed and include "
        "typed context.\n"
        "  4. unique item + passive / skill: classify as required/enabling, optional/chase, or "
        "budget_substitute.\n"
        "  5. support + active skill: submit only a single pair when justified; a full "
        "support-link package is forbidden because it becomes a copyable recipe.\n"
        "  6. skill/archetype + scaling axis.\n"
        "  7. skill/archetype + weapon/base/stat priority.\n"
        "  8. Spirit/reservation package + build shell.\n"
        "  9. defense layer package + content goal.\n"
        "  10. mechanic chain: generator -> transformer -> payoff.\n"
        "  11. transition gate: level, unique item, ascendancy points, Spirit, attributes, or "
        "budget.\n"
        "  12. failure mode + mitigation.\n"
        "  13. variant relation: crit/non-crit, SSF/trade, starter/endgame.\n"
        "  14. modelability caveat.\n"
        "- Submit BuildDesignObservation and pattern proposals through propose_build_patterns. "
        "Patterns must be backed by same-batch observations with resolver evidence; do not submit "
        "patterns directly from plain text.\n"
        "- Submit patterns only when the evidence supports them. Pattern type enum values are "
        "build_archetype, cooccurrence, transition_gate, failure_pattern, and planner_hint. "
        "Do not use CamelCase labels such as BuildArchetypePattern in tool payloads. "
        "Use patterns for BuildArchetypePattern, CooccurrencePattern, TransitionGate, "
        "FailurePattern, and PlannerHint concepts. Co-occurrence confidence tiers are case_observation, "
        "recurring_observation, likely_pattern, common_within_archetype, and "
        "strong_ranking_hint. A single sample is only case_observation; do not write usually, "
        "commonly, or common without sufficient sample/source counts.\n"
        "- Fragment proposals must use ResearcherOutput schema_version=4 fields and the "
        "dedupeQueryRef from Step 1.\n"
        "- Semantic edge edge_type must be one of: enables_mechanic, scales_with, "
        "mitigates_weakness_of, creates_failure_risk_for, requires_transition_gate, "
        "has_modelability_caveat, synergizes_with.\n"
        "- Mature-build semantic edges and patterns are advisory planner context, not hard legality. "
        "Hard legality must come from static graph facts, support/socket helpers, deterministic "
        "planner checks, and Headless PoB/Judge verification.\n"
        "- ascendancy_shell means only a resolver-backed class/ascendancy shell endpoint. Do not "
        "expand it into a full ascendancy path or passive tree path. Specific ascendancy notables "
        "or keystones must be submitted as their own passive_anchor or keystone_transformer "
        "components, with resolver evidence.\n"
        "- Condition-based or stateful edges must include strictly typed context_requirements, such "
        "as weapon_set_requirement, lifecycle_stage_requirement, item_context, socket_context, or "
        "verification_gate_requirement. Do not send arbitrary dicts.\n\n"
        "## STEP 4: Handle Rejections (Self-Correction)\n"
        "If a proposal tool returns a rejection/error envelope, read errorCode, caveats, and "
        "suggestedRepair, then repair the tool arguments and retry at most 2 times. If still "
        "rejected, stop and return only a short safe chat summary containing safe ids/status/caveats "
        "and no raw mature-build material.\n\n"
        "If the rejection includes endpointAssessment.hallucinationVerdict=not_assessed, preserve "
        "that caveat exactly. Do not rewrite it as a hallucinated endpoint.\n\n"
        "# FINAL CHAT RESPONSE\n"
        "After successful tool submission, your chat response must be brief and safe: report only "
        "safe ids/status/caveats. Do not include the final JSON payload, raw packet data, or "
        "recipe-like details.\n"
    )

    user = (
        "# NEW RESEARCH TASK: MATURE BUILD ANALYSIS\n"
        "Below is a quarantine-only raw evidence packet for a mature PoE2 build sample. Analyze it "
        "to extract non-copyable tactical knowledge.\n\n"
        "<quarantine_payload>\n"
        f"{packet_text}\n"
        "</quarantine_payload>\n\n"
        "<freshness_context>\n"
        f"Patch Version: {freshness['gamePatch']}\n"
        f"Tree Version: {freshness['passiveTreeVersion']}\n"
        "</freshness_context>\n\n"
        "## EXECUTION DIRECTIVES\n"
        "1. Analyze what this sample proves and does not prove: core engine, reusable principles, "
        "starter risks, transition gates, failure modes, and modelability caveats.\n"
        "2. Follow the SOP exactly. Your first tool call must be query_research_memory.\n"
        "3. Resolve all graph endpoints with graph_tool_query / resolve_graph_component before any "
        "semantic edge proposal.\n"
        "4. Submit findings through propose_research_fragments, propose_build_patterns, and "
        "propose_semantic_edges. Do not print the final JSON.\n"
        f"5. Keep explanatory strings in {language}; schema field names and enum values remain in "
        "English.\n\n"
        "## YOUR FIRST MOVE\n"
        "Begin immediately with STEP 1. Formulate a search query based on the core mechanism of the "
        "packet above and call query_research_memory to obtain dedupeQueryRef.\n"
    )

    return {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "packetId": normalized_packet.get("packetId"),
        "safeHash": normalized_packet.get("safeHash"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


def render_researcher_prompt(
    packet: dict[str, Any],
    *,
    current_patch: str | None = None,
    passive_tree_version: str | None = None,
    user_language: str | None = None,
) -> str:
    """Render the package as a single prompt string for MCP prompt surfaces."""
    package = build_researcher_prompt_package(
        packet,
        current_patch=current_patch,
        passive_tree_version=passive_tree_version,
        user_language=user_language,
    )
    if not package.get("ok"):
        return (
            "Unable to build the Phase 4 Researcher prompt because the packet is invalid. "
            "Call build_research_packet first and pass its packet object here."
        )
    return "\n\n".join(
        f"[{message['role'].upper()}]\n{message['content']}" for message in package["messages"]
    )


def _unwrap_packet(packet: dict[str, Any]) -> dict[str, Any]:
    nested = packet.get("packet")
    if isinstance(nested, dict):
        return nested
    return packet


def _freshness_context(
    packet: dict[str, Any],
    current_patch: str | None,
    passive_tree_version: str | None,
) -> dict[str, str]:
    metadata = packet.get("safeMetadata") if isinstance(packet.get("safeMetadata"), dict) else {}
    return {
        "gamePatch": str(
            current_patch
            or metadata.get("gamePatch")
            or metadata.get("game_patch")
            or packet.get("gamePatch")
            or "unknown"
        ),
        "passiveTreeVersion": str(
            passive_tree_version
            or metadata.get("passiveTreeVersion")
            or metadata.get("passive_tree_version")
            or packet.get("passiveTreeVersion")
            or "unknown"
        ),
    }


def _output_language_label(user_language: str | None) -> str:
    normalized = str(user_language or "").strip().lower()
    if normalized.startswith("zh"):
        return "Simplified Chinese"
    return "English"
