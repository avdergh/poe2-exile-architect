"""Narrow, fingerprint-bound repairs for confirmed 2026-08-22 Research defects."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from . import mature_learning, research_contracts, research_runtime
from ..runtime.file_lock import interprocess_file_lock


REPAIR_ID = research_contracts.KNOWN_RESEARCH_REPAIR_ID
KNOWN_BAD_RECORDS = research_contracts.KNOWN_BAD_RESEARCH_RECORDS


def inspect_known_repair(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.is_file():
        return {
            "status": "mismatch",
            "repairId": REPAIR_ID,
            "recordCount": 0,
            "mismatchCount": 1,
            "records": [],
            "mismatches": [{"reason": "database_missing"}],
            "noRawMatureBuildMaterial": True,
        }
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if mature_learning.schema_version(con) != mature_learning.SCHEMA_VERSION:
            return {
                "status": "mismatch",
                "repairId": REPAIR_ID,
                "recordCount": 0,
                "mismatchCount": 1,
                "records": [],
                "mismatches": [{"reason": "schema_version_mismatch"}],
                "noRawMatureBuildMaterial": True,
            }
        return _plan(con)
    finally:
        con.close()


def apply_known_repair(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    mature_learning.initialize_store(path)
    with interprocess_file_lock(research_runtime.research_write_lock_path(path)):
        con = mature_learning.connect(path)
        try:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute("SELECT value FROM meta WHERE key = ?", (REPAIR_ID,)).fetchone()
            if existing is not None:
                con.rollback()
                return {"status": "already_applied", "repairId": REPAIR_ID}
            plan = _plan(con)
            if plan["mismatchCount"]:
                con.rollback()
                return {**plan, "status": "mismatch"}
            for item in plan["records"]:
                con.execute(
                    """
                    UPDATE deep_research_records
                    SET visibility = 'quarantined', split = 'quarantine', status = 'quarantined',
                        source_state_scope = 'unknown', last_seen_at = ?
                    WHERE record_id = ? AND superseded_by_id IS NULL
                    """,
                    (item["updatedAt"], item["recordId"]),
                )
            revision = research_runtime.bump_memory_revision(con)
            con.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (REPAIR_ID, str(revision)))
            con.commit()
            return {
                **plan,
                "status": "applied",
                "repairId": REPAIR_ID,
                "memoryRevision": revision,
            }
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()


def _plan(con: sqlite3.Connection) -> dict[str, Any]:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for expected in KNOWN_BAD_RECORDS:
        row = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = ?",
            (expected["recordId"],),
        ).fetchone()
        if row is None:
            mismatches.append({"recordId": expected["recordId"], "reason": "missing"})
            continue
        evidence_sources = sorted(
            str(item[0])
            for item in con.execute(
                "SELECT source_case_ref FROM deep_research_record_evidence "
                "WHERE knowledge_scope = ? AND knowledge_key = ? ORDER BY source_case_ref",
                (str(row["knowledge_scope"]), str(row["knowledge_key"])),
            ).fetchall()
        )
        actual = {
            "knowledgeKey": str(row["knowledge_key"] or ""),
            "recordKind": str(row["record_kind"]),
            "projectionHash": research_runtime.projection_hash(row),
            "sourceCaseRefs": sorted(mature_learning._json_loads(row["source_case_refs"], [])),
            "evidenceSourceCaseRefs": evidence_sources,
        }
        wanted_sources = sorted(expected["sourceCaseRefs"])
        if (
            actual["knowledgeKey"] != expected["knowledgeKey"]
            or actual["recordKind"] != expected["recordKind"]
            or actual["projectionHash"] != expected["projectionHash"]
            or actual["sourceCaseRefs"] != wanted_sources
            or actual["evidenceSourceCaseRefs"] != wanted_sources
        ):
            mismatches.append(
                {
                    "recordId": expected["recordId"],
                    "reason": "fingerprint_mismatch",
                    "actual": actual,
                }
            )
            continue
        records.append(
            {
                "recordId": expected["recordId"],
                "knowledgeKey": expected["knowledgeKey"],
                "sourceCaseRefs": wanted_sources,
                "updatedAt": now,
            }
        )
    return {
        "status": "ready" if not mismatches else "mismatch",
        "repairId": REPAIR_ID,
        "recordCount": len(records),
        "mismatchCount": len(mismatches),
        "records": records,
        "mismatches": mismatches,
        "noRawMatureBuildMaterial": True,
    }
