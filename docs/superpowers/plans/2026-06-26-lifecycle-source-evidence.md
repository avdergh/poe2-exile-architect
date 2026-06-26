# Lifecycle Source Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract structured lifecycle evidence from pasted guide/source text and feed it into lifecycle classification.

**Architecture:** Add a focused `server/knowledge/lifecycle_evidence.py` module for pure text extraction. Integrate its result into `server/knowledge/lifecycle.py::analyze_build_lifecycle` so failed imports and guide-like sources still produce useful starter/transition/endgame evidence.

**Tech Stack:** Python standard library regexes, existing SQLite corpus helpers, pytest, `scripts/verify.ps1`.

---

## File Structure

- Create: `docs/architecture/phase-03f-lifecycle-source-evidence.md`
  - Local technical contract.
- Create: `server/knowledge/lifecycle_evidence.py`
  - Source text extraction helpers.
- Modify: `server/knowledge/lifecycle.py`
  - Include source evidence in lifecycle analysis and use it for classification hints.
- Modify: `tests/test_lifecycle.py`
  - Add source extraction and lifecycle classification tests.
- Modify: `README.md` and `server/ASSISTANT_GUIDE.md`
  - Explain source evidence and its limitations.

---

### Task 1: RED extraction tests

**Files:**
- Modify: `tests/test_lifecycle.py`

- [ ] **Step 1: Add failing tests**

```python
def test_lifecycle_source_evidence_extracts_starter_transition_and_endgame_signals(monkeypatch):
    from server.knowledge import lifecycle_evidence

    monkeypatch.setattr(
        lifecycle_evidence.corpus,
        "find_skills",
        lambda query="", gem_type=None, limit=30, **_kw: (
            [{"name": "Spark", "gem_type": "active", "tags": ["lightning"]}]
            if query.lower() == "spark"
            else []
        ),
    )
    monkeypatch.setattr(
        lifecycle_evidence.corpus,
        "search_uniques",
        lambda query="", limit=20, **_kw: (
            [{"name": "Dream Fragment", "base": "Sapphire Ring", "item_type": "ring"}]
            if query.lower() == "dream fragment"
            else []
        ),
    )

    evidence = lifecycle_evidence.extract_lifecycle_source_evidence(
        "Level with Spark through campaign. Switch at level 75 when Dream Fragment is equipped. "
        "Final endgame setup is not a starter."
    )

    assert "campaign_early" in evidence["stageSignals"]
    assert "endgame_final" in evidence["stageSignals"]
    assert evidence["skillCandidates"][0]["name"] == "Spark"
    assert evidence["uniqueCandidates"][0]["name"] == "Dream Fragment"
    assert evidence["transitionHints"][0]["level"] == 75
    assert "required_unique_language" in evidence["riskFlags"]
```

- [ ] **Step 2: Add analyze integration test**

```python
def test_analyze_build_lifecycle_uses_source_evidence_when_import_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        lifecycle.lifecycle_evidence,
        "extract_lifecycle_source_evidence",
        lambda source: {
            "stageSignals": ["campaign_early", "endgame_final"],
            "lifecycleHints": ["starter_route", "endgame_form"],
            "uniqueCandidates": [{"name": "Dream Fragment"}],
            "skillCandidates": [{"name": "Spark"}],
            "transitionHints": [{"level": 75, "snippet": "Switch at level 75"}],
            "riskFlags": ["required_unique_language"],
            "evidenceTags": ["external-guide", "corpus", "lifecycle-source-extraction"],
        },
    )

    result = lifecycle.analyze_build_lifecycle("guide text", import_error="not a pob")

    assert result["ok"] is False
    assert result["classification"] == "starter_then_transition"
    assert result["sourceEvidence"]["uniqueCandidates"][0]["name"] == "Dream Fragment"
```

- [ ] **Step 3: Run RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py::test_lifecycle_source_evidence_extracts_starter_transition_and_endgame_signals tests/test_lifecycle.py::test_analyze_build_lifecycle_uses_source_evidence_when_import_is_unavailable -q`

Expected: FAIL because `lifecycle_evidence` does not exist and `analyze_build_lifecycle` does not consume source evidence.

---

### Task 2: Implement extractor

**Files:**
- Create: `server/knowledge/lifecycle_evidence.py`

- [ ] **Step 1: Add extractor**

Implementation requirements:

- Detect stage signals with conservative keyword sets.
- Extract transition snippets around switch/respec/transition language and nearby level numbers.
- Confirm candidate skills and uniques via corpus search.
- Add risk flags for required unique language and endgame-only language without starter language.
- Return stable empty lists when nothing is found.

- [ ] **Step 2: Run extraction tests**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py::test_lifecycle_source_evidence_extracts_starter_transition_and_endgame_signals -q`

Expected: PASS.

---

### Task 3: Integrate classification

**Files:**
- Modify: `server/knowledge/lifecycle.py`

- [ ] **Step 1: Import `lifecycle_evidence`**

Use the helper in `analyze_build_lifecycle`.

- [ ] **Step 2: Update feature derivation**

Implementation requirements:

- `critical_uniques` includes imported unique dependencies plus source unique candidates when
  required-unique language is present.
- `low_level_viable` can be true when source evidence contains early campaign/starter language.
- `starter_route_available` can be true when source evidence contains starter route/transition hints.
- `endgame_scaling` can be true when source evidence contains endgame stage signals.
- Return `sourceEvidence`.

- [ ] **Step 3: Run lifecycle tests**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py -q`

Expected: PASS.

---

### Task 4: Docs, verification, commit

**Files:**
- Modify: `README.md`
- Modify: `server/ASSISTANT_GUIDE.md`

- [ ] **Step 1: Update docs**

Document:

- Source text extraction is external-guide evidence, not computed truth.
- It helps explain lifecycle classification and transition hints.

- [ ] **Step 2: Run quick verification**

Run: `.\scripts\verify.ps1 quick`

Expected: PASS.

- [ ] **Step 3: Run noncompute verification**

Run: `.\scripts\verify.ps1 noncompute`

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```powershell
git add docs/architecture/phase-03f-lifecycle-source-evidence.md docs/superpowers/plans/2026-06-26-lifecycle-source-evidence.md server/knowledge/lifecycle_evidence.py server/knowledge/lifecycle.py tests/test_lifecycle.py README.md server/ASSISTANT_GUIDE.md
git commit -m "feat: extract lifecycle evidence from guide sources"
```

Expected: commit succeeds on `codex/phase-3-lifecycle`.

---

## Self-Review

- Spec coverage: The plan covers source evidence extraction, classification integration, docs, tests,
  and layered verification.
- Placeholder scan: No TBD or placeholder implementation steps.
- Type consistency: Helper is `extract_lifecycle_source_evidence`; returned evidence is
  `sourceEvidence` inside lifecycle analysis.
