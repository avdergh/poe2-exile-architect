# Phase 5 旧重型设计归档

> 本文件只作为旧设计参考，不代表当前 Phase 5 主线，不按本文中的“已完成/进行中”状态继续
> 开发。当前主线以 `docs/phases/05_generation.md` 为准。

# 旧标题：Phase 5 - Agent 主导的 BD 创建与验证反馈

## 阶段状态

进行中。P5.0 schema contracts、最小 final package gate、P5.1 deterministic Brief Interpreter
和 `/poe-bd-create` brief refinement 入口已实现；P5.2 Architect context assembly 已完成；
P5.3 Architect proposal prompt / packet handoff 已完成，等待阶段性 code review、需求对齐 review
和人工验收后进入 P5.4。

## 阶段定位

Phase 5 的目标不是写一个全知的程序化 BD 补全器，也不是让 Agent 直接输出一份未经验证
的完整 PoB。Phase 5 要建立第一版可验证的 BD 创建流程：

```text
UserBuildRequest
  -> BuildBriefDraft
  -> BuildBrief
  -> Phase 4 Architect research context
  -> ArchitectGenerationPacket
  -> Architect Agent candidate design space
  -> BuildPlan proposal
  -> BuildPlan acceptance gate
  -> deterministic completion / local search
  -> PoB import + Judge advisory
  -> failure audit + internal retry
  -> candidate selection
  -> BuildCandidatePackage + benchmark report
```

核心原则是 `Agent-directed constrained generation`：Agent 负责机制设计、候选空间、取舍和
失败修正；仓库负责 resolver、typed schema、局部搜索、约束校验、PoB/Judge 参考评估和
可追溯报告。

Phase 5 的上限来自 Agent、Phase 4 记忆、deterministic tools 和 Judge feedback 的协作，而
不是单靠固定程序把一个粗略蓝图补成高端 BD。

## 依赖

- Phase 1 Judge / modelability 基线。
- Phase 2 source-backed physical graph 和 official ID / endpoint mapping。
- Phase 3 typed graph retrieval、resolver 和 topology tools。
- Phase 4 semantic memory、build patterns、Architect research context handoff。

## 输入层：UserBuildRequest -> BuildBrief

用户请求可能很模糊，也可能很具体。Phase 5 需要先把自然语言请求转换成结构化
`BuildBrief`。

示例请求：

- “我想要一个适合新手开荒的 BD”；
- “我想要一个上限很高的 BD”；
- “给我某个职业的强力 BD”；
- “我想玩某个升华下的某种玩法”；
- “便宜、手感好、不太脆，最好适合刷图”。

新增 `UserBuildRequest` 和 `BriefInterpreter`：

- `UserBuildRequest` 保存用户需求的安全摘要、字段来源、可追问事项和 version / freshness
  context，不保存 raw request summary、完整 raw transcript 或 raw dialogue；
- `BriefInterpreter` 由外部 Agent 执行，职责只是把用户意图转成 `BuildBriefDraft` 和可验证
  `BuildBrief`，不是直接生成 BD；
- `BuildBriefDraft` 保存 Agent 的解释摘要、字段来源、默认假设、clarification questions、
  未决项和可审查 rationale summary；信息足够时可以同时输出 `BuildBrief`，但缺少关键约束
  或存在互斥职业等不可满足合同冲突时必须保持 `needs_clarification`；
- `BuildBriefDraft` 不能保存 hidden chain-of-thought、完整对话 transcript、raw scratchpad 或
  中间推理日志；
- 每个解释性字段必须标记来源：`user_explicit`、`agent_inferred`、`defaulted` 或 `unknown`；
- `BuildBriefDraft.fieldSources` 不能为空；`BuildBrief.fieldSources` 至少覆盖 goal、target scenes、
  lifecycle stages、target lifecycle stages、cross-stage locked dimensions、economy mode、
  budget model、price source status 和 modelability tolerance；
- Agent 可以从“新手开荒”推断 low budget、low complexity、league start，但这些必须标记
  为 `agent_inferred`，不能伪装成用户明确要求；
- 缺少关键约束时，优先生成 clarification questions；如果用户允许继续，则以 caveat 形式
  记录假设。

`BuildBrief` 至少包含：

- goal / target scene：mapping、bossing、hybrid、campaign、league start、endgame；
- lifecycle stage：本次 Phase 5 输出/生成的阶段，campaign early / mid / late、maps entry、
  budget endgame、final endgame；
- target lifecycle stage：设计时必须考虑的完整生命周期目标；例如用户要求“先给开荒，但后期
  洗点转攻坚/终局”，`lifecycleStages` 可以只含 campaign late / maps entry，
  `targetLifecycleStages` 必须同时包含 budget endgame / final endgame；
- cross-stage locked dimensions：当前 Phase 5 只允许 `class` 作为跨阶段硬锁；开荒、攻坚和
  终局之间可以更换升华、技能、support、天赋和装备，但不能更换职业；
- economy / budget：trade、SSF、league start、low / medium / high / minmax / unknown；
- required / preferred / forbidden class、ascendancy、skill、mechanic、item；
- complexity preference：button count、rotation complexity、new-player friendliness；
- defense preference：tankiness、avoidance、minion playstyle、range / melee tolerance；
- craft / trade realism：unique availability、craft effort tolerance、price source status；
- modelability tolerance：是否接受 PoB/Judge 部分不可建模的机制；
- freshness context：league / ruleset、game patch、passive tree version、PoB version / commit、
  graph snapshot id、research memory snapshot / query ref；
- export requirements：是否需要后续 Phase 6 `.build` export readiness。

## Architect Research Context

Phase 5 必须消费 Phase 4 的 creator-visible、planner-visible research context：

- clean fragments；
- advisory semantic edges；
- build archetype patterns；
- cooccurrence patterns；
- transition gates；
- failure caveats；
- modelability caveats；
- verification tasks；
- `usedFragmentIds`、`usedSemanticEdgeIds`、`usedPatternIds`。

这些 context 只能作为 advisory research context，不能替代 Phase 2/3 hard source facts、
support/socket legality、deterministic planner 或 Phase 1 Judge。

`needs_revalidation`、stale 或 low-confidence memory 只能进入 caveat / verification task，
不能作为强证据驱动生成。

Phase 5 context assembly 必须执行 split 和版本边界：

- 只允许消费 `creator_visible` / `planner_visible`、`train_context`、copy-safety passed 的
  context；Phase 4 handoff report 必须显式携带 top-level 和 row-level `visibility`、`split`、
  `copySafetyState` 证明，不能只靠上游筛选假设；
- `ArchitectResearchContextForGeneration` 必须用 typed `visibility`、`split` 和 `knowledgeScope`
  表达边界，不能只靠自由文本 status；
- evaluator-only、holdout、quarantined、raw-rich transient evidence 不能进入 Architect
  generation packet；
- context 的 game patch、passive tree version、PoB version / commit 和 graph snapshot 必须
  与 `BuildBrief` 的 freshness context 对齐；不一致时只能作为 stale caveat 或 verification
  task，不能作为当前强建议；缺少可验证 freshness 证明时也必须排除对应 row；
- transition gates、planner hints、modelability caveats 和 verification tasks 必须从通过 P5.2 row
  gate 的 fragments / edges / patterns 重建，不能直接转发 Phase 4 report 顶层 advisory list；
- `ArchitectGenerationPacket` 本身、`BuildBrief` 和 `ArchitectResearchContext` 的 league /
  ruleset / patch / tree / PoB / graph snapshot / research memory ref 必须一致；
- `usedFragmentIds`、`usedSemanticEdgeIds`、`usedPatternIds` 必须进入后续
  `BuildCandidatePackage`，用于 benchmark 和人工 review 追溯。

## 新赛季 / 新 Patch 更新流程

Phase 5 的 version / freshness context 会随着赛季、patch、passive tree、PoB commit、graph
snapshot 和 Phase 4 research memory 更新而变化。新赛季来临时，Phase 5 不应靠散落的硬编码
字符串维持可用性；必须通过本节维护当前阶段需要更新的范围和方式。

本节只约束 Phase 5。Phase 1-4、Phase 6+ 的更新流程不在这里展开。

当前 P5.0 已实现 schema contracts 和最小 final package gate，P5.1 已实现 deterministic Brief
Interpreter 和 `/poe-bd-create` brief refinement 入口，P5.2 已实现 Architect context assembly，
因此新赛季至少检查：

- `VersionContext` 合同是否仍覆盖当前生成所需的 freshness 字段：league、ruleset、game patch、
  passive tree version、PoB version / commit、graph snapshot id、research memory ref；
- P5.0 测试 fixture 中的 league / patch / tree / graph snapshot 示例是否仍适合作为合同样例；
  如果会误导验收或文档，就更新 fixture 和测试说明；
- `ArchitectGenerationPacket`、`BuildBrief`、`ArchitectResearchContextForGeneration`、
  `BuildCandidatePackage` 的 version / freshness 对齐 gate 是否仍能拒绝跨赛季 artifact 拼接；
- `server/generation/brief_interpreter.py` 是否仍只从用户请求和传入 `VersionContext` 推断，不
  内置过期赛季名、patch、经济或 price source 结论；
- `scripts/create_build.py brief`、`poe-bd-creator-plugin/skills/poe-bd-create/SKILL.md`、
  `server/ASSISTANT_GUIDE.md` 和 `README.md` 中的 P5.1 示例 version context 是否仍适合作为
  合同样例；如果会误导新赛季运行，就更新示例和测试 fixture；
- `scripts/create_build.py context` 是否仍能把当前 Phase 4 handoff report 转换为
  `ArchitectResearchContextForGeneration`，并且 stale / `needs_revalidation` / version mismatch
  只进入 caveat，不进入 used ids；
- Phase 4 handoff report 是否显式输出 top-level 和 row-level `visibility`、`split`、
  `copySafetyState`、`pobVersionOrCommit` 和 `currentVersionContext`；缺少这些证明时 P5.2 应拒绝
  report 或把对应 row 排除；
- Phase 4 handoff report 中的 `gamePatch`、`passiveTreeVersion`、`pobVersionOrCommit` 和
  `currentVersionContext.graphSnapshotId` 是否与 `BuildBrief.versionContext` 对齐；不对齐时必须
  刷新 Phase 4 context handoff，或让 P5.2 输出 `stale_caveated` / `missing_context`；
- 当前 graph snapshot 更新后，P5.2 测试 fixture、`VersionContext.graphSnapshotId` 示例和
  `currentVersionContext` 示例必须一起更新，避免跨 snapshot artifact 拼接；
- 如果新赛季 economy / trade API 或价格源状态变化，P5.1 仍只能把 `priceSourceStatus` 置为
  `unknown` 或用户/外部工具明确提供的状态，不能凭旧赛季默认成 `fresh`；
- `docs/phases/05_generation.md` 中的 Phase 5 状态、已完成项和新赛季维护清单是否需要更新；
- 运行 `tests/test_phase5_generation_models.py`、`tests/test_phase5_brief_interpreter.py`、
  `tests/test_phase5_create_build_cli.py`、`tests/test_phase5_generation_productization_docs.py`
  和 `scripts/verify.ps1 quick`，确认 schema / gate / brief refinement 合同没有被新版本上下文破坏。

随着 P5.1+ 开发推进，本节必须同步扩展。例如：

- P5.1 Brief Interpreter 完成后，补充新赛季默认 league / economy / price source 解释规则的更新方式；已完成
- P5.2 Architect context assembly 完成后，补充如何刷新 Phase 4 context handoff、stale /
  `needs_revalidation` caveat 和 current graph snapshot；已完成
- P5.3 Architect proposal prompt 完成后，补充 worker prompt、allowed schema、run id /
  candidate prefix、output directory ref 和 `CandidateDesignSpace` accept schema 的版本化更新方式；
  已完成
- P5.4 / P5.5 deterministic tools 完成后，补充 support、Spirit、passive、gear、price 和 craft
  realism 相关数据源或约束的更新方式；
- P5.6 PoB / Judge 接入后，补充 PoB commit、Judge advisory caveat、modelability gap 和 import
  smoke 的更新方式；
- P5.10 benchmark 完成后，补充新赛季固定 BuildBrief benchmark、memory-assisted baseline 和
  人工 review 样例的重跑要求。

如果新赛季只改变本地 runtime cache 或用户生成记录，不需要推送 GitHub。只有当 schema、测试
fixture、文档、pinned data、plugin/runtime bundle 或仓库内验证合同发生变化时，才需要提交并
推送到 GitHub。

## Architect Generation Packet

Phase 5 不新增内部 OpenAI / Claude / Gemini provider loop。仓库只负责生成安全的
`ArchitectGenerationPacket` / `workerPrompt`，由外部成熟 Agent 执行 Architect 推理。

`ArchitectGenerationPacket` 至少包含：

- safe `BuildBrief`；
- Phase 4 `ArchitectResearchContext` 和 used ids；
- resolver / graph query instructions；
- allowed output schema；
- copy-safety rules；
- hard blocker / advisory signal policy；
- version / freshness context；
- 当前 run id、candidate id 前缀和输出目录。

Packet / prompt 可以包含供外部 Agent 推理的安全上下文，但不能包含 raw PoB code、raw XML、
完整装备表、完整天赋路径、完整 gem/support links、raw account / character details、完整 URL
或 evaluator-only / holdout / quarantined evidence；除 copy-safety policy 本身外，所有
agent-facing packet text 都必须经过 split / holdout / quarantine / raw-rich marker 检查，不能只
检查 structured context。

Phase 5 应提供类似 Phase 4.5 的 accept flow：

- `queue` / `claim` / `prompt` / `accept` 或等价 service 入口只输出 safe metadata；
- `prompt` 是唯一给 Architect worker 的推理输入，主 orchestrator 不应转述 transient
  candidate / runtime material；
- P5.3 `accept-design-space` 只接受 strict schema 的 `CandidateDesignSpace`，并检查 schema、
  no-raw、brief id、version context、Phase 4 used ids 和 resolver snapshot；
- `BuildPlanProposal` accept 和 BuildPlan gate 属于 P5.4，不能在 P5.3 中伪装成已完成；
- 运行态不得修改仓库源码、测试、文档、schema 或 plugin manifest。

## Architect Candidate Design Space

Architect Agent 不应只给一个单线答案，而应先输出 `CandidateDesignSpace`：

- 可能的升华壳；
- 主技能 / secondary skill / delivery package；
- scaling axis：伤害类型、暴击/非暴击、投射物、召唤、异常、触发、持续伤害等；
- key passive / notable / keystone anchors；
- unique / base item / weapon family candidates；
- Spirit / reservation package；
- defense layer package；
- transition gates；
- failure modes；
- modelability caveats；
- variants：starter/endgame、SSF/trade、crit/non-crit、mapping/bossing。

Agent 可以提出候选机制和变体，但必须通过 resolver / graph tools 验证 endpoint。ambiguous /
missing endpoint 只能进入 caveat 或 verification task，不能被自动选择。

## BuildPlan Proposal

`BuildPlanProposal` 是 Architect 对某一候选路线的结构化方案。它表达设计假设和搜索空间，
而不是完整最终 BD。

它可以包含：

- build identity / archetype；
- class、ascendancy、main skill、secondary skills；
- component roles：primary_damage、clear_skill、boss_skill、generator、payoff、
  reservation、defensive_buff、movement、trigger_host、support_modifier、unique_enabler、
  passive_anchor、keystone_transformer、weapon_base、scaling_stat、defense_layer、
  resource_engine；
- passive anchors，而不是完整 passive path；
- support intent 和 candidate supports，而不是复制完整 gem/support link；
- gear roles、base candidates、unique candidates、stat priorities，而不是完整装备表；
- Spirit / reservation assumptions；
- state A / state B assumptions；
- stage plan / progression assumptions：campaign、maps entry、budget endgame 和 final endgame
  的最小差异、过渡门槛和未解决 caveats；
- transition gates 和 failure modes；
- unresolved / ambiguous caveats；
- used Phase 4 context ids。

`BuildPlanProposal` 不能：

- 直接写 PoB XML / PoB code；
- 直接输出完整 passive path；
- 直接复制成熟 BD 的完整装备表；
- 直接复制完整 gem/support link 套餐；
- 把 advisory pattern 当 hard legality；
- 把单样本 `case_observation` 说成 usually / common / 常见。

这不是为了避开正确答案。Phase 5 禁止的是复制成熟 BD 的原始表达，不禁止独立生成相同或
相似的合理机制。只要 resolver-backed、copy-safe、planner/Judge 可验证，系统可以使用常见
强机制、强暗金、强天赋和强 support 思路。

## BuildPlan Acceptance Gate

新增 `BuildPlanAcceptanceGate`。Gate 的职责是拒绝不安全或不可验证的方案，而不是压制强解。

Gate 检查：

- schema 是否 strict；
- endpoint 是否 resolver-backed；
- ambiguous / missing endpoint 是否被降级为 caveat；
- Phase 4 used ids 是否保留；
- context requirements 是否 typed；
- visibility / split / scope 是否允许进入 creator 侧生成；
- patch / tree / PoB / graph snapshot / research memory freshness 是否匹配或已降级为 caveat；
- copy-safety 是否通过；
- 是否包含 raw PoB code、raw XML、完整装备表、完整天赋路径、完整 gem/support links、
  raw account / character details 或完整 URL；
- 是否把 advisory research context 误写为 hard legality；
- 是否把低样本观察误写为 common pattern。

Gate 不检查：

- “这个机制是不是太常见”；
- “这个暗金是不是成熟 BD 也用了”；
- “这个天赋是不是强势所以要避开”。

## Deterministic Completion / Local Search

Phase 5 的程序化部分是局部补全和约束搜索，不是假装全局理解 PoE2。

局部工具包括：

- resolver / graph preflight；
- support legality 和 support candidate search；
- Spirit / reservation budget check；
- passive anchor connection / budget check；
- attribute / resistance / requirement check；
- gear role completion / affix search；
- budget / craft realism scoring；
- unique availability 和 price freshness caveat；
- weapon/base compatibility；
- PoB import / snapshot creation；
- Judge advisory evaluation。

中间态和最终态要分开：

- 在 deterministic completion 过程中，attribute / resistance / passive budget / Spirit 等失败可
  作为 solver target 或 repair target 保留；
- 只有当补全器证明 infeasible、搜索预算耗尽、或最终 `BuildSnapshot` 仍违反 hard blocker 时，
  这些失败才阻止候选通过；
- 每个补全器都必须输出 searched constraints、accepted assumptions、unresolved constraints、
  infeasible reason 和版本上下文，不能只输出“已补完”。

对 lifecycle / 开荒需求，Phase 5 至少输出 `StagePlan`：

- 覆盖 `BuildBrief` 要求的 lifecycle stage；
- `StagePlan` 只需覆盖本次输出的 `lifecycleStages`，不强制覆盖未来
  `targetLifecycleStages`；未来阶段目标用于当前职业和设计方向选择，并进入 caveat /
  transition gate；
- 标记每个 stage 的 skill intent、核心 anchor、装备/词缀角色、Spirit / reservation 假设和
  transition gate；
- transition gate 可以是平滑过渡点，也可以是允许洗点、换技能、换装备、甚至换升华后的转型
  门槛；只有职业不能作为可变维度处理；
- 允许输出 stage caveat 或 unresolved progression gap；
- 不要求生成官方 `.build` 的精确 level interval、完整 leveling passive path 或完整升级装备表；
  这些属于 Phase 6。

OR-Tools 可以作为 `GearConstraintSolver` 的实现选项，但不是 Phase 5 的中心。必须先做
dependency spike：

- 验证 uv / Windows / macOS / Linux 安装可用；
- 运行最小 CP-SAT 或 MIP smoke test；
- 证明它对装备约束问题比现有 greedy / scaffold 有明确收益。

Agent 不能直接写 OR-Tools API calls；它只能提交 typed constraints 和 goals。程序把这些约束
翻译给 solver。

## Judge Advisory 与 Failure Audit

Phase 1 Judge 在 Phase 5 中是重要参考，但不是绝对真理。任何失败都要进入
`FailureAuditPacket`，由 Agent 和 deterministic diagnostics 一起核验。

Hard deterministic blockers 可以直接阻止候选：

- class / ascendancy pairing 不合法；
- endpoint 不存在；
- support 明确不兼容；
- passive budget 明确超；
- Spirit 明确超；
- 属性需求明确不满足；
- PoB import 完全失败；
- raw / copy-safety 违规。

Advisory judge signals 只作为参考：

- DPS / EHP / recovery / mobility 低；
- selected skill 不确定；
- `FullDPS` rollup；
- minion / trigger / projectile lower-bound caveat；
- modelability gap；
- recovery pool / defense model 不完整；
- dual-state limited evidence。

`FailureAuditPacket` 必须分类失败来源：

- `true_build_failure`：构筑确实非法或明显失败；
- `planner_completion_failure`：局部补全器补错或搜索空间太窄；
- `judge_modelability_gap`：Judge / PoB 表达不足；
- `selected_skill_probe_suspect`：当前评分技能选择可疑；
- `resolver_or_source_gap`：graph/source 覆盖不足；
- `architect_assumption_error`：Architect 设计假设错误；
- `needs_user_clarification`：用户 brief 不足以判断。

Judge 判定失败后不能直接结束；Phase 5 必须核验失败是否合理，并把工具误判或覆盖缺口记录
为 `ToolFeedbackEvent`。

Agent 可以质疑 Judge / PoB / planner 的诊断，但不能自行覆盖 hard blocker：

- 如果 Agent 判断 hard blocker 来自工具误判或 source gap，候选仍保持 invalid / caveated；
- 只有 deterministic tool、resolver、PoB/Judge readback 或人工验收补充证据后，hard blocker
  才能解除；
- copy-safety 违规不能通过 Agent audit 降级为 advisory signal。

`ToolFeedbackEvent` 只是开发和验收反馈，不是 reward memory：

- 不自动调整 graph / memory 权重；
- 不自动放宽 gate；
- 不自动改变 solver 行为；
- 后续必须通过测试、fixture 或人工 review 才能转化为工具改动。

## Internal Retry

Phase 5 必须支持小型 internal generation retry。它和 Phase 7 Critic loop 不同。

Phase 5 internal retry：

- 发生在单次 `/poe-bd-create` 运行内部；
- 目标是让当前候选更合法、更完整、更符合 brief；
- 通常限制 1-2 轮；
- 不沉淀 reward memory；
- 不做 reference / mature BD 深度比较；
- 不做 rollback / early stopping 框架。

Phase 7 Critic loop：

- 是跨轮次、可学习、可沉淀的进化循环；
- 可以和 reference / mature BD / prior snapshot 比较；
- 记录 failed strategies；
- 支持 rollback、early stopping；
- 产出 failure pattern / reward memory 候选。

二者不冲突。Phase 5 internal retry 是为了让第一次生成不太弱；Phase 7 是后续系统进化。

## Candidate Selection

Phase 5 允许 Architect 提出多个候选，但必须用结构化 `CandidateSelectionReport` 说明最终选择。

选择顺序建议：

- 先过滤 raw / copy-safety / schema / unresolved hard endpoint failure；
- 再过滤最终 `BuildSnapshot` 上仍无法解释的 hard deterministic blockers；
- 再按 brief fit、lifecycle / budget / craft realism、modelability tolerance、transition gate
  覆盖、Judge advisory score 和 caveat 严重度排序；
- 对 limited evidence 候选，可以被选为当前最好方向，但必须保留 reward-ineligible /
  limited-evidence caveat，不能声称强可比或强 reward。

`CandidateSelectionReport` 至少记录：

- considered candidate ids；
- rejected candidate ids 和 structured reasons；
- selected candidate id；
- tie-break policy；
- used Phase 4 ids；
- Judge advisory summary；
- unresolved caveats；
- human-review fields。

## BuildCandidatePackage Acceptance Gate

`BuildPlanAcceptanceGate` 只证明候选方案输入安全，不证明最终报告安全。Phase 5 还必须在输出
前执行 `BuildCandidatePackageAcceptanceGate`。

Final package gate 检查：

- package schema strict；
- `BuildBrief`、`ArchitectResearchContext` used ids、`CandidateDesignSpace`、`BuildPlanProposal`、
  `PlannerCompletionResult`、`StagePlan`、`CandidateSelectionReport`、`JudgeAdvisoryReport`、
  `FailureAuditPacket` 和 caveats 是否齐全；
- local opaque snapshot id、source hash、version / freshness / graph snapshot context 是否存在；
- local opaque snapshot id 和 source hash 是否为非空安全引用；
- `CandidateDesignSpace.briefId` 是否引用当前 `BuildBrief.briefId`，`PlannerCompletionResult.proposalId`
  是否引用当前 `BuildPlanProposal.proposalId`；
- resolver evidence 的 `snapshotId` 是否与 package graph snapshot id 一致；
- package 顶层、`BuildPlanProposal.stagePlan` 和 `PlannerCompletionResult.stagePlan` 是否都覆盖
  `BuildBrief.lifecycleStages`；
- package、brief、design space、proposal、completion、stage plan、selection、snapshot、Judge、
  audit、benchmark、tool feedback 和 optional export readiness 的 league / ruleset / game patch /
  passive tree / PoB / graph snapshot / research memory ref 是否一致；
- Phase 4 used ids 是否跨 `ArchitectResearchContext`、`CandidateDesignSpace`、`BuildPlanProposal`
  和 `CandidateSelectionReport` 可追溯；
  accepted package 至少必须携带一个 Phase 4 used id，不能全 bucket 为空；design space、proposal
  和 selection report 也必须各自携带可追溯 used id；
- `CandidateSelectionReport` 的 considered / rejected / selected candidate ids 是否都存在于
  `CandidateDesignSpace`；
- selected candidate 是否没有同时出现在 rejected candidates 中；
- final hard blocker 是否被正确标记为 invalid / caveated，且没有被 Agent audit 覆盖；
- `PlannerCompletionResult` 的 infeasible / error、invalid support / Spirit / passive / gear、
  Spirit 超预算和 passive 超预算不能作为成功 package 输出；
- `JudgeAdvisoryReport.hardFailures` 不能作为成功 package 输出；如果需要继续，只能进入 bounded
  retry、safe incomplete summary 或人工复核；
- `JudgeAdvisoryReport.status` 必须是 `evaluated` 才能作为 accepted package 输出；
- no-raw-material safety flags 是否为 true；
- 输出不包含 raw PoB code、raw XML、完整装备表、完整天赋路径、完整 gem/support links、
  raw account / character details、完整 URL、hidden chain-of-thought、transcript、dialogue 或
  raw transcript；
- optional `ExportReadinessReport` 是否只表达 readiness / unsupported caveat，不伪装成 Phase 6
  已完成 export。

未通过 final package gate 的结果不能作为 `/poe-bd-create` 的成功报告，只能输出 safe error、
incomplete package summary 或进入 bounded retry。

## 产品化入口

Phase 5 应新增用户-facing skill / command：

```text
/poe-bd-create
```

示例：

```text
/poe-bd-create 我想要一个适合新手开荒的 Deadeye 弓系 BD
/poe-bd-create --ascendancy Stormweaver --goal bossing --budget medium
/poe-bd-create --brief-file brief.json
```

该入口应像 `/poe-bd-research` 一样产品化：

- 无参数时先询问生成目标和约束，而不是直接开始；
- 支持交互式选择时，优先给出 brief refinement 选项；
- 支持本地 `brief.json`；
- 输出 safe generation report；
- `BuildBrief` 是给后续 Architect / planner / skills 使用的结构化 artifact；运行态 agent 应向用户
  总结规范化后的关键意图和必要追问，而不是要求用户阅读或复制 JSON；
- `clarificationQuestions` 是 agent-facing follow-up queue；如果 `BuildBrief` 已 ready，agent
  可以先呈现规范化意图并把追问作为下一轮自然语言问题，而不是用追问替代 `BuildBrief` 本身；
- 支持输出 / 接受 `ArchitectGenerationPacket`、`CandidateDesignSpace`、`BuildPlanProposal`
  和 `BuildCandidatePackage`；
- 不要求用户手动执行 shell 命令；
- 不在运行态修改仓库源码、测试、文档、schema 或 plugin manifest。

`/poe-bd-create` 应作为 Phase 7 的默认生成入口。Phase 7 可以调用同一套 service 生成新候选
或修正候选，而不是复制一套生成逻辑。

## 可插拔边界

Phase 5 generation module 必须可替换：

- 默认实现是外部 Architect Agent + 本地 deterministic tools；
- 未来可以替换为其他成熟 BD 生成模块；
- 替换模块只要输入 `BuildBrief`，输出 `BuildPlanProposal` / `BuildCandidatePackage`，并通
  过同样的 resolver、copy-safety、planner、Judge 和 benchmark gate，就可以接入。

项目仍不新增内部 OpenAI / Claude / Gemini provider loop。

## Phase 5 / Phase 6 边界

Phase 5 不合并 Phase 6。

Phase 5 关注：

```text
能否从用户需求生成合理、可验证、可评估的 BD 候选？
```

Phase 6 关注：

```text
能否把候选稳定导出为官方 `.build` JSON，并表达 leveling progression？
```

Phase 5 输出 `BuildCandidatePackage`：

- `BuildBrief`；
- `ArchitectResearchContext` used ids；
- `CandidateDesignSpace`；
- `BuildPlanProposal`；
- `PlannerCompletionResult`；
- `StagePlan` / `progressionAssumptions` / stage caveats；
- `CandidateSelectionReport`；
- `BuildSnapshot` local opaque id、source hash 和 sanitized summary；
- `JudgeAdvisoryReport`；
- `FailureAuditPacket`；
- `ToolFeedbackEvent`；
- `GenerationBenchmarkReport`；
- optional `ExportReadinessReport`。

Phase 6 读取 `BuildCandidatePackage`，只负责 `.build` export、level intervals、official GGG
ID resolution、unsupported field caveats 和 export schema validation。

`BuildCandidatePackage` 不能输出 raw PoB code / XML 或完整可复刻 build material。PoB import /
export material 只能作为 transient runtime artifact 存在于本地 opaque reference 后面；报告和聊天
输出只能暴露 hash、summary、caveats 和本地 snapshot id。

## 非目标

- 不做完整 Critic repair loop、rollback 或 early stopping；这是 Phase 7。
- 不写 reward weights 或 reward memory；这是 Phase 8。
- 不承诺官方 `.build` 导出；这是 Phase 6。
- 不声称 Judge 分数就是机制真值；Judge 是 advisory + hard blocker 的混合工具。
- 不把 Phase 4 mature BD pattern 当成 hard legality。
- 不复制成熟 BD 的 raw material 或完整表达。

## 阶段开发与 Review 准则

Phase 5 每个有验收标准的小阶段完成后都要进行 code review 和需求对齐 review；review 结论是
审查输入，不是自动采纳的权威。

采纳 subagent / reviewer 反馈前必须先核验：

- 是否符合 PoE2 领域事实和项目硬边界，例如职业不能跨阶段更换，只能洗升华、技能、天赋、
  装备和 support；
- 是否符合用户已确认的阶段范围，例如当前 P5.1 不新增 `lifecycleStrategy`、
  `activeOutputStages` 或 `futureStageGoals`；
- 是否能被代码事实、测试 fixture、deterministic tool、PoB/Judge readback 或人工验收支撑；
- 是否会引入过宽解释、误导字段名、错误业务语义或把非法用户表述建模成可支持功能。

不合理或语义不准确的 review 反馈必须改写成正确的问题再处理；必要时先向用户确认，不能为了
“消灭 review finding”而违背领域规则或扩大阶段范围。

## 工作项

### P5.0 文档与 schema - 已完成

- 更新 `BuildBrief`、`BuildPlan`、`BuildSnapshot` 相关 schema。已完成
- 新增 `UserBuildRequest`、`BuildBriefDraft`、`BriefInterpreterOutput`、
  `ArchitectGenerationPacket`、`CandidateDesignSpace`、
  `BuildPlanProposal`、`BuildPlanAcceptanceReport`、`PlannerCompletionResult`、
  `StagePlan`、`FailureAuditPacket`、`ToolFeedbackEvent`、`CandidateSelectionReport`、
  `BuildCandidatePackageAcceptanceReport`、`BuildCandidatePackage`。已完成
- 所有 schema 使用 strict typed models，不接受开放 `Dict[str, Any]` 作为持久合同。已完成
- 所有持久 artifact 都必须包含 version / freshness / snapshot context 和 no-raw-material
  safety flags。已完成
- 所有 Agent-facing 或 durable summary 只能保存 rationale summary，不能保存 hidden
  chain-of-thought、raw transcript 或 scratchpad。已完成
- `BuildCandidatePackageAcceptanceReport` 和 `validate_build_candidate_package` 最小实现已完成：
  覆盖 no-raw / no-hidden-reasoning、copy-safety、version context、nested `StagePlan`、
  Phase 4 used ids、artifact reference、resolver snapshot、candidate selection、planner hard
  blocker、Judge evaluated status / hard failure 和 safe acceptance report。已完成
- `validate_generation_packet` 已校验 packet、brief 和 Architect context 的 freshness / version
  对齐，并对 agent-facing packet text 与 structured context 执行 split / holdout / quarantine /
  raw-rich marker 检查，同时避免把安全规则文本中提到的 holdout / quarantined policy 误判为上下文
  污染。已完成
- `ArchitectGenerationPacket` 已包含 run id、candidate id prefix、output directory ref 和
  resolver / graph query instructions。已完成
- `UserBuildRequest`、`BuildBriefDraft` 和 `BuildBrief` 的 version context / field source provenance
  已收紧；`UserBuildRequest` 不保存 raw request summary；Architect context split / visibility /
  scope 已改为 typed contract。已完成
- 新增 Phase 5 新赛季 / 新 patch 更新流程，并声明该流程随 P5.x 开发持续维护。已完成

### P5.1 Brief Interpreter - 已完成

- 实现 deterministic `BriefInterpreter`，把 transient 用户请求转换成 safe `UserBuildRequest`、
  `BuildBriefDraft` 和可选 `BuildBrief`，不运行内部 provider loop。已完成
- 实现 `/poe-bd-create` 无参数和自然语言请求的 brief refinement 流程；当前 P5.1 只输出 brief，
  不生成候选 BD、不运行 planner、不运行 PoB/Judge。已完成
- 标记 `user_explicit` / `agent_inferred` / `defaulted` / `unknown`。已完成
- 对关键缺口输出 clarification questions。已完成
- copyable build link / PoB-like material 在进入 durable artifact 前 redacted，并只作为 unresolved
  caveat 保留。已完成
- 新增 `targetLifecycleStages` 和 `crossStageLockedDimensions=["class"]`，保留“先开荒、后期
  洗点转攻坚/终局”的长期目标，同时不要求当前 `StagePlan` 输出未来完整 BD。已完成
- 调整 `StagePlan.transitionGates` 语义：transition gate 可以表达洗点/换技能/换装备/换升华后
  的转型门槛，但职业必须跨阶段保持不变。已完成
- 新增 `scripts/create_build.py brief`，作为 skill 和其他宿主可调用的 safe CLI 包装。已完成
- 新增 `poe-bd-creator-plugin/skills/poe-bd-create/SKILL.md`，并更新 installer fallback、README、
  assistant guide 和 plugin manifest，使入口可独立插拔。已完成

### 后续优化：多语言 PoE2 术语归一化

P5.1 当前只做最小 deterministic brief refinement。后续应增加专业术语归一化层，用于中文、
日语、韩语等自然语言请求进入 Phase 4 memory / graph 检索前的 domain mapping：

- 保留用户原语言 safe summary，但额外生成 agent-facing normalized domain terms；
- 使用项目维护的 PoE2 glossary / alias table，把“开荒”“攻坚”“终局”“洗点”“升华”等术语
  映射到 controlled vocabulary、英文 domain terms 或 stable keys；
- 不能确定的术语不做硬翻译，进入 unresolved/caveat 或 clarification queue；
- 不使用普通直译替代专业映射，避免把 PoE2 专有词、职业/升华/技能名和玩法语境翻错；
- 该优化进入后续 P5.x / P5.2 context handoff 设计，不作为当前 P5.1 验收阻塞项。

### P5.2 Architect context assembly

- 读取 Phase 4 creator-visible、planner-visible context。已完成
- 输出 `usedFragmentIds`、`usedSemanticEdgeIds`、`usedPatternIds`。已完成
- stale / `needs_revalidation` context 只作为 caveat。已完成
- 拒绝 evaluator-only、holdout、quarantined 或 raw-rich transient evidence 进入 generation
  packet。已完成
- 校验 context 与 `BuildBrief` 的 patch / tree / PoB / graph snapshot freshness；缺 freshness
  证明的 row 不能进入 used ids。已完成
- 从通过 P5.2 gate 的 row 重建 transition gates、planner hints、modelability caveats 和
  verification tasks，避免 stale row 的顶层 advisory 残留。已完成
- `ArchitectGenerationPacket` handoff 必须保留 `targetLifecycleStages` 和
  `crossStageLockedDimensions=["class"]`，使 Architect 在只生成当前 `lifecycleStages` 时仍按
  完整生命周期目标选择职业 shell 和长期方向。已完成
- 新增 `server/generation/context_assembly.py` 和 `scripts/create_build.py context`，作为外部
  orchestrator / skill 可插拔调用的 safe context assembly 入口。已完成

### P5.3 Architect proposal prompt - 已完成

- 生成 safe `ArchitectGenerationPacket` / worker prompt，不运行内部 provider loop。已完成
- 让 Architect Agent 输出 `CandidateDesignSpace`，而不是单一路线。已完成
- 要求每个候选说明 role、assumption、transition gate、failure mode 和 modelability caveat。
  已完成
- 要求 query-before-propose，不能凭名字硬选 endpoint。已完成
- 通过 P5.3 accept flow 接收 strict schema `CandidateDesignSpace` 输出。已完成
- 新增 `server/generation/packet_builder.py`、`scripts/create_build.py packet` 和
  `scripts/create_build.py accept-design-space`，作为外部 orchestrator / skill 可插拔调用的
  safe Architect handoff 入口。已完成

### P5.4 BuildPlan gate

- 校验 resolver evidence、typed constraints、copy-safety 和 used ids。
- 拒绝 ambiguous endpoint 自动选择。
- 拒绝完整装备表、完整天赋路径和完整 gem/support links。
- 不拒绝独立生成的常见强机制。

### P5.5 Deterministic completion tools

- 实现 support / socket candidate completion。
- 实现 Spirit / reservation budget check。
- 实现 passive anchor connection 和 passive budget check。
- 实现 gear role / stat priority / resistance / attribute local search。
- 实现 budget / craft realism scoring 和 price freshness caveat。
- 实现 `StagePlan` / progression assumptions / stage caveats。
- 输出 unresolved constraints、infeasible reasons 和 searched constraint summary。
- OR-Tools 仅在 spike 证明可用和有收益后引入。

### P5.6 PoB / Judge / Failure Audit

- 生成 BuildSnapshot safe reference。
- 导入 PoB 并运行 Judge advisory。
- 把 Judge 输出转换成 `FailureAuditPacket`。
- 记录 `ToolFeedbackEvent`，区分真实失败、工具误判、Judge modelability gap 和 source gap。
- 确保 Agent audit 不能覆盖 hard blocker，只能提出 evidence-backed 复核或工具反馈。

### P5.7 Internal retry

- 支持 1-2 轮 bounded retry。
- Retry 输入是 sanitized failure audit 和 candidate summary，不包含 raw PoB/XML。
- Retry 不写 reward memory，不做 Phase 7 rollback。

### P5.8 Candidate selection

- 对多候选生成 `CandidateSelectionReport`。
- 记录 rejected candidates、selected candidate、tie-break policy 和 unresolved caveats。
- limited evidence 候选可以被选为当前方向，但必须保留 limited / reward-ineligible caveat。

### P5.9 Final package gate

- 对 `BuildCandidatePackage` 运行 final safety / freshness / completeness gate。
- 确认 package 只暴露 local opaque snapshot id、source hash 和 sanitized summary。
- 未通过 final package gate 时输出 safe incomplete summary 或进入 bounded retry。

### P5.10 Benchmark 和人工验收

- 固定 5-10 个 BuildBrief。
- 对比 no-memory baseline、memory-assisted Architect、memory + planner + Judge feedback。
- 人类 review 检查路线是否有实际 BD 设计价值。

## 验收

- `/poe-bd-create` 可以从模糊自然语言请求生成结构化 `BuildBrief`。
- `BuildBrief`、context、candidate package 都带 version / freshness / snapshot context。
- `ArchitectGenerationPacket` 和 accept flow 不包含 raw/copyable/evaluator-only material。
- `BuildBriefDraft` 和 durable reports 不保存 hidden chain-of-thought、raw transcript 或 scratchpad。
- Agent 能输出多候选 `CandidateDesignSpace`，而不是单一路线。
- BuildPlan gate 能拒绝 raw/copy、不解析 endpoint、ambiguous 硬选和 schema 错误。
- Deterministic completion 能补全并校验 support、Spirit、passive budget、gear requirements、
  attribute / resistance constraints。
- Budget / craft realism 和 price source 缺口会进入 scoring 或 caveat。
- lifecycle / 开荒请求至少输出 `StagePlan`、progression assumptions 和 stage caveats。
- PoB import / Judge advisory 能产出 safe `BuildSnapshot` 和 `FailureAuditPacket`。
- Judge 失败会被核验，但 Agent 不能自行覆盖 hard blocker。
- Internal retry 能在固定失败样例上改善合法性或明确停止原因。
- 多候选输出有 `CandidateSelectionReport`，能解释选择和拒绝原因。
- 最终 `BuildCandidatePackage` 通过 final safety / freshness / completeness gate。
- Memory-assisted generation 在固定 BuildBriefs 上优于 no-memory baseline，至少体现在合法率、
  context relevance、transition gate / caveat 覆盖和人工 review 质量。
- 输出不包含 raw PoB code、raw XML、完整装备表、完整天赋路径、完整 gem/support links、
  raw account / character details、完整 URL、hidden chain-of-thought 或 raw transcript。

## 验证

Generation benchmark 指标：

- BuildBrief interpretation quality；
- freshness / version context completeness；
- candidate design diversity；
- resolver-backed endpoint rate；
- BuildPlan acceptance / rejection correctness；
- creator-visible / planner-visible split enforcement；
- PoB import rate；
- hard legality pass rate；
- capped resistance rate；
- Spirit validity rate；
- passive budget validity；
- support plan validity；
- attribute validity；
- budget / craft realism caveat correctness；
- stage plan / progression caveat completeness；
- Judge caveat correctness；
- failure audit correctness；
- internal retry improvement rate；
- candidate selection explanation quality；
- final package gate pass rate；
- memory-assisted vs no-memory uplift；
- copy-safety pass rate；
- human review pass rate。

Focused tests：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_phase5_generation_models.py -q
.\.tools\uv\uv.exe run pytest tests/test_phase5_brief_interpreter.py tests/test_phase5_build_plan_gate.py -q
.\.tools\uv\uv.exe run pytest tests/test_phase5_completion.py tests/test_phase5_failure_audit.py -q
.\.tools\uv\uv.exe run pytest tests/test_phase5_generation_benchmark.py -q
```

阶段级验证：

```powershell
.\scripts\verify.ps1 quick
```
