# 构筑实装与质量收尾

Blueprint accepted 后读取。按“机制来源 → 可执行基础版本 → 核心可行性 → 质量实验 → 最终来源辅助”
推进；配置冻结、状态绑定审计和Judge见[验证与恢复](validation-and-recovery.md)。组件采用依据和
必需unique判定见[Research使用](research-use.md)，不要在装备阶段另选一个未审读的设计来源。

## 1. 小事务与状态所有权

`apply_build_mutation_batch(batch_kind=..., ...)` 只执行Agent已决定的机械修改，不能装入搜索、
optimizer或依赖新group fingerprint才能决定的编辑。不要把整个BD混进一个批次。

| 职能 | 本阶段用途 |
| --- | --- |
| `bootstrap` | `new_build`可为首项，设置职业、升华及最终目标等级 |
| `mechanism_shell` | 普通宝石主输出时恰含一次`set_main_skill`，只初始化一次，并设置显式武器槽；副技能留给来源盘点后的skill_loadout |
| `required_gear` | 本流程用于已决定的机制武器；非武器来源件用独立`equip_item/equip_jewel` |
| `skill_loadout` | 来源盘点后仍缺失职责的技能组 |
| `passive_delta` | Agent选定的局部节点分配/取消，不全局重排 |
| `ordinary_gear` | 机制件锁定后补普通装备，使用工具允许的显式槽位 |
| `config` | 每批一次`set_config`；最终战斗假设在验证阶段锁定 |

只有以`new_build`开始的bootstrap可省略`expected_state_hash`；其后串联上一操作的
`outputStateHash/stateHash`。独立装备、技能组和config工具也修改同一活动状态；出现
`build_state_conflict`时核对actualStateHash，不沿用旧hash。装备/珠宝使用显式slot/socket。
箭袋是例外：不放入mutation批次；独立`equip_item`省略slot自动识别引擎`Weapon 2`，不能传`Quiver`。

失败只回滚当前职能事务；`rolledBack=true`才表示恢复成功。`recoveryRequired=true`时停止普通
事务，通过`new_build` bootstrap显式恢复。`craft_item`或镶嵌工具返回的特殊来源
`craftReceiptRef`在独立/批量`equip_item`时原样传入，不能手写或省略。

## 2. 先落实机制来源，再补技能职责

1. 先设置最终目标等级，落实Blueprint及组件决策采用的非可选`unique_enabler`、会授予技能的
   升华/核心被动。逐件读当前静态全文并验证；不能把整个adopted package的每个组件自动视为采用。
2. 调用`list_skill_groups`，按实际source、slot、active effect和enabled状态盘点已有清图、Boss、
   setup/payoff、persistent和utility职责。已有真实来源满足职责就直接使用；被选来源disabled时
   用新鲜fingerprint先启用，不把它误判为缺失。
3. 装备/升华/被动提供主输出时跳过`mechanism_shell`，落实提供者后用
   `set_skill_group_state(make_main=true, ...)`选择真实来源组。禁止创建普通宝石代理，或为编辑性、
   辅助审计和Spirit比例禁用正确来源。
4. 多个来源承担同职责时，按等级、辅助能力、资源成本、武器状态及用途选择；没有不同职责/状态
   证据时不静默保留重复组。只有缺失职责进入`skill_loadout`；局部修改用
   `list_skill_groups`后的`replace_skill_group/remove_skill_group/set_skill_group_state`。

明确说明主技能如何清图，稀有怪/Boss由哪个技能或setup/payoff组合处理，不把当前计算组当作整个
BD唯一主技能。未显式指定等级的主动宝石使用角色可合法装备的最高基础等级；显式超需求会回滚，
最终仍复读基础等级。装备/天赋`+levels`可以提高计算等级，不能因此下调合法基础宝石。

已知会授予/移除技能的装备、升华、被动变化，或来源物品经Rune/词条操作重装后，立即重新盘点。
普通数值换装、未触及来源物品的Rune变化不额外触发来源盘点。不要跨换装复用group index、
fingerprint、来源辅助或审计；最终来源辅助写入在第6节执行。

## 3. 基础装备与药剂

Family必需暗金/暗金珠宝先于普通黄装逐件读取、实测、锁定，写组件级
`adopted/caveated/rejected`。当前版本不可用时写`rejected`并说明unavailable原因；完整准入与拒绝
条件在Research reference。黄装围绕锁定机制件补属性、Spirit、抗性、防御与资源。

| 内容阶段 | `plan_gear(stage=...)` | 元素/非CI混沌规划目标 |
| --- | --- | --- |
| 剧情 | `campaign` | 30% / 0% |
| 刚进图 | `maps_entry` | 50% / 30% |
| 终局 | `endgame` | 60% / 30% |

规划目标不替代按实际等级执行的Judge/Lifecycle门槛。达到阶段目标后把后缀留给实际输出、属性、
资源等缺口；明确内容需求才覆盖到75%，不是各阶段都要求满抗。`scaffold_gear`仅供中间态计算，
最终必须替换全部`Scaffold ...`占位物品。

`plan_gear/optimize_item/craft_item/rank_upgrades`使用`acquisition_profile="realistic_trade"`，
先声明`locked_slots`。普通黄装每件最多5条显式、最多2条深T1；按实际roll文本计数，来源T2不能
豁免重叠T1数值。显式`theoretical`只作升级目标，不能进入推荐主方案。`Item Level`与底材需求
匹配目标阶段，词缀来自该物品等级池；`generated_item_attainability_check_failed`后重新规划。
低配替代和升级顺序作为同一方案的建议，不生成三套独立PoB。

此时先实际装备基础生命/魔力药剂。Family指定暗金药剂时直接验证；普通药剂用
`optimize_flask(slot, base?, ilvl, strategy)`，按职责选`recovery/sustain/instant`，证据不足默认
`recovery`。Flask是Magic最多1前缀/1后缀，不套普通Rare的3/3链。完成第一版职业、升华、等级、
技能组、必要装备、核心天赋和基础配置后进入核心检查，不能拿空骨架验收。

## 4. 核心可行性：在护符、额外珠宝和镶嵌精修前

用现有`list_skill_groups/get_build_stats/get_defenses`及精确机制/等级查询，不新增评分器。
可编辑、可建模核心组先放入可计算临时辅助；不可写来源保留真实组、intended supports和能力缺口。

- 核对来源职责没有未解释重复，武器与技能兼容，属性满足已装备物品和已启用宝石，Spirit未超额
  保留。属性不足、来源冲突、武器不兼容、超额保留必须先修；还未采用的未来换装预算不是当前非法。
- 对每个清图/Boss/setup-payoff核心组，重新读取fingerprint并用`set_skill_group_state(make_main=true)`
  临时选中，再读该组成本/速率/恢复；切换后读取新状态，结束时恢复原主组，不套用另一组的消耗。
- Mana/Life都检查每次固定、每次百分比、每秒固定、每秒百分比成本。`*LeechGainRate`已含On-Hit，
  不再加`*OnHitRate`；未建模Mana恢复不能抵消确定性Life失败。不要按“总蓝是单次耗蓝固定倍数”删辅助。
- 铺弹、引爆、蓄力和走位按完整循环的动作、成本、恢复窗口判断。循环时长/恢复无法证明时保留
  unknown与验证任务，不能用持续按键模型判死或伪造通过。当前工具没有受检循环续航回执时，
  setup/payoff缺口仍为candidate，非PoB说明不能直接将其升级recommended。
- 记录Physical/Fire/Cold/Lightning/Chaos的`MaximumHitTaken`；缺值标unknown。用户未指定一击线
  时只报事实，不自设统一硬门槛。只有证实的机制失败才返回核心方案；未建模但有验证路径的机制
  继续推进并保留具名缺口。

PoB未覆盖恢复时先复核当前corpus/Graph/Research，必要时核对机制或实战证据，表述为“需验证
未建模恢复覆盖”，不能仅据静态缺口说会断蓝。只有普通魔力瓶承担持续缺口且无其他覆盖时才视为
真实失败，再按辅助、天赋、技能、装备、护符、镶嵌、药剂或轮转修复。外部证据不能冒充Research
premise的deep-read解决记录，相关引用规则见[Research使用](research-use.md)。

## 5. 主动质量实验与完整装备系统

技能采用依据是机制价值、职责、配套与条件，不是PoB是否方便计算。明确的未建模状态不按零收益
处理，也不降低采用优先级；可用有依据的Agent情景DPS粗估参与比较。粗估与PoB指标分开，说明
覆盖、重叠与重复计数，缺依据时保持未知。数值排序工具无法覆盖完整机制时保留真实配套。

合法且机制完整的基础版本形成后，首次Judge前完成一次适用质量收尾，比较高影响武器、辅助组合、
局部天赋、珠宝、镶嵌和战斗配置。Judge报警不是探索前提；目标包括伤害、防御、续航、操作和装备
可行性。仅去重相同state hash、目标和参数的调用；新假设/目标/状态允许继续比较。

| 方向 | 操作与采用依据 |
| --- | --- |
| 精确搜索 | `search_passives/search_mods/search_items`不设固定候选条数上限；默认返回量不是上限。选定后用`get_passive/get_item`等精确详情，必要时扩展结果或改查询。天赋搜索与详情均由Build服务读取当前状态 |
| 武器/黄装/天赋 | 用单槽`optimize_item/craft_item`、`plan_gear`和局部`optimize_passives`；禁止`optimize_build`与`optimize_passives(reset=true, points=0)`全局重排 |
| 辅助 | 对每个用户可编辑组及`noSupports=false`的核心`Tree:*`/`Item:*`组，用group_index/新鲜fingerprint调用`optimize_supports`，按职责比较完整当前与候选组合；同目标完整测量、合法性不回归且净正收益才要求修改，可以纯移除辅助，不机械要求五辅 |
| Spirit机会成本 | 定向查询该等级的精魂/保留搭配，验证等级、Spirit、实际作用。使用率不高于80%时实测与Blueprint职责一致的持久技能：有正收益且不破坏机制则采用；无可容纳/有价值选项则记录留余量理由，不塞无关技能凑比例 |
| 普通暗金 | `relevant_uniques`发现后用`search_uniques/get_unique`读全文；静态排除不兼容项后最多实测3个最高相关候选。属性/抗性被破坏时，最多围绕该件重规划一次黄装后决定，不展开分支树；Family必需件不受3件限制 |
| 珠宝 | 暗金/radius/Time-Lost都位置化评估；Time-Lost先`search_mods`确认精确mod ID，再`optimize_jewel(selected_mod_ids=...)`构造。已分配槽替换用`evaluate_jewel_socket`，普通rare珠宝在Family暗金珠宝之后评估 |
| 护符 | 容量读最终PoB `CharmLimit`并封顶3；腰带缺`Charm Slots`为unknown，不按0。90级默认三槽腰带/三个护符质量目标。`optimize_charm`生成Magic 1/1，Normal Charm只作candidate |
| 镶嵌 | `plan_item_sockets_batch(slot_socket_counts, goals)`评估全部可镶嵌装备，局部重测用`optimize_item_sockets`；两者共用回执登记。`socketed/partial_socketed`方案须实际`equip_item`并原样带craftReceiptRef；状态解释见验证reference |

精魂技能在资料中未出现不等于不需要；按主技能/职业补查。资源剩余不是线性可兑换的收益，Spirit
机会成本不能变成低利用率硬失败。辅助允许分别作用于同组宿主和输出，但每个辅助至少有一个PoB
确认的实际作用目标；数值能力仍跟随选中的精确输出。辅助搜索从当前组合与保留使用条件的最小组合出发，结果不证明
全局最优；runtime ID确认不可用的`uncoveredCandidates`保留为未覆盖，不能当成无收益或静默排除
其机制价值。审计status/reasonClass与可继续条件统一见
[验证与恢复](validation-and-recovery.md)。

新增路径可用`alloc_passive(path_attribute=...)`明确选择力量/敏捷/智慧，已有属性点用
`set_passive_attribute(node, attribute)`改选，归入`passive_delta`小事务；从`get_passive`读取选项，
不按职业默认猜选，也不为补属性重排整树。

用`list_jewel_sockets`盘点：已分配槽必须填真实珠宝，经`evaluate_jewel_socket`比较后用
`equip_jewel`显式填入/替换，正收益允许采用；该操作不花天赋点，不属于新增槽位决策。
写后必须通过物品来源、暗金数量、活动Spec读回与回滚核验。目标≥90才强制额外槽审计；核心与重要支撑
天赋完成后以精确node ID声明`protected_node_ids`，为已选下一颗珠宝调用`evaluate_next_jewel_socket`，
比较全部当前可达槽及安全单点叶节点的等点边际，不重排树。正收益只能经
`apply_next_jewel_socket_decision`原子应用，再在新state重审；不能先手工点额外槽后填珠宝来绕过审计。
无正收益或无可达槽才结束。
`policy_limited/inconclusive`可Judge但只能candidate，不能以成熟案例槽数、固定轮数或最低槽数代替。
低于90级只在机制需要时评估额外槽，不作为质量门禁。

镶嵌保留现有底材、物品等级、隐式和显式，不为Rune重做整件物品，不机械套Perfect Essence/腐化
成品。只写`Rune:`而缺少匹配效果/receipt不算装入；最终审计比较孔容量与可信Rune数。

依赖武器切换/武器组天赋时，保留合理设计，但当前工具不能按武器组分别分配/评分：
`alloc_passive`无weapon-set参数，单状态DPS不能成为双状态强信号。记录State_A/State_B未分别验证
的caveat，不为单状态面板放弃用户明确的切换方向。终局目标有诊断价值时可用`pinnacle_readiness`，
剧情阶段不受它的终局门槛驱动。

## 6. 锁定来源辅助并转入最终验证

`noSupports=false`的真实`Tree:*`/`Item:*`组可配置辅助，容量取最终角色等级对应的技能基础等级。
目标等级须早于授予技能的升华/被动分配；配置来源辅助后不要再`set_level`。物品来源辅助必须在
机制装备、Rune和词条最终锁定后，用新鲜fingerprint和实际source group调用
`configure_source_skill_supports(source_group_index, supports, expected_fingerprint, expected_state_hash?)`。
来源物品再次重装会使旧group、辅助与审计失效，需重读重配，不假定跨换装自动恢复。

`noSupports=true`明确表示辅助不适用；其他不可写来源保留真实技能与建模缺口，不复制普通
Ruzhan/Kelari等代理组。完成后进入验证reference的config锁定与最终状态审计；先前设计探索的
审计不能在换装/镶嵌/config变化后继续当作current。
