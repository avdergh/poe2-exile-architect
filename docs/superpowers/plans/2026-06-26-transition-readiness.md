# Transition Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a transition-readiness evaluator that tells the agent whether a player should switch lifecycle stages now and what to fix if not.

**Architecture:** Extend the existing `server/knowledge/lifecycle.py` transition-gate model instead of creating a separate planner. The evaluator reuses default or stored gates, calls `evaluate_transition_gate`, normalizes optional user feedback with the existing feedback-pattern logic, and returns stage-aware repair actions. Expose it through one MCP tool in `server/main.py`.

**Tech Stack:** Python standard library, existing lifecycle memory JSON, FastMCP, pytest, `scripts/verify.ps1`.

---

## File Structure

- Create: `docs/architecture/phase-03c-transition-readiness.md`
  - Local technical contract.
- Modify: `docs/superpowers/plans/2026-06-26-transition-readiness.md`
  - This implementation plan.
- Modify: `server/knowledge/lifecycle.py`
  - Add `evaluate_transition_readiness`.
  - Add stage-aware feedback action helpers.
  - Include recommended actions in `record_build_feedback`.
- Modify: `server/main.py`
  - Add MCP tool `evaluate_transition_readiness(build_id?, from_stage, to_stage, state)`.
- Modify: `README.md` and `server/ASSISTANT_GUIDE.md`
  - Document readiness checks.
- Modify: `tests/test_lifecycle.py`
  - Add RED/GREEN tests for readiness and feedback actions.
- Modify: `tests/test_server.py`
  - Add tool-surface and forwarding tests.

---

### Task 1: RED lifecycle tests

**Files:**
- Modify: `tests/test_lifecycle.py`

- [ ] **Step 1: Add failing readiness tests**

```python
def test_transition_readiness_blocks_missing_gate_requirements_and_feedback():
    result = lifecycle.evaluate_transition_readiness(
        from_stage="maps_entry",
        to_stage="endgame_budget",
        state={
            "level": 72,
            "items": [],
            "checks": {
                "resists_capped": False,
                "sustain_ok": False,
                "pob_model_supported": True,
            },
            "feedback": "进图缺蓝，不能维持输出。",
        },
    )

    assert result["ok"] is True
    assert result["ready"] is False
    assert result["recommendation"] == "hold_current_stage"
    assert "level 75" in " ".join(result["missing"]).lower()
    assert result["feedbackPattern"] == "sustain_gap"
    assert any("sustain" in action.lower() for action in result["recommendedActions"])


def test_transition_readiness_uses_stored_build_gates(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))
    route = lifecycle.research_build_lifecycle("闪电终局BD", persist=True)

    result = lifecycle.evaluate_transition_readiness(
        build_id=route["buildId"],
        from_stage="maps_entry",
        to_stage="endgame_budget",
        state={
            "level": 75,
            "items": ["build-defining unique or equivalent rare affix"],
            "checks": {
                "resists_capped": True,
                "sustain_ok": True,
                "pob_model_supported": True,
            },
        },
    )

    assert result["ready"] is True
    assert result["recommendation"] == "transition_allowed"
    assert result["source"] == "stored"


def test_record_build_feedback_returns_stage_repair_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))

    result = lifecycle.record_build_feedback(
        build_id="life-test",
        stage="maps_entry",
        feedback="刚进异界暴毙，抗性也没满。",
    )

    assert result["failurePattern"] == "defense_gap"
    assert any("resist" in action.lower() for action in result["recommendedActions"])
```

- [ ] **Step 2: Run RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py -q`

Expected: FAIL because `evaluate_transition_readiness` and `recommendedActions` do not exist yet.

---

### Task 2: Implement lifecycle readiness

**Files:**
- Modify: `server/knowledge/lifecycle.py`

- [ ] **Step 1: Add implementation**

Implementation requirements:

- Add `evaluate_transition_readiness(build_id=None, from_stage="", to_stage="", state=None)`.
- Load stored gates when `build_id` is present; otherwise use `_default_gates()`.
- Find the matching gate by `fromStage` and `toStage`.
- Return `{ok:false}` when no matching gate exists or `state` is not a dict.
- Call existing `evaluate_transition_gate`.
- If missing requirements exist, return `recommendation="hold_current_stage"`.
- If ready, return `recommendation="transition_allowed"`.
- Normalize `state["feedback"]` with `_failure_pattern`.
- Add `recommendedActions` from a new helper:

```python
def _recommended_actions(stage: str, pattern: str | None, missing: list[str]) -> list[str]:
    ...
```

- Include code comments explaining why failed gates block transition.

- [ ] **Step 2: Add recommended actions to feedback recording**

`record_build_feedback` should include `recommendedActions` using the same helper.

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
def test_evaluate_transition_readiness_tool_forwards_state(monkeypatch):
    from server import main

    monkeypatch.setattr(
        main.lifecycle,
        "evaluate_transition_readiness",
        lambda **kwargs: {"ok": True, "state": kwargs["state"], "from": kwargs["from_stage"]},
    )

    result = main.evaluate_transition_readiness(
        from_stage="maps_entry",
        to_stage="endgame_budget",
        state={"level": 70},
    )

    assert result["ok"] is True
    assert result["state"]["level"] == 70
    assert result["from"] == "maps_entry"
```

- [ ] **Step 2: Run RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_server.py::test_evaluate_transition_readiness_tool_forwards_state -q`

Expected: FAIL because the MCP tool does not exist yet.

- [ ] **Step 3: Add tool**

Add:

```python
@mcp.tool()
def evaluate_transition_readiness(
    from_stage: str,
    to_stage: str,
    state: dict[str, Any],
    build_id: str = "",
) -> dict[str, Any]:
    ...
```

- [ ] **Step 4: Update docs and tool count**

Tool count becomes 73 because Phase 3B already added `analyze_lifecycle_cohort`.

- [ ] **Step 5: Run server tests**

Run: `.\.tools\uv\uv.exe run pytest tests/test_server.py -q`

Expected: PASS.

---

### Task 4: Verification and commit

**Files:**
- All changed files.

- [ ] **Step 1: Run fast verification**

Run: `.\scripts\verify.ps1 quick`

Expected: PASS.

- [ ] **Step 2: Run broader non-engine verification**

Run: `.\scripts\verify.ps1 noncompute`

Expected: PASS.

- [ ] **Step 3: Commit**

Run:

```powershell
git add docs/architecture/phase-03c-transition-readiness.md docs/superpowers/plans/2026-06-26-transition-readiness.md server/knowledge/lifecycle.py server/main.py README.md server/ASSISTANT_GUIDE.md tests/test_lifecycle.py tests/test_server.py
git commit -m "feat: add transition readiness checks"
```

Expected: commit succeeds on `codex/phase-3-lifecycle`.

---

## Self-Review

- Spec coverage: The plan covers transition gates, user feedback, MCP surface, docs, tests, and fast verification.
- Placeholder scan: No placeholder tasks; every production behavior has a concrete test expectation.
- Type consistency: Public function/tool name is `evaluate_transition_readiness`; state remains a plain dict to match existing MCP dict tools.
