# PoE2 BD Creator 项目规格

Last updated: 2026-06-27

本文档是项目的本地接续规格，供 Codex/Claude Code 在上下文压缩或切换会话后快速恢复真实状态。
它只记录已经完成的能力、当前真实方向、明确待办和必须遵守的边界；不要把愿望写成已完成。

配套架构文档：`docs/PROJECT_ARCHITECTURE.md`。

## 项目总目标

构建一个可靠的 Path of Exile 2 BD Creator。最终形态可以是独立 agent，也可以是依托
Codex / Claude Code / Claude Desktop MCP 的开源工具。

目标用户可以是完全不懂 BD 的新手。用户只说“给我一个强力 BD”时，系统也应该能：

- 确认当前赛季、patch、天赋树和 PoB 数据新鲜度；
- 研究当前热门成熟 BD、论坛/攻略、pobb.in/PoB 样本和本地 corpus；
- 输出“开荒 → 转型 → 终局”的生命周期路线，而不是只给一个毕业形态；
- 解释核心机制、为什么强、为什么不能直接开荒、什么时候该转型；
- 用 PoB2/headless engine 验证能验证的数值；
- 在机制无法建模时明确 caveat；
- 根据用户反馈持续修正；
- 把可复用、被验证、不过期的技巧沉淀为知识，但不能把单次反馈或 LLM 猜测直接写成真理。

## 产品设计核心判断

LLM 不是外围补丁，而是本产品的核心研究与创造主体。

LLM 负责：

- 多视角研究问题拆解；
- 从热门 BD、攻略、论坛、pobb.in/PoB 摘要和用户反馈中提取机制假设；
- 归纳技巧、解释原理、比较差异；
- 生成候选生命周期路线；
- 发现 creator 输出与 mature evidence 的差距；
- 反思失败原因并提出待验证技巧。

确定性代码、SQLite、freshness gate、sanitizer 和 PoB engine 负责：

- 数据边界和安全过滤；
- patch/tree/league/provenance 记录；
- copyability 防护；
- 可复现的工程回归；
- 数值计算与验证；
- 防止 LLM 把未经验证的猜测晋升为 durable memory。

## 不可协商边界

- 新鲜度优先：涉及当前 meta、热门 BD、patch、赛季、天赋树、PoB 数据时，必须先确认最新数据。
- PoB/engine-computed 数字是 DPS/EHP/抗性/数值判断的权威来源。
- poe.ninja、论坛、pobb.in、攻略和 reference builds 是研究/校准来源，不是复制模板。
- 不能泄漏或保存可复刻真实 BD 的 raw 内容，例如 PoB code、完整装备表、完整天赋树、完整 node list、完整宝石连接、攻略全文。
- 成熟 BD 学习必须保留 creator/evaluator/holdout 边界，避免训练上下文偷看评测答案。
- 用户反馈默认是 local episodic memory；只有多来源验证、engine delta 或明确人工审核后，才可能晋升为 durable technique。
- LLM 输出的技巧候选默认低信任；不能跳过 evidence、patch/tree、PoB modelability、promotion 状态和 copyability 边界。
- 机制不能被 engine 建模时，必须显式说明 caveat。

## 已完成能力概览

### Foundation / freshness

- 本地 MCP/server tool surface，可供 LLM 调用 PoE2 build 工具。
- 本地 corpus 查询：技能、辅助、暗金、词缀、机制、升华、天赋等。
- PoB2 headless runtime 集成。
- 本地 0.5.4 validated runtime certification。
- Freshness gate：GGG patch/tree、PoB compatibility、poe.ninja snapshot evidence。
- 验证分层：`quick`、`noncompute`、`compute`、`full`，避免每个小改动都跑昂贵 compute/full。

### Build optimization foundation

- engine-backed build state 与 build evaluation。
- build import/export、stats、defenses、gear、skill、config、passive 操作。
- support/passive/gear/jewel/unique/scaffold/upgrade 等 optimizer 和 helper。
- reference build browsing / benchmarking，仅用于 calibration，不作为复制源。
- stage repair actions，用于根据阶段问题给出修正建议。

### Phase 3 lifecycle research

已实现生命周期 BD 骨架：

- Phase 3A：生命周期 route scaffold、classification、stages、transition gates、memory schema。
- Phase 3B：非复制 reference cohort evidence 与 live-meta context。
- Phase 3C：transition readiness evaluator。
- Phase 3D：stage verification budgets。
- Phase 3E：stage verification executor。
- Phase 3F：source/guide text evidence extraction。
- Phase 3G：source-derived transition gates。
- Phase 3H：stage-aware repair actions。
- Phase 3I：lifecycle route quality gate。
- Phase 3J：safe meta archetype trend adapter。
- Phase 3K：feedback-informed lifecycle memory context。
- Phase 3L：lifecycle route evaluation harness。
- Phase 3M：engine-computed endgame stage numeric range evaluation。

### Phase 3N.1 mature build learning store

已实现并审查：

- SQLite mature learning store schema。
- user-data DB path。
- `source_groups`、`source_snapshots`、`mature_build_cases`、`technique_candidates`、
  `candidate_evidence`、`technique_edges` 表。
- seed fixture manifest。
- deterministic sanitized fixture import。
- allowlist sanitizer。
- copyability / reconstruction guard。
- visibility / split / knowledge_scope 边界。
- seed fixture 禁止 `user_feedback_local` 进入 global seed knowledge。
- expiration/freshness metadata 目前只记录，不主动降权或删除。

局部文档：

- `docs/architecture/phase-03n1-mature-build-learning-store.md`
- `docs/superpowers/specs/2026-06-27-mature-build-learning-design.md`
- `docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md`

### Phase 3N.2 deterministic mature candidate extraction

已实现并审查：

- 从 sanitized mature cases 确定性抽取低信任 `technique_candidates`。
- 为候选写入 `candidate_evidence`。
- candidate ID 包含 creator/evaluator/quarantine bucket，避免 holdout/quarantine evidence 合并到 creator-visible candidate。
- 非 creator 候选降为 `eval_ephemeral`。
- `source_count` / `support_count` / `contradiction_count` 从 evidence 表回算。
- 推导生命周期提示字段：
  - `required_prerequisites`
  - `starter_risk_reason`
  - `transition_gate_summary`
  - `unsafe_before_stage`
- `candidate_evidence.evidence_id` 使用 `{case_id, relation, extraction_method}`，避免 case visibility 改变后旧 creator-visible evidence 残留。
- candidate upsert 保留已有 `promoted` / `rejected` / `stale` 状态。

重要定位修正：

- 3N.2 的确定性抽取是安全 baseline / fallback，不是主要智能来源。
- 实跑 seed fixture 后可见，其输出多为标签级摘要，不能充分提炼“为什么强、质变点是什么、何时转型”等高价值 BD 技巧。
- 后续 mature learning 的主要技巧抽取应提前引入 LLM，但 LLM 输出必须经过 sanitizer、evidence、freshness 和评测边界。

局部文档：

- `docs/architecture/phase-03n2-mature-candidate-extraction.md`
- `docs/superpowers/plans/2026-06-27-mature-learning-candidate-extraction-3n2.md`

## 当前工作：Phase 3N.3 方向纠偏

当前 3N.3 不再继续实现先前的 creator-safe retrieval 草稿。

已废弃方向：

- `docs/architecture/phase-03n3-mature-retrieval-provenance.md`
- `docs/superpowers/plans/2026-06-27-mature-learning-retrieval-3n3.md`

废弃原因：

- retrieval 只能读取已有候选，但当前确定性候选本身洞察不足；
- 项目真正需要优先验证的是：LLM 能否从真实热门成熟 BD 中提取有价值的设计技巧，并让 creator agent 变强；
- 继续堆 retrieval / FTS / vector，会把工程做漂亮但不解决“BD 创造能力不足”的核心问题。

新的 3N.3 目标：

Phase 3N.3 LLM-assisted mature build extraction and real-effect validation。

当前 active 文档：

- `docs/architecture/phase-03n3-llm-mature-extraction-real-effect.md`
- `docs/superpowers/plans/2026-06-27-phase-03n3-llm-mature-extraction-real-effect.md`

目标：

- 定位并获取当前赛季 poe.ninja 热门 BD 的真实样本来源，优先覆盖多个职业/升华，而不是单职业样本。
- 从真实热门样本生成 sanitized brief，保留 provenance、league、patch、tree、rank/popularity、diversity bucket。
- 使用 LLM 提取高价值技巧候选：
  - 核心机制；
  - 技能/辅助/装备/天赋/升华协同；
  - 质变阈值；
  - 开荒不可行原因；
  - 转型门槛；
  - PoB 可建模性；
  - 失败风险；
  - 可复用设计原则。
- 确定性 sanitizer 和 copyability guard 继续阻止 raw build 泄漏。
- 使用 creator/evaluator split 做真实效果验证：creator 不看 holdout，evaluator 比较生成结果与 held-out mature evidence。
- LLM 反思出的技巧先进入 candidate，不自动晋升 durable memory。

当前已完成的 3N.3 准备工作：

- 已完成新需求开发前 subagent 预审。
- 已写入 3N.3 局部技术文档，明确 source probe 和 LLM 信息预算是硬前置门禁。
- 已写入 3N.3 中文实施计划，后续执行应按风险分级测试策略推进。
- 已明确 3N.3 不接 route synthesis、不自动晋升 durable memory、不做自动周期性 fetcher、不引入 vector DB / graph DB。
- 已实现 `server/live/mature_sources.py` source probe shape helper，用于 copy-safe 地总结来源响应形状，不保存 raw 内容。
- 已新增 `tests/test_mature_sources.py`，覆盖 ascendancy-only payload、aggregate rows、build-level row shape 和 HTTP/payload 失败摘要。
- 已完成首轮 live poe.ninja source probe，并写入 `docs/research/poe-ninja-source-probe-2026-06-27.md`。
- 本次 source probe 结论：公开 `index-state` / `build-index-state` 只稳定提供 league/snapshot/ascendancy/sample-size 级别信息；未找到稳定公开 build-level JSON rows；猜测 build-level API 路径返回 404。
- 已实现 `server/knowledge/mature_sample_contract.py` 样本 manifest 合同，用于校验 source/popularity/freshness/diversity 元数据，并拒绝 raw/copyable build 内容。
- 已新增 `tests/test_mature_sample_contract.py`，覆盖缺失字段、未知来源、freshness/popularity 不完整、raw 字段、PoB blob、完整 support-link-like 文本和嵌套 copyable 字段。
- 已实现 `server/knowledge/mature_llm_extraction.py` 的 LLM extraction schema validation 与 copy-safe prompt package；当前不调用模型 provider、不写 DB、不接 route synthesis。
- 已新增 `tests/test_mature_llm_extraction.py`，覆盖 schema、patch/tree/evidence 必填、raw 字段、PoB blob、完整 support-link-like 文本、高 copyability risk、非法枚举和 prompt 构造前 raw 字段拒绝。
- 已实现 `server/knowledge/mature_eval.py` creator/evaluator contamination guard 与 evaluator gap 类型校验。
- 已新增 `tests/test_mature_eval.py`，覆盖 creator 输入中的 evaluator-only / eval-holdout / quarantined / raw PoB / copyable 文本拒绝，以及 evaluator gap 类型、severity 和 copyability 校验。

当前尚未实现：

- 首轮 `docs/evaluations/*phase-03n3*` 真实效果验证报告；
- 真实 poe.ninja build-level 热门样本抓取器；
- LLM extraction output 写入 `technique_candidates` / `candidate_evidence`；
- LLM extraction runner；
- teacher-student / evaluator 自动循环；
- mature candidates 到 route synthesis 的接入；
- active expiration/downweighting；
- vector DB / external graph DB。

## 真实效果验证原则

单测只能验证既定代码逻辑是否正确，不能证明 BD Creator 真的更会做 BD。

从 Phase 3N.3 开始，每个会影响“BD 创造能力”的阶段都需要设计实际效果验证。详见：

- `docs/architecture/real-effect-evaluation-protocol.md`

真实效果验证应至少覆盖：

- 新手输入：“给我一个强力 BD”；
- 生命周期完整性：starter → transition → maps entry → budget endgame → final；
- 热门成熟 BD 核心机制命中；
- 终局-only BD 是否被误当开荒；
- 转型门槛是否合理；
- engine 可验证数值是否真实；
- 不可建模机制 caveat；
- copyability/safety；
- freshness/patch/tree 标签；
- evaluator gap 的数量和严重度。

## 确认门槛

以下事项必须先获得用户确认：

- 主动知识过期 / 降权策略；
- 自动周期性 live fetcher；
- mature candidates 直接影响 route synthesis；
- 自动晋升 durable technique memory；
- 引入 vector DB 或 external graph DB；
- 存储或展示可能复刻真实 BD 的 raw 内容。

## 审查和验证政策

- 每轮新需求开发前，向 subagent 提供项目目标、当前阶段目标、需求目标和拟实施内容，做设计/规格预审。
- 代码改动完成后，默认做 subagent code review。
- 接口、需求语义、evidence 边界、安全边界、用户输出合同变化时，做窄规格复审。
- 关键功能先写局部技术文档，再写代码。
- 测试策略按风险分级：
  - 简单确定性逻辑（字段 shape、纯函数过滤、文档生成、无副作用格式转换）可以直接实现，然后跑 targeted tests；
  - 涉及安全边界、evidence/visibility 边界、DB schema/migration、LLM 输出合同、route synthesis、engine/PoB 数值、bug 回归时，优先使用严格 TDD 或至少先写能捕获风险的测试；
  - 无论是否 TDD，都不能跳过验证；完成声明必须有新鲜验证输出支撑。
- 使用技能时必须从当前 session 的 skill roots 展开真实路径读取，不能猜路径。
- 工具调用卫生是硬要求：
  - 禁止调用无说明、无用途或占位性质的本地工具，尤其不要调用 `functions.zz`。
  - 每次工具调用前必须能说清楚“这次调用要验证/读取/修改什么”；说不清就不要调用。
  - `multi_tool_use.parallel` 只用于彼此独立且确实需要的命令，不得夹带占位、空调用或无关技能读取。
  - 技能文件路径必须严格按当前会话的 skill roots 表展开；不能使用记忆中的旧路径或猜测路径。
- 验证梯度：
  1. touched feature targeted tests；
  2. `.\scripts\verify.ps1 quick`；
  3. `.\scripts\verify.ps1 noncompute`；
  4. `compute` / `full` 只在 engine/PoB/optimizer/runtime 或 release/merge 时使用。
- 文档-only 改动至少做 `git diff --check` 和人工一致性检查。

## 近期待办

优先级最高：

- 执行 Phase 3N.3 实施计划：
  `docs/superpowers/plans/2026-06-27-phase-03n3-llm-mature-extraction-real-effect.md`。
- 根据首轮 source probe 结论，推进 pobb.in / forum / guide / manual curated fallback sanitized brief 流程。
- 实现 LLM extraction output 到候选/evidence 层的导入，同时保持 creator/evaluator 边界。
- 生成首轮真实效果验证报告模板，并用小样本跑通 creator/evaluator 对比。
- 设计并执行首轮 4～8 个小样本真实效果验证；随后扩展到 10～30 个多职业热门样本。

随后：

- teacher-student mature build evaluation loop。
- evaluator gap 蒸馏为 candidate technique。
- candidate promotion / revalidation。
- passive tree 研究：大图搜索、非连通选择、珠宝半径、阈值机制。
- 用户反馈诊断：伤害低、暴毙、缺蓝、清图慢、Boss 慢等。
- memory relevance：按 patch/tree/route relevance 限制 durable cards 召回。

## Codex 接续指南

新会话或上下文压缩后，优先读取：

1. `docs/PROJECT_SPEC.md`
2. `docs/PROJECT_ARCHITECTURE.md`
3. 当前阶段局部 architecture 文档
4. 当前阶段 implementation plan（如果存在且仍 active）
5. `server/ASSISTANT_GUIDE.md`
6. `scripts/verify.ps1`

注意：

- `docs/superpowers/plans/*` 大多是历史实施计划，不一定代表当前方向。
- Phase 3N.3 retrieval 草稿已废弃，不要继续实现 `server/knowledge/mature_retrieval.py`。
- `tests/test_mature_learning.py` 仍保护 mature-learning 安全边界，不要因为 deterministic extraction 被降级就删除安全测试。
