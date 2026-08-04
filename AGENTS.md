# AGENTS.md - Poe2 BD Creator Agent 指南

这是本仓库给 Codex、Claude Code 和其他编码 agent 使用的标准工作指南。长期有效的规
则放在这里，具体阶段执行清单放在 `docs/phases/`。

## 文档语言策略

- `docs/ARCHITECTURE.md` 和 `docs/ARCHITECTURE.CN.md` 是当前唯一维护双语的文档。
- `docs/PROJECT_SPEC.md`、`docs/SCHEMAS.md`、`docs/phases/*.md`、`AGENTS.md`、
  `CLAUDE.md` 以及其他仓库说明文档只维护中文。
- 不要新增 `.CN.md` 副本，除非用户明确重新改变语言策略。

## 项目方向

PoE2 BD Creator 是 verification-first 的 Path of Exile 2 BD 研究与生成工具基座。
Codex、Claude Code 等外部成熟 agent 负责研究、推理、比较、反思和 BD 合成。仓库本
身提供可重复执行的工具、结构化记忆、图知识、安全边界和评估合同。BD 创造不能变成
“Agent 给 plan，程序自动补完整 BD”的流程；整个构筑创造、查询取舍和失败修正仍由
Agent 主导。

长期闭环是：

```text
成熟 BD 数据 / PoB 导出 / pobb.in / poe.ninja
  -> quarantine-only raw intake
  -> 外部 Researcher Agent
  -> clean fragments + graph knowledge + long-term memory
  -> 外部 Architect Agent 按需查询图、记忆、语料和 PoB/计算工具
  -> Agent 主导候选 BD 创造和可评估临时状态搭建
  -> Headless PoB judge 与安全报告
  -> 成熟原 BD 的安全 Profile 与 FamilyTarget
  -> 同 Family / 同等级的独立盲测 Create
  -> 独立 Comparator 逐维比较（Judge 仅作 advisory）
  -> 具体知识回流 Research，跨维生成经验进入本地 Learning Memory
  -> 后续案例召回、correction 与趋势复审
```

仓库不应再增长项目内 autonomous LLM/provider loop。不要新增项目自带的 OpenAI/Claude
API runner、隐藏 agent loop，或持久化模型调用 prompt/report 日志。

## 不可协商规则

- 不要从零编写新的数值 BD 引擎。数值声明必须使用现有 Headless PathOfBuilding-PoE2
  wrapper，或明确标记为 unverified/unmodelled。
- 没有 PoB/modelability evidence，就不能声明 DPS/EHP/抗性/Spirit 合法性。
- 没有 static source，就不能创建 physical graph node。
- 没有已存在 graph node，就不能创建 semantic graph edge。
- 没有 typed tool，就不能让 agent 查询图。不要暴露 raw Cypher/Gremlin/SQL 拼接给
  agent。
- 模糊组件查询只用于候选发现：先 `search_graph_components`，再用
  `resolve_graph_component` 确认 stable key；模糊或向量相似度不能直接授权 semantic edge。
- Family identity 统一使用玩家 `active_skill` 的 `skill:` stable key。物理图已确认关联的
  `gem:` key 可以作为 Research 查询别名，但不能直接替代 FamilyTarget、TargetAnchorIdentity
  或 StageFamilyIdentity；typed receipt 必须保存两者的等价 key 集合。
- Research 与 PoB 对同一组件可能使用不同显示名。target anchor 仍以 stable key 为身份权威，并
  保存 artifact 实际显示名；候选 stable key 必须先由 typed Family discovery receipt 验证，
  artifact 名称与候选展示名不同时，还必须由 artifact 的同一 graph snapshot 把 artifact 名称
  唯一解析到该 stable key。解析缺失、歧义、跨 snapshot 或 key 不同都必须失败关闭，不能因此
  放宽职业、升华、Family、artifact 或 lifecycle。
- 没有 patch/version/status，就不能进入 durable memory。
- 没有 copy-safety pass，就不能持久化成熟 BD 知识。
- 没有后 3 例相对前 3 例的四项联合趋势，就不能声称 Phase 7 出现初步进步信号；十案例趋势
  不能声明因果证明。
- Phase 7 不允许比较后修复或重新生成同一案例；Phase 5 已有有限内部 retry 不受此条影响。
- Judge 数值只能作为 Phase 7 `advisoryOnly` 附件，不能自动决定 Comparator winner 或写 reward。
- Create packet 只能包含 FamilyTarget、等级、版本和默认目标，不能泄露原 BD 装备、天赋、技能组、
  机制摘要或 Judge 结果。
- Phase 7 Blind Create 不得读取或调用 Phase 8 `StarterResearchPacket`、starter cache 或
  progression 状态；联网开荒证据只属于显式 progression 模式。
- Phase 8 不能修改普通单阶段 Create 的等级语义、Research recall、生成/Judge 或导出合同。
  progression 必须先通过普通 Create 生成并绑定 immutable target anchor；最后目标阶段复用同一
  artifact/source hash，不得重新生成一个较弱目标或用桥接形态替换。
- 每次普通用户触发 Create 时，除非请求明确只产出单个固定目标/最终 BD 且不要开荒过程，否则
  必须先阻塞式询问是否生成完整开荒成长过程。用户回答前不能调用 freshness、Research、
  `start-run`、progression 或 PoB/计算工具；本次请求只问一次。选择“需要”进入 progression，
  选择“不需要”进入普通单阶段 Create。`referenceBlind=true` 的内部 Blind Create 禁止追问，
  继续按锁定 packet 执行。
- 新 progression 在未指定唯一目标 Family 时，必须先用基础职业、精确 patch 和天赋树版本调用
  `query_research_memory(detail_level="family")` 请求 10 个成熟 Family；不足 10 个返回全部合格
  Family，少于 2 个暂停并报告 Research 缺口。Agent 必须比较 discovery receipt 实际返回的
  全部 2–10 个候选，按机制闭环、Research 支持、目标契合与强度证据、可玩风险和 modelability
  完整排序，第一名为目标、第二名为备用。候选阶段不跑完整 Judge、不调用全局 optimizer；
  modelability 不能在前三项均无优势时单独决定目标。用户提供完整唯一 Family 时跳过 discovery。
  选定的升华/主技能必须与随后绑定的 target anchor 一致；首次目标失败后只有 Agent 可基于证据
  显式切换一次备用 Family，Judge 不自动换流派。
- Create 当前默认禁止 `optimize_build` 和全局被动树重排。Agent 已经决定的机械变更应通过
  `apply_build_mutation_batch` 按 `bootstrap / mechanism_shell / skill_loadout / passive_delta /
  required_gear / ordinary_gear / config` 职能拆成小事务；不得把整个 BD 混进一个批次。只有以
  `new_build` 开始的 bootstrap 可省略输入 hash，后续事务必须串联上一批 `outputStateHash`。
  搜索、optimizer、隐式装备槽和隐式珠宝孔不能进入批次。失败只回滚当前职能事务；只有
  `rolledBack=true` 才能确认恢复，`recoveryRequired=true` 时必须停止并恢复活动状态。
- 每个 progression 阶段（包括 `campaign_early`）都必须交付该等级下完整、强力且可玩的阶段
  BD，不得用“最小壳”“仅过渡”或空装备槽降低完成标准。蓝图必须在 PoB 构筑前确定阶段方向；
  claim 后设计冻结，同一阶段只允许一次初始化，后续使用按职能拆分的局部 delta。除蓝图已声明
  且填写 `rebuildReason` 的重大转型外，后续阶段默认继承上一 artifact；确定性合法性、资源、装备、
  天赋或辅助问题必须局部修复，只有现有的一次版本化 stage replan 可以在失败后改变整体方向。
  这些执行约束不能变成固定 DPS/EHP、装备槽或天赋点等主观硬门槛。
- Judge 对新生成的 80 级及以上候选使用确定性终局抗性门槛：火/冰/电分别不得低于 60%，
  非 CI 构筑的混沌抗性不得低于 30%；CI 只豁免混沌抗性。该门槛由共享 preflight 与正式
  Judge 入口共同执行，预检失败返回 `attemptConsumed=false`。79 级及以下、可信第三方参考
  构筑仍只回读抗性作 diagnostic，不产生这组 hard failure；元素 Max Hit 和其他防御层继续按
  各自合同评估。
- Progression 的 Lifecycle 元素抗性门槛独立于 Judge，但必须按活动 PoB 的实际等级计算，而不是
  按可重叠的 lifecycle stage 名称或调用者提示计算：45–64 级火/冰/电各 30%，65–79 级各 50%，
  80–89 级各 60%；45 级以下和 90 级以上不增加 Lifecycle 百分比门槛。90 级以上仍由 Judge 的
  60/30 终局规则负责，Lifecycle 不得再叠加 75% 满抗要求。
- Create 的 Judge 反馈默认使用 `strict_mode=false`（`feedbackMode=hard_only`）：内部计算照常
  执行，但对 Agent、可信 attempt、artifact、retry、Review 和 progression 只暴露确定性
  `hardFailures`、`passed`、快照绑定和安全诊断，不返回 aggregate、quality band、
  playability/quality warning、reward、主观 caveat 或基于它们的自动结论。只有用户明确要求
  “严格模式”或调用方手动传 `strict_mode=true` 时，才可在本次 run 全程使用完整反馈；首个
  attempt 后禁止切换模式。checkpoint 和 lifecycle 的建议性字段遵循同一开关，原始 PoB 数值和
  确定性 gate 不受影响。
- 重复的 completeness、preflight、stats 和 defenses 检查使用
  `inspect_generation_checkpoint`，以语义 `build_state_hash` 合并；状态改变后必须生成新检查，
  正式 Judge 与 artifact-bound lifecycle verification 仍是独立可信步骤。
- `inspect_generation_checkpoint` 和 `evaluate_generation_candidate` 必须复用同一个无评分
  `HardLegalityAudit`。属性、装备/宝石等级、武器兼容、Spirit、普通与武器组天赋预算、黄装
  词缀等确定性非法状态必须在写 Judge receipt 前拦截，返回 `attemptConsumed=false`，不能消耗
  三次正式 Judge 额度。装备优化或升级探针也必须在临时换装后审计整个角色，并拒绝属性不足或
  已装备槽位消失的候选。
- `craft_item` 返回的 Perfect Essence、符文和腐化效果必须由 PoB `crafting_options` 派生的
  `craftReceiptRef` 证明；后续 `equip_item` 或批量 `equip_item` 必须原样传该引用。制作、
  装备写入、completeness、Judge 前共享审计和 artifact 保存统一使用来源感知物品合法性，不得
  再用独立的普通词缀检查器覆盖结果。receipt 只保存版本、来源类别和语义指纹，不保存完整物品
  文本；物品、槽位或版本改变时失败关闭。第三方旧物品无 receipt 可保留诊断，但不能因此成为
  新生成 artifact 的可信特殊来源。
- Create 的组件、天赋、物品和词缀搜索应使用精确 query，选中候选后改用精确详情工具；不得设置
  固定候选条数上限，也不得把默认返回量当成搜索上限。同一未改变 Family 身份的 Research 不设
  固定摘要、维度或 record 深读额度；应继续查询到设计职责、关键条件、失败场景和验证任务得到
  足够覆盖。checkpoint 只阻止相同 query/receipt 因上下文压缩被原样重放，不能阻止新的定向查询。
- 精确 Family 查询必须检查 `familyRecordCoverage / familyRecordIndex /
  familyPremiseCatalog`。选中 Family 的关键失败 premise 必须在 `ResearchMemoryUse` 中标记
  `resolved/caveated/not_applicable`；resolved 只能引用本轮 record-detail 回执实际深读的解决
  记录。普通单阶段 Create 与 progression target 共用该审计。caveated premise 不自动判 BD
  失败，但 target 只能 `limited_accepted`，并把风险写入 TargetDesignCoverage 和路线报告。
- 对所有 progression 阶段、目标与转型候选，机制完整且合法的基础版本形成后必须做一次符合当前
  等级的主动质量收尾，检查高影响武器、辅助、天赋路径、珠宝、符文/灵魂核心和配置。Judge 报警
  不是探索前提；只去重同一 state hash、同一目标和同一参数的机械调用，不缩小合理的优化搜索
  空间，也不拿终局数值阈值要求低等级阶段。
- 每个通过正式 Judge 且通过共享硬合法性审计的 attempt 都是可保护的 passing baseline。主动
  质量收尾必须在隔离的新状态上进行；后续候选更好且合法时可晋升，若仅质量增量导致回归，可用
  `save_final_build_artifact(..., attempt_index=baseline轮次)` 保存仍有效的精确 baseline。即使
  新状态被 preflight 拦截而没有消耗 Judge、baseline 仍是最后一条 receipt，也按活动 state hash
  已偏离来识别恢复。恢复必须有当前 MCP 进程内的精确 Judge 快照、同 state hash 合法性回执和显式
  `laterFindingsScope=candidate_delta_only`；后续发现若也影响 baseline、快照丢失或绑定不一致，
  必须失败关闭。
- progression 的活动 lifecycle gate 使用默认 compact 响应，每个正式 Judge attempt 前最多一次；
  同一 state hash 不重复验证。artifact 保存后再独立且只执行一次 artifact-bound lifecycle。
  调参期间使用 `inspect_generation_checkpoint`，`detail=full` 只用于具名局部诊断。
- 长 progression 不能依赖聊天历史保存 Research 条件。Create 查询使用紧凑 response profile，
  选定的重要 evidence、条件、失败场景、验证任务和未解决项写入本地有界 working checkpoint；
  压缩/重启后先读取 resume packet，再进行 PoB mutation。checkpoint 不保存隐藏推理或原始材料。
- target anchor 和 progression stage 必须在保存前修复活动快照 lifecycle gate，并在保存后使用
  `verify_lifecycle_stage(..., artifact_id=...)` 生成可信回执。failed/unknown、篡改或跨
  artifact/stage 的回执不能绑定；调用者布尔值不能授权药剂或资源续航。
- Phase 5 正常顺序是保存 artifact 后再消费 review。若旧任务误先消费 review，
  `save_final_build_artifact` 仍必须核对同一 candidate/attempt、精确 Judge snapshot 和语义
  state hash 后才能恢复保存；不得手工删除 review marker、可信 receipt 或运行锁。
- progression 尚未完成但可信 target anchor 已绑定时，即使失败登记、暂停或审批层本身被阻断，
  也可用 progression id 导出 `routeIncomplete=true` 的恢复包；不能零文件结束或称为完整路线。
- 只有精确 `graphSnapshotId=unavailable:pending_discovery` 能在 target anchor 绑定时从可信
  artifact 解析一次；必须在同一 progression id 内原子冻结，不能另开路线或消耗 target retry。
  `StageCreatePacket.generationMemoryMode` 是阶段唯一事实源；run 绑定和阶段完成都要校验 manifest，
  模式错误不推进 revision、不消耗 retry，原 claim 可继续绑定正确 run。
- 新 progression 的 Family/Research 使用必须由 typed query receipt 验证。普通 Create 目标
  anchor 没有 stage packet，其 `researchMemoryRef` 必须属于本次实际 progressive queries；
  `family_exact` 阶段必须原样使用 claim 返回的 `StageCreatePacket.versionContext`，不能换成
  后续临时 ref。实际采用的 Family/record/pattern/edge/fragment 必须真实出现在 receipt 结果中，
  且 receipt 必须在当前 progression 启动后查询过。尚未升华、主要依靠联网开荒证据与
  corpus/mechanics 公共知识的 `starter_common` 阶段不是成熟 Family：不得伪造升华 Family 或强求
  精确 Research 命中，必须使用 typed `StarterStageIdentity`、StarterEvidenceUse 和公共知识引用。
  已确认核心 secondary skill 的 key/name 仍必须匹配同一 artifact 的启用 tested skill group。
- 能归入 Research schema 的知识不能写 Learning Memory；Memory correction 必须追加事件并保留
  do-not-repeat 历史。
- 不要持久化或暴露第三方成熟 BD 的原始整角色材料：PoB code、raw XML、raw account/character
  细节、长篇复制攻略文本，或由全部装备槽、整棵已分配天赋、全部技能组和完整配置组成的整角色
  镜像。允许保存可复用核心机制包，包括关键技能与辅助组合、局部核心天赋连接、暗金/装备与技能、
  天赋、资源系统的完整联动；不得按组件数量机械拒绝。系统自己
  生成、经过可信 Judge 且由 Agent 明确接受的最终候选，可以作为 Phase 6 本地私有
  `FinalBuildArtifact` 保存完整 PoB XML，但不得进入聊天、人工验收包、研究记忆或 Git。
- 禁止游戏内交互、overlay、内存读取、自动化或 live-screen parsing。

## 当前事实源

- `AGENTS.md`：标准 agent 操作规则和工具地图。
- `CLAUDE.md`：轻量 Claude Code shim，指回本文件。
- `docs/PROJECT_SPEC.md`：中文唯一项目总纲，维护方向、边界、Phase 关系和 Phase 状态。
- `docs/ARCHITECTURE.md` / `docs/ARCHITECTURE.CN.md`：高层架构和数据流，唯一双语文档。
- `docs/SCHEMAS.md`：中文唯一核心数据结构合同。
- `docs/JUDGE_SCORING_SYSTEM.md`：Judge 当前评分策略、证据分层、兼容逻辑和查询路径说明。
- `docs/phases/`：中文唯一各阶段执行计划和验收标准。
- `server/ASSISTANT_GUIDE.md`：通过 MCP 展示给 LLM client 的 runtime 指南。
- `scripts/verify.ps1`：验证 profile。

根 `README.md` 现在只承担安装、skill 自动化入口和安全边界说明。它不能夸大尚未完成的
生成、导出、对照学习效果或 reward-memory 能力；详细阶段细节仍维护在 `docs/phases/`。

## 命令

如果 Windows 工作区的 PATH 里没有 `uv`，使用仓库自带的 uv：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_fragment_extraction.py -q
.\.tools\uv\uv.exe run pytest tests/test_mature_fragment_extraction.py tests/test_mature_ninja_payload.py tests/test_mature_pobb_payload.py tests/test_mature_source_intake.py tests/test_mature_source_probe_runner.py tests/test_mature_sources.py tests/test_mature_sample_contract.py tests/test_mature_eval.py -q
.\scripts\verify.ps1 quick
```

验证梯度：

- touched module 使用 focused tests；
- knowledge/MCP/lifecycle/doc 改动使用 `.\scripts\verify.ps1 quick`；
- 跨范围非 engine 改动使用 `.\scripts\verify.ps1 noncompute`；
- engine、PoB、optimizer、runtime packaging 或 release gate 才使用 `compute` / `full`；
- `compute` / `full` 是重型 Headless PoB 认证入口，本地 Windows 经常运行 15 分钟以上。
  调用这些 profile 时，外层命令超时必须至少给到 30 分钟（`1800000ms`）；10 分钟工具超时
  只能说明外层预算不足，不能直接判定 compute suite 失败。`scripts/verify.ps1` 会为这些
  profile 传入 30 分钟 pytest 单测试超时。

## 工具 / 文件地图

### 入口

- `server/main.py`：MCP server 和公开 tool 注册。只有实现已放在正确层级后，才在这里新
  增用户可见 MCP tool。
- `server/ASSISTANT_GUIDE.md`：通过 MCP instructions 交付给 LLM client 的 runtime 指南。
- `server/BUILD_ADVICE.md`：由 `build_advice` 搜索的持久 BD 原则文本。

### Compute 层

- `server/compute/engine.py`：长生命周期 Headless PathOfBuilding-PoE2 JSON-RPC 进程和
  build state 调用，是数值权威。
- `server/runtime/node.py`：Node/npm package runner 的共享宿主发现层。converter 和 manifest
  验证必须复用它，支持显式环境变量、系统 PATH 和 Codex Desktop 随附 runtime；不要重新引入
  对全局 `node` / `npx` 的硬依赖。
- `pob/pob_headless.lua`：进入 pinned PoB-PoE2 代码的 Lua bridge。
- `server/compute/pob_code.py`：PoB share code/link/XML import/export codec。
- `server/compute/buildopt.py`：整体 build optimizer；MCP `optimize_build` 当前默认禁用，只保留
  显式维护开关，不属于 Create 流程。
- `server/compute/mutation_batch.py`：Agent 已决定的机械变更按职能分型的小事务执行器；每种
  scope 有独立白名单、数量上限和轻量后置条件，不执行搜索或优化器。
- `server/compute/itemopt.py`：rare item、jewel、gear-plan 和 upgrade optimization。
- `server/compute/craftopt.py`：crafting-system optimization。
- `server/compute/supportopt.py`：engine-measured support selection。
- `server/compute/solver.py`：stat lever ranking 和 target solving。
- `server/compute/skilltext.py`：skill text normalization 和 lever templates。

### Judge 层

- `server/judge/models.py`：Phase 1 judge 的 evaluator version、v3 metric keys 和 failure code
  / caveat 常量。
- `server/judge/rules.py`：class/ascendancy、support/socket v1、PoB weaponCheck 和
  physical-invalid blocker；weapon/skill 兼容性以 PoB readback 的 `disableReason` 为权威，
  不要在 Python 里按技能名硬编码武器需求。
- `server/judge/scoring.py`：`judge_v6_evidence_separated` 评分；hard floor 与 quality target
  分离，动态可用主资源池 recovery、异构 Max Hit、CI 混沌免疫、EHP 物理短板补偿和扁平
  aggregate 权重；`scoreBreakdown.offense` 必须输出 provenance、evidence level、raw/effective
  DPS 和 minion/count 诊断。
- `server/judge/modelability.py`：partial modelability、main socket group core blocker 和轻量
  whitelist caveat。
- `server/judge/evaluator.py`：从 active PoB readback 生成内部 `BuildEvaluation`；如果
  `judgeSelectedSkill` 被用于 offense，socket/modelability/weaponCheck 也必须跟随 selected
  skill group，而不是继续检查最后点击的 buff/战旗组；输出 `defenseModel` 只作诊断，不替代
  PoB Max Hit / EHP 评分证据。
- `server/judge/comparison.py`：候选与参考的 `selectionWinner` / `rewardWinner` /
  `rewardStrength` 合同；limited evidence 可以 selection，但 `rewardWinner` 必须保持
  `unknown`，不能写成强 reward。
- `server/judge/runner.py`：dedicated engine safe-call，处理 import/evaluation timeout、EOF 和
  crash recovery。
- `server/judge/fixtures.py`、`server/judge/benchmark.py`：synthetic Phase 1 baseline，写入
  user-data runtime，不进入仓库。
- Judge 核心仍是内部基线；Phase 5 只在 `server/main.py` 公开受限的
  `evaluate_generation_candidate` 入口，用于评价 Agent 已搭建的活动构筑。不要公开可接受任意
  原始输入的通用 Judge 工具。
- `server/generation/evaluation_snapshots.py` 只在当前 MCP 进程内短暂保留 Judge 的精确 XML，
  供 `save_final_build_artifact` 保存；run receipt 仍然 raw-free。保存前用共享
  `build_state_hash` 比较语义输入，不能用会受 `PlayerStat` / `FullDPSSkill` 刷新影响的 raw XML
  hash 判断是否修改过构筑；精确快照丢失时必须失败关闭，不能替换 Judge XML。
- Phase 1 对使用 weapon set passives 的 dual-state build 只给 limited reward；没有 State_A /
  State_B 分别评分证据时，不能把单状态最高 DPS 写成强学习信号。
- Phase 1 对 `FullDPS` rollup、召唤物 PoB output、投射物下界、关键 metric 缺失等 evidence
  只给 limited reward；这些信号可以帮助单个 BD 诊断，但不能污染后续 reward memory。

### Knowledge 层

- `server/knowledge/db.py`：SQLite/FTS corpus 查询。
- `server/knowledge/mechanics.py`：本地 mechanics 解释和 wiki-tier 引用。
- `server/knowledge/refbuilds.py`：仅用于校准的 reference build 摘要。
- `server/knowledge/lifecycle.py`：lifecycle route 模型、feedback memory 和 route helpers。
- `server/knowledge/lifecycle_*`：lifecycle cohort evidence、source evidence、verification、
  quality gates 和 evaluation harness。
- `server/knowledge/mature_learning.py`：mature-learning SQLite schema、sanitizer、seed import
  和 deterministic baseline extraction。这里的安全边界不能破坏。
- `server/knowledge/copy_safety.py`：共享 copyability guard。
- `server/knowledge/mature_sample_contract.py`：sanitized mature sample manifest 校验。
- `server/knowledge/mature_eval.py`：creator/evaluator contamination 和 typed gap 合同。
- `server/knowledge/mature_fragment_extraction.py`：外部 agent research packet builder 和 clean
  fragment schema v3 validator。它不能调用模型 provider。
- `server/knowledge/research_models.py`、`server/knowledge/research_memory.py`：Phase 4 typed
  proposal、聚焦 `DeepResearchRecord`、SQLite 写入和两级召回合同。单条深度记录只回答一个主要
  问题；中文正文原则上不超过 400 字，英文不超过 250 个单词。
- `server/knowledge/mature_source_intake.py`：按 build family 聚合来源变体，并构建供外部
  agent 研究的 raw-rich、quarantine-only case。
- `server/knowledge/mature_ninja_payload.py`：从渲染后的 poe.ninja build 页面提取 PoB import
  material，并转换为 quarantine-only payload row。
- `server/knowledge/mature_pobb_payload.py`：把 pobb.in 链接或 raw build source 导入为
  quarantine-only payload row。

### Comparative Learning 层

- `server/learning/models.py`：FamilyTarget、盲测 Create packet、逐维 comparison、Memory、correction
  和 campaign state typed contracts。
- `server/learning/case_store.py`：case-bound quarantine；原始 code/XML 只存在本地隔离目录。
- `server/learning/memory.py`：Research SQLite 之外的本地 append-only Learning Memory、召回、修正
  和防振荡。
- `server/learning/service.py`：Phase 7 CAS、幂等、暂停、恢复、显式 phase retry、串行 case gate 和
  十案例趋势汇总。它不创建 Desktop task、不调用模型。
- Reference/Profile 与 Comparator 使用同一可见任务；Create 必须是另一个任务。task/thread 创建与
  协调由 `$poe-bd-learning-loop` skill 完成。

### Build Progression 层

- `server/generation/progression.py`：Phase 8 锚点 Route v3（兼容读取 v1/v2）、本地 manifest、
  可信 `FinalBuildArtifact` 绑定和按 stage id 加载。
- `server/generation/progression_research.py`：StarterResearchPacket intake、URL 哈希、安全
  patch-scoped cache；它不联网、不写 Research/Memory。
- `server/generation/progression_service.py`：Phase 8 CAS、幂等、暂停、恢复、阶段 run 绑定和
  严格串行 gate；新状态先绑定普通 Create target anchor，目标前阶段各自运行 Phase 5，最后
  target closure 不再启动 Create。它不创建 Desktop task、不调用模型。
- `server/generation/progression_context.py`：独立 context revision 的临时语义工作集和
  ResumePacket 输入合同；保存 selected Research premises 与简短决策，不保存 PoB/XML、网页、
  对话或隐藏推理。
- `server/generation/validation_checkpoint.py`：按语义 build-state hash 合并 completeness、
  preflight 和有界数值回读；只缓存安全结果。
- `server/generation/progression_provenance.py`：读取已消费 Phase 5 安全 review；对
  `family_exact` 阶段验证精确 Family query receipt 以及候选实际采用的 Research ID，对
  `starter_common` 阶段保留 Starter/Web + corpus/mechanics provenance；不读取或返回 PoB XML。
- `server/generation/progression_lifecycle.py`：保存并重新校验 artifact-bound lifecycle
  内容寻址回执；原始 artifact hash 与 PoB 恢复态 hash 分开记录，回执不保存 XML。
- `server/generation/progression_costs.py`、`progression_delivery.py`：粗粒度 unique/craft effort
  成本画像和完整成长包导出。
- `server/MCP_BOOTSTRAP.md`：实际通过 MCP instructions 发送的短启动规则，避免延迟工具发现反复
  注入完整 `ASSISTANT_GUIDE.md`；完整指南仍是人类可读 runtime 事实源。
- `server/runtime/tool_telemetry.py`：只记录工具名、耗时、响应字节和安全关联 ID 的上下文成本
  遥测；禁止记录参数正文和响应内容。
- 完整成长流程的目标 anchor 和每个目标前重要里程碑必须分别拥有可信 Phase 5 artifact；目标
  anchor 先由普通 Create 从空状态生成，最后目标阶段直接复用它。不能从终局 PoB 自动删点、
  降级装备来伪造早期阶段。
- 开荒与目标阶段只锁基础职业，允许不同升华、技能、天赋、装备和资源。外部 Agent 有界搜索
  开荒资料；首个升华前及其他尚未形成成熟 Family 的阶段使用 `starter_common` 知识模式，
  结构化保存技能职责、前提和排除条件；转型/目标阶段再启用 `family_exact` Research。程序只
  验证安全摘要，社区攻略不能直接进入 Research 或 Learning Memory。
- progression manifest 只保存有界 typed delta、transition bridge、安全 evidence/artifact facts
  和引用；网页原文、完整 URL 与阶段 XML 不进入其中。
- 价格只作风险和获取难度说明。转型必须由技能、升华、天赋、Spirit、资源、防御、必需物品和
  Judge 等机制 readiness 决定，不能由价格档位自动触发。

### Live / Freshness 层

- `server/freshness/*`：patch/tree/PoB/poe.ninja freshness providers、cache 和 evaluator。
- `server/live/meta.py`：live meta shaping。不要从 ascendancy-only 数据推断 build-level
  popularity。
- `server/live/mature_sources.py`：对 build-level source 可用性做 copy-safe response-shape
  probe。
- `server/live/mature_source_probe.py`：比较候选成熟样本来源，并渲染安全的 source-probe
  report。
- `server/live/prices.py`、`wiki.py`、`update.py`、`version.py`：价格查询、live wiki fallback、
  更新和版本辅助。

### Scripts 和 Data

- `scripts/run_mature_source_probe.py`：本地 source-probe report 辅助脚本。它不运行 LLM。
- `scripts/run_judge_user_samples.py`：Phase 1 真实 PoB code transient 验收脚本。输出
  sanitized report，不持久化 raw PoB code/XML；允许输出 `judgeSelectedSkill` 摘要以便审查
  buff/战旗/辅助技能导致的 0 DPS 误读，但禁止输出完整 gem/support links。输入支持整文件
  XML、JSON/JSONL/manifest、显式分隔符和逐行 code；失败报告只输出 sanitized `errorKind`。
- `scripts/smoke_*.py`：按子系统划分的 focused smoke checks。
- `scripts/install_local_validated_runtime.py`：安装已认证 runtime data 到本地。
- `scripts/build_bundle.py`：构建 `.mcpb` bundle。
- `data/mature_build_learning/seed_cases.json`：只保存 sanitized seed mature cases。
- `data/reference_builds.json`：只保存校准摘要，不是模板。

## 阶段文档

- `docs/phases/00_cleanup.md`：Phase 0 cleanup 和文档结构。
- `docs/phases/01_judge_eval.md`：deterministic judge 和 modelability matrix。
- `docs/phases/02_graph_cold.md`：physical graph cold start 和 official ID mapping。
- `docs/phases/03_graph_tools.md`：graph backend 和 typed graph tools。
- `docs/phases/04_research_memory.md`：Researcher extraction 进入 semantic graph 和 memory。
- `docs/phases/05_generation.md`：Agent 主导的 BD 生成原型、Judge 和人工验收。
- `docs/phases/06_build_export.md`：官方 `.build` export。
- `docs/phases/07_critic_loop.md`：同 Family/同等级对照学习循环与轻量自进化 Memory。
- `docs/phases/08_build_progression.md`：用多个可信阶段 artifact 交付完整 BD 成长流程。
- `docs/phases/09_scale_productization.md`：scale、revalidation 和后续 productization。

## 编辑政策

- 优先使用聚焦模块和既有模式。
- 手工编辑使用 `apply_patch`。
- 除非用户明确要求，否则不要 revert 用户改动。
- 不要新增长篇历史规划文档。阶段细节更新对应的 `docs/phases/*.md`。
