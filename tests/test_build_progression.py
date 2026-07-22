from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from server import paths
from server.generation import models, progression


VERSION = models.VersionContext(
    league="Standard",
    ruleset="softcore_trade",
    game_patch="0.5.0",
    passive_tree_version="0_5",
    pob_version_or_commit="0.22.0",
    graph_snapshot_id="graph:test",
    research_memory_ref="dq-0123456789abcdef",
)


@pytest.fixture()
def isolated_progression(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    facts = {
        "final-build:early": (20, "hash-early", "Monk", "", "Falling Thunder"),
        "final-build:final": (80, "hash-final", "Monk", "Invoker", "Tempest Flurry"),
    }

    def read_artifact(artifact_id: str):
        value = facts.get(artifact_id)
        if value is None:
            return None
        level, source_hash, class_shell, ascendancy, main_skill = value
        return (
            SimpleNamespace(
                artifact_id=artifact_id,
                source_hash=source_hash,
                safe_summary={
                    "level": str(level),
                    "class": class_shell,
                    "ascendancy": ascendancy,
                    "mainSkill": main_skill,
                },
                version_context=VERSION,
            ),
            "<PathOfBuilding/>",
        )

    monkeypatch.setattr(
        progression.artifacts, "read_final_build_artifact_for_export", read_artifact
    )
    monkeypatch.setattr(
        progression.artifacts,
        "load_final_build_artifact",
        lambda _engine, *, artifact_id: {
            "status": "loaded",
            "activeBuild": {"mainSkill": facts[artifact_id][4]},
        },
    )
    return facts


def _route() -> dict[str, object]:
    return {
        "routeName": "Monk verified progression",
        "classShell": "Monk",
        "targetFinalArtifactId": "final-build:final",
        "stages": [
            {
                "lifecycleStage": "campaign_early",
                "targetLevel": 20,
                "artifactId": "final-build:early",
                "purpose": "Establish a low-requirement campaign shell.",
                "playPattern": "Build combo, spend with the main attack, and keep moving.",
                "changesFromPrevious": [],
                "transitionRequirements": [],
                "acquisitionPriorities": ["weapon damage", "elemental resistance"],
                "caveats": [],
            },
            {
                "lifecycleStage": "endgame_budget",
                "targetLevel": 80,
                "artifactId": "final-build:final",
                "purpose": "Reach the requested verified target build.",
                "playPattern": "Maintain the staff buff and use the main attack for delivery.",
                "changesFromPrevious": [
                    {
                        "category": "skill",
                        "action": "replace",
                        "subject": "Tempest Flurry",
                        "replaces": "Falling Thunder",
                        "reason": "The target loop is now supported by the later passive shell.",
                        "evidenceRefs": ["artifact:final-build-final"],
                    }
                ],
                "transitionRequirements": [
                    {
                        "kind": "judge_gate",
                        "description": "The target snapshot passes the stage Judge gate.",
                        "status": "satisfied",
                        "evidenceRefs": ["artifact:final-build-final"],
                    }
                ],
                "acquisitionPriorities": ["cap resistances", "secure sustain"],
                "caveats": [],
            },
        ],
        "routeSummary": "Two real PoB snapshots anchor the campaign-to-target transition.",
        "versionContext": VERSION.model_dump(mode="json", by_alias=True),
        "noRawMaterial": True,
    }


def test_progression_route_requires_trusted_monotonic_artifacts(isolated_progression):
    saved = progression.save_progression_route(_route())

    assert saved["status"] == "saved"
    assert saved["containsRawPob"] is False
    assert [stage["targetLevel"] for stage in saved["progressionRoute"]["stages"]] == [20, 80]
    listed = progression.list_progression_routes()
    assert listed["progressionRoutes"][0]["routeId"] == saved["progressionRoute"]["routeId"]

    loaded = progression.load_progression_stage(
        object(),
        route_id=saved["progressionRoute"]["routeId"],
        lifecycle_stage="budget_endgame",
    )
    assert loaded["status"] == "loaded"
    assert loaded["activeBuild"]["mainSkill"] == "Tempest Flurry"


def test_progression_route_rejects_prose_only_or_mismatched_stages(isolated_progression):
    route = _route()
    route["stages"][1]["artifactId"] = "final-build:missing"  # type: ignore[index]
    route["targetFinalArtifactId"] = "final-build:missing"
    assert progression.save_progression_route(route)["errorCode"] == (
        "progression_stage_artifact_not_trusted"
    )

    route = _route()
    route["stages"][1]["targetLevel"] = 79  # type: ignore[index]
    assert progression.save_progression_route(route)["errorCode"] == (
        "progression_stage_level_mismatch"
    )


def test_progression_route_rejects_unordered_levels_and_missing_transition_details():
    route = _route()
    route["stages"][1]["targetLevel"] = 10  # type: ignore[index]
    result = progression.save_progression_route(route)
    assert result["errorCode"] == "invalid_progression_route"


def test_progression_route_revalidates_artifact_facts_on_read(isolated_progression):
    saved = progression.save_progression_route(_route())
    route_id = saved["progressionRoute"]["routeId"]
    path = progression.progression_routes_dir() / route_id / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["artifactFacts"][0]["level"] = 99
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert progression.list_progression_routes()["progressionRoutes"] == []
    assert (
        progression.load_progression_stage(
            object(), route_id=route_id, lifecycle_stage="campaign_early"
        )["errorCode"]
        == "progression_route_not_found"
    )

    route = _route()
    route["stages"][1]["changesFromPrevious"] = []  # type: ignore[index]
    result = progression.save_progression_route(route)
    assert result["errorCode"] == "invalid_progression_route"
