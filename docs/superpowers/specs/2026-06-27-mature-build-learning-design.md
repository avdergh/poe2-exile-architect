# Mature Build Learning Pipeline Design

Last updated: 2026-06-27

## Purpose

The mature build learning pipeline is the agent's current-season research memory layer. It learns
from popular, mature Path of Exile 2 build cases so the BD creator starts with useful design
intuition instead of waiting for user-provided examples.

This layer does not generate final builds by itself. It provides evidence-labeled design
candidates, lifecycle risks, and comparison material for `research_build_lifecycle` /
`suggest_build_lifecycle`. PoB2/engine verification and lifecycle transition gates remain the
authority for final recommendations.

## Product positioning

The pipeline has three responsibilities:

1. Discover and sanitize mature build samples from controlled high-signal sources.
2. Distill reusable technique candidates with provenance, tags, lifecycle applicability, and
   freshness metadata.
3. Support a later teacher-student evaluation loop where an agent-created route can be compared
   against mature samples without copying them.

It explicitly does not:

- copy full mature builds into recommendations;
- treat popularity as proof of power or beginner viability;
- write user feedback into global project seed knowledge;
- promote a single source into durable advice;
- bypass freshness, PoB/engine checks, or transition readiness.

## Data architecture

Use a SQLite-first, hybrid-ready architecture.

SQLite is the source of truth because PoE2 build knowledge needs exact filtering by patch, passive
tree, league, lifecycle stage, class, ascendancy, skill, tag, source, evidence type, freshness,
visibility, and promotion status. A vector-only store would be unsafe because semantically similar
but stale or stage-incompatible techniques can be worse than no retrieval.

The v1 store should include:

- structured columns for exact filters;
- JSON payload columns for sanitized keypoints and compact summaries;
- edge tables for graph-like relationships;
- text summaries suitable for FTS/BM25 or later embeddings.

Do not introduce an external graph database in Phase 3N. Represent relationships with a
`technique_edges` table first. Do not introduce a vector database in Phase 3N. A future vector index
may be added as a derived recall cache, but every vector result must round-trip through SQLite for
version, stage, visibility, evidence, and stale-status filtering.

Recommended retrieval order:

1. exact SQLite filters;
2. FTS/BM25 or keyword search over technique summaries;
3. optional future vector recall;
4. SQLite re-filtering;
5. engine/evidence validation before recommendation.

## Core entities

### `source_snapshots`

Represents a controlled fetch or curated import from a mature build source.

Required fields:

- `id`
- `source_type`: `poe_ninja`, `forum`, `pobb_in`, `pob_archive`, `manual_fixture`, or future source
- `source_url` or opaque source reference
- `fetched_at`
- `league`
- `game_patch`
- `passive_tree_version`
- `pob_version_or_commit`
- `popularity_filter`
- `diversity_bucket`
- `raw_hash`
- `sanitizer_version`
- `freshness_status`
- `attribution`
- `usage_policy`

The store must not persist copied forum pages, full PoB codes, complete passive trees, full gear
lists, or complete gem/support setups. It may store minimal attributed summaries and hashes.

### `mature_build_cases`

Represents a sanitized mature build case.

Required fields:

- `case_id`
- `source_snapshot_id`
- `external_id_hash`
- `visibility`: `creator_visible`, `evaluator_only`, or `quarantined`
- `split`: `train_context`, `eval_holdout`, or `quarantine`
- `class`
- `ascendancy`
- `main_skill`
- `damage_types`
- `delivery_tags`
- `defense_tags`
- `mechanic_tags`
- `lifecycle_stage`: usually `endgame_budget`, `endgame_final`, or `unknown_lifecycle`
- `budget_band`
- `popularity_rank`
- `sample_weight`
- `pob_modelability`: `full`, `partial`, `not_modelable`, or `unknown`
- `sanitized_keypoints`
- `numeric_ranges_or_metrics`
- `redacted_fields_present`
- `created_at`
- `last_seen_at`

`visibility` and `split` are required from Phase 3N even before the teacher-student loop exists.
Without them, Phase 3O could leak evaluator-only or holdout knowledge into the creator context.

### `technique_candidates`

Represents a reusable design idea distilled from mature evidence or later evaluation gaps.

Required fields:

- `candidate_id`
- `statement`
- `summary_for_llm`
- `category_tags`
- `lifecycle_stage`
- `mechanism_role`
- `evidence_type`
- `source_count`
- `support_count`
- `contradiction_count`
- `confidence`
- `promotion_status`: `candidate`, `promoted`, `rejected`, `stale`, or `quarantined`
- `game_patch`
- `passive_tree_version`
- `league`
- `freshness_status`
- `compatibility_status`
- `budget_band`
- `pob_modelability`
- `first_seen_at`
- `last_seen_at`

Candidates are not durable rules. They are research material until promoted by a later, explicit
promotion workflow.

### `technique_edges`

Represents graph-like relationships without requiring a graph database.

Supported edge types:

- `requires`
- `enables`
- `conflicts_with`
- `upgrades_to`
- `replaces`
- `transition_from`
- `transition_to`
- `synergizes_with`

Required fields:

- `from_candidate_id`
- `to_candidate_id`
- `edge_type`
- `evidence_ids`
- `confidence`
- `league`
- `game_patch`
- `passive_tree_version`

### Future `teacher_student_runs`

Phase 3N should leave room for a later table that stores Phase 3O evaluation runs:

- target mature case or cohort id;
- sanitized target brief id;
- creator-visible fields used;
- withheld fields hash;
- generated route id;
- evaluator result id;
- gap candidate ids;
- contamination or leakage flags.

## Tag taxonomy

The mature learning store should support multi-dimensional tags. Tags are filterable metadata, not
free-form prose.

Category tags:

- `passive_tree`
- `gear`
- `unique_item`
- `skill_gem`
- `support_gem`
- `spirit`
- `mana_sustain`
- `ascendancy`
- `defense_layer`
- `damage_scaling`
- `ailment`
- `crit`
- `minion`
- `projectile`
- `dot`
- `trigger`
- `jewel`
- `atlas_or_mapping`
- `bossing`
- `crafting_or_trade`
- `transition_gate`

Lifecycle stage tags:

- `campaign_early`
- `campaign_mid`
- `campaign_late`
- `maps_entry`
- `endgame_budget`
- `endgame_final`
- `unknown_lifecycle`

Mechanism role tags:

- `enabler`
- `scaler`
- `threshold`
- `converter`
- `sustain_solution`
- `defensive_core`
- `budget_substitute`
- `failure_pattern`
- `quality_of_life`
- `risk`

Evidence tags:

- `poe_ninja_hot`
- `external_forum_guide`
- `pobb_in_import`
- `pob_archive`
- `reference_cohort`
- `engine_computed`
- `user_feedback_local`
- `generated_eval_gap`
- `multi_source_confirmed`

Applicability tags:

- `starter_viable`
- `starter_risky`
- `transition_only`
- `endgame_only`
- `budget_friendly`
- `expensive`
- `requires_unique`
- `requires_threshold`
- `pob_model_uncertain`
- `patch_sensitive`

## Phase 3N: mature build seed corpus and candidate store

Phase 3N builds the data backbone. It should not yet change route synthesis behavior.

Scope:

- create the SQLite mature-learning store;
- define schemas, indexes, and JSON payload boundaries;
- ingest a small fixture corpus of sanitized mature build cases;
- enforce popularity metadata and diversity fields;
- extract deterministic `technique_candidates`;
- support read-only retrieval and exact filtering;
- expose provenance and safety metadata;
- prove raw build content is not exposed;
- keep user feedback separate from the global seed corpus.

Out of scope:

- automatic live periodic fetching;
- automatic promotion to durable technique cards;
- direct route generation influence;
- teacher-student execution;
- vector database integration;
- external graph database integration.

The first implementation slice should use tiny curated fixtures rather than a full live crawler.
This lets the schema, sanitizer, retrieval, and tests stabilize before network variability is added.

## Phase 3O: teacher-student evaluation loop

Phase 3O turns mature build cases into practice tasks for the BD creator.

Planned flow:

1. Select a mature case or cohort.
2. Create a sanitized target brief from creator-visible fields only.
3. Ask a creator subagent to produce a lifecycle route using current memory and research workflow.
4. Let an evaluator compare the generated route with richer sanitized evaluator-only evidence and
   engine-calibrated ranges.
5. Distill gaps into low-trust `generated_eval_gap` technique candidates.

Safeguards:

- creator never sees raw PoB code, full passive tree, exact item set, exact gem/support setup, or
  copied guide text;
- evaluator access is separated from creator context;
- holdout cases exclude candidates derived only from that exact case from creator retrieval;
- generated gaps never promote themselves;
- durable promotion requires mature multi-source evidence, engine delta, or explicit human review;
- all outputs must preserve provenance, patch/tree/league, source count, and modelability caveats.

## Phase 3P: candidate promotion and revalidation

Phase 3P promotes trustworthy candidates and handles compatibility drift.

Promotion may eventually depend on:

- multi-source mature confirmation;
- cohort frequency;
- engine-computed delta;
- explicit human review;
- repeated local feedback, only for local memory and not global seed knowledge.

Knowledge expiration policy is intentionally not fixed in this design. The schema stores the fields
needed for expiration and revalidation, but the actual stale/downweight thresholds must be confirmed
with the user before implementation. At minimum, future policy will need to answer:

- whether any patch change makes a technique stale or only passive-tree/mechanic-affecting patches;
- whether league changes alone reduce confidence;
- how long an unseen technique remains current;
- how to handle techniques with unknown patch/tree metadata;
- whether reappearance in new mature samples refreshes a candidate automatically.

Implementation must pause for user confirmation before adding active expiration or downweighting
behavior beyond metadata capture.

## User feedback boundary

External mature build samples may become release-managed seed knowledge after sanitization and
review. User feedback does not become global seed knowledge.

User feedback remains local memory:

- exact-build episodic feedback stays local;
- repeated local failure patterns can affect local warnings;
- obvious Agent design bugs may become local repair lessons;
- no user-specific feedback is written into the global mature build seed corpus.

## Evaluation plan

Phase 3N should include deterministic tests for:

- schema creation and migration safety;
- raw PoB/tree/gear/code fields are redacted or rejected;
- exact filters by patch, tree, league, stage, category, role, budget, and evidence type;
- cross-class/ascendancy diversity metadata is preserved;
- `creator_visible` / `evaluator_only` and `train_context` / `eval_holdout` are preserved;
- user feedback cannot enter the seed corpus;
- no route synthesis behavior changes in Phase 3N;
- candidate retrieval returns provenance and caveats.

Later retrieval quality evaluation should add recall tests:

- define representative research questions;
- mark expected technique candidates;
- measure recall at 5 and 10;
- add vector retrieval only if structured + text retrieval misses important candidates;
- add graph database only if edge-table traversal becomes insufficient.

## Open confirmation gates

The following decisions require user confirmation before implementation:

1. Active knowledge expiration and downweighting policy.
2. Any automated live periodic fetcher.
3. Any route-synthesis behavior that directly uses mature candidates.
4. Any auto-promotion from candidate to durable technique card.
5. Any migration from SQLite/FTS/edge tables to vector or external graph infrastructure.
