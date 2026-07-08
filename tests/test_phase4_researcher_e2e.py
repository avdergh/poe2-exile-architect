from __future__ import annotations

import json

import pytest

from scripts import run_phase4_researcher_e2e
from server.compute import pob_code


def _sample_code() -> str:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="92" className="Ranger" ascendClassName="Deadeye" />
  <Skills>
    <Skill mainActiveSkillCalcs="Lightning Arrow">
      <Gem nameSpec="Lightning Arrow" />
      <Gem nameSpec="Scattershot" />
    </Skill>
  </Skills>
</PathOfBuilding2>
"""
    return pob_code.encode_code(xml)


def test_phase4_researcher_e2e_report_is_safe_while_transient_packet_keeps_raw(tmp_path):
    source_file = tmp_path / "sample-pob-code.txt"
    source_file.write_text(_sample_code(), encoding="utf-8")

    report, transient = run_phase4_researcher_e2e.build_acceptance_report(
        [source_file],
        temp_root=tmp_path,
        ttl_seconds=3600,
        current_patch="0.5.4",
        passive_tree_version="0_5",
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["status"] == "ready_for_external_researcher"
    assert report["sampleCount"] == 1
    assert report["samples"][0]["safeMetadata"]["mainSkill"] == "Lightning Arrow"
    assert report["samples"][0]["promptInstructionChecks"]["toolDriven"] is True
    assert "eNrt" not in serialized
    assert "rawXml" not in serialized
    assert "rawImportCode" not in serialized
    assert "PathOfBuilding" not in serialized
    assert "transientPacketPath" not in serialized
    assert "transientPromptPath" not in serialized

    assert len(transient) == 1
    packet_path = transient[0]["packetPath"]
    prompt_path = transient[0]["promptPath"]
    packet_text = packet_path.read_text(encoding="utf-8")
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert "rawImportCode" in packet_text
    assert "PathOfBuilding" in packet_text
    assert "MUST NOT output the final JSON as regular text" in prompt_text
    assert "query_research_memory" in prompt_text


def test_phase4_researcher_e2e_mark_import_failures_without_raw_leak(tmp_path):
    source_file = tmp_path / "bad-pob-code.txt"
    source_file.write_text("not-a-pob-code", encoding="utf-8")

    report, transient = run_phase4_researcher_e2e.build_acceptance_report(
        [source_file],
        temp_root=tmp_path,
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["status"] == "needs_input_repair"
    assert report["samples"][0]["status"] == "import_failed"
    assert report["samples"][0]["errorCode"] == "build_import_failed"
    assert transient == []
    assert "not-a-pob-code" not in serialized


def test_phase4_researcher_e2e_safe_error_redacts_copyable_build_urls(monkeypatch, tmp_path):
    source_file = tmp_path / "bad-pob-link.txt"
    source_file.write_text("https://pobb.in/copyable123", encoding="utf-8")

    def fail_with_copyable_url(_source: str) -> str:
        raise pob_code.PobCodeError("failed import from https://pobb.in/copyable123")

    monkeypatch.setattr(run_phase4_researcher_e2e.pob_code, "to_xml", fail_with_copyable_url)

    report, transient = run_phase4_researcher_e2e.build_acceptance_report(
        [source_file],
        temp_root=tmp_path,
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["status"] == "needs_input_repair"
    assert transient == []
    assert "https://pobb.in" not in serialized
    assert "copyable123" not in serialized
    assert report["samples"][0]["safeError"] == "copyable_build_link"


def test_phase4_researcher_e2e_write_report_rejects_unsafe_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(run_phase4_researcher_e2e, "JSON_OUTPUT", tmp_path / "report.json")
    monkeypatch.setattr(run_phase4_researcher_e2e, "MD_OUTPUT", tmp_path / "report.md")
    unsafe_report = {
        "status": "needs_input_repair",
        "sampleCount": 1,
        "readyCount": 0,
        "safeArtifactOnly": True,
        "samples": [{"sampleId": "bad", "status": "import_failed", "safeError": "eNrt" + "A" * 80}],
        "caveats": [],
    }

    with pytest.raises(ValueError, match="unsafe durable report"):
        run_phase4_researcher_e2e.write_report(unsafe_report)

    assert not (tmp_path / "report.json").exists()
    assert not (tmp_path / "report.md").exists()


def test_phase4_researcher_e2e_markdown_does_not_expose_transient_paths(tmp_path):
    source_file = tmp_path / "sample-pob-code.txt"
    source_file.write_text(_sample_code(), encoding="utf-8")

    report, _transient = run_phase4_researcher_e2e.build_acceptance_report(
        [source_file],
        temp_root=tmp_path,
    )

    markdown = run_phase4_researcher_e2e._markdown(report)

    assert "transientPacketPath" not in markdown
    assert "transientPromptPath" not in markdown
    assert "researcher_prompt.txt" not in markdown
    assert "rawImportCode" not in markdown
