# PoE2 实时新鲜度 Provider 设计

日期：2026-06-23  
状态：已确认（2026-06-23）  
范围：第二阶段——GGG、poe.ninja、PoB 实时证据与本地缓存

## 1. 目标

让 `get_freshness_report` 在网络可用时自动采集当前游戏补丁、联盟、官方天赋树、PoB 和
Meta 快照证据，并通过现有保守门禁判断是否足以标记为 `verified_current`。

本阶段不生成 BD、不下载完整 Ninja 角色库，也不把第三方 popularity 当作强度结论。

## 2. 选择的方案

采用“按来源独立 TTL、持久缓存、按需刷新”的方案 B。

每个来源拥有两个时间边界：

- `refresh_after`：超过此时间应尝试刷新；
- `reject_after`：超过此时间后，缓存不能继续提供 `current` 证据。

默认策略：

| 来源 | `refresh_after` | `reject_after` |
|---|---:|---:|
| GGG 补丁论坛 | 15 分钟 | 2 小时 |
| poe.ninja 快照和联盟 | 30 分钟 | 2 小时 |
| GGG 官方天赋树 GitHub | 1 小时 | 6 小时 |
| PoB GitHub release | 1 小时 | 6 小时 |
| 本地安装、PoB pin、语料库 | 每次读取 | 立即判断 |

TTL 是刷新调度，不是版本正确性的替代品。刚抓取的旧 PoB 仍然是 `stale`。

## 3. 调用行为

`get_freshness_report` 默认执行有上限的同步刷新：

1. 读取每个来源的最后成功缓存；
2. 缓存未到 `refresh_after` 时直接使用；
3. 缓存需要刷新时，在单个总时间预算内并行请求过期来源；
4. 请求成功则原子替换缓存；
5. 请求失败则回退到最后成功缓存；
6. 回退缓存超过 `reject_after` 时降级为 `stale`；
7. 从未成功缓存过且请求失败时生成 `unknown` 证据。

首个实现的总刷新预算为 8 秒，单来源网络超时为 5 秒。调用结束后必须返回报告，不能因
任意外部站点永久挂起。

`force_refresh=true` 跳过 `refresh_after`，但仍遵守网络超时和请求频率保护。它用于人工
检查新补丁，不由普通 Agent 在循环中反复调用。

## 4. 缓存模型

每个来源保存独立 JSON 文件：

```text
<POE2_MCP_DATA>/freshness/
  ggg-patch.json
  ggg-tree.json
  ninja-index.json
  ninja-build-index.json
  pob-release.json
```

缓存 envelope：

```json
{
  "schema_version": 1,
  "source": "ggg-patch",
  "source_url": "https://...",
  "fetched_at": "2026-06-23T08:30:00+00:00",
  "checked_at": "2026-06-23T08:30:00+00:00",
  "etag": null,
  "last_modified": null,
  "content_sha256": "...",
  "payload": {}
}
```

规则：

- `fetched_at`：当前 payload 首次或最近实际下载时间；
- `checked_at`：最近一次成功确认来源未变化的时间；
- HTTP `304` 只更新 `checked_at`，保留 `fetched_at` 和 payload；
- `content_sha256` 校验缓存内容，损坏时视为没有缓存；
- 写入使用临时文件加 `os.replace`，避免进程中断留下半份 JSON；
- 缓存只保存解析后的最小事实和必要原始字段，不长期保存整页论坛 HTML。

## 5. Provider 接口

所有 provider 实现同一同步接口：

```python
class EvidenceProvider(Protocol):
    name: str
    policy: CachePolicy

    def collect(
        self,
        *,
        now: datetime,
        force_refresh: bool = False,
    ) -> ProviderResult: ...
```

`ProviderResult` 包含：

- `evidence`：零条或多条 `FreshnessEvidence`；
- `cache_state`：`fresh`、`refreshed`、`revalidated`、`fallback`、`missing`；
- `diagnostics`：请求失败、解析失败、缓存年龄等非敏感信息；
- `duration_ms`。

Provider 不调用 freshness evaluator，也不互相调用。Service 并行收集结果后统一构造
`FreshnessManifest`。

## 6. GGG 补丁 Provider

来源：

- `https://www.pathofexile.com/forum/view-forum/2212`
- 最新匹配主题页

解析步骤：

1. 从索引按文档顺序查找第一个严格匹配
   `MAJOR.MINOR.PATCH` 或 `MAJOR.MINOR.PATCH Hotfix N` 的主题；
2. 提取主题 URL、完整标题和基础补丁；
3. 请求主题页并验证 `og:title` 与索引标题一致；
4. 读取首个 GGG staff 帖子的 `post_date` 原始文本；
5. 生成 `GAME_PATCH` 证据。

证据：

```text
component = game_patch
version = "0.5.3 Hotfix 9"
claims = game_patch:0.5.3
status = current
```

“current”仅表示这是官方补丁索引当前第一条版本主题。跨来源是否兼容由 evaluator 决定。

HTML 结构不符合预期时不能猜测，生成 `unknown`。

## 7. GGG 官方天赋树 Provider

来源：

- GitHub latest release API；
- GitHub main commit API；
- `data.json` 最新修改 commit。

生成两个证据：

### `LEAGUE`

- 版本：官方 release 名称中的联盟名；
- claim：规范化 league slug；
- URL：官方 release；
- release 名称无法解析时为 `unknown`。

### `PASSIVE_TREE`

- 版本：修改 `data.json` 的完整 commit SHA；
- claim：从 commit message 或 release tag 规范化的 `passive_tree=0_5`；
- URL：commit 页面；
- 必须验证 main 当前 SHA 与 `data.json` 最新 commit 关系，不能只看旧 release。

官方树 tag `0.5.2` 表示导出版本系列，不自动生成 `game_patch=0.5.2` claim。

## 8. poe.ninja Provider

来源：

- `/poe2/api/data/index-state`
- `/poe2/api/data/build-index-state`

主联盟选择规则：

1. 只从 `buildLeagues` 选择；
2. 排除 Standard、HC、SSF、Ruthless 和私人联盟；
3. 必须在 `snapshotVersions` 中存在相同 URL；
4. 若存在多个候选，选择快照日期最新者；
5. 无法唯一选择时生成冲突诊断，不按列表第一项猜测。

生成 `META_SNAPSHOT` 证据：

```text
version = snapshotVersions[].version
claims:
  league = snapshotVersions[].name
  passive_tree = snapshotVersions[].passiveTree
```

快照版本示例 `0653-20260623-55698` 中的八位日期用于检查快照年龄，但完整字符串仍是版本
标识。`build-index-state` 的同联盟样本量保存在 diagnostics，联盟不存在或样本量为零时
证据为 `unknown`。

本阶段不调用 `/poe2/api/builds/{version}/search`。

## 9. PoB Release 与本地 Pin Provider

远程来源：

- PoB GitHub latest release；
- release commit；
- release notes 和该 commit 的历史。

本地来源：

- `.runtime-data/installed.json`；
- `pob/PINNED.md`；
- 本项目维护的 `data/compatibility/pob.json`。

兼容清单使用显式事实：

```json
{
  "schema_version": 1,
  "entries": [
    {
      "commit": "dc409a7073e4e2752e9a642db7544af53551d006",
      "pob_version": "0.21.1",
      "game_patch": "0.5.3",
      "passive_tree": "0_5",
      "verified_by": ["golden-tests"],
      "verified_at": "..."
    }
  ]
}
```

只有命中本地兼容清单的安装 commit 才能生成补丁和树 claim。release notes 中出现
“0.5.3”只用于发现待验证候选，不能自动授予兼容。

如果远程最新 release 比本地 pin 新：

- 本地 PoB 证据状态为 `stale`；
- 报告列出远程版本和本地版本；
- 不自动安装或替换 PoB。

PoB 升级是单独任务：更新 pin、应用补丁、运行黄金测试、写入兼容清单后才可转为 current。

## 10. 状态与故障降级

| 情况 | Provider 状态 |
|---|---|
| 请求成功且解析成功 | 根据内容生成 `current`/`stale` |
| 条件请求 304 | 使用缓存，保持原内容状态 |
| 请求失败，缓存未超过 `reject_after` | 使用缓存；报告 warning |
| 请求失败，缓存超过 `reject_after` | 证据 `stale` |
| 请求失败且没有缓存 | 证据 `unknown` |
| 响应结构变化 | `unknown`，保存解析诊断，不保存错误 payload |
| 两个可信来源版本不一致 | 各自保持事实，由 evaluator 输出 `blocked_conflict` |

Provider 的网络错误不能抛到 MCP 顶层。编程错误和违反内部不变量仍应在测试中暴露，不能
被宽泛 `except Exception` 静默吞掉。

## 11. 并发与限流

- Service 最多同时执行 4 个外部来源请求；
- 同一进程中同一 provider 只允许一个进行中的刷新；
- 其他调用复用该刷新结果或旧缓存，不能产生请求风暴；
- `force_refresh` 仍受每来源最短 60 秒间隔限制；
- User-Agent 明确标识项目用途；
- 不绕过登录、验证码、访问控制或 robots 限制。

## 12. MCP 输出

`get_freshness_report` 增加可选参数：

```text
force_refresh: bool = false
```

保留现有字段，并增加：

```json
{
  "provider_status": [
    {
      "source": "ggg-patch",
      "cache_state": "fresh",
      "duration_ms": 3,
      "diagnostics": []
    }
  ]
}
```

`check_data_version` 继续包装同一报告。普通调用不会泄露缓存绝对路径、HTTP headers 中的
凭据或异常堆栈。

## 13. 测试策略

测试分三层：

1. **纯解析 fixture**
   - GGG 补丁索引与主题；
   - GitHub API JSON；
   - Ninja index/build-index JSON；
   - PoB release JSON。
2. **缓存状态机**
   - fresh、refresh、304、fallback、hard stale、corrupt cache；
   - 使用注入的时钟和 HTTP transport，不访问公网。
3. **Service/MCP 集成**
   - 全来源一致时 `verified_current`；
   - 本地旧 PoB 时 `blocked_stale`；
   - Ninja 树与官方树不一致时 `blocked_conflict`；
   - 单站离线且缓存有效时继续返回；
   - 所有外部来源失败时在时间预算内返回 `blocked_unknown`。

网络 smoke test 独立运行，不作为离线单元测试的必要条件。

## 14. 可观测性

日志只记录：

- source；
- cache state；
- HTTP 状态码；
- 请求耗时；
- 解析错误分类；
- 证据版本。

不记录完整响应正文。调试需要的 fixture 由开发者显式保存并脱敏。

## 15. 本阶段完成标准

- 四类外部来源均有 fixture 驱动的 provider；
- 缓存支持原子写入、内容哈希、条件请求和硬过期；
- 真实网络失败不会让 MCP 调用超过总预算；
- 旧 PoB pin 被正确判为 `blocked_stale`；
- PoB 升级并通过黄金测试后，兼容清单可使完整报告达到 `verified_current`；
- 文档记录每个来源的 URL、观察字段、TTL 和已知风险；
- Ruff、Mypy、离线测试和 MCP manifest 校验通过。
