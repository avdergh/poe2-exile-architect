# Mature Build Learning 3N.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 3N.1 mature-build learning foundation: SQLite schema, fixture manifest
validation, allowlist sanitizer, redaction/copyability tests, and strict evidence-boundary guards.

**Architecture:** Add a new `server.knowledge.mature_learning` module as a deterministic,
offline-first store layer. SQLite is the trusted fact store; the first slice creates schema and
safe fixture ingestion only, without candidate extraction, retrieval influence, route synthesis
changes, active expiration/downweighting, auto-promotion, vector DB, or graph DB infrastructure.

**Tech Stack:** Python 3.11 standard library (`sqlite3`, `json`, `hashlib`, `dataclasses` if useful),
pytest, existing `server.paths` user-data path conventions, project verification via
`.tools\uv\uv.exe` and `scripts\verify.ps1 quick`.

---

## Scope guard

Phase 3N.1 must produce a working, testable data backbone only.

In scope:

- SQLite database creation and schema versioning.
- User-data store path ownership.
- Tiny curated fixture manifest format and deterministic fixture import.
- Source-group/source-snapshot/sanitized-case persistence.
- Schema tables for future candidates/evidence/edges, even if not populated yet.
- Recursive allowlist sanitizer for mature build cases.
- Redaction and copyability/reconstruction guards.
- Validation for schema migrations, `visibility`, `split`, `knowledge_scope`, source eligibility,
  structured popularity/currentness evidence, and local-feedback isolation.
- Tests proving no raw PoB/tree/gear/gem content is persisted.

Out of scope for this slice:

- Live poe.ninja/forum/pobb.in crawler.
- Technique candidate extraction.
- Candidate retrieval or FTS.
- Route synthesis behavior changes.
- Teacher-student evaluation loop.
- Active knowledge expiration/downweighting.
- Auto-promotion to durable technique cards.
- Vector DB or external graph DB.

## File structure

- Create: `docs/architecture/phase-03n1-mature-build-learning-store.md`
  - Local technical doc for schema, path ownership, fixture manifest, sanitizer contract, and
    non-copyability boundaries.
- Modify: `server/paths.py`
  - Add `mature_learning_path()` returning the writable user-data SQLite path.
  - Add `mature_learning_seed_fixtures_path()` returning bundled seed fixture JSON.
- Create: `server/knowledge/mature_learning.py`
  - Owns schema creation, validation constants, sanitizer, copyability guard, deterministic fixture
    import, and safe insert helpers.
- Create: `data/mature_build_learning/seed_cases.json`
  - Tiny sanitized fixture corpus with at least four class/ascendancy buckets and explicit
    structured popularity/provenance/currentness rationale.
- Create: `tests/test_mature_learning.py`
  - RED/GREEN tests for schema, fixtures, sanitizer, copyability, visibility/split/scope, and local
    feedback isolation.
- Modify: `docs/PROJECT_SPEC.md`
  - Track Phase 3N.1 plan/implementation status.
- Modify: `docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md`
  - Check off tasks as they complete.

---

### Task 1: Local technical doc for 3N.1 store boundaries

**Files:**

- Create: `docs/architecture/phase-03n1-mature-build-learning-store.md`
- Modify: `docs/PROJECT_SPEC.md`
- Modify: `docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md`

- [x] **Step 1: Create the architecture doc**

Create `docs/architecture/phase-03n1-mature-build-learning-store.md` with this content:

```markdown
# Phase 3N.1 Mature Build Learning Store

Last updated: 2026-06-27

## Purpose

Phase 3N.1 creates the mature-build learning data backbone. It stores only sanitized, attributed,
non-copyable mature build cases and the schema needed for later technique candidates.

This slice does not change build generation, route synthesis, recommendation ranking, memory
promotion, or knowledge expiration behavior.

## Store ownership

The mature-learning SQLite database is a mutable user-data artifact at
`paths.mature_learning_path()`. Bundled seed fixtures live under
`data/mature_build_learning/seed_cases.json` and are imported into the user-data store when the
caller explicitly initializes or imports them.

The bundled fixture file is not a raw build archive. It contains only sanitized fixture rows plus
manifest metadata proving why each row represents a popular mature-case stand-in.

## Schema and migration safety

The Phase 3N.1 migration creates these tables:

- `meta`
- `source_groups`
- `source_snapshots`
- `mature_build_cases`
- `technique_candidates`
- `candidate_evidence`
- `technique_edges`

Phase 3N.1 populates only source groups, source snapshots, and mature build cases. Candidate and
edge tables exist so later slices do not need a disruptive migration.

Migration rules:

- new database: create schema v1 and write `schema_version = 1`;
- existing v1 database: no-op/idempotent initialization;
- future database `schema_version > 1`: refuse to initialize/open through this module;
- migrations must never downgrade a database by overwriting `schema_version`.

`candidate_evidence` has a stable `evidence_id` primary key because later edge rows and promotion
logic need evidence ids. `technique_edges` has a stable `edge_id` primary key for deterministic
edge imports and later review.

## Fixture policy

Fixture import requires:

- current or explicitly unknown `league`, `game_patch`, and `passive_tree_version`;
- `fixture_manifest.eligibility_basis`;
- `fixture_manifest.popularity_signal`;
- `fixture_manifest.currentness_basis`;
- `fixture_manifest.diversity_policy`;
- deterministic ids or deterministic hash inputs;
- diversity metadata so one class or ascendancy does not dominate the seed set.

Manual fixtures without structured popularity/provenance/currentness rationale are rejected. If a
row claims `freshnessStatus: verified_current` or `current_metadata_only`, then `league`,
`gamePatch`, and `passiveTreeVersion` must be present and must not be `unknown`.

## Sanitization policy

Sanitization is allowlist-based. Allowed fields include class, ascendancy, main skill, broad damage
types, delivery tags, defense tags, mechanic tags, lifecycle stage, budget band, popularity metadata,
modelability, coarse keypoints, aggregate numeric ranges, freshness metadata, and attribution.

Forbidden persisted content includes raw PoB code, pobb.in raw code, raw XML, full passive trees,
ordered passive node lists, full gear lists, exact affixes, full gem/support links, copied guide
text, and enough ordered keypoints to reconstruct the original build.

The sanitizer scans recursively, not just top-level fields. Raw/copyable content hidden inside
`numericRangesOrMetrics`, `fixtureManifest`, keypoints, attribution, or any other allowed container
is rejected.

`numericRangesOrMetrics` accepts only aggregate range objects such as
`{"min": 100000, "median": 500000, "max": 1200000, "n": 8}` with optional percentile fields. It
must reject arbitrary stat dumps, nested gear/tree/gem fields, booleans, non-numeric values,
non-finite values, and `min > max`.

## Copyability guard

The sanitizer rejects records that are too reconstructable even if they avoid explicitly forbidden
field names. The first guard is intentionally conservative:

- too many named unique items is rejected;
- too many passive anchors or ordered passive hints is rejected;
- full support-link-like lists are rejected;
- exact item slot details are rejected;
- copied long guide prose is rejected.
- PoB-code-like encoded blobs in any persisted text field are rejected.

False positives are acceptable in Phase 3N.1. A mature case that is too detailed should be
quarantined or summarized more coarsely.

## Visibility, split, and scope boundaries

Only these combinations are valid:

| visibility | split | behavior |
| --- | --- | --- |
| `creator_visible` | `train_context` | Can become creator context in later slices. |
| `evaluator_only` | `eval_holdout` | Evaluator-only; never creator context. |
| `quarantined` | `quarantine` | Not usable until manually cleared. |

`user_feedback_local` evidence must use `knowledge_scope: local_user`. It cannot be inserted as
`global_seed` and cannot enter the bundled seed fixture corpus even when its scope is correctly
`local_user`. Future local feedback ingestion must use a separate local-memory path.

## Expiration fields

Freshness and compatibility fields are stored as inert metadata only. Phase 3N.1 must not use these
fields to change confidence, ranking, promotion status, retrieval order, or route synthesis.
```

- [x] **Step 2: Update project spec status**

In `docs/PROJECT_SPEC.md`, update the Phase 3N current work status to say that Phase 3N.1 is in
implementation planning/execution and that this slice is limited to schema, fixture manifest,
sanitizer, and redaction/copyability tests.

- [x] **Step 3: Mark Task 1 complete in this plan**

Change the Task 1 checkboxes from `[ ]` to `[x]` after the doc and spec update are saved.

- [ ] **Step 4: Commit Task 1**

Run:

```powershell
git add docs/architecture/phase-03n1-mature-build-learning-store.md docs/PROJECT_SPEC.md docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md
git commit -m "docs: plan mature learning store foundation"
```

Expected: commit succeeds.

---

### Task 2: RED tests for SQLite schema and path ownership

**Files:**

- Modify: `server/paths.py`
- Create: `server/knowledge/mature_learning.py`
- Create: `tests/test_mature_learning.py`
- Modify: `docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md`

- [ ] **Step 1: Write failing path/schema tests**

Create `tests/test_mature_learning.py` with these initial tests:

```python
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
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py -q
```

Expected: FAIL because `paths.mature_learning_path`, `server.knowledge.mature_learning`, and
`SchemaVersionError` do not exist yet.

- [ ] **Step 3: Add path helpers**

In `server/paths.py`, add:

```python
def mature_learning_path() -> Path:
    """Writable Phase 3N mature-build learning store.

    Mature build learning is release-seeded but locally mutable. The SQLite database belongs in
    user-data so fixture imports, later revalidation metadata, and local-only feedback boundaries do
    not modify bundled project files.
    """
    return user_data_dir() / "mature_build_learning.sqlite"


def mature_learning_seed_fixtures_path() -> Path:
    """Bundled sanitized seed fixtures for the mature-learning store."""
    return BUNDLE_ROOT / "data" / "mature_build_learning" / "seed_cases.json"
```

- [ ] **Step 4: Add minimal schema module**

Create `server/knowledge/mature_learning.py` with:

```python
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
```

- [ ] **Step 5: Run GREEN**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git add server/paths.py server/knowledge/mature_learning.py tests/test_mature_learning.py docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md
git commit -m "feat: add mature learning sqlite schema"
```

Expected: commit succeeds.

---

### Task 3: RED/GREEN sanitizer and copyability guard

**Files:**

- Modify: `server/knowledge/mature_learning.py`
- Modify: `tests/test_mature_learning.py`
- Modify: `docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md`

- [ ] **Step 1: Add failing sanitizer tests**

Append these tests to `tests/test_mature_learning.py`:

```python
def _raw_case(**overrides):
    base = {
        "sourceType": "manual_fixture",
        "sourceRef": "fixture://spark-stormweaver",
        "league": "Dawn of the Hunt",
        "gamePatch": "0.5.4",
        "passiveTreeVersion": "0_5",
        "class": "Sorceress",
        "ascendancy": "Stormweaver",
        "mainSkill": "Spark",
        "damageTypes": ["lightning"],
        "deliveryTags": ["spell", "projectile"],
        "defenseTags": ["energy_shield", "recharge"],
        "mechanicTags": ["crit", "shock"],
        "lifecycleStage": "endgame_final",
        "budgetBand": "expensive",
        "popularityRank": 1,
        "sampleWeight": 1.0,
        "pobModelability": "partial",
        "keypoints": [
            "Scales lightning spell damage through broad +level and crit investment.",
            "Uses an endgame-only defensive identity; not a direct campaign starter.",
        ],
        "numericRangesOrMetrics": {
            "TotalDPS": {"min": 100000, "median": 500000, "max": 1200000, "n": 8}
        },
        "visibility": "creator_visible",
        "split": "train_context",
        "knowledgeScope": "global_seed",
        "evidenceType": "poe_ninja_hot",
        "freshnessStatus": "verified_current",
        "compatibilityStatus": "current",
        "fixtureManifest": {
            "eligibility_basis": "manual_stand_in_for_hot_sample",
            "popularity_signal": {"kind": "rank", "rank": 1, "source": "fixture_manifest"},
            "currentness_basis": {
                "league": "Dawn of the Hunt",
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "snapshot_date": "2026-06-27",
            },
            "diversity_policy": "Popularity filtered before diversity cap.",
        },
    }
    base.update(overrides)
    return base


def test_sanitize_mature_case_keeps_allowed_coarse_fields():
    sanitized = mature_learning.sanitize_mature_case(_raw_case())

    assert sanitized["class"] == "Sorceress"
    assert sanitized["ascendancy"] == "Stormweaver"
    assert sanitized["main_skill"] == "Spark"
    assert sanitized["damage_types"] == ["lightning"]
    assert sanitized["delivery_tags"] == ["spell", "projectile"]
    assert sanitized["redacted_fields_present"] == []
    assert sanitized["sanitized_keypoints"]
    assert "pobCode" not in sanitized
    assert "passiveTree" not in sanitized


def test_sanitize_rejects_explicit_raw_copyable_fields():
    raw = _raw_case(
        pobCode="eNrtVerySecret",
        passiveTree={"nodes": [1, 2, 3]},
        gear={"Ring 1": {"name": "Exact Item"}},
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert "forbidden_copyable_fields" in result["error"]
    assert {"pobCode", "passiveTree", "gear"} <= set(result["redactedFieldsPresent"])


def test_copyability_guard_rejects_reconstructable_keypoints():
    raw = _raw_case(
        keypoints=[
            "Unique: Exact Ring",
            "Unique: Exact Helmet",
            "Unique: Exact Body Armour",
            "Passive path: node 1 -> node 2 -> node 3 -> node 4",
            "Supports: A, B, C, D, E",
        ]
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"
    assert "too_many_named_uniques" in result["copyabilityFlags"]
    assert "ordered_passive_path" in result["copyabilityFlags"]
    assert "full_support_link_like" in result["copyabilityFlags"]


def test_sanitize_rejects_nested_forbidden_copyable_fields():
    raw = _raw_case(
        numericRangesOrMetrics={
            "TotalDPS": {"min": 100000, "max": 200000, "n": 3},
            "gear": {"Ring 1": "Exact copied item"},
        }
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert result["error"] == "forbidden_copyable_fields"
    assert "numericRangesOrMetrics.gear" in result["redactedFieldsPresent"]


def test_sanitize_rejects_pob_code_like_text_anywhere():
    raw = _raw_case(
        keypoints=[
            "Broad summary.",
            "eNrt" + ("A" * 180),
        ]
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"
    assert "pob_code_like_blob" in result["copyabilityFlags"]


def test_sanitize_rejects_non_aggregate_numeric_metrics():
    raw = _raw_case(
        numericRangesOrMetrics={
            "TotalDPS": {"value": 123456, "configTab": {"enemyIsBoss": "Uber"}},
        }
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert result["error"] == "invalid_numeric_ranges_or_metrics"


def test_sanitize_rejects_non_finite_numeric_metrics():
    raw = _raw_case(
        numericRangesOrMetrics={
            "TotalDPS": {"min": 100000, "median": float("inf"), "max": 200000, "n": 3},
        }
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert result["error"] == "invalid_numeric_ranges_or_metrics"


def test_sanitize_rejects_current_claim_with_unknown_patch_tree_or_league():
    result = mature_learning.sanitize_mature_case(
        _raw_case(league="unknown", freshnessStatus="verified_current")
    )

    assert result["ok"] is False
    assert result["error"] == "current_claim_missing_version_metadata"
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py -q
```

Expected: FAIL because `sanitize_mature_case` is not implemented.

- [ ] **Step 3: Add sanitizer constants and helper functions**

In `server/knowledge/mature_learning.py`, add these imports:

```python
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any
```

Add:

```python
SANITIZER_VERSION = "phase3n1-v1"

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
}

VALID_VISIBILITY_SPLITS = {
    ("creator_visible", "train_context"),
    ("evaluator_only", "eval_holdout"),
    ("quarantined", "quarantine"),
}

VALID_KNOWLEDGE_SCOPES = {"global_seed", "local_user", "eval_ephemeral"}
VALID_MODELABILITY = {"full", "partial", "not_modelable", "unknown"}
VALID_FRESHNESS = {
    "current_metadata_only",
    "verified_current",
    "stale",
    "needs_revalidation",
    "unknown",
}
VALID_COMPATIBILITY = {"current", "stale", "unknown", "quarantined"}
CURRENT_FRESHNESS_CLAIMS = {"verified_current", "current_metadata_only"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _as_string_list(value: Any, *, max_items: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:max_items]:
        text = str(item).strip()
        if text:
            out.append(text[:240])
    return out


def _find_forbidden_paths(value: Any, *, path: str = "") -> list[str]:
    """Find forbidden raw-build fields anywhere inside a fixture payload."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if key_text in FORBIDDEN_COPYABLE_FIELDS:
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
        for key, cell in range_value.items():
            if not _is_number(cell):
                return {}, "invalid_numeric_ranges_or_metrics"
        if float(range_value["min"]) > float(range_value["max"]):
            return {}, "invalid_numeric_ranges_or_metrics"
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
```

- [ ] **Step 4: Add `sanitize_mature_case`**

In `server/knowledge/mature_learning.py`, add:

```python
def sanitize_mature_case(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized mature-case dict or an explicit rejection result.

    The sanitizer is intentionally allowlist-first. It never tries to preserve raw build fields and
    relies on a conservative copyability guard to reject records that could reconstruct a mature
    build even through innocently named summaries.
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
    if freshness in CURRENT_FRESHNESS_CLAIMS and (
        str(raw.get("league") or "").lower() == "unknown"
        or str(raw.get("gamePatch") or "").lower() == "unknown"
        or str(raw.get("passiveTreeVersion") or "").lower() == "unknown"
        or not str(raw.get("league") or "").strip()
        or not str(raw.get("gamePatch") or "").strip()
        or not str(raw.get("passiveTreeVersion") or "").strip()
    ):
        return {"ok": False, "error": "current_claim_missing_version_metadata"}

    numeric_ranges, numeric_error = _validate_numeric_ranges(raw.get("numericRangesOrMetrics") or {})
    if numeric_error:
        return {"ok": False, "error": numeric_error}

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
        "lifecycle_stage": str(raw.get("lifecycleStage") or "unknown_lifecycle"),
        "budget_band": str(raw.get("budgetBand") or "unknown"),
        "popularity_rank": raw.get("popularityRank"),
        "sample_weight": float(raw.get("sampleWeight") or 1.0),
        "pob_modelability": modelability,
        "sanitized_keypoints": keypoints,
        "numeric_ranges_or_metrics": numeric_ranges,
        "redacted_fields_present": [],
        "visibility": str(raw.get("visibility")),
        "split": str(raw.get("split")),
        "knowledge_scope": str(raw.get("knowledgeScope")),
        "evidence_type": str(raw.get("evidenceType") or "manual_fixture"),
        "game_patch": str(raw.get("gamePatch") or "unknown"),
        "passive_tree_version": str(raw.get("passiveTreeVersion") or "unknown"),
        "league": str(raw.get("league") or "unknown"),
        "freshness_status": freshness,
        "compatibility_status": compatibility,
        "created_at": now,
        "last_seen_at": now,
    }
```

- [ ] **Step 5: Run GREEN**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add server/knowledge/mature_learning.py tests/test_mature_learning.py docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md
git commit -m "feat: add mature build sanitizer"
```

Expected: commit succeeds.

---

### Task 4: RED/GREEN fixture manifest validation and deterministic import

**Files:**

- Create: `data/mature_build_learning/seed_cases.json`
- Modify: `server/knowledge/mature_learning.py`
- Modify: `tests/test_mature_learning.py`
- Modify: `docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md`

- [ ] **Step 1: Add failing fixture import tests**

Append these tests to `tests/test_mature_learning.py`:

```python
def test_fixture_manifest_requires_structured_popularity_currentness_and_diversity():
    raw = _raw_case(fixtureManifest={"eligibility_basis": "manual_stand_in_for_hot_sample"})

    result = mature_learning.validate_fixture_manifest(raw)

    assert result["ok"] is False
    assert "fixture_manifest_incomplete" in result["error"]
    assert "popularity_signal" in result["missing"]
    assert "currentness_basis" in result["missing"]
    assert "diversity_policy" in result["missing"]


def test_fixture_manifest_requires_rank_signal_and_snapshot_date():
    raw = _raw_case(
        fixtureManifest={
            "eligibility_basis": "manual_stand_in_for_hot_sample",
            "popularity_signal": {"kind": "rank"},
            "currentness_basis": {
                "league": "Dawn of the Hunt",
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
            },
            "diversity_policy": "Popularity filtered before diversity cap.",
        }
    )

    result = mature_learning.validate_fixture_manifest(raw)

    assert result["ok"] is False
    assert "popularity_signal.rank" in result["missing"]
    assert "currentness_basis.snapshot_date" in result["missing"]


def test_import_seed_fixtures_persists_sanitized_cases(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    fixture_path.write_text(
        """
{
  "schemaVersion": 1,
  "fixtureSet": "phase3n1-test",
  "cases": [
    {
      "sourceType": "manual_fixture",
      "sourceRef": "fixture://spark-stormweaver",
      "league": "Dawn of the Hunt",
      "gamePatch": "0.5.4",
      "passiveTreeVersion": "0_5",
      "class": "Sorceress",
      "ascendancy": "Stormweaver",
      "mainSkill": "Spark",
      "damageTypes": ["lightning"],
      "deliveryTags": ["spell", "projectile"],
      "defenseTags": ["energy_shield"],
      "mechanicTags": ["crit", "shock"],
      "lifecycleStage": "endgame_final",
      "budgetBand": "expensive",
      "popularityRank": 1,
      "sampleWeight": 1.0,
      "pobModelability": "partial",
      "keypoints": ["Endgame lightning caster scaling fixture."],
      "numericRangesOrMetrics": {},
      "visibility": "creator_visible",
      "split": "train_context",
      "knowledgeScope": "global_seed",
      "evidenceType": "poe_ninja_hot",
      "freshnessStatus": "verified_current",
      "compatibilityStatus": "current",
      "diversityBucket": "stormweaver-lightning-spell",
      "fixtureManifest": {
        "eligibility_basis": "manual_stand_in_for_hot_sample",
        "popularity_signal": {"kind": "rank", "rank": 1, "source": "fixture_manifest"},
        "currentness_basis": {
          "league": "Dawn of the Hunt",
          "game_patch": "0.5.4",
          "passive_tree_version": "0_5",
          "snapshot_date": "2026-06-27"
        },
        "diversity_policy": "Popularity filtered before diversity balancing."
      }
    },
    {
      "sourceType": "manual_fixture",
      "sourceRef": "fixture://deadeye-projectile",
      "league": "Dawn of the Hunt",
      "gamePatch": "0.5.4",
      "passiveTreeVersion": "0_5",
      "class": "Ranger",
      "ascendancy": "Deadeye",
      "mainSkill": "Lightning Arrow",
      "damageTypes": ["lightning", "physical"],
      "deliveryTags": ["attack", "projectile"],
      "defenseTags": ["evasion"],
      "mechanicTags": ["projectile"],
      "lifecycleStage": "endgame_budget",
      "budgetBand": "moderate",
      "popularityRank": 2,
      "sampleWeight": 1.0,
      "pobModelability": "partial",
      "keypoints": ["Projectile attack fixture with starter-risk caveat."],
      "numericRangesOrMetrics": {},
      "visibility": "evaluator_only",
      "split": "eval_holdout",
      "knowledgeScope": "global_seed",
      "evidenceType": "poe_ninja_hot",
      "freshnessStatus": "verified_current",
      "compatibilityStatus": "current",
      "diversityBucket": "deadeye-projectile-attack",
      "fixtureManifest": {
        "eligibility_basis": "manual_stand_in_for_hot_sample",
        "popularity_signal": {"kind": "rank", "rank": 2, "source": "fixture_manifest"},
        "currentness_basis": {
          "league": "Dawn of the Hunt",
          "game_patch": "0.5.4",
          "passive_tree_version": "0_5",
          "snapshot_date": "2026-06-27"
        },
        "diversity_policy": "Held out for later evaluator tests after popularity filter."
      }
    }
  ]
}
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"
    mature_learning.initialize_store(db_path)

    result = mature_learning.import_fixture_file(fixture_path, db_path=db_path)

    assert result["ok"] is True
    assert result["importedCases"] == 2
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT count(*) FROM source_groups").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM source_snapshots").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM mature_build_cases").fetchone()[0] == 2
    rows = con.execute("SELECT visibility, split FROM mature_build_cases ORDER BY case_id").fetchall()
    assert {tuple(row) for row in rows} == {
        ("creator_visible", "train_context"),
        ("evaluator_only", "eval_holdout"),
    }
    versions = con.execute("SELECT DISTINCT sanitizer_version FROM source_snapshots").fetchall()
    assert {row[0] for row in versions} == {mature_learning.SANITIZER_VERSION}


def test_import_fixture_file_is_idempotent(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    raw = _raw_case(sourceRef="fixture://idempotent-case")
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "idempotent", "cases": [raw]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"

    first = mature_learning.import_fixture_file(fixture_path, db_path=db_path)
    second = mature_learning.import_fixture_file(fixture_path, db_path=db_path)

    assert first["ok"] is True
    assert second["ok"] is True
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT count(*) FROM source_groups").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM source_snapshots").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM mature_build_cases").fetchone()[0] == 1


def test_seed_fixture_import_rejects_user_feedback_even_when_local_scope(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    raw = _raw_case(evidenceType="user_feedback_local", knowledgeScope="local_user")
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "feedback", "cases": [raw]}),
        encoding="utf-8",
    )

    result = mature_learning.import_fixture_file(fixture_path, db_path=tmp_path / "mature.sqlite")

    assert result["ok"] is False
    assert result["importedCases"] == 0
    assert result["rejected"][0]["error"] == "seed_fixture_cannot_use_user_feedback"
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py -q
```

Expected: FAIL because fixture validation/import functions do not exist.

- [ ] **Step 3: Add bundled seed fixture file**

Create `data/mature_build_learning/seed_cases.json` with four sanitized fixture rows. Use the two
rows from the test above, plus:

```json
{
  "sourceType": "manual_fixture",
  "sourceRef": "fixture://witchhunter-grenade",
  "league": "Dawn of the Hunt",
  "gamePatch": "0.5.4",
  "passiveTreeVersion": "0_5",
  "class": "Mercenary",
  "ascendancy": "Witchhunter",
  "mainSkill": "Explosive Grenade",
  "damageTypes": ["fire", "physical"],
  "deliveryTags": ["attack", "area", "projectile"],
  "defenseTags": ["armour", "evasion"],
  "mechanicTags": ["grenade", "cooldown"],
  "lifecycleStage": "endgame_budget",
  "budgetBand": "moderate",
  "popularityRank": 3,
  "sampleWeight": 1.0,
  "pobModelability": "partial",
  "keypoints": ["Grenade-style attack fixture focused on cooldown and area scaling."],
  "numericRangesOrMetrics": {},
  "visibility": "creator_visible",
  "split": "train_context",
  "knowledgeScope": "global_seed",
  "evidenceType": "poe_ninja_hot",
  "freshnessStatus": "verified_current",
  "compatibilityStatus": "current",
  "diversityBucket": "witchhunter-grenade-attack",
  "fixtureManifest": {
    "eligibility_basis": "manual_stand_in_for_hot_sample",
    "popularity_signal": {"kind": "rank", "rank": 3, "source": "fixture_manifest"},
    "currentness_basis": {
      "league": "Dawn of the Hunt",
      "game_patch": "0.5.4",
      "passive_tree_version": "0_5",
      "snapshot_date": "2026-06-27"
    },
    "diversity_policy": "Diversity cap preserves non-caster coverage after popularity filter."
  }
}
```

and:

```json
{
  "sourceType": "manual_fixture",
  "sourceRef": "fixture://infernalist-minion",
  "league": "Dawn of the Hunt",
  "gamePatch": "0.5.4",
  "passiveTreeVersion": "0_5",
  "class": "Witch",
  "ascendancy": "Infernalist",
  "mainSkill": "Skeletal Arsonist",
  "damageTypes": ["fire"],
  "deliveryTags": ["minion", "projectile"],
  "defenseTags": ["minion_screen", "energy_shield"],
  "mechanicTags": ["minion", "spirit"],
  "lifecycleStage": "endgame_final",
  "budgetBand": "expensive",
  "popularityRank": 4,
  "sampleWeight": 1.0,
  "pobModelability": "partial",
  "keypoints": ["Minion fixture with Spirit and endgame scaling caveats."],
  "numericRangesOrMetrics": {},
  "visibility": "quarantined",
  "split": "quarantine",
  "knowledgeScope": "global_seed",
  "evidenceType": "poe_ninja_hot",
  "freshnessStatus": "verified_current",
  "compatibilityStatus": "current",
  "diversityBucket": "infernalist-minion-spirit",
  "fixtureManifest": {
    "eligibility_basis": "manual_stand_in_for_hot_sample",
    "popularity_signal": {"kind": "rank", "rank": 4, "source": "fixture_manifest"},
    "currentness_basis": {
      "league": "Dawn of the Hunt",
      "game_patch": "0.5.4",
      "passive_tree_version": "0_5",
      "snapshot_date": "2026-06-27"
    },
    "diversity_policy": "Quarantined fixture proves visibility/split boundaries after popularity filter."
  }
}
```

The final JSON file must be valid and must wrap all four rows in:

```json
{
  "schemaVersion": 1,
  "fixtureSet": "phase3n1-seed",
  "cases": []
}
```

- [ ] **Step 4: Implement fixture validation/import**

In `server/knowledge/mature_learning.py`, add:

```python
REQUIRED_FIXTURE_MANIFEST_FIELDS = {
    "eligibility_basis",
    "popularity_signal",
    "currentness_basis",
    "diversity_policy",
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
    if popularity_signal.get("kind") == "rank" and not str(popularity_signal.get("rank") or "").strip():
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


def import_fixture_file(fixture_path: Path | None = None, *, db_path: Path | None = None) -> dict[str, Any]:
    path = fixture_path or paths.mature_learning_seed_fixtures_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"fixture_file_unreadable: {exc}"}
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        return {"ok": False, "error": "fixture_cases_must_be_list"}

    initialize_store(db_path)
    imported = 0
    rejected: list[dict[str, Any]] = []
    with connect(db_path) as con:
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
            _insert_sanitized_fixture(con, raw, sanitized, manifest_result["manifest"])
            imported += 1
    return {"ok": not rejected, "importedCases": imported, "rejected": rejected}


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
```

- [ ] **Step 5: Run GREEN**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

Run:

```powershell
git add data/mature_build_learning/seed_cases.json server/knowledge/mature_learning.py tests/test_mature_learning.py docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md
git commit -m "feat: add mature learning seed fixtures"
```

Expected: commit succeeds.

---

### Task 5: Boundary tests for visibility, scope, and non-copyable persistence

**Files:**

- Modify: `server/knowledge/mature_learning.py`
- Modify: `tests/test_mature_learning.py`
- Modify: `docs/PROJECT_SPEC.md`
- Modify: `docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md`

- [ ] **Step 1: Add failing boundary tests**

Append these tests to `tests/test_mature_learning.py`:

```python
def test_invalid_visibility_split_is_rejected_by_sanitizer():
    result = mature_learning.sanitize_mature_case(
        _raw_case(visibility="creator_visible", split="eval_holdout")
    )

    assert result["ok"] is False
    assert result["error"] == "invalid_visibility_split"


def test_user_feedback_local_cannot_enter_global_seed():
    result = mature_learning.sanitize_mature_case(
        _raw_case(evidenceType="user_feedback_local", knowledgeScope="global_seed")
    )

    assert result["ok"] is False
    assert result["error"] == "local_feedback_must_stay_local"


def test_persisted_fixture_rows_do_not_contain_raw_copyable_content(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    raw = _raw_case(
        sourceRef="fixture://safe-case",
        keypoints=["Broad coarse keypoint about an endgame-only scaling lane."],
    )
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "copy-safety", "cases": [raw]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"

    result = mature_learning.import_fixture_file(fixture_path, db_path=db_path)

    assert result["ok"] is True
    raw_db_bytes = db_path.read_bytes()
    assert b"pobCode" not in raw_db_bytes
    assert b"passiveTree" not in raw_db_bytes
    assert b"Ring 1" not in raw_db_bytes
    assert b"fullGemLinks" not in raw_db_bytes


def test_expiration_metadata_is_inert_in_phase_3n1(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    raw = _raw_case(freshnessStatus="stale", compatibilityStatus="stale")
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "stale-inert", "cases": [raw]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"

    result = mature_learning.import_fixture_file(fixture_path, db_path=db_path)

    assert result["ok"] is True
    con = sqlite3.connect(db_path)
    row = con.execute(
        "SELECT freshness_status, compatibility_status FROM mature_build_cases"
    ).fetchone()
    assert tuple(row) == ("stale", "stale")
```

`import json` should already be present from the Task 2 test scaffold.

- [ ] **Step 2: Run RED or confirm existing GREEN coverage**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py -q
```

Expected: If the earlier implementation already covers these boundaries, this may PASS
immediately. If any test fails, implement only the missing boundary behavior described by the
failure.

- [ ] **Step 3: Confirm no route synthesis or MCP surface changes**

Do not add route synthesis hooks, MCP tools, ranking, or retrieval helpers in this task. This slice
must not modify `server/main.py` or lifecycle route synthesis modules. Run:

```powershell
git diff --name-only
```

Expected touched production files before final review are limited to:

```text
server/paths.py
server/knowledge/mature_learning.py
```

If `server/main.py`, `server/knowledge/lifecycle.py`, or retrieval/ranking modules appear in the
diff, stop and remove that behavior from this slice.

- [ ] **Step 4: Update project spec completion map**

In `docs/PROJECT_SPEC.md`, add Phase 3N.1 to the completed or in-progress capability map after the
tests pass. State explicitly:

- schema and seed fixture import exist;
- sanitizer/copyability tests exist;
- expiration fields are inert;
- candidate extraction/retrieval/route influence remain pending.

- [ ] **Step 5: Run focused GREEN**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py tests/test_lifecycle_eval.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

Run:

```powershell
git add server/knowledge/mature_learning.py tests/test_mature_learning.py docs/PROJECT_SPEC.md docs/superpowers/plans/2026-06-27-mature-build-learning-3n1.md
git commit -m "test: enforce mature learning copy boundaries"
```

Expected: commit succeeds.

---

### Task 6: Verification and reviews

**Files:**

- Review all files touched by Tasks 1-5.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py tests/test_lifecycle.py tests/test_lifecycle_eval.py -q
```

Expected: PASS.

- [ ] **Step 2: Run quick verification**

Run:

```powershell
.\scripts\verify.ps1 quick
```

Expected: PASS.

- [ ] **Step 3: Request post-implementation code review**

Send a code-review subagent the changed file list and ask for:

- schema correctness and migration safety;
- sanitizer bypass risks;
- fixture import idempotence;
- evidence-boundary violations;
- accidental route synthesis or retrieval influence;
- Windows/path compatibility.

- [ ] **Step 4: Request narrow post-implementation spec review**

Because 3N.1 introduces a new evidence store and safety boundary, request a narrow spec review
covering:

- implementation matches Phase 3N.1 scope;
- no active expiration/downweighting behavior;
- no auto-promotion;
- no route generation influence;
- no raw mature build copying.

- [ ] **Step 5: Apply review fixes with targeted tests**

For each accepted review finding:

1. write or adjust a failing test that reproduces the issue;
2. run the targeted test and confirm it fails for the expected reason;
3. implement the smallest fix;
4. rerun the targeted test and confirm PASS;
5. rerun `.\scripts\verify.ps1 quick` if the fix touches behavior.

- [ ] **Step 6: Final status check**

Run:

```powershell
git status --short
git log --oneline -5
```

Expected: either a clean working tree after final commit, or only intentional plan checkbox updates.

---

## Self-review

- Spec coverage: This plan covers Phase 3N.1 schema/store path, fixture manifest, sanitizer,
  copyability/redaction tests, valid visibility/split/scope boundaries, local feedback isolation,
  inert expiration metadata, and no route behavior changes.
- Placeholder scan: The plan contains no open implementation placeholders. Future phases are named
  only in the explicit out-of-scope list.
- Type consistency: Public functions introduced here are `initialize_store`, `schema_version`,
  `connect`, `sanitize_mature_case`, `validate_fixture_manifest`, and `import_fixture_file`.
  Test names and implementation snippets use the same names.
