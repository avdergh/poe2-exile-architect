# Pinned PoB-PoE2 dependency

The compute layer drives the Path of Building Community **PoE2** fork headless.
This file records the exact upstream we build against so the working copy (which is
git-ignored, not committed) is reproducible. At CI-setup time this becomes a proper
git submodule pinned to the commit below.

| Field | Value |
|-------|-------|
| Repo | https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2 |
| Branch | `dev` |
| Pinned commit | `7d1aa43c8c938d7be150d197ed9cdec8a4c1c620` (2026-06-25, `dev` candidate: `0.5.4 Export` + `ModCache`) |
| License | MIT |
| Game data | game patch `0.5.4`, passive tree version `0_5` |

## Reproduce the working copy

```sh
# Check out the EXACT pinned commit (below), not the moving `dev` tip — reproducible + matches CI.
# A blobless clone keeps the full commit graph cheaply, so the pinned SHA stays reachable even
# after dev advances (GitHub refuses a shallow fetch of an unadvertised SHA).
git clone --filter=blob:none --no-checkout \
  https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git \
  pob/PathOfBuilding-PoE2
git -C pob/PathOfBuilding-PoE2 config core.autocrlf false   # keep LF so the LF patch applies on Windows
git -C pob/PathOfBuilding-PoE2 checkout 7d1aa43c8c938d7be150d197ed9cdec8a4c1c620
# then apply our tracked fork patches (see "Local patches" below)
(cd pob/PathOfBuilding-PoE2 && git apply --ignore-whitespace ../patches/*.patch)
```

## Local patches

The vendored copy is git-ignored, so any unavoidable PoB-core change lives as a tracked
`*.patch` under `pob/patches/` and is re-applied after clone (above) — never edited in place
silently (CLAUDE.md §7). These are candidates to upstream to the fork; when one lands upstream,
bump the pinned commit and drop the patch.

| Patch | Why it can't live in the shim |
|-------|-------------------------------|
| `0001-split-personality-alternate-class-starts.patch` | A jewel can grant *several* alternate class starts (Split Personality grants all six). Upstream `Item.lua`/`PassiveSpec.lua` kept only the last, so jewel-pathing into multiple class regions was wrong. The fix is in PoB's tree/item build path — the shim can't reach it. |

## Runtime requirements (validated in M0 spike)

- **LuaJIT 2.1** — installed on this machine via MSYS2:
  `pacman -S mingw-w64-ucrt-x86_64-luajit` → `C:\msys64\ucrt64\bin\luajit.exe`
- **lua-utf8** — required by `src/Modules/Common.lua`. For now satisfied by a pure-Lua
  ASCII shim in `pob/pob_headless.lua` (`package.preload["lua-utf8"]`). v1 packaging
  should bundle a real `luautf8` built against LuaJIT for correct non-ASCII handling.
- Pure-Lua deps (`dkjson`, `xml`, `base64`, `sha1`, `lua-profiler`) ship in the fork's
  `runtime/lua/` and resolve via `package.path = "../runtime/lua/?.lua"` when run from `src/`.
- `lcurl` is patched out by `HeadlessWrapper.lua`; `Deflate`/`Inflate` are stubbed, so PoB
  import codes must be inflated in Python and fed as XML (matches PLAN.md).

## How headless is invoked

Run with working directory = `pob/PathOfBuilding-PoE2/src`, mirroring the fork's `.busted`
config (`directory=src`, `lpath=../runtime/lua/?.lua`, `helper=HeadlessWrapper.lua`).
`pob/pob_headless.lua` boots the engine and exposes a line-delimited JSON-RPC loop.
