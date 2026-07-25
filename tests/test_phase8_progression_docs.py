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

    for text in (phase, schemas, guide, progression_reference):
        assert "StarterResearchPacket" in text
        assert "TransitionBridge" in text
        assert "stageId" in text
        assert "价格" in text or "Price" in text or "price" in text
    assert "progression-mode.md" in skill
    assert "默认 4" in phase or "默认四" in progression_reference
    assert "最多 5" in progression_reference or "最多五" in progression_reference
    assert "limited_offline_inference" in guide
    assert "targetArtifactId" in schemas
    assert "v1 route" in schemas
    assert "Blind Create" in guide
    assert "starter cache" in guide


def test_manifest_advertises_phase8_tool_surface_and_release_version():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    names = {item["name"] for item in manifest["tools"]}
    assert manifest["version"] == "0.1.40"
    assert {
        "start_build_progression",
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
        "get_build_progression_status",
        "classify_build_progression_costs",
        "finalize_build_progression",
        "export_build_progression_package",
    } <= names
    from server.main import mcp

    assert names == {tool.name for tool in asyncio.run(mcp.list_tools())}
