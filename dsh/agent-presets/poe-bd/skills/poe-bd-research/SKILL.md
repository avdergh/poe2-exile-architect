---
name: poe-bd-research
description: Use when the user wants to collect, queue, analyze, or store mature Path of Exile 2 build knowledge from poe.ninja or local PoB import codes.
---

# 最高优先级 输出语言必须与用户一致

**这是本 Skill 的首要交付规则，优先于下文默认示例、模板、参考资料与宿主适配说明的语言。**
最终面向用户的表述跟随用户本次请求的自然语言；只有用户明确指定另一种输出语言时才覆盖。
标题、摘要、正文、表格、图表标签、注意事项、交付文件中的说明与会话结论都使用同一目标语言。
中英混合请求以表达需求的主要语言为准，不因 PoB、网页或组件名是英文而切换整份产物语言；
只有确实无法判断时才澄清。目标语言的官方专名未经核实时保留原名，周围解释仍使用目标语言。
工具名、schema 字段/枚举、stable key、回执、路径与代码不翻译；这条规则不改写既有知识记录，
也不改变 typed 合同。交付前检查实际正文语言，不能只修改 language 元数据。
委派、续聊或自动流程必须传递原始用户请求及其目标语言，接收任务的 Agent 沿用该选择。

> **DSH 适配说明**：本 skill 运行在 DeepSeek Harness。所有 poe-bd 能力都是 MCP
> 工具，完整名带 `mcp__poe_<server>__` 前缀（例如
> `mcp__poe_knowledge__query_research_memory`、`mcp__poe_build__get_build_stats`），
> 下文只写末尾名称。加载本 skill 使用 DSH 的 `skill` 工具，不存在 `/poe-bd-*`
> 斜杠命令。工具清单以当前会话实际注册为准，不要猜测未注册的工具名。
> **DSH 映射**：Controller 用 `subagent` 后台启动显式
> `poe-bd-research-worker`，等待后台结算，并用 `send_message` 续聊回访。
> queue、status 与 cleanup 使用 `mcp__poe_research__*` typed 工具；不得回退 shell。
> 每个 Research Worker 的 assignment 必须携带 opaque runRef、用户原始研究请求和授权上下文。

# /poe-bd-research

把成熟 PoE2 BD 样本转成 copy-safe、resolver-backed、planner-advisory 的研究记忆。当前会话建立/恢复
队列、编排显式 `$poe-bd-research-worker`、汇总与清理；每个案例由独立 Subagent 研究。

## Controller Boundary

- 主会话永不 claim、读取案例证据、编辑 review 或 accept，也不提供串行 fallback。
- queue 前确认宿主 Subagent 能共享 Research MCP 工具和 opaque `runRef`。运行态位于 user-data，
  不依赖 checkout/cwd，不把 queue/review/quarantine 写入项目或插件缓存。
- 本次是产品运行，不修改源码、测试、文档、schema、安装脚本或 plugin manifest。collector、运行绑定
  或 queue 失败时只报告 safe error 并停止，不临场修代码。
- `/poe-bd-research` / `$poe-bd-research` 是执行 workflow 的请求，不是 shell 命令；不要要求用户复制
  内部 PowerShell/Python 命令。queue/status/cleanup 与 Worker 返回保持 safe-only，原始 PoB/XML、
  账号/角色明细和完整 URL 不得进入普通聊天、Research Memory 或 Git。

## 参数

将 `$ARGUMENTS` 映射为 typed 参数：

| 用户选项 | 参数与含义 |
|---|---|
| `--limit N` | `limit`：当前 softcore trade league 样本数；无参按下节处理。 |
| `--worker-count N` | `worker_count`：请求并发，默认 5，范围 1–5。 |
| `--retention-days N` | `retention_days`：新run原料保留期限，默认7天，范围1–30；恢复不续期。 |
| `--league current\|<league-url>` | `league`：默认 `current`。 |
| `--ascendancy NAME` | `ascendancies` 列表：对渲染结果本地筛选，可重复。 |
| `--class NAME` | `classes` 列表：透传 poe.ninja class，可重复；`Blood+Mage` 先归一，不得二次编码。 |
| `--level-min N` / `--level-max N` | `level_min / level_max`：默认 90–100；精确等级令两者相等。 |
| `--source-file ABSOLUTE_PATH` / `--source-batch-file ABSOLUTE_PATH` | `source_files / source_batch_files` 列表：本地单个/批量输入，只接收绝对路径。 |
| `--expected-source-count N` | `expected_source_count`：本地输入预期数，不符不建队列。 |
| `--source-game-patch PATCH` | `source_game_patch`：本地来源实际版本，见“来源版本”。 |
| `--resume --run-ref REF` | 用 `mcp__poe_research__get_research_run_status(run_ref=REF)` 恢复调度。 |
| `--supplement-sample-id ID` | 可重复的补录目标，条件与调用见“回访、补录与清理”。 |
| `--dry-run` | `dry_run=true`：只验证 collector，不建队列、不产生知识。 |

用户粘贴的裸 PoB code/raw XML 先保存到 OS temp 文件，链接由宿主 fetch 后落临时文件，再用
`source_files`；无法本地化时才请用户提供文件。不要把 code 原文放入命令行、run runtime 或仓库。
工具接收URL时会在入队冻结已解析内容，之后claim不重新抓取该URL。旧URL-only队列或材料hash不符
保持不可恢复诊断，不能拿新响应重标旧来源；重新研究走新来源流程。
在线角色去重由本地 intake ledger 负责：跳过本 league 已入队角色并继续分页，accept 后晋升为 accepted；
本地 source-file/batch 不走该 ledger。

## No-Argument Behavior

`$ARGUMENTS` 为空时，在任何联网/queue 前询问：小批量 `limit=20`、大批量 `limit=50`、提供 runRef
恢复，或链路预检 `limit=5 --dry-run`。预检只用于用户明确要求验证链路，不能替代真实研究。
用户已给数量、输入或分析意图时直接 queue；`poe-bd-research-loop` 携带参数发起时不重复菜单。

## Typed Tool Binding 与来源版本

Controller 使用 `mcp__poe_research__start_research_run / mcp__poe_research__get_research_run_status / mcp__poe_research__cleanup_research_run` 管理运行态。
工具未显示先精确 discovery；缺失时停止，不搜索仓库/插件路径，也不回退 shell CLI。
`scripts/research_mature_builds.py` 仅供源码开发/legacy 兼容。向 Worker 只传 `runRef`，不传 runDir、
reviewFile、插件 cache path 或 Research DB path。

正常 Research 只研究最新版本 BD；历史知识用于召回和补丁对照。在线采样由服务端绑定官方当前
patch/联盟。本地文件必须有 `source_game_patch`：复用用户已明确的版本，未知时补齐后再 queue，
不能用本地 PoB 版本猜来源补丁。补录保持原队列来源版本；`modelGamePatch` 独立记录，来源与模型
不同表示模型缺口，不能重标来源或把旧模型输出当作当期数值认证。

调用 `mcp__poe_research__start_research_run` 时按参数表传入请求。live collector 外层超时至少 10 分钟；超时按 runtime
failure 停止，不在同一 turn 重复 queue。非 dry-run 保存返回的 `runId + runRef` 和安全计数。
普通新任务始终创建独立 run；只有用户显式给出已有 runRef 并要求恢复时才复用，不能覆盖既有 queue
或把新任务写进旧 run。

## Worker Scheduling

目标宿主容量是 6 个活动槽位：Controller 占 1 个，Worker、回访和其他 Subagent 共享剩余槽位。
Research Worker 的业务并发上限仍为 5；实际并发取 `dispatchableCount`、请求 worker-count 与宿主
可用槽位的最小值，并报告实际 Worker 数。只在 `status.dispatchableCount > 0` 时创建新 Worker；
该值含 queued 与 lease 已过期、可由 claim 原子回收的 claimed 案例，不得抢占或复制未过期 lease。

每个 assignment：

- 显式点名 `$poe-bd-research-worker`，携带具名 opaque `runRef`；
- 不指定 sampleId，不复制 Worker Skill 或逐案步骤；
- 必须用 `subagent` 后台派发并在 assignment 中携带用户本次研究请求/授权上下文；
  不得创建缺少父任务信息的空上下文 Worker，也不能只由 Controller 转述授权。

维护活动 Worker、待回访队列及 `sampleId → agent → acceptance → feedback`。Worker 返回后读取 safe
outcome，再查 status；已完成 agent 不处理第二案，回访仍发原 agent。

| 事件/状态 | Controller 动作 |
|---|---|
| `dispatchableCount > 0` 且有空槽 | 先用释放的槽位创建全新 Worker，再处理回访；启用回访时把已完成 sampleId 与原 agent 加入待回访队列。 |
| `worker_capacity_reached / no_pending_cases` | 无 sampleId 的调度结果，不记业务失败。 |
| 原 Worker 正在 validate/retry | 保持单案归属，不释放为新案例。 |
| `staleAcceptingCount > 0` | 不回收或复制；等待原 Worker 用同一 review/attempt 重放 accept，从 final write receipt 幂等完成 ledger/queue 收尾，即使 lease 过期也不重写 Memory。无对应 Worker 仍 stale 时，停止 cleanup/补位并报告恢复诊断。 |
| 不可恢复的单案错误 | 结束该 Worker，保留 run/lease，继续其他 queued 案例，最终业务结果记失败。 |
| 同一基础设施 safe error 在两个新 Worker 中连续重复 | 停止补位，升级为 run-level runtime failure。 |

claim 后的 Worker 必须返回 `sampleId + safe outcome`；accepted 还需 safe acceptance 摘要。

### Waiting Cadence

- Worker 运行期间依赖 DSH `subagent` 的后台结算通知，不调用 Codex `wait_agent`，也不忙轮询。
- 只有 Worker 结算、发生 safe error、需要补位/验收恢复，或用户主动询问状态时才查询 status；
  无变化时不发送心跳或重复枚举相同 Worker/lease。

## 回访、补录与清理

回访默认关闭。用户明确要求时记录到待回访队列，直到无 dispatchable 案例且所有活动 Worker 已结算，
再按原 agent 续聊。只判断高价值内容是否充分入库、是否发现工具/流程缺陷；只反馈，不修改。

无回访时，全部案例 accepted、`effectiveResearchCompleteCount == acceptedCount`、status 无
queued/claimed/accepting/rejected 且计数一致后才调用
`mcp__poe_research__cleanup_research_run(run_ref=<runRef>)`；还须确认 write receipt/legacy receipt 已保存并完成 ledger
reconciliation。接受安全子集不等于整案完成。出现缺口、用户要求补研或原料到期时，先读
[补研、重取与期限](references/followup-and-retention.md)，按工具返回的当前状态处理。

有回访时，反馈已返回不等于获得 cleanup 授权；等用户明确确认或放弃全部反馈：

- 批准知识补录：结束旧 Worker assignment，通过 `mcp__poe_research__start_research_run` 传
  `re_research_run_ref + supplement_sample_ids + supplement_focus`，从原 run quarantine 使用
  完全相同的 PoB 只重建获批同 case。目标须已 accepted 且 quarantine 可恢复；空、未知、未接受或
  不可恢复目标在建 run 前失败关闭。省略 `supplement_sample_ids` 才表示全 run 补录。
  保持原 researchGroup/Family 身份，只补既有缺口，必须产生 `created+updated >= 1`。
  将新 runRef 作为新 assignment 发原 agent，不让旧 assignment queue 或领取第二案。
- 批准工具/流程修复：follow-up 明确 Worker 运行态已经结束，切换普通开发任务，不再加载 Worker Skill
  或执行 Research queue/claim。
- 修复与复核后再 cleanup；上下文或 agent 映射丢失时保留 runRef，不推断授权。

显式放弃才传 `abandon_incomplete=true`；到期使用普通cleanup由锁定策略判断。活动lease、accepting
或待恢复状态不能绕过；清理保存安全审计，原runRef仍可查询。不得手工删目录或直接改SQLite。

## Final Status

分别报告 accepted patterns/deep records/semantic edges、created/updated/evidence counts、acceptanceMode、
deferred reasons、unresolved mention/unique component counts、writeReceiptRef、mechanic audit 和 unique-gem
diagnostics，并单列原始`researchCompletion`、当前`effectiveResearchCompletion`及未关闭缺口数。
partial_with_deferred 不描述成原始clean，
同一 unresolved 组件的多次 mention 不算多个组件。

调用方要求业务标记时，最终回答最后一行只能是 `POE_RESEARCH_SUCCEEDED: yes` 或
`POE_RESEARCH_SUCCEEDED: no`。仅当请求案例全部正式 accepted、status 无 queued/claimed/accepting/rejected、
计数与持久化一致、`effectiveResearchCompleteCount == acceptedCount` 且无 run-level/单案不可恢复失败时输出 yes，否则 no。
