# Phase 3G Source-Derived Transition Gates

## Purpose

Phase 3F extracts guide/source text such as "switch at level 75 when X is equipped." Phase 3G turns
that evidence into draft `TransitionGate` objects so the lifecycle agent can reason about when a
guide expects the player to change from starter to endgame form.

## Contract

`analyze_build_lifecycle(source)` now returns:

- `sourceTransitionGates`: gates synthesized from explicit source transition hints.
- `transitionGates`: source-derived gates followed by default lifecycle gates.

A source-derived gate includes:

- `source`: `source-evidence`.
- `fromStage` and `toStage` inferred from the mentioned level.
- `requirements.level` when a level is mentioned.
- `requirements.items` when required unique language and corpus-confirmed unique candidates exist.
- conservative checks for map/endgame transitions.
- caveats that the gate came from external text and must be verified before switching.

## Stage Inference

The first implementation uses coarse lifecycle bands:

- level ≤ 25: `campaign_early` → `campaign_mid`
- level ≤ 45: `campaign_mid` → `campaign_late`
- level ≤ 65: `campaign_late` → `maps_entry`
- level ≤ 85: `maps_entry` → `endgame_budget`
- higher or unknown: `endgame_budget` → `endgame_final`

## Boundaries

- Source gates are hypotheses, not proof.
- They do not replace engine verification or readiness checks.
- They should preserve exact snippets so the assistant can explain where the gate came from.
- If no explicit transition hint exists, no source gate is produced.
