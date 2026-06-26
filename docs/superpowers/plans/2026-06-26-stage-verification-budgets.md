# Stage Verification Budgets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit stage-level verification budgets so lifecycle routes can tell the agent what must be checked in PoB for each campaign/map/endgame stage.

**Architecture:** Add a focused `server/knowledge/lifecycle_verification.py` module that owns static verification budgets and returns stage verification plans. `server/knowledge/lifecycle.py` will call it when constructing stage plans, replacing the previous generic verification note with concrete budgets. One MCP inspection tool exposes the same plan directly.

**Tech Stack:** Python standard library, existing lifecycle stage ids, FastMCP, pytest, `scripts/verify.ps1`.

---

## File Structure

- Create: `docs/architecture/phase-03d-stage-verification-budgets.md`
  - Local technical contract.
- Create: `server/knowledge/lifecycle_verification.py`
  - Stage budgets and plan helpers.
- Modify: `server/knowledge/lifecycle.py`
  - Attach stage verification plans to lifecycle stage output.
- Modify: `server/main.py`
  - Add MCP tool `plan_lifecycle_stage_verification(stage, build_id?, state?)`.
- Modify: `README.md` and `server/ASSISTANT_GUIDE.md`
  - Document stage verification budgets.
- Modify: `tests/test_lifecycle.py`
  - Add tests for budgets and lifecycle integration.
- Modify: `tests/test_server.py`
  - Add tool surface and forwarding tests.

---

### Task 1: RED lifecycle verification tests

**Files:**
- Modify: `tests/test_lifecycle.py`

- [ ] **Step 1: Add failing tests**

```python
def test_stage_verification_plan_for_maps_entry_requires_resists_and_sustain():
    from server.knowledge import lifecycle_verification

    plan = lifecycle_verification.plan_stage_verification("maps_entry")

    assert plan["ok"] is True
    assert plan["stage"] == "maps_entry"
    assert plan["levelTarget"] >= 65
    assert "get_defenses" in plan["engineTools"]
    assert "resists_capped" in plan["targetChecks"]
    assert "sustain_ok" in plan["targetChecks"]


def test_research_build_lifecycle_attaches_concrete_stage_verification():
    result = lifecycle.research_build_lifecycle("给我一个新手能懂的终局BD")
    maps_entry = next(stage for stage in result["stages"] if stage["id"] == "maps_entry")

    assert maps_entry["verification"]["status"] == "planned"
    assert maps_entry["verification"]["levelTarget"] >= 65
    assert "gearAssumption" in maps_entry["verification"]
    assert "evaluate_build" in maps_entry["verification"]["engineTools"]
```

- [ ] **Step 2: Run RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py -q`

Expected: FAIL because `lifecycle_verification` does not exist and lifecycle stages still contain a generic verification note.

---

### Task 2: Implement verification budgets

**Files:**
- Create: `server/knowledge/lifecycle_verification.py`
- Modify: `server/knowledge/lifecycle.py`

- [ ] **Step 1: Add `lifecycle_verification.py`**

Implementation requirements:

- Define budgets for all six lifecycle stages.
- Include representative `levelTarget`, `passivePointBudget`, `gearAssumption`, `engineTools`,
  `metricGroups`, `targetChecks`, `failureModes`, and `caveats`.
- Add:

```python
def plan_stage_verification(stage: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    ...
```

- Unknown stages return `{ok:false, error:"unknown lifecycle stage"}`.

- [ ] **Step 2: Integrate with lifecycle stage plans**

In `_stage_plan`, replace the generic verification object with:

```python
"verification": lifecycle_verification.plan_stage_verification(stage["id"])
```

- [ ] **Step 3: Run lifecycle tests**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py -q`

Expected: PASS.

---

### Task 3: MCP tool and docs

**Files:**
- Modify: `tests/test_server.py`
- Modify: `server/main.py`
- Modify: `README.md`
- Modify: `server/ASSISTANT_GUIDE.md`

- [ ] **Step 1: Add failing server test**

```python
def test_plan_lifecycle_stage_verification_tool_forwards_state(monkeypatch):
    from server import main

    monkeypatch.setattr(
        main.lifecycle.lifecycle_verification,
        "plan_stage_verification",
        lambda stage, state=None: {"ok": True, "stage": stage, "state": state},
    )

    result = main.plan_lifecycle_stage_verification("maps_entry", state={"level": 68})

    assert result["ok"] is True
    assert result["stage"] == "maps_entry"
    assert result["state"]["level"] == 68
```

- [ ] **Step 2: Run RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_server.py::test_plan_lifecycle_stage_verification_tool_forwards_state -q`

Expected: FAIL because the MCP tool does not exist yet.

- [ ] **Step 3: Add tool**

Add:

```python
@mcp.tool()
def plan_lifecycle_stage_verification(
    stage: str,
    state: dict[str, Any] | None = None,
    build_id: str = "",
) -> dict[str, Any]:
    ...
```

Tool count becomes 74.

- [ ] **Step 4: Update docs**

README and Assistant Guide should explain that stage verification plans are not computed results.

- [ ] **Step 5: Run server tests**

Run: `.\.tools\uv\uv.exe run pytest tests/test_server.py -q`

Expected: PASS.

---

### Task 4: Verification and commit

**Files:**
- All changed files.

- [ ] **Step 1: Run quick verification**

Run: `.\scripts\verify.ps1 quick`

Expected: PASS.

- [ ] **Step 2: Run noncompute verification**

Run: `.\scripts\verify.ps1 noncompute`

Expected: PASS.

- [ ] **Step 3: Commit**

Run:

```powershell
git add docs/architecture/phase-03d-stage-verification-budgets.md docs/superpowers/plans/2026-06-26-stage-verification-budgets.md server/knowledge/lifecycle_verification.py server/knowledge/lifecycle.py server/main.py README.md server/ASSISTANT_GUIDE.md tests/test_lifecycle.py tests/test_server.py
git commit -m "feat: add stage verification budgets"
```

Expected: commit succeeds on `codex/phase-3-lifecycle`.

---

## Self-Review

- Spec coverage: The plan covers stage verification budgets, lifecycle output integration, MCP exposure, docs, tests, and fast verification.
- Placeholder scan: No placeholder tasks; every public behavior has a concrete test.
- Type consistency: Public helper is `lifecycle_verification.plan_stage_verification`; MCP tool is `plan_lifecycle_stage_verification`.
