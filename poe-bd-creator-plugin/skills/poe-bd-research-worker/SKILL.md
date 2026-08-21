---
name: poe-bd-research-worker
description: Internal explicit-only worker for one leased PoE2 mature-build Research case. Use only when the poe-bd-research Controller supplies an existing runDir; never create or resume a queue.
---

# PoE BD Research Worker

本 Skill 只供 `poe-bd-research` Controller 显式派发。它从既有队列原子 claim 一案，完成证据读取、
研究、safe review、校验和 accept，然后停止。

## Assignment Boundary

开始前必须收到 `runDir`：既有 Research run 的规范化绝对路径。

缺少绑定、runDir 中没有 `poe_bd_research_queue.sqlite`，或当前任务不是 Controller 的显式 Worker
派发时，返回 `worker_assignment_missing` 并停止。不得自行发现其他仓库、创建/恢复 queue、使用默认
`.poe-bd-research`、询问用户运行模式或回退为主会话研究。

## Runtime Binding

只在已加载 Worker Skill 的安装内解析运行前缀：

1. `runtimeRoot` 优先取安装器管理的任一 `poe_*_mcp` cwd；否则取 `POE_BD_CREATOR_DIR`，再否则从本
   Skill 的真实路径向上查找。候选必须包含 `server/main.py` 和 `scripts/research_mature_builds.py`，且
   是带 `pyproject.toml` 的源码仓库，或带 `.codex-plugin/plugin.json` 与
   `scripts/run_plugin_server.mjs` 的自包含插件；缺失或歧义时返回 safe failure，不猜 cwd 或全盘搜索。
2. 源码仓库在 Windows 依次使用 `runtimeRoot/.tools/uv/uv.exe`、PATH uv；macOS/Linux 依次使用
   `runtimeRoot/.tools/uv/uv`、PATH uv，调用前缀为：

   ```text
   <uvCommand> run --project <runtimeRoot> python <runtimeRoot>/scripts/research_mature_builds.py
   ```

   自包含插件复用 MCP 已注册的 Node，或从 PATH 解析 Node，调用前缀为：

   ```text
   <nodeCommand> <runtimeRoot>/scripts/run_plugin_server.mjs --research-cli
   ```

Node 只作为插件官方 Python 启动器，不把它当成 uv。路径含空格时使用宿主的原生参数边界；不得把
runDir 或 runtimeRoot 回退为当前 cwd。

## Runtime Boundary

- 只处理一个 claim；完成或失败后不得领取第二案、嵌套委派或执行 cleanup。
- 这是产品运行态，不得修改源码、测试、文档、schema、安装配置或其他 run artifact。
- 唯一允许编辑的文件是当前 lease 的 `reviewFile`，使用文件编辑工具或 `apply_patch`；不得用
  here-string、`Set-Content` 或内联 JSON 重写整份 review。
- 原始 PoB/XML 只留在 quarantine 与 lease-bound transient packet；不得进入聊天、safe review 或
  durable memory。
- 工具未直接显示时先用宿主标准 tool discovery/search 查找 `query_research_memory` 与
  `graph_tool_query`，不要根据首屏列表断言不可用。

## Single-Case Workflow

1. 使用已验证运行前缀执行：

   ```text
   claim --output-dir <runDir>
   ```

   `worker_capacity_reached` / `no_pending_cases` 是无 sampleId 的调度结果，原样返回后停止。`claimed`
   后保存 `sampleId`、`leaseToken`、`reviewFile` 和完整 `workerPrompt`；后续所有命令都绑定同一
   runDir/lease。

   `claim_packet_failed` 已包含 sampleId：原样返回 safe outcome 后停止。`leaseReleased=true` 表示案例
   已安全回到 dispatchable 队列；`recoveryRequired=true` 时不得重试或猜测状态，交给 Controller 停止
   补位并报告。

2. 直接遵守 `workerPrompt`。先 `inspect`，再按其指定顺序用可分页 `read` 读完全部分区；`search`
   只能定位具体线索，不能替代完整读取。先独立重建案例，再查询 Research Memory，并通过
   `search_graph_components` → `resolve_graph_component` 确认 stable key。
   Family 查询用 `primary_skill_key=skill:/gem:`；`build_family_keys` 只接收查询已返回的 `bf-...`，
   未知时省略，禁止把技能 key 填进去。

3. 初步研究完成后运行 `review-contract`，以其 `mandatoryChecks`、模板、枚举、兼容矩阵和 rules 为
   当前 lease 的精确事实源；不得从本 Skill 猜字段或固定检查数量。

4. 运行 `init-review` 原子创建骨架，只编辑返回的 reviewFile。`already_exists` 表示保留已有工作，
   不得覆盖重建。

5. 先执行 `accept --validate-only`。结构、resolver、角色、因果或职责变化后，对完整对象重新复核；
   按 validationIssues 有界修正。missing/ambiguous endpoint 最多进行两轮 repair，不能要求程序猜枚举
   或自动选择端点。

6. Mandatory Checks 全部通过后执行正式 `accept`。可修复的 `acceptance_rejected` 使用同一 safe review
   走 `retry-accept --sample-id <sampleId>`；不要把 validation/retry 当成新案例。不可恢复的 runtime
   错误停止当前 Worker，保留 run/lease 状态并返回 safe failure。

7. claim 成功后的任何结束路径都返回 `sampleId + safe outcome`；accepted 时附 safe acceptance 摘要，
   至少包含 acceptanceMode、created/updated/evidence counts、semantic edge count、deferred reasons、
   unresolved mention/unique component counts 和 mechanic/unique-gem diagnostics。不得输出 raw material。

## Supplemental Checks

- 补充研究或更正既有知识时，优先以相同标题/知识构成更新原记录；不要制造新旧矛盾正文。确需废弃旧
  结论时明确失效理由。
- `gearResponsibilities` 只归因组件静态文本直接提供的职责；来源实例词缀、插入物或转换效果必须归因
  到真实来源。无图节点的纯稀有/魔法装使用显式 `gearResponsibilities=[]`，并在 content 写槽位、目标
  词条和档位追求。
- 在 validate-only 和正式 accept 前复核每个最终对象的 title、summary、content、conditions、
  failureConditions、typedPayload、applicability/exclusions、contextRequirements、plannerHint 与
  verificationTasks；未复核字段不得沿用。
