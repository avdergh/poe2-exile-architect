# Phase 0 - 清理与文档结构

## 阶段状态

已完成。

## 目标

锁定新的 verification-first 项目方向，并删除描述旧产品形态的 public-facing 或历史过程
文档。

## 范围

- 开发阶段删除 `README.md` 和 `README.CN.md`。
- `docs/PROJECT_SPEC.md` 作为中文唯一项目总纲，不作为实现 checklist。
- 用 `docs/ARCHITECTURE.md` / `docs/ARCHITECTURE.CN.md` 替代旧 architecture 文档。
- 增加 `docs/SCHEMAS.md` 作为中文唯一核心数据结构合同。
- 增加 `docs/phases/` 作为中文唯一阶段执行计划目录。
- 更新 `AGENTS.md` 和 `CLAUDE.md`，指向新的 source of truth。
- 删除非 architecture 的中文副本文档，避免双份维护漂移。

## 阶段内进度

- 旧 `README` 已删除。
- 旧 `docs/PROJECT_ARCHITECTURE.md` 已替换为 `docs/ARCHITECTURE.md`。
- `PROJECT_SPEC` 已收敛为中文唯一总纲，并维护 Phase 状态总览。
- `SCHEMAS` 已收敛为中文唯一数据结构合同。
- `docs/phases/*.md` 已收敛为中文唯一阶段计划。

## 验收

```powershell
rg README .
git diff --check
```

`README` 引用只允许出现在“README 开发阶段有意缺席”或“未来 productization 再重建”的
政策文本中。

还需要扫描已删除的内部模型 runner 模块和历史报告目录。除刻意保留的政策文本外，不应
存在旧符号引用。
