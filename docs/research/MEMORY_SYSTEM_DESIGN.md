# PoE2 BD Agent 记忆系统设计

## 1. 文档定位

本文设计当前项目下一版领域记忆 MVP。项目不是从零开始：Phase 4 已经从真实成熟 BD 中提取
fragment、semantic edge、build pattern 和简单技巧，Phase 5 的真实会话也验证了这些知识能够改善
BD 生成。

当前目标不是先建设一套完整 Agent memory 平台，而是解决三个具体问题：

1. 成熟 BD 的提取深度仍不够，很多机制被拆成了失去整体语义的小关系；
2. 缺少职业/升华级的设计原则、取舍、失败模式和评估注意事项；
3. 现有 `query_research_memory` 主要返回 ID 和元数据，Agent 有时没有真正获得可用知识。

MVP 只验证：在现有 memory 基线上增加深度核心机制包和高层经验，能否继续提高最终 BD 质量。

## 2. 核心原则

### 2.1 Agent 继续主导 BD 创造

记忆提供机制、经验、反例和设计问题，不替 Agent 选择最终技能、装备、天赋或升华。合法性和数值
仍由静态资料、typed graph、PoB、Judge 和人工共同核验。

### 2.2 事实、案例和经验分层

- physical graph：游戏实体、静态事实和官方 ID；
- semantic edge / build pattern：组件关系和组内模式；
- deep research record：一次或一组成熟 BD 的完整安全分析档案；
- mature-build case / fragment：档案引用的案例证据和可检索结论；
- design memory card：跨一个或多个案例形成的高层设计经验；
- Phase 7 episode：未来的生成、修复和结果经验。

一次案例可以产生观察，但不能自动成为职业通用规律。

本文中的几个术语具体含义：

- **失败模式**：一个设计在什么条件下会失去预期效果，以及断点在哪里。例如充能玩法在 Boss 无
  杂兵时无法稳定产球、冻结链面对不可冻结目标失效、Spirit 预留过满导致核心技能无法启用、局部
  天赋转换节点未分配时胸甲不再是防御引擎。它不是“这个 BD 很差”，而是带触发条件和后果的
  可复用风险知识。
- **组内模式**：只在当前明确样本组中重复出现的共同选择或机制。例如三个 Martial Artist 样本都
  使用 Hollow Focus + Refutation。它能支持“该三样本组存在共同壳”，但不能直接声称所有
  Martial Artist 都必须这样设计。
- **安全研究证据**：从原始 PoB、语料、PoB 读回或人工分析中得到、经过清洗后可以长期引用的证据。
  它可以包含精确组件名、机制文本摘要、结构化数值范围、工具结果 hash、案例 ID 和核心组合；不含
  PoB code/raw XML、账号角色信息、长篇来源原文或第三方整角色镜像。

### 2.3 保存完整核心机制，不保存整角色镜像或原始导入材料

记忆可以并且应该完整保存对重新设计 BD 有价值的核心机制包，例如：

- 一个主动技能与其关键辅助宝石组合；
- 清图、Boss、触发、生成和消费技能之间的完整职责链与轮转；
- keystone、notable、天赋珠宝和局部核心天赋连接方案；
- 暗金或关键装备职责与技能、辅助、天赋、资源系统之间的完整联动；
- generator -> state -> transformer -> payoff -> refresh 的机制闭环；
- 该组合的适用条件、机会成本、替代方案和失败条件。

“片段”按知识作用域定义，不按长度、节点数量或辅助宝石数量定义。一个片段可以在自己的机制范围
内完整。少一个节点或少一个辅助不是安全边界，多记录几个关键组件也不等于复制。

禁止持久化的是能够一比一还原第三方整名角色的原始或镜像材料：

- PoB 导入码、raw XML、账号和角色信息、原始整角色导出；
- 把全部装备槽的精确物品、整棵已分配天赋、全部技能组和完整配置共同保存成整角色快照；
- 长篇复制攻略或来源原文。

判断依据是知识作用域：核心机制包允许完整，整角色镜像禁止。copy-safety 不得仅因辅助数量、局部
天赋顺序，或暗金、技能和天赋同时出现而拒绝知识。

当前 `server/knowledge/copy_safety.py` 中按辅助数量、分隔符长度、局部路径形状或装备槽形状触发的
启发式规则与本边界不完全一致。实现 MVP 时必须调整：这些信号最多用于提示“可能是整角色镜像”，
不能单独阻止核心机制包入库；只有原始导入材料或跨装备、天赋、技能和配置的整角色聚合才阻止
持久化。

系统生成并通过可信 Judge 的最终 PoB 仍按 Phase 6 私有产物合同保存，不进入研究 memory。

### 2.4 版本、证据和作用域必须保留

每条长期经验至少带：

- 职业和升华作用域；
- 生命周期、场景和预算条件；
- 来源案例和安全证据引用；
- 赛季大版本、天赋树版本和必要的 PoB/modelability 信息；
- 提议状态由现有 accept 流程处理；持久 fragment 沿用 valid、needs_revalidation、deprecated、
  rejected 等现有状态；
- 适用条件、失败条件和已知反例。

### 2.5 不保存隐藏推理

只保存可审查的原则、机制说明、来源、字段依据和 rationale summary。不保存 hidden
chain-of-thought、草稿推理、完整对话或 raw prompt。

## 3. MVP 范围

### 3.1 MVP 实现

- 深化 Phase 4 提取，允许保存完整核心机制包；
- 新增一层完整安全深度研究档案，避免 Researcher 在入库前被 fragment 字段迫使删减信息；
- 扩展现有 `research_fragments`，让它承载档案的可检索索引和高层经验；
- 复用现有 Researcher 提议/accept 流程，在写入前完成人工批准；
- 增强现有 `query_research_memory`，直接返回可读的 fragment、edge、pattern 和高层经验；
- 更新 Researcher/Creator skill 和 runtime guide，列清工具调用方式；
- 用 current-memory 与 deep-memory 的真实会话做人工对照。

### 3.2 MVP 明确不实现

- 独立向量数据库或新数据库服务；
- 独立的 design-memory FTS 索引；
- retrieved/used/outcome 事件链和自动 credit assignment；
- run-token 绑定的 memory 使用审计；
- 自动 reward、自动调权或自动晋升；
- 自动 reflection loop；
- 动态职业档案缓存；
- embedding、图扩散和复杂 rerank；
- 多级 feature flag 发布平台；
- 自动修改 schema、prompt、skill 或代码。

这些能力只有在 MVP 证明深度 memory 有增量价值后才考虑。

## 4. 深度提取内容

Researcher 对成熟 BD 至少尝试提取以下结构；样本没有的维度可以为空，不允许为了填字段编造：

### 4.1 技能职责包

- active skill 和关键 supports；
- clear、boss、burst、generator、consumer、trigger host、triggered payload、movement、defense、
  reservation 等职责；
- 技能之间的启动条件、资源流、状态流和轮转；
- Boss 无杂兵、无法冻结、无法击杀等环境下是否仍成立。

如果关键 supports 共同决定技能行为，应保存完整关键组合，不机械拆成单 pair。

### 4.2 机制链

```text
generator
-> state/resource
-> transformer
-> payoff
-> refresh
-> failure condition
```

应说明哪些部分由机制文本证明、哪些由 PoB 计算、哪些只是 Researcher 推断。

### 4.3 装备和暗金联动

- 装备槽职责；
- 机制启用、资源闭环、状态生成、恢复、扩散或防御作用；
- 与技能、辅助、天赋和珠宝的组合；
- 黄装或其他暗金替代；
- 机会成本、预算、词缀现实性和获取注意事项。

允许保存一个暗金与相关技能、辅助、天赋组成的完整核心联动。

### 4.4 天赋和珠宝结构

- 共同骨架与变体专属区域；
- keystone/notable/passive anchor；
- 局部核心连接方案；
- weapon-set A/B 的不同职责；
- 天赋珠宝、半径放大、装备授予节点和转化链。

允许保存解释机制所需的局部核心天赋连接，不要求退化成几个孤立节点。只有整棵角色已分配树的
镜像才属于禁止项。

### 4.5 设计哲学和取舍

- 为什么该职业或升华适合这套机制；
- 输出、防御、恢复、操作和预算如何取舍；
- 什么是必需组件、可选组件和追求上限组件；
- 哪些路线看似相似但在特定条件下会失败；
- PoB/Judge 对该机制有哪些评估盲点。

## 5. MVP 存储设计

### 5.1 复用现有存储

继续使用 mature-learning SQLite：

- fragment、semantic edge、build observation、build pattern 保持现状；
- 原始成熟 BD 继续只在 quarantine transient 流程中使用；
- 新增聚焦研究记录作为深度知识事实源，fragment/edge/pattern 作为它的检索索引和可复用结论；
- 两层引用同一 case/evidence IDs，不复制原始 PoB 材料。

### 5.2 BuildFamily 与 canonical knowledge

反复研究真实案例后，单靠 `research_group_id + record_kind + title` 无法阻止近义重复。MVP 增加一层
轻量归类，但不把整个 BD 固化成模板：

```text
source snapshot
-> BuildFamily（升华 + 核心主技能 + 核心副技能集合）
-> canonical DeepResearchRecord knowledge unit
-> per-source safe evidence
```

防御、暗金、supports、资源方案和预算差异不参与 Family 身份，它们作为同一 Family 下的知识单元或
来源变体保存。每条知识再按 `record_kind` 选择必要的核心角色组件生成 `knowledge_key`；完全相同的
结构才自动归并，部分相似只保留为独立记录。标题或正文改写不能单独触发合并。

存储继续复用 mature-learning SQLite，只增加：

- `research_build_families` 与按 source 去重的 Family evidence；
- `deep_research_records.build_family_key/knowledge_key/evidence_count`；
- `deep_research_record_evidence`，保存各来源观察到的组件、条件、失败条件和版本。

同知识出现新来源时不复制 canonical 正文。系统选择信息更完整的一条作为代表，其他来源细节留在
evidence；历史高置信重复标记为 `deprecated` 并指向 canonical，无法可靠识别的旧记录保持原状。
召回命中 Family 的核心技能时，可在结果预算内扩展到该 Family 的其他知识单元，并同时返回升华、
主技能、副技能和来源计数摘要，使生成阶段可以实际消费分类结果。

### 5.3 `deep_research_records`

现有 `research_fragments` 无法无损保存三个案例中已经出现的完整轮转、双武器状态、装备槽职责、
天赋结构和工具盲点。MVP 因此新增一张轻量深度记录表，而不是把所有内容继续压进 fragment，或把
一个案例的全部分析塞进一条超长记录。

一次研究任务产生一组 `DeepResearchRecord`。每条记录只回答一个主要问题，例如一个技能包、
一条机制链、一个装备联动或一个失败模式；同一案例或同一比较任务通过 `research_group_id` 聚合。
案例分析的完整性由这组记录共同承担，不要求任何单条记录成为整份案例报告。

必要字段：

| 字段 | 说明 |
| --- | --- |
| `record_id` | 稳定 ID |
| `research_group_id` | 同一案例、样本组或比较任务的聚合 ID；不要求新增独立 group 表 |
| `record_kind` | 聚焦知识类型；使用当前 strict 枚举，扩展需走 schema review |
| `title`、`summary` | 记录标题和短检索摘要 |
| `content` | 对当前知识单元完整、可审查且精简的说明 |
| `component_keys` | 本记录涉及的稳定技能、物品、天赋、职业或机制组件 |
| `conditions`、`failure_conditions` | 成立条件、机会成本、风险和失效边界 |
| `class_key`、`ascendancy_key` | resolver-backed 作用域；跨变体记录可包含多个 scope refs |
| `source_case_refs`、`safe_evidence_refs` | 案例和安全证据 |
| `typed_payload` | 可选结构化内容；只用于该 record kind 已稳定的字段 |
| `extraction_method_version`、`record_schema_version` | 提取和档案版本 |
| `game_patch`、`passive_tree_version`、`pob_version_or_commit` | 版本上下文 |
| `visibility`、`split`、`knowledge_scope` | 复用现有隔离合同 |
| `status`、`copy_safety_state` | valid/revalidation/deprecated 等状态 |
| `created_at`、`last_validated_at` | 时间 |

首批推荐的 `record_kind` 保持贴近实际研究内容：

- `skill_package`、`mechanic_chain`、`rotation`；
- `gear_synergy`、`passive_package`、`defense_engine`、`resource_engine`；
- `design_tradeoff`、`failure_mode`、`modelability_caveat`；
- `variant_comparison`、`class_or_ascendancy_principle`、`open_question`。

这些类型不是提取上限。新案例出现无法准确归类的知识单元时，可以提交一个描述清楚的实验类型，
与 schema extension candidate 一起审查；不能为了服从现有枚举而降低提取质量。

单条记录遵守以下约束：

- 只表达一个主要知识单元，不混入整份案例概览；
- `summary` 用于检索，`content` 用于解释该单元如何成立、何时使用以及如何失败；
- 单条 `content` 正文原则上不超过 400 个中文字符；英文按单词计算，原则上不超过 250 个英文
  单词。标题、结构化字段、组件 ID 和证据引用不计入正文预算；
- 这是写作软预算，不是数据库硬限制。超过预算时应优先检查是否混入了多个问题，并按可独立召回的
  知识单元拆分；
- 不在每条记录重复职业、版本、来源背景和整组结论；共享信息由顶层字段、引用和
  `research_group_id` 表达；
- 只有拆分会破坏同一核心机制的 generator/state/transformer/payoff 因果闭环，或拆散必须共同成立
  的技能、辅助、装备和天赋联动时，才允许少量超过预算；
- 新发现尚无合适 `record_kind` 或 `typed_payload` 时，可以先使用受审查的实验类型并在 `content`
  中准确表达，同时提交 schema extension candidate，不能丢弃或硬塞进错误字段。

例如同一个复杂变体可以拆成“标记与冻结机制链”“双武器天赋状态”“关键装备槽职责”“PoB
不可建模点”“高预算机会成本”等多条记录，而不是保存成一条变体全分析。

### 5.4 `research_fragments` 作为召回索引

一组深度记录完成后，Researcher 再提炼可查询 fragment/edge/pattern。给 fragment 增加：

- `source_record_refs`：引用相关聚焦记录；
- 新 fragment types：`class_principle/design_tradeoff/failure_pattern/evaluation_caveat`；
- 可选 `scope_class_key/scope_ascendancy_key/scenario_tags/budget_bands/evidence_scope`。

fragment 不负责保存所有研究内容，只负责：

- 为 Agent 召回提供短而可读的原则和风险；
- 给图关系和高层经验提供稳定引用；
- 指向聚焦记录，以便 Agent 在需要时进一步读取完整知识单元。

这样既不限制深度提取字段，也不要求每次召回把整个案例的全部研究记录塞进上下文。

## 6. 写入与人工审查

### 6.1 提议流程

```text
成熟 BD transient evidence
-> Researcher 深度分析
-> 按知识单元拆成一组 DeepResearchRecord
-> 检查研究组覆盖范围和每条记录的聚焦性
-> 人工确认没有丢失重要机制且不含整角色镜像
-> 批量写入 deep_research_records
-> 从记录组提炼 fragment/edge/pattern proposals
-> 通过现有 accept/propose 流程写入检索索引
```

程序只检查：

- strict schema；
- 记录顶层身份、research group 和 stable keys 可解析；
- evidence refs 存在且没有越过 creator/holdout/local 边界；
- 版本和作用域完整；
- 没有 PoB/raw XML、账号信息或第三方整角色镜像；
- 单案例没有被冒充为 cohort/cross-source；
- 每条记录只有一个主要知识单元，研究组覆盖清单没有明显缺口；
- 索引 fragment 没有把经验写成游戏硬合法性。

当前实现还补充两条运行保障：版本上下文由 queue 从应用兼容清单/已安装 runtime 注入并由 accept
覆盖 worker 自填值；`pob_version_or_commit` 的新写入值使用应用维护的 PoB 版本枚举，缺失或
`unknown` 归一为当前版本。fallback worker 可以只提交组件名称、职责和 resolver 查询词，由 accept
gate 解析稳定 ID。
整案没有任何锚定具体组件的可复用机制记录时，在写库前拒绝，避免通用警告污染 durable memory。

程序不得因为核心技能组合、关键 supports、局部天赋连接或暗金联动记录得完整而拒绝记录。

### 6.2 人工审查

MVP 在现有研究 accept 流程前增加一次记录组 review：

```text
show research group summary and focused records
-> approve | request repair | reject
-> persist record group
-> review and accept derived fragments/edges/patterns
```

人工重点判断：

- 是否比组件共现更深入；
- 是否保留了机制成立所需的完整组合；
- 记录组是否覆盖当前能够观察或合理推断的重要内容；
- 单条记录是否聚焦、有效，是否混入多个本可独立召回的主题；
- 是否错误扩大作用域；
- 是否有明确机会成本、失败条件和反例；
- 是否能指导 Agent 设计，而不是空泛结论；
- 是否已经接近第三方整角色镜像。

未批准的记录组不必先持久化到数据库；需要修改时重新提交 safe records。已写入记录若需重大修改，
沿用 deprecated/successor 思路，不在 MVP 新建 review event 系统。

## 7. 召回设计

### 7.1 复用 `query_research_memory`

MVP 不新增 `query_design_memory`。增强现有 `query_research_memory`，让一个工具返回：

- 可读 fragment：title、summary、principle、conditions、risks、verification tasks；
- 相关 semantic edges；
- 相关 build patterns 和 planner hints；
- 匹配的高层经验 fragments；
- 匹配记录的 record ID、research group ID、title 和 summary；
- 每项的 ID、作用域、版本、证据和 modelability caveat。

现有公开查询主要返回 ID 和元数据。MVP 必须修复这一点；只有返回 Agent 能读懂的知识内容才算查询
成功。

MVP 给 `query_research_memory` 增加可选 `detail_level=summary|record`：

- `summary` 默认返回短 fragment/edge/pattern 和档案摘要；
- `record` 仅对已命中的少量 record ID 返回完整聚焦记录。

这样 Agent 可以先检索摘要，再按需深读；不会因为字段丰富而一次塞入同一案例的全部记录。

### 7.2 查询输入

保留当前 `query`、`component_keys` 和 `limit`，只增加少量可选过滤：

- `class_key`；
- `ascendancy_key`；
- `lifecycle_stage`；
- `scenario_tags`；
- `budget_band`；
- `include_design_memory`，用于 MVP 对照。

职业或升华未确定时，不按 memory 覆盖量替 Agent 推荐职业。MVP 首轮 benchmark 只使用已经指定
职业或升华的请求，跨职业 discovery 后移。

### 7.3 召回顺序

数据量较小时不建立新 FTS。使用：

1. visibility/status/version 过滤；
2. class/ascendancy 精确匹配；
3. component key 交集；
4. lifecycle/scenario/budget 匹配；
5. 对 title、principle 和条件做简单文本匹配；
6. 默认返回 3-6 条最相关的聚焦记录摘要，并控制总字符预算。

记录正文 `content` 不参与程序硬过滤。程序只按顶层 metadata、稳定组件 ID 和派生索引筛选；正文
由 Agent 阅读。后续若某个新维度反复需要检索，再把它提升为 typed payload 或索引字段。

结果同时返回正向原则、失败模式和评估 caveat。记忆只作为 advisory，Agent 仍需查询图、语料和 PoB。

## 8. MVP 验证

### 8.1 三个现有案例是否足够

三个 Martial Artist 变体足够：

- 校准核心机制包结构；
- 创建首批高层经验 fragment proposals；
- 验证存储、人工 review 和召回；
- 检查知识是否保留了技能、天赋、装备和操作之间的完整联动。

它们不足以证明跨职业泛化。实现可以先开始，正式增量 benchmark 前建议补：

1. 在 Monk 中选择另一个升华，提供该升华的 3 个不同变体；
2. 选择另一个职业及其自身一个升华，提供 3 个不同变体；
3. 可选再补 2-3 个 Martial Artist 的明显反例或不同路线。

### 8.2 对照方式

同一批已指定职业/升华的 BuildBrief 分别运行：

- `current_memory`：`include_design_memory=false`，过滤高层 fragment types；
- `deep_memory`：`include_design_memory=true`；
- 少量 `no_memory` 只作辅助消融。

相同 Agent、工具和 Judge，人工比较：

- 机制完整度；
- 技能职责和轮转；
- 装备/天赋联动与现实性；
- 失败条件和场景适配；
- PoB/Judge 误判审计；
- 最终 BD 的实际设计价值；
- 工具是否真的返回并使用了可读知识。

MVP 通过条件：deep-memory 在多数配对中更合理，且不降低 hard legality 和 PoB 可计算率。无需自动
胜负报告、use-event credit 或统计显著性平台。

## 9. 随案例演化提取方案

新案例很可能发现新维度。MVP 采用轻量流程：

```text
发现表达缺口
-> 在 EXTRACTION_METHOD.md 记录结构化候选
-> 人工 review
-> 更新 prompt / enum / typed condition / 可选字段或关系
-> additive migration
-> 回放固定校准案例
-> 实验查询
-> 确认有效后默认启用
```

### 9.1 先判断是否真的需要改 schema

优先顺序：

```text
更新提取 prompt/方法
-> 增加受控 role/tag
-> 增加 typed condition
-> 查询时派生
-> 增加可选字段
-> 增加关系表
```

只有前一层无法表达时才进入下一层。Agent 只能提议，不能自动修改 schema、代码或 skill。

这里的“改 schema”只影响 record kind、typed payload 和召回索引。DeepResearchRecord 的
`content` 可以立即准确表达新的安全知识单元，因此新发现不会等待 schema 修改才被保存。结构化演化
的目的，是让反复出现且确有查询价值的内容变得可过滤、可比较，而不是决定哪些研究内容有资格存在。

### 9.2 轻量启用

不再使用四级 activation 系统。只有两个状态：

- `experimental`：新字段已经可以提取和查询，但只在校准脚本或 deep-memory 测试中使用；
- `default`：回放和真实会话确认有价值后，进入默认 deep-memory 查询。

prompt-only 修正若不改变持久合同，回放通过后可以直接生效。发现问题时把字段恢复为 experimental，
停止默认查询消费，不回滚已经完成的加法数据库迁移。

`EXTRACTION_METHOD.md` 继续维护 candidate/accepted/implemented/rejected 列表。只有出现多个并行
提交者、自动提议，或文档已经明显难以去重和 review 时，才考虑迁移到 SQLite 治理表；不预设数量
阈值。

## 10. 后续能力

以下只保留方向，不在 MVP 中预先固定表结构：

- Phase 7 repair/rollback episodes；
- 后续跨阶段经验反思、效果统计和 scoped utility；
- retrieval/use/outcome 审计；
- embedding、graph expansion 和复杂 rerank；
- 动态职业设计档案；
- 稳定分析方法晋升为 skill；
- 自动 revalidation、supersede 和 memory health report。

每项能力都必须证明相对当前版本有增量收益后再设计具体合同。

## 11. 精简结论

本版 MVP 以聚焦深度研究记录为主体，并增加最小的 BuildFamily/canonical evidence 归并层；继续复用
现有 fragment、查询和 accept 流程。与上一版
相比，明确砍掉：

- 三张事件/证据治理表；
- 独立 FTS；
- 新的查询工具和高层经验/事件治理表；
- run 级 memory 使用绑定；
- discovery mode；
- 四级启用系统；
- MVP 自动 credit 和复杂证据谱系统计。

保留的只有：聚焦安全研究记录、深度核心机制包、现有索引扩展、人工审查、可读召回、版本/证据
边界、真实会话对照和轻量 schema 演化。这些足以验证 memory 是否让 Agent 产生更高水平的 BD。

## 12. 设计依据

- `docs/research/AGENT_MEMORY_SYSTEM_RESEARCH.md`
- `docs/research/BD_KNOWLEDGE.md`
- `docs/research/EXTRACTION_METHOD.md`
- Hermes Agent Memory / Skills
- MemGPT / Letta
- Mem0
- Graphiti / Zep
- Hindsight
- ExpeL / Reflexion / ReasoningBank
