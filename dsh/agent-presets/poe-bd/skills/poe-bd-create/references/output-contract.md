# Create 的提交对象合同

在生成机制蓝图、填写 Draft 或最终安全摘要时查本文件。查询与采用方法见 [research-use.md](research-use.md)；正式 Judge 与重验见 [validation-and-recovery.md](validation-and-recovery.md)；baseline选择/保存、review、导出与用户披露见 [delivery.md](delivery.md)。不要让用户阅读或填写内部对象。

## 模板、字段归属与版本

从本次 `mcp__poe_build__start_generation_run.agentOutputDraftTemplate` 填写 prompt/candidate；顶层字段已有模板，不自行重建另一份列表。原样保留本次 `runContext`、`packetId`、`promptId/requestRef`、`experimentContext`，不得复用其他 run 的旧 `HumanReviewPacket`。内部对象使用 schema 的 camelCase；工具参数仍按各工具签名传入。

模板的 `researchMemoryUse / researchExecutionPlan / mechanismBlueprint` 初始为 null，不能据此省掉匹配模式所需的嵌套合同。四种对象各负其责：

`mcp__poe_build__start_generation_run.agentInputContracts` 提供从实际模型派生的输入schema及共享定义，
按本次填写的对象查约束，不猜数组上限、引用格式或理由长度，也不要把schema塞进candidate。
重复且仍合法的Draft返回 `already_validated` 时沿用原验证；它不刷新时间、不替代状态变化后的重验。

| 对象 | 责任 |
| --- | --- |
| `researchMemoryUse` 的 insight/premise 决策 | 已召回证据的实际利用、逐组件subject决定、失败前提处置 |
| `researchExecutionPlan` | 设计案例、研究包取舍、跨案例机制的完整配套 |
| `mechanismBlueprint` | 把知识综合为可证伪的机制与玩法模型 |
| `prototypeBuildCandidate` | 最终接受方案的安全摘要，绑定选定attempt与artifact |

它们可以共用真实证据引用，不能由一段通用“采用理由”相互替代。candidate 表达阶段目标、职业、主副技能职责、机制、防御、Spirit/资源、装备职责、天赋锚点、转型门槛与caveat；`gearRoles/passiveAnchorIntents` 写方向，不复制完整装备表/天赋路径，也不为单一Judge数字压缩合理多技能组合。

`currentOutputStages/targetLifecycleStages` 使用 `campaign_early / campaign_mid / campaign_late / maps_entry / endgame_budget / endgame_final`；兼容别名 `budget_endgame / final_endgame` 也可输入。90级对应 `endgame_budget`（82+），`endgame_final` 需92+；不能自造stage。`crossStageLockedDimensions=["class"]`。

`fieldSources` 的键覆盖 `user_request_summary / refined_prompt_summary / current_output_stages / target_lifecycle_stages / cross_stage_locked_dimensions`，这些键为snake_case；值仅 `user_explicit / agent_inferred / defaulted / unknown`。

`versionContext` 一次包含 `league / ruleset / gamePatch / passiveTreeVersion / pobVersionOrCommit / graphSnapshotId / researchMemoryRef`，来自本run的freshness、图和Memory查询。`pobVersionOrCommit` 只填原版本/commit，不拼 `(stale)`；过期状态放 `unresolvedItems/unresolvedCaveats/toolFeedbackEvents`。图不可用时保留工具明确返回的 unavailable 标记，不猜版本。Research引用用实际 `dedupeQueryRef`，no-memory用下述精确sentinel。

prompt、最终candidate、其接受audit及toolFeedback的版本与对应可信Judge receipt一致，包括 `researchMemoryRef`；不得事后改写已有attempt的版本来配合新候选。不同attempt保留各自真实绑定，最终选中哪轮就用哪轮版本。

## ResearchMemoryUse

普通匹配模式填写以下嵌套字段；引用列表去重，不能混用授权与对照集合：

| 字段 | 内容 |
| --- | --- |
| `retrievalOutcome` | `matched / no_matching_memory` |
| `dedupeQueryRefs / comparisonDedupeQueryRefs` | 本run完整授权/对照receipt页链；精确规则见research-use |
| `componentKeys / buildFamilyKeys / deepRecordIds` | 本次实际召回且使用的稳定身份和深读记录 |
| `selectedKnowledgeScope / selectedSourceCaseRef` | 最终唯一授权lane；scope为 `global_seed / local_user`，Blind仅global |
| `patternIds / semanticEdgeIds / memoryItemIds` | v2 lane匹配时保持空，不把其他通道注册为授权来源 |
| `insightDecisions` | 下述逐项利用决定 |
| `premiseAuditVersion / premiseDecisions` | 有premise决定时version为1；逐项处置关键失败前提 |
| `noMatchReason` | 只在no-match时填写真实原因 |

每条 `insightDecisions` 用 `sourceRefs / decision / summary / application`，`decision=adopted/caveated/rejected`；`sourceRefs` 必须来自本次实际召回且已登记的记忆项。合同要求的组件另填原样 `subjectRef`，逐项覆盖与最多24项规则见research-use；普通记录级决定可省略subjectRef。

canonical key 中的 ASCII 撇号必须保留，不能删去或替换。证据引用使用工具返回的安全 stable key/
receipt ID（3–240字符），不能直接用带空格的显示名或完整URL；外部来源应保留无原料的证据标识。

每条 `premiseDecisions` 用 `premiseId / decision / resolutionRefs / application`，必要时加 `caveat`：

- `resolved` 必须有本run record-detail深读解决记录，且不带caveat。
- `caveated` 必须写caveat；未关闭前提保留风险，不伪造解决引用。
- `not_applicable` 用application说明完整理由，不带resolutionRefs/caveat。

`premiseId` 唯一。索引中见过但未实际深读的记录、网页或普通图/语料不能作为resolved依据；获取回执与可用引用的精确边界以research-use为准。

模式差异：

- `matched` 有实际记忆项和insight决定，不填noMatchReason；最终lane与所有授权receipt一致。
- `no_matching_memory` 保留真实查询receipt与noMatchReason，但不伪造lane、记忆项、insight/premise、对照引用或executionPlan。不能把已发现的authorized Family改报no-match。
- `--no-memory` 省略 `researchMemoryUse/researchExecutionPlan`，`memoryReferences=[]`，`researchMemoryRef="disabled:no_memory_baseline"`；其他图/机制/PoB工具与蓝图照常。
- Blind的独立 `learningMemoryUse` 按 [blind-mode.md](blind-mode.md) 填写并提交，不混入Research引用。

`memoryReferences` 在匹配模式可省略，helper从typed use生成包含查询及记忆项的去重并集；无需手工再抄一份。

## ResearchExecutionPlan

匹配Research时，填写本次合同的 `contractRef / selectedDesignCaseRef / selectedVariantRationale / coherenceSummary / packageDecisions / crossCaseMechanismPlans`。设计case必须等于最终授权lane。

每个要求的package恰好决定一次：`packageId / decision / mechanismRationale / buildApplication / verificationEvidenceRefs`。decision仅 `adopted / tested_and_rejected / not_applicable / retained_as_alternative`；跨案例采用另用 `crossCasePlanRef` 绑定计划。完整采纳、部分保留及真实外部证据的区别按research-use执行。

每个 `crossCaseMechanismPlans` 对象填写：

- 身份/配套：`planId / sourceCaseRefs / sourcePackageIds / targetCompanionPackageIds`；额外配套可填 `additionalCompanionPackageIds`。
- 原因：`mechanismRationale / compatibilityRationale / tradeoffRationale`。
- 操作/验证：`implementationPlan / conflictResolutionPlan / verificationPlan / failureExitConditions / evidenceRefs`。

source与package一致，target companion来自授权lane；计划引用不得重复，验证至少两项，步骤要具体说明操作与退出条件。package/case/contract ID引用工具实际返回的值，不造来源。

Draft冻结 `contractRef`、`selectedDesignCaseRef`、package ID/决定/跨案例计划引用，以及计划ID、来源case/package、目标/额外companion。Judge后可据实际结果更新变体/整体理由、机制兼容与取舍解释、buildApplication、证据、实施/冲突/验证步骤、失败退出条件；不能借此改变来源案例、采用/拒绝结论或配套依赖。最终review检查结构hash；完整plan hash仍用于审计。机制变动需要重验时按validation-and-recovery路由，不靠改正文绕过。

## MechanismBlueprint 入口

完整内容、证据状态与覆盖要求见 [mechanism-blueprint.md](mechanism-blueprint.md)，这里仅列模板未提供的对象入口：

- `mechanismBlueprint`：`document / claims / coverage / unresolvedQuestions`。
- 每条claim：`claimId / title / status / explanation / sourceRefs / componentKeys / conditions / failureConditions / verificationTasks`。
- 每条coverage：`axis / status / explanation / claimRefs`；claimRefs引用本蓝图的claimId。

`claimId` 为 Agent 分配的 `mbc-` 加16位十六进制 ID，不是工具回执。`document` 为800–20000字符，
每条 claim 的 explanation 为80–1800字符，每条 coverage 的 explanation 为40–800字符。
ResearchExecutionPlan 的 selectedVariantRationale/coherenceSummary 各至少80字符；package 的
mechanismRationale 至少40字符、buildApplication 至少30字符。正文应写具体因果与实施依据。

提交给 `mcp__poe_build__validate_generation_blueprint` 的 `blueprint_draft` 包含 `candidateId / versionContext / noRawMaterial / researchMemoryUse / researchExecutionPlan / toolReferences / mechanismBlueprint`，按模式省略不适用的Research对象。返回的 `blueprintRef` 与同一份已接受蓝图写入candidate的 `mechanismBlueprintRef/mechanismBlueprint`，并添加匹配ToolReference；不能只留一个“已完成蓝图”的布尔值。

## 工具引用与最终完整度决定

### DPS粗估与技能价值

`prototypeBuildCandidate.performanceEstimates`可选，最多8项，均为Agent情景估计，不能替代PoB/Judge
的可信数值。每项填写`estimateId / subject / estimateScope / lowerDps / upperDps / basis /
assumptions / sourceRefs / overlapHandling / limitations`，`evidenceKind`固定为`agent_estimated`。
`estimateScope`为`skill_dps / additional_dps / total_dps`，明确是单技能、额外增量还是包含已有输出的
总量；不自动相加。上下界须有限、非负、顺序正确，至少一项假设、已声明审读的ToolReference来源
及限制，说明触发频率、有效命中/重叠、覆盖率、同时生效及重复计数处理。简述依据与公式，不写
隐藏推理过程。范围是条件情景，不冒充统计置信区间；缺少可靠依据时保持未知，不填0作占位。

构筑比较应同时查看机制作用、配套、失败窗口、PoB部分与有依据的粗估。建模困难不降低技能采用
优先级；candidate表示验证覆盖有限，不表示构筑弱。粗估不能单独把机制假设升级为已证事实，也不
进入Judge/reward/进步趋势的数值字段。所有来源仍受当前run、版本、模式及case边界约束。
粗估锚点须对应最终选中的候选；恢复旧baseline时重算或撤回新状态的估计。比较使用相同场景，
不单凭乐观上界采用，也不把粗估的证据限制解释成技能本身弱。
完整与compact Review均保留此数组，最终报告并列展示“PoB可计算部分”和“Agent粗估情景”，明确
每个范围的假设及未验证项，不把不同来源或不同条件的数字混成一个已验证DPS。

`toolReferences` 每项为 `{toolName, queryRef, summary, evidenceKind, reviewBasis}`：

- `internal_receipt`：此处仅支持本 run 已校验的 Research query/contract 引用；reviewBasis=null。
- `agent_reviewed`：实际审读过的图、机制、语料、PoB/计算或外部证据；reviewBasis 写明精确证据、
  观察和条件（20–1000字符），它仍是 Agent 审读声明，不是后端执行或语义认证。
- `unverified`：默认值，旧条目不自动提权；reviewBasis=null，只能供 hypothesis/unknown 保留。

`mcp__poe_knowledge__query_research_memory` 条目覆盖授权与对照的全部receipt引用，另必须有实际 `mcp__poe_knowledge__get_freshness_report`
条目；`mcp__poe_knowledge__construct_research_execution_contract` 与 `mcp__poe_build__validate_generation_blueprint` 引用匹配最终
contractRef/blueprintRef。后两者的 Blueprint 标记与 freshness 诊断不能伪装为机制事实回执。
queryRef 必须对应真实执行或真实证据；不得伪造。当前输出合同为 generation-agent-output-v5。
Blueprint或baseline返回的evidenceAudit是只读来源审计，不属于candidate可提交字段。

`completenessAdvisoryDecisions` 只登记最终可信快照 `transientBuildState.completenessAdvisories` 中仍存在的提示。每项为 `advisoryCode / decision / reason`，decision仅 `deferred / intentionally_unused`；已消失的提示不保留陈旧决定。`spirit_opportunity_review_required` 不允许deferred，其实测、采用与重新评估要求见delivery。

## Attempts、FailureAudit 与 ToolFeedback

顶层只写一次最终 `prototypeBuildCandidate`。每条 `generationAttempts` 用 `attemptIndex`、`prototypeBuildCandidate:{candidateId}`、`failureAudit`；attemptIndex取工具值，从0开始、最多2。helper按候选ID、可信receipt和artifact选择核对，不要求每轮复制完整candidate。

`transientBuildState/judgeAdvisoryReport` 由可信receipt按attempt补入，默认省略；显式填写必须完全一致，不能造snapshotId、sourceHash、分数或硬失败。诊断看 `testedSkillGroups / selectedSkill / skillGroupDiagnostics / attributeShortfalls`；`pob_main_group` 是计算焦点，不代表BD只有一个输出。Judge `error` 是执行错误，不改写成构筑hardFailures；反馈模式及用户措辞按validation-and-recovery/delivery。

每条 `failureAudit` 包含 `auditId / attemptIndex / candidateId / snapshotId / classification / retryDecision / summary / plannedChanges / retainedCaveats / stopReason / versionContext / noRawMaterial`。classification枚举：

| 值 | 含义 |
| --- | --- |
| `true_build_failure` | 真实合法性或质量问题 |
| `judge_modelability_gap` | PoB/Judge表达不足 |
| `judge_offense_evidence_gap` | 正伤害metric存在但delivery evidence有限；strong evidence低于阶段floor是真实不足 |
| `judge_score_review_required` | 可计算但低分需人工校准 |
| `selected_skill_suspect` | 评分技能可疑 |
| `tool_or_data_gap / mixed / no_material_failure / unknown` | 工具/数据缺口、混合、无实质失败或未知 |

非最终轮 `retryDecision=retry` 且写具体plannedChanges；最后轮为accept或带stopReason的stop。accept只用于已评估通过且无硬阻断的候选。选择非最后一轮passing baseline时，顶层另交一份指向该baseline的最终接受audit；不能沿用其旧retry audit或后续失败轮audit，精确选择/保存条件见delivery。选择最后轮时顶层audit可省略。

可选 `toolFeedbackEvents` 每项包含 `eventId / feedbackType / summary / requiresHumanOrTestReview / versionContext / noRawMaterial`。feedbackType仅 `judge_modelability_gap / judge_offense_evidence_gap / judge_score_review_required / query_gap / copy_safety_gap / pob_state_gap / tool_usability_gap`。摘要与证据保持safe-only，不记录raw构筑、隐藏推理或对话日志。
