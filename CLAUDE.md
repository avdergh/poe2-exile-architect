# CLAUDE.md - Claude Code 入口

Claude Code 应使用 [AGENTS.md](AGENTS.md) 作为标准项目指南。

这个文件只是为了让 Claude Code 快速发现仓库规则，避免复制完整 agent handbook。如果
本文件和 `AGENTS.md` 不一致，应更新本文件重新指向 `AGENTS.md`，不要分叉规则。

## 快速规则

- 本项目是 verification-first 的 PoE2 BD 研究与生成工具基座。
- 不要新增项目自带的 autonomous LLM provider loop。
- 不要编写替代数值 BD 引擎；数值声明使用现有 Headless PathOfBuilding-PoE2 wrapper。
- Mature build raw material 只能 quarantine-only，不能持久化可复刻 BD 配方。
- Graph、memory、judge 和 planner 工作使用 typed tools 与 schemas。
- 长期方向保存在 `AGENTS.md`、`docs/PROJECT_SPEC.md`、`docs/ARCHITECTURE.md` /
  `docs/ARCHITECTURE.CN.md` 和 `docs/SCHEMAS.md`。
- 阶段执行细节保存在 `docs/phases/`。
- 除 `docs/ARCHITECTURE.md` / `docs/ARCHITECTURE.CN.md` 外，当前文档只维护中文版本。
- 根 `README.md` 只用于安装、skill 自动化入口和安全边界说明；不要把未完成的生成能力写成已完成产品。

常用命令：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_fragment_extraction.py -q
.\scripts\verify.ps1 quick
```
