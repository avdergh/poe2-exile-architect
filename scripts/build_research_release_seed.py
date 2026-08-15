"""Build a copy-safe Research Memory SQLite seed for release packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.knowledge import mature_learning  # noqa: E402


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
_FORBIDDEN_TEXT_MARKERS = (
    "<pathofbuilding",
    "rawxml",
    "rawimportcode",
    "pobb.in/",
    "pastebin.com/",
    "http://",
    "https://",
    "c:\\users\\",
    "/home/",
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
        _backup_database(source_path, temp)
        _prune_to_creator_safe_seed(temp, release_version=release_version)
        report = _validate_seed(temp)
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
        if mature_learning.schema_version(con) != mature_learning.SCHEMA_VERSION:
            raise ValueError("Research Memory source schema does not match the release runtime")
        con.execute("PRAGMA foreign_keys = OFF")
        for table in _OPERATIONAL_TABLES:
            con.execute(f"DELETE FROM {table}")
        safe_scope = (
            "visibility = 'creator_visible' AND split = 'train_context' "
            "AND knowledge_scope IN ('global_seed', 'local_user') "
            "AND copy_safety_state = 'passed'"
        )
        for table in _SCOPED_TABLES:
            predicate = safe_scope
            if table != "research_build_design_observations":
                predicate += " AND status = 'valid'"
            con.execute(f"DELETE FROM {table} WHERE NOT ({predicate})")
        con.execute(
            """
            DELETE FROM research_fragment_evidence
            WHERE fragment_id NOT IN (SELECT fragment_id FROM research_fragments)
               OR visibility <> 'creator_visible'
               OR split <> 'train_context'
               OR knowledge_scope NOT IN ('global_seed', 'local_user')
            """
        )
        con.execute(
            """
            DELETE FROM deep_research_record_evidence
            WHERE knowledge_key NOT IN (
                SELECT knowledge_key FROM deep_research_records WHERE knowledge_key IS NOT NULL
            )
            """
        )
        con.execute(
            """
            DELETE FROM research_build_family_evidence
            WHERE build_family_key NOT IN (
                SELECT DISTINCT build_family_key
                FROM deep_research_records
                WHERE build_family_key IS NOT NULL
            )
            """
        )
        con.execute(
            """
            DELETE FROM research_build_families
            WHERE build_family_key NOT IN (
                SELECT DISTINCT build_family_key
                FROM deep_research_records
                WHERE build_family_key IS NOT NULL
            )
            """
        )
        con.execute(
            "DELETE FROM meta WHERE key NOT IN ('schema_version', 'phase4_build_family_backfill_version')"
        )
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
    if counts["familyCount"] < 1 or counts["recordCount"] < 1:
        raise ValueError("Research release seed contains no usable Family knowledge")
    return counts


def _reject_unsafe_text(con: sqlite3.Connection) -> None:
    tables = [
        str(row[0])
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        if not str(row[0]).startswith("research_fragment_fts")
    ]
    for table in tables:
        text_columns = [
            str(row[1])
            for row in con.execute(f"PRAGMA table_info({table})")
            if str(row[2] or "").upper() in {"TEXT", ""}
        ]
        if not text_columns:
            continue
        query = "SELECT " + ", ".join(f'"{column}"' for column in text_columns) + f" FROM {table}"
        for row in con.execute(query):
            joined = "\n".join(str(value) for value in row if value is not None).casefold()
            marker = next((item for item in _FORBIDDEN_TEXT_MARKERS if item in joined), None)
            if marker:
                raise ValueError(f"Research release seed contains forbidden text marker in {table}")


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
