"""Product entrypoint for mature PoE2 build research queues.

This script does not call an LLM provider. It prepares safe queue metadata,
leases mature build cases to a bounded worker pool, renders bounded transient
evidence only for each active lease, and accepts safe proposals through the
existing typed gates.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from contextlib import closing
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
from server.knowledge import (  # noqa: E402
    copy_safety,
    graph_seed,
    graph_tools,
    mature_learning,
    pob_xml_meta,
    research_identity,
    research_intake_ledger,
    research_contracts,
    research_completion,
    research_retention,
    research_followups,
    research_memory,
    research_models,
    research_packet,
    research_readback,
    research_runtime,
)
from server.runtime.file_lock import interprocess_file_lock  # noqa: E402

DEFAULT_OUTPUT_DIR = REPO_ROOT / ".poe-bd-research"
RUNS_DIRNAME = "runs"
QUEUE_DB_FILENAME = "poe_bd_research_queue.sqlite"
DEFAULT_TEMP_DIRNAME = "poe-bd-creator-research-packets"
DEFAULT_MEMORY_DB_PATH = paths.mature_learning_path()
DEFAULT_INTAKE_LEDGER_PATH = research_intake_ledger.default_ledger_path()
DEFAULT_WORKER_COUNT = 5
MAX_WORKER_COUNT = 5
_ACCEPT_LOCK = threading.RLock()
MAX_LEASE_SECONDS = 24 * 60 * 60

RESEARCH_MANDATORY_CHECKS = (
    "暗金/lineage 宝石必须标注 unique 身份；unique support gem 保持 support_modifier role，"
    "不得误用 unique_enabler。",
    "已分配天赋树珠宝槽必须显式声明空置或已插珠宝及 radius/Time-Lost 覆盖；装备珠宝孔不能替代树槽。",
    "评估全部 persistent buff 的 Spirit/reservation 预算与来源，并写入资源闭环记录。",
    "盘点全部启用技能组；Family 核心和结论依赖的高影响组必须提供 supportPackages 或 "
    "supportCoverageExceptions，其他组也不得静默丢弃。",
    "辅助机制结论以 review 内 support_skill_group_candidates 组合校验为准；单对查询只用于候选发现，"
    "机制语义不得按名称猜测。",
    "Memory 对照前先用 search_graph_components + resolve_graph_component 解析身份 stable key，"
    "再检查 familyRecordCoverage、familyRecordIndex 与 familyPremiseCatalog。",
    "把 packet 中每个 condition* 写成 条件→来源组件→验证状态；无来源假设必须进入 modelability caveat。",
    "每个装备槽位都必须以结构化组件、content 文本或显式 not_applicable 的一种形式出现在记录中。",
    "不得猜 stable-key 路径；所有组件先 search 再 resolve，resolverQuery 必须是完整 key、映射、alias "
    "或归一化显示名。",
    "lookup_mechanic silent/unavailable 时保留有样本证据或引擎读回支持的结论；不因 wiki 缺页强制新增 "
    "caveat 或 verification task。",
    "非 Family 核心技能组也必须被观察；结论依赖其插槽结构时保存根技能与 socketed supports，否则明确保留为 "
    "content、caveat 或 verification task。",
    "每个 resource_engine/mechanic_chain 写入前核对生成与消费方向，并与既有同组件 Family 记录对照。",
    "出现 unresolved 计数时必须逐个执行 search_graph_components，再定性为 source gap。",
    "Family 身份只使用升华 + primary_damage 技能集合；纯 clear/boss/triggered/trigger_host 副技能包"
    "不要求自己的 primary_damage，support/non-skill 组件不改变该豁免。",
    "每案至少提交 2 条 resolver-backed semantic edge；无法合法推导时明确说明，禁止为凑数发明关系。",
    "review 顶层 memoryUse 必须存在并记录本案的 query_research_memory 查询；未查询时保留空 queries "
    "并说明原因。",
)

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


def _effective_worker_count(value: Any) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = DEFAULT_WORKER_COUNT
    return min(MAX_WORKER_COUNT, max(1, requested))


def _accept_lock_path(memory_db_path: str | Path) -> Path:
    memory_path = Path(memory_db_path).resolve()
    return memory_path.with_name(f".{memory_path.name}.research-accept.lock")


def queue_cases(
    *,
    league_url: str = "current",
    limit: int = 50,
    worker_count: int = DEFAULT_WORKER_COUNT,
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
    ttl_seconds: int = 24 * 60 * 60,
    current_patch: str | None = None,
    passive_tree_version: str | None = None,
    pob_version_or_commit: str | None = None,
    browser_driver: Any | None = None,
    resume: bool = False,
    dry_run: bool = False,
    intake_ledger_path: str | Path | None = None,
    re_research_run_dir: str | Path | None = None,
    supplement_sample_ids: list[str] | None = None,
    supplement_focus: str = "",
    retention_days: int = 7,
    target_character_refs: set[str] | None = None,
    reacquisition_context: dict[str, str] | None = None,
    re_research_scope: str = "supplement",
    memory_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create or resume a safe mature-build research queue.

    ``re_research_run_dir`` points at a completed research run whose cases are re-queued as
    local supplement research (the same source hash is re-studied to close gaps, marked
    ``supplement=true``). Raw material is rebuilt from the prior run's quarantine; cases
    without quarantine material are skipped.
    """
    effective_worker_count = _effective_worker_count(worker_count)
    if re_research_scope not in {"supplement", "full_case"}:
        raise ValueError("invalid_re_research_scope")
    if re_research_scope == "full_case" and (re_research_run_dir is None or not supplement_sample_ids):
        raise ValueError("full_case_revisit_requires_selected_source_cases")
    if resume and dry_run:
        raise ValueError("resume_dry_run_not_supported")
    output_root = Path(output_dir)
    if not resume:
        output_root.mkdir(parents=True, exist_ok=True)
    db_path = _queue_db_path(output_root, queue_db_path)
    if db_path.exists() and not resume:
        raise FileExistsError("research queue already exists; use --resume with the same --output-dir")
    effective_ledger = (
        Path(intake_ledger_path) if intake_ledger_path is not None else DEFAULT_INTAKE_LEDGER_PATH
    )
    effective_temp_root = _effective_temp_root(temp_root, output_root=output_root)
    if resume and not dry_run:
        return _resume_queue_cases(
            output_root=output_root, db_path=db_path, effective_temp_root=effective_temp_root,
            worker_count=effective_worker_count, memory_db_path=memory_db_path,
        )
    effective_temp_root.mkdir(parents=True, exist_ok=True)
    research_packet.cleanup_expired_packets(temp_root=effective_temp_root)
    version_context = _runtime_version_context(
        current_patch=current_patch,
        passive_tree_version=passive_tree_version,
        pob_version_or_commit=pob_version_or_commit,
    )
    source_file_values = list(source_files or [])
    source_batch_file_values = list(source_batch_files or [])
    if re_research_run_dir is not None:
        if source_file_values or source_batch_file_values:
            raise ValueError(
                "--re-research cannot be combined with --source-file/--source-batch-file"
            )
        if resume:
            raise ValueError("--re-research cannot be combined with --resume")
        prior_run_root = Path(re_research_run_dir)
        if not (prior_run_root / QUEUE_DB_FILENAME).exists():
            raise ValueError(
                f"--re-research run directory has no {QUEUE_DB_FILENAME}: {re_research_run_dir}"
            )
    elif supplement_sample_ids is not None:
        raise ValueError("supplement_sample_ids require --re-research")
    normalized_supplement_ids = _normalize_supplement_sample_ids(supplement_sample_ids)
    normalized_ninja_classes = legacy_batch._normalize_ninja_classes(ninja_classes or [])
    local_sources = legacy_batch._local_sources(source_file_values, source_batch_file_values)
    collector_stats: dict[str, Any] = {
        "pagesFetched": 0,
        "pageRowsSeen": 0,
        "skippedAlreadyResearched": 0,
    }
    source_input_summary = {
        "sourceFileArgumentCount": len(source_file_values),
        "sourceBatchFileArgumentCount": len(source_batch_file_values),
        "localSourceInputCount": len(local_sources),
        "reResearchRunDir": _display_path(Path(re_research_run_dir)) if re_research_run_dir else "",
        "reSupplementCaseCount": 0,
        "reSupplementSkippedUnrecoverableCount": 0,
        "requestedSupplementSampleCount": len(normalized_supplement_ids or []),
        "selectedSupplementSampleCount": 0,
        "selectedSupplementSampleIds": [],
        "missingSupplementSampleCount": 0,
        "missingSupplementSampleIds": [],
        "notAcceptedSupplementSampleCount": 0,
        "notAcceptedSupplementSampleIds": [],
        "unrecoverableSupplementSampleCount": 0,
        "unrecoverableSupplementSampleIds": [],
        "levelMin": max(0, int(level_min or 0)),
        "levelMax": max(0, int(level_max or 0)),
        "requestedSampleCount": (
            len(local_sources)
            if source_file_values or source_batch_file_values
            else len(normalized_supplement_ids)
            if normalized_supplement_ids is not None
            else max(0, int(limit))
        ),
        "expectedSourceCount": (
            max(0, int(expected_source_count)) if expected_source_count is not None else None
        ),
        "intakePagesFetched": 0,
        "intakePageRowsSeen": 0,
        "intakeSkippedAlreadyResearched": 0,
        "intakeLedgerRecordedCount": 0,
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
    re_research_cases: list[dict[str, Any]] = []
    if re_research_run_dir is not None:
        re_research_cases, re_unrecoverable = _cases_from_prior_run(
            Path(re_research_run_dir),
            supplement_sample_ids=normalized_supplement_ids,
            supplement_focus=supplement_focus,
        )
        if re_research_scope == "full_case":
            for case in re_research_cases:
                case["supplement"] = False
        source_input_summary["reSupplementCaseCount"] = len(re_research_cases)
        source_input_summary["reSupplementSkippedUnrecoverableCount"] = re_unrecoverable
        source_input_summary["selectedSupplementSampleCount"] = len(re_research_cases)
        source_input_summary["selectedSupplementSampleIds"] = [
            str(case.get("sampleId") or "") for case in re_research_cases
        ]
    cases = (
        re_research_cases
        if re_research_run_dir is not None
        else (
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
                intake_ledger_path=effective_ledger,
                collector_stats=collector_stats,
                **({"target_character_refs": target_character_refs} if target_character_refs is not None else {}),
            )
        )
    )
    if target_character_refs is not None and any(
        case.get("status") == "pending" and (
            case.get("characterRef") not in target_character_refs
            or case.get("league") != league_url
        ) for case in cases
    ):
        raise ValueError("reacquisition_target_mismatch")
    _normalize_sample_ids(cases, sample_start_index=sample_start_index)
    source_input_summary["uniqueLocalCaseCount"] = len(cases) if local_sources else 0
    source_input_summary["duplicateLocalSourceCount"] = (
        max(0, len(local_sources) - len(cases)) if local_sources else 0
    )
    source_input_summary["intakePagesFetched"] = int(collector_stats.get("pagesFetched") or 0)
    source_input_summary["intakePageRowsSeen"] = int(collector_stats.get("pageRowsSeen") or 0)
    source_input_summary["intakeSkippedAlreadyResearched"] = int(
        collector_stats.get("skippedAlreadyResearched") or 0
    )

    if dry_run:
        report = _queue_report(
            status="dry_run",
            db_path=db_path,
            requested_worker_count=effective_worker_count,
            cases=[_safe_case_row_from_case(case) for case in cases],
            dry_run=True,
            source_input_summary=source_input_summary,
            intake_ledger_summary=_intake_ledger_summary(
                effective_ledger,
                league=(str(collector_stats.get("resolvedLeague") or "") or league_url),
                local_sources=local_sources,
            ),
        )
        _assert_safe_payload(report)
        return report

    _init_db(db_path)
    _write_metadata(
        db_path,
        {
            "queueKind": "poe_bd_research_external_agent_queue",
            "retentionPolicy": json.dumps(research_retention.create_policy(
                now=_now(), retention_days=retention_days,
            ), sort_keys=True),
            "reacquisitionParentRunRef": (reacquisition_context or {}).get("parentRunRef", ""),
            "reacquisitionParentSampleId": (reacquisition_context or {}).get("sampleId", ""),
            "reacquisitionRequestId": (reacquisition_context or {}).get("requestId", ""),
            "reResearchScope": re_research_scope if re_research_run_dir else "case",
            "supplementParentRunRef": (
                f"research-run:{Path(re_research_run_dir).name}" if re_research_run_dir else ""
            ),
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
            "requestedSupplementSampleCount": str(
                source_input_summary["requestedSupplementSampleCount"]
            ),
            "selectedSupplementSampleCount": str(
                source_input_summary["selectedSupplementSampleCount"]
            ),
            "selectedSupplementSampleIds": json.dumps(
                source_input_summary["selectedSupplementSampleIds"], ensure_ascii=False
            ),
            "missingSupplementSampleCount": str(
                source_input_summary["missingSupplementSampleCount"]
            ),
            "missingSupplementSampleIds": json.dumps(
                source_input_summary["missingSupplementSampleIds"], ensure_ascii=False
            ),
            "notAcceptedSupplementSampleCount": str(
                source_input_summary["notAcceptedSupplementSampleCount"]
            ),
            "notAcceptedSupplementSampleIds": json.dumps(
                source_input_summary["notAcceptedSupplementSampleIds"], ensure_ascii=False
            ),
            "unrecoverableSupplementSampleCount": str(
                source_input_summary["unrecoverableSupplementSampleCount"]
            ),
            "unrecoverableSupplementSampleIds": json.dumps(
                source_input_summary["unrecoverableSupplementSampleIds"], ensure_ascii=False
            ),
            "intakePagesFetched": str(source_input_summary["intakePagesFetched"]),
            "intakePageRowsSeen": str(source_input_summary["intakePageRowsSeen"]),
            "intakeSkippedAlreadyResearched": str(
                source_input_summary["intakeSkippedAlreadyResearched"]
            ),
            "intakeSkippedAlreadyStudied": str(
                source_input_summary.get("intakeSkippedAlreadyStudied") or 0
            ),
            "intakeLedgerRecordedCount": str(source_input_summary["intakeLedgerRecordedCount"]),
            "intakeLedgerPath": str(Path(effective_ledger).resolve()),
            "queueStatus": (
                ""
                if any(case.get("status") == "pending" for case in cases)
                else "source_unavailable"
            ),
            "requestedWorkerCount": str(effective_worker_count),
            "workerCountSemantics": "parallel_subagents_one_case_each",
            "currentPatch": version_context["gamePatch"],
            "passiveTreeVersion": version_context["passiveTreeVersion"],
            "pobVersionOrCommit": version_context["pobVersionOrCommit"],
            "versionContextStatus": version_context["status"],
            "modelGamePatch": version_context.get("modelGamePatch", ""),
            "updatedAt": _now_iso(),
        },
    )

    inserted = 0
    skipped_duplicates = 0
    ledger_recorded = 0
    studied_source_hashes = _studied_source_hashes()
    skipped_already_studied = 0
    for case in cases:
        if case.get("status") != "pending":
            packet_id = ""
            packet_safe_hash = ""
        else:
            _write_quarantine_case(output_root, case)
            packet = _prepare_packet(
                case,
                temp_root=effective_temp_root,
                ttl_seconds=ttl_seconds,
                current_patch=version_context["gamePatch"],
                passive_tree_version=version_context["passiveTreeVersion"],
                pob_version_or_commit=version_context["pobVersionOrCommit"],
                version_context=version_context,
            )
            packet_id = str(packet["packetId"])
            packet_safe_hash = str(packet["packetSafeHash"])
        source_hash = str(case.get("sourceHash") or "").strip()
        if (
            source_hash
            and source_hash in studied_source_hashes
            and not dry_run
            and not local_sources
            and not re_research_run_dir
            and target_character_refs is None
        ):
            # The same mature build (byte-identical PoB text) was already researched and
            # accepted into durable memory; re-queueing it would duplicate knowledge and
            # split families. Skip it and report the count truthfully.
            skipped_already_studied += 1
            continue
        row = _safe_case_row_from_case(
            case,
            packet_id=packet_id,
            packet_safe_hash=packet_safe_hash,
        )
        was_inserted = _insert_case_if_absent(db_path, row)
        inserted += 1 if was_inserted else 0
        skipped_duplicates += 0 if was_inserted else 1
        character_ref = str(case.get("characterRef") or "").strip()
        if was_inserted and character_ref.startswith("character-hash:") and target_character_refs is None:
            if research_intake_ledger.record_case(
                effective_ledger,
                league=str(case.get("league") or league_url),
                character_ref=character_ref,
                source_hash=str(case.get("sourceHash") or ""),
                level=int(case.get("level") or 0),
                ascendancy=str(case.get("ascendancy") or ""),
                main_skill=str(case.get("mainSkill") or ""),
                sample_id=str(case.get("sampleId") or ""),
            ):
                ledger_recorded += 1
    source_input_summary["intakeLedgerRecordedCount"] = ledger_recorded
    source_input_summary["intakeSkippedAlreadyStudied"] = skipped_already_studied
    resolved_league = str(collector_stats.get("resolvedLeague") or "") or league_url
    intake_ledger_summary = _intake_ledger_summary(
        effective_ledger,
        league=resolved_league,
        local_sources=local_sources,
    )
    _write_metadata(
        db_path,
        {
            "intakeLedgerRecordedCount": str(ledger_recorded),
            "intakeLedgerSummary": json.dumps(
                intake_ledger_summary, ensure_ascii=False, sort_keys=True
            ),
        },
    )

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
        intake_ledger_summary=intake_ledger_summary,
    )
    if re_research_run_dir is not None:
        # Re-research is a single queue-action fact, not persisted queue metadata: overlay
        # it on the queue report so the supplement round is visible without polluting
        # later queue_status reads.
        report["reResearchRunDir"] = str(source_input_summary.get("reResearchRunDir") or "")
        report["reSupplementCaseCount"] = int(
            source_input_summary.get("reSupplementCaseCount") or 0
        )
        report["reSupplementSkippedUnrecoverableCount"] = int(
            source_input_summary.get("reSupplementSkippedUnrecoverableCount") or 0
        )
    _assert_safe_payload(report)
    return report


def claim_case(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    lease_seconds: int = 7200,
    lease_owner: str = "current_researcher_agent",
    temp_root: str | Path | None = None,
) -> dict[str, Any]:
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    with interprocess_file_lock(_run_lock_path(db_path)):
        # Cleanup can win after the caller resolved runRef but before this lock.
        # Never let _init_db recreate that run and shadow its safe cleanup audit.
        if not db_path.is_file():
            return {
                "status": "rejected", "errorCode": "research_run_not_found",
                "noRawMatureBuildMaterial": True,
            }
        policy = research_retention.inspect_policy(_read_metadata(db_path), now=_now())
        if not policy["newClaimAllowed"]:
            return {
                "status": "retention_expired" if policy["status"] == "expired" else "retention_policy_invalid",
                "retention": policy, "noRawMatureBuildMaterial": True,
            }
        return _claim_case_locked(
            output_dir=output_dir, queue_db_path=queue_db_path, lease_seconds=lease_seconds,
            lease_owner=lease_owner, temp_root=temp_root,
        )


def _run_lock_path(db_path: Path) -> Path:
    return db_path.parent.parent / f".{db_path.parent.name}.research-run.lock"


def _acceptance_source_context(
    row: sqlite3.Row, version_context: dict[str, Any], pob_readback: dict[str, Any] | None,
) -> dict[str, Any]:
    context = {
        "sourceHashRef": str(row["source_hash_ref"]),
        "sourceHash": str(row["source_hash"]),
        "gamePatch": str(version_context.get("gamePatch") or ""),
        "passiveTreeVersion": str(version_context.get("passiveTreeVersion") or ""),
        "pobVersionOrCommit": str(version_context.get("pobVersionOrCommit") or ""),
        "knowledgeScope": _authoritative_knowledge_scope(row),
    }
    if isinstance(pob_readback, dict) and pob_readback.get("status") == "available":
        binding = pob_readback.get("stateBinding") or {}
        for key in ("sourceSnapshotHash", "activeSets"):
            if binding.get(key):
                context[key] = binding[key]
    return context


def _claim_case_locked(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    lease_seconds: int = 7200,
    lease_owner: str = "current_researcher_agent",
    temp_root: str | Path | None = None,
) -> dict[str, Any]:
    """Atomically lease one case up to the queue's bounded worker capacity."""
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    if not db_path.is_file():
        return {
            "status": "rejected", "errorCode": "research_run_not_found",
            "noRawMatureBuildMaterial": True,
        }
    _init_db(db_path, allow_create=False)
    now = _now()
    lease_seconds = min(MAX_LEASE_SECONDS, max(1, int(lease_seconds or 1)))
    expires = now + timedelta(seconds=lease_seconds)
    # token_urlsafe's alphabet includes "-", so a token can start with "-" and argparse would
    # treat a "--lease-token <value>" value as a new option ("expected one argument"). Prefix a
    # letter so every generated token is argparse-safe; main() additionally rewrites legacy
    # dash-leading values into the equals form.
    lease_token = "t" + secrets.token_urlsafe(32)
    with closing(_connect_queue(db_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        configured_worker_count = conn.execute(
            "SELECT value FROM metadata WHERE key = 'requestedWorkerCount'"
        ).fetchone()
        worker_count = _effective_worker_count(
            configured_worker_count["value"]
            if configured_worker_count is not None
            else DEFAULT_WORKER_COUNT
        )
        active_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                  FROM cases
                 WHERE status IN ('claimed', 'accepting')
                   AND (status = 'accepting' OR lease_expires_at > ?)
                """,
                (_iso(now),),
            ).fetchone()[0]
        )
        if active_count >= worker_count:
            conn.commit()
            return {
                "status": "worker_capacity_reached",
                "queueKind": "poe_bd_research_external_agent_queue",
                "activeCaseCount": active_count,
                "workerCount": worker_count,
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
    try:
        _rebuild_packet_for_claim(
            row=claimed,
            output_root=Path(output_dir),
            temp_root=temp_root,
            lease_seconds=lease_seconds,
            queue_db_path=db_path,
        )
        with closing(_connect_queue(db_path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            claimed = conn.execute(
                "SELECT * FROM cases WHERE id = ?", (int(claimed["id"]),)
            ).fetchone()
    except Exception:
        with closing(_connect_queue(db_path)) as conn, conn:
            cur = conn.execute(
                """
                UPDATE cases
                   SET status = 'queued',
                       lease_token = NULL,
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       updated_at = ?
                 WHERE id = ?
                   AND status = 'claimed'
                   AND lease_token = ?
                   AND packet_safe_hash = ?
                """,
                (
                    _now_iso(),
                    int(claimed["id"]),
                    lease_token,
                    str(claimed["packet_safe_hash"]),
                ),
            )
            conn.commit()
        result = {
            "status": "claim_packet_failed",
            "queueKind": "poe_bd_research_external_agent_queue",
            "sampleId": str(claimed["sample_id"]),
            "errorKind": "packet_prepare_failed",
            "leaseReleased": cur.rowcount == 1,
            "retryable": cur.rowcount == 1,
            "recoveryRequired": cur.rowcount != 1,
            "noRawMatureBuildMaterial": True,
        }
        _assert_safe_payload(result)
        return result
    result = _claim_payload(
        dict(claimed),
        lease_token=lease_token,
        output_root=Path(output_dir),
        temp_root=temp_root,
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
    node_type: str | None = None,
    exclude_routing: bool = False,
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
        node_type=node_type,
        exclude_routing=exclude_routing,
        response_metadata={"sampleId": str(row["sample_id"])},
    )
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
        response_metadata={"sampleId": str(row["sample_id"])},
    )
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
        "contractVersion": research_contracts.SAFE_REVIEW_CONTRACT_VERSION,
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
            "reviewContractVersion": research_contracts.SAFE_REVIEW_CONTRACT_VERSION,
            "safeArtifactOnly": True,
            "artifactIdentity": artifact_identity,
            "knowledgeScope": _authoritative_knowledge_scope(row),
            "caseCoverage": {
                "supports": "evidence_missing",
                "rotation": "evidence_missing",
                "passiveAscendancy": "evidence_missing",
                "gearRoles": "evidence_missing",
                "resourceDefense": "evidence_missing",
            },
            "mechanicAudit": [],
            "memoryUse": {"queries": []},
            "sourceSkillGroupReviews": [],
            "pobReadbackAudit": [],
            "deepResearchRecords": [],
            "candidateReviews": [],
            "semanticEdges": [],
        },
        "memoryUseQuerySchema": {
            "dedupeQueryRef": "required dq-... receipt from query_research_memory",
            "query": "safe query summary",
            "ascendancyKey": "optional ascendancy:... identity",
            "primarySkillKey": "optional skill:... or gem:... identity",
            "buildFamilyKeys": (
                "optional stored bf-... IDs returned by an earlier query; omit when unknown, "
                "never place skill:/gem: keys here"
            ),
            "outcome": "safe comparison outcome",
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
            "mechanicAuditMatchKind": sorted(acceptance.MECHANIC_AUDIT_MATCH_KINDS),
            "mechanicAuditDecision": sorted(acceptance.MECHANIC_AUDIT_DECISIONS),
            "mechanicAuditCorroboration": sorted(acceptance.MECHANIC_AUDIT_CORROBORATION),
            "gearResponsibilityType": sorted(research_models.GEAR_RESPONSIBILITY_TYPES),
            "gearSubject": sorted(research_contracts.GEAR_SUBJECTS),
            "sourceStateScope": sorted(research_contracts.SOURCE_STATE_SCOPES),
            "supportDeliveryRole": ["direct"],
            "sourceGroupResearchDisposition": sorted(acceptance.SOURCE_GROUP_RESEARCH_DISPOSITIONS),
            "sourceGroupSupportDisposition": sorted(acceptance.SOURCE_GROUP_SUPPORT_DISPOSITIONS),
            "pobReadbackDisposition": ["reviewed", "unavailable", "unmodelled"],
            "typedIdentityFields": {
                "familyCoreSkillKeys": "resolved skill keys explicitly retained as Family-core secondary metadata when their role is not already inferred from clear/boss/triggered_payload; these keys do not change the Family identity key",
                "resourceMechanisms": "lower_snake_case resource methods without graph nodes",
                "supportPackages": "v3 uses stable skillKey/supportKeys plus exact sourceGroupRef/rootSkillRef and one source-local socketedItemRef per support instance; source-local refs are validation-only and are not durable identity",
                "supportCoverageExceptions": "skillKey, or exact skillName when resolver is unavailable, plus source_coverage_gap/not_applicable detail",
                "availability": "standard or source_specific_random",
                "sourceSpecificComponentKeys": "random-instance components excluded from planner advice",
                "ascendancyResponsibilities": "componentKey, or exact componentName when resolver is unavailable, plus concrete responsibility",
                "gearResponsibilities": "componentKey, or exact componentName when resolver is unavailable, plus canonical responsibilityType and concise responsibility; use an explicit [] only for content-based rare/magic gear evidence",
                "gearSubjects": "canonical equipment/jewel subjects for content-based gear records",
                "jewelSocketStates": "typed node/spec/item state for active empty, active-unallocated, and other-spec tree jewel assignments",
            },
        },
        "componentRoleNodeTypeCompatibility": {
            role: list(node_types)
            for role, node_types in sorted(acceptance.ROLE_NODE_TYPES.items())
        },
        "recordIdentityRoles": research_identity.kind_identity_roles(),
        "sourceClaimKeyRule": (
            "Optional record-root sourceClaimKey defaults to default. Use a stable lowercase "
            "ASCII slug (letters/digits first, then letters/digits/_/-, <=80 characters) only "
            "to distinguish parallel conditional claims from the same source and mechanism "
            "topic. Reuse the key when revising that claim. It is not a typedPayload field, "
            "content identity, new source, or additional independent evidence."
        ),
        "sourceClaimRevisionRule": (
            "Different knowledge topics coexist even when their titles match. A cross-topic correction "
            "must supply optional record-root sourceClaimRevision with knowledgeKey, recordId and "
            "projectionHash from the exact current source claim; it never authorizes another source."
        ),
        "typedPayloadSchema": {
            "knowledgeShape": {
                "mechanic_chain": "state_causal_chain",
                "rotation": "player_action_sequence",
                "others": "optional; do not invent shapes outside allowedValues.knowledgeShape",
            },
            "familyCoreSkillKeys": {
                "type": "list[str]",
                "rule": "resolved skill stable keys (skill:...) that are not already inferred from clear/boss/triggered_payload roles; Family-core trigger hosts must be declared here explicitly; no duplicates; values enrich secondary metadata and support coverage but do not change the Family identity key",
            },
            "resourceMechanisms": {
                "type": "list[str]",
                "rule": "lower_snake_case tags (e.g. mana_leech, mana_flask) for resource methods without physical graph nodes; each matches ^[a-z][a-z0-9_]{0,63}$; no duplicates",
            },
            "supportPackages": {
                "type": "list[object]",
                "entry": '{"skillKey": str, "supportKeys": [str, ...], "socketedItemRefs": [str, ...], "deliveryRole": "direct", "sourceGroupRef": str, "rootSkillRef": str}',
                "rule": "For record schema 2, every record kind containing resolved support gems must provide supportPackages covering all resolved support gems in that same record, even a single support; packages in other records cannot satisfy this obligation; copy the physical socket package from the lease skill-group manifest: skillKey is the resolved root skill; supportKeys and socketedItemRefs are parallel lists identifying the support type and exact physical instance under that root; sourceGroupRef/rootSkillRef must match exactly; <=12 entries; the same socketedItemRef cannot appear in two packages, while distinct instances may share a support stable key; source-local refs are stripped before durable storage; record socketed active payloads and host/payload mechanics through components/mechanic records rather than deliveryRole",
            },
            "supportCoverageExceptions": {
                "type": "list[object]",
                "entry": 'exactly {"skillKey": str, "reason": "source_coverage_gap"|"not_applicable", "detail": str}',
                "rule": "skillKey resolved and mentioned in the same record; one entry per skillKey; detail <=240 chars; use only for a real gap or a single-support skill; exceptions explain group-level source coverage and cannot waive per-record packaging of resolved supports",
            },
            "availability": {"type": "str", "values": ["standard", "source_specific_random"]},
            "sourceSpecificComponentKeys": {
                "type": "list[str]",
                "rule": "requires availability=source_specific_random; references resolved components in the same record; <=12",
            },
            "ascendancyResponsibilities": {
                "type": "list[object]",
                "entry": 'exactly {"componentKey": str, "responsibility": str}',
                "rule": "componentKey resolved and mentioned in the same record with an ascendancy-eligible role; responsibility <=240 chars; <=12 entries",
            },
            "gearResponsibilities": {
                "type": "list[object]",
                "entry": 'exactly {"componentKey": str, "responsibilityType": str, "responsibility": str}',
                "rule": "only on gear_synergy records; componentKey resolved and mentioned in the same record with role unique_enabler/gear_base/weapon_base; responsibilityType in allowedValues.gearResponsibilityType; responsibility <=240 chars; <=12 entries; componentKey unique; for rare/magic items without a graph node, explicitly set gearResponsibilities=[] and describe slot + target mods + roll pursuit in content; a missing or null field is not this declaration",
            },
            "gearSubjects": {
                "type": "list[str]",
                "rule": "required and non-empty when gearResponsibilities=[]; use allowedValues.gearSubject",
            },
            "jewelSocketStates": {
                "type": "list[object]",
                "entry": "nodeId/specId/state plus itemId unless state=empty",
                "rule": "only on passive_package/open_question/modelability_caveat; states are filled/empty/socketed_unallocated/other_spec and must match the packet-derived jewel socket view",
            },
        },
        "sourceSkillGroupReviewTemplate": {
            "groupRef": "read_research_case(section=skill-groups) 返回的精确 groupRef",
            "researchDisposition": "represented | not_relevant | needs_followup",
            "supportDisposition": (
                "packaged | source_has_no_supports | not_applicable | source_coverage_gap"
            ),
            "affectedRecords": ["与 deepResearchRecords.title 完全一致的标题"],
            "reason": "一句话说明该启用组如何处理；gap 会使验收保持 partial",
        },
        "pobReadbackAuditTemplate": {
            "disposition": "reviewed | unavailable | unmodelled",
            "readbackRef": "reviewed/unmodelled 必须原样填写 pob-readback 分区的 snapshotRef；unavailable 不填写",
            "reason": "说明数值读回可用性或未建模边界",
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
                "matchKind": "direct | redirect | search_candidate | local_corpus",
                "relevanceReason": "Research Agent 阅读页面内容后，说明它为何支持、反驳或未回答当前 claim",
            },
            "corroboration": ["source_artifact", "pinned_pob_static"],
            "decision": "keep",
        },
        "recordTemplate": {
            "recordKind": "mechanic_chain",
            "sourceClaimKey": "default",
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
            "sourceStateScope": "unknown",
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
            "verificationTasks": ["用 PoB 读回验证 <机制> 的 <数值>，记录实测是否符合预期"],
            "transferScope": "family",
            "availability": "standard",
            "sourceSpecificComponentNames": [],
            "transferRationale": "若选择 component，说明移除原 Family 名称后为何仍可迁移。",
            "applicabilityRequirements": [],
            "exclusionConditions": [],
            "claimScopeReview": {
                "evidenceScope": "current_case",
                "claimScope": "case_only",
                "verdict": "supported",
                "reason": "Research Agent 确认文本只表达当前案例证据，没有作总体频率外推",
                "safeEvidenceRefs": [artifact_identity["safeEvidenceRef"]],
            },
        },
        "semanticEdgeTemplate": {
            "source_key": "resolved skill:... / unique:pob:... / keystone:pob:0_5:... stable key",
            "target_key": "resolved stable key of the other endpoint",
            "edge_type": "enables_mechanic | scales_with | mitigates_weakness_of | creates_failure_risk_for | requires_transition_gate | has_modelability_caveat | synergizes_with",
            "rationale": "一句可核查的因果/关系说明",
            "source_resolution": {
                "tool_name": "resolve_graph_component",
                "status": "resolved",
                "stable_key": "端点的 stable key（与 source_key 相同）",
                "snapshot_id": "resolve 返回的 snapshotId",
                "evidence_path_nodes": ["resolve 返回的 evidencePath.nodes（含本端点 stable key）"],
                "source_refs": ["resolve 返回的 sourceRefs"],
            },
            "target_resolution": {
                "tool_name": "resolve_graph_component",
                "status": "resolved",
                "stable_key": "端点的 stable key（与 target_key 相同）",
                "snapshot_id": "resolve 返回的 snapshotId",
                "evidence_path_nodes": ["resolve 返回的 evidencePath.nodes（含本端点 stable key）"],
                "source_refs": ["resolve 返回的 sourceRefs"],
            },
            "source_case_refs": [artifact_identity["caseRef"]],
            "safe_evidence_refs": [artifact_identity["safeEvidenceRef"]],
            "game_patch": version_context["gamePatch"],
            "passive_tree_version": version_context["passiveTreeVersion"],
            "pob_version_or_commit": version_context["pobVersionOrCommit"],
            "status": "valid",
            "confidence": "medium",
            "modelability": "partial",
            "copy_safety_state": "passed",
            "context_requirements": [
                {
                    "context_type": "version_context",
                    "game_patch": version_context["gamePatch"],
                    "passive_tree_version": version_context["passiveTreeVersion"],
                    "pob_version": version_context["pobVersionOrCommit"],
                }
            ],
            "affected_component_keys": ["source_key", "target_key"],
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledge_scope": "global_seed",
            "directionality": "directional | associative（synergizes_with 必须 associative）",
        },
        "mandatoryChecks": list(RESEARCH_MANDATORY_CHECKS),
        "rules": [
            "只能使用 allowedValues 中的枚举；不得自造 role、axis 或 patternType。",
            "artifactIdentity、sampleId、researchGroupId、caseRef、safeEvidenceRef 和版本字段由当前 lease 注入；不要在记录或候选中重复抄写。",
            "role 表达组件在 BD 中的功能；节点类型由 resolver 证明，并按 componentRoleNodeTypeCompatibility 检查。",
            "primary_damage 是唯一的主输出角色，两条规则互补而非重复：①记录级——每个 "
            "skill_package / mechanic_chain 身份记录必须声明至少一个 primary_damage 组件，否则无法"
            "锚定 Family 身份；②组级——同一 researchGroupId 的记录必须使用同一个 ascendancyKey，且"
            "该组 primary_damage 集合应恰好等于该 BD 真正的主输出技能集合：同一 BD 有多个主输出时"
            "全部声明（集合语义，合法），clear_skill / boss_skill / triggered_payload 等副技能和 "
            "trigger_host 不得标为 primary_damage；参与 Family 技能身份判断的主动技能角色全是 "
            "clear/boss/triggered/trigger_host 的纯副技能包不需要自己的 primary_damage 声明，"
            "support_modifier 等非主动技能组件不改变该豁免；标错集合会产生 sibling Family。",
            "只有 skill_package 和已确认 mechanic_chain 能授权 BuildFamily 归档。Family identity key 只由升华与 primary_damage 技能集合决定；clear_skill、boss_skill、triggered_payload 自动进入 Family 核心副技能元数据但不改变 key。trigger_host 不自动进入该元数据（换宿主视为变体），需要保留为 Family-core 时必须显式声明进 familyCoreSkillKeys；modelability_caveat、failure_mode 或 open_question 中的未证实组件不会授权 Family，也不得在这些记录里填写 familyCoreSkillKeys。",
            "必须为整个 researchGroup 的每个 Family 核心技能组提供 typedPayload.supportPackages，且每组至少两个已解析辅助；若来源确实缺失或技能不接受普通辅助，使用 supportCoverageExceptions 明确 source_coverage_gap 或 not_applicable，不能只在正文提辅助。",
            "来源组静态校验会对不兼容的技能-辅助对（unsupportedSourceSupportPairs）整条 defer 声明它们的记录：结构化组件同时含该技能与该辅助 key、或同一句正文精确提到两者，都会触发；被拒的 unsupportedPairs 会带 triggeringSegment 引用触发句，先改句再重验。声明某技能时，正文不要在同一句提及静态不兼容的辅助（如把玩家攻击类辅助写在召唤/野兽技能句子里）。",
            "正文使用来源中的具体主动技能或辅助名称时，也应把它写入 components；validate-only 会报告来源名称与结构化组件之间的缺口。仅正文提及不会阻塞，但某证据记录（skill_package/mechanic_chain/rotation）已结构化其 active skill 而该组仍有 ≥2 个辅助完全未打包时，support 覆盖会判定为 evidence_missing；不要只把辅助名称写进正文而省略 components/supportPackages。",
            "passiveAscendancy covered 必须有 ascendancy_shell，并在 typedPayload.ascendancyResponsibilities 写具体升华节点/职责；验收会核验该节点在物理图中确实 belongs_to 当前升华。",
            "gearRoles covered 必须有 gear_synergy：已解析武器/暗金在 typedPayload.gearResponsibilities 写明具体职责；纯稀有/魔法装（无图节点）必须显式填写 gearResponsibilities=[]，并在 content 写明槽位+目标词条+档位追求，即为 content 型装备证据（字段缺失/null 不算声明；该记录仍须含 ≥1 已解析组件作锚点）。只有防御或便利装备不足以代表构筑身份装备已还原。依赖身份装备的机制和 component transfer 必须包含对应装备职责。",
            "gearRoles 为 evidence_missing 时，accept 会暂缓 mechanic_chain 和 component transfer，避免遗漏身份装备后把实例机制写成通用知识；补齐装备职责或确认 not_applicable 后再提交。",
            "若装备分区显示 itemStates 包含 mutated，依赖该随机实例的记录写 availability=source_specific_random，并在 sourceSpecificComponentKeys 指出对应装备。该知识只解释本案，不进入常规 Create 召回或 planner pattern。",
            "依赖随机实例的 candidateReview 也写 availability=source_specific_random，并在 sourceSpecificComponentNames 精确指出对应组件。accept 只用这些组件建立 observation 索引；组件无法解析时保留无组件索引的案例备注，不生成 planner pattern。",
            "resource_engine 若依赖法力偷取、普通药剂或装备词缀等无物理图节点机制，必须在 typedPayload.resourceMechanisms 写 lower_snake_case 标签，例如 mana_leech、mana_flask；否则无法生成 knowledge key。",
            "组件已被 resolve_graph_component 唯一解析时，将返回的 stable key 写入 componentKey。宿主没有 resolver 时，supportPackages 可用 skillName/supportNames，升华和装备职责可用 componentName；accept 只对同一记录中唯一解析的精确名称做 stable-key 替换。",
            "classKey 和 ascendancyKey 必须是图节点 stable key（例如 class:monk、ascendancy:monk:martial_artist），不能写显示名（Monk / Martial Artist）；显示名会导致端点校验失败。",
            "更细的轮转、窗口和证据语义写入 content、typedPayload、conditions 或 summary。",
            "只在独立重建完成后，可用 explain_mechanic/search_mechanics 和 lookup_mechanic 复核触发、前置条件、资源流、转换或变形等高风险结论，并把结果写入 mechanicAudit；lookup_mechanic 命中时使用其返回的 revision-pinned sourceRef。wiki 无对应页面是常态，不要求为此标注或降级。",
            "机制全文搜索只产生候选；选中后按精确标题重新读取正文，由 Research Agent 填写 supports/contradicts/silent 和 relevanceReason。direct/redirect/page ID 只证明页面身份，不能授权语义结论。",
            "每条 mechanic_chain 和 resource_engine 都必须被至少一个 mechanicAudit.affectedRecords 精确引用；claim 必须写该对象实际依赖的最强因果结论，不能只审计一个更弱的前提。",
            "每次 lookup_mechanic 只查询一个精确 Wiki 页面或一个中央机制名称，不得把 A / B 组件名拼成一次查询。一个关系需要多页证据时，提交多条关联同一对象的原子 mechanicAudit。",
            "poe2wiki 只能作为机制解释的校对证据，不能替代来源实例归属、support 兼容性、武器状态、数值 Judge 或 Family 身份证据；每条 mechanicAudit 条目都必须填写至少一种 corroboration（source_artifact / pinned_pob_static / typed_graph / typed_support_compatibility / local_mechanics / judge_readback 任选，样本来源即可，silent/unavailable 条目同样适用），wiki 不是 corroboration 的替代品。",
            "wiki contradicted 但仍 keep 的对象、主动 decision=defer 的对象以及没有其他 corroboration 的 wiki-only 对象会被最小范围暂缓；wiki unavailable 不会自动阻塞无关对象。",
            "每个 covered 维度必须有具体记录证据；证据不足时填 evidence_missing。",
            "先写 safe review，再运行 accept --validate-only；修复全部 invalid_schema 后才能正式 accept。",
            "safe review 使用 UTF-8、两空格缩进的多行 JSON，确保有界修复能精确编辑单个字段。",
            "单样本只能形成 case_observation；不得用任何语言作总体频率外推。每个 candidateReview 必须提交 claimScopeReview，由 Research Agent 以 typed scope 明确确认当前文字的证据范围。",
            "transferScope=component 只用于有明确因果链、最低适用条件、排除条件和验证任务的跨 Family 候选；普通案例事实使用 family。",
            "单案例不得提交 transferScope=global。公用知识由后端依据跨 Family 证据晋升，且最高只到 likely_pattern。",
            "不要为了产出公用知识而强行标记 component；不确定时保持 family。",
            "support 配对以 review 内的组合 fixed-point 校验为准（support_skill_group_candidates，模拟 PoB 技能组实际生效性）；独立的 support_skill_candidate 单对查询仅用于候选发现，结论不一致时以组合校验为准。",
            "resolverQuery 必须是可解析查询：完整 stable key、id-mapping external_id、归一化 alias 或归一化显示名（如 Blood Mage、The Hammer of Faith）。不得把 key 尾段（如 snake_case 带撇号形式 beira's_anguish、hysseg's_claw）当作 resolverQuery——它必然解析失败，且失败时组件会被排除出 gearResponsibilities 等引用。",
            "多实体/兵种类技能（Skeletal*/Spectre/Companion 等）的 stable key 通常为 Summon* 复数形式（如 skill:SummonSkeletalStormMagesPlayer）；同类宝石可能同时存在 Command*/Summon* 双端点，先 search_graph_components 再 resolve，不要凭直觉猜 key。",
            "Family 决策清单：Family identity key = 升华 + primary_damage 技能集合；clear_skill / boss_skill / triggered_payload 自动进入核心副技能元数据，secondary_skill / generator / control_skill / trigger_host 不自动进入，需要保留时显式写入 typedPayload.familyCoreSkillKeys（仅限 skill_package/mechanic_chain 记录）。只有写错 primary 集合会产生 sibling Family；副技能集合错误会污染元数据与 support 覆盖，但不会改变 Family key。",
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
        "reviewContractVersion": research_contracts.SAFE_REVIEW_CONTRACT_VERSION,
        "safeArtifactOnly": True,
        "artifactIdentity": _lease_artifact_identity(row),
        "knowledgeScope": _authoritative_knowledge_scope(row),
        "caseCoverage": {
            "supports": "evidence_missing",
            "rotation": "evidence_missing",
            "passiveAscendancy": "evidence_missing",
            "gearRoles": "evidence_missing",
            "resourceDefense": "evidence_missing",
        },
        "mechanicAudit": [],
        "memoryUse": {"queries": []},
        "sourceSkillGroupReviews": [],
        "pobReadbackAudit": [],
        "deepResearchRecords": [],
        "candidateReviews": [],
        "semanticEdges": [],
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


def load_review_payload(
    *,
    lease_token: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Read the lease-bound safe review for typed MCP editing without exposing its path."""

    output_root = Path(output_dir)
    row = _case_for_valid_lease(_queue_db_path(output_root, queue_db_path), lease_token)
    review_file = _suggested_review_file(
        output_dir=output_root,
        sample_id=str(row["sample_id"]),
        lease_token=lease_token,
    )
    review_path = output_root / review_file
    if not review_path.is_file():
        raise ValueError("lease-bound review is not initialized")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(review, dict):
        raise ValueError("lease-bound review must be a JSON object")
    acceptance._assert_safe(review)
    result = {
        "status": "loaded",
        "sampleId": str(row["sample_id"]),
        "review": review,
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_payload(result)
    return result


def save_review_payload(
    *,
    lease_token: str,
    review_payload: dict[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    _allow_accept_recovery: bool = False,
) -> dict[str, Any]:
    """Atomically persist a safe in-memory review owned by the active lease."""

    output_root = Path(output_dir)
    db_path = _queue_db_path(output_root, queue_db_path)
    row = (
        _case_for_review_save(db_path, lease_token)
        if _allow_accept_recovery
        else _case_for_valid_lease(db_path, lease_token)
    )
    review_file = _suggested_review_file(
        output_dir=output_root,
        sample_id=str(row["sample_id"]),
        lease_token=lease_token,
    )
    review_path = output_root / review_file
    if not review_path.is_file():
        raise ValueError("lease-bound review is not initialized")
    canonical = _canonical_review_payload(
        payload=copy.deepcopy(review_payload),
        sample_id=str(row["sample_id"]),
        source_hash_ref=str(row["source_hash_ref"]),
        packet_safe_hash=str(row["packet_safe_hash"]),
        version_context=_queue_version_context(db_path),
    )
    acceptance._assert_safe(canonical)
    if str(row["status"]) in {"accepting", "accepted"}:
        _assert_matching_inflight_review(
            db_path=db_path,
            row=row,
            review_payload=canonical,
            expected_origin_state=str(row["accept_origin_state"] or "claimed"),
        )
    else:
        serialized = json.dumps(canonical, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        staging = review_path.with_name(f".{review_path.name}.{secrets.token_hex(8)}.tmp")
        try:
            staging.write_text(serialized, encoding="utf-8", newline="\n")
            os.replace(staging, review_path)
        finally:
            staging.unlink(missing_ok=True)
    result = {
        "status": "saved",
        "sampleId": str(row["sample_id"]),
        "reviewFile": review_path.relative_to(output_root.resolve()).as_posix(),
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_payload(result)
    return result


def _slice_review_for_record(
    review: dict[str, Any],
    record_index: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    records = review.get("deepResearchRecords") or []
    selected = records[record_index]
    title = str(selected.get("title") or "") if isinstance(selected, dict) else ""
    matching_title_count = sum(
        1
        for record in records
        if isinstance(record, dict) and str(record.get("title") or "") == title
    )
    title_is_unique = bool(title) and matching_title_count == 1
    kept_audits: list[dict[str, Any]] = []
    out_of_slice_references: list[str] = []
    ambiguous_audit_count = 0
    audits = review.get("mechanicAudit") or []
    for audit in audits:
        if not isinstance(audit, dict):
            continue
        affected_records = [
            str(value).strip() for value in audit.get("affectedRecords") or [] if str(value).strip()
        ]
        if title not in affected_records:
            out_of_slice_references.extend(affected_records)
            continue
        if not title_is_unique:
            ambiguous_audit_count += 1
            out_of_slice_references.extend(affected_records)
            out_of_slice_references.extend(
                str(value).strip()
                for value in audit.get("affectedCandidates") or []
                if str(value).strip()
            )
            continue
        narrowed = copy.deepcopy(audit)
        out_of_slice_references.extend(value for value in affected_records if value != title)
        out_of_slice_references.extend(
            str(value).strip()
            for value in narrowed.get("affectedCandidates") or []
            if str(value).strip()
        )
        narrowed["affectedRecords"] = [title]
        narrowed["affectedCandidates"] = []
        kept_audits.append(narrowed)
    group_reviews = review.get("sourceSkillGroupReviews") or []
    kept_group_reviews: list[dict[str, Any]] = []
    for group_review in group_reviews:
        if not isinstance(group_review, dict):
            kept_group_reviews.append(group_review)
            continue
        affected_records = [
            str(value).strip()
            for value in group_review.get("affectedRecords") or []
            if str(value).strip()
        ]
        if not affected_records:
            kept_group_reviews.append(copy.deepcopy(group_review))
            continue
        if title not in affected_records:
            out_of_slice_references.extend(affected_records)
            continue
        narrowed = copy.deepcopy(group_review)
        out_of_slice_references.extend(value for value in affected_records if value != title)
        narrowed["affectedRecords"] = [title]
        kept_group_reviews.append(narrowed)
    candidates = review.get("candidateReviews") or []
    edges = review.get("semanticEdges") or []
    sliced = {
        **review,
        "deepResearchRecords": [selected],
        "candidateReviews": [],
        "semanticEdges": [],
        "mechanicAudit": kept_audits,
        "sourceSkillGroupReviews": kept_group_reviews,
    }
    context = {
        "recordIndex": record_index,
        "recordTitle": title,
        "excludedMechanicAuditCount": max(0, len(audits) - len(kept_audits)),
        "excludedCandidateCount": len(candidates),
        "excludedSemanticEdgeCount": len(edges),
        "outOfSliceReferences": sorted(set(out_of_slice_references)),
    }
    if not title_is_unique:
        context["ambiguousRecordTitle"] = title
        context["ambiguousMechanicAuditCount"] = ambiguous_audit_count
    return sliced, context


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
    only_record: int | None = None,
    intake_ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate or accept a safe Researcher proposal for the current lease."""
    output_root = Path(output_dir)
    db_path = _queue_db_path(output_root, queue_db_path)
    if not validation_only:
        research_memory.ResearchMemoryService(
            db_path=Path(memory_db_path), initialize_store=True
        )
        with _ACCEPT_LOCK, interprocess_file_lock(_accept_lock_path(memory_db_path)):
            recovered = _recover_accepting_case(
                db_path=db_path,
                lease_token=lease_token,
                review_file=Path(review_file),
                output_root=output_root,
                memory_db_path=Path(memory_db_path),
                intake_ledger_path=(
                    Path(intake_ledger_path)
                    if intake_ledger_path is not None
                    else DEFAULT_INTAKE_LEDGER_PATH
                ),
            )
        if recovered is not None:
            return recovered
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
        version_context=version_context,
    )
    authoritative_scope = _authoritative_knowledge_scope(row)
    review_contract_version = str(review_payload.get("reviewContractVersion") or "")
    if review_contract_version not in {
        research_contracts.LEGACY_SAFE_REVIEW_CONTRACT_VERSION,
        research_contracts.SAFE_REVIEW_CONTRACT_VERSION,
    }:
        result = {
            # This check runs before the accepting CAS. The row is still claimed and the same
            # lease remains authoritative, so do not pretend retry-accept is now available.
            "status": "validation_failed",
            "errorCode": "review_contract_upgrade_required",
            "sampleId": sample_id,
            "validationOnly": validation_only,
            "readyForAccept": False,
            "fullyResolvedForAccept": False,
            "queueStateChanged": False,
            "nextAction": (
                "Upgrade the existing review in place, then rerun ordinary accept with the same "
                "lease token."
            ),
            "validationIssues": [
                {
                    "loc": ["reviewContractVersion"],
                    "msg": "upgrade the safe review to phase4-safe-review-v3 and complete the new Agent review fields",
                    "type": "value_error",
                }
            ],
            "noRawMatureBuildMaterial": True,
        }
        _assert_safe_payload(result)
        return result
    if (
        review_contract_version == research_contracts.LEGACY_SAFE_REVIEW_CONTRACT_VERSION
        and not validation_only
    ):
        result = {
            "status": "validation_failed",
            "errorCode": "review_contract_upgrade_required",
            "sampleId": sample_id,
            "validationOnly": False,
            "readyForAccept": False,
            "fullyResolvedForAccept": False,
            "queueStateChanged": False,
            "nextAction": "Upgrade the review in place to phase4-safe-review-v3.",
            "validationIssues": [
                {
                    "loc": ["reviewContractVersion"],
                    "msg": "new durable Research writes require phase4-safe-review-v3",
                    "type": "value_error",
                }
            ],
            "noRawMatureBuildMaterial": True,
        }
        _assert_safe_payload(result)
        return result
    submitted_scope = str(review_payload.get("knowledgeScope") or authoritative_scope)
    if submitted_scope != authoritative_scope:
        result = {
            "status": "validation_failed",
            "errorCode": "knowledge_scope_mismatch",
            "sampleId": sample_id,
            "validationOnly": validation_only,
            "readyForAccept": False,
            "fullyResolvedForAccept": False,
            "queueStateChanged": False,
            "validationIssues": [
                {
                    "loc": ["knowledgeScope"],
                    "msg": "knowledgeScope is server-owned and must match source provenance",
                    "type": "value_error",
                }
            ],
            "noRawMatureBuildMaterial": True,
        }
        _assert_safe_payload(result)
        return result
    _bind_authoritative_review_scope(
        review_payload,
        row=row,
        mismatch_error="knowledgeScope is server-owned and must match source provenance",
    )
    source_skill_manifest = _optional_acceptance_skill_manifest(
        row=row,
        output_root=output_root,
        temp_root=temp_root,
    )
    pob_readback = _optional_pob_readback(
        row=row,
        output_root=output_root,
        temp_root=temp_root,
    )
    jewel_counts = _optional_jewel_counts(
        row=row,
        output_root=output_root,
        temp_root=temp_root,
    )
    if validation_only:
        review_payload_for_run = review_payload
        single_record: int | None = None
        slice_context: dict[str, Any] | None = None
        if only_record is not None:
            records = review_payload_for_run.get("deepResearchRecords") or []
            if not 0 <= only_record < len(records):
                raise ValueError(
                    f"--only-record {only_record} out of range; the review has "
                    f"{len(records)} deep records"
                )
            review_payload_for_run, slice_context = _slice_review_for_record(
                review_payload_for_run,
                only_record,
            )
            single_record = only_record
        source_skill_manifest_for_run = source_skill_manifest
        if single_record is not None and isinstance(source_skill_manifest, dict):
            retained_group_refs = {
                str(item.get("groupRef") or "")
                for item in review_payload_for_run.get("sourceSkillGroupReviews") or []
                if isinstance(item, dict) and str(item.get("groupRef") or "")
            }
            source_skill_manifest_for_run = {
                **source_skill_manifest,
                "activeSkillGroups": [
                    group
                    for group in source_skill_manifest.get("activeSkillGroups") or []
                    if isinstance(group, dict)
                    and str(group.get("groupRef") or "") in retained_group_refs
                ],
            }
        report = acceptance.accept_deep_review_candidates(
            db_path=Path(memory_db_path),
            json_output=output_root / "unused-validation-report.json",
            md_output=output_root / "unused-validation-report.md",
            review_file=safe_review_file,
            version_context=version_context,
            source_skill_manifest=source_skill_manifest_for_run,
            pob_readback=pob_readback,
            jewel_counts=jewel_counts,
            review_payload=review_payload_for_run,
            require_deep_records=True,
            validation_only=True,
        )
        result = _validation_only_result(report, sample_id=sample_id)
        effective_ledger = (
            Path(intake_ledger_path)
            if intake_ledger_path is not None
            else DEFAULT_INTAKE_LEDGER_PATH
        )
        result["durableWritePreflight"] = _durable_write_preflight(
            memory_db_path=Path(memory_db_path),
            intake_ledger_path=effective_ledger,
            requires_intake_ledger=str(row["character_ref"] or "").startswith("character-hash:"),
        )
        if single_record is not None:
            result["singleRecordValidation"] = {
                "recordIndex": single_record,
                "note": "Only this record was validated; caseCoverage, Family identity and "
                "deferred counts reflect the single-record slice, not the full review.",
            }
            result["sliceContext"] = slice_context or {}
        _assert_safe_payload(result, allow_core_mechanisms=True)
        return result

    if only_record is not None:
        raise ValueError("--only-record is only supported together with --validate-only")

    accept_dir = (
        Path(acceptance_output_dir) if acceptance_output_dir else output_root / "acceptance"
    )
    accept_dir.mkdir(parents=True, exist_ok=True)
    # Same lease reference normalization as _suggested_review_file so the acceptance artifact
    # basename and the review basename derive from the identical slug.
    slug = f"{_slug(sample_id)}-{_slug(lease_token)[:12]}"
    run_id = str(_read_metadata(db_path).get("runId") or output_root.name)
    canonical_review_hash = research_runtime.stable_hash(review_payload)
    accept_attempt_key = research_runtime.accept_attempt_key(
        run_id=run_id,
        sample_id=sample_id,
        packet_safe_hash=str(row["packet_safe_hash"]),
        canonical_review_hash=canonical_review_hash,
        contract_version=review_contract_version,
        expected_origin_state="claimed",
    )
    with _ACCEPT_LOCK, interprocess_file_lock(_accept_lock_path(memory_db_path)):
        _begin_accepting(
            db_path,
            row=row,
            lease_token=lease_token,
            accept_attempt_key=accept_attempt_key,
        )
        try:
            report = acceptance.accept_deep_review_candidates(
                db_path=Path(memory_db_path),
                json_output=accept_dir / f"{slug}-acceptance.json",
                md_output=accept_dir / f"{slug}-acceptance.md",
                review_file=safe_review_file,
                version_context=version_context,
                source_skill_manifest=source_skill_manifest,
                pob_readback=pob_readback,
                jewel_counts=jewel_counts,
                review_payload=review_payload,
                require_deep_records=True,
                acceptance_context={
                    "runRef": f"research-run:{run_id}",
                    "sampleId": sample_id,
                    "acceptAttemptKey": accept_attempt_key,
                    "packetSafeHash": str(row["packet_safe_hash"]),
                    "canonicalReviewHash": canonical_review_hash,
                    "contractVersion": review_contract_version,
                    "expectedOriginState": "claimed",
                    "sourceContext": _acceptance_source_context(row, version_context, pob_readback),
                    "supplement": bool(row["supplement"]),
                },
            )
        except Exception:
            receipt_ref = research_runtime.write_receipt_ref(f"research-run:{run_id}", sample_id)
            receipt = research_memory.ResearchMemoryService(
                db_path=Path(memory_db_path), initialize_store=False
            ).get_research_write_receipt(receipt_ref)
            if receipt is None or str(receipt.get("acceptAttemptKey") or "") != accept_attempt_key:
                _finish_accepting_after_exception(db_path, row=row, lease_token=lease_token)
            raise
        accepted = str(report.get("status") or "") == "accepted"
        supplement_no_gain = str(report.get("errorCode") or "") == "supplement_no_gain"
        if supplement_no_gain:
            accepted = False
        status = "accepted" if accepted else "acceptance_rejected"
        ledger_finalization = "not_required"
        if accepted and str(row["character_ref"] or "").startswith("character-hash:"):
            effective_ledger = (
                Path(intake_ledger_path)
                if intake_ledger_path is not None
                else DEFAULT_INTAKE_LEDGER_PATH
            )
            ledger_finalization = research_intake_ledger.finalize_accepted(
                effective_ledger,
                league=str(row["league"] or ""),
                character_ref=str(row["character_ref"] or ""),
                source_hash=str(row["source_hash"] or ""),
                sample_id=sample_id,
            )
            if ledger_finalization == "conflict":
                with closing(_connect_queue(db_path)) as conn, conn:
                    conn.execute(
                        "UPDATE cases SET finalization_status = 'ledger_conflict', updated_at = ? "
                        "WHERE sample_id = ? AND status = 'accepting' "
                        "AND accept_attempt_key = ?",
                        (_now_iso(), sample_id, accept_attempt_key),
                    )
                    conn.commit()
                result = {
                    "status": "finalization_pending",
                    "sampleId": sample_id,
                    "acceptAttemptKey": accept_attempt_key,
                    "writeReceiptRef": report.get("writeReceiptRef"),
                    "ledgerFinalization": ledger_finalization,
                    "memoryCommitted": True,
                    "retryable": True,
                    "noRawMatureBuildMaterial": True,
                }
                _assert_safe_payload(result)
                return result
        with closing(_connect_queue(db_path)) as conn, conn:
            cur = conn.execute(
                """
                UPDATE cases
                   SET status = ?,
                       accepted_at = ?,
                       updated_at = ?,
                       lease_token = CASE WHEN ? THEN lease_token ELSE NULL END,
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       acceptance_status = ?,
                       accepted_pattern_count = ?,
                       accepted_deep_record_count = ?,
                       accepted_semantic_edge_count = ?,
                       unresolved_deep_record_component_count = ?,
                       research_quality_summary = ?,
                       deferred_candidate_count = ?
                       ,accept_attempt_key = ?
                       ,write_receipt_ref = ?
                       ,finalization_status = ?
                 WHERE sample_id = ?
                   AND status = 'accepting'
                   AND lease_token = ?
                   AND packet_safe_hash = ?
                """,
                (
                    status,
                    _now_iso() if accepted else "",
                    _now_iso(),
                    int(accepted),
                    str(
                        report.get("status")
                        if accepted
                        else report.get("errorCode") or report.get("status") or ""
                    ),
                    int(report.get("acceptedPatternCount") or 0),
                    int(report.get("acceptedDeepRecordCount") or 0),
                    int(report.get("acceptedSemanticEdgeCount") or 0),
                    int(report.get("unresolvedDeepRecordComponentCount") or 0),
                    json.dumps(
                        _research_quality_summary(report), ensure_ascii=False, sort_keys=True
                    ),
                    int(report.get("deferredCandidateCount") or 0),
                    accept_attempt_key,
                    str(report.get("writeReceiptRef") or "") or None,
                    "complete" if accepted else "rejected",
                    sample_id,
                    lease_token,
                    str(row["packet_safe_hash"]),
                ),
            )
            conn.commit()
        if cur.rowcount != 1:
            raise ValueError("lease was modified before accept could be committed")
        if accepted:
            # The case is durably recorded: its transient packet is no longer needed. Best-effort
            # cleanup so a file-lock hiccup never turns a successful accept into an error.
            try:
                effective_temp_root = _effective_temp_root(temp_root, output_root=output_root)
                research_packet.cleanup_packets_by_safe_hashes(
                    {str(row["packet_safe_hash"])},
                    temp_root=effective_temp_root,
                )
            except (OSError, ValueError):
                pass
    result = {
        "status": status,
        "errorCode": report.get("errorCode") if not accepted else None,
        "sampleId": sample_id,
        "packetSafeHash": str(row["packet_safe_hash"]),
        "acceptAttemptKey": accept_attempt_key,
        "writeReceiptRef": report.get("writeReceiptRef"),
        "ledgerFinalization": ledger_finalization,
        "acceptedPatternCount": int(report.get("acceptedPatternCount") or 0),
        "acceptedDeepRecordCount": int(report.get("acceptedDeepRecordCount") or 0),
        "acceptedSemanticEdgeCount": int(report.get("acceptedSemanticEdgeCount") or 0),
        "createdDeepRecordCount": int(report.get("createdDeepRecordCount") or 0),
        "updatedDeepRecordCount": int(report.get("updatedDeepRecordCount") or 0),
        "unchangedDeepRecordCount": int(report.get("unchangedDeepRecordCount") or 0),
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
        "semanticEdgeWrite": report.get("semanticEdgeWrite") or {},
        "supplement": int(row["supplement"] or 0),
        "supplementNoGain": supplement_no_gain,
        "supplementNoGainReason": (
            "Supplement research produced no created or updated deep record; the case was "
            "not accepted. Add at least one genuinely new or corrected record (the same "
            "knowledge key updates in place) and re-run accept."
            if supplement_no_gain
            else ""
        ),
        "noRawMatureBuildMaterial": True,
    }
    result, transport_diagnostics = _safe_validation_transport_report(result)
    result["copySafetyDiagnostics"] = transport_diagnostics
    _assert_safe_payload(result, allow_core_mechanisms=True)
    return result


def _recover_accepting_case(
    *,
    db_path: Path,
    lease_token: str,
    review_file: Path,
    output_root: Path,
    memory_db_path: Path,
    intake_ledger_path: Path,
) -> dict[str, Any] | None:
    _init_db(db_path, allow_create=False)
    with closing(_connect_queue(db_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM cases WHERE status IN ('accepting', 'accepted') "
            "AND lease_token = ? LIMIT 1",
            (lease_token,),
        ).fetchone()
    if row is None:
        return None
    run_id = str(_read_metadata(db_path).get("runId") or db_path.parent.name)
    safe_review_file = _resolve_review_file(review_file, output_root=output_root)
    review_payload = _assert_review_file_for_lease(
        review_file=safe_review_file,
        output_root=output_root,
        sample_id=str(row["sample_id"]),
        lease_token=lease_token,
        source_hash_ref=str(row["source_hash_ref"]),
        packet_safe_hash=str(row["packet_safe_hash"]),
        version_context=_queue_version_context(db_path),
    )
    _bind_authoritative_review_scope(
        review_payload,
        row=row,
        mismatch_error="accepting case review knowledgeScope changed during recovery",
    )
    expected_attempt_key = research_runtime.accept_attempt_key(
        run_id=run_id,
        sample_id=str(row["sample_id"]),
        packet_safe_hash=str(row["packet_safe_hash"]),
        canonical_review_hash=research_runtime.stable_hash(review_payload),
        contract_version=str(review_payload.get("reviewContractVersion") or ""),
        expected_origin_state=str(row["accept_origin_state"] or "claimed"),
    )
    if expected_attempt_key != str(row["accept_attempt_key"] or ""):
        raise ValueError("accepting case review hash does not match acceptAttemptKey")
    receipt_ref = research_runtime.write_receipt_ref(
        f"research-run:{run_id}", str(row["sample_id"])
    )
    receipt = research_memory.ResearchMemoryService(
        db_path=memory_db_path,
        initialize_store=False,
    ).get_research_write_receipt(receipt_ref)
    if receipt is None:
        if str(row["status"]) == "accepted":
            raise ValueError("accepted queue case is missing its final write receipt")
        with closing(_connect_queue(db_path)) as conn, conn:
            conn.execute(
                "UPDATE cases SET status = COALESCE(NULLIF(accept_origin_state, ''), 'claimed'), "
                "finalization_status = 'memory_not_committed', updated_at = ? "
                "WHERE sample_id = ? AND status = 'accepting' AND lease_token = ?",
                (_now_iso(), str(row["sample_id"]), lease_token),
            )
            conn.commit()
        return None
    if str(receipt.get("acceptAttemptKey") or "") != str(row["accept_attempt_key"] or ""):
        raise ValueError("accepting case receipt does not match acceptAttemptKey")
    if str(row["status"]) == "accepted":
        return {
            **_research_quality_summary(receipt.get("acceptanceSummary") or {}),
            "status": "accepted",
            "sampleId": str(row["sample_id"]),
            "acceptAttemptKey": str(row["accept_attempt_key"]),
            "writeReceiptRef": receipt_ref,
            "ledgerFinalization": "already_finalized",
            "idempotentRecovery": True,
            "responseReplay": True,
            "memoryCommitted": True,
            "noRawMatureBuildMaterial": True,
        }
    ledger_finalization = "not_required"
    if str(row["character_ref"] or "").startswith("character-hash:"):
        ledger_finalization = research_intake_ledger.finalize_accepted(
            intake_ledger_path,
            league=str(row["league"] or ""),
            character_ref=str(row["character_ref"] or ""),
            source_hash=str(row["source_hash"] or ""),
            sample_id=str(row["sample_id"]),
        )
        if ledger_finalization == "conflict":
            return {
                "status": "finalization_pending",
                "sampleId": str(row["sample_id"]),
                "acceptAttemptKey": str(row["accept_attempt_key"]),
                "writeReceiptRef": receipt_ref,
                "ledgerFinalization": ledger_finalization,
                "memoryCommitted": True,
                "retryable": True,
                "noRawMatureBuildMaterial": True,
            }
    summary = receipt.get("acceptanceSummary") or {}
    with closing(_connect_queue(db_path)) as conn, conn:
        cur = conn.execute(
            """
            UPDATE cases
               SET status = 'accepted', accepted_at = ?, updated_at = ?,
                   lease_owner = NULL, lease_expires_at = NULL,
                   acceptance_status = 'accepted',
                   accepted_pattern_count = ?, accepted_deep_record_count = ?,
                   accepted_semantic_edge_count = ?, write_receipt_ref = ?,
                   finalization_status = 'complete', research_quality_summary = ?,
                   deferred_candidate_count = ?, unresolved_deep_record_component_count = ?
             WHERE sample_id = ? AND status = 'accepting' AND accept_attempt_key = ?
            """,
            (
                _now_iso(),
                _now_iso(),
                int(summary.get("acceptedPatternCount") or 0),
                int(summary.get("acceptedDeepRecordCount") or 0),
                int(summary.get("acceptedSemanticEdgeCount") or 0),
                receipt_ref,
                json.dumps(_research_quality_summary(summary), ensure_ascii=False, sort_keys=True),
                int(summary.get("deferredCandidateCount") or 0),
                int(summary.get("unresolvedDeepRecordMentionCount") or 0),
                str(row["sample_id"]),
                str(row["accept_attempt_key"]),
            ),
        )
        conn.commit()
    if cur.rowcount != 1:
        raise ValueError("accepting case changed before receipt recovery completed")
    return {
        **_research_quality_summary(summary),
        "status": "accepted",
        "sampleId": str(row["sample_id"]),
        "acceptAttemptKey": str(row["accept_attempt_key"]),
        "writeReceiptRef": receipt_ref,
        "ledgerFinalization": ledger_finalization,
        "idempotentRecovery": True,
        "memoryCommitted": True,
        "noRawMatureBuildMaterial": True,
    }


def _recover_retry_accepting_case(
    *,
    db_path: Path,
    sample_id: str,
    review_file: Path,
    output_root: Path,
    memory_db_path: Path,
    intake_ledger_path: Path,
) -> dict[str, Any] | None:
    """Finish or replay a retry attempt from its committed Memory receipt."""

    _init_db(db_path, allow_create=False)
    with closing(_connect_queue(db_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM cases WHERE sample_id = ? "
            "AND status IN ('accepting', 'accepted') "
            "AND accept_origin_state = 'acceptance_rejected' LIMIT 1",
            (sample_id,),
        ).fetchone()
    if row is None:
        return None
    run_id = str(_read_metadata(db_path).get("runId") or db_path.parent.name)
    safe_review_file = _resolve_review_file(review_file, output_root=output_root)
    review_payload = _canonical_review_artifact_identity(
        review_file=safe_review_file,
        sample_id=str(row["sample_id"]),
        source_hash_ref=str(row["source_hash_ref"]),
        packet_safe_hash=str(row["packet_safe_hash"]),
        version_context=_queue_version_context(db_path),
    )
    _bind_authoritative_review_scope(
        review_payload,
        row=row,
        mismatch_error="retry review knowledgeScope changed during recovery",
    )
    expected_attempt_key = research_runtime.accept_attempt_key(
        run_id=run_id,
        sample_id=str(row["sample_id"]),
        packet_safe_hash=str(row["packet_safe_hash"]),
        canonical_review_hash=research_runtime.stable_hash(review_payload),
        contract_version=str(review_payload.get("reviewContractVersion") or ""),
        expected_origin_state="acceptance_rejected",
    )
    if expected_attempt_key != str(row["accept_attempt_key"] or ""):
        raise ValueError("retry review hash does not match acceptAttemptKey")
    receipt_ref = research_runtime.write_receipt_ref(
        f"research-run:{run_id}", str(row["sample_id"])
    )
    receipt = research_memory.ResearchMemoryService(
        db_path=memory_db_path,
        initialize_store=False,
    ).get_research_write_receipt(receipt_ref)
    if receipt is None:
        if str(row["status"]) == "accepted":
            raise ValueError("accepted retry case is missing its final write receipt")
        _finish_retry_accepting_after_exception(db_path, row=row)
        return None
    if str(receipt.get("acceptAttemptKey") or "") != expected_attempt_key:
        raise ValueError("retry receipt does not match acceptAttemptKey")

    ledger_finalization = "not_required"
    if str(row["character_ref"] or "").startswith("character-hash:"):
        ledger_finalization = research_intake_ledger.finalize_accepted(
            intake_ledger_path,
            league=str(row["league"] or ""),
            character_ref=str(row["character_ref"] or ""),
            source_hash=str(row["source_hash"] or ""),
            sample_id=str(row["sample_id"]),
        )
        if ledger_finalization == "conflict":
            return {
                "status": "finalization_pending",
                "sampleId": str(row["sample_id"]),
                "acceptAttemptKey": expected_attempt_key,
                "writeReceiptRef": receipt_ref,
                "ledgerFinalization": ledger_finalization,
                "memoryCommitted": True,
                "retryable": True,
                "noRawMatureBuildMaterial": True,
            }
    if str(row["status"]) == "accepted":
        return {
            **_research_quality_summary(receipt.get("acceptanceSummary") or {}),
            "status": "accepted",
            "sampleId": str(row["sample_id"]),
            "acceptAttemptKey": expected_attempt_key,
            "writeReceiptRef": receipt_ref,
            "ledgerFinalization": ledger_finalization,
            "idempotentRecovery": True,
            "responseReplay": True,
            "memoryCommitted": True,
            "noRawMatureBuildMaterial": True,
        }

    summary = receipt.get("acceptanceSummary") or {}
    with closing(_connect_queue(db_path)) as conn, conn:
        cur = conn.execute(
            """
            UPDATE cases
               SET status = 'accepted', accepted_at = ?, updated_at = ?,
                   lease_token = NULL, lease_owner = NULL, lease_expires_at = NULL,
                   acceptance_status = 'accepted',
                   accepted_pattern_count = ?, accepted_deep_record_count = ?,
                   accepted_semantic_edge_count = ?, write_receipt_ref = ?,
                   finalization_status = 'complete', research_quality_summary = ?,
                   deferred_candidate_count = ?, unresolved_deep_record_component_count = ?
             WHERE sample_id = ? AND status = 'accepting' AND accept_attempt_key = ?
            """,
            (
                _now_iso(),
                _now_iso(),
                int(summary.get("acceptedPatternCount") or 0),
                int(summary.get("acceptedDeepRecordCount") or 0),
                int(summary.get("acceptedSemanticEdgeCount") or 0),
                receipt_ref,
                json.dumps(_research_quality_summary(summary), ensure_ascii=False, sort_keys=True),
                int(summary.get("deferredCandidateCount") or 0),
                int(summary.get("unresolvedDeepRecordMentionCount") or 0),
                str(row["sample_id"]),
                expected_attempt_key,
            ),
        )
        conn.commit()
    if cur.rowcount != 1:
        raise ValueError("retry accepting case changed before receipt recovery completed")
    return {
        **_research_quality_summary(summary),
        "status": "accepted",
        "sampleId": str(row["sample_id"]),
        "acceptAttemptKey": expected_attempt_key,
        "writeReceiptRef": receipt_ref,
        "ledgerFinalization": ledger_finalization,
        "idempotentRecovery": True,
        "memoryCommitted": True,
        "noRawMatureBuildMaterial": True,
    }


def review_budget(*, review_file: str | Path) -> dict[str, Any]:
    """Report per-record content length against the durable budget.

    Matches server.knowledge.research_models._content_budget: zh-CN counts
    whitespace-stripped characters (<=400), en counts words (<=250). A record is
    within budget when its length fits or it carries a lengthExceptionReason.
    """
    payload = json.loads(Path(review_file).read_text(encoding="utf-8"))
    records = payload.get("deepResearchRecords") or []
    if not isinstance(records, list):
        raise ValueError("deep review deepResearchRecords must be a list")
    items: list[dict[str, Any]] = []
    over_budget: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"deep research record at index {index} must be an object")
        content = str(record.get("content") or "")
        lang = str(record.get("contentLanguage") or "zh-CN")
        if lang == "zh-CN":
            length = len(re.sub(r"\s+", "", content))
            budget = 400
            unit = "chars (whitespace-stripped)"
        else:
            length = len(re.findall(r"\b[\w'-]+\b", content, flags=re.UNICODE))
            budget = 250
            unit = "words"
        reason = str(record.get("lengthExceptionReason") or "") or None
        within = length <= budget or bool(reason and reason.strip())
        item = {
            "index": index,
            "recordKind": str(record.get("recordKind") or ""),
            "title": str(record.get("title") or ""),
            "contentLanguage": lang,
            "length": length,
            "budget": budget,
            "unit": unit,
            "withinBudget": within,
            "lengthExceptionReason": reason,
        }
        items.append(item)
        if not within:
            over_budget.append(
                {
                    "index": index,
                    "title": str(record.get("title") or ""),
                    "length": length,
                    "budget": budget,
                }
            )
    return {
        "status": "ok" if not over_budget else "over_budget",
        "recordCount": len(items),
        "overBudgetCount": len(over_budget),
        "items": items,
        "overBudget": over_budget,
        "note": (
            "Budget matches research_models._content_budget: zh-CN counts whitespace-stripped "
            "characters (<=400), en counts words (<=250); lengthExceptionReason exempts only an "
            "indivisible mechanism chain."
        ),
        "noRawMatureBuildMaterial": True,
    }


def save_rejected_review_payload(
    *,
    sample_id: str,
    review_payload: dict[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Replace the one safe review belonging to a rejected case before typed retry."""

    output_root = Path(output_dir)
    db_path = _queue_db_path(output_root, queue_db_path)
    row = _case_for_retry_review_save(db_path, sample_id)
    review_root = (output_root / "reviews").resolve()
    matches = sorted(review_root.glob(f"{_slug(sample_id)}-*-safe-review.json"))
    if len(matches) != 1:
        raise ValueError("rejected case must have exactly one lease-bound safe review")
    review_path = matches[0].resolve()
    review_path.relative_to(review_root)
    canonical = _canonical_review_payload(
        payload=copy.deepcopy(review_payload),
        sample_id=str(row["sample_id"]),
        source_hash_ref=str(row["source_hash_ref"]),
        packet_safe_hash=str(row["packet_safe_hash"]),
        version_context=_queue_version_context(db_path),
    )
    acceptance._assert_safe(canonical)
    if str(row["status"]) in {"accepting", "accepted"}:
        _assert_matching_inflight_review(
            db_path=db_path,
            row=row,
            review_payload=canonical,
            expected_origin_state="acceptance_rejected",
        )
    else:
        serialized = json.dumps(canonical, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        staging = review_path.with_name(f".{review_path.name}.{secrets.token_hex(8)}.tmp")
        try:
            staging.write_text(serialized, encoding="utf-8", newline="\n")
            os.replace(staging, review_path)
        finally:
            staging.unlink(missing_ok=True)
    result = {
        "status": "saved",
        "sampleId": str(row["sample_id"]),
        "reviewFile": review_path.relative_to(output_root.resolve()).as_posix(),
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
    intake_ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Retry acceptance for a previously rejected safe review artifact."""
    output_root = Path(output_dir)
    db_path = _queue_db_path(output_root, queue_db_path)
    research_memory.ResearchMemoryService(db_path=Path(memory_db_path), initialize_store=True)
    with _ACCEPT_LOCK, interprocess_file_lock(_accept_lock_path(memory_db_path)):
        recovered = _recover_retry_accepting_case(
            db_path=db_path,
            sample_id=sample_id,
            review_file=Path(review_file),
            output_root=output_root,
            memory_db_path=Path(memory_db_path),
            intake_ledger_path=(
                Path(intake_ledger_path)
                if intake_ledger_path is not None
                else DEFAULT_INTAKE_LEDGER_PATH
            ),
        )
    if recovered is not None:
        return recovered
    row = _case_for_rejected_sample(db_path, sample_id)
    version_context = _queue_version_context(db_path)
    source_skill_manifest = _optional_acceptance_skill_manifest(
        row=row,
        output_root=output_root,
        temp_root=temp_root,
    )
    if source_skill_manifest is None:
        try:
            _rebuild_packet_for_claim(
                row=row,
                output_root=output_root,
                temp_root=temp_root,
                lease_seconds=research_packet.MAX_TTL_SECONDS,
                queue_db_path=db_path,
            )
        except (OSError, ValueError):
            pass
        row = _case_for_rejected_sample(db_path, sample_id)
        source_skill_manifest = _optional_acceptance_skill_manifest(
            row=row,
            output_root=output_root,
            temp_root=temp_root,
        )
    if source_skill_manifest is None:
        result = {
            "status": "acceptance_rejected",
            "errorCode": "retry_packet_unavailable",
            "sampleId": str(row["sample_id"]),
            "readyForAccept": False,
            "fullyResolvedForAccept": False,
            "queueStateChanged": False,
            "nextAction": (
                "The source evidence packet could not be restored from the retained Research "
                "run. Requeue the source before retrying acceptance."
            ),
            "validationIssues": [
                {
                    "loc": ["artifactIdentity", "packetSafeHash"],
                    "msg": "retry requires the exact source evidence packet",
                    "type": "value_error",
                }
            ],
            "noRawMatureBuildMaterial": True,
        }
        _assert_safe_payload(result)
        return result
    pob_readback = _optional_pob_readback(
        row=row,
        output_root=output_root,
        temp_root=temp_root,
    )
    jewel_counts = _optional_jewel_counts(
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
        version_context=version_context,
    )
    review_contract_version = str(review_payload.get("reviewContractVersion") or "")
    if review_contract_version not in {
        research_contracts.LEGACY_SAFE_REVIEW_CONTRACT_VERSION,
        research_contracts.SAFE_REVIEW_CONTRACT_VERSION,
    }:
        result = {
            "status": "acceptance_rejected",
            "errorCode": "review_contract_upgrade_required",
            "sampleId": str(row["sample_id"]),
            "validationOnly": False,
            "readyForAccept": False,
            "fullyResolvedForAccept": False,
            "validationIssues": [
                {
                    "loc": ["reviewContractVersion"],
                    "msg": "upgrade the safe review to phase4-safe-review-v3 and complete the new Agent review fields",
                    "type": "value_error",
                }
            ],
            "noRawMatureBuildMaterial": True,
        }
        _assert_safe_payload(result)
        return result
    if review_contract_version == research_contracts.LEGACY_SAFE_REVIEW_CONTRACT_VERSION:
        result = {
            "status": "acceptance_rejected",
            "errorCode": "review_contract_upgrade_required",
            "sampleId": str(row["sample_id"]),
            "validationOnly": False,
            "readyForAccept": False,
            "fullyResolvedForAccept": False,
            "validationIssues": [
                {
                    "loc": ["reviewContractVersion"],
                    "msg": "new durable Research writes require phase4-safe-review-v3",
                    "type": "value_error",
                }
            ],
            "noRawMatureBuildMaterial": True,
        }
        _assert_safe_payload(result)
        return result
    authoritative_scope = _authoritative_knowledge_scope(row)
    submitted_scope = str(review_payload.get("knowledgeScope") or authoritative_scope)
    if submitted_scope != authoritative_scope:
        raise ValueError("knowledgeScope is server-owned and does not match source provenance")
    _bind_authoritative_review_scope(
        review_payload,
        row=row,
        mismatch_error="knowledgeScope is server-owned and does not match source provenance",
    )
    slug = f"{_slug(str(row['sample_id']))}-{_slug(safe_review_file.stem)[-24:]}"
    run_id = str(_read_metadata(db_path).get("runId") or output_root.name)
    canonical_review_hash = research_runtime.stable_hash(review_payload)
    accept_attempt_key = research_runtime.accept_attempt_key(
        run_id=run_id,
        sample_id=str(row["sample_id"]),
        packet_safe_hash=str(row["packet_safe_hash"]),
        canonical_review_hash=canonical_review_hash,
        contract_version=review_contract_version,
        expected_origin_state="acceptance_rejected",
    )
    with _ACCEPT_LOCK, interprocess_file_lock(_accept_lock_path(memory_db_path)):
        _begin_retry_accepting(db_path, row=row, accept_attempt_key=accept_attempt_key)
        try:
            report = acceptance.accept_deep_review_candidates(
                db_path=Path(memory_db_path),
                json_output=accept_dir / f"{slug}-acceptance.json",
                md_output=accept_dir / f"{slug}-acceptance.md",
                review_file=safe_review_file,
                version_context=version_context,
                source_skill_manifest=source_skill_manifest,
                pob_readback=pob_readback,
                jewel_counts=jewel_counts,
                review_payload=review_payload,
                require_deep_records=True,
                acceptance_context={
                    "runRef": f"research-run:{run_id}",
                    "sampleId": str(row["sample_id"]),
                    "acceptAttemptKey": accept_attempt_key,
                    "packetSafeHash": str(row["packet_safe_hash"]),
                    "canonicalReviewHash": canonical_review_hash,
                    "contractVersion": review_contract_version,
                    "expectedOriginState": "acceptance_rejected",
                    "sourceContext": _acceptance_source_context(row, version_context, pob_readback),
                    "supplement": bool(row["supplement"]),
                },
            )
        except Exception:
            receipt_ref = research_runtime.write_receipt_ref(
                f"research-run:{run_id}", str(row["sample_id"])
            )
            receipt = research_memory.ResearchMemoryService(
                db_path=Path(memory_db_path), initialize_store=False
            ).get_research_write_receipt(receipt_ref)
            if receipt is None or str(receipt.get("acceptAttemptKey") or "") != accept_attempt_key:
                _finish_retry_accepting_after_exception(db_path, row=row)
            raise
        accepted = str(report.get("status") or "") == "accepted"
        supplement_no_gain = str(report.get("errorCode") or "") == "supplement_no_gain"
        if supplement_no_gain:
            accepted = False
        status = "accepted" if accepted else "acceptance_rejected"
        ledger_finalization = "not_required"
        if accepted and str(row["character_ref"] or "").startswith("character-hash:"):
            effective_ledger = (
                Path(intake_ledger_path)
                if intake_ledger_path is not None
                else DEFAULT_INTAKE_LEDGER_PATH
            )
            ledger_finalization = research_intake_ledger.finalize_accepted(
                effective_ledger,
                league=str(row["league"] or ""),
                character_ref=str(row["character_ref"] or ""),
                source_hash=str(row["source_hash"] or ""),
                sample_id=str(row["sample_id"]),
            )
            if ledger_finalization == "conflict":
                with closing(_connect_queue(db_path)) as conn, conn:
                    conn.execute(
                        "UPDATE cases SET finalization_status = 'ledger_conflict', updated_at = ? "
                        "WHERE sample_id = ? AND status = 'accepting' "
                        "AND accept_attempt_key = ?",
                        (_now_iso(), str(row["sample_id"]), accept_attempt_key),
                    )
                    conn.commit()
                result = {
                    "status": "finalization_pending",
                    "sampleId": str(row["sample_id"]),
                    "acceptAttemptKey": accept_attempt_key,
                    "writeReceiptRef": report.get("writeReceiptRef"),
                    "ledgerFinalization": ledger_finalization,
                    "memoryCommitted": True,
                    "retryable": True,
                    "noRawMatureBuildMaterial": True,
                }
                _assert_safe_payload(result)
                return result
        with closing(_connect_queue(db_path)) as conn, conn:
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
                       accepted_semantic_edge_count = ?,
                       unresolved_deep_record_component_count = ?,
                       research_quality_summary = ?,
                       deferred_candidate_count = ?
                       ,accept_attempt_key = ?
                       ,write_receipt_ref = ?
                       ,finalization_status = ?
                 WHERE sample_id = ?
                   AND status = 'accepting'
                   AND packet_safe_hash = ?
                """,
                (
                    status,
                    _now_iso() if accepted else "",
                    _now_iso(),
                    str(
                        report.get("status")
                        if accepted
                        else report.get("errorCode") or report.get("status") or ""
                    ),
                    int(report.get("acceptedPatternCount") or 0),
                    int(report.get("acceptedDeepRecordCount") or 0),
                    int(report.get("acceptedSemanticEdgeCount") or 0),
                    int(report.get("unresolvedDeepRecordComponentCount") or 0),
                    json.dumps(
                        _research_quality_summary(report), ensure_ascii=False, sort_keys=True
                    ),
                    int(report.get("deferredCandidateCount") or 0),
                    accept_attempt_key,
                    str(report.get("writeReceiptRef") or "") or None,
                    "complete" if accepted else "rejected",
                    str(row["sample_id"]),
                    str(row["packet_safe_hash"]),
                ),
            )
            conn.commit()
        if cur.rowcount != 1:
            raise ValueError("rejected case was modified before retry accept could be committed")
        if accepted:
            # The case is durably recorded: its transient packet is no longer needed. Best-effort
            # cleanup so a file-lock hiccup never turns a successful accept into an error.
            try:
                effective_temp_root = _effective_temp_root(temp_root, output_root=output_root)
                research_packet.cleanup_packets_by_safe_hashes(
                    {str(row["packet_safe_hash"])},
                    temp_root=effective_temp_root,
                )
            except (OSError, ValueError):
                pass
    result = {
        "status": status,
        "errorCode": report.get("errorCode") if not accepted else None,
        "sampleId": str(row["sample_id"]),
        "packetSafeHash": str(row["packet_safe_hash"]),
        "acceptAttemptKey": accept_attempt_key,
        "writeReceiptRef": report.get("writeReceiptRef"),
        "ledgerFinalization": ledger_finalization,
        "acceptedPatternCount": int(report.get("acceptedPatternCount") or 0),
        "acceptedDeepRecordCount": int(report.get("acceptedDeepRecordCount") or 0),
        "acceptedSemanticEdgeCount": int(report.get("acceptedSemanticEdgeCount") or 0),
        "createdDeepRecordCount": int(report.get("createdDeepRecordCount") or 0),
        "updatedDeepRecordCount": int(report.get("updatedDeepRecordCount") or 0),
        "unchangedDeepRecordCount": int(report.get("unchangedDeepRecordCount") or 0),
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
        "semanticEdgeWrite": report.get("semanticEdgeWrite") or {},
        "supplement": int(row["supplement"] or 0),
        "supplementNoGain": supplement_no_gain,
        "supplementNoGainReason": (
            "Supplement research produced no created or updated deep record; the case was "
            "not accepted. Add at least one genuinely new or corrected record (the same "
            "knowledge key updates in place) and re-run accept."
            if supplement_no_gain
            else ""
        ),
        "noRawMatureBuildMaterial": True,
    }
    result, transport_diagnostics = _safe_validation_transport_report(result)
    result["copySafetyDiagnostics"] = transport_diagnostics
    _assert_safe_payload(result, allow_core_mechanisms=True)
    return result


def _begin_accepting(
    db_path: Path,
    *,
    row: sqlite3.Row,
    lease_token: str,
    accept_attempt_key: str,
    origin_state: str = "claimed",
) -> None:
    now = _now_iso()
    with closing(_connect_queue(db_path)) as conn, conn:
        cur = conn.execute(
            """
            UPDATE cases
               SET status = 'accepting',
                   accept_attempt_key = ?,
                   accept_origin_state = ?,
                   finalization_status = '',
                   updated_at = ?
             WHERE sample_id = ?
               AND status = 'claimed'
               AND lease_token = ?
               AND lease_expires_at > ?
               AND packet_safe_hash = ?
            """,
            (
                accept_attempt_key,
                origin_state,
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
    _init_db(db_path, allow_create=False)
    with closing(_connect_queue(db_path)) as conn, conn:
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


def _case_for_retry_review_save(db_path: Path, sample_id: str) -> sqlite3.Row:
    """Return the normal retry row or the exact in-flight retry row for replay."""

    _init_db(db_path, allow_create=False)
    with closing(_connect_queue(db_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
              FROM cases
             WHERE sample_id = ?
               AND (
                    status = 'acceptance_rejected'
                    OR (
                        status IN ('accepting', 'accepted')
                        AND accept_origin_state = 'acceptance_rejected'
                    )
               )
             LIMIT 1
            """,
            (sample_id,),
        ).fetchone()
    if row is None:
        raise ValueError("sample is not in acceptance_rejected or matching retry state")
    return row


def _begin_retry_accepting(
    db_path: Path,
    *,
    row: sqlite3.Row,
    accept_attempt_key: str,
) -> None:
    now = _now_iso()
    with closing(_connect_queue(db_path)) as conn, conn:
        cur = conn.execute(
            """
            UPDATE cases
               SET status = 'accepting',
                   accept_attempt_key = ?,
                   accept_origin_state = 'acceptance_rejected',
                   finalization_status = '',
                   updated_at = ?
             WHERE sample_id = ?
               AND status = 'acceptance_rejected'
               AND packet_safe_hash = ?
            """,
            (
                accept_attempt_key,
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
    with closing(_connect_queue(db_path)) as conn, conn:
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
    with closing(_connect_queue(db_path)) as conn, conn:
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
    intake_ledger_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    _init_db(db_path, allow_create=False)
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
        "levelMin": int(metadata.get("levelMin") or 0),
        "levelMax": int(metadata.get("levelMax") or 0),
        "localSourceInputCount": local_source_input_count,
        "requestedSampleCount": requested_sample_count,
        "expectedSourceCount": (
            int(metadata["expectedSourceCount"]) if metadata.get("expectedSourceCount") else None
        ),
        "uniqueLocalCaseCount": int(metadata.get("uniqueLocalCaseCount") or 0),
        "duplicateLocalSourceCount": int(metadata.get("duplicateLocalSourceCount") or 0),
        "requestedSupplementSampleCount": int(metadata.get("requestedSupplementSampleCount") or 0),
        "selectedSupplementSampleCount": int(metadata.get("selectedSupplementSampleCount") or 0),
        "selectedSupplementSampleIds": json.loads(
            str(metadata.get("selectedSupplementSampleIds") or "[]")
        ),
        "missingSupplementSampleCount": int(metadata.get("missingSupplementSampleCount") or 0),
        "missingSupplementSampleIds": json.loads(
            str(metadata.get("missingSupplementSampleIds") or "[]")
        ),
        "notAcceptedSupplementSampleCount": int(
            metadata.get("notAcceptedSupplementSampleCount") or 0
        ),
        "notAcceptedSupplementSampleIds": json.loads(
            str(metadata.get("notAcceptedSupplementSampleIds") or "[]")
        ),
        "unrecoverableSupplementSampleCount": int(
            metadata.get("unrecoverableSupplementSampleCount") or 0
        ),
        "unrecoverableSupplementSampleIds": json.loads(
            str(metadata.get("unrecoverableSupplementSampleIds") or "[]")
        ),
        "intakePagesFetched": int(metadata.get("intakePagesFetched") or 0),
        "intakePageRowsSeen": int(metadata.get("intakePageRowsSeen") or 0),
        "intakeSkippedAlreadyResearched": int(metadata.get("intakeSkippedAlreadyResearched") or 0),
        "intakeLedgerRecordedCount": int(metadata.get("intakeLedgerRecordedCount") or 0),
    }
    intake_ledger_source = "snapshot"
    if intake_ledger_summary is None:
        try:
            league_hint = str(rows[0]["league"] or "") if rows else ""
            live_summary = _live_intake_ledger_summary(metadata, league_hint=league_hint)
            if live_summary is not None:
                intake_ledger_summary = live_summary
                intake_ledger_source = "live"
        except Exception:  # noqa: BLE001 - report falls back to the queue-time snapshot
            intake_ledger_summary = None
    if intake_ledger_summary is None:
        try:
            persisted = json.loads(str(metadata.get("intakeLedgerSummary") or "{}"))
            if isinstance(persisted, dict) and persisted:
                intake_ledger_summary = persisted
        except (json.JSONDecodeError, TypeError):
            intake_ledger_summary = None
    return _queue_report(
        status=status_override or persisted_status or "ok",
        db_path=db_path,
        requested_worker_count=_effective_worker_count(
            metadata.get("requestedWorkerCount") or DEFAULT_WORKER_COUNT
        ),
        cases=rows,
        dry_run=False,
        inserted_count=inserted_count,
        duplicate_count=duplicate_count,
        source_input_summary=source_input_summary,
        intake_ledger_summary=intake_ledger_summary,
        intake_ledger_source=intake_ledger_source,
    )


def _pending_cleanup_path(runs_root: Path) -> Path:
    return runs_root / "pending_cleanups.json"


def _read_pending_cleanups(runs_root: Path) -> list[dict[str, Any]]:
    path = _pending_cleanup_path(runs_root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _write_pending_cleanups(runs_root: Path, items: list[dict[str, Any]]) -> None:
    path = _pending_cleanup_path(runs_root)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    payload = {"version": 1, "items": items}
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _queue_pending_cleanup(runs_root: Path, *, run_id: str, evidence: dict[str, Any]) -> None:
    items = [item for item in _read_pending_cleanups(runs_root) if item.get("runId") != run_id]
    items.append(
        {
            "runId": run_id,
            "queuedAt": _now_iso(),
            "evidence": evidence,
        }
    )
    _write_pending_cleanups(runs_root, items)


def _drop_pending_cleanup(runs_root: Path, run_id: str) -> None:
    items = [item for item in _read_pending_cleanups(runs_root) if item.get("runId") != run_id]
    _write_pending_cleanups(runs_root, items)


def _probe_locked_files(output_root: Path, *, max_depth: int = 3) -> list[str]:
    """Best-effort diagnostic: which files inside the run directory currently refuse
    a rename (a common signature of an open handle). Every probe is reverted
    immediately; results are advisory only and may race with handle changes."""

    locked: list[str] = []
    probe_suffix = ".poe-bd-cleanup-probe"
    root = output_root.resolve()

    def walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for entry in entries:
            if entry.name.endswith(probe_suffix):
                continue
            if entry.is_dir():
                walk(entry, depth + 1)
                continue
            try:
                os.rename(entry, Path(str(entry) + probe_suffix))
                os.rename(Path(str(entry) + probe_suffix), entry)
            except OSError:
                locked.append(str(entry))

    walk(root, 0)
    return locked


def _delete_run_directory(output_root: Path, staging: Path) -> tuple[str, dict[str, Any]]:
    """Delete a run, retaining its exact safe queue if removal only partly succeeds.

    A failed rmtree can already have removed the queue or raw source files. Restore
    only the safe queue so the next cleanup can recheck the original completion
    evidence; deleted source material is neither reconstructed nor claimed intact.
    """
    try:
        queue_snapshot = (output_root / QUEUE_DB_FILENAME).read_bytes()
    except OSError as exc:
        return "deferred", {
            "reason": "queue_snapshot_unavailable",
            "osError": _safe_os_error(exc),
            "retried": False,
            "hint": "The safe queue could not be preserved; no directory removal was attempted.",
        }

    def restore_missing_queue(retained_root: Path) -> dict[str, Any]:
        queue_path = retained_root / QUEUE_DB_FILENAME
        restored = False
        restore_error = None
        if not queue_path.is_file():
            temporary = retained_root / f".{QUEUE_DB_FILENAME}.{secrets.token_hex(8)}.restore"
            try:
                with temporary.open("xb") as handle:
                    handle.write(queue_snapshot)
                    handle.flush()
                    os.fsync(handle.fileno())
                if not queue_path.exists():
                    temporary.replace(queue_path)
                    restored = True
            except OSError as exc:
                restore_error = _safe_os_error(exc)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        available = queue_path.is_file()
        return {
            "queueRestored": restored,
            "queuePreserved": available,
            "queueRestoreError": restore_error,
            "recoveryRequired": not available,
            "runtimeMayBePartiallyRemoved": True,
        }
    for attempt in (1, 2, 3):
        try:
            if staging.exists():
                shutil.rmtree(staging)
            output_root.rename(staging)
            break
        except OSError as exc:
            if attempt < 3:
                time.sleep(0.5)
                continue
            return (
                "deferred",
                {
                    "reason": "directory_rename_failed",
                    "osError": _safe_os_error(exc),
                    "retried": True,
                    "lockedFiles": _probe_locked_files(output_root),
                    "hint": (
                        "another process may hold a handle inside the run directory (for "
                        "example a terminal or file explorer opened at this run directory, an "
                        "editor that keeps the review/queue files open, or an antivirus scan); "
                        "close such handles and re-run cleanup. The run was queued for a "
                        "delayed retry and remains fully intact."
                    ),
                },
            )
    try:
        shutil.rmtree(staging)
    except OSError as exc:
        try:
            shutil.rmtree(staging)
        except OSError:
            try:
                staging.rename(output_root)
                restored_from_staging = True
            except OSError:
                restored_from_staging = False
            queue_recovery = restore_missing_queue(
                output_root if restored_from_staging else staging
            )
            return (
                "deferred",
                {
                    "reason": "staging_removal_failed",
                    "osError": _safe_os_error(exc),
                    "retried": True,
                    "restoredFromStaging": restored_from_staging,
                    **queue_recovery,
                    "hint": (
                        "Directory removal partly failed. The safe queue is preserved when "
                        "queuePreserved is true; already removed source material is unavailable. "
                        "Close blocking handles and retry cleanup to recheck the same evidence."
                    ),
                },
            )
    return "cleaned", {}


def _restore_released_intake_rows(ledger_path: Path, rows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for row in rows:
        try:
            research_intake_ledger.record_case(
                ledger_path,
                league=str(row.get("league") or ""),
                character_ref=str(row.get("characterRef") or ""),
                source_hash=str(row.get("sourceHash") or ""),
                level=int(row.get("level") or 0),
                ascendancy=str(row.get("ascendancy") or ""),
                main_skill=str(row.get("mainSkill") or ""),
                sample_id=str(row.get("sampleId") or ""),
            )
        except (OSError, sqlite3.Error, ValueError):
            failures.append(str(row.get("sampleId") or ""))
    return failures


def _release_abandoned_intake_rows(
    *,
    rows: list[dict[str, Any]],
    metadata: dict[str, str],
) -> dict[str, Any]:
    ledger_path_text = str(metadata.get("intakeLedgerPath") or "").strip()
    ledger_path = Path(ledger_path_text) if ledger_path_text else DEFAULT_INTAKE_LEDGER_PATH
    released_rows: list[dict[str, Any]] = []
    accepted_preserved = 0
    missing = 0
    for row in rows:
        if str(row.get("status") or "") == "accepted":
            accepted_preserved += 1
            continue
        character_ref = str(row.get("characterRef") or "").strip()
        if not character_ref.startswith("character-hash:"):
            continue
        outcome = research_intake_ledger.release_queued_case(
            ledger_path,
            league=str(row.get("league") or ""),
            character_ref=character_ref,
            source_hash=str(row.get("sourceHash") or ""),
            sample_id=str(row.get("sampleId") or ""),
        )
        if outcome == "released":
            released_rows.append(row)
            continue
        if outcome == "accepted_preserved":
            accepted_preserved += 1
            continue
        if outcome == "missing":
            missing += 1
            continue
        rollback_failures = _restore_released_intake_rows(ledger_path, released_rows)
        return {
            "status": "rejected",
            "errorCode": "research_intake_ledger_release_failed",
            "releaseOutcome": outcome,
            "sampleId": str(row.get("sampleId") or ""),
            "releasedIntakeLedgerCount": len(released_rows),
            "ledgerRollbackFailedSampleIds": rollback_failures,
            "recoveryRequired": bool(rollback_failures),
        }
    return {
        "status": "ok",
        "ledgerPath": ledger_path,
        "releasedRows": released_rows,
        "releasedIntakeLedgerCount": len(released_rows),
        "acceptedIntakeLedgerCountPreserved": accepted_preserved,
        "missingIntakeLedgerCount": missing,
    }


def cleanup_completed_run(
    *,
    run_id: str,
    temp_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    allow_rejected: bool = False,
    abandon_incomplete: bool = False,
    memory_db_path: str | Path = DEFAULT_MEMORY_DB_PATH,
) -> dict[str, Any]:
    """Serialize cleanup with acceptance; preserve safe diagnostics before removing raw data."""
    if not isinstance(run_id, str) or not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{4}", run_id):
        return {"status": "rejected", "errorCode": "invalid_research_run_id"}
    runtime_root = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    run_db = runtime_root / RUNS_DIRNAME / run_id / QUEUE_DB_FILENAME
    # Store initialization owns the same process lock; finish it before entering
    # the non-reentrant OS lock used by acceptance and cleanup.
    research_memory.ResearchMemoryService(db_path=Path(memory_db_path))
    with (
        _ACCEPT_LOCK,
        interprocess_file_lock(_accept_lock_path(memory_db_path)),
        interprocess_file_lock(_run_lock_path(run_db)),
    ):
        return _cleanup_completed_run_locked(
            run_id=run_id, temp_root=temp_root, output_dir=output_dir,
            allow_rejected=allow_rejected, abandon_incomplete=abandon_incomplete,
            memory_db_path=memory_db_path,
        )


def _cleanup_completed_run_locked(
    *,
    run_id: str,
    temp_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    allow_rejected: bool = False,
    abandon_incomplete: bool = False,
    memory_db_path: str | Path = DEFAULT_MEMORY_DB_PATH,
) -> dict[str, Any]:
    """Delete one Research run while preserving its durable Research Memory.

    ``allow_rejected`` permits cleanup when the run also contains ``acceptance_rejected``
    cases (e.g. cases blocked by source-data gaps that can never be accepted). It is an
    explicit opt-in: at least one case must still hold accepted durable records, and the
    default stays strict.

    ``abandon_incomplete`` is a separate explicit opt-in for discarding an unfinished run.
    It releases only exact queued intake-ledger reservations owned by that run, preserves
    accepted ledger history and durable Research Memory, and rolls the releases back if the
    run directory cannot be removed.
    """

    if not isinstance(run_id, str) or not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{4}", run_id):
        return {"status": "rejected", "errorCode": "invalid_research_run_id"}
    runtime_root = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    runs_root = (runtime_root / RUNS_DIRNAME).resolve()
    output_root = (runs_root / run_id).resolve()
    if not _is_relative_to(output_root, runs_root) or output_root.parent != runs_root:
        return {"status": "rejected", "errorCode": "invalid_research_run_id"}
    # Every cleanup call first drains the delayed-retry queue so a run whose directory
    # rename failed earlier gets cleaned as soon as the blocking handle is gone.
    retried = _retry_pending_cleanups(runs_root, memory_db_path=Path(memory_db_path), current_run_id=run_id)
    if run_id in retried.get("retriedIds", []):
        # The queued retry just cleaned this exact run (evidence was captured before any
        # deletion); report it as cleaned instead of falling into not-found.
        return {
            "status": "cleaned",
            "taskKind": "research",
            "taskId": run_id,
            "removedTransientPacketCount": 0,
            "memoriesPreserved": True,
            "userExportsPreserved": True,
            "containsRawMaterial": False,
            "delayedRetry": retried,
        }
    staging = output_root.with_name(f"{output_root.name}.cleanup-staging")
    if not output_root.exists() and staging.exists():
        # Recover a run left in the cleanup-staging directory by a previous
        # interrupted cleanup (staging_removal_failed): rename it back before
        # any not-found rejection so the run stays auditable and re-cleanable.
        try:
            staging.rename(output_root)
        except OSError as exc:
            return {
                "status": "partial",
                "errorCode": "research_run_cleanup_failed",
                "detail": {
                    "reason": "staging_restore_failed",
                    "osError": _safe_os_error(exc),
                    "retried": False,
                    "hint": (
                        "a previous cleanup moved the run directory to "
                        f"{staging.name}; restoring it failed, likely because a "
                        "process holds a handle inside it. Close such handles and "
                        "re-run cleanup; the staging directory is preserved."
                    ),
                },
            }
    db_path = output_root / QUEUE_DB_FILENAME
    if not db_path.is_file():
        return {"status": "rejected", "errorCode": "research_run_not_found"}
    rows = _fetch_cases(db_path)
    metadata = _read_metadata(db_path)
    retention = research_retention.inspect_policy(metadata, rows, now=_now())
    if retention["activeLeaseCount"] or retention["invalidLeaseCount"]:
        return {"status": "rejected", "errorCode": "research_active_claim_lease", "retention": retention}
    if any(
        row.get("status") == "accepting"
        or (row.get("status") == "accepted"
            and row.get("finalizationStatus") not in (None, "", "complete"))
        for row in rows
    ):
        return {"status": "rejected", "errorCode": "research_acceptance_recovery_required"}
    retention_expired = retention["expiredCleanupAllowed"]
    discard_incomplete = abandon_incomplete or retention_expired
    if not discard_incomplete:
        allowed_statuses = {"accepted", "acceptance_rejected"} if allow_rejected else {"accepted"}
        if not rows or any(str(row.get("status") or "") not in allowed_statuses for row in rows):
            return {"status": "rejected", "errorCode": "completed_research_run_required"}
        if not any(
            int(row.get("accepted_deep_record_count") or row.get("acceptedDeepRecordCount") or 0)
            > 0
            for row in rows
        ):
            return {"status": "rejected", "errorCode": "completed_research_run_required"}

    ledger_release: dict[str, Any] = {
        "status": "ok",
        "ledgerPath": DEFAULT_INTAKE_LEDGER_PATH,
        "releasedRows": [],
        "releasedIntakeLedgerCount": 0,
        "acceptedIntakeLedgerCountPreserved": 0,
        "missingIntakeLedgerCount": 0,
    }
    preserved_receipts = _preserve_legacy_write_receipts(
        output_root=output_root,
        run_id=run_id,
        rows=rows,
        memory_db_path=Path(memory_db_path),
    )
    if preserved_receipts.get("status") != "ok":
        return preserved_receipts
    _attach_followup_completion(
        runtime_root=runtime_root, memory_db_path=Path(memory_db_path), run_id=run_id, rows=rows,
    )
    incomplete = [
        row for row in rows if row.get("status") == "accepted"
        and row.get("effectiveResearchCompletion", research_completion.completion_summary(row)["researchCompletion"]) != "complete"
    ]
    if incomplete and not discard_incomplete:
        return {
            "status": "rejected", "errorCode": "research_followup_required",
            "incompleteSampleIds": [row.get("sampleId") for row in incomplete],
            "preservedWriteReceiptRefs": preserved_receipts.get("writeReceiptRefs") or [],
            "rawMaterialPreserved": True,
            "nextAction": "Supplement the retained source, or explicitly abandon incomplete research.",
            "noRawMatureBuildMaterial": True,
        }
    metadata = {**metadata, "cleanupReason": (
        "explicit_abandonment" if abandon_incomplete else "retention_expired" if retention_expired else "completed"
    )}
    audit = _preserve_run_audit(
        runtime_root=runtime_root, run_id=run_id, rows=rows, metadata=metadata,
        receipt_refs=preserved_receipts.get("writeReceiptRefs") or [],
        abandon_incomplete=abandon_incomplete,
    )
    if discard_incomplete:
        ledger_release = _release_abandoned_intake_rows(rows=rows, metadata=metadata)
        if ledger_release.get("status") != "ok":
            return ledger_release
    packet_hashes = {str(row.get("packetSafeHash") or "") for row in rows}
    evidence = {
        "caseCount": len(rows),
        "acceptedDeepRecordCount": sum(
            int(row.get("accepted_deep_record_count") or row.get("acceptedDeepRecordCount") or 0)
            for row in rows
        ),
        "packetSafeHashes": sorted(packet_hashes),
        "validatedAt": _now_iso(),
        "preservedWriteReceiptRefs": preserved_receipts.get("writeReceiptRefs") or [],
        "completionProtectionVersion": 1,
        "cleanupAuditHash": research_runtime.stable_hash(audit),
        "queueStateHash": research_runtime.stable_hash(_fetch_cases(db_path)),
        "followupStateHash": research_followups.state_fingerprint(runtime_root / "followups.sqlite", f"research-run:{run_id}"),
        "memoryRevision": _cleanup_memory_revision(Path(memory_db_path)),
    }
    effective_temp_root = _effective_temp_root(temp_root, output_root=output_root)
    packet_cleanup = research_packet.cleanup_packets_by_safe_hashes(
        packet_hashes,
        temp_root=effective_temp_root,
    )
    # Atomic delete: rename the whole run directory aside first, then remove the staging
    # directory. A failure rolls the original directory back so a partial cleanup can never
    # leave the run (queue, reviews, acceptance reports) half-deleted and un-auditable.
    # When even the rename fails, the run is left fully intact and queued for a delayed
    # retry on the next cleanup call (with the validation evidence captured above so the
    # retry never re-reads a half-removed queue DB).
    outcome, detail = _delete_run_directory(output_root, staging)
    if outcome == "deferred":
        if discard_incomplete:
            rollback_failures = _restore_released_intake_rows(
                Path(ledger_release["ledgerPath"]),
                list(ledger_release["releasedRows"]),
            )
            return {
                "status": "partial",
                "errorCode": "research_run_abandon_failed",
                "detail": detail,
                "releasedIntakeLedgerCount": int(ledger_release["releasedIntakeLedgerCount"]),
                "ledgerRollbackFailedSampleIds": rollback_failures,
                "recoveryRequired": bool(rollback_failures) or bool(detail.get("recoveryRequired")),
            }
        _queue_pending_cleanup(
            runs_root,
            run_id=run_id,
            evidence=evidence,
        )
        return {
            "status": "partial",
            "errorCode": "research_run_cleanup_failed",
            "detail": detail,
            "queuedDelayedRetry": True,
            "recoveryRequired": bool(detail.get("recoveryRequired")),
            "delayedRetry": retried,
        }
    _drop_pending_cleanup(runs_root, run_id)
    return {
        "status": "cleaned",
        "taskKind": "research",
        "taskId": run_id,
        "removedTransientPacketCount": packet_cleanup["removed"],
        "memoriesPreserved": True,
        "userExportsPreserved": True,
        "containsRawMaterial": False,
        "abandonedIncomplete": abandon_incomplete,
        "retentionExpired": retention_expired,
        "releasedIntakeLedgerCount": int(ledger_release["releasedIntakeLedgerCount"]),
        "acceptedIntakeLedgerCountPreserved": int(
            ledger_release["acceptedIntakeLedgerCountPreserved"]
        ),
        "missingIntakeLedgerCount": int(ledger_release["missingIntakeLedgerCount"]),
        "delayedRetry": retried,
        "preservedWriteReceiptRefs": preserved_receipts.get("writeReceiptRefs") or [],
        "safeAuditPreserved": True,
        "researchIncompleteCount": len(incomplete),
    }


def _preserve_legacy_write_receipts(
    *,
    output_root: Path,
    run_id: str,
    rows: list[dict[str, Any]],
    memory_db_path: Path,
) -> dict[str, Any]:
    """Import a minimal audit receipt before a legacy run directory is removed."""

    con = mature_learning.connect(memory_db_path)
    refs: list[str] = []
    try:
        con.execute("BEGIN IMMEDIATE")
        for row in rows:
            if str(row.get("status") or "") != "accepted":
                continue
            sample_id = str(row.get("sampleId") or row.get("sample_id") or "")
            if not sample_id:
                # Legacy unit fixtures and pre-product queue rows without a stable sample
                # identity cannot produce an auditable receipt; real product rows always carry it.
                continue
            receipt_ref = research_runtime.write_receipt_ref(f"research-run:{run_id}", sample_id)
            existing = con.execute(
                "SELECT acceptance_summary FROM research_record_write_receipts WHERE receipt_ref = ?",
                (receipt_ref,),
            ).fetchone()
            if existing:
                receipt_summary = json.loads(existing["acceptance_summary"])
                if receipt_summary.get("completionDiagnosticsVersion") == 1:
                    row.update(research_completion.completion_summary(receipt_summary))
                else:
                    # Legacy receipts did not record research quality. Preserve known
                    # queue/report gaps without upgrading the immutable receipt to clean.
                    row.update(_legacy_completion_diagnostics(
                        output_root=output_root, sample_id=sample_id, row=row,
                    ))
                row["writeReceiptRef"] = receipt_ref
                refs.append(receipt_ref)
                continue
            report: dict[str, Any] | None = None
            for candidate in reversed(
                sorted((output_root / "acceptance").glob(f"{_slug(sample_id)}-*-acceptance.json"))
            ):
                try:
                    loaded = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(loaded, dict) and loaded.get("safeArtifactOnly") is True:
                    report = loaded
                    break
            record_writes = list(
                (((report or {}).get("deepRecordWrite") or {}).get("recordWrites") or [])
            )
            accepted_count = int(
                row.get("accepted_deep_record_count") or row.get("acceptedDeepRecordCount") or 0
            )
            if accepted_count and not record_writes:
                con.rollback()
                return {
                    "status": "rejected",
                    "errorCode": "legacy_research_write_receipt_unavailable",
                    "sampleId": sample_id,
                    "noRawMatureBuildMaterial": True,
                }
            summary = {
                "acceptedPatternCount": int((report or {}).get("acceptedPatternCount") or 0),
                "acceptedDeepRecordCount": int(
                    (report or {}).get("acceptedDeepRecordCount") or accepted_count
                ),
                "acceptedSemanticEdgeCount": int(
                    (report or {}).get("acceptedSemanticEdgeCount") or 0
                ),
                **research_completion.completion_summary(report or {}),
            }
            _assert_safe_payload(summary)
            _assert_safe_payload({"recordWrites": record_writes})
            attempt_key = str(row.get("acceptAttemptKey") or row.get("accept_attempt_key") or "")
            if not attempt_key:
                attempt_key = (
                    "legacy-"
                    + research_runtime.stable_hash({"runId": run_id, "sampleId": sample_id})[:20]
                )
            con.execute(
                """
                INSERT INTO research_record_write_receipts(
                    receipt_ref, run_ref, sample_id, accept_attempt_key, packet_safe_hash,
                    canonical_review_hash, contract_version, expected_origin_state,
                    acceptance_summary, record_writes_json, pattern_ids, semantic_edge_ids,
                    provenance, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'legacy', 'claimed', ?, ?, ?, ?, 'legacy_report', ?)
                """,
                (
                    receipt_ref,
                    f"research-run:{run_id}",
                    sample_id,
                    attempt_key,
                    str(row.get("packetSafeHash") or row.get("packet_safe_hash") or ""),
                    research_runtime.stable_hash(report or summary),
                    json.dumps(summary, ensure_ascii=False, sort_keys=True),
                    json.dumps(record_writes, ensure_ascii=False, sort_keys=True),
                    json.dumps(((report or {}).get("patternWrite") or {}).get("patternIds") or []),
                    json.dumps(
                        ((report or {}).get("semanticEdgeWrite") or {}).get("edgeIds") or []
                    ),
                    _now_iso(),
                ),
            )
            refs.append(receipt_ref)
            row.update(research_completion.completion_summary(summary))
            row["writeReceiptRef"] = receipt_ref
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()
    return {"status": "ok", "writeReceiptRefs": refs}


def _legacy_completion_diagnostics(
    *, output_root: Path, sample_id: str, row: dict[str, Any],
) -> dict[str, Any]:
    projections = [research_completion.completion_summary(row)]
    for path in sorted((output_root / "acceptance").glob(f"{_slug(sample_id)}-*-acceptance.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(report, dict) and report.get("safeArtifactOnly") is True:
            projections.append(research_completion.completion_summary(report))
    merged: dict[str, Any] = {"acceptanceMode": "unknown"}
    for projection in projections:
        if projection["researchCompletion"] == "needs_followup":
            merged["acceptanceMode"] = "partial_with_deferred"
        for key, value in projection.items():
            if isinstance(value, int) and not isinstance(value, bool) and key.endswith("Count"):
                merged[key] = max(merged.get(key, 0), value)
            elif key in {"deferredGapSummaries", "unresolvedComponentGapSummaries", "caseCoverageGaps"}:
                items = merged.setdefault(key, [])
                items.extend(item for item in value if item not in items)
            elif key == "deferredReasonCounts":
                reasons = merged.setdefault(key, {})
                for reason, count in value.items():
                    reasons[reason] = max(reasons.get(reason, 0), count)
            elif key == "caseCoverage":
                coverage = merged.setdefault(key, {})
                for dimension, state in value.items():
                    if state == "evidence_missing" or dimension not in coverage:
                        coverage[dimension] = state
    return {
        **research_completion.completion_summary(merged, supplement=bool(row.get("supplement"))),
        "completionEvidence": "legacy_queue_and_safe_reports",
    }


def _run_audit_path(runtime_root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{4}", run_id):
        raise ValueError("invalid_research_run_id")
    audit_root = (runtime_root / "run-audits").resolve()
    candidate = (audit_root / f"{run_id}.json").resolve()
    if candidate.parent != audit_root:
        raise ValueError("invalid_research_run_audit_path")
    return candidate


def _cleanup_memory_revision(memory_db_path: Path) -> int:
    with closing(mature_learning.connect(memory_db_path)) as con:
        return research_runtime.get_memory_revision(con)


def _attach_followup_completion(
    *, runtime_root: Path, memory_db_path: Path, run_id: str, rows: list[dict[str, Any]],
) -> None:
    for row in rows:
        if row.get("status") != "accepted" or not row.get("sampleId"):
            continue
        original = research_completion.completion_summary(row)["researchCompletion"]
        row["effectiveResearchCompletion"] = original
        if not memory_db_path.is_file():
            continue
        try:
            state = research_followups.inspect_followups(
                db_path=runtime_root / "followups.sqlite", memory_db_path=memory_db_path,
                run_ref=f"research-run:{run_id}", sample_id=row["sampleId"], limit=1,
            )
        except (sqlite3.Error, ValueError):
            state = {"status": "unavailable"}
        if state.get("status") == "ok":
            row["effectiveResearchCompletion"] = state["effectiveResearchCompletion"]
            row["followupRevision"] = state["revision"]
            row["openGapCount"] = state["openGapCount"]
            row["originFingerprint"] = state["originFingerprint"]


def _preserve_run_audit(
    *, runtime_root: Path, run_id: str, rows: list[dict[str, Any]],
    metadata: dict[str, Any], receipt_refs: list[str], abandon_incomplete: bool,
) -> dict[str, Any]:
    """Persist only safe identities and unresolved work outside disposable source material."""
    samples = [
        {
            "sampleId": row.get("sampleId"), "status": row.get("status"),
            "sourceHashRef": row.get("sourceHashRef"),
            "sourceHash": row.get("sourceHash") or "",
            "characterRef": row.get("characterRef") or "",
            "league": row.get("league") or "",
            "sourceType": row.get("sourceType") or "",
            "writeReceiptRef": row.get("writeReceiptRef") or None,
            "completionEvidence": row.get("completionEvidence") or "acceptance_diagnostics",
            **research_completion.completion_summary(row, supplement=bool(row.get("supplement"))),
            "effectiveResearchCompletion": row.get("effectiveResearchCompletion") or research_completion.completion_summary(row)["researchCompletion"],
            "followupRevision": row.get("followupRevision"),
        }
        for row in rows
    ]
    audit = {
        "auditVersion": 1, "runId": run_id, "runRef": f"research-run:{run_id}",
        "status": "cleanup_prepared", "preparedAt": _now_iso(),
        "sourceGamePatch": metadata.get("currentPatch") or "unknown",
        "sourcePassiveTreeVersion": metadata.get("passiveTreeVersion") or "unknown",
        "retention": research_retention.inspect_policy(metadata, rows, now=_now()),
        "cleanupReason": metadata.get("cleanupReason") or "completed",
        "parentRunRef": metadata.get("supplementParentRunRef") or None,
        "reacquisitionParentRunRef": metadata.get("reacquisitionParentRunRef") or None,
        "reacquisitionParentSampleId": metadata.get("reacquisitionParentSampleId") or None,
        "reacquisitionRequestId": metadata.get("reacquisitionRequestId") or None,
        "abandonedIncomplete": abandon_incomplete,
        "preservedWriteReceiptRefs": receipt_refs,
        "sampleCount": len(samples), "samples": samples,
        "acceptedCount": sum(row["status"] == "accepted" for row in samples),
        "researchCompleteCount": sum(
            row["status"] == "accepted" and row["researchCompletion"] == "complete"
            for row in samples
        ),
        "researchNeedsFollowupCount": sum(
            row["status"] == "accepted" and row["researchCompletion"] == "needs_followup"
            for row in samples
        ),
        "researchCompletionUnknownCount": sum(
            row["status"] == "accepted" and row["researchCompletion"] == "unknown"
            for row in samples
        ),
        "acceptedPatternCount": sum(int(row.get("acceptedPatternCount") or 0) for row in rows),
        "acceptedDeepRecordCount": sum(int(row.get("acceptedDeepRecordCount") or 0) for row in rows),
        "acceptedSemanticEdgeCount": sum(int(row.get("acceptedSemanticEdgeCount") or 0) for row in rows),
        "researchIncompleteCount": sum(
            row["researchCompletion"] != "complete" or row["status"] != "accepted"
            for row in samples
        ),
        "createAuthorizing": False, "noRawMatureBuildMaterial": True,
    }
    _assert_safe_payload(audit)
    path = _run_audit_path(runtime_root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(audit, ensure_ascii=False, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return audit


def read_run_audit(*, output_dir: str | Path, run_id: str) -> dict[str, Any] | None:
    root = Path(output_dir)
    path = _run_audit_path(root, run_id)
    if not path.is_file():
        return None
    audit = json.loads(path.read_text(encoding="utf-8"))
    if audit.get("auditVersion") != 1 or audit.get("runId") != run_id:
        raise ValueError("invalid_research_run_audit")
    _assert_safe_payload(audit)
    runtime_exists = any(
        (root / RUNS_DIRNAME / f"{run_id}{suffix}").exists()
        for suffix in ("", ".cleanup-staging")
    )
    return {
        **audit, "status": "cleanup_pending" if runtime_exists else "archived",
        "rawMaterialAvailable": False,
        "sourceSnapshotRecovery": "check_retained_run" if runtime_exists else "unavailable",
        "runtimeDirectoryPreserved": runtime_exists,
        "dispatchableCount": 0,
    }


def _retry_pending_cleanups(
    runs_root: Path, *, memory_db_path: Path | None = None, current_run_id: str | None = None,
) -> dict[str, Any]:
    """Retry queued cleanups whose directory rename previously failed.

    Each queued item carries the validation evidence captured before any deletion, so a
    retry never re-reads a queue DB that may already be gone. A run whose directory and
    staging are both absent is considered fully cleaned and is dropped from the queue.
    """
    report: dict[str, Any] = {
        "status": "ok",
        "retried": 0,
        "dropped": 0,
        "stillPending": 0,
        "retriedIds": [],
    }
    items = _read_pending_cleanups(runs_root)
    if not items:
        return report
    for item in items:
        run_id = str(item.get("runId") or "")
        output_root = (runs_root / run_id).resolve()
        if output_root.parent != runs_root:
            _drop_pending_cleanup(runs_root, run_id)
            report["dropped"] += 1
            continue
        staging = output_root.with_name(f"{output_root.name}.cleanup-staging")
        if not output_root.exists() and not staging.exists():
            _drop_pending_cleanup(runs_root, run_id)
            report["dropped"] += 1
            continue
        # A run lock is held by the caller only for its own target. Other queued
        # cleanups remain visible until explicitly retried under their own lock.
        if current_run_id is not None and run_id != current_run_id:
            report["stillPending"] += 1
            continue
        if not output_root.exists():
            if not staging.exists():
                _drop_pending_cleanup(runs_root, run_id)
                report["dropped"] += 1
                continue
            try:
                staging.rename(output_root)
            except OSError:
                report["stillPending"] += 1
                continue
        evidence = item.get("evidence") or {}
        try:
            audit_path = _run_audit_path(runs_root.parent, run_id)
            protected = (
                evidence.get("completionProtectionVersion") == 1
                and audit_path.is_file()
                and evidence.get("cleanupAuditHash") == research_runtime.stable_hash(
                    json.loads(audit_path.read_text(encoding="utf-8"))
                )
                and evidence.get("queueStateHash") == research_runtime.stable_hash(
                    _fetch_cases(output_root / QUEUE_DB_FILENAME)
                )
                and evidence.get("followupStateHash") == research_followups.state_fingerprint(
                    runs_root.parent / "followups.sqlite", f"research-run:{run_id}"
                )
                and memory_db_path is not None
                and evidence.get("memoryRevision") == _cleanup_memory_revision(memory_db_path)
            )
        except (OSError, ValueError, sqlite3.Error):
            protected = False
        if not protected:
            report["stillPending"] += 1
            report.setdefault("revalidationRequiredIds", []).append(run_id)
            continue
        # Even repairs that forgot to advance memory_revision must not let a
        # stale support projection authorize deletion of unresolved source data.
        retry_rows = _fetch_cases(output_root / QUEUE_DB_FILENAME)
        retry_metadata = _read_metadata(output_root / QUEUE_DB_FILENAME)
        retry_policy = research_retention.inspect_policy(retry_metadata, retry_rows, now=_now())
        _attach_followup_completion(
            runtime_root=runs_root.parent, memory_db_path=memory_db_path, run_id=run_id, rows=retry_rows,
        )
        if (retry_policy["activeLeaseCount"] or retry_policy["invalidLeaseCount"]
                or retry_policy["acceptanceRecoveryCount"]
                or any(row.get("status") == "accepted" and row.get("effectiveResearchCompletion", research_completion.completion_summary(row)["researchCompletion"]) != "complete"
                       for row in retry_rows)):
            report["stillPending"] += 1
            report.setdefault("revalidationRequiredIds", []).append(run_id)
            continue
        outcome, _detail = _delete_run_directory(output_root, staging)
        if outcome == "cleaned":
            _drop_pending_cleanup(runs_root, run_id)
            report["retried"] += 1
            report["retriedIds"].append(run_id)
        else:
            report["stillPending"] += 1
    return report


def _connect_queue(db_path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError("research queue was not found")
    try:
        return sqlite3.connect(db_path.resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True)
    except sqlite3.OperationalError:
        if not db_path.is_file():
            raise FileNotFoundError("research queue was not found") from None
        raise


def _init_db(db_path: Path, *, allow_create: bool = True) -> None:
    if allow_create:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path)) if allow_create else _connect_queue(db_path)
    with closing(connection) as conn, conn:
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
                character_ref TEXT NOT NULL DEFAULT '',
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
                accepted_semantic_edge_count INTEGER NOT NULL DEFAULT 0,
                unresolved_deep_record_component_count INTEGER NOT NULL DEFAULT 0,
                research_quality_summary TEXT NOT NULL DEFAULT '{}',
                deferred_candidate_count INTEGER NOT NULL DEFAULT 0
                ,accept_attempt_key TEXT
                ,accept_origin_state TEXT
                ,write_receipt_ref TEXT
                ,finalization_status TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_cases_status_lease
                ON cases(status, lease_expires_at, id);
            """
        )
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(cases)")}
        if "character_ref" not in columns:
            conn.execute("ALTER TABLE cases ADD COLUMN character_ref TEXT NOT NULL DEFAULT ''")
        if "accepted_deep_record_count" not in columns:
            conn.execute(
                "ALTER TABLE cases ADD COLUMN accepted_deep_record_count INTEGER NOT NULL DEFAULT 0"
            )
        if "accepted_semantic_edge_count" not in columns:
            conn.execute(
                "ALTER TABLE cases ADD COLUMN accepted_semantic_edge_count "
                "INTEGER NOT NULL DEFAULT 0"
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
        if "supplement" not in columns:
            conn.execute("ALTER TABLE cases ADD COLUMN supplement INTEGER NOT NULL DEFAULT 0")
        if "supplement_context" not in columns:
            conn.execute("ALTER TABLE cases ADD COLUMN supplement_context TEXT NOT NULL DEFAULT ''")
        if "accept_attempt_key" not in columns:
            conn.execute("ALTER TABLE cases ADD COLUMN accept_attempt_key TEXT")
        if "accept_origin_state" not in columns:
            conn.execute("ALTER TABLE cases ADD COLUMN accept_origin_state TEXT")
        if "write_receipt_ref" not in columns:
            conn.execute("ALTER TABLE cases ADD COLUMN write_receipt_ref TEXT")
        if "finalization_status" not in columns:
            conn.execute(
                "ALTER TABLE cases ADD COLUMN finalization_status TEXT NOT NULL DEFAULT ''"
            )
        conn.commit()


def _write_metadata(db_path: Path, values: dict[str, str]) -> None:
    with closing(_connect_queue(db_path)) as conn, conn:
        conn.executemany(
            """
            INSERT INTO metadata(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            [(str(key), str(value)) for key, value in values.items()],
        )
        conn.commit()


def _read_metadata(db_path: Path) -> dict[str, str]:
    conn = _connect_queue(db_path, readonly=True)
    try:
        rows = conn.execute("SELECT key, value FROM metadata").fetchall()
    finally:
        conn.close()
    return {str(key): str(value) for key, value in rows}


def _insert_case_if_absent(db_path: Path, row: dict[str, Any]) -> bool:
    now = _now_iso()
    with closing(_connect_queue(db_path)) as conn, conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO cases(
                sample_id, status, source_type, source_hash, source_hash_ref,
                character_ref, league, level, class_name, ascendancy, main_skill,
                safe_error, packet_id, packet_safe_hash, supplement, supplement_context,
                created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["sampleId"],
                row["status"],
                row["sourceType"],
                row["sourceHash"],
                row["sourceHashRef"],
                row["characterRef"],
                row["league"],
                int(row["level"]),
                row["className"],
                row["ascendancy"],
                row["mainSkill"],
                row["safeError"],
                row["packetId"],
                row["packetSafeHash"],
                int(row.get("supplement") or 0),
                str(row.get("supplementContext") or ""),
                now,
                now,
            ),
        )
        conn.commit()
    return cur.rowcount == 1


def _fetch_cases(db_path: Path) -> list[dict[str, Any]]:
    conn = _connect_queue(db_path, readonly=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM cases ORDER BY id ASC").fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            quality_summary = json.loads(str(row["research_quality_summary"] or "{}"))
        except json.JSONDecodeError:
            quality_summary = {}
        # Queue columns predate completion diagnostics and default to zero. Only
        # positive legacy counts prove a gap; defaults cannot prove its absence.
        completion_input = dict(quality_summary)
        for field, column in (
            ("deferredCandidateCount", "deferred_candidate_count"),
            ("unresolvedDeepRecordMentionCount", "unresolved_deep_record_component_count"),
        ):
            if int(row[column] or 0) > 0:
                completion_input[field] = max(
                    int(row[column]), int(completion_input.get(field) or 0)
                )
        completion = research_completion.completion_summary(
            completion_input, supplement=bool(row["supplement"])
        )
        out.append(
            {
                "sampleId": str(row["sample_id"]),
                "status": str(row["status"]),
                "sourceType": str(row["source_type"]),
                "sourceHash": str(row["source_hash"]),
                "sourceHashRef": str(row["source_hash_ref"]),
                "characterRef": str(row["character_ref"] or ""),
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
                "writeReceiptRef": str(row["write_receipt_ref"] or ""),
                "finalizationStatus": str(row["finalization_status"] or ""),
                "supplement": bool(row["supplement"]),
                "acceptedPatternCount": int(row["accepted_pattern_count"] or 0),
                "acceptedDeepRecordCount": int(row["accepted_deep_record_count"] or 0),
                "acceptedSemanticEdgeCount": int(row["accepted_semantic_edge_count"] or 0),
                "unresolvedDeepRecordComponentCount": int(
                    row["unresolved_deep_record_component_count"] or 0
                ),
                **quality_summary,
                "deferredCandidateCount": int(row["deferred_candidate_count"] or 0),
                **completion,
            }
        )
    return out


def _case_for_valid_lease(db_path: Path, lease_token: str) -> sqlite3.Row:
    _init_db(db_path, allow_create=False)
    now = _now_iso()
    with closing(_connect_queue(db_path)) as conn, conn:
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


def _case_for_review_save(db_path: Path, lease_token: str) -> sqlite3.Row:
    """Return the valid claimed row or the exact in-flight row for accept replay."""

    _init_db(db_path, allow_create=False)
    now = _now_iso()
    with closing(_connect_queue(db_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
              FROM cases
             WHERE lease_token = ?
               AND (
                    (status = 'claimed' AND lease_expires_at > ?)
                    OR status IN ('accepting', 'accepted')
               )
             LIMIT 1
            """,
            (lease_token, now),
        ).fetchone()
    if row is None:
        raise ValueError("lease is invalid or has no matching accept attempt")
    return row


def _refresh_packet_expiry(
    *,
    temp_root: Path,
    packet_safe_hash: str,
    ttl_seconds: int,
) -> bool:
    """Rewrite an existing packet's expiry to now + ttl; returns True when rewritten.

    The safe hash does not include ``expiresAt`` (see research_packet.build_research_packet),
    so rewriting the expiry keeps the packet identity stable while aligning its lifetime with
    the caller's TTL (e.g. a claim's lease duration).
    """
    expires = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(ttl_seconds or 1)))
    expires_iso = expires.isoformat(timespec="seconds")
    for packet_path in temp_root.glob(f"{research_packet.PACKET_PREFIX}*/packet.json"):
        try:
            payload = json.loads(packet_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("safeHash") or "") != str(packet_safe_hash):
            continue
        payload["expiresAt"] = expires_iso
        staging_path = packet_path.with_name(f".{packet_path.name}.{secrets.token_hex(8)}.tmp")
        try:
            staging_path.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(staging_path, packet_path)
        finally:
            staging_path.unlink(missing_ok=True)
        return True
    return False


def _rebuild_packet_for_claim(
    *,
    row: sqlite3.Row,
    output_root: Path,
    temp_root: str | Path | None,
    lease_seconds: int,
    queue_db_path: Path | None = None,
) -> None:
    """Ensure the claimed case's packet lives exactly as long as the lease.

    A claimed case studies from its packet; the packet should live as long as the lease so an
    expired packet always coincides with an expired (reclaimable) lease. When the packet still
    exists (e.g. the queued 24h packet), its expiry is rewritten to the lease duration; when
    it is missing, it is rebuilt from the run-local quarantine with the lease TTL. The safe
    hash stays stable (version context comes from the durable queue metadata).
    """
    effective_temp_root = _effective_temp_root(temp_root, output_root=output_root)
    db_path = _queue_db_path(output_root, queue_db_path)
    quarantine = _quarantine_dir(output_root)
    raw = _verified_quarantine_raw(quarantine, row)
    if not raw:
        raise ValueError("research_source_material_unavailable_or_mismatched")
    version_context = _queue_version_context(db_path)
    case = legacy_batch._case_from_source(
        raw,
        source_hash=str(row["source_hash"]),
        sample_id=str(row["sample_id"]),
        source_type=str(row["source_type"]),
        league=str(row["league"]),
        row={},
    )
    if str(row["packet_safe_hash"] or ""):
        research_packet.cleanup_packets_by_safe_hashes(
            {str(row["packet_safe_hash"])}, temp_root=effective_temp_root
        )
    packet = _prepare_packet(
        case,
        temp_root=effective_temp_root,
        ttl_seconds=max(1, int(lease_seconds or 1)),
        current_patch=version_context["gamePatch"],
        passive_tree_version=version_context["passiveTreeVersion"],
        pob_version_or_commit=version_context["pobVersionOrCommit"],
        include_pob_readback=True,
        version_context=version_context,
    )
    with closing(_connect_queue(db_path)) as conn, conn:
        conn.execute(
            """
            UPDATE cases
               SET packet_id = ?,
                   packet_safe_hash = ?,
                   updated_at = ?
             WHERE sample_id = ?
            """,
            (
                str(packet["packetId"]),
                str(packet["packetSafeHash"]),
                _now_iso(),
                str(row["sample_id"]),
            ),
        )
        conn.commit()


def _quarantine_dir(output_root: Path) -> Path:
    """Return the run-local quarantine directory for raw source material.

    Quarantine and lease packets use separate subtrees inside the private run directory
    (gitignored and removed with the run), so a lost or expired packet can be rebuilt from
    quarantine while the case is still queued.
    """
    return Path(output_root) / "quarantine"


def _write_quarantine_case(output_root: Path, case: dict[str, Any]) -> Path:
    """Persist the raw source material of one queued case into the run-local quarantine.

    Content-addressed by ``sourceHash`` (db-unique), with ``sampleId`` stored inside for
    cross-checks. Idempotent: an existing file with the same hash is left untouched.
    """
    quarantine = _quarantine_dir(output_root)
    quarantine.mkdir(parents=True, exist_ok=True)
    source_hash = str(case.get("sourceHash") or "").strip()
    raw = str(case.get("_rawImportCode") or "")
    source_ref = str(case.get("sourceHashRef") or "")
    if (not re.fullmatch(r"[a-f0-9]{64}", source_hash)
            or legacy_batch.pob_code.is_link(raw)
            or hashlib.sha256(raw.encode("utf-8")).hexdigest() != source_hash
            or source_ref not in {f"source-hash:{source_hash}", f"source-hash:{source_hash[:16]}"}
            or legacy_batch._source_to_xml(raw) != str(case.get("_rawXml") or "")):
        raise ValueError("research_source_material_identity_mismatch")
    target = quarantine / f"{source_hash}.json"
    if target.exists():
        if not _verified_quarantine_raw(quarantine, {
            "sample_id": str(case.get("sampleId") or ""),
            "source_hash": source_hash, "source_hash_ref": source_ref,
        }):
            raise ValueError("existing_quarantine_material_mismatch")
        return target
    payload = {
        "sampleId": str(case.get("sampleId") or ""),
        "sourceHash": source_hash,
        "sourceHashRef": str(case.get("sourceHashRef") or ""),
        "sourceType": str(case.get("sourceType") or ""),
        "league": str(case.get("league") or ""),
        "className": str(case.get("className") or ""),
        "ascendancy": str(case.get("ascendancy") or ""),
        "level": str(case.get("level") or ""),
        "mainSkill": str(case.get("mainSkill") or ""),
        "rawImportCode": str(case.get("_rawImportCode") or ""),
        "rawXml": str(case.get("_rawXml") or ""),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _prepare_packet(
    case: dict[str, Any],
    *,
    temp_root: Path,
    ttl_seconds: int,
    current_patch: str,
    passive_tree_version: str,
    pob_version_or_commit: str,
    include_pob_readback: bool = False,
    version_context: dict[str, str] | None = None,
) -> dict[str, str]:
    context = research_readback.normalize_version_context({
        **(version_context or {}),
        "gamePatch": current_patch,
        "passiveTreeVersion": passive_tree_version,
        "pobVersionOrCommit": pob_version_or_commit,
    })
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
            "modelGamePatch": context["modelGamePatch"],
            "versionContextStatus": context["status"],
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledgeScope": (
                "global_seed"
                if str(case.get("sourceType") or "").casefold() == "poe_ninja_import_code"
                else "local_user"
            ),
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
    if include_pob_readback and os.environ.get("POE2_RESEARCH_POB_READBACK", "1") != "0":
        packet_case["pobReadback"] = research_readback.build_safe_readback(
            str(case.get("_rawXml") or ""),
            source_hash_ref=str(case.get("sourceHashRef") or ""),
            version_context=context,
        )
    result = research_packet.build_research_packet(
        packet_case,
        persist_for_transport=True,
        ttl_seconds=ttl_seconds,
        temp_root=temp_root,
    )
    packet = result["packet"]
    return {"packetId": str(packet["packetId"]), "packetSafeHash": str(packet["safeHash"])}


def _resume_queue_cases(
    *,
    output_root: Path,
    db_path: Path,
    effective_temp_root: Path,
    worker_count: int,
    memory_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Resume without changing a live lease, an accept attempt or its source binding."""
    effective_memory = Path(memory_db_path) if memory_db_path is not None else paths.mature_learning_path()
    # Same memory -> run lock order as cleanup. The locked implementation only
    # reads Memory-independent queue state; it never re-enters accept or cleanup.
    with (
        _ACCEPT_LOCK,
        interprocess_file_lock(_accept_lock_path(effective_memory)),
        interprocess_file_lock(_run_lock_path(db_path)),
    ):
        return _resume_queue_cases_locked(
            output_root=output_root, db_path=db_path,
            effective_temp_root=effective_temp_root, worker_count=worker_count,
        )


def _resume_queue_cases_locked(
    *,
    output_root: Path,
    db_path: Path,
    effective_temp_root: Path,
    worker_count: int,
) -> dict[str, Any]:
    if not db_path.is_file():
        report = _queue_report(
            status="resume_failed",
            db_path=db_path,
            requested_worker_count=worker_count,
            cases=[],
            dry_run=False,
            source_input_summary={
                "levelMin": 0,
                "levelMax": 0,
                "requestedSampleCount": 0,
                "expectedSourceCount": None,
            },
        )
        report["errorCode"] = "research_run_not_found"
        report["safeError"] = "resume requires the --output-dir returned by the original queue run"
        _assert_safe_payload(report)
        return report

    metadata = _read_metadata(db_path)
    rows = _fetch_cases(db_path)
    now = _now()
    retention = research_retention.inspect_policy(metadata, rows, now=now)
    if not retention["newClaimAllowed"]:
        report = queue_status(output_dir=output_root, queue_db_path=db_path)
        report.update({
            "status": "resume_blocked",
            "errorCode": "retention_expired" if retention["status"] == "expired" else "retention_policy_invalid",
            "retention": retention,
            "recoveryRequired": bool(retention["acceptanceRecoveryCount"]),
            "nextAction": "Preserve pending accept/retry recovery and active leases; use audited cleanup when allowed.",
        })
        _assert_safe_payload(report)
        return report

    _write_metadata(
        db_path,
        {
            "requestedWorkerCount": str(_effective_worker_count(worker_count)),
            "workerCountSemantics": "parallel_subagents_one_case_each",
        },
    )
    version_context = _queue_version_context(db_path)
    quarantine = _quarantine_dir(output_root)
    active_rows = [
        row
        for row in rows
        if str(row.get("status") or "") in {"queued", "claimed", "accepting", "acceptance_rejected"}
        or (row.get("status") == "accepted" and row.get("finalizationStatus") not in (None, "", "complete"))
    ]
    rebuilt = 0
    intact = 0
    unavailable = 0
    recovery_count = 0
    protected_lease_count = 0
    diagnostics: list[dict[str, str]] = []
    ttl_seconds = 24 * 60 * 60
    if retention["policy"]:
        deadline = datetime.fromisoformat(retention["policy"]["expiresAt"])
        ttl_seconds = min(ttl_seconds, max(1, int((deadline - now).total_seconds())))
    for row in active_rows:
        row_policy = research_retention.inspect_policy(metadata, [row], now=now)
        if row_policy["acceptanceRecoveryCount"]:
            recovery_count += 1
            diagnostics.append({
                "sampleId": str(row["sampleId"]),
                "errorCode": "research_acceptance_recovery_required",
                "nextAction": "Replay the original accept or retry with its unchanged review and receipt binding.",
            })
            continue
        if row_policy["activeLeaseCount"] or row_policy["invalidLeaseCount"]:
            protected_lease_count += 1
            diagnostics.append({
                "sampleId": str(row["sampleId"]),
                "errorCode": "research_active_claim_lease" if row_policy["activeLeaseCount"] else "invalid_research_claim_lease",
                "nextAction": "Keep the original lease binding; resume only after the lease is safely released or expired.",
            })
            continue
        packet_safe_hash = str(row.get("packetSafeHash") or "")
        if packet_safe_hash and _resume_packet_is_current(effective_temp_root, packet_safe_hash, now):
            intact += 1
            continue
        source_hash = str(row.get("sourceHash") or "")
        raw = _verified_quarantine_raw(quarantine, {
            "sample_id": row["sampleId"], "source_hash": source_hash,
            "source_hash_ref": row["sourceHashRef"],
        })
        if not raw:
            # Keep trusted queue history even if material was lost. Reacquisition
            # and audited expiry cleanup must still be able to explain this case.
            with closing(_connect_queue(db_path)) as conn, conn:
                conn.execute(
                    "UPDATE cases SET safe_error = 'resume_source_material_unavailable', updated_at = ? "
                    "WHERE sample_id = ? AND status = ? AND packet_safe_hash = ?",
                    (_now_iso(), row["sampleId"], row["status"], packet_safe_hash),
                )
            unavailable += 1
            diagnostics.append({
                "sampleId": str(row["sampleId"]),
                "errorCode": "resume_source_material_unavailable",
                "nextAction": "Keep this source case for controlled reacquisition or audited cleanup.",
            })
            continue
        case = legacy_batch._case_from_source(
            raw,
            source_hash=source_hash,
            sample_id=str(row.get("sampleId") or ""),
            source_type=str(row.get("sourceType") or "poe_ninja_import_code"),
            league=str(row.get("league") or "unknown"),
            row={},
        )
        packet = _prepare_packet(
            case,
            temp_root=effective_temp_root,
            ttl_seconds=ttl_seconds,
            current_patch=version_context["gamePatch"],
            passive_tree_version=version_context["passiveTreeVersion"],
            pob_version_or_commit=version_context["pobVersionOrCommit"],
            version_context=version_context,
        )
        with closing(_connect_queue(db_path)) as conn, conn:
            conn.execute(
                """
                UPDATE cases
                   SET packet_id = ?,
                       packet_safe_hash = ?,
                       safe_error = CASE WHEN safe_error = 'resume_source_material_unavailable' THEN '' ELSE safe_error END,
                       updated_at = ?
                 WHERE sample_id = ?
                   AND status = ? AND packet_safe_hash = ?
                """,
                (
                    str(packet["packetId"]),
                    str(packet["packetSafeHash"]),
                    _now_iso(),
                    str(row.get("sampleId") or ""),
                    row["status"], packet_safe_hash,
                ),
            )
            conn.commit()
        rebuilt += 1

    report = queue_status(output_dir=output_root, queue_db_path=db_path)
    report["status"] = "resumed_partial" if diagnostics else "resumed"
    report["retention"] = retention
    report["recoveryRequired"] = recovery_count > 0
    report["resumeDiagnostics"] = diagnostics
    report["resumeSummary"] = {
        "activeCaseCount": len(active_rows),
        "packetIntactCount": intact,
        "packetRebuiltCount": rebuilt,
        "unrecoverableCaseCount": unavailable,
        "acceptanceRecoveryRequiredCount": recovery_count,
        "protectedLeaseCount": protected_lease_count,
        "removedCaseCount": 0,
    }
    _assert_safe_payload(report)
    return report


def _resume_packet_is_current(temp_root: Path, packet_safe_hash: str, now: datetime) -> bool:
    # The general loader expires every packet in this directory. Resume must not
    # sweep a different case's material while its acceptance is still recoverable.
    for packet_path in temp_root.glob(f"{research_packet.PACKET_PREFIX}*/packet.json"):
        try:
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            expires = datetime.fromisoformat(str(packet.get("expiresAt") or ""))
            if expires.tzinfo is not None and expires > now and _packet_integrity_matches(packet, packet_safe_hash):
                return True
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return False


def _load_packet_by_safe_hash(temp_root: Path, packet_safe_hash: str) -> dict[str, Any]:
    for packet_path in temp_root.glob(f"{research_packet.PACKET_PREFIX}*/packet.json"):
        try:
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _packet_integrity_matches(packet, packet_safe_hash):
            try:
                expiry = datetime.fromisoformat(str(packet["expiresAt"]).replace("Z", "+00:00"))
                if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            return packet
    raise FileNotFoundError("transient packet not found; recreate the queue or reclaim the case")


def _packet_integrity_matches(packet: Any, expected_hash: str) -> bool:
    if not isinstance(packet, dict) or packet.get("safeHash") != expected_hash:
        return False
    core = {key: value for key, value in packet.items() if key not in {
        "packetId", "createdAt", "expiresAt", "safeHash",
    }}
    return research_packet._safe_hash(core) == expected_hash


def _packet_for_valid_lease(
    *,
    row: sqlite3.Row,
    output_dir: Path,
    temp_root: str | Path | None,
) -> dict[str, Any]:
    root = _effective_temp_root(temp_root, output_root=output_dir)
    packet = _load_packet_by_safe_hash(root, str(row["packet_safe_hash"]))
    metadata, raw = packet.get("safeMetadata") or {}, packet.get("rawContext") or {}
    material = raw.get("rawImportCode")
    if (metadata.get("case_id") != str(row["sample_id"])
            or metadata.get("sourceHash") != str(row["source_hash"])
            or metadata.get("sourceRef") != str(row["source_hash_ref"])
            or not isinstance(material, str) or legacy_batch.pob_code.is_link(material)
            or hashlib.sha256(material.encode("utf-8")).hexdigest() != str(row["source_hash"])):
        raise ValueError("research_packet_source_identity_mismatch")
    if legacy_batch._source_to_xml(material) != raw.get("rawXml"):
        raise ValueError("research_packet_source_snapshot_mismatch")
    return packet


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


def _optional_pob_readback(
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
    return research_packet.validated_pob_readback(packet)


def _optional_jewel_counts(
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
    return research_packet.jewel_counts(packet)


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
        "characterRef": legacy_batch._safe_text(case.get("characterRef")),
        "league": legacy_batch._safe_text(case.get("league")),
        "level": int(case.get("level") or 0),
        "className": legacy_batch._safe_text(case.get("className")),
        "ascendancy": legacy_batch._safe_text(case.get("ascendancy")),
        "mainSkill": legacy_batch._safe_text(case.get("mainSkill")),
        "mainSkillAuthority": "programmatic_snapshot_non_authoritative",
        "safeError": legacy_batch._safe_text(case.get("safeError")),
        "packetId": legacy_batch._safe_text(packet_id),
        "packetSafeHash": legacy_batch._safe_text(packet_safe_hash),
        "supplement": 1 if case.get("supplement") else 0,
        "supplementContext": legacy_batch._safe_text(case.get("supplementContext")),
    }


def _normalize_supplement_sample_ids(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    normalized = sorted({str(value).strip() for value in values if str(value).strip()})
    if not normalized:
        raise ValueError("supplement_sample_ids must contain at least one sampleId")
    if len(normalized) > 50:
        raise ValueError("supplement_sample_ids may contain at most 50 unique sampleIds")
    return normalized


def inspect_supplement_selection(
    prior_run_root: Path,
    supplement_sample_ids: list[str],
) -> dict[str, Any]:
    """Validate a targeted supplement selection without exposing private run paths."""

    requested = _normalize_supplement_sample_ids(supplement_sample_ids)
    assert requested is not None
    prior_db = prior_run_root / QUEUE_DB_FILENAME
    prior_quarantine = _quarantine_dir(prior_run_root)
    with closing(sqlite3.connect(prior_db)) as conn, conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT sample_id, status, source_hash, source_hash_ref FROM cases ORDER BY id"
        ).fetchall()
    by_id = {str(row["sample_id"]): row for row in rows}
    missing = sorted(set(requested) - set(by_id))
    not_accepted = sorted(
        sample_id
        for sample_id in requested
        if sample_id in by_id and str(by_id[sample_id]["status"] or "") != "accepted"
    )
    unrecoverable: list[str] = []
    for sample_id in requested:
        row = by_id.get(sample_id)
        if row is None or sample_id in not_accepted:
            continue
        raw = _verified_quarantine_raw(prior_quarantine, row)
        if not raw:
            unrecoverable.append(sample_id)
    return {
        "status": ("ok" if not (missing or not_accepted or unrecoverable) else "invalid"),
        "requestedSupplementSampleCount": len(requested),
        "selectedSupplementSampleCount": (
            len(requested) if not (missing or not_accepted or unrecoverable) else 0
        ),
        "selectedSupplementSampleIds": (
            requested if not (missing or not_accepted or unrecoverable) else []
        ),
        "missingSupplementSampleCount": len(missing),
        "missingSupplementSampleIds": missing,
        "notAcceptedSupplementSampleCount": len(not_accepted),
        "notAcceptedSupplementSampleIds": not_accepted,
        "unrecoverableSupplementSampleCount": len(unrecoverable),
        "unrecoverableSupplementSampleIds": sorted(unrecoverable),
        "noRawMatureBuildMaterial": True,
    }


def _verified_quarantine_raw(prior_quarantine: Path, row: Any) -> str:
    sample_id = str(row["sample_id"] or "").strip()
    source_hash = str(row["source_hash"] or "").strip()
    source_hash_ref = str(row["source_hash_ref"] or "").strip()
    if (not sample_id or not re.fullmatch(r"[a-f0-9]{64}", source_hash)
            or source_hash_ref not in {f"source-hash:{source_hash}", f"source-hash:{source_hash[:16]}"}):
        return ""
    quarantine_path = prior_quarantine / f"{source_hash}.json"
    try:
        payload = json.loads(quarantine_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    raw = payload.get("rawImportCode")
    if not isinstance(raw, str) or not raw or legacy_batch.pob_code.is_link(raw):
        return ""
    if str(payload.get("sampleId") or "").strip() != sample_id:
        return ""
    if str(payload.get("sourceHash") or "").strip() != source_hash:
        return ""
    if str(payload.get("sourceHashRef") or "").strip() != source_hash_ref:
        return ""
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != source_hash:
        return ""
    try:
        decoded = legacy_batch._source_to_xml(raw)
    except (ValueError, TypeError):
        return ""
    frozen = payload.get("rawXml")
    if frozen is not None and frozen != decoded:
        return ""
    return raw


def _cases_from_prior_run(
    prior_run_root: Path,
    *,
    supplement_sample_ids: list[str] | None = None,
    supplement_focus: str = "",
) -> tuple[list[dict[str, Any]], int]:
    """Re-queue completed cases of a prior run as local supplement research.

    Every case row of the prior run (any status) is rebuilt from its run-local quarantine
    raw material and marked ``supplement=true``; rows whose quarantine material is missing
    are skipped (their raw source is unrecoverable). Supplement cases keep the prior
    ``sampleId`` for traceability and chain the ``supplementContext`` focus text.
    """
    selected_ids = _normalize_supplement_sample_ids(supplement_sample_ids)
    if selected_ids is not None:
        selection = inspect_supplement_selection(prior_run_root, selected_ids)
        if selection["status"] != "ok":
            raise ValueError(
                "invalid targeted supplement selection: "
                + json.dumps(selection, ensure_ascii=False, sort_keys=True)
            )
    prior_db = prior_run_root / QUEUE_DB_FILENAME
    prior_quarantine = _quarantine_dir(prior_run_root)
    cases: list[dict[str, Any]] = []
    skipped = 0
    with closing(sqlite3.connect(prior_db)) as conn, conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT sample_id, status, source_hash, source_hash_ref, source_type, character_ref,
                   league, level, class_name, ascendancy, main_skill
              FROM cases
             ORDER BY id
            """
        ).fetchall()
    for row in rows:
        if selected_ids is not None and str(row["sample_id"] or "") not in selected_ids:
            continue
        source_hash = str(row["source_hash"] or "").strip()
        if not source_hash:
            skipped += 1
            continue
        raw = _verified_quarantine_raw(prior_quarantine, row)
        if not raw:
            skipped += 1
            continue
        case = legacy_batch._case_from_source(
            raw,
            source_hash=source_hash,
            sample_id=str(row["sample_id"] or ""),
            source_type=str(row["source_type"] or "local_pob_code_file"),
            league=str(row["league"] or "unknown"),
            row={},
            character_ref=str(row["character_ref"] or ""),
        )
        case["supplement"] = True
        case["supplementContext"] = str(supplement_focus or "").strip()
        cases.append(case)
    return cases, skipped


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
    intake_ledger_summary: dict[str, Any] | None = None,
    intake_ledger_source: str = "snapshot",
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for case in cases:
        counts[str(case.get("status") or "")] = counts.get(str(case.get("status") or ""), 0) + 1
    samples = [_safe_sample_for_report(case) for case in cases]
    source_input_summary = dict(source_input_summary or {})
    level_min = int(source_input_summary.get("levelMin") or 0)
    level_max = int(source_input_summary.get("levelMax") or 0)
    sample_levels = [int(case.get("level") or 0) for case in cases if int(case.get("level") or 0)]
    level_bias_note = ""
    if level_min and level_max and level_max > level_min and sample_levels:
        if all(level == level_max for level in sample_levels):
            level_bias_note = (
                f"Level filter {level_min}-{level_max} semantics: samples were selected "
                "highest level first and all landed at the range maximum; use "
                "--level-min == --level-max for an exact level."
            )
    requested_sample_count = int(source_input_summary.get("requestedSampleCount") or 0)
    unavailable_count = counts.get("import_failed", 0)
    available_sample_count = max(0, len(samples) - unavailable_count)
    now_iso = _now_iso()
    expired_claimed_count = sum(
        1
        for case in cases
        if str(case.get("status") or "") == "claimed"
        and str(case.get("leaseExpiresAt") or "")
        and str(case.get("leaseExpiresAt") or "") <= now_iso
    )
    stale_accepting_count = sum(
        1
        for case in cases
        if str(case.get("status") or "") == "accepting"
        and str(case.get("leaseExpiresAt") or "")
        and str(case.get("leaseExpiresAt") or "") <= now_iso
    )
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
        "expiredClaimedCount": expired_claimed_count,
        "dispatchableCount": counts.get("queued", 0) + expired_claimed_count,
        "claimedCount": counts.get("claimed", 0),
        "acceptingCount": counts.get("accepting", 0),
        "staleAcceptingCount": stale_accepting_count,
        "acceptedCount": counts.get("accepted", 0),
        "researchCompleteCount": sum(
            case.get("status") == "accepted" and case.get("researchCompletion") == "complete"
            for case in samples
        ),
        "researchNeedsFollowupCount": sum(
            case.get("status") == "accepted" and case.get("researchCompletion") == "needs_followup"
            for case in samples
        ),
        "researchCompletionUnknownCount": sum(
            case.get("status") == "accepted" and case.get("researchCompletion") == "unknown"
            for case in samples
        ),
        "rejectedCount": counts.get("acceptance_rejected", 0),
        "importFailedCount": counts.get("import_failed", 0),
        "requestedWorkerCount": _effective_worker_count(requested_worker_count),
        "workerCountSemantics": "parallel_subagents_one_case_each",
        "workerReusePolicy": "fresh_subagent_per_case_no_evidence_reuse",
        "insertedCount": inserted_count,
        "duplicateCount": duplicate_count,
        "intakePagesFetched": int(source_input_summary.get("intakePagesFetched") or 0),
        "intakePageRowsSeen": int(source_input_summary.get("intakePageRowsSeen") or 0),
        "intakeSkippedAlreadyResearched": int(
            source_input_summary.get("intakeSkippedAlreadyResearched") or 0
        ),
        "intakeSkippedAlreadyStudied": int(
            source_input_summary.get("intakeSkippedAlreadyStudied") or 0
        ),
        "intakeLedgerRecordedCount": int(
            source_input_summary.get("intakeLedgerRecordedCount") or 0
        ),
        "intakeLedgerSummary": intake_ledger_summary or {},
        "intakeLedgerSource": intake_ledger_source,
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
        "reResearchRunDir": str(source_input_summary.get("reResearchRunDir") or ""),
        "reSupplementCaseCount": int(source_input_summary.get("reSupplementCaseCount") or 0),
        "reSupplementSkippedUnrecoverableCount": int(
            source_input_summary.get("reSupplementSkippedUnrecoverableCount") or 0
        ),
        "requestedSupplementSampleCount": int(
            source_input_summary.get("requestedSupplementSampleCount") or 0
        ),
        "selectedSupplementSampleCount": int(
            source_input_summary.get("selectedSupplementSampleCount") or 0
        ),
        "selectedSupplementSampleIds": list(
            source_input_summary.get("selectedSupplementSampleIds") or []
        ),
        "missingSupplementSampleCount": int(
            source_input_summary.get("missingSupplementSampleCount") or 0
        ),
        "missingSupplementSampleIds": list(
            source_input_summary.get("missingSupplementSampleIds") or []
        ),
        "notAcceptedSupplementSampleCount": int(
            source_input_summary.get("notAcceptedSupplementSampleCount") or 0
        ),
        "notAcceptedSupplementSampleIds": list(
            source_input_summary.get("notAcceptedSupplementSampleIds") or []
        ),
        "unrecoverableSupplementSampleCount": int(
            source_input_summary.get("unrecoverableSupplementSampleCount") or 0
        ),
        "unrecoverableSupplementSampleIds": list(
            source_input_summary.get("unrecoverableSupplementSampleIds") or []
        ),
        "samples": samples,
        "dryRun": bool(dry_run),
        "noRawMatureBuildMaterial": True,
        "caveats": [
            "The queue stores only safe metadata, leases, and packet safe hashes.",
            "Raw mature build material exists only in run-local quarantine and lease-bound transient packets.",
            "Use inspect/read/search from the active lease to read bounded structured evidence.",
            "This script does not call any OpenAI, Claude, Gemini, or other model provider API.",
            *([level_bias_note] if level_bias_note else []),
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


def _studied_source_hashes() -> set[str]:
    """Return source-hash values already durably researched in the mature-learning store.

    Matches on the byte-identical PoB text hash stored in record ``source_case_refs``
    (``source-hash:<sha>``). This catches the historical-duplicate case that the
    character-level intake ledger cannot (accounts are not persisted for older runs).
    """
    try:
        from server.knowledge import mature_learning

        db = mature_learning.mature_learning_path()
        if not Path(db).is_file():
            return set()
        con = mature_learning.connect(db)
        try:
            rows = con.execute(
                "SELECT DISTINCT source_case_refs FROM deep_research_records "
                "WHERE knowledge_scope = 'global_seed' AND status = 'valid' "
                "AND superseded_by_id IS NULL"
            ).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - queue proceeds without the historical index
        return set()
    studied: set[str] = set()
    for row in rows:
        try:
            refs = json.loads(str(row[0] or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            refs = []
        for ref in refs if isinstance(refs, list) else []:
            text = str(ref or "")
            if text.startswith("source-hash:"):
                studied.add(text[len("source-hash:") :])
    return studied


def _intake_ledger_summary(
    ledger_path: Path,
    *,
    league: str,
    local_sources: list[str],
) -> dict[str, Any]:
    """Safe cross-run intake-dedup snapshot for queue reports.

    Local source-file queues never touch the character ledger.
    """
    if local_sources:
        return {
            "used": False,
            "reason": "local_source_input",
            "totalRecords": 0,
            "byStatus": {},
            "league": "",
        }
    summary = research_intake_ledger.summary(ledger_path, league=str(league or ""))
    return {
        "used": True,
        "league": str(league or ""),
        "totalRecords": int(summary.get("totalRecords") or 0),
        "byStatus": summary.get("byStatus") or {},
    }


def _live_intake_ledger_summary(
    metadata: dict[str, Any], *, league_hint: str = ""
) -> dict[str, Any] | None:
    """Re-read the per-user intake ledger at report time.

    ``queue_status`` historically served the queue-time snapshot, which stays ``queued``
    forever even after accepts promoted the rows. Live re-read makes the final status
    truthful; the queue-time snapshot remains the fallback when the ledger is missing.
    """
    league = (str(metadata.get("league") or "").strip()) or league_hint
    ledger_path = str(metadata.get("intakeLedgerPath") or "").strip()
    if ledger_path:
        try:
            return _intake_ledger_summary(Path(ledger_path), league=league, local_sources=False)
        except Exception:  # noqa: BLE001 - snapshot fallback below
            return None
    try:
        return _intake_ledger_summary(
            DEFAULT_INTAKE_LEDGER_PATH, league=league, local_sources=False
        )
    except Exception:  # noqa: BLE001 - snapshot fallback below
        return None


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
        "acceptedSemanticEdgeCount": int(case.get("acceptedSemanticEdgeCount") or 0),
        "createdDeepRecordCount": int(case.get("createdDeepRecordCount") or 0),
        "updatedDeepRecordCount": int(case.get("updatedDeepRecordCount") or 0),
        "unchangedDeepRecordCount": int(case.get("unchangedDeepRecordCount") or 0),
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
        "uniqueGemDiagnostics": case.get("uniqueGemDiagnostics") or {},
        "acceptanceCaveats": case.get("acceptanceCaveats") or [],
        "deferredCandidateCount": int(case.get("deferredCandidateCount") or 0),
        "writeReceiptRef": str(case.get("writeReceiptRef") or ""),
        **research_completion.completion_summary(case, supplement=bool(case.get("supplement"))),
    }


def _research_quality_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "acceptanceMode": legacy_batch._safe_text(report.get("acceptanceMode")),
        "deferredReasonCounts": dict(report.get("deferredReasonCounts") or {}),
        "acceptedPatternCount": int(report.get("acceptedPatternCount") or 0),
        "acceptedDeepRecordCount": int(report.get("acceptedDeepRecordCount") or 0),
        "acceptedSemanticEdgeCount": int(report.get("acceptedSemanticEdgeCount") or 0),
        "createdDeepRecordCount": int(report.get("createdDeepRecordCount") or 0),
        "updatedDeepRecordCount": int(report.get("updatedDeepRecordCount") or 0),
        "unchangedDeepRecordCount": int(report.get("unchangedDeepRecordCount") or 0),
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
        "uniqueGemDiagnostics": report.get("uniqueGemDiagnostics") or {},
        "acceptanceCaveats": report.get("caveats") or [],
        "unresolvedDeepRecordMentionCount": int(
            report.get("unresolvedDeepRecordMentionCount")
            or report.get("unresolvedDeepRecordComponentCount")
            or 0
        ),
        "unresolvedUniqueComponentCount": int(report.get("unresolvedUniqueComponentCount") or 0),
        "unkeyedDeepRecordCount": int(report.get("unkeyedDeepRecordCount") or 0),
        "deepRecordsWithoutKnowledgeIdentity": report.get("deepRecordsWithoutKnowledgeIdentity")
        or [],
        **research_completion.completion_summary(
            report, supplement=report.get("completionScope") == "supplement"
        ),
    }


def _validation_only_result(report: dict[str, Any], *, sample_id: str) -> dict[str, Any]:
    safe_report, transport_diagnostics = _safe_validation_transport_report(report)
    upstream_diagnostics: list[dict[str, Any]] = []
    for item in safe_report.get("copySafetyDiagnostics") or []:
        if not isinstance(item, dict) or not item.get("flags"):
            continue
        diagnostic = {
            "loc": list(item.get("loc") or []),
            "flags": list(item.get("flags") or []),
            "blockingFlags": list(item.get("flags") or []),
        }
        if "originLoc" in item:
            diagnostic["originLoc"] = list(item.get("originLoc") or [])
            diagnostic["originKind"] = str(item.get("originKind") or "unknown")
            if item.get("safeTitle"):
                diagnostic["safeTitle"] = item["safeTitle"]
        upstream_diagnostics.append(diagnostic)
    copy_safety_diagnostics = [*upstream_diagnostics, *transport_diagnostics]
    blocking_copy_safety = [item for item in copy_safety_diagnostics if item["blockingFlags"]]
    deferred_reason_counts = dict(safe_report.get("deferredReasonCounts") or {})
    schema_issue_count = int(deferred_reason_counts.get("invalid_schema") or 0)
    validation_issues: list[dict[str, Any]] = []
    for deferred in safe_report.get("deferredCandidates") or []:
        validation_issues.extend(list(deferred.get("validationIssues") or []))
    for key in ("patternWrite", "deepRecordWrite"):
        write_result = safe_report.get(key) or {}
        if write_result.get("errorCode") == "invalid_schema":
            schema_issue_count += 1
            validation_issues.extend(
                list((write_result.get("facts") or {}).get("validationIssues") or [])
            )
    validation_issues.extend(
        {
            "loc": item["loc"],
            "msg": "validation text failed copy-safety: " + ", ".join(item["blockingFlags"]),
            "type": "copy_safety",
        }
        for item in transport_diagnostics
        if item["blockingFlags"]
    )
    ready = (
        safe_report.get("status") == "accepted"
        and schema_issue_count == 0
        and not blocking_copy_safety
    )
    deferred_candidate_count = int(safe_report.get("deferredCandidateCount") or 0)
    unresolved_mention_count = int(
        safe_report.get("unresolvedDeepRecordMentionCount")
        or safe_report.get("unresolvedDeepRecordComponentCount")
        or 0
    )
    case_coverage_gap_count = int(safe_report.get("caseCoverageGapCount") or 0)
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
        "wouldAcceptPatternCount": int(safe_report.get("acceptedPatternCount") or 0),
        "wouldAcceptDeepRecordCount": int(safe_report.get("acceptedDeepRecordCount") or 0),
        "wouldAcceptSemanticEdgeCount": int(safe_report.get("acceptedSemanticEdgeCount") or 0),
        "unresolvedDeepRecordComponentCount": int(
            safe_report.get("unresolvedDeepRecordComponentCount") or 0
        ),
        "unresolvedDeepRecordMentionCount": unresolved_mention_count,
        "unresolvedUniqueComponentCount": int(
            safe_report.get("unresolvedUniqueComponentCount") or 0
        ),
        "unkeyedDeepRecordCount": int(safe_report.get("unkeyedDeepRecordCount") or 0),
        "deepRecordsWithoutKnowledgeIdentity": safe_report.get(
            "deepRecordsWithoutKnowledgeIdentity"
        )
        or [],
        "deepRecordsWithUnresolvedComponents": safe_report.get(
            "deepRecordsWithUnresolvedComponents"
        )
        or [],
        **_research_quality_summary(safe_report),
        "acceptanceMode": acceptance_mode,
        "schemaIssueCount": schema_issue_count,
        "validationIssues": validation_issues,
        "copySafetyDiagnostics": copy_safety_diagnostics,
        "copySafetyBlockingIssueCount": len(blocking_copy_safety),
        "deferredCandidateCount": deferred_candidate_count,
        "deferredReasonCounts": deferred_reason_counts,
        "deferredCandidates": safe_report.get("deferredCandidates") or [],
        "patternValidation": safe_report.get("patternWrite") or {},
        "deepRecordValidation": safe_report.get("deepRecordWrite") or {},
        "semanticEdgeValidation": safe_report.get("semanticEdgeWrite") or {},
        "noRawMatureBuildMaterial": True,
    }


def _safe_validation_transport_report(
    report: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Redact unsafe validation prose while preserving safe paths and repair categories."""

    diagnostics: list[dict[str, Any]] = []
    typed_key_fields = {
        "componentKey",
        "componentKeys",
        "skillKey",
        "supportKeys",
        "hostSkillKey",
        "resolverQuery",
        "recordRef",
        "sourceGroupRef",
        "rootSkillRef",
    }

    def visit(value: Any, *, path: list[str | int]) -> Any:
        if isinstance(value, dict):
            safe_mapping: dict[str, Any] = {}
            for child_key, child in value.items():
                safe_key = _safe_validation_path_segment(str(child_key))
                safe_mapping[safe_key] = visit(child, path=[*path, safe_key])
            return safe_mapping
        if isinstance(value, list):
            return [visit(child, path=[*path, index]) for index, child in enumerate(value)]
        if isinstance(value, str):
            flags = copy_safety.copyability_flags(value)
            if path and str(path[-1]) in typed_key_fields:
                blocking_flags = copy_safety.durable_knowledge_flags(value)
                if not blocking_flags:
                    return value
            if (
                path
                and path[-1] == "reportId"
                and flags == ["full_gem_link_like"]
                and re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,120}", value)
            ):
                return value
            if flags:
                blocking_flags = copy_safety.durable_knowledge_flags(value)
                if not blocking_flags:
                    return value
                diagnostics.append(
                    {
                        "loc": path,
                        "flags": flags,
                        "blockingFlags": blocking_flags,
                    }
                )
                return "[validation text redacted by copy-safety: " + ", ".join(flags) + "]"
        return value

    safe_report = visit(copy.deepcopy(report), path=[])
    if not isinstance(safe_report, dict):
        raise TypeError("validation report must remain an object after transport redaction")
    return safe_report, diagnostics


def _safe_validation_path_segment(value: str) -> str:
    if len(value) <= 120 and not copy_safety.copyability_flags(value):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"redacted-key:{digest}"


def _durable_write_preflight(
    *,
    memory_db_path: Path,
    intake_ledger_path: Path,
    requires_intake_ledger: bool,
) -> dict[str, Any]:
    """Check current-process write access without creating files or changing task state."""

    memory_writable = _existing_write_handle_available(memory_db_path)
    lock_writable = _existing_write_handle_available(_accept_lock_path(memory_db_path))
    ledger_writable = (
        _existing_write_handle_available(intake_ledger_path) if requires_intake_ledger else True
    )
    checks = {
        "memoryDb": memory_writable,
        "acceptLock": lock_writable,
        "intakeLedger": ledger_writable,
    }
    ready = all(value is True for value in checks.values())
    return {
        "status": "write_handle_ready" if ready else "permission_required",
        "memoryDbWritable": memory_writable,
        "acceptLockWritable": lock_writable,
        "intakeLedgerRequired": requires_intake_ledger,
        "intakeLedgerWritable": ledger_writable,
        "unknownTargets": [name for name, value in checks.items() if value is None],
        "requiresWriteApproval": not ready,
        "advisoryOnly": True,
        "scope": "existing_file_handles_only",
        "sqliteSidecarCreationUnverified": True,
        "checkedWithoutMutation": True,
    }


def _existing_write_handle_available(path: Path) -> bool | None:
    try:
        target = Path(path)
        if not target.is_file():
            # Creation cannot be proven without mutating the parent directory. Fail closed and
            # let the Worker request permission before formal accept.
            return None
        with target.open("r+b"):
            pass
        return True
    except PermissionError:
        return False
    except OSError:
        return None


_COMPACT_MECHANIC_AUDIT_KEYS = (
    "entryCount",
    "highRiskRecordCount",
    "liveEvidenceCoverage",
    "liveEvidenceStatus",
    "pinnedRevisionCount",
    "provided",
    "schemaIssueCount",
    "statusCounts",
    "decisionCounts",
    "advisories",
    "deferredObjectCount",
    "compoundWikiQueryCount",
    "unauditedHighRiskRecordCount",
    "unauditedHighRiskRecordTitles",
)


def _should_compact_report(result: dict[str, Any]) -> bool:
    if result.get("status") not in ("accepted", "validation_passed"):
        return False
    if int(result.get("deferredCandidateCount") or 0) > 0:
        return False
    if (
        int(
            result.get("unresolvedDeepRecordMentionCount")
            or result.get("unresolvedDeepRecordComponentCount")
            or 0
        )
        > 0
    ):
        return False
    if int(result.get("unresolvedUniqueComponentCount") or 0) > 0:
        return False
    if int(result.get("caseCoverageGapCount") or 0) > 0:
        return False
    return True


def _compact_accept_result(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    audit = out.get("mechanicAudit")
    if isinstance(audit, dict):
        out["mechanicAudit"] = {
            key: audit[key] for key in _COMPACT_MECHANIC_AUDIT_KEYS if key in audit
        }
    else:
        out.pop("mechanicAudit", None)
    deep_record_write = out.get("deepRecordWrite")
    record_writes = (
        deep_record_write.get("recordWrites") or [] if isinstance(deep_record_write, dict) else []
    )
    out["writeAdvisoryCounts"] = {
        "crossFamilyDuplicate": sum(
            len(item.get("crossFamilyDuplicateAdvisories") or [])
            for item in record_writes
            if isinstance(item, dict)
        )
    }
    for key in (
        "sourceEvidenceDiagnostics",
        "patternWrite",
        "deepRecordWrite",
        "semanticEdgeWrite",
        "patternValidation",
        "deepRecordValidation",
        "semanticEdgeValidation",
        "deferredCandidates",
    ):
        out.pop(key, None)
    return out


def _identity_resolvability_hint(
    *,
    ascendancy: str,
    main_skill: str,
    source_skill_id: str | None = None,
) -> dict[str, Any]:
    """Best-effort identity resolvability pre-check for a claimed case.

    Advisory only: a failed graph load or unresolved display name never blocks the
    claim; the formal identity gate still lives in accept. Renamed ascendancies
    (e.g. Witch "Lich" -> "Abyssal Lich") resolve through graph aliases, so the
    canonical key hint prevents researcher-side mislabelling.
    """
    normalized_source_skill_id = str(source_skill_id or "").strip()
    has_primary = bool(normalized_source_skill_id or str(main_skill or "").strip())
    hint: dict[str, Any] = {
        "ascendancyCanonicalKey": None,
        "ascendancyResolvable": False,
        "primarySkillResolvable": False,
        "primarySkillResolutionHint": {
            "authority": "programmatic_snapshot_non_authoritative",
            "subject": "pob_selected_calculation_skill",
            "status": "graph_unavailable" if has_primary else "not_provided",
            "queryKind": "source_skill_id" if normalized_source_skill_id else "display_name",
            "displayName": str(main_skill or "").strip(),
            "sourceSkillId": normalized_source_skill_id or None,
            "resolvedSkillKey": None,
            "candidateSkillKeys": [],
            "snapshotId": None,
            "authorizesFamilyIdentity": False,
        },
    }
    ascendancy_name = str(ascendancy or "").strip()
    main_skill_name = str(main_skill or "").strip()
    try:
        index_path = graph_seed.ensure_installed()
        service = graph_tools.service_from_snapshot_index(str(index_path))
    except Exception:
        return hint
    hint["primarySkillResolutionHint"]["snapshotId"] = (
        str(getattr(service.snapshot, "snapshot_id", "") or "") or None
    )
    try:
        if ascendancy_name:
            result = service.run_tool(
                "resolve_graph_component",
                {"query": ascendancy_name, "expected_node_types": ["ascendancy"]},
            )
            if result.get("status") == "resolved":
                resolved = (result.get("resolvedSubject") or {}).get("stableKey") or ""
                hint["ascendancyCanonicalKey"] = str(resolved) or None
                hint["ascendancyResolvable"] = True
    except Exception:
        pass
    try:
        if normalized_source_skill_id or main_skill_name:
            exact_skill_key = (
                normalized_source_skill_id
                if normalized_source_skill_id.startswith("skill:")
                else f"skill:{normalized_source_skill_id}"
                if normalized_source_skill_id
                else ""
            )
            result = service.run_tool(
                "resolve_graph_component",
                {
                    "query": exact_skill_key or main_skill_name,
                    "expected_node_types": ["active_skill"],
                    "scope": "player",
                },
            )
            status = str(result.get("status") or "missing")
            public_status = status if status in {"resolved", "ambiguous", "missing"} else "missing"
            candidates: list[str] = []
            resolved_subject = result.get("resolvedSubject") or {}
            resolved_key = str(resolved_subject.get("stableKey") or "")
            if exact_skill_key and public_status == "resolved" and resolved_key != exact_skill_key:
                public_status = "ambiguous"
            for item in result.get("candidates") or result.get("candidateSubjects") or []:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("stableKey") or item.get("componentKey") or "")
                if key.startswith("skill:"):
                    candidates.append(key)
            if resolved_key.startswith("skill:"):
                candidates.append(resolved_key)
            hint["primarySkillResolutionHint"].update(
                {
                    "status": public_status,
                    "resolvedSkillKey": resolved_key or None,
                    "candidateSkillKeys": sorted(set(candidates))[:12],
                }
            )
            hint["primarySkillResolvable"] = public_status == "resolved"
    except Exception:
        hint["primarySkillResolutionHint"]["status"] = "graph_unavailable"
    return hint


def _claim_payload(
    row: dict[str, Any],
    *,
    lease_token: str,
    output_root: Path,
    temp_root: str | Path | None,
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
    source_skill_id = ""
    try:
        packet = _packet_for_valid_lease(
            row=row,
            output_dir=output_root,
            temp_root=temp_root,
        )
        raw_context = packet.get("rawContext")
        raw_xml = str(raw_context.get("rawXml") or "") if isinstance(raw_context, dict) else ""
        selected_identity = pob_xml_meta.main_skill_identity_from_pob_xml(raw_xml)
        source_skill_id = str((selected_identity or {}).get("skillId") or "")
    except (FileNotFoundError, ValueError):
        source_skill_id = ""
    identity_hint = _identity_resolvability_hint(
        ascendancy=str(row["ascendancy"]),
        main_skill=str(row["main_skill"]),
        source_skill_id=source_skill_id,
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
        **identity_hint,
        "leaseToken": lease_token,
        "leaseExpiresAt": str(row["lease_expires_at"]),
        "supplement": bool(row["supplement"]),
        "supplementContext": str(row["supplement_context"] or ""),
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
    version_context: dict[str, str],
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
        version_context=version_context,
    )


def _canonical_review_artifact_identity(
    *,
    review_file: Path,
    sample_id: str,
    source_hash_ref: str,
    packet_safe_hash: str,
    version_context: dict[str, str],
) -> dict[str, Any]:
    payload = json.loads(review_file.read_text(encoding="utf-8"))
    return _canonical_review_payload(
        payload=payload,
        sample_id=sample_id,
        source_hash_ref=source_hash_ref,
        packet_safe_hash=packet_safe_hash,
        version_context=version_context,
    )


def _canonical_review_payload(
    *,
    payload: Any,
    sample_id: str,
    source_hash_ref: str,
    packet_safe_hash: str,
    version_context: dict[str, str],
) -> dict[str, Any]:
    """Bind one safe in-memory review to its authoritative queue identity."""

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
        if not isinstance(artifact_identity, dict):
            raise ValueError(
                "review artifactIdentity does not match the current lease; "
                "expected an object, got " + str(type(artifact_identity).__name__)
            )
        mismatched = {
            key: {"expected": value, "actual": str(artifact_identity.get(key) or "")}
            for key, value in expected_identity.items()
            if str(artifact_identity.get(key) or "") != value
        }
        if mismatched:
            detail = ", ".join(
                f"{key} expected={item['expected']!r} actual={item['actual']!r}"
                for key, item in sorted(mismatched.items())
            )
            raise ValueError("review artifactIdentity does not match the current lease; " + detail)
    elif not entries or any(
        str(item.get("caseRef") or "") != source_hash_ref
        or expected_evidence_ref not in _review_evidence_refs(item)
        for item in entries
    ):
        raise ValueError(
            "review artifact identity does not match the current lease; expected "
            f"caseRef={source_hash_ref!r} and safeEvidenceRef={expected_evidence_ref!r} "
            "on every deepResearchRecord/candidateReview"
        )
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
    canonical_version_requirement = {
        "context_type": "version_context",
        "game_patch": version_context["gamePatch"],
        "passive_tree_version": version_context["passiveTreeVersion"],
        "pob_version": version_context["pobVersionOrCommit"],
    }
    for edge in canonical.get("semanticEdges") or []:
        if not isinstance(edge, dict):
            continue
        edge["source_case_refs"] = [source_hash_ref]
        edge["safe_evidence_refs"] = [expected_evidence_ref]
        edge["game_patch"] = version_context["gamePatch"]
        edge["passive_tree_version"] = version_context["passiveTreeVersion"]
        edge["pob_version_or_commit"] = version_context["pobVersionOrCommit"]
        requirements = edge.get("context_requirements")
        if requirements is None:
            requirements = []
        elif not isinstance(requirements, list):
            # Preserve the invalid caller shape so typed semantic-edge validation rejects it.
            continue
        retained_requirements = [
            requirement
            for requirement in requirements
            if not (
                isinstance(requirement, dict)
                and requirement.get("context_type") == "version_context"
            )
        ]
        edge["context_requirements"] = [
            canonical_version_requirement,
            *retained_requirements,
        ]
    return canonical


def _lease_artifact_identity(row: sqlite3.Row) -> dict[str, str]:
    packet_safe_hash = str(row["packet_safe_hash"])
    return {
        "sampleId": str(row["sample_id"]),
        "caseRef": str(row["source_hash_ref"]),
        "safeEvidenceRef": f"evidence:{packet_safe_hash[:16]}",
        "packetSafeHash": packet_safe_hash,
    }


def _authoritative_knowledge_scope(row: sqlite3.Row | dict[str, Any]) -> str:
    """Derive durable scope from server-owned source provenance."""

    source_type = str(row["source_type"] or "").strip().casefold()
    if source_type in {"poe_ninja_import_code", "poe_ninja", "public_poe_ninja"}:
        return "global_seed"
    return "local_user"


def _bind_authoritative_review_scope(
    review_payload: dict[str, Any],
    *,
    row: sqlite3.Row | dict[str, Any],
    mismatch_error: str,
) -> dict[str, Any]:
    """Apply the same server-owned scope projection before every accept-attempt hash."""

    authoritative_scope = _authoritative_knowledge_scope(row)
    submitted_scope = str(review_payload.get("knowledgeScope") or authoritative_scope)
    if submitted_scope != authoritative_scope:
        raise ValueError(mismatch_error)
    review_payload["knowledgeScope"] = authoritative_scope
    for edge in review_payload.get("semanticEdges") or []:
        if isinstance(edge, dict):
            edge["knowledge_scope"] = authoritative_scope
    return review_payload


def _assert_matching_inflight_review(
    *,
    db_path: Path,
    row: sqlite3.Row,
    review_payload: dict[str, Any],
    expected_origin_state: str,
) -> None:
    """Permit replay only when the submitted canonical review owns the in-flight attempt."""

    _bind_authoritative_review_scope(
        review_payload,
        row=row,
        mismatch_error="in-flight review knowledgeScope does not match source provenance",
    )
    run_id = str(_read_metadata(db_path).get("runId") or db_path.parent.name)
    expected_attempt_key = research_runtime.accept_attempt_key(
        run_id=run_id,
        sample_id=str(row["sample_id"]),
        packet_safe_hash=str(row["packet_safe_hash"]),
        canonical_review_hash=research_runtime.stable_hash(review_payload),
        contract_version=str(review_payload.get("reviewContractVersion") or ""),
        expected_origin_state=expected_origin_state,
    )
    if expected_attempt_key != str(row["accept_attempt_key"] or ""):
        raise ValueError("in-flight review hash does not match acceptAttemptKey")


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
    supplement = int(row["supplement"] or 0)
    supplement_context = str(row["supplement_context"] or "")
    supplement_section = ""
    if supplement:
        supplement_section = (
            "\n## Supplement Research\n"
            "- 这是对同一来源案例的补充研究轮（前一轮已验收入库）。身份记录会由 accept 自动归入"
            "既有 Family（join/expand + family_merge_log），无需手动复刻首轮身份结构；"
            "clear_skill / boss_skill / triggered_payload 自动副技能与 trigger-host 不参与身份。\n"
            "- 先查询既有 Family 知识（query_research_memory 的 familyRecordCoverage / "
            "familyRecordIndex / familyPremiseCatalog），只补缺口，不得重复已有结论；"
            "同一知识命中 knowledge_key 会原地更新，不产生新记录。\n"
            "- 本轮必须产生至少一条新增或更新记录（created+updated ≥ 1），否则 accept 会判定"
            "补充轮无效。\n"
            + (f"- 本轮聚焦清单：{supplement_context}\n" if supplement_context else "")
        )
    mandatory_checks_text = "\n".join(
        f"{index}. {check}" for index, check in enumerate(RESEARCH_MANDATORY_CHECKS, start=1)
    )
    return f"""你正在执行 PoE2 mature build Researcher 流程，只负责当前 leased case。
这是当前案例的安全导航 brief。
{supplement_section}

## Runtime Boundary
- 这是产品运行态，不要修改源码、测试、文档、schema 或安装配置。
- 你是当前 lease 的唯一 worker，必须连续持有证据上下文、safe review 与 accept 责任；不得再次
  委派，也不得领取第二个案例。
- 所有后续脚本命令都必须携带最初 queue 返回的 `--output-dir <runDir>`，不得使用默认共享目录。
- 不要读源码或临时构造 service 绕过 MCP、lease 或 acceptance 边界。
- 原始 PoB/XML 只能留在 run 内 quarantine 与 transient packet，不得写入聊天、safe review 或 durable memory。
- claim 成功后的任何结束路径都必须返回 sampleId 和 safe outcome；accepted 时附 safe acceptance 摘要。
- 最终只报告 safe artifact、验收状态和安全错误。

## Case
- sampleId: {sample_id}
- leaseToken: {lease_token}
- sourceType/sourceRef: {source_type} / {source_hash_ref}
- class/ascendancy/level: {class_name} / {ascendancy} / {level}
- programmatic mainSkill candidate: {main_skill or "unknown"}（非权威快照线索）
- packetSafeHash: {packet_safe_hash}
- safeReviewFile: {review_file}（相对当前 --output-dir）

## Research Quality First
研究质量优先于速度与上下文预算：必须完整读取全部要求的分区，并盘点每个启用技能组。Family
主技能、核心副技能以及研究结论实际依赖的高影响组应使用 supportPackages 或
supportCoverageExceptions 保存根技能与 socketed items；低影响、内部 id 或无法唯一解析的组可以保留
为明确 caveat / verification task，不得静默丢弃，也不因其自身缺口机械否定整个案例。
批量 resolve 与精简视图用于降低上下文成本；优先把精力用于构筑身份、因果链和失败条件。

## Evidence First
先运行 inspect，再严格按 recommendedReadOrder（包括 skill-groups 与 pob-readback）把每个分区分页读完；
complete=false 时用上一页响应的 nextCursor 续页（不要用 cursor+limit 自算：字符预算截断时实返
数量会少于请求 limit，自算会跳过中间条目；响应出现 continuityWarning 时尤其如此）。
jewels 分区只含天赋树珠宝（gear 分区仍包含它们，供逐槽对照）；search 只能定位
具体线索，不能替代完整分区读取。
技能、天赋和装备效果必须来自当前案例证据或工具事实；允许保留有价值的推断，但必须明确标为推断，
不能把模型记忆中的免疫、转换、触发或缩放效果写成已证实事实。

独立重建当前案例后，先解析身份组件：用 search_graph_components 发现候选、用
resolve_graph_component 确认 ascendancy 与 class 的 stable key（显示名不会命中存储 key，会静默
返回空）；再以 stable key 调用 query_research_memory，首次身份宽查固定使用
`detail_level="summary" + response_profile="create_compact"`。检查返回的 familyRecordCoverage /
familyRecordIndex / familyPremiseCatalog；选定 Family 后，按 familyRecordIndex 的 `record_ids` 调用
`detail_level="record" + response_profile="create_compact"` 精确深读，直到关键 premise、失败条件和
验证任务闭合，不设置固定深读额度。逐条对照既有同升华/同技能 Family 知识。其余组件同样先 search
再 resolve，不得猜 key 路径（支持宝石 metadata 路径可能有
Items/Gem 与 Items/Gems 两种形式）。工具未直接显示时，使用宿主标准 tool discovery / tool search
按精确名称查找；工具可能采用延迟发现，不要根据首屏工具列表断言不可用。

独立重建和组件解析完成后，针对会改变因果链的高风险结论做一轮轻量机制校对：先用
explain_mechanic / search_mechanics 查看当前本地静态机制资料，再用 lookup_mechanic 查询实时
poe2wiki。重点检查触发与手动施放、前置状态、资源生成/消耗、伤害转换、mutation/transform 等；
不要为普通组件名称逐个查 Wiki。每次只查询一个精确页面或中央机制名称，不得拼接 `A / B`；需要多页
时写多条原子审计。全文搜索只返回候选，不授权结论；选中候选后按精确标题重新读取正文，由你判断
`supports / contradicts / silent`，并在 `wiki.relevanceReason` 说明内容为何回答或没有回答当前 claim。
直接标题、redirect、页面 ID 和 revision 只证明页面身份，同样不能替代内容判断。每条 mechanic_chain 和 resource_engine 都必须由 mechanicAudit 精确引用，claim
必须写对象真正依赖的最强因果结论，不能只审计较弱前提。把复核结果写入顶层 mechanicAudit，并使用
lookup_mechanic 返回的 revision-pinned sourceRef。Wiki 只作校对证据，不能替代来源实例归属、support
兼容性、武器状态、Family 身份或数值 Judge；每项结论仍需注明 source artifact、PoB static、typed
graph 等独立佐证。

## Mandatory Checks
以下 {len(RESEARCH_MANDATORY_CHECKS)} 项是提交前的强制自检，缺一不可：
{mandatory_checks_text}

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

  research_mature_builds.py accept --output-dir <runDir> --lease-token {lease_token} --review-file {review_file} --validate-only --compact

若返回 validation_failed，按 validationIssues 自行修正并重新校验。readyForAccept=true 只表示安全子集
可以接收；fullyResolvedForAccept=true 才表示已有可归档的 Build Family，且没有覆盖缺口、候选暂缓
或深度记录组件缺口。对
component_type_mismatch、错误 role/query 和其他可修复问题先做一次有界修复；只有真实 source coverage
缺口或经复核仍无法唯一解析的内容才保留为 partial_with_deferred。validate-only 不写 durable memory，
也不改变当前 lease。

校验通过后，正式 `accept` 与可修复拒绝后的 `retry-accept` 同样使用 `--compact`；有 deferred、
unresolved、coverage gap 或 failure 时 CLI 会自动回退完整报告，不得手工隐藏失败详情。
`review_contract_upgrade_required` 发生在队列 CAS 前，案例仍为 claimed：补齐 v2 review 后必须用同一
lease token 重新运行普通 `accept --compact`，不能改走只接受 rejected 案例的 `retry-accept`。
"""


def _normalize_sample_ids(cases: list[dict[str, Any]], *, sample_start_index: int) -> None:
    index = max(1, int(sample_start_index))
    for case in cases:
        if case.get("supplement"):
            # Supplement research keeps the prior run's sample id for traceability.
            continue
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


def _preflight_queue_cli(args: argparse.Namespace) -> None:
    if args.supplement_sample_id is not None and not args.re_research:
        raise ValueError("--supplement-sample-id requires --re-research")
    if not args.re_research:
        return
    if args.source_file or args.source_batch_file:
        raise ValueError("--re-research cannot be combined with local source input")
    if args.resume:
        raise ValueError("--re-research cannot be combined with --resume")
    if args.expected_source_count is not None:
        raise ValueError("--re-research cannot be combined with --expected-source-count")
    prior = Path(args.re_research)
    if not (prior / QUEUE_DB_FILENAME).is_file():
        raise ValueError(f"--re-research run directory has no {QUEUE_DB_FILENAME}")
    if args.supplement_sample_id is not None:
        selection = inspect_supplement_selection(prior, args.supplement_sample_id)
        if selection["status"] != "ok":
            raise ValueError(
                "invalid targeted supplement selection: "
                + json.dumps(selection, ensure_ascii=False, sort_keys=True)
            )


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
    context["modelGamePatch"] = local.get("gamePatch", "")
    context["status"] = ("source_patch_model_mismatch" if context["gamePatch"] != local.get("gamePatch")
                         else "certified_local_runtime")
    return research_readback.normalize_version_context(context)


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
        "modelGamePatch": _known_version(metadata.get("modelGamePatch")),
    }
    missing = [key for key, value in context.items() if not value and key != "modelGamePatch"]
    if missing:
        raise ValueError(
            "research queue lacks durable version context; recreate the queue after updating "
            f"the local certified runtime ({', '.join(missing)})"
        )
    return research_readback.normalize_version_context(context)


def _known_version(value: Any) -> str:
    normalized = str(value or "").strip()
    return "" if normalized.casefold() in {"", "unknown", "none", "null"} else normalized


def _effective_temp_root(temp_root: str | Path | None, *, output_root: Path) -> Path:
    if temp_root is None:
        # Controller and Worker subprocesses share the run directory, while sandboxed Workers
        # may not be allowed to read the Controller's OS temp directory. The run is already a
        # private raw-bearing quarantine boundary and cleanup removes it as one unit, so keep
        # the default lease packet in a separate private subtree of that same boundary.
        return (Path(output_root) / DEFAULT_TEMP_DIRNAME).resolve()
    root = Path(temp_root)
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


def _safe_os_error(exc: OSError) -> dict[str, Any]:
    """Safe numeric OSError detail without leaking filesystem paths."""
    return {
        "errno": exc.errno,
        "winerror": exc.winerror if getattr(exc, "winerror", None) is not None else None,
        "strerror": str(exc.strerror or ""),
    }


def _now_iso() -> str:
    return _iso(_now())


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _assert_safe_payload(
    payload: dict[str, Any], *, allow_core_mechanisms: bool = False
) -> None:
    """Guard transport; only reviewed-knowledge results allow bounded core mechanisms.

    Validation, acceptance and retry reports already use the durable-knowledge policy.
    Their diagnostic prose must keep that policy at the final transport boundary too.
    This never authorizes a record or changes raw-material checks; queue/control payloads
    retain the stricter default.
    """
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe research queue markers detected: {', '.join(leaks)}")
    if copy_safety.find_forbidden_paths(payload):
        raise ValueError("unsafe research queue contains forbidden raw fields")
    classify = (
        copy_safety.durable_knowledge_flags
        if allow_core_mechanisms
        else copy_safety.copyability_flags
    )
    flags: set[str] = set()
    for text in _human_text(payload):
        flags.update(classify(text))
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


def _rewrite_lease_token_argv(argv: list[str] | None) -> list[str] | None:
    """Rewrite ``--lease-token <value>`` into the equals form when the value starts with ``-``.

    argparse treats a ``-``-leading option value as a new option, so legacy dash-leading
    lease tokens would fail with "expected one argument". Only ``--lease-token`` is
    rewritten (never other options, whose dash-leading values must keep failing loudly);
    ``None`` and already-equals-form arguments pass through untouched.
    """
    if argv is None:
        return None
    out: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if (
            arg == "--lease-token"
            and index + 1 < len(argv)
            and str(argv[index + 1]).startswith("-")
        ):
            out.append(f"--lease-token={argv[index + 1]}")
            index += 2
            continue
        out.append(arg)
        index += 1
    return out


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
    # Windows GBK consoles garble UTF-8 Chinese output; normalize stdout to UTF-8 unless the
    # user explicitly chose another encoding (PYTHONIOENCODING / UTF-8 mode / already UTF-8).
    try:
        if (
            not os.environ.get("PYTHONIOENCODING")
            and not sys.flags.utf8_mode
            and getattr(sys.stdout, "encoding", None) != "utf-8"
        ):
            sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass
    parser = argparse.ArgumentParser(prog="poe-bd-research")
    subparsers = parser.add_subparsers(dest="command", required=True)

    queue_parser = subparsers.add_parser(
        "queue",
        description=(
            "Collect mature build samples into a safe research queue. Real enqueueing happens "
            "by default; use --dry-run only to verify the collector chain without creating a "
            "queue or producing knowledge. Interactive agents: when the user states a case "
            "count or analysis intent, run with --limit N directly and do not offer the "
            "preflight dry-run instead."
        ),
    )
    _add_queue_location_args(queue_parser, default_output_dir=None)
    queue_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help=(
            "Number of new cases to enqueue (default 50). The default is a CLI compatibility "
            "value: interactive skill invocations must not silently start 50; run the count "
            "the user actually asked for."
        ),
    )
    queue_parser.add_argument(
        "--worker-count",
        type=int,
        default=DEFAULT_WORKER_COUNT,
        help="Concurrent one-case research workers (default 5, clamped to 1-5).",
    )
    queue_parser.add_argument("--league", default="current")
    queue_parser.add_argument(
        "--level-min",
        type=int,
        default=90,
        help=(
            "Inclusive lower level bound. Level filters are ranges, not exact matches: "
            "poe.ninja ladder rows are sampled highest level first, so a range like "
            "95-100 deterministically returns level-100 builds unless fewer exist. Use "
            "--level-min == --level-max for an exact level."
        ),
    )
    queue_parser.add_argument("--level-max", type=int, default=100)
    queue_parser.add_argument("--ascendancy", action="append", default=[])
    queue_parser.add_argument("--class", dest="ninja_classes", action="append", default=[])
    queue_parser.add_argument("--source-file", action="append", default=[])
    queue_parser.add_argument("--source-batch-file", action="append", default=[])
    queue_parser.add_argument("--expected-source-count", type=int)
    queue_parser.add_argument("--sample-start-index", type=int, default=1)
    queue_parser.add_argument("--resume", action="store_true")
    queue_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Only inspect the safe samples that would be enqueued; no queue is created and no "
            "knowledge is produced. Use it only to verify the poe.ninja/collector chain when "
            "the user explicitly wants a link check - never as a substitute for real analysis "
            "(run --limit N instead)."
        ),
    )
    queue_parser.add_argument(
        "--re-research",
        default=None,
        metavar="RUN_DIR",
        help="Re-queue every case of a completed research run as local supplement research "
        "(same source re-studied to close gaps). Raw material is rebuilt from that run's "
        "quarantine; cases are marked supplement=true and accept enforces a created+updated "
        ">= 1 gate.",
    )
    queue_parser.add_argument(
        "--supplement-focus",
        default="",
        help="Optional focus checklist injected into the supplement-round worker brief "
        "(e.g. '骷髅军团各宝宝配装、资源账本').",
    )
    queue_parser.add_argument(
        "--supplement-sample-id",
        action="append",
        default=None,
        help="With --re-research, re-queue only these exact prior-run sampleIds. Repeatable.",
    )
    queue_parser.add_argument("--ttl-seconds", type=int, default=24 * 60 * 60)
    queue_parser.add_argument(
        "--intake-ledger",
        default=None,
        help="Override the per-user research intake dedup ledger (character-level "
        "cross-run dedup for poe.ninja collection). Default: user data dir.",
    )
    queue_parser.add_argument("--current-patch")
    queue_parser.add_argument("--passive-tree-version")
    queue_parser.add_argument("--pob-version-or-commit")

    claim_parser = subparsers.add_parser("claim")
    _add_queue_location_args(claim_parser)
    claim_parser.add_argument("--lease-seconds", type=int, default=7200)
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
    read_parser.add_argument(
        "--section",
        required=True,
        choices=list(research_packet.RESEARCH_SECTIONS) + ["skill-groups"],
        help="structured section; skill-groups returns each root skill and its socketed items",
    )
    read_parser.add_argument(
        "--cursor",
        type=int,
        default=0,
        help="page cursor: the previous response's nextCursor (0 starts at the first page)",
    )
    read_parser.add_argument(
        "--limit",
        type=int,
        default=research_packet.DEFAULT_PAGE_SIZE,
        help="requested page size; the response may return fewer items when a large entry "
        "hits the response character budget (use nextCursor to continue)",
    )
    read_parser.add_argument(
        "--node-type",
        default=None,
        help="passives only: keystone|notable|jewel_socket|granted_jewel_socket|"
        "ascendancy|mastery|normal",
    )
    read_parser.add_argument(
        "--exclude-routing",
        action="store_true",
        default=False,
        help="passives + --node-type normal only: drop pure routing/attribute nodes "
        "(+5 to any Attribute) to reduce low-information pagination",
    )

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
    accept_parser.add_argument(
        "--only-record",
        type=int,
        default=None,
        help="Validate a single deep record by index (requires --validate-only); "
        "caseCoverage/Family/deferred counts reflect the single-record slice.",
    )
    accept_parser.add_argument(
        "--compact",
        action="store_true",
        help="Return a compact acceptance summary; automatically falls back to the full report "
        "when any candidate is deferred or validation failed.",
    )
    accept_parser.add_argument(
        "--intake-ledger",
        default=None,
        help="Override the per-user research intake dedup ledger updated on accept.",
    )

    retry_accept_parser = subparsers.add_parser("retry-accept")
    _add_queue_location_args(retry_accept_parser)
    retry_accept_parser.add_argument("--sample-id", required=True)
    retry_accept_parser.add_argument("--review-file", required=True)
    retry_accept_parser.add_argument("--memory-db-path", default=str(DEFAULT_MEMORY_DB_PATH))
    retry_accept_parser.add_argument("--acceptance-output-dir")
    retry_accept_parser.add_argument("--intake-ledger", default=None)
    retry_accept_parser.add_argument("--compact", action="store_true")

    review_budget_parser = subparsers.add_parser("review-budget")
    review_budget_parser.add_argument("--review-file", required=True)

    status_parser = subparsers.add_parser("status")
    _add_queue_location_args(status_parser)

    # ``parse_args(None)`` reads ``sys.argv`` itself, which would bypass the compatibility
    # rewrite below. Materialize the real CLI arguments first so legacy dash-leading lease
    # tokens follow the same path as programmatic ``main([...])`` calls.
    effective_argv = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(_rewrite_lease_token_argv(effective_argv))
    try:
        if args.command == "queue":
            _preflight_queue_cli(args)
            run_id, output_dir = _queue_cli_output_dir(args)
            try:
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
                    intake_ledger_path=args.intake_ledger,
                    re_research_run_dir=args.re_research,
                    supplement_sample_ids=args.supplement_sample_id,
                    supplement_focus=args.supplement_focus,
                )
            except BaseException:
                if run_id is not None:
                    shutil.rmtree(output_dir, ignore_errors=True)
                raise
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
                    node_type=args.node_type,
                    exclude_routing=args.exclude_routing,
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
            result = accept_case(
                output_dir=args.output_dir,
                queue_db_path=args.queue_db_path,
                lease_token=args.lease_token,
                review_file=args.review_file,
                memory_db_path=args.memory_db_path,
                acceptance_output_dir=args.acceptance_output_dir,
                temp_root=args.temp_root,
                validation_only=args.validate_only,
                only_record=args.only_record,
                intake_ledger_path=args.intake_ledger,
            )
            if getattr(args, "compact", False) and _should_compact_report(result):
                result = _compact_accept_result(result)
            _print_json(result)
            return 0
        if args.command == "retry-accept":
            result = retry_accept_case(
                output_dir=args.output_dir,
                queue_db_path=args.queue_db_path,
                sample_id=args.sample_id,
                review_file=args.review_file,
                memory_db_path=args.memory_db_path,
                acceptance_output_dir=args.acceptance_output_dir,
                temp_root=args.temp_root,
                intake_ledger_path=args.intake_ledger,
            )
            if getattr(args, "compact", False) and _should_compact_report(result):
                result = _compact_accept_result(result)
            _print_json(result)
            return 0
        if args.command == "review-budget":
            _print_json(review_budget(review_file=args.review_file))
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
