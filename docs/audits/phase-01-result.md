# 第一阶段结果：可信底座与本地新鲜度门禁

## 已完成

1. 上游基线同步到 2026-06-23 发布的 `v0.1.39`；
2. 从同一 release 安装并校验 PoB 引擎、语料库和 Windows LuaJIT；
3. 修复中文 Windows 使用系统默认编码读取 UTF-8 manifest 的问题；
4. 新增与网络无关的新鲜度领域模型和保守判定器；
5. 新增本地 release 证据 provider 与共享 service；
6. 新增 MCP 工具 `get_freshness_report`；
7. 将旧 `check_data_version` 改为严格门禁包装器，RePoE 单源结果降为
   `legacy_corpus_probe`；
8. 在 MCP 操作指南中加入当前赛季声明规则。

## 门禁性质

门禁要求游戏补丁、联盟、官方天赋树、PoB 引擎、PoB 数据、语料库和 Meta 快照全部有
当前且兼容的证据。它具备以下安全边界：

- 缺少强制组件或必要兼容 claim 时阻断；
- 冲突、过期和未知原因同时保留，顶层状态按优先级选择；
- 非法枚举、空版本、空安全集合和可变输入不能绕过判定；
- 同来源历史记录只使用最新快照，并列且不一致的强制记录视为冲突；
- 可选来源只能产生警告，不能撤销当前结论；
- 原始证据和活动证据分别保留；
- 版本和联盟 claim 使用规范化值比较；
- 未建模关键机制降级为 `current_unmodelled`。

## 当前真实输出

本地 `v0.1.39` 能证明 PoB 提交、PoB 数据、语料库和天赋树 claim 的 release 内部一致性，
但上游 manifest 没有 PoB 对应游戏补丁字段，也尚未接入官方补丁、联盟、官方树和完整
Ninja 快照 provider。

因此当前真实输出是：

```text
blocked_unknown
```

这是预期的保守行为。系统不会把“本地 release 是最新下载的”误写成“当前赛季 BD 已验证”。

## 验证

### 通过

- 93 个非计算、MCP 表面和 freshness 测试；
- `ruff check server scripts pipeline tests`；
- `ruff format --check server scripts pipeline tests`；
- `mypy server/freshness`；
- `@anthropic-ai/mcpb validate manifest.json`。

两轮独立只读审查发现的高/中风险边界均已通过新增回归测试处理。

### 已知上游基线

PoB 计算套件共 71 个测试。当前 Windows 主机上前 69 个通过，
`test_optimize_build_crafting_keeps_resists_capped` 在 300 秒上限内仍执行批量装备候选，
最后 1 个未执行。该性能问题来自同步后的上游 `v0.1.39` 基线，本阶段未修改优化器。

## 下一环节

先写官方与 Meta provider 技术文档，然后实现：

1. GGG 官方补丁证据；
2. 当前联盟证据；
3. 官方天赋树快照证据；
4. Ninja 构筑快照、联盟和树版本证据；
5. PoB 提交到已验证游戏补丁的显式兼容映射。

只有这些证据完成交叉验证后，门禁才可能输出 `verified_current`。
