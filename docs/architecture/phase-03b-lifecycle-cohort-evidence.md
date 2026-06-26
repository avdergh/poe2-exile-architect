# Phase 3B Lifecycle Cohort Evidence

## Purpose

Phase 3B adds a cohort-evidence layer between raw sources and lifecycle synthesis. It answers:
"For this goal, what do mature reference archetypes and live ascendancy context commonly agree on?"

The immediate goal is not full poe.ninja character scraping or passive-tree optimization. The goal is
to give the lifecycle agent a structured research substrate: recurring levers, recurring delivery
traits, recurring defenses, and live-meta context that can guide later PoB stage verification.

## Contract

The analyzer returns:

- `referenceMatches`: slim, non-copyable reference build slices.
- `commonLevers`: recurring scaling levers from matching references.
- `commonDamageTypes`, `commonDelivery`, `commonDefenses`: recurring archetype traits.
- `ascendancyContext`: matched reference ascendancies annotated with live poe.ninja popularity when
  available.
- `warnings`: caveats such as missing samples or live-meta absence.

## Boundaries

- This is not a build copier.
- This is not a passive tree optimizer.
- poe.ninja ascendancy popularity is context, not a recommendation.
- Reference builds are calibration samples, not templates.
- PoB remains the source of computed DPS/EHP/resistance truth.
