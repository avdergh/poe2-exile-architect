# PoE2 BD Creator 数据结构合同

最后更新：2026-09-06

本文档在产品层定义核心 artifact contracts。精确字段校验应放在代码和测试里。

## 跨补丁知识适用性

正常 Research 只研究最新版本 BD；旧知识继续作为召回与补丁复核对象。
Research Memory DB schema 7 复用 `research_content_revisions` 正文与
`deep_research_record_bindings` 结论记录，在 `deep_research_record_evidence` 显式绑定每个来源声明。
正文包含标题、摘要、正文、组件及职责、
适用条件、失败条件和 typed payload，按完整存储值精确共享，不按语义相似度自动合并。
`deep_research_records` 是兼容视图。6→7迁移保留旧正文、记录ID、来源版本、projection和状态；先固定
仍匹配的旧复核，再纠正schema2来源/安全引用/证据数的派生缓存，纠偏不重写原review指纹。缺失或
失配证据保留为NULL绑定及安全缺口，不用另一来源正文补造认证。
`contentRevisionRef` 标识内容，不授予另一条记录的来源、版本、模型或可见权限。
普通查询在来源／权限／目标版本过滤后、分页前归并相同内容，优先返回当期代表记录；
Family 深读覆盖、前提和执行合同采用相同代表选择。明确指定 record IDs 时仍逐条精确读取。
历史来源和版本证据不删除，不同条件的内容仍独立；Create 继续先选定 source-case lane。
发布时仅有安全存活绑定引用的正文能够保留，升级备份和裁剪前私有副本不进入发布目录。

Family 身份与 `knowledgeConceptKey` 跨版本稳定；0.5.5 起具体 record/evidence identity
包含来源 patch，保留此前已发布的旧记录 ID。`research_patch_reviews` 追加保存 target kind/id、
scope、来源／目标 patch、来源指纹、原 projection hash、outcome、理由、修订摘要、验证任务、
补丁证据和独立 review 引用；不得覆盖来源正文、版本或把复核视为新样本。
召回的 `targetApplicability` 区分 `current_evidence / reviewed_compatible /
historical_unreviewed / incompatible / changed_scope / unsupported_version`。0.5.5 默认继承
0.5.4 召回；不适用只阻止目标版本采纳，历史查询仍可用。审查改变 memory revision，使旧
Create 分页回执失效。发布审查必须属于 global_seed、目标存在且源指纹仍匹配。
目标版本不适用的正文退出 Create 实现证据，但同 Family 的 `patchCorrections` 保留修订理由、
验证任务与审查引用；它们明确 `createAuthorizing=false`，不能伪装成 premise 深读解决记录。

审查同时保存完整读取指纹和稳定断言指纹；追加来源／证据引用不会撤销已确认的不适用限制，
实际正文或条件改变才使审查过期。发布副本剔除过期审查，本地事件历史保留。
Research 来源 patch 与 PoB 模型认证 patch 独立：在线来源绑定官方 patch/联盟；本地文件
须传 `source_game_patch`，补录继承原队列；队列单独记录 `modelGamePatch`，存在模型缺口
时使用 `source_patch_model_mismatch`，不得将模型版本误写为新样本来源版本。
该上下文同时进入 packet 安全元数据、PoB readback 和 review contract；旧队列缺少模型补丁时
使用 `model_version_unknown`。读回成功／失败均保留版本信息，数值仍遵守 partial modelability。
语义边的逆边与短环路检查也使用目标 patch／tree 及有效补丁复核，明确失效的旧边不再阻止
当期关系入库；仍有效、未复核或复核已过期的历史边继续参与冲突检查。

## 语料发布与运行时认证

`update-manifest.json` 的 `corpus.certificate` 携带独立语料证书，绑定 corpus SHA256、
游戏补丁与树版本；不借用引擎证书。更新器将数据库、`corpus.compatibility.json` 和安装元数据
成组切换／回滚，支持同版本补证。旧发布缺证时仅允许复用哈希完全相同的既有可信证书。
各 MCP 进程读取按文件身份刷新的只读内存快照，避免长期占用 Windows 数据库文件；读取认证
与更新共用锁，元数据、实际内容和证书保持一致。
CI 与发布重建使用 `pipeline.corpus_certificate`：只有静态表与已认证基线完全相同的重打包
可重新绑定文件哈希，保留原认证时间和补丁；wiki 仅作参考。静态数据有变化必须先取得新证书，
自动刷新在发布前停止，原发布继续可用。

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
- 普通 Create 的 budget model 只描述用户披露口径，不参与 Family、暗金、黄装、符文或药剂选择；
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
- `AgentDpsEstimate`：候选的可选`performanceEstimates`（最多8项），只表示Agent情景粗估。
  字段为`estimateId / subject / estimateScope / evidenceKind / lowerDps / upperDps / basis /
  assumptions / sourceRefs / overlapHandling / limitations`。`evidenceKind`固定`agent_estimated`；
  scope为`skill_dps/additional_dps/total_dps`。边界须有限、非负、upper>0且lower≤upper，不接受布尔；
  ID唯一、来源引用去重且须对应候选已声明审读的ToolReference；Research采用对应实际查询回执，
  仍由run级provenance核验。说明公式、假设、重复计数和限制。
  范围不是统计置信区间，不能自动相加，不替换PoB/Judge/reward字段；估计与可信数值在完整及
  compact Review分开呈现。没有估计依据时省略，不填0。建模覆盖不自动降低技能采用权重。
- `PrototypeBuildCandidate`：Agent 产出的候选 BD 安全摘要。至少表达当前输出阶段、完整生命
  周期目标、职业壳、跨阶段职业硬锁、主技能/辅助技能意图、机制和伤害缩放轴、防御层、
  Spirit / 保留资源假设、装备角色、词缀方向、天赋锚点或区域意图、转型门槛、未解决注意事项
  和使用过的工具/记忆引用。普通模式还必须带 `ResearchMemoryUse`：记录真实
  `dedupeQueryRef`、定向查询使用的 stable component keys、命中的 Build Family / 深度记录、
  `selectedKnowledgeScope + selectedSourceCaseRef`，以及每条研究结论被采用、保留或拒绝后如何影响
  候选。Query contract v2 只允许同一案例 lane 的 deep record/index/premise/digest 授权 Create；
  pattern / semantic edge / legacy fragment 只可作为 ToolReference。无匹配可以显式
  记录 `no_matching_memory`，不能用空泛工具调用冒充记忆已参与设计。
  选中 Family 的查询若返回 `familyPremiseCatalog`，还必须使用
  `premiseAuditVersion=1 + premiseDecisions` 覆盖全部关键失败 premise。每项 decision 为
  `resolved / caveated / not_applicable`：resolved 必须引用本轮
  `detail_level="record"` 回执实际出现的 DeepResearchRecord；caveated 必须保存具体风险；
  not_applicable 必须说明当前候选为何不受影响。普通单阶段 Create 使用
  同一 receipt 审计器。
  Research Execution Contract v2 另从 authoritative packages 派生最多 24 个
  `requiredInsightDecisionSubjects`，只包含 canonical `unique_enabler`。新 Agent Output v4 的对应
  `insightDecisions` 必须用 `subjectRef` 精确覆盖并引用真实 source record；旧最终 artifact 不要求
  回填。package、premise 与 comparison/cross-case 决策仍由原结构独立负责。
  `subjectRef`、Blueprint 组件与证据引用、package/cross-case 证据引用允许 canonical key 中的
  ASCII 撇号（例如 `unique:pob:kalandra's_touch`），必须原样保留。引用仍限制为 3–240 字符，
  不允许空白、双引号、分号或完整 URL；字符可解析不替代来源 lane、record、subject 的精确核验。
- `GenerationDraft`：首次正式 Judge 前的一次性轻量校验对象，只包含已绑定的
  `runContext / packetId / agentRefinedBuildPrompt / prototypeBuildCandidate`，不要求 Judge receipt、
  attempt 或 artifact selection。`start_generation_run` 用 Pydantic alias 返回完整 camelCase
  skeleton；`validate_generation_draft` 校验 run/prompt/request、字段类型、versionContext、当前 run
  Research receipt/lane 与 premise audit，但不持久化、不消耗 run。failure-condition premise 的
  `decisionTemplate` 最少包含 `premiseId / decision / resolutionRefs / application / caveat`。
  `resolved` 的引用只能来自本轮 deep-read record；网页、外部样本、普通图和 corpus 证据只能进入
  tool references、rationale 或 caveat，不能成为 `resolutionRefs`。
- `TransientBuildStateRef`：由 `evaluate_generation_candidate` 从真实活动 PoB 快照生成的临时
  构筑状态引用；对外和持久报告里只能出现不透明本地引用、摘要和安全 hash，不能
  展开 PoB 导入码、原始 XML、第三方成熟 BD 的完整装备表、完整天赋路径或原始技能连接。
  当状态为 `available` 时，必须包含 `testedSkillGroups`，记录 Agent 实际测试的技能组编号、职责、
  全部主动技能及数量、辅助技能和启用状态，使蓝耗、Spirit、伤害和可建模性结论可复核。新评估
  同时带 `semanticStateHash`，用于判断 PoB 派生输出刷新前后是否仍是同一构筑输入。
  `mainSocketGroup` 只标记 PoB 当前计算组，不声明整个 BD 只有一个主技能。
- `JudgeAdvisoryReport`：Phase 1 Judge 生成的参考评估，新增 `feedbackMode` 与
  `subjectiveFeedbackSuppressed`。新 Create 默认写 `hard_only/true`，只保留硬阻断、`passed`、
  快照绑定、实际选择技能、技能组和属性缺口等确定性诊断；aggregate、score vector、quality
  band、playability/quality warning、reward、offense floor、modelability/score caveat 必须为空。
  用户手动传 `strict_mode=true` 时写 `strict/false`，才表达硬阻断、分数、证据等级、可建模
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
  同一 run 的首个可信 attempt 会锁定反馈模式；后续 attempt 请求另一模式时返回
  `judge_feedback_mode_mismatch` 和 `attemptConsumed=false`，不消耗三次 Judge 额度。
- `HardLegalityAudit`：不含强度评分的共享确定性合法性结果，由 checkpoint、正式 Judge、
  `optimize_item` / `rank_upgrades` 和 artifact 保存共同复用。字段包括
  `auditVersion / hardLegalityReady / hardFailures / checks / sourceContext`；checks 分别记录
  职业/升华、属性差额、装备等级、主动宝石等级、PoB 武器兼容、Spirit、普通/武器组天赋预算、
  已装备词缀合法性、生成候选遗留的 `Scaffold ...` 装备，以及 rare/magic 装备缺失 `Item Level`。
  主动技能等级保留 `naturalMaxLevel` 并返回 `levelAuthority`：普通宝石沿用自然等级上限；
  只有 PoB 合成首宝石、实际装备槽、物品来源和精确授予技能同时绑定时才使用 `item_grant`。
  稀疏来源技能等级复用 PoB 的标准等级归一化，再核对实际读回和精确等级模型；缺失来源绑定或
  模型必须失败，不能凭 XML 的 `source/fromItem` 提升权限，也不改写原始宝石等级数据。
  `inspect_generation_checkpoint` v8 另外把
  `hardLegalityReady / mechanismReady / qualityAdvisories / readyForJudge` 分开返回。预检失败
  必须带 `attemptConsumed=false`，不能写 Judge attempt receipt。装备候选比较同时保留换装前后
  两份审计：新增或加重确定性错误的候选必须拒绝；诊断用基础构筑本来就存在且未被候选加重的
  错误继续披露，但不能被错误归因为本次换装。
  v8保留 `skillSupportAudit.groupResults` 逐组记录 active skill、freshness、`reasonClass`、reason codes
  与 PoB runtime capability。当前辅助应用已验证、结构和约束完整、缺口由原生PoB明确识别为
  数值模型缺失时，`capability_gap` 映射为 `unknown`；其他 evidence/measurement/actionable gap 均阻止 Judge。
  原生代理生成 effect 的 `UsedByProxy/Cooldown/Duration/Buff` 类型与Herald类型也要求独立频率；
  负载的普通攻击速度或零DPS不能替代。`rateSourceEffectIds`保留相关原生effect身份。
  `ObjectDurability/Duration/DamageOverTime`声明同时存在，但持续时间缺失、持续伤害未读回时，
  `declaredDamageModel="incomplete"`及`declared_duration_dot_model_missing`阻止伤害排序，即使有正的
  普通武器命中读数。优化器、Checkpoint与Judge共用`support_capability_is_model_gap`：仅接受与
  `triggerRate/declaredDamageModel`一致的已知模型缺口代码，保留numericRanking=unsupported并
  以unknown候选继续；已知模型缺口可以同时存在。缺失、畸形、不一致或夹杂测量/资源失败的
  reasonCodes不能借此放行。受影响旧审计需重验，不批量改标旧artifact。
  `supportApplication` 保存每个辅助的实际作用目标；允许分别服务同组宿主和输出技能，不能要求
  全部辅助作用于同一选中效果。数值能力判断仍绑定该次精确选中效果。
  preflight从身份核对通过的runtime组投影`mainActiveSkillCalcs/activeSkillSelectionError`，保留完整
  active顺序和重复名；未选中的空显示名效果仅在runtime提供非空稳定effectId时保留原索引位置，
  选中空名、身份缺失或多输出歧义均不猜index1。辅助速率缺口仍用`currentConstraintCheck`
  核可读Mana/Spirit约束，明确超限/测量错误/缺值不能由capability_gap覆盖。
  每个quality项的`currentAdverseEvidence`只标记同snapshot的当前有效反证；审计missing/stale不标记。
  满孔仍纳入曾审槽位的时效核对，已卸槽不遗留义务，可信装备后的当前applied计划可通过。
- `lifecycle_mechanism_observation_v1`：正式lifecycle与checkpoint共用typed声明及快照实物观察。
  活动声明保留在engine有界内存中，绑定语义state hash与精确group/activeIndex/skill；所选artifact
  可保存安全typed绑定输入，不保存XML或以caller布尔/pass授权。cache hit也重新观察并跑原gate，
  空声明或新失配声明撤销旧判断。
  实际等级、药剂和技能从所评快照读取，关键组件必须同时具备声明、匹配实物、stable key和refs。
- `mechanismEvidence`：成功Draft冻结的raw-free Blueprint marker/正文、Draft marker及Research
  使用决定/执行计划，随可信Judge receipt绑定run/candidate/attempt/source/semantic hash/完整输出。
  `bundleHash`同时锚定在进程内精确Judge snapshot中；不复制整个候选。旧无bundle回执保留原current
  binding路径，但不能跨修订恢复。保存后由artifact/selection的`mechanismEvidenceHash`支撑最终
  Blueprint、Research与selected-attempt校验，当前marker不回写；来源、决定和稳定执行结构不变，
  仍须通过本run的receipt/deep-read/premise/subject审计，不能借历史context跳过来源权限。
  Draft marker v3新增`researchDecisionHash`，与最终历史校验使用相同的来源、决定、解决证据和稳定
  执行结构身份；允许的叙述补充及无序引用重排不改变该身份。同语义marker缺内存bundle时，完整
  验证可返回`accepted/evidenceRebuilt=true`，不改原marker字节、时间或run期限。所有要求Blueprint
  的新Judge均须有bundle，否则`generation_draft_evidence_required/attemptConsumed=false`。
  旧v2 marker可在原run完整重验后升级，旧receipt不补造历史证据、仍按原兼容权限读取/保存。
- `build_state_hash`与Research XML结构读取使用`pob_xml_input_v1`：按pinned PoB Lua一次解码
  五种命名实体，numeric/unknown实体按PoB行为处理，保留属性内LF/CR/TAB。读取投影不能序列化
  写回PoB；活动XML局部变更保留非目标原字节。普通未受影响输入的旧hash保持兼容。
  新Research readback binding由生成器写`xmlInputSemanticsVersion/sourceInputStateHash`，
  对确受旧ET语义影响的输入缺失或不匹配时要求重验；仍独立校验原始`sourceSnapshotHash`。
  单独补标记不能授权旧数值，也不批量迁移或提高历史知识权限。
- `support_audit_v5`：`measurement.combinationComparison`比较完整当前组合与完整候选组合，
  两者必须绑定同一精确技能、目标、原始构筑状态并完整测量；合法性不得新增或加重错误。
  当前版本可用性由`data/compatibility/gem-availability.json`的官方移除事件与静态精确gem ID绑定；
  原始语料、来源版本和物理图身份保留。`released`、PoB能计算、等级曲线通过均不代替当前可用性。
  搜索、详情、等级入口、图查询与活动`gemAvailabilitySubjects`共享可用性修订；发布校验其语料身份。
  已移除候选在测量前排除，`unavailableInGameCandidates`列明依据，不混入`uncoveredCandidates`的模型缺口。
  `availabilityContext`绑定目录指纹与当前引擎的审读排除，变化后旧审计变stale；完整重算才可替代旧强制推荐。
  `optimize_supports.availability_reviews`接受精确`componentKey/targetPatch/reason`与官方及独立来源的
  `sourceReviews(url/assessment/relevanceReason)`。Agent须阅读实际内容，参数只声明`agent_reviewed`，
  不提升为内部Research证据。通过原生精确支持身份校验后原子登记在本引擎会话；错误补丁、歧义身份、
  缺少官方或独立审读均拒绝，不部分登记。此排除不写用户库或发布目录，重连后由Agent重交。
  当前组含失效辅助时输出`currentUnavailableSupports/supportsToRemove/recoveryAction`；重新选择有效组合，
  即使面板降低也不能保留失效组件；修复不冒充同玩法的数值升级，采用后另审当前完整组合。
  辅助适用性沿 PoB 实际 source instance、effect ID 与已应用 effectList 追溯独立宿主，先授权
  宿主上的辅助，再纳入它授予的子技能；自身授予和无根循环不能作为适用性证据。
  `supportApplication` 保留 `supportEffectId/rootedActiveEffectIds/unrootedActiveEffectIds`，
  `activeSkills` 只列有合法来源的已应用效果。合法宿主、负载与已授权子技能仍可分别受辅助作用。
  全组合与每个候选测量均读取 `Life/LifeReserved/LifeUnreserved`；缺数值是测量缺口，
  `life_reservation_exhausts_life` 是候选拒绝原因，仍继续搜索其他合法组合。旧 v3 必须重验。
  只有完整审计证明净正收益，才设置`positiveGainCombinationAvailable`并要求修改；
  `positiveGainSupportsMissing`为空不代表无需修改，纯移除方案由`supportsToRemove`表达。
  搜索从当前与最小辅助集合出发；最小集合保留PoB实际应用且增加`HasUsageCondition`的辅助。
  `usageConditionContractVersion=1/usageConditionContracts`逐效果绑定support/effect ID；新增、移除
  或替换使用条件的组合记为`support_usage_condition_changed`，不是自动正收益。Agent需先明确
  改组才能改变玩法条件；该合同不证明移动、站立或充能条件的实际覆盖率。缺少该运行时证据的旧
  数值审计必须重验，不补标记。`globalOptimalityProven=false`；覆盖仅限已筛选的runtime可解析
  辅助身份及已访问组合。PoB runtime ID确认不可用的候选单列于`uncoveredCandidates`，
  `modelCoverageComplete=false`不等于这些候选无收益，也不能将搜索结果称为全局最优。
  同effect、目标权重、约束及完整候选范围的新测量错误或反证撤销旧comparison沿用权限；历史
  诊断可保留，不能给新state签发旧数值的passed。较窄查询或不同目标不能洗掉已证实的正收益义务。
  PoB生成/移除附属effect时按固定effectId与精确名称唯一定位输出，分别记录
  `baselineActiveSkillIndex/candidateActiveSkillIndex`；原state审计和新state沿用各绑定实际序号。
  名称与effectId交叉不匹配、缺失或歧义均拒绝。该effectId用于数值目标，不替代Research Family键。
  普通组局部探针发现其他组或拓扑变化时，改用原始完整snapshot重建该候选；实际操作失败仍阻断，
  不能冒充裸技能不可建模或无收益。
  非活动物品来源组在每次完整snapshot重载后先设为计算主组，再选择精确active effect；不能在
  PoB尚未生成该来源的活动效果列表时同时要求有效序号。激活后仍核对来源、effectId和实际辅助，
  最终恢复原state hash。这仅选择计算焦点，不证明副武器切换、充能或增益覆盖已经验证。
- PoB runtime contract 10 识别原生 `Default Attack`：`sourceKind=default_attack` 和宝石
  `levelAuthority=default_attack` 必须绑定当前 MAIN 计算产生的 slot/effect/level 授予，XML标签不能授权。
  默认攻击的 `activeSkills[].effectiveLevel` 与原始宝石 `level` 分开读回；前者含装备增级，后者负责等级合法性。
  未选为主输出、未纳入FullDPS、只有一个原生根且没有辅助的默认组不要求优化审计；采用后照常执行。
  两武器组的默认攻击按实际槽位分别标识，未活动组不能借缺少effect读数取得审计通过。
  `configure_source_skill_supports` 支持该原生来源，仍核辅助实际适用性、资源、指纹和失败回滚。
  设置普通主技能保留已有来源组及辅助；普通旧主组仍被替换。
- 持久制作回执的 `pobCommit` 两侧必须已知，所有版本字段规范化后精确相等。缺失版本不能作为
  通配证据，旧共享配额ID不可与新模型混用；拒绝不重写旧回执，重新制作或测量后生成新回执。
- `GearAttainabilityPolicy`：只约束生成黄装候选的质量，不属于物品合法性。默认
  `realistic_trade` 每件最多五条显式词缀与两条深 T1；显式 `theoretical` 允许六词缀上限。
  `plan_gear / optimize_item / craft_item / rank_upgrades` 与 Checkpoint 使用同一 policy 及 tier 阶梯，
  实际 roll 后重新分类，来源低档与高档数值重叠时继续寻找实际低档候选；完整成品须再次通过审计。
  装备写入、暗金、药剂、护符、珠宝、Rune、Soul Core、implicit 和 corruption 不受该策略限制。
  `plan_gear`的边际词缀选择在全局group互斥、底材前后缀容量、总显式与实际深T1预算内联合优化，
  完整成品必须另测；不能将边际分数之和直接当作组合收益。
- 物品词缀容量按静态底材类型与稀有度共用`db.craft_profile`：普通Rare装备3前/3后，
  Jewel类Rare（含Radius/Time-Lost）2前/2后；Magic仍1前/1后，Flask域保持Magic限制。
  `optimize_jewel`自动选择与Agent精确选择、通用单件优化、边际规划、物品解析的剩余槽位和
  来源感知合法性审计使用同一容量。隐式、Rune及可信特殊来源仍按既有来源合同计数，
  不套普通黄装可获得性预算；`theoretical`也不能提高底材合法容量。不得按职业、升华或技能名分支。
- 普通装备搜索使用`item_replacement_context_v1`：抗性发现以卸除待换槽后的PoB状态为准，候选
  绑定原effectId/精确名称、用户组或source归属与配置，逐项完整测量并验证恢复；未知、缺值、
  非有限数值或显式失败不进入排名。原生未配置派生源可随真实词缀变化，原输出与用户配置不得漂移。
  完整物品由PoB原生Item解析后一次替换目标槽，再按完整新装备组合刷新槽位；不走UI粘贴的
  anoint/Rune自动继承，也不在替换中间重算空槽，避免合法换弓误删箭袋。真正不兼容的组合仍由
  PoB槽位规则与原输入／整角色合法性检查拒绝。普通写入、制作、镶嵌和批量测量复用该解析路径。
  `plan_gear.planReplayVerified`表示仅重放返回物品便可复现投影，仍不替代最终Judge或装备采纳。
  `craft_item.comparison`比较原完整装备与最终成品；旧`metricBare/metricCrafted`保留为制作步骤比较。
  空活动主手的攻击构筑仅在精确输出及PoB武器检查共同证明缺少武器时，允许原基线保留
  `TotalDPS/FullDPS`缺值；Life/EHP等其他指标仍须完整。
  返回`baselineStatus="unavailable_empty_weapon"`、`comparisonAvailable=false`，不填零或认证净增益。
  新成品仍须同输出可测且武器兼容；错误武器、其他缺值与非有限数值不适用此例外。
- `CraftLegalityReceipt`：由服务端根据当前 PoB `crafting_options` 签发的本地、raw-free、
  content-addressed 制作来源凭据。它绑定底材、槽位类型、物品等级、PoB/数据版本、原始与 PoB
  round-trip 语义指纹，以及 Perfect Essence、符文和腐化选项的安全哈希；不保存完整物品文本。
  `craft_item` 只有在最终物品和 PoB 写回态都通过共享来源感知审计后才持久化 receipt，并返回
  `craftReceiptRef`。`equip_item` 与 `FunctionalBuildMutationBatch.equip_item` 可携带该引用；
  引用、物品、槽位或版本不一致时失败关闭。普通黄装不需要 receipt；第三方特殊来源无 receipt
  时只保留未验证诊断，不能授权新的生成 artifact。
- 暗金合法性从 corpus 保留的 pinned PoB `uniques.raw` 读取固定词条、隐式与完整变体组合。
  `get_unique.variantSelection` 返回 `requiredSelections/allowDuplicateVariants/options/modifierTemplates`；
  新版PoB的Version与独立Variant组使用`selectionModel=version_group_v1`，附`versions/groups/defaultSelection`，
  每条模板保留版本/组条件，默认选择跟随PoB源声明；不同版本或互斥组不得叠加。`defaultSelectionText`
  只投影该明确默认选择，语料和图的可读文本保留其他选项及成立条件，不把历史效果写成常驻收益。
  展平的 `text` 仅供阅读，不代表所有变体可以同时装备。校验按 PoB 的 variant 共享与重复语义核对
  完整词条多重集、数值范围及选择数量，不允许任意子集、跨变体拼接或由调用者扩大选择容量。
  PoB来源中的词条种类标记（如`{desecrated}`）与剪贴板效果分开比较；仅统一效果文本，原始
  结构指纹、实际读回及独立的Rune/腐化等特殊来源回执审计不因此放宽。
  写入后的同暗金身份校验包含实际选中变体和隐式，不能用同名不同效果的物品冒充请求。
  静态源中无条件的原生 `Corrupted` 标记由 `variantSelection.intrinsicCorrupted` 显示；只有
  名称、底材、完整变体和实际词条范围匹配时，共享审计才返回 `intrinsicCorruption`，包含
  `verified_static_source` 状态、暗金身份、源指纹和物品指纹。它不创建制作凭据、不授权额外
  腐化效果或 Rune。原生标记缺失、来源缺失、来源改变或装备读回失配均重新判定，不能删除
  `Corrupted` 绕过门禁；后加特殊来源的装备写入仍必须显式提供原制作凭据，不能自动猜选。
- `optimize_item_sockets` 复用同一个 `CraftLegalityReceipt`，不定义第二套写入合同。它读取已装备
  物品，只接受显式 1–2 孔，在保留底材、Item Level、隐式和全部显式词缀后选择 PoB
  `crafting_options.runes` 中的符文/灵魂核心；用现有 `equip_item` 携 receipt 提交。
  `item_socket_review_v2`由单槽与批量入口共用状态绑定登记，只有`measurementComplete=true`
  的`no_positive/not_applicable`才授权留空；`measurement_error/capability_gap`不得当作无收益。
  `socketed/partial_socketed`只表示有待应用的正收益方案，可信装备写入后才可携带到新状态；
  `partial_socketed`此时转为`partial_no_positive`，表示已应用正收益且余孔无收益，保留原孔容量。
  重测失败撤销该槽旧pending方案，不能借旧物品指纹重新取得完成资格；恢复失败须停止并恢复状态。
  镶嵌探针保留 Item ID 和非物品输入。PoB 因当前候选首次生成默认 `Thorns/Explode` 派生组时，
  只在实际 runtime 确认精确 effect ID、不可辅助、非主组且未加入 Full DPS 后，允许在私有只读
  比较投影中排除该新增组；原有组、辅助、配置、天赋和其他物品仍须完整相同，不放宽全局状态 hash。
  部分镶嵌按 PoB 格式为每个空孔写入精确 `Rune: None`；该占位保留孔容量，但不计入实际符文、
  来源回执或已填孔数，未知符文名仍须保留并失败关闭。`crafting_options` 的上限元数据包含独立的
  `evidencePatch/evidenceRef`；当前补丁补齐的单件、Ancient Augment 与 Aldur 遗产共享上限同时用于
  搜索、可信装备及共享硬合法性检查。上限来源更新不改变原 PoB 数值模型的补丁认证，也不补造
  尚未被当前 PoB 数据收录的效果。
- `HumanReviewPacket`：供人工验收使用的安全报告。至少包含用户需求摘要、Agent 改写后的提示词
  或 `BuildBrief` 摘要、候选 BD 摘要、使用过的查询和工具引用、Judge 状态、硬阻断、注意事项、
  人工评分字段和是否建议进入下一阶段。`lifecycleEvidenceCoverage` 只根据最终可信 snapshot
  标出至多一个 `evaluatedStage`，其余候选声明阶段进入 `textOnlyStages`，不得把一轮 Judge
  误写成完整生命周期验证。
  多 attempt 的可信 Review 必须从 `artifact-selection.json` 继承
  `selectedAttemptIndex / artifactSelectionOutcome`；不得默认为最后一轮。单 attempt 与旧版
  无 selection receipt 的包保持兼容。
- `ToolFeedbackEvent`：开发/验收反馈，用于记录 Judge/工具无法评估、误判、覆盖缺口或接口难用；
  它不自动调整 graph / memory 权重，不自动放宽安全边界，也不自动改变工具行为。
- `FailureAuditSummary`：Agent 对某一轮 Judge 结果的可审查结论摘要，绑定本轮候选编号和快照编号，
  只记录失败分类、重试/停止/接受决定、计划改动、保留注意事项和停止原因；不能保存逐步推理。
- `GenerationAttemptRecord`：同一个生成运行中的一轮不可变评估记录，包含候选引用、可信临时状态、
  可信 Judge 报告和 `FailureAuditSummary`。轮次从 0 开始，最多为 2；非最后一轮必须明确选择继续
  重试，最后一轮必须接受或说明停止原因。Agent 文件在顶层只提交一次完整最终 candidate，每轮可只
  提交 attempt index、`prototypeBuildCandidate: {candidateId}` 和 failure audit；helper 先核对
  candidateId 与对应可信 receipt，再补全 state/Judge。显式提交可信字段时仍必须逐字段匹配 receipt。
- 装备完整度中的护符容量以最终 PoB `CharmLimit` 为有效值并封顶 3；腰带缺少 `Charm Slots` 为
  `unknown/missing_property`，不得折算为 0。90 级三槽/三护符是 Create 质量目标，只有已装备护符数
  超过有效容量才是硬合法性失败。装备优化默认目标为元素 60%、非 CI 混沌 30%，并返回
  `resistanceTargetMet`；`resistsCapped` 仅保留兼容语义，显式 75 目标仍受支持。
- `RetryComparisonReport`：P5.2 才需要的有限内部重试对比报告。它记录同一
  `feedbackMode`。`hard_only` 不产生 `scoreDelta/score_improved/regressed-by-score`，人工字段只
  复核硬合法性、重试范围和停止理由；`strict` 才保留分数变化和质量改善复核。它只比较同一用户请求下的安全摘要、
  Judge 结果和人工可审查差异，不写奖励记忆，不做长期进化式学习。若后续质量探索失败但旧
  passing baseline 被恢复，结果使用 `baseline_restored_after_regression`。

### FunctionalBuildMutationBatch

`apply_build_mutation_batch` 只接受单一职能的小事务，不是整套 BD 的通用大事务。`batchKind` 固定为：

- `bootstrap`：一次 `set_class`、一次 `set_level`，可选首项 `new_build`，最多 3 步；
- `mechanism_shell`：恰好一次主技能，加必要副技能与显式武器槽，最多 6 步；
- `skill_loadout`：只增加已决定的次级技能组，最多 8 步；
- `passive_delta`：精确天赋节点增删或已分配属性点改选，最多 16 步；
- `required_gear`：机制必需装备/珠宝，最多 4 步；
- `ordinary_gear`：普通装备补全，最多 10 步；
- `config`：一次配置提交。

所有 scope 都禁止搜索和 optimizer，总请求体不得超过 128KB。装备和珠宝必须提供显式 slot/socket；
批量 `equip_item` 使用 `craft_item` 特殊制作结果时还必须原样携带 `craftReceiptRef`；
需要 skill-group fingerprint 的精确编辑继续使用独立 CAS 工具，不能混入批次。只有首项为
`new_build` 的 bootstrap 可以省略 `expectedStateHash`；其余批次必须链入上一批
`outputStateHash`。

`allocate_passive.pathAttribute` 可选择 `Strength/Dexterity/Intelligence`，只作用于本次新增路径；
独立 `alloc_passive` 对应参数是 `path_attribute`。`set_passive_attribute` 操作要求精确整数 `node`
与 `attribute`，节点必须已经分配且由当前 PoB 树确认为属性点；同选项为幂等，不花点、不改路径。
`search_passives/get_passive` 均属于 Build 服务，返回 `isAttribute/attribute/attributeOptions`。
单工具与批次失败均核对恢复后的语义 hash，失败恢复不能用后续装备成功清除。

`equip_jewel` 要求显式已分配 `socket`，与通用 `equip_item(slot="Jewel <id>")`、批次共用事务性
写入和来源感知审计；特殊来源原样传 `craftReceiptRef`。它用于已有槽位的填入/替换，不分配天赋；
新增额外槽的正收益仍只能经 `apply_next_jewel_socket_decision` 应用。写后由活动 `Tree/Spec/Sockets`
与真实 Item ID 核对物品，不能借非活动 Spec 或 ItemSet 的珠宝镜像通过；Rare/Magic 珠宝要求
Item Level，Unique 数量使用静态来源限制。Checkpoint/Judge 与 artifact 检查也纳入这些树珠宝。
PoB 不把物品授予的免费槽写入 `Spec.nodes`，实时审计因此使用引擎读回的
`allocatedPassiveJewelSocketIds`；XML-only 结构检查仅确认显式已分配槽，不提升免费槽数值权限。
新保存要求 `hard_legality_v7` 的正式 Judge 回执（含 baseline 恢复），旧版须重验；既有 artifact 的
原审计版本与权限保留，不重写 manifest。Checkpoint 使用 `generation_checkpoint_v11`，不复用旧检查。
数值、preflight与硬合法性缓存按引擎对象和实际PoB进程实例隔离，每个引擎最多保留48个状态；
进程重建、同对象更换进程或运行时替换后，即使XML相同也必须重算，不凭可复用的OS进程号授权。
`validationRef`同时绑定该进程生命周期、语义状态、精确输出选择器和可用性指纹，不持久化为跨会话
凭据。会话释放不被缓存阻止；计算或缓存命中刷新期间上下文失效返回
`generation_checkpoint_context_changed`，不得返回旧通过/失败或重新发布旧缓存。
目录或会话审读排除改变时，Checkpoint以可用性上下文指纹区分同一PoB状态；恢复旧快照也重新应用
本会话已有的排除。`agentAvailabilityReviews`保持Agent审读权限，可收紧交付，不能证明内部Research来源。
共享 `lifeReservation` 检查使用 PoB 已取整的保留与未保留生命读回；生命保留导致剩余生命不足 1 时
返回 `life_reservation_exhausts_life`，同时用于辅助候选、装备候选、预检、Judge 和 artifact。
CI 不豁免这条规则；普通生命保留在仍有可用生命时保持合法，不重算百分比，也不据辅助名称特判。
`gemAvailability`对活动启用组的精确gem/game ID检查已确认移除项，新生成候选返回
`equipped_gem_unavailable_in_target_patch`；禁用组/宝石不混入活动组合，第三方历史参考只保留诊断。
没有移除命中仅为`checked_known_removals`，不是对所有组件做过当前可用性认证。
Python/Headless bridge 当前使用运行时合同 9，旧合同的 user-data 引擎不能覆盖新版 bundle；
属性、珠宝、辅助宿主与生命保留观察不会通过修改旧安装元数据获得权限。

`evaluate_next_jewel_socket` 在任何天赋/数值探针前复用 `audit_jewel_input`，核对静态珠宝底材、
Rare/Magic 的 Item Level、来源及共享物品合法性。普通词缀未识别时返回
`candidate_jewel_unrecognized_affixes`（`reasonClass=evidence_gap`），不把该词缀判作零收益或
自动认定非法；输入失败不写审计回执、不修改活动状态、不覆盖既有决定。
仅当同状态旧审计的全部可达槽都因 `current_safe_leaf_points_insufficient` 停在候选测量之前，
且没有候选测量、测量错误或待应用正收益时，才允许在相同 goals 和保护节点下更换候选输入。
新回执记录 `replacesUnmeasuredCandidateFingerprint` 并重新检查，旧 unknown 不自动升级为通过。
部分测量、缺字段的旧审计、目标/保护范围变化及待应用正收益仍受 pending 门禁保护；恢复失败保留
原回执并要求恢复活动构筑。

Lifecycle 的 `buildDefiningComponentKey` 与证据引用共用有界安全引用规则，保留 canonical key
中的 ASCII 撇号。URL、控制字符、空白、重复引用、组件 kind/key 前缀不匹配及不完整声明仍拒绝；
允许 key 进入声明不等于机制已验证，必须从同一活动快照重新观察组件。

执行器只回滚当前职能批次，不修改此前已经提交的 scope。失败回执必须区分
`attemptedOperationsBeforeFailure` 与 `persistedOperationCount`；只有 `rolledBack=true` 才能确认
输入状态已恢复。`rolledBack=false` 时必须同时返回 `atomic=false` 和
`recoveryRequired=true`；执行器标记该引擎并拒绝后续职能事务，只有显式从 `new_build` 开始的
bootstrap 可以解除恢复状态。调用者不得继续把活动引擎当作可信状态。RPC 成功不等于构筑质量通过；
每种 scope 只执行自己的轻量后置条件，完整性、资源闭环、数值和 lifecycle 仍由
`inspect_generation_checkpoint`、Judge 与可信 lifecycle receipt 验证。

P5.2 研究记忆对照不新增持久对照报告。现有创建入口支持 `--no-memory`：普通模式必须渐进查询
研究记忆并填写 `ResearchMemoryUse`；无记忆模式禁止调用研究记忆、禁止填写该结构，但保留其他
全部工具。人工用同一请求分别运行两种模式并直接审查结果；程序不自动宣布胜负。

P5.1 证据可信度边界：

- `ToolReference` 包含 `toolName/queryRef/summary/evidenceKind/reviewBasis`。旧条目缺少
  `evidenceKind` 时为 `unverified`，不能因名字或引用格式像工具就提升权限。
  `internal_receipt` 当前只接受通过本 run 时效、来源与资格校验的 Research query/contract 来源；
  其他工具的普通返回没有此处可查询的内部回执注册表。`agent_reviewed` 必须填写实质
  `reviewBasis`，说明实际审读的精确证据和条件；它是 Agent 声明，不证明后端核验了工具执行或
  语义真伪。`TransientBuildStateRef` 和 `JudgeAdvisoryReport` 仍必须来自本次可信评估凭据。
- Blueprint 的 grounded/inferred/rejected 不得依赖 unverified 引用；hypothesis 可保留这种来源，
  但必须列 verificationTasks；unknown 不提升。服务端保存 `evidenceAudit`（版本
  `generation_evidence_v1`）及 `evidenceAuditHash`，明确 `semanticTruthVerified=false` 与
  `numericLegalityVerified=false`。引用身份受检不等于机制结论、数值或合法性获证。
- Draft 的 `evidenceAuditHash/designToolsHash/designToolRefs` 绑定 Blueprint 来源层级和实际设计引用的
  toolName/queryRef/evidenceKind/reviewBasis；summary 叙述与无序引用顺序不刷新 marker。
  增加无关诊断引用不构成设计修订。Judge后可按原执行合同追加真实、已审读的验证旁证，但原设计
  引用不可移除/替换或提权。来源审读依据改变时重新验证受影响的 Blueprint/Draft。
  `designEvidenceUses/designEvidenceUsesHash`另外按packageId与planId冻结原来源关联（包括未列入
  ToolReference的Research来源）；原引用仍出现在其他claim/package/plan中不能替代原关联保留。
  同subject只允许原集合保留并追加旁证；跨subject移动/交换或删除引用必须重验Draft。
  Judge 的 raw-free 历史设计 bundle 保留这些引用与权限，baseline 的 `selectedDesignEvidence`
  返回原 `toolReferences/evidenceAudit`；最终输出和 Review 继续核对原绑定，不能重新声明为更强证据。
  当前输出合同为 `generation-agent-output-v5`；旧受管 run 必须重启，旧 artifact 不批量重标。
  已是v5但缺新关联marker的活动Draft必须完整重验；旧Judge bundle只有在精确历史绑定通过后，
  才能从其原ResearchExecutionPlan读取原关联，不能根据新candidate补造或回写原marker。
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
  旧候选不能作为新请求的输入；未消费运行四小时后过期；
- 同一运行在最终验收前可以写入初始评估和最多两次重试评估。每轮可信凭据独立保存且不可覆盖，
  `trusted-evaluation.json` 只作为最新一轮兼容指针；最终 helper 必须逐轮核对 Agent 提交的
  `generationAttempts` 的 attempt index、candidateId 与可信凭据；完整最终 candidate 只需在顶层
  提交一次，不要求在每轮重复；
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
  duplicate_support_gem、invalid_support_gem、illegal_equipped_item_affixes、
  rarity_not_allowed_for_base_domain、endgame_flask_loadout_incomplete；
- playability failure codes：`severe_elemental_resistance_shortfall`（仅历史 artifact 兼容读取；
  当前新 Judge 不再发出）、
  `below_playability_floor`、`catastrophic_defense_shortboard`；
- quality warnings：`elemental_resistance_below_cap`（仅历史兼容）、`negative_chaos_resistance`、各 offense / Max Hit
  quality target miss，以及生成候选 offense delivery evidence 为 limited/unavailable 时的
  `offense_delivery_not_established`；后者限制综合档位和最终交付，但不属于确定性非法。strong
  direct DPS 低于地板时使用 `below_playability_floor`，不复用 delivery warning；
- DPS 语义遵循 PoB：`AverageDamage` 是平均命中，`TotalDPS` 是 Hit DPS，`CombinedDPS` 加入当前
  技能的已建模次级/持续伤害，`FullDPS` 汇总被纳入的 skill actors/groups；
- short-circuit state：physical-invalid failure 必须标记被 blocked 的 score dimensions；
- reward eligibility：熔断 evaluation 不能产生 positive reward；
- reward strength：`BuildEvaluation` / `BuildComparison` 使用 `rewardStrength` 区分
  `strong`、`limited` 和 `none`。只有 strong 才能被未来明确规划的 reward memory
  消费；limited 只允许作为观察或弱信号；
- 非终局空升华：campaign / maps-entry 样本缺失 ascendancy 可以追加
  `missing_ascendancy_non_endgame_caveat` 并继续评估；endgame 样本缺失 ascendancy 仍是
  `invalid_class_ascendancy_pairing`；
- recovery 主池：生命侧使用 `LifeUnreserved`，不是 `Life`；`Life`、`LifeReserved` 和
  `LifeUnreservedPercent` 仅用于诊断和 fallback；
- CI：runtime contract 7 起的 `get_build/get_defenses.defenseMechanics` 读取活动玩家 PoB
  `mainOutput.ChaosInoculation`，覆盖天赋、装备与珠宝授予的实际状态；`keystones` 仍只表示树分配。
  该观测包含 `schemaVersion=1/source=pob_main_output/status=observed|unavailable`；明确 false
  或不完整的新观测不回退到树节点。预检、Judge、防御评分和抗性目标共享同一防御状态投影。
  生命为 1、装备名字、非活动词条及混沌抗数值均不能证明 CI；卸除或禁用来源后重新观察。
  CI 下 chaos score 按混沌免疫处理，不使用 `ChaosMaximumHitTaken` 的 nil/0/超大值反推。
  旧静态 readback 保留树字段兼容，不因此获得新原生观测或升级历史回执；新运行使用匹配合同的桥接；
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
  limited reward；非法或 core-unmodelled comparison 不进入未来 reward memory；
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
  `schema_version = 5`（legacy deep record）继续兼容；safe-review v3 新写入使用
  `ResearcherOutput.schema_version = 6` 与 `DeepResearchRecord.record_schema_version = 2`。
  Research Memory SQLite schema 独立为 7，不能把这些版本号混为一个字段。
- `DeepResearchRecord`：同一案例通过 `research_group_id` 聚合成多条聚焦记录。每条只表达一个主要
  知识单元，保存 title、summary、content、record kind、stable component keys、条件、失败条件、
  safe evidence、版本和作用域。中文 `content` 原则上不超过 400 字，英文原则上不超过 250 个单词；
  只有不可拆分的核心机制链可以携带 `length_exception_reason` 少量超出。
- `BuildFamily`：由已解析的 `ascendancy_key + primary_skill_keys`（主输出技能**集合**）确定。
  `primary_skill_keys` 是研究者声明为 `primary_damage` 角色的全部 skill stable key（CoC 双输出
  构建可含多个）；`primary_skill_key` 保留第一个作为兼容单值。clear/boss/triggered-payload
  自动副技能、trigger-host（CoC/Spellslinger 等）、`familyCoreSkillKeys` 均**不参与身份**，只作
  Family 内元数据。技能名以 gem 等价规范化后比较（同一宝石授予的弹药/直击变体视为同一技能，
  见 `server/knowledge/skill_equivalence.py`）。support、暗金、装备、防御和资源方案不参与 Family
  身份。身份相同的档案自动归入既有 Family，不新建 sibling 档案。
  BuildFamilyKey 保持 scope-independent；Family 的可变元数据和 evidence 使用
  `(knowledge_scope, build_family_key)` 复合身份，Global 与 Local 不共享统计、合并或 secondary
  skill 派生状态。
- `Canonical KnowledgeUnit`：`DeepResearchRecord` 通过 `BuildFamily + record_kind + kind-specific
  core component roles + gearSubjects + skill/support/host topology` 生成 scope-independent
  `knowledge_key`；它标识机制主题，不再限制同scope只有一个可变正文。不同条件/结论保留不同record，
  精确相同投影复用record；同来源修订只移动自己声明，共享记录写时复制，不能按正文丰富度覆盖他源。
  标题和正文相似度不授权跨来源合并。schema2 的任何记录只要结构化包含 resolved support，就必须通过
  `typed_payload.supportPackages` 保存根技能及其真实 socketed supports；同一技能、不同辅助包是同
  Family 下不同知识单元。结构证据不足时保留原记录，不进行
  猜测性归并。
- `source_specific_random`：Cultivated/mutated 等随机实例依赖写入
  `typed_payload.availability` 和 `sourceSpecificComponentKeys`。它拥有独立知识身份，只用于案例解释；
  默认 Create 召回排除，也不能生成 planner-visible Pattern。
- 无物理图节点的普通资源方式通过 `typed_payload.resourceMechanisms` 保存 lower_snake_case 机制标签，
  例如 `mana_leech`、`mana_flask`。已归入 Family 但不能生成 `knowledge_key` 的记录不得作为 clean
  acceptance 入库，必须补足结构化身份或暂缓。
- `DeepResearchRecordEvidence`：当前来源声明的主键为
  `(knowledge_scope, knowledge_key, source_case_ref, source_claim_key, game_patch, passive_tree_version)`。
  每项显式保存`record_id + accepted_projection_hash + binding_issue`及实际组件、条件、版本。只有精确
  record/hash匹配、binding_issue为空，且record/schema/source state/provenance等门槛都通过才授权Create。
  schema1/unknown新写可以保留精确结构定位及diagnostic issue，不能升级权限；旧库无从证明的绑定保持NULL。
  evidenceCount按当前结论的独立source_case_ref计，不按claimKey、提及次数或历史来源缓存计。
- `source_claim_key`：proposal根字段，safe review使用`sourceClaimKey`，默认`default`；安全小写slug，
  最长80字符。相同来源同主题的并存条件分支用不同稳定key，修订复用原key；不放入typedPayload、
  Family、机制主题或内容hash。record-detail的`sourceClaims`返回当前来源与key索引，Create只返回
  所选lane的索引；修改key不增加独立来源证据。
- `comparisonRecordBindings`：执行合同中，完整exact unit已由权威lane提供时，对照来源复用该权威
  package，保留自己的record、来源版本与targetApplicability诊断。不能代替权威深读、premise解决或
  借对照版本提升权限；条件不同的包保持独立，comparison-only不新增跨record合并。
- `pobReadbackAudit`：`reviewed/unmodelled` 必须绑定当前 lease packet 的精确 `snapshotRef`，
  `unavailable` 必须匹配该 packet 的真实状态；未绑定的自报 disposition 不能关闭
  `resourceDefense` coverage，也不能形成 clean。
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
- `AgentSemanticScopeReviewRequirement`：Pattern 新写入必须保存外部 Research Agent 的 typed
  适用范围审核（当前案例证据、case-only 或 conditional-transfer-hypothesis、supported verdict、
  safe evidence refs）。它进入既有 `context_requirements` JSON，不增加 SQLite 列；旧 Pattern 查询时
  标记为 `legacy_unattested`，不得按自然语言措辞提升权重。`recurring_observation` / `likely_pattern`
  必须使用 `current_family + family_specific` 或 `multi_family + population_pattern`，且非单案 Pattern
  的 `sample_count` 不能超过 distinct `source_case_refs`；审核 evidence refs 必须属于 Pattern 自身。
- Safe review contract v3 要求每个启用技能容器有 `sourceSkillGroupReviews`，并在
  `supportPackages` 临时绑定 `sourceGroupRef + rootSkillRef`，同时让 `supportKeys` 与
  `socketedItemRefs` 逐项对应；验收以物理实例 ref 拒绝同一实例的重复归属，但允许不同根技能下的
  不同实例使用同一个 support stable key。验收后只持久化根技能与其 socketed support topology，
  source-local refs 不进入 durable record 或知识身份。新 review 的 `deliveryRole` 只允许 `direct`；
  socketed active payload 的 host/payload 机制由组件角色和机制记录表达，
  不得用 PoB 计算影响对象改写物理插槽关系。`gearSubjects` 区分正文型装备主题，`sourceStateScope` 区分
  active/alternate/state-agnostic/unknown。`mechanicAudit.wiki` 保存候选来源 `matchKind` 与 Agent 的
  `relevanceReason`。页面标题、redirect、ID 与搜索排名只证明页面身份/候选来源，`wiki.status` 才是
  Agent 阅读内容后的 supports/contradicts/silent 判断。
- `ResearchRunRef`：发布产品只暴露 `research-run:<runId>`，服务端确定性映射到
  `user_data/research/runs/<runId>`；不得向 Agent 返回或接受 queue DB、review、quarantine、插件 cache
  内部文件或 Research Memory 的绝对路径。
- Typed review transport：`initialize_research_review` 返回内存安全对象，
  `validate_research_review` 保存并校验 Agent 提交的 safe review，`accept_research_review` 对调用方提交的
  同一完整 safe review 再执行正式验收；Agent 不直接编辑运行态文件。
- `ResearchWriteReceipt`：一案一行，绑定 run/sample、attempt/packet/review/contract hash，保存
  candidate→scope/key/recordId、write action、evidence 与 before/after projection hash。pattern、deep、
  edge、receipt 和一次 `memory_revision` 在同一 `BEGIN IMMEDIATE` 事务提交；queue/ledger 在提交后
  幂等收尾。`get_research_write_receipt` 只供审计，不生成 Create DQ。
- 同名不同`knowledgeKey`默认并存；跨主题修订必须给record-root `sourceClaimRevision`
  （proposal为`source_claim_revision`）的knowledgeKey/recordId/projectionHash，来自本来源当前深读。
  该请求不进入知识正文/投影；整批写入前核对旧精确claim、状态与版本，拒绝陈旧绑定及批内互相撤回。
  原claim资格与record lane资格分别返回`claimBindingStatus/currentEligibility`和
  `recordLaneEligibility`；不能借兄弟claim证明已撤销的原声明，也不禁用合法lane知识。
- URL在入队冻结为已解析XML并以冻结材料的完整hash建身份；之后claim/resume不得重新抓取该URL。
  quarantine和packet读取重验hash/sample/ref及XML一致性，读取packet也重算声明的safeHash。
  旧URL-only材料不重标、不补造hash，明确保留不可恢复诊断。查询/恢复使用不可创建的已有库连接，
  缺queue不得复活已清理任务；status与cleanup共享run锁。resume的dry-run组合在任何清理前拒绝。
- Research完成诊断与上述receipt同事务提交：`completionDiagnosticsVersion=1`、
  `researchCompletion=complete/needs_followup/unknown`、`completionScope=case/supplement`，保存
  deferred/未解析/coverage计数、typed原因及安全定位，不保存被拒绝正文。缺失计数保留unknown；
  `completionDiagnosticsIncomplete` 阻止缺失信息被缓存默认零升级为clean。补录成功不自动关闭父案。
- 辅助组合拒绝诊断保留全部`unsupportedPairs`端点、类型条件和来源证据；自然语言预览单独限长，
  不把全部配对拼成一条过长caveat而遮住原始拒绝原因。预览限长不删除结构明细、不放宽copy-safety，
  也不能将被拒记录或来源缺口变为通过。
- Research的validate/accept/retry结果回传与已审查知识使用同一`durable_knowledge_flags`规则：
  有界核心辅助包、局部天赋连接和装备联动的诊断文字不因组件数量在末端再次拒绝；原始材料、
  可复制角色链接、禁用字段和过长正文仍拒绝。队列/控制响应保持严格默认；此区分仅作用于回传，
  不改变schema、resolver、辅助兼容、缺口或接受权限，也不将诊断切片当成整案校验。
- `acceptedCount` 与 `researchCompleteCount/researchNeedsFollowupCount/researchCompletionUnknownCount`
  分离。原诊断不改，后续`effectiveResearchCompletion/effectiveResearchCompleteCount`用于完成性判断。
  默认cleanup拒绝尚有有效缺口的案例；显式放弃或锁定期限到期也不能绕过活跃lease与accepting恢复。
  删除前在user-data `research/run-audits/<runId>.json`保存安全审计；同runRef状态可返回archived，
  但该归档不授权Create或读取原料。旧receipt不改写，已知旧queue/report缺口以独立provenance保留。
  延迟删除还绑定followup指纹与Memory revision，并重核支持投影；仅重试本次指定run，其他排队项
  保留待定向处理。删除失败仍保留重试入口。
- `ResearchFollowup`存于user-data `research/followups.sqlite`，不进入知识种子或Create授权。
  `gapRef`由不可变receipt及诊断位置派生，coverage/deferred/unresolved明细抵扣对应计数，实际缺项
  保留aggregate/unknown。`submit_research_gap_review`以revision CAS及request幂等追加
  resolved/not_applicable/successor_evidence/reopen；前两者必须引用较晚可信receipt的实际写入记录及
  当前精确projection/claim。来源以完整`sourceHash`为权威，16/64位`sourceHashRef`须与其匹配，
  各claim保留原ref；同时核对patch/tree、knowledgeScope、sourceStateScopes及已绑定活动组合。
  旧短ref缺full hash、旧场景证据缺失或legacy provenance不提升闭合权限。原回执保存sourceContext，
  新recordWrites补sourceStateScope/sourcePobVersionOrCommit；不从当前已修改记录反推历史证据。
  新组件/候选缺口还保存安全record/component subject指纹；局部闭合必须匹配实际typed解决证据，
  同一missing/deferred不能关闭。完整case的resolved也不能省略已知目标组件；旧组件身份不足时拒绝
  猜resolved，真实not_applicable仍可完整复核。其他独立partial缺口不妨碍本项有效解决。
  unknown/aggregate必须完整case证据；保留原料可显式选择`re_research_scope=full_case`和sample IDs
  建新run完整复核，来源与Family不重标，不要求制造知识改动。普通supplement继续要求有实际增益。
- `ResearchReacquisition`存于`research/reacquisition.sqlite`，按已解析league+characterRef原子预留。
  request与parent/sample/origin fingerprint/child run不可换绑，无超时抢占；仅指定角色可越过普通
  accepted去重，旧intake行不刷新。未命中为not_found_within_search_scope。返回exact_source或
  successor_snapshot，均保留独立run和真实patch；后者不能关闭原案事实。队列/归档恢复须核对lineage、
  full hash/ref、league/patch及已接受receipt；已释放请求不能继续collector。
- `retentionPolicy`创建时锁定UTC createdAt/expiresAt/retentionDays/policyVersion，默认7天、范围1–30。
  resume/claim不续期；共享claim上限24小时，packet TTL与租约同源。到期停止新claim，既有有效lease
  及accepting/finalization保护继续；cleanup调用时判断到期并保存cleanupReason，状态查询不删除。
  没有后台模型或定时任务，离线期间不承诺到点物理删除。legacy缺policy保持unconfigured，可明确处置。
- `ResearchQuerySession`：每次 `create_compact` 首查创建唯一 retrievalRef，在固定
  `memory_revision` 上构建 actual-content manifest。单一 cursor 连续分页，每页最终 UTF-8 JSON
  ≤65,536 bytes；只有同 session 的 `0..terminal` 完整链且 complete 才授权 Create。
  `deepRecordEligibilityVersion=1`绑定本次深读资格语义；coverage/index/premise与实际Create读回
  共用`valid`、未被替代、schema2、standard availability、活动/状态无关来源及精确projection绑定。
  来源scope、目标patch/tree及补丁采纳限制继续生效。普通Research诊断仍可读needs_revalidation。
  每页可信result_contract原样保存该页`familyRecordCoverage`（本页没有时为空数组）；完整页链
  合并后，Create检查所有requiredDeepReadRecordIds是否深读并逐项决定，摘要不算深读。
  旧资格版本的raw查询不能启动新session，旧session不能继续签新页；旧授权页缺版本或coverage
  时不可采纳，必须重新查询。该过程不修改旧知识、补造旧回执或批量提升权限。
- Deep-record validate-only 同时返回 `inferredBuildFamilyKeys`、`resolvedTargetFamilyKeys` 和
  `familyResolutionPreview`；兼容 `buildFamilyKeys` 使用只读 `join/expand/new` 后的 target key。
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
- 每个 Judge passed 且 `HardLegalityAudit.hardLegalityReady=true` 的 attempt 都可成为 passing
  baseline。`save_final_build_artifact(attempt_index)` 可以选择任意仍可信的 passing attempt，
  不再机械要求最后一轮；
- Judge 的精确 XML 只在当前 MCP 进程内短暂保留，不写进 run receipt；保存最新 attempt 时仍
  重新读取活动 PoB，用 `semanticStateHash` 拒绝真实构筑变化。保存旧 passing attempt 时不要求
  活动 PoB 回退，但必须使用内存中该轮精确快照和同 state hash 的合法性回执；
- `PlayerStat`、`FullDPSSkill` 等派生输出刷新不算构筑变化；如果进程内精确快照已经丢失且原始
  XML hash 也不再一致，保存必须以 `trusted_evaluation_snapshot_unavailable` 失败关闭并要求重新
  评估，不能把新 XML 冒充 Judge 快照；
- 每个生成运行最多一个 artifact，不覆盖；
- 选择旧 attempt 必须提交有界 `selectionReason`，并证明后续发现仅为
  `laterFindingsScope=candidate_delta_only`。若后续问题影响旧 baseline、范围未知、精确快照因
  进程重启丢失或 Judge/合法性绑定不一致，必须失败关闭；
- 质量增量也可能在共享合法性预检中被拒绝，因此不会产生新的 Judge attempt。此时保存器仍须
  检测到活动状态已经偏离 passing baseline，并只在 `selectionReason` 与
  `laterFindingsScope=candidate_delta_only` 明确、旧快照仍在进程内且绑定一致时恢复 baseline；
  不能因为“最后一条 Judge receipt 仍然是 passing attempt”而误把当前非法活动状态当成该快照；
- 保存写入 raw-free `ArtifactSelectionReceipt`，记录实际 attempt、state hash、Judge snapshot、
  选择结果（包括 `baseline_restored_after_regression`）和 artifact id。review 与 retry report
  以该 receipt 的实际保存 attempt 为最终候选，而不是最后一次 attempt；
- review consumption 不属于构筑证据。正常顺序仍是先保存 artifact 再 review；若旧任务误先消费
  review，保存仅可在 run token、实际选择的 candidate/attempt、精确 Judge snapshot 和语义
  `build_state_hash` 全部一致时恢复，并返回 `orderingRecovery.reviewAlreadyConsumed=true`。
  这不能绕过任何 trusted evaluation 或完整度检查；
- 失败轮次不保存完整 PoB XML；
- 跨机制修订选择baseline时，精确快照中的历史bundle、receipt、artifact manifest与selection
  指纹必须一致，并声明`candidate_delta_only`及选择理由；返回的`selectedDesignEvidence`只含
  原Blueprint ref/正文、ResearchMemoryUse/ExecutionPlan与hash，不含完整candidate、XML或run token。
  设计验证、Judge、保存共用run锁；发布selection后禁止重写该run设计marker或追加Judge。
- 保存前可重算同Judge快照及精确输出的lifecycle，manifest记录新结论、保留原其他quality checklist；
  原其他quality限制不提升，同状态/输出的`currentAdverseEvidence`可单向收紧。原Judge receipt不变，
  已保存旧artifact不追溯升级。任意等级的roundtrip/lifecycle恢复失败都停止发布并置引擎恢复门禁，
  `recoveryRequired=true`不能继续写artifact或selection。
- `lifecycleDeclarationBinding`可选保存在manifest，含观察版本、语义hash、精确target及typed输入；
  不保存pass/XML。默认artifact lifecycle先验证该绑定，同session同状态/输出的声明（含显式空）
  优先；无session时才回读保存输入，再从PoB重新观察。损坏绑定拒绝；旧无绑定且无声明时，
  需要该声明的检查保持unknown。
- XML 只能存在本地 artifact store，不能进入 `HumanReviewPacket`、聊天、研究记忆或 Git；
- artifact 必须能在 MCP 重启后重新载入 Headless PoB。

生成候选中的 `Scaffold ...` 占位装，以及 rare/magic 装备缺少 `Item Level`，属于共享
`HardLegalityAudit` 的 Judge 前硬失败；修复前不写 Judge receipt，`attemptConsumed=false`。
符文/灵魂核心、天赋珠宝、药剂和护符仍由 Agent 填写或记录明确不使用理由，属于接受候选前的
advisory，不是程序自动配装规则。

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
- `artifacts` 固定包含 `pob_xml`、`pob_import_code`、`official_build`、`poe_ninja_pob` 四项；
- 本地文件项包含 `status`、`outputPath` 或 `errorCode`；poe.ninja 项包含 `published` + `url`
  或 `failed` + `errorCode`，并标记 `publicExternalUpload=true`；
- exported count 和 expected count；
- overall status：全部成功为 `exported`，部分失败为 `partial`；
- response 不包含 raw PoB。

Agent 最终答复必须逐项转述这四项，不能因为某项失败或忘记调用而省略；不得回显上传的原始 PoB code。

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

## 插件发布种子合同

Codex 发布包携带两类只读首装种子，不把用户运行库本身当作发布资产：

- `ResearchReleaseSeed` 是一个通过 SQLite `quick_check`、与运行时 schema 完全一致的净化库。
  只允许 `creator_visible / train_context / (global_seed|local_user) / copy_safety=passed / status=valid`
  的知识记录，
  `source/case/candidate/query/rejected/revalidation/decay` 等运行态表必须为空；meta 只保留 schema、
  backfill 和 `release_seed_kind/version/created_at`。种子不得包含原始 PoB/XML、完整 URL 或本机路径。
- `PhysicalGraphSeedManifest` 保存 `schemaVersion`、`snapshotId`、相对 `snapshotFile`、SHA-256 和安全
  数量摘要。不得保存构建机的绝对 snapshot/index 路径。

首次启动时，服务把种子原子安装到用户数据目录。目标 Research 库或可用物理图已经存在时不得
覆盖；插件升级也不自动重置用户新增知识。`LearningMemoryReleaseSeed` 是通过完整事件 schema 与
durable copy-safety 校验的 JSONL；首次运行仅在本地 Learning Memory 不存在时安装。发布包不包含
campaign 状态、quarantine、价格缓存或完整第三方角色材料。

## Phase 7 对照学习合同

### FamilyTarget

对照学习中唯一允许传给盲测 Create 的 reference 派生合同：

- `schemaVersion`；
- `buildFamilyKey`；
- `ascendancyKey`；
- `primarySkillKey`；
- `secondarySkillKeys`；
- `targetLevel`；
- `versionContext`：game patch、passive tree、PoB version/commit；
- `safeEvidenceRefs`。

Family 身份必须由现有 `BuildFamilyIdentity` 推导。升华、主技能、核心次级技能或等级歧义时不生成
`FamilyTarget`。装备、天赋、辅助、配置、机制摘要、来源 URL 和 Judge 结果都不是该合同字段。

### BlindCreatePacket

必要字段：case/campaign 的安全引用、`FamilyTarget`、默认目标、Research/Memory 使用许可和
`referenceBlind=true`。默认目标固定为“软核交易、无固定预算、综合强度与可玩性优先”。

packet validator 必须递归拒绝 reference gear、passives、skill groups、mechanic summary、raw source、
PoB code/XML、完整 URL、reference Judge 和 comparison 内容。Create 结果必须同时记录完整
claim-bound `researchMemoryUse` 与 `learningMemoryUse`：前者只能引用服务端强制 Global 的完整
Research 页链（no-match 的 selected lane 为空但 effective scope 仍为 Global）；后者绑定活动 Create
claim 的 Learning query receipt、完整召回 ID、每条经验的
`adopted/caveated/rejected`、应用说明和 harmful/incorrect 观察；提交时必须与服务端安全收据
完全一致。

### BuildComparisonReport

当前 schemaVersion=2。报告引用两个安全 evidence packet，不嵌入完整构筑镜像。固定十个维度；每项包含：

- dimension；
- verdict：`generated_advantage/reference_advantage/tradeoff/tie/unknown`；
- generated/reference safe evidence refs；
- 简短 rationale；
- critical gap 标记。

非 unknown 维度必须有双方非空、唯一、安全引用；提交服务核对每项引用属于本案例已保存的对应
`SafeBuildEvidence.evidenceRef/safeEvidenceRefs`，跨案例、错侧或未知引用拒绝。gap 引用也必须属于
双方来源集合，gapId 唯一，维度 criticalGap 与该维度是否存在 critical typed gap 完全一致。
引用绑定不代替 Comparator 阅读与判断证据是否支持结论。
FamilyTarget、SafeBuildEvidence、DimensionComparison和ComparisonGap共用安全bounded reference
字符合同：3–240字符，允许并保留canonical ASCII撇号，如`unique:pob:kalandra's_touch`。
生产者与消费者一致校验；不得去掉撇号改名，也不放松重复、错侧/跨案与精确来源成员检查。

派生 metricsVersion=2，显式保存 `unknownDimensionCount/comparableDimensionCount/evidenceBound/
trendEligible/tradeoff`。notWeaker 仅计 generated_stronger；tradeoff 单列，不自动非劣。
只有 v2、双方绑定、十维全部可比较、双方合法性已知且总结果非 incomparable 才可能进入趋势。
旧 schemaVersion=1 仍可诊断，但不自动取得新覆盖权限；无绑定的单独 schema validation 也不授权趋势。

总结果只允许 `generated_stronger/reference_stronger/tradeoff/incomparable`。Judge 附件必须带
`advisoryOnly=true`，报告 validator 禁止出现自动 winner 来源。reference 更强时，root cause 使用
Phase 7 固定七类。报告同时保存 Family/等级匹配、合法性/modelability 状态和安全的时间指标。

### LearningMemoryEntry 与 LearningMemoryCorrection

Learning Memory 是 Research SQLite 之外的本地 append-only store。维护者的安全事件流可以净化为
`data/comparative_learning/learning-memory.seed.jsonl` 并随 Git/插件发布；运行时仍复制到用户数据
目录后追加，不能直接修改捆绑种子。

Entry 必要字段：lesson id、lesson、scope、Family/等级约束、dimension、conditions、exclusions、
recommended Create behavior、verification tasks、安全 comparison/source/candidate refs、patch/tree/PoB
版本、状态、copy-safety、reviewed case 和时间戳。状态只允许
`active/narrowed/superseded/deprecated/stale`。

能归入 `DeepResearchRecord` 现有 record kind 的具体技能包、机制链、轮转、装备、天赋、防御、
资源等知识，必须以 `dbFit=true` 拒绝写入 Learning Memory。

Correction 是不可变追加事件，action 只允许 `narrow/revise/supersede/deprecate`，保存修改前后
摘要、原因、触发案例、安全 evidence refs 和 replacement lesson（如适用）。查询返回当前有效
lesson 及相关 correction/do-not-repeat 摘要。已被 correction 覆盖的同义 lesson 再次提交时，必须
引用旧 correction 并提供新证据；否则以 `corrected_lesson_requires_new_evidence` 拒绝。

### LearningCampaignState

Campaign 默认为 10 个串行案例和 3 案例滚动窗口。durable control state 只保存安全引用，使用
`campaignId/caseId/taskId/claimId/threadId/phase/revision` 做 CAS。Reference/Profile 与 Comparator
共用任务绑定；Create 必须使用不同任务。Phase checkpoint 可暂停、恢复和显式 retry，但 Create
一旦提交后不能为同一案例再次启动，Compare 后也不能回到 Create。

Campaign summary 核对 comparisonRef 内容指纹，从当前 v2 报告和本案例双方安全 packet 重新派生
比较指标，不信任旧派生缓存。
其他累计指标与阶段耗时保留；旧报告或重验失败时标记 legacy_or_unverified，不改写原状态文件。
缺失/非法数值中位数返回 null，不补成 0；unknown、缺覆盖、旧资格或终态失败均不能支持进步信号。
十例全程完整绑定覆盖后，趋势判断只比较前 3 例与后 3 例；只有
not-weaker 上升、reference-advantage 中位数下降、critical gap 不增加、合法性和 Family 匹配不退化
时才输出 `initial_progress_signal`，否则输出 `function_complete_learning_unproven`。该结论不是因果
证明，也不是 Judge reward。

## ResearchMergePlan v1

Deep record 的语义合并由外部模型提出、独立模型复审，服务端只做有界候选、字段处置、召回、
projection、scope/Family 和 CAS 校验。plan 逐项保存 action、target/source record IDs、完整合并后
记录、每个 canonical 字段的 preserved/revised/retired_with_evidence 处置，以及 reviewer 结论。
涉及陌生、版本敏感或冲突的 PoE2 机制时，reviewer 必须查询 GGG、pinned PoB 或固定 revision Wiki，
只保存安全 evidence ref；权威来源缺失或冲突时 reject/keep-distinct。preview 不写库；apply 必须绑定
preview 的 Memory revision 与 plan hash，并由用户显式批准。旧 evidence 不自动升级为新 projection
授权，Pattern/Edge/Fragment 不属于此合同。

## Research PoB Readback v4

配置记录保留`configSetId/configSetIndex/title/isActive/valueType/kind`；Input与Placeholder区分。
配置身份通过`config-sets`分页，紧凑摘要不重复附全量身份清单；含外层sampleId的完整响应计入预算。
超长配置项以`evidence_fragment`连续分页，无损重组后才是完整证据。技能/物品/Spec/珠宝的结构提取
与readback共用选择器：Spec按列表位置，外部Spec.id仅作别名，数字ID规范化一致，兼容根级旧Spec。
`configIdentity`与build/activeSets保留来源活动选择，legacy平铺配置按上游默认组兼容；缺失、重复、
无效或不存在的多组selector不能猜选。readback的`stateBinding.activeSets/sourceActiveSets`绑定
skillSet/itemSet/passiveSpec/configSet，来源与PoB实际导出不一致时为unavailable。另绑定
`activeConfigSet/sourceActiveConfigSet`、sourceHashRef与`sourceSnapshotHash`；快照指纹也覆盖
Placeholder，不能用忽略该字段的通用语义hash授权旧读回。旧无绑定available receipt降级为unavailable，
重新claim时重算。非活动配置可作有身份的场景证据，不能混入当前活动数值结论。
新PoB的`CustomModifierBlock`在config视图保留`blockIndex/blockTitle/enabled/value`，并分别标记
`effectiveInConfigSet/appliesToActiveConfig`。正文读取遵循原生Lua的首文本段语义，legacy迁移按
实际赋值顺序判断；禁用块和其他ConfigSet不授权当前数值。现代块readback还绑定
`customModifierSemanticsVersion/sourceActiveCustomModifiersHash/activeCustomModifiersHash`，
来源与PoB实际活动修饰不一致时不可用；旧缺该绑定的现代块回执须重验，不批量提权。

Spirit 总账区分 `spiritReservedCapped` 与真实 `spiritRequested`。requested 由 PoB 最终
`Spirit - SpiritUnreserved` 得到；`spiritUsed` 仅作一个兼容周期的 requested 别名。合法性同时核对
available/requested/unreserved/overBy/capped 的恒等式，缺失或矛盾为 unverified。readback 还保存当前
`activeWeaponSet`；技能与 socketed items 的物理关系来自来源导出结构，不由 PoB effect applicability
重建。本阶段不生成双武器快照，也不以
逐组开关差值推算 Spirit。

旧版 `FinalBuildArtifact`（schema 1）在新的交付选择中默认是
`legacy_spirit_unverified`。`preview_final_artifact_spirit_revalidation` 只读加载原 XML、核对
source hash 并生成绑定计划；用户批准后 `apply_final_artifact_spirit_revalidation` 追加
`spirit-revalidation.json` 事件。`passed` 才恢复新交付资格；`spirit_budget_exceeded` 和
`legacy_spirit_unverified` 继续阻断。旧 manifest、XML、Judge receipt 均不改写。

尚未保存 artifact 的 schema-1 evaluation receipt 不做跨版本包装；保存入口返回
`legacy_evaluation_requires_rejudge`，必须用当前 Judge 重新评估后再保存。
