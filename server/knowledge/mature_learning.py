"""Sanitized mature-build learning store.

Phase 3N.1 owns only schema, fixture ingestion, and copy-safety boundaries. It intentionally does
not influence route synthesis or promote knowledge; later phases may read these tables after their
own visibility and provenance gates are implemented.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .. import paths

SCHEMA_VERSION = 4
SANITIZER_VERSION = "phase3n1-v1"
EXTRACTOR_VERSION = "phase3n2-v1"
EXTRACTION_METHOD = "deterministic_mature_case_summary"
RELEASE_SEED_KIND = "creator_safe_research_seed_v1"

FORBIDDEN_COPYABLE_FIELDS = {
    "pobCode",
    "pastebinCode",
    "pobbInCode",
    "rawXml",
    "rawPob",
    "passiveTree",
    "passiveNodeIds",
    "fullPassiveNodeIds",
    "orderedPassiveNodes",
    "gear",
    "items",
    "itemSets",
    "affixes",
    "exactAffixes",
    "skillGroups",
    "supportGems",
    "fullGemLinks",
    "guideText",
    "copiedGuideText",
    "configTab",
    "raw",
    "rawContent",
    "rawPayload",
    "rawJson",
    "rawHtml",
    "rawResponse",
    "originalPayload",
    "sourceHtml",
    "sourceJson",
    "guideMarkdown",
    "guideHtml",
    "rawGuideText",
    "characterUrl",
    "profileUrl",
    "accountName",
    "characterName",
}

VALID_VISIBILITY_SPLITS = {
    ("creator_visible", "train_context"),
    ("evaluator_only", "eval_holdout"),
    ("quarantined", "quarantine"),
}
VALID_KNOWLEDGE_SCOPES = {"global_seed", "local_user", "eval_ephemeral"}
RELEASE_SEED_KNOWLEDGE_SCOPES = {"global_seed", "local_user"}
VALID_MODELABILITY = {"full", "partial", "not_modelable", "unknown"}
VALID_LIFECYCLE_STAGES = {
    "campaign_early",
    "campaign_mid",
    "campaign_late",
    "maps_entry",
    "endgame_budget",
    "endgame_final",
    "unknown_lifecycle",
}
VALID_EVIDENCE_TYPES = {
    "poe_ninja_hot",
    "external_forum_guide",
    "pobb_in_import",
    "pob_archive",
    "reference_cohort",
    "engine_computed",
    "user_feedback_local",
    "generated_eval_gap",
    "multi_source_confirmed",
    "manual_fixture",
}
VALID_FRESHNESS = {
    "current_metadata_only",
    "verified_current",
    "stale",
    "needs_revalidation",
    "unknown",
}
VALID_COMPATIBILITY = {"current", "stale", "unknown", "quarantined"}
CURRENT_FRESHNESS_CLAIMS = {"verified_current", "current_metadata_only"}
REQUIRED_FIXTURE_MANIFEST_FIELDS = {
    "eligibility_basis",
    "popularity_signal",
    "currentness_basis",
    "diversity_policy",
}


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
    CHECK (creator_visible IN (0, 1)),
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context' AND creator_visible = 1)
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout' AND creator_visible = 0)
        OR (visibility = 'quarantined' AND split = 'quarantine' AND creator_visible = 0)
    )
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

_PHASE4_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_fragments (
    fragment_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL,
    fragment_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    reusable_principle TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    component_keys TEXT NOT NULL,
    source_case_refs TEXT NOT NULL,
    safe_evidence_refs TEXT NOT NULL,
    confidence TEXT NOT NULL,
    copyability_risk TEXT NOT NULL,
    lifecycle_stages TEXT NOT NULL,
    modelability TEXT NOT NULL,
    verification_tasks TEXT NOT NULL,
    conditions TEXT NOT NULL,
    risks TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    pob_version_or_commit TEXT NOT NULL,
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    status TEXT NOT NULL,
    copy_safety_state TEXT NOT NULL,
    current_version_context TEXT NOT NULL,
    affected_component_keys TEXT NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    embedding_model TEXT,
    embedding_dim INTEGER,
    embedding_ref TEXT,
    embedding_status TEXT NOT NULL DEFAULT 'not_configured',
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_validated_at TEXT,
    superseded_by_id TEXT,
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context')
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout')
        OR (visibility = 'quarantined' AND split = 'quarantine')
    ),
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral')),
    CHECK (status IN ('valid', 'needs_revalidation', 'stale', 'rejected', 'deprecated', 'quarantined')),
    CHECK (copy_safety_state IN ('passed', 'needs_review', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_research_fragments_bucket
ON research_fragments(visibility, split, knowledge_scope, status);

CREATE INDEX IF NOT EXISTS idx_research_fragments_dedupe
ON research_fragments(dedupe_key, visibility, split, knowledge_scope);

CREATE VIRTUAL TABLE IF NOT EXISTS research_fragment_fts USING fts5(
    fragment_id,
    chunk_text,
    component_keys,
    content='research_fragments',
    content_rowid='rowid',
    tokenize="unicode61 tokenchars ':'"
);

CREATE TRIGGER IF NOT EXISTS research_fragments_ai
AFTER INSERT ON research_fragments BEGIN
    INSERT INTO research_fragment_fts(rowid, fragment_id, chunk_text, component_keys)
    VALUES (new.rowid, new.fragment_id, new.chunk_text, new.component_keys);
END;

CREATE TRIGGER IF NOT EXISTS research_fragments_ad
AFTER DELETE ON research_fragments BEGIN
    INSERT INTO research_fragment_fts(
        research_fragment_fts, rowid, fragment_id, chunk_text, component_keys
    ) VALUES ('delete', old.rowid, old.fragment_id, old.chunk_text, old.component_keys);
END;

CREATE TRIGGER IF NOT EXISTS research_fragments_au
AFTER UPDATE ON research_fragments BEGIN
    INSERT INTO research_fragment_fts(
        research_fragment_fts, rowid, fragment_id, chunk_text, component_keys
    ) VALUES ('delete', old.rowid, old.fragment_id, old.chunk_text, old.component_keys);
    INSERT INTO research_fragment_fts(rowid, fragment_id, chunk_text, component_keys)
    VALUES (new.rowid, new.fragment_id, new.chunk_text, new.component_keys);
END;

CREATE TABLE IF NOT EXISTS research_fragment_evidence (
    evidence_id TEXT PRIMARY KEY,
    fragment_id TEXT NOT NULL REFERENCES research_fragments(fragment_id),
    source_case_refs TEXT NOT NULL,
    safe_evidence_refs TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    pob_version_or_commit TEXT NOT NULL,
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    confidence TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context')
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout')
        OR (visibility = 'quarantined' AND split = 'quarantine')
    ),
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral'))
);

CREATE TABLE IF NOT EXISTS research_semantic_edges (
    edge_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    target_key TEXT NOT NULL,
    canonical_source_key TEXT NOT NULL,
    canonical_target_key TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    rationale TEXT NOT NULL,
    source_case_refs TEXT NOT NULL,
    safe_evidence_refs TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    pob_version_or_commit TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence TEXT NOT NULL,
    modelability TEXT NOT NULL,
    copy_safety_state TEXT NOT NULL,
    context_requirements TEXT NOT NULL,
    affected_component_keys TEXT NOT NULL,
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    directionality TEXT NOT NULL,
    planner_visible INTEGER NOT NULL DEFAULT 1,
    current_version_context TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_validated_at TEXT,
    superseded_by_id TEXT,
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context')
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout')
        OR (visibility = 'quarantined' AND split = 'quarantine')
    ),
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral')),
    CHECK (directionality IN ('directional', 'associative')),
    CHECK (planner_visible IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_research_edges_directional
ON research_semantic_edges(
    visibility, split, knowledge_scope, edge_type, source_key, target_key, directionality, planner_visible
);

CREATE TABLE IF NOT EXISTS research_build_design_observations (
    observation_id TEXT PRIMARY KEY,
    observation_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    axes TEXT NOT NULL,
    components TEXT NOT NULL,
    component_keys TEXT NOT NULL,
    source_case_refs TEXT NOT NULL,
    safe_evidence_refs TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    pob_version_or_commit TEXT NOT NULL,
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    copy_safety_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context')
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout')
        OR (visibility = 'quarantined' AND split = 'quarantine')
    ),
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral')),
    CHECK (copy_safety_state IN ('passed', 'needs_review', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_research_observations_bucket
ON research_build_design_observations(visibility, split, knowledge_scope, observation_type);

CREATE TABLE IF NOT EXISTS research_build_patterns (
    pattern_id TEXT PRIMARY KEY,
    pattern_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    component_keys TEXT NOT NULL,
    component_roles TEXT NOT NULL,
    confidence_tier TEXT NOT NULL,
    transfer_scope TEXT NOT NULL DEFAULT 'family',
    transfer_key TEXT,
    applicability_axes TEXT NOT NULL DEFAULT '[]',
    applicability_requirements TEXT NOT NULL DEFAULT '[]',
    exclusion_conditions TEXT NOT NULL DEFAULT '[]',
    transfer_rationale TEXT,
    origin_family_keys TEXT NOT NULL DEFAULT '[]',
    sample_count INTEGER NOT NULL,
    family_count INTEGER NOT NULL,
    source_diversity_count INTEGER NOT NULL,
    denominator INTEGER,
    source_case_refs TEXT NOT NULL,
    safe_evidence_refs TEXT NOT NULL,
    context_requirements TEXT NOT NULL,
    planner_hint TEXT,
    verification_tasks TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    pob_version_or_commit TEXT NOT NULL,
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'valid',
    copy_safety_state TEXT NOT NULL,
    current_version_context TEXT NOT NULL DEFAULT '{}',
    planner_visible INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_validated_at TEXT,
    superseded_by_id TEXT,
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context')
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout')
        OR (visibility = 'quarantined' AND split = 'quarantine')
    ),
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral')),
    CHECK (status IN ('valid', 'needs_revalidation', 'stale', 'deprecated', 'quarantined')),
    CHECK (copy_safety_state IN ('passed', 'needs_review', 'rejected')),
    CHECK (transfer_scope IN ('family', 'component', 'global')),
    CHECK (planner_visible IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_research_patterns_bucket
ON research_build_patterns(visibility, split, knowledge_scope, pattern_type, planner_visible);

CREATE TABLE IF NOT EXISTS deep_research_records (
    record_id TEXT PRIMARY KEY,
    research_group_id TEXT NOT NULL,
    build_family_key TEXT,
    knowledge_key TEXT,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    record_kind TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    content TEXT NOT NULL,
    content_language TEXT NOT NULL,
    length_exception_reason TEXT,
    component_keys TEXT NOT NULL,
    component_mentions TEXT NOT NULL DEFAULT '[]',
    source_case_refs TEXT NOT NULL,
    safe_evidence_refs TEXT NOT NULL,
    conditions TEXT NOT NULL,
    failure_conditions TEXT NOT NULL,
    typed_payload TEXT NOT NULL,
    class_key TEXT,
    ascendancy_key TEXT,
    extraction_method_version TEXT NOT NULL,
    record_schema_version INTEGER NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    pob_version_or_commit TEXT NOT NULL,
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    status TEXT NOT NULL,
    copy_safety_state TEXT NOT NULL,
    current_version_context TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_validated_at TEXT,
    superseded_by_id TEXT,
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context')
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout')
        OR (visibility = 'quarantined' AND split = 'quarantine')
    ),
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral')),
    CHECK (status IN ('valid', 'needs_revalidation', 'stale', 'deprecated', 'quarantined')),
    CHECK (copy_safety_state IN ('passed', 'needs_review', 'rejected')),
    CHECK (content_language IN ('zh-CN', 'en'))
);

CREATE INDEX IF NOT EXISTS idx_deep_research_records_bucket
ON deep_research_records(
    visibility, split, knowledge_scope, status, record_kind, research_group_id
);

CREATE TABLE IF NOT EXISTS research_build_families (
    build_family_key TEXT PRIMARY KEY,
    ascendancy_key TEXT NOT NULL,
    primary_skill_key TEXT NOT NULL,
    secondary_skill_keys TEXT NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_build_family_evidence (
    build_family_key TEXT NOT NULL,
    source_case_ref TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (build_family_key, source_case_ref),
    FOREIGN KEY (build_family_key) REFERENCES research_build_families(build_family_key)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS deep_research_record_evidence (
    knowledge_key TEXT NOT NULL,
    source_case_ref TEXT NOT NULL,
    safe_evidence_refs TEXT NOT NULL,
    observed_component_keys TEXT NOT NULL,
    observed_component_mentions TEXT NOT NULL,
    conditions TEXT NOT NULL,
    failure_conditions TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    pob_version_or_commit TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (knowledge_key, source_case_ref)
);

CREATE TABLE IF NOT EXISTS research_rejected_proposals (
    rejection_id TEXT PRIMARY KEY,
    proposal_hash TEXT NOT NULL,
    error_code TEXT NOT NULL,
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 1,
    caveats TEXT NOT NULL,
    suggested_repair TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_dedupe_queries (
    dedupe_query_ref TEXT PRIMARY KEY,
    query_hash TEXT NOT NULL,
    query_text_preview TEXT NOT NULL,
    component_keys TEXT NOT NULL,
    request_contract TEXT NOT NULL DEFAULT '{}',
    result_contract TEXT NOT NULL DEFAULT '{}',
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_revalidation_events (
    event_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    old_version_context TEXT NOT NULL,
    new_version_context TEXT NOT NULL,
    safe_evidence_refs TEXT NOT NULL,
    affected_component_keys TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (target_kind IN ('fragment', 'semantic_edge', 'build_pattern')),
    CHECK (outcome IN ('still_valid', 'invalidated', 'changed_scope', 'needs_review'))
);

CREATE TABLE IF NOT EXISTS research_decay_events (
    event_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    decay_scope TEXT NOT NULL,
    old_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    changed_component_keys TEXT NOT NULL,
    new_version_context TEXT NOT NULL,
    created_at TEXT NOT NULL
);
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
    if db_path is None:
        _install_bundled_release_seed_if_missing(path)
    con = connect(path)
    try:
        existing = schema_version(con)
        if existing > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"mature learning DB schema {existing} is newer than supported {SCHEMA_VERSION}"
            )
        con.executescript(_SCHEMA_SQL)
        con.executescript(_PHASE4_SCHEMA_SQL)
        _migrate_phase4_additive_schema(con)
        con.execute(
            """
            INSERT INTO meta(key, value) VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(SCHEMA_VERSION),),
        )
        con.commit()
    finally:
        con.close()
    return path


def _install_bundled_release_seed_if_missing(target: Path) -> bool:
    """Install a release seed once without replacing an existing local Research store."""

    if target.exists():
        return False
    seed = paths.mature_learning_release_seed_path()
    if not seed.is_file():
        return False
    validate_release_seed(seed)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid4().hex}.installing")
    shutil.copy2(seed, temp)
    try:
        # A hard link is atomic and refuses to replace a database another MCP process may have
        # created while this seed was being copied.  The temporary copy lives beside the target,
        # so both paths are guaranteed to be on the same filesystem.
        os.link(temp, target)
        return True
    except FileExistsError:
        return False
    finally:
        temp.unlink(missing_ok=True)


def validate_release_seed(seed: Path) -> None:
    """Fail closed if a bundled Research seed contains mutable or non-creator-safe state."""

    uri = f"file:{seed.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        integrity = con.execute("PRAGMA quick_check").fetchone()
        if not integrity or str(integrity[0]).casefold() != "ok":
            raise ValueError("research release seed failed SQLite integrity check")
        if schema_version(con) != SCHEMA_VERSION:
            raise ValueError("research release seed schema version mismatch")
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        if meta.get("release_seed_kind") != RELEASE_SEED_KIND:
            raise ValueError("research release seed kind is missing or unsupported")
        for table in (
            "source_groups",
            "source_snapshots",
            "mature_build_cases",
            "technique_candidates",
            "candidate_evidence",
            "technique_edges",
            "research_rejected_proposals",
            "research_dedupe_queries",
            "research_revalidation_events",
            "research_decay_events",
        ):
            if con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]:
                raise ValueError(f"research release seed contains forbidden table rows: {table}")
        scoped_tables = (
            "research_fragments",
            "research_semantic_edges",
            "research_build_design_observations",
            "research_build_patterns",
            "deep_research_records",
        )
        for table in scoped_tables:
            where = (
                "visibility <> 'creator_visible' OR split <> 'train_context' "
                "OR knowledge_scope NOT IN ('global_seed', 'local_user') "
                "OR copy_safety_state <> 'passed'"
            )
            if table != "research_build_design_observations":
                where += " OR status <> 'valid'"
            if con.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0]:
                raise ValueError(f"research release seed contains non-creator-safe rows: {table}")
        orphan_family_count = con.execute(
            """
            SELECT count(*)
            FROM research_build_families AS family
            WHERE NOT EXISTS (
                SELECT 1
                FROM deep_research_records AS record
                WHERE record.build_family_key = family.build_family_key
            )
            """
        ).fetchone()[0]
        if orphan_family_count:
            raise ValueError("research release seed contains Family rows without public records")
        orphan_evidence_count = con.execute(
            """
            SELECT count(*)
            FROM research_build_family_evidence AS evidence
            WHERE NOT EXISTS (
                SELECT 1
                FROM research_build_families AS family
                WHERE family.build_family_key = evidence.build_family_key
            )
            """
        ).fetchone()[0]
        if orphan_evidence_count:
            raise ValueError("research release seed contains orphaned Family evidence")
    finally:
        con.close()


def schema_version(con: sqlite3.Connection) -> int:
    try:
        row = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0


def _migrate_phase4_additive_schema(con: sqlite3.Connection) -> None:
    _add_column_if_missing(
        con,
        "research_dedupe_queries",
        "request_contract",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        con,
        "research_dedupe_queries",
        "result_contract",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        con,
        "deep_research_records",
        "component_mentions",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _add_column_if_missing(con, "deep_research_records", "build_family_key", "TEXT")
    _add_column_if_missing(con, "deep_research_records", "knowledge_key", "TEXT")
    _add_column_if_missing(
        con,
        "deep_research_records",
        "evidence_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        con,
        "research_build_patterns",
        "transfer_scope",
        "TEXT NOT NULL DEFAULT 'family'",
    )
    _add_column_if_missing(con, "research_build_patterns", "transfer_key", "TEXT")
    _add_column_if_missing(
        con,
        "research_build_patterns",
        "applicability_axes",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _add_column_if_missing(
        con,
        "research_build_patterns",
        "applicability_requirements",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _add_column_if_missing(
        con,
        "research_build_patterns",
        "exclusion_conditions",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _add_column_if_missing(con, "research_build_patterns", "transfer_rationale", "TEXT")
    _add_column_if_missing(
        con,
        "research_build_patterns",
        "origin_family_keys",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _add_column_if_missing(
        con,
        "research_build_patterns",
        "status",
        "TEXT NOT NULL DEFAULT 'valid'",
    )
    _add_column_if_missing(
        con,
        "research_build_patterns",
        "current_version_context",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        con,
        "research_build_patterns",
        "last_validated_at",
        "TEXT",
    )
    _add_column_if_missing(
        con,
        "research_build_patterns",
        "superseded_by_id",
        "TEXT",
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_patterns_transfer
        ON research_build_patterns(transfer_scope, transfer_key, confidence_tier, planner_visible)
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_deep_research_records_family
        ON deep_research_records(build_family_key, record_kind, status)
        """
    )
    con.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_deep_research_records_canonical_knowledge
        ON deep_research_records(knowledge_key)
        WHERE knowledge_key IS NOT NULL AND superseded_by_id IS NULL
        """
    )
    _migrate_revalidation_events_target_kind_check(con)


def _add_column_if_missing(
    con: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    try:
        columns = {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return
    if column not in columns:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_revalidation_events_target_kind_check(con: sqlite3.Connection) -> None:
    row = con.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type = 'table' AND name = 'research_revalidation_events'
        """
    ).fetchone()
    sql = str(row["sql"] if row else "")
    if "target_kind IN ('fragment', 'semantic_edge')" not in sql:
        return
    con.execute(
        "ALTER TABLE research_revalidation_events RENAME TO research_revalidation_events_old"
    )
    con.execute(
        """
        CREATE TABLE research_revalidation_events (
            event_id TEXT PRIMARY KEY,
            target_kind TEXT NOT NULL,
            target_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            old_version_context TEXT NOT NULL,
            new_version_context TEXT NOT NULL,
            safe_evidence_refs TEXT NOT NULL,
            affected_component_keys TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CHECK (target_kind IN ('fragment', 'semantic_edge', 'build_pattern')),
            CHECK (outcome IN ('still_valid', 'invalidated', 'changed_scope', 'needs_review'))
        )
        """
    )
    con.execute(
        """
        INSERT INTO research_revalidation_events(
            event_id, target_kind, target_id, outcome, old_version_context,
            new_version_context, safe_evidence_refs, affected_component_keys, created_at
        )
        SELECT event_id, target_kind, target_id, outcome, old_version_context,
               new_version_context, safe_evidence_refs, affected_component_keys, created_at
        FROM research_revalidation_events_old
        """
    )
    con.execute("DROP TABLE research_revalidation_events_old")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _json_loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def _normalized_scalar(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _normalized_tag_list(value: Any, *, max_items: int = 24) -> list[str]:
    values = value if isinstance(value, list) else [value]
    normalized: set[str] = set()
    for item in values[:max_items]:
        text = _normalized_scalar(item).replace(" ", "_")
        if text:
            normalized.add(text[:80])
    return sorted(normalized)


def _as_string_list(value: Any, *, max_items: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:max_items]:
        text = str(item).strip()
        if text:
            out.append(text[:240])
    return out


def _normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _find_forbidden_paths(value: Any, *, path: str = "") -> list[str]:
    """Find forbidden raw-build fields anywhere inside a fixture payload."""
    forbidden_normalized = {_normalize_field_name(field) for field in FORBIDDEN_COPYABLE_FIELDS}
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _normalize_field_name(key_text) in forbidden_normalized:
                found.append(child_path)
            found.extend(_find_forbidden_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            found.extend(_find_forbidden_paths(child, path=child_path))
    return found


def _all_text_fragments(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        fragments: list[str] = []
        for child in value.values():
            fragments.extend(_all_text_fragments(child))
        return fragments
    if isinstance(value, list):
        fragments = []
        for child in value:
            fragments.extend(_all_text_fragments(child))
        return fragments
    return []


def _copyability_flags(raw: dict[str, Any]) -> list[str]:
    text = "\n".join(_all_text_fragments(raw))
    lower = text.lower()
    flags: list[str] = []
    unique_mentions = len(re.findall(r"\bunique\s*:", lower))
    if unique_mentions >= 3:
        flags.append("too_many_named_uniques")
    if re.search(r"(passive path|node\s+\d+).{0,80}(->|,|\bthen\b).{0,80}node\s+\d+", lower):
        flags.append("ordered_passive_path")
    if re.search(r"supports?\s*:\s*[^.\n,]+(?:,\s*[^.\n,]+){4,}", lower):
        flags.append("full_support_link_like")
    if re.search(r"(ring 1|ring 2|helmet|body armour|gloves|boots|weapon)\s*:", lower):
        flags.append("slot_exact_gear_like")
    if len(text) > 1200:
        flags.append("long_guide_prose_like")
    if re.search(r"\b(?:eNrt|pobb\.in/|pastebin\.com/)[A-Za-z0-9+/_=-]{80,}", text):
        flags.append("pob_code_like_blob")
    return flags


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_numeric_ranges(value: Any) -> tuple[dict[str, Any], str | None]:
    """Allow only aggregate metric ranges, never raw stat dumps."""
    if value in (None, {}):
        return {}, None
    if not isinstance(value, dict):
        return {}, "invalid_numeric_ranges_or_metrics"
    normalized: dict[str, Any] = {}
    allowed_keys = {"min", "median", "max", "n", "p10", "p25", "p75", "p90", "p95"}
    for metric, range_value in value.items():
        if not isinstance(metric, str) or not isinstance(range_value, dict):
            return {}, "invalid_numeric_ranges_or_metrics"
        extra = set(range_value) - allowed_keys
        if extra:
            return {}, "invalid_numeric_ranges_or_metrics"
        if not {"min", "max", "n"} <= set(range_value):
            return {}, "invalid_numeric_ranges_or_metrics"
        for cell in range_value.values():
            if not _is_number(cell):
                return {}, "invalid_numeric_ranges_or_metrics"
        if float(range_value["min"]) > float(range_value["max"]):
            return {}, "invalid_numeric_ranges_or_metrics"
        if int(range_value["n"]) != range_value["n"] or int(range_value["n"]) <= 0:
            return {}, "invalid_numeric_ranges_or_metrics"
        min_value = float(range_value["min"])
        max_value = float(range_value["max"])
        ordered_percentiles = [
            key for key in ("p10", "p25", "median", "p75", "p90", "p95") if key in range_value
        ]
        previous = min_value
        for key in ordered_percentiles:
            current = float(range_value[key])
            if current < min_value or current > max_value or current < previous:
                return {}, "invalid_numeric_ranges_or_metrics"
            previous = current
        normalized[metric] = dict(range_value)
    return normalized, None


def _validate_visibility_scope(raw: dict[str, Any]) -> str | None:
    visibility = str(raw.get("visibility") or "")
    split = str(raw.get("split") or "")
    if (visibility, split) not in VALID_VISIBILITY_SPLITS:
        return "invalid_visibility_split"
    scope = str(raw.get("knowledgeScope") or raw.get("knowledge_scope") or "")
    if scope not in VALID_KNOWLEDGE_SCOPES:
        return "invalid_knowledge_scope"
    evidence_type = str(raw.get("evidenceType") or raw.get("evidence_type") or "")
    if evidence_type == "user_feedback_local" and scope != "local_user":
        return "local_feedback_must_stay_local"
    return None


def _raw_value(raw: dict[str, Any], camel: str, snake: str, default: Any = "") -> Any:
    value = raw.get(camel)
    if value in (None, "") and snake in raw:
        return raw.get(snake)
    return default if value is None else value


def _sample_weight(value: Any) -> tuple[float, str | None]:
    try:
        sample_weight = float(value if value not in (None, "") else 1.0)
    except (TypeError, ValueError):
        return 0.0, "invalid_sample_weight"
    if not math.isfinite(sample_weight) or sample_weight <= 0:
        return 0.0, "invalid_sample_weight"
    return sample_weight, None


def sanitize_mature_case(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized mature-case dict or an explicit rejection result.

    This is intentionally allowlist-first: raw build fields are rejected recursively before any
    summary text is persisted, and the remaining text is checked for reconstructable build details.
    """
    if not isinstance(raw, dict):
        return {"ok": False, "error": "case_must_be_object"}

    forbidden_present = sorted(_find_forbidden_paths(raw))
    if forbidden_present:
        return {
            "ok": False,
            "error": "forbidden_copyable_fields",
            "redactedFieldsPresent": forbidden_present,
        }

    boundary_error = _validate_visibility_scope(raw)
    if boundary_error:
        return {"ok": False, "error": boundary_error}

    copyability = _copyability_flags(raw)
    if copyability:
        return {
            "ok": False,
            "error": "copyability_guard_failed",
            "copyabilityFlags": copyability,
        }

    freshness = str(raw.get("freshnessStatus") or "unknown")
    compatibility = str(raw.get("compatibilityStatus") or "unknown")
    modelability = str(raw.get("pobModelability") or "unknown")
    if freshness not in VALID_FRESHNESS:
        return {"ok": False, "error": "invalid_freshness_status"}
    if compatibility not in VALID_COMPATIBILITY:
        return {"ok": False, "error": "invalid_compatibility_status"}
    if modelability not in VALID_MODELABILITY:
        return {"ok": False, "error": "invalid_pob_modelability"}
    lifecycle_stage = str(
        raw.get("lifecycleStage") or raw.get("lifecycle_stage") or "unknown_lifecycle"
    )
    evidence_type = str(raw.get("evidenceType") or raw.get("evidence_type") or "manual_fixture")
    if lifecycle_stage not in VALID_LIFECYCLE_STAGES:
        return {"ok": False, "error": "invalid_lifecycle_stage"}
    if evidence_type not in VALID_EVIDENCE_TYPES:
        return {"ok": False, "error": "invalid_evidence_type"}
    if freshness in CURRENT_FRESHNESS_CLAIMS and (
        str(raw.get("league") or "").lower() == "unknown"
        or str(raw.get("gamePatch") or "").lower() == "unknown"
        or str(raw.get("passiveTreeVersion") or "").lower() == "unknown"
        or not str(raw.get("league") or "").strip()
        or not str(raw.get("gamePatch") or "").strip()
        or not str(raw.get("passiveTreeVersion") or "").strip()
    ):
        return {"ok": False, "error": "current_claim_missing_version_metadata"}

    numeric_ranges, numeric_error = _validate_numeric_ranges(
        raw.get("numericRangesOrMetrics") or {}
    )
    if numeric_error:
        return {"ok": False, "error": numeric_error}
    sample_weight, sample_error = _sample_weight(raw.get("sampleWeight"))
    if sample_error:
        return {"ok": False, "error": sample_error}

    keypoints = _as_string_list(raw.get("keypoints"), max_items=8)
    now = _now()
    source_ref = str(raw.get("sourceRef") or raw.get("sourceUrl") or "")
    external_hash = _stable_hash(
        {
            "sourceRef": source_ref,
            "class": raw.get("class"),
            "ascendancy": raw.get("ascendancy"),
            "mainSkill": raw.get("mainSkill"),
            "keypoints": keypoints,
        }
    )

    return {
        "ok": True,
        "external_id_hash": external_hash,
        "class": str(raw.get("class") or ""),
        "ascendancy": str(raw.get("ascendancy") or ""),
        "main_skill": str(raw.get("mainSkill") or ""),
        "damage_types": _as_string_list(raw.get("damageTypes")),
        "delivery_tags": _as_string_list(raw.get("deliveryTags")),
        "defense_tags": _as_string_list(raw.get("defenseTags")),
        "mechanic_tags": _as_string_list(raw.get("mechanicTags")),
        "lifecycle_stage": lifecycle_stage,
        "budget_band": str(raw.get("budgetBand") or "unknown"),
        "popularity_rank": raw.get("popularityRank"),
        "sample_weight": sample_weight,
        "pob_modelability": modelability,
        "sanitized_keypoints": keypoints,
        "numeric_ranges_or_metrics": numeric_ranges,
        "redacted_fields_present": [],
        "visibility": str(raw.get("visibility")),
        "split": str(raw.get("split")),
        "knowledge_scope": str(_raw_value(raw, "knowledgeScope", "knowledge_scope")),
        "evidence_type": evidence_type,
        "game_patch": str(raw.get("gamePatch") or "unknown"),
        "passive_tree_version": str(raw.get("passiveTreeVersion") or "unknown"),
        "league": str(raw.get("league") or "unknown"),
        "freshness_status": freshness,
        "compatibility_status": compatibility,
        "created_at": now,
        "last_seen_at": now,
    }


def validate_fixture_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    manifest = raw.get("fixtureManifest") or raw.get("fixture_manifest")
    if not isinstance(manifest, dict):
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": sorted(REQUIRED_FIXTURE_MANIFEST_FIELDS),
        }
    missing = sorted(key for key in REQUIRED_FIXTURE_MANIFEST_FIELDS if key not in manifest)
    if missing:
        return {"ok": False, "error": "fixture_manifest_incomplete", "missing": missing}
    if not str(manifest.get("eligibility_basis") or "").strip():
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": ["eligibility_basis"],
        }
    popularity_signal = manifest.get("popularity_signal")
    if not isinstance(popularity_signal, dict) or not popularity_signal:
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": ["popularity_signal"],
        }

    structured_missing: list[str] = []
    if not str(popularity_signal.get("kind") or "").strip():
        structured_missing.append("popularity_signal.kind")
    if (
        popularity_signal.get("kind") == "rank"
        and not str(popularity_signal.get("rank") or "").strip()
    ):
        structured_missing.append("popularity_signal.rank")

    currentness = manifest.get("currentness_basis")
    if not isinstance(currentness, dict) or not currentness:
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": ["currentness_basis"],
        }
    if not str(currentness.get("snapshot_date") or "").strip():
        structured_missing.append("currentness_basis.snapshot_date")
    if not str(manifest.get("diversity_policy") or "").strip():
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": ["diversity_policy"],
        }
    if structured_missing:
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": structured_missing,
        }
    if not str(raw.get("popularityRank") or "").strip():
        return {"ok": False, "error": "fixture_popularity_missing", "missing": ["popularityRank"]}
    if not str(raw.get("diversityBucket") or "").strip():
        return {"ok": False, "error": "fixture_diversity_missing", "missing": ["diversityBucket"]}
    if str(raw.get("freshnessStatus") or "") in CURRENT_FRESHNESS_CLAIMS:
        required_currentness = {"league", "game_patch", "passive_tree_version"}
        currentness_missing = sorted(
            key
            for key in required_currentness
            if not str(currentness.get(key) or "").strip()
            or str(currentness.get(key) or "").lower() == "unknown"
        )
        if currentness_missing:
            return {
                "ok": False,
                "error": "fixture_currentness_incomplete",
                "missing": currentness_missing,
            }
    return {"ok": True, "manifest": manifest}


def import_fixture_file(
    fixture_path: Path | None = None, *, db_path: Path | None = None
) -> dict[str, Any]:
    path = fixture_path or paths.mature_learning_seed_fixtures_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"fixture_file_unreadable: {exc}"}
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        return {"ok": False, "error": "fixture_cases_must_be_list"}

    initialize_store(db_path)
    pending: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    rejected: list[dict[str, Any]] = []
    for raw in cases:
        if str(raw.get("evidenceType") or raw.get("evidence_type") or "") == "user_feedback_local":
            rejected.append({"ok": False, "error": "seed_fixture_cannot_use_user_feedback"})
            continue
        manifest_result = validate_fixture_manifest(raw)
        if not manifest_result.get("ok"):
            rejected.append(manifest_result)
            continue
        sanitized = sanitize_mature_case(raw)
        if not sanitized.get("ok"):
            rejected.append(sanitized)
            continue
        pending.append((raw, sanitized, manifest_result["manifest"]))

    if rejected:
        return {"ok": False, "importedCases": 0, "rejected": rejected}

    con = connect(db_path)
    try:
        for raw, sanitized, manifest in pending:
            _insert_sanitized_fixture(con, raw, sanitized, manifest)
        con.commit()
    finally:
        con.close()
    return {"ok": True, "importedCases": len(pending), "rejected": []}


def _insert_sanitized_fixture(
    con: sqlite3.Connection,
    raw: dict[str, Any],
    sanitized: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    now = _now()
    source_ref = str(raw.get("sourceRef") or "")
    dedupe_hash = _stable_hash(
        {
            "sourceType": raw.get("sourceType"),
            "sourceRef": source_ref,
            "class": raw.get("class"),
            "ascendancy": raw.get("ascendancy"),
            "mainSkill": raw.get("mainSkill"),
        }
    )
    source_group_id = f"sg-{dedupe_hash[:12]}"
    snapshot_id = f"ss-{dedupe_hash[:12]}"
    case_id = f"case-{sanitized['external_id_hash'][:12]}"

    con.execute(
        """
        INSERT OR REPLACE INTO source_groups(
            source_group_id, dedupe_hash, canonical_source_type, canonical_source_ref,
            league, game_patch, passive_tree_version, created_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_group_id,
            dedupe_hash,
            str(raw.get("sourceType") or "manual_fixture"),
            source_ref,
            sanitized["league"],
            sanitized["game_patch"],
            sanitized["passive_tree_version"],
            now,
            now,
        ),
    )
    con.execute(
        """
        INSERT OR REPLACE INTO source_snapshots(
            id, source_group_id, source_type, source_url, fetched_at, league, game_patch,
            passive_tree_version, pob_version_or_commit, popularity_filter, diversity_bucket,
            raw_hash, sanitizer_version, freshness_status, attribution, usage_policy,
            fixture_manifest
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            source_group_id,
            str(raw.get("sourceType") or "manual_fixture"),
            source_ref,
            now,
            sanitized["league"],
            sanitized["game_patch"],
            sanitized["passive_tree_version"],
            str(raw.get("pobVersionOrCommit") or "unknown"),
            str(raw.get("popularityFilter") or "fixture-structured-popularity-required"),
            str(raw.get("diversityBucket") or "unknown"),
            _stable_hash(raw),
            SANITIZER_VERSION,
            sanitized["freshness_status"],
            str(raw.get("attribution") or source_ref),
            str(raw.get("usagePolicy") or "sanitized_fixture_only"),
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        ),
    )
    con.execute(
        """
        INSERT OR REPLACE INTO mature_build_cases(
            case_id, source_snapshot_id, external_id_hash, visibility, split, knowledge_scope,
            class, ascendancy, main_skill, damage_types, delivery_tags, defense_tags,
            mechanic_tags, lifecycle_stage, budget_band, popularity_rank, sample_weight,
            pob_modelability, sanitized_keypoints, numeric_ranges_or_metrics,
            redacted_fields_present, source_group_id, evidence_type, game_patch,
            passive_tree_version, league, freshness_status, compatibility_status,
            created_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            snapshot_id,
            sanitized["external_id_hash"],
            sanitized["visibility"],
            sanitized["split"],
            sanitized["knowledge_scope"],
            sanitized["class"],
            sanitized["ascendancy"],
            sanitized["main_skill"],
            json.dumps(sanitized["damage_types"], ensure_ascii=False),
            json.dumps(sanitized["delivery_tags"], ensure_ascii=False),
            json.dumps(sanitized["defense_tags"], ensure_ascii=False),
            json.dumps(sanitized["mechanic_tags"], ensure_ascii=False),
            sanitized["lifecycle_stage"],
            sanitized["budget_band"],
            sanitized["popularity_rank"],
            sanitized["sample_weight"],
            sanitized["pob_modelability"],
            json.dumps(sanitized["sanitized_keypoints"], ensure_ascii=False),
            json.dumps(sanitized["numeric_ranges_or_metrics"], ensure_ascii=False),
            json.dumps(sanitized["redacted_fields_present"], ensure_ascii=False),
            source_group_id,
            sanitized["evidence_type"],
            sanitized["game_patch"],
            sanitized["passive_tree_version"],
            sanitized["league"],
            sanitized["freshness_status"],
            sanitized["compatibility_status"],
            sanitized["created_at"],
            sanitized["last_seen_at"],
        ),
    )


def _case_tags(row: sqlite3.Row, column: str) -> list[str]:
    return _normalized_tag_list(_json_loads(row[column], []))


def _candidate_visibility_bucket(row: sqlite3.Row) -> str:
    if row["visibility"] == "creator_visible" and row["split"] == "train_context":
        return "creator_context"
    if row["visibility"] == "evaluator_only" and row["split"] == "eval_holdout":
        return "evaluator_holdout"
    return "quarantine"


def _candidate_knowledge_scope(row: sqlite3.Row) -> str:
    bucket = _candidate_visibility_bucket(row)
    if bucket != "creator_context":
        return "eval_ephemeral"
    return str(row["knowledge_scope"])


def _candidate_category_tags(row: sqlite3.Row) -> list[str]:
    damage = _case_tags(row, "damage_types")
    delivery = _case_tags(row, "delivery_tags")
    defenses = _case_tags(row, "defense_tags")
    mechanics = _case_tags(row, "mechanic_tags")
    stage = str(row["lifecycle_stage"])
    budget = _normalized_scalar(row["budget_band"])
    modelability = str(row["pob_modelability"])

    tags = {"ascendancy", "skill_gem"}
    if damage:
        tags.add("damage_scaling")
    if defenses:
        tags.add("defense_layer")
    if "projectile" in delivery or "projectile" in mechanics:
        tags.add("projectile")
    if "minion" in delivery or "minion" in mechanics or "minion_screen" in defenses:
        tags.add("minion")
    if "crit" in mechanics:
        tags.add("crit")
    if {"shock", "ignite", "freeze", "chill", "poison", "bleed"} & set(mechanics):
        tags.add("ailment")
    if "spirit" in mechanics:
        tags.add("spirit")
    if stage in {"endgame_budget", "endgame_final"}:
        tags.add("transition_gate")
        tags.add("endgame_only")
    if budget == "expensive":
        tags.add("expensive")
    elif budget in {"cheap", "low", "budget", "moderate"}:
        tags.add("budget_friendly")
    if modelability != "full":
        tags.add("pob_model_uncertain")
    return sorted(tags)


def _mechanism_role(row: sqlite3.Row) -> str:
    mechanics = set(_case_tags(row, "mechanic_tags"))
    defenses = _case_tags(row, "defense_tags")
    budget = _normalized_scalar(row["budget_band"])
    stage = str(row["lifecycle_stage"])

    if "spirit" in mechanics:
        return "enabler"
    if "mana_sustain" in mechanics or "mana" in mechanics:
        return "sustain_solution"
    if defenses and not _case_tags(row, "damage_types"):
        return "defensive_core"
    if budget == "expensive" or stage == "endgame_final":
        return "threshold"
    if "cooldown" in mechanics:
        return "quality_of_life"
    return "scaler"


def _required_prerequisites(row: sqlite3.Row) -> list[str]:
    mechanics = set(_case_tags(row, "mechanic_tags"))
    delivery = set(_case_tags(row, "delivery_tags"))
    stage = str(row["lifecycle_stage"])
    budget = _normalized_scalar(row["budget_band"])
    prerequisites: list[str] = []

    if stage == "endgame_final":
        prerequisites.append("endgame-final passive, ascendancy, and gear budget")
    elif stage == "endgame_budget":
        prerequisites.append("entry-endgame budget and stabilized mapping setup")
    elif stage == "maps_entry":
        prerequisites.append("campaign completion with capped core defenses")

    if budget == "expensive":
        prerequisites.append("expensive or build-defining item access")
    elif budget in {"moderate", "budget", "cheap", "low"}:
        prerequisites.append("basic trade or self-found upgrade budget")

    if "spirit" in mechanics:
        prerequisites.append("Spirit capacity and reservation plan")
    if "crit" in mechanics:
        prerequisites.append("critical strike foundation before scaling")
    if {"shock", "ignite", "freeze", "chill", "poison", "bleed"} & mechanics:
        prerequisites.append("reliable ailment application or scaling")
    if "cooldown" in mechanics:
        prerequisites.append("cooldown cadence or recovery support")
    if "minion" in mechanics or "minion" in delivery:
        prerequisites.append("minion level/count and Spirit support")
    if "projectile" in delivery:
        prerequisites.append("projectile coverage and scaling support")
    if row["pob_modelability"] != "full":
        prerequisites.append("PoB/engine caveat review before recommendation")

    if not prerequisites:
        prerequisites.append("stage-appropriate passive points, gems, and baseline gear")
    return prerequisites


def _starter_risk_reason(row: sqlite3.Row) -> str:
    keypoints = " ".join(_json_loads(row["sanitized_keypoints"], []))
    lower_keypoints = keypoints.lower()
    stage = str(row["lifecycle_stage"])
    budget = _normalized_scalar(row["budget_band"])
    risks: list[str] = []

    if stage in {"endgame_budget", "endgame_final"}:
        risks.append(f"starter risk: mature evidence is scoped to {stage}, not campaign proof")
    if budget == "expensive":
        risks.append("starter risk: expensive budget can hide leveling weaknesses")
    if any(word in lower_keypoints for word in ("starter-risk", "not a direct campaign", "caveat")):
        risks.append("starter risk: sanitized evidence explicitly flags a transition caveat")
    if row["pob_modelability"] != "full":
        risks.append("starter risk: PoB/engine modelability is incomplete")

    if not risks:
        return "No specific starter risk recorded; still verify before treating as starter viable."
    return "; ".join(risks) + "."


def _transition_gate_summary(row: sqlite3.Row, prerequisites: list[str]) -> str:
    preview = ", ".join(prerequisites[:4])
    if len(prerequisites) > 4:
        preview += ", ..."
    return (
        f"Transition only after reaching {row['lifecycle_stage']} and satisfying: {preview}. "
        "If unmet, keep the starter route and re-evaluate."
    )


def _unsafe_before_stage(stage: str) -> str:
    return {
        "endgame_final": "endgame_budget",
        "endgame_budget": "maps_entry",
        "maps_entry": "campaign_late",
        "campaign_late": "campaign_mid",
        "campaign_mid": "campaign_early",
        "campaign_early": "campaign_early",
    }.get(stage, "unknown_lifecycle")


def _candidate_from_case(row: sqlite3.Row) -> dict[str, Any]:
    damage = _case_tags(row, "damage_types")
    delivery = _case_tags(row, "delivery_tags")
    defenses = _case_tags(row, "defense_tags")
    mechanics = _case_tags(row, "mechanic_tags")
    keypoints = _json_loads(row["sanitized_keypoints"], [])
    category_tags = _candidate_category_tags(row)
    mechanism_role = _mechanism_role(row)
    prerequisites = _required_prerequisites(row)
    visibility_bucket = _candidate_visibility_bucket(row)
    knowledge_scope = _candidate_knowledge_scope(row)
    compatibility = (
        "quarantined" if visibility_bucket == "quarantine" else row["compatibility_status"]
    )

    # The semantic key intentionally excludes source refs, exact keypoints, and case ids. That lets
    # multiple mature cases support one broad technique while the boundary bucket prevents holdout
    # or quarantine evidence from being merged into creator-visible candidates.
    semantic_key = {
        "bucket": visibility_bucket,
        "scope": knowledge_scope,
        "class": _normalized_scalar(row["class"]),
        "ascendancy": _normalized_scalar(row["ascendancy"]),
        "main_skill": _normalized_scalar(row["main_skill"]),
        "damage": damage,
        "delivery": delivery,
        "defenses": defenses,
        "mechanics": mechanics,
        "stage": row["lifecycle_stage"],
        "budget": _normalized_scalar(row["budget_band"]),
        "category_tags": category_tags,
        "mechanism_role": mechanism_role,
        "league": _normalized_scalar(row["league"]),
        "game_patch": _normalized_scalar(row["game_patch"]),
        "passive_tree_version": _normalized_scalar(row["passive_tree_version"]),
    }
    candidate_id = f"tc-{_stable_hash(semantic_key)[:16]}"
    statement = (
        f"{row['ascendancy']} {row['main_skill']} mature cases suggest a "
        f"{mechanism_role} pattern for {row['lifecycle_stage']}."
    )
    summary = (
        f"Research candidate only: {row['class']}/{row['ascendancy']} using "
        f"{row['main_skill']} with tags {', '.join(category_tags[:8])}. "
        "Validate with lifecycle gates and PoB before recommendation."
    )
    if keypoints:
        summary += f" Sanitized note count: {len(keypoints)}."

    return {
        "candidate_id": candidate_id,
        "knowledge_scope": knowledge_scope,
        "statement": statement,
        "summary_for_llm": summary,
        "category_tags": category_tags,
        "lifecycle_stage": row["lifecycle_stage"],
        "mechanism_role": mechanism_role,
        "evidence_type": row["evidence_type"],
        "confidence": "low",
        "promotion_status": "quarantined" if visibility_bucket == "quarantine" else "candidate",
        "game_patch": row["game_patch"],
        "passive_tree_version": row["passive_tree_version"],
        "league": row["league"],
        "freshness_status": row["freshness_status"],
        "compatibility_status": compatibility,
        "budget_band": row["budget_band"],
        "pob_modelability": row["pob_modelability"],
        "required_prerequisites": prerequisites,
        "starter_risk_reason": _starter_risk_reason(row),
        "transition_gate_summary": _transition_gate_summary(row, prerequisites),
        "unsafe_before_stage": _unsafe_before_stage(str(row["lifecycle_stage"])),
    }


def _upsert_candidate(con: sqlite3.Connection, candidate: dict[str, Any], now: str) -> None:
    con.execute(
        """
        INSERT INTO technique_candidates(
            candidate_id, knowledge_scope, statement, summary_for_llm, category_tags,
            lifecycle_stage, mechanism_role, evidence_type, source_count, support_count,
            contradiction_count, confidence, promotion_status, game_patch,
            passive_tree_version, league, freshness_status, compatibility_status,
            budget_band, pob_modelability, required_prerequisites, starter_risk_reason,
            transition_gate_summary, unsafe_before_stage, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(candidate_id) DO UPDATE SET
            statement = excluded.statement,
            summary_for_llm = excluded.summary_for_llm,
            category_tags = excluded.category_tags,
            lifecycle_stage = excluded.lifecycle_stage,
            mechanism_role = excluded.mechanism_role,
            evidence_type = excluded.evidence_type,
            confidence = excluded.confidence,
            promotion_status = CASE
                WHEN technique_candidates.promotion_status IN ('promoted', 'rejected', 'stale')
                    THEN technique_candidates.promotion_status
                WHEN excluded.promotion_status = 'quarantined'
                    THEN 'quarantined'
                ELSE excluded.promotion_status
            END,
            game_patch = excluded.game_patch,
            passive_tree_version = excluded.passive_tree_version,
            league = excluded.league,
            freshness_status = excluded.freshness_status,
            compatibility_status = excluded.compatibility_status,
            budget_band = excluded.budget_band,
            pob_modelability = excluded.pob_modelability,
            required_prerequisites = excluded.required_prerequisites,
            starter_risk_reason = excluded.starter_risk_reason,
            transition_gate_summary = excluded.transition_gate_summary,
            unsafe_before_stage = excluded.unsafe_before_stage,
            last_seen_at = excluded.last_seen_at
        """,
        (
            candidate["candidate_id"],
            candidate["knowledge_scope"],
            candidate["statement"],
            candidate["summary_for_llm"],
            json.dumps(candidate["category_tags"], ensure_ascii=False),
            candidate["lifecycle_stage"],
            candidate["mechanism_role"],
            candidate["evidence_type"],
            candidate["confidence"],
            candidate["promotion_status"],
            candidate["game_patch"],
            candidate["passive_tree_version"],
            candidate["league"],
            candidate["freshness_status"],
            candidate["compatibility_status"],
            candidate["budget_band"],
            candidate["pob_modelability"],
            json.dumps(candidate["required_prerequisites"], ensure_ascii=False),
            candidate["starter_risk_reason"],
            candidate["transition_gate_summary"],
            candidate["unsafe_before_stage"],
            now,
            now,
        ),
    )


def _upsert_candidate_evidence(
    con: sqlite3.Connection, row: sqlite3.Row, candidate_id: str, now: str
) -> str:
    relation = "supports"
    evidence_id = f"ev-{_stable_hash({'case_id': row['case_id'], 'relation': relation, 'extraction_method': EXTRACTION_METHOD})[:16]}"
    creator_visible = 1 if _candidate_visibility_bucket(row) == "creator_context" else 0
    con.execute(
        """
        INSERT INTO candidate_evidence(
            evidence_id, candidate_id, case_id, source_snapshot_id, source_group_id,
            relation, visibility, split, knowledge_scope, extraction_method,
            extractor_version, confidence, creator_visible, created_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(evidence_id) DO UPDATE SET
            candidate_id = excluded.candidate_id,
            source_snapshot_id = excluded.source_snapshot_id,
            source_group_id = excluded.source_group_id,
            relation = excluded.relation,
            visibility = excluded.visibility,
            split = excluded.split,
            knowledge_scope = excluded.knowledge_scope,
            extraction_method = excluded.extraction_method,
            extractor_version = excluded.extractor_version,
            confidence = excluded.confidence,
            creator_visible = excluded.creator_visible,
            last_seen_at = excluded.last_seen_at
        """,
        (
            evidence_id,
            candidate_id,
            row["case_id"],
            row["source_snapshot_id"],
            row["source_group_id"],
            relation,
            row["visibility"],
            row["split"],
            row["knowledge_scope"],
            EXTRACTION_METHOD,
            EXTRACTOR_VERSION,
            0.55,
            creator_visible,
            now,
            now,
        ),
    )
    return evidence_id


def _delete_stale_candidate_evidence(con: sqlite3.Connection, evidence_ids: set[str]) -> None:
    """Remove evidence emitted by this extractor when its source case is no longer scanned."""
    if evidence_ids:
        placeholders = ",".join("?" for _ in evidence_ids)
        con.execute(
            f"""
            DELETE FROM candidate_evidence
            WHERE extraction_method = ?
              AND evidence_id NOT IN ({placeholders})
            """,
            (EXTRACTION_METHOD, *sorted(evidence_ids)),
        )
        return
    con.execute(
        "DELETE FROM candidate_evidence WHERE extraction_method = ?",
        (EXTRACTION_METHOD,),
    )


def _refresh_candidate_counts(con: sqlite3.Connection) -> None:
    # Candidate counters are cached projections only. Evidence rows remain the authority so tests
    # can deliberately corrupt counters and verify the next extraction restores them.
    con.execute(
        """
        UPDATE technique_candidates
        SET
            source_count = (
                SELECT count(DISTINCT ce.source_group_id)
                FROM candidate_evidence ce
                WHERE ce.candidate_id = technique_candidates.candidate_id
                  AND ce.relation = 'supports'
            ),
            support_count = (
                SELECT count(*)
                FROM candidate_evidence ce
                WHERE ce.candidate_id = technique_candidates.candidate_id
                  AND ce.relation = 'supports'
            ),
            contradiction_count = (
                SELECT count(*)
                FROM candidate_evidence ce
                WHERE ce.candidate_id = technique_candidates.candidate_id
                  AND ce.relation = 'contradicts'
            )
        """
    )


def extract_technique_candidates(db_path: Path | None = None) -> dict[str, Any]:
    """Extract low-trust technique candidates from sanitized mature cases.

    Phase 3N.2 deliberately does not expose retrieval or route-synthesis behavior. The function only
    creates deterministic candidate/evidence rows so later phases can add visibility-safe retrieval.
    """
    initialize_store(db_path)
    con = connect(db_path)
    try:
        rows = con.execute("SELECT * FROM mature_build_cases ORDER BY case_id").fetchall()
        now = _now()
        candidate_ids: set[str] = set()
        evidence_ids: set[str] = set()
        for row in rows:
            candidate = _candidate_from_case(row)
            _upsert_candidate(con, candidate, now)
            evidence_id = _upsert_candidate_evidence(con, row, candidate["candidate_id"], now)
            candidate_ids.add(candidate["candidate_id"])
            evidence_ids.add(evidence_id)
        _delete_stale_candidate_evidence(con, evidence_ids)
        _refresh_candidate_counts(con)
        con.commit()
    finally:
        con.close()
    return {
        "ok": True,
        "casesScanned": len(rows),
        "candidatesUpserted": len(candidate_ids),
        "evidenceUpserted": len(evidence_ids),
        "extractorVersion": EXTRACTOR_VERSION,
    }
