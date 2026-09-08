# 机制蓝图

在Research执行合同与package决定完成后、任何PoB写入/装备规划前读取。no-memory模式没有Research
合同，以实际查询到的图、机制和语料证据设计，仍执行同一蓝图验证。

## 设计内容

蓝图是Agent撰写的、可证伪的机制与玩法综合说明，不是固定表单或自动装配指令。组织形式自由，
只解释当前BD相关的因果关系：

- 伤害从何产生，如何投送、缩放和保持在线。
- 普通怪群的清理方式，以及密度/击杀依赖。
- 无小怪Boss的输出、启动、叠层、爆发和停手窗口。
- 防御池、减伤/避免、恢复和紧急失效窗口。
- Life、Mana、ES、Spirit、充能的支付/恢复，区分命中/未命中、击杀/无击杀状态。
- 操作轮转、必须维持的动作与条件。
- 哪个技能、升华、局部天赋或装备职责实现每个采用机制。
- 失败条件、模型限制、尚缺证据及具体验证任务。

明确区分来源事实与设计推断。缺证据时做定向查询或标为hypothesis/unknown，不能编造交互、数值
或uptime；保留Research的conditions、failureConditions、排除条件和验证任务。实装时仍核对原始
Research及当前静态/PoB事实，蓝图不替代这些来源。

## 薄证据索引

正文附带供后续审计使用的小型索引，字段位置见[提交数据合同](output-contract.md)：

| 索引 | 内容 |
| --- | --- |
| `claims` | 关键机制结论；状态为grounded/inferred/hypothesis/unknown/rejected，并关联实际证据、条件、失败情形和验证任务 |
| `coverage` | damage_delivery、clear、boss、defense、life_recovery、mana_recovery、spirit、rotation各方向显式标为covered/not_applicable/unknown |
| `unresolvedQuestions` | 后续实装和Judge仍应看到的缺口 |

不要以填满索引替代机制综合。Research package采纳、组件insight、蓝图claims及最终candidate承担
不同审计职责，可以共享证据引用，不能用其中一个对象代替其余对象。

## 验证与修订

用当前candidate ID、versionContext、最终researchMemoryUse/researchExecutionPlan（适用时）、
蓝图及引用的ToolReferences调用`mcp__poe_build__validate_generation_blueprint`。每个非unknown claim关联
实际Research/package/record或图/机制/语料引用。ToolReference按[提交合同](output-contract.md)显式
填写evidenceKind：grounded/inferred/rejected不能依赖unverified；hypothesis可保留未验证来源，
但必须给verificationTasks。外部agent_reviewed必须附reviewBasis，仍是Agent审读声明，
不等于内部工具执行或语义已获认证；不能登记未调用工具或伪造queryRef。
返回的evidenceAudit区分内部来源身份、Agent审读与未验证假设，不证明数值或合法性。

accepted后保存blueprintRef，并在最终candidate中使用同一蓝图和匹配ToolReference。此前不能
mcp__poe_build__new_build、分配天赋、评估暗金、mcp__poe_build__plan_gear、craft或equip。

新证据改变核心输出、防御、资源或轮转意图时，先修订并重验蓝图，再继续实装。仅实现签名变化与
Draft重验的区别见[验证与恢复](validation-and-recovery.md)；不要求普通数值微调重写整份蓝图。
引用的工具身份、证据层级或审读依据改变也须重验来源绑定；仅summary改写和引用顺序变化不提权。
