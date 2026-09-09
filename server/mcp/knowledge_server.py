"""poe-knowledge-mcp: offline corpus, graph, mechanics, Research queries, live freshness/prices.

Read-only domain: never touches the PoB engine. The numeric authority for builds stays in
``build_server``. This module re-registers the knowledge-domain tools defined in ``server.main``
with a short domain bootstrap; see ``server/main.py`` for the implementations.
"""

from __future__ import annotations

from pathlib import Path

from ..main import (  # noqa: F401  (re-registered below)
    analyze_lifecycle_cohort,
    apply_updates,
    audit_lifecycle_route,
    build_advice,
    check_data_version,
    check_for_updates,
    compare_lifecycle_routes,
    construct_research_execution_contract,
    corpus_info,
    evaluate_lifecycle_route,
    evaluate_transition_readiness,
    explain_mechanic,
    find_skills,
    find_supports_for,
    get_freshness_report,
    get_gem,
    get_research_write_receipt,
    get_item,
    get_meta_archetype_trends,
    get_meta_builds,
    get_prices,
    get_unique,
    graph_tool_query,
    list_ascendancies,
    list_price_leagues,
    list_reference_builds,
    list_skills_for_level,
    list_transition_gates,
    lookup_mechanic,
    plan_lifecycle_stage_verification,
    query_public_learning_memory,
    query_research_memory,
    record_build_feedback,
    reverse_lookup,
    search_items,
    search_mechanics,
    search_mods,
    search_uniques,
    suggest_build_lifecycle,
    update_corpus,
    _SessionIsolatedFastMCP,
)

_GUIDE = Path(__file__).parent.parent / "MCP_KNOWLEDGE_BOOTSTRAP.md"
try:
    _INSTRUCTIONS: str | None = _GUIDE.read_text(encoding="utf-8")
except OSError:
    _INSTRUCTIONS = (
        "Exile Architect knowledge server: offline corpus, graph, mechanics, Research queries, "
        "freshness and prices. Build numbers come from the build server, never from here."
    )

mcp = _SessionIsolatedFastMCP("poe-knowledge-mcp", instructions=_INSTRUCTIONS)

_TOOLS = (
    analyze_lifecycle_cohort,
    apply_updates,
    audit_lifecycle_route,
    build_advice,
    check_data_version,
    check_for_updates,
    compare_lifecycle_routes,
    construct_research_execution_contract,
    corpus_info,
    evaluate_lifecycle_route,
    evaluate_transition_readiness,
    explain_mechanic,
    find_skills,
    find_supports_for,
    get_freshness_report,
    get_gem,
    get_research_write_receipt,
    get_item,
    get_meta_archetype_trends,
    get_meta_builds,
    get_prices,
    get_unique,
    graph_tool_query,
    list_ascendancies,
    list_price_leagues,
    list_reference_builds,
    list_skills_for_level,
    list_transition_gates,
    lookup_mechanic,
    plan_lifecycle_stage_verification,
    query_public_learning_memory,
    query_research_memory,
    record_build_feedback,
    reverse_lookup,
    search_items,
    search_mechanics,
    search_mods,
    search_uniques,
    suggest_build_lifecycle,
    update_corpus,
)

for _fn in _TOOLS:
    mcp.tool()(_fn)

if __name__ == "__main__":
    mcp.run()
