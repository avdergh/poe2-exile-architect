# Progression 模式：目标锚点优先的完整成长 BD

只在用户明确要求“从开荒到目标等级的完整成长流程”时使用。仓库状态服务不创建任务、不联网、
不调用模型；宿主 Agent 在当前可见任务内严格串行完成。

## 不可破坏的边界

- 普通单阶段 Create 是已经完成的能力。progression 的 `82/92` 验证门槛不能改变普通 Create 的
  等级映射、Research recall、技能组、升华、优化、Judge、保存或导出逻辑。
- 目标 BD 必须先按普通单阶段 Create 从空状态生成并保存为 immutable anchor。不能先做低等级
  构筑再倒推目标，也不能用较弱 bridge artifact 替换目标。
- 基础职业是唯一跨阶段硬锁。开荒可使用完全不同的升华、技能、天赋、装备、防御和资源系统。
- 价格只说明风险，不能触发转型。TransitionBridge 的 blocking gate 必须是机制 readiness。
- 网页只提供候选；组件、机制、数值/合法性分别由 graph/corpus、mechanic、PoB/Judge 验证。

## 1. 启动并生成 Target Anchor

1. 调用 `get_freshness_report`，形成完整 `VersionContext`。
2. 调用 `start_build_progression(operation_id, base_class, target_level, goal,
   version_context)`，保存 `progressionId` 和 `revision`。新状态为 `target_anchor_pending`，
   返回 `TargetAnchorCreatePacket`。
3. 按普通单阶段 Create 工作流生成目标：
   - `scripts/create_build.py start-run --memory-mode memory_assisted`；
   - `new_build` 后从空状态搭建，不读取 starter packet/cache；
   - 解析目标 ascendancy 与玩家 `active_skill` 的 `skill:` stable key；`gem:` key 只作查询别名；
   - 正常渐进查询 Research、记录真实 `researchMemoryUse`；
   - 完整搭建、preflight、Judge，并在活动快照上运行目标等级对应的
     `verify_lifecycle_stage`；真实 sustain/机制失败必须在最多两次既有内部修正中解决；
   - Agent 接受后保存 `FinalBuildArtifact`；
   - 立即调用 `verify_lifecycle_stage(stage, state, artifact_id=...)`，由工具恢复 immutable
     artifact 并生成 `verificationRef`；完成 validate/review；
   - progression anchor 暂不单独调用单阶段 export。
4. 构造 `TargetAnchorIdentity`：稳定 ascendancy/primary/secondary key，加与 artifact safe summary
   完全一致的升华与主技能规范名称。已确认核心 secondary key 必须逐一带规范名称，并真实出现在
   artifact 的启用 tested skill group 中。
5. 构造 `TargetDesignCoverage`，十个维度各一次：
   `skill_package`、`clear_duty`、`boss_duty`、`damage_delivery`、
   `ascendancy_and_passives`、`gear_synergy`、`defense_and_recovery`、
   `resource_and_spirit`、`combat_configuration`、`modelability`。
   状态可为 `research_adopted`、`independently_verified`、
   `unavailable_with_caveat`；不要提交 `rejected`。`research_adopted` 的 evidence ref 至少有一个
   必须是最终候选从 typed Research 结果中实际采用的 Family、deep record、pattern、semantic
   edge 或 fragment ID；`dq-*` 查询回执本身只能证明查询过，不能证明采用过知识。
   `independently_verified` 至少引用当前 anchor artifact，或该 Phase 5 run/source-hash 证据；
   不要使用自造引用。
6. 调用 `bind_build_progression_target_anchor`，传入上一步的 `verificationRef`。工具会验证
   artifact 时间、职业、等级、版本、Family 名称、目标 lifecycle 已通过、最终 failure audit、
   十维 coverage 和 typed Research provenance。Judge 仅为 `advisoryOnly`；但 lifecycle
   failed/unknown，或 Agent 自己判定为 `true_build_failure` / `mixed` 的候选都不能绑定。

PoB import/save 后 XML 字段顺序可能变化，所以不要自己重新导出再比较原始字符串。可信回执把
immutable artifact 的原始 source hash 与恢复后的 engine hash 分开记录；后者只证明验证过程中
未发生突变。回执是内容寻址的，不含 XML，手工改写结论后不能再被状态服务信任。

anchor 绑定后不可更换 artifact id、source hash、Family 或目标等级。

## 2. 有界联网开荒研究

`target_anchor_pending` 期间，start/status 会隐藏 starter packet 和 stale candidate，只返回是否
存在缓存的提示，避免目标 Create 被开荒证据影响。anchor 绑定后，如果已有 fresh exact-patch
`StarterResearchPacket`，从 `get_build_progression_status` 读取安全 packet。否则使用
Web/Browser 做最多六来源的有界研究：

- 优先当前精确 patch、明确等级分段的结构化/官方论坛/可信作者攻略；
- 两个独立来源收敛，或一个当前精确 patch 且明确分级的完整来源，才能 `supported`；
- 聚合帖/评论只发现来源；旧 patch 只作待复核，跨赛季禁用；
- 断网时提交 `limited_offline_inference` 并披露低证据。

调用 `intake_starter_research_packet` 前读取工具的嵌套 input schema。完整 URL 只能临时放在 intake
输入，入口立即哈希；不得把网页正文、长篇复制、整套装备/天赋/技能镜像、PoB 或账号角色信息放入
状态或聊天。

## 3. Research receipt 与 Blueprint

对每个实际阶段分别解析 ascendancy、玩家 `active_skill` 的 `skill:` stable key，并调用
`query_research_memory(ascendancy_key=..., primary_skill_key=...)`。每个阶段至少有一个精确 Family
typed receipt。

`query_research_memory` 可以接收物理图已关联的 `gem:` key，并在 typed receipt 中保存对应
gem/active-skill 等价 key 集合；因此真实 gem 查询可以授权对应 active-skill Family。但
`TargetAnchorIdentity`、`StageFamilyIdentity` 和蓝图始终使用 `skill:` key，不能把任意 gem/key
重命名为 Family identity。

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
- 在 claim 前，把准备采用的 `buildFamilyKey` 的 ascendancy、primary skill 和完整
  `secondarySkillKeys` 与 `StageFamilyIdentity` 逐项核对。若核心副技能不同，必须先修订尚未
  开始的蓝图；不能完成 artifact 后再换成另一个 Family。

提交 `ProgressionBlueprint`：

- 默认四个 artifact：已绑定 target anchor + 三个目标前阶段；无变化可合并，最多五个；
- 每个阶段使用稳定 `stageId`；
- `targetAnchorArtifactId` 必须等于已绑定 anchor；
- 最后 stage 必须 `routeRole=target`、目标等级与 anchor 相同，Family stable keys 和规范名称也相同；
- starter stages 的 evidence status 与 starter packet 一致；
- 第一阶段没有 entry bridge；其余每阶段有 `TransitionBridge`；
- `budget/price` gate 必须 `blocking=false`；
- 每阶段覆盖 clear、boss、defense、resource 职责；
- Family 改变时使用新的精确 query receipt。

蓝图启动后，只能用 `revise_future_build_progression_stages` 修改尚未开始的未来阶段；anchor、
已开始/重试/完成阶段、base class、target level 和版本事实不可变。

## 4. 创建 Target 之前的阶段

对每个 `requiresPhase5Run=true` 的 stage：

1. `claim_build_progression_stage`；
2. `create_build.py start-run`，再 `bind_build_progression_stage_run`；
3. 第一阶段 `new_build`；后续优先加载上一 artifact 后正向修改，大 Family 转型可从空重建；
4. 按当前阶段实际 Family 渐进查询 Research 并完整搭建技能组、装备、天赋、升华、配置、属性、
   抗性、Spirit、药剂/护符和资源；
5. `inspect_build_completeness`、preflight、活动快照 `verify_lifecycle_stage`、正式 Judge；
6. 在既有 Phase 5 retry 内修正 lifecycle/Judge 的真实问题；
7. 保存 artifact，再调用 `verify_lifecycle_stage(..., artifact_id=...)` 生成可信
   `verificationRef`，完成 validate/review；不要逐阶段 export；
8. 确认回执的 `evaluatedSourceHash` 与最终 Judge/artifact hash 一致；
9. `classify_build_progression_costs`；
10. 在 `StageCompletionReport.transitionReadiness` 中逐项提交 entry bridge requirement。id、kind、
   blocking、description 不能改写；所有 blocking gate 必须 `satisfied` 且有安全 evidence ref；
11. `complete_build_progression_stage` 只提交 `verificationRef` 作为 lifecycle 授权；其他复制字段
    不会覆盖可信回执。

`endgame_budget` progression stage 最低 82，`endgame_final` 最低 92；这是 progression lifecycle
验证预算，不是普通 Create 的等级映射。

阶段失败调用 `fail_build_progression_stage`。检查状态后最多一次
`retry_build_progression_stage`。暂停/恢复始终使用最新 revision。

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

Route v1/v2 继续可读；新 anchor-first route 写 v3。Judge findings 必须披露，但 v3 quality 不按
Judge aggregate 自动决定，而由 Starter/Research/cost evidence、TargetDesignCoverage 和 target
role 决定。

`save_build_progression_route` 只保留 Route v2 兼容写入，不能提交 anchor 字段。Route v3 必须
由完成全部状态机验证后的 `finalize_build_progression` 产生。
