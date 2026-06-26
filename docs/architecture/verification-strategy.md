# Verification Strategy

## Purpose

The full pytest suite is intentionally expensive because `tests/test_compute.py` certifies the
Path-of-Building runtime and optimizer behavior. Running that suite after every small knowledge-layer
change wastes development time. Verification should be layered by risk.

## Profiles

Use `scripts/verify.ps1` from the repository root:

- `.\scripts\verify.ps1 quick`
  - Default inner loop.
  - Runs lifecycle/server/project-config tests plus static checks.
  - Good for MCP tool surface, docs, lifecycle memory, and research-workflow changes.
- `.\scripts\verify.ps1 noncompute`
  - Broad regression without `tests/test_compute.py`.
  - Good before committing knowledge, freshness, corpus, docs, and MCP changes.
- `.\scripts\verify.ps1 compute`
  - Heavy PoB compute certification only.
  - Use when engine, optimization, item generation, support ranking, or PoB runtime behavior changes.
- `.\scripts\verify.ps1 full`
  - Full release/merge gate.
  - Use before major integration, runtime upgrades, or when a change touches cross-cutting engine
    behavior.
- `.\scripts\verify.ps1 lint`
  - Static checks and manifest validation only.

## Agent Rule

For small Phase 3 lifecycle increments, run focused RED/GREEN tests first, then `quick`. Escalate to
`noncompute` before commit when the change touches shared server behavior. Run `full` only at major
milestones or when compute/runtime behavior is in scope.
