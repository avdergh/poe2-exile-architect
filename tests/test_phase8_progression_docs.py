from __future__ import annotations

import asyncio
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_phase8_docs_and_runtime_guide_define_progression_mode():
    phase = (ROOT / "docs" / "phases" / "08_build_progression.md").read_text(encoding="utf-8")
    schemas = (ROOT / "docs" / "SCHEMAS.md").read_text(encoding="utf-8")
    guide = (ROOT / "server" / "ASSISTANT_GUIDE.md").read_text(encoding="utf-8")
    skill = (ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-create" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    progression_reference = (
        ROOT
        / "poe-bd-creator-plugin"
        / "skills"
        / "poe-bd-create"
        / "references"
        / "progression-mode.md"
    ).read_text(encoding="utf-8")
    writing_reference = (
        ROOT
        / "poe-bd-creator-plugin"
        / "skills"
        / "poe-bd-create"
        / "references"
        / "progression-writing.md"
    ).read_text(encoding="utf-8")

    for text in (phase, schemas, guide, progression_reference):
        assert "StarterResearchPacket" in text
        assert "TransitionBridge" in text
        assert "stageId" in text
        assert "价格" in text or "Price" in text or "price" in text
        assert "stage_complete_loadout" in text
        assert "complete_stage_build" in text
        assert "single_initialization_then_function_scoped_deltas" in text
        assert "blueprint_declared_or_versioned_replan_only" in text
        assert "rebuildReason" in text
        assert "diagnostic_only" in text
        assert "endgame_minimums_60_30" in text
        assert "minimal_mechanism_shell" not in text
    for text in (phase, schemas, guide, progression_reference, skill):
        assert "mechanism_shell" in text
        assert "passive_delta" in text
        assert "outputStateHash" in text
    assert "progression-mode.md" in skill
    assert "progression-writing.md" in skill
    for text in (phase, schemas, guide, skill, progression_reference, writing_reference):
        assert "playerGuide" in text
    assert "mechanicExplanation" in writing_reference
    assert "levelingSteps" in writing_reference
    assert "commonProblems" in writing_reference
    assert "技术验证附录" in phase
    assert "默认 4" in phase or "默认四" in progression_reference
    assert "最多 5" in progression_reference or "最多五" in progression_reference
    assert "limited_offline_inference" in guide
    assert "targetArtifactId" in schemas
    assert "v1 route" in schemas
    assert "Blind Create" in guide
    assert "starter cache" in guide
    assert "checkpoint_build_progression_context" in guide
    assert 'detail="resume"' in guide
    assert 'response_profile="create_compact"' in guide
    assert "criticalPremiseDigest" in progression_reference
    for text in (phase, schemas, guide, progression_reference, skill):
        assert 'detail="compact"' in text or "detail=compact" in text
    assert "不设固定摘要、维度查询或 record 深读额度" in phase
    assert "不设固定 Family 摘要、维度查询或 record 深读额度" in progression_reference
    assert "不设固定 Family 摘要、维度查询或 record 深读额度" in skill
    assert "do not impose a fixed summary" in guide
    assert "默认返回量不是候选上限" in phase
    assert "默认返回量不是候选上限" in progression_reference
    assert "不得设置固定候选条数" in skill
    assert "default result count is" in guide
    assert "主动质量收尾" in phase
    assert "主动质量收尾" in skill
    assert "deliberate quality pass" in guide
    assert "orderingRecovery.reviewAlreadyConsumed" in schemas
    assert "stage_running" in schemas
    assert "routeIncomplete=true" in progression_reference
    for text in (phase, schemas, guide, progression_reference, skill):
        assert "familyRecordCoverage" in text
        assert "familyPremiseCatalog" in text
        assert "premiseDecisions" in text or "premise decision" in text
        assert "generationMemoryMode" in text
        assert "unavailable:pending_discovery" in text
        assert "anchor_bound" in text
    assert "familyRecordIndex" in phase
    assert 'detail_level="record"' in progression_reference
    assert "recoveryExportAvailable" in phase
    assert "阻塞式入口确认" in progression_reference
    assert "附带开荒策略" in progression_reference
    assert "调用任何工具前必须先确认" in phase
    for text in (phase, guide, progression_reference, skill):
        assert "精魂" in text or "Spirit" in text
        assert "保留" in text or "reservation" in text
        assert "软" in text or "soft design" in text
    assert "来源未提及不等于" in phase
    assert "不应只列一个主技能" in progression_reference
    assert "不增加固定技能数量" in skill


def test_manifest_advertises_phase8_tool_surface_and_release_version():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    names = {item["name"] for item in manifest["tools"]}
    assert manifest["version"] == "0.1.56"
    assert {
        "start_build_progression",
        "submit_build_progression_target_selection",
        "bind_build_progression_target_anchor",
        "intake_starter_research_packet",
        "submit_build_progression_blueprint",
        "revise_future_build_progression_stages",
        "claim_build_progression_stage",
        "bind_build_progression_stage_run",
        "complete_build_progression_stage",
        "fail_build_progression_stage",
        "retry_build_progression_stage",
        "pause_build_progression",
        "resume_build_progression",
        "checkpoint_build_progression_context",
        "get_build_progression_status",
        "classify_build_progression_costs",
        "finalize_build_progression",
        "export_build_progression_package",
    } <= names
    from server.main import mcp

    assert names == {tool.name for tool in asyncio.run(mcp.list_tools())}
