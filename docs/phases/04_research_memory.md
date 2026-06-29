# Phase 4 - Researcher 提取进入 Semantic Graph 与 Memory

## 阶段状态

未开始。

## 目标

让外部 Researcher Agents 从成熟 BD 中提取可复用、non-copyable 的知识，并且只把通过校
验的 semantic knowledge 写入长期记忆。

## 依赖

- Phase 1 judge/modelability output。
- Phase 2 physical graph。
- Phase 3 typed graph tools。
- 现有 mature source intake 和 copy-safety helpers。

## 工作项

- 升级 `ResearchPacket`，包含：
  - safe metadata；
  - quarantine-only raw context；
  - 可用时包含 judge output；
  - physical graph context；
  - freshness evidence；
  - copy-safety rules；
  - requested clean output schema。
- Researcher output 可包含：
  - clean fragments；
  - semantic edge proposals；
  - failure pattern proposals；
  - transition gate proposals；
  - verification tasks；
  - modelability caveats。
- 校验 semantic edge proposals：
  - endpoint nodes 必须 resolve 到 physical graph；
  - aliases 必须可追溯；
  - evidence refs 必须安全；
  - copy-safety 必须通过；
  - patch/version/status/confidence/modelability 必须存在；
  - creator/evaluator/holdout boundaries 必须成立。
- 实现 patch decay：
  - old edges 降权或变为 `needs_revalidation`；
  - 外部 agent 可执行 invalidation review；
  - 未复核的旧知识不能作为强证据。

## 验收

- 对同一批 reference cases 重复提取能产出稳定的核心 semantic edges。
- 不存在的 endpoints 会被拒绝。
- Copyable mature-build material 会被拒绝。
- Patch decay 可通过模拟版本变化测试。
- Semantic graph 改善 retrieval benchmarks。

## 验证

运行 mature extraction/memory tests 和 graph retrieval benchmark，然后运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_fragment_extraction.py tests/test_mature_ninja_payload.py tests/test_mature_pobb_payload.py tests/test_mature_source_intake.py tests/test_mature_source_probe_runner.py tests/test_mature_sources.py tests/test_mature_sample_contract.py tests/test_mature_eval.py -q
.\scripts\verify.ps1 quick
```
