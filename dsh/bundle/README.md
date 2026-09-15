# Exile Architect for DeepSeek Harness（bundle）

这是 Exile Architect（poe-bd-creator）的 **DSH bundle**：声明
`"dsh": { "bundle": { "patch": "./cordis.patch.yml" } }`，用
`dsh plugin --profile <name> add <本包或本目录>` 安装后成为该 profile 的一层 patch，
把四个本地 MCP server 注册给该 profile 的每个会话。

它只负责**注册工具**；工作流 skill 与 `poe-bd` agent preset 仍由
`scripts/install_dsh_preset.py`（或 `install.ps1 -FromCheckout dsh`）放置。

## 前置条件

1. 按根 [README](../../README.md) 第 1–3 步装好本项目本体：`uv sync`、固定版本 PoB
   源码及其补丁、LuaJIT。四个 MCP server 启动的是同一个 headless PoB 引擎。
2. 本机已装 DSH（本包在 `0.1.6-alpha.1` 上核对），`pnpm` 在 PATH（`dsh plugin`
   会转发给 pnpm）。
3. 环境变量 `POE_BD_CREATOR_ROOT` 指向 poe-bd-creator 检出目录；`uv` 不在 PATH 时
   再设 `POE_BD_UV`。

## 安装

```powershell
# 本地目录（安装前先在这里 `git clone`/检出本项目）
dsh plugin --profile web add <项目目录>\dsh\bundle

# 发布到 npm 之后
dsh plugin --profile web add poe2-exile-architect-dsh
```

`dsh plugin` 会把包写进该 profile 的依赖；bundle 成员资格在**启动时**生效，装完需要
重启该 profile。之后同一 profile 的**所有**会话都会带上 poe-bd 工具（不再局限于
preset 会话）。

### 验证

```powershell
$env:POE_BD_CREATOR_ROOT = '<项目目录>'
dsh --profile web --dump-config      # 只打印组合树，不启动
```

`--dump-config` 会为每一行标注来源文件：应能看到四个 `poe-*-mcp` 行来自本包的
`cordis.patch.yml`，且没有 unmatched patch target 警告。

### 与 preset 二选一

`scripts/install_dsh_preset.py` 放置的 preset **自己也带这四个 MCP 行**。两者同时使用
会各拉起一套实例（两个 PoB 引擎），并让工具对所有会话可见。请二选一：

- 只装 preset：隔离在 poe-bd 会话，其他会话不受影响（推荐）；
- 只装本 bundle：工具全会话可用，然后另外放置 preset 拿人设与 skills——此时需要从
  `agent-presets/poe-bd/agent.cordis.yml` 里删掉那四个 MCP 行，或改用
  `install_dsh_preset.py` 之外的 skill 安装方式。

## 已知边界

- 四个 server 跑的是你检出目录里的 Python 模块；本包不含 Python 代码、不含 PoB，
  也不代管 `uv sync`。
- 没设 `POE_BD_CREATOR_ROOT` 时不会阻止 profile 启动：子进程以字面目录名
  `POE_BD_CREATOR_ROOT-not-set` 启动失败，MCP client 记录该失败，会话里没有 poe-bd
  工具。看到这个名字就是漏设环境变量。
- 本包只插入行、不覆盖任何既有行；`agent-presets` 的 preset root 与默认 preset 都
  不被改动（往 bundle 里塞 preset 需要重述该行完整 config，会连带改变默认 preset，
  因此不在这里做）。
