from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_desktop_research_loop_skill_has_visible_task_contract():
    skill_root = REPO_ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-research-loop"
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    metadata = (skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert "name: poe-bd-research-loop" in skill
    for desktop_tool in (
        "list_projects",
        "create_thread",
        "list_threads",
        "read_thread",
        "send_message_to_thread",
        "set_thread_title",
        "navigate_to_codex_page",
    ):
        assert desktop_tool in skill
    for state_tool in (
        "validate_poe_research_plan",
        "claim_next_poe_research_task",
        "record_poe_research_phase_started",
        "record_poe_research_phase_finished",
        "release_poe_research_claim",
        "pause_poe_research",
        "resume_poe_research",
        "get_poe_research_status",
        "retry_poe_research_task",
    ):
        assert state_tool in skill
    assert "model: gpt-5.6-sol" in skill
    assert "thinking: medium" in skill
    assert skill.count("thinking: xhigh") == 3
    assert (
        "/poe-bd-research --limit ${num} 抓 ${level} 级 ${class} 的成熟 BD 样本进行研究"
    ) in skill
    assert "poe-bd-research\\SKILL.md" not in skill
    assert "只使用已安装插件的 `/poe-bd-research` 入口" in skill
    assert "POE_RESEARCH_SUCCEEDED: yes" in skill
    assert "POE_RESEARCH_SUCCEEDED: no" in skill
    assert "research_succeeded=true" in skill
    assert "research_succeeded=false" in skill
    assert "--research-succeeded yes|no" in skill
    assert "完整的 safe review、validation/accept/status 回执" in skill
    assert "不得把完整安全产物降级为只看摘要" in skill
    assert "运行态只能通过 typed Research MCP 查询，不读取或编辑 run 文件" in skill
    assert "不能因为组件成功解析就认为机制解释正确" in skill
    assert (
        "Findings 按严重度优先，给出对应 sourceCaseRef、recordId、patternId 或 artifact 位置"
    ) in skill
    assert "不要把单个语义错误直接扩展成全局硬规则" in skill
    assert (
        "先核实上一步 review 的 findings，不要未经验证直接照单修改。本 turn "
        "进入普通开发修复阶段，不继续 queue、claim 或新增案例的研究入库流程。"
    ) in skill
    assert "优先精确修复错误字段、证据或关系，保留仍然正确的研究成果" in skill
    assert "先写入并验证修正版，再清理被替代的数据" in skill
    assert "实施最小、通用修复，补聚焦回归测试，并运行 quick 验证" in skill
    assert "只重新处理明确受影响的本次 sourceCaseRef" in skill
    assert "不得按具体职业、技能、暗金或单一案例硬编码" in skill
    assert "存在其他有效来源支持的共享数据不得误删" in skill
    assert "完成后分别核对修复、保留和删除的数据，以及数据库实际增量" in skill
    assert "每个写入或更新的修正版都必须做全对象语义闭环复核" in skill
    assert "未逐项验证的旧字段不得原样沿用" in skill
    assert "装备职责还必须区分组件静态文本直接提供的固有职责" in skill
    assert "写入后重新读取完整持久化对象" in skill
    assert ("修复并验证成功的问题精炼记录到 ${notesRoot}/resolved-issues.md") in skill
    assert ("真正未解决的问题才写入 ${notesRoot}/unresolved-issues.md，写入前检查同义条目") in skill
    assert "若 review 没有可执行问题，不修改代码、数据或 notes，直接说明无需修复" in skill
    assert "POE_FIX_DATA_REPAIRED: yes" in skill
    assert "POE_FIX_DATA_REPAIRED: no" in skill
    assert "只有实际写入、更新、重建或替换了修正后仍保留在数据库中的研究数据" in skill
    assert "只复审上一步 Fix 实际修复并保留在数据库中的研究数据" in skill
    assert "对每个修正版重新读取完整持久化对象，检查全对象语义闭环" in skill
    assert "不能只复查 Fix 声称修改的字段" in skill
    assert "如果仍然错误，不再尝试第二次修复" in skill
    assert "${notesRoot}/post-fix-review-issues.md" in skill
    assert "claim --plan '<绝对路径>' --workflow-version 2" in skill
    assert "data_repaired=true" in skill
    assert "data_repaired=false" in skill
    assert "phase=rereview + expected_phase=rereview_pending" in skill
    assert "phase=rereview + expected_phase=rereview_running" in skill
    assert "review一下上面的研究结果和过程" not in skill
    assert "修复上面review发现的明显问题" not in skill
    assert "${notesRoot}/unresolved-issues.md" in skill
    assert "${notesRoot}/resolved-issues.md" in skill
    for desktop_state in (
        "`active`",
        "`idle`",
        "`notLoaded`",
        "`completed`",
        "`interrupted`",
        "`failed`",
        "插入了额外 turn",
    ):
        assert desktop_state in skill
    assert "start_poe_research" not in skill
    assert "wait_poe_research_events" not in skill
    assert "stop_poe_research" not in skill
    assert "worker" not in skill
    assert "JSON 事件" in skill
    assert "scripts/invoke_mcp.py" in skill
    assert "不得编辑 bridge" in skill
    assert "不得复述 child 输出" in skill
    assert "POE_BD_CREATOR_DIR" in skill
    assert "POE_RESEARCH_ORCHESTRATOR_DIR" in skill
    assert "creatorRoot" in skill
    assert "orchestratorRoot" in skill
    assert "notesRoot" in skill
    assert "poe-bd-creator-plugin/skills/poe-bd-research-loop/SKILL.md" in skill
    assert "skills/poe-bd-research-loop/SKILL.md" in skill
    assert "POE_BD_CREATOR_DIR` 指向真实源码 checkout" in skill
    assert "不得全盘搜索或猜测其他路径" in skill
    assert "E:\\poe-bd-creator" not in skill
    assert "E:\\poe-research-orchestrator" not in skill
    assert 'value: "poe_research_orchestrator"' in metadata
    assert "State-only Markdown claims" in metadata
    assert "command:" not in metadata
    assert "args:" not in metadata
    assert "cwd:" not in metadata
    assert "E:\\" not in metadata
    assert "allow_implicit_invocation: false" in metadata


def test_desktop_research_loop_skill_uses_compact_low_churn_monitoring():
    skill = (
        REPO_ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-research-loop" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "`wait_threads` 是首选但非必需的增量等待能力" in skill
    assert "`afterCursor`" in skill
    assert "`timeoutMs=300000`" in skill
    assert "状态未变化时不得发送 commentary" in skill
    assert "list_threads(query=精确任务标题, limit=3)" in skill
    assert "至少间隔 300 秒" in skill
    assert "不得用全量 `list_threads`" in skill
    assert "不得为等待启动 shell sleep、后台进程" in skill
    assert "不报告“仍为 active”“更新时间刷新”“继续等待”" in skill
    assert "不得重复调用 `get_poe_research_status`" in skill


def test_product_readme_and_guides_use_poe_bd_research_entrypoint():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    guide = (REPO_ROOT / "server" / "ASSISTANT_GUIDE.md").read_text(encoding="utf-8")
    guide = " ".join(guide.split())
    controller = (
        REPO_ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-research" / "SKILL.md"
    ).read_text(encoding="utf-8")
    worker_root = REPO_ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-research-worker"
    worker = (worker_root / "SKILL.md").read_text(encoding="utf-8")
    worker_metadata = (worker_root / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert "/poe-bd-research" in readme
    assert "poe-bd-creator-plugin/skills/poe-bd-research/SKILL.md" in readme
    assert "/poe-bd-research" in guide
    assert "$poe-bd-research" in guide
    assert "poe-bd-research-worker" in controller
    assert "allow_implicit_invocation: false" in worker_metadata
    assert "default_prompt" not in worker_metadata
    assert "gearResponsibilities" in worker
    assert 'response_profile="full"' in worker
    assert "sourceSkillGroupReviews" in worker
    assert "rootSkillRef" in worker
    assert "claimScopeReview" in worker
    assert "relevanceReason" in worker
    assert "validate_research_review" in worker
    assert "complete=false" in worker and "nextCursor" in worker
    assert "不能把模型记忆中的免疫、转换、触发或缩放写成已证实事实" in worker
    assert "`enableGlobal1` / `enableGlobal2` 是单颗 gem 的 granted-effect 开关" in worker
    assert "绝不是\n  武器组标志" in worker
    assert "`weaponSetScope` 才是技能组级字段" in worker
    assert "`global` / `weapon_set_1` /\n  `weapon_set_2`" in worker
    assert "不得根据任一 gem 的 global-effect 开关推断武器切换" in worker
    assert "durableWritePreflight.status=permission_required" in worker
    assert "write_handle_ready" in worker and "advisory" in worker
    assert "review_contract_upgrade_required" in worker
    assert "案例仍是 claimed" in worker and "不能改走只处理 rejected 案例的 retry" in worker
    assert "在 typed validation 和正式 accept 前复核每个最终对象" in worker
    assert "initialize_research_review" in guide
    assert "in-memory safe review object" in guide
    # Scheduling is maintained in the installed Controller, not a second GUIDE workflow.
    assert "Controller" in guide and "scheduling" in guide
    assert "poe-bd-research-worker" in controller
    assert "never claims cases or reads case evidence" in guide
    assert "Never delegate a research case to a subagent" not in guide
    assert "开发阶段有意不保留 `README.md`" not in agents
    assert "开发阶段有意不保留 `README.md`" not in claude
    assert "run_phase45_researcher_batch.py --limit" not in guide
    assert "prompt slot" not in guide.lower()
    assert "poe-bd-research" in guide
    assert "before any network crawl" in guide
    assert "Do not ask Codex Desktop users to paste PowerShell/Python commands into the chat box" in guide
    assert "poe-bd-research-worker" in guide
    assert "opaque `runRef`" in guide
    assert "my-build.txt" in readme
    research_usage = readme.split("### Research", maxsplit=1)[1].split("### Create", maxsplit=1)[0]
    # Research input examples stay local; user-approved Create share links are allowed.
    assert "poe.ninja" not in research_usage
    assert "docs/" not in readme
    assert "No-Argument Behavior" in controller
    assert "--resume --run-ref REF" in controller
    assert "普通新任务始终创建独立 run" in controller
    assert "不能覆盖既有 queue" in controller
    assert "runRef" in controller
    assert "plugin cache" in guide
    assert "--class NAME" in controller
    assert "class" in controller and "不得二次编码" in controller
    assert "runtime product workflow" in guide
    assert "query_research_memory" in guide
    assert "search_graph_components" in guide
    assert "resolve_graph_component" in guide
    assert "get_research_review_contract" in guide
    assert "initialize_research_review" in guide
    assert "validate_research_review" in guide
    assert "accept_research_review" in guide
    assert "fullyResolvedForAccept" in guide
    assert "get_research_review_contract" in worker
    assert "从原 run quarantine" in controller and "完全相同的 PoB" in controller
    assert "created+updated >= 1" in controller
    for internal_contract in (
        "scripts/research_mature_builds.py",
        "worker-brief",
        "review-contract --output-dir",
        "accept --validate-only",
        "fullyResolvedForAccept",
        "runDir",
    ):
        assert internal_contract not in readme
    assert "## 开发验证" not in readme


def test_research_controller_and_worker_skills_have_separate_roles():
    controller = (
        REPO_ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-research" / "SKILL.md"
    ).read_text(encoding="utf-8")
    worker_root = REPO_ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-research-worker"
    worker = (worker_root / "SKILL.md").read_text(encoding="utf-8")
    metadata = (worker_root / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert "主会话永不 claim、读取案例证据、编辑 review 或 accept" in controller
    assert "poe-bd-research-worker" in controller
    assert "runRef" in controller
    assert "status.dispatchableCount > 0" in controller
    assert "Research Worker 的业务并发上限仍为 5" in controller
    assert "目标宿主容量是 6 个活动槽位" in controller
    assert "wait_agent(timeout_ms=300000)" in controller
    assert "不得快于 5 分钟" in controller
    assert "待回访队列" in controller
    assert "先用释放的槽位创建全新 Worker" in controller
    assert "两个新 Worker 中连续重复" in controller
    assert "反馈已返回不等于获得 cleanup 授权" in controller
    assert "re_research_run_ref" in controller and "supplement_sample_ids" in controller
    assert "Worker 运行态已经结束" in controller
    assert "POE_RESEARCH_SUCCEEDED: yes" in controller
    assert "claim --output-dir" not in controller
    assert "Researcher Checklist" not in controller
    assert "Mandatory Checks" not in controller

    assert "name: poe-bd-research-worker" in worker
    assert "Internal explicit-only worker" in worker
    assert "worker_assignment_missing" in worker
    assert "researchCliArgv" not in worker
    assert "claim_research_case" in worker
    assert "start_research_run" in controller
    assert "不回退 shell CLI" in controller
    assert "不回退 shell CLI" in worker
    assert "runRef" in worker
    assert "不得自行发现其他仓库、创建/恢复 queue" in worker
    assert "只处理一个 claim" in worker
    assert "sampleId + safe outcome" in worker
    assert "accepted 时附 safe acceptance 摘要" in worker
    assert "`build_family_keys` 只接收查询已返回的 `bf-...`" in worker
    assert '`detail_level="record" + response_profile="full"`' in worker
    assert "retry_research_review" in worker
    assert (
        "accept_research_review(run_ref=<runRef>, lease_token=<leaseToken>, review=<review>)"
        in worker
    )
    assert "adopt_legacy_research_run" not in controller
    assert "不得用 shell/file tool 编辑运行态" in worker
    assert "No-Argument Behavior" not in worker
    assert "--resume" not in worker
    assert "cleanup_completed_task_runtime" not in worker
    assert "allow_implicit_invocation: false" in metadata


def test_document_language_policy_exempts_runtime_prompts():
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "server/ASSISTANT_GUIDE.md" in agents
    assert "server/MCP_BOOTSTRAP.md" in agents
    assert "英文" in agents
    assert "runtime prompt" in agents
    assert "属于语言策略的明确例外" in agents
    assert "不要求翻译或维护 `.CN.md` 副本" in agents


def test_plugin_manifests_are_valid_json_and_point_to_skill_tree():
    for manifest in (
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
        ".cursor-plugin/plugin.json",
        ".copilot-plugin/plugin.json",
    ):
        payload = json.loads((REPO_ROOT / manifest).read_text(encoding="utf-8"))
        assert payload["name"] == "poe-bd-creator"
        assert payload["version"].startswith("0.5.0")
        assert payload["skills"] == "./poe-bd-creator-plugin/skills/"
        assert "agents" not in payload
        assert "TODO" not in json.dumps(payload)

    codex_manifest = json.loads(
        (REPO_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    packaged_codex_manifest = json.loads(
        (REPO_ROOT / "poe-bd-creator-plugin" / ".codex-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    assert codex_manifest["version"] == packaged_codex_manifest["version"]
    assert all(
        "poe-bd-research-worker" not in prompt
        for prompt in codex_manifest["interface"]["defaultPrompt"]
    )
    assert all(
        "poe-bd-research-loop" not in prompt
        for prompt in codex_manifest["interface"]["defaultPrompt"]
    )
    codex_mcp = json.loads((REPO_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert codex_manifest["mcpServers"] == "./.mcp.json"
    assert set(codex_mcp["mcpServers"]) == {
        "poe_knowledge_mcp",
        "poe_build_mcp",
        "poe_research_mcp",
        "poe_learning_mcp",
    }
    for module in (
        "server.mcp.knowledge_server",
        "server.mcp.build_server",
        "server.mcp.research_server",
        "server.mcp.learning_server",
    ):
        server = next(
            s
            for s in codex_mcp["mcpServers"].values()
            if s["args"] == ["run", "python", "-m", module]
        )
        assert server["command"] == "./.tools/uv/uv.exe"
        assert server["cwd"] == "."
        assert server["env"]["PYTHONPATH"] == "."

    codex_bundle = json.loads(
        (REPO_ROOT / "poe-bd-creator-plugin" / ".codex-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    assert codex_bundle["name"] == "poe-bd-creator"
    assert codex_bundle["version"].startswith("0.5.0")
    assert codex_bundle["skills"] == "./skills/"
    assert all(
        "poe-bd-research-worker" not in prompt
        for prompt in codex_bundle["interface"]["defaultPrompt"]
    )
    assert all(
        "poe-bd-research-loop" not in prompt
        for prompt in codex_bundle["interface"]["defaultPrompt"]
    )


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
