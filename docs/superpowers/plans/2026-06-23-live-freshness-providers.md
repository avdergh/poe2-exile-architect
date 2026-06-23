# PoE2 Live Freshness Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add cached, bounded, cross-source live evidence for the current PoE2 patch, league, official passive tree, poe.ninja snapshot, and PoB release so the existing freshness gate can make current-season decisions.

**Architecture:** Keep parsing, HTTP/cache state, provider shaping, and final evaluation separate. Each source adapter converts saved fixtures or live responses into `FreshnessEvidence`; a shared cache runner handles TTL, conditional requests and fallback, while `service.py` aggregates provider results within a fixed time budget.

**Tech Stack:** Python 3.11+, standard-library `urllib`, `concurrent.futures`, dataclasses, pytest, FastMCP, GitHub REST API, GGG HTML, poe.ninja JSON.

---

## File map

- `server/freshness/cache.py`: cache policy, envelope validation, atomic JSON storage and conditional HTTP runner.
- `server/freshness/provider_models.py`: provider result, cache state, diagnostics and HTTP response contracts.
- `server/freshness/ggg.py`: GGG patch-forum and official-tree parsers/providers.
- `server/freshness/ninja.py`: poe.ninja index/build-index parsers/provider.
- `server/freshness/pob.py`: remote PoB release parsing, local pin comparison and compatibility manifest.
- `server/freshness/service.py`: concurrent orchestration and final report metadata.
- `data/compatibility/pob.json`: only commits that passed this project's golden verification.
- `tests/fixtures/freshness/`: compact saved source responses.
- `tests/test_freshness_cache.py`: deterministic cache state-machine tests.
- `tests/test_freshness_ggg.py`: official-source parser/provider tests.
- `tests/test_freshness_ninja.py`: Ninja parser/provider tests.
- `tests/test_freshness_pob.py`: PoB pin and compatibility tests.
- `tests/test_freshness_service.py`: bounded orchestration and MCP integration tests.
- `scripts/smoke_freshness.py`: optional real-network diagnostic.

### Task 1: Provider contracts and cache state machine

**Files:**
- Create: `server/freshness/provider_models.py`
- Create: `server/freshness/cache.py`
- Create: `tests/test_freshness_cache.py`
- Modify: `server/freshness/__init__.py`

- [ ] **Step 1: Write failing tests for cache envelope validation**

Test that a valid envelope round-trips, a mismatched `content_sha256` is rejected, and timezone-naive timestamps are rejected.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_freshness_cache.py -q
```

Expected: collection fails because `server.freshness.cache` and `provider_models` do not exist.

- [ ] **Step 3: Implement provider contracts and atomic cache storage**

Define:

```python
class CacheState(StrEnum):
    FRESH = "fresh"
    REFRESHED = "refreshed"
    REVALIDATED = "revalidated"
    FALLBACK = "fallback"
    MISSING = "missing"

@dataclass(frozen=True, slots=True)
class CachePolicy:
    refresh_after: timedelta
    reject_after: timedelta
    minimum_force_interval: timedelta = timedelta(seconds=60)

@dataclass(frozen=True, slots=True)
class ProviderResult:
    source: str
    evidence: tuple[FreshnessEvidence, ...]
    cache_state: CacheState
    diagnostics: tuple[str, ...]
    duration_ms: int
```

`CacheEnvelope` must calculate its hash from canonical UTF-8 JSON for `payload`, write via a
sibling temporary file and replace with `os.replace`.

- [ ] **Step 4: Write failing tests for refresh, 304 and fallback**

Use an injected transport returning `200`, `304`, or raising a normalized network error. Assert:

- cache younger than `refresh_after` causes no transport call;
- `200` replaces payload and returns `refreshed`;
- `304` updates only `checked_at` and returns `revalidated`;
- network failure before `reject_after` returns `fallback`;
- network failure after `reject_after` exposes hard-stale state to the provider;
- corrupt cache behaves as missing.

- [ ] **Step 5: Implement the minimal cache runner**

Use `ETag` and `Last-Modified` from the envelope to build `If-None-Match` and
`If-Modified-Since`. Catch only normalized transport and cache I/O/JSON errors; do not swallow
programming errors.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_freshness_cache.py -q
.\.tools\uv\uv.exe run ruff check server/freshness tests/test_freshness_cache.py
```

Expected: all focused tests pass and Ruff is clean.

Commit:

```powershell
git add server/freshness/provider_models.py server/freshness/cache.py server/freshness/__init__.py tests/test_freshness_cache.py
git commit -m "feat: add freshness provider cache"
```

### Task 2: GGG patch and official-tree providers

**Files:**
- Create: `server/freshness/ggg.py`
- Create: `tests/test_freshness_ggg.py`
- Create: `tests/fixtures/freshness/ggg-patch-index.html`
- Create: `tests/fixtures/freshness/ggg-patch-thread.html`
- Create: `tests/fixtures/freshness/ggg-tree-release.json`
- Create: `tests/fixtures/freshness/ggg-tree-commit.json`
- Create: `tests/fixtures/freshness/ggg-tree-data-commit.json`

- [ ] **Step 1: Save compact, attributed fixtures**

Keep only the HTML/JSON fields required by the parsers. Add a header comment or sidecar metadata
with source URL and retrieval date; do not save an entire copyrighted forum page.

- [ ] **Step 2: Write failing pure-parser tests**

Assert:

```python
patch = parse_patch_index(index_html)
assert patch.title == "0.5.3 Hotfix 9"
assert patch.base_patch == "0.5.3"
assert patch.thread_url.endswith("/3973617")

thread = parse_patch_thread(thread_html, expected_title=patch.title)
assert thread.posted_at_raw == "Jun 23, 2026, 2:03:40 PM"

tree = parse_official_tree(release_json, commit_json, data_commit_json)
assert tree.league == "Runes of Aldur"
assert tree.tree_series == "0_5"
assert len(tree.commit) == 40
```

Also test malformed title, mismatched thread title, missing release league, and non-version commit
message.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_freshness_ggg.py -q
```

Expected: import failure because `server.freshness.ggg` does not exist.

- [ ] **Step 4: Implement pure parsers**

Use `html.parser.HTMLParser`, not regex over an entire HTML document. Regex is permitted only for
the already-extracted title text:

```text
^\d+\.\d+\.\d+(?: Hotfix \d+)?$
```

Generate canonical URLs and tree-series claims without assigning a game-patch claim to the tree
release.

- [ ] **Step 5: Write failing provider/cache tests**

Inject the cache runner and assert the patch provider emits `GAME_PATCH`, while the official-tree
provider emits `LEAGUE` and `PASSIVE_TREE`.

- [ ] **Step 6: Implement providers with configured policies**

Use:

```python
PATCH_POLICY = CachePolicy(minutes=15, reject_hours=2)
TREE_POLICY = CachePolicy(hours=1, reject_hours=6)
```

Hard-stale cache changes emitted evidence to `SourceStatus.STALE`; no cache and fetch failure emits
`SourceStatus.UNKNOWN`.

- [ ] **Step 7: Verify and commit**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_freshness_ggg.py -q
.\.tools\uv\uv.exe run ruff check server/freshness/ggg.py tests/test_freshness_ggg.py
```

Commit:

```powershell
git add server/freshness/ggg.py tests/test_freshness_ggg.py tests/fixtures/freshness
git commit -m "feat: add GGG freshness providers"
```

### Task 3: poe.ninja snapshot provider

**Files:**
- Create: `server/freshness/ninja.py`
- Create: `tests/test_freshness_ninja.py`
- Create: `tests/fixtures/freshness/ninja-index.json`
- Create: `tests/fixtures/freshness/ninja-build-index.json`

- [ ] **Step 1: Write failing selection and parsing tests**

Fixtures must include the main league, HC/SSF variants, Standard, an old league and a private
league. Assert selection of `Runes of Aldur`, version-date parsing, `PassiveTree-0.5 -> 0_5`, and
sample-size lookup.

Test ambiguous current candidates, missing snapshot, malformed version, zero sample and a tree
version mismatch.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_freshness_ninja.py -q
```

Expected: import failure because `server.freshness.ninja` does not exist.

- [ ] **Step 3: Implement pure selection and shaping**

Private leagues are identified by `PL\d+` in the name or `pl\d+` URL. Exclude names/token sets
containing HC, SSF, Ruthless, Standard. Select the candidate with the newest valid UTC date embedded
in `version`; a tie between different leagues is a conflict result, not first-item selection.

- [ ] **Step 4: Implement the cached provider**

Use a 30-minute refresh and 2-hour reject policy. Emit one `META_SNAPSHOT` evidence record with
league and passive-tree claims. Include sample size and snapshot date only in diagnostics.

- [ ] **Step 5: Verify and commit**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_freshness_ninja.py -q
.\.tools\uv\uv.exe run ruff check server/freshness/ninja.py tests/test_freshness_ninja.py
```

Commit:

```powershell
git add server/freshness/ninja.py tests/test_freshness_ninja.py tests/fixtures/freshness
git commit -m "feat: add poe ninja snapshot provider"
```

### Task 4: PoB release, local pin and compatibility manifest

**Files:**
- Create: `server/freshness/pob.py`
- Create: `data/compatibility/pob.json`
- Create: `tests/test_freshness_pob.py`
- Create: `tests/fixtures/freshness/pob-release.json`
- Create: `tests/fixtures/freshness/pob-release-commit.json`
- Modify: `server/freshness/providers.py`

- [ ] **Step 1: Write failing tests for explicit compatibility**

Assert that:

- a local commit absent from the compatibility manifest never receives patch/tree claims;
- a matching verified commit receives `game_patch` and `passive_tree` claims;
- remote release ahead of local pin marks local PoB engine/data stale;
- release-note text alone cannot grant compatibility;
- malformed compatibility entries are rejected.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_freshness_pob.py -q
```

Expected: import failure because `server.freshness.pob` does not exist.

- [ ] **Step 3: Implement manifest and release parsers**

The initial compatibility file has an empty `entries` array because the installed `a82a33b4` has
not passed current-patch verification. Do not pre-authorize `v0.21.1`.

- [ ] **Step 4: Implement local/remote comparison**

Compare full commits when available and accepted unambiguous short-prefix commits. If the remote
commit does not share the local prefix and remote release is newer, emit stale engine/data records
with diagnostics naming both versions.

- [ ] **Step 5: Verify and commit**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_freshness_pob.py -q
.\.tools\uv\uv.exe run ruff check server/freshness/pob.py tests/test_freshness_pob.py
```

Commit:

```powershell
git add server/freshness/pob.py server/freshness/providers.py data/compatibility/pob.json tests/test_freshness_pob.py tests/fixtures/freshness
git commit -m "feat: add PoB freshness compatibility"
```

### Task 5: Concurrent service and MCP integration

**Files:**
- Modify: `server/freshness/service.py`
- Modify: `server/main.py`
- Modify: `manifest.json`
- Modify: `tests/test_freshness_service.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write failing aggregation tests**

Use injected providers to assert:

- matching current evidence reaches `verified_current`;
- stale local PoB reaches `blocked_stale`;
- Ninja tree conflict reaches `blocked_conflict`;
- provider diagnostics are serialized;
- a provider exception is converted to provider-level missing/unknown without losing other evidence.

- [ ] **Step 2: Write a failing time-budget test**

Provide blocking fake providers and assert `get_freshness_report(total_timeout=0.1)` returns in under
0.5 seconds with missing provider diagnostics.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_freshness_service.py tests/test_server.py -q
```

Expected: failures because live providers, `force_refresh`, timeout and provider status are absent.

- [ ] **Step 4: Implement bounded parallel aggregation**

Use `ThreadPoolExecutor(max_workers=4)`. Submit only providers requiring collection, wait up to the
remaining total budget, cancel pending futures and synthesize missing results. Preserve deterministic
provider-status ordering.

- [ ] **Step 5: Update MCP tools**

Expose:

```python
def get_freshness_report(force_refresh: bool = False) -> dict[str, Any]
```

`check_data_version` calls the same service once, then adds the legacy corpus probe. Update manifest
descriptions without adding a second tool.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_freshness_service.py tests/test_server.py -q
.\.tools\uv\uv.exe run ruff check server/main.py server/freshness tests/test_freshness_service.py tests/test_server.py
```

Commit:

```powershell
git add server/freshness/service.py server/main.py manifest.json tests/test_freshness_service.py tests/test_server.py
git commit -m "feat: integrate live freshness evidence"
```

### Task 6: Live smoke diagnostic and documentation

**Files:**
- Create: `scripts/smoke_freshness.py`
- Create: `docs/architecture/live-freshness-runtime.md`
- Create: `docs/audits/phase-02-result.md`
- Modify: `PACKAGING.md`

- [ ] **Step 1: Write the smoke command**

The script calls the service with `force_refresh=True`, prints decision, evidence versions, cache
states and sanitized diagnostics, and exits non-zero only for internal errors—not for
`blocked_stale` or unavailable networks.

- [ ] **Step 2: Document runtime controls**

Document TTL defaults, cache location, total timeout, condition requests, offline fallback and the
fact that the current PoB pin is expected to block verification until upgraded.

- [ ] **Step 3: Run offline verification**

Run:

```powershell
$env:POE2_MCP_DATA='E:\poe-bd-creator\.runtime-data'
$env:POE2_MCP_NO_AUTOUPDATE='1'
.\.tools\uv\uv.exe run pytest -q --ignore=tests/test_compute.py
.\.tools\uv\uv.exe run ruff check server scripts pipeline tests
.\.tools\uv\uv.exe run ruff format --check server scripts pipeline tests
.\.tools\uv\uv.exe run mypy server/freshness
npx --yes @anthropic-ai/mcpb validate manifest.json
```

Expected: all commands pass.

- [ ] **Step 4: Run live smoke**

Run:

```powershell
$env:POE2_MCP_DATA='E:\poe-bd-creator\.runtime-data'
.\.tools\uv\uv.exe run python scripts/smoke_freshness.py
```

Expected on 2026-06-23: external sources parse successfully and the decision remains
`blocked_stale` because local PoB `a82a33b4` is behind `v0.21.1`.

- [ ] **Step 5: Record evidence and commit**

Write actual commands, counts, source versions and remaining blockers to `phase-02-result.md`.

Commit:

```powershell
git add scripts/smoke_freshness.py docs/architecture/live-freshness-runtime.md docs/audits/phase-02-result.md PACKAGING.md
git commit -m "docs: record live freshness runtime"
```

### Task 7: PoB v0.21.1 upgrade and compatibility certification

**Files:**
- Modify: `pob/PINNED.md`
- Modify: `.github/workflows/release.yml`
- Modify: local vendored PoB payload during verification (ignored)
- Modify: `data/compatibility/pob.json`
- Modify: affected golden tests only when the new engine intentionally changes expected values

- [ ] **Step 1: Download the exact PoB release commit**

Resolve `v0.21.1` to full commit `dc409a7073e4e2752e9a642db7544af53551d006`, check it out in the
ignored PoB working copy, and reapply tracked fork patches. If a patch no longer applies, inspect
whether upstream incorporated it before changing the patch.

- [ ] **Step 2: Run focused engine health and golden calculations**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_compute.py -q --timeout=300
```

Expected: all non-known-performance tests pass. The existing
`test_optimize_build_crafting_keeps_resists_capped` timeout must be reported separately and cannot
be called green without a completed result.

- [ ] **Step 3: Review numerical changes**

For every changed golden assertion, compare old/new outputs and tie the change to a PoB `v0.21.1`
release fix. Do not mechanically update expected values.

- [ ] **Step 4: Certify compatibility only after verification**

Add the full commit to `data/compatibility/pob.json` with:

```json
{
  "pob_version": "0.21.1",
  "game_patch": "0.5.3",
  "passive_tree": "0_5",
  "verified_by": ["golden-tests", "GGG-patch", "GGG-tree", "ninja-tree"]
}
```

Use the actual verification timestamp.

- [ ] **Step 5: Re-run the complete phase verification**

Run all commands from Task 6 plus live smoke. Expected: if no source changed during execution, the
report can reach `verified_current`; otherwise record the exact conflict or stale source.

- [ ] **Step 6: Commit**

```powershell
git add pob/PINNED.md .github/workflows/release.yml data/compatibility/pob.json tests
git commit -m "chore: certify PoB 0.21.1"
```

### Task 8: Final independent review

**Files:**
- Review all changes since `543a628`
- Update: `docs/audits/phase-02-result.md`

- [ ] **Step 1: Request specification compliance review**

Review every requirement in
`docs/superpowers/specs/2026-06-23-live-freshness-providers-design.md`. Resolve all missing or extra
behavior and re-run focused tests.

- [ ] **Step 2: Request code-quality review**

Review cache corruption, timestamp handling, source ambiguity, exception boundaries, thread
cleanup, path safety and diagnostic data leakage. Resolve every P1/P2 issue and re-run focused tests.

- [ ] **Step 3: Run fresh final verification**

Run the full Task 6 verification commands after all review fixes. Record exact results in the audit.

- [ ] **Step 4: Commit the final audit**

```powershell
git add docs/audits/phase-02-result.md
git commit -m "docs: finalize phase two audit"
```
