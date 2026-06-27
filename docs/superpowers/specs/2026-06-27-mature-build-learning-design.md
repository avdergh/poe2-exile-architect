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

### `source_groups`

Represents duplicate or near-duplicate source families. A forum guide, pobb.in import, poe.ninja
entry, and archived page can describe the same underlying build. Grouping them prevents holdout
leakage and keeps source-count promotion honest.

Required fields:

- `source_group_id`
- `dedupe_hash`
- `canonical_source_type`
- `canonical_source_ref`
- `league`
- `game_patch`
- `passive_tree_version`
- `created_at`
- `last_seen_at`

### `source_snapshots`

Represents metadata for a controlled fetch or curated import from a mature build source. A snapshot
is not a raw page/build archive.

Required fields:

- `id`
- `source_group_id`
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

### Sampling and source eligibility policy

Phase 3N must not ingest random builds. Every sample must explain why it represents a popular,
mature, current-season case.

Eligibility rules:

- Current-season/current-patch metadata is required for a case to be considered `current`. Cases with
  missing patch/tree metadata may be stored only as `freshness_status: unknown` and must not be used
  to claim current-meta knowledge.
- Source priority is:
  1. poe.ninja current-league hot/top builds or source snapshots;
  2. high-signal build guides with visible popularity signals such as replies, views, update date, or
     community curation;
  3. pobb.in/PoB Archives imports only when tied to a high-signal public source or current hot sample;
  4. manual fixtures only when they include a manifest explaining the original popularity/source
     rationale.
- Popularity filtering must happen before diversity balancing. Diversity caps then prevent one class
  or ascendancy from filling the entire seed set.
- Sampling must be deterministic within eligible strata. The same source snapshot and policy should
  choose the same cases.
- Random sampling is not allowed unless explicitly used inside a deterministic fixture generator with
  a fixed seed and a documented reason.
- Fixture cases must include a `fixture_manifest` or equivalent metadata proving they are stand-ins
  for popular mature cases, not arbitrary examples.

Suggested first-slice policy:

- ingest a tiny manually curated fixture set;
- include at least four classes or ascendancies;
- cap each ascendancy/archetype at a small fixed count;
- include popularity fields even if sourced from fixture metadata;
- reject fixture rows with no popularity or provenance rationale.

### `mature_build_cases`

Represents a sanitized mature build case.

Required fields:

- `case_id`
- `source_snapshot_id`
- `external_id_hash`
- `visibility`: `creator_visible`, `evaluator_only`, or `quarantined`
- `split`: `train_context`, `eval_holdout`, or `quarantine`
- `knowledge_scope`: `global_seed`, `local_user`, or `eval_ephemeral`
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
- `source_group_id`
- `created_at`
- `last_seen_at`

`visibility` and `split` are required from Phase 3N even before the teacher-student loop exists.
Without them, Phase 3O could leak evaluator-only or holdout knowledge into the creator context.

Allowed visibility/split combinations:

| visibility | split | retrieval behavior |
| --- | --- | --- |
| `creator_visible` | `train_context` | Can be used as creator research context after filtering. |
| `evaluator_only` | `eval_holdout` | Can be used by evaluators, never creator retrieval. |
| `quarantined` | `quarantine` | Not available to creator or evaluator until manually cleared. |

All other combinations are invalid in Phase 3N.

### `technique_candidates`

Represents a reusable design idea distilled from mature evidence or later evaluation gaps.

Required fields:

- `candidate_id`
- `knowledge_scope`: `global_seed`, `local_user`, or `eval_ephemeral`
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
- `required_prerequisites`
- `starter_risk_reason`
- `transition_gate_summary`
- `unsafe_before_stage`
- `first_seen_at`
- `last_seen_at`

Candidates are not durable rules. They are research material until promoted by a later, explicit
promotion workflow.

### `candidate_evidence`

Links candidates to the exact evidence that supports, contradicts, or merely mentions them. Aggregate
counts on `technique_candidates` are derived from this table, not treated as primary proof.

Required fields:

- `candidate_id`
- `case_id`
- `source_snapshot_id`
- `source_group_id`
- `relation`: `supports`, `contradicts`, or `mentions`
- `visibility`
- `split`
- `knowledge_scope`
- `extraction_method`
- `extractor_version`
- `confidence`
- `creator_visible`
- `created_at`
- `last_seen_at`

This table is required before promotion, holdout exclusion, source-count validation, or revalidation
logic can be implemented.

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
- `candidate_evidence_ids`
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

Controlled freshness values:

- `current_metadata_only`
- `verified_current`
- `stale`
- `needs_revalidation`
- `unknown`

Controlled compatibility values:

- `current`
- `stale`
- `unknown`
- `quarantined`

Phase 3N may store these values as metadata, but it must not use them to actively downweight,
promote, alter retrieval ranking, or affect route synthesis until the user confirms the expiration
policy.

## Sanitization and copyability policy

Sanitization is allowlist-based. Anything not explicitly allowed is rejected or redacted.

Allowed mature-case content:

- class, ascendancy, main skill, broad damage type, broad delivery tags;
- broad defense identity, e.g. ES stacker, MoM, armour/evasion, CI, block, recovery layer;
- broad scaling levers, e.g. +levels, penetration, crit scaling, ailment magnitude, minion levels;
- lifecycle classification and stage applicability;
- prerequisite categories, e.g. requires unique, requires threshold, requires late passive cluster;
- coarse budget band and popularity/rank metadata;
- engine-computed aggregate ranges only when produced by the engine or trusted benchmark output;
- short non-verbatim summaries and attribution.

Forbidden persisted content:

- raw PoB code, pastebin code, pobb.in raw code, or full XML;
- full passive tree, ordered passive node list, or exact path;
- full gear list, exact item set, exact affix list, or item-by-slot reproduction;
- full skill/support group, exact link order, or complete gem setup;
- copied guide text or forum posts;
- enough ordered keypoints to reconstruct a mature build.

Granularity limits:

- uniques may be recorded as prerequisite categories or named only when they are the public,
  build-defining mechanism under study; full item sets remain forbidden;
- passive tree information should stay at anchor/cluster/category level, not node-path level;
- gems/supports should stay at role/category level unless a single active skill is the archetype
  identifier;
- numeric values must be aggregate ranges or engine observations, not copied character sheet dumps.

Tests must include copyability/reconstruction guards. If a sanitized record could plausibly recreate
the original build without external research, it is too detailed.

## Phase 3N: mature build seed corpus and candidate store

Phase 3N builds the data backbone. It should not yet change route synthesis behavior.

Phase 3N is split into smaller implementation slices:

### Phase 3N.1: schema, fixtures, sanitizer, and redaction proof

- create the SQLite mature-learning store;
- define schema versioning and migrations;
- define store path ownership, preferring user-data updates over bundled seed fallback like other
  project data;
- ingest a tiny fixture corpus with fixture manifests;
- enforce sampling/provenance metadata;
- enforce sanitizer allowlist and copyability tests;
- preserve `visibility`, `split`, `knowledge_scope`, and `source_group_id`;
- prove user feedback cannot enter the global seed corpus.

### Phase 3N.2: deterministic candidate extraction and evidence bridge

- extract deterministic `technique_candidates` from sanitized cases;
- populate `candidate_evidence`;
- derive support/contradiction/source counts from evidence rows;
- capture prerequisite and lifecycle-risk fields.

### Phase 3N.3: retrieval, FTS, indexes, and provenance output

- support read-only retrieval and exact filtering;
- add FTS/BM25 over summaries if needed;
- return provenance, caveats, and visibility-safe summaries;
- prove no route synthesis behavior changes.

### Phase 3N.4: edge table population

- populate `technique_edges` only after candidate/evidence modeling is stable;
- keep external graph DB out of scope.

Original Phase 3N scope, spread across these slices:

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
2. Create a minimal sanitized benchmark brief for the creator. This brief is separate from mature
   case-store retrieval and contains only the task framing needed for evaluation.
3. Ask a creator subagent to produce a lifecycle route using current memory and research workflow.
4. Let an evaluator compare the generated route with richer sanitized evaluator-only evidence and
   engine-calibrated ranges.
5. Distill gaps into low-trust `generated_eval_gap` technique candidates.

Safeguards:

- creator never sees raw PoB code, full passive tree, exact item set, exact gem/support setup, or
  copied guide text;
- a Phase 3O target brief derived from a held-out case is a separate, minimal evaluation input; it
  must not grant creator retrieval access to the held-out case, evaluator-only evidence, or
  candidates derived from that source group;
- evaluator access is separated from creator context;
- creator retrieval excludes `evaluator_only`, `eval_holdout`, `quarantined`, and artifacts derived
  from the current target, cohort, or `source_group_id`;
- split assignment is immutable for an evaluation run;
- source duplicates and mirrors must share a `source_group_id` for holdout exclusion;
- generated eval gaps remain `eval_ephemeral` or `quarantined` and are not creator-visible for the
  same benchmark family unless independently promoted from non-holdout evidence;
- generated gaps never promote themselves;
- durable promotion requires mature multi-source evidence, engine delta, or explicit human review;
- all outputs must preserve provenance, patch/tree/league, source count, and modelability caveats.

Phase 3O test matrix:

- creator context cannot retrieve evaluator-only cases;
- creator context cannot retrieve eval-holdout cases;
- creator context cannot retrieve candidates derived from the same source group as the target;
- generated gap candidates are not creator-visible by default;
- evaluator reports contamination/leakage flags if a boundary is violated.

## Phase 3P: candidate promotion and revalidation

Phase 3P promotes trustworthy candidates and handles compatibility drift.

Promotion may eventually depend on:

- multi-source mature confirmation;
- cohort frequency;
- engine-computed delta;
- explicit human review;
- repeated local feedback, only for local memory and not global seed knowledge.

Human review alone is not a free pass. It must include a review rationale, patch/tree scope,
provenance, and copy-safety confirmation.

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

In Phase 3N, expiration-related fields are inert metadata. They must not alter retrieval rank,
candidate confidence, promotion status, or route behavior until the user approves an active
expiration policy.

## User feedback boundary

External mature build samples may become release-managed seed knowledge after sanitization and
review. User feedback does not become global seed knowledge.

User feedback remains local memory:

- exact-build episodic feedback stays local;
- repeated local failure patterns can affect local warnings;
- obvious Agent design bugs may become local repair lessons;
- no user-specific feedback is written into the global mature build seed corpus.

Schema-level rule: `user_feedback_local` evidence must use `knowledge_scope: local_user` and must not
be inserted into `global_seed` mature cases or global seed candidates.

## Evaluation plan

Phase 3N should include deterministic tests for:

- schema creation and migration safety;
- popular/latest source eligibility and fixture manifest validation;
- raw PoB/tree/gear/code fields are redacted or rejected;
- sanitized records cannot reconstruct full builds;
- exact filters by patch, tree, league, stage, category, role, budget, and evidence type;
- cross-class/ascendancy diversity metadata is preserved;
- `creator_visible` / `evaluator_only` and `train_context` / `eval_holdout` are preserved;
- invalid `visibility` / `split` combinations are rejected;
- creator retrieval cannot see evaluator/holdout material;
- generated gap candidates are not creator-visible by default;
- user feedback cannot enter the seed corpus;
- local feedback cannot be promoted into global seed;
- expiration metadata is inert until confirmed;
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
