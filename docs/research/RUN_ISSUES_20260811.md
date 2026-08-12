# /poe-bd-research 运行问题记录（2026-08-11）

> 本文档记录一次 `/poe-bd-research` 产品运行态执行中观察到的流程/工具问题，供后续改进参考。
> 本次运行：runId `20260811-222353-a455`，来源 local PoB code（Mercenary/Witchhunter 96 手雷）。

## 问题清单

### 1. workerPrompt 中文乱码（GBK/UTF-8 编码冲突）— 已规避

- **现象**：`claim` 返回的 `workerPrompt` 在 Windows PowerShell 5.1 终端显示为乱码（`������ִ�� PoE2 mature build Researcher...`），无法直接阅读。
- **影响**：研究指令内容不可读，只能依赖 Skill 本体与 review-contract 完成工作。
- **规避**：后续命令设置 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'` 后输出正常；但 `claim` 本身的 workerPrompt 已在首个调用中不可读。
- **建议**：CLI 显式控制 stdout 编码（如 `sys.stdout.reconfigure(encoding='utf-8')`），或文档注明 Windows 用户需 `chcp 65001`。

### 2. graph_tool_query 的 `component_kinds` 参数被拒 — 已纠正

- **现象**：首次调用 `search_graph_components` 传入 `{"query": "Witchhunter", "component_kinds": ["ascendancy"]}`，返回 `invalid_schema`：`Extra inputs are not permitted. Only use typed schema.` 可用字段为 `context / expected_node_types / limit / query / scope`。
- **影响**：一次无效调用；对研究无实质损害。
- **建议**：文档/skill 中的示例若暗示 `component_kinds`，应更新为 `expected_node_types`（本次运行中 `resolve_graph_component` 也接受 `query` 直接传 stable key）。

### 3. candidateReviews.verificationTasks 必须非空但模板示例为空 — 已修复

- **现象**：`review-contract` 的 `candidateTemplate` 示例中 `verificationTasks: []`（空数组），但 `accept --validate-only` 校验 `_string_list(candidate, "verificationTasks")` 要求**非空**，首次 validate 报 `deep review field must be a non-empty list: verificationTasks`（runtime_failed）。
- **影响**：一次 validate-only 失败，需人工推断 contract 与校验器的不一致。
- **建议**：contract 模板示例把 `verificationTasks` 留空是误导；应在模板中给出至少一个占位任务，或在校验器允许空列表（候选可无验证任务）时放宽。

### 4. support_skill_candidate 对防御 buff / 弹药技能的类型匹配导致记录需拆解 — 已处理

- **现象**：
  - `Explosive Shot`（crossbowammoskill）组内 `Multishot II` 被 `support_skill_candidate` 判为 `required_types_not_matched`（虽然独立调用显示 `hard_compatible`，但 fixed-point 校验在 review 中拒绝该配对）。
  - `Wind Dancer`（防御 buff）组内 Blind II / Knockback / Pin I 全部 `required_types_not_matched`。
- **影响**：`Explosive Shot` 从 supportPackages 移除 Multishot II；`Surrounded 攻防包` 的 Wind Dancer supports 改为 `supportCoverageExceptions` 声明。知识结论本身不受影响，但记录结构与来源技能组的实际 socket 归属不一致（来源中这些宝石确实与技能同组）。
- **建议**：fixed-point 校验与独立 `support_skill_candidate` 结论不一致时，应在 review-contract 中说明两种判定模式的关系；防御 buff 组内支持宝石的归属语义（不生效 vs 归属子技能）需要更明确的指导。

### 5. failure_mode 记录 knowledge identity 需要 primary_damage 角色组件 — 已修复

- **现象**：`Boss 战无小怪` 记录初始组件 role 为 `control_skill` + `payoff`，被拒 `missing_knowledge_identity`。`research_identity.py` 中 `failure_mode` 的 `_KIND_IDENTITY_ROLES` 仅含 `primary_damage / secondary_skill / resource_engine / defense_layer / unique_enabler / keystone_transformer`，`control_skill`/`payoff` 均不构成 identity。
- **影响**：一次 validate-only 失败；把 `Explosive Grenade` role 改为 `primary_damage` 后通过。
- **建议**：review-contract 的 recordTemplate 未说明各 recordKind 的 identity 角色要求；可在 contract 中列出每种 recordKind 可构成 identity 的角色，或提供 `_KIND_IDENTITY_ROLES` 的公开映射。

### 6. cleanup_completed_task_runtime 在 Windows 上目录重命名失败（占用句柄）— 未解决

- **现象**：任务全部 accepted 后调用 `cleanup_completed_task_runtime(task_kind="research", task_id=runId)` 两次均失败：`research_run_cleanup_failed` / `directory_rename_failed` / `errno 13, winerror 5 拒绝访问`，hint 提示进程持有句柄。
- **影响**：run 目录（`.poe-bd-research/runs/20260811-222353-a455`）保留在磁盘上；Research Memory 已写入（不依赖 cleanup），业务结果不受影响。属 Windows 平台运行态问题，需等待句柄释放后重试或人工清理。
- **建议**：cleanup 在 Windows 上对含打开句柄的目录使用 rename 而非删除；失败时应给出更明确的释放指引（如提示哪些进程/工具可能持有句柄），或支持延迟清理队列。

## 观察总结

- 流程总体稳定：queue → claim → inspect/read → memory 对照 → graph resolve → review-contract → init-review → validate-only → accept → status 均按合同工作；cleanup 是本运行唯一未完成步骤（且不影响业务结果）。
- 文档与校验器不一致（问题 3、5）和 Windows 平台细节（问题 1、6）是本次运行的主要摩擦点；问题 2 属参数命名差异。
- 全部研究内容最终以 `acceptanceMode=clean` 入库，16 条深度记录 + 4 个 pattern 全部接受，0 暂缓。
