# Phase 3D Stage Verification Budgets

## Purpose

Lifecycle routes should not be trusted until each stage has a concrete verification budget. Phase 3D
defines what a stage-level PoB verification pass must know before it can claim a build is good for
that stage.

This phase creates the verification skeleton only. It does not yet execute every PoB step
automatically. The contract tells the agent which level, passive budget, gear assumption, metrics,
and checks must be verified for each lifecycle stage.

## Stage Budget Contract

Each stage verification plan contains:

- `levelTarget`: representative level for the stage.
- `passivePointBudget`: approximate passive budget to use for PoB setup.
- `gearAssumption`: what level of gear is allowed for the stage.
- `engineTools`: MCP tools expected during verification.
- `metricGroups`: offense, defense, sustain, and caveat metrics to inspect.
- `targetChecks`: lifecycle checks such as `resists_capped`, `basic_defense_online`, and
  `pob_model_supported`.
- `failureModes`: common reasons a stage should fail verification.

## Boundaries

- A verification plan is not a computed result.
- Actual DPS/EHP/resistance values still come from PoB engine tools.
- Expensive endgame checks should be gated behind stage readiness and budget assumptions.
- If a mechanic is not modelled by PoB, the verification plan must preserve that caveat.
