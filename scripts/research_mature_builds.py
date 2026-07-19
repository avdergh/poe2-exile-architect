"""Product entrypoint for mature PoE2 build research queues.

This script does not call an LLM provider. It prepares safe queue metadata,
leases one mature build case at a time to the current Researcher agent, renders
bounded transient evidence only for the active lease, and accepts safe proposals
through the existing typed gates.
"""

from __future__ import annotations

import argparse
import copy
import json
import secrets
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_phase45_researcher_batch as legacy_batch  # noqa: E402
from scripts import run_phase4_deep_review_acceptance as acceptance  # noqa: E402
from server import paths  # noqa: E402
from server.freshness import providers as freshness_providers  # noqa: E402
from server.knowledge import copy_safety, research_models, research_packet  # noqa: E402

DEFAULT_OUTPUT_DIR = REPO_ROOT / ".poe-bd-research"
RUNS_DIRNAME = "runs"
QUEUE_DB_FILENAME = "poe_bd_research_queue.sqlite"
DEFAULT_TEMP_DIRNAME = "poe-bd-creator-research-packets"
DEFAULT_MEMORY_DB_PATH = paths.mature_learning_path()

RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
    "transientPacketPath",
    "transientPromptPath",
    "packet.json",
    "researcher_prompt.txt",
    "pobb.in/",
    "poe.ninja/",
)


def queue_cases(
    *,
    league_url: str = "current",
    limit: int = 50,
    worker_count: int = 1,
    level_min: int = 90,
    level_max: int = 100,
    ascendancies: list[str] | None = None,
    ninja_classes: list[str] | None = None,
    source_files: list[str | Path] | None = None,
    source_batch_files: list[str | Path] | None = None,
    expected_source_count: int | None = None,
    sample_start_index: int = 1,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    temp_root: str | Path | None = None,
    ttl_seconds: int = 3600,
    current_patch: str | None = None,
    passive_tree_version: str | None = None,
    pob_version_or_commit: str | None = None,
    browser_driver: Any | None = None,
    resume: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create or resume a safe mature-build research queue."""
    del worker_count  # Deprecated compatibility input; execution is always serial.
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    db_path = _queue_db_path(output_root, queue_db_path)
    effective_temp_root = _effective_temp_root(temp_root, output_root=output_root)
    effective_temp_root.mkdir(parents=True, exist_ok=True)
    research_packet.cleanup_expired_packets(temp_root=effective_temp_root)
    version_context = _runtime_version_context(
        current_patch=current_patch,
        passive_tree_version=passive_tree_version,
        pob_version_or_commit=pob_version_or_commit,
    )
    if not dry_run and db_path.exists() and not resume:
        raise FileExistsError(
            "research queue already exists; use --resume with the same --output-dir"
        )

    source_file_values = list(source_files or [])
    source_batch_file_values = list(source_batch_files or [])
    normalized_ninja_classes = legacy_batch._normalize_ninja_classes(ninja_classes or [])
    local_sources = legacy_batch._local_sources(source_file_values, source_batch_file_values)
    source_input_summary = {
        "sourceFileArgumentCount": len(source_file_values),
        "sourceBatchFileArgumentCount": len(source_batch_file_values),
        "localSourceInputCount": len(local_sources),
        "requestedSampleCount": (
            len(local_sources)
            if source_file_values or source_batch_file_values
            else max(0, int(limit))
        ),
        "expectedSourceCount": (
            max(0, int(expected_source_count)) if expected_source_count is not None else None
        ),
    }
    if expected_source_count is not None:
        if not source_file_values and not source_batch_file_values:
            raise ValueError("--expected-source-count requires local source input")
        if int(expected_source_count) < 1:
            raise ValueError("--expected-source-count must be at least 1")
        if len(local_sources) != int(expected_source_count):
            report = _source_input_count_mismatch_report(
                expected_source_count=int(expected_source_count),
                source_input_summary=source_input_summary,
            )
            _assert_safe_payload(report)
            return report
    cases = (
        legacy_batch._cases_from_sources(
            local_sources,
            sample_start_index=sample_start_index,
        )
        if local_sources
        else legacy_batch._cases_from_ninja(
            league_url=league_url,
            limit=limit,
            level_min=level_min,
            level_max=level_max,
            ascendancies=ascendancies or [],
            browser_driver=browser_driver,
            ninja_classes=normalized_ninja_classes,
        )
    )
    _normalize_sample_ids(cases, sample_start_index=sample_start_index)
    source_input_summary["uniqueLocalCaseCount"] = len(cases) if local_sources else 0
    source_input_summary["duplicateLocalSourceCount"] = (
        max(0, len(local_sources) - len(cases)) if local_sources else 0
    )

    if dry_run:
        report = _queue_report(
            status="dry_run",
            db_path=db_path,
            requested_worker_count=1,
            cases=[_safe_case_row_from_case(case) for case in cases],
            dry_run=True,
            source_input_summary=source_input_summary,
        )
        _assert_safe_payload(report)
        return report

    _init_db(db_path)
    _write_metadata(
        db_path,
        {
            "queueKind": "poe_bd_research_external_agent_queue",
            "leagueUrl": legacy_batch._safe_text(league_url),
            "limit": str(limit),
            "levelMin": str(level_min),
            "levelMax": str(level_max),
            "ascendancies": json.dumps(
                [legacy_batch._safe_text(item) for item in ascendancies or []],
                ensure_ascii=False,
            ),
            "ninjaClasses": json.dumps(
                [legacy_batch._safe_text(item) for item in normalized_ninja_classes],
                ensure_ascii=False,
            ),
            "sourceFileArgumentCount": str(source_input_summary["sourceFileArgumentCount"]),
            "sourceBatchFileArgumentCount": str(
                source_input_summary["sourceBatchFileArgumentCount"]
            ),
            "localSourceInputCount": str(source_input_summary["localSourceInputCount"]),
            "expectedSourceCount": (
                ""
                if source_input_summary["expectedSourceCount"] is None
                else str(source_input_summary["expectedSourceCount"])
            ),
            "uniqueLocalCaseCount": str(source_input_summary["uniqueLocalCaseCount"]),
            "duplicateLocalSourceCount": str(source_input_summary["duplicateLocalSourceCount"]),
            "requestedSampleCount": str(source_input_summary["requestedSampleCount"]),
            "queueStatus": (
                ""
                if any(case.get("status") == "pending" for case in cases)
                else "source_unavailable"
            ),
            "requestedWorkerCount": "1",
            "workerCountSemantics": "serial_one_case_at_a_time",
            "currentPatch": version_context["gamePatch"],
            "passiveTreeVersion": version_context["passiveTreeVersion"],
            "pobVersionOrCommit": version_context["pobVersionOrCommit"],
            "versionContextStatus": version_context["status"],
            "updatedAt": _now_iso(),
        },
    )

    inserted = 0
    skipped_duplicates = 0
    for case in cases:
        if case.get("status") != "pending":
            packet_id = ""
            packet_safe_hash = ""
        else:
            packet = _prepare_packet(
                case,
                temp_root=effective_temp_root,
                ttl_seconds=ttl_seconds,
                current_patch=version_context["gamePatch"],
                passive_tree_version=version_context["passiveTreeVersion"],
                pob_version_or_commit=version_context["pobVersionOrCommit"],
            )
            packet_id = str(packet["packetId"])
            packet_safe_hash = str(packet["packetSafeHash"])
        row = _safe_case_row_from_case(
            case,
            packet_id=packet_id,
            packet_safe_hash=packet_safe_hash,
        )
        was_inserted = _insert_case_if_absent(db_path, row)
        inserted += 1 if was_inserted else 0
        skipped_duplicates += 0 if was_inserted else 1

    report = queue_status(
        output_dir=output_root,
        queue_db_path=db_path,
        status_override=(
            "queued"
            if any(case.get("status") == "pending" for case in cases)
            else "source_unavailable"
        ),
        inserted_count=inserted,
        duplicate_count=skipped_duplicates,
    )
    _assert_safe_payload(report)
    return report


def claim_case(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    lease_seconds: int = 1800,
    lease_owner: str = "current_researcher_agent",
) -> dict[str, Any]:
    """Atomically lease one case while preventing concurrent active research."""
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    _init_db(db_path)
    now = _now()
    expires = now + timedelta(seconds=max(1, int(lease_seconds or 1)))
    lease_token = secrets.token_urlsafe(32)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            """
            SELECT *
              FROM cases
             WHERE status IN ('claimed', 'accepting')
               AND (status = 'accepting' OR lease_expires_at > ?)
             ORDER BY id ASC
             LIMIT 1
            """,
            (_iso(now),),
        ).fetchone()
        if active is not None:
            conn.commit()
            return {
                "status": "active_case_in_progress",
                "queueKind": "poe_bd_research_external_agent_queue",
                "sampleId": str(active["sample_id"]),
                "noRawMatureBuildMaterial": True,
            }
        row = conn.execute(
            """
            SELECT *
              FROM cases
             WHERE status = 'queued'
                OR (status = 'claimed' AND lease_expires_at <= ?)
             ORDER BY id ASC
             LIMIT 1
            """,
            (_iso(now),),
        ).fetchone()
        if row is None:
            conn.commit()
            return {
                "status": "no_pending_cases",
                "queueKind": "poe_bd_research_external_agent_queue",
                "noRawMatureBuildMaterial": True,
            }
        conn.execute(
            """
            UPDATE cases
               SET status = 'claimed',
                   lease_token = ?,
                   lease_owner = ?,
                   lease_expires_at = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (lease_token, _safe_short(lease_owner), _iso(expires), _iso(now), int(row["id"])),
        )
        claimed = conn.execute("SELECT * FROM cases WHERE id = ?", (int(row["id"]),)).fetchone()
        conn.commit()
    result = _claim_payload(
        dict(claimed),
        lease_token=lease_token,
        output_root=Path(output_dir),
    )
    _assert_safe_payload(result)
    return result


def render_claim_prompt(
    *,
    lease_token: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    temp_root: str | Path | None = None,
    current_patch: str | None = None,
    passive_tree_version: str | None = None,
    user_language: str = "zh-CN",
) -> str:
    """Render a safe navigation manifest for the current agent holding a valid lease."""
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    row = _case_for_valid_lease(db_path, lease_token)
    version_context = _queue_version_context(db_path)
    packet = _packet_for_valid_lease(
        row=row,
        output_dir=Path(output_dir),
        temp_root=temp_root,
    )
    manifest = research_packet.inspect_packet(packet)
    payload = {
        "status": "ok",
        "deprecatedRawPrompt": True,
        "message": (
            "完整 PoB/XML 不再通过 prompt 输出。请按 inspect -> read/search -> safe review -> "
            "accept 的流程研究当前案例。"
        ),
        "sampleId": str(row["sample_id"]),
        "packetId": manifest["packetId"],
        "packetSafeHash": manifest["packetSafeHash"],
        "safeMetadata": manifest["safeMetadata"],
        "sections": manifest["sections"],
        "recommendedReadOrder": manifest["recommendedReadOrder"],
        "requiredCoverage": manifest["requiredCoverage"],
        "versionContext": {
            "gamePatch": current_patch or version_context["gamePatch"],
            "passiveTreeVersion": passive_tree_version or version_context["passiveTreeVersion"],
            "pobVersionOrCommit": version_context["pobVersionOrCommit"],
        },
        "userLanguage": user_language,
        "nextCommands": ["inspect", "read", "search", "accept"],
        "noRawMatureBuildMaterial": True,
    }
    _assert_transient_view_payload(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def inspect_case(
    *,
    lease_token: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    temp_root: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect the current transient case without returning raw transport material."""
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    row = _case_for_valid_lease(db_path, lease_token)
    packet = _packet_for_valid_lease(
        row=row,
        output_dir=Path(output_dir),
        temp_root=temp_root,
    )
    result = research_packet.inspect_packet(packet)
    result["sampleId"] = str(row["sample_id"])
    _assert_transient_view_payload(result)
    return result


def read_case_section(
    *,
    lease_token: str,
    section: str,
    cursor: int = 0,
    limit: int = research_packet.DEFAULT_PAGE_SIZE,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    temp_root: str | Path | None = None,
) -> dict[str, Any]:
    """Read one bounded structured section for the currently leased case."""
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    row = _case_for_valid_lease(db_path, lease_token)
    packet = _packet_for_valid_lease(
        row=row,
        output_dir=Path(output_dir),
        temp_root=temp_root,
    )
    result = research_packet.read_packet_section(
        packet,
        section=section,
        cursor=cursor,
        limit=limit,
    )
    result["sampleId"] = str(row["sample_id"])
    _assert_transient_view_payload(result, enforce_size=True)
    return result


def search_case(
    *,
    lease_token: str,
    query: str,
    section: str | None = None,
    limit: int = research_packet.DEFAULT_PAGE_SIZE,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    temp_root: str | Path | None = None,
) -> dict[str, Any]:
    """Search the structured transient case currently protected by a valid lease."""
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    row = _case_for_valid_lease(db_path, lease_token)
    packet = _packet_for_valid_lease(
        row=row,
        output_dir=Path(output_dir),
        temp_root=temp_root,
    )
    result = research_packet.search_packet(
        packet,
        query=query,
        section=section,
        limit=limit,
    )
    result["sampleId"] = str(row["sample_id"])
    _assert_transient_view_payload(result, enforce_size=True)
    return result


def render_worker_brief(
    *,
    lease_token: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Render a safe inline brief for the current Researcher agent."""
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    row = _case_for_valid_lease(db_path, lease_token)
    sample_id = str(row["sample_id"])
    review_file = _suggested_review_file(
        output_dir=Path(output_dir),
        sample_id=sample_id,
        lease_token=lease_token,
    )
    prompt_text = _worker_brief_text(row, lease_token=lease_token, review_file=review_file)
    result = {
        "status": "ok",
        "queueKind": "poe_bd_research_external_agent_queue",
        "sampleId": sample_id,
        "leaseToken": lease_token,
        "reviewFile": review_file,
        "workerPrompt": prompt_text,
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_payload(result)
    return result


def render_review_contract(
    *,
    lease_token: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return the exact safe-review contract just before the Agent writes the artifact."""
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    row = _case_for_valid_lease(db_path, lease_token)
    version_context = _queue_version_context(db_path)
    sample_id = str(row["sample_id"])
    review_file = _suggested_review_file(
        output_dir=Path(output_dir),
        sample_id=sample_id,
        lease_token=lease_token,
    )
    artifact_identity = _lease_artifact_identity(row)
    result = {
        "status": "ok",
        "contractVersion": "phase4-safe-review-v1",
        "sampleId": sample_id,
        "reviewFile": review_file,
        "artifactIdentity": {
            "reportId": "poe_bd_research_review",
            "safeArtifactOnly": True,
            **artifact_identity,
        },
        "artifactEncoding": {
            "format": "json",
            "encoding": "utf-8",
            "prettyPrinted": True,
            "indent": 2,
        },
        "topLevelTemplate": {
            "reportId": "poe_bd_research_review",
            "safeArtifactOnly": True,
            "artifactIdentity": artifact_identity,
            "caseCoverage": {
                "supports": "evidence_missing",
                "rotation": "evidence_missing",
                "passiveAscendancy": "evidence_missing",
                "gearRoles": "evidence_missing",
                "resourceDefense": "evidence_missing",
            },
            "mechanicAudit": [],
            "deepResearchRecords": [],
            "candidateReviews": [],
        },
        "allowedValues": {
            "caseCoverage": sorted(acceptance.CASE_COVERAGE_STATUSES),
            "componentRole": sorted(research_models.COMPONENT_ROLES),
            "recordKind": sorted(research_models.DEEP_RESEARCH_RECORD_KINDS),
            "patternType": sorted(acceptance.PATTERN_TYPE_VALUES),
            "axis": sorted(acceptance.DESIGN_AXIS_VALUES),
            "transferScope": ["family", "component"],
            "knowledgeShape": ["player_action_sequence", "state_causal_chain"],
            "mechanicAuditClaimType": sorted(acceptance.MECHANIC_AUDIT_CLAIM_TYPES),
            "mechanicAuditWikiStatus": sorted(acceptance.MECHANIC_AUDIT_WIKI_STATUSES),
            "mechanicAuditDecision": sorted(acceptance.MECHANIC_AUDIT_DECISIONS),
            "mechanicAuditCorroboration": sorted(acceptance.MECHANIC_AUDIT_CORROBORATION),
            "gearResponsibilityType": sorted(research_models.GEAR_RESPONSIBILITY_TYPES),
            "typedIdentityFields": {
                "familyCoreSkillKeys": "resolved generator/control skill keys not already inferred from clear, boss, trigger host/payload roles",
                "resourceMechanisms": "lower_snake_case resource methods without graph nodes",
                "supportPackages": "skillKey/supportKeys, or exact skillName/supportNames when resolver is unavailable",
                "supportCoverageExceptions": "skillKey, or exact skillName when resolver is unavailable, plus source_coverage_gap/not_applicable detail",
                "availability": "standard or source_specific_random",
                "sourceSpecificComponentKeys": "random-instance components excluded from planner advice",
                "ascendancyResponsibilities": "componentKey, or exact componentName when resolver is unavailable, plus concrete responsibility",
                "gearResponsibilities": "componentKey, or exact componentName when resolver is unavailable, plus canonical responsibilityType and concise responsibility",
            },
        },
        "componentRoleNodeTypeCompatibility": {
            role: list(node_types)
            for role, node_types in sorted(acceptance.ROLE_NODE_TYPES.items())
        },
        "mechanicAuditTemplate": {
            "claim": "需要外部机制复核的具体事实结论",
            "claimType": "behavior_or_trigger",
            "affectedRecords": ["与 deepResearchRecords.title 完全一致的标题"],
            "affectedCandidates": [],
            "wiki": {
                "status": "supports",
                "pageTitle": "lookup_mechanic 返回的 title",
                "sourceRef": "poe2wiki:page:<pageId>:rev:<revisionId>",
            },
            "corroboration": ["source_artifact", "pinned_pob_static"],
            "decision": "keep",
        },
        "recordTemplate": {
            "recordKind": "mechanic_chain",
            "title": "聚焦知识单元标题",
            "summary": "用于召回的短摘要",
            "content": "只解释一个主要问题，并写出具体组件、因果、条件与风险。",
            "contentLanguage": "zh-CN",
            "lengthExceptionReason": None,
            "components": [
                {
                    "candidateName": "具体组件名",
                    "componentKey": None,
                    "role": "generator",
                    "resolverQuery": "具体组件名",
                }
            ],
            "conditions": [],
            "failureConditions": [],
            "typedPayload": {"knowledgeShape": "state_causal_chain"},
            "classKey": None,
            "ascendancyKey": None,
            "extractionMethodVersion": "deep_research_mvp_v1",
        },
        "candidateTemplate": {
            "patternType": "cooccurrence",
            "title": "安全候选标题",
            "summary": "只描述本案例支持的关系",
            "axes": ["mechanic_engine"],
            "components": [
                {
                    "candidateName": "具体组件名",
                    "componentKey": None,
                    "role": "primary_damage",
                    "resolverQuery": "具体组件名",
                }
            ],
            "plannerHint": "生成阶段可尝试的安全提示",
            "verificationGate": "需要 PoB/Judge/人工复验的条件",
            "verificationTasks": [],
            "transferScope": "family",
            "availability": "standard",
            "sourceSpecificComponentNames": [],
            "transferRationale": "若选择 component，说明移除原 Family 名称后为何仍可迁移。",
            "applicabilityRequirements": [],
            "exclusionConditions": [],
        },
        "rules": [
            "只能使用 allowedValues 中的枚举；不得自造 role、axis 或 patternType。",
            "artifactIdentity、sampleId、researchGroupId、caseRef、safeEvidenceRef 和版本字段由当前 lease 注入；不要在记录或候选中重复抄写。",
            "role 表达组件在 BD 中的功能；节点类型由 resolver 证明，并按 componentRoleNodeTypeCompatibility 检查。",
            "同一 researchGroupId 的记录必须使用同一个 ascendancyKey，并且只把一个核心主技能标为 primary_damage。",
            "只有 skill_package 和已确认 mechanic_chain 能授权 BuildFamily 身份。clear_skill、boss_skill、triggered_payload，以及负责投送 triggered_payload 或 primary_damage 的 trigger_host 由程序自动参与 Family；modelability_caveat、failure_mode 或 open_question 中的未证实组件不会参与 Family，也不得在这些记录里填写 familyCoreSkillKeys。",
            "必须为整个 researchGroup 的每个 Family 核心技能组提供 typedPayload.supportPackages，且每组至少两个已解析辅助；若来源确实缺失或技能不接受普通辅助，使用 supportCoverageExceptions 明确 source_coverage_gap 或 not_applicable，不能只在正文提辅助。",
            "正文使用来源中的具体主动技能或辅助名称时，也应把它写入 components；validate-only 会报告来源名称与结构化组件之间的缺口，但不会要求把所有工具技能和辅助都持久化。",
            "passiveAscendancy covered 必须有 ascendancy_shell，并在 typedPayload.ascendancyResponsibilities 写具体升华节点/职责；验收会核验该节点在物理图中确实 belongs_to 当前升华。",
            "gearRoles covered 必须有 gear_synergy，并在 typedPayload.gearResponsibilities 说明已解析武器/暗金的具体职责；只有防御或便利装备不足以代表构筑身份装备已还原。依赖身份装备的机制和 component transfer 必须包含对应装备职责。",
            "gearRoles 为 evidence_missing 时，accept 会暂缓 mechanic_chain 和 component transfer，避免遗漏身份装备后把实例机制写成通用知识；补齐装备职责或确认 not_applicable 后再提交。",
            "若装备分区显示 itemStates 包含 mutated，依赖该随机实例的记录写 availability=source_specific_random，并在 sourceSpecificComponentKeys 指出对应装备。该知识只解释本案，不进入常规 Create 召回或 planner pattern。",
            "依赖随机实例的 candidateReview 也写 availability=source_specific_random，并在 sourceSpecificComponentNames 精确指出对应组件。accept 只用这些组件建立 observation 索引；组件无法解析时保留无组件索引的案例备注，不生成 planner pattern。",
            "resource_engine 若依赖法力偷取、普通药剂或装备词缀等无物理图节点机制，必须在 typedPayload.resourceMechanisms 写 lower_snake_case 标签，例如 mana_leech、mana_flask；否则无法生成 knowledge key。",
            "组件已被 resolve_graph_component 唯一解析时，将返回的 stable key 写入 componentKey。宿主没有 resolver 时，supportPackages 可用 skillName/supportNames，升华和装备职责可用 componentName；accept 只对同一记录中唯一解析的精确名称做 stable-key 替换。",
            "更细的轮转、窗口和证据语义写入 content、typedPayload、conditions 或 summary。",
            "只在独立重建完成后，用 explain_mechanic/search_mechanics 和 lookup_mechanic 复核触发、前置条件、资源流、转换或变形等高风险结论，并把结果写入 mechanicAudit。lookup_mechanic 命中时必须使用其 revision-pinned sourceRef。",
            "每条 mechanic_chain 和 resource_engine 都必须被至少一个 mechanicAudit.affectedRecords 精确引用；claim 必须写该对象实际依赖的最强因果结论，不能只审计一个更弱的前提。",
            "每次 lookup_mechanic 只查询一个精确 Wiki 页面或一个中央机制名称，不得把 A / B 组件名拼成一次查询。一个关系需要多页证据时，提交多条关联同一对象的原子 mechanicAudit。",
            "poe2wiki 只能作为机制解释的校对证据，不能替代来源实例归属、support 兼容性、武器状态、数值 Judge 或 Family 身份证据；每项 supports/contradicts 结论还必须填写至少一种 corroboration。",
            "wiki contradicted 但仍 keep 的对象、主动 decision=defer 的对象以及没有其他 corroboration 的 wiki-only 对象会被最小范围暂缓；wiki unavailable 不会自动阻塞无关对象。",
            "每个 covered 维度必须有具体记录证据；证据不足时填 evidence_missing。",
            "先写 safe review，再运行 accept --validate-only；修复全部 invalid_schema 后才能正式 accept。",
            "safe review 使用 UTF-8、两空格缩进的多行 JSON，确保有界修复能精确编辑单个字段。",
            "单样本只能形成 case_observation，不能声称 common、usually 或通常。",
            "transferScope=component 只用于有明确因果链、最低适用条件、排除条件和验证任务的跨 Family 候选；普通案例事实使用 family。",
            "单案例不得提交 transferScope=global。公用知识由后端依据跨 Family 证据晋升，且最高只到 likely_pattern。",
            "不要为了产出公用知识而强行标记 component；不确定时保持 family。",
        ],
        "versionContext": version_context,
        "nextActions": ["init-review", "edit_review", "accept --validate-only", "accept"],
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_payload(result)
    return result


def init_review(
    *,
    lease_token: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Atomically create the lease-bound safe-review skeleton without overwriting work."""
    output_root = Path(output_dir)
    db_path = _queue_db_path(output_root, queue_db_path)
    row = _case_for_valid_lease(db_path, lease_token)
    sample_id = str(row["sample_id"])
    review_file = _suggested_review_file(
        output_dir=output_root,
        sample_id=sample_id,
        lease_token=lease_token,
    )
    review_path = output_root / review_file
    review_path.parent.mkdir(parents=True, exist_ok=True)
    skeleton = {
        "reportId": "poe_bd_research_review",
        "safeArtifactOnly": True,
        "artifactIdentity": _lease_artifact_identity(row),
        "caseCoverage": {
            "supports": "evidence_missing",
            "rotation": "evidence_missing",
            "passiveAscendancy": "evidence_missing",
            "gearRoles": "evidence_missing",
            "resourceDefense": "evidence_missing",
        },
        "mechanicAudit": [],
        "deepResearchRecords": [],
        "candidateReviews": [],
    }
    try:
        with review_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(skeleton, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        status = "initialized"
    except FileExistsError:
        status = "already_exists"
    result = {
        "status": status,
        "sampleId": sample_id,
        "reviewFile": review_file,
        "created": status == "initialized",
        "artifactEncoding": {
            "format": "json",
            "encoding": "utf-8",
            "prettyPrinted": True,
            "indent": 2,
        },
        "nextAction": "Edit only this lease-bound review file, then run accept --validate-only.",
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_payload(result)
    return result


def accept_case(
    *,
    lease_token: str,
    review_file: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    memory_db_path: str | Path = DEFAULT_MEMORY_DB_PATH,
    acceptance_output_dir: str | Path | None = None,
    temp_root: str | Path | None = None,
    validation_only: bool = False,
) -> dict[str, Any]:
    """Validate or accept a safe Researcher proposal for the current lease."""
    output_root = Path(output_dir)
    db_path = _queue_db_path(output_root, queue_db_path)
    row = _case_for_valid_lease(db_path, lease_token)
    version_context = _queue_version_context(db_path)
    sample_id = str(row["sample_id"])
    safe_review_file = _resolve_review_file(Path(review_file), output_root=output_root)
    review_payload = _assert_review_file_for_lease(
        review_file=safe_review_file,
        output_root=output_root,
        sample_id=sample_id,
        lease_token=lease_token,
        source_hash_ref=str(row["source_hash_ref"]),
        packet_safe_hash=str(row["packet_safe_hash"]),
    )
    source_skill_manifest = _optional_acceptance_skill_manifest(
        row=row,
        output_root=output_root,
        temp_root=temp_root,
    )
    if validation_only:
        report = acceptance.accept_deep_review_candidates(
            db_path=Path(memory_db_path),
            json_output=output_root / "unused-validation-report.json",
            md_output=output_root / "unused-validation-report.md",
            review_file=safe_review_file,
            version_context=version_context,
            source_skill_manifest=source_skill_manifest,
            review_payload=review_payload,
            require_deep_records=True,
            validation_only=True,
        )
        result = _validation_only_result(report, sample_id=sample_id)
        _assert_safe_payload(result)
        return result

    accept_dir = (
        Path(acceptance_output_dir) if acceptance_output_dir else output_root / "acceptance"
    )
    accept_dir.mkdir(parents=True, exist_ok=True)
    _begin_accepting(db_path, row=row, lease_token=lease_token)
    slug = f"{_slug(sample_id)}-{lease_token[:12]}"
    try:
        report = acceptance.accept_deep_review_candidates(
            db_path=Path(memory_db_path),
            json_output=accept_dir / f"{slug}-acceptance.json",
            md_output=accept_dir / f"{slug}-acceptance.md",
            review_file=safe_review_file,
            version_context=version_context,
            source_skill_manifest=source_skill_manifest,
            review_payload=review_payload,
            require_deep_records=True,
        )
    except Exception:
        _finish_accepting_after_exception(db_path, row=row, lease_token=lease_token)
        raise
    accepted = str(report.get("status") or "") == "accepted"
    status = "accepted" if accepted else "acceptance_rejected"
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE cases
               SET status = ?,
                   accepted_at = ?,
                   updated_at = ?,
                   lease_token = NULL,
                   lease_owner = NULL,
                   lease_expires_at = NULL,
                   acceptance_status = ?,
                   accepted_pattern_count = ?,
                   accepted_deep_record_count = ?,
                   unresolved_deep_record_component_count = ?,
                   research_quality_summary = ?,
                   deferred_candidate_count = ?
             WHERE sample_id = ?
               AND status = 'accepting'
               AND lease_token = ?
               AND packet_safe_hash = ?
            """,
            (
                status,
                _now_iso() if accepted else "",
                _now_iso(),
                str(report.get("status") or ""),
                int(report.get("acceptedPatternCount") or 0),
                int(report.get("acceptedDeepRecordCount") or 0),
                int(report.get("unresolvedDeepRecordComponentCount") or 0),
                json.dumps(_research_quality_summary(report), ensure_ascii=False, sort_keys=True),
                int(report.get("deferredCandidateCount") or 0),
                sample_id,
                lease_token,
                str(row["packet_safe_hash"]),
            ),
        )
        conn.commit()
    if cur.rowcount != 1:
        raise ValueError("lease was modified before accept could be committed")
    result = {
        "status": status,
        "sampleId": sample_id,
        "packetSafeHash": str(row["packet_safe_hash"]),
        "acceptedPatternCount": int(report.get("acceptedPatternCount") or 0),
        "acceptedDeepRecordCount": int(report.get("acceptedDeepRecordCount") or 0),
        "createdDeepRecordCount": int(report.get("createdDeepRecordCount") or 0),
        "updatedDeepRecordCount": int(report.get("updatedDeepRecordCount") or 0),
        "addedDeepRecordEvidenceCount": int(report.get("addedDeepRecordEvidenceCount") or 0),
        "acceptedBuildFamilyKeys": report.get("acceptedBuildFamilyKeys") or [],
        "unresolvedDeepRecordComponentCount": int(
            report.get("unresolvedDeepRecordComponentCount") or 0
        ),
        "deepRecordsWithUnresolvedComponents": report.get("deepRecordsWithUnresolvedComponents")
        or [],
        **_research_quality_summary(report),
        "deferredCandidateCount": int(report.get("deferredCandidateCount") or 0),
        "deferredReasonCounts": report.get("deferredReasonCounts") or {},
        "patternWrite": report.get("patternWrite") or {},
        "deepRecordWrite": report.get("deepRecordWrite") or {},
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_payload(result)
    return result


def retry_accept_case(
    *,
    sample_id: str,
    review_file: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    memory_db_path: str | Path = DEFAULT_MEMORY_DB_PATH,
    acceptance_output_dir: str | Path | None = None,
    temp_root: str | Path | None = None,
) -> dict[str, Any]:
    """Retry acceptance for a previously rejected safe review artifact."""
    output_root = Path(output_dir)
    db_path = _queue_db_path(output_root, queue_db_path)
    row = _case_for_rejected_sample(db_path, sample_id)
    version_context = _queue_version_context(db_path)
    source_skill_manifest = _optional_acceptance_skill_manifest(
        row=row,
        output_root=output_root,
        temp_root=temp_root,
    )
    accept_dir = (
        Path(acceptance_output_dir) if acceptance_output_dir else output_root / "acceptance"
    )
    accept_dir.mkdir(parents=True, exist_ok=True)
    safe_review_file = _resolve_review_file(Path(review_file), output_root=output_root)
    review_payload = _canonical_review_artifact_identity(
        review_file=safe_review_file,
        sample_id=str(row["sample_id"]),
        source_hash_ref=str(row["source_hash_ref"]),
        packet_safe_hash=str(row["packet_safe_hash"]),
    )
    _begin_retry_accepting(db_path, row=row)
    slug = f"{_slug(str(row['sample_id']))}-{_slug(safe_review_file.stem)[-24:]}"
    try:
        report = acceptance.accept_deep_review_candidates(
            db_path=Path(memory_db_path),
            json_output=accept_dir / f"{slug}-acceptance.json",
            md_output=accept_dir / f"{slug}-acceptance.md",
            review_file=safe_review_file,
            version_context=version_context,
            source_skill_manifest=source_skill_manifest,
            review_payload=review_payload,
            require_deep_records=True,
        )
    except Exception:
        _finish_retry_accepting_after_exception(db_path, row=row)
        raise
    accepted = str(report.get("status") or "") == "accepted"
    status = "accepted" if accepted else "acceptance_rejected"
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE cases
               SET status = ?,
                   accepted_at = ?,
                   updated_at = ?,
                   lease_token = NULL,
                   lease_owner = NULL,
                   lease_expires_at = NULL,
                   acceptance_status = ?,
                   accepted_pattern_count = ?,
                   accepted_deep_record_count = ?,
                   unresolved_deep_record_component_count = ?,
                   research_quality_summary = ?,
                   deferred_candidate_count = ?
             WHERE sample_id = ?
               AND status = 'accepting'
               AND packet_safe_hash = ?
            """,
            (
                status,
                _now_iso() if accepted else "",
                _now_iso(),
                str(report.get("status") or ""),
                int(report.get("acceptedPatternCount") or 0),
                int(report.get("acceptedDeepRecordCount") or 0),
                int(report.get("unresolvedDeepRecordComponentCount") or 0),
                json.dumps(_research_quality_summary(report), ensure_ascii=False, sort_keys=True),
                int(report.get("deferredCandidateCount") or 0),
                str(row["sample_id"]),
                str(row["packet_safe_hash"]),
            ),
        )
        conn.commit()
    if cur.rowcount != 1:
        raise ValueError("rejected case was modified before retry accept could be committed")
    result = {
        "status": status,
        "sampleId": str(row["sample_id"]),
        "packetSafeHash": str(row["packet_safe_hash"]),
        "acceptedPatternCount": int(report.get("acceptedPatternCount") or 0),
        "acceptedDeepRecordCount": int(report.get("acceptedDeepRecordCount") or 0),
        "createdDeepRecordCount": int(report.get("createdDeepRecordCount") or 0),
        "updatedDeepRecordCount": int(report.get("updatedDeepRecordCount") or 0),
        "addedDeepRecordEvidenceCount": int(report.get("addedDeepRecordEvidenceCount") or 0),
        "acceptedBuildFamilyKeys": report.get("acceptedBuildFamilyKeys") or [],
        "unresolvedDeepRecordComponentCount": int(
            report.get("unresolvedDeepRecordComponentCount") or 0
        ),
        "deepRecordsWithUnresolvedComponents": report.get("deepRecordsWithUnresolvedComponents")
        or [],
        **_research_quality_summary(report),
        "deferredCandidateCount": int(report.get("deferredCandidateCount") or 0),
        "deferredReasonCounts": report.get("deferredReasonCounts") or {},
        "patternWrite": report.get("patternWrite") or {},
        "deepRecordWrite": report.get("deepRecordWrite") or {},
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_payload(result)
    return result


def _begin_accepting(db_path: Path, *, row: sqlite3.Row, lease_token: str) -> None:
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE cases
               SET status = 'accepting',
                   updated_at = ?
             WHERE sample_id = ?
               AND status = 'claimed'
               AND lease_token = ?
               AND lease_expires_at > ?
               AND packet_safe_hash = ?
            """,
            (
                now,
                str(row["sample_id"]),
                lease_token,
                now,
                str(row["packet_safe_hash"]),
            ),
        )
        conn.commit()
    if cur.rowcount != 1:
        raise ValueError("lease is invalid, expired, or already accepting")


def _case_for_rejected_sample(db_path: Path, sample_id: str) -> sqlite3.Row:
    _init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
              FROM cases
             WHERE sample_id = ?
               AND status = 'acceptance_rejected'
            """,
            (sample_id,),
        ).fetchone()
    if row is None:
        raise ValueError("sample is not in acceptance_rejected state")
    return row


def _begin_retry_accepting(db_path: Path, *, row: sqlite3.Row) -> None:
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE cases
               SET status = 'accepting',
                   updated_at = ?
             WHERE sample_id = ?
               AND status = 'acceptance_rejected'
               AND packet_safe_hash = ?
            """,
            (
                now,
                str(row["sample_id"]),
                str(row["packet_safe_hash"]),
            ),
        )
        conn.commit()
    if cur.rowcount != 1:
        raise ValueError("sample is no longer in acceptance_rejected state")


def _finish_accepting_after_exception(
    db_path: Path,
    *,
    row: sqlite3.Row,
    lease_token: str,
) -> None:
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE cases
               SET status = 'claimed',
                   updated_at = ?
             WHERE sample_id = ?
               AND status = 'accepting'
               AND lease_token = ?
               AND packet_safe_hash = ?
            """,
            (
                now,
                str(row["sample_id"]),
                lease_token,
                str(row["packet_safe_hash"]),
            ),
        )
        conn.commit()


def _finish_retry_accepting_after_exception(
    db_path: Path,
    *,
    row: sqlite3.Row,
) -> None:
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE cases
               SET status = 'acceptance_rejected',
                   updated_at = ?
             WHERE sample_id = ?
               AND status = 'accepting'
               AND packet_safe_hash = ?
            """,
            (
                now,
                str(row["sample_id"]),
                str(row["packet_safe_hash"]),
            ),
        )
        conn.commit()


def queue_status(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    status_override: str | None = None,
    inserted_count: int | None = None,
    duplicate_count: int | None = None,
) -> dict[str, Any]:
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    _init_db(db_path)
    metadata = _read_metadata(db_path)
    rows = _fetch_cases(db_path)
    local_source_input_count = int(metadata.get("localSourceInputCount") or 0)
    requested_sample_count = int(
        metadata.get("requestedSampleCount")
        or (local_source_input_count if local_source_input_count > 0 else metadata.get("limit"))
        or 0
    )
    persisted_status = metadata.get("queueStatus") or ""
    if (
        not persisted_status
        and metadata.get("updatedAt")
        and requested_sample_count > 0
        and not any(str(row.get("status") or "") != "import_failed" for row in rows)
    ):
        persisted_status = "source_unavailable"
    source_input_summary = {
        "sourceFileArgumentCount": int(metadata.get("sourceFileArgumentCount") or 0),
        "sourceBatchFileArgumentCount": int(metadata.get("sourceBatchFileArgumentCount") or 0),
        "localSourceInputCount": local_source_input_count,
        "requestedSampleCount": requested_sample_count,
        "expectedSourceCount": (
            int(metadata["expectedSourceCount"]) if metadata.get("expectedSourceCount") else None
        ),
        "uniqueLocalCaseCount": int(metadata.get("uniqueLocalCaseCount") or 0),
        "duplicateLocalSourceCount": int(metadata.get("duplicateLocalSourceCount") or 0),
    }
    return _queue_report(
        status=status_override or persisted_status or "ok",
        db_path=db_path,
        requested_worker_count=int(metadata.get("requestedWorkerCount") or 1),
        cases=rows,
        inserted_count=inserted_count,
        duplicate_count=duplicate_count,
        dry_run=False,
        source_input_summary=source_input_summary,
    )


def _init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_hash TEXT NOT NULL UNIQUE,
                source_hash_ref TEXT NOT NULL,
                league TEXT NOT NULL,
                level INTEGER NOT NULL,
                class_name TEXT NOT NULL,
                ascendancy TEXT NOT NULL,
                main_skill TEXT NOT NULL,
                safe_error TEXT NOT NULL,
                packet_id TEXT NOT NULL,
                packet_safe_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                lease_token TEXT,
                lease_owner TEXT,
                lease_expires_at TEXT,
                accepted_at TEXT,
                acceptance_status TEXT,
                accepted_pattern_count INTEGER NOT NULL DEFAULT 0,
                accepted_deep_record_count INTEGER NOT NULL DEFAULT 0,
                unresolved_deep_record_component_count INTEGER NOT NULL DEFAULT 0,
                research_quality_summary TEXT NOT NULL DEFAULT '{}',
                deferred_candidate_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_cases_status_lease
                ON cases(status, lease_expires_at, id);
            """
        )
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(cases)")}
        if "accepted_deep_record_count" not in columns:
            conn.execute(
                "ALTER TABLE cases ADD COLUMN accepted_deep_record_count INTEGER NOT NULL DEFAULT 0"
            )
        if "unresolved_deep_record_component_count" not in columns:
            conn.execute(
                "ALTER TABLE cases ADD COLUMN unresolved_deep_record_component_count "
                "INTEGER NOT NULL DEFAULT 0"
            )
        if "research_quality_summary" not in columns:
            conn.execute(
                "ALTER TABLE cases ADD COLUMN research_quality_summary TEXT NOT NULL DEFAULT '{}'"
            )
        conn.commit()


def _write_metadata(db_path: Path, values: dict[str, str]) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO metadata(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            [(str(key), str(value)) for key, value in values.items()],
        )
        conn.commit()


def _read_metadata(db_path: Path) -> dict[str, str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM metadata").fetchall()
    return {str(key): str(value) for key, value in rows}


def _insert_case_if_absent(db_path: Path, row: dict[str, Any]) -> bool:
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO cases(
                sample_id, status, source_type, source_hash, source_hash_ref,
                league, level, class_name, ascendancy, main_skill, safe_error,
                packet_id, packet_safe_hash, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["sampleId"],
                row["status"],
                row["sourceType"],
                row["sourceHash"],
                row["sourceHashRef"],
                row["league"],
                int(row["level"]),
                row["className"],
                row["ascendancy"],
                row["mainSkill"],
                row["safeError"],
                row["packetId"],
                row["packetSafeHash"],
                now,
                now,
            ),
        )
        conn.commit()
    return cur.rowcount == 1


def _fetch_cases(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM cases ORDER BY id ASC").fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            quality_summary = json.loads(str(row["research_quality_summary"] or "{}"))
        except json.JSONDecodeError:
            quality_summary = {}
        out.append(
            {
                "sampleId": str(row["sample_id"]),
                "status": str(row["status"]),
                "sourceType": str(row["source_type"]),
                "sourceHash": str(row["source_hash"]),
                "sourceHashRef": str(row["source_hash_ref"]),
                "league": str(row["league"]),
                "level": int(row["level"] or 0),
                "className": str(row["class_name"]),
                "ascendancy": str(row["ascendancy"]),
                "mainSkill": str(row["main_skill"]),
                "mainSkillAuthority": "programmatic_snapshot_non_authoritative",
                "safeError": str(row["safe_error"]),
                "packetId": str(row["packet_id"]),
                "packetSafeHash": str(row["packet_safe_hash"]),
                "leaseExpiresAt": str(row["lease_expires_at"] or ""),
                "acceptedAt": str(row["accepted_at"] or ""),
                "acceptanceStatus": str(row["acceptance_status"] or ""),
                "acceptedPatternCount": int(row["accepted_pattern_count"] or 0),
                "acceptedDeepRecordCount": int(row["accepted_deep_record_count"] or 0),
                "unresolvedDeepRecordComponentCount": int(
                    row["unresolved_deep_record_component_count"] or 0
                ),
                **quality_summary,
                "deferredCandidateCount": int(row["deferred_candidate_count"] or 0),
            }
        )
    return out


def _case_for_valid_lease(db_path: Path, lease_token: str) -> sqlite3.Row:
    _init_db(db_path)
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
              FROM cases
             WHERE lease_token = ?
               AND status = 'claimed'
               AND lease_expires_at > ?
            """,
            (lease_token, now),
        ).fetchone()
    if row is None:
        raise ValueError("lease is invalid, expired, or no longer claimed")
    return row


def _prepare_packet(
    case: dict[str, Any],
    *,
    temp_root: Path,
    ttl_seconds: int,
    current_patch: str,
    passive_tree_version: str,
    pob_version_or_commit: str,
) -> dict[str, str]:
    packet_case = {
        "safeMetadata": {
            "case_id": case["sampleId"],
            "sourceType": case["sourceType"],
            "sourceRef": case["sourceHashRef"],
            "sourceHash": case["sourceHash"],
            "league": case.get("league") or "unknown",
            "class": case.get("className") or "",
            "ascendancy": case.get("ascendancy") or "",
            "level": str(case.get("level") or ""),
            "mainSkill": case.get("mainSkill") or "",
            "mainSkillAuthority": "programmatic_snapshot_non_authoritative",
            "gamePatch": current_patch,
            "passiveTreeVersion": passive_tree_version,
            "pobVersionOrCommit": pob_version_or_commit,
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledgeScope": "global_seed",
            "evidenceType": case["sourceType"],
            "freshnessStatus": "current_metadata_only"
            if case["sourceType"] == "poe_ninja_import_code"
            else "unknown",
            "compatibilityStatus": "unknown",
        },
        "rawContext": {
            "rawImportCode": case["_rawImportCode"],
            "rawXml": case["_rawXml"],
            "programmaticDiagnostics": {
                "authority": "non_authoritative",
                "rawImportedMainSkill": case.get("mainSkill") or "",
                "judgeProbeStatus": "not_run",
                "judgeSelectedSkillCandidate": "",
                "selectionCaveats": [
                    "Programmatic diagnostics are snapshot-trap warnings, not ground truth."
                ],
            },
            "sourcePayload": {
                "kind": case["sourceType"],
                "sourceHash": case["sourceHash"],
            },
        },
    }
    result = research_packet.build_research_packet(
        packet_case,
        persist_for_transport=True,
        ttl_seconds=ttl_seconds,
        temp_root=temp_root,
    )
    packet = result["packet"]
    return {"packetId": str(packet["packetId"]), "packetSafeHash": str(packet["safeHash"])}


def _load_packet_by_safe_hash(temp_root: Path, packet_safe_hash: str) -> dict[str, Any]:
    research_packet.cleanup_expired_packets(temp_root=temp_root)
    for packet_path in temp_root.glob(f"{research_packet.PACKET_PREFIX}*/packet.json"):
        try:
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(packet.get("safeHash")) == str(packet_safe_hash):
            return packet
    raise FileNotFoundError("transient packet not found; recreate the queue or reclaim the case")


def _packet_for_valid_lease(
    *,
    row: sqlite3.Row,
    output_dir: Path,
    temp_root: str | Path | None,
) -> dict[str, Any]:
    root = _effective_temp_root(temp_root, output_root=output_dir)
    return _load_packet_by_safe_hash(root, str(row["packet_safe_hash"]))


def _optional_acceptance_skill_manifest(
    *,
    row: sqlite3.Row,
    output_root: Path,
    temp_root: str | Path | None,
) -> dict[str, Any] | None:
    try:
        packet = _packet_for_valid_lease(
            row=row,
            output_dir=output_root,
            temp_root=temp_root,
        )
    except FileNotFoundError:
        return None
    return research_packet.build_skill_evidence_manifest(packet)


def _safe_case_row_from_case(
    case: dict[str, Any],
    *,
    packet_id: str = "",
    packet_safe_hash: str = "",
) -> dict[str, Any]:
    return {
        "sampleId": legacy_batch._safe_text(case.get("sampleId")),
        "status": "queued"
        if case.get("status") == "pending"
        else legacy_batch._safe_text(case.get("status")),
        "sourceType": legacy_batch._safe_text(case.get("sourceType")),
        "sourceHash": legacy_batch._safe_text(case.get("sourceHash")),
        "sourceHashRef": legacy_batch._safe_text(case.get("sourceHashRef")),
        "league": legacy_batch._safe_text(case.get("league")),
        "level": int(case.get("level") or 0),
        "className": legacy_batch._safe_text(case.get("className")),
        "ascendancy": legacy_batch._safe_text(case.get("ascendancy")),
        "mainSkill": legacy_batch._safe_text(case.get("mainSkill")),
        "mainSkillAuthority": "programmatic_snapshot_non_authoritative",
        "safeError": legacy_batch._safe_text(case.get("safeError")),
        "packetId": legacy_batch._safe_text(packet_id),
        "packetSafeHash": legacy_batch._safe_text(packet_safe_hash),
    }


def _queue_report(
    *,
    status: str,
    db_path: Path,
    requested_worker_count: int,
    cases: list[dict[str, Any]],
    dry_run: bool,
    inserted_count: int | None = None,
    duplicate_count: int | None = None,
    source_input_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for case in cases:
        counts[str(case.get("status") or "")] = counts.get(str(case.get("status") or ""), 0) + 1
    samples = [_safe_sample_for_report(case) for case in cases]
    source_input_summary = dict(source_input_summary or {})
    requested_sample_count = int(source_input_summary.get("requestedSampleCount") or 0)
    unavailable_count = counts.get("import_failed", 0)
    available_sample_count = max(0, len(samples) - unavailable_count)
    report = {
        "reportId": "poe-bd-research-queue-v1",
        "status": status,
        "safeArtifactOnly": True,
        "queueKind": "poe_bd_research_external_agent_queue",
        "queueDb": db_path.name,
        "sampleCount": len(samples),
        "requestedSampleCount": requested_sample_count,
        "availableSampleCount": available_sample_count,
        "sampleShortfallCount": max(0, requested_sample_count - available_sample_count),
        "queuedCount": counts.get("queued", 0),
        "claimedCount": counts.get("claimed", 0),
        "acceptedCount": counts.get("accepted", 0),
        "rejectedCount": counts.get("acceptance_rejected", 0),
        "importFailedCount": counts.get("import_failed", 0),
        "requestedWorkerCount": 1,
        "workerCountSemantics": "serial_one_case_at_a_time",
        "workerReusePolicy": "fresh_lease_bound_sections_per_case_no_evidence_reuse",
        "insertedCount": inserted_count,
        "duplicateCount": duplicate_count,
        "sourceFileArgumentCount": int(source_input_summary.get("sourceFileArgumentCount") or 0),
        "sourceBatchFileArgumentCount": int(
            source_input_summary.get("sourceBatchFileArgumentCount") or 0
        ),
        "localSourceInputCount": int(source_input_summary.get("localSourceInputCount") or 0),
        "expectedSourceCount": source_input_summary.get("expectedSourceCount"),
        "uniqueLocalCaseCount": int(source_input_summary.get("uniqueLocalCaseCount") or 0),
        "duplicateLocalSourceCount": int(
            source_input_summary.get("duplicateLocalSourceCount") or 0
        ),
        "samples": samples,
        "dryRun": bool(dry_run),
        "noRawMatureBuildMaterial": True,
        "caveats": [
            "The queue stores only safe metadata, leases, and packet safe hashes.",
            "Raw mature build material exists only in transient OS temp packets.",
            "Use inspect/read/search from the active lease to read bounded structured evidence.",
            "This script does not call any OpenAI, Claude, Gemini, or other model provider API.",
        ],
    }
    if status == "source_unavailable":
        report.update(
            {
                "errorKind": "source_unavailable",
                "queueCreated": not dry_run,
                "safeError": "no usable mature build samples matched the requested source and filters",
                "nextStep": (
                    "Report that the source is unavailable for the requested selection. "
                    "Do not claim or accept a case from this queue."
                ),
            }
        )
    return report


def _source_input_count_mismatch_report(
    *,
    expected_source_count: int,
    source_input_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "reportId": "poe-bd-research-queue-v1",
        "status": "source_input_count_mismatch",
        "safeArtifactOnly": True,
        "queueCreated": False,
        "expectedSourceCount": expected_source_count,
        "localSourceInputCount": int(source_input_summary["localSourceInputCount"]),
        "sourceFileArgumentCount": int(source_input_summary["sourceFileArgumentCount"]),
        "sourceBatchFileArgumentCount": int(source_input_summary["sourceBatchFileArgumentCount"]),
        "safeError": "local source count does not match --expected-source-count",
        "nextStep": (
            "Pass every intended --source-file/--source-batch-file input in one queue command, "
            "then retry with the same expected count."
        ),
        "noRawMatureBuildMaterial": True,
    }


def _safe_sample_for_report(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "sampleId": legacy_batch._safe_text(case.get("sampleId")),
        "status": legacy_batch._safe_text(case.get("status")),
        "sourceType": legacy_batch._safe_text(case.get("sourceType")),
        "sourceHashRef": legacy_batch._safe_text(case.get("sourceHashRef")),
        "packetSafeHash": legacy_batch._safe_text(case.get("packetSafeHash")),
        "className": legacy_batch._safe_text(case.get("className")),
        "ascendancy": legacy_batch._safe_text(case.get("ascendancy")),
        "level": int(case.get("level") or 0),
        "mainSkill": legacy_batch._safe_text(case.get("mainSkill")),
        "mainSkillAuthority": "programmatic_snapshot_non_authoritative",
        "safeError": legacy_batch._safe_text(case.get("safeError")),
        "leaseExpiresAt": legacy_batch._safe_text(case.get("leaseExpiresAt")),
        "acceptedAt": legacy_batch._safe_text(case.get("acceptedAt")),
        "acceptanceStatus": legacy_batch._safe_text(case.get("acceptanceStatus")),
        "acceptanceMode": legacy_batch._safe_text(case.get("acceptanceMode")),
        "acceptedPatternCount": int(case.get("acceptedPatternCount") or 0),
        "acceptedDeepRecordCount": int(case.get("acceptedDeepRecordCount") or 0),
        "createdDeepRecordCount": int(case.get("createdDeepRecordCount") or 0),
        "updatedDeepRecordCount": int(case.get("updatedDeepRecordCount") or 0),
        "addedDeepRecordEvidenceCount": int(case.get("addedDeepRecordEvidenceCount") or 0),
        "createdBuildFamilyCount": int(case.get("createdBuildFamilyCount") or 0),
        "addedBuildFamilyEvidenceCount": int(case.get("addedBuildFamilyEvidenceCount") or 0),
        "acceptedBuildFamilyKeys": case.get("acceptedBuildFamilyKeys") or [],
        "unresolvedDeepRecordComponentCount": int(
            case.get("unresolvedDeepRecordComponentCount") or 0
        ),
        "unresolvedDeepRecordMentionCount": int(
            case.get("unresolvedDeepRecordMentionCount")
            or case.get("unresolvedDeepRecordComponentCount")
            or 0
        ),
        "unresolvedUniqueComponentCount": int(case.get("unresolvedUniqueComponentCount") or 0),
        "unkeyedDeepRecordCount": int(case.get("unkeyedDeepRecordCount") or 0),
        "recordKindCounts": case.get("recordKindCounts") or {},
        "caseCoverage": case.get("caseCoverage") or {},
        "caseCoverageGapCount": int(case.get("caseCoverageGapCount") or 0),
        "caseCoverageGaps": case.get("caseCoverageGaps") or [],
        "singleComponentObservationCount": int(case.get("singleComponentObservationCount") or 0),
        "acceptedTransferCandidateCount": int(case.get("acceptedTransferCandidateCount") or 0),
        "promotedTransferPatternCount": int(case.get("promotedTransferPatternCount") or 0),
        "promotedTransferPatternIds": case.get("promotedTransferPatternIds") or [],
        "recordKindAdvisories": case.get("recordKindAdvisories") or [],
        "deferredCandidateCount": int(case.get("deferredCandidateCount") or 0),
    }


def _research_quality_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "acceptanceMode": legacy_batch._safe_text(report.get("acceptanceMode")),
        "createdDeepRecordCount": int(report.get("createdDeepRecordCount") or 0),
        "updatedDeepRecordCount": int(report.get("updatedDeepRecordCount") or 0),
        "addedDeepRecordEvidenceCount": int(report.get("addedDeepRecordEvidenceCount") or 0),
        "createdBuildFamilyCount": int(report.get("createdBuildFamilyCount") or 0),
        "addedBuildFamilyEvidenceCount": int(report.get("addedBuildFamilyEvidenceCount") or 0),
        "acceptedBuildFamilyKeys": report.get("acceptedBuildFamilyKeys") or [],
        "recordKindCounts": report.get("recordKindCounts") or {},
        "caseCoverage": report.get("caseCoverage") or {},
        "caseCoverageGapCount": int(report.get("caseCoverageGapCount") or 0),
        "caseCoverageGaps": report.get("caseCoverageGaps") or [],
        "singleComponentObservationCount": int(report.get("singleComponentObservationCount") or 0),
        "acceptedTransferCandidateCount": int(report.get("acceptedTransferCandidateCount") or 0),
        "promotedTransferPatternCount": int(report.get("promotedTransferPatternCount") or 0),
        "promotedTransferPatternIds": report.get("promotedTransferPatternIds") or [],
        "recordKindAdvisories": report.get("recordKindAdvisories") or [],
        "sourceEvidenceDiagnostics": report.get("sourceEvidenceDiagnostics") or {},
        "mechanicAudit": report.get("mechanicAudit") or {},
        "mechanicAuditEntryCount": int(report.get("mechanicAuditEntryCount") or 0),
        "mechanicAuditSchemaIssueCount": int(report.get("mechanicAuditSchemaIssueCount") or 0),
        "mechanicAuditPinnedRevisionCount": int(
            report.get("mechanicAuditPinnedRevisionCount") or 0
        ),
        "mechanicAuditLiveEvidenceStatus": legacy_batch._safe_text(
            report.get("mechanicAuditLiveEvidenceStatus")
        ),
        "mechanicAuditUnauditedHighRiskRecordCount": int(
            report.get("mechanicAuditUnauditedHighRiskRecordCount") or 0
        ),
        "mechanicAuditAdvisories": report.get("mechanicAuditAdvisories") or [],
        "unresolvedDeepRecordMentionCount": int(
            report.get("unresolvedDeepRecordMentionCount")
            or report.get("unresolvedDeepRecordComponentCount")
            or 0
        ),
        "unresolvedUniqueComponentCount": int(report.get("unresolvedUniqueComponentCount") or 0),
        "unkeyedDeepRecordCount": int(report.get("unkeyedDeepRecordCount") or 0),
        "deepRecordsWithoutKnowledgeIdentity": report.get("deepRecordsWithoutKnowledgeIdentity")
        or [],
    }


def _validation_only_result(report: dict[str, Any], *, sample_id: str) -> dict[str, Any]:
    deferred_reason_counts = dict(report.get("deferredReasonCounts") or {})
    schema_issue_count = int(deferred_reason_counts.get("invalid_schema") or 0)
    validation_issues: list[dict[str, Any]] = []
    for deferred in report.get("deferredCandidates") or []:
        validation_issues.extend(list(deferred.get("validationIssues") or []))
    for key in ("patternWrite", "deepRecordWrite"):
        write_result = report.get(key) or {}
        if write_result.get("errorCode") == "invalid_schema":
            schema_issue_count += 1
            validation_issues.extend(
                list((write_result.get("facts") or {}).get("validationIssues") or [])
            )
    ready = report.get("status") == "accepted" and schema_issue_count == 0
    deferred_candidate_count = int(report.get("deferredCandidateCount") or 0)
    unresolved_mention_count = int(
        report.get("unresolvedDeepRecordMentionCount")
        or report.get("unresolvedDeepRecordComponentCount")
        or 0
    )
    case_coverage_gap_count = int(report.get("caseCoverageGapCount") or 0)
    fully_resolved = (
        ready
        and deferred_candidate_count == 0
        and unresolved_mention_count == 0
        and case_coverage_gap_count == 0
    )
    acceptance_mode = "clean" if fully_resolved else "partial_with_deferred" if ready else "blocked"
    return {
        "status": "validation_passed" if ready else "validation_failed",
        "sampleId": sample_id,
        "readyForAccept": ready,
        "fullyResolvedForAccept": fully_resolved,
        "validationOnly": True,
        "durableWritePerformed": False,
        "queueStateChanged": False,
        "wouldAcceptPatternCount": int(report.get("acceptedPatternCount") or 0),
        "wouldAcceptDeepRecordCount": int(report.get("acceptedDeepRecordCount") or 0),
        "unresolvedDeepRecordComponentCount": int(
            report.get("unresolvedDeepRecordComponentCount") or 0
        ),
        "unresolvedDeepRecordMentionCount": unresolved_mention_count,
        "unresolvedUniqueComponentCount": int(report.get("unresolvedUniqueComponentCount") or 0),
        "unkeyedDeepRecordCount": int(report.get("unkeyedDeepRecordCount") or 0),
        "deepRecordsWithoutKnowledgeIdentity": report.get("deepRecordsWithoutKnowledgeIdentity")
        or [],
        "deepRecordsWithUnresolvedComponents": report.get("deepRecordsWithUnresolvedComponents")
        or [],
        **_research_quality_summary(report),
        "acceptanceMode": acceptance_mode,
        "schemaIssueCount": schema_issue_count,
        "validationIssues": validation_issues,
        "deferredCandidateCount": deferred_candidate_count,
        "deferredReasonCounts": deferred_reason_counts,
        "deferredCandidates": report.get("deferredCandidates") or [],
        "patternValidation": report.get("patternWrite") or {},
        "deepRecordValidation": report.get("deepRecordWrite") or {},
        "noRawMatureBuildMaterial": True,
    }


def _claim_payload(
    row: dict[str, Any],
    *,
    lease_token: str,
    output_root: Path,
) -> dict[str, Any]:
    sample_id = str(row["sample_id"])
    review_file = _suggested_review_file(
        output_dir=output_root,
        sample_id=sample_id,
        lease_token=lease_token,
    )
    worker_prompt = _worker_brief_text(
        row,
        lease_token=lease_token,
        review_file=review_file,
    )
    return {
        "status": "claimed",
        "queueKind": "poe_bd_research_external_agent_queue",
        "sampleId": sample_id,
        "sourceType": str(row["source_type"]),
        "sourceHashRef": str(row["source_hash_ref"]),
        "packetId": str(row["packet_id"]),
        "packetSafeHash": str(row["packet_safe_hash"]),
        "className": str(row["class_name"]),
        "ascendancy": str(row["ascendancy"]),
        "level": int(row["level"] or 0),
        "mainSkill": str(row["main_skill"]),
        "mainSkillAuthority": "programmatic_snapshot_non_authoritative",
        "leaseToken": lease_token,
        "leaseExpiresAt": str(row["lease_expires_at"]),
        "reviewFile": review_file,
        "workerPrompt": worker_prompt,
        "noRawMatureBuildMaterial": True,
    }


def _suggested_review_file(
    *,
    output_dir: Path,
    sample_id: str,
    lease_token: str,
) -> str:
    lease_ref = _slug(lease_token)[:12]
    return (Path("reviews") / f"{_slug(sample_id)}-{lease_ref}-safe-review.json").as_posix()


def _assert_review_file_for_lease(
    *,
    review_file: Path,
    output_root: Path,
    sample_id: str,
    lease_token: str,
    source_hash_ref: str,
    packet_safe_hash: str,
) -> dict[str, Any]:
    resolved = review_file.resolve()
    reviews_root = (output_root / "reviews").resolve()
    try:
        resolved.relative_to(reviews_root)
    except ValueError:
        raise ValueError("review file does not belong to the current lease")
    sample_prefix = f"{_slug(sample_id)}-"
    safe_suffix = "-safe-review.json"
    if not resolved.name.startswith(sample_prefix) or not resolved.name.endswith(safe_suffix):
        raise ValueError("review file does not belong to the current lease")
    lease_ref = resolved.name[len(sample_prefix) : -len(safe_suffix)]
    normalized_lease = _slug(lease_token)
    if len(lease_ref) < 12 or not normalized_lease.startswith(lease_ref):
        raise ValueError("review file does not belong to the current lease")
    return _canonical_review_artifact_identity(
        review_file=resolved,
        sample_id=sample_id,
        source_hash_ref=source_hash_ref,
        packet_safe_hash=packet_safe_hash,
    )


def _canonical_review_artifact_identity(
    *,
    review_file: Path,
    sample_id: str,
    source_hash_ref: str,
    packet_safe_hash: str,
) -> dict[str, Any]:
    payload = json.loads(review_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("safeArtifactOnly") is not True:
        raise ValueError("review artifact identity does not match the current lease")
    entries = [
        item
        for key in ("deepResearchRecords", "candidateReviews")
        for item in payload.get(key) or []
        if isinstance(item, dict)
    ]
    expected_evidence_ref = f"evidence:{packet_safe_hash[:16]}"
    artifact_identity = payload.get("artifactIdentity")
    if artifact_identity is not None:
        expected_identity = {
            "sampleId": sample_id,
            "caseRef": source_hash_ref,
            "safeEvidenceRef": expected_evidence_ref,
            "packetSafeHash": packet_safe_hash,
        }
        if not isinstance(artifact_identity, dict) or any(
            str(artifact_identity.get(key) or "") != value
            for key, value in expected_identity.items()
        ):
            raise ValueError("review artifactIdentity does not match the current lease")
    elif not entries or any(
        str(item.get("caseRef") or "") != source_hash_ref
        or expected_evidence_ref not in _review_evidence_refs(item)
        for item in entries
    ):
        raise ValueError("review artifact identity does not match the current lease")
    if not entries:
        raise ValueError("review artifact must contain at least one record or candidate")

    canonical = copy.deepcopy(payload)
    canonical["artifactIdentity"] = {
        "sampleId": sample_id,
        "caseRef": source_hash_ref,
        "safeEvidenceRef": expected_evidence_ref,
        "packetSafeHash": packet_safe_hash,
    }
    for key in ("deepResearchRecords", "candidateReviews"):
        for item in canonical.get(key) or []:
            if not isinstance(item, dict):
                continue
            item["sampleId"] = sample_id
            item["caseRef"] = source_hash_ref
            item["safeEvidenceRef"] = expected_evidence_ref
    for item in canonical.get("deepResearchRecords") or []:
        if isinstance(item, dict):
            item["researchGroupId"] = f"research:{sample_id}"
    return canonical


def _lease_artifact_identity(row: sqlite3.Row) -> dict[str, str]:
    packet_safe_hash = str(row["packet_safe_hash"])
    return {
        "sampleId": str(row["sample_id"]),
        "caseRef": str(row["source_hash_ref"]),
        "safeEvidenceRef": f"evidence:{packet_safe_hash[:16]}",
        "packetSafeHash": packet_safe_hash,
    }


def _review_evidence_refs(item: dict[str, Any]) -> list[str]:
    plural = item.get("safeEvidenceRefs") or []
    if not isinstance(plural, list):
        return []
    return sorted(
        {
            str(value).strip()
            for value in [item.get("safeEvidenceRef"), *plural]
            if str(value or "").strip()
        }
    )


def _resolve_review_file(review_file: Path, *, output_root: Path) -> Path:
    if review_file.is_absolute():
        return review_file
    candidates = [Path.cwd() / review_file, output_root / review_file]
    if review_file.parent == Path("."):
        candidates.append(output_root / "reviews" / review_file.name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[1]


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _worker_brief_text(row: sqlite3.Row, *, lease_token: str, review_file: str) -> str:
    sample_id = str(row["sample_id"])
    source_type = str(row["source_type"])
    source_hash_ref = str(row["source_hash_ref"])
    packet_safe_hash = str(row["packet_safe_hash"])
    class_name = str(row["class_name"])
    ascendancy = str(row["ascendancy"])
    level = int(row["level"] or 0)
    main_skill = str(row["main_skill"] or "")
    return f"""你正在执行 PoE2 mature build Researcher 流程，只负责当前 leased case。
这是当前案例的安全导航 brief。

## Runtime Boundary
- 这是产品运行态，不要修改源码、测试、文档、schema 或安装配置。
- 禁止使用 subagent，不要转交给其他 agent；当前案例正式 accept 前不得领取下一案。
- 所有后续脚本命令都必须携带最初 queue 返回的 `--output-dir <runDir>`，不得使用默认共享目录。
- 不要读源码或临时构造 service 绕过 MCP、lease 或 acceptance 边界。
- 原始 PoB/XML 只能留在 transient packet，不得写入聊天、safe review 或 durable memory。
- 最终只报告 safe artifact、验收状态和安全错误。

## Case
- sampleId: {sample_id}
- leaseToken: {lease_token}
- sourceType/sourceRef: {source_type} / {source_hash_ref}
- class/ascendancy/level: {class_name} / {ascendancy} / {level}
- programmatic mainSkill candidate: {main_skill or "unknown"}（非权威快照线索）
- packetSafeHash: {packet_safe_hash}
- safeReviewFile: {review_file}（相对当前 --output-dir）

## Evidence First
先运行 inspect，再按 skills、gear、passives、config、build 顺序把每个分区分页读完；complete=false
时继续使用 nextCursor。search 只能定位具体线索，不能替代完整分区读取。
技能、天赋和装备效果必须来自当前案例证据或工具事实；允许保留有价值的推断，但必须明确标为推断，
不能把模型记忆中的免疫、转换、触发或缩放效果写成已证实事实。

独立重建当前案例后，再调用 query_research_memory 查重和对照；随后用
search_graph_components 发现具体组件候选、用 resolve_graph_component 确认稳定 ID。工具未直接
显示时，使用宿主标准 tool discovery / tool search 按精确名称查找；工具可能采用延迟发现，不要根据
首屏工具列表断言不可用。

独立重建和组件解析完成后，针对会改变因果链的高风险结论做一轮轻量机制校对：先用
explain_mechanic / search_mechanics 查看当前本地静态机制资料，再用 lookup_mechanic 查询实时
poe2wiki。重点检查触发与手动施放、前置状态、资源生成/消耗、伤害转换、mutation/transform 等；
不要为普通组件名称逐个查 Wiki。每次只查询一个精确页面或中央机制名称，不得拼接 `A / B`；需要多页
时写多条原子审计。每条 mechanic_chain 和 resource_engine 都必须由 mechanicAudit 精确引用，claim
必须写对象真正依赖的最强因果结论，不能只审计较弱前提。把复核结果写入顶层 mechanicAudit，并使用
lookup_mechanic 返回的 revision-pinned sourceRef。Wiki 只作校对证据，不能替代来源实例归属、support
兼容性、武器状态、Family 身份或数值 Judge；每项结论仍需注明 source artifact、PoB static、typed
graph 等独立佐证。

## Research Goal
重建并分别记录：
- 主/副伤害技能、supports、触发或生成-兑现关系；
- 可执行轮转、爆发窗口和无小怪/Boss 变体；
- 装备槽职责、暗金必要性、可替代黄装与机会成本；
- 核心天赋、升华、珠宝和武器组局部结构；
- 资源闭环、防御层、失效条件和 PoB/Judge 不可建模部分。

不要只复述属性共现或“仍需验证”。一次案例应形成多条聚焦 DeepResearchRecord，每条只回答一个
主要问题；多个组件共同构成核心机制时应完整保留该机制包。

分析候选 Pattern 时，区分 Family 内事实和跨 Family 可迁移机制。只有当一条候选解决可重复出现的
设计问题、包含明确因果链，并能写出最低适用条件、排除条件和验证任务时，才标记
transferScope=component；移除当前职业/升华/流派名称后仍应有意义。单案例不得标记 global，也不要
为了数量强行制造迁移候选。首次发现始终只是 case_observation，后端只会依据独立跨 Family 证据晋升。

## Write And Validate
完成分析后调用 review-contract --output-dir <runDir> --lease-token {lease_token}，在写入前即时获取精确 JSON 结构、
canonical role/axis/pattern 枚举和模板。不得自造枚举；更细的窗口、轮转或证据语义写入 content、
typedPayload、conditions 或 summary。role 表达 BD 功能，物理节点类型由 resolver 证明；已经唯一解析的
组件必须填写 resolver 返回的 componentKey。随后运行 init-review --output-dir <runDir> --lease-token {lease_token}，由程序
原子创建 UTF-8、两空格缩进的多行 JSON safe review 骨架。只编辑 safeReviewFile；不得用 PowerShell here-string、
内联 ConvertTo-Json 或 Set-Content 拼接整份 review，也不得借此修改源码或其他 artifact。

把候选编辑进 safeReviewFile。propose_* 只用于候选校验，不代表入库。写完后先运行：

  research_mature_builds.py accept --output-dir <runDir> --lease-token {lease_token} --review-file {review_file} --validate-only

若返回 validation_failed，按 validationIssues 自行修正并重新校验。readyForAccept=true 只表示安全子集
可以接收；fullyResolvedForAccept=true 才表示已有可归档的 Build Family，且没有覆盖缺口、候选暂缓
或深度记录组件缺口。对
component_type_mismatch、错误 role/query 和其他可修复问题先做一次有界修复；只有真实 source coverage
缺口或经复核仍无法唯一解析的内容才保留为 partial_with_deferred。validate-only 不写 durable memory，
也不改变当前 lease。
"""


def _normalize_sample_ids(cases: list[dict[str, Any]], *, sample_start_index: int) -> None:
    index = max(1, int(sample_start_index))
    for case in cases:
        source_hash = str(case.get("sourceHash") or "").strip()
        if source_hash:
            case["sampleId"] = f"case:poe-bd-research-{source_hash[:16]}"
        else:
            case["sampleId"] = f"case:poe-bd-research-{index:03d}"
        index += 1


def _queue_db_path(output_root: Path, queue_db_path: str | Path | None) -> Path:
    return Path(queue_db_path) if queue_db_path is not None else output_root / QUEUE_DB_FILENAME


def _allocate_run_output_dir(base_output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[str, Path]:
    runs_root = base_output_dir / RUNS_DIRNAME
    runs_root.mkdir(parents=True, exist_ok=True)
    timestamp = _now().astimezone().strftime("%Y%m%d-%H%M%S")
    for _ in range(20):
        run_id = f"{timestamp}-{secrets.token_hex(2)}"
        run_dir = runs_root / run_id
        try:
            run_dir.mkdir()
        except FileExistsError:
            continue
        return run_id, run_dir
    raise RuntimeError("could not allocate a unique research run directory")


def _queue_cli_output_dir(args: argparse.Namespace) -> tuple[str | None, Path]:
    if args.output_dir:
        output_dir = Path(args.output_dir)
        return None, output_dir
    if args.resume:
        raise ValueError("--resume requires the --output-dir returned by the original queue run")
    if args.dry_run:
        return None, DEFAULT_OUTPUT_DIR
    return _allocate_run_output_dir(DEFAULT_OUTPUT_DIR)


def _attach_run_location(report: dict[str, Any], *, run_id: str, run_dir: Path) -> None:
    display_dir = _display_path(run_dir)
    report.update({"runId": run_id, "runDir": display_dir})
    if report.get("status") not in {"source_input_count_mismatch", "source_unavailable"}:
        report["nextCommandArgs"] = {"outputDir": display_dir}
    _assert_safe_payload(report)


def _runtime_version_context(
    *,
    current_patch: str | None,
    passive_tree_version: str | None,
    pob_version_or_commit: str | None,
) -> dict[str, str]:
    explicit_pob_raw = _known_version(pob_version_or_commit)
    explicit_pob_version = freshness_providers.resolve_pob_version_enum(explicit_pob_raw)
    if explicit_pob_raw and explicit_pob_version is None:
        raise ValueError("unsupported application PoB version: " + explicit_pob_raw)
    explicit = {
        "gamePatch": _known_version(current_patch),
        "passiveTreeVersion": _known_version(passive_tree_version),
        "pobVersionOrCommit": explicit_pob_version or "",
    }
    local = _local_certified_version_context()
    context = {key: explicit[key] or local.get(key, "") for key in explicit}
    missing = [key for key, value in context.items() if not value]
    if missing:
        raise ValueError(
            "durable research requires certified patch, passive tree, and PoB versions; "
            f"missing: {', '.join(missing)}"
        )
    context["status"] = "certified_local_runtime"
    return context


def _local_certified_version_context() -> dict[str, str]:
    compatibility = freshness_providers.current_local_compatibility()
    if compatibility is None:
        return {}
    return {
        "gamePatch": compatibility.game_patch,
        "passiveTreeVersion": compatibility.passive_tree,
        "pobVersionOrCommit": compatibility.pob_version,
    }


def _queue_version_context(db_path: Path) -> dict[str, str]:
    metadata = _read_metadata(db_path)
    context = {
        "gamePatch": _known_version(metadata.get("currentPatch")),
        "passiveTreeVersion": _known_version(metadata.get("passiveTreeVersion")),
        "pobVersionOrCommit": _known_version(metadata.get("pobVersionOrCommit")),
        "status": _known_version(metadata.get("versionContextStatus")),
    }
    missing = [key for key, value in context.items() if not value]
    if missing:
        raise ValueError(
            "research queue lacks durable version context; recreate the queue after updating "
            f"the local certified runtime ({', '.join(missing)})"
        )
    return context


def _known_version(value: Any) -> str:
    normalized = str(value or "").strip()
    return "" if normalized.casefold() in {"", "unknown", "none", "null"} else normalized


def _effective_temp_root(temp_root: str | Path | None, *, output_root: Path) -> Path:
    root = (
        Path(temp_root)
        if temp_root is not None
        else Path(tempfile.gettempdir()) / DEFAULT_TEMP_DIRNAME
    )
    resolved_root = root.resolve()
    if _is_relative_to(resolved_root, output_root.resolve()):
        raise ValueError("temp_root must not be inside the durable output_dir")
    if _is_relative_to(resolved_root, REPO_ROOT.resolve()):
        raise ValueError("temp_root must not be inside the repository workspace")
    system_temp = Path(tempfile.gettempdir()).resolve()
    if not _is_relative_to(resolved_root, system_temp):
        raise ValueError("temp_root must be inside the operating system temporary directory")
    return resolved_root


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)[:120]


def _safe_short(value: str) -> str:
    return legacy_batch._safe_text(value)[:120]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _iso(_now())


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _assert_safe_payload(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe research queue markers detected: {', '.join(leaks)}")
    if copy_safety.find_forbidden_paths(payload):
        raise ValueError("unsafe research queue contains forbidden raw fields")
    flags: set[str] = set()
    for text in _human_text(payload):
        flags.update(copy_safety.copyability_flags(text))
    if flags:
        raise ValueError(f"unsafe research queue failed copy-safety: {sorted(flags)}")


def _assert_transient_view_payload(payload: dict[str, Any], *, enforce_size: bool = False) -> None:
    """Guard lease-bound structured evidence without applying durable-field restrictions."""
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe transient research markers detected: {', '.join(leaks)}")
    flags = set(copy_safety.copyability_flags(payload))
    forbidden_flags = {
        "raw_pob_xml_marker",
        "pob_code_like_blob",
        "copyable_build_link",
        "raw_account_or_character_url",
        "long_guide_prose_like",
    }
    if flags & forbidden_flags:
        raise ValueError(f"unsafe transient research payload: {sorted(flags & forbidden_flags)}")
    if enforce_size and len(serialized) > research_packet.MAX_RESPONSE_CHARS:
        raise ValueError("transient research response exceeds the bounded output limit")


def _human_text(value: Any, *, key: str = "") -> list[str]:
    scan_keys = {"caveats", "safeError", "nextWorkerStep"}
    if isinstance(value, dict):
        out: list[str] = []
        for child_key, child in value.items():
            out.extend(_human_text(child, key=str(child_key)))
        return out
    if isinstance(value, list):
        out = []
        for child in value:
            out.extend(_human_text(child, key=key))
        return out
    if isinstance(value, str) and key in scan_keys:
        return [value]
    return []


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _runtime_failure_payload(command: str | None, exc: Exception) -> dict[str, Any]:
    status = "collector_failed" if command == "queue" else "runtime_failed"
    safe_error = legacy_batch._safe_error(str(exc))
    flags = copy_safety.copyability_flags(safe_error)
    if flags:
        safe_error = "runtime error details redacted by copy-safety"
    payload = {
        "status": status,
        "errorKind": status,
        "command": legacy_batch._safe_text(command or "unknown"),
        "safeError": safe_error,
        "noRawMatureBuildMaterial": True,
        "safeArtifactOnly": True,
        "nextStep": (
            "Report this safe failure to the user. Do not patch repository source files while "
            "running the poe-bd-research product workflow."
        ),
    }
    _assert_safe_payload(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="poe-bd-research")
    subparsers = parser.add_subparsers(dest="command", required=True)

    queue_parser = subparsers.add_parser("queue")
    _add_queue_location_args(queue_parser, default_output_dir=None)
    queue_parser.add_argument("--limit", type=int, default=50)
    queue_parser.add_argument(
        "--worker-count",
        type=int,
        default=1,
        help="Deprecated compatibility option; research always runs one case at a time.",
    )
    queue_parser.add_argument("--league", default="current")
    queue_parser.add_argument("--level-min", type=int, default=90)
    queue_parser.add_argument("--level-max", type=int, default=100)
    queue_parser.add_argument("--ascendancy", action="append", default=[])
    queue_parser.add_argument("--class", dest="ninja_classes", action="append", default=[])
    queue_parser.add_argument("--source-file", action="append", default=[])
    queue_parser.add_argument("--source-batch-file", action="append", default=[])
    queue_parser.add_argument("--expected-source-count", type=int)
    queue_parser.add_argument("--sample-start-index", type=int, default=1)
    queue_parser.add_argument("--resume", action="store_true")
    queue_parser.add_argument("--dry-run", action="store_true")
    queue_parser.add_argument("--ttl-seconds", type=int, default=3600)
    queue_parser.add_argument("--current-patch")
    queue_parser.add_argument("--passive-tree-version")
    queue_parser.add_argument("--pob-version-or-commit")

    claim_parser = subparsers.add_parser("claim")
    _add_queue_location_args(claim_parser)
    claim_parser.add_argument("--lease-seconds", type=int, default=1800)
    claim_parser.add_argument("--lease-owner", default="external_researcher_worker")

    prompt_parser = subparsers.add_parser("prompt")
    _add_queue_location_args(prompt_parser)
    prompt_parser.add_argument("--lease-token", required=True)
    prompt_parser.add_argument("--current-patch")
    prompt_parser.add_argument("--passive-tree-version")
    prompt_parser.add_argument("--user-language", default="zh-CN")

    inspect_parser = subparsers.add_parser("inspect")
    _add_queue_location_args(inspect_parser)
    inspect_parser.add_argument("--lease-token", required=True)

    read_parser = subparsers.add_parser("read")
    _add_queue_location_args(read_parser)
    read_parser.add_argument("--lease-token", required=True)
    read_parser.add_argument("--section", required=True, choices=research_packet.RESEARCH_SECTIONS)
    read_parser.add_argument("--cursor", type=int, default=0)
    read_parser.add_argument("--limit", type=int, default=research_packet.DEFAULT_PAGE_SIZE)

    search_parser = subparsers.add_parser("search")
    _add_queue_location_args(search_parser)
    search_parser.add_argument("--lease-token", required=True)
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--section", choices=research_packet.RESEARCH_SECTIONS)
    search_parser.add_argument("--limit", type=int, default=research_packet.DEFAULT_PAGE_SIZE)

    worker_brief_parser = subparsers.add_parser("worker-brief")
    _add_queue_location_args(worker_brief_parser)
    worker_brief_parser.add_argument("--lease-token", required=True)

    review_contract_parser = subparsers.add_parser("review-contract")
    _add_queue_location_args(review_contract_parser)
    review_contract_parser.add_argument("--lease-token", required=True)

    init_review_parser = subparsers.add_parser("init-review")
    _add_queue_location_args(init_review_parser)
    init_review_parser.add_argument("--lease-token", required=True)

    accept_parser = subparsers.add_parser("accept")
    _add_queue_location_args(accept_parser)
    accept_parser.add_argument("--lease-token", required=True)
    accept_parser.add_argument("--review-file", required=True)
    accept_parser.add_argument("--memory-db-path", default=str(DEFAULT_MEMORY_DB_PATH))
    accept_parser.add_argument("--acceptance-output-dir")
    accept_parser.add_argument("--validate-only", action="store_true")

    retry_accept_parser = subparsers.add_parser("retry-accept")
    _add_queue_location_args(retry_accept_parser)
    retry_accept_parser.add_argument("--sample-id", required=True)
    retry_accept_parser.add_argument("--review-file", required=True)
    retry_accept_parser.add_argument("--memory-db-path", default=str(DEFAULT_MEMORY_DB_PATH))
    retry_accept_parser.add_argument("--acceptance-output-dir")

    status_parser = subparsers.add_parser("status")
    _add_queue_location_args(status_parser)

    args = parser.parse_args(argv)
    try:
        if args.command == "queue":
            run_id, output_dir = _queue_cli_output_dir(args)
            report = queue_cases(
                league_url=args.league,
                limit=args.limit,
                worker_count=args.worker_count,
                level_min=args.level_min,
                level_max=args.level_max,
                ascendancies=list(args.ascendancy or []),
                ninja_classes=list(args.ninja_classes or []),
                source_files=[Path(item) for item in args.source_file],
                source_batch_files=[Path(item) for item in args.source_batch_file],
                expected_source_count=args.expected_source_count,
                sample_start_index=args.sample_start_index,
                output_dir=output_dir,
                queue_db_path=args.queue_db_path,
                temp_root=args.temp_root,
                ttl_seconds=args.ttl_seconds,
                current_patch=args.current_patch,
                passive_tree_version=args.passive_tree_version,
                pob_version_or_commit=args.pob_version_or_commit,
                resume=args.resume,
                dry_run=args.dry_run,
            )
            if run_id is not None:
                _attach_run_location(report, run_id=run_id, run_dir=output_dir)
            _print_json(report)
            return (
                1
                if report.get("status") in {"source_input_count_mismatch", "source_unavailable"}
                else 0
            )
        if args.command == "claim":
            _print_json(
                claim_case(
                    output_dir=args.output_dir,
                    queue_db_path=args.queue_db_path,
                    lease_seconds=args.lease_seconds,
                    lease_owner=args.lease_owner,
                )
            )
            return 0
        if args.command == "prompt":
            print(
                render_claim_prompt(
                    output_dir=args.output_dir,
                    queue_db_path=args.queue_db_path,
                    temp_root=args.temp_root,
                    lease_token=args.lease_token,
                    current_patch=args.current_patch,
                    passive_tree_version=args.passive_tree_version,
                    user_language=args.user_language,
                )
            )
            return 0
        if args.command == "inspect":
            _print_json(
                inspect_case(
                    output_dir=args.output_dir,
                    queue_db_path=args.queue_db_path,
                    temp_root=args.temp_root,
                    lease_token=args.lease_token,
                )
            )
            return 0
        if args.command == "read":
            _print_json(
                read_case_section(
                    output_dir=args.output_dir,
                    queue_db_path=args.queue_db_path,
                    temp_root=args.temp_root,
                    lease_token=args.lease_token,
                    section=args.section,
                    cursor=args.cursor,
                    limit=args.limit,
                )
            )
            return 0
        if args.command == "search":
            _print_json(
                search_case(
                    output_dir=args.output_dir,
                    queue_db_path=args.queue_db_path,
                    temp_root=args.temp_root,
                    lease_token=args.lease_token,
                    query=args.query,
                    section=args.section,
                    limit=args.limit,
                )
            )
            return 0
        if args.command == "worker-brief":
            _print_json(
                render_worker_brief(
                    output_dir=args.output_dir,
                    queue_db_path=args.queue_db_path,
                    lease_token=args.lease_token,
                )
            )
            return 0
        if args.command == "review-contract":
            _print_json(
                render_review_contract(
                    output_dir=args.output_dir,
                    queue_db_path=args.queue_db_path,
                    lease_token=args.lease_token,
                )
            )
            return 0
        if args.command == "init-review":
            _print_json(
                init_review(
                    output_dir=args.output_dir,
                    queue_db_path=args.queue_db_path,
                    lease_token=args.lease_token,
                )
            )
            return 0
        if args.command == "accept":
            _print_json(
                accept_case(
                    output_dir=args.output_dir,
                    queue_db_path=args.queue_db_path,
                    lease_token=args.lease_token,
                    review_file=args.review_file,
                    memory_db_path=args.memory_db_path,
                    acceptance_output_dir=args.acceptance_output_dir,
                    temp_root=args.temp_root,
                    validation_only=args.validate_only,
                )
            )
            return 0
        if args.command == "retry-accept":
            _print_json(
                retry_accept_case(
                    output_dir=args.output_dir,
                    queue_db_path=args.queue_db_path,
                    sample_id=args.sample_id,
                    review_file=args.review_file,
                    memory_db_path=args.memory_db_path,
                    acceptance_output_dir=args.acceptance_output_dir,
                    temp_root=args.temp_root,
                )
            )
            return 0
        if args.command == "status":
            _print_json(queue_status(output_dir=args.output_dir, queue_db_path=args.queue_db_path))
            return 0
    except Exception as exc:  # noqa: BLE001 - CLI runtime must report safe JSON, not a traceback.
        _print_json(_runtime_failure_payload(args.command, exc))
        return 1
    return 2


def _add_queue_location_args(
    parser: argparse.ArgumentParser,
    *,
    default_output_dir: str | None = str(DEFAULT_OUTPUT_DIR),
) -> None:
    parser.add_argument("--output-dir", default=default_output_dir)
    parser.add_argument("--queue-db-path")
    parser.add_argument("--temp-root")


if __name__ == "__main__":
    raise SystemExit(main())
