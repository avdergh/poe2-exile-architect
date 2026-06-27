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
- copied long guide prose is rejected;
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
