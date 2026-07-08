# Phase 4 - Researcher 语义记忆

## 状态

Phase 4 基础闭环已完成：项目已经具备把外部 Researcher Agent 提交的
copy-safe、resolver-backed、versioned mature-build knowledge 写入长期记忆和 advisory
semantic graph 的能力。

Phase 4.5 继续维护在本文档内，作为进入 Phase 5 前的补课阶段，目前也已完成产品化收口。
它补的是知识覆盖和提取深度：让系统能从成熟 BD 中抽取升华壳、技能包、关键天赋、暗金、
资源/Spirit、防御层、机制链、阶段切换和失败条件，而不是只存零散技能联动。

用户-facing 入口统一叫 `/poe-bd-research` / `$poe-bd-research`。`phase45` 只作为内部阶段名
和 legacy 兼容名保留，不再作为推荐用户命令。

## Phase 4 已交付

- `ResearcherOutput schema_version=4`、strict proposal schema、typed `context_requirements`
  和 structured rejection envelope。
- `build_research_packet` transient packet helper：raw PoB code/XML 只允许临时使用，支持
  tempfile 前缀目录、TTL 和清理。
- `query_research_memory`、`propose_research_fragments`、`append_evidence_to_fragment`、
  `propose_semantic_edges`、`propose_build_patterns`、`submit_revalidation_result` 等 MCP /
  service gate。
- SQLite mature-learning schema：clean fragments、fragment evidence、semantic edges、
  build design observations、build patterns、rejected proposals、patch revalidation。
- semantic edge gate：endpoint 必须来自 Phase 3 resolver，proposal 必须携带 resolver
  evidence、typed context、version 和 copy-safety fields。
- patch decay / revalidation：memory item、semantic edge、build pattern 可进入
  `needs_revalidation`，复核后可恢复或产生 successor。
- Phase 5 handoff：`build_phase4_architect_research_context.py` 输出 creator-visible、
  planner-visible、copy-safe context，并包含 `usedFragmentIds`、`usedSemanticEdgeIds`、
  `usedPatternIds` 和 verification tasks。

## 安全边界

- 项目不新增内部 OpenAI / Claude / Gemini provider loop；研究推理由 Codex、Claude Code、
  Gemini 等外部成熟 agent 执行。
- raw mature-build material 只能出现在 quarantine-only transient packet 中，不能进入 durable
  report、state、memory、creator-visible context 或普通聊天输出。
- 禁止持久化或暴露 PoB code、raw XML、完整装备表、完整 passive path、完整 gem/support links、
  raw account / character details、完整 URL 或长篇复制攻略文本。
- 没有 static source，不能创建 physical graph node。
- 没有 resolver-backed physical endpoint，不能创建 semantic edge。
- mature BD semantic edges 和 build patterns 都是 advisory research context，不是 hard
  legality、PoB 数值证明或 reward weight。
- unresolved / ambiguous / source coverage gap endpoint 不能被自动选中；它们应进入 manual
  mapping、static source refresh 或 verification task。

## 产品化入口

安装 skill 后，在 Codex 或支持 skill 的宿主中使用：

```text
/poe-bd-research --limit 50 --worker-count 5
```

这是会话里的 skill invocation，不是要求用户在 Codex 输入框里执行 shell 命令；宿主 agent 应
通过工具运行内部脚本。

若无参数触发 `/poe-bd-research`，skill 应先询问运行数量和模式，而不是先联网 dry-run 或静默
启动完整 live crawl。若宿主支持交互式选择/确认 UI，优先给出“预检 5 个样本（推荐）/ 小批量
提取 20 个样本 / 大批量提取 50 个样本 / 恢复已有队列”这类可选项；否则退化为普通文字选项。
`--resume` 是独立恢复模式，不绑定到 50 个样本。

等价的底层脚本入口是：

```powershell
.\.tools\uv\uv.exe run python scripts\research_mature_builds.py queue --limit 50 --worker-count 5
.\.tools\uv\uv.exe run python scripts\research_mature_builds.py claim --output-dir .poe-bd-research
.\.tools\uv\uv.exe run python scripts\research_mature_builds.py worker-brief --output-dir .poe-bd-research --lease-token <leaseToken>
.\.tools\uv\uv.exe run python scripts\research_mature_builds.py prompt --output-dir .poe-bd-research --lease-token <leaseToken>
.\.tools\uv\uv.exe run python scripts\research_mature_builds.py accept --output-dir .poe-bd-research --lease-token <leaseToken> --review-file <safe-review.json>
.\.tools\uv\uv.exe run python scripts\research_mature_builds.py status --output-dir .poe-bd-research
```

macOS / Linux 将 `.\.tools\uv\uv.exe` 替换为 `./.tools/uv/uv`。

默认行为：

- 从 poe.ninja 当前 softcore trade league 拉取样本；
- 等级默认 90-100；
- `--limit` 默认 50；
- `--worker-count` 表示并发 Researcher agent lane 数，不表示预生成多个 raw prompt；
- `worker-brief` 输出 safe-only `workerPrompt`，宿主必须把它原样发给 subagent，不能只发本机
  `SKILL.md` 路径或临时口头说明；
- 支持 `--ascendancy`、`--league current|<league-url>`、`--level-min`、`--level-max`、
  `--source-file`、`--source-batch-file`、`--resume`、`--dry-run`、`--db-path`、
  `--output-dir`；
- batch mode 仍必须一案一轮：一个 Researcher prompt 只包含一个完整 BD；
- 默认不复用 raw-rich Researcher transcript，避免前一个样本污染后一个样本；
- 不支持程序化 subagent 的宿主必须报告 `requestedWorkers`、`effectiveWorkers=1` 和降级原因，
  然后串行执行。
- `/poe-bd-research` 是产品运行态，不是开发任务。运行期间 agent 不得修改仓库源码、测试、
  文档、schema、安装脚本或 plugin manifest；collector / source / runtime 失败时只报告
  safe error 并停止。

`queue`、`claim`、`status`、`accept` 都只输出 safe metadata。`prompt --lease-token` 是唯一
允许输出 raw-rich transient material 的子命令，只能由持有 lease 的 Researcher worker 临时
读取；主 orchestrator 不应转述或持久化它。

## 提取目标

Phase 4.5 的 mature BD 设计观察包括：

- 升华 + 主技能：作为 shell suitability，不作为技能合法性；
- 主技能 + secondary skill：标明 clear、boss、generator、payoff、movement、trigger host 等
  role；
- 技能 + key passive / notable / keystone：必须 resolver-backed；
- 暗金 + 天赋点 / 技能：区分 enabling、optional / chase、budget substitute；
- support + active skill：允许单 pair，禁止复制完整 support link 套餐；
- skill / archetype + scaling axis、weapon/base/stat priority；
- Spirit / reservation package + build shell；
- defense layer package + content goal；
- mechanic chain：generator -> transformer -> payoff；
- transition gate、failure mode、variant relation、modelability caveat。

提取采用两段式：先形成 `BuildDesignObservation`，再把 resolver-backed、copy-safe、证据足够的
部分提升为 semantic edge / cooccurrence pattern / planner hint。单样本只能写
`case_observation`，不能声称 usually / commonly / 常见。跨样本 pattern 必须由样本数、
family count、source diversity 和 resolver-backed evidence 支撑。

## Legacy 兼容

旧脚本 `scripts/run_phase45_researcher_batch.py` 和
`scripts/phase45_accept_single_review.py` 仅作为兼容 wrapper 保留。它们会向 `stderr` 输出
deprecation warning，`stdout` 保持机器可读，避免污染 JSON。公共 README、MCP guide 和 skill
不再推荐这些旧命令。

之前程序化写入的 30 条浅层 `case_observation` 保留审计记录，但不作为 Deep Researcher 结果：
它们应保持 `needs_revalidation` / `planner_visible=0`，不进入 Phase 5 默认 handoff。

## 验收

Phase 4 已完成工程链路；Phase 4.5 已完成产品化入口收口：用户可以用一个产品入口启动
批量队列，在本地外部 agent 环境中逐案例完成 deep Researcher 提取，并通过 MCP/service
gates 写入 durable memory。

Focused 验证：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_research_mature_builds.py tests/test_research_productization_docs.py -q
.\.tools\uv\uv.exe run pytest tests/test_research_prompt.py tests/test_research_memory.py -q
```

阶段级验证：

```powershell
.\scripts\verify.ps1 quick
```
