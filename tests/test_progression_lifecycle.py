from __future__ import annotations

import json
from types import SimpleNamespace

from server import paths
from server.generation import progression_lifecycle


ARTIFACT_ID = "final-build:lifecycle-receipt-test"
SOURCE_HASH = "source-hash-1234"
RESTORED_HASH = "restored-hash-5678"


def _result(
    *,
    status: str = "passed",
    caveats: list[str] | None = None,
    verification_required: bool = False,
) -> dict[str, object]:
    return {
        "stage": "maps_entry",
        "status": status,
        "pass": status == "passed",
        "verificationRequired": verification_required,
        "failedChecks": [] if status == "passed" else ["sustain_ok"],
        "unknownChecks": [],
        "caveats": caveats or [],
        "evidenceTags": ["engine-computed", "stage-verification"],
        "evaluatedSourceHash": SOURCE_HASH,
        "buildId": "fixture-build",
        "observationTarget": {
            "groupIndex": 2,
            "activeIndex": 1,
            "skillName": "Tempest Bell",
        },
    }


def _isolate(tmp_path, monkeypatch):
    context = SimpleNamespace(
        model_dump=lambda **_kwargs: {
            "groupIndex": 2,
            "activeIndex": 1,
            "skillName": "Tempest Bell",
            "sourceMetric": "TotalDPS",
        }
    )
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        progression_lifecycle.artifacts,
        "read_final_build_artifact_for_export",
        lambda artifact_id: (
            (
                SimpleNamespace(
                    source_hash=SOURCE_HASH,
                    judge_report=SimpleNamespace(calculation_context=context),
                ),
                "<PathOfBuilding/>",
            )
            if artifact_id == ARTIFACT_ID
            else None
        ),
    )


def test_artifact_lifecycle_receipt_round_trips_and_is_idempotent(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    first = progression_lifecycle.save_artifact_lifecycle_receipt(
        artifact_id=ARTIFACT_ID,
        source_hash=SOURCE_HASH,
        restored_engine_source_hash=RESTORED_HASH,
        result=_result(
            caveats=["Maps-entry verification remains scoped to the evaluated snapshot."]
        ),
    )
    second = progression_lifecycle.save_artifact_lifecycle_receipt(
        artifact_id=ARTIFACT_ID,
        source_hash=SOURCE_HASH,
        restored_engine_source_hash=RESTORED_HASH,
        result=_result(
            caveats=["Maps-entry verification remains scoped to the evaluated snapshot."]
        ),
    )

    assert first["status"] == "recorded"
    assert second["verificationRef"] == first["verificationRef"]
    receipt = progression_lifecycle.read_trusted_artifact_lifecycle_receipt(
        first["verificationRef"],
        artifact_id=ARTIFACT_ID,
        stage="maps_entry",
    )
    assert receipt is not None
    assert receipt["sourceHash"] == SOURCE_HASH
    assert receipt["restoredEngineSourceHash"] == RESTORED_HASH
    assert receipt["artifactBound"] is True
    assert receipt["observationTarget"]["skillName"] == "Tempest Bell"
    assert receipt["caveats"] == [
        "Maps-entry verification remains scoped to the evaluated snapshot."
    ]
    assert "xml" not in json.dumps(receipt).casefold()


def test_artifact_lifecycle_receipt_detects_payload_tampering(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    recorded = progression_lifecycle.save_artifact_lifecycle_receipt(
        artifact_id=ARTIFACT_ID,
        source_hash=SOURCE_HASH,
        restored_engine_source_hash=RESTORED_HASH,
        result=_result(),
    )
    receipt_path = (
        paths.build_progression_lifecycle_receipts_dir()
        / f"{recorded['verificationRef'].split(':', 1)[1]}.json"
    )
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["caveats"] = ["tampered"]
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    assert (
        progression_lifecycle.read_trusted_artifact_lifecycle_receipt(
            recorded["verificationRef"],
            artifact_id=ARTIFACT_ID,
            stage="maps_entry",
        )
        is None
    )


def test_artifact_lifecycle_receipt_rejects_unbounded_or_wrong_hash_results(
    tmp_path,
    monkeypatch,
):
    _isolate(tmp_path, monkeypatch)

    oversized = progression_lifecycle.save_artifact_lifecycle_receipt(
        artifact_id=ARTIFACT_ID,
        source_hash=SOURCE_HASH,
        restored_engine_source_hash=RESTORED_HASH,
        result=_result(caveats=["x" * 501]),
    )
    wrong_hash_result = _result()
    wrong_hash_result["evaluatedSourceHash"] = "different-hash"
    wrong_hash = progression_lifecycle.save_artifact_lifecycle_receipt(
        artifact_id=ARTIFACT_ID,
        source_hash=SOURCE_HASH,
        restored_engine_source_hash=RESTORED_HASH,
        result=wrong_hash_result,
    )

    assert oversized["errorCode"] == "invalid_artifact_lifecycle_result"
    assert wrong_hash["errorCode"] == "invalid_artifact_lifecycle_result"


def test_failed_artifact_lifecycle_result_is_recorded_but_not_promoted_to_pass(
    tmp_path,
    monkeypatch,
):
    _isolate(tmp_path, monkeypatch)

    recorded = progression_lifecycle.save_artifact_lifecycle_receipt(
        artifact_id=ARTIFACT_ID,
        source_hash=SOURCE_HASH,
        restored_engine_source_hash=RESTORED_HASH,
        result=_result(status="failed"),
    )
    receipt = progression_lifecycle.read_trusted_artifact_lifecycle_receipt(
        recorded["verificationRef"],
        artifact_id=ARTIFACT_ID,
        stage="maps_entry",
    )

    assert receipt is not None
    assert receipt["status"] == "failed"
    assert receipt["pass"] is False
    assert receipt["failedChecks"] == ["sustain_ok"]


def test_artifact_lifecycle_receipt_preserves_conditional_pass(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    recorded = progression_lifecycle.save_artifact_lifecycle_receipt(
        artifact_id=ARTIFACT_ID,
        source_hash=SOURCE_HASH,
        restored_engine_source_hash=RESTORED_HASH,
        result=_result(verification_required=True),
    )

    receipt = progression_lifecycle.read_trusted_artifact_lifecycle_receipt(
        recorded["verificationRef"],
        artifact_id=ARTIFACT_ID,
        stage="maps_entry",
    )

    assert receipt is not None
    assert receipt["pass"] is True
    assert receipt["verificationRequired"] is True
