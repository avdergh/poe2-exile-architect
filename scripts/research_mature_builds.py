"""Product entrypoint for mature PoE2 build research queues.

This script does not call an LLM provider. It prepares safe queue metadata,
leases one mature build case at a time to an external Researcher agent, renders
the transient raw-rich prompt only for the leased worker, and accepts safe
proposals through the existing typed gates.
"""

from __future__ import annotations

import argparse
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
from server.knowledge import copy_safety, research_packet, research_prompt  # noqa: E402

DEFAULT_OUTPUT_DIR = REPO_ROOT / ".poe-bd-research"
QUEUE_DB_FILENAME = "poe_bd_research_queue.sqlite"
DEFAULT_TEMP_DIRNAME = "poe-bd-creator-research-packets"
DEFAULT_MEMORY_DB_PATH = REPO_ROOT / "phase4_real_research_memory.sqlite"

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
    worker_count: int = 5,
    level_min: int = 90,
    level_max: int = 100,
    ascendancies: list[str] | None = None,
    source_files: list[str | Path] | None = None,
    source_batch_files: list[str | Path] | None = None,
    sample_start_index: int = 1,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    temp_root: str | Path | None = None,
    ttl_seconds: int = 3600,
    current_patch: str = "unknown",
    passive_tree_version: str = "unknown",
    browser_driver: Any | None = None,
    resume: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create or resume a safe mature-build research queue."""
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    db_path = _queue_db_path(output_root, queue_db_path)
    effective_temp_root = _effective_temp_root(temp_root, output_root=output_root)
    effective_temp_root.mkdir(parents=True, exist_ok=True)
    research_packet.cleanup_expired_packets(temp_root=effective_temp_root)

    local_sources = legacy_batch._local_sources(source_files or [], source_batch_files or [])
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
        )
    )
    _normalize_sample_ids(cases, sample_start_index=sample_start_index)

    if dry_run:
        report = _queue_report(
            status="dry_run",
            db_path=db_path,
            requested_worker_count=worker_count,
            cases=[_safe_case_row_from_case(case) for case in cases],
            dry_run=True,
        )
        _assert_safe_payload(report)
        return report

    if db_path.exists() and not resume:
        db_path.unlink()
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
            "requestedWorkerCount": str(max(1, int(worker_count or 1))),
            "workerCountSemantics": "concurrent_researcher_agent_lanes",
            "currentPatch": legacy_batch._safe_text(current_patch),
            "passiveTreeVersion": legacy_batch._safe_text(passive_tree_version),
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
                current_patch=current_patch,
                passive_tree_version=passive_tree_version,
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
        status_override="queued",
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
    lease_owner: str = "external_researcher_worker",
) -> dict[str, Any]:
    """Atomically lease one queued case to a Researcher worker."""
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    _init_db(db_path)
    now = _now()
    expires = now + timedelta(seconds=max(1, int(lease_seconds or 1)))
    lease_token = secrets.token_urlsafe(32)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
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
    result = _claim_payload(dict(claimed), lease_token=lease_token)
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
    """Render the raw-rich prompt for the worker holding a valid lease."""
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    row = _case_for_valid_lease(db_path, lease_token)
    root = _effective_temp_root(temp_root, output_root=Path(output_dir))
    packet = _load_packet_by_safe_hash(root, str(row["packet_safe_hash"]))
    return research_prompt.render_researcher_prompt(
        packet,
        current_patch=current_patch,
        passive_tree_version=passive_tree_version,
        user_language=user_language,
    )


def render_worker_brief(
    *,
    lease_token: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Render a safe, inline first message for a Researcher worker."""
    db_path = _queue_db_path(Path(output_dir), queue_db_path)
    row = _case_for_valid_lease(db_path, lease_token)
    sample_id = str(row["sample_id"])
    review_file = _suggested_review_file(output_dir=Path(output_dir), sample_id=sample_id)
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


def accept_case(
    *,
    lease_token: str,
    review_file: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    queue_db_path: str | Path | None = None,
    memory_db_path: str | Path = DEFAULT_MEMORY_DB_PATH,
    acceptance_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Accept a safe Researcher proposal and mark the leased case complete."""
    output_root = Path(output_dir)
    db_path = _queue_db_path(output_root, queue_db_path)
    row = _case_for_valid_lease(db_path, lease_token)
    sample_id = str(row["sample_id"])
    _begin_accepting(db_path, row=row, lease_token=lease_token)
    accept_dir = (
        Path(acceptance_output_dir) if acceptance_output_dir else output_root / "acceptance"
    )
    accept_dir.mkdir(parents=True, exist_ok=True)
    safe_review_file = _resolve_review_file(Path(review_file), output_root=output_root)
    slug = _slug(sample_id)
    try:
        report = acceptance.accept_deep_review_candidates(
            db_path=Path(memory_db_path),
            json_output=accept_dir / f"{slug}-acceptance.json",
            md_output=accept_dir / f"{slug}-acceptance.md",
            review_file=safe_review_file,
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
        "deferredCandidateCount": int(report.get("deferredCandidateCount") or 0),
        "patternWrite": report.get("patternWrite") or {},
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
) -> dict[str, Any]:
    """Retry acceptance for a previously rejected safe review artifact."""
    output_root = Path(output_dir)
    db_path = _queue_db_path(output_root, queue_db_path)
    row = _case_for_rejected_sample(db_path, sample_id)
    _begin_retry_accepting(db_path, row=row)
    accept_dir = (
        Path(acceptance_output_dir) if acceptance_output_dir else output_root / "acceptance"
    )
    accept_dir.mkdir(parents=True, exist_ok=True)
    safe_review_file = _resolve_review_file(Path(review_file), output_root=output_root)
    slug = _slug(str(row["sample_id"]))
    try:
        report = acceptance.accept_deep_review_candidates(
            db_path=Path(memory_db_path),
            json_output=accept_dir / f"{slug}-acceptance.json",
            md_output=accept_dir / f"{slug}-acceptance.md",
            review_file=safe_review_file,
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
        "deferredCandidateCount": int(report.get("deferredCandidateCount") or 0),
        "patternWrite": report.get("patternWrite") or {},
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
    return _queue_report(
        status=status_override or "ok",
        db_path=db_path,
        requested_worker_count=int(metadata.get("requestedWorkerCount") or 1),
        cases=rows,
        inserted_count=inserted_count,
        duplicate_count=duplicate_count,
        dry_run=False,
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
                deferred_candidate_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_cases_status_lease
                ON cases(status, lease_expires_at, id);
            """
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
                "safeError": str(row["safe_error"]),
                "packetId": str(row["packet_id"]),
                "packetSafeHash": str(row["packet_safe_hash"]),
                "leaseExpiresAt": str(row["lease_expires_at"] or ""),
                "acceptedAt": str(row["accepted_at"] or ""),
                "acceptanceStatus": str(row["acceptance_status"] or ""),
                "acceptedPatternCount": int(row["accepted_pattern_count"] or 0),
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
            "gamePatch": current_patch,
            "passiveTreeVersion": passive_tree_version,
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
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for case in cases:
        counts[str(case.get("status") or "")] = counts.get(str(case.get("status") or ""), 0) + 1
    samples = [_safe_sample_for_report(case) for case in cases]
    report = {
        "reportId": "poe-bd-research-queue-v1",
        "status": status,
        "safeArtifactOnly": True,
        "queueKind": "poe_bd_research_external_agent_queue",
        "queueDb": db_path.name,
        "sampleCount": len(samples),
        "queuedCount": counts.get("queued", 0),
        "claimedCount": counts.get("claimed", 0),
        "acceptedCount": counts.get("accepted", 0),
        "rejectedCount": counts.get("acceptance_rejected", 0),
        "importFailedCount": counts.get("import_failed", 0),
        "requestedWorkerCount": max(1, int(requested_worker_count or 1)),
        "workerCountSemantics": "concurrent_researcher_agent_lanes",
        "workerReusePolicy": "fresh_raw_rich_prompt_per_case_no_transcript_reuse",
        "insertedCount": inserted_count,
        "duplicateCount": duplicate_count,
        "samples": samples,
        "dryRun": bool(dry_run),
        "noRawMatureBuildMaterial": True,
        "caveats": [
            "The queue stores only safe metadata, leases, and packet safe hashes.",
            "Raw mature build material exists only in transient OS temp packets.",
            "Use the prompt subcommand from the leased Researcher worker to read one raw-rich prompt.",
            "This script does not call any OpenAI, Claude, Gemini, or other model provider API.",
        ],
    }
    return report


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
        "safeError": legacy_batch._safe_text(case.get("safeError")),
        "leaseExpiresAt": legacy_batch._safe_text(case.get("leaseExpiresAt")),
        "acceptedAt": legacy_batch._safe_text(case.get("acceptedAt")),
        "acceptanceStatus": legacy_batch._safe_text(case.get("acceptanceStatus")),
        "acceptedPatternCount": int(case.get("acceptedPatternCount") or 0),
        "deferredCandidateCount": int(case.get("deferredCandidateCount") or 0),
    }


def _claim_payload(row: dict[str, Any], *, lease_token: str) -> dict[str, Any]:
    return {
        "status": "claimed",
        "queueKind": "poe_bd_research_external_agent_queue",
        "sampleId": str(row["sample_id"]),
        "sourceType": str(row["source_type"]),
        "sourceHashRef": str(row["source_hash_ref"]),
        "packetId": str(row["packet_id"]),
        "packetSafeHash": str(row["packet_safe_hash"]),
        "className": str(row["class_name"]),
        "ascendancy": str(row["ascendancy"]),
        "level": int(row["level"] or 0),
        "mainSkill": str(row["main_skill"]),
        "leaseToken": lease_token,
        "leaseExpiresAt": str(row["lease_expires_at"]),
        "noRawMatureBuildMaterial": True,
    }


def _suggested_review_file(*, output_dir: Path, sample_id: str) -> str:
    return (Path("reviews") / f"{_slug(sample_id)}-safe-review.json").as_posix()


def _resolve_review_file(review_file: Path, *, output_root: Path) -> Path:
    if review_file.is_absolute():
        return review_file
    cwd_path = Path.cwd() / review_file
    output_path = output_root / review_file
    if cwd_path.exists():
        return cwd_path
    return output_path


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
    return f"""你是 PoE2 mature build Researcher worker。你只负责当前 leased case，不负责改代码。

这是完整的 safe worker brief；不要只依赖另一个文件路径来理解任务。真正的一案标准 Researcher prompt 会由下面的 prompt 子命令输出，且只允许你这个 worker 临时读取。

## Runtime Boundary
- 这是产品运行态 workflow，不是开发/调试任务。
- 不要修改源码、测试、文档、schema、安装脚本或 plugin manifest。
- 不要使用 apply_patch，不要现场修脚本。
- 你不是独自在工作流里；不要 revert 或改动其他 worker 的 artifact。
- 最终回复只能包含 safe review artifact 路径、ready-for-accept 状态和 safe error/status。

## Case
- sampleId: {sample_id}
- leaseToken: {lease_token}
- sourceType: {source_type}
- sourceRef: {source_hash_ref}
- class/ascendancy/level: {class_name} / {ascendancy} / {level}
- programmatic mainSkill candidate: {main_skill or "unknown"}，这是非权威快照线索，不是结论。
- packetSafeHash: {packet_safe_hash}
- safeReviewFile: {review_file}（相对 --output-dir）

## First Action
从仓库根目录运行 prompt 子命令读取本案完整标准 Researcher prompt。选择当前系统可用的调用方式；不要要求用户在聊天框执行命令。

Windows 示例：
```powershell
.\\.tools\\uv\\uv.exe run python scripts\\research_mature_builds.py prompt --output-dir .poe-bd-research --lease-token {lease_token}
```

POSIX 示例：
```bash
./.tools/uv/uv run python scripts/research_mature_builds.py prompt --output-dir .poe-bd-research --lease-token {lease_token}
```

prompt 输出是本案唯一 raw-rich transient material。不要把它复制到最终回复，不要保存到 repo，不要写入 safe review artifact。

## Tool Availability
- 如果当前 worker 会话直接暴露 `query_research_memory`、`graph_tool_query` / `resolve_graph_component`、`propose_research_fragments`、`propose_build_patterns`、`propose_semantic_edges`，就按 prompt SOP 使用它们。
- 如果这些 MCP tools 没有暴露，不要搜索隐藏工具、不要临时构造服务、不要读源码找替代 API。请用 prompt 进行深度分析，然后写 safe review artifact；orchestrator 会用 accept gate 做 resolver、schema、copy-safety 和入库。

## Safe Review Artifact Contract
把候选写到 `safeReviewFile`；它是相对 `--output-dir` 的路径。JSON 顶层形状：
```json
{{
  "reportId": "poe_bd_research_review",
  "safeArtifactOnly": true,
  "candidateReviews": [
    {{
      "sampleId": "{sample_id}",
      "caseRef": "{source_hash_ref}",
      "safeEvidenceRef": "evidence:{packet_safe_hash[:16]}",
      "patternType": "build_archetype",
      "title": "中文安全标题",
      "summary": "中文安全摘要，只写机制原则，不写可复刻配方",
      "axes": ["character_shell", "primary_skill_package"],
      "components": [
        {{
          "candidateName": "组件名",
          "componentKey": "resolver-backed-stable-key",
          "role": "primary_damage",
          "resolverQuery": "用于解析该组件的查询词"
        }}
      ],
      "plannerHint": "Phase 5 可尝试或避免的安全提示",
      "verificationGate": "需要 planner/Judge/人工验证的条件",
      "verificationTasks": ["安全复验任务"],
      "gamePatch": "unknown",
      "passiveTreeVersion": "unknown",
      "pobVersionOrCommit": "unknown"
    }}
  ]
}}
```

`patternType` 只能使用 snake_case 枚举：`build_archetype`、`cooccurrence`、`transition_gate`、`failure_pattern`、`planner_hint`。不要使用 `BuildArchetypePattern` / `CooccurrencePattern` 这类 CamelCase，也不要把 `mechanic_engine`、`itemization` 这类设计轴填到 `patternType`。

`axes` 只能使用这些设计轴：`identity`、`character_shell`、`primary_skill_package`、`secondary_skill_package`、`passive_tree_shape`、`itemization`、`scaling_axis`、`resource_engine`、`defense_layers`、`mechanic_engine`、`rotation_playstyle`、`transition_gates`、`failure_modes`、`variant_relations`、`modelability_caveats`。

只输出你有把握的 candidate。endpoint 缺失、ambiguous 或只是抽象层标签时，写 verification task 或干脆不写该 candidate；不要猜 stable key。单样本只能是 case observation，不要写“通常/常见/common/usually”。
"""


def _normalize_sample_ids(cases: list[dict[str, Any]], *, sample_start_index: int) -> None:
    index = max(1, int(sample_start_index))
    for case in cases:
        case["sampleId"] = f"case:poe-bd-research-{index:03d}"
        index += 1


def _queue_db_path(output_root: Path, queue_db_path: str | Path | None) -> Path:
    return Path(queue_db_path) if queue_db_path is not None else output_root / QUEUE_DB_FILENAME


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
    _add_queue_location_args(queue_parser)
    queue_parser.add_argument("--limit", type=int, default=50)
    queue_parser.add_argument("--worker-count", type=int, default=5)
    queue_parser.add_argument("--league", default="current")
    queue_parser.add_argument("--level-min", type=int, default=90)
    queue_parser.add_argument("--level-max", type=int, default=100)
    queue_parser.add_argument("--ascendancy", action="append", default=[])
    queue_parser.add_argument("--source-file", action="append", default=[])
    queue_parser.add_argument("--source-batch-file", action="append", default=[])
    queue_parser.add_argument("--sample-start-index", type=int, default=1)
    queue_parser.add_argument("--resume", action="store_true")
    queue_parser.add_argument("--dry-run", action="store_true")
    queue_parser.add_argument("--ttl-seconds", type=int, default=3600)
    queue_parser.add_argument("--current-patch", default="unknown")
    queue_parser.add_argument("--passive-tree-version", default="unknown")

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

    worker_brief_parser = subparsers.add_parser("worker-brief")
    _add_queue_location_args(worker_brief_parser)
    worker_brief_parser.add_argument("--lease-token", required=True)

    accept_parser = subparsers.add_parser("accept")
    _add_queue_location_args(accept_parser)
    accept_parser.add_argument("--lease-token", required=True)
    accept_parser.add_argument("--review-file", required=True)
    accept_parser.add_argument("--memory-db-path", default=str(DEFAULT_MEMORY_DB_PATH))
    accept_parser.add_argument("--acceptance-output-dir")

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
            _print_json(
                queue_cases(
                    league_url=args.league,
                    limit=args.limit,
                    worker_count=args.worker_count,
                    level_min=args.level_min,
                    level_max=args.level_max,
                    ascendancies=list(args.ascendancy or []),
                    source_files=[Path(item) for item in args.source_file],
                    source_batch_files=[Path(item) for item in args.source_batch_file],
                    sample_start_index=args.sample_start_index,
                    output_dir=args.output_dir,
                    queue_db_path=args.queue_db_path,
                    temp_root=args.temp_root,
                    ttl_seconds=args.ttl_seconds,
                    current_patch=args.current_patch,
                    passive_tree_version=args.passive_tree_version,
                    resume=args.resume,
                    dry_run=args.dry_run,
                )
            )
            return 0
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
        if args.command == "worker-brief":
            _print_json(
                render_worker_brief(
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


def _add_queue_location_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--queue-db-path")
    parser.add_argument("--temp-root")


if __name__ == "__main__":
    raise SystemExit(main())
