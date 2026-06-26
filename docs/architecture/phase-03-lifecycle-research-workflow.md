# Phase 3A Lifecycle Research Workflow

## Purpose

Phase 3A makes the assistant reason about a build's lifecycle instead of only its final PoB. A
strong endgame build may be impossible to level directly if it needs a unique, lineage gem,
threshold, late passive cluster, or unmodelled trigger. The first implementation therefore adds a
research scaffold: starter stages, transition gates, endgame stages, evidence labels, and feedback
memory.

## Workflow

1. `suggest_build_lifecycle` runs the freshness gate before making a current-season claim.
2. The goal is decomposed into research questions inspired by deep-research agents: stage viability,
   evidence collection, extraction, cohort analysis, synthesis, PoB verification, and memory
   promotion.
3. The route is classified as `starter_to_endgame`, `starter_then_transition`, `endgame_only`,
   `starter_only`, or `unknown_lifecycle`.
4. Each stage carries a plan and evidence tags. The stage plan intentionally does not invent DPS or
   EHP; PoB verification must happen with that stage's level, gear, and passive budget.
5. Transition gates block premature swaps. A gate can require level, items, gems, ascendancy points,
   and boolean readiness checks such as capped resists or sustain.

## Boundaries

- PoB remains the source of truth for computed numbers.
- poe.ninja is context and sample discovery, not proof of optimality.
- Reference builds calibrate archetype levers; they are not copied.
- Feedback starts as episodic memory and only becomes durable technique memory through explicit
  promotion.
