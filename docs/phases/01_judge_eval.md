# Phase 1 - 确定性 Judge 与 Modelability Matrix

## 阶段状态

未开始。

## 目标

先证明现有 Headless PathOfBuilding-PoE2 sandbox 和确定性规则可以判断 BD 的质量、合法
性与 modelability，再让后续生成或学习依赖这些分数。

## 依赖

- Phase 0 文档结构。
- 现有 `server/compute/engine.py` 和 `pob/pob_headless.lua`。
- 现有 import/export 和 compute tests。

## 工作项

- 在代码中定义 `BuildSnapshot`、`BuildEvaluation` 和 `BuildComparison`。
- 建立固定 judge fixture set：
  - legal strong build；
  - legal weak build；
  - uncapped resistance build；
  - low DPS build；
  - high DPS / low defense build；
  - passive over-budget build；
  - attack skill with no weapon；
  - Spirit-insufficient build；
  - unmodelled meta-trigger build；
  - single-state 和 dual-state markers。
- 产出 PoE2 modelability matrix：
  - single-state DPS；
  - dual weapon state；
  - support socket / skill socket behavior；
  - Spirit reservation；
  - minion reservation；
  - meta-trigger；
  - projectile overlap caveats；
  - unsupported mechanics。
- 基于 PoB 输出和 hard legality checks 建立 deterministic scoring。
- 生成 baseline benchmark report，供后续 Phase 对比。

## 验收

- 显而易见的 strong/weak fixture comparison 能选出正确赢家。
- Illegal fixtures 返回具体 failure codes。
- Spirit shortfalls 能被检测。
- Unmodelled mechanics 变成 caveats，不产生虚假 reward。
- Benchmark output 可重复。

## 验证

实现后先跑 focused judge tests，然后运行：

```powershell
.\scripts\verify.ps1 quick
```
