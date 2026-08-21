---
name: poe-bd-research-worker
description: Internal explicit-only worker for one leased PoE2 mature-build Research case. Use only when the poe-bd-research Controller supplies an existing opaque runRef; never create or resume a queue.
---

> **DSH 适配说明**：本 skill 运行在 DeepSeek Harness。所有 poe-bd 能力都是 MCP
> 工具，完整名带 `mcp__poe_<server>__` 前缀（例如
> `mcp__poe_knowledge__query_research_memory`、`mcp__poe_build__get_build_stats`），
> 下文只写末尾名称。加载本 skill 使用 DSH 的 `skill` 工具，不存在 `/poe-bd-*`
> 斜杠命令。工具清单以当前会话实际注册为准，不要猜测未注册的工具名。
> **DSH Worker**：只允许 Controller 显式用 `skill` 工具加载本 skill；从 assignment
> 取得 runDir 后用 shell 执行单案流程，不创建或恢复 queue。

# PoE BD Research Worker

本 Skill 只供 `poe-bd-research` Controller 显式派发。它从既有队列原子 claim 一案，完成证据读取、
研究、safe review、校验和 accept，然后停止。

## Assignment Boundary

开始前必须收到 `runRef`：既有 Research run 的 opaque `research-run:...` 引用，并且当前 fork 必须
包含用户本次研究请求/授权的真实上下文。

缺少绑定/用户请求上下文，或当前任务不是 Controller 的显式 Worker 派发时，返回
`worker_assignment_missing` 并停止。不得自行发现其他仓库、创建/恢复 queue、询问用户运行模式或
回退为主会话研究。

## Typed Tool Binding

只使用 Research MCP 的 `mcp__poe_research__claim_research_case / mcp__poe_research__inspect_research_case / mcp__poe_research__read_research_case /
mcp__poe_research__search_research_case / mcp__poe_research__get_research_review_contract / mcp__poe_research__initialize_research_review /
mcp__poe_research__validate_research_review / mcp__poe_research__accept_research_review / mcp__poe_research__retry_research_review`。工具未显示时先按精确名做 tool
discovery；缺失时返回 safe failure，不搜索仓库、不解析插件路径，也不回退 shell CLI。

## Runtime Boundary

- 只处理一个 claim；完成或失败后不得领取第二案、嵌套委派或执行 cleanup。
- 这是产品运行态，不得修改源码、测试、文档、schema、安装配置、queue、review 文件或其他 run
  artifact。`mcp__poe_research__initialize_research_review` 返回 safe review 对象；只在模型工作状态中修改该对象，再把
  完整对象传给 typed validation。不得用 shell/file tool 编辑运行态。
- 原始 PoB/XML 只留在 quarantine 与 lease-bound transient packet；不得进入聊天、safe review 或
  durable memory。
- 工具未直接显示时先用宿主标准 tool discovery/search 查找 `mcp__poe_knowledge__query_research_memory` 与
  `mcp__poe_knowledge__graph_tool_query`，不要根据首屏列表断言不可用。

## Single-Case Workflow

1. 调用 `mcp__poe_research__claim_research_case(run_ref=<runRef>)`。

   `worker_capacity_reached` / `no_pending_cases` 是无 sampleId 的调度结果，原样返回后停止。`claimed`
   后保存 `sampleId` 与 `leaseToken`；后续所有工具都绑定同一 runRef/lease。

   `claim_packet_failed` 已包含 sampleId：原样返回 safe outcome 后停止。`leaseReleased=true` 表示案例
   已安全回到 dispatchable 队列；`recoveryRequired=true` 时不得重试或猜测状态，交给 Controller 停止
   补位并报告。

2. 先以同一 `run_ref + lease_token` 调用 `mcp__poe_research__inspect_research_case`，再按返回顺序用可分页
   `mcp__poe_research__read_research_case` 读完全部分区；
   `mcp__poe_research__search_research_case`
   只能定位具体线索，不能替代完整读取。先独立重建案例，再查询 Research Memory，并通过
   `search_graph_components` → `resolve_graph_component` 确认 stable key。
   Family 首次身份宽查固定用 `detail_level="summary" + response_profile="create_compact"`，并检查
   `familyRecordCoverage / familyRecordIndex / familyPremiseCatalog`；选定 Family 后按 index 返回的
   `record_ids` 使用 `detail_level="record" + response_profile="create_compact"` 精确深读，直到关键
   premise、失败条件和验证任务闭合，不设固定深读额度。Family 查询用
   `primary_skill_key=skill:/gem:`；`build_family_keys` 只接收查询已返回的 `bf-...`，未知时省略，禁止
   把技能 key 填进去。

3. 初步研究完成后以同一 `run_ref + lease_token` 调用 `mcp__poe_research__get_research_review_contract`，以其
   `mandatoryChecks`、模板、枚举、兼容矩阵和 rules 为
   当前 lease 的精确事实源；不得从本 Skill 猜字段或固定检查数量。
   机制全文搜索只提供候选；选中后按精确标题读取正文，由你在 `mechanicAudit.wiki` 填写
   `matchKind`、`relevanceReason` 与 supports/contradicts/silent。Candidate Pattern 必须填写
   `claimScopeReview`，用 typed scope 确认任何语言的正文只表达当前案例证据或条件迁移假设；不得依赖
   关键词门禁。

4. 以同一 `run_ref + lease_token` 调用 `mcp__poe_research__initialize_research_review` 获取骨架。`already_exists`
   表示返回既有安全对象，不得清空重建。
   在模型工作状态中补全 review，不写文件。

5. 调用
   `mcp__poe_research__validate_research_review(run_ref=<runRef>, lease_token=<leaseToken>, review=<review>)`。
   结构、resolver、角色、因果或职责变化后，对完整对象重新复核；
   按 validationIssues 有界修正。missing/ambiguous endpoint 最多进行两轮 repair，不能要求程序猜枚举
   或自动选择端点。保存 clean validation 返回的 `reviewHash`；修改 review 后旧 hash 立即失效。

6. Mandatory Checks 全部通过后调用
   `mcp__poe_research__accept_research_review(run_ref=<runRef>, lease_token=<leaseToken>, expected_review_hash=<reviewHash>)`。
   hash 不一致时重新 validate，
   不得绕过。可修复的 `acceptance_rejected` 把修正后的 review 交给
   `mcp__poe_research__retry_research_review(run_ref=<runRef>, sample_id=<sampleId>, review=<review>)`；任何
   deferred/unresolved/coverage gap/failure 都保留
   完整诊断。不要把 validation/retry 当成新案例。不可恢复的 runtime 错误停止当前 Worker，保留
   runRef/lease 状态并返回 safe failure。`review_contract_upgrade_required` 时补齐 v2 对象后重新 validate。

7. claim 成功后的任何结束路径都返回 `sampleId + safe outcome`；accepted 时附 safe acceptance 摘要，
   至少包含 acceptanceMode、created/updated/evidence counts、semantic edge count、deferred reasons、
   unresolved mention/unique component counts 和 mechanic/unique-gem diagnostics。不得输出 raw material。

## Supplemental Checks

- 补充研究或更正既有知识时，优先以相同标题/知识构成更新原记录；不要制造新旧矛盾正文。确需废弃旧
  结论时明确失效理由。
- `gearResponsibilities` 只归因组件静态文本直接提供的职责；来源实例词缀、插入物或转换效果必须归因
  到真实来源。无图节点的纯稀有/魔法装使用显式 `gearResponsibilities=[]`，并在 content 写槽位、目标
  词条和档位追求。
- 在 typed validation 和正式 accept 前复核每个最终对象的 title、summary、content、conditions、
  failureConditions、typedPayload、applicability/exclusions、contextRequirements、plannerHint 与
  verificationTasks；未复核字段不得沿用。
