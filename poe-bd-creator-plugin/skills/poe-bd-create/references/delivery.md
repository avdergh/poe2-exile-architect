# 保存、提交与交付

完成 [validation-and-recovery.md](validation-and-recovery.md) 的正式评估后使用本文件。
顺序是：选择 passing attempt → 保存 artifact → artifact-bound lifecycle → 普通 validate/review
或 Blind submit → 按已选交付方式导出与披露。具体输出字段见
[output-contract.md](output-contract.md)，Blind 的 claim、身份和提交合同见
[blind-mode.md](blind-mode.md)。

## 选择 passing attempt

只有正式 Judge 已评估、`passed=true`、无 `hardFailures` 且通过共享硬合法性审计的 attempt，
才是可保护的 passing baseline。首次正式 Judge 前的基础版本与主动质量收尾不构成 baseline。
若通过后继续质量探索，保留Judge已捕获的不可变快照，在当前活动构筑继续局部修改形成新state；
这就是与baseline快照隔离的增量状态，不需要另找克隆工具，也不能覆盖旧快照。新候选更好且合法时再晋升。

由 Agent 明确选择最终采用的 passing attempt，调用
`save_final_build_artifact(run_id, run_token, candidate_id, attempt_index)`。每个 run 只保存
一个 artifact，失败 attempt 不保存完整 PoB。保存必须使用当前 MCP 进程仍保留的精确 Judge
快照和同语义 state hash 的合法性回执；`PlayerStat` / `FullDPSSkill` 刷新不算真实构筑变化。

后续质量增量造成回归时，可以请求保存仍有效的 baseline，但须传
`later_findings_scope="candidate_delta_only"` 及有界选择理由。即使后续修改被预检拦截、未消耗
Judge，且 baseline 仍是最后一条 receipt，活动 state 已偏离时也适用该恢复声明。

选择非最后一轮时，顶层另提交最终接受 `failureAudit`：其 attempt、candidate、snapshot 和版本
都绑定所选 baseline，接受决定为 `accept`，在摘要及保留 caveat 中说明后续发现为何只影响增量。
不能复用该轮原来的 retry audit，也不能使用后来失败轮次的 audit。选择最后一轮时可由 helper
补入该轮审计；具体结构及其他 attempt 的决定见 [output-contract.md](output-contract.md)。

后续修订了 Blueprint/Draft 时，保存工具可用原 Judge 绑定的历史证据恢复所选 baseline。
按返回的 `selectedDesignEvidence` 保留原 Blueprint 引用/正文、Research 使用决定与执行计划，
以及 `toolReferences/evidenceAudit` 中原设计证据与审读权限；将它们和其他必需的本run诊断引用合并，
不能丢失原引用或把agent_reviewed重新声明为internal_receipt。
原packageId/planId与其来源的关联也必须保留，不能把原引用移到其他决定下来维持全局集合。
只将已有candidate字段写回候选；evidenceAudit和mechanismEvidenceHash是只读审计信息，留在
工作checkpoint，不新增到candidate顶层。
据所选 artifact 完成最终 candidate；理由和验证补充仍遵守 [output-contract.md](output-contract.md)。
服务端不回写当前 marker，也不自动补全候选。旧回执没有历史证据、精确快照丢失、后续发现也影响
baseline 或绑定不一致时仍拒绝；不能手改 marker、snapshot 或 hash 绕过。保存后只进行该
artifact 的验证与交付，不再修订此 run 的 Blueprint/Draft 或追加 Judge。

## 保存后验证与提交分流

保存成功后，对所选 artifact 独立调用且只调用一次
`verify_lifecycle_stage(stage, artifact_id=..., detail="compact", strict_mode=<本次模式>)`。
artifact lifecycle 继承其 Judge calculation context，不接受改选其他技能。保留 artifact、阶段、
source hash 与观察目标一致的可信回执；failed/unknown、篡改或跨 artifact/stage 的结果不能冒用
为通过回执。活动快照已验证不替代本步骤。
省略 `state` 时使用同engine/快照/输出的当前声明，缺少session声明时读取该artifact保存的
`lifecycleDeclarationBinding`输入并重新观察；不会复用旧pass布尔。显式 `state={}` 表示撤销，
本session内后续省略state不会覆盖该撤销。旧artifact没有绑定声明时，按实际机制提供typed输入，
不能凭旧档位补造通过。

- **普通 Create：**将安全最终对象提交 `validate_generation_output`，按返回字段路径修正；
  它不消费 run。通过后将同一最终对象提交 `complete_generation_review`，由插件在受管用户
  数据目录原子写入并消费 review。`HumanReviewPacket` 只表示可进入人工验收，不代表人已认可
  构筑。不要自行定位或编辑运行文件。
- **Blind Create：**按 [blind-mode.md](blind-mode.md) 完成身份回读并提交
  `submit_learning_create_result`，进入 Compare；不无条件执行普通
  `complete_generation_review`，不执行用户导出或本任务清理。其他自动 Create 同样不进行面向
  用户的导出或 poe.ninja 上传，按其调用方合同返回内部 artifact。

普通 review 中，最终可信快照仍存在的 completeness advisory 必须记录具体处理决定；已经消失
的提示不保留陈旧决定。通常可用 `deferred` 或 `intentionally_unused`。唯一例外是
`spirit_opportunity_review_required`：有正收益预留并采用时，重新评估使提示从快照消失；确认
没有正收益选项时只能用 `intentionally_unused` 并记录实测依据，不能 deferred。

正常顺序始终是保存 artifact 后再消费普通 review。旧任务若已误先消费 review，保存工具只有在
candidate、attempt、精确 Judge snapshot 和语义 state hash 全部一致时才允许恢复，并返回
`orderingRecovery.reviewAlreadyConsumed=true`；此例外不是常规路径。不得手工删除或改名
review-result、review-consumed、可信 Judge 回执或运行锁。按工具的受检路径修复；无法恢复时
如实记录失败或重试。

## 交付档位与格式限制

允许以明确的Agent情景粗估展示未建模收益，使用candidate的`performanceEstimates`，与PoB计算值
并列，不覆盖PoB XML/导入码中的统计值或Judge回执。展示范围、依据、假设、重叠/重复计数处理和
限制；验证覆盖与技能采用价值分开说明，不能因模型缺口把有作用的技能当作零收益或降低采用优先级。
candidate标签说明证据覆盖有限，不是强弱评分。完整字段与边界见output-contract。

保存前参考 checkpoint 的 `deliveryStatus`；保存后以可信 artifact manifest 的档位为准：
blocked 不导出，candidate 只称技术候选或
待验证方案，recommended 才称推荐成品。正式 Judge passed、artifact 已保存、review accepted
都不能自行把 candidate 升级。
保存时可用同快照/同 Judge 输出的新机制证据重算 lifecycle，其他质量保留旧限制并接受当前
有效失败/撤权的单向收紧；仅missing/stale不算反证，新passed不提升旧unknown。历史Judge
receipt不改，已经保存的旧artifact不追溯升级。

严格模式的非硬性 Judge 警告不阻止硬合法技术候选保存和导出，但真实玩法/质量缺口仍需披露；
有严重短板者只能称弱原型/待完善候选。`scoreApplicability="unavailable"` 单独出现时只限制
PoB 数值措辞，说明未建模范围及非 PoB 验证依据，不自动降级或改换机制。默认 hard-only 只说明
“主观 Judge 反馈已关闭”，不要输出或推断被抑制的字段。

仅严格模式下，`qualityBand="strong"`只是评分档位，不代表强证据；若`rewardStrength="limited"`，
必须同时披露“评分档位strong，但证据/奖励强度limited”，不能只展示高档位。

保存工具会做轻量 PoB round-trip，核对技能/辅助、装备数量、孔位/Rune 和天赋珠宝；失败不能
继续导出。官方 `.build` 的 `guidanceOnly` 表示其黄装、装备孔位、Rune/Soul Core 与天赋珠宝
以 guidance text 表达，受限字段写入 description。PoB XML/导入码才是完整装备权威；格式限制
既不降低其权威性，也不改变候选的交付档位。

## 普通用户导出与清理

按开始时已经确定的自然语言交付选择执行，不再询问，也不新增授权表或二次确认：

| 用户选择 | 执行 | 完成条件与清理 |
| --- | --- | --- |
| 仅本地 | `export_final_pob_artifact(artifact_id, format="both", name=...)`，再 `export_final_build_artifact(artifact_id, name, author, description)` | XML、import code、`.build` 三个文件均成功才完成；不调用整包或 poe.ninja 发布入口。本地工具没有整包清理回执，保留现场 |
| 本地 + poe.ninja | 只调用一次 `export_final_build_package(artifact_id, name, author, description)`，生成三个本地文件并上传同一已验证 PoB code | 四项全部成功且 `runtimeCleanupReady=true` 后，才调用 `cleanup_completed_task_runtime(task_kind="generation", task_id=artifact_id)` |

部分导出失败时展示对应 errorCode 并保留现场，不伪造 `runtimeCleanupReady`。Blind 的 artifact
还要进入 Compare，由 Learning campaign 完成后统一清理。

最终以自然语言展示构筑摘要、默认假设、Judge 结论、`lifecycleEvidenceCoverage`、内部重试
改变了什么、最终 artifact id 和交付档位。逐项展示 compact review 的 `requiredUserDisclosures`，
包括符文、灵魂核心、珠宝、药剂或护符暂缓/不用的理由，不能仅留在内部文件。

仅本地逐项列出三个文件，成功项给路径、失败项给 errorCode；分享分支列出四项，
`poe_ninja_pob` 成功时确认 `publicExternalUpload=true` 并给可点击 URL，失败项给 errorCode。
两种分支都明确 `.build` 的格式限制，不展示 PoB XML 或导入码原文。用户选择分享时返回的公开
分享 URL 才是此流程允许展示的完整 URL；普通报告与聊天继续排除第三方原始材料、账号/角色细节
及隐藏推理。自己设计的技能/辅助组合、装备槽位摘要和天赋锚点可以用于说明方案。
