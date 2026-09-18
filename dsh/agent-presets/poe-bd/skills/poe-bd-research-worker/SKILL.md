---
name: poe-bd-research-worker
description: Internal explicit-only worker for one leased PoE2 mature-build Research case. Use only when the poe-bd-research Controller supplies an existing opaque runRef; never create or resume a queue.
---

# 最高优先级 输出语言必须与用户一致

**这是本 Skill 的首要交付规则，优先于下文默认示例、模板、参考资料与宿主适配说明的语言。**
最终面向用户的表述跟随用户本次请求的自然语言；只有用户明确指定另一种输出语言时才覆盖。
标题、摘要、正文、表格、图表标签、注意事项、交付文件中的说明与会话结论都使用同一目标语言。
中英混合请求以表达需求的主要语言为准，不因 PoB、网页或组件名是英文而切换整份产物语言；
只有确实无法判断时才澄清。目标语言的官方专名未经核实时保留原名，周围解释仍使用目标语言。
工具名、schema 字段/枚举、stable key、回执、路径与代码不翻译；这条规则不改写既有知识记录，
也不改变 typed 合同。交付前检查实际正文语言，不能只修改 language 元数据。
委派、续聊或自动流程必须传递原始用户请求及其目标语言，接收任务的 Agent 沿用该选择。

> **DSH 适配说明**：本 skill 运行在 DeepSeek Harness。所有 poe-bd 能力都是 MCP
> 工具，完整名带 `mcp__poe_<server>__` 前缀（例如
> `mcp__poe_knowledge__query_research_memory`、`mcp__poe_build__get_build_stats`），
> 下文只写末尾名称。加载本 skill 使用 DSH 的 `skill` 工具，不存在 `/poe-bd-*`
> 斜杠命令。工具清单以当前会话实际注册为准，不要猜测未注册的工具名。
> **DSH Worker**：只允许 Controller 显式用 `skill` 工具加载本 skill；从 assignment
> 取得 opaque runRef 后使用 `mcp__poe_research__*` typed 工具执行单案流程，不使用 shell，
> 不创建或恢复 queue。assignment 必须包含用户原始研究请求和授权上下文。

# PoE BD Research Worker

只接受 `poe-bd-research` Controller 显式派发的既有 `runRef`，原子 claim 一案，完成证据读取、研究、
safe review、校验和 accept 后停止。

## Assignment 与运行边界

当前 fork 必须含用户本次研究请求/授权的真实上下文及 opaque `research-run:...` 引用。
缺少任一项或不是 Controller 显式派发时，返回 `worker_assignment_missing` 并停止；
不得自行发现其他仓库、创建/恢复 queue、询问运行模式或回退为主会话研究。

- 只处理一个 claim；完成或失败后不得领取第二案、嵌套委派或执行 cleanup。
- 本次是产品运行，不修改源码、测试、文档、schema、安装配置、queue、review 文件或其他运行态。
  `mcp__poe_research__initialize_research_review` 返回 safe review 对象，只在模型工作状态中修改，再完整提交给 typed 工具；
  不得用 shell/file tool 编辑运行态。
- 原始 PoB/XML 只留在 quarantine 与 lease-bound transient packet，不进入聊天、safe review 或 durable memory。

## 工具表面

案例运行态管理只用 Research MCP 的 `mcp__poe_research__claim_research_case / mcp__poe_research__inspect_research_case / mcp__poe_research__read_research_case /
mcp__poe_research__search_research_case / mcp__poe_research__get_research_review_contract / mcp__poe_research__initialize_research_review / mcp__poe_research__validate_research_review /
mcp__poe_research__accept_research_review / mcp__poe_research__retry_research_review`。

MCP 结果先检查 `isError`；错误响应可能只有 `content` 而没有 `structuredContent`，须保留并审读
其中的 safe error，不把缺失字段当作空证据。通过 JavaScript 包装调用时，不得将 `undefined`
传给 `store` 等序列化接口，以免二次序列化失败掩盖原始工具错误。

研究另用 `mcp__poe_knowledge__query_research_memory`、`mcp__poe_knowledge__graph_tool_query`、本地 `mcp__poe_knowledge__explain_mechanic/mcp__poe_knowledge__search_mechanics`
和实时 `mcp__poe_knowledge__lookup_mechanic`。图组件发现与解析是同一MCP工具的两个子操作，依次调用
`mcp__poe_knowledge__graph_tool_query(tool_name="search_graph_components", payload=...)` 和
`mcp__poe_knowledge__graph_tool_query(tool_name="resolve_graph_component", payload=...)`。
解析到天赋 stable key 后，用 `mcp__poe_knowledge__graph_tool_query(tool_name="explain_graph_evidence",
payload={"node_key":"<stable key>"})` 深读 `statTexts` 与来源；该证据只证明静态效果，不证明已应用。
需要发现操作时用 `tool_name="list_graph_tools", payload={}`；指定
`payload={"query_family":"<目录返回的名称>"}` 读取其完整参数 schema。不得猜内部函数名。
子操作名不是独立MCP工具，不能因其单独discovery未命中就报告缺工具。精确discovery只针对真实MCP
工具名；实际入口缺失才返回safe failure，不根据首屏断言不可用，不搜索仓库/插件路径，也不回退 shell CLI。

## 研究方法与证据

- 来源 BD 不保证正确。辅助经精确来源绑定的整组校验确认不兼容后，从知识正文、组件、
  `supportPackages` 和语义边中排除；不另写不兼容声明、`open_question` 或警告记录。
  若该源组所有辅助均确认不兼容，在 `sourceSkillGroupReviews` 使用
  `supportDisposition=excluded_incompatible`；混合组仍为 `packaged`，只打包有效辅助。
  工具保留排除审核事实，不要求把来源错误存成知识，也不为凑辅助数量补造组件。
  未解析、模型未知、缺少核验与未证实关系不能当作已确认不兼容。
- 研究质量优先于速度和上下文预算。完整读取要求的分区，并独立盘点每个启用容器，填写
  `sourceSkillGroupReviews`。Family 主技能、核心副技能和结论依赖的高影响组保留根技能及 socketed
  items 中有效的辅助；已确认排除项不形成覆盖缺口。其他组也明确处置。真实 `source_coverage_gap` 保持 partial；低影响、内部 ID 或无法唯一解析
  的组可 needs_followup/caveat，不静默丢弃或机械否定整案。
- 技能、天赋与装备效果来自案例证据或 typed 事实。有价值的推断明确标为推断，
  不能把模型记忆中的免疫、转换、触发或缩放写成已证实事实。
  装备声明授予的节点须解析并深读实际效果；声明授予不等于 PoB 已应用。特殊宝石身份由精确
  gem ID 的静态事实确认，辅助仍用 support_modifier，不依赖正文中的英文 unique/lineage 字样。
- `mcp__poe_knowledge__get_gem.effectDetails` 按精确 effect 分别提供正文、类型约束和 statSet；由数值/模板投影的描述有
  `descriptionOrigin=stat_text_projection`，不是原始简述。授予的同名增益没有明确 effect ID/数值时
  继续查来源，不能从名字或 stat ID 猜持续时间、恢复量，也不能把静态类型兼容当实战已应用。
- PoB 字段语义：`enableGlobal1` / `enableGlobal2` 是单颗 gem 的 granted-effect 开关，绝不是
  武器组标志；`weaponSetScope` 才是技能组级字段，取值为 `global` / `weapon_set_1` /
  `weapon_set_2`。不得根据任一 gem 的 global-effect 开关推断武器切换、轮转状态或插槽关系。
- 分别重建主/副输出与辅助、触发/生成-兑现关系、可执行轮转/爆发窗口及无小怪/Boss 变体、装备槽职责、
  暗金必要性/黄装替代/机会成本、核心天赋/升华/珠宝/武器组局部结构、资源闭环、防御层、失效条件和
  PoB/Judge 未建模部分。不要只复述属性共现或“仍需验证”。
- 保留跨版本 Family 稳定身份，正常 Research 只研究最新样本；历史知识照常召回并显示目标适用性。
  来源 patch 与模型认证版本分开，不能重标历史样本、把历史样本数算作当期证据或把补丁兼容复核当作
  新样本。相同正文/条件/typed payload 由服务共享；`contentRevisionRef` 不能替代记录身份或授权另一来源。
  明确失效只限制目标版本，待核知识保留验证任务；新增或修正结论仍走本 Worker typed review/accept。

## 单案流程

1. 调用 `mcp__poe_research__claim_research_case(run_ref=<runRef>)`，保存同一 `sampleId + leaseToken`。

   `worker_capacity_reached / no_pending_cases` 无 sampleId，原样返回后停止。`claim_packet_failed`
   已有 sampleId：返回 safe outcome；`leaseReleased=true` 表示回到可调度队列，`recoveryRequired=true`
   时不得重试或猜状态，交 Controller 停止补位并报告。
   `supplement=true` 时按 supplementContext，只补同 case 缺口；保持原 researchGroup/Family，
   必须产生 `created+updated >= 1`。
   focus包含gapRef时，返回每项实际解决范围与新writeReceipt中的记录映射；不因补录有增益就声明
   父案完整。逐项关闭由Controller读证据后提交，Worker不领取或创建额外任务。

2. 同一 runRef/lease 先 `mcp__poe_research__inspect_research_case`，按返回顺序分页 `mcp__poe_research__read_research_case` 读完全部分区。
   search 只定位线索，不能替代 read。`complete=false` 时只用返回的 `nextCursor` 续页，不能自行
   `cursor+limit`：字符预算可能使本页条数少于 limit。先独立重建案例，再查询 Memory；
   `config-sets`分页提供配置身份；若返回`evidence_fragment`，按同一源条目及fragment顺序完整重组
   后再解释，片段或紧凑身份摘要不能当成完整配置证据。
   身份组件经 `search_graph_components` → `resolve_graph_component` 确认 stable key 后用于比较。

   Research 使用 `response_profile="full"`，不能用会选单案例授权 lane 的 `create_compact`。
   Family 首查 `detail_level="summary"`，检查 `familyRecordCoverage / familyRecordIndex /
   familyPremiseCatalog`；选定后按 index 的 record_ids 用
   `detail_level="record" + response_profile="full"` 深读至关键 premise、失败条件和验证任务闭合，
   不设固定深读额度。`primary_skill_key` 接收 skill:/gem:；`build_family_keys` 只接收查询已返回的 `bf-...`，
   未知时省略，不能填技能 key。

3. 初步研究后调用 `mcp__poe_research__get_research_review_contract`，以当前 lease 的 mandatoryChecks、枚举、schema、
   模板、兼容矩阵与 rules 为精确事实源，不从 Skill 猜字段或固定检查数量。
   高风险因果结论先查本地 mechanics，再用 `mcp__poe_knowledge__lookup_mechanic` 校对。全文搜索只发现候选，选中后按
   精确标题读正文，在 mechanicAudit 写 supports/contradicts/silent 与 relevanceReason；页面身份
   不授权语义，Wiki 不替代来源实例或其他独立 corroboration。Candidate Pattern 按合同填写
   `claimScopeReview`，确认当前案例证据/条件迁移范围，不依赖关键词门禁。
   Wiki 返回 `errorCode=rate_limited` 时遵循 `retryAfterSeconds/retryAt` 建议；工具不自动等待或重试，
   建议时间不保证届时成功，不立即反复请求同页。

4. 调用 `mcp__poe_research__initialize_research_review`，在返回对象中填写研究。`already_exists` 返回既有工作，不能清空重建。
   具体字段形状与枚举遵循合同，填写时守住以下语义：

   每条记录的`sourceClaimKey`默认`default`；同来源同主题的并存条件分支用稳定的不同key，修订时复用
   原key，可从record-detail的`sourceClaims`核对。不要随机换key制造新分支，它不会增加独立来源证据。
   同标题的不同knowledgeKey默认并存。跨主题纠正必须显式传`sourceClaimRevision`，其
   `knowledgeKey/recordId/projectionHash`来自本来源当前记录深读；不能用标题、其他来源回执或旧指纹猜修订。
   正文中文通常最多400字、英文250词；仅不可拆分的同一机制链可说明 `lengthExceptionReason`。
   `recordContentLimits` 显示单位与拆分规则，不为绕长度限制创建重复身份或随机换来源声明key。

   - supportPackages 表达真实物理插槽归属，不能把 PoB 计算作用对象当作根技能。按 skill-groups 的
     sourceGroupRef、rootSkillRef 和 socketedItemRefs 绑定实际实例；host/payload 关系另用组件与机制记录表达。
     逐记录执行合同的supportPackages覆盖要求，不能用另一条记录或研究组总体的包替代当前记录。
   - gearResponsibilities 只归因组件静态文本直接提供的职责；实例词缀、插入物或转换归因真实来源。
     无图节点的黄装按合同显式声明内容型装备证据，在正文写槽位、目标词条与档位。
   - sourceStateScope 区分活动/副武器/未知状态，后两者不能当常驻收益。pobReadbackAudit 按合同绑定
     pob-readback 的真实状态与精确 snapshotRef，数值只说明本 case 活动快照，不外推为 Family 通用值。
     Spirit 账本自洽只证明模型算术，须先核供给与启用状态，不能仅据差额要求修改原 BD；成因按本来源
     验证，不搬用他案遗漏原因。天赋使用现有分池读数，节点条目数不是消费点，缺值不能补零。
     v5 `pob-readback` 的 `reservationLedger` 先给总览，再分页提供逐组/逐effect资源保留明细；
     读取全部行和无损片段，区分当前actor、另一武器组、全武器保留、装备授予免保留与生命替代。
     `nativeReservedBase`可能已包含百分比换算，不再加Percent，不用逐行相加取代原生总账。
     这些编号是导入后的runtime身份；原sourceGroup映射未观察时保持未知，不能按同名或序号猜归并。
     账本不提供每个技能的每次/每秒施法成本；缺失数值保持null，不能变成0或断言原BD非法。
     config 的 `configSetId/isActive/valueType` 保留场景归属；仅 `stateBinding.activeSets` 绑定的
     活动组合支撑当前数值，非活动条件独立研究，身份无效或读回 unavailable 时不混用其他场景。
     配置勾选与 placeholder 仅声明情景，不证明条件已经发生或具备持续覆盖。
   - 同主题修订沿用稳定来源声明；跨主题使用上述显式修订绑定。废弃旧结论说明失效理由，不能凭同名覆盖。

5. 在 typed validation 和正式 accept 前复核每个最终对象的 title、summary、content、conditions、
   failureConditions、typedPayload、applicability/exclusions、contextRequirements、plannerHint、
   verificationTasks；未复核字段不得沿用。调用
   `mcp__poe_research__validate_research_review(run_ref=<runRef>, lease_token=<leaseToken>, review=<review>)`。
   结构、resolver、角色、因果或职责变化后重审完整对象，按 validationIssues 有界修正；missing/ambiguous
   endpoint 最多两轮 repair，不让程序猜枚举或端点。`readyForAccept=true` 仅说明安全子集可接收；
   校验失败先读顶层 `blockingReasons` 与 `validationIssues`，再按其位置读对应完整诊断；
   语义方向冲突须审读旧新关系，不能仅更换关系类型来绕过拒绝。
   `fullyResolvedForAccept=true` / `acceptanceMode=clean` 才说明覆盖、暂缓与组件缺口全闭合。
   `durableWritePreflight.status=permission_required` 时，在调用正式 accept 前停止并向 Controller 返回
   安全权限需求；`write_handle_ready` 仅为句柄 advisory，不保证事务成功。

6. Mandatory Checks 通过后调用
   `mcp__poe_research__accept_research_review(run_ref=<runRef>, lease_token=<leaseToken>, review=<review>)`。
   按实际状态处理结果，不能把下列分支合并成通用 retry：

   | 状态/结果 | 动作 |
   |---|---|
   | 可修复 `acceptance_rejected` | 修正 review 后用 `mcp__poe_research__retry_research_review(run_ref=<runRef>, sample_id=<sampleId>, review=<review>)`。 |
   | `review_contract_upgrade_required` | 发生在 CAS 前，案例仍是 claimed；升级对象并补齐字段，以同 lease 重新 validate 和普通 accept，不能改走只处理 rejected 案例的 retry。 |
   | 不可恢复 runtime 错误 | 停止，保留 runRef/lease，返回 safe failure。 |

   deferred/unresolved/coverage gap/failure 保留完整诊断；只有 clean validation/accept 可用 compact 摘要。
   validation/retry 都是原单案，不创建新案例。

7. claim 成功后的任何结束路径都返回 `sampleId + safe outcome`；accepted 时附 safe acceptance 摘要：
   writeReceiptRef、acceptanceMode、researchCompletion、created/updated/evidence counts、semantic edge count、deferred reasons、
   unresolved mention/unique component counts 和 mechanic/unique-gem diagnostics。不得输出 raw material。
   validation-only 的候选 recordId 不代表持久身份；验收后以 `mcp__poe_knowledge__get_research_write_receipt` 的
   `writtenMapping` 为准，再按其中实际 recordId 读回，不能把预览 ID 查询为空当作未入库。
   回执默认 `detail="summary"`；沿 `pagination.nextCursor` 完整读取所有实际ID/指纹。
   `detail="records"` 分页读取完整写入映射与当时保存的canonical摘要，不含完整正文；正文仍按实际
   recordId用 `mcp__poe_knowledge__query_research_memory(detail_level="record", response_profile="full")` 读回并核绑定，
   当前投影不能冒充历史写入正文。支持审计、缺口和比较提示用
   `detail="diagnostics"` 与 `diagnosticSections` 返回的精确 `section` 分页读取。
   `claimBindingStatus=diagnostic_only` 加 `bindingIssue=source_state_unknown/legacy_record_schema`
   表示资格诊断，不能误作来源指纹损坏；仍按本声明 `currentEligibility` 保持排除。
