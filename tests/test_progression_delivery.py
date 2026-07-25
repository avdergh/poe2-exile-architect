from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from server import paths
from server.generation import progression_delivery


def test_progression_delivery_has_fixed_multistage_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    route = {
        "routeId": "11111111-1111-1111-1111-111111111111",
        "routeName": "Monk Progression",
        "classShell": "Monk",
        "targetArtifactId": "final-build:target",
        "routeSummary": "A safe route summary.",
        "qualityStatus": "verified",
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
