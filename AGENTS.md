# AGENTS.md - Poe2 BD Creator Agent 指南

这是本仓库给 Codex、Claude Code 和其他编码 agent 使用的标准工作指南。长期有效的规
则放在这里，具体阶段执行清单放在 `docs/phases/`。

## 文档语言策略

- `docs/ARCHITECTURE.md` 和 `docs/ARCHITECTURE.CN.md` 是当前唯一维护双语的文档。
- `docs/PROJECT_SPEC.md`、`docs/SCHEMAS.md`、`docs/phases/*.md`、`AGENTS.md`、
  `CLAUDE.md` 以及其他仓库说明文档只维护中文。
- 不要新增 `.CN.md` 副本，除非用户明确重新改变语言策略。

## 项目方向

PoE2 BD Creator 是 verification-first 的 Path of Exile 2 BD 研究与生成工具基座。
Codex、Claude Code 等外部成熟 agent 负责研究、推理、比较、反思和 BD 合成。仓库本
身提供确定性工具、结构化记忆、图知识、安全边界和评估合同。

长期闭环是：

```text
成熟 BD 数据 / PoB 导出 / pobb.in / poe.ninja
  -> quarantine-only raw intake
  -> 外部 Researcher Agent
  -> clean fragments + graph knowledge + long-term memory
  -> 外部 Architect Agent
  -> deterministic planners 与 Headless PoB judge
  -> reference comparison 与 Critic Agent gaps
  -> rollback / repair / early stopping
  -> reward events 调整 graph 和 memory 权重
```

仓库不应再增长项目内 autonomous LLM/provider loop。不要新增项目自带的 OpenAI/Claude
API runner、隐藏 agent loop，或持久化模型调用 prompt/report 日志。

## 不可协商规则

- 不要从零编写新的数值 BD 引擎。数值声明必须使用现有 Headless PathOfBuilding-PoE2
  wrapper，或明确标记为 unverified/unmodelled。
- 没有 PoB/modelability evidence，就不能声明 DPS/EHP/抗性/Spirit 合法性。
- 没有 static source，就不能创建 physical graph node。
- 没有已存在 graph node，就不能创建 semantic graph edge。
- 没有 typed tool，就不能让 agent 查询图。不要暴露 raw Cypher/Gremlin/SQL 拼接给
  agent。
- 没有 patch/version/status，就不能进入 durable memory。
- 没有 copy-safety pass，就不能持久化成熟 BD 知识。
- 没有 snapshot score improvement，就不能声称 loop 成功。
- 没有 early stopping，就不能做 autonomous repair loop。
- 不要持久化或暴露可复刻成熟 BD 的材料：PoB code、raw XML、完整装备表、完整
  passive path、完整 gem/support links、raw account/character 细节或长篇复制攻略文本。
- 禁止游戏内交互、overlay、内存读取、自动化或 live-screen parsing。

## 当前事实源

- `AGENTS.md`：标准 agent 操作规则和工具地图。
- `CLAUDE.md`：轻量 Claude Code shim，指回本文件。
- `docs/PROJECT_SPEC.md`：中文唯一项目总纲，维护方向、边界、Phase 关系和 Phase 状态。
- `docs/ARCHITECTURE.md` / `docs/ARCHITECTURE.CN.md`：高层架构和数据流，唯一双语文档。
- `docs/SCHEMAS.md`：中文唯一核心数据结构合同。
- `docs/JUDGE_SCORING_SYSTEM.md`：Judge 当前评分策略、证据分层、兼容逻辑和查询路径说明。
- `docs/phases/`：中文唯一各阶段执行计划和验收标准。
- `server/ASSISTANT_GUIDE.md`：通过 MCP 展示给 LLM client 的 runtime 指南。
- `scripts/verify.ps1`：验证 profile。

开发阶段有意不保留 `README.md`。等 learning/generation/evaluation loop 有 benchmark
证据后再重建。

## 命令

如果 Windows 工作区的 PATH 里没有 `uv`，使用仓库自带的 uv：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_fragment_extraction.py -q
.\.tools\uv\uv.exe run pytest tests/test_mature_fragment_extraction.py tests/test_mature_ninja_payload.py tests/test_mature_pobb_payload.py tests/test_mature_source_intake.py tests/test_mature_source_probe_runner.py tests/test_mature_sources.py tests/test_mature_sample_contract.py tests/test_mature_eval.py -q
.\scripts\verify.ps1 quick
```

验证梯度：

- touched module 使用 focused tests；
- knowledge/MCP/lifecycle/doc 改动使用 `.\scripts\verify.ps1 quick`；
- 跨范围非 engine 改动使用 `.\scripts\verify.ps1 noncompute`；
- engine、PoB、optimizer、runtime packaging 或 release gate 才使用 `compute` / `full`；
- `compute` / `full` 是重型 Headless PoB 认证入口，本地 Windows 经常运行 15 分钟以上。
  调用这些 profile 时，外层命令超时必须至少给到 30 分钟（`1800000ms`）；10 分钟工具超时
  只能说明外层预算不足，不能直接判定 compute suite 失败。`scripts/verify.ps1` 会为这些
  profile 传入 30 分钟 pytest 单测试超时。

## 工具 / 文件地图

### 入口

- `server/main.py`：MCP server 和公开 tool 注册。只有实现已放在正确层级后，才在这里新
  增用户可见 MCP tool。
- `server/ASSISTANT_GUIDE.md`：通过 MCP instructions 交付给 LLM client 的 runtime 指南。
- `server/BUILD_ADVICE.md`：由 `build_advice` 搜索的持久 BD 原则文本。

### Compute 层

- `server/compute/engine.py`：长生命周期 Headless PathOfBuilding-PoE2 JSON-RPC 进程和
  build state 调用，是数值权威。
- `pob/pob_headless.lua`：进入 pinned PoB-PoE2 代码的 Lua bridge。
- `server/compute/pob_code.py`：PoB share code/link/XML import/export codec。
- `server/compute/buildopt.py`：整体 build optimizer。
- `server/compute/itemopt.py`：rare item、jewel、gear-plan 和 upgrade optimization。
- `server/compute/craftopt.py`：crafting-system optimization。
- `server/compute/supportopt.py`：engine-measured support selection。
- `server/compute/solver.py`：stat lever ranking 和 target solving。
- `server/compute/skilltext.py`：skill text normalization 和 lever templates。

### Judge 层

- `server/judge/models.py`：Phase 1 judge 的 evaluator version、v3 metric keys 和 failure code
  / caveat 常量。
- `server/judge/rules.py`：class/ascendancy、support/socket v1、PoB weaponCheck 和
  physical-invalid blocker；weapon/skill 兼容性以 PoB readback 的 `disableReason` 为权威，
  不要在 Python 里按技能名硬编码武器需求。
- `server/judge/scoring.py`：`judge_v3_evidence_aware` 评分；hard floor 与 quality target
  分离，动态可用主资源池 recovery、异构 Max Hit、CI 混沌免疫、EHP 物理短板补偿和扁平
  aggregate 权重；`scoreBreakdown.offense` 必须输出 provenance、evidence level、raw/effective
  DPS 和 minion/count 诊断。
- `server/judge/modelability.py`：partial modelability、main socket group core blocker 和轻量
  whitelist caveat。
- `server/judge/evaluator.py`：从 active PoB readback 生成内部 `BuildEvaluation`；如果
  `judgeSelectedSkill` 被用于 offense，socket/modelability/weaponCheck 也必须跟随 selected
  skill group，而不是继续检查最后点击的 buff/战旗组；输出 `defenseModel` 只作诊断，不替代
  PoB Max Hit / EHP 评分证据。
- `server/judge/comparison.py`：候选与参考的 `selectionWinner` / `rewardWinner` /
  `rewardStrength` 合同；limited evidence 可以 selection，但 `rewardWinner` 必须保持
  `unknown`，不能写成强 reward。
- `server/judge/runner.py`：dedicated engine safe-call，处理 import/evaluation timeout、EOF 和
  crash recovery。
- `server/judge/fixtures.py`、`server/judge/benchmark.py`：synthetic Phase 1 baseline，写入
  user-data runtime，不进入仓库。
- Judge 当前是内部基线，不在 `server/main.py` 注册 MCP tool。真实样本验收前不要把它包装
  成用户可见工具。
- Phase 1 对使用 weapon set passives 的 dual-state build 只给 limited reward；没有 State_A /
  State_B 分别评分证据时，不能把单状态最高 DPS 写成强学习信号。
- Phase 1 对 `FullDPS` rollup、召唤物 PoB output、投射物下界、关键 metric 缺失等 evidence
  只给 limited reward；这些信号可以帮助单个 BD 诊断，但不能污染后续 reward memory。

### Knowledge 层

- `server/knowledge/db.py`：SQLite/FTS corpus 查询。
- `server/knowledge/mechanics.py`：本地 mechanics 解释和 wiki-tier 引用。
- `server/knowledge/refbuilds.py`：仅用于校准的 reference build 摘要。
- `server/knowledge/lifecycle.py`：lifecycle route 模型、feedback memory 和 route helpers。
- `server/knowledge/lifecycle_*`：lifecycle cohort evidence、source evidence、verification、
  quality gates 和 evaluation harness。
- `server/knowledge/mature_learning.py`：mature-learning SQLite schema、sanitizer、seed import
  和 deterministic baseline extraction。这里的安全边界不能破坏。
- `server/knowledge/copy_safety.py`：共享 copyability guard。
- `server/knowledge/mature_sample_contract.py`：sanitized mature sample manifest 校验。
- `server/knowledge/mature_eval.py`：creator/evaluator contamination 和 typed gap 合同。
- `server/knowledge/mature_fragment_extraction.py`：外部 agent research packet builder 和 clean
  fragment schema v3 validator。它不能调用模型 provider。
- `server/knowledge/mature_source_intake.py`：按 build family 聚合来源变体，并构建供外部
  agent 研究的 raw-rich、quarantine-only case。
- `server/knowledge/mature_ninja_payload.py`：从渲染后的 poe.ninja build 页面提取 PoB import
  material，并转换为 quarantine-only payload row。
- `server/knowledge/mature_pobb_payload.py`：把 pobb.in 链接或 raw build source 导入为
  quarantine-only payload row。

### Live / Freshness 层

- `server/freshness/*`：patch/tree/PoB/poe.ninja freshness providers、cache 和 evaluator。
- `server/live/meta.py`：live meta shaping。不要从 ascendancy-only 数据推断 build-level
  popularity。
- `server/live/mature_sources.py`：对 build-level source 可用性做 copy-safe response-shape
  probe。
- `server/live/mature_source_probe.py`：比较候选成熟样本来源，并渲染安全的 source-probe
  report。
- `server/live/prices.py`、`wiki.py`、`update.py`、`version.py`：价格查询、live wiki fallback、
  更新和版本辅助。

### Scripts 和 Data

- `scripts/run_mature_source_probe.py`：本地 source-probe report 辅助脚本。它不运行 LLM。
- `scripts/run_judge_user_samples.py`：Phase 1 真实 PoB code transient 验收脚本。输出
  sanitized report，不持久化 raw PoB code/XML；允许输出 `judgeSelectedSkill` 摘要以便审查
  buff/战旗/辅助技能导致的 0 DPS 误读，但禁止输出完整 gem/support links。输入支持整文件
  XML、JSON/JSONL/manifest、显式分隔符和逐行 code；失败报告只输出 sanitized `errorKind`。
- `scripts/smoke_*.py`：按子系统划分的 focused smoke checks。
- `scripts/install_local_validated_runtime.py`：安装已认证 runtime data 到本地。
- `scripts/build_bundle.py`：构建 `.mcpb` bundle。
- `data/mature_build_learning/seed_cases.json`：只保存 sanitized seed mature cases。
- `data/reference_builds.json`：只保存校准摘要，不是模板。

## 阶段文档

- `docs/phases/00_cleanup.md`：Phase 0 cleanup 和文档结构。
- `docs/phases/01_judge_eval.md`：deterministic judge 和 modelability matrix。
- `docs/phases/02_graph_cold.md`：physical graph cold start 和 official ID mapping。
- `docs/phases/03_graph_tools.md`：graph backend 和 typed graph tools。
- `docs/phases/04_research_memory.md`：Researcher extraction 进入 semantic graph 和 memory。
- `docs/phases/05_generation.md`：Architect generation、OR-Tools gear solver、Spirit planning。
- `docs/phases/06_build_export.md`：官方 `.build` export 和 leveling progression。
- `docs/phases/07_critic_loop.md`：rollback、repair 和 early stopping。
- `docs/phases/08_reward_memory.md`：RLAIF-lite reward memory。
- `docs/phases/09_scale_productization.md`：scale、revalidation 和后续 productization。

## 编辑政策

- 优先使用聚焦模块和既有模式。
- 手工编辑使用 `apply_patch`。
- 除非用户明确要求，否则不要 revert 用户改动。
- 不要新增长篇历史规划文档。阶段细节更新对应的 `docs/phases/*.md`。
