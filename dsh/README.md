# DeepSeek Harness 适配（dsh/）

本目录是 Exile Architect（poe-bd-creator）对 **DeepSeek Harness (DSH)** 的适配层。
DSH 原生内置 MCP client 桥（`@deepseek-ai/dsh-mcp-client`），因此本适配与
OpenCode/Claude/Cursor 的适配方式同构：把已有的四个域 MCP server
（knowledge / build / research / learning）注册进 DSH，并把工作流 skill 改写成
DSH 的工具命名与能力形态。

## 组成

| 路径 | 作用 |
|---|---|
| `poe-bd.mcp.cordis.yml` | 第一层：`- insert:` patch，把四个 MCP server 注册进宿主组合 |
| `agent-presets/poe-bd/agent.cordis.yml` | 第二层：`poe-bd` agent preset 组合（MCP 行 + 人设 + skill 注册） |
| `agent-presets/poe-bd/preset.yml` | preset 显示元数据 |
| `agent-presets/poe-bd/skills/` | 四个用户工作流 skill + 一个显式 Research Worker（由 `scripts/adapt_skills_for_dsh.py` 生成，勿手改） |
| `../scripts/adapt_skills_for_dsh.py` | skill 改写生成器（工具名前缀、DSH 说明头） |
| `../scripts/install_dsh_preset.py` | preset 安装/卸载/诊断（install / uninstall / doctor） |

## 工具命名

DSH 中每个 MCP 工具注册为 `mcp__<serverName>__<工具名>`：

- `mcp__poe_knowledge__*` — 语料/图/机制/Research 查询、生命周期知识
- `mcp__poe_build__*` — headless PoB 引擎、计算、Judge、Phase 5 生成
- `mcp__poe_research__*` — 研究 intake 与 typed 提案
- `mcp__poe_learning__*` — Phase 7 对照学习

skill 正文已按此命名改写；`search_graph_components` / `resolve_graph_component`
是 `graph_tool_query` 的参数值，**不加前缀**。

## 安装

前置：本机已装 DSH，仓库在可访问的绝对路径。Windows 默认使用仓库自带的
`.tools/uv/uv.exe`；Linux/macOS 默认使用 PATH 中的 `uv`；两者都可用 `POE_BD_UV`
显式覆盖可执行文件。

### 第一层：注册 MCP（快速验证）

```powershell
dsh web --patch <repo>\dsh\poe-bd.mcp.cordis.yml
```

patch 加载成功后，新建会话应出现 `mcp__poe_*__*` 工具；HMR / 是否需要重启以当前 DSH
版本的运行提示为准。要长期生效，把该文件的 `- insert:` 块合并进
`$DSH_HOME\cordis.patch.yml`（全 profile）或
`$DSH_HOME\profiles\<name>\cordis.patch.yml`（单 profile）；不要覆盖已有文件内容。

### 第二层：安装 `poe-bd` preset

```powershell
python scripts\install_dsh_preset.py install          # 先 --dry-run 预览
python scripts\install_dsh_preset.py doctor           # 健康检查
python scripts\install_dsh_preset.py uninstall        # 卸载
```

安装目标：`${DSH_HOME:-$HOME/.dsh}\.agent-presets\poe-bd\`。之后在 DSH Web
新建会话，在预设列表选择 **poe-bd**，即获得四个 MCP 工具集 + 四个用户工作流 skill + 一个显式
Research Worker + poe-bd
人设；其他会话不受影响（MCP 子进程只在 preset 挂载时拉起）。

更新已有 preset 时，安装器会先完整复制到同级 `poe-bd.next`，再把当前目录移动为
`poe-bd.bak` 后切换；复制或切换失败会恢复旧目录。为避免覆盖用户保留的恢复点，已有
`poe-bd.bak`（或目标缺失但存在孤儿 backup）时会返回 conflict，不自动删除。`--dry-run`
只报告预期目标/backup，不写文件。

### 路径解析

MCP 行的 `cwd`/`PYTHONPATH` 从环境变量 `POE_BD_CREATOR_ROOT` 解析，回退到组合文件里的
字面路径；命令优先使用 `POE_BD_UV`，否则 Windows 使用仓库 uv.exe，非 Windows 使用 PATH
中的 `uv`。换机器时：

- 设置 `POE_BD_CREATOR_ROOT=<repo 绝对路径>` 后启动 DSH；
- 或把组合文件里的 `E:/poe-bd-creator` 字面量替换为实际路径
  （`install_dsh_preset.py install --repo-root <path>` 会在安装副本中自动替换）。
- 若 `uv` 不在上述默认位置，再设置 `POE_BD_UV=<uv 可执行文件>`。

## 验证

1. `dsh web --patch ...` 后新建会话，确认工具列表出现 `mcp__poe_knowledge__*` 等；
   四个 server 各自拉起 headless PoB 引擎，日志中不应有启动错误。
2. 在 poe-bd 会话里加载 `poe-bd-create` skill 后提问一个 BD 需求，确认走完
   `get_freshness_report → 渐进 Research 查询 → start_generation_run → …` 主链路。
3. `python scripts\adapt_skills_for_dsh.py --check` 可随时核对生成后的 skill 无
   缺失/陈旧文件、裸工具名、残留旧前缀或双前缀；
   `python scripts\install_dsh_preset.py doctor` 核对安装状态（含 staging `.next`
   残留与孤儿 `.bak` 检测；已安装旁的 `.bak` 是重装保留的恢复点，仅报告不判坏）。

## 已知边界

- DSH 只桥 MCP **tools**，不桥 MCP instructions；运行指引通过 preset 人设与 skill
  注入，不依赖 `MCP_*_BOOTSTRAP.md`。
- `poe-bd-learning-loop` 使用 DSH 的 `subagent` + `send_message` 映射 Desktop 任务。
- stdio 子进程环境会被 scrub（凭据类变量与 `DSH_*`），`PYTHONUTF8`/`PYTHONPATH`
  已在行内显式声明。
- 动态 Cordis 插件（`cordis_define`/`cordis_run`）不是本适配的交付形态，仅适合
  运行时调试；正式能力来自 patch / preset 两层的静态组合。
- **bundle 转换注意点**：将来把第一层 MCP 行打包为 DSH bundle（
  `cordis.patch.yml` 插件包，`dsh bundle install`）时，必须从本 preset 移除 4 个
  MCP 行——同一 `serverName` 在 preset 与 bundle 两处注册会让后加载实例失败。
  届时 preset 只保留人设/skills，MCP 注册全局由 bundle 承担，二选一，不能并存。
