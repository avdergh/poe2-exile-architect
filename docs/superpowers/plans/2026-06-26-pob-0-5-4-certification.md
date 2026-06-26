# PoB 0.5.4 Certification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Certify a PoB-PoE2 commit that can safely assert `game_patch=0.5.4` after the 2026-06-26 live freshness smoke detected GGG patch drift.

**Architecture:** Keep the existing fail-closed freshness design: only `data/compatibility/pob.json` may authorize PoB/local `game_patch` and `passive_tree` claims. Because no tagged PoB release newer than `v0.21.1` exists at the start of this work, treat the PoB `dev` commit containing `0.5.4 Export` plus the following `ModCache` commit as a candidate; certify it only after golden compute tests pass.

**Tech Stack:** PowerShell 7, Git for Windows, Python 3.12 via `.tools/uv/uv.exe`, pytest, Ruff, mypy, GitHub-hosted PoB-PoE2 source.

---

### Task 1: Record the 0.5.4 drift and candidate policy

**Files:**
- Create: `docs/architecture/pob-dev-export-certification.md`
- Modify: `docs/architecture/pob-upgrade-certification.md`
- Modify: `docs/audits/phase-02-result.md`

- [x] **Step 1: Write the local technical document**

Create `docs/architecture/pob-dev-export-certification.md` with the exact evidence:

```markdown
# PoB dev-export certification

The normal path is to certify a tagged PathOfBuilding-PoE2 release. When GGG publishes a new
game patch before PoB cuts a release, this project may certify an exact PoB `dev` commit only if:

1. GGG live patch evidence has advanced beyond the latest certified compatibility manifest entry.
2. The PoB `dev` history contains an explicit export/data commit for that game patch.
3. The selected commit is pinned by full SHA and includes any follow-up generated cache commit.
4. The local headless PoB golden suite passes against that exact SHA with tracked fork patches applied.
5. `data/compatibility/pob.json` records the candidate separately from tagged releases.

For the 2026-06-26 drift:

- GGG patch provider reports `0.5.4 Hotfix 2` and claim `game_patch=0.5.4`.
- Latest tagged PoB release remains `v0.21.1` at `dc409a7073e4e2752e9a642db7544af53551d006`.
- PoB `dev` contains `7f52b81ba25217737524257799732361bc8fda42` (`0.5.4 Export`) followed by
  `7d1aa43c8c938d7be150d197ed9cdec8a4c1c620` (`ModCache`).
- Candidate to certify: `7d1aa43c8c938d7be150d197ed9cdec8a4c1c620`.
```

- [x] **Step 2: Update existing certification doc**

Add a short section to `docs/architecture/pob-upgrade-certification.md` stating that untagged
dev-export candidates are allowed only under the five conditions above, and that release workflow
`POB_COMMIT` must always be a full SHA from the compatibility manifest.

- [x] **Step 3: Update the Phase 2 audit**

Append a certification work item showing the 2026-06-26 smoke is blocked until the candidate passes
golden tests and a new validated runtime is installed or published.

### Task 2: Pin and authorize the 0.5.4 candidate

**Files:**
- Modify: `pob/PINNED.md`
- Modify: `.github/workflows/release.yml`
- Modify: `data/compatibility/pob.json`
- Modify: `tests/test_freshness_pob.py`

- [x] **Step 1: Check out the exact PoB candidate locally**

Run:

```powershell
git -C pob/PathOfBuilding-PoE2 fetch origin dev
git -C pob/PathOfBuilding-PoE2 checkout 7d1aa43c8c938d7be150d197ed9cdec8a4c1c620
git -C pob/PathOfBuilding-PoE2 reset --hard 7d1aa43c8c938d7be150d197ed9cdec8a4c1c620
git -C pob/PathOfBuilding-PoE2 apply --ignore-whitespace ../patches/*.patch
```

Expected: checkout succeeds and the tracked split-personality patch either applies cleanly or is
already incorporated upstream. If it fails, inspect before editing the patch.

- [x] **Step 2: Update repository pin and release workflow**

Replace the old `dc409a7073e4e2752e9a642db7544af53551d006` pin with
`7d1aa43c8c938d7be150d197ed9cdec8a4c1c620` in `pob/PINNED.md` and
`.github/workflows/release.yml`. In `pob/PINNED.md`, label it as a `dev` candidate containing the
`0.5.4 Export` and `ModCache` commits.

- [x] **Step 3: Add compatibility manifest entry**

Add this entry to `data/compatibility/pob.json` after verification succeeds:

```json
{
  "commit": "7d1aa43c8c938d7be150d197ed9cdec8a4c1c620",
  "pob_version": "0.21.1-dev.20260625",
  "game_patch": "0.5.4",
  "passive_tree": "0_5",
  "verified_by": ["golden-tests", "GGG-patch", "GGG-tree", "ninja-tree", "pob-dev-export"],
  "verified_at": "ACTUAL_UTC_TIMESTAMP"
}
```

- [x] **Step 4: Update tests**

Change `tests/test_freshness_pob.py::test_repository_manifest_authorizes_only_the_certified_pob_pin`
so it expects the repository pin to resolve to the newest entry with `game_patch == "0.5.4"` while
still asserting the previous `dc409a7` entry remains valid for `game_patch == "0.5.3"`.

### Task 3: Verify and record the certification

**Files:**
- Modify: `docs/audits/phase-02-result.md`

- [x] **Step 1: Run focused tests**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_freshness_pob.py tests/test_freshness_service.py tests/test_freshness_cache.py tests/test_smoke_freshness.py -q
```

Expected: all selected tests pass.

- [x] **Step 2: Run golden compute certification**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_compute.py -q --timeout=300
```

Expected: all compute tests pass. If numerical assertions change, stop and trace the change to a
PoB candidate commit before updating any expected values.

- [x] **Step 3: Run full non-compute, lint, typing, manifest checks**

Run:

```powershell
$env:POE2_MCP_DATA = Join-Path $PWD.Path '.runtime-data'
$env:POE2_MCP_NO_AUTOUPDATE = '1'
.\.tools\uv\uv.exe run pytest -q --ignore=tests/test_compute.py
.\.tools\uv\uv.exe run ruff check server scripts pipeline tests
.\.tools\uv\uv.exe run ruff format --check server scripts pipeline tests
.\.tools\uv\uv.exe run mypy server/freshness
npx --yes @anthropic-ai/mcpb validate manifest.json
```

Expected: pytest, Ruff, mypy, and manifest schema validation pass.

- [x] **Step 4: Verify live smoke behavior**

Run the smoke twice:

```powershell
$env:POE2_MCP_DATA = Join-Path $PWD.Path '.runtime-data'
.\.tools\uv\uv.exe run python scripts/smoke_freshness.py
```

Expected before a local validated runtime is installed: the smoke may still block because
`.runtime-data/installed.json` points at the older `v0.1.39` release. Record that honestly.

If a local candidate runtime is installed for development, rerun and record whether the decision
becomes `verified_current`.

- [ ] **Step 5: Commit**

Run:

```powershell
git add .github/workflows/release.yml data/compatibility/pob.json docs/architecture/pob-dev-export-certification.md docs/architecture/pob-upgrade-certification.md docs/audits/phase-02-result.md docs/superpowers/plans/2026-06-26-pob-0-5-4-certification.md pob/PINNED.md tests/test_freshness_pob.py
git commit -m "chore: certify PoB 0.5.4 candidate"
```
