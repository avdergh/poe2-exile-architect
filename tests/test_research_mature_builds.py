from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from server.compute import pob_code
from server import paths


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


def test_research_queue_defaults_to_runtime_memory_store():
    from scripts import research_mature_builds

    assert research_mature_builds.DEFAULT_MEMORY_DB_PATH == paths.mature_learning_path()


def test_queue_cli_allocates_a_distinct_default_run_directory_per_invocation(
    tmp_path, capsys, monkeypatch
):
    from scripts import research_mature_builds

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        research_mature_builds,
        "DEFAULT_OUTPUT_DIR",
        tmp_path / ".poe-bd-research",
    )
    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )

    reports = []
    for _ in range(2):
        code = research_mature_builds.main(["queue", "--source-file", str(source_file)])
        assert code == 0
        reports.append(json.loads(capsys.readouterr().out))

    first, second = reports
    assert first["runId"] != second["runId"]
    assert first["runDir"] != second["runDir"]
    assert first["nextCommandArgs"] == {"outputDir": first["runDir"]}
    assert second["nextCommandArgs"] == {"outputDir": second["runDir"]}
    for report in reports:
        run_dir = tmp_path / Path(report["runDir"])
        assert run_dir.parent.parent == tmp_path / ".poe-bd-research"
        assert (run_dir / research_mature_builds.QUEUE_DB_FILENAME).exists()
        assert research_mature_builds.queue_status(output_dir=run_dir)["queuedCount"] == 1


def test_queue_refuses_to_overwrite_an_existing_queue(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-no-overwrite"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=temp_root,
    )
    db_path = output_dir / research_mature_builds.QUEUE_DB_FILENAME
    original_db = db_path.read_bytes()

    with pytest.raises(FileExistsError, match="already exists"):
        research_mature_builds.queue_cases(
            source_files=[source_file],
            output_dir=output_dir,
            temp_root=temp_root,
        )

    assert db_path.read_bytes() == original_db
    assert research_mature_builds.queue_status(output_dir=output_dir)["queuedCount"] == 1


def test_queue_forwards_optional_ninja_class_filter(tmp_path, monkeypatch):
    from scripts import research_mature_builds

    captured: dict = {}

    def fake_cases_from_ninja(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        research_mature_builds.legacy_batch,
        "_cases_from_ninja",
        fake_cases_from_ninja,
    )
    output_dir = tmp_path / "research"
    queued = research_mature_builds.queue_cases(
        league_url="runesofaldur",
        limit=3,
        level_min=95,
        level_max=95,
        ninja_classes=["Blood+Mage"],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-ninja-class-filter",
    )

    assert captured["ninja_classes"] == ["Blood Mage"]
    with sqlite3.connect(output_dir / research_mature_builds.QUEUE_DB_FILENAME) as conn:
        stored = conn.execute("SELECT value FROM metadata WHERE key = 'ninjaClasses'").fetchone()[0]
    assert json.loads(stored) == ["Blood Mage"]
    assert queued["status"] == "source_unavailable"
    assert queued["errorKind"] == "source_unavailable"
    assert queued["requestedSampleCount"] == 3
    assert queued["availableSampleCount"] == 0
    assert queued["sampleShortfallCount"] == 3
    assert queued["queueCreated"] is True
    assert research_mature_builds.queue_status(output_dir=output_dir)["status"] == (
        "source_unavailable"
    )
    with sqlite3.connect(output_dir / research_mature_builds.QUEUE_DB_FILENAME) as conn:
        conn.execute("DELETE FROM metadata WHERE key IN ('queueStatus', 'requestedSampleCount')")
        conn.commit()
    legacy_status = research_mature_builds.queue_status(output_dir=output_dir)
    assert legacy_status["status"] == "source_unavailable"
    assert legacy_status["requestedSampleCount"] == 3
    assert legacy_status["sampleShortfallCount"] == 3


def test_queue_cli_stops_when_live_source_has_no_usable_samples(tmp_path, capsys, monkeypatch):
    from scripts import research_mature_builds

    monkeypatch.setattr(
        research_mature_builds.legacy_batch,
        "_cases_from_ninja",
        lambda **kwargs: [],
    )

    code = research_mature_builds.main(
        [
            "queue",
            "--output-dir",
            str(tmp_path / "research"),
            "--limit",
            "5",
            "--class",
            "Gemling+Legionnaire",
            "--level-min",
            "81",
            "--level-max",
            "81",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["status"] == "source_unavailable"
    assert payload["errorKind"] == "source_unavailable"
    assert payload["sampleCount"] == 0
    assert payload["requestedSampleCount"] == 5
    assert payload["availableSampleCount"] == 0
    assert payload["sampleShortfallCount"] == 5
    assert payload["queuedCount"] == 0
    assert payload["queueCreated"] is True
    assert "claim" in payload["nextStep"]
    _assert_safe_payload(payload, tmp_path.parent)


def test_research_sample_id_is_stable_across_separate_queue_runs(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    first = research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=tmp_path / "first",
        temp_root=tmp_path.parent / "poe-research-temp-stable-id-first",
        dry_run=True,
    )
    second = research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=tmp_path / "second",
        temp_root=tmp_path.parent / "poe-research-temp-stable-id-second",
        sample_start_index=99,
        dry_run=True,
    )

    assert first["samples"][0]["sampleId"] == second["samples"][0]["sampleId"]
    assert first["samples"][0]["sampleId"].startswith("case:poe-bd-research-")


def test_queue_claim_and_prompt_expose_only_safe_bounded_navigation(tmp_path):
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
    assert queued["requestedWorkerCount"] == 1
    assert queued["workerCountSemantics"] == "serial_one_case_at_a_time"
    assert "preparedCount" not in queued
    _assert_safe_payload(queued, tmp_path.parent)

    queue_db = output_dir / "poe_bd_research_queue.sqlite"
    db_bytes = queue_db.read_bytes()
    assert not any(marker.encode("utf-8") in db_bytes for marker in RAW_MARKERS)
    assert str(temp_root).encode("utf-8") not in db_bytes

    first = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    second = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    assert first["status"] == "claimed"
    assert second["status"] == "active_case_in_progress"
    assert second["sampleId"] == first["sampleId"]
    assert first["mainSkillAuthority"] == "programmatic_snapshot_non_authoritative"
    assert first["packetSafeHash"]
    assert first["reviewFile"].startswith("reviews/")
    assert "这是当前案例的安全导航 brief" in first["workerPrompt"]
    assert "不要转交给其他 agent" in first["workerPrompt"]
    assert "--output-dir <runDir>" in first["workerPrompt"]
    assert first["leaseToken"] in first["workerPrompt"]
    _assert_safe_payload(first, tmp_path.parent)
    _assert_safe_payload(second, tmp_path.parent)

    prompt_text = research_mature_builds.render_claim_prompt(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=first["leaseToken"],
    )

    prompt_payload = json.loads(prompt_text)
    assert prompt_payload["deprecatedRawPrompt"] is True
    assert prompt_payload["recommendedReadOrder"] == [
        "skills",
        "gear",
        "passives",
        "config",
        "build",
    ]
    _assert_safe_payload(prompt_payload, tmp_path.parent)

    status = research_mature_builds.queue_status(output_dir=output_dir)
    assert status["claimedCount"] == 1
    assert status["queuedCount"] == 1
    assert all("acceptedDeepRecordCount" in sample for sample in status["samples"])
    assert all(
        sample["mainSkillAuthority"] == "programmatic_snapshot_non_authoritative"
        for sample in status["samples"]
    )
    assert all("unresolvedDeepRecordComponentCount" in sample for sample in status["samples"])
    assert all("unresolvedDeepRecordMentionCount" in sample for sample in status["samples"])
    assert all("unresolvedUniqueComponentCount" in sample for sample in status["samples"])
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

    assert claimed["reviewFile"].startswith("reviews/")
    assert claimed["workerPrompt"]

    brief = research_mature_builds.render_worker_brief(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
    )

    assert brief["status"] == "ok"
    assert brief["sampleId"] == claimed["sampleId"]
    assert brief["reviewFile"].startswith("reviews/")
    prompt = brief["workerPrompt"]
    assert "这是当前案例的安全导航 brief" in prompt
    assert "不要转交给其他 agent" in prompt
    assert "inspect" in prompt
    assert "read" in prompt
    assert "programmatic mainSkill candidate" in prompt
    assert "非权威快照线索" in prompt
    assert "tool discovery / tool search" in prompt
    assert "工具可能采用延迟发现" in prompt
    assert "lookup_mechanic" in prompt
    assert "mechanicAudit" in prompt
    assert "revision-pinned sourceRef" in prompt
    assert "不得拼接 `A / B`" in prompt
    assert "最强因果结论" in prompt
    assert "不要读源码或临时构造 service" in prompt
    assert "safeReviewFile" in prompt
    assert "review-contract" in prompt
    assert "accept --output-dir <runDir> --lease-token" in prompt
    assert "--validate-only" in prompt
    assert "不得自造枚举" in prompt
    assert "componentKey" in prompt
    assert "两空格缩进的多行 JSON" in prompt
    assert "fullyResolvedForAccept" in prompt
    assert "partial_with_deferred" in prompt
    assert "DeepResearchRecord" in prompt
    assert "完整保留该机制包" in prompt
    assert '"patternType": "build_archetype"' not in prompt
    assert "SKILL.md" not in prompt
    _assert_safe_payload(brief, tmp_path.parent)


def test_review_contract_discloses_exact_enums_just_before_writing(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("MirageDeadeyePlayer", ascendancy="Pathfinder", level=100),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-review-contract",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    contract = research_mature_builds.render_review_contract(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
    )

    assert contract["status"] == "ok"
    assert contract["reviewFile"] == claimed["reviewFile"]
    assert contract["topLevelTemplate"]["artifactIdentity"] == {
        "sampleId": claimed["sampleId"],
        "caseRef": claimed["sourceHashRef"],
        "safeEvidenceRef": f"evidence:{claimed['packetSafeHash'][:16]}",
        "packetSafeHash": claimed["packetSafeHash"],
    }
    assert contract["topLevelTemplate"]["caseCoverage"]["supports"] == "evidence_missing"
    assert contract["topLevelTemplate"]["mechanicAudit"] == []
    assert contract["mechanicAuditTemplate"]["wiki"]["sourceRef"].startswith("poe2wiki:page:")
    assert contract["mechanicAuditTemplate"]["decision"] == "keep"
    assert "contradicts" in contract["allowedValues"]["mechanicAuditWikiStatus"]
    assert "source_artifact" in contract["allowedValues"]["mechanicAuditCorroboration"]
    assert any("mechanic_chain 和 resource_engine" in rule for rule in contract["rules"])
    assert any("A / B" in rule for rule in contract["rules"])
    family_rules = [rule for rule in contract["rules"] if "BuildFamily" in rule]
    assert family_rules
    assert any("trigger_host" in rule and "不自动参与身份" in rule for rule in family_rules)
    assert not any(
        "trigger_host 由程序自动参与" in rule or "trigger_host roles" in rule
        for rule in contract["rules"]
    )
    assert (
        "clear/boss/triggered_payload"
        in contract["typedPayloadSchema"]["familyCoreSkillKeys"]["rule"]
    )
    assert "trigger hosts" in contract["typedPayloadSchema"]["familyCoreSkillKeys"]["rule"]
    assert "support_modifier" in contract["allowedValues"]["componentRole"]
    assert "burst_window" not in contract["allowedValues"]["componentRole"]
    assert contract["artifactEncoding"] == {
        "format": "json",
        "encoding": "utf-8",
        "prettyPrinted": True,
        "indent": 2,
    }
    assert "notable" in contract["componentRoleNodeTypeCompatibility"]["payoff"]
    assert contract["componentRoleNodeTypeCompatibility"]["gear_base"] == ["item_base"]
    assert "unique" in contract["componentRoleNodeTypeCompatibility"]["weapon_base"]
    assert contract["recordTemplate"]["components"][0]["componentKey"] is None
    assert "sampleId" not in contract["recordTemplate"]
    assert "caseRef" not in contract["candidateTemplate"]
    assert contract["allowedValues"]["transferScope"] == ["family", "component"]
    assert contract["allowedValues"]["gearResponsibilityType"] == [
        "budget_substitute",
        "defense",
        "identity_enabler",
        "optional_upgrade",
        "primary_skill_source",
        "recovery",
        "resource_or_spirit",
        "scaling",
        "utility",
    ]
    assert contract["candidateTemplate"]["transferScope"] == "family"
    assert "gearResponsibilities" in contract["allowedValues"]["typedIdentityFields"]
    assert "supportCoverageExceptions" in contract["allowedValues"]["typedIdentityFields"]
    assert (
        "skillName/supportNames"
        in contract["allowedValues"]["typedIdentityFields"]["supportPackages"]
    )
    assert "applicabilityRequirements" in contract["candidateTemplate"]
    assert "exclusionConditions" in contract["candidateTemplate"]
    assert "不得自造 role" in contract["rules"][0]
    assert contract["nextActions"] == [
        "init-review",
        "edit_review",
        "accept --validate-only",
        "accept",
    ]
    _assert_safe_payload(contract, tmp_path.parent)


def test_init_review_creates_pretty_utf8_skeleton_and_never_overwrites(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("MirageDeadeyePlayer", ascendancy="Pathfinder", level=100),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=tmp_path.parent / "poe-research-temp-init-review",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    initialized = research_mature_builds.init_review(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
    )
    review_path = output_dir / claimed["reviewFile"]
    raw = review_path.read_bytes()
    text = raw.decode("utf-8")
    payload = json.loads(text)

    assert initialized["status"] == "initialized"
    assert initialized["created"] is True
    assert initialized["reviewFile"] == claimed["reviewFile"]
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert text.endswith("\n")
    assert '\n  "caseCoverage": {' in text
    assert payload["reportId"] == "poe_bd_research_review"
    assert payload["safeArtifactOnly"] is True
    assert payload["artifactIdentity"] == {
        "sampleId": claimed["sampleId"],
        "caseRef": claimed["sourceHashRef"],
        "safeEvidenceRef": f"evidence:{claimed['packetSafeHash'][:16]}",
        "packetSafeHash": claimed["packetSafeHash"],
    }
    assert payload["deepResearchRecords"] == []
    assert payload["candidateReviews"] == []
    assert payload["mechanicAudit"] == []

    review_path.write_text(text.replace("evidence_missing", "covered", 1), encoding="utf-8")
    existing = research_mature_builds.init_review(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
    )
    assert existing["status"] == "already_exists"
    assert existing["created"] is False
    assert (
        json.loads(review_path.read_text(encoding="utf-8"))["caseCoverage"]["supports"] == "covered"
    )
    _assert_safe_payload(initialized, tmp_path.parent)
    _assert_safe_payload(existing, tmp_path.parent)


def test_init_review_rejects_wrong_or_expired_lease(tmp_path):
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
        temp_root=tmp_path.parent / "poe-research-temp-init-review-lease",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    with pytest.raises(ValueError, match="lease"):
        research_mature_builds.init_review(output_dir=output_dir, lease_token="wrong-token")
    _expire_case_lease(output_dir / "poe_bd_research_queue.sqlite", claimed["sampleId"])
    with pytest.raises(ValueError, match="lease"):
        research_mature_builds.init_review(
            output_dir=output_dir,
            lease_token=claimed["leaseToken"],
        )
    assert not (output_dir / claimed["reviewFile"]).exists()


def test_init_review_cli_returns_safe_bounded_metadata(tmp_path, capsys):
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
        temp_root=tmp_path.parent / "poe-research-temp-init-review-cli",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    code = research_mature_builds.main(
        [
            "init-review",
            "--output-dir",
            str(output_dir),
            "--lease-token",
            claimed["leaseToken"],
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "initialized"
    assert payload["reviewFile"] == claimed["reviewFile"]
    assert payload["noRawMatureBuildMaterial"] is True
    _assert_safe_payload(payload, tmp_path.parent)


def test_validate_only_keeps_current_lease_and_skips_durable_acceptance(tmp_path, monkeypatch):
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
        temp_root=tmp_path.parent / "poe-research-temp-validate-only",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    calls: list[dict] = []

    def fake_validate(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "deferredReasonCounts": {},
            "patternWrite": {"status": "accepted", "validationOnly": True},
            "deepRecordWrite": {"status": "accepted", "validationOnly": True},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_validate,
    )
    result = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
        validation_only=True,
    )

    assert result["status"] == "validation_passed"
    assert result["readyForAccept"] is True
    assert result["fullyResolvedForAccept"] is True
    assert result["acceptanceMode"] == "clean"
    assert result["durableWritePerformed"] is False
    assert result["queueStateChanged"] is False
    assert calls[0]["validation_only"] is True
    status = research_mature_builds.queue_status(output_dir=output_dir)
    assert status["claimedCount"] == 1
    assert status["acceptedCount"] == 0


def test_validation_only_distinguishes_partial_acceptance_from_clean_acceptance():
    from scripts import research_mature_builds

    result = research_mature_builds._validation_only_result(
        {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 3,
            "unresolvedDeepRecordComponentCount": 2,
            "unresolvedDeepRecordMentionCount": 2,
            "unresolvedUniqueComponentCount": 1,
            "unkeyedDeepRecordCount": 1,
            "deepRecordsWithoutKnowledgeIdentity": [
                {"titleZh": "无身份资源记录", "recordKind": "resource_engine"}
            ],
            "deepRecordsWithUnresolvedComponents": [
                {
                    "titleZh": "待修复记录",
                    "recordKind": "mechanic_chain",
                    "unresolvedComponentCount": 2,
                }
            ],
            "deferredCandidateCount": 1,
            "deferredReasonCounts": {"component_type_mismatch": 1},
            "deferredCandidates": [{"reason": "component_type_mismatch"}],
            "patternWrite": {"status": "accepted", "validationOnly": True},
            "deepRecordWrite": {"status": "accepted", "validationOnly": True},
        },
        sample_id="case:partial",
    )

    assert result["status"] == "validation_passed"
    assert result["readyForAccept"] is True
    assert result["fullyResolvedForAccept"] is False
    assert result["acceptanceMode"] == "partial_with_deferred"
    assert result["unresolvedDeepRecordMentionCount"] == 2
    assert result["unresolvedUniqueComponentCount"] == 1
    assert result["unkeyedDeepRecordCount"] == 1
    assert result["deepRecordsWithoutKnowledgeIdentity"][0]["recordKind"] == "resource_engine"
    assert result["deepRecordsWithUnresolvedComponents"][0]["titleZh"] == "待修复记录"


def test_validation_only_treats_case_coverage_gap_as_partial_acceptance():
    from scripts import research_mature_builds

    result = research_mature_builds._validation_only_result(
        {
            "status": "accepted",
            "acceptedDeepRecordCount": 3,
            "deferredCandidateCount": 0,
            "caseCoverageGapCount": 1,
            "caseCoverageGaps": ["gearRoles"],
            "patternWrite": {"status": "accepted", "validationOnly": True},
            "deepRecordWrite": {"status": "accepted", "validationOnly": True},
        },
        sample_id="case:coverage-gap",
    )

    assert result["status"] == "validation_passed"
    assert result["readyForAccept"] is True
    assert result["fullyResolvedForAccept"] is False
    assert result["acceptanceMode"] == "partial_with_deferred"
    assert result["caseCoverageGaps"] == ["gearRoles"]


def test_bounded_case_reader_pages_all_sections_and_finds_non_main_skill(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "rich-sample.txt"
    source_file.write_text(pob_code.encode_code(_rich_sample_xml()), encoding="utf-8")
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-rich-reader"
    research_mature_builds.queue_cases(
        source_files=[source_file],
        output_dir=output_dir,
        temp_root=temp_root,
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    inspected = research_mature_builds.inspect_case(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
    )

    assert inspected["sections"]["skills"]["itemCount"] == 3
    assert inspected["sections"]["gear"]["itemCount"] == 2
    assert inspected["sections"]["passives"]["itemCount"] > 50
    _assert_safe_payload(inspected, tmp_path.parent)

    all_passives: list[dict] = []
    cursor = 0
    while True:
        page = research_mature_builds.read_case_section(
            output_dir=output_dir,
            temp_root=temp_root,
            lease_token=claimed["leaseToken"],
            section="passives",
            cursor=cursor,
            limit=7,
        )
        assert len(json.dumps(page, ensure_ascii=False, indent=2)) <= 12_000
        all_passives.extend(page["items"])
        if page["complete"]:
            break
        cursor = page["nextCursor"]

    allocated = [item["nodeId"] for item in all_passives if item["kind"] == "allocated_node"]
    assert allocated == [str(value) for value in range(100, 160)]
    assert len(allocated) == len(set(allocated))

    skills = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="skills",
        limit=50,
    )
    names = [gem["name"] for group in skills["items"] for gem in group["gems"]]
    assert "Plasma Blast" in names
    assert "Bonestorm" in names
    assert "Blasphemy" in names
    assert "Controlled Destruction" in names

    search = research_mature_builds.search_case(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        query="Bonestorm",
        section="skills",
    )
    assert search["totalMatchCount"] == 1
    assert search["matches"][0]["item"]["gems"][0]["name"] == "Bonestorm"
    _assert_safe_payload(search, tmp_path.parent)


def test_passive_reader_enriches_known_nodes_from_pinned_tree(tmp_path):
    from scripts import research_mature_builds

    xml = _sample_xml("SparkPlayer", ascendancy="Stormweaver", level=90).replace(
        "</PathOfBuilding2>",
        '<Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="57513,45918" /></Tree></PathOfBuilding2>',
    )
    source_file = tmp_path / "passive-sample.txt"
    source_file.write_text(pob_code.encode_code(xml), encoding="utf-8")
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-passive-enrichment"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="passives",
        limit=50,
    )

    nodes = {item.get("nodeId"): item for item in page["items"] if item["kind"] == "allocated_node"}
    assert nodes["57513"]["name"] == "Eldritch Battery"
    assert nodes["57513"]["nodeTypes"] == ["keystone"]
    assert nodes["45918"]["name"] == "Mind Over Matter"


def test_passive_reader_exposes_ascendancy_ownership(tmp_path):
    from scripts import research_mature_builds

    xml = _sample_xml("SparkPlayer", ascendancy="Oracle", level=90).replace(
        "</PathOfBuilding2>",
        '<Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="55135" /></Tree></PathOfBuilding2>',
    )
    source_file = tmp_path / "oracle-passive-sample.txt"
    source_file.write_text(pob_code.encode_code(xml), encoding="utf-8")
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-oracle-passive"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="passives",
        limit=50,
    )

    node = next(item for item in page["items"] if item.get("nodeId") == "55135")
    assert node["name"] == "Forced Outcome"
    assert node["ascendancyName"] == "Oracle"
    assert node["isAscendancyPassive"] is True


def test_passive_reader_filters_by_node_type(tmp_path):
    from scripts import research_mature_builds

    xml = _sample_xml("SparkPlayer", ascendancy="Stormweaver", level=90).replace(
        "</PathOfBuilding2>",
        '<Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="57513,45918,100" /></Tree></PathOfBuilding2>',
    )
    source_file = tmp_path / "passive-filter-sample.txt"
    source_file.write_text(pob_code.encode_code(xml), encoding="utf-8")
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-passive-filter"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    keystone_page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="passives",
        node_type="keystone",
        limit=50,
    )
    keystone_nodes = [item for item in keystone_page["items"] if item["kind"] == "allocated_node"]
    assert [item["nodeId"] for item in keystone_nodes] == ["57513", "45918"]
    assert keystone_page["totalCount"] == 2
    assert keystone_page["complete"] is True

    normal_page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="passives",
        node_type="normal",
        limit=50,
    )
    normal_nodes = [item for item in normal_page["items"] if item["kind"] == "allocated_node"]
    assert [item["nodeId"] for item in normal_nodes] == ["100"]

    unfiltered = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="passives",
        limit=50,
    )
    unfiltered_allocated = [
        item for item in unfiltered["items"] if item["kind"] == "allocated_node"
    ]
    assert sorted(item["nodeId"] for item in unfiltered_allocated) == ["100", "45918", "57513"]


def test_case_reader_reports_cross_axis_rare_cooccurrence_advisory(tmp_path):
    from scripts import research_mature_builds

    xml = _sample_xml("SparkPlayer", ascendancy="Stormweaver", level=90).replace(
        "</PathOfBuilding2>",
        (
            '<Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="57513" /></Tree>'
            '<Items activeItemSet="1">'
            '<Item id="7">Rarity: RARE\nThorns of Chaos\nHelmet\nItem Level: 82\n'
            "+30 to maximum Life\n50% increased Chaos Damage\n40 to 60 Physical Thorns damage</Item>"
            '<ItemSet id="1"><Slot name="Helmet" itemId="7" /></ItemSet></Items>'
            "</PathOfBuilding2>"
        ),
    )
    source_file = tmp_path / "advisory-sample.txt"
    source_file.write_text(pob_code.encode_code(xml), encoding="utf-8")
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-advisory"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="gear",
        limit=50,
    )
    assert page["advisories"]
    assert "chaos" in page["advisories"][0]
    assert "thorns" in page["advisories"][0]


def test_case_reader_omits_advisory_without_rare_axis_cooccurrence(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "clean-sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-clean-advisory"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)

    page = research_mature_builds.read_case_section(
        output_dir=output_dir,
        temp_root=temp_root,
        lease_token=claimed["leaseToken"],
        section="skills",
        limit=50,
    )
    assert page["advisories"] == []


def test_case_reader_rejects_wrong_or_expired_lease(tmp_path):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"
    temp_root = tmp_path.parent / "poe-research-temp-reader-lease"
    research_mature_builds.queue_cases(
        source_files=[source_file], output_dir=output_dir, temp_root=temp_root
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1)

    with pytest.raises(ValueError, match="lease"):
        research_mature_builds.inspect_case(
            output_dir=output_dir,
            temp_root=temp_root,
            lease_token="wrong-token",
        )

    with sqlite3.connect(output_dir / "poe_bd_research_queue.sqlite") as con:
        con.execute(
            "UPDATE cases SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE sample_id = ?",
            (claimed["sampleId"],),
        )
        con.commit()
    with pytest.raises(ValueError, match="lease"):
        research_mature_builds.read_case_section(
            output_dir=output_dir,
            temp_root=temp_root,
            lease_token=claimed["leaseToken"],
            section="skills",
        )


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
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "recordKindCounts": {"rotation": 1},
            "caseCoverage": {
                "supports": "covered",
                "rotation": "covered",
                "passiveAscendancy": "evidence_missing",
                "gearRoles": "evidence_missing",
                "resourceDefense": "evidence_missing",
            },
            "caseCoverageGapCount": 3,
            "caseCoverageGaps": [
                "passiveAscendancy",
                "gearRoles",
                "resourceDefense",
            ],
            "singleComponentObservationCount": 1,
            "createdBuildFamilyCount": 1,
            "addedBuildFamilyEvidenceCount": 1,
            "recordKindAdvisories": ["fixture advisory"],
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
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert calls[0]["review_file"] == review_file
    assert accepted["recordKindCounts"] == {"rotation": 1}
    assert accepted["caseCoverageGapCount"] == 3
    assert accepted["singleComponentObservationCount"] == 1
    assert accepted["createdBuildFamilyCount"] == 1
    assert accepted["addedBuildFamilyEvidenceCount"] == 1
    status_sample = research_mature_builds.queue_status(output_dir=output_dir)["samples"][0]
    assert status_sample["createdBuildFamilyCount"] == 1
    assert status_sample["addedBuildFamilyEvidenceCount"] == 1
    assert status_sample["caseCoverage"]["rotation"] == "covered"
    assert status_sample["caseCoverageGaps"] == [
        "passiveAscendancy",
        "gearRoles",
        "resourceDefense",
    ]
    assert status_sample["recordKindAdvisories"] == ["fixture advisory"]


def test_accept_resolves_lease_review_basename_from_reviews_directory(tmp_path, monkeypatch):
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
        temp_root=tmp_path.parent / "poe-research-temp-review-basename",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
            "deepRecordWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=review_file.name,
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert calls[0]["review_file"] == review_file


def test_accept_allows_full_current_lease_token_in_review_filename(tmp_path, monkeypatch):
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
        temp_root=tmp_path.parent / "poe-research-temp-full-lease-review",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    sample_slug = research_mature_builds._slug(claimed["sampleId"])
    review_file = output_dir / "reviews" / f"{sample_slug}-{claimed['leaseToken']}-safe-review.json"
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
            "deepRecordWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=review_file.name,
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert calls[0]["review_file"] == review_file


def test_accept_rejects_matching_lease_filename_with_wrong_case_identity(tmp_path, monkeypatch):
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
        temp_root=tmp_path.parent / "poe-research-temp-wrong-review-identity",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed, case_ref="source-hash:wrong")
    calls: list[dict] = []
    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        lambda **kwargs: calls.append(kwargs),
    )

    with pytest.raises(ValueError, match="identity"):
        research_mature_builds.accept_case(
            output_dir=output_dir,
            lease_token=claimed["leaseToken"],
            review_file=review_file.name,
            memory_db_path=tmp_path / "memory.sqlite",
        )

    assert calls == []


def test_accept_canonicalizes_repeated_record_identity_from_lease(tmp_path, monkeypatch):
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
        temp_root=tmp_path.parent / "poe-research-temp-canonical-review-identity",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
    payload = json.loads(review_file.read_text(encoding="utf-8"))
    payload["deepResearchRecords"][0]["sampleId"] = claimed["sampleId"] + "-typo"
    payload["deepResearchRecords"][0]["researchGroupId"] = "research:copied-by-agent"
    review_file.write_text(json.dumps(payload), encoding="utf-8")
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
            "deepRecordWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    canonical = calls[0]["review_payload"]["deepResearchRecords"][0]
    assert canonical["sampleId"] == claimed["sampleId"]
    assert canonical["researchGroupId"] == f"research:{claimed['sampleId']}"
    assert canonical["caseRef"] == claimed["sourceHashRef"]
    assert canonical["safeEvidenceRef"] == f"evidence:{claimed['packetSafeHash'][:16]}"


def test_queue_cli_stops_when_local_attachment_count_does_not_match(tmp_path, capsys):
    from scripts import research_mature_builds

    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research"

    code = research_mature_builds.main(
        [
            "queue",
            "--output-dir",
            str(output_dir),
            "--source-file",
            str(source_file),
            "--expected-source-count",
            "5",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["status"] == "source_input_count_mismatch"
    assert payload["expectedSourceCount"] == 5
    assert payload["localSourceInputCount"] == 1
    assert payload["queueCreated"] is False
    assert not (output_dir / "poe_bd_research_queue.sqlite").exists()


def test_accept_identity_allows_plural_safe_evidence_refs(tmp_path, monkeypatch):
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
        temp_root=tmp_path.parent / "poe-research-temp-plural-evidence",
    )
    claimed = research_mature_builds.claim_case(output_dir=output_dir, lease_seconds=1800)
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    payload = {
        "safeArtifactOnly": True,
        "deepResearchRecords": [
            {
                "sampleId": claimed["sampleId"],
                "caseRef": claimed["sourceHashRef"],
                "safeEvidenceRefs": [f"evidence:{claimed['packetSafeHash'][:16]}"],
            }
        ],
        "candidateReviews": [],
    }
    review_file.write_text(json.dumps(payload), encoding="utf-8")
    calls: list[dict] = []

    def fake_accept_deep_review_candidates(**kwargs):
        calls.append(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 0,
            "acceptedDeepRecordCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {"status": "accepted"},
            "deepRecordWrite": {"status": "accepted"},
        }

    monkeypatch.setattr(
        "scripts.research_mature_builds.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=claimed["reviewFile"],
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
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)
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
    assert second["reviewFile"] != first["reviewFile"]

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
    review_file = output_dir / second["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, second)

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
    review_file = output_dir / claimed["reviewFile"]
    review_file.parent.mkdir(parents=True)
    _write_claim_review(review_file, claimed)

    accepted = research_mature_builds.accept_case(
        output_dir=output_dir,
        lease_token=claimed["leaseToken"],
        review_file=review_file,
        memory_db_path=tmp_path / "memory.sqlite",
    )

    assert accepted["status"] == "accepted"
    assert reclaim_attempts == [
        {
            "status": "active_case_in_progress",
            "queueKind": "poe_bd_research_external_agent_queue",
            "sampleId": claimed["sampleId"],
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


def _write_claim_review(path: Path, claimed: dict, *, case_ref: str | None = None) -> None:
    payload = {
        "safeArtifactOnly": True,
        "deepResearchRecords": [
            {
                "sampleId": claimed["sampleId"],
                "caseRef": case_ref or claimed["sourceHashRef"],
                "safeEvidenceRef": f"evidence:{claimed['packetSafeHash'][:16]}",
            }
        ],
        "candidateReviews": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


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


def _rich_sample_xml() -> str:
    nodes = ",".join(str(value) for value in range(100, 160))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Witch" ascendClassName="Blood Mage" mainSocketGroup="1" />
  <Skills activeSkillSet="1">
    <SkillSet id="1">
      <Skill enabled="true"><Gem nameSpec="Plasma Blast" skillId="PlasmaBlastPlayer" enabled="true" /><Gem nameSpec="Controlled Destruction" skillId="SupportControlledDestruction" gemId="SupportGemControlledDestruction" enabled="true" /></Skill>
      <Skill enabled="true"><Gem nameSpec="Bonestorm" skillId="BonestormPlayer" enabled="true" /><Gem nameSpec="Arcane Tempo" skillId="SupportArcaneTempo" gemId="SupportGemArcaneTempo" enabled="true" /></Skill>
      <Skill enabled="true"><Gem nameSpec="Blasphemy" skillId="BlasphemyPlayer" enabled="true" /></Skill>
    </SkillSet>
  </Skills>
  <Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="{nodes}" nodes1="201,202" nodes2="301" /></Tree>
  <Items activeItemSet="1">
    <Item id="1">Rarity: RARE\nResearch Wand\nAttuned Wand\nItem Level: 90\n+3 to Level of all Spell Skills\n80% increased Spell Damage</Item>
    <Item id="2">Rarity: UNIQUE\nResearch Armour\nSilk Robe\nItem Level: 90\nGain a defensive state while casting</Item>
    <ItemSet id="1"><Slot name="Weapon 1" itemId="1" /><Slot name="Body Armour" itemId="2" /></ItemSet>
  </Items>
  <Config><Input name="conditionEnemyBoss" string="Pinnacle" /><Input name="conditionCritRecently" boolean="true" /></Config>
</PathOfBuilding2>
"""


def test_research_packet_marks_mutated_item_modifiers_without_raw_xml():
    from server.knowledge import research_packet

    parsed = research_packet._parse_item_text(
        """Rarity: UNIQUE
Rathpith Globe
Omen Crest Shield
Item Level: 90
{mutated} 20% increased Spell Damage per 100 Maximum Mana
10% increased Critical Hit Chance per 100 Maximum Life"""
    )

    assert parsed["itemStates"] == ["mutated"]
    assert parsed["mutatedModifiers"] == ["20% increased Spell Damage per 100 Maximum Mana"]
    assert "rawXml" not in parsed


def test_research_packet_builds_safe_active_skill_evidence_manifest():
    from server.knowledge import research_packet

    manifest = research_packet.build_skill_evidence_manifest(
        {"rawContext": {"rawXml": _rich_sample_xml()}}
    )

    assert [
        [skill["name"] for skill in item["activeSkills"]] for item in manifest["activeSkillGroups"]
    ] == [
        ["Plasma Blast"],
        ["Bonestorm"],
        ["Blasphemy"],
    ]
    assert manifest["activeSkillGroups"][0]["supports"] == [
        {"name": "Controlled Destruction", "gemId": "SupportGemControlledDestruction"}
    ]
    assert manifest["noRawMatureBuildMaterial"] is True
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert "<Skills" not in serialized
    assert "rawXml" not in serialized


def test_compact_accept_report_only_for_clean_results():
    from scripts import research_mature_builds as rmb

    clean = {
        "status": "accepted",
        "deferredCandidateCount": 0,
        "caseCoverageGapCount": 0,
        "unresolvedDeepRecordMentionCount": 0,
        "unresolvedUniqueComponentCount": 0,
    }
    assert rmb._should_compact_report(clean) is True
    assert rmb._should_compact_report({**clean, "deferredCandidateCount": 1}) is False
    assert rmb._should_compact_report({**clean, "status": "validation_failed"}) is False
    assert rmb._should_compact_report({**clean, "unresolvedDeepRecordComponentCount": 2}) is False
    assert rmb._should_compact_report({**clean, "caseCoverageGapCount": 1}) is False
    assert rmb._should_compact_report({**clean, "status": "validation_passed"}) is True


def test_compact_accept_result_strips_bulk_blocks_and_keeps_quality_summary():
    from scripts import research_mature_builds as rmb

    result = {
        "status": "accepted",
        "sampleId": "case:fixture",
        "acceptedDeepRecordCount": 2,
        "deferredReasonCounts": {},
        "mechanicAudit": {
            "entryCount": 10,
            "pinnedRevisionCount": 6,
            "liveEvidenceStatus": "partial",
            "schemaIssueCount": 0,
            "unauditedHighRiskRecordCount": 0,
            "entries": [{"index": 0, "claim": "long claim body"}],
        },
        "sourceEvidenceDiagnostics": {"available": True, "unstructuredSourceSupportMentions": []},
        "patternWrite": {"status": "accepted", "patternIds": ["bdp-1"]},
        "deepRecordWrite": {"status": "accepted", "recordWrites": [{"title": "long canonical"}]},
        "deferredCandidates": [],
        "noRawMatureBuildMaterial": True,
    }
    compact = rmb._compact_accept_result(result)

    assert compact["mechanicAudit"] == {
        "entryCount": 10,
        "pinnedRevisionCount": 6,
        "liveEvidenceStatus": "partial",
        "schemaIssueCount": 0,
        "unauditedHighRiskRecordCount": 0,
    }
    assert "entries" not in compact["mechanicAudit"]
    assert "sourceEvidenceDiagnostics" not in compact
    assert "patternWrite" not in compact
    assert "deepRecordWrite" not in compact
    assert "deferredCandidates" not in compact
    assert compact["acceptedDeepRecordCount"] == 2
    assert compact["status"] == "accepted"
    assert compact["noRawMatureBuildMaterial"] is True


def test_research_packet_captures_unslotted_jewel_items():
    from server.knowledge import research_packet

    metadata = research_packet._passive_node_metadata("0_5")
    socket_ids = [
        node_id
        for node_id, meta in metadata.items()
        if "jewel_socket" in (meta.get("nodeTypes") or [])
    ]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="{socket_ids[0]}" /></Tree>
  <Items activeItemSet="1">
    <Item id="1">Rarity: RARE\nRapture Curio\nTime-Lost Ruby\nItem Level: 80\nLevelReq: 0\nRadius: Large\nUpgrades Radius to Large\nNotable Passive Skills in Radius also grant 5% increased Life Regeneration rate\nSmall Passive Skills in Radius also grant 2% increased Fire Damage\nSmall Passive Skills in Radius also grant 3% increased Warcry Speed</Item>
    <Item id="2">Rarity: RARE\nFate Core\nSiege Crossbow\nItem Level: 80\nLevelReq: 79\nAdds 92 to 143 Fire Damage</Item>
    <ItemSet id="1"><Slot name="Weapon 1 Swap" itemId="2" /></ItemSet>
  </Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}
    sections = research_packet._packet_sections(packet)
    jewel_items = [item for item in sections["gear"] if "Time-Lost" in str(item.get("base") or "")]
    assert len(jewel_items) == 1
    assert jewel_items[0]["slot"] == "Jewel"
    assert jewel_items[0]["name"] == "Rapture Curio"
    assert any(
        "Notable Passive Skills in Radius also grant" in mod for mod in jewel_items[0]["modifiers"]
    )
    assert any(
        "Small Passive Skills in Radius also grant 2% increased Fire Damage" in mod
        for mod in jewel_items[0]["modifiers"]
    )
    counts = research_packet.jewel_counts(packet, sections=sections)
    assert counts["allocatedJewelSocketCount"] == 1
    assert counts["socketedJewelCount"] == 1
    assert research_packet.jewel_advisories(packet, sections=sections) == []
    from server.knowledge import research_packet

    metadata = research_packet._passive_node_metadata("0_5")
    socket_ids = [
        node_id
        for node_id, meta in metadata.items()
        if "jewel_socket" in (meta.get("nodeTypes") or [])
    ]
    assert socket_ids, "0_5 tree must expose jewel socket nodes for this fixture"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="{socket_ids[0]}" /></Tree>
  <Items activeItemSet="1"><ItemSet id="1" /></Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}
    counts = research_packet.jewel_counts(packet)

    assert counts["status"] == "ok"
    assert counts["allocatedJewelSocketCount"] == 1
    assert counts["socketedJewelCount"] == 0
    assert any("jewel socket" in item for item in research_packet.jewel_advisories(packet))


def test_research_packet_jewel_counts_counts_socketed_jewels():
    from server.knowledge import research_packet

    metadata = research_packet._passive_node_metadata("0_5")
    socket_ids = [
        node_id
        for node_id, meta in metadata.items()
        if "jewel_socket" in (meta.get("nodeTypes") or [])
    ]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="1"><Spec id="1" treeVersion="0_5" nodes="{socket_ids[0]}" /></Tree>
  <Items activeItemSet="1">
    <Item id="3">Rarity: RARE\nResearch Jewel\nEmerald\nItem Level: 82\n12% increased Attack Speed</Item>
    <ItemSet id="1"><Slot name="Jewel 1" itemId="3" /></ItemSet>
  </Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}
    counts = research_packet.jewel_counts(packet)

    assert counts["status"] == "ok"
    assert counts["allocatedJewelSocketCount"] == 1
    assert counts["socketedJewelCount"] == 1
    assert research_packet.jewel_advisories(packet) == []


def test_research_packet_jewel_counts_flags_tree_data_missing():
    from server.knowledge import research_packet

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" className="Mercenary" ascendClassName="Gemling Legionnaire" mainSocketGroup="1" />
  <Tree activeSpec="1"><Spec id="1" treeVersion="0_5_unknown_tree" nodes="2491" /></Tree>
  <Items activeItemSet="1"><ItemSet id="1" /></Items>
</PathOfBuilding2>
"""
    packet = {"rawContext": {"rawXml": xml}}
    counts = research_packet.jewel_counts(packet)

    assert counts["status"] == "tree_data_missing"
    assert any("node metadata" in item for item in research_packet.jewel_advisories(packet))


def test_research_packet_inspect_exposes_jewel_counts_without_raw_xml():
    from server.knowledge import research_packet

    packet = {"rawContext": {"rawXml": _rich_sample_xml()}}
    inspected = research_packet.inspect_packet(packet)

    assert inspected["jewelCounts"]["status"] == "ok"
    assert isinstance(inspected["jewelCounts"]["allocatedJewelSocketCount"], int)
    assert isinstance(inspected["jewelAdvisories"], list)
    serialized = json.dumps(inspected, ensure_ascii=False)
    assert "<Tree" not in serialized
    assert "rawXml" not in serialized
