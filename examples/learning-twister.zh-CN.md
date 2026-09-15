# Twister 构筑学习指南：完整案例

[English introduction](learning-twister.en.md) · [返回首页](../README.zh-CN.md)

**[下载完整 HTML 学习指南](https://github.com/avdergh/poe2-exile-architect/raw/refs/heads/main/examples/learning-twister.zh-CN.zip)**，解压后用浏览器打开 `Twister-learning-guide.html`。图标已内嵌，目录、搜索与组件说明可离线使用。

下面是同一份指南的完整 14 章正文，可直接在 GitHub 阅读；文末附组件与概念说明。HTML 文件保留原产物的图标与交互排版。

对象：**100 级 Gemling Legionnaire / Twister**。本页展示已有教学产物，不宣称其内容已按最新补丁重新验证。

Whirling Slash 负责准备，Twister 负责把准备转成命中。这本指南从一次完整操作开始，逐步解释两套武器、宝石、装备、天赋和升华怎样配合。

## 先用一次投掷认识这套构筑

这是一套 100 级 Gemling Legionnaire 长矛攻击 BD。主输出是 Twister，Whirling Slash 为它准备可利用的旋风。先认清这两个动作，再看装备和天赋，许多选择就有了共同的目标。

**一次输出的基本配合**

1. **建立旋风**：用 Whirling Slash 建立并积累 Whirlwind。
2. **强化投掷**：在准备对象仍存在时，让 Twister 与它发生交互。
3. **保持接触**：让强化后的旋风实际接触目标，留意目标移动。

Twister 虽然看起来像释放一个旋风，它仍然是使用长矛的投射物攻击。武器伤害、攻击附加伤害、元素攻击伤害、投射物属性和暴击都会参与；不能按普通法术的思路，只寻找法术伤害。

这套构筑把速度与伤害分开建设：第一套武器偏向快速完成准备动作，第二套武器偏向兑现伤害。The Taming 让 Wind 技能获得多种元素地面强化；Projectile Acceleration III 让投射物速度投资同时参与伤害；暴击与敌人抗性的处理则继续放大这部分元素命中。

| 看到的选择 | 它首先解决的问题 |
| --- | --- |
| Whirling Slash 与速度配置 | 缩短准备时间，建立可供 Twister 利用的对象 |
| Twister 与元素伤害配置 | 把准备好的强化变成实际命中 |
| 充能技能与恢复 | 让准备和输出能一轮接一轮继续 |
| 闪避与 Energy Shield | 为完成动作和重新建立状态争取空间 |

#### 先记住三个检查点

有准备对象、技能交互成功、旋风接触到目标。这三个条件缺一项，单纯提高纸面伤害都不能补回丢失的输出。

## 把准备动作和输出动作接起来

先练习没有复杂增益的一次完整交互，再加入标记和充能。下面的顺序用于理解配置的分工；导出文件没有记录作者实际每一场战斗的按键和切换设置。

| 武器状态 | 主要职责 | 为什么这样配 |
| --- | --- | --- |
| 第一套 | 完成近战准备动作 | 高速度 Soaring Spear、空副手和速度天赋 |
| 第二套 | 使用更强的伤害配置输出 | The Ordained、Guiding Palm of the Eye 与元素暴击天赋 |

### 第一遍先确认旋风交互

用 Whirling Slash 建立 Whirlwind，观察阶段积累。趁对象仍在，让 Twister 穿过并利用它，再观察目标是否留在旋风经过的区域。Whirling Slash 的旋风还有离开后的崩塌行为，因此移动时机和站位不能忽略。

Whirlwind 的阶段会强化 Twister，当前技能资料列出每阶段 80% more damage。这里的学习重点不是先背百分比，而是理解：准备动作是否完成，会直接改变后续攻击的质量。

### 熟悉之后再加入增益

**带标记和充能的一轮操作**

1. **先看状态**：检查可用充能、Barrage 使用次数和当前武器状态。
2. **完成准备**：建立 Whirlwind，给重要目标施加 Sniper's Mark。
3. **兑现并重建**：有条件时使用 Barrage，投出 Twister，随后补准备与充能。

#### 切换武器时要重新看条件

Dance with Death 需要单手近战武器和空副手。第二套拿着 Sceptre 时，不能继续把这一条件算作成立；两套武器各自的天赋也不能合并为永久状态。

场上对象、增益和伤害在切换武器时怎样保留，不能仅凭这份导出确定。练习时先看实际技能绑定和对象变化，不要假定所有属性都会自动按两套武器中最有利的数值叠加。

## 沿着伤害来源理解放大顺序

先找攻击的伤害基础，再看技能强化、属性投资、暴击和敌人抗性。把它们分层理解，比把所有百分比加在一起更容易判断一件装备为什么有用。

**从攻击基础到命中结果**

1. **伤害基础**：武器的物理与闪电伤害，以及攻击附加伤害。
2. **技能与属性**：旋风强化、额外元素伤害、投射物速度和相关辅助。
3. **命中结算**：暴击方式、敌人抗性以及满足条件的受伤增加。

### The Taming 解决地面强化条件

Twister 属于 Wind 技能。The Taming 让这类技能可以利用多种元素地面的强化，并视为获得相应强化，减少对现场临时铺出不同地面的依赖。它因此接近机制装备，不能只按戒指上的抗性和普通伤害词条衡量。

#### 地面强化和敌人异常要分开看

技能视为获得火、冰、电地面的强化，不等于敌人已被点燃、感电和冰缓。Yoke of Suffering、The Taming 的异常相关伤害及 Harness the Elements，仍要看敌人真正承受了哪些异常。

### 投射物速度为何值得反复投资

Projectile Acceleration III 让投射物速度的 increased/reduced 修正同时用于伤害。因此手套、Catapult、普通投射物速度小点和珠宝可以服务同一条输出路线。它们还会改变旋风移动与接触目标的方式。

攻击速度、技能速度和移动速度不是投射物速度。more Projectile Speed 也不能未经核对就按 increased Projectile Speed 的规则再兑换一次伤害。速度提高后，旋风是否仍能有效接触移动中的 Boss，也需要观察。

### 暴击加成与抗性分别处理什么

Garukhan's Resolve 将单次暴击判定限制在 50%，同时进行两次判定。如果只有一次成功，应用一次暴击伤害加成；两次都成功，加成应用两次。这解释了树上和珠宝中大量暴击伤害的价值。

| 假设单次判定为 50% | 概率示例 | 结果 |
| --- | --- | --- |
| 两次都失败 | 25% | 普通命中 |
| 只有一次成功 | 50% | 应用一次暴击伤害加成 |
| 两次都成功 | 25% | 暴击伤害加成应用两次 |

这张表只是判定方式的例子。双成功不等于整次最终伤害直接乘二，暴击率投资也没有因此失去意义。仍然需要把基础暴击与 increased 暴击机会建设到合适水平。

Rakiata's Flow 改变所辅助攻击对元素抗性的处理，让敌人的正元素抗性可能成为有利条件。采用它后，减抗与反转抗性之间要重新比较，不能照搬普通元素 BD 的全部减抗建议；命中的抗性处理也不能直接推广到所有异常持续伤害。

#### 更多旋风不等于同倍数的 Boss 伤害

Twister 同批旋风命中同一目标存在间隔限制，当前资料为 0.66 秒。Salvo 的投射物、Whirlwind 的强化和 Barrage 的重复改变不同部分，不能把数量直接相乘。先观察接触时间和交互，再看面板。

## 主攻和准备技能的宝石怎样分工

这两组技能的辅助看起来都在提高攻击能力，目标却不同。Twister 追求一次有效输出的质量，Whirling Slash 追求快速完成准备。

### Twister 的五颗辅助

| 辅助 | 在本组中的职责 |
| --- | --- |
| Salvo | 随时间积累封印，使用时增加随机方向投射物。适合准备后释放；连续使用不能假定每次满封印，也不能保证所有投射物都覆盖 Boss。 |
| Projectile Acceleration III | 将投射物速度的 increased/reduced 投资同时用于伤害，连接手套、天赋与珠宝。 |
| Elemental Armament II | 强化武器攻击中的元素伤害部分，与额外元素伤害来源配合。 |
| Garukhan's Resolve | 改变暴击判定和加成结算，让暴击伤害投资有更明确的回报。 |
| Rakiata's Flow | 改变对敌人元素抗性的处理，服务于元素命中。 |

源宝石是 20 级、20 品质，前次导入的当前模型读到有效等级 25。基础等级与装备、升华作用后的有效等级要分开看。Twister 的普通品质涉及额外旋风机会，Advanced Thaumaturgy 对应的额外品质还涉及投射物速度，不能把两种效果混算。

### Whirling Slash 的五颗辅助

| 辅助 | 为什么适合准备技能 |
| --- | --- |
| Rage III | 近战命中获得 Rage；未达到最大 Rage 时还能获得额外攻击速度，速度部分不是全程无条件成立。 |
| Rapid Attacks III | 以伤害代价换攻击速度，符合快速完成准备的目标。 |
| Blazing Critical | 通过满足条件的手动暴击建立火焰强化，帮助后续攻击。 |
| Magnified Area II | 改善准备技能的范围与操作容错，不应当作 Twister 所有伤害都因此提高。 |
| Rigwald's Ferocity | 两套武器下的速度与伤害取舍不同，与准备套和输出套的分工相符。 |

Whirling Slash 在来源中为 1 级、20 品质，前次模型有效等级为 3。低基础等级、高品质与它的准备职责相符：品质和额外品质可以服务动作效率，而本案并没有主要依赖它自己的直接命中伤害。

#### 等级和阶级不要读混

辅助名称里的 I、II、III 表示阶级，不是宝石等级。来源中的辅助大多记录为 1 级、0 品质，不能因此判定它们没有升级。

## 充能怎样支持一轮接一轮输出

先看充能从哪里来，再看它被谁消耗。Barrage 想把充能用于当前输出，Charge Regulation 想保留充能维持增益，两者需要产球和保留机制来协调。

**产球与耗球的配合**

1. **建立充能**：Sniper's Mark 的暴击事件，以及 Combat Frenzy 的控制事件。
2. **改善维持**：额外产球、充能持续时间和消耗时不移除的机会。
3. **分配用途**：Barrage 强化攻击；Charge Regulation 持续提供增益并周期消耗。

### Sniper's Mark 把重要目标接入循环

标记参与后续暴击及 Frenzy Charge 获取。Charge Profusion II 改善产球，并可能带来其他类型；Eternal Mark 减轻第一次触发后立即补标记的负担。Mark for Death II 引入物理伤害相关破甲条件，Armour Demolisher II 放大已有破甲。标记的普通品质与暴击收益有关，额外品质还涉及被标记敌人的伤害。

#### Breachlord's Rift 要先找到命中事件

这颗辅助需要所辅助技能命中并冻结或 Electrocute 敌人。Sniper's Mark 本身没有直接命中，因此不能把它介绍为这一组的稳定破甲来源。若它承担辅助颜色配置职责，应另看 Gem Studded 的实际条件。

### Combat Frenzy 依赖控制事件

冻结、Electrocute 或 Pin 等事件能为它建立 Frenzy Charges，但存在内部间隔。Charge Profusion II 改善每次触发的产出。Empowered Sparks I 则要求所辅助技能产生 Power Charge，所以还要追溯额外产球带来的 Power 分支，不能讲成每个 Frenzy Charge 都直接触发 Spark。

普通品质和额外品质分别影响产球机会、内部间隔等行为。Shock 与 Electrocute 不相同，有闪电伤害或能感电，不代表产球条件已经持续成立。

### Barrage 消耗充能建立输出窗口

Barrage 强化后续攻击、增加重复，并能消耗 Frenzy Charges 增加效果。重复有伤害折减，冷却也与被强化攻击耗时有关，因此更多重复不是没有代价的最终伤害倍数。

| 辅助 | 对输出窗口的作用 |
| --- | --- |
| Heightened Charges | 让充能消耗有机会取得额外收益 |
| Perpetual Charge | 有机会保留充能，同时仍按消耗处理，减轻下一轮的产球压力 |
| Cooldown Recovery II | 改善重新获得使用机会的速度 |
| Uhtred's Constellation | 增加储存的冷却使用次数，不把无直接命中的增益技能变成主输出 |
| Olroth's Conviction | 增加强化技能的使用机会，让一次准备服务更多后续动作 |

### Charge Regulation 提供增益也提出需求

不同类型的充能分别提供速度、暴击和防御相关增益，维持过程又会周期性消耗它们。品质参与持续与收益，The Fabled Stag、充能持续时间和不移除充能的机会帮助减少断档。本组的 Clarity I 提供资源辅助，但不能与别组的 Clarity II 未经核对就按两份完整增益相加。

#### 一个适合上手时观察的现象

先连续打一小段，观察充能是在积累、稳定还是逐渐耗尽。如果一开始很强、几轮之后明显断档，先检查产耗球和冷却，不要只归因于武器伤害低。

## 把持续增益和清图扩散放回各自的位置

持续技能不一定都直接打伤害，有的提供增益，有的等待触发事件。读懂宿主和触发条件，才能知道一颗辅助究竟服务于谁。

### Trinity 利用持续元素命中建立 Affinity

每次命中中最高的元素伤害类型会积累对应 Affinity，同时减少其他类型；积累再转成元素伤害收益。多种元素存在，不等于增益自动满值。Fire Mastery 为这颗包含 Fire 类型的技能提供等级。

普通品质的技能速度条件看总 Affinity 超过 250，而不是每种都达到 250。额外品质的随机元素转换会改变伤害构成。Trinity 的基础 Spirit 占用很高，安排其他持续技能时必须一起算入。

### Herald of Ice 把击碎扩散到周围敌人

冰爆服务于冻结、击碎之后的清图。Elemental Armament II 强化其攻击元素伤害，Magnified Area II 扩大覆盖；Armour Break III、Armour Explosion、Uruk's Smelting 则要求继续追溯物理命中、破甲与完全破甲事件。

Armour Break III 需要相应伤害与破甲条件；Armour Explosion 在完全破甲后产生另一种爆炸；Uruk's Smelting 强化破甲及相关物理受伤收益。它们不是对所有元素伤害统一提供无条件 more，也不能仅凭多颗爆炸辅助就认定存在无限自触发。没有小怪可击碎的 Boss 战，清图链本来就不会以相同方式运转。

### Purity of Ice 也是功能辅助的载体

它由 Guiding Palm of the Eye 授予，提供冰冷抗性相关增益。Her Declaration 通过持续技能和 Presence 提供 Intimidate 相关作用；Clarity II 帮助 Mana，Cannibalism II 提供击杀回血，Vitality II 提供生命再生。

#### 先确认授予技能仍然存在

切到不持有 Sceptre 的状态时，要重新看 Purity of Ice 及其辅助是否仍然成立。Cannibalism II 需要击杀；Clarity I 与 Clarity II 也不能直接当独立完整增益累加。

### 默认技能和装备技能怎样阅读

Spear Throw 包含武器授予的条目，并非本案主输出。Frost Nexus 需要实际命中已冻结敌人才产生冰缓地面；The Taming 已提供 Wind 技能的地面强化条件，所以它不是 Twister 获得冰地强化的唯一前提。

Righteous Descent 来自 The Ordained，利用 Fragment of Divinity 提供额外攻击与恢复机会；碎片供给限制了使用节奏。文件中的重复授予条目，也不代表有多份可同时叠加的技能增益。

## 防御技能怎样为操作争取空间

这套 BD 需要完成准备和投掷，防御的作用之一就是让这些动作有机会完成。减少受击、承受受击和恢复损失，分别由不同部分承担。

**防御的三个环节**

1. **减少命中**：闪避、Wind Dancer、Blind 与控制降低部分敌人的威胁。
2. **承受损失**：Life、Energy Shield、Ward、抗性及相关承伤方式。
3. **重新建立**：Ghost Dance、护盾充能、再生、药剂与满足条件的恢复。

### Wind Dancer 的阶段和反击

Wind Dancer 积累阶段改善闪避，受击后消耗阶段并触发 Gale Force。Elemental Armament II 和 Magnified Area II 主要服务反击的伤害与范围；Pinpoint Critical 用暴击伤害换暴击机会；Ambush 要求目标满血；Blind II 改善致盲相关效果。

反击能打伤害，不代表值得主动承受危险攻击。连续受击会改变阶段状态，Ambush 也不能当作整场 Boss 战常驻。学习这组时，应先理解防御节奏，再看反击附带的收益。

### Ghost Dance 让闪避参与护盾恢复

它积累 Ghost Shrouds，受击失去 Shroud 后获得恢复相关收益。当前资料中的效果涉及按闪避值提供一段护盾再生，不能照搬旧版本的瞬间恢复描述。Cooldown Recovery II 服务于 Shroud 的恢复节奏；普通品质与额外品质还涉及保留效率、可维持的 Shroud 等功能。

#### Armour Demolisher I 没有自动创造破甲

Ghost Dance 自身没有明确破甲事件，所以这颗辅助不能被算作稳定破甲来源。它可能还与颜色配置有关，但这个用途需要单独核对，不能代替实际破甲机制。

### Virtuous Barrier 会建立也会受损

Essence of Virtue 授予这个技能。不同类型的 Motes 分别参与最大生命、生命与 Mana 恢复、闪避、Deflection 和护盾充能等方面；它们随时间积累，受击会失去随机 Mote。这里与主动技能的属性要求有关，不能混成 Gem Studded 的辅助颜色计数。重复条目不代表能同时开启两份 Virtuous Barrier。

## 先看武器和防具各自解决什么

看装备时先找职责，再看数值高低。一件速度武器、一顶高 ES 头盔和一件高闪避胸甲，在这里解决的是不同问题。

### 第一套 Soaring Spear 为准备动作提速

Armageddon Edge 的突出价值是攻击速度，并保留空副手条件。命中和物理伤害相关 Mana 偷取帮助动作与资源，但不能据此证明第二套所有元素输出都稳定回蓝。Thrud's Might 涉及特殊词缀来源，Soul Core of Quipolatl 服务速度，镶嵌效果提高只放大相应可缩放效果，不等于同百分比总伤害。

### 第二套 The Ordained 配合 Guiding Palm of the Eye

The Ordained 提供物理和闪电伤害基础、基础暴击相关属性，并让闪电伤害参与特定生命偷取计算；Fragment of Divinity 与 Righteous Descent 又增加恢复和攻击机会。Saqawal's Rune of the Sky 补充额外元素伤害。

Guiding Palm of the Eye 同时提供额外冰冷伤害、Spirit 和 Purity of Ice，Rabbit Idol 帮助 Spirit 预算。它的 Guided Freezing Shrine 还有额外冰冷场上效果。写给 Allies 的攻击附加或再生共享词条，不应直接当角色自己又获得一份相同收益；召唤物指令类条件也不能当主输出收益。

### 头盔与胸甲是一组防御配套

Hypnotic Star 的 Ancestral Tiara 底材提供高局部 ES，既建立护盾基础，又经 Subterfuge Mask 转为闪避基础。抗性和护盾充能相关属性补充防御；稀有度、经验类镶嵌主要服务刷图，不应介绍成攻坚核心。

Loath Ward 是这件稀有胸甲的随机名称，Slipstrike Vest 是它的底材。选择它的重点是胸甲自身的高闪避：天赋 Beastial Skin 放大胸甲的闪避收益，天赋 Spectral Ward 再利用胸甲闪避建立护盾基础。这里的 Deflection 是防御属性，不是另一个要使用的技能。

胸甲中的两颗 Perfect Iron Rune 是镶嵌符文，用来强化这件装备的局部防御。读这条配合时，要分清胸甲自身的闪避和角色最后的总闪避，不能把已经放大后的角色总值再当作胸甲局部值计算一次。

### 手套把多个输出目标放在同一部位

Phoenix Claw 是这副稀有手套的随机名称，Runeforged Secured Wraps 是底材。手套上的投射物速度、投射物技能等级和攻击附加闪电伤害，分别服务速度转伤害、技能成长和攻击基础。

Mark 指标记技能类别，例如 Sniper's Mark；相关使用速度让上标记的动作更快。混沌抗性和 Ward 则属于防御，Ward 不是一个需要按键使用的技能。镶嵌物 Kolr's Hunt 涉及 Marksman 词缀来源，所以不能只拿一条普通攻击伤害词条比较这双手套的替代品。

### 鞋子主要补防御和抗性

Armageddon Pace 的 Daggerfoot Shoes 提供闪避与 ES、抗性及部分抗击晕能力，Greater Glacial Rune 继续补冰冷抗性。来源没有明确的移动速度显式词条，所以操作速度还要看树和技能，不能把它介绍成高跑速鞋。

#### 阅读镶嵌时把条件一起读完

文本中标有 Bonded 的部分有独立条件，未确认激活时不算额外常驻属性。特殊词缀来源、镶嵌效果和角色本身获得的属性，也需要分别理解。

## 首饰和珠宝怎样连接核心机制

有些部位可以用普通属性替换，有些部位一旦移走，就需要另找机制来源。先分清这两类职责。

### Yoke of Suffering 奖励真实施加的异常

敌人身上的元素异常能转成受到伤害增加，因此重点是实际异常种类和维持。它对异常持续时间的不利修正也是代价，不能只计算每种异常的收益。涂油 Vulgar Methods 提供 Strength 和暴击机会，同时减少最大 Mana，帮助门槛与暴击但缩小资源缓冲。

### 两个戒指的替换难度不同

Entropy Coil 是 Unset Ring，主要承担额外技能槽、生命、抗性和功能属性。技能很多时，额外技能槽有实际价值；附加冰伤是补充，不能把它视为另一套核心机制。

The Taming 则提供 Wind 技能的多元素地面强化条件，同时补抗性和异常相关伤害。替换它，除了比较词条，还必须解决被移走的地面强化机制；地面强化仍不等于敌人已受到对应异常。

### 三颗珠宝各有一个重点

| 珠宝 | 应当保留的职责 |
| --- | --- |
| Heart of the Well | 额外火焰和闪电伤害补元素命中，暴击伤害和持续时间服务兑现与维持。 |
| Phoenix Wound 的 Emerald | 投射物速度、攻击暴击、元素伤害和攻击速度共同进入已有输出体系。提速后仍要看资源压力。 |
| Rapture Joy 的 Time-Lost Emerald | 让半径内的重要节点得到额外暴击、投射物速度和暴击伤害等收益；位置和附近已投入的节点决定价值。 |

#### 半径珠宝不能脱离位置比较

同一颗 Time-Lost Emerald 换一个孔，覆盖的重要节点可能不同。先看半径里有哪些已分配节点，再谈词条总收益；这里不把它按整棵树全局生效计算。

## 腰带护符和药剂怎样改变使用场景

这一组配置能让刷图越来越顺，但其中有不少效果依赖击杀或被施加状态。先看触发条件，才能理解为什么同一套装备在无小怪 Boss 战中感觉不同。

### Headhunter 提供刷图中的累积优势

击杀稀有怪后获得的临时能力会改善清图过程，腰带本身也提供生命、属性和三个护符槽。没有可供偷取的稀有怪时，应按角色基础状态看待它，不把之前偷取的一整套能力当永久属性。

| 护符 | 用途 | 使用条件 |
| --- | --- | --- |
| The Fall of the Axe | 应对减速，效果期间获得 Onslaught | 装备着不等于永久 Onslaught |
| Rite of Passage | 击杀后获得 Spirit of the Wolf | 依赖稀有或传奇敌人击杀及持续时间 |
| Beira's Anguish | 应对被点燃并产生燃烧地面 | 需要触发，不能保证 Boss 一直被自己点燃 |

The Taming 已解决 Wind 技能的地面强化条件，因此不能把 Beira's Anguish 讲成 Twister 获得火地强化的唯一必需品。

### 两瓶药剂解决不同的问题

Seething Ultimate Life Flask of the Distiller 提供紧急生命恢复：瞬回有利于救急，但恢复总量下降；减少消耗帮助管理使用次数。它恢复 Life，不会自动把 ES 补满。

Lavianga's Spirits 不能按普通 Mana Flask 手动使用，而是持续提供效果。它与 Mana Flask 恢复和药剂效果期间的速度条件相连。药剂恢复不是 Mana Regeneration；药剂效果期间与使用药剂时也不是同一个触发条件。

#### 先分清恢复来自哪一类

普通再生、药剂、偷取和技能恢复各有条件。核对持续输出时，把已经包含在某项读数中的恢复再加一次，会让资源看上去比实际更充足。

## 沿着天赋目标理解路径和武器组

这棵树追求的不是单一大面板。暴击、局部防御转换、动作速度、充能和武器组分工，分别解释了不同区域的投入。

### 先建立暴击机会再兑现暴击伤害

| 节点 | 在这套配置中的作用 |
| --- | --- |
| Struck Through | 攻击基础暴击机会，与普通 increased 暴击机会不是同一层。 |
| True Strike 与 Heartstopping | 补暴击机会并提供属性。 |
| Javelin | 服务长矛暴击伤害。 |
| Heartbreaking 与 For the Jugular | 暴击伤害加上属性，帮助输出与门槛。 |
| Deadly Force | 利用近期暴击改善后续输出。 |
| Moment of Truth | 利用近期非暴击条件；Garukhan's Resolve 并没有消除非暴击命中。 |

周围 Critical Chance、Attack Critical Chance、Spear Critical Chance、Critical Damage 和 Damage on Critical 小点分别补足机会、专属范围、加成与条件收益。采用特殊暴击结算后，仍然不能放弃基础暴击建设。

### 头盔 ES 与胸甲闪避互相配套

**局部防御值怎样被再次利用**

1. **装备基础**：头盔的局部 ES，胸甲的局部闪避。
2. **关键节点**：Subterfuge Mask 与 Spectral Ward 取得额外防御基础。
3. **继续放大**：Beastial Skin、Mindful Awareness 和其他防御小点。

Subterfuge Mask 利用头盔自身 ES 建立闪避基础；Spectral Ward 利用胸甲自身闪避建立 ES 基础；Beastial Skin 强化胸甲闪避，Mindful Awareness 同时投资闪避和 ES。Enhanced Reflexes 则连接闪避、Deflection 与 Dexterity。Evasion、Evasion and Energy Shield、Deflection and Evasion 小点围绕同一套基础继续投入。

### 动作速度与充能让操作更连贯

Dance with Death 是第一套空副手的重要条件。Flow State 兼顾技能速度与 Mana，Flow Like Water 改善攻击和施法动作并提供属性，Step Like Mist 连接移动、Mana 与属性，Escape Velocity 连接移动与闪避。

The Fabled Stag 延长充能并提供消耗时不移除的机会，Charge Duration 及其 Dexterity 小点减少自然过期。Catalysis 提供元素攻击伤害并改变部分物理命中的承伤方式；Remorseless 的投射物收益与近距离条件要分别看。Spear Damage、Elemental Attack Damage 和 Projectile Damage 小点继续为已有机制补数值。

### 第一套的二十四点服务快速准备

| 节点 | 为何放在第一套 |
| --- | --- |
| Wellspring 与 Stimulants | 围绕 Mana Flask 恢复和药剂效果期间的速度。 |
| Chakra of Thought | Mana 参与承伤，并在不是低 Mana 时提供速度；资源状态更重要。 |
| Tenfold Attacks 与 Agile Succession | 近期命中后的速度，以及相关闪避收益。 |
| Acceleration | 移动与技能速度，改善准备和调整位置。 |

配套小点投资 Attack Speed、Skill Speed、Mana Regeneration、Mana Flask Recovery，以及速度和药剂持续时间组合。它们不能在第二套状态下被无条件保留。

### 第二套的二十四点服务输出

| 节点 | 输出职责与代价 |
| --- | --- |
| Catapult | 投射物速度与攻击范围，配合 Twister 和速度转伤害辅助。 |
| Harness the Elements | 利用敌人真实的元素异常，不能用地面强化替代条件。 |
| Prolonged Assault | 攻击伤害、技能持续时间和增益维持。 |
| Stupefy 与 Dizzying Hits | 建立并利用 Daze 的伤害或暴击条件。 |
| Killer Instinct | 生命状态决定收益；本案不能套用另一份低血变体的条件。 |
| Cooked | 以防御属性削减换暴击伤害，是明确取舍。 |

其余小点继续补元素伤害与冻结积累、投射物速度、攻击伤害、持续时间、暴击和对 Dazed 敌人的收益。两套各二十四点是替换的分配方案，不是四十八点同时生效。

### 属性点和珠宝孔也有成本

属性过路点既连接区域，也满足装备和宝石要求。前次导入读到 Strength 71 对需求 65、Dexterity 225 对需求 150、Intelligence 128 对需求 110；Strength 的余量较小，换掉涂油或腰带时尤其要复查。三个珠宝孔承担各自珠宝收益，半径珠宝还依赖位置。职业起点和 Gemling 起点是树结构，不额外编成独立增益。

## 升华怎样让多组技能一起受益

Gemling Legionnaire 的选择与大量功能技能、高品质和属性要求有关。理解升华后，再回头看那些没有直接打伤害的宝石，会更容易分辨它们的用途。

### Essence of Virtue 让技能配置参与防御

它授予 Virtuous Barrier。Motes 与主动技能的属性要求相连，分别参与生命、恢复、闪避、Deflection 和护盾充能等方面，并存在积累与受击损失的过程。这与辅助颜色计数是两套不同的规则。

### Advanced Thaumaturgy 使品质具有功能价值

它让技能品质获得额外效果。Whirling Slash 可以从品质得到准备速度，Twister 的品质影响旋风机会及投射物速度，Barrage 连接重复与充能保留，Sniper's Mark 和 Ghost Dance 也有各自的功能效果。树上 Skill Gem Quality 小点因此能同时服务多组技能，不能统称为少量伤害。

### Gem Studded 要看实际可计数的辅助颜色

最多的辅助颜色对应承受暴击、技能成本和移动施放惩罚等不同效果。一颗辅助可能同时承担直接作用与颜色配置，但必须按实际计数和启用状态核对。存在红绿蓝三色，不足以证明三项效果同时成立。

#### 颜色用途不能替代直接作用的解释

Ghost Dance 中的 Armour Demolisher I，或 Sniper's Mark 中的 Breachlord's Rift，可能有颜色方面的考虑；这仍不等于它们已经在该组产生稳定破甲，不能用猜测替作者决定动机。

### Motoric Implants 提高具有 Dexterity 要求的技能等级

Implanted Gems 在本案选择 Motoric Implants 分支。它影响的不只是主输出，还包括多颗功能技能，所以要看作用后的有效等级。升华小点的品质与属性需求减免，则帮助大量不同功能宝石共存。

## 安排常驻技能并留出恢复余量

资源有两种不同的问题：Spirit 决定哪些持续技能能同时存在，Mana 和 Life 决定动作能否持续。把这两件事分开检查，排错会更直接。

### 先确认可以同时开启哪些技能

Trinity、Herald of Ice、Charge Regulation、Wind Dancer、Ghost Dance 和 Combat Frenzy 等持续技能共同占用 Spirit，部分辅助也会改变成本。Guiding Palm of the Eye 提供 Spirit 和授予技能，因此切换武器还会改变需要考虑的组合。

#### 这份导入需要先核对启用列表

前次模型读到容量 215、请求 254，差额为 39。实装时先核对武器切换、授予技能和实际启用组合，不要把文件中所有勾选都同时开启。这不是让你照着关闭某颗技能，而是先明确哪一组增益应该一起工作。

### 再看一轮操作的成本和恢复

前次在第二套 Twister 状态下，模型读到每次 Mana 成本 56，对应面板频率约 92.8 每秒，普通 Mana 再生为 66.5 每秒。单看普通再生不足以覆盖这段连续动作，但还要分别考虑持续药剂恢复、满足条件的偷取、技能恢复，以及准备和移动带来的间歇。

第一套的物理 Mana 偷取和药剂天赋，不能直接证明第二套可以无限持续。反过来，模型中的静态差额也不能直接判定实战必然断蓝。练习时观察数轮完整操作后的资源趋势，比只看满蓝起手的一次爆发更有用。

### 防御要看能否重新建立

前次第二套状态读到约 1808 Life、3031 ES、166 Ward，三项元素抗性 75%，混沌抗性 22%。这些数值帮助辨认防御结构：它依赖闪避减少受击，ES 承受损失，再通过 Ghost Dance、护盾充能、再生、药剂和满足条件的恢复重建状态。

它没有很大的生命池可以承受所有攻击。连续受击、控制失效、恢复尚未建立、混沌伤害，以及输出状态中 Cooked 的防御取舍，都可能让操作空间变小。遇到这些情况，先重新建立防御和资源，而不是强行把准备动作打完。

#### 换装备时先保住关键连接

替换前确认四件事：技能所需武器仍在、Spirit 组合能运行、属性需求满足、头盔与胸甲的防御配套仍成立。来源有特殊词缀和镶嵌，若当前工具对物品报错，应先核对词条与版本，不直接把它当成可复制的普通黄装模板。

## 从刷图过渡到没有小怪的 Boss

同一套构筑在两个场景中可能表现不同。先认出哪些状态由小怪提供，进入 Boss 战时才知道哪些部分要依靠自己的操作维持。

| 条件 | 刷图时 | 无小怪 Boss 时 |
| --- | --- | --- |
| 冻结击碎与产球 | 事件较多，容易接入循环 | 需要看控制事件能否持续发生 |
| Headhunter 与击杀护符 | 可从稀有怪和击杀取得临时增益 | 不能假定偷取和击杀增益常驻 |
| Cannibalism II | 击杀回血帮助清图 | 没有击杀时不提供这条恢复 |
| 旋风接触 | 密集目标更容易被覆盖 | Boss 位移可能浪费已经准备的输出 |
| 充能与冷却 | 战斗过程不断补充条件 | 需要独立观察产耗球和输出窗口 |

### 练习时按三个阶段加东西

- 先练 Whirling Slash 与 Twister：看准备对象是否被利用、目标是否被旋风接触。
- 再加入 Sniper's Mark 和 Barrage：观察充能、重复和冷却怎样改变一轮输出。
- 最后同时观察持续增益与资源：看几轮之后是否出现充能减少、Mana 下滑或防御难以恢复。

### 遇到问题时从哪里开始找

| 看到的现象 | 先检查的环节 |
| --- | --- |
| 旋风很多，Boss 掉血却不明显 | 准备强化是否成功、轨迹是否接触、目标是否离开，同批命中间隔是否限制收益 |
| 第一轮顺，后面逐渐断档 | 产球是否跟上 Barrage 和 Charge Regulation，冷却与持续时间是否衔接 |
| 换一件装备后技能或增益异常 | 武器授予、属性要求、Spirit 和技能槽是否被改变 |
| 切换输出后更容易倒下 | 武器组防御差异、Cooked 代价、恢复状态和混沌抗性 |

学习过程中，先把实际动作和条件接起来，再比较数值。The Taming 的地面强化、敌人身上的异常、暴击判定和最终命中是不同环节；知道它们分别由谁提供，才能有依据地更换装备或调整操作。

#### 版本与资料说明

本指南整理自你提供的单一导出及前次机制分析。来源补丁未明确，文中模型读数用于说明这份配置的结构；技能效果变化时，应以适用版本和游戏内实际表现重新核对。专有名称未确认官方简中时保留英文。

## 组件与概念说明

### Soaring Spear

**类别：长矛武器**

这是一把稀有长矛，属于第一套武器，重点是快速完成准备动作。图片对应 Soaring Spear 底材。

### Ancestral Tiara

**类别：头盔**

这是稀有头盔的随机名称，底材为 Ancestral Tiara。高局部 Energy Shield 为防御配套提供基础。

### Slipstrike Vest

**类别：胸甲**

这是稀有胸甲的随机名称，底材为 Slipstrike Vest。Beastial Skin 和 Spectral Ward 是与它配套的天赋节点。

### Beastial Skin

**类别：天赋节点**

这是天赋节点，强化胸甲提供的闪避价值。它与这件高闪避胸甲相配合。

### Spectral Ward

**类别：天赋节点**

这是天赋节点，利用胸甲自身闪避建立 Energy Shield 基础；不是一件名叫 Ward 的装备。

### Runeforged Secured Wraps

**类别：手套**

这是稀有手套的随机名称，底材为 Runeforged Secured Wraps。它提供投射物速度和技能等级等输出属性，也提供部分防御。

### Daggerfoot Shoes

**类别：鞋子**

这是稀有鞋子的随机名称，底材为 Daggerfoot Shoes，主要补混合防御与抗性。

### Unset Ring

**类别：戒指**

这是稀有戒指的随机名称。Unset Ring 底材提供额外技能槽，其他词条补生命和抗性。

### The Taming

**类别：暗金戒指**

这是一枚暗金戒指，给 Wind 技能提供多种地面强化条件，是这套 Twister 配合的重要来源。

### The Ordained

**类别：暗金长矛**

这是一把暗金长矛，位于偏输出的第二套武器，并授予 Righteous Descent。

### Guiding Palm of the Eye

**类别：暗金权杖**

这是一把暗金权杖，提供额外冰冷伤害和 Spirit，并授予 Purity of Ice。

### Yoke of Suffering

**类别：暗金项链**

这是一条暗金项链，利用敌人实际承受的元素异常增加收益。

### Perfect Iron Rune

**类别：镶嵌物**

这是一枚镶嵌符文。胸甲中的两颗用来强化装备局部防御；它不是技能或天赋。

### Headhunter

**类别：暗金腰带**

这是一条暗金腰带，击杀稀有怪后取得临时能力，更偏向刷图场景。

### Gemling Legionnaire

**类别：升华职业**

这是角色选择的升华职业。它提供 Virtuous Barrier、品质和宝石等级等配套，不是一件装备或一颗辅助宝石。

### Deflection

**类别：防御属性**

这里说的是与角色防御有关的属性，不是在列出一个需要主动使用的技能。胸甲词条和部分天赋会参与它的构成。

### Ward

**类别：防御属性**

这是手套等装备提供的另一层防护。这里并不是叫 Ward 的一颗技能宝石，也不能把它和 Energy Shield 当作同一个数值。

### Mark

**类别：技能类别**

指用于标记敌人的一类技能。这套构筑中的例子是 Sniper's Mark；Mark 使用速度影响施加这类标记的动作。

### Whirlwind

**类别：场上效果**

这里是 Whirling Slash 创建、能被 Twister 利用的旋风对象，不是一颗还需要单独装备的宝石。

### Spirit

**类别：保留资源**

用于维持多种持续技能。要比较同一武器状态下的可用容量与同时开启的技能占用。

### Energy Shield

**类别：防御数值**

通常简称 ES。这里是与 Life 分开的防护数值，来源包括装备和天赋；这套构筑会利用头盔与胸甲的配套来建立它。

### ES

**类别：防御数值的简称**

Energy Shield 的简称。它与 Life、Ward 不应作为同一个数值重复计算。

### Life

**类别：生命数值**

角色的生命。生命药剂和相关再生处理这部分损失，不能直接认为它们会把 Energy Shield 同时补满。

### Mana

**类别：技能消耗资源**

使用技能可能支付的资源。理解循环时，先看每次及持续消耗，再看再生、药剂和满足条件的其他恢复。

### Affinity

**类别：技能增益资源**

Trinity 通过元素命中积累的资源。命中中的最高元素伤害类型影响获得哪一类，积累之后再提供收益。

### Rage

**类别：状态资源**

这组 Whirling Slash 通过 Rage III 的相关命中建立它。是否已经达到上限，会影响该辅助提供的速度条件。

### Frenzy Charge

**类别：充能**

这套构筑中由相应标记或控制事件建立的充能，可参与 Barrage 等技能的消耗与增益。

### Frenzy Charges

**类别：充能**

Frenzy Charge 的复数写法。需要同时观察产出、维持和消耗，不能只看起手时是否满层。

### Power Charge

**类别：充能**

与 Frenzy Charge 不同类型的充能。Empowered Sparks I 要求产生这一类型，不能把其他充能的产生视为同一条件。

### Wind

**类别：技能标签**

Twister 与 Whirling Slash 所属的技能标签。The Taming 针对这一类技能提供相应地面强化条件。

### Bonded

**类别：词条条件**

标注在部分镶嵌效果前的条件。读装备时要把这个条件一起核对，不能直接把后面的数值都当常驻属性。

### Skill Speed

**类别：属性与同名天赋小点**

这里概括技能速度投入。树上存在多个同名而图标不同的小点，因此不以其中任意一个图标代表全部节点。

### Daze

**类别：敌人状态**

这里描述敌人处于某种状态。相关天赋利用该状态取得收益，不能只因点了天赋就把状态当永久存在。

### Shock

**类别：元素异常**

这里指异常状态，不是在推荐一颗同名辅助。它与 Combat Frenzy 要求的 Electrocute 不是同一条件。

### Electrocute

**类别：控制状态**

这里指控制状态，是 Combat Frenzy 的条件之一；存在闪电伤害不等于这个状态已经持续生效。

### Ghost Shrouds

**类别：技能层数**

Ghost Dance 建立的层数，会随受击和恢复过程变化。不是额外需要装备的一组宝石。

### Shroud

**类别：技能层数**

这里是对 Ghost Dance 层数的简称，和一颗同名辅助宝石不是同一个语境。

### Onslaught

**类别：增益状态**

此处由护符 The Fall of the Axe 在满足触发条件后提供，不是装备护符就永久开启。
