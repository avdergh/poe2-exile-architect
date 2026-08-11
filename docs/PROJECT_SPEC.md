# PoE2 BD Creator 项目规格

最后更新：2026-07-26

本文档是项目的中文唯一总纲，用来维护产品方向、不可协商边界、验证哲学，以及各
Phase 的关系和完成状态。每个 Phase 的详细执行清单、验收项和阶段内进度放在
`docs/phases/`。

## 产品愿景

PoE2 BD Creator 的最终目标不是“研究 BD 的流程”本身，而是成为一个能够自主研究、自
我进化，并产出极高质量、且合乎游戏物理规则的 PoE2 BD 创造平台。

长期愿景是：系统能够在可验证约束下探索技能、天赋、装备、Spirit、经济环境和场景目
标之间的组合空间，发现人类玩家不容易系统搜索到的机制联动，并为不同场景提供高质量
的配装、技能、天赋和升级路线方案。

研究成熟 BD、提取知识、建立图记忆和运行对照学习循环都是实现这个愿景的手段，不是
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
- 相同 Family、相同等级盲测 Create 相对成熟原 BD 的差距持续收窄。

在这个验证哲学下，Judge 的职责不是“为所有 PoE2 机制强行算出一个看似精确的真 DPS /
真 EHP”，而是先建立物理边界与证据边界：

- 对已被 Headless PoB 稳定表达、且有明确 provenance 的数值，Judge 可以给出可比较分数；
- 对 `FullDPS` rollup、召唤/指令复合输出、多段触发链、高规避/条件 sustain 等 PoB 原生表
  达盲区，Judge 必须优先输出 caveat、confidence 和 reward-strength，而不是伪造高置信度
  真值；
- “知道哪些不能装作算准”与“知道哪些可以进入强 reward”本身就是 Phase 1 的核心交付，而
  不是失败。

Create 当前默认不把这些主观评价交给生成 Agent：`strict_mode=false` 只投影硬失败、合法性、
快照绑定和安全事实诊断；完整评分仍在内部计算，但 aggregate、quality band、
playability/quality warning、reward 和主观 caveat 不进入 attempt、artifact、retry、Review。只有用户明确要求严格模式并手动使用 `strict_mode=true` 时才返回完整评价，而且
同一生成 run 不能中途切换。这个开关不减少 Research 深读、主动质量收尾或 PoB 原始数值验证。

## 系统闭环

```text
成熟 BD 数据 / PoB 导出 / pobb.in / poe.ninja
  -> quarantine-only raw intake
  -> 外部 Researcher Agent
  -> clean fragments + physical/semantic graph + long-term memory
  -> 外部 Architect Agent 按需查询图、记忆、语料和 PoB/计算工具
  -> Agent 主导候选 BD 创造和可评估临时状态搭建
  -> Headless PoB Judge + 安全报告
  -> 同 Family / 同等级的 reference profile 与盲测 Create
  -> 独立 Comparator 逐维比较（Judge 仅作参考）
  -> Research 回流 + 本地 Learning Memory
  -> 后续案例召回与趋势复审
```

长期记忆采用双轨结构，而不是纯文本记忆：

- symbolic / relational graph memory（符号/关系图记忆）：保存 source-backed physical facts、
  通过校验的 semantic edges、官方 ID、天赋拓扑、requirements、support/socket legality、
  装备词缀模板和其他可验证 JSON facts；
- semantic vector memory（语义向量记忆）：保存通过 copy-safety 和版本校验的 clean fragments、
  机制理解、研究摘要和可复用原则，用于语义检索与 Researcher / Architect 上下文组装。

Phase 2/3 先建立符号图与 typed access；Phase 4 再把成熟 BD 研究产物写入 semantic graph
和 vector memory；Phase 7 另外维护不适合进入 Research DB 的本地轻量 Learning Memory。
普通 Create 交付可信的单阶段终局 BD：以 Research Family 为身份与设计权威，artifact 保存后
绑定不可变快照。
相同 Family 的 Research 与组件搜索不设固定条数上限；working checkpoint 只阻止相同
query/receipt 在压缩后原样重放，不能截断新证据与候选。
精确 Family 查询用 coverage、未展开索引和稳定 premise catalog 显示知识全貌；Boss、资源、
轮转等失败条件必须被明确解决、采用替代方案、判定不适用或保留 caveat，解决记录必须实际深读。
lifecycle 调参使用 state-hash checkpoint，正式 attempt 边界才执行 compact gate。
`Phase 5 可信 artifact` 指通过正式 Judge 与共享硬合法性审计的最终候选，不代表把终局 BD
自动删点降配。

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
- 自包含 Codex 发布构建：MCP/Create 运行入口、只读 corpus、净化 Research release seed、净化
  Learning Memory seed、可移植 physical graph seed、PoB 子集和 Python 依赖一起进入插件包并以
  相同种子提交到 Git。首次启动只在用户库不存在时安装种子；升级不覆盖本地 Research、Learning
  Memory 或运行状态。

已有底座不等于产品能力已经验证；能力必须通过 benchmark 证明。

其中，Phase 1 当前已经形成可运行的内部 Judge 基线：

- `server/judge/*` 提供 legality、score vector、modelability、comparison 和 sample-audit；
- `scripts/run_judge_user_samples.py` 与 `scripts/run_judge_ninja_samples.py` 提供真实样本验收；
- `docs/JUDGE_SCORING_SYSTEM.md` 维护当前评分策略、证据分层、兼容逻辑和查询路径说明。

这不表示“所有 PoE2 机制都已被数值精确建模”，而是表示：Judge 已经能稳定区分
strong evidence、limited evidence、source-data problem 与 unsolved modelability gap，
并阻止有限证据污染强 reward。

## 上游依赖与长期解耦原则

当前仓库建立在 MIT 许可的 `MaxWilk/poe2-build-mcp` 基座之上，并已经对 Headless PoB bridge、
计算工具、语料库、MCP 注册、运行时安装和打包流程做了项目所需的修改。现阶段不拆分仓库，也不
新建独立 runtime 项目；当前可运行版本继续作为单仓维护。

后续开发必须控制新增耦合，为未来按需拆分保留清晰边界：

- Exile Architect 新增的 Judge、知识/记忆、生成、Critic、reward、artifact 和导出功能，应放在
  项目自身模块中，不继续把产品逻辑写入上游 compute、live 或 PoB bridge 内部；
- 业务层优先依赖稳定的 typed contract、adapter、service facade 或 MCP tool，不直接读取、修改
  或假设上游模块的私有对象、内部目录结构和未声明状态；
- 对 Headless PoB、PoB code codec、静态 corpus 和基础计算能力的调用，应逐步集中到少量明确的
  runtime 边界，避免 Judge、Knowledge、Generation 等模块分别跨层引用底层实现；
- 必须修改底层基座时，改动应保持聚焦，说明为什么不能在项目适配层完成，并通过合同测试固定
  输入、输出、错误、版本和状态所有权；
- 新工具不能因为实现方便就把 Agent 工作流固化进底层 runtime。底层只提供可验证能力，设计、
  查询取舍和失败修正仍由 Agent 主导；
- 安装、更新和打包逻辑应区分项目产品版本、上游基座版本、PoB commit、数据版本和 converter
  provider 版本，不能继续依赖“它们总在同一仓库、同一版本变化”的隐含假设；
- 保留上游许可证、来源和修改说明。解耦不表示隐藏派生关系，也不通过复制代码规避 attribution；
- 暂不执行仓库拆分。只有稳定边界、双边测试、迁移回滚方案和人工验收都准备完成后，才重新评估
  是否建立独立 runtime 仓库或外部服务。

本原则的目标是让后续功能与上游内部实现保持低耦合，而不是在当前阶段为了形式上的独立而破坏
已经可运行的生成、Judge 和导出闭环。

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
  -> Phase 7 同 Family / 同等级对照学习循环
  -> Phase 9 scale / revalidation / productization
```

其中 Phase 1 是所有“好坏判断”的前置门槛；Phase 2 和 Phase 3 是图记忆可用性的前置
门槛；Phase 4 负责把成熟 BD 研究变成可复用长期知识；Phase 5 之后才开始验证生成能
力；Phase 7 只有在生成、Research 和 Judge 可用后才有意义；Phase 5/6 的可信 artifact 是
普通 Create 交付与导出的基础。

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
- Phase 7：对成熟原 BD 做安全 Profile，形成唯一 `FamilyTarget`，只给独立 Create 任务相同 Family 和等级，再由独立
  Comparator 逐维比较。Judge 只作为 advisory evidence，不能按 aggregate 自动选赢家；具体
  build knowledge 回到 Research，不适合 Research schema 的跨维生成经验才进入 Learning Memory。
- 普通 Create：不扩写全知评分器。未指定唯一目标流派时，先从精确版本 Research 数据中召回
  全部合格的 2–10 个成熟 Family，做轻量机制/证据比较并保留第一名与备用；选中后由普通
  Create 独立生成并保存 immutable artifact。Judge 只作 advisory，typed
  Research receipt、设计覆盖和机制 gate 防止 Family/知识漂移。全局 optimizer/全局树重排禁用，
  重复检查按 build-state hash 合并。价格只作获取风险说明。

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
| Phase 6 | 已完成：最终 PoB 保存、桌面 PoB 文件导出、可插拔 converter、单阶段 `.build` 导出、自动校验和真实人工验收均已收口 | Phase 2、5 | 只保存 Phase 5 最终通过且被 Agent 接受的完整 PoB artifact，导出桌面 PoB 可查看的 XML/导入码，并忠实转换为官方单阶段 `.build` JSON；处理恢复、provider 隔离、官方 ID、导出校验和人工验收，不重新设计生命周期或补完整 BD。后续导出发现的构筑内容问题按根因回到 Phase 1-5 修正。 | `docs/phases/06_build_export.md` |
| Phase 7 | 功能实现完成、首轮实跑暂停于 6/10、学习效果未评估 | Phase 1、4、5，按需依赖 Phase 6 | 建立成熟原 BD Profile、同 Family/同等级盲测 Create、独立逐维比较和面向后续案例的 Research/轻量 Learning Memory 回流；首轮计划 10 个串行案例，恢复后再执行固定趋势验收。 | `docs/phases/07_critic_loop.md` |
| Phase 9 | 未开始 | Phase 1-7 达到进入条件 | 在核心闭环被 benchmark 证明后，再做规模化、自动重验证、前端和完整产品叙事。 | `docs/phases/09_scale_productization.md` |

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
- 不要持久化或暴露第三方成熟 BD 的 PoB code、raw XML、raw account/character details、长篇复制
  攻略文本，或由全部装备槽、整棵已分配天赋、全部技能组和完整配置组成的整角色镜像。允许保存
  可复用核心机制包，包括关键技能与辅助组合、局部核心天赋连接、暗金/装备与技能、天赋、资源系统
  的完整联动；边界按知识作用域而不是组件数量判断。系统自己生成、经过可信
  Judge、并由 Agent 明确接受的最终候选允许作为本地私有 `FinalBuildArtifact` 保存完整 PoB XML，
  但不得进入聊天、人工验收包、研究记忆或 Git。
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
- 同 Family、同等级 Create 的接受率和 Family 匹配率；
- generated stronger/not-weaker 比例、reference-advantage 维度数和 critical gap；
- Learning Memory 的召回、采用、拒绝、污染与 correction；
- 第一批 10 案例中最后 3 例相对最初 3 例的方向性趋势。

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

官方天赋树 provider 每小时尝试刷新，但可信缓存允许保留 7 天。GitHub 匿名 API 限流必须输出
明确诊断；运行环境可以通过 `GH_TOKEN` 或 `GITHUB_TOKEN` 提高限额。当官方提交时间暂时无法
确认，而本地已认证 PoB/语料与 poe.ninja 对同一赛季天赋树世代一致时，只降低“官方最新提交”
证据并输出 warning，不把整个构筑错误判成版本不可用；缺少独立交叉证据或世代冲突时仍阻断。

验证耗时也是规格的一部分：

- `quick` 是日常聚焦回归；`noncompute` 与 `full` 都排除完整 PoB compute golden，其中 `full`
  作为发布/合并门禁继续运行全部非计算测试和静态检查。
- `compute` 只在直接修改 PoB 引擎、Lua bridge、数值计算或 optimizer 行为，或人工明确要求时
  单独运行，不再被 `full`、runtime packaging 或普通 release 自动触发。它在 Windows 本地经常
  运行 15 分钟以上，执行时外层命令超时至少给到 30 分钟（`1800000ms`）。

## 文档模型

- `PROJECT_SPEC.md`：中文唯一项目总纲，维护方向、边界、Phase 关系和 Phase 状态。
- `ARCHITECTURE.md` / `ARCHITECTURE.CN.md`：仅此架构文档维护英文和中文两版。
- `SCHEMAS.md`：中文唯一核心数据结构合同。
- `JUDGE_SCORING_SYSTEM.md`：Judge 当前评分合同、证据分层、兼容逻辑和查询路径说明。
- `phases/*.md`：中文唯一阶段执行计划、验收标准和阶段内进度。

保持 `PROJECT_SPEC.md` 和 `ARCHITECTURE*.md` 紧凑，不要把它们写成详细阶段 task list。

## Public README 政策

根 `README.md` 现在允许存在，但定位很窄：它是安装/自动化 README，只写安装、skill
自动化入口、成熟 BD 研究命令、已验证的单阶段生成/导出能力、平台能力矩阵和安全边界。它可以
准确说明 Phase 5/6 已完成的 Agent 主导生成、最终 PoB 保存和官方 `.build` 导出，但不能据此
宣称生成质量、复合技能评分、对照学习效果或 reward memory 已成为成熟产品。完整 public product
narrative 仍等 learning/generation/evaluation loop 有 benchmark 证据后再扩展。

## 接续指南

上下文丢失后按顺序阅读：

1. `AGENTS.md`
2. `docs/PROJECT_SPEC.md`
3. `docs/ARCHITECTURE.md` 或 `docs/ARCHITECTURE.CN.md`
4. `docs/SCHEMAS.md`
5. 相关 `docs/phases/*.md`
6. `server/ASSISTANT_GUIDE.md`
7. `scripts/verify.ps1`
