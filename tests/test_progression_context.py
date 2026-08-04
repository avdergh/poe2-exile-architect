from __future__ import annotations

import inspect
import json
from copy import deepcopy
from pathlib import Path

from server import main, paths
from server.generation import models, progression_context, progression_service


ROOT = Path(__file__).resolve().parents[1]


VERSION = models.VersionContext(
    league="Test League",
    ruleset="poe2",
    game_patch="0.5.4",
    passive_tree_version="0_5",
    pob_version_or_commit="pob:test",
    graph_snapshot_id="graph:test",
    research_memory_ref="dq-0123456789abcdef",
)


def _checkpoint() -> dict[str, object]:
    return {
        "checkpointId": "context-checkpoint:flicker-target",
        "stageId": None,
        "currentGoal": "完成 Martial Artist Flicker Strike 的目标锚点。",
        "familyIdentity": {
            "ascendancyKey": "ascendancy:monk:martial_artist",
            "primarySkillKey": "skill:FlickerStrikePlayer",
            "secondarySkillKeys": ["skill:TempestBellPlayer"],
            "ascendancyName": "Martial Artist",
            "primarySkillName": "Flicker Strike",
            "secondarySkillNames": ["Tempest Bell"],
        },
        "recalledEvidence": [
            {
                "evidenceRef": "drr-flicker-charge-loop",
                "knowledgeKind": "skill_package",
                "title": "Flicker Strike 充能循环",
                "decision": "caveated",
                "application": "只有找到可重复产球方式后才能宣称 Boss 循环闭环。",
                "criticalConditions": ["Power Charge 可供 Flicker Strike 消耗"],
                "failureConditions": ["无小怪 Boss 中 Power Charge 枯竭"],
                "verificationTasks": ["验证首次产球和 Boss 场景维持率"],
                "verificationRefs": ["skill:FlickerStrikePlayer"],
            }
        ],
        "premiseDecisions": [
            {
                "premiseId": "rp-0123456789abcdef",
                "decision": "resolved",
                "resolutionRefs": ["drr-flicker-charge-loop"],
                "application": "采用已深读的独立 Boss 产球方案替代仅靠击杀的起球方式。",
                "verificationTasks": ["验证健康单体 Boss 的首次产球和持续维持率"],
            },
            {
                "premiseId": "rp-fedcba9876543210",
                "decision": "caveated",
                "resolutionRefs": [],
                "application": "保留为目标锚点的显式限制，不在上下文压缩时丢失。",
                "caveat": "极端长 Boss 战的维持率仍缺少完整建模证据。",
                "verificationTasks": ["在 artifact-bound lifecycle 中保留该限制"],
            },
        ],
        "mechanism": {
            "summary": "Flicker Strike 消耗球，Tempest Bell 负责单体窗口。",
            "damageLoop": ["建立可验证的 Power Charge 来源", "近身攻击并敲击 Tempest Bell"],
            "resourceLoop": ["生命偷取覆盖 Lifetap 成本"],
            "defenseLoop": ["抗性与护甲承担基础防御"],
            "configurationAssumptions": ["无小怪 Boss 不预设 Power Charge"],
            "unresolvedItems": ["Killing Palm 不能在健康单体 Boss 上建立初始球"],
        },
        "nextActions": ["验证独立 Boss 产球来源", "再进入正式 Judge"],
        "activeArtifactId": None,
        "activeBuildStateHash": "build-state:flicker-target",
    }


def test_progression_working_context_survives_a_simulated_context_reset(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    started = progression_service.start_build_progression(
        operation_id="op:start:context-reset",
        base_class="Monk",
        target_level=85,
        goal="创建从开荒到 Flicker Strike 的完整路线。",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )

    saved = progression_service.checkpoint_build_progression_context(
        progression_id=started["progressionId"],
        expected_context_revision=0,
        operation_id="op:context:flicker",
        checkpoint=_checkpoint(),
    )
    assert saved["status"] == "context_checkpointed"
    assert saved["contextRevision"] == 1

    # Simulate losing every earlier tool response: recovery uses only the persisted packet.
    resumed = progression_service.get_build_progression_status(
        started["progressionId"],
        detail="resume",
    )
    restored = resumed["resumePacket"]["workingCheckpoint"]
    evidence = restored["recalledEvidence"][0]
    assert evidence["criticalConditions"] == ["Power Charge 可供 Flicker Strike 消耗"]
    assert evidence["failureConditions"] == ["无小怪 Boss 中 Power Charge 枯竭"]
    premise_decisions = {item["premiseId"]: item for item in restored["premiseDecisions"]}
    assert premise_decisions["rp-0123456789abcdef"]["resolutionRefs"] == ["drr-flicker-charge-loop"]
    assert premise_decisions["rp-fedcba9876543210"]["decision"] == "caveated"
    assert "极端长 Boss 战" in premise_decisions["rp-fedcba9876543210"]["caveat"]
    assert resumed["resumePacket"]["nextAction"] == "compare_and_select_target_candidates"
    selection_packet = resumed["resumePacket"]["targetSelection"]["selectionPacket"]
    assert selection_packet["candidateCountRequested"] == 10
    assert selection_packet["minimumCandidateCount"] == 2
    assert resumed["containsHiddenReasoning"] is False


def test_progression_context_is_cas_idempotent_and_copy_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    progression_id = "00000000-0000-0000-0000-000000000001"

    first = progression_context.checkpoint_progression_context(
        progression_id=progression_id,
        expected_context_revision=0,
        operation_id="op:context:first",
        checkpoint=_checkpoint(),
    )
    duplicate = progression_context.checkpoint_progression_context(
        progression_id=progression_id,
        expected_context_revision=0,
        operation_id="op:context:first",
        checkpoint=_checkpoint(),
    )
    conflict = progression_context.checkpoint_progression_context(
        progression_id=progression_id,
        expected_context_revision=0,
        operation_id="op:context:stale",
        checkpoint=_checkpoint(),
    )

    assert first["contextRevision"] == 1
    assert duplicate["idempotent"] is True
    assert duplicate["contextRevision"] == 1
    assert conflict["errorCode"] == "progression_context_revision_conflict"

    unsafe = _checkpoint()
    unsafe["currentGoal"] = "读取 https://example.invalid/full-guide"
    rejected = progression_context.checkpoint_progression_context(
        progression_id=progression_id,
        expected_context_revision=1,
        operation_id="op:context:unsafe",
        checkpoint=unsafe,
    )
    assert rejected["errorCode"] == "invalid_progression_working_context"


def test_progression_context_preserves_common_starter_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    progression_id = "00000000-0000-0000-0000-000000000003"
    checkpoint = _checkpoint()
    checkpoint["knowledgeMode"] = "starter_common"
    checkpoint["familyIdentity"] = None
    checkpoint["starterIdentity"] = {
        "primarySkillKey": "skill:IceStrikePlayer",
        "secondarySkillKeys": ["skill:FrozenLocusPlayer"],
        "primarySkillName": "Ice Strike",
        "secondarySkillNames": ["Frozen Locus"],
        "expectedAscendancyKey": None,
        "expectedAscendancyName": None,
    }

    saved = progression_context.checkpoint_progression_context(
        progression_id=progression_id,
        expected_context_revision=0,
        operation_id="op:context:common-starter",
        checkpoint=checkpoint,
    )
    restored = progression_context.read_progression_context(progression_id)

    assert saved["status"] == "context_checkpointed"
    assert restored["checkpoint"]["knowledgeMode"] == "starter_common"
    assert restored["checkpoint"]["familyIdentity"] is None
    assert restored["checkpoint"]["starterIdentity"]["primarySkillName"] == "Ice Strike"


def test_progression_context_fails_closed_on_corrupt_existing_state(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    progression_id = "00000000-0000-0000-0000-000000000002"
    context_path = paths.build_progression_runs_dir() / progression_id / "working-context.json"
    context_path.parent.mkdir(parents=True)
    context_path.write_text("{not-json", encoding="utf-8")

    rejected = progression_context.checkpoint_progression_context(
        progression_id=progression_id,
        expected_context_revision=0,
        operation_id="op:context:corrupt",
        checkpoint=_checkpoint(),
    )

    assert rejected["errorCode"] == "progression_context_corrupt"
    assert context_path.read_text(encoding="utf-8") == "{not-json"


def test_mcp_status_defaults_compact_and_full_state_remains_explicit(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    started = progression_service.start_build_progression(
        operation_id="op:start:compact-status",
        base_class="Monk",
        target_level=85,
        goal="创建一条长流程以测试紧凑状态。",
        version_context=VERSION.model_dump(mode="json", by_alias=True),
    )

    compact = progression_service.get_build_progression_status(
        started["progressionId"],
        detail="compact",
    )
    full = progression_service.get_build_progression_status(
        started["progressionId"],
        detail="full",
    )
    assert "targetAnchorCreatePacket" not in compact["buildProgression"]["targetAnchor"]
    assert full["buildProgression"]["targetAnchor"]["targetAnchorCreatePacket"] is None
    selection_packet = full["buildProgression"]["targetSelection"]["selectionPacket"]
    assert selection_packet["candidateCountRequested"] == 10
    assert selection_packet["maximumCandidateCount"] == 10
    compact_size = len(json.dumps(compact, ensure_ascii=False).encode("utf-8"))
    full_size = len(json.dumps(full, ensure_ascii=False).encode("utf-8"))
    assert compact_size < full_size
    assert (
        inspect.signature(main.get_build_progression_status).parameters["detail"].default
        == "compact"
    )


def test_create_compact_research_response_preserves_failure_conditions():
    full = {
        "status": "known",
        "dedupeQueryRef": "dq-0123456789abcdef",
        "results": [
            {
                "memoryItemId": "fragment-flicker-resource",
                "fragmentId": "fragment-flicker-resource",
                "fragmentType": "resource_engine",
                "title": "充能资源检查",
                "summary": "消费前先证明生成。",
                "reusablePrinciple": "Boss 场景必须能持续获得球。",
                "componentKeys": ["skill:FlickerStrikePlayer"],
                "conditions": ["存在稳定球源"],
                "risks": ["仅靠击杀触发"],
                "verificationTasks": ["检查 Boss 球源"],
            }
        ],
        "deepResearchRecords": [
            {
                "recordId": "drr-flicker-charge-loop",
                "buildFamilyKey": "bf-flicker",
                "recordKind": "skill_package",
                "title": "Flicker Strike 主伤包",
                "summary": "使用 Power Charge 驱动额外攻击。",
                "conditions": ["Power Charge 可供消耗"],
                "failureConditions": ["Power Charge 枯竭"],
                "componentMentions": [{"candidateName": "Flicker Strike"}] * 30,
                "typedPayload": {"supportPackages": []},
                "content": "保持充能后再评估主循环。",
            }
        ],
        "buildFamilies": [
            {
                "buildFamilyKey": "bf-flicker",
                "ascendancyKey": "ascendancy:monk:martial_artist",
                "primarySkillKey": "skill:FlickerStrikePlayer",
                "secondarySkillKeys": [],
                "recordKindCounts": {"skill_package": 1},
            }
        ],
        "familyRecordCoverage": [
            {
                "buildFamilyKey": "bf-flicker",
                "eligibleRecordCount": 2,
                "returnedRecordCount": 1,
                "unreturnedRecordCount": 1,
                "recordKindCounts": {"skill_package": 1, "failure_mode": 1},
                "responseComplete": False,
            }
        ],
        "familyRecordIndex": [
            {
                "recordId": "drr-flicker-boss-failure",
                "buildFamilyKey": "bf-flicker",
                "recordKind": "failure_mode",
                "title": "无小怪 Boss 起球失败",
                "summary": "仅靠击杀或终结不能保证健康 Boss 起球。",
                "componentKeys": ["skill:FlickerStrikePlayer"],
                "returnedInThisResponse": False,
            },
        ],
        "familyPremiseCatalog": [
            {
                "premiseId": "rp-0123456789abcdef",
                "buildFamilyKey": "bf-flicker",
                "evidenceRef": "drr-flicker-boss-failure",
                "recordKind": "failure_mode",
                "premiseType": "failure_condition",
                "text": "无小怪 Boss 中 Power Charge 枯竭",
                "componentKeys": ["skill:FlickerStrikePlayer"],
            }
        ],
        "premiseAuditVersion": 1,
        "semanticEdges": [
            {
                "edgeId": "edge-flicker-charge",
                "sourceKey": "skill:KillingPalmPlayer",
                "targetKey": "skill:FlickerStrikePlayer",
                "edgeType": "enables",
                "rationale": "生成的球支持消费循环。",
                "contextRequirements": ["Killing Palm 可命中目标"],
                "affectedComponentKeys": ["skill:FlickerStrikePlayer"],
            }
        ],
        "buildPatterns": [
            {
                "patternId": "bdp-flicker-charge",
                "patternType": "planner_hint",
                "title": "充能维持",
                "summary": "先证明生成再评估消费。",
                "applicabilityRequirements": ["可重复获得 Power Charge"],
                "exclusionConditions": ["Boss 场景无法触发生成器"],
                "verificationTasks": ["测量 Boss 维持率"],
            }
        ],
        "transferablePatterns": [],
        "retrievalPolicy": {"veryLargeRepeatedPolicy": "x" * 8_000},
        "requestedComponentKeys": [],
        "requestedResearchAxes": [],
        "requestedAscendancyKey": "ascendancy:monk:martial_artist",
        "requestedPrimarySkillKey": "skill:FlickerStrikePlayer",
        "requestedBuildFamilyKeys": [],
        "requestedRecordKinds": [],
        "includeTransferable": False,
        "componentKeyGroups": [],
        "detailLevel": "summary",
    }

    compact = main._compact_create_research_response(full)
    assert "retrievalPolicy" not in compact
    assert "componentMentions" not in compact["deepResearchRecords"][0]
    assert compact["responseProfileTruncatesResults"] is False
    assert compact["familyRecordCoverage"][0]["unreturnedRecordCount"] == 1
    assert compact["familyRecordIndex"][0]["returnedInThisResponse"] is False
    assert compact["familyPremiseCatalog"][0]["premiseId"] == "rp-0123456789abcdef"
    assert compact["premiseAuditVersion"] == 1
    digest = {item["evidenceRef"]: item for item in compact["criticalPremiseDigest"]}
    assert digest["drr-flicker-charge-loop"]["failureConditions"] == ["Power Charge 枯竭"]
    assert digest["bdp-flicker-charge"]["verificationTasks"] == ["测量 Boss 维持率"]
    assert digest["fragment-flicker-resource"]["failureConditions"] == ["仅靠击杀触发"]
    assert digest["edge-flicker-charge"]["criticalConditions"] == ["Killing Palm 可命中目标"]
    assert "conditions" not in compact["results"][0]
    assert "contextRequirements" not in compact["semanticEdges"][0]
    assert "applicabilityRequirements" not in compact["buildPatterns"][0]
    assert (
        len(json.dumps(compact, ensure_ascii=False)) < len(json.dumps(full, ensure_ascii=False)) / 2
    )

    focused_payload = deepcopy(full)
    focused_payload["detailLevel"] = "record"
    focused = main._compact_create_research_response(focused_payload)
    assert focused["buildPatterns"][0]["patternId"] == "bdp-flicker-charge"
    assert focused["results"][0]["fragmentId"] == "fragment-flicker-resource"
    assert focused["criticalPremiseDigest"][0]["evidenceRef"] == ("drr-flicker-charge-loop")

    expanded = deepcopy(full)
    expanded["results"] = [
        dict(full["results"][0], fragmentId=f"fragment-{index}") for index in range(15)
    ]
    expanded["semanticEdges"] = [
        dict(full["semanticEdges"][0], edgeId=f"edge-{index}") for index in range(8)
    ]
    expanded["buildPatterns"] = [
        dict(full["buildPatterns"][0], patternId=f"pattern-{index}") for index in range(8)
    ]
    expanded["transferablePatterns"] = [
        dict(full["buildPatterns"][0], patternId=f"transferable-{index}") for index in range(5)
    ]
    expanded_compact = main._compact_create_research_response(expanded)
    assert len(expanded_compact["results"]) == 15
    assert len(expanded_compact["semanticEdges"]) == 8
    assert len(expanded_compact["buildPatterns"]) == 8
    assert len(expanded_compact["transferablePatterns"]) == 5


def test_mcp_bootstrap_does_not_repeat_the_complete_runtime_guide():
    bootstrap = (ROOT / "server" / "MCP_BOOTSTRAP.md").read_text(encoding="utf-8")
    full_guide = (ROOT / "server" / "ASSISTANT_GUIDE.md").read_text(encoding="utf-8")

    assert main._GUIDE.name == "MCP_BOOTSTRAP.md"
    assert main._INSTRUCTIONS == bootstrap
    assert len(bootstrap.encode("utf-8")) < 8_000
    assert len(bootstrap) < len(full_guide) / 5
    assert "checkpoint_build_progression_context" in bootstrap
    assert 'detail="resume"' in bootstrap
