# 修复计划（v5，P3+P4 已实现；P0-3 暂停）

> 状态：v3/v4 均完成独立 review；**v5 实现 P4 三项**（③ advisory 豁免 → ② status 快照 → ① 批量
> resolve 上限+守卫），按 P4 review 修正后的方案实施（详见「P4 实现记录」）。
> **P0-3 暂停**：等用户侧确认 Codex 是否更新 subagent 的 MCP 支持能力后再议，并发测试一并暂停。
> 排序原则：频率 × 影响 ÷ 成本。P0=建议立即修；P1=值得修；P2=随改；另有"不做"清单。

---

## P3 实现记录（v4，2026-08-18：content 型黄装知识单位，零提示词增长）

**背景**：单 agent 实测暴露——`gear_synergy` 强制 `gearResponsibilities` 非空且须引用
图节点，纯稀有/魔法装（无图节点）无合法路径，研究者被迫改 recordKind（语义谎言）。
用户决策：**不引入复杂字段设计（否决 gearTemplates 方案），黄装知识作为 content 描述，
随召回返回即可供 Create 使用**。

**实施（全部为代码/校验层，提示词净增 0 token，合同规则换词不增量）**：
1. `server/knowledge/research_models.py`：`gearResponsibilities` 由"非空列表 ≤12"放宽为
   "列表 ≤12"；空列表 = content 型黄装路径（content 本身强制非空）；非空时条目校验
   逻辑原样抽为 `_validate_gear_responsibilities`，语义不变。
2. `scripts/run_phase4_deep_review_acceptance.py`：`_has_explicit_gear_responsibilities`
   增加 content 路径——`gear_synergy` + 空 responsibilities + 非空 content 计为显式
   装备覆盖证据（deep_records 视图传入；验收 summary 不带 content，故从 deep payload
   读取）；`_evaluate_case_coverage` 增加 `deep_records` 参数，两处调用点同步。
3. 合同/提示同源措辞换词：contract rule「gearRoles covered」与 research_prompt.py
   gearRoles 句同步写明 content 型路径（不新增条目）。
4. 召回侧零改动：已核实 `query_research_memory` 在 `detail_level="record"` 时返回
   content + typedPayload（research_memory.py:4037-4039），Create 侧按需以 record 级
   读取黄装模板即可，不放大默认 summary 载荷。

**效果**：纯稀有装驱动的 gear_synergy 记录可合法入库（不改 recordKind）；gearRoles
覆盖度如实判定（content 型证据可声明 covered，机制链不再被误暂缓）；黄装词条知识
以 content 随 Family 召回，Create 模型可直接使用。

**验证**：新增 `test_content_based_gear_synergy_counts_as_explicit_gear_coverage`（单元）
与 `test_content_gear_record_keeps_mechanic_chain_and_gear_coverage`（集成，gearRoles
covered + 机制链不被暂缓 + 记录入库）；覆盖度回归测试全过；相关测试文件全量 +
verify.ps1 quick。

## 单 agent 实测记录（v4，2026-08-18）

- **结果**：subagent 独立跑完 1 案（97 Witch/Abyssal Lich/Thrashing Vines），accepted/clean，
  14 创建 + 2 更新记录，并入既有 Family bf-9dc58e...，0 deferred；回访自评 7 项知识完整性
  全"完整"（技能组 11 组闭合、25 件装备、6 树槽珠宝、配置条件含推断标注等）。
- **P0-1..P2-3 实测**：token 解析顺畅；continuityWarning 实际触发 2 次且续页无跳项；
  countNotes 解释 Phylactery 槽差值避免误报；P1-1 提示一次修复通过；P2-1 未踩到。
- **新摩擦点（P3 与后续）**：① resolve 字段名（P3 前项，独立跟踪，见下）；② gear_synergy
  空职责（P3 已修）；③ 批量 resolve 45 key 仍需 6+ 轮（建议按记录组件集一次解析，P4 候选）；
  ④ status 无 per-sample deferredReasonCounts 快照（P4 候选）；⑤ contract 可明示非身份
  副包 primary_damage advisory 不阻塞（P4 候选，措辞澄清类）。
- **resolve 字段名问题（已修，v4）**：`_normalize_resolve_component_key_alias`
  （graph_tools.py，run_tool 入口处）把 `componentKey` 归一化为 `query`——与 safe-review
  合同组件词汇一致，首次调用即可成功；两者同时提供时保持原样交由 schema 报歧义。
  零提示词增长，`search_graph_components` 等其它工具不受影响。测试：
  `test_resolve_graph_component_accepts_component_key_alias` /
  `test_resolve_graph_component_component_key_alias_combines_with_filters` /
  `test_resolve_graph_component_rejects_dual_query_spellings` /
  `test_component_key_alias_is_resolve_only`（test_graph_tools.py，31 条全过）。

---

## 实现记录（v3，2026-08-18）

- **P0-1 已实现**：token 生成加 `"t"` 前缀（`scripts/research_mature_builds.py` claim_case）；
  `_rewrite_lease_token_argv` 只精确改写 `--lease-token` 后紧跟的 `-` 开头值为等号形式并接入 main()；
   acceptance 文件名与 review 文件名统一走 `_slug(lease_token)[:12]`。测试：
  `test_claim_lease_token_is_argparse_safe` / `test_lease_token_argv_rewrite_only_touches_lease_token` /
  `test_read_cli_parses_dash_leading_lease_token_without_argparse_error`。
- **P0-2 已实现**：`read_packet_section` 两分支在字符预算截断（`nextCursor < cursor + limit`）时
  附加 `continuityWarning`（`_continuity_warning` / `_attach_continuity_warning`）；workerPrompt
  Evidence First 强化"只用 nextCursor 续页、勿用 cursor+limit 自算"。测试：
  `test_read_packet_section_continuity_warning_and_gap_free_chaining`（0..N 全量无空隙无重叠）。
- **P1-3 已实现**：`jewel_counts` 增加 `countNotes`（camelCase 四字段口径说明；向后兼容，
  `_unresolved_jewel_sockets_deferred` 只读旧 key）。测试：既有三珠宝测试补 countNotes 断言。
- **P1-1 已实现**：`unsupported_structured_skill_support_pair` caveat 追加
  supportCoverageExceptions（reason=source_coverage_gap/not_applicable）出口，措辞与
  research_prompt.py:349-352 对齐。测试：2770/2928 处新增文本断言。
- **P1-2 已实现**：`insufficient_gear_context` deferred 增加 `rootCauseRefs`
  （指向 invalid_schema 的 gear_synergy 记录 recordKind/title/sampleId，仅根因存在时附带）；
  accept 聚合前 `_root_cause_first_deferred` 稳定排序（invalid_schema 前置），门禁语义不变。
  测试：`test_gear_context_deferral_references_schema_root_cause_records` /
  `test_gear_context_deferral_without_schema_root_cause_omits_root_cause_refs` /
  `test_root_cause_first_deferred_orders_invalid_schema_before_dependents`。
- **P2-1 已实现**：`_load_safe_json` 错误信息以 `文件名:行:列` 开头（JSONDecodeError 的
  lineno/colno）。测试：`test_load_safe_json_reports_line_column_location_first`。
- **P2-2 已实现**：review-contract 规则重写 primary_damage 双规则关系
  （记录级 ≥1 锚定身份；组级 primary 集合=真实主输出技能集合，多主输出合法，副技能不得标 primary）。
- **P2-3 已实现**：`insufficient_transfer_evidence` caveat 追加"新 Family 首次入库需独立跨族证据"。
  测试：`test_component_transfer_without_gear_evidence_defers_with_first_intake_caveat`。
- **P2-4 仅记录**：cleanup 已有 delayed retry 且实跑成功，不改代码。
- 验证：两个 focused 测试文件全量通过 + `.\scripts\verify.ps1 quick`。

---

## P0-1 CLI lease token 解析兼容（每次会话都可能踩，修复极小）

**现状/证据**：`secrets.token_urlsafe(32)`（`scripts/research_mature_builds.py:410`）的字母表含 `-`，
token 可能以 `-` 开头；argparse `--lease-token` 取值以 `-` 开头时被当作新选项，报 `expected one
argument`（实跑 case 1 踩中，靠 `--lease-token=` 等号形式绕过）。

**方案**：
- (a) 主修复：token 生成时保证首字符为字母数字（如 `"t" + secrets.token_urlsafe(32)`）；
- (b) 防御：argv 预处理**只精确改写 `--lease-token` 后紧跟的 `-` 开头值**为等号形式（不得全局扫描其他选项）；
- (c) 顺带统一：acceptance 文件名用原始 `lease_token[:12]`（`scripts/research_mature_builds.py:1063`），
  与 review 文件名的 `_slug(lease_token)[:12]`（3129-3130）不一致——无功能影响，统一为 slug。

**涉及文件**：`scripts/research_mature_builds.py`（410 生成、argparse 区 3842-3907、1063）。
**验证矩阵**：focused tests（`tests/test_research_mature_builds.py` 新增：token 首字符断言 + 前导 `-`
token 经等号形式解析的 CLI 回归测试；现有 token 唯一性断言 1937、文件名断言 1627 不受影响）；
收尾 `.\scripts\verify.ps1 quick`。
**工作量**：S（0.5 天）。**风险**：低；`_slug` 校验（3154-3156）自洽，workerPrompt 内嵌 token 两侧一致。

---

## P0-2 read 分页游标语义固定（数据完整性，实踩 2 次）

**现状/证据（review 修正根因）**：`read_case_section`（`scripts/research_mature_builds.py:548`）分页经
`research_packet.py:973-991 _bounded_page`，`nextCursor=index`（已消费条数）连续推进、响应已含
`cursor/limit/nextCursor/complete`；**空隙来自调用方**用"上一页 cursor + 请求 limit"自算游标，尤其
字符预算截断（`MAX_RESPONSE_CHARS - 750`，981-988）导致实返 < limit 时自算漂移
（实跑 case 3 的 54-70、case 4 的 68-94）。

**方案**：
- (a) read 分页固定页大小（`limit` 仅作 ≤ 固定页提示，游标推进由服务端算）；
- (b) **复用现有 `limit/nextCursor` 字段**，不新增 pageSize/expectedNextCursor；当字符预算截断使
  `nextCursor < cursor + limit` 时响应增加 `continuityWarning` 显式告警；
- (c) 脚本/文档教 agent **用响应里的 nextCursor 链式推进**（workerPrompt 补一句）；
- (d) 新增测试：0..N 全量分页读取无空隙、无重叠（**当前无 read 分页测试，属全新测试**）。
- 语义区分：`queue` 的 `--limit` 是取样数，被 skill/loop/README 强制使用，**绝不能动**；
  仅 `read`/`search` 的页 limit 可固定（全仓确认无外部调用方）。

**涉及文件**：`scripts/research_mature_builds.py`（read 实现 + argparse）、`server/knowledge/research_packet.py`
（_bounded_page）、workerPrompt 措辞（3335-3419）。
**验证矩阵**：focused tests（`tests/test_research_mature_builds.py` 新增分页连续性测试）+ `verify.ps1 quick`。
**工作量**：M（1 天）。**风险**：低-中（先 grep 全仓 `--limit` 调用点，区分 queue/read 语义）。

---

## P0-3 上下文开销精简（最大摩擦；review 重排为"教学先行"）

实跑 5 案：normal 天赋 130-160 节点（~90% 属性噪音）、resolve 单次 2-4KB 样板 × 90 次、
宽召回 memory 单次可达 450KB；导致后期深度递减（case 1 15 条 → case 5 8 条）。
**review 关键结论：三个子项主张的能力大半已存在，最大且最便宜的杠杆是教学对齐（零代码）。**

### P0-3-教学（主修复，零代码）
workerPrompt（`research_mature_builds.py:826-866、3335-3419`）与 `poe-bd-research/SKILL.md`（391-394 一带）
补三句话：
1. 天赋读取用 `--exclude-routing`（**已存在**：argparse 3878-3884 → `research_packet.py:437-442` 过滤
   → `_is_pure_routing_passive`/`_is_any_attribute_stat` 477-487）；
2. resolve 用 `keys` 批量 + `detail="compact"`（**已存在**：`server/knowledge/graph_tools.py` 92-104、
   590-668，compact 已保留 evidencePathNodes 契约）；
3. read 用 nextCursor 链式推进（配合 P0-2）。
工作量：S（0.5 天）。**先复跑一次实测，若噪音/体积仍超预算再上下列代码补丁**（避免为猜测的杠杆付实现成本）。

### P0-3a（条件补丁）天赋 normal 节点 compact 视图
- 若 `--exclude-routing` 后仍嫌字段多：`read --section passives --node-type normal --compact` 输出
  name/nodeId/stat 摘要。涉及 `scripts/research_mature_builds.py`。S。

### P0-3b（条件补丁）graph_tool_query 通用 compact
- `server/main.py:2823 graph_tool_query` 增加可选 `compact=true`，裁剪**非 resolve 族**（search/explain 等）
  的 evidencePath 样板；**resolve 族必须继续保留 evidencePathNodes**（graph_tools.py:598-599/630 契约、
  research_prompt.py:248）。`test_mcp_split.py` 名称成员断言（59 行）只验工具名，加参数不加工具
  → 无需改该测试（已确认）。矩阵补 `tests/test_graph_tools.py`（658/830 有 evidencePath 断言）。M。

### P0-3c（条件补丁）宽召回 memory 响应裁剪
- **边界写死**：`familyPremiseCatalog` 与 `familyRecordIndex` 的截断/summary 裁剪**只允许作用于未传
  build_family_keys 的宽召回**（`server/main.py:3112-3122 family_scoped` 空 keys 原样返回全量）；
  family-scoped 响应（Create 审计路径，poe-bd-create/SKILL.md:26 + AGENTS.md:138 强制检查 catalog）
  **必须保持完整**——否则 `progression_provenance.py:158-186` 的 premise 审计静默少查，削弱硬合规面。
- 裁剪对象含 `familyRecordIndex`（research_memory.py:3416-3426，宽召回第二大头）。
- 涉及：`server/knowledge/research_memory.py:795-936、3403-3463`、`server/main.py:2922-3160`；
  同步更新 `tests/test_research_memory.py:1236-1255`（receipt==响应 契约）与
  `tests/test_phase5_create_build_cli.py:146`（Create fixture 带 catalog）。
- 另查：MCP 默认 `response_profile="full"`（main.py:2922）——宽召回误用 full 是 450KB 候选来源，
  评估教学收紧默认值。M。

---

## P1-1 meta-host 打包死锁的提示优化（实踩 2 次）

**现状/证据**：fixed-point 拒绝消息（`server/knowledge/physical_graph.py:1639`）只教 "move each rejected
support into the supportPackages entry..."，未提 `supportCoverageExceptions`（
`scripts/run_phase4_deep_review_acceptance.py:2776-2795`；case 2/4 各多跑两轮 validate）。
注：另一路径（4343-4378）与 `research_prompt.py:349-352` 已教该路径。

**方案**：在 unsupportedPairs caveat 文本（2784-2792）追加"受拒对可改走 `supportCoverageExceptions`
（reason=`source_coverage_gap`/`not_applicable`）"，并与 research_prompt.py:349-352、4343-4378
既有措辞**逐字对齐**。
**验证矩阵**：**新增**文本断言（现有测试 2373/2770/2928/3147 只钉 reason 码与 pair key，不覆盖消息文本）。
**工作量**：S。

---

## P1-2 级联暂缓报根因（诊断效率）

**现状/证据**：case 3 中 gear_synergy 记录 invalid_schema，依赖它的 mechanic_chain 以
`insufficient_gear_context`（不同原因）被暂缓，首次诊断误判。全仓无 rootCause 字段（新字段）。

**方案**：deferred 对象增加 `rootCauseRefs`（指向实际 invalid_schema 的 recordId/title）；
accept 聚合（run_phase4_deep_review_acceptance.py:2132/3462 一带）"根因优先"排序。
不改门禁语义（invalid_schema 的 schema_gate_failed 662-663 保持）。M（1 天）。

---

## P1-3 jewelCounts 口径说明（实踩 2 次）

**现状/证据（review 修正）**：`jewel_counts`（`server/knowledge/research_packet.py:243` 起）返回
**四个**字段（allocatedJewelSocketCount / treeSocketedJewelCount / embeddedJewelCount /
socketedJewelCount），核心痛点成立：不解释 allocated≠socketed 的差值来源
（Voices 额外孔 / From Nothing 半径分配 / Phylactery 槽；case 1/3 需人工对账）。

**方案**：`jewel_counts` 增加 `countNotes` 字段（camelCase 风格一致）解释差值来源。
消费方 `_unresolved_jewel_sockets_deferred`（run_phase4_deep_review_acceptance.py:207-226）只读现有 key，向后兼容。
**验证矩阵**：`tests/test_research_mature_builds.py:2351-2354、2429-2430` + `tests/test_phase4_deep_review_acceptance.py:1815-1818` 更新/新增。S。

---

## P2 随改（低优先，顺路处理）

- **P2-1** review JSON 解析错误定位：runtime_failed（scripts 3716/3725）把"文件名:行:列"提到错误顶部。S。
- **P2-2** primary_damage 双规则 advisory 措辞：说明"skill_package 至少一个 primary_damage"与
  "researchGroup 只允许一个"的关系（research_models.py / research_identity.py:14 PRIMARY_ROLES 单例）。S。
- **P2-3** 新 Family 迁移候选暂缓消息友好化：`insufficient_transfer_evidence`（2063，caveat 2065-2069）
  注明"新 Family 首次入库，候选待独立跨族证据"。S。
- **P2-4** Windows cleanup 句柄占用：已有 delayed retry（1898 起）且实跑重试成功，**不改代码**，仅记录。

---

## 不做清单（边界声明）

- 不改变 acceptance 合同/枚举语义（避免知识口径漂移）；
- 不引入 raw PoB/XML 输出；不改 quarantine、copy-safety、resolver 门禁；
- 不做"全自动修复"类优化（保持 Agent 主导）；
- 不为猜测的杠杆新建已存在能力的重复实现（review 修正点）。

---

## 执行顺序建议（v2 原案 / v3 实际）

1. ~~教学 PR（P0-3-教学 + P0-2 的 nextCursor 提示 + P2-2/2-3 措辞）~~：**P0-3 整块已按用户决策推迟**
   （含教学；P0-2 的 nextCursor 提示已随 P0-2 实现，P2-2/2-3 措辞已随各自实现）。
2. P0-1 → P0-2（代码）→ P1-3 → P1-1（各独立小 PR）→ **v3 已全部实现并测试通过**。
3. ~~复跑一次研究实测教学效果~~：随 P0-3 一并推迟（subagent 并行方案先行）。
4. P1-2 → P2-1 → **v3 已实现并测试通过**；P2-4 仅记录不改码。

## 验证矩阵总则（v2，review 修订）

- 每个改动文件必须有对应 focused tests，**用 `uv run pytest <文件>` 显式运行**——
  `verify.ps1 quick` **不包含** test_research_mature_builds.py / test_phase4_deep_review_acceptance.py /
  test_research_memory.py，不能替代 focused 运行；
- graph 响应形状改动另跑 `tests/test_graph_tools.py`；MCP 工具改动核对 `tests/test_mcp_split.py`；
- 收尾 `.\scripts\verify.ps1 quick`；触碰 graph 响应形状 → `noncompute`；不触碰 PoB 引擎 → 无需 compute；
- 改动提示语后全仓 grep 同源措辞（research_prompt.py / workerPrompt 模板 / run_phase4_* 消息），保持表述一致。

---

## v3 Review 记录（独立 subagent 静态 review，2026-08-18）

- **总体结论**：READY WITH MINOR NOTES。8/8 项全部 APPROVE——所有实现与「实现记录（v3）」
  逐条一致，均为增量化/展示层/教学层改动，未改动任何门禁或数值语义。
- **逐条**：P0-1 approve（token 前缀 + 仅精确改写 `--lease-token` + 文件名 slug 统一，None/
  等号形式/无值三种边界通过）；P0-2 approve（`nextCursor < cursor + limit` 截断谓词正确，
  两分支均附加，空页截断项场景覆盖）；P1-1 approve（与 contract 文本 supportCoverageExceptions
  措辞一致）；P1-2 approve（rootCauseRefs 仅取自 invalid_schema 的 gear_synergy、非空才附带；
  稳定排序纯展示层、门禁不消费排序）；P2-1/P2-2/P2-3/P1-3 approve（P2-2 双规则与
  infer_build_family 集合语义一致，未发现组级单主输出强制）。
- **minor notes（均已在实现轮闭环）**：① 测试通过性由实现轮验证（两个 focused 测试文件
  全量 exit 0 + verify.ps1 quick 全绿），reviewer 预算内未重跑；② P1-1 与 research_prompt.py:349-352
  的措辞对齐（reason 枚举逐字一致，语义一致）；③ argv 改写仅处理精确 `--lease-token` 拼写
  （符合"只精确改写"计划意图）；④ schema_deferred_records 耦合依赖调用方过滤 invalid_schema
  （内部有防御性二次过滤，全仓唯一调用点）；⑤ P0-2 只覆盖 read_packet_section 两分支
  （search 为独立分页路径，不在计划范围）。
- 过程中两次后台 review subagent 未能在时限内产出结论，已中断并改用最小预算前台静态 review
  完成；本记录即其结论。

---

## Review 记录（subagent 对照仓库逐条验证，2026-08-18）

- **总体结论**：v1 计划可执行，P0-1/P0-2/P1-1/P1-3 证据基本属实；**P0-3 结构性误判**
  （三个子项能力已存在：`--exclude-routing` / resolve keys-batch+compact / create_compact+family_scoped），
  主修复应为教学对齐；P0-3c 按 Family 截断会削弱 progression_provenance 硬合规审计面。
- **逐条**：P0-1 approve（补 1063 raw slice 统一）；P0-2 amend（根因是调用方自算游标 + 字符预算截断，
  复用现有字段 + continuityWarning，测试为全新）；P0-3a reject 原案/amend 教学优先；P0-3b amend
  （resolve compact 必须保留 evidencePathNodes，test_mcp_split.py 无需改）；P0-3c amend（截断仅宽召回、
  补 familyRecordIndex、保 receipt 契约 test_research_memory.py:1252-1255）；P1-1 approve（测试为新增文本断言、
  与 349-352/4343-4378 措辞对齐）；P1-2/P2-1/2-2/2-3/2-4 approve；P1-3 amend（四字段表述、camelCase）。
- **优先级评审**：同意 P0-1→P0-2 排序；P0-3 从最大工程量降为"教学（S）→ 实测 → 按需补丁"；
  遗漏项：familyRecordIndex 裁剪、MCP 默认 response_profile=full、深度递减因果未证（先复跑）。
- **风险确认**：token 前缀安全（slug 自洽）；`--limit` 语义必须区分 queue（绝不能动）与 read（无外部调用方）；
  quick 档不含 focused 研究测试。

---

## v4 Review 记录（独立 subagent 静态 review，2026-08-18）

- **总体结论**：READY WITH MINOR NOTES，5/5 APPROVE。别名归一化 fail-closed（非字符串/空串/
  双拼写/其它工具均安全，错误提示字段清单保持准确）；gear 放宽后"空职责+空 content"不可能
  通过（content 强制非空）；content 路径两个调用点正确（中间过滤只移除 mechanic_chain）；
  门禁语义零变化；报告载荷无膨胀（summary 不带 content）；全仓无旧措辞残留。
- **minor notes**：① `componentKey`+`keys`（无 query）走批量路径时别名被静默丢弃（无害，
  与"双拼写拒绝"意图略不一致）；② 双拼写拒绝提示不宣传 componentKey 别名（外观问题）；
  ③ content 型黄装记录仍需 ≥1 已解析组件锚点（`insufficient_research_depth` 强制），
  contract 未显式说明（文档缺口，可与 P4③ 措辞轮一并补）；④ 两个别名守卫测试在功能被
  移除时不会失败（钉的是契约而非回归，可接受）。

## P4 实现记录（v5，2026-08-18）

按 P4 review 的修正方案实施，顺序 ③→②→①（全部 S 级，零提示词增长）：

- **③ primary_damage advisory 豁免**：`_record_kind_advisories` 对"组件全部为
  clear_skill/boss_skill/triggered_payload/trigger_host"的纯副技能包跳过 primary_damage
  advisory（advisory 文案同步注明豁免；锚定身份的包仍要求 primary）；contract 双规则句与
  workerPrompt 清单 14 换词补充"纯副技能包不需要自己的 primary_damage 声明"；同时补 v4
  文档缺口——content 型黄装记录须含 ≥1 已解析组件锚点（contract gearRoles 句）。
  测试：`test_record_kind_advisory_exempts_secondary_only_packages`。
- **② status per-sample deferredReasonCounts 快照**：`_research_quality_summary` 增加
  `deferredReasonCounts`（accept 时持久化）；`_fetch_cases` 已把 quality_summary 全量并入
  每行输出，status 自动可见，无需改 status 代码。测试：
  `test_research_quality_summary_persists_deferred_reason_counts_for_status`（accept→status 往返）。
- **① 批量 resolve 上限 + payload 守卫**：`ResolveGraphComponentInput.keys` 上限 20→60；
  批量端点 `_resolve_graph_components_batch` 在 detail=full 且载荷超 `MAX_PAYLOAD_BYTES`
  时降级为 compact 投影（语义边四字段保留）+ `payload_limit_truncated` caveat，不再无守卫
  膨胀。测试：`test_resolve_graph_component_batch_handles_large_key_sets`（30 key）/
  `test_resolve_graph_component_batch_enforces_key_cap`（61 key 拒绝）/
  `test_resolve_graph_component_batch_full_falls_back_to_compact_on_payload_overflow`。
- 验证：6 个新测试全过 + 6 个受影响测试文件全量 + verify.ps1 quick。

## P4 Review 记录（独立 subagent 静态 review，2026-08-18）

- **总体结论**：READY WITH MINOR NOTES，5/5 APPROVE（advisory 豁免 / 三处措辞 / quality
  summary / 批量守卫 / 测试全部正确，符合设计 review 的 ③②① 方案）。
- **minor notes 处置**：① 英文 mandatoryChecks 镜像缺豁免句 → **已修**（:878 补
  "clear/boss/triggered secondary-only packages are exempt"）；② contract 规则"组件全是副角色"
  措辞宽于 4-role 集合 → **已修**（改为"组件全是 clear/boss/triggered/trigger_host 的纯副
  技能包"，与实现逐字对齐）；③ 60/61 边界未钉 → **已修**（large-key-set 测试 30→60，精确
  钉住上限）；④ gearRoles content 路径"防御便利装可满足覆盖"——**先前 v4 review 已评估并
  接受**（防线从 schema 级退到 review 级是 content 路径的固有属性，研究者自声明 + 深审把关），
  且锚点要求由 insufficient_research_depth 强制 ≥1 已解析组件，与新增措辞一致；⑤ 工作树
  diff 含 v3/v4 改动——**各自轮次已独立 review**（v3 轮 / v4 轮），非遗漏。
- 修复后：三个受影响测试文件全量 exit 0 + verify.ps1 quick 全绿。

## P4 候选 review 记录（独立 subagent 设计 review，2026-08-18）

- **① 按记录组件集批量 resolve — VERIFIED（真实摩擦），建议 amend**：`keys` 上限 20
  （graph_tools.py:94）是问题本体；批量端点 `_resolve_graph_components_batch` 无 payload
  守卫（`MAX_PAYLOAD_BYTES` 只作用于 get_passive_subgraph_in_radius）——**先提高上限
  （~60，仅 detail=compact）并给批量路径加 payload 守卫**（S）；记录级输入模式（M）仅在
  提高上限后仍嫌多轮再做；记录级模式还需解决"批量共享 expected_node_types/scope、无逐项
  覆盖"的既有缺口（acceptance 侧逐组件过滤依赖它）。
- **② status per-sample deferredReasonCounts 快照 — VERIFIED（真持久化缺口），建议照做**：
  deferredReasonCounts 在 accept 时计算、实时返回给 agent、**随后被丢弃**，从未写入队列库；
  `research_quality_summary`（TEXT JSON）不含它。修法：accept 时并入
  `research_quality_summary`（无 ALTER/迁移，旧行 `'{}'` 安全）+ `_queue_report` 暴露；
  加 accept→status 往返测试。S。
- **③ 非身份副包 primary_damage advisory — 部分 VERIFIED（前提错一半），建议 amend**：
  **contract 本身已消歧**（rules 878/884-889、workerPrompt 14 均已写明副技能不参与身份）；
  真正矛盾的信号是 **advisory 本身**——`_record_kind_advisories` 对每个
  skill_package/mechanic_chain（含纯副技能包）都提示"should declare at least one
  primary_damage"，与合同自相矛盾。修法：advisory 跳过或显式豁免 secondary-only 包
  （全部组件 role ∈ clear_skill/boss_skill/triggered_payload/trigger_host），或追加
  "副技能包不要求"；保留 advisory 属性不升为硬失败；兜底：锚定 Family 身份的包仍须有
  primary。S。
- **执行顺序（若全做）**：③→②→①（③最便宜且消除每案误导信号；②解锁运行后监控；
  ①触及共享 MCP 工具契约，最后做并单独 review）。
