# DeepSeek Harness 适配（dsh/）

本目录是 Exile Architect（poe-bd-creator）对 **DeepSeek Harness (DSH)** 的适配层。
DSH 原生内置 MCP client 桥（`@deepseek-ai/dsh-mcp-client`），因此本适配与
OpenCode/Claude/Cursor 的适配方式同构：把已有的四个域 MCP server
（knowledge / build / research / learning）注册进 DSH，并把工作流 skill 改写成
DSH 的工具命名与能力形态。

项目对外呈现的是 **Research / Create / Learning** 三个工作流（Research 附带一个只由
Controller 派发的 `poe-bd-research-worker`），它们也是目前最完善的三条链路。Phase 7
对照学习 loop 驱动随 preset 一起安装，但定位是实验性能力，不作为对外卖点。

本适配在 DSH `0.1.6-alpha.1` 上开发与核对，尚未完成真实宿主验收。

## 前置条件

1. **先按根 [README](../README.md) 第 1–3 步装好本项目本体**：`uv sync`、固定版本
   PoB 源码及其补丁、LuaJIT。四个 MCP server 启动的是同一个 headless PoB 引擎；
   跳过这一步会得到"工具在但计算全失败"的会话。
2. 本机已装 DSH，并能用 `dsh web`（或等价入口）启动。`.agent-presets` 与
   `--patch` 是该版本的组合结构，更早的版本可能不识别。
3. `uv` 可用。根 README 已要求安装 uv；若 `uv` 不在 `PATH`，用
   `POE_BD_UV=<uv 可执行文件>` 显式指定。注意 `.tools/` 是 git-ignored 的本地目录：
   **新克隆里没有 `.tools/uv/uv.exe`**，只有开发机上才可能存在。
4. `python` 可用（仅安装/诊断时需要；也可以用 `uv run python` 代替）。

## 组成

| 路径 | 作用 |
|---|---|
| `poe-bd.mcp.cordis.yml` | 第一层：`- insert:` patch，把四个 MCP server 注册进宿主组合 |
| `agent-presets/poe-bd/agent.cordis.yml` | 第二层：`poe-bd` agent preset 组合（MCP 行 + 人设 + skill 注册） |
| `agent-presets/poe-bd/preset.yml` | preset 显示元数据 |
| `agent-presets/poe-bd/skills/` | 三个对外工作流 skill（Research / Create / Learning）+ 显式 Research Worker + 实验性对照学习 loop（由 `scripts/adapt_skills_for_dsh.py` 生成，勿手改） |
| `bundle/` | 可选：符合 DSH 包约定的 bundle（`dsh.bundle.patch`），用 `dsh plugin add` 把四个 MCP 行作为 profile 的一层注册；只注册工具，不带 preset |
| `../scripts/adapt_skills_for_dsh.py` | skill 改写生成器（工具名前缀、DSH 说明头、逐 skill 宿主改写） |
| `../scripts/install_dsh_preset.py` | preset 安装/卸载/诊断（install / uninstall / doctor） |

两个组合文件里的 `__POE_BD_CREATOR_ROOT__` / `__POE_BD_UV__` 是**占位符，不是可用
路径**：安装器在放置 preset 时把它们替换成真实值，并把替换后的 layer-1 patch 写到
preset 目录里。直接使用仓库里的模板而不安装时，必须自己设置
`POE_BD_CREATOR_ROOT`（以及必要时 `POE_BD_UV`）。

## 安装

### 一键安装（推荐）

```powershell
# Windows：在项目目录里
.\install.ps1 -FromCheckout dsh
```

```sh
# macOS / Linux
bash install.sh --from-checkout dsh
```

安装器会把 `poe-bd` preset 放到 `${DSH_HOME:-$HOME/.dsh}/.agent-presets/poe-bd/`，
写入你的项目路径与 uv 位置，并在同目录生成填好路径的
`poe-bd.mcp.cordis.yml`。之后新建 DSH 会话，在预设列表选择 **poe-bd**。

手动等价命令：

```powershell
uv run python scripts\install_dsh_preset.py install   # 先 --dry-run 预览
uv run python scripts\install_dsh_preset.py doctor    # 健康检查
uv run python scripts\install_dsh_preset.py uninstall # 卸载
```

`--repo-root <绝对路径>` 可以覆盖被写入的项目路径（默认就是本仓库）。安装器使用
staging + 可恢复 backup：先完整复制到同级 `poe-bd.next`，再把当前目录移动为
`poe-bd.bak` 后切换；复制或切换失败会恢复旧目录。

### 可选：作为 DSH bundle 安装

`dsh/bundle/` 是一个符合 DSH 包约定的 **bundle**（`package.json` 里声明
`"dsh": { "bundle": { "patch": "./cordis.patch.yml" } }`）。它只把四个 MCP 行注册成
profile 的一层，不携带 preset；`dsh plugin` 会转发给 `pnpm`，需要 pnpm 在 PATH。

```powershell
$env:POE_BD_CREATOR_ROOT = '<项目目录>'
dsh plugin --profile web add <项目目录>\dsh\bundle   # 发布到 npm 后可用包名
dsh --profile web --dump-config                      # 只打印组合树，确认四行来自本 bundle
```

bundle 成员资格在**启动时**生效：装完重启该 profile，之后该 profile 的**所有**会话都带
poe-bd 工具。因此它和上面的 preset 注册是二选一（见下）。

### 两条注册路径二选一

- **preset（推荐）**：只装 preset，poe-bd 会话拥有四个 MCP 工具集 + 三个对外工作流 skill
  （Research / Create / Learning）、显式 Research Worker 与实验性对照学习 loop + 人设；
  其他会话不受影响，MCP 子进程只在挂载 preset 时拉起。
- **宿主级 patch / bundle**：`dsh web --patch <preset 目录>\poe-bd.mcp.cordis.yml`、把该
  文件的 `- insert:` 块合并进 `$DSH_HOME\cordis.patch.yml`（全 profile）/
  `$DSH_HOME\profiles\<name>\cordis.patch.yml`（单 profile），或用上面的 `dsh plugin add`。
  这样所有会话都能看到工具，但也就失去了 preset 的会话隔离。

**不要同时使用两者。** 两者的 `serverName` 属于不同 scope，不会直接报错，但会同时存在
两套实例：同一个 server 拉起两次，等于两份 PoB 引擎，并且工具对所有会话可见。

### 环境变量

| 变量 | 作用 |
|---|---|
| `POE_BD_CREATOR_ROOT` | 项目目录；覆盖组合里写入的路径 |
| `POE_BD_UV` | uv 可执行文件；覆盖组合里写入的 uv |
| `DSH_HOME` | DSH home，预设根为 `${DSH_HOME:-$HOME/.dsh}/.agent-presets/` |

### 更新

```powershell
git pull --ff-only; uv sync
.\install.ps1 -FromCheckout dsh -Force
```

重装会把上一版保留为 `poe-bd.bak` 恢复点；因此**再下一次**重装会报
`backup_already_exists`。加 `-Force`（脚本形式 `--force`）会把该恢复点改名为带时间戳的
目录再继续，而不是删除。目标目录缺失但只剩 `.bak`（切换中断）时仍报
`orphan_backup_exists`，需要人工确认后再处理。

## 工具命名

DSH 中每个 MCP 工具注册为 `mcp__<serverName>__<工具名>`：

- `mcp__poe_knowledge__*` — 语料/图/机制/Research 查询、生命周期知识
- `mcp__poe_build__*` — headless PoB 引擎、计算、Judge、Phase 5 生成
- `mcp__poe_research__*` — 研究 intake 与 typed 提案
- `mcp__poe_learning__*` — Phase 7 对照学习

skill 正文已按此命名改写；`search_graph_components` / `resolve_graph_component`
是 `graph_tool_query` 的参数值，**不加前缀**。

## 验证

1. `uv run python scripts\install_dsh_preset.py doctor`（或 `.\install.ps1 -Doctor dsh`）
   返回 `healthy`，且 `checks.rowsResolvable` / `checks.tokensResolved` /
   `checks.emittedPatch` 为 `true`。
2. **行名必须与目标 DSH 版本匹配**：`checks.rowsResolvable` 比较 preset 引用的每个插件名与
   `agent-presets/poe-bd/dsh-plugin-rows.json`（当前记录 DSH `0.1.6-alpha.1` 的 177 个可解析
   行名）。行名对不上会让 `dsh-agent-presets` 把**整个 preset 判为 broken**（在预设列表里
   显示加载失败、无法选中），而不是只坏那一行；安装器会在写入前直接失败关闭。
3. 升级 DSH 后复检（需要 DSH 检出与 node）：

   ```powershell
   uv run python scripts\install_dsh_preset.py --probe <DSH 检出目录>
   # { "preset": "poe-bd", "verdict": "loadable", ... } 且退出码 0
   ```

   它调用 DSH 自己的 `discoverPresets`（与 GUI 同一套解析）来判定已放置的 preset 能否挂载。
   若报 broken：改对应行使其与本机 DSH 版本一致，然后刷新快照并跑测试：

   ```powershell
   uv run python scripts\install_dsh_preset.py --write-row-snapshot <DSH 检出目录>
   python -m pytest tests/test_dsh_adapter.py -q
   ```

4. 新建 DSH 会话并选择 **poe-bd**，确认工具列表出现 `mcp__poe_knowledge__*`、
   `mcp__poe_build__*`、`mcp__poe_research__*`、`mcp__poe_learning__*`；四个 server
   各自拉起 headless PoB 引擎，日志中不应有启动错误。
5. 在会话里让它调用 `engine_health`，再加载 `poe-bd-create` skill 提一个 BD 需求，
   确认走完 `get_freshness_report → 渐进 Research 查询 → start_generation_run → …` 主链路。
   `engine_health` 只观察进程与工具活动，不启动也不重置 PoB：首次计算前返回
   `not_started` 属于正常结果，`busy` 表示任务仍在运行；两者都不认证构筑，也不需要
   先执行 `new_build`。引擎真的起不来时才会报 `exited` 或错误详情。
6. 改过 skill 或适配器时：`uv run python scripts\adapt_skills_for_dsh.py --check`
   校验生成树无缺失/陈旧文件、裸工具名、旧前缀、重复前缀，并且每条宿主改写规则仍匹配
   源 skill；`python -m pytest tests/test_dsh_adapter.py -q` 覆盖安装器与生成器。

## 已知边界

- **本 preset 的行名与 DSH 版本绑定**：组合里的每一行都对齐该版本随发行版交付的 `standard`
  preset（当前 `0.1.6-alpha.1`）。DSH 改名或换行时，未同步的行会让整个 preset 变成
  「加载失败」——这正是 0.1.6-alpha.1 上 `workflow-worker-thread` → `workflow-ptc` 的情况。
  `dsh-plugin-rows.json` 快照、安装器的失败关闭与 `--probe` 三道检查覆盖它（见上）。
- DSH 会把 MCP server 的 instructions 作为 prompt 文本注入会话（`### MCP server: …`，
  每个 server 默认上限 32768 字节，超限会让该实例连接失败）。因此
  `server/MCP_*_BOOTSTRAP.md` 会随 server 一起进入 DSH 会话；四个文件目前合计约
  8.6 KB，远低于上限。
- 对外呈现 Research / Create / Learning 三个工作流与显式 `poe-bd-research-worker`；
  实验性对照学习 loop（`poe-bd-learning-loop`）随 preset 一起安装，但不在对外介绍里主推。
- `poe-bd-research` Controller 用 `subagent` 派发显式 `poe-bd-research-worker`；对照学习
  loop 同样用 DSH 的 `subagent` + `send_message` 映射 Desktop 任务：Reference 与 Create 是
  两个独立子代理，把 `subagent` 返回的持久 agent id 同时作为 `task_id` 与 `thread_id`；
  Compare/Learn/rereview 用 `send_message` 回到同一个 Reference 子代理。
- stdio 子进程环境会被 scrub（凭据类变量与 `DSH_*`），`PYTHONUTF8`/`PYTHONPATH`
  已在行内显式声明。
- 动态 Cordis 插件（`cordis_define`/`cordis_run`）不是本适配的交付形态，仅适合
  运行时调试；正式能力来自 patch / preset 两层的静态组合。
- **bundle 与 preset 不能同时注册同一批 server**：`dsh/bundle/` 只携带 layer-1 MCP 行，
   preset 也含同样四行。同一个 `serverName` 在两处注册时，后加载的实例会失败（并且
   各自拉起一份 PoB 引擎）。因此装 bundle 的 profile 不要再叠加本 preset 的 MCP 行；
   需要会话隔离时用 preset，需要全 profile 可见时用 bundle。
