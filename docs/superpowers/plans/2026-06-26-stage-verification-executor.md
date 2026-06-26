# Stage Verification Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only verifier that evaluates the active PoB build against a lifecycle stage's verification budget.

**Architecture:** Keep check semantics in `server/knowledge/lifecycle_verification.py` as pure functions so fast tests do not boot PoB. Add one MCP tool in `server/main.py` that collects active build stats/defenses and passes them to the pure evaluator.

**Tech Stack:** Python standard library, FastMCP, existing PoB engine wrappers, pytest, `scripts/verify.ps1`.

---

## File Structure

- Create: `docs/architecture/phase-03e-stage-verification-executor.md`
  - Local technical contract for the executor.
- Modify: `server/knowledge/lifecycle_verification.py`
  - Add pure metric extraction and target-check evaluation.
- Modify: `server/main.py`
  - Add `verify_lifecycle_stage(stage, state?, build_id?)`.
- Modify: `tests/test_lifecycle.py`
  - Add pure evaluator RED/GREEN tests.
- Modify: `tests/test_server.py`
  - Add MCP surface and active-build forwarding tests.
- Modify: `README.md` and `server/ASSISTANT_GUIDE.md`
  - Explain the difference between planning a verification budget and executing a stage check.

---

### Task 1: RED pure lifecycle verifier tests

**Files:**
- Modify: `tests/test_lifecycle.py`

- [ ] **Step 1: Add failing tests**

```python
def test_verify_stage_metrics_fails_maps_entry_when_resists_and_sustain_are_low():
    from server.knowledge import lifecycle_verification

    result = lifecycle_verification.verify_stage_metrics(
        "maps_entry",
        stats={"TotalDPS": 20000, "Life": 1200, "Mana": 40, "ManaCost": 80},
        defenses={
            "resistances": {"fire": 55, "cold": 76, "lightning": 70},
            "totalEHP": 2400,
        },
    )

    assert result["ok"] is True
    assert result["pass"] is False
    assert result["status"] == "failed"
    assert {"resists_capped", "basic_defense_online", "sustain_ok"} <= set(result["failedChecks"])


def test_verify_stage_metrics_passes_maps_entry_with_engine_values():
    from server.knowledge import lifecycle_verification

    result = lifecycle_verification.verify_stage_metrics(
        "maps_entry",
        stats={"TotalDPS": 90000, "Life": 2600, "Mana": 500, "ManaCost": 40},
        defenses={
            "resistances": {"fire": 75, "cold": 79, "lightning": 76},
            "totalEHP": 12000,
        },
    )

    assert result["pass"] is True
    assert result["status"] == "passed"
    assert result["failedChecks"] == []
```

- [ ] **Step 2: Run RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py::test_verify_stage_metrics_fails_maps_entry_when_resists_and_sustain_are_low tests/test_lifecycle.py::test_verify_stage_metrics_passes_maps_entry_with_engine_values -q`

Expected: FAIL because `verify_stage_metrics` does not exist.

---

### Task 2: Implement pure verifier

**Files:**
- Modify: `server/knowledge/lifecycle_verification.py`

- [ ] **Step 1: Add `verify_stage_metrics`**

Implementation requirements:

- Call `plan_stage_verification(stage, state=state)`.
- Normalize stats and defenses into `observations`.
- Evaluate known checks from the stage plan.
- Unknown checks stay in `unknownChecks`.
- Return `passed` only when every target check is known and passing.

- [ ] **Step 2: Run lifecycle tests**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py -q`

Expected: PASS.

---

### Task 3: Add MCP active-build executor

**Files:**
- Modify: `tests/test_server.py`
- Modify: `server/main.py`

- [ ] **Step 1: Add failing server tests**

```python
def test_verify_lifecycle_stage_tool_registered():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "verify_lifecycle_stage" in names


def test_verify_lifecycle_stage_collects_active_build_metrics(monkeypatch):
    from server import main

    class _Stub:
        def get_stats(self, keys=None):
            return {"stats": {"Life": 2600, "Mana": 500, "ManaCost": 40, "TotalDPS": 90000}}

        def get_defenses(self):
            return {"resistances": {"fire": 75, "cold": 79, "lightning": 76}, "totalEHP": 12000}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    result = main.verify_lifecycle_stage("maps_entry", state={"level": 68})

    assert result["ok"] is True
    assert result["stage"] == "maps_entry"
    assert result["pass"] is True
    assert result["stateSnapshot"]["level"] == 68
```

- [ ] **Step 2: Run RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_server.py::test_verify_lifecycle_stage_tool_registered tests/test_server.py::test_verify_lifecycle_stage_collects_active_build_metrics -q`

Expected: FAIL because the tool is not registered.

- [ ] **Step 3: Add MCP tool**

Implementation requirements:

- Fetch plan first to know the requested stat keys.
- Read `get_stats(keys)` and `get_defenses()` from the active engine.
- Call `lifecycle.lifecycle_verification.verify_stage_metrics`.
- Preserve `buildId` when supplied.

---

### Task 4: Docs, verification, commit

**Files:**
- Modify: `README.md`
- Modify: `server/ASSISTANT_GUIDE.md`

- [ ] **Step 1: Update docs**

Document:

- `plan_lifecycle_stage_verification` returns a checklist/budget.
- `verify_lifecycle_stage` executes a read-only active-build check.

- [ ] **Step 2: Run quick verification**

Run: `.\scripts\verify.ps1 quick`

Expected: PASS.

- [ ] **Step 3: Run noncompute verification**

Run: `.\scripts\verify.ps1 noncompute`

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```powershell
git add docs/architecture/phase-03e-stage-verification-executor.md docs/superpowers/plans/2026-06-26-stage-verification-executor.md server/knowledge/lifecycle_verification.py server/main.py tests/test_lifecycle.py tests/test_server.py README.md server/ASSISTANT_GUIDE.md
git commit -m "feat: add lifecycle stage verification executor"
```

Expected: commit succeeds on `codex/phase-3-lifecycle`.

---

## Self-Review

- Spec coverage: The plan covers pure evaluator behavior, MCP active-build execution, docs, tests,
  and layered verification.
- Placeholder scan: No TBD or implementation placeholders.
- Type consistency: Public helper is `verify_stage_metrics`; MCP tool is `verify_lifecycle_stage`.
