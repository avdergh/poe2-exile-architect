# Phase 3C Transition Readiness

## Purpose

Lifecycle routes need a practical decision point: "Can the player safely transition now?" Phase 3C
adds a readiness evaluator that checks a transition gate against the player's current state and
turns missing requirements plus play feedback into actionable next steps.

## Inputs

The evaluator accepts:

- `build_id`: optional lifecycle build id. When present, stored gates for that build are preferred.
- `from_stage` / `to_stage`: the transition being evaluated.
- `state`: current player facts:
  - `level`
  - `items`
  - `gems`
  - `ascendancyPoints`
  - `checks`, such as `resists_capped`, `sustain_ok`, `basic_defense_online`
  - `feedback`, such as "缺蓝", "暴毙", "伤害不足", or "清图慢"

## Outputs

The evaluator returns:

- `ready`: whether the transition gate is satisfied.
- `recommendation`: `transition_allowed` or `hold_current_stage`.
- `missing`: unmet requirements from the gate.
- `feedbackPattern`: normalized feedback category when feedback is supplied.
- `recommendedActions`: stage-aware fixes before switching.
- `caveats`: gate caveats, including PoB modelling warnings.

## Boundaries

- This is not a stage optimizer.
- This does not infer missing player state.
- If PoB cannot model the mechanic, the result must keep that caveat visible.
- A failed readiness check should keep the player on the current stage and suggest repairs, not
  silently recommend the final build.
