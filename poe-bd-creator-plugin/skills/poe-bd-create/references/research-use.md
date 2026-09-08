# Create 的 Research 使用

普通 memory-assisted Create 在 `start_generation_run` 之后读取本文件，直到形成最终设计案例、研究决策和机制蓝图输入。`--no-memory` 不调用 Research/Learning Memory，输出差异见 [output-contract.md](output-contract.md)。Blind Create 先应用 [blind-mode.md](blind-mode.md) 的 claim、scope 和单案例隔离差异。

## 来源版本与目标适用性

读取 `targetApplicability`：优先当期证据，其次 `reviewed_compatible` 的历史证据，再使用带验证任务的
历史知识。0.5.5可正常召回0.5.4知识，保留来源gamePatch；不能因版本不同宣称no_matching_memory。
兼容复核不代表当期样本或当前PoB数值认证；`incompatible/changed_scope` 不得作为目标版本实现或
premise解决依据。数据/模型未覆盖的组件保持unmodelled，不能改标签补齐或引用旧PoB证明当前合法。

## 1. 发现 Family

先 `graph_tool_query(tool_name="search_graph_components", ...)`，再把候选的 `resolverPayload` 原样传给 `resolve_graph_component`，确认职业/升华 stable key。模糊候选只用于发现。升华是 Family 发现入口：没有选定 Family 前，不得猜主技能再反查 Family；用户明确指定技能时另解析 stable key，作为 `related_skill_key` 匹配条件。

第一次使用用户原始职业/升华名称。解析 missing/ambiguous，或该身份的 Family discovery 返回 `no_family` 时，只追加一次官方英文名 fallback：从 GGG 官方页面/数据核对英文名，再 search→resolve→Family discovery。不得用本地翻译表、循环试多个翻译或搜索摘要猜 stable key。

调用 `query_research_memory(detail_level="family", response_profile="create_compact", ...)`，传当前 `class_key`、`ascendancy_key` 与版本；用户指定技能时加 `related_skill_key`，它匹配 Family 的 primary/secondary skill 集合。discovery 不传 `primary_skill_key`，也不把普通辅助、utility、副技能作为必需 AND。

检查 `familyDiscovery.outcome`，以及各 Family 的 `primarySkillKeys`、`secondarySkillKeys`、`recordKindCounts`、`deepResearchRecords`、`createEligibility`：

- `known_family_not_authorized` 是已知但需 revalidation，不能误报 `no_family`；确无 Family 才是 `no_family`。
- 选定后统一用 `build_family_keys=[selectedFamilyKey]` 定位；不再用猜出的主技能重新定位 Family。
- 完成 discovery 页链后，用终页 `dedupeQueryRef` 调用 `record_generation_family_discovery(run_id, run_token, family_discovery_ref, selected_family_key)`。不能绑定首个或中间页；确无 Family 时 `selected_family_key=""`。memory-assisted Draft/Judge 必须有此 run 绑定；已发现 authorized Family 时不能改报 `no_matching_memory`。

## 2. 完整读取授权案例与对照案例

### 查询回执规则

Create 授权查询使用 `response_profile="create_compact"`；每次首查创建新的 bounded retrieval session。普通 Create 首查传本次 generation `run_id` 为 `run_ref`；Blind 首查的绑定见其 reference。`run_ref` 关联任务，不改变 scope/case 权威。

命中查询选择一条 `(selectedKnowledgeScope, selectedSourceCaseRef)` lane。`complete=false` 时只把返回的 `retrieval.nextCursor` 原样传为下一次 `continuation_cursor`，连续读到 `complete=true`，保存每页 `dedupeQueryRef`。continuation 只传 cursor，不跳页、重排或混合 session。响应按最终 UTF-8 JSON 65,536 bytes 分页；`memory_item_too_large` 不是完整记录，不得采纳截断内容。

授权 `dedupeQueryRefs` 必须包含各 session 从 page 0 到 terminal 的完整连续链；memory revision、manifest、scope/case 不一致都会失败。全部授权查询使用最终同一 lane；其他案例只进 `comparisonDedupeQueryRefs`，其各自页链也必须完整，Family/补丁/天赋树版本相同，且不能等于授权 lane。

两组引用都必须在当前 Phase 5 run 创建之后实际查询过。发现/比较阶段的旧 receipt 不能用于本 run 的 evaluate/review。`versionContext.researchMemoryRef` 使用本 run 授权 `dedupeQueryRefs` 中的真实引用；一旦写入某次可信 Judge receipt，不得改写该 receipt 的版本绑定。

`response_profile="full"` 用于 Research 比较或补充 ToolReference，不产生新版 Create 授权 receipt。lane-specific Create 不能把 pattern、semantic edge、legacy fragment 当作授权深度记录。

### 选择设计案例

读取精确 Family 返回的 `sourceCaseLane.familyAvailable`。自动选择的最高覆盖案例只是初始 lane；按 `eligibleRecordKindCount`、`eligibleRecordCount` 从高到低再选最多 2 条其他案例，不足 2 条则全部选择。每条显式传 `knowledge_scope`、`source_case_ref`，保持 Family/版本，用 `detail_level="summary"` 新开 compact 查询并完成页链。

普通 Create 有 2 个案例时读 2/2，有 3 个及以上时至少读 3 个总案例；Blind 不做此对照。对照页的引用放入 `comparisonDedupeQueryRefs` 与对应 ToolReference。每条摘要说明是佐证、补充还是冲突，以及如何改变设计/验证计划；对照内容不能直接解决授权 lane 的 premise。

读完初始与对照 lane 后调用：

```text
construct_research_execution_contract(authoritative_dedupe_query_refs,
comparison_dedupe_query_refs, build_family_key, selected_knowledge_scope,
selected_source_case_ref, game_patch, passive_tree_version)
```

比较 `caseProfiles` 的职业壳、核心技能职责、防御、资源、必要装备、天赋/珠宝状态、失败条件及证据/验证计划，说明哪个最符合用户目标。若 `selectedDesignCaseRef` 不是初始 lane，显式重查该 case 作为最终授权 lane，原 lane 移入对照，然后重新构造合同；计划选择与授权 lane 必须一致。

## 3. 深读职责、条件与失败前提

检查 `familyRecordCoverage / familyRecordIndex / familyPremiseCatalog`，先以 `detail_level="record", response_profile="create_compact"` 深读 `familyRecordCoverage.requiredDeepReadRecordIds` 的全部记录。集合由支持包、非 optional 装备职责、资源、失败条件和核心机制代表记录派生，遗漏会触发 `research_required_records_not_read`。

具体缺口未关闭时，在同一 Family/lane 用 `record_kinds` 做定向摘要，再对需要的 `recordIds` 用 `detail_level="record", response_profile="create_compact"` 精确深读并读完整页链。不得以一次宽查代替取舍，也不因上下文预算放弃关键记录；不设固定摘要、维度、记录或查询轮数。

优先读 `criticalPremiseDigest`，保留 `recordKind`、`conditions`、`failureConditions`、`typedPayload` 和验证任务：

- `supportPackages` 是归属明确的辅助候选，后续由当前 PoB/`optimize_supports` 验证。
- `gearResponsibilities` 转为装备职责；`ascendancyResponsibilities` 支持升华取舍；`resourceMechanisms`、轮转和机制链转为支付预算、失败状态与验证计划，不授权程序自动装配。
- Family 知识优先于公用/跨流派知识。`case_observation` 是待验证假设；跨案例一般性结论需更高证据等级。pattern 的 `confidenceTier / semanticScopeReview` 决定范围；`legacy_unattested` 只能作旧观察，不能凭“常见/通常”等措辞提高权重。
- 采用暗金、天赋、触发、转换或资源交互前，以当前静态/机制事实复核前提。resolver 只证明存在，不证明交互；已被事实否定的结论记 `rejected`，不能仅加 caveat 后继续当依据。合法性与数值仍由当前图、PoB 和 Judge 验证。

关键失败 premise 逐项记 `resolved / caveated / not_applicable`。`resolved` 的 `resolutionRefs` 只能引用本 run record-detail receipt 的 `deepReadRecordIds`；深读多条解决记录就实际查询全部对应 ID。网络、外部样本、普通图/语料证据只能写 ToolReference、理由或 caveat，不能充当 resolution。没有深读解决记录时保留 `caveated`，或以当前事实说明 `not_applicable`；caveated 只降低采纳档位并披露风险，不自动判 BD 失败。字段形状见 [output-contract.md](output-contract.md)。

## 4. 为研究包与组件作决定

合同的 `authoritativePackagesRequireDeepRead` 要求：所有 `authority=authoritative/authoritative_and_comparison`
的 package，其 `recordId` 都必须先有本run的record-detail深读回执，即使决定 `not_applicable` 或
`tested_and_rejected` 也不豁免。第3节的 `requiredDeepReadRecordIds` 可能只是其中一部分，不能代替
全授权包检查；补读后重构合同，确认全部授权包recordId都在 `authoritativeDeepReadRecordIds` 中。

对最终合同全部 `reviewRequiredPackageIds` 填 `packageDecisions`：`adopted / tested_and_rejected / not_applicable / retained_as_alternative`。分别说明机制理由、最终应用和实际证据；“更强/更协同/常见搭配”不足以构成理由。授权 lane 的 package 不能只留为 alternative。

`adopted` 表示完整保留 build-defining skill/support package。只复用部分组件时，package 用
`tested_and_rejected`，保留组件另用 Blueprint claim 和 insight `caveated` 表达。引用必须属于
本 run 已校验的 Research receipt/contract/package/record，或 candidate 中显式 agent_reviewed
且填写 reviewBasis 的 ToolReference；默认 unverified 引用不能授权执行决定。不得伪造
checkpoint/机制/PoB 引用。`adopted`、`tested_and_rejected` 及每个跨案例计划至少包含一项
Research/合同之外已审读的图、机制或 PoB/计算证据；来源 package 本身不能证明适合当前候选。

对照 package 采用前必须在该 case 做 record 深读，并绑定完整 `crossCaseMechanismPlan`：来源 case/package、授权 lane 的配套 package、机制闭环、兼容性、机会成本、实施与冲突处理、至少两项验证、失败退出条件及证据。允许兼容的完整机制组合，不允许只摘单个伤害词缀、辅助、暗金或恢复手段而省掉配套。无法证明完整兼容时保留 alternative 或测试后拒绝。深读更新后再次构造最终 contract view；相同 lanes/版本下 `contractRef` 稳定，deep-read coverage 会更新。

### 必需暗金与逐组件决策

深读记录的 `component_keys` 中 `unique:`/`item_base:` 是 Family 候选，不能因默认黄装工具链忽略；暗金用 `get_unique` 读全文，后续按构筑阶段实测。

`gear_synergy.typedPayload.componentMentions` 中 `role=unique_enabler`，且同组件 `gearResponsibilities.responsibilityType` 不是 `optional_upgrade`/`budget_substitute` 时，视为所选案例的组成件，默认保留并先于普通黄装落实。只有用户明确排除、当期不可用、当前事实否定机制，或围绕组件一次配套重规划仍无法修复合法性/资源失败时，才可拒绝；当期不可用用 `rejected` 并在 summary/application 写清 unavailable 原因。价格不能作为拒绝理由。optional/budget substitute 和普通 scaling/defense/utility 候选只要求评估；Family 未提暗金也不免除后续普通候选评估。

Contract v2 的 `requiredInsightDecisionSubjects` 只列授权 lane 的 canonical `unique_enabler`。每个 subject 在 `insightDecisions` 中原样填写唯一 `subjectRef`，至少引用其一个 `sourceRecordIds`。多个暗金分别决定，不能合成模糊一项；不得缺失、重复、额外或引用无关记录。普通记录级 insight 可不填 subjectRef。subject 最多 24 项；超限重查数据范围，不能截断。组件决定不能代替 package、premise 或跨案例配套决定。

## 5. 补缺、停止与交接

精确 Family 无命中、深度证据薄弱或资源/防御/轮转/机制链仍有具体缺口时，做定向补查：同主技能跨升华仅传主技能 key；机制查询使用 `include_transferable=true` 和 canonical `research_axes`。full 结果中的 transferable 事实只作 ToolReference，不进入当前 Family 的授权 lane 或 `researchMemoryUse`。

`get_meta_builds/get_meta_archetype_trends` unavailable 不阻止 Create，也不证明流派不存在。先查 PoB、corpus、Graph、Research；仍有缺口时查官方补丁/数据、PoE2 Wiki，最后查当前赛季 poe.ninja/pobb.in 等样本并用 `import_build`/PoB 复核。网络证据只进 `toolReferences / rationaleSummary / unresolvedCaveats / toolFeedbackEvents`。目标低于70或 Research 无Family命中时，普通 Create 可用网络/模型知识为设计主源；≥70且命中Family时仅补维度，不替换Family结论。Blind仍遵守其隔离边界。

普通 Create 确认精确 Family、等级和版本后调用 `query_public_learning_memory(family_key, target_level, version_context, dimensions=None, limit=8)`，同时读 lesson、`correctionsAndDoNotRepeat` 与 stale 提示。lesson 仍需当前事实/PoB验证，只在安全摘要引用实际采用的 lesson ID；不填 Phase7 专用 `learningMemoryUse`。

停止条件：Family已发现、规定对照已完成、第3节必读集合与第4节全授权包/对照采纳的深读要求均已满足、全部package已决定、跨案例采用计划完整、当前具体缺口已处理。只为新缺口追加查询，不原样重放相同 query/receipt，也不以固定轮数结束。确无命中时记录真实 `no_matching_memory + noMatchReason`，不伪造引用或lane；已知但需复核的Family不能冒充不存在。

将选定证据、条件、失败窗口、验证任务和未解决项交给 [mechanism-blueprint.md](mechanism-blueprint.md) 综合；数据填写时读取 [output-contract.md](output-contract.md)。本阶段只决定设计与证据，不自动组装BD。
