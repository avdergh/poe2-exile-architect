from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_poe_bd_create_skill_documents_current_p5_boundary():
    skill_path = REPO_ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-create" / "SKILL.md"
    skill = skill_path.read_text(encoding="utf-8")

    assert "name: poe-bd-create" in skill
    assert "# /poe-bd-create" in skill
    assert "Agent 主导" in skill
    assert "当前功能" in skill
    assert "结构化需求摘要" in skill
    assert "构筑经验记忆" in skill
    assert "常用 MCP 工具清单" in skill
    assert "必须通过 MCP 工具调用" in skill
    assert "不能用 PowerShell 搜索仓库文件代替" in skill
    assert "get_freshness_report" in skill
    assert "不能因为没有在界面中" in skill
    assert 'decision="blocked_stale"' in skill
    assert "不等于停止生成" in skill
    assert "过期 PoB 有限证据" in skill
    assert "只填原始版本号/commit" in skill
    assert 'qualityBand="strong"' in skill
    assert 'rewardStrength="limited"' in skill
    assert "start_generation_run" in skill
    assert "runContext" in skill
    assert "禁止复用/改写其他运行的旧" in skill
    assert "query_research_memory" in skill
    assert 'detail_level="summary"' in skill
    assert 'detail_level="record"' in skill
    assert 'response_profile="create_compact"' in skill
    assert "criticalPremiseDigest" in skill
    assert "ascendancy_key" in skill
    assert "primary_skill_key" in skill
    assert "build_family_keys" in skill
    assert "record_kinds" in skill
    assert "recordKindCounts" in skill
    assert "supportPackages" in skill
    assert "gearResponsibilities" in skill
    assert "ascendancyResponsibilities" in skill
    assert "resourceMechanisms" in skill
    assert "buildFamilies" in skill
    assert "deepResearchRecords" in skill
    assert "buildPatterns" in skill
    assert "selectedKnowledgeScope" in skill
    assert "selectedSourceCaseRef" in skill
    assert "continuation_cursor" in skill
    assert "case_observation" in skill
    assert "researchMemoryUse" in skill
    assert 'retrievalOutcome="no_matching_memory"' in skill
    assert "insightDecisions" in skill
    assert "role=unique_enabler" in skill
    assert "optional_upgrade" in skill
    assert "budget_substitute" in skill
    assert "requiredInsightDecisionSubjects" in skill
    assert "subjectRef" in skill
    assert "价格不能成为拒绝理由" in skill
    assert "价格不能成为拒绝理由" in skill
    assert "apply_next_jewel_socket_decision" in skill
    assert "protected_node_ids" in skill
    assert "selected_mod_ids" in skill
    assert "全部当前可达槽" in skill
    assert "最近额外孔" not in skill
    assert "最多两轮" not in skill
    assert "offense_skill_group_index=<最终Judge目标组>" in skill
    assert "当前版本不可用时写 `rejected`" in skill
    assert "adopted / rejected / unavailable" not in skill
    assert "操作简单、造价低" not in skill
    assert "graph_tool_query" in skill
    assert "find_skills" in skill
    assert "find_supports_for" in skill
    assert "explain_mechanic" in skill
    assert "build_advice" in skill
    assert "补丁敏感事实以当前 pinned PoB" in skill
    assert "suggest_build_lifecycle" in skill
    assert "new_build" in skill
    assert "set_class" in skill
    assert "set_skill" in skill
    assert "optimize_supports" in skill
    assert "plan_gear" in skill
    assert "optimize_flask" in skill
    assert "endgame_flask_loadout_incomplete" in skill
    assert "evaluate_build" in skill
    assert "apply_build_mutation_batch" in skill
    assert "mechanism_shell" in skill
    assert "passive_delta" in skill
    assert "recoveryRequired=true" in skill
    assert "inspect_generation_checkpoint" in skill
    assert "evaluate_generation_candidate" in skill
    assert "strict_mode=false" in skill
    assert "strict_mode=true" in skill
    assert "feedbackMode" in skill
    assert "hard_only" in skill
    assert "不要用" in skill
    assert "冒充正式 Judge" in skill
    assert "材料可进入人工验收" in skill
    assert "agent-output.json" in skill
    assert "agentRefinedBuildPrompt" in skill
    assert "prototypeBuildCandidate" in skill
    assert "Agent 提交的顶层字段" in skill
    assert "最终选中 attempt 的完整候选摘要" in skill
    assert "baseline_acceptance_audit_required" in skill
    assert "currentOutputStages" in skill
    assert "targetLifecycleStages" in skill
    assert "crossStageLockedDimensions" in skill
    assert "transientBuildState" in skill
    assert "testedSkillGroups" in skill
    assert "judgeAdvisoryReport" in skill
    assert "toolFeedbackEvents" in skill
    assert "给用户看的内容" in skill
    assert "提交给运行工具的内部对象" in skill
    assert "不能换职业" in skill
    assert "complete_generation_review" in skill
    assert "poe_ninja_pob" in skill
    assert "publicExternalUpload=true" in skill
    assert "validate_generation_output" in skill
    assert "lifecycleEvidenceCoverage" in skill
    assert "HumanReviewPacket" in skill
    assert "referenceBlind=true" in skill
    assert "不要搜索仓库" in skill
    assert "隐藏思维链" in skill
    assert "完整对话记录" in skill
    assert "技能组合、辅助组合、装备槽位摘要、天赋锚点或转型路线" in skill
    assert "必须串行调用" in skill
    assert "不接触活动构筑的" in skill
    assert "设计判断" in skill
    assert "工具验证结论" in skill
    assert "完整技能连接" not in skill
    assert "P5" not in skill
    assert "程序化解释器" not in skill
    assert "旧的" not in skill
    assert "强奖励" not in skill
    assert "Architect" not in skill


def test_phase5_guides_and_manifests_advertise_create_current_p5_boundary():
    phase5 = (REPO_ROOT / "docs" / "phases" / "05_generation.md").read_text(encoding="utf-8")
    guide = (REPO_ROOT / "server" / "ASSISTANT_GUIDE.md").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "/poe-bd-create" in phase5
    assert "P5.1 第一阶段原型" in phase5
    assert "HumanReviewPacket" in phase5
    assert "complete_generation_review" in phase5
    assert "start_generation_run" in phase5
    assert "不因为 Agent 自己生成了具体" in phase5
    assert "生命周期工具只保证阶段路线" in phase5
    assert "testedSkillGroups" in phase5
    assert "真实活动构筑" in phase5
    assert "可信凭据" in phase5
    assert "独立 Judge" in phase5
    assert "evaluate_generation_candidate" in phase5
    assert "strict_mode=false" in phase5
    assert "apply_build_mutation_batch" in phase5
    assert "required_gear" in phase5
    assert "rolledBack=true" in phase5
    assert "inspect_generation_checkpoint" in phase5
    assert "保存 artifact" in phase5
    assert "review marker" in phase5
    assert "diagnostic_only" in phase5
    assert "validate_generation_output" in phase5
    assert "LifecycleEvidenceCoverage" in phase5
    assert "设计判断和工具验证结论" in phase5
    assert "## Canonical build (create → optimize → validate → cost → present)" not in guide
    assert "`points=0` fills the budget" not in guide
    assert "optimize_passives(points<=0)" not in guide
    assert 'Open-ended "strong build" / "beginner-friendly endgame"' not in guide
    assert "run the **lifecycle workflow first**" not in guide
    assert "start with `suggest_build_lifecycle`" not in guide
    assert "Route user-triggered Create through `/poe-bd-create`" in guide
    assert not (REPO_ROOT / "docs" / "phases" / "05_create_judge_optimization.md").exists()
    assert "ResearchMemoryUse" in (REPO_ROOT / "docs" / "SCHEMAS.md").read_text(encoding="utf-8")
    assert "familyRecordCoverage" in phase5
    assert "familyRecordIndex" in phase5
    assert "familyPremiseCatalog" in phase5
    assert "premiseDecisions" in phase5
    assert 'detail_level="record"' in phase5
    assert "no_matching_memory" in phase5
    assert "/poe-bd-create" in guide
    assert "Agent-led prototype" in guide
    assert "complete_generation_review" in guide
    assert "start_generation_run" in guide
    assert "must not reject them merely because" in guide
    assert "every PoB/compute tool sequentially" in guide
    assert "testedSkillGroups" in guide
    assert "evaluate_generation_candidate" in guide
    assert "strict_mode=false" in guide
    assert "hard-only" in guide
    assert "apply_build_mutation_batch" in guide
    assert "Do not mix the whole build into one transaction" in guide
    assert "recoveryRequired=true" in guide
    assert "`rolledBack=true`" in guide
    assert "inspect_generation_checkpoint" in guide
    assert "protected_node_ids" in guide
    assert "every currently reachable empty socket" in guide
    assert "Do not stop on a fixed round or jewel count" in guide
    assert "read back for diagnostics" in guide
    assert "validate_generation_output" in guide
    assert "lifecycleEvidenceCoverage" in guide
    assert "trusted receipt" in guide
    assert "progressive research recall" in guide
    assert "directly generates the requested target-level endgame build" in guide
    assert "no blocking leveling-progression question" in guide
    assert "recordKindCounts" in guide
    assert "successful component resolution proves existence" in guide
    assert 'response_profile="create_compact"' in guide
    assert "researchMemoryUse" in guide
    assert "physical graph, and corpus override patch-sensitive prose" in guide
    assert "use `optimize_flask` to create a legal Magic target" in guide
    assert "because it is expensive or because the user supplied a budget" in guide
    assert "价格只在方案锁定后披露，不参与采用" in phase5
    assert "清图/Boss/生存/造价/上限" not in phase5
    assert "/poe-bd-create" in readme
    assert "poe-bd-creator-plugin/skills/poe-bd-create/SKILL.md" in readme
    for internal_contract in (
        "complete_generation_review",
        "start_generation_run",
        "strict_mode=false",
        "evaluate_generation_candidate",
    ):
        assert internal_contract not in readme
    assert "## 脚本入口" not in readme
    assert "## 插件发布数据" not in readme
    assert "docs/PROJECT_SPEC.md" in readme
    assert "docs/SCHEMAS.md" in readme
    assert "docs/phases/" in readme

    for manifest in (
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
        ".cursor-plugin/plugin.json",
        ".copilot-plugin/plugin.json",
    ):
        payload = json.loads((REPO_ROOT / manifest).read_text(encoding="utf-8"))
        assert payload["skills"] == "./poe-bd-creator-plugin/skills/"
        assert "poe-bd-create" in json.dumps(payload)


def test_installers_fallback_uninstall_knows_all_product_skills():
    ps1 = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    sh_lines = {line.strip() for line in sh.splitlines()}

    assert (
        "@('poe-bd-research', 'poe-bd-research-worker', 'poe-bd-create', 'poe-bd-research-loop', "
        "'poe-bd-learning-loop')" in ps1
    )
    assert "printf '%s\\n' \"poe-bd-research\"" not in sh_lines
    assert (
        'printf \'%s\\n\' "poe-bd-research" "poe-bd-research-worker" "poe-bd-create" "poe-bd-research-loop" '
        '"poe-bd-learning-loop"' in sh
    )


def test_installers_register_poe2_mcp_server_for_supported_hosts():
    ps1 = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Register-Codex-McpServer" in ps1
    assert "Resolve-UvCommand" in ps1
    assert "MCP installation requires uv" in ps1
    assert '"[mcp_servers.$($server.Name)]"' in ps1
    assert 'args = @("run", "python", "-m", "server.main")' not in ps1
    assert "$server.Module" in ps1
    assert "@('run', 'python', '-m', $server.Module)" in ps1
    assert "-RegisterMcpOnly" in ps1
    assert "$RepoDir = $ScriptRepoDir" in ps1
    assert "register_codex_mcp_server" in sh
    assert "resolve_uv_command" in sh
    assert "MCP installation requires uv" in sh
    assert "[mcp_servers.poe_build_mcp]" in sh
    assert 'args = ["run", "python", "-m", "server.main"]' not in sh
    assert '"run", "python", "-m", "server.mcp.knowledge_server"' in sh
    assert "--register-mcp-only" in sh
    assert 'REPO_DIR="$SCRIPT_DIR"' in sh
    assert "Codex、Claude Code、Cursor 和 OpenCode" in readme
    assert "两者都不存在时会明确停止" in readme
    assert "poe_knowledge_mcp" in readme
    assert "poe_build_mcp" in readme

    for marker in ("claude", "cursor", "opencode"):
        assert marker in ps1
        assert marker in sh
    assert "configure_agent_host.py" in ps1
    assert "configure_agent_host.py" in sh
    assert "poe-bd-research-loop" in ps1
    assert "poe-bd-learning-loop" in ps1
    assert (
        "$PortableSkills = @('poe-bd-research', 'poe-bd-research-worker', 'poe-bd-create')" in ps1
    )
    assert 'PORTABLE_SKILLS="poe-bd-research poe-bd-research-worker poe-bd-create"' in sh
    assert "Assert-ResearchSkillPair" in ps1
    assert "validate_research_skill_pair" in sh
    assert "must both exist" in ps1
    assert "must both exist" in sh


def test_phase5_distribution_includes_generation_runtime_contracts():
    bundle_builder = (REPO_ROOT / "scripts" / "build_bundle.py").read_text(encoding="utf-8")
    manifest = json.loads((REPO_ROOT / "manifest.json").read_text(encoding="utf-8"))
    tool_names = {tool["name"] for tool in manifest["tools"]}

    assert 'ROOT / "data" / "compatibility" / "pob.json"' in bundle_builder
    assert {
        "get_freshness_report",
        "query_research_memory",
        "graph_tool_query",
        "suggest_build_lifecycle",
        "apply_build_mutation_batch",
        "inspect_generation_preflight",
        "inspect_generation_checkpoint",
        "evaluate_generation_candidate",
    }.issubset(tool_names)
