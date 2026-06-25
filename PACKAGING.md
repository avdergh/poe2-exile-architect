# Packaging & self-update

## Self-contained bundle

[scripts/build_bundle.py](scripts/build_bundle.py) assembles a self-contained `.mcpb` and is
run per-OS by [.github/workflows/release.yml](.github/workflows/release.yml). A bundle contains:

- `server/` — the MCP server. `server/__init__.py` activates the vendored `lib/` as a *site*
  dir (prepended for precedence, `addsitedir` so `.pth` hooks like pywin32's native DLL setup run).
- `lib/` — vendored Python dependencies (per-OS; compiled wheels like `pydantic-core` and
  `pywin32` are platform-specific, which is why bundles are built on each OS).
- `pob/` — the PoB engine subset (`PathOfBuilding-PoE2/src`, `runtime/lua`, `pob_headless.lua`).
- `data/corpus.sqlite` + `data/reference_builds.json` + `data/VERSION` — the bundled seed corpus
  plus the calibration reference-build set (used by `list_reference_builds` / `benchmark_build`).
- `runtime/luajit/<platform>/luajit[.exe]` — LuaJIT, built from source in CI (the PoB-pinned
  commit). `server/paths.py` auto-detects it.

`build_bundle.py` excludes PoB's GUI art (passive-tree / gem textures the headless engine never
loads — rendering is stubbed), which cuts the bundle from ~400 MB to **~30 MB**. The Python side
is validated to run from the bundle with no repo/venv on the path, and the trimmed engine produces
identical numbers (calc + tree + optimize all verified); LuaJIT is supplied per-OS by the release
workflow.

Build locally (LuaJIT optional; falls back to a system LuaJIT if not vendored):

```sh
uv run python scripts/build_bundle.py --version 2026.06.19
# -> dist/poe2-build-mcp-<version>-<platform>.mcpb
```

> CI is the source of truth for shipped bundles: it builds LuaJIT per-OS, checks out the pinned PoB
> commit and applies the tracked `pob/patches/`, then builds + publishes all three OS bundles (the
> Windows LuaJIT DLL set and macOS arm64 wheels are handled there).

## Self-update

Updates are pulled from our own **validated GitHub releases** (engine bumps are gated by the
golden-test CI), never live upstream — see [server/live/update.py](server/live/update.py).

- A release publishes `update-manifest.json`, `corpus.sqlite`, and `pob-engine.zip`.
- The installed server checks `…/releases/latest/download/update-manifest.json` on startup
  (throttled, best-effort, in a background thread) and installs newer corpus + engine into a
  **writable user-data dir** (`%LOCALAPPDATA%` / `~/Library/Application Support` / `$XDG_DATA_HOME`).
- [server/paths.py](server/paths.py) prefers that user-data copy over the bundled seed, so the
  seed is always a working fallback and updates layer on top.
- Manual control: the `check_for_updates` and `apply_updates` tools; `update_corpus(rebuild_from_source=true)`
  rebuilds the corpus from RePoE locally. Set `POE2_MCP_NO_AUTOUPDATE=1` to disable auto-update,
  or `POE2_MCP_DATA` to relocate the user-data dir.

## Live freshness runtime

The bundle also runs live freshness checks through `get_freshness_report`. These checks are
separate from self-update: `POE2_MCP_NO_AUTOUPDATE=1` disables the background updater, but it does
not disable on-demand freshness live checks.

Freshness provider caches live in the writable user-data directory under:

```text
<POE2_MCP_DATA or platform user-data>/freshness/
```

Set `POE2_MCP_DATA` to relocate both self-update data and freshness caches for local smoke runs or
portable deployments:

```powershell
$env:POE2_MCP_DATA = Join-Path $PWD.Path '.runtime-data'
```

Calling `get_freshness_report(force_refresh=True)` requests an immediate provider refresh, subject
to each provider's reject window and minimum forced-refresh throttle. It bypasses the normal
`refresh_after` interval once that throttle allows a new attempt, but it may still return fresh
cache, fallback cache, or a source-specific blocker instead of performing a new HTTP request on
every call.

Run the live diagnostic from the repo root with:

```powershell
$env:POE2_MCP_DATA = Join-Path $PWD.Path '.runtime-data'
.\.tools\uv\uv.exe run python scripts/smoke_freshness.py
```

The smoke prints the strict decision, blockers, provider cache states, and evidence versions. It
exits non-zero only for internal script/service errors; `blocked_stale`, `blocked_unknown`, and
temporary network unavailability are valid freshness outcomes.

## Requirements at the host

The `.mcpb` manifest runs `python -m server.main` with `PYTHONPATH=${__dirname}`, so the host
needs a Python 3.11+ runtime. Everything else (deps, engine, corpus, LuaJIT) is inside the bundle.
