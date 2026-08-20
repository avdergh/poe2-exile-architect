---
name: poe-bd-research
description: Use when the user wants to collect, queue, analyze, or store mature Path of Exile 2 build knowledge from poe.ninja or local PoB import codes.
---

> **DSH 适配说明**：本 skill 运行在 DeepSeek Harness。所有 poe-bd 能力都是 MCP
> 工具，完整名带 `mcp__poe_<server>__` 前缀（例如
> `mcp__poe_knowledge__query_research_memory`、`mcp__poe_build__get_build_stats`），
> 下文只写末尾名称。加载本 skill 使用 DSH 的 `skill` 工具，不存在 `/poe-bd-*`
> 斜杠命令。工具清单以当前会话实际注册为准，不要猜测未注册的工具名。
> **DSH 映射**：Controller 用 `subagent` 后台启动显式
> `poe-bd-research-worker`，等待后台结算，并用 `send_message` 续聊回访。
> queue 由 DSH shell（Windows 为 pwsh）执行，外层超时至少 `600000ms`。

# /poe-bd-research

把成熟 PoE2 BD 样本转成 copy-safe、resolver-backed、planner-advisory 的研究记忆。当前会话只负责
建立/恢复队列、编排显式 Research Worker、汇总与清理；每个案例都由独立 Subagent 使用
`$poe-bd-research-worker` 完成。

## Controller Boundary

- 主会话永不 claim、读取案例证据、编辑 review 或 accept，也不提供串行 fallback。
- queue 前确认宿主的 Subagent 能共享同一 filesystem、runDir、checkout/runtime 和 Research MCP
  工具面。宿主只有 spawn 能力但无法确认这些共享语义时，失败关闭且不创建队列。
- 最多同时运行 5 个当前 run 的案例研究 Worker；回访和其他任务不计入该业务上限，但仍受宿主总容量
  限制。只在 `status.dispatchableCount > 0` 时创建新 Worker；该值包含 queued 与 lease 已过期、可由
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
- `--resume --output-dir PATH`：恢复原 queue；仍由 Controller 派发全新的单案 Worker。
- `--dry-run`：只验证 collector，不建队列、不产生知识。
- `--output-dir PATH`：高级覆盖；普通新任务让 queue 创建独立 `runs/<runId>`。

快速粘贴的裸 PoB code、pobb.in/pastebin 链接或 raw XML 先保存到 OS temp 文件，再替换成
`--source-file <temp>`。不要把 code 原文放进命令行参数、runDir 或仓库；链接先由宿主 fetch 后落临时
文件，无法本地化时才请用户提供文件。

角色级去重由本地 intake ledger 负责：queue 会跳过本 league 已研究角色并继续分页；正式 accept 后
记录晋升为 accepted。本地 source-file/batch 不走该 ledger。

## No-Argument Behavior

如果 `$ARGUMENTS` 为空，在任何联网或 queue 操作前询问：

- 小批量提取：真实 `limit=20`；
- 大批量提取：真实 `limit=50`；
- 恢复已有队列：用户提供原 runDir；
- 链路预检：`limit=5 --dry-run`，仅在用户明确只想验证链路时使用。

用户已给案例数量、输入或分析意图时直接执行真实 queue，不要用 dry-run 替代。由
`poe-bd-research-loop` 发起且已经携带 `--limit` 等参数时也直接进入同一 Controller 流程，不再询问
菜单；后续案例仍全部交给 Worker。

## Runtime Binding

queue 前一次性解析并冻结：

1. `runtimeRoot` 优先取安装器管理的任一 `poe-*-mcp` cwd；否则取 `POE_BD_CREATOR_DIR`，再否则从当前
   Skill 的真实路径向上查找。候选必须包含 `server/main.py` 和 `scripts/research_mature_builds.py`，且
   是带 `pyproject.toml` 的源码仓库，或带 `.codex-plugin/plugin.json` 与
   `scripts/run_plugin_server.mjs` 的自包含插件；缺失或歧义时停止，不能猜 cwd 或全盘搜索。
2. 源码仓库按 `runtimeRoot/.tools/uv/uv.exe`、`runtimeRoot/.tools/uv/uv`、PATH uv 解析，冻结为：

   ```text
   [uvCommand, "run", "--project", runtimeRoot, "python", runtimeRoot/scripts/research_mature_builds.py]
   ```

   自包含插件复用 MCP 已注册的 Node，或从 PATH 解析 Node，冻结为：

   ```text
   [nodeCommand, runtimeRoot/scripts/run_plugin_server.mjs, "--research-cli"]
   ```

3. `researchCliArgv` 必须是上述绝对 argv 数组之一，不存成 shell 字符串。Node 只作为插件官方 Python
   启动器，不把它当成 uv；对应入口或解释器不可用时停止。

内部执行或派发时保持元素边界，路径含空格也不得重新拆分。

## Queue

用冻结 argv 追加 `queue` 和用户参数。live collector 外层超时至少 10 分钟；超时后按 runtime failure
停止，不在同一 turn 重复 queue。

非 dry-run queue 返回 `runId`、绝对 `runDir` 与 sample/status 计数。保存该 runDir，所有 Worker 和
status 命令都使用它；不得退回共享 `.poe-bd-research`。显式目录已有 queue 时只有 `--resume` 可以
复用，不能覆盖。

## Worker Scheduling

每个 Worker 派发必须：

- 显式点名 `$poe-bd-research-worker`；
- 携带具名的绝对 `runDir`；
- 不指定 sampleId，不复制 Worker Skill 或逐案研究步骤；自然语言措辞可按当前上下文调整；
- 宿主支持时使用无父上下文或最小上下文的新 Subagent。

初始创建数取 `dispatchableCount`、有效 worker-count 与宿主可用容量的最小值。维护活动 Research Worker
集合；任一 Worker 返回后读取其 safe outcome 并重新查询 status：只有 dispatchableCount 仍大于 0 才新建
Worker 补位，已完成 agent 不处理第二案。

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

回访默认关闭。用户明确要求时，在原 Worker 完成 Research 后续聊同一 agent，只要求判断：高价值内容
是否充分入库、是否发现工具/流程缺陷；只反馈，不修改。回访不占 Research Worker 上限，可与后续案例
研究重叠。

无回访时，只有全部案例 accepted、status 无 queued/claimed/accepting/rejected 且计数一致后才调用
`mcp__poe_build__cleanup_completed_task_runtime(task_kind="research", task_id=<runId>)`。

只有用户明确决定放弃一个未完成 run 时，才可对同一工具传
`abandon_incomplete=true`。该路径只释放由本 run 精确拥有、仍为 `queued` 的 intake-ledger 占位，
保留 `accepted` ledger、Research Memory、种子和用户导出；身份不匹配或目录删除失败时失败关闭并
回滚已释放占位。不得用手工删目录或直接改 SQLite 代替。

有回访时，反馈已返回不等于获得 cleanup 授权：

- 等用户明确确认或放弃全部反馈；
- 批准知识补录时，Controller 结束旧 Worker assignment，使用原 runDir 通过既有 `--re-research` /
  `--supplement-focus` 创建新的 supplement run，再把新 runDir 作为新的显式 Worker assignment 续发给
  原 agent；不得要求旧 Worker 在原 assignment 中 queue 或领取第二案；
- 批准工具/流程修复时，follow-up 必须明确 Worker 运行态已经结束，本轮切换为普通开发任务，不再
  加载 Worker Skill 或执行 Research queue/claim；
- 修复与复核完成后再 cleanup；上下文或 agent 映射丢失时保留 runDir，不推断授权。

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
