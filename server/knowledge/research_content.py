"""Shared immutable Research content with the legacy authorization-row projection.

The public SQL view deliberately has exactly the pre-migration columns.  Record IDs,
version evidence, and review fingerprints continue to identify authorization rows;
sharing a content revision never grants another row's evidence or permissions.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Sequence

from . import research_runtime

CONTENT_FIELDS = (
    "title",
    "summary",
    "content",
    "component_keys",
    "component_mentions",
    "conditions",
    "failure_conditions",
    "typed_payload",
)
REVISIONS = "research_content_revisions"
BINDINGS = "deep_research_record_bindings"
VIEW = "deep_research_records"


def installed(con: sqlite3.Connection) -> bool:
    objects = dict(
        con.execute(
            "SELECT name, type FROM sqlite_master WHERE name IN (?, ?, ?)",
            (REVISIONS, BINDINGS, VIEW),
        ).fetchall()
    )
    triggers = {
        row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    }
    indexes = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    binding_fields = {row[1] for row in con.execute(f"PRAGMA table_info({BINDINGS})")}
    content_fields = {row[1] for row in con.execute(f"PRAGMA table_info({REVISIONS})")}
    return (
        objects == {REVISIONS: "table", BINDINGS: "table", VIEW: "view"}
        and {
            "research_content_insert",
            "research_content_update",
            "research_content_delete",
            "research_content_gc_update",
            "research_content_gc_delete",
        }
        <= triggers
        and {"idx_research_content_lookup", "idx_research_content_binding"} <= indexes
        and {"record_id", "content_revision_id", "knowledge_scope", "game_patch", "projection_hash"}
        <= binding_fields
        and {"revision_id", *CONTENT_FIELDS} <= content_fields
    )


def unit_key_sql(alias: str) -> str:
    """Internal SQL expression; alias is chosen by repository code, never a tool caller."""
    fields = (
        "knowledge_scope",
        "build_family_key",
        "record_kind",
        "record_schema_version",
        "class_key",
        "ascendancy_key",
        "content_language",
        "source_state_scope",
        "status",
    )
    return (
        "json_array("
        + ",".join(f"{alias}.{field}" for field in fields)
        + (
            f",(SELECT content_revision_id FROM {BINDINGS} AS content_binding "
            f"WHERE content_binding.record_id={alias}.record_id))"
        )
    )


def migrate(con: sqlite3.Connection, *, invalidate_receipts: bool = True) -> None:
    """Run inside the caller's backed-up schema transaction; do not commit here."""
    if installed(con):
        return
    table = con.execute("SELECT sql, type FROM sqlite_master WHERE name=?", (VIEW,)).fetchone()
    if table is None or table["type"] != "table":
        raise ValueError("research_content_legacy_table_required")
    info = list(con.execute(f"PRAGMA table_info({VIEW})"))
    columns = [str(row["name"]) for row in info]
    metadata = [name for name in columns if name not in CONTENT_FIELDS]
    indexes = [
        str(row[0])
        for row in con.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
            (VIEW,),
        )
    ]
    con.execute(
        f"CREATE TABLE {REVISIONS} (revision_id INTEGER PRIMARY KEY, "
        + ", ".join(f"{name} TEXT NOT NULL" for name in CONTENT_FIELDS)
        + ")"
    )
    # Avoid a full-body UNIQUE index that would itself store another copy of every body.
    # SQLite serializes writers; the trigger's exact-match insert is atomic.
    con.execute(f"CREATE INDEX idx_research_content_lookup ON {REVISIONS}(title, length(content))")
    original_sql = str(table["sql"])
    binding_sql = re.sub(
        r"CREATE TABLE\s+\"?deep_research_records\"?",
        f"CREATE TABLE {BINDINGS}",
        original_sql,
        count=1,
        flags=re.IGNORECASE,
    )
    for field in CONTENT_FIELDS:
        binding_sql = re.sub(rf"(?m)^\s*{field}\s+[^\n]+,\s*$", "", binding_sql)
    binding_sql = binding_sql.replace(
        "(", f"(content_revision_id INTEGER NOT NULL REFERENCES {REVISIONS}(revision_id),", 1
    )
    con.execute(binding_sql)
    match = " AND ".join(f"{name} IS ?" for name in CONTENT_FIELDS)
    for row in con.execute(f"SELECT * FROM {VIEW}").fetchall():
        values = tuple(row[name] for name in CONTENT_FIELDS)
        revision = con.execute(
            f"SELECT revision_id FROM {REVISIONS} WHERE {match}", values
        ).fetchone()
        if revision is None:
            revision_id = con.execute(
                f"INSERT INTO {REVISIONS}({', '.join(CONTENT_FIELDS)}) VALUES ({','.join('?' for _ in values)})",
                values,
            ).lastrowid
        else:
            revision_id = revision[0]
        con.execute(
            f"INSERT INTO {BINDINGS}(content_revision_id,{','.join(metadata)}) "
            f"VALUES ({','.join('?' for _ in range(len(metadata) + 1))})",
            (revision_id, *(row[name] for name in metadata)),
        )
    con.execute(f"DROP TABLE {VIEW}")
    for sql in indexes:
        con.execute(re.sub(r'(?i)(\bON\s+)"?deep_research_records"?', rf"\g<1>{BINDINGS}", sql))
    con.execute(f"CREATE INDEX idx_research_content_binding ON {BINDINGS}(content_revision_id)")
    projection = ", ".join(
        f"{'content' if name in CONTENT_FIELDS else 'binding'}.{name} AS {name}" for name in columns
    )
    con.execute(
        f"CREATE VIEW {VIEW} AS SELECT {projection} FROM {BINDINGS} AS binding "
        f"JOIN {REVISIONS} AS content ON content.revision_id=binding.content_revision_id"
    )
    defaults = {str(row["name"]): row["dflt_value"] for row in info}
    for operation in ("INSERT", "UPDATE"):

        def new_value(name: str) -> str:
            default = defaults[name] if operation == "INSERT" else None
            return f"COALESCE(NEW.{name}, {default})" if default is not None else f"NEW.{name}"

        content_values = ", ".join(new_value(name) for name in CONTENT_FIELDS)
        new_match = " AND ".join(f"{name} IS {new_value(name)}" for name in CONTENT_FIELDS)
        revision_select = f"SELECT revision_id FROM {REVISIONS} WHERE {new_match} LIMIT 1"
        intern = (
            f"INSERT INTO {REVISIONS}({','.join(CONTENT_FIELDS)}) SELECT {content_values} "
            f"WHERE NOT EXISTS ({revision_select});"
        )
        if operation == "INSERT":
            write = (
                f"INSERT INTO {BINDINGS}(content_revision_id,{','.join(metadata)}) "
                f"VALUES (({revision_select}),{','.join(new_value(name) for name in metadata)});"
            )
        else:
            assignments = ",".join(f"{name}=NEW.{name}" for name in metadata)
            write = (
                f"UPDATE {BINDINGS} SET content_revision_id=({revision_select}),{assignments} "
                "WHERE record_id=OLD.record_id;"
            )
        con.execute(
            f"CREATE TRIGGER research_content_{operation.lower()} INSTEAD OF {operation} ON {VIEW} "
            f"BEGIN {intern} {write} END"
        )
    con.execute(
        f"CREATE TRIGGER research_content_delete INSTEAD OF DELETE ON {VIEW} BEGIN "
        f"DELETE FROM {BINDINGS} WHERE record_id=OLD.record_id; END"
    )
    # Deleting or revising the last binding also removes unreachable private/rejected content.
    for operation in ("DELETE", "UPDATE OF content_revision_id"):
        name = "delete" if operation == "DELETE" else "update"
        con.execute(
            f"CREATE TRIGGER research_content_gc_{name} AFTER {operation} ON {BINDINGS} BEGIN "
            f"DELETE FROM {REVISIONS} WHERE revision_id=OLD.content_revision_id "
            f"AND NOT EXISTS (SELECT 1 FROM {BINDINGS} WHERE content_revision_id=OLD.content_revision_id); END"
        )
    if invalidate_receipts:
        research_runtime.bump_memory_revision(con)


def content_ref(row: Any) -> str:
    return (
        "kcr-"
        + research_runtime.stable_hash(
            {
                "contentSchemaVersion": 1,
                **{key: row[key] for key in CONTENT_FIELDS},
            }
        )[:24]
    )


def select_distinct(
    con: sqlite3.Connection,
    sql: str,
    params: Sequence[Any],
    *,
    target_patch: str | None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Fold exact content only after the caller's permission/source/version filtering.

    Keep all legacy columns, and choose the same representative for coverage, detail,
    and execution. Explicit record-ID reads can bypass this function.
    """
    columns = [str(row["name"]) for row in con.execute(f"PRAGMA table_info({VIEW})")]
    partition = (
        unit_key_sql("eligible") + ", research_patch_adoptable(record_id, projection_hash, ?)"
    )
    order = "(game_patch = ?) DESC, evidence_count DESC, last_validated_at DESC, record_id"
    query = (
        f"WITH eligible AS ({sql}), ranked AS (SELECT eligible.*, ROW_NUMBER() OVER "
        f"(PARTITION BY {partition} ORDER BY {order}) AS content_rank FROM eligible) "
        f"SELECT {','.join(columns)} FROM ranked WHERE content_rank=1 ORDER BY {order}"
    )
    args = [*params, target_patch or "", target_patch or "", target_patch or ""]
    if limit is not None:
        query += " LIMIT ?"
        args.append(limit)
    return list(con.execute(query, args).fetchall())


def validate_storage(con: sqlite3.Connection) -> None:
    if not installed(con):
        raise ValueError("research_content_storage_incomplete")
    if con.execute(
        f"SELECT 1 FROM {REVISIONS} AS content WHERE NOT EXISTS "
        f"(SELECT 1 FROM {BINDINGS} WHERE content_revision_id=content.revision_id) LIMIT 1"
    ).fetchone():
        raise ValueError("research_content_orphan_revision")
    if con.execute(
        f"SELECT 1 FROM {BINDINGS} AS binding WHERE NOT EXISTS "
        f"(SELECT 1 FROM {REVISIONS} WHERE revision_id=binding.content_revision_id) LIMIT 1"
    ).fetchone():
        raise ValueError("research_content_missing_revision")
