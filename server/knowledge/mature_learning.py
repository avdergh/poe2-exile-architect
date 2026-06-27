"""Sanitized mature-build learning store.

Phase 3N.1 owns only schema, fixture ingestion, and copy-safety boundaries. It intentionally does
not influence route synthesis or promote knowledge; later phases may read these tables after their
own visibility and provenance gates are implemented.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import paths

SCHEMA_VERSION = 1


class SchemaVersionError(RuntimeError):
    """Raised when the store is newer than this code can safely read."""


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_groups (
    source_group_id TEXT PRIMARY KEY,
    dedupe_hash TEXT NOT NULL UNIQUE,
    canonical_source_type TEXT NOT NULL,
    canonical_source_ref TEXT NOT NULL,
    league TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_snapshots (
    id TEXT PRIMARY KEY,
    source_group_id TEXT NOT NULL REFERENCES source_groups(source_group_id),
    source_type TEXT NOT NULL,
    source_url TEXT,
    fetched_at TEXT NOT NULL,
    league TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    pob_version_or_commit TEXT,
    popularity_filter TEXT NOT NULL,
    diversity_bucket TEXT NOT NULL,
    raw_hash TEXT NOT NULL,
    sanitizer_version TEXT NOT NULL,
    freshness_status TEXT NOT NULL,
    attribution TEXT NOT NULL,
    usage_policy TEXT NOT NULL,
    fixture_manifest TEXT NOT NULL DEFAULT '{}',
    CHECK (source_type IN ('poe_ninja', 'forum', 'pobb_in', 'pob_archive', 'manual_fixture')),
    CHECK (freshness_status IN (
        'current_metadata_only', 'verified_current', 'stale', 'needs_revalidation', 'unknown'
    ))
);

CREATE TABLE IF NOT EXISTS mature_build_cases (
    case_id TEXT PRIMARY KEY,
    source_snapshot_id TEXT NOT NULL REFERENCES source_snapshots(id),
    external_id_hash TEXT NOT NULL,
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    class TEXT NOT NULL,
    ascendancy TEXT NOT NULL,
    main_skill TEXT NOT NULL,
    damage_types TEXT NOT NULL,
    delivery_tags TEXT NOT NULL,
    defense_tags TEXT NOT NULL,
    mechanic_tags TEXT NOT NULL,
    lifecycle_stage TEXT NOT NULL,
    budget_band TEXT NOT NULL,
    popularity_rank INTEGER,
    sample_weight REAL NOT NULL,
    pob_modelability TEXT NOT NULL,
    sanitized_keypoints TEXT NOT NULL,
    numeric_ranges_or_metrics TEXT NOT NULL,
    redacted_fields_present TEXT NOT NULL,
    source_group_id TEXT NOT NULL REFERENCES source_groups(source_group_id),
    evidence_type TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    league TEXT NOT NULL,
    freshness_status TEXT NOT NULL,
    compatibility_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context')
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout')
        OR (visibility = 'quarantined' AND split = 'quarantine')
    ),
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral')),
    CHECK (pob_modelability IN ('full', 'partial', 'not_modelable', 'unknown')),
    CHECK (lifecycle_stage IN (
        'campaign_early', 'campaign_mid', 'campaign_late', 'maps_entry',
        'endgame_budget', 'endgame_final', 'unknown_lifecycle'
    )),
    CHECK (evidence_type IN (
        'poe_ninja_hot', 'external_forum_guide', 'pobb_in_import', 'pob_archive',
        'reference_cohort', 'engine_computed', 'user_feedback_local',
        'generated_eval_gap', 'multi_source_confirmed', 'manual_fixture'
    )),
    CHECK (freshness_status IN (
        'current_metadata_only', 'verified_current', 'stale', 'needs_revalidation', 'unknown'
    )),
    CHECK (compatibility_status IN ('current', 'stale', 'unknown', 'quarantined'))
);

CREATE TABLE IF NOT EXISTS technique_candidates (
    candidate_id TEXT PRIMARY KEY,
    knowledge_scope TEXT NOT NULL,
    statement TEXT NOT NULL,
    summary_for_llm TEXT NOT NULL,
    category_tags TEXT NOT NULL,
    lifecycle_stage TEXT NOT NULL,
    mechanism_role TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 0,
    support_count INTEGER NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    confidence TEXT NOT NULL,
    promotion_status TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    league TEXT NOT NULL,
    freshness_status TEXT NOT NULL,
    compatibility_status TEXT NOT NULL,
    budget_band TEXT NOT NULL,
    pob_modelability TEXT NOT NULL,
    required_prerequisites TEXT NOT NULL,
    starter_risk_reason TEXT NOT NULL,
    transition_gate_summary TEXT NOT NULL,
    unsafe_before_stage TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral')),
    CHECK (promotion_status IN ('candidate', 'promoted', 'rejected', 'stale', 'quarantined')),
    CHECK (freshness_status IN (
        'current_metadata_only', 'verified_current', 'stale', 'needs_revalidation', 'unknown'
    )),
    CHECK (compatibility_status IN ('current', 'stale', 'unknown', 'quarantined')),
    CHECK (pob_modelability IN ('full', 'partial', 'not_modelable', 'unknown'))
);

CREATE TABLE IF NOT EXISTS candidate_evidence (
    evidence_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES technique_candidates(candidate_id),
    case_id TEXT NOT NULL REFERENCES mature_build_cases(case_id),
    source_snapshot_id TEXT NOT NULL REFERENCES source_snapshots(id),
    source_group_id TEXT NOT NULL REFERENCES source_groups(source_group_id),
    relation TEXT NOT NULL,
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    confidence REAL NOT NULL,
    creator_visible INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    CHECK (relation IN ('supports', 'contradicts', 'mentions')),
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context')
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout')
        OR (visibility = 'quarantined' AND split = 'quarantine')
    ),
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral')),
    CHECK (creator_visible IN (0, 1))
);

CREATE TABLE IF NOT EXISTS technique_edges (
    edge_id TEXT PRIMARY KEY,
    from_candidate_id TEXT NOT NULL REFERENCES technique_candidates(candidate_id),
    to_candidate_id TEXT NOT NULL REFERENCES technique_candidates(candidate_id),
    edge_type TEXT NOT NULL,
    candidate_evidence_ids TEXT NOT NULL,
    confidence REAL NOT NULL,
    league TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    CHECK (edge_type IN (
        'requires', 'enables', 'conflicts_with', 'upgrades_to', 'replaces',
        'transition_from', 'transition_to', 'synergizes_with'
    ))
);

INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1');
"""


def mature_learning_path() -> Path:
    return paths.mature_learning_path()


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or mature_learning_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def initialize_store(db_path: Path | None = None) -> Path:
    path = db_path or mature_learning_path()
    with connect(path) as con:
        existing = schema_version(con)
        if existing > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"mature learning DB schema {existing} is newer than supported {SCHEMA_VERSION}"
            )
        con.executescript(_SCHEMA_SQL)
    return path


def schema_version(con: sqlite3.Connection) -> int:
    try:
        row = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0
