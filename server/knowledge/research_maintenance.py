"""One-shot, auditable maintenance for pre-Family research memory."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from . import mature_learning
from . import research_identity
from . import research_memory
from . import research_models
from . import research_runtime
from . import research_claim_writes


LEGACY_CLEANUP_MARKER = "phase4_legacy_memory_cleanup_v1"
RESEARCH_CONTRACT_CALIBRATION_MARKER = "phase4_research_contract_calibration_v1"
RECONCILE_RECORD_IDS_MARKER = "phase4_deep_record_id_reconcile_v1"

STORMWEAVER_CALIBRATION_SPECS: dict[str, dict[str, Any]] = {
    "source-hash:9dcc40c506855f93": {
        "supportPackages": {
            "skill:SparkPlayer": [
                "support:Metadata/Items/Gem/SupportGemConsideredCasting",
                "support:Metadata/Items/Gems/SupportGemArcaneTempoTwo",
                "support:Metadata/Items/Gems/SupportGemAccelerationTwo",
                "support:Metadata/Items/Gems/SupportGemPinpointCritical",
                "support:Metadata/Items/Gems/SupportGemInspirationTwo",
            ],
            "skill:MetaCastOnCritPlayer": [
                "support:Metadata/Items/Gems/SupportGemPinpointCritical",
                "support:Metadata/Items/Gem/SupportGemFluke",
                "support:Metadata/Items/Gems/SupportGemInspirationTwo",
                "support:Metadata/Items/Gems/SupportGemColdMastery",
            ],
        },
        "extraSupports": {
            "support:Metadata/Items/Gems/SupportGemAccelerationTwo": "Projectile Acceleration II",
        },
    },
    "source-hash:b3793fd4ed43a1fc": {
        "supportPackages": {
            "skill:SparkPlayer": [
                "support:Metadata/Items/Gems/SupportGemFork",
                "support:Metadata/Items/Gems/SupportGemPierceThree",
                "support:Metadata/Items/Gems/SupportGemVilentasPropulsion",
                "support:Metadata/Items/Gems/SupportGemPinpointCritical",
            ],
            "skill:MetaCastOnCritPlayer": [
                "support:Metadata/Items/Gem/SupportGemSpellCascade",
                "support:Metadata/Items/Gem/SupportGemImpetusTwo",
                "support:Metadata/Items/Gems/SupportGemConcentratedEffect",
                "support:Metadata/Items/Gems/SupportGemArcaneTempoTwo",
                "support:Metadata/Items/Gems/SupportGemColdMastery",
            ],
        },
        "extraSupports": {
            "support:Metadata/Items/Gems/SupportGemFork": "Fork",
            "support:Metadata/Items/Gems/SupportGemPierceThree": "Pierce III",
            "support:Metadata/Items/Gems/SupportGemVilentasPropulsion": "Vilenta's Propulsion",
            "support:Metadata/Items/Gem/SupportGemSpellCascade": "Spell Cascade",
            "support:Metadata/Items/Gem/SupportGemImpetusTwo": "Boundless Energy II",
            "support:Metadata/Items/Gems/SupportGemConcentratedEffect": "Concentrated Area",
        },
    },
    "source-hash:e7b7effe4da58488": {
        "supportPackages": {
            "skill:FrostboltPlayer": [
                "support:Metadata/Items/Gems/SupportGemVilentasPropulsion",
                "support:Metadata/Items/Gem/SupportGemWildshardsThree",
                "support:Metadata/Items/Gems/SupportGemPinpointCritical",
                "support:Metadata/Items/Gems/SupportGemRisingTempest",
                "support:Metadata/Items/Gems/SupportGemMagnifiedEffectTwo",
            ]
        },
        "extraSupports": {
            "support:Metadata/Items/Gems/SupportGemMagnifiedEffectTwo": "Magnified Area II",
        },
    },
    "source-hash:6b65a3b2bfcc639f": {
        "recordFields": {
            "title": "Spark-CoC Comet 处决支持包",
            "summary": "Spark 高频暴击驱动偏处决与覆盖的 Comet 载荷。",
            "content": "Spark 以 Vilenta's Propulsion、Rapid Casting II、Execute III 和 Zenith II 作为高频主攻；Cast on Critical 以 Execute III、Spell Cascade、Zenith II 和 Efficiency II 承载 Comet。该支持选择偏向处决窗口和区域覆盖，Spark 与 Comet 必须分组评价，不能把触发器名称当作主技能。",
        },
        "supportPackages": {
            "skill:SparkPlayer": [
                "support:Metadata/Items/Gems/SupportGemVilentasPropulsion",
                "support:Metadata/Items/Gems/SupportGemArcaneTempoTwo",
                "support:Metadata/Items/Gems/SupportGemExecuteThree",
                "support:Metadata/Items/Gem/SupportGemZenithTwo",
            ],
            "skill:MetaCastOnCritPlayer": [
                "support:Metadata/Items/Gems/SupportGemExecuteThree",
                "support:Metadata/Items/Gem/SupportGemSpellCascade",
                "support:Metadata/Items/Gem/SupportGemZenithTwo",
                "support:Metadata/Items/Gems/SupportGemInspirationTwo",
            ],
        },
        "extraSupports": {
            "support:Metadata/Items/Gems/SupportGemVilentasPropulsion": "Vilenta's Propulsion",
            "support:Metadata/Items/Gems/SupportGemExecuteThree": "Execute III",
            "support:Metadata/Items/Gem/SupportGemZenithTwo": "Zenith II",
        },
    },
    "source-hash:82be3741e4be100f": {
        "recordFields": {
            "title": "成熟冷转 Spark-CoC 技能包",
            "summary": "高等级 Spark 本体与冷系 CoC-Comet 共同输出。",
            "content": "Spark 使用 Rapid Casting II、Pinpoint Critical、Projectile Acceleration II、Considered Casting 与 Zenith II，兼顾施法频率、弹速和暴击；CoC-Comet 使用 Fluke、Pinpoint Critical、Efficiency II 和 Cold Mastery，承担冷系集中载荷。该版本主手额外投射物和高额法术等级让 Spark 本体也占明显输出份额。",
        },
        "supportPackages": {
            "skill:SparkPlayer": [
                "support:Metadata/Items/Gems/SupportGemArcaneTempoTwo",
                "support:Metadata/Items/Gems/SupportGemPinpointCritical",
                "support:Metadata/Items/Gems/SupportGemAccelerationTwo",
                "support:Metadata/Items/Gem/SupportGemConsideredCasting",
                "support:Metadata/Items/Gem/SupportGemZenithTwo",
            ],
            "skill:MetaCastOnCritPlayer": [
                "support:Metadata/Items/Gem/SupportGemFluke",
                "support:Metadata/Items/Gems/SupportGemPinpointCritical",
                "support:Metadata/Items/Gems/SupportGemInspirationTwo",
                "support:Metadata/Items/Gems/SupportGemColdMastery",
            ],
        },
        "extraSupports": {
            "support:Metadata/Items/Gems/SupportGemPinpointCritical": "Pinpoint Critical",
            "support:Metadata/Items/Gems/SupportGemAccelerationTwo": "Projectile Acceleration II",
            "support:Metadata/Items/Gem/SupportGemZenithTwo": "Zenith II",
            "support:Metadata/Items/Gems/SupportGemInspirationTwo": "Efficiency II",
        },
    },
}

MUTATED_RATHPITH_SOURCE = "source-hash:6b65a3b2bfcc639f"
MUTATED_RATHPITH_COMPONENT = "unique:pob:rathpith_globe"
MUTATED_RATHPITH_PATTERN_ID = "bdp-b1d9b647408b0ca2"


def remove_exclusive_research_sources(
    source_case_refs: list[str],
    *,
    db_path: Path | None = None,
    apply: bool = False,
    backup_path: Path | None = None,
) -> dict[str, Any]:
    """Remove source-owned research only when no durable unit mixes wanted and retained sources."""

    wanted = sorted({str(value).strip() for value in source_case_refs if str(value).strip()})
    if not wanted:
        raise ValueError("source_case_refs must contain at least one source")
    path = Path(db_path or mature_learning.mature_learning_path()).resolve()
    mature_learning.initialize_store(path)
    con = mature_learning.connect(path)
    try:
        shared: list[dict[str, Any]] = []
        owned_rows: dict[str, list[str]] = {}
        for table, id_column in (
            ("deep_research_records", "record_id"),
            ("research_build_patterns", "pattern_id"),
            ("research_build_design_observations", "observation_id"),
            ("research_semantic_edges", "edge_id"),
            ("research_fragments", "fragment_id"),
        ):
            owned_rows[table] = []
            for row in con.execute(f"SELECT {id_column}, source_case_refs FROM {table}"):
                refs = {str(value) for value in _loads(row["source_case_refs"], [])}
                matched = refs & set(wanted)
                if not matched:
                    continue
                if refs - set(wanted):
                    shared.append(
                        {
                            "table": table,
                            "id": str(row[id_column]),
                            "matchedSourceRefs": sorted(matched),
                            "retainedSourceRefs": sorted(refs - set(wanted)),
                        }
                    )
                else:
                    owned_rows[table].append(str(row[id_column]))
        shared_family_evidence = [
            {
                "knowledgeScope": str(row["knowledge_scope"]),
                "buildFamilyKey": str(row["build_family_key"]),
                "retainedEvidenceCount": int(row["retained_count"]),
            }
            for row in con.execute(
                f"""
                SELECT knowledge_scope, build_family_key,
                       sum(CASE WHEN source_case_ref NOT IN ({",".join("?" for _ in wanted)})
                                THEN 1 ELSE 0 END) AS retained_count,
                       sum(CASE WHEN source_case_ref IN ({",".join("?" for _ in wanted)})
                                THEN 1 ELSE 0 END) AS matched_count
                FROM research_build_family_evidence
                GROUP BY knowledge_scope, build_family_key
                HAVING matched_count > 0 AND retained_count > 0
                """,
                (*wanted, *wanted),
            ).fetchall()
        ]
        if shared_family_evidence:
            shared.extend(
                {"table": "research_build_families", **item} for item in shared_family_evidence
            )
        report: dict[str, Any] = {
            "status": "blocked_shared_evidence" if shared else "planned",
            "databasePath": str(path),
            "sourceCaseRefs": wanted,
            "sharedDurableUnits": shared,
            "deleteCounts": {table: len(ids) for table, ids in owned_rows.items()},
            "deleteCountsByEvidenceTable": {
                "research_fragment_evidence": int(
                    con.execute(
                        (
                            "SELECT count(*) FROM research_fragment_evidence "
                            f"WHERE fragment_id IN ({','.join('?' for _ in owned_rows['research_fragments'])})"
                        )
                        if owned_rows["research_fragments"]
                        else "SELECT 0",
                        owned_rows["research_fragments"],
                    ).fetchone()[0]
                ),
                "deep_research_record_evidence": int(
                    con.execute(
                        f"SELECT count(*) FROM deep_research_record_evidence WHERE source_case_ref IN ({','.join('?' for _ in wanted)})",
                        wanted,
                    ).fetchone()[0]
                ),
                "research_build_family_evidence": int(
                    con.execute(
                        f"SELECT count(*) FROM research_build_family_evidence WHERE source_case_ref IN ({','.join('?' for _ in wanted)})",
                        wanted,
                    ).fetchone()[0]
                ),
            },
        }
        if shared or not apply:
            return report

        resolved_backup_path = _backup_database(
            con,
            path,
            backup_path,
            marker="phase4_source_retraction",
        )
        try:
            con.execute("BEGIN IMMEDIATE")
            visible_change_count = 0
            fragment_ids = owned_rows["research_fragments"]
            if fragment_ids:
                visible_change_count += max(
                    0,
                    con.execute(
                    "DELETE FROM research_fragment_evidence "
                    f"WHERE fragment_id IN ({','.join('?' for _ in fragment_ids)})",
                    fragment_ids,
                    ).rowcount,
                )
            for table, id_column in (
                ("research_build_patterns", "pattern_id"),
                ("research_build_design_observations", "observation_id"),
                ("research_semantic_edges", "edge_id"),
                ("research_fragments", "fragment_id"),
                ("deep_research_records", "record_id"),
            ):
                ids = owned_rows[table]
                if ids:
                    predicate = f"{id_column} IN ({','.join('?' for _ in ids)})"
                    visible_change_count += int(con.execute(
                        f"SELECT count(*) FROM {table} WHERE {predicate}", ids
                    ).fetchone()[0])
                    con.execute(f"DELETE FROM {table} WHERE {predicate}", ids)
            visible_change_count += max(
                0,
                con.execute(
                    f"DELETE FROM deep_research_record_evidence WHERE source_case_ref IN ({','.join('?' for _ in wanted)})",
                    wanted,
                ).rowcount,
            )
            visible_change_count += max(
                0,
                con.execute(
                    f"DELETE FROM research_build_family_evidence WHERE source_case_ref IN ({','.join('?' for _ in wanted)})",
                    wanted,
                ).rowcount,
            )
            visible_change_count += max(
                0,
                con.execute(
                    "DELETE FROM research_build_families WHERE NOT EXISTS "
                    "(SELECT 1 FROM research_build_family_evidence e "
                    "WHERE e.knowledge_scope = research_build_families.knowledge_scope "
                    "AND e.build_family_key = research_build_families.build_family_key) "
                    "AND NOT EXISTS (SELECT 1 FROM deep_research_records r "
                    "WHERE r.knowledge_scope = research_build_families.knowledge_scope "
                    "AND r.build_family_key = research_build_families.build_family_key)"
                ).rowcount,
            )
            con.execute(
                "INSERT INTO meta(key, value) VALUES ('phase4_build_family_backfill_version', '0') "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
            )
            integrity = str(con.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = list(con.execute("PRAGMA foreign_key_check").fetchall())
            if integrity != "ok" or foreign_keys:
                raise RuntimeError("research source removal failed database integrity checks")
            if visible_change_count:
                research_runtime.bump_memory_revision(con)
            con.commit()
        except Exception:
            con.rollback()
            raise
        report.update(
            {
                "status": "applied",
                "backupPath": str(resolved_backup_path),
                "databaseIntegrity": integrity,
                "foreignKeyViolationCount": len(foreign_keys),
            }
        )
        return report
    finally:
        con.close()


def cleanup_legacy_research_memory(
    *,
    db_path: Path | None = None,
    apply: bool = False,
    backup_path: Path | None = None,
) -> dict[str, Any]:
    path = Path(db_path or mature_learning.mature_learning_path()).resolve()
    mature_learning.initialize_store(path)
    con = mature_learning.connect(path)
    try:
        marker = con.execute(
            "SELECT value FROM meta WHERE key = ?", (LEGACY_CLEANUP_MARKER,)
        ).fetchone()
        if marker is not None:
            return {
                "status": "already_applied",
                "marker": LEGACY_CLEANUP_MARKER,
                "details": _loads(marker[0], {}),
            }

        fragment_supersessions = _legacy_fragment_supersessions(con)
        familyless_rows = list(
            con.execute(
                """
                SELECT record_id, research_group_id
                FROM deep_research_records
                WHERE visibility = 'creator_visible'
                  AND split = 'train_context'
                  AND status IN ('valid', 'needs_revalidation')
                  AND superseded_by_id IS NULL
                  AND COALESCE(build_family_key, '') = ''
                  AND COALESCE(knowledge_key, '') = ''
                  AND evidence_count = 0
                  AND extraction_method_version = 'deep_research_mvp_v1'
                  AND record_schema_version = 1
                ORDER BY research_group_id, record_id
                """
            ).fetchall()
        )
        familyless_ids = [str(row["record_id"]) for row in familyless_rows]
        familyless_groups = sorted({str(row["research_group_id"]) for row in familyless_rows})
        report: dict[str, Any] = {
            "status": "planned" if not apply else "pending",
            "marker": LEGACY_CLEANUP_MARKER,
            "databasePath": str(path),
            "fragmentSupersessions": [
                {"fragmentId": duplicate, "supersededById": canonical}
                for duplicate, canonical in sorted(fragment_supersessions.items())
            ],
            "fragmentSupersessionCount": len(fragment_supersessions),
            "quarantinedDeepRecordCount": len(familyless_ids),
            "quarantinedResearchGroupCount": len(familyless_groups),
            "quarantinedResearchGroupIds": familyless_groups,
            "physicalDeleteCount": 0,
        }
        if not apply:
            return report

        resolved_backup_path = _backup_database(con, path, backup_path)
        now = _now()
        try:
            con.execute("BEGIN IMMEDIATE")
            _apply_fragment_supersessions(con, fragment_supersessions, now)
            if familyless_ids:
                placeholders = ",".join("?" for _ in familyless_ids)
                con.execute(
                    f"""
                    UPDATE deep_research_records
                    SET visibility = 'quarantined',
                        split = 'quarantine',
                        status = 'quarantined',
                        last_seen_at = ?
                    WHERE record_id IN ({placeholders})
                    """,
                    (now, *familyless_ids),
                )
            marker_details = {
                "appliedAt": now,
                "backupPath": str(resolved_backup_path),
                "fragmentSupersessionCount": len(fragment_supersessions),
                "quarantinedDeepRecordCount": len(familyless_ids),
                "quarantinedResearchGroupCount": len(familyless_groups),
            }
            con.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                (LEGACY_CLEANUP_MARKER, _json(marker_details)),
            )
            if fragment_supersessions or familyless_ids:
                research_runtime.bump_memory_revision(con)
            con.commit()
        except Exception:
            con.rollback()
            raise
        report.update(
            {
                "status": "applied",
                "backupPath": str(resolved_backup_path),
                "appliedAt": now,
            }
        )
        return report
    finally:
        con.close()


def calibrate_research_contract_v1(
    *,
    db_path: Path | None = None,
    apply: bool = False,
    backup_path: Path | None = None,
) -> dict[str, Any]:
    """Calibrate known Phase 4 records to the support, Family and random-instance contracts."""

    path = Path(db_path or mature_learning.mature_learning_path()).resolve()
    mature_learning.initialize_store(path)
    con = mature_learning.connect(path)
    try:
        marker = con.execute(
            "SELECT value FROM meta WHERE key = ?",
            (RESEARCH_CONTRACT_CALIBRATION_MARKER,),
        ).fetchone()
        if marker is not None:
            return {
                "status": "already_applied",
                "marker": RESEARCH_CONTRACT_CALIBRATION_MARKER,
                "details": _loads(marker[0], {}),
            }

        skill_rows = _calibration_skill_rows(con)
        mutated_rows = _calibration_mutated_rows(con)
        pattern_exists = (
            con.execute(
                "SELECT 1 FROM research_build_patterns WHERE pattern_id = ?",
                (MUTATED_RATHPITH_PATTERN_ID,),
            ).fetchone()
            is not None
        )
        report: dict[str, Any] = {
            "status": "planned" if not apply else "pending",
            "marker": RESEARCH_CONTRACT_CALIBRATION_MARKER,
            "databasePath": str(path),
            "supportPackageRecordCount": len(skill_rows),
            "supportPackageSourceRefs": sorted(skill_rows),
            "sourceSpecificRandomRecordCount": len(mutated_rows),
            "sourceSpecificRandomPatternCount": int(pattern_exists),
            "physicalDeleteCount": 0,
        }
        protected = [
            {"recordId": str(row["record_id"]), "reason": reason}
            for row in [*skill_rows.values(), *mutated_rows]
            if (reason := _legacy_mutation_issue(con, row))
        ]
        for row in skill_rows.values():
            selected_sources = {
                source for source, selected in skill_rows.items()
                if selected["record_id"] == row["record_id"]
            }
            if set(_loads(row["source_case_refs"], [])) - selected_sources:
                protected.append({
                    "recordId": str(row["record_id"]),
                    "reason": "source_claims_outside_calibration",
                })
        if protected:
            return {
                **report,
                "status": "blocked_unsafe_targets",
                "protectedRecords": protected,
                "repair": "已绑定来源或存在条件变体的目标须使用逐来源研究修订，旧校准不覆盖这些记录。",
            }
        if not apply:
            return report

        resolved_backup_path = _backup_database(
            con,
            path,
            backup_path,
            marker=RESEARCH_CONTRACT_CALIBRATION_MARKER,
        )
        now = _now()
        try:
            con.execute("BEGIN IMMEDIATE")
            calibrated_rows: list[tuple[str, str]] = []
            for source_ref, row in skill_rows.items():
                calibrated_rows.append(
                    _apply_support_calibration(
                        con,
                        row=row,
                        source_ref=source_ref,
                        spec=STORMWEAVER_CALIBRATION_SPECS[source_ref],
                        now=now,
                    )
                )
            calibrated_new_ids = {new_id for _old_id, new_id in calibrated_rows}
            for old_id, new_id in sorted(set(calibrated_rows)):
                if old_id in calibrated_new_ids:
                    continue
                con.execute(
                    """
                    UPDATE deep_research_records
                    SET status = 'deprecated', superseded_by_id = ?, last_seen_at = ?
                    WHERE record_id = ?
                    """,
                    (new_id, now, old_id),
                )
            for row in mutated_rows:
                typed_payload = _loads(row["typed_payload"], {})
                typed_payload.update(
                    {
                        "availability": "source_specific_random",
                        "sourceSpecificComponentKeys": [MUTATED_RATHPITH_COMPONENT],
                    }
                )
                con.execute(
                    """
                    UPDATE deep_research_records
                    SET typed_payload = ?, last_seen_at = ?, last_validated_at = ?
                    WHERE record_id = ?
                    """,
                    (_json(typed_payload), now, now, row["record_id"]),
                )
            if pattern_exists:
                con.execute(
                    """
                    UPDATE research_build_patterns
                    SET planner_visible = 0, status = 'deprecated', last_seen_at = ?
                    WHERE pattern_id = ?
                    """,
                    (now, MUTATED_RATHPITH_PATTERN_ID),
                )
            marker_details = {
                "appliedAt": now,
                "backupPath": str(resolved_backup_path),
                "supportPackageRecordCount": len(skill_rows),
                "sourceSpecificRandomRecordCount": len(mutated_rows),
                "sourceSpecificRandomPatternCount": int(pattern_exists),
            }
            con.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                (RESEARCH_CONTRACT_CALIBRATION_MARKER, _json(marker_details)),
            )
            con.execute(
                """
                INSERT INTO meta(key, value) VALUES ('phase4_build_family_backfill_version', '0')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )
            if skill_rows or mutated_rows or pattern_exists:
                research_runtime.bump_memory_revision(con)
            con.commit()
        except Exception:
            con.rollback()
            raise

        backfill = research_memory.ResearchMemoryService(
            db_path=path,
            initialize_store=False,
        ).backfill_deep_research_knowledge(force=True)
        report.update(
            {
                "status": "applied",
                "backupPath": str(resolved_backup_path),
                "appliedAt": now,
                "backfill": backfill,
            }
        )
        return report
    finally:
        con.close()


def reconcile_deep_record_ids(
    *,
    db_path: Path | None = None,
    apply: bool = False,
    backup_path: Path | None = None,
) -> dict[str, Any]:
    """Relocate active deep records whose record_id no longer hashes to their
    knowledge_key, restoring the id = hash(knowledge_key) invariant that historical
    backfill key rewrites broke (the source of UNIQUE record_id collisions on re-accept).

    Only active rows are relocated. Deprecated husks are never relocated: their decoupled
    ids are the stable tombstones the write-path adoption in _persist_deep_record and the
    query redirect rely on. The one exception is a husk occupying an active row's anchor
    id: it is removed (dependents re-pointed to the husk's final chain head) so the active
    unit can reclaim its canonical id. Targets occupied by a different active unit (drift
    cycles) are reported and left alone; the write-path adoption keeps future accepts safe.
    """
    path = Path(db_path or mature_learning.mature_learning_path()).resolve()
    mature_learning.initialize_store(path)
    con = mature_learning.connect(path)
    try:
        marker = con.execute(
            "SELECT value FROM meta WHERE key = ?", (RECONCILE_RECORD_IDS_MARKER,)
        ).fetchone()
        if marker is not None:
            return {
                "status": "already_applied",
                "marker": RECONCILE_RECORD_IDS_MARKER,
                "details": _loads(marker[0], {}),
            }

        active_rows = list(
            con.execute(
                """
                SELECT *
                FROM deep_research_records
                WHERE knowledge_key IS NOT NULL
                  AND status IN ('valid', 'needs_revalidation')
                  AND superseded_by_id IS NULL
                ORDER BY record_id
                """
            ).fetchall()
        )
        relocations: list[dict[str, str]] = []
        husk_replacements: list[dict[str, str]] = []
        superseded_duplicates: list[dict[str, str]] = []
        conflicts: list[dict[str, str]] = []
        protected_records: list[dict[str, str]] = []
        already_consistent_count = 0
        for row in active_rows:
            key = str(row["knowledge_key"])
            record_id = str(row["record_id"])
            target_id = research_runtime.canonical_record_id(str(row["knowledge_scope"]), key)
            if target_id == record_id:
                already_consistent_count += 1
                continue
            protection = _legacy_mutation_issue(con, row)
            if protection:
                protected_records.append({"recordId": record_id, "reason": protection})
                continue
            occupant = con.execute(
                """
                SELECT record_id, knowledge_key, status, superseded_by_id
                FROM deep_research_records
                WHERE record_id = ?
                """,
                (target_id,),
            ).fetchone()
            base = {
                "recordId": record_id,
                "targetRecordId": target_id,
                "knowledgeKey": key,
                "title": str(row["title"] or ""),
            }
            if occupant is None:
                relocations.append(base)
            elif str(occupant["knowledge_key"] or "") == key and str(occupant["status"] or "") in (
                "valid",
                "needs_revalidation",
            ):
                # The anchor id already holds this unit's canonical row; the drifted row
                # is a duplicate that only needs supersession.
                superseded_duplicates.append(base)
            elif occupant["superseded_by_id"] is not None:
                husk_replacements.append(
                    {
                        **base,
                        "huskId": str(occupant["record_id"]),
                        "huskHeadId": str(occupant["superseded_by_id"] or ""),
                    }
                )
            else:
                conflicts.append(
                    {
                        **base,
                        "targetOccupiedBy": str(occupant["record_id"]),
                    }
                )
        report: dict[str, Any] = {
            "status": "planned" if not apply else "pending",
            "marker": RECONCILE_RECORD_IDS_MARKER,
            "databasePath": str(path),
            "activeKeyedRecordCount": len(active_rows),
            "alreadyConsistentCount": already_consistent_count,
            "relocationCount": len(relocations) + len(husk_replacements),
            "relocations": relocations,
            "huskReplacementCount": len(husk_replacements),
            "huskReplacements": husk_replacements,
            "supersededDuplicateCount": len(superseded_duplicates),
            "supersededDuplicates": superseded_duplicates,
            "conflictCount": len(conflicts),
            "conflicts": conflicts,
            "protectedRecordCount": len(protected_records),
            "protectedRecords": protected_records,
            "physicalDeleteCount": 0,
        }
        if protected_records and not (relocations or husk_replacements or superseded_duplicates):
            report["status"] = "blocked_unsafe_targets"
            report["repair"] = "来源绑定或条件变体保留现有记录 ID；旧 ID 整理不能替代逐来源修订。"
            return report
        if not apply:
            return report

        resolved_backup_path = _backup_database(
            con, path, backup_path, marker=RECONCILE_RECORD_IDS_MARKER
        )
        now = _now()
        physical_delete_count = 0
        try:
            con.execute("BEGIN IMMEDIATE")

            def _insert_relocated_copy(old_id: str, target_id: str, key: str) -> None:
                # The moving row already carries `key`, so blank it until the copy is in
                # place and the old row is deprecated; otherwise the canonical
                # knowledge-key index would see two active holders.
                values = dict(con.execute(
                    "SELECT * FROM deep_research_records WHERE record_id = ?", (old_id,)
                ).fetchone())
                con.execute(
                    "UPDATE deep_research_records SET knowledge_key = NULL WHERE record_id = ?",
                    (old_id,),
                )
                values.update(record_id=target_id, knowledge_key=key, superseded_by_id=None)
                con.execute(
                    f"INSERT INTO deep_research_records({','.join(values)}) "
                    f"VALUES ({','.join('?' for _ in values)})", tuple(values.values()),
                )

            scheduled_husk_ids = {action["huskId"] for action in husk_replacements}
            for action in husk_replacements:
                husk_id = action["huskId"]
                # Re-point dependents to the husk's final chain head (skipping other
                # husks that are themselves scheduled for deletion in this run).
                head_id = action["huskHeadId"] or None
                seen = {husk_id}
                while head_id is not None and head_id not in seen:
                    seen.add(head_id)
                    if head_id not in scheduled_husk_ids:
                        break
                    head = con.execute(
                        "SELECT superseded_by_id FROM deep_research_records WHERE record_id = ?",
                        (head_id,),
                    ).fetchone()
                    head_id = head["superseded_by_id"] if head is not None else None
                con.execute(
                    """
                    UPDATE deep_research_records
                    SET superseded_by_id = ?
                    WHERE superseded_by_id = ?
                    """,
                    (head_id, husk_id),
                )
                con.execute("DELETE FROM deep_research_records WHERE record_id = ?", (husk_id,))
                physical_delete_count += 1
                _insert_relocated_copy(
                    action["recordId"], action["targetRecordId"], action["knowledgeKey"]
                )
            for action in relocations:
                _insert_relocated_copy(
                    action["recordId"], action["targetRecordId"], action["knowledgeKey"]
                )

            # Phase 2: deprecate displaced old ids only after every insert is complete,
            # and re-point any husk chains that referenced the displaced ids.
            for action in [*relocations, *husk_replacements]:
                old_id = action["recordId"]
                target_id = action["targetRecordId"]
                key = action["knowledgeKey"]
                con.execute(
                    """
                    UPDATE deep_research_records
                    SET status = 'deprecated', superseded_by_id = ?, knowledge_key = ?,
                        last_seen_at = ?
                    WHERE record_id = ?
                    """,
                    (target_id, key, now, old_id),
                )
                con.execute(
                    """
                    UPDATE deep_research_records
                    SET superseded_by_id = ?
                    WHERE superseded_by_id = ? AND record_id != ?
                    """,
                    (target_id, old_id, old_id),
                )
            for action in superseded_duplicates:
                con.execute(
                    """
                    UPDATE deep_research_records
                    SET status = 'deprecated', superseded_by_id = ?, last_seen_at = ?
                    WHERE record_id = ?
                    """,
                    (action["targetRecordId"], now, action["recordId"]),
                )
            for action in [*relocations, *husk_replacements, *superseded_duplicates]:
                con.execute(
                    "UPDATE deep_research_record_evidence SET record_id = ? WHERE record_id = ?",
                    (action["targetRecordId"], action["recordId"]),
                )
                if con.execute(
                    "SELECT 1 FROM deep_research_record_evidence WHERE record_id = ? LIMIT 1",
                    (action["targetRecordId"],),
                ).fetchone():
                    research_claim_writes.refresh_record_evidence(con, action["targetRecordId"], now)

            integrity = str(con.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = list(con.execute("PRAGMA foreign_key_check").fetchall())
            if integrity != "ok" or foreign_keys:
                raise RuntimeError("deep record id reconciliation failed integrity checks")
            marker_details = {
                "appliedAt": now,
                "backupPath": str(resolved_backup_path),
                "relocationCount": len(relocations) + len(husk_replacements),
                "huskReplacementCount": len(husk_replacements),
                "supersededDuplicateCount": len(superseded_duplicates),
                "conflictCount": len(conflicts),
                "physicalDeleteCount": physical_delete_count,
            }
            if not protected_records:
                con.execute(
                    "INSERT INTO meta(key, value) VALUES (?, ?)",
                    (RECONCILE_RECORD_IDS_MARKER, _json(marker_details)),
                )
            if relocations or husk_replacements or superseded_duplicates:
                research_runtime.bump_memory_revision(con)
            con.commit()
        except Exception:
            con.rollback()
            raise
        report.update(
            {
                "status": "applied_safe_subset" if protected_records else "applied",
                "backupPath": str(resolved_backup_path),
                "databaseIntegrity": integrity,
                "foreignKeyViolationCount": len(foreign_keys),
                "physicalDeleteCount": physical_delete_count,
            }
        )
        return report
    finally:
        con.close()


def _legacy_mutation_issue(con: sqlite3.Connection, row: sqlite3.Row) -> str | None:
    """Protect source-bound conclusions from historical key-only rewrite algorithms."""
    key = str(row["knowledge_key"] or "")
    if key and con.execute(
        "SELECT 1 FROM deep_research_records WHERE knowledge_scope = ? AND knowledge_key = ? "
        "AND record_id != ? AND superseded_by_id IS NULL "
        "AND projection_hash IS NOT NULL AND projection_hash IS NOT ? LIMIT 1",
        (row["knowledge_scope"], key, row["record_id"], row["projection_hash"]),
    ).fetchone():
        return "conditional_conclusion_variants"
    if con.execute(
        "SELECT 1 FROM deep_research_record_evidence WHERE record_id = ? "
        "AND binding_issue IS NULL LIMIT 1",
        (row["record_id"],),
    ).fetchone():
        return "source_claim_binding_requires_typed_revision"
    if int(row["record_schema_version"] or 1) >= 2 and str(row["record_id"]) != (
        research_runtime.canonical_record_id(str(row["knowledge_scope"]), key)
    ):
        return "conclusion_record_id_is_not_legacy_anchor"
    return None


def _calibration_skill_rows(con: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    result: dict[str, sqlite3.Row] = {}
    for source_ref in STORMWEAVER_CALIBRATION_SPECS:
        row = con.execute(
            """
            SELECT * FROM deep_research_records
            WHERE record_kind = 'skill_package'
              AND status IN ('valid', 'needs_revalidation')
              AND superseded_by_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM json_each(deep_research_records.source_case_refs)
                  WHERE json_each.value = ?
              )
            ORDER BY last_validated_at DESC, record_id
            LIMIT 1
            """,
            (source_ref,),
        ).fetchone()
        if row is not None:
            result[source_ref] = row
    return result


def _calibration_mutated_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        con.execute(
            """
            SELECT * FROM deep_research_records
            WHERE status IN ('valid', 'needs_revalidation')
              AND superseded_by_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM json_each(deep_research_records.source_case_refs)
                  WHERE json_each.value = ?
              )
              AND EXISTS (
                  SELECT 1 FROM json_each(deep_research_records.component_keys)
                  WHERE json_each.value = ?
              )
            """,
            (MUTATED_RATHPITH_SOURCE, MUTATED_RATHPITH_COMPONENT),
        ).fetchall()
    )


def _apply_support_calibration(
    con: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    source_ref: str,
    spec: dict[str, Any],
    now: str,
) -> tuple[str, str]:
    old_record_id = str(row["record_id"])
    old_knowledge_key = str(row["knowledge_key"] or "")
    protection = _legacy_mutation_issue(con, row)
    if protection:
        raise ValueError(f"support_calibration_unsafe_target: {protection}")
    evidence_rows = con.execute(
        """
        SELECT * FROM deep_research_record_evidence
        WHERE knowledge_scope = ? AND source_case_ref = ? AND knowledge_key = ?
          AND game_patch = ? AND passive_tree_version = ?
          AND (record_id = ? OR record_id IS NULL)
        """,
        (row["knowledge_scope"], source_ref, old_knowledge_key,
         row["game_patch"], row["passive_tree_version"], old_record_id),
    ).fetchall()
    if len(evidence_rows) > 1:
        raise ValueError("support_calibration_ambiguous_source_claim")
    evidence = evidence_rows[0] if evidence_rows else None
    mentions = _loads(
        evidence["observed_component_mentions"] if evidence else row["component_mentions"],
        [],
    )
    support_names = dict(spec["extraSupports"])
    existing_supports = {
        str(item.get("component_key") or "")
        for item in mentions
        if isinstance(item, dict) and item.get("role") == "support_modifier"
    }
    required_supports = {
        support_key
        for support_keys in spec["supportPackages"].values()
        for support_key in support_keys
    }
    for support_key in sorted(required_supports - existing_supports):
        mentions.append(
            {
                "candidate_name": support_names.get(support_key, support_key.rsplit("/", 1)[-1]),
                "role": "support_modifier",
                "resolver_query": support_key,
                "expected_node_types": ["support_gem"],
                "scope": "any",
                "component_key": support_key,
                "resolution_status": "resolved",
            }
        )
    typed_payload = _loads(row["typed_payload"], {})
    typed_payload.pop("familyCoreSkillKeys", None)
    typed_payload["supportPackages"] = [
        {"skillKey": skill_key, "supportKeys": sorted(set(support_keys))}
        for skill_key, support_keys in sorted(spec["supportPackages"].items())
    ]
    component_keys = sorted(
        set(
            _loads(
                evidence["observed_component_keys"] if evidence else row["component_keys"],
                [],
            )
        )
        | required_supports
    )
    record_fields = spec.get("recordFields") or {}
    safe_evidence_refs = _loads(
        evidence["safe_evidence_refs"] if evidence else row["safe_evidence_refs"], []
    )
    conditions = _loads(evidence["conditions"] if evidence else row["conditions"], [])
    failure_conditions = _loads(
        evidence["failure_conditions"] if evidence else row["failure_conditions"], []
    )
    proposal_payload = {
        "research_group_id": "research:case:poe-bd-research-" + source_ref.split(":", 1)[1],
        "record_kind": row["record_kind"],
        "title": record_fields.get("title", row["title"]),
        "summary": record_fields.get("summary", row["summary"]),
        "content": record_fields.get("content", row["content"]),
        "content_language": row["content_language"],
        "length_exception_reason": row["length_exception_reason"],
        "component_keys": component_keys,
        "component_mentions": mentions,
        "source_case_refs": [source_ref],
        "safe_evidence_refs": safe_evidence_refs,
        "conditions": conditions,
        "failure_conditions": failure_conditions,
        "typed_payload": typed_payload,
        "class_key": row["class_key"],
        "ascendancy_key": row["ascendancy_key"],
        "extraction_method_version": row["extraction_method_version"],
        "record_schema_version": int(row["record_schema_version"]),
        "game_patch": row["game_patch"],
        "passive_tree_version": row["passive_tree_version"],
        "pob_version_or_commit": row["pob_version_or_commit"],
        "visibility": row["visibility"],
        "split": row["split"],
        "knowledge_scope": row["knowledge_scope"],
        "status": row["status"],
        "copy_safety_state": row["copy_safety_state"],
    }
    proposal = research_models.DeepResearchRecordProposal.model_validate(proposal_payload)
    family = research_identity.infer_build_family([proposal])
    if family is None:
        raise ValueError(f"cannot infer calibrated Family for {source_ref}")
    new_knowledge_key = research_identity.knowledge_key(proposal, family)
    if new_knowledge_key is None:
        raise ValueError(f"cannot infer calibrated knowledge key for {source_ref}")
    old_knowledge_key = str(row["knowledge_key"] or "")
    record_id = research_runtime.canonical_record_id(proposal.knowledge_scope, new_knowledge_key)
    if con.execute(
        "SELECT 1 FROM deep_research_records WHERE knowledge_scope = ? AND knowledge_key = ? "
        "AND record_id != ? AND superseded_by_id IS NULL LIMIT 1",
        (proposal.knowledge_scope, new_knowledge_key, old_record_id),
    ).fetchone():
        raise ValueError("support_calibration_target_conclusion_occupied")
    values = research_memory.ResearchMemoryService(initialize_store=False)._deep_record_values(
        proposal,
        record_id=record_id,
        build_family_key=family.key,
        knowledge_key=new_knowledge_key,
        evidence_count=1,
        now=now,
    )
    existing = con.execute(
        "SELECT * FROM deep_research_records WHERE record_id = ?", (record_id,)
    ).fetchone()
    if existing is not None and (
        str(existing["record_id"]) != old_record_id
        or _legacy_mutation_issue(con, existing)
    ):
        raise ValueError("support_calibration_target_conclusion_occupied")
    if existing is not None:
        values["created_at"] = existing["created_at"]
    columns = tuple(values)
    if existing is None:
        con.execute(
            f"INSERT INTO deep_research_records({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )
    else:
        updates = [column for column in columns if column != "record_id"]
        con.execute(
            "UPDATE deep_research_records SET " + ",".join(f"{column}=?" for column in updates)
            + " WHERE record_id=?", (*(values[column] for column in updates), record_id),
        )
    first_seen_at = evidence["first_seen_at"] if evidence else row["created_at"]
    con.execute(
        "DELETE FROM deep_research_record_evidence WHERE knowledge_scope = ? "
        "AND source_case_ref = ? AND knowledge_key = ? AND source_claim_key = ? "
        "AND game_patch = ? AND passive_tree_version = ?",
        (proposal.knowledge_scope, source_ref, old_knowledge_key,
         evidence["source_claim_key"] if evidence else "default",
         row["game_patch"], row["passive_tree_version"]),
    )
    con.execute(
        """
        INSERT INTO deep_research_record_evidence(
            knowledge_scope, knowledge_key, source_case_ref, safe_evidence_refs,
            observed_component_keys, observed_component_mentions, conditions,
            failure_conditions, game_patch, passive_tree_version,
            pob_version_or_commit, accepted_projection_hash, source_state_scope,
            first_seen_at, last_seen_at, source_claim_key, record_id, binding_issue
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'unknown', ?, ?, ?, NULL,
                  'maintenance_requires_revalidation')
        ON CONFLICT(knowledge_scope, knowledge_key, source_case_ref, source_claim_key,
                    game_patch, passive_tree_version) DO UPDATE SET
            safe_evidence_refs = excluded.safe_evidence_refs,
            observed_component_keys = excluded.observed_component_keys,
            observed_component_mentions = excluded.observed_component_mentions,
            conditions = excluded.conditions,
            failure_conditions = excluded.failure_conditions,
            record_id = NULL, binding_issue = 'maintenance_requires_revalidation',
            accepted_projection_hash = NULL, source_state_scope = 'unknown',
            last_seen_at = excluded.last_seen_at
        """,
        (
            proposal.knowledge_scope,
            new_knowledge_key,
            source_ref,
            _json(safe_evidence_refs),
            _json(component_keys),
            _json(mentions),
            _json(conditions),
            _json(failure_conditions),
            row["game_patch"],
            row["passive_tree_version"],
            row["pob_version_or_commit"],
            first_seen_at,
            now,
            evidence["source_claim_key"] if evidence else "default",
        ),
    )
    return old_record_id, record_id


def _legacy_fragment_supersessions(con: sqlite3.Connection) -> dict[str, str]:
    rows = list(
        con.execute(
            """
            SELECT * FROM research_fragments
            WHERE visibility = 'creator_visible'
              AND split = 'train_context'
              AND status IN ('valid', 'needs_revalidation')
            ORDER BY created_at, fragment_id
            """
        ).fetchall()
    )
    supersessions: dict[str, str] = {}
    exact_groups: dict[tuple[tuple[str, ...], tuple[str, ...], str], list[sqlite3.Row]] = {}
    for row in rows:
        key = (
            tuple(sorted(_loads(row["source_case_refs"], []))),
            tuple(sorted(_loads(row["component_keys"], []))),
            _normalized_title(str(row["title"])),
        )
        exact_groups.setdefault(key, []).append(row)
    for group in exact_groups.values():
        if len(group) < 2:
            continue
        canonical = max(group, key=_fragment_quality)
        for row in group:
            if row["fragment_id"] != canonical["fragment_id"]:
                supersessions[str(row["fragment_id"])] = str(canonical["fragment_id"])

    nonempty_by_sources: dict[tuple[str, ...], list[sqlite3.Row]] = {}
    for row in rows:
        if _loads(row["component_keys"], []):
            sources = tuple(sorted(_loads(row["source_case_refs"], [])))
            nonempty_by_sources.setdefault(sources, []).append(row)
    for row in rows:
        if _loads(row["component_keys"], []):
            continue
        sources = tuple(sorted(_loads(row["source_case_refs"], [])))
        title = _normalized_title(str(row["title"])).removesuffix("endpoint待审")
        candidates = [
            candidate
            for candidate in nonempty_by_sources.get(sources, [])
            if _titles_overlap(title, _normalized_title(str(candidate["title"])))
        ]
        if candidates:
            replacement = max(candidates, key=_fragment_quality)
            supersessions[str(row["fragment_id"])] = str(replacement["fragment_id"])
    return _collapse_supersessions(supersessions)


def _apply_fragment_supersessions(
    con: sqlite3.Connection,
    supersessions: dict[str, str],
    now: str,
) -> None:
    duplicates_by_canonical: dict[str, list[str]] = {}
    for duplicate, canonical in supersessions.items():
        duplicates_by_canonical.setdefault(canonical, []).append(duplicate)
    for canonical_id, duplicate_ids in duplicates_by_canonical.items():
        placeholders = ",".join("?" for _ in duplicate_ids)
        rows = list(
            con.execute(
                f"""
                SELECT * FROM research_fragments
                WHERE fragment_id = ? OR fragment_id IN ({placeholders})
                """,
                (canonical_id, *duplicate_ids),
            ).fetchall()
        )
        source_refs = sorted({item for row in rows for item in _loads(row["source_case_refs"], [])})
        safe_refs = sorted({item for row in rows for item in _loads(row["safe_evidence_refs"], [])})
        evidence_count = max(int(row["evidence_count"] or 0) for row in rows)
        con.execute(
            """
            UPDATE research_fragments
            SET source_case_refs = ?, safe_evidence_refs = ?, evidence_count = ?, last_seen_at = ?
            WHERE fragment_id = ?
            """,
            (_json(source_refs), _json(safe_refs), evidence_count, now, canonical_id),
        )
        con.execute(
            f"""
            UPDATE research_fragments
            SET status = 'deprecated', superseded_by_id = ?, last_seen_at = ?
            WHERE fragment_id IN ({placeholders})
            """,
            (canonical_id, now, *duplicate_ids),
        )


def _backup_database(
    con: sqlite3.Connection,
    database_path: Path,
    backup_path: Path | None,
    *,
    marker: str = LEGACY_CLEANUP_MARKER,
) -> Path:
    if backup_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = database_path.with_name(
            f"{database_path.stem}.pre-{marker}-{stamp}{database_path.suffix}"
        )
    resolved = Path(backup_path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists():
        raise FileExistsError(f"backup already exists: {resolved}")
    destination = sqlite3.connect(resolved)
    try:
        con.backup(destination)
    finally:
        destination.close()
    return resolved


def _fragment_quality(row: sqlite3.Row) -> tuple[int, int, int, str]:
    return (
        int(row["evidence_count"] or 0),
        len(_loads(row["safe_evidence_refs"], [])),
        len(_loads(row["component_keys"], [])),
        str(row["fragment_id"]),
    )


def _collapse_supersessions(supersessions: dict[str, str]) -> dict[str, str]:
    collapsed: dict[str, str] = {}
    for duplicate, target in supersessions.items():
        visited = {duplicate}
        while target in supersessions and target not in visited:
            visited.add(target)
            target = supersessions[target]
        collapsed[duplicate] = target
    return collapsed


def _titles_overlap(left: str, right: str) -> bool:
    return bool(left and right and (left.startswith(right) or right.startswith(left)))


def _normalized_title(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _loads(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(value: Any) -> str:
    import hashlib

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
