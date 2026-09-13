# 最终验证与失败修正

按 [build-and-refine.md](build-and-refine.md) 形成机制完整、合法且资源闭环的基础版本后使用本文件。
先完成一次符合目标等级的主动质量收尾，覆盖高影响武器、辅助、天赋路径、珠宝、符文/灵魂核心
和战斗配置，再进入首次正式 Judge。
这次收尾不以 Judge 报警为前提；只有通过正式 Judge 的 attempt 才能成为 passing baseline。

本文件负责检查顺序和恢复决策；候选、Research 使用、attempt 与失败审计的具体字段见
[output-contract.md](output-contract.md)。通过正式评估后按 [delivery.md](delivery.md) 选择、保存和交付。

## 反馈模式与证据边界

除非用户在本次请求中明确要求“严格模式”或 `--strict-judge`，否则 preflight、checkpoint、
lifecycle 和 `evaluate_generation_candidate` 统一使用 `strict_mode=false`。默认仍运行完整计算，
只使用确定性 `hardFailures`、合法性、快照绑定和事实诊断；不得补写或反推被抑制的评分、质量档位、
playability/quality warning、reward 或主观 caveat。严格模式统一传 `strict_mode=true`，第一次
正式 Judge 后同一 run 不得切换。

游戏内机制与当前规则、Family Research、当前 Graph/corpus 及明确的外部机制/实战证据决定
构筑身份和玩法结构；PoB 可建模性界定数值证据范围。不得因触发率、重叠、轮转、来源技能或恢复
不可建模而替换核心机制，或把合法的 meta host + payload 拆成自施法代理。保留正确结构，补充
机制验证并收窄数值声明。PoB 能力不足本身不决定合法性或交付档位；最终措辞仍服从可信 receipt
的 `deliveryStatus`。

## 配置锁定与最终审计

1. 对终局/Boss 目标调用一次 `apply_combat_profile`，选择符合用户目标的 tier，并传最新
   `expected_state_hash`；也可用 `set_config` 设置相同 key。公共 `set_config` 是只修改显式字段的PATCH；
   `apply_combat_profile` 完整替换自己的Boss tier与六个布尔条件，false会清除旧值；二者返回最新stateHash。
   读取返回的 assumed 清单，只保留
   构筑实际能产生的条件：感电需要来源，诅咒需要已配置技能，power/frenzy charges 需要生成手段，
   `full_es` 需要 ES 构筑。默认开关全开，不能直接接受；未应用 profile 时条件全部关闭，依赖
   这些条件的输出只能视为对应下限。将最终 assumed 清单原样记入本轮失败审计摘要与工具引用；
   后续重试沿用同一战斗假设，不能为通过 Judge 临时切换开关。
2. 确定本次唯一的 offense group 和精确主动技能名：纯清图目标选 clear group，Boss/均衡目标选
   single-target group，用新鲜fingerprint的`set_skill_group_state`锁定对应active effect。
   后续 Support审计、checkpoint、Draft、活动 lifecycle 和 Judge 复用这一
   目标；不传 `Load *` / `Reload *` 内部形态。
3. 装备、天赋、珠宝、Rune 和 config 锁定后，重新生成最终 Support/Jewel/Socket 回执。
   当前状态适用的审计必须新鲜；`stale/missing`、明确失败、未应用正收益都先修复，不能靠
   早期探索结果进入 Judge。
   - Support 覆盖用户可编辑组及需要辅助的真实来源组，用精确 group 和新鲜 fingerprint。
     `support_audit_v5`的`positiveGainCombinationAvailable=true`表示完整组合有已证实正收益；
     应按完整方案更新并重审，包括`positiveGainSupportsMissing`为空但`supportsToRemove`非空的纯移除。
     同条件的新测量错误或反证会撤销旧数值回执的沿用权限；缩窄查询或换目标不能洗掉已证实的整改。
     搜索保留PoB实际观察到的使用条件辅助；不能仅因更高DPS自动加入移动/站立/充能等使用门槛。
     Agent决定改变此类玩法条件时，先明确改组再重审；使用条件合同不证明实际覆盖率。
     辅助生成或删除附属effect后，按实际列表中的精确名称与PoB effectId确认输出，不能沿用旧序号。
     辅助可以分别服务同组 host 与 payload，但每个辅助都必须由 PoB 确认作用于有合法来源的 active
     effect；自身授予或无根循环不能反向授权。生命保留不得耗尽可用生命，CI与释放Spirit均不豁免。
     当前可用性独立于PoB模型、等级曲线及上游`released`字段。工具按版本化静态移除证据过滤，
     `unavailableInGameCandidates`单列已排除组件；模型缺失仍放在`uncoveredCandidates`，二者不混用。
     数值能力绑定所选精确输出。当应用、结构和约束检查完整，原生PoB明确识别数值模型
     缺口时，可按 `capability_gap` 以unknown继续Judge，交付仍为candidate；测量错误、证据不全和
     可修复缺口继续阻断。`noSupports=true` 不需制造辅助审计；不可写来源保留真实结构和验证缺口。
     代理或Herald缺频率时，不把负载速度或零DPS当有效全程排序；声明持续/耐久/持续伤害物体而
     缺少其时间与持续伤害模型时，正的局部命中同样不足。保留模型缺口和不支持数值排序的状态，
     以待验证候选继续；不因错误面板推荐拆掉配套，也不因未建模降低技能的采用优先级。
     已建模范围内的数值升级仍须完整组合比较。模型缺口下由Agent按机制、条件及粗估选择组合，
     核实际辅助适用性和硬合法性，明确标记未验证取舍；不能把局部面板改善或粗估说成完整净收益。
   - 等级 ≥90 的额外珠宝槽审计保留精确 `protected_node_ids`，以当前真实候选审查全部可达槽。
     正收益经 `apply_next_jewel_socket_decision` 原子应用后，在新状态重新审计；受保护策略下的
     `policy_limited/inconclusive` 可以继续 Judge，但交付保持 candidate。低于 90 级不新增此质量
     门禁；已经分配的珠宝槽仍须填入真实珠宝。
     候选底材、等级、来源或普通词缀识别有问题时，按输入诊断纠正后重试；不把未识别词缀当零收益。
     只有全部槽位都尚未测量、仅因安全叶节点不足而受限，工具才允许在相同 goals 和保护节点下
     更换候选。部分测量、测量错误及待应用正收益保持 pending；不得修改状态或删回执绕过。
   - Socket 使用`item_socket_review_v2`且必须对应实际装备。`socketed/partial_socketed`均是待应用
     方案，携原`craftReceiptRef`完成可信`equip_item`后，后者才转为`partial_no_positive`，
     保留原孔容量并允许无收益余孔留空。`no_positive/not_applicable`需完整测量才能全部留空；
     `measurement_error/capability_gap`继续是验证缺口。重测失败会撤销该槽旧pending方案，
     不能复用旧方案结论。仅有`Rune:`声明而无匹配效果/receipt不算镶嵌。
4. 调用 `inspect_generation_checkpoint`，传本次反馈模式和 offense group/name。它合并
   completeness、preflight、有界 stats 和 defenses；仅同一引擎/PoB进程中的同一语义状态复用结果。先复读
   `buildSummary` 的职业、升华、等级和主技能，只有具名局部诊断才另读 `get_build()`。

## 处理 checkpoint

`generation_checkpoint_context_changed`表示检查期间引擎或缓存上下文已变化。先确认活动构筑及
精确输出仍对应本候选，再重新调用checkpoint；进程重建丢失活动状态时，按已有可信恢复规则恢复
构筑和所需证据后再检查。不能沿用旧validationRef或通过结论；此类重查不消耗正式Judge额度。

先执行可恢复修正，再判断是否需要用户介入。发现辅助已移除、禁用或不适用时，查精确详情的
`availability`与当前补丁；若尚未录入可用性目录，阅读官方页面与独立旁证，再向`optimize_supports`
传`availability_reviews`：每项含精确`componentKey`、`targetPatch`、`reason=removed|disabled`，
以及至少两项`sourceReviews`（`url`、`assessment=supports_unavailable`、`relevanceReason`）。
必须审读内容及其适用补丁；仅粘贴URL、名字、搜索结果、PoB能计算或缺少刻印入口都不够。
这只是本引擎会话内的`agent_reviewed`排除，不是内部Research回执，也不改全局语料或历史知识。
保留该结构化审读声明以便会话恢复后重交，并把来源放入输出的普通toolReferences与取舍说明。

在同一精确输出、目标和资源约束下重新搜索完整组合。旧方案含失效辅助时，不能只删掉那一项就沿用
旧收益；采用新完整方案后再次审计。若当前组本身有失效辅助，按`currentUnavailableSupports /
supportsToRemove / recoveryAction`修复，面板下降不构成保留非法组件的理由。按下表刷新Draft及
受影响检查，继续lifecycle、Judge和交付，不把这一可修复问题转交用户。只有实际工具不可用、
恢复失败、关键证据无法取得且无法形成合法候选，或需要用户改变锁定要求时，才说明具体未解阻碍。

先处理 `preflight.blockingIssues` 和 completeness 硬失败，再处理
`createQualityChecklist` 中的辅助、机制依赖、占位物品、装备可获得性、护符/药剂、珠宝、镶嵌和
续航项。`qualityRepairPlan` 提供定向入口；各类修正与额度统一见下表。
`createQualityChecklist`、`deliveryStatus` 在 hard-only 下仍是事实输出，不能因为 Judge 数值高
而略过。特别检查：

- `Scaffold ...` 占位装备、rare/magic 缺少 `Item Level`、装备/基础宝石等级或属性需求不合法，
  以及黄装前后缀数量、词缀组排他、词缀物品等级问题，均应在正式 Judge 前修复。装备/天赋的
  `+levels` 不等于基础宝石等级非法。
- 新生成 ≥80 级候选缺少 Flask 1/2、使用 Normal Flask 或没有可识别词缀的 Flask，会触发
  `endgame_flask_loadout_incomplete`。Unique Flask 合法，至少一条合法词缀的 Magic Flask 合法；
  Magic Flask 未达到 1 前缀/1 后缀属于质量缺口，仍应主动补齐。
- 已分配天赋珠宝槽必须填满，`unspentPoints` 必须为 0。Spirit 按未封顶账本检查超额保留和
  一致性；低利用率不构成硬失败。`opportunityReviewRequired=true` 时完成机会成本检查，并按
  [delivery.md](delivery.md) 处理最终仍存在的 Spirit advisory。
- 攻击类终局主输出检查 `HitChance`；低于约 95% 时补充命中来源，再正式评估，并在摘要说明。
  法术无命中判定，跳过并说明原因。接近剧情结束或进图时，主输出仅零到一个辅助是高优先级
  完整度提醒，应实测合理组合或解释有意保留的原因；它不是辅助数量硬规则。
- Judge 对新生成 ≥80 级候选要求火/冰/电各 ≥60%、非 CI 混沌 ≥30%，CI 只豁免混沌。
  Lifecycle 的额外元素门槛按活动 PoB 实际等级计算：45–64 级各 30%，65–79 级各 50%，
  80–89 级各 60%；45 级以下与 90 级以上不增加该门槛。`resists_capped` 只是兼容 check ID，
  不代表一律需要 75% 满抗，也不能用 stage 名称或调用者提示改变等级档位。

## Draft、活动 lifecycle 与正式 Judge

Research 深读完成、最终摘要形成后，按 `start_generation_run` 返回的 draft skeleton 填写安全
输出，调用 `validate_generation_draft` 并传相同 offense group/name。服务端观察最终 PoB 的
辅助集合、主导命中类型和 Mana/Life 支付域；Draft 不消费 run，也不占正式 Judge attempt。
先按返回字段路径修复 run/request、版本、premise、application/caveat 与深读引用问题。
Research receipt 必须在当前 run 创建后查询；Judge 绑定的 `researchMemoryRef` 与各对象版本
须保持一致，具体规则见 [output-contract.md](output-contract.md)。

Draft 冻结 Research 决策结构。Judge 后可以依据结果补充选择理由、机制/兼容性/取舍说明、应用、
验证证据和实现/验证/退出步骤；不得借文字更新改变来源案例、采用/拒绝决定或跨案例依赖。
同一PoB/Blueprint下取得合法新深读证据、修订premise/insight/package决定，也应重验Draft；
只改允许叙述或无序引用顺序不刷新。若Judge返回`generation_draft_evidence_required`，在原run
重交该设计完成完整校验；`evidenceRebuilt=true`仅重建内存证据，不续期、不替代旧Judge快照。

Draft也绑定设计实际引用的证据层级与reviewBasis；更换证据或审读依据必须重验，不能在最终输出
中直接提权。纯summary改写、无序引用顺序和无关诊断引用不触发设计修订。旧受管run若返回
generation_contract_upgrade_requires_restart，应按新合同开启run，不补改旧marker或artifact。
每个package/跨案例plan的原来源关联分别保留；旧引用仍存在于别的claim/决定下不能替代本项
原关联。Judge后可为同一决定追加旁证，不能移除、交换或挪用原引用。缺关联marker的活动Draft
需完整重验；历史恢复只从受检Judge bundle的原计划读回关联，不从新candidate补造。

使用活动 lifecycle gate 时，传当前阶段、精确 offense group/name、本次反馈模式和
`detail="compact"`，按下表限制调用。保存前先修复已确认的真实阻断；required failed/unknown
只能保留 candidate，不能伪造通过。`endgame_final` 的 required checks 是主技能镶嵌、基础
防御和续航；PoB 建模支持、core threshold、upgrade budget、pinnacle readiness 是 advisory。
实际存在的未建模恢复层可能得到带 `verificationRequired` 的通过结论，仍需验证真实覆盖，不能
据此编造吞吐。`detail="full"` 只用于具名局部诊断。

若阶段要求关键组件证据，在 lifecycle 的 typed `state` 中声明所选机制实际依赖的组件
kind/name/stable key 与 evidence refs。工具从同一快照核对实物；不要提交“已验证”布尔值。
同 engine、state hash 和精确输出的 checkpoint 会复用该声明并重新观察，补证据后无需重复填表。
缺声明保持 unknown；新的空声明或失配声明会撤销旧判断。状态或输出改变后重新验证。

随后调用 `evaluate_generation_candidate`，传本 run 凭据、candidate、版本、本次反馈模式及
同一 offense group/name。正式 Judge 捕获不可变快照并在独立引擎评估；`evaluate_build`、
`pinnacle_readiness` 和 Agent 自拟评分不能代替它。重复 enabled 组、无合法 host 的普通多主动组、
重复辅助和确定性非法状态应被预检非消耗式拒绝。合法 host + payload 共组可以保留，但具体标签
兼容性仍需当前机制/Research 验证，结构放行不等于任意 payload 都合法。

保留返回的 `attemptIndex`、`attemptConsumed` 和安全结论。可信临时状态与 Judge 报告由 receipt
按 attempt 补入最终对象，不重复手填。`selected_skill_conflict` 不消费 attempt；Judge 执行错误
保留为错误，不能改成构筑失败或已评估。`trustedEvaluation` 只证明快照与 Judge 绑定，
`versionContextTrusted=false` 要求继续核对本次 freshness，不能宣称已获当前版本认证。

## 变化、重验与额度

以下三种“两轮”分别计数：质量返工、核心机制重建、正式 Judge 重试；不可相互替代或通过新建
run 重置。保留本次用户需求与明确锁定项。

| 变化或事件 | 失效范围与下一步 | 额度与停止条件 |
| --- | --- | --- |
| 状态、目标、参数及Research实质决定均未变化 | 复用检查结果；不重放相同Research查询或刷新Draft marker；内存证据缺失时按工具要求完整重建 | 不以形式轮数重复；重建不续期 |
| 版本失效候选、输入错误或回执陈旧 | 审读并绑定精确证据，排除已确认失效的候选，在完整有效候选范围重算，修正后重审并继续交付 | 资料/工具输入纠错不计质量探索或核心重建，不消耗正式Judge；同条件重复且没有新证据/方案时不得空转 |
| 装备、天赋、珠宝、Rune 或 config 改变 | 使用最新 state hash；锁定后重做最终 Support/Jewel/Socket 及 checkpoint。若机制 signature 不变，不要求重复 Research | 局部修正不计核心重建；仅实际消费的正式评估计 Judge attempt |
| 核心输出、辅助组合、主导伤害类型或 Mana/Life 支付域改变 | 重验 Draft；只有 Blueprint 机制意图也改变时才重验 Blueprint。重新确认 offense group/name，并刷新受影响检查 | 单纯辅助或局部天赋修改不自动算核心重建 |
| 升华或核心主技能身份改变 | 先重新解析身份并在本 run 重新查询 Research，更新新查询引用，再完成 Blueprint/Draft 与最终检查 | 保留用户锁定项；不可沿用原身份授权 |
| Research 决策结构改变 | 重新完成对应知识取舍与 Draft；不得在 Judge 后仅改文字来变更案例、package 决定或跨案例依赖 | 旧 passing attempt 不会自动获得新绑定；保存限制见 delivery |
| `qualityRepairPlan` 指出质量缺口 | 定向返工后刷新相关最终检查 | 最多两轮质量返工；仍有 failed 项只可保留 candidate，硬失败仍须阻断 |
| 确需推倒核心机制 | 在同一 run 内重建；局部技能组问题先用精确原子编辑，只有方向确需重建时才用 `new_build` | 最多两次核心机制级修复/重建；仍无法证明但硬合法可交付待验证候选，已确认真实失败且补救失败则停止交付 |
| 需要活动 lifecycle gate | 每个正式 attempt 前最多一次；同状态同目标复用。状态改变后，在下一 attempt 前生成新 gate，不要求上次 gate 必须失败 | 调参用 checkpoint；artifact 保存后另做一次独立验证 |
| 正式 Judge 未通过且存在可修正项 | 在当前会话、同 run 和反馈模式下修正后评估；预检 `attemptConsumed=false` 不占额度 | 初次加最多两次正式重试，共三次；以工具返回计数，`retry_limit_reached` 后停止 |

## 结果核验与修复选择

每轮只记录简短结论、具体修改计划和保留 caveat，区分真实构筑失败、建模/数值证据缺口、选错
技能、工具/数据缺口或没有实质失败；不保存逐步推理。`passed=true` 不代表值得推荐：
`blocked` 不导出，`candidate` 只能称技术候选/待验证方案，`recommended` 才能称推荐成品。

默认模式只处理硬失败和事实诊断。严格模式另区分确定性非法、严重可玩性短板、推荐质量缺口和
建模范围；若有 `playabilityFailures`、`qualityBand="barely_playable"`、目标相关维度为 0，
或 `offenseEvidence.floorStatus != "met"`，优先修正或核验。重试耗尽后硬合法者可供人工研究，
但只能称弱原型/待完善候选。`scoreApplicability="unavailable"` 单独出现时限制综合分与 DPS
强度声明，不自动降级、换核或证明 BD 非法。

“开荒顺畅”还需清图、单体/Boss 职责及资源恢复证据；单一技能兼任两者时提供 PoB/机制依据或
明确实战 caveat，否则补充单体方案或限定为清图方向。续航结合未保留资源、使用频率、自动恢复、
药剂、击回/偷取、技能效果和完整轮转；不要按总蓝量与单次耗蓝的固定倍数删辅助。

`unmodelled_mana_recovery_requires_verification` 只表述为“需验证未建模恢复覆盖”。先查当前
corpus、Graph、Research 与机制资料；普通 Create 仍有证据缺口时可联网核对或保留实战验证任务，
Blind 的联网边界按 [blind-mode.md](blind-mode.md)。静态缺口和缓冲秒数不能直接证明“会断蓝”；
确认只有普通魔力瓶承担持续缺口且无其他覆盖时，才按真实失败修复辅助、天赋、技能、装备、护符、
镶嵌、药剂或轮转。未建模 Mana 恢复不能覆盖确定性 Life 失败；setup/payoff 循环仍无可信模型时
保持 candidate。外部证据可补充机制说明，不能代替本轮 Research 深读记录把 premise 改成 resolved。
