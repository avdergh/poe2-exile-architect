# Agent 长期记忆与经验进化系统调研

## 1. 调研目标

本文调研截至 2026-07-13 较有代表性的开源 Agent 记忆系统和研究路线，重点回答：

- Agent 应该保存事实、经历、原则、策略还是技能；
- 一次成功或失败如何逐步沉淀成可复用经验；
- 如何在长期积累后仍保持可检索、可解释、可撤销和版本安全；
- 如何让记忆帮助 Agent 形成设计判断，而不是只向提示词中堆更多检索片段；
- 哪些设计适合 PoE2 BD 创造，哪些方案虽然先进但不适合直接照搬。

本文是前置调研，不是本项目最终 memory schema 或 Phase 7/8 实现方案。

## 2. 核心结论

当前较成熟的系统并不存在一个统一的“最佳记忆数据库”。高质量 Agent 记忆通常由多个层级共同
组成：

1. **工作记忆**：本轮目标、当前状态、未解决问题和必要约束，容量小且随任务结束清理。
2. **语义记忆**：相对稳定的事实、机制、概念和关系，例如技能、装备、天赋之间的作用关系。
3. **情景记忆**：一次任务中发生了什么、采取了什么策略、为什么失败或成功。
4. **经验或心智模型**：跨多个情景反思后形成的取舍原则、失败模式、设计哲学和因果解释。
5. **程序或技能记忆**：已经被证明有效的操作流程、研究方法、修复策略或可组合技能。

最值得本项目吸收的共识是：

- 原始经历不能直接升级成稳定原则；
- 检索不应只依赖向量相似度，还需要结构、时间、版本、任务范围和证据质量；
- 记忆写入与记忆使用必须分开治理；
- 反思产物必须保留来源和反例，不能覆盖原始证据；
- “成功过”不代表“普遍正确”，必须记录适用条件和失败条件；
- 高价值经验应逐渐从事件日志压缩成原则，再按需要编译成 Agent 可执行的技能；
- 记忆是否有效必须通过任务结果的 A/B benchmark 证明，不能用“存了很多条”作为成功标准。

## 3. 代表性系统

### 3.1 Hermes Agent：有限核心记忆、会话档案和可进化技能

[Hermes Agent](https://github.com/NousResearch/hermes-agent) 将长期学习拆成三个明显不同的层级：

- `MEMORY.md` 和 `USER.md` 是容量严格受限、每个会话都注入提示词的核心记忆；
- 完整历史会话进入 SQLite FTS5，需要时再搜索，不占用每轮上下文；
- 复杂任务、重复纠正和稳定工作习惯可以被后台 review 提炼成记忆，或进一步写成可按需加载的
  skill。

值得关注的设计：

- 核心记忆有硬容量限制，迫使 Agent 合并、压缩和删除低价值内容；
- 核心记忆是会话开始时的冻结快照，写入不会不断扰动当前提示词；
- 记忆与技能写入支持 staging、diff、approve/reject，降低错误经验污染未来行为的风险；
- skill 采用渐进披露，仅在相关任务中加载；
- 外部深层记忆提供者与内置核心记忆并行工作，而不是互相替代。

对本项目的启发：BD Agent 也需要一个很小的“当前职业设计原则摘要”，但完整研究记录、失败轨迹
和组件关系不应该全部常驻提示词。稳定方法可以成为可按职业或机制加载的设计技能。

局限：Hermes 的核心记忆主要面向用户偏好和通用工作习惯，缺少 PoE2 所需的版本、Judge 证据、
场景和机制链合同，不能直接作为领域记忆实现。

### 3.2 Letta / MemGPT：分层上下文与 Agent 自主管理

[MemGPT](https://arxiv.org/abs/2310.08560) 及其工程化延续
[Letta](https://github.com/letta-ai/letta) 把有限上下文视为操作系统中的快速内存，将记忆分为：

- 始终位于上下文中的 core memory；
- 可搜索、容量更大的 archival memory；
- 当前消息和历史上下文。

Agent 可以通过工具主动修改核心 memory block，或把低频内容换出到长期存储。

对本项目的启发：生成 BD 时不应一次查询并塞入所有职业经验，而应先提供很小的职业/目标设计
摘要，再让 Agent 按当前候选机制主动检索更深的装备、技能、失败案例和版本证据。

局限：它主要解决上下文容量和长期对话问题，本身不判断经验是否可靠，也不提供从多个 BD 成败
案例中形成设计哲学的晋升机制。

### 3.3 Mem0：面向生产场景的事实提取、合并与个性化检索

[Mem0](https://github.com/mem0ai/mem0) 侧重从对话中动态提取显著事实，并对已有记忆执行新增、更新、
删除或保持等操作。其增强方案加入图结构，以表达实体间关系。系统强调低 token 成本、快速检索、
用户/Agent/run 作用域和可追踪的 memory history。

值得借鉴：

- 写入不是无条件 append，而是先与已有记忆比较后决定合并或替换；
- 通过作用域与 metadata 隔离不同用户、Agent 和任务；
- 记忆更新保留历史，有利于审计错误覆盖；
- 提取、存储和检索是可替换组件。

对本项目的启发：同一职业原则不应该不断产生近义重复条目；新赛季证据可以 supersede 旧结论，
但旧结论仍应保留历史和版本范围。

局限：其默认目标是对话事实和个性化，不足以表达“某策略在什么 Judge 证据、预算、场景和机制
条件下成功”。若直接套用，容易把 Agent 推断当成用户事实保存。

### 3.4 LangMem：语义、情景、程序记忆与双写入路径

[LangMem](https://github.com/langchain-ai/langmem) 明确区分：

- semantic memory：事实和概念；
- episodic memory：过去的任务、动作和结果；
- procedural memory：改变 Agent 如何执行任务的规则或 prompt。

它还区分两种写入路径：

- hot path：当前交互中立即写入，反馈快但增加延迟并容易受当前上下文影响；
- background：在任务结束后异步反思和整理，适合合并、抽象和跨案例提炼。

语义信息还可以保存为一个不断更新的 profile，或保存为多条可独立检索的 collection。

对本项目的启发：

- Judge/Critic 每轮的事实和 gap 属于情景记忆，不应直接变成职业哲学；
- 跨样本形成的职业原则属于语义或经验记忆；
- “分析成熟 BD 的方法”“遇到主技能误选时如何审计”等属于程序记忆；
- Phase 7 当轮只记录结构化事件，较重的经验提炼可以在候选结束后处理。

### 3.5 Graphiti / Zep：双时间图与可失效关系

[Graphiti](https://github.com/getzep/graphiti) 是 [Zep](https://arxiv.org/abs/2501.13956) 的时间化知识图
核心。它将输入保存为 episodes，并抽取 entities 和 relationships。重要能力包括：

- 同时记录事实在现实世界中的有效时间和系统获知该事实的时间；
- 新信息与旧信息冲突时让旧关系失效，但保留历史；
- 混合使用语义、关键词和图搜索，并可按图距离 rerank；
- 支持持续增量更新，而不是定期重建整张图。

对本项目的启发：PoE2 经验天然具有赛季时间性。某装备联动可能在 0.5 有效、0.6 失效；系统需要
回答“当前版本适用什么”和“过去为什么这样设计”，而不是直接覆盖旧边。具体组件组合和机制链
非常适合用这种有时间范围的图表达。

局限：图擅长表达关系和多跳检索，不等于能自动形成高质量设计哲学。没有独立 evidence gate 时，
LLM 抽取出的错误关系仍然会污染图。

### 3.6 Cognee：图、向量、会话缓存与改进管线

[Cognee](https://github.com/topoteretes/cognee) 提供 `remember`、`recall`、`forget`、`improve` 等操作，
将输入转换成带 ontology 的知识图和向量索引。它还区分快速 session memory 与后台同步到永久图的
长期记忆。

对本项目的启发：短期生成过程与长期可信知识应使用不同存储层；会话中的工具轨迹可以先保存在
临时层，只有经过 Judge、Critic、人工或跨案例验证的结果才进入永久层。

局限：作为通用知识基础设施，它的 ingestion 和 ontology 生成较重。我们的物理图已有严格静态
来源和 typed endpoint 约束，不宜让通用 cognify 管线自动改写现有物理图。

### 3.7 Hindsight：世界事实、经历与心智模型

[Hindsight](https://github.com/vectorize-io/hindsight) 的分层与本项目需求最接近：

- World：关于世界的事实；
- Experiences：Agent 自己经历过的事件和结果；
- Mental Models：通过反思事实和经历形成的理解、判断和高层认识。

它对外提供三个主要动作：

- retain：保存事实或经历；
- recall：通过向量、BM25、图和时间检索并融合结果；
- reflect：对已有记忆做更深分析，形成新的观察和心智模型。

检索结果使用 reciprocal rank fusion 合并，再通过 reranker 排序，并按 token 预算裁剪。

对本项目的启发：

- PoE2 机制说明和静态规则属于 World；
- 某次 BD 生成、修改、Judge 反馈和实战反馈属于 Experiences；
- “该职业应先建立资源闭环，再选择消费技能”“高频暴击可作为触发与输出的共同总线”等属于
  Mental Models。

这正好解释了为什么单纯把所有内容放进图数据库不够：图可以存关系，但 Agent 还需要跨案例形成的
领域心智模型。

局限：通用 reflect 仍由 LLM 完成。若没有版本、证据、反例和 promotion gate，心智模型可能只是
写得漂亮的错误总结。

### 3.8 MemOS：将记忆作为一等资源治理

[MemOS](https://github.com/MemTensor/MemOS) 和其
[论文](https://arxiv.org/abs/2505.22101) 将记忆分成 plaintext、activation 和 parametric memory，
并以 MemCube 作为统一、可追踪、可迁移的抽象，由调度层管理不同记忆的生命周期。

对本项目的启发：记忆应有统一身份、所有权、版本、状态和生命周期；未来更换向量库或图后端时，
领域 memory contract 不应随底层实现改变。

局限：参数记忆和跨模型记忆迁移远超当前项目需要。现阶段引入完整 memory operating system 会使
实现过重，且与外部 Agent 主导的架构不匹配。

### 3.9 A-MEM：动态笔记网络与记忆演化

[A-MEM](https://github.com/WujiangXu/A-mem) 基于 Zettelkasten 思想。每条新记忆被整理成包含上下文、
关键词和标签的结构化笔记，再与历史记忆建立连接；新记忆还可以触发已有记忆的上下文和属性更新。

对本项目的启发：经验不一定只能挂在预定义职业目录下。新的构筑可能把过去分离的“暴击总线”、
“充能消费”“可攻击升华目标”连接成一个新的跨职业设计模式。

局限：允许新记忆主动改写旧记忆具有较高污染风险。本项目更适合 append evidence、建立 supersede
关系或生成新的综合卡片，而不是静默重写历史结论。

### 3.10 HippoRAG：图上的关联扩散检索

[HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG) 用知识图和 Personalized PageRank 做单次多跳
检索，目标是从少量查询实体激活相关知识簇。

对本项目的启发：当 Agent 查询“Martial Artist 的充能型 Boss 构筑”时，不应只返回文本最相似
的几条记录，还可以从职业、升华、资源、消费技能、无杂兵失败条件等种子沿图扩散，召回跨文档但
结构相关的经验。

局限：它主要优化 recall，不处理经验写入质量、反思晋升或技能形成。

## 4. 从经历中进化的研究路线

### 4.1 Generative Agents：记忆流、重要性和高层反思

[Generative Agents](https://arxiv.org/abs/2304.03442) 保存完整经验流，并综合 relevance、recency 和
importance 选择记忆。积累到一定程度后再生成更高层 reflections，供后续计划使用。

可借鉴点：不是每次经历都立即总结原则；反思应在证据积累或重要性达到阈值后触发。对 BD 系统，
单个样本的装备选择只能是观察，多个独立样本和生成结果共同支持后，才形成职业经验。

### 4.2 Reflexion：将失败反馈保存为语言经验

[Reflexion](https://arxiv.org/abs/2303.11366) 不更新模型参数，而是根据外部或内部反馈生成文字反思，
存入 episodic memory，供下一次尝试参考。

可借鉴点：Phase 7 的 Judge/Critic 失败可以形成紧凑的“上轮为什么失败、下轮避免什么”记录，
比重新塞入完整轨迹更有效。

风险：一次错误 Judge 或错误自我解释会被放大。因此反思必须绑定 snapshot、证据等级、
modelability caveat 和是否真的改善了下一轮结果。

### 4.3 ExpeL：从多条轨迹提取可迁移经验

[ExpeL](https://arxiv.org/abs/2308.10144) 从一组训练任务的成功与失败经历中抽取自然语言 insights，
推理时同时召回经验和相关案例。它强调不修改模型参数也能随经验积累提升表现。

这是本项目“构筑哲学记忆”最直接的研究参照：

- 单轮 repair 只产生情景记录；
- 多个相似 brief、成熟 BD 和生成结果一起比较；
- 从成功与失败差异中提取有条件的经验；
- 新任务召回经验原则和少量支持案例，而不是完整旧 BD。

### 4.4 Voyager：把稳定经验编译为可组合技能

[Voyager](https://github.com/MineDojo/Voyager) 保存不断增长的可执行技能库，并结合环境反馈、执行错误
和自我验证持续改进技能。技能是可解释、可组合、跨任务复用的程序记忆。

对本项目的启发不是让程序自动创造 BD，而是将稳定经验变成 Agent 可调用的设计技能，例如：

- 审计充能构筑的生成、消费、保留和 Boss 无杂兵循环；
- 分析多技能清图/Boss/触发职责；
- 审计黄装预算和暗金机会成本；
- 对 weapon-set 双状态分别建立证据。

技能应规范 Agent 如何研究和验证，不应替 Agent 自动选择最终 BD。

### 4.5 Hermes 的后台自我改进：记忆与技能分流

Hermes 的后台 review 会判断一次经验更适合成为紧凑记忆，还是成为/修改一个程序 skill，并可要求
人工批准。这提供了一条实际工程路径：

```text
一次经历
-> 是否值得保存
-> 事实/偏好进入 memory
-> 重复、可执行的方法进入 skill
-> 写入前可审查
```

本项目可进一步加入 Judge 与版本证据门槛，避免仅凭 Agent 自评完成晋升。

## 5. 横向比较

| 系统/路线 | 主要记忆形态 | 写入/进化特点 | 检索特点 | 最适合借鉴的部分 | 主要风险 |
| --- | --- | --- | --- | --- | --- |
| Hermes | 小型核心记忆、会话档案、skills | 后台 review，记忆/技能分流，可审批 | 常驻摘要 + FTS + 按需 skill | 有限核心记忆、程序经验、写入审批 | 领域证据合同较弱 |
| Letta/MemGPT | core + archival | Agent 主动换入换出 | 核心常驻，档案按需搜索 | 上下文分层和主动检索 | 不判断经验是否正确 |
| Mem0 | 原子事实、向量/图、历史 | 提取后 ADD/UPDATE/DELETE | metadata + semantic/graph | 去重、合并、作用域和历史 | 容易把推断当事实 |
| LangMem | semantic/episodic/procedural | hot path 或后台写入 | profile 或 collection | 记忆类型与写入路径分类 | 需要自行实现领域 gate |
| Graphiti/Zep | episode、实体、时间化关系 | 冲突失效并保留历史 | 语义 + 关键词 + 图 + rerank | 赛季版本、关系演化、多跳 | LLM 抽取错误仍会入图 |
| Cognee | session cache、图、向量、ontology | remember/improve 管线 | 自动路由 recall | 临时层到永久层同步 | 对现有严格物理图过重 |
| Hindsight | World、Experiences、Mental Models | retain + reflect | 向量/BM25/图/时间融合 | 事实、经历、设计哲学分层 | 反思仍可能自洽但错误 |
| MemOS | 多形态 MemCube | 统一生命周期和调度 | 按任务调度多类记忆 | 后端无关合同与治理 | 当前阶段过度设计 |
| A-MEM | 动态互联笔记 | 新笔记连接并演化旧记忆 | 语义和链接网络 | 跨类别发现新联系 | 静默改写历史风险高 |
| HippoRAG | 实体图索引 | 以知识整合为主 | PPR 多跳扩散 | 从机制种子召回知识簇 | 不解决写入与反思质量 |
| Reflexion | 失败反思情景 | 每次反馈后生成语言反思 | 后续 trial 注入 | Phase 7 内部 retry 摘要 | 错误反馈会被强化 |
| ExpeL | 轨迹 + 跨案例 insights | 从成功/失败集合提炼 | 经验原则 + 相似案例 | 职业经验和设计哲学 | 抽象过度或样本污染 |
| Voyager | 可执行技能库 | 环境反馈和验证后改进 | 任务相关 skill retrieval | 分析/修复方法程序化 | 不能让技能接管 BD 创造 |

## 6. 记忆系统的共同难题

### 6.1 写入比检索更危险

检索错误通常只影响一次任务，错误长期记忆会持续影响未来所有任务。因此应优先设计：

- 什么事件有资格产生 memory candidate；
- 谁可以批准晋升；
- 如何保留原始证据和反例；
- 如何撤销、降权或标记过期；
- 新赛季如何失效和重验证。

### 6.2 相似不等于适用

向量检索可能因为文本相似召回错误经验。例如两个构筑都使用暴击和 Power Charge，但一个依赖
清图击杀，另一个需要稳定 Boss 产球。召回必须额外匹配：

- 职业/升华；
- 生命周期阶段；
- 清图、Boss、攻坚等场景；
- 预算和获取条件；
- patch/tree/PoB 版本；
- 机制链的 generator、state、payoff 和 failure condition；
- modelability 与证据等级。

### 6.3 反思容易形成“漂亮但错误”的哲学

LLM 很擅长为偶然共现编写因果解释。高层经验必须区分：

- 直接机制文本；
- PoB/Judge 可验证结果；
- 成熟样本组内模式；
- Agent 设计推断；
- 实战或人工反馈；
- 尚未解释的工具缺口。

经验应允许带反例、适用范围和待验证条件，不能只保存一句肯定式结论。

### 6.4 记忆越多不代表 Agent 越强

过多记忆会造成召回污染、提示词拥挤和思路固化。需要：

- token budget；
- 多样性控制；
- 冲突和反例注入；
- 旧版本 decay；
- 同义合并；
- 使用频率不能替代成功证据；
- no-memory 与 memory-assisted A/B 验证。

### 6.5 成功经验可能压制创造力

成熟经验只能作为 prior，不应成为模板或硬规则。Agent 仍需探索未见组合；记忆应说明“为什么这条
路线曾有效”和“在哪些条件下不适用”，而不是告诉 Agent 只能重复历史最优解。

## 7. 对 PoE2 BD 场景的初步映射

以下只是调研后的概念映射，不是最终 schema：

| PoE2 内容 | 更适合的记忆层 |
| --- | --- |
| 技能、装备、support、天赋、词缀的静态事实 | physical/semantic graph |
| 小粒度技能组合、装备联动、机制链 | 有版本和证据的 semantic graph edge/pattern |
| 一次成熟 BD 分析 | research episode |
| 一次生成、Judge、repair、rollback 轨迹 | generation episode |
| 一次失败为何发生、如何修复 | episodic reflection |
| 某职业/升华的设计取舍、常见资源哲学、失败条件 | class-scoped mental model |
| 跨职业可迁移的机制设计原则 | domain mental model |
| 如何分析多技能、充能、黄装预算、武器组状态 | procedural design skill |
| 当前生成必须始终看到的极少数原则 | bounded working/core memory |

用户提出的“具体组合进入图、综合经验按职业整理”方向总体合理，但根据调研还需要补两个层：

- **情景证据层**：保留经验从哪些成熟样本、生成轮次、Judge 和人工反馈得出；
- **程序技能层**：把稳定的分析与修复方法变成 Agent 可按需加载的操作规程。

否则综合经验很容易失去来源，图中的组合也很难解释为什么值得使用。

## 8. 后续设计时建议重点决策的问题

下一轮针对本项目设计 memory 系统时，应先确定这些问题，而不是先选向量库：

1. 记忆类型：事实、情景、反思、心智模型、技能分别有哪些正式合同。
2. 作用域：职业、升华、技能族、场景、预算、生命周期和版本如何组合。
3. 晋升：单案例观察如何升级成组内模式、职业经验、跨职业原则或 skill。
4. 反例：失败案例和相反证据如何阻止过度泛化。
5. 写入者：Researcher、Architect、Critic、Judge、人工反馈各能提议什么，谁能最终接受。
6. 检索：如何联合 typed graph、FTS、向量、时间过滤、因果/机制链和 rerank。
7. 上下文：哪些内容始终注入，哪些必须由 Agent 按需查询。
8. 更新：新赛季是删除、降权、标记 stale、建立 supersede，还是触发 revalidation。
9. 治理：如何审查、回滚、解释某条经验为何进入本次生成。
10. 验证：memory-assisted 是否在固定 BuildBrief 上改善合法率、Judge 质量、人工评分和创新性。

## 9. 初步判断

本项目不适合直接安装某个通用 memory 库后把所有内容交给它管理。更合理的方向可能是组合多种
成熟思想：

- 保留当前 source-backed typed graph，承载具体组件与小粒度机制关系；
- 借鉴 Hindsight/ExpeL，增加经历到职业心智模型的反思与晋升层；
- 借鉴 Hermes/Voyager，将稳定方法沉淀为按需加载的程序技能；
- 借鉴 Graphiti，为语义关系和经验增加有效时间、失效与 supersede 历史；
- 借鉴 Letta/Hermes，只让少量高价值原则进入核心上下文，其余由 Agent 主动检索；
- 借鉴 Mem0/A-MEM 做去重、连接和演化，但禁止无证据静默重写；
- 借鉴 MemOS，将领域合同与底层图、向量或关系数据库实现解耦。

真正的“进化”不应定义为记忆条目越来越多，而应定义为：在相似目标上，Agent 能更快提出更合理
的机制空间，更少重复已知失败，更好解释设计取舍，同时仍能探索与历史经验不同的新路线。

## 10. 主要来源

- [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- [Hermes Persistent Memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)
- [Hermes Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [MemGPT](https://arxiv.org/abs/2310.08560)
- [Letta](https://github.com/letta-ai/letta)
- [Mem0](https://github.com/mem0ai/mem0) / [Mem0 paper](https://arxiv.org/abs/2504.19413)
- [LangMem](https://github.com/langchain-ai/langmem)
- [Graphiti](https://github.com/getzep/graphiti) / [Zep paper](https://arxiv.org/abs/2501.13956)
- [Cognee](https://github.com/topoteretes/cognee)
- [Hindsight](https://github.com/vectorize-io/hindsight)
- [MemOS](https://github.com/MemTensor/MemOS) / [MemOS paper](https://arxiv.org/abs/2505.22101)
- [A-MEM](https://github.com/WujiangXu/A-mem) / [A-MEM paper](https://arxiv.org/abs/2502.12110)
- [HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG) / [HippoRAG paper](https://arxiv.org/abs/2405.14831)
- [Generative Agents](https://arxiv.org/abs/2304.03442)
- [Reflexion](https://arxiv.org/abs/2303.11366)
- [ExpeL](https://arxiv.org/abs/2308.10144)
- [Voyager](https://github.com/MineDojo/Voyager) / [Voyager paper](https://arxiv.org/abs/2305.16291)
