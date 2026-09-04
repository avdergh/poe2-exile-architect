---
name: poe-bd-create
description: Use when the user asks for a Path of Exile 2 build, starter build, endgame build, bossing build, mapping build, class build, skill build, or build recommendation.
---

# /poe-bd-create

## 当前功能

这是一个 Agent 主导的 PoE2 构筑创建入口。你的任务是理解用户想要什么，仅在交付方式未说明时
按“用户交互”一节追问一次，然后查询项目
提供的资料和计算工具，设计候选构筑，并把结果整理成可人工验收的安全摘要。

普通用户只应该看到这一项自然语言交付问题、构筑摘要和验收结论。不要让普通用户阅读或填写 JSON。

默认模式必须渐进查询
`query_research_memory(response_profile="create_compact")`。每次首查都会建立新的 bounded retrieval
session；必须沿唯一 `retrieval.nextCursor` 连续读取到 `complete=true`，保存该 session 每一页的新
`dedupeQueryRef`。命中时锁定一条 `(selectedKnowledgeScope, selectedSourceCaseRef)` 作为
Create 授权通道，后续权威深读不得跨 scope/case 拼接；但还必须读取
`sourceCaseLane.familyAvailable`，对其余案例按覆盖度最多再选 2 条，分别完成独立紧凑查询并把全部
分页回执写入 `comparisonDedupeQueryRefs`。比较案例只用于交叉核对共识、差异和失败条件，不能混入
授权通道或 premise resolution。读完案例后必须调用
`construct_research_execution_contract`，按 `caseProfiles` 选择与用户目标最一致的设计案例，并对
合同里的每个 package 给出有证据的决定。跨案例机制允许采用，但必须提交完整
`crossCaseMechanismPlan`；只摘取单个增益、没有配套技能/装备/天赋/资源方案或验证退出条件的拼接
一律拒绝。确认精确 Family 后调用
`query_public_learning_memory` 读取公开种子与本地追加的跨案例经验。明确记录哪些 Research 结论
被采用、保留为注意事项或拒绝；Learning lesson 只作为待验证的设计提醒。Create 必须优先阅读
紧凑结果中的 `criticalPremiseDigest`；不能只记住正向组件而丢失条件、失败场景和验证任务。
`buildPatterns` 以 typed `confidenceTier` 和 `semanticScopeReview` 为范围权威；
`legacy_unattested` 只能作为需重新验证的旧观察，不能凭自然语言中的“常见/通常”等措辞提高权重。用户
显式使用 `--no-memory` 时跳过 Research 与 Learning Memory；静态语料、图、机制、生命周期、
PoB、计算和 Judge 工具仍正常使用。不要为无记忆模式创建另一套 skill 或另一套 MCP 工具。

Judge 反馈默认是硬门槛模式。除非用户在本次请求中明确写出“严格模式”或 `--strict-judge`，否则
`inspect_generation_preflight`、`inspect_generation_checkpoint`、`verify_lifecycle_stage` 和
`evaluate_generation_candidate` 一律使用 `strict_mode=false`。该模式仍运行完整 PoB/Judge，
但只返回确定性硬失败、是否合法、快照绑定和事实诊断；不要补写、猜测或从其他字段反推出评分、
质量档位、playability/quality warning、reward 或主观 caveat。用户明确要求严格模式时，上述
调用统一传 `strict_mode=true`；第一次正式 Judge 后同一 run 不得切换模式。

**构筑真值优先级：**游戏内机制与当前规则、Family Research、当前 Graph/corpus、明确的实战或
外部机制证据决定 BD 身份、技能结构和可执行性；PoB 可建模性只提示工具覆盖了哪些数值证据。
不得因为 PoB 无法计算触发率、重叠、轮转、来源技能或恢复层，就拒绝/替换 Family、核心机制，
或把合法的 meta host + payload 拆成自施法代理。未建模时保留游戏内正确结构，用 Research/当前
机制/实战验证缺失部分，并收窄 DPS、吞吐与续航等数值结论；PoB 提示本身不是合法性、质量或
`deliveryStatus` 的否决条件。

当输入是 `referenceBlind=true` 的 `BlindCreatePacket` 时，进入对照学习盲测模式：不询问任何
交互问题，直接按 [references/blind-mode.md](references/blind-mode.md) 执行
（Research 查询必须绑定活动 campaign/claim 并由服务端强制 global-only；另查询
`query_learning_memory`、提交 `submit_learning_create_result`）。Blind 或其他自动 Create 不执行面向
用户的导出，也不上传 poe.ninja；只保存内部 artifact 并进入 Compare。

## 用户交互

本工具专注终局 BD 生成（目标等级通常 80+，覆盖从进图到巅峰的内容），不提供全链路开荒成长
流程。普通 Create 直接生成用户请求的目标等级单阶段 BD。

普通交互 Create 开始时只确认交付方式。用户尚未说明时，只问下面这一题，不得同时追问职业、预算、
阶段、偏好或其他构筑字段：

> ① 仅生成本地 PoB 文件  
> ② 本地文件之外，再生成 poe.ninja 分享链接

用户已经明确“仅本地”或“同时生成 poe.ninja 分享链接”时不得重复询问。其余需求不完整时根据用户
原话、当前上下文和终局单阶段默认值做合理假设，并在最终摘要披露；不得为了补齐字段再开启第二轮
问题。即使没有任何构筑参数，也按默认终局单阶段目标自主选择方向，不追加构筑问题。Blind/自动
Create 不询问，也不执行用户交付导出。

## 生命周期定位

终局 BD 可覆盖不同升华、技能、天赋、装备、防御与资源方案；跨内容硬锁是基础职业，不能换职业。
普通单阶段请求只覆盖当前阶段，但职业选择和转型门槛仍要考虑用户明确提出的后期目标。

## 工作流程

1. 将用户需求整理成结构化需求摘要。
2. 需求足够后，调用插件 MCP 的 `start_generation_run`，为本次请求创建独立运行状态和一次性
   凭据。普通模式传 `memory_mode="memory_assisted"`；用户使用 `--no-memory` 时传
   `memory_mode="no_memory"`。不要搜索仓库、猜测工作目录或运行 `scripts/create_build.py`；发布
   插件已经自带这个入口。若工具确实未注册，停止并报告插件安装不完整，不能降级成文字 BD。
3. 先实际调用 MCP 的 `get_freshness_report`。调用成功说明 PoE2 MCP 可用；不能因为没有在界面中
   看到某个工具分组、没有搜索到工具说明或没有先找到 Python 函数，就声称 MCP 不可用。
4. 按下面的 MCP 工具清单查询资料，基于查询结果设计候选构筑方向，不要临时猜工具名。普通模式
    中，`build_advice` 只提供规划启发；补丁敏感事实以当前 pinned PoB、physical graph 和
    current corpus 为准。
   按以下顺序使用研究记忆：
   - 先用 `graph_tool_query(tool_name="search_graph_components", ...)` 发现候选，再用
     `graph_tool_query(tool_name="resolve_graph_component", ...)` 确认用户指定的职业/升华 stable key；
     把搜索结果中的 `resolverPayload` 原样传给 resolver，模糊候选不能当作已确认 key。升华是
     Family 发现入口：尚未选定 Family 前不得由 Agent 猜主技能再反查 Family。用户明确指定技能时
     另解析其 stable key，只作为 `related_skill_key` 的匹配条件。
     第一次必须使用用户原始职业/升华名称。若组件未唯一解析（missing/ambiguous），或用该身份完成的 Family discovery
     返回 `no_family`，只允许追加一次官方英文名称 fallback：联网查 GGG 官方页面/官方数据中的英文
     职业或升华名，再用英文名重新 search→resolve→Family discovery。不要维护本地语言映射表，
     不要循环尝试多个翻译，也不要把搜索引擎摘要当稳定键。
   - Create 用途的查询必须传 `response_profile="create_compact"`。它只返回一条来源一致 lane 中可
     授权 Create 的 deep records、对应 index/premise/critical digest，并按最终 UTF-8 JSON
     65,536 bytes 分页。每次首查生成不可复用的 retrieval session；`complete=false` 时只能把该页
     `retrieval.nextCursor` 原样传给下一次 `continuation_cursor`，不能跳页、重排或跨 session 合并。
     单项过大返回 `memory_item_too_large`，不得把截断内容当完整知识。`response_profile="full"` 只可
     用于 Research 比较或 ToolReference，不产生新版 Create 授权 receipt。
   - Family discovery 首次查询使用 `detail_level="family"`，传当前 `class_key`、`ascendancy_key`、
     版本字段；用户明确指定技能时可再传 `related_skill_key`。它同时匹配现有
     `primarySkillKeys/secondarySkillKeys`。检查 `familyDiscovery.outcome`、`buildFamilies` 中每个 Family 的
     `primarySkillKeys`、`recordKindCounts`、`deepResearchRecords` 与 `createEligibility`：
     `known_family_not_authorized` 表示 Family 已知但需
     revalidation，不得误报 `no_family`；只有数据库确无 Family 才是 `no_family`。选定 Family 后，
     后续授权查询统一传 `build_family_keys=[selectedFamilyKey]`，不能用 Agent 猜出的主技能重新定位。
     Family discovery 不传 `primary_skill_key`；该字段只属于已知身份的精确旧查询兼容路径。
     普通辅助、utility 和副技能由命中 Family/记录返回后再解析，不作为 Family 发现的必需 AND。
     lane-specific Create 不把 pattern、semantic edge 或 legacy fragment 当权威。首查完成全部页后，
     记录返回的 `selectedKnowledgeScope` 与 `selectedSourceCaseRef`。
     读取该精确 Family 查询返回的 `sourceCaseLane.familyAvailable`。自动选中的最高覆盖案例只是
     初始 lane，不自动成为最终设计案例；再按 `eligibleRecordKindCount`、`eligibleRecordCount` 从高到低选择最多 2 条其他案例
     （不足 2 条则全部选择），对每条显式传对应 `knowledge_scope` 和 `source_case_ref`，用相同
     Family、补丁、天赋树版本和 `detail_level="summary"` 新开 `create_compact` 查询并读完整 page
     chain。把这些页的回执只写入 `researchMemoryUse.comparisonDedupeQueryRefs` 和对应
     `query_research_memory` ToolReference；ToolReference summary 必须说明该案例是佐证、补充还是与
     授权 lane 冲突，以及它如何改变设计或验证计划。普通 Create 在数据库存在 2 个案例时必须读
     2/2；存在 3 个及以上时至少读 3 个总案例。Blind Create 保持 claim 绑定的单案例隔离，不做此
     对照。普通 Create 的每次 Research 首查传本次 `start_generation_run` 的 `run_id` 作为
     `run_ref`；continuation 只传服务端 cursor。`run_ref` 只关联同一生成任务，不改变 scope/case
     权威。
     读完初始 lane 与对照 lane 后调用
     `construct_research_execution_contract(authoritative_dedupe_query_refs,
     comparison_dedupe_query_refs, build_family_key, selected_knowledge_scope,
     selected_source_case_ref, game_patch, passive_tree_version)`。比较返回的 `caseProfiles`，从职业壳、
     核心技能职责、防御层、资源机制、必要装备、天赋/珠宝状态、失败条件与证据覆盖/验证计划说明为什么
     某个案例最匹配用户目标。若选择的 `selectedDesignCaseRef` 不是初始 lane，必须显式重查该 case，
     将它变成最终 `researchMemoryUse.selectedSourceCaseRef` 的授权 lane，并把原 lane 移入对照引用，
     然后重新构造合同；不得让计划选择与授权 lane 不一致。
     对最终采用的 discovery 调用
     `record_generation_family_discovery(run_id, run_token, family_discovery_ref,
     selected_family_key)`；`family_discovery_ref` 必须是已读到 `retrieval.complete=true` 的终页
     `dedupeQueryRef`，不能传首个分页或中间页；确实无 Family 时 `selected_family_key=""`。memory-assisted draft/Judge
     没有该 run 绑定会失败；discovery 已返回 authorized Family 时不得再声明
     `retrievalOutcome="no_matching_memory"`。
   - 选定 Family 后，先读取 `familyRecordCoverage.requiredDeepReadRecordIds` 中的全部记录；该集合
     由现有支持包、非 optional 装备职责、资源机制、失败条件和核心机制代表记录派生，遗漏任何一项
     都会使 `validate_generation_draft` 返回 `research_required_records_not_read`。之后若具体设计缺口
     尚未关闭，再使用
     `build_family_keys=[...]`、已选 `knowledge_scope`、`source_case_ref` 和 `record_kinds=[...]` 做定向
     摘要查询，再对解决当前设计所需的 `recordIds` 使用
     `detail_level="record", response_profile="create_compact"`。每次新查询仍需读完自己的完整 page
     chain，且选中 lane 必须与最终 `researchMemoryUse` 一致。优先按维度
     渐进深读，不要用一次无差别宽查代替取舍；但不得因为上下文预算放弃关键记录。
   - 最终合同的 `packages` 是需要作决定的研究包，不是自动装配指令。对每个
     `reviewRequiredPackageIds` 填写 `researchExecutionPlan.packageDecisions`：
     `adopted / tested_and_rejected / not_applicable / retained_as_alternative`。每项分别说明机制理由、
     在最终 BD 中的应用，以及实际验证证据引用；“更强”“更协同”“常见搭配”等泛化表述不构成
     理由。授权 lane 的 package 不能只保留为 alternative。所有验证证据必须是候选
     `toolReferences.queryRef`、本轮 Research receipt、contract/package/record ref 中真实存在的引用；
     自造 checkpoint、机制或 PoB 引用会被 Draft validation 拒绝。`adopted` 与
     `tested_and_rejected` 还必须至少引用一条 Research/合同之外的图、机制或 PoB/计算工具证据；
     只引用来源 package 不能证明它适合当前构筑。每个跨案例计划也必须满足同一外部证据要求。
     `adopted` 只表示完整保留 build-defining skill/support package；只复用其中组件时，package 使用
     `tested_and_rejected`，保留组件另以 Blueprint claim 和 insight `caveated` 记录，不得夸大为整包采用。
   - 对照案例的 package 若 `adopted`，必须绑定一个 `crossCaseMechanismPlan`。计划至少包含来源
     case/package、最终设计案例中的配套 package、机制闭环理由、兼容性理由、机会成本、具体实现
     步骤、冲突处理、至少两项验证、失败退出条件与证据引用。允许把确实兼容的机制跨案例组合成
     新的完整方案；禁止只拿伤害词缀、单个辅助、暗金或恢复手段而不承担它在来源案例中的必要配套。
     所有授权 package 必须先完成 record 深读；任何对照 package 在 `adopted` 前也必须以该 case 的
     `detail_level="record"` 完整深读。深读完成后再次调用合同工具取得最终 contract view（同一
     lanes/版本下 `contractRef` 稳定，但 deep-read coverage 会更新）。无法证明完整兼容时使用
     `retained_as_alternative` 或 `tested_and_rejected`。
   - 研究停止条件是“Family 已发现、要求的多案例对照已完成、授权 lane 的必读记录已深读、
     Research Execution Contract 的全部 package 已决定、跨案例采用计划完整、当前具体证据缺口已
     关闭”，不设固定查询轮数。
     新发现缺口才追加定向查询；不要为完成形式轮数重复同一 query/receipt。
   - 精确 Family 无命中、有效深度记录过少，或候选在资源、防御、轮转、机制链等具体设计维度仍有
     缺口时，执行第二次定向召回：同主技能跨升华查询只传主技能 key；机制缺口查询使用
     `include_transferable=true` 和对应的 canonical `research_axes`。full Research 结果中的
     transferable 事实只能作 ToolReference；不要把它们写成当前 Family 的 lane 权威或加入
     Create-authorizing `researchMemoryUse`。
   - Family 知识始终优先于公用/跨流派知识（scopeWeight 分层与 transferable 通道以 AGENTS.md 为准）。
   - 深读 `recordKind`、`conditions`、`failureConditions`、`criticalPremiseDigest` 和
     `typedPayload`；完整 page chain 才代表完整紧凑响应。具体歧义需要更多正文时，在相同 lane
     使用 `detail_level="record"` 新开并读完一个 session。将 `supportPackages` 作为归属明确的辅助候选并交给当前版本 PoB/
     `optimize_supports` 验证；将 `gearResponsibilities` 转成装备职责而不是照抄来源物品；将
     `ascendancyResponsibilities` 用作升华节点取舍依据；将 `resourceMechanisms` 和轮转/机制链
     转成资源预算、失效条件与 Judge 分状态检查。新字段提供设计证据，不授权程序自动组装 BD。
   - 深读记录的 `component_keys` 中的 `unique:` / `item_base:` 组件是 family 声明的暗金/底材
     候选：用 `get_unique` 读全文核对机制，再按流程用 `equip_item` / `equip_jewel` 实测 delta，
     不能因为默认走稀有装工具链就忽略它们。对 `gear_synergy` 的
     `typedPayload.componentMentions`，`role=unique_enabler` 且同组件 `gearResponsibilities` 的
     `responsibilityType` 不是 `optional_upgrade` 或 `budget_substitute` 时，视为 Family 组成件并
     默认保留。只有用户明确排除、当前版本不可用、当前静态事实否定其机制，或围绕该组件做一次
     配套重规划后仍无法修复合法性/资源闭环失败时才能拒绝。`optional_upgrade`、
     `budget_substitute` 及普通 scaling/defense/utility 候选只要求评估；价格不能成为拒绝理由。
     一个记录包含多个暗金时，在现有 `researchMemoryUse.insightDecisions` 中按 stable key 为每个
     组件分别记录决定，不创建合并决定。family 未提及暗金不代表"不需要"，只能说明该 family
     没有把暗金作为关键组件；仍应主动评估一次（见第 5 步的 unique 评估轮）。
   - `case_observation` 只可作为当前候选的待验证假设；只有更高证据等级才能支持跨案例的一般性
     结论。采用涉及暗金、天赋、触发、转换或资源交互的结论前，必须用当前静态事实或机制工具
     复核其前提；resolver 成功只证明组件存在，不证明机制解释正确。矛盾项应标为 `rejected`，
     不能仅保留 caveat 后继续当作设计依据。所有记忆仍需经图、PoB 和 Judge 验证合法性与数值。
   - 在 `researchMemoryUse` 中记录完整 page chain 的全部查询引用、命中的 Family/deep record、
     `selectedKnowledgeScope`、`selectedSourceCaseRef`，以及每条被采用、保留或拒绝的结论如何影响
     候选；不得把其他 lane 的 pattern/edge/fragment 注册成采用来源。若定向查询没有命中，显式使用
     `retrievalOutcome="no_matching_memory"` 和 `noMatchReason`，不能伪造引用。目标等级低于 70
     或 Research 无 Family 命中时，允许 Agent 联网研究与模型知识作为设计主源；≥70 且命中
     Family 时仍以 Family 为身份与设计权威，联网证据只作补充、结论不替换 Family 结论。
   - 普通 Create 确认精确 `buildFamilyKey`、目标等级和当前版本后，调用
     `query_public_learning_memory(family_key, target_level, version_context, dimensions=None,
     limit=8)`。同时阅读 lesson、`correctionsAndDoNotRepeat` 和版本不匹配的 stale 提示；lesson
     必须再经当前图、机制、PoB 和 Judge 验证。普通 Create 不填写 Phase 7 专用的
     `learningMemoryUse`，只在安全摘要的来源/注意事项中引用实际采用的 lesson ID。
   - `get_meta_builds` / `get_meta_archetype_trends` 返回 unavailable 时不阻塞 Create，也不把空结果
     解释为“该流派不存在”。先复核当前 PoB、corpus、Graph 与 Research；仍有机制或样本缺口时，
     再查官方补丁/官方数据/PoE2 Wiki，最后查当前赛季 poe.ninja、pobb.in 等样本，并用
     `import_build` / 当前 PoB 复核。联网证据只写入 `toolReferences`、`rationaleSummary`、
     `unresolvedCaveats` 或 `toolFeedbackEvents`；它不能进入 premise `resolutionRefs`，也不能替换
     目标等级 ≥70 且已命中 Family 的身份权威。
   `--no-memory` 模式不得调用 Research 或 Learning Memory，候选里的 `memoryReferences` 必须为空、
   `researchMemoryUse` 必须省略，`researchMemoryRef` 使用 `disabled:no_memory_baseline`。
   对照学习盲测模式的每次 Research 首查必须传
   `run_ref=<campaignId>, claim_ref=<claimId>`；`blind_global_only` 不是授权依据，服务端按 claim 验证活动 Blind Create
   claim 并把 scope 强制为 `global_seed`，调用方不得用 `local_user` 或无绑定 receipt。然后按
   [blind-mode.md](references/blind-mode.md) 调用
   `query_learning_memory`（claim 绑定、revision 处理与 lesson 决策见该文件）。
   - Research 合同与 package 决策完成后，读取
     [references/mechanism-blueprint.md](references/mechanism-blueprint.md)，由模型先生成一份自由形式、
     深度且可证伪的机制蓝图。正文不使用固定模板，但必须结合最终授权 Research、对照结论与当前
     图/机制/语料，解释当前 BD 实际相关的输出传递、清图、Boss、保命、生命/魔力/能盾恢复、Spirit、
     操作轮转、成立条件、失败窗口与验证任务；不得用模型常识补写证据缺口。重要结论用
     `grounded / inferred / hypothesis / unknown / rejected` 薄索引回连真实证据，八个基础覆盖方向
     必须显式标为 covered/not_applicable/unknown。
   - 调用 `validate_generation_blueprint(run_id, run_token, blueprint_draft)`。只有返回 accepted 后才可
     开始 `new_build`、技能/天赋变更、暗金评估、`plan_gear`、craft 或装备写入。把返回的
     `blueprintRef`、同一份 `mechanismBlueprint` 和匹配 ToolReference 写入最终 candidate。后续若新
     证据改变核心输出、防御、资源或轮转模型，先修订并重新验证蓝图；不得让装备选择静默引入蓝图
     外的新机制。蓝图是知识综合层，不替代装备阶段继续读取原始 Research 与当前事实。
5. 使用 `apply_build_mutation_batch(batch_kind=..., ...)` 把 Agent 已经决定的机械操作按职能拆成
   小事务：`bootstrap` 只设置 `new_build`（可选首项）、职业和等级；普通宝石承担主输出时，
   `mechanism_shell` 只设置该唯一主技能和显式武器槽，所有副技能都必须等来源核对后再通过
   `skill_loadout` 添加。主输出由装备、升华或被动授予时跳过 `mechanism_shell`，先用
   `required_gear`/独立 `equip_item`/`passive_delta` 落实武器和来源提供者，再读取真实来源组并用
   `set_skill_group_state(make_main=true, ...)` 设为主技能；不得创建普通宝石代理。随后按需使用
   `skill_loadout`、`passive_delta`、
   `required_gear`、`ordinary_gear` 和单次 `config`。不得把整个 BD 混进一个批次。只有以
   `new_build` 开始的 bootstrap 可省略 `expected_state_hash`；其余事务必须使用上一批
   `outputStateHash`。装备和珠宝必须传显式 slot/socket。批次不做搜索或优化，也不能包含需要
   新 skill-group fingerprint 才能决定的编辑。失败只回滚当前职能事务；仅当
   `rolledBack=true` 才继续；`recoveryRequired=true` 后服务端会拒绝普通事务，只能以
   `new_build` bootstrap 显式恢复。批次槽位白名单以 `server/compute/mutation_batch.py` 为准，
   实测要点：只有普通宝石主输出路径调用 `mechanism_shell`，该批次必须恰含一次
   `set_main_skill` 且只能初始化一次（所有副技能后续用 `skill_loadout`）；来源主输出路径不得调用
   该批次。`required_gear` 只允许武器槽（Weapon 1/2 及 Swap）；`ordinary_gear`
   允许武器槽+Helmet/Body Armour/Gloves/Boots/Belt/Amulet/Ring 1/2/Flask 1/2/Charm 1-3；
   **箭袋（Quiver）不在任何批次白名单**，引擎把它映射为 `Weapon 2` 槽（completeness 层叫
   `Quiver`），只能走独立 `equip_item` 且不能显式传 `slot="Quiver"`（省略 slot 自动识别）。
   独立 compute/equip 工具（`equip_item`、`remove_skill_group`、`replace_skill_group`、
   `set_config`、`apply_combat_profile` 等）与批次共享同一活动构筑、同样会改变 state hash，
   之后第一批次必须用该工具返回的最新 hash（`build_state_conflict` 提示 actualStateHash）；
   `apply_combat_profile` 等 config 变更会改变 semantic hash，必须在最终状态绑定的审计、checkpoint
   与 Draft 之前完成，读取前始终以工具返回的最新 hash 为准。
   **任何 `skill_loadout` 之前必须完成一次技能来源核对**：
   - 先装备组件级 `researchMemoryUse.insightDecisions` 与最终蓝图都确认 `adopted` 的非可选
     `unique_enabler`，并分配会授予技能的必要升华/被动；不能把 adopted package 中的每个组件都
     自动视为采用。来源件仍需先用当前静态事实核对全文并实测，不能因为要求先装备就跳过验证；
   - 立即调用 `list_skill_groups`，以实际 `source`、`slot`、主动技能和 enabled 状态确认装备、升华、
     被动已经提供了哪些职责；不得仅凭 Research 中出现过技能名就假设来源；
   - 已有真实来源组满足清图、Boss、setup/payoff、persistent 或 utility 职责时直接使用该组；若
     蓝图选定的来源组当前 disabled，应使用新鲜 fingerprint 先启用，而不是把它视为缺失。不得
     再添加同职责的普通技能组，也不得为了通过辅助审计、Spirit 利用率或工具可编辑性而禁用
     正确来源并制造普通代理组；
   - 同一职责存在多个来源时，基于技能等级、辅助能力、资源成本、武器状态和实际用途明确选择；
     未证明具有不同职责或不同武器状态时不得静默同时保留；
   - 只有来源核对后仍缺失的职责才进入 `skill_loadout`。之后任何已知会授予或移除技能的装备、
     升华或被动发生变化，或来源物品因 Rune/词条操作被重新装备时，必须重新读取并核对来源；普通
     数值换装和未触及来源物品的 Rune 变化不额外触发来源核对。不得跨换装沿用旧 group index、
     fingerprint 或审计结论。
    然后把候选方向落实成当前请求所需的完整活动构筑。至少实际
    设置职业、升华、等级、主技能和辅助技能、其他技能组、装备、天赋和
    战斗配置，并检查属性、抗性、Spirit 与资源状态。不能拿只有职业和主技能的空骨架去验收。
    `noSupports=false` 的 `Tree:*` 与 `Item:*` 真实来源技能可以安装辅助，槽位容量由最终角色等级对应
    的技能基础等级决定。
    单阶段 Create 必须先 `set_level(<最终目标等级>)`，再分配授予技能的升华/被动节点，最后读取
    `list_skill_groups` 的新鲜 fingerprint 并调用 `configure_source_skill_supports`；配置后禁止再次
    调用 `set_level`。物品来源技能必须在机制装备、Rune 和装备词条最终确定后再配置；主输出来自
    source group 时必须直接配置真实来源组，不得复制普通 Ruzhan/Kelari 或其他技能组作为代理。
    之后若重新装备来源物品，旧 group index、fingerprint、辅助和审计全部失效，必须重新读取并配置，
    不建设跨换装自动恢复。
    主动形成客观可执行的输出技能包：说明主技能如何清图，稀有怪/Boss 由主技能、独立单体技能或
    setup/payoff 组合中的哪一部分处理，并检查当前等级已可获得的精魂/保留技能能否提供伤害、
    清图、资源或防御协同。资料没有主动提到精魂技能时，不能自动理解成“不需要”；应继续按主技能
    和职业定向搜索常见精魂/保留搭配，再用 corpus、机制和 PoB 核对可用等级、Spirit 需求和实际
    作用。Spirit 是稀缺的持久效果预算，剩余值通常不能按比例兑换收益，终局大量闲置大概率就是
    机会成本浪费；因此应优先把它分配给与输出、防御、资源或轮转真正协同的持久机制，而不是为过
    门槛塞无关填充。使用率不高于 80% 时必须执行一次机会成本检查：定向查询并实测与蓝图职责一致
    的持续技能，有明确正收益且不破坏核心机制时采用；没有有价值或可容纳的选项时保留余量并说明
    理由。利用率本身不是游戏合法性，也不得为了达到比例添加无关技能。
   当前 Create 禁止调用 `optimize_build`，也禁止用 `optimize_passives(reset=true, points=0)` 做
   全局树重排；允许针对明确缺口或高影响质量探索使用局部 `optimize_supports`、单槽装备工具
   以及手工/定向天赋节点。
   `search_passives`、`search_mods` 和 `search_items` 使用精确 query；不得设置固定候选条数
   上限，也不得把默认返回量误解为最多只能查看这些结果。从候选中选定对象后使用
   `get_passive`、`get_item` 或对应精确详情工具；必要时扩大结果或调整查询，不能因速度放弃
   可能决定构筑质量的候选。
   Family 明确指定或按上述 `unique_enabler` 职责派生的组成暗金/暗金珠宝，必须在普通黄装前逐项
   读取、实测并锁定；
   每项都记录 `adopted / caveated / rejected`；当前版本不可用时写 `rejected`，并在
   summary/application 中明确 unavailable 原因。黄装围绕已经锁定的机制件补属性、Spirit、抗性
   和防御。先快速形成机制完整、合法且资源闭环的基础版本，再固定执行一次主动质量收尾：比较高影响
   武器、辅助组合、天赋路径、珠宝、符文/灵魂核心和战斗配置。Judge、checkpoint 或 lifecycle
   报警不是调用 `plan_gear`、`craft_item`、`optimize_item`、`optimize_jewel`、
   `optimize_supports` 或局部 `optimize_passives` 的前提；只要探索可能显著改善伤害、防御、
   续航、操作或装备可行性即可。只复用同一 state hash、同一目标和同一参数的完全相同结果，
   不限制有新假设、新目标或新状态的比较。终局/巅峰目标可在有诊断价值时调用
   `pinnacle_readiness`；剧情阶段不得被其终局门槛驱动。
   对每个用户可编辑技能组以及 `noSupports=false` 的核心 `Tree:*`/`Item:*` 来源组，都调用一次带 `group_index` 和
   新鲜 fingerprint 的 `optimize_supports`；
   清图/单体、combo、utility、persistent 都以引擎边际结果决定，不要求机械五辅。只有返回的
   `supportAudit.status=passed` 才说明不存在未经处理的正收益空位。真实来源组的最终辅助必须用
   `configure_source_skill_supports(source_group_index, supports, expected_fingerprint,
   expected_state_hash?)` 写入；写入失败、辅助未作用到目标 active effect，或缺少通过的 support audit
   时，`deliveryStatus` 只能是 `candidate`。`noSupports=true` 表示辅助不适用，无需制造审计；其他底层
   不支持的来源必须保留真实技能并记录 modelability caveat，不能复制普通技能绕过。
    质量收尾必须包含一次普通候选暗金评估轮：调用 `relevant_uniques`（按活动主技能 scaling 匹配
    unique 与 unique jewel 候选），并与前面已经处理的 family `unique:` 组件分开记录，用
    `search_uniques`/`get_unique` 读全文核对机制；对确有机制收益的候选用 `equip_item` /
    `equip_jewel` 实测 delta，数值以引擎为准。只有装备方案和实测结果锁定后才调用 `get_prices`，
    价格只写入 ToolReference、注意事项和最终用户价格表，不参与暗金、黄装、符文、药剂或 Family
    的选择。unique/radius jewel（含 Time-Lost）必须位置化评估。Time-Lost 词缀先用
    `search_mods` 取得精确 mod ID，再由 `optimize_jewel(selected_mod_ids=[...])` 合法构造；不得手写
    未验证词缀。已分配槽中的替换用 `evaluate_jewel_socket`，尚未开启的槽统一走下述受保护全槽
    审计；普通 rare jewel 只在 Family 暗金珠宝完成评估后用 `optimize_jewel` 生成。
    Family 必需件全部实测；普通暗金先静态排除武器/机制不兼容项，再最多实测 3 个最高相关候选。
    普通候选暗金换装破坏属性/抗性时，最多围绕该暗金重规划一次配套黄装后决定采用或拒绝，不展开
    分支树。暗金不是稀有装的替代品而是机制件：不要只因为"当前装备稀有装"就跳过评估，也不要
    机械套用不符合机制前提的暗金。
   装备目标必须匹配当前阶段：剧情/开荒使用 `plan_gear(stage="campaign")`，刚进图使用
   `stage="maps_entry"`，终局才使用 `stage="endgame"`。元素抗性仍按阶段合法性补足；非 CI 混沌抗
   默认目标分别是 0%、30%、30%，元素目标分别是 30%、50%、60%，不是所有阶段都强行 75%。
   达到阶段目标后，应把后缀留给技能
   等级、输出、属性、资源、移速或其他实际缺口；只有明确内容需求才覆盖到 75%。
   `scaffold_gear` 只能让中途骨架可计算，所有 `Scaffold ...` 占位物品必须在最终评估前替换。
   最终黄装必须带当前阶段合理的 `Item Level`，底材需求等级不能超过角色等级，词缀必须来自该
   物品等级可用池。不要为了面板分数把剧情角色穿上终局底材或默认 ilvl 82 黄装。
   未给预算时只生成一套 `acquisition_profile="realistic_trade"` 主方案：先锁定机制件
   `locked_slots`，其余槽位最多 5 条关键词缀；提供关键槽低配替代和毕业升级优先级，不生成三套
   独立 PoB。六词缀理论黄装只能写在升级建议中，不能进入推荐主方案。
   未显式写等级的主动宝石会自动使用当前角色可合法装备的最高基础等级；显式等级超过角色需求时
   工具会回滚。最终仍要复读宝石等级。合法性只检查基础宝石等级，装备或天赋的 `+levels` 可以把
   计算等级继续提高，不应为此降低基础宝石等级。
   若候选方向依赖武器切换或武器组天赋：当前 MCP 工具不支持按武器组分别分配天赋与分别评分
   （`alloc_passive` 无 weapon set 参数），只能按单状态评估；单状态 DPS 不能当作双状态强信号，
   输出 caveat「weapon-set 切换机制未按 State_A/State_B 分别验证」（AGENTS 规则：dual-state
   仅 limited reward）。不要为了单状态数字放弃合理的双状态设计；用户明确要求 Boss 切换流时，
   保留设计并说明验证限制。
   **进入护符、额外珠宝和 Rune/Soul Core 精修前，必须完成一次核心可行性检查。**此时应已装备
   当前目标阶段已可获得并采用的机制件、第一版可穿戴装备（机制件与适用黄装），分配基础天赋，
   并先装备当前阶段的基础生命/魔力药剂。对当前可编辑、可建模的核心输出放入可计算的临时辅助；
   不可写来源保留真实来源组、intended supports 与工具缺口，使用当前机制、Research 或实战证据
   继续检查，不得为获得临时面板创建普通代理。检查只用
   现有 `list_skill_groups`、`get_build_stats`、`get_defenses`、等级/机制资料和必要的精确机制查询，
   不新增一套评分器，也不把尚可由普通黄装补齐的缺口误判成机制失败：
   - 复读每个核心职责的真实技能来源，确认没有未解释的同职责重复，武器和主动技能兼容；
   - 检查当前属性、装备需求、抗性和未封顶 Spirit 账本。当前已装备物品或已启用宝石的属性需求
     不足属于确定性非法：可以保留 BD 方向，但必须先修黄装，不能进入下一精修阶段。尚未采用的
     未来换装预算和阶段抗性目标可以继续作为下一轮装备目标；来源冲突、武器不兼容或超额保留等
     确定性矛盾同样必须先修；
   - 对每个承担清图、Boss 或 setup/payoff 的核心技能组，先重新读取 `list_skill_groups`，用新鲜
     fingerprint 通过 `set_skill_group_state(make_main=true, ...)` 临时选为计算组，再读取该组的
     `ManaCost`、`Speed` 与资源统计；每次切换后都要使用新状态重新读取，并在结束时恢复原主组，
     不得把当前主组的消耗数据套到其他技能；
   - 对连续使用的输出技能，核对 Mana/Life 的每次固定、每次百分比、每秒固定和每秒百分比成本；
     固定与百分比单次成本合并检查，`*LeechGainRate` 已含 On-Hit、不得再叠加 `*OnHitRate`。未建模
     Mana 恢复不能覆盖确定性 Life 失败。对铺弹、引爆、蓄力、
     走位等 setup/payoff 组合按一次完整循环的动作、成本和恢复窗口判断。无法可靠取得循环时长或
     恢复覆盖时只标为 `unknown` 并保留验证任务，不得用持续按键模型直接判死，也不得伪造通过；
     当前 checkpoint/lifecycle 尚不能接收受检的循环续航回执，因此该缺口在最终交付中仍保持
     `deliveryStatus=candidate`；PoB 外机制或实战证据用于说明玩法边界，不能在本轮把状态升级为
     `recommended`，直到后续提供可信的 setup/payoff 轮转模型；
   - 读取 Physical/Fire/Cold/Lightning/Chaos `MaximumHitTaken` 并写入候选诊断。用户未给具体一击线
     目标时只报告事实；某类 Max Hit 无法读取时明确标为 `unknown`，不得把任意阈值变成硬门槛；
   - 只有已经证实的核心机制失败才暂停后续精修并回到技能、资源或必要装备方案。尚未采用的未来
     换装属性预算、阶段抗性目标和未建模但仍有验证路径的机制继续推进，但必须保留明确的修复目标
     或 caveat。
6. 补齐真实装备系统，而不是只填十个基础装备槽：
   - 实际装备当前阶段生命药剂和魔力药剂。Family 明确指定暗金药剂时直接装备并验证；普通药剂
     使用 `optimize_flask(slot, base?, ilvl, strategy)`，根据 Research 职责选择
     `recovery / sustain / instant`，证据不足时默认 `recovery`。它生成合法 Magic 药剂（最多
     1 前缀/1 后缀）；不得用普通装备的 Rare 3/3 优化链处理 Flask；
   - 护符容量以最终 PoB `CharmLimit` 为准并封顶 3；腰带缺少 `Charm Slots` 是 unknown，不能按 0。
     90 级 Create 默认把三槽腰带和三个护符作为质量目标；用 `optimize_charm` 生成合法 Magic
     1 前缀/1 后缀方案。Normal Charm 只能进入 `candidate`，不能进入推荐成品；
   - 调用 `list_jewel_sockets`；分配了珠宝孔就必须用 `optimize_jewel` / `equip_jewel` 填入真实珠宝。
     仅目标等级 ≥90 强制执行额外珠宝槽审计；低于 90 级不作为质量门禁，只在机制需要时评估。
     核心与重要支撑天赋完成后，先把不得为珠宝牺牲的精确节点 ID 列为
     `protected_node_ids`，再为下一颗真实候选调用 `evaluate_next_jewel_socket`。该工具比较这颗珠宝的
     全部当前可达槽，只允许当前安全单点叶节点参与等点替换；它不替 Agent 选择珠宝，也不重排天赋
     树。正收益只能用 `apply_next_jewel_socket_decision` 原子应用，随后必须在输出 state 上重新审计，
     直到当前候选无正收益或没有可达槽。`policy_limited/inconclusive` 可继续 Judge，但交付保持
     candidate；不得用成熟案例槽数、固定轮数或最低槽数代替当前 state 回执；
   - 用一次 `plan_item_sockets_batch(slot_socket_counts, goals)` 评估全部可镶嵌装备；`socketed` 结果
     的 item/craftReceiptRef 必须实际 `equip_item`；`partial_no_positive` 表示保留原孔容量、已装入正收益
     Rune 且其余孔无正收益，`no_positive/not_applicable` 才能全部留空。检查以孔容量对比带可信
     craft receipt 的实际 Rune 数；只有 `Rune:` 声明而没有匹配效果/receipt 不算已镶嵌。不要为
     镶嵌重做整件装备，也不要机械套用带 Perfect Essence 和腐化的终局 `craft_item` 结果。
7. 正式最终检查前先固化战斗假设：对终局/Boss 目标调用一次
   `apply_combat_profile(tier=<与用户目标一致>，...开关...)`（或用 `set_config` 传相同 key）
   设置敌方条件并读取返回的 assumed 清单。默认值全开，**只保留构筑实际能产生的假设**：
   `shocked` 需要构筑能施加感电、`cursed` 需要实际配置的诅咒技能、power/frenzy charges 需要
   生成手段、`full_es` 需要 ES 构建——无法产生的就关闭，否则 DPS 会被不可能维持的效果抬高；
   不调用时这些条件全部关闭，对依赖感电/诅咒/充能的 BD 属于下限值，不能当作目标强度。
   把 assumed 清单原样记入本轮 `failureAudit.summary` 与 `toolReferences`；战斗配置属于构筑
   的一部分，后续重试沿用同一假设，不能为通过 Judge 临时切换开关。
   战斗配置稳定后，重新完成最终 Support/Jewel/Socket 状态绑定审计，再调用一次
   `inspect_generation_checkpoint(strict_mode=<本次反馈模式>,
   offense_skill_group_index=<最终Judge目标组>, expected_skill_name=<该组主动技能>)`。纯清图目标使用
   clear group；Boss/均衡目标使用 single-target group，确保续航和 Judge 检查同一技能。它按语义 `build_state_hash` 合并
   completeness、preflight、有界 stats 和 defenses；同一状态重复调用会复用结果。修复其中
   completeness 的硬失败。`Scaffold ...` 占位装备和 rare/magic 黄装缺少 `Item Level` 是两项
   确定性 Create 硬门槛，在 hard-only 下也必须修复；它们会在 Judge 启动前返回
   `attemptConsumed=false`。`createQualityChecklist` 与 `deliveryStatus` 是客观事实，在 hard-only 下也
   始终返回；主观 `qualityAdvisories` 仍只在严格模式出现。逐项处理
   `skillSupportAudit/mechanismDependencies/bootstrapItems/gearAttainability/charmLoadout/
   jewelDecision/itemSockets/sustain`。`qualityRepairPlan` 给出定向修复入口，最多做两轮返工；两轮后仍
   有 failed 项则保持 `candidate`，不得继续包装成成品。新生成且等级 ≥80 的候选若缺少 Flask 1/2、
   使用 Normal Flask 或 Flask 没有可识别词缀，会以 `endgame_flask_loadout_incomplete` 硬失败；
   Unique Flask 合法，至少一条合法词缀的 Magic Flask 合法。Magic Flask 尚未填满 1/1 只产生
   质量 blocker，Create 应主动收尾到 1/1。这个工具不会替你设计
   BD；不能仅因为 Judge 数值高就跳过。黄装必须通过前后缀数量、词缀组排他和词缀物品等级
   检查，不能用理论上不存在的黄装抬高伤害或防御数值。主动宝石超过角色等级需求同样是硬失败。
   攻击类主技能（非法术）还必须检查 checkpoint stats 的 `HitChance`：终局目标低于约 95% 时，
   补充命中来源（装备词缀/天赋/Unique）后再进入正式 Judge，达标情况写入验收摘要。法术技能
   无命中判定，跳过此项并说明原因，不要机械执行。
   Judge/Preflight 还会强制执行两项最终完整度门槛：所有已经分配的天赋树珠宝槽都必须填入珠宝；
   `unspentPoints` 必须为 0。Spirit 只按未封顶账本检查超额保留和一致性；使用率不高于 80% 时
   `createCompletion.spirit.opportunityReviewRequired=true`，Agent 必须完成上述机会成本检查并在候选
   中记录采用结果或保留余量的理由，但不能把低利用率改写成硬失败。
8. 使用 checkpoint 的 `buildSummary` 复读职业、升华、等级和主技能；只有需要完整局部诊断时
   再单独调用 `get_build()`，不要机械重复整份 readback。发现遗留状态或缺项时继续修正。
   Research 深读完成且最终候选摘要形成后，按 `start_generation_run` 返回的完整 camelCase draft
   skeleton 填写 prompt、candidate、versionContext 和 premise decisions，并在首次正式 Judge 前按
   当前机制修订调用一次 `validate_generation_draft(run_id, run_token, agent_output_draft,
   offense_skill_group_index=<最终Judge目标组>, expected_skill_name=<精确主动技能>)`。服务端从最终
   PoB 自动冻结辅助集合、主导命中类型和 Mana/Life 支付域；核心机制改变后重验 Draft，相同状态不得
   重复刷新。该工具不要求 Judge
   receipt、不持久化也不消耗 run；先修复它报告的字段类型、run/request 绑定、premise version、
   application/caveat 与非本轮 deep-read resolution ref，再进入 Judge。Draft 只冻结 Research
   决策结构：`contractRef`、`selectedDesignCaseRef`、每个 package 的 ID/决定/跨案例计划引用，以及
   每个跨案例计划的 ID、来源 case/package 和目标/附加 companion。Judge 后允许依据实际结果更新
   `selectedVariantRationale`、`coherenceSummary`、机制/兼容性/取舍理由、`buildApplication`、验证
   证据、实现/冲突处理/验证步骤与失败退出条件；不得借此改变来源案例、采用/拒绝结论或跨案例
   依赖关系。
9. 修复 checkpoint `preflight.blockingIssues` 后才进入正式 Judge；完全重复的 enabled skill group、
    无合法 host 的普通多主动技能组、重复辅助或 completeness hard failure 不应消耗一次 attempt。
    已知 payload host 与其 socketed active 共组是合法结构，即使 PoB 不能计算触发率也不得拆组；
    host 与 payload 的具体标签兼容性仍须由当前机制/Research 核对，结构放行不等于任意 payload 合法。
    严格模式返回的 advisories 仍由 Agent 判断和记录；默认模式不得重建这些主观建议。
    使用生命周期 gate 时，调参期间继续使用 checkpoint；每个正式 Judge attempt
    最多在其前调用一次活动快照
    `verify_lifecycle_stage(..., detail="compact", strict_mode=<本次反馈模式>,
    offense_skill_group_index=<最终Judge目标组>, expected_skill_name=<精确主动技能>)`。只有该 gate 暴露真实阻断并且构筑 state hash
    已改变，下一正式 attempt 才能再次调用。artifact 保存后另调用且只调用一次
    `verify_lifecycle_stage(..., artifact_id=..., detail="compact", strict_mode=<本次反馈模式>)` 生成可信回执。不要在每次装备、
    天赋或辅助微调后重复跑 lifecycle，也不要为了看完整对象使用 `detail="full"`。
    `endgame_final` 的 required checks 是 `main_skill_socketed/basic_defense_online/sustain_ok`；
    `pob_model_supported/core_threshold_met/upgrade_budget_ready/pinnacle_ready` 只是 advisory。
    required 任一 failed/unknown 时 `deliveryStatus` 只能是 `candidate`。检测到活动构筑中真实存在的
    未建模恢复层时，生命周期可以通过但必须带 `verificationRequired`；这不授权编造恢复吞吐数值，
    仍要用当前机制、Research 或实战证据核验实际轮转。
10. 调用 `evaluate_generation_candidate(run_id, run_token, candidate_id, version_context,
    strict_mode=<本次反馈模式>, offense_skill_group_index=<clear或single-target组>,
    expected_skill_name=<该组实际主动技能>)`。纯清图目标评分 clear group；Boss/均衡目标优先评分
    single-target group。group/name 冲突返回 `selected_skill_conflict` 且不消耗 attempt；不得传
    `Load *` / `Reload *` 内部形态。这个工具
    会捕获当前 PoB 状态，在独立 Judge 引擎中运行正式评估，并把可信结果绑定到本次运行。不要用
    `evaluate_build`、`pinnacle_readiness` 或 Agent 自己整理的分数冒充正式 Judge。
11. 将该工具返回的 `attemptIndex` 及安全 Judge 结论保留。可信 `transientBuildState` 和
    `judgeAdvisoryReport` 已写入本次 receipt，最终 `agent-output.json` 可以省略这两份重复内容；
    helper 会按 attempt index 补全并严格核对。工具
   拒绝空骨架时继续完成构筑；工具返回 Judge 执行错误时保留错误报告，不要自行改写成已评估。
   `trustedEvaluation` 只表示活动快照和 Judge 结果由程序绑定；`versionContextTrusted=false` 表示
   版本上下文仍需与本次 `get_freshness_report` 返回核对，不能借此冒充当前赛季强验证。
12. 对本轮结果做简短失败核验：区分真实构筑失败、PoB/Judge 建模缺口、Judge 选错技能、工具或
    数据缺口、混合问题，或者当前没有实质失败。只保存结论摘要、修改计划和保留的注意事项，
    不保存逐步推理。
    `passed=true` 只表示确定性合法性通过，不等于候选值得推荐。以可信 receipt 的单一
    `deliveryStatus` 为用户措辞权威：`blocked` 不导出；`candidate` 只能称技术候选/待验证方案；
    `recommended` 才能称推荐成品。默认 hard-only 只处理
    `hardFailures` 和确定性诊断；不得把被抑制的主观字段当作空缺后自行补写。仅当本次是用户明确
    请求的严格模式时，才按以下四层处理结果：
    `hardFailures` 是确定性非法；`playabilityFailures` 是合法但存在严重可玩性短板；
    `qualityWarnings` 是未达到推荐质量目标；`modelability` 是 PoB/Judge 能否可靠计算；
    `offenseEvidence` 区分 metric 是否可用、阶段 floor 是否达到和 delivery evidence 是否充分。
    如果存在 `playabilityFailures`、`qualityBand="barely_playable"`、offense/recovery 等与用户
    目标直接相关的维度为 0，或 `offenseEvidence.floorStatus != "met"`，
    必须优先继续修正或核验。重试耗尽后可以交付给人工研究，但只能称为“弱原型/待完善候选”，
    不能称为“推荐方案”“开荒顺畅已验证”或“成品 BD”。
    `scoreApplicability="unavailable"` 表示核心机制当前无法可靠数值验证。不得引用综合分或 DPS
    强度，也不得把工具能力不足说成 BD 非法、质量较差或必须换核；保留该设计并明确需要机制参考或
    实战核验。它本身不降低 `deliveryStatus`，只有真实合法性、资源闭环、装备可行性或玩法证据缺口
    才能降级。
    对“开荒顺畅”请求，还必须检查清图职责、单体/Boss 职责和资源恢复；不能只证明三抗、属性和
    插槽合法就接受。若一个技能同时承担清图与单体，必须有 PoB/机制证据或明确实战 caveat；否则
    应补充独立单体技能/组合，或把结果降级为仅清图方向。
    接近剧情结束或进入异界时，主输出仍只有零到一个辅助技能属于高优先级完整度提醒。调用
    `optimize_supports` 测试阶段合理的组合，或说明少辅助为何是有意设计；它不是合法性硬规则。
    不要用“总蓝量至少是单次耗蓝的固定倍数”删辅助。续航应结合未保留蓝量、使用频率、自动恢复、
    药剂、击回/偷取、Buff/技能效果和实际技能轮转判断。Lifecycle 暴露
    `unmodelled_mana_recovery_requires_verification` 时，只表述为“需验证未建模恢复覆盖”：先用当前
    corpus、Graph、Research 与游戏内机制复核，不足时联网核对当前机制或要求实战验证。PoB 在这里
    只是诊断静态缺口，不能因它未覆盖恢复层而阻断推荐；确认真实缺口时依次调整辅助、天赋、技能、
    装备、护符、镶嵌、药剂和轮转并复验。
    未建模提示本身不能直接写成“会断蓝”，静态缺口和缓冲秒数只作为内部核对线索；确认只有普通
    魔力瓶承担持续缺口且无其他恢复覆盖时仍视为真实失败。联网证据不能把 Research premise 改成
    resolved，缺少本轮 deep-read 解决记录时必须保留为 `caveated`。
     新生成 80 级及以上候选的终局抗性门槛（火/冰/电各≥60%、非 CI 混沌≥30%，CI 豁免混沌）与
     生命周期分级门槛（45-64 各 30%、65-79 各 50%、80-89 各 60%，90+ 无额外
     Lifecycle 门槛）以 AGENTS.md 不可协商规则为准，按活动 PoB 实际等级计算，不能因 stage 名称
     或调用者提示改变档位；`resists_capped` 只是兼容 check ID，不代表必须 75% 满抗。
13. 如果 Judge 未通过，在当前会话、当前 `runId`
    和当前需求上下文中直接修改
    活动构筑，再次以相同 `strict_mode` 调用 `evaluate_generation_candidate`。严格模式下存在
    `playabilityFailures` 且有明确可修正项时也可重试；默认 hard-only 不得因隐藏的主观评价改造
    构筑。不要重新调用 `start_generation_run`，也不要要求用户
    重复需求。最多重试两轮；程序返回 `retry_limit_reached` 后必须停止。
    如果修正改变了升华或核心主技能，必须先重新解析身份并重新调用 `query_research_memory`；新一轮
    `researchMemoryUse` 和 `versionContext.researchMemoryRef` 必须包含新的 `dedupeQueryRef`。只调整
    supports、装备数值、天赋路径或配置时不要求重复查询。
    同一 run 最多进行两次核心机制级修复或重建，保留用户明确锁定项；局部装备、辅助和天赋修正
    不计作核心重建。两次后仍无法证明但硬合法时，可以继续 Judge/导出，但必须称为“待验证候选”，
    不得称推荐级成品；若已经确认机制真实失败且补救失败，则停止交付。
14. 顶层只写一次完整最终 `prototypeBuildCandidate`。每轮 compact `generationAttempts` 只写
    `attemptIndex`、`prototypeBuildCandidate: {candidateId}` 和 `failureAudit`；不要在 attempt 中重复
    完整候选。非最后一轮的 `retryDecision` 必须是 `retry`；最后一轮必须是 `accept` 或带明确停止
    原因的 `stop`。helper 按 attempt index、candidateId、可信 receipt 和 artifact-selection 补全
    临时状态与 Judge 报告；同一可信 candidateId 不再比较两份重复候选正文。
15. 每个正式 Judge 已评估、`passed=true`、没有 `hardFailures` 且通过共享硬合法性审计的 attempt
    都是可保护的 passing baseline。完成主动质量收尾后，由 Agent 选择实际采用的 passing attempt，
    并在 `complete_generation_review` 前调用
    `save_final_build_artifact(run_id, run_token, candidate_id, attempt_index)`。新候选更好且合法时选择
    新 attempt；若后续仅质量增量导致回归，可以保存较早 baseline，但必须仍有当前 MCP 进程内的
    精确 Judge 快照、同 state-hash 合法性回执，并传
    `later_findings_scope="candidate_delta_only"` 及有界选择理由。选择的 attempt 不是最后一轮时，
    `agent_output` 顶层还必须显式提交一份最终接受 `failureAudit`：其 `attemptIndex`、`candidateId`、
    `snapshotId` 和版本指向被恢复的 baseline，`retryDecision="accept"`，并在 `summary` 与
    `retainedCaveats` 中说明为何后续发现只影响 candidate delta。不能复用该轮原先的 `retry` audit，
    也不能使用后来失败轮次的 audit；否则返回 `baseline_acceptance_audit_required`。选择最后一轮时
    顶层 `failureAudit` 可省略，由 helper 从该轮补入。后续发现影响 baseline、快照丢失或绑定不一致
    时必须失败关闭；仍有 retry 额度时重新评估，不能伪造 snapshot 或手工改 hash。
    `PlayerStat` / `FullDPSSkill` 等派生输出刷新不算真实变化，失败 attempt 不保存完整 PoB。
    正常顺序永远是“保存 artifact → validate/review”。若旧任务已经误先消费 review，保存工具
    仍会在 candidate、attempt、精确 Judge snapshot 和语义 state hash 全部一致时返回
    `orderingRecovery.reviewAlreadyConsumed=true` 并允许恢复保存；这不是跳过审查的常规路径。
    严格模式下，`playabilityFailures`、`qualityBand="barely_playable"`、目标维度为 0 和其他非硬性
    Judge 警告不阻止技术候选保存与导出；真实玩法/质量缺口会保留 `deliveryStatus=candidate`。
    `scoreApplicability="unavailable"` 单独出现时只限制 PoB 数值措辞，不得自动降级或改换机制；仍须
    在用户可见结论中说明未建模范围与采用的非 PoB 验证依据。
    默认 hard-only 只说明“主观 Judge 反馈已关闭”，不要输出这些字段或据此降级路线。
16. 把本次生成的安全摘要对象作为 `agent_output` 直接提交给
    `validate_generation_output(run_id, run_token, agent_output)`；它不会消费 run，可以根据返回的
    字段路径修正后重试。通过后把同一份最终对象提交给
    `complete_generation_review(run_id, run_token, agent_output)`。插件在受管用户数据目录中完成
    原子写入和可信 review，不需要也不允许 Agent 自己定位或编辑运行文件。可信快照中每个仍存在
    的 completeness advisory，都必须在
    `completenessAdvisoryDecisions` 中记录 `deferred` 或 `intentionally_unused` 及具体理由；已真正
    处理且不再出现在最终快照中的提示不要保留陈旧决策。唯一例外是
    `spirit_opportunity_review_required`：找到有价值的预留并采用后必须重新评估，让提示从快照消失；
    确认没有正收益选项时只能写 `intentionally_unused` 并记录实测依据，不得使用 `deferred`。最终
    PoB XML 由专用 artifact 工具写入
    本地私有存储，不要放入 `agent_output`。
    不得手工删除或改名 `review-result`、`review-consumed`、可信 Judge 回执或运行锁来修复顺序；
    使用 artifact 的受检恢复路径，或按状态机登记失败/重试。
17. 普通交互 Create 的 artifact 保存成功后，按开始时已经确定的交付方式执行，不再询问。Blind/
    自动 Create 跳过本步骤，只保留内部 artifact 供 Compare：
    - **仅本地**：调用 `export_final_pob_artifact(artifact_id, format="both", name=...)` 生成 PoB XML
      和 PoB import code，再调用 `export_final_build_artifact(artifact_id, name, author, description)`
      生成官方 `.build`。不得调用 `export_final_build_package`，也不得调用任何 poe.ninja 发布入口；
      三个本地文件均成功才算本地交付完成；任一失败时展示对应 errorCode 并保留现场；
    - **本地 + poe.ninja**：只调用一次
      `export_final_build_package(artifact_id, name, author, description)`，由现有工具生成三个本地文件并
      上传同一份已验证 PoB code，返回四项 `artifacts` 清单。
    不新增 delivery policy、授权表或二次确认；交付选择只由本轮用户自然语言决定。
     保存 artifact 时会执行一次轻量 PoB round-trip，核对技能/辅助、装备数量、孔位/Rune 和天赋
     珠宝；失败不能导出。`.build` 返回 `guidanceOnly`，并把受限字段写入 description；该限制不改变
     PoB XML/导入码的权威性，也不能把 `candidate` 升级成 `recommended`。
     选择分享时，非 Blind Create 只有在四项全部成功且返回 `runtimeCleanupReady=true` 后，才调用
    `cleanup_completed_task_runtime(task_kind="generation", task_id=artifact_id)`；部分导出时保留现场。
    仅本地工具目前不返回整包清理回执，因此保留运行现场，不伪造 `runtimeCleanupReady`。Blind Create
    的 artifact 仍要进入 Compare，由 Learning campaign 完成后统一清理。
18. 普通交互 Create 向用户展示自然语言构筑结果、Judge 结论、`lifecycleEvidenceCoverage`、内部重试
    改了什么、最终 artifact id，并按选定分支逐项列出结果：仅本地列出 XML、import code、`.build`
    三项，成功项给路径、失败项给 errorCode；分享分支列出整包四项，`poe_ninja_pob` 成功时必须确认
    `publicExternalUpload=true` 并给可点击 URL，失败项给 errorCode。Blind/自动 Create 不展示用户导出项，
    继续提交内部 artifact 进入 Compare。
    官方 `.build` 的黄装、装备孔位、Rune/Soul Core 与天赋珠宝只以 guidance
     text 表达；PoB XML/导入码才是完整装备权威，必须向用户展示这一格式限制。还必须逐项展示
     compact review 的 `requiredUserDisclosures`，不能把符文、
    灵魂核心、珠宝、药剂或护符的暂缓/不用理由留在内部文件。不要展示 PoB XML 或导入码原文。

对照学习盲测模式完成 artifact 后，按 [blind-mode.md](references/blind-mode.md) 用本任务 claim
调用 `submit_learning_create_result`（identity records、目标等级、artifact id、generated
evidence、完整 `researchMemoryUse` 与 `learningMemoryUse`；Family/等级回读不一致时让案例失败）。

内部重试不等于重新生成整个上下文。优先在当前活动构筑上做针对性修正；只有 Agent 判断设计方向
本身需要推倒重建时，才可以在同一个 `runId` 内调用 `new_build` 重新搭建。技能组局部问题优先使用
`list_skill_groups` 后的强类型原子修改，不要因为缺少精确编辑而重建整份 PoB。无论哪种方式，前一轮
可信快照都已由程序保存，不能覆盖或伪造。

如果 `get_freshness_report` 的实际 MCP 调用返回“工具不存在”或宿主明确拒绝调用，才可以判断
PoE2 MCP 不可用。此时说明工具缺失并停止本次构筑生成；不要改为搜索仓库中的旧候选、旧验收包、
临时 JSON 或历史运行产物，也不要把静态文档拼成一个未经工具查询的新 BD。

## Freshness 处理规则

`decision="blocked_stale"` 不等于停止生成：先看具体 blocker 与组件状态。补丁仅在赛季大版本不同
（如 0.5 vs 0.6）时视为不兼容；`github_rate_limited` 但有本地交叉确认时，不表述为"官方天赋树
不可用"；仅本地 PoB 落后则继续生成并标注"过期 PoB 有限证据"（不得宣称当前赛季已验证）；机制
未建模则记录 modelability caveat 不编造数值；核心规则冲突/未知时停止强验证并向用户说明缺口。
league 值在 fresh 组件无法验证时只能采用 provider 声称值（如 ggg-tree 声称的赛季名）：写入
`versionContext.league` 并在 `unresolvedItems`/`unresolvedCaveats` 显式标注"赛季名未经验证，
来自 freshness 声称值"，不要表述为已验证事实。
过期 PoB 模式下仍必须完成 `new_build`、活动构筑、evaluate 和验收包流程，结论同时给出设计判断、
过期诊断和版本限制。完整规则以 AGENTS.md 为准。

## 常用 MCP 工具清单

宿主中完整工具名带 server 前缀（如 `poe_knowledge_mcp__query_research_memory`、
`poe_build_mcp__get_build_stats`），下面只写末尾名称；必须通过 MCP 工具调用，
不能用 PowerShell 搜索仓库文件代替。Create 只连接 knowledge + build 两个 server：知识/图/
机制/Research 查询走 `poe_knowledge_mcp`，所有 PoB/计算/Judge 工具走
`poe_build_mcp`。所有 PoB/计算工具共享同一个活动构筑、**必须串行调用**
（部分优化工具内部临时改状态再恢复，不能按名称推断只读）；只有不接触活动构筑的语料/图/机制/
静态查询可以并行。

**构筑经验记忆**（顺序见工作流第 4 步）：
`query_research_memory`（默认 `detail_level="summary"` + `response_profile="create_compact"`，
精确 Family 检查 `familyRecordCoverage/familyRecordIndex/familyPremiseCatalog`；沿单一
`continuation_cursor` 读到 complete，并锁定 scope+sourceCase lane）｜
`construct_research_execution_contract`（比较 case profiles、生成 package 合同；不自动组装 BD）｜
`query_public_learning_memory`（普通 Create 用，lesson 必须重新验证）｜
`query_learning_memory`（仅 referenceBlind 活动 claim）｜`build_advice`/`suggest_build_lifecycle`
（规划启发，补丁敏感事实以 pinned PoB/图/corpus 为准）。

**图与机制**：`graph_tool_query(resolve_graph_component)` 解析稳定组件｜`find_skills`/`get_gem`/
`list_skills_for_level`（等级获取参考候选池，真实等级可用性以引擎校验为准）｜
`find_supports_for`（数值靠计算工具验证）｜`explain_mechanic`/`search_mechanics`｜
`search_items`/`search_uniques`/`get_unique`｜`relevant_uniques`（按主技能匹配 unique + unique
jewel 候选，须读全文并实测后采用）｜`evaluate_jewel_socket`（unique/radius jewel 的 socket 位置化
评估，先 alloc 再评估）｜`search_mods`/`reverse_lookup`｜`list_ascendancies`。

**临时构筑与计算**（顺序/门禁/重试以工作流为准）：
`new_build`/`set_class`/`set_level`/`set_skill` 初始化｜`add_skill_group`/`list_skill_groups`/
`replace_skill_group`/`remove_skill_group`/`set_skill_group_state`（局部修改前重读 fingerprint 与
state hash）｜`apply_build_mutation_batch`（职能小事务、串联 `outputStateHash`、不接受搜索/
optimizer，仅 `rolledBack=true` 表示回滚成功）｜`equip_item`/`equip_jewel`（显式 slot/socket；
`craft_item` 的 `craftReceiptRef` 原样传入）｜`search_passives`/`alloc_passive`/`optimize_supports`/
`plan_gear(acquisition_profile="realistic_trade", locked_slots=[...])`/`optimize_item`/
`optimize_flask`/`optimize_charm`/`plan_item_sockets_batch`/`evaluate_next_jewel_socket`/
`apply_next_jewel_socket_decision`/
`configure_source_skill_supports`/`scaffold_gear`/局部
`optimize_passives`｜
`apply_combat_profile`（Boss 战假设：默认 shocked/cursed/charges/full_es 全开，只保留构筑
实际能产生的条件，返回的 assumed 清单须记录）｜
`validate_level_availability`（等级约束参考，非硬门槛，数值以 PoB 读回为准）｜
`inspect_generation_checkpoint`/`get_defenses`/`get_build_stats`/`evaluate_build`/
`pinnacle_readiness`（局部诊断；正式 Judge 只用 `evaluate_generation_candidate`）｜
`start_generation_run`/`record_generation_family_discovery`/`validate_generation_blueprint`/
`validate_generation_draft`/`validate_generation_output`/
`complete_generation_review`（Phase 5 run，
不依赖仓库工作目录）｜`save_final_build_artifact`（先于 complete_review）｜
`list_final_build_artifacts`/`load_final_build_artifact`｜`export_final_pob_artifact` +
`export_final_build_artifact`（仅本地）｜`export_final_build_package`（本地 + poe.ninja）；单格式补导/
诊断用 `export_final_pob_artifact`/`export_final_build_artifact`/
`get_build_planner_converter_status`）。`export_build()` 只用于本地临时状态。

`evaluate_generation_candidate` 的 `version_context` 一次提供完整对象，值来自本次 freshness/图/
记忆查询，不猜测、不搜源码补字段：

```json
{
  "league": "当前赛季名",
  "ruleset": "softcore_trade",
  "gamePatch": "当前补丁",
  "passiveTreeVersion": "当前天赋树版本",
  "pobVersionOrCommit": "当前 PoB commit 或版本",
  "graphSnapshotId": "本次图快照编号或明确的 unavailable 标记",
  "researchMemoryRef": "本次 run 内查询回执或明确的 unavailable 标记"
}
```

`pobVersionOrCommit` 只填原始版本号/commit，不拼 `(stale)` 等状态文字；过期状态写入
`unresolvedItems`/`unresolvedCaveats`/`toolFeedbackEvents` 和用户可见版本限制。

## 输出分层

给用户看的内容使用自然语言，说明候选方向、无法评估原因和人工需要判断的点。

明确区分设计判断和工具验证结论：例如“预计剧情手感顺畅”属于 Agent 的设计判断；只有工具实际
检查过的抗性、Spirit、蓝耗、EHP、阶段门槛等才能写成工具验证结论。不要把设计判断描述成已经
通过 PoB/Judge 验证。

只有显式严格模式才输出 `qualityBand`/`rewardStrength` 等主观字段；`qualityBand="strong"` 只表示
当前评分档位，不表示强证据或强验证；若 `rewardStrength="limited"` 必须写成"评分档位 strong，
但证据/奖励强度 limited"。

提交给运行工具的内部对象字段名使用 schema 约定的英文 camelCase。每次运行必须使用
`start_generation_run` 返回的新凭据，禁止复用/改写其他运行的旧 `HumanReviewPacket`；顶层必须
原样带上 `runContext`，`packetId`、`agentRefinedBuildPrompt.promptId/requestRef` 用该次返回值。

Agent 提交的顶层字段：

- `runContext`
- `packetId`
- `agentRefinedBuildPrompt`
- `prototypeBuildCandidate`：最终选中 attempt 的完整候选摘要；每轮 attempt 只保留 `{candidateId}`
- `failureAudit`：仅选择非最后一轮 passing attempt 时必须显式提交最终接受审计；否则可省略
- `toolFeedbackEvents`（可选）
- `generationAttempts`

`agentRefinedBuildPrompt` 至少包含：

- `promptId`
- `requestRef`
- `userRequestSummary`
- `refinedPromptSummary`
- `currentOutputStages`
- `targetLifecycleStages`
- `crossStageLockedDimensions`
- `fieldSources`
- `defaultAssumptions`
- `clarificationQuestions`
- `unresolvedItems`
- `versionContext`
- `noRawMaterial`

字段级约束（服务端 schema 校验，写错会 rejected）：

- `currentOutputStages` / `targetLifecycleStages` 必须是 lifecycle stage 枚举值
  （`campaign_early / campaign_mid / campaign_late / maps_entry / endgame_budget /
  endgame_final / budget_endgame / final_endgame`），不能自定义阶段名；90 级目标对应
  `endgame_budget`（82+），`endgame_final` 需 92+。
- `crossStageLockedDimensions` 只能是 `["class"]`。
- `fieldSources` 的**键**必须覆盖 5 个固定字段名（snake_case）：
  `user_request_summary`、`refined_prompt_summary`、`current_output_stages`、
  `target_lifecycle_stages`、`cross_stage_locked_dimensions`；值只能是
  `user_explicit / agent_inferred / defaulted / unknown`。
- 顶层 `versionContext` 必须与 Judge receipt 的 versionContext **完全一致**
  （含 `researchMemoryRef`）；`toolFeedbackEvents` 每项也要带同一 versionContext。

`prototypeBuildCandidate` 至少包含：

- `candidateId`
- `promptRef`
- `currentOutputStages`
- `targetLifecycleStages`
- `crossStageLockedDimensions`
- `classShell`
- `primarySkillIntent`
- `secondarySkillIntents`
- `mechanicAxes`
- `defenseLayers`
- `spiritAssumptions`
- `gearRoles`
- `passiveAnchorIntents`
- `transitionGates`
- `unresolvedCaveats`
- `completenessAdvisoryDecisions`：只记录**最终可信快照中实际存在的**完整度提示（以
  `transientBuildState.completenessAdvisories` 为准）；快照里不存在的 advisory code 写了会被拒。
  每项包含 `advisoryCode`、`decision`（`deferred` / `intentionally_unused`）和 `reason`
  ；其中 `spirit_opportunity_review_required` 不允许 `deferred`，只能在完成机会成本检查且没有正收益
  方案时使用 `intentionally_unused`，否则应采用改动并让该提示从最终快照消失
- `toolReferences`：每项为对象 `{toolName, queryRef, summary}`；其中
  `query_research_memory` 条目的 `queryRef` 必须覆盖 `researchMemoryUse.dedupeQueryRefs` 与
  `comparisonDedupeQueryRefs` 的全部引用，且必须包含一条 `get_freshness_report` 条目（服务端硬性要求）
- `memoryReferences`（可省略；helper 从 typed `researchMemoryUse` 生成完整去重并集）
- `researchMemoryUse`
- `researchExecutionPlan`：必须引用本轮 `construct_research_execution_contract` 的 `contractRef`，
  选择的 design case 必须等于最终授权 lane；包含全部 package 决定与跨案例完整搭配计划
- `mechanismBlueprintRef` / `mechanismBlueprint`：装备制作前经
  `validate_generation_blueprint` 接受的自由机制蓝图及其薄证据/覆盖索引；ToolReference 必须包含
  同一 `blueprintRef`
- `rationaleSummary`
- `versionContext`
- `noRawMaterial`

候选摘要要表达阶段目标、职业壳、主副技能职责、伤害机制、防御、Spirit/资源、装备职责、天赋锚点、
转型门槛和未解决项；清图、单体、触发与条件性附加伤害可由不同技能承担，不要为单一 Judge 数字
压缩合理的多技能组合。`gearRoles`/`passiveAnchorIntents` 只写方向，不复制完整装备表或天赋路径。

普通模式的 `researchMemoryUse` 至少包含：`retrievalOutcome`、`dedupeQueryRefs`、
`comparisonDedupeQueryRefs`、
`componentKeys`、`buildFamilyKeys`、`selectedKnowledgeScope`、`selectedSourceCaseRef`、
`deepRecordIds`、`patternIds`、`semanticEdgeIds`、
`memoryItemIds`、`insightDecisions` 和可选的 `noMatchReason`。`insightDecisions` 每项使用
`sourceRefs`、`decision`（`adopted` / `caveated` / `rejected`）、`summary` 和 `application`；
`sourceRefs` 必须来自本次命中的安全记忆项。`memoryReferences` 保留兼容，但不必手工复制；
helper 会加入全部授权/对照查询引用和实际使用的记忆项 ID；`versionContext.researchMemoryRef`
使用其中一个真实 `dedupeQueryRef`。匹配 v2 lane 时必须填写两个 selected 字段，且
`patternIds`、`semanticEdgeIds`、`memoryItemIds` 保持空；`no_matching_memory` 时不得伪造 lane。

匹配 Research 时 `researchExecutionPlan` 必须包含：`contractRef`、`selectedDesignCaseRef`、
`selectedVariantRationale`、`coherenceSummary`、`packageDecisions` 和
`crossCaseMechanismPlans`。每条 package decision 的 `mechanismRationale`、`buildApplication` 和
`verificationEvidenceRefs` 都是必填；对照 package 的 `adopted` 决定必须用 `crossCasePlanRef`
绑定完整计划。Draft validation 会重新构造合同并校验所有 package 恰好决定一次、来源 case 与
package 一致、目标 companion 来自授权 lane、跨案例 adopted package 被计划完整覆盖；最终 review
会核对结构 hash 未在 Judge 后改变。完整 plan hash 仍保留作审计，但不会阻止 Judge 驱动的实现、
理由和证据修正。

**关键约束（receipt 时效与一致性，违反会导致整个 run 无法交付）**：

- `dedupeQueryRefs` 与 `comparisonDedupeQueryRefs` 引用的全部 receipt 必须在**当前 Phase 5 run 创建之后**（
  `start_generation_run` 之后）实际查询过——发现/比较阶段的
  旧 receipt 不能用于 evaluate/review。因此普通 Create 的正确顺序是：
  `start_generation_run` → 在 run 内重新做定向 Research 查询（至少覆盖最终采用的全部
  record 与 premise resolution 引用）→ 再 `evaluate_generation_candidate`。
- 授权 `dedupeQueryRefs` 中的同一 retrieval session 必须提供从 page 0 到 terminal 的连续完整
  receipt 链；跨 session、跳页、乱序、memory revision 变化或 manifest 不一致都会失败。所有授权
  v2 receipt 必须选择同一 `selectedKnowledgeScope + selectedSourceCaseRef`，并与 candidate 字段
  完全一致。其他案例只能放进 `comparisonDedupeQueryRefs`；每个对照案例同样必须提供完整 page
  chain、相同 Family/补丁/天赋树版本，且不能与授权 lane 相同。
- `evaluate_generation_candidate` 的 `version_context.researchMemoryRef` 必须就是该 run 内
  receipt 之一（绑定后不可更换）。
- `premiseDecisions` 中 `decision="resolved"` 的 `resolutionRefs` 必须属于**本轮 receipt 的
  deepReadRecordIds**（一次 record 深读只返回请求的记录；引用多条记录就一次查全）。
- 联网页面、外部样本、普通图/语料查询只能作为工具引用或 caveat，不能写入 premise
  `resolutionRefs`；没有本轮 deep-read 解决记录时只能用 `caveated` 或 `not_applicable`。
- 顶层 candidate、`generationAttempts[].failureAudit`、`toolFeedbackEvents` 的
  `versionContext` 必须与 Judge receipt 完全一致（`same_version` 含 `researchMemoryRef`）。
- `toolFeedbackEvents` 每项结构：`eventId`、`feedbackType`（枚举：
  `judge_modelability_gap / judge_offense_evidence_gap / judge_score_review_required /
  query_gap / copy_safety_gap / pob_state_gap / tool_usability_gap`）、`summary`、
  `requiresHumanOrTestReview`、`versionContext`、`noRawMaterial`。

对照学习盲测的独立 `learningMemoryUse`（`queryRef`/`recalledLessonIds`/`decisions`，每项含
`lessonId`/`decision`/`application`/`harmfulOrIncorrect`/`observation`）见
[blind-mode.md](references/blind-mode.md)；提交给 `submit_learning_create_result`，不混入
Research SQLite 引用，也不得写入原始来源信息。

`transientBuildState` 和 `judgeAdvisoryReport` 由 evaluate 的 trusted receipt 按 attempt 补入，
默认不要在 `agent_output` 中重复；显式写入必须与 receipt 完全一致，不得自行生成 `snapshotId`/
`sourceHash`/分数/硬阻断。诊断以 receipt 的 `testedSkillGroups`、`selectedSkill`、
`skillGroupDiagnostics`、`attributeShortfalls` 为准；`pob_main_group` 只是当前计算组，不代表
整个 BD 只能有一个主技能。`feedbackMode="hard_only"` 只用确定性字段；评分/质量档位/caveats/reward
只在显式严格模式下使用。`error` 只表示正式 Judge 调用错误，不能改写成构筑 `hardFailures`。

`generationAttempts` 每项至少包含：

- `attemptIndex`：由 `evaluate_generation_candidate` 返回，从 0 开始，最多为 2；
- `prototypeBuildCandidate`：只写 `{candidateId}` 的候选引用；完整最终候选只在顶层写一次；
- `failureAudit`：本轮 Agent 的安全失败核验摘要。

`failureAudit` 使用英文 schema 字段：`auditId`、`attemptIndex`、`candidateId`、`snapshotId`、
`classification`、`retryDecision`、`summary`、`plannedChanges`、`retainedCaveats`、`stopReason`、
`versionContext`、`noRawMaterial`。`classification` 枚举：
`true_build_failure`（真实合法性/质量问题）｜`judge_modelability_gap`（PoB/Judge 表达不足）｜
`judge_offense_evidence_gap`（有正伤害指标但 delivery evidence limited；strong evidence 低于阶段
floor 是真实伤害不足，不得写成 evidence gap）｜`judge_score_review_required`（可计算但低分需
人工校准）｜`selected_skill_suspect`（评分技能可疑）｜`tool_or_data_gap`｜`mixed`｜
`no_material_failure`｜`unknown`。

`retryDecision="retry"` 必须写具体 `plannedChanges`；`"stop"` 必须写 `stopReason`；只有 Judge 已
评估、通过且无硬阻断时才能用 `"accept"`。

## 安全输出

不输出或写入普通报告、聊天、研究记忆：PoB 导入码、原始 XML、完整 URL、账号/角色/profile 细节；
只有用户选择分享时，最终 `poe_ninja_pob` 交付项返回的公开分享 URL 才允许展示。不得输出
隐藏思维链、完整对话记录、草稿推理。唯一允许持久化完整 PoB XML 的入口是
`save_final_build_artifact`（本系统生成、可信 passing Judge、Agent 明确选中的 attempt，写入本地
私有 artifact store；Agent 不读取/复制/转述其中 XML）。不直接复制第三方完整成熟 BD——约束的是
抄袭与原始材料泄漏，不禁止输出自己设计的技能组合、辅助组合、装备槽位摘要、天赋锚点或转型路线；
helper 会硬拦原始材料和隐私/来源信息。可以输出：安全摘要、字段来源、默认假设、可审查的简短
理由摘要、本地临时状态引用、Judge 摘要和注意事项。

## Phase 5 运行管理工具

`start_generation_run` / `record_generation_family_discovery` / `validate_generation_blueprint` /
`validate_generation_draft` / `validate_generation_output` /
`complete_generation_review` 按工作流
第 2、16 步使用；原样保留返回的 `runContext`、`requestRef`、`promptId`、`packetId` 和
`experimentContext`。运行状态由插件在受管用户数据目录管理，凭据两小时后过期、review 成功后失效。
两个提交工具共用 fail-closed canonicalization：validate 不消费 run，complete 成功后消费；按可信
receipt 补入并核对 Judge 字段、memory lane、attempt 连续性和重试上限；缺少凭据、引用不匹配或
显式字段与 receipt 不一致都会拒绝。`HumanReviewPacket` 只表示材料可进入人工验收，不代表 Judge
或人已认可该 BD；rejected 时按字段错误修正或向用户说明阻塞点。
