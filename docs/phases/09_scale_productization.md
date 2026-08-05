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

已提前完成一个不依赖 Phase 9 效果声明的基础缺口：Codex 发布包可同时携带净化 Research 种子、
可移植物理图种子、只读 corpus、MCP/Create 运行入口和运行依赖。它只解决“安装后能运行和召回”，
不代表 Phase 9 的规模化、在线迁移或学习效果已经完成。

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

packaging 或 release gate 使用不含 PoB golden 的 `full`。只有直接修改 PoB 引擎、Lua bridge、
数值计算或 optimizer 行为时才显式运行 `compute`。
