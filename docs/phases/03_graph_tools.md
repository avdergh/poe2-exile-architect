# Phase 3 - Graph Backend 与 Typed Graph Tools

## 阶段状态

已完成。Phase 1 Judge / modelability 基线和 Phase 2 physical graph cold-start 已阶段性完成；
当前阶段已基于 Phase 2 已有 snapshot / store 建立 read-only typed graph facade，暂不需要引入
更重的 graph backend。

Phase 3 的第一步不是重新发明一套图存储，而是把 Phase 2 已经能离线复现的 source-backed
facts 通过 typed、validated tools 暴露给外部 agent。

当前开发进度：read-only `GraphQueryService`、strict typed schema、NetworkX bounded passive
topology、通用 MCP `graph_tool_query`、Phase 3 deterministic benchmark 脚本和 focused tests
已落地，focused graph tests、deterministic benchmark 和 `quick` 验证均已通过；E2E report
已完成人工 review 并验收通过。Phase 3 当前可作为 Phase 4 Researcher memory 和 Phase 5
planner 的 typed physical graph access 前置能力。

## 目标

通过 typed、validated tools 把图知识暴露给外部 agent，而不是让 agent 写 raw graph query
strings。

本阶段的核心输出是：

- read-only graph query service；
- agent-facing typed tool schemas；
- provenance / status / confidence / caveat 完整的 graph query result；
- 固定 typed graph tool deterministic benchmark；
- 禁止 raw Cypher / Gremlin / SQL 进入 agent 接口。

## 双轨记忆定位

项目长期记忆不是纯文本记忆，而是双轨结构：

- symbolic / relational graph memory（符号/关系图记忆）：保存可验证的节点、边、官方 ID、
  requirements、resource profile、support/socket legality、passive topology、装备词缀模板和
  其他 source-backed JSON facts；
- semantic vector memory（语义向量记忆）：保存 copy-safe 的 clean fragments、机制理解、
  研究摘要和可复用原则，用于语义检索和上下文组装。

Phase 3 只负责第一条轨道的 typed access layer：让外部 agent 通过受控工具查询符号图事实。
Phase 3 不负责建立向量数据库，也不把成熟 BD 研究文本直接写入长期记忆；这些属于 Phase 4
Researcher memory 的范围。

## 依赖

- Phase 1 Judge / modelability vocabulary。
- Phase 2 physical graph：
  - `server/knowledge/physical_graph.py`；
  - JSON durable snapshot；
  - SQLite snapshot index / store；
  - resolver、source explain、official ID mapping；
  - requirements / resource / support / socket / passive / caveat computed fact contracts。
- Freshness / version evidence。

## 当前基础

Phase 2 已经提供以下可复用能力：

- `GraphSnapshot`、`GraphNode`、`GraphEdge`、`GraphAlias`、`GraphSource`、
  `GraphIdMapping` 等内部合同；
- `save_snapshot()` / `load_snapshot()`；
- `register_snapshot()` / `list_registered_snapshots()` / `load_latest_snapshot()`；
- `resolve_node()` / `resolve_candidates()` / `resolve_id_mapping()`；
- `explain_sources()`；
- `can_roll_mod`；
- `requirements_for_component`；
- `resource_profile_for_component`；
- `support_skill_candidate`；
- `socket_support_legality`；
- `passive_neighbors`；
- `passive_allocation_options`；
- `passive_allocation_overlay`；
- `caveat_component_set`。

## 初期工作项

- 明确 Phase 3 backend policy（已完成）：
  - 默认使用 Phase 2 的 JSON snapshot + SQLite snapshot index / store；
  - 只有当 typed query ergonomics、bounded topology query 性能或 deterministic benchmark
    证明必要时，才评估 embedded graph database、Neo4j 或其他后端；
  - 本阶段不引入 semantic vector store；向量检索和 embedding memory 等到 Phase 4 的
    clean fragment / semantic memory 合同稳定后再选型；
  - backend 替换不能改变 agent-facing typed schema。
- 定义内部 `GraphQueryService`（已完成）：
  - 加载 latest snapshot；
  - 统一 resolve / ambiguity / missing-node 行为；
  - 统一返回 provenance、status、confidence、source refs、snapshot id 和 caveats；
  - 拒绝 raw query string；
  - 对需要上下文的 query family 执行 context validation，缺上下文时返回 structured
    `missing_context`，不能猜；
  - 默认 read-only，不提供外部 upsert 或 weight adjustment。
- 定义 typed input schemas（已完成）：
  - `GraphToolInput`；
  - `GraphToolContext`；
  - context policy 至少区分 `none`、`version_only`、`item_context`、`socket_context`、
    `passive_context`、`build_state_context`；
  - resolve / source explain 可无 build context；
  - item/mod、socket/support、passive allocation/path 等状态化查询必须声明并校验所需
    context。
- 定义 typed result schemas（已完成）：
  - `GraphResolveResult`；
  - `GraphQueryResult`；
  - `GraphEvidencePath`；
  - `GraphToolError`；
  - `GraphToolDeterministicBenchmarkResult`。
- 设计首批 typed tools，优先覆盖 Phase 2 已有 deterministic facts（已完成）：
  - resolve graph component；
  - explain graph evidence；
  - requirements for component；
  - resource profile for component；
  - support skill candidate；
  - socket support legality；
  - can roll mod；
  - passive neighbors；
  - bounded passive topology path；
  - bounded passive subgraph in radius；
  - passive allocation options / overlay；
  - caveat component set；
  - build planner ID resolve；
  - patch / source stale edge inspection。
- 对 passive topology 工具的边界（已完成）：
  - `passive_neighbors` 只适合解释相邻 source-backed topology；
  - agent 不应通过反复调用 `passive_neighbors` 自己做无界 BFS / DFS；
  - `find_passive_topology_path(start, end, context?, constraints?)` 返回静态拓扑路径和 caveats，
    不声称完整 build-state allocation legality；
  - `get_passive_subgraph_in_radius(node, hop_limit, filters?)` 必须有 hop / node count 上限，并
    返回压缩 JSON；
  - 固定 topology benchmark case 必须在有限工具调用与有限 payload 内完成；初始建议上限：
    单个 query 不超过 1 次 macro tool call、`hop_limit <= 6`、`node_limit <= 200`、payload
    不超过 64KB；
  - 如涉及 class start、weapon set、allocated passives 或 point budget，必须通过
    `GraphToolContext` 显式传入，否则返回 `missing_context` / context caveat。
- 对 verified JSON fragments / template-shaped facts 的处理边界（已完成）：
  - Phase 3 可以返回 source-backed subgraph、requirements payload、resource profile、
    support/socket legality、item-mod availability 等结构化事实；
  - 这些返回值可以服务 Phase 5 planner，但不能在 Phase 3 直接变成成熟 BD 模板库；
  - 可复用 planner fragment 的持久化、copy-safety、语义归纳和 promotion 规则属于
    Phase 4/5。
- 建立 typed graph tool deterministic benchmark（已完成，人工 review 已通过）：
  - 复用 Phase 2 fixed E2E 样例；
  - 增加 typed tool query 样例；
  - 覆盖 known / unknown / ambiguous / unsupported / stale / missing_context；
  - 验证 known physical facts 100% 带 provenance / source refs；
  - 验证 missing / ambiguous / unsupported 100% 结构化返回；
  - 验证 hallucinated compatibility rate 为 0；
  - 验证 passive topology macro tools 能避免 agent 进行无界邻接遍历，并遵守 max tool
    calls / max hops / max nodes / max payload bytes 上限。
- 在 schema 和测试稳定后，才考虑把首批 read-only graph tools 注册到 `server/main.py`（已完成，已注册 `graph_tool_query`）。

## 明确延期

- Semantic graph ingestion 属于 Phase 4。
- Semantic vector memory / embedding retrieval 属于 Phase 4 或之后。
- Graph retrieval vs text / vector retrieval 的质量对比属于 Phase 4 或之后；Phase 3 只验证 typed
  physical graph tools 的确定性、可解释性和防幻觉能力。
- `query_synergy`、`find_archetype_subgraph` 这类语义 / archetype 查询属于 Phase 4 之后。
- `adjust_weight`、reward weight update 属于 Phase 8。
- 外部 agent 不获得 `upsert_node`、`upsert_edge` 或 raw graph write tool。
- Graph tools 不替代 PoB / Judge 的最终 build-state legality；它们只提供 source-backed
  static facts 和可解释查询路径。

## 验收

- Agent 不需要、也不能写 Cypher / Gremlin / SQL。
- Tool inputs 是 typed schema，不接受 raw graph query string。
- Tool outputs 至少包含：
  - snapshot id；
  - resolved component key；
  - status；
  - confidence；
  - provenance / source refs；
  - caveats；
  - missing / ambiguous / unsupported 的结构化错误。
- 对不存在的 endpoint、unsupported official ID 或 ambiguous alias，必须返回 expected rejection
  或 structured ambiguity，不能静默创建事实。
- Typed graph tool deterministic benchmark 必须通过：
  - fixed physical fact queries 返回 expected status；
  - known facts 带 provenance / source refs；
  - missing / ambiguous / unsupported / missing_context 结构化返回；
  - physical compatibility、ID mapping、passive topology 等事实的 hallucination rate 为 0；
  - agent 不需要通过无界重复调用 `passive_neighbors` 自己遍历图；
  - topology macro tools 遵守固定的 tool-call、hop、node 和 payload 上限。
- E2E report 需要用户 review；未完成人工验收前，Phase 3 不能标记完成。

## 验证

实现时先跑 focused graph tests，例如：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_physical_graph*.py -q
```

graph tool tests 和 deterministic benchmark 通过后运行：

```powershell
.\scripts\verify.ps1 quick
```
