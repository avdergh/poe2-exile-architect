from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_product_readme_and_guides_use_poe_bd_research_entrypoint():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    spec = (REPO_ROOT / "docs" / "PROJECT_SPEC.md").read_text(encoding="utf-8")
    guide = (REPO_ROOT / "server" / "ASSISTANT_GUIDE.md").read_text(encoding="utf-8")
    phase4 = (REPO_ROOT / "docs" / "phases" / "04_research_memory.md").read_text(encoding="utf-8")

    assert "/poe-bd-research" in readme
    assert "/poe-bd-research" in guide
    assert "$poe-bd-research" in guide
    assert "/poe-bd-research" in phase4
    assert "$poe-bd-research" in phase4
    assert "scripts/research_mature_builds.py" in readme
    assert "worker-brief" in readme
    assert "worker-brief" in guide
    assert "worker-brief" in phase4
    assert "worker-count" in readme
    assert "并发 Researcher agent lane" in readme
    assert "开发阶段有意不保留 `README.md`" not in agents
    assert "开发阶段有意不保留 `README.md`" not in claude
    assert "Public README 政策" in spec
    assert "安装/自动化 README" in spec
    assert "run_phase45_researcher_batch.py --limit" not in guide
    assert "run_phase45_researcher_batch.py --limit" not in phase4
    assert "prompt slot" not in guide.lower()
    assert "prompt slot" not in phase4.lower()
    assert "poe-bd-research" in guide
    assert "poe-bd-research" in phase4
    assert "先询问运行数量和模式" in readme
    assert "before any network crawl" in guide
    assert "先询问运行数量和模式" in phase4
    assert "不是让你在聊天框里执行 shell 命令" in readme
    assert "Do not ask Codex Desktop" in guide
    assert "users to paste PowerShell/Python commands into the chat box" in guide
    assert "不是要求用户在 Codex 输入框里执行 shell 命令" in phase4
    assert "不能只发本机" in phase4
    assert "Do not send only a local `SKILL.md` path" in guide
    assert "预检 5 个样本" in readme
    assert "preflight 5" in guide
    assert "预检 5 个样本" in phase4
    assert "交互式选择控件" in readme
    assert "interactive choice/confirmation UI" in guide
    assert "小批量" in phase4
    assert "大批量" in phase4
    assert "恢复已有队列" in phase4
    assert "不绑定到 50 个样本" in readme
    assert "must not be tied only to the large-batch option" in guide
    assert "产品运行态" in readme
    assert "runtime product workflow" in guide
    assert "不得修改仓库源码" in phase4
    assert "## 开发验证" not in readme


def test_skill_documents_one_case_worker_semantics():
    skill = (
        REPO_ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-research" / "SKILL.md"
    ).read_text(encoding="utf-8")
    agent = (
        REPO_ROOT / "poe-bd-creator-plugin" / "agents" / "mature-build-researcher.md"
    ).read_text(encoding="utf-8")

    assert "一案一轮" in skill
    assert "worker-count" in skill
    assert "并发 Researcher agent lane 数" in skill
    assert "不是 prompt slot" in skill
    assert "requestedWorkers" in skill
    assert "effectiveWorkers=1" in skill
    assert "运行态" in skill
    assert "不得修改仓库源码" in skill
    assert "不得调用调试/TDD/代码修改类 skill" in skill
    assert "collector_failed" in skill
    assert "source_unavailable" in skill
    assert "--limit 5 --worker-count 1 --dry-run" in skill
    assert "/poe-bd-research --limit 20 --worker-count 5" in skill
    assert "不要在用户选择前联网采样" in skill
    assert "不是在执行 shell 命令" in skill
    assert "不要要求用户把 PowerShell/Python 命令复制到会话框或终端" in skill
    assert "交互式选择/确认工具" in skill
    assert "预检 5 个样本（推荐）" in skill
    assert "小批量提取" in skill
    assert "大批量提取" in skill
    assert "恢复已有队列" in skill
    assert "不要把 `--resume` 只绑定到大批量" in skill
    assert "退化为普通文字选项" in skill
    assert "底层 `scripts/research_mature_builds.py` 命令是 agent 内部实现步骤" in skill
    assert "worker-brief" in skill
    assert "不要把 `SKILL.md` 路径" in skill
    assert "把返回 JSON 里的 `workerPrompt` 原样发给该 worker" in skill
    assert "如果 worker 会话没有暴露这些 MCP tools" in skill
    assert "不应搜索隐藏工具" in skill
    assert "query_research_memory" in agent
    assert "resolver" in agent
    assert "inline `workerPrompt`" in agent
    assert "不要只依赖 `SKILL.md` 路径" in agent
    assert "不要搜索隐藏工具" in agent
    assert "safe review artifact" in agent
    assert "`build_archetype`" in agent
    assert "`variant_relations`" in agent
    assert "不要使用 `BuildArchetypePattern`" in agent
    assert "PoB code" in agent


def test_plugin_manifests_are_valid_json_and_point_to_skill_tree():
    for manifest in (
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
        ".cursor-plugin/plugin.json",
        ".copilot-plugin/plugin.json",
    ):
        payload = json.loads((REPO_ROOT / manifest).read_text(encoding="utf-8"))
        assert payload["name"] == "poe-bd-creator"
        assert payload["version"] == "0.4.5"
        assert payload["skills"] == "./poe-bd-creator-plugin/skills/"
        assert "TODO" not in json.dumps(payload)


def test_installers_support_dry_run_and_refuse_real_directory_overwrite():
    ps1 = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")

    assert "DryRun" in ps1
    assert "Refusing to overwrite" in ps1
    assert "real file/directory" in ps1
    assert "Test-OwnedReparse" in ps1
    assert "link not owned by this installer" in ps1
    assert "--dry-run" in sh
    assert "Refusing to overwrite" in sh
    assert "real file/directory" in sh
    assert "link_owned_by_installer" in sh
    assert "link not owned by this installer" in sh
    assert "skill_list_root" in sh
    assert "POE_BD_CREATOR_REPO_URL" in ps1
    assert "POE_BD_CREATOR_REPO_URL" in sh
