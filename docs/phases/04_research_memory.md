# Phase 4 - Researcher 语义记忆

持续研究积累维护在：

- `docs/research/BD_KNOWLEDGE.md`：成熟 BD 中提取的可复用知识与技巧；
- `docs/research/EXTRACTION_METHOD.md`：每批样本反向总结的深度挖掘方法，后续用于调整本阶段的
  schema、prompt、工具和验收标准。

这两份文档是滚动研究记录，不替代本阶段的正式实现合同。运行态（`/poe-bd-research`）禁止修改
仓库文档（见下方产品化入口），样本知识与方法学的回填由两条通道承担：`poe-bd-research-loop`
的 review/fix 通道把每案修正沉淀到外部 orchestrator 的 `research-notes/`；需要进仓库的通用
知识/方法则在开发态手动回填本文档。`research-notes/` 与这两份文档是不同产物，不再互为替身。
继续遵守单样本 observation、组内 pattern 和跨来源通用规律的证据分层。

下一版深度 memory MVP 采用两层持久化方向：一次研究先按知识单元保存一组聚焦、安全的
`DeepResearchRecord`，再提炼 fragment/semantic edge/build pattern 作为召回索引。同一案例通过
`research_group_id` 聚合，完整性由记录组共同保证；单条记录不能膨胀成整份案例报告。现有 fragment
schema 不能反向限制 Researcher 分析深度；新维度即使尚未结构化，也应先进入聚焦记录，后续再决定
是否升级为 record kind、typed payload 或索引字段。详细设计见
`docs/research/MEMORY_SYSTEM_DESIGN.md`。

当前实现进度：

- `deep_research_records` SQLite 存储和 strict `DeepResearchRecord` 合同：已完成；
- `propose_deep_research_records` MCP 候选校验工具：已完成；队列研究只由 `accept` 入库；
- `query_research_memory(detail_level=summary|record)` 两级召回：已完成；
- `BuildFamily`（升华 + 核心主/副技能）归类、kind-specific `knowledge_key`、跨 source canonical
  knowledge upsert 和逐来源 evidence：已完成；support、装备、防御和资源方案保留为 Family 内知识；
- 历史 `DeepResearchRecord` 高置信回填：可识别记录归入 Family，同知识选择信息最完整的 canonical，
  其他记录以 `deprecated/superseded_by_id` 保留审计；无法可靠识别的旧记录不强行合并；
- `/poe-bd-research` skill 深度提取合同、lease-bound worker brief 和提交期 review contract：已完成；
- 深挖方法、脱敏合格案例和浅层反例保留在 skill；worker brief 只携带当前案例导航和研究目标，精确
  schema/枚举在写入前由 `review-contract` 渐进披露：已完成；
- Researcher 顺序为“先独立分析当前案例，再查 memory 对照/查重，最后写入”，避免旧经验锚定新
  案例发现：已完成；
- fallback worker 可提交组件名称、角色和 resolver 查询词，由 accept gate 解析并回填稳定 ID：已完成；
- safe review acceptance 对深度记录的 resolver/schema/copy-safety/版本验收，以及“整案至少一条
  具体组件机制记录”的最低深度门槛：已完成；
- 研究队列与 MCP 查询统一使用用户数据目录中的正式 mature-learning SQLite；队列创建时注入应用
  当前 patch/tree 和 PoB 版本枚举，accept 时把缺失/`unknown` 归一为当前值并覆盖 worker 自填值：
  已完成；
- accept/status 按 typed reason 区分 schema、resolver、图源覆盖和提取深度问题：已完成；其中
  `unresolved_jewel_sockets` 覆盖“已分配珠宝槽无珠宝物品且 review 未声明珠宝状态”，
  `tree_data_missing` 不阻塞只提示：已完成；
- `accept --validate-only` 复用正式 acceptance 逻辑，返回具体字段路径、提交值和 canonical 枚举，且
  不写 durable memory、不改变 lease；Agent 必须自行修复后再正式 accept：已完成；
- fragment/edge/pattern 继续作为短召回索引：已完成；
- 更多职业样本回放、字段扩展候选和真实生成质量对照：等待后续案例验证。

运行时信息按以下边界维护，压缩重复时不得删除其唯一事实源。命令、顺序与编辑约束的执行事实源是
`/poe-bd-research` skill 与 claim 返回的 `workerPrompt`/`review-contract`，本节只维护运行时语义
边界，不复述命令：

- MCP `ASSISTANT_GUIDE`：保留工具能力地图、选择条件、权威边界和安全边界；
- `/poe-bd-research` skill：保留完整研究流程、深挖方法、覆盖维度及正反例；
- `claim.workerPrompt`：只保留当前 lease 身份、证据读取顺序、质量目标和下一步；
- `review-contract`：在写 artifact 前提供精确 JSON 形状、canonical role/axis/pattern 枚举与模板；
- `init-review`：按当前 lease 原子创建 UTF-8、两空格缩进的 review 骨架，已有文件不覆盖；
- `accept --validate-only`：以正式门禁规则给出可修复错误，不做 alias 猜测或自动改写。
- canonical role 表达 BD 功能，通过兼容矩阵与 resolver 的物理 node type 对照；它不是 node type
  alias。生成/兑现、被动转换器和武器职责可以由不同合法实体类型承担，但 stable key 仍必须唯一解析。
- `readyForAccept` 表示安全子集可接收；`fullyResolvedForAccept` 与 `acceptanceMode=clean` 才表示无候选
  暂缓和组件解析缺口。`partial_with_deferred` 先修复当前证据可解决的 role/type/query 问题。
- `unresolvedDeepRecordMentionCount` 统计未解析提及次数，`unresolvedUniqueComponentCount` 统计去重
  组件；兼容字段 `unresolvedDeepRecordComponentCount` 继续表示 mention 次数。
- `createdDeepRecordCount`、`updatedDeepRecordCount` 与 `addedDeepRecordEvidenceCount` 分开报告；
  同一 Family 的同知识再次出现时优先追加证据，不重复制造近义正文。
- Family 身份 = 升华 + 主输出技能**集合**（研究者声明的 `primary_damage` 角色技能，可多个）。
  自动副技能（clear/boss/triggered-payload）、trigger-host（同一 payload 换 host 视为变体）、
   `familyCoreSkillKeys` 一律**不参与身份**，只作 Family 内元数据。技能名按 gem 等价规范化后比较
   （同一宝石授予的弹药/直击变体视为同一技能，见 `skill_equivalence.py`）。
   独特宝石变体（如 `UniqueBreachLightningBoltPlayer`）与普通版共享同一家族身份 token
   （同显示名归一到同一 `gem:` token），这是**有意语义**：同名技能的不同形态是一个 Family，
   其机制差异（cooldown/triggered）由记录层精确 component key 保留，绝不通过拆分身份表达；
   无显示名映射的独特变体（如部分 `UniqueSkillGem*`）保持独立 `key:` token，除非模型确认等价行。
   不得把"加等价行"当作修复——对已确定性归一的变体写行是零行为变化。
   `skill_package` / `mechanic_chain` 记录必须声明至少一个 `primary_damage` 组件；
  身份相同的新研究自动归入既有 Family（不新建 sibling 档案），超集主技能集合会扩展既有 Family
  并合并其记录。`skill_package` 用 `supportPackages` 保存技能到辅助的归属，同技能不同辅助包保持
  不同知识单元。无图节点的资源方式用 `resourceMechanisms` 形成轻量身份。
  `unkeyedDeepRecordCount > 0` 时只能报告 partial，不能报告 clean。
- 签名词缀（极端掷骰 "Rolls only the minimum or maximum Damage value"、最低抗性伤害、元素地面
  交互、implicit "Allocates <passive>"、"Grants Skill: Level N"、Surpassing 额外投射、充能保留
  概率词缀）驱动记录因果结论时，必须独立成记录或进入 mechanicAudit，不能只出现在 content 字符串。
- 跨设计轴罕见同现（如混沌伤害节点、荆棘与中毒机会并存）无法闭环时建 `open_question` 记录结构化
  疑点；`modelability_caveat` 只用于“机制存在但 PoB 未建模/未证实”的情况。`read` 输出的
  cross-axis advisory 只作提示，不参与验收 gate。
- Family 归并（2026-08 起）：`scripts/merge_build_families.py` 按集合包含规则全量重构存量档案
  （dry-run → validate → apply，迭代到收敛，apply 前整库备份，合并写 `family_merge_log`；
  回滚 = apply 前快照恢复，日志仅审计）。入库自动归入与合并共用 `_resolve_family_target` /
  `_merge_family_records`；merge 后必须 bump `BUILD_FAMILY_BACKFILL_VERSION` 触发
  `backfill_deep_research_knowledge` 重推 knowledge_key（记录迁移保留原 knowledge_key，
  由 backfill 统一重算 canonical）。**backfill 重推会用新身份公式重建档案，可能与既有档案
  产生同 canonical 重复（同一宝石的不同变体技能 key 不同但等价），因此完整顺序是
  merge → backfill → 再跑一次 merge 收敛**；收敛后用
  `scripts/reconcile_orphan_records.py` 处理孤儿记录（join 挂回 / new 建档 / 无身份降级为
  待复核，expand 不自动执行；可疑身份组用 `--skip-group` 跳过留人工确认）。任何 key
  变更必须先跑 backfill 迁移并覆盖测试，不得静默自动合并身份。
- 已知数据缺口（unique jewels）：语料 unique 表来自 `pob/PathOfBuilding-PoE2/src/Data/Uniques/*.lua`
  的非递归 glob 摄入，存在三个具体缺口：
  1. **PoE2 Time-Lost 系列缺失**——其 unique 条目位于 `Uniques/Special/Generated.lua`
     （Time-Lost Diamond 等），提取器未摄入且 item_type 会是 "Generated"，因此
     `get_unique` / `search_uniques` 拿不到 Time-Lost 文本；
  2. **Historic timeless jewels**（Heroic Tragedy、Undying Hate，base "Timeless Jewel"，PoE2
     条目）被 `relevant_uniques.uniqueJewels` 排除出候选——因为 pinned 引擎的
     "Passives in radius are Conquered" 词缀是空规则（`ModParser.lua` 中 `= { }`），评估无意义；
     该排除依赖引擎实现状态，若未来引擎实现 conquered 规则应移除该过滤；
  3. **Grand Spectrum 变体被 name 去重丢弃**（只保留 Ruby）。
  执行层约束：即使补齐数据，研究提取侧也无法重建可评估的 PoB item text——research packet 只
  保留解析后的词缀摘要（`research_packet._parse_item_text` 丢弃原始文本），Time-Lost Jewel 的
  完整文本只能人工维护。PoB 引擎对 Time-Lost Jewel 的 radius 计算支持完整（词缀
  "Small/Notable Passive Skills in Radius also grant X" 按半径内已分配天赋生效，已实测验证），
  Create 侧用 `evaluate_jewel_socket` 做位置化评估。数据修复需上游 PoB-PoE2 更新
  Uniques/jewel.lua 或人工维护（另开数据维护任务）。
- `source_specific_random` 随机实例知识只解释来源案例，默认不进入 Create 召回或 planner Pattern。
- supports 覆盖要求每个核心技能组有至少两个结构化辅助；passiveAscendancy 覆盖要求升华壳和具体
  `ascendancyResponsibilities`，不能由任意普通 notable/keystone 代替。
- `query_research_memory` 支持 `ascendancy_key` / `primary_skill_key` 精确 Family 身份、
  `build_family_keys` / `record_kinds` 定向读取，并在 `buildFamilies` 返回 `recordKindCounts`；自然语言
  目标只对精确 Family 内记录排序，不会把已有 Family 过滤掉。未使用精确身份参数时仍保留文本、
  组件和 Family 主/副技能兼容召回。

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

- `ResearcherOutput schema_version=4` 基础合同、strict proposal schema、typed `context_requirements`
  和 structured rejection envelope。
- 当前深度提取使用向后兼容的 `schema_version=5`，新增聚焦 `DeepResearchRecord`。
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

## 语义边回填与每案建边

存量语义边通过 `scripts/backfill_semantic_edges.py` 做确定性 T1 回填，只写以下可证明的
关系形状，且全部走 `propose_semantic_edges`（copy-safety / resolver / 冲突门禁）：

- transition_gate pattern → `requires_transition_gate`（target 优先级：transition_gate role >
  keystone_transformer > unique_enabler > weapon_base）；
- mechanic_chain record → `enables_mechanic`（generator→payoff、unique_enabler→primary_damage/payoff，
  每记录 ≤2）；
- failure_mode record → `creates_failure_risk_for`；
- modelability_caveat record → `has_modelability_caveat`（每记录 ≤3）。

脚本从当前注册物理图快照节点直接构建 resolver evidence；候选生成前先对 DB 做只读一致性
快照副本（运行中的 MCP server 可能并发维护 store），保证单次运行确定性；离线做逆边/短环
预检后分块（25）提交，`ON CONFLICT(edge_id) DO UPDATE` 幂等。单案例 cooccurrence pattern
不提升为边（无跨 Family 证据）。全部回填边为 low/medium 置信度 advisory，使用前需
PoB/Judge 复核。

后续每案研究强制建边：worker brief 强制检查要求每案至少提交 2 条 resolver-backed
semantic edge 写入 safe review 的 `semanticEdges`；acceptance gate（
`run_phase4_deep_review_acceptance.py`）在正式 accept 时通过持久化版
`propose_semantic_edges` 写入，报告 `acceptedSemanticEdgeCount` 并计入 queue case 状态。
无法推导时必须说明原因，不得为凑数发明关系。MCP 的 `propose_semantic_edges` 仍是
validate-only（acceptance 是唯一持久化写入方）。

## 安全边界

- 项目不新增内部 OpenAI / Claude / Gemini provider loop；研究推理由 Codex、Claude Code、
  Gemini 等外部成熟 agent 执行。
- raw mature-build material 只能出现在 quarantine-only transient packet 中，不能进入 durable
  report、state、memory、creator-visible context 或普通聊天输出。
- 禁止持久化或暴露 PoB code、raw XML、raw account/character details、完整 URL、长篇复制攻略文本，
  或把全部装备槽、整棵已分配天赋、全部技能组和完整配置共同保存成第三方整角色镜像。
- 允许完整保存可复用核心机制包，包括关键技能与辅助组合、局部核心天赋连接、暗金/装备与技能、
  天赋、资源系统的联动。不得按辅助数量或局部节点数量机械拒绝。
- 没有 static source，不能创建 physical graph node。
- 没有 resolver-backed physical endpoint，不能创建 semantic edge。
- mature BD semantic edges 和 build patterns 都是 advisory research context，不是 hard
  legality、PoB 数值证明或 reward weight。
- unresolved / ambiguous / source coverage gap endpoint 不能被自动选中；它们应进入 manual
  mapping、static source refresh 或 verification task。

## 产品化入口

研究运行态禁止使用 subagent、子代理或独立 agent lane。研究 MCP 工具只保证在触发 skill 的当前
主会话可用；当前 Agent 必须亲自完成 prompt 读取、深度提取、safe review 和 accept，并严格逐案串行。
Research 任务连接 `poe_knowledge_mcp` + `poe_research_mcp` 两个按域拆分的 server（工具面约 48 个），
不触发 Codex 数量上限；历史遗留的聚合入口 `poe2-build-mcp`（`server/main.py`）仍注册，仅保留供
测试与旧宿主配置兼容（见 AGENTS.md），产品运行入口是四个按域拆分的 server。
工具未直接显示时应先用宿主标准 tool discovery / tool search 按精确名称查找，再判断是否真的不可用。

安装 skill 后，在 Codex 或支持 skill 的宿主中使用：

```text
/poe-bd-research --limit 50
```

这是会话里的 skill invocation，不是要求用户在 Codex 输入框里执行 shell 命令；宿主 agent 应
通过工具运行内部脚本。

若无参数触发 `/poe-bd-research`，skill 应先询问运行数量和模式，而不是先联网 dry-run 或静默
启动完整 live crawl。若宿主支持交互式选择/确认 UI，优先给出“预检 5 个样本（推荐）/ 小批量
提取 20 个样本 / 大批量提取 50 个样本 / 恢复已有队列”这类可选项；否则退化为普通文字选项。
`--resume` 是独立恢复模式，不绑定到 50 个样本；恢复时必须同时提供原始 `queue` 返回的
`--output-dir <runDir>`。

**显式意图优先于预检菜单**：用户明确给出案例数量或分析意图（例如“抓 5 个案例来分析”）时，
直接按 `--limit N` 执行完整流程（真实入队、逐案研究、accept），不得推荐或执行 `--dry-run`
预检——预检不产生任何知识，只用于用户无参数且明确想先验证链路时。

等价的底层脚本入口与逐案流程（queue → claim → inspect/read/search → review-contract →
init-review → accept --validate-only → accept → status）以 `/poe-bd-research` skill 的
`逐案流程` 为唯一执行事实源，本文档不再复述命令；完整参数见
`scripts/research_mature_builds.py --help`。

默认非 dry-run `queue` 会创建 `.poe-bd-research/runs/<runId>` 并返回 `runDir`；同一轮的所有后续
命令都必须使用该目录，且 `--resume` 需要原 `runDir`。不同会话使用不同 run，可以并发执行。

默认行为：

- 从 poe.ninja 当前 softcore trade league 拉取样本；
- 等级默认 90-100；
- `--limit` 默认 50；
- 当前 Agent 一次只 claim 一个案例，并在完成该案例 accept 后再领取下一案；
- `claim` 原子返回 safe-only `workerPrompt` 和 `reviewFile`，当前 Agent 必须直接遵守该 prompt，
  不得转交给其他 agent，也不能只依赖本机 `SKILL.md` 路径或临时口头说明；
- `worker-brief` 只用于恢复已经 claimed 的任务；
- 支持 `--ascendancy`、`--league current|<league-url>`、`--level-min`、`--level-max`、
  `--class`（可选透传 poe.ninja URL class filter）、`--source-file`、`--source-batch-file`、
  `--expected-source-count`、`--resume`、`--dry-run`、`--output-dir`；
- `--class` 同时接受空格名称和 poe.ninja URL 中的 `+` 分隔形式，编码前统一归一；列表返回后还会
  按同一升华名本地复核，非目标升华不得占用 `limit`；
- poe.ninja 采集按角色级去重：每用户本地 intake ledger（`paths.user_data_dir()/research_intake.sqlite`，
  可用 `--intake-ledger` 覆盖）记录已入队角色（`character-hash:` 引用，明文角色名不落盘），
  `queue` 会跳过本 league 已研究角色并继续分页抓取列表，直到凑满 `limit` 个新案例或列表穷尽
  （单次最多 15 页）；queue 报告输出 `intakePagesFetched` / `intakeSkippedAlreadyResearched` /
  `intakeLedgerRecordedCount` / `intakeLedgerSummary`。正式 accept 后 ledger 记录晋升为 `accepted`，
  后续 queue 不再重复抓取同一角色；本地 source-file 输入不走 ledger；
- batch mode 仍必须一案一轮：一个 Researcher prompt 只包含一个完整 BD；
- 默认不复用上一案的 transient evidence，避免前一个样本污染后一个样本；
- `/poe-bd-research` 是产品运行态，不是开发任务。运行期间 agent 不得修改仓库源码、测试、
  文档、schema、安装脚本或 plugin manifest；collector / source / runtime 失败时只报告
  safe error 并停止。

`queue`、`claim`、`status`、`accept` 都只输出 safe metadata。完整 raw-rich material 只保留在
OS temp 的 lease-bound packet 中，不再通过终端输出。当前 Agent 使用 `inspect` 查看分区清单，
再通过有界、可分页的 `read` / `search` 读取 `skills`、`gear`、`passives`、`config`、`build`；
`prompt` 仅作为兼容 manifest。公开 `propose_*` 只验证候选，safe review + `accept` 是队列研究唯一
durable write 路径。

`init-review` 只负责可靠地创建当前 lease 绑定的空骨架，不生成研究内容，也不增加新的 durable writer。
运行态 Agent 只能用文件编辑工具或 `apply_patch` 编辑这个 `reviewFile`，不能用 PowerShell here-string、
内联 `ConvertTo-Json` 或 `Set-Content` 拼接整份 JSON，也不能借此修改源码或其他运行产物。

产品默认 durable memory 是 `paths.mature_learning_path()` 指向的用户数据数据库，与 MCP
`query_research_memory` 使用同一文件。仓库根的 `phase4_real_research_memory.sqlite` 仅是旧开发脚本
历史路径，不再是 `/poe-bd-research` 默认写入目标。

### 公开知识种子与本地增量

开源分发不依赖中央 Research API，也不直接发布维护者的 mutable 数据库。发布流程从维护者本地库
筛选 `creator_visible + train_context + (global_seed/local_user) + copy_safety_state=passed` 的有效知识，清空
quarantine、来源原材料、查询回执、拒绝提案和维护事件，再生成带 schema、release version 与
SHA-256 的只读 SQLite seed。发布前先运行 `scripts/audit_public_research_memory.py`，该审计只输出
计数、版本覆盖和安全 ID，不输出记录正文。

Git checkout 与 release bundle 都携带 `data/mature_build_learning/release.sqlite`。新用户第一次初始化
且本地数据库不存在时，从已验证 seed 安装；已有数据库绝不覆盖。`local_user` 仍是运行时作用域，
但维护者当前通过安全审计的内容也进入发布种子。Research 运行状态、Judge 快照与最终
artifact 始终只在用户数据目录。中央服务只用于未来明确 opt-in 的投稿、撤回或跨设备同步，不能
成为 Create/Research 的硬依赖。

## 提取目标

Phase 4.5 的 mature BD 设计观察包括：

- 升华 + 主技能：作为 shell suitability，不作为技能合法性；
- 主技能 + secondary skill：标明 clear、boss、generator、payoff、movement、trigger host 等
  role；
- 技能 + key passive / notable / keystone：必须 resolver-backed；
- 暗金 + 天赋点 / 技能：区分 enabling、optional / chase、budget substitute；
- support + active skill：单 pair 可以作为小粒度关系；若多个 supports 共同决定机制行为，允许将完整
  关键组合和技能归属保存在 `supportPackages` 中；
- skill / archetype + scaling axis、weapon/base/stat priority；
- Spirit / reservation package + build shell；
- defense layer package + content goal；
- mechanic chain：generator -> transformer -> payoff；
- transition gate、failure mode、variant relation、modelability caveat。

提取采用两段式：先形成 `BuildDesignObservation`，再把 resolver-backed、copy-safe、证据足够的
部分提升为 semantic edge / cooccurrence pattern / planner hint。单样本只能写
`case_observation`，不能声称 usually / commonly / 常见。跨样本 pattern 必须由样本数、
family count、source diversity 和 resolver-backed evidence 支撑。

Pattern 的 `component` 作用域表示在 Family 知识之上授予有条件的跨 Family 迁移资格，不是与
Family 归属互斥的低权重分类。它在 `origin_family_keys` 对应 Family 内按 Family 权重召回，在其他
Family 才进入较低权重公用通道。单案 Researcher 只有在候选解决可重复设计问题、具有明确因果链，
并提交适用条件、排除条件、迁移理由和验证任务时，才能将其标成 `component`；单案例不能声明
`global`。后端使用 pattern type、核心稳定组件/职责和适用轴生成确定性
transfer key：同一 Family 的重复来源只增强 Family 内证据，不授权跨 Family 晋升；第二个独立 Family
出现同一结构后才晋升为 `recurring_observation`。公用知识最高为 `likely_pattern`，
`common_within_archetype` / `strong_ranking_hint` 只保留给 Family/Archetype 内排序。

实际 skill 保留 `docs/research/EXTRACTION_METHOD.md` 的精简执行版，并带一个脱敏合格机制链示例和
一个浅层反例；worker prompt 不重复整套方法和 schema。没有 resolver 工具时，worker 仍应提交具体组件名称、职责和查询词；
accept gate 负责解析稳定 ID。`skill_package`、`mechanic_chain`、`rotation`、`gear_synergy`、
`passive_package`、资源/防御引擎等具体记录没有可解析组件时会被暂缓；整案只有泛泛属性共现、通用
警告或工具 caveat 时会被拒绝且不写入 durable memory。

`pob_version_or_commit` 保留旧字段名以兼容已有 schema，但新写入语义是应用维护的 PoB 版本枚举，
例如当前 `0.22.0`，不再默认保存 commit。新赛季/新认证 PoB 到来时更新
`data/compatibility/pob.json` 和发布 runtime；来源案例没有声明版本或 worker 提交 `unknown` 时按应用
当前值处理，只有显式提交不在兼容清单中的版本才拒绝。

## Create 精确 Family 召回合同

Family discovery 仍只返回适合比较的轻量摘要。`supportingRecordIds` 不是简单取 evidence 排名前几
条，而是优先覆盖 `mechanic_chain / rotation / resource_engine / failure_mode` 等不同机制职责，
避免高证据的装备记录把关键轮转或失败场景完全挤出候选摘要。

选中 Family 后，`query_research_memory` 的 `limit` 只表示首轮展开多少条记录。服务端不能再把
调用方请求暗中缩小为六条记录或六条关联上下文。精确 Family 响应还必须返回：

- `familyRecordCoverage`：当前精确版本下合格记录总数、已展开数量、各 record kind 数量和是否完整；
- `familyRecordIndex`：本轮未展开记录的安全索引，包含 ID、类型、标题、摘要和稳定组件 key；
- `familyPremiseCatalog`：`mechanic_chain / rotation / resource_engine / failure_mode` 中的条件与
  失败条件，每项使用稳定 `premiseId`；
- `premiseAuditVersion`：当前前提审计合同版本。

调用方可以先用 coverage/index 发现缺口，再按同一 Family、组件 key、record kind、record ID 或
失败文本继续定向查询；不设置总查询次数或深读条数上限。作为解决方案采用的深度记录必须通过
`detail_level="record"` 真正读过，摘要中只看到 ID 不算采用。

typed query receipt 的 `result_contract` 保存本轮 `familyRecordCoverage`、
`familyPremiseCatalog`、`premiseAuditVersion` 和实际 `deepReadRecordIds`。这样后续 Create 审计
依据的是查询当时的安全快照，不会因数据库后来新增、修订或失效记录而改变已经完成的运行。

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

### 研究上下文传输真实验收（2026-07-15）

使用独立验收目录从当前 poe.ninja 来源串行研究两条 100 级 Witch 案例。两案均通过
`claim -> inspect -> read/search -> safe review -> accept`，未通过 prompt 或终端输出 raw XML、
PoB code 或临时路径。

- Abyssal Lich 案：`skills=13`、`gear=15`、`passives=159`、`config=17`、`build=1`；按默认
  `limit=20` 分别读取 2、1、8、1、1 页，全部 `complete=true`，无遗漏或重复。最终接受 6 条
  深度记录、3 条 observation、3 条 pattern，五个覆盖维度全部 `covered`。
- Blood Mage 案：`skills=12`、`gear=15`、`passives=136`、`config=17`、`build=1`；分别读取
  2、1、7、1、1 页，全部 `complete=true`，无遗漏或重复。校准后接受 7 条深度记录、3 条
  observation、3 条 pattern，五个覆盖维度全部 `covered`，无 deferred 或未解析组件。
- 两案分页响应的最大字符数约为 11.3K，低于 12K 目标。导入标签 `Blasphemy` / `Spellslinger`
  未遮蔽实际多技能组；研究结果恢复了触发宿主、载荷、supports、装备职责、核心天赋、轮转和资源防御。
- Acceptance 报告计数与独立验收数据库实际行数逐项一致。公开 `propose_*` 返回
  `validationOnly=true` 且不返回 durable ID；只有 `accept` 写入 durable memory。

### 组件发现与图解析边界

- `search_graph_components` 用具体名称、预期节点类型做有界候选发现；后续可替换或补充向量召回。
- `resolve_graph_component` 只负责稳定 ID、名称、别名或已发现 stable key 的最终确认。
- `DeepResearchRecord` 可保存未唯一解析的 `component_mentions`，包括名称、角色、查询提示、预期类型和
  解析状态；解析失败不等于研究内容无效。
- `BuildPattern` 和 semantic edge 仍要求稳定端点。词法或向量相似度只能用于发现候选，不能自动写图。
- 声明类型下找不到组件时，acceptance 会做一次不限类型诊断。唯一同名组件若存在于其他节点类型，
  返回 `component_type_mismatch` 和建议角色；只有所有类型都找不到时才是 `source_coverage_gap`。
- 不限类型诊断优先完全同名候选，再考虑包含词匹配，避免 `Critical Strike` 被
  `Ballista Critical Strike` 等相关名称掩盖。功能 role 与该物理类型兼容时直接保留原功能角色，不要求
  Agent 把 `payoff` 机械改写成 `passive_anchor`。
- safe review 使用 UTF-8、两空格缩进的多行 JSON，保证 validate-only 后能对单个 role、query 或 key
  做有界修复；压缩单行不是安全失败，但不符合运行合同。

### 研究执行 checklist（2026-08-07 修订，防再犯）

以下条目已迁入 `workerPrompt` 的 Mandatory Checks（中文 13 项，运行时权威）与 review-contract
的 `mandatoryChecks`（英文枚举），两处一一对应；`/poe-bd-research` skill 不再保留 13 项全文，
只以引用指向 claim 返回的 `workerPrompt`（详见该 skill 的提交前自检段）。本段保留为阶段审查
记录；执行时以运行时合同为准，避免再次出现"两套清单从未对账"。

以下条目来自真实案例审查（Monk/Martial Artist Hollow Palm 案例的补齐与修正），每个 deep
case 研究都应执行：

1. **Memory 对照必须用 stable key**：查询前先 `search_graph_components` +
   `resolve_graph_component` 解析 packet 的 ascendancy 与 class，再用
   `ascendancy:monk:martial_artist` / `class:monk` 形式过滤 `query_research_memory`；
   显示名（Martial Artist / Monk）不会命中存储 key，会静默返回空。必须检查返回的
   `familyRecordCoverage` / `familyRecordIndex` / `familyPremiseCatalog` 并逐条对照既有
   同升华/同技能 Family 知识（生成/消费角色、充能链、Combo 独立性等），避免重复或方向错误。
2. **Config 条件三栏检查表**：把 packet 每个 `condition*`（EnemyChilled / EnemyBleeding /
   EnemyBlinded / EnemyIgnited / CritRecently / BeenHitRecently / usePowerCharges 等）列成
   "条件 → 来源组件 → 验证状态"；无来源的假设（例如无点火来源却启用 Ignited）必须写成
   modelability caveat，不得静默采纳。
3. **装备全覆盖盘点**：14/14 件装备逐一在 records 中出现（结构化组件 / content 文本 /
   显式 not_applicable 三选一）；写 review 前成表自查，避免装备信息零命中。
4. **禁止猜 key 路径**：所有组件先 `search_graph_components` 再 `resolve_graph_component`；
   支持宝石的 metadata 路径可能有 `Items/Gem` 与 `Items/Gems` 两种形式，猜错会被判
   component_type_mismatch 或 missing。
5. **silent / unavailable 不丢结论**：`lookup_mechanic` 返回 silent 或语料无文本的机制，直接以
   样本证据与引擎读回为准写入记录；不需要因 wiki silent 额外标注 caveat 或 verification task
   （wiki 佐证不是要求，论坛 BD 多数机制没有对应 wiki 页面）。
6. **非 core 技能支持入记录**：Gathering Storm / Herald of Ice / Tempest Bell 等非 Family-core
   技能组的支持集合至少写入记录内容或 secondary supportPackages，不能只做兼容性检查。
7. **因果方向自查**：每个 resource_engine / mechanic_chain 写前核对生成 vs 消费方向（Rend 是
   Power Charge 消费者而非生成器）；与既有同组件 Family 记录对照。
8. **未解析组件逐个 search**：任何 unresolved 计数出现时，先对该组件名执行一次
   `search_graph_components` 再定性为 source gap（Nascent Hope 案例：图中实际存在
   `unique:pob:nascent_hope`，未 search 导致误报 gap）。

### 存量修正通道

Research Memory 的 durable writer 只有 accept。修正既有记录两条路径：

- **同 case 补录（新 research run + accept）**：用与最初完全相同的 PoB 文本重新 queue
  （sampleId/sourceHashRef 相同 → researchGroupId 相同）；补录记录保持旧记录的
  `title / recordKind / researchGroupId / source_case_refs` 不变时，`_persist_deep_record`
  会命中 `_existing_deep_record_id` 并原地 UPDATE 覆盖（`updatedDeepRecordCount` 计数）；
  identity 变化（knowledge_key 改变）时同一 UPDATE 会清理旧 key 的孤儿 evidence，不产生
  双记录。familyCoreSkillKeys 修正会改变 Family secondary 集合 → Family key 变化，旧 key
  成为无记录空壳，属预期。
- **维护脚本**：`server/knowledge/research_maintenance.py` 提供
  `calibrate_research_contract_v1`（按 source_ref spec 重建记录 + 旧记录
  `deprecated + superseded_by_id` + force backfill，带 backup 与原子事务），以及
  `remove_exclusive_research_sources` / `cleanup_legacy_research_memory`；CLI 入口
  `scripts/calibrate_phase4_research_contract.py`。适合批量确定性修正（装备职责、support
  归属、availability 标记），不适合需要重新推理的方向性修正。

### 2026-08-07 修正记录（Tempest Flurry Hollow Palm 案例）

- 新 research run（同 source）重放 11 条记录，全部原地 UPDATE（updatedDeepRecordCount=11，
  createdDeepRecordCount=0），acceptanceMode=clean，unresolved 归零。
- 修正：Rend 从充能生成器改为消费者（payoff，ConsumesCharges→闪电 buff）；familyCoreSkillKeys
  移除 WyvernRendPlayer；Nascent Hope 解析为 `unique:pob:nascent_hope` 并结构化；7 件装备
  （Dread Curtain / Anarchy Spark / Demon Salvation / 生命瓶 / 2 魅力 / Golem Urge）补录进
  content；config 条件缺口（Ignited/Bleeding/Blinded）与 Innervate 补进 modelability caveat；
  Spirit 总预算补进暴击敲钟记录的 failureConditions；Overabundance I 的 key 修正为
  `support:Metadata/Items/Gems/SupportGemOverabundance`（复数 Gems）。
