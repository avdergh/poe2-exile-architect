"""Source-owned Research claims over shared, projection-bound knowledge records.

Structural migration preserves legacy record bodies and IDs.  An evidence row with
an unverifiable historical projection remains an explicit gap, never fresh proof.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from typing import Any

from . import patch_reviews, research_content, research_runtime

EVIDENCE = "deep_research_record_evidence"
CLAIM_FIELDS = ("source_claim_key", "record_id", "binding_issue")
DEFAULT_CLAIM_KEY = "default"
MIGRATION_REPORT_META_KEY = "research_claim_migration_v7_report"
MIGRATION_AUDIT_SCHEMA_VERSION = 1
_PRIMARY_KEY = (
    "knowledge_scope",
    "knowledge_key",
    "source_case_ref",
    "source_claim_key",
    "game_patch",
    "passive_tree_version",
)
_VERSION_FIELDS = ("game_patch", "passive_tree_version", "pob_version_or_commit")
DIAGNOSTIC_BINDING_ISSUES = frozenset({"legacy_record_schema", "source_state_unknown"})
BINDING_ISSUES = frozenset(
    {
        "missing_projection_hash",
        "record_missing",
        "projection_unavailable",
        "projection_ambiguous",
        "record_projection_mismatch",
        "source_reference_mismatch",
        "source_version_mismatch",
        "source_state_mismatch",
        "source_state_unknown",
        "legacy_record_schema",
        "record_retired",
        "merge_content_revised",
        "maintenance_requires_revalidation",
        "record_quarantined",
    }
)


def installed(con: sqlite3.Connection) -> bool:
    info = list(con.execute(f"PRAGMA table_info({EVIDENCE})"))
    columns = {row[1] for row in info}
    primary_key = tuple(row[1] for row in sorted(info, key=lambda row: row[5]) if row[5])
    indexes = {
        row[1]: row for row in con.execute(f"PRAGMA index_list({research_content.BINDINGS})")
    }
    topic_index = indexes.get("idx_deep_research_records_scope_knowledge")
    evidence_indexes = {row[1] for row in con.execute(f"PRAGMA index_list({EVIDENCE})")}
    return (
        set(CLAIM_FIELDS) <= columns
        and primary_key == _PRIMARY_KEY
        and topic_index is not None
        and not bool(topic_index[2])
        and _index_columns(con, "idx_deep_research_records_scope_knowledge")
        == ("knowledge_scope", "knowledge_key")
        and "idx_deep_research_record_evidence_record" in evidence_indexes
        and _index_columns(con, "idx_deep_research_record_evidence_record") == ("record_id",)
        and "idx_deep_research_record_evidence_lane" in evidence_indexes
        and _index_columns(con, "idx_deep_research_record_evidence_lane")
        == ("knowledge_scope", "source_case_ref", "knowledge_key")
    )


def _index_columns(con: sqlite3.Connection, index: str) -> tuple[str, ...]:
    return tuple(str(row[2]) for row in con.execute(f"PRAGMA index_info({index})"))


def _source_refs(record: Any) -> set[str]:
    try:
        values = json.loads(record["source_case_refs"])
    except (TypeError, ValueError):
        return set()
    return {str(value) for value in values} if isinstance(values, list) else set()


def _binding_issue(evidence: Any, record: Any) -> str | None:
    if record["projection_hash"] != research_runtime.projection_hash(record):
        return "record_projection_mismatch"
    if evidence["source_case_ref"] not in _source_refs(record):
        return "source_reference_mismatch"
    if any(evidence[field] != record[field] for field in _VERSION_FIELDS):
        return "source_version_mismatch"
    if evidence["source_state_scope"] != record["source_state_scope"]:
        return "source_state_mismatch"
    if int(record["record_schema_version"] or 1) < 2:
        return "legacy_record_schema"
    if evidence["source_state_scope"] == "unknown":
        return "source_state_unknown"
    return None


def _legacy_binding(con: sqlite3.Connection, evidence: Any) -> tuple[str | None, str | None]:
    accepted_hash = evidence["accepted_projection_hash"]
    if not accepted_hash:
        return None, "missing_projection_hash"
    candidates = list(
        con.execute(
            "SELECT * FROM deep_research_records WHERE knowledge_scope=? AND knowledge_key=? "
            "AND superseded_by_id IS NULL ORDER BY record_id",
            (evidence["knowledge_scope"], evidence["knowledge_key"]),
        )
    )
    if not candidates:
        return None, "record_missing"
    candidates = [row for row in candidates if row["projection_hash"] == accepted_hash]
    if not candidates:
        return None, "projection_unavailable"
    matches = [row for row in candidates if _binding_issue(evidence, row) is None]
    if len(matches) == 1:
        return str(matches[0]["record_id"]), None
    if len(matches) > 1:
        return None, "projection_ambiguous"
    return None, _binding_issue(evidence, candidates[0])


def _json_ref_set(value: Any) -> set[str]:
    try:
        refs = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("research_claim_reference_cache_invalid") from exc
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise ValueError("research_claim_reference_cache_invalid")
    return set(refs)


def _audit_ref(value: str) -> str:
    """Keep known opaque IDs, digest every other legacy label before recording it in an audit."""
    if re.fullmatch(
        r"(?:drr-[0-9a-f]{16,64}|(?:source-hash|case-hash|safe-hash|claim-hash):[0-9a-f]{12,64})",
        value,
    ):
        return value
    return "audit-ref:sha256:" + research_runtime.stable_hash({"legacyReference": value})


def _refresh_migrated_support_metadata(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Correct derived support caches without rewriting legacy claims or reviewed content."""
    records = con.execute(
        "SELECT * FROM deep_research_records AS record WHERE record_schema_version >= 2 "
        "AND EXISTS (SELECT 1 FROM deep_research_record_evidence AS evidence "
        "WHERE evidence.knowledge_scope=record.knowledge_scope "
        "AND evidence.knowledge_key=record.knowledge_key)"
    ).fetchall()
    corrections: list[dict[str, Any]] = []
    for record in records:
        evidence = con.execute(
            "SELECT source_case_ref,safe_evidence_refs FROM deep_research_record_evidence "
            "WHERE record_id=? AND knowledge_scope=? AND knowledge_key=? "
            "AND accepted_projection_hash=? AND binding_issue IS NULL "
            "AND game_patch=? AND passive_tree_version=? AND pob_version_or_commit=? "
            "AND source_state_scope=?",
            (
                record["record_id"],
                record["knowledge_scope"],
                record["knowledge_key"],
                record["projection_hash"],
                record["game_patch"],
                record["passive_tree_version"],
                record["pob_version_or_commit"],
                record["source_state_scope"],
            ),
        ).fetchall()
        sources = {row["source_case_ref"] for row in evidence}
        refs = {ref for row in evidence for ref in _json_ref_set(row["safe_evidence_refs"])}
        previous_sources = _json_ref_set(record["source_case_refs"])
        previous_refs = _json_ref_set(record["safe_evidence_refs"])
        if (
            previous_sources == sources
            and previous_refs == refs
            and int(record["evidence_count"]) == len(sources)
        ):
            continue
        con.execute(
            "UPDATE deep_research_records SET source_case_refs=?,safe_evidence_refs=?,"
            "evidence_count=? WHERE record_id=?",
            (
                json.dumps(sorted(sources), ensure_ascii=False, separators=(",", ":")),
                json.dumps(sorted(refs), ensure_ascii=False, separators=(",", ":")),
                len(sources),
                record["record_id"],
            ),
        )
        corrections.append(
            {
                "recordId": _audit_ref(str(record["record_id"])),
                "removedSourceCaseRefs": sorted(
                    _audit_ref(ref) for ref in previous_sources - sources
                ),
                "removedSafeEvidenceRefs": sorted(_audit_ref(ref) for ref in previous_refs - refs),
                "previousEvidenceCount": int(record["evidence_count"]),
                "currentEvidenceCount": len(sources),
            }
        )
    return sorted(corrections, key=lambda item: item["recordId"])


def migrate(con: sqlite3.Connection, *, invalidate_receipts: bool = True) -> dict[str, Any]:
    """Migrate inside the caller's backed-up transaction, without committing."""
    if installed(con):
        return {
            "schemaVersion": MIGRATION_AUDIT_SCHEMA_VERSION,
            "targetDatabaseSchemaVersion": 7,
            "status": "already_applied",
            "boundClaims": 0,
            "gapClaims": 0,
            "bindingIssues": {},
            "derivedMetadataCorrectedCount": 0,
            "derivedMetadataCorrections": [],
        }
    if not research_content.installed(con):
        raise ValueError("research_claim_content_storage_required")
    old_info = list(con.execute(f"PRAGMA table_info({EVIDENCE})"))
    old_columns = [str(row[1]) for row in old_info]
    if set(CLAIM_FIELDS) & set(old_columns):
        raise ValueError("research_claim_partial_schema")
    original_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        # Only reviews whose original fingerprint still matches are upgraded by this helper.
        patch_reviews.install_schema(con)
        legacy_rows = list(con.execute(f"SELECT * FROM {EVIDENCE}"))
        bindings = [(row, *_legacy_binding(con, row)) for row in legacy_rows]
        con.execute(f"ALTER TABLE {EVIDENCE} RENAME TO {EVIDENCE}_v6")
        columns_sql = []
        for row in old_info:
            definition = f"{row[1]} {row[2]}"
            if row[3]:
                definition += " NOT NULL"
            if row[4] is not None:
                definition += f" DEFAULT {row[4]}"
            columns_sql.append(definition)
        columns_sql.extend(
            [
                "source_claim_key TEXT NOT NULL DEFAULT 'default'",
                "record_id TEXT",
                "binding_issue TEXT",
                f"PRIMARY KEY ({','.join(_PRIMARY_KEY)})",
            ]
        )
        con.execute(f"CREATE TABLE {EVIDENCE} ({','.join(columns_sql)})")
        insert_columns = [*old_columns, *CLAIM_FIELDS]
        insert_sql = (
            f"INSERT INTO {EVIDENCE} ({','.join(insert_columns)}) "
            f"VALUES ({','.join('?' for _ in insert_columns)})"
        )
        for row, record_id, issue in bindings:
            con.execute(
                insert_sql,
                (*(row[column] for column in old_columns), DEFAULT_CLAIM_KEY, record_id, issue),
            )
        con.execute(f"DROP TABLE {EVIDENCE}_v6")
        con.execute("DROP INDEX IF EXISTS idx_deep_research_records_scope_knowledge")
        con.execute(
            f"CREATE INDEX idx_deep_research_records_scope_knowledge ON {research_content.BINDINGS}"
            "(knowledge_scope, knowledge_key) WHERE knowledge_key IS NOT NULL AND superseded_by_id IS NULL"
        )
        con.execute(
            f"CREATE INDEX idx_deep_research_record_evidence_lane ON {EVIDENCE}"
            "(knowledge_scope, source_case_ref, knowledge_key)"
        )
        con.execute(
            f"CREATE INDEX idx_deep_research_record_evidence_record ON {EVIDENCE}(record_id)"
        )
        corrections = _refresh_migrated_support_metadata(con)
        if invalidate_receipts:
            research_runtime.bump_memory_revision(con)
        issues = Counter(issue for _, _, issue in bindings if issue is not None)
        report = {
            "schemaVersion": MIGRATION_AUDIT_SCHEMA_VERSION,
            "targetDatabaseSchemaVersion": 7,
            "status": "migrated",
            "claimCount": len(bindings),
            "boundClaims": len(bindings) - sum(issues.values()),
            "gapClaims": sum(issues.values()),
            "bindingIssues": dict(sorted(issues.items())),
            "derivedMetadataCorrectedCount": len(corrections),
            "derivedMetadataCorrections": corrections,
        }
        con.execute(
            "INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (
                MIGRATION_REPORT_META_KEY,
                json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
        return report
    finally:
        con.row_factory = original_factory


def validate_storage(con: sqlite3.Connection, *, release: bool = False) -> None:
    """Validate explicit bindings without granting legacy or unknown-state claims authority.

    New writes may retain a structurally exact diagnostic record pointer.  Its issue
    must explain the actual qualification gap, and never excuses a bad hash, source,
    scope, version, or state binding.  Migration still leaves such old claims unbound.
    """
    if not installed(con):
        raise ValueError("research_claim_storage_incomplete")
    original_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        for evidence in con.execute(f"SELECT * FROM {EVIDENCE}").fetchall():
            if not str(evidence["source_claim_key"] or "").strip():
                raise ValueError("research_claim_key_missing")
            record_id, issue = evidence["record_id"], evidence["binding_issue"]
            if record_id is None:
                if issue not in BINDING_ISSUES:
                    raise ValueError("research_claim_gap_reason_missing")
                if release:
                    raise ValueError("research_release_claim_unbound")
                continue
            if issue is not None and issue not in DIAGNOSTIC_BINDING_ISSUES:
                raise ValueError("research_claim_bound_with_gap")
            if issue is not None and release:
                raise ValueError("research_release_claim_diagnostic_only")
            record = con.execute(
                "SELECT * FROM deep_research_records WHERE record_id=?", (record_id,)
            ).fetchone()
            if record is None:
                raise ValueError("research_claim_record_missing")
            if (
                evidence["knowledge_scope"] != record["knowledge_scope"]
                or evidence["knowledge_key"] != record["knowledge_key"]
                or not evidence["accepted_projection_hash"]
                or evidence["accepted_projection_hash"] != record["projection_hash"]
            ):
                raise ValueError("research_claim_binding_mismatch")
            actual_issue = _binding_issue(evidence, record)
            if actual_issue != issue:
                raise ValueError("research_claim_" + (actual_issue or "diagnostic_issue_mismatch"))
    finally:
        con.row_factory = original_factory


def has_variants(con: sqlite3.Connection, scope: str | None = None) -> bool:
    """Whether legacy maintenance would conflate independent active conclusions."""
    scope_sql = " AND knowledge_scope=?" if scope is not None else ""
    return (
        con.execute(
            "SELECT 1 FROM deep_research_records WHERE knowledge_key IS NOT NULL "
            "AND superseded_by_id IS NULL"
            + scope_sql
            + " GROUP BY knowledge_scope, knowledge_key HAVING count(*) > 1 LIMIT 1",
            (scope,) if scope is not None else (),
        ).fetchone()
        is not None
    )
