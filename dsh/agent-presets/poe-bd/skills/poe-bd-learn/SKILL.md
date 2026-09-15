---
name: poe-bd-learn
description: Teach an existing Path of Exile 2 build in the user's language through a complete H5 learning reader. Explain skills, equipment, passives and augments with exact icons, categories and concept definitions, using Research-depth analysis without storing knowledge or creating a build.
---

# 最高优先级 输出语言必须与用户一致

**这是 Learning 的首要交付规则，优先于本 Skill 的默认示例、模板和资料语言。**
输出语言跟随用户本次请求的自然语言；只有用户明确指定另一种输出语言时才覆盖。中文请求用中文，
英文请求用英文，不固定默认中文，不根据 PoB、网页、技能名或辅助名中的英文切换整份文档语言。
标题、目录、小标题、正文、表格、流程图、提示、文档元信息和会话导读必须保持同一目标语言。
中英混合请求按用户表达意图的主要语言判断；仅在无法判断时澄清，不能自行回退为英文。
专有名称是唯一例外：目标语言的官方名称未经确认时保留英文原名，周围说明仍使用用户语言。
开始 run 时明确传入 user_language；用户另有指定时传 output_language。生成 lesson 时声明同一
language，交付前逐项复核语言一致性；不能仅改 language 字段而保留另一种语言的正文。

> **DSH 适配说明**：本 skill 运行在 DeepSeek Harness。所有 poe-bd 能力都是 MCP
> 工具，完整名带 `mcp__poe_<server>__` 前缀（例如
> `mcp__poe_knowledge__query_research_memory`、`mcp__poe_build__get_build_stats`），
> 下文只写末尾名称。加载本 skill 使用 DSH 的 `skill` 工具，不存在 `/poe-bd-*`
> 斜杠命令。工具清单以当前会话实际注册为准，不要猜测未注册的工具名。
> Learning 首要规则是输出语言跟随用户。H5 保留完整讲解，组件名称附精确图标与类别说明；不写 Research 或 Phase 7 Memory。
> `study` 工具按职责分布在 research、knowledge 与 build 三个域；不调用入库工具，不要求 Codex 浏览器。

## Learning 的职责

带用户理解指定的一个 BD。分析粒度与 Research 相同，学习表达单独编写。完整 H5 学习页是主要交付，
会话保留导读和页面入口；语言遵守上面的首要规则。页面包含完整正文，不另做简化联动页，不放天赋树。
H5 连续阅读，兼容手机，名称可查询和点开说明；当前 Agent 分析和写作，
工具负责覆盖检查、机制示意图、比较表与排版，不把研究字段自动拼成攻略。
开始组织正文前阅读 [教学组织与表达](references/teaching.md)。

## 边界

- 专用 Study 工具只将原料放在 user-data 临时隔离区。不创建 Research queue/claim/accept，不写
  Pattern、图、Research 或 Phase 7 Memory，不调用 Create，不改变当前活动构筑。
- 优先用用户附件路径；粘贴码必要时存 OS temp 文件，不能把原文放入命令参数、会话或仓库。没有
  工具先 discovery，不搜索仓库或 shell 编辑运行态。只处理用户指定来源。
- 区分来源事实、资料解释、PoB 观察、Agent 推断与未知。没有作者说明就不猜其动机。冗余、无效、
  可疑的选择也须说明，不为每个选择硬编合理性。
- 专有名称使用 `{{componentRef}}`，精确官方简中身份/版本词表缺失就保留英文。中文解释效果，
  不临时翻译名称，不把繁中、社区或机器翻译当官方。本轮阅读官方双语实体对照后，可调用
  `mcp__poe_research__review_study_terminology` 绑定片段、同一实体与官方发布者审读；仅当前 run 有效，失败继续英文。
- 每处具体技能或辅助宝石名称后都要有精确图标，包括封面、页眉、目录、标题、正文、表格、流程图
  和提示。组件 token 由渲染器统一插图，不手工粘贴图片 URL，不用近似名字、颜色占位图或 AI 图。
  未提供技能栏图标的特殊宝石，只能用同一精确宝石 ID 的官方物品外观；找不到则处理 needs_icons，
  不能把缺图文档当作已经完成。校对时检查图标所属宝石、辅助阶级和紧邻名称的位置。
- 装备、天赋、升华和符文也使用各自的正确图标。稀有装备随机名与底材名需要说明关系，底材图不能
  冒充某个随机名独有的外观。天赋按树版本和节点 ID 取图，不能凭同名猜选；同名节点只有精确共用
  图标时才可归组展示。符文来自原装备的镶嵌记录，额外比较项用 iconComponentRefs 绑定身份。
- 新手未必知道一个名字是什么。首次介绍先说清类别，再讲作用，例如“这是稀有胸甲的随机名，底材
  是……”或“这是与胸甲配套的天赋”。reader 中的界面标签、类别名称、componentNotes 和 concepts
  都使用用户语言；概念词用清楚的定义解释，不为了补图给属性套用某颗宝石图标。
- 图标资源齐全不等于全文识别完整。交付前逐处核对简称、同名词和新提到的组件。尽量使用完整名称；
  不让 Clarity、Barrier 这样的简称静默漏图。概念确实不对应独立组件时，在 concepts 中说明其类别。
- 文档里的比较技能及授予子技能先精确查询身份，再用 guide.iconSkillRefs 声明；来源子技能候选见
  contract.additionalSkillIcons。同名词若指状态或机制而非宝石，使用 `{{term:原词}}`，例如
  `{{term:Shock}}`；不能把状态、天赋名称中的词误标成一颗宝石。

## 流程

1. `mcp__poe_research__start_study_run` 冻结一个 source_file 或 source_url，保存 opaque runRef。未知 source_patch
   保留 unknown，来源版本、模型版本与资料版本分别判断，不拿当前模型认证旧 BD。
2. `mcp__poe_research__inspect_study_case` 后，按序分页 `mcp__poe_research__read_study_case` 读完所有分区，跟随 nextCursor；search
   只定位、不算完整覆盖。保留 evidenceRef/componentRefs。核对活动技能组、装备组、Spec、ConfigSet、
   武器组与启用状态。区分手动容器、装备/升华授予和默认技能；重复授予不是多个可叠加增益。
3. `mcp__poe_knowledge__query_study_knowledge` 定向查 gem/item/unique/mechanic；图 search → resolve；Research
   summary → record 深读，直到职责、关键机制、条件和失败场景足够清楚，不设固定深读额度。
   他案不能补成本案装备、数值、低血状态或操作事实。外部页面读正文后，通过
   `mcp__poe_research__review_study_evidence` 逐 subject 记录 supports/contradicts/silent 和 relevance，保持 agent_reviewed。
4. 先建立因果链，再调用 `mcp__poe_research__get_study_contract` 按 `study_explanation_v5` 完成内部十个主题、机制链、
   逐装备/宝石说明、逐技能容器审读、天赋功能分组与关键点。源回执只证明存在，supported 因果还需
   对应 subject 的独立 supports 审读。不能用泛化句子批量填字段。随后单独编写 guide：按读者理解
   顺序编排小标题和正文，用流程图解释机制，用表格比较真正可比较的对象，用随文提示解释必要前提。
   guide 的 topic/component/group/mechanism 引用负责保持覆盖，内部主题不强制变成十个可见章节。
5. 数值用 `mcp__poe_build__observe_study_scenario` 的精确 group_index/skill_name，在隔离 PoB 中观察。导入
   归一化可能改变组号；selection_required 时阅读 availableOutputs 后精确重选，不猜邻近/同名组。
   物品/天赋移除用 `mcp__poe_build__evaluate_study_counterfactual`，只有 comparable 可引用差值。模型缺口、非法
   状态、丢失输出和缺数值不是零收益；不消耗 Judge，不替用户修改原 BD。
6. `mcp__poe_research__validate_study_lesson` 检查分析与学习正文两层覆盖，修复后重验。通过不代表程序证明了教学质量，
   Agent 须完成 depthReview 与 guide.teachingReview。`mcp__poe_research__complete_study_explanation` 生成自包含 H5、
   同内容 Markdown 与简短会话导读，并按精确 ID 准备和嵌入图标。交付前首先复核语言一致性，再检查
   每处技能名后的正确图标、分页、图表和内容连贯性。不能仅修改 language 字段来通过校验。
7. 最终答复提供构筑核心导读与 H5 页面入口。完整讲解必须在页面里，不能只做一页速查或把之前的
   会话原样装进文件。原始核验反馈留在内部，影响实际使用的结论用学习语言放在对应章节。
   完成后 `mcp__poe_research__cleanup_study_run` 清理原料；失败可在固定期限内恢复，恢复不续期，明确放弃才 abandon。

## 必须达到的粒度

- **核心与输出**：实际输出实体、命中/异常/触发/代理关系，基础伤害来源、转换与额外伤害、
  increased/more/taken/抗性分别在哪层起效，组件为什么搭配，放大依赖什么。
- **循环**：起手、准备、蓄积、消耗、输出、恢复、断档后的重启；刷图与无小怪 Boss 分开。
  充能、冷却、持续时间、站位、武器切换与场上对象怎样配合，不把勾选状态当真实覆盖率。
- **每个技能组和宝石**：输出、准备、触发宿主/负载、增益、防御、授予等实际职责；每个辅助作用于
  谁、有什么条件与代价。核对等级、品质、特殊品质、技能等级来源、颜色/属性机制。罗马数字阶级
  不是宝石等级；重复辅助、最高生效、缺少合法根的触发不能一概累加。
- **每件装备**：两套武器、防具、首饰、腰带、护符、药剂、珠宝全部覆盖。摘必要词条解释底材/局部
  防御、属性优先级、机制暗金、镶嵌、涂油、条件、取舍与替代边界。半径珠宝绑定位置；偷取、击杀、
  受击增益不当作常驻 Boss 能力。不要输出完整物品词条和配置镜像。
- **天赋与升华**：按职责覆盖所有已分配点，解释寻求的属性、绕路/跨区成本和武器组区别。每个
  notable、keystone 和有作用的升华具体解释，过路属性点可合讲。分清装备局部值与角色总值、
  基础暴击与 increased 暴击、资源支付域、防御层和失败条件。
- **资源与防御**：Spirit 请求与容量，Mana/Life 每次及持续成本，恢复来源及触发条件；闪避、ES、
  护甲、Ward、抗性、恢复和控制如何分工。药剂恢复不是再生，含击回的偷取不能重复相加。
- **前提与局限**：真正可疑的链接、来源/模型差异、配置虚高、无小怪与移动目标，以及尚无法证明
  的部分。语言具体克制，不写宣传语、学习评分、“隐藏答案”，不把全文变成统一格式卡片。
