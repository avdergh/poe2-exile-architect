# Windows 运行时基线

## 目标

保证源码模式和正式 `.mcpb` 安装包在中文 Windows 上使用相同、可复现的运行时输入。
这一环节只处理上游基线，不改变构筑研究逻辑。

## 固定输入

当前基线对应 2026-06-23 发布的上游 `v0.1.39`：

- Python：与上游发布 CI 一致的 CPython 3.12；
- PoB 引擎：release manifest 固定的 `a82a33b4`；
- 语料库：release manifest 中带 SHA-256 的 `corpus.sqlite`；
- LuaJIT：同一 release 的 Windows `.mcpb` 内置二进制。

开发机数据安装在被忽略的 `.runtime-data/`，LuaJIT 安装在上游已忽略的
`runtime/luajit/win-x64/`。这些文件是可重新下载的构建输入，不进入源码。

## UTF-8 边界

`manifest.json` 是 UTF-8 文件，并包含 Unicode 标点。`Path.read_text()` 未指定编码时会
使用系统区域设置；在中文 Windows 上通常是 GBK，因此读取会失败并让
`_server_version()` 错误返回 `unknown`。

处理规则：

1. 仓库内的 JSON、Markdown 和配置文件一律按 UTF-8 读取；
2. 测试必须断言生产代码显式传入 UTF-8，不能依赖 CI 机器恰好使用 UTF-8；
3. 用户生成的文本是否允许其他编码，由对应导入器单独决定，不能借此放宽内部文件规则。

## 性能测试边界

PoB 装备组合搜索会向单个持久 LuaJIT worker 发送大量候选。完整计算测试允许使用比普通
单元测试更长的时间窗，但任何超时都要记录具体测试和 worker 堆栈，不能简单标记为通过。

## 验收

- 版本读取测试不依赖 Windows 当前代码页；
- 非计算测试全部通过；
- 完整计算测试有可复现的通过结果，或在审计文档中记录明确的超时用例与调用栈。
