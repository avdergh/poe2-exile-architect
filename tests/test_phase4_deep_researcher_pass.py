from __future__ import annotations

import json

import pytest

from scripts import run_phase4_deep_researcher_pass
from server.compute import pob_code


RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
    "transientPacketPath",
    "transientPromptPath",
    "researcher_prompt.txt",
)


def _sample_code() -> str:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="92" className="Warrior" ascendClassName="Titan" mainSocketGroup="2" />
  <Skills>
    <Skill mainActiveSkillCalcs="Dread Banner">
      <Gem nameSpec="Dread Banner" skillId="DreadBannerPlayer" />
    </Skill>
    <Skill mainActiveSkillCalcs="Molten Blast">
      <Gem nameSpec="Molten Blast" skillId="MoltenBlastPlayer" />
      <Gem nameSpec="Cooldown Recovery II" skillId="SupportGemIngenuityTwo" />
    </Skill>
  </Skills>
</PathOfBuilding2>
"""
    return pob_code.encode_code(xml)


def _fake_judge_probe(_source: str, snapshot_id: str) -> dict[str, object]:
    return {
        "snapshotId": snapshot_id,
        "summary": {
            "class": "Warrior",
            "ascendancy": "Titan",
            "mainSkill": "Dread Banner",
            "judgeSelectedSkill": "Molten Blast",
            "level": "92",
        },
        "scoreBreakdown": {
            "offense": {
                "skillName": "Molten Blast",
                "skillGroupIndex": 2,
                "provenance": "direct_pob_dps",
                "evidenceLevel": "limited",
            }
        },
        "caveats": ["snapshot_selected_skill_may_be_non_damage"],
    }


def test_deep_researcher_report_is_safe_while_transient_packet_keeps_raw_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source_file = tmp_path / "sample-pob-code.txt"
    source_file.write_text(_sample_code(), encoding="utf-8")
    monkeypatch.setattr(run_phase4_deep_researcher_pass, "_run_judge_probe", _fake_judge_probe)

    report, transient = run_phase4_deep_researcher_pass.build_deep_pass_report(
        [source_file],
        temp_root=tmp_path,
        current_patch="0.5.4",
        passive_tree_version="0_5",
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["status"] == "ready_for_deep_researcher"
    assert report["sampleCount"] == 1
    assert report["readyCount"] == 1
    sample = report["samples"][0]
    assert sample["diagnosticSummary"]["rawImportedMainSkill"] == "Dread Banner"
    assert sample["diagnosticSummary"]["judgeSelectedSkillCandidate"] == "Molten Blast"
    assert sample["diagnosticSummary"]["authority"] == "non_authoritative"
    assert sample["promptInstructionChecks"]["singleCaseOnly"] is True
    assert sample["promptInstructionChecks"]["judgeProbeNonAuthoritative"] is True
    assert sample["promptInstructionChecks"]["designAxisStatusRequired"] is True

    for marker in RAW_MARKERS:
        assert marker not in serialized

    assert len(transient) == 1
    packet_text = transient[0]["packetPath"].read_text(encoding="utf-8")
    prompt_text = transient[0]["promptPath"].read_text(encoding="utf-8")
    assert "rawImportCode" in packet_text
    assert "PathOfBuilding" in packet_text
    assert "programmaticDiagnostics" in packet_text
    assert "judgeSelectedSkillCandidate" in packet_text
    assert "NON-AUTHORITATIVE" in prompt_text
    assert "rawImportedMainSkill" in prompt_text
    assert "judgeSelectedSkillCandidate" in prompt_text
    assert "one build sample only" in prompt_text
    assert "not_extractable_from_payload" in prompt_text


def test_deep_researcher_prompt_allows_unknown_axis_statuses() -> None:
    prompt = run_phase4_deep_researcher_pass.render_deep_researcher_prompt(
        {
            "packetId": "rp-test",
            "safeHash": "a" * 64,
            "safeMetadata": {"case_id": "case-1"},
            "rawContext": {"programmaticDiagnostics": {}},
        },
        current_patch="0.5.4",
        passive_tree_version="0_5",
    )

    for axis in [
        "scaling_axis",
        "resource_engine",
        "defense_layers",
        "transition_gates",
        "failure_modes",
        "variant_relation",
    ]:
        assert axis in prompt
    for status in [
        "observed",
        "weak_signal",
        "not_observed",
        "not_extractable_from_payload",
        "requires_judge_verification",
    ]:
        assert status in prompt
    assert "Do not force every axis to produce a finding" in prompt
    assert "Programmatic diagnostics are NON-AUTHORITATIVE" in prompt
    assert "Do not treat rawImportedMainSkill as ground truth" in prompt
    assert "Do not treat judgeSelectedSkillCandidate as ground truth" in prompt


def test_deep_researcher_import_failure_does_not_leak_raw(tmp_path) -> None:
    source_file = tmp_path / "bad-pob-code.txt"
    source_file.write_text("not-a-pob-code", encoding="utf-8")

    report, transient = run_phase4_deep_researcher_pass.build_deep_pass_report(
        [source_file],
        temp_root=tmp_path,
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["status"] == "needs_input_repair"
    assert report["samples"][0]["status"] == "import_failed"
    assert transient == []
    assert "not-a-pob-code" not in serialized
