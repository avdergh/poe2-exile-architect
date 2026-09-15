from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_poe_bd_create_skill_documents_current_p5_boundary():
    from skill_document_helpers import read_skill_documents

    skill_dir = REPO_ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-create"
    documents = read_skill_documents(skill_dir)
    entrypoint = documents["SKILL.md"]
    assert "name: poe-bd-create" in entrypoint
    # The workflow is usable from the installed entrypoint, without repository-only docs.
    assert set(documents) == {
        path.relative_to(skill_dir).as_posix() for path in skill_dir.rglob("*.md")
    }
    content = "\n".join(documents.values())
    for tool in (
        "start_generation_run", "record_generation_family_discovery",
        "construct_research_execution_contract", "validate_generation_blueprint",
        "validate_generation_draft", "inspect_generation_checkpoint",
        "evaluate_generation_candidate", "save_final_build_artifact",
        "verify_lifecycle_stage", "validate_generation_output",
        "complete_generation_review", "submit_learning_create_result",
    ):
        assert tool in content
    for mode in ("referenceBlind=true", "--no-memory", "strict_mode=false", "strict_mode=true"):
        assert mode in entrypoint
    assert "starter-research" in documents["references/blind-mode.md"]
    assert "starter cache" in documents["references/blind-mode.md"]
    assert "联网开荒证据" in documents["references/blind-mode.md"]


def test_create_submission_reference_covers_current_failure_enums():
    from typing import get_args
    from server.generation import models

    reference = (
        REPO_ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-create"
        / "references" / "output-contract.md"
    ).read_text(encoding="utf-8")
    # These enums are needed because start-run intentionally does not invent audit content.
    for model, field in ((models.FailureAuditSummary, "classification"), (models.ToolFeedbackEvent, "feedback_type")):
        values = get_args(model.model_fields[field].annotation)
        assert values
        for value in values:
            assert value in reference


def test_phase5_guides_and_manifests_advertise_create_current_p5_boundary():
    phase5 = (REPO_ROOT / "docs" / "phases" / "05_generation.md").read_text(encoding="utf-8")
    guide = (REPO_ROOT / "server" / "ASSISTANT_GUIDE.md").read_text(encoding="utf-8")
    guide = " ".join(guide.split())
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
    assert "Successful component resolution proves existence" in guide
    assert 'response_profile="create_compact"' in guide
    assert "researchMemoryUse" in guide
    assert "physical graph, and corpus override patch-sensitive prose" in guide
    assert "use `optimize_flask` to create a legal Magic target" in guide
    assert "because it is expensive or because the user supplied a budget" in guide
    # Workflow details remain reachable from the installed skill, not duplicated in this index.
    for reference in (
        "research-use.md", "mechanism-blueprint.md", "build-and-refine.md",
        "validation-and-recovery.md", "output-contract.md", "delivery.md", "blind-mode.md",
    ):
        assert reference in guide
    assert "execute the internal script" not in guide
    assert "import_build` a known PoB and copy its archetype" not in guide
    assert "formal evaluation still ends with" not in guide
    assert guide.index("| Prepare design |") < guide.index("| Validate implementation |")
    assert guide.index("| Preserve final candidate |") < guide.index("| Verify saved artifact |")
    assert guide.index("| Verify saved artifact |") < guide.index("| Validate and consume final submission |")
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
        "@('poe-bd-research', 'poe-bd-research-worker', 'poe-bd-create', 'poe-bd-learn', 'poe-bd-research-loop', "
        "'poe-bd-learning-loop')" in ps1
    )
    assert "printf '%s\\n' \"poe-bd-research\"" not in sh_lines
    assert (
        'printf \'%s\\n\' "poe-bd-research" "poe-bd-research-worker" "poe-bd-create" "poe-bd-learn" "poe-bd-research-loop" '
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
    # Host names and the required runtime remain checkable across README languages.
    for host in ("Codex", "Claude Code", "Cursor", "OpenCode"):
        assert host in readme
    assert "uv" in readme
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
        "$PortableSkills = @('poe-bd-research', 'poe-bd-research-worker', 'poe-bd-create', 'poe-bd-learn')" in ps1
    )
    assert 'PORTABLE_SKILLS="poe-bd-research poe-bd-research-worker poe-bd-create poe-bd-learn"' in sh
    assert "Assert-ResearchSkillPair" in ps1
    assert "validate_research_skill_pair" in sh
    assert "must both exist" in ps1
    assert "must both exist" in sh


def test_phase5_distribution_includes_generation_runtime_contracts():
    bundle_builder = (REPO_ROOT / "scripts" / "build_bundle.py").read_text(encoding="utf-8")
    manifest = json.loads((REPO_ROOT / "manifest.json").read_text(encoding="utf-8"))
    tool_names = {tool["name"] for tool in manifest["tools"]}

    assert 'ROOT / "data" / "compatibility"' in bundle_builder
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
