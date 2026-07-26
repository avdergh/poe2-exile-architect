# Phase 8 - 目标锚点优先的联网开荒与完整成长流程

## 阶段状态

功能实现完成候选，处于最终验收阶段。当前实现保留开荒证据、成本画像、多阶段 artifact、
恢复/重试和完整成长包导出，并把编排修正为：

```text
普通单阶段 Create 先生成目标 BD
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

1. 同基础职业下成型快、前期职责完整的开荒 Family；
2. 由正常 Create 独立生成并接受的目标高上限 Family；
3. 用技能、升华、天赋、Spirit、资源、防御和必需物品门槛连接两者的 TransitionBridge。

不能从目标 PoB 自动删点或降级装备伪造早期阶段，也不能先生成较弱的桥接 BD，再把它当作目标
毕业 BD。目标 anchor 一旦绑定，artifact id、source hash、Family、等级和版本都不可替换。

## 目标 Anchor

`start_build_progression` 创建 schema v2 状态并首先进入 `target_anchor_pending`，返回
`TargetAnchorCreatePacket`。Agent 必须按普通单阶段 `$poe-bd-create` 从空状态生成目标：

在 anchor 绑定前，start/status 不返回 `StarterResearchPacket` 或 stale candidate 正文，只暴露
是否存在缓存的布尔提示；因此目标 Create 不会提前看到开荒路线。

- 使用普通 Create 的渐进 Research recall 和真实 `researchMemoryUse`；
- 使用普通 Create 的最多两次内部修正；
- 在保存前按目标等级运行一次活动快照 lifecycle gate；失败或 unknown 时先在普通 Create 的既有
  retry 内修复，不能把资源断裂等真实问题留给 progression；
- 完成正式 Judge、保存 `FinalBuildArtifact` 和 `review-packet`；
- 保存后再用 `verify_lifecycle_stage(..., artifact_id=...)` 直接验证私有 immutable artifact，
  取得 `verificationRef`；
- 不读取 starter web packet，也不从尚未存在的早期阶段倒推一个低配目标。

随后调用 `bind_build_progression_target_anchor`。绑定必须同时验证：

- artifact 在当前 progression 启动后产生，职业、等级和六项版本事实一致；
- `verificationRef` 是该 artifact、目标 lifecycle stage 和原始 source hash 的可信回执，且结果为
  `passed`；失败、unknown、缺失、篡改或属于其他 artifact/stage 的回执一律拒绝；
- artifact 摘要中的升华/主技能名称与已解析 stable key 身份一致；
- 最终 Agent failure audit 为 `accept`，且不是 `true_build_failure` 或含混的 `mixed`；
- `TargetDesignCoverage` 恰好覆盖技能包、清图、Boss、伤害兑现、升华/天赋、装备协同、
  防御/恢复、资源/Spirit、战斗配置和 modelability 十个维度；
- Judge 只作 `advisoryOnly` 附件，不以分数或 warning 自动阻断/选优；
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
- result 只保存返回的 Family identity 与 record/pattern/edge/fragment ID；
- ref 同时绑定安全 request/result；后续知识库变化形成新 ref，不覆盖旧 provenance；
- 历史无 typed contract 的 dedupe ref 仍可用于旧 Research 去重，但不能授权新 progression。

蓝图的每个阶段必须至少有一个使用该阶段精确
`ascendancyKey + primarySkillKey` 的 receipt。Phase 5 可以继续渐进查询；artifact 的
普通 target anchor 没有 stage packet，其 `researchMemoryRef` 只需属于候选实际
`researchMemoryUse.dedupeQueryRefs`。目标前阶段必须把 claim 返回的
`StageCreatePacket.versionContext` 原样用于 Phase 5/Judge/artifact；后续渐进查询可以继续进入
`researchMemoryUse`，但不能替换 stage-bound ref。阶段完成时服务会验证所有实际采用的知识 ID
都真实出现在这些 receipt 中，并要求 receipt 在当前 progression 启动后实际查询过，不能只复用
历史 ref。时间门槛在蓝图提交时即检查；恢复运行不需要重建已被安全 receipt 隐去的原始 query
文本。

在 claim 前，Agent 必须把准备采用的 `buildFamilyKey` 的 ascendancy、primary skill 和完整
`secondarySkillKeys` 与 `StageFamilyIdentity` 逐项核对。若核心副技能不同，只能先修订尚未
开始的蓝图；不能完成 artifact 后再换成另一个 Family。阶段完成时服务会再次按 immutable
receipt 检查并失败关闭。

Family identity 统一使用玩家 `active_skill` 的 `skill:` stable key。`gem:` stable key 可以作为
`query_research_memory` 的查询入口；receipt 会记录由物理图确认的等价 key 集合，使该真实查询
可追溯到对应 active-skill Family。没有图关系的两个 key 不能互相授权。

Family identity 还必须保存升华/主技能的规范名称。声明已确认核心 secondary key 时，也必须保存
一一对应的规范名称并在同一 artifact 的启用 tested skill groups 中匹配。阶段 artifact 的 PoB
readback 摘要必须同时匹配 stable key 对应的名称，避免“查询 A Family、实际做 B 技能”的
provenance 漂移。

## 联网开荒研究

联网由外部 Agent 使用宿主 Web/Browser 完成，仓库不新增自主模型、隐藏 loop 或内部全网爬虫。
一次路线最多采纳六个来源：

开荒安全摘要使用 `StarterResearchPacket`，并按以下来源规则形成：

- 两个独立当前资料收敛，或一个当前精确 patch、明确等级分段的完整攻略，才可标记
  `supported`；
- 聚合帖和评论只能发现来源；旧 patch 只能成为待复核候选；跨赛季禁止采用；
- 组件存在性、机制前提、数值和合法性仍分别由 corpus/graph、mechanic、PoB/Judge 验证；
- 断网时允许 `limited_offline_inference`，但必须披露低证据。

URL 在 intake 时立即转换为 `safe_url_ref`。网页正文、完整 URL、PoB code/XML 和整角色镜像不
落盘。安全缓存按基础职业、精确 patch 和天赋树版本保存七天；过期或同赛季 patch 不一致只作为
待复核 candidate。

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

## 可恢复编排

新状态机为：

```text
target_anchor_pending
  -> research_pending / blueprint_pending
  -> stage_pending -> stage_running -> stage_completed
  -> ...目标之前的阶段...
  -> target stage claim（requiresPhase5Run=false）
  -> 重新校验并复用同一个 Target Anchor 的 artifact/lifecycle receipt
  -> finalize_pending -> completed
```

每个 mutation 使用 `operationId + expectedRevision` 做幂等与 CAS，并支持 pause/resume、阶段
失败和一次显式外部 retry。

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
- Judge 诊断完整保留，但不自动决定 v3 quality；
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
- `get_build_progression_status`
- `classify_build_progression_costs`
- `finalize_build_progression`
- `export_build_progression_package`

兼容保留 `save/list/load_build_progression_*`。所有工具只接收和返回安全控制状态。

## 导出

完整成长包包含路线说明、每阶段 PoB XML、每阶段 import-code 文件，以及仅目标 anchor 的官方
单阶段 `.build`。MCP 只返回完整 inventory、路径或 errorCode，不回显内容。

## 验收

- 普通 80 级 Create 与 Phase 8 前基线等价，Research recall、技能包、升华点和 Judge 流程无回归；
- progression 首先创建目标 anchor，之后只有目标前阶段运行新的 Create；
- anchor 绑定前必须通过目标等级对应的 artifact-bound lifecycle gate；资源断裂等真实构筑失败
  不能靠 caller boolean、药剂名称或放宽门槛变成通过；
- target closure 复用相同 artifact id/source hash 和可信 lifecycle receipt，机制门槛不满足时
  失败关闭；
- PoB XML 恢复后字节序变化不会破坏 artifact 身份；回执篡改、跨 artifact/stage 复用会失败关闭；
- Agent 认定存在真实 build failure 的候选不能成为 anchor；
- 每个阶段 Family/采用知识都有 typed receipt，伪造或跨 Family 引用失败关闭；
- 开荒与目标技能/升华可以完全不同，基础职业不同则拒绝；
- URL/网页/整角色原料不进入状态、route、Research 或 Memory；
- price 不阻断或触发转型；
- Route v1/v2 继续可读，新锚点路线为 v3；
- focused、quick、noncompute、独立 CR、真实四阶段任务和 full 全部通过。
