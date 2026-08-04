from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from server import paths
from server.generation import progression_delivery, progression_service


def test_progression_delivery_has_fixed_multistage_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    route = {
        "routeId": "11111111-1111-1111-1111-111111111111",
        "routeName": "Monk Progression",
        "classShell": "Monk",
        "targetArtifactId": "final-build:target",
        "routeSummary": "A safe route summary.",
        "qualityStatus": "verified",
        "targetDesignCoverage": {
            "unresolvedCaveats": ["The longest boss resource loop remains only partially verified."]
        },
        "artifactFacts": [
            {
                "artifactId": "final-build:starter",
                "judgeScoreApplicability": "applicable",
                "judgeModelabilityStatus": "full",
                "judgePlayabilityFailures": [],
                "judgeQualityWarnings": [],
                "judgeCaveats": [],
            },
            {
                "artifactId": "final-build:target",
                "judgeScoreApplicability": "unavailable",
                "judgeModelabilityStatus": "partial",
                "judgePlayabilityFailures": ["Recovery needs manual validation."],
                "judgeQualityWarnings": [],
                "judgeCaveats": ["Target delivery is only partially modelled."],
            },
        ],
        "stages": [
            {
                "stageId": "stage:starter-20",
                "targetLevel": 20,
                "routeRole": "starter_bootstrap",
                "lifecycleStage": "campaign_early",
                "evidenceStatus": "supported",
                "purpose": "Establish the starter.",
                "playPattern": "Use the starter loop.",
                "costProfileRef": "progression-cost:starter",
                "transitionBridge": None,
                "caveats": [],
                "artifactId": "final-build:starter",
            },
            {
                "stageId": "stage:target-80",
                "targetLevel": 80,
                "routeRole": "target",
                "lifecycleStage": "maps_entry",
                "evidenceStatus": "supported",
                "purpose": "Establish the target.",
                "playPattern": "Use the target loop.",
                "costProfileRef": "progression-cost:target",
                "costProfile": {
                    "league": "Test League",
                    "baseCurrency": "Exalted Orb",
                    "highestRequiredBand": "expensive",
                    "paidDependencyCount": 2,
                    "requiredDependencyCount": 3,
                    "unknownRequiredDependencyCount": 1,
                    "fallbackCoverage": 0.667,
                    "livePriceCoverage": 0.5,
                    "costEvidenceStatus": "limited",
                },
                "changesFromPrevious": [
                    {
                        "category": "skill",
                        "action": "replace",
                        "subject": "Target Skill",
                        "replaces": "Starter Skill",
                        "reason": "The target resource loop is now stable.",
                    }
                ],
                "acquisitionPriorities": ["Secure the target weapon before switching."],
                "transitionBridge": {
                    "summary": "Switch after the resource loop is stable.",
                    "requirements": [
                        {
                            "status": "satisfied",
                            "description": "Resource loop verified.",
                        }
                    ],
                },
                "caveats": [],
                "artifactId": "final-build:target",
            },
        ],
    }
    monkeypatch.setattr(
        progression_delivery.progression,
        "read_progression_route",
        lambda _route_id: route,
    )
    monkeypatch.setattr(
        progression_delivery.artifacts,
        "read_final_build_artifact_for_export",
        lambda artifact_id: (
            SimpleNamespace(artifact_id=artifact_id, source_hash=f"hash:{artifact_id}"),
            "<PathOfBuilding><Build/></PathOfBuilding>",
        ),
    )

    def export_official(*_args, **kwargs):
        destination = kwargs["_destination_path"]
        destination.write_text("{}", encoding="utf-8")
        return {
            "status": "exported",
            "outputPath": str(destination),
            "warnings": [],
        }

    monkeypatch.setattr(
        progression_delivery.build_planner_exporter,
        "export_final_build_artifact",
        export_official,
    )

    result = progression_delivery.export_build_progression_package(
        route["routeId"],
        name="Monk Route",
    )

    assert result["status"] == "exported"
    assert result["expectedCount"] == 6
    assert result["exportedCount"] == 6
    assert result["officialBuildScope"] == "target_stage_only"
    assert [row["artifactType"] for row in result["artifacts"]].count("target_official_build") == 1
    for row in result["artifacts"]:
        assert Path(row["outputPath"]).is_file()
    guide = next(
        row for row in result["artifacts"] if row["artifactType"] == "progression_route_guide"
    )
    text = Path(guide["outputPath"]).read_text(encoding="utf-8")
    assert "价格档位只用于说明获取风险" in text
    assert "未知必需依赖 1" in text
    assert "实时价格覆盖 0.5" in text
    assert "Target Skill（替换 Starter Skill）" in text
    assert "Secure the target weapon before switching." in text
    assert "Recovery needs manual validation." in text
    assert "目标 Research / 机制限制" in text
    assert "longest boss resource loop" in text
    assert "PathOfBuilding" not in text


def test_progression_delivery_reports_each_failed_format(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    route = {
        "routeId": "11111111-1111-1111-1111-111111111111",
        "routeName": "Broken Route",
        "classShell": "Monk",
        "targetArtifactId": "final-build:missing",
        "routeSummary": "A safe route summary.",
        "qualityStatus": "limited",
        "stages": [
            {
                "stageId": "stage:target-80",
                "targetLevel": 80,
                "routeRole": "target",
                "lifecycleStage": "maps_entry",
                "evidenceStatus": "limited",
                "purpose": "Target.",
                "playPattern": "Target loop.",
                "costProfileRef": None,
                "transitionBridge": None,
                "caveats": [],
                "artifactId": "final-build:missing",
            }
        ],
    }
    monkeypatch.setattr(
        progression_delivery.progression,
        "read_progression_route",
        lambda _route_id: route,
    )
    monkeypatch.setattr(
        progression_delivery.artifacts,
        "read_final_build_artifact_for_export",
        lambda _artifact_id: None,
    )
    monkeypatch.setattr(
        progression_delivery.build_planner_exporter,
        "export_final_build_artifact",
        lambda *_args, **_kwargs: {
            "status": "rejected",
            "errorCode": "converter_unavailable",
        },
    )

    result = progression_delivery.export_build_progression_package(route["routeId"])
    assert result["status"] == "partial"
    assert result["expectedCount"] == 4
    failed = {
        row["artifactType"]: row["errorCode"]
        for row in result["artifacts"]
        if row["status"] == "failed"
    }
    assert failed["stage_pob_xml"] == "final_artifact_invalid"
    assert failed["stage_pob_import_code"] == "final_artifact_invalid"
    assert failed["target_official_build"] == "converter_unavailable"


@pytest.mark.parametrize("anchor_status", ["bound", "anchor_bound"])
def test_failed_progression_exports_a_clearly_incomplete_target_recovery(
    tmp_path,
    monkeypatch,
    anchor_status,
):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    state = {
        "progressionId": "22222222-2222-2222-2222-222222222222",
        "status": "failed",
        "request": {"baseClass": "Monk", "targetLevel": 85},
        "targetAnchor": {
            "status": anchor_status,
            "artifactId": "final-build:verified-target",
            "designCoverage": {
                "unresolvedCaveats": ["The target boss resource loop remains explicitly caveated."]
            },
        },
        "blueprint": {
            "routeName": "Monk Recovery",
            "stages": [
                {"stageId": "stage:starter-18", "targetLevel": 18},
                {"stageId": "stage:target-85", "targetLevel": 85},
            ],
        },
        "stages": [
            {
                "stageId": "stage:starter-18",
                "status": "failed",
                "artifactId": None,
                "failureCode": "starter_loop_not_viable",
            },
            {
                "stageId": "stage:target-85",
                "status": "pending",
                "artifactId": None,
                "failureCode": None,
            },
        ],
    }
    monkeypatch.setattr(
        progression_delivery.artifacts,
        "read_final_build_artifact_for_export",
        lambda artifact_id: (
            SimpleNamespace(artifact_id=artifact_id),
            "<PathOfBuilding><Build/></PathOfBuilding>",
        ),
    )

    def export_official(*_args, **kwargs):
        destination = kwargs["_destination_path"]
        destination.write_text("{}", encoding="utf-8")
        return {"status": "exported", "outputPath": str(destination), "warnings": []}

    monkeypatch.setattr(
        progression_delivery.build_planner_exporter,
        "export_final_build_artifact",
        export_official,
    )

    result = progression_delivery.export_build_progression_recovery_package(state)

    assert result["status"] == "partial"
    assert result["routeIncomplete"] is True
    assert result["targetArtifactId"] == "final-build:verified-target"
    assert result["failedStageId"] == "stage:starter-18"
    assert result["exportedCount"] == result["expectedCount"] == 4
    assert any(row["artifactType"] == "stage_pob_import_code" for row in result["artifacts"])
    assert any(row["artifactType"] == "target_official_build" for row in result["artifacts"])
    guide = next(
        row for row in result["artifacts"] if row["artifactType"] == "progression_recovery_guide"
    )
    text = Path(guide["outputPath"]).read_text(encoding="utf-8")
    assert "这不是完整成长路线" in text
    assert "starter_loop_not_viable" in text
    assert "target boss resource loop" in text
    assert "PathOfBuilding" not in text


def test_public_export_routes_failed_progression_id_to_recovery(monkeypatch):
    state = {
        "progressionId": "22222222-2222-2222-2222-222222222222",
        "status": "failed",
    }
    monkeypatch.setattr(
        progression_service.progression,
        "read_progression_route",
        lambda _route_id: None,
    )
    monkeypatch.setattr(progression_service, "_read_state", lambda _progression_id: state)
    captured = {}

    def export_recovery(received, **metadata):
        captured["state"] = received
        captured["metadata"] = metadata
        return {"status": "partial", "routeIncomplete": True}

    monkeypatch.setattr(
        progression_service.progression_delivery,
        "export_build_progression_recovery_package",
        export_recovery,
    )

    result = progression_service.export_build_progression_package(
        state["progressionId"],
        name="Recovery",
    )

    assert result == {"status": "partial", "routeIncomplete": True}
    assert captured["state"] is state
    assert captured["metadata"]["name"] == "Recovery"


@pytest.mark.parametrize("progression_status", ["stage_running", "paused"])
def test_running_or_paused_progression_can_export_bound_target_recovery(
    tmp_path,
    monkeypatch,
    progression_status,
):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    state = {
        "progressionId": "33333333-3333-3333-3333-333333333333",
        "status": progression_status,
        "activeStageId": "stage:starter-18",
        "request": {"baseClass": "Monk", "targetLevel": 85},
        "targetAnchor": {
            "status": "anchor_bound",
            "artifactId": "final-build:verified-target",
        },
        "blueprint": {
            "routeName": "Monk Interrupted Recovery",
            "stages": [
                {"stageId": "stage:starter-18", "targetLevel": 18},
                {"stageId": "stage:target-85", "targetLevel": 85},
            ],
        },
        "stages": [
            {
                "stageId": "stage:starter-18",
                "status": "running",
                "artifactId": None,
                "failureCode": None,
            }
        ],
    }
    monkeypatch.setattr(
        progression_delivery.artifacts,
        "read_final_build_artifact_for_export",
        lambda artifact_id: (
            SimpleNamespace(artifact_id=artifact_id),
            "<PathOfBuilding><Build/></PathOfBuilding>",
        ),
    )

    def export_official(*_args, **kwargs):
        destination = kwargs["_destination_path"]
        destination.write_text("{}", encoding="utf-8")
        return {"status": "exported", "outputPath": str(destination), "warnings": []}

    monkeypatch.setattr(
        progression_delivery.build_planner_exporter,
        "export_final_build_artifact",
        export_official,
    )

    result = progression_delivery.export_build_progression_recovery_package(state)

    assert result["status"] == "partial"
    assert result["progressionState"] == progression_status
    assert result["activeStageId"] == "stage:starter-18"
    assert result["recoveryReason"] == "route_incomplete"
    assert result["failedStageId"] is None
    assert result["exportedCount"] == result["expectedCount"] == 4
    guide = next(
        row for row in result["artifacts"] if row["artifactType"] == "progression_recovery_guide"
    )
    text = Path(guide["outputPath"]).read_text(encoding="utf-8")
    assert f"当前流程状态：{progression_status}" in text
    assert "当前活动阶段：stage:starter-18" in text
    assert "失败记录：尚未写入" in text


def test_public_export_uses_completed_progression_route_id(monkeypatch):
    state = {
        "progressionId": "44444444-4444-4444-4444-444444444444",
        "status": "completed",
        "routeId": "route:verified",
    }
    monkeypatch.setattr(
        progression_service.progression,
        "read_progression_route",
        lambda route_id: {"routeId": route_id} if route_id == "route:verified" else None,
    )
    monkeypatch.setattr(progression_service, "_read_state", lambda _progression_id: state)
    captured = {}

    def export_route(route_id, **metadata):
        captured["routeId"] = route_id
        captured["metadata"] = metadata
        return {"status": "exported", "routeId": route_id}

    monkeypatch.setattr(
        progression_service.progression_delivery,
        "export_build_progression_package",
        export_route,
    )

    result = progression_service.export_build_progression_package(
        state["progressionId"],
        name="Complete",
    )

    assert result == {"status": "exported", "routeId": "route:verified"}
    assert captured["routeId"] == "route:verified"
    assert captured["metadata"]["name"] == "Complete"


def test_safe_filename_keeps_long_shared_prefixes_distinct():
    left = progression_delivery._safe_filename("stage-" + ("shared-" * 12) + "left")
    right = progression_delivery._safe_filename("stage-" + ("shared-" * 12) + "right")

    assert len(left) <= 48
    assert len(right) <= 48
    assert left != right
