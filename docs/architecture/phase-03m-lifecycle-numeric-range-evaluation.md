# Phase 3M Lifecycle Numeric Range Evaluation

Phase 3M extends the lifecycle route evaluator with optional numeric range comparison. It answers:
"When a lifecycle stage already has engine-computed verification, do its DPS/EHP values sit in a
reasonable calibration range for mature reference builds?"

This remains an evaluation layer. It never runs PoB, never fetches live data, never writes memory,
and never treats reference builds as templates. It only compares numbers that were already computed
elsewhere.

## Public contract

`evaluate_lifecycle_route(route, reference_profile=None, goal=None)` keeps the Phase 3L output shape
and adds `evidenceReview.numericRangeReview`:

- `status`: `not_evaluated`, `compared`, or `invalid_reference`.
- `stageComparisons`: one row per endgame stage and metric that could be compared.
- `warnings`: non-blocking warning codes, such as `numeric_range_below_reference`.
- `unknowns`: range-review unknown codes local to the range review.
- `note`: reminder that this is calibration, not proof of build strength.

The top-level evaluator may surface warnings from `numericRangeReview`, but v1 does not fail a route
solely because a budget stage is below a mature reference range. It marks the route as
`needs_review` through warnings.

Numeric range input is separate from reference-alignment input. If `reference_profile` contains only
numeric ranges or a raw `benchmark_build` result, the evaluator must still use the route's own
`cohortAnalysis` for non-copyable cohort alignment.

## Accepted numeric evidence

The evaluator may compare only stage-local engine-computed verification:

- stage `id` is `endgame_budget` or `endgame_final`;
- `stage["verification"]` is a dictionary;
- `stage["verification"]["evidenceTags"]` contains `engine-computed`;
- observations contain numeric `offense.TotalDPS` or `totalEHP`.

Planned verification budgets do not count. Textual numeric claims do not count. A route-level
`engine-computed` tag does not certify every stage.

## Accepted reference range shapes

The evaluator accepts either of these safe, non-copyable shapes:

```json
{
  "numericRanges": {
    "TotalDPS": {"min": 100000, "median": 500000, "max": 1000000, "n": 8},
    "FullDPS": {"min": 200000, "median": 800000, "max": 1500000, "n": 8},
    "TotalEHP": {"min": 12000, "median": 22000, "max": 40000, "n": 8}
  }
}
```

or the existing `benchmark_build` shape:

```json
{
  "dps": {"reference": {"min": 100000, "median": 500000, "max": 1000000, "n": 8}},
  "ehp": {"reference": {"min": 12000, "median": 22000, "max": 40000, "n": 8}}
}
```

Only distribution fields are consumed. Raw build content remains ignored by the Phase 3L reference
sanitizer.

`FullDPS` is compared only when an explicit `FullDPS` range exists. The existing `benchmark_build`
`dps.reference` range is a `TotalDPS` range and must not be reused for `FullDPS`.

Reference ranges are valid only when `min` and `max` are finite non-boolean numbers and
`min <= max`. `median`, `p25`, `p75`, and `n` may be copied into comparison rows only when numeric.
Invalid ranges produce `invalid_reference` and no comparison rows.

## Placement semantics

For each metric:

- below `min` => `below_range`;
- between `min` and `max` inclusive => `within_range`;
- above `max` => `above_range`;
- missing or invalid value/range => not compared.

The evaluator does not choose upgrades. If a value is below range, it emits the warning code
`numeric_range_below_reference`; callers should then use the active build's own tools
(`rank_levers`, stage repair actions, and PoB verification) to find the missing multiplier or
defensive layer.

Each comparison row includes `stage`, `metric`, `observedMetric`, `referenceMetric`, `value`,
`referenceMin`, `referenceMax`, and optional `referenceN`.
