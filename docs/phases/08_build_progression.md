# Phase 8 - 目标锚点优先的联网开荒与完整成长流程

普通 `/poe-bd-create` 在调用任何工具前必须先确认用户是否需要完整开荒过程。只有用户明确要求
单个固定目标 BD 时跳过；用户选择“需要”后才进入本 Phase。模糊的“附带开荒策略”必须先确认，
不能静默降级成文字建议，也不能未经确认直接启动耗时 progression。

## 阶段状态

功能实现完成候选，处于最终验收阶段。当前实现保留开荒证据、成本画像、多阶段 artifact、
恢复/重试和完整成长包导出，并把编排修正为：

```text
按职业/精确版本从 Research 发现最多 10 个成熟 Family
  -> 比较并完整排序实际返回的全部 2–10 个候选
  -> 第一名作为目标、第二名作为一次性备用
  -> 普通单阶段 Create 生成选中的目标 BD
  -> 绑定不可变 Target Anchor
  -> 有界联网研究同职业开荒
  -> 设计开荒/桥接/目标路线
  -> 分别创建目标之前的真实里程碑
  -> 用同一个 Target Anchor artifact 闭合目标阶段
  -> Route v3 + 完整成长包
```

普通单阶段 Create 的等级语义、Research 查询、有限内部 retry、artifact 保存和导出保持 Phase 5
既有行为。Phase 8 的 `82/92` 生命周期验证门槛只属于 progression 蓝图与
`verify_lifecycle_stage`，不能反向修改普通 Create。

## 核心问题与原则

成熟公开 BD 多来自 80 级以后，不能证明早期怎样开荒。高上限流派又常有技能、资源、Spirit、
触发或装备成型门槛，因此开荒升华、技能、天赋和资源系统可以与目标完全不同。

基础职业是唯一跨阶段硬锁。完整成长路线拆成三个设计对象：

1. 同基础职业下成型快、前期职责完整的开荒技能包；首个升华前它不是成熟 Family；
2. 由正常 Create 独立生成并接受的目标高上限 Family；
3. 用技能、升华、天赋、Spirit、资源、防御和必需物品门槛连接两者的 TransitionBridge。

不能从目标 PoB 自动删点或降级装备伪造早期阶段，也不能先生成较弱的桥接 BD，再把它当作目标
毕业 BD。目标 anchor 一旦绑定，artifact id、source hash、Family、等级和版本都不可替换。

## Family discovery、目标选择与可恢复 Anchor

`start_build_progression` 创建 schema v3 状态。用户未提供完整且唯一的目标 Family 时先进入
`selection_pending`，返回 `TargetCandidateSelectionPacket` 和一份固定请求 10 个候选的
Family discovery 参数。Agent 用基础职业、当前精确 patch 和天赋树版本调用
`query_research_memory(detail_level="family")`。这里只返回 Family 身份、合格证据量、record kind
覆盖、关键前提、失败条件和 typed receipt，不返回深度正文。

合格 Family 必须由当前精确 patch/tree 下 `creator_visible + train_context + copy-safety passed +
status=valid` 的深度记录支持。旧 patch、stale、`needs_revalidation` 或自由拼装的 Family 不能补
数量。数据库有 5–10 个时全部比较；只有 2–4 个时仍比较全部并标记覆盖有限；少于 2 个时状态
暂停，等待补 Research，不能猜一个目标。数据库超过 10 个时按合格证据量、记录类型覆盖和记录
数排序后返回前 10 个。

用户只指定升华或主技能时，它是 discovery 的硬过滤条件；用户已经给出完整唯一的升华、主技能和
Family identity 时跳过 discovery，直接进入 `anchor_running`，也不允许备用切换。

Agent 提交的 `TargetCandidateSelection` 必须覆盖 discovery receipt 实际返回的全部 2–10 个
Family，不能删改、补造或只挑容易建模的候选。排名是完整排列，第一名为 selected，第二名为
reserve。比较维度固定为：

- 机制闭环；
- Research 支持；
- 目标契合与强度证据；
- 可玩风险；
- modelability。

modelability 不能在前三项均无优势时单独决定第一名。候选只保存设计摘要和安全引用，不跑完整
Judge，不调用全局 optimizer，也不搭完整装备/天赋。选择完成后状态进入 `anchor_running` 并返回
锁定第一名 Family 的 `TargetAnchorCreatePacket`。Agent 启动普通 Phase 5 run 后必须调用
`bind_build_progression_target_run`，再按普通单阶段 `$poe-bd-create` 从空状态生成目标：

在 anchor 绑定前，start/status 不返回 `StarterResearchPacket` 或 stale candidate 正文，只暴露
是否存在缓存的布尔提示；因此目标 Create 不会提前看到开荒路线。

- 使用普通 Create 的渐进 Research recall 和真实 `researchMemoryUse`；
- `globalOptimizerAllowed=false`；只允许 Agent 指定的局部工具与手工/定向天赋，不允许 whole-build
  或全局树重排；
- 使用普通 Create 的最多两次内部修正；共享 `HardLegalityAudit` 会在 Judge 前检查属性、
  装备/宝石等级、武器、Spirit、天赋预算和词缀，确定性错误返回
  `attemptConsumed=false`，不消耗正式 Judge 次数；
- 在保存前按目标等级运行一次活动快照 lifecycle gate；失败或 unknown 时先在普通 Create 的既有
  retry 内修复，不能把资源断裂等真实问题留给 progression；
- 首个通过 Judge 且合法的版本成为受保护 baseline；随后完整执行一次主动质量收尾。新版本更好
  且合法时选择新版本，质量增量回归时可保存旧 passing attempt 的精确快照，不得因最后一次探索
  失败丢掉已验证目标；
- 完成正式 Judge、选择并保存 `FinalBuildArtifact` 和 `review-packet`；
- 保存后再用 `verify_lifecycle_stage(..., artifact_id=...)` 直接验证私有 immutable artifact，
  取得 `verificationRef`；
- 不读取 starter web packet，也不从尚未存在的早期阶段倒推一个低配目标。

若第一名 Family 的机制无法闭环、质量不可接受或证据不足，Agent 先调用
`fail_build_progression_target_anchor`，再基于安全证据显式调用
`reselect_build_progression_target_candidate`，最多切换一次第二名；Judge warning 或分数不能
自动触发切换。工具、审批或控制流程中断只允许同一 Family 使用一次
`retry_build_progression_target_anchor`，不占 Phase 5 内部构筑修正；切到备用 Family 后拥有自己
的一次中断 retry。用户锁定 Family 时禁止切换。

随后调用 `bind_build_progression_target_anchor`。绑定必须同时验证：

- artifact 在当前 progression 启动后产生，职业、等级和六项版本事实一致；
- artifact run 与当前 `bind_build_progression_target_run` 绑定一致；
- `verificationRef` 是该 artifact、目标 lifecycle stage 和原始 source hash 的可信回执，且结果为
  `passed`；失败、unknown、缺失、篡改或属于其他 artifact/stage 的回执一律拒绝；
- artifact 摘要中的升华/主技能名称与已解析 stable key 身份一致；若 Research 与 PoB 使用不同
  显示名，typed receipt 先验证候选 key，再由 artifact 同一 graph snapshot 把 artifact 名称
  唯一解析到该 key，并保存别名解析证据；
- 最终 Agent failure audit 为 `accept`，且不是 `true_build_failure` 或含混的 `mixed`；
- `TargetDesignCoverage` 恰好覆盖技能包、清图、Boss、伤害兑现、升华/天赋、装备协同、
  防御/恢复、资源/Spirit、战斗配置和 modelability 十个维度；
- Judge 默认使用 `strict_mode=false` 的 hard-only 可信附件，不以分数或 warning 自动阻断/选优；
  用户显式要求严格模式时才保留完整 advisory 字段，同一 target/stage run 不能中途切换；
- Agent 显式给出 `accepted` 或 `limited_accepted`；后者的 caveat 必须进入最终路线；
- artifact 使用的每个 Research Family/record/pattern/edge/fragment 都能由 typed query receipt
  追溯。

任一设计维度为 `rejected` 时不能绑定。`unavailable_with_caveat` 可以绑定，但最终路线质量为
`limited`。标记为 `research_adopted` 的维度必须引用实际采用的 Family、record、pattern、edge
或 fragment ID；单独引用查询回执 `dq-*` 只能证明查过，不能证明采用过。
标记为 `independently_verified` 的维度必须引用当前 anchor 的真实 artifact，或该 Phase 5
run/source-hash 证据；任意格式安全的字符串不能冒充验证来源。

PoB import/save 不保证 XML 字节序列稳定。生命周期回执因此同时记录两种 hash：artifact
manifest 中的原始 `sourceHash` 是 immutable 身份；PoB 恢复后的
`restoredEngineSourceHash` 是共享 `build_state_hash` 产生的语义状态投影，只用于证明验证过程中
等级、技能、装备、天赋、配置等计算输入没有变化。它忽略 `PlayerStat`、`FullDPSSkill` 等只读
计算会刷新的派生输出和 XML 展示噪声。系统不会通过重新序列化去伪造原始 hash，也不会因字段
顺序或派生输出刷新把真实同一 artifact 误判成另一个构筑；真实语义变化仍会 fail closed。回执
不保存 XML，并使用内容寻址检测本地篡改。

## Typed Research provenance

`query_research_memory` 在原有 dedupe 表中追加 copy-safe `request_contract` 与
`result_contract`：

- request 保存精确升华、主技能、graph-backed gem/active-skill 等价 key、Family、record kind、
  axes 和查询模式，不保存原始 PoB/来源；
- result 保存返回的 Family identity、record/pattern/edge/fragment ID，以及精确 Family 查询
  当时的 `familyRecordCoverage / familyPremiseCatalog / premiseAuditVersion /
  deepReadRecordIds`；不保存网页、整角色或原始查询文本；
- ref 同时绑定安全 request/result；后续知识库变化形成新 ref，不覆盖旧 provenance；
- 历史无 typed contract 的 dedupe ref 仍可用于旧 Research 去重，但不能授权新 progression。

知识路由按阶段分成两类：

- `starter_common`：首个升华前或仍未形成稳定成熟流派的开荒阶段。使用
  `StarterStageIdentity` 保存主副技能及可选的预期升华，不要求、也不允许伪造成品 Family
  Research receipt；Phase 5 使用 `generationMemoryMode=standard`，主要依赖
  StarterResearchPacket、corpus/graph、mechanics 和 PoB；
- `family_exact`：转型开始后已经确定升华和核心主技能的阶段。必须至少有一个使用该阶段精确
  `ascendancyKey + primarySkillKey` 的 typed receipt，并使用 memory-assisted Create。

普通 target anchor 没有 stage packet，其 `researchMemoryRef` 只需属于候选实际
`researchMemoryUse.dedupeQueryRefs`。目标前阶段必须把 claim 返回的
`StageCreatePacket.versionContext` 原样用于 Phase 5/Judge/artifact；后续渐进查询可以继续进入
`researchMemoryUse`，但不能替换 stage-bound ref。阶段完成时服务会验证所有实际采用的知识 ID
都真实出现在这些 receipt 中，并要求 receipt 在当前 progression 启动后实际查询过，不能只复用
历史 ref。时间门槛在蓝图提交时即检查；恢复运行不需要重建已被安全 receipt 隐去的原始 query
文本。

选中成熟 Family 后，Agent 必须把 `familyPremiseCatalog` 中所有关键失败 premise 写入
`ResearchMemoryUse.premiseDecisions`：

- `resolved` 引用本轮 `detail_level="record"` 回执真正深读的解决记录；
- `caveated` 保存仍未解决的具体风险；
- `not_applicable` 说明为何当前候选不受该前提影响。

Boss、资源、轮转等职责仍有未处理失败条件时，必须利用 `familyRecordIndex` 按 Family、组件、
record kind、record ID 或失败文本继续定向查询；首轮 `limit` 和 create-compact 响应都不能被
当作总上限。替代机制可以通过审计，不为某个特定技能或资源方案写死答案。

对 `family_exact` 阶段，在 claim 前 Agent 必须把准备采用的 `buildFamilyKey` 的 ascendancy、
primary skill 和完整
`secondarySkillKeys` 与 `StageFamilyIdentity` 逐项核对。若核心副技能不同，只能先修订尚未
开始的蓝图；不能完成 artifact 后再换成另一个 Family。阶段完成时服务会再次按 immutable
receipt 检查并失败关闭。

`starter_common` 阶段改用 `StarterStageIdentity`。若尚未升华，其 expected ascendancy 必须为空，
artifact readback 只接受 `None/Unascended`；不能因为成熟数据库没有对应记录就把它视为召回失败。

Family identity 统一使用玩家 `active_skill` 的 `skill:` stable key。`gem:` stable key 可以作为
`query_research_memory` 的查询入口；receipt 会记录由物理图确认的等价 key 集合，使该真实查询
可追溯到对应 active-skill Family。没有图关系的两个 key 不能互相授权。

Family identity 还必须保存 artifact 实际使用的升华/主技能名称。声明已确认核心 secondary key
时，也必须保存一一对应的名称并在同一 artifact 的启用 tested skill groups 中匹配。Research
名称与 PoB readback 名称不同不等于 Family 不同；但只能由 artifact 的同一 graph snapshot
把 artifact 名称唯一解析到 typed receipt 已验证的 Family stable key 后接受。Research Family
标题不要求本身是图别名。artifact 名称缺失、歧义、跨 snapshot 或解析为不同 key 仍拒绝，避免
“查询 A Family、实际做 B 技能”的 provenance 漂移。

## 联网开荒研究

联网由外部 Agent 使用宿主 Web/Browser 完成，仓库不新增自主模型、隐藏 loop 或内部全网爬虫。
一次路线最多采纳六个来源：

开荒安全摘要使用 `StarterResearchPacket`，并按以下来源规则形成：

- 两个独立当前资料收敛，或一个当前精确 patch、明确等级分段的完整攻略，才可标记
  `supported`；
- 聚合帖和评论只能发现来源；旧 patch 只能成为待复核候选；跨赛季禁止采用；
- 组件存在性、机制前提、数值和合法性仍分别由 corpus/graph、mechanic、PoB/Judge 验证；
- 技能包 claim 应结构化记录每个技能的 clear/boss/setup/payoff 等职责，以及它提供、依赖的条件
  和排除场景；不能把“多个技能共同承担职责”的模糊摘要直接固化为单一主技能；
- 断网时允许 `limited_offline_inference`，但必须披露低证据。

URL 在 intake 时立即转换为 `safe_url_ref`。网页正文、完整 URL、PoB code/XML 和整角色镜像不
落盘。安全缓存按基础职业、精确 patch 和天赋树版本保存七天；过期或同赛季 patch 不一致只作为
待复核 candidate。Starter packet cache v2 要求 `skill_package` claim 带结构化技能职责；
旧 v1 包仍可读取，但只能以 `starter_role_schema_revalidation_required` 进入待复核，不能直接
命中新路线。

## Blueprint 与转型

默认四个 artifact：一个已绑定目标 anchor，加三个目标之前的开荒/桥接里程碑；无实质变化时可
合并，最多五个。`ProgressionBlueprint.targetAnchorArtifactId` 必须等于已绑定 anchor，最后一个
`StageBlueprint` 必须使用相同 Family、等级和 `routeRole=target`。

开荒候选优先前期伤害、成型速度、清图/Boss 职责、资源稳定、低装备依赖和操作复杂度。与目标
相似度和洗点量只是次要因素。

每个非首阶段必须提交 TransitionBridge。完成阶段时，`StageCompletionReport.transitionReadiness`
逐项回报相同 requirement；不能改写 kind、blocking 或描述。所有 blocking 机制门槛必须为
`satisfied` 且带安全证据引用。`budget/price` 永远非 blocking。

生命周期标签服从 progression 验证预算：`endgame_budget >= 82`，
`endgame_final >= 92`。这同时保留普通 Create 的既有摘要等级映射：65–81 级为
`maps_entry`，82–91 级为 `endgame_budget`，92 级起为 `endgame_final`。

每个 `StageCreatePacket` 都使用 `loadoutScope=stage_complete_loadout` 和
`qualityGoal=complete_stage_build`。`campaign_early` 与后续阶段一样，目标是在当前等级交付完整、
强力且可玩的阶段 BD：完整技能职责、可用装备、合理天赋、资源与实际操作必须闭环，不能用“只是
过渡”解释空装备槽或未完成设计。这里不增加固定 DPS/EHP、装备槽数量或天赋点数等主观硬门槛；
79 级及以下仍为 `judgeElementalResistancePolicy=diagnostic_only`；80 级及以上改为
`judgeElementalResistancePolicy=endgame_minimums_60_30`，要求火/冰/电各 60%、非 CI 混沌抗
30%，CI 只豁免混沌抗。共享 checkpoint 在正式 Judge 前执行并且失败不消耗 attempt。元素 Max
Hit 与其他确定性合同照常验证。全局被动树和 whole-build optimizer 仍禁止，所有阶段均使用
Agent 决定的局部、目标明确优化。

Lifecycle 另有只用于阶段就绪的元素抗性门槛，并以活动 PoB 的真实等级而非重叠 stage label
计算：45–64 级三抗各 30%，65–79 级各 50%，80–89 级各 60%；45 级以下和 90 级以上不增加
Lifecycle 百分比门槛。Lifecycle 不检查混沌抗，也不得用历史 `resists_capped` 名称把 50%/60%
偷偷提升为 75%。

为了防止完整早期 BD 变成反复推倒重做，policy 同时固定
`mutationStrategy=single_initialization_then_function_scoped_deltas` 与
`designChangePolicy=blueprint_declared_or_versioned_replan_only`：阶段路线必须先在蓝图中确定；claim
后设计冻结；同一阶段只初始化一次，后续按 `mechanism_shell / skill_loadout / passive_delta /
required_gear / ordinary_gear / config` 提交局部事务。后续阶段默认继承上一 artifact。只有技能体系、
升华或资源系统发生蓝图已声明的重大转型时，才允许 `rebuildFromScratch=true`，并必须给出
`rebuildReason`；第一阶段不能声明重建。普通合法性、资源、装备、天赋或辅助问题必须局部修复；
整体方向只能在确定性失败后通过既有的一次版本化 stage replan 改变。

`StageCreatePacket.generationMemoryMode` 是 progression 阶段的唯一事实源，优先于普通 Create
默认值。绑定 stage run 时服务读取 Phase 5 run manifest；实际 `memoryMode` 不一致就返回
expected/actual，不绑定、不推进 revision、不消耗外部 retry，原 claim 仍可绑定一个新建的正确
run。阶段完成时再次执行同一校验，防止已绑定 manifest 被替换。

Agent 已经决定的机械操作使用 `apply_build_mutation_batch` 按
`bootstrap / mechanism_shell / skill_loadout / passive_delta / required_gear / ordinary_gear /
config` 拆成小型职能事务。不得跨需要读回 skill-group fingerprint、装备槽、珠宝孔、武器兼容
或资源状态的边界混批。除以 `new_build` 开始的 bootstrap 外，每批都必须使用上一批
`outputStateHash` 做 CAS；失败只回滚当前批，`recoveryRequired=true` 时暂停恢复。正式 Judge 前
调用 `inspect_generation_checkpoint`，按语义 `build_state_hash` 一次合并 completeness、
preflight、有界 stats 与 defenses；状态变化后才重新计算。正式 Judge 和 artifact-bound
lifecycle 仍独立执行。

效率规则只删除完全重复的工作，不截断知识、候选或质量探索：

- 同一未改变 Family 身份的目标/阶段不设固定摘要、维度查询或 record 深读额度；应查询到阶段
  职责、关键条件、失败场景和验证任务得到足够覆盖。checkpoint 只阻止同一 query/receipt 因
  上下文压缩被原样重放；
- `search_passives/search_mods/search_items` 使用精确 query，默认返回量不是候选上限；必要时扩大
  结果并对选中项读取精确详情；
- 调参期间使用 checkpoint；每个正式 Judge attempt 前最多一次活动
  `verify_lifecycle_stage(detail="compact")`，且只有 state hash 改变后才能再次执行；
- artifact 保存后只执行一次 artifact-bound lifecycle；完整计算照常执行，receipt 继续保存既有
  的安全信任字段，compact 只压缩当前对话响应；
- 机制完整、合法的基础版本形成后，每个阶段候选都必须执行一次符合当前等级的主动质量收尾，
  检查武器、辅助、天赋路径、珠宝、符文/灵魂核心和配置。Judge 报警不是探索前提；只去重同一
  state hash、目标和参数的完全相同重型调用，也不能用终局数值阈值要求低等级阶段。

## 可恢复编排

新状态机为：

```text
selection_pending
  -> anchor_running
       -> anchor_failed
            -> 同 Family 一次外部中断 retry
            -> Agent 显式切换一次 reserve Family
       -> anchor_bound（accepted / limited_accepted）
  -> research_pending / blueprint_pending
  -> stage_pending -> stage_running -> stage_completed
  -> ...目标之前的阶段...
  -> target stage claim（requiresPhase5Run=false）
  -> 重新校验并复用同一个 Target Anchor 的 artifact/lifecycle receipt
  -> finalize_pending -> completed
```

Family discovery 少于两个时进入 `paused`，补充 Research 后显式 resume 回到
`selection_pending`。每个 mutation 使用 `operationId + expectedRevision` 做幂等与 CAS，并支持
pause/resume、target run 绑定、同 Family 一次外部中断 retry、一次 reserve Family 切换，以及
每个目标前阶段的一次显式外部 retry。

新 progression 允许以精确占位值 `graphSnapshotId=unavailable:pending_discovery` 启动。绑定
target anchor 时只能从可信 target artifact 将它解析一次为具体 snapshot，或非 pending 的最终
`unavailable:<reason>`；其余版本字段仍严格一致。全部检查通过后，服务在同一 progression id
中原子更新 canonical version context、selection/anchor packet 并记录
`graphSnapshotResolution`。解析后永久冻结；已有具体 snapshot 不能漂移，也不能为了修复冲突
另开路线或消耗 target external retry。

失败阶段尚未保存 artifact 且不是 target closure 时，这一次外部 retry 可以携带版本化
`revisedStage + revisedBlueprintId + replanSummary`。它允许 Agent 基于新公共证据或新 Family
receipt 改换当前失败技能方向，并追加 old/new identity、失败代码和证据审计；职业、阶段等级、
lifecycle/route role、target anchor 和版本保持不变。已经完成或已消耗 retry 的阶段仍不可改。

正常 Phase 5 顺序固定为“选择 passing attempt → 保存 artifact → validate/review”。最后一次质量
探索不是机械最终结果：若它回归，只要后续发现明确局限于质量增量，旧 baseline 的精确 Judge
快照、共享合法性回执和 state hash 仍可信，就可选择旧 attempt。历史或长上下文任务误先消费
review 时，artifact saver 也必须核对实际选择的 candidate/attempt、精确 Judge snapshot 和语义
state hash；禁止手工删除 review marker、可信 receipt 或运行锁。若质量增量在 Judge 前合法性
预检就被拒绝、没有产生新 attempt，也必须通过活动 state hash 与 passing baseline 的差异以及
`candidate_delta_only` 原因恢复精确旧快照，不能直接保存当前非法活动构筑。

只要 target anchor 已可信绑定且路线尚未完成，`export_build_progression_package(progressionId)`
就可导出明确标记 `routeIncomplete=true` 的恢复包。这同时覆盖
`stage_pending / stage_running / paused / failed / finalize_pending` 和控制/审批层阻断，并兼容
旧状态 `bound` 与当前状态 `anchor_bound`；恢复包不创建 Route v3，不能称为完整成长路线。

长流程额外使用独立的 `ProgressionWorkingCheckpoint`，避免把聊天上下文误当成工作数据库：

- Agent 在选定重要 Research、改变机制结论、进入正式 Judge 前和阶段完成前调用
  `checkpoint_build_progression_context`；
- checkpoint 保存采用/保留/拒绝的 evidence、关键条件、失败条件、验证任务、机制摘要、配置
  假设、未解决项、阶段 knowledge mode、对应的 Family/Starter identity 和下一步；同时保存
  premise ID、`resolved/caveated/not_applicable`、解决记录、Create 应用方式和验证任务，不保存隐藏
  推理、聊天、网页、URL、PoB/XML 或整角色材料；
- checkpoint 使用独立 `contextRevision + operationId` 做 CAS/幂等，不推进 progression
  `revision`，也不进入 Research/Memory/Git；
- `get_build_progression_status` 默认返回 compact 控制摘要；`detail=resume` 一次返回有界恢复包，
  `detail=full` 只保留为明确需要完整安全状态时的兼容入口；
- 上下文压缩或任务恢复后，Agent 必须先读取 resume packet，再进行新的 PoB mutation。完整
  Research 优先按 checkpoint 中的 evidence ref 定向读取，避免原样重放整个 Family；现有引用
  无法回答新缺口或歧义时仍可继续定向查询。

`query_research_memory(response_profile="create_compact")` 不改变 durable typed receipt，只从当前
对话响应中删除每项的重复 retrieval policy、component mention 等字段，不截断命中结果，并增加
`criticalPremiseDigest`，把条件、失败场景和验证任务提升为 Create 的高显著性输入。具体歧义
依赖省略字段时可显式读取 full 响应。

目标绑定时，未解决 premise 不自动等于构筑失败，但不能从报告中消失。存在 `caveated` decision
时只允许 `limited_accepted`；对应 premise ID 必须进入 `TargetDesignCoverage`，具体风险必须进入
路线说明。`accepted` 只能用于所有关键 premise 都已 resolved 或 not_applicable 的候选。

MCP server instructions 使用短 bootstrap，而不是在每次延迟工具发现时重复注入完整
`ASSISTANT_GUIDE.md`。运行时还只记录工具名、耗时、响应字节数和安全 run/progression/stage
关联，用于定位上下文放大；不记录参数正文或响应内容。

目标之前的阶段仍各自执行独立 Phase 5 run、Judge、artifact、review、artifact-bound lifecycle
回执和成本画像。每个阶段先在保存前修复活动快照 gate，保存后再以 artifact id 生成可信
`verificationRef`；`complete_build_progression_stage` 不信任调用者复制的 lifecycle 字段。
领取最后 target stage 时，`StageCreatePacket.requiresPhase5Run=false` 且
`targetAnchorArtifactId` 指向最初 anchor；此时重新校验绑定时的 artifact/receipt、验证转型门槛
并完成阶段。不要因 PoB reserialize 可能改变字节顺序而生成另一份 target 身份，绝不再运行第五次
Create。

schema v1 的旧 progression 状态按旧语义恢复，不自动迁移；已保存 Route v1/v2 继续可读。

## Route v3、质量与成本

新锚点路线写 Route v3：

- `targetArtifactId == targetAnchorArtifactId`；
- 最后阶段的 artifact/source hash 与最初 anchor 完全相同；
- 保存 `TargetDesignCoverage`、稳定 `stageId`、阶段证据、resolved transition bridge 和成本画像；
- 默认 hard-only 只保留 Judge 硬门槛与确定性诊断；显式 strict 才保留完整诊断，但两种模式都不
  自动决定 v3 quality；
- v3 quality 由 Starter/Research evidence、成本 evidence、目标设计 coverage 和 target role 决定。

非锚点兼容入口仍可写 Route v2；Route v1/v2 不重写。兼容入口
`save_build_progression_route` 不能直接提交 anchor 字段；Route v3 只能由通过 CAS 状态机全部
验证的 `finalize_build_progression` 写入，不能绕过 target anchor、Research provenance、阶段
hash 和 transition readiness 合同。

价格只作风险说明。暗金按 Divine 等价分为
`cheap <= 0.1D`、`moderate <= 0.5D`、`expensive <= 2D`、`chase > 2D`、`unknown`；黄装只按
craft effort 分类。不得计算虚假整套总价，也不得按价格自动触发转型。

## 公开工具

- `start_build_progression`
- `submit_build_progression_target_selection`
- `bind_build_progression_target_anchor`
- `intake_starter_research_packet`
- `submit_build_progression_blueprint`
- `revise_future_build_progression_stages`
- `claim_build_progression_stage`
- `bind_build_progression_stage_run`
- `complete_build_progression_stage`
- `fail_build_progression_stage`
- `retry_build_progression_stage`
- `pause_build_progression`
- `resume_build_progression`
- `checkpoint_build_progression_context`
- `get_build_progression_status`
- `classify_build_progression_costs`
- `finalize_build_progression`
- `export_build_progression_package`

兼容保留 `save/list/load_build_progression_*`。所有工具只接收和返回安全控制状态。

## 导出

完整成长包包含路线说明、每阶段 PoB XML、每阶段 import-code 文件，以及仅目标 anchor 的官方
单阶段 `.build`。MCP 只返回完整 inventory、路径或 errorCode，不回显内容。

若路线在目标前阶段失败，但 immutable target anchor 已经绑定，
`export_build_progression_package(progression_id)` 返回明确的恢复包：状态固定为 `partial`、
`routeIncomplete=true`，包含已完成阶段、目标 anchor 的 XML/import-code、目标单阶段 `.build`
以及恢复说明、当前活动/失败阶段和 failure code。`fail_build_progression_stage` 响应会返回
`recoveryExportAvailable` 与明确下一动作；即使失败登记或审批本身无法完成，Agent 也必须直接用
已知 progression id 调用恢复导出。它不能生成 Route v3，也不能被描述成完整成长路线。

## 验收

- 普通 80 级 Create 与 Phase 8 前基线等价，Research recall、技能包、升华点和 Judge 流程无回归；
- progression 首先创建目标 anchor，之后只有目标前阶段运行新的 Create；
- anchor 绑定前必须通过目标等级对应的 artifact-bound lifecycle gate；资源断裂等真实构筑失败
  不能靠 caller boolean、药剂名称或放宽门槛变成通过；
- target closure 复用相同 artifact id/source hash 和可信 lifecycle receipt，机制门槛不满足时
  失败关闭；
- PoB XML 恢复后字节序变化不会破坏 artifact 身份；回执篡改、跨 artifact/stage 复用会失败关闭；
- Agent 认定存在真实 build failure 的候选不能成为 anchor；
- `family_exact` 阶段的 Family/采用知识都有 typed receipt；`starter_common` 阶段不强求成熟
  Family 命中，但必须有 typed 开荒技能身份、StarterEvidenceUse 和公共知识引用；
- 未升华早期 artifact 可合法使用 `None/Unascended`，不得为了查询成品 Family 提前分配升华；
- 未保存 artifact 的失败阶段可在唯一外部 retry 中审计式换方向，不能借此修改阶段等级或 target；
- 失败路线仍可导出明确标记不完整的目标恢复包，不能让可信 target 因早期失败而零交付；
- 开荒与目标技能/升华可以完全不同，基础职业不同则拒绝；
- URL/网页/整角色原料不进入状态、route、Research 或 Memory；
- 模拟清空聊天后，只靠 `detail=resume` 能恢复关键 Research 条件、失败场景、当前 stage 和下一步；
- compact status 与 Create Research 响应显著小于 full 兼容响应，MCP 遥测不保存请求或结果正文；
- price 不阻断或触发转型；
- Route v1/v2 继续可读，新锚点路线为 v3；
- focused、quick、noncompute、独立 CR、真实四阶段任务和 full 全部通过。
