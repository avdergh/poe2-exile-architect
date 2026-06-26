# Phase 3K Feedback-Informed Lifecycle Synthesis

## Purpose

Phase 3K closes the local learning loop for lifecycle build research. Earlier phases can record
practice feedback and promote verified lessons, but a later `suggest_build_lifecycle` route should
also surface those lessons back to the agent in a conservative, evidence-labeled way.

This is an advisory memory layer, not a second planner. Memory can change warnings, repair
priorities, transition caution, and explanations. It must not replace PoB verification or invent
DPS/EHP/resistance numbers.

## Contract

`research_build_lifecycle(...)` adds a `memoryContext` object:

- `ok`: always true when local memory was read successfully.
- `scope`: exact `buildId` plus `source: local_lifecycle_memory`.
- `policy`: explicit booleans:
  - `advisoryOnly`
  - `doesNotReplacePobVerification`
  - `singleFeedbackIsEpisodicOnly`
  - `noComputedNumbers`
- `repeatedFailurePatterns`: feedback grouped by exact `(buildId, stage, failurePattern)` with
  `count >= 2`.
- `recentEpisodicReflections`: recent feedback for the exact build id. Single entries are shown
  here, but do not trigger stage warnings.
- `techniqueCards`: promoted durable memory summaries with compatibility labels.
- `stalenessNotes`: explanations for stale or unknown patch/tree compatibility.
- `evidenceTags`: local memory evidence labels.

Stages may add:

- `memoryWarnings`: generated only from repeated failure patterns for the same build id and stage.
- `memoryRecommendedActions`: conservative stage-aware repair actions for those repeated patterns.

## Relevance and safety boundaries

- Feedback is matched by exact deterministic `buildId` only. Phase 3K does not do fuzzy matching
  across similar goals, because that would risk leaking one build's failure into another route.
- The global `failure_patterns` aggregate remains useful for storage statistics, but route synthesis
  derives repeated patterns from `feedback_reflections` grouped by `(buildId, stage, failurePattern)`.
- Single feedback remains episodic: it can appear under `recentEpisodicReflections`, but it cannot
  become a stage warning or durable technique by itself.
- Promoted technique cards are still advisory. A `current` card is not a hard rule; a `stale` card is
  down-weighted and must be re-verified before influencing a build decision.
- `memoryContext` is not part of the lifecycle quality gate's hard pass/fail criteria. New users
  with no memory should still receive valid routes.

## Patch/tree compatibility

Technique cards already store `patch` and `passiveTree`. When summarizing them, compare those values
with `current_compatibility_claim()`:

- `current`: card patch/tree both match known current claim.
- `stale`: card patch or tree conflicts with a known current claim.
- `unknown`: either side lacks enough information, including cards stamped as `unknown`.

Influence labels:

- `advisory` for `current`.
- `downweighted` for `stale`.
- `unknown` for `unknown`.

Stale or unknown cards should produce staleness notes, not hard recommendations.
