from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

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
        "final-build:bridge": (60, "hash-bridge", "Monk", "Invoker", "Tempest Flurry"),
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
                run_id={
                    "final-build:early": "00000000-0000-0000-0000-000000000001",
                    "final-build:bridge": "00000000-0000-0000-0000-000000000002",
                    "final-build:final": "00000000-0000-0000-0000-000000000003",
                }[artifact_id],
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
    assert saved["progressionRoute"]["qualityStatus"] == "limited"
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


def test_progression_route_can_use_a_deterministic_idempotent_id(isolated_progression):
    route_id = str(uuid4())
    first = progression.save_progression_route(_route(), route_id=route_id)
    second = progression.save_progression_route(_route(), route_id=route_id)

    assert first["progressionRoute"]["routeId"] == route_id
    assert second["status"] == "saved"
    assert second["idempotent"] is True
    assert second["progressionRoute"]["routeId"] == route_id


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

    copied_gear = _route()
    copied_gear["stages"][0]["purpose"] = (
        "Helmet: Exact Helm; Gloves: Exact Gloves; Boots: Exact Boots; "
        "Amulet: Exact Amulet; Belt: Exact Belt"
    )
    assert (
        progression.save_progression_route(copied_gear)["errorCode"] == "invalid_progression_route"
    )


def test_route_stage_can_preserve_all_bounded_progression_provenance_refs():
    refs = [
        "starter-research:packet",
        *[f"dq-{index:016x}" for index in range(16)],
        *[f"artifact:evidence-{index}" for index in range(12)],
    ]

    stage = progression.ProgressionStageV2(
        stage_id="stage:provenance-bounds",
        lifecycle_stage="campaign_early",
        route_role="starter_bootstrap",
        target_level=20,
        artifact_id="final-build:early",
        purpose="Preserve the bounded evidence set.",
        play_pattern="Use the verified starter loop.",
        evidence_status="supported",
        source_refs=refs,
        changes_from_previous=[],
        transition_bridge=None,
    )

    assert stage.source_refs == refs
    assert len(stage.source_refs) == 29


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


def test_route_v2_allows_repeated_lifecycle_stages_but_requires_stage_id_selector(
    isolated_progression,
):
    route = _route()
    final_stage = route["stages"][1]  # type: ignore[index]
    bridge_stage = {
        **final_stage,
        "stageId": "stage:bridge-60",
        "lifecycleStage": "maps_entry",
        "routeRole": "transition",
        "targetLevel": 60,
        "artifactId": "final-build:bridge",
        "changesFromPrevious": final_stage["changesFromPrevious"],
        "transitionBridge": {
            "bridgeId": "bridge:starter-to-bridge",
            "summary": "Open the target resource loop before changing the final package.",
            "requirements": [
                {
                    "requirementId": "gate:resource-loop",
                    "kind": "resource_loop",
                    "description": "The target resource loop is stable.",
                    "status": "satisfied",
                    "blocking": True,
                    "evidenceRefs": ["artifact:final-build-bridge"],
                }
            ],
            "fallbackPlan": "Remain on the starter package.",
        },
        "evidenceStatus": "supported",
        "sourceRefs": ["starter-research:packet"],
    }
    bridge_stage.pop("transitionRequirements", None)
    target_stage = {
        **final_stage,
        "stageId": "stage:target-80",
        "lifecycleStage": "maps_entry",
        "routeRole": "target",
        "transitionBridge": {
            "bridgeId": "bridge:bridge-to-target",
            "summary": "Complete the target mechanic after the bridge is proven.",
            "requirements": [
                {
                    "requirementId": "gate:judge-target",
                    "kind": "judge_gate",
                    "description": "The target snapshot passes its gate.",
                    "status": "satisfied",
                    "blocking": True,
                    "evidenceRefs": ["artifact:final-build-final"],
                }
            ],
            "fallbackPlan": "Keep playing the verified bridge form.",
        },
        "evidenceStatus": "supported",
        "sourceRefs": ["starter-research:packet"],
    }
    target_stage.pop("transitionRequirements", None)
    first_stage = {
        **route["stages"][0],  # type: ignore[index]
        "stageId": "stage:starter-20",
        "routeRole": "starter_bootstrap",
        "evidenceStatus": "supported",
        "sourceRefs": ["starter-research:packet"],
        "playerGuide": {
            "mechanicExplanation": "Use a simple setup-and-payoff loop while gear is scarce.",
            "levelingSteps": ["Upgrade the weapon first.", "Add the boss skill when available."],
            "commonProblems": [
                {
                    "symptom": "Boss damage slows down.",
                    "solution": "Use the setup skill before spending the payoff.",
                }
            ],
        },
    }
    first_stage.pop("transitionRequirements", None)
    route.pop("targetFinalArtifactId")
    route["targetArtifactId"] = "final-build:final"
    route["stages"] = [first_stage, bridge_stage, target_stage]

    saved = progression.save_progression_route(route)
    assert saved["status"] == "saved"
    assert saved["progressionRoute"]["stages"][0]["playerGuide"]["levelingSteps"] == [
        "Upgrade the weapon first.",
        "Add the boss skill when available.",
    ]
    route_id = saved["progressionRoute"]["routeId"]
    assert (
        progression.load_progression_stage(
            object(), route_id=route_id, lifecycle_stage="maps_entry"
        )["errorCode"]
        == "progression_stage_ambiguous"
    )
    loaded = progression.load_progression_stage(
        object(), route_id=route_id, stage_id="stage:bridge-60"
    )
    assert loaded["status"] == "loaded"
    assert loaded["stage"]["artifactId"] == "final-build:bridge"


def test_compatibility_route_writer_cannot_bypass_the_anchor_state_service(
    isolated_progression,
):
    route = _route()
    final_stage = route["stages"][1]  # type: ignore[index]
    first_stage = {
        **route["stages"][0],  # type: ignore[index]
        "stageId": "stage:starter-20",
        "routeRole": "starter_bootstrap",
        "evidenceStatus": "supported",
        "sourceRefs": ["starter-research:packet"],
    }
    first_stage.pop("transitionRequirements", None)
    target_stage = {
        **final_stage,
        "stageId": "stage:target-80",
        "routeRole": "target",
        "evidenceStatus": "supported",
        "sourceRefs": ["starter-research:packet"],
        "transitionBridge": {
            "bridgeId": "bridge:target-anchor",
            "summary": "Close the target only after the verified mechanism gate.",
            "requirements": [
                {
                    "requirementId": "gate:target-anchor",
                    "kind": "judge_gate",
                    "description": "The immutable target artifact is verified.",
                    "status": "satisfied",
                    "blocking": True,
                    "evidenceRefs": ["artifact:final-build-final"],
                }
            ],
            "fallbackPlan": "Keep the previous verified milestone.",
        },
    }
    target_stage.pop("transitionRequirements", None)
    route.pop("targetFinalArtifactId")
    route["targetArtifactId"] = "final-build:final"
    route["targetAnchorArtifactId"] = "final-build:final"
    route["targetDesignCoverage"] = {
        "coverageId": "target-coverage:compatibility-bypass",
        "dimensions": [
            {
                "dimension": dimension,
                "status": "independently_verified",
                "summary": f"Verified {dimension}.",
                "evidenceRefs": [f"artifact:{dimension}"],
            }
            for dimension in (
                "skill_package",
                "clear_duty",
                "boss_duty",
                "damage_delivery",
                "ascendancy_and_passives",
                "gear_synergy",
                "defense_and_recovery",
                "resource_and_spirit",
                "combat_configuration",
                "modelability",
            )
        ],
        "acceptanceSummary": "Attempt to bypass the anchor state service.",
        "unresolvedCaveats": [],
        "agentAcceptance": "accepted",
    }
    route["stages"] = [first_stage, target_stage]

    result = progression.save_progression_route(route)

    assert result["errorCode"] == "progression_anchor_route_requires_service"


def test_legacy_route_is_read_without_rewriting(isolated_progression):
    route_id = str(uuid4())
    legacy_proposal = _route()
    facts = [
        progression._legacy_artifact_fact("final-build:early"),
        progression._legacy_artifact_fact("final-build:final"),
    ]
    manifest = {
        "schemaVersion": 1,
        "routeId": route_id,
        "proposal": legacy_proposal,
        "artifactFacts": facts,
        "createdAt": "2026-01-01T00:00:00+00:00",
        "localOnly": True,
        "containsRawPob": False,
    }
    route_dir = progression.progression_routes_dir() / route_id
    route_dir.mkdir(parents=True)
    path = route_dir / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    listed = progression.list_progression_routes()
    assert listed["progressionRoutes"][0]["schemaVersion"] == 1
    assert listed["progressionRoutes"][0]["targetArtifactId"] == "final-build:final"
    assert listed["progressionRoutes"][0]["stages"][0]["stageId"].startswith("stage:legacy-")
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 1
