---
name: poe-bd-research
description: Use when the user wants to collect, queue, analyze, or store mature Path of Exile 2 build knowledge from poe.ninja or local PoB import codes.
argument-hint: ["[--limit N] [--worker-count N] [--ascendancy NAME] [--source-file PATH|--source-batch-file PATH]"]
---

# /poe-bd-research

把成熟 PoE2 BD 样本转成 copy-safe、resolver-backed、planner-advisory 的研究记忆。脚本只负责队列、lease、transient packet、验收和入库；外部 agent 负责逐案例研究。

## Runtime Mode - Hard Boundary

这是产品运行态 workflow，不是开发/调试任务。

- 用户在 Codex 会话框输入 `/poe-bd-research` / `$poe-bd-research` 是在请求 agent 执行 workflow，不是在执行 shell 命令。agent 必须自己用可用工具运行内部脚本；不要要求用户把 PowerShell/Python 命令复制到会话框或终端。
- 运行 `/poe-bd-research` / `$poe-bd-research` 时，不得修改仓库源码、测试、文档、schema、安装脚本或 plugin manifest。
- 不得调用调试/TDD/代码修改类 skill，不得使用 `apply_patch`，不得新增测试或现场修脚本。
- 只允许写入 `--output-dir` 下的队列/验收 artifact，以及 OS temp 下的 transient packet。
- 如果 queue、collector、claim、prompt 或 accept 失败，只报告 safe error 并停止。典型状态是 `collector_failed`、`source_unavailable` 或 `runtime_failed`。
- 如果用户需要修复失败原因，明确告诉用户这需要另开普通开发请求；不要在本次 research runtime 中临场改代码。

## Options

`$ARGUMENTS` 可包含：

- `--limit N`：从 poe.ninja 当前 softcore trade league 取样。底层 CLI 默认 50；交互式 skill 无参时不要静默启动 50。
- `--worker-count N`：并发 Researcher agent lane 数。底层 CLI 默认 5；它不是 prompt slot。
- `--ascendancy NAME`：可重复，按升华筛选。
- `--level-min N` / `--level-max N`：默认 90-100。
- `--source-file PATH`：单个本地 PoB code/XML。
- `--source-batch-file PATH`：本地批量文件；执行时仍一案一轮。
- `--resume`：复用已有队列和 lease 状态。
- `--dry-run`：只查看将入队的 safe 样本。
- `--output-dir PATH`：默认 `.poe-bd-research`。

## No-Argument Behavior

如果 `$ARGUMENTS` 为空，不要先联网 dry-run，也不要直接启动完整 50 样本 / 5 worker 的 live crawl。先询问用户要怎么运行。

如果宿主提供交互式选择/确认工具（例如 Codex 的 choice/confirmation UI），优先发起一个选择问题。建议选项：

- `预检 5 个样本（推荐）`：只执行 `limit=5`、`worker-count=1`、`--dry-run`，验证 poe.ninja/collector 可用，不创建实际队列。
- `小批量提取`：实际运行 `limit=20`、`worker-count=5`。
- `大批量提取`：实际运行 `limit=50`、`worker-count=5`。
- `恢复已有队列`：使用用户指定的 `limit` / `worker-count`，并附加 `--resume`。不要把 `--resume` 只绑定到大批量。

如果宿主没有选择控件，退化为普通文字选项，等待用户回复。不要在用户选择前联网采样。

```text
请选择运行方式：
1. 预检 5 个样本（推荐，不入库）
2. 小批量提取：20 个样本，5 个 worker
3. 大批量提取：50 个样本，5 个 worker
4. 恢复已有队列：请给出 limit / worker-count
```

如果给示例，只给 skill 命令：

```text
/poe-bd-research --limit 5 --worker-count 1 --dry-run
/poe-bd-research --limit 20 --worker-count 5
/poe-bd-research --limit 50 --worker-count 5
/poe-bd-research --limit 20 --worker-count 5 --resume
```

底层 `scripts/research_mature_builds.py` 命令是 agent 内部实现步骤，只在用户明确要求 CLI/debug 信息时展示。

## Progress

按阶段向用户报告：

1. `[Phase 1/5] Queue`：建立或恢复 safe queue。
2. `[Phase 2/5] Claim`：最多领取 `worker-count` 个 case。
3. `[Phase 3/5] Research`：每个 worker 只分析一个完整 BD。
4. `[Phase 4/5] Accept`：把 safe proposal/review 交给 acceptance gate。
5. `[Phase 5/5] Status`：报告 accepted/deferred/remaining。

## Workflow

下面的脚本命令是 agent 内部执行步骤。Codex 桌面用户不需要、也通常不能在会话框中执行这些命令。

1. 在项目根目录运行 queue：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py queue $ARGUMENTS
   ```

   Windows 可用：

   ```powershell
   .\.tools\uv\uv.exe run python scripts\research_mature_builds.py queue $ARGUMENTS
   ```

   如果该命令返回 `collector_failed` / `source_unavailable` / `runtime_failed`，报告 safe error 并停止；不要调试源码。

2. 如果宿主支持程序化 subagent（Codex 支持），启动最多 `worker-count` 个并发 worker。每个 worker 只拿一个 lease：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py claim --output-dir .poe-bd-research
   ```

   不要把 `SKILL.md` 路径或一段临时口头说明当作 worker 首条 prompt。claim 后先生成 safe-only worker brief：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py worker-brief --output-dir .poe-bd-research --lease-token <leaseToken>
   ```

   把返回 JSON 里的 `workerPrompt` 原样发给该 worker。`workerPrompt` 已内联运行边界、非权威 safe metadata、MCP 缺失 fallback 和 safe review artifact 形状；它不含 raw mature build material。不要在主 orchestrator 里读取 raw prompt。

3. Worker 根据 `workerPrompt` 自己运行：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py prompt --output-dir .poe-bd-research --lease-token <leaseToken>
   ```

   prompt 输出是 raw-rich transient material。worker 必须按 prompt 内 SOP 调 `query_research_memory`、resolver、`propose_*` tools，或写出 safe review artifact。禁止把 prompt、PoB code、raw XML、完整装备、完整天赋路径、完整 gem/support links 写入 repo、报告或聊天总结。
   如果 worker 会话没有暴露这些 MCP tools，worker 不应搜索隐藏工具或临时读源码找替代 API；直接写 `workerPrompt` 指定路径下的 safe review artifact，交给 orchestrator 的 `accept` gate 统一 resolver/schema/copy-safety/入库。

4. 若 worker 产出 safe review artifact，主 orchestrator 运行：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py accept --output-dir .poe-bd-research --lease-token <leaseToken> --review-file <safe-review.json>
   ```

5. 循环 claim/research/accept，直到 status 无 queued case：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py status --output-dir .poe-bd-research
   ```

## Worker Rules

- 一案一轮：一个 Researcher prompt 只能包含一个完整 BD。
- 默认不复用 raw-rich transcript。复用的是 queue lane、skill、脚本和工具，不是上一案的上下文。
- Codex 可并发 worker；不支持 subagent 的宿主必须报告 `requestedWorkers`、`effectiveWorkers=1` 和降级原因，然后串行执行。
- `worker-count` 表示并发 agent lane 数。不得解释为“预生成 N 个 prompt slot”。
- 若 claim 返回 no pending case，停止派发新 worker。

## Researcher Checklist

每个 worker 必须评估但不能强行编造这些设计轴：

- 升华 + 主技能：shell suitability，不是技能合法性。
- 主技能 + secondary skill：标 clear、boss、generator、payoff、movement、trigger host 等 role。
- 技能 + key passive / notable / keystone：必须 resolver-backed。
- 暗金 + 天赋点 / 技能：区分 required/enabling、optional/chase、budget substitute。
- support + active skill：只允许单 pair，不复制完整 support 套餐。
- scaling axis、weapon/base/stat priority、Spirit/reservation、defense package、mechanic chain、transition gate、failure mode、variant relation、modelability caveat。

## Safety

- queue/status/claim/accept 输出必须是 safe-only。
- `prompt` 是唯一允许输出 raw-rich material 的子命令，并且只能由持有 lease 的 worker 调用。
- missing/ambiguous endpoint 不得自动选择；最多 2 次 bounded repair，失败后写 manual mapping / source refresh。
- 单样本只能写 `case_observation`，不能宣称 common/usually/通常。
