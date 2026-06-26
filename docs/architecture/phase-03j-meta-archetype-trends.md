# Phase 3J Meta Archetype Trend Adapter

## Purpose

The lifecycle agent needs to learn from mature build cohorts, but it must not hallucinate
build-level meta evidence from sources that only expose ascendancy popularity. Phase 3J adds a
small, safe adapter for aggregate archetype/sample trends so future providers can plug in real
skill/ascendancy trend rows without contaminating lifecycle research with unsupported claims.

## Contract

`shape_archetype_trends(data, league?, limit?)` formats aggregate build-archetype rows when the
payload explicitly contains them. The safe public shape is:

- `ok`: whether aggregate archetype rows are available.
- `source`: currently `poe.ninja` for the live adapter.
- `kind`: `archetype_trends`.
- `league`: selected league.
- `archetypes`: sanitized rows with only `skill`, `ascendancy`, `sampleCount`, `share`, `trend`,
  and `evidenceTags`.
- `unavailableReason`: present when the source payload lacks aggregate build-level samples.
- `note`: reminds callers that trends are discovery context, not proof of power.

The adapter accepts controlled aggregate fields such as `archetypes`, `skills`, or `skillStats`.
It deliberately ignores raw character/build dumps, gear lists, passive trees, or anything that
would encourage copying a build.

## Boundaries

- The existing poe.ninja build-index endpoint currently supports ascendancy popularity. If the
  payload lacks aggregate skill/archetype rows, the adapter returns `ok: false` with a clear
  unavailable reason.
- This phase does not add fragile webpage scraping or protobuf reverse engineering.
- A trend row is live-meta evidence only. It can help select samples to investigate, but engine
  checks and lifecycle gates still decide whether a route is viable.
- The lifecycle cohort layer may consume sanitized trend rows for hints, but must keep them
  separate from reference-build calibration and PoB-computed evidence.

## Future provider seam

When a stable build-level source is available, it should feed the same sanitized row shape. That
provider can be poe.ninja protobuf data, a curated pobb.in/forum sample collector, or a validated
offline snapshot. The lifecycle code should not need to know which provider produced the aggregate
rows.
