# Phase 2 E2E 样例人工验收报告

## 摘要

- 样例总数：19
- Phase 2 出关状态：可出关
- ready_for_human_review：true
- ready_for_phase2_exit：true

## 覆盖矩阵

| 验收场景 | 状态 | family |
| --- | --- | --- |
| gem -> active skill | covered | gem_grants_skill |
| skill weapon hard constraint | covered | skill_weapon_requirement |
| support candidate vs hard compatibility | covered | support_skill_candidate |
| gem/support requirement fact | covered | requirements_for_component |
| gem/support resource fact | covered | resource_profile_for_component |
| socket/support hard constraint | covered | socket_support_legality |
| base item + item level -> mod availability | covered | can_roll_mod |
| unique -> base item | covered | unique_base_item |
| passive -> official ID | covered | id_mapping_supported |
| passive connected_to source provenance | covered | edge_provenance |
| weapon set allocation overlay | covered | passive_allocation_overlay |
| passive choice / allocation option | covered | passive_allocation_options |
| ambiguous alias | covered | resolver_ambiguous_alias |
| missing node | covered | resolver_missing_node |
| unsupported official ID | covered | id_mapping_unsupported |
| skill/support .build ID resolver | covered | build_resolver_skill_support |
| modelability caveat component set | covered | caveat_component_set |

## 样例列表

| # | family | status | caveat |
| --- | --- | --- | --- |
| 1 | gem_grants_skill | known |  |
| 2 | skill_weapon_requirement | known |  |
| 3 | support_skill_candidate | known |  |
| 4 | socket_support_legality | unsupported |  |
| 5 | can_roll_mod | known |  |
| 6 | requirements_for_component | known |  |
| 7 | resource_profile_for_component | known |  |
| 8 | unique_base_item | known |  |
| 9 | passive_allocation_options | known |  |
| 10 | passive_allocation_overlay | ambiguous | dual_weapon_state_limited_caveat |
| 11 | caveat_component_set | known |  |
| 12 | resolver_ambiguous_alias | ambiguous | ambiguous_alias |
| 13 | resolver_missing_node | missing |  |
| 14 | build_resolver_skill_support | resolved |  |
| 15 | id_mapping_supported | resolved |  |
| 16 | id_mapping_unsupported | unsupported | official_passive_string_id_not_vendored |
| 17 | inventory_slot_mapping | resolved |  |
| 18 | unique_name_mapping | resolved |  |
| 19 | edge_provenance | known |  |

## 人工评分

- 已预填人工评分：pass x 19
