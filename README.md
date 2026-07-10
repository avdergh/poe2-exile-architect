# Exile Architect

Exile Architect 是一个 verification-first 的 Path of Exile 2 BD 研究与生成工具基座。它不尝试在项目内部重新训练或内置一个模型循环，而是让 Codex、Claude Code 等成熟 agent 负责研究与推理；仓库负责确定性工具、MCP 合同、图谱、记忆、安全边界和验收。

当前可用的两条产品入口是成熟 BD 研究提取和 Agent 主导的 BD 生成原型：前者把安全机制知识写入
长期记忆，后者让 Agent 查询这些知识、搭建活动 PoB、运行 Judge 并进行有限内部修正。

## 能做什么

- 从 poe.ninja 当前赛季普通服拉取 90-100 级成熟 BD 样本。
- 支持本地单个或批量 PoB import code / XML。
- 用 `/poe-bd-research` 或 `$poe-bd-research` 启动队列。
- 用 `/poe-bd-create` 或 `$poe-bd-create` 启动 Phase 5 Agent 主导生成原型；Agent 负责理解、
  查询、候选设计和活动 PoB 搭建，程序负责运行绑定、快照捕获、Judge 调用和人工验收包生成。
- 每个 Researcher worker 只读取一个 transient raw-rich prompt。
- 通过 resolver、typed schema、copy-safety 和 proposal gate 后才入库。

仍在建设中的能力包括官方 `.build` 导出、完整 Critic 修复/回滚/提前停止循环、分场景多技能
组合评分和 reward memory。README 不把这些描述成已完成产品。

## 安装

Codex 本地 MCP 运行需要 [uv](https://docs.astral.sh/uv/)；安装器会优先使用仓库内
`.tools/uv`，其次使用 `PATH` 中的 `uv`。两者都不存在时会明确停止，不会写入一个无法启动的
MCP 配置。

Windows PowerShell：

```powershell
.\install.ps1 codex
```

macOS / Linux：

```bash
./install.sh codex
```

常用选项：

```powershell
.\install.ps1 -DryRun codex
.\install.ps1 -Update
.\install.ps1 -Uninstall codex
```

```bash
./install.sh --dry-run codex
./install.sh --update
./install.sh --uninstall codex
```

安装器会链接 `poe-bd-creator-plugin/skills/poe-bd-research` 和
`poe-bd-creator-plugin/skills/poe-bd-create`，不会覆盖已有真实目录；卸载只删除自己创建的
symlink/junction。

安装器还会为 Codex 注册本项目 MCP 服务 `poe2_build_mcp`，这样 `/poe-bd-create` 运行时才能
看到 `query_research_memory`、`find_skills`、`new_build`、`evaluate_generation_candidate` 等工具。修改会写入
`~/.codex/config.toml` 中带有 `poe-bd-creator managed MCP server` 标记的配置块；卸载 Codex
目标时只删除这个托管配置块，不会改动其他 MCP 服务。

## 使用 `/poe-bd-create`

当前 `/poe-bd-create` 是 Phase 5 原型入口：Agent 负责把“我想要一个适合新手开荒的 BD”这类
自然语言需求转成更具体的设计提示词或最小 BuildBrief 摘要，自己按需查询项目工具，并在活动
PoB 中搭建候选 BD。程序先通过 `scripts/create_build.py start-run` 创建本次独立运行，再由
`evaluate_generation_candidate` 捕获构筑并运行 Phase 1 Judge，最后由
`scripts/create_build.py review-packet` 核对可信评估结果并整理人工验收包。程序不接管 BD 补全，
Judge 结果也仍需人工判断。

示例：

```text
/poe-bd-create 我想要一个适合新手开荒的 Deadeye 弓系 BD
```

无参数时，skill 应先询问目标、职业/升华、主技能、预算、trade/SSF 和防御偏好，而不是直接
开始生成。若输入包含 pobb.in、PoB code 或其他可复制 build material，入口必须先移除原始材料，
再以注意事项或追问形式处理。

如果用户只要求当前开荒阶段、但同时说明后期要洗点转攻坚/终局，Agent 产物应把当前输出阶段
保存在 `currentOutputStages`，把完整生命周期目标保存在 `targetLifecycleStages`，并用
`crossStageLockedDimensions=["class"]` 表达跨阶段只能锁职业。

## 使用 `/poe-bd-research`

在 Codex 或支持 skill 的宿主里输入：

```text
/poe-bd-research --limit 20 --worker-count 5
```

这是会话里的 skill 指令，不是让你在聊天框里执行 shell 命令。Codex agent 会在后台调用本地脚本和工具。

如果不带参数，skill 应先询问运行数量和模式，而不是先联网 dry-run，也不是静默启动完整 50 样本采集。你可以选择：预检 5 个样本（推荐，不入库）、小批量提取 20 个样本、大批量提取 50 个样本，或恢复已有队列。

如果宿主支持交互式选择控件，应优先显示这些选项。不支持时退化为普通文字选项。`--resume` 是独立恢复模式，不绑定到 50 个样本。

含义：

- 默认从 poe.ninja 当前 softcore trade league 拉样本；
- 等级默认 90-100；
- `--worker-count 5` 表示最多 5 个并发 Researcher agent lane；
- 每个 lane 每次只分析一个完整 BD；
- 默认不复用 raw-rich transcript，避免前一个样本污染后一个样本。

筛升华：

```text
/poe-bd-research --limit 30 --ascendancy Deadeye
```

使用本地批量 code 文件：

```text
/poe-bd-research --source-batch-file samples.txt --worker-count 5
```

如果宿主不支持程序化 subagent，它必须明确报告 `requestedWorkers`、`effectiveWorkers=1` 和降级原因，然后串行执行。

`/poe-bd-research` 是产品运行态入口，不是开发任务。运行期间 agent 只能操作队列、lease、transient prompt、safe review 和 acceptance；如果 collector 或外部源失败，应报告 `collector_failed` / `source_unavailable` / `runtime_failed`，不能现场修改仓库源码、测试或文档。

## 脚本入口

skill 内部使用这个产品化脚本。普通 Codex 桌面用户不需要手动运行这些命令；它们主要用于 CLI/debug 或其他宿主集成：

```powershell
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py queue --limit 20 --worker-count 5
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py claim --output-dir .poe-bd-research
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py worker-brief --output-dir .poe-bd-research --lease-token <leaseToken>
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py prompt --output-dir .poe-bd-research --lease-token <leaseToken>
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py accept --output-dir .poe-bd-research --lease-token <leaseToken> --review-file <safe-review.json>
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py status --output-dir .poe-bd-research
.\.tools\uv\uv.exe run python scripts\create_build.py start-run --memory-mode memory_assisted
.\.tools\uv\uv.exe run python scripts\create_build.py review-packet --run-id <runId> --run-token <runToken>
```

macOS / Linux 将 `.\.tools\uv\uv.exe` 替换为 `./.tools/uv/uv`。

## 安全边界

- 不持久化 PoB code、raw XML、完整装备表、完整天赋路径、完整 gem/support links、账号名、角色名或完整 URL。
- `queue`、`claim`、`status`、`accept` 只输出 safe metadata。
- `worker-brief` 只输出 safe worker 首条消息；宿主应把其中的 `workerPrompt` 原样发给 subagent，不要只发送本机 `SKILL.md` 路径或临时说明。
- `prompt` 是唯一会输出 raw-rich transient material 的子命令，只应由持有 lease 的 Researcher worker 调用。
- 没有 static source 不能创建 physical node。
- 没有已解析 graph node 不能写 semantic edge。
- 单个样本只能形成 `case_observation`，不能宣称“通常”“常见”。

## 平台能力

| 平台 | Skill 发现 | MCP 工具 | 程序化并发 worker | 本地 uv / PoB |
| --- | --- | --- | --- | --- |
| Codex | 支持 | 支持 | 支持 | 支持 |
| Claude Code | 支持 | 取决于本地配置 | 默认串行降级 | 支持 |
| Cursor / VS Code Copilot | 取决于宿主 skill/plugin 支持 | 取决于本地配置 | 默认串行降级 | 支持 |
| Gemini / OpenCode / OpenClaw / Hermes | 取决于宿主 | 取决于本地配置 | 默认串行降级 | 支持 |

多平台兼容的目标是让同一套 skill、脚本和安全合同可被不同 agent 宿主使用；不是承诺每个平台都有 Codex 一样的 subagent 调度能力。
