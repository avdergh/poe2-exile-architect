"""poe-research-mcp: mature-build intake, clean fragment/edge/record/pattern proposals and
validation. Quarantine-only raw intake; acceptance is the only durable writer.
"""

from __future__ import annotations

from pathlib import Path

from ..main import (  # noqa: F401  (re-registered below)
    _SessionIsolatedFastMCP,
    start_study_run,
    inspect_study_case,
    read_study_case,
    search_study_case,
    get_study_contract,
    review_study_evidence,
    review_study_terminology,
    validate_study_lesson,
    complete_study_explanation,
    cleanup_study_run,
    accept_research_review,
    apply_research_record_merge,
    append_evidence_to_fragment,
    build_research_packet,
    claim_research_case,
    cleanup_research_run,
    get_research_review_contract,
    get_research_run_status,
    get_research_followup_status,
    submit_research_gap_review,
    reacquire_research_source,
    initialize_research_review,
    inspect_research_merge_candidates,
    inspect_research_case,
    inspect_rejected_research_proposals,
    propose_build_patterns,
    propose_deep_research_records,
    propose_research_fragments,
    propose_semantic_edges,
    preview_research_record_merge,
    read_research_case,
    retry_research_review,
    search_research_case,
    start_research_run,
    submit_revalidation_result,
    inspect_research_patch_review_targets,
    submit_research_patch_review,
    validate_research_review,
    validate_researcher_output,
)

_GUIDE = Path(__file__).parent.parent / "MCP_RESEARCH_BOOTSTRAP.md"
try:
    _INSTRUCTIONS: str | None = _GUIDE.read_text(encoding="utf-8")
except OSError:
    _INSTRUCTIONS = (
        "Exile Architect research server: quarantine-only mature-build intake and typed "
        "fragment/edge/record proposals. Acceptance is the only durable writer."
    )

mcp = _SessionIsolatedFastMCP("poe-research-mcp", instructions=_INSTRUCTIONS)

_TOOLS = (
    start_study_run,
    inspect_study_case,
    read_study_case,
    search_study_case,
    get_study_contract,
    review_study_evidence,
    review_study_terminology,
    validate_study_lesson,
    complete_study_explanation,
    cleanup_study_run,
    accept_research_review,
    apply_research_record_merge,
    append_evidence_to_fragment,
    build_research_packet,
    claim_research_case,
    cleanup_research_run,
    get_research_review_contract,
    get_research_run_status,
    get_research_followup_status,
    submit_research_gap_review,
    reacquire_research_source,
    initialize_research_review,
    inspect_research_merge_candidates,
    inspect_research_case,
    inspect_rejected_research_proposals,
    propose_build_patterns,
    propose_deep_research_records,
    propose_research_fragments,
    propose_semantic_edges,
    preview_research_record_merge,
    read_research_case,
    retry_research_review,
    search_research_case,
    start_research_run,
    submit_revalidation_result,
    inspect_research_patch_review_targets,
    submit_research_patch_review,
    validate_research_review,
    validate_researcher_output,
)

for _fn in _TOOLS:
    mcp.tool()(_fn)

if __name__ == "__main__":
    mcp.run()
