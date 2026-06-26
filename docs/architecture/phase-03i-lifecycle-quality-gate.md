# Phase 3I Lifecycle Quality Gate

## Purpose

The lifecycle agent should not present a route as usable when it is missing starter stages,
transition gates, evidence labels, or stage verification plans. Phase 3I adds a structural quality
gate that can audit a lifecycle route before it is shown to a player or used in evaluations.

## Contract

`audit_lifecycle_route(route)` returns:

- `pass`: whether the route satisfies the minimum lifecycle contract.
- `score`: 0-100 structural completeness score.
- `missing`: blocking structural gaps.
- `warnings`: non-blocking concerns.
- `checks`: individual check results.
- `evidenceTags`: includes `lifecycle-quality-gate`.

Minimum checks:

- At least one campaign stage exists.
- `maps_entry` exists.
- At least one endgame stage exists.
- Transition gates exist.
- Every stage has evidence tags.
- Every stage has a verification plan.
- Starter/endgame-transition classifications include a transition gate into endgame.

## Boundaries

- This quality gate audits structure, not build power.
- It does not replace PoB verification or meta/reference comparison.
- A passing gate means "the route is complete enough to research/verify," not "the build is strong."
