# Learning：单 BD 学习文档

`poe-bd-learn` 面向玩家解释已有 BD，内部使用 Study 命名，与 Phase 7 learning-loop 区分。
分析沿用 Research 粒度，教学正文单独编排为完整 H5，会话给导读。首要规则是语言跟随用户，明确
指定输出语言时才覆盖；标题、目录、图表、提示和导读同样遵守。英文专名不决定正文语言。不生成
脱离完整正文的联动页或天赋树。用机制流程图、比较表、组件类别和概念解释帮助理解。
名称未核实官方简中时保留英文。桌面与手机连续阅读，HTML 内嵌图片与脚本，可单文件离线打开。

## 模块与流程

- `intake.py` 冻结输入；`storage.py / service.py` 管理 user-data 隔离原料、固定期限、锁和回执。
- `analysis.py` 复用 Research 分区读取，记录组件身份、技能归属、等级品质、武器组和天赋类别。
- `knowledge.py` 只读语料、图与 Research，不安装 seed、迁移或写 durable dedupe receipt。
- `models.py / validation.py` 定义并验证完整章节、逐组件/技能组/天赋覆盖与证据。
- `guide.py` 定义教学内容、reader 多语言界面标签、componentNotes 与 concepts；`html_document.py`
  与 `templates/reader.*` 负责响应式页面、章节搜索、图片放大和类别说明。`render.py` 保留 Markdown
  正文。渲染只接收教学层，不能自动展开内部分析字段，PDF 不再是主交付路径。
- `delivery.py` 原子发布固定文件名及 hash 清单，重试核验完整性；`localization.py` 负责名称回退。
- `language.py` 规范化并锁定用户/目标语言，声明不符或未完成语言审读时不得交付。
- `icon_catalog.py / icons.py` 从精确 gem/effect ID 读取游戏图标路径，下载、像素格式转换和校验；
  缺 UI 图标的特殊宝石只允许同 ID 物品图。`inline_names.py` 在所有可见位置统一插图，保护完整
  组件名称，term token 区分同名机制词。额外技能/组件须显式绑定 iconSkillRefs/iconComponentRefs。
- `component_icons.py` 关联随机装备名、精确底材、暗金、镶嵌和天赋身份；`passive_art.py` 从同版本
  PoB 的启用图标 DDS 数组按原始层号读取，保留文件指纹，禁止猜相似图。打包只补入这些小图标数组。
- `measurements.py` 使用独立 PoB 观察精确输出及装备/天赋移除，不触碰活动 Create 或 Judge。

流程：start → inspect/read 全部分区 → 定向深读与机制审读 → 按需隔离观察 → contract → validate
→ 教学编辑与图表组织 → complete → 文档与会话导读 → cleanup。导入改变组号时返回实际 availableOutputs，
Agent 精确重选。`complete_study_explanation` 返回文档路径与指纹，清理原料后文档仍可阅读。

## 深度与证据

`study_explanation_v5` 要求核心、输出、循环、技能、装备、天赋、升华、资源、防御、限制十个内部主题。
说明起手/维持/消耗/恢复/重启、无小怪 Boss、每颗宝石实际对象与等级品质、每件装备、天赋属性与
关键点、武器组、镶嵌/涂油/半径珠宝和可疑选择，不能一句“提升伤害”交差。depthReview 是 Agent
审读声明。教学章节可自由合并重排，用读者能理解的小标题，不能直接导出审计反馈。guide 的覆盖检查
保持所有组件与机制，teachingReview 要求 Agent 复核阅读顺序、细节和限制是否放在相关上下文。
结构校验不冒充语义质量评分，不用字数或关键词表判定深度与语言风格。

source_read 只证明存在，supported 因果须有该 subject 的 supports 审读，外部证据保持 agent_reviewed。
分页不得跳过，search 与他 run 回执不补覆盖，他案知识不替代本案事实。数值仅代表实际模型/状态/
输出，来源版本未知保留 unknown；模型缺口和非法状态不产生可信差值，不把未建模当作无收益。

Study 不创建 Research case，不写 intake ledger、Pattern、图、Research 或 Phase 7 Memory。
PoB/XML 只进临时 quarantine，正文不附全量精确词条和配置。完成/明确放弃后清理原料，恢复不续期。

## 验证

`tests/test_study_*.py` 覆盖 H5 生成、转义、类别与别名、DDS 层号、打包、内部分析不泄漏、两层覆盖、来源绑定、
只读 Memory、术语回退、过期清理和隔离计算。`scripts/smoke_study_mode.py` 使用合成来源验证真实
PoB 到学习文档的完整流程。真实用户 BD 在临时隔离区验收，不提交为仓库样本。
