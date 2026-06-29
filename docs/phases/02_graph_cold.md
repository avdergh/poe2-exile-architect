# Phase 2 - Physical Graph 冷启动与官方 ID 映射

## 阶段状态

未开始。

## 目标

从权威静态来源建立 graph 的物理世界，而不是依赖 LLM 发明或推断基础事实。

## 依赖

- Phase 1 modelability vocabulary。
- 现有 corpus 和 PoB/GGG static data。

## 工作项

- 创建 physical graph ingestion path。
- 注入 base nodes：
  - skill；
  - support；
  - unique；
  - base item；
  - affix；
  - passive node；
  - notable；
  - keystone；
  - ascendancy；
  - class；
  - weapon type；
  - inventory slot。
- 注入 base edges：
  - passive `connected_to`；
  - skill `has_tag`；
  - support `compatible_with`；
  - affix `applies_to`；
  - item `can_roll`；
  - unique `has_mod`；
  - class `starts_at`；
  - ascendancy `belongs_to`；
  - skill/support `build_planner_exportable`。
- 保存 versioned provenance：
  - source 和 source file；
  - game patch；
  - passive tree version；
  - PoB version/commit；
  - status；
  - confidence。
- 保存官方 `.build` export 需要的 ID 映射：
  - PoB display/internal identifiers；
  - GGG `PassiveSkills`；
  - GGG `BaseItemTypes`；
  - GGG inventory IDs；
  - unique Words/name references；
  - Build Planner export identifiers。

## 验收

- Static node 和 edge counts 符合 source data expectations。
- 抽样 graph facts 能追溯到 static source files。
- 不存在的 skill、notable 或 unique references 会校验失败。
- `.build` 相关 IDs 能为 supported nodes resolve。
- 不依赖 LLM 也能回答基础 graph questions。

## 验证

添加 graph ingestion tests，然后运行：

```powershell
.\scripts\verify.ps1 quick
```
