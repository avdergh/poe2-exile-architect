# Phase 7 - 带 Rollback 与 Early Stopping 的 Critic Loop

## 阶段状态

未开始。

## 目标

让 generate-evaluate-repair loop 能持续改善最佳候选，而不是震荡或浪费 agent/tool budget。

## 依赖

- Phase 1 judge。
- Phase 5 generation。
- 当 `.build` artifact 进入 loop 时，按需依赖 Phase 6 export。

## 工作项

- 保存每一轮 loop：
  - round id；
  - PoB XML snapshot；
  - optional `.build` draft；
  - BuildEvaluation；
  - score；
  - gap list；
  - changed components；
  - graph edges used；
  - repair strategy；
  - modelability caveats。
- Critic Agent 可输出 structured gaps：
  - numeric underperformance；
  - defense gap；
  - Spirit gap；
  - missing core mechanism；
  - unsafe transition；
  - wrong passive anchor；
  - support mismatch；
  - gear constraint conflict；
  - modelability issue；
  - patch stale issue；
  - budget unrealistic。
- 当 repair 降低分数时回滚到 best snapshot。
- 追踪 failed strategies。
- 增加 `StatePruner` / `ContextPack`：
  - 本地保留完整 snapshots、round logs、gap history 和 failed strategies；
  - 发给外部 Critic/Architect Agent 的 retry context 只包含 best snapshot summary、关键失败摘要、禁用策略、未解决 gaps、modelability caveats 和下一步约束；
  - rollback 后不把完整失败历史、完整 PoB/XML 或长对话日志继续塞回 prompt；
  - context pack 必须可追溯到本地 snapshot/round ids。
- Early stop 条件：
  - repeated low score gain；
  - repeated rollback；
  - repeated critical gap failure；
  - modelability blocker；
  - solver infeasibility；
  - iteration 或 token budget exhaustion。
- 产出 low-trust failure pattern candidates。

## 验收

- Loop 内 best score 单调不下降。
- Critical gaps 减少，或 loop 带清晰原因停止。
- Rollback 能恢复预期 snapshot。
- Retry context 在固定 round history 下可重复生成，并且明显小于完整历史。
- ContextPack 不包含完整 PoB/XML、长失败日志或可复刻成熟 BD material。
- Failure patterns 能被后续相似 briefs 检索到。

## 验证

运行 loop benchmark，然后运行：

```powershell
.\scripts\verify.ps1 quick
```
