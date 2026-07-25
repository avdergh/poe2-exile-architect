from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from server import paths
from server.generation import models, progression_models, progression_service


VERSION = models.VersionContext(
    league="Test League",
    ruleset="softcore_trade",
    game_patch="0.5.4",
    passive_tree_version="0_5",
    pob_version_or_commit="pob:test",
    graph_snapshot_id="graph:test",
    research_memory_ref="dq-0123456789abcdef",
)


@pytest.fixture()
def isolated_service(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        progression_service,
        "_valid_phase5_run",
        lambda _run_id, *, not_before: bool(not_before),
    )
    monkeypatch.setattr(
        progression_service.progression_costs,
        "read_trusted_cost_profile",
        lambda cost_profile_ref, *, stage_id, allow_expired=False: (
            _cost(stage_id) if cost_profile_ref == _cost(stage_id)["costProfileRef"] else None
        ),
    )
    manifests: dict[str, SimpleNamespace] = {}

    def read_artifact(artifact_id: str):
        manifest = manifests.get(artifact_id)
        return (manifest, "<PathOfBuilding/>") if manifest else None

    monkeypatch.setattr(
        progression_service.artifacts,
        "read_final_build_artifact_for_export",
        read_artifact,
    )
    monkeypatch.setattr(
        progression_service.progression.artifacts,
        "read_final_build_artifact_for_export",
        read_artifact,
    )
    return manifests


def _research() -> dict[str, object]:
    return {
        "baseClass": "Monk",
        "gamePatch": "0.5.4",
        "passiveTreeVersion": "0_5",
        "levelMin": 1,
        "levelMax": 65,
        "networkStatus": "available",
        "sources": [
            {
                "sourceId": "source:guide-current",
                "sourceUrl": "https://starter.example/monk",
                "sourceKind": "structured_guide",
                "title": "Current Monk starter",
                "claimedPatch": "0.5.4",
                "explicitLevelBands": True,
                "summary": "A short level-banded starter summary.",
            }
        ],
        "claims": [
            {
                "claimId": "starter-claim:starter-family",
                "claimKind": "ascendancy_choice",
                "levelMin": 1,
                "levelMax": 65,
                "summary": "Use the fast-forming campaign ascendancy.",
                "componentKeys": ["ascendancy:starter-monk"],
                "sourceRefs": ["source:guide-current"],
                "verificationTasks": ["Resolve the ascendancy and verify each stage."],
            }
        ],
        "contradictions": [],
        "unresolvedChecks": [],
    }


def _bridge(index: int) -> dict[str, object]:
    return {
        "bridgeId": f"bridge:stage-{index}",
        "summary": "Advance only after the next mechanic is functional.",
        "requirements": [
            {
                "requirementId": f"gate:resource-{index}",
                "kind": "resource_loop",
                "description": "The resource loop is stable in the verified snapshot.",
                "status": "required",
                "blocking": True,
                "evidenceRefs": [],
            },
            {
                "requirementId": f"gate:price-{index}",
                "kind": "price",
                "description": "The cost band is disclosed.",
                "status": "unverified",
                "blocking": False,
                "evidenceRefs": [],
            },
        ],
        "fallbackPlan": "Keep the previous verified stage.",
    }


def _blueprint(packet_id: str) -> dict[str, object]:
    stages = []
    stage_specs = [
        ("starter-10", "campaign_early", "starter_bootstrap", 10, "starter"),
        ("starter-30", "campaign_mid", "starter_established", 30, "starter"),
        ("bridge-60", "campaign_late", "transition", 60, "target"),
        ("target-80", "maps_entry", "target", 80, "target"),
    ]
    for index, (suffix, lifecycle, role, level, family) in enumerate(stage_specs):
        stages.append(
            {
                "stageId": f"stage:{suffix}",
                "lifecycleStage": lifecycle,
                "routeRole": role,
                "targetLevel": level,
                "familyIdentity": {
                    "ascendancyKey": f"ascendancy:{family}-monk",
                    "primarySkillKey": f"skill:{family}-attack",
                    "secondarySkillKeys": [],
                },
                "ascendancyIntent": (
                    "Fast Campaign Ascendancy" if family == "starter" else "High Ceiling Ascendancy"
                ),
                "primarySkillIntent": ("Early Attack" if family == "starter" else "Target Attack"),
                "skillPackageIntents": ["main damage", "movement"],
                "passiveAnchorIntents": ["nearby efficient cluster"],
                "gearRoleIntents": ["legal weapon", "resistance coverage"],
                "responsibilityCoverage": [
                    "clear",
                    "boss",
                    "defense",
                    "resource",
                    "mobility",
                ],
                "evidenceStatus": "supported",
                "entryBridge": None if index == 0 else _bridge(index),
                "expectedCostBand": "unknown",
                "researchQueryRefs": [f"dq-{index + 1:016x}"],
                "rebuildFromScratch": index == 2,
            }
        )
    return {
        "blueprintId": "progression-blueprint:monk-80",
        "routeName": "Monk starter into target",
        "baseClass": "Monk",
        "targetLevel": 80,
        "starterResearchPacketId": packet_id,
        "starterEvidenceUse": {
            "packetId": packet_id,
            "decisions": [
                {
                    "claimId": "starter-claim:starter-family",
                    "decision": "adopted",
                    "application": "Use the campaign Family for the first two stages.",
                    "verificationRefs": ["graph:ascendancy-starter"],
                }
            ],
        },
        "starterChoiceSummary": "Choose early formation speed over target similarity.",
        "targetIntent": {
            "ascendancyIntent": "High Ceiling Ascendancy",
            "primarySkillIntent": "Target Attack",
            "mechanicIntents": ["late resource loop"],
            "ceilingGoals": ["high boss ceiling"],
            "knownEarlyFailures": ["resource loop is unavailable early"],
        },
        "stages": stages,
        "mergeRationale": [],
        "versionContext": VERSION.model_dump(mode="json", by_alias=True),
        "noRawMaterial": True,
    }


def _start_and_blueprint() -> tuple[str, int, dict[str, object]]:
    started = progression_service.start_build_progression(
        operation_id="op:start",
        base_class="Monk",
        target_level=80,
        goal="Create a fast starter that transitions into a high-ceiling target.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    progression_id = started["progressionId"]
    research = progression_service.intake_starter_research_packet(
        progression_id=progression_id,
        expected_revision=0,
        operation_id="op:research",
        packet=_research(),
    )
    packet_id = research["packetId"]
    accepted = progression_service.submit_build_progression_blueprint(
        progression_id=progression_id,
        expected_revision=1,
        operation_id="op:blueprint",
        blueprint=_blueprint(packet_id),
    )
    return progression_id, accepted["revision"], _blueprint(packet_id)


def test_progression_blueprint_rejects_endgame_stage_below_verification_level():
    blueprint = _blueprint("starter-research:packet-123")
    blueprint["stages"][-1]["lifecycleStage"] = "endgame_budget"

    # Persisted pre-v2.1 stage packets stay loadable so an in-flight route can be failed/retried
    # after an upgrade. Only accepting or revising a complete blueprint enforces the new floor.
    legacy_stage = progression_models.StageBlueprint.model_validate(blueprint["stages"][-1])
    assert legacy_stage.target_level == 80
    legacy_packet = progression_models.StageCreatePacket(
        progression_id="00000000-0000-0000-0000-000000000001",
        blueprint_id=blueprint["blueprintId"],
        base_class=blueprint["baseClass"],
        target_level=80,
        route_target_level=80,
        target_intent=blueprint["targetIntent"],
        stage=legacy_stage,
        previous_artifact_id=None,
        starter_research_packet_id=blueprint["starterResearchPacketId"],
        starter_evidence_use=blueprint["starterEvidenceUse"],
        version_context=VERSION,
        no_raw_material=True,
        progression_bound=True,
    )
    assert legacy_packet.stage.lifecycle_stage == "endgame_budget"
    with pytest.raises(ValueError, match="target level 82 or higher"):
        progression_models.ProgressionBlueprint.model_validate(blueprint)

    blueprint["targetLevel"] = 82
    blueprint["stages"][-1]["targetLevel"] = 82
    accepted = progression_models.ProgressionBlueprint.model_validate(blueprint)
    assert accepted.stages[-1].lifecycle_stage == "endgame_budget"


def test_progression_blueprint_requires_resolved_typed_family_keys():
    blueprint = _blueprint("starter-research:packet-123")
    blueprint["stages"][0]["familyIdentity"]["ascendancyKey"] = "skill:not-an-ascendancy"

    with pytest.raises(ValueError, match="resolved ascendancy key"):
        progression_models.ProgressionBlueprint.model_validate(blueprint)

    blueprint = _blueprint("starter-research:packet-123")
    blueprint["stages"][0]["familyIdentity"]["primarySkillKey"] = "unique:not-a-skill"
    with pytest.raises(ValueError, match="resolved skill keys"):
        progression_models.ProgressionBlueprint.model_validate(blueprint)


def test_progression_blueprint_rejects_when_all_starter_claims_are_rejected(
    isolated_service,
):
    started = progression_service.start_build_progression(
        operation_id="op:start:all-rejected",
        base_class="Monk",
        target_level=80,
        goal="Create a complete progression with bounded starter evidence.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=0,
        operation_id="op:research:all-rejected",
        packet=_research(),
    )
    blueprint = _blueprint(research["packetId"])
    blueprint["starterEvidenceUse"]["decisions"][0]["decision"] = "rejected"
    blueprint["starterEvidenceUse"]["decisions"][0]["verificationRefs"] = []

    result = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:all-rejected",
        blueprint=blueprint,
    )

    assert result["errorCode"] == "starter_evidence_use_has_no_selected_claim"


def _manifest(
    artifact_id: str,
    run_id: str,
    level: int,
    source_hash: str,
    *,
    class_shell: str = "Monk",
    research_ref: str = "dq-0123456789abcdef",
) -> SimpleNamespace:
    return SimpleNamespace(
        artifact_id=artifact_id,
        run_id=run_id,
        source_hash=source_hash,
        safe_summary={
            "level": str(level),
            "class": class_shell,
            "ascendancy": "Varies By Stage",
            "mainSkill": "Stage Skill",
        },
        version_context=VERSION.model_copy(update={"research_memory_ref": research_ref}),
        judge_report=SimpleNamespace(
            playability_failures=[],
            quality_warnings=[],
            caveats=[],
            score_applicability="applicable",
            modelability_status="full",
        ),
    )


def _cost(stage_id: str) -> dict[str, object]:
    return {
        "status": "classified",
        "stageId": stage_id,
        "costProfileRef": f"progression-cost:{stage_id.removeprefix('stage:')}",
        "league": "Test League",
        "baseCurrency": "Exalted Orb",
        "dependencies": [],
        "highestRequiredBand": "unknown",
        "paidDependencyCount": 0,
        "requiredDependencyCount": 0,
        "unknownRequiredDependencyCount": 0,
        "fallbackCoverage": 1.0,
        "livePriceCoverage": 1.0,
        "costEvidenceStatus": "supported",
        "capturedAt": "2026-01-01T00:00:00+00:00",
        "expiresAt": "2026-01-01T06:00:00+00:00",
        "containsTotalPrice": False,
    }


def test_fresh_starter_cache_returns_the_safe_packet_for_blueprint_recovery(isolated_service):
    seeded = progression_service.start_build_progression(
        operation_id="op:start:cache-seed",
        base_class="Monk",
        target_level=80,
        goal="Seed one safe starter packet.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    accepted = progression_service.intake_starter_research_packet(
        progression_id=seeded["progressionId"],
        expected_revision=0,
        operation_id="op:research:cache-seed",
        packet=_research(),
    )
    assert accepted["starterResearchPacket"]["claims"][0]["claimId"] == (
        "starter-claim:starter-family"
    )

    reused = progression_service.start_build_progression(
        operation_id="op:start:cache-consumer",
        base_class="Monk",
        target_level=80,
        goal="Reuse the exact-patch starter packet.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    assert reused["currentState"] == "blueprint_pending"
    assert reused["starterResearchPacket"]["packetId"] == accepted["packetId"]
    assert "https://" not in str(reused["starterResearchPacket"])
    status = progression_service.get_build_progression_status(reused["progressionId"])
    assert status["buildProgression"]["starterResearchPacket"]["claims"][0]["claimId"] == (
        "starter-claim:starter-family"
    )

    cache_path = next(paths.starter_research_cache_dir().glob("*.json"))
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    cached["createdAt"] = "2025-01-01T00:00:00+00:00"
    cached["expiresAt"] = "2025-01-08T00:00:00+00:00"
    cache_path.write_text(json.dumps(cached), encoding="utf-8")
    stale = progression_service.start_build_progression(
        operation_id="op:start:stale-candidate",
        base_class="Monk",
        target_level=80,
        goal="Revalidate a stale safe candidate.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    assert stale["currentState"] == "research_pending"
    assert stale["starterResearchPacket"] is None
    assert stale["starterResearchCandidate"]["packetId"] == accepted["packetId"]
    stale_status = progression_service.get_build_progression_status(stale["progressionId"])
    assert (
        stale_status["buildProgression"]["starterResearchCandidate"]["packetId"]
        == (accepted["packetId"])
    )


def test_starter_stage_evidence_cannot_overstate_a_limited_web_packet(isolated_service):
    started = progression_service.start_build_progression(
        operation_id="op:start:limited-evidence",
        base_class="Monk",
        target_level=80,
        goal="Keep starter and target evidence separate.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    research_packet = _research()
    research_packet["sources"][0]["sourceKind"] = "aggregator"
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=0,
        operation_id="op:research:limited-evidence",
        packet=research_packet,
    )
    assert research["evidenceStatus"] == "limited"

    overstated = _blueprint(research["packetId"])
    rejected = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:overstated-evidence",
        blueprint=overstated,
    )
    assert rejected["errorCode"] == "starter_stage_evidence_status_mismatch"

    corrected = _blueprint(research["packetId"])
    for stage in corrected["stages"][:2]:
        stage["evidenceStatus"] = "limited"
    accepted = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:bounded-evidence",
        blueprint=corrected,
    )
    assert accepted["status"] == "blueprint_accepted"


def test_progression_is_serial_cas_bound_and_finalizes_route_v2(isolated_service):
    manifests = isolated_service
    progression_id, revision, blueprint = _start_and_blueprint()
    # Starter and target Families/ascendancies are intentionally different.
    assert (
        blueprint["stages"][0]["familyIdentity"]  # type: ignore[index]
        != blueprint["stages"][-1]["familyIdentity"]  # type: ignore[index]
    )

    for index, stage_blueprint in enumerate(blueprint["stages"]):  # type: ignore[index]
        claimed = progression_service.claim_build_progression_stage(
            progression_id=progression_id,
            expected_revision=revision,
            operation_id=f"op:claim:{index}",
        )
        revision = claimed["revision"]
        assert claimed["stageId"] == stage_blueprint["stageId"]
        assert (
            claimed["stageCreatePacket"]["versionContext"]["researchMemoryRef"]
            == stage_blueprint["researchQueryRefs"][-1]
        )
        if stage_blueprint["rebuildFromScratch"]:
            assert claimed["stageCreatePacket"]["previousArtifactId"] is None
        duplicate = progression_service.claim_build_progression_stage(
            progression_id=progression_id,
            expected_revision=revision,
            operation_id=f"op:other-claim:{index}",
        )
        assert duplicate["errorCode"] == "progression_stage_not_claimable"

        run_id = f"00000000-0000-0000-0000-{index + 1:012d}"
        bound = progression_service.bind_build_progression_stage_run(
            progression_id=progression_id,
            stage_id=claimed["stageId"],
            claim_id=claimed["claimId"],
            run_id=run_id,
            expected_revision=revision,
            operation_id=f"op:bind:{index}",
        )
        revision = bound["revision"]
        artifact_id = f"final-build:artifact-{index}"
        source_hash = f"source-hash-{index}"
        manifests[artifact_id] = _manifest(
            artifact_id,
            run_id,
            stage_blueprint["targetLevel"],
            source_hash,
            research_ref=stage_blueprint["researchQueryRefs"][0],
        )
        changes = (
            []
            if index == 0
            else [
                {
                    "category": "skill",
                    "action": "replace",
                    "subject": f"Stage Skill {index}",
                    "replaces": f"Stage Skill {index - 1}",
                    "reason": "Advance to the next verified stage package.",
                    "evidenceRefs": [f"artifact:{artifact_id}"],
                }
            ]
        )
        completed = progression_service.complete_build_progression_stage(
            progression_id=progression_id,
            stage_id=claimed["stageId"],
            claim_id=claimed["claimId"],
            artifact_id=artifact_id,
            lifecycle_verification={
                "stage": stage_blueprint["lifecycleStage"],
                "status": "passed",
                "pass": True,
                "failedChecks": [],
                "unknownChecks": [],
                "caveats": [],
                "evidenceTags": ["engine-computed", "stage-verification"],
                "evaluatedSourceHash": source_hash,
            },
            cost_profile=_cost(claimed["stageId"]),
            completion_report={
                "purpose": f"Verify milestone {index + 1}.",
                "playPattern": "Use the stage-specific main loop and keep moving.",
                "changesFromPrevious": changes,
                "acquisitionPriorities": ["resistance coverage"],
                "caveats": [],
                "sourceRefs": ["starter-research:packet-safe"],
            },
            expected_revision=revision,
            operation_id=f"op:complete:{index}",
        )
        revision = completed["revision"]

    finalized = progression_service.finalize_build_progression(
        progression_id=progression_id,
        expected_revision=revision,
        operation_id="op:finalize",
        route_summary="Four independently verified milestones connect the starter and target.",
    )
    assert finalized["status"] == "completed"
    assert finalized["qualityStatus"] == "verified"
    status = progression_service.get_build_progression_status(progression_id)
    assert status["buildProgression"]["currentState"] == "completed"
    assert len(status["buildProgression"]["stages"]) == 4


def test_progression_rejects_hash_mismatch_and_allows_only_one_external_retry(
    isolated_service,
):
    manifests = isolated_service
    progression_id, revision, blueprint = _start_and_blueprint()
    claimed = progression_service.claim_build_progression_stage(
        progression_id=progression_id,
        expected_revision=revision,
        operation_id="op:claim:first",
    )
    revision = claimed["revision"]
    running_status = progression_service.get_build_progression_status(progression_id)
    assert running_status["buildProgression"]["activeStage"]["claimId"] == claimed["claimId"]
    assert (
        running_status["buildProgression"]["activeStage"]["stageCreatePacket"]
        == claimed["stageCreatePacket"]
    )
    run_id = "10000000-0000-0000-0000-000000000001"
    bound = progression_service.bind_build_progression_stage_run(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        run_id=run_id,
        expected_revision=revision,
        operation_id="op:bind:first",
    )
    revision = bound["revision"]
    artifact_id = "final-build:first"
    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        10,
        "real-hash",
        research_ref=blueprint["stages"][0]["researchQueryRefs"][0],  # type: ignore[index]
    )
    rejected = progression_service.complete_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification={
            "stage": blueprint["stages"][0]["lifecycleStage"],  # type: ignore[index]
            "status": "passed",
            "pass": True,
            "evaluatedSourceHash": "wrong-hash",
        },
        cost_profile=_cost(claimed["stageId"]),
        completion_report={
            "purpose": "Verify the first milestone.",
            "playPattern": "Use the stage loop.",
            "changesFromPrevious": [],
            "sourceRefs": [],
        },
        expected_revision=revision,
        operation_id="op:complete:bad-hash",
    )
    assert rejected["errorCode"] == "progression_lifecycle_source_hash_mismatch"

    failed = progression_service.fail_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        failure_code="stage_verification_failed",
        expected_revision=revision,
        operation_id="op:fail:first",
    )
    retried = progression_service.retry_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        expected_revision=failed["revision"],
        operation_id="op:retry:first",
    )
    assert retried["retryCount"] == 1

    mutated_retry = deepcopy(blueprint)
    mutated_retry["blueprintId"] = "progression-blueprint:retry-bypass"
    mutated_retry["stages"][0]["primarySkillIntent"] = "Bypass the failed stage"
    rejected_revision = progression_service.revise_future_build_progression_stages(
        progression_id=progression_id,
        expected_revision=retried["revision"],
        operation_id="op:revise:retry-bypass",
        blueprint=mutated_retry,
    )
    assert rejected_revision["errorCode"] == "started_progression_stage_immutable"

    claimed_again = progression_service.claim_build_progression_stage(
        progression_id=progression_id,
        expected_revision=retried["revision"],
        operation_id="op:claim:again",
    )
    failed_again = progression_service.fail_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed_again["stageId"],
        claim_id=claimed_again["claimId"],
        failure_code="stage_verification_failed",
        expected_revision=claimed_again["revision"],
        operation_id="op:fail:again",
    )
    exhausted = progression_service.retry_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed_again["stageId"],
        expected_revision=failed_again["revision"],
        operation_id="op:retry:again",
    )
    assert exhausted["errorCode"] == "progression_stage_retry_limit_reached"


def test_progression_rejects_unbound_and_mismatched_stage_artifacts(isolated_service, monkeypatch):
    manifests = isolated_service
    progression_id, revision, blueprint = _start_and_blueprint()
    first_blueprint = blueprint["stages"][0]
    claimed = progression_service.claim_build_progression_stage(
        progression_id=progression_id,
        expected_revision=revision,
        operation_id="op:claim:binding-contract",
    )
    artifact_id = "final-build:binding-contract"
    run_id = "30000000-0000-0000-0000-000000000001"
    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        first_blueprint["targetLevel"],
        "binding-contract-hash",
        research_ref=first_blueprint["researchQueryRefs"][0],
    )
    completion = {
        "purpose": "Verify the binding contract.",
        "playPattern": "Use the stage loop.",
        "changesFromPrevious": [],
        "sourceRefs": [],
    }
    lifecycle = {
        "stage": first_blueprint["lifecycleStage"],
        "status": "passed",
        "pass": True,
        "evaluatedSourceHash": "binding-contract-hash",
    }
    unbound = progression_service.complete_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification=lifecycle,
        cost_profile=_cost(claimed["stageId"]),
        completion_report=completion,
        expected_revision=claimed["revision"],
        operation_id="op:complete:unbound",
    )
    assert unbound["errorCode"] == "progression_stage_run_not_bound"

    monkeypatch.setattr(
        progression_service,
        "_valid_phase5_run",
        lambda _run_id, *, not_before: False,
    )
    missing_run = progression_service.bind_build_progression_stage_run(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        run_id=run_id,
        expected_revision=claimed["revision"],
        operation_id="op:bind:missing-run",
    )
    assert missing_run["errorCode"] == "progression_phase5_run_not_found"
    monkeypatch.setattr(
        progression_service,
        "_valid_phase5_run",
        lambda _run_id, *, not_before: bool(not_before),
    )
    bound = progression_service.bind_build_progression_stage_run(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        run_id=run_id,
        expected_revision=claimed["revision"],
        operation_id="op:bind:binding-contract",
    )

    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        first_blueprint["targetLevel"] + 1,
        "binding-contract-hash",
        research_ref=first_blueprint["researchQueryRefs"][0],
    )
    wrong_level = progression_service.complete_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification=lifecycle,
        cost_profile=_cost(claimed["stageId"]),
        completion_report=completion,
        expected_revision=bound["revision"],
        operation_id="op:complete:wrong-level",
    )
    assert wrong_level["errorCode"] == "progression_stage_level_mismatch"

    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        first_blueprint["targetLevel"],
        "binding-contract-hash",
        class_shell="Witch",
        research_ref=first_blueprint["researchQueryRefs"][0],
    )
    wrong_class = progression_service.complete_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification=lifecycle,
        cost_profile=_cost(claimed["stageId"]),
        completion_report=completion,
        expected_revision=bound["revision"],
        operation_id="op:complete:wrong-class",
    )
    assert wrong_class["errorCode"] == "progression_base_class_mismatch"

    wrong_version_manifest = _manifest(
        artifact_id,
        run_id,
        first_blueprint["targetLevel"],
        "binding-contract-hash",
        research_ref=first_blueprint["researchQueryRefs"][0],
    )
    wrong_version_manifest.version_context = wrong_version_manifest.version_context.model_copy(
        update={"game_patch": "0.6.0"}
    )
    manifests[artifact_id] = wrong_version_manifest
    wrong_version = progression_service.complete_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification=lifecycle,
        cost_profile=_cost(claimed["stageId"]),
        completion_report=completion,
        expected_revision=bound["revision"],
        operation_id="op:complete:wrong-version",
    )
    assert wrong_version["errorCode"] == "progression_version_context_mismatch"

    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        first_blueprint["targetLevel"],
        "binding-contract-hash",
        research_ref=first_blueprint["researchQueryRefs"][0],
    )
    monkeypatch.setattr(
        progression_service.progression_costs,
        "read_trusted_cost_profile",
        lambda cost_profile_ref, *, stage_id, allow_expired=False: {
            **_cost(stage_id),
            "league": "Wrong League",
        },
    )
    wrong_cost_league = progression_service.complete_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification=lifecycle,
        cost_profile=_cost(claimed["stageId"]),
        completion_report=completion,
        expected_revision=bound["revision"],
        operation_id="op:complete:wrong-cost-league",
    )
    assert wrong_cost_league["errorCode"] == "progression_cost_profile_league_mismatch"
    monkeypatch.setattr(
        progression_service.progression_costs,
        "read_trusted_cost_profile",
        lambda cost_profile_ref, *, stage_id, allow_expired=False: (
            _cost(stage_id) if cost_profile_ref == _cost(stage_id)["costProfileRef"] else None
        ),
    )
    completed = progression_service.complete_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification=lifecycle,
        cost_profile=_cost(claimed["stageId"]),
        completion_report=completion,
        expected_revision=bound["revision"],
        operation_id="op:complete:binding-contract",
    )
    second_blueprint = blueprint["stages"][1]
    claimed_second = progression_service.claim_build_progression_stage(
        progression_id=progression_id,
        expected_revision=completed["revision"],
        operation_id="op:claim:duplicate-snapshot",
    )
    second_run = "30000000-0000-0000-0000-000000000002"
    bound_second = progression_service.bind_build_progression_stage_run(
        progression_id=progression_id,
        stage_id=claimed_second["stageId"],
        claim_id=claimed_second["claimId"],
        run_id=second_run,
        expected_revision=claimed_second["revision"],
        operation_id="op:bind:duplicate-snapshot",
    )
    duplicate_artifact = "final-build:duplicate-snapshot"
    manifests[duplicate_artifact] = _manifest(
        duplicate_artifact,
        second_run,
        second_blueprint["targetLevel"],
        "binding-contract-hash",
        research_ref=second_blueprint["researchQueryRefs"][0],
    )
    duplicate_snapshot = progression_service.complete_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed_second["stageId"],
        claim_id=claimed_second["claimId"],
        artifact_id=duplicate_artifact,
        lifecycle_verification={
            "stage": second_blueprint["lifecycleStage"],
            "status": "passed",
            "pass": True,
            "evaluatedSourceHash": "binding-contract-hash",
        },
        cost_profile=_cost(claimed_second["stageId"]),
        completion_report={
            "purpose": "Reject a reused snapshot.",
            "playPattern": "Use the next stage loop.",
            "changesFromPrevious": [
                {
                    "category": "skill",
                    "action": "replace",
                    "subject": "Next Skill",
                    "replaces": "Starter Skill",
                    "reason": "Move to the next independently evaluated snapshot.",
                    "evidenceRefs": ["artifact:duplicate-snapshot"],
                }
            ],
            "sourceRefs": [],
        },
        expected_revision=bound_second["revision"],
        operation_id="op:complete:duplicate-snapshot",
    )
    assert duplicate_snapshot["errorCode"] == "progression_duplicate_snapshot"


def test_progression_pause_cas_idempotency_and_future_only_blueprint_revision(
    isolated_service,
):
    manifests = isolated_service
    progression_id, revision, blueprint = _start_and_blueprint()
    conflict = progression_service.pause_build_progression(
        progression_id=progression_id,
        expected_revision=revision - 1,
        operation_id="op:pause:conflict",
        reason="Checkpoint before the first stage.",
    )
    assert conflict["errorCode"] == "progression_revision_conflict"

    paused = progression_service.pause_build_progression(
        progression_id=progression_id,
        expected_revision=revision,
        operation_id="op:pause",
        reason="Checkpoint before the first stage.",
    )
    duplicate = progression_service.pause_build_progression(
        progression_id=progression_id,
        expected_revision=revision,
        operation_id="op:pause",
        reason="Checkpoint before the first stage.",
    )
    assert duplicate["idempotent"] is True
    assert duplicate["revision"] == paused["revision"]
    resumed = progression_service.resume_build_progression(
        progression_id=progression_id,
        expected_revision=paused["revision"],
        operation_id="op:resume",
    )

    claimed = progression_service.claim_build_progression_stage(
        progression_id=progression_id,
        expected_revision=resumed["revision"],
        operation_id="op:claim:immutable",
    )
    run_id = "20000000-0000-0000-0000-000000000001"
    bound = progression_service.bind_build_progression_stage_run(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        run_id=run_id,
        expected_revision=claimed["revision"],
        operation_id="op:bind:immutable",
    )
    stage_blueprint = blueprint["stages"][0]  # type: ignore[index]
    artifact_id = "final-build:immutable-first"
    source_hash = "immutable-first-hash"
    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        stage_blueprint["targetLevel"],
        source_hash,
        research_ref=stage_blueprint["researchQueryRefs"][0],
    )
    completed = progression_service.complete_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification={
            "stage": stage_blueprint["lifecycleStage"],
            "status": "passed",
            "pass": True,
            "evaluatedSourceHash": source_hash,
        },
        cost_profile=_cost(claimed["stageId"]),
        completion_report={
            "purpose": "Lock the first verified milestone.",
            "playPattern": "Use the starter loop.",
            "changesFromPrevious": [],
            "sourceRefs": [],
        },
        expected_revision=bound["revision"],
        operation_id="op:complete:immutable",
    )

    mutated_completed = deepcopy(blueprint)
    mutated_completed["blueprintId"] = "progression-blueprint:bad-revision"
    mutated_completed["stages"][0]["primarySkillIntent"] = "Changed Completed Skill"
    rejected = progression_service.revise_future_build_progression_stages(
        progression_id=progression_id,
        expected_revision=completed["revision"],
        operation_id="op:revise:completed",
        blueprint=mutated_completed,
    )
    assert rejected["errorCode"] == "started_progression_stage_immutable"

    future_only = deepcopy(blueprint)
    future_only["blueprintId"] = "progression-blueprint:future-revision"
    future_only["stages"][1]["primarySkillIntent"] = "Revised Future Skill"
    revised = progression_service.revise_future_build_progression_stages(
        progression_id=progression_id,
        expected_revision=completed["revision"],
        operation_id="op:revise:future",
        blueprint=future_only,
    )
    assert revised["status"] == "future_stages_revised"
    assert revised["preservedCompletedStageIds"] == ["stage:starter-10"]
    assert revised["preservedStartedStageIds"] == ["stage:starter-10"]


def test_progression_rejects_a_different_base_class(isolated_service):
    started = progression_service.start_build_progression(
        operation_id="op:start:class-mismatch",
        base_class="Monk",
        target_level=80,
        goal="Create a complete progression.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=0,
        operation_id="op:research:class-mismatch",
        packet=_research(),
    )
    blueprint = _blueprint(research["packetId"])
    blueprint["baseClass"] = "Witch"
    result = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:class-mismatch",
        blueprint=blueprint,
    )
    assert result["errorCode"] == "progression_base_class_mismatch"


def test_progression_artifact_must_use_stage_packet_research_ref(isolated_service):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:bound-research-ref",
        base_class="Monk",
        target_level=80,
        goal="Bind every stage artifact to the Research ref in its StageCreatePacket.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=started["revision"],
        operation_id="op:research:bound-research-ref",
        packet=_research(),
    )
    blueprint = _blueprint(research["packetId"])
    first_stage = blueprint["stages"][0]
    first_stage["researchQueryRefs"] = [
        "dq-0000000000000001",
        "dq-0000000000000002",
    ]
    accepted = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:bound-research-ref",
        blueprint=blueprint,
    )
    claimed = progression_service.claim_build_progression_stage(
        progression_id=started["progressionId"],
        expected_revision=accepted["revision"],
        operation_id="op:claim:bound-research-ref",
    )
    assert (
        claimed["stageCreatePacket"]["versionContext"]["researchMemoryRef"] == "dq-0000000000000002"
    )
    run_id = "20000000-0000-0000-0000-000000000001"
    bound = progression_service.bind_build_progression_stage_run(
        progression_id=started["progressionId"],
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        run_id=run_id,
        expected_revision=claimed["revision"],
        operation_id="op:bind:bound-research-ref",
    )
    artifact_id = "final-build:wrong-research-ref"
    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        first_stage["targetLevel"],
        "bound-research-ref-hash",
        research_ref="dq-0000000000000001",
    )

    result = progression_service.complete_build_progression_stage(
        progression_id=started["progressionId"],
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification={
            "stage": first_stage["lifecycleStage"],
            "status": "passed",
            "pass": True,
            "evaluatedSourceHash": "bound-research-ref-hash",
        },
        cost_profile=_cost(claimed["stageId"]),
        completion_report={
            "purpose": "Verify the first milestone.",
            "playPattern": "Use the stage loop.",
            "changesFromPrevious": [],
            "sourceRefs": [],
        },
        expected_revision=bound["revision"],
        operation_id="op:complete:bound-research-ref",
    )

    assert result["errorCode"] == "progression_stage_research_query_mismatch"


def test_progression_rejects_unbounded_lifecycle_payload(isolated_service):
    manifests = isolated_service
    progression_id, revision, blueprint = _start_and_blueprint()
    claimed = progression_service.claim_build_progression_stage(
        progression_id=progression_id,
        expected_revision=revision,
        operation_id="op:claim:bounded-lifecycle",
    )
    run_id = "30000000-0000-0000-0000-000000000001"
    bound = progression_service.bind_build_progression_stage_run(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        run_id=run_id,
        expected_revision=claimed["revision"],
        operation_id="op:bind:bounded-lifecycle",
    )
    artifact_id = "final-build:bounded-lifecycle"
    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        blueprint["stages"][0]["targetLevel"],  # type: ignore[index]
        "bounded-lifecycle-hash",
        research_ref=blueprint["stages"][0]["researchQueryRefs"][-1],  # type: ignore[index]
    )

    result = progression_service.complete_build_progression_stage(
        progression_id=progression_id,
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification={
            "stage": blueprint["stages"][0]["lifecycleStage"],  # type: ignore[index]
            "status": "passed",
            "pass": True,
            "failedChecks": [],
            "unknownChecks": [],
            "caveats": ["x" * 501],
            "evidenceTags": ["engine-computed"],
            "evaluatedSourceHash": "bounded-lifecycle-hash",
        },
        cost_profile=_cost(claimed["stageId"]),
        completion_report={
            "purpose": "Verify the first milestone.",
            "playPattern": "Use the stage loop.",
            "changesFromPrevious": [],
            "sourceRefs": [],
        },
        expected_revision=bound["revision"],
        operation_id="op:complete:bounded-lifecycle",
    )

    assert result["errorCode"] == "invalid_progression_lifecycle_verification"
