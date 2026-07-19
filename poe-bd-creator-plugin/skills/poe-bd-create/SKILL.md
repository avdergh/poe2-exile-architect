---
name: poe-bd-create
description: Use when the user asks for a Path of Exile 2 build, starter build, endgame build, bossing build, mapping build, class build, skill build, or build recommendation.
argument-hint: ["[--no-memory] [natural language build request]"]
---

# /poe-bd-create

## 当前功能

这是一个 Agent 主导的 PoE2 构筑创建入口。你的任务是理解用户想要什么，必要时追问，查询项目
提供的资料和计算工具，设计候选构筑，并把结果整理成可人工验收的安全摘要。

普通用户只应该看到自然语言追问、构筑摘要和验收结论。不要让普通用户阅读或填写 JSON。

默认模式必须渐进查询 `query_research_memory`，并明确记录哪些研究结论被采用、保留为注意事项或
拒绝。用户显式使用 `--no-memory` 时，只跳过研究记忆；静态语料、图、机制、生命周期、PoB、
计算和 Judge 工具仍正常使用。不要为无记忆模式创建另一套 skill 或另一套 MCP 工具。

## 用户交互

无参数触发时，先询问用户目标，不要直接生成构筑。

用户需求可能很模糊，例如：

- 新手开荒顺畅；
- 后期攻坚或终局上限高；
- 某个职业、升华、技能或玩法；
- 只要开荒、只要攻坚、只要终局，或想要完整生命周期方向。

信息不足时，用简短自然语言追问。优先确认：

- 当前要输出哪个阶段：开荒、进图、攻坚、终局；
- 是否有指定职业、升华、技能、武器、预算或交易环境；
- 更重视清图、打 Boss、生存、操作简单、造价低，还是后期上限；
- 是否允许后续洗点、换技能、换装备、换升华。

如果用户已经给出足够信息，直接进入设计，不要为了补齐所有字段而追问。

## 生命周期规则

PoE2 构筑通常围绕最终目标规划，但前期也要能开荒。开荒、攻坚、终局可以是完全不同的玩法。

唯一跨阶段硬锁是职业：不能换职业。

允许跨阶段改变：

- 升华；
- 主技能和辅助技能；
- 天赋；
- 装备；
- 防御层；
- 资源和 Spirit 方案。

当用户说“先给开荒，后期洗点转攻坚/终局”时，本次输出只需要覆盖当前阶段，但职业选择和转型
门槛必须考虑后期目标。

## 工作流程

1. 将用户需求整理成结构化需求摘要。
2. 判断是否需要追问；需要追问时先问用户。
3. 需求足够后，调用本地 helper 的 `start-run`，为本次请求创建独立运行目录和一次性运行凭据。
   普通模式传入 `--memory-mode memory_assisted`；用户使用 `--no-memory` 时传入
   `--memory-mode no_memory`。
4. 先实际调用 MCP 的 `get_freshness_report`。调用成功说明 PoE2 MCP 可用；不能因为没有在界面中
   看到某个工具分组、没有搜索到工具说明或没有先找到 Python 函数，就声称 MCP 不可用。
5. 按下面的 MCP 工具清单查询资料，基于查询结果设计候选构筑方向，不要临时猜工具名。普通模式
   中，`build_advice` 只提供规划启发；补丁敏感事实以当前 pinned PoB、physical graph 和
   current corpus 为准。
   按以下顺序使用研究记忆：
   - 先用 `graph_tool_query(tool_name="search_graph_components", ...)` 发现候选，再用
     `graph_tool_query(tool_name="resolve_graph_component", ...)` 确认用户指定或初选的升华、主技能
     stable key；模糊候选不能当作已确认 key。
   - 精确 Family 首次查询同时传 `ascendancy_key`、`primary_skill_key`，并让 `component_keys`
     只包含这两个稳定身份。普通辅助、utility 和副技能不能作为必需 AND 条件；它们由命中的
     Family/记录返回后再按需解析。自然语言 `query` 只表达构筑目标和排序偏好，不能代替精确身份。
     检查 `buildFamilies` 的 `secondarySkillKeys`、`recordKindCounts`，以及
     `deepResearchRecords`、`buildPatterns`、`semanticEdges` 和旧 `results`，不要只看第一条摘要。
   - 选定 Family 后，若其 `recordKindCounts` 显示存在尚未读取的相关知识，使用
     `build_family_keys=[...]` 和 `record_kinds=[...]` 做定向摘要查询，再对高度相关的少量
     `recordIds` 使用 `detail_level="record"`。不要靠提高总返回上限把整个 Family 塞进上下文。
   - 精确 Family 无命中、有效深度记录过少，或候选在资源、防御、轮转、机制链等具体设计维度仍有
     缺口时，执行第二次定向召回：同主技能跨升华查询只传主技能 key；机制缺口查询使用
     `include_transferable=true` 和对应的 canonical `research_axes`。检查独立返回的
     `transferablePatterns`，不要把它们写成当前 Family 的成熟经验。
   - Family 知识始终优先。公用知识只占补充通道，`scopeWeightCap` 不得高于 Family；即使证据很多，
     `component/global` 也不能获得 `common_within_archetype` 或 `strong_ranking_hint` 的跨流派权威。
     `transferScope=component` 的 Pattern 在其 `originFamilyKeys` 对应 Family 内仍作为 Family 知识返回；
     只有迁移到其他 Family 时才进入较低权重的 `transferablePatterns` 通道。
   - 深读 `recordKind`、`componentMentions.role`、`conditions`、`failureConditions` 和
     `typedPayload`。将 `supportPackages` 作为归属明确的辅助候选并交给当前版本 PoB/
     `optimize_supports` 验证；将 `gearResponsibilities` 转成装备职责而不是照抄来源物品；将
     `ascendancyResponsibilities` 用作升华节点取舍依据；将 `resourceMechanisms` 和轮转/机制链
     转成资源预算、失效条件与 Judge 分状态检查。新字段提供设计证据，不授权程序自动组装 BD。
   - `case_observation` 只可作为当前候选的待验证假设；只有更高证据等级才能支持跨案例的一般性
     结论。采用涉及暗金、天赋、触发、转换或资源交互的结论前，必须用当前静态事实或机制工具
     复核其前提；resolver 成功只证明组件存在，不证明机制解释正确。矛盾项应标为 `rejected`，
     不能仅保留 caveat 后继续当作设计依据。所有记忆仍需经图、PoB 和 Judge 验证合法性与数值。
   - 在 `researchMemoryUse` 中记录查询引用、命中的 Family/record/pattern/edge，以及每条被采用、
     保留或拒绝的结论如何影响候选。若定向查询没有命中，显式使用
     `retrievalOutcome="no_matching_memory"` 和 `noMatchReason`，不能伪造引用。
   `--no-memory` 模式不得调用该工具，候选里的 `memoryReferences` 必须为空、
   `researchMemoryUse` 必须省略，`researchMemoryRef` 使用 `disabled:no_memory_baseline`。
6. 调用 `new_build()` 清空本 MCP session 的活动状态，然后串行使用 PoB/计算工具，把候选方向落实成当前请求所需的
   完整活动构筑。至少实际设置职业、升华、等级、主技能和辅助技能、其他技能组、装备、天赋和
   战斗配置，并检查属性、抗性、Spirit 与资源状态。不能拿只有职业和主技能的空骨架去验收。
   装备目标必须匹配当前阶段：剧情/开荒使用 `plan_gear(stage="campaign")`，刚进图使用
   `stage="maps_entry"`，终局才使用 `stage="endgame"`。元素抗性仍按阶段合法性补足；非 CI 混沌抗
   默认目标分别是 0%、30%、60%，不是所有阶段都强行 75%。达到阶段目标后，应把后缀留给技能
   等级、输出、属性、资源、移速或其他实际缺口；只有明确内容需求才覆盖到 75%。
   `scaffold_gear` 只能让中途骨架可计算，所有 `Scaffold ...` 占位物品必须在最终评估前替换。
   最终黄装必须带当前阶段合理的 `Item Level`，底材需求等级不能超过角色等级，词缀必须来自该
   物品等级可用池。不要为了面板分数把剧情角色穿上终局底材或默认 ilvl 82 黄装。
7. 补齐真实装备系统，而不是只填十个基础装备槽：
   - 实际装备当前阶段生命药剂和魔力药剂；
   - 根据腰带提供的护符槽选择并装备护符，或明确说明为什么当前阶段没有可用护符槽；
   - 调用 `list_jewel_sockets`，由你判断当前阶段是否值得投入天赋珠宝；分配了珠宝孔就必须用
     `optimize_jewel` / `equip_jewel` 填入真实可用珠宝，决定不投入时记录理由；
   - 对可镶嵌装备检查符文/灵魂核心。剧情阶段只使用阶段可获得、预算合理且确有作用的方案，
     不要机械套用带 Perfect Essence 和腐化的终局 `craft_item` 结果；不使用时记录理由。
8. 调用 `inspect_build_completeness()`。修复其中的硬失败；对物品等级、占位装备、符文/灵魂核心、
   天赋珠宝、药剂和护符提示逐项处理或记录明确设计理由。这个工具只做完整度诊断，不会替你设计
   BD；不能仅因为 Judge 数值高就跳过。黄装必须通过前后缀数量、词缀组排他和词缀物品等级
   检查，不能用理论上不存在的黄装抬高伤害或防御数值。
9. 调用 `get_build()` 复读活动构筑，确认 PoB 中的职业、技能、装备和天赋确实是本次候选；发现
   遗留状态或缺项时继续修正。
10. 调用 `inspect_generation_preflight()`。修复 blocking issues 后才进入正式 Judge；完全重复的
    enabled skill group、多主动技能组、重复辅助或 completeness hard failure 不应消耗一次 attempt。
    advisories 仍由 Agent 判断和记录。
11. 调用 `evaluate_generation_candidate(run_id, run_token, candidate_id, version_context)`。这个工具
   会捕获当前 PoB 状态，在独立 Judge 引擎中运行正式评估，并把可信结果绑定到本次运行。不要用
   `evaluate_build`、`pinnacle_readiness` 或 Agent 自己整理的分数冒充正式 Judge。
12. 将该工具返回的 `attemptIndex` 及安全 Judge 结论保留。可信 `transientBuildState` 和
    `judgeAdvisoryReport` 已写入本次 receipt，最终 `agent-output.json` 可以省略这两份重复内容；
    helper 会按 attempt index 补全并严格核对。工具
   拒绝空骨架时继续完成构筑；工具返回 Judge 执行错误时保留错误报告，不要自行改写成已评估。
   `trustedEvaluation` 只表示活动快照和 Judge 结果由程序绑定；`versionContextTrusted=false` 表示
   版本上下文仍需与本次 `get_freshness_report` 返回核对，不能借此冒充当前赛季强验证。
13. 对本轮结果做简短失败核验：区分真实构筑失败、PoB/Judge 建模缺口、Judge 选错技能、工具或
    数据缺口、混合问题，或者当前没有实质失败。只保存结论摘要、修改计划和保留的注意事项，
    不保存逐步推理。
    `passed=true` 只表示确定性合法性通过，不等于候选值得推荐。按以下四层处理结果：
    `hardFailures` 是确定性非法；`playabilityFailures` 是合法但存在严重可玩性短板；
    `qualityWarnings` 是未达到推荐质量目标；`modelability` 是 PoB/Judge 能否可靠计算；
    `offenseEvidence` 区分 metric 是否可用、阶段 floor 是否达到和 delivery evidence 是否充分。
    如果存在 `playabilityFailures`、`qualityBand="barely_playable"`、offense/recovery 等与用户
    目标直接相关的维度为 0，或 `offenseEvidence.floorStatus != "met"`，
    必须优先继续修正或核验。重试耗尽后可以交付给人工研究，但只能称为“弱原型/待完善候选”，
    不能称为“推荐方案”“开荒顺畅已验证”或“成品 BD”。
    `scoreApplicability="unavailable"` 表示核心机制当前无法可靠数值验证。不得引用综合分或 DPS
    强度，也不得把工具能力不足说成 BD 非法；保留该设计并明确需要机制参考或实战核验。
    对“开荒顺畅”请求，还必须检查清图职责、单体/Boss 职责和资源恢复；不能只证明三抗、属性和
    插槽合法就接受。若一个技能同时承担清图与单体，必须有 PoB/机制证据或明确实战 caveat；否则
    应补充独立单体技能/组合，或把结果降级为仅清图方向。
    接近剧情结束或进入异界时，主输出仍只有零到一个辅助技能属于高优先级完整度提醒。调用
    `optimize_supports` 测试阶段合理的组合，或说明少辅助为何是有意设计；它不是合法性硬规则。
    不要用“总蓝量至少是单次耗蓝的固定倍数”删辅助。续航应结合未保留蓝量、使用频率、每秒
    恢复、药剂、击回/偷取和实际技能轮转判断；证据不足时标记为待实测。
14. 如果 Judge 未通过，或存在 `playabilityFailures` 且有明确可修正项，在当前会话、当前 `runId`
    和当前需求上下文中直接修改
    活动构筑，再次调用 `evaluate_generation_candidate`。不要重新调用 `start-run`，也不要要求用户
    重复需求。最多重试两轮；程序返回 `retry_limit_reached` 后必须停止。
    如果修正改变了升华或核心主技能，必须先重新解析身份并重新调用 `query_research_memory`；新一轮
    `researchMemoryUse` 和 `versionContext.researchMemoryRef` 必须包含新的 `dedupeQueryRef`。只调整
    supports、装备数值、天赋路径或配置时不要求重复查询。
15. 每轮生成一项 compact `generationAttempts` 记录，只写 `attemptIndex`、本轮 candidate 和
    `failureAudit`。非最后一轮的 `retryDecision` 必须是 `retry`；最后一轮必须是 `accept` 或带明确
    停止原因的 `stop`。顶层最终 candidate、failure audit、临时状态和 Judge 报告由 helper 从末次
    compact attempt 与 receipt 规范化生成，不必重复抄写。
16. 如果最后一轮 Judge 已评估、`passed=true`、没有 `hardFailures`，且活动快照有效，必须在
    调用 `review-packet` 前调用
    `save_final_build_artifact(run_id, run_token, candidate_id, attempt_index)`。这个工具只保存当前
    最后一轮且仍与可信 Judge 快照完全一致的活动 PoB；失败轮次和旧 attempt 不保存完整 PoB。
    当前临时交付策略下，`playabilityFailures`、`qualityBand="barely_playable"`、目标维度为 0、
    `scoreApplicability="unavailable"` 和其他非硬性 Judge 警告不阻止保存与导出。它们仍必须原样
    出现在用户可见 Judge 结论中，并将结果称为弱原型/待验证候选，不能称为推荐方案或已验证成品。
17. 只把本次生成的安全摘要写入 `start-run` 已初始化的 `agentOutputFile`。先调用
    `validate-output`；它不会消费 run，可以根据字段路径修正后重试。通过后再用对应 `runId` 和
    `runToken` 调用 `review-packet --compact`。完整 review 会写入 `reviewResultFile`，stdout 只返回
    紧凑摘要。最终 PoB XML 由专用 artifact 工具写入本地私有存储，不要写入 `agentOutputFile`。
18. artifact 保存成功后，只调用一次
    `export_final_build_package(artifact_id, name, author, description)`。这个工具固定尝试导出 PoB XML、
    PoB 导入码文本和官方 `.build`，并返回完整 `artifacts` 清单。不要再自行分别调用多个导出工具
    拼接交付结果；除非用户明确只补导某一种格式。
19. 向用户展示自然语言构筑结果、Judge 结论、`lifecycleEvidenceCoverage`、内部重试改了什么、
    最终 artifact id，并逐项列出
    `export_final_build_package.artifacts` 中的全部三项。成功项必须给路径，失败项必须给 errorCode；
    不得省略任何一项。不要展示 PoB XML 或导入码原文。

内部重试不等于重新生成整个上下文。优先在当前活动构筑上做针对性修正；只有 Agent 判断设计方向
本身需要推倒重建时，才可以在同一个 `runId` 内调用 `new_build` 重新搭建。无论哪种方式，前一轮
可信快照都已由程序保存，不能覆盖或伪造。

如果 `get_freshness_report` 的实际 MCP 调用返回“工具不存在”或宿主明确拒绝调用，才可以判断
PoE2 MCP 不可用。此时说明工具缺失并停止本次构筑生成；不要改为搜索仓库中的旧候选、旧验收包、
临时 JSON 或历史运行产物，也不要把静态文档拼成一个未经工具查询的新 BD。

## Freshness 处理规则

`get_freshness_report.decision="blocked_stale"` 不等于必须停止生成。它首先表示不能把结果宣称为
“当前版本已验证”。必须查看具体 blocker 和各组件状态：

- 游戏补丁只在赛季大版本不同（例如 `0.5` 与 `0.6`）时视为数据不兼容；同一赛季内的精确
  补丁号差异只记录来源和注意事项，不应仅因此停止生成。以 freshness 返回的结构化结论为准，
  不要自行比较字符串。
- `provider_status` 出现 `github_rate_limited`，但 freshness 已由本地已认证 PoB/语料和
  poe.ninja 交叉确认同一树世代、顶层没有对应 blocker 时，只说明官方最新提交暂时无法刷新；
  不要将其表述为“官方天赋树不可用”。
- 当前游戏补丁、赛季和天赋树可确认，仅本地 `pob_engine` / `pob_data` 落后：继续查询、设计、
  搭建活动构筑并运行 Judge。把 PoB 数值和 Judge 评分明确标为“过期 PoB 有限证据”，不得宣称
  当前赛季已验证，但不能因此停止生成。
- 当前补丁资料可用，但某个机制在 PoB 中尚未建模：继续生成，记录 modelability caveat，不编造
  数值。
- 当前游戏补丁、赛季、天赋树或设计所需的核心技能/机制资料发生冲突或无法确认：停止当前版本
  的强验证，向用户说明具体缺口；必要时追问是否接受明确版本绑定的未验证设计。
- `blocked_conflict` / `blocked_unknown` 也必须看具体组件，不能只根据 decision 名称机械停止；但
  不能在核心游戏规则未知时自行假设当前合法性。

过期 PoB 有限证据模式下仍必须完成 `new_build`、活动构筑搭建、`get_build`、
`evaluate_generation_candidate` 和人工验收包流程。用户可见结论需要同时给出 Agent 设计判断、
过期 PoB/Judge 诊断和版本限制。

## 常用 MCP 工具清单

下列名称是 PoE2 MCP tool 名称。通过宿主提供的 MCP 工具调用，不是 Python 函数调用，也不是
让用户手动执行。宿主中的完整工具名通常带有 `mcp__poe2_build_mcp__` 前缀，例如
`mcp__poe2_build_mcp__get_freshness_report`；下面为了便于阅读只写末尾名称。必须通过 MCP 工具调用
它们，不能用 PowerShell 搜索仓库文件来代替。

构筑经验记忆：

- `query_research_memory(query, component_keys=[...], ascendancy_key=...,
  primary_skill_key=..., build_family_keys=[...], record_kinds=[...], limit=...,
  detail_level="summary", include_transferable=false, research_axes=[])`：按精确 Family、稳定组件
  和记录类型查询安全摘要、深度记录、模式与语义边。首查使用升华与核心主技能的精确参数；选定
  Family 后按 `recordKindCounts` 定向查询。`gem:` 与对应 `skill:` 身份由工具依据物理图关系等价
  处理。使用 `detail_level="record", record_ids=[...]` 只深读已选记录。需要跨 Family 机制时
  显式启用 `include_transferable` 并按缺口提供 `research_axes`；结果在 `transferablePatterns`
  中单列。每次返回的 `dedupeQueryRef` 是本次查询的安全引用。
- `build_advice(topic)`：查构筑规划启发，例如开荒红线、终局伤害来源、防御短板。
- `suggest_build_lifecycle(goal, ...)`：查生命周期路线骨架。这个工具可能只返回阶段、转型门槛和
  设计原则，不一定给具体技能名；如果没有技能名，由你继续用技能、机制和计算工具选择。

图和机制查询：

- `graph_tool_query(tool_name="resolve_graph_component", payload={...})`：解析技能、职业、机制、
  passive anchor、物品等稳定组件。
- `find_skills(query, ...)` / `get_gem(name_or_id)`：找主动技能和技能详情。
- `find_supports_for(skill, limit=...)`：找候选辅助技能；数值强弱仍要靠计算工具验证。
- `explain_mechanic(topic)` / `search_mechanics(query, limit=...)`：查机制说明。
- `search_items(query, ...)` / `search_uniques(query, ...)` / `get_unique(name)`：查物品和暗金。
- `search_mods(text, ...)` / `reverse_lookup(stat, ...)`：查装备词缀来源。
- `list_ascendancies(character)`：查职业可用升华。

临时构筑和计算：

这些工具共享同一个临时构筑状态。所有 PoB/计算工具都必须串行调用，包括名称看起来像查询或
优化的工具；部分优化工具内部会临时修改再恢复构筑状态，不能按工具名称推断它是只读的。只有
不接触共享临时构筑状态的语料、图、机制和静态资料查询可以并行。

- `new_build()`：开始搭建临时构筑前先清空状态。
- `set_class(class_name, ascendancy=None)`：设置职业和可选升华。
- `set_level(level)`：设置当前阶段等级。
- `set_skill(skill)`：设置主技能和辅助技能。
- `add_skill_group(skill, in_full_dps=False)`：加入光环、保留、辅助伤害或其他技能组。
- `equip_item(raw, slot=None)` / `equip_jewel(raw, socket=None)`：装备临时物品或珠宝。
- `search_passives(query, ...)` / `alloc_passive(node)`：查并分配关键天赋点。
- `optimize_supports(skill, ...)`：用引擎测辅助技能组合。
- `plan_gear(...)` / `optimize_item(...)` / `scaffold_gear(...)`：搭建或补足临时装备状态。
- `plan_gear(stage=..., chaos_resist_target=...)`：整套装备规划必须传当前阶段。不要为提高 EHP/Judge
  分数而在剧情阶段强行封顶混沌抗；显式 75% 只用于确有该需求的终局内容。
- `inspect_build_completeness()`：Judge 前检查黄装物品等级、底材等级、Scaffold 占位装、符文/
  灵魂核心决策、天赋珠宝、药剂和护符。除明确等级非法外是 advisory，不替 Agent 决定配装。
- `inspect_generation_preflight()`：正式 Judge 前对同一活动 snapshot 做技能组与 completeness
  阻断预检；blocking issue 不应消耗 attempt，advisory 仍由 Agent 决定。
- `get_defenses()` / `get_build_stats(keys=None)`：读取防御和伤害等计算结果。
- `evaluate_build(goals)`：做当前阶段局部数值检查，不是正式 Judge。
- `pinnacle_readiness(...)`：只用于用户明确要求的终局攻坚/巅峰候选；不得用于剧情或普通开荒
  候选，否则会把混沌抗 75%、终局 EHP/DPS 等门槛错误套到早期构筑。
- `evaluate_generation_candidate(run_id, run_token, candidate_id, version_context)`：构筑完成后的正式
  Judge 入口。它只捕获和评价 Agent 已搭好的活动构筑，不会替 Agent 补技能、装备或天赋。
- `save_final_build_artifact(run_id, run_token, candidate_id, attempt_index)`：Agent 接受最后一轮通过
  Judge 的活动 PoB 后保存最终本地产物；必须在 `review-packet` 前调用。
- `list_final_build_artifacts()`：列出最终产物的安全元数据。
- `load_final_build_artifact(artifact_id)`：把最终产物恢复到活动 PoB，不返回原始 XML。
- `export_final_pob_artifact(artifact_id, format="both", name="")`：把最终可信产物写成本地 PoB XML
  和/或导入码文本文件；响应只返回路径。默认 `both`，也可只选 `xml` 或 `import_code`。
- `export_final_build_package(artifact_id, name, author, description, link)`：最终交付首选入口。一次生成
  PoB XML、PoB 导入码文本和官方 `.build`，并固定列出三项的成功路径或失败错误码。
- `get_build_planner_converter_status()`：检查固定版本的官方 `.build` 转换 provider 是否可用。
- `export_final_build_artifact(artifact_id, name, author, description, link)`：把最终可信 PoB 导出为
  官方单阶段 `.build` 文件，返回本地路径、provider 信息、转换统计和注意事项。
- `export_build()` 只能用于本地临时状态，不要把导入码写进用户输出或持久报告。

`evaluate_generation_candidate` 的 `version_context` 必须一次提供完整对象，字段使用下面这些名称；
值来自本次 freshness、图和记忆查询，不要临时猜测，也不要通过搜索源码补字段：

```json
{
  "league": "当前赛季名",
  "ruleset": "softcore_trade",
  "gamePatch": "当前补丁",
  "passiveTreeVersion": "当前天赋树版本",
  "pobVersionOrCommit": "当前 PoB commit 或版本",
  "graphSnapshotId": "本次图快照编号或明确的 unavailable 标记",
  "researchMemoryRef": "本次记忆查询引用或明确的 unavailable 标记"
}
```

`pobVersionOrCommit` 只填写原始版本号或 commit，不要把 `(stale)`、`过期` 等状态文字拼进版本值。
过期状态写入 `unresolvedItems`、`unresolvedCaveats`、`toolFeedbackEvents` 和用户可见版本限制。

## 输出分层

给用户看的内容使用自然语言，说明候选方向、无法评估原因和人工需要判断的点。

明确区分设计判断和工具验证结论：例如“预计剧情手感顺畅”属于 Agent 的设计判断；只有工具实际
检查过的抗性、Spirit、蓝耗、EHP、阶段门槛等才能写成工具验证结论。不要把设计判断描述成已经
通过 PoB/Judge 验证。

`qualityBand="strong"` 只表示当前评分档位，不表示强证据或当前赛季强验证。若
`rewardStrength="limited"`，用户输出必须明确写成“评分档位 strong，但证据/奖励强度 limited”，
不能只写“strong”或“强力验证通过”。

给 helper 的内部文件必须是 `agent-output.json`，字段名使用 schema 约定的英文 camelCase。

每次运行都必须使用 `start-run` 返回的新路径和凭据。禁止读取、复用或改写其他运行留下的
`agent-output.json`、`.tmp_agent_output_*`、旧 `HumanReviewPacket` 或历史候选文件。本次文件顶层
必须原样带上 `start-run` 返回的 `runContext`；`packetId`、`agentRefinedBuildPrompt.promptId` 和
`agentRefinedBuildPrompt.requestRef` 也必须使用该次返回值。

顶层字段：

- `runContext`
- `packetId`
- `agentRefinedBuildPrompt`
- `toolFeedbackEvents`
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
- `toolReferences`
- `memoryReferences`（可省略；helper 从 typed `researchMemoryUse` 生成完整去重并集）
- `researchMemoryUse`
- `rationaleSummary`
- `versionContext`
- `noRawMaterial`

普通模式的 `researchMemoryUse` 至少包含：`retrievalOutcome`、`dedupeQueryRefs`、
`componentKeys`、`buildFamilyKeys`、`deepRecordIds`、`patternIds`、`semanticEdgeIds`、
`memoryItemIds`、`insightDecisions` 和可选的 `noMatchReason`。`insightDecisions` 每项使用
`sourceRefs`、`decision`（`adopted` / `caveated` / `rejected`）、`summary` 和 `application`；
`sourceRefs` 必须来自本次命中的安全记忆项。`memoryReferences` 保留兼容，但不必手工复制；
helper 会加入全部 `dedupeQueryRefs` 和实际使用的记忆项 ID；`versionContext.researchMemoryRef`
使用其中一个真实 `dedupeQueryRef`。

`transientBuildState` 至少包含：

- `status`
- `snapshotId`
- `sourceHash`
- `safeSummary`
- `testedSkillGroups`
- `missingReasons`
- `versionContext`
- `noRawMaterial`

当 `status="available"` 时，`testedSkillGroups` 不能为空。每项至少记录：

- `groupIndex`：PoB 中的技能组编号；
- `role`：只记录 `pob_main_group`（PoB 当前计算组）或 `additional_skill_group`（额外技能组）；
  这不是对整个 BD 唯一主技能的判断；
- `activeSkill`：实际放入临时状态的主动或持续技能；
- `activeSkills` / `activeSkillCount`：该组全部主动技能及数量，用来定位一个技能组误放多个主动
  技能导致的插槽错误；
- `supports`：计算时实际使用的辅助技能名称；
- `enabled`：计算时是否启用。

`judgeAdvisoryReport` 至少包含：

- `reportId`
- `status`
- `hardFailures`
- `caveats`
- `aggregateScore`
- `rewardStrength`
- `evaluatedSnapshotId`
- `evaluatedSourceHash`
- `selectedSkill`：Judge 本次用于 offense 评分的伤害组件，不等于整个 BD 唯一主技能；
- `supplementalSkills`：条件性附加伤害组件及其场景限制，例如击杀后爆炸；
- `skillGroupDiagnostics`：选中组和其他已测试组的主动技能数量、名称与辅助数量；
- `attributeShortfalls`：当前力量、敏捷或智慧低于需求时的具体缺口；
- `errorCode`
- `versionContext`
- `noRawMaterial`

`transientBuildState` 和 `judgeAdvisoryReport` 由本次 `evaluate_generation_candidate` 的 trusted
receipt 补入。不要自行生成 `snapshotId`、`sourceHash`、Judge 分数或硬阻断；如果仍显式写入，
必须与 receipt 完全一致。`error` 只表示正式 Judge 调用发生错误，此时不能把构筑失败写进
`hardFailures`。

`generationAttempts` 每项至少包含：

- `attemptIndex`：由 `evaluate_generation_candidate` 返回，从 0 开始，最多为 2；
- `prototypeBuildCandidate`：本轮 Agent 候选安全摘要；
- `failureAudit`：本轮 Agent 的安全失败核验摘要。

`failureAudit` 使用英文 schema 字段：`auditId`、`attemptIndex`、`candidateId`、`snapshotId`、
`classification`、`retryDecision`、`summary`、`plannedChanges`、`retainedCaveats`、`stopReason`、
`versionContext`、`noRawMaterial`。`classification` 只能是：

- `true_build_failure`：构筑确实存在合法性或质量问题；
- `judge_modelability_gap`：PoB/Judge 对机制表达不足；
- `judge_offense_evidence_gap`：已有正伤害指标，但 delivery evidence 仍为 limited；strong evidence
  低于阶段 floor 属于真实阶段伤害不足，不得写成 evidence gap；
- `judge_score_review_required`：modelability 可用，但低分仍需要校准/人工审查；
- `selected_skill_suspect`：Judge 本次选择的评分技能可疑；
- `tool_or_data_gap`：工具或当前数据覆盖不足；
- `mixed`：同时存在多类问题；
- `no_material_failure`：没有需要重试的实质失败；
- `unknown`：当前证据不足以分类。

`retryDecision="retry"` 时必须写具体 `plannedChanges`；`retryDecision="stop"` 时必须写
`stopReason`；只有 Judge 已评估、通过且没有硬阻断时才能使用 `retryDecision="accept"`。

## 候选构筑摘要语义

- 当前输出阶段；
- 完整生命周期目标；
- 职业壳，并明确不能换职业；
- 主技能意图和辅助技能意图；
- 清图、单体、触发、伤害兑现和条件性附加效果可以由不同技能承担；不要为了迎合单一 Judge
  数字把合理的多技能组合压缩成一个技能；
- 主要伤害机制和缩放轴；
- 防御层；
- Spirit 或保留资源假设；
- 装备角色和词缀方向，不要列完整装备表；
- 天赋锚点或区域意图，不要列完整天赋路径；
- 转型门槛，例如何时洗点、换技能、换装备或换升华；
- 未解决问题和不能评估的原因；
- 使用过的工具、查询或记忆引用。

## 安全输出

不要输出或写入普通报告、聊天、研究记忆：

- PoB 导入码；
- 原始 XML；
- 完整 URL；
- 账号、角色或 profile 细节；
- 模型隐藏思维链；
- 完整对话记录；
- 草稿推理区。

唯一允许持久化完整 PoB XML 的入口是 `save_final_build_artifact`。它只处理本系统自己生成、最后一轮
可信 Judge 已通过且 Agent 明确接受的候选，并写入本地私有 artifact store；Agent 不读取、复制或
转述其中 XML。

不要直接复制第三方完整成熟 BD。这里约束的是抄袭和原始材料泄漏，不是禁止你输出自己设计出来的
技能组合、辅助组合、装备槽位摘要、天赋锚点或转型路线。helper 会硬拦原始材料和隐私/来源信息，
不会因为一个候选和常见强机制相似就判定失败。

可以输出：

- 安全摘要；
- 字段来源；
- 默认假设；
- 可审查的简短理由摘要；
- 本地临时状态引用；
- Judge 摘要和注意事项。

## 本地 helper

普通用户不需要手动运行脚本；宿主 Agent 自己调用。

Windows：

```powershell
.\.tools\uv\uv.exe run python scripts\create_build.py start-run --memory-mode memory_assisted
.\.tools\uv\uv.exe run python scripts\create_build.py start-run --memory-mode no_memory
.\.tools\uv\uv.exe run python scripts\create_build.py validate-output --run-id "<runId>" --run-token "<runToken>"
.\.tools\uv\uv.exe run python scripts\create_build.py review-packet --compact --run-id "<runId>" --run-token "<runToken>"
```

macOS / Linux：

```bash
./.tools/uv/uv run python scripts/create_build.py start-run --memory-mode memory_assisted
./.tools/uv/uv run python scripts/create_build.py start-run --memory-mode no_memory
./.tools/uv/uv run python scripts/create_build.py validate-output --run-id "<runId>" --run-token "<runToken>"
./.tools/uv/uv run python scripts/create_build.py review-packet --compact --run-id "<runId>" --run-token "<runToken>"
```

`start-run` 返回：

- `runContext`：本次运行的一次性绑定信息，原样写入内部 JSON；
- `requestRef`、`promptId`、`packetId`：本次产物必须使用的编号；
- `agentOutputFile`：本次唯一允许写入和验收的 Agent 产物路径；
  helper 已在其中初始化 run binding 骨架，Agent 在该文件上补安全设计字段；
- `reviewResultFile`：helper 成功验收后原子写入的安全结果副本；若命令输出意外中断，可以读取
  这个文件确认本次结果。
- `experimentContext`：本次是否允许使用研究记忆，以及最多两轮内部重试的运行合同。

`review-packet` 根据 `runId` 自行定位本次目录，不接受调用者指定其他清单或产物路径；它只接受
与本次运行凭据匹配的文件。运行凭据两小时后过期，成功验收后立即失效，不能再次验收。

`validate-output` 与 `review-packet` 共用同一条 fail-closed canonicalization。前者不消费 run；后者
成功后写完整 review 并消费运行凭据。两者都会读取本次运行目录中的可信 Judge 凭据。缺少凭据、
候选编号不一致，或 Agent 文件中的临时状态/Judge 报告与可信结果不同，都会被拒绝。helper 通过
只表示材料可以进入人工验收；Judge 分数仍是参考评估，不代表人已经认可这个 BD。

在普通或 `--no-memory` 模式下，`review-packet` 还会逐轮核对 `generationAttempts`。普通模式缺少
研究记忆安全引用、无记忆模式实际调用了研究记忆、轮次不连续、超过两次重试，或任一轮状态/Judge
与可信凭据不一致时都会拒绝。返回的 `retryComparisonReport` 只描述同一次生成内部修正前后的
硬阻断和分数变化，不用于自动比较普通模式与无记忆模式。

helper 期望的顶层结构：

- `agentRefinedBuildPrompt`：结构化需求摘要；
- `prototypeBuildCandidate`：候选构筑安全摘要；
- `transientBuildState`：正式评估工具返回的临时构筑状态引用；
- `judgeAdvisoryReport`：正式评估工具返回的 Judge 安全摘要；
- `toolFeedbackEvents`：可选，记录工具缺口或误判。

helper 返回人工验收包 `HumanReviewPacket`。如果返回 rejected，按错误原因修改安全摘要或向用户说明阻塞点。
