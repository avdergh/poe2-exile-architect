# Meta Archetype Trend Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe meta archetype/sample trend adapter that exposes unavailable status honestly
unless a real aggregate provider supplies build-level trend rows.

**Architecture:** Extend `server/live/meta.py` with pure shaping helpers and a cached live wrapper.
Expose the adapter through one MCP tool, and let lifecycle cohort analysis optionally consume
sanitized trend rows as context. Keep build-level trend evidence separate from ascendancy
popularity and reference-build calibration.

**Tech Stack:** Python standard library, FastMCP, pytest, `scripts/verify.ps1`.

---

## File Structure

- Create: `docs/architecture/phase-03j-meta-archetype-trends.md`
  - Technical contract and boundaries.
- Modify: `server/live/meta.py`
  - Add pure trend shaping and cached live wrapper.
- Modify: `server/knowledge/lifecycle_cohort.py`
  - Optionally attach sanitized archetype trend context when provided.
- Modify: `server/main.py`
  - Add MCP tool `get_meta_archetype_trends` and pass trend context into lifecycle research.
- Modify: `tests/test_live_meta.py`
  - Add focused tests for unavailable payloads and controlled aggregate fixtures.
- Modify: `tests/test_lifecycle.py`
  - Add cohort consumption test.
- Modify: `tests/test_server.py`
  - Add tool-surface and forwarding tests.
- Modify: `README.md` and `server/ASSISTANT_GUIDE.md`
  - Document that ascendancy popularity is available now, while build-level trend rows are only
    available when a real aggregate provider supplies them.

---

### Task 1: RED live-meta tests

- [x] **Step 1: Add unavailable-payload test**

Add a test proving that the current build-index style payload returns `ok: false`,
`kind == "archetype_trends"`, and an `unavailableReason` instead of inventing skill trends.

- [x] **Step 2: Add controlled aggregate fixture test**

Add a test with a selected league containing aggregate `archetypes` rows. Assert the adapter keeps
only safe fields: `skill`, `ascendancy`, `sampleCount`, `share`, `trend`, and `evidenceTags`.

- [x] **Step 3: Run RED**

Run targeted tests and expect failure because `shape_archetype_trends` does not exist yet.

---

### Task 2: Implement pure trend adapter

- [x] **Step 1: Add `shape_archetype_trends`**

Select the league using the existing league-selection helper. If aggregate rows are absent, return
an unavailable result with an explicit reason.

- [x] **Step 2: Normalize aggregate rows**

Map controlled row fields into the safe public shape. Normalize `percentage`/`share` into a
0-1 `share`, convert trend values using the existing trend helper, and drop raw gear/tree/build
fields.

- [x] **Step 3: Add `get_archetype_trends`**

Use the same network/cache pattern as `get_meta_builds`; on upstream failure, fall back to cached
data and mark the result stale when possible.

---

### Task 3: Lifecycle/MCP integration

- [x] **Step 1: Add lifecycle cohort trend context**

When `meta["archetypeTrends"]` contains available rows, attach matching sanitized rows under
`archetypeTrendContext` and add `live-archetype-trends` to evidence tags.

- [x] **Step 2: Add MCP tool**

Expose `get_meta_archetype_trends(league?, limit?)`, returning unavailable status rather than an
exception when the live source lacks aggregate rows.

- [x] **Step 3: Pass trend context into lifecycle research**

`suggest_build_lifecycle` and `analyze_lifecycle_cohort` should fetch trends opportunistically and
continue when unavailable.

---

### Task 4: Docs, verification, review, commit

- [x] **Step 1: Update docs**

Update README and assistant guide with the distinction between current ascendancy popularity and
future/provider-backed build-level trend rows.

- [x] **Step 2: Run focused tests**

Run the new live-meta tests plus lifecycle/server tests touched by this phase.

- [x] **Step 3: Run layered verification**

Run `.\scripts\verify.ps1 quick` and `.\scripts\verify.ps1 noncompute`.

- [x] **Step 4: Request subagent code review**

Use one focused code-review subagent for the 3J diff, then address Critical/Important feedback.

- [x] **Step 5: Commit**

Commit the completed Phase 3J change on `codex/phase-3-lifecycle`.

---

## Self-Review

- Spec coverage: The plan covers unavailable behavior, controlled aggregate shaping, lifecycle
  consumption, MCP exposure, docs, verification, subagent review, and commit.
- Placeholder scan: No implementation placeholder remains; each task has a concrete expected
  behavior.
- Type consistency: Public names are `shape_archetype_trends`, `get_archetype_trends`, and
  `get_meta_archetype_trends`; lifecycle field is `archetypeTrendContext`.
