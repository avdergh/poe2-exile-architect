# 上游基线审计

## 导入记录

| 字段 | 值 |
|---|---|
| 上游项目 | `MaxWilk/poe2-build-mcp` |
| 上游地址 | https://github.com/MaxWilk/poe2-build-mcp |
| 导入版本 | `v0.1.39` |
| 发布时间 | 2026-06-23 04:35:15 UTC |
| 导入日期 | 2026-06-23 |
| 标签源码 ZIP SHA-256 | `a0e82c3b2862818ac2660e12698da0c76fd215be4810c265dcd695b406acfb1b` |
| Windows MCPB SHA-256 | `0624cbcd6d0520ee2b921456b6d34d5682c33cb7e3dafac58cf120823b6e34e5` |
| 许可证 | MIT |
| 本地 Git 状态 | 当前执行环境只提供只读 Git 包装器，尚未保留提交历史或创建远程 fork |

最初导入的 `0.1.38` 在审计期间被同日发布的 `v0.1.39` 取代。我们的中文文档被保留，
所有发生变化的上游源码文件均从 `v0.1.39` 标签归档重新同步。

## 固定运行时

上游 release manifest 声明：

| 组件 | 版本或校验值 |
|---|---|
| 应用版本 | `0.1.39` |
| PoB 提交 | `a82a33b4` |
| PoB source SHA-256 | `3654b56c4e889b00f05d35290e4567159fedb3b93efb400be30b91c2911192bd` |
| `corpus.sqlite` SHA-256 | `0e029a90d0baab94b113e6592dfb64dfb08f09b9f88c26970f7e7d626a6b4610` |
| `pob-engine.zip` SHA-256 | `5e48ae5319203958e05d78a117424ff065515674fd4d72c7b659bfb6615a8760` |
| LuaJIT 提交 | `871db2c84ecefd70a850e03a6c340214a81739f0` |
| Python | CPython 3.12.13，匹配上游发布 CI 的 3.12 系列 |

数据通过上游 `apply_updates(force=True)` 安装到 `.runtime-data/`，由上游代码验证
release manifest 中的 SHA-256。LuaJIT 来自同一 release 的 Windows `.mcpb`。

## 测试基线

### 非计算测试

在中文 Windows 默认代码页下运行：

```text
71 passed
```

覆盖 `corpus`、`passives`、`refbuilds`、`server`、`skilltext` 和 `update`。

审计发现 `manifest.json` 包含 UTF-8 Unicode 标点，而生产代码依赖系统默认编码。
该问题已用回归测试复现，并改为显式 UTF-8 读取。

### PoB 计算测试

`tests/test_compute.py` 共收集 71 个测试。为每个测试设置 300 秒上限后：

- 前 69 个通过；
- `test_optimize_build_crafting_keeps_resists_capped` 超时；
- 超时时 worker 正在 `eval_items` 中执行大批装备候选计算；
- 最后 1 个测试未执行。

这被记录为上游 `v0.1.39` 在当前 Windows 主机上的性能基线，不视为本项目新功能的
通过结果，也暂不在新鲜度阶段修改优化器。

## 许可证边界

- 当前导入源码为 MIT；
- `deepwa7er/poe2-mcp` 没有明确许可证，不复制其代码；
- `maxrenke/pob2-mcp` 为 GPL-3.0，不合入本项目；
- Ninja 未公开接口将根据公开响应行为独立实现，并保存自有 fixture。

## 仍待解决

1. 在后续 PoB 升级阶段重新运行全部黄金测试；
2. 分析两个超重构筑优化测试的候选规模和超时策略；
3. 获得真实 Git/GitHub 写权限后创建用户 fork，并把原项目配置为 `upstream`；
4. 统一游戏、天赋树、PoB、语料库和 Ninja 快照的版本清单。
