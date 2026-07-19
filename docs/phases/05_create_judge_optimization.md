# Create / Judge 复跑优化

## 目标

本轮优化来自一次真实的 `/poe-bd-create` 武僧 1—70 级开荒运行。目标不是放宽
verification-first 边界，也不是让程序替 Agent 自动补完整 BD，而是让 Create 更少依赖
重复手写合同，让 Judge 更准确地区分：

- 物理或规则不合法；
- PoB 无法计算；
- PoB 已计算出伤害，但低于阶段门槛或实战交付证据有限；
- 构筑合法，但质量确实偏低。

本轮必须保持：

- 活动 PoB 仍由 Agent 完整搭建；
- Judge 仍评价不可变 snapshot；
- trusted receipt 只作为 transient state 和 Judge 结果的事实源；candidate body、memory 和
  version context 仍由 Agent 提供，`versionContextTrusted=false` 必须保留；
- limited evidence 不能产生 strong reward；
- 不新增项目内模型调用或自动修装循环；
- 不在 review、聊天或 Git 中暴露 raw PoB XML / import code。

## 本次运行暴露的问题

### Create 合同摩擦

一次包含三次 Judge 尝试的运行要求 Agent 在 `agent-output.json` 中重复写入：

- 顶层 transient state 和 Judge report；
- 每次 attempt 的同一份 transient state 和 Judge report；
- 顶层最终 candidate 和最后一次 attempt 的同一份 candidate；
- `researchMemoryUse` 已持有的 query/item ID，再复制到 `memoryReferences`。

这些字段已经存在于可信 receipt，重复抄写只会制造错配面。真实运行先后遇到：

- stage lock 和 `fieldSources` 的 schema 错误；
- 旧 attempt 的 memory reference 集合不完整；
- 顶层最终 candidate 与末次 attempt 不完全一致；
- 直到最终 `review-packet` 才逐项发现错误。

### Create 阶段证据表达不准确

用户要求“开荒到 70 级”，candidate 可以声明四个 lifecycle stage，但当前只保存并 Judge
一个 70 级 snapshot。早中期路线只是 Agent 设计判断，不是 PoB/Judge 证据。Review packet
当前没有明确区分 `evaluatedStages` 和 `textOnlyStages`。

### Judge 诊断过于二元

真实运行中，主技能具有合法 socket group，Judge 选择正确，PoB 返回正 `TotalDPS`，同时
`modelability.status=full`、`scoreApplicability=applicable`。但由于数值低于 maps-entry offense
hard floor，offense 得分为 0，随后触发 `offense_delivery_not_established` 和 0.29 总分上限。

归零的直接原因是 stage curve 把 hard floor 作为 0 分边界，并在 strong evidence 低于地板时
触发 `below_playability_floor`；`offense_delivery_not_established` 是归零后的下游标签与 aggregate
cap，不是归零原因。优化必须修正这两个概念的混用，不能用“delivery 不足”解释所有低分。

这里混合了两个不同问题：

- PoB 观察到的阶段伤害不足；
- 轮转、条件技能或战斗 uptime 的交付证据不足。

正 DPS 不应被描述成“没有伤害证据”，但低于 hard floor 也不能被抬成已达到阶段要求。

### Caveat 和分类噪声

- 合法单主动技能组默认得到 `support_conflict_unverified_caveat`。它不参与 aggregate 或 reward
  限制，但旧 Create 指南会因为它要求 Agent 继续核验，因此属于会浪费重试的操作噪声，而不是
  Judge 数值惩罚。
- `non_endgame_sample_caveat` 出现在明确的 campaign / maps-entry 请求中；level band 已足够表达
  evaluation scope。该 caveat 原本不扣分也不限制 reward，问题仅是命名和展示把正常阶段说成
  样本缺陷。
- selected skill 使用直接 PoB DPS 时，来自其他 FullDPS 诊断的 caveat 可能继续污染主技能
  offense provenance。
- `modelability.status=full` 的低分样本仍可能分类为
  `judge_unsolved_modelability_gap`，命名与证据状态冲突。

## 方案

### 1. 由运行时补全可信字段

`review-packet` 在 schema 验证前读取本 run 的 trusted receipts，并生成 canonical payload。
安全顺序固定为：

1. 先扫描原始 `agent-output.json` 的 copy safety 和 hidden reasoning；
2. fail-closed 读取并校验连续 receipt；
3. 补全省略的可信字段；
4. 再扫描、验证 canonical packet。

Receipt 读取必须确认 attempt index 连续、每份 state/Judge 均通过 Pydantic、
`trusted-evaluation.json` 与最后一个 attempt receipt 完全一致。损坏、中间缺口或 latest
不一致不能降级成“没有 receipt”。Canonical payload 规则：

- 顶层 `transientBuildState` / `judgeAdvisoryReport` 可省略，由最后一个 receipt 补全；
- `generationAttempts[*]` 可只写 `attemptIndex`、candidate 和 failure audit；对应 state/Judge
  由同 index receipt 补全；
- 如果 Agent 仍显式提供可信字段，必须与 receipt 完全一致，继续防止篡改；
- 顶层 candidate 和 failure audit 可从最后一个 compact attempt 派生；如果显式提供，必须与
  最后一个 attempt 完全一致；
- 最终 candidate ID 必须对应最后一个 receipt；receipt 不会把 candidate 内容本身升级为可信；
- 旧的完整 payload 保持兼容。

`PrototypeBuildCandidate` 将 `memoryReferences` 规范化为以下字段的去重并集，而不再要求 Agent
手工复制：

- `researchMemoryUse.dedupeQueryRefs`；
- build family / deep record / pattern / semantic edge / memory item IDs；
- Agent 额外提供的安全引用。

这不会减少来源审计：typed `researchMemoryUse` 仍是权威，tool reference 和 memory-mode gate
仍保留。

### 2. 增加可重复的非消费校验和紧凑结果

Create CLI 增加：

- `validate-output`：读取 trusted receipts、补全 canonical payload、执行完整 schema/domain/retry
  校验，但不消费 run；
- `review-packet --compact`：完整 review 仍写入 `review-result.json`，stdout 只返回状态、路径、
  最终 Judge 摘要与 retry delta，减少长输出占用上下文；
- `start-run` 初始化带 run binding 的最小 `agent-output.json` 骨架，避免 Agent 再抄 run ID、
  token、prompt ID 和 packet ID。

Schema 错误必须返回稳定的字段路径和简短 message，不回显原始 payload。

### 3. 增加 Judge 前的活动构筑预检

新增 typed MCP tool `inspect_generation_preflight`，只读取当前活动 build，不启动 dedicated Judge。
它至少检查：

- main skill group 是否存在；
- generated candidate 的 group 是否只有一个 active skill；
- 同 group 是否有重复 support；
- 是否存在完全重复的 enabled skill group；
- completeness hard failures；
- completeness advisories 作为非阻断提示。

`evaluate_generation_candidate` 只抓取一次 active XML；预检与 dedicated Judge 必须共享这份
不可变 XML，禁止再次抓取活动状态造成 TOCTOU。确定性的 blocking issue 存在时不创建 Judge
engine、不写 attempt receipt、不消耗 retry，返回 `generation_preflight_failed`。重复主动技能名
但 support/用途不同不能机械阻断；只有基于 gem/skill ID 与排序后 support ID 的完整 group
signature 重复才阻断。

### 4. 拆分 offense 观察值与证据置信度

Judge offense breakdown 增加：

- `rawDps` / `effectiveDps`；
- `observedValue`：按阶段目标计算的原始得分；
- `metricStatus`：`available` 或 `unavailable`；
- `floorStatus`：`met`、`missed`、`unverified` 或 `unavailable`；
- `deliveryEvidenceStatus`：`established`、`limited` 或 `unavailable`；
- `floorProgress` 与 `scoreConfidenceFactor`；
- `scorePolicy`：说明使用原始 stage curve 还是 limited-evidence confidence adjustment。

规则：

- 有正 DPS 且 evidence strong：delivery evidence 为 `established`，是否达到阶段地板由
  `floorStatus` 单独表达；
- 有正 DPS 但 evidence limited：delivery evidence 为 `limited`；
- 没有可用 DPS：metric 和 delivery evidence 为 `unavailable`；
- `floorProgress = clamp(effectiveDps / hardFloor, 0, 1)`；
- `scoreConfidenceFactor` 为 strong 1.0、limited 0.5、none 0.0；
- `offenseValue = observedValue * scoreConfidenceFactor`；`floorProgress` 只作诊断，不加分；
- physical-invalid、core-blocked、not-modelable 或 DPS<=0 时仍为 0；
- strong evidence 低于 hard floor 继续产生 playability failure 和 `reward=none`；
- limited evidence 低于 floor 继续保留 floor-unverified caveat，reward 最多 limited；
- strong evidence 低于 floor 时不再附加 `offense_delivery_not_established`；低伤害由
  `floorStatus=missed` 和 `below_playability_floor` 解释；
- `offense_delivery_not_established` 仅表示 evidence limited/unavailable，不能再暗示阶段伤害一定
  低，也不能替代 hard-floor 判断；
- limited delivery 继续限制 aggregate / quality band 和 reward，绝不能产生 strong reward。

同 DPS 下 limited evidence 得分不得高于 strong evidence。`effectiveDps` 不再乘所谓实战 uptime
系数；当前 Judge 没有足够证据推断真实 uptime。

脱敏 offense evidence 必须进入 `JudgeAdvisoryReport` 和 trusted receipt，而不是只留在 raw
Judge result。字段包括 raw/effective DPS、source metric、evidence level、observed value、floor
progress/status、delivery evidence status 与 score policy。

本轮不尝试为 Tempest Bell 之类的轮转技能发明 uptime 或自动合并 DPS。条件性伤害继续作为
supplemental diagnostic。

### 5. 减少无操作价值的 caveat

- 合法、单主动技能、support 已被 PoB 识别的 group 不再默认携带
  `support_conflict_unverified_caveat`；这是减少无效核验和 retry，不改变 aggregate 或 reward。
  具体 disable/unknown/duplicate 情况仍报告明确错误。
- campaign / maps-entry 通过 `levelBand` 表达评价范围，不再追加
  `non_endgame_sample_caveat`，也不新增 blanket reward limit。同一 level band 内证据充分的阶段型
  构筑可以产生 strong Judge evidence；Phase 5 人工验收包仍按自身原型安全合同不透出 strong
  reward，二者不能混为一谈。跨 level band 比较返回 `level_band_mismatch`，这是比较合同不成立，
  不是对非终局样本扣分。
- FullDPS 的根因先在 `pob_headless.lua` 修正：direct DPS 与 FullDPS 相等或在容差内时优先
  direct；只有 FullDPS 实质更高或 direct=0 时才选 FullDPS。bridge 同时保留 direct/full
  diagnostic。`full_dps_rollup_caveat` 只在 offense source metric 确实为 FullDPS 时进入 offense
  evidence。条件性附加技能仍使用 `conditional_supplemental_damage_caveat`。

### 6. 修正最终分类语义

- core mechanic `not_modelable` / core-blocked：保留
  `judge_unsolved_modelability_gap`；
- full/partial modelability 下，只有 delivery evidence 为 limited/unavailable 的低分才归为
  `judge_offense_evidence_gap`；strong direct evidence 低于阶段 floor 属于真实阶段伤害不足；
- modelability 可用但仍存在无法解释的低分：`judge_score_review_required`；
- 已解释的真实低质量、合法性失败、严重可玩性失败和 source-data problem 保持现有分类。

`FailureAuditSummary.classification` 与 `ToolFeedbackEvent.feedbackType` 同步接受 offense evidence
gap / score review 语义，避免 Agent 被迫继续写成 modelability gap。

### 7. 明确 lifecycle evidence coverage

Human review packet 只由最终可信 state/Judge 自动计算：

- `evaluatedStages`：本 run 最终 snapshot/Judge 真正覆盖的至多一个阶段；
- `textOnlyStages`：candidate 声明但本 run 未数值验证的阶段；
- `coverageStatus`：`complete` 或 `partial`。

阶段采用 knowledge lifecycle 的 canonical 名称与边界，并为 generation 的历史别名建立显式
映射：1—25 early、26—45 mid、46—64 late、65—75 maps-entry，76 以上按目标合同进入 budget/
final endgame；`budget_endgame/final_endgame` 规范化为 `endgame_budget/endgame_final`。本轮不把
三次 retry receipt 改造成多阶段 snapshot；retry 和 lifecycle evidence 必须继续是两种不同
语义。后续若实现多阶段验证，应新增 stage-keyed receipt，而不是复用 attempt index。

Judge 自身当前在 69→70 时把 DPS hard floor 从 5,000 跳到 50,000。这一阈值不连续列为后续
校准项；`floorProgress` 只改善诊断表达，不绕过或软化该阈值。

## 验收标准

### Create

- 一次 memory-assisted 三尝试 run 可用 compact attempt 输入生成 review packet；
- trusted state/Judge 缺失时自动补全，显式篡改时仍拒绝；
- memory references 自动规范化且不削弱 no-memory / memory-assisted gate；
- `validate-output` 可重复调用且不消费 run；
- `review-packet --compact` 仍把完整包原子写入 review-result；
- preflight 在完全重复 skill group 时阻止 Judge，在不同 support/职责的同名技能时不误杀；
- review packet 明确显示 1—70 请求中只有 70 级阶段得到数值验证。

### Judge

- 正 DPS 不再被误写成 metric unavailable；低于 hard floor 时仍可按既有 stage curve 得到 0 分，
  但必须由 floor/playability 语义解释，不能归因于 delivery evidence；
- breakdown 同时保留阶段门槛、原始观察分、floor progress 和 delivery status，不用未经校准的
  credit 改写实际 offense 分；
- limited delivery 仍不能获得 strong reward，quality band 不能伪装成完成态；
- direct selected-skill DPS 不再继承无关 FullDPS caveat；
- 合法 socket group 不再得到无条件 support-conflict caveat；
- maps-entry sample 不再得到 non-endgame 缺陷 caveat，也不因阶段本身受到 blanket reward limit；
- full modelability 的 limited-offense case 不再分类为 modelability gap。

### 回归

- focused generation/Judge/server tests 全部通过；
- `scripts/verify.ps1 quick` 通过；
- 因修改 `pob_headless.lua`，执行 `scripts/verify.ps1 compute`，外层超时至少 30 分钟；
- 变更不写 durable reward memory，不新增 raw PoB 输出，不改变 artifact snapshot/hash gate。
