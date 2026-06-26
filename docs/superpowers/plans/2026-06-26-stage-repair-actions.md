# Stage Repair Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add beginner-readable repair actions to lifecycle stage verification results.

**Architecture:** Extend the pure verifier in `server/knowledge/lifecycle_verification.py` with a small action mapper based on failed/unknown checks. MCP output inherits the actions automatically through `verify_lifecycle_stage`.

**Tech Stack:** Python standard library, pytest, `scripts/verify.ps1`.

---

## File Structure

- Create: `docs/architecture/phase-03h-stage-repair-actions.md`
  - Technical contract.
- Modify: `server/knowledge/lifecycle_verification.py`
  - Add `recommendedActions` generation.
- Modify: `tests/test_lifecycle.py`
  - Add RED/GREEN tests for repair actions.
- Modify: `server/ASSISTANT_GUIDE.md`
  - Tell the assistant to report repair actions when a stage fails.

---

### Task 1: RED repair action tests

**Files:**
- Modify: `tests/test_lifecycle.py`

- [ ] **Step 1: Add failing tests**

```python
def test_verify_stage_metrics_returns_repair_actions_for_failed_maps_entry():
    from server.knowledge import lifecycle_verification

    result = lifecycle_verification.verify_stage_metrics(
        "maps_entry",
        stats={"Life": 1200, "Mana": 40, "ManaCost": 80},
        defenses={"resistances": {"fire": 55, "cold": 76, "lightning": 70}, "totalEHP": 2400},
    )

    joined = " ".join(result["recommendedActions"]).lower()
    assert "resist" in joined
    assert "sustain" in joined or "mana" in joined
    assert "transition" in joined


def test_verify_stage_metrics_returns_actions_for_unknown_endgame_checks():
    from server.knowledge import lifecycle_verification

    result = lifecycle_verification.verify_stage_metrics(
        "endgame_budget",
        stats={"Life": 4000, "Mana": 500, "ManaCost": 30},
        defenses={"resistances": {"fire": 75, "cold": 75, "lightning": 75}, "totalEHP": 14000},
    )

    joined = " ".join(result["recommendedActions"]).lower()
    assert "build-defining" in joined
    assert result["status"] == "unknown"
```

- [ ] **Step 2: Run RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py::test_verify_stage_metrics_returns_repair_actions_for_failed_maps_entry tests/test_lifecycle.py::test_verify_stage_metrics_returns_actions_for_unknown_endgame_checks -q`

Expected: FAIL because `recommendedActions` is not present.

---

### Task 2: Implement action mapper

**Files:**
- Modify: `server/knowledge/lifecycle_verification.py`

- [ ] **Step 1: Add `_recommended_actions(stage, checks, failed, unknown)`**

Implementation requirements:

- Return stage-aware repair strings.
- Include a hold-transition warning for failed checks.
- Include unknown-evidence warnings for unknown endgame checks.
- Return a success action when all checks pass.

- [ ] **Step 2: Add to verifier output**

Add `recommendedActions` to `verify_stage_metrics`.

- [ ] **Step 3: Run lifecycle tests**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py -q`

Expected: PASS.

---

### Task 3: Docs, verification, commit

**Files:**
- Modify: `server/ASSISTANT_GUIDE.md`

- [ ] **Step 1: Update guide**

Document that failed/unknown stage verification must be reported with `recommendedActions`.

- [ ] **Step 2: Run quick verification**

Run: `.\scripts\verify.ps1 quick`

Expected: PASS.

- [ ] **Step 3: Run noncompute verification**

Run: `.\scripts\verify.ps1 noncompute`

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```powershell
git add docs/architecture/phase-03h-stage-repair-actions.md docs/superpowers/plans/2026-06-26-stage-repair-actions.md server/knowledge/lifecycle_verification.py tests/test_lifecycle.py server/ASSISTANT_GUIDE.md
git commit -m "feat: add repair actions to stage verification"
```

Expected: commit succeeds on `codex/phase-3-lifecycle`.

---

## Self-Review

- Spec coverage: The plan covers repair-action generation, verifier output, docs, tests, and
  layered verification.
- Placeholder scan: No TBD or placeholder implementation steps.
- Type consistency: Output field is `recommendedActions`.
