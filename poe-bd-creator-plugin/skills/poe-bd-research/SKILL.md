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
- 一案一轮并串行处理：一个 Researcher prompt 只包含一个完整 BD；
  当前案例完成正式 accept 前不得再领取下一案。`active_case_in_progress` 表示继续当前案例，
  `no_pending_cases` 表示停止领取；默认
  不把上一案的 transient evidence 带入下一案。
- 工具未直接列在当前上下文时，先使用宿主提供的标准 tool discovery / tool search，按精确名称
  查找 `query_research_memory` 和 `graph_tool_query`；不要仅凭首屏工具列表断言 MCP 不可用。
- 用户在 Codex 会话框输入 `/poe-bd-research` / `$poe-bd-research` 是在请求 agent 执行 workflow，不是在执行 shell 命令。agent 必须自己用可用工具运行内部脚本；不要要求用户把 PowerShell/Python 命令复制到会话框或终端。
- 运行 `/poe-bd-research` / `$poe-bd-research` 时，不得修改仓库源码、测试、文档、schema、安装脚本或 plugin manifest。
- 不得调用调试/TDD/代码修改类 skill，不得新增测试或现场修脚本。唯一允许的文件编辑是使用
  文件编辑工具或 `apply_patch` 编辑当前 lease 的 `reviewFile`；不得编辑其他 artifact 或仓库文件。
- 只允许写入 `--output-dir` 下的队列/验收 artifact，以及 OS temp 下的 transient packet。
- queue/status/claim/review-contract/init-review/validate-only/accept 必须保持 safe-only；inspect/read/search
  必须绑定当前有效 lease，并保持有界响应。missing/ambiguous endpoint 不得自动选择，最多进行 2 次
  bounded repair，失败后记录 manual mapping / source refresh。
- `prompt` 仅保留兼容入口，只能返回 safe manifest 和迁移提示，不得输出 raw-rich material。
- 单样本只能形成 `case_observation`，不能宣称 common、usually 或“通常”。
- 如果 queue、collector、claim、prompt 或 accept 失败，只报告 safe error 并停止。典型状态是 `collector_failed`、`source_unavailable` 或 `runtime_failed`。
- 如果用户需要修复失败原因，明确告诉用户这需要另开普通开发请求；不要在本次 research runtime 中临场改代码。

## Options

`$ARGUMENTS` 可包含：

> 快速粘贴模式：`$ARGUMENTS` 允许直接包含裸 PoB import code、pobb.in/pastebin 链接或 raw XML
> （例如 `/poe-bd-research 研究一下这个bd eNrt...`）。这是受支持的快速测试用法：当前 Agent
> 应把识别出的 code/链接内容保存到 OS 临时目录的本地文件（不要写进仓库、runDir 或任何运行
> 产物目录），再执行 `queue --source-file <临时文件>` 走标准单案例流程。**不要把 code 原文拼进
> `<research-cli> queue ...` 的命令行参数**：raw code 会进入进程参数、shell 历史和日志，也容易
> 超过命令行长度限制。链接型输入先用宿主 webfetch 取回内容再落临时文件；实在无法本地化的
> 才提示用户另存为文件。

- `--limit N`：从 poe.ninja 当前 softcore trade league 取样。底层 CLI 默认 50；交互式 skill 无参时不要静默启动 50。
- `--league current|<league-url>`：透传 poe.ninja league（默认 `current`）。
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

如果宿主没有选择控件，退化为普通文字选项，等待用户回复。不要在用户选择前联网采样。`$ARGUMENTS`
若包含裸 PoB code/链接（快速粘贴模式），不要询问运行模式，直接按下方"快速粘贴模式"落临时文件并
走 `queue --source-file`（见 Options）。

当本 skill 由 `poe-bd-research-loop` 编排触发时，child 收到的固定 prompt 已携带 `--limit` 等参数
（`$ARGUMENTS` 非空），直接按参数执行，不再询问交互模式；不得把 loop 无人值守场景当成普通
交互式无参调用。

用户明确要求示例时，只展示与所选模式对应的一条 skill 命令，例如
`/poe-bd-research --limit 5 --dry-run` 或 `/poe-bd-research --limit 20`，不要同时罗列所有组合。

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

### 运行绑定

开始第一次 queue 前，一次性解析并冻结运行前缀；后续所有命令复用它，不得依赖调用时 cwd：

1. `repoRoot` 优先使用当前宿主由安装器管理的 `poe_knowledge_mcp`（或任一 `poe_*_mcp`）条目中的
   `cwd`；若宿主不暴露启动
   配置，则使用 `POE_BD_CREATOR_DIR`，再否则解析当前已加载 `SKILL.md` 的真实路径（跟随 symlink /
   junction）并向上查找仓库根。候选必须同时包含 `pyproject.toml`、`server/main.py` 和
   `scripts/research_mature_builds.py`，且必须能规范化为绝对路径；MCP `cwd` 为相对值或不可见时改走
   后续发现方式。缺失或歧义时停止，不得使用当前 cwd、按目录名猜测或全盘搜索。
2. `uvCommand` 优先使用同一 MCP 条目中的 `command`；OpenCode 使用 `command[0]`，但仅在可执行文件名
   为 `uv` / `uv.exe` 时采用，不能把 Codex bundle 的 `node` launcher 当成 uv。相对 command 必须
   以已验证的 `repoRoot` 解析为绝对路径。宿主未暴露适用条目时，严格复用安装器的选择顺序：
   `repoRoot/.tools/uv/uv.exe`、`repoRoot/.tools/uv/uv`、PATH 中的 `uv`；PATH 命中后也解析为绝对路径。
   没有可执行的 `uvCommand` 时停止并提示重新运行 installer/doctor，不得假定仓库一定附带 `.tools/uv`。
3. 冻结 `<research-cli>` 为
   `<uvCommand> run --project <repoRoot> python <repoRoot>/scripts/research_mature_builds.py`。尖括号表示已
   验证的绝对参数，不是字面量；路径含空格时保持为独立且正确引用的参数。不得把解析结果写回
   Skill、仓库或 review artifact。

### 逐案流程

0. 参数预处理（快速粘贴模式）：执行 queue 前先检查 `$ARGUMENTS`。若其中包含裸 PoB import code
   （`eNrt...` / `AIAAA...` 等长 base64 串）、pobb.in/pastebin 链接或 raw XML（例如用户直接写
   `研究一下这个bd <code>`），把识别出的材料保存为 OS 临时目录下的单个本地文件
   （命名如 `quick-case-<短hash>.txt`；不写进仓库、runDir 或运行产物目录），然后把该位置的
   `$ARGUMENTS` 替换为 `--source-file <临时文件>` 再继续；链接先用宿主 webfetch 取回内容再落盘。
   临时文件与 transient packet 同级由系统清理，不需要手动删除。若 `$ARGUMENTS` 只有轻量选项则
   跳过本步。

1. 运行 queue：

   ```bash
   <research-cli> queue $ARGUMENTS
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
   <research-cli> claim --output-dir <runDir>
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
   <research-cli> inspect --output-dir <runDir> --lease-token <leaseToken>
   ```

   再按 `skills -> gear -> passives -> config -> build` 顺序读取；若 `complete=false`，使用返回的
   `nextCursor` 继续读取同一分区：

   ```bash
   <research-cli> read --output-dir <runDir> --lease-token <leaseToken> --section skills
   ```

   需要定位某个具体名称时使用有界搜索；search 不能替代完整分区读取：

   ```bash
   <research-cli> search --output-dir <runDir> --lease-token <leaseToken> --query "Bonestorm" --section skills
   ```

   这些接口只输出结构化 transient evidence，不输出 raw XML、PoB code 或临时路径。完整研究方法以
   本次 `claim` 返回的 `workerPrompt` 为准；不得跳过其中的关键顺序：先读完全部分区并独立重建案例，
   再查询 Research Memory，随后以 `search_graph_components` 发现候选并用
   `resolve_graph_component` 确认 stable key。`propose_*` 只校验候选，不代表入库；accept 仍是唯一
   durable writer。

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
   <research-cli> review-contract --output-dir <runDir> --lease-token <leaseToken>
   ```

   该响应中的模板、`allowedValues`、`componentRoleNodeTypeCompatibility` 和 `rules` 是本次 lease 的
   精确事实源，必须全部遵守，不得在 Skill 中另行推断或自造枚举。身份字段由 lease 注入；组件解析、
   resolver 不可用时的精确名称回退，以及各类 typed payload 的填写方式均按该合同执行。

   随后让程序原子创建当前 lease 的 safe review 骨架：

   ```bash
   <research-cli> init-review --output-dir <runDir> --lease-token <leaseToken>
   ```

   只使用文件编辑工具或 `apply_patch` 编辑命令返回的 `reviewFile`。不得用 PowerShell here-string、
   内联 `ConvertTo-Json` 或 `Set-Content` 拼接整份 review；这些方式容易因转义、换行或编码导致运行态
   失败。骨架必须保持 UTF-8、两空格缩进的多行 JSON，Agent 后续根据 validate-only 结果精确修改
   role、query 或 componentKey。`already_exists` 表示保留现有工作，不能覆盖或重新初始化。

5. 写出 safe review 后，先运行正式验收逻辑的无副作用校验：

   ```bash
   <research-cli> accept --output-dir <runDir> --lease-token <leaseToken> --review-file <safe-review.json> --validate-only
   ```

   `validation_failed` 时按 `validationIssues` 自行 review 和修正，不得要求程序猜测或自动映射自造
   枚举。`readyForAccept=true` 只表示当前安全子集可以入库；只有
   `fullyResolvedForAccept=true` / `acceptanceMode=clean` 才表示 Build Family 可归档，且覆盖维度、
   候选和深度记录组件均无缺口。若返回
   `partial_with_deferred`，先修复 `component_type_mismatch`、错误 role/query/componentKey 等当前证据
   可解决的问题并重新校验；真实 `source_coverage_gap` 或经有界查询仍无法唯一解析的内容才允许保留
   暂缓。确认这些边界后，才去掉 `--validate-only` 正式运行：

   ```bash
   <research-cli> accept --output-dir <runDir> --lease-token <leaseToken> --review-file <safe-review.json>
   ```

   正式 accept 前必须逐项核对提交前自检（与 `review-contract` 的 `mandatoryChecks` 一一对应）：
   1) 暗金/lineage 宝石已标注 unique 身份（`uniqueGemDiagnostics.unlabeledUniqueGemNames` 为空，
      或非空时已补 unique_enabler role / open_question / modelability_caveat 声明）；
   2) `jewelCounts` 中已分配珠宝槽无珠宝物品时，review 已显式声明珠宝状态（无 `unresolved_jewel_sockets`
      暂缓）；
   3) Spirit/reservation 预算已写入资源记录；
   4) 每个启用技能组的 supports 已完整打包或经 `supportCoverageExceptions` 声明（无
      `supportCoverageBlockedByStructuredOmission`）；
   5) support 机制语义均有证据链，无凭名字推断的表述；
   6) Memory 对照用 stable key：先 search_graph_components + resolve_graph_component 解析
      ascendancy/class，再以 stable key 过滤 `query_research_memory`，并检查
      `familyRecordCoverage / familyRecordIndex / familyPremiseCatalog` 逐条对照既有同族知识；
   7) config 条件三栏表：packet 每个 `condition*` 都有"条件 → 来源组件 → 验证状态"，无来源假设
      已写成 modelability caveat；
   8) 装备全覆盖：每个装备槽位在记录中"结构化组件 / content 文本 / 显式 not_applicable"三选一；
   9) 未猜 key 路径：所有组件先 search 再 resolve，支持宝石注意 `Items/Gem` 与 `Items/Gems` 两种
      metadata 路径；
   10) silent / unavailable 已沉淀：语料无文本或 `lookup_mechanic` 返回 silent 的高价值机制已写入
       caveat / verification task；
   11) 非 Family-core 技能组 supports 已写入记录内容或 secondary supportPackages；
   12) resource_engine / mechanic_chain 因果方向（生成 vs 消费）已核对并与既有同组件 Family 记录
       对照；
   13) 任何 unresolved 计数已先对该组件名 search_graph_components 再定性，未把图中存在的组件误报为
       source gap。

6. 完成当前案例的 accept 后，才循环 claim/research/accept 处理下一案，直到 status 无 queued case：

   ```bash
   <research-cli> status --output-dir <runDir>
   ```

7. 只有最终 status 显示全部请求案例均为 `accepted` 后，调用
   `cleanup_completed_task_runtime(task_kind="research", task_id=<queue 返回的 runId>)`。它删除 queue、
   safe review、acceptance 报告和对应 transient packet，但保留已经写入的 Research Memory。若任务
   尚未全部 accepted，工具会拒绝清理，不能手工删目录绕过。

`accept` 返回的 `deferredReasonCounts` 是最终汇报的事实源。分别如实报告
`invalid_schema`、`ambiguous_endpoint_requires_reviewed_mapping`、`component_type_mismatch`、
`source_coverage_gap`、
`insufficient_research_depth` / `insufficient_case_research_depth`、`missing_deep_research_records`、
`unresolved_jewel_sockets`
等原因；不要把 schema 或深度失败改写成“等待 Judge/resolver 验证”。只有实际 reason 指向 Judge
时才可以这样描述。`unresolved_jewel_sockets` 的处置：inspect 的 `jewelCounts.status` 为 `ok` 且
存在已分配珠宝槽无珠宝物品时，review 必须显式声明珠宝状态（空置或已插宝石及 radius 条件）；
`tree_data_missing` 表示无法计数，允许保留暂缓但须在报告中说明；packet 缺失时需重新 queue。

每案还必须报告 `mechanicAuditEntryCount`、`mechanicAuditPinnedRevisionCount`、
`mechanicAuditLiveEvidenceStatus` 和 `mechanicAuditUnauditedHighRiskRecordCount`。只要提交了审计但
固定 Wiki 修订数为 0，就必须明确写“Wiki 审计未实际取得 live evidence”，不能把结构化
`mechanicAudit` 存在或 `acceptanceMode=clean` 描述成 Wiki 校对成功。

每案还必须报告 `uniqueGemDiagnostics`：`uniqueGemCandidates`（来源中的 lineage/暗金宝石）、
`unlabeledUniqueGemNames`（被提及但未标注 unique 身份）与 `uniqueGemStatusUnknownNames`（语料无法
确认，不阻塞）。`unlabeledUniqueGemNames` 非空时，不得把该案描述为暗金身份已全部标注。

`deferredCandidateCount=0` 只表示 pattern/candidate 没有暂缓，不代表所有深度记录组件都已解析。
最终汇报必须区分 `unresolvedDeepRecordMentionCount` 与 `unresolvedUniqueComponentCount`。兼容字段
`unresolvedDeepRecordComponentCount` 仍表示 mention 次数；同一个组件在三条记录中未解析会计为 3，
不能误报为三个不同组件。任一值非零时，不得使用“全部完成且无暂缓”这类会掩盖解析缺口的表述。
最终汇报还必须逐案给出 `acceptanceMode`；`partial_with_deferred` 可以是有价值的部分入库，但不得
描述为 clean 验收。
正式 accept 后还应区分 `createdDeepRecordCount`、`updatedDeepRecordCount` 和
`addedDeepRecordEvidenceCount`；同一 Family 的既有知识增加来源证据时，不得误报为新建知识。

## Researcher Checklist

`workerPrompt` 与当前 lease 的 `review-contract` 已覆盖研究顺序、Family 身份、案例覆盖、迁移范围和
结构化字段合同。这里仅保留二者未完整表达的补充检查；冲突时以运行时合同为准。

- 补充研究（对同一 source 案例的追加 run，例如补录珠宝、暗金或 Spirit 维度）必须**复刻首轮
  identity 记录结构**：Family 核心技能组件（primary_damage，以及自动参与身份的
  clear_skill / boss_skill / triggered_payload 组件和 typedPayload.familyCoreSkillKeys）必须与首轮
  完全一致。Family key 由 (ascendancy, primary, secondary) 确定性推导，遗漏任一 secondary 身份
  组件就会产生 sibling family 分裂——同一个 BD 的知识会分散到多个档案夹，系统只有提示不会自动
  合并。无法确认首轮身份结构时，先用 `query_research_memory` 的 familyRecordCoverage 核对既有
  Family 的 secondary 集合，再写 identity 记录。
- 辅助与主动技能即使都已解析，也不代表二者机制兼容。凡声称某辅助为具体技能生成、转换、保留或放大
  某项机制，必须用 `support_skill_candidate` 或等价 typed graph helper 复核该精确配对；结果未知时保留
  caveat / verification task，不得写成已成立事实。
- 每项 `gearResponsibilities` 必须区分组件静态文本直接提供的固有职责，以及来源实例词缀、插入物、
  mutation / transform 或其他组件间接提供的职责。只有前者可以直接归因给该装备组件；后者必须把真实
  来源组件或转换前提写入结构化字段和条件，证据无法唯一归属时降为 caveat / open question，不能因为
  装备名称成功解析就把整份来源实例的效果归给该装备。
- safe review 顶层 `mechanicAudit` 只记录高风险事实声明，精确关联受影响的 record/candidate 标题，并
  使用 `supports`、`contradicts`、`silent`、`unavailable` 和 `keep`、`revise`、`defer`。Wiki 冲突却
  仍 keep、主动 defer、或没有独立 corroboration 的 wiki-only 对象会被最小范围暂缓；Wiki 不可用
  不会自动阻塞无关对象。
- 不得在 Wiki 审计中把 `A / B` 这类多个页面名拼成查询主题；查询中央机制或逐页查询，并让
  claim 覆盖 record/candidate 中实际使用的完整因果关系。`mechanic_chain` / `resource_engine` 未被
  mechanicAudit 引用会作为显式 advisory 报告，但不会由程序按技能名硬拒绝。
- 中文 `content` 原则上不超过 400 字，英文不超过 250 个单词。独立结论必须拆分；不可拆分的核心
  机制链才允许填写 `lengthExceptionReason` 后少量超出。
- `rotation` 必须描述玩家操作顺序并写
  `typedPayload.knowledgeShape="player_action_sequence"`；`mechanic_chain` 必须描述状态因果链并写
  `typedPayload.knowledgeShape="state_causal_chain"`。
- pattern 至少关联两个不同的已解析组件；单组件候选只作为 observation，不得包装成可复用 pattern。
- 机制签名词缀驱动记录因果结论时，必须独立成记录（gear_synergy/mechanic_chain）或至少进入
  `mechanicAudit`，不得只出现在 content 字符串。签名词缀家族包括：极端掷骰
  （"Rolls only the minimum or maximum Damage value"）、最低抗性伤害
  （"based on their Lowest Resistance"）、元素地面交互（Wind Skills / Elemental Ground）、
  implicit "Allocates <passive>"、"Grants Skill: Level N <skill>"、Surpassing 额外投射、
  "X% chance to not remove Charges but still count as consuming them"。签名词缀驱动的审计必须带
  revision-pinned `lookup_mechanic` sourceRef 和至少一项独立佐证。
- 暗金宝石（unique skill/support gem、unique jewel）与普通宝石不同：unique support gem 自带固定
  词缀（如 Ailith's Chimes / Uhtred's 系列），unique jewel 常带位置化效果。凡案例使用暗金宝石，
  必须在记录中标注其 unique 身份（组件 role 保持 support_modifier/unique_enabler），radius/Time-Lost
  jewel 的"Small/Notable Passive Skills in Radius also grant X"词缀必须原样保留在
  conditions/verificationTasks 中，并把半径覆盖的已分配天赋类型写入 conditions；不得把 radius
  增益当作全局增益。数据缺口：语料 unique jewel 表缺 PoE2 Time-Lost 系列（其 unique 在
  Uniques/Special/Generated.lua，提取器未摄入），Historic timeless jewels（base "Timeless
  Jewel"）因引擎 conquered 规则为空而排除出候选；来源实例中出现的 radius jewel 若无法从语料取
  文本，以 PoB 引擎读回为准并在 modelability_caveat 记录数据缺口。
- 跨组件异常组合（如混沌伤害节点、荆棘与中毒机会、低血分支并存）无法闭环时，建 `open_question`
  记录结构化疑点（异常组件、可能机制、已排除项、验证任务），不得塞进 modelability caveat；
  `modelability_caveat` 只用于"机制存在但 PoB 无法建模/未证实数值"。`read` 输出中的
  cross-axis advisory 是提示不是 gate。
- mechanicAudit 除 `mechanic_chain` / `resource_engine` 强制项外，凡记录因果结论依赖签名词缀、
  或主输出链接存在未验证辅助时，也必须审计或写验证任务。
- 宽召回 memory 查询使用 `query_research_memory(detail_level="summary",
  response_profile="create_compact")`；只有深读指定记录时才 `detail_level="record"`。
  被动分区读取可用 `read --section passives --node-type notable|keystone|jewel_socket|normal`
  过滤，减少全量分页开销。
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
