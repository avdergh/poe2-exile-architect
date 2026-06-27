# PoE2 BD Creator Project Spec

Last updated: 2026-06-27

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
- Phase 3M: lifecycle numeric range evaluation for engine-computed endgame stage snapshots.

## Current work

### Phase 3N: mature build learning pipeline design

Status: design in progress; pre-design subagent review completed; formal design spec drafted in
`docs/superpowers/specs/2026-06-27-mature-build-learning-design.md`; implementation plan and code
must wait for user approval of the design.

Goal: add a current-season mature build learning layer that samples popular mature BD cases,
sanitizes them, stores structured technique candidates with provenance/tags/freshness metadata, and
prepares a later teacher-student evaluation loop without copying mature builds.

Scope:

- Use SQLite as the trusted fact store for mature learning data, with JSON payload fields, edge
  tables for graph-like relationships, and later optional FTS/vector recall as derived retrieval
  layers.
- Store source snapshots, sanitized mature build cases, technique candidates, and technique edges.
- Preserve `creator_visible` / `evaluator_only` and `train_context` / `eval_holdout` boundaries so
  Phase 3O can evaluate generated routes without leaking answers to the creator.
- Add multi-dimensional tags for passive tree, gear, skills, defenses, scaling, sustain, lifecycle
  stage, mechanism role, source evidence, budget, and PoB modelability.
- Keep user feedback local; do not write user-specific lessons into global seed knowledge.
- Do not auto-promote candidates, alter route synthesis, or implement active knowledge expiration in
  Phase 3N.

Confirmation gates:

- Ask the user before implementing any active knowledge expiration/downweighting policy.
- Ask the user before adding an automated live periodic fetcher.
- Ask the user before using mature candidates to directly influence route synthesis.
- Ask the user before auto-promoting candidates to durable technique cards.
- Ask the user before adding vector DB or external graph DB infrastructure.

## Review and verification policy

- Before each new feature slice, send overall goal, current phase, requirement goal, and proposed
  implementation to a subagent for design/spec pre-review.
- Post-implementation code review is the default gate before commit.
- Post-implementation spec review is required only when interface, requirement semantics, evidence
  boundary, safety boundary, or user-output contract changes.
- Write local technical docs before code for key features.
- Use TDD for behavior changes: RED test, confirm failure, implement, confirm GREEN.
- Skill instructions must be loaded from the exact skill root map shown in the active session.
  In particular, `superpowers:*` skills are plugin skills under the `openai-curated/superpowers`
  cache root, not `.codex/skills/.system`.
- Preferred verification ladder:
  1. targeted tests for the touched feature;
  2. `.\scripts\verify.ps1 quick`;
  3. `.\scripts\verify.ps1 noncompute` before broader lifecycle/MCP commits;
  4. `compute` / `full` only for engine/PoB/optimizer/runtime changes.

## Near backlog

- Mature build sample ingestion: safe, fresh provider/corpus pipeline for poe.ninja/pobb.in/forum
  samples without copying raw build content into recommendations.
- Teacher-student mature build evaluation loop: creator subagent generates lifecycle routes from
  sanitized briefs; evaluator compares against held-out mature evidence and distills gap candidates.
- Candidate promotion and revalidation: promote only with multi-source evidence, engine delta, or
  explicit review; stale/downweight strategy requires user confirmation.
- Passive tree research: graph/search strategy for large passive tree, non-connected selections,
  jewel radius effects, and threshold interactions.
- Technique memory relevance: cap/sort durable technique cards by patch compatibility and route
  relevance as local memory grows.
- User feedback loop: richer diagnosis from feedback such as damage low, deaths, mana/sustain, slow
  clear, slow bossing, and promote only validated lessons.
