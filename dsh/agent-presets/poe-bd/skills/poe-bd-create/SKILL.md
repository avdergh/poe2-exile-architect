---
name: poe-bd-create
description: Use when the user asks to create a Path of Exile 2 build or build recommendation for a target level, class, skill or endgame goal.
---

> **DSH 适配说明**：本 skill 运行在 DeepSeek Harness。所有 poe-bd 能力都是 MCP
> 工具，完整名带 `mcp__poe_<server>__` 前缀（例如
> `mcp__poe_knowledge__query_research_memory`、`mcp__poe_build__get_build_stats`），
> 下文只写末尾名称。加载本 skill 使用 DSH 的 `skill` 工具，不存在 `/poe-bd-*`
> 斜杠命令。工具清单以当前会话实际注册为准，不要猜测未注册的工具名。
> Create 只连接 knowledge + build 两个 server：知识/图/机制/Research 查询走
> `mcp__poe_knowledge__*`，所有 PoB/计算/Judge 工具走 `mcp__poe_build__*`。
> 所有 PoB/计算工具共享同一个活动构筑、必须串行调用；只有不接触活动构筑的
> 语料/图/机制/静态查询可以并行。

# /poe-bd-create

## 任务与模式

Agent 主导理解需求、查询取舍、机制设计、PoB 实装和失败修正，直接生成用户请求的目标等级单阶段 BD
（通常80+）；不生成全链路开荒成长方案。形成结构化需求摘要，基础职业一经锁定不能换职业。
其他缺失参数结合用户原话、上下文和终局默认值合理推定，在最终摘要披露。

普通交互 Create 开始时只确认交付方式。用户已经明确选择时不得重复询问；否则只问一次：

> ① 仅生成本地 PoB 文件  
> ② 本地文件之外，再生成 poe.ninja 分享链接

不得同时追问职业、预算、阶段等构筑字段，也不得为了补齐字段再开启第二轮问题。即使未给构筑参数，
仍自主选择终局方向。Blind/自动 Create 不询问，也不执行用户交付导出。

| 路径 | 初始化与知识来源 | 完成出口 |
| --- | --- | --- |
| 普通默认 | `mcp__poe_build__start_generation_run(memory_mode="memory_assisted")`；在本run内查询Research与公开Learning Memory | artifact及lifecycle验证后，普通validate/review，再按既定交付方式导出 |
| 用户显式 `--no-memory` | `memory_mode="no_memory"`；跳过Research与Learning，使用图/语料/机制/PoB，仍做Blueprint与Judge | 与普通路径相同；输出空值约定见提交合同 |
| `referenceBlind=true` | 先读取[Blind差异](references/blind-mode.md)；本次生成使用`mcp__poe_build__start_generation_run(memory_mode="memory_assisted")`，已有本次run则继续；Research另绑定原campaign/claim，不新建campaign | 只保存内部artifact，按claim提交Compare；不用普通review/用户导出/清理出口 |

反馈模式独立于上述路径：默认 `strict_mode=false`（`feedbackMode=hard_only`），用户明确要求
“严格模式”或 `--strict-judge` 才统一使用 `strict_mode=true`。首个正式Judge后不得切换。
主观评分、质量档位、warning和reward在默认模式下不推测、不补写；客观质量检查和交付标签仍须处理。

## 贯穿边界

- 游戏机制与当前规则、Family Research、当前图/语料和明确机制证据决定设计；PoB可建模性只限定
  数值声明，不授权换Family、拆掉真实触发宿主或制造自施法代理。无法验证的结论保留假设/unknown。
- PoB数值来自本次对应状态及目标的读回；允许Agent另给有依据的DPS情景粗估，明确范围、假设、
  来源与重复计数处理。建模覆盖不决定技能价值，未建模不按零收益或低优先级处理。可信Judge、artifact和
  Research回执不能自造、改hash或跨run复用。研究结论保留成立条件、失败窗口与验证任务。
- 必须通过 MCP 工具调用，不搜索调用者仓库、安装路径或运行文件，不用PowerShell/CLI代替。
  普通Create的知识工具在 `poe-knowledge-mcp`，PoB/计算/Judge在 `poe-build-mcp`；
  Blind所需Learning工具由其claim入口提供。工具名有宿主前缀，以下只写末尾名称。
- 所有PoB/计算工具共享活动构筑，必须串行调用；只有不接触活动构筑的知识查询可并行。
  机械写入使用职能小事务、最新state hash/fingerprint；只有 `rolledBack=true` 才确认恢复。
  禁用 `mcp__poe_build__optimize_build` 和全局被动树重排；Agent决定候选，工具不自动补完整BD。
- 不复制第三方整角色材料，不把原始PoB code/XML、账号/角色明细、完整来源URL、隐藏思维链或完整
  对话记录写入聊天/普通报告/记忆。自产passing候选仅由artifact工具保存完整XML；最终公开分享URL
  是交付例外。可以展示自己设计的技能组合、辅助组合、装备槽位摘要、天赋锚点或转型路线。
- 价格与预算只说明获取风险；装备与机制锁定后才查询价格，不改变Family、暗金、黄装或镶嵌采用。

## 执行顺序

按当前阶段读取下列reference，不要开始时一次加载全部细节。每项只详细定义一处，状态变化时按
验证reference的失效表返回对应阶段，不从头重放整套查询。

1. **初始化与版本。** 整理需求，调用模式表指定的 `mcp__poe_build__start_generation_run`，保存原样返回的
   `runContext/requestRef/promptId/packetId/experimentContext` 与 `agentOutputDraftTemplate`。
   不复用其他run的材料。实际调用 `mcp__poe_knowledge__get_freshness_report`，使用用户目标联盟或服务的补丁绑定选择。
   不能因为没有在界面中看到分组或没找到函数源码就判MCP不可用；精确工具发现和实际调用确认缺失后，
   报告安装不完整并停止，不能降级成未经验证的文字BD。版本异常按下节处理。

2. **构筑经验记忆。** memory-assisted路径读取并执行[Research使用](references/research-use.md)：
   解析职业/升华 → Family发现 → 授权/对照案例 → 关键记录深读 → Research执行合同及逐项决定。
   锁定一条设计授权lane，不能把对照证据混入premise解决引用。按该reference的停止条件结束查询；
   no-memory跳过本阶段，Blind使用其绑定差异。

3. **机制蓝图。** 读取[Blueprint](references/mechanism-blueprint.md)，综合证据与目标设计机制；
   需要填写输入对象时查[提交数据合同](references/output-contract.md)。调用
   `mcp__poe_build__validate_generation_blueprint`，accepted后才允许PoB变更、装备规划和暗金实测。
   蓝图不替代实装时核对来源事实；机制意图变化时先修订它。

4. **实装与质量收尾。** 读取[构筑与精修](references/build-and-refine.md)：
   bootstrap/目标等级 → 必需机制件与核心天赋 → 技能来源盘点与缺失职责 → 基础装备/药剂 →
   核心可行性 → 质量实验与完整装备系统 → 最终来源辅助配置。
   先处理确定性非法，再进入精修；未建模保持真实结构及具名验证任务。首次正式Judge前完成适用
   质量收尾，不能把未受Judge评估的基础版本称为passing baseline。

5. **冻结、评估与修复。** 读取[验证与恢复](references/validation-and-recovery.md)：
   config锁定 → 最终Support/Jewel/Socket → checkpoint → Draft → 活动lifecycle → 正式Judge。
   Checkpoint/Draft/lifecycle/Judge使用同一精确输出组和技能名。修复只使相关证据失效；
   正式Judge、质量返工、核心重建分别计额度。通过正式Judge且具有同hash硬合法性回执后，
   才保护该attempt的精确快照，后续增量在隔离新状态上进行。

6. **选择与交付。** 读取[交付](references/delivery.md)，选择实际接受的passing attempt：
   保存artifact → artifact-bound lifecycle → 普通validate/review或Blind提交 → 允许的导出/清理。
   数据形状按[提交数据合同](references/output-contract.md)，以可信 `deliveryStatus` 区分
   blocked/candidate/recommended，向用户披露实际缺口、版本限制和全部requiredUserDisclosures。
   工具操作失败保留现场，不能手改回执/锁或把技术候选称为推荐成品。

## 版本异常

`decision="blocked_stale"` 不等于停止生成：区分本地PoB过期、可补的来源缺口与核心规则冲突。
仅模型落后时继续搭建与评估，标注“过期 PoB 有限证据”；机制未知不编造数值。规则冲突/未知
停止强验证，说明具名缺口。`github_rate_limited` 但有本地交叉确认时，不误报官方树不可用。

模型兼容按精确补丁认证，不能由共同 `0.5` 前缀推断。历史Research召回独立于当期数值认证，
来源版本不改标；兼容/changed_scope等适用性处理见Research reference。联盟无法验证时保留
目标与来源差异，在unresolvedItems/unresolvedCaveats中记录，不用旧联盟名称充当当期身份。
过期模式仍需完成活动构筑、evaluate和受检交付。工具返回值是版本/时效权威，不在Skill另抄有效期。

## 工具发现索引

只用于定位能力；参数、顺序和失败处置在对应阶段，避免把索引当另一条流程。

| 需要的能力 | 入口 |
| --- | --- |
| 知识与机制 | `mcp__poe_knowledge__graph_tool_query`、`mcp__poe_knowledge__find_skills/mcp__poe_knowledge__get_gem/mcp__poe_knowledge__find_supports_for`、`mcp__poe_knowledge__explain_mechanic/mcp__poe_knowledge__search_mechanics`；Research见其reference |
| 装备与天赋候选 | `mcp__poe_knowledge__search_items/mcp__poe_knowledge__search_uniques/mcp__poe_knowledge__get_unique`、`mcp__poe_knowledge__search_mods/mcp__poe_knowledge__get_item`、`mcp__poe_build__search_passives/mcp__poe_build__get_passive`、`mcp__poe_knowledge__list_ascendancies` |
| 规划启发 | `mcp__poe_knowledge__build_advice/mcp__poe_knowledge__suggest_build_lifecycle`；不能覆盖当前版本事实、本Skill的Family和质量政策 |
| 等级参考 | `mcp__poe_knowledge__list_skills_for_level/mcp__poe_build__validate_level_availability`；候选参考，实际合法性由PoB与共享审计确认 |
| 局部诊断 | `mcp__poe_build__get_build_stats/mcp__poe_build__get_defenses/mcp__poe_build__evaluate_build/mcp__poe_build__pinnacle_readiness`；不能冒充正式Judge |
| 状态与导出恢复 | `mcp__poe_build__list_final_build_artifacts/mcp__poe_build__load_final_build_artifact/mcp__poe_build__get_build_planner_converter_status`；按验证/交付reference处理 |
