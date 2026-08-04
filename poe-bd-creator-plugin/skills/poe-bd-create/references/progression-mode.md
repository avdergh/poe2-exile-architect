# Progression 模式：目标锚点优先的完整成长 BD

只在 `/poe-bd-create` 的阻塞式入口确认中，用户选择“需要完整开荒过程”后使用。模糊的
“附带开荒策略”不能被静默解释成文字建议或完整 progression；必须先确认。仓库状态服务不创建任务、不
联网、不调用模型；宿主 Agent 在当前可见任务内严格串行完成。

## 不可破坏的边界

- 普通单阶段 Create 是已经完成的能力。progression 的 `82/92` 验证门槛不能改变普通 Create 的
  等级映射、Research recall、技能组、升华、优化、Judge、保存或导出逻辑。
- 目标 BD 必须先按普通单阶段 Create 从空状态生成并保存为 immutable anchor。不能先做低等级
  构筑再倒推目标，也不能用较弱 bridge artifact 替换目标。
- 基础职业是唯一跨阶段硬锁。开荒可使用完全不同的升华、技能、天赋、装备、防御和资源系统。
- 价格只说明风险，不能触发转型。TransitionBridge 的 blocking gate 必须是机制 readiness。
- 网页只提供候选；组件、机制、数值/合法性分别由 graph/corpus、mechanic、PoB/Judge 验证。

## 上下文预算与恢复

progression 的聊天记录不是事实数据库。MCP 只把控制状态和安全 artifact 持久化时，自动上下文
压缩会丢失早先 Research 的条件和失败场景。因此每条路线还要维护独立的临时语义工作集：

- Create 查询 Research 时统一传 `response_profile="create_compact"`，优先读取
  `criticalPremiseDigest`；
- 目标或阶段完成重要召回取舍后，调用 `checkpoint_build_progression_context`，保存
  `recalledEvidence` 的 `adopted/caveated/rejected`、关键条件、失败条件、验证任务及证据引用；
- 同时保存每个 premise ID 的 `resolved/caveated/not_applicable`、解决记录、Create 应用方式、
  caveat 和验证任务，保证压缩后不会只恢复“查过某条记录”而丢掉如何处理；
- 同一 checkpoint 还保存机制摘要、配置假设、未解决项和下一步，但禁止保存隐藏思维链、聊天
  记录、网页/URL、PoB code/XML 或整角色材料；
- 当前阶段同时保存 `knowledgeMode`，并只保存与之匹配的 `familyIdentity` 或
  `starterIdentity`，避免恢复后把开荒技能包重新解释成成品 Family；
- 工作集使用独立 `contextRevision`，不会消耗或改写 progression 的 CAS `revision`；
- 正常检查状态使用 `get_build_progression_status(detail="compact")`；
- 自动压缩、重启、长时间中断或不确定先前结论时，在任何 PoB mutation 前调用一次
  `get_build_progression_status(detail="resume")`。恢复包一次性给出当前请求、anchor 摘要、活动
  stage packet、完成阶段引用和 `workingCheckpoint`；
- `detail="full"` 只用于确实需要完整安全状态的局部步骤，不能每轮轮询。

恢复包只保留工作结论；完整 Research 仍由 evidence ref 定向读取。不要把整个 Family 的全部记录
重新注入，以免恢复动作本身再次耗尽上下文。

同一未改变身份的目标或 `family_exact` 阶段不设固定 Family 摘要、维度查询或 record 深读额度。
继续定向查询，直到阶段职责、关键条件、失败场景和验证任务得到足够覆盖。checkpoint 已保存的
同一 query/receipt 在压缩恢复后不原样重放，但新缺口、歧义和候选取舍仍可继续查询。
组件/天赋/词缀搜索使用精确 query，默认返回量不是候选上限；需要时扩大结果，再对选中项使用
精确详情工具。`create_compact` 只省略重复字段，不截断命中结果。

精确 Family 响应中的 `familyRecordCoverage` 表示合格记录总量与类型覆盖，
`familyRecordIndex` 列出本轮未展开记录，`familyPremiseCatalog` 给出稳定 premise ID。为 Boss、
资源、轮转等职责建立处理表，并写入 `ResearchMemoryUse.premiseDecisions`；每个关键失败 premise
必须是：

- `resolved`：引用本轮 `detail_level="record"` 真正深读的解决记录；
- `caveated`：记录仍未解决的风险；
- `not_applicable`：说明为何当前候选不受影响。

只在摘要中看到 ID 不能算采用。可按 Family、组件 key、record kind、record ID 或失败文本继续
定向查询，允许采用替代机制，不把某个技能或资源方案写死。

## 1. Research Family discovery、排序与 Target Anchor

1. 调用 `get_freshness_report`，形成完整 `VersionContext`。
2. 调用 `start_build_progression(operation_id, base_class, target_level, goal,
   version_context, class_key?, target_family_constraint?)`，保存 `progressionId` 和 `revision`。
   用户没有提供完整唯一 `lockedIdentity + buildFamilyKey` 时，新状态为 `selection_pending`，
   返回 `TargetCandidateSelectionPacket` 和 `targetFamilyDiscoveryRequest`；锁定 Family 时直接
   进入 `anchor_running` 且禁止备用切换。
3. 按返回参数调用
   `query_research_memory(query="", detail_level="family", class_key=..., game_patch=...,
   passive_tree_version=..., ascendancy_key?, primary_skill_key?, build_family_keys?)`。一次请求 10
   个；不足 10 个返回当前全部合格 Family。只有精确 patch/tree、`creator_visible`、
   `train_context`、copy-safety passed、`status=valid` 的深度记录有资格。不能用旧 patch、
   stale、`needs_revalidation` 或自由拼装 Family 补数。少于 2 个时提交 receipt 让状态暂停并
   报告 Research 缺口；补 Research 后 resume 并重新 query。
4. 对 receipt 实际返回的全部 2–10 个 Family 做轻量比较，不能手工删掉不喜欢的候选。每项保存
   真实 `buildFamilyKey`、同一 `familyDiscoveryRef`、精确升华/主技能/核心副技能身份、机制摘要、
   预期优势、风险和安全 evidence refs。比较恰好五维：
   `mechanism_closure`、`research_support`、`goal_fit_and_power_evidence`、
   `playability_risk`、`modelability`。排名是完整排列，第一名 selected、第二名 reserve；
   modelability 不能在前三项均无优势时单独决定第一名。此处不搭完整装备/天赋，不跑正式
   Judge，不调用 `optimize_build` 或全局树优化。
5. 调用 `submit_build_progression_target_selection`。服务端用 typed receipt 验证候选数量、全量
   覆盖和 Family identity，并返回锁定第一名的 `TargetAnchorCreatePacket`。用户只指定升华或
   技能时，它是 discovery 硬过滤条件；不能借候选步骤改写用户约束。
6. 启动普通单阶段 Phase 5 run，并立即调用 `bind_build_progression_target_run`。再按普通 Create
   工作流生成所选目标：
   - `scripts/create_build.py start-run --memory-mode memory_assisted`；
   - `new_build` 后从空状态搭建，不读取 starter packet/cache；
   - 解析目标 ascendancy 与玩家 `active_skill` 的 `skill:` stable key；`gem:` key 只作查询别名；
   - 正常渐进查询 Research，调用时传 `response_profile="create_compact"`，记录真实
     `researchMemoryUse`；
   - 选定目标机制包后立即写第一次 context checkpoint，尤其保存
     `criticalPremiseDigest` 中的条件、失败场景和验证任务；
   - 完整搭建后调用 `inspect_generation_checkpoint(strict_mode=<本次反馈模式>)`；只有 `hardLegalityReady` 和 `mechanismReady` 同时为真才
     进入 Judge。属性、装备/宝石等级、武器、Spirit、天赋预算、词缀等确定性错误返回
     `attemptConsumed=false`，修正后仍保留三次正式 Judge；
   - 运行 Judge，并在活动快照上运行目标等级对应的
     `verify_lifecycle_stage(..., detail="compact", strict_mode=<本次反馈模式>)`；它只在每个正式 Judge attempt 前最多调用
     一次，调参过程使用 state-hash checkpoint。真实 sustain/机制失败必须在最多两次既有内部
     修正中解决；只有修正后 state hash 改变，下一 attempt 才重新运行 gate；
   - 首个合法 Judge 通过版本成为受保护 baseline；然后完整做一次武器、辅助、天赋、珠宝、
     符文/灵魂核心和配置的主动质量收尾。新版本更好且合法则选择新 attempt；质量增量回归时，
     即使新状态在 preflight 就被拦截且没有新增 Judge receipt，也可恢复 passing baseline，但
     必须仍有精确快照与同 state-hash 合法性回执，并声明后续发现只影响 candidate delta；
   - Agent 选择实际 passing attempt 后保存 `FinalBuildArtifact`；
   - 立即且只调用一次
     `verify_lifecycle_stage(stage, state, artifact_id=..., detail="compact", strict_mode=<本次反馈模式>)`，由工具恢复
     immutable artifact 并生成 `verificationRef`；完成 validate/review；
   - progression anchor 暂不单独调用单阶段 export。
   - 如果 progression 以 `graphSnapshotId=unavailable:pending_discovery` 启动，anchor 绑定会从
     可信 target artifact 在同一 progression 中解析并冻结最终 snapshot；不要新开路线或消耗
     target retry。已经具体化的 graph snapshot 绝不允许改变。
7. 若第一名 Family 最终为 `mechanism_unclosed / quality_unacceptable / evidence_insufficient`，
   先调用 `fail_build_progression_target_anchor`。只有 Agent 能带 decision summary 和 evidence
   refs 显式调用 `reselect_build_progression_target_candidate`，最多切到第二名一次；Judge
   分数/warning 不能自动触发。`tool_interruption / approval_interruption /
   control_interruption` 只调用同一 Family 的一次 `retry_build_progression_target_anchor`。
8. 构造 `TargetAnchorIdentity`：稳定 ascendancy/primary/secondary key，加与 artifact safe summary
   完全一致的升华与主技能实际名称。Research 与 PoB 名称不同不代表 Family 不同；绑定工具只在
   typed discovery receipt 已验证候选 stable key，且 artifact 的同一 graph snapshot 能把
   artifact 实际名称唯一解析到该 key 时接受，并返回 `identityAliasResolution`。Research Family
   标题不必本身是图别名；不要自行把近似名称当作 artifact 别名。已确认核心 secondary key 必须
   逐一带 artifact 名称，并真实出现在 artifact 的启用 tested skill group 中。
9. 构造 `TargetDesignCoverage`，十个维度各一次：
   `skill_package`、`clear_duty`、`boss_duty`、`damage_delivery`、
   `ascendancy_and_passives`、`gear_synergy`、`defense_and_recovery`、
   `resource_and_spirit`、`combat_configuration`、`modelability`。
   状态可为 `research_adopted`、`independently_verified`、
   `unavailable_with_caveat`；不要提交 `rejected`。`research_adopted` 的 evidence ref 至少有一个
   必须是最终候选从 typed Research 结果中实际采用的 Family、deep record、pattern、semantic
   edge 或 fragment ID；`dq-*` 查询回执本身只能证明查询过，不能证明采用过知识。
   `independently_verified` 至少引用当前 anchor artifact，或该 Phase 5 run/source-hash 证据；
   不要使用自造引用。
10. 调用 `bind_build_progression_target_anchor`，传入上一步的 `verificationRef` 和
    `acceptance_decision=accepted|limited_accepted`。工具会验证
    artifact 时间、职业、等级、版本、Family stable key 与经图证明的显示名、目标 lifecycle 已
    通过、最终 failure audit、
   十维 coverage 和 typed Research provenance。Judge 仅为 `advisoryOnly`；但 lifecycle
   failed/unknown，或 Agent 自己判定为 `true_build_failure` / `mixed` 的候选都不能绑定。
   `ResearchMemoryUse` 有任何 `caveated` premise 时必须选择 `limited_accepted`，把 premise ID
   写入 TargetDesignCoverage，把具体风险写进路线；不能用 `accepted` 隐去风险。

PoB import/save 后 XML 字段顺序可能变化，所以不要自己重新导出再比较原始字符串。可信回执把
immutable artifact 的原始 source hash 与恢复后的 engine hash 分开记录；后者只证明验证过程中
未发生突变。回执是内容寻址的，不含 XML，手工改写结论后不能再被状态服务信任。

anchor 只有在 artifact、artifact-bound lifecycle 和 acceptance decision 全部可信后才绑定；
绑定后不可更换 artifact id、source hash、Family 或目标等级。

## 2. 有界联网开荒研究

`selection_pending / anchor_running / anchor_failed` 期间，start/status 会隐藏 starter packet
和 stale candidate，只返回是否存在缓存的提示，避免目标 Create 被开荒证据影响。anchor 绑定后，
如果已有 fresh exact-patch
`StarterResearchPacket`，从 `get_build_progression_status(detail="resume")` 读取安全 packet。
否则使用
Web/Browser 做最多六来源的有界研究：

- 优先当前精确 patch、明确等级分段的结构化/官方论坛/可信作者攻略；
- 两个独立来源收敛，或一个当前精确 patch 且明确分级的完整来源，才能 `supported`；
- 聚合帖/评论只发现来源；旧 patch 只作待复核，跨赛季禁用；
- 断网时提交 `limited_offline_inference` 并披露低证据。

调用 `intake_starter_research_packet` 前读取工具的嵌套 input schema。完整 URL 只能临时放在 intake
输入，入口立即哈希；不得把网页正文、长篇复制、整套装备/天赋/技能镜像、PoB 或账号角色信息放入
状态或聊天。

`skill_package` claim 必须提交结构化 `skillRoles` 及其 provides/requires；旧 cache v1 会以
`starter_role_schema_revalidation_required` 返回，只能重新检索/复核后提交 v2，不能直接采用。

## 3. 分阶段知识路由与 Blueprint

不要把成熟 BD 数据库强套到首个升华前的开荒阶段。按实际成型状态选择：

- `starter_common`：首个升华前，或仍然只是通用开荒技能包。解析主副 `skill:` stable key，
  使用 `StarterStageIdentity`，`familyIdentity=null`、`researchQueryRefs=[]`，并记录非空
  `commonKnowledgeRefs`。知识来自 StarterResearchPacket、corpus/graph、mechanics 和 PoB；
  `StageCreatePacket` 会要求 `generationMemoryMode=standard`。18级等正常未升华快照不能为了
  查询成品 Family 提前分配升华。
- `family_exact`：转型开始、升华与核心主技能稳定后，才调用
  `query_research_memory(ascendancy_key=..., primary_skill_key=...,
  response_profile="create_compact")`。每个此类阶段至少有一个精确 Family typed receipt，并用
  `StageFamilyIdentity`。

`StageCreatePacket.generationMemoryMode` 是该阶段唯一事实源，优先于普通 Create 默认值。创建
Phase 5 run 时必须显式使用它。若绑定返回 expected/actual 不一致，保留原 claim，创建一个模式
正确的新 run 再绑定；不要 fail/retry stage，因为这种拒绝不推进 revision、也不消耗外部 retry。

`query_research_memory` 可以接收物理图已关联的 `gem:` key，并在 typed receipt 中保存对应
gem/active-skill 等价 key 集合；因此真实 gem 查询可以授权对应 active-skill Family。但
`TargetAnchorIdentity`、`StageFamilyIdentity`、`StarterStageIdentity` 和蓝图始终使用
`skill:` key，不能把任意 gem/key 重命名为身份。

允许在 Phase 5 中继续渐进查询：

- `researchMemoryUse.dedupeQueryRefs` 记录全部实际查询；
- 普通 target anchor 没有 stage packet，artifact `versionContext.researchMemoryRef` 可以使用其中
  任意一个真实 ref；
- 目标前阶段必须把 claim 返回的 `StageCreatePacket.versionContext` 原样交给 Phase 5/Judge/
  artifact；后续查询仍记录，但不能替换 stage-bound ref；
- 每个采用的 Family、deep record、pattern、semantic edge、fragment ID 必须出现在这些 receipt
  的 result contract 中；
- 全部引用查询都必须在 progression 启动后实际运行，蓝图提交时即检查时间；历史 ref 不能冒充
  本轮召回，恢复阶段也不需要重建 receipt 已刻意隐藏的原始自然语言 query。
- 对 `family_exact` 阶段，在 claim 前把准备采用的 `buildFamilyKey` 的 ascendancy、primary
  skill 和完整
  `secondarySkillKeys` 与 `StageFamilyIdentity` 逐项核对。若核心副技能不同，必须先修订尚未
  开始的蓝图；不能完成 artifact 后再换成另一个 Family。
- 对 `starter_common` 阶段，检查 StarterClaim 的结构化 `skillRoles`、`provides/requires`、
  applicability 和 exclusions；模糊的“多个技能共同承担职责”摘要不能直接固化为唯一主技能。
- 蓝图提交前写 context checkpoint，把每个阶段的知识模式、实际技能/Family、关键 premise、
  未解决项和下一步保存下来。查询 receipt 只证明查过，checkpoint 才承担压缩后的工作恢复。

提交 `ProgressionBlueprint`：

- 默认四个 artifact：已绑定 target anchor + 三个目标前阶段；无变化可合并，最多五个；
- 每个阶段使用稳定 `stageId`；
- `targetAnchorArtifactId` 必须等于已绑定 anchor；
- 最后 stage 必须 `routeRole=target`、目标等级与 anchor 相同，Family stable keys 和规范名称也相同；
- starter stages 的 evidence status 与 starter packet 一致；
- 第一阶段没有 entry bridge；其余每阶段有 `TransitionBridge`；
- `budget/price` gate 必须 `blocking=false`；
- 每阶段覆盖 clear、boss、defense、resource 职责；
- `family_exact` 的 Family 改变时使用新的精确 query receipt。

蓝图锁定前再做一次便宜的开荒候选选择。这与目标 Family discovery 不同，也不是额外 Judge gate：对至少两个合理技能包核对职责、
setup/payoff 前提、技能可用等级、武器兼容、资源方式和明确 exclusion，记录选择与拒绝理由。
候选阶段不要调用面向终局的 `optimize_build` 或提前制作整套装备；先用 corpus/mechanics 与
必要的技能、武器兼容证据排除方向错误，选中后再完整构筑该阶段。

每个 `StageCreatePacket` 都带服务端生成的 `optimizationPolicy`：

- 所有阶段（包括 `campaign_early`）都使用 `loadoutScope=stage_complete_loadout` 与
  `qualityGoal=complete_stage_build`；必须交付该等级下完整、强力且可玩的技能、装备、天赋、资源和
  操作方案，不能以“只是过渡”为理由留下未完成构筑；
- 不为低等级阶段增加固定 DPS/EHP、装备槽数量或天赋点数等主观硬门槛；阶段强度由路线职责、
  当前等级可获得条件、Research/开荒证据和 Agent 的主动质量收尾共同保证；
- 所有阶段仍禁止 `optimize_build` 与全局树重排，只能做 Agent 指定的局部优化；
- policy 固定 `mutationStrategy=single_initialization_then_function_scoped_deltas`：阶段只初始化一次，
  后续按职能提交局部变化；
- policy 固定 `designChangePolicy=blueprint_declared_or_versioned_replan_only`：claim 后设计冻结，普通
  合法性、资源、装备、天赋或辅助问题只能局部修复；整体方向只能在确定性失败后走现有的一次
  版本化 stage replan；
- 79 级及以下使用 `judgeElementalResistancePolicy=diagnostic_only`；80 级及以上使用
  `judgeElementalResistancePolicy=endgame_minimums_60_30`，要求火/冰/电分别至少 60%，非 CI
  混沌抗至少 30%。共享 checkpoint 在正式 Judge 前拦截且不消耗 attempt；CI 只豁免混沌抗。
- Lifecycle 阶段就绪检查按活动 PoB 实际等级使用独立的元素抗性门槛：45–64 级三抗各 30%，
  65–79 级各 50%，80–89 级各 60%；45 级以下和 90 级以上不增加 Lifecycle 抗性百分比门槛。
  stage label 和 caller state 不能覆盖实际等级，`resists_capped` 只是兼容 check ID，不代表 75%。

蓝图启动后，只能用 `revise_future_build_progression_stages` 修改尚未开始的未来阶段；anchor、
已开始/重试/完成阶段、base class、target level 和版本事实不可变。

## 4. 创建 Target 之前的阶段

对每个 `requiresPhase5Run=true` 的 stage：

1. `claim_build_progression_stage`；
2. `create_build.py start-run`，再 `bind_build_progression_stage_run`；
3. 第一阶段用 `apply_build_mutation_batch(batch_kind="bootstrap", ...)` 从 `new_build`、职业和
   等级开始；后续按 `mechanism_shell / skill_loadout / passive_delta / required_gear /
   ordinary_gear / config` 拆成职能小事务。后续阶段优先加载上一 artifact 后正向修改，大
   转型只有在蓝图设置 `rebuildFromScratch=true` 并提供 `rebuildReason` 时才可从空重建；第一阶段
   不能声明重建。只有以 `new_build` 开始的 bootstrap 可省略输入 hash，其余批次都用
   上一批 `outputStateHash` 做 CAS。不得混合职能，不得使用隐式装备槽/珠宝孔，也不能放搜索或
   optimizer；失败只回滚当前批，`recoveryRequired=true` 时暂停恢复；
4. 按 `StageCreatePacket` 的知识模式工作：`starter_common` 不进行成品 Family 召回；
   `family_exact` 按当前实际 Family 渐进查询 Research。所有阶段随后完整搭建技能组、装备、天赋、
   升华、配置、属性、Spirit、药剂/护符和资源，并执行符合当前等级的主动质量收尾；
   查询取舍完成后更新 context checkpoint，再开始大量 PoB mutation；
5. 先调用 `inspect_generation_checkpoint(strict_mode=<本次反馈模式>)`，按同一 build-state hash 一次取得 completeness、
   preflight、stats 和 defenses；修复后状态 hash 改变则重新检查。随后每个正式 attempt 最多
   运行一次活动快照 `verify_lifecycle_stage(..., detail="compact", strict_mode=<本次反馈模式>)` 和正式 Judge；同一 hash
   不得重复调用 lifecycle，artifact-bound lifecycle 仍在保存后独立且只执行一次；
6. 在既有 Phase 5 retry 内修正 lifecycle/Judge 的真实问题；
7. 保存 artifact，再调用
   `verify_lifecycle_stage(..., artifact_id=..., detail="compact", strict_mode=<本次反馈模式>)` 生成可信
   `verificationRef`，完成 validate/review；不要逐阶段 export；
8. 确认回执的 `evaluatedSourceHash` 与最终 Judge/artifact hash 一致；
9. `classify_build_progression_costs`；
10. 在 `StageCompletionReport.transitionReadiness` 中逐项提交 entry bridge requirement。id、kind、
   blocking、description 不能改写；所有 blocking gate 必须 `satisfied` 且有安全 evidence ref；
11. `complete_build_progression_stage` 只提交 `verificationRef` 作为 lifecycle 授权；其他复制字段
    不会覆盖可信回执。
12. 完成阶段前最后更新 checkpoint：记录本阶段 artifact、已解决/未解决条件和下一阶段动作；随后
    下一阶段只需 compact status 或 resume packet，不回放本阶段全部工具结果。

`endgame_budget` progression stage 最低 82，`endgame_final` 最低 92；这是 progression lifecycle
验证预算，不是普通 Create 的等级映射。

阶段失败调用 `fail_build_progression_stage`。检查状态后最多一次
`retry_build_progression_stage`。若失败阶段尚无 artifact 且不是 target closure，可以在这次
retry 中提交版本化 `revisedStage/revisedBlueprintId/replanSummary` 换技能方向；必须加入新公共
证据 ref（starter_common）或新 Research ref（family_exact），且不能改 stage id、等级、
lifecycle/route role、基础职业、目标或版本。暂停/恢复始终使用最新 revision。

## 5. 闭合 Target

前三个目标前阶段完成后领取最后 stage：

1. 确认 `StageCreatePacket.requiresPhase5Run=false` 且
   `targetAnchorArtifactId` 与最初 anchor 相同；
2. 不调用 `start-run`，不调用 `bind_build_progression_stage_run`；
3. 从 progression 状态读取绑定时已经通过的 target `verificationRef`；完成阶段会重新校验它所
   指向的 immutable artifact 和 source hash，不重新序列化 XML，也不生成另一份身份；
4. 如需检查构筑或成本，可以只读加载 `targetAnchorArtifactId`，不得修改后冒充同一 anchor；
5. 分类 anchor 成本，提交从最后 bridge 到 target 的全部 readiness；
6. 用同一个 artifact id 和原始 `verificationRef` 调用
   `complete_build_progression_stage`。

如果 blocking 机制门槛尚未满足，保持上一个 bridge artifact 可用并暂停路线。不能把 bridge
伪装成目标，也不能重新 Create 一个更弱目标来绕过 gate。

## 6. 完成与导出

全部阶段完成后：

1. `finalize_build_progression` 写 anchored Route v3；
2. 确认 `targetArtifactId == targetAnchorArtifactId`，最终 stage source hash 与 anchor 相同；
3. `export_build_progression_package` 一次导出；
4. 向用户逐项报告 inventory：每阶段 XML、每阶段 import-code、路线说明，以及只属于 target
   anchor 的官方 `.build`；失败项报告 errorCode，不展示内容。

若目标前阶段最终失败，或失败登记/暂停/本地审批超时使状态仍停在 `stage_running`，但 target
anchor 已经可信绑定，仍立即调用
`export_build_progression_package(progression_id)`。它会返回
`status=partial`、`routeIncomplete=true` 的恢复包，至少交付目标 XML/import-code/`.build` 和
失败阶段说明。该入口覆盖 `stage_pending / stage_running / paused / failed /
finalize_pending`，并兼容旧 `bound` 与当前 `anchor_bound`。逐项返回已完成阶段 XML/导入码、
target XML/导入码/`.build`、恢复说明、活动/失败阶段和 failure code。必须明确这不是完整成长
路线，不能因为失败而只给文字、隐藏 artifact id 或让用户零文件离开。

正常顺序必须是“保存 artifact → validate/review”。如果旧任务已经误先消费 review，调用
`save_final_build_artifact` 的受检顺序恢复；它仍会重新核对 candidate、attempt、精确 Judge
snapshot 和语义 state hash。不得删除/改名 review marker、可信 receipt 或运行锁。

Route v1/v2 继续可读；新 anchor-first route 写 v3。Judge findings 必须披露，但 v3 quality 不按
Judge aggregate 自动决定，而由 Starter/Research/cost evidence、TargetDesignCoverage 和 target
role 决定。

`save_build_progression_route` 只保留 Route v2 兼容写入，不能提交 anchor 字段。Route v3 必须
由完成全部状态机验证后的 `finalize_build_progression` 产生。
