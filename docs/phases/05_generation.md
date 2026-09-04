# Phase 5 - Agent 主导的 BD 生成原型

## 阶段状态

已完成。旧的重型 Phase 5 设计已归档，当前交付的是经过真实会话人工验收的轻量原型路线。

已完成：

- 将上一版“程序组装上下文、严格候选空间、重型 gate、局部 planner 补全”的设计归档到
  `docs/phases/05_generation_heavy_design_archive.md`。已完成
- Phase 5 主文档改为原型优先设计，明确 Agent 主导用户意图理解、查询、设计和候选生成；
  程序负责工具边界、安全、版本上下文、可评估状态的 Judge 调用，以及生成供人审查的安全
  报告；是否通过验收由人决定。已完成
- 完成 P5.1 所需的原型 schema、一次性运行绑定、Agent 主导 skill、真实 PoB 快照、独立 Judge
  调用和可信人工验收包。已完成
- P5.1 真实用户场景人工验收通过：Agent 在本地 PoB 过期时正确降级为有限证据，完成 Spark /
  Orb of Storms / Elemental Storm 多技能候选、可信 Judge 和人工验收包。已完成
- P5.2 同一运行内有限内部重试和 `--no-memory` 轻量对照已通过真实会话人工验收。已完成
- P5.3 已根据真实失败样例完成缺口复盘，补齐条件性伤害组件、发布/安装一致性、运行锁恢复和
  安全边界，未引入程序化 BD 补全器。已完成
- Phase 5 最终代码审查和需求方向核验已完成，合理发现已修复，`full` 提交级验证已通过。已完成

旧 P5.1/P5.2/P5.3 重型实现不再代表当前主线设计。

## 方向调整

上一版 Phase 5 设计过重，最大问题是把用户需求理解、上下文选择和候选方案收束过早交给
程序。PoE2 BD 生成的高价值部分是机制选择、阶段取舍、失败解释和搜索方向调整，这些不适合
用固定规则提前写死。

新的 Phase 5 先做可运行原型，而不是一次写完整生成系统：

```text
用户自然语言需求
  -> 外部 Agent 理解需求、必要时追问
  -> 外部 Agent 生成更具体的设计提示词 / BuildBrief 摘要
  -> 外部 Agent 自己调用数据库、图工具、记忆和 PoB/计算工具
  -> 外部 Agent 生成候选 BD
  -> 程序运行安全检查和 Judge 评估
  -> 输出人工验收包
```

## 当前边界

当前 Create 另有一组务实质量门禁：`get_build()` 是无副作用 readback；Judge 由调用方指定技能组与
技能名；checkpoint 始终返回八项 `createQualityChecklist` 和单一 `deliveryStatus`。辅助、续航、
现实装备、Charm/Flask、珠宝边际决策与 Rune 批量决策未完成时只允许 `candidate`。系统最多给出两轮
定向返工；Judge hard-pass 不再被解释为成品质量通过。

Memory-assisted Create 还会把最终 Family discovery receipt 与 selected Family 写入 run。用户本地化
名称解析失败或首次 Family 为 `no_family` 时，Agent 只查询一次官方英文名称并重试；不建设本地
多语言别名库。draft 和 Judge 均要求该 run 绑定存在。

Phase 5 仍遵守项目硬边界：

- 不持久化模型隐藏思维链（hidden chain-of-thought，模型私有逐步推理）、完整对话记录
  （transcript）、草稿推理区（scratchpad）或未经清洗的原始提示词（raw prompt）；
- 不持久化或输出 PoB 导入码、原始 XML、账号/角色细节或完整 URL；
- 不要直接抄袭完整第三方成熟 BD。Agent 可以独立选择相同的合理机制、职业、技能、暗金、
  辅助组合、天赋思路或装备方向，但不能把第三方完整 PoB、攻略、角色页或导入材料当作自己的
  生成结果；
- 没有 PoB/Judge 证据，不能声称 DPS、EHP、Spirit、抗性、属性或天赋预算已经验证；
- Agent 只能通过结构化工具查询数据库和图，不暴露原生 SQL、Cypher 或 Gremlin 查询语句；
- 跨阶段唯一硬锁是职业；开荒、攻坚、终局之间可以洗升华、换技能、换天赋、换装备和辅助技能。

Judge 反馈采用显式开关：普通 Create 默认 `strict_mode=false`，底层正式 Judge 仍完整计算，但仅把
确定性硬失败、`passed`、快照绑定和安全事实诊断交给 Agent；评分、质量档位、可玩性/质量警告、
reward 和主观 caveat 不进入 attempt、retry、Review 或 artifact。用户明确要求
“严格模式”时，调用方才在 checkpoint、Judge 和 lifecycle 调用中一致传
`strict_mode=true`；同一 run 首轮 Judge 后不能改模式。默认模式不替代主动质量收尾：Agent 仍须
基于 Research、机制、PoB 原始数值和构筑职责主动比较高影响方案，而不能把“没有质量警告”等同于
质量已经验证。

普通 Create 只交付用户请求的目标等级单阶段终局 BD；目标 BD 按本章流程从空状态生成，在既有
retry 内解决目标 lifecycle 的真实资源/机制失败，review 并保存为 immutable artifact，再对私有
artifact 生成可信 lifecycle receipt。

## Agent 与程序分工

Agent 负责：

- 理解模糊用户需求；
- 判断是否还需要向用户追问其他约束；
- 将用户需求改写成更具体的生成提示词或最小 `BuildBrief`；
- 选择要查询的数据库、Phase 4 记忆、图工具、机制资料和 PoB/计算工具；
- 设计候选职业壳、阶段路线、主技能、机制轴、防御层、资源/Spirit 思路、转型门槛；
- 根据 Judge 结果和工具反馈解释失败原因；
- 在后续原型阶段做内部重试。

程序负责：

- 提供结构化查询工具、PoB/Judge、安全检查和版本上下文边界；
- 校验 Agent 输出不包含原始 PoB、原始 XML、完整 URL、账号/角色细节、模型隐藏思维链或原生
  查询文本；Phase 5 helper 不负责判断候选是否“像成熟 BD”，也不因为 Agent 自己生成了具体
  技能组合、辅助组合、装备槽位摘要、天赋锚点或转型路线而硬拒绝；
- 保存安全摘要、字段来源、默认假设、注意事项和可审查的理由摘要；
- 生成 Judge 评估报告和供人工验收使用的安全报告；
- 记录工具误判、覆盖缺口和后续需要补的最小工具支持。

程序不负责：

- 用固定规则把用户问题转成最终 `BuildBrief`；
- 把数据库内容全部查出来塞给 Agent；
- 过早规定候选空间必须有几个变体、哪些字段齐全；
- 在没有 PoB/Judge 证据时替 Agent 声称候选已验证；
- 判断候选是否“像不像别人”。Phase 5 只关心是否安全、可解释、可验证和有设计价值。

普通单阶段 Create 保存 artifact 后，由 `export_final_build_package` 统一导出 PoB 文件、
导入码、官方 `.build`，并把已验证 code 发布成公开 poe.ninja PoB 分享链接。

## 原型阶段拆分

### P5.A 文档重定向与旧设计归档 - 已完成

- 主文档改为轻量原型路线。已完成
- 旧重型设计归档到 `05_generation_heavy_design_archive.md`，以后如果需要参考其中的结构合同、
  报告形态或基准测试思路，再按当前原型失败样例挑选使用。已完成
- `docs/PROJECT_SPEC.md` 同步 Phase 5 当前状态。已完成

### P5.1 第一阶段原型：Agent 主导生成 + Judge + 人工验收 - 已完成

目标：跑通最小闭环。外部 Agent 从真实用户问题出发，自己查询、设计并在 PoB 中搭建候选 BD；
程序捕获该状态、运行 Phase 1 Judge，并生成供人判断的安全报告。

流程：

1. 用户输入自然语言需求。
2. Agent 直接把需求整理为结构化摘要；如果信息不足，简短追问目标阶段、职业/升华/技能、重视
   清图/Boss/生存/操作/上限等约束；预算和价格只进入最终造价及获取难度披露。然后生成更具体的
   设计提示词或最小 `BuildBrief`。不需要
   开荒过程确认；本工具只产出目标等级单阶段终局 BD。
3. Agent 调用插件 MCP 的 `start_generation_run` 建立本次运行凭据；run 状态保存在受管用户数据
   目录。发布插件不要求仓库 checkout、当前工作目录或 Agent 手工编辑 `agent-output.json`。
4. Agent 按需查询研究记忆、图工具、语料库、机制说明、构筑原则和 PoB/计算工具，生成候选概要。
   精确 Family 查询的首轮 `limit` 只是展开量；Agent 必须阅读
   `familyRecordCoverage / familyRecordIndex / familyPremiseCatalog`，为 Boss、资源、轮转等
   职责建立处理表。存在未解决失败 premise 时，继续按 Family、组件、record kind、record ID
   或失败文本定向查询，直到采用原方案、采用替代方案、判定不适用或明确保留 caveat；不设固定
   查询或深读额度。
   Graph 搜索结果提供可原样回传 resolver 的 `resolverPayload.componentKey`；Family 身份继续使用
   `skill:` key，等级验证在边界处统一解析显示名、`gem:` 和 `skill:`。Meta aggregate unavailable
   时不阻塞 Create：先查 PoB/corpus/Graph/Research，再查官方补丁/数据/Wiki，最后用当前赛季
   poe.ninja/pobb.in 样本并 `import_build` 复核。网络证据不能写入 premise `resolutionRefs`。
5. Agent 使用 `apply_build_mutation_batch` 按 `bootstrap / mechanism_shell / skill_loadout /
   passive_delta / required_gear / ordinary_gear / config` 提交已经决定的小型职能事务，再用局部
   查询/优化工具补足明确缺口。不得把整个 BD 混进一个批次；批次不接受搜索或 optimizer。
   只有从 `new_build` 开始的 bootstrap 可省略输入 hash，后续事务必须使用上一批输出 hash 做
   CAS。失败只回滚当前职能事务，只有 `rolledBack=true` 才能确认恢复；否则停止并恢复 session。
   用这些小事务把候选落实为真实活动构筑。Create 默认禁止 `optimize_build` 与全局被动树重排。
   该状态至少包含职业、升华、
   等级、主技能与辅助技能、其他技能组、装备、天赋和战斗配置，并能读出属性、抗性、Spirit 与
   资源状态。程序不替 Agent 自动补全这些内容。`craft_item` 返回 Perfect Essence、符文或
   腐化效果时，Agent 必须在后续直接或批量 `equip_item` 中原样传入 `craftReceiptRef`；该
   raw-free receipt 同时绑定 PoB 写回后的语义指纹，不能用于证明被改写的物品。
   Family `gear_synergy` 中非 `optional_upgrade` / `budget_substitute` 的 `unique_enabler` 暗金先于
   普通黄装实装并逐组件记录 `adopted/caveated/rejected`；当前版本不可用写为 `rejected`，并在
   summary/application 记录 unavailable 原因。价格只在方案锁定后披露，不参与采用。
   普通暗金候选放在基础黄装之后。90 级默认以三槽腰带和三护符为
   质量目标，有效容量读取最终 PoB `CharmLimit`；缺属性为 unknown，只有超容量是硬失败。
   所有可镶嵌装备都要评估 `optimize_item_sockets`，但无机制收益或机制不适用可以明确不用；价格
   不是拒绝理由。默认装备优化
   目标等级 ≥90 的终局额外珠宝孔采用受保护的单候选全槽审计；低于 90 级不作为质量门禁，只在
   机制确有需要时自愿评估。Agent 先完成核心机制和重要支撑天赋，把不可交换的精确节点 ID 传为
   `protected_node_ids`，再用 `evaluate_next_jewel_socket` 比较一颗已选珠宝在全部当前可达槽位的
   真实等点收益。工具只允许当前安全单点叶节点参与替换，不向内拆分支或重排树。
   正收益 `decisionRef` 只能用 `apply_next_jewel_socket_decision` 原子应用，随后必须在输出 state
   重新审计；不再按固定轮数或成熟案例槽数停止。`policy_limited/inconclusive` 可进入 Judge，但
   交付保持 candidate。
   在元素 60%、非 CI 混沌 30% 后停止继续购买普通抗性，用户明确要求时可覆盖为 75%。
6. Agent 先调用 `inspect_generation_checkpoint` v4。该工具按语义 build-state hash 合并
   completeness、preflight、有界 stats 和 defenses，并分别返回
   `hardLegalityReady / mechanismReady / qualityAdvisories / readyForJudge`。共享、无评分的
   `HardLegalityAudit` 检查属性需求、装备等级、主动宝石等级、PoB 武器兼容、Spirit、普通/
   武器组天赋预算、来源感知黄装合法性、遗留 `Scaffold ...` 占位装备，以及 rare/magic 装备是否
   缺少 `Item Level`；制作、写入、checkpoint、Judge 和 artifact 保存共用
   同一物品审计，普通前后缀、Perfect Essence、符文和腐化不会再由两套检查器分别判断。同一状态
   不重复执行，状态修改后自动形成新检查。主动宝石
   检查只看宝石自身等级，装备或天赋提供的 `+levels` 不会造成误判。
   Research 深读和最终候选摘要完成，且装备、天赋、珠宝、Rune、辅助与 config 冻结后，Agent 先
   完成 state-bound Support/Jewel/Socket 检查与 checkpoint，再调用
   `validate_generation_draft(..., offense_skill_group_index, expected_skill_name)`。服务端从该最终 PoB
   观察辅助集合、主导命中类型和 Mana/Life 支付域，并与 state hash、Research/Blueprint 绑定。
   相同机制修订只调用一次；核心技能、辅助、主伤轴或支付域改变后重验 Draft，不新增 finalization
   状态机。memory-assisted/no-memory run 缺少 marker 时 Judge 失败且不消耗 attempt。
7. `evaluate_generation_candidate` 在写可信 Judge receipt 前对同一快照再次运行共享审计。
   确定性非法或机制结构未闭环时返回 blocker、`attemptConsumed=false` 和当前 attempt count，
   不启动独立 Judge，也不消耗初始一次加两次 retry。Agent 修正状态后重新 checkpoint。
8. 预检通过后，程序只捕获一次当前 PoB XML；预检与独立 Judge
   共享这份不可变快照，在独立 Judge
   引擎中运行 Phase 1 Judge，只持久化清洗后的状态引用和评估报告；同一份原始 XML 仅在当前
   MCP 进程内短暂保留，供最终 artifact 保存，既不进入 run 目录，也不进入报告。可信凭据绑定到
   本次 `runId` 与候选编号，同时记录不含原始材料的 `semanticStateHash`。该凭据的可信范围是
   快照和 Judge 结果；版本上下文仍来自 Agent 本次
   freshness/图/记忆查询，不因写入该凭据而自动变成程序签名事实。
9. Agent 在顶层只保存一次完整最终 candidate；每轮 `generationAttempts` 只需保存 attempt index、
   `{candidateId}` candidate 引用和 failure audit。`validate_generation_output` 以 candidateId 核对
   本 run 的连续可信 receipts，并补全 state/Judge 做非消费校验，不再要求每轮重复同一份完整候选。
   `memoryReferences` 可以从 typed `ResearchMemoryUse` 归一化。
10. 首个通过 Judge 且通过共享合法性审计的 attempt 成为受保护 passing baseline。Agent 随后仍
    必须执行一次完整主动质量收尾；新版本更好且合法时选择新 attempt，后续探索回归时可以选择
    旧 baseline。Judge 分数只作 advisory，Agent 还要结合机制闭环、配置真实性、多技能职责和
    用户目标决定实际保存轮次。
11. 对实际选择的 passing attempt 调用
    `save_final_build_artifact(..., attempt_index=...)`，再进入 review。选择 baseline 不要求当前
    活动 PoB 仍等于它；即使后续质量状态在 preflight 就失败、没有新增 Judge receipt，也能按活动
    state hash 已偏离来恢复。但必须仍有当前 MCP 进程内的精确 Judge XML、同 state hash 的合法性回执，并
    明确声明后续发现只影响 `candidate_delta_only`。若后续发现也影响 baseline、快照在重启后
    丢失或引用不一致，保存失败关闭。正常顺序不可颠倒；若历史运行误先消费 review，artifact
    saver 仍必须逐项核对 run token、实际选择的 candidate/attempt、精确 Judge snapshot 和
    state hash 才允许顺序恢复。Agent 不得删除 review marker、receipt 或运行锁。
12. `complete_generation_review` 核对 Agent 提交对象、artifact-selection receipt 与可信凭据，
    原子写入完整 `HumanReviewPacket`，只返回最终 Judge、重试差值、生命周期证据覆盖和
   `requiredUserDisclosures`。可信快照中
   每个未消失的完整度 advisory 都必须在候选中记录 `deferred` 或 `intentionally_unused` 及理由；
   缺项、候选不一致或评估结果被改写时拒绝验收。
   普通单阶段 Create 使用 Research 使用审计：每个关键失败 premise 都要在
   `ResearchMemoryUse.premiseDecisions` 中标为 `resolved / caveated / not_applicable`；resolved
   必须引用本轮 `detail_level="record"` 回执实际深读的解决记录。只在摘要中看到记录 ID、伪造
   receipt 或遗漏 premise decision 都会拒绝 review。该校验只检查引用和处理记录完整，不替
   Agent 判断机制结论是否正确。
    多 attempt 时，顶层完整 candidate、选中 attempt 的 candidateId 与可信 receipt 必须一致；
    `selectedAttemptIndex / artifactSelectionOutcome` 必须来自可信
   artifact-selection receipt，并同时进入 Human Review 与 retry report；不得用空值回退到
   最后一轮。单 attempt 与旧版包保持兼容。
13. 人工判断候选是否值得继续推进。

新生成的 80 级及以上候选必须达到火/冰/电各 60%、非 CI 混沌抗 30%；CI 只豁免混沌抗。
共享 `inspect_generation_checkpoint` 在正式 Judge 前执行该确定性门槛，失败不消耗 attempt。
79 级及以下和可信第三方参考仍为 `diagnostic_only`；元素 Max Hit 和其他防御层继续评估。

P5.1 不追求：

- 一次性补完开荒、攻坚、终局三个阶段的完整生命周期；
- 完整 `.build` 导出；
- 跨案例对照学习循环；
- 与成熟 BD 对比学习；
- 最终输出包的强检查门。


P5.1 最小产物：

- `AgentRefinedBuildPrompt`：Agent 产出的更具体生成提示词或最小 `BuildBrief` 摘要；
- `PrototypeBuildCandidate`：Agent 产出的安全候选 BD 摘要；
- `TransientBuildStateRef`：程序从真实 PoB 快照生成的安全状态引用，包含实际测试技能组、每组全部
  主动技能和数量，以及忽略派生输出/展示噪声的 `semanticStateHash`；
- `JudgeAdvisoryReport`：Phase 1 Judge 的可信安全摘要，包括硬阻断、注意事项、总分、分项分数、
  可建模性、Judge 实际选择技能、插槽诊断、属性缺口与复现版本；
- `HumanReviewPacket`：供人工验收使用的安全报告，至少包含用户需求摘要、Agent 改写后的
  生成提示词或 `BuildBrief` 摘要、候选 BD 摘要、使用过的查询和工具引用、Judge 状态、硬阻断、
  注意事项、人工评分字段和是否建议进入下一阶段；
- `LifecycleEvidenceCoverage`：只从最终可信 state/Judge 推导至多一个数值验证阶段，并把候选
  声明但没有独立 snapshot 的阶段列为 text-only；
- `ToolFeedbackEvent`：记录 Judge/工具无法评估、误判或缺口。

当前实现进度：

- Agent 需求理解、按需查询、候选概要与自然语言输出流程。已完成
- 原型 schema、安全检查、一次性运行凭据和 `HumanReviewPacket`。已完成
- `/poe-bd-create` 的 PoB 工具顺序、同一 MCP session 状态串行约束和实际技能组记录。已完成
- `evaluate_generation_candidate` 捕获活动 PoB、运行独立 Judge、生成无原始 XML 的可信凭据。
  已完成
- `complete_generation_review` 强制核对本次可信凭据，不接受 Agent 自填或改写的 Judge 结果。已完成
- trusted receipt canonicalization、非消费 `validate_generation_output`、compact attempt 与 compact review。
  已完成
- Judge 前活动构筑预检与同一 XML snapshot 复用。已完成
- Judge offense 观察值/阶段 floor/delivery evidence 拆分，以及显式 reward limit reasons。已完成
- 主技能组识别、多主动技能组诊断、Judge 实际选择技能和属性缺口安全摘要。已完成
- PoB 当前技能组、Judge 评分组件和条件性附加伤害组件分层；击杀爆炸不再误触发插槽非法。
  已完成
- 活动技能组支持基于 `index + fingerprint + stateHash` 的原子替换、删除和状态切换；来源技能组、
  主组约束、过期选择器和解析失败均失败关闭，不修改 PoB 存档格式。已完成
- 天赋优化 v2 在独立 PoB 快照运行，支持无副作用预览、提交前状态比较、稳定多目标累加、量化
  平局规则、精确路径节点和版本化输入/输出凭证；确定性测试比较实际节点与语义状态哈希。已完成
- P5.1 真实用户场景人工验收。已完成

人工验收记录：

- 运行编号：`da15d003-6d9a-4315-a3ec-2f4b1b5dd404`；
- 模糊请求“开荒比较顺畅的 BD”被 Agent 转换为操作简单、剧情至初入异界目标；造价只作披露；
- Agent 在 `blocked_stale` 且仅本地 PoB 过期时继续生成，没有错误停机；
- 活动构筑包含 Sorceress / Stormweaver、Spark、Orb of Storms、Elemental Storm、10 个装备槽和
  73/73 天赋点；
- Judge 无硬阻断，选中显式 Spark 作为本次 offense 组件，并将 `FullDPS` 投射物重叠保留为有限
  证据；
- `qualityBand=strong` 只表示当前评分档位，`rewardStrength=limited` 才表示证据/奖励强度；
- 人工确认该结果足以证明 P5.1 最小闭环可运行，不表示 Spark 候选已经获得当前 0.5.4 的强证据
  数值认证。

P5.1 验收：

- 能处理模糊请求，例如“我要一个开荒顺畅，后期洗点转型后攻坚和终局上限也比较高的 BD，先给我开荒阶段”；
- Agent 不输出 JSON 给普通用户要求用户阅读，而是自然语言追问或总结需求；
- Agent 生成的 `BuildBrief`/提示词由 Agent 负责，不由程序固定规则生成；
- Agent 必须给出与设计决策相关的查询证据，例如使用了哪个记忆、图查询、机制说明、
  构筑原则或 PoB/计算结果；无关查询不算通过；
- Agent 必须先实际调用 `get_freshness_report` 判断 PoE2 MCP 是否可用；只有宿主明确返回工具
  不存在或拒绝调用时才能报告 MCP 缺失，此时停止生成，不能搜索并复用仓库中的历史候选；
- freshness 为 `blocked_stale` 时必须检查具体组件：若当前补丁、赛季和天赋树可确认，仅本地 PoB
  引擎/数据落后，则继续完成候选、过期 PoB 有限证据 Judge 和人工验收包，不得机械停止；若当前
  游戏规则、天赋树或核心机制资料冲突/未知，才停止当前版本强验证或向用户追问；
- 每次请求必须使用新的运行凭据和本次唯一产物路径；旧产物、运行目录外产物和已经成功验收过的
  运行都不能通过 helper；
- 候选明确职业是跨阶段唯一硬锁；
- 生命周期工具只保证阶段路线、转型门槛和设计原则的参考价值；它没有给出具体技能名时不算
  失败，Agent 应继续用 `find_skills`、`get_gem`、`find_supports_for`、机制查询和 PoB/计算工具
  选择技能；
- 阶段计划里的转型门槛可以是洗点、换技能、换装备或洗升华后的转型门槛；
- Agent 必须把候选概要落实成真实 PoB 活动构筑，不能用空骨架代替；所有 PoB/计算工具串行调用；
- 正式 Judge 必须由 `evaluate_generation_candidate` 执行，`evaluate_build` 和生命周期门槛检查不能
  冒充 Judge；
- 可信凭据必须绑定本次运行、候选、快照和来源哈希；篡改或缺少凭据时 helper 拒绝；
- Judge 执行错误不能携带构筑硬阻断或分数；成功评估也不透出 `strong` 奖励信号；
- `testedSkillGroups` 必须来自实际 PoB 快照并记录技能组编号、全部主动技能及数量、辅助技能、中性
  的 PoB 当前组/额外组职责和启用状态；`mainSocketGroup` 只表示 PoB 当前计算组，不能解释成整个
  BD 唯一主技能；
- 一个候选可以有多个主要输出组件。Judge 本次选中的伤害组件、PoB 当前组和 Agent 设计中的清图/
  单体/触发/兑现技能必须保持不同语义；
- Judge 硬阻断报告必须提供足以修正候选的安全诊断：实际选择技能、选中技能组的主动技能数量与
  名称，以及具体属性缺口；
- 用户输出必须区分设计判断和工具验证结论；
- 人工验收包不包含原始 PoB、原始 XML、完整 URL、账号/角色细节、模型隐藏思维链、完整对话
  记录或原生查询文本；允许包含 Agent 生成的具体技能包、装备槽位摘要、天赋锚点和转型路线，
  供人工判断是否有实际 BD 设计价值。

### P5.2 第二阶段原型：有限内部重试与无记忆对照 - 已完成

进入条件：P5.1 人工验收确认候选有基本 BD 设计价值。

目标：

- 当生成BD无法通过judge, 将失败原因吐给agent作为上下文, 加 1-2 轮有限内部重试， 这里我建议直接使用skill实现，不要严格程序化；
- 增加“不使用 Phase 4 记忆”和“使用 Phase 4 记忆”的对照用来验证生成效果；
- 观察 Phase 4 记忆是否真的提升候选质量。

流程：

```text
候选 BD + Judge 参考评估 + 注意事项
  -> Agent 做失败核验
  -> Agent 修改设计方向或补查询
  -> 重新搭建临时构筑状态
  -> Judge 再评估
  -> 输出重试对比报告
```

这里的重试是 Create 内部有限质量修正，不是 Phase 7 的跨案例对照学习。它不写 Learning Memory，
不在比较后重新生成本案例，也不自行比较成熟原 BD。

当前实现边界：

- 初始候选和每次重试必须留在同一个 Agent 会话和同一个 `runId` 中，直接复用已有需求、查询和
  设计上下文；每轮只生成独立 PoB 快照和独立可信 Judge 凭据，不能覆盖上一轮结果；
- 同一次运行最多重试两轮；是否重试、失败是否可信以及具体修改方向由 Agent 判断，程序不自动
  修改技能、装备、天赋或配置，也不要求 Agent 为重试重新填充整套上下文；
- Agent 只把上一轮的安全候选摘要、Judge 报告、注意事项和工具反馈用于失败核验，不把隐藏推理、
  原始 PoB 或完整对话重新拼成重试提示词；
- 现有 `/poe-bd-create` 增加轻量 `--no-memory` 模式：该模式只禁用研究记忆查询，仍可使用静态
  语料、图、机制、PoB 和 Judge；普通模式必须实际查询研究记忆；
- 不实现自动记忆对照报告或胜负判断。人工用同一个固定请求分别运行普通模式和 `--no-memory`
  模式，直接比较最终构筑、Judge 结果、注意事项和设计价值。

P5.2 验收：

- MVP 至少选择 1 个固定用户请求，分别运行“不使用研究记忆”和“使用研究记忆”两种模式；
- 重试输入只包含安全候选摘要、Judge 报告和注意事项；
- 重试能改善合法性、可评估性或明确停止原因；
- 人工 review 能判断使用 Phase 4 记忆是否优于不使用 Phase 4 记忆。

其余固定请求保留为 P5.3 缺口采样池，不作为 P5.2 MVP 的完成阻断条件。只有需要对记忆收益形成
更稳定的统计结论时，才扩展为完整多样本对照。

这里“不使用 Phase 4 记忆”只指禁用 Phase 4 研究记忆；仍允许使用静态语料库、图工具、机制
查询、PoB 和 Judge。否则对照组会变成“什么工具都不用”，无法判断 Phase 4 记忆是否带来提升。

研究记忆对照采用轻量人工方式：普通 `/poe-bd-create` 必须查询研究记忆；
`/poe-bd-create --no-memory` 跳过研究记忆。人工对同一固定请求分别运行两次并直接审查结果，不
新增自动对照报告、自动胜负判断或新的无记忆 MCP 工具。

当前实现进度：

- 同一 `runId` 内保存初始评估和最多两次重试的独立可信 Judge 凭据，不覆盖前一轮。已完成
- Agent 安全失败核验、逐轮可信核对和内部重试前后报告。已完成
- `/poe-bd-create --no-memory` 轻量模式及普通模式研究记忆要求。已完成
- 真实会话人工验收。已完成

人工验收记录：

- 固定请求 `给我来一个开荒比较顺畅的BD` 已分别运行普通模式和 `--no-memory` 模式；
- 无记忆模式第一轮 Judge 因属性需求和元素抗性硬阻断失败；Agent 保留 Sorceress / Stormweaver /
  Spark 构筑方向，在同一运行状态中调整技能等级、属性和抗性后，第二轮 Judge 通过；两次正式
  Judge 之间未调用 `new_build`，证明内部重试能够复用旧构筑并按失败反馈局部修正；
- 普通模式首次 Judge 即通过，人工判断其 BD 方向也比无记忆候选更合理；该结论只代表本次原型
  验收，不视为研究记忆在所有请求上稳定胜出的统计证明；
- 人工确认 P5.2 MVP 验收通过。已完成

固定人工验收请求：

1. `给我来一个开荒比较顺畅的BD`
2. `我要一个开荒顺畅，后期洗点转型后攻坚和终局上限也比较高的BD，先给我开荒阶段的BD就可以`
3. `我已经完成开荒，想要一个低预算、优先打Boss的异界BD，不限定职业和技能`
4. `我想玩佣兵职业，主要清图，操作不要太复杂，给我攻坚阶段的BD`
5. `我想用Spark做一个终局上限高的BD，职业和升华由你选，优先生存和Boss能力`

需要扩大样本时，从以上请求池选择题目，分别运行普通 `/poe-bd-create` 和
`/poe-bd-create --no-memory`。人工记录最终候选是否符合需求、Judge 硬阻断和注意事项、是否发生
内部重试、重试是否解决具体问题，以及研究记忆是否带来可见设计价值。无需一次跑完全部题目，
也无需把结果提交给自动比较程序。

### P5.3 第三阶段原型复盘：定位缺口并决定最小工具支持 - 已完成

进入条件：P5.1/P5.2 产生足够真实失败样例。

目标：根据真实失败样例判断问题出在哪里，再决定是否需要补最小工具支持。这里不是开发一套新的
合法性验证系统；Phase 1 / Judge 已经负责合法性、评分和可建模性边界。Phase 5 只消费这些结果。

P5.3 主要做缺口分类：

- Agent 指令缺口：提示词没有说清目标、阶段、查询顺序或输出要求；
- 查询入口缺口：已有数据库、图、语料、Phase 4 记忆不好查，或结果不适合 Agent 使用；
- 构筑操作缺口：Agent 会设计，但现有 PoB/计算工具调用太碎，难以把设计落成可评估状态；
- Judge 报告转译缺口：Judge 已经给了结果，但返回信息不适合作为 Agent 修正上下文或人工验收材料；
- 数据覆盖缺口：静态语料、图节点、Phase 4 记忆或版本上下文缺失；
- 产品报告缺口：人工验收包缺少必要字段，导致人无法判断候选价值。

只有当真实失败样例证明“单靠 Agent 调工具反复写”成本太高、错误太多，才补小工具。小工具可以是：

- 更好用的查询包装；
- 更清晰的 Judge 报告摘要；
- 把多步 PoB 操作打包成一个可审查的执行入口；
- 把 Agent 产出的候选摘要整理成人工验收包；
- 对已有 Judge/PoB 结果做结构化失败原因提取。

P5.3 不做：

- 重新实现 Phase 1 已经负责的合法性判定；
- 写一套替代 Judge 的验证工具；
- 让程序根据 BuildPlan 全自动补完整 BD；
- 恢复“Agent 只给 plan，程序完全补全”的旧方向。

真实样例复盘结论：

- Agent 指令和查询入口已经足以完成需求理解、按需查询、活动 PoB 搭建和有限重试，不需要新增
  程序化需求解释器、上下文组装器或 BD 自动补全器。已完成
- Judge 的主要现实缺口不是“缺一个唯一主技能”，而是条件性内部效果和多技能场景职责容易混淆。
  已将击杀爆炸和 Thorns 等条件性反应伤害保留为 supplemental component（附加伤害组件），不再
  代替常规主 offense 或触发普通插槽非法；完整轮转与组合评分继续作为跨阶段待优化项。已完成
- 真实运行证明同一 `runId` 的局部修正可解决属性和抗性硬阻断；程序只保存逐轮不可变凭据并核对
  连续性，不根据分数替 Agent 决定修改方向。已完成
- 默认运行已收敛到 `memory_assisted`，无记忆模式必须显式指定；旧 `standard` 仅保留单轮兼容，
  不能用空 `generationAttempts` 跳过多轮审计。已完成
- 精确 Family 召回只用升华和核心主技能作为首查身份；图中 `gem:` 与对应 `skill:` 节点通过
  `grants_skill/granted_by` 关系等价匹配。可信快照显示重试改变升华或主技能时，验收要求新的
  `query_research_memory` 引用，普通局部修正不重复查库。已完成
- 精确 Family 查询使用独立的 `ascendancy_key` / `primary_skill_key` 合同，自然语言目标只参与
  相关性排序，不会把已有 Family 过滤成空结果，也不会把仅以该技能作副技能的 Family 当作精确
  主技能命中。Family 摘要返回 `recordKindCounts`；Agent 可用 `build_family_keys` 和
  `record_kinds` 按支持包、轮转、装备、升华、资源或防御缺口渐进深读，避免固定六条摘要静默
  遗漏新结构。已完成
- Create 查询使用 `response_profile="create_compact"`：在一个固定 revision 上选择单一
  `(knowledgeScope, sourceCaseRef)` lane，只把 eligible deep record/index/premise/digest 作为授权
  内容。每次首查创建唯一 retrieval session，以单 cursor 连续分页，每页 ≤64 KiB；完整
  `0..terminal` receipt 链才可写入 `ResearchMemoryUse`。pattern/edge/fragment 与其他 lane 只能作
  ToolReference；Research 维护使用 full 响应。已完成
- Create 将 `supportPackages`、`gearResponsibilities`、`ascendancyResponsibilities` 和
  `resourceMechanisms` 分别转成待验证的辅助候选、装备职责、升华取舍与资源/失效状态，不由程序
  自动拼装 BD。涉及暗金、天赋、触发、转换或资源交互的记忆结论在采用前仍需核对当前静态事实；
  resolver 成功不等于机制解释正确。已完成
- 精确 Family 无命中、证据过薄或存在具体设计轴缺口时，可显式查询同主技能经验与
  `transferablePatterns`。公用知识单列通道、固定返回上限，scope 权重低于 Family，且最高只允许
  `likely_pattern`；它不能伪装成当前 Family 成熟经验。component Pattern 在来源 Family 内仍通过
  `buildPatterns` 使用 Family 权重，只在跨 Family 使用时进入公用通道。已完成
- 安全扫描只阻断原始 PoB/URL/隐私/隐藏推理材料，不阻断 Agent 生成的完整技能组合；同时修复了
  不同 zlib 压缩级别 PoB 导入码的检测绕过。已完成
- Phase 5 分发链补齐固定 PoB、兼容清单、CI/Release 固定提交、MCP 注册和生成工具声明；安装器
  缺少 `uv` 时明确停止，运行时更新只接受本仓库发布源。已完成
- 评估互斥锁支持在超过 Judge 超时预算后恢复陈旧锁，避免异常退出让同一运行永久不可用。已完成
- 修正防御工具对抗性的阶段错配：`plan_gear` 按剧情、进图、终局使用 0%、30%、30% 的非 CI
  混沌抗默认目标与 30%、50%、60% 的元素目标；达到目标后不再让普通抗性词缀抢占后缀。
  显式 75% 目标仍受支持，Judge 的新生成终局硬门槛继续是元素 60%、非 CI 混沌 30%。已完成

因此 P5.3 不再新增新的大工具层。后续优先进入 Phase 6 导出；多技能轮转、触发与兑现组合、
分场景评分和更强版本证据绑定由真实样例继续驱动，不在 Phase 5 内手写全知规则。

### 待优化提示：多技能、轮转与场景职责

P5.1 当前只要求跑通真实候选、可信 Judge 和人工验收，不要求一次解决完整复合输出评分。但每次
真实验收都应记录以下缺口，供 P5.3 分类：

- 清图技能与 Boss 技能是否被错误压成一个所谓“唯一主技能”；
- 触发器、伤害兑现技能、辅助伤害层和条件性附加效果是否被混为同一插槽组；
- 多个技能是同时生效、交替轮转、条件触发，还是只能二选一；
- PoB `FullDPS` 是否有足够证据代表组合输出，还是只应视为上界或有限证据；
- Judge 当前选择的伤害组件是否与 Agent 声明的场景职责一致；
- Judge 是否把内部合成效果、增益技能或最后点击的技能误当成整个 BD 的评价对象。

Phase 5 负责用真实候选暴露这些问题并让 Agent 提供职责说明；Phase 1/Judge 负责补证据合同和
分场景评估；Phase 7 的独立 Comparator 比较双方循环和投送机制，并把 Judge 结果仅作为
`advisoryOnly` 附件。当前不允许用未经证明的技能 DPS 相加来“解决”组合评分。

### Freshness 降级与赛季兼容策略 - 已完成

通用 freshness 的 `blocked_stale` 约束的是“当前版本已验证”声明，不是所有 Phase 5 生成行为。
当官方补丁、赛季和天赋树可确认，而本地 PoB 引擎或数据落后时，P5.1 应继续运行并输出过期 PoB
有限证据、版本注意事项和人工验收材料，不能机械停止生成。

Phase 5 的 PoB 数据兼容性按赛季大版本判断，例如 `0.5.3`、`0.5.4` 和 `0.5.4b` 均属于
`0.5` 赛季。上游 PoB 在同一赛季发布新版本时只提示有更新可用，不因此把已认证的本地运行时
判为过期；精确补丁号仍保留在报告中。只有赛季大版本、天赋树世代或核心版本声明冲突时，才
阻断当前版本强验证。该策略不表示同赛季所有机制都已被 PoB 完整建模，具体缺口仍进入注意事项。
固定 PoB 已更新到上游正式版 `0.22.0`，并通过 Headless PoB、Judge 和 Phase 5 快照计算回归。已完成

官方天赋树刷新失败需要区分“树世代未知”和“GitHub 最新提交暂时无法确认”。当前实现每小时
尝试刷新、可信缓存保留 7 天，并识别 GitHub 匿名 API 限流。若本地已认证 PoB/语料与 poe.ninja
共同确认同一赛季树世代，则官方提交缓存过期只作为 warning；没有这些交叉证据时仍按 stale/
unknown 阻断。部署环境可选配置 `GH_TOKEN` 或 `GITHUB_TOKEN` 提高 GitHub API 限额。已完成

## BuildBrief 与提示词语义

`BuildBrief` 在新路线中仍有价值，但它是 Agent 产出的结构化需求摘要，不是程序化解释器的输出。

最小字段建议：

- 用户目标安全摘要；
- 当前输出阶段；
- 完整生命周期目标；
- 跨阶段硬锁：只能是职业；
- 预算/经济环境披露假设（只用于最终造价和获取难度说明，不参与构筑选择）；
- 用户明确指定或排除的职业、升华、技能、机制、物品；
- Agent 默认假设；
- 需要追问的问题；
- 字段来源；
- 版本上下文；
- 注意事项。

保存规则：

- 可以保存解释摘要、字段来源、默认假设和可审查的理由摘要；
- 不能保存模型隐藏思维链、完整对话记录、草稿推理区或未经清洗的原始提示词；
- 多语言术语归一化暂不实现，只记录后续优化点：中文、日语、韩语等请求中的 PoE2 专有词，
  后续应通过项目 glossary/alias table 映射到英文 domain terms 或 stable keys，不能靠普通直译。

## Phase 5 / Phase 6 边界

Phase 5 和 Phase 6 不能用“有没有装备、天赋、技能补全”来区分。只要 Phase 5 要跑 Judge，
当前评估阶段就必须已经有可被 PoB/Judge 读取的装备、天赋、技能、等级、配置、属性、抗性和
Spirit 状态。

Phase 5 负责：

- 从用户需求生成候选 BD；
- 主导搭建当前请求阶段可 Judge 的临时构筑状态；
- 运行 PoB/Judge；
- 输出安全摘要、Judge 结果、注意事项和本地临时状态引用；
- 通过人工验收判断这个候选是否值得继续。

Phase 6 负责：

- 把 Phase 5 已验证或部分验证的候选转换成官方 `.build` JSON；
- 处理官方 ID、导出字段、不支持字段的注意事项和导出结构校验；
- 保证导出物可以被外部工具消费。

所以 Phase 6 不是“才开始让 BD 变完整”。Phase 5 为了 Judge 已经需要当前阶段可评估的完整临时
状态；Phase 6 是把这个状态和阶段路线产品化、标准化、可导出化。

## 查询上下文策略

Phase 5 原型不做“程序把 Phase 4 数据库全查出来塞上下文”。

正确方式：

- Agent 先根据改写后的生成提示词判断要查什么；
- 先用结构化图工具确认升华、主技能和核心副技能 stable key，再用自然语言目标和
  `component_keys` 查询研究记忆 summary；
- summary 同时提供匹配的 Build Family、深度记录、planner-visible pattern、semantic edge 和
  旧 fragment；Agent 只按 `record_ids` 深读少量高度相关记录；
- 精确 Family 为空或在资源、防御、轮转、机制链等维度存在明确缺口时，Agent 才使用
  `include_transferable=true` 和 canonical `research_axes` 读取独立的 `transferablePatterns` 通道；
  Family 结果保留优先配额，公用知识不得挤占或覆盖同等相关的 Family 经验；
- Agent 使用 `recordKind`、组件职责、条件、失败条件、typed payload、pattern 证据等级和
  verification tasks 做取舍，不能把 `case_observation` 写成通用规律；
- 查询结果只作为参考上下文；
- 节点解析、辅助技能、Spirit、天赋、装备、PoB/Judge 仍以各自工具证据为准。

程序需要提供的是：

- 安全查询入口；
- 查询结果大小限制；
- 使用过的查询引用、Family/record/pattern/edge ID，以及采用、保留或拒绝结论的安全摘要；
- 定向查询无命中时允许显式记录 `no_matching_memory`，但不能以一次空泛工具调用冒充使用了记忆；
- 数据分区、可见性、安全检查和版本上下文边界；
- 不让可直接复刻成熟 BD 的原始材料进入持久产物。

## Judge 使用策略

Judge 是参考评估和硬阻断来源的组合。

可以作为硬阻断：

- 职业/升华组合不合法；
- 辅助技能明确不兼容；
- Spirit 明确超预算；
- 天赋预算明确超出；
- 属性需求明确不足；
- 已装备物品或主动宝石超过角色可用等级；
- PoB 回读确认主技能与当前武器不兼容；
- 黄装/魔法装词缀数量或组别明确非法；
- PoB 导入完全失败；
- 原始材料安全检查失败；
- 程序能确定的结构、版本或节点错误。

只作为参考信号：

- DPS 低；
- EHP 低；
- 回复能力弱；
- 机动性弱；
- Judge 选中的主伤害技能不确定；
- 召唤物、触发、FullDPS 汇总、投射物重叠、条件增益等建模注意事项；
- PoB/Judge 没建模的机制。

Judge 失败必须进入失败核验，区分：

- 构筑真的失败；
- Agent 设计假设错；
- 工具/数据库覆盖缺口；
- PoB/Judge 建模不足；
- 临时构筑状态没搭完整；
- Judge 选中的主伤害技能或 FullDPS 读错。

Agent 不能用解释覆盖硬阻断；只能给出复核证据、修正候选或记录工具反馈。

## 当前阶段装备完整度补充

真实导出验收发现，早期原型可能把 `scaffold_gear` 的占位黄装保存为最终候选，并遗漏黄装物品
等级、符文/灵魂核心、天赋珠宝、药剂和护符。Phase 5 的“可评估完整状态”因此补充以下合同：

- `plan_gear` 按角色等级选择当前阶段可获得底材，以同一物品等级筛选词缀池，并把
  `Item Level` 写入 PoB 黄装。已完成
- Judge 将装备需求等级高于角色等级视为硬非法，不能再让低等级角色穿终局底材通过。已完成
- `set_skill` 对未写等级的主动宝石选择当前角色可用的最高基础等级；显式超等级会回滚。Preflight
  和 Judge 也会拦截导入构筑或降级角色后遗留的超等级主动宝石。已完成
- `inspect_build_completeness` 在正式 Judge 前报告占位装备、缺失物品等级、符文/灵魂核心决策、
  天赋珠宝、生命/魔力药剂和腰带护符容量。已完成
- `scaffold_gear` 仍可用于中途计算，但所有 `Scaffold ...` 物品，以及 rare/magic 装备缺少
  `Item Level`，现在由共享 `HardLegalityAudit` 在 Judge 前阻断并返回
  `attemptConsumed=false`；它们不再只是保存前 advisory。已完成
- 药剂、护符、珠宝和符文由 Agent 根据阶段、Research 职责和构筑机制选择；价格只作披露。80 级
  以上新生成候选必须装备暗金或至少一条合法词缀的 Magic 生命/魔力药剂；普通药剂使用
  `optimize_flask`，程序不替 Agent 选择 Family 暗金。已完成
- 生成腰带写入真实 `Charm Slots`；缺少属性为 unknown，最终容量读取 PoB `CharmLimit` 并封顶 3。
  90 级三槽/三护符属于质量目标，只有装备数量超过容量才硬失败。已完成
- 新增 `optimize_item_sockets`，在保留现有物品全部普通内容的前提下增量选择 1–2 个符文/灵魂核心，
  复用现有 craft receipt 与 `equip_item` 写回。所有可镶嵌槽都应评估，但允许明确不用。已完成
- `optimize_item` 和 `rank_upgrades` 返回候选前复用同一个全角色 `HardLegalityAudit`；换装造成
  属性不足、其他装备失效或已装备槽位从 10 个退化为 9 个时，该候选不进入推荐排行，并保留
  结构化拒绝原因。黄装自身词缀审计仍先执行。已完成
- 资源续航同时检查 Mana/Life 的每次固定、每次百分比、每秒固定和每秒百分比成本；固定与百分比
  单次成本必须合并后检查可支付性。`*LeechGainRate` 已包含 On-Hit，不能与 `*OnHitRate` 双计。
  存在 PoB 未建模 Mana 恢复时输出
  “需验证未建模恢复覆盖”，先用 PoB/corpus/Graph/Research、必要时联网复核，再通过辅助、天赋、
  技能、装备、护符、镶嵌、药剂或轮转补救；不能直接下“会断蓝”结论。确认只依赖普通魔力瓶且
  无其他覆盖时仍失败。同一 run 最多两次核心机制级重建；两次后硬合法但未证明只能称待验证候选，
  真实失败且无法补救则停止交付。已完成
- 所有装备优化路径共享元素 60%、非 CI 混沌 30% 的默认饱和目标，保留显式 75 覆盖和
  `resistsCapped` 兼容字段，并用 `resistanceTargetMet` 表达新目标。已完成

这些检查不把 BD 创造转回程序化补全。它们只保证 Agent 最终接受的是可玩的阶段构筑，而不是为
Judge 临时堆出的计算骨架。

## 新赛季 / 新 Patch 更新流程

本节只约束 Phase 5 原型。随着原型开发推进，本节需要同步维护。

当前原型阶段，新赛季至少检查：

- `docs/phases/05_generation.md` 和 `docs/PROJECT_SPEC.md` 的 Phase 5 状态是否仍准确；
- `/poe-bd-create` 技能的提示、示例和版本上下文是否会误导新赛季运行；
- 给 Agent 的指令是否仍要求查询当前数据库/图/记忆，而不是使用过期静态例子；
- Judge 版本、PoB commit、graph snapshot、research memory ref 是否进入人工验收包；
- `evaluate_generation_candidate` 是否仍能载入当前 PoB 快照并输出匹配的新 Judge 版本；
- 固定 PoB 是否已更新到当前赛季内经过计算回归认证的稳定版本；同赛季上游小版本只提示更新，
  不自动让现有运行时失效；
- 新赛季 PoB 数据导致技能组、装备、天赋或 Spirit 读回字段变化时，更新可信快照提取和测试样例；
- 固定验收请求是否仍适合当前赛季；
- 如果新增了原型代码或测试，相关测试样例里的赛季、补丁、天赋树、图快照是否需要更新。

后续随着开发推进继续补充：

- P5.1 原型完成后，补充“Agent 改写后的生成提示词”“原型候选 BD”“人工验收报告”的版本字段
  更新方式。已完成
- P5.2 的赛季重跑使用新的运行凭据，至少从固定请求池选择同一道题分别运行普通模式和
  `--no-memory` 模式；核对普通模式实际查询研究记忆、无记忆模式跳过研究记忆、每轮 Judge 凭据
  独立保存，以及失败后仍能在同一运行中修正。已完成
- P5.3 未新增程序化补全器；新赛季需要同步固定 PoB commit、`data/compatibility/pob.json`、
  CI/Release 的 `POB_COMMIT`、本地认证运行时、`.mcpb` 内兼容清单，以及条件性技能组件回归样例。
  已完成

如果新赛季只改变本地运行缓存或用户运行记录，不需要推送 GitHub。只有当结构合同、测试样例、
文档、固定数据、插件/运行时包或仓库内验证合同发生变化时，才需要提交并推送。

## Review 与开发准则

- Phase 5 开发过程中不再进行阶段性需求对齐 review 或阶段性 code review；
- 整个 Phase 5 完成、准备提交时统一进行 code review；review 反馈需要先核验合理性，不能盲目采纳；
- 不为了消灭 review finding 而支持非法语义，例如“后期换职业”；
- 遇到复杂功能或不好处理的问题，不默认降级，需要先说明选项并征求意见；
- 需要人工验收时停止开发，展示阶段结果。

## 当前非目标

- 不做旧式 P5.3 严格多候选结构主流程；
- 不做“Agent 只给高层 plan，程序完全自动补完整 BD”的旧方向；
- 不做 Phase 6 `.build` export；
- 不做 Phase 7 reference Profile、盲测 Create、独立 Compare 或跨案例 Learning Memory；
- 不做全链路开荒成长流程（仅交付目标等级单阶段终局 BD）；
- 不把 Judge 分数当成机制真值；
- 不把 Phase 4 成熟 BD 研究模式当作硬性合法性证据。

## 验证结果

开发过程中先按改动范围运行聚焦测试和 quick profile。由于最终实现修改了 Judge、PoB shim、
freshness、运行时安装和打包，提交前已运行完整验证：

```powershell
.\scripts\verify.ps1 full
```

完整 pytest、Ruff、格式检查、freshness 边界类型检查和 MCP bundle manifest 校验均已通过。
后续如果只改 Phase 5 原型非计算代码，优先运行对应 `tests/test_phase5_*.py` 聚焦测试，再运行
quick profile；运行时打包和普通发布使用不含 PoB golden 的 `full`。只有直接修改 PoB 引擎、
Lua bridge、数值计算或 optimizer 行为时才显式使用 `compute`。
