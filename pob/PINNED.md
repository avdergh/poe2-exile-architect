# Pinned PoB-PoE2 依赖

Compute 层通过 headless 方式驱动 Path of Building Community 的 **PoE2** fork。本文档记录
项目构建所依赖的精确 upstream，确保 git-ignored 的 working copy 可复现。在 CI setup
时，这会变成真正的 git submodule，并 pin 到下方 commit。

| 字段 | 值 |
| --- | --- |
| Repo | https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2 |
| Branch | `dev` |
| Pinned commit | `7d1aa43c8c938d7be150d197ed9cdec8a4c1c620`（2026-06-25，`dev` candidate：`0.5.4 Export` + `ModCache`） |
| License | MIT |
| Game data | game patch `0.5.4`，passive tree version `0_5` |

## 复现 working copy

```sh
# Check out 精确 pinned commit（如下），不要使用移动中的 `dev` tip；这样可复现并匹配 CI。
# blobless clone 以较低成本保留完整 commit graph，因此即使 dev 前进，pinned SHA 仍可达
#（GitHub 会拒绝 shallow fetch 未公开 SHA）。
git clone --filter=blob:none --no-checkout \
  https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git \
  pob/PathOfBuilding-PoE2
git -C pob/PathOfBuilding-PoE2 config core.autocrlf false   # 保持 LF，方便 Windows 上应用 LF patch
git -C pob/PathOfBuilding-PoE2 checkout 7d1aa43c8c938d7be150d197ed9cdec8a4c1c620
# 然后应用我们 tracked 的 fork patches（见下方 "Local patches"）
(cd pob/PathOfBuilding-PoE2 && git apply --ignore-whitespace ../patches/*.patch)
```

## Local patches

vendored copy 被 git-ignore，因此任何不可避免的 PoB-core 改动都应作为 tracked `*.patch` 放
在 `pob/patches/` 下，并在 clone 后重新应用（见上方），不要静默直接改 vendored 源码。
这些 patch 是 upstream 候选；当某个 patch 被 upstream 接收后，应 bump pinned commit
并删除该 patch。

| Patch | 为什么不能放在 shim 里 |
| --- | --- |
| `0001-split-personality-alternate-class-starts.patch` | 一个 jewel 可以提供多个 alternate class starts（Split Personality 提供全部六个）。Upstream `Item.lua`/`PassiveSpec.lua` 只保留最后一个，导致 jewel pathing 到多个职业区域时错误。修复点在 PoB tree/item build path 中，shim 无法触达。 |

## Runtime requirements（M0 spike 已验证）

- **LuaJIT 2.1**：本机通过 MSYS2 安装：
  `pacman -S mingw-w64-ucrt-x86_64-luajit` -> `C:\msys64\ucrt64\bin\luajit.exe`
- **lua-utf8**：`src/Modules/Common.lua` 需要。目前由 `pob/pob_headless.lua` 中的 pure-Lua
  ASCII shim 满足（`package.preload["lua-utf8"]`）。v1 packaging 应 bundle 一个基于 LuaJIT
  构建的真实 `luautf8`，以正确处理非 ASCII。
- Pure-Lua deps（`dkjson`、`xml`、`base64`、`sha1`、`lua-profiler`）随 fork 的
  `runtime/lua/` 提供，从 `src/` 运行时通过 `package.path = "../runtime/lua/?.lua"` 解析。
- `lcurl` 由 `HeadlessWrapper.lua` patch 掉；`Deflate`/`Inflate` 被 stub，因此 PoB import
  codes 必须在 Python 中 inflate，并以 XML 喂给引擎（匹配 `AGENTS.md` 中的 compute-layer
  contract）。

## Headless 调用方式

运行工作目录为 `pob/PathOfBuilding-PoE2/src`，与 fork 的 `.busted` config 保持一致
（`directory=src`、`lpath=../runtime/lua/?.lua`、`helper=HeadlessWrapper.lua`）。
`pob/pob_headless.lua` 启动引擎，并暴露 line-delimited JSON-RPC loop。
