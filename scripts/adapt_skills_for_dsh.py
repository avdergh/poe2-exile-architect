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
`_TOOLS` tuples, so it cannot drift from the real registrations. Two gates fail
the run instead of degrading silently:

- every source skill must be adapted (`EXTRA_NOTES`) or be a recorded exclusion
  (`SKILL_EXCLUSIONS`);
- every literal `POLISH` rule must still match its source sentence, because a
  reworded source skill otherwise leaves un-adapted host text in the output.

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

# Per-skill extra notes appended after the generic note. Research (with its
# explicit worker), create and learning are the three workflows the project
# presents to users; the comparative-learning loop driver ships alongside them
# but is documented as experimental.
EXTRA_NOTES = {
    "poe-bd-learn": """\
> Learning 首要规则是输出语言跟随用户。H5 保留完整讲解，组件名称附精确图标与类别说明；不写 Research 或 Phase 7 Memory。
> `study` 工具按职责分布在 research、knowledge 与 build 三个域；不调用入库工具，不要求 Codex 浏览器。
""",
    "poe-bd-create": """\
> Create 只连接 knowledge + build 两个 server：知识/图/机制/Research 查询走
> `mcp__poe_knowledge__*`，所有 PoB/计算/Judge 工具走 `mcp__poe_build__*`。
> 所有 PoB/计算工具共享同一个活动构筑、必须串行调用；只有不接触活动构筑的
> 语料/图/机制/静态查询可以并行。
""",
    "poe-bd-research": """\
> **DSH 映射**：Controller 用 `subagent` 后台启动显式
> `poe-bd-research-worker`，等待后台结算，并用 `send_message` 续聊回访。
> queue、status 与 cleanup 使用 `mcp__poe_research__*` typed 工具；不得回退 shell。
> 每个 Research Worker 的 assignment 必须携带 opaque runRef、用户原始研究请求和授权上下文。
""",
    "poe-bd-research-worker": """\
> **DSH Worker**：只允许 Controller 显式用 `skill` 工具加载本 skill；从 assignment
> 取得 opaque runRef 后使用 `mcp__poe_research__*` typed 工具执行单案流程，不使用 shell，
> 不创建或恢复 queue。assignment 必须包含用户原始研究请求和授权上下文。
""",
    "poe-bd-learning-loop": """\
> **DSH 映射（重要）**：Codex Desktop 任务原语（`create_thread` /
> `send_message_to_thread` / `wait_threads` 等）在 DSH 中不存在。对应关系：
> 可见任务 → DSH 子代理（`subagent` / `subagent_fork`，默认后台运行）+
> `send_message` 推进阶段；等待 → 子代理后台结算通知；`$poe-bd-create` →
> 加载 `poe-bd-create` skill。任务初始化/恢复语义（不创建重复任务、不重放
> 已消费阶段）保持不变。
""",
}

# Source skills this adapter deliberately never generates, with the reason.
# Everything else in the source tree must appear in EXTRA_NOTES or here, so a
# newly added host skill cannot be dropped from the preset silently.
SKILL_EXCLUSIONS = {
    "poe-bd-research-loop": (
        "Codex Desktop loop driver (resolves its own SKILL.md path and drives visible "
        "threads); DSH uses the poe-bd-research controller with an explicit worker"
    ),
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
#
# These rules carry the host mapping the mechanical pass cannot express: Codex
# Desktop task primitives, and sentences that read as a host config key rather
# than a DSH tool namespace. `polish_problems` fails the run when a rule stops
# matching its source sentence, because a silently skipped rule leaves the
# un-adapted host text in the generated tree.
POLISH = {
    "poe-bd-create": [
        (
            "普通Create的知识工具在 `poe-knowledge-mcp`，PoB/计算/Judge在 `poe-build-mcp`；",
            "普通Create的知识工具在 `mcp__poe_knowledge__*`，PoB/计算/Judge在 `mcp__poe_build__*`；",
        ),
    ],
    "poe-bd-research": [
        (
            "必须 fork 包含用户本次研究请求/授权的最近上下文；不得使用 `fork_turns=none`。Subagent 继承父任务\n"
            "  权限模式，但用户授权上下文仍需可见，不能只由 Controller 转述。",
            "必须用 `subagent` 后台派发并在 assignment 中携带用户本次研究请求/授权上下文；\n"
            "  不得创建缺少父任务信息的空上下文 Worker，也不能只由 Controller 转述授权。",
        ),
        (
            "- Worker 运行期间使用宿主的事件等待原语；Codex 使用 `wait_agent(timeout_ms=300000)`。Worker\n"
            "  完成或需要关注时由邮箱事件提前唤醒，不忙轮询。\n"
            "- 300 秒超时且状态无变化时，不查询 queue status；最多发送一条简短心跳后继续下一个\n"
            "  300 秒等待窗口。无变化心跳不得快于 5 分钟，不重复枚举相同的 Worker/lease 状态。\n"
            "- 只有 Worker 返回、发生 safe error、需要补位/验收恢复，或用户主动询问状态时才立即唤醒并查询\n"
            "  status。心跳不是 status 轮询授权。",
            "- Worker 运行期间依赖 DSH `subagent` 的后台结算通知，不调用 Codex `wait_agent`，也不忙轮询。\n"
            "- 只有 Worker 结算、发生 safe error、需要补位/验收恢复，或用户主动询问状态时才查询 status；\n"
            "  无变化时不发送心跳或重复枚举相同 Worker/lease。",
        ),
    ],
    "poe-bd-learning-loop": [
        (
            "这是 Desktop 可见的 BD 对照学习控制器。",
            "这是由 DSH 子代理驱动的 BD 对照学习控制器。",
        ),
        (
            "## 可见任务初始化",
            "## 子代理初始化",
        ),
        (
            "一个案例使用两个任务：",
            "一个案例使用两个 DSH 子代理（`subagent` 的 `description` 写下列名称）：",
        ),
        (
            "使用 Desktop `create_thread` 时先发送短初始化提示，让新任务只输出\n"
            "`POE_LEARNING_READY: yes`，不接触来源、不执行分析。取得真实 threadId/hostId 后：\n"
            "\n"
            "1. 调用 `mcp__poe_learning__claim_learning_phase` 绑定真实 taskId/threadId；\n"
            "2. 再用 `send_message_to_thread` 发送包含 claimId 的阶段提示；\n"
            "3. 通过 `wait_threads` 等待该阶段结束。\n"
            "\n"
            "这样避免在任务 ID 尚未知时提前执行。Reference 与 Create 的 taskId 和 threadId 必须不同；Compare、\n"
            "Learn、rereview 必须复用 Reference 任务。创建后设置上述标题并导航到新任务，让用户可见。",
            "用 `subagent` 后台派发只回答 `POE_LEARNING_READY: yes`、不接触来源也不执行分析的初始化子代理，\n"
            "拿到持久 agent id 后：\n"
            "\n"
            "1. 调用 `mcp__poe_learning__claim_learning_phase`，把该 agent id 同时作为 `task_id` 与 `thread_id`；\n"
            "2. 再用 `send_message` 发送包含 claimId 的阶段提示；\n"
            "3. 等该子代理的后台结算通知，不调用 `wait_threads`。\n"
            "\n"
            "这样避免在子代理 id 尚未知时提前执行。Reference 与 Create 必须是两个不同 agent id；Compare、\n"
            "Learn、rereview 必须用 `send_message` 回到同一个 Reference 子代理并传入同一对 id。不要为同一案例\n"
            "重复派发子代理，也不要用空上下文派发取代携带 claimId 的阶段提示。",
        ),
        (
            "- 对单任务使用 `wait_threads`，携带最新 cursor，`timeoutMs=300000`。超时且状态无变化时直接继续\n"
            "  等待，不发送“仍在运行” commentary，不频繁读取任务全文。",
            "- 依赖 DSH `subagent` 的后台结算通知等待阶段结束；不调用 `wait_threads`，也不轮询子代理输出。\n"
            "  不发送“仍在运行” commentary，不频繁读取子代理全文。",
        ),
        (
            "只有用户检查可见任务后才调用",
            "只有用户查看子代理结果后才调用",
        ),
        (
            "分流、correction、耗时和累计趋势。用户可直接打开可见任务查看过程。",
            "分流、correction、耗时和累计趋势。用户可在子代理列表查看该案例的 Reference/Create 子代理及其终态。",
        ),
    ],
}


def mechanical_rewrite(text: str, mapping: dict[str, list[str]]) -> str:
    """Apply the mechanical steps: tool prefixes, legacy prefixes, row ids."""
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
    return _LEGACY_SERVER_RE.sub(r"poe-\1-mcp", text)


def rewrite_text(
    text: str,
    mapping: dict[str, list[str]],
    name: str,
    *,
    applied: list[int] | None = None,
) -> str:
    """Run the mechanical rewrite, then this skill's literal host polish.

    `applied` (when given) records the 1-based index of every POLISH rule that
    matched, which is what `polish_problems` turns into a fail-closed gate.
    """
    text = mechanical_rewrite(text, mapping)
    # 4. Targeted polish for sentences that need DSH phrasing, not row ids.
    for index, (old, new) in enumerate(POLISH.get(name, []), 1):
        if old in text:
            text = text.replace(old, new)
            if applied is not None:
                applied.append(index)
    return text


def polish_problems(source: Path, mapping: dict[str, list[str]]) -> list[str]:
    """Report POLISH rules that no longer match any source sentence.

    A rule that stops matching is a silent host-adapter regression: the source
    skill was reworded and the generated tree keeps the un-adapted (Codex-only)
    wording. `--check` cannot see it any other way, because the leftover text is
    still a valid tool-name shape.
    """
    problems: list[str] = []
    for name, pairs in POLISH.items():
        skill_dir = source / name
        if not skill_dir.is_dir():
            problems.append(f"{skill_dir}: POLISH target skill is missing")
            continue
        applied: list[int] = []
        for path in sorted(skill_dir.rglob("*")):
            if path.is_file():
                rewrite_text(path.read_text(encoding="utf-8"), mapping, name, applied=applied)
        fired = set(applied)
        for index, (old, _new) in enumerate(pairs, 1):
            if index not in fired:
                head = old.splitlines()[0][:60]
                problems.append(
                    f"{skill_dir}: POLISH rule {index} no longer matches its source "
                    f"sentence ({head!r})"
                )
    return problems


def skill_coverage_problems(source: Path) -> list[str]:
    """Report source skills this adapter neither generates nor excludes.

    `expected_skill_files` derives from `EXTRA_NOTES`, so without this check a
    new host skill would be dropped from the DSH preset without a word.
    """
    present = {path.name for path in source.iterdir() if path.is_dir()}
    adapted = set(EXTRA_NOTES)
    excluded = set(SKILL_EXCLUSIONS)
    problems = [
        f"{source / name}: source skill has no DSH adaptation "
        f"(add it to EXTRA_NOTES or SKILL_EXCLUSIONS)"
        for name in sorted(present - adapted - excluded)
    ]
    problems += [
        f"{source / name}: excluded skill no longer exists upstream"
        for name in sorted(excluded - present)
    ]
    problems += [
        f"{source / name}: skill is both adapted and excluded" for name in sorted(adapted & excluded)
    ]
    return problems


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
            if "# 最高优先级 输出语言必须与用户一致" in rewritten:
                # The user's highest-priority language rule must precede host-adapter guidance.
                priority_start = rewritten.index("# 最高优先级 输出语言必须与用户一致")
                next_section = re.search(r"^#{1,2} ", rewritten[priority_start + 1 :], re.M)
                if next_section is None:
                    raise SystemExit("section after language-priority rule is missing")
                pos = priority_start + 1 + next_section.start()
                rewritten = rewritten[:pos] + note + "\n" + rewritten[pos:]
            else:
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
        if rel.as_posix().endswith("poe-bd-research/SKILL.md"):
            for forbidden in (
                "queue 由 DSH shell",
                "`fork_turns=none`",
                "wait_agent(",
                "必须 fork",
            ):
                if forbidden in text:
                    leftovers.append(f"{rel}: stale DSH Research instruction remains: {forbidden}")
        if rel.as_posix().endswith("poe-bd-research-worker/SKILL.md"):
            for forbidden in ("取得 runDir 后用 shell", "`fork_turns=none`"):
                if forbidden in text:
                    leftovers.append(f"{rel}: stale DSH Worker instruction remains: {forbidden}")
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


def prune_stale(out: Path, expected: set[str], *, known_skills: set[str]) -> list[str]:
    """Delete generated files inside known skill dirs that are no longer expected.

    Scoped to the skill names the adapter owns, so a regeneration drops a removed
    skill or reference file without touching anything else in `--out`.
    """
    removed: list[str] = []
    for skill in sorted(known_skills):
        skill_dir = out / skill
        if not skill_dir.is_dir():
            continue
        keep = {rel for rel in expected if rel.startswith(f"{skill}/")}
        for path in sorted(skill_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            rel = path.relative_to(out).as_posix()
            if path.is_file() and rel not in keep:
                path.unlink()
                removed.append(rel)
            elif path.is_dir() and not any(child.is_file() for child in path.rglob("*")):
                path.rmdir()
        if not any(skill_dir.rglob("*")):
            skill_dir.rmdir()
            removed.append(f"{skill}/")
    return removed


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
    # Structural gates run first: a source skill without an adaptation, or a
    # polish rule that no longer matches, must fail before anything is written.
    structural = skill_coverage_problems(args.source) + polish_problems(args.source, mapping)
    expected_files = expected_skill_files(args.source)
    if args.check:
        problems = structural + check_clean(args.out, mapping, expected_files=expected_files)
        if problems:
            print("\n".join(problems))
            return 1
        print(f"OK: {args.out} is clean")
        return 0

    if structural:
        print("\n".join(structural))
        return 1

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

    pruned = prune_stale(
        args.out,
        expected_files,
        known_skills=set(EXTRA_NOTES) | set(SKILL_EXCLUSIONS),
    )
    for rel in pruned:
        print(f"  pruned stale generated path: {rel}")
        summary.append(f"pruned {rel}")

    problems = structural + check_clean(args.out, mapping, expected_files=expected_files)
    if problems:
        print("\n".join(problems))
        return 1
    print("\n".join(summary))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
