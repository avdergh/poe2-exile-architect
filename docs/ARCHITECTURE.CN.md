# PoE2 BD Creator 架构

[English](ARCHITECTURE.md) | [中文](ARCHITECTURE.CN.md)

Last updated: 2026-06-29

本文档说明高层模块布局和数据流。详细实现工作放在 `docs/phases/`。Architecture 是当前
唯一维护英文和中文两版的文档；project spec、schemas 和 phase plans 只维护中文。

## 高层形态

```text
External Agents
  Researcher / Architect / Critic
        |
        v
server/main.py  (MCP tools, prompts, instructions)
        |
        v
domain routers / workflow services  (thin orchestration, no hidden LLM loop)
        |
        +-- compute: Headless PoB, build mutation, item/support/passive tools
        +-- knowledge: corpus, mature learning, copy-safety, lifecycle, schemas
        +-- graph/memory: physical facts, semantic edges, reward-weighted memory
        +-- judge: build evaluation, comparison, modelability, benchmark reporting
        +-- planners: passive path, gear constraints, support selection, `.build` export
        +-- freshness/live: patch/tree/PoB/poe.ninja/wiki/price context
        |
        v
data/* / user-data / pob/*
```

Server 暴露 typed tools 和 contracts。外部 agent 负责创造性推理。仓库不运行自己的隐藏 LLM
loop。`server/main.py` 应保持 thin MCP entrypoint：负责 tool 注册、参数适配和 response
shaping。跨领域 workflow 应放进 router/service modules，避免 entrypoint 同时拥有 compute、
graph、judge 和 planner 逻辑。持久 event bus 是后续规模化选项，不是 Phase 0 的架构要求。

## 数据流

```text
source probe
  -> quarantine payload
  -> ResearchPacket
  -> Researcher Agent
  -> CleanFragment + semantic edge proposals
  -> validators + copy-safety + graph resolution
  -> long-term memory / semantic graph

BuildBrief
  -> graph + memory retrieval
  -> Architect Agent BuildPlan
  -> deterministic completion
  -> BuildSnapshot
  -> Headless PoB Judge
  -> BuildEvaluation / BuildComparison
  -> Critic Agent gaps
  -> rollback / repair / early stop
  -> StatePruner / ContextPack
  -> compact agent retry context
  -> RewardEvent
  -> graph/memory weight updates
```

## 核心 Runtime 模块

| 区域 | 当前文件 | 职责 |
| --- | --- | --- |
| MCP entry | `server/main.py` | Thin public tool 注册、参数适配和 response shaping。 |
| Domain routing | planned router/service modules | MCP entrypoint 之外的跨层 workflow orchestration。 |
| Agent instructions | `server/ASSISTANT_GUIDE.md`, `AGENTS.md`, `CLAUDE.md` | 面向人和 agent 的操作指南。 |
| Compute | `server/compute/*`, `pob/pob_headless.lua` | Headless PoB calls、import/export、build mutation、数值 evaluation helpers。 |
| Knowledge | `server/knowledge/db.py`, `mechanics.py`, `refbuilds.py` | Static corpus 查询和 mechanics context。 |
| Mature intake | `server/knowledge/mature_*`, `server/live/mature_*` | Quarantine-only mature sample intake 和 clean fragment contracts。 |
| Copy-safety | `server/knowledge/copy_safety.py` | 防止 reconstructable build material 的 guardrails。 |
| Lifecycle/eval | `server/knowledge/lifecycle*` | 现有 route、verification、quality 和 evaluation helpers。 |
| Freshness/live | `server/freshness/*`, `server/live/*` | Patch/tree/PoB/poe.ninja/wiki/price context。 |
| Scripts | `scripts/*` | Verification、smoke tests、packaging、source probes。 |

计划中的模块应遵循相同分层：

- graph 和 memory 代码先放 knowledge layer，必要时再拆独立 package；
- judge 必须 deterministic 且 compute-backed；
- planners 产出结构化 artifacts，供 judge 验证；
- workflow orchestration 应在 `server/main.py` 变成 coordination bottleneck 前移入 router/service
  modules；
- repair loops 应向 agent 传递压缩后的 `ContextPack`，完整 snapshots 和 round logs 保存在本地状态；
- MCP tools 只包装已经在 lower layer 测试过的函数。

## 权威边界

- PoB/compute 对数值声明负责。
- Static data 对 physical graph facts 负责。
- 外部 agent 负责推理和提出 semantic links，但不负责 validation。
- Validators 负责 schema、copy-safety、graph-resolution 和 split-boundary enforcement。
- Judge outputs 对 reward signals 负责。
- State pruning 对 rollback/repair loop 的 agent-facing retry context 负责；完整本地历史不会自动重发给外部 agent。
- Phase benchmark reports 对进度声明负责。

## 文档地图

| 路径 | 作用 |
| --- | --- |
| `docs/PROJECT_SPEC.md` | 中文唯一项目总纲、硬边界、Phase 关系和 Phase 状态。 |
| `docs/ARCHITECTURE.md` / `docs/ARCHITECTURE.CN.md` | 双语高层架构与数据流地图。 |
| `docs/SCHEMAS.md` | 中文唯一核心 artifact contracts。 |
| `docs/phases/*.md` | 中文唯一详细阶段工作、依赖、进度和验收标准。 |

## Runtime 状态

- Active build state 存在共享 Headless PoB session 中。
- Durable generated reports 不存入仓库。
- Mature raw payloads 只允许 quarantine-only transient 使用。
- Long-term knowledge 必须 clean、versioned、evidence-backed 且 copy-safe。
- User-data/runtime 目录可以保存本地状态；仓库文档应描述 contracts，而不是偶然的本地 artifacts。
