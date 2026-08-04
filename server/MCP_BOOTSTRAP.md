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

- Compute authority for the active build: `get_build_stats`, `get_defenses`,
  `inspect_build_completeness`, `evaluate_build`, `verify_lifecycle_stage`, optimizers and all
  mutators.
- Static facts and candidates: item/skill/support/passive/mod searches, graph tools,
  `explain_mechanic`, lifecycle helpers and Research memory.
- Time-sensitive facts: freshness, prices, meta adapters and live wiki fallback. If unavailable,
  continue only with an explicit evidence caveat.

## Create

`/poe-bd-create` is Agent-led. Resolve the intended ascendancy and player active-skill `skill:` key,
then query Research progressively: exact Family summary, selected dimensions, and all record IDs
needed to resolve the design. For Create calls normally use
`query_research_memory(response_profile="create_compact")`
so critical premises remain visible without repeating retrieval plumbing. Record every recalled
item as adopted, caveated or rejected and verify any patch-sensitive interaction.
Do not impose a fixed query, dimension, record-read, or candidate-count ceiling. Reuse an unchanged
query receipt from the working checkpoint, but continue targeted retrieval until design duties,
conditions, failure modes and verification tasks are adequately covered. Compact responses remove
repeated fields, never returned results. Use precise component searches; select, then read exact
detail.
For an exact Family, inspect coverage/index/premises: `limit` is only the first page. Mark every
failure premise resolved/caveated/not-applicable; resolved requires a record-detail receipt.

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
`attemptConsumed=false` before Judge.
After a legal mechanism-complete baseline, run one deliberate high-impact quality pass across
weapon, supports, passive paths, jewels, runes/soul cores and configuration. A Judge warning is not
required to explore a materially stronger option; dedupe only an identical call on the same state
and objective.
Protect every passing legal Judge snapshot. If the quality-pass delta regresses, select the earlier
passing attempt only when its exact process-local snapshot and legality receipt remain available and
later findings are explicitly limited to that delta.
Progression runs compact lifecycle once per Judge/state hash and once artifact-bound after save,
using the same `strict_mode`. Save before review; never delete review markers.

## Complete progression

Progression is anchor-first. Unless the user locked one complete Family, query exact-version
Research for ten mature Families and compare every returned candidate (2-10). Rank mechanism
closure, Research support, goal/power evidence, playability risk and modelability; first is selected,
second is reserve, and modelability alone cannot win. Fewer than two Families pauses for a Research
gap. Only the Agent may explicitly switch once to the reserve after evidence-backed failure; Judge
never switches automatically. Bind the fresh target Phase 5 run, then create and bind the ordinary
target artifact. Build each pre-target
milestone independently; the final target stage reuses the identical target artifact and lifecycle
receipt. Every stage, including `campaign_early`, must be complete and playable at its level.
Freeze design, initialize once, then use scoped deltas. Inherit the prior artifact; rebuilding
requires blueprint `rebuildFromScratch=true` plus `rebuildReason`; other direction changes use the
versioned replan after failure.

The stage packet's memory mode overrides Create defaults; replace a wrong run on the same claim
without retry. Resolve `unavailable:pending_discovery` once from the trusted anchor in the same
progression, then freeze it.

Do not force mature Family recall onto an unascended starter. Use `starter_common` with typed
starter skill identity plus web/corpus/mechanics evidence until ascendancy and the transition
Family are stable; use `family_exact` Research from the transition onward. An unsaved failed
pre-target stage may use its one external retry for an audited versioned replan. If the route still
fails after a trusted target anchor exists, export and disclose the incomplete target recovery
package instead of returning no files.
The same recovery export is required when a control-plane/approval interruption leaves the route
unfinished without successfully recording `failed`.

Long progression conversations must not rely on transcript memory:

- after selecting important Research or changing the mechanism plan, call
  `checkpoint_build_progression_context`;
- normal status reads use `get_build_progression_status(detail="compact")`;
- after automatic context compaction, restart, or uncertainty, call it once with
  `detail="resume"` before further build mutations;
- use `detail="full"` only when a complete safe state is specifically required.

Checkpoint premise decisions/solution refs with conditions, tasks and next actions; never raw
material or hidden reasoning. A caveated target requires `limited_accepted` and route disclosure.

Every pre-target stage needs a Phase 5 artifact and lifecycle receipt. Build a complete
loadout and perform one level-appropriate quality pass without fixed early DPS/EHP gates.
Price is advisory only;
transitions depend on the actual skill, ascendancy,
passive, Spirit, resource, defense, required-item and readiness conditions. Treat those as explicit
transition gates, not prose-only promises.

## Tool discovery

Discover tools in batches. Use the installed skill references for workflow; do not reload the full
assistant guide during one run.
