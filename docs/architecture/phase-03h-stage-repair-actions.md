# Phase 3H Stage Repair Actions

## Purpose

Stage verification should be usable by beginners, not just machine-readable. Phase 3H adds
stage-aware repair actions to `verify_lifecycle_stage` / `verify_stage_metrics` so a failed
lifecycle stage tells the agent what to fix before recommending a transition.

## Contract

Verification results include `recommendedActions`:

- Failed `resists_capped` / `resists_near_cap`: cap or repair elemental resistances before
  progressing.
- Failed `basic_defense_online`: raise life/ES/EHP before trading defense for damage.
- Failed or unknown `sustain_ok`: fix mana/Spirit/life sustain before adding supports or switching.
- Failed `pob_model_supported`: do not present the computed number as the mechanism's true value.
- Unknown build-defining/endgame checks: gather item, threshold, or guide evidence before claiming
  readiness.

## Boundaries

- Actions are conservative and stage-aware, not optimizer output.
- They do not mutate the active build.
- Specific stat gains still require normal engine tools such as `optimize_item`, `plan_gear`,
  `rank_upgrades`, or `optimize_supports`.
