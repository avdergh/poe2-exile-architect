# Phase 3 - Graph Backend 与 Typed Graph Tools

## 阶段状态

未开始。

## 目标

通过 typed、validated tools 把图知识暴露给外部 agent，而不是让 agent 写 raw graph query
strings。

## 依赖

- Phase 2 physical graph。

## 工作项

- 定义 `GraphMemoryStore`：
  - `upsert_node`；
  - `upsert_edge`；
  - `resolve_node`；
  - `neighbors`；
  - `paths`；
  - `query_subgraph`；
  - `mark_stale`；
  - `adjust_weight`。
- 评估 backend choices：
  - embedded graph database；
  - Neo4j；
  - SQLite-backed graph fallback。
- 基于以下标准选择：
  - testability；
  - Windows support；
  - dependency risk；
  - version/status/weight support；
  - typed-tool ergonomics。
- 暴露 typed tools：
  - `query_synergy(component, context)`；
  - `find_conflicts(component, context)`；
  - `find_required_prerequisites(component)`；
  - `find_passive_neighbors(node)`；
  - `find_archetype_subgraph(skill, goal)`；
  - `resolve_build_planner_id(component)`；
  - `find_patch_stale_edges(context)`；
  - `explain_evidence_path(edge_or_node)`。
- 建立 graph retrieval benchmarks。

## 验收

- Agent 不需要写 Cypher/Gremlin/SQL。
- 在 broad semantic ingestion 之前，graph retrieval 至少在一个 benchmark 维度上优于 text retrieval。
- Tool outputs 包含 provenance 和 status。

## 验证

运行 graph tool tests 和 retrieval benchmark，然后运行：

```powershell
.\scripts\verify.ps1 quick
```
