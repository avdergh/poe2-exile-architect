"""Raw-free reservations for explicitly targeted Research reacquisition.

This state machine neither collects sources nor judges research completeness.
The workflow must verify a child run has no live lease or accepting transaction
before releasing/finalizing its reservation. Time alone never frees a scope.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
from typing import Any

from .. import paths


SCHEMA_VERSION = 1
LEDGER_FILENAME = "reacquisition.sqlite"
_PATTERNS = {
    "league": r"[a-z0-9][a-z0-9_-]{0,119}",
    "character_ref": r"character-hash:[0-9a-f]{16}",
    "parent_run_ref": r"research-run:[A-Za-z0-9][A-Za-z0-9_-]{0,159}",
    "new_run_ref": r"research-run:[A-Za-z0-9][A-Za-z0-9_-]{0,159}",
    "sample_id": r"case:[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}",
    "origin_fingerprint": r"[0-9a-f]{64}",
    "request_id": r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}",
    "origin_source_hash": r"[0-9a-f]{64}",
    "source_hash": r"[0-9a-f]{64}",
    "origin_patch": r"[0-9][A-Za-z0-9_.-]{0,39}",
    "source_patch": r"[0-9][A-Za-z0-9_.-]{0,39}",
    "reason_code": r"[a-z][a-z0-9_]{0,79}",
}
_BINDING_FIELDS = (
    "league", "character_ref", "parent_run_ref", "sample_id", "origin_fingerprint",
    "request_id", "new_run_ref", "origin_source_hash", "origin_patch",
)
_PUBLIC_FIELDS = {
    "league": "league", "character_ref": "characterRef", "parent_run_ref": "parentRunRef",
    "sample_id": "sampleId", "origin_fingerprint": "originFingerprint",
    "request_id": "requestId", "new_run_ref": "newRunRef",
    "origin_source_hash": "originSourceHash", "origin_patch": "originPatch",
    "source_hash": "sourceHash", "source_patch": "sourcePatch", "relation": "sourceRelation",
    "status": "status", "reason_code": "reasonCode", "created_at": "createdAt",
    "updated_at": "updatedAt",
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reservations (
    request_id TEXT PRIMARY KEY,
    league TEXT NOT NULL,
    character_ref TEXT NOT NULL,
    parent_run_ref TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    origin_fingerprint TEXT NOT NULL,
    new_run_ref TEXT NOT NULL UNIQUE,
    origin_source_hash TEXT NOT NULL,
    origin_patch TEXT NOT NULL,
    source_hash TEXT NOT NULL DEFAULT '',
    source_patch TEXT NOT NULL DEFAULT '',
    relation TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('reserved', 'queued', 'failed', 'completed')),
    reason_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS active_reacquisition_scope
    ON reservations(league, character_ref) WHERE status IN ('reserved', 'queued');
CREATE TABLE IF NOT EXISTS reservation_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL REFERENCES reservations(request_id),
    status TEXT NOT NULL,
    reason_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


class ReacquisitionConflict(ValueError):
    """A request, source scope or child-run binding is already owned."""


def default_ledger_path() -> Path:
    return paths.research_runtime_dir() / LEDGER_FILENAME


def _validated(**values: str) -> dict[str, str]:
    for name, value in values.items():
        if not isinstance(value, str) or re.fullmatch(_PATTERNS[name], value) is None:
            raise ValueError(f"invalid safe reacquisition field: {name}")
    if values.get("league") in {"current", "latest"}:
        raise ValueError("reacquisition requires a resolved league identity")
    return values


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: str | Path) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=30)) as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key,value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if version is None or version[0] != str(SCHEMA_VERSION):
            raise ValueError("unsupported research reacquisition schema")
        conn.commit()


def _public(row: sqlite3.Row, *, idempotent: bool = False) -> dict[str, Any]:
    return {
        **{name: row[column] for column, name in _PUBLIC_FIELDS.items()},
        "idempotent": idempotent,
    }


def _event(conn: sqlite3.Connection, request_id: str, status: str, reason: str, now: str) -> None:
    conn.execute(
        "INSERT INTO reservation_events(request_id,status,reason_code,created_at) VALUES(?,?,?,?)",
        (request_id, status, reason, now),
    )


def reserve(
    db_path: str | Path,
    *,
    league: str,
    character_ref: str,
    parent_run_ref: str,
    sample_id: str,
    origin_fingerprint: str,
    request_id: str,
    new_run_ref: str,
    origin_source_hash: str,
    origin_patch: str,
) -> dict[str, Any]:
    """Atomically reserve one character. Reusing a terminal request does not retry it."""
    binding = _validated(
        league=league, character_ref=character_ref, parent_run_ref=parent_run_ref,
        sample_id=sample_id, origin_fingerprint=origin_fingerprint, request_id=request_id,
        new_run_ref=new_run_ref, origin_source_hash=origin_source_hash, origin_patch=origin_patch,
    )
    if parent_run_ref == new_run_ref:
        raise ValueError("reacquisition requires an independent child run")
    init_db(db_path)
    with closing(sqlite3.connect(db_path, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute("SELECT * FROM reservations WHERE request_id=?", (request_id,)).fetchone()
        if prior is not None:
            if any(prior[key] != value for key, value in binding.items()):
                raise ReacquisitionConflict("request_id already binds a different reacquisition")
            return _public(prior, idempotent=True)
        now = _now()
        try:
            conn.execute(
                "INSERT INTO reservations(" + ",".join(_BINDING_FIELDS)
                + ",status,created_at,updated_at) VALUES (" + ",".join("?" for _ in _BINDING_FIELDS)
                + ",'reserved',?,?)",
                (*[binding[key] for key in _BINDING_FIELDS], now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise ReacquisitionConflict("character scope or child run is already reserved") from exc
        _event(conn, request_id, "reserved", "", now)
        row = conn.execute("SELECT * FROM reservations WHERE request_id=?", (request_id,)).fetchone()
        conn.commit()
        return _public(row)


def get_request(db_path: str | Path, *, request_id: str) -> dict[str, Any] | None:
    _validated(request_id=request_id)
    if not Path(db_path).is_file():
        return None
    with closing(sqlite3.connect(db_path, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM reservations WHERE request_id=?", (request_id,)).fetchone()
        return _public(row) if row is not None else None


def list_requests(
    db_path: str | Path, *, parent_run_ref: str, sample_id: str | None = None
) -> list[dict[str, Any]]:
    _validated(parent_run_ref=parent_run_ref, **({"sample_id": sample_id} if sample_id is not None else {}))
    if not Path(db_path).is_file():
        return []
    with closing(sqlite3.connect(db_path, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM reservations WHERE parent_run_ref=?"
        args = [parent_run_ref]
        if sample_id is not None:
            query += " AND sample_id=?"
            args.append(sample_id)
        rows = conn.execute(query + " ORDER BY created_at,request_id", args).fetchall()
        return [_public(row) for row in rows]


def mark_queued(
    db_path: str | Path,
    *,
    request_id: str,
    new_run_ref: str,
    source_hash: str,
    source_patch: str,
    character_ref: str,
    league: str,
) -> dict[str, Any]:
    """Bind the collected source; a changed snapshot never upgrades its parent's evidence."""
    _validated(request_id=request_id, new_run_ref=new_run_ref, source_hash=source_hash,
               source_patch=source_patch, character_ref=character_ref, league=league)
    if not Path(db_path).is_file():
        raise ReacquisitionConflict("reacquisition request does not exist")
    with closing(sqlite3.connect(db_path, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = _bound_request(conn, request_id, new_run_ref)
        if row["league"] != league or row["character_ref"] != character_ref:
            raise ReacquisitionConflict("collected character differs from the reserved scope")
        if row["status"] in {"queued", "completed"}:
            if row["source_hash"] != source_hash or row["source_patch"] != source_patch:
                raise ReacquisitionConflict("collected snapshot differs from the bound source")
            return _public(row, idempotent=True)
        if row["status"] != "reserved":
            raise ReacquisitionConflict("terminal reservation cannot be queued again")
        relation = (
            "exact_source" if row["origin_source_hash"] == source_hash and row["origin_patch"] == source_patch
            else "successor_snapshot"
        )
        now = _now()
        conn.execute(
            "UPDATE reservations SET status='queued',source_hash=?,source_patch=?,relation=?,updated_at=? "
            "WHERE request_id=?", (source_hash, source_patch, relation, now, request_id),
        )
        _event(conn, request_id, "queued", "", now)
        row = conn.execute("SELECT * FROM reservations WHERE request_id=?", (request_id,)).fetchone()
        conn.commit()
        return _public(row)


def _bound_request(conn: sqlite3.Connection, request_id: str, new_run_ref: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM reservations WHERE request_id=?", (request_id,)).fetchone()
    if row is None or row["new_run_ref"] != new_run_ref:
        raise ReacquisitionConflict("reacquisition request or child run binding does not match")
    return row


def release(
    db_path: str | Path, *, request_id: str, new_run_ref: str, reason_code: str
) -> dict[str, Any]:
    """Explicitly free an inactive reservation, preserving its failed history.

    The caller must have established that no collection/lease/accept is active.
    A failed request stays failed; retry uses a new request and a new child run.
    """
    return _finish(db_path, request_id=request_id, new_run_ref=new_run_ref,
                   status="failed", reason_code=reason_code)


def finalize(db_path: str | Path, *, request_id: str, new_run_ref: str) -> dict[str, Any]:
    """Finish an inactive queued child. This does not close any parent research gap."""
    return _finish(db_path, request_id=request_id, new_run_ref=new_run_ref,
                   status="completed", reason_code="")


def _finish(
    db_path: str | Path, *, request_id: str, new_run_ref: str, status: str, reason_code: str
) -> dict[str, Any]:
    _validated(request_id=request_id, new_run_ref=new_run_ref,
               **({"reason_code": reason_code} if status == "failed" else {}))
    if not Path(db_path).is_file():
        raise ReacquisitionConflict("reacquisition request does not exist")
    with closing(sqlite3.connect(db_path, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = _bound_request(conn, request_id, new_run_ref)
        if row["status"] == status:
            if row["reason_code"] != reason_code:
                raise ReacquisitionConflict("terminal reservation reason is immutable")
            return _public(row, idempotent=True)
        if row["status"] in {"failed", "completed"} or (status == "completed" and row["status"] != "queued"):
            raise ReacquisitionConflict("invalid reacquisition terminal transition")
        now = _now()
        conn.execute("UPDATE reservations SET status=?,reason_code=?,updated_at=? WHERE request_id=?",
                     (status, reason_code, now, request_id))
        _event(conn, request_id, status, reason_code, now)
        row = conn.execute("SELECT * FROM reservations WHERE request_id=?", (request_id,)).fetchone()
        conn.commit()
        return _public(row)
