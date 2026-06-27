# PoE2 BD Creator 项目架构

Last updated: 2026-06-27

本文档配合 `docs/PROJECT_SPEC.md` 使用。`PROJECT_SPEC` 记录目标、当前阶段和真实状态；
本文档记录项目结构、关键文件职责、核心工作流和 Codex 接续指南。

如果两份文档与代码或最近提交冲突，以代码和最近验证结果为准，并立即更新这两份文档。

## 1. 项目定位

本项目的最终目标是做一个可靠的 Path of Exile 2 BD Creator。它可以作为 MCP server
服务 Claude Desktop，也可以作为 Codex / Claude Code 中的研究型 agent 工具链。

核心定位不是“写死一批 build 模板”，而是让 LLM 在可靠工具约束下完成 BD 研究、创造和迭代：

- LLM 负责研究、提问、归纳、生成、解释、对比和反思；
- PoB2/headless engine 负责可计算数值；
- freshness layer 负责当前赛季、patch、tree、PoB 数据可信度；
- sanitizer / SQLite / evidence tables 负责边界、provenance、copy-safety 和可回溯性；
- tests 和真实效果评测共同决定系统是否真的变强。

## 2. 非协商边界

- 当前 meta 相关结论必须先经过 freshness gate。
- DPS、EHP、抗性等数值必须来自 PoB/engine 或明确标注为未验证。
- poe.ninja、pobb.in、论坛、攻略、reference builds 是研究来源，不是复制来源。
- 不保存或输出可复刻成熟 BD 的 raw 内容：PoB code、完整装备、完整天赋树、完整 node list、完整 gem links、攻略全文。
- 用户反馈默认是本地 episodic memory，不进入 global seed。
- LLM 可以生成技巧候选，但不能直接晋升 durable memory，不能跳过 evidence / patch-tree / PoB / safety 边界。

## 3. 高层架构

```text
User / LLM Agent
    |
    v
server/main.py  (MCP tool surface + orchestration)
    |
    +--> server/compute/*      PoB2 engine、build state、optimizer、数值验证
    +--> server/knowledge/*    corpus、lifecycle、reference、mature learning、memory
    +--> server/freshness/*    patch/tree/PoB/poe.ninja freshness evidence
    +--> server/live/*         live price/wiki/meta/update adapters
    |
    v
data/* / .runtime-data/* / pob/*
```

Agent 层应按这个顺序工作：

1. 理解用户目标和约束。
2. 检查 freshness。
3. 收集证据：corpus、reference、live meta、mature samples、用户反馈。
4. LLM 形成机制假设和生命周期路线。
5. 用 engine 验证可计算部分。
6. 对不可计算机制写 caveat。
7. 输出 starter → transition → maps → budget endgame → final 的路线。
8. 记录反馈；只有验证过的技巧才可能晋升。

## 4. 顶层目录

| 路径 | 作用 |
| --- | --- |
| `README.md` | 面向使用者的项目说明、安装、工具列表和能力介绍。当前仍偏 MCP/server 视角。 |
| `PLAN.md` | 早期总体设计与路线说明，保留历史价值，但当前接续应优先读 `PROJECT_SPEC`。 |
| `CLAUDE.md` | 面向 Claude/Codex 的工程约定、常用命令、工作流规则。 |
| `pyproject.toml` | Python 项目元数据、依赖、ruff/mypy/pytest 配置。 |
| `uv.lock` | uv 锁文件。 |
| `manifest.json` | MCP bundle / Claude Desktop extension manifest。 |
| `PACKAGING.md` | `.mcpb` 打包与发布说明。 |
| `LICENSE` | 项目许可证。 |
| `assets/` | 图标等静态资产。 |
| `data/` | 本地 corpus、reference builds、兼容性信息、mature-learning seed fixtures。 |
| `docs/` | 架构、规格、审计、研究、历史实施计划。 |
| `pipeline/` | 离线构建 corpus/reference 数据的脚本，不在 runtime hot path。 |
| `pob/` | 本地 PathOfBuilding-PoE2 工作副本和 pin 信息。体积大，主要供 engine/runtime 使用。 |
| `runtime/` | 打包或本地运行所需 runtime 资源。 |
| `scripts/` | 验证、smoke、打包、runtime 安装等开发脚本。 |
| `server/` | MCP server 与核心功能实现。 |
| `tests/` | pytest 测试，覆盖 compute、freshness、lifecycle、MCP surface、mature learning 安全边界等。 |

## 5. `server/` 文件职责

### 入口与通用文件

| 文件 | 作用 |
| --- | --- |
| `server/main.py` | MCP server 主入口；注册 tools/prompts/instructions；连接 compute、knowledge、live、freshness、lifecycle。体积较大，修改前应先定位具体 tool。 |
| `server/paths.py` | 统一管理 repo/data/user-data/runtime 路径。mature learning DB path 等路径应走这里。 |
| `server/scaffold.py` | build scaffold / baseline gear 等辅助逻辑。 |
| `server/ASSISTANT_GUIDE.md` | 通过 MCP instructions 给 LLM 的操作指南；影响 LLM 如何使用工具。 |
| `server/BUILD_ADVICE.md` | 面向 LLM 的通用 BD 原则和机制建议。 |
| `server/__init__.py` | package marker / lightweight metadata。 |

### `server/compute/`

compute 层与 PoB/headless engine 相关，负责数值与 build state。知识层不应反向依赖 compute。

| 文件 | 作用 |
| --- | --- |
| `engine.py` | 管理 headless PoB JSON-RPC subprocess、engine health、build state 调用。 |
| `pob_code.py` | PoB share code / XML import-export codec。 |
| `buildopt.py` | 整体 build optimizer：archetype-seeded、gear/tree/support 等组合优化。 |
| `itemopt.py` | 单件装备 rare crafting / affix 选择 / gear optimization。 |
| `craftopt.py` | 更完整的 crafting 系统，包括 runes/soul cores/essences/corruptions 等。 |
| `supportopt.py` | support gem 组合选择，并用 engine 评估收益。 |
| `solver.py` | solve_for / rank_levers 等数值求解和边际收益计算。 |
| `skilltext.py` | skill text normalize 与 lever template 填充等纯 Python 辅助。 |
| `__init__.py` | compute package marker。 |

### `server/knowledge/`

knowledge 层负责 corpus、机制知识、reference calibration、lifecycle 研究、mature learning store。

| 文件 | 作用 |
| --- | --- |
| `db.py` | SQLite/FTS corpus 查询：items、skills、supports、mods、uniques、ascendancies 等。 |
| `mechanics.py` | wiki mechanics tier 查询与 mechanic explanation。 |
| `advice.py` | 读取/搜索 `BUILD_ADVICE.md`。 |
| `itemparse.py` | 解析物品文本、识别词缀/tier/open prefix/suffix。 |
| `refbuilds.py` | reference build calibration library；只输出非复制摘要和 engine-verified metrics。 |
| `lifecycle.py` | 生命周期 BD 核心模型、route synthesis、classification、feedback memory。当前较大，修改需小心。 |
| `lifecycle_cohort.py` | 非复制 reference cohort evidence。 |
| `lifecycle_evidence.py` | 从 source/guide text 中提取 lifecycle evidence。 |
| `lifecycle_verification.py` | stage verification budgets/executor，读取 active build engine stats 后做阶段 gate。 |
| `lifecycle_quality.py` | lifecycle route quality gate。 |
| `lifecycle_eval.py` | lifecycle route evaluation harness，用于回归和真实效果评测基础。 |
| `mature_learning.py` | Phase 3N mature build learning SQLite schema、sanitizer、fixture import、deterministic baseline extraction。后续 LLM extraction 应优先新增小模块，不继续无限膨胀此文件。 |
| `mature_sample_contract.py` | Phase 3N.3 样本 manifest 合同；校验 source/popularity/freshness/diversity 元数据，并拒绝 raw/copyable build 内容。 |
| `mature_llm_extraction.py` | Phase 3N.3 LLM extraction contract；已实现 copy-safe prompt package、schema validation 和 copyability guard。尚未实现候选/evidence 导入和模型 runner。 |
| `mature_eval.py` | Phase 3N.3 creator/evaluator contamination guard 与 gap 类型校验；已实现 creator 输入污染拒绝和 evaluator gap 合同。尚未实现完整 report runner。 |
| `__init__.py` | knowledge package marker。 |

### `server/freshness/`

freshness 层负责判断“当前数据是否可信”。涉及当前赛季和 meta 时必须优先使用。

| 文件 | 作用 |
| --- | --- |
| `models.py` | freshness evidence、component、claim、status 等核心模型。 |
| `provider_models.py` | provider result/cache policy 等 provider 层模型。 |
| `cache.py` | live provider cache、refresh throttling、concurrency guard、file cache store。 |
| `ggg.py` | GGG patch/tree freshness provider。 |
| `pob.py` | PathOfBuilding-PoE2 release/commit/data compatibility provider。 |
| `ninja.py` | poe.ninja snapshot/index provider；当前能拿 league/tree/sample-size 等 snapshot evidence。 |
| `providers.py` | provider composition / factory。 |
| `evaluator.py` | 将多源 evidence 汇总成 freshness gate 判断。 |
| `service.py` | freshness service runtime integration。 |
| `__init__.py` | freshness public exports。 |

### `server/live/`

live 层是网络适配器，不应直接替代 freshness/evidence 逻辑。

| 文件 | 作用 |
| --- | --- |
| `prices.py` | poe2scout 等价格查询。 |
| `meta.py` | live meta / poe.ninja aggregate shaping；当前 build-level rows 不可用时必须返回 unavailable，不能猜。 |
| `mature_sources.py` | Phase 3N.3 source probe shape helper；记录 poe.ninja / fallback 来源的响应形状与失败原因，不返回 raw 内容。已实现 copy-safe shaping；尚未实现自动抓取器。 |
| `wiki.py` | live PoE2 Wiki long-tail lookup。 |
| `update.py` | data/corpus/runtime self-update 逻辑。 |
| `version.py` | 本地/远端数据版本检查。 |
| `__init__.py` | live package marker。 |

## 6. `pipeline/` 文件职责

| 文件 | 作用 |
| --- | --- |
| `build_corpus.py` | 离线构建 `data/corpus.sqlite`，从 RePoE/poe2db/wiki 等源生成 FTS corpus。 |
| `wiki.py` | 构建 mechanics wiki tier 的抓取/清洗逻辑。 |
| `build_reference_builds.py` | 从 seed PoB codes 生成 `data/reference_builds.json`，只保存 calibration metrics，不保存复制用详情。 |
| `reference_builds_seed.txt` | reference build seed PoB codes。包含 raw PoB code，只用于离线构建 calibration 数据，不应出现在 LLM 输出或 mature learning seed。 |
| `__init__.py` | pipeline package marker。 |

## 7. `scripts/` 文件职责

| 文件 | 作用 |
| --- | --- |
| `verify.ps1` | 统一验证入口。profiles：`quick`、`noncompute`、`compute`、`full`、`lint`。 |
| `smoke_mcp_client.py` | 端到端 MCP stdio smoke，验证 server 真能作为 MCP 初始化、列工具、调用工具。 |
| `smoke_compute.py` | headless PoB engine smoke。 |
| `smoke_import.py` | PoB code round-trip/import smoke。 |
| `smoke_corpus.py` | corpus 查询 smoke。 |
| `smoke_m3.py` | config/item/evaluate/compare tool smoke。 |
| `smoke_live.py` | live ops smoke，涉及网络。 |
| `smoke_freshness.py` | freshness provider/gate live diagnostic。 |
| `smoke_optimize.py` | passive optimizer smoke。 |
| `smoke_passives.py` | passive search/allocate/deallocate smoke。 |
| `install_local_validated_runtime.py` | 将已认证 PoB/corpus 安装到本地 runtime data dir 的开发辅助脚本。 |
| `build_bundle.py` | 打包 `.mcpb`。 |
| `make_icon.py` | 生成 `assets/icon.png`。 |

## 8. `tests/` 文件职责

不要因为当前要引入 LLM 就删除既有测试。大多数测试保护的是安全边界和工程合同。

| 文件 | 作用 |
| --- | --- |
| `conftest.py` | 共享 pytest fixtures，包含昂贵 engine 的 session 级复用。 |
| `test_compute.py` | PoB engine 与 import codec 的 golden-value 认证，昂贵但关键。 |
| `test_server.py` | MCP instructions/prompts/tool surface 合同，保护 LLM 能看到的指南和工具形状。 |
| `test_lifecycle.py` | 生命周期 route、classification、transition、memory 等 Phase 3A 合同。 |
| `test_lifecycle_eval.py` | lifecycle evaluation harness 合同。 |
| `test_mature_learning.py` | mature learning schema/sanitizer/copyability/visibility/deterministic baseline extraction。安全边界部分非常重要。 |
| `test_freshness.py` | freshness model/evaluator 基础行为。 |
| `test_freshness_cache.py` | provider cache/throttle/concurrency 行为。 |
| `test_freshness_ggg.py` | GGG patch/tree provider。 |
| `test_freshness_pob.py` | PoB provider。 |
| `test_freshness_ninja.py` | poe.ninja provider。 |
| `test_freshness_service.py` | freshness service integration。 |
| `test_smoke_freshness.py` | smoke_freshness 脚本行为。 |
| `test_live_meta.py` | live meta shaping，保护“不猜 build-level rows”的边界。 |
| `test_mature_sources.py` | Phase 3N.3 source probe shape helper 测试，保护“不保存 raw 内容、不把 aggregate/ascendancy 当 build-level”的边界。 |
| `test_mature_sample_contract.py` | Phase 3N.3 样本 manifest 合同测试，保护 popularity/freshness/diversity 必填和 copyability 拒绝边界。 |
| `test_mature_llm_extraction.py` | Phase 3N.3 LLM extraction contract 测试，保护 schema、prompt、copyability 和 raw 字段拒绝边界。 |
| `test_mature_eval.py` | Phase 3N.3 creator/evaluator guard 测试，保护 holdout/evaluator/quarantine 不进入 creator 输入，并约束 evaluator gap 类型。 |
| `test_corpus.py` | corpus 查询。 |
| `test_refbuilds.py` | reference calibration library 输出非复制摘要。 |
| `test_passives.py` | passive search/allocation。 |
| `test_skilltext.py` | skill text normalize 和 lever template。 |
| `test_update.py` | data/runtime self-update 与 app-version nag 解耦。 |
| `test_install_local_validated_runtime.py` | local validated runtime installer。 |
| `test_project_config.py` | pytest timeout 等项目配置 guard。 |
| `fixtures/` | PoB/freshness 等测试 fixture。 |

## 9. `data/` 文件职责

| 文件或目录 | 作用 |
| --- | --- |
| `data/corpus.sqlite` | 构建好的只读 game corpus / FTS 数据库。 |
| `data/reference_builds.json` | engine-verified reference calibration 摘要。不能当 build 模板复制。 |
| `data/compatibility/pob.json` | PoB compatibility metadata。 |
| `data/mature_build_learning/seed_cases.json` | Phase 3N seed mature cases，已经 sanitizer/copy-safety 设计约束。 |
| `data/raw/` | corpus 构建输入缓存，包含 RePoE/wiki 原始派生数据。 |

## 10. `docs/` 文件职责

| 路径 | 作用 |
| --- | --- |
| `docs/PROJECT_SPEC.md` | 当前目标、完成状态、当前工作、审查/验证政策。Codex 接续第一优先级。 |
| `docs/PROJECT_ARCHITECTURE.md` | 本文件；项目结构、文件地图、工作流和接续指南。 |
| `docs/architecture/` | 局部技术设计文档。后续关键功能仍应先写这里。 |
| `docs/architecture/real-effect-evaluation-protocol.md` | 真实效果验证协议。 |
| `docs/architecture/phase-03n3-llm-mature-extraction-real-effect.md` | 当前 Phase 3N.3 局部技术设计；source probe、manifest、LLM contract、creator/evaluator guard 已实现，候选导入和真实效果报告尚未实现。 |
| `docs/superpowers/specs/` | 已批准设计规格。部分内容是历史。 |
| `docs/superpowers/plans/` | 历史实施计划居多；不要仅因计划存在就认为方向仍 active。 |
| `docs/superpowers/plans/2026-06-27-phase-03n3-llm-mature-extraction-real-effect.md` | 当前 Phase 3N.3 实施计划；后续执行入口。 |
| `docs/evaluations/` | 计划用于真实效果验证报告；Phase 3N.3 首轮报告尚未创建。 |
| `docs/audits/` | 早期审计结果。 |
| `docs/research/` | 调研记录。 |
| `docs/research/poe-ninja-source-probe-2026-06-27.md` | Phase 3N.3 首轮 poe.ninja build-level source probe 报告；只保存 shape/状态/结论，不保存 raw 内容。 |
| `docs/build-optimizer-spec.md` | build optimizer 规格。 |

## 11. 当前 active / legacy 状态

Active source of truth：

1. `docs/PROJECT_SPEC.md`
2. `docs/PROJECT_ARCHITECTURE.md`
3. `docs/architecture/phase-03n3-llm-mature-extraction-real-effect.md`
4. `docs/superpowers/plans/2026-06-27-phase-03n3-llm-mature-extraction-real-effect.md`
5. 代码与测试

Legacy but useful：

- `docs/superpowers/plans/*`：多数是已完成的实施计划，用于追溯，不代表当前方向。
- `PLAN.md`：早期总体方案，仍有背景价值，但不覆盖 Phase 3N 后的新判断。
- Phase 3A–3M 局部文档：代表已实现切片的设计背景。

已废弃：

- 先前 Phase 3N.3 creator-safe retrieval 草稿。不要继续实现 `server/knowledge/mature_retrieval.py`。
- “3N.3 仍不依赖 LLM”的方向。当前产品设计要求 LLM 提前进入 mature build 技巧抽取与真实效果验证。

## 12. 核心工作流

### 用户请求生成 BD

```text
用户目标
  -> LLM 澄清/拆解
  -> freshness gate
  -> corpus/reference/live/mature evidence 检索
  -> LLM 形成 lifecycle route
  -> engine 验证可计算阶段
  -> route quality/evaluation
  -> 输出阶段化 BD + caveats + 转型门槛
  -> 用户反馈
  -> local memory / reflection / possible promoted technique
```

### 成熟 BD 学习

```text
热门样本发现
  -> source snapshot + provenance
  -> sanitizer/copyability guard
  -> LLM extraction: 机制、阈值、转型、风险、协同
  -> candidate technique with evidence
  -> creator/evaluator split
  -> real-effect evaluation
  -> gap reflection
  -> candidate update
  -> promoted durable memory only after verification
```

## 13. 验证策略

工程验证：

- 小改动：targeted tests。
- lifecycle/MCP 文档或轻量逻辑：`.\scripts\verify.ps1 quick`。
- 较广泛非 engine 回归：`.\scripts\verify.ps1 noncompute`。
- engine/PoB/optimizer/runtime：`.\scripts\verify.ps1 compute`。
- release/merge：`.\scripts\verify.ps1 full`。
- 文档-only：至少 `git diff --check`，必要时做文档链接/术语一致性检查。

产品真实效果验证：

- 单测不能证明 BD Creator 真会做强 BD。
- 任何影响推荐质量、成熟 BD 学习、LLM extraction、route synthesis 的阶段，都需要真实效果验证。
- 具体协议见 `docs/architecture/real-effect-evaluation-protocol.md`。

## 14. 后续开发注意事项

- 新功能先做 subagent 设计/规格预审。
- 关键功能先写局部技术文档，再写代码。
- 测试策略按风险分级：简单确定性逻辑可直接开发后跑 targeted tests；安全边界、evidence 边界、DB migration、LLM 输出合同、route synthesis、engine 数值和 bug 回归仍优先用严格 TDD 或先测后改。
- LLM extraction 要有明确 input/output contract、copy-safety prompt、schema validation 和 evaluator gap 记录。
- 不要把 vector DB / graph DB 当成第一反应；先证明真实样本和 LLM extraction 能产生有价值技巧，再决定索引形态。
- 不要把 deterministic candidate extraction 删除；它仍是安全 baseline 和边界测试资产。
