# poe.ninja build-level source probe

Date: 2026-06-27
Scope: Phase 3N.3 mature build learning source probe
Raw content persisted: no

本文档记录一次 copy-safe 的 poe.ninja 来源探测。探测目标是判断当前公开入口是否稳定暴露
PoE2 build-level 热门成熟 BD 样本。本文只保存 HTTP 状态、content type、响应顶层 shape、
row shape、hash 前缀和结论，不保存 raw JSON、raw HTML、角色信息、装备、天赋树、宝石连接或
PoB code。

## Probe method

请求使用浏览器风格 User-Agent，并只在内存中读取响应。对 JSON 响应调用
`server.live.mature_sources.shape_build_level_probe()` 生成安全摘要；对 HTML/JS 只统计脚本数量、
是否存在明显 API 路径字符串和内容 hash 前缀。

## URLs probed

| URL | HTTP | Content type | Safe finding |
| --- | ---: | --- | --- |
| `https://poe.ninja/poe2/api/data/index-state` | 200 | `application/json` | 顶层 key 为 `buildLeagues`、`economyLeagues`、`oldBuildLeagues`、`oldEconomyLeagues`、`snapshotVersions`；未发现 build-level rows。 |
| `https://poe.ninja/poe2/api/data/build-index-state` | 200 | `application/json` | 顶层 key 为 `leagueBuilds`；nested league row shape 包含 `category`、`hardcore`、`leagueName`、`leagueUrl`、`statistics`、`status`、`total`；`statistics` row shape 为 `class`、`percentage`、`trend`；未发现 build-level rows。 |
| `https://poe.ninja/poe2/builds` | 200 | `text/html` | 页面可访问；探测到 2 个 script；HTML 中未直接发现 `/api/data/...` 路径。 |
| `https://poe.ninja/poe2/builds/runesofaldur` | 200 | `text/html` | 页面可访问；探测到 2 个 script；HTML 中未直接发现 `/api/data/...` 路径。 |
| `https://poe.ninja/poe2/api/data/builds?league=runesofaldur` | 404 | none | 猜测 build-level API 不存在或不可公开访问。 |
| `https://poe.ninja/poe2/api/data/buildoverview?league=runesofaldur` | 404 | none | 猜测 buildoverview API 不存在或不可公开访问。 |
| `https://poe.ninja/poe2/api/data/build-overview?league=runesofaldur` | 404 | none | 猜测 build-overview API 不存在或不可公开访问。 |
| `https://poe.ninja/poe2/api/data/0/getbuildoverview?overview=runesofaldur&type=exp&language=en` | 404 | none | 旧式 path 不适用于当前 PoE2 路径。 |
| `https://poe.ninja/api/data/0/getbuildoverview?overview=runesofaldur&type=exp&language=en` | 404 | none | 旧式非 poe2 path 不适用于当前 PoE2 路径。 |

## Response shape summary

### `index-state`

- Build-level rows available: no
- Shape summary:
  - `buildLeagues`
  - `economyLeagues`
  - `oldBuildLeagues`
  - `oldEconomyLeagues`
  - `snapshotVersions`
- Safe conclusion: 适合 freshness / league / snapshot 发现，不适合作为成熟 BD 样本来源。

### `build-index-state`

- Build-level rows available: no
- Top-level shape:
  - `leagueBuilds`
- Nested `leagueBuilds` row shape:
  - `category`
  - `hardcore`
  - `leagueName`
  - `leagueUrl`
  - `statistics`
  - `status`
  - `total`
- Nested `statistics` row shape:
  - `class`
  - `percentage`
  - `trend`
- Safe conclusion: 当前公开 JSON 只稳定暴露 league / ascendancy popularity / sample-size 级别信息，
  不能当作 build-level 热门 BD 样本。

### HTML pages

- `poe2/builds` 和 `poe2/builds/runesofaldur` 都可访问。
- 页面本身未直接暴露可复用的 `/api/data/...` build-level 路径。
- 本次未保存 HTML 或 JS bundle 内容。

## Build-level rows available

Current result: no stable public build-level JSON endpoint found.

这个结论只代表本次探测结果。后续仍可继续研究页面运行时、网络请求、protobuf/二进制资源或其他社区来源，
但不能在当前代码中假设 poe.ninja build-level rows 已经可用。

## Fallback plan

Phase 3N.3 后续应采用 fallback 流程：

1. 继续使用 poe.ninja `index-state` / `build-index-state` 作为 freshness、league、passive tree、
   sample-size 和 ascendancy popularity context。
2. 成熟 BD 样本先从其他来源获取：
   - pobb.in / PoB import；
   - 高热度论坛/攻略；
   - 社区视频/帖子中人工 curated 的 sanitized fixture；
   - 已有 reference builds 的非复制 calibration 摘要。
3. 对所有 fallback 样本要求 manifest：
   - 来源类型；
   - popularity basis；
   - league / patch / passive tree；
   - diversity bucket；
   - copyability proof。
4. 不实现自动周期性 fetcher，除非用户确认。

## Product impact

- `server/live/mature_sources.py` 的当前职责保持为 source probe shape helper。
- `server/live/meta.py` 继续保持保守：不能从 ascendancy-only payload 推断技能/装备/build-level meta。
- `docs/PROJECT_SPEC.md` 中的“真实 poe.ninja build-level 热门样本抓取器”仍应保持未实现。
- 3N.3 下一步应转向样本 manifest / sanitized brief 合同，以及 pobb.in/forum/manual curated fallback 样本流程。
