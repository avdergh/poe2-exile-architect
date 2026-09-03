# PoE2 BD Creator 架构

[English](ARCHITECTURE.md) | [中文](ARCHITECTURE.CN.md)

Last updated: 2026-07-27

本文档说明高层模块布局和数据流。详细实现工作放在 `docs/phases/`。Architecture 是当前
唯一维护英文和中文两版的文档；project spec、schemas 和 phase plans 只维护中文。

## 高层形态

```text
External Agents
  Researcher / Architect / Reference-Comparator
        |
        v
server/main.py  (MCP tools, prompts, instructions)
        |
        v
domain routers / workflow services  (thin orchestration, no hidden LLM loop)
        |
        +-- compute: Headless PoB, build mutation, item/support/passive tools
        +-- knowledge: corpus, mature learning, copy-safety, lifecycle, schemas
        +-- graph/memory: physical facts, semantic edges, Research DB, local Learning Memory
        +-- judge: build evaluation、modelability 与 advisory-only 数值附件
        +-- comparative learning: quarantine case、blind packet、comparison、campaign state
        +-- agent helper tools: 查询、PoB 操作、候选状态整理、`.build` export
        +-- freshness/live: patch/tree/PoB/poe.ninja/wiki/price context
        |
        v
data/* / user-data / pob/*
```

Server 暴露 typed tools 和 contracts。外部 agent 负责创造性推理。仓库不运行自己的隐藏 LLM
loop。`server/main.py` 应保持 thin MCP entrypoint：负责 tool 注册、参数适配和 response
shaping。跨领域 workflow 应放进 router/service modules，避免 entrypoint 同时拥有 compute、
graph、judge 和跨层工作流逻辑。持久 event bus 是后续规模化选项，不是 Phase 0 的架构要求。

## 数据流

```text
source probe
  -> quarantine payload
  -> ResearchPacket
  -> Researcher Agent
  -> CleanFragment + semantic edge proposals
  -> validators + copy-safety + graph resolution
  -> long-term memory / semantic graph

用户需求 / BuildBrief 摘要
  -> Architect Agent 按需查询 graph / memory / corpus / PoB tools
  -> Agent 主导候选 BD 设计
  -> Agent 使用工具搭建可评估临时构筑状态
  -> BuildSnapshot / 本地临时状态引用
  -> Headless PoB Judge
  -> BuildEvaluation / 最终本地 artifact

成熟原 BD
  -> case-bound quarantine
  -> Reference/Comparator Agent 安全 Profile
  -> FamilyTarget + reference evidence
  -> 独立 Create Agent 只接收 FamilyTarget + 等级
  -> generated evidence + Judge advisoryOnly
  -> Reference/Comparator Agent 逐维比较
  -> Research 回流 / Learning Memory lesson + correction
  -> 下一案例 Create 召回

终局 BD 请求
  -> Research 按职业/精确 patch/tree 发现最多 10 个成熟 Family
  -> Agent 比较并排序实际返回的全部 2–10 个 Family，保留第一名与备用
  -> 普通单阶段 Create 从空状态生成选中的目标 BD
  -> Judge 前共享硬合法性审计；保护每个 passing baseline
  -> FamilyTarget + 身份 stable key 集合 + immutable artifact/hash
  -> artifact-bound lifecycle 回执
  -> 交付包（PoB XML / 导入码 / `.build` / 公开 poe.ninja PoB 链接）
```

## 核心 Runtime 模块

| 区域 | 当前文件 | 职责 |
| --- | --- | --- |
| MCP entry | `server/main.py` | 聚合 server（测试/旧宿主配置兼容），工具实现的单一事实源。 |
| Split MCP entries | `server/mcp/{knowledge,build,research,learning}_server.py` | 四个按域拆分 server，re-register 聚合工具的子集，任务只发现本域工具。 |
| Domain routing | planned router/service modules | MCP entrypoint 之外的跨层 workflow orchestration。 |
| Agent instructions | `server/MCP_{KNOWLEDGE,BUILD,RESEARCH,LEARNING}_BOOTSTRAP.md`（拆分 server）、`server/MCP_BOOTSTRAP.md`（legacy）、`server/ASSISTANT_GUIDE.md`、`AGENTS.md`、`CLAUDE.md` | 各 server 数百字硬边界启动规则和完整的人类/agent 操作指南。 |
| Compute | `server/compute/*`, `pob/pob_headless.lua` | Headless PoB calls、import/export、build mutation、数值 evaluation helpers。 |
| Knowledge | `server/knowledge/db.py`, `mechanics.py`, `refbuilds.py` | Static corpus 查询和 mechanics context。 |
| Mature intake | `server/knowledge/mature_*`, `server/live/mature_*` | Quarantine-only mature sample intake 和 clean fragment contracts。 |
| Copy-safety | `server/knowledge/copy_safety.py` | 防止 reconstructable build material 的 guardrails。 |
| Lifecycle/eval | `server/knowledge/lifecycle*` | 现有 route、verification、quality 和 evaluation helpers。 |
| Comparative learning | `server/learning/*` | Phase 7 typed contracts、隔离案例、盲测 packet、比较报告、Learning Memory 和可恢复 campaign 状态。 |
| Create provenance | `server/generation/progression_provenance.py` | 普通 Create 的 Research receipt/premise 审计与 run 内时效校验。 |
| Hard legality / artifact selection | `server/judge/hard_legality.py`, `server/generation/artifacts.py` | 在 checkpoint、Judge、装备候选和 artifact 保存之间复用无评分合法性审计；确定性错误不消耗 Judge attempt，并允许在质量探索回归后恢复当前进程内仍可信的 passing baseline。 |
| Judge feedback projection | `server/generation/evaluation.py`, `preflight.py`, `validation_checkpoint.py`, `retry.py`, `prototype.py` | 内部 Judge 照常运行，但 Create 默认 `strict_mode=false`，只有硬门槛和确定性诊断跨过可信边界；用户显式 `strict_mode=true` 才恢复完整主观评分，并锁定同一 run 的模式。 |
| Context telemetry | `server/runtime/tool_telemetry.py` | 只记录工具名、耗时、响应字节和安全关联 ID，用于定位上下文放大。 |
| Freshness/live | `server/freshness/*`, `server/live/*` | Patch/tree/PoB/poe.ninja/wiki/price context。 |
| Scripts | `scripts/*` | Verification、smoke tests、packaging、source probes。 |
| Release packaging | `scripts/build_codex_plugin.py`, `build_research_release_seed.py`, `package_physical_graph_seed.py` | 生成自包含插件；净化 Research 与可移植物理图只作首装种子，绝不覆盖已有用户库。 |

计划中的模块应遵循相同分层：

- graph 和 memory 代码先放 knowledge layer，必要时再拆独立 package；
- judge 必须 deterministic 且 compute-backed；
- Agent helper tools 只提供局部、可审查、可重复的查询或操作能力，不能接管成“Agent 出
  plan，程序自动补完整 BD”的流程；
- workflow orchestration 应在 `server/main.py` 变成 coordination bottleneck 前移入 router/service
  modules；
- 对照循环只把 `FamilyTarget + 等级` 发给 Create；reference 细节只能留在隔离的 Comparator 上下文；
- MCP tools 只包装已经在 lower layer 测试过的函数。

## 权威边界

- PoB/compute 对数值声明负责。
- Static data 对 physical graph facts 负责。
- 外部 agent 负责推理和提出 semantic links，但不负责 validation。
- 外部 Architect Agent 负责 BD 创造、查询取舍、临时状态搭建策略和失败修正方向。
- Validators 负责 schema、copy-safety、graph-resolution 和 split-boundary enforcement。
- Comparator Agent 对逐维 tradeoff 和总结果负责；Judge 数值只作为 `advisoryOnly` 附件。
- Phase 7 状态服务负责 CAS、幂等、暂停、恢复和安全 checkpoint，不创建任务或调用模型。
- Research schema 对具体 build knowledge 负责；Learning Memory 只接收跨维 Create 行为经验及其 correction。
- Git 与插件只携带 provenance 已证明、creator-safe 的 `global_seed` Research 与 Learning Memory 发布种子；
  首次运行复制到用户数据目录，运行态继续分库追加且不回写捆绑种子。
- 普通 Create 保持单阶段语义：先从 Research receipt 获取当前精确版本最多 10 个成熟
  Family，并比较实际返回的全部 2–10 个候选；用户锁定唯一 Family 时跳过该步骤。候选阶段不跑
  完整 Judge/全局优化器。Judge 只作 advisory，Family 与实际采用
  知识限定在一条 `(knowledgeScope, sourceCaseRef)` lane，并由完整 bounded retrieval-session
  receipt 链校验。
- 社区攻略是候选证据，不能直接进入 Research/Learning Memory；
  技能与机制前提仍由当前 graph/corpus/mechanic 复核。
- Phase benchmark reports 对进度声明负责。

## 文档地图

| 路径 | 作用 |
| --- | --- |
| `docs/PROJECT_SPEC.md` | 中文唯一项目总纲、硬边界、Phase 关系和 Phase 状态。 |
| `docs/ARCHITECTURE.md` / `docs/ARCHITECTURE.CN.md` | 双语高层架构与数据流地图。 |
| `docs/SCHEMAS.md` | 中文唯一核心 artifact contracts。 |
| `docs/phases/*.md` | 中文唯一详细阶段工作、依赖、进度和验收标准。 |

## Runtime 状态

- 每个 MCP session 拥有隔离的 Active build state；默认全进程最多运行 5 个 Headless PoB 实例，
  同一 session 的完整工具调用串行执行，避免多步 optimizer 状态互相穿插。
- Durable generated reports 不存入仓库。
- Mature raw payloads 只允许 quarantine-only transient 使用。
- Phase 7 原始来源按 case 隔离保存；控制状态、报告和 Learning Memory 只能持久化 hash/ref 与安全摘要。
- MCP 遥测只保存大小与耗时，不保存参数或响应正文。
- Long-term knowledge 必须 clean、versioned、evidence-backed 且 copy-safe。
- User-data/runtime 目录可以保存本地状态；仓库文档应描述 contracts，而不是偶然的本地 artifacts。
