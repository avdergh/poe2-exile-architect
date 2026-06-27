# Phase 3N.3 LLM 辅助成熟 BD 抽取与真实效果验证

Last updated: 2026-06-27

本文档定义 Phase 3N.3 的局部技术设计。它覆盖“真实热门成熟 BD 样本发现 → LLM 技巧抽取 →
creator/evaluator 对照 → 真实效果验证”的最小可落地闭环。

本阶段不是继续实现旧的 retrieval-first 草稿。retrieval 只能读取已有候选；当前真正需要先验证的是：
LLM 能否从真实热门成熟 BD 中提取非平庸设计技巧，并让后续 BD Creator 更会做生命周期路线。

## 1. 目标

Phase 3N.3 的目标是建立一个小而可信的成熟 BD 学习闭环：

1. 找到当前赛季真正流行的成熟 BD 样本来源，优先 poe.ninja，必要时补充 pobb.in、论坛、攻略或手工
   curated 快照。
2. 将样本转成可持久化的 sanitized brief，保留来源、赛季、patch、天赋树、流行度和多样性标签。
3. 让 LLM 在 copy-safe 合同下提取技巧候选：机制、协同、阈值、转型门槛、开荒风险、PoB 可建模性和失败风险。
4. 把 LLM 输出再次经过 schema validation 与 copyability guard。当前实现只做 prompt package、schema validation 和安全门禁；写入候选层属于后续任务。
5. 使用 creator/evaluator split 做真实效果验证：creator 不能看 holdout，evaluator 用 held-out mature evidence 对比输出差距。
6. 产出一份真实效果评估报告，证明本阶段是否真的改善了 BD 研究能力，而不是只让单测变绿。

## 2. 本阶段不做什么

这些能力都不在 Phase 3N.3 MVP 内，除非后续单独设计并获得用户确认：

- 不让 mature candidates 直接影响正式 route synthesis。
- 不自动晋升 durable technique memory。
- 不实现主动知识过期、降权或自动重验证策略。
- 不实现自动周期性 live fetcher。
- 不引入 vector DB 或 external graph DB。
- 不保存 raw PoB code、完整装备表、完整 passive tree、完整 passive node list、完整 gem links 或攻略全文。
- 不把 evaluator-only / holdout / quarantined evidence 暴露给 creator。

## 3. 两个硬前置门禁

### 3.1 来源探测门禁

现有代码已经能稳定读取 poe.ninja snapshot / ascendancy popularity，但还不能假设 build-level 热门样本接口可用。
因此 3N.3 的第一步必须是 source probe spike。

source probe 要记录：

- 探测的 URL、参数、请求头类型和时间；
- HTTP 状态；
- 响应形状摘要，而不是 raw 响应全文；
- 是否稳定、是否需要浏览器 header、是否需要页面脚本或 protobuf 解析；
- 是否包含 build-level 行；
- 是否只包含 ascendancy popularity；
- 失败原因；
- fallback 建议。

如果 poe.ninja build-level 数据无法稳定获取，系统必须明确进入 fallback：

1. 使用 poe.ninja 提供的赛季/天赋树/样本量作为 freshness 与 meta context。
2. 从 pobb.in、论坛/攻略、社区高热度帖子或手工 curated sanitized fixtures 收集少量成熟案例。
3. 保留“poe.ninja build-level unavailable”的可追踪报告，不能假装已经拿到了热门 BD 明细。

### 3.2 LLM 信息预算与安全合同门禁

3N.2 的确定性候选只看粗标签，已经证明只能产出浅层摘要。3N.3 必须让 LLM 参与真正的机制抽取，
但同时不能把 raw/copyable 内容落库或暴露给 creator。

本阶段采用三层信息模型：

| 层级 | 是否可持久化 | 是否 creator-visible | 用途 |
| --- | --- | --- | --- |
| source raw / page / PoB code | 否 | 否 | 只允许在受控 extraction 操作中短暂读取，用于理解来源。不能写入 DB、报告或 prompt artifact。 |
| extractor rich brief | 默认否；如需保存必须 quarantine | 否 | LLM 抽取时的临时上下文。可以帮助理解机制，但输出前必须压缩成非复制技巧。 |
| sanitized brief / technique candidate | 是 | 仅限 creator_visible/train_context | 可持久化、可评估、可作为后续 creator context 的安全摘要。 |

关键原则：

- LLM 可以在 extraction worker / Codex / Claude Code 的临时上下文中阅读来源材料并归纳，但最终落库内容必须是
  sanitized、schema-valid、non-copyable 的技巧候选。
- raw PoB、完整装备、完整树、完整 gem links、攻略全文都不能写入本地 SQLite、seed fixture、报告或最终用户输出。
- LLM 输出默认低信任。没有 schema validation、copyability guard、evidence refs 和 evaluator check，就不能进入
  creator-visible 候选。

## 4. 数据流

```text
source probe
  -> source_probe_report
  -> sample discovery decision
  -> source snapshot + provenance
  -> sanitized mature case
  -> LLM extraction prompt package
  -> LLM structured output
  -> schema validation + copyability guard
  -> future candidate/evidence import (not implemented in current slice)
  -> creator/evaluator split evaluation
  -> gap report + reflection candidate
```

这个流程中有两个事实源：

- SQLite mature-learning store：已能保存 sanitized cases、确定性候选技巧和 evidence 边界；当前 3N.3 切片尚未把 LLM 输出写入 store。
- evaluation report：保存本轮真实效果验证结果、gap、人工判断和下一步动作。

## 5. 建议新增模块

### `server/live/mature_sources.py`

负责网络来源探测和响应形状摘要。它只做 source probe，不做自动抓取器。

职责：

- 探测 poe.ninja build-level 相关 URL 或页面数据源；
- 记录 HTTP 状态和响应 shape；
- 判断是否有可用 build-level rows；
- 返回 `SourceProbeReport`，不返回 raw 页面全文或 raw JSON dump。

### `server/knowledge/mature_llm_extraction.py`

负责 LLM 抽取合同，不负责直接调用某个商业模型。

职责：

- 生成 copy-safe extraction prompt package；
- 定义 LLM 输出 JSON schema；
- 校验 LLM 输出；
- 对输出运行 copyability guard；
- 暂不写入 `technique_candidates` / `candidate_evidence`，后续若实现导入，必须走现有 evidence/visibility 边界。

这样设计是为了让 Codex、Claude Code、Claude Desktop MCP 或未来 OpenAI/Claude API provider 都能复用同一合同。
3N.3 不是“以后才用 LLM”：LLM 在本阶段就参与抽取；只是本地代码先不绑定具体 provider key。

### `server/knowledge/mature_eval.py`

负责真实效果验证的结构化记录。

职责：

- 表示 creator 输入、creator 输出摘要、evaluator held-out evidence、gap 和 reflection；
- 生成 evaluation report 数据结构；
- 保证 evaluator-only 信息不会出现在 creator input。

如果后续发现该模块与 `lifecycle_eval.py` 高度重叠，可以再合并；3N.3 先保持边界清楚。

## 6. LLM 抽取输出合同

LLM 输出必须是 JSON 对象，并至少包含：

```json
{
  "schemaVersion": 1,
  "sourceCaseId": "case-id-or-source-ref",
  "techniques": [
    {
      "techniqueName": "short non-copyable name",
      "mechanismSummary": "what the build is doing at a high level",
      "whyItWorks": "why the interaction scales or stabilizes the build",
      "requiredComponents": ["coarse component category, not full item/gem list"],
      "thresholdsOrBreakpoints": ["coarse threshold or unknown"],
      "lifecycleApplicability": "starter_to_endgame | starter_then_transition | endgame_only | starter_only | unknown_lifecycle",
      "starterRisks": ["why this may fail during campaign"],
      "transitionGates": ["specific but non-copyable gate"],
      "skillLinksSummary": "coarse role summary, not full gem links",
      "passiveTreeAnchors": ["coarse anchor family, not node list"],
      "gearOrUniqueRoles": ["role of unique or gear class, not full gear table"],
      "defensePlan": "coarse defensive identity",
      "pobModelability": "full | partial | not_modelable | unknown",
      "evidenceRefs": ["sanitized evidence id or source group id"],
      "confidence": "low | medium | high",
      "copyabilityRisk": "low | medium | high"
    }
  ]
}
```

输出必须拒绝或 quarantine 的情况：

- 出现 PoB code、pobb.in raw code、pastebin code 或 XML。
- 出现完整装备表、完整 affix、完整 passive node list、完整 gem/support links。
- 出现长段复制攻略文本。
- `copyabilityRisk = high` 但仍试图写入 creator-visible。
- 缺少 evidence refs、patch/tree/league 或 lifecycle 判断。

## 7. Creator / Evaluator split

creator 输入只允许包含：

- creator-visible/train-context sanitized cases；
- 通过校验且已完成候选导入的 creator-visible technique candidates；
- aggregate meta / freshness evidence；
- 用户目标和偏好。

creator 输入禁止包含：

- evaluator-only / eval-holdout cases；
- evaluator-only LLM extraction；
- raw source；
- held-out mature build 的完整信息；
- 能复刻 held-out build 的差异报告。

evaluator 可以读取 held-out mature evidence，但输出给 creator 的 gap 必须是抽象问题，例如：

- 缺少核心机制；
- 转型过早；
- 低估预算；
- 防御层不足；
- sustain 风险；
- PoB 不可建模 caveat 遗漏；
- 生命周期分类错误。

## 8. 真实效果验证 MVP

3N.3 MVP 通过标准：

- 完成一次 poe.ninja build-level source probe，并记录成功或失败原因。
- 有 fallback 样本流程，而不是卡死在单一来源。
- 规划或导入 10～30 个多职业 sanitized samples；早期可以先用 4～8 个样本跑通闭环，但报告必须标注样本不足。
- 后续真实效果执行阶段至少产生一条 LLM 抽取的非平庸技巧候选，例如包含机制、阈值、转型门槛和开荒风险；当前代码切片只提供抽取合同和校验。
- creator/evaluator 对比能指出差异，而不是只说“相似/不相似”。
- 没有 raw/copyable 内容落库或进入 creator 输出。

## 9. 与现有 3N.1 / 3N.2 的关系

- 3N.1 的 SQLite store、sanitizer、fixture manifest 和 copyability guard 继续作为安全底座。
- 3N.2 的 deterministic extraction 保留为 baseline/fallback，不删除、不贬成废代码。
- 3N.3 新增 LLM extraction 合同后，未来若把 LLM 输出导入候选层，仍必须通过 existing candidate/evidence 边界进入 store。
- 如果 3N.3 需要保存更丰富的 LLM extraction artifact，必须新增 schema migration 和测试；不能把 raw JSON 塞进任意字段。

## 10. 后续确认点

以下决策不在本阶段自动推进，必须单独询问用户：

- 是否允许成熟技巧候选影响正式 BD route synthesis；
- 知识过期、降权和重验证策略；
- 是否开启自动周期性 live fetcher；
- 是否引入 vector DB 或 graph DB；
- durable technique memory 的自动/半自动晋升规则；
- 是否允许将真实热门样本 seed 随开源项目发布，还是仅作为本地私有评测集。
