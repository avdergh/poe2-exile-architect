# AGENTS.md - Poe2 BD Creator Agent 指南

这是本仓库给 Codex、Claude Code 和其他编码 agent 使用的标准工作指南。长期有效的规
则放在这里，具体阶段执行清单放在 `docs/phases/`。

## 文档语言策略

- `docs/ARCHITECTURE.md` 和 `docs/ARCHITECTURE.CN.md` 是当前唯一维护双语的文档。
- `server/ASSISTANT_GUIDE.md` 和 `server/MCP_*_BOOTSTRAP.md` 是直接注入不同 LLM client 的英文
  runtime prompt，属于语言策略的明确例外，不要求翻译或维护 `.CN.md` 副本。
- `docs/PROJECT_SPEC.md`、`docs/SCHEMAS.md`、`docs/phases/*.md`、`AGENTS.md`、
  `CLAUDE.md` 以及除此之外的其他仓库说明文档只维护中文。
- 不要新增 `.CN.md` 副本，除非用户明确重新改变语言策略。

## 项目方向

PoE2 BD Creator 是 verification-first 的 Path of Exile 2 BD 研究与生成工具基座。
Codex、Claude Code 等外部成熟 agent 负责研究、推理、比较、反思和 BD 合成。仓库本
身提供可重复执行的工具、结构化记忆、图知识、安全边界和评估合同。BD 创造不能变成
“Agent 给 plan，程序自动补完整 BD”的流程；整个构筑创造、查询取舍和失败修正仍由
Agent 主导。

长期闭环是：

```text
成熟 BD 数据 / PoB 导出 / pobb.in / poe.ninja
  -> quarantine-only raw intake
  -> 外部 Researcher Agent
  -> clean fragments + graph knowledge + long-term memory
  -> 外部 Architect Agent 按需查询图、记忆、语料和 PoB/计算工具
  -> Agent 主导候选 BD 创造和可评估临时状态搭建
  -> Headless PoB judge 与安全报告
  -> 成熟原 BD 的安全 Profile 与 FamilyTarget
  -> 同 Family / 同等级的独立盲测 Create
  -> 独立 Comparator 逐维比较（Judge 仅作 advisory）
  -> 具体知识回流 Research，跨维生成经验进入本地 Learning Memory
  -> 后续案例召回、correction 与趋势复审
```

仓库不应再增长项目内 autonomous LLM/provider loop。不要新增项目自带的 OpenAI/Claude
API runner、隐藏 agent loop，或持久化模型调用 prompt/report 日志。

## 不可协商规则

- 不要从零编写新的数值 BD 引擎。数值声明必须使用现有 Headless PathOfBuilding-PoE2
  wrapper，或明确标记为 unverified/unmodelled。
- 没有 PoB/modelability evidence，就不能声明 DPS/EHP/抗性/Spirit 合法性。
- 没有 static source，就不能创建 physical graph node。
- 没有已存在 graph node，就不能创建 semantic graph edge。
- 没有 typed tool，就不能让 agent 查询图。不要暴露 raw Cypher/Gremlin/SQL 拼接给
  agent。
- 模糊组件查询只用于候选发现：先 `search_graph_components`，再用
  `resolve_graph_component` 确认 stable key；模糊或向量相似度不能直接授权 semantic edge。
- 机制全文搜索同样只用于候选发现。页面标题、redirect、ID、搜索排名和 revision 只绑定页面身份；
  Research Agent 必须阅读选定页面内容，在 `mechanicAudit` 写 supports/contradicts/silent 与
  `relevanceReason`，并保留至少一项独立 corroboration。
- 单案例 Pattern 的自然语言范围由 `claimScopeReview` typed Agent 审核，不得使用任何语言的关键词/
  否定词表判定是否过度外推；Pattern 权重只由 typed confidence 与样本/Family/来源证据授权。
- Family identity 统一使用玩家 `active_skill` 的 `skill:` stable key。物理图已确认关联的
  `gem:` key 可以作为 Research 查询别名，但不能直接替代 FamilyTarget 或
  Family 身份权威的 stable key 集合；typed receipt 必须保存两者的等价 key 集合。
- Research 与 PoB 对同一组件可能使用不同显示名。Family 身份仍以 stable key 为身份权威，并
  保存 artifact 实际显示名；候选 stable key 必须先由 typed Family discovery receipt 验证，
  artifact 名称与候选展示名不同时，还必须由 artifact 的同一 graph snapshot 把 artifact 名称
  唯一解析到该 stable key。解析缺失、歧义、跨 snapshot 或 key 不同都必须失败关闭，不能因此
  放宽职业、升华、Family、artifact 或 lifecycle。
- 没有 patch/version/status，就不能进入 durable memory。
- 没有 copy-safety pass，就不能持久化成熟 BD 知识。
- 没有后 3 例相对前 3 例的四项联合趋势，就不能声称 Phase 7 出现初步进步信号；十案例趋势
  不能声明因果证明。
- Phase 7 不允许比较后修复或重新生成同一案例；Phase 5 已有有限内部 retry 不受此条影响。
- Judge 数值只能作为 Phase 7 `advisoryOnly` 附件，不能自动决定 Comparator winner 或写 reward。
- Create packet 只能包含 FamilyTarget、等级、版本和默认目标，不能泄露原 BD 装备、天赋、技能组、
  机制摘要或 Judge 结果。
- Phase 7 Blind Create 不得读取或调用任何 starter-research 材料、starter cache 或
  对照学习状态；联网开荒证据对 Phase 7 Blind Create 同样禁止。普通 Create 的目标等级
  低于 70 或 Research 无 Family 命中时，允许 Agent 联网研究与模型知识作为设计主源
  （见 poe-bd-create 工作流第 4 步）；≥70 且命中 Family 时仍以 Family 为身份与设计
  权威，联网证据只作补充，结论不替换 Family 结论。
- 每次普通用户触发 Create，直接生成用户请求的目标等级单阶段终局 BD（典型 80+）。`referenceBlind=true`
  的内部 Blind Create packet 禁止追问，直接按锁定 packet 执行。
- 普通 Create 以 Research Family 为身份与设计权威：`buildFamilies` 命中时 Family 优先（stable
  key 身份不变），联网/模型知识仅补维度、结论不替换 Family 结论；`buildFamilies` 为空时如实记录
  `retrievalOutcome="no_matching_memory"` + `noMatchReason`，以图/机制/语料与模型知识设计，数值
  与合法性仍以 PoB 读回与 Judge 为准。
- 发布插件内的普通 Create 必须通过 `start_generation_run / validate_generation_draft /
  validate_generation_output / complete_generation_review` 管理 Phase 5 run。draft validator 在
  Research 深读完成、最终候选摘要形成、首次正式 Judge 前对每个机制修订调用一次；相同 Blueprint、
  implementation signature 与 state hash 不得重复刷新。核心输出、辅助、伤害类型或 Mana/Life
  支付域改变后必须重验 Draft；只有 Blueprint 的机制意图也改变时才重验 Blueprint。Draft 调用必须
  传与 Checkpoint/Judge 相同的 group index 和精确技能名，完整 implementation signature 由服务端
  从最终 PoB 观察，不能要求 Agent 在构筑前猜最终组号或辅助；它不持久化、不消耗 run，
  最终 validator 仍负责 Judge/artifact 可信绑定。不得搜索仓库工作目录或要求用户安装/执行
  `scripts/create_build.py`；CLI 只保留为仓库开发兼容入口。
- 发布插件内的普通 Research 必须通过 `start_research_run / claim_research_case /
  inspect_research_case / read_research_case / search_research_case / get_research_review_contract /
  initialize_research_review / validate_research_review / accept_research_review /
  retry_research_review / cleanup_research_run` 管理运行态。新 run 只能保存在 user-data 并以 opaque
  `runRef` 暴露；不得把 queue/review/quarantine 写入调用者项目、源码仓库或
  插件 cache，也不得要求 Agent shell 编辑运行态文件。`scripts/research_mature_builds.py` 只保留仓库
  开发兼容入口。
- Create 当前默认禁止 `optimize_build` 和全局被动树重排。Agent 已经决定的机械变更应通过
  `apply_build_mutation_batch` 按 `bootstrap / mechanism_shell / skill_loadout / passive_delta /
  required_gear / ordinary_gear / config` 职能拆成小事务；不得把整个 BD 混进一个批次。只有以
  `new_build` 开始的 bootstrap 可省略输入 hash，后续事务必须串联上一批 `outputStateHash`。
  搜索、optimizer、隐式装备槽和隐式珠宝孔不能进入批次。失败只回滚当前职能事务；只有
  `rolledBack=true` 才能确认恢复，`recoveryRequired=true` 时必须停止并恢复活动状态。
  批次槽位白名单以 `server/compute/mutation_batch.py` 为准：`mechanism_shell` 每批必须恰含
  一次 `set_main_skill` 且只能初始化一次；`required_gear` 只允许武器槽；箭袋不在任何批次
  白名单（引擎槽位为 `Weapon 2`），只能走独立 `equip_item`。独立 compute/equip 工具
  （`equip_item`、`remove_skill_group`、`replace_skill_group`、`set_config` 等）共享同一活动
  构筑、同样改变 state hash，后续批次必须用其返回的最新 hash 串联。
- Create/evaluate 的 Research receipt 有 run 内时效：`evaluate_generation_candidate` 传入的
  `versionContext.researchMemoryRef` 以及 `researchMemoryUse.dedupeQueryRefs` 引用的 receipt
  都必须在当前 Phase 5 run 创建之后查询过（发现/比较阶段的旧 receipt 不能用于本 run 的
  evaluate/review，应在 run 内重新做定向查询）。
- `search_graph_components` 的候选必须返回可原样传给 resolver 的 `resolverPayload.componentKey`。
  Research Family 继续以 `skill:` key 为身份权威；`validate_level_availability` 负责把显示名、
  `gem:` 与 `skill:` 解析到同一 gem/active-skill 身份，存在多 granting gem 时必须返回歧义，
  不得猜选。PoB mutation 继续只接受宝石显示名。
- `set_skill`、`add_skill_group`、`replace_skill_group` 及 mutation batch 必须先解析全部请求宝石，
  再比较请求与 PoB 实际落盘的 canonical multiset；未知宝石直接拒绝，任何静默丢弃都回滚修改前
  XML、保持 state hash，并返回 `skill_group_incomplete`。
- Judge 对新生成的 80 级及以上候选使用确定性终局抗性门槛：火/冰/电分别不得低于 60%，
  非 CI 构筑的混沌抗性不得低于 30%；CI 只豁免混沌抗性。该门槛由共享 preflight 与正式
  Judge 入口共同执行，预检失败返回 `attemptConsumed=false`。79 级及以下、可信第三方参考
  构筑仍只回读抗性作 diagnostic，不产生这组 hard failure；元素 Max Hit 和其他防御层继续按
  各自合同评估。
- Lifecycle 元素抗性门槛独立于 Judge，但必须按活动 PoB 的实际等级计算，而不是
  按可重叠的 lifecycle stage 名称或调用者提示计算：45–64 级火/冰/电各 30%，65–79 级各 50%，
  80–89 级各 60%；45 级以下和 90 级以上不增加 Lifecycle 百分比门槛。90 级以上仍由 Judge 的
  60/30 终局规则负责，Lifecycle 不得再叠加 75% 满抗要求。
- Create 的 Judge 反馈默认使用 `strict_mode=false`（`feedbackMode=hard_only`）：内部计算照常
  执行，但对 Agent、可信 attempt、artifact、retry、Review 只暴露确定性
  `hardFailures`、`passed`、快照绑定和安全诊断，不返回 aggregate、quality band、
  playability/quality warning、reward、主观 caveat 或基于它们的自动结论。只有用户明确要求
  “严格模式”或调用方手动传 `strict_mode=true` 时，才可在本次 run 全程使用完整反馈；首个
  attempt 后禁止切换模式。checkpoint 和 lifecycle 的建议性字段遵循同一开关，原始 PoB 数值和
  确定性 gate 不受影响。
- 重复的 completeness、preflight、stats 和 defenses 检查使用
  `inspect_generation_checkpoint`，以语义 `build_state_hash` 合并；状态改变后必须生成新检查，
  正式 Judge 与 artifact-bound lifecycle verification 仍是独立可信步骤。
- 最终 Support、Jewel、Socket 回执必须在装备、天赋、珠宝、Rune 和 config 锁定后生成。
  Checkpoint 必须区分 `current/stale/missing`；正式 Judge 对适用检查的 stale/missing、明确失败和
  未应用正收益非消耗式拒绝。已执行的 `inconclusive` 不是 missing，允许继续但交付保持 candidate。
- 90 级以上的额外天赋珠宝槽审计保持核心天赋优先：Agent 先完成核心机制与重要支撑节点，再把这些
  精确节点 ID 作为 `protected_node_ids`，用 `evaluate_next_jewel_socket` 比较一颗已选珠宝在全部当前
  可达槽位的等点边际收益。工具只可替换当前安全单点叶节点，不向内拆分支、不重排树，也不以成熟
  案例槽数、固定轮数或最低槽数作为目标。正收益只能经 `apply_next_jewel_socket_decision` 原子应用，
  并在新 state 重做审计；`policy_limited/inconclusive` 可 Judge 但只能交付 candidate。
- `inspect_generation_checkpoint` 和 `evaluate_generation_candidate` 必须复用同一个无评分
  `HardLegalityAudit`。属性、装备/宝石等级、武器兼容、Spirit、普通与武器组天赋预算、黄装
  词缀、生成候选遗留的 `Scaffold ...` 装备和 rare/magic 装备缺少 `Item Level` 等确定性非法状态
  必须在写 Judge receipt 前拦截，返回 `attemptConsumed=false`，不能消耗
  三次正式 Judge 额度。装备优化或升级探针也必须在临时换装后审计整个角色，并拒绝属性不足或
  已装备槽位消失的候选。
- Phase 5 Agent 输出只需在顶层保存一次完整最终 candidate；每个 `generationAttempts` 可用
  `prototypeBuildCandidate: {candidateId}` 简写。helper 必须以 attempt index、candidateId、可信
  evaluation receipt 和 artifact-selection 交叉校验选中轮次，不得要求 Agent 在每轮重复候选正文。
- `craft_item` 返回的 Perfect Essence、符文和腐化效果必须由 PoB `crafting_options` 派生的
  `craftReceiptRef` 证明；后续 `equip_item` 或批量 `equip_item` 必须原样传该引用。制作、
  装备写入、completeness、Judge 前共享审计和 artifact 保存统一使用来源感知物品合法性，不得
  再用独立的普通词缀检查器覆盖结果。receipt 只保存版本、来源类别和语义指纹，不保存完整物品
  文本；物品、槽位或版本改变时失败关闭。第三方旧物品无 receipt 可保留诊断，但不能因此成为
  新生成 artifact 的可信特殊来源。
- public `equip_item` 与 mutation batch 必须共用一次事务性写入：显式特殊来源必须原样传
  `craftReceiptRef`，写入后从实际槽位读回完整语义物品并再次核对 receipt；异常或 Rune 同槽继承
  必须恢复输入 XML，只有 `rolledBack=true` 才可继续。
- Create 的组件、天赋、物品和词缀搜索应使用精确 query，选中候选后改用精确详情工具；不得设置
  固定候选条数上限，也不得把默认返回量当成搜索上限。同一未改变 Family 身份的 Research 不设
  固定摘要、维度或 record 深读额度；应继续查询到设计职责、关键条件、失败场景和验证任务得到
  足够覆盖。checkpoint 只阻止相同 query/receipt 因上下文压缩被原样重放，不能阻止新的定向查询。
- 精确 Family 查询必须检查 `familyRecordCoverage / familyRecordIndex /
  familyPremiseCatalog`。选中 Family 的关键失败 premise 必须在 `ResearchMemoryUse` 中标记
  `resolved/caveated/not_applicable`；resolved 只能引用本轮 record-detail 回执实际深读的解决
  记录。caveated premise 不自动判 BD 失败，只降低采纳档位并把风险写入注意事项。
- 联网页面、外部样本、普通图/语料查询只能补充 `toolReferences / rationaleSummary /
  unresolvedCaveats / toolFeedbackEvents`，不能写入 premise `resolutionRefs`；缺少本轮 deep-read
  解决记录时 premise 必须保持 `caveated` 或明确 `not_applicable`。
- 机制完整且合法的基础版本形成后必须做一次符合当前
  等级的主动质量收尾，检查高影响武器、辅助、天赋路径、珠宝、符文/灵魂核心和配置。Judge 报警
  不是探索前提；只去重同一 state hash、同一目标和同一参数的机械调用，不缩小合理的优化搜索
  空间，也不拿终局数值阈值要求低等级阶段。
- Family `gear_synergy` 中以 `unique_enabler` 声明、且职责不是 `optional_upgrade` 或
  `budget_substitute` 的暗金/暗金珠宝，默认属于所选 source-case 变体；必须先于普通黄装实装并逐组件
  记录 `adopted/caveated/rejected`。当前版本不可用时使用 `rejected`，并在 summary/application 中
  明确记录 unavailable 原因。只有用户明确排除、当前版本不可用、机制前提被当前事实否定，
  或一次配套重规划后仍存在无法修复的合法性/资源失败时才能拒绝。普通 `relevant_uniques` 候选放在
  基础黄装后评估；radius/Time-Lost 继续位置化评估，普通黄珠宝最后优化。价格不得成为拒绝理由。
- 90 级 Create 默认以三槽腰带和三个护符为质量目标，但 1/2 槽腰带仍是合法状态；缺少
  `Charm Slots` 为 unknown，不得默认为 0。有效容量读取最终 PoB `CharmLimit` 并封顶 3，装备
  护符超过容量必须回滚并作为硬合法性失败。
- 所有可镶嵌装备都必须评估符文/灵魂核心；`optimize_item_sockets` 只在保留现有底材、物品等级、
  隐式和显式的前提下增加 1–2 个 PoB crafting option，并继续用现有 receipt + `equip_item`
  写回。无机制收益或机制不适用可以不用，但必须记录理由；价格和用户预算不参与采用决定。
- 90 级 softcore Create 的装备优化默认在元素 60%、非 CI 混沌 30% 后停止继续主动购买普通抗性；
  用户明确要求满抗时才覆盖为 75%。`plan_gear / optimize_item / craft_item /
  optimize_item_sockets` 必须共用该饱和目标，并保留 `resistsCapped` 兼容字段与新的
  `resistanceTargetMet` 语义。
- Lifecycle 发现未建模资源恢复时只输出“需验证未建模恢复覆盖”，不得据静态缺口直接宣布会断蓝。
  Agent 先用 PoB/corpus/Graph/Research，必要时联网复核，再针对辅助、天赋、技能、装备、护符、
  镶嵌、药剂或轮转修复。每个 run 最多两次核心机制级重建；两次后硬合法但仍无法证明只能导出为
  “待验证候选”，已确认真实失败且补救失败则停止交付。局部装备/辅助/天赋修正不计核心重建。
- Lifecycle/Checkpoint 的持续资源审计只声明覆盖 Mana 与 Life，并读取两者的每次、百分比、每秒和
  百分比每秒成本。`*LeechGainRate` 已含 On-Hit，不得再与 `*OnHitRate` 相加；后者只能作为缺失时的
  回退。未建模 Mana 恢复不能覆盖确定性的 Life 失败。
- 每个通过正式 Judge 且通过共享硬合法性审计的 attempt 都是可保护的 passing baseline。主动
  质量收尾必须在隔离的新状态上进行；后续候选更好且合法时可晋升，若仅质量增量导致回归，可用
  `save_final_build_artifact(..., attempt_index=baseline轮次)` 保存仍有效的精确 baseline。即使
  新状态被 preflight 拦截而没有消耗 Judge、baseline 仍是最后一条 receipt，也按活动 state hash
  已偏离来识别恢复。恢复必须有当前 MCP 进程内的精确 Judge 快照、同 state hash 合法性回执和显式
  `laterFindingsScope=candidate_delta_only`；后续发现若也影响 baseline、快照丢失或绑定不一致，
  必须失败关闭。
- lifecycle gate 使用默认 compact 响应，每个正式 Judge attempt 前最多一次；
  同一 state hash 不重复验证。artifact 保存后再独立且只执行一次 artifact-bound lifecycle。
  活动 lifecycle 必须显式复用该 attempt 的 offense group/name；artifact lifecycle 强制继承
  artifact Judge calculation context，不接受调用方改选其他技能。
  调参期间使用 `inspect_generation_checkpoint`，`detail=full` 只用于具名局部诊断。
- Create 查询使用紧凑 response profile，
  选定的重要 evidence、条件、失败场景、验证任务和未解决项写入本地有界 working checkpoint。
- 目标与候选必须在保存前修复活动快照 lifecycle gate，并在保存后使用
  `verify_lifecycle_stage(..., artifact_id=...)` 生成可信回执。failed/unknown、篡改或跨
  artifact/stage 的回执不能绑定；调用者布尔值不能授权药剂或资源续航。
- Phase 5 正常顺序是保存 artifact 后再消费 review。若旧任务误先消费 review，
  `save_final_build_artifact` 仍必须核对同一 candidate/attempt、精确 Judge snapshot 和语义
  state hash 后才能恢复保存；不得手工删除 review marker、可信 receipt 或运行锁。
- 能归入 Research schema 的知识不能写 Learning Memory；Memory correction 必须追加事件并保留
  do-not-repeat 历史。
- 不要持久化或暴露第三方成熟 BD 的原始整角色材料：PoB code、raw XML、raw account/character
  细节、长篇复制攻略文本，或由全部装备槽、整棵已分配天赋、全部技能组和完整配置组成的整角色
  镜像。允许保存可复用核心机制包，包括关键技能与辅助组合、局部核心天赋连接、暗金/装备与技能、
  天赋、资源系统的完整联动；不得按组件数量机械拒绝。系统自己
  生成、经过可信 Judge 且由 Agent 明确接受的最终候选，可以作为 Phase 6 本地私有
  `FinalBuildArtifact` 保存完整 PoB XML，但不得进入聊天、人工验收包、研究记忆或 Git。
- 禁止游戏内交互、overlay、内存读取、自动化或 live-screen parsing。

## 当前事实源

- `AGENTS.md`：标准 agent 操作规则、工具地图和变更审查 Checklist。
- `CLAUDE.md`：轻量 Claude Code shim，指回本文件。
- `docs/PROJECT_SPEC.md`：中文唯一项目总纲，维护方向、边界、Phase 关系和 Phase 状态。
- `docs/ARCHITECTURE.md` / `docs/ARCHITECTURE.CN.md`：高层架构和数据流，唯一双语文档。
- `docs/SCHEMAS.md`：中文唯一核心数据结构合同。
- `docs/JUDGE_SCORING_SYSTEM.md`：Judge 当前评分策略、证据分层、兼容逻辑和查询路径说明。
- `docs/phases/`：中文唯一各阶段执行计划和验收标准。
- `server/ASSISTANT_GUIDE.md`：通过 MCP 展示给 LLM client 的 runtime 指南。
- `docs/research/`：研究流程的历史设计与方法归档（`MEMORY_SYSTEM_DESIGN.md`、
  `EXTRACTION_METHOD.md`、`BD_KNOWLEDGE.md`、`AGENT_MEMORY_SYSTEM_RESEARCH.md`）；现行运行合同
  以 `/poe-bd-research` Controller、显式 `/poe-bd-research-worker` 与 typed
  `get_research_review_contract` 为准；CLI `workerPrompt` 只保留仓库开发兼容。
- `scripts/verify.ps1`：验证 profile。

根 `README.md` 现在只承担安装、skill 自动化入口和安全边界说明。它不能夸大尚未完成的
生成、导出、对照学习效果或 reward-memory 能力；详细阶段细节仍维护在 `docs/phases/`。

## 命令

如果 Windows 工作区的 PATH 里没有 `uv`，使用仓库自带的 uv：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_fragment_extraction.py -q
.\.tools\uv\uv.exe run pytest tests/test_mature_fragment_extraction.py tests/test_mature_ninja_payload.py tests/test_mature_pobb_payload.py tests/test_mature_source_intake.py tests/test_mature_source_probe_runner.py tests/test_mature_sources.py tests/test_mature_sample_contract.py tests/test_mature_eval.py -q
.\scripts\verify.ps1 quick
```

验证梯度：

- `ruff check` 继续作为正确性硬门禁；`ruff format --check` 只报告排版差异并发出 warning，不阻塞
  quick / noncompute / full / lint 或 CI/release。
- touched module 使用 focused tests；
- knowledge/MCP/lifecycle/doc 改动使用 `.\scripts\verify.ps1 quick`；
- 跨范围非 engine 改动使用 `.\scripts\verify.ps1 noncompute`；
- runtime packaging、release gate 和最终合并使用 `full`；`full` 明确排除重型
  `tests/test_compute.py`，因此不会重复消耗十几分钟跑 PoB golden；
- `compute` 只在直接修改 PoB 引擎、Lua bridge、数值计算或 optimizer 行为，或用户明确要求时
  手动运行，不再是普通发布/合并门禁。它在 Windows 经常运行 15 分钟以上，调用时外层超时至少
  30 分钟（`1800000ms`）。

## 工具 / 文件地图

### 入口

- `server/main.py`：MCP 工具实现的单一事实源（聚合 server `poe2-build-mcp` 保留，供测试与旧宿主配置兼容）。不要在聚合 server 之外新增重复工具实现。
- `server/mcp/knowledge_server.py` / `build_server.py` / `research_server.py` / `learning_server.py`：
  四个按域拆分的 MCP server 入口，各自 re-register `server/main.py` 中本域工具并携带各自的短 bootstrap
   instructions。新工具先在 `server/main.py` 实现，再按归属加入对应入口的 `_TOOLS`（归属判据：是否触碰
   活动 PoB 引擎——触碰则归 `build_server`，包括 artifact-bound lifecycle 验证；纯状态机归
   learning 域；只读知识/研究查询归 knowledge；intake/propose/validate 归 research）。
  归属变更必须同步 `tests/test_mcp_split.py` 的覆盖断言。
- `server/MCP_*_BOOTSTRAP.md`：各 server 的短 instructions（几百字硬边界）；完整流程在 Skill 中。
- `server/ASSISTANT_GUIDE.md`：通过 MCP instructions 交付给 LLM client 的 runtime 指南。
- `server/BUILD_ADVICE.md`：由 `build_advice` 搜索的持久 BD 原则文本。

### Compute 层

- `server/compute/engine.py`：长生命周期 Headless PathOfBuilding-PoE2 JSON-RPC 进程和
  build state 调用，是数值权威。
- `server/runtime/node.py`：Node/npm package runner 的共享宿主发现层。converter 和 manifest
  验证必须复用它，支持显式环境变量、系统 PATH 和 Codex Desktop 随附 runtime；不要重新引入
  对全局 `node` / `npx` 的硬依赖。
- `pob/pob_headless.lua`：进入 pinned PoB-PoE2 代码的 Lua bridge。
- `server/compute/pob_code.py`：PoB share code/link/XML import/export codec。
- `server/compute/buildopt.py`：整体 build optimizer；MCP `optimize_build` 当前默认禁用，只保留
  显式维护开关，不属于 Create 流程。
- `server/compute/mutation_batch.py`：Agent 已决定的机械变更按职能分型的小事务执行器；每种
  scope 有独立白名单、数量上限和轻量后置条件，不执行搜索或优化器。
- `server/compute/itemopt.py`：rare item、jewel、gear-plan 和 upgrade optimization。
- `server/compute/craftopt.py`：crafting-system optimization。
- `server/compute/supportopt.py`：engine-measured support selection。
- `server/compute/solver.py`：stat lever ranking 和 target solving。
- `server/compute/skilltext.py`：skill text normalization 和 lever templates。

### Judge 层

- `server/judge/models.py`：Phase 1 judge 的 evaluator version、v3 metric keys 和 failure code
  / caveat 常量。
- `server/judge/rules.py`：class/ascendancy、support/socket v1、PoB weaponCheck 和
  physical-invalid blocker；weapon/skill 兼容性以 PoB readback 的 `disableReason` 为权威，
  不要在 Python 里按技能名硬编码武器需求。
- `server/judge/scoring.py`：`judge_v6_evidence_separated` 评分；hard floor 与 quality target
  分离，动态可用主资源池 recovery、异构 Max Hit、CI 混沌免疫、EHP 物理短板补偿和扁平
  aggregate 权重；`scoreBreakdown.offense` 必须输出 provenance、evidence level、raw/effective
  DPS 和 minion/count 诊断。
- `server/judge/modelability.py`：partial modelability、main socket group core blocker 和轻量
  whitelist caveat。
- `server/judge/evaluator.py`：从 active PoB readback 生成内部 `BuildEvaluation`；如果
  `judgeSelectedSkill` 被用于 offense，socket/modelability/weaponCheck 也必须跟随 selected
  skill group，而不是继续检查最后点击的 buff/战旗组；输出 `defenseModel` 只作诊断，不替代
  PoB Max Hit / EHP 评分证据。
- `server/judge/comparison.py`：候选与参考的 `selectionWinner` / `rewardWinner` /
  `rewardStrength` 合同；limited evidence 可以 selection，但 `rewardWinner` 必须保持
  `unknown`，不能写成强 reward。
- `server/judge/runner.py`：dedicated engine safe-call，处理 import/evaluation timeout、EOF 和
  crash recovery。
- `server/judge/fixtures.py`、`server/judge/benchmark.py`：synthetic Phase 1 baseline，写入
  user-data runtime，不进入仓库。
- Judge 核心仍是内部基线；Phase 5 只在 `server/main.py` 公开受限的
  `evaluate_generation_candidate` 入口，用于评价 Agent 已搭建的活动构筑。不要公开可接受任意
  原始输入的通用 Judge 工具。
- `server/generation/evaluation_snapshots.py` 只在当前 MCP 进程内短暂保留 Judge 的精确 XML，
  供 `save_final_build_artifact` 保存；run receipt 仍然 raw-free。保存前用共享
  `build_state_hash` 比较语义输入，不能用会受 `PlayerStat` / `FullDPSSkill` 刷新影响的 raw XML
  hash 判断是否修改过构筑；精确快照丢失时必须失败关闭，不能替换 Judge XML。
- Phase 1 对使用 weapon set passives 的 dual-state build 只给 limited reward；没有 State_A /
  State_B 分别评分证据时，不能把单状态最高 DPS 写成强学习信号。
- Phase 1 对 `FullDPS` rollup、召唤物 PoB output、投射物下界、关键 metric 缺失等 evidence
  只给 limited reward；这些信号可以帮助单个 BD 诊断，但不能污染后续 reward memory。

### Knowledge 层

- `server/knowledge/db.py`：SQLite/FTS corpus 查询。
- `server/knowledge/mechanics.py`：本地 mechanics 解释和 wiki-tier 引用。
- `server/knowledge/refbuilds.py`：仅用于校准的 reference build 摘要。
- `server/knowledge/lifecycle.py`：lifecycle route 模型、feedback memory 和 route helpers。
- `server/knowledge/lifecycle_*`：lifecycle cohort evidence、source evidence、verification、
  quality gates 和 evaluation harness。
- `server/knowledge/mature_learning.py`：mature-learning SQLite schema、sanitizer、seed import
  和 deterministic baseline extraction。这里的安全边界不能破坏。
- `server/knowledge/copy_safety.py`：共享 copyability guard。
- `server/knowledge/mature_sample_contract.py`：sanitized mature sample manifest 校验。
- `server/knowledge/mature_eval.py`：creator/evaluator contamination 和 typed gap 合同。
- `server/knowledge/mature_fragment_extraction.py`：外部 agent research packet builder 和 clean
  fragment schema v3 validator。它不能调用模型 provider。
- `server/knowledge/research_models.py`、`server/knowledge/research_memory.py`：Phase 4 typed
  proposal、聚焦 `DeepResearchRecord`、SQLite 写入和两级召回合同。单条深度记录只回答一个主要
  问题；中文正文原则上不超过 400 字，英文不超过 250 个单词。
- `server/knowledge/mature_source_intake.py`：按 build family 聚合来源变体，并构建供外部
  agent 研究的 raw-rich、quarantine-only case。
- `server/knowledge/mature_ninja_payload.py`：从渲染后的 poe.ninja build 页面提取 PoB import
  material，并转换为 quarantine-only payload row。
- `server/knowledge/mature_pobb_payload.py`：把 pobb.in 链接或 raw build source 导入为
  quarantine-only payload row。
- `server/knowledge/research_intake_ledger.py`：每用户本地角色级 research intake 去重 ledger
  （user-data SQLite，只存 `character-hash:` 引用和安全元数据）；queue 按 (league, character_ref)
  跳过已入队角色并分页凑满新案例，accept 后晋升为 `accepted`。

### Comparative Learning 层

- `server/learning/models.py`：FamilyTarget、盲测 Create packet、逐维 comparison、Memory、correction
  和 campaign state typed contracts。
- `server/learning/case_store.py`：case-bound quarantine；原始 code/XML 只存在本地隔离目录。
- `server/learning/memory.py`：Research SQLite 之外、由安全发布种子初始化的本地 append-only
  Learning Memory、召回、修正和防振荡。只提交净化种子，不提交用户运行态文件。
- `server/learning/service.py`：Phase 7 CAS、幂等、暂停、恢复、显式 phase retry、串行 case gate 和
  十案例趋势汇总。它不创建 Desktop task、不调用模型。
- Reference/Profile 与 Comparator 使用同一可见任务；Create 必须是另一个任务。task/thread 创建与
  协调由 `$poe-bd-learning-loop` skill 完成。

### Generation Provenance / Lifecycle 层

- `server/generation/validation_checkpoint.py`：按语义 build-state hash 合并 completeness、
  preflight 和有界数值回读；只缓存安全结果。
- `server/generation/progression_provenance.py`：普通 Create 的 Research receipt/premise 审计
  （receipt run 内时效校验、family-premise 决策完整性）；不读取或返回 PoB XML。
- `server/generation/progression_lifecycle.py`：保存并重新校验 artifact-bound lifecycle
  内容寻址回执；原始 artifact hash 与 PoB 恢复态 hash 分开记录，回执不保存 XML。
- `server/MCP_BOOTSTRAP.md`：legacy 聚合 server 的 instructions（`python -m server.main` 兼容入口
  仍注入它）；四个拆分 server 各注入自己的 `server/MCP_{KNOWLEDGE,BUILD,RESEARCH,LEARNING}_BOOTSTRAP.md`。
  均为几百字硬边界，避免延迟工具发现反复注入完整 `ASSISTANT_GUIDE.md`；完整指南仍是人类可读
  runtime 事实源。
- `server/runtime/tool_telemetry.py`：只记录工具名、耗时、响应字节和安全关联 ID 的上下文成本
  遥测；禁止记录参数正文和响应内容。
- 价格与用户预算只作风险和获取难度说明，不改变普通 Create 的 Family、暗金、黄装、符文或药剂
  选择；`get_prices` 必须在装备和机制方案锁定后调用。

### Live / Freshness 层

- `server/freshness/*`：patch/tree/PoB/poe.ninja freshness providers、cache 和 evaluator。
- `server/live/meta.py`：live meta shaping。不要从 ascendancy-only 数据推断 build-level
  popularity。
- `server/live/mature_sources.py`：对 build-level source 可用性做 copy-safe response-shape
  probe。
- `server/live/mature_source_probe.py`：比较候选成熟样本来源，并渲染安全的 source-probe
  report。
- `server/live/prices.py`、`wiki.py`、`update.py`、`version.py`：价格查询、live wiki fallback、
  更新和版本辅助。

### Scripts 和 Data

- `scripts/run_mature_source_probe.py`：本地 source-probe report 辅助脚本。它不运行 LLM。
- `scripts/merge_build_families.py`：按集合包含规则（身份 = 升华 + 主输出技能集合，gem 等价
  展开）全量重构存量 Build Family 档案；dry-run / validate / apply 三模式，apply 前整库备份，
  合并写 `family_merge_log`（回滚 = apply 前快照恢复，日志仅审计）；记录迁移保留原
  knowledge_key，由 backfill 统一重算 canonical；完整顺序是 merge → backfill → 再跑一次
  merge 收敛，共用 `research_memory._resolve_family_target` / `_merge_family_records`。
- `scripts/reconcile_orphan_records.py`：处理 family 挂载失效的孤儿记录——join（挂回既有
  family）/ new（建 family 并移动）/ 无身份降级为待复核；`--skip-group` 跳过可疑身份组留
  人工确认，expand 不自动执行。
- `scripts/backfill_semantic_edges.py`：存量 Research Memory 的确定性 T1 语义边回填脚本
  （transition_gate / mechanic_chain / failure_mode / modelability_caveat → typed edges）。
  从只读一致性快照副本派生候选，离线去重与逆边/短环预检后分块经 `propose_semantic_edges`
  持久化；`--dry-run / --validate / --apply` 三模式，幂等。单案例 cooccurrence 不提升。
- `scripts/run_judge_user_samples.py`：Phase 1 真实 PoB code transient 验收脚本。输出
  sanitized report，不持久化 raw PoB code/XML；允许输出 `judgeSelectedSkill` 摘要以便审查
  buff/战旗/辅助技能导致的 0 DPS 误读，但禁止输出完整 gem/support links。输入支持整文件
  XML、JSON/JSONL/manifest、显式分隔符和逐行 code；失败报告只输出 sanitized `errorKind`。
- `scripts/smoke_*.py`：按子系统划分的 focused smoke checks。
- `scripts/install_local_validated_runtime.py`：安装已认证 runtime data 到本地。
- `scripts/build_bundle.py`：构建 `.mcpb` bundle。
- `scripts/build_research_release_seed.py`：从本地成熟 Research 库导出 creator-safe、无运行态和本机
  路径的发布种子。
- `scripts/package_physical_graph_seed.py`：把最新验证物理图转换为不含绝对路径的发布种子。
- `scripts/build_codex_plugin.py`：把服务、helper、依赖、语料、Research/graph 种子和 PoB 子集组装为
  自包含 Codex 插件；必要种子缺失时失败关闭。
- 更新 Codex Desktop 插件时先用 `codex plugin list --json` 确认真实 local source，把已验证 stage 以 staging + 可恢复 backup 部署到该 source，再执行 `codex plugin add <plugin>@<marketplace>`。
- WindowsApps 内 `codex.exe` 若被 ACL 拒绝，复制同一桌面端签名程序到任务临时目录，核对 SHA-256 与 Authenticode 后安装；确认无 PoB 子进程再停精确旧插件服务，完成后删除临时副本。
- `scripts/adapt_skills_for_dsh.py`：把插件 skills 改写为 DSH 工具前缀与 DSH 说明头，生成
  `dsh/agent-presets/poe-bd/skills/`；幂等运行，`--check` 同时校验缺失/陈旧文件、裸工具名、
  旧前缀和重复前缀。
- `scripts/install_dsh_preset.py`：以 staging + 可恢复 backup 安装、卸载或诊断 DSH `poe-bd`
  会话 preset 到 `${DSH_HOME}/.agent-presets/poe-bd/`；不触碰宿主组合与随发行版 preset。
- `dsh/`：DeepSeek Harness 适配层——`poe-bd.mcp.cordis.yml`（四个域 MCP server 的
  `dsh-mcp-client` 注册 patch）、`agent-presets/poe-bd/`（preset 模板：组合 + 改写 skills）和
  `README.md`（中文说明）。
- `data/mature_build_learning/seed_cases.json`：只保存 sanitized seed mature cases。
- `data/reference_builds.json`：只保存校准摘要，不是模板。

## 阶段文档

- `docs/phases/00_cleanup.md`：Phase 0 cleanup 和文档结构。
- `docs/phases/01_judge_eval.md`：deterministic judge 和 modelability matrix。
- `docs/phases/02_graph_cold.md`：physical graph cold start 和 official ID mapping。
- `docs/phases/03_graph_tools.md`：graph backend 和 typed graph tools。
- `docs/phases/04_research_memory.md`：Researcher extraction 进入 semantic graph 和 memory。
- `docs/phases/05_generation.md`：Agent 主导的 BD 生成原型、Judge 和人工验收。
- `docs/phases/06_build_export.md`：官方 `.build` export。
- `docs/phases/07_critic_loop.md`：同 Family/同等级对照学习循环与轻量自进化 Memory。
- `docs/phases/09_scale_productization.md`：scale、revalidation 和后续 productization。

## 变更审查 Checklist

任何涉及代码、工具或知识合同的变更在合并前，按以下六维做一轮完整审查，禁止逐轮追加维度：

- 正确性：改动逻辑、恢复/回滚语义、边界分支（含失败路径）逐行核验。
- 实证：涉及数据/事实的断言（语料内容、引擎规则、数据源结构）必须先查数据源证实，禁止按
  名称/底座做表层推断（反例：把 PoE2 Historic jewels 误判为 PoE1 遗留）。
- 表述覆盖：全仓 grep 同源表述（docstring、note、skill、docs、BUILD_ADVICE 等持久文本），
  不限于已知位置。
- 消费方清单：新增工具/字段/枚举时，grep 所有消费方（manifest.json、bootstrap、打包脚本、
  测试断言、文档工具表）；manifest.json tools 清单必须与工具总数一致。
- 验证矩阵：每个改动文件明确由哪个测试档覆盖（quick / noncompute / compute / full）；
  不存在"改了个没人测的文件"；Lua bridge 改动合并前必须手动跑 compute 档并覆盖新路径。
- 边界声明：明确本轮交付的能力边界（如"能力闭环 vs 内容/数据闭环"）、运行期操作提示
  （MCP 重启、发布时统一更新）。

## 编辑政策

- 优先使用聚焦模块和既有模式。
- 手工编辑使用 `apply_patch`。
- 除非用户明确要求，否则不要 revert 用户改动。
- 不要新增长篇历史规划文档。阶段细节更新对应的 `docs/phases/*.md`。
