# Phase 5 - 约束驱动的 Architect 生成

## 阶段状态

未开始。

## 目标

从 graph/memory context 生成合法、符合 PoE2 特性的 BD 候选，同时让所有数值、寻路、装
备、support、Spirit 和合法性工作都保持确定性。

## 依赖

- Phase 1 judge。
- Phase 3 typed graph retrieval。
- Phase 4 semantic memory。

## 工作项

- 在代码中定义 `BuildBrief` 和 `BuildPlan`。
- 在声称 gear solver 之前先做 OR-Tools dependency spike：
  - 验证 uv/Windows 下安装可用；
  - 运行最小 CP-SAT 或 MIP smoke test。
- 通过结构化需求翻译到 OR-Tools，实现 `GearConstraintSolver`：
  - slot/affix/tier variables；
  - prefix/suffix limits；
  - affix groups；
  - attribute constraints；
  - elemental/chaos resistance constraints；
  - Spirit constraints；
  - life/ES floor constraints；
  - budget/craft realism scoring。
- 确保 agent 永远不直接写 OR-Tools API calls。
- 实现 `PassivePathPlanner`：
  - agent 只选择 anchors；
  - planner 在 passive budget 内连接 anchors；
  - 输出包含 level-interval sequence。
- 实现面向 PoE2 skill sockets/support planning 的 `SupportSelector`。
- 把 Spirit budget 和 reservation plan 作为一等 build validity。
- 表达 weapon-swap 的 state A/state B assumptions；不支持 dual-state evaluation 时明确标记。

## 验收

- 生成候选在可建模范围内能 import into PoB。
- 抗性、属性、Spirit、supports 和 passive budgets 都由确定性流程评估。
- OR-Tools solver 在 multi-objective gear constraints 上优于旧 scaffold/greedy baseline。
- 带 graph/memory 的生成在固定 BuildBriefs 上优于 no-memory baseline。

## 验证

运行 generation benchmark：

- PoB import rate；
- capped resistance rate；
- Spirit validity rate；
- passive budget validity；
- support plan validity；
- attribute validity；
- DPS/EHP target placement；
- modelability caveat correctness；
- copy-safety pass rate。

然后运行：

```powershell
.\scripts\verify.ps1 quick
```
