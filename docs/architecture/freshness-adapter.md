# 新鲜度本地适配与 MCP 接口

## 当前切片

这一切片把纯门禁接到现有 MCP，但只采集能够从本地安装可靠证明的证据：

- 已安装的、经过 release SHA-256 校验的 PoB 引擎提交；
- 与该 release 配套的 PoB 数据；
- 与该 release 配套的语料库；
- 上游固定声明的天赋树兼容版本。

PoB 游戏补丁兼容 claim 只在安装元数据明确包含 `game_patch` 时生成。当前上游 release
manifest 没有这个字段，因此不能根据提交日期或 release 名称硬猜；缺失会继续阻断，直到
PoB 升级流程写入经过验证的兼容补丁。

它**不会**因为本地 release 是最新下载版本，就推断游戏补丁、官方树、联盟和 Ninja
快照也是最新。因此第一版真实本地报告预期为 `blocked_unknown`，直到后续官方和 Meta
provider 补齐证据。这是正确的保守结果，不是功能失败。

## 接口

新增 MCP 工具 `get_freshness_report`，直接返回结构化 `FreshnessReport`。

保留旧工具 `check_data_version` 以兼容已有客户端，但修改语义：

- 顶层 `recommendation` 使用严格门禁判定；
- `freshness` 保存完整门禁报告；
- 原 RePoE 时间和联盟探测结果放入 `legacy_corpus_probe`；
- RePoE 单源的 `up_to_date` 只能描述语料探针，不能升级整体结论。

## 本地证据来源

本地 provider 读取：

- `server.live.update.installed_meta()`；
- `server.live.update.installed_version()`；
- `server.knowledge.db.corpus_info()`；
- 仓库固定的 PoB 天赋树兼容声明。

Provider 只负责整形证据，不执行判定。所有读取失败都降级为缺失或 `unknown`，不得让 MCP
服务启动失败。

## 后续扩展

下一切片将增加官方补丁、官方天赋树、联盟和 Ninja 快照 provider。它们只需生成相同的
`FreshnessEvidence`，无需修改 MCP 接口或判定器。
