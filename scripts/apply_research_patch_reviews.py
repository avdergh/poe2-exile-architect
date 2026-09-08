"""校验并原子应用已完成独立复核的补丁适用性决定；不生成审查结论。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.knowledge import mature_learning, patch_reviews  # noqa: E402


def apply_bundle(
    db_path: Path, reviews: list[dict], *, apply: bool = False, backup_dir: Path | None = None
) -> dict:
    """Validate all decisions in one transaction; dry-run rolls back every write."""
    if not db_path.is_file() or not reviews:
        raise ValueError("existing_database_and_nonempty_reviews_required")
    identities = [
        (item.get("target_kind"), item.get("target_id"), item.get("target_game_patch"))
        for item in reviews
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate_patch_review_target")
    con = mature_learning.connect(db_path)
    backup_path = None
    try:
        con.execute("BEGIN IMMEDIATE")
        if apply:
            destination = backup_dir or db_path.parent / "patch-review-backups"
            destination.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = destination / f"{db_path.stem}-{stamp}.sqlite"
            with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as source:
                with sqlite3.connect(backup_path) as target:
                    source.backup(target)
        patch_reviews.install_schema(con)
        results = [patch_reviews.submit(con, item) for item in reviews]
        counts: dict[str, int] = {}
        for item in reviews:
            counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
        if apply:
            con.commit()
        else:
            con.rollback()
        return {
            "status": "applied" if apply else "validated",
            "reviewCount": len(results),
            "outcomes": counts,
            "idempotentReplayCount": sum(bool(r.get("idempotentReplay")) for r in results),
            "backupPath": str(backup_path) if backup_path else None,
            "sourceKnowledgePreserved": True,
        }
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    reviews = json.loads(args.reviews.read_text(encoding="utf-8"))
    result = apply_bundle(args.db, reviews, apply=args.apply, backup_dir=args.backup_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
