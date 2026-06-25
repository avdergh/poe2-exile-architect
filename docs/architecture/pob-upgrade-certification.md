# PoB upgrade and compatibility certification

## Purpose

This slice upgrades the pinned Path of Building Community PoE2 engine/data and certifies
that this project can safely claim compatibility with the current game patch and passive
tree.

The compatibility manifest is a safety boundary. A remote PoB release can prove that a
newer upstream engine exists, but it cannot prove that this MCP's headless bridge, fork
patches, optimizer assumptions, and golden calculations still work. Only a successful
local certification run may add `game_patch` and `passive_tree` claims to
`data/compatibility/pob.json`.

## Target release

Task 7 targets the upstream release observed during Phase 2:

```text
tag: v0.21.1
commit: dc409a7073e4e2752e9a642db7544af53551d006
published: 2026-06-23T05:51:33Z
```

Before changing the pin, the implementer must re-resolve the tag from upstream using a
fresh network source. GitHub API may be rate-limited; `git ls-remote` is an acceptable
fallback. If neither source can confirm the release tag and commit in the current
session, certification must stop as blocked rather than relying only on old fixtures.

## Files changed by certification

Expected tracked changes:

- `pob/PINNED.md`
- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `data/compatibility/pob.json`
- golden tests only if numerical changes are traced to upstream release behavior
- audit documentation if final smoke/verification outcomes change

Expected untracked/ignored working changes:

- `pob/PathOfBuilding-PoE2/`

The ignored PoB working copy is allowed during verification, but it must not be committed.

## Checkout and patch workflow

1. Clone the upstream PoB2 repository into `pob/PathOfBuilding-PoE2` if it is absent.
2. Set `core.autocrlf=false` in that working copy.
3. Check out the exact target commit.
4. Apply tracked fork patches from `pob/patches/*.patch` with `git apply --ignore-whitespace`.

If a patch fails:

- inspect whether upstream incorporated the patch;
- if upstream did, remove or update the tracked patch in the same certification commit;
- otherwise treat the certification as blocked until the patch conflict is understood.

Do not silently edit the ignored PoB working copy as the durable fix.

## Required verification

Focused engine gate:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_compute.py -q --timeout=300
```

Every completed test result must be recorded. The known slow
`test_optimize_build_crafting_keeps_resists_capped` case must not be called passing if it times
out or is interrupted.

If a golden value changes:

1. capture the old and new values;
2. identify the PoB release note, upstream commit, or data change that explains the drift;
3. update the expected value only when the new value is justified.

Full phase gate after focused verification:

```powershell
$env:POE2_MCP_DATA = Join-Path $PWD.Path '.runtime-data'
$env:POE2_MCP_NO_AUTOUPDATE = '1'
.\.tools\uv\uv.exe run pytest -q --ignore=tests/test_compute.py
.\.tools\uv\uv.exe run ruff check server scripts pipeline tests
.\.tools\uv\uv.exe run ruff format --check server scripts pipeline tests
.\.tools\uv\uv.exe run mypy server/freshness
npx --yes @anthropic-ai/mcpb validate manifest.json
.\.tools\uv\uv.exe run python scripts/smoke_freshness.py
```

## Compatibility manifest entry

Only after successful focused and full verification, add an entry like:

```json
{
  "commit": "dc409a7073e4e2752e9a642db7544af53551d006",
  "pob_version": "0.21.1",
  "game_patch": "0.5.3",
  "passive_tree": "0_5",
  "verified_by": ["golden-tests", "GGG-patch", "GGG-tree", "ninja-tree"],
  "verified_at": "2026-06-25T00:00:00+00:00"
}
```

Use the actual UTC verification timestamp. Do not add the entry if compute tests, source
freshness, or patch application are unresolved.

## Expected freshness result

After the local pin and compatibility manifest both point at the certified PoB commit,
`get_freshness_report(force_refresh=True)` can reach `verified_current` only when the other
required sources agree at runtime:

- GGG patch -> `game_patch=0.5.3`;
- GGG tree -> `passive_tree=0_5`;
- poe.ninja -> `league=runes-of-aldur`, `passive_tree=0_5`;
- local corpus / PoB data -> certified `game_patch=0.5.3`, `passive_tree=0_5`.

If any source is unavailable, hard-stale, or conflicting during the final smoke, record the
exact source state in the audit instead of weakening the gate.

