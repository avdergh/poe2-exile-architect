# 成熟 BD 知识与技巧

本文档持续沉淀从成熟 PoE2 BD 样本中提取的可复用设计知识。它可以完整记录关键技能与辅助组合、
局部核心天赋连接、暗金/装备职责和跨组件机制闭环。它不保存 PoB 导入码、raw XML、账号角色信息，
也不把全部装备、整棵天赋、全部技能组和配置组装成可一比一还原第三方整角色的镜像。

## 证据标记

- `直接观察`：来自用户提供的 PoB XML、Headless PoB 读回或项目语料。
- `组内模式`：在当前同类样本组中重复出现，仍不能直接扩大为全局规律。
- `设计推断`：由技能、装备、天赋和支持的组合推断玩法，需要实战或更多样本验证。
- `工具缺口`：PoB、Judge、词缀语料或选技逻辑当前无法可靠解释。

## 样本组 001：90 级 Martial Artist 三变体

- 样本引用：`16c74fc9992d`、`827829451e64`、`422d161ca3bc`。
- 共同角色壳：Monk / Martial Artist，等级 90，天赋树 `0_5`。
- 共同升华核心：`Runic Meridians`、`Way of the Stonefist`、`Hollow Focus Technique`；第四个
  大点在 `Hollow Form Technique` 与 `Hollow Resonance Technique` 之间分化。
- 共同普通天赋骨架：暴击率、暴击伤害、长杖命中/暴伤、攻击与施法速度、闪避/能量护盾混合
  防御，以及 `Spectral Ward` 将胸甲闪避转成最大能量护盾。
- 共同技能骨架：三个样本都使用 `Hollow Focus` 与 `Refutation`；`Hollow Focus` 都搭配
  `Cooldown Recovery II` 和 `Overabundance II`。

### 共通知识

#### 1. 升华选择必须按“赠送技能系统”分析

`直接观察`：该升华不是简单提供若干被动倍率：

- `Hollow Focus Technique` 直接授予 Hollow Focus；
- `Hollow Form Technique` 直接授予 Hollow Form；
- `Hollow Resonance Technique` 直接授予 Hollow Resonance；
- `Runic Meridians` 增加头盔、胸甲、手套和鞋的符文专用插槽；
- `Way of the Stonefist` 转化手套底材并强化相关显式词缀。

因此提取升华时必须同时检查：赠送技能、装备槽改写、符文容量和普通装备词缀如何配合，不能只
记录升华名或四个节点名。

#### 2. Hollow Focus 是“环境中的可攻击目标”，不是普通常驻伤害光环

`直接观察`：Hollow Focus 周期生成灵体钟；玩家命中钟会立即摧毁它并产生范围冲击波。钟本身
总是处于可重晕、可斩杀状态，且对钟的命中总是暴击。

`组内模式`：三个样本都增加钟的数量上限和生成频率，说明其价值至少包括：

- 给范围冲击波提供额外触发目标；
- 为依赖暴击、斩杀、重晕或击中事件的技能/支持提供稳定宿主；
- 让原本需要敌人进入特定状态的技能，在战斗场地中拥有更可控的交互对象。

`设计推断`：Hollow Focus 的真实价值可能明显高于 PoB 单独显示的极低 DPS。评价时应追踪
“攻击钟 -> 冲击波/重晕/斩杀 -> 后续收益”的事件链，而不是把它当成独立主输出技能。

#### 3. 暴击是多系统总线，不只是伤害乘区

`组内模式`：三套树都投入基础暴击率、长杖暴击、暴击伤害和近期暴击条件。暴击同时参与：

- 直接输出；
- Hollow Resonance 的敲钟触发；
- Cast on Critical 的能量生成；
- 对 Hollow Focus 钟的稳定交互；
- 部分手套、珠宝、近期暴击天赋和条件增益。

因此 Phase 4 应提取“暴击驱动了哪些事件”，而不只记录最终暴击率。

#### 4. 混合闪避/能量护盾防御由胸甲和天赋共同构成

`组内模式`：三个样本都选择闪避/能量护盾路线，并使用 `Spectral Ward`。样本胸甲普遍同时堆
闪避与能量护盾，普通天赋再增加两者。

可复用原则：当某节点按胸甲局部防御值转化全局资源时，胸甲不是普通防御槽，而是防御引擎的
核心输入。提取时需要记录：底材类型、局部数值、转化节点、恢复技能和最终资源池之间的链路。

#### 5. Refutation 是短时主动防御窗口

`直接观察`：Refutation 消耗全部 Ward，短时间阻挡所有可阻挡命中；样本普遍为其配置持续时间、
冷却恢复或次数类支持。

`设计推断`：它更像需要主动掌握时机的防御技能，而不是常驻 EHP。PoB 的静态 EHP 无法表达
玩家在 Boss 重击前开启 Refutation 的收益，也无法表达被重晕后窗口中断的风险。

### 变体 A：Flicker Strike 充能循环

#### 构筑身份

- 主体输出：Flicker Strike，PoB 当前组直接计算约 23.2 万 Combined DPS，暴击率约 97%。
- 补充技能：Charged Staff、Falling Thunder、Killing Palm、Staggering Palm、Whirling Assault。
- 升华分支：Hollow Focus + Hollow Form。
- 资源：145 Spirit 中保留 140；Power Charge 是输出、移动和增益共用资源。

#### 输出与操作循环

`设计推断`：

1. Killing Palm 斩杀低血敌人并获取 Power Charge；高稀有度敌人给更多充能。
2. 最大充能点、额外获得随机充能的武器符文和斩杀阈值装备提高充能供给。
3. Flicker Strike 消耗充能追加传送攻击，承担高速清图与贴身连续输出。
4. `Perpetual Charge` 提供不移除充能但仍获得消费收益的概率，延长连续传送链。
5. Charged Staff 消耗全部充能，为后续长杖攻击附加闪电伤害和冲击波。
6. Falling Thunder 在合适窗口消费充能，并通过 `Culmination II` 将此前其他近战命中积累的
   Combo 转换成单次爆发。
7. Staggering Palm 处理重晕窗口并给长杖攻击附加投射物；Whirling Assault 提供连续命中、
   Rage 与位移中的清怪覆盖。

#### 巧妙组合

- `One with the Storm` 让长杖技能消费充能时多计算一次消费收益；`Overflowing Power` 与
  `The Power Within` 增加最大充能和充能后的暴伤。
- Redflare Conduit 命中获球、到达最大球时自我感电并清空充能，同时消费球恢复最大 Mana；它把
  “获取 -> 到顶 -> 清空 -> 回蓝”做成周期系统。
- Beacon of Azis 让暴击忽略敌人元素抗性，并补大量 Spirit/Mana；它解释了为何该变体极端追求
  暴击率，也减少了常规穿透/降抗需求。
- Shavronne's Satchel 让生命药剂恢复同时作用于能量护盾，与 ES 主防御壳形成恢复闭环。
- Deathblow、Myris Uxor、Heart of the Well、Bounty Hunter/Hunting Companion 等共同提高斩杀
  阈值和击杀恢复，使 Killing Palm 与清图循环更容易启动。

#### 代价与风险

- Spirit 只剩 5，几乎没有保留调整余地。
- Flicker Strike 单次 Mana 消耗高，依赖击杀/消费回蓝、Mana leech 和药剂；Boss 无杂兵时需
  单独验证充能与 Mana 循环。
- 当前 PoB 显示火抗和雷抗未满，但成熟样本可能使用特殊来源；不能仅据此否定机制。
- 这是多按钮、多状态构筑；手感上限高，但资源中断时会明显掉速。

### 变体 B：Hollow Resonance 冰系暴击触发

#### 构筑身份

- 主体技能：Hollow Resonance，暴击约 97%；其伤害由其他技能暴击触发敲钟。
- 基础攻击：Quarterstaff Strike、Shattering Palm、Tempest Bell。
- 触发层：Cast on Critical + Frost Wall。
- 清图层：Herald of Ice、冰墙碎裂、Shattering Palm 冰碎爆炸。
- 升华分支：Hollow Focus + Hollow Resonance。

#### 输出与操作循环

`设计推断`：

1. 高频长杖攻击和 Shattering Palm 持续暴击，驱动 Hollow Resonance。
2. 暴击同时给 Cast on Critical 生成能量；`Boundless Energy II` 加快能量生成，
   `Energy Retention` 有概率退还一半触发能量。
3. 自动触发 Frost Wall，并用 Fortress、Spell Cascade 增加冰晶数量和覆盖。
4. 近战攻击、钟或冰碎爆炸破坏冰墙/冰晶，产生额外冷伤爆发与控制。
5. Shattering Palm 给敌人附加冰片，后续伤害达到门槛后再爆炸；Herald of Ice 继续放大冻结
   击杀后的清图连锁。
6. Tempest Bell 在 Combo 满后落地，持续吃玩家攻击并触发冲击波；元素异常还能给钟的冲击波
   增加对应元素伤害。

#### 巧妙组合

- `Evocational Practitioner` 同时提高“触发后暴击率”和“近期暴击后 Meta 技能能量获取”，把
  暴击和触发循环双向连接。
- Hollow Resonance 搭配 Brittle Armour：冻结目标后，物理伤害会持续破甲；这让冰系控制层为
  后续物理/混合攻击提供防御削减，而不是只贡献冷伤。
- Beacon of Azis 让高暴击攻击忽略元素抗性，同时提供 Meta/保留技能需要的 Spirit。
- Trampletoe 的过量伤害扩散与 Herald of Ice、冰碎爆炸都属于击杀后清图层，体现该变体偏向
  怪群连锁而非单一面板 DPS。

#### 代价与风险

- Cast on Critical 的触发频率与 Frost Wall 实际爆炸数量目前无法由 PoB 可靠汇总；直接读取
  Frost Wall 组的几十点 DPS 会严重误导。
- 属性读回存在 Strength/Intelligence 缺口，需确认武器组状态或特殊装备转化是否被工具漏读。
- 依赖冻结、冰墙位置和近战命中密度；对不可冻结或位移频繁的 Boss，实际兑现需要单独验证。

### 变体 C：双武器天赋状态的标记/冻结/变形轮转

#### 构筑身份

- 升华分支：Hollow Focus + Hollow Form。
- 技能包：Hand of Chayula + Freezing Mark、Hollow Form + Whirling Assault、Devour、Rend、
  Charged Staff、Shattering Palm、Tempest Bell。
- 防御：约 5168 ES、Ghost Dance、Wind Dancer、Refutation，并使用 Mageblood 护符体系。
- 双武器天赋：两套各使用 22 点；一套偏长杖暴击/攻击范围/充能消费，另一套偏冷伤、混沌伤、
  持续时间、Combo 与混合防御。

#### 输出与操作循环

`设计推断`：

1. Hand of Chayula 位移到目标并以提高效果触发 Freezing Mark。
2. Freezing Mark 让目标更容易被冻结；冻结后给予额外冷伤 Buff。
3. `Eternal Mark` 让标记首次激活时不被消费，延长同一目标上的收益；`Charged Mark` 在激活时
   生成感电地面；`Mark for Death II` 把标记目标承受的物理伤害转成破甲。
4. Shattering Palm 布置冰片并在后续伤害达到门槛时爆炸；Tempest Bell 消费 Combo 形成持续
   冲击波宿主。
5. Devour 从尸体或可斩杀目标恢复生命并获取 Power Charge；Rend 消费球获得额外闪电伤害，
   `Heightened Charges` 有概率让消费收益翻倍，`Perpetual Charge` 有概率保留充能。
6. Charged Staff 提供闪电附伤并在造成 Shock 时施加 Lightning Exposure。
7. Hollow Form 召唤幻影执行插入的近战攻击，消费 Power Charge 时增加幻影数量；其真实总输出
   取决于幻影数量、插入攻击和持续时间，当前 PoB 几乎没有正确表达。

#### 双武器天赋的巧妙用途

- 攻击状态：暴击、长杖暴伤、攻击范围、Daze、`One with the Storm`，服务直接长杖输出和充能
  消费。
- 持续/技能状态：冷伤、混沌伤、持续时间、Combo 维持、冷技能施法速度和 ES/闪避，服务标记、
  Hollow Form、Rend/Devour 等变形或持续技能。

这不是简单的“换一把武器多一点伤害”，而是用武器组天赋把同一角色切换成两种技能逻辑。任何
Judge 若只读一个状态，都不能给出强结论。

#### 装备与珠宝

- Mageblood 强化重复 Legacy 护符，为持续防御/功能增益提供高预算核心；它表明该变体不是低成本
  路线。
- 黄装项链同时提供近战技能等级、ES、Mana 恢复和抗性，是技能等级与防御资源的复合槽。
- Time-Lost Emerald 增强半径内 notable，并让小点额外提供攻击/元素伤、notable 额外提供长杖
  攻速；这是“放大一片高密度天赋区”的区域型珠宝，而不是普通四词缀珠宝。
- 另一颗珠宝补暴击、攻速、攻击伤害和 Shock 幅度，把直接攻击与闪电异常联系起来。

#### 代价与风险

- 操作和配置复杂度最高，依赖正确的技能状态、武器组、标记与充能时机。
- 当前 PoB 的 Hand of Chayula/Freezing Explosion 选技和 Hollow Form 数值都不足以代表整体输出。
- Mageblood 和高质量区域珠宝意味着较高预算；不能把它抽象成普通开荒模板。

## 对生成 Agent 的可复用建议

- 设计 Martial Artist 时，先选升华赠送技能分支，再围绕它设计技能事件链，不能先写一个普通
  长杖技能再把升华当作最后的倍率补丁。
- 每个主动技能必须标记职责：常驻攻击、充能生成、充能消费、Combo 生成、Combo 消费、标记宿主、
  触发宿主、击杀清图、防御窗口或移动。
- 充能构筑必须同时验证生成、最大值、消费、保留概率、翻倍收益和无杂兵 Boss 场景。
- Meta trigger、Hollow Form、Tempest Bell、Hollow Focus 与冰墙爆炸都需要独立 modelability
  caveat；不要用单一技能面板替代整套轮转。
- 暗金和黄装的选择应按职责评价：机制启用、资源闭环、防御恢复、清图扩散、预算与可替代性，
  而不是简单统计暗金数量。
