# PoE2 BD Creator 数据结构合同

最后更新：2026-07-10

本文档在产品层定义核心 artifact contracts。精确字段校验应放在代码和测试里。

## BuildBrief / AgentRefinedBuildPrompt

用户/请求侧的生成约束。Phase 5 原型中，程序不再用固定规则生成 `BuildBrief`；
`BuildBrief` 只作为 Agent 可选择使用的结构化需求摘要概念。当前代码落地的 P5.1 合同是
`AgentRefinedBuildPrompt`，由外部 Architect Agent 产出。

必要概念：

- goal 和目标玩法；
- lifecycle stage：本次输出/生成的阶段；
- target lifecycle stage：设计时必须考虑的完整生命周期目标；
- cross-stage locked dimensions：当前只允许 `class`，表示开荒、攻坚、终局之间可以换升华、
  技能、天赋、装备和 support，但不能换职业；
- economy mode：`trade`、`ssf`、`league_start`、`unknown`；
- budget model：`low`、`medium`、`high`、`minmax`、`user_defined`、`unknown`；
- price source status：`fresh`、`stale`、`unavailable`、`unknown`；
- target scene：`mapping`、`bossing`、`hybrid`、`campaign`、`league_start`、`endgame`、
  `unknown`；
- preferred/required/forbidden skills、classes、mechanics、items；
- weapon state mode：`single_state`、`dual_state_requested`；
- leveling 和官方 `.build` export requirements。

Phase 5 P5.1 当前要求：

- `AgentRefinedBuildPrompt` 保存用户需求安全摘要、Agent 改写后的设计提示词摘要、字段来源、
  默认假设、追问事项、未决项和 version / freshness context；
- 公开 JSON 字段使用 `currentOutputStages` 这类驼峰形式；内部测试或代码也可以使用
  `current_output_stages` 这类蛇形形式，helper 必须同时接受；
- 不保存 raw request、完整 raw transcript、raw dialogue、hidden chain-of-thought、raw scratchpad
  或中间推理日志；
- 解释性字段必须包含 field source 标记：`user_explicit`、`agent_inferred`、`defaulted` 或
  `unknown`；
- 必须包含 freshness context：league / ruleset、game patch、passive tree version、PoB version /
  commit、graph snapshot id 和 research memory ref；
- `targetLifecycleStages` 必须覆盖 `currentOutputStages`；当用户只要求当前开荒输出但明确提出
  后期洗点/攻坚/终局目标时，`currentOutputStages` 可以只含当前阶段，`targetLifecycleStages`
  必须保留未来目标，供 Architect 选择职业和机制方向；
- `crossStageLockedDimensions` 当前只能是 `["class"]`。

## BuildPlan

如果后续继续使用 `BuildPlan` 这个名称，它只表示 Architect Agent 产出的结构化设计摘要或
候选构筑说明，不是交给程序自动补完整 BD 的任务单。Phase 5 原型不强制使用这个重型名称，
可以优先使用更轻的候选摘要和人工验收材料。

必要概念：

- archetype 和 reusable principle；
- class 和 ascendancy；
- main skill 和 support intent；
- passive anchors，而不是完整 passive paths；
- gear roles，而不是复制来的完整装备表；
- defense layers；
- sustain plan；
- Spirit budget 和 reservation plan；
- state A / state B assumptions；
- leveling milestones；
- modelability caveats。

如果后续重新引入 `BuildPlanProposal`，它也只能表示 Agent 对某个候选路线的结构化说明，
不能表示程序接管后的自动补全输入。它必须：

- 引用 resolver-backed components 和 Phase 4 used ids；
- 表达 passive anchors、support intents、gear roles、Spirit / reservation assumptions 和
  state assumptions；
- 包含 `StagePlan` / progression assumptions / stage caveats，至少覆盖 `BuildBrief` 要求的
  lifecycle stage；
- `StagePlan.transitionGates` 可以表达平滑过渡点，也可以表达洗点、换技能、换装备或换升华后
  的转型门槛；职业仍受 `crossStageLockedDimensions=["class"]` 约束；
- 禁止输出 raw PoB code / XML、完整 passive path、完整装备表或完整 gem/support links；
- 禁止把 advisory research context 当成 hard legality，或把单样本 observation 说成 common
  pattern。

## BuildSnapshot

用于评估的具体候选状态。

必要概念：

- snapshot id；
- PoB XML/code hash 或本地 opaque reference；
- 可选官方 `.build` draft reference；
- class、ascendancy、level、main skill；
- passive point usage；
- weapon state mode；
- generated/loaded source；
- freshness claims。

Phase 5 的 `BuildCandidatePackage` 只能暴露 local opaque snapshot id、source hash 和 sanitized
summary。PoB import/export material 只能作为 transient runtime artifact 存在于本地 opaque
reference 后面，不能进入 durable report、普通聊天输出或 creator-visible artifact。

## Phase5Generation

Phase 5 当前采用 Agent 主导的轻量原型合同。这里的“合同”只约束安全摘要、工具边界、评估
证据和人工验收材料；不定义“Agent 出方案，程序自动补完整 BD”的流程。

当前核心产物：

- `GenerationRunContext`：每次 `/poe-bd-create` 请求的一次性运行绑定，包含本次 `runId` 和随机
  `runToken`。它由 `start-run` helper 生成，只用于防止旧候选、旧临时 JSON 或其他运行产物冒充
  本次结果；成功生成 `HumanReviewPacket` 后立即失效。
- `AgentRefinedBuildPrompt`：Agent 对用户自然语言需求的更具体设计提示词或最小 `BuildBrief`
  摘要。它可以保存用户目标摘要、字段来源、默认假设、需要追问的问题和版本上下文；不能保存
  模型隐藏思维链、完整对话记录、草稿推理区或未经清洗的原始提示词。
- `PrototypeBuildCandidate`：Agent 产出的候选 BD 安全摘要。至少表达当前输出阶段、完整生命
  周期目标、职业壳、跨阶段职业硬锁、主技能/辅助技能意图、机制和伤害缩放轴、防御层、
  Spirit / 保留资源假设、装备角色、词缀方向、天赋锚点或区域意图、转型门槛、未解决注意事项
  和使用过的工具/记忆引用。普通模式还必须带 `ResearchMemoryUse`：记录真实
  `dedupeQueryRef`、定向查询使用的 stable component keys、命中的 Build Family / 深度记录 /
  pattern / semantic edge，以及每条研究结论被采用、保留或拒绝后如何影响候选。无匹配可以显式
  记录 `no_matching_memory`，不能用空泛工具调用冒充记忆已参与设计。
- `TransientBuildStateRef`：由 `evaluate_generation_candidate` 从真实活动 PoB 快照生成的临时
  构筑状态引用；对外和持久报告里只能出现不透明本地引用、摘要和安全 hash，不能
  展开 PoB 导入码、原始 XML、第三方成熟 BD 的完整装备表、完整天赋路径或原始技能连接。
  当状态为 `available` 时，必须包含 `testedSkillGroups`，记录 Agent 实际测试的技能组编号、职责、
  全部主动技能及数量、辅助技能和启用状态，使蓝耗、Spirit、伤害和可建模性结论可复核。
  `mainSocketGroup` 只标记 PoB 当前计算组，不声明整个 BD 只有一个主技能。
- `JudgeAdvisoryReport`：Phase 1 Judge 生成的参考评估。它表达硬阻断、分数、证据等级、可建模
  注意事项和失败原因；可信报告还应提供 Judge 实际选择的技能、选中技能组的安全插槽诊断和
  属性缺口摘要，使 Agent 与人工能定位硬阻断。条件性内部效果作为 supplemental component 单独
  记录，不能因没有普通宝石插槽被判非法。`offenseEvidence` 保存脱敏的 raw/effective DPS、
  direct/full 诊断、阶段 floor 进度、evidence level 与 delivery status；`rewardLimitReasons`
  显式说明有限证据、partial modelability 或其他真实证据限制为什么不能产生 strong reward；
  lifecycle stage 本身由 `levelBand` 表达，不自动成为 reward limit。它不是
  机制真值，也不替代 Agent 的失败核验。
- P5.1 人工验收包里的 `JudgeAdvisoryReport` 只保留安全参考信号：Judge 出错时不能携带分数
  或奖励强度；成功评估的分数必须在 0 到 1 之间，并且必须带 `evaluatedSnapshotId` 和
  `evaluatedSourceHash` 以绑定对应 `TransientBuildStateRef`；P5.1 不透出 `strong` 奖励信号，
  避免把原型人工验收包误用成奖励记忆输入。
- `evaluate_generation_candidate` 在独立 Judge 引擎里复评不可变快照，并将安全结果作为可信凭据
  绑定到 `runId` 和 `candidateId`；Judge 调用本身发生错误时使用 `error`，必须带受限
  `errorCode`，并且不能携带构筑 `hardFailures`。`trustedEvaluationScope` 固定为
  `snapshot_and_judge_only`，`versionContextTrusted=false`；这表示程序签住快照和 Judge 结果，
  不表示调用者传入的赛季、补丁、图或记忆版本已经获得程序签名。
- `HumanReviewPacket`：供人工验收使用的安全报告。至少包含用户需求摘要、Agent 改写后的提示词
  或 `BuildBrief` 摘要、候选 BD 摘要、使用过的查询和工具引用、Judge 状态、硬阻断、注意事项、
  人工评分字段和是否建议进入下一阶段。`lifecycleEvidenceCoverage` 只根据最终可信 snapshot
  标出至多一个 `evaluatedStage`，其余候选声明阶段进入 `textOnlyStages`，不得把一轮 Judge
  误写成完整生命周期验证。
- `ToolFeedbackEvent`：开发/验收反馈，用于记录 Judge/工具无法评估、误判、覆盖缺口或接口难用；
  它不自动调整 graph / memory 权重，不自动放宽安全边界，也不自动改变工具行为。
- `FailureAuditSummary`：Agent 对某一轮 Judge 结果的可审查结论摘要，绑定本轮候选编号和快照编号，
  只记录失败分类、重试/停止/接受决定、计划改动、保留注意事项和停止原因；不能保存逐步推理。
- `GenerationAttemptRecord`：同一个生成运行中的一轮不可变评估记录，包含本轮 Agent 候选安全
  摘要、可信临时状态引用、可信 Judge 报告和 `FailureAuditSummary`。轮次从 0 开始，最多为 2；
  非最后一轮必须明确选择继续重试，最后一轮必须接受或说明停止原因。Agent 文件可以只提交
  attempt index、candidate 和 failure audit；helper 从连续、严格校验的本 run trusted receipts
  补全 state/Judge。显式提交可信字段时仍必须逐字段匹配 receipt。
- `RetryComparisonReport`：P5.2 才需要的有限内部重试对比报告。它只比较同一用户请求下的安全摘要、
  Judge 结果和人工可审查差异，不写奖励记忆，不做长期进化式学习。

P5.2 研究记忆对照不新增持久对照报告。现有创建入口支持 `--no-memory`：普通模式必须渐进查询
研究记忆并填写 `ResearchMemoryUse`；无记忆模式禁止调用研究记忆、禁止填写该结构，但保留其他
全部工具。人工用同一请求分别运行两种模式并直接审查结果；程序不自动宣布胜负。

P5.1 证据可信度边界：

- `ToolReference` 仍是 Agent 报告的查询引用；`TransientBuildStateRef` 和
  `JudgeAdvisoryReport` 必须来自本次可信评估凭据；
- helper 必须核对运行编号、候选编号、快照编号、来源 hash 和完整安全报告；缺失或被 Agent
  改写时拒绝生成 `HumanReviewPacket`；
- 可信 Judge 完成且没有硬阻断时可以使用 `ready_for_human_review`。该状态只表示材料可以交给人
  判断，不表示人已经接受候选，也不表示 Judge 是绝对强度裁判；
- `get_freshness_report` 引用是运行流程完整性要求，用于发现 Agent 明显跳步，不是可信调用回执。
  版本上下文仍需人工结合本次 freshness 返回核验，不能仅凭 `trustedEvaluation=true` 宣称当前赛季
  已验证。

旧重型合同状态：

- `ArchitectResearchContextForGeneration`、`ArchitectGenerationPacket`、`CandidateDesignSpace`、
  `BuildPlanAcceptanceReport`、`PlannerCompletionResult`、`CandidateSelectionReport`、
  `BuildCandidatePackageAcceptanceReport` 和完整 `BuildCandidatePackage` 属于上一版重型设计的参考
  材料，当前主线不要求实现。
- 如果后续真实失败样例证明需要重新引入其中一部分，也必须按当前方向改造：Agent 仍负责查询、
  创造、临时状态搭建策略和失败修正；程序只提供工具调用、安全边界、Judge 执行和报告封装。

安全边界：

- 每次生成必须先建立新的 `GenerationRunContext`；内部产物的 `runContext`、`packetId`、
  `promptId` 和 `requestRef` 必须与本次运行清单一致，且只能从 helper 根据 `runId` 定位的本次
  运行目录进入；调用者不能给 helper 指定其他运行清单或 Agent 产物路径；
- 成功验收的运行只能消费一次。历史 `agent-output.json`、`.tmp_agent_output_*`、旧人工验收包和
  旧候选不能作为新请求的输入；未消费运行两小时后过期；
- 同一运行在最终验收前可以写入初始评估和最多两次重试评估。每轮可信凭据独立保存且不可覆盖，
  `trusted-evaluation.json` 只作为最新一轮兼容指针；最终 helper 必须逐轮核对 Agent 提交的
  `generationAttempts` 与可信凭据；
- `start-run` 初始化已绑定 run/prompt/packet 的最小 `agent-output.json`；`validate-output` 可在不
  消费运行的情况下重复执行 canonicalization、schema、domain 与 retry 校验；`review-packet
  --compact` 仍原子写入完整 review result，只缩短 stdout；
- canonicalization 前先扫描原始 Agent 文件，之后 fail-closed 校验 receipt 连续性、最新指针与
  typed state/Judge，再补全可信字段并重新执行安全检查；不能用 hydration 隐藏原始危险字段；
- 所有 schema 使用 strict typed models，不接受开放 `Dict[str, Any]` 作为持久合同；
- 所有 durable artifact 必须带 version / freshness / snapshot context 和 no-raw-material safety
  flags；
- 原型报告的 version context 必须覆盖用户需求摘要、候选摘要、临时状态引用、Judge 报告和人工
  验收材料；
- `PrototypeBuildCandidate` 必须说明它覆盖的是哪个当前输出阶段；未来阶段目标可以先进入转型
  门槛、默认假设和注意事项；
- `TransientBuildStateRef` 的 graph snapshot id / PoB version / source hash 必须与 Judge 报告对齐；
- 所有接触共享 PoB 构筑状态的计算工具必须串行；部分优化/测量工具内部会临时修改再恢复状态，
  不能按工具名称判断为只读。只有不接触共享构筑状态的静态资料查询可以并行；
- 用户可见报告必须区分 Agent 的设计判断和 PoB/Judge 工具验证结论；
- `HumanReviewPacket.recommendedNextAction`：可信 Judge 完成且没有硬阻断时使用
  `ready_for_human_review`；Judge 执行错误使用 `human_review_required`；构筑硬阻断使用
  `blocked_by_hard_failure`；
- Judge `error`、PoB 导入失败、硬阻断或无法搭建临时状态时，不能输出成“已验证
  候选”；只能输出安全的不完整摘要、失败原因和人工复核材料；
- 输出安全检查必须确认报告不包含 raw PoB code、raw XML、第三方成熟 BD 的原始完整材料、
  raw account / character details、完整 URL、hidden chain-of-thought、transcript、dialogue 或
  raw transcript；Agent 自己生成并实际测试的 `testedSkillGroups` 不属于第三方原始材料。
- 可选导出就绪摘要只能表达“是否可能进入 Phase 6 导出”和不支持项，不能伪装成已经完成官方
  `.build` 导出。

## BuildEvaluation

对单个 snapshot 的 deterministic judge 输出。

必要概念：

- pass/fail；
- score scale：当前 Judge v6 使用 `0_to_1`；
- score vector：当前最小实现包含 offense、defense、recovery、mobility；physical-invalid 时
  这些维度必须标记 blocked；
- score breakdown：每个维度应说明 raw value、hard floor、quality floor、target、
  source metric 和 caveats；
- judge selected skill：当 PoB/poe.ninja 导入的当前主技能只是 buff、战旗或辅助状态时，
  Judge 可以使用 `judgeSelectedSkill` 暴露实际用于 offense 评分的技能摘要；只能包含技能名、
  group index、source metric、projectile count 和 caveats，不能输出完整 gem/support links；
  如果 source metric 是 `FullDPS`，必须标记为 socket-group rollup，而不是单技能精确 DPS；
- offense evidence：`scoreBreakdown.offense` 必须包含 `provenance` 与 `evidenceLevel`。
  `direct_pob_dps` 可以是 strong evidence；`isolated_full_dps_rollup` 和
  `minion_pob_output` 默认只能是 limited evidence；无可用 DPS 时使用
  `unknown_or_unavailable` / `none`。同时保留 `sourceMetricDetail`、`skillName`、
  `skillGroupIndex`、`isMinion`、`activeSkillCount`、`activeMinionLimit`、`rawDps`、
  `effectiveDps` 和 caveats，避免把 PoB 原始读数、数量修正和最终评分输入混在一起；
- weapon check：`judgeSelectedSkill` 和主技能摘要可以包含 `weaponCheck`，仅暴露技能名、
  PoB weapon requirements、当前装备武器类型、兼容状态和 PoB `disableReason`。当
  `disableReason` 显示技能被当前武器禁用时，必须产生 `incompatible_weapon_skill_tags`；
  不允许用 Python 技能名表替代 PoB 兼容性判断；
- scenario fit：当前作为展示型 mapping/bossing/hybrid fit，不参与 aggregate；
- aggregate score：必须包含 weight profile；当前 `judge_v6_evidence_separated` 保留现有阶段权重：
  campaign 为 0.35/0.30/0.20/0.15，maps-entry 为 0.375/0.35/0.175/0.10，endgame 为
  0.40/0.40/0.15/0.05；
- quality band：`invalid`、`barely_playable`、`prototype_only`、`entry_endgame`、`solid`、`strong`；
- 四层结果合同：`hardFailures` 仅表示确定性非法并决定 legality pass；
  `playabilityFailures` 表示合法但严重不可玩短板；`qualityWarnings` 表示未达到推荐质量目标；
  `modelability` / `scoreApplicability` 表示 PoB 数值是否可用于结论；
- legality diagnostics：至少包含 `passiveBudget` 和 `weaponSetBudget` 的 used、available、
  over 信息；诊断用于解释 hard failure，不能把超预算自动降级为合法；
- PoB-computed metrics；
- resistance、Spirit、attribute、support、weapon、weapon/skill tag、passive-budget checks；
- legality failure codes：attribute_requirement_unmet、passive_budget_exceeded、
  attack_skill_without_weapon、incompatible_weapon_skill_tags、spirit_budget_exceeded、
  invalid_class_ascendancy_pairing、invalid_socket_setup、support_limit_exceeded、
  duplicate_support_gem、invalid_support_gem、illegal_equipped_item_affixes；
- playability failure codes：`severe_elemental_resistance_shortfall`、
  `below_playability_floor`、`catastrophic_defense_shortboard`；
- quality warnings：`elemental_resistance_below_cap`、`negative_chaos_resistance`、各 offense / Max Hit
  quality target miss，以及生成候选 offense delivery evidence 为 limited/unavailable 时的
  `offense_delivery_not_established`；后者限制综合档位和最终交付，但不属于确定性非法。strong
  direct DPS 低于地板时使用 `below_playability_floor`，不复用 delivery warning；
- DPS 语义遵循 PoB：`AverageDamage` 是平均命中，`TotalDPS` 是 Hit DPS，`CombinedDPS` 加入当前
  技能的已建模次级/持续伤害，`FullDPS` 汇总被纳入的 skill actors/groups；
- short-circuit state：physical-invalid failure 必须标记被 blocked 的 score dimensions；
- reward eligibility：熔断 evaluation 不能产生 positive reward；
- reward strength：`BuildEvaluation` / `BuildComparison` 使用 `rewardStrength` 区分
  `strong`、`limited` 和 `none`。只有 strong 才能被后续 Phase 8 作为强 reward memory
  消费；limited 只允许作为观察或弱信号；
- 非终局空升华：campaign / maps-entry 样本缺失 ascendancy 可以追加
  `missing_ascendancy_non_endgame_caveat` 并继续评估；endgame 样本缺失 ascendancy 仍是
  `invalid_class_ascendancy_pairing`；
- recovery 主池：生命侧使用 `LifeUnreserved`，不是 `Life`；`Life`、`LifeReserved` 和
  `LifeUnreservedPercent` 仅用于诊断和 fallback；
- CI：`Chaos Inoculation` 以 build keystone readback 为权威；CI 下 chaos score 直接按混沌
  免疫处理，不使用 `ChaosMaximumHitTaken` 的 nil/0/超大值反推；
- source hash：真实样本验收只输出 hash，不输出 raw source；
- reproducibility：至少包含 evaluator version、tree version、latest tree version；版本不一致时
  必须追加 `version_mismatch_caveat`；
- state evaluations：single-state 时一个 active state，dual-state 时分别记录 state A/state B
  的 metrics、hard checks 和 caveats；
- defense model：`BuildEvaluation.defenseModel` 是诊断层，不直接替代 defense score。
  `poolModel` 至少覆盖 `life`、`low_life`、`es`、`ci`、`mom`、`eb_mom_mana`、`ward`、
  `hybrid`、`unknown`；`hitMitigationModel`、`avoidanceModel` 和 `sustainModel` 只能解释
  PoB 已读出的防御层，不得把高闪避、高格挡或高 EHP 自动洗白为可承受一击；
- modelability status；
- limited evidence：缺少关键 PoB 指标、primary pool 不可得或 partial modelability 时，evaluation
  可以用于 selection，但 `rewardEligible` 必须降为 `limited`，不能作为 strong reward 写入学习；
- limited offense evidence：`projectile_overlap_unverified_caveat`、
  `minion_dps_unverified_caveat`、
  `minion_count_multiplier_caveat`、`full_dps_rollup_caveat` 等 caveat 必须限制 reward，
  但不应阻止单个 BD 的 selection / 诊断评分；
- dual-state limited evidence：Phase 1 如果检测到 weapon set passive usage，但尚未分别计算
  State_A / State_B，必须追加 `dual_weapon_state_limited_caveat` 并将 reward 降为 `limited`；
- compute failure：`pob_compute_failed` 可以输出 sanitized `errorKind`，不能输出 raw import
  text、raw XML、完整异常 detail 或路径化敏感材料；
- evidence tags；
- 不包含 copied reference build material。

## BuildComparison

Candidate vs reference 或 candidate vs prior round。

必要概念：

- compared snapshot ids；
- metric deltas 和 score-vector deltas；
- legal-state deltas；
- reference placement；
- structured gaps；
- selection winner：`candidate`、`reference`、`prior`、`tie`、`unknown`；
- reward winner：`candidate`、`reference`、`prior`、`tie`、`unknown`；
- scenario / active-state comparison policy；
- comparability/status：`comparable`、`limited_evidence`、`partial_modelability`、
  `level_band_mismatch`、`candidate_invalid`、`reference_invalid`、`both_invalid`、`incomparable`；
- incomparable reason：例如 core_mechanic_not_modelable、missing_metric、different_active_state_policy；
- `levelBand` 不同的 evaluation 不直接比较 aggregate，也不产生 selection/reward winner；这表示
  比较合同不成立，不是对 campaign / maps-entry 构筑本身扣分；
- reward eligibility：full comparable 才能进入 strong reward；partial modelability 只能进入
  limited reward；非法或 core-unmodelled comparison 不进入 reward memory；
- limited evidence comparison：如果任一方只有 limited evidence，可以给出
  `selectionWinner`，但 `rewardWinner` 必须是 `unknown`，`rewardStrength=limited`，防止把
  FullDPS rollup、召唤物数量近似、投射物下界或关键指标缺失写成强学习信号；
- modelability limitations。

## ResearchPacket

外部 Researcher Agent 输入。

必要概念：

- safe metadata；
- quarantine-only raw context；
- 可用时包含 judge output；
- physical graph context；
- freshness evidence；
- copy-safety rules；
- requested clean output schema。

## CleanFragment

可持久化的结构化研究知识。它可以包含完整核心机制包，但不能包含原始导入材料或第三方整角色
镜像。

必要概念：

- fragment type；
- reusable principle；
- source case refs；
- confidence；
- copyability risk；
- lifecycle stages；
- modelability；
- verification tasks。

## BuildDesignObservation

Phase 4.5 的成熟 BD 设计观察中间层。它用于先记录“这个 BD 为什么成立”，不急着把所有
内容图化为 semantic edge。

必要概念：

- observation type：build archetype、cooccurrence、transition gate、failure pattern、
  Agent 设计提示或 modelability caveat；
- title / summary；
- BD 设计轴：identity、character shell、primary / secondary skill package、passive tree
  shape、itemization、scaling axis、resource / Spirit engine、defense layers、mechanic chain、
  rotation / playstyle、transition gates、failure modes、variant relations、modelability caveats；
- components：每个 component 必须是 resolver-backed stable key，并带 role，例如
  primary_damage、clear_skill、boss_skill、generator、payoff、reservation、defensive_buff、
  ascendancy_shell、movement、trigger_host、support_modifier、unique_enabler、transition_gate、passive_anchor、
  keystone_transformer、gear_base、weapon_base、scaling_stat、defense_layer、resource_engine；
- `ascendancy_shell` 只表示 resolver-backed 职业/升华壳，用作 Agent 设计参考上下文；
  不代表完整升华点路径，也不是 hard legality。具体升华 notable / keystone 若作为机制锚点，
  必须单独用 `passive_anchor` / `keystone_transformer` 组件并携带 resolver evidence；
- source case refs 和 safe evidence refs；
- game patch、passive tree version、PoB version/commit；
- visibility / split / knowledge scope；
- 不包含 raw PoB code、raw XML、账号角色信息，或由全部装备槽、整棵已分配天赋、全部技能组和配置
  组成的第三方整角色镜像；允许保存关键技能与辅助组合、局部核心天赋连接和跨组件机制包。

## BuildPattern

Phase 4.5 从多个 BuildDesignObservation 或样本中聚合出的 Agent 可见设计参考模式。

必要概念：

- pattern type：BuildArchetypePattern、CooccurrencePattern、TransitionGate、FailurePattern、
  PlannerHint；
- component keys 和 component roles；
- confidence tier：case_observation、recurring_observation、likely_pattern、
  common_within_archetype、strong_ranking_hint；
- `transfer_scope`：`family`、`component` 或 `global`。`family` 表示只在来源 Build Family 内使用；
  `component` 表示该 Family 知识同时具备带明确条件的跨 Family 迁移资格，而不是脱离 Family 或在
  来源 Family 内降权；`global` 只接受静态事实/流程规则或独立 review，单成熟案例不能直接声明；
- 可迁移 pattern 保存 `applicability_axes`、`applicability_requirements`、
  `exclusion_conditions`、`transfer_rationale` 和 `origin_family_keys`。缺少最低条件、排除条件、验证任务
  或来源 Family 的 component 候选不得入库；
- sample count、family count、source diversity count 和可选 denominator；
- typed context requirements；
- Agent 设计提示和 verification tasks；
- patch/tree/PoB version、visibility/split/scope、status、copy-safety state、current version context；
- pattern 必须由同批、同 visibility/split/scope/version 且完整覆盖 component keys 的
  `BuildDesignObservation` 支撑；patch decay 后进入 `needs_revalidation` 并移出 Agent 可见
  context，复核仍有效时才能恢复；
- 所有 pattern 都是 advisory research context，不能替代 Phase 2/3 hard source facts、
  support/socket legality、Phase 5 Agent 设计判断或 Phase 1 Judge。
- 单案例新 pattern 始终从 `case_observation` 开始。结构身份相同的 component pattern 只有获得两个
  独立 Family 的证据后才能晋升为 `recurring_observation`；达到多样来源要求后最多晋升为
  `likely_pattern`。`common_within_archetype` 与 `strong_ranking_hint` 仅用于 Family/Archetype 内部，
  不能赋予公用知识跨 Family 强排序权。
- component pattern 只保存一条记录，并通过 `origin_family_keys` 建立双重召回：来源 Family 内进入
  `buildPatterns` 且使用 Family 权重，其他 Family 才进入较低权重的 `transferablePatterns`；同次查询
  不得在两个通道重复返回。

## GraphNode

Physical 或 semantic knowledge node。

必要概念：

- node id 和 stable key；
- node type；
- display name 和 aliases；
- source 和 source file；
- game patch、passive tree version、PoB version/commit；
- status：`valid`、`deprecated`、`nerfed`、`unknown`、`needs_revalidation`；
- confidence；
- 适用时包含 official IDs。

## GraphEdge

已存在节点之间的关系。

必要概念：

- edge id；
- source node id；
- target node id；
- edge type；
- evidence refs；
- game patch、passive tree version、PoB version/commit；
- status；
- confidence；
- weight（semantic / reward edges 使用；source-backed physical edge 可以为空或固定默认值）；
- modelability。

Semantic edges 必须在两个 endpoint nodes 都能 resolve 后才能创建。

## GraphToolInput

Phase 3 typed graph tools 的通用输入外壳。所有 graph tool 都必须使用 typed payload，不能把
raw Cypher / Gremlin / SQL 作为字符串传入。

必要概念：

- tool name / query family；
- typed payload；
- optional `GraphToolContext`；
- context policy：`none`、`version_only`、`item_context`、`socket_context`、
  `passive_context`、`build_state_context`；
- snapshot selection：latest 或 explicit snapshot id；
- result limits：例如 hop limit、node limit、candidate limit；
- no-raw-query guarantee。

Context policy 由工具声明，而不是由 agent 自由猜测。缺少必需 context 时，工具必须返回
`status: "missing_context"` 和 `missingContext` 字段，不能用默认值伪造状态化结论。
输入 schema 必须拒绝 raw query 字段，例如 `raw_query`、`query_string`、`cypher`、`gremlin`
或 `sql`。schema validation failure 不能把 Pydantic traceback 或 Python stack trace 暴露给
agent；必须转换为 public error envelope：`status: "error"`、`errorCode: "invalid_schema"`、
`noRawQuery: true` 和可读 caveat。

## GraphToolContext

状态化 graph query 的可选上下文。它不是完整 BuildSnapshot，也不能替代 PoB/Judge；只用于
让 graph tools 明确自己回答的是哪个静态/半静态场景。

可用字段：

- discriminator：`context_type`，必须显式传入；Pydantic 使用
  `Field(discriminator="context_type")` 解析 union；
- version context：game patch、passive tree version、PoB version / commit；
- ruleset context：league、ruleset、lifecycle stage、level/stage label；
- character context：class、ascendancy、level；
- item context：item level、item base key、domain、tags、rarity、slot；
- socket context：skill key、support keys、current support count、max support count、
  duplicate policy、socket group kind；
- passive context：start node、target node、active weapon set、allocated passive keys、
  weapon set point budget、normal point budget、hop / node limits；
- build-state context：current attributes、Spirit / reservation summary、equipped weapon types、
  relevant caveats。

不同 query family 只能读取自己声明需要的 context slice。工具返回值必须说明 `contextUsed`；
如果输入上下文不足或与 snapshot/version 冲突，必须返回 `status: "missing_context"`、
`missingContext` 或 `contextCaveats`。
当前 context discriminator 取值为：`version_context`、`item_context`、`socket_context`、
`passive_context`、`build_state_context`。

## GraphResolveResult

Phase 3 typed graph tools 的通用 resolve 结果。

必要概念：

- component display name / alias / typed query payload；
- snapshot id；
- status：`resolved`、`missing`、`ambiguous`、`unsupported`、`stale`、`error`；
- resolved stable key；
- resolved node type；
- display name；
- aliases matched；
- candidates（仅在 ambiguous 时返回安全摘要）；
- confidence；
- caveats；
- source refs。

Resolver 可以接受玩家可读的 component name、alias 或 typed payload；不能接受 raw Cypher /
Gremlin / SQL，也不能把原生图查询字符串包装成普通文本。

## GraphQueryResult

Phase 3 read-only typed graph query 的通用结果外壳。具体 fact payload 由工具类型决定，但外
层字段必须稳定。

必要概念：

- tool name / query family；
- typed input echo（只回显安全、非 raw query 的输入）；
- snapshot id；
- status：`known`、`unknown`、`ambiguous`、`unsupported`、`stale`、`missing_context`、`error`；
- resolved subject / object stable keys；
- structured facts；
- evidence path；
- provenance / source refs；
- confidence；
- caveats；
- `contextPolicy`；
- `contextUsed`；
- `missingContext`；
- `contextCaveats`；
- freshness / version context；
- no-raw-query guarantee。

Graph tools 不能返回 raw Cypher / Gremlin / SQL，也不能把 raw graph rows 当作 public
contract。不存在的 endpoint、unsupported official ID 和 ambiguous alias 必须结构化返回，不能
静默创建或猜测事实。

## GraphEvidencePath

用于解释一个 graph answer 为什么成立。

必要概念：

- snapshot id；
- nodes；
- edges；
- computed fact ids；
- source refs；
- source status；
- confidence；
- caveats；
- patch / passive tree / PoB version context。

Evidence path 只解释 source-backed 或 computed fact 链路，不暴露可复刻成熟 BD 的 raw source
材料。

## GraphToolError

Phase 3 typed graph tools 的结构化错误合同。错误必须可解释、可测试，不能把 Python traceback
或 raw graph backend error 暴露给 agent。

必要概念：

- status：`missing_context`、`ambiguous`、`unsupported`、`stale`、`error`；
- error code；
- message；
- `missingContext`；
- candidate summaries（仅 ambiguous 时返回安全摘要）；
- source refs（如果错误来自 source-backed unsupported/stale 状态）；
- caveats；
- recoverable flag；
- suggested next typed tool（可选）。

`invalid_schema` 是 `errorCode`，不是新的 result status。MCP adapter 和 `GraphQueryService`
入口必须捕获 schema validation error，把未知字段、缺少 discriminator 或错误 context type 转成
结构化 `GraphToolError`。

## GraphToolDeterministicBenchmarkResult

Phase 3 typed graph tool deterministic benchmark 的报告结构。它验证工具确定性、上下文校验、
provenance 完整度和防幻觉能力；不要求和 Phase 4 的 semantic vector / text retrieval 做质量对比。

必要概念：

- benchmark id；
- snapshot id；
- tool families covered；
- case counts by status：`known`、`unknown`、`ambiguous`、`unsupported`、`stale`、
  `missing_context`、`error`；
- expected status match rate；
- provenance completeness rate；
- hallucinated compatibility count；
- missing / ambiguous / unsupported structured-return rate；
- topology macro limits：max tool calls、max nodes、max hops、max payload bytes；
- pass/fail；
- caveats；
- reproducibility context。

Passive topology macro tools 只返回 source-backed static topology。`find_passive_topology_path`
的 path 是纯拓扑最短路径，不计算已分配节点的 0-cost 跃迁、normal/weapon-set 点数预算或最终
build-state allocation legality；这些预算和分配成本属于 Phase 5 的 Agent 构筑过程和 Judge 证据。
Phase 3 path/subgraph
默认上限为 `hop_limit <= 6`、`node_limit <= 200`、payload 不超过 64KB，并在跨 weapon-set
exclusive state 时返回 `unsupported` 与 `conflicting_weapon_set_caveat`。

## Phase4ResearchMemory

Phase 4 research memory 保存外部 Researcher Agent 提交的 clean、typed proposal。这里的 clean 指
不含原始导入材料、账号角色信息和第三方整角色镜像，不表示必须拆散关键技能、辅助、局部天赋或
装备联动。
它不是成熟 BD 模板库，也不是 physical graph fact source。

核心概念：

- `ResearcherOutput`：strict Pydantic schema；旧 `schema_version = 4` 继续兼容，深度提取使用
  `schema_version = 5`，并增加 `DeepResearchRecord` proposals。
- `DeepResearchRecord`：同一案例通过 `research_group_id` 聚合成多条聚焦记录。每条只表达一个主要
  知识单元，保存 title、summary、content、record kind、stable component keys、条件、失败条件、
  safe evidence、版本和作用域。中文 `content` 原则上不超过 400 字，英文原则上不超过 250 个单词；
  只有不可拆分的核心机制链可以携带 `length_exception_reason` 少量超出。
- `BuildFamily`：只由已解析的 `ascendancy_key + primary_skill_key + sorted
  secondary_skill_keys` 确定。clear/boss/triggered-payload，以及在同一技能包/机制链中与载荷成对的
  trigger-host 自动作为核心副技能；普通 secondary 只是 Family 内工具或变体。其他确实定义流派的
  generator/control 等技能通过
  `typed_payload.familyCoreSkillKeys` 显式加入，且必须引用同一研究组已解析的 skill stable key。support、
  暗金、装备、防御和资源方案不参与 Family 身份。
- `Canonical KnowledgeUnit`：`DeepResearchRecord` 通过 `BuildFamily + record_kind + kind-specific
  core component roles` 生成 `knowledge_key`。标题和正文只用于召回与选择更完整的代表文本，不能单独
  授权跨来源合并。`skill_package` 还必须通过 `typed_payload.supportPackages` 保存每个核心技能组的
  support 归属；同一技能、不同辅助包是同 Family 下不同知识单元。结构证据不足时保留原记录，不进行
  猜测性归并。
- `source_specific_random`：Cultivated/mutated 等随机实例依赖写入
  `typed_payload.availability` 和 `sourceSpecificComponentKeys`。它拥有独立知识身份，只用于案例解释；
  默认 Create 召回排除，也不能生成 planner-visible Pattern。
- 无物理图节点的普通资源方式通过 `typed_payload.resourceMechanisms` 保存 lower_snake_case 机制标签，
  例如 `mana_leech`、`mana_flask`。已归入 Family 但不能生成 `knowledge_key` 的记录不得作为 clean
  acceptance 入库，必须补足结构化身份或暂缓。
- `DeepResearchRecordEvidence`：同一 `knowledge_key` 每个 `source_case_ref` 只保存一份安全证据，
  包括该来源观察到的组件、条件、失败条件和版本。重复研究同一 source 只更新时间；新 source 增加
  evidence count，不复制 canonical 正文。
- `CleanFragmentProposal`：机制级可复用原则，必须带 title、summary、reusable principle、
  safe evidence refs、source case refs、confidence、copyability risk、lifecycle、modelability、
  verification tasks、patch/tree/PoB version 和 visibility/split/scope。
- `SemanticEdgeProposal`：只引用已存在 physical graph stable keys；必须带
  `source_resolution` / `target_resolution` resolver evidence、typed `context_requirements`、
  affected component keys、version/status/confidence/modelability 和 copy-safety state。
- `EndpointResolutionEvidence`：来自 `resolve_graph_component` 的紧凑证据，至少包含
  `tool_name="resolve_graph_component"`、`status="resolved"`、`stable_key`、`snapshot_id`、
  `evidence_path_nodes` 和 safe `source_refs`。后端必须复核它与 proposed endpoint stable key
  和当前 graph snapshot 一致；缺失、错配或 stale evidence 必须拒绝。
- `ResearchContextRequirement`：discriminated union，不允许开放 `Dict[str, Any]`。它只复用 Phase 3
  `GraphToolContext` 中可持久化、结构封闭的 `version_context`、`item_context`、`socket_context`
  和 `passive_context`，并补充 research-only 的 lifecycle stage、transition gate、verification
  gate、resource threshold、Spirit reservation、item role、weapon set 和 socket/support 前提。
  Phase 3 graph tool 的 `build_state_context` 可用于瞬时查询，但不能进入 durable research proposal。
- `ResearchFragmentEvidence`：对已有 fragment 追加 safe evidence refs；不能把 evaluator-only /
  holdout / quarantined evidence 追加到 creator-visible fragment。
- `ResearchRevalidationEvent`：patch decay 后的复核结果；`still_valid` 可恢复 `valid`，
  `changed_scope` 需要 successor，旧知识变为 `deprecated` / `stale`。

工程约束：

- SQLite FTS5 tokenizer 必须保留 stable key 冒号：`tokenize="unicode61 tokenchars ':'"`。
- stable key 精确过滤走 indexed metadata / JSON metadata，不只依赖 FTS `MATCH`。
- `synergizes_with` 无向 edge id 使用 canonical JSON payload hash，不能裸字符串拼接。
- directional short-cycle 同步检测上限为 `max_depth=3`。
- rejected proposals 必须幂等 upsert，重复提交只增加 `retry_count`。
- acceptance 必须分别报告 canonical record 的 created/updated 数量和新增 source evidence 数量；
  “本案接受了多少记录”不能再被解释为“数据库新建了多少条知识”。
- `caseCoverage.supports` 只有在每个核心技能组有结构化 `supportPackages` 且至少两个已解析辅助时才是
  `covered`；`passiveAscendancy` 必须包含 ascendancy shell 和绑定到具体已解析升华节点的
  `ascendancyResponsibilities`，普通 notable/keystone 不足以代替。
- 所有 public tool envelope 必须包含 `noRawQuery: true` 和 `noRawMatureBuildMaterial: true`。

禁止输出或持久化：

- raw PoB code；
- raw XML；
- raw account / character / profile URL；
- long copied guide text。

允许持久化：

- 对机制成立必要的完整 key skill/support package；
- 局部核心 passive connection、keystone/notable/jewel package；
- 暗金/装备与技能、辅助、天赋、资源系统的完整核心联动。

禁止的是把全部装备槽、整棵已分配天赋、全部技能组和完整配置共同组装成可一比一还原第三方
整角色的镜像。边界按知识作用域判断，不按组件数量判断。

## RewardEvent

来自生成、比较、修复或失败的学习信号。

必要概念：

- build brief id；
- snapshot ids；
- used graph edges 和 techniques；
- before/after scores；
- fixed gaps 和 failed gaps；
- rollback count；
- final outcome；
- patch/version context；
- modelability caveats。

## FailurePattern

可复用的死胡同或反复修复失败描述。

必要概念：

- trigger conditions；
- failed strategy；
- affected lifecycle stage；
- evidence refs；
- recommended avoidance or alternative；
- confidence 和 promotion status。

## BuildPlannerExport

官方 `.build` artifact contract。

必要概念：

- 单阶段 passives；
- 单阶段 skills 和 support skills；
- inventory slot hints；
- 支持时包含 weapon set；
- resolved GGG IDs；
- unsupported-field caveats；
- converter provider identity、version/commit 和 validation result。

Phase 6 MVP 不要求自动生成 `level_interval` 或多阶段生命周期。只有未来输入本身提供了多个完整
阶段状态时，导出层才可以忠实表达等级区间，不能从单阶段 PoB 自动推导。

## FinalBuildArtifact

系统自己生成的最终可信 PoB 本地私有产物。它不是研究记忆，也不是用户可直接阅读的安全报告。

必要字段：

- `artifactId`；
- `runId`；
- `candidateId`；
- `attemptIndex`；
- `snapshotId`；
- `sourceHash`；
- 完整 PoB XML；
- 可信 Judge 凭据引用；
- version context；
- created at；
- local-only / no-chat / no-memory 边界标记。

约束：

- 当前临时交付策略只要求可信 Judge 已评估、`passed=true`、没有 `hardFailures`，且活动快照有效；
  playability failure、`barely_playable`、分数不可用或 offense 为 0 等非硬性结论不阻止创建和
  导出，但必须随 artifact 保留并在用户输出中明确披露，不能据此宣称质量通过；
- 保存时必须重新读取活动 PoB 并验证 hash 与可信凭据一致；
- 每个生成运行最多一个 artifact，不覆盖；
- 失败轮次不保存完整 PoB XML；
- XML 只能存在本地 artifact store，不能进入 `HumanReviewPacket`、聊天、研究记忆或 Git；
- artifact 必须能在 MCP 重启后重新载入 Headless PoB。

保存前的活动构筑还需要通过装备完整度诊断：黄装/魔法装带物品等级、底材等级可穿戴、没有
`Scaffold ...` 占位装；符文/灵魂核心、天赋珠宝、药剂和护符由 Agent 填写或记录明确不使用理由。
除底材等级非法外，这些是 Agent 接受候选前的 advisory，不是程序自动配装规则。

## FinalPobExportReport

最终可信 PoB 的本地用户导出报告。导出前必须复用 `FinalBuildArtifact` 的完整性和可信 Judge 校验。

必要字段：

- artifact id 和 source hash；
- 导出格式：`xml`、`import_code` 或两者；
- 每个本地输出文件的 format 和 output path；
- exported at；
- 响应不含 raw PoB，但本地输出文件明确含完整 PoB 材料的边界标记。

MCP 响应、聊天和人工验收摘要不得携带 XML 或导入码原文。XML 文件供桌面 PoB 直接打开或导入；
导入码文本供用户在 PoB 的 Import/Export 页面粘贴。两者都只能来自已验证的最终 artifact。

## FinalBuildDeliveryPackage

最终交付编排报告。它不参与 BD 设计，只保证交付格式完整且稳定。

必要字段：

- artifact id；
- `artifacts` 固定包含 `pob_xml`、`pob_import_code`、`official_build` 三项；
- 每项包含 `status`、`outputPath` 或 `errorCode`；
- exported count 和 expected count；
- overall status：全部成功为 `exported`，部分失败为 `partial`；
- response 不包含 raw PoB。

Agent 最终答复必须逐项转述这三项，不能因为某项失败或忘记调用而省略。

## BuildPlannerConverterResult

可插拔 PoB -> 官方 `.build` provider 的稳定边界。

必要字段：

- provider id；
- provider version / fixed commit；
- license / provenance reference；
- source hash；
- parsed Build JSON object；
- serialized `.build` JSON；
- warnings，包含 level、code 和 message；
- conversion stats；
- schema validation status；
- output path（成功写出时）。

最终 `BuildPlannerExportReport` 另外携带 artifact id、output path、导出时间和单阶段标记；provider
边界本身不需要知道 artifact store 的内部结构。

业务层不得依赖 provider 内部类型。provider 缺失、崩溃、输出非 JSON、输出 hash 不匹配或包含
error-level warning 时，导出失败而不是静默切换到名称猜测。
`DeepResearchRecord.component_mentions` 保存当前案例中被明确讨论、但未必已经解析为物理图 stable key
的组件提及。每项包含 `candidate_name`、`role`、`resolver_query`、`expected_node_types`、可选
`component_key` 和 `resolution_status`。已解析项同时进入 `component_keys`；未解析项仍可入库和召回，
但不得据此创建 semantic edge。

这里的 `role` 是 BD 功能角色，不是物理节点类型的别名。一个 `payoff` 可以来自主动技能、被动或
暗金，非武器的普通装备基底使用 `gear_base`，武器基底使用 `weapon_base`；后者也可能由暗金武器承担。acceptance 使用受控的 role/node-type 兼容矩阵，
但仍要求 resolver 唯一确认 stable key。兼容矩阵不能把模糊候选变成已解析端点，也不能授权 semantic
edge。验收报告中的 `unresolvedDeepRecordMentionCount` 统计未解析提及次数，
`unresolvedUniqueComponentCount` 统计去重后的组件；旧字段 `unresolvedDeepRecordComponentCount` 保持为
mention 次数以兼容现有消费者。
