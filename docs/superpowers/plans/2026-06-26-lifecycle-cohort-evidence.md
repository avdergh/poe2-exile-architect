# Lifecycle Cohort Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Phase 3B cohort-evidence layer that turns goal-specific corpus candidates, live poe.ninja ascendancy context, and engine-verified reference builds into structured lifecycle research evidence.

**Architecture:** Keep the new analysis in a focused knowledge-layer module, `server/knowledge/lifecycle_cohort.py`, so `server/knowledge/lifecycle.py` does not grow into a research monolith. `suggest_build_lifecycle` will call the cohort analyzer after collecting goal evidence, then annotate stage plans with common levers, reference archetype matches, and live-meta context. The analyzer must remain calibration-only: it may identify patterns, but it must not copy reference builds.

**Tech Stack:** Python standard library, existing `server.knowledge.refbuilds`, existing `server.live.meta` output shape, pytest, FastMCP.

---

## File Structure

- Create: `docs/architecture/phase-03b-lifecycle-cohort-evidence.md`
  - Local technical doc describing the cohort evidence contract and boundaries.
- Create: `server/knowledge/lifecycle_cohort.py`
  - Focused analyzer for reference/meta/corpus evidence aggregation.
- Modify: `server/knowledge/lifecycle.py`
  - Call the cohort analyzer from `research_build_lifecycle`.
  - Add cohort hints/evidence tags to relevant lifecycle stages.
- Modify: `server/main.py`
  - Add a small inspection tool, `analyze_lifecycle_cohort(goal, preferences?, limit?)`, for debugging and agent research.
- Modify: `README.md` and `server/ASSISTANT_GUIDE.md`
  - Document the new cohort evidence concept without overstating it as a full optimizer.
- Modify: `tests/test_lifecycle.py`
  - Add tests for cohort extraction and lifecycle integration.
- Modify: `tests/test_server.py`
  - Add tool-surface test for `analyze_lifecycle_cohort`.

---

### Task 1: Write the local technical document

**Files:**
- Create: `docs/architecture/phase-03b-lifecycle-cohort-evidence.md`

- [ ] **Step 1: Add the document**

```markdown
# Phase 3B Lifecycle Cohort Evidence

## Purpose

Phase 3B adds a cohort-evidence layer between raw sources and lifecycle synthesis. It answers:
"For this goal, what do mature reference archetypes and live ascendancy context commonly agree on?"

## Contract

The analyzer returns:

- `referenceMatches`: slim, non-copyable reference build slices.
- `commonLevers`: recurring scaling levers from matching references.
- `commonDamageTypes`, `commonDelivery`, `commonDefenses`: recurring archetype traits.
- `ascendancyContext`: matched reference ascendancies annotated with live poe.ninja popularity when available.
- `warnings`: caveats such as missing samples or live-meta absence.

## Boundaries

- This is not a build copier.
- This is not a passive tree optimizer.
- poe.ninja ascendancy popularity is context, not a recommendation.
- PoB remains the source of computed DPS/EHP/resistance truth.
```

- [ ] **Step 2: Verify no trailing whitespace**

Run: `git diff --check`

Expected: exit 0.

---

### Task 2: Add RED tests for cohort extraction

**Files:**
- Modify: `tests/test_lifecycle.py`

- [ ] **Step 1: Add failing tests**

```python
def test_lifecycle_cohort_extracts_reference_patterns_and_live_meta(monkeypatch):
    from server.knowledge import lifecycle_cohort

    monkeypatch.setattr(
        lifecycle_cohort.refbuilds,
        "search",
        lambda query="", limit=8: {
            "count": 2,
            "builds": [
                {
                    "ascendancy": "Stormweaver",
                    "mainSkill": "Lightning Spear",
                    "damageTypes": ["lightning"],
                    "delivery": ["spell", "projectile"],
                    "defenseIdentity": "ES recharge",
                    "dominantLever": "+levels to skills",
                    "topLevers": [{"lever": "+levels to skills"}, {"lever": "critical multiplier"}],
                },
                {
                    "ascendancy": "Stormweaver",
                    "mainSkill": "Spark",
                    "damageTypes": ["lightning"],
                    "delivery": ["spell", "projectile"],
                    "defenseIdentity": "ES recharge",
                    "dominantLever": "+levels to skills",
                    "topLevers": [{"lever": "+levels to skills"}, {"lever": "cast speed"}],
                },
            ],
        },
    )

    cohort = lifecycle_cohort.analyze_goal_cohort(
        goal="闪电远程终局BD",
        skill_candidates=[{"name": "Lightning Spear", "query": "lightning"}],
        meta={
            "ok": True,
            "source": "poe.ninja",
            "league": "Runes of Aldur",
            "ascendancies": [{"ascendancy": "Stormweaver", "percentage": 18.5, "trend": "rising"}],
        },
        limit=4,
    )

    assert cohort["ok"] is True
    assert cohort["sampleSize"] == 2
    assert cohort["commonLevers"][0]["name"] == "+levels to skills"
    assert cohort["commonDamageTypes"][0]["name"] == "lightning"
    assert cohort["ascendancyContext"][0]["ascendancy"] == "Stormweaver"
    assert cohort["ascendancyContext"][0]["liveMeta"]["percentage"] == 18.5
    assert "reference-cohort" in cohort["evidenceTags"]
    assert "live-meta" in cohort["evidenceTags"]


def test_research_build_lifecycle_includes_cohort_hints(monkeypatch):
    monkeypatch.setattr(
        lifecycle.corpus,
        "find_skills",
        lambda query="", gem_type=None, limit=5, **_kw: [
            {"name": "Lightning Spear", "tags": ["lightning", "projectile"]}
        ],
    )
    monkeypatch.setattr(
        lifecycle.lifecycle_cohort,
        "analyze_goal_cohort",
        lambda **_kw: {
            "ok": True,
            "sampleSize": 1,
            "referenceMatches": [{"mainSkill": "Lightning Spear", "ascendancy": "Stormweaver"}],
            "commonLevers": [{"name": "+levels to skills", "count": 1}],
            "commonDamageTypes": [{"name": "lightning", "count": 1}],
            "commonDelivery": [{"name": "projectile", "count": 1}],
            "commonDefenses": [{"name": "ES recharge", "count": 1}],
            "ascendancyContext": [{"ascendancy": "Stormweaver", "referenceCount": 1}],
            "warnings": [],
            "evidenceTags": ["reference-cohort", "live-meta"],
        },
    )

    result = lifecycle.research_build_lifecycle(
        "给我一个闪电远程终局BD",
        meta={"ok": True, "ascendancies": []},
    )

    assert result["cohortAnalysis"]["sampleSize"] == 1
    endgame = next(stage for stage in result["stages"] if stage["id"] == "endgame_final")
    assert "+levels to skills" in " ".join(endgame["cohortHints"])
    assert "reference-cohort" in endgame["evidenceTags"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py -q`

Expected: FAIL because `server.knowledge.lifecycle_cohort` and lifecycle integration do not exist yet.

---

### Task 3: Implement cohort analyzer

**Files:**
- Create: `server/knowledge/lifecycle_cohort.py`

- [ ] **Step 1: Add implementation**

```python
"""Cohort evidence for lifecycle build research.

This module aggregates mature-reference and live-meta context into non-copyable patterns.
It intentionally returns archetype evidence, not full builds.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from . import refbuilds


def analyze_goal_cohort(
    *,
    goal: str,
    skill_candidates: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    ...
```

Implementation requirements:

- Build search queries from skill candidate names and the original goal.
- Call `refbuilds.search(query, limit=limit)`.
- Deduplicate matches by `(ascendancy, mainSkill, dominantLever)`.
- Count common levers from `dominantLever` and `topLevers`.
- Count damage type, delivery, and defense identity.
- Join matched ascendancies with `meta["ascendancies"]` by name.
- Return warnings if no reference samples or live meta is unavailable.
- Include code comments explaining why references are calibration-only.

- [ ] **Step 2: Run tests and verify GREEN**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py -q`

Expected: remaining failure only for lifecycle integration, if any.

---

### Task 4: Integrate cohort evidence into lifecycle synthesis

**Files:**
- Modify: `server/knowledge/lifecycle.py`

- [ ] **Step 1: Import analyzer and thread cohort into stage plans**

Implementation requirements:

- Import `lifecycle_cohort`.
- After `_collect_goal_evidence`, call:

```python
cohort = lifecycle_cohort.analyze_goal_cohort(
    goal=goal,
    skill_candidates=evidence.get("skillCandidates") or [],
    meta=meta,
)
```

- Add `cohortAnalysis` to the returned lifecycle route.
- Pass `cohort` into `_stage_plan`.
- For `endgame_budget` and `endgame_final`, add `cohortHints` such as:
  - `Common mature-build levers: +levels to skills, critical multiplier`
  - `Common delivery traits: spell, projectile`
  - `Common defense identities: ES recharge`
- Add `reference-cohort` / `live-meta` tags from cohort evidence to stage `evidenceTags`.

- [ ] **Step 2: Run lifecycle tests**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py -q`

Expected: PASS.

---

### Task 5: Add MCP inspection tool and docs

**Files:**
- Modify: `server/main.py`
- Modify: `README.md`
- Modify: `server/ASSISTANT_GUIDE.md`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Add failing server test**

```python
def test_analyze_lifecycle_cohort_tool_uses_meta(monkeypatch):
    from server import main

    monkeypatch.setattr(
        main.live_meta,
        "get_meta_builds",
        lambda limit=8: {"ok": True, "source": "poe.ninja", "ascendancies": []},
    )
    monkeypatch.setattr(
        main.lifecycle.lifecycle_cohort,
        "analyze_goal_cohort",
        lambda **kwargs: {
            "ok": True,
            "goal": kwargs["goal"],
            "sampleSize": 0,
            "referenceMatches": [],
            "evidenceTags": ["reference-cohort"],
        },
    )

    result = main.analyze_lifecycle_cohort("闪电终局BD")

    assert result["ok"] is True
    assert result["goal"] == "闪电终局BD"
```

- [ ] **Step 2: Run server test and verify RED**

Run: `.\.tools\uv\uv.exe run pytest tests/test_server.py::test_analyze_lifecycle_cohort_tool_uses_meta -q`

Expected: FAIL because the tool does not exist.

- [ ] **Step 3: Add the MCP tool**

```python
@mcp.tool()
def analyze_lifecycle_cohort(
    goal: str,
    preferences: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Analyze non-copyable lifecycle cohort evidence for a natural-language build goal."""
    ...
```

- [ ] **Step 4: Update tool count and docs**

Expected tool count becomes 72.

- [ ] **Step 5: Run server tests**

Run: `.\.tools\uv\uv.exe run pytest tests/test_server.py -q`

Expected: PASS.

---

### Task 6: Final verification and commit

**Files:**
- All changed files.

- [ ] **Step 1: Run focused tests**

Run: `.\.tools\uv\uv.exe run pytest tests/test_lifecycle.py tests/test_server.py -q`

Expected: PASS.

- [ ] **Step 2: Run style/type/manifest checks**

Run:

```powershell
.\.tools\uv\uv.exe run ruff check server scripts pipeline tests
.\.tools\uv\uv.exe run ruff format --check server scripts pipeline tests
.\.tools\uv\uv.exe run mypy server/freshness
npx --yes @anthropic-ai/mcpb validate manifest.json
git diff --check
```

Expected: all exit 0; manifest may keep the existing icon-size warning.

- [ ] **Step 3: Commit**

Run:

```powershell
git add docs/architecture/phase-03b-lifecycle-cohort-evidence.md docs/superpowers/plans/2026-06-26-lifecycle-cohort-evidence.md server/knowledge/lifecycle_cohort.py server/knowledge/lifecycle.py server/main.py README.md server/ASSISTANT_GUIDE.md tests/test_lifecycle.py tests/test_server.py
git commit -m "feat: add lifecycle cohort evidence"
```

Expected: commit succeeds on `codex/phase-3-lifecycle`.

---

## Self-Review

- Spec coverage: The plan covers local docs, cohort evidence extraction, lifecycle integration, MCP exposure, docs, tests, and verification.
- Placeholder scan: No task uses `TBD`, `TODO`, or "implement later"; the only ellipsis is inside the implementation sketch where the following bullet list gives exact behavior.
- Type consistency: Public names are `lifecycle_cohort.analyze_goal_cohort`, `cohortAnalysis`, `cohortHints`, and MCP tool `analyze_lifecycle_cohort`.
