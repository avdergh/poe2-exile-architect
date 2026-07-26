from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
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

    def receipt_reader():
        def read(ref: str):
            suffix = int(ref.removeprefix("dq-"), 16)
            target = suffix not in {1, 2}
            return {
                "dedupeQueryRef": ref,
                "queryHash": f"hash:{ref}",
                "componentKeys": [],
                "request": {
                    "ascendancyKey": (
                        "ascendancy:target-monk" if target else "ascendancy:starter-monk"
                    ),
                    "primarySkillKey": (
                        "skill:target-attack" if target else "skill:starter-attack"
                    ),
                },
                "result": {
                    "buildFamilies": [],
                    "deepRecordIds": [],
                    "patternIds": [],
                    "semanticEdgeIds": [],
                    "memoryItemIds": [],
                },
                "lastSeenAt": datetime.now(timezone.utc).isoformat(),
                "noRawQuery": True,
                "noRawMatureBuildMaterial": True,
            }

        return read

    def phase5_provenance(run_id: str):
        manifest = next((item for item in manifests.values() if item.run_id == run_id), None)
        if manifest is None:
            return None
        ref = manifest.version_context.research_memory_ref
        return {
            "runId": run_id,
            "candidateId": manifest.candidate_id,
            "sourceHash": manifest.source_hash,
            "researchMemoryUse": {
                "retrievalOutcome": "no_matching_memory",
                "dedupeQueryRefs": [ref],
                "componentKeys": [],
                "buildFamilyKeys": [],
                "deepRecordIds": [],
                "patternIds": [],
                "semanticEdgeIds": [],
                "memoryItemIds": [],
                "insightDecisions": [],
                "noMatchReason": "No fixture memory was required.",
            },
            "finalFailureAudit": {
                "classification": "no_material_failure",
                "retryDecision": "accept",
            },
        }

    monkeypatch.setattr(progression_service, "_research_receipt_reader", receipt_reader)
    monkeypatch.setattr(progression_service, "_read_phase5_provenance", phase5_provenance)

    def lifecycle_receipt_reader(
        verification_ref: str,
        *,
        artifact_id: str,
        stage: str,
    ):
        manifest = manifests.get(artifact_id)
        if manifest is None or verification_ref != _lifecycle_ref(
            artifact_id,
            stage,
            manifest.source_hash,
        ):
            return None
        return {
            "schemaVersion": 1,
            "verificationRef": verification_ref,
            "artifactId": artifact_id,
            "sourceHash": manifest.source_hash,
            "restoredEngineSourceHash": f"restored:{manifest.source_hash}",
            "stage": stage,
            "status": "passed",
            "pass": True,
            "failedChecks": [],
            "unknownChecks": [],
            "caveats": [],
            "evidenceTags": ["engine-computed", "stage-verification"],
            "buildId": None,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "artifactBound": True,
            "noRawMaterial": True,
        }

    monkeypatch.setattr(
        progression_service.progression_lifecycle,
        "read_trusted_artifact_lifecycle_receipt",
        lifecycle_receipt_reader,
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


def _ready_transition(
    stage_blueprint: dict[str, object],
    source_hash: str,
) -> list[dict[str, object]]:
    bridge = stage_blueprint["entryBridge"]
    if bridge is None:
        return []
    return [
        {
            **requirement,
            "status": ("satisfied" if requirement["blocking"] else requirement["status"]),
            "evidenceRefs": ([f"snapshot:{source_hash}"] if requirement["blocking"] else []),
        }
        for requirement in bridge["requirements"]
    ]


def _blueprint(
    packet_id: str,
    *,
    target_anchor_artifact_id: str | None = None,
) -> dict[str, object]:
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
                    "ascendancyName": (
                        "Fast Campaign Ascendancy"
                        if family == "starter"
                        else "High Ceiling Ascendancy"
                    ),
                    "primarySkillName": (
                        "Early Attack" if family == "starter" else "Target Attack"
                    ),
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
        "targetAnchorArtifactId": target_anchor_artifact_id,
        "stages": stages,
        "mergeRationale": [],
        "versionContext": VERSION.model_dump(mode="json", by_alias=True),
        "noRawMaterial": True,
    }


def _target_coverage() -> dict[str, object]:
    dimensions = [
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
    ]
    return {
        "coverageId": "target-coverage:monk-target",
        "dimensions": [
            {
                "dimension": dimension,
                "status": "independently_verified",
                "summary": f"Verified {dimension} for the target fixture.",
                "evidenceRefs": [f"fixture:{dimension}"],
            }
            for dimension in dimensions
        ],
        "acceptanceSummary": "The target fixture covers every required design dimension.",
        "unresolvedCaveats": [],
        "agentAcceptance": "accepted",
    }


def _lifecycle_ref(artifact_id: str, stage: str, source_hash: str) -> str:
    digest = hashlib.sha256(f"{artifact_id}|{stage}|{source_hash}".encode()).hexdigest()[:16]
    return f"lifecycle-verification:{digest}"


def _lifecycle_result(
    artifact_id: str,
    stage: str,
    source_hash: str,
) -> dict[str, object]:
    return {
        "stage": stage,
        "status": "passed",
        "pass": True,
        "failedChecks": [],
        "unknownChecks": [],
        "caveats": [],
        "evidenceTags": ["engine-computed", "stage-verification"],
        "evaluatedSourceHash": source_hash,
        "verificationRef": _lifecycle_ref(artifact_id, stage, source_hash),
        "artifactBound": True,
    }


def _bind_target_anchor(
    started: dict[str, object],
    manifests: dict[str, SimpleNamespace],
    *,
    operation_suffix: str,
    design_coverage: dict[str, object] | None = None,
    secondary_skill_keys: list[str] | None = None,
    secondary_skill_names: list[str] | None = None,
    manifest_core_skills: list[str] | None = None,
) -> dict[str, object]:
    artifact_id = f"final-build:target-anchor-{operation_suffix}"
    run_id = f"90000000-0000-0000-0000-{len(manifests) + 1:012d}"
    source_hash = f"target-anchor-hash-{operation_suffix}"
    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        80,
        source_hash,
        research_ref="dq-0000000000000004",
        ascendancy="High Ceiling Ascendancy",
        main_skill="Target Attack",
        core_skills=manifest_core_skills,
    )
    coverage_payload = deepcopy(design_coverage or _target_coverage())
    for dimension in coverage_payload["dimensions"]:
        if dimension["status"] == "independently_verified" and all(
            str(ref).startswith("fixture:") for ref in dimension["evidenceRefs"]
        ):
            dimension["evidenceRefs"] = [
                artifact_id,
                f"generation:{run_id}:{source_hash}",
            ]
    return progression_service.bind_build_progression_target_anchor(
        progression_id=str(started["progressionId"]),
        artifact_id=artifact_id,
        target_identity={
            "ascendancyKey": "ascendancy:target-monk",
            "primarySkillKey": "skill:target-attack",
            "secondarySkillKeys": secondary_skill_keys or [],
            "ascendancyName": "High Ceiling Ascendancy",
            "primarySkillName": "Target Attack",
            "secondarySkillNames": secondary_skill_names or [],
        },
        design_coverage=coverage_payload,
        lifecycle_verification_ref=_lifecycle_ref(
            artifact_id,
            "maps_entry",
            source_hash,
        ),
        expected_revision=int(started["revision"]),
        operation_id=f"op:anchor:{operation_suffix}",
    )


def _start_and_blueprint(
    manifests: dict[str, SimpleNamespace],
) -> tuple[str, int, dict[str, object]]:
    started = progression_service.start_build_progression(
        operation_id="op:start",
        base_class="Monk",
        target_level=80,
        goal="Create a fast starter that transitions into a high-ceiling target.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    progression_id = started["progressionId"]
    anchored = _bind_target_anchor(started, manifests, operation_suffix="default")
    research = progression_service.intake_starter_research_packet(
        progression_id=progression_id,
        expected_revision=anchored["revision"],
        operation_id="op:research",
        packet=_research(),
    )
    packet_id = research["packetId"]
    blueprint = _blueprint(
        packet_id,
        target_anchor_artifact_id=anchored["targetArtifactId"],
    )
    accepted = progression_service.submit_build_progression_blueprint(
        progression_id=progression_id,
        expected_revision=research["revision"],
        operation_id="op:blueprint",
        blueprint=blueprint,
    )
    return progression_id, accepted["revision"], blueprint


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


def test_progression_blueprint_rejects_research_receipts_not_queried_in_this_run(
    isolated_service,
    monkeypatch,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:historical-blueprint-receipt",
        base_class="Monk",
        target_level=80,
        goal="Reject a blueprint assembled from historical Research receipts.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    anchored = _bind_target_anchor(
        started,
        manifests,
        operation_suffix="historical-blueprint-receipt",
    )
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=anchored["revision"],
        operation_id="op:research:historical-blueprint-receipt",
        packet=_research(),
    )
    blueprint = _blueprint(
        research["packetId"],
        target_anchor_artifact_id=anchored["targetArtifactId"],
    )
    current_reader = progression_service._research_receipt_reader()

    def historical_reader():
        def read(ref: str):
            receipt = current_reader(ref)
            return {**receipt, "lastSeenAt": "2020-01-01T00:00:00+00:00"} if receipt else None

        return read

    monkeypatch.setattr(
        progression_service,
        "_research_receipt_reader",
        historical_reader,
    )

    result = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:historical-blueprint-receipt",
        blueprint=blueprint,
    )

    assert result["errorCode"] == "progression_research_receipt_not_current_run"


def test_progression_blueprint_target_stage_must_match_the_anchor_lifecycle_scope(
    isolated_service,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:target-lifecycle-scope",
        base_class="Monk",
        target_level=80,
        goal="Keep target lifecycle identity aligned with its accepted anchor receipt.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    anchored = _bind_target_anchor(
        started,
        manifests,
        operation_suffix="target-lifecycle-scope",
    )
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=anchored["revision"],
        operation_id="op:research:target-lifecycle-scope",
        packet=_research(),
    )
    blueprint = _blueprint(
        research["packetId"],
        target_anchor_artifact_id=anchored["targetArtifactId"],
    )
    blueprint["stages"][-1]["lifecycleStage"] = "campaign_late"

    result = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:target-lifecycle-scope",
        blueprint=blueprint,
    )

    assert result["errorCode"] == "progression_target_anchor_lifecycle_stage_mismatch"


def test_progression_blueprint_rejects_when_all_starter_claims_are_rejected(
    isolated_service,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:all-rejected",
        base_class="Monk",
        target_level=80,
        goal="Create a complete progression with bounded starter evidence.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    anchored = _bind_target_anchor(started, manifests, operation_suffix="all-rejected")
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=anchored["revision"],
        operation_id="op:research:all-rejected",
        packet=_research(),
    )
    blueprint = _blueprint(
        research["packetId"],
        target_anchor_artifact_id=anchored["targetArtifactId"],
    )
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
    ascendancy: str = "Fast Campaign Ascendancy",
    main_skill: str = "Early Attack",
    core_skills: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        artifact_id=artifact_id,
        run_id=run_id,
        candidate_id=f"candidate:{artifact_id}",
        source_hash=source_hash,
        created_at=datetime.now(timezone.utc).isoformat(),
        safe_summary={
            "level": str(level),
            "class": class_shell,
            "ascendancy": ascendancy,
            "mainSkill": main_skill,
        },
        tested_skill_groups=[SimpleNamespace(enabled=True, active_skills=list(core_skills or []))],
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


def test_starter_cache_is_withheld_from_target_create_then_exposed_after_anchor(
    isolated_service,
):
    manifests = isolated_service
    seeded = progression_service.start_build_progression(
        operation_id="op:start:cache-seed",
        base_class="Monk",
        target_level=80,
        goal="Seed one safe starter packet.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    seeded_anchor = _bind_target_anchor(seeded, manifests, operation_suffix="cache-seed")
    accepted = progression_service.intake_starter_research_packet(
        progression_id=seeded["progressionId"],
        expected_revision=seeded_anchor["revision"],
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
    assert reused["currentState"] == "target_anchor_pending"
    assert reused["starterResearchPacket"] is None
    assert reused["starterResearchCandidate"] is None
    assert reused["starterEvidenceWithheldUntilAnchor"] is True
    assert reused["starterCache"] == {
        "evidenceAvailable": True,
        "withheldUntilAnchor": True,
    }
    assert accepted["packetId"] not in json.dumps(reused)
    before_anchor = progression_service.get_build_progression_status(reused["progressionId"])
    assert before_anchor["buildProgression"]["starterResearchPacket"] is None
    assert before_anchor["buildProgression"]["starterEvidenceWithheldUntilAnchor"] is True
    reused_anchor = _bind_target_anchor(reused, manifests, operation_suffix="cache-consumer")
    assert reused_anchor["nextAction"] == "submit_blueprint"
    status = progression_service.get_build_progression_status(reused["progressionId"])
    assert status["buildProgression"]["currentState"] == "blueprint_pending"
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
    assert stale["currentState"] == "target_anchor_pending"
    assert stale["starterResearchPacket"] is None
    assert stale["starterResearchCandidate"] is None
    assert stale["starterEvidenceWithheldUntilAnchor"] is True
    assert stale["starterCache"] == {
        "evidenceAvailable": True,
        "withheldUntilAnchor": True,
    }
    assert accepted["packetId"] not in json.dumps(stale)
    stale_anchor = _bind_target_anchor(stale, manifests, operation_suffix="stale-candidate")
    assert stale_anchor["nextAction"] == "intake_starter_research"
    stale_status = progression_service.get_build_progression_status(stale["progressionId"])
    assert stale_status["buildProgression"]["currentState"] == "research_pending"
    assert (
        stale_status["buildProgression"]["starterResearchCandidate"]["packetId"]
        == (accepted["packetId"])
    )


def test_starter_stage_evidence_cannot_overstate_a_limited_web_packet(isolated_service):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:limited-evidence",
        base_class="Monk",
        target_level=80,
        goal="Keep starter and target evidence separate.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    anchored = _bind_target_anchor(started, manifests, operation_suffix="limited-evidence")
    research_packet = _research()
    research_packet["sources"][0]["sourceKind"] = "aggregator"
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=anchored["revision"],
        operation_id="op:research:limited-evidence",
        packet=research_packet,
    )
    assert research["evidenceStatus"] == "limited"

    overstated = _blueprint(
        research["packetId"],
        target_anchor_artifact_id=anchored["targetArtifactId"],
    )
    rejected = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:overstated-evidence",
        blueprint=overstated,
    )
    assert rejected["errorCode"] == "starter_stage_evidence_status_mismatch"

    corrected = _blueprint(
        research["packetId"],
        target_anchor_artifact_id=anchored["targetArtifactId"],
    )
    for stage in corrected["stages"][:2]:
        stage["evidenceStatus"] = "limited"
    accepted = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:bounded-evidence",
        blueprint=corrected,
    )
    assert accepted["status"] == "blueprint_accepted"


def test_progression_is_serial_cas_bound_and_finalizes_anchored_route_v3(isolated_service):
    manifests = isolated_service
    progression_id, revision, blueprint = _start_and_blueprint(manifests)
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
            == stage_blueprint["researchQueryRefs"][0]
        )
        if stage_blueprint["rebuildFromScratch"]:
            assert claimed["stageCreatePacket"]["previousArtifactId"] is None
        duplicate = progression_service.claim_build_progression_stage(
            progression_id=progression_id,
            expected_revision=revision,
            operation_id=f"op:other-claim:{index}",
        )
        assert duplicate["errorCode"] == "progression_stage_not_claimable"

        if stage_blueprint["routeRole"] == "target":
            assert claimed["requiresPhase5Run"] is False
            artifact_id = blueprint["targetAnchorArtifactId"]
            anchor_manifest = manifests[artifact_id]
            source_hash = anchor_manifest.source_hash
        else:
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
                ascendancy=stage_blueprint["familyIdentity"]["ascendancyName"],
                main_skill=stage_blueprint["familyIdentity"]["primarySkillName"],
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
        if stage_blueprint["routeRole"] == "target":
            not_ready = progression_service.complete_build_progression_stage(
                progression_id=progression_id,
                stage_id=claimed["stageId"],
                claim_id=claimed["claimId"],
                artifact_id=artifact_id,
                lifecycle_verification=_lifecycle_result(
                    artifact_id,
                    stage_blueprint["lifecycleStage"],
                    source_hash,
                ),
                cost_profile=_cost(claimed["stageId"]),
                completion_report={
                    "purpose": "Do not close the target before its mechanism gates are ready.",
                    "playPattern": "Keep the previous verified bridge form.",
                    "changesFromPrevious": changes,
                    "sourceRefs": [],
                    "transitionReadiness": [],
                },
                expected_revision=revision,
                operation_id="op:complete:target-not-ready",
            )
            assert not_ready["errorCode"] == "progression_transition_readiness_incomplete"
        completed = progression_service.complete_build_progression_stage(
            progression_id=progression_id,
            stage_id=claimed["stageId"],
            claim_id=claimed["claimId"],
            artifact_id=artifact_id,
            lifecycle_verification=_lifecycle_result(
                artifact_id,
                stage_blueprint["lifecycleStage"],
                source_hash,
            ),
            cost_profile=_cost(claimed["stageId"]),
            completion_report={
                "purpose": f"Verify milestone {index + 1}.",
                "playPattern": "Use the stage-specific main loop and keep moving.",
                "changesFromPrevious": changes,
                "acquisitionPriorities": ["resistance coverage"],
                "caveats": [],
                "sourceRefs": ["starter-research:packet-safe"],
                "transitionReadiness": _ready_transition(stage_blueprint, source_hash),
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
    route = progression_service.progression.read_progression_route(finalized["routeId"])
    assert route["schemaVersion"] == 3
    assert route["targetAnchorArtifactId"] == blueprint["targetAnchorArtifactId"]
    status = progression_service.get_build_progression_status(progression_id)
    assert status["buildProgression"]["currentState"] == "completed"
    assert len(status["buildProgression"]["stages"]) == 4
    assert (
        status["buildProgression"]["targetAnchor"]["artifactId"]
        == (blueprint["targetAnchorArtifactId"])
    )
    target_manifest = manifests[blueprint["targetAnchorArtifactId"]]
    target_manifest.judge_report.playability_failures = ["resource_loop_not_sustainable"]
    cloned_payload = {
        key: route[key]
        for key in (
            "routeName",
            "classShell",
            "targetArtifactId",
            "stages",
            "routeSummary",
            "starterResearchPacketId",
            "targetAnchorArtifactId",
            "targetDesignCoverage",
            "versionContext",
        )
    }
    cloned_payload["noRawMaterial"] = True
    limited = progression_service.progression.save_anchored_progression_route(
        cloned_payload,
        route_id="00000000-0000-0000-0000-000000000099",
    )
    assert limited["status"] == "saved"
    assert limited["progressionRoute"]["qualityStatus"] == "limited"


def test_progression_rejects_hash_mismatch_and_allows_only_one_external_retry(
    isolated_service,
):
    manifests = isolated_service
    progression_id, revision, blueprint = _start_and_blueprint(manifests)
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
            "verificationRef": _lifecycle_ref(
                artifact_id,
                blueprint["stages"][0]["lifecycleStage"],  # type: ignore[index]
                "wrong-hash",
            ),
            "artifactBound": True,
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
    assert rejected["errorCode"] == "progression_lifecycle_receipt_not_trusted"

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
    progression_id, revision, blueprint = _start_and_blueprint(manifests)
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
        **_lifecycle_result(
            artifact_id,
            first_blueprint["lifecycleStage"],
            "binding-contract-hash",
        ),
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
            **_lifecycle_result(
                duplicate_artifact,
                second_blueprint["lifecycleStage"],
                "binding-contract-hash",
            ),
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
            "transitionReadiness": _ready_transition(
                second_blueprint,
                "binding-contract-hash",
            ),
        },
        expected_revision=bound_second["revision"],
        operation_id="op:complete:duplicate-snapshot",
    )
    assert duplicate_snapshot["errorCode"] == "progression_duplicate_snapshot"


def test_progression_pause_cas_idempotency_and_future_only_blueprint_revision(
    isolated_service,
):
    manifests = isolated_service
    progression_id, revision, blueprint = _start_and_blueprint(manifests)
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
        lifecycle_verification=_lifecycle_result(
            artifact_id,
            stage_blueprint["lifecycleStage"],
            source_hash,
        ),
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
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:class-mismatch",
        base_class="Monk",
        target_level=80,
        goal="Create a complete progression.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    anchored = _bind_target_anchor(started, manifests, operation_suffix="class-mismatch")
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=anchored["revision"],
        operation_id="op:research:class-mismatch",
        packet=_research(),
    )
    blueprint = _blueprint(
        research["packetId"],
        target_anchor_artifact_id=anchored["targetArtifactId"],
    )
    blueprint["baseClass"] = "Witch"
    result = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:class-mismatch",
        blueprint=blueprint,
    )
    assert result["errorCode"] == "progression_base_class_mismatch"


def test_progression_stage_artifact_keeps_the_claimed_research_ref(isolated_service):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:bound-research-ref",
        base_class="Monk",
        target_level=80,
        goal="Bind every stage artifact to the Research ref in its StageCreatePacket.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    anchored = _bind_target_anchor(started, manifests, operation_suffix="progressive-ref")
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=anchored["revision"],
        operation_id="op:research:bound-research-ref",
        packet=_research(),
    )
    blueprint = _blueprint(
        research["packetId"],
        target_anchor_artifact_id=anchored["targetArtifactId"],
    )
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
        claimed["stageCreatePacket"]["versionContext"]["researchMemoryRef"] == "dq-0000000000000001"
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
    artifact_id = "final-build:progressive-research-ref"
    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        first_stage["targetLevel"],
        "bound-research-ref-hash",
        research_ref="dq-0000000000000002",
    )

    result = progression_service.complete_build_progression_stage(
        progression_id=started["progressionId"],
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification=_lifecycle_result(
            artifact_id,
            first_stage["lifecycleStage"],
            "bound-research-ref-hash",
        ),
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


def test_progression_uses_the_trusted_receipt_instead_of_unbounded_caller_fields(
    isolated_service,
):
    manifests = isolated_service
    progression_id, revision, blueprint = _start_and_blueprint(manifests)
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
            "verificationRef": _lifecycle_ref(
                artifact_id,
                blueprint["stages"][0]["lifecycleStage"],  # type: ignore[index]
                "bounded-lifecycle-hash",
            ),
            "artifactBound": True,
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

    assert result["status"] == "stage_completed"
    status = progression_service.get_build_progression_status(progression_id)
    assert status["buildProgression"]["stages"][0]["lifecycleVerification"]["caveats"] == []


def test_progression_rejects_a_target_anchor_with_failed_lifecycle_receipt(
    isolated_service,
    monkeypatch,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:failed-lifecycle-anchor",
        base_class="Monk",
        target_level=80,
        goal="Reject a resource-broken target before it shapes the progression.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    artifact_id = "final-build:failed-lifecycle-anchor"
    run_id = "70000000-0000-0000-0000-000000000001"
    source_hash = "failed-lifecycle-anchor-hash"
    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        80,
        source_hash,
        research_ref="dq-0000000000000004",
        ascendancy="High Ceiling Ascendancy",
        main_skill="Target Attack",
    )
    verification_ref = _lifecycle_ref(artifact_id, "maps_entry", source_hash)
    monkeypatch.setattr(
        progression_service.progression_lifecycle,
        "read_trusted_artifact_lifecycle_receipt",
        lambda ref, *, artifact_id, stage: {
            "verificationRef": ref,
            "artifactId": artifact_id,
            "sourceHash": source_hash,
            "stage": stage,
            "status": "failed",
            "pass": False,
            "failedChecks": ["sustain_ok"],
            "unknownChecks": [],
            "caveats": [],
            "evidenceTags": ["engine-computed", "stage-verification"],
        },
    )

    result = progression_service.bind_build_progression_target_anchor(
        progression_id=started["progressionId"],
        artifact_id=artifact_id,
        target_identity={
            "ascendancyKey": "ascendancy:target-monk",
            "primarySkillKey": "skill:target-attack",
            "secondarySkillKeys": [],
            "ascendancyName": "High Ceiling Ascendancy",
            "primarySkillName": "Target Attack",
        },
        design_coverage=_target_coverage(),
        lifecycle_verification_ref=verification_ref,
        expected_revision=started["revision"],
        operation_id="op:anchor:failed-lifecycle",
    )

    assert result["errorCode"] == "progression_target_anchor_lifecycle_not_verified"
    status = progression_service.get_build_progression_status(started["progressionId"])
    assert status["buildProgression"]["currentState"] == "target_anchor_pending"


def test_progression_rejects_target_anchor_when_agent_found_a_real_build_failure(
    isolated_service,
    monkeypatch,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:bad-anchor",
        base_class="Monk",
        target_level=80,
        goal="Do not anchor a target that the creating Agent rejected.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    artifact_id = "final-build:bad-target-anchor"
    run_id = "80000000-0000-0000-0000-000000000001"
    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        80,
        "bad-target-anchor-hash",
        research_ref="dq-0000000000000004",
        ascendancy="High Ceiling Ascendancy",
        main_skill="Target Attack",
    )
    monkeypatch.setattr(
        progression_service,
        "_read_phase5_provenance",
        lambda _run_id: {
            "candidateId": manifests[artifact_id].candidate_id,
            "sourceHash": manifests[artifact_id].source_hash,
            "researchMemoryUse": {
                "retrievalOutcome": "no_matching_memory",
                "dedupeQueryRefs": ["dq-0000000000000004"],
                "componentKeys": [],
                "buildFamilyKeys": [],
                "deepRecordIds": [],
                "patternIds": [],
                "semanticEdgeIds": [],
                "memoryItemIds": [],
                "insightDecisions": [],
                "noMatchReason": "No fixture memory.",
            },
            "finalFailureAudit": {
                "classification": "true_build_failure",
                "retryDecision": "accept",
            },
        },
    )

    result = progression_service.bind_build_progression_target_anchor(
        progression_id=started["progressionId"],
        artifact_id=artifact_id,
        target_identity={
            "ascendancyKey": "ascendancy:target-monk",
            "primarySkillKey": "skill:target-attack",
            "secondarySkillKeys": [],
            "ascendancyName": "High Ceiling Ascendancy",
            "primarySkillName": "Target Attack",
        },
        design_coverage=_target_coverage(),
        lifecycle_verification_ref=_lifecycle_ref(
            artifact_id,
            "maps_entry",
            "bad-target-anchor-hash",
        ),
        expected_revision=started["revision"],
        operation_id="op:anchor:bad-anchor",
    )

    assert result["errorCode"] == "progression_target_anchor_agent_rejected"
    status = progression_service.get_build_progression_status(started["progressionId"])
    assert status["buildProgression"]["currentState"] == "target_anchor_pending"


def test_progression_rejects_target_anchor_from_a_preexisting_phase5_run(
    isolated_service,
    monkeypatch,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:old-anchor-run",
        base_class="Monk",
        target_level=80,
        goal="Require a target run created for this progression.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    monkeypatch.setattr(
        progression_service,
        "_valid_phase5_run",
        lambda _run_id, *, not_before: False,
    )

    result = _bind_target_anchor(
        started,
        manifests,
        operation_suffix="old-anchor-run",
    )

    assert result["errorCode"] == "progression_target_anchor_run_not_new"
    status = progression_service.get_build_progression_status(started["progressionId"])
    assert status["buildProgression"]["currentState"] == "target_anchor_pending"


def test_progression_rejects_untraceable_research_adopted_target_coverage(
    isolated_service,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:untraceable-coverage",
        base_class="Monk",
        target_level=80,
        goal="Require adopted target knowledge to trace to actual Research use.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    coverage = _target_coverage()
    coverage["dimensions"][0] = {
        **coverage["dimensions"][0],
        "status": "research_adopted",
        "evidenceRefs": ["deep-record:not-returned"],
    }

    result = _bind_target_anchor(
        started,
        manifests,
        operation_suffix="untraceable-coverage",
        design_coverage=coverage,
    )

    assert result["errorCode"] == "progression_target_coverage_research_ref_not_used"


def test_target_coverage_requires_an_adopted_research_item_not_only_a_query_receipt():
    coverage = _target_coverage()
    coverage["dimensions"][0] = {
        **coverage["dimensions"][0],
        "status": "research_adopted",
        "evidenceRefs": ["dq-0000000000000004"],
    }
    validated = progression_models.TargetDesignCoverage.model_validate(coverage)
    provenance = {
        "dedupeQueryRefs": ["dq-0000000000000004"],
        "exactIdentityQueryRefs": ["dq-0000000000000004"],
        "buildFamilyKeys": [],
        "deepRecordIds": [],
        "patternIds": [],
        "semanticEdgeIds": [],
        "memoryItemIds": [],
    }

    assert (
        progression_service._validate_target_coverage_provenance(
            validated,
            provenance,
            trusted_independent_refs={
                ref
                for item in validated.dimensions
                if item.status == "independently_verified"
                for ref in item.evidence_refs
            },
        )
        == "progression_target_coverage_research_ref_not_used"
    )

    provenance["deepRecordIds"] = ["deep-record:target-loop"]
    coverage["dimensions"][0]["evidenceRefs"] = ["deep-record:target-loop"]
    validated = progression_models.TargetDesignCoverage.model_validate(coverage)
    assert (
        progression_service._validate_target_coverage_provenance(
            validated,
            provenance,
            trusted_independent_refs={
                ref
                for item in validated.dimensions
                if item.status == "independently_verified"
                for ref in item.evidence_refs
            },
        )
        is None
    )


def test_progression_rejects_untrusted_independently_verified_target_coverage(
    isolated_service,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:untrusted-independent-coverage",
        base_class="Monk",
        target_level=80,
        goal="Require independently verified target coverage to bind to the target snapshot.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    coverage = _target_coverage()
    coverage["dimensions"][0]["evidenceRefs"] = ["untrusted:target-snapshot"]

    result = _bind_target_anchor(
        started,
        manifests,
        operation_suffix="untrusted-independent-coverage",
        design_coverage=coverage,
    )

    assert result["errorCode"] == "progression_target_coverage_independent_ref_not_trusted"


def test_progression_target_core_secondary_skill_must_exist_in_the_anchor_artifact(
    isolated_service,
):
    manifests = isolated_service
    missing_started = progression_service.start_build_progression(
        operation_id="op:start:missing-core-skill",
        base_class="Monk",
        target_level=80,
        goal="Bind the declared target core skill to the tested artifact.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    missing = _bind_target_anchor(
        missing_started,
        manifests,
        operation_suffix="missing-core-skill",
        secondary_skill_keys=["skill:TempestBellPlayer"],
        secondary_skill_names=["Tempest Bell"],
        manifest_core_skills=[],
    )
    assert missing["errorCode"] == "progression_target_anchor_family_mismatch"

    present_started = progression_service.start_build_progression(
        operation_id="op:start:present-core-skill",
        base_class="Monk",
        target_level=80,
        goal="Accept the target when its declared core skill is enabled.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    present = _bind_target_anchor(
        present_started,
        manifests,
        operation_suffix="present-core-skill",
        secondary_skill_keys=["skill:TempestBellPlayer"],
        secondary_skill_names=["Tempest Bell"],
        manifest_core_skills=["Tempest Bell"],
    )
    assert present["status"] == "target_anchor_bound"
