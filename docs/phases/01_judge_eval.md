# Phase 1 - 确定性 Judge 与 Modelability Matrix

## 阶段状态

已完成。当前 Phase 1 以 `judge_phase1_v7` / `judge_v6_evidence_separated` 作为内部 Judge
基线：合法性仍由 hard checks 和 PoB readback 兜底，质量评分输出 evidence-aware score
vector，并明确区分 strong evidence、limited evidence、source-data problem 和
unsolved modelability gap。

## 目标

先证明现有 Headless PathOfBuilding-PoE2 sandbox 和确定性规则可以判断 BD 的质量、合法
性与 modelability，再让后续生成或学习依赖这些分数。

这里的“判断质量”有一个必须明确的语义边界：Phase 1 的 Judge 不是要为所有机制给出绝对
正确的真数值，而是要把样本分成三层：

- 有强证据、可直接比较的数值；
- 只有有限 PoB 面板证据、但仍可诊断或 limited selection 的数值；
- 当前 Headless PoB/bridge 无法稳定表达，必须标为 `unverified` / `unmodelled` /
  `judge_unsolved_modelability_gap` 的机制簇。

只要 Judge 能稳定识别这些边界，并阻止有限证据污染强 reward 和记忆，它就符合 Phase 1
的核心职责。

## 依赖

- Phase 0 文档结构。
- 现有 `server/compute/engine.py` 和 `pob/pob_headless.lua`。
- 现有 import/export 和 compute tests。

## 工作项

- 在代码中定义 `BuildSnapshot`、`BuildEvaluation` 和 `BuildComparison`。
- 建立固定 judge fixture set：
  - legal strong build；
  - legal weak build；
  - uncapped resistance build；
  - attribute-insufficient build；
  - low DPS build；
  - high DPS / low defense build；
  - passive over-budget build；
  - attack skill with no weapon；
  - incompatible weapon / skill tag build；
  - Spirit-insufficient build；
  - unmodelled meta-trigger build；
  - single-state 和 dual-state markers。
- 产出 PoE2 modelability matrix：
  - single-state DPS；
  - dual weapon state；
  - support socket / skill socket behavior；
  - Spirit reservation；
  - minion reservation；
  - meta-trigger；
  - projectile overlap caveats；
  - unsupported mechanics。
- 基于 PoB 输出和 hard legality checks 建立 deterministic score vector，而不是只建立
  单一总分：
  - offense；
  - defense；
  - recovery；
  - mobility；
  - 展示型 scenario fit（mapping、bossing、hybrid）。
- Judge 输出必须从单一分数转为 evidence-aware 合同：
  - legality / validity；
  - raw score vector；
  - metric provenance；
  - evidence / confidence tier；
  - reward eligibility / reward strength。
- Judge v3 必须区分 hard floor 和 quality target：
  - hard floor 只用于判断低到不可运行的 failure；
  - quality floor / target 用于成熟 BD 质量评分，不能让合法 BD 直接失败，也不能把高于
    hard floor 的可计算 BD 直接归零；
  - score scale 为 `0_to_1`。
- 如果需要 report-friendly aggregate score，必须声明权重 profile；后续 reward memory
  不能只依赖单一总分。
- 对 `limited evidence` 的 raw score，不允许直接当作“构筑真强度”进入 strong reward：
  - `isolated_full_dps_rollup`、`minion_pob_output`、fallback defense/recovery、dual-state
    limited evidence 等，必须以 confidence tier 约束 reward；
  - 不要求在 Phase 1 内解决所有技能/机制的绝对数值真值；
  - 对未解决机制，允许保留非零诊断分，但必须用 caveat 与 reward-strength 表达“不够自
    信”。
- 定义 hard-failure short-circuit policy：
  - 触发 physical-invalid failure 时，相关评分维度必须熔断，不能让非法 BD 用局部面板数
    据参与赢家判断或 reward；
  - `attribute_requirement_unmet`、`incompatible_weapon_skill_tags`、
    `attack_skill_without_weapon`、`passive_budget_exceeded` 和 `spirit_budget_exceeded`
    至少属于熔断 failure；
  - 熔断后的 offense、defense、recovery、mobility 等下游分数必须标记为 blocked，而不是仅
    低分；
  - report 可以保留 raw PoB metrics 作为诊断材料，但不能把它们用于 reward。
- 为 dual-state build 明确定义 active-state evaluation policy：
  - state A / state B 分别保存 PoB metrics、hard checks 和 caveats；
  - mapping/clear 可指定一个 active state；
  - bossing/single-target 可指定另一个 active state；
  - 不支持双态计算时返回 modelability caveat，不把最高状态 DPS 当作整体质量。
- 为 BuildComparison 定义 comparability contract：
  - 只有当两个 snapshot 在目标场景和 active-state policy 下 modelability 可比较时，才
    可以返回 candidate/reference/prior winner；
  - 一方核心 `modelability.status=not_modelable` 或关键 metric provenance 为 unmodelled 时，比较结果
    必须是 incomparable/unknown，并带 caveat；
  - 不允许把“无法建模导致的低表面数值”解释为机制或 build archetype 本身较弱；
  - 后续 reward memory 只能消费 comparable comparison。
- 明确 Phase 边界：
  - Phase 1 只建立 legality / score / modelability / confidence 基线；
  - 复杂技能与 archetype 的“结构正确性”“语义契合度”“参考族 placement”由 Phase 4
    semantic graph、Phase 5 生成约束和后续跨阶段 reward memory 逐步接管；
  - Phase 1 不通过发明新的数值引擎来替代这些后续阶段。
- 为每次 benchmark report 保存 reproducibility context：
  - fixture set id；
  - evaluator version；
  - PoB version/commit；
  - game patch；
  - passive tree version；
  - metric provenance（PoB-computed、hard-check-derived、unavailable、unmodelled）。
- 建立四层结果 taxonomy：
  - legality：确定性职业、插槽、武器、属性、预算、Spirit 和装备非法；
  - severe playability：强证据 DPS 和灾难性防御短板；
  - quality warnings：剧情阶段混沌抗与 offense/Max Hit 质量目标；
  - modelability：PoB/Judge 当前是否能可靠计算；
  - 新生成的 80 级及以上候选要求火/冰/电各 60%、非 CI 混沌抗 30%；共享 preflight 先拦截且
    不消耗 Judge attempt，79 级及以下和可信第三方参考只作 diagnostic；
  - attribute_requirement_unmet；
  - passive_budget_exceeded；
  - attack_skill_without_weapon；
  - incompatible_weapon_skill_tags；
  - spirit_budget_exceeded；
  - pob_compute_failed；
  - trigger_rate_unmodelled_caveat。
- 生成 baseline benchmark report，供后续 Phase 对比。

## 当前实现

- 新增内部模块 `server/judge/`，暂不暴露 MCP tool：
  - `models.py`：evaluator version、metric keys、failure code / caveat 常量；
  - `rules.py`：class/ascendancy、support/socket v1、physical-invalid blocker；
  - `scoring.py`：`judge_v6_evidence_separated`，包含 hard floor / quality target 分离、阶段感知权重、
    hard-floor 到 target 的对数连续评分、动态可用主资源池 recovery、异构 Max Hit、CI
    混沌免疫、EHP 物理短板补偿、终局抗性 readiness gate、offense evidence provenance
    和扁平 aggregate；
  - `modelability.py`：main socket group meta-trigger 不可数值验证、partial modelability、白名单 caveat；
  - `comparison.py`：`selectionWinner` 与 `rewardWinner` 分离，并输出 `rewardStrength`；
  - `evaluator.py`：从 active PoB build 生成 `BuildEvaluation`，包含 `defenseModel` 诊断层；
  - `runner.py`：engine factory/import/evaluation safe-call、timeout、EOF/crash recovery；
  - `fixtures.py` / `benchmark.py`：synthetic baseline report。
- `pob/pob_headless.lua` 的 readback 增加：
  - `load_build_xml()` 返回 `treeVersion` / `latestTreeVersion`；
  - `get_build()` 返回 `treeVersion` / `latestTreeVersion`；
  - `mainSkillGroup` 中每个 gem 返回 `isSupport`、`isActive`、`supportKnown`。
  - `get_build()` 返回 `judgeSelectedSkill`，用于处理 poe.ninja / PoB 导入中“当前主技能
    只是最后点击的 buff/战旗/辅助状态”的情况；
  - `judgeSelectedSkill` 会扫描 socket group，临时隔离每组 `includeInFullDPS` 后选择最高
    可计算输出，并返回 skill name、group index、source metric、projectile count、技能组来源、
    场景限制和 caveats；该字段只是本次 offense 计算组件，不表示整个 BD 只有一个主技能；
  - PoB 内部生成的击杀爆炸保留为 `judgeSupplementalSkills` 条件伤害组件，标记
    `requires_kill`，不冒充 Boss 持续输出，也不执行普通宝石插槽合法性检查；
  - 当 `judgeSelectedSkill` 的输出来自 `FullDPS` 时，报告必须把它标记为 socket-group rollup，
    不能把它误读为单个 active skill 的精确一段伤害；
  - `judgeSelectedSkill` 返回 `activeSkillCount`、`rawDps` 和 `effectiveDps`。`FullDPS`
    路径不再额外乘数量；非 `FullDPS` 的 PoB minion output 会按当前 active skill count
    计算 `effectiveDps`，并追加 limited reward caveat；
  - `judgeSelectedSkill` 和 `mainSkillWeaponCheck` 暴露 PoB active skill 的 weapon requirements、
    当前装备武器类型和 PoB `disableReason`；`disableReason` 是 `incompatible_weapon_skill_tags`
    的权威来源，不能在 Python 里按技能名硬编码武器表；
  - passive budget readback 会计入 PoB 输出的 `ExtraPoints`、`WeaponSetPassivePoints` 和
    `PassivePointsToWeaponSetPoints`。
- `evaluator.py` 对适用普通插槽规则的 selected skill group 做 socket、modelability 和 weapon
  check；条件性内部合成效果与插槽合法性解耦；
  即使 selected damage skill 的 DPS 为 0，只要 PoB 标记它是 damage skill 或带有 weaponCheck，
  也必须执行合法性检查，不能把“武器非法导致的 0 DPS”误判成普通低输出。
- `BuildEvaluation` 增加 `legality` 诊断：
  - `passiveBudget` 展示 used、available、over、league extra applied；
  - `weaponSetBudget` 展示每个 weapon set 的 used、available 和 overMax；
  - 超预算仍是 physical-invalid hard failure，不因诊断存在而降级。
- `BuildEvaluation.scoreBreakdown.offense` 增加 evidence contract：
  - `direct_pob_dps` 默认 strong；
  - `isolated_full_dps_rollup` 默认 limited；
  - `minion_pob_output` 默认 limited；
  - `unknown_or_unavailable` 表示无可用 DPS；
  - limited offense evidence 仍可用于单个 BD selection / 诊断评分，但不能产生 strong reward。
- v6 将正伤害观察值、阶段地板与实战交付证据拆开：offense breakdown 输出
  `metricStatus`、`floorStatus`、`deliveryEvidenceStatus`、`observedValue`、
  `floorProgress` 和 confidence factor。`floorProgress` 只作诊断，不产生额外 credit；strong
  direct evidence 低于地板时 delivery 仍为 established，但继续作为 playability failure 和 0 分；
  limited evidence 仍不能产生 strong reward。
- `judgeSelectedSkill` 同时返回 direct/full diagnostics；二者在容差内相等时优先 direct，只有
  FullDPS 实质增加组件或 direct 为 0 时才采用 rollup。合法单主动技能组不再无条件附加
  `support_conflict_unverified_caveat`，但 `supportKnown` 仍不宣称 support applicability 已验证。
- campaign / maps-entry scope 由 `levelBand` 表达，不再附加缺陷式 caveat，也不设置 blanket
  reward limit；阶段型强证据只能在相同阶段/场景合同内比较，不同 `levelBand` 返回
  `level_band_mismatch`，不产生 winner。
- Judge 的 aggregate / scenario fit 语义已经转为 confidence-aware：
  - raw 分数可以展示，但是否可比较、是否可用于 reward，取决于 evidence / caveat；
  - `judge_unsolved_modelability_gap` 不再被视为 Judge 失败，而是 Phase 1 成功识别到的“当前
   不应装作算准”的机制簇；
  - 对 `trusted_reference` 外部成熟样本，抗性质量警示、attribute mismatch、
    multi-active group 等可在 confidence contract 下保留强警示或 limited reward，而不必
    一律当作 archetype 负样本。
- `BuildEvaluation.defenseModel` 只作为诊断层：
  - `poolModel` 区分 `life`、`low_life`、`es`、`ci`、`mom`、`eb_mom_mana`、`ward`、
    `hybrid`、`unknown`；
  - 保留物理 Max Hit 的 `TotalEHP / 40000`、最高 1.5x 补偿；
  - 补偿只用于物理分，不用于元素/混沌，也不把 avoidance 自动当作可承受一击。
- 特殊防御模型的 Judge 语义：
  - 对 `avoidance_evasion_hybrid`、`mom_mana_primary_pool_caveat`、CI / ES / hybrid 等
    PoB 表达边界，Judge 优先建立“是否越过不可玩底线”的启发式兜底；
  - 防御端允许展示低分或 caveat，但不应在证据不足时伪装成“绝对客观的 archetype 真强弱”；
  - 完整的结构语义验证和跨 archetype 奖励，属于后续图谱 / semantic placement 阶段。
- `BuildComparison` 增加 reward 防污染合同：
  - full modelability + strong evidence 才允许 `rewardStrength=strong` 和明确 `rewardWinner`；
  - limited evidence 可以给出 `selectionWinner`，但 `rewardWinner=unknown`，
    `rewardStrength=limited`；
  - physical-invalid、core unmodelled 和 compute failed 均为 `rewardStrength=none`。
- 新增 `scripts/run_judge_user_samples.py --source-file <local-file>`：
  - 只做 transient import；
  - 支持单个 XML 整文件、JSON/JSONL/`samples` manifest、显式 `---POB-SAMPLE---` 分隔符和逐行 PoB code；
  - 输出 hash、摘要、`judgeSelectedSkill`、score vector、score breakdown、quality band、
    failures、modelability、caveats；
  - 额外输出 `regressionMatrix`，只固定 source hash、摘要、offense provenance、
    defenseModel、failure/caveat、rewardEligibility / rewardStrength 等脱敏字段，不固定精确
    aggregate 分数；
  - compute/import 失败只输出 `errorKind` 和 `pob_compute_failed`，不输出底层 error detail；
  - 不回显 PoB code、raw XML、完整装备、完整天赋或完整 gem links。
- Synthetic baseline 写到 `paths.user_data_dir()/runtime/judge_baseline_phase1.json`，不进入仓库。

## 验收

- 显而易见的 strong/weak fixture comparison 能选出正确赢家。
- Illegal fixtures 返回具体 failure codes。
- Attribute shortfalls 和 weapon/skill tag conflicts 能被检测。
- 终局样本缺失 ascendancy 是 hard failure；非终局样本缺失 ascendancy 追加
  `missing_ascendancy_non_endgame_caveat`，不作为 physical-invalid。
- Spirit shortfalls 能被检测。
- Unmodelled mechanics 变成 caveats，不产生虚假 reward。
- Score vector 每个维度可解释；aggregate score 如存在，必须带权重 profile。
- Recovery 使用 `LifeUnreserved` / `EnergyShield` 作为可用主资源池，不能因 Total Life
  错误惩罚 low-life / life reservation BD。
- MoM/EB 类构筑在包含 `Mind Over Matter` 且 Mana 为主要承伤资源时，recovery 主池允许使用
  `ManaUnreserved`，并追加 `mom_mana_primary_pool_caveat`。
- CI 构筑不能因 `ChaosMaximumHitTaken` 为 nil、0 或特殊值被误判为混沌防御短板。
- PoB strong-evidence 输出低于 hard floor 时进入 playability failure；limited/unknown evidence
  不得触发 DPS 硬失败。低于 quality floor 时进入 `qualityWarnings`，不能等同非法或 0 DPS。
- 对本系统生成的候选，如果 offense delivery 不是 established，追加
  `offense_delivery_not_established` 并把综合分限制在 `prototype_only`；候选可以继续由 Agent
  修正或作为建模缺口研究，但不能保存为最终可交付 PoB。该限制不应用于成熟参考样本的事实判断。
- `TotalDPS` 按 PoB 定义解释为 Hit DPS，不是单次命中。多投射物 / 多段命中优先读取 PoB 的
  `CombinedDPS` / `FullDPS` 组件；无法证明重叠时使用 `projectile_overlap_unverified_caveat`，
  不盲乘 projectile count，也不把 Hit DPS 统称为下界。
- 缺失关键 PoB 指标或只靠 fallback 估分时，允许 selection 使用该 evaluation，但 reward 必须
  降为 `limited`，避免把证据不足写成强学习信号。
- 对 `FullDPS` rollup、召唤 / 指令复合输出、触发链、多 active rotation、规避型防御和条
  件 sustain 等机制簇，如果 Judge 当前只能给 limited evidence，就允许把它们稳定归为
  `judge_unsolved_modelability_gap`；这属于 Phase 1 成功识别盲区，而不是失败。
- 使用 weapon set passive points 的样本在 Phase 1 中追加 `dual_weapon_state_limited_caveat`，
  selection 可用，但 reward 降为 `limited`；Phase 1 仍不声称已完成 State_A / State_B 的分别
  场景评分。
- 熔断 failure 会阻断下游评分和 reward，而不是产生一个看似可比较的低分或高分。
- Dual-state fixture 不会被错误压缩成单状态最高 DPS。
- Winner 只能在可比较的 modelability 范围内给出；遇到 blocker 时返回 incomparable/
  unknown 和 caveat。
- Benchmark report 带完整 reproducibility context。
- Benchmark output 可重复。
- 真实样本验收报告需要由用户审阅并认可；未完成该步骤前 Phase 1 不能标记完成。

## 第一轮真实样本回归记录

已使用 7 个用户提供的 poe.ninja 100 级榜单 PoB code 做 transient 验收，不持久化 raw code、
raw XML、完整装备、完整天赋或完整 gem links。

关键观察：

- `judgeSelectedSkill` 成功修正 Dread Banner / buff 类当前主技能导致的 0 DPS 误读，并能选择
  Molten Crash / Ember Fusillade 等可计算输出技能。
- `FullDPS` 在扫描时已按 socket group 隔离，避免把全局 FullDPS 聚合错绑到某个技能。
- CI + Eldritch Battery + Mind Over Matter 样本的 `EnergyShield=0` 不是读取错误；ES 被 EB 转
  成 Mana，Judge 已用 `ManaUnreserved` 作为 recovery 主池并输出 caveat。
- 当前公开证据只支持当前联赛 1 个额外全服 passive point；Sample 3 与 Sample 6 仍分别存在
  超出该范围的 passive / weapon-set budget。Judge 保持 hard failure，并在 `legality` 中暴露
  over 数值，后续需继续核对 poe.ninja 导出、树版本和赛季额外点来源。
- Twister 榜首样本在当前 PoB sandbox 中隔离可计算输出约 18-20 万 DPS，低于 30 万 quality
  floor；Judge 现在给非零低分并在 `qualityWarnings` 标记 offense 质量目标未达到，但这说明 offense 标准和技能
  modelability 仍需更多样本校准，不能把当前分数视作最终客观真理。

## 验证

实现后先跑 focused judge tests：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_judge_rules.py tests/test_judge_scoring.py tests/test_judge_evaluator.py tests/test_judge_modelability.py tests/test_judge_runner.py tests/test_judge_comparison.py tests/test_judge_benchmark.py tests/test_judge_user_samples.py -q
```

Bridge readback focused tests：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_compute.py::test_import_reproduces_stats tests/test_compute.py::test_paste_tolerates_missing_count -q
```

全局回归：

```powershell
.\scripts\verify.ps1 quick
.\scripts\verify.ps1 compute
git diff --check
```

注意：`compute` 会运行完整 `tests/test_compute.py`，在 Windows 本地经常超过 15 分钟。
执行该命令时外层命令超时必须至少给到 30 分钟；如果只给 10 分钟导致超时，应记录为外
层预算不足，而不是直接判定 compute 失败。脚本内部已为 compute profile 使用 30 分钟
pytest 单测试超时。

真实样本人工验收：

```powershell
.\.tools\uv\uv.exe run python scripts/run_judge_user_samples.py --source-file <你提供的本地pob-code文件>
```
