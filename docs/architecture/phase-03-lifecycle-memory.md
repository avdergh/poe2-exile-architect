# Phase 3A Lifecycle Memory

## Store

Lifecycle memory is stored at `paths.lifecycle_memory_path()` as JSON in the writable user-data
directory. This keeps Phase 3A simple and local while the research workflow stabilizes. The store
contains:

- `lifecycle_builds`: generated lifecycle route summaries.
- `transition_gates`: stage-switch requirements per lifecycle build.
- `feedback_reflections`: user practice feedback, stored as episodic memory.
- `failure_patterns`: grouped feedback patterns such as defense, resistance, sustain, damage, and
  clear-speed gaps.
- `technique_cards`: durable, patch-scoped lessons promoted from evidence.

## Promotion Rule

A single user report does not become a durable rule. `record_build_feedback` always writes episodic
memory. `promote_technique_memory` requires explicit evidence IDs and records the current game patch
and passive tree when available, so stale techniques can be down-weighted in later phases.

## Future Upgrade Path

If the lifecycle corpus grows beyond a local JSON file, migrate this schema to SQLite/FTS alongside
the existing corpus. Keep the same public MCP contracts so agents and tests do not depend on the
storage backend.
