from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[1]


def test_phase7_docs_define_comparative_learning_boundary():
    phase = (ROOT / "docs" / "phases" / "07_critic_loop.md").read_text(encoding="utf-8")
    spec = (ROOT / "docs" / "PROJECT_SPEC.md").read_text(encoding="utf-8")
    schemas = (ROOT / "docs" / "SCHEMAS.md").read_text(encoding="utf-8")
    guide = (ROOT / "server" / "ASSISTANT_GUIDE.md").read_text(encoding="utf-8")

    for text in (phase, spec, schemas, guide):
        assert "FamilyTarget" in text
        assert "Learning Memory" in text
    assert "每个案例只调用一次" in phase
    assert "advisoryOnly" in phase
    assert "10 个" in phase
    assert "不运行额外 Holdout" in phase
    assert "Phase 8 多可信阶段 artifact" in spec
    assert "corrected_lesson_requires_new_evidence" in schemas
    assert "$poe-bd-learning-loop" in guide


def test_phase7_runtime_is_packaged_and_has_no_provider_loop():
    bundle = (ROOT / "scripts" / "build_bundle.py").read_text(encoding="utf-8")
    learning_files = list((ROOT / "server" / "learning").glob("*.py"))
    joined = "\n".join(path.read_text(encoding="utf-8") for path in learning_files).casefold()

    assert '"server"' in bundle
    assert "openai" not in joined
    assert "anthropic" not in joined
    assert "requests.post" not in joined


def test_learning_loop_skill_and_plugin_are_discoverable():
    skill = ROOT / "poe-bd-creator-plugin" / "skills" / "poe-bd-learning-loop"
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    openai_yaml = (skill / "agents" / "openai.yaml").read_text(encoding="utf-8")
    plugin = json.loads(
        (ROOT / "poe-bd-creator-plugin" / ".codex-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )

    assert "name: poe-bd-learning-loop" in text
    assert "$poe-bd-learning-loop" in openai_yaml
    assert "poe-bd-learning-loop" in json.dumps(plugin)
    assert "query_learning_memory" in text
    assert "submit_learning_comparison" in text
    assert "POE_LEARNING_READY: yes" in text


def test_bundle_manifest_lists_phase7_tools():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    names = {item["name"] for item in manifest["tools"]}
    assert {
        "start_learning_campaign",
        "intake_learning_case",
        "claim_learning_phase",
        "submit_learning_profile",
        "get_learning_create_packet",
        "query_learning_memory",
        "submit_learning_create_result",
        "submit_learning_comparison",
        "propose_learning_lesson",
        "append_learning_memory_correction",
        "get_learning_campaign_status",
    } <= names
