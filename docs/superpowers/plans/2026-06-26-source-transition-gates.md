# Source Transition Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert explicit guide/source transition hints into draft lifecycle transition gates.

**Architecture:** Keep gate synthesis in `server/knowledge/lifecycle.py` because it reuses the existing `make_transition_gate` shape. The source extractor remains focused on evidence extraction; lifecycle analysis decides how evidence maps to build stages.

**Tech Stack:** Python standard library, existing lifecycle model, pytest, `scripts/verify.ps1`.

---

## File Structure

- Create: `docs/architecture/phase-03g-source-transition-gates.md`
  - Technical contract for source-derived gates.
- Modify: `server/knowledge/lifecycle.py`
  - Add source gate synthesis and include it in analysis output.
- Modify: `tests/test_lifecycle.py`
  - Add tests for guide text → transition gate behavior.
- Modify: `README.md` and `server/ASSISTANT_GUIDE.md`
  - Document source-derived gates and caveats.

---

### Task 1: RED gate synthesis test

**Files:**
- Modify: `tests/test_lifecycle.py`

- [ ] **Step 1: Add failing test**

```python
def test_analyze_build_lifecycle_synthesizes_source_transition_gate(monkeypatch):
    monkeypatch.setattr(
        lifecycle.lifecycle_evidence,
        "extract_lifecycle_source_evidence",
        lambda source: {
            "stageSignals": ["campaign_early", "endgame_final"],
            "lifecycleHints": ["starter_route", "transition_required", "endgame_form"],
            "uniqueCandidates": [{"name": "Dream Fragment"}],
            "skillCandidates": [{"name": "Spark"}],
            "transitionHints": [{"level": 75, "snippet": "Switch at level 75 when Dream Fragment is equipped."}],
            "riskFlags": ["required_unique_language"],
            "evidenceTags": ["external-guide", "corpus", "lifecycle-source-extraction"],
        },
    )

    result = lifecycle.analyze_build_lifecycle("guide text", import_error="not a pob")

    gate = result["sourceTransitionGates"][0]
    assert gate["source"] == "source-evidence"
    assert gate["fromStage"] == "maps_entry"
    assert gate["toStage"] == "endgame_budget"
    assert gate["requirements"]["level"] == 75
    assert gate["requirements"]["items"] == ["Dream Fragment"]
    assert "resists_capped" in gate["requirements"]["checks"]
```

- [ ] **Step 2: Run RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py::test_analyze_build_lifecycle_synthesizes_source_transition_gate -q`

Expected: FAIL because `sourceTransitionGates` does not exist.

---

### Task 2: Implement synthesis

**Files:**
- Modify: `server/knowledge/lifecycle.py`

- [ ] **Step 1: Add helper**

Implementation requirements:

- `_source_transition_gates(source_evidence)` returns a list of `TransitionGate`-shaped dicts.
- Use level bands to infer from/to stages.
- Include required unique candidates only when `required_unique_language` is present.
- Include map/endgame safety checks.
- Add caveats and the original snippet.

- [ ] **Step 2: Integrate output**

Implementation requirements:

- `analyze_build_lifecycle` returns `sourceTransitionGates`.
- `transitionGates` starts with source gates and appends default gates without duplicating identical
  from/to/source ids.

- [ ] **Step 3: Run lifecycle tests**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py -q`

Expected: PASS.

---

### Task 3: Docs, verification, commit

**Files:**
- Modify: `README.md`
- Modify: `server/ASSISTANT_GUIDE.md`

- [ ] **Step 1: Update docs**

Document:

- `sourceTransitionGates` are guide-derived hypotheses.
- They must be rechecked with readiness/stage verification before recommending a switch.

- [ ] **Step 2: Run quick verification**

Run: `.\scripts\verify.ps1 quick`

Expected: PASS.

- [ ] **Step 3: Run noncompute verification**

Run: `.\scripts\verify.ps1 noncompute`

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```powershell
git add docs/architecture/phase-03g-source-transition-gates.md docs/superpowers/plans/2026-06-26-source-transition-gates.md server/knowledge/lifecycle.py tests/test_lifecycle.py README.md server/ASSISTANT_GUIDE.md
git commit -m "feat: synthesize transition gates from guide evidence"
```

Expected: commit succeeds on `codex/phase-3-lifecycle`.

---

## Self-Review

- Spec coverage: The plan covers gate synthesis, lifecycle integration, docs, tests, and layered
  verification.
- Placeholder scan: No TBD or placeholder implementation steps.
- Type consistency: Output field is `sourceTransitionGates`; gate shape follows
  `make_transition_gate`.
