# Phase 8 - 联网开荒研究与可验证的完整 BD 成长流程

## 阶段状态

功能实现完成候选，处于最终验收阶段。开荒证据、路线蓝图、可恢复阶段编排、Route v2、
粗粒度成本画像和完整成长包导出已经落地；focused 与 quick 门禁已通过。完成真实四阶段成长
路线验收、插件新进程复验和最终 full 门禁后，才把本阶段标记为已完成。

## 核心问题

公开成熟 BD 大多来自 80 级以后，不能证明早期怎样开荒。实际游戏中的高上限终局流派常有前期
硬伤，因此开荒升华、技能、天赋和资源系统可能与目标流派完全不同。完整成长流程不能把终局 PoB
机械删点、降级装备后冒充早期 BD，也不能要求开荒阶段必须沿用终局 Family。

Phase 8 将问题拆成三个独立设计任务：

1. 同一基础职业下，选择成型快、低依赖、前期清图和单体职责完整的开荒流派；
2. 使用成熟 Research、图、语料和 PoB 工具设计目标高上限流派；
3. 找到终局技能、升华、天赋、Spirit、资源和必需物品同时就绪的安全转型桥梁。

基础职业是唯一跨阶段硬锁。开荒与目标阶段允许使用完全不同的升华、技能、辅助、天赋、装备、
防御层和资源方案。

## 目标

- 默认 4 个真实里程碑；无实质变化时合并，最多 5 个；
- 每个重要里程碑都有独立 Phase 5 run、Judge 结果和可加载的 `FinalBuildArtifact`；
- 相邻阶段记录 typed 技能、升华、天赋、装备、配置和资源变化；
- 转型由机制闭环和合法性决定，价格只提供风险与获取难度说明；
- 联网开荒资料只形成 patch-scoped 候选证据，不能自动写入 Research 或 Learning Memory；
- 用户可以加载和导出任一真实阶段，而不是只阅读目标 BD 加一段文字过程。

## 联网开荒研究

联网搜索由外部 Agent 使用宿主 Web/Browser 执行，仓库不新增自主模型、隐藏 agent loop 或内部
全网爬虫。一次路线最多采纳六个来源。Agent 优先查找当前 patch、明确分级、说明零资金或
league-start 假设的职业开荒攻略。

来源使用规则：

- 当前 patch 的结构化分级攻略或官方论坛完整攻略可以作为直接候选证据；
- 聚合帖、评论和视频索引只用于发现来源，不能单独授权开荒结论；
- 至少两个独立来源收敛，或一个当前 patch 且明确给出等级分段的完整来源，才能标记为
  `supported`；否则为 `limited`；
- 旧 patch 资料只能作为待复核候选；跨赛季资料不能用于当前路线；
- 所有技能、升华、天赋和机制前提仍需当前 corpus/graph/mechanic 工具复核；
- 数值、资源和合法性仍由对应等级的真实 PoB/Judge 验证。

原始网页、攻略全文和完整 URL 不进入持久化状态。入口把 URL 立即转换为
`copy_safety.safe_url_ref`，只保存短摘要、patch、来源类型、更新时间、有限 claims 和哈希引用。
安全缓存以基础职业、精确 game patch 和天赋树版本为键，七天内可复用；过期或同赛季版本不一致
时只返回待复核证据。验证失败的 packet 可标记为 `deprecated`。
fresh cache 命中和后续状态恢复都会返回完整的安全 packet（claims、矛盾和待验证项），但仍不含
原始 URL；因此 Agent 可以重建 evidence-use 决策而不依赖先前聊天内容。
过期或同赛季版本不一致时只返回 `starterResearchCandidate`，必须重新联网/静态复核并提交新的
packet，不能直接绑定旧候选。

联网不可用或资料不足时，流程降级为 `limited_offline_inference`：Agent 使用当前知识库和成熟
机制职责反推开荒候选，仍完成阶段 PoB/Judge，但必须向用户披露开荒证据不足。

## 路线设计

开荒候选优先考虑：

- 技能可用等级和前期基础伤害；
- 清图、Boss 和资源恢复是否都有明确职责；
- 第一轮升华点是否立即产生收益；
- 是否依赖暗金、特殊阈值或复杂触发循环；
- 武器升级、属性和 Spirit 压力；
- 操作复杂度和失败状态。

与终局流派相似度和洗点量只是次要因素。每个实际阶段按自己的升华与主技能 Family 查询 Research；
开荒 Family 和目标 Family 不共享身份查询。转型前后的 Family 改变时必须产生新的记忆查询引用。

转型门槛可以包含：

- 核心技能和辅助可用；
- 升华点与洗点条件满足；
- 关键天赋阈值可一次性连接；
- Spirit、属性和武器要求满足；
- 主输出循环在实际使用频率下可持续；
- 清图、Boss 和基础防御在新形态中都成立；
- 机制必需物品已经拥有；
- 阶段验证和正式 Judge 通过。

价格本身不能自动触发转型。若玩家到目标等级时终局循环仍未闭环，目标阶段可以继续使用开荒或
桥接形态；未来终局只能作为未验证说明，不得强行切换。

阶段标签必须服从实际验证预算，不能用更高阶段名称包装较低等级结果：
`endgame_budget` 的目标等级不得低于 82，`endgame_final` 不得低于 92。80 级路线的目标
artifact 通常仍属于 `maps_entry`；它可以已经采用目标 Family，但必须按 80 级实际闭环程度描述。

## 可恢复编排

Progression 状态服务只保存安全 typed state，不创建 Desktop task、不调用模型。状态机为：

```text
research_pending
  -> blueprint_pending
  -> stage_pending -> stage_running -> stage_completed
  -> ...下一阶段...
  -> finalize_pending
  -> completed
```

并支持 `paused`、`failed` 和一次显式阶段重试。所有 mutation 使用
`operationId + expectedRevision` 做幂等和 CAS。

每个阶段固定执行：

1. claim 当前 `StageCreatePacket`；
2. 创建独立 Phase 5 run，并把 `runId` 绑定到阶段；
3. 第一阶段从空 PoB 构建；后续阶段优先加载上一 artifact 后正向修改；
4. 大规模换升华/技能时允许从空状态重建，但仍需记录相邻 delta；
5. 完整性检查、生命周期阶段验证、正式 Judge、artifact 保存和 review；
6. 校验 runId、职业、等级、版本、source hash 和阶段验证 hash；
7. 当前阶段完成后才开放下一阶段。

战役中期/后期的单体门槛由同一活动 XML 的启用技能组、非空 graph/mechanic/Research 证据引用
和正的 PoB offense 联合验证；这只证明职责闭环，不把数值门槛冒充为“实战手感良好”。首升华或
关键辅助同样从该 XML 读回，不能用调用者提供的布尔值伪造。

`endgame_budget` 的成型组件门槛同样绑定这份 XML：Agent 必须声明一个真实启用技能、升华或
当前 ItemSet 已装备物品，并同时提供已解析 stable component key 与安全外部证据引用。运行时
负责匹配，调用者自报“组件已上线”不能通过。

已经开始、进入显式 retry 或完成的阶段都不可修改。第一阶段开始后，只允许版本化调整尚未开始
的未来阶段，职业、目标等级、版本上下文和顶层路线意图不得改变。Phase 5 内部仍最多两次修正；
整个阶段失败后暂停，不自动重启路线。

## 数据合同

### StarterResearchPacket

- base class、game patch、passive tree version 和 captured at；
- `supported / limited / limited_offline_inference` evidence status；
- 最多六个安全 source descriptors；
- 等级区间、技能/辅助候选、开荒升华、武器方向、切换信号、装备假设；
- contradictions、unresolved premises 和 verification tasks；
- active/stale/deprecated cache status；
- 无原文、无完整 URL、无完整角色镜像。

### ProgressionBlueprint

- base class、目标等级和目标内容；
- starter selection 与独立 target intent；
- 2~5 个事件驱动 `StageBlueprint`；
- 每阶段有独立 evidence status；starter 阶段必须与 starter packet 一致，target/transition
  阶段使用自己的 Research、mechanic 和 PoB 证据；
- 阶段 Family 的升华和技能必须分别使用已解析的 `ascendancy:` / `skill:` stable key；
- `StarterEvidenceUse` 必须覆盖全部 claim，且至少选择一条 `adopted` 或 `caveated` 证据；全量
  rejected 不能形成开荒选择；
- `TransitionBridge`；
- 阶段 Research/Starter evidence 使用审计；
- 价格只作 advisory 的明确标志。

### ProgressionRouteArtifact v2

- `stageId` 是稳定阶段身份；
- lifecycle stage 只要求非递减，允许同一 lifecycle 内多个阶段；
- 每阶段有 route role、artifact、用途、play pattern、证据状态、成本画像和 caveats；
- 后续阶段有 typed changes 和 transition bridge；
- `targetArtifactId` 指向用户目标阶段，不暗示一定是毕业形态；
- route 记录 artifact coverage 与 `verified / limited` quality status；
- v1 route 继续可读，不原地重写；新 route 只写 v2。

## 公开工具

- `start_build_progression`
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

兼容保留 `save_build_progression_route`、`list_build_progression_routes` 和
`load_build_progression_stage`。新工具只读写安全控制状态，不接收或返回 PoB XML、网页正文、
完整 URL 或隐藏推理。

## 成本画像

现有 live price 只负责当前联盟通货和暗金事实：

- `cheap`：不高于 0.1 Divine；
- `moderate`：高于 0.1、不高于 0.5 Divine；
- `expensive`：高于 0.5、不高于 2 Divine；
- `chase`：高于 2 Divine；
- 无法取得 Divine 锚点或报价时为 `unknown`。

黄装不伪造市场价，只把现有 craft effort 映射为
`routine / moderate / expensive / chase`。路线不输出虚假总造价，只报告最高必需档位、付费依赖
数量、未知必需依赖数量、平替覆盖、价格风险和 live coverage。付费依赖统计已有可换算报价的
必需暗金，以及高于 routine 的必需黄装制作；价格快照六小时内复用，失败只降低证据状态。

## 导出

完整成长包固定包含：

- 路线说明文档；
- 每个阶段的 PoB XML 文件；
- 每个阶段的 PoB import-code 文本文件；
- 目标阶段的官方单阶段 `.build`。

除非 provider 能忠实表达多阶段，否则不得伪造官方 `level_interval`。MCP 响应只返回固定 inventory、
本地路径或 errorCode，不返回 XML、导入码正文或完整来源 URL。

## 实施顺序

1. 文档、schema 和 runtime 指南先行。
2. Starter evidence intake/cache、蓝图、Route v2 和成本合同。
3. 可恢复 progression state service 与 MCP facade。
4. 阶段级 Create skill 编排和 source-hash 绑定。
5. 完整成长包导出、manifest 和插件更新。
6. focused、quick、noncompute、代码审查、真实四阶段验收和 full。

## 验收

- 开荒和目标升华/技能可以完全不同，基础职业不同则失败；
- 原始网页、完整 URL 和整角色材料不会进入 cache、route、Review、Memory 或 Git；
- exact-patch cache 可复用，过期降级，跨赛季拒绝；
- 联网失败能有限证据继续，且用户可见；
- 每阶段都有独立、run-bound、hash-bound 的真实 artifact；
- 低于阶段验证预算的蓝图会失败关闭，80 级目标不能伪装成 `endgame_budget`；
- 成型组件必须由同一 XML 匹配、stable key 和安全外部证据联合证明；
- 转型不能仅由价格触发；
- 重复 lifecycle stage 可按 `stageId` 加载，v1 route 仍兼容；
- hard-valid 但有 playability/modelability 缺口的路线只能标记为 `limited`；
- 每阶段导出清单完整，目标 `.build` 失败时保留明确错误；
- 单阶段 Create、Phase 6 导出、Phase 7 blind isolation 和 Research DB 无回归。
