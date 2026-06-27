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

### Phase 3N: mature build learning pipeline

Status: design approved for the first implementation slice. The reviewed design spec lives in
`docs/superpowers/specs/2026-06-27-mature-build-learning-design.md`. Phase 3N.1 implementation
planning is documented in
`docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md`; pre-implementation subagent
review completed with blocking issues resolved and only small implementation-level fixes folded
into the plan. Task 1 local architecture documentation has started in
`docs/architecture/phase-03n1-mature-build-learning-store.md`. Task 2 SQLite schema/path work is
implemented with focused tests passing. Task 3 sanitizer/copyability guard is implemented with
focused tests passing. Task 4 structured fixture manifest and deterministic import are implemented
with focused tests passing. Task 5 boundary tests for visibility/scope/copy-safety/inert expiration
are implemented with focused tests passing, and no route/MCP surface files are touched.
Post-review fixes tightened candidate evidence creator visibility, recursive forbidden-key
normalization, sanitizer enum/sample/numeric validation, seed all-or-nothing import, and bundled
seed fixture smoke coverage.

Goal: add a current-season mature build learning layer that samples popular mature BD cases,
sanitizes them, stores structured technique candidates with provenance/tags/freshness metadata, and
prepares a later teacher-student evaluation loop without copying mature builds.

Scope:

- Use SQLite as the trusted fact store for mature learning data, with JSON payload fields, edge
  tables for graph-like relationships, and later optional FTS/vector recall as derived retrieval
  layers.
- Store source groups, source snapshots, sanitized mature build cases, candidate evidence,
  technique candidates, and technique edges.
- Require explicit popular/latest sampling eligibility, fixture provenance manifests, sanitizer
  allowlists, and copyability/reconstruction tests before ingesting mature samples.
- Preserve `creator_visible` / `evaluator_only` and `train_context` / `eval_holdout` boundaries so
  Phase 3O can evaluate generated routes without leaking answers to the creator.
- Add multi-dimensional tags for passive tree, gear, skills, defenses, scaling, sustain, lifecycle
  stage, mechanism role, source evidence, budget, and PoB modelability.
- Keep user feedback local; do not write user-specific lessons into global seed knowledge.
- Do not auto-promote candidates, alter route synthesis, or implement active knowledge expiration in
  Phase 3N.
- Split Phase 3N into smaller slices: schema/sanitizer/fixtures, deterministic candidate extraction
  and evidence bridge, retrieval/FTS/provenance, then optional edge population.

Current Phase 3N.1 target:

- Add SQLite schema and user-data store path for mature-learning data. (implemented)
- Add a tiny curated fixture manifest and deterministic sanitized fixture import. (implemented)
- Add an allowlist sanitizer and copyability/reconstruction tests. (implemented)
- Enforce `visibility` / `split` / `knowledge_scope` boundaries and prove local user feedback
  cannot enter global seed knowledge. (implemented)
- Keep expiration metadata inert and do not change route synthesis behavior. (implemented)

Pre-review fixes folded into the Phase 3N.1 plan:

- Schema initialization must be idempotent and refuse future DB versions without downgrading.
- `candidate_evidence` and `technique_edges` need stable primary keys.
- Sanitization must scan recursively and validate aggregate numeric range shape.
- Fixture manifests must use structured popularity/currentness/diversity fields.
- Seed fixture import must reject `user_feedback_local` even when scoped as `local_user`.

Current Phase 3N.2 target:

- 从已净化成熟案例中确定性抽取 `technique_candidates`。 (implemented, reviewed)
- 为每个候选写入 `candidate_evidence`，保留 `visibility` / `split` / `knowledge_scope`
  边界。 (implemented, reviewed)
- 从 evidence 表回算 `source_count`、`support_count`、`contradiction_count`。 (implemented,
  reviewed)
- 推导 `required_prerequisites`、`starter_risk_reason`、`transition_gate_summary` 和
  `unsafe_before_stage`，用于后续生命周期研究。 (implemented, reviewed)
- 开发前预审要求：候选 ID 必须包含 creator/evaluator/quarantine 边界 bucket；非 creator
  候选必须降为 `eval_ephemeral`；同语义跨边界样本必须拆成不同 candidate，避免 holdout
  证据撑大 creator candidate。 (implemented, reviewed)
- 代码审查修复：`candidate_evidence.evidence_id` 改为 case 级稳定键
  `{case_id, relation, extraction_method}`，避免同一 case 从 creator 改 evaluator 时旧
  creator-visible evidence 残留；candidate upsert 保留已有 `promoted` / `rejected` /
  `stale` 状态。
- 不改变 route synthesis、MCP 输出、检索、自动晋升或知识过期行为。
- 局部技术文档：
  `docs/architecture/phase-03n2-mature-candidate-extraction.md`；实施计划：
  `docs/superpowers/plans/2026-06-27-mature-learning-candidate-extraction-3n2.md`。
- Verification so far: `.\.tools\uv\uv.exe run pytest tests\test_mature_learning.py -q` and
  `.\scripts\verify.ps1 quick` pass after formatting.
- Code review and narrow evidence-boundary re-review passed after the stale-evidence fix.
- Follow-up risks for later slices: Phase 3N.3 retrieval must filter by creator-visible evidence
  instead of bare candidate rows; zero-support generated candidates should be hidden or cleaned; any
  future incremental extraction must not reuse the full-scan stale-evidence deletion behavior.

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
