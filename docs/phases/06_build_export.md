# Phase 6 - 官方 .build 导出与 Leveling Progression

## 阶段状态

未开始。

## 目标

把支持的 BuildPlans 导出为官方 PoE2 Build Planner `.build` JSON 格式，并表达 leveling
progression，而不是只输出最终 100 级状态。

## 依赖

- Phase 2 official ID mapping。
- Phase 5 BuildPlan 和 PassivePathPlanner outputs。

## 工作项

- 定义 `BuildPlannerExport`。
- 将 BuildPlan 和 leveling sequences 转换为 `.build` JSON：
  - 带 `level_interval` 的 passives；
  - 带 `level_interval` 的 skills；
  - 带 `level_interval` 的 support skills；
  - inventory slot hints；
  - 支持时包含 weapon set；
  - notes 和 caveats。
- 生成 stage snapshots：
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
- Level intervals 覆盖 starter-to-endgame progression。
- `.build` output 与 BuildPlan 和 judge evidence 对齐。
- Export 不包含 copyable mature-build raw material。

## 验证

运行 `.build` schema/fixture tests，然后运行：

```powershell
.\scripts\verify.ps1 quick
```
