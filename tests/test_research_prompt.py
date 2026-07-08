from __future__ import annotations

from server.knowledge import research_prompt


def _packet() -> dict:
    return {
        "packetId": "rp-test",
        "safeHash": "abc123",
        "safeMetadata": {
            "case_id": "case-lightning-arrow",
            "mainSkill": "Lightning Arrow",
            "gamePatch": "0.5.4",
            "passiveTreeVersion": "0_5",
        },
        "rawContext": {
            "pobCode": "eNrt" + "A" * 180,
            "pageText": "quarantine-only mature build evidence",
        },
        "copySafetyRules": [
            "Final output must not contain raw PoB code, raw XML, full gear, full passive path, or full gem links."
        ],
        "requestedOutputSchema": "ResearcherOutput schema_version=4",
    }


def _prompt_text(package: dict) -> str:
    return "\n".join(str(message["content"]) for message in package["messages"])


def test_researcher_prompt_is_tool_driven_not_plain_json_output():
    package = research_prompt.build_researcher_prompt_package(
        _packet(),
        current_patch="0.5.4",
        passive_tree_version="0_5",
        user_language="zh-CN",
    )

    text = _prompt_text(package)

    assert package["ok"] is True
    assert package["schemaVersion"] == 4
    assert "ResearcherOutput schema_version=4" in text
    assert "MUST NOT output the final JSON as regular text" in text
    assert "DO NOT output your final analysis as markdown JSON" in text
    assert "propose_research_fragments" in text
    assert "propose_semantic_edges" in text
    assert "Return exactly one JSON object" not in text


def test_researcher_prompt_requires_query_before_write_and_append_evidence():
    text = _prompt_text(research_prompt.build_researcher_prompt_package(_packet()))

    assert "STEP 1: Query & Deduplicate (Mandatory)" in text
    assert "query_research_memory" in text
    assert "dedupeQueryRef" in text
    assert "append_evidence_to_fragment" in text
    assert "DO NOT create duplicates" in text
    assert "validate_researcher_output before proposing writes" not in text
    assert "Do not use validate_researcher_output as a routine preflight" in text


def test_researcher_prompt_hard_locks_graph_resolution_before_edges():
    text = _prompt_text(research_prompt.build_researcher_prompt_package(_packet()))

    assert "STEP 2: Resolve Physical Keys (Mandatory)" in text
    assert "graph_tool_query" in text
    assert "resolve_graph_component" in text
    assert "Before constructing ANY semantic edge" in text
    assert "FORBIDDEN from calling propose_semantic_edges" in text
    assert "stable_key" in text
    assert "resolvedSubject.stableKey" in text
    assert "snapshotId" in text
    assert "evidencePath.nodes" in text


def test_researcher_prompt_distinguishes_graph_coverage_gap_from_hallucination():
    text = _prompt_text(research_prompt.build_researcher_prompt_package(_packet()))

    assert "Do not label unresolved mature-build entities as hallucinations" in text
    assert "graph_snapshot_unavailable" in text
    assert "source_coverage_gap" in text
    assert "static source review" in text


def test_researcher_prompt_requires_secondary_resolution_and_bounded_repair():
    text = _prompt_text(research_prompt.build_researcher_prompt_package(_packet()))

    assert "secondary endpoint" in text
    assert "abstract layer labels" in text
    assert "at most 2 narrowed resolver attempts" in text
    assert "requires_manual_endpoint_mapping" in text
    assert "never choose the most likely candidate" in text
    assert "static source refresh request" in text


def test_researcher_prompt_has_copy_safety_and_bounded_rejection_loop():
    text = _prompt_text(research_prompt.build_researcher_prompt_package(_packet()))

    assert "NEVER output raw PoB code" in text
    assert "raw XML" in text
    assert "full gear tables" in text
    assert "full passive trees" in text
    assert "full gem/support links" in text
    assert "raw character URLs" in text
    assert "retry at most 2 times" in text
    assert "safe ids/status/caveats" in text


def test_researcher_prompt_requires_build_design_observation_and_pattern_axes():
    text = _prompt_text(research_prompt.build_researcher_prompt_package(_packet()))

    assert "BuildDesignObservation" in text
    assert "build_design_observations" in text
    assert "character_shell" in text
    assert "primary_skill_package" in text
    assert "secondary_skill_package" in text
    assert "passive_tree_shape" in text
    assert "itemization" in text
    assert "scaling_axis" in text
    assert "resource_engine" in text
    assert "defense_layers" in text
    assert "mechanic_engine" in text
    assert "transition_gates" in text
    assert "failure_modes" in text
    assert "patterns" in text
    assert "propose_build_patterns" in text
    assert "case_observation" in text
    assert "common_within_archetype" in text
    assert "hard legality" in text
    assert "ascendancy_shell" in text


def test_researcher_prompt_lists_phase45_extraction_checklist_explicitly():
    text = _prompt_text(research_prompt.build_researcher_prompt_package(_packet()))

    expected_phrases = [
        "ascendancy + primary skill",
        "shell suitability, not skill legality",
        "primary skill + secondary skill",
        "role such as clear, boss, generator, payoff, movement, or trigger_host",
        "skill + key passive / notable / keystone",
        "resolver-backed",
        "unique item + passive / skill",
        "required/enabling, optional/chase, or budget_substitute",
        "support + active skill",
        "single pair",
        "full support-link package",
        "skill/archetype + scaling axis",
        "weapon/base/stat priority",
        "Spirit/reservation package + build shell",
        "defense layer package + content goal",
        "mechanic chain",
        "generator -> transformer -> payoff",
        "level, unique item, ascendancy points, Spirit, attributes, or budget",
        "failure mode + mitigation",
        "variant relation",
        "crit/non-crit, SSF/trade, starter/endgame",
        "modelability caveat",
        "Do not force every checklist item",
    ]
    for phrase in expected_phrases:
        assert phrase in text


def test_researcher_prompt_keeps_programmatic_diagnostics_non_authoritative():
    text = _prompt_text(research_prompt.build_researcher_prompt_package(_packet()))

    assert "Programmatic diagnostics are non-authoritative hints" in text
    assert (
        "Do not let summaries, resolver shortlists, imported main skill, or selected-skill probes limit your analysis"
        in text
    )
    assert "If a useful signal appears only in raw quarantine evidence" in text
    assert "treat it as eligible for analysis" in text
    assert (
        "Do not discard a plausible mechanism solely because it is absent from a programmatic summary"
        in text
    )


def test_researcher_user_directives_include_pattern_submission_tool():
    package = research_prompt.build_researcher_prompt_package(_packet())
    user_text = package["messages"][1]["content"]

    assert (
        "Submit findings through propose_research_fragments, propose_build_patterns, and propose_semantic_edges"
        in user_text
    )
