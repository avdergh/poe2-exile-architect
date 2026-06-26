# Lifecycle Numeric Range Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional reference-range comparison to lifecycle route evaluation when stages already
carry engine-computed verification snapshots.

**Architecture:** Extend `server/knowledge/lifecycle_eval.py` with a small pure helper that extracts
endgame stage observations and compares them against safe reference distributions supplied through
`reference_profile`. Keep the MCP surface unchanged and expose the result under
`evidenceReview.numericRangeReview`.

**Tech Stack:** Python standard library, pytest, existing MCP server surface, existing
`evaluate_lifecycle_route` output contract, existing `benchmark_build` reference distribution shape.

**Status:** Completed; focused tests, quick verification, noncompute verification, code review, and
spec/evidence-boundary review passed after regression fixes.

---

## File Structure

- Modify: `server/knowledge/lifecycle_eval.py`
  - Add numeric range extraction, comparison, and warning propagation.
- Modify: `tests/test_lifecycle_eval.py`
  - Add RED/GREEN coverage for engine-computed endgame stage comparison, non-computed stages, and
    `benchmark_build`-shaped references.
- Modify: `docs/architecture/phase-03m-lifecycle-numeric-range-evaluation.md`
  - Keep contract and evidence boundaries in sync with implementation.
- Modify: `docs/PROJECT_SPEC.md`
  - Track Phase 3M status and completion.

---

### Task 1: RED tests for range comparison contract

- [x] **Step 1: Add endgame comparison test**

Add a test that attaches an engine-computed `verification` snapshot to `endgame_final` and supplies
`reference_profile["numericRanges"]`. Assert:

```python
result = lifecycle_eval.evaluate_lifecycle_route(route, reference_profile=profile)
review = result["evidenceReview"]["numericRangeReview"]
assert review["status"] == "compared"
assert review["stageComparisons"][0]["stage"] == "endgame_final"
assert {row["metric"] for row in review["stageComparisons"]} >= {"TotalDPS", "TotalEHP"}
assert "numeric_range_below_reference" in result["warnings"]
assert result["grade"] == "needs_review"
assert "numeric_range_below_reference" not in result["issues"]
```

- [x] **Step 2: Add no-compute safety test**

Use a route whose stage verification is only a planned budget. Supply numeric ranges and assert:

```python
assert result["evidenceReview"]["numericRangeReview"]["status"] == "not_evaluated"
assert result["evidenceReview"]["numericRangeReview"]["stageComparisons"] == []
```

- [x] **Step 3: Add benchmark-shape reference test**

Supply a `benchmark_build`-style profile with `dps.reference` and `ehp.reference`. Assert the range
review compares `TotalDPS` and `TotalEHP`, does not compare `FullDPS`, and does not break existing
route cohort alignment.

- [x] **Step 4: Add profile-shape safety test**

Supply a `numericRanges`-only profile while the route has valid `cohortAnalysis`. Assert
`referenceComparison.alignmentStatus == "aligned"` so numeric-only input does not override cohort
alignment.

- [x] **Step 5: Add stage-local evidence test**

Put `engine-computed` on the stage or route but not inside `stage["verification"]["evidenceTags"]`.
Assert numeric range review is `not_evaluated`.

- [x] **Step 6: Add invalid-route and invalid-reference tests**

Assert invalid route output includes stable `evidenceReview.numericRangeReview`, and invalid ranges
with non-numeric/bool values or `min > max` produce `invalid_reference`.

- [x] **Step 7: Add anti-leak test**

Supply numeric ranges plus raw copyable fields such as `gear`, `pobCode`, and `passiveTree`; assert
the serialized evaluation output does not include those raw fields.

- [x] **Step 8: Run RED**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_lifecycle_eval.py -q
```

Expected: FAIL because `numericRangeReview` is not implemented yet.

---

### Task 2: Implement pure numeric range review

- [x] **Step 1: Add range extraction helpers**

In `server/knowledge/lifecycle_eval.py`, add helpers:

```python
def _review_numeric_ranges(stages: list[dict[str, Any]], reference_profile: dict[str, Any] | None) -> dict[str, Any]:
    ...

def _normalize_numeric_ranges(reference_profile: Any) -> tuple[dict[str, dict[str, float]], list[str]]:
    ...
```

The helpers must accept `numericRanges.TotalDPS` / `numericRanges.TotalEHP` and
`dps.reference` / `ehp.reference`. They may accept `numericRanges.FullDPS`, but must not compare
`FullDPS` against `dps.reference`. Reject bools, non-finite values, and ranges where `min > max`.

- [x] **Step 2: Extract only stage-local engine-computed observations**

Use only endgame stages where `stage["verification"]["evidenceTags"]` contains `engine-computed`.
Read:

```python
observations["offense"]["TotalDPS"]
observations["totalEHP"]
```

- [x] **Step 3: Preserve cohort alignment source**

When `reference_profile` is numeric-only or `benchmark_build`-shaped, keep reference alignment on
`route.cohortAnalysis`. Numeric ranges are an extra calibration input, not a replacement for cohort
alignment fields.

- [x] **Step 4: Compare and emit warnings**

For each comparable value, return `placement` as `below_range`, `within_range`, or `above_range`.
If any value is below range, add warning `numeric_range_below_reference`.

- [x] **Step 5: Wire into `evaluate_lifecycle_route`**

Attach the result at:

```python
evidence_review["numericRangeReview"] = numeric_range_review
```

Propagate `numericRangeReview["warnings"]` to top-level warnings, but do not convert them to issues.

- [x] **Step 6: Run GREEN**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_lifecycle_eval.py -q
```

Expected: PASS.

---

### Task 3: Verification and review

- [x] **Step 1: Run focused tests**

```powershell
.\.tools\uv\uv.exe run pytest tests/test_lifecycle_eval.py tests/test_server.py -q
```

- [x] **Step 2: Run quick verification**

```powershell
.\scripts\verify.ps1 quick
```

- [x] **Step 3: Run noncompute verification**

```powershell
.\scripts\verify.ps1 noncompute
```

- [x] **Step 4: Request code review**

Request a post-implementation code review. Because this changes evidence semantics inside an
existing output contract, request a narrow spec/evidence-boundary review too.

- [x] **Step 5: Commit**

```powershell
git add server/knowledge/lifecycle_eval.py tests/test_lifecycle_eval.py docs/PROJECT_SPEC.md docs/architecture/phase-03m-lifecycle-numeric-range-evaluation.md docs/superpowers/plans/2026-06-26-lifecycle-numeric-range-evaluation.md
git commit -m "feat: add lifecycle numeric range evaluation"
```

---

## Self-Review

- Spec coverage: Covers stage-local engine evidence, safe reference distribution shapes, comparison
  semantics, warning propagation, and no-compute/no-network boundaries.
- Placeholder scan: No placeholder implementation tasks remain.
- Type consistency: Public MCP function remains `evaluate_lifecycle_route`; new nested output is
  `evidenceReview.numericRangeReview`.
