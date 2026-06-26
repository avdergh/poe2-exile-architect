# Lifecycle Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structural lifecycle quality gate that detects incomplete route outputs before they are presented or evaluated.

**Architecture:** Add a focused `server/knowledge/lifecycle_quality.py` module that audits route dictionaries without importing the heavy lifecycle module. `research_build_lifecycle` attaches the audit result, and one MCP tool exposes route auditing for evaluation workflows.

**Tech Stack:** Python standard library, FastMCP, pytest, `scripts/verify.ps1`.

---

## File Structure

- Create: `docs/architecture/phase-03i-lifecycle-quality-gate.md`
  - Technical contract.
- Create: `server/knowledge/lifecycle_quality.py`
  - Pure route audit helper.
- Modify: `server/knowledge/lifecycle.py`
  - Attach `qualityGate` to suggested routes.
- Modify: `server/main.py`
  - Add MCP tool `audit_lifecycle_route(route)`.
- Modify: `tests/test_lifecycle.py`
  - Add quality gate tests.
- Modify: `tests/test_server.py`
  - Add tool-surface test.
- Modify: `README.md` and `server/ASSISTANT_GUIDE.md`
  - Document quality gate semantics.

---

### Task 1: RED quality gate tests

**Files:**
- Modify: `tests/test_lifecycle.py`

- [ ] **Step 1: Add failing pure audit test**

```python
def test_lifecycle_quality_gate_fails_incomplete_route():
    from server.knowledge import lifecycle_quality

    audit = lifecycle_quality.audit_lifecycle_route(
        {"classification": "starter_then_transition", "stages": [], "transitionGates": []}
    )

    assert audit["pass"] is False
    assert "missing_campaign_stage" in audit["missing"]
    assert "missing_transition_gates" in audit["missing"]
```

- [ ] **Step 2: Add lifecycle integration test**

```python
def test_research_build_lifecycle_includes_quality_gate():
    result = lifecycle.research_build_lifecycle("给我一个新手能玩的强力终局BD")

    assert result["qualityGate"]["pass"] is True
    assert result["qualityGate"]["score"] >= 80
```

- [ ] **Step 3: Run RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py::test_lifecycle_quality_gate_fails_incomplete_route tests/test_lifecycle.py::test_research_build_lifecycle_includes_quality_gate -q`

Expected: FAIL because `lifecycle_quality` and `qualityGate` do not exist.

---

### Task 2: Implement quality module and integrate

**Files:**
- Create: `server/knowledge/lifecycle_quality.py`
- Modify: `server/knowledge/lifecycle.py`

- [ ] **Step 1: Add audit helper**

Implementation requirements:

- Return `pass`, `score`, `missing`, `warnings`, `checks`, and `evidenceTags`.
- Treat missing campaign/maps/endgame stages, transition gates, evidence tags, and verification
  plans as blocking.
- Treat missing freshness as warning.

- [ ] **Step 2: Attach to route result**

In `research_build_lifecycle`, add `qualityGate` after the route dict is assembled.

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

- [ ] **Step 1: Add server tool test**

```python
def test_audit_lifecycle_route_tool_forwards_route(monkeypatch):
    from server import main

    monkeypatch.setattr(
        main.lifecycle.lifecycle_quality,
        "audit_lifecycle_route",
        lambda route: {"pass": False, "route": route},
    )

    result = main.audit_lifecycle_route({"stages": []})

    assert result["pass"] is False
    assert result["route"]["stages"] == []
```

- [ ] **Step 2: Add MCP tool**

Tool name: `audit_lifecycle_route(route)`.

- [ ] **Step 3: Update docs**

Document that this is a structural gate, not a power/engine gate.

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
git add docs/architecture/phase-03i-lifecycle-quality-gate.md docs/superpowers/plans/2026-06-26-lifecycle-quality-gate.md server/knowledge/lifecycle_quality.py server/knowledge/lifecycle.py server/main.py tests/test_lifecycle.py tests/test_server.py README.md server/ASSISTANT_GUIDE.md
git commit -m "feat: add lifecycle route quality gate"
```

Expected: commit succeeds on `codex/phase-3-lifecycle`.

---

## Self-Review

- Spec coverage: The plan covers route audit, lifecycle integration, MCP exposure, docs, tests, and
  layered verification.
- Placeholder scan: No TBD or placeholder implementation steps.
- Type consistency: Helper/tool name is `audit_lifecycle_route`; route output field is
  `qualityGate`.
