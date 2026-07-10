# Phase 6 - 官方 .build 导出

## 阶段状态

未开始。

## 目标

把 Phase 5 已由 Agent 设计、并带有可验证或部分可验证证据的候选状态，转换为官方 PoE2 Build
Planner `.build` JSON 格式。

Phase 6 不负责重新设计 BD 生命周期，也不负责把 Agent 的方案程序化补完整。若需要导出开荒、
攻坚、终局或升级区间，它只能表达 Phase 5 已经给出的阶段状态、阶段假设和注意事项；缺失时
必须返回 unsupported 或 unresolved caveat。

## 依赖

- Phase 2 official ID mapping。
- Phase 5 Agent 候选摘要、可评估临时状态引用、阶段假设和 Judge 证据。

## 工作项

- 定义 `BuildPlannerExport`。
- 将 Phase 5 已提供的候选状态和阶段数据转换为 `.build` JSON：
  - 带 `level_interval` 的 passives；
  - 带 `level_interval` 的 skills；
  - 带 `level_interval` 的 support skills；
  - inventory slot hints；
  - 支持时包含 weapon set；
  - notes 和 caveats。
- 在 Phase 5 已提供阶段数据时导出 stage snapshots：
  - campaign early；
  - campaign mid；
  - campaign late；
  - maps entry；
  - budget endgame；
  - final endgame。
- 标记 unsupported 或 unresolved fields：
  - meta gems unsupported；
  - unresolved GGG IDs；
  - PoB-only concepts；
  - dual-state unsupported；
  - generated placeholder items not exportable。

## 验收

- Exported JSON 对 supported fields 匹配官方格式。
- Unresolved IDs 会失败或产生明确 caveats。
- 如果 Phase 5 提供了升级区间，level intervals 必须按原始阶段设计表达；如果没有提供，Phase 6
  不能自行发明完整升级路线。
- `.build` output 与 Phase 5 候选状态和 Judge evidence 对齐。
- Export 不包含 copyable mature-build raw material。

## 验证

运行 `.build` schema/fixture tests，然后运行：

```powershell
.\scripts\verify.ps1 quick
```
