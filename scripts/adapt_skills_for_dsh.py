"""Rewrite Exile Architect skills for the DeepSeek Harness agent preset.

The Codex/OpenCode plugin skills call MCP tools by bare name (or by the
`poe_<domain>_mcp__<tool>` prefixed form). In DSH every MCP tool is registered
as `mcp__<serverName>__<tool>`, so this script rewrites a copy of the skills
under `dsh/agent-presets/poe-bd/skills/` with:

- the DSH tool prefix applied to every real MCP tool name (word-boundary safe,
  so `get_build` never corrupts `get_build_stats`);
- legacy `poe_<domain>_mcp__` prefixed forms converted to `mcp__poe_<domain>__`;
- bare server-name references (`poe_knowledge_mcp` -> `poe-knowledge-mcp` row id);
- a DSH adaptation note inserted after the frontmatter.

The tool -> server mapping is parsed from the four `server/mcp/*_server.py`
`_TOOLS` tuples, so it cannot drift from the real registrations.

Run from the repo root:

    python scripts/adapt_skills_for_dsh.py            # rewrite (idempotent)
    python scripts/adapt_skills_for_dsh.py --check    # verify no leftovers
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILLS = ROOT / "poe-bd-creator-plugin" / "skills"
OUT_SKILLS = ROOT / "dsh" / "agent-presets" / "poe-bd" / "skills"

# server name (DSH mcp-client serverName) -> server entry module.
SERVER_MODULES = {
    "poe_knowledge": "server/mcp/knowledge_server.py",
    "poe_build": "server/mcp/build_server.py",
    "poe_research": "server/mcp/research_server.py",
    "poe_learning": "server/mcp/learning_server.py",
}

# Generic note inserted after the frontmatter of every adapted skill.
GENERIC_NOTE = """\
> **DSH 适配说明**：本 skill 运行在 DeepSeek Harness。所有 poe-bd 能力都是 MCP
> 工具，完整名带 `mcp__poe_<server>__` 前缀（例如
> `mcp__poe_knowledge__query_research_memory`、`mcp__poe_build__get_build_stats`），
> 下文只写末尾名称。加载本 skill 使用 DSH 的 `skill` 工具，不存在 `/poe-bd-*`
> 斜杠命令。工具清单以当前会话实际注册为准，不要猜测未注册的工具名。
"""

# Per-skill extra notes appended after the generic note.
EXTRA_NOTES = {
    "poe-bd-create": """\
> Create 只连接 knowledge + build 两个 server：知识/图/机制/Research 查询走
> `mcp__poe_knowledge__*`，所有 PoB/计算/Judge 工具走 `mcp__poe_build__*`。
> 所有 PoB/计算工具共享同一个活动构筑、必须串行调用；只有不接触活动构筑的
> 语料/图/机制/静态查询可以并行。
""",
    "poe-bd-research": """\
> **DSH 映射**：Controller 用 `subagent` 后台启动显式
> `poe-bd-research-worker`，等待后台结算，并用 `send_message` 续聊回访。
> queue 由 DSH shell（Windows 为 pwsh）执行，外层超时至少 `600000ms`。
""",
    "poe-bd-research-worker": """\
> **DSH Worker**：只允许 Controller 显式用 `skill` 工具加载本 skill；从 assignment
> 取得 runDir 后用 shell 执行单案流程，不创建或恢复 queue。
""",
    "poe-bd-learning-loop": """\
> **DSH 映射（重要）**：Codex Desktop 任务原语（`create_thread` /
> `send_message_to_thread` / `wait_threads` 等）在 DSH 中不存在。对应关系：
> 可见任务 → DSH 子代理（`subagent` / `subagent_fork`，默认后台运行）+
> `send_message` 推进阶段；等待 → 子代理后台结算通知；`$poe-bd-create` →
> 加载 `poe-bd-create` skill。任务初始化/恢复语义（不创建重复任务、不重放
> 已消费阶段）保持不变。
""",
    "poe-bd-research-loop": """\
> **DSH 映射（重要）**：Codex Desktop 任务原语与 `poe_research_orchestrator`
> MCP 是 Codex 环境的编排方式，本 preset 不提供。DSH 下等效编排：主会话
> （控制任务）用 `subagent` 启动研究子代理（后台运行、可续聊），用
> `send_message` 按阶段发送固定提示词，等待子代理结算通知，以 poe-bd 的 MCP
> 状态工具作为检查点事实源。`poe_research_orchestrator` MCP 若需保留，须在
> DSH 中单独注册。
""",
}

# Legacy prefixed form -> DSH prefixed form (server-name segment only).
_LEGACY_PREFIX_RE = re.compile(r"poe_(knowledge|build|research|learning)_mcp__")
# Bare legacy server-name references (row ids in the DSH composition).
_LEGACY_SERVER_RE = re.compile(r"poe_(knowledge|build|research|learning)_mcp")
_LEGACY_WILDCARD = "poe_*_mcp"


def load_tool_names() -> dict[str, list[str]]:
    """Parse each server module's `_TOOLS` tuple into tool-name lists."""
    mapping: dict[str, list[str]] = {}
    for server, rel in SERVER_MODULES.items():
        path = ROOT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_TOOLS":
                        for elt in node.value.elts:  # type: ignore[attr-defined]
                            if isinstance(elt, ast.Name):
                                names.append(elt.id)
        if not names:
            raise SystemExit(f"no _TOOLS parsed from {path}")
        mapping[server] = sorted(names)
    return mapping


def tool_to_prefixed(mapping: dict[str, list[str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for server, names in mapping.items():
        for name in names:
            full = f"mcp__{server}__{name}"
            if name in result and result[name] != full:
                raise SystemExit(
                    f"tool name {name!r} is registered by more than one DSH server: "
                    f"{result[name]!r}, {full!r}"
                )
            result[name] = full
    return result


def boundary_re(name: str) -> re.Pattern[str]:
    # Word chars include `_`, so a bare-name match can never bite inside a
    # longer snake_case token (`get_build` vs `get_build_stats`).
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")


# Per-skill literal polish applied after the mechanical rewrite. Kept in the
# generator so re-runs stay identical.
POLISH = {
    "poe-bd-create": [
        (
            "机制/Research 查询走 `poe-knowledge-mcp`，所有 PoB/计算/Judge 工具走\n`poe-build-mcp`。",
            "机制/Research 查询走 `mcp__poe_knowledge__*`，所有 PoB/计算/Judge 工具走\n`mcp__poe_build__*`。",
        ),
    ],
    "poe-bd-research": [
        (
            "当前宿主由安装器管理的 `poe-knowledge-mcp`（或任一 `poe-*-mcp`）条目中的",
            "当前宿主 MCP 注册中 `poe-knowledge-mcp`（或任一 `poe-*-mcp`）行的",
        ),
    ],
}


def rewrite_text(text: str, mapping: dict[str, list[str]], name: str) -> str:
    prefixed = tool_to_prefixed(mapping)
    # 1. Bare names -> DSH prefixed names. Legacy `poe_*_mcp__name` forms are
    #    untouched here: the segment before the tool name is a word char, so the
    #    boundary never matches inside them.
    for tool, full in sorted(prefixed.items(), key=lambda kv: -len(kv[0])):
        text = boundary_re(tool).sub(full, text)
    # 2. Legacy prefixed forms -> DSH prefixed forms.
    text = _LEGACY_PREFIX_RE.sub(r"mcp__poe_\1__", text)
    # 3. Bare legacy server-name references -> DSH composition row ids.
    text = text.replace(_LEGACY_WILDCARD, "poe-*-mcp")
    text = _LEGACY_SERVER_RE.sub(r"poe-\1-mcp", text)
    # 4. Targeted polish for sentences that need DSH phrasing, not row ids.
    for old, new in POLISH.get(name, []):
        if old in text:
            text = text.replace(old, new)
    return text


def insert_note(text: str, note: str) -> str:
    """Insert the DSH adaptation note right after the frontmatter block."""
    if not text.startswith("---"):
        raise SystemExit("skill file has no frontmatter")
    end = text.index("\n---", 3)
    close = text.index("\n", end + 1) + 1
    return text[:close] + "\n" + note + text[close:]


def adapt_skill(
    name: str,
    mapping: dict[str, list[str]],
    *,
    source: Path,
    skill_dir: Path,
    out: Path,
) -> list[str]:
    found: list[str] = []
    for rel in sorted(skill_dir.rglob("*")):
        if not rel.is_file():
            continue
        # `agents/` holds host-interface metadata for other hosts, not skill
        # content; DSH discovers only SKILL.md / flat Markdown and would ignore
        # these files, so keep them out of the preset.
        if rel.parent.name == "agents":
            continue
        # Relative to the skills ROOT so the skill-name directory level is kept.
        out_file = out / rel.relative_to(source)
        text = rel.read_text(encoding="utf-8")
        original = text
        rewritten = rewrite_text(text, mapping, name)
        if rel.name == "SKILL.md":
            note = GENERIC_NOTE + EXTRA_NOTES.get(name, "")
            rewritten = insert_note(rewritten, note)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(rewritten, encoding="utf-8", newline="\n")
        hits = {tool for tool in tool_to_prefixed(mapping) if tool in original}
        found.extend(f"{tool}:{rel.name}" for tool in sorted(hits))
    return found


def check_clean(
    skills_dir: Path,
    mapping: dict[str, list[str]],
    *,
    expected_files: set[str] | None = None,
) -> list[str]:
    leftovers: list[str] = []
    actual_files = {
        path.relative_to(skills_dir).as_posix() for path in skills_dir.rglob("*") if path.is_file()
    }
    if expected_files is not None:
        for rel in sorted(expected_files - actual_files):
            leftovers.append(f"{skills_dir / rel}: generated file is missing")
        for rel in sorted(actual_files - expected_files):
            leftovers.append(f"{skills_dir / rel}: stale generated file remains")
    for rel in sorted(skills_dir.rglob("*")):
        if not rel.is_file():
            continue
        text = rel.read_text(encoding="utf-8")
        if _LEGACY_PREFIX_RE.search(text):
            leftovers.append(f"{rel}: legacy poe_*_mcp__ prefix remains")
        if _LEGACY_SERVER_RE.search(text) or _LEGACY_WILDCARD in text:
            leftovers.append(f"{rel}: bare poe_*_mcp server reference remains")
        prefixed = tool_to_prefixed(mapping)
        for tool, full in prefixed.items():
            if boundary_re(tool).search(text):
                leftovers.append(f"{rel}: bare MCP tool name remains: {tool}")
            # A prefixed tool name must never appear with a double prefix.
            if full + full in text:
                leftovers.append(f"{rel}: doubled prefix for {tool}")
    return leftovers


def expected_skill_files(source: Path) -> set[str]:
    expected: set[str] = set()
    for name in sorted(EXTRA_NOTES):
        skill_dir = source / name
        if not skill_dir.is_dir():
            raise SystemExit(f"missing source skill: {skill_dir}")
        for path in skill_dir.rglob("*"):
            if path.is_file() and path.parent.name != "agents":
                expected.add(path.relative_to(source).as_posix())
    return expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_SKILLS, help="source skills dir")
    parser.add_argument("--out", type=Path, default=OUT_SKILLS, help="output skills dir")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify an existing output tree instead of rewriting",
    )
    parser.add_argument(
        "--delete-out", action="store_true", help="remove the output dir before writing"
    )
    args = parser.parse_args(argv)

    mapping = load_tool_names()
    expected_files = expected_skill_files(args.source)
    if args.check:
        problems = check_clean(args.out, mapping, expected_files=expected_files)
        if problems:
            print("\n".join(problems))
            return 1
        print(f"OK: {args.out} is clean")
        return 0

    if args.delete_out and args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True, exist_ok=True)

    summary: list[str] = []
    for name in sorted(EXTRA_NOTES):
        skill_dir = args.source / name
        if not skill_dir.is_dir():
            raise SystemExit(f"missing source skill: {skill_dir}")
        found = adapt_skill(name, mapping, source=args.source, skill_dir=skill_dir, out=args.out)
        summary.append(f"{name}: {len(found)} tool-name references rewritten")
        for hit in found:
            print(f"  {hit}")

    problems = check_clean(args.out, mapping, expected_files=expected_files)
    if problems:
        print("\n".join(problems))
        return 1
    print("\n".join(summary))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
