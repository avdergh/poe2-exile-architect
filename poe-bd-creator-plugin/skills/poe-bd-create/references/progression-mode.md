# Progression 模式：完整成长 BD

本说明只用于用户明确要求“从开荒到目标等级的完整成长流程”时。宿主 Agent 在当前可见任务内
串行完成全部阶段；仓库状态服务不创建任务、不联网、不调用模型。

## 核心边界

- 基础职业是唯一跨阶段硬锁。开荒和目标阶段可以更换升华、技能、天赋、装备、防御、资源与
  Spirit 方案。
- 开荒路线优先前期伤害、成型速度、清图/Boss 职责、资源稳定、低装备依赖和可操作性；与目标
  Family 的相似度和洗点量只是次要因素。
- 转型由机制闭环触发，不由市场价格触发。价格只说明获取风险；“已经拥有必需物品”可以是机制
  门槛。
- 每个实际里程碑必须有独立 Phase 5 run、正式 Judge、`FinalBuildArtifact` 和绑定到相同
  source hash 的 `verify_lifecycle_stage` 结果。不能从终局 PoB 自动删点、降级装备来伪造早期
  阶段。
- 默认 4 个里程碑；无实质变化时合并，最多 5 个。目标等级到达时终局机制仍未闭环，就保存可玩
  的开荒/桥接形态，把未来转型写成未验证说明，不强行切换。

## 1. 启动和版本

1. 调用 `get_freshness_report`，形成完整 `versionContext`。
2. 调用 `start_build_progression(operation_id, base_class, target_level, goal,
   version_context)`。
3. 保存每次返回的 `progressionId` 与最新 `revision`。所有修改调用都传唯一 `operationId` 和
   当前 `expectedRevision`；revision 冲突时先读状态，不猜测覆盖。
4. 如果返回 fresh exact-patch starter cache，读取响应中的安全
   `starterResearchPacket` 后直接进入蓝图；恢复任务时从
   `get_build_progression_status` 取回同一安全 packet 和活动 `StageCreatePacket`。
   stale 或同赛季不同精确补丁只会作为 `starterResearchCandidate` 返回，必须重新复核并提交新
   packet；跨赛季资料不能采用。

## 2. 有界联网开荒研究

缓存未命中时，由宿主 Agent 使用可用的 Web/Browser 搜索同一基础职业的当前开荒资料。项目内
不得新增爬网循环或模型调用。

- 最多采纳 6 个来源。
- 优先当前精确 patch、明确等级分段的完整攻略、官方论坛或可信作者攻略。
- 聚合帖和评论只用于发现原始来源，不能单独授权开荒结论。
- 两个独立来源对同一结论收敛，或一个当前精确 patch 且明确分级的完整攻略，才可能成为
  `supported`；其他情况为 `limited`。
- 旧 patch 只能作为待验证候选。跨赛季资料不能采用。
- 联网不可用时继续做 `limited_offline_inference`，但所有社区前提保持待复核。
- 社区内容只提出候选：组件存在性用 corpus/graph，机制前提用 mechanic 工具，数值与合法性用
  PoB/Judge 验证。

将这些内容整理成 `StarterResearchPacket` 输入。每个来源只保留短字段：临时 `sourceId`、
`sourceUrl`、来源类型、标题、claimed patch、是否明确
等级分段和不超过 360 字的摘要。结论写成 bounded claims，包含等级范围、组件 key、临时
`sourceRefs` 和验证任务。不得提交网页正文、长篇复制、整套技能链、整棵天赋、整套装备、PoB
code/XML、账号角色信息。

构造 packet、blueprint、成本请求或阶段完成报告前，先读取对应 MCP 工具暴露的嵌套
`inputSchema`；字段、枚举和必填项以 typed schema 为准，不要靠 validation error 逐项猜测。

调用 `intake_starter_research_packet`。工具会立即把 URL 转为 `safe_url_ref` 并写入 7 天
patch-scoped 安全缓存。不要在后续状态、报告或聊天中重复完整 URL。

## 3. 设计蓝图

先独立选择三个对象：

1. 同基础职业的开荒 Family；
2. 用户目标对应的高上限 Family；
3. 连接二者的 `TransitionBridge`。

每个阶段都解析实际升华和主技能 stable key，并按该阶段 Family 独立调用
`query_research_memory`。升华或主技能改变时必须使用新的 `dedupeQueryRef`；不同 Family 不能
共享身份查询。记录 Starter claim 的 `adopted/caveated/rejected` 及当前静态/机制/PoB 验证引用。

提交 `ProgressionBlueprint` 时：

- 2–5 个 `StageBlueprint`，默认 4；少于 4 时给出逐项 merge rationale；
- 等级严格递增；lifecycle stage 可重复但不得倒退；
- 每阶段有稳定 `stageId`、`routeRole`、实际 Family identity、技能/升华意图、职责覆盖、
  独立 evidence status、Research query refs 和成本预期；
- Family identity 必须使用已解析的 `ascendancy:` / `skill:` stable key；不能把搜索候选或任意
  安全字符串当成已确认 Family；
- starter 阶段 evidence status 必须等于 starter packet 状态；target/transition 阶段按自己的
  Research、mechanic 与 PoB 证据记录；
- 第一阶段无 bridge；每个后续阶段必须有 `TransitionBridge`；
- bridge 分别检查技能可用、升华点、洗点、天赋阈值、Spirit、属性、资源循环、防御、必需物品和
  Judge 门槛；
- `budget/price` requirement 必须非 blocking，bridge 至少有一个非价格的机制门槛；
- 所有 Starter claims 必须各有一条证据使用决策，且至少一条被 `adopted` 或 `caveated`；全量
  rejected 时重新研究，不能提交蓝图。

用 `submit_build_progression_blueprint` 提交。蓝图启动后，只有尚未开始的未来阶段可通过
`revise_future_build_progression_stages` 做版本化修改；已开始、进入显式 retry 或已完成阶段
不可改。

## 4. 串行阶段循环

对每个阶段严格执行：

1. `claim_build_progression_stage`，读取 `StageCreatePacket`。
2. 调用 `scripts/create_build.py start-run --memory-mode memory_assisted` 创建本阶段全新的 Phase 5
   run，随后用 `bind_build_progression_stage_run` 绑定 `runId`。
   本阶段所有 Phase 5/Judge 调用必须逐字段原样使用 `StageCreatePacket.versionContext`；
   `ruleset` 是 freshness 返回的游戏规则集（不是 trade/SSF 模式），
   `researchMemoryRef` 是本阶段已绑定的 Research provenance，不能换成临时新查询 ref。
3. 第一阶段 `new_build` 后从零搭建。后续阶段优先
   `load_final_build_artifact(previousArtifactId)` 再正向修改；packet 标记
   `rebuildFromScratch=true` 或发生大规模 Family 转型时可以 `new_build` 重建。
4. 按本阶段实际 Family 查询 Research，搭建完整技能组、装备、天赋、升华、配置、属性、抗性、
   Spirit、药剂/护符和资源状态。
5. 运行 `inspect_build_completeness`、`inspect_generation_preflight`，修复阻断并记录所有仍存在
   advisory 的处理决定。
6. 在最终活动状态调用 `verify_lifecycle_stage`，保留 `evaluatedSourceHash`。结果必须
   `status=passed`；failed/unknown 阶段不能宣称可用。
   `campaign_mid/campaign_late` 的单体职责必须在 `state` 中提交
   `singleTargetSkillName` 和安全的 `singleTargetEvidenceRefs`；工具只在该技能名真实出现在
   同一 XML 的启用技能组、外部证据引用非空且 PoB 有正伤害时通过。它只验证单体职责存在，
   不把此结果夸大为实际操作手感认证。升华或关键辅助则直接从同一 XML 读回。
   `endgame_budget` 的成型组件检查必须提交
   `buildDefiningComponentKind`、`buildDefiningComponentName`、
   `buildDefiningComponentKey` 和安全的 `buildDefiningEvidenceRefs`；组件只能是技能、升华或
   已装备物品，且必须在同一 XML 中匹配。不能用调用者自报布尔值证明机制已经上线。
   lifecycle stage 必须匹配真实验证范围：`endgame_budget` 最低 82 级，
   `endgame_final` 最低 92 级；80 级目标通常仍是 `maps_entry`。若高上限机制尚未闭环，
   保留已验证开荒/桥接形态，并把未来转型写成未验证说明。
7. 调用 `evaluate_generation_candidate`。Phase 5 内仍最多两次修正；每次修正后重新确认最终
   lifecycle hash。Judge hard-valid 但有 playability/modelability 缺口时允许保存，整条 route
   必须降为 `limited` 并完整披露。
8. Agent 接受最后一轮后调用 `save_final_build_artifact`，再完成本阶段 `validate-output` 与
   `review-packet --compact`。progression-bound 阶段不要调用单阶段导出。
9. 用 `classify_build_progression_costs` 提交本阶段必需/推荐/可选依赖：
   - 暗金按实时 Divine 等价值分类：`cheap ≤ 0.1D`、`moderate ≤ 0.5D`、
     `expensive ≤ 2D`、`chase > 2D`；
   - 黄装只传 craft effort，映射为 `routine/moderate/expensive/chase`；
   - 价格不可用时仍继续，只降低 cost evidence；
   - `paidDependencyCount` 统计有可换算报价的必需暗金，以及高于 routine 的必需黄装制作；
   - 不计算或报告整套总价。
10. 调用 `complete_build_progression_stage`，提交 artifact、同 hash lifecycle result、成本画像和
    安全阶段报告。成功后才领取下一阶段。

阶段发生不可恢复错误时调用 `fail_build_progression_stage`。检查状态后，最多调用一次
`retry_build_progression_stage`；不要自动重启整条路线。需要临时停下时用
`pause_build_progression`，恢复前先 `get_build_progression_status`，再用最新 revision 调用
`resume_build_progression`。

## 5. 完成与导出

全部阶段完成后：

1. 调用 `finalize_build_progression` 生成 Route v2。Route 使用稳定 `stageId`；
   `targetArtifactId` 指向最后阶段。
2. 调用一次 `export_build_progression_package`。
3. 用户可见结果逐项列出完整 inventory：
   - 每阶段 PoB XML；
   - 每阶段 PoB import-code 文件；
   - 路线说明文档；
   - 仅目标阶段的官方 `.build`。
4. 成功项给本地路径，失败项给 `errorCode`。不要展示文件原文。
5. 披露每阶段 Judge/lifecycle 结论、证据状态、成本最高必需档位、付费依赖数、未知必需依赖数、
   平替覆盖、价格覆盖，以及所有 `requiredUserDisclosures`。

读取 Route v2 阶段时优先传 `stage_id`。只有某个 lifecycle stage 唯一命中时才使用旧 selector；
重复 lifecycle 会返回明确歧义。
