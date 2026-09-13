# Phase 7 - BD 对照学习循环与轻量自进化 Memory

## 历史阶段状态（不作为当前执行进度）

功能实现已合入 `main`。早期文档曾记载第一轮计划10个串行案例、暂停于6例；该段没有当前运行态
核验，不能用它声称今天存在6个可恢复案例，或据此安排第7–10例。保留这段历史说明不授权恢复旧campaign。

2026-09-13当前工作按《PoE2 BD Creator：Create / Research 首轮审查与优化计划》的阶段4/5推进：
Research内容/召回/采用审计与Create成果验证。本文件后续章节仅保留Phase 7设计合同；功能实现、
当前实验状态与学习效果验收分别报告，不把历史状态当作当前任务清单。

## 目标

Phase 7 不再对同一个生成候选反复 Critic、修复、回滚或 Early Stop。它建立一个由外部
Agent 主导的对照学习循环：先安全建模一个成熟原 BD，再让独立 Create 任务只根据相同
Family 和相同等级盲测生成，随后由独立 Comparator 逐维比较，并把可复用改进作用于后续
案例。

每个案例只调用一次现有 `/poe-bd-create` 流程。Create 自身最多三次可信 Judge attempt
仍属于 Phase 5 有限内部修正；比较完成后不得重新生成或修复本案例。

## 依赖与边界

- 依赖 Phase 1 Judge、Phase 4 Research、Phase 5 Create；读取最终本地 artifact 时按需依赖
  Phase 6。
- Family 唯一定义复用 `BuildFamilyIdentity`：升华、主伤技能和已确认的核心/次级技能。
- Create 只看到 `FamilyTarget`、目标等级、当前版本和默认目标：软核交易、无固定预算、综合
  强度与可玩性优先。
- 原 BD 的装备、天赋、技能组、机制摘要、Judge 结果和来源信息不得进入 Create packet。
- 只限制等级，不限制预算；装备投入与可获得性是比较维度，不是 Create 的硬锁。
- Judge 是 `advisoryOnly` 证据附件，不自动决定比较赢家，也不写 reward。
- 仓库只保存状态和 typed contract，不调用模型 provider、不隐藏运行 agent loop。Desktop
  skill 创建和协调用户可见任务。
- 原始 PoB code/XML 只允许进入 case-bound quarantine；不得进入控制状态、比较报告、Learning
  Memory、聊天或 Git。

## 四阶段循环

### 1. Profile

输入支持 PoB code/link、本地 source file，以及复用现有 poe.ninja collector 的自动抓取。
每个来源先写入独立 quarantine case，再由 Reference/Comparator 任务重建原 BD、调用现有
Family inference 并生成安全的 reference evidence。

`FamilyTarget` 必须包含：

- `buildFamilyKey`；
- `ascendancyKey`；
- `primarySkillKey`；
- `secondarySkillKeys`；
- `targetLevel`；
- patch、天赋树、PoB 版本上下文；
- 不泄露原 BD 内容的安全 evidence refs。

升华、主技能、核心次级技能或等级无法唯一确认时，案例失败关闭，不猜测。

### 2. Create

每个案例创建一个与 Reference/Comparator 完全独立的可见 Create 任务。盲测 packet 只能包含
`FamilyTarget`、等级、版本和默认目标，并明确允许正常使用 Research DB 与 Learning Memory。

Create 完成后必须：

- 产生通过 Phase 5 可信回读的最终 artifact；
- 从最终 artifact/readback 重新推导 Family 和等级；
- Family 与等级完全匹配，否则案例失败；
- 在活动 Create claim 内查询 Learning Memory，由服务端按 Family/等级/版本绑定并保存安全 query
  receipt；提交必须与 receipt 一致；
- 对每条召回经验记录 `adopted/caveated/rejected` 决策、应用方式，以及是否观察到
  harmful/incorrect。

### 3. Compare

比较回到原 Reference/Comparator 任务。Comparator 接收双方各自的安全证据包，逐维输出证据、
结论和未知项，不能接收第三方原始 code/XML，也不能按 Judge aggregate 直接选胜者。

固定维度：

1. 伤害循环与投送机制；
2. 主副技能职责和辅助组合；
3. 配置条件及其真实性；
4. 关键触发、转换和机制链；
5. 装备、天赋、升华协同；
6. 清图、Boss 和条件爆发；
7. 防御层、恢复、资源、Spirit 和续航；
8. 机动性与实际操作；
9. 完整性、合法性和 modelability；
10. 装备投入与可获得性。

单维结论只允许 `generated_advantage`、`reference_advantage`、`tradeoff`、`tie`、`unknown`；
总结果只允许 `generated_stronger`、`reference_stronger`、`tradeoff`、`incomparable`。

比较合同 v2 要求非 unknown 维度绑定本案例双方安全 evidence packet 的引用，错侧、跨案例和
不存在引用均拒绝。criticalGap 标记与 typed critical gaps 必须一致；unknown 明确计数。
tradeoff 单列，不自动算作 not-weaker。服务端核对引用身份，结论仍由独立 Comparator 审读判断。
独立CR后的引用兼容修复使FamilyTarget、SafeBuildEvidence、DimensionComparison、ComparisonGap
共用3–240字符安全引用合同；canonical ASCII撇号原样保留，生产者接受的合法key可直接用于
本侧比较，不需要删字符或换成泛化引用，精确成员和copy-safety检查继续执行。

当生成 BD 更弱时，gap 必须至少归入一个 typed 根因：

- `missing_critical_technique`；
- `create_instruction_tool_or_data_defect`；
- `research_knowledge_or_retrieval_defect`；
- `learning_memory_missing_or_polluted`；
- `judge_or_modelability_gap`；
- `unrealistic_reference_configuration`；
- `insufficient_evidence`。

### 4. Fix/Learn 与条件复审

- 技能包、机制链、轮转、装备、天赋、防御、资源或其他能归入现有 Research schema 的知识，
  必须进入 Research 流程，不写 Learning Memory。
- 无法归入 Research DB、但能指导未来 Create 取舍的综合经验，可写 Learning Memory。
- 可复现的小型确定性代码/流程缺陷允许在 `codex/*` 分支做最小修复并补测试；在 `main` 上
  必须先暂停。
- 架构、产品取舍或证据不足项进入 backlog，状态机暂停等待人工决定。
- 发生代码、Research 数据或 Learning Memory 修改后，Comparator 对原报告做条件复审。
- 不修复、不重跑本案例 Create；所有改进只影响后续案例。

## Learning Memory

Learning Memory 是 user-data 中独立于 Research SQLite 的 append-only JSONL store。维护者当前通过
事件 schema 与 durable copy-safety 的 lesson/correction 会生成只读发布种子并进入 Git；新用户
首次运行时复制到本地可写 store。每条 lesson 包含：

- 简短 lesson；
- `global/family/level_band` 作用域及对应 Family/等级条件；
- 改进维度、适用条件、排除条件；
- 推荐 Create 行为和验证任务；
- comparison/source/candidate 的安全引用；
- patch、天赋树、PoB 版本；
- `active/narrowed/superseded/deprecated/stale` 状态；
- copy-safety 与复审信息。

单案例 lesson 经 Fix/复审后立即可供下一案例召回。修正采用追加事件：`narrow`、`revise`、
`supersede`、`deprecate`；事件记录修改前后摘要、原因、触发案例和证据。查询同时返回有效
lesson 和相关 correction/do-not-repeat 摘要。

如果已经被修正的同义 lesson 再次提交，必须引用旧 correction 并提供新的安全证据，否则拒绝，
防止反复“记录 → 修正 → 再记录”。

## Desktop 状态机

状态机按 campaign/case 保存安全控制状态，并使用 task id、claim id、thread id、当前 phase 和
revision 做 CAS。默认同一 campaign 只允许一个 active case：

```text
profile_pending -> profile_running -> create_pending -> create_running
-> compare_pending -> compare_running -> learn_pending -> learn_running
-> rereview_pending? -> completed
```

任一 phase 可进入 `paused` 或 `failed`。恢复从最后一个已提交 checkpoint 开始；显式 retry
只重试失败 phase，不得绕过已消费的 Create，也不得在 Compare 后创建第二个候选。

Reference/Profile 与 Comparator 绑定同一个可见任务；Create 必须绑定另一个可见任务。任务创建
由 Desktop skill 完成，状态服务只保存 claim、packet、checkpoint、暂停、恢复和重试元数据。

## 第一轮 10 案例验收

- 默认一个案例完全结束后才启动下一个；
- 每案例完成后记录累计指标和阶段耗时；
- 使用 3 个案例的滚动窗口；
- 最初 3 例与最后 3 例做方向性对比，中间 4 例作为持续学习过程；
- 不运行额外 Holdout，不运行逐案例 memory-on/off A/B。

跟踪指标：Create 接受率、Family 匹配率、generated stronger/not-weaker 比例、reference-advantage
维度数、critical gap 数、Memory 召回/采用/拒绝/污染/修正、Create/Research 缺陷分类、Judge/
modelability 可用率，以及各阶段和每案例耗时。

只有全部十例具备 v2、双方证据绑定、十维可比较与已知合法性，且最后 3 例相对最初 3 例同时满足下列条件，才
报告“出现初步进步信号”：

- not-weaker（当前只计 generated_stronger）比例上升；tradeoff 比例单列；
- reference-advantage 中位数下降；
- critical gap 不增加；
- 合法性、Family 和等级匹配不退化。

状态查询从已保存报告和当前案例双方证据重新校验并派生比较指标。旧报告保留诊断但不自动取得
新覆盖权限；缺失数值为 null，不以 0 表示无优势/无缺口，也不把证据减少当作改善。
工程合同修复不恢复历史暂停批次，也不重跑任何已比较案例。

10 个案例且没有 A/B 只能提供方向性证据，不能声明因果证明。如果趋势没有改善，Phase 7 标记为
“功能实现完成、学习效果未证实”，保留全部根因和 Memory correction，再决定下一批案例或
后续规模化方案。

已消费 Create 后发生 Family/等级回读不匹配属于终态失败：记录指标并释放严格串行槽位，不允许
重放该 Create；失败尝试计入十案例总数，但因比较证据不完整，不能支持“初步进步信号”。

## 自动测试与验证

- Family 精确复用、等级一致和歧义失败关闭；
- Create packet 不泄露 reference 细节；
- code/XML 不进入 durable artifacts；
- Reference/Comparator 与 Create 独立任务绑定；
- 状态机 CAS、幂等、暂停、恢复和 phase retry；
- Judge 不参与自动 winner；
- DB-fit 经验不能误入 Learning Memory；
- Memory 下一案例立即召回；
- correction 历史、污染修正和防振荡；
- 显式 source 与自动抓取各至少一个 E2E；
- Create、Research 和导出流程无回归。

验证梯度：focused tests → `verify.ps1 quick` → `verify.ps1 noncompute` → 最终
`verify.ps1 full`，然后代码审查和真实 Desktop 任务验收。
