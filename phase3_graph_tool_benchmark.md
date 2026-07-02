# Phase 3 Typed Graph Tool Benchmark

## 摘要

- benchmark id：phase3_typed_graph_tools_v1
- snapshot id：physical-graph-61792486905f62f9b6ba2c95
- 样例总数：17
- benchmark 状态：可人工验收
- expected_status_match_rate：1.00
- provenance_completeness_rate：1.00
- structured_return_rate：1.00
- hallucinated_compatibility_count：0

## 样例列表

| # | tool | expected | actual | status match | caveats |
| --- | --- | --- | --- | --- | --- |
| 1 | resolve_graph_component | ambiguous | ambiguous | true | ambiguous_alias |
| 2 | requirements_for_component | known | known | true |  |
| 3 | resource_profile_for_component | known | known | true |  |
| 4 | resource_profile_for_component | unknown | unknown | true |  |
| 5 | requirements_for_component | stale | stale | true | version_context_mismatch |
| 6 | socket_support_legality | missing_context | missing_context | true |  |
| 7 | socket_support_legality | known | known | true |  |
| 8 | can_roll_mod | missing_context | missing_context | true |  |
| 9 | can_roll_mod | known | known | true |  |
| 10 | support_skill_candidate | known | known | true |  |
| 11 | support_skill_candidate | unsupported | unsupported | true |  |
| 12 | support_skill_candidate | known | known | true |  |
| 13 | support_skill_candidate | error | error | true | missing support contract requirements: skill:BenchmarkMissingContractSupport |
| 14 | find_passive_topology_path | known | known | true | topology_only_path |
| 15 | get_passive_subgraph_in_radius | known | known | true | topology_only_subgraph |
| 16 | build_planner_id_resolve | unsupported | unsupported | true | official_passive_string_id_not_vendored |
| 17 | resolve_graph_component | error | error | true | Tool input validation failed: raw graph query fields are not permitted (sql). Only use typed schema. |

## 人工评分

- 已预填人工评分：pass x 17
