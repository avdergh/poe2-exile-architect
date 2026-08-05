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
    assert "MCP tool 名称" in skill
    assert "通过宿主提供的 MCP 工具调用" in skill
    assert "不是 Python 函数调用" in skill
    assert "get_freshness_report" in skill
    assert "不能因为没有在界面中" in skill
    assert 'decision="blocked_stale"' in skill
    assert "不能因此停止生成" in skill
    assert "过期 PoB 有限证据" in skill
    assert "只填写原始版本号或 commit" in skill
    assert 'qualityBand="strong"' in skill
    assert 'rewardStrength="limited"' in skill
    assert "start_generation_run" in skill
    assert "runContext" in skill
    assert "禁止读取、复用或改写其他运行留下的" in skill
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
    assert "semanticEdges" in skill
    assert "case_observation" in skill
    assert "researchMemoryUse" in skill
    assert 'retrievalOutcome="no_matching_memory"' in skill
    assert "insightDecisions" in skill
    assert "graph_tool_query" in skill
    assert "find_skills" in skill
    assert "find_supports_for" in skill
    assert "explain_mechanic" in skill
    assert "build_advice" in skill
    assert "补丁敏感事实以当前 pinned PoB" in skill
    assert "suggest_build_lifecycle" in skill
    assert "不一定给具体技能名" in skill
    assert "new_build" in skill
    assert "set_class" in skill
    assert "set_skill" in skill
    assert "optimize_supports" in skill
    assert "plan_gear" in skill
    assert "evaluate_build" in skill
    assert "apply_build_mutation_batch" in skill
    assert "mechanism_shell" in skill
    assert "passive_delta" in skill
    assert "recoveryRequired=true" in skill
    assert "inspect_generation_checkpoint" in skill
    assert "diagnostic_only" in skill
    assert "evaluate_generation_candidate" in skill
    assert "strict_mode=false" in skill
    assert "strict_mode=true" in skill
    assert "feedbackMode" in skill
    assert "hard_only" in skill
    assert "不要用" in skill
    assert "冒充正式 Judge" in skill
    assert "人工验收包" in skill
    assert "agent-output.json" in skill
    assert "agentRefinedBuildPrompt" in skill
    assert "prototypeBuildCandidate" in skill
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
    assert "validate_generation_output" in skill
    assert "lifecycleEvidenceCoverage" in skill
    assert "HumanReviewPacket" in skill
    assert "无参数" in skill
    assert "否则必须先问" in skill
    assert "是否产出开荒过程 BD" in skill
    assert "只产出一个固定目标 BD" in skill
    assert "在用户回答前" in skill
    assert "不得调用 freshness" in skill
    assert "用户已经在当前对话中回答过" in skill
    assert "referenceBlind=true" in skill
    assert "普通用户不需要仓库" in skill
    assert "不要搜索仓库" in skill
    assert "managed_user_data" in skill
    assert "模型隐藏思维链" in skill
    assert "完整对话记录" in skill
    assert "技能组合、辅助组合、装备槽位摘要、天赋锚点或转型路线" in skill
    assert "不会因为一个候选和常见强机制相似就判定失败" in skill
    assert "所有 PoB/计算工具都必须串行调用" in skill
    assert "不接触共享临时构筑状态" in skill
    assert "设计判断" in skill
    assert "工具验证结论" in skill
    assert "完整技能连接" not in skill
    assert "bind_build_progression_target_run" in skill
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
    assert "diagnostic_only" in guide
    assert "validate_generation_output" in guide
    assert "lifecycleEvidenceCoverage" in guide
    assert "trusted receipt" in guide
    assert "progressive research recall" in guide
    assert "Before any ordinary `/poe-bd-create` tool call" in guide
    assert "one fixed target/final build without progression" in guide
    assert "Do not call freshness, Research" in guide
    assert "recordKindCounts" in guide
    assert "successful component resolution proves existence" in guide
    assert 'response_profile="create_compact"' in guide
    assert "researchMemoryUse" in guide
    assert "physical graph, and corpus override patch-sensitive prose" in guide
    assert "/poe-bd-create" in readme
    assert "Phase 5 Agent 主导生成原型" in readme
    assert "complete_generation_review" in readme
    assert "start_generation_run" in readme
    assert "不依赖仓库 checkout" in readme
    assert "strict_mode=false" in readme
    assert "evaluate_generation_candidate" in readme

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
        "@('poe-bd-research', 'poe-bd-create', 'poe-bd-research-loop', "
        "'poe-bd-learning-loop')" in ps1
    )
    assert "printf '%s\\n' \"poe-bd-research\"" not in sh_lines
    assert (
        'printf \'%s\\n\' "poe-bd-research" "poe-bd-create" "poe-bd-research-loop" '
        '"poe-bd-learning-loop"' in sh
    )


def test_installers_register_poe2_mcp_server_for_supported_hosts():
    ps1 = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Register-Codex-McpServer" in ps1
    assert "Resolve-UvCommand" in ps1
    assert "MCP installation requires uv" in ps1
    assert "[mcp_servers.poe2_build_mcp]" in ps1
    assert 'args = @("run", "python", "-m", "server.main")' in ps1
    assert "-RegisterMcpOnly" in ps1
    assert "$RepoDir = $ScriptRepoDir" in ps1
    assert "register_codex_mcp_server" in sh
    assert "resolve_uv_command" in sh
    assert "MCP installation requires uv" in sh
    assert "[mcp_servers.poe2_build_mcp]" in sh
    assert 'args = ["run", "python", "-m", "server.main"]' in sh
    assert "--register-mcp-only" in sh
    assert 'REPO_DIR="$SCRIPT_DIR"' in sh
    assert "Codex、Claude Code、Cursor 和 OpenCode" in readme
    assert "两者都不存在时会明确停止" in readme
    assert "poe2_build_mcp" in readme

    for marker in ("claude", "cursor", "opencode"):
        assert marker in ps1
        assert marker in sh
    assert "configure_agent_host.py" in ps1
    assert "configure_agent_host.py" in sh
    assert "poe-bd-research-loop" in ps1
    assert "poe-bd-learning-loop" in ps1
    assert "$PortableSkills = @('poe-bd-research', 'poe-bd-create')" in ps1
    assert 'PORTABLE_SKILLS="poe-bd-research poe-bd-create"' in sh


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
