from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
        "candidateId": candidate_id,
        "createdAt": "2026-07-10T00:00:00+00:00",
        "transientBuildState": state,
        "judgeAdvisoryReport": judge,
    }
    receipt_path = Path(str(run["agentOutputFile"])).parent / "trusted-evaluation.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")


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
    assert "Traceback" not in completed.stderr


def test_create_build_review_packet_cli_wraps_unreadable_file_as_safe_error(tmp_path):
    run = _start_run(tmp_path)

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
    assert "Traceback" not in completed.stderr
