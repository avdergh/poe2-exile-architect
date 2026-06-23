# 第二阶段调研：官方与 Meta 实时来源

调研时间：2026-06-23  
目标：验证补丁、联盟、官方天赋树、PoB 和 poe.ninja 是否存在可机器读取、可审计的来源。

## 1. GGG 官方补丁

来源：

- https://www.pathofexile.com/forum/view-forum/2212
- https://www.pathofexile.com/forum/view-thread/3973617

论坛索引的主题链接具有稳定形状：

```html
<a href="/forum/view-thread/3973617">
    0.5.3 Hotfix 9
</a>
```

主题页同时包含：

```html
<meta property="og:title"
      content="Early Access Patch Notes - 0.5.3 Hotfix 9 - Forum - Path of Exile">
<span class="post_date">Jun 23, 2026, 2:03:40 PM</span>
```

2026-06-23 调研时，论坛索引第一条版本主题是 `0.5.3 Hotfix 9`。Provider 应从索引顺序
选取第一个满足严格版本标题格式的主题，再从主题页读取首个 GGG 帖子的时间。不能把新闻、
置顶说明或其他论坛板块当作补丁版本。

可提供：

- 完整补丁版本：`0.5.3 Hotfix 9`；
- 兼容性 claim：`game_patch=0.5.3`；
- 官方主题 URL；
- 抓取时间和官方发帖时间。

风险：

- 页面是 HTML，不是公开 JSON API；
- 主题列表结构可能改变；
- 发帖时间没有显式时区，因此只保留原始文本或按站点已验证时区解析，不能擅自按本地时区解释。

## 2. GGG 官方天赋树导出

来源：

- https://github.com/grindinggear/poe2-skilltree-export
- https://api.github.com/repos/grindinggear/poe2-skilltree-export/releases/latest
- https://api.github.com/repos/grindinggear/poe2-skilltree-export/commits/main

2026-06-23 的响应：

| 字段 | 值 |
|---|---|
| 最新 release tag | `0.5.2` |
| release 名称 | `Path of Exile 2: Runes of Aldur` |
| release 发布时间 | `2026-05-26T04:49:47Z` |
| main commit | `1e9eb2d8c1946398c3aaaacfbaead5c75c0d1fa6` |
| main commit 时间 | `2026-06-15T23:50:47Z` |
| main commit message | `0.5.2` |

`data.json` 顶层包含：

```text
tree, classes, groups, nodes, edges, skillOverrides, jewelSlots,
min_x, min_y, max_x, max_y
```

文件本身没有单独的补丁或树版本字段。因此 provider 应：

- 使用 GitHub commit SHA 作为官方树快照的不可变版本；
- 从最新 `data.json` commit message/release tag 提取树系列 `0_5`；
- 从官方 release 名称提取联盟 `Runes of Aldur`；
- 不把 release tag `0.5.2` 误当成当前游戏补丁。官方 main 是当前树快照来源，树系列与
  游戏补丁的兼容性由其他来源交叉验证。

## 3. poe.ninja 索引与快照

来源：

- https://poe.ninja/poe2/api/data/index-state
- https://poe.ninja/poe2/api/data/build-index-state
- https://poe.ninja/poe2/builds/runesofaldur

`index-state` 返回：

```text
economyLeagues
oldEconomyLeagues
snapshotVersions
buildLeagues
oldBuildLeagues
```

2026-06-23 的 Runes of Aldur 主联盟快照样本：

```json
{
  "url": "runesofaldur",
  "name": "Runes of Aldur",
  "version": "0653-20260623-55698",
  "snapshotName": "runes-of-aldur",
  "overviewType": 0,
  "passiveTree": "PassiveTree-0.5"
}
```

`build-index-state` 同日返回主联盟样本量 `124304`。响应头在调研时包含
`Last-Modified: Tue, 23 Jun 2026 08:27:53 GMT`，但 `index-state` 不保证提供该头。

可提供：

- 当前主挑战联盟和 slug；
- 快照不可变版本；
- 从快照版本中提取的 UTC 日期；
- `passiveTree=PassiveTree-0.5`，规范化为 `0_5`；
- 样本量和升华分布。

风险：

- 这是公开但未文档化的第三方接口；
- `version` 格式不是正式契约；
- 不能因为接口返回成功就认为所有角色数据已完整；
- popularity 只能用于 Meta 比较，不能作为强度结论。

构筑搜索页面的前端公开调用：

```text
GET /poe2/api/builds/{version}/search
GET /poe2/api/builds/{version}/tooltip
GET /poe2/api/builds/dictionary
```

这证明后续可以独立实现构筑级 Meta 采样，但第二阶段只接入 freshness 所需的
`index-state` 和 `build-index-state`，不在同一切片内实现完整构筑下载与 protobuf 解码。

## 4. Path of Building Community PoE2

来源：

- https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/releases/tag/v0.21.1
- https://api.github.com/repos/PathOfBuildingCommunity/PathOfBuilding-PoE2/compare/a82a33b4...v0.21.1

2026-06-23 的最新 release：

| 字段 | 值 |
|---|---|
| 版本 | `v0.21.1` |
| release commit | `dc409a7073e4e2752e9a642db7544af53551d006` |
| 发布时间 | `2026-06-23T05:51:33Z` |
| 相对本地 pin `a82a33b4` | ahead 16 commits |

release 历史中存在显式提交：

```text
de56576eee  0.5.3 Export
```

release notes 也明确包含 `after 0.5.3` 的修复以及多项计算修复。因此当前本地
`a82a33b4` 不能取得 `game_patch=0.5.3` 的兼容 claim，应判为落后；后续必须升级到
经过本项目黄金测试验证的 `v0.21.1` commit，再生成显式兼容清单。

## 5. 数据源职责结论

| 组件 | 主来源 | 辅助交叉验证 |
|---|---|---|
| 游戏补丁 | GGG Early Access Patch Notes | PoB release/export |
| 联盟 | GGG 官方树 release 名称 | poe.ninja build league |
| 官方天赋树 | GGG `data.json` commit SHA | Ninja `passiveTree` |
| PoB 引擎/数据 | PoB release commit + 本地 pin | GGG 补丁、官方树 |
| Meta 快照 | Ninja `index-state` | Ninja `build-index-state` |

没有任何单一来源足够授予 `verified_current`。Provider 只生成证据，最终状态仍由
`server.freshness.evaluator` 统一裁决。
