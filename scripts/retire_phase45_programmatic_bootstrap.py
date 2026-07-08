"""Retire mislabeled Phase 4.5 programmatic bootstrap rows from planner context."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.knowledge import copy_safety, mature_learning  # noqa: E402

DB_PATH = REPO_ROOT / "phase4_real_research_memory.sqlite"
JSON_OUTPUT = REPO_ROOT / "phase45_programmatic_bootstrap_retirement_report.json"
MD_OUTPUT = REPO_ROOT / "phase45_programmatic_bootstrap_retirement_report.md"

LEGACY_MARKERS = (
    "safe:phase45-deep:",
    "case:phase45-deep-",
    "phase45-deep-mcp-batch-v1",
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
    "pobb.in/",
    "poe.ninja/",
)


def retire_programmatic_bootstrap_rows(
    *,
    db_path: str | Path = DB_PATH,
    retirement_status: str = "needs_revalidation",
    dry_run: bool = False,
    json_output: str | Path | None = None,
    md_output: str | Path | None = None,
) -> dict[str, Any]:
    if retirement_status not in {"needs_revalidation", "deprecated"}:
        raise ValueError("retirement_status must be needs_revalidation or deprecated")

    mature_learning.initialize_store(Path(db_path))
    con = mature_learning.connect(Path(db_path))
    try:
        rows = _matching_pattern_rows(con)
        matched_ids = [str(row["pattern_id"]) for row in rows]
        updated = 0
        if not dry_run and matched_ids:
            placeholders = ",".join("?" for _ in matched_ids)
            con.execute(
                f"""
                UPDATE research_build_patterns
                SET status = ?, planner_visible = 0, last_seen_at = ?
                WHERE pattern_id IN ({placeholders})
                """,
                (retirement_status, _now(), *matched_ids),
            )
            con.commit()
            updated = len(matched_ids)
    finally:
        con.close()

    report = {
        "reportId": "phase45-programmatic-bootstrap-retirement-v1",
        "status": "dry_run" if dry_run else "accepted",
        "safeArtifactOnly": True,
        "retirementStatus": retirement_status,
        "matchedPatternCount": len(matched_ids),
        "updatedPatternCount": updated,
        "retiredPatternIds": matched_ids,
        "caveats": [
            "Rows matched legacy programmatic bootstrap markers.",
            "Rows are retained for audit but removed from planner-visible context.",
            "This does not retire external Deep Researcher case observations.",
        ],
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_report(report)
    if json_output is not None:
        Path(json_output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if md_output is not None:
        Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _matching_pattern_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = con.execute(
        """
        SELECT pattern_id, title, summary, planner_hint, source_case_refs, safe_evidence_refs
        FROM research_build_patterns
        WHERE planner_visible = 1
          AND status = 'valid'
        ORDER BY pattern_id
        """
    ).fetchall()
    matched: list[sqlite3.Row] = []
    for row in rows:
        haystack = " ".join(
            [
                str(row["title"] or ""),
                str(row["source_case_refs"] or ""),
                str(row["safe_evidence_refs"] or ""),
            ]
        )
        if any(marker in haystack for marker in LEGACY_MARKERS) and _has_programmatic_shape(row):
            matched.append(row)
    return matched


def _has_programmatic_shape(row: sqlite3.Row) -> bool:
    title = str(row["title"] or "")
    summary = str(row["summary"] or "")
    planner_hint = str(row["planner_hint"] or "")
    return (
        title.startswith("Case observation case:phase45-")
        and "One mature sample contains resolver-backed components with roles:" in summary
        and "Treat as a safe case observation, not a reusable trend." in summary
        and "Use this case observation only as a candidate component set for Phase 5 search"
        in planner_hint
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _assert_safe_report(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe retirement report markers detected: {', '.join(leaks)}")
    if copy_safety.find_forbidden_paths(report):
        raise ValueError("unsafe retirement report contains forbidden raw fields")
    flags: set[str] = set()
    for text in _human_text(report):
        flags.update(copy_safety.copyability_flags(text))
    if flags:
        raise ValueError("unsafe retirement report failed copy-safety scan")


def _human_text(value: Any, *, key: str = "") -> list[str]:
    scan_keys = {"caveats"}
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


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4.5 Programmatic Bootstrap Retirement",
        "",
        f"- Status: `{report['status']}`",
        f"- Matched patterns: `{report['matchedPatternCount']}`",
        f"- Updated patterns: `{report['updatedPatternCount']}`",
        f"- Retirement status: `{report['retirementStatus']}`",
        "",
        "## Retired Pattern IDs",
        "",
    ]
    lines.extend(f"- `{pattern_id}`" for pattern_id in report["retiredPatternIds"])
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.append("")
    text = "\n".join(lines)
    if re.search(r"(?:https?://|www\.|pobb\.in|poe\.ninja|pastebin\.com)", text, re.I):
        raise ValueError("unsafe URL in retirement markdown")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=str(DB_PATH))
    parser.add_argument("--retirement-status", default="needs_revalidation")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    report = retire_programmatic_bootstrap_rows(
        db_path=args.db_path,
        retirement_status=args.retirement_status,
        dry_run=args.dry_run,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
