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

- pass/fail 和 score；
- hard failures 和 warnings；
- PoB-computed metrics；
- resistance、Spirit、attribute、support、weapon、passive-budget checks；
- modelability status；
- evidence tags；
- 不包含 copied reference build material。

## BuildComparison

Candidate vs reference 或 candidate vs prior round。

必要概念：

- compared snapshot ids；
- metric deltas；
- legal-state deltas；
- reference placement；
- structured gaps；
- winner：`candidate`、`reference`、`prior`、`unknown`；
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
