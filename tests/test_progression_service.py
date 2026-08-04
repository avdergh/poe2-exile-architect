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
        progression_service,
        "_phase5_run_manifest",
        lambda run_id, *, not_before, require_fresh=True: {
            "startedAt": not_before,
            "experimentContext": {
                "memoryMode": (
                    "standard"
                    if run_id == "12000000-0000-0000-0000-000000000001"
                    else "memory_assisted"
                )
            },
        },
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
            if ref in {"dq-aaaaaaaaaaaaaaaa", "dq-cccccccccccccccc"}:
                families = [
                    {
                        "buildFamilyKey": "family:target-high",
                        "ascendancyKey": "ascendancy:target-monk",
                        "primarySkillKey": "skill:target-attack",
                        "secondarySkillKeys": [],
                    },
                    {
                        "buildFamilyKey": "family:target-alternate",
                        "ascendancyKey": "ascendancy:alternate-monk",
                        "primarySkillKey": "skill:alternate-attack",
                        "secondarySkillKeys": [],
                    },
                ]
                if ref == "dq-cccccccccccccccc":
                    families = families[:1]
                return {
                    "dedupeQueryRef": ref,
                    "queryHash": f"hash:{ref}",
                    "componentKeys": [],
                    "request": {
                        "detailLevel": "family",
                        "classKey": "class:monk",
                        "gamePatch": "0.5.4",
                        "passiveTreeVersion": "0_5",
                        "limit": 10,
                        "ascendancyKey": None,
                        "primarySkillKey": None,
                        "buildFamilyKeys": [],
                    },
                    "result": {
                        "buildFamilies": families,
                        "deepRecordIds": [],
                        "patternIds": [],
                        "semanticEdgeIds": [],
                        "memoryItemIds": [],
                    },
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "lastSeenAt": datetime.now(timezone.utc).isoformat(),
                    "noRawQuery": True,
                    "noRawMatureBuildMaterial": True,
                }
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
                "createdAt": datetime.now(timezone.utc).isoformat(),
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
                "componentKeys": [
                    "ascendancy:starter-monk",
                    "skill:starter-attack",
                ],
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
                "rebuildReason": (
                    "The target skill and resource engine replace the established starter route."
                    if index == 2
                    else None
                ),
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


def _use_common_unascended_starter(
    blueprint: dict[str, object],
    packet_id: str,
) -> dict[str, object]:
    first = blueprint["stages"][0]
    first["knowledgeMode"] = "starter_common"
    first["familyIdentity"] = None
    first["starterIdentity"] = {
        "primarySkillKey": "skill:starter-attack",
        "secondarySkillKeys": [],
        "primarySkillName": "Early Attack",
        "secondarySkillNames": [],
        "expectedAscendancyKey": None,
        "expectedAscendancyName": None,
    }
    first["ascendancyIntent"] = "Remain unascended before the first campaign trial."
    first["researchQueryRefs"] = []
    first["commonKnowledgeRefs"] = [packet_id, "skill:starter-attack"]
    return blueprint


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


def _target_selection() -> dict[str, object]:
    candidates = [
        {
            "candidateId": "target-candidate:high-ceiling",
            "buildFamilyKey": "family:target-high",
            "familyDiscoveryRef": "dq-aaaaaaaaaaaaaaaa",
            "identity": {
                "ascendancyKey": "ascendancy:target-monk",
                "primarySkillKey": "skill:target-attack",
                "secondarySkillKeys": [],
                "ascendancyName": "High Ceiling Ascendancy",
                "primarySkillName": "Target Attack",
                "secondarySkillNames": [],
            },
            "mechanismSummary": "Scale the verified target attack through its primary loop.",
            "expectedStrengths": ["High target ceiling after the mechanism closes."],
            "knownRisks": ["Requires the target resource loop to be verified."],
            "evidenceRefs": ["dq-aaaaaaaaaaaaaaaa", "dq-0000000000000004"],
            "globalOptimizerUsed": False,
            "fullJudgeUsed": False,
        },
        {
            "candidateId": "target-candidate:alternate",
            "buildFamilyKey": "family:target-alternate",
            "familyDiscoveryRef": "dq-aaaaaaaaaaaaaaaa",
            "identity": {
                "ascendancyKey": "ascendancy:alternate-monk",
                "primarySkillKey": "skill:alternate-attack",
                "secondarySkillKeys": [],
                "ascendancyName": "Alternate Ascendancy",
                "primarySkillName": "Alternate Attack",
                "secondarySkillNames": [],
            },
            "mechanismSummary": "Use a simpler alternate attack with a lower projected ceiling.",
            "expectedStrengths": ["Simpler initial mechanism closure."],
            "knownRisks": ["Lower projected target scaling."],
            "evidenceRefs": ["dq-aaaaaaaaaaaaaaaa", "skill:alternate-attack"],
            "globalOptimizerUsed": False,
            "fullJudgeUsed": False,
        },
    ]
    return {
        "selectionId": "target-selection:fixture",
        "familyDiscoveryRef": "dq-aaaaaaaaaaaaaaaa",
        "candidates": candidates,
        "dimensionComparisons": [
            {
                "dimension": "mechanism_closure",
                "preferredCandidateId": "target-candidate:high-ceiling",
                "summary": "The selected loop has a verifiable closure plan.",
            },
            {
                "dimension": "research_support",
                "preferredCandidateId": "target-candidate:high-ceiling",
                "summary": "The selected Family has the stronger exact Research basis.",
            },
            {
                "dimension": "goal_fit_and_power_evidence",
                "preferredCandidateId": "target-candidate:high-ceiling",
                "summary": "The selected Family has stronger evidence for the requested ceiling.",
            },
            {
                "dimension": "playability_risk",
                "preferredCandidateId": "target-candidate:alternate",
                "summary": "The alternate is simpler but gives up the requested ceiling.",
            },
            {
                "dimension": "modelability",
                "preferredCandidateId": "target-candidate:high-ceiling",
                "summary": "Both are modelable and the selected candidate better fits the goal.",
            },
        ],
        "candidateRanking": [
            "target-candidate:high-ceiling",
            "target-candidate:alternate",
        ],
        "selectedCandidateId": "target-candidate:high-ceiling",
        "selectionSummary": "Select the high-ceiling target after comparing every discovered Family.",
        "unresolvedRisks": ["Verify the complete resource loop in the ordinary target Create."],
    }


def _select_target_candidates(
    started: dict[str, object],
    *,
    operation_suffix: str,
    selection: dict[str, object] | None = None,
) -> dict[str, object]:
    return progression_service.submit_build_progression_target_selection(
        progression_id=str(started["progressionId"]),
        selection=selection or _target_selection(),
        expected_revision=int(started["revision"]),
        operation_id=f"op:target-selection:{operation_suffix}",
    )


def _bind_target_anchor(
    started: dict[str, object],
    manifests: dict[str, SimpleNamespace],
    *,
    operation_suffix: str,
    design_coverage: dict[str, object] | None = None,
    secondary_skill_keys: list[str] | None = None,
    secondary_skill_names: list[str] | None = None,
    manifest_core_skills: list[str] | None = None,
    manifest_graph_snapshot_id: str | None = None,
    selected_primary_skill_name: str | None = None,
    artifact_primary_skill_name: str | None = None,
    acceptance_decision: str = "accepted",
) -> dict[str, object]:
    selection = _target_selection()
    if selected_primary_skill_name is not None:
        selection["candidates"][0]["identity"]["primarySkillName"] = selected_primary_skill_name
    if secondary_skill_keys is not None:
        selection["candidates"][0]["identity"]["secondarySkillKeys"] = secondary_skill_keys
        selection["candidates"][0]["identity"]["secondarySkillNames"] = secondary_skill_names or []
    selected = _select_target_candidates(
        started,
        operation_suffix=operation_suffix,
        selection=selection,
    )
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
        main_skill=artifact_primary_skill_name or "Target Attack",
        core_skills=manifest_core_skills,
        graph_snapshot_id=manifest_graph_snapshot_id,
    )
    run_bound = progression_service.bind_build_progression_target_run(
        progression_id=str(started["progressionId"]),
        run_id=run_id,
        expected_revision=int(selected["revision"]),
        operation_id=f"op:anchor-run:{operation_suffix}",
    )
    if "revision" not in run_bound:
        return run_bound
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
            "primarySkillName": artifact_primary_skill_name or "Target Attack",
            "secondarySkillNames": secondary_skill_names or [],
        },
        design_coverage=coverage_payload,
        lifecycle_verification_ref=_lifecycle_ref(
            artifact_id,
            "maps_entry",
            source_hash,
        ),
        expected_revision=int(run_bound["revision"]),
        operation_id=f"op:anchor:{operation_suffix}",
        acceptance_decision=acceptance_decision,
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


def test_progression_requires_two_target_candidates_before_target_create(isolated_service):
    started = progression_service.start_build_progression(
        operation_id="op:start:target-selection-contract",
        base_class="Monk",
        target_level=80,
        goal="Compare two bounded target designs before full synthesis.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )

    assert started["nextAction"] == "compare_and_select_target_candidates"
    assert started["targetCandidateSelectionPacket"]["candidateCountRequested"] == 10
    assert started["targetCandidateSelectionPacket"]["minimumCandidateCount"] == 2
    assert started["targetCandidateSelectionPacket"]["globalOptimizerAllowed"] is False
    assert started["targetAnchorCreatePacket"] is None

    blocked = progression_service.bind_build_progression_target_anchor(
        progression_id=started["progressionId"],
        artifact_id="final-build:not-yet-created",
        target_identity=_target_selection()["candidates"][0]["identity"],
        design_coverage=_target_coverage(),
        lifecycle_verification_ref="lifecycle-verification:0000000000000000",
        expected_revision=started["revision"],
        operation_id="op:anchor:before-selection",
    )
    assert blocked["errorCode"] == "progression_target_selection_required"

    selected = _select_target_candidates(
        started,
        operation_suffix="selection-contract",
    )
    packet = selected["targetAnchorCreatePacket"]
    assert packet["selectedCandidateId"] == "target-candidate:high-ceiling"
    assert packet["selectedTargetIdentity"]["primarySkillKey"] == "skill:target-attack"
    assert packet["selectedCandidate"]["mechanismSummary"].startswith("Scale the verified")
    assert packet["globalOptimizerAllowed"] is False
    assert packet["optimizationPolicy"]["passiveTreeOptimizationMode"] == "manual_targeted"
    assert packet["optimizationPolicy"]["loadoutScope"] == "stage_complete_loadout"


def test_pending_graph_snapshot_resolves_once_inside_the_same_progression(
    isolated_service,
):
    manifests = isolated_service
    pending_version = VERSION.model_copy(
        update={"graph_snapshot_id": "unavailable:pending_discovery"}
    )
    started = progression_service.start_build_progression(
        operation_id="op:start:pending-graph",
        base_class="Monk",
        target_level=80,
        goal="Resolve the graph snapshot from the trusted target artifact.",
        version_context=pending_version.model_dump(mode="json", by_alias=True),
    )

    anchored = _bind_target_anchor(
        started,
        manifests,
        operation_suffix="pending-graph",
        manifest_graph_snapshot_id="graph:resolved-target",
    )

    assert anchored["status"] == "target_anchor_bound"
    assert anchored["progressionId"] == started["progressionId"]
    assert anchored["graphSnapshotResolution"]["originalGraphSnapshotId"] == (
        "unavailable:pending_discovery"
    )
    assert anchored["graphSnapshotResolution"]["resolvedGraphSnapshotId"] == (
        "graph:resolved-target"
    )
    full = progression_service.get_build_progression_status(
        started["progressionId"],
        detail="full",
    )["buildProgression"]
    assert full["request"]["versionContext"]["graphSnapshotId"] == "graph:resolved-target"
    assert (
        full["targetSelection"]["selectionPacket"]["versionContext"]["graphSnapshotId"]
        == "graph:resolved-target"
    )
    assert (
        full["targetAnchor"]["targetAnchorCreatePacket"]["versionContext"]["graphSnapshotId"]
        == "graph:resolved-target"
    )
    assert full["graphSnapshotResolution"]["sourceArtifactId"] == anchored["targetArtifactId"]


def test_target_anchor_accepts_graph_proven_skill_display_alias_for_same_stable_key(
    isolated_service,
    monkeypatch,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:target-skill-alias",
        base_class="Monk",
        target_level=80,
        goal="Bind a PoB display alias without changing the selected target Family.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )

    def resolve_alias(display_name: str, *, node_type: str, scope: str, graph_snapshot_id: str):
        assert node_type == "active_skill"
        assert scope == "player"
        assert graph_snapshot_id == "graph:test"
        if display_name != "Rend":
            return None
        return {
            "stableKey": "skill:target-attack",
            "sourceRefs": ["source:fixture-graph"],
        }

    monkeypatch.setattr(
        progression_service,
        "_resolve_graph_component_name",
        resolve_alias,
    )
    anchored = _bind_target_anchor(
        started,
        manifests,
        operation_suffix="target-skill-alias",
        selected_primary_skill_name="Wyvern Rend",
        artifact_primary_skill_name="Rend",
    )

    assert anchored["status"] == "target_anchor_bound"
    assert anchored["targetIdentity"]["primarySkillKey"] == "skill:target-attack"
    assert anchored["targetIdentity"]["primarySkillName"] == "Rend"
    assert anchored["identityAliasResolution"] == [
        {
            "componentRole": "primary_skill",
            "componentKey": "skill:target-attack",
            "proofMode": "artifact_name_to_selected_stable_key",
            "artifactDisplayName": "Rend",
            "expectedDisplayName": "Wyvern Rend",
            "expectedIdentitySource": "selected_candidate",
            "graphSnapshotId": "graph:test",
            "sourceRefs": ["source:fixture-graph"],
        }
    ]
    full = progression_service.get_build_progression_status(
        started["progressionId"],
        detail="full",
    )["buildProgression"]
    assert full["targetAnchor"]["identity"]["primarySkillName"] == "Rend"
    assert full["targetAnchor"]["identityAliasResolution"] == (anchored["identityAliasResolution"])


def test_target_anchor_rejects_unproven_skill_display_alias_even_when_key_is_claimed(
    isolated_service,
    monkeypatch,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:target-skill-alias-rejected",
        base_class="Monk",
        target_level=80,
        goal="Reject a display name that cannot be proven to be the selected skill.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )

    def resolve_alias(display_name: str, *, node_type: str, scope: str, graph_snapshot_id: str):
        del node_type, scope, graph_snapshot_id
        stable_key = {
            "Wyvern Rend": "skill:target-attack",
            "Unrelated Attack": "skill:unrelated-attack",
        }.get(display_name)
        if stable_key is None:
            return None
        return {"stableKey": stable_key, "sourceRefs": ["source:fixture-graph"]}

    monkeypatch.setattr(
        progression_service,
        "_resolve_graph_component_name",
        resolve_alias,
    )
    rejected = _bind_target_anchor(
        started,
        manifests,
        operation_suffix="target-skill-alias-rejected",
        selected_primary_skill_name="Wyvern Rend",
        artifact_primary_skill_name="Unrelated Attack",
    )

    assert rejected["errorCode"] == "progression_target_anchor_selection_mismatch"
    full = progression_service.get_build_progression_status(
        started["progressionId"],
        detail="full",
    )["buildProgression"]
    assert full["currentState"] == "anchor_running"
    assert full["targetAnchor"].get("artifactId") is None


def test_concrete_graph_snapshot_cannot_drift_during_target_binding(isolated_service):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:concrete-graph",
        base_class="Monk",
        target_level=80,
        goal="Keep an already concrete graph snapshot immutable.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )

    rejected = _bind_target_anchor(
        started,
        manifests,
        operation_suffix="concrete-graph",
        manifest_graph_snapshot_id="graph:different",
    )

    assert rejected["errorCode"] == "progression_version_context_mismatch"
    status = progression_service.get_build_progression_status(
        started["progressionId"],
        detail="full",
    )["buildProgression"]
    assert status["request"]["versionContext"]["graphSnapshotId"] == "graph:test"
    assert status["graphSnapshotResolution"] is None


def test_progression_target_selection_rejects_one_candidate_and_wrong_anchor_identity(
    isolated_service,
):
    started = progression_service.start_build_progression(
        operation_id="op:start:target-selection-invalid",
        base_class="Monk",
        target_level=80,
        goal="Fail closed when target comparison or binding does not match.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    one = _target_selection()
    one["candidates"] = one["candidates"][:1]
    invalid = progression_service.submit_build_progression_target_selection(
        progression_id=started["progressionId"],
        selection=one,
        expected_revision=started["revision"],
        operation_id="op:target-selection:one",
    )
    assert invalid["errorCode"] == "invalid_progression_target_selection"

    selected = _select_target_candidates(started, operation_suffix="identity-mismatch")
    expanded_identity = deepcopy(_target_selection()["candidates"][0]["identity"])
    expanded_identity["secondarySkillKeys"] = ["skill:unselected-secondary"]
    expanded_identity["secondarySkillNames"] = ["Unselected Secondary"]
    expanded = progression_service.bind_build_progression_target_anchor(
        progression_id=started["progressionId"],
        artifact_id="final-build:not-yet-created",
        target_identity=expanded_identity,
        design_coverage=_target_coverage(),
        lifecycle_verification_ref="lifecycle-verification:0000000000000000",
        expected_revision=selected["revision"],
        operation_id="op:anchor:unselected-secondary",
    )
    assert expanded["errorCode"] == "progression_target_anchor_selection_mismatch"

    mismatch = progression_service.bind_build_progression_target_anchor(
        progression_id=started["progressionId"],
        artifact_id="final-build:not-yet-created",
        target_identity=_target_selection()["candidates"][1]["identity"],
        design_coverage=_target_coverage(),
        lifecycle_verification_ref="lifecycle-verification:0000000000000000",
        expected_revision=selected["revision"],
        operation_id="op:anchor:selection-mismatch",
    )
    assert mismatch["errorCode"] == "progression_target_anchor_selection_mismatch"


def test_progression_target_selection_rejects_a_shrunk_discovery_receipt(
    isolated_service,
    monkeypatch,
):
    started = progression_service.start_build_progression(
        operation_id="op:start:target-selection-shrunk-receipt",
        base_class="Monk",
        target_level=80,
        goal="Reject a receipt that did not request the complete ten-Family discovery window.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    trusted_reader = progression_service._research_receipt_reader()

    def read_with_shrunk_limit(ref: str):
        receipt = trusted_reader(ref)
        if ref == "dq-aaaaaaaaaaaaaaaa":
            receipt = deepcopy(receipt)
            receipt["request"]["limit"] = 5
        return receipt

    monkeypatch.setattr(
        progression_service,
        "_research_receipt_reader",
        lambda: read_with_shrunk_limit,
    )
    rejected = progression_service.submit_build_progression_target_selection(
        progression_id=started["progressionId"],
        selection=_target_selection(),
        expected_revision=started["revision"],
        operation_id="op:target-selection:shrunk-receipt",
    )

    assert rejected["errorCode"] == "progression_target_discovery_limit_mismatch"


def test_target_selection_allows_two_material_variants_inside_a_user_locked_family():
    selection = _target_selection()
    candidates = selection["candidates"]
    candidates[1]["identity"] = deepcopy(candidates[0]["identity"])

    parsed = progression_models.TargetCandidateSelection.model_validate(selection)

    assert (
        parsed.candidates[0].identity.primary_skill_key
        == parsed.candidates[1].identity.primary_skill_key
    )
    duplicate = deepcopy(selection)
    duplicate["candidates"][1]["mechanismSummary"] = duplicate["candidates"][0]["mechanismSummary"]
    with pytest.raises(ValueError, match="materially distinct"):
        progression_models.TargetCandidateSelection.model_validate(duplicate)


def test_target_selection_rejects_a_modelability_only_winner():
    selection = _target_selection()
    for comparison in selection["dimensionComparisons"]:
        comparison["preferredCandidateId"] = (
            "target-candidate:high-ceiling"
            if comparison["dimension"] == "modelability"
            else "target-candidate:alternate"
        )

    with pytest.raises(ValueError, match="modelability alone"):
        progression_models.TargetCandidateSelection.model_validate(selection)


def test_family_discovery_with_fewer_than_two_exact_families_pauses(
    isolated_service,
):
    started = progression_service.start_build_progression(
        operation_id="op:start:insufficient-family-research",
        base_class="Monk",
        target_level=80,
        goal="Pause when exact-version Research cannot support a comparison.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )

    result = progression_service.submit_build_progression_target_selection(
        progression_id=started["progressionId"],
        selection={"familyDiscoveryRef": "dq-cccccccccccccccc"},
        expected_revision=started["revision"],
        operation_id="op:target-selection:insufficient-family-research",
    )

    assert result["status"] == "target_family_discovery_insufficient"
    assert result["discoveredFamilyCount"] == 1
    assert result["currentState"] == "paused"
    status = progression_service.get_build_progression_status(started["progressionId"])
    assert status["buildProgression"]["currentState"] == "paused"
    assert status["buildProgression"]["targetAnchor"]["status"] == "anchor_paused"

    resumed = progression_service.resume_build_progression(
        progression_id=started["progressionId"],
        expected_revision=result["revision"],
        operation_id="op:resume:insufficient-family-research",
    )
    assert resumed["currentState"] == "selection_pending"
    resumed_status = progression_service.get_build_progression_status(started["progressionId"])
    assert resumed_status["buildProgression"]["targetAnchor"]["status"] == "selection_pending"


def test_target_anchor_allows_one_explicit_reserve_switch_and_no_second_switch(
    isolated_service,
):
    started = progression_service.start_build_progression(
        operation_id="op:start:reserve-switch",
        base_class="Monk",
        target_level=80,
        goal="Switch only after the Agent records a supported target failure.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    selected = _select_target_candidates(started, operation_suffix="reserve-switch")
    failed = progression_service.fail_build_progression_target_anchor(
        progression_id=started["progressionId"],
        failure_code="quality_unacceptable",
        expected_revision=selected["revision"],
        operation_id="op:target-fail:reserve-switch",
    )
    assert failed["reserveFamilyReselectionAvailable"] is True
    assert failed["sameFamilyRetryAvailable"] is False

    switched = progression_service.reselect_build_progression_target_candidate(
        progression_id=started["progressionId"],
        decision_summary=(
            "The selected Family remained below the requested target after its bounded quality pass."
        ),
        evidence_refs=["judge:target-attempt-1"],
        expected_revision=failed["revision"],
        operation_id="op:target-reselect:reserve-switch",
    )
    assert switched["selectedBuildFamilyKey"] == "family:target-alternate"
    assert switched["fallbackUsed"] is True
    assert switched["judgeTriggeredAutomatically"] is False

    failed_again = progression_service.fail_build_progression_target_anchor(
        progression_id=started["progressionId"],
        failure_code="quality_unacceptable",
        expected_revision=switched["revision"],
        operation_id="op:target-fail:reserve-switch-again",
    )
    rejected = progression_service.reselect_build_progression_target_candidate(
        progression_id=started["progressionId"],
        decision_summary="Try another Family.",
        evidence_refs=["judge:target-attempt-2"],
        expected_revision=failed_again["revision"],
        operation_id="op:target-reselect:reserve-switch-again",
    )
    assert failed_again["reserveFamilyReselectionAvailable"] is False
    assert rejected["errorCode"] == "progression_target_reselection_not_available"


def test_target_anchor_same_family_external_retry_is_limited_but_reserve_has_its_own_budget(
    isolated_service,
):
    started = progression_service.start_build_progression(
        operation_id="op:start:target-retry",
        base_class="Monk",
        target_level=80,
        goal="Reserve external retry for control interruptions only.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    selected = _select_target_candidates(started, operation_suffix="target-retry")
    interrupted = progression_service.fail_build_progression_target_anchor(
        progression_id=started["progressionId"],
        failure_code="tool_interruption",
        expected_revision=selected["revision"],
        operation_id="op:target-fail:tool-interruption",
    )
    retried = progression_service.retry_build_progression_target_anchor(
        progression_id=started["progressionId"],
        expected_revision=interrupted["revision"],
        operation_id="op:target-retry:first",
    )
    interrupted_again = progression_service.fail_build_progression_target_anchor(
        progression_id=started["progressionId"],
        failure_code="tool_interruption",
        expected_revision=retried["revision"],
        operation_id="op:target-fail:tool-interruption-again",
    )
    retry_rejected = progression_service.retry_build_progression_target_anchor(
        progression_id=started["progressionId"],
        expected_revision=interrupted_again["revision"],
        operation_id="op:target-retry:second",
    )
    assert retried["externalRetryCount"] == 1
    assert retry_rejected["errorCode"] == "progression_target_anchor_retry_limit_reached"


def test_target_control_interruption_rebinds_a_new_run_on_the_same_progression(
    isolated_service,
):
    started = progression_service.start_build_progression(
        operation_id="op:start:target-control-retry",
        base_class="Monk",
        target_level=80,
        goal="Keep the same progression while retrying one interrupted target run.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    selected = _select_target_candidates(
        started,
        operation_suffix="target-control-retry",
    )
    first_run = "91000000-0000-0000-0000-000000000001"
    first_bound = progression_service.bind_build_progression_target_run(
        progression_id=started["progressionId"],
        run_id=first_run,
        expected_revision=selected["revision"],
        operation_id="op:target-run:control-first",
    )
    interrupted = progression_service.fail_build_progression_target_anchor(
        progression_id=started["progressionId"],
        failure_code="control_interruption",
        expected_revision=first_bound["revision"],
        operation_id="op:target-fail:control",
    )
    retried = progression_service.retry_build_progression_target_anchor(
        progression_id=started["progressionId"],
        expected_revision=interrupted["revision"],
        operation_id="op:target-retry:control",
    )
    second_run = "91000000-0000-0000-0000-000000000002"
    second_bound = progression_service.bind_build_progression_target_run(
        progression_id=started["progressionId"],
        run_id=second_run,
        expected_revision=retried["revision"],
        operation_id="op:target-run:control-second",
    )

    assert second_bound["status"] == "target_run_bound"
    assert second_bound["progressionId"] == started["progressionId"]
    full = progression_service.get_build_progression_status(
        started["progressionId"],
        detail="full",
    )["buildProgression"]
    assert full["targetAnchor"]["currentRunId"] == second_run
    assert full["targetAnchor"]["externalRetryCount"] == 1
    assert [row["runId"] for row in full["targetAnchor"]["runHistory"]] == [
        first_run,
        second_run,
    ]
    assert full["targetAnchor"]["runHistory"][0]["status"] == "failed"
    assert full["targetAnchor"]["runHistory"][1]["status"] == "running"


def test_user_locked_target_skips_discovery_and_cannot_switch_family(isolated_service):
    started = progression_service.start_build_progression(
        operation_id="op:start:user-locked-family",
        base_class="Monk",
        target_level=80,
        goal="Keep the user-selected Family.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
        target_family_constraint={
            "ascendancyKey": "ascendancy:target-monk",
            "primarySkillKey": "skill:target-attack",
            "buildFamilyKey": "family:target-high",
            "lockedIdentity": {
                "ascendancyKey": "ascendancy:target-monk",
                "primarySkillKey": "skill:target-attack",
                "secondarySkillKeys": [],
                "ascendancyName": "High Ceiling Ascendancy",
                "primarySkillName": "Target Attack",
                "secondarySkillNames": [],
            },
        },
    )

    assert started["currentState"] == "anchor_running"
    assert started["targetCandidateSelectionPacket"] is None
    assert started["targetFamilyDiscoveryRequest"] is None
    failed = progression_service.fail_build_progression_target_anchor(
        progression_id=started["progressionId"],
        failure_code="quality_unacceptable",
        expected_revision=started["revision"],
        operation_id="op:target-fail:user-locked-family",
    )
    rejected = progression_service.reselect_build_progression_target_candidate(
        progression_id=started["progressionId"],
        decision_summary="Attempt to switch a locked target.",
        evidence_refs=["judge:target-attempt-1"],
        expected_revision=failed["revision"],
        operation_id="op:target-reselect:user-locked-family",
    )
    assert failed["userLocked"] is True
    assert failed["reserveFamilyReselectionAvailable"] is False
    assert rejected["errorCode"] == "progression_target_reselection_not_available"


def test_partial_target_constraint_becomes_a_hard_family_discovery_filter(
    isolated_service,
):
    started = progression_service.start_build_progression(
        operation_id="op:start:partial-family-filter",
        base_class="Monk",
        target_level=80,
        goal="Discover only Families matching the requested ascendancy.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
        target_family_constraint={
            "ascendancyKey": "ascendancy:target-monk",
        },
    )

    assert started["currentState"] == "selection_pending"
    assert started["targetCandidateSelectionPacket"]["familyFilters"] == {
        "ascendancyKey": "ascendancy:target-monk"
    }
    assert started["targetFamilyDiscoveryRequest"]["ascendancyKey"] == ("ascendancy:target-monk")


def test_target_anchor_must_preserve_a_core_secondary_declared_by_selected_candidate(
    isolated_service,
    monkeypatch,
):
    started = progression_service.start_build_progression(
        operation_id="op:start:selected-secondary",
        base_class="Monk",
        target_level=80,
        goal="Lock an explicitly compared secondary mechanism.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    selection = _target_selection()
    selection["candidates"][0]["identity"]["secondarySkillKeys"] = ["skill:target-secondary"]
    selection["candidates"][0]["identity"]["secondarySkillNames"] = ["Target Secondary"]
    trusted_reader = progression_service._research_receipt_reader()

    def read_with_secondary(ref: str):
        receipt = trusted_reader(ref)
        if ref == "dq-aaaaaaaaaaaaaaaa":
            receipt = deepcopy(receipt)
            receipt["result"]["buildFamilies"][0]["secondarySkillKeys"] = ["skill:target-secondary"]
        return receipt

    monkeypatch.setattr(
        progression_service,
        "_research_receipt_reader",
        lambda: read_with_secondary,
    )
    selected = progression_service.submit_build_progression_target_selection(
        progression_id=started["progressionId"],
        selection=selection,
        expected_revision=started["revision"],
        operation_id="op:target-selection:selected-secondary",
    )

    mismatch = progression_service.bind_build_progression_target_anchor(
        progression_id=started["progressionId"],
        artifact_id="final-build:not-yet-created",
        target_identity=_target_selection()["candidates"][0]["identity"],
        design_coverage=_target_coverage(),
        lifecycle_verification_ref="lifecycle-verification:0000000000000000",
        expected_revision=selected["revision"],
        operation_id="op:anchor:selected-secondary-mismatch",
    )

    assert mismatch["errorCode"] == "progression_target_anchor_selection_mismatch"


def test_progression_stage_optimization_policy_requires_complete_loadouts_at_every_level():
    blueprint = _blueprint("starter-research:packet-123")
    early = progression_models.StageBlueprint.model_validate(blueprint["stages"][0])
    later = progression_models.StageBlueprint.model_validate(blueprint["stages"][1])
    endgame = progression_models.StageBlueprint.model_validate(blueprint["stages"][-1])

    early_policy = progression_models.stage_optimization_policy(early)
    later_policy = progression_models.stage_optimization_policy(later)
    endgame_policy = progression_models.stage_optimization_policy(endgame)

    assert early_policy.mode == "stage_targeted"
    assert early_policy.required_objectives == later_policy.required_objectives
    assert early_policy.loadout_scope == "stage_complete_loadout"
    assert early_policy.outside_mask_findings == "report_only_no_retry"
    assert early_policy.advisory_objectives == []
    assert "global_passive_tree_optimization" in early_policy.excluded_objectives
    assert "full_gear_optimization" not in early_policy.excluded_objectives
    assert early_policy.quality_goal == "complete_stage_build"
    assert early_policy.mutation_strategy == ("single_initialization_then_function_scoped_deltas")
    assert early_policy.design_change_policy == ("blueprint_declared_or_versioned_replan_only")
    assert later_policy.mode == "stage_targeted"
    assert later_policy.loadout_scope == "stage_complete_loadout"
    assert "damage_delivery" in later_policy.required_objectives
    assert later_policy.global_optimizer_allowed is False
    assert early_policy.judge_elemental_resistance_policy == "diagnostic_only"
    assert "elemental_resistance_judgment" in early_policy.excluded_objectives
    assert endgame_policy.judge_elemental_resistance_policy == "endgame_minimums_60_30"
    assert "elemental_resistance_judgment" not in endgame_policy.excluded_objectives


def test_target_anchor_optimization_policy_uses_endgame_resistance_gate_at_level_80():
    campaign_policy = progression_models.target_anchor_optimization_policy(79)
    endgame_policy = progression_models.target_anchor_optimization_policy(80)

    assert campaign_policy.judge_elemental_resistance_policy == "diagnostic_only"
    assert "elemental_resistance_judgment" in campaign_policy.excluded_objectives
    assert endgame_policy.judge_elemental_resistance_policy == "endgame_minimums_60_30"
    assert "elemental_resistance_judgment" not in endgame_policy.excluded_objectives


def test_legacy_campaign_early_optimization_policy_remains_loadable():
    blueprint = _blueprint("starter-research:packet-123")
    early = progression_models.StageBlueprint.model_validate(blueprint["stages"][0])
    legacy_policy = progression_models.StageOptimizationPolicy(
        mode="early_minimal",
        loadout_scope="minimal_mechanism_shell",
        required_objectives=[
            "skill_availability",
            "weapon_compatibility",
            "resource_sustain",
        ],
        excluded_objectives=[
            "elemental_resistance_judgment",
            "global_whole_build_optimization",
            "global_passive_tree_optimization",
            "offense_quality_chasing",
            "defense_quality_chasing",
            "full_gear_optimization",
        ],
    )

    packet = progression_models.StageCreatePacket(
        progression_id="00000000-0000-0000-0000-000000000001",
        blueprint_id=blueprint["blueprintId"],
        base_class=blueprint["baseClass"],
        target_level=early.target_level,
        route_target_level=blueprint["targetLevel"],
        target_intent=blueprint["targetIntent"],
        stage=early,
        previous_artifact_id=None,
        starter_research_packet_id=blueprint["starterResearchPacketId"],
        starter_evidence_use=blueprint["starterEvidenceUse"],
        optimization_policy=legacy_policy,
        version_context=VERSION,
        no_raw_material=True,
        progression_bound=True,
    )

    assert packet.optimization_policy is not None
    assert packet.optimization_policy.mode == "early_minimal"
    assert packet.optimization_policy.quality_goal == "legacy_early_policy"


def test_new_blueprint_rebuild_requires_a_reason_and_first_stage_never_rebuilds():
    blueprint_payload = _blueprint("starter-research:packet-123")
    parsed = progression_models.ProgressionBlueprint.model_validate(blueprint_payload)
    assert progression_service._blueprint_execution_contract_error(parsed) is None

    missing_reason = deepcopy(blueprint_payload)
    missing_reason["stages"][2]["rebuildReason"] = None
    parsed_missing = progression_models.ProgressionBlueprint.model_validate(missing_reason)
    assert progression_service._blueprint_execution_contract_error(parsed_missing) == (
        "progression_stage_rebuild_reason_required"
    )

    first_stage_rebuild = deepcopy(blueprint_payload)
    first_stage_rebuild["stages"][0]["rebuildFromScratch"] = True
    first_stage_rebuild["stages"][0]["rebuildReason"] = (
        "The first stage already initializes a new build and cannot request another rebuild."
    )
    parsed_first = progression_models.ProgressionBlueprint.model_validate(first_stage_rebuild)
    assert progression_service._blueprint_execution_contract_error(parsed_first) == (
        "progression_first_stage_rebuild_forbidden"
    )

    stray_reason = deepcopy(blueprint_payload)
    stray_reason["stages"][1]["rebuildReason"] = (
        "This reason is invalid because the stage is configured to inherit its predecessor."
    )
    parsed_stray = progression_models.ProgressionBlueprint.model_validate(stray_reason)
    assert progression_service._blueprint_execution_contract_error(parsed_stray) == (
        "progression_stage_rebuild_reason_without_rebuild"
    )


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


def test_progression_common_starter_does_not_require_a_mature_family_receipt(
    isolated_service,
    monkeypatch,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:common-starter",
        base_class="Monk",
        target_level=80,
        goal="Use public campaign knowledge before the mature Family transition.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    anchored = _bind_target_anchor(started, manifests, operation_suffix="common-starter")
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=anchored["revision"],
        operation_id="op:research:common-starter",
        packet=_research(),
    )
    blueprint = _use_common_unascended_starter(
        _blueprint(
            research["packetId"],
            target_anchor_artifact_id=anchored["targetArtifactId"],
        ),
        research["packetId"],
    )
    accepted = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:common-starter",
        blueprint=blueprint,
    )
    assert accepted["status"] == "blueprint_accepted"

    claimed = progression_service.claim_build_progression_stage(
        progression_id=started["progressionId"],
        expected_revision=accepted["revision"],
        operation_id="op:claim:common-starter",
    )
    packet = claimed["stageCreatePacket"]
    assert packet["stage"]["knowledgeMode"] == "starter_common"
    assert packet["stage"]["familyIdentity"] is None
    assert packet["generationMemoryMode"] == "standard"
    assert packet["researchMemoryPolicy"] == "starter_common_no_family_memory"
    assert packet["versionContext"]["researchMemoryRef"] == research["packetId"]
    assert packet["optimizationPolicy"]["mode"] == "stage_targeted"
    assert packet["optimizationPolicy"]["loadoutScope"] == "stage_complete_loadout"
    assert packet["optimizationPolicy"]["qualityGoal"] == "complete_stage_build"
    assert packet["optimizationPolicy"]["mutationStrategy"] == (
        "single_initialization_then_function_scoped_deltas"
    )
    assert packet["optimizationPolicy"]["designChangePolicy"] == (
        "blueprint_declared_or_versioned_replan_only"
    )
    assert packet["optimizationPolicy"]["outsideMaskFindings"] == "report_only_no_retry"
    assert packet["globalOptimizerAllowed"] is False

    run_id = "12000000-0000-0000-0000-000000000001"
    bound = progression_service.bind_build_progression_stage_run(
        progression_id=started["progressionId"],
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        run_id=run_id,
        expected_revision=claimed["revision"],
        operation_id="op:bind:common-starter",
    )
    artifact_id = "final-build:common-unascended-starter"
    source_hash = "common-unascended-starter-hash"
    manifests[artifact_id] = _manifest(
        artifact_id,
        run_id,
        10,
        source_hash,
        research_ref=research["packetId"],
        ascendancy="None",
        main_skill="Early Attack",
    )
    monkeypatch.setattr(
        progression_service,
        "_read_phase5_provenance",
        lambda _run_id: {
            "runId": run_id,
            "candidateId": f"candidate:{artifact_id}",
            "sourceHash": source_hash,
            "researchMemoryUse": None,
            "finalFailureAudit": {
                "classification": "no_material_failure",
                "retryDecision": "accept",
            },
        },
    )
    completed = progression_service.complete_build_progression_stage(
        progression_id=started["progressionId"],
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id=artifact_id,
        lifecycle_verification=_lifecycle_result(
            artifact_id,
            "campaign_early",
            source_hash,
        ),
        cost_profile=_cost(claimed["stageId"]),
        completion_report={
            "purpose": "Verify the unascended public-knowledge starter.",
            "playPattern": "Use the early attack while remaining unascended.",
            "changesFromPrevious": [],
            "sourceRefs": [research["packetId"]],
        },
        expected_revision=bound["revision"],
        operation_id="op:complete:common-starter",
    )
    assert completed["status"] == "stage_completed"
    status = progression_service.get_build_progression_status(
        started["progressionId"],
        detail="full",
    )
    provenance = status["buildProgression"]["stages"][0]["researchProvenance"]
    assert provenance["knowledgeMode"] == "starter_common"
    assert provenance["dedupeQueryRefs"] == []


def test_wrong_stage_memory_mode_is_rejected_without_consuming_the_claim_or_retry(
    isolated_service,
    monkeypatch,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:stage-memory-mode",
        base_class="Monk",
        target_level=80,
        goal="Keep the starter stage on the packet-selected standard memory mode.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    anchored = _bind_target_anchor(
        started,
        manifests,
        operation_suffix="stage-memory-mode",
    )
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=anchored["revision"],
        operation_id="op:research:stage-memory-mode",
        packet=_research(),
    )
    blueprint = _use_common_unascended_starter(
        _blueprint(
            research["packetId"],
            target_anchor_artifact_id=anchored["targetArtifactId"],
        ),
        research["packetId"],
    )
    accepted = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:stage-memory-mode",
        blueprint=blueprint,
    )
    claimed = progression_service.claim_build_progression_stage(
        progression_id=started["progressionId"],
        expected_revision=accepted["revision"],
        operation_id="op:claim:stage-memory-mode",
    )
    assert claimed["stageCreatePacket"]["generationMemoryMode"] == "standard"

    wrong_run_id = "12000000-0000-0000-0000-000000000002"
    rejected = progression_service.bind_build_progression_stage_run(
        progression_id=started["progressionId"],
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        run_id=wrong_run_id,
        expected_revision=claimed["revision"],
        operation_id="op:bind:stage-memory-mode-wrong",
    )
    assert rejected["errorCode"] == "progression_stage_memory_mode_mismatch"
    assert rejected["expectedMemoryMode"] == "standard"
    assert rejected["actualMemoryMode"] == "memory_assisted"
    assert rejected["stageRetryConsumed"] is False
    assert rejected["claimRemainsActive"] is True
    assert rejected["revision"] == claimed["revision"]

    after_rejection = progression_service.get_build_progression_status(
        started["progressionId"],
        detail="full",
    )["buildProgression"]
    stage = after_rejection["stages"][0]
    assert stage["retryCount"] == 0
    assert stage["boundRunId"] is None
    assert after_rejection["activeStage"]["claimId"] == claimed["claimId"]

    correct_run_id = "12000000-0000-0000-0000-000000000001"
    bound = progression_service.bind_build_progression_stage_run(
        progression_id=started["progressionId"],
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        run_id=correct_run_id,
        expected_revision=claimed["revision"],
        operation_id="op:bind:stage-memory-mode-correct",
    )
    assert bound["status"] == "run_bound"
    assert bound["runId"] == correct_run_id
    monkeypatch.setattr(
        progression_service,
        "_phase5_run_manifest",
        lambda _run_id, *, not_before, require_fresh=True: {
            "startedAt": not_before,
            "experimentContext": {"memoryMode": "memory_assisted"},
        },
    )
    tampered = progression_service.complete_build_progression_stage(
        progression_id=started["progressionId"],
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        artifact_id="final-build:not-read-because-mode-mismatch",
        lifecycle_verification={},
        cost_profile={},
        completion_report={},
        expected_revision=bound["revision"],
        operation_id="op:complete:stage-memory-mode-tampered",
    )
    assert tampered["errorCode"] == "progression_stage_memory_mode_mismatch"
    assert tampered["expectedMemoryMode"] == "standard"
    assert tampered["actualMemoryMode"] == "memory_assisted"
    assert tampered["stageRetryConsumed"] is False
    assert tampered["revision"] == bound["revision"]


def test_failed_unsaved_starter_stage_can_replan_once_with_fresh_public_evidence(
    isolated_service,
):
    manifests = isolated_service
    started = progression_service.start_build_progression(
        operation_id="op:start:starter-replan",
        base_class="Monk",
        target_level=80,
        goal="Allow one audited starter direction change after a failed viability attempt.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    anchored = _bind_target_anchor(started, manifests, operation_suffix="starter-replan")
    research = progression_service.intake_starter_research_packet(
        progression_id=started["progressionId"],
        expected_revision=anchored["revision"],
        operation_id="op:research:starter-replan",
        packet=_research(),
    )
    blueprint = _use_common_unascended_starter(
        _blueprint(
            research["packetId"],
            target_anchor_artifact_id=anchored["targetArtifactId"],
        ),
        research["packetId"],
    )
    accepted = progression_service.submit_build_progression_blueprint(
        progression_id=started["progressionId"],
        expected_revision=research["revision"],
        operation_id="op:blueprint:starter-replan",
        blueprint=blueprint,
    )
    claimed = progression_service.claim_build_progression_stage(
        progression_id=started["progressionId"],
        expected_revision=accepted["revision"],
        operation_id="op:claim:starter-replan",
    )
    failed = progression_service.fail_build_progression_stage(
        progression_id=started["progressionId"],
        stage_id=claimed["stageId"],
        claim_id=claimed["claimId"],
        failure_code="starter_loop_not_viable",
        expected_revision=claimed["revision"],
        operation_id="op:fail:starter-replan",
    )
    revised_stage = deepcopy(blueprint["stages"][0])
    revised_stage["starterIdentity"] = {
        "primarySkillKey": "skill:replacement-attack",
        "secondarySkillKeys": [],
        "primarySkillName": "Replacement Attack",
        "secondarySkillNames": [],
        "expectedAscendancyKey": None,
        "expectedAscendancyName": None,
    }
    revised_stage["primarySkillIntent"] = "Replacement Attack"
    revised_stage["commonKnowledgeRefs"] = [
        research["packetId"],
        "skill:replacement-attack",
        "corpus:replacement-attack",
    ]
    retried = progression_service.retry_build_progression_stage(
        progression_id=started["progressionId"],
        stage_id=claimed["stageId"],
        expected_revision=failed["revision"],
        operation_id="op:retry:starter-replan",
        revised_stage=revised_stage,
        revised_blueprint_id="progression-blueprint:starter-replan-v2",
        replan_summary="The first skill loop failed; use the independently checked replacement.",
    )
    assert retried["status"] == "stage_retry_opened"
    assert retried["replanned"] is True

    reclaimed = progression_service.claim_build_progression_stage(
        progression_id=started["progressionId"],
        expected_revision=retried["revision"],
        operation_id="op:claim:starter-replan-v2",
    )
    assert (
        reclaimed["stageCreatePacket"]["stage"]["starterIdentity"]["primarySkillKey"]
        == "skill:replacement-attack"
    )
    status = progression_service.get_build_progression_status(
        started["progressionId"],
        detail="full",
    )
    history = status["buildProgression"]["stages"][0]["replanHistory"]
    assert history[0]["failureCode"] == "starter_loop_not_viable"


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
    graph_snapshot_id: str | None = None,
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
        version_context=VERSION.model_copy(
            update={
                "research_memory_ref": research_ref,
                **(
                    {"graph_snapshot_id": graph_snapshot_id}
                    if graph_snapshot_id is not None
                    else {}
                ),
            }
        ),
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
    assert reused["currentState"] == "selection_pending"
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
    assert stale["currentState"] == "selection_pending"
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
    caveated_payload = deepcopy(cloned_payload)
    caveated_payload["targetDesignCoverage"]["unresolvedCaveats"] = [
        "The target boss resource loop remains only partially verified."
    ]
    caveated = progression_service.progression.save_anchored_progression_route(
        caveated_payload,
        route_id="00000000-0000-0000-0000-000000000098",
    )
    assert caveated["status"] == "saved"
    assert caveated["progressionRoute"]["qualityStatus"] == "limited"

    target_manifest = manifests[blueprint["targetAnchorArtifactId"]]
    target_manifest.judge_report.playability_failures = ["resource_loop_not_sustainable"]
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
    assert failed["recoveryExportAvailable"] is True
    assert failed["recoveryExportAction"] == "export_build_progression_package"
    assert failed["nextAction"] == "retry_stage_or_export_recovery"
    failed_status = progression_service.get_build_progression_status(
        progression_id,
        detail="compact",
    )
    assert failed_status["buildProgression"]["nextAction"] == ("retry_stage_or_export_recovery")
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
    selected = _select_target_candidates(
        started,
        operation_suffix="failed-lifecycle-anchor",
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
        expected_revision=selected["revision"],
        operation_id="op:anchor:failed-lifecycle",
    )

    assert result["errorCode"] == "progression_target_anchor_lifecycle_not_verified"
    status = progression_service.get_build_progression_status(started["progressionId"])
    assert status["buildProgression"]["currentState"] == "anchor_running"


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
    selected = _select_target_candidates(started, operation_suffix="bad-anchor")
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
    run_bound = progression_service.bind_build_progression_target_run(
        progression_id=started["progressionId"],
        run_id=run_id,
        expected_revision=selected["revision"],
        operation_id="op:anchor-run:bad-anchor",
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
        expected_revision=run_bound["revision"],
        operation_id="op:anchor:bad-anchor",
    )

    assert result["errorCode"] == "progression_target_anchor_agent_rejected"
    status = progression_service.get_build_progression_status(started["progressionId"])
    assert status["buildProgression"]["currentState"] == "anchor_running"


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

    assert result["errorCode"] == "progression_phase5_run_not_found"
    status = progression_service.get_build_progression_status(started["progressionId"])
    assert status["buildProgression"]["currentState"] == "anchor_running"


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


def test_caveated_research_premise_requires_limited_target_acceptance(
    isolated_service,
    monkeypatch,
):
    manifests = isolated_service
    premise_id = "rp-0123456789abcdef"
    provenance = {
        "dedupeQueryRefs": ["dq-0000000000000004"],
        "exactIdentityQueryRefs": ["dq-0000000000000004"],
        "buildFamilyKeys": ["family:target-high"],
        "deepRecordIds": ["drr-target-resource-alternative"],
        "patternIds": [],
        "semanticEdgeIds": [],
        "memoryItemIds": [],
        "premiseDecisionIds": [premise_id],
        "caveatedPremiseIds": [premise_id],
        "premiseDecisions": [
            {
                "premiseId": premise_id,
                "decision": "caveated",
                "resolutionRefs": [],
                "application": "Keep the unresolved target resource risk visible.",
                "caveat": "The longest boss scenario remains only partially verified.",
            }
        ],
        "retrievalOutcome": "matched",
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }
    monkeypatch.setattr(
        progression_service.progression_provenance,
        "validate_research_provenance",
        lambda **_kwargs: (None, deepcopy(provenance)),
    )
    coverage = _target_coverage()
    coverage["dimensions"][0] = {
        **coverage["dimensions"][0],
        "status": "research_adopted",
        "evidenceRefs": [premise_id],
    }
    coverage["unresolvedCaveats"] = [
        "The longest boss resource loop remains only partially verified."
    ]

    strict_started = progression_service.start_build_progression(
        operation_id="op:start:strict-premise-acceptance",
        base_class="Monk",
        target_level=80,
        goal="Do not silently accept an unresolved Research premise.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    rejected = _bind_target_anchor(
        strict_started,
        manifests,
        operation_suffix="strict-premise-acceptance",
        design_coverage=coverage,
    )
    assert rejected["errorCode"] == (
        "progression_target_caveated_premise_requires_limited_acceptance"
    )

    limited_started = progression_service.start_build_progression(
        operation_id="op:start:limited-premise-acceptance",
        base_class="Monk",
        target_level=80,
        goal="Preserve an explicit Research premise caveat in a limited target anchor.",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )
    accepted = _bind_target_anchor(
        limited_started,
        manifests,
        operation_suffix="limited-premise-acceptance",
        design_coverage=coverage,
        acceptance_decision="limited_accepted",
    )
    assert accepted["status"] == "target_anchor_bound"
    assert accepted["acceptanceDecision"] == "limited_accepted"
    assert accepted["caveatedPremiseIds"] == [premise_id]


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
    monkeypatch,
):
    manifests = isolated_service
    trusted_reader = progression_service._research_receipt_reader()

    def read_with_core_secondary(ref: str):
        receipt = trusted_reader(ref)
        if ref == "dq-aaaaaaaaaaaaaaaa":
            receipt = deepcopy(receipt)
            receipt["result"]["buildFamilies"][0]["secondarySkillKeys"] = [
                "skill:TempestBellPlayer"
            ]
        return receipt

    monkeypatch.setattr(
        progression_service,
        "_research_receipt_reader",
        lambda: read_with_core_secondary,
    )
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
