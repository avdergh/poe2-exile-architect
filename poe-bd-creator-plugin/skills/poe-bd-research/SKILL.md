---
name: poe-bd-research
description: Use when the user wants to collect, queue, analyze, or store mature Path of Exile 2 build knowledge from poe.ninja or local PoB import codes.
---

# /poe-bd-research

把成熟 PoE2 BD 样本转成 copy-safe、resolver-backed、planner-advisory 的研究记忆。当前会话只负责
建立/恢复队列、编排显式 Research Worker、汇总与清理；每个案例都由独立 Subagent 使用
`$poe-bd-research-worker` 完成。

## Controller Boundary

- 主会话永不 claim、读取案例证据、编辑 review 或 accept，也不提供串行 fallback。
- queue 前确认宿主的 Subagent 能共享 Research MCP 工具面和 opaque `runRef`。产品态运行不依赖当前
  checkout/cwd，也不把 queue/review/quarantine 写入项目或插件缓存。
- 目标宿主容量是 6 个活动槽位：Controller 占 1 个，Research Worker、回访和其他
  Subagent 共享剩余 5 个，超出部分排队。Research Worker 的业务并发上限仍为 5；宿主实际
  总容量低于 6 时按可用槽位降级，并向用户报告实际 Worker 数，不得宣称已启用 5 Worker。
  只在 `status.dispatchableCount > 0` 时创建新 Worker；该值包含 queued 与 lease 已过期、可由
  claim 原子回收的 claimed 案例。
- 这是产品运行态，不得修改源码、测试、文档、schema、安装脚本或 plugin manifest。collector、运行
  绑定或 queue 失败时只报告 safe error 并停止，不在本次运行临场修代码。
- 用户在会话中输入 `/poe-bd-research` / `$poe-bd-research` 是请求 Agent 执行 workflow，不是 shell
  命令；不要要求用户复制内部 PowerShell/Python 命令。
- queue/status/cleanup 和 Worker 返回必须保持 safe-only。原始 PoB code/XML、账号/角色明细和完整 URL
  不得进入普通聊天、Research Memory 或 Git。

## Options

`$ARGUMENTS` 可包含：

- `--limit N`：从 poe.ninja 当前 softcore trade league 取样；交互式无参时不得静默使用 CLI 的 50。
- `--worker-count N`：Research Worker 数，范围 1–5，默认 5；宿主容量更低时自动降低实际并发。
- `--league current|<league-url>`：poe.ninja league，默认 `current`。
- `--ascendancy NAME`：可重复，对已渲染结果做本地升华筛选。
- `--class NAME`：可重复，透传 poe.ninja 的 `class` 参数；`Blood+Mage` 先归一，不得二次编码。
- `--level-min N` / `--level-max N`：默认 90–100；这是区间，精确等级需令两者相等。
- `--source-file PATH`：单个本地 PoB code/XML。
- `--source-batch-file PATH`：本地批量输入；每案由独立 Worker 处理。
- `--expected-source-count N`：本地输入的预期案例数；不符时不创建队列。
- `--resume --run-ref REF`：恢复新产品队列；仍由 Controller 派发全新的单案 Worker。
- `--legacy-run-dir PATH`：只用于把无活动 lease 的旧 run 复制进 user-data runtime；源目录保留。
- `--dry-run`：只验证 collector，不建队列、不产生知识。

快速粘贴的裸 PoB code、pobb.in/pastebin 链接或 raw XML 先保存到 OS temp 文件，再替换成
`--source-file <temp>`。不要把 code 原文放进命令行参数、run runtime 或仓库；链接先由宿主 fetch 后落临时
文件，无法本地化时才请用户提供文件。

角色级去重由本地 intake ledger 负责：queue 会跳过本 league 已研究角色并继续分页；正式 accept 后
记录晋升为 accepted。本地 source-file/batch 不走该 ledger。

## No-Argument Behavior

如果 `$ARGUMENTS` 为空，在任何联网或 queue 操作前询问：

- 小批量提取：真实 `limit=20`；
- 大批量提取：真实 `limit=50`；
- 恢复已有队列：用户提供 runRef；旧任务只有 legacy runDir 时先走 typed adoption；
- 链路预检：`limit=5 --dry-run`，仅在用户明确只想验证链路时使用。

用户已给案例数量、输入或分析意图时直接执行真实 queue，不要用 dry-run 替代。由
`poe-bd-research-loop` 发起且已经携带 `--limit` 等参数时也直接进入同一 Controller 流程，不再询问
菜单；后续案例仍全部交给 Worker。

## Typed Tool Binding

产品态只使用 Research MCP 的 `start_research_run / adopt_legacy_research_run /
get_research_run_status / cleanup_research_run`。工具未显示时先按精确名做 tool discovery；缺失时停止，不搜索仓库、不解析
插件安装路径，也不回退 shell CLI。工具返回的 `runRef` 是唯一运行身份；不得向 Worker 传 runDir、
reviewFile、插件 cache path 或 Research DB path。

源码仓库的 `scripts/research_mature_builds.py` 只保留开发/legacy 兼容，不属于发布 Skill 流程。

## Queue

调用 `start_research_run` 并逐字段传入用户参数。live collector 外层超时至少 10 分钟；超时后按
runtime failure 停止，不在同一 turn 重复 queue。非 dry-run 返回 `runId + runRef` 与安全计数；保存
runRef，后续 status/Worker 只使用它。`--resume` 调用
`get_research_run_status(run_ref=<runRef>)`；旧绝对 runDir 先调用
`adopt_legacy_research_run(legacy_run_dir=<旧路径>)`，活动 lease 未结算时停止，不复制/抢占。

## Worker Scheduling

每个 Worker 派发必须：

- 显式点名 `$poe-bd-research-worker`；
- 携带具名的 opaque `runRef`；
- 不指定 sampleId，不复制 Worker Skill 或逐案研究步骤；自然语言措辞可按当前上下文调整；
- 必须 fork 包含用户本次研究请求/授权的最近上下文；不得使用 `fork_turns=none`。Subagent 继承父任务
  权限模式，但用户授权上下文仍需可见，不能只由 Controller 转述。

初始创建数取 `dispatchableCount`、有效 worker-count 与宿主可用 Subagent 槽位的最小值；
目标 6 总槽位下可同时运行 5 个 Worker。维护活动 Research Worker 集合与待回访队列。任一 Worker
返回后读取其 safe outcome 并重新查询 status：

1. `dispatchableCount > 0` 时先用释放的槽位创建全新 Worker，再处理回访；
2. 回访已启用时，把 `sampleId → 原 agent` 加入待回访队列，不在仍有待研究案例时占用槽位；
3. 已完成 agent 不处理第二个 Research 案例；后续回访仍发送给该原 agent。

### Waiting Cadence

- Worker 运行期间使用宿主的事件等待原语；Codex 使用 `wait_agent(timeout_ms=300000)`。Worker
  完成或需要关注时由邮箱事件提前唤醒，不忙轮询。
- 300 秒超时且状态无变化时，不查询 queue status；最多发送一条简短心跳后继续下一个
  300 秒等待窗口。无变化心跳不得快于 5 分钟，不重复枚举相同的 Worker/lease 状态。
- 只有 Worker 返回、发生 safe error、需要补位/验收恢复，或用户主动询问状态时才立即唤醒并查询
  status。心跳不是 status 轮询授权。

- `worker_capacity_reached` / `no_pending_cases` 是无 sampleId 的调度结果，不记业务失败。
- `staleAcceptingCount > 0` 只表示可能存在中断的验收；不得自动回收或复制。等待对应活动 Worker
  结算；若已无对应 Worker 仍保持 stale，则停止 cleanup/补位并报告显式恢复所需诊断。
- claim 后的 Worker 必须返回 `sampleId + safe outcome`；accepted 时还返回 safe acceptance 摘要。
- 主会话保存 `sampleId → agent → acceptance → feedback`。
- validate/retry 是原 Worker 的正常单案修复路径，不释放为新案例。
- 不可恢复的单案错误结束该 Worker、保留 run/lease，Controller 继续其他 queued 案例，并把最终业务
  结果标为失败。
- 同一基础设施 safe error 若在两个新 Worker 中连续重复，停止补位并升级为 run-level runtime failure，
  避免无限创建 Worker。不得抢占或复制未过期 lease。

## Optional Revisit And Cleanup

回访默认关闭。用户明确要求时，在原 Worker 完成 Research 后记录到待回访队列；只有
当前 run 已无 dispatchable 案例且所有活动 Research Worker 均已结算后，才按原 agent 续聊。每次回访
只要求判断：高价值内容是否充分入库、是否发现工具/流程缺陷；只反馈，不修改。回访和其他
Subagent 与 Research Worker 共享 5 个 Subagent 槽位，超出部分排队。

无回访时，只有全部案例 accepted、status 无 queued/claimed/accepting/rejected 且计数一致后才调用
`cleanup_research_run(run_ref=<runRef>)`。

只有用户明确决定放弃一个未完成 run 时，才可对同一工具传
`abandon_incomplete=true`。该路径只释放由本 run 精确拥有、仍为 `queued` 的 intake-ledger 占位，
保留 `accepted` ledger、Research Memory、种子和用户导出；身份不匹配或目录删除失败时失败关闭并
回滚已释放占位。不得用手工删目录或直接改 SQLite 代替。

有回访时，反馈已返回不等于获得 cleanup 授权：

- 等用户明确确认或放弃全部反馈；
- 批准知识补录时，Controller 结束旧 Worker assignment，使用原 runRef 通过
  `re_research_run_ref + supplement_focus` 创建新的 supplement run，再把新 runRef 作为新的显式
  Worker assignment 续发给
  原 agent；不得要求旧 Worker 在原 assignment 中 queue 或领取第二案；
- 批准工具/流程修复时，follow-up 必须明确 Worker 运行态已经结束，本轮切换为普通开发任务，不再
  加载 Worker Skill 或执行 Research queue/claim；
- 修复与复核完成后再 cleanup；上下文或 agent 映射丢失时保留 runRef，不推断授权。

## Final Status

最终 status 和 Worker safe summaries 分别报告 accepted patterns、deep records、semantic edges、
created/updated/evidence counts、acceptanceMode、deferred reasons、unresolved mention/unique component
counts、mechanic audit 与 unique-gem diagnostics。不要把 partial_with_deferred 描述为 clean，也不要把
同一 unresolved 组件的多次 mention 当成多个不同组件。

当调用方要求研究业务标记时，最终回答最后一行必须且只能包含一个：

```text
POE_RESEARCH_SUCCEEDED: yes
POE_RESEARCH_SUCCEEDED: no
```

只有请求案例全部正式 accepted、status 无 queued/claimed/accepting/rejected、计数与持久化一致且没有
run-level/单案不可恢复失败时才输出 `yes`；否则输出 `no`。
