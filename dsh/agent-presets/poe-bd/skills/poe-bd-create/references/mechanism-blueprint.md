# Create Mechanism Blueprint

Use this reference after the final Research Execution Contract and package decisions are ready,
and before any stateful PoB construction or equipment planning.

## Purpose

The mechanism blueprint is a model-authored design dossier, not a form and not an automatic build
assembler.  Its prose may use any organization that best explains the selected BD.  It must deeply
synthesize the recalled Family knowledge, current graph/mechanic/corpus facts and explicit user
goal into one coherent, falsifiable model of how the build plays and survives.

The blueprint remains a synthesis layer.  Equipment, skills and passives must still be verified
against the underlying Research records and current static/PoB facts; the document never replaces
those sources.

## Content quality

Explain the causal mechanics that matter for this build rather than filling generic headings.  A
substantive blueprint normally makes clear:

- where damage originates, how it is delivered, scaled and kept online;
- how ordinary packs are cleared and which density/on-kill assumptions are involved;
- how single-target/Boss damage works without adds, including setup, ramp and downtime;
- primary defensive pools, mitigation/avoidance, recovery and emergency failure windows;
- life, mana, Energy Shield, Spirit and charge costs/recovery in hit, no-hit, kill and no-kill
  states;
- the player rotation and which actions or conditions are mandatory;
- which skill, Ascendancy, passive or future gear responsibility owns each adopted mechanism;
- failure conditions, modelling limits and concrete verification tasks.

Do not invent missing interactions, values or uptime.  If evidence is insufficient, query the
specific gap or label it `hypothesis` / `unknown`.  Preserve recalled `conditions`,
`failureConditions`, exclusions and verification tasks.  Distinguish source facts from design
inferences.

## Thin evidence index

The free-form document is accompanied by a small typed index:

- `claims`: important mechanism conclusions with `grounded`, `inferred`, `hypothesis`, `unknown`
  or `rejected` status, safe evidence refs, conditions, failures and verification tasks;
- `coverage`: whether `damage_delivery`, `clear`, `boss`, `defense`, `life_recovery`,
  `mana_recovery`, `spirit` and `rotation` are covered, not applicable or still unknown;
- `unresolvedQuestions`: evidence gaps that remain visible to later implementation and Judge.

Document form is unrestricted; only this evidence/coverage index is structured so later phases can
audit omissions and trace conclusions.

## Validation and revision

Call `mcp__poe_build__validate_generation_blueprint` with the candidate ID, current version context, final
`researchMemoryUse`, final `researchExecutionPlan`, blueprint and all referenced ToolReferences.
Every non-unknown claim must resolve to a real Research/package/record or current graph/mechanic/
corpus ToolReference.  The tool returns a `blueprintRef`; include the same blueprint and ref in the
final candidate plus a matching ToolReference.

Do not begin PoB mutations, passive allocation, unique evaluation, `mcp__poe_build__plan_gear`, crafting or item
equipping until the blueprint is accepted.  If later evidence changes the core damage, defense,
resource or rotation model, revise and revalidate the blueprint before continuing.  Draft
validation freezes the accepted blueprint for the selected candidate.
