# Phase 01 Foundation Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the MIT upstream baseline and add a conservative, test-driven freshness gate that prevents stale PoE2 data from being presented as current-season verified.

**Architecture:** Preserve the upstream MCP and headless-PoB structure. Add a pure `server.freshness` domain package whose evaluator accepts source records and returns an evidence-rich report; network providers remain separate so correctness tests are deterministic.

**Tech Stack:** Python 3.11+, pytest, FastMCP, SQLite, headless Path of Building PoE2.

---

### Task 1: Establish the upstream baseline

**Files:**
- Import: upstream `MaxWilk/poe2-build-mcp` source tree
- Preserve: `docs/architecture/phase-01-foundation-audit.md`
- Create: `docs/audits/upstream-baseline.md`

- [ ] **Step 1: Import the latest reviewed MIT source archive**

Copy the source tree without copying a foreign `.git` directory. Record the upstream URL, archive branch, retrieval date, license, and reviewed release in `docs/audits/upstream-baseline.md`.

- [ ] **Step 2: Install or locate the required Python runtime**

Run:

```powershell
python --version
uv --version
```

Expected: Python 3.11+ and `uv` are available. If unavailable, document the exact blocker before changing production code.

- [ ] **Step 3: Run the unmodified upstream tests**

Run:

```powershell
uv sync
uv run pytest -q
```

Expected: the upstream suite passes. Record the test count and any platform-specific exclusions in the audit document.

### Task 2: Define the freshness domain with TDD

**Files:**
- Create: `server/freshness/__init__.py`
- Create: `server/freshness/models.py`
- Create: `server/freshness/evaluator.py`
- Test: `tests/test_freshness.py`

- [ ] **Step 1: Write failing tests for the report states**

Cover `verified_current`, `blocked_stale`, `blocked_conflict`, `blocked_unknown`, and `current_unmodelled`. Assert both the overall status and human-readable blocker codes.

- [ ] **Step 2: Run the tests and verify the expected import failure**

Run:

```powershell
uv run pytest tests/test_freshness.py -q
```

Expected: FAIL because `server.freshness` does not exist.

- [ ] **Step 3: Implement immutable source records and the pure evaluator**

The evaluator must:

- require game, official tree, PoB engine, PoB data, and league snapshot records;
- compare normalized patch and tree identifiers;
- return all blockers rather than stopping at the first;
- downgrade current-but-unmodelled builds without treating them as stale.

- [ ] **Step 4: Run focused and full tests**

Run:

```powershell
uv run pytest tests/test_freshness.py -q
uv run pytest -q
```

Expected: all tests pass.

### Task 3: Expose the freshness gate through the MCP surface

**Files:**
- Modify: `server/main.py`
- Modify: `server/live/version.py`
- Test: `tests/test_server.py`
- Test: `tests/test_freshness.py`

- [ ] **Step 1: Write a failing MCP-level test**

The test must prove that a stale PoB engine produces `blocked_stale` even when RePoE is current.

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```powershell
uv run pytest tests/test_server.py -q
```

Expected: FAIL because the structured freshness report is not yet exposed.

- [ ] **Step 3: Add the structured report**

Keep the legacy tool name temporarily for compatibility, but return the new report shape and evidence. Add a clearer `get_freshness_report` MCP tool that uses the same service.

- [ ] **Step 4: Verify focused and full tests**

Run:

```powershell
uv run pytest tests/test_server.py tests/test_freshness.py -q
uv run pytest -q
```

Expected: all tests pass.

### Task 4: Audit documentation and first checkpoint

**Files:**
- Update: `docs/audits/upstream-baseline.md`
- Create: `docs/audits/phase-01-checkpoint.md`

- [ ] **Step 1: Record verified facts**

Document the actual local test results, upstream PoB pin, current game patch evidence, known unmodelled mechanics, and any runtime limitations.

- [ ] **Step 2: Run final verification**

Run:

```powershell
uv run pytest -q
uv run python scripts/smoke_live.py
```

Expected: test suite passes; live smoke either succeeds or reports a source-specific degraded state without claiming `verified_current`.

- [ ] **Step 3: Request specification and code-quality review**

Review against `docs/architecture/phase-01-foundation-audit.md`, resolve all critical and important findings, then re-run the verification commands.

