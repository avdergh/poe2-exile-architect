"""poe-learning-mcp: Phase 7 comparative-learning campaign state, blind Create packets and the
local append-only Learning Memory. Judge/PoB tooling lives in the build server.
"""

from __future__ import annotations

from pathlib import Path

from ..main import (  # noqa: F401  (re-registered below)
    _SessionIsolatedFastMCP,
    append_learning_memory_correction,
    claim_learning_phase,
    complete_learning_case_feedback,
    fail_learning_phase,
    get_learning_campaign_status,
    get_learning_create_packet,
    intake_learning_case,
    load_learning_reference_case,
    pause_learning_campaign,
    promote_technique_memory,
    propose_learning_lesson,
    query_learning_memory,
    resume_learning_campaign,
    retry_learning_phase,
    start_learning_campaign,
    submit_learning_comparison,
    submit_learning_create_result,
    submit_learning_profile,
    submit_learning_rereview,
)

_GUIDE = Path(__file__).parent.parent / "MCP_LEARNING_BOOTSTRAP.md"
try:
    _INSTRUCTIONS: str | None = _GUIDE.read_text(encoding="utf-8")
except OSError:
    _INSTRUCTIONS = (
        "Exile Architect learning server: Phase 7 campaign state, blind Create packets and "
        "append-only Learning Memory. Judge scores are advisory only."
    )

mcp = _SessionIsolatedFastMCP("poe-learning-mcp", instructions=_INSTRUCTIONS)

_TOOLS = (
    append_learning_memory_correction,
    claim_learning_phase,
    complete_learning_case_feedback,
    fail_learning_phase,
    get_learning_campaign_status,
    get_learning_create_packet,
    intake_learning_case,
    load_learning_reference_case,
    pause_learning_campaign,
    promote_technique_memory,
    propose_learning_lesson,
    query_learning_memory,
    resume_learning_campaign,
    retry_learning_phase,
    start_learning_campaign,
    submit_learning_comparison,
    submit_learning_create_result,
    submit_learning_profile,
    submit_learning_rereview,
)

for _fn in _TOOLS:
    mcp.tool()(_fn)

if __name__ == "__main__":
    mcp.run()
