# PoE2 BD Creator Project Spec

Last updated: 2026-06-26

This is the local handoff document for context compaction or session switching. It summarizes the
project goal, completed capabilities, current work, review policy, and likely next backlog. Keep it
updated at the end of each meaningful feature slice.

## Overall goal

Build a reliable Path of Exile 2 build creator agent. The agent should help a beginner ask for a
strong build, research current-season evidence, explain the core mechanic, produce a lifecycle route
from campaign starter to transition to endgame, verify what can be verified with PoB2/engine data,
and learn from user feedback without turning unverified anecdotes into durable rules.

## Non-negotiable boundaries

- Freshness matters: current patch/tree/season data must be checked before current-meta claims.
- PoB/engine-computed numbers are the authority for numeric DPS/EHP/resistance claims.
- poe.ninja, forums, pobb.in, and reference builds are research/calibration sources, not templates
  to copy blindly.
- Reference samples must not leak copyable raw build content such as PoB codes, gear lists, passive
  node lists, or full trees.
- Feedback memory is advisory until repeatedly observed or promoted with evidence and patch/tree
  scope.
- If a mechanism cannot be modeled by the engine, the output must say so explicitly.

## Completed capability map

### Foundation and freshness

- Local MCP/server tool surface for PoE2 build work.
- Bundled corpus lookup for skills, supports, uniques, mechanics, and reference calibration.
- PoB2 runtime integration and local 0.5.4 validated runtime certification.
- Freshness gate with GGG patch/tree, PoB compatibility, and poe.ninja snapshot evidence.
- Verification strategy split into `quick`, `noncompute`, `compute`, and `full` so small lifecycle
  changes do not always pay full compute cost.

### Build optimization foundation

- Engine-backed build evaluation and active build state.
- Reference build browsing and benchmarking as calibration only.
- Levers/rank-upgrades/support/passive/gear/jewel helpers.
- Defensive scaffolding and stage repair actions for beginner-friendly iteration.

### Phase 3 lifecycle research

- Phase 3A: lifecycle route scaffold, classification, stages, transition gates, memory schema.
- Phase 3B: cohort evidence from non-copyable reference patterns and live-meta context.
- Phase 3C: transition readiness evaluator.
- Phase 3D: stage verification budgets.
- Phase 3E: stage verification executor.
- Phase 3F: lifecycle source/guide text evidence extraction.
- Phase 3G: source-derived transition gates.
- Phase 3H: stage-aware repair actions.
- Phase 3I: lifecycle route quality gate.
- Phase 3J: safe meta archetype trend adapter.
- Phase 3K: feedback-informed lifecycle memory context.
- Phase 3L: lifecycle route evaluation harness.

## Current work

### Phase 3L: lifecycle evaluation harness

Status: completed; targeted tests, quick verification, noncompute verification, code review, and
spec/evidence-boundary review passed.

Goal: add a pure evaluation harness for route outputs so development/regression checks can ask
whether a lifecycle route is structurally complete, evidence-labeled, aligned with safe reference
cohort patterns, and honest about unknowns.

Scope:

- Add `server/knowledge/lifecycle_eval.py`.
- Add MCP tool `evaluate_lifecycle_route`.
- Add focused tests in `tests/test_lifecycle_eval.py`.
- Do not run PoB compute, network fetches, or memory writes.
- Do not judge numeric range closeness in v1; engine-computed evidence only prevents local numeric
  claims from being flagged as unsupported.

## Review and verification policy

- Before each new feature slice, send overall goal, current phase, requirement goal, and proposed
  implementation to a subagent for design/spec pre-review.
- Post-implementation code review is the default gate before commit.
- Post-implementation spec review is required only when interface, requirement semantics, evidence
  boundary, safety boundary, or user-output contract changes.
- Write local technical docs before code for key features.
- Use TDD for behavior changes: RED test, confirm failure, implement, confirm GREEN.
- Preferred verification ladder:
  1. targeted tests for the touched feature;
  2. `.\scripts\verify.ps1 quick`;
  3. `.\scripts\verify.ps1 noncompute` before broader lifecycle/MCP commits;
  4. `compute` / `full` only for engine/PoB/optimizer/runtime changes.

## Near backlog

- Evaluation v2: compare verified lifecycle stage outputs against reference numeric ranges only when
  engine-computed data is present.
- Mature build sample ingestion: safe, fresh provider/corpus pipeline for poe.ninja/pobb.in/forum
  samples without copying raw build content into recommendations.
- Passive tree research: graph/search strategy for large passive tree, non-connected selections,
  jewel radius effects, and threshold interactions.
- Technique memory relevance: cap/sort durable technique cards by patch compatibility and route
  relevance as local memory grows.
- User feedback loop: richer diagnosis from feedback such as damage low, deaths, mana/sustain, slow
  clear, slow bossing, and promote only validated lessons.
