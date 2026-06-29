# Phase 8 - RLAIF-lite Reward Memory

## 阶段状态

未开始。

## 目标

使用 judge 和 Critic outcomes 改善 graph/memory ranking，但不训练大语言模型。

## 依赖

- Phase 4 semantic memory。
- Phase 5 generation。
- Phase 7 loop events。

## 工作项

- 定义并持久化 `RewardEvent`：
  - BuildBrief；
  - initial BuildPlan；
  - used techniques；
  - graph edges used；
  - before and after scores；
  - fixed gaps；
  - failed gaps；
  - rollback count；
  - final best snapshot id；
  - modelability caveats；
  - patch/version context；
  - outcome。
- 更新 graph/memory weights：
  - successful edge upweighting；
  - successful technique upweighting；
  - failed strategy downweighting；
  - stale edge downweighting；
  - repeated failure pattern upweighting；
  - scenario-specific technique weighting。
- 防止 low-confidence、unverified knowledge 自动 promotion。

## 验收

- Reward memory 可开关，用于 A/B tests。
- Reward updates 可解释、可回滚。
- Reward event 不包含 copyable mature-build material。
- 在考虑更复杂 rankers 之前，reward memory 必须改善 benchmark outcomes。

## 验证

运行 A/B benchmark：

- success rate；
- average score；
- critical gap count；
- loop convergence rounds；
- rollback count；
- Spirit/resistance/attribute legality；
- reference closeness。

然后运行：

```powershell
.\scripts\verify.ps1 quick
```
