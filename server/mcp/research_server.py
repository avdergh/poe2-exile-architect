"""poe-research-mcp: mature-build intake, clean fragment/edge/record/pattern proposals and
validation. Quarantine-only raw intake; acceptance is the only durable writer.
"""

from __future__ import annotations

from pathlib import Path

from ..main import (  # noqa: F401  (re-registered below)
    _SessionIsolatedFastMCP,
    append_evidence_to_fragment,
    build_research_packet,
    inspect_rejected_research_proposals,
    propose_build_patterns,
    propose_deep_research_records,
    propose_research_fragments,
    propose_semantic_edges,
    submit_revalidation_result,
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
    append_evidence_to_fragment,
    build_research_packet,
    inspect_rejected_research_proposals,
    propose_build_patterns,
    propose_deep_research_records,
    propose_research_fragments,
    propose_semantic_edges,
    submit_revalidation_result,
    validate_researcher_output,
)

for _fn in _TOOLS:
    mcp.tool()(_fn)

if __name__ == "__main__":
    mcp.run()
