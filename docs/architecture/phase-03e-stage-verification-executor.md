# Phase 3E Stage Verification Executor

## Purpose

Phase 3D tells the agent what a lifecycle stage must verify. Phase 3E turns that checklist into a
first executable gate for the active PoB build.

The executor is intentionally conservative: it reads available engine stats/defenses, evaluates
stage target checks, and reports pass/fail/caveats. It does not mutate the build, optimize gear, or
claim a route is solved.

## Contract

`verify_lifecycle_stage(stage, state?, build_id?)` returns:

- `status`: `passed`, `failed`, or `unknown`.
- `pass`: boolean only when all required checks are known and passing.
- `plan`: the Phase 3D verification budget used for the stage.
- `observations`: raw engine-derived metric values normalized for lifecycle checks.
- `checks`: named target checks such as `resists_capped`, `basic_defense_online`, and `sustain_ok`.
- `failedChecks`: checks that are known and failing.
- `unknownChecks`: checks that require manual evidence or mechanics not visible in the current
  engine snapshot.
- `caveats`: stage caveats plus engine/modeling warnings.
- `evidenceTags`: includes `engine-computed` for values read from PoB and `stage-verification`
  for derived lifecycle checks.

## Boundaries

- The executor consumes the active build exactly as loaded. It does not call `set_level`, equip
  starter gear, or allocate passives automatically.
- Numeric thresholds are deliberately coarse for v1. They are stage gates, not final balance
  targets.
- If a check depends on game feel, unavailable items, price, or an unmodelled mechanism, the result
  must stay `unknown` instead of fabricating confidence.
- Engine warnings and import caveats must remain visible in the response.

## Initial Checks

The first implementation evaluates checks that can be inferred from existing engine data:

- `resists_near_cap`: elemental resistances are at least 60%.
- `resists_capped`: elemental resistances are at least 75%.
- `basic_defense_online`: total EHP or life/ES pool clears the stage's coarse floor.
- `sustain_ok`: mana is available and mana cost does not exceed the stage's conservative ratio.
- `pob_model_supported`: no engine warning/limitation is present.

Other target checks are reported as unknown until later phases add direct evidence extractors.
