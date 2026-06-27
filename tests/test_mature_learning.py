"""Phase 3N mature-build learning store tests.

The mature-learning store must keep popular mature build knowledge useful but non-copyable.
Phase 3N.1 creates schema and safety guards only; it must not affect route synthesis.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from server import paths
from server.knowledge import mature_learning


def _tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def test_mature_learning_path_lives_in_user_data(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))

    path = paths.mature_learning_path()

    assert path == tmp_path / "mature_build_learning.sqlite"
    assert path.parent == tmp_path


def test_initialize_store_creates_phase_3n1_schema(tmp_path):
    db_path = tmp_path / "mature.sqlite"

    mature_learning.initialize_store(db_path)
    con = sqlite3.connect(db_path)

    assert mature_learning.schema_version(con) == mature_learning.SCHEMA_VERSION
    assert {
        "meta",
        "source_groups",
        "source_snapshots",
        "mature_build_cases",
        "technique_candidates",
        "candidate_evidence",
        "technique_edges",
    } <= _tables(con)
    assert {
        "source_group_id",
        "dedupe_hash",
        "canonical_source_type",
        "canonical_source_ref",
        "league",
        "game_patch",
        "passive_tree_version",
        "created_at",
        "last_seen_at",
    } <= _columns(con, "source_groups")
    assert {
        "case_id",
        "source_snapshot_id",
        "external_id_hash",
        "visibility",
        "split",
        "knowledge_scope",
        "class",
        "ascendancy",
        "main_skill",
        "sanitized_keypoints",
        "redacted_fields_present",
        "source_group_id",
    } <= _columns(con, "mature_build_cases")
    assert "evidence_id" in _columns(con, "candidate_evidence")
    assert "edge_id" in _columns(con, "technique_edges")


def test_initialize_store_is_idempotent_for_schema_v1(tmp_path):
    db_path = tmp_path / "mature.sqlite"

    mature_learning.initialize_store(db_path)
    mature_learning.initialize_store(db_path)
    con = sqlite3.connect(db_path)

    assert mature_learning.schema_version(con) == mature_learning.SCHEMA_VERSION
    assert con.execute("SELECT count(*) FROM meta WHERE key = 'schema_version'").fetchone()[0] == 1


def test_initialize_store_refuses_future_schema_without_downgrading(tmp_path):
    db_path = tmp_path / "future.sqlite"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '999')")
    con.commit()
    con.close()

    with pytest.raises(mature_learning.SchemaVersionError):
        mature_learning.initialize_store(db_path)

    con = sqlite3.connect(db_path)
    assert con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "999"


def test_schema_rejects_invalid_candidate_evidence_visibility_split(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    mature_learning.initialize_store(db_path)
    con = sqlite3.connect(db_path)

    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            """
            INSERT INTO candidate_evidence(
                evidence_id, candidate_id, case_id, source_snapshot_id, source_group_id,
                relation, visibility, split, knowledge_scope, extraction_method,
                extractor_version, confidence, creator_visible, created_at, last_seen_at
            ) VALUES (
                'ev-1', 'cand-missing', 'case-missing', 'ss-missing', 'sg-missing',
                'supports', 'creator_visible', 'eval_holdout', 'global_seed',
                'test', 'test', 1.0, 1, 'now', 'now'
            )
            """
        )
