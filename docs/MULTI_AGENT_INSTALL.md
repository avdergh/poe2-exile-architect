# 多 Agent 安装与验证

本项目采用“一个规范 skill 源 + 一个本地 MCP server + 薄宿主适配器”的结构。业务规则只维护在
`poe-bd-creator-plugin/skills/` 和 `server/`；安装器只负责把可移植 skill 链接到宿主发现目录，
并安全写入该宿主的 `poe2_build_mcp` 配置。

## 支持范围

- Codex：安装四个 skill，并写入 `~/.codex/config.toml`。
- Claude Code：安装 `poe-bd-research`、`poe-bd-create`，并写入 `~/.claude.json`。
- Cursor：安装上述两个 skill，并写入 `~/.cursor/mcp.json`。
- OpenCode：安装上述两个 skill 到原生目录 `~/.config/opencode/skills`，并写入
  `~/.config/opencode/opencode.json`；可用 `OPENCODE_CONFIG` 覆盖配置路径。
- `poe-bd-research-loop`、`poe-bd-learning-loop` 依赖 Codex Desktop 的可见任务编排，本阶段不迁移。
- Pi 能读取 Agent Skills，但完整 Create/Research 还需要 MCP 扩展层；在有一等、可维护的适配器前，
  不把 Pi 标为支持。

## 快速安装

从当前 checkout 安装 OpenCode：

```powershell
.\install.ps1 -FromCheckout opencode
.\install.ps1 -FromCheckout -Doctor opencode
```

```bash
./install.sh --from-checkout opencode
./install.sh --doctor opencode
```

面向普通开源用户，直接运行 checkout 中的 `install.ps1 opencode` 或 `./install.sh opencode`；安装器
会 clone/update `~/.poe-bd-creator/repo`。支持把 `opencode` 换成 `codex`、`claude` 或 `cursor`。

## 安全写配置

JSON 配置适配器只管理 `poe2_build_mcp` 一个条目：

- 保留其他顶层字段和其他 MCP server；
- 遇到同名但非本安装器管理的条目时失败关闭；
- 首次修改已有配置时创建一次 `.poe-bd-creator.bak`；
- 在 `~/.poe-bd-creator/host-config-state.json` 保存条目指纹；
- 卸载时只有“路径、条目和指纹仍完全匹配”才删除；
- 配置含注释或尾随逗号时不擅自重写，要求用户先转换为严格 JSON。

skill 使用 symlink/junction 指向同一 checkout，因此更新仓库后不会产生多份漂移副本。真实目录、
不属于安装器的链接以及用户修改过的 MCP 条目都不会被覆盖或删除。

## OpenCode 验收

1. 运行 doctor，确认 repo、uv、server 入口、配置条目和托管回执均为 `true`。
2. 重启 OpenCode，运行 `opencode mcp list`，确认 `poe2_build_mcp` 已连接。
3. 新建会话，要求 Agent“加载 `poe-bd-create` skill，并列出开始 Create 前必须确认的问题”。此步只
   验证 skill 发现，不应直接启动 Build run。
4. 再要求 Agent 调用 `get_freshness_report` 或 `engine_health`，验证 MCP tool discovery。
5. 最后用一个明确的单阶段 BD 请求做 smoke test；如果请求没有明确表示只要固定最终 BD，Agent
   应依项目合同先询问是否需要完整成长流程。

当前机器上的 Codex、Claude Code、Cursor 和 OpenCode MCP 配置若未设置 `POE2_MCP_DATA`，会落到
同一 OS 用户数据目录，因此可共享已有 Research Memory；不会复制数据库，也不会把本地学习状态
上传到任何服务。

## 开源项目采用的模式

这一设计参考了以下已公开做法：

- [Agent Skills 规范](https://agentskills.io/specification)：skill 目录使用可移植 `SKILL.md` 合同。
- [Vercel skills CLI](https://github.com/vercel-labs/skills)：一个 skill 源安装到多个 Agent，并优先
  通过链接避免副本漂移。
- [Serena](https://github.com/oraios/serena)：跨客户端复用一个本地 MCP 启动命令，不为每个宿主复制
  业务实现。
- [Context7 CLI](https://context7.com/docs/clients/cli)：由一个 setup 入口同时处理宿主 MCP 配置和
  skill 发现。
- [OpenCode MCP 文档](https://opencode.ai/docs/mcp-servers)：本地 server 使用命令数组、工作目录和
  环境变量配置。

本项目没有直接依赖这些项目的安装器代码；上面的参考只用于确定互操作结构和用户体验。

## 知识库分发边界

公开发布采用 local-first 混合方案：

- `global_seed` 与维护者当前 `local_user`：经过 copy-safety、版本和状态审计后，共同构建为带
  schema/version/hash 的 SQLite 种子，并直接提交到 Git、进入 GitHub Release 和 bundle。它们是
  开源数据产品，需要独立的数据许可与来源声明，不能自动沿用代码的 MIT 许可。
- Phase 7 Learning Memory：经过 durable copy-safety 与事件链校验后，构建独立 JSONL 种子并提交
  到 Git；它仍不进入 Research SQLite。
- quarantine、Research query receipts、progression/campaign、Judge 快照和最终 artifact 始终只
  留在用户本地。
- 首次启动只在本地数据库不存在时安装种子，不能覆盖已有用户库。后续种子更新应采用版本化合并或
  独立只读 seed + 可写 local overlay，不能整库替换。
- 中央服务器不是运行必需项。只有将来需要用户明确 opt-in 的社区投稿、快速撤回或跨设备同步时，
  才增加服务端；离线 Create/Research 仍应可用。

维护者发布前运行：

```powershell
.\.tools\uv\uv.exe run python scripts\audit_public_research_memory.py
.\.tools\uv\uv.exe run python scripts\build_research_release_seed.py --release-version <version>
```

第一条命令只输出计数、版本覆盖和被阻止的安全 ID，不输出知识正文；第二条命令从本地 mutable DB
生成隔离的 release seed。只提交净化后的只读种子，绝不能提交日常可写数据库；GitHub checkout、
Release 资产和插件 bundle 使用同一份内容寻址种子。
