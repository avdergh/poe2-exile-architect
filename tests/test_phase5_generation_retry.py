from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from server.generation import prototype, retry, run_store
from tests.test_phase5_prototype_models import agent_submission_payload


REPO_ROOT = Path(__file__).resolve().parents[1]


def _version(memory_ref: str) -> dict[str, str]:
    return {
        "league": "Runes of Aldur",
        "ruleset": "softcore_trade",
        "gamePatch": "0.5.4",
        "passiveTreeVersion": "0_5",
        "pobVersionOrCommit": "test",
        "graphSnapshotId": "graph:test",
        "researchMemoryRef": memory_ref,
    }


def _state(snapshot: str, source_hash: str, version: dict[str, str]) -> dict[str, object]:
    return {
        "status": "available",
        "snapshotId": snapshot,
        "sourceHash": source_hash,
        "safeSummary": {"class": "Ranger", "level": "68", "mainSkill": "Lightning Arrow"},
        "testedSkillGroups": [
            {
                "groupIndex": 1,
                "role": "pob_main_group",
                "activeSkill": "Lightning Arrow",
                "activeSkills": ["Lightning Arrow"],
                "activeSkillCount": 1,
                "supports": ["Martial Tempo"],
                "enabled": True,
            }
        ],
        "missingReasons": [],
        "versionContext": version,
        "noRawMaterial": True,
    }


def _judge(
    snapshot: str,
    source_hash: str,
    version: dict[str, str],
    *,
    passed: bool,
    score: float,
) -> dict[str, object]:
    return {
        "reportId": f"judge:{snapshot}",
        "status": "evaluated",
        "hardFailures": [] if passed else ["attribute_requirement_unmet"],
        "caveats": ["projectile_count_lower_bound_caveat"],
        "aggregateScore": score,
        "rewardStrength": "limited",
        "evaluatedSnapshotId": snapshot,
        "evaluatedSourceHash": source_hash,
        "passed": passed,
        "qualityBand": "viable" if passed else "invalid",
        "versionContext": version,
        "noRawMaterial": True,
    }


def _attempt(
    base_candidate: dict[str, object],
    version: dict[str, str],
    *,
    index: int,
    passed: bool,
    score: float,
) -> dict[str, object]:
    candidate = copy.deepcopy(base_candidate)
    candidate["candidate_id"] = f"candidate:retry:{index}"
    candidate["version_context"] = version
    snapshot = f"generation:test:{index}"
    source_hash = f"hash-{index}"
    state = _state(snapshot, source_hash, version)
    judge = _judge(snapshot, source_hash, version, passed=passed, score=score)
    audit = {
        "auditId": f"audit:{index}",
        "attemptIndex": index,
        "candidateId": candidate["candidate_id"],
        "snapshotId": snapshot,
        "classification": "no_material_failure" if passed else "true_build_failure",
        "retryDecision": "accept" if passed else "retry",
        "summary": "通过当前证据验收。" if passed else "属性需求确实未满足。",
        "plannedChanges": [] if passed else ["补足缺失属性后重新评估"],
        "retainedCaveats": ["投射物重叠仍是有限证据"],
        "stopReason": None,
        "versionContext": version,
        "noRawMaterial": True,
    }
    return {
        "attemptIndex": index,
        "prototypeBuildCandidate": candidate,
        "transientBuildState": state,
        "judgeAdvisoryReport": judge,
        "failureAudit": audit,
    }


def _retry_payload(
    memory_mode: str = "no_memory",
) -> tuple[dict[str, object], list[dict[str, object]]]:
    payload = agent_submission_payload()
    query_ref = "dq-fedcba9876543210"
    version = _version("disabled:no_memory_baseline" if memory_mode == "no_memory" else query_ref)
    payload["agentRefinedBuildPrompt"]["version_context"] = version
    base_candidate = payload["prototypeBuildCandidate"]
    base_candidate["prompt_ref"] = payload["agentRefinedBuildPrompt"]["prompt_id"]
    base_candidate["tool_references"] = [
        {
            "tool_name": "get_freshness_report",
            "query_ref": "freshness:test",
            "summary": "Freshness checked.",
        }
    ]
    base_candidate["memory_references"] = []
    base_candidate["research_memory_use"] = None
    if memory_mode == "memory_assisted":
        base_candidate["tool_references"].append(
            {
                "tool_name": "query_research_memory",
                "query_ref": query_ref,
                "summary": "Relevant starter pattern queried.",
            }
        )
        base_candidate["memory_references"] = [query_ref, "drr-fedcba9876543210"]
        base_candidate["research_memory_use"] = {
            "retrieval_outcome": "matched",
            "dedupe_query_refs": [query_ref],
            "component_keys": ["skill:LightningArrowPlayer"],
            "build_family_keys": [],
            "deep_record_ids": ["drr-fedcba9876543210"],
            "pattern_ids": [],
            "semantic_edge_ids": [],
            "memory_item_ids": [],
            "insight_decisions": [
                {
                    "source_refs": ["drr-fedcba9876543210"],
                    "decision": "adopted",
                    "summary": "投射物清图需要单体补充方案。",
                    "application": "候选加入独立单体技能组并继续验证。",
                }
            ],
            "no_match_reason": None,
        }

    attempts = [
        _attempt(base_candidate, version, index=0, passed=False, score=0.2),
        _attempt(base_candidate, version, index=1, passed=True, score=0.7),
    ]
    final = attempts[-1]
    payload["prototypeBuildCandidate"] = final["prototypeBuildCandidate"]
    payload["transientBuildState"] = final["transientBuildState"]
    payload["judgeAdvisoryReport"] = final["judgeAdvisoryReport"]
    payload["generationAttempts"] = attempts
    receipts = [
        {
            "schemaVersion": 1,
            "runId": "run:test",
            "attemptIndex": attempt["attemptIndex"],
            "candidateId": attempt["prototypeBuildCandidate"]["candidate_id"],
            "transientBuildState": attempt["transientBuildState"],
            "judgeAdvisoryReport": attempt["judgeAdvisoryReport"],
        }
        for attempt in attempts
    ]
    return payload, receipts


def test_same_run_retry_builds_trusted_before_after_report():
    payload, receipts = _retry_payload("no_memory")
    reviewed = prototype.validate_and_build_human_review_packet(payload, trusted_evaluation=True)
    assert reviewed["status"] == "accepted"

    result = retry.validate_and_build_retry_report(
        reviewed["humanReviewPacket"],
        {
            "experimentContext": {
                "memoryMode": "no_memory",
                "maxRetryCount": 2,
            }
        },
        receipts,
        run_id="run:test",
    )

    assert result["status"] == "accepted"
    report = result["retryComparisonReport"]
    assert report["programmaticOutcome"] == "legality_improved"
    assert report["resolvedHardFailures"] == ["attribute_requirement_unmet"]
    assert report["scoreDelta"] == pytest.approx(0.5)
    assert [row["attemptIndex"] for row in report["attempts"]] == [0, 1]


def test_no_memory_mode_rejects_research_memory_usage():
    payload, receipts = _retry_payload("memory_assisted")
    reviewed = prototype.validate_and_build_human_review_packet(payload, trusted_evaluation=True)

    result = retry.validate_and_build_retry_report(
        reviewed["humanReviewPacket"],
        {
            "experimentContext": {
                "memoryMode": "no_memory",
                "maxRetryCount": 2,
            }
        },
        receipts,
        run_id="run:test",
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "no_memory_lane_used_research_memory"


def test_memory_assisted_mode_accepts_memory_evidence():
    payload, receipts = _retry_payload("memory_assisted")
    reviewed = prototype.validate_and_build_human_review_packet(payload, trusted_evaluation=True)

    result = retry.validate_and_build_retry_report(
        reviewed["humanReviewPacket"],
        {
            "experimentContext": {
                "memoryMode": "memory_assisted",
                "maxRetryCount": 2,
            }
        },
        receipts,
        run_id="run:test",
    )

    assert result["status"] == "accepted"
    assert result["experimentContext"]["memoryMode"] == "memory_assisted"


def test_memory_assisted_mode_accepts_explicit_no_match():
    payload, receipts = _retry_payload("memory_assisted")
    for attempt in payload["generationAttempts"]:
        candidate = attempt["prototypeBuildCandidate"]
        query_ref = candidate["research_memory_use"]["dedupe_query_refs"][0]
        candidate["memory_references"] = [query_ref]
        candidate["research_memory_use"] = {
            "retrieval_outcome": "no_matching_memory",
            "dedupe_query_refs": [query_ref],
            "component_keys": ["skill:LightningArrowPlayer"],
            "build_family_keys": [],
            "deep_record_ids": [],
            "pattern_ids": [],
            "semantic_edge_ids": [],
            "memory_item_ids": [],
            "insight_decisions": [],
            "no_match_reason": "定向 summary 查询未返回同升华或同核心技能知识。",
        }
    payload["prototypeBuildCandidate"] = payload["generationAttempts"][-1][
        "prototypeBuildCandidate"
    ]
    reviewed = prototype.validate_and_build_human_review_packet(payload, trusted_evaluation=True)

    result = retry.validate_and_build_retry_report(
        reviewed["humanReviewPacket"],
        {
            "experimentContext": {
                "memoryMode": "memory_assisted",
                "maxRetryCount": 2,
            }
        },
        receipts,
        run_id="run:test",
    )

    assert result["status"] == "accepted"


def test_memory_assisted_retry_rejects_stale_query_after_primary_skill_change():
    payload, receipts = _retry_payload("memory_assisted")
    payload["generationAttempts"][1]["transientBuildState"]["safeSummary"]["mainSkill"] = (
        "Ice Strike"
    )
    payload["prototypeBuildCandidate"] = payload["generationAttempts"][-1][
        "prototypeBuildCandidate"
    ]
    payload["transientBuildState"] = payload["generationAttempts"][-1]["transientBuildState"]
    receipts[1]["transientBuildState"] = payload["generationAttempts"][1]["transientBuildState"]
    reviewed = prototype.validate_and_build_human_review_packet(payload, trusted_evaluation=True)
    assert reviewed["status"] == "accepted"

    result = retry.validate_and_build_retry_report(
        reviewed["humanReviewPacket"],
        {
            "experimentContext": {
                "memoryMode": "memory_assisted",
                "maxRetryCount": 2,
            }
        },
        receipts,
        run_id="run:test",
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "research_memory_requery_required"
    assert result["caveats"] == ["Changed identity fields: primary_skill."]


def test_memory_assisted_mode_rejects_tool_only_memory_evidence():
    payload, receipts = _retry_payload("memory_assisted")
    for attempt in payload["generationAttempts"]:
        attempt["prototypeBuildCandidate"]["research_memory_use"] = None
    payload["prototypeBuildCandidate"] = payload["generationAttempts"][-1][
        "prototypeBuildCandidate"
    ]
    reviewed = prototype.validate_and_build_human_review_packet(payload, trusted_evaluation=True)

    result = retry.validate_and_build_retry_report(
        reviewed["humanReviewPacket"],
        {
            "experimentContext": {
                "memoryMode": "memory_assisted",
                "maxRetryCount": 2,
            }
        },
        receipts,
        run_id="run:test",
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "memory_assisted_lane_missing_memory_evidence"


def test_standard_compatibility_mode_cannot_skip_multiple_attempt_receipts():
    payload = agent_submission_payload()
    reviewed = prototype.validate_and_build_human_review_packet(payload, trusted_evaluation=True)
    assert reviewed["status"] == "accepted"
    _, receipts = _retry_payload("no_memory")

    result = retry.validate_and_build_retry_report(
        reviewed["humanReviewPacket"],
        {
            "experimentContext": {
                "memoryMode": "standard",
                "maxRetryCount": 2,
            }
        },
        receipts,
        run_id="run:test",
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_generation_attempts"


def test_run_store_keeps_three_immutable_attempt_receipts(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bound = run_store.BoundRun(
        run_id="00000000-0000-0000-0000-000000000001",
        run_dir=run_dir,
        manifest={},
    )
    version = _version("memory:test")
    for index in range(3):
        snapshot = f"generation:test:{index}"
        receipt = {
            "candidateId": f"candidate:{index}",
            "transientBuildState": _state(snapshot, f"hash-{index}", version),
            "judgeAdvisoryReport": _judge(
                snapshot,
                f"hash-{index}",
                version,
                passed=index > 0,
                score=0.2 + index * 0.2,
            ),
        }
        assert run_store.write_trusted_evaluation(bound, receipt) == index

    receipts = run_store.read_trusted_evaluations(bound)
    assert [receipt["attemptIndex"] for receipt in receipts] == [0, 1, 2]
    assert (
        json.loads(bound.trusted_evaluation_path.read_text(encoding="utf-8"))["attemptIndex"] == 2
    )
    with pytest.raises(run_store.RunStoreError, match="retry_limit_reached"):
        run_store.write_trusted_evaluation(bound, receipt)


def test_no_memory_retry_cli_validates_all_attempt_receipts(tmp_path: Path):
    env = os.environ.copy()
    env["POE_BD_CREATE_RUNS_DIR"] = str(tmp_path / "runs")
    started = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "create_build.py"),
            "start-run",
            "--memory-mode",
            "no_memory",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    run = json.loads(started.stdout)
    payload, receipts = _retry_payload("no_memory")
    payload["packet_id"] = run["packetId"]
    payload["runContext"] = run["runContext"]
    payload["agentRefinedBuildPrompt"]["prompt_id"] = run["promptId"]
    payload["agentRefinedBuildPrompt"]["request_ref"] = run["requestRef"]
    for attempt in payload["generationAttempts"]:
        attempt["prototypeBuildCandidate"]["prompt_ref"] = run["promptId"]
    payload["prototypeBuildCandidate"] = payload["generationAttempts"][-1][
        "prototypeBuildCandidate"
    ]

    run_dir = Path(run["agentOutputFile"]).parent
    receipts_dir = run_dir / "trusted-evaluations"
    receipts_dir.mkdir()
    for index, receipt in enumerate(receipts):
        receipt["runId"] = run["runContext"]["runId"]
        receipt["createdAt"] = "2026-07-10T00:00:00+00:00"
        (receipts_dir / f"attempt-{index}.json").write_text(
            json.dumps(receipt, ensure_ascii=False),
            encoding="utf-8",
        )
    (run_dir / "trusted-evaluation.json").write_text(
        json.dumps(receipts[-1], ensure_ascii=False),
        encoding="utf-8",
    )
    Path(run["agentOutputFile"]).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    reviewed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "create_build.py"),
            "review-packet",
            "--run-id",
            run["runContext"]["runId"],
            "--run-token",
            run["runContext"]["runToken"],
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    result = json.loads(reviewed.stdout)

    assert result["status"] == "accepted"
    assert result["experimentContext"]["memoryMode"] == "no_memory"
    assert result["retryComparisonReport"]["resolvedHardFailures"] == [
        "attribute_requirement_unmet"
    ]
