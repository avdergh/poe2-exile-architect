"""Validate the frozen 0.5.0 Research release-seed content expectation."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.knowledge import mature_learning  # noqa: E402


EXPECTED_GLOBAL_LANES = {
    "source-hash:16d58adff7c76899": 6,
    "source-hash:953d020627f0cc5c": 10,
    "source-hash:c5c603213cd2f5bf": 2,
}


def validate_release_content(seed: str | Path) -> dict[str, object]:
    path = Path(seed).resolve()
    mature_learning.validate_release_seed(path)
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        lane_rows = con.execute(
            """
            SELECT evidence.source_case_ref, count(DISTINCT record.record_id) AS record_count
            FROM deep_research_record_evidence AS evidence
            JOIN deep_research_records AS record
              ON record.knowledge_scope = evidence.knowledge_scope
             AND record.knowledge_key = evidence.knowledge_key
            JOIN research_source_provenance AS provenance
              ON provenance.source_case_ref = evidence.source_case_ref
             AND provenance.knowledge_scope = evidence.knowledge_scope
            JOIN research_build_families AS family
              ON family.knowledge_scope = record.knowledge_scope
             AND family.build_family_key = record.build_family_key
            WHERE record.knowledge_scope = 'global_seed'
              AND record.visibility = 'creator_visible'
              AND record.split = 'train_context'
              AND record.copy_safety_state = 'passed'
              AND record.status = 'valid'
              AND record.superseded_by_id IS NULL
              AND record.record_schema_version = 2
              AND record.source_state_scope IN ('active_state', 'state_agnostic')
              AND evidence.source_state_scope IN ('active_state', 'state_agnostic')
              AND evidence.accepted_projection_hash = record.projection_hash
              AND COALESCE(json_extract(record.typed_payload, '$.availability'), 'standard')
                  = 'standard'
            GROUP BY evidence.source_case_ref
            ORDER BY evidence.source_case_ref
            """
        ).fetchall()
        actual_lanes = {
            str(row["source_case_ref"]): int(row["record_count"] or 0) for row in lane_rows
        }
        family_count = int(
            con.execute(
                "SELECT count(*) FROM research_build_families WHERE knowledge_scope = 'global_seed'"
            ).fetchone()[0]
        )
        record_count = int(
            con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0]
        )
        non_global_count = int(
            con.execute(
                "SELECT count(*) FROM deep_research_records "
                "WHERE knowledge_scope <> 'global_seed'"
            ).fetchone()[0]
        )
    finally:
        con.close()
    errors: list[str] = []
    if actual_lanes != EXPECTED_GLOBAL_LANES:
        errors.append("global_lane_counts")
    if family_count != 3:
        errors.append("global_family_count")
    if record_count != 18:
        errors.append("eligible_record_union")
    if non_global_count:
        errors.append("non_global_records")
    return {
        "status": "ok" if not errors else "error",
        "errorCode": None if not errors else "research_release_expectation_mismatch",
        "seed": str(path),
        "expectedGlobalLanes": EXPECTED_GLOBAL_LANES,
        "actualGlobalLanes": actual_lanes,
        "globalFamilyCount": family_count,
        "recordCount": record_count,
        "nonGlobalRecordCount": non_global_count,
        "mismatches": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        default="data/mature_build_learning/release.sqlite",
    )
    args = parser.parse_args()
    report = validate_release_content(args.seed)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
