---
name: poe-bd-learning-loop
description: Use when the user asks to start, run, resume, pause, retry, inspect, or evaluate a Path of Exile 2 comparative build-learning campaign from PoB sources or automatically collected poe.ninja builds.
---

# /poe-bd-learning-loop

## 作用

这是 Desktop 可见的 BD 对照学习控制器。每个案例先由 Reference/Comparator 任务安全分析原 BD，
再由完全独立的 Create 任务只按相同 Family 和相同等级盲测生成，随后回到 Comparator 做逐维比较
和经验分流。程序只保存 typed state、隔离来源和安全报告，不创建隐藏模型循环。

默认首批固定 10 个案例，严格串行。一个案例结束前不得启动下一个。每个案例只运行一次
`$poe-bd-create`；Create 自身允许既有的最多两次内部修正，Compare 后不得重新生成本案例。

## 入口

支持：

- 直接 PoB code、pobb.in/pastebin link 或 XML；
- `--source-file <绝对路径>`；
- `--auto --class <职业> --level <等级> --count <数量>`，复用现有 poe.ninja collector，收集后以
  `sourceMode="automatic"` 逐个隔离导入；
- `status <campaignId>`；
- `pause <campaignId>`；
- `resume <campaignId>`；
- `retry <campaignId> <caseId>`。

直接来源和本地文件可以逐案例补入同一 campaign。自动模式仍受十案例上限和严格串行约束；不能
先批量启动十个 Create 任务。

## 不可突破的隔离

- 原始 code/XML 只传给 `intake_learning_case`。工具返回后不得把原文写入提示词、聊天、控制
  状态、报告、Memory、文件或 Git。
- Create 只能看到 `BlindCreatePacket`：FamilyTarget、等级、版本和默认目标。不得向 Create 发送
  原 BD 装备、天赋、技能组、机制摘要、配置、来源、Comparator 结论或 Judge 数据。
- Family 唯一复用 Research 的定义：升华、主伤技能和已确认核心次级技能。歧义时案例失败，不猜。
- Judge 数值只允许作为 `advisoryOnly` 附件。不得按 aggregate、DPS 或总分自动选赢家或写 reward。
- 具体技能、机制链、轮转、装备、天赋、防御、资源、tradeoff、failure 或 modelability 知识必须
  回到 Research；Learning Memory 只接收跨维的未来 Create 行为经验。
- 架构或产品取舍进入 backlog 并暂停。只有 `codex/*` 分支允许自动修复可复现的小型代码缺陷。

## 开始 campaign

1. 实际调用 `start_learning_campaign(operation_id=<唯一值>, case_limit=10)`。
2. 每次仅导入一个案例：
   - direct：`intake_learning_case(..., source_mode="direct", source=<原始输入>)`；
   - file：`source_mode="source_file", source=<绝对路径>`；
   - auto：先用现有浏览器/collector 取得一个 PoB import material，再用
     `source_mode="automatic", source=<material>, source_ref=<安全发现引用>`。
3. 立刻丢弃控制任务上下文中的原始 source；后续只使用 campaignId、caseId、safe source ref 和
   revision。
4. 每次 mutation 都传新 `operationId` 与最新 `expectedRevision`。revision conflict 时重新读
   `get_learning_campaign_status`，不得覆盖新状态。

## 可见任务初始化

一个案例使用两个任务：

- `PoE Learning Reference · #<ordinal> · <caseId>`：Profile、Compare、Learn 和条件复审；
- `PoE Learning Create · #<ordinal> · <caseId>`：只运行一次盲测 Create。

使用 Desktop `create_thread` 时先发送短初始化提示，让新任务只输出
`POE_LEARNING_READY: yes`，不接触来源、不执行分析。取得真实 threadId/hostId 后：

1. 调用 `claim_learning_phase` 绑定真实 taskId/threadId；
2. 再用 `send_message_to_thread` 发送包含 claimId 的阶段提示；
3. 通过 `wait_threads` 等待该阶段结束。

这样避免在任务 ID 尚未知时提前执行。Reference 与 Create 的 taskId 和 threadId 必须不同；Compare、
Learn、rereview 必须复用 Reference 任务。创建后设置上述标题并导航到新任务，让用户可见。

## Profile

Reference 任务收到 claim 后：

1. 调用 `load_learning_reference_case(campaign_id, case_id, claim_id, thread_id)`；响应不含 raw。
2. 串行使用 `get_build`、`list_skill_groups`、`get_build_stats`、`get_defenses`、
   `inspect_build_completeness` 和必要的机制工具理解原 BD。不要把整角色镜像写入持久报告。
3. 用 `graph_tool_query` 的 search → resolve 两步确认升华、主技能和真正 Family-core 的次级技能。
   辅助、utility、普通防御/资源技能不能机械加入 Family。
4. 以现有 Research `identity_records` 形状调用 `submit_learning_profile`。`targetLevel` 必须来自活动
   reference readback，并与隔离来源发现等级相同。
5. `referenceEvidence` 只写简短安全维度观察和 safe refs；reference Judge 不可用时明确
   `available=false`，不得滥用生成候选专用 Judge 入口。

Family 歧义、等级冲突或原构筑无法安全重建时，让工具失败关闭，并在任务末行输出
`POE_LEARNING_PROFILE_SUCCEEDED: no`；成功则输出 `yes`。

## Blind Create

Profile 成功后创建独立 Create 任务、claim `create`，然后发送：

```text
使用 $poe-bd-create 执行本次 BlindCreatePacket。先调用 get_learning_create_packet 取得唯一输入；
不得查询或要求原 BD 细节。正常查询 Research，并在活动 Create claim 内调用
query_learning_memory；Family、等级和 versionContext 由服务端绑定，提交时使用返回的新 revision。
默认目标是软核交易、无固定预算、综合强度与可玩性优先。只运行一次 Create，
允许 skill 自身既有的有限内部修正。完成并保存最终 artifact 后，重新解析最终 Family 和等级，调用
submit_learning_create_result，提交安全 generated evidence 与完整 learningMemoryUse 审计。
```

Create 必须记录每条 Memory 的 `adopted/caveated/rejected`、应用方式和
`harmfulOrIncorrect`。没有命中也提交真实 queryRef 和空列表。最终 Family 或等级不一致时案例失败；
不得再次 Create。

## Compare

Create 提交成功后，回到 Reference 任务 claim `compare`：

1. 可再次用当前 compare claim 调用 `load_learning_reference_case`，读取必要的 reference 证据；记录
   临时安全笔记后，调用 `load_final_build_artifact` 检查 generated artifact。
2. 检查双方配置条件的真实性；不能让一边开满不现实条件、另一边按常态配置。
3. 固定比较十个维度：
   - damage loop/delivery；
   - skill roles/supports；
   - configuration realism；
   - trigger/conversion chain；
   - gear/passive/ascendancy synergy；
   - clear/boss/conditional burst；
   - defense/recovery/resource/Spirit；
   - mobility/playability；
   - legality/completeness/modelability；
   - gear effort/attainability。
4. 每维只用 `generated_advantage/reference_advantage/tradeoff/tie/unknown`；总结果只用
   `generated_stronger/reference_stronger/tradeoff/incomparable`。
5. reference 更强时，把 gap 分类为固定七类之一。每个 Judge 附件必须
   `advisoryOnly=true`；comparison report 顶层必须是 `noAutomaticWinner=true`、
   `noRewardWrite=true`。
6. 调用 `submit_learning_comparison`。赢家来自 Comparator 的证据判断，不来自工具自动推导。

## Fix/Learn 与条件复审

回到同一 Reference 任务 claim `learn`：

- DB-fit 知识使用现有 `$poe-bd-research`/Research typed proposals；不得把它改写成泛化 lesson 逃避
  Research schema。
- 跨维 Create 行为经验用当前 campaign/case/claim/thread 调用 `propose_learning_lesson`，必须
  `dbFit=false`，带版本、条件、排除、
  verification tasks 和安全 refs。成功后立即可供下一案例召回。
- 发现 Memory harmful/incorrect 时用同一 Learn claim 调用 `append_learning_memory_correction`。修正只能
  `narrow/revise/supersede/deprecate`，必须保留 before/after、原因、触发案例和证据。
- 已修正的同义 lesson 再提交时，必须引用旧 correction 且带新证据；否则接受工具拒绝，不绕过。
- 小型确定性代码缺陷仅在 `codex/*` 分支最小修复并补测试；`main` 上暂停。产品/架构决定或证据
  不足写入 backlog。
- 最后调用 `complete_learning_case_feedback`。任何 Research、Memory 或 code mutation 都进入
  `rereview_pending`；`none` 直接完成；backlog 暂停。

条件复审仍在 Reference 任务，claim `rereview`。只复审本案例实际 mutation，不重新生成本案例，
不改变已提交 winner。调用 `submit_learning_rereview` 后才可开始下一案例。

## 等待、状态和恢复

- 对单任务使用 `wait_threads`，携带最新 cursor，`timeoutMs=300000`。超时且状态无变化时直接继续
  等待，不发送“仍在运行” commentary，不频繁读取任务全文。
- 只在终态读取最后一轮；用 MCP campaign 状态而不是 child 自述作为 checkpoint 事实源。
- `pause` 调用 `pause_learning_campaign`。运行 claim 会安全回到 pending；不能声称控制器能远程终止
  已经在运行的模型 turn。
- `resume` 先查状态，再调用 `resume_learning_campaign`；有 backlog 时传人工决定。
- phase 失败时先记录 `fail_learning_phase`。只有用户检查可见任务后才调用
  `retry_learning_phase`；已消费的 Create 结果永远不能重试。
- 恢复时复用已经绑定的任务。不得创建重复 Reference/Create，也不得手工编辑 campaign JSON。

## 十案例报告

每案例完成后调用 `get_learning_campaign_status`，只报告阶段、任务 ID、终态和累计安全指标。完成
十例后使用工具返回的固定趋势结论：

- `initial_progress_signal`：只能表述“出现初步进步信号”；
- `function_complete_learning_unproven`：表述“功能实现完成、学习效果未证实”。

趋势只比较最初 3 例与最后 3 例，中间 4 例是持续学习过程；滚动窗口为 3。不额外运行 Holdout，
不做逐案例 memory-on/off A/B。无论结果如何，都明确只有 10 例且没有 A/B，因此不是因果证明。

保存最终趋势摘要后，调用
`cleanup_completed_task_runtime(task_kind="learning_campaign", task_id=campaignId)`。它删除 campaign、
quarantine、盲测 generation run 和内部 final artifact，只保留 Research Memory、Learning Memory
及用户已经取得的报告；campaign 未完成时会拒绝清理。

## 对用户的输出

不要转述原始来源、完整构筑镜像、child 长篇正文或 Memory JSON。报告：campaign/case、两个可见
任务、阶段终态、Family/等级匹配、Comparator 总结果、关键 gap 分类、Research/Memory/code/backlog
分流、correction、耗时和累计趋势。用户可直接打开可见任务查看过程。
