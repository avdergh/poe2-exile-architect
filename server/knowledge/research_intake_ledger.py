"""Cross-run research intake dedup ledger (character-level).

poe.ninja build lists are sampled highest level first, so repeated top-down
collection keeps re-fetching the same characters. This local, per-user ledger
records which poe.ninja characters have already been queued for research per
league, so a new queue keeps fetching list pages until it finds fresh
characters instead of re-researching the same builds.

Only safe hashed refs and safe metadata are stored here. Raw account/character
names, raw PoB codes and raw XML never enter this store, never enter Research
Memory, Learning Memory or Git; the existing ``character-hash:<...>`` ref style
(from ``mature_ninja_payload``) is reused so identities stay copy-safe.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .. import paths

SCHEMA_VERSION = 1
LEDGER_FILENAME = "research_intake.sqlite"
DEFAULT_STATUS = "queued"
ACCEPTED_STATUS = "accepted"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intake_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league TEXT NOT NULL,
    character_ref TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 0,
    ascendancy TEXT NOT NULL DEFAULT '',
    main_skill TEXT NOT NULL DEFAULT '',
    first_sample_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(league, character_ref)
);

CREATE INDEX IF NOT EXISTS idx_intake_records_source_hash
    ON intake_records(source_hash);
"""

VALID_STATUSES = {DEFAULT_STATUS, ACCEPTED_STATUS}


def default_ledger_path() -> Path:
    """Per-user stable ledger location shared across research runs."""
    return paths.user_data_dir() / LEDGER_FILENAME


def character_ref(account: str, name: str) -> str:
    """Copy-safe character identity ref: hashes the normalized account/name pair.

    Path-segment percent-encoding is decoded with ``unquote`` (never
    ``unquote_plus``: ``+`` is a literal path character, not a space) so a
    ref stays stable even if poe.ninja changes its href encoding.
    """
    account_text = " ".join(unquote(str(account or "")).split()).casefold()
    name_text = " ".join(unquote(str(name or "")).split()).casefold()
    digest = hashlib.sha256(f"{account_text}\u0000{name_text}".encode("utf-8")).hexdigest()
    return f"character-hash:{digest[:16]}"


def init_db(db_path: str | Path) -> None:
    """Create the ledger schema (idempotent)."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()


def seen_character_refs(db_path: str | Path, league: str) -> set[str]:
    """Return character refs already recorded for one league.

    A missing ledger file reads as empty: read-only consumers never create it.
    """
    path = Path(db_path)
    if not path.is_file():
        return set()
    try:
        init_db(path)
    except sqlite3.Error:
        return set()
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT character_ref FROM intake_records WHERE league = ?",
            (str(league or "").strip(),),
        ).fetchall()
    return {str(row[0]) for row in rows}


def record_case(
    db_path: str | Path,
    *,
    league: str,
    character_ref: str,
    source_hash: str,
    level: int = 0,
    ascendancy: str = "",
    main_skill: str = "",
    sample_id: str = "",
) -> bool:
    """Record one queued character; returns True when newly inserted.

    An existing row keeps its status (queued -> accepted is never downgraded),
    only safe metadata is refreshed.
    """
    init_db(db_path)
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO intake_records(
                league, character_ref, source_hash, level, ascendancy, main_skill,
                first_sample_id, status, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                str(league or "").strip(),
                str(character_ref or "").strip(),
                str(source_hash or "").strip(),
                int(level or 0),
                str(ascendancy or "")[:160],
                str(main_skill or "")[:160],
                str(sample_id or "")[:240],
                now,
                now,
            ),
        )
        inserted = cur.rowcount == 1
        if not inserted:
            conn.execute(
                """
                UPDATE intake_records
                   SET source_hash = ?,
                       level = ?,
                       ascendancy = ?,
                       main_skill = ?,
                       updated_at = ?
                 WHERE league = ?
                   AND character_ref = ?
                """,
                (
                    str(source_hash or "").strip(),
                    int(level or 0),
                    str(ascendancy or "")[:160],
                    str(main_skill or "")[:160],
                    now,
                    str(league or "").strip(),
                    str(character_ref or "").strip(),
                ),
            )
        conn.commit()
    return inserted


def mark_accepted(db_path: str | Path, *, league: str, character_ref: str) -> bool:
    """Promote a queued record to accepted once the run durably accepted it.

    Keyed by the UNIQUE (league, character_ref) identity: two characters with
    byte-identical builds share a source_hash, so source_hash alone could
    promote a character that was never actually researched.
    """
    path = Path(db_path)
    if not path.is_file():
        return False
    init_db(path)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE intake_records
               SET status = 'accepted', updated_at = ?
             WHERE league = ?
               AND character_ref = ?
               AND status != 'accepted'
            """,
            (
                _now_iso(),
                str(league or "").strip(),
                str(character_ref or "").strip(),
            ),
        )
        conn.commit()
    return cur.rowcount > 0


def finalize_accepted(
    db_path: str | Path,
    *,
    league: str,
    character_ref: str,
    source_hash: str = "",
    sample_id: str = "",
) -> str:
    """Idempotently finalize one ledger row after a committed Research receipt."""

    path = Path(db_path)
    can_recreate = bool(str(source_hash or "").strip() and str(sample_id or "").strip())
    if not path.is_file() and not can_recreate:
        return "conflict"
    init_db(path)
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT status FROM intake_records WHERE league = ? AND character_ref = ?",
            (str(league or "").strip(), str(character_ref or "").strip()),
        ).fetchone()
        if row is None:
            if not can_recreate:
                return "conflict"
            now = _now_iso()
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO intake_records(
                    league, character_ref, source_hash, first_sample_id,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'accepted', ?, ?)
                """,
                (
                    str(league or "").strip(),
                    str(character_ref or "").strip(),
                    str(source_hash or "").strip(),
                    str(sample_id or "").strip(),
                    now,
                    now,
                ),
            )
            conn.commit()
            return "recreated" if cur.rowcount == 1 else "conflict"
        if str(row[0]) == ACCEPTED_STATUS:
            return "already_accepted"
        cur = conn.execute(
            "UPDATE intake_records SET status = 'accepted', updated_at = ? "
            "WHERE league = ? AND character_ref = ? AND status = 'queued'",
            (
                _now_iso(),
                str(league or "").strip(),
                str(character_ref or "").strip(),
            ),
        )
        conn.commit()
    return "accepted" if cur.rowcount == 1 else "conflict"


def release_queued_case(
    db_path: str | Path,
    *,
    league: str,
    character_ref: str,
    source_hash: str,
    sample_id: str,
) -> str:
    """Release one abandoned queue reservation without touching accepted history.

    The four safe identity fields bind the release to the exact case that originally
    reserved the character.  A missing row is already released; an accepted row is
    durable history and is deliberately preserved.  Any queued identity mismatch fails
    closed so abandoning one run cannot release another run's reservation.
    """

    path = Path(db_path)
    if not path.is_file():
        return "missing"
    init_db(path)
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            """
            SELECT id, status, source_hash, first_sample_id
              FROM intake_records
             WHERE league = ?
               AND character_ref = ?
            """,
            (str(league or "").strip(), str(character_ref or "").strip()),
        ).fetchone()
        if row is None:
            return "missing"
        status = str(row[1] or "")
        if status == ACCEPTED_STATUS:
            return "accepted_preserved"
        if status != DEFAULT_STATUS:
            return "status_mismatch"
        stored_source_hash = str(row[2] or "")
        stored_sample_id = str(row[3] or "")
        if (
            stored_source_hash != str(source_hash or "").strip()
            or stored_sample_id != str(sample_id or "").strip()
        ):
            return "ownership_mismatch"
        cur = conn.execute(
            "DELETE FROM intake_records WHERE id = ? AND status = 'queued'",
            (int(row[0]),),
        )
        conn.commit()
    finally:
        conn.close()
    return "released" if cur.rowcount == 1 else "concurrent_change"


def summary(db_path: str | Path, league: str | None = None) -> dict[str, Any]:
    """Safe aggregate counts for transparency in queue reports."""
    path = Path(db_path)
    empty: dict[str, Any] = {
        "totalRecords": 0,
        "byStatus": {},
        "leagues": {},
        "schemaVersion": SCHEMA_VERSION,
    }
    if not path.is_file():
        return empty
    try:
        init_db(path)
    except sqlite3.Error:
        return empty
    with sqlite3.connect(path) as conn:
        if league is not None:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM intake_records "
                "WHERE league = ? GROUP BY status",
                (str(league).strip(),),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM intake_records WHERE league = ?",
                (str(league).strip(),),
            ).fetchone()[0]
            return {
                "totalRecords": int(total),
                "byStatus": {str(r[0]): int(r[1]) for r in rows},
                "schemaVersion": SCHEMA_VERSION,
            }
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM intake_records GROUP BY status"
        ).fetchall()
        league_rows = conn.execute(
            "SELECT league, COUNT(*) AS count FROM intake_records GROUP BY league"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM intake_records").fetchone()[0]
    return {
        "totalRecords": int(total),
        "byStatus": {str(r[0]): int(r[1]) for r in status_rows},
        "leagues": {str(r[0]): int(r[1]) for r in league_rows},
        "schemaVersion": SCHEMA_VERSION,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
