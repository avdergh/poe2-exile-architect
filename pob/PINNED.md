# Pinned PoB-PoE2 依赖

Compute 层通过 headless 方式驱动 Path of Building Community 的 **PoE2** fork。本文档记录
项目构建所依赖的精确 upstream，确保 git-ignored 的 working copy 可复现。在 CI setup
时，这会变成真正的 git submodule，并 pin 到下方 commit。

| 字段 | 值 |
| --- | --- |
| Repo | https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2 |
| Branch | `dev` |
| Pinned commit | `ce566eac45ea8a86477f513c7ee65a1ebe60014e`（2026-09-10，开发分支固定提交） |
| License | MIT |
| Game data | game patch `0.5.5` 数据，passive tree version `0_5`；计算认证以 `data/compatibility/pob.json` 为准 |

2026-09-13直连上游核验：正式版仍为0.23.1，但开发分支`ce566eac45ea8a86477f513c7ee65a1ebe60014e`
与RePoE导出4.5.5.2（`bdfed992aed0d4c91b9ffb5ef1c3f1acd7af2537`）均已出现官方0.5.5新增的17个
灵魂核心数据条目。上游资料可供升级验收，不再沿用9月5日“上游尚缺数据”作为当前结论。
固定提交与本地补丁已更新，并通过123项完整计算回归、17新增核心效果检查及独立审查。
`data/compatibility/pob.json`以`0.23.1-dev.20260910`登记0.5.5覆盖；静态与数值证书分别保存。
此覆盖不表示所有机制都已建模，现有unknown/unmodelled诊断保持。

## 复现 working copy

```sh
# Check out 精确 pinned commit（如下），不要使用移动中的 `dev` tip；这样可复现并匹配 CI。
# blobless clone 以较低成本保留完整 commit graph，因此即使 dev 前进，pinned SHA 仍可达
#（GitHub 会拒绝 shallow fetch 未公开 SHA）。
git clone --filter=blob:none --no-checkout \
  https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git \
  pob/PathOfBuilding-PoE2
git -C pob/PathOfBuilding-PoE2 config core.autocrlf false   # 保持 LF，方便 Windows 上应用 LF patch
git -C pob/PathOfBuilding-PoE2 checkout ce566eac45ea8a86477f513c7ee65a1ebe60014e
# 然后应用我们 tracked 的 fork patches（见下方 "Local patches"）
(cd pob/PathOfBuilding-PoE2 && git apply --ignore-whitespace ../patches/*.patch)
```

## Local patches

vendored copy 被 git-ignore，因此任何不可避免的 PoB-core 改动都应作为 tracked `*.patch` 放
在 `pob/patches/` 下，并在 clone 后重新应用（见上方），不要静默直接改 vendored 源码。
这些 patch 作为插件长期维护的本地兼容层，不由插件流程自动提交到外部仓库。若未来上游独立包含
等价修复，再 bump pinned commit 并删除对应本地 patch。

| Patch | 为什么不能放在 shim 里 |
| --- | --- |
| `0001-split-personality-alternate-class-starts.patch` | 一个 jewel 可以提供多个 alternate class starts（Split Personality 提供全部六个）。Upstream `Item.lua`/`PassiveSpec.lua` 只保留最后一个，导致 jewel pathing 到多个职业区域时错误。修复点在 PoB tree/item build path 中，shim 无法触达。 |
| `0002-tree-source-skill-supports.patch` | 等级与来源组保留已由上游接管。本补丁只记录辅助实际支持的精确 effect ID，供插件核验真实作用目标。 |
| `0003-isolate-item-source-supports.patch` | 同槽迁移采用上游实现；跨槽共享只传播无来源辅助组，保留共享源槽，避免物品来源组的直属辅助串入其他技能。 |
| `0004-coming-calamity-no-base-reservation.patch` | The Coming Calamity 的三种物品来源 Herald 不支付基础 Spirit，但辅助自身的 Spirit 费用仍需计算。该规则仅绑定此物品，不推广到其他授予技能的装备。 |
| `0005-refresh-synthetic-no-supports.patch` | Explode、Thorns等PoB合成来源组从XML恢复后必须重新标记为不可安装辅助，避免质量检查把合法合成效果误判为缺少辅助审计。 |
| `0006-augment-limit-metadata.patch` | 仅为上游原生配额追加版本与精确文件证据；不覆盖效果数值、limit 或 limitId。旧手工共享组 ID 随模型升级失效。 |
| `0007-standard-luajit-syntax.patch` | 把上游新增的空值运算、复合赋值、continue 与 lambda 语法等价展开为标准 LuaJIT 可解析形式；保留 nil/false 区别，不引入新的数值模型。 |
| `0008-normalize-sparse-item-grant-levels.patch` | 物品技能的逻辑等级可能对应稀疏模型等级。属性/角色等级筛选前后复用 PoB 原生归一化，避免副武器校验把有效模型覆盖为不存在的等级并令导入失败；不改效果数值或凭显示名特判。 |

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
