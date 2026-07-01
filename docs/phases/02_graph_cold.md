# Phase 2 - Physical Graph 冷启动与官方 ID 映射

## 阶段状态

已完成：开工前文档复核、Source Inventory 与 Physical Graph Contract 的 TDD 合同切片、
fixed E2E acceptance artifact、用户人工评分和 `quick` 验证均已完成。当前实现覆盖 immutable
source/node/edge/snapshot、alias、ID mapping、capability、
requirement/resource fact、passive choice/allocation option、computed fact result 合同，
deterministic snapshot id、raw static source inventory builder，`skill_gems.min.json` 的首个
nodes/edges ingestion slice，base item / mod ingestion slice，`skills.min.json` 的 skill type /
support contract / resource fact ingestion slice，以及 `can_roll_mod`、`requirements_for_component`、
`resource_profile_for_component`、`support_skill_candidate`、`socket_support_legality` computed fact
原型，以及 JSON snapshot
save/load、SQLite snapshot index/store、基础 resolve/source explain 能力、passive official ID /
choice / allocation option ingestion、`unique -> base item` query、最小 weapon-set allocation
overlay query、component-set 级别 caveat context 原型，以及 19 个固定 E2E 样例 acceptance
report。

整体进度粗估：100%（待提交/合并）。已完成基础合同、source inventory、六类 raw ingestion 起步、十组关键
computed fact 原型，以及 JSON durable snapshot、SQLite snapshot index/store、candidate-aware
基础 resolve、build-facing skill/support resolver payload skeleton、mini E2E report 骨架与第一版
固定样例 bundle；当前固定 E2E artifact 已达到 19 个样例，并已按人工 review `pass` 更新
acceptance report。剩余更完整的 official ID 覆盖、真实 tree/unique 全量摄入、weapon set overlay
深化、caveat registry 扩展、完整 official inventory/passive tables acquisition 属于 Phase 3+
增量或后续 source acquisition 工作，不阻塞 Phase 2 cold-start 出关。

Phase 2 最终完成已经经过 deterministic tests、E2E 样例验收和人工评分通过；当前状态等待提交与
合并。

## 当前进度复核

- Phase 1 已完成 Judge / modelability 基线，后续 graph 需要继承其 evidence、confidence、
  reward-strength、physical-invalid 和 modelability caveat 词汇。
- 当前已有静态数据底座：
  - `data/raw/base_items.min.json`、`skill_gems.min.json`、`skills.min.json`、
    `ascendancies.min.json`、`mods.min.json`；
  - `pob/PathOfBuilding-PoE2/src/Data/Uniques/` 中的 unique 可读文本；
  - `data/corpus.sqlite` schema v4，已经提供 items、gems、mods、uniques、ascendancies 和
    mechanics 的 read-only 查询；
  - `server/freshness/*` 已提供 game patch、league、passive tree、PoB engine/data、
    corpus 和 meta snapshot 的 freshness / version evidence；
  - Headless PoB bridge 能读取 passive tree version、build tree version、passive budget 和
    selected-skill weapon compatibility。
- 当前已新增 `server/knowledge/physical_graph.py` 作为 Phase 2 physical graph 合同入口；
  `tests/test_physical_graph_contracts.py` 覆盖 source claim、namespaced stable key、orphan edge、
  edge enum、alias / official ID mapping、capability、requirement/resource facts、passive
  choice/allocation option、computed fact result、source inventory builder 和 deterministic
  snapshot、skill gem raw ingestion、base item/mod/skills ingestion，以及 `can_roll_mod`、
  `requirements_for_component`、`resource_profile_for_component`、`support_skill_candidate` 的
  regression slice。
- 当前 Phase 2 cold-start 已出关；后续更完整的官方 ID 获取、graph backend typed tools、
  semantic graph 和 `.build` exporter 分别按 Phase 3/4/6 承接。

## 目标

从权威静态来源建立可重复构建的 physical graph fact layer，而不是依赖 LLM 发明或推断基础
事实。

Phase 2 的交付物是：

- source-backed physical nodes；
- source-backed physical edges；
- versioned provenance；
- 最小 durable physical graph snapshot / store；
- alias / resolver contract；
- 官方 `.build` export 所需的 ID 映射基础；
- dynamic/computed physical fact contracts；
- 不暴露 raw graph query 的内部查询/校验能力。

Phase 2 不追求完整 agent-facing graph retrieval。Typed graph tools、graph retrieval benchmark
和 backend 产品化属于 Phase 3；semantic graph 与 mature BD 知识属于 Phase 4；官方 `.build`
artifact 生成属于 Phase 6。

## 依赖

- Phase 1 judge/modelability vocabulary。
- 现有 corpus 和 raw static data。
- PoB pinned data 和 Headless PoB readback。
- GGG official passive tree / passive ID 来源。
- Freshness/version evidence。

## 范围边界

- 没有 static source，就不能创建 physical graph node。
- 没有已存在 endpoint nodes，就不能创建 physical graph edge。
- Display name 不能作为唯一主键；必须有 stable key、source id 和 aliases。
- Tag overlap 不能伪装成真实兼容性。例如 support 与 skill 共享 tag 只能作为低置信候选或
  `shares_tag_with` 类事实；recommended-support source 只能生成 `recommended_for`，不能生成
  `compatible_with`；只有显式兼容规则或 PoB/GGG 可追溯 evidence 支持时，才能写成
  `compatible_with`。
- 大规模 `item can_roll affix` 不应无脑物化成笛卡尔积。优先保存 mod domain、spawn tags、
  base tags 和可验证 resolver；必要的 `can_roll` view 由后续 typed query 或 planner 派生。
- 不在 Phase 2 暴露 MCP graph tools，不让 agent 写 Cypher/Gremlin/SQL。
- 不写入 semantic edges、mature-build techniques、reward weights 或 copyable mature BD 材料。
- 不实现 `.build` exporter，只保存 resolver 能力和 unsupported-field caveats。
- `connected_to` 只表达静态天赋树拓扑，不等同于最终可分配路径。Weapon set passives、
  alternate class starts、ascendancy unlock constraints 和 attribute-choice nodes 必须通过
  allocation overlay / resolver 表达。
- `shares_tag_with` 只表达候选相关性，不能表达技能、辅助和武器的合法组合。
- 组合导致的 modelability caveat 不能无条件写到单个 skill 节点上；必须保留触发 caveat 的
  component set / context。
- Phase 2 要为 Phase 5 提供静态 legality input 的 source-backed facts 或 computed facts，但
  最终 build-state 合法性仍以 PoB/Judge 为准。Phase 5 不应绕过 Phase 2 resolver 直接拼 raw
  static data。

## 工作项

### 1. Source Inventory 与 Provenance（进行中）

当前实现：

- `SourceClaim` / `GraphSource` 合同已建立，允许 per-source claims 保留 `unknown` 和
  `not_applicable`，并校验 source id、kind、source file、duplicate claim 和 confidence。
- `SourceInventorySpec` / `build_source_inventory()` 已建立，默认扫描当前 raw static source：
  - `repoe:ascendancies`：37；
  - `repoe:base_items`：5241；
  - `repoe:mods`：16845；
  - `repoe:skill_gems`：1189；
  - `repoe:skills`：8340；
  - `ggg:developer_docs:inventories`：2（官方开发文档 BuildInventorySlot 示例 fixture）。
- 已有 focused test 覆盖 claim 查询、缺失 claim 返回 `None`、top-level JSON source count、
  missing source 默认失败和显式 `include_missing` 的 missing provenance。
- 尚未实现 freshness evidence 汇入、官方 ID source acquisition、source schema drift report 或
  source count 变更的人审 gate。

- 为每个可用静态来源建立 source inventory：
  - source kind；
  - source file/path；
  - source URL 或 upstream；
  - expected count；
  - schema/version；
  - game patch；
  - passive tree version；
  - PoB version/commit；
  - freshness status；
  - confidence。
- 明确每类节点的 canonical source 优先级，例如 base item / gem / mod 以 RePoE raw 为主，
  unique 可读文本以 pinned PoB data 为主，passive tree 以 GGG official tree 或 pinned PoB
  tree data 的可追溯 ID 为主。
- 明确 official ID source acquisition：
  - upstream URL 或本地 vendored path；
  - cache path；
  - fixture path；
  - offline test fallback；
  - network failure policy；
  - source schema drift detection。
- 不要求每个 source 都声明所有版本维度。Source inventory 使用 per-source `claims`：
  - 已知维度写入 claim；
  - 不适用维度写为 `not_applicable`；
  - 不可证明维度写为 `unknown`，并降低 confidence 或追加 caveat；
  - 禁止为了满足字段而伪造 game patch、passive tree version 或 PoB commit。
- source inventory 必须可测试，不能只写在文档里。

### 2. Physical Graph Contract（进行中）

当前实现：

- `GraphNode`、`GraphEdge`、`GraphSnapshot` 和 `build_snapshot()` 已建立最小 immutable
  contract，覆盖 namespaced stable key、source refs、edge endpoint resolve、edge evidence refs、
  allowed edge type enum 和 deterministic snapshot id。
- `GraphAlias`、`GraphIdMapping`、`GraphCapability`、`RequirementFact`、`ResourceFact`、
  `PassiveChoice`、`AllocationOption`、`ComputedFactRequest` 和 `ComputedFactResult` 已建立
  最小合同，snapshot 会校验它们引用的 source/node/choice。
- `save_snapshot()` / `load_snapshot()`、`resolve_node()` 和 `explain_sources()` 已建立 JSON
  durable snapshot、基础 node resolve 和 source explain 原型。
- `register_snapshot()` / `list_registered_snapshots()` / `load_latest_snapshot()` 已建立 SQLite
  snapshot index/store 原型，用于登记 JSON snapshot、列出历史和加载 latest。
- 当前 allowed edge type enum 已对齐本阶段 Base Edges Ingestion 初始清单。
- 尚未实现 snapshot tombstone/report、resolver ranking/ambiguity report、allocation overlay
  evaluator 或 computed fact evaluator。

- 定义内部合同：
  - `GraphNode`；
  - `GraphEdge`；
  - `GraphAlias`；
  - `GraphSource`；
  - `GraphIdMapping`；
  - `GraphSnapshot`；
  - `GraphCapability`；
  - `RequirementFact` / `ResourceFact`；
  - `PassiveChoice` / `AllocationOption`；
  - `ComputedFactRequest` / `ComputedFactResult`。
- 每个 node 至少包含：
  - stable key；
  - node type；
  - display name；
  - aliases；
  - source refs；
  - status；
  - confidence；
  - game patch / passive tree / PoB version context；
  - official IDs（如果支持）。
- 每个 edge 至少包含：
  - stable key；
  - source node；
  - target node；
  - edge type；
  - evidence refs；
  - status；
  - confidence；
  - modelability / evidence level（必要时继承 Phase 1 词汇）。
- edge ingestion 必须先 resolve endpoints；不存在的 endpoint 必须失败，而不是创建 dangling
  edge。
- stable key 必须带 namespace，不能用 display name：
  - `gem:<metadata_id>`；
  - `skill:<skill_id>`；
  - `support:<metadata_id>`；
  - `item_base:<metadata_id>`；
  - `mod:<metadata_id>`；
  - `unique:pob:<normalized_name>`；
  - `passive:ggg:<id>` 或 `passive:pob:<tree_version>:<id>`；
  - `class:<normalized_name>`；
  - `ascendancy:<class>:<normalized_name>`；
  - `passive_choice:<passive_id>:<option_id>`；
  - `tag:<kind>:<normalized_name>`；
  - `caveat:<code>`。
- 最小 durable store / snapshot 是 Phase 2 范围内工作：
  - 可以是 SQLite-backed physical graph tables、generated JSON snapshot，或等价的可测试持久层；
  - 必须支持 ingestion、resolve、computed fact、explain source 和 deterministic rebuild；
  - 不要求支持 Phase 3 的 arbitrary traversal、weight adjustment、agent-facing typed tools 或
    graph retrieval benchmark。
- 当前实现优先落在 generated JSON snapshot：
  - 已支持 `build_snapshot()` -> `save_snapshot()` -> `load_snapshot()` round-trip；
  - 已支持 `register_snapshot()` -> `list_registered_snapshots()` -> `load_latest_snapshot()`
    的 SQLite snapshot index；
  - 已支持 alias/id/stable-key 的基础 resolve；
  - 已支持 node -> source explain；
  - 尚未实现 removed/tombstoned node report、snapshot GC、stale source invalidation workflow 或
    richer index metadata。
- Graph snapshot lifecycle 必须定义：
  - snapshot id；
  - source generation ids；
  - created_at；
  - rebuild inputs；
  - removed/deprecated/tombstoned node handling；
  - repeated ingestion idempotency；
  - stale source invalidation。

### 3. Base Nodes Ingestion（进行中）

当前实现：

- `ingest_skill_gems()` 已从 `data/raw/skill_gems.min.json` 建立首个 source-backed nodes
  ingestion path：
  - skill gem；
  - support gem；
  - active skill；
  - gem tag；
  - display alias；
  - RePoE gem metadata ID mapping。
- 真实 raw data smoke：`skill_gems.min.json` 当前生成 2576 个 nodes、1189 个 aliases、1189 个
  metadata id mappings。
- `ingest_base_items()` / `ingest_mods()` 已建立 base item、item class、item tag、mod 和
  RePoE metadata/id mapping 的 source-backed ingestion path。
- 真实 raw data smoke：`base_items.min.json` + `mods.min.json` 合并后当前生成 22473 个 nodes、
  5241 个 aliases、22086 个 id mappings、18526 个 requirement facts。
- `ingest_skills()` 已建立 `skills.min.json` 的 source-backed ingestion path：
  - active skill alias；
  - skill type；
  - weapon type requirement；
  - per-level / base resource fact；
  - support contract requirement fact；
  - RePoE skill id mapping。
- 真实 raw data smoke：`skill_gems.min.json` + `skills.min.json` 当前可稳定合并，生成 9783 个 nodes、
  48126 条 edges、14396 条 resource facts。
- `ingest_passive_tree()` 已建立 `pob/PathOfBuilding-PoE2/src/TreeData/0_5/tree.json` 的最小
  source-backed ingestion path：
  - class；
  - ascendancy；
  - passive / notable / keystone；
  - `starts_at`；
  - `belongs_to`；
  - `connected_to`（当前仅保留可 resolve 的 node-to-node 连接）；
  - passive type；
  - passive stat text；
  - connection caveat requirement fact；
  - unlock constraint requirement fact；
  - PoB passive node id / passive skill id / class id / ascendancy id 映射；
  - attribute-choice passive 的 `PassiveChoice` / `AllocationOption`。
- 真实 raw data smoke：`0_5` passive tree 当前生成 11008 个 nodes、17266 条 edges、4945 个 aliases、
  4968 个 id mappings、200 个 unlock constraint requirement facts、5 个 connection caveat facts。
- `ingest_uniques()` 已建立首个 pinned PoB unique text ingestion path：
  - unique node；
  - `has_base`；
  - `has_mod_text`；
  - unique name alias / mapping。
- `ingest_inventory_slots()` 已建立官方 Build Planner docs 示例 fixture ingestion：
  - inventory slot node；
  - `ggg:Inventories` ID mapping；
  - `build_inventory_slot` requirement fact（例如 `build_slot`、`weapon_set`）。
- 尚未实现完整 official passive string IDs、完整 `Inventories` 表 acquisition、完整 caveat code
  registry 或全量 unique parser；但 passive node 已补上 `pob:passive_node_id` /
  `pob:passive_skill_node_id`。

优先建立以下 physical node 类型：

- skill gem；
- active skill；
- support gem；
- unique；
- base item；
- affix / mod；
- passive node；
- notable；
- keystone；
- ascendancy；
- class；
- weapon type；
- inventory slot；
- passive choice / allocation option；
- mechanics tag / gem tag（只保存静态 tag，不写语义推断）；
- modelability caveat code。

实现顺序建议先走可由现有 raw/corpus 稳定覆盖的 items、gems、mods、uniques、ascendancies
和 classes，再处理 passive tree source 与 official passive IDs。passive graph 不应只从
Headless PoB 搜索结果反推，除非能记录对应 static source 和版本。

### 4. Base Edges Ingestion（进行中）

当前实现：

- `ingest_skill_gems()` 已从明确 raw fields 建立首个 source-backed edges ingestion path：
  - gem/support `has_tag`；
  - gem/support `grants_skill`；
  - active skill `granted_by` gem/support；
  - support `recommended_for` gem。
- 真实 raw data smoke：`skill_gems.min.json` 当前生成 13057 条 edges，其中 4971 条
  `recommended_for`，0 条 `compatible_with`。
- raw `recommended_supports` 中发现少量 active gem 引用；当前 parser 会跳过非 support 推荐引用，
  避免 dangling edge 和 candidate-as-compatible。后续应追加 caveat/report，而不是静默长期忽略。
- `ingest_base_items()` / `ingest_mods()` 已从明确 raw fields 建立 base item `has_tag`、
  `has_item_class` 和 mod `applies_to_tag` edges。
- 真实 raw data smoke：`base_items.min.json` + `mods.min.json` 合并后当前生成 30636 条 edges，
  0 条 `can_roll` durable edge。
- `ingest_skills()` 已从明确 raw fields 建立 active skill `has_type`、`requires_weapon_type` 的
  source-backed edges；support skill 的 `allowed_types` / `excluded_types` / `supports_gems_only`
  当前先保存为 support contract requirement fact，供 computed helper 判断，不提前物化为
  `compatible_with`。
- `ingest_passive_tree()` 已从明确 tree fields 建立：
  - class `starts_at`；
  - ascendancy `belongs_to` class；
  - passive `belongs_to` ascendancy；
  - passive `connected_to` passive；
  - passive `has_type`；
  - passive `has_stat_text`。
- 当前对真实 `0_5` tree JSON 中 14 条指向 `nodes` 表外 id 的连接采取保守策略：跳过未知 target，
  不生成 dangling `connected_to` edge。后续需要进一步判断这些 id 是中间连接点还是导出残留，
  再决定是否补中间节点还原。
- 当前已把这类跳过行为显式写成 `connection_caveat` requirement fact；后续 query / E2E 可以直接
  返回 `unresolved_connection_ids`，而不是静默少邻居。
- 当前进一步确认：
  - 这 14 条 unresolved connection 全部出现在 6 个 `classesStart` 共享起点节点上；
  - `classesStart` 中包含 `Shadow`、`Marauder`、`Duelist`、`Templar` 等当前 `classes` 列表中
    不再作为主 class 公开的旧名称；
  - PoB runtime 会维护 `classStartNodeNameMap`，说明这些共享起点与 legacy class-name /
    shared-start 兼容逻辑有关，不是普通随机坏边。
- 暂定后续方向：
  - Phase 2 可考虑把 legacy class start name 当 alias / mapping，而不是正式 `class` node；
  - `connected_to` 还原若需要覆盖这些 14 条边，可能要引入 shared-start compatibility 规则，
    而不只是单纯补 `nodes` 表解析。
- 尚未实现 skill item-class requirements、socket/support limit、unique/passive edges 或每种 edge
  type 的完整 metadata contract。

Phase 2 必须使用封闭 edge type enum。初始允许的 source-backed physical edges：

- gem `grants_skill`；
- skill/gem `has_tag`；
- skill `has_type`；
- skill `requires_weapon_type` / `requires_item_class`（当 raw source 或 PoB/GGG source 可证明）；
- support `has_tag`；
- support `has_type`；
- support `recommended_for`；
- support `shares_tag_with`（如果需要保留候选关系，必须标记为低置信候选，不等同
  `compatible_with`）；
- support `compatible_with`（只有明确 source 或 PoB/GGG evidence 时创建）；
- active skill `granted_by` gem；
- gem/support `has_requirement`；
- skill/gem/support `has_resource_cost`；
- skill/gem/support `has_reservation`；
- socket group `has_socket_constraint`；
- support `has_support_limit_rule`；
- affix/mod `applies_to_tag`；
- base item `has_tag`；
- base item `has_item_class`；
- unique `has_base`；
- unique `has_mod_text`；
- ascendancy `belongs_to` class；
- class `starts_at` passive start；
- passive `connected_to` passive；
- passive `has_stat_text`；
- passive `has_type`；
- passive `has_unlock_constraint`；
- passive `has_allocation_option`；
- passive choice `belongs_to_passive`。

`.build` exportability 不作为泛化 `component -> build_planner_exportable` edge 存储。它应是
node capability / resolver status，例如 `exportable`、`unsupported`、`ambiguous` 或
`requires_phase6_mapping`。

如果 source 只能证明“推荐”“共享 tag”“候选”，edge type 必须表达候选性质，不能把候选边
提升为硬兼容事实。

每种 edge type 必须定义：

- allowed source kinds；
- default confidence；
- whether it is hard legality evidence；
- whether it is candidate-only；
- whether it can be consumed by Phase 5 planner before PoB verification；
- required tests。

### 5. Weapon Set 与 Allocation Overlay（进行中）

当前实现：

- `passive_allocation_overlay()` 已建立最小 overlay query：
  - 从 `weapon_set_overlay` requirement fact 读取 `allocation_states`；
  - 可返回文档对齐的 `documented_weapon_set_indices`（当前为 0..2）；
  - 返回 `weapon_set_point_conversion`；
  - 对 state-specific reachability 返回 `dual_weapon_state_limited_caveat`；
  - 缺少 overlay fact 时明确返回 `unknown` / `normal` 默认态，而不是假装可规划。
- pinned PoB passive export 脚本已确认存在 `WeaponPointsGranted` / “Passive Skill Points become
  Weapon Set Skill Points” 信号，可继续扩展到真实 tree fixture。
- 尚未实现 per-set budget、node allocated-state overlay、alternate class start / jewel start
  叠加、以及真实 build-state reachability 评估。

Passive graph ingestion 必须把静态拓扑和可分配状态分开：

- `connected_to` 只保存 tree source 中的物理邻接；
- class start、ascendancy start、alternate class start 和 jewel-granted start 是 resolver /
  allocation root 事实；
- weapon set passives 需要单独的 allocation overlay contract，至少表达：
  - `normal`；
  - `weapon_set_1`；
  - `weapon_set_2`；
  - `both_sets`；
  - per-set budget；
  - converted weapon-set point sources；
  - node allocation state；
  - state-specific reachability caveat。
- Phase 2 不需要实现最终 passive path planner，但必须让 Phase 5 能区分“树上相邻”和“在某个
  weapon set state 下可合法分配”。
- Attribute-choice nodes、multi-choice passives 和其他 passive options 必须使用
  `PassiveChoice` / `AllocationOption` 合同表达：
  - option id；
  - parent passive id；
  - display name；
  - stat text；
  - source refs；
  - allocation-state interaction；
  - unsupported/ambiguous caveat。
  如果某类选择暂时无法建成 graph node，必须明确作为 overlay value 输出，不能生成 dangling
  `has_allocation_option` edge。
- E2E fixtures 必须覆盖至少一个 weapon set passive usage 样例，证明无状态 `connected_to`
  不会被误当成最终可分配证据。

### 6. Resolver 与官方 ID 映射（进行中）

当前实现：

- `resolve_node()` 已支持 stable key、external id、alias 和 display name 的基础 deterministic
  resolve。
- `resolve_candidates()` 已支持 `resolved` / `ambiguous` / `missing` 的 candidate-aware 返回形状；
  `alias_collision_report()` 已支持 normalized alias collision report。
- `resolve_id_mapping()` 已支持按 system + external id 返回 `resolved` / `unsupported` /
  `ambiguous` / `missing`，可显式承接 unsupported official ID 样例。
- `build_component_resolver_payload()` 已支持 skill gem / support gem 的 build-facing resolver
  payload skeleton，当前返回 metadata id、display name、source refs、统一的
  `export_status`/`caveats` 形状，以及 `unsupported` / `missing` reason；当前已对 meta gem 显式
  返回 `meta_gem_not_supported`。
- `build_component_resolver_export()` 已支持多节点 bulk export-readiness report，可汇总
  `resolved` / `unsupported` / `missing` 计数。
- `build_resolver_preflight_summary()` 已支持把 bulk export report 与 alias collision report 汇总
  成 preflight summary，可直接服务后续 E2E/report skeleton。
- `build_fixed_resolver_e2e_report()` 已支持 resolver/export readiness 的 fixed-sample report
  skeleton，可继续扩展到 skill/base/mod/passive query families。
- `build_can_roll_mod_e2e_sample()` 已支持 computed-fact query family 的 fixed-sample report entry，
  作为 `can_roll_mod` E2E skeleton 的起点。
- `build_phase2_mini_e2e_report()` 已支持把 resolver 与 `can_roll_mod` query families 聚成
  mini E2E report，作为后续 10-20 固定样例报告的第一版代码落点。
- 当前 mini E2E report 已包含 `resolver_preflight` 汇总，可把 export readiness 与 alias
  collision 风险一起带到样例报告中。
- 当前 `can_roll_mod` sample 已支持 positive/negative pair，可覆盖 `item_level_too_low` 这类
  excluded reason。
- 当前 mini E2E report 已扩展到六类 query family：
  - resolver/export readiness；
  - `can_roll_mod`；
  - `requirements_for_component`；
  - `resource_profile_for_component`；
  - `support_skill_candidate`；
  - `passive_neighbors`。
- 当前已新增：
  - `build_unique_base_item_e2e_sample()`；
  - `build_id_mapping_e2e_sample()`；
  - `build_edge_provenance_e2e_sample()`；
  - `build_phase2_fixed_sample_bundle()`；
  - `passive_allocation_options` / `passive_allocation_overlay` / `caveat_component_set`
    对应的 fixed-sample 基础查询能力。
- `build_phase2_fixed_acceptance_report()` 已建立第一版人工验收摘要聚合器：
  - 汇总 `family_counts`；
  - 汇总 `status_counts`；
  - 汇总 per-family caveats；
  - 区分 `ready_for_human_review`（无 `fail`）与 `ready_for_phase2_exit`（全部样例都已 `pass`）；
  - 作为后续 10-20 固定样例验收包的 report 顶层骨架。
- `build_phase2_acceptance_artifact()` 已建立 bundle -> acceptance report 的统一 artifact 入口，
  便于后续直接导出人工验收包。
- `scripts/run_phase2_acceptance_artifact.py` 已建立首个离线 acceptance artifact 产物脚本，当前会
  生成 `phase2_acceptance_artifact.json` 与 `phase2_acceptance_report.md` 供人工审阅。
- 当前第一版 fixed-sample bundle 最少覆盖：
  - gem -> granted skill；
  - skill -> weapon requirement；
  - support candidate；
  - socket/support duplicate 与 support-limit hard constraint；
  - base item + item level -> mod availability；
  - gem requirement fact；
  - skill resource fact；
  - unique -> base item；
  - supported / unsupported official id mapping；
  - source-backed official docs inventory slot mapping；
  - unique name mapping；
  - passive allocation option；
  - passive weapon-set overlay caveat；
  - caveat -> component set；
  - ambiguous alias；
  - missing node；
  - edge provenance；
  - skill/support build-facing resolver payload。
- 当前 acceptance report 聚合已覆盖上述新增 family，不再只识别早期 resolver / can-roll 样例。
- 当前 fixed-sample bundle 已可直接流入 `build_phase2_fixed_acceptance_report()`，当前 artifact
  生成 19 个样例；脚本默认不预填人工评分，显式传入 `--default-review-grade pass` 后已生成
  人工验收通过版 report：`ready_for_human_review=True`、`ready_for_phase2_exit=True`。
- 当前 fixed-sample `edge_provenance` 覆盖真实 passive `connected_to` provenance，不再用
  `granted_by` 反向技能边代替 passive topology 证明。
- 当前 `requirements_for_component` sample 已覆盖 `unknown` 场景，不会在缺失 fact 时伪造需求。
- 当前 `resource_profile_for_component` 已支持：
  - exact stage；
  - base fallback（仅限没有分级资源曲线的组件）；
  - 缺少 stage 返回 `unknown`；
  - 缺少 source-backed node 直接失败。
- 当前 `support_skill_candidate` 已支持：
  - 根据 `support_gem.allowed_types` / `excluded_types` 的后缀表达式做硬约束判断；
  - `supports_gems_only` 硬约束；
  - `recommended_for` 与 `hard_compatible` 区分；
  - `shared_tags` 只作为解释字段，不提升为兼容性事实。
- 当前 `socket_support_legality` 已支持：
  - 先复用 `support_skill_candidate` 的 source-backed support-vs-skill 判断；
  - 读取 `socket_context` requirement fact 或调用参数中的 socket context；
  - 输出 duplicate support、support limit exceeded、support family 与 expected rejection；
  - 不写死随 patch 变化的全局 socket 数值，真实规则必须来自后续 source-backed ingestion。
- 当前 `passive_neighbors` 已支持：
  - 返回 source-backed `connected_to` 邻居；
  - 返回 `unresolved_connection_ids`；
  - 存在 unresolved connection 时标记 `ambiguous`，并附带
    `unresolved_passive_connections` caveat。
- 当前 `passive_allocation_options` 已支持：
  - 返回 parent passive 的 `choice_keys`；
  - 返回 option 的 `display_name` / `stat_text` / `allocation_states`；
  - 缺少 choice 时返回 `unknown`。
- 当前 `passive_allocation_overlay` 已支持：
  - 返回 `allocation_states`；
  - 返回 `weapon_set_point_conversion`；
  - 返回 `dual_weapon_state_limited_caveat`。
- 当前 `caveat_component_set` 已支持：
  - 返回 `component_keys`；
  - 返回 `trigger_condition`；
  - 返回 `modelability_effect` / `reward_eligibility_effect`。
- 当前 resolve contract 会显式报 `ambiguous` 或 `missing`，不会自动猜测节点。
- `explain_edge_sources()` 已支持对单条 physical edge（例如 `passive connected_to`）返回 evidence
  source，可直接服务 connected_to provenance 验收样例。
- 现有 id mappings 仅覆盖已落地 ingestion slice：
  - `repoe:gem_metadata`；
  - `repoe:base_item_metadata`；
  - `repoe:mod_id`；
  - `repoe:skill_id`。
- 真实 raw data smoke：当前 `skill_gems` snapshot 已发现 18 组 alias collisions，可作为后续
  resolver ranking / unsupported caveat / human review 的输入。
- 尚未实现 official `.build` / GGG / PoB resolver、ranking、stale/unsupported caveat、
  candidate scoring 或 human-facing ambiguity explanation。

建立 deterministic resolver，至少覆盖：

- display name / alias 到 graph node；
- PoB display/internal identifiers；
- GGG `PassiveSkills`；
- GGG `BaseItemTypes`；
- active skill gem identifiers；
- support gem identifiers；
- active skill identifiers；
- meta gem / unsupported skill export caveats；
- GGG inventory IDs；
- unique Words/name references；
- Build Planner export identifiers；
- unsupported 或 ambiguous ID caveats。

Resolver 输出必须区分：

- resolved；
- ambiguous；
- unsupported；
- stale；
- missing。

模糊匹配只能作为候选返回，不能自动创建 node 或 edge。

### 7. Computed Physical Facts（进行中）

当前实现：

- `can_roll_mod(snapshot, base_item_key, mod_key, item_level)` 已建立首个 computed fact helper：
  - 输入必须引用已存在 base item node 和 mod node；
  - 使用 source-backed base item tags、mod `applies_to_tag` 和 mod `required_level`；
  - 返回 `ComputedFactResult`，包含 `can_roll`、`required_level`、`matching_tags` 和
    `excluded_reason`；
  - 不生成 durable `can_roll` edge，避免 item × mod × item level 笛卡尔积。
- `requirements_for_component(snapshot, component_key, level_or_stage)` 已建立最小 helper：
  - 当前从已有 `RequirementFact` 读取 requirements；
  - 有 source-backed fact 时返回 `known`；
  - 缺少 fact 时返回 `unknown`，不自动推断。
- `resource_profile_for_component(snapshot, component_key, level_or_stage)` 已建立最小 helper：
  - 当前从已有 `ResourceFact` 读取 costs / reservations；
  - exact stage 命中时返回 `known`；
  - 只有 `base` profile 的组件允许 fallback 到 `base`；
  - 存在分级 profile 但缺少目标 stage 时返回 `unknown`；
  - 缺少 source-backed node 时直接失败。
- `support_skill_candidate(snapshot, support_key, skill_key)` 已建立 legality/candidate helper：
  - 当前读取 support contract requirement fact；
  - 按 PoB 同语义的后缀表达式处理 `allowed_types` / `excluded_types`；
  - `supports_gems_only` 会切断 craft/item granted active skill；
  - 输出 `recommended` / `hard_compatible` / `unsupported`；
  - `shared_tags` 只作为 explain 字段。
- `build_requirements_for_component_e2e_sample()` 已建立该 family 的 fixed-sample report entry。
- `build_resource_profile_for_component_e2e_sample()` / `build_support_skill_candidate_e2e_sample()`
  / `build_socket_support_legality_e2e_sample()` / `build_passive_neighbors_e2e_sample()` 已建立对应
  family 的 fixed-sample report entry。
- 真实 raw data smoke 已覆盖 positive 和 negative case，且 `skill_gems` + `skills` 合并可稳定运行。
- 尚未实现 domain、prefix/suffix、generation weight、tier/range、mod group exclusion 或 ambiguous
  case 的完整判定；当前原型只能作为 Phase 2 computed contract 骨架，不能替代 crafting solver。

以下事实不应默认全部物化为 graph edges，而应通过 deterministic computed fact contract 暴露：

- `requirements_for_component(component, level_or_stage)`：
  - 输出 attribute requirements、level requirements、weapon/item-class requirements、source refs；
  - 缺少可证明 source 时返回 `unknown`，不能推断。
- `resource_profile_for_component(component, level_or_stage)`：
  - 输出 mana/life cost、Spirit reservation、persistent reservation、cooldown/stored-use 等可从
    static source 读取的资源事实；
  - 只表达静态需求，不声称实战 sustain 或 DPS。
- `socket_support_legality(skill, support, socket_context)`：
  - 输出 duplicate support、support limit、support family/color/tag/source constraints；
  - 当前已完成 duplicate support、support limit 与 support family 原型（进行中）；
  - support color/tag/source constraints 仍待真实 source-backed fixture；
  - Phase 1/Judge 仍负责 build-state hard failure。
- `can_roll_mod(base_item, item_level, domain, prefix_suffix)`：
  - 输入 base item / tags、item level、domain、prefix/suffix；
  - 输出可 roll mod candidates、required level、tier/range、groups、source refs；
  - 必须说明 excluded reason，例如 item level too low、tag mismatch、domain mismatch；
  - 输出是 computed fact，不是 durable semantic edge。
- `skill_weapon_legality(skill, equipped_weapon_types)`：
  - Phase 2 可返回 raw source requirements / candidate hard constraints；
  - Phase 1/PoB readback 的 `disableReason` 仍是最终 build-state legality evidence。
- `support_skill_candidate(skill, support)`：
  - 输出 recommended / shares-tag / hard-compatible / unsupported / unknown；
  - 不允许把 shares-tag 结果提升为 hard-compatible。
- `passive_reachability_overlay(class, ascendancy, allocation_state)`：
  - 只返回 topology + root + state caveats；
  - 不替代 Phase 5 的 passive path planner。

Computed facts 必须可 explain source，并且在输入缺少 source-backed node 时失败。

### 8. Modelability Caveat Context（进行中）

当前实现：

- `caveat_component_set()` 已建立最小 query：
  - 从 `component_set` requirement fact 返回 `component_keys`；
  - 返回 `trigger_condition`；
  - 返回 `modelability_effect` / `reward_eligibility_effect`；
  - 作为 component-set 级别 caveat context 的首个 deterministic 合同。
- 当前 caveat context 仍依赖手工/fixture 注入 requirement fact，尚未建立完整 caveat node registry
  builder，也尚未把 Phase 1 vocabulary 全量导入。

Phase 2 可以建立 caveat code 节点或等价 registry，但只保存 deterministic modelability 事实，
不保存成熟 BD 语义知识。

最低要求：

- caveat code 来自 Phase 1 judge/modelability vocabulary 或明确的 source-data caveat；
- caveat 可以关联到 component set，而不是只关联单个 skill：
  - meta trigger gem + triggered spell；
  - minion setup + command/trigger skill；
  - isolated `FullDPS` rollup；
  - dual weapon state limited evidence；
  - missing/ambiguous official ID。
- caveat edge / registry entry 必须包含 trigger condition、source refs、modelability effect、
  reward eligibility effect 和 confidence。
- Phase 4 才能把 Researcher 输出的语义 edge proposal 提升为长期 semantic graph knowledge。

Fixture evidence 只能作为 regression evidence 或 PoB/GGG source parser 的验证材料；不能单独
创建 durable physical edge。Durable physical facts 必须来自 static source 或 PoB/GGG 可追溯
readback。

### 9. Validation 与 Regression（已完成，后续增量继续追加）

当前实现：

- `tests/test_physical_graph_contracts.py` 已覆盖：
  - source / snapshot / alias / id mapping / capability / fact 基础合同；
  - `skill_gems`、`base_items`、`mods`、`skills`、`passive_tree`、`uniques` ingestion；
  - JSON snapshot round-trip；
  - SQLite snapshot index/store；
  - resolve / collision report / export preflight；
  - `can_roll_mod`、`requirements_for_component`、`resource_profile_for_component`、
    `support_skill_candidate`、`socket_support_legality`、`passive_allocation_options`、
    `passive_allocation_overlay`、`caveat_component_set`、`unique_base_item`；
  - mini E2E report family 聚合与 fixed-sample bundle。
- focused test 当前可稳定通过：
  - `.\.tools\uv\uv.exe run pytest tests/test_physical_graph_contracts.py -q`
- acceptance artifact 脚本当前可离线运行：
  - `.\.tools\uv\uv.exe run python scripts/run_phase2_acceptance_artifact.py --default-review-grade pass`
- `.\scripts\verify.ps1 quick` 已通过。
- 当前 acceptance artifact/report：
  - `phase2_acceptance_artifact.json`；
  - `phase2_acceptance_report.md`；
  - 19 个固定样例均已预填人工评分 `pass`；
  - `edge_provenance` 样例使用 passive `connected_to`；
  - `can_roll_mod` 样例输出 `base_domain`、`mod_domain`、`generation_type` 并保持 known。
- 后续增量：
  - 更真实的 passive / weapon-set overlay regression fixture；
  - 真实 passive tree 中 14 条 unresolved connection target 的结构归因与还原策略；
  - official ID source/cache 离线 fixture；
  - 完整 official `Inventories` 表 acquisition；
  - 更完整的 acceptance report 展示 polish。

- Node count 和 edge count 必须与 source expectations 对齐，并允许按 source version 更新。
- Alias collision 必须被检测并可解释。
- Orphan edge 必须失败。
- 重复 ingestion 必须幂等。
- version/freshness mismatch 必须进入 provenance 或 caveat。
- `.build` 相关 IDs 必须能为 supported nodes resolve；unsupported fields 必须输出 caveat。
- 不存在的 skill、notable、unique、base item、mod reference 必须校验失败。
- graph fact explain 必须能回溯到 source file/source row。
- Edge enum 之外的 edge type 必须被拒绝。
- computed fact 必须覆盖 positive、negative 和 ambiguous case。
- weapon set allocation overlay 必须有 regression fixture。
- official ID source/cache fixture 必须能离线运行。
- requirements/resource facts 必须覆盖 attribute、level、Spirit/reservation、socket/support
  hard constraint 的样例。
- skill/support `.build` resolver 必须覆盖 supported、unsupported meta gem 和 ambiguous case。

## 验收

- Static node 和 edge counts 符合 source data expectations。
- 抽样 graph facts 能追溯到 static source files。
- 不存在的 skill、notable、unique、base item 或 mod references 会校验失败。
- Resolver 能为 supported `.build` 相关节点输出官方 ID 或明确 unsupported/ambiguous caveat。
- 不依赖 LLM 也能回答基础 physical graph questions，例如：
  - 某个 gem grant 哪些 active skills；
  - 某个 skill/gem 有哪些 static tags；
  - 某个 attack skill 的 source-backed weapon/item-class requirements；
  - 某个 support 为什么只是 recommended、候选或真实 compatible；
  - 某个 gem/support 的 attribute、level、Spirit/reservation 或 socket/support constraint；
  - 某个 unique 对应哪个 base item；
  - 某个 mod 在给定 base + item level 下为什么可 roll 或不可 roll；
  - 某个 passive/notable 的 official ID、类型和邻接节点；
  - 某个 passive 在 normal / weapon set state 下的 allocation caveat；
  - 某个 caveat 是由哪个 component set 触发，而不是误绑到单个 skill；
  - 某个 node/edge 的 source、version、status 和 confidence。
- Phase 2 E2E report 至少包含 10-20 个固定样例 query，覆盖：
  - gem -> active skill；
  - skill -> weapon hard constraint；
  - support candidate vs hard compatibility；
  - gem/support requirement/resource fact；
  - socket/support hard constraint；
  - base item + item level -> mod availability；
  - unique -> base item；
  - passive -> official ID；
  - passive connected_to -> source provenance；
  - weapon set allocation overlay；
  - passive choice / allocation option；
  - ambiguous alias；
  - missing node；
  - unsupported official ID；
  - skill/support `.build` ID resolver；
  - modelability caveat component set。
- E2E 样例验收报告需由用户审阅并认可；未完成人工评分前，Phase 2 不能标记完成。

人工评分 rubric：

- `pass`：固定样例全部返回 source-backed answer、expected caveat 或 expected rejection；
- `minor_issue`：不影响 Phase 3/5/6 入口的说明性缺口，例如展示文案不清；
- `fail`：出现 hallucinated fact、dangling edge、candidate-as-compatible、missing required
  provenance、copyable mature material、raw query exposure、unsupported ID 被当作 resolved、
  或关键样例无法离线复现。

Phase 2 进入完成状态至少需要：

- focused tests 通过；
- `.\scripts\verify.ps1 quick` 通过；
- E2E report 中无 `fail`；
- 人工 review 接受所有 `minor_issue` 的延期或修复决定。

## 验证

实现时先跑 focused graph tests，例如：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_physical_graph*.py -q
```

knowledge/MCP/lifecycle/doc 相关回归运行：

```powershell
.\scripts\verify.ps1 quick
```

如果只修改文档，至少运行：

```powershell
git diff --check
```
