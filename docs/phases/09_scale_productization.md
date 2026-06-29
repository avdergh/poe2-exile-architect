# Phase 9 - Scale、Revalidation 与 Productization

## 阶段状态

未开始。

## 目标

只有在核心 benchmarked loop 证明系统确实改善后，再扩展数据、自动化和用户-facing packaging。

## 进入条件

- Deterministic judge 在 fixtures 上可靠。
- Physical graph 和 typed graph retrieval 有 benchmark value。
- Researcher extraction 改善 semantic retrieval，且没有 copy-safety leaks。
- Generation 以有用比例产出 legal、modelable candidates。
- Critic loops 能改善 best score，或以清晰原因停止。
- Reward memory 显示 A/B uplift。

## 可能工作

- 更大的 mature corpus。
- Automatic patch revalidation。
- 更强 graph backend。
- Preference ranker。
- Frontend visualization。
- User feedback intake。
- Batch research jobs。
- Public README reconstruction。
- Release/package documentation。

## 验收

- Full benchmark regression 保持稳定或改善。
- Patch migration tests 通过。
- Copy-safety audit 通过。
- Public artifacts 通过 smoke checks。
- 官方 `.build` export compatibility 保持完整。

## 验证

对触及区域使用最广且合适的 verification gate：

```powershell
.\scripts\verify.ps1 noncompute
```

只有触及 PoB runtime、packaging 或 release gates 时才使用 `compute` 或 `full`。
