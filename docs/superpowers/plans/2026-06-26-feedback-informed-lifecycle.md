# Feedback-Informed Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed local lifecycle feedback and promoted technique memory back into later route
synthesis as advisory context.

**Architecture:** Add a small memory summarizer inside `server/knowledge/lifecycle.py`. It derives
exact-build repeated failure patterns from `feedback_reflections`, annotates stages with
memory-specific warnings/actions, and labels promoted technique cards as current/stale/unknown
against the local compatibility claim.

**Tech Stack:** Python standard library, existing JSON lifecycle memory, FastMCP, pytest,
`scripts/verify.ps1`.

**Status:** Implemented and verified. Post-implementation review required one follow-up fix:
`general_feedback` memory actions must stay neutral and must not claim a transition gate is
satisfied.

---

## File Structure

- Create: `docs/architecture/phase-03k-feedback-informed-lifecycle.md`
  - Contract and boundaries for `memoryContext`.
- Modify: `server/knowledge/lifecycle.py`
  - Add internal memory summarizer and stage memory annotation.
- Modify: `tests/test_lifecycle.py`
  - Add RED/GREEN tests for exact-build feedback reuse, single-feedback safety, stale technique
    downweighting, and cross-build isolation.
- Modify: `README.md` and `server/ASSISTANT_GUIDE.md`
  - Explain that feedback memory is advisory and patch-scoped.
- Create: `docs/superpowers/plans/2026-06-26-feedback-informed-lifecycle.md`
  - This implementation plan.

---

### Task 1: RED tests for advisory memory context

- [x] **Step 1: Add repeated-feedback route test**

Add a test in `tests/test_lifecycle.py`:

```python
def test_research_lifecycle_includes_repeated_feedback_memory_context(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))
    goal = "给我一个新手能玩的强力终局BD"
    first = lifecycle.research_build_lifecycle(goal, persist=True)

    lifecycle.record_build_feedback(first["buildId"], "maps_entry", "刚进异界暴毙")
    lifecycle.record_build_feedback(first["buildId"], "maps_entry", "还是容易死")
    second = lifecycle.research_build_lifecycle(goal, persist=False)

    assert second["buildId"] == first["buildId"]
    assert second["memoryContext"]["policy"]["advisoryOnly"] is True
    assert second["memoryContext"]["repeatedFailurePatterns"][0]["stage"] == "maps_entry"
    maps = next(stage for stage in second["stages"] if stage["id"] == "maps_entry")
    assert maps["memoryWarnings"]
    assert maps["memoryRecommendedActions"]
```

- [x] **Step 2: Add single-feedback safety test**

Add:

```python
def test_single_feedback_is_recent_context_but_not_stage_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))
    route = lifecycle.research_build_lifecycle("闪电新手开荒BD", persist=True)

    lifecycle.record_build_feedback(route["buildId"], "maps_entry", "缺蓝")
    updated = lifecycle.research_build_lifecycle("闪电新手开荒BD", persist=False)

    assert updated["memoryContext"]["recentEpisodicReflections"]
    assert updated["memoryContext"]["repeatedFailurePatterns"] == []
    maps = next(stage for stage in updated["stages"] if stage["id"] == "maps_entry")
    assert maps["memoryWarnings"] == []
```

- [x] **Step 3: Add cross-build isolation test**

Add:

```python
def test_feedback_memory_does_not_cross_build_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))
    route_a = lifecycle.research_build_lifecycle("闪电新手开荒BD", persist=True)
    route_b = lifecycle.research_build_lifecycle("火焰新手开荒BD", persist=True)

    lifecycle.record_build_feedback(route_a["buildId"], "maps_entry", "暴毙")
    lifecycle.record_build_feedback(route_a["buildId"], "maps_entry", "还是死")
    updated_b = lifecycle.research_build_lifecycle("火焰新手开荒BD", persist=False)

    assert updated_b["buildId"] == route_b["buildId"]
    assert updated_b["memoryContext"]["repeatedFailurePatterns"] == []
```

- [x] **Step 4: Add stale technique downweight test**

Add:

```python
def test_stale_promoted_technique_is_downweighted(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))
    feedback = lifecycle.record_build_feedback("life-test", "maps_entry", "暴毙")
    lifecycle.promote_technique_memory(
        [feedback["feedbackId"]],
        "Old patch lesson",
        current_patch="0.5.3",
        current_tree="0_5_old",
    )
    monkeypatch.setattr(
        lifecycle,
        "current_compatibility_claim",
        lambda: {"game_patch": "0.5.4", "passive_tree": "0_5_new"},
    )

    route = lifecycle.research_build_lifecycle("任意强力BD", persist=False)

    card = route["memoryContext"]["techniqueCards"][0]
    assert card["compatibilityStatus"] == "stale"
    assert card["influence"] == "downweighted"
    assert route["memoryContext"]["stalenessNotes"]
```

- [x] **Step 5: Run RED**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py::test_research_lifecycle_includes_repeated_feedback_memory_context tests/test_lifecycle.py::test_single_feedback_is_recent_context_but_not_stage_warning tests/test_lifecycle.py::test_feedback_memory_does_not_cross_build_ids tests/test_lifecycle.py::test_stale_promoted_technique_is_downweighted -q
```

Expected: FAIL because `memoryContext`, `memoryWarnings`, and `memoryRecommendedActions` are not
implemented yet.

---

### Task 2: Implement memory summarizer and stage annotation

- [x] **Step 1: Add helper functions**

In `server/knowledge/lifecycle.py`, add internal helpers near feedback-memory code:

- `_summarize_lifecycle_memory(build_id: str) -> dict[str, Any]`
- `_compatibility_for_card(card: dict[str, Any], claim: dict[str, Any]) -> tuple[str, str]`
- `_memory_annotation_for_stage(stage_id: str, memory_context: dict[str, Any]) -> dict[str, list[str]]`

The summarizer must derive repeated failure patterns from `feedback_reflections`, grouped by exact
`buildId`, `stage`, and `failurePattern`, with threshold `count >= 2`.

- [x] **Step 2: Attach memory context before stage creation**

In `research_build_lifecycle`, compute `build_id` before constructing stages, call
`_summarize_lifecycle_memory(build_id)`, and pass the result to `_stage_plan(...)`.

- [x] **Step 3: Add stage fields**

Extend `_stage_plan(...)` to always include:

```python
"memoryWarnings": [],
"memoryRecommendedActions": [],
```

When repeated failures match the stage, fill those fields with conservative text/actions from
`_recommended_actions(stage_id, pattern)`.

- [x] **Step 4: Add route field**

Add `"memoryContext": memory_context` to the route result. The route must still include
`qualityGate`; memory absence must not make the quality gate fail.

- [x] **Step 5: Run GREEN targeted tests**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py -q
```

Expected: PASS.

---

### Task 3: Docs and assistant guidance

- [x] **Step 1: Update README**

In the lifecycle section, say feedback memory now reappears as advisory `memoryContext` and stage
memory warnings after repeated exact-build feedback. It does not replace PoB verification.

- [x] **Step 2: Update server assistant guide**

Add a short instruction: when `memoryContext.repeatedFailurePatterns` exists, mention the repeated
player issue and stabilize that stage before transition; treat stale technique cards as historical
context requiring re-verification.

---

### Task 4: Verification, review, commit

- [x] **Step 1: Run focused tests**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py tests/test_server.py -q
```

- [x] **Step 2: Run quick verification**

Run:

```powershell
.\scripts\verify.ps1 quick
```

- [x] **Step 3: Run noncompute verification**

Run:

```powershell
.\scripts\verify.ps1 noncompute
```

- [x] **Step 4: Request post-implementation reviews**

Request one spec review and one code review. This feature changes memory evidence semantics, so the
conditional post-implementation spec review is required.

- [x] **Step 5: Commit**

Commit with:

```powershell
git commit -m "feat: add feedback-informed lifecycle memory context"
```

---

## Self-Review

- Spec coverage: Covers advisory memory context, exact-build repeated patterns, single-feedback
  safety, stale technique downweighting, stage annotations, docs, verification, and dual review.
- Placeholder scan: No placeholder tasks remain.
- Type consistency: Public output names are `memoryContext`, `memoryWarnings`, and
  `memoryRecommendedActions`.
