"""Full re-consolidation of Build Families under the set-based identity rule.

Identity = ascendancy + primary-skill SET (gem-equivalence expanded). Secondary skills and
trigger hosts never participate. Families merge when canonical primary sets satisfy a
containment relation (A ⊆ B -> A joins B; B ⊆ A -> B's set is extended and A joins).
Partial-overlap and disjoint families are left untouched (reported for human review).

Modes:
  --dry-run   compute the full merge plan without writing anything
  --validate  dry-run + consistency checks (no orphans, no containment violations)
  --apply     back up the DB, execute the merge iteratively until convergence, write a
              per-merge log table, and report the outcome

Knowledge records keep their knowledge keys when relocated; duplicates are resolved by
record quality (richer survives). This script only moves ownership, never knowledge content.
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

from server.knowledge import mature_learning, research_identity, research_memory  # noqa: E402
from server.knowledge.skill_equivalence import SkillEquivalenceIndex  # noqa: E402

_MERGE_LOG_SQL = """
CREATE TABLE IF NOT EXISTS family_merge_log (
    merge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    src_family_key TEXT NOT NULL,
    dst_family_key TEXT NOT NULL,
    dst_primary_skill_keys TEXT NOT NULL,
    relation TEXT NOT NULL,
    moved INTEGER NOT NULL DEFAULT 0,
    deprecated INTEGER NOT NULL DEFAULT 0,
    merged_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(value, default):
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_families(con):
    rows = con.execute(
        "SELECT build_family_key, ascendancy_key, primary_skill_key, primary_skill_keys, "
        "secondary_skill_keys, evidence_count FROM research_build_families"
    ).fetchall()
    families = []
    for row in rows:
        keys = _loads(row["primary_skill_keys"], None)
        if not keys:
            keys = [str(row["primary_skill_key"] or "")] if row["primary_skill_key"] else []
        families.append(
            {
                "key": str(row["build_family_key"]),
                "ascendancy": str(row["ascendancy_key"]),
                "primary_keys": [str(k) for k in keys if k],
                "secondary_keys": [str(k) for k in _loads(row["secondary_skill_keys"], [])],
                "evidence_count": int(row["evidence_count"] or 0),
            }
        )
    return families


def collect_record_primary_keys(con, family_key: str) -> list[str]:
    rows = con.execute(
        "SELECT component_mentions FROM deep_research_records WHERE build_family_key = ?",
        (family_key,),
    ).fetchall()
    keys: set[str] = set()
    for row in rows:
        for mention in _loads(row["component_mentions"], []):
            if (
                isinstance(mention, dict)
                and str(mention.get("role") or "") == "primary_damage"
                and str(mention.get("component_key") or "").startswith("skill:")
            ):
                keys.add(str(mention["component_key"]))
    return sorted(keys)


def canonical_set(con, keys, idx: SkillEquivalenceIndex) -> frozenset[str]:
    """Canonical primary-set token with gem AND model-confirmed equivalence applied."""
    return research_memory.ResearchMemoryService._canonical_identity_set(con, keys, idx=idx)


def merge_plan_expansions(con, families, idx: SkillEquivalenceIndex) -> list[dict]:
    """Auto-merge candidates under set containment.

    - identical canonical primary sets -> ``join`` the lower-evidence family into the
      higher-evidence one (no identity change);
    - strict subset canonical sets -> ``expand`` the superset family's primary list and
      join the subset into it.

    Partial-overlap and disjoint families are left untouched (reported for review).
    """
    plan: list[dict] = []
    by_ascendancy: dict[str, list[dict]] = {}
    for fam in families:
        by_ascendancy.setdefault(fam["ascendancy"], []).append(fam)
    for ascendancy, group in by_ascendancy.items():
        entries = [
            (canonical_set(con, f["primary_keys"], idx), f) for f in group if f["primary_keys"]
        ]
        for canon, fam in entries:
            supersets = [
                (other_canon, other)
                for other_canon, other in entries
                if other["key"] != fam["key"] and canon < other_canon
            ]
            if supersets:
                # strict subset -> join the smallest strict superset (deterministic)
                supersets.sort(key=lambda pair: (len(pair[0]), sorted(pair[0]), pair[1]["key"]))
                other_canon, other = supersets[0]
                merged = sorted(set(fam["primary_keys"]) | set(other["primary_keys"]))
                plan.append(
                    {
                        "src": fam["key"],
                        "dst": other["key"],
                        "dst_key": None,  # expand: identity key is recomputed
                        "relation": "expand",
                        "dst_primary_keys": merged,
                    }
                )
                continue
            # identical canonical set -> join the lower-evidence family into the richer one
            same_canon = sorted(
                [
                    other
                    for other_canon, other in entries
                    if other["key"] != fam["key"] and other_canon == canon
                ],
                key=lambda other: (-other["evidence_count"], other["key"]),
            )
            if same_canon:
                target = same_canon[0]
                lower = fam["evidence_count"] < target["evidence_count"] or (
                    fam["evidence_count"] == target["evidence_count"] and fam["key"] < target["key"]
                )
                if lower:
                    plan.append(
                        {
                            "src": fam["key"],
                            "dst": target["key"],
                            "dst_key": target["key"],  # join keeps the target's stored key
                            "relation": "join",
                            "dst_primary_keys": target["primary_keys"],
                        }
                    )
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(mature_learning.mature_learning_path()),
        help="mature learning DB path (default: per-user store)",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help="directory for the pre-apply backup copy (default: beside the DB)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="compute plan, write nothing")
    mode.add_argument("--validate", action="store_true", help="dry-run + consistency checks")
    mode.add_argument("--apply", action="store_true", help="back up, merge, write log")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(json.dumps({"status": "error", "errorCode": "db_missing", "db": str(db_path)}))
        return 2

    idx = SkillEquivalenceIndex.shared()
    mature_learning.initialize_store(db_path)
    con = mature_learning.connect(db_path)
    try:
        families = load_families(con)
        # initialize primary_skill_keys for legacy rows: stored value + record-level primary
        # damage declarations
        enriched = []
        for fam in families:
            record_keys = collect_record_primary_keys(con, fam["key"])
            fam["primary_keys"] = sorted(set(fam["primary_keys"]) | set(record_keys))
            enriched.append(fam)
        join_plan = merge_plan_expansions(con, enriched, idx)
        partial_overlap: list[dict] = []
        by_asc: dict[str, list[dict]] = {}
        for fam in enriched:
            by_asc.setdefault(fam["ascendancy"], []).append(fam)
        for asc, group in by_asc.items():
            entries = [
                (canonical_set(con, f["primary_keys"], idx), f) for f in group if f["primary_keys"]
            ]
            for i, (canon_i, fam_i) in enumerate(entries):
                for canon_j, fam_j in entries[i + 1 :]:
                    inter = canon_i & canon_j
                    if (
                        inter
                        and canon_i != canon_j
                        and not (canon_i < canon_j)
                        and not (canon_j < canon_i)
                    ):
                        partial_overlap.append(
                            {
                                "family_a": fam_i["key"],
                                "family_b": fam_j["key"],
                                "ascendancy": asc,
                                "shared": sorted(inter),
                            }
                        )
        report = {
            "status": "ok",
            "mode": "dry-run" if args.dry_run else "validate" if args.validate else "apply",
            "familyCount": len(enriched),
            "mergePlan": join_plan,
            "partialOverlapPairs": partial_overlap,
            "mergePlanCount": len(join_plan),
            "partialOverlapCount": len(partial_overlap),
        }
        if args.dry_run or args.validate:
            if args.validate:
                report["consistency"] = {
                    "familiesWithoutPrimaryKeys": sum(1 for f in enriched if not f["primary_keys"]),
                    "familiesWithNoRecords": sum(
                        1
                        for f in enriched
                        if con.execute(
                            "SELECT 1 FROM deep_research_records WHERE build_family_key = ?",
                            (f["key"],),
                        ).fetchone()
                        is None
                        and con.execute(
                            "SELECT 1 FROM research_build_family_evidence "
                            "WHERE build_family_key = ?",
                            (f["key"],),
                        ).fetchone()
                        is None
                    ),
                }
            print(json.dumps(report, ensure_ascii=False))
            return 0

        # apply
        backup_path = None
        if args.backup_dir:
            backup_dir = Path(args.backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_dir / f"mature_build_learning.pre-merge-{stamp}.sqlite"
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = db_path.with_name(f"{db_path.stem}.pre-merge-{stamp}{db_path.suffix}")
        shutil.copy2(db_path, backup_path)
        con.execute(_MERGE_LOG_SQL)
        service = research_memory.ResearchMemoryService(
            db_path=db_path, graph_service=None, initialize_store=False
        )
        now = _now()
        # Backfill primary_skill_keys on every family (stored value + record-level primary
        # damage declarations) so later rounds and future runs see a consistent identity.
        for fam in enriched:
            con.execute(
                "UPDATE research_build_families SET primary_skill_keys = ? WHERE build_family_key = ?",
                (_json(fam["primary_keys"]), fam["key"]),
            )
        con.commit()
        merged = 0
        rounds = 0
        while True:
            rounds += 1
            families = load_families(con)
            enriched_now = []
            for fam in families:
                record_keys = collect_record_primary_keys(con, fam["key"])
                fam["primary_keys"] = sorted(set(fam["primary_keys"]) | set(record_keys))
                enriched_now.append(fam)
            plan_round = merge_plan_expansions(con, enriched_now, idx)
            if not plan_round:
                break
            for entry in plan_round:
                src = entry["src"]
                if (
                    con.execute(
                        "SELECT 1 FROM research_build_families WHERE build_family_key = ?",
                        (src,),
                    ).fetchone()
                    is None
                ):
                    continue  # already merged this round
                dst_key = entry.get("dst_key")
                if dst_key is not None:
                    if (
                        con.execute(
                            "SELECT 1 FROM research_build_families WHERE build_family_key = ?",
                            (dst_key,),
                        ).fetchone()
                        is None
                    ):
                        continue  # target gone; next round replans
                    dst_identity = next(
                        (
                            research_identity.BuildFamilyIdentity(
                                ascendancy_key=fam["ascendancy"],
                                primary_skill_keys=tuple(sorted(fam["primary_keys"])),
                                secondary_skill_keys=tuple(sorted(fam["secondary_keys"])),
                            )
                            for fam in enriched_now
                            if fam["key"] == dst_key
                        ),
                        None,
                    )
                    if dst_identity is None:
                        continue
                else:
                    dst_identity = research_identity.BuildFamilyIdentity(
                        ascendancy_key=next(
                            f["ascendancy"] for f in enriched_now if f["key"] == src
                        ),
                        primary_skill_keys=tuple(sorted(entry["dst_primary_keys"])),
                    )
                    dst_key = dst_identity.key
                result = service._merge_family_records(
                    con,
                    src_family_key=src,
                    dst_identity=dst_identity,
                    now=now,
                    dst_key=dst_key,
                )
                con.execute(
                    """
                    INSERT INTO family_merge_log(
                        src_family_key, dst_family_key, dst_primary_skill_keys,
                        relation, moved, deprecated, merged_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        src,
                        result["dst_family_key"],
                        _json(list(dst_identity.primary_skill_keys)),
                        entry["relation"],
                        result["moved"],
                        result["deprecated"],
                        now,
                    ),
                )
                merged += 1
            con.commit()
            if rounds > 50:
                print(
                    json.dumps(
                        {"status": "error", "errorCode": "merge_did_not_converge"},
                        ensure_ascii=False,
                    )
                )
                return 3
        report.update(
            {
                "status": "applied",
                "backup": str(backup_path),
                "mergeRounds": rounds,
                "mergedFamilyGroups": merged,
            }
        )
        print(json.dumps(report, ensure_ascii=False))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
