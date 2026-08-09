from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts import create_build
from tests.test_phase5_prototype_models import agent_submission_payload


REPO_ROOT = Path(__file__).resolve().parents[1]


def _start_run(tmp_path: Path) -> dict[str, object]:
    env = os.environ.copy()
    env["POE_BD_CREATE_RUNS_DIR"] = str(tmp_path / "runs")
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "create_build.py"),
            "start-run",
            "--memory-mode",
            "standard",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    result = json.loads(completed.stdout)
    result["_runsDir"] = str(tmp_path / "runs")
    return result


def test_start_run_defaults_to_memory_assisted(tmp_path: Path):
    env = os.environ.copy()
    env["POE_BD_CREATE_RUNS_DIR"] = str(tmp_path / "runs")

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "create_build.py"),
            "start-run",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    result = json.loads(completed.stdout)
    assert result["experimentContext"]["memoryMode"] == "memory_assisted"
    assert result["experimentContext"]["globalOptimizerAllowed"] is False
    assert result["experimentContext"]["passiveTreeOptimizationMode"] == "manual_targeted"
    assert result["experimentContext"]["mutationBatchPreferred"] is True


def test_start_run_initializes_bound_agent_output_template(tmp_path: Path):
    run = _start_run(tmp_path)

    template = json.loads(Path(str(run["agentOutputFile"])).read_text(encoding="utf-8"))

    assert run["agentOutputTemplateInitialized"] is True
    assert template["runContext"] == run["runContext"]
    assert template["packetId"] == run["packetId"]
    assert template["agentRefinedBuildPrompt"] == {
        "promptId": run["promptId"],
        "requestRef": run["requestRef"],
    }


def test_plugin_start_generation_run_manages_storage_without_exposing_paths(
    tmp_path: Path, monkeypatch
):
    runs = tmp_path / "managed-runs"
    monkeypatch.setenv("POE_BD_CREATE_RUNS_DIR", str(runs))

    result = create_build.start_generation_run("memory_assisted")

    assert result["status"] == "started"
    assert result["storage"] == "managed_user_data"
    assert "agentOutputFile" not in result
    assert "reviewResultFile" not in result
    run_id = result["runContext"]["runId"]
    assert (runs / run_id / "run-manifest.json").is_file()
    assert (runs / run_id / "agent-output.json").is_file()


def _bind_submission_to_run(payload: dict[str, object], run: dict[str, object]) -> None:
    payload["packet_id"] = run["packetId"]
    payload["runContext"] = run["runContext"]
    prompt = payload["agentRefinedBuildPrompt"]
    candidate = payload["prototypeBuildCandidate"]
    assert isinstance(prompt, dict)
    assert isinstance(candidate, dict)
    prompt["prompt_id"] = run["promptId"]
    prompt["request_ref"] = run["requestRef"]
    candidate["prompt_ref"] = run["promptId"]
    # Most CLI tests exercise run binding/consumption rather than Research provenance.
    # Remove the generic model fixture's synthetic Research IDs so those tests do not
    # depend on a user's real local Research database.
    candidate["research_memory_use"] = None


def _review_command(run: dict[str, object]) -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "create_build.py"),
        "review-packet",
        "--run-id",
        str(run["runContext"]["runId"]),
        "--run-token",
        str(run["runContext"]["runToken"]),
    ]


def _review_env(run: dict[str, object]) -> dict[str, str]:
    env = os.environ.copy()
    env["POE_BD_CREATE_RUNS_DIR"] = str(run["_runsDir"])
    return env


def test_ordinary_create_cannot_skip_a_receipt_premise_audit():
    payload = agent_submission_payload()
    candidate = payload["prototypeBuildCandidate"]
    assert isinstance(candidate, dict)
    usage = candidate["research_memory_use"]
    assert isinstance(usage, dict)
    usage["build_family_keys"] = ["bf-1234567890abcdef"]
    receipt = {
        "dedupeQueryRef": "dq-0123456789abcdef",
        "result": {
            "buildFamilies": [
                {"buildFamilyKey": "bf-1234567890abcdef"},
            ],
            "deepRecordIds": ["drr-1234567890abcdef"],
            "patternIds": ["bdp-1234567890abcdef"],
            "semanticEdgeIds": [],
            "memoryItemIds": [],
            "deepReadRecordIds": [],
            "premiseAuditVersion": 1,
            "familyPremiseCatalog": [
                {
                    "premiseId": "rp-0123456789abcdef",
                    "buildFamilyKey": "bf-1234567890abcdef",
                    "recordId": "drr-1234567890abcdef",
                    "recordKind": "failure_mode",
                    "premiseType": "failure_condition",
                    "text": "目标场景中的基础资源生成方式会失效。",
                    "componentKeys": ["skill:LightningArrowPlayer"],
                }
            ],
        },
    }
    canonical_payload = {
        "prototypeBuildCandidate": {
            "researchMemoryUse": {
                "retrievalOutcome": usage["retrieval_outcome"],
                "dedupeQueryRefs": usage["dedupe_query_refs"],
                "componentKeys": usage["component_keys"],
                "buildFamilyKeys": usage["build_family_keys"],
                "deepRecordIds": usage["deep_record_ids"],
                "patternIds": usage["pattern_ids"],
                "semanticEdgeIds": usage["semantic_edge_ids"],
                "memoryItemIds": usage["memory_item_ids"],
                "insightDecisions": [
                    {
                        "sourceRefs": item["source_refs"],
                        "decision": item["decision"],
                        "summary": item["summary"],
                        "application": item["application"],
                    }
                    for item in usage["insight_decisions"]
                ],
                "premiseAuditVersion": None,
                "premiseDecisions": [],
                "noMatchReason": None,
            }
        }
    }

    error, _caveats = create_build._validate_candidate_research_use(
        canonical_payload,
        receipt_reader=lambda _ref: receipt,
    )

    assert error == "progression_research_premise_audit_required"


def test_ordinary_create_rejects_a_deep_read_receipt_not_seen_in_this_run():
    canonical_payload = {
        "prototypeBuildCandidate": {
            "researchMemoryUse": {
                "retrievalOutcome": "matched",
                "dedupeQueryRefs": ["dq-0123456789abcdef"],
                "componentKeys": ["skill:LightningArrowPlayer"],
                "buildFamilyKeys": ["bf-1234567890abcdef"],
                "deepRecordIds": ["drr-1234567890abcdef"],
                "patternIds": [],
                "semanticEdgeIds": [],
                "memoryItemIds": [],
                "insightDecisions": [
                    {
                        "sourceRefs": ["drr-1234567890abcdef"],
                        "decision": "adopted",
                        "summary": "Use the selected record.",
                        "application": "Apply it to the candidate.",
                    }
                ],
                "premiseAuditVersion": None,
                "premiseDecisions": [],
                "noMatchReason": None,
            }
        }
    }
    receipt = {
        "dedupeQueryRef": "dq-0123456789abcdef",
        "lastSeenAt": "2026-07-29T00:00:00+00:00",
        "result": {
            "buildFamilies": [{"buildFamilyKey": "bf-1234567890abcdef"}],
            "deepRecordIds": ["drr-1234567890abcdef"],
            "patternIds": [],
            "semanticEdgeIds": [],
            "memoryItemIds": [],
        },
    }

    error, _caveats = create_build._validate_candidate_research_use(
        canonical_payload,
        receipt_reader=lambda _ref: receipt,
        not_before="2026-07-30T00:00:00+00:00",
    )

    assert error == "progression_research_receipt_not_current_run"


def _attach_trusted_evaluation(payload: dict[str, object], run: dict[str, object]) -> None:
    context = payload["agentRefinedBuildPrompt"]["version_context"]
    candidate_id = payload["prototypeBuildCandidate"]["candidate_id"]
    state = {
        "status": "available",
        "snapshotId": "generation:test:snapshot",
        "sourceHash": "0123456789abcdef",
        "safeSummary": {"class": "Ranger", "level": "68", "mainSkill": "Lightning Arrow"},
        "testedSkillGroups": [
            {
                "role": "main_damage",
                "activeSkill": "Lightning Arrow",
                "supports": ["Martial Tempo"],
                "enabled": True,
            }
        ],
        "missingReasons": [],
        "versionContext": context,
        "noRawMaterial": True,
    }
    judge = {
        "reportId": "judge:generation:test:snapshot",
        "status": "evaluated",
        "passed": True,
        "hardFailures": [],
        "caveats": ["test_caveat"],
        "aggregateScore": 0.55,
        "rewardStrength": "limited",
        "evaluatedSnapshotId": "generation:test:snapshot",
        "evaluatedSourceHash": "0123456789abcdef",
        "versionContext": context,
        "noRawMaterial": True,
    }
    payload["transientBuildState"] = state
    payload["judgeAdvisoryReport"] = judge
    receipt = {
        "schemaVersion": 1,
        "runId": run["runContext"]["runId"],
        "attemptIndex": 0,
        "candidateId": candidate_id,
        "createdAt": "2026-07-10T00:00:00+00:00",
        "transientBuildState": state,
        "judgeAdvisoryReport": judge,
    }
    receipt_path = Path(str(run["agentOutputFile"])).parent / "trusted-evaluation.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    attempts_dir = receipt_path.parent / "trusted-evaluations"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    (attempts_dir / "attempt-0.json").write_text(
        json.dumps(receipt, ensure_ascii=False),
        encoding="utf-8",
    )


def _compact_submission(payload: dict[str, object], run: dict[str, object]) -> dict[str, object]:
    prompt = payload["agentRefinedBuildPrompt"]
    candidate = payload["prototypeBuildCandidate"]
    state = payload["transientBuildState"]
    assert isinstance(prompt, dict)
    assert isinstance(candidate, dict)
    assert isinstance(state, dict)
    audit = {
        "auditId": "audit:test:0",
        "attemptIndex": 0,
        "candidateId": candidate["candidate_id"],
        "snapshotId": state["snapshotId"],
        "classification": "no_material_failure",
        "retryDecision": "accept",
        "summary": "可信快照已通过确定性合法性检查。",
        "plannedChanges": [],
        "retainedCaveats": ["仍需人工确认玩法手感。"],
        "stopReason": None,
        "versionContext": prompt["version_context"],
        "noRawMaterial": True,
    }
    return {
        "schemaVersion": 2,
        "runContext": run["runContext"],
        "packetId": run["packetId"],
        "agentRefinedBuildPrompt": prompt,
        "toolFeedbackEvents": [],
        "generationAttempts": [
            {
                "attemptIndex": 0,
                "prototypeBuildCandidate": candidate,
                "failureAudit": audit,
            }
        ],
    }


def test_create_build_review_packet_cli_outputs_safe_human_review_packet(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    _attach_trusted_evaluation(payload, run)
    submission_file = Path(str(run["agentOutputFile"]))
    submission_file.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.stdout, (
        f"review helper produced no stdout; returncode={completed.returncode}; "
        f"stderr={completed.stderr}"
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "accepted"
    assert payload["humanReviewPacket"]["packetId"] == run["packetId"]
    assert payload["humanReviewPacket"]["judgeAdvisoryReport"]["status"] == "evaluated"
    assert payload["humanReviewPacket"]["recommendedNextAction"] == "ready_for_human_review"
    assert "rawTranscript" not in completed.stdout
    assert "chainOfThought" not in completed.stdout
    assert "pobb.in" not in completed.stdout


def test_validate_output_hydrates_compact_attempt_without_consuming_run(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    _attach_trusted_evaluation(payload, run)
    compact = _compact_submission(payload, run)
    Path(str(run["agentOutputFile"])).write_text(
        json.dumps(compact, ensure_ascii=False),
        encoding="utf-8",
    )

    validate_command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "create_build.py"),
        "validate-output",
        "--run-id",
        str(run["runContext"]["runId"]),
        "--run-token",
        str(run["runContext"]["runToken"]),
    ]
    first = subprocess.run(
        validate_command,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )
    second = subprocess.run(
        validate_command,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    first_result = json.loads(first.stdout)
    assert first_result["status"] == "accepted"
    assert first_result["validationOnly"] is True
    assert first_result["attemptCount"] == 1
    assert first_result["lifecycleEvidenceCoverage"] == {
        "coverageStatus": "partial",
        "evaluatedStages": ["maps_entry"],
        "textOnlyStages": ["campaign_late"],
        "evaluatedLevel": 68,
        "sourceSnapshotId": "generation:test:snapshot",
    }
    assert json.loads(second.stdout)["status"] == "accepted"
    assert not Path(str(run["reviewResultFile"])).exists()
    assert not (Path(str(run["agentOutputFile"])).parent / "review-consumed").exists()

    review_command = _review_command(run)
    review_command.insert(3, "--compact")
    reviewed = subprocess.run(
        review_command,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )
    reviewed_result = json.loads(reviewed.stdout)
    assert reviewed_result["status"] == "accepted"
    assert reviewed_result["validationOnly"] is False
    assert Path(str(run["reviewResultFile"])).is_file()
    assert "humanReviewPacket" not in reviewed_result


def test_raw_agent_output_is_scanned_before_trusted_fields_are_hydrated(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    _attach_trusted_evaluation(payload, run)
    payload["transientBuildState"]["safeSummary"] = {
        "rawXml": "<PathOfBuilding><Build /></PathOfBuilding>"
    }
    Path(str(run["agentOutputFile"])).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["errorCode"] == "copy_safety_violation"


def test_compact_attempt_rejects_conflicting_trusted_field_aliases(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    _attach_trusted_evaluation(payload, run)
    compact = _compact_submission(payload, run)
    attempt = compact["generationAttempts"][0]
    attempt["transientBuildState"] = payload["transientBuildState"]
    attempt["transient_build_state"] = {
        **payload["transientBuildState"],
        "sourceHash": "tampered-hash",
    }
    Path(str(run["agentOutputFile"])).write_text(
        json.dumps(compact, ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["errorCode"] == "invalid_schema"


def test_create_build_review_packet_cli_requires_trusted_evaluation(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    Path(str(run["agentOutputFile"])).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["errorCode"] == "missing_trusted_evaluation"


def test_create_build_review_packet_cli_rejects_tampered_judge_result(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    _attach_trusted_evaluation(payload, run)
    payload["judgeAdvisoryReport"]["aggregateScore"] = 0.99
    Path(str(run["agentOutputFile"])).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["errorCode"] == "trusted_evaluation_mismatch"


def test_create_build_review_packet_cli_rejects_copyable_agent_output(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    payload["prototypeBuildCandidate"]["gear_roles"].append(
        "weapon: rare copied bow https://pobb.in/abcd"
    )
    submission_file = Path(str(run["agentOutputFile"]))
    submission_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "rejected"
    assert payload["errorCode"] == "copy_safety_violation"
    assert "pobb.in" not in completed.stdout


def test_create_build_review_packet_cli_wraps_malformed_json_as_safe_error(tmp_path):
    run = _start_run(tmp_path)
    submission_file = Path(str(run["agentOutputFile"]))
    submission_file.write_text("{ not json", encoding="utf-8")

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "rejected"
    assert payload["errorCode"] == "invalid_input"
    assert "Traceback" not in completed.stderr
    assert "not json" not in completed.stdout


def test_create_build_review_packet_cli_wraps_invalid_utf8_as_safe_error(tmp_path):
    run = _start_run(tmp_path)
    submission_file = Path(str(run["agentOutputFile"]))
    submission_file.write_bytes(b"\xff\xfe\xfa")

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.stdout, (
        f"review helper produced no stdout; returncode={completed.returncode}; "
        f"stderr={completed.stderr}"
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "rejected"
    assert payload["errorCode"] == "invalid_input"
    assert "Traceback" not in completed.stderr


def test_create_build_review_packet_cli_wraps_non_object_json_as_safe_error(tmp_path):
    run = _start_run(tmp_path)
    submission_file = Path(str(run["agentOutputFile"]))
    submission_file.write_text("[]", encoding="utf-8")

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "rejected"
    assert payload["errorCode"] == "invalid_input"
    assert "Traceback" not in completed.stderr


def test_create_build_review_packet_cli_wraps_packet_consistency_errors(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    _attach_trusted_evaluation(payload, run)
    payload["prototypeBuildCandidate"]["prompt_ref"] = "prompt:other"
    submission_file = Path(str(run["agentOutputFile"]))
    submission_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "rejected"
    assert payload["errorCode"] == "invalid_schema"
    assert payload["caveats"] == ["input: Value error, candidate prompt_ref must match prompt_id"]
    assert "Traceback" not in completed.stderr


def test_create_build_review_packet_cli_wraps_unreadable_file_as_safe_error(tmp_path):
    run = _start_run(tmp_path)
    Path(str(run["agentOutputFile"])).unlink()

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "rejected"
    assert payload["errorCode"] == "invalid_input"
    assert "Traceback" not in completed.stderr


def test_create_build_review_packet_cli_rejects_old_unbound_artifact(tmp_path):
    run = _start_run(tmp_path)
    submission_file = Path(str(run["agentOutputFile"]))
    submission_file.write_text(
        json.dumps(agent_submission_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 1
    assert payload["status"] == "rejected"
    assert payload["errorCode"] == "run_binding_mismatch"


def test_create_build_review_packet_cli_rejects_file_outside_current_run(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    old_file = tmp_path / "old_agent_output.json"
    old_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    Path(str(run["agentOutputFile"])).unlink()

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    result = json.loads(completed.stdout)
    assert completed.returncode == 1
    assert result["errorCode"] == "invalid_input"


def test_create_build_review_packet_cli_consumes_accepted_run(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    _attach_trusted_evaluation(payload, run)
    submission_file = Path(str(run["agentOutputFile"]))
    submission_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    first = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )
    second = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert json.loads(first.stdout)["status"] == "accepted"
    assert Path(str(run["reviewResultFile"])).is_file()
    assert second.returncode == 1
    assert json.loads(second.stdout)["errorCode"] == "run_already_consumed"


def test_create_build_review_packet_cli_allows_only_one_concurrent_accept(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    _attach_trusted_evaluation(payload, run)
    Path(str(run["agentOutputFile"])).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    processes = [
        subprocess.Popen(
            _review_command(run),
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_review_env(run),
        )
        for _ in range(2)
    ]

    completed = [process.communicate(timeout=30) for process in processes]
    results = [json.loads(stdout) for stdout, _ in completed]

    assert sum(result["status"] == "accepted" for result in results) == 1
    rejected = next(result for result in results if result["status"] == "rejected")
    assert rejected["errorCode"] == "run_already_consumed"


def test_create_build_review_packet_cli_rejects_wrong_run_token(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    Path(str(run["agentOutputFile"])).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    command = _review_command(run)
    command[-1] = "wrong-token"

    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["errorCode"] == "run_binding_mismatch"


def test_create_build_review_packet_cli_rejects_expired_run(tmp_path):
    run = _start_run(tmp_path)
    manifest_path = Path(str(run["agentOutputFile"])).parent / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["startedAt"] = "2020-01-01T00:00:00+00:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["errorCode"] == "run_expired"


def test_create_build_review_packet_cli_rejects_conflicting_packet_id_aliases(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    payload["packet_id"] = "human-review:wrong"
    Path(str(run["agentOutputFile"])).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["errorCode"] == "run_binding_mismatch"


def test_create_build_review_packet_cli_rejects_conflicting_artifact_aliases(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    payload["prototype_build_candidate"] = {"candidate_id": "stale-candidate"}
    Path(str(run["agentOutputFile"])).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["errorCode"] == "invalid_schema"


def test_create_build_review_packet_cli_wraps_invalid_feedback_collection(tmp_path):
    run = _start_run(tmp_path)
    payload = agent_submission_payload()
    _bind_submission_to_run(payload, run)
    _attach_trusted_evaluation(payload, run)
    payload["toolFeedbackEvents"] = None
    Path(str(run["agentOutputFile"])).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["errorCode"] == "invalid_schema"
    assert "Traceback" not in completed.stderr


def test_create_build_review_packet_cli_never_echoes_manifest_payload(tmp_path):
    run = _start_run(tmp_path)
    manifest_path = Path(str(run["agentOutputFile"])).parent / "run-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "status": "rejected",
                "rawTranscript": "private transcript",
                "source": "https://pobb.in/unsafe",
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    result = json.loads(completed.stdout)
    assert completed.returncode == 1
    assert result["errorCode"] == "invalid_run_manifest"
    assert "private transcript" not in completed.stdout
    assert "pobb.in" not in completed.stdout


def test_create_build_review_packet_cli_wraps_invalid_manifest_path(tmp_path):
    run = _start_run(tmp_path)
    manifest_path = Path(str(run["agentOutputFile"])).parent / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["agentOutputFile"] = "invalid\u0000path"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    completed = subprocess.run(
        _review_command(run),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_review_env(run),
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["errorCode"] == "invalid_run_manifest"


def test_direction_layer_no_match_usage_passes_receipt_audit():
    """snake_case no_matching_memory usage + a run-fresh receipt passes the receipt audit.

    Guards the alias fix in _validate_candidate_research_use (a snake_case researchMemoryUse
    must NOT silently skip the receipt/premise audit).
    """
    from datetime import datetime, timezone

    payload = agent_submission_payload()
    candidate = payload["prototypeBuildCandidate"]
    assert isinstance(candidate, dict)
    candidate["research_memory_use"] = {
        "retrieval_outcome": "no_matching_memory",
        "dedupe_query_refs": ["dq-0123456789abcdef"],
        "component_keys": [],
        "build_family_keys": [],
        "deep_record_ids": [],
        "pattern_ids": [],
        "semantic_edge_ids": [],
        "memory_item_ids": [],
        "insight_decisions": [],
        "premise_audit_version": None,
        "premise_decisions": [],
        "no_match_reason": "知识库无匹配记忆，以图/机制与模型知识设计",
    }
    receipt = {
        "dedupeQueryRef": "dq-0123456789abcdef",
        "lastSeenAt": datetime.now(timezone.utc).isoformat(),
        "result": {},
    }
    error, _caveats = create_build._validate_candidate_research_use(
        payload,
        receipt_reader=lambda _ref: receipt,
    )
    assert error is None

    # A stale receipt must still be caught through the snake_case path.
    stale = dict(receipt)
    stale["lastSeenAt"] = "2026-01-01T00:00:00+00:00"
    error, caveats = create_build._validate_candidate_research_use(
        payload,
        receipt_reader=lambda _ref: stale,
        not_before="2026-07-01T00:00:00+00:00",
    )
    assert error == "progression_research_receipt_not_current_run"
    assert caveats and "dq-0123456789abcdef" in caveats[0]
