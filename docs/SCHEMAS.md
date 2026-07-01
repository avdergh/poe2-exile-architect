# PoE2 BD Creator 数据结构合同

最后更新：2026-06-29

本文档在产品层定义核心 artifact contracts。精确字段校验应放在代码和测试里。

## BuildBrief

用户/请求侧的生成约束。

必要概念：

- goal 和目标玩法；
- lifecycle stage；
- economy mode：`trade`、`ssf`、`league_start`、`unknown`；
- budget model：`low`、`medium`、`high`、`minmax`、`user_defined`；
- price source status：`fresh`、`stale`、`unavailable`；
- target scene：`mapping`、`bossing`、`hybrid`、`unknown`；
- preferred/required/forbidden skills、classes、mechanics、items；
- weapon state mode：`single_state`、`dual_state_requested`；
- leveling 和官方 `.build` export requirements。

## BuildPlan

Architect Agent 在 deterministic completion 前提出的方案。

必要概念：

- archetype 和 reusable principle；
- class 和 ascendancy；
- main skill 和 support intent；
- passive anchors，而不是完整 passive paths；
- gear roles，而不是复制来的完整装备表；
- defense layers；
- sustain plan；
- Spirit budget 和 reservation plan；
- state A / state B assumptions；
- leveling milestones；
- modelability caveats。

## BuildSnapshot

用于评估的具体候选状态。

必要概念：

- snapshot id；
- PoB XML/code hash 或本地 opaque reference；
- 可选官方 `.build` draft reference；
- class、ascendancy、level、main skill；
- passive point usage；
- weapon state mode；
- generated/loaded source；
- freshness claims。

## BuildEvaluation

对单个 snapshot 的 deterministic judge 输出。

必要概念：

- pass/fail；
- score scale：当前 Judge v2 使用 `0_to_1`；
- score vector：当前最小实现包含 offense、defense、recovery、mobility；physical-invalid 时
  这些维度必须标记 blocked；
- score breakdown：每个维度应说明 raw value、hard floor、quality floor、target、
  source metric 和 caveats；
- judge selected skill：当 PoB/poe.ninja 导入的当前主技能只是 buff、战旗或辅助状态时，
  Judge 可以使用 `judgeSelectedSkill` 暴露实际用于 offense 评分的技能摘要；只能包含技能名、
  group index、source metric、projectile count 和 caveats，不能输出完整 gem/support links；
  如果 source metric 是 `FullDPS`，必须标记为 socket-group rollup，而不是单技能精确 DPS；
- offense evidence：`scoreBreakdown.offense` 必须包含 `provenance` 与 `evidenceLevel`。
  `direct_pob_dps` 可以是 strong evidence；`isolated_full_dps_rollup` 和
  `minion_pob_output` 默认只能是 limited evidence；无可用 DPS 时使用
  `unknown_or_unavailable` / `none`。同时保留 `sourceMetricDetail`、`skillName`、
  `skillGroupIndex`、`isMinion`、`activeSkillCount`、`activeMinionLimit`、`rawDps`、
  `effectiveDps` 和 caveats，避免把 PoB 原始读数、数量修正和最终评分输入混在一起；
- weapon check：`judgeSelectedSkill` 和主技能摘要可以包含 `weaponCheck`，仅暴露技能名、
  PoB weapon requirements、当前装备武器类型、兼容状态和 PoB `disableReason`。当
  `disableReason` 显示技能被当前武器禁用时，必须产生 `incompatible_weapon_skill_tags`；
  不允许用 Python 技能名表替代 PoB 兼容性判断；
- scenario fit：当前作为展示型 mapping/bossing/hybrid fit，不参与 aggregate；
- aggregate score：必须包含 weight profile；当前 `judge_v2_reality_calibrated` 使用 offense
  0.40、defense 0.40、recovery 0.15、mobility 0.05；
- quality band：`invalid`、`barely_playable`、`entry_endgame`、`solid`、`strong`；
- hard failures 和 warnings；
- legality diagnostics：至少包含 `passiveBudget` 和 `weaponSetBudget` 的 used、available、
  over 信息；诊断用于解释 hard failure，不能把超预算自动降级为合法；
- PoB-computed metrics；
- resistance、Spirit、attribute、support、weapon、weapon/skill tag、passive-budget checks；
- failure codes：uncapped_resistance、attribute_requirement_unmet、passive_budget_exceeded、
  attack_skill_without_weapon、incompatible_weapon_skill_tags、spirit_budget_exceeded、
  invalid_class_ascendancy_pairing、invalid_socket_setup、support_limit_exceeded、
  duplicate_support_gem、invalid_support_gem、pob_compute_failed、unmodelled_mechanic；
- short-circuit state：physical-invalid failure 必须标记被 blocked 的 score dimensions；
- reward eligibility：熔断 evaluation 不能产生 positive reward；
- reward strength：`BuildEvaluation` / `BuildComparison` 使用 `rewardStrength` 区分
  `strong`、`limited` 和 `none`。只有 strong 才能被后续 Phase 8 作为强 reward memory
  消费；limited 只允许作为观察或弱信号；
- 非终局空升华：campaign / maps-entry 样本缺失 ascendancy 可以追加
  `missing_ascendancy_non_endgame_caveat` 并继续评估；endgame 样本缺失 ascendancy 仍是
  `invalid_class_ascendancy_pairing`；
- recovery 主池：生命侧使用 `LifeUnreserved`，不是 `Life`；`Life`、`LifeReserved` 和
  `LifeUnreservedPercent` 仅用于诊断和 fallback；
- CI：`Chaos Inoculation` 以 build keystone readback 为权威；CI 下 chaos score 直接按混沌
  免疫处理，不使用 `ChaosMaximumHitTaken` 的 nil/0/超大值反推；
- source hash：真实样本验收只输出 hash，不输出 raw source；
- reproducibility：至少包含 evaluator version、tree version、latest tree version；版本不一致时
  必须追加 `version_mismatch_caveat`；
- state evaluations：single-state 时一个 active state，dual-state 时分别记录 state A/state B
  的 metrics、hard checks 和 caveats；
- defense model：`BuildEvaluation.defenseModel` 是诊断层，不直接替代 defense score。
  `poolModel` 至少覆盖 `life`、`low_life`、`es`、`ci`、`mom`、`eb_mom_mana`、`ward`、
  `hybrid`、`unknown`；`hitMitigationModel`、`avoidanceModel` 和 `sustainModel` 只能解释
  PoB 已读出的防御层，不得把高闪避、高格挡或高 EHP 自动洗白为可承受一击；
- modelability status；
- limited evidence：缺少关键 PoB 指标、primary pool 不可得或 partial modelability 时，evaluation
  可以用于 selection，但 `rewardEligible` 必须降为 `limited`，不能作为 strong reward 写入学习；
- limited offense evidence：`lower_bound_dps_caveat`、`minion_dps_unverified_caveat`、
  `minion_count_multiplier_caveat`、`full_dps_rollup_caveat` 等 caveat 必须限制 reward，
  但不应阻止单个 BD 的 selection / 诊断评分；
- dual-state limited evidence：Phase 1 如果检测到 weapon set passive usage，但尚未分别计算
  State_A / State_B，必须追加 `dual_weapon_state_limited_caveat` 并将 reward 降为 `limited`；
- compute failure：`pob_compute_failed` 可以输出 sanitized `errorKind`，不能输出 raw import
  text、raw XML、完整异常 detail 或路径化敏感材料；
- evidence tags；
- 不包含 copied reference build material。

## BuildComparison

Candidate vs reference 或 candidate vs prior round。

必要概念：

- compared snapshot ids；
- metric deltas 和 score-vector deltas；
- legal-state deltas；
- reference placement；
- structured gaps；
- selection winner：`candidate`、`reference`、`prior`、`tie`、`unknown`；
- reward winner：`candidate`、`reference`、`prior`、`tie`、`unknown`；
- scenario / active-state comparison policy；
- comparability/status：`comparable`、`partial_modelability`、`candidate_invalid`、
  `reference_invalid`、`both_invalid`、`incomparable`；
- incomparable reason：例如 unmodelled_mechanic、missing_metric、different_active_state_policy；
- reward eligibility：full comparable 才能进入 strong reward；partial modelability 只能进入
  limited reward；非法或 core-unmodelled comparison 不进入 reward memory；
- limited evidence comparison：如果任一方只有 limited evidence，可以给出
  `selectionWinner`，但 `rewardWinner` 必须是 `unknown`，`rewardStrength=limited`，防止把
  FullDPS rollup、召唤物数量近似、投射物下界或关键指标缺失写成强学习信号；
- modelability limitations。

## ResearchPacket

外部 Researcher Agent 输入。

必要概念：

- safe metadata；
- quarantine-only raw context；
- 可用时包含 judge output；
- physical graph context；
- freshness evidence；
- copy-safety rules；
- requested clean output schema。

## CleanFragment

可持久化的 non-copyable research finding。

必要概念：

- fragment type；
- reusable principle；
- source case refs；
- confidence；
- copyability risk；
- lifecycle stages；
- modelability；
- verification tasks。

## GraphNode

Physical 或 semantic knowledge node。

必要概念：

- node id 和 stable key；
- node type；
- display name 和 aliases；
- source 和 source file；
- game patch、passive tree version、PoB version/commit；
- status：`valid`、`deprecated`、`nerfed`、`unknown`、`needs_revalidation`；
- confidence；
- 适用时包含 official IDs。

## GraphEdge

已存在节点之间的关系。

必要概念：

- edge id；
- source node id；
- target node id；
- edge type；
- evidence refs；
- game patch、passive tree version、PoB version/commit；
- status；
- confidence；
- weight；
- modelability。

Semantic edges 必须在两个 endpoint nodes 都能 resolve 后才能创建。

## RewardEvent

来自生成、比较、修复或失败的学习信号。

必要概念：

- build brief id；
- snapshot ids；
- used graph edges 和 techniques；
- before/after scores；
- fixed gaps 和 failed gaps；
- rollback count；
- final outcome；
- patch/version context；
- modelability caveats。

## FailurePattern

可复用的死胡同或反复修复失败描述。

必要概念：

- trigger conditions；
- failed strategy；
- affected lifecycle stage；
- evidence refs；
- recommended avoidance or alternative；
- confidence 和 promotion status。

## BuildPlannerExport

官方 `.build` artifact contract。

必要概念：

- 带 `level_interval` 的 passives；
- 带 `level_interval` 的 skills 和 support skills；
- inventory slot hints；
- 支持时包含 weapon set；
- resolved GGG IDs；
- unsupported-field caveats。
