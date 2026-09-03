# 对照学习盲测模式（Blind Create）

仅在收到 `referenceBlind=true` 的 `BlindCreatePacket` 时使用。这是 Phase 7 对照学习的
内部 Create 模式，不面向普通用户。

## 硬约束

- 不得追问或改写锁定的 `FamilyTarget`；不得索取、搜索或推断原 BD 的装备、天赋、技能组、
  机制摘要、配置或 Judge 结果。只按目标 Family、等级、版本和默认目标正常创建。
- 不询问任何交互问题——直接按锁定 packet 执行（普通 Create 本就不做开荒过程确认）。
- 提交 Create 结果时使用 `mcp__poe_learning__submit_learning_create_result`，不是普通 review 流程的
  `mcp__poe_build__complete_generation_review`（盲测的 artifact 仍要进入 Compare，由 Learning campaign
  完成后统一清理，不调用 `mcp__poe_build__cleanup_completed_task_runtime`）。

## 知识调用差异

- 每次 `mcp__poe_knowledge__query_research_memory(response_profile="create_compact")` 首查都传
  `run_ref=<campaignId>`、`claim_ref=<claimId>`；`blind_global_only` 仅为兼容提示，不是授权依据。服务端验证当前
  `create_running` claim 后强制 `global_seed`；不得传或采用 `local_user`、mixed 或 legacy-unscoped
  receipt。沿唯一 `continuation_cursor` 连续读完全部页，并在 `researchMemoryUse` 保存完整 receipt
  链以及同一 `selectedKnowledgeScope + selectedSourceCaseRef`。
- 除 Research 记忆外，必须在活动 Create claim 内调用
  `mcp__poe_learning__query_learning_memory(campaign_id, case_id, claim_id, thread_id, expected_revision,
  operation_id, dimensions=None, limit=8)`；Family、等级和版本由服务端从 FamilyTarget 绑定，
  提交结果时使用查询返回的新 revision。
- 同时阅读有效 lesson 与 `correctionsAndDoNotRepeat`。为每条召回 lesson 记录
  `adopted/caveated/rejected`、实际应用、`harmfulOrIncorrect` 和观察；没有命中也保存真实
  `queryRef` 与空决策。Research 无命中时仍保存 claim-bound 完整页链；其 selected lane 为空，
  但服务端 receipt 的 effective scope 必须是 `global_seed`。修正历史优先于旧 lesson，不得把已废弃做法重新采用。
- 独立 `learningMemoryUse` 至少包含 `queryRef`、`recalledLessonIds` 和 `decisions`；每项
  decision 包含 `lessonId`、`decision`（`adopted/caveated/rejected`）、`application`、
  `harmfulOrIncorrect` 和可选 `observation`。它提交给 `mcp__poe_learning__submit_learning_create_result`，
  不混入 Research SQLite 引用，也不得写入原始来源信息。

## 完成后

完成 artifact 后重新读取并解析最终升华、主技能和已确认核心次级技能，用本任务收到的 claim
调用 `mcp__poe_learning__submit_learning_create_result`。提交内容只包含 identity records、目标等级、artifact id、
安全 generated evidence、完整 `researchMemoryUse` 和 `learningMemoryUse`。Family 或等级回读不一致时让案例失败，不得为
同一案例重新调用 Create；后续比较和改进由对照学习入口负责。
