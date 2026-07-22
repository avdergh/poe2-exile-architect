# Exile Architect

Exile Architect 是一个 verification-first 的 Path of Exile 2 BD 研究与生成工具基座。它不尝试在项目内部重新训练或内置一个模型循环，而是让 Codex、Claude Code 等成熟 agent 负责研究与推理；仓库负责确定性工具、MCP 合同、图谱、记忆、安全边界和验收。

当前产品入口包括成熟 BD 研究提取、Agent 主导的 BD 生成，以及 Phase 7 对照学习：先对原 BD
安全建模，再让独立 Create 只按相同 Family 和等级盲测生成，最后由独立 Comparator 逐维比较，
把具体知识回流 Research、把跨维生成经验写入本地 Learning Memory。

## 能做什么

- 从 poe.ninja 当前赛季普通服拉取 90-100 级成熟 BD 样本。
- 支持本地单个或批量 PoB import code / XML。
- 用 `/poe-bd-research` 或 `$poe-bd-research` 启动队列。
- 用 `/poe-bd-research-loop` 或 `$poe-bd-research-loop` 运行 Desktop 可见研究循环。每个计划项
  都会创建一个新的侧边栏任务：`gpt-5.6-sol + medium` 研究，同一任务切换到 `xhigh` review
  和 fix；用户直接打开任务查看完整过程。控制任务只推进阶段和报告 thread ID/终态，不复制
  子任务正文。`poe_research_orchestrator` MCP 只保存 Markdown claim、检查点、暂停和恢复状态，
  不创建会话、不调用模型，也不启动后台控制台。
- 用 `/poe-bd-create` 或 `$poe-bd-create` 启动 Phase 5 Agent 主导生成原型；Agent 负责理解、
  查询、候选设计和活动 PoB 搭建，程序负责运行绑定、快照捕获、Judge 调用和人工验收包生成。
- 用 `/poe-bd-learning-loop` 或 `$poe-bd-learning-loop` 运行 Phase 7 对照学习。默认首批 10 个案例
  严格串行；每案例只运行一次 Create，Judge 只作参考，改进只影响后续案例。
- 对最终通过且被 Agent 接受的候选，保存本地私有 PoB artifact，并导出桌面 PoB XML、PoB
  导入码文本和官方单阶段 `.build` 文件。
- 当前 Researcher Agent 每次只处理一个 transient 案例，并通过有界清单、分区读取和搜索获得证据。
- 通过 resolver、typed schema、copy-safety 和 acceptance gate 后才入库。

Phase 7 功能正在建设；十案例趋势只能证明方向性信号，不能证明 Memory 与质量提升之间的因果。
分场景多技能组合评分和 Phase 8 仍待后续规划。当前导出能力用于交付和暴露前置构筑问题，不代表
Agent 已能稳定创造所有类型的高水平 BD，也不代表完整产品闭环已经成熟。

## 安装

Codex 本地 MCP 运行需要 [uv](https://docs.astral.sh/uv/)；安装器会注册统一的
`poe2_build_mcp`，并优先使用仓库内
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
.\install.ps1 -RegisterMcpOnly
.\install.ps1 -Update
.\install.ps1 -Uninstall codex
```

```bash
./install.sh --dry-run codex
./install.sh --register-mcp-only
./install.sh --update
./install.sh --uninstall codex
```

安装器会链接 `poe-bd-creator-plugin/skills/poe-bd-research`、
`poe-bd-creator-plugin/skills/poe-bd-create`、
`poe-bd-creator-plugin/skills/poe-bd-research-loop` 和
`poe-bd-creator-plugin/skills/poe-bd-learning-loop`，不会覆盖已有真实目录；卸载只删除自己
创建的 symlink/junction。

安装器还会为 Codex 注册本项目 MCP 服务 `poe2_build_mcp`，这样 `/poe-bd-create` 运行时才能
看到 `query_research_memory`、`find_skills`、`new_build`、`evaluate_generation_candidate` 等工具。修改会写入
`~/.codex/config.toml` 中带有 `poe-bd-creator managed MCP server` 标记的配置块；卸载 Codex
目标时只删除这个托管配置块，不会改动其他 MCP 服务。
已有本地 checkout 和 skills、只缺 MCP 工具时，可使用 `-RegisterMcpOnly` / `--register-mcp-only`；
该模式不会 pull、clone 或重新链接 skill。注册后需要新建 Codex 任务以重新发现工具。

## 使用 `/poe-bd-create`

当前 `/poe-bd-create` 是 Phase 5 原型入口：Agent 负责把“我想要一个适合新手开荒的 BD”这类
自然语言需求转成更具体的设计提示词或最小 BuildBrief 摘要，自己按需查询项目工具，并在活动
PoB 中搭建候选 BD。程序先通过 `scripts/create_build.py start-run` 创建本次独立运行，再由
`evaluate_generation_candidate` 捕获构筑并运行 Phase 1 Judge，最后由
`inspect_generation_preflight` 先检查活动构筑，再由 `scripts/create_build.py validate-output` 做
非消费校验、`scripts/create_build.py review-packet --compact` 核对可信评估结果并整理人工验收包。
程序不接管 BD 补全，
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

研究案例必须由当前主会话逐案完成，禁止委派给 subagent 或独立 agent lane，因为研究 MCP 工具只
保证在当前主会话可用。

在 Codex 或支持 skill 的宿主里输入：

```text
/poe-bd-research --limit 20
```

这是会话里的 skill 指令，不是让你在聊天框里执行 shell 命令。Codex agent 会在后台调用本地脚本和工具。

如果不带参数，skill 应先询问运行数量和模式，而不是先联网 dry-run，也不是静默启动完整 50 样本采集。你可以选择：预检 5 个样本（推荐，不入库）、小批量提取 20 个样本、大批量提取 50 个样本，或恢复已有队列。

如果宿主支持交互式选择控件，应优先显示这些选项。不支持时退化为普通文字选项。`--resume` 是独立恢复模式，不绑定到 50 个样本，并且必须带上原始 `queue` 返回的 `--output-dir <runDir>`。

含义：

- 默认从 poe.ninja 当前 softcore trade league 拉样本；
- 等级默认 90-100；
- 当前 Agent 一次只领取并分析一个完整 BD；
- 当前案例完成验收后，才继续领取下一案；
- 默认不复用 raw-rich transcript，避免前一个样本污染后一个样本。

筛升华：

```text
/poe-bd-research --limit 30 --ascendancy Deadeye
```

使用 poe.ninja 自身的 `class` URL 条件筛选来源（当前网站该参数填写升华名称）：

```text
/poe-bd-research --limit 10 --class "Blood Mage" --level-min 95 --level-max 95
```

程序会把它编码为 `class=Blood+Mage`；从网页条件取得的 `--class "Blood+Mage"` 也会归一为
同一名称，不会二次编码为 `%2B`。collector 会在采样前再次排除不匹配的升华；不传 `--class`
时不会增加该 URL 参数。

使用本地批量 code 文件：

```text
/poe-bd-research --source-batch-file samples.txt
```

`/poe-bd-research` 是产品运行态入口，不是开发任务。运行期间 agent 只能操作队列、lease、transient prompt、safe review 和 acceptance；如果 collector 或外部源失败，应报告 `collector_failed` / `source_unavailable` / `runtime_failed`，不能现场修改仓库源码、测试或文档。

## 脚本入口

skill 内部使用这个产品化脚本。普通 Codex 桌面用户不需要手动运行这些命令；它们主要用于 CLI/debug 或其他宿主集成：

```powershell
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py queue --limit 20
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py claim --output-dir <runDir>
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py worker-brief --output-dir <runDir> --lease-token <leaseToken>  # 仅恢复已领取任务
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py prompt --output-dir <runDir> --lease-token <leaseToken>
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py inspect --output-dir <runDir> --lease-token <leaseToken>
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py read --output-dir <runDir> --lease-token <leaseToken> --section skills --cursor 0 --limit 20
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py search --output-dir <runDir> --lease-token <leaseToken> --query <componentName>
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py review-contract --output-dir <runDir> --lease-token <leaseToken>
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py init-review --output-dir <runDir> --lease-token <leaseToken>
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py accept --output-dir <runDir> --lease-token <leaseToken> --review-file <safe-review.json> --validate-only
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py accept --output-dir <runDir> --lease-token <leaseToken> --review-file <safe-review.json>
.\.tools\uv\uv.exe run python scripts/research_mature_builds.py status --output-dir <runDir>
.\.tools\uv\uv.exe run python scripts\create_build.py start-run --memory-mode memory_assisted
.\.tools\uv\uv.exe run python scripts\create_build.py validate-output --run-id <runId> --run-token <runToken>
.\.tools\uv\uv.exe run python scripts\create_build.py review-packet --compact --run-id <runId> --run-token <runToken>
```

macOS / Linux 将 `.\.tools\uv\uv.exe` 替换为 `./.tools/uv/uv`。

非 dry-run 的默认 `queue` 会返回唯一的 `runDir`，后续命令必须原样使用。每个研究会话拥有独立
`.poe-bd-research/runs/<runId>`，因此多个会话可以并发运行；已有队列目录不会被静默覆盖。

## 安全边界

- 不持久化 PoB code、raw XML、完整装备表、完整天赋路径、完整 gem/support links、账号名、角色名或完整 URL。
- `queue`、`claim`、`prompt`、`inspect`、`review-contract`、`init-review`、`status` 和 `accept` 只输出 safe metadata 或安全合同。
- `claim` 原子返回当前案例的 safe brief；当前 Agent 直接遵守其中的 `workerPrompt`，不得转交给其他 agent。`worker-brief` 仅用于恢复已领取的任务。
- `prompt` 是兼容入口，只返回 safe manifest 和后续命令，不再输出 raw XML 或 PoB code。
- 当前 lease 持有者使用 `inspect` 查看分区清单，再用 `read` 分页读取 `skills`、`gear`、`passives`、`config` 和 `build`；`search` 只搜索当前 transient 案例。
- `review-contract` 在提交前提供 canonical 枚举和 JSON 模板；`init-review` 原子创建 lease 绑定的
  JSON 骨架且不覆盖已有工作；先运行 `accept --validate-only` 自检，普通 `accept` 是队列研究唯一的 durable memory 写入入口。
- `readyForAccept` 表示安全子集可接收，`fullyResolvedForAccept` / `acceptanceMode=clean` 才表示没有
  暂缓候选或组件解析缺口；safe review 使用 UTF-8、两空格缩进的多行 JSON，便于 Agent 有界修复。
- 没有 static source 不能创建 physical node。
- 没有已解析 graph node 不能写 semantic edge。
- 单个样本只能形成 `case_observation`，不能宣称“通常”“常见”。

## 平台能力

| 平台 | Skill 发现 | MCP 工具 | 串行逐案研究 | 本地 uv / PoB |
| --- | --- | --- | --- | --- |
| Codex | 支持 | 支持 | 支持 | 支持 |
| Claude Code | 支持 | 取决于本地配置 | 支持 | 支持 |
| Cursor / VS Code Copilot | 取决于宿主 skill/plugin 支持 | 取决于本地配置 | 支持 | 支持 |
| Gemini / OpenCode / OpenClaw / Hermes | 取决于宿主 | 取决于本地配置 | 支持 | 支持 |

多平台兼容的目标是让同一套 skill、脚本和安全合同可被不同 agent 宿主串行执行。
