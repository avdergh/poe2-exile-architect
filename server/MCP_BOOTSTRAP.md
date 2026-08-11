# Exile Architect MCP bootstrap

Path of Exile 2 corpus, Research, live freshness/prices and one Headless PoB engine share this MCP
session.

## Non-negotiable operating rules

1. Never invent build numbers. DPS, EHP, life/ES, resistances, crit, accuracy, Spirit and sustain
   claims must come from PoB/compute readback for the active build.
2. Before calling a build current-season verified, call `get_freshness_report`. Only
   `verified_current` permits that label; otherwise preserve the returned blockers/caveats.
3. Verify mechanics from the corpus/graph/mechanics tools. Component resolution proves existence,
   not an interaction. Preserve Research `conditions`, `failureConditions`, exclusions and
   verification tasks when adopting a record.
4. All compute tools share one mutable active build and must be called sequentially. Submit exact
   Agent-authored changes through small function-scoped `apply_build_mutation_batch` calls, never a
   mixed whole-build batch; chain each output state hash. It never runs an optimizer. Trust rollback
   only when `rolledBack=true`, and read skill-group fingerprints before precise group edits.
5. Re-check defenses and completeness after gear changes. A legal/Judge-passed build is not
   automatically a strong or smooth build; disclose playability, quality and modelability findings.
6. Never expose or persist third-party raw PoB code/XML, whole-character mirrors, full URLs, account
   details, hidden reasoning or conversation transcripts. Generated final XML is private to the
   artifact/export layer.

## Fact sources

- Active-build facts come from compute/readback; static facts from corpus, graph, mechanics and
  Research; time-sensitive facts from freshness, prices and live sources. If a required source is
  unavailable, continue only with an explicit evidence caveat.

## Create

`/poe-bd-create` is Agent-led. Resolve the ascendancy and active-skill `skill:` key, then query exact
Family Research progressively with `response_profile="create_compact"`. Inspect coverage, index and
premises; `limit` is only the first page. Continue precise, targeted retrieval without a fixed read
ceiling until responsibilities, conditions, failures and verification tasks are covered. Record
each use as adopted/caveated/rejected. Mark every failure premise resolved/caveated/not-applicable;
resolved requires a record-detail receipt.

Assemble a real active loadout: class/ascendancy, level, skills/supports, secondary groups, gear,
passives, config, attributes, resistances, Spirit and resources. The global `optimize_build` path is
temporarily disabled; use targeted tools and manual passive decisions. Use
`inspect_generation_checkpoint`, then `evaluate_generation_candidate`. Create defaults to
`strict_mode=false`: only hard gates and facts cross the trust boundary; scores, bands, warnings,
reward and subjective caveats are hidden.
Use `true` on all validation calls only when explicitly requested; never switch after attempt 0.
Equip a special-source `craft_item` result with its `craftReceiptRef`; item, slot or version drift
fails legality.
The checkpoint and formal entry share a score-free hard-legality audit. Deterministic attribute,
item/gem level, weapon, Spirit, passive-budget and affix failures must return
`attemptConsumed=false` before Judge. Remaining generated `Scaffold ...` gear and rare/magic gear
without `Item Level` are also hard failures in every feedback mode.
After a legal mechanism-complete baseline, run one deliberate high-impact quality pass across
weapon, supports, passive paths, jewels, runes/soul cores and configuration. A Judge warning is not
required to explore a materially stronger option; dedupe only an identical call on the same state
and objective.
Protect every passing legal Judge snapshot. If the quality-pass delta regresses, select the earlier
passing attempt only when its exact process-local snapshot and legality receipt remain available and
later findings are explicitly limited to that delta.
Write the complete final candidate once at the top level. Each `generationAttempts` row may use only
`prototypeBuildCandidate: {candidateId}` plus its failure audit; trusted receipts and artifact
selection supply the selected attempt's immutable state/Judge facts.
Create runs compact lifecycle once per Judge/state hash and once artifact-bound after save,
using the same `strict_mode`. Save before review; never delete review markers.
Lifecycle guidance still covers explicit transition gates and readiness checks: a strong endgame
build may need a separate starter route. Treat gates as explicit requirements, not prose-only
promises, and use the lifecycle research/verification tools before claiming a stage transition.
Price is advisory only.
