from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

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
    "packet.json",
    "researcher_prompt.txt",
)


def test_queue_claim_and_prompt_keep_raw_only_in_prompt(tmp_path):
    from scripts import research_mature_builds

    batch_file = tmp_path / "samples.txt"
    batch_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
        + "\n---POB-SAMPLE---\n"
        + _sample_code("SparkPlayer", ascendancy="Stormweaver", level=96),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp"

    queued = research_mature_builds.queue_cases(
        source_batch_files=[batch_file],
        output_dir=output_dir,
        temp_root=temp_root,
        worker_count=5,
        ttl_seconds=3600,
    )

    assert queued["status"] == "queued"
    assert queued["queueKind"] == "poe_bd_research_external_agent_queue"
    assert queued["sampleCount"] == 2
    assert queued["requestedWorkerCount"] == 5
    assert queued["workerCountSemantics"] == "concurrent_researcher_agent_lanes"
    assert "preparedCount" not in queued
    _assert_safe_payload(queued, tmp_path.parent)

    queue_db = output_dir / "poe_bd_research_queue.sqlite"
    db_bytes = queue_db.read_bytes()
    assert not any(marker.encode("utf-8") in db_bytes for marker in RAW_MARKERS)
    assert str(temp_root).encode("utf-8") not in db_bytes

    first = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    second = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    assert first["status"] == "claimed"
    assert second["status"] == "claimed"
    assert first["sampleId"] != second["sampleId"]
    assert first["leaseToken"] != second["leaseToken"]
    assert first["packetSafeHash"]
    assert "prompt" not in json.dumps(first, ensure_ascii=False).casefold()
    _assert_safe_payload(first, tmp_path.parent)
    _assert_safe_payload(second, tmp_path.parent)

    prompt_text = research_mature_builds.render_claim_prompt(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=first["leaseToken"],
    )

    assert "query_research_memory" in prompt_text
    assert "BuildDesignObservation" in prompt_text
    assert "one build sample only" in prompt_text
    assert "rawImportCode" in prompt_text
    assert "PathOfBuilding" in prompt_text

    status = research_mature_builds.queue_status(output_dir=output_dir)
    assert status["claimedCount"] == 2
    _assert_safe_payload(status, tmp_path.parent)


def test_worker_brief_is_safe_inline_and_explains_tool_fallback(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    monkeypatch.chdir(tmp_path)
    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("MirageDeadeyePlayer", ascendancy="Pathfinder", level=100),
        encoding="utf-8",
    )
    output_dir = Path(".poe-bd-research")
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-worker-brief",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    brief = research_mature_builds.render_worker_brief(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
    )

    assert brief["status"] == "ok"
    assert brief["sampleId"] == claimed["sampleId"]
    assert brief["reviewFile"].startswith("reviews/")
    prompt = brief["workerPrompt"]
    assert "这是完整的 safe worker brief" in prompt
    assert "不要只依赖另一个文件路径" in prompt
    assert "programmatic mainSkill candidate" in prompt
    assert "非权威快照线索" in prompt
    assert "如果这些 MCP tools 没有暴露" in prompt
    assert "不要搜索隐藏工具" in prompt
    assert "safeReviewFile" in prompt
    assert "candidateReviews" in prompt
    assert "不要猜 stable key" in prompt
    assert '"patternType": "build_archetype"' in prompt
    assert "BuildArchetypePattern" in prompt
    assert "不要使用 `BuildArchetypePattern`" in prompt
    assert "`variant_relations`" in prompt
    assert "SKILL.md" not in prompt
    _assert_safe_payload(brief, tmp_path.parent)


def test_accept_resolves_review_file_relative_to_output_dir(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-relative-review",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / "reviews" / "safe-review.json"
    review_file.parent.mkdir()
    review_file.write_text('{"safeArtifactOnly": true}', encoding="utf-8")
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file="reviews/safe-review.json",
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert calls[0]["review_file"] == review_file


def test_retry_accept_rejected_case_without_lease(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-retry-accept",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / "safe-review.json"
    review_file.write_text('{"safeArtifactOnly": true}', encoding="utf-8")
    calls: list[dict] = []

    def fake_reject_then_accept(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "status": "rejected",
                "acceptedPatternCount": 0,
                "deferredCandidateCount": 0,
                "patternWrite": {"status": "error"},
            }
        return {
            "status": "accepted",
            "acceptedPatternCount": 2,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_reject_then_accept,
    )

    rejected = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory.sqlite",
    )
    assert rejected["status"] == "acceptance_rejected"
    assert research_mature_builds.queue_status(output_dir=output_dir)["rejectedCount"] == 1

    retried = research_mature_builds.retry_accept_case(
        output_dir=output_dir,
        sample_id=claimed["sampleId"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert retried["status"] == "accepted"
    assert retried["acceptedPatternCount"] == 2
    assert len(calls) == 2
    status = research_mature_builds.queue_status(output_dir=output_dir)
    assert status["acceptedCount"] == 1
    assert status["rejectedCount"] == 0


def test_expired_lease_can_reclaim_and_old_lease_cannot_accept(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-reclaim",
    )
    first = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    _expire_case_lease(output_dir / "poe_bd_research_queue.sqlite", first["sampleId"])
    second = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    assert second["sampleId"] == first["sampleId"]
    assert second["leaseToken"] != first["leaseToken"]

    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    review_file = tmp_path / "safe-review.json"
    review_file.write_text('{"safeArtifactOnly": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="lease"):
        research_mature_builds.accept_case(
            output_dir=output_dir,
            lease_token=first["leaseToken"],
            review_file=review_file,
            memory_db_path=tmp_path / "memory.sqlite",
        )
    assert calls == []

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=second["leaseToken"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert accepted["sampleId"] == second["sampleId"]
    assert accepted["acceptedPatternCount"] == 1
    assert len(calls) == 1
    assert research_mature_builds.queue_status(output_dir=output_dir)["acceptedCount"] == 1


def test_accept_holds_exact_lease_before_running_durable_acceptance(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-accept-lock",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    reclaim_attempts: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        _expire_case_lease(output_dir / "poe_bd_research_queue.sqlite", claimed["sampleId"])
        reclaim_attempts.append(
            research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
        )
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    review_file = tmp_path / "safe-review.json"
    review_file.write_text('{"safeArtifactOnly": true}', encoding="utf-8")

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert reclaim_attempts == [
        {
            "status": "no_pending_cases",
            "queueKind": "poe_bd_research_external_agent_queue",
            "noRawMatureBuildMaterial": True,
        }
    ]
    assert research_mature_builds.queue_status(output_dir=output_dir)["acceptedCount"] == 1


def test_legacy_phase45_wrappers_warn_on_stderr_without_polluting_json_stdout(
    tmp_path, capsys, monkeypatch
):
    from scripts import phase45_accept_single_review, run_phase45_researcher_batch

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    code = run_phase45_researcher_batch.main(
        [
            "--source-file",
            str(source_file),
            "--output-dir",
            str(tmp_path / "legacy-queue"),
            "--temp-root",
            str(tmp_path.parent / "legacy-temp"),
            "--dry-run",
            "--json-output",
            str(tmp_path / "legacy.json"),
            "--md-output",
            str(tmp_path / "legacy.md"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "deprecated" in captured.err.lower()
    assert json.loads(captured.out)["status"] == "dry_run"

    review_file = tmp_path / "safe-review.json"
    review_file.write_text('{"safeArtifactOnly": true}', encoding="utf-8")

    def fake_accept_deep_review_candidates(**kwargs):
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {},
        }

    monkeypatch.setattr(
        "scripts.phase45_accept_single_review.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    code = phase45_accept_single_review.main(
        [
            "--review-file",
            str(review_file),
            "--case-id",
            "case:legacy-001",
            "--output-dir",
            str(tmp_path / "legacy-accept"),
            "--db-path",
            str(tmp_path / "memory.sqlite"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "deprecated" in captured.err.lower()
    assert json.loads(captured.out)["status"] == "accepted"


def test_queue_cli_reports_collector_failure_as_safe_json(tmp_path, capsys, monkeypatch):
    from scripts import research_mature_builds

    def fail_collect(**kwargs):
        raise RuntimeError("HTTP Error 403: Forbidden while fetching poe.ninja")

    monkeypatch.setattr(research_mature_builds.legacy_batch, "_cases_from_ninja", fail_collect)

    code = research_mature_builds.main(
        [
            "queue",
            "--output-dir",
            str(tmp_path / "research"),
            "--limit",
            "1",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 1
    assert payload["status"] == "collector_failed"
    assert payload["command"] == "queue"
    assert payload["noRawMatureBuildMaterial"] is True
    assert "HTTP Error 403" in payload["safeError"]
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err
    _assert_safe_payload(payload, tmp_path.parent)


def _expire_case_lease(db_path: Path, sample_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE cases
               SET lease_expires_at = '2000-01-01T00:00:00+00:00'
             WHERE sample_id = ?
            """,
            (sample_id,),
        )
        conn.commit()


def _assert_safe_payload(payload: dict, transient_parent: Path) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)
    assert str(transient_parent) not in serialized


def _sample_code(skill_id: str, *, ascendancy: str, level: int) -> str:
    return pob_code.encode_code(_sample_xml(skill_id, ascendancy=ascendancy, level=level))


def _sample_xml(skill_id: str, *, ascendancy: str, level: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="{level}" className="Ranger" ascendClassName="{ascendancy}" mainSocketGroup="1" />
  <Skills>
    <Skill mainActiveSkillCalcs="{skill_id}">
      <Gem nameSpec="{skill_id}" skillId="{skill_id}" enabled="true" />
    </Skill>
  </Skills>
</PathOfBuilding2>
"""
