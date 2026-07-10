# PoE2 BD Creator 项目规格

最后更新：2026-07-10

本文档是项目的中文唯一总纲，用来维护产品方向、不可协商边界、验证哲学，以及各
Phase 的关系和完成状态。每个 Phase 的详细执行清单、验收项和阶段内进度放在
`docs/phases/`。

## 产品愿景

PoE2 BD Creator 的最终目标不是“研究 BD 的流程”本身，而是成为一个能够自主研究、自
我进化，并产出极高质量、且合乎游戏物理规则的 PoE2 BD 创造平台。

长期愿景是：系统能够在可验证约束下探索技能、天赋、装备、Spirit、经济环境和场景目
标之间的组合空间，发现人类玩家不容易系统搜索到的机制联动，并为不同场景提供高质量
的配装、技能、天赋和升级路线方案。

研究成熟 BD、提取知识、建立图记忆和运行 Critic loop 都是实现这个愿景的手段，不是
产品终点。

## 工程目标与验证哲学

为了实现上述愿景，并最大限度压制外部 Agent（Codex、Claude Code 或其他成熟 agent）
的幻觉，本项目采用 Verification-first 的工程基座架构：外部 agent 负责研究、推理、
反思、BD 合成和批判；仓库本身提供可重复执行的工具、图知识、长期记忆、安全边界和评估
合同。程序不能把 Agent 的构筑思路接管成“自动补完整 BD”的流程。

开发阶段不追求“看起来合理”的文本建议，而是通过循环学习过程，在固定 benchmark 上可
量化地逼近高质量 BD 的标准：

- 更高的合法 BD 比率；
- 更高的 PoB 可计算率；
- 在 PoB 可建模范围内更好的 DPS/EHP/reference placement；
- 更少 critical gaps；
- 更好的 Spirit、抗性、属性和天赋点预算合法性；
- 更安全的 non-copyable 知识提取；
- repair loop 更快收敛。

在这个验证哲学下，Judge 的职责不是“为所有 PoE2 机制强行算出一个看似精确的真 DPS /
真 EHP”，而是先建立物理边界与证据边界：

- 对已被 Headless PoB 稳定表达、且有明确 provenance 的数值，Judge 可以给出可比较分数；
- 对 `FullDPS` rollup、召唤/指令复合输出、多段触发链、高规避/条件 sustain 等 PoB 原生表
  达盲区，Judge 必须优先输出 caveat、confidence 和 reward-strength，而不是伪造高置信度
  真值；
- “知道哪些不能装作算准”与“知道哪些可以进入强 reward”本身就是 Phase 1 的核心交付，而
  不是失败。

## 系统闭环

```text
成熟 BD 数据 / PoB 导出 / pobb.in / poe.ninja
  -> quarantine-only raw intake
  -> 外部 Researcher Agent
  -> clean fragments + physical/semantic graph + long-term memory
  -> 外部 Architect Agent 按需查询图、记忆、语料和 PoB/计算工具
  -> Agent 主导候选 BD 创造和可评估临时状态搭建
  -> Headless PoB Judge + 安全报告
  -> reference comparison + 外部 Critic Agent
  -> rollback / repair / early stopping
  -> reward events 调整 graph 和 memory 权重
```

长期记忆采用双轨结构，而不是纯文本记忆：

- symbolic / relational graph memory（符号/关系图记忆）：保存 source-backed physical facts、
  通过校验的 semantic edges、官方 ID、天赋拓扑、requirements、support/socket legality、
  装备词缀模板和其他可验证 JSON facts；
- semantic vector memory（语义向量记忆）：保存通过 copy-safety 和版本校验的 clean fragments、
  机制理解、研究摘要和可复用原则，用于语义检索与 Researcher / Architect 上下文组装。

Phase 2/3 先建立符号图与 typed access；Phase 4 再把成熟 BD 研究产物写入 semantic graph
和 vector memory；Phase 8 才根据 reward events 调整 graph / memory ranking。

## 已有底座

当前仓库已经有可复用底座：

- 通过 `server/compute/engine.py` 和 `pob/pob_headless.lua` 集成 Headless
  PathOfBuilding-PoE2。
- PoB import/export、build stats、defenses、passive search/allocation、item/support/build
  optimization helpers。
- skills、supports、items、uniques、mods、passives、ascendancies 和 mechanics 的 PoE2
  corpus 查询。
- patch/tree/PoB/poe.ninja context 的 freshness providers。
- 从 poe.ninja 和 pobb.in 到 quarantine-only payload 的 mature-source intake。
- Copy-safety、mature sample contracts、fragment extraction contracts 和 evaluator
  boundaries。
- Lifecycle/evaluation helpers 和小型 mature-learning store。

已有底座不等于产品能力已经验证；能力必须通过 benchmark 证明。

其中，Phase 1 当前已经形成可运行的内部 Judge 基线：

- `server/judge/*` 提供 legality、score vector、modelability、comparison 和 sample-audit；
- `scripts/run_judge_user_samples.py` 与 `scripts/run_judge_ninja_samples.py` 提供真实样本验收；
- `docs/JUDGE_SCORING_SYSTEM.md` 维护当前评分策略、证据分层、兼容逻辑和查询路径说明。

这不表示“所有 PoE2 机制都已被数值精确建模”，而是表示：Judge 已经能稳定区分
strong evidence、limited evidence、source-data problem 与 unsolved modelability gap，
并阻止有限证据污染强 reward。

## Phase 关系

Phase 不是平行愿望清单，而是一条验证优先的依赖链：

```text
Phase 0 文档与边界
  -> Phase 1 Judge / modelability 基线
  -> Phase 2 物理图冷启动
  -> Phase 3 Typed graph tools
  -> Phase 4 Researcher 语义记忆
  -> Phase 5 Agent 主导的生成原型
  -> Phase 6 官方 .build 导出
  -> Phase 7 Critic loop / rollback / early stopping
  -> Phase 8 RLAIF-lite reward memory
  -> Phase 9 scale / revalidation / productization
```

其中 Phase 1 是所有“好坏判断”的前置门槛；Phase 2 和 Phase 3 是图记忆可用性的前置
门槛；Phase 4 负责把成熟 BD 研究变成可复用长期知识；Phase 5 之后才开始验证生成能
力；Phase 7 和 Phase 8 只有在生成与 judge 可用后才有意义。

### 待优化提示：复合输出与多场景评估

PoE2 BD 通常不是单一技能、单一面板和单一战斗场景。清图、Boss、触发、伤害兑现、条件性
附加效果和防御维持可能由多个技能共同完成。当前 Judge 仍是可运行基线，不应把一次选中的
最高伤害组件解释成整个 BD 的唯一主技能或完整强度。

该问题按以下阶段持续收敛：

- Phase 1 / Judge 持续维护：区分 PoB 当前计算组、多个伤害组件、条件性附加效果和技能组
  合法性；逐步补充清图、单体、持续输出、触发/兑现和组合同时生效关系的证据合同。无法可靠
  建模时输出 caveat / confidence，不伪造组合 DPS。
- Phase 5 P5.1-P5.3：已用 Agent 实际生成的候选发现并修复条件性内部效果误选、插槽误判和
  逐轮可信核对问题；Agent 说明各技能职责，可信报告保存足够诊断。完整轮转和组合建模继续作为
  后续跨阶段优化，不在 Phase 5 手写全知评分器。
- Phase 7：消费已经可信的分场景 Judge 诊断做 Critic、修复、回滚和提前停止；不负责发明缺失
  的底层数值真值。
- Phase 8：只有场景证据和 confidence 足够时才允许写 reward memory；多技能组合或时序关系未
  解决时必须限制或禁止强奖励。

这是一项跨阶段待优化能力，不因 Phase 1 基线状态为“已完成”而视为已经解决。后续优先由
Phase 5 真实失败样例驱动，不提前手写一套脱离 PoB 和游戏机制的全知评分器。

## Phase 状态

Spec 只维护 Phase 状态和概括目标；更细的执行进度维护在对应 `docs/phases/*.md`。

| Phase | 状态 | 依赖关系 | 概括工作 | 细节文档 |
| --- | --- | --- | --- | --- |
| Phase 0 | 已完成 | 无 | 清理旧方向文档，建立中文 spec、phase docs、schema docs，以及双语 architecture。 | `docs/phases/00_cleanup.md` |
| Phase 1 | 已完成：Judge / modelability 基线、真实样本回归与评分合同收口完成 | Phase 0 | 证明 Headless PoB 与确定性规则能判断 BD 合法性、质量和 modelability。 | `docs/phases/01_judge_eval.md` |
| Phase 2 | 已完成：cold-start 合同、固定 E2E 样例验收、人工评分通过，并已合入 `main` | Phase 1 | 从静态权威数据冷启动 physical graph，并建立官方 `.build` 需要的 ID 映射基础。 | `docs/phases/02_graph_cold.md` |
| Phase 3 | 已完成：read-only typed graph facade、NetworkX bounded topology、MCP `graph_tool_query`、deterministic benchmark 与人工验收通过 | Phase 2 | 通过 typed tools 暴露 source-backed graph 查询，禁止 agent 写原生图查询语句。 | `docs/phases/03_graph_tools.md` |
| Phase 4 | 已完成：Researcher 语义记忆、Phase 4.5 source/pattern 补课和真实逐案例 Researcher 批量提取入口 `/poe-bd-research` 已收口 | Phase 1、2、3 | 让外部 Researcher Agent 抽取 non-copyable 语义知识，写入 semantic graph / memory / build patterns，并为 Phase 5 提供 copy-safe、resolver-backed、advisory 组合模式上下文。 | `docs/phases/04_research_memory.md` |
| Phase 5 | 已完成：Agent 主导生成、活动 PoB 搭建、可信 Judge、有限内部重试、无记忆对照和真实会话人工验收均已收口 | Phase 1、3、4 | 外部 Architect Agent 主导用户意图理解、按需查询、候选 BD 设计、活动 PoB 搭建和失败解释；仓库捕获不可变快照、运行 Judge，并提供安全且与本次运行绑定的人工验收材料。 | `docs/phases/05_generation.md` |
| Phase 6 | 未开始 | Phase 2、5 | 把 Phase 5 已由 Agent 设计并可验证或部分可验证的候选状态转换为官方 `.build` JSON；只处理导出格式、官方 ID 和导出校验，不负责重新设计生命周期或补完整 BD。 | `docs/phases/06_build_export.md` |
| Phase 7 | 未开始 | Phase 1、5，按需依赖 Phase 6 | 建立生成-评估-修复闭环，支持 snapshot、rollback、early stopping 和 failure pattern。 | `docs/phases/07_critic_loop.md` |
| Phase 8 | 未开始 | Phase 4、5、7 | 用 judge 和 Critic 结果更新 graph/memory 权重，实现 RLAIF-lite，而不是训练 LLM。 | `docs/phases/08_reward_memory.md` |
| Phase 9 | 未开始 | Phase 1-8 达到进入条件 | 在核心闭环被 benchmark 证明后，再做规模化、自动重验证、前端和完整产品叙事。 | `docs/phases/09_scale_productization.md` |

## 硬边界

- 不要实现新的数值 BD 引擎。数值声明必须来自 Headless PathOfBuilding-PoE2，或明确标
  记为 unverified/unmodelled。
- 不要为了降低 gap 数量而发明第二套主观数值真值。对证据不足的 offense / defense /
  recovery / mobility，只能降低 confidence、限制 reward、或转交后续语义阶段处理。
- 项目不拥有内部 autonomous LLM provider loop。Agent 工作通过 explicit packets 和
  schemas 交给 Codex、Claude Code 或其他外部成熟 agent。
- Agent 给出的方案不能交给程序做全自动 BD 补全；整个 BD 创造、取舍、查询和失败修正仍由
  Agent 主导，程序只提供工具、边界、评估和报告。
- 真实成熟 BD 是研究/校准来源，不是复制模板。
- Raw mature-build material 只允许 quarantine-only transient 使用。
- 不要持久化或暴露 PoB code、raw XML、完整装备表、完整 passive path、完整
  gem/support links、raw account/character details 或长篇复制攻略文本。
- Creator/evaluator/holdout 边界必须强制执行。
- 每个 durable memory item 都必须带 source、evidence、patch/tree/PoB version、status、
  confidence 和 copy-safety state。
- Agent 访问图必须使用 typed tools，不能使用 raw graph-query text。
- 官方 `.build` export 必须有可解析 GGG ID，并明确 unsupported-field caveats。
- 禁止游戏内交互、overlay、内存读取、自动化或 live-screen parsing。
- 非常重要的一点！每个阶段的功能开发必须经过E2E测试，且由人类评分通过后才算真正的通过，每个phase的最终产物都必须经过这个过程

## 验证哲学

每个阶段都必须先定义如何衡量效果，再声称能力完成。任何功能的核心问题是：它是否
让 benchmarked build generation 或 evaluation 变得更好？

核心 benchmark 维度：

- legal build rate；
- PoB import 和 compute success；
- modelability caveat correctness；
- DPS/EHP/reference placement；
- 抗性、Spirit、属性、support 和 passive-budget validity；
- typed graph tool 的确定性、provenance 完整度、上下文校验和防幻觉能力；
- Phase 4 之后 graph / vector / text retrieval 组合相对纯文本检索的质量；
- copy-safety pass rate；
- repair-loop score improvement；
- rollback 和 early-stopping behavior；
- reward-memory A/B uplift。

Judge 的评分语义也必须接受分层验证，而不是只看单一 aggregate：

- legality / validity：是否满足确定性硬约束；
- raw score vector：PoB 当前可表达的 offense / defense / recovery / mobility；
- evidence / confidence：这些 raw scores 是否来自 strong evidence、limited evidence、
  还是 unmodelled / unsupported 机制；
- reward eligibility：这些分数能否进入后续 comparison、Critic 和 reward memory。

当 raw score 和 evidence / confidence 冲突时，以证据边界为先：宁可保守地把样本归到
`judge_unsolved_modelability_gap`，也不能把有限证据写成强 reward 事实。

Phase 5 对 freshness 使用降级策略：如果当前游戏补丁、赛季和天赋树可确认，仅本地 PoB 引擎或
数据落后，可以继续生成候选并运行过期 PoB 的有限证据诊断，但必须禁止“当前赛季已验证”声明。
只有当前游戏规则、天赋树或所需核心机制资料冲突/未知时，才停止当前版本强验证或请求用户决定。
通用 freshness 的 `blocked_stale` 不能被机械解释为“停止所有 BD 生成”。

PoB 数据版本兼容性按赛季大版本比较，精确补丁号只用于来源追踪和注意事项。同一赛季内上游 PoB
发布小版本只产生更新提醒，不自动撤销已经认证的本地运行时；跨赛季大版本或天赋树世代冲突仍
必须阻断强验证。

验证耗时也是规格的一部分：

- `quick` / `noncompute` 是日常开发和非引擎回归入口，应避免运行完整 PoB compute golden
  suite。
- `compute` / `full` 是重型 Headless PoB 认证入口，在 Windows 本地经常运行 15 分钟以上；
  执行这些 profile 时，外层命令超时必须至少给到 30 分钟（`1800000ms`）。
- `scripts/verify.ps1 compute` / `full` 会把 pytest 单测试超时提升到 30 分钟。10 分钟以内的
  调用工具超时只能说明外层预算不足，不能直接判定 compute suite 失败。

## 文档模型

- `PROJECT_SPEC.md`：中文唯一项目总纲，维护方向、边界、Phase 关系和 Phase 状态。
- `ARCHITECTURE.md` / `ARCHITECTURE.CN.md`：仅此架构文档维护英文和中文两版。
- `SCHEMAS.md`：中文唯一核心数据结构合同。
- `JUDGE_SCORING_SYSTEM.md`：Judge 当前评分合同、证据分层、兼容逻辑和查询路径说明。
- `phases/*.md`：中文唯一阶段执行计划、验收标准和阶段内进度。

保持 `PROJECT_SPEC.md` 和 `ARCHITECTURE*.md` 紧凑，不要把它们写成详细阶段 task list。

## Public README 政策

根 `README.md` 现在允许存在，但定位很窄：它是安装/自动化 README，只写安装、skill
自动化入口、成熟 BD 研究命令、平台能力矩阵和安全边界。它不能把 Phase 5 之后的生成、
导出、Critic loop 或 reward memory 写成已完成产品。完整 public product narrative 仍等
learning/generation/evaluation loop 有 benchmark 证据后再扩展。

## 接续指南

上下文丢失后按顺序阅读：

1. `AGENTS.md`
2. `docs/PROJECT_SPEC.md`
3. `docs/ARCHITECTURE.md` 或 `docs/ARCHITECTURE.CN.md`
4. `docs/SCHEMAS.md`
5. 相关 `docs/phases/*.md`
6. `server/ASSISTANT_GUIDE.md`
7. `scripts/verify.ps1`
