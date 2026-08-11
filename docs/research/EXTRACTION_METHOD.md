# 成熟 BD 深度挖掘方法

本文档记录研究成熟 PoE2 BD 时学到的方法，直接指导后续 Phase 4 提取 schema、prompt、工具和
验收标准调整。运行态不更新本文档；新样本的方法学反馈由 `poe-bd-research-loop` 的 review/fix
通道沉淀到外部 orchestrator 的 `research-notes/`，需要进仓库的通用方法在开发态手动回填。

> 注意：本文是方法学文档，其中出现的 role / 枚举示例（如 §三、§九）是方法描述，不是运行时
> 枚举。canonical role、axis、patternType 以当前 lease 的 review-contract `allowedValues` 为准
> （代码事实源 `server/knowledge/research_models.py` 的 `COMPONENT_ROLES`），写 review 时不得
> 采用本文示例枚举。

## 当前方法版本

- 方法版本：`v2`
- 首批校准样本：3 个 90 级 Monk / Martial Artist 变体。
- `v1` 核心变化：从“组件共现摘要”升级为“职责、状态、事件链、装备分工与可兑现输出”的深度分析。
- `v2` 核心变化：增加提取/schema 扩展候选机制，让后续案例可以通过受控提案、人工 review、加法
  迁移和校准集回放逐步完善提取合同。

## 一、研究单位不是单个组件，而是可执行机制链

旧式浅层提取容易得到：

```text
主技能 + 辅助技能 + 暗金 + 若干天赋共同出现
```

深度提取必须回答：

```text
什么事件产生资源/状态
-> 什么技能或装备转换它
-> 哪个技能兑现伤害/防御
-> 如何重新回到循环起点
```

推荐最小机制链字段：

- `generator`：充能、Combo、暴击能量、尸体、冻结、重晕、击杀等来源；
- `state`：Power Charge、Combo、标记、冻结、感电地面、可斩杀、可重晕等；
- `transformer`：支持、天赋、装备或升华如何修改该状态；
- `payoff`：最终伤害、清图、恢复或防御窗口；
- `refresh`：循环如何重新启动；
- `failure_condition`：Boss 无杂兵、无法冻结、触发频率不足、Mana 中断等。

## 二、必须扫描全部技能组，不能只读 mainSocketGroup

本批样本验证了三类 snapshot trap（快照陷阱）：

- PoB 当前主技能可能是升华技能、标记技能或工具技能；
- 真正输出由多个技能承担，清图、Boss、生成器和消费器不同；
- Meta trigger 或 Hollow Form 的插入技能在 PoB 中可能显示接近 0 DPS。

Phase 4 Researcher 对每个技能组至少提取：

- active skills；
- supports；
- 是否来自天赋/装备自动授予；
- 是否启用；
- PoB 当前可计算的选中 actor；
- 职责标签：`sustained_damage`、`burst`、`clear`、`boss`、`generator`、`consumer`、
  `trigger_host`、`triggered_payload`、`mark_host`、`movement`、`defensive_window`、
  `reservation`；
- 启动条件和消费资源；
- 与其他技能组的入边/出边。

transient Researcher 必须看到完整技能组，才能判断各组件在整套系统中的职责。长期记忆允许保存对
机制成立不可缺少的完整技能 + 辅助组合，不要求机械拆成单 pair。拆分
只在每个 pair 本身就是独立知识时使用；如果拆分会丢失行为、时序、资源或触发语义，应保存完整
核心技能包。禁止的是把全部技能组、整套装备、整棵天赋和配置共同组装成第三方整角色镜像。

## 三、支持宝石需要提取“行为修改”，不能只记录兼容性

本批样本中的关键支持包括：

- Perpetual Charge：消费充能时有概率不移除，但仍获得消费收益；
- Heightened Charges：消费收益有概率翻倍；
- Culmination II：其他近战命中生成 Combo，使用支持技能时按 Combo 提高伤害并清空；
- Boundless Energy II：提高 Meta 技能能量生成；
- Energy Retention：触发时有概率返还部分能量；
- Eternal Mark：标记首次激活不被消费；
- Charged Mark：标记激活时产生感电地面；
- Brittle Armour：冻结期间受到的物理伤害转为破甲。

Phase 4 应新增或强化以下提取轴：

- `support_behavior`；
- `supported_role_change`；
- `resource_effect`；
- `timing_effect`；
- `state_created_or_preserved`；
- `downstream_payoff`。

## 四、装备研究要从“词缀清单”升级为“槽位职责”

每个装备槽至少回答：

- 它提供的是基础数值、机制启用、资源闭环、状态生成、恢复、清图扩散还是防御？
- 该职责能否被黄装或其他暗金替代？
- 该装备与哪个天赋、技能或支持形成乘法关系？
- 它是必需、强力可选、预算替代还是纯追求上限？
- 它的代价是什么：抗性、属性、Spirit、装备槽、操作或价格？

需要新增的持久知识字段建议：

- `slot_role`；
- `mechanic_enabled`；
- `required_stats`；
- `opportunity_cost`；
- `substitution_class`；
- `budget_tier`；
- `synergy_targets`；
- `craft_or_acquisition_caveat`。

不能把“暗金出现”直接解释成“暗金必要”，也不能把多词缀黄装直接解释成“平民可获得”。

## 五、天赋研究需要同时做共同骨架、变体专属与区域放大

同升华多样本应做集合比较：

- 共同 notable：可能代表职业壳或升华的稳定骨架；
- 变体专属 notable：解释具体技能、资源或防御方向；
- 仅出现在 weapon set 的节点：代表状态切换，而非始终生效；
- 由项链涂油、特殊宝石（Time-Lost Jewel、暗金宝石等）授予/放大的节点：不能和普通路径混为一谈。

建议输出：

- `shared_shell_passives`；
- `variant_passives`；
- `weapon_set_a_role` / `weapon_set_b_role`；
- `allocated_by_item`；
- `radius_jewel_amplification`；
- `passive_to_item_conversion`，例如胸甲闪避经 Spectral Ward 变成 ES。

## 六、武器组必须按状态分别分析

本批第三个样本使用两套各 22 点 weapon-set passives：一套偏长杖暴击/范围/充能，另一套偏
冷伤、混沌伤、持续时间、Combo 和混合防御。

Phase 4 不能只保存“使用了武器组天赋”。必须记录：

- 两个状态分别启用哪些节点；
- 哪些技能或装备绑定到哪个状态；
- 切换的触发方式和操作成本；
- 状态 A/B 各自的 offense、defense、resource assumptions；
- PoB/Judge 是否分别计算过两种状态。

没有双状态独立证据时，只能给 limited knowledge，不能把两套状态的最好数值同时视为常驻。

## 七、先重建实际手法，再解释面板

建议 Researcher 输出一个 `rotation_model`：

1. 战前常驻状态；
2. 接敌技能；
3. 资源/状态生成；
4. 持续输出；
5. 爆发消费；
6. 防御反应；
7. 击杀后或 Boss 无杂兵时的循环差异。

手法必须标注置信度。PoB 不提供真实动作顺序时，允许给出 `design_inference`，但必须列出推断依据
和验证任务。

## 八、数值与机制证据必须分开

当前工具容易出现：

- Cast on Critical 触发技能显示极低 DPS；
- Hollow Form、Hollow Focus、Tempest Bell 等复合机制未汇总；
- Judge 选中标记爆炸或升华技能，而不是整套主要输出；
- 新赛季特殊词缀、符文、变异、腐化或转化装备被本地黄装审计误报非法。

因此每个结论至少带一个证据等级：

- `pob_direct`：PoB 对当前 actor 直接计算；
- `pob_partial`：PoB 只覆盖部分组件；
- `corpus_mechanic`：技能/天赋/装备文本明确说明；
- `cross_sample_pattern`：多个独立样本重复；
- `researcher_inference`：组合推断；
- `needs_gameplay_validation`：需要实战；
- `tool_gap`：工具或数据覆盖不足。

Judge 结果不能覆盖 Researcher 的机制分析。发现“成熟样本全部非法”时，应优先审查语料覆盖、
特殊来源和解析规则，而不是自动把样本丢弃。

## 九、单样本、组内模式与通用规律必须分层

- 一个样本：只能写 `case_observation`。
- 同升华三个样本共同出现：可以写 `cohort_pattern`，作用域限定该样本组。
- 不同来源、不同作者、不同技能族继续重复：才考虑升级成 planner-visible 通用 pattern。
- 任何 common/usually/主流等措辞都必须有样本数、来源数、版本和去重依据。

## 十、建议调整 Phase 4 提取输出

后续 schema/prompt 可考虑增加：

- `skill_role_graph`：技能职责与相互依赖；
- `mechanic_chains`：generator/state/transformer/payoff/refresh/failure；
- `rotation_model`；
- `gear_slot_roles`；
- `passive_clusters` 与 `weapon_set_states`；
- `jewel_role` 与 `radius_amplification`；
- `ascendancy_granted_systems`；
- `budget_and_substitution`；
- `boss_without_adds_audit`；
- `modelability_matrix`；
- `tool_feedback`，记录 Judge 选技、物品审计和 PoB 读数疑点。

## 十一、每批样本的标准工作流

1. 校验来源、版本、职业、升华、等级和 source hash。
2. 解析 active skill/item/tree/config sets，排除未启用备选配置。
3. Headless PoB 读回角色状态、资源、防御和当前 main group。
4. 扫描全部技能组，并对候选输出组做独立读数。
5. 查询关键技能、支持、天赋和暗金的机制文本。
6. 对装备做槽位职责和机会成本分析。
7. 比较共同骨架、变体专属选择和 weapon-set 状态。
8. 重建 rotation 与机制链，标记直接证据和推断。
9. 记录 PoB/Judge/语料缺口，不让工具结论覆盖人工研究。
10. 按知识单元形成一组安全 `DeepResearchRecord`；每条只回答一个主要问题，同一案例通过
    `research_group_id` 聚合。不得为了迁就 fragment 字段而删减轮转、技能组合、装备职责、天赋
    结构或工具盲点，也不得把整个案例分析塞进一条记录。
11. 检查记录组覆盖范围：当前可观察、可解释或明确标为推断的有用内容是否都有归属，同时确认单条
    记录保持聚焦。单条 `content` 正文原则上不超过 400 个中文字符；英文按单词计算，原则上不超过
    250 个英文单词。标题、结构化字段、组件 ID 和证据引用不计入预算。超过时优先按独立知识单元
    拆分；只有拆分会破坏同一核心机制的因果闭环时才允许少量超出，不能机械截断。
12. 再从记录组提炼 fragment、semantic edge 和 build pattern，作为有界召回索引；索引不是深度
    记录的替代品。
13. 在开发态（而非运行态）把本轮方法学反馈回填 BD 知识文档和本文档；运行态只通过
    `poe-bd-research-loop` 的 fix 通道沉淀到 `research-notes/`。

## 十二、聚焦深度记录与召回索引必须分开

- 一次研究产生多条 `DeepResearchRecord`，单条负责一个完整知识单元，记录组共同负责案例覆盖；
- `record_kind` 和可选 `typed_payload` 负责已稳定结构，例如 skill package、mechanic chain、gear
  role、passive package、rotation、failure mode 和 tool gap；`record_kind` 不是封闭枚举；
- fragment/edge/pattern 负责检索效率，只保存可复用摘要、稳定组件和条件；
- 新发现暂时没有合适 record kind 或 typed payload 时，先使用受审查的实验类型，在一条聚焦记录中
  准确表达并提交 schema extension candidate，不能丢弃；
- 只有反复出现且确有过滤、比较或召回价值的维度，才升级为新 record kind、typed payload 或索引
  字段；
- Agent 查询时先读索引摘要，需要时再按 record ID 深读少量相关记录，不默认读取整个研究组。

## 本批研究暴露的 Phase 4 缺口

- 当前浅层 fragment 主要记录“多个组件一起出现”，不足以指导 Agent 重建玩法。
- 现有技能 role 粒度不够，缺少 generator/consumer/trigger host/triggered payload/defensive window。
- support 提取缺少资源、时序和状态改变。
- 装备提取缺少槽位职责、替代关系、预算和机会成本。
- 缺少 weapon-set 状态级别的知识合同。
- 缺少完整 rotation、Boss 无杂兵审计和操作复杂度。
- modelability caveat 仍停留在技能级，尚未覆盖整条机制链。
- 工具反馈没有系统记录“Judge 选错输出组件”和“特殊词缀被误报非法”。

## 运行态校准：Witch / Abyssal Lich / Barrage 单案例

首次真实 `/poe-bd-research` 单案例运行虽然工程流程成功，但只产出“投射、暴击、元素异常可能
协同”“资源和防御需复验”等泛泛记录，具体技能、辅助、装备、局部天赋、珠宝、升华联动和轮转均
为空。复盘确认不是方法文档缺失，而是方法没有进入 worker prompt，且 fallback 合同要求无 resolver
工具的 worker 自己提供稳定 ID，迫使其删除具体组件。

本次已完成以下校准：

- 将本文核心步骤、一个脱敏合格机制链示例和一个浅层反例内联到标准 Researcher prompt；
- fallback 组件只要求名称、职责和 resolver 查询词，稳定 ID 由 accept gate 回填；
- 具体 record kind 必须锚定至少一个已解析组件，整案必须至少产生一条具体机制记录；
- 浅层整案在写库前拒绝，不能只存若干通用 caveat 后仍显示成功；
- patch、天赋树和应用当前 PoB 版本枚举由队列运行时注入，worker 不负责从案例猜版本；缺失或
  `unknown` 按当前值归一；
- acceptance 按真实原因区分 schema、resolver、source coverage 和 research depth。

这些是最低质量保障，不是对未来字段的封顶。后续样本仍应继续发现装备职责、天赋结构、珠宝、
升华与复杂轮转中尚未表达的维度，并按本文扩展流程局部演进。

## 提取/schema 扩展候选

新案例发现当前提取合同无法准确表达的信息时，先记录扩展候选，不立即修改 schema。先判断它属于：

1. 现有字段已经能表达，只需更新研究 prompt 或方法；
2. 新的受控 role/tag；
3. 需要参与程序过滤的新 typed requirement；
4. 无法从现有字段派生的新可选字段；
5. 需要独立生命周期的新关系或事件；
6. 可以由现有数据查询时派生的视图。

每条候选使用以下模板：

```text
proposalId:
status: candidate | accepted | implemented | rejected
discoveredInCases:
expressionGap:
proposedChange: prompt_only | controlled_value | typed_field | relation | derived_view
targetArtifact:
safeExample:
expectedUse:
migrationOrBackfill:
risk:
activationState: experimental | default
reviewSummary:
```

约束：

- 不允许用开放 `extensions` JSON 绕过 strict schema；
- 单案例可以触发 prompt-only 或明确机制枚举候选；新增字段/关系通常需要更多独立案例或明确官方
  机制依据；
- 优先更新 prompt、增加受控值、typed condition 或派生视图，最后才新增字段/表；
- accepted 候选实施后必须回放固定校准集，并确认旧数据仍可读取；
- 缺少新字段的旧记录只产生 coverage caveat，不能自动成为反例；
- 扩展候选不进入 Architect 普通 memory 召回。
- `experimental` 只在校准或 deep-memory 测试中使用；`default` 才进入默认 deep-memory 查询；
- prompt-only 修正若不改变持久合同，校准集回放通过后可以直接生效。

### Candidate

当前为空。后续每批案例若发现新维度，按上述模板追加。

### Accepted

当前为空。

### Implemented

当前为空。

### Rejected

当前为空。
