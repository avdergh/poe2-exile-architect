# Exile Architect

Exile Architect 是一个 verification-first 的 Path of Exile 2 BD 研究与生成工具基座。它不尝试在项目内部重新训练或内置一个模型循环，而是让 Codex、Claude Code 等成熟 agent 负责研究与推理；仓库负责确定性工具、MCP 合同、图谱、记忆、安全边界和验收。

## 能做什么

- 用成熟 Agent 研究 poe.ninja 或本地 PoB 来源，并沉淀经过安全过滤的结构化知识。
- 由 Agent 主导设计 PoE2 BD，使用本地资料、图、Headless PoB 和 Judge 做验证。
- 支持用户请求的目标等级单阶段终局 BD（典型 80+），不提供全链路开荒成长流程；最终能力和限制以当前 Skill、Phase 文档为准。
- Codex Desktop 额外提供 Research/Learning 可见任务循环；其他宿主当前安装 Research/Create。

## 安装

本地 MCP 运行需要 [uv](https://docs.astral.sh/uv/)；安装器会注册四个按域拆分的 MCP server
（`poe_knowledge_mcp`、`poe_build_mcp`、`poe_research_mcp`、`poe_learning_mcp`），
并优先使用仓库内
`.tools/uv`，其次使用 `PATH` 中的 `uv`。两者都不存在时会明确停止，不会写入一个无法启动的
MCP 配置。拆分让单阶段 Create 只发现 knowledge + build 两个 server，避免无关工具和重复
指令注入挤占上下文。
Research Skill 会复用安装器管理的仓库根和 `uv` 命令，并以绝对脚本路径运行；从其他项目调用时
不会把当前工作目录误当成本仓库。

官方 `.build` 转换和 MCPB manifest 校验需要 Node.js。项目优先使用
`POE_BD_NODE_EXECUTABLE` 显式配置或系统 `PATH`，也会自动发现 Codex Desktop 随附的 Node
运行时；不要求用户额外安装全局 `npx`。转换 provider 仍要求 Node 20 或更高版本。

### OpenCode 快速体验

已有 checkout 时，Windows PowerShell：

```powershell
.\install.ps1 -FromCheckout opencode
.\install.ps1 -FromCheckout -Doctor opencode
```

macOS / Linux：

```bash
./install.sh --from-checkout opencode
./install.sh --doctor opencode
```

安装后重启 OpenCode，再运行 `opencode mcp list`；列表中应出现 `poe_knowledge_mcp` 和
`poe_build_mcp`（另有两个 Research/Learning 域 server）。然后直接要求
Agent“使用 `poe-bd-create` skill 创建一个 PoE2 BD”或“使用 `poe-bd-research` skill 做成熟 BD
研究”。有些宿主会把 skill 暴露为斜杠命令，有些通过内置 skill tool 加载，因此不把
`/poe-bd-create` 是否出现在命令面板作为唯一验收标准。

OpenCode 安装器只链接 `poe-bd-research` 和 `poe-bd-create`，并安全合并
`~/.config/opencode/opencode.json` 的 `mcp` 下四个 server 条目。它不会迁移依赖 Codex Desktop 任务
编排能力的 `poe-bd-research-loop` / `poe-bd-learning-loop`。

### 从开源仓库安装

Windows PowerShell：

```powershell
.\install.ps1 codex
.\install.ps1 opencode
.\install.ps1 claude
.\install.ps1 cursor
```

macOS / Linux：

```bash
./install.sh codex
./install.sh opencode
./install.sh claude
./install.sh cursor
```

如果尚未 clone，可以先把安装脚本下载到临时文件、检查内容，再运行。安装器会把仓库放到
`~/.poe-bd-creator/repo`；也可以用 `POE_BD_CREATOR_DIR` 改位置。不要把远程脚本直接 pipe 给
shell。

常用选项：

```powershell
.\install.ps1 -DryRun codex
.\install.ps1 -FromCheckout opencode
.\install.ps1 -RegisterMcpOnly -McpHost opencode
.\install.ps1 -Doctor opencode
.\install.ps1 -Update
.\install.ps1 -Uninstall opencode
```

```bash
./install.sh --dry-run codex
./install.sh --from-checkout opencode
./install.sh --register-mcp-only opencode
./install.sh --doctor opencode
./install.sh --update
./install.sh --uninstall opencode
```

Codex 安装全部四个 skill；Claude Code、Cursor 和 OpenCode 当前只安装可移植的 Research/Create
两个 skill。安装器不会覆盖已有真实目录或同名非托管 MCP 配置；JSON 客户端首次修改前会保留
`.poe-bd-creator.bak`，并用本地指纹回执确保卸载只删除自己写入且未被用户修改的条目。

Codex Desktop 的 `poe-bd-research-loop` 需要独立的 `poe-research-orchestrator` checkout。设置
`POE_RESEARCH_ORCHESTRATOR_DIR`，或把它放在本项目 checkout 的同级目录；Skill 会校验标记文件后
使用，不依赖盘符、用户名或固定绝对路径。完整说明见[多 Agent 安装指南](docs/MULTI_AGENT_INSTALL.md)。

安装器会为 Codex、Claude Code、Cursor 和 OpenCode 注册本项目四个按域拆分的 MCP server
（`poe_knowledge_mcp` / `poe_build_mcp` / `poe_research_mcp` / `poe_learning_mcp`）。Codex 修改
`~/.codex/config.toml` 中带托管标记的块；其他三个宿主只合并各自 JSON 中的命名条目。
已有本地 checkout 和 skills、只缺 MCP 工具时，可使用 `-RegisterMcpOnly` / `--register-mcp-only`；
该模式不会 pull、clone 或重新链接 skill。注册后需要重启宿主或新建任务以重新发现工具。完整
客户端路径、配置形状和故障排查见 [多 Agent 安装指南](docs/MULTI_AGENT_INSTALL.md)。

### DeepSeek Harness

DSH 原生内置 MCP client 桥，适配方式与 OpenCode 同构（注册四个域 MCP server）：
"快速体验"先执行第一层 patch 注册工具，再安装 `poe-bd` 会话 preset 获得人设、四个
skill 与 MCP 工具集：

```powershell
dsh web --patch dsh\poe-bd.mcp.cordis.yml          # 第一层：注册 mcp__poe_*__* 工具
python scripts\install_dsh_preset.py install        # 第二层：安装 poe-bd preset
python scripts\install_dsh_preset.py doctor         # 诊断
```

安装后新建 DSH 会话并在预设列表选择 **poe-bd**。换机器时设置
`POE_BD_CREATOR_ROOT` 或在组合文件里替换路径字面量。四个 skill 由
`scripts/adapt_skills_for_dsh.py` 从插件源生成（工具名带 `mcp__poe_<server>__`
前缀）。当前交付已完成静态配置、生成/安装回滚测试和 YAML 解析；真实 DSH 会话启动仍待
装有 DSH 的环境验收。完整说明见 [dsh/README.md](dsh/README.md)。

## 快速使用

安装并重启宿主后，可以直接对 Agent 说：

```text
使用 poe-bd-create skill，给我设计一个适合新手的 PoE2 BD。
使用 poe-bd-research skill，分析 5 个成熟 BD 样本。
```

“预检”（`--dry-run`）只验证采集链路、不产生知识，仅在明确只想确认链路时使用；想真正分析 N
个案例时直接说“用 poe-bd-research 分析 N 个成熟 BD”，会按 `--limit N` 真实入队并逐案研究。

支持斜杠命令的宿主也可以使用 `/poe-bd-create` 和 `/poe-bd-research`。不同宿主的 Skill 发现方式
可能不同，不以命令面板是否显示斜杠命令作为唯一安装验收标准。

## 安全边界

- 不把第三方 PoB code、raw XML、完整角色镜像、账号/角色信息或长篇攻略原文写入 Git、聊天或长期记忆。
- 只有通过来源、resolver、typed schema 和 copy-safety 检查的净化知识才能进入公开种子或持久记忆。
- 没有 static source 不能创建 physical node。
- 没有已解析 graph node 不能写 semantic edge。
- 单个样本只能形成 `case_observation`，不能宣称“通常”“常见”。
- 项目不内置 autonomous LLM/provider loop；研究、设计、比较与修正始终由外部 Agent 主导。

## 文档

- [多 Agent 安装与验证](docs/MULTI_AGENT_INSTALL.md)
- [DeepSeek Harness 适配](dsh/README.md)
- [项目总纲](docs/PROJECT_SPEC.md)
- [架构说明（中文）](docs/ARCHITECTURE.CN.md) / [Architecture](docs/ARCHITECTURE.md)
- [核心数据合同](docs/SCHEMAS.md)
- [阶段计划与验收](docs/phases/)
- [Create Skill 合同](poe-bd-creator-plugin/skills/poe-bd-create/SKILL.md)
- [Research Skill 合同](poe-bd-creator-plugin/skills/poe-bd-research/SKILL.md)
- [Agent 开发指南](AGENTS.md)
- [LLM runtime 指南（英文）](server/ASSISTANT_GUIDE.md)

## 平台能力

| 平台 | 安装器 | 可用 skill | MCP 自动配置 | 当前结论 |
| --- | --- | --- | --- | --- |
| Codex | 支持 | 四个 | 支持 | 完整支持 |
| Claude Code | 支持 | Research、Create | 支持 | 可测试 |
| Cursor | 支持 | Research、Create | 支持 | 可测试 |
| OpenCode | 支持 | Research、Create | 支持 | 当前优先测试目标 |
| DeepSeek Harness | 静态适配（patch + preset） | 四个（改写版） | 静态配置完成 | 待 DSH 实机验收 |
| VS Code Copilot / Gemini / OpenClaw / Hermes | 仅 skill 链接 | Research、Create | 不支持 | 需手工接 MCP，暂不宣称完整可用 |
| Pi | 未接入 | 未接入 | Pi 需要扩展层 | 暂不支持 |

多平台共享同一套 skill、MCP server、用户数据目录和安全合同；宿主适配层只负责 skill 发现与 MCP
配置。两个 Desktop loop 仍保持 Codex 专属，不通过复制 prompt 的方式伪装成跨平台能力。
