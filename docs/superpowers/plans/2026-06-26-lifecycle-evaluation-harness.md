# Lifecycle Evaluation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pure lifecycle route evaluation harness for regression and development review.

**Architecture:** Add `server/knowledge/lifecycle_eval.py` as a thin evaluator over route
dictionaries. It reuses `lifecycle_quality.audit_lifecycle_route`, compares only sanitized
reference/cohort fields, and reports stable issue/warning/unknown codes without running PoB,
network, or memory writes.

**Tech Stack:** Python standard library, pytest, existing MCP server surface, existing lifecycle
quality/cohort route shapes.

**Status:** Completed; post-review fixes, final verification, and narrow re-review passed.

---

## File Structure

- Create: `docs/architecture/phase-03l-lifecycle-evaluation-harness.md`
  - Contract, boundaries, and v1/v2 split.
- Create: `server/knowledge/lifecycle_eval.py`
  - Pure evaluator and helper functions.
- Create: `tests/test_lifecycle_eval.py`
  - Focused RED/GREEN tests for pass, unknowns, sanitization, numeric boundary, and memory policy.
- Modify: `server/main.py`
  - Expose `evaluate_lifecycle_route(route, reference_profile?, goal?)`.
- Modify: `tests/test_server.py`
  - Tool surface count and forwarding test.
- Modify: `README.md` and `server/ASSISTANT_GUIDE.md`
  - Document evaluation harness as a development/regression check.

---

### Task 1: RED tests for evaluator contract

- [x] **Step 1: Add passing structured-route test**

Create `tests/test_lifecycle_eval.py` with:

```python
def test_evaluate_lifecycle_route_passes_structured_route_with_cohort_alignment():
    route = _route()
    result = lifecycle_eval.evaluate_lifecycle_route(route)
    assert result["ok"] is True
    assert result["pass"] is True
    assert result["grade"] == "pass"
    assert result["qualityGate"]["pass"] is True
    assert result["referenceComparison"]["alignmentStatus"] == "aligned"
```

- [x] **Step 2: Add missing-reference unknown test**

```python
def test_evaluate_lifecycle_route_marks_missing_reference_alignment_unknown():
    route = _route()
    route.pop("cohortAnalysis")
    result = lifecycle_eval.evaluate_lifecycle_route(route)
    assert result["pass"] is False
    assert "reference_alignment_unknown" in result["unknowns"]
```

- [x] **Step 3: Add anti-copy sanitization test**

```python
def test_evaluate_lifecycle_route_sanitizes_copyable_reference_fields():
    profile = {"sampleSize": 1, "commonLevers": [{"name": "+levels"}], "gear": ["secret"]}
    result = lifecycle_eval.evaluate_lifecycle_route(_route(), reference_profile=profile)
    assert "reference_raw_fields_sanitized" in result["warnings"]
    assert "gear" not in json.dumps(result)
    assert result["boundaries"]["copiedReference"] is False
```

- [x] **Step 4: Add numeric boundary test**

```python
def test_evaluate_lifecycle_route_rejects_unverified_numeric_claims():
    route = _route()
    route["stages"][0]["dpsEstimate"] = 123456
    result = lifecycle_eval.evaluate_lifecycle_route(route)
    assert "unsupported_computed_claim" in result["issues"]
    assert result["pass"] is False
```

- [x] **Step 5: Add memory policy test**

```python
def test_evaluate_lifecycle_route_rejects_non_advisory_memory_policy():
    route = _route()
    route["memoryContext"]["policy"]["advisoryOnly"] = False
    result = lifecycle_eval.evaluate_lifecycle_route(route)
    assert "memory_policy_not_advisory" in result["issues"]
```

- [x] **Step 6: Run RED**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_lifecycle_eval.py -q
```

Expected: FAIL because `server.knowledge.lifecycle_eval` does not exist yet.

---

### Task 2: Implement pure evaluator

- [x] **Step 1: Add `server/knowledge/lifecycle_eval.py`**

Implement `evaluate_lifecycle_route(route, reference_profile=None, goal=None)` with stable output
fields: `ok`, `kind`, `pass`, `score`, `grade`, `issues`, `warnings`, `unknowns`, `checks`,
`routeSummary`, `qualityGate`, `referenceComparison`, `evidenceReview`, `memoryReview`,
`boundaries`, `evidenceTags`, and `note`.

- [x] **Step 2: Reuse quality gate**

Call `lifecycle_quality.audit_lifecycle_route(route)` internally instead of trusting any embedded
`route["qualityGate"]`.

- [x] **Step 3: Sanitize reference profile**

Ignore copyable keys and only compare `commonLevers`, `commonDamageTypes`, `commonDelivery`,
`commonDefenses`, `ascendancyContext`, and `sampleSize`.

- [x] **Step 4: Score deterministically**

Start at 100; subtract 20 per issue, 8 per unknown, and 5 per warning. Clamp 0-100.

- [x] **Step 5: Run GREEN**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_lifecycle_eval.py -q
```

Expected: PASS.

---

### Task 3: MCP surface and docs

- [x] **Step 1: Add MCP tool**

In `server/main.py`, import/expose:

```python
@mcp.tool()
def evaluate_lifecycle_route(
    route: dict[str, Any],
    reference_profile: dict[str, Any] | None = None,
    goal: str | None = None,
) -> dict[str, Any]:
    return lifecycle_eval.evaluate_lifecycle_route(route, reference_profile, goal)
```

- [x] **Step 2: Add server tests**

Update tool count from 77 to 78 and assert `"evaluate_lifecycle_route"` is registered. Add a
forwarding test that monkeypatches `main.lifecycle_eval.evaluate_lifecycle_route`.

- [x] **Step 3: Update README and assistant guide**

Document it as a development/regression evaluation tool, not as a user-facing promise that a route is
numerically strong.

- [x] **Step 4: Run focused tests**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_lifecycle_eval.py tests/test_server.py -q
```

Expected: PASS.

---

### Task 4: Verification, review, commit

- [x] **Step 1: Run quick verification**

Run:

```powershell
.\scripts\verify.ps1 quick
```

- [x] **Step 2: Run noncompute verification**

Run:

```powershell
.\scripts\verify.ps1 noncompute
```

- [x] **Step 3: Request post-implementation reviews**

Because this adds a new output contract and MCP tool, request both spec review and code review.

- [x] **Step 4: Commit**

Commit with:

```powershell
git commit -m "feat: add lifecycle route evaluation harness"
```

---

## Self-Review

- Spec coverage: Covers route structure, quality gate reuse, reference alignment, anti-copy,
  numeric boundary, memory advisory policy, MCP exposure, docs, and verification.
- Placeholder scan: No placeholder tasks remain.
- Type consistency: Public function/tool is `evaluate_lifecycle_route`; output kind is
  `lifecycle_route_evaluation`.
