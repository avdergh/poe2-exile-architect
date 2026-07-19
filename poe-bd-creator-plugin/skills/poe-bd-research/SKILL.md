---
name: poe-bd-research
description: Use when the user wants to collect, queue, analyze, or store mature Path of Exile 2 build knowledge from poe.ninja or local PoB import codes.
---

# /poe-bd-research

把成熟 PoE2 BD 样本转成 copy-safe、resolver-backed、planner-advisory 的研究记忆。脚本只负责队列、lease、transient packet、验收和入库；外部 agent 负责逐案例研究。

## Runtime Mode - Hard Boundary

这是产品运行态 workflow，不是开发/调试任务。

- 禁止使用 subagent、子代理或独立 agent lane 研究案例。研究 MCP 工具只保证在触发本 skill 的当前
  主会话可用，因此当前 Agent 必须亲自读取 prompt、调用研究工具、生成 safe review 并执行 accept。
- 工具未直接列在当前上下文时，先使用宿主提供的标准 tool discovery / tool search，按精确名称
  查找 `query_research_memory` 和 `graph_tool_query`；不要仅凭首屏工具列表断言 MCP 不可用。
- 用户在 Codex 会话框输入 `/poe-bd-research` / `$poe-bd-research` 是在请求 agent 执行 workflow，不是在执行 shell 命令。agent 必须自己用可用工具运行内部脚本；不要要求用户把 PowerShell/Python 命令复制到会话框或终端。
- 运行 `/poe-bd-research` / `$poe-bd-research` 时，不得修改仓库源码、测试、文档、schema、安装脚本或 plugin manifest。
- 不得调用调试/TDD/代码修改类 skill，不得新增测试或现场修脚本。唯一允许的文件编辑是使用
  文件编辑工具或 `apply_patch` 编辑当前 lease 的 `reviewFile`；不得编辑其他 artifact 或仓库文件。
- 只允许写入 `--output-dir` 下的队列/验收 artifact，以及 OS temp 下的 transient packet。
- 如果 queue、collector、claim、prompt 或 accept 失败，只报告 safe error 并停止。典型状态是 `collector_failed`、`source_unavailable` 或 `runtime_failed`。
- 如果用户需要修复失败原因，明确告诉用户这需要另开普通开发请求；不要在本次 research runtime 中临场改代码。

## Options

`$ARGUMENTS` 可包含：

- `--limit N`：从 poe.ninja 当前 softcore trade league 取样。底层 CLI 默认 50；交互式 skill 无参时不要静默启动 50。
- `--ascendancy NAME`：可重复，对已渲染结果做本地升华筛选。
- `--class NAME`：可重复，透传为 poe.ninja 列表 URL 的 `class` 参数；当前网站用它筛升华，
  例如 `--class "Blood Mage"` 会编码为 `class=Blood+Mage`。从网站 URL 取得的
  `--class "Blood+Mage"` 也会先归一为同一名称，不会二次编码成 `%2B`。collector 会对返回列表
  再做同名本地复核，其他升华不能占用请求的样本数量。它不是 PoB 基础职业字段。
- `--level-min N` / `--level-max N`：默认 90-100。
- `--source-file PATH`：单个本地 PoB code/XML。
- `--source-batch-file PATH`：本地批量文件；执行时仍一案一轮。
- `--expected-source-count N`：多个本地附件的预期案例数；实际解析数量不符时不创建队列。
- `--resume`：复用已有队列和 lease 状态；必须同时传入原始 `queue` 返回的 `--output-dir <runDir>`。
- `--dry-run`：只查看将入队的 safe 样本。
- `--output-dir PATH`：高级覆盖项。正常新任务不传时，`queue` 自动创建
  `.poe-bd-research/runs/<runId>` 独立目录；已有队列不会被静默覆盖。

## No-Argument Behavior

如果 `$ARGUMENTS` 为空，不要先联网 dry-run，也不要直接启动完整 50 样本 / 5 worker 的 live crawl。先询问用户要怎么运行。

如果宿主提供交互式选择/确认工具（例如 Codex 的 choice/confirmation UI），优先发起一个选择问题。建议选项：

- `预检 5 个样本（推荐）`：只执行 `limit=5`、`--dry-run`，验证 poe.ninja/collector 可用，不创建实际队列。
- `小批量提取`：实际运行 `limit=20`，按队列逐案研究。
- `大批量提取`：实际运行 `limit=50`，按队列逐案研究。
- `恢复已有队列`：使用用户指定的 `runDir` 和 `limit`，并附加 `--resume`。不要把 `--resume` 只绑定到大批量。

如果宿主没有选择控件，退化为普通文字选项，等待用户回复。不要在用户选择前联网采样。

```text
请选择运行方式：
1. 预检 5 个样本（推荐，不入库）
2. 小批量提取：20 个样本，逐案处理
3. 大批量提取：50 个样本，逐案处理
4. 恢复已有队列：请给出原 runDir 和 limit
```

如果给示例，只给 skill 命令：

```text
/poe-bd-research --limit 5 --dry-run
/poe-bd-research --limit 20
/poe-bd-research --limit 50
/poe-bd-research --limit 10 --class "Blood Mage" --level-min 95 --level-max 95
/poe-bd-research --limit 20 --resume --output-dir .poe-bd-research/runs/<runId>
```

底层 `scripts/research_mature_builds.py` 命令是 agent 内部实现步骤，只在用户明确要求 CLI/debug 信息时展示。

## Progress

按阶段向用户报告：

1. `[Phase 1/5] Queue`：建立或恢复 safe queue。
2. `[Phase 2/5] Claim`：只领取一个 case。
3. `[Phase 3/5] Research`：当前 Agent 只分析这个完整 BD。
4. `[Phase 4/5] Accept`：把 safe proposal/review 交给 acceptance gate。
5. `[Phase 5/5] Status`：分别报告 accepted patterns、accepted deep records、
   transfer candidates/promotions、`unresolvedDeepRecordComponentCount`、deferred candidates 和 remaining。

当调用方明确要求研究循环业务结果标记时，最终回答的最后一行必须且只能包含一个：

```text
POE_RESEARCH_SUCCEEDED: yes
POE_RESEARCH_SUCCEEDED: no
```

只有请求数量的案例全部完成正式 accept、最终 status 没有 queued/claimed/accepting case，且 acceptance
报告计数与实际持久化结果一致时才输出 `yes`。queue/collector/claim/research/accept 任一步运行失败、
没有取得可继续使用的 `runDir`、案例未全部处理或缺少验收/持久化证据时必须输出 `no`。这个标记描述
研究业务结果，不等同于 Desktop turn 的 `completed` 状态；不得因为聊天 turn 正常结束就输出 `yes`。

## Workflow

下面的脚本命令是 agent 内部执行步骤。Codex 桌面用户不需要、也通常不能在会话框中执行这些命令。

1. 在项目根目录运行 queue：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py queue $ARGUMENTS
   ```

   Windows 可用：

   ```powershell
   .\.tools\uv\uv.exe run python scripts\research_mature_builds.py queue $ARGUMENTS
   ```

   live poe.ninja collector 可能需要数分钟；宿主命令的外层超时必须至少为 10 分钟
   （以毫秒配置时为 `600000ms`）。不得用 1–2 分钟的工具超时截断 collector，再把外层预算不足误报为
   `collector_failed`。若达到这个外层预算仍未返回，按 runtime failure 停止，不在同一 research turn
   重复 queue。

   非 dry-run 的默认 `queue` 会返回 `runId`、`runDir` 和 `nextCommandArgs.outputDir`。当前会话必须
   保存并在后续所有命令中原样使用这个 `runDir`；不得退回固定 `.poe-bd-research`。不同会话各自
   创建独立 run，因此可以并发研究。显式目录中已经存在队列时，除 `--resume` 外一律停止，不能覆盖。

   如果该命令返回 `collector_failed` / `source_unavailable` / `runtime_failed`，报告 safe error 并停止；不要调试源码。

2. 当前 Agent 领取一个 case；在该案例完成 accept 前，不得再领取下一案：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py claim --output-dir <runDir>
   ```

   `claim` 会在同一次原子操作中返回 `workerPrompt` 和 `reviewFile`。当前 Agent 必须直接遵守
   `workerPrompt`，不要把它转交给其他 agent，也不要手工复制 `leaseToken` 再执行第二条命令。
   `workerPrompt` 已内联运行边界、非权威 safe metadata、渐进读取流程和研究质量目标；它不含 raw
   mature build material，也不会提前塞入完整提交 schema。精确合同在写 review 前通过
   `review-contract` 即时读取。

   `worker-brief --lease-token <token>` 只用于恢复一个已经 claimed 的任务，不是正常 claim 后的必经
   步骤。

   多个本地附件必须在同一次 `queue` 中重复传入 `--source-file`，并传
   `--expected-source-count <附件数>`。只有返回的 `localSourceInputCount` 与预期一致后才能 claim；
   不得根据用户附件数自行宣称队列中还有未领取案例。

3. 当前 Agent 根据 `workerPrompt` 先检查分区清单：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py inspect --output-dir <runDir> --lease-token <leaseToken>
   ```

   再按 `skills -> gear -> passives -> config -> build` 顺序读取；若 `complete=false`，使用返回的
   `nextCursor` 继续读取同一分区：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py read --output-dir <runDir> --lease-token <leaseToken> --section skills
   ```

   需要定位某个具体名称时使用有界搜索；search 不能替代完整分区读取：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py search --output-dir <runDir> --lease-token <leaseToken> --query "Bonestorm" --section skills
   ```

   这些接口只输出结构化 transient evidence，不输出 raw XML、PoB code 或临时路径。当前 Agent
   必须先独立重建技能职责、轮转、机制链、装备/天赋职责、取舍和工具盲点；形成初步判断后，再用
   `query_research_memory(detail_level="summary")` 查重和对照，必要时只按 `record_ids` 深读少量记录。
   随后使用 `search_graph_components` / `resolve_graph_component` 解析组件。`propose_*` 只做候选
   schema、resolver 和 copy-safety 校验，不代表入库完成；所有候选仍必须写入 `workerPrompt` 指定的
   safe review artifact，由 accept 作为唯一 durable writer。

   独立重建和组件解析完成后，只针对会改变结论因果链的高风险机制做轻量校对。先用
   `explain_mechanic` / `search_mechanics` 查看当前本地静态机制资料，再用 `lookup_mechanic` 查询实时
   poe2wiki；工具未出现在首屏时使用宿主的 tool discovery 按精确名称查找。优先检查触发与手动施放、
   前置状态、资源生成/消耗、伤害转换、mutation / transform，不要为普通组件名称逐页查询。
   每次 `lookup_mechanic` 只查询一个精确页面或中央机制名称，不得把 `A / B` 组件名拼成一次查询；
   一个关系需要多页证据时，写多条关联同一对象的原子审计。每条 `mechanic_chain` 和
   `resource_engine` 都必须被至少一项 `mechanicAudit.affectedRecords` 精确引用，且 `claim` 必须写该
   对象真正依赖的最强因果结论，不能只审计一个较弱前提。
   `lookup_mechanic` 命中后，把其 `pageId`、`revisionId` 形成的 revision-pinned `sourceRef` 连同结论写入
   safe review 顶层 `mechanicAudit`。Wiki 只作机制解释的校对证据，不能替代来源实例归属、辅助兼容性、
   武器状态、Family 身份或数值 Judge；每项 supports / contradicts 还必须注明至少一种独立佐证。

4. 初步研究、memory 对照和组件解析完成后，读取当前 lease 的精确 review 合同：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py review-contract --output-dir <runDir> --lease-token <leaseToken>
   ```

   只使用该合同返回的 canonical role、axis 和 pattern 枚举，不得自造值。`role` 描述组件在 BD 中
   承担的功能，不等于唯一物理节点类型；以合同中的 `componentRoleNodeTypeCompatibility` 和 resolver
   证据为准。成功解析的组件应把 resolver 返回的 stable key 写入 `componentKey`。更细的轮转阶段、
   爆发窗口、证据身份或机制说明写入 `content`、`typedPayload`、`conditions` 或 `summary`。
   `artifactIdentity` 及记录中的 `sampleId`、`researchGroupId`、`caseRef`、`safeEvidenceRef`
   由 lease 注入，不要重复抄写。宿主没有 resolver 时，`supportPackages` 使用精确
   `skillName` / `supportNames`，升华和装备职责使用精确 `componentName`；accept 只做同一记录内
   唯一解析名称的 stable-key 替换，不替 Agent 推断职责或技能归属。

   随后让程序原子创建当前 lease 的 safe review 骨架：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py init-review --output-dir <runDir> --lease-token <leaseToken>
   ```

   只使用文件编辑工具或 `apply_patch` 编辑命令返回的 `reviewFile`。不得用 PowerShell here-string、
   内联 `ConvertTo-Json` 或 `Set-Content` 拼接整份 review；这些方式容易因转义、换行或编码导致运行态
   失败。骨架必须保持 UTF-8、两空格缩进的多行 JSON，Agent 后续根据 validate-only 结果精确修改
   role、query 或 componentKey。`already_exists` 表示保留现有工作，不能覆盖或重新初始化。

5. 写出 safe review 后，先运行正式验收逻辑的无副作用校验：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py accept --output-dir <runDir> --lease-token <leaseToken> --review-file <safe-review.json> --validate-only
   ```

   `validation_failed` 时按 `validationIssues` 自行 review 和修正，不得要求程序猜测或自动映射自造
   枚举。`readyForAccept=true` 只表示当前安全子集可以入库；只有
   `fullyResolvedForAccept=true` / `acceptanceMode=clean` 才表示 Build Family 可归档，且覆盖维度、
   候选和深度记录组件均无缺口。若返回
   `partial_with_deferred`，先修复 `component_type_mismatch`、错误 role/query/componentKey 等当前证据
   可解决的问题并重新校验；真实 `source_coverage_gap` 或经有界查询仍无法唯一解析的内容才允许保留
   暂缓。确认这些边界后，才去掉 `--validate-only` 正式运行：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py accept --output-dir <runDir> --lease-token <leaseToken> --review-file <safe-review.json>
   ```

6. 完成当前案例的 accept 后，才循环 claim/research/accept 处理下一案，直到 status 无 queued case：

   ```bash
   ./.tools/uv/uv run python scripts/research_mature_builds.py status --output-dir <runDir>
   ```

`accept` 返回的 `deferredReasonCounts` 是最终汇报的事实源。分别如实报告
`invalid_schema`、`ambiguous_endpoint_requires_reviewed_mapping`、`component_type_mismatch`、
`source_coverage_gap`、
`insufficient_research_depth` / `insufficient_case_research_depth`、`missing_deep_research_records`
等原因；不要把 schema 或深度失败改写成“等待 Judge/resolver 验证”。只有实际 reason 指向 Judge
时才可以这样描述。

每案还必须报告 `mechanicAuditEntryCount`、`mechanicAuditPinnedRevisionCount`、
`mechanicAuditLiveEvidenceStatus` 和 `mechanicAuditUnauditedHighRiskRecordCount`。只要提交了审计但
固定 Wiki 修订数为 0，就必须明确写“Wiki 审计未实际取得 live evidence”，不能把结构化
`mechanicAudit` 存在或 `acceptanceMode=clean` 描述成 Wiki 校对成功。

`deferredCandidateCount=0` 只表示 pattern/candidate 没有暂缓，不代表所有深度记录组件都已解析。
最终汇报必须区分 `unresolvedDeepRecordMentionCount` 与 `unresolvedUniqueComponentCount`。兼容字段
`unresolvedDeepRecordComponentCount` 仍表示 mention 次数；同一个组件在三条记录中未解析会计为 3，
不能误报为三个不同组件。任一值非零时，不得使用“全部完成且无暂缓”这类会掩盖解析缺口的表述。
最终汇报还必须逐案给出 `acceptanceMode`；`partial_with_deferred` 可以是有价值的部分入库，但不得
描述为 clean 验收。
正式 accept 后还应区分 `createdDeepRecordCount`、`updatedDeepRecordCount` 和
`addedDeepRecordEvidenceCount`；同一 Family 的既有知识增加来源证据时，不得误报为新建知识。

## Case Rules

- 一案一轮：一个 Researcher prompt 只能包含一个完整 BD。
- 串行处理：当前案例完成 accept 前，不得 claim 下一案。
- 默认不把上一案的 transient evidence 带入下一案；复用的是 queue、skill、脚本、工具和已验收记忆。
- 若 claim 返回 `active_case_in_progress`，继续当前案例，不得另领新案例。
- 若 claim 返回 `no_pending_cases`，停止领取。

## Researcher Checklist

- 一次案例生成多条共享 `research_group_id` 的 `DeepResearchRecord`；单条只回答一个主要问题。
- 同一研究组使用同一个已解析 `ascendancyKey`，并只把一个核心主技能标为 `primary_damage`；
  `clear_skill`、`boss_skill`、`triggered_payload`，以及投送 `triggered_payload` 或主伤载荷的 `trigger_host` 由程序自动
  参与 Family，不得重复写入 `typedPayload.familyCoreSkillKeys`。普通 `secondary_skill` 是 Family 内
  工具/变体；只有 generator、control 等其他副技能确实决定流派身份时，才把 stable key 写入该字段。
  support、装备、防御和资源方案不参与 `BuildFamily` 身份。
- 必须在整个 research group 中为每个已确认 Family 核心技能组填写 `typedPayload.supportPackages`；
  CoC/触发宿主和 triggered payload 也分别检查。每组至少两个已解析辅助；来源确实缺失或技能不接受
  普通辅助时，用 `supportCoverageExceptions` 写明 `source_coverage_gap` / `not_applicable` 和原因。
- 辅助与主动技能即使都已解析，也不代表二者机制兼容。凡声称某辅助为具体技能生成、转换、保留或放大
  某项机制，必须用 `support_skill_candidate` 或等价 typed graph helper 复核该精确配对；结果未知时保留
  caveat / verification task，不得写成已成立事实。
- `passiveAscendancy` 只有在记录包含 `ascendancy_shell`，并通过
  `typedPayload.ascendancyResponsibilities` 把具体升华 passive/notable/keystone 与职责对应时才算 covered；
  验收会核验节点确实属于当前升华，任意普通 notable 或 keystone 不足以证明升华职责已还原。
- `gearRoles` 只有在 `gear_synergy` 用 `typedPayload.gearResponsibilities` 关联已解析装备与具体职责时才算
  covered；至少要还原主技能来源、身份装备或主要缩放装备之一，只有防御/便利装备不能代表完整装备职责。
  若该维度为 `evidence_missing`，验收会暂缓 `mechanic_chain` 和 component transfer，避免把漏读身份装备
  后的错误机制写入 durable memory。
- 每项 `gearResponsibilities` 必须区分组件静态文本直接提供的固有职责，以及来源实例词缀、插入物、
  mutation / transform 或其他组件间接提供的职责。只有前者可以直接归因给该装备组件；后者必须把真实
  来源组件或转换前提写入结构化字段和条件，证据无法唯一归属时降为 caveat / open question，不能因为
  装备名称成功解析就把整份来源实例的效果归给该装备。
- 只有已确认的 `skill_package` / `mechanic_chain` 授权 Family 身份。`modelability_caveat`、`failure_mode`
  或 `open_question` 中未证实的技能不参与 Family，也不得在这些记录中填写 `familyCoreSkillKeys`。
- 装备读取若显示 `itemStates=["mutated"]`，依赖该随机实例的记录必须写
  `typedPayload.availability="source_specific_random"` 和 `sourceSpecificComponentKeys`。它可解释本案，
  但默认不进入 Create 召回；依赖该实例的 candidateReview 同样写
  `availability="source_specific_random"`，并在 `sourceSpecificComponentNames` 精确指出 candidate
  `components` 中对应的来源组件。accept 只用这些组件建立 observation 索引；组件没有稳定节点时保留
  无组件索引的案例备注，不生成 planner Pattern。
- `resource_engine` 若依赖法力偷取、普通药剂、装备词缀等没有物理图节点的机制，必须在
  `typedPayload.resourceMechanisms` 写精确的 lower_snake_case 标签（如 `mana_leech`、`mana_flask`）。
  正文提到但结构化身份缺失的记录会以 `missing_knowledge_identity` 暂缓，不能报告 clean。
- safe review 顶层必须填写 `caseCoverage`，分别审计 supports、rotation、passiveAscendancy、
  gearRoles、resourceDefense；状态只能是 `covered`、`evidence_missing`、`not_applicable`。
- safe review 顶层 `mechanicAudit` 只记录高风险事实声明，精确关联受影响的 record/candidate 标题，并
  使用 `supports`、`contradicts`、`silent`、`unavailable` 和 `keep`、`revise`、`defer`。Wiki 冲突却
  仍 keep、主动 defer、或没有独立 corroboration 的 wiki-only 对象会被最小范围暂缓；Wiki 不可用
  不会自动阻塞无关对象。
- 不得在 Wiki 审计中把 `A / B` 这类多个页面名拼成查询主题；查询中央机制或逐页查询，并让
  claim 覆盖 record/candidate 中实际使用的完整因果关系。`mechanic_chain` / `resource_engine` 未被
  mechanicAudit 引用会作为显式 advisory 报告，但不会由程序按技能名硬拒绝。
- 中文 `content` 原则上不超过 400 字，英文不超过 250 个单词。独立结论必须拆分；不可拆分的核心
  机制链才允许填写 `lengthExceptionReason` 后少量超出。
- 优先分别记录 skill package、mechanic chain、rotation、gear synergy、passive package、资源/防御
  引擎、设计取舍、失败模式和 modelability caveat；不要把整个案例分析塞进一条记录。
- 当前 Agent 必须重建具体技能职责、机制因果链、装备/天赋职责和可执行轮转，不能只输出属性共现与
  通用复验提醒。
- `rotation` 必须描述玩家操作顺序并写
  `typedPayload.knowledgeShape="player_action_sequence"`；`mechanic_chain` 必须描述状态因果链并写
  `typedPayload.knowledgeShape="state_causal_chain"`。
- pattern 至少关联两个不同的已解析组件；单组件候选只作为 observation，不得包装成可复用 pattern。
- 每个 pattern 明确填写 `transferScope`。`family` 表示仅限来源 Family；`component` 表示该 Family
  知识同时获得跨 Family 条件迁移资格，不会降低它在来源 Family 内的召回权重。只有候选解决可重复
  设计问题、具有明确因果链，并写出最低适用条件、排除条件、迁移理由和验证任务时，才能使用
  `component`。去掉当前职业、升华和流派名称后，该条件性结论仍须有意义；不确定时保持 `family`。
- 单案例不得使用 `global`，也不得自行提高置信等级。首次发现始终是 `case_observation`；后端只在
  结构相同的候选获得独立跨 Family 证据后晋升，公用知识最高为 `likely_pattern`。
- 没有 resolver 工具时仍提交组件名称、角色和 resolver 查询词，由 accept gate 统一补稳定 ID；不要
  因此删掉具体组件，也不要猜 ID。
- resolver 可见时先用 `search_graph_components` 按具体名称和类型发现候选，再用
  `resolve_graph_component` 确认稳定 ID。描述性短语不是组件名；模糊候选不能直接写 semantic edge。
- 在 validate-only 和正式 accept 前对每个最终对象做全对象语义闭环复核。组件、角色、因果或职责发生
  变化时，必须逐项重查 title、summary、content、conditions、failureConditions、typedPayload、
  applicability / exclusions、contextRequirements、plannerHint 和 verificationTasks；未逐项复核的旧字段
  不得原样沿用。

每个案例必须评估但不能强行编造这些设计轴：

- 升华 + 主技能：shell suitability，不是技能合法性。
- 主技能 + secondary skill：标 clear、boss、generator、payoff、movement、trigger host 等 role。
- 技能 + key passive / notable / keystone：必须 resolver-backed。
- 暗金 + 天赋点 / 技能：区分 required/enabling、optional/chase、budget substitute。
- support + active skill：单 pair 可作为图关系；多个 supports 共同决定机制时，保留完整关键组合，
  不要为了规避数量型规则而拆掉机制语义。
- scaling axis、weapon/base/stat priority、Spirit/reservation、defense package、mechanic chain、transition gate、failure mode、variant relation、modelability caveat。

合格的深挖应像这样：带有 Killing Palm、Flicker Strike + Perpetual Charge、Charged Staff、
Falling Thunder + Culmination II 的案例，不能只写“充能技能有协同”。需要还原 Killing Palm 获取
Power Charge，Flicker Strike 消费并由 Perpetual Charge 尝试保留，普通攻击积累 Combo，Falling
Thunder + Culmination II 在窗口中兑现爆发，同时说明 Charged Staff 对同一 charge 的竞争、无小怪
Boss 时的续接风险，以及装备与局部天赋如何支撑资源。应拆成技能包、机制链、轮转、装备/天赋职责和
失败模式等聚焦记录。

浅层反例：“该案例堆叠投射物、暴击、元素伤害和能量护盾，建议在 PoB 中继续验证。”这类文字没有
具体组件、因果、操作顺序或职责分工，只能作为 open question，不能成为主要 durable output。

## Safety

- queue/status/claim/review-contract/init-review/validate-only/accept 输出必须是 safe-only。
- `prompt` 仅保留兼容入口，返回 safe manifest 和迁移提示；不得再输出 raw-rich material。
- `inspect/read/search` 必须绑定当前有效 lease，且所有 read/search 响应都有数量和字符上限。
- missing/ambiguous endpoint 不得自动选择；最多 2 次 bounded repair，失败后写 manual mapping / source refresh。
- 单样本只能写 `case_observation`，不能宣称 common/usually/通常。
