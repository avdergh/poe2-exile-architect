"""Small shared primitives for versioned Research writes and retrievals."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from . import research_contracts


CREATE_VISIBLE_PROJECTION_FIELDS = (
    "title",
    "summary",
    "content",
    "component_keys",
    "component_mentions",
    "conditions",
    "failure_conditions",
    "typed_payload",
    "record_kind",
    "record_schema_version",
    "game_patch",
    "passive_tree_version",
    "pob_version_or_commit",
    "visibility",
    "split",
    "knowledge_scope",
    "status",
    "copy_safety_state",
    "source_state_scope",
)


def research_write_lock_path(db_path: str | Path) -> Path:
    path = Path(db_path).resolve()
    return path.with_name(f".{path.name}.research-accept.lock")


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def create_visible_projection(value: Mapping[str, Any] | sqlite3.Row) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    keys = set(value.keys())
    for field in CREATE_VISIBLE_PROJECTION_FIELDS:
        if field not in keys:
            continue
        raw = value[field]
        if field in {
            "component_keys",
            "component_mentions",
            "conditions",
            "failure_conditions",
            "typed_payload",
        } and isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                pass
        projection[field] = raw
    return projection


def projection_hash(value: Mapping[str, Any] | sqlite3.Row) -> str:
    return stable_hash(create_visible_projection(value))


def source_state_scope(value: Any) -> str:
    normalized = str(value or "unknown").strip()
    return normalized if normalized in research_contracts.SOURCE_STATE_SCOPES else "unknown"


def get_memory_revision(con: sqlite3.Connection) -> int:
    row = con.execute("SELECT value FROM meta WHERE key = 'research_memory_revision'").fetchone()
    try:
        return int(row[0]) if row else 0
    except (TypeError, ValueError):
        return 0


def bump_memory_revision(con: sqlite3.Connection) -> int:
    revision = get_memory_revision(con) + 1
    con.execute(
        """
        INSERT INTO meta(key, value) VALUES ('research_memory_revision', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (str(revision),),
    )
    return revision


def write_receipt_ref(run_ref: str, sample_id: str) -> str:
    return "rwr-" + stable_hash({"runRef": run_ref, "sampleId": sample_id})[:20]


def accept_attempt_key(
    *,
    run_id: str,
    sample_id: str,
    packet_safe_hash: str,
    canonical_review_hash: str,
    contract_version: str,
    expected_origin_state: str,
) -> str:
    return (
        "raa-"
        + stable_hash(
            {
                "runId": run_id,
                "sampleId": sample_id,
                "packetSafeHash": packet_safe_hash,
                "canonicalReviewHash": canonical_review_hash,
                "contractVersion": contract_version,
                "expectedOriginState": expected_origin_state,
            }
        )[:24]
    )


def canonical_record_id(knowledge_scope: str, knowledge_key: str) -> str:
    if knowledge_scope == "global_seed":
        return "drr-" + stable_hash({"knowledge_key": knowledge_key})[:16]
    return (
        "drr-"
        + stable_hash({"knowledge_scope": knowledge_scope, "knowledge_key": knowledge_key})[:16]
    )


def is_create_authorizing_state(value: Any) -> bool:
    return source_state_scope(value) in research_contracts.CREATE_AUTHORIZING_SOURCE_STATE_SCOPES
