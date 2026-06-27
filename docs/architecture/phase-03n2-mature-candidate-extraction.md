# Phase 3N.2 成熟 BD 候选技巧抽取

Last updated: 2026-06-27

## 目标

Phase 3N.2 将 Phase 3N.1 已经净化并落库的 `mature_build_cases` 转成低信任候选技巧。
这些候选技巧用于后续研究、检索和评估，不是最终 BD 推荐，也不会直接改变路线生成结果。

本阶段关注“成熟 BD 中出现了哪些可复用设计信号”，而不是“照抄一个成熟 BD”。因此抽取结果必须保持粗粒度：
保留职业、升华、主技能、宽泛机制、阶段风险和证据来源；拒绝保存完整天赋树、装备表、宝石连接或攻略全文。

## 输入和输出

输入只允许读取 `mature_build_cases` 的安全字段：

- class / ascendancy / main_skill；
- damage_types / delivery_tags / defense_tags / mechanic_tags；
- lifecycle_stage / budget_band；
- pob_modelability；
- sanitized_keypoints；
- source_group_id / source_snapshot_id；
- evidence_type / league / game_patch / passive_tree_version；
- visibility / split / knowledge_scope；
- freshness_status / compatibility_status。

输出写入两张表：

- `technique_candidates`：候选技巧的规范化摘要、标签、生命周期字段和回算计数。
- `candidate_evidence`：候选技巧与成熟案例之间的 evidence 桥接关系。

## 确定性抽取

候选 ID 使用规范化语义 key 生成。语义 key 至少包含：

- visibility/split 派生出的边界 bucket；
- 候选知识 scope；
- class、ascendancy、main_skill；
- damage、delivery、defense、mechanic 标签；
- lifecycle_stage、budget_band；
- category_tags、mechanism_role；
- league、game_patch、passive_tree_version。

同一语义 key 的多个来源会合并成同一个候选，并由多条 `candidate_evidence` 支撑。
但同一语义如果跨越 creator/evaluator/quarantine 边界，必须因为 bucket 不同而生成不同候选，
防止 holdout 或 quarantine evidence 撑大 creator-visible 候选的可信度。
重复运行抽取器必须幂等：候选和 evidence 的主键稳定，行数不膨胀，只刷新 `last_seen_at` 和回算计数。
`evidence_id` 由 case ID、relation 和 extraction method 生成，`candidate_id` 与 `extractor_version`
只作为字段保存和更新。这样同一个 case 的语义或 visibility/split 发生变化时，evidence 会移动到新的
candidate，而不是留下旧 creator-visible evidence；后续抽取器升级也不会把同一条 evidence 变成多条
evidence。

所有进入 semantic key 的标签/list 必须 lower/trim/sort/dedupe。这样能避免相同成熟案例因为标签顺序或大小写不同
被错误拆分，也能让 source_count 更接近“语义来源数量”。

## Evidence 边界

`candidate_evidence` 继承成熟案例的 `visibility`、`split` 和 `knowledge_scope`。
`creator_visible` 只能在以下组合下为 1：

- `visibility = creator_visible`
- `split = train_context`

`evaluator_only` / `eval_holdout` 和 `quarantined` / `quarantine` 的 evidence 必须写 `creator_visible = 0`。

候选表本身没有 visibility 字段，所以 Phase 3N.2 会额外降低非 creator 案例派生候选的可见 scope：

- creator-visible 训练案例：保留原始 `knowledge_scope`；
- evaluator-only holdout 案例：候选 `knowledge_scope = eval_ephemeral`；
- quarantined 案例：候选 `knowledge_scope = eval_ephemeral` 且 `promotion_status = quarantined`。

这能减少后续检索层误用候选表裸数据的风险。真正的 creator 检索仍必须在 Phase 3N.3 通过 evidence
过滤实现。

注意：`candidate_evidence.knowledge_scope` 表示来源归属，不等于 creator 访问权限。未来任何 creator 检索都必须
同时要求 `candidate_evidence.creator_visible = 1`、`visibility = creator_visible`、`split = train_context`。

## 计数规则

`technique_candidates` 中的聚合计数不是事实来源，事实来源是 `candidate_evidence`。
每次抽取结束后从 evidence 表回算：

- `source_count`：`relation = supports` 的 distinct `source_group_id` 数量；
- `support_count`：`relation = supports` 的 evidence 数量；
- `contradiction_count`：`relation = contradicts` 的 evidence 数量。

Phase 3N.2 默认成熟案例 evidence 关系为 `supports`。矛盾证据的自动抽取留到后续更精细的对比阶段。
回算时以当前 evidence 表为准；如果候选行里的计数字段被篡改，下一次抽取也必须恢复为 evidence 推导结果。

## 生命周期字段

抽取器需要为候选写入四个生命周期研究字段：

- `required_prerequisites`：粗粒度前置条件，例如终局资源、预算、Spirit、暴击基础、冷却节奏或 PoB 建模 caveat。
- `starter_risk_reason`：为什么不能把该成熟终局形态直接当开荒 BD。
- `transition_gate_summary`：什么时候才应该考虑切换到这类终局机制。
- `unsafe_before_stage`：在什么阶段前不应默认推荐该机制。

这些字段是研究提示，不是可执行配置。真正推荐时仍需要 lifecycle gate 和 PoB/engine 验证。

## Out of scope

Phase 3N.2 不做以下事情：

- 不增加 FTS、BM25、向量库或外部图数据库；
- 不实现 route synthesis 读取 mature candidates；
- 不改变 MCP 对外工具输出；
- 不做自动晋升到 durable technique memory；
- 不实现主动过期、降权或自动重验证策略；
- 不实现 teacher-student evaluation loop；
- 不抓取实时 poe.ninja / pobb.in / forum 数据。

如果后续要让成熟候选影响 BD 生成，需要单独设计 Phase 3N.3/3O 的 visibility-safe 检索和评估边界。
