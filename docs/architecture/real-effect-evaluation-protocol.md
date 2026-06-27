# 真实效果验证协议

Last updated: 2026-06-27

本文档定义 PoE2 BD Creator 的阶段性真实效果验证方式。它补充单元测试：单测证明代码合同没有破，
真实效果验证证明 agent 是否真的更会研究、创造和解释 BD。

## 1. 为什么需要真实效果验证

本项目的核心目标不是“跑通一组函数”，而是“让 LLM + 工具链可靠地产出强 BD，并能解释和迭代”。

单测能验证：

- schema 是否正确；
- sanitizer 是否拒绝 raw/copyable 字段；
- freshness provider 是否解析指定 fixture；
- lifecycle route 是否满足既定合同；
- engine golden values 是否没有漂移。

单测不能证明：

- agent 能不能从热门 BD 中看出真正的质变机制；
- agent 会不会把终局-only BD 错当开荒 BD；
- agent 输出是否对新手可执行；
- LLM 反思出的技巧是否真的能提升下一次生成；
- 当前赛季 meta 是否被正确理解；
- 生成 BD 是否接近成熟案例的核心设计身份。

因此，凡是影响 BD 创造质量的阶段，都必须引入真实效果验证。

## 2. 验证对象

真实效果验证优先覆盖这些能力：

- 新手输入处理：用户只说“给我一个强力 BD”时能否输出阶段化路线。
- 生命周期建模：starter → transition → maps entry → budget endgame → final 是否完整。
- 热门 BD 学习：能否从 poe.ninja / pobb.in / forum / guide / reference samples 中提取核心技巧。
- LLM 技巧抽取：是否抽到机制、阈值、转型门槛、失败风险，而不是只有标签摘要。
- creator/evaluator loop：creator 生成结果是否能被 held-out mature evidence 检验。
- 用户反馈：伤害不足、暴毙、缺蓝、清图慢、Boss 慢等反馈是否能定位阶段问题。

## 3. 数据集原则

### 样本来源

优先级：

1. 当前赛季 poe.ninja 热门 BD。
2. pobb.in / PoB code 对应的成熟案例。
3. 论坛/攻略中的高热度成熟 BD。
4. 本地 reference builds，仅用于 calibration。
5. 手工 curated fixture，只用于早期开发和 regression，不应假装是真实 meta。

### 新鲜度

每个样本必须记录：

- league；
- game patch；
- passive tree version；
- snapshot date / fetched_at；
- source type；
- source URL 或 source ref；
- popularity signal；
- diversity bucket；
- freshness / compatibility status。

### 多样性

首次 3N.3 真实验证建议使用 10～30 个样本，覆盖：

- 至少 4～6 个不同 class/ascendancy；
- 不同 delivery：attack、spell、minion、projectile、DoT、trigger/automation 等；
- 不同防御层：life、ES、armour、evasion、block、minion screen 等；
- 不同生命周期定位：starter_to_endgame、starter_then_transition、endgame_only、starter_only、unknown。

### 安全边界

验证集可以在 evaluator-only/holdout 环境中暂存更丰富信息，但 creator-facing 输入不得包含：

- raw PoB code；
- 完整装备表；
- 完整天赋树；
- 完整 passive node list；
- 完整 gem/support links；
- 攻略全文。

creator 只允许看 sanitized brief、聚合标签、粗粒度 keypoints 和允许的 provenance。

## 4. 标准验证流程

```text
真实热门样本
  -> source snapshot
  -> sanitizer / redaction
  -> sanitized brief
  -> LLM extraction
  -> candidate technique
  -> creator agent 生成 lifecycle route
  -> engine 验证可计算部分
  -> evaluator 对比 held-out mature evidence
  -> gap report
  -> LLM reflection
  -> candidate update 或 local lesson
```

### Step 1：样本发现

目标是找到当前赛季真正流行的样本，而不是随机抓取。

要求：

- popularity basis 必须明确，例如 poe.ninja rank、class percentage、guide heat、forum replies/views。
- 如果 build-level API 不稳定，先记录探测结果，再使用可复现快照或手工 fixture 过渡。
- 不能只抓一个职业。

### Step 2：净化和分割

每个样本进入 store 前必须经过：

- forbidden raw field scan；
- copyability guard；
- structured manifest validation；
- creator/evaluator split；
- freshness metadata check。

### Step 3：LLM 技巧抽取

LLM 应输出结构化候选，而不是自由散文。

候选字段建议：

- `technique_name`
- `mechanism_summary`
- `why_it_works`
- `required_components`
- `thresholds_or_breakpoints`
- `lifecycle_applicability`
- `starter_risks`
- `transition_gates`
- `skill_links_summary`
- `passive_tree_anchors`
- `gear_or_unique_roles`
- `defense_plan`
- `pob_modelability`
- `evidence_refs`
- `confidence`
- `copyability_risk`

LLM 输出必须再经过 schema validation 和 copyability check。失败则进入 rejected/quarantine，不进入 creator-visible candidate。

### Step 4：Creator 生成

creator agent 基于 sanitized knowledge 和用户目标生成 lifecycle route。

要求：

- 至少包含 starter、transition、endgame 三段；
- 说明为何终局形态能或不能开荒；
- 每个阶段给技能、辅助、核心天赋方向、装备优先级、目标数值、风险；
- 明确哪些数值来自 engine，哪些是未验证推断；
- 不复制 held-out 样本。

### Step 5：Engine 验证

对可建模部分执行：

- DPS / Full DPS；
- EHP；
- resists / overcap；
- life / ES / mana；
- Spirit / reservation；
- sustain；
- stage-specific thresholds。

PoB 不能建模的机制必须进入 caveat，而不是由 LLM 补数字。

### Step 6：Evaluator 对比

evaluator 可以读取 held-out mature evidence，并比较：

- creator 是否命中核心机制；
- 是否遗漏 build-defining unique / gem / ascendancy interaction；
- 是否误判生命周期；
- 是否低估预算或转型门槛；
- 是否给出错误数值或不可验证数值；
- 是否存在 copyability 泄漏；
- 是否对新手可执行。

### Step 7：Gap 蒸馏和反思

gap 分为：

- `missing_core_mechanism`
- `wrong_lifecycle_classification`
- `unsafe_transition`
- `numeric_underperformance`
- `defense_gap`
- `sustain_gap`
- `budget_unrealistic`
- `pob_modelability_missed`
- `copyability_risk`
- `stale_or_unknown_freshness`
- `novice_explanation_gap`

LLM 可以基于 gap 写 reflection，但 reflection 默认不进入 durable memory。

晋升条件至少满足其一：

- 多来源 mature evidence 支撑；
- engine delta 明确；
- 同类用户反馈反复出现；
- 人工审核明确通过。

## 5. 评测指标

| 指标 | 含义 |
| --- | --- |
| `route_completeness` | 是否包含开荒、转型、入图、预算终局、毕业或明确说明缺失。 |
| `lifecycle_correctness` | 是否避免把 endgame-only 当 starter。 |
| `mechanism_alignment` | 是否命中成熟 BD 的核心 scaling identity 和质变点。 |
| `transition_gate_quality` | 转型门槛是否具体、可检查、不过早。 |
| `engine_validity` | 数值是否来自 engine，是否标明不可建模 caveat。 |
| `defense_and_sustain_quality` | 是否覆盖抗性、防御、Spirit、Mana sustain、命中/暴击等关键问题。 |
| `freshness_correctness` | 是否带 league/patch/tree/PoB 版本标签，是否拒绝 stale 伪当前。 |
| `copy_safety` | 是否没有 raw PoB、完整装备、完整树、完整 links、攻略全文泄漏。 |
| `novice_usefulness` | 新手是否能理解核心原理和下一步行动。 |
| `evaluator_gap_severity` | evaluator 发现的 gap 数量和严重程度。 |
| `learning_delta` | 经过 reflection/candidate 更新后，同类任务是否减少 gap。 |

## 6. 阶段性门禁

### Phase 3N.3 MVP 门禁

通过标准：

- 至少完成一轮真实样本来源探测；
- 如果 poe.ninja build-level 数据无法稳定获取，必须记录失败 URL/原因和替代方案；
- 有 10～30 个多职业 sanitized sample plan 或 fixture plan；
- 有 LLM extraction output contract；
- 有至少一条从真实/近真实样本抽出的非平庸技巧候选示例；
- evaluator 能指出 creator 与 mature evidence 的差异；
- 没有 raw/copyable 内容泄漏。

### 接入 route synthesis 前门禁

成熟技巧影响推荐前，必须满足：

- retrieval 只读取 creator-visible evidence；
- candidate 有 freshness/compatibility 标签；
- candidate 不处于 rejected/stale/quarantined；
- 至少有一次真实效果验证显示它改善了输出；
- 用户确认是否允许 mature candidates 影响 route synthesis。

### durable memory 晋升门禁

晋升 durable technique memory 前，必须满足：

- evidence 可回溯；
- patch/tree scope 明确；
- 不含 raw/copyable 内容；
- 不是单次 LLM 猜测；
- 有 multi-source、engine delta、重复反馈或人工审核之一。

## 7. 报告格式

每轮真实效果验证应生成报告，建议保存到：

- `docs/evaluations/YYYY-MM-DD-<topic>.md`

报告至少包含：

- 数据新鲜度；
- 样本来源与多样性；
- creator 输入；
- creator 输出摘要；
- engine 验证结果；
- evaluator gap；
- LLM reflection；
- 是否产生 candidate technique；
- 是否允许晋升；
- 下一轮改进点。

## 8. 当前状态

截至 2026-06-27：

- 已有工程单测和 mature learning safety baseline；
- 已确认 deterministic extraction 输出偏标签级，不能满足高价值技巧沉淀；
- 已确认 poe.ninja freshness index 可获取当前赛季/tree/sample-size；
- 尚未定位稳定 build-level 热门样本接口；
- 尚未实现 LLM extraction runner；
- 尚未完成真实热门 BD 样本评测。

下一步应优先推进 Phase 3N.3：真实样本发现 + LLM-assisted extraction + 首轮真实效果验证。
