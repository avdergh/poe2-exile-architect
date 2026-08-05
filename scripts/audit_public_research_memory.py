"""Audit the copy-safe Research subset that may become a release seed.

This command never exports row bodies. It reports counts, version coverage, and safe record IDs for
blocked rows so maintainers can review a candidate database before building a release asset.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server import paths  # noqa: E402
from server.knowledge import copy_safety, mature_learning  # noqa: E402

RELEASE_WHERE = """
visibility = 'creator_visible'
AND split = 'train_context'
AND knowledge_scope IN ('global_seed', 'local_user')
AND status IN ('valid', 'needs_revalidation')
AND copy_safety_state = 'passed'
"""


def _decode_structured_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Decode JSON columns so long structured lists are not mistaken for copied prose."""
    decoded: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, str) and value.lstrip().startswith(("[", "{")):
            try:
                decoded[key] = json.loads(value)
                continue
            except json.JSONDecodeError:
                pass
        decoded[key] = value
    return decoded


def _row_blockers(row: dict[str, Any]) -> list[str]:
    decoded = _decode_structured_fields(row)
    blockers: set[str] = set()
    if copy_safety.find_forbidden_paths(decoded):
        blockers.add("forbidden_field")
    blockers.update(copy_safety.durable_knowledge_flags(decoded))
    if copy_safety.contains_raw_url(decoded):
        blockers.add("raw_url")
    return sorted(blockers)


def _read_rows(con: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in con.execute(f"SELECT * FROM {table} WHERE {RELEASE_WHERE}")]


def audit_database(db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        return {"status": "blocked", "errorCode": "research_database_not_found"}
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        schema = mature_learning.schema_version(con)
        if schema != mature_learning.SCHEMA_VERSION:
            return {
                "status": "blocked",
                "errorCode": "research_schema_version_mismatch",
                "schemaVersion": schema,
                "expectedSchemaVersion": mature_learning.SCHEMA_VERSION,
            }
        records = _read_rows(con, "deep_research_records")
        patterns = _read_rows(con, "research_build_patterns")
        excluded = {
            "quarantinedRecords": con.execute(
                "SELECT count(*) FROM deep_research_records WHERE visibility = 'quarantined'"
            ).fetchone()[0],
            "queryReceipts": con.execute("SELECT count(*) FROM research_dedupe_queries").fetchone()[
                0
            ],
            "rejectedProposals": con.execute(
                "SELECT count(*) FROM research_rejected_proposals"
            ).fetchone()[0],
        }
    finally:
        con.close()

    blocked_rows: list[dict[str, Any]] = []
    version_counts: Counter[tuple[str, str, str]] = Counter()
    for kind, rows, id_column in (
        ("deep_record", records, "record_id"),
        ("build_pattern", patterns, "pattern_id"),
    ):
        for row in rows:
            flags = _row_blockers(row)
            if flags:
                blocked_rows.append({"kind": kind, "id": row[id_column], "flags": flags})
            version_counts[
                (
                    str(row.get("game_patch") or "unknown"),
                    str(row.get("passive_tree_version") or "unknown"),
                    str(row.get("pob_version_or_commit") or "unknown"),
                )
            ] += 1

    blockers: list[str] = []
    if not records:
        blockers.append("no_public_deep_research_records")
    if blocked_rows:
        blockers.append("copy_safety_audit_failed")
    versions = [
        {
            "gamePatch": key[0],
            "passiveTreeVersion": key[1],
            "pobVersionOrCommit": key[2],
            "knowledgeUnitCount": count,
        }
        for key, count in sorted(version_counts.items())
    ]
    return {
        "status": "publishable" if not blockers else "blocked",
        "snapshotFormatVersion": 1,
        "schemaVersion": mature_learning.SCHEMA_VERSION,
        "counts": {
            "deepResearchRecords": len(records),
            "buildPatterns": len(patterns),
            "globalSeedRecords": sum(
                1 for row in records if row.get("knowledge_scope") == "global_seed"
            ),
            "localUserRecords": sum(
                1 for row in records if row.get("knowledge_scope") == "local_user"
            ),
        },
        "excludedLocalState": excluded,
        "versionCoverage": versions,
        "blockers": blockers,
        "blockedRows": blocked_rows[:100],
        "blockedRowCount": len(blocked_rows),
        "noRawKnowledgeReturned": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=paths.mature_learning_path())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = audit_database(args.db)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report["status"] == "publishable" else 2


if __name__ == "__main__":
    sys.exit(main())
