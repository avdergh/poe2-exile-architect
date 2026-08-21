---
name: poe-bd-create
description: Use when the user asks for a Path of Exile 2 build, starter build, endgame build, bossing build, mapping build, class build, skill build, or build recommendation.
---

> **DSH 适配说明**：本 skill 运行在 DeepSeek Harness。所有 poe-bd 能力都是 MCP
> 工具，完整名带 `mcp__poe_<server>__` 前缀（例如
> `mcp__poe_knowledge__query_research_memory`、`mcp__poe_build__get_build_stats`），
> 下文只写末尾名称。加载本 skill 使用 DSH 的 `skill` 工具，不存在 `/poe-bd-*`
> 斜杠命令。工具清单以当前会话实际注册为准，不要猜测未注册的工具名。
> Create 只连接 knowledge + build 两个 server：知识/图/机制/Research 查询走
> `mcp__poe_knowledge__*`，所有 PoB/计算/Judge 工具走 `mcp__poe_build__*`。
> 所有 PoB/计算工具共享同一个活动构筑、必须串行调用；只有不接触活动构筑的
> 语料/图/机制/静态查询可以并行。

# /poe-bd-create

## 当前功能

这是一个 Agent 主导的 PoE2 构筑创建入口。你的任务是理解用户想要什么，必要时追问，查询项目
提供的资料和计算工具，设计候选构筑，并把结果整理成可人工验收的安全摘要。

普通用户只应该看到自然语言追问、构筑摘要和验收结论。不要让普通用户阅读或填写 JSON。

默认模式必须渐进查询
`mcp__poe_knowledge__query_research_memory(response_profile="create_compact")`，并在确认精确 Family 后调用
`mcp__poe_knowledge__query_public_learning_memory` 读取公开种子与本地追加的跨案例经验。明确记录哪些 Research 结论
被采用、保留为注意事项或拒绝；Learning lesson 只作为待验证的设计提醒。Create 必须优先阅读
紧凑结果中的 `criticalPremiseDigest`；不能只记住正向组件而丢失条件、失败场景和验证任务。
`buildPatterns` 以 typed `confidenceTier` 和 `semanticScopeReview` 为范围权威；
`legacy_unattested` 只能作为需重新验证的旧观察，不能凭自然语言中的“常见/通常”等措辞提高权重。用户
显式使用 `--no-memory` 时跳过 Research 与 Learning Memory；静态语料、图、机制、生命周期、
PoB、计算和 Judge 工具仍正常使用。不要为无记忆模式创建另一套 skill 或另一套 MCP 工具。

Judge 反馈默认是硬门槛模式。除非用户在本次请求中明确写出“严格模式”或 `--strict-judge`，否则
`mcp__poe_build__inspect_generation_preflight`、`mcp__poe_build__inspect_generation_checkpoint`、`mcp__poe_build__verify_lifecycle_stage` 和
`mcp__poe_build__evaluate_generation_candidate` 一律使用 `strict_mode=false`。该模式仍运行完整 PoB/Judge，
但只返回确定性硬失败、是否合法、快照绑定和事实诊断；不要补写、猜测或从其他字段反推出评分、
质量档位、playability/quality warning、reward 或主观 caveat。用户明确要求严格模式时，上述
调用统一传 `strict_mode=true`；第一次正式 Judge 后同一 run 不得切换模式。

当输入是 `referenceBlind=true` 的 `BlindCreatePacket` 时，进入对照学习盲测模式：不询问任何
交互问题，直接按 [references/blind-mode.md](references/blind-mode.md) 执行
（查询 `mcp__poe_learning__query_learning_memory`、提交 `mcp__poe_learning__submit_learning_create_result`）。

## 用户交互

本工具专注终局 BD 生成（目标等级通常 80+，覆盖从进图到巅峰的内容），不提供全链路开荒成长
流程。普通 Create 直接生成用户请求的目标等级单阶段 BD。

无参数触发时，先简短追问构筑目标，不要直接生成构筑。

用户需求可能很模糊，例如：

- 后期攻坚或终局上限高；
- 某个职业、升华、技能或玩法；
- 只要攻坚、只要终局，或想要完整终局方向。

需求信息不足时，用简短自然语言追问。优先确认：

- 当前要输出哪个阶段：进图、攻坚、终局；
- 是否有指定职业、升华、技能、武器、预算或交易环境；
- 更重视清图、打 Boss、生存、操作简单、造价低，还是后期上限；
- 是否允许后续洗点、换技能、换装备、换升华。

其他字段已经足够时直接进入设计，不要为了补齐所有字段继续追问。

## 生命周期定位

终局 BD 可覆盖不同升华、技能、天赋、装备、防御与资源方案；跨内容硬锁是基础职业，不能换职业。
普通单阶段请求只覆盖当前阶段，但职业选择和转型门槛仍要考虑用户明确提出的后期目标。

## 工作流程

1. 将用户需求整理成结构化需求摘要。
2. 需求足够后，调用插件 MCP 的 `mcp__poe_build__start_generation_run`，为本次请求创建独立运行状态和一次性
   凭据。普通模式传 `memory_mode="memory_assisted"`；用户使用 `--no-memory` 时传
   `memory_mode="no_memory"`。不要搜索仓库、猜测工作目录或运行 `scripts/create_build.py`；发布
   插件已经自带这个入口。若工具确实未注册，停止并报告插件安装不完整，不能降级成文字 BD。
3. 先实际调用 MCP 的 `mcp__poe_knowledge__get_freshness_report`。调用成功说明 PoE2 MCP 可用；不能因为没有在界面中
   看到某个工具分组、没有搜索到工具说明或没有先找到 Python 函数，就声称 MCP 不可用。
4. 按下面的 MCP 工具清单查询资料，基于查询结果设计候选构筑方向，不要临时猜工具名。普通模式
    中，`mcp__poe_knowledge__build_advice` 只提供规划启发；补丁敏感事实以当前 pinned PoB、physical graph 和
    current corpus 为准。
   按以下顺序使用研究记忆：
   - 先用 `mcp__poe_knowledge__graph_tool_query(tool_name="search_graph_components", ...)` 发现候选，再用
     `mcp__poe_knowledge__graph_tool_query(tool_name="resolve_graph_component", ...)` 确认用户指定或初选的升华、主技能
     stable key；模糊候选不能当作已确认 key。
   - Create 用途的查询默认传 `response_profile="create_compact"`。它不改变 durable typed
     receipt，不截断命中结果，只压缩每项的重复检索字段，并把条件、失效场景和验证任务集中到
     `criticalPremiseDigest`。若具体歧义依赖被省略字段，显式改用 `response_profile="full"`；
     Research 采集/维护流程仍使用默认完整响应。
   - 精确 Family 首次查询同时传 `ascendancy_key`、`primary_skill_key`，并让 `component_keys`
     只包含这两个稳定身份。普通辅助、utility 和副技能不能作为必需 AND 条件；它们由命中的
     Family/记录返回后再按需解析。自然语言 `query` 只表达构筑目标和排序偏好，不能代替精确身份。
     Family identity 使用玩家 `active_skill` 的 `skill:` key；物理图已关联的 `gem:` key 可以
     作为查询别名，但不能直接写入 FamilyTarget 或作为 Family 身份权威。
     检查 `buildFamilies` 的 `secondarySkillKeys`、`recordKindCounts`，以及
     `deepResearchRecords`、`buildPatterns`、`semanticEdges` 和旧 `results`，不要只看第一条摘要。
   - 选定 Family 后，若其 `recordKindCounts` 显示存在尚未读取的相关知识，使用
     `build_family_keys=[...]` 和 `record_kinds=[...]` 做定向摘要查询，再对解决当前设计所需的
     `recordIds` 使用 `detail_level="record", response_profile="create_compact"`。优先按维度
     渐进深读，不要用一次无差别宽查代替取舍；但不得因为上下文预算放弃关键记录。
   - 一个未改变 Family 身份的 Create 不设固定 Family 摘要、维度查询或 record 深读额度。继续
     定向查询，直到技能职责、轮转、资源、防御、装备/天赋协同、关键条件、失败场景和验证任务
     获得足够覆盖。working checkpoint 只阻止上下文压缩后原样重放同一个 query/receipt；它不
     能阻止为新发现的缺口、歧义或候选取舍继续查询。
   - 精确 Family 无命中、有效深度记录过少，或候选在资源、防御、轮转、机制链等具体设计维度仍有
     缺口时，执行第二次定向召回：同主技能跨升华查询只传主技能 key；机制缺口查询使用
     `include_transferable=true` 和对应的 canonical `research_axes`。检查独立返回的
     `transferablePatterns`，不要把它们写成当前 Family 的成熟经验。
   - Family 知识始终优先于公用/跨流派知识（scopeWeight 分层与 transferable 通道以 AGENTS.md 为准）。
   - 深读 `recordKind`、`conditions`、`failureConditions`、`criticalPremiseDigest` 和
     `typedPayload`；紧凑响应只省略重复字段，不截断命中结果，遇到具体歧义或需要被省略字段时
     可切换完整响应。将 `supportPackages` 作为归属明确的辅助候选并交给当前版本 PoB/
     `mcp__poe_build__optimize_supports` 验证；将 `gearResponsibilities` 转成装备职责而不是照抄来源物品；将
     `ascendancyResponsibilities` 用作升华节点取舍依据；将 `resourceMechanisms` 和轮转/机制链
     转成资源预算、失效条件与 Judge 分状态检查。新字段提供设计证据，不授权程序自动组装 BD。
   - 深读记录的 `component_keys` 中的 `unique:` / `item_base:` 组件是 family 声明的暗金/底材
     候选：用 `mcp__poe_knowledge__get_unique` 读全文核对机制，再按流程用 `mcp__poe_build__equip_item` / `mcp__poe_build__equip_jewel` 实测 delta，
     不能因为默认走稀有装工具链就忽略它们。family 未提及暗金不代表"不需要"，只能说明该
     family 没有把暗金作为关键组件；仍应主动评估一次（见第 5 步的 unique 评估轮）。
   - `case_observation` 只可作为当前候选的待验证假设；只有更高证据等级才能支持跨案例的一般性
     结论。采用涉及暗金、天赋、触发、转换或资源交互的结论前，必须用当前静态事实或机制工具
     复核其前提；resolver 成功只证明组件存在，不证明机制解释正确。矛盾项应标为 `rejected`，
     不能仅保留 caveat 后继续当作设计依据。所有记忆仍需经图、PoB 和 Judge 验证合法性与数值。
   - 在 `researchMemoryUse` 中记录查询引用、命中的 Family/record/pattern/edge，以及每条被采用、
     保留或拒绝的结论如何影响候选。若定向查询没有命中，显式使用
     `retrievalOutcome="no_matching_memory"` 和 `noMatchReason`，不能伪造引用。目标等级低于 70
     或 Research 无 Family 命中时，允许 Agent 联网研究与模型知识作为设计主源；≥70 且命中
     Family 时仍以 Family 为身份与设计权威，联网证据只作补充、结论不替换 Family 结论。
   - 普通 Create 确认精确 `buildFamilyKey`、目标等级和当前版本后，调用
     `mcp__poe_knowledge__query_public_learning_memory(family_key, target_level, version_context, dimensions=None,
     limit=8)`。同时阅读 lesson、`correctionsAndDoNotRepeat` 和版本不匹配的 stale 提示；lesson
     必须再经当前图、机制、PoB 和 Judge 验证。普通 Create 不填写 Phase 7 专用的
     `learningMemoryUse`，只在安全摘要的来源/注意事项中引用实际采用的 lesson ID。
   `--no-memory` 模式不得调用 Research 或 Learning Memory，候选里的 `memoryReferences` 必须为空、
   `researchMemoryUse` 必须省略，`researchMemoryRef` 使用 `disabled:no_memory_baseline`。
   对照学习盲测模式在 Research 查询后按 [blind-mode.md](references/blind-mode.md) 调用
   `mcp__poe_learning__query_learning_memory`（claim 绑定、revision 处理与 lesson 决策见该文件）。
5. 使用 `mcp__poe_build__apply_build_mutation_batch(batch_kind=..., ...)` 把 Agent 已经决定的机械操作按职能拆成
   小事务：`bootstrap` 只设置 `mcp__poe_build__new_build`（可选首项）、职业和等级；`mechanism_shell` 设置唯一
   主技能、必要副技能和显式武器槽；随后按需使用 `skill_loadout`、`passive_delta`、
   `required_gear`、`ordinary_gear` 和单次 `config`。不得把整个 BD 混进一个批次。只有以
   `mcp__poe_build__new_build` 开始的 bootstrap 可省略 `expected_state_hash`；其余事务必须使用上一批
   `outputStateHash`。装备和珠宝必须传显式 slot/socket。批次不做搜索或优化，也不能包含需要
   新 skill-group fingerprint 才能决定的编辑。失败只回滚当前职能事务；仅当
   `rolledBack=true` 才继续；`recoveryRequired=true` 后服务端会拒绝普通事务，只能以
   `mcp__poe_build__new_build` bootstrap 显式恢复。批次槽位白名单以 `server/compute/mutation_batch.py` 为准，
   实测要点：`mechanism_shell` 每个批次必须恰含一次 `set_main_skill` 且只能初始化一次（后续
   副技能用 `skill_loadout`）；`required_gear` 只允许武器槽（Weapon 1/2 及 Swap）；`ordinary_gear`
   允许武器槽+Helmet/Body Armour/Gloves/Boots/Belt/Amulet/Ring 1/2/Flask 1/2/Charm 1-3；
   **箭袋（Quiver）不在任何批次白名单**，引擎把它映射为 `Weapon 2` 槽（completeness 层叫
   `Quiver`），只能走独立 `mcp__poe_build__equip_item` 且不能显式传 `slot="Quiver"`（省略 slot 自动识别）。
   独立 compute/equip 工具（`mcp__poe_build__equip_item`、`mcp__poe_build__remove_skill_group`、`mcp__poe_build__replace_skill_group`、
   `mcp__poe_build__set_config`、`mcp__poe_build__apply_combat_profile` 等）与批次共享同一活动构筑、同样会改变 state hash，
   之后第一批次必须用该工具返回的最新 hash（`build_state_conflict` 提示 actualStateHash）；
   `mcp__poe_build__apply_combat_profile` 等 config 变更不改 semantic hash 但改数值，读取前仍以工具返回为准。
    然后把候选方向落实成当前请求所需的完整活动构筑。至少实际
    设置职业、升华、等级、主技能和辅助技能、其他技能组、装备、天赋和
    战斗配置，并检查属性、抗性、Spirit 与资源状态。不能拿只有职业和主技能的空骨架去验收。
    主动形成客观可执行的输出技能包：说明主技能如何清图，稀有怪/Boss 由主技能、独立单体技能或
    setup/payoff 组合中的哪一部分处理，并检查当前等级已可获得的精魂/保留技能能否提供伤害、
    清图、资源或防御协同。资料没有主动提到精魂技能时，不能自动理解成“不需要”；应继续按主技能
    和职业定向搜索常见精魂/保留搭配，再用 corpus、机制和 PoB 核对可用等级、Spirit 需求和实际
    作用。若本阶段确实没有合适选项，可以保留 Spirit、使用非精魂副技能/标记/诅咒等替代，并写清
    理由。这里是软设计要求，不增加固定技能数量、Spirit 保留量、DPS 阈值或新的 Judge/Lifecycle
    硬失败。
   当前 Create 禁止调用 `mcp__poe_build__optimize_build`，也禁止用 `mcp__poe_build__optimize_passives(reset=true, points=0)` 做
   全局树重排；允许针对明确缺口或高影响质量探索使用局部 `mcp__poe_build__optimize_supports`、单槽装备工具
   以及手工/定向天赋节点。
   `mcp__poe_build__search_passives`、`mcp__poe_knowledge__search_mods` 和 `mcp__poe_knowledge__search_items` 使用精确 query；不得设置固定候选条数
   上限，也不得把默认返回量误解为最多只能查看这些结果。从候选中选定对象后使用
   `mcp__poe_knowledge__get_passive`、`mcp__poe_knowledge__get_item` 或对应精确详情工具；必要时扩大结果或调整查询，不能因速度放弃
   可能决定构筑质量的候选。
   先快速形成机制完整、合法且资源闭环的基础版本，再固定执行一次主动质量收尾：比较高影响
   武器、辅助组合、天赋路径、珠宝、符文/灵魂核心和战斗配置。Judge、checkpoint 或 lifecycle
   报警不是调用 `mcp__poe_build__plan_gear`、`mcp__poe_build__craft_item`、`mcp__poe_build__optimize_item`、`mcp__poe_build__optimize_jewel`、
   `mcp__poe_build__optimize_supports` 或局部 `mcp__poe_build__optimize_passives` 的前提；只要探索可能显著改善伤害、防御、
   续航、操作或装备可行性即可。只复用同一 state hash、同一目标和同一参数的完全相同结果，
   不限制有新假设、新目标或新状态的比较。终局/巅峰目标可在有诊断价值时调用
   `mcp__poe_build__pinnacle_readiness`；剧情阶段不得被其终局门槛驱动。
    质量收尾必须包含一次暗金评估轮：先调用 `mcp__poe_build__relevant_uniques`（按活动主技能 scaling 匹配
    unique 与 unique jewel 候选），再结合 family 记录深读得到的 `unique:` 组件，用
    `mcp__poe_knowledge__search_uniques`/`mcp__poe_knowledge__get_unique` 读全文核对机制；对确有机制收益的候选用 `mcp__poe_build__equip_item` /
    `mcp__poe_build__equip_jewel` 实测 delta，数值以引擎为准，并用 `mcp__poe_knowledge__get_prices` 把核心暗金的价格/获取难度写入
    注意事项。对 unique/radius jewel（含 Time-Lost 系列）候选必须做位置化评估：先
    `mcp__poe_build__alloc_passive` 分配候选 socket（`mcp__poe_build__list_jewel_sockets` 查看），再用 `mcp__poe_build__evaluate_jewel_socket`
    遍历各空 socket 比较 radius 增益（radius 内已分配天赋决定效果），选最佳位置后再
    `mcp__poe_build__equip_jewel` 提交；普通 rare jewel 仍用 `mcp__poe_build__optimize_jewel`。注意语料 unique jewel 表缺
    PoE2 Time-Lost 系列且 Historic timeless jewels 被排除（conquered 引擎空规则），候选文本
    需人工提供或从引擎读回核对。暗金不是稀有装的替代品而是机制件：不要只因为"当前装备稀有装"
    就跳过评估，也不要机械套用不符合机制前提的暗金。
   装备目标必须匹配当前阶段：剧情/开荒使用 `mcp__poe_build__plan_gear(stage="campaign")`，刚进图使用
   `stage="maps_entry"`，终局才使用 `stage="endgame"`。元素抗性仍按阶段合法性补足；非 CI 混沌抗
   默认目标分别是 0%、30%、60%，不是所有阶段都强行 75%。达到阶段目标后，应把后缀留给技能
   等级、输出、属性、资源、移速或其他实际缺口；只有明确内容需求才覆盖到 75%。
   `mcp__poe_build__scaffold_gear` 只能让中途骨架可计算，所有 `Scaffold ...` 占位物品必须在最终评估前替换。
   最终黄装必须带当前阶段合理的 `Item Level`，底材需求等级不能超过角色等级，词缀必须来自该
   物品等级可用池。不要为了面板分数把剧情角色穿上终局底材或默认 ilvl 82 黄装。
   未显式写等级的主动宝石会自动使用当前角色可合法装备的最高基础等级；显式等级超过角色需求时
   工具会回滚。最终仍要复读宝石等级。合法性只检查基础宝石等级，装备或天赋的 `+levels` 可以把
   计算等级继续提高，不应为此降低基础宝石等级。
   若候选方向依赖武器切换或武器组天赋：当前 MCP 工具不支持按武器组分别分配天赋与分别评分
   （`mcp__poe_build__alloc_passive` 无 weapon set 参数），只能按单状态评估；单状态 DPS 不能当作双状态强信号，
   输出 caveat「weapon-set 切换机制未按 State_A/State_B 分别验证」（AGENTS 规则：dual-state
   仅 limited reward）。不要为了单状态数字放弃合理的双状态设计；用户明确要求 Boss 切换流时，
   保留设计并说明验证限制。
6. 补齐真实装备系统，而不是只填十个基础装备槽：
   - 实际装备当前阶段生命药剂和魔力药剂；
   - 根据腰带提供的护符槽选择并装备护符，或明确说明为什么当前阶段没有可用护符槽；
   - 调用 `mcp__poe_build__list_jewel_sockets`，由你判断当前阶段是否值得投入天赋珠宝；分配了珠宝孔就必须用
     `mcp__poe_build__optimize_jewel` / `mcp__poe_build__equip_jewel` 填入真实可用珠宝，决定不投入时记录理由；
   - 对可镶嵌装备检查符文/灵魂核心。剧情阶段只使用阶段可获得、预算合理且确有作用的方案，
     不要机械套用带 Perfect Essence 和腐化的终局 `mcp__poe_build__craft_item` 结果；不使用时记录理由。
7. 调用一次 `mcp__poe_build__inspect_generation_checkpoint(strict_mode=<本次反馈模式>)`。它按语义 `build_state_hash` 合并
   completeness、preflight、有界 stats 和 defenses；同一状态重复调用会复用结果。修复其中
   completeness 的硬失败。`Scaffold ...` 占位装备和 rare/magic 黄装缺少 `Item Level` 是两项
   确定性 Create 硬门槛，在 hard-only 下也必须修复；它们会在 Judge 启动前返回
   `attemptConsumed=false`。默认 hard-only 不返回其余质量提示；装备完整性和主动质量收尾仍由本流程
   既定职责检查，不能把“没有 advisory”当成已经完善。严格模式下才对符文/灵魂核心、天赋珠宝、
   药剂和护符等非硬性提示逐项处理或记录明确设计理由。这个工具不会替你设计
   BD；不能仅因为 Judge 数值高就跳过。黄装必须通过前后缀数量、词缀组排他和词缀物品等级
   检查，不能用理论上不存在的黄装抬高伤害或防御数值。主动宝石超过角色等级需求同样是硬失败。
   攻击类主技能（非法术）还必须检查 checkpoint stats 的 `HitChance`：终局目标低于约 95% 时，
   补充命中来源（装备词缀/天赋/Unique）后再进入正式 Judge，达标情况写入验收摘要。法术技能
   无命中判定，跳过此项并说明原因，不要机械执行。
8. 使用 checkpoint 的 `buildSummary` 复读职业、升华、等级和主技能；只有需要完整局部诊断时
   再单独调用 `mcp__poe_build__get_build()`，不要机械重复整份 readback。发现遗留状态或缺项时继续修正。
9. 修复 checkpoint `preflight.blockingIssues` 后才进入正式 Judge；完全重复的
    enabled skill group、多主动技能组、重复辅助或 completeness hard failure 不应消耗一次 attempt。
    严格模式返回的 advisories 仍由 Agent 判断和记录；默认模式不得重建这些主观建议。
    使用生命周期 gate 时，调参期间继续使用 checkpoint；每个正式 Judge attempt
    最多在其前调用一次活动快照
    `mcp__poe_build__verify_lifecycle_stage(..., detail="compact", strict_mode=<本次反馈模式>)`。只有该 gate 暴露真实阻断并且构筑 state hash
    已改变，下一正式 attempt 才能再次调用。artifact 保存后另调用且只调用一次
    `mcp__poe_build__verify_lifecycle_stage(..., artifact_id=..., detail="compact", strict_mode=<本次反馈模式>)` 生成可信回执。不要在每次装备、
    天赋或辅助微调后重复跑 lifecycle，也不要为了看完整对象使用 `detail="full"`。
10. 正式评估前先固化战斗假设：对终局/Boss 目标调用一次
    `mcp__poe_build__apply_combat_profile(tier=<与用户目标一致>，...开关...)`（或用 `mcp__poe_build__set_config` 传相同 key）
    设置敌方条件并读取返回的 assumed 清单。默认值全开，**只保留构筑实际能产生的假设**：
    `shocked` 需要构筑能施加感电、`cursed` 需要实际配置的诅咒技能、power/frenzy charges 需要
    生成手段、`full_es` 需要 ES 构建——无法产生的就关闭，否则 DPS 会被不可能维持的效果抬高；
    不调用时这些条件全部关闭，对依赖感电/诅咒/充能的 BD 属于下限值，不能当作目标强度。
    把 assumed 清单原样记入本轮 `failureAudit.summary` 与 `toolReferences`；战斗配置属于构筑
    的一部分，后续重试沿用同一假设，不能为通过 Judge 临时切换开关。
    然后调用 `mcp__poe_build__evaluate_generation_candidate(run_id, run_token, candidate_id, version_context,
    strict_mode=<本次反馈模式>)`。这个工具
    会捕获当前 PoB 状态，在独立 Judge 引擎中运行正式评估，并把可信结果绑定到本次运行。不要用
    `mcp__poe_build__evaluate_build`、`mcp__poe_build__pinnacle_readiness` 或 Agent 自己整理的分数冒充正式 Judge。
11. 将该工具返回的 `attemptIndex` 及安全 Judge 结论保留。可信 `transientBuildState` 和
    `judgeAdvisoryReport` 已写入本次 receipt，最终 `agent-output.json` 可以省略这两份重复内容；
    helper 会按 attempt index 补全并严格核对。工具
   拒绝空骨架时继续完成构筑；工具返回 Judge 执行错误时保留错误报告，不要自行改写成已评估。
   `trustedEvaluation` 只表示活动快照和 Judge 结果由程序绑定；`versionContextTrusted=false` 表示
   版本上下文仍需与本次 `mcp__poe_knowledge__get_freshness_report` 返回核对，不能借此冒充当前赛季强验证。
12. 对本轮结果做简短失败核验：区分真实构筑失败、PoB/Judge 建模缺口、Judge 选错技能、工具或
    数据缺口、混合问题，或者当前没有实质失败。只保存结论摘要、修改计划和保留的注意事项，
    不保存逐步推理。
    `passed=true` 只表示确定性合法性通过，不等于候选值得推荐。默认 hard-only 只处理
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
    强度，也不得把工具能力不足说成 BD 非法；保留该设计并明确需要机制参考或实战核验。
    对“开荒顺畅”请求，还必须检查清图职责、单体/Boss 职责和资源恢复；不能只证明三抗、属性和
    插槽合法就接受。若一个技能同时承担清图与单体，必须有 PoB/机制证据或明确实战 caveat；否则
    应补充独立单体技能/组合，或把结果降级为仅清图方向。
    接近剧情结束或进入异界时，主输出仍只有零到一个辅助技能属于高优先级完整度提醒。调用
    `mcp__poe_build__optimize_supports` 测试阶段合理的组合，或说明少辅助为何是有意设计；它不是合法性硬规则。
    不要用“总蓝量至少是单次耗蓝的固定倍数”删辅助。续航应结合未保留蓝量、使用频率、每秒
    恢复、药剂、击回/偷取和实际技能轮转判断。若 `ManaCost × Speed` 已高于回复、偷取与击回，
    且只有魔力瓶补缺口，必须明确写成“持续攻击依赖魔力瓶，Boss 长战存在断蓝风险”，并保留
    每秒缺口与满蓝维持时间；不能再降级成笼统“建议实测”。只有指标缺失时才标记待实测。
     新生成 80 级及以上候选的终局抗性门槛（火/冰/电各≥60%、非 CI 混沌≥30%，CI 豁免混沌）与
     生命周期分级门槛（45-64 各 30%、65-79 各 50%、80-89 各 60%，90+ 无额外
     Lifecycle 门槛）以 AGENTS.md 不可协商规则为准，按活动 PoB 实际等级计算，不能因 stage 名称
     或调用者提示改变档位；`resists_capped` 只是兼容 check ID，不代表必须 75% 满抗。
13. 如果 Judge 未通过，在当前会话、当前 `runId`
    和当前需求上下文中直接修改
    活动构筑，再次以相同 `strict_mode` 调用 `mcp__poe_build__evaluate_generation_candidate`。严格模式下存在
    `playabilityFailures` 且有明确可修正项时也可重试；默认 hard-only 不得因隐藏的主观评价改造
    构筑。不要重新调用 `mcp__poe_build__start_generation_run`，也不要要求用户
    重复需求。最多重试两轮；程序返回 `retry_limit_reached` 后必须停止。
    如果修正改变了升华或核心主技能，必须先重新解析身份并重新调用 `mcp__poe_knowledge__query_research_memory`；新一轮
    `researchMemoryUse` 和 `versionContext.researchMemoryRef` 必须包含新的 `dedupeQueryRef`。只调整
    supports、装备数值、天赋路径或配置时不要求重复查询。
14. 顶层只写一次完整最终 `prototypeBuildCandidate`。每轮 compact `generationAttempts` 只写
    `attemptIndex`、`prototypeBuildCandidate: {candidateId}` 和 `failureAudit`；不要在 attempt 中重复
    完整候选。非最后一轮的 `retryDecision` 必须是 `retry`；最后一轮必须是 `accept` 或带明确停止
    原因的 `stop`。helper 按 attempt index、candidateId、可信 receipt 和 artifact-selection 补全
    临时状态与 Judge 报告；同一可信 candidateId 不再比较两份重复候选正文。
15. 每个正式 Judge 已评估、`passed=true`、没有 `hardFailures` 且通过共享硬合法性审计的 attempt
    都是可保护的 passing baseline。完成主动质量收尾后，由 Agent 选择实际采用的 passing attempt，
    并在 `mcp__poe_build__complete_generation_review` 前调用
    `mcp__poe_build__save_final_build_artifact(run_id, run_token, candidate_id, attempt_index)`。新候选更好且合法时选择
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
    严格模式下，`playabilityFailures`、`qualityBand="barely_playable"`、目标维度为 0、
    `scoreApplicability="unavailable"` 和其他非硬性 Judge 警告不阻止保存与导出。它们仍必须原样
    出现在用户可见 Judge 结论中，并将结果称为弱原型/待验证候选，不能称为推荐方案或已验证成品。
    默认 hard-only 只说明“主观 Judge 反馈已关闭”，不要输出这些字段或据此降级路线。
16. 把本次生成的安全摘要对象作为 `agent_output` 直接提交给
    `mcp__poe_build__validate_generation_output(run_id, run_token, agent_output)`；它不会消费 run，可以根据返回的
    字段路径修正后重试。通过后把同一份最终对象提交给
    `mcp__poe_build__complete_generation_review(run_id, run_token, agent_output)`。插件在受管用户数据目录中完成
    原子写入和可信 review，不需要也不允许 Agent 自己定位或编辑运行文件。可信快照中每个仍存在
    的 completeness advisory，都必须在
    `completenessAdvisoryDecisions` 中记录 `deferred` 或 `intentionally_unused` 及具体理由；已真正
    处理且不再出现在最终快照中的提示不要保留陈旧决策。最终 PoB XML 由专用 artifact 工具写入
    本地私有存储，不要放入 `agent_output`。
    不得手工删除或改名 `review-result`、`review-consumed`、可信 Judge 回执或运行锁来修复顺序；
    使用 artifact 的受检恢复路径，或按状态机登记失败/重试。
17. 普通单阶段 Create 在 artifact 保存成功后，只调用一次
    `mcp__poe_build__export_final_build_package(artifact_id, name, author, description)`。这个工具固定尝试导出 PoB XML、
     PoB 导入码文本和官方 `.build`，并返回完整 `artifacts` 清单。不要再自行分别调用多个导出工具
     拼接交付结果；除非用户明确只补导某一种格式。
     非 Blind Create 只有在三项全部成功且返回 `runtimeCleanupReady=true` 后，才调用
    `mcp__poe_build__cleanup_completed_task_runtime(task_kind="generation", task_id=artifact_id)`。部分导出时保留现场
    供补导；Blind Create 的 artifact 仍要进入 Compare，由 Learning campaign 完成后统一清理。
18. 向用户展示自然语言构筑结果、Judge 结论、`lifecycleEvidenceCoverage`、内部重试改了什么、
    最终 artifact id，并逐项列出
    `mcp__poe_build__export_final_build_package.artifacts` 中的全部三项。成功项必须给路径，失败项必须给 errorCode；
    不得省略任何一项。还必须逐项展示 compact review 的 `requiredUserDisclosures`，不能把符文、
    灵魂核心、珠宝、药剂或护符的暂缓/不用理由留在内部文件。不要展示 PoB XML 或导入码原文。

对照学习盲测模式完成 artifact 后，按 [blind-mode.md](references/blind-mode.md) 用本任务 claim
调用 `mcp__poe_learning__submit_learning_create_result`（identity records、目标等级、artifact id、generated
evidence、learningMemoryUse；Family/等级回读不一致时让案例失败）。

内部重试不等于重新生成整个上下文。优先在当前活动构筑上做针对性修正；只有 Agent 判断设计方向
本身需要推倒重建时，才可以在同一个 `runId` 内调用 `mcp__poe_build__new_build` 重新搭建。技能组局部问题优先使用
`mcp__poe_build__list_skill_groups` 后的强类型原子修改，不要因为缺少精确编辑而重建整份 PoB。无论哪种方式，前一轮
可信快照都已由程序保存，不能覆盖或伪造。

如果 `mcp__poe_knowledge__get_freshness_report` 的实际 MCP 调用返回“工具不存在”或宿主明确拒绝调用，才可以判断
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
过期 PoB 模式下仍必须完成 `mcp__poe_build__new_build`、活动构筑、evaluate 和验收包流程，结论同时给出设计判断、
过期诊断和版本限制。完整规则以 AGENTS.md 为准。

## 常用 MCP 工具清单

宿主中完整工具名带 server 前缀（如 `mcp__poe_knowledge__query_research_memory`、
`mcp__poe_build__get_build_stats`），下面只写末尾名称；必须通过 MCP 工具调用，
不能用 PowerShell 搜索仓库文件代替。Create 只连接 knowledge + build 两个 server：知识/图/
机制/Research 查询走 `mcp__poe_knowledge__*`，所有 PoB/计算/Judge 工具走
`mcp__poe_build__*`。所有 PoB/计算工具共享同一个活动构筑、**必须串行调用**
（部分优化工具内部临时改状态再恢复，不能按名称推断只读）；只有不接触活动构筑的语料/图/机制/
静态查询可以并行。

**构筑经验记忆**（顺序见工作流第 4 步）：
`mcp__poe_knowledge__query_research_memory`（默认 `detail_level="summary"` + `response_profile="create_compact"`，
精确 Family 检查 `familyRecordCoverage/familyRecordIndex/familyPremiseCatalog`，`limit` 不是总
召回上限）｜`mcp__poe_knowledge__query_public_learning_memory`（普通 Create 用，lesson 必须重新验证）｜
`mcp__poe_learning__query_learning_memory`（仅 referenceBlind 活动 claim）｜`mcp__poe_knowledge__build_advice`/`mcp__poe_knowledge__suggest_build_lifecycle`
（规划启发，补丁敏感事实以 pinned PoB/图/corpus 为准）。

**图与机制**：`mcp__poe_knowledge__graph_tool_query(resolve_graph_component)` 解析稳定组件｜`mcp__poe_knowledge__find_skills`/`mcp__poe_knowledge__get_gem`/
`mcp__poe_knowledge__list_skills_for_level`（等级获取参考候选池，真实等级可用性以引擎校验为准）｜
`mcp__poe_knowledge__find_supports_for`（数值靠计算工具验证）｜`mcp__poe_knowledge__explain_mechanic`/`mcp__poe_knowledge__search_mechanics`｜
`mcp__poe_knowledge__search_items`/`mcp__poe_knowledge__search_uniques`/`mcp__poe_knowledge__get_unique`｜`mcp__poe_build__relevant_uniques`（按主技能匹配 unique + unique
jewel 候选，须读全文并实测后采用）｜`mcp__poe_build__evaluate_jewel_socket`（unique/radius jewel 的 socket 位置化
评估，先 alloc 再评估）｜`mcp__poe_knowledge__search_mods`/`mcp__poe_knowledge__reverse_lookup`｜`mcp__poe_knowledge__list_ascendancies`。

**临时构筑与计算**（顺序/门禁/重试以工作流为准）：
`mcp__poe_build__new_build`/`mcp__poe_build__set_class`/`mcp__poe_build__set_level`/`mcp__poe_build__set_skill` 初始化｜`mcp__poe_build__add_skill_group`/`mcp__poe_build__list_skill_groups`/
`mcp__poe_build__replace_skill_group`/`mcp__poe_build__remove_skill_group`/`mcp__poe_build__set_skill_group_state`（局部修改前重读 fingerprint 与
state hash）｜`mcp__poe_build__apply_build_mutation_batch`（职能小事务、串联 `outputStateHash`、不接受搜索/
optimizer，仅 `rolledBack=true` 表示回滚成功）｜`mcp__poe_build__equip_item`/`mcp__poe_build__equip_jewel`（显式 slot/socket；
`mcp__poe_build__craft_item` 的 `craftReceiptRef` 原样传入）｜`mcp__poe_build__search_passives`/`mcp__poe_build__alloc_passive`/`mcp__poe_build__optimize_supports`/
`mcp__poe_build__plan_gear`/`mcp__poe_build__optimize_item`/`mcp__poe_build__scaffold_gear`/局部 `mcp__poe_build__optimize_passives`｜
`mcp__poe_build__apply_combat_profile`（Boss 战假设：默认 shocked/cursed/charges/full_es 全开，只保留构筑
实际能产生的条件，返回的 assumed 清单须记录）｜
`mcp__poe_build__validate_level_availability`（等级约束参考，非硬门槛，数值以 PoB 读回为准）｜
`mcp__poe_build__inspect_generation_checkpoint`/`mcp__poe_build__get_defenses`/`mcp__poe_build__get_build_stats`/`mcp__poe_build__evaluate_build`/
`mcp__poe_build__pinnacle_readiness`（局部诊断；正式 Judge 只用 `mcp__poe_build__evaluate_generation_candidate`）｜
`mcp__poe_build__start_generation_run`/`mcp__poe_build__validate_generation_output`/`mcp__poe_build__complete_generation_review`（Phase 5 run，
不依赖仓库工作目录）｜`mcp__poe_build__save_final_build_artifact`（先于 complete_review）｜
`mcp__poe_build__list_final_build_artifacts`/`mcp__poe_build__load_final_build_artifact`｜`mcp__poe_build__export_final_build_package`（普通单阶段
交付入口；单格式补导/诊断用 `mcp__poe_build__export_final_pob_artifact`/`mcp__poe_build__export_final_build_artifact`/
`mcp__poe_build__get_build_planner_converter_status`）。`mcp__poe_build__export_build()` 只用于本地临时状态。

`mcp__poe_build__evaluate_generation_candidate` 的 `version_context` 一次提供完整对象，值来自本次 freshness/图/
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
`mcp__poe_build__start_generation_run` 返回的新凭据，禁止复用/改写其他运行的旧 `HumanReviewPacket`；顶层必须
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
- `toolReferences`：每项为对象 `{toolName, queryRef, summary}`；其中
  `mcp__poe_knowledge__query_research_memory` 条目的 `queryRef` 必须覆盖 `researchMemoryUse.dedupeQueryRefs` 全部
  引用，且必须包含一条 `mcp__poe_knowledge__get_freshness_report` 条目（服务端硬性要求）
- `memoryReferences`（可省略；helper 从 typed `researchMemoryUse` 生成完整去重并集）
- `researchMemoryUse`
- `rationaleSummary`
- `versionContext`
- `noRawMaterial`

候选摘要要表达阶段目标、职业壳、主副技能职责、伤害机制、防御、Spirit/资源、装备职责、天赋锚点、
转型门槛和未解决项；清图、单体、触发与条件性附加伤害可由不同技能承担，不要为单一 Judge 数字
压缩合理的多技能组合。`gearRoles`/`passiveAnchorIntents` 只写方向，不复制完整装备表或天赋路径。

普通模式的 `researchMemoryUse` 至少包含：`retrievalOutcome`、`dedupeQueryRefs`、
`componentKeys`、`buildFamilyKeys`、`deepRecordIds`、`patternIds`、`semanticEdgeIds`、
`memoryItemIds`、`insightDecisions` 和可选的 `noMatchReason`。`insightDecisions` 每项使用
`sourceRefs`、`decision`（`adopted` / `caveated` / `rejected`）、`summary` 和 `application`；
`sourceRefs` 必须来自本次命中的安全记忆项。`memoryReferences` 保留兼容，但不必手工复制；
helper 会加入全部 `dedupeQueryRefs` 和实际使用的记忆项 ID；`versionContext.researchMemoryRef`
使用其中一个真实 `dedupeQueryRef`。

**关键约束（receipt 时效与一致性，违反会导致整个 run 无法交付）**：

- `dedupeQueryRefs` 引用的全部 receipt 必须在**当前 Phase 5 run 创建之后**（
  `mcp__poe_build__start_generation_run` 之后）实际查询过——发现/比较阶段的
  旧 receipt 不能用于 evaluate/review。因此普通 Create 的正确顺序是：
  `mcp__poe_build__start_generation_run` → 在 run 内重新做定向 Research 查询（至少覆盖最终采用的全部
  record 与 premise resolution 引用）→ 再 `mcp__poe_build__evaluate_generation_candidate`。
- `mcp__poe_build__evaluate_generation_candidate` 的 `version_context.researchMemoryRef` 必须就是该 run 内
  receipt 之一（绑定后不可更换）。
- `premiseDecisions` 中 `decision="resolved"` 的 `resolutionRefs` 必须属于**本轮 receipt 的
  deepReadRecordIds**（一次 record 深读只返回请求的记录；引用多条记录就一次查全）。
- 顶层 candidate、`generationAttempts[].failureAudit`、`toolFeedbackEvents` 的
  `versionContext` 必须与 Judge receipt 完全一致（`same_version` 含 `researchMemoryRef`）。
- `toolFeedbackEvents` 每项结构：`eventId`、`feedbackType`（枚举：
  `judge_modelability_gap / judge_offense_evidence_gap / judge_score_review_required /
  query_gap / copy_safety_gap / pob_state_gap / tool_usability_gap`）、`summary`、
  `requiresHumanOrTestReview`、`versionContext`、`noRawMaterial`。

对照学习盲测的独立 `learningMemoryUse`（`queryRef`/`recalledLessonIds`/`decisions`，每项含
`lessonId`/`decision`/`application`/`harmfulOrIncorrect`/`observation`）见
[blind-mode.md](references/blind-mode.md)；提交给 `mcp__poe_learning__submit_learning_create_result`，不混入
Research SQLite 引用，也不得写入原始来源信息。

`transientBuildState` 和 `judgeAdvisoryReport` 由 evaluate 的 trusted receipt 按 attempt 补入，
默认不要在 `agent_output` 中重复；显式写入必须与 receipt 完全一致，不得自行生成 `snapshotId`/
`sourceHash`/分数/硬阻断。诊断以 receipt 的 `testedSkillGroups`、`selectedSkill`、
`skillGroupDiagnostics`、`attributeShortfalls` 为准；`pob_main_group` 只是当前计算组，不代表
整个 BD 只能有一个主技能。`feedbackMode="hard_only"` 只用确定性字段；评分/质量档位/caveats/reward
只在显式严格模式下使用。`error` 只表示正式 Judge 调用错误，不能改写成构筑 `hardFailures`。

`generationAttempts` 每项至少包含：

- `attemptIndex`：由 `mcp__poe_build__evaluate_generation_candidate` 返回，从 0 开始，最多为 2；
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

不输出或写入普通报告、聊天、研究记忆：PoB 导入码、原始 XML、完整 URL、账号/角色/profile 细节、
隐藏思维链、完整对话记录、草稿推理。唯一允许持久化完整 PoB XML 的入口是
`mcp__poe_build__save_final_build_artifact`（本系统生成、可信 passing Judge、Agent 明确选中的 attempt，写入本地
私有 artifact store；Agent 不读取/复制/转述其中 XML）。不直接复制第三方完整成熟 BD——约束的是
抄袭与原始材料泄漏，不禁止输出自己设计的技能组合、辅助组合、装备槽位摘要、天赋锚点或转型路线；
helper 会硬拦原始材料和隐私/来源信息。可以输出：安全摘要、字段来源、默认假设、可审查的简短
理由摘要、本地临时状态引用、Judge 摘要和注意事项。

## Phase 5 运行管理工具

`mcp__poe_build__start_generation_run` / `mcp__poe_build__validate_generation_output` / `mcp__poe_build__complete_generation_review` 按工作流
第 2、16 步使用；原样保留返回的 `runContext`、`requestRef`、`promptId`、`packetId` 和
`experimentContext`。运行状态由插件在受管用户数据目录管理，凭据两小时后过期、review 成功后失效。
两个提交工具共用 fail-closed canonicalization：validate 不消费 run，complete 成功后消费；按可信
receipt 补入并核对 Judge 字段、memory lane、attempt 连续性和重试上限；缺少凭据、引用不匹配或
显式字段与 receipt 不一致都会拒绝。`HumanReviewPacket` 只表示材料可进入人工验收，不代表 Judge
或人已认可该 BD；rejected 时按字段错误修正或向用户说明阻塞点。
