# Judge 评分系统说明

最后更新：2026-07-12

本文档描述 Phase 1 当前实现的 Judge 评分系统，包括：

- 分数如何计算；
- 哪些情况会直接判非法；
- 哪些分数只是“有限证据”；
- 为了兼容 poe.ninja、PoB 导入态、特殊防御模型，我们做了哪些查询与降级逻辑；
- 这些结果后续如何进入比较（comparison，对比）与 reward（奖励信号）。

本文档只描述当前代码真实实现，不描述未来理想态。

---

## 0. 术语对照表

为了方便阅读，下面列出本文反复出现的英文术语与中文含义：

| 英文术语 | 中文说明 |
| --- | --- |
| `Judge` | 评估器 / 裁判器 |
| `evidence-aware` | 证据感知 |
| `BuildEvaluation` | 构筑评估结果 |
| `BuildComparison` | 构筑对比结果 |
| `hard failure` | 强失败 / 硬失败 |
| `hard floor` | 硬地板 |
| `quality floor` | 质量起评分 |
| `target` | 目标线 |
| `score vector` | 分项分数向量 |
| `aggregate score` | 综合分 |
| `scenario fit` | 场景适配分 |
| `modelability` | 可建模性 |
| `provenance` | 证据来源 |
| `evidence level` | 证据强度 |
| `strong evidence` | 强证据 |
| `limited evidence` | 有限证据 |
| `trusted reference` | 外部可信参考样本 |
| `fallback` | 回退 / 兜底 |
| `downgrade` | 降级处理 |
| `rollup` | 汇总面板 |
| `socket group` | 技能组 |
| `active skill` | 主动技能 |
| `support gem` | 辅助宝石 |
| `main skill` | 主技能 |
| `weapon check` | 武器兼容性检查 |
| `reward eligible` | 是否允许产生奖励信号 |
| `reward strength` | 奖励强度 |
| `selection winner` | 选择赢家 |
| `reward winner` | 奖励赢家 |
| `blocked` | 被阻断 / 熔断 |
| `source data problem` | 来源数据问题 |
| `unsolved modelability gap` | 暂未解决的可建模性缺口 |

---

## 1. Judge 的职责边界

Judge 不是一个新的数值引擎，而是一个 **evidence-aware evaluator（证据感知评估器）**。

评估输出严格拆成四层，不能互相冒充：

1. **Legality（合法性）**：`hardFailures`，只包含职业、插槽、武器、属性、预算和装备等
   确定性非法；决定 `pass`。
2. **Severe Playability（严重可玩性）**：`playabilityFailures`，表示 BD 合法但存在严重输出、
   抗性或防御短板；不改变 legality pass，分类为 `severe_playability_failure`，不能作为最终推荐产物。
3. **Quality（质量）**：`qualityWarnings` 与 score vector，表示未达到推荐质量目标，不是非法。
4. **Modelability（可建模性）**：说明 PoB 是否足以支撑数值结论；核心不可建模时
   `scoreApplicability=unavailable`，不能引用综合分作强度结论。

Score Vector（分项分数向量）输出四个核心维度：
   - `offense`（进攻）
   - `defense`（防御）
   - `recovery`（恢复）
   - `mobility`（机动）

Reward Safety（奖励安全）在四层之上防止有限证据和 PoB 盲区污染后续奖励记忆。

换句话说，Judge 不承诺“把所有机制都算准”，但它必须诚实地说明：

- 这是强证据；
- 这是有限证据；
- 这里是 PoB 暂时无解的机制盲区；
- 这里是导入态/状态态本身可疑。

---

## 2. 总体流程

当前评估流程可以概括为：

1. `PobEngine` 导入构筑。
2. Lua bridge（Lua 桥接层）从 Headless PoB 回读基础数据。
3. `judgeSelectedSkill`（Judge 主技能选择器）主动扫描技能组，选择真正参与 offense 的技能。
4. `rules.py` 先跑 legality blockers（合法性阻断器）。
5. `modelability.py` 判断是否存在 core unmodelled mechanic（核心不可建模机制）。
6. `scoring.py` 计算四项分数、aggregate（综合分）、scenario fit（场景适配分）。
7. `evaluator.py` 整合为 `BuildEvaluation`（构筑评估结果）。
8. `comparison.py` 决定这个结果是否可以参与强 reward。

对应的主要代码位置：

- [server/judge/scoring.py](/E:/poe-bd-creator/server/judge/scoring.py)
- [server/judge/evaluator.py](/E:/poe-bd-creator/server/judge/evaluator.py)
- [server/judge/rules.py](/E:/poe-bd-creator/server/judge/rules.py)
- [server/judge/modelability.py](/E:/poe-bd-creator/server/judge/modelability.py)
- [server/judge/comparison.py](/E:/poe-bd-creator/server/judge/comparison.py)
- [pob/pob_headless.lua](/E:/poe-bd-creator/pob/pob_headless.lua)

---

## 3. 分数体系总览

### 3.1 分数范围

当 `scoreApplicability=applicable` 时，核心分项和综合分使用：

- `scoreScale = "0_to_1"`

也就是：

- `0.0` = 极差 / 不可用 / 被阻断
- `1.0` = 达到当前 target（目标线）或超过目标线

当核心机制 `not_modelable` 时，分数字段只保留内部诊断占位，`qualityBand=unmodelled`，不得用于
强度结论、最终产物验收或 reward。

### 3.2 维度

Judge 当前输出这些主维度：

| 维度 | 含义 | 备注 |
| --- | --- | --- |
| `offense` | 进攻能力 | 依赖所选 damage skill（伤害技能） |
| `defense` | 防御能力 | 以 Max Hit（最大承伤）为主轴 |
| `recovery` | 恢复能力 | 基于可用主资源池的动态恢复 |
| `mobility` | 机动能力 | 以移动速度为主，必要时用技能速度兜底 |

此外还有三个展示型分数：

- `mappingFit`（刷图适配）
- `bossingFit`（打 Boss 适配）
- `hybridFit`（综合适配）

注意：这三个是 **scenario fit（场景适配）展示分**，不是 legality 判定，也不是 reward 的唯一依据。

### 3.3 综合分权重

当前综合分按等级阶段使用不同权重。合法性与完整度独立判定，不进入加权分：

```text
campaign:   offense 0.35 / defense 0.30 / recovery 0.20 / mobility 0.15
maps_entry: offense 0.375 / defense 0.35 / recovery 0.175 / mobility 0.10
endgame:    offense 0.40 / defense 0.40 / recovery 0.15 / mobility 0.05
```

权重 profile（权重配置名）为：

- `judge_v6_evidence_separated`

这组权重属于项目产品启发式，不是官方规则。阶段感知调整的依据是：剧情开荒的实际体验高度
依赖资源恢复和移动/走位，而终局数值比较仍更依赖伤害与防御。权重仍需用真实构筑样本和人工
验收继续校准，不能据此声称某个 BD 客观全局最优。

---

## 4. Hard Floor、Quality Floor、Target

Judge 明确区分三类阈值：

### 4.1 Hard Floor（硬地板）

这是“低到接近不可运行”的阈值。

如果低于 hard floor，不一定立刻非法，但会进入：

- `below_playability_floor`（低于可玩底线）
- `catastrophic_defense_shortboard`（灾难性防御短板）

之类的强负面路径。

### 4.2 Quality Floor（质量起评分）

这是“成熟 BD 开始像样”的起评分位置。

低于 quality floor：

- 不代表一定非法；
- 但该项质量分会很低，甚至为 0；
- 同时会在 `qualityWarnings` 追加具体维度的质量目标警示。

### 4.3 Target（目标线）

达到 target 之后，该项分数记为 `1.0`。

目标线以上不继续线性暴涨，避免被虚高面板破坏权重。

---

## 5. 标准评分公式

Judge 对多数连续指标使用 **logarithmic score（对数评分）**：

```text
value <= floor      -> 0
value >= target     -> 1
otherwise           -> log10(value / floor) / log10(target / floor)
```

实际代码入口：

- `target_log_score(...)`

这样做的原因是：

- 能给“刚过线”和“远超线”的构筑留出差距；
- 能压制 5000 万 DPS 这种极端面板对总分的破坏；
- 更符合 PoE2 成熟 BD 的边际收益递减。

---

## 6. Level Band（等级分段）

Judge 不是一套固定终局线打天下，而是按等级段使用不同标准：

- `campaign`（战役期）
- `maps_entry`（初入地图）
- `endgame`（终局）

当前分段规则：

- `< 70` -> `campaign`
- `70 - 79` -> `maps_entry`
- `>= 80` -> `endgame`

等级段本身已经表达评价范围，因此 campaign / maps-entry 不再把
`non_endgame_sample_caveat` 当作构筑缺陷，也不因“非终局”本身降低分数或 reward。阶段型候选
只能和相同目标阶段、版本及场景下的样本比较；证据 limited、partial modelability 或其他明确
限制仍通过各自的 `rewardLimitReasons` 约束。`BuildComparison` 遇到不同 `levelBand` 时返回
`level_band_mismatch`，不比较 aggregate，也不把范围不一致伪装成某一方的低分。

---

## 7. Offense（进攻）评分

## 7.1 先选“真正的输出技能”

Judge 不盲信导入后当前选中的 main skill（主技能）。

Lua 里的 `computeJudgeSelectedSkill()` 会主动遍历所有 socket group（技能组）和 active skill（主动技能），并做这些事情：

1. 临时把每个技能组单独设置为 `includeInFullDPS`。
2. 读取该组下可用的伤害指标。
3. 对 `Buff / Aura / Herald / HasReservation / Hex / Mark / Warcry / Travel / Banner`
   这类 utility-only active（纯功能型主动技能）降优先级。
4. 如果是 minion（召唤物）技能，尝试从 PoB 的 minion output（召唤物输出）路径取值。
5. 选出当前最可信、数值最高、又不是纯功能技能的候选。

这就是 `judgeSelectedSkill`。它表示 Judge 本次用于 offense 评分的一个伤害组件，不等于整个 BD
只有一个主技能，也不等于 `mainSocketGroup` 之外的技能都不重要。

PoB 还会把部分升华、装备或机制产生的内部效果动态加入技能组列表。Judge 必须区分：

- 玩家配置或来源明确的可用技能组；
- PoB 当前计算组；
- 条件性内部合成效果，例如只在击杀后发生的爆炸；
- Judge 本次选中的伤害组件。

条件性击杀爆炸保留为 `judgeSupplementalSkills`，并标记 `requires_kill`。它可以帮助解释清图能力，
但不能代表 Boss 持续输出，也不能因为没有普通宝石插槽而触发 `invalid_socket_setup`。

它会额外返回：

- `skillName`（技能名）
- `groupIndex`（技能组索引）
- `sourceMetric`（取值来源）
- `rawDps`（原始 DPS）
- `effectiveDps`（有效 DPS）
- `activeSkillCount`（有效召唤/实例数量）
- `activeMinionLimit`（召唤上限）
- `projectileCount`（投射物数量）
- `weaponCheck`（武器兼容性）
- `caveats`（警示）
- `groupOrigin`（技能组来源类型）
- `socketLegalityApplicable`（是否适用普通宝石插槽合法性）
- `scenarioLimitations`（例如 `requires_kill`）

如果最终选中的不是原始 `mainSkill`，会追加：

- `auto_selected_damage_skill_caveat`

如果存在未纳入主要 offense 数值的条件性附加伤害组件，追加：

- `conditional_supplemental_damage_caveat`

### 7.2 offense 取值优先级

PoB 字段按上游实际定义解释：

- `AverageDamage`：平均单次命中；
- `TotalDPS`：PoB 界面的 Hit DPS，即平均命中乘攻击/施法频率及引擎已识别的数量倍率；
- `CombinedDPS`：当前技能的 Hit DPS 加 PoB 已建模的持续伤害和次级组件；
- `FullDPS`：被纳入 Full DPS 的技能 actor、技能组与持续伤害汇总。

这些字段都不自动证明真实战斗覆盖率、技能轮转同时成立或投射物重叠。

Python 层优先看 `JudgeDPS`。如果 Lua 已经给出 `judgeSelectedSkill`，就使用它。

Lua 会同时保留 `directDps` 和 `fullDps`。两者相等或仅有浮点误差时优先直接指标；只有
`FullDPS` 实质更高或直接指标为 0 时才把 `FullDPS` 作为 offense 来源，避免无意义的 rollup
caveat 污染直接 PoB 证据。

否则才 fallback（回退）到 PoB 常规字段：

- `FullDPS`
- `CombinedDPS`
- `WithPoisonDPS`
- `WithIgniteDPS`
- `WithBleedDPS`
- `WithImpaleDPS`
- `WithDotDPS`
- `TotalDPS`
- `MinionCombinedDPS`
- `MinionTotalDPS`

### 7.3 offense 证据分层

Judge 对 offense 明确区分 provenance（证据来源）和 evidence level（证据强度）。

`scoreBreakdown.offense` 同时输出观察值与可信度：`metricStatus`、`floorStatus`、
`deliveryEvidenceStatus`、`observedValue`、`floorProgress`、`scoreConfidenceFactor` 和
`scorePolicy`。阶段地板进度只作诊断，不给未经校准的额外分：

```text
floorProgress = clamp(effectiveDps / hardFloor, 0, 1)
offenseValue = observedValue * confidenceFactor
```

strong / limited / none 的 confidence factor 分别为 1 / 0.5 / 0。正 DPS 低于 hard floor
不再被描述成“指标不可用”。strong direct evidence 的 delivery 已建立，即使其数值低于地板；
此时用 `floorStatus=missed`、`below_playability_floor` 和 0 分表达阶段伤害不足，不再追加 delivery
不足警告。limited evidence 继续标记 delivery limited，并且最多产生 limited reward。物理非法、
核心不可建模或 DPS 为 0 时仍为 0。

注意：当前 69→70 级会把 DPS hard floor 从 5,000 提高到 50,000。这个边界已用回归测试明确
记录，但仍是待真实样本校准项。`floorProgress` 让人工看见距离，但不会绕过或软化该阈值。

#### A. `direct_pob_dps`（PoB 直接伤害）

- 默认 `evidenceLevel = strong`
- 这是最理想的 offense 证据

#### B. `isolated_full_dps_rollup`（隔离技能组后的 FullDPS 汇总）

- 默认 `evidenceLevel = limited`
- 追加 `full_dps_rollup_caveat`

含义不是“这就是严格单体真 DPS”，而是：

- 这是 PoB 对当前技能组的 rollup（汇总面板）；
- 它汇总了被纳入 Full DPS 的 actor 与持续伤害组件；
- 但仍不能自动等同于真实全命中、全覆盖、全时序成立的最终伤害。

#### C. `minion_pob_output`（PoB 召唤物输出）

- 默认 `evidenceLevel = limited`
- 追加 `minion_dps_unverified_caveat`

如果是非 `FullDPS` 的 minion 路径：

- 优先用 `activeSkillCount`
- 没有时才 fallback 到 `ActiveMinionLimit`
- 然后计算：

```text
effectiveDps = rawMinionDps * count
```

并追加：

- `minion_count_multiplier_caveat`

原因是：

- 不乘数量会系统性低估召唤 BD；
- 但这个乘法仍是 PoB 外层近似，因此只能给 limited evidence。

#### D. `unknown_or_unavailable`（未知或不可用）

表示当前拿不到可靠 offense 数据。

### 7.4 projectile overlap（投射物重叠）

如果 `ProjectileCount > 1` 且当前用的不是 `FullDPS`，Judge 会追加：

- `projectile_overlap_unverified_caveat`

含义是 PoB Hit DPS 可能已包含引擎认识的数量倍率，但额外投射物究竟能否重叠单体、只增加覆盖，
或参与次级效果仍需按具体技能核验。Judge 不手工乘投射物数量，也不再把 `TotalDPS` 统称为下界。

### 7.5 offense 阈值

当前 `endgame` 的主要进攻阈值：

| 指标 | 数值 |
| --- | ---: |
| `hard_floor` | 50,000 |
| `quality_floor` | 300,000 |
| `target` | 2,500,000 |

如果当前 evidence 是 limited，会改用更保守的 limited target：

- `quality_floor = 150,000`
- `target = 750,000`

这样做的目的不是“放水”，而是避免把有限证据误当成强证据去打死。

---

## 8. Defense（防御）评分

### 8.1 主轴：五类 Max Hit（最大承伤）

Judge 当前防御主轴不是护甲、闪避、格挡某一项单独数值，而是五类最大承伤：

- `PhysicalMaximumHitTaken`（物理最大承伤）
- `FireMaximumHitTaken`（火焰最大承伤）
- `ColdMaximumHitTaken`（冰霜最大承伤）
- `LightningMaximumHitTaken`（闪电最大承伤）
- `ChaosMaximumHitTaken`（混沌最大承伤）

每一项都会单独打分，再组合成最终防御分。

### 8.2 异构阈值

物理与元素/混沌不是一条线。

当前 `endgame` 阈值：

| 类型 | hard floor | quality floor | target |
| --- | ---: | ---: | ---: |
| 物理 `physical` | 5,000 | 6,000 | 12,000 |
| 元素 `elemental` | 5,000 | 12,000 | 25,000 |
| 混沌 `chaos` | 1,000 | 8,000 | 18,000 |

### 8.3 CI（Chaos Inoculation，异灵之体）特判

如果构筑明确拥有 `Chaos Inoculation`：

- 混沌分数直接记为 `1.0`
- `sourceMetric = "ChaosInoculation"`
- 不用 `ChaosMaximumHitTaken` 的 nil / 0 / 极大值去反推

同时会追加：

- `ci_chaos_immunity_caveat`

如果 keystone（关键天赋）读不到，而是通过 `Chaos Resist >= 100` 弱推断出来，会再追加：

- `ci_resist_fallback_caveat`

### 8.4 物理短板 EHP 补偿

如果五类短板中，最低的是物理，并且 `TotalEHP`（总等效血量）很高，会保留一个有限物理补偿：

```text
ehp_multiplier = clamp(TotalEHP / 40000, 1.0, 1.5)
phys_score = min(1.0, phys_score * ehp_multiplier)
```

重要边界：

- 只补 physical（物理）
- 不补元素
- 不补混沌
- 上限固定 1.5x

这是为了避免右半区高闪避 / 高规避 BD 被单纯的物理 Max Hit 误杀。

### 8.5 最终 defense 组合

当前 defense 使用：

```text
defense = 0.6 * min_score + 0.4 * mean_score
```

也就是：

- 仍然重视最短板；
- 但不完全等于“只看最差那一项”。

### 8.6 avoidance_evasion_hybrid（规避混合型）特殊策略

如果满足典型高闪避画像，例如：

- `EvadeChance >= 55`
- `TotalEHP >= 17000`
- 物理 Max Hit 不是 0，但偏低
- 元素分数整体还过得去

Judge 会把防御策略标为：

- `scorePolicy = "avoidance_evasion_hybrid"`

这不是直接洗白，而是把 defense 从“纯 Max Hit 木桶”稍微往真实规避流方向拉回一点。

### 8.7 catastrophic_defense_shortboard（灾难性防御短板）

Judge 不会因为单个 `phys max hit` 低就直接判死。

当前需要多信号同时成立，例如：

- `phys < 5000`
- `TotalEHP < 12000`
- 没有明显 avoidance proof（规避证明）：
  - `EvadeChance >= 55`
  - `EffectiveAverageBlockChance >= 20`
  - `EffectiveSpellSuppressionChance >= 75`
  - `AvoidAllDamageFromHitsChance >= 15`
  这些都不满足
- 再加一条强恶化条件：
  - `phys < 3000`
  - 或至少两项元素 Max Hit 低于 hard floor
  - 或非 CI 且 `chaos < 1000`

这时才会触发：

- `catastrophic_defense_shortboard`

### 8.8 抗性分层

75% 是默认元素抗性上限和推荐质量目标，不是合法性条件。当前使用三层结构：

- `campaign`：任一元素抗性 `< 30%` 才进入
  `severe_elemental_resistance_shortfall`；
- `maps_entry` / `endgame`：任一元素抗性 `< 60%` 才进入该严重可玩性失败；
- 任一元素抗性 `< 75%` 时进入 `elemental_resistance_below_cap` 质量警示。

非 CI 构筑混沌抗性为负时使用 `negative_chaos_resistance` 质量警示，不再把它与确定性非法混合。
剧情阶段混沌抗达到 `0%` 后，混沌 Max Hit 保留诊断，但不参与防御 shortboard，避免诱导 Agent
牺牲输出、恢复、移动和属性去强追剧情混沌满抗。

---

## 9. Recovery（恢复）评分

### 9.1 主资源池不是固定生命

恢复分的关键是 **primary pool（主资源池）**。

当前 Judge 会在这些候选里选最大的：

- `LifeUnreserved`（未保留生命）
- `EnergyShield`（能量护盾）
- `ManaUnreserved`（未保留法力，限 MoM 相关情形）

这解决了几个历史坑：

- low-life（低血）/ 高保留生命构筑，不能用 `Total Life` 当主池
- CI（异灵之体）构筑不能因为生命低而恢复崩溃
- MoM / EB + MoM（心灵升华 / 异能电池 + 心灵升华）构筑，必要时主池应切到 mana

### 9.2 生命与法力缺字段的 fallback

如果没有 `LifeUnreserved` 但有 `Life`：

- 会 fallback 到 `Life`
- 并追加 `life_unreserved_missing_caveat`

如果 MoM 构筑没有 `ManaUnreserved` 但有 `Mana`：

- 会 fallback 到 `Mana`
- 并追加 `mana_unreserved_missing_caveat`

如果主池最终仍不可得：

- `primary_pool_unavailable_caveat`
- recovery 分数记为 `0`

不会伪造一个静态主池。

### 9.3 recovery 取值

生命侧恢复取三者最大值：

- `LifeRegenRecovery`
- `LifeLeechGainRate`
- `LifeRecharge`

如果 `LifeLeechGainRate` 不可用，会用：

- `LifeOnHitRate`

护盾侧恢复取三者最大值：

- `EnergyShieldRegenRecovery`
- `EnergyShieldLeechGainRate`
- `EnergyShieldRecharge`

如果 `EnergyShieldLeechGainRate` 不可用，会用：

- `EnergyShieldOnHitRate`

法力侧恢复取三者最大值：

- `ManaRegenRecovery`
- `NetManaRegen`
- `ManaLeechGainRate`

必要时用：

- `ManaOnHitRate`

### 9.4 动态恢复阈值

默认恢复阈值：

```text
quality_floor = primary_pool * 0.03
target        = primary_pool * 0.15
```

如果主池较小（`<= 3000`），会切到更宽容的一组：

```text
quality_floor = primary_pool * 0.015
target        = primary_pool * 0.08
```

这是为了避免小池构筑被不合理地要求“每秒 15%”。

### 9.5 recovery 诊断字段

Judge 会把这些诊断也保留下来，方便人工排查：

- `Life`
- `LifeUnreserved`
- `LifeReserved`
- `LifeUnreservedPercent`
- `EnergyShield`
- `Mana`
- `ManaUnreserved`
- `ManaUnreservedPercent`
- `lifePoolSource`
- `primaryPoolSource`

---

## 10. Mobility（机动）评分

Judge 优先读取移动相关字段：

- `EffectiveMovementSpeedMod`
- `MovementSpeedMod`
- `MovementSpeedWhileUsingSkill`

如果这些字段能读到，就按移动速度评分。

如果这些字段读不到或分数太差，但 `Speed`（技能速度）比较可靠，会回退到：

- `Speed`

并追加：

- `skill_speed_mobility_fallback_caveat`

这让一些移动速度字段不稳定、但实际动作很快的构筑，不至于 mobility 直接归零。

---

## 11. Scenario Fit（场景适配分）

当前三种场景分数的计算方式是：

### `mappingFit`（刷图）

```text
offense * 0.35 +
defense * 0.25 +
recovery * 0.10 +
mobility * 0.30
```

### `bossingFit`（Boss）

```text
offense * 0.45 +
defense * 0.35 +
recovery * 0.15 +
mobility * 0.05
```

### `hybridFit`（综合）

```text
offense * 0.40 +
defense * 0.35 +
recovery * 0.15 +
mobility * 0.10
```

它们是展示型分数，主要用于回答：

- 这个构筑更偏刷图还是更偏打 Boss？

不是 legality blocker（合法性阻断器）。

---

## 12. Quality Band（质量档位）

当前质量档位：

- `invalid`（非法）
- `barely_playable`（勉强可玩）
- `prototype_only`（已有观察值，但 offense delivery 证据不足）
- `entry_endgame`（能进终局）
- `solid`（扎实）
- `strong`（强）

规则大致是：

- 被 blocked（阻断） -> `invalid`
- 出现强底线失败 -> `barely_playable`
- 生成候选的 delivery evidence 不是 established -> `offense_delivery_not_established`（进攻兑现
  尚未建立）和 `prototype_only`，综合分上限为 0.34，因此不能被其他维度平均成 `solid`；这不是
  确定性非法，也不表示 PoB 没有正 DPS，而是表示当前候选还没有足够证据作为可交付成品
- 综合分高 -> `solid` 或 `strong`

---

## 13. Physical Invalid（物理非法）与熔断

以下 failure code（失败码）属于 physical-invalid blocker（物理非法阻断器）：

- `invalid_class_ascendancy_pairing`
- `invalid_socket_setup`
- `support_limit_exceeded`
- `duplicate_support_gem`
- `invalid_support_gem`
- `attribute_requirement_unmet`
- `incompatible_weapon_skill_tags`
- `attack_skill_without_weapon`
- `passive_budget_exceeded`
- `weapon_set_budget_exceeded`
- `spirit_budget_exceeded`

一旦命中这些 blocker：

- `offense / defense / recovery / mobility` 全部标记 `blocked = true`
- 四项分数直接清零
- `aggregate = 0`
- 不允许产生正向 reward

这是“非法”和“低分”的本质区别：

- 低分仍然是合法 BD；
- blocked 则说明 Judge 明确认为它在当前合同下不合法。

---

## 14. Trusted Reference（外部可信样本）兼容策略

对于 `trusted_reference`，Judge 会更谨慎地区分：

- 真正的构筑非法
- 导入态异常
- 站点样本漂移
- PoB/网页状态不一致

因此会对一部分问题做 downgrade（降级处理），从 hard failure 改成强警示 caveat，例如：

- `external_passive_budget_anomaly_caveat`
- `external_weapon_set_budget_anomaly_caveat`
- `trusted_reference_attribute_requirement_mismatch_caveat`
- `trusted_reference_floor_unverified_caveat`

这不代表“Judge 放过错误”，而是：

- 对外部成熟样本，我们优先避免把 intake / import（采集 / 导入）异常学成 archetype 负样本；
- 这些样本默认不能进入 `strong reward`。

---

## 15. Modelability（可建模性）与 Limited Evidence

### 15.1 三种状态

当前 `modelability` 分为：

- `full`（可完整建模）
- `partial`（部分可建模）
- `not_modelable`（不可建模）

### 15.2 core blocked（核心阻断）

如果主技能组存在某些核心 meta trigger（元触发）支持，例如：

- `Cast on Critical`
- `Cast on Shock`
- `Cast on Freeze`
- `Cast on Ignite`
- `Cast on Minion Death`

并且它处在主技能组核心位置，就会触发 `main_socket_group_core_unmodelled` 与
`trigger_rate_unmodelled_caveat`。

这不进入 `hardFailures`：Spirit 预算仍正常做确定性检查，但触发事件频率、Energy 累积、冷却与
被触发技能总输出当前无法可靠计算，因此 `pass` 可以为 true，`scoreApplicability` 为
`unavailable`，且不能保存为已数值验证的最终产物或产生正向 reward。

这时比较结果会被判成：

- `incomparable`（不可比较）

### 15.3 limited reward（有限奖励）

以下 caveat 会把 reward 降为 limited：

- `projectile_overlap_unverified_caveat`
- `minion_dps_unverified_caveat`
- `minion_count_multiplier_caveat`
- `full_dps_rollup_caveat`
- `metric_unavailable_caveat`
- `primary_pool_unavailable_caveat`
- `dual_weapon_state_limited_caveat`
- 以及若干 trusted reference / source-data 兼容 caveat

含义是：

- 可以展示分数；
- 可以做 selection（选择）；
- 但不能把它当成强 reward memory 的稳定监督信号。

对于本系统生成的候选，limited offense evidence（有限进攻证据）仍可以保留用于诊断，但如果
offense 分数实际为 0，则最终 PoB artifact（产物）保存门槛必须拒绝该候选。成熟参考 BD 的校准
样本不套用这一生成候选交付上限，以免把 PoB 无法建模的成熟机制误写成真实失败。

---

## 16. Comparison（比较）与 Reward Contract（奖励合同）

当前比较合同有三层：

### 16.1 `selectionWinner`

谁在当前信息下更值得被选中。

### 16.2 `rewardWinner`

谁可以被当作可靠 reward 信号写入后续学习。

### 16.3 `rewardStrength`

- `strong`
- `limited`
- `none`

当前规则：

1. 双方都合法、且 full modelability、且强证据  
   -> `rewardStrength = strong`

2. 任一方是 limited evidence 或 partial modelability  
   -> 可以有 `selectionWinner`  
   -> `rewardWinner = unknown`  
   -> `rewardStrength = limited`

3. physical-invalid / core unmodelled / compute failed  
   -> `rewardStrength = none`

这就是 Judge 当前防污染的核心。

---

## 17. Defense Model（防御模型诊断）

`BuildEvaluation` 里还有一个诊断层：

- `defenseModel`

它不会直接代替 defense 分数，但会解释：

- 这是 life（生命）构筑
- 这是 low_life（低血）构筑
- 这是 es（护盾）构筑
- 这是 ci（异灵之体）构筑
- 这是 mom（心灵升华）构筑
- 这是 `eb_mom_mana`（异能电池 + 心灵升华，以法力为主池）构筑
- 这是 ward（结界）构筑
- 这是 hybrid（混合池）构筑

同时还会保留：

- `hitMitigationModel`（承伤模型）
- `avoidanceModel`（规避模型）
- `sustainModel`（续航模型）
- `confidence`（置信度）

这部分主要用于：

- 人工解释为什么某个特殊构筑分数低；
- 后续 Phase 4/5 接 semantic graph（语义图谱）时，补 archetype-specific reasoning（流派专属推理）。

---

## 18. scoreReview（低分复审）

当前对外部成熟样本，Judge 还有一层自检：

如果样本 `pass = true`，但出现以下任一情况：

- `aggregate < 0.5`
- `offense < 0.5`
- `defense < 0.5`
- `recovery < 0.5`
- `mobility < 0.5`

就会标记：

- `scoreReviewNeeded = true`

然后 `sample_audit.py` 会尝试解释：

- 这是 limited evidence 导致的低分；
- 这是特殊防御模型导致的低分；
- 这是确实偏弱；
- 或这是 Judge 仍未收口的 modelability gap。

最终会归类到四类之一：

- `judge_pass_and_scores_explained`
- `real_legality_failure`
- `source_data_problem`
- `judge_unsolved_modelability_gap`

---

## 19. poe.ninja 采集链路的特殊兼容

当前 `poe.ninja` 采集不是直接假设页面结构永远固定，而是做了多重提取：

1. 浏览器渲染角色页。
2. 从渲染后的 HTML 查找：
   - `aria-label="Import code for Path of Building"`
   - 对应 `value="..."`
3. 若第一种失败，再 fallback 到 `<input ...>` 标签级别提取。
4. 只做 transient import（瞬时导入），不把 raw PoB code（原始 PoB 码）持久化进仓库文档。

对应代码：

- [server/knowledge/mature_ninja_payload.py](/E:/poe-bd-creator/server/knowledge/mature_ninja_payload.py)
- [scripts/run_judge_ninja_samples.py](/E:/poe-bd-creator/scripts/run_judge_ninja_samples.py)

---

## 20. 当前已知边界

Judge 现在已经可以稳定处理很多现实问题，但仍有明确边界：

### 已经处理到位的

- poe.ninja 导入后主技能停在 buff / banner / curse
- summon（召唤）构筑的数量乘区基础修正
- low-life / reservation（保留）生命主池问题
- CI 混沌免疫
- MoM / EB + MoM 主池诊断
- 外部样本的点数漂移 / 状态漂移兼容

### 仍然只做 limited evidence 的

- `FullDPS` rollup
- 多投射物 overlap / shotgun 真值
- 复杂 minion 配置完整真值
- 部分特殊 trigger 链
- 可疑导入态下的极端防御读数

### 刻意不做的

- 自己新写一套完整数值引擎
- 用硬编码技能白名单代替 PoB 真实 readback
- 把有限证据包装成强 reward

---

## 21. 读这份文档时的一个关键心法

Judge 当前不是在追求一句话回答：

> “这个 BD 到底是不是 0.93 分？”

而是在追求一组更靠谱的回答：

- 这个 BD 合不合法？
- 这个分数来自哪一类证据？
- 哪些部分是 PoB 强证据？
- 哪些部分只是近似读数？
- 哪些地方是导入态异常，不应该学成坏样本？
- 哪些地方要留给后续图谱阶段去做语义补完？

这也是当前 Phase 1 真正完成的价值所在。
