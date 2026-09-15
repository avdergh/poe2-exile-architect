"""Build a copy-safe Research Memory SQLite seed for release packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.knowledge import (  # noqa: E402
    mature_learning, patch_reviews, research_claim_writes, research_memory,
)


DEFAULT_SOURCE = mature_learning.mature_learning_path()
DEFAULT_OUTPUT = ROOT / "data" / "mature_build_learning" / "release.sqlite"

_OPERATIONAL_TABLES = (
    "source_groups",
    "source_snapshots",
    "mature_build_cases",
    "technique_candidates",
    "candidate_evidence",
    "technique_edges",
    "research_rejected_proposals",
    "research_dedupe_queries",
    "research_query_sessions",
    "research_record_write_receipts",
    "research_revalidation_events",
    "research_decay_events",
)
_SCOPED_TABLES = (
    "research_fragments",
    "research_semantic_edges",
    "research_build_design_observations",
    "research_build_patterns",
    "deep_research_records",
)


def build_release_seed(
    *,
    source: str | Path = DEFAULT_SOURCE,
    output: str | Path = DEFAULT_OUTPUT,
    release_version: str,
) -> dict[str, Any]:
    source_path = Path(source).resolve()
    output_path = Path(output).resolve()
    if source_path == output_path:
        raise ValueError("release seed output must differ from the mutable source database")
    if not source_path.is_file():
        raise FileNotFoundError(f"Research Memory source database is missing: {source_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        # The pre-pruning snapshot and any schema backup contain private source data.
        # Keep both in a disposable directory outside the publication tree, including failures.
        with tempfile.TemporaryDirectory(prefix="poe-research-release-") as scratch:
            snapshot = Path(scratch) / "snapshot.sqlite"
            _backup_database(source_path, snapshot)
            mature_learning.initialize_store(snapshot)
            _prune_to_creator_safe_seed(snapshot, release_version=release_version)
            report = _validate_seed(snapshot)
            shutil.copyfile(snapshot, temp)
        temp.replace(output_path)
    finally:
        temp.unlink(missing_ok=True)
    return {
        "status": "built",
        "output": str(output_path),
        "releaseVersion": release_version,
        "sha256": _sha256(output_path),
        "sizeBytes": output_path.stat().st_size,
        **report,
    }


def _backup_database(source: Path, target: Path) -> None:
    source_uri = f"file:{source.as_posix()}?mode=ro"
    with (
        closing(sqlite3.connect(source_uri, uri=True)) as source_con,
        closing(sqlite3.connect(target)) as target_con,
    ):
        source_con.backup(target_con)


def _prune_to_creator_safe_seed(path: Path, *, release_version: str) -> None:
    with closing(sqlite3.connect(path)) as con:
        con.row_factory = sqlite3.Row
        if mature_learning.schema_version(con) != mature_learning.SCHEMA_VERSION:
            raise ValueError("Research Memory source schema does not match the release runtime")
        # Review holds must be evaluated while their original events and receipts
        # still exist. Deleting operational history first would restore held records.
        held_records = [
            (row["record_id"],)
            for row in con.execute("SELECT * FROM deep_research_records").fetchall()
            if research_memory.pending_hold_for_record(con, row)
        ]
        con.execute("PRAGMA foreign_keys = OFF")
        con.executemany("DELETE FROM deep_research_records WHERE record_id=?", held_records)
        for table in _OPERATIONAL_TABLES:
            con.execute(f"DELETE FROM {table}")
        safe_scope = (
            "visibility = 'creator_visible' AND split = 'train_context' "
            "AND knowledge_scope = 'global_seed' "
            "AND copy_safety_state = 'passed'"
        )
        for table in _SCOPED_TABLES:
            predicate = safe_scope
            if table != "research_build_design_observations":
                predicate += " AND status = 'valid'"
            if table == "deep_research_records":
                predicate += (
                    " AND record_schema_version = 2 AND projection_hash IS NOT NULL "
                    "AND source_state_scope IN ('active_state', 'state_agnostic') "
                    "AND COALESCE(json_extract(typed_payload, '$.availability'), 'standard') = 'standard'"
                )
            con.execute(f"DELETE FROM {table} WHERE NOT ({predicate})")
        con.execute("DELETE FROM research_source_provenance WHERE knowledge_scope <> 'global_seed'")
        con.execute(
            """
            DELETE FROM deep_research_records
            WHERE knowledge_scope = 'global_seed'
              AND NOT EXISTS (
                  SELECT 1
                  FROM deep_research_record_evidence AS evidence
                  JOIN research_source_provenance AS provenance
                    ON provenance.source_case_ref = evidence.source_case_ref
                   AND provenance.knowledge_scope = evidence.knowledge_scope
                  JOIN research_build_families AS family
                    ON family.knowledge_scope = deep_research_records.knowledge_scope
                   AND family.build_family_key = deep_research_records.build_family_key
                  WHERE evidence.knowledge_scope = deep_research_records.knowledge_scope
                    AND evidence.knowledge_key = deep_research_records.knowledge_key
                    AND evidence.record_id = deep_research_records.record_id
                    AND COALESCE(evidence.binding_issue, '') = ''
                    AND evidence.accepted_projection_hash = deep_research_records.projection_hash
                    AND evidence.source_state_scope IN ('active_state', 'state_agnostic')
              )
            """
        )
        con.execute(
            """
            DELETE FROM research_fragment_evidence
            WHERE fragment_id NOT IN (SELECT fragment_id FROM research_fragments)
               OR visibility <> 'creator_visible'
               OR split <> 'train_context'
               OR knowledge_scope <> 'global_seed'
            """
        )
        con.execute(
            """
            DELETE FROM deep_research_record_evidence
            WHERE knowledge_scope <> 'global_seed'
               OR NOT EXISTS (
                    SELECT 1 FROM deep_research_records AS record
                    WHERE record.knowledge_scope = deep_research_record_evidence.knowledge_scope
                      AND record.knowledge_key = deep_research_record_evidence.knowledge_key
                      AND record.record_id = deep_research_record_evidence.record_id
                      AND COALESCE(deep_research_record_evidence.binding_issue, '') = ''
                      AND record.status = 'valid'
                      AND record.superseded_by_id IS NULL
                      AND record.projection_hash =
                          deep_research_record_evidence.accepted_projection_hash
               )
               OR source_state_scope NOT IN ('active_state', 'state_agnostic')
               OR NOT EXISTS (
                    SELECT 1 FROM research_source_provenance AS provenance
                    WHERE provenance.source_case_ref =
                          deep_research_record_evidence.source_case_ref
                      AND provenance.knowledge_scope =
                          deep_research_record_evidence.knowledge_scope
               )
            """
        )
        con.execute(
            """
            DELETE FROM research_build_family_evidence
            WHERE NOT EXISTS (
                SELECT 1
                FROM deep_research_records AS record
                JOIN deep_research_record_evidence AS record_evidence
                  ON record_evidence.knowledge_scope = record.knowledge_scope
                 AND record_evidence.knowledge_key = record.knowledge_key
                 AND record_evidence.record_id = record.record_id
                 AND record_evidence.accepted_projection_hash = record.projection_hash
                 AND COALESCE(record_evidence.binding_issue, '') = ''
                WHERE record.build_family_key = research_build_family_evidence.build_family_key
                  AND record.knowledge_scope = research_build_family_evidence.knowledge_scope
                  AND record_evidence.source_case_ref =
                      research_build_family_evidence.source_case_ref
                  AND record.knowledge_scope = 'global_seed'
                  AND record.status = 'valid'
                  AND record.superseded_by_id IS NULL
            )
            """
        )
        for row in con.execute("SELECT record_id FROM deep_research_records").fetchall():
            research_claim_writes.refresh_record_evidence(
                con, str(row["record_id"]), datetime.now(timezone.utc).isoformat()
            )
        con.execute(
            """
            DELETE FROM research_build_families
            WHERE NOT EXISTS (
                SELECT 1 FROM deep_research_records AS record
                WHERE record.knowledge_scope = research_build_families.knowledge_scope
                  AND record.build_family_key = research_build_families.build_family_key
            )
            """
        )
        con.execute(
            """
            UPDATE research_build_families
            SET evidence_count = (
                SELECT count(*) FROM research_build_family_evidence AS evidence
                WHERE evidence.knowledge_scope = research_build_families.knowledge_scope
                  AND evidence.build_family_key = research_build_families.build_family_key
            )
            """
        )
        research_memory.ResearchMemoryService._reconcile_build_family_secondary_skill_keys(
            con,
            knowledge_scope="global_seed",
        )
        con.execute("DELETE FROM meta WHERE key <> 'schema_version'")
        patch_reviews.validate_release_reviews(con, prune=True)
        now = datetime.now(timezone.utc).isoformat()
        for key, value in (
            ("release_seed_kind", mature_learning.RELEASE_SEED_KIND),
            ("release_seed_version", release_version),
            ("release_seed_created_at", now),
        ):
            con.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                (key, value),
            )
        con.commit()
        con.execute("VACUUM")


def _validate_seed(path: Path) -> dict[str, Any]:
    mature_learning.validate_release_seed(path)
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as con:
        _reject_unsafe_text(con)
        counts = {
            "familyCount": con.execute("SELECT count(*) FROM research_build_families").fetchone()[
                0
            ],
            "recordCount": con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0],
            "patternCount": con.execute("SELECT count(*) FROM research_build_patterns").fetchone()[
                0
            ],
            "edgeCount": con.execute("SELECT count(*) FROM research_semantic_edges").fetchone()[0],
            "observationCount": con.execute(
                "SELECT count(*) FROM research_build_design_observations"
            ).fetchone()[0],
            "scopeCounts": {
                str(scope): int(count)
                for scope, count in con.execute(
                    """
                    SELECT knowledge_scope, count(*)
                    FROM deep_research_records
                    GROUP BY knowledge_scope
                    ORDER BY knowledge_scope
                    """
                )
            },
        }
    return counts


def _reject_unsafe_text(con: sqlite3.Connection) -> None:
    mature_learning.validate_release_seed_text(con)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--release-version", required=True)
    args = parser.parse_args(argv)
    report = build_release_seed(
        source=args.source,
        output=args.output,
        release_version=args.release_version,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
