# Phase 3L Lifecycle Evaluation Harness

Phase 3L adds a deterministic evaluation harness for lifecycle route outputs. It answers: "Is this
route complete, evidence-labeled, and aligned with mature-build calibration patterns enough to use
in development/regression evaluation?"

This is not a generator, optimizer, PoB verifier, or live-meta fetcher. It never creates a build,
never copies a reference build, never runs engine compute, never pulls network data, and never writes
memory.

## Public contract

`evaluate_lifecycle_route(route, reference_profile=None, goal=None)` returns a
`LifecycleRouteEvaluation` dictionary:

- `ok`: evaluator ran successfully.
- `kind`: always `lifecycle_route_evaluation`.
- `pass`: true only when there are no blocking issues and no unknown evidence gaps.
- `score`: 0-100 deterministic score.
- `grade`: `pass`, `needs_review`, or `fail`.
- `issues`: stable blocking codes.
- `warnings`: stable non-blocking codes.
- `unknowns`: stable codes for claims the evaluator cannot judge.
- `checks`: per-check status rows.
- `routeSummary`: build id, goal, classification, and stage ids.
- `qualityGate`: fresh structural audit from `lifecycle_quality.audit_lifecycle_route`.
- `referenceComparison`: non-copyable archetype alignment against `reference_profile` or the route's
  own `cohortAnalysis`.
- `evidenceReview`: stage evidence, verification plans, numeric-claim safety.
- `memoryReview`: whether lifecycle memory remains advisory.
- `boundaries`: explicit false flags for PoB compute, network, memory writes, and reference copying.
- `evidenceTags`: includes `lifecycle-route-evaluation`.
- `note`: short reminder that the result is evaluation only, not a build recommendation.

## Reference comparison boundary

The evaluator may compare only non-copyable calibration fields:

- common levers;
- damage types;
- delivery traits;
- defense identities;
- ascendancy context;
- sample size.

If a supplied `reference_profile` contains raw fields such as `pobCode`, `gear`, `items`,
`passiveTree`, `tree`, `passives`, `skills`, or `supportGems`, those fields are ignored and
`reference_raw_fields_sanitized` is emitted. The output must not leak those fields.

## Numeric boundary

Phase 3L v1 does not judge DPS/EHP closeness. Engine-computed evidence only supports numeric claims
inside that local route/stage/subtree. If the route includes computed-looking numeric claims such as
DPS or EHP without local `engine-computed` evidence, the evaluator emits
`unsupported_computed_claim`.

Future phases can add numeric range checks once lifecycle stages carry real
`verify_lifecycle_stage` / `benchmark_build` results.
