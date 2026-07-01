"""Internal deterministic judge for Phase 1.

The judge is intentionally not exposed as an MCP tool yet. External agents should use it only
through phase-specific scripts and tests until the evaluation contract is stable.
"""

from __future__ import annotations

__all__ = [
    "benchmark",
    "comparison",
    "evaluator",
    "fixtures",
    "modelability",
    "models",
    "rules",
    "runner",
    "scoring",
]
