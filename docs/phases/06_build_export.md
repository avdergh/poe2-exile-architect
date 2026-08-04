# Phase 6 - 最终 PoB 产物保存与官方 `.build` 导出

## 阶段状态

已完成。

已完成：

- 重新确认阶段边界：Phase 6 不重新设计或补全 BD，只保存 Phase 5 最终可信 PoB，并转换为
  官方 Build Planner 可读取的单阶段 `.build`。已完成
- 核对 GGG 官方 Build Planner v1 experimental 文档，确认 `.build` 是游戏内 Build Planner 和
  官网 Builds 页面支持的 JSON 文件。已完成
- 取消多阶段、升级区间和生命周期快照作为 MVP 要求；Phase 6 第一版只输出一个最终阶段。已完成
- 审查首个第三方转换 provider：`PraedythXIV/poe2-build-converter` 使用 MIT License，具有独立
  `convert(input, options)` 核心入口和较完整测试，但未发布为稳定包，`package.json` 为 private。
  第一版按固定 commit 通过隔离适配器调用，不让业务层依赖其内部类型。已完成
- 真实生成候选已完成最终 artifact 保存、桌面 PoB XML/导入码导出、官方 `.build` 转换和人工
  查看；导出结果成功暴露前置构筑完整度问题，并验证导出闭环可用于持续校正 Phase 1-5。已完成

## 阶段目标

建立以下最小闭环：

```text
Agent 在活动 PoB 中完成候选
  -> evaluate_generation_candidate 生成可信 Judge 凭据
  -> Agent 明确接受某个 passed 候选
  -> 保存该候选的最终完整 PoB artifact
  -> 会话或 MCP 重启后仍可恢复
  -> 可插拔 converter 转成官方单阶段 .build JSON
  -> schema/provider validation
  -> 游戏内 Build Planner 人工导入验收
```

`.build` 是构筑指导文件，不是 PoB 的完整替代品。PoB 继续承担完整装备、天赋、技能、配置和
数值计算；`.build` 负责在游戏内展示推荐升华、天赋、技能、辅助技能和装备槽提示。

## 依赖

- Phase 2 physical graph、官方 ID 和 resolver 基础；
- Phase 5 活动 PoB、可信 Judge 凭据和有限内部重试；
- GGG 官方 Build Planner v1 experimental 格式文档；
- 一个经过许可证和行为审查的可插拔 PoB -> `.build` converter provider。

## 边界

- Phase 6 不负责重新设计 BD、补装备、补天赋或选择技能；
- Phase 6 不根据单阶段 PoB 自动推导开荒、攻坚、终局或升级路线；
- 失败轮次只保留 Phase 5 已有的安全 Judge 摘要，不持久化完整 PoB XML；
- 每个生成运行最多保存一个最终完整 PoB artifact；
- 只有 Agent 明确接受、可信 Judge `passed=true`、且当前活动 PoB 哈希与该 Judge 凭据一致时
  才能保存；
- 保存的 PoB XML 只进入本地私有 artifact store，不进入聊天、人工验收包、研究记忆或 Git；
- 第三方成熟 BD 的原始 PoB/XML 仍遵守 quarantine-only 边界，不能借 Phase 6 进入最终 artifact；
- converter 是可替换 provider。业务层只依赖稳定输入输出合同，不直接依赖第三方内部模块；
- GGG 官方格式和游戏内导入结果是最终权威，第三方 converter 不是绝对真理；
- 官方 ID 缺失、歧义、过期或 provider 不支持时必须返回结构化 caveat，不能猜测。

## P6.0 文档与 provider 选型 - 已完成

完成项：

- GGG 官方文档确认 `.build` 为单个 `Build` JSON 对象，当前版本是 v1 experimental；
- 官方使用方式包括放入本地 `BuildPlanner` 目录，以及上传官网 Builds 页面后在游戏内使用；
- 官方字段包括 `name`、`author`、`link`、`description`、`ascendancy`、`passives`、`skills`、
  `inventory_slots`；
- meta gems 当前官方格式不支持；
- 社区已有 PoB2 -> `.build` 转换实现，第一版不从零重新研究所有映射；
- 首选 provider 为 `PraedythXIV/poe2-build-converter`，固定 commit、保留 MIT notice，并通过
  provider adapter 隔离。

## P6.1 最终可信 PoB artifact

目标：只保存最终通过且被 Agent 接受的一版 PoB。

最小流程：

1. Agent 完成最后一次 `evaluate_generation_candidate`；
2. Agent 根据 Judge 和自身核验决定接受该版本；
3. Agent 调用最终保存工具，并指定本次运行、候选和可信 attempt；
4. 程序重新读取活动 PoB XML，并用可信凭据中的 `semanticStateHash` 核对等级、技能、装备、
   天赋和配置等真实输入没有变化；
5. 程序核对 candidate、attempt、snapshot、原始 source hash 和 `passed=true`，并取回当前
   MCP 进程内短暂保留的精确 Judge XML；
6. 核对成功后把该精确 Judge 快照原子写入一个 `FinalBuildArtifact`；
7. 同一运行已有 artifact 时拒绝覆盖。

验收：

- Judge 未通过时不能保存；
- 活动 PoB 在 Judge 后发生变化时不能保存；
- 失败轮次不会留下完整 XML；
- 同一运行只能保存一个最终 artifact；
- MCP 重启后能读取并重新载入 artifact；
- artifact XML 不出现在安全报告、日志、聊天或 Git 状态中。

当前实现：

- 新增本地私有 artifact store，默认位于 user-data 的 `final-build-artifacts`，测试可通过环境变量
  隔离。已完成
- 新增 `save_final_build_artifact`：只接受当前运行最后一轮、可信 Judge `passed=true`、没有硬
  阻断且活动 PoB 语义输入未变化的候选；PoB 刷新派生输出不会造成误拒，精确 Judge XML 只在
  进程内交接，未落盘到 run receipt。已完成
- 同一运行只能保存一个最终 artifact，拒绝覆盖；失败轮次和旧 attempt 不保存完整 XML。已完成
- 新增 `list_final_build_artifacts`，只返回安全 manifest，不返回 XML 或 PoB code。已完成
- 新增 `load_final_build_artifact`，校验 XML 与 source hash 后直接恢复到活动 Headless PoB，响应
  只包含安全摘要。已完成
- `/poe-bd-create` 已加入保存顺序：Agent 接受最后一轮通过版本后，必须在 `review-packet` 消费
  run token 前保存最终 artifact。已完成
- 聚焦测试覆盖保存、列表、MCP 重启后恢复、活动状态篡改、Judge 失败、旧 attempt、重复保存和
  artifact 损坏。已完成

P6.1 状态：已完成。

## P6.2 可插拔 converter provider

业务层合同：

```text
FinalBuildArtifact PoB XML + export metadata
  -> BuildPlannerConverter
  -> .build JSON + warnings + conversion stats + provider provenance
```

第一版 provider 策略：

- provider 代码固定到明确 Git commit，不跟随上游 `main` 漂移；
- provider 安装在本地工具/运行时目录，不把完整第三方前端应用混入业务模块；
- 通过标准输入输出或等价隔离边界调用；
- Python/MCP 层不 import 第三方 TypeScript 内部类型；
- provider 缺失时返回明确安装/准备指引，不静默降级为名称猜测；
- provider 输出还要通过本项目的最小官方 schema 校验；
- 后续可以替换成正式包、其他 CLI 或自研实现，而不改变 MCP 对外合同。

验收：

- provider 可用性可探测；
- 固定版本和许可证可追踪；
- 相同 PoB XML 和 metadata 产生确定性 `.build` JSON；
- provider 错误不会破坏 MCP 主进程；
- 替换 provider 不需要修改 artifact store 或 Phase 5。

当前实现：

- 固定 `PraedythXIV/poe2-build-converter` commit
  `27f5dad0d0979aa23a604defd11fcf7ae4668444`，保留 MIT notice 和数据来源说明。已完成
- provider 通过 NDJSON 子进程合同隔离；Python 层不 import 第三方 TypeScript 类型。已完成
- 新增安装脚本，执行固定 lockfile 安装、编译、零高危漏洞审计和运行依赖裁剪。已完成
- 新增 `get_build_planner_converter_status`，检查 provider identity、version、commit、license、
  runner 和 Node 版本。已完成
- Node 运行时通过共享 resolver 发现：优先尊重显式配置和系统 PATH，并可自动使用 Codex
  Desktop 随附 runtime；验证脚本同样复用该 resolver 和可用的 `npx` / `pnpm` runner，不要求
  全局安装 `npx`。provider 仍要求 Node 20 或更高版本。已完成
- provider 缺失、进程失败、超时、非 JSON、请求/hash 不匹配和畸形响应均返回结构化错误。已完成
- provider 子进程通信固定使用 UTF-8，避免 Windows 中文系统按 GBK 解码装备提示中的 Unicode
  符号而产生内部空值错误。已完成
- 使用真实 `witchhunter_detonate.pobcode` fixture 验证固定 provider 可转换升华、天赋、技能和
  辅助技能。已完成

P6.2 状态：已完成。

## P6.3 单阶段 `.build` 导出

第一版只忠实导出最终 PoB 当前状态：

- name / author / description；
- ascendancy；
- 当前已分配 passives；
- 当前技能和 support skills；
- 当前 inventory slot hints；
- 支持时保留 weapon set；
- uniques 使用官方 `unique_name`；
- rares/magic items 只能进入官方格式允许的 guidance text；
- unsupported、missing、ambiguous 和 stale 字段进入 caveats。

第一版不做：

- 多阶段 build snapshots；
- 自动生成 `level_interval`；
- 自动拆分升级树；
- 自动生成开荒到终局路线；
- 把 PoB DPS/EHP 写进官方字段并伪装成游戏内计算结果。

当前实现：

- 新增内部 artifact 读取入口，导出前重新核对 XML hash、Judge snapshot/source hash、passed 状态
  和硬阻断。已完成
- 新增 `export_final_build_artifact`，只从最终可信 artifact 转换，不接受聊天中的任意 XML。已完成
- provider 转换后递归移除全部 `level_interval`，MVP 输出严格保持单阶段。已完成
- 输出包含升华、当前天赋、技能/辅助和 provider 可映射的装备槽提示；不修改 Agent 已完成的 BD。
  已完成

P6.3 状态：已完成。

## P6.4 导出门与产物

导出必须检查：

- artifact manifest、PoB XML 和 source hash 一致；
- artifact 绑定的可信 Judge 仍可核对；
- provider identity、version/commit 和 license 已记录；
- `.build` 顶层是单个 Build JSON object；
- name 非空；
- passive IDs、gem IDs 和 inventory IDs 满足官方格式与 provider validation；
- provider `error` warning 阻止成功导出；
- 非阻断 warning 和 unsupported fields 进入 `BuildPlannerExportReport`；
- 输出文件使用 `.build` 后缀，并写入本地导出目录。

当前实现：

- 本地最小官方 schema 校验覆盖顶层字段、非空 name、passive/gem/support ID、inventory ID 和
  单阶段无 `level_interval`。已完成
- provider `error` warning 和 schema validation failure 阻断写文件；info/warn 原样进入安全导出
  报告。已完成
- `.build` 原子写入 user-data 的 `build-planner-exports`，响应只返回路径、provider provenance、
  转换统计和 caveats，不包含 PoB XML。已完成
- 新增 `export_final_pob_artifact`，默认同时写出桌面 PoB 可用的完整 XML 和导入码文本；响应仅返回
  本地路径，不把原始内容写入聊天或报告。已完成
- 新增 `export_final_build_package` 作为稳定交付入口，一次生成并固定列出 PoB XML、导入码文本和
  官方 `.build` 三项；部分失败时仍保留完整清单和错误码，避免 Agent 漏生成或漏报产物。已完成
- skill 和 MCP instructions 已加入 artifact 保存后导出流程。已完成
- 聚焦测试覆盖成功导出、损坏 artifact、error warning、provider 缺失/崩溃/协议错误/hash 不匹配
  和真实 fixture。已完成
- `quick` 和完整 `noncompute` 验证通过，MCP manifest、格式检查、静态检查和全部非计算测试均通过。
  已完成
- 使用真实 Stormweaver Arc 与 Deadeye Lightning Arrow 最终 artifact 回归导出成功；Arc 映射
  79 个天赋、3 个技能、7 个辅助和 10 个装备槽，schema validation 通过且无 warning。已完成

P6.4 状态：已完成。

## P6.5 E2E 与人工验收

固定验收流程：

1. 运行 `/poe-bd-create` 生成一个真实候选；
2. 至少一次可信 Judge 通过；
3. Agent 明确接受并保存最终 artifact；
4. 重启 MCP 或新会话加载 artifact；
5. 导出 PoB XML、PoB 导入码文本和单阶段 `.build`；
6. 在桌面 PoB 中打开 XML 或导入导入码，核对完整装备、天赋、技能组、配置和计算结果；
7. 把 `.build` 放入游戏 `BuildPlanner` 目录或上传官网 Builds 页面；
8. 在游戏内核对升华、天赋、技能/辅助和装备槽提示；
9. 记录 PoB、converter 和游戏内显示差异；
10. 人工评分通过后 Phase 6 才完成。

本轮人工验收新增检查：

- PoB 中黄装应显示阶段合理 `Item Level`，且底材需求等级不高于角色等级；
- 最终 artifact 不得保留 `Scaffold ...` 占位装备；
- 核对符文/灵魂核心、天赋珠宝、生命/魔力药剂和腰带支持的护符是否已实际装备，或是否有明确
  的阶段/预算理由不使用；
- 官方 `.build` 只能把黄装转为槽位提示文字，不能据此误判 PoB 内黄装是暗金；完整随机黄装仍以
  PoB XML/导入码为准。

P6.5 状态：人工验收通过，已完成。

## 完成后的问题归属

Phase 6 完成后，真实 PoB / `.build` 导出仍会继续作为全链路验收入口，但发现的问题按根因归属：

- 构筑技能、装备、天赋、药剂、护符、珠宝或符文不完整：回到 Phase 5 和公共计算工具修正；
- 合法性、评分、主输出识别或建模判断不合理：回到 Phase 1 / Judge 修正；
- 数据、图、机制或研究记忆缺口：回到对应 Phase 2-4 能力修正；
- artifact 保存、PoB 文件、provider 转换、官方 ID、`.build` schema 或交付清单错误：属于
  Phase 6 维护范围。

因此，后续根据导出结果完善前置阶段不表示 Phase 6 重新进入“进行中”；只有导出合同本身发生
回归或官方格式变化时，才重新维护本阶段实现。

## 进度维护

- 每完成一个具有验收标准的工作项，在本文件对应条目后标记“已完成”；
- provider commit、官方格式版本、游戏赛季和数据更新时间必须随实现同步维护；
- 新赛季优先验证官方 `.build` schema 是否变化、provider 数据是否更新、被保存 PoB 的 tree
  version 是否仍兼容；
- README 可以准确说明已支持最终可信单阶段 PoB 与官方 `.build` 导出，但不能把它描述成已经
  解决生成质量、复合技能评分或完整产品闭环。已完成

## 验证

开发中先运行聚焦测试。涉及 artifact store、MCP 注册、安装和文档时至少运行：

```powershell
.\scripts\verify.ps1 quick
```

涉及 PoB XML 捕获/恢复、converter runtime 或打包时，按改动范围运行 compute/full。最终提交前统一
进行代码审查和完整验证。
