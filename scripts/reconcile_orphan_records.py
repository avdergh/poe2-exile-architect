"""Reconcile orphan deep records (records whose family mount no longer exists).

Orphan sources: historical leftovers (family rows deleted without relocating records) and
backfill boundaries (records whose identity could not be re-derived kept their old family
mount after the family was consolidated).

Modes:
  --dry-run   analyse every orphan: derive identity by research group, resolve the target
              family via the same canonical-set logic as accept, and print a disposition
              list for human review (join / expand / new / unclassifiable).
  --apply     back up the DB, then execute only the reviewed dispositions:
              join  -> move records onto the matched family;
              new   -> create the inferred family and move records onto it;
              unclassifiable -> detach (build_family_key=NULL, knowledge_key=NULL,
              status=needs_revalidation) so the record is visible as pending review
              instead of silently unreachable.
              expand is never auto-applied: it needs a merge of an existing family and is
              reported for a dedicated merge run.

Nothing here edits record content or knowledge bodies; it only fixes mount points.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.knowledge import mature_learning, research_identity  # noqa: E402
from server.knowledge.research_memory import ResearchMemoryService  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(value, default):
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def orphan_rows(con):
    return con.execute(
        """
        SELECT * FROM deep_research_records r
        WHERE r.build_family_key IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM research_build_families f
              WHERE f.build_family_key = r.build_family_key
          )
        ORDER BY r.research_group_id, r.record_id
        """
    ).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(mature_learning.mature_learning_path()),
        help="mature learning DB path (default: per-user store)",
    )
    parser.add_argument("--backup-dir", default=None, help="pre-apply backup directory")
    parser.add_argument(
        "--skip-group",
        action="append",
        default=[],
        help="research group id to leave untouched (repeatable; reported, not applied)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(json.dumps({"status": "error", "errorCode": "db_missing"}))
        return 2
    con = mature_learning.connect(db_path)
    try:
        rows = orphan_rows(con)
        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(str(row["research_group_id"]), []).append(row)

        dispositions: list[dict] = []
        for group_id, group_rows in sorted(groups.items()):
            identity = research_identity.infer_build_family(group_rows)
            entry = {
                "group_id": group_id,
                "record_count": len(group_rows),
                "record_ids": [str(r["record_id"]) for r in group_rows],
                "titles": [str(r["title"])[:60] for r in group_rows][:3],
                "ascendancy": str(group_rows[0]["ascendancy_key"] or ""),
            }
            if identity is None:
                entry["disposition"] = "unclassifiable"
                dispositions.append(entry)
                continue
            entry["identity"] = {
                "ascendancy_key": identity.ascendancy_key,
                "primary_skill_keys": list(identity.primary_skill_keys),
            }
            # resolve target like accept does
            service = ResearchMemoryService(db_path=db_path, initialize_store=False)
            target, relation, src_key = service._resolve_family_target(con, family=identity)
            entry["relation"] = relation
            entry["disposition"] = "expand" if relation == "expand" else relation
            entry["target_family_key"] = target.key if relation != "new" else None
            entry["target_primary_keys"] = list(target.primary_skill_keys)
            dispositions.append(entry)

        report = {
            "status": "ok",
            "mode": "dry-run" if args.dry_run else "apply",
            "orphanRecordCount": len(rows),
            "orphanGroupCount": len(groups),
            "byDisposition": {
                d: sum(1 for e in dispositions if e["disposition"] == d)
                for d in ("join", "expand", "new", "unclassifiable")
            },
            "dispositions": dispositions,
        }
        if args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        # apply: back up, then execute reviewed dispositions
        if args.backup_dir:
            backup_dir = Path(args.backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_dir / f"mature_build_learning.pre-orphan-{stamp}.sqlite"
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = db_path.with_name(f"{db_path.stem}.pre-orphan-{stamp}{db_path.suffix}")
        shutil.copy2(db_path, backup_path)
        report["backup"] = str(backup_path)
        now = _now()
        service = ResearchMemoryService(db_path=db_path, initialize_store=False)
        applied = {"join": 0, "new": 0, "unclassifiable": 0, "expand": 0}
        skipped = 0
        for entry in dispositions:
            group_id = entry["group_id"]
            if group_id in args.skip_group:
                entry["skipped_reason"] = "human review required (identity suspicious)"
                skipped += 1
                continue
            group_rows = [r for r in orphan_rows(con) if str(r["research_group_id"]) == group_id]
            if entry["disposition"] == "unclassifiable":
                for row in group_rows:
                    con.execute(
                        """
                        UPDATE deep_research_records
                        SET build_family_key = NULL, knowledge_key = NULL,
                            evidence_count = 0,
                            status = CASE WHEN status = 'valid'
                                          THEN 'needs_revalidation' ELSE status END,
                            last_seen_at = ?
                        WHERE record_id = ?
                        """,
                        (now, str(row["record_id"])),
                    )
                applied["unclassifiable"] += 1
                continue
            if entry["relation"] == "join" and entry.get("target_family_key"):
                for row in group_rows:
                    con.execute(
                        "UPDATE deep_research_records SET build_family_key = ? WHERE record_id = ?",
                        (entry["target_family_key"], str(row["record_id"])),
                    )
                applied["join"] += 1
                continue
            if entry["relation"] == "new":
                identity = research_identity.BuildFamilyIdentity(
                    ascendancy_key=entry["identity"]["ascendancy_key"],
                    primary_skill_keys=tuple(entry["identity"]["primary_skill_keys"]),
                )
                service._upsert_build_family(
                    con,
                    family=identity,
                    source_case_refs=sorted(
                        {ref for row in group_rows for ref in _loads(row["source_case_refs"], [])}
                    ),
                    now=now,
                )
                for row in group_rows:
                    con.execute(
                        "UPDATE deep_research_records SET build_family_key = ? WHERE record_id = ?",
                        (identity.key, str(row["record_id"])),
                    )
                applied["new"] += 1
                continue
            applied["expand"] += 1
            entry["skipped_reason"] = (
                "expand requires merging an existing family; run the family merge "
                "script for this group instead"
            )
        con.commit()
        report["applied"] = applied
        report["skippedGroups"] = [e for e in dispositions if e.get("skipped_reason")]
        report["skippedExpandGroups"] = [
            e
            for e in dispositions
            if e.get("skipped_reason") is None and e["disposition"] == "expand"
        ]
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
