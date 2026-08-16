---
name: poe-bd-research-loop
description: Orchestrate a PoE2 build-research plan as user-visible Codex Desktop sidebar tasks. Use when the user provides a Markdown class/level/count plan, asks to run or resume the research/review/fix/conditional-rereview loop, checks its phase, pauses it at a phase boundary, or retries a blocked visible task.
---

# PoE BD Research Loop

把当前 Codex Desktop 任务作为控制任务；每个研究项创建一个用户可在侧边栏直接打开的新任务。
状态 MCP 只负责 Markdown、claim、检查点、并发锁和恢复，不创建任务、不调用模型、不转发聊天。

## 必需能力

开始任何领取前，确认当前 Desktop 暴露以下原生任务工具：

```text
list_projects
create_thread
list_threads
read_thread
send_message_to_thread
set_thread_title
navigate_to_codex_page
```

缺少任一工具时明确停止，不得领取任务，不得回退到 Codex app-server、SDK、CLI、后台进程、
subagent 或聊天内容转发。

`wait_threads` 是首选但非必需的增量等待能力。当前 Desktop 暴露它时必须优先使用；未暴露时才
允许按下文的 300 秒低频 `list_threads` fallback 监控，不能忙轮询。

## 可移植路径与状态服务

不得把维护者机器的盘符、用户名或 checkout 绝对路径写入 Skill、提示词或 metadata。开始任何
状态调用或任务创建前，一次性解析并冻结以下路径：

1. `creatorRoot`：优先使用环境变量 `POE_BD_CREATOR_DIR`；否则从当前已加载
   `SKILL.md` 的真实路径向上查找同时包含 `pyproject.toml`、`server/main.py`，且当前 Skill 位于
   以下任一布局的根目录：源码布局 `poe-bd-creator-plugin/skills/poe-bd-research-loop/SKILL.md`，
   或发布 bundle 布局 `skills/poe-bd-research-loop/SKILL.md`。候选必须唯一且通过这些标记校验；
   不得采用当前 shell cwd、临时目录或仅名称相似的目录。若自动发现的 bundle 根不是 Codex
   Desktop 中可唯一识别的项目，则在 claim 或任何写操作前停止，并要求用户把
   `POE_BD_CREATOR_DIR` 指向真实源码 checkout。
2. `orchestratorRoot`：优先使用环境变量 `POE_RESEARCH_ORCHESTRATOR_DIR`；否则只检查
   `creatorRoot` 的同级目录 `poe-research-orchestrator`。候选必须同时包含 `pyproject.toml`、
   `scripts/invoke_mcp.py` 和 `research-notes/`。缺失或歧义时在任何 claim/mutation 前停止，并提示
   用户设置 `POE_RESEARCH_ORCHESTRATOR_DIR`；不得全盘搜索或猜测其他路径。
3. `notesRoot = orchestratorRoot/research-notes`。向 child 发送固定提示词时，用规范化后的绝对
   `notesRoot` 替换 `${notesRoot}`。

状态更新优先调用已暴露的 `poe_research_orchestrator` MCP 工具。若当前任务没有直接暴露该 MCP，
只允许使用 `orchestratorRoot/scripts/invoke_mcp.py` bridge；bridge 仍通过 MCP 协议调用纯状态接口。
依次使用以下第一个存在的 Python 启动方式：

1. `orchestratorRoot/.venv/Scripts/python.exe`；
2. `orchestratorRoot/.venv/bin/python`；
3. PATH 中的 `uv`，以 `uv run --project <orchestratorRoot> python
   <orchestratorRoot>/scripts/invoke_mcp.py` 运行；
4. `creatorRoot/.tools/uv/uv.exe` 或 `creatorRoot/.tools/uv/uv`，使用同一 `uv run --project` 参数。

把最终命令前缀记为 `<bridge>`；下文的 `<bridge> validate ...`、`<bridge> claim ...` 等表示在同一
已验证前缀后追加参数，不是让用户手工输入。没有可用启动方式时停止，不得编辑 bridge、临时编写
MCP client、直接导入状态模块或直接修改 Markdown/sidecar。环境变量只作为本机配置读取，不能把
解析后的绝对值写回仓库或发布包。

## 固定配置与提示词

研究任务：

```text
model: gpt-5.6-sol
thinking: medium
prompt: /poe-bd-research --limit ${num} 抓 ${level} 级 ${class} 的成熟 BD 样本进行研究

最终回答最后一行必须是 `POE_RESEARCH_SUCCEEDED: yes` 或 `POE_RESEARCH_SUCCEEDED: no`。只有请求数量的案例全部正式 accept、最终 remaining 为 0，且报告计数与实际持久化结果一致时才能输出 yes；任何运行失败、案例未完成或证据缺失都输出 no。
```

固定 prompt 必须携带 `--limit ${num}`：`/poe-bd-research` 的"无参数必询问"交互规则不适用于本
loop 的无人值守 child，带参数后 child 直接执行、不询问。研究对象是成熟 BD 样本，不是"模板"
（reference builds 只是校准摘要，见 AGENTS.md）。

Review 在同一任务中发送：

```text
model: gpt-5.6-sol
thinking: xhigh
prompt: 只做审查，不修改代码、数据库或运行产物。基于本任务 runDir 中的 safe review、accept/status 报告和实际入库结果，核对：五项研究覆盖是否有具体证据；核心技能职责、身份装备、天赋、触发、转换和资源机制是否事实一致；Family、Pattern、transfer scope、未解析项和暂缓项是否合理；报告计数是否与实际写入一致。

（"五项研究覆盖"指 review-contract 的 caseCoverage 五维：supports / rotation / passiveAscendancy / gearRoles / resourceDefense。）

涉及暗金、天赋、触发或转换的关键结论，应使用当前静态资料或机制工具复核，不能因为组件成功解析就认为机制解释正确。

先独立完成审查，再简单对照 ${notesRoot}/resolved-issues.md 和 ${notesRoot}/unresolved-issues.md。Findings 按严重度优先，给出对应 sourceCaseRef、recordId、patternId 或 artifact 位置，并区分：单案例 LLM 判断错误、来源证据不足、确定性的工作流缺陷。只报告当前证据能复现的问题，不要把单个语义错误直接扩展成全局硬规则。没有明显问题时明确说明。
```

Fix 无条件在 review completed 后于同一任务发送；没有问题时由 Agent 自行确认无需修复：

```text
model: gpt-5.6-sol
thinking: xhigh
prompt: 先核实上一步 review 的 findings，不要未经验证直接照单修改。本 turn 进入普通开发修复阶段，不继续 queue、claim 或新增案例的研究入库流程。

按问题性质处理：
- 单案例知识错误：如果能精确定位 sourceCaseRef、recordId、patternId，并能根据现有 artifact、来源证据或机制工具确认正确结论，优先精确修复错误字段、证据或关系，保留仍然正确的研究成果；只有无法可靠修复的最小数据单元才清理，不修改通用工作流。无法安全原位修复时，先写入并验证修正版，再清理被替代的数据。
- 可稳定复现的确定性工作流缺陷：实施最小、通用修复，补聚焦回归测试，并运行 quick 验证；必要时只重新处理明确受影响的本次 sourceCaseRef，不重新研究或清理无关数据。
- 来源不足、语义不确定、难度高或需要产品取舍的问题：不要强行程序化，记录到 ${notesRoot}/unresolved-issues.md。

不得按具体职业、技能、暗金或单一案例硬编码，不做无关重构，不以牺牲 Researcher 分析灵活度换取表面通过。清理污染数据前必须确认影响范围和来源归属，优先清理错误 evidence、关系或记录，而不是整个 run、Family 或 Pattern；存在其他有效来源支持的共享数据不得误删。完成后分别核对修复、保留和删除的数据，以及数据库实际增量。

每个写入或更新的修正版都必须做全对象语义闭环复核，不能只复核 finding 点名的字段。组件、角色、因果或职责变化时，逐项重查 title、summary、content、conditions、failureConditions、typedPayload、applicability / exclusions、contextRequirements、plannerHint 和 verificationTasks；未逐项验证的旧字段不得原样沿用。装备职责还必须区分组件静态文本直接提供的固有职责，与来源实例词缀、插入物、mutation / transform 或其他组件间接提供的职责；后者必须保留真实来源组件或转换前提，证据不能唯一归属时不得写成该装备的固有职责。写入后重新读取完整持久化对象，对照 finding、修正版和预期增量，确认没有陈旧字段或错误来源关系后才能报告已修复。

修复并验证成功的问题精炼记录到 ${notesRoot}/resolved-issues.md；真正未解决的问题才写入 ${notesRoot}/unresolved-issues.md，写入前检查同义条目。若 review 没有可执行问题，不修改代码、数据或 notes，直接说明无需修复。

修正 Research Memory 的唯一合法通道是 durable writer：同 case 补录（相同 PoB 文本重新 queue + accept；CLI 用 `research_mature_builds.py queue --re-research <旧run目录> [--supplement-focus ...]` 从旧 run 的 quarantine 重建案例为补充研究轮，accept 要求 created+updated ≥1 否则判定无效）或 `server/knowledge/research_maintenance.py` 的 `calibrate_phase4_research_contract_v1` / `remove_exclusive_research_sources` / `cleanup_legacy_research_memory`（见 docs/phases/04_research_memory.md「存量修正通道」）。不得绕过 acceptance 直接改库，也不得手工编辑 SQLite、safe review 或运行产物；只删除错误数据而没有保留修正版时不得输出 yes。

最终必须单独输出一行 `POE_FIX_DATA_REPAIRED: yes` 或 `POE_FIX_DATA_REPAIRED: no`。只有实际写入、更新、重建或替换了修正后仍保留在数据库中的研究数据时才输出 yes；纯代码、测试、notes、artifact 修改，或只删除错误数据而没有保留修正版时输出 no。
```

只有 Fix 输出 `POE_FIX_DATA_REPAIRED: yes` 时，才在同一任务发送复审：

```text
model: gpt-5.6-sol
thinking: xhigh
prompt: 只复审上一步 Fix 实际修复并保留在数据库中的研究数据，不扩大到未修改数据，不进行新研究或代码修复。基于原 review findings、Fix 结果、runDir artifact 和实际数据库内容，核对修正版的事实、证据、关系、Family/Pattern 和计数是否正确。

对每个修正版重新读取完整持久化对象，检查全对象语义闭环；特别核对组件或职责变化后是否仍残留旧的 conditions、typedPayload、contextRequirements、plannerHint、verificationTasks 或错误来源归属，不能只复查 Fix 声称修改的字段。

如果修正版正确，不修改任何数据，明确说明复审通过。如果仍然错误，不再尝试第二次修复；确认 sourceCaseRef、recordId、patternId、来源归属和共享关系后，只清理仍然错误的最小数据单元，保留未受影响及其他来源支持的数据，并核对清理后的数据库实际结果。

复审发现的错误无论清理是否成功，都精炼记录到 ${notesRoot}/post-fix-review-issues.md；写入前检查同义条目，记录对应 task/thread、sourceCaseRef、recordId、patternId、错误表现、清理范围和结果。复审通过时不要写入该文档。
```

提示词正文必须逐字使用上面的固定文本，只替换 `${num}`、`${class}`、`${level}`、`${notesRoot}`。
`${notesRoot}` 必须是本轮预先解析并冻结的规范化绝对路径。不要要求 JSON
输出，不要附加结构化 schema。Research 与 Fix 末行的单值标记只用于条件分支，不是结果 schema。
研究首条消息中的 skill mention 不得省略。只使用已安装插件的 `/poe-bd-research` 入口，不附加
仓库内 `SKILL.md` 的本地文件链接；否则同一 skill 会以安装版和源码版重复出现在任务中。

## 取得并校验任务文档

1. 从用户消息、附件或 `/mention` 取得原 `.md` 文件的稳定本地绝对路径。不得复制、猜测默认
   路径或改用临时副本。
2. 调用 `validate_poe_research_plan(plan_path)`。MCP 未直接暴露时使用：

   ```text
   <bridge> validate --plan '<绝对路径>'
   ```

3. `ok=false`、路径缺失、开放阻断问题或旧检查点待核对时停止并报告安全状态。
4. 启动、恢复或查询阶段都以 `get_poe_research_status(plan_path)` 为检查点事实源；bridge 为
   `status --plan '<绝对路径>'`。
5. 调用 `list_projects`，按规范化绝对路径精确选择本轮已冻结的 `creatorRoot`。没有唯一匹配
   时停止；不要创建 projectless 或 worktree 任务。

## 每项任务的状态机

### 1. 领取与创建可见任务

1. 调用 `claim_next_poe_research_task(plan_path, workflow_version=2)`；bridge 为
   `claim --plan '<绝对路径>' --workflow-version 2`。`workflow_version=2` 启用条件复审；不得省略。
2. 若返回 `paused`、`completed`、`reconcile_legacy` 或 `inspect_and_retry`，按对应恢复规则处理，
   不创建新任务。
3. 对新 claim 调用 `create_thread`：
   - target：上一步精确选中的 `creatorRoot` 本地项目；
   - model：`gpt-5.6-sol`；
   - thinking：`medium`；
   - prompt：固定 research 提示词。
4. 创建成功后，立即设置标题
   `PoE Research · ${class} L${level} · ${task_id}`，并调用 `navigate_to_codex_page(thread_id)`，
   让用户可直接看到任务。
5. 调用 `record_poe_research_phase_started`，传入
   `task_id + claim_id + thread_id + phase=research + expected_phase=creating_thread`。bridge 为：

   ```text
   <bridge> begin --plan '<绝对路径>' --task-id '<task>' --claim-id '<claim>' --thread-id '<thread>' --phase research --expected-phase creating_thread
   ```

### 2. 只监控状态，不转发正文

Research、review 和 rereview 通常各约 20 分钟，fix 通常不少于 10 分钟。按这个量级设计监听，
不要把长阶段当成需要高频状态播报的短命令。

1. 已绑定 thread 后，若 Desktop 暴露 `wait_threads`，对单一目标使用紧凑增量等待：携带该
   `hostId` 和上一快照的 `afterCursor`，设置 `timeoutMs=300000`。它在任务完成或需要关注时会提前
   返回；超时只表示继续等待，不是需要向用户报告的事件。始终更新 cursor，禁止重复消费已返回
   内容。
2. `wait_threads` 超时且目标仍为 `active` 时，状态未变化时不得发送 commentary，不得调用
   `read_thread`，也不得重复调用 `get_poe_research_status`。直接进入下一次紧凑等待，不把 child
   commentary、研究结果、review 正文或 fix 正文带入控制任务上下文。
3. 若没有 `wait_threads`，才使用 `list_threads(query=精确任务标题, limit=3)`；同一阶段两次实际
   查询至少间隔 300 秒。不得用全量 `list_threads`，不得为等待启动 shell sleep、后台进程、
   heartbeat 或事件转发。
4. 只有任务不再 active 时才调用一次
   `read_thread(thread_id, turnLimit=1, includeOutputs=false)`，只使用最新 turn 的
   `completed` / `interrupted` / `failed` 状态。Research 必须只读取最终回答末行的
   `POE_RESEARCH_SUCCEEDED: yes|no` 标记，Fix 必须只读取最终回答末行的
   `POE_FIX_DATA_REPAIRED: yes|no` 标记；除此之外忽略回答正文，不得复制或转述正文。
5. `idle` 不是成功证据，必须核对最新 turn 状态。`notLoaded` 也不是终态；在下一次有界等待后
   重新列举并读取一次，仍无法确认时把控制循环停在当前检查点，不能假装 completed 或重复发送。
6. 控制任务只在以下事件向用户报告一次：阶段成功派发、阶段进入
   `completed` / `interrupted` / `failed`、计划进入 `blocked` / `paused`、或确实需要用户介入。
   不报告“仍为 active”“更新时间刷新”“继续等待”等未变化快照。
7. 如果最新用户消息不是本控制器刚发送的固定提示词，说明用户向 child 插入了额外 turn；在
   sidecar 当前阶段保持不变并暂停推进，请用户决定，禁止把额外 turn 当成预期阶段完成。

### 3. Research → Review

Research 最新 turn 为 `completed` 时：

1. 只解析最终回答末行的精确标记：
   - `POE_RESEARCH_SUCCEEDED: yes`：调用 `record_poe_research_phase_finished`，参数为
     `phase=research + expected_phase=research_running + turn_status=completed + research_succeeded=true`。
   - `POE_RESEARCH_SUCCEEDED: no`：同样记录完成，但传 `research_succeeded=false`；状态服务先进入
     `blocked + paused`，不得自动发送 review。若最终报告明确显示请求数量已全部正式 accept、
     `remaining=0`、报告计数与持久化结果一致，只因暂缓或未解析证据而输出 no，则在用户明确确认
     “已完成入库，应继续审查”后，调用 `recover_poe_research_intake_for_review`，保留
     `research_succeeded=false` 审计事实并进入 `review_pending`；不得把该恢复伪装成 research 成功。
   - marker 缺失、重复或矛盾：不得猜测成功；按 `research_succeeded=false` 记录并阻断，提示用户检查
     可见 thread/runDir 后显式 retry。
   bridge 的 finish 命令必须追加 `--research-succeeded yes|no`。
2. 只有 `research_succeeded=true` 后再查状态；若已请求暂停，停在 `review_pending`，不要发送 review。
3. 否则调用 `send_message_to_thread`，对同一 `thread_id` 指定
   `gpt-5.6-sol + xhigh` 并发送固定 review 提示。
4. 发送成功后记录
   `phase=review + expected_phase=review_pending` started，然后按同样方式监控。

### 4. Review → Fix

Review 最新 turn 为 `completed` 时：

1. 记录 `phase=review + expected_phase=review_running + turn_status=completed` finished。
2. 再查状态；若已请求暂停，停在 `fix_pending`。
3. 否则对同一任务用 `gpt-5.6-sol + xhigh` 无条件发送固定 fix 提示。
4. 发送成功后记录 `phase=fix + expected_phase=fix_pending` started，然后监控。

### 5. Fix → 条件复审或完成

Fix 最新 turn 为 `completed` 时：

1. 只解析最终回答末行的精确标记：
   - `POE_FIX_DATA_REPAIRED: yes`：记录 Fix finished 时传 `data_repaired=true`；状态进入
     `rereview_pending`。
   - `POE_FIX_DATA_REPAIRED: no`：传 `data_repaired=false`；状态直接完成并更新 Markdown。
2. marker 缺失、重复或矛盾时不得猜测，也不得记录 Fix finished。请求阶段边界暂停并报告用户，
   等用户核对可见 Fix turn 后明确确认 yes/no。
3. bridge 完成命令必须追加 `--data-repaired yes|no`。

### 6. 复审 → 完成与下一项

`data_repaired=true` 时，对同一 `thread_id` 使用 `gpt-5.6-sol + xhigh` 发送固定复审提示。发送成功后
记录 `phase=rereview + expected_phase=rereview_pending` started，然后按同样方式监控。

复审最新 turn 为 `completed` 时，记录
`phase=rereview + expected_phase=rereview_running + turn_status=completed` finished。只有未触发复审的
Fix completed，或已触发复审时 rereview completed，才会让状态服务在原 Markdown 对应项标记完成。
确认状态后再 claim 下一项，并为下一项创建全新的可见任务。

任一阶段最新 turn 为 `interrupted` 或 `failed` 时，把该真实状态记录到 finished 接口。状态服务
会保存 thread ID、标记 `blocked + paused` 且不自动重放。报告 thread ID 和失败阶段后停止。

## 恢复、释放、暂停与重试

- 已绑定 thread：根据 sidecar 的 `thread_id` 和 `next_action` 继续监控或发送下一固定阶段，绝不
  创建重复任务。
- `creating_thread` 且没有绑定 thread：用 `list_threads` 按 claim 的领取时间、精确 research
  prompt、项目路径及 class/level/task ID 标题搜索：
  - 唯一匹配：用该 thread 补录 research started；
  - 无匹配：只有确认确实没有创建结果后，调用 `release_poe_research_claim`，并设置
    `acknowledge_no_thread=true`；
  - 多个匹配：停止并请用户选择，禁止释放或再次创建。
- 旧 sidecar 的 `research_running` 等活动检查点保留历史 thread ID，只报告
  `reconcile_legacy`；不得自动创建或重放。
- 普通“暂停”：调用 `pause_poe_research(plan_path)`。当前 child turn 可结束，但结束后不发送
  下一阶段；bridge 为 `pause --plan '<绝对路径>'`。
- 立即硬暂停：导航到可见 child，明确让用户点击该任务输入框的暂停按钮。不要声称控制任务能
  远程中断正在运行的 Desktop turn。
- 恢复：调用 `resume_poe_research`；若状态要求 retry，不能绕过。
- 整份计划归零：只有用户明确要求丢弃现有检查点并从头开始时，调用
  `reset_poe_research_plan(plan_path, acknowledge_reset=true)`；bridge 为
  `reset --plan '<绝对路径>' --acknowledge-reset`。运行中的 Desktop turn 必须拒绝重置；成功后重新
  validate/status，并从第一项重新 claim。不得用手工编辑 Markdown/sidecar 代替该接口。
- 重试：必须取得用户对该可见 thread/runDir 已检查的明确确认，才调用
  `retry_poe_research_task(... acknowledge_reviewed=true)`。重试会新建 claim 和新任务，不会自动
  复用失败 turn。
- 已完成入库后继续审查：仅当 blocked research turn 为 `completed`、最终报告明确全部案例已正式
  accept、`remaining=0` 且持久化计数一致，并且用户明确确认应继续审查时，调用
  `recover_poe_research_intake_for_review(... acknowledge_intake_complete=true)`。该接口复用原 thread、
  进入 `review_pending`，不会重跑研究，也不会把 `research_succeeded=false` 改写成 true。

## 对用户的报告边界

每次阶段变化只报告标题、thread ID、阶段和终态，例如“thread X 的 research 已 completed，
已进入 xhigh review”。用户直接在侧边栏任务中查看研究过程、review 结论和 fix 详情。
控制任务不得复述 child 输出，也不得用 JSON 事件、heartbeat 或双份消息模拟可见进度。

创建成功的任务在最终答复中按 Desktop 要求输出对应的 `created-thread` 指令，方便重新打开。
