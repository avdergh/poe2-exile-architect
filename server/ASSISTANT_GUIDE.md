# How to use Exile Architect for Path of Exile 2

You have a PoE2 toolset with two halves: a **knowledge corpus** (offline game facts) and a
**Path of Building compute engine** (real build math). Read this once — it's how the tools fit
together and how to avoid the common mistakes.

Before describing a build as current-season verified, call `get_freshness_report`. Only
`verified_current` permits that label. `current_unmodelled` requires an explicit calculation
caveat; every `blocked_*` result requires reporting its blockers instead of guessing.

## Operating discipline (the rules that matter most)

1. **Never state a build number the engine didn't produce.** DPS, EHP, life/ES, resistances,
   crit, accuracy — all come from a compute tool. Don't estimate or reason your way to a figure.
   If the engine can't model something, say so plainly instead of inventing a value.
2. **Verify before you assert — especially "the tool is wrong."** If a number looks off, prove
   why with a controlled probe (change one input, re-read) before claiming the engine under-reports
   or is buggy. Most "wrong" numbers are a missing build piece or a default you didn't check.
3. **Ground everything in real data; never assert a mechanic from memory.** Gear comes from real
   mods (`optimize_item`, `search_mods`), never invented affixes. When you are not 100% sure how a
   mechanic/keystone/skill/interaction works — e.g. whether a skill *shotguns* (overlaps multiple
   hits on one target), what limits its rate (cast speed vs cooldown vs mana), or how a support
   behaves — **look it up first** (`explain_mechanic` / `lookup_mechanic`) or prove it with a
   controlled engine probe. Guessing wastes turns and ships wrong claims.
4. **When DPS is far short of endgame, find the missing *multiplier*, don't tweak margins.** The
   dominant multiplier is build-specific — it could be crit (a meta nuke runs ~98% crit / 7× multi),
   a "more"-multiplier stack, ailment/DoT, minions, or "+levels". Find it with `rank_levers`; don't
   default to crit OR mana-stacking — there's no one recipe. The **ascendancy** is a top multiplier
   to check first (a conditional "more vs bosses" can be +50% — but only once its enemy-condition is
   enabled; see the build flow). Note a from-scratch greedy build (`optimize_item`/`optimize_passives`)
   plateaus well below a deeply min-maxed meta build (perfect +levels, top jewels, perfect crit), so
   for a *true* endgame-DPS target, `import_build` a known PoB and copy its archetype (skill + any
   trigger, scaling identity, keystones, jewels), then verify each layer on the engine. See
   `build_advice("Reaching endgame DPS")`.
5. **Re-check `get_defenses` after every gear change.** Resists silently break caps when you
   reshuffle gear for damage — never trade a cap for DPS without noticing.
6. **Don't call a build "done" or "viable" without the gate.** Set explicit goals (anchored to the
   player's content) and pass `evaluate_build`. A one-weapon, few-notable skeleton is not a build.
7. **Use the tools proactively, and label your facts.** Whenever the user asks about a build, item,
   skill, mechanic, or number, use the toolset — and say which bucket each answer came from
   ("PoB computes 1.2M DPS" vs "the corpus lists…" vs "Trade price is roughly…").
8. **Don't default to a particular skill, ascendancy, or archetype.** When the user hasn't named
   one, derive it from their stated goal/content (boss vs farm, playstyle) — using `get_meta_builds`
   as *context* and the engine to compare — instead of reaching for a favorite. This guide names no
   skills on purpose; let the player's goal and the engine's numbers pick. The reference-build
   library (`list_reference_builds` / `benchmark_build`) is **calibration only** — never reproduce a
   reference build as the answer; it exists to range-check numbers and reveal an archetype's lever.
9. **Treat strong builds as a lifecycle, not a static PoB.** A final-form endgame build may be
   impossible or miserable to level with if it depends on a unique, lineage gem, threshold, Spirit
   setup, or late passive cluster. When the user asks for a strong build without a full anchor, start
   with `suggest_build_lifecycle`: present campaign starter → transition gate → budget endgame →
   final endgame. Never recommend switching stages until the transition gate is met.
10. **A verified progression requires real milestone artifacts.** When the user explicitly asks
    for a complete campaign-to-target progression, first use ordinary single-stage Create to build
    and bind an immutable target anchor. Then submit bounded starter evidence and a blueprint and
    claim the pre-target milestones serially. Each pre-target milestone gets a separate Phase 5
    run, Judge, same-hash lifecycle verification and `FinalBuildArtifact`; the final target closure
    reuses the identical anchor artifact/hash without another Create. Never present prose-only
    stages or an automatically downgraded final PoB as independently verified.
11. **A starter is not the final build with fewer points.** For a complete progression, the base
    class is the only hard cross-stage lock. The campaign starter may use a different ascendancy,
    skill package, tree, gear and resource loop from the high-ceiling target. Use bounded current-
    patch web research when the host supports it, submit only safe starter claims, and independently
    verify every real milestone. Web failure permits a labelled limited-evidence fallback.
12. **Price is advisory, not the transition clock.** Use live unique prices and craft effort to
    label acquisition risk. Switch only when the target mechanic's skill, ascendancy, passive,
    Spirit, resource, defense and required-item gates are actually ready.

## Three kinds of facts

- **Computed (engine — authoritative for *this* build):** `get_build_stats`, `get_defenses`,
  `evaluate_build`, `compare_to`, `solve_for`, `rank_levers`, `optimize_passives`, `optimize_item`,
  `optimize_jewel`, `optimize_supports`, `rank_upgrades`, `plan_gear`, `craft_item` (full crafting
  system), `apply_build_mutation_batch` (small function-scoped exact mutations only),
  `inspect_generation_checkpoint` (state-hash merged validation),
  `alloc_passive`/`dealloc_passive`, `scaffold_gear`,
  `search_passives`/`get_passive` (query the
  active tree, with `pathDist` reachability), `verify_lifecycle_stage`, `engine_health`, and every
  `set_*`/`equip_*` mutator (they return fresh stats). Exact for the current build state.
- **Looked-up (corpus — offline, deterministic):** `search_items`/`get_item`,
  `find_skills`/`get_gem`/`find_supports_for`, `search_mods`/`reverse_lookup`,
  `search_uniques`/`get_unique`, `parse_item`, `list_ascendancies`, `corpus_info`, and the mechanics
  layer — `explain_mechanic` / `search_mechanics` / `relevant_mechanics` (wiki tier, PoE2 Wiki
  **CC BY-NC-SA 3.0** — cite the `attribution` it returns), `build_advice` (planning heuristics;
  current pinned PoB data, physical graph, and corpus override patch-sensitive prose),
  and lifecycle memory/tools (`suggest_build_lifecycle`, `analyze_build_lifecycle`,
  `analyze_lifecycle_cohort`, `compare_lifecycle_routes`, `audit_lifecycle_route`,
  `evaluate_lifecycle_route`, `list_transition_gates`,
  `evaluate_transition_readiness`, `plan_lifecycle_stage_verification`, `record_build_feedback`,
  `promote_technique_memory`, plus Phase 4 research-memory tools
  (`build_research_packet`, `validate_researcher_output`, `query_research_memory`,
  `propose_deep_research_records`, `propose_research_fragments`, `append_evidence_to_fragment`, `propose_semantic_edges`,
  `propose_build_patterns`, `submit_revalidation_result`,
  `inspect_rejected_research_proposals`). Static facts to *find* options; the engine *values* them.
- **Live (network — may be unavailable):** `get_prices`, `list_price_leagues`, `get_meta_builds`,
  `get_meta_archetype_trends`, `lookup_mechanic` (live wiki fallback for topics not in the corpus),
  `check_data_version`, `check_for_updates`/`apply_updates`, `update_corpus`. Approximate,
  time-sensitive; if one returns "unavailable," carry on and say so.

## Phase 4 research memory workflow

Phase 4 turns one mature PoE2 build at a time into copy-safe research memory. The product entry is
`/poe-bd-research` / `$poe-bd-research`; internal phase names and script commands are not user
commands.

### Tool map

- `scripts/research_mature_builds.py queue/claim/inspect/read/search`: lease one case and expose
  bounded transient evidence. `inspect` lists sections; `read` paginates them; `search` locates a
  concrete name but never replaces complete section reads.
- `query_research_memory`: compare the independently reconstructed case with accepted memory.
  Query summaries first and deep-read only selected record IDs.
- `graph_tool_query(tool_name="search_graph_components")`: discover concrete graph candidates by
  name and type. Candidate similarity is not endpoint authority.
- `graph_tool_query(tool_name="resolve_graph_component")`: confirm a stable physical-graph key.
  Only resolved keys may authorize semantic edges.
- `propose_deep_research_records`, `propose_research_fragments`,
  `propose_build_patterns`, and `propose_semantic_edges`: validate candidate schema, resolver
  evidence and copy safety. In the queue workflow these tools do not persist durable memory.
- `append_evidence_to_fragment`: add safe evidence to an already accepted equivalent fragment
  instead of creating a duplicate.
- `submit_revalidation_result`: renew, narrow or supersede accepted knowledge after version review.
- `scripts/research_mature_builds.py review-contract`: disclose the exact safe-review structure and
  canonical enums just before writing.
- `scripts/research_mature_builds.py init-review`: atomically create the current lease's UTF-8,
  two-space-indented review skeleton without overwriting an existing artifact.
- `scripts/research_mature_builds.py accept --validate-only`: run the real acceptance logic without
  changing durable memory or queue state. Plain `accept` is the only durable writer.

If tools are not shown eagerly, use the host's normal tool discovery/search by exact name before
declaring them unavailable. The unified MCP exposes the research tools; this behavior is not based
on a documented tool-count cap.

### Runtime flow

- Never delegate a research case to a subagent or separate agent lane. The current main conversation
  must read the bounded evidence, analyze the case, write the safe review and run acceptance.
- If no arguments are supplied, ask for a mode before any network crawl: preflight 5
  (`--dry-run`), small extraction 20, large extraction 50, or resume. Resume must not be tied only
  to the large-batch option.
- Use `--class "Blood Mage"` when the user supplies poe.ninja's `class` filter. It is passed through
  to the list URL as `class=Blood+Mage`; URL-style input such as `--class "Blood+Mage"` is normalized
  before encoding and must not become `class=Blood%2BMage`. On the current site this names an
  ascendancy, not the PoB base class. The collector also applies the normalized class locally so
  unrelated ascendancies cannot consume the requested sample limit. `--ascendancy` remains a local
  post-render filter.
- Treat the skill invocation as a chat request. Do not ask Codex Desktop users to paste PowerShell/Python commands into the chat box.
- This is a runtime product workflow. Do not edit source, tests, docs, schemas or installers while
  executing it. Report safe collector/source/runtime errors and stop.
- Script order is `queue -> claim -> inspect/read/search -> memory/graph research ->
  review-contract -> init-review -> edit safe review -> accept --validate-only -> accept -> status`.
- A non-dry-run `queue` without an explicit output directory creates
  `.poe-bd-research/runs/<runId>` and returns `runDir`. Preserve that value as `--output-dir` for
  every later command in the run. Never fall back to the shared `.poe-bd-research` root. Existing
  queue databases are not overwritten; `--resume` requires the original `runDir`.
- `claim` atomically returns the safe `workerPrompt`, lease identity and review path. Follow it
  directly; `worker-brief` is resume-only. Do not rely only on a local `SKILL.md` path.
- Finish acceptance for the current case before claiming another. Do not carry transient evidence
  across cases; reuse only tools, the skill and accepted memory.
- Reconstruct skills/supports, rotation, mechanism chains, gear and passive responsibilities,
  resource/defense engines, tradeoffs, failure conditions and modelability gaps before querying
  durable memory. The research skill owns the full depth checklist and calibrated examples.
- Keep one resolved ascendancy and one `primary_damage` skill consistent across a research group.
  `clear_skill`, `boss_skill`, `triggered_payload`, and a `trigger_host` delivering a triggered or primary payload are inferred Family
  core skills and must not be repeated in `typedPayload.familyCoreSkillKeys`. Supports stay outside
  Family identity, but `skill_package` records preserve ownership in `typedPayload.supportPackages`.
- `passiveAscendancy` coverage requires an ascendancy shell plus concrete resolved ascendancy
  responsibilities. Mutated random item instances are case-only evidence, excluded from normal
  creator retrieval and planner patterns.
- A `resource_engine` based on ordinary leech, flasks or affixes needs lower_snake_case
  `typedPayload.resourceMechanisms` when no resolved physical resource component identifies it.
- Do not invent role, axis or pattern enums. A canonical role describes build function and may be
  compatible with more than one physical graph node type; follow the just-in-time compatibility
  map and resolver evidence, and put every resolved stable key in `componentKey`. Write the review
  as UTF-8, two-space-indented JSON so a bounded repair can edit one field safely. Edit only the
  lease-bound review file; do not assemble the complete JSON with PowerShell here-strings,
  inline `ConvertTo-Json`, or `Set-Content`.
- `readyForAccept=true` means a safe subset can be accepted. Prefer
  `fullyResolvedForAccept=true` / `acceptanceMode=clean`; for `partial_with_deferred`, repair
  type/role/query/key mistakes before accepting and retain only genuine source or bounded ambiguity
  gaps.
- One sample can establish only a `case_observation`, not a common or usual pattern. Patterns and
  semantic edges remain advisory planning context, never hard legality.
- Mark a pattern `transferScope=component` only when it expresses a causal module with explicit
  applicability requirements, exclusions, rationale, and verification tasks. Single cases cannot
  claim global scope. Cross-Family promotion is backend-derived and capped at `likely_pattern`;
  `common_within_archetype` and `strong_ranking_hint` remain Family/archetype-only. Component scope
  grants conditional cross-Family retrieval; it does not reduce the pattern's priority inside any
  Family listed in `originFamilyKeys`.

Queue, claim, inspect, read, search, review-contract, init-review, validation and acceptance outputs are safe-only.
Raw PoB code/XML, account or character details and whole-character mirrors remain confined to the
lease-bound OS-temp packet. Durable records may preserve a complete reusable core mechanism package,
including exact key skill/support roles, local passive connections and item/resource interactions,
without reproducing the whole third-party character.
## Phase 5 create workflow

Phase 5 generation is being built incrementally. The user-facing product entry is
`/poe-bd-create` / `$poe-bd-create`. In the current Agent-led prototype, the Agent refines the user
request, queries tools, designs the candidate, and assembles the complete active PoB state. The
program snapshots that state, runs the Phase 1 Judge, and prepares a safe human review packet. It
does not take over build completion.

- Treat `/poe-bd-create` as a chat-level skill invocation, not a shell command for the user to run.
  The host agent should execute the internal script with its tools and summarize the safe result.
- Before any ordinary `/poe-bd-create` tool call, ask whether the user wants a complete leveling
  progression with independently built/validated stage PoBs or one target-level build with at most
  textual leveling advice. Skip this blocking question only when the request explicitly says to
  produce one fixed target/final build without progression. Do not call freshness, Research,
  `start_generation_run`, progression, or PoB tools until the user answers. Ask only once per request. Internal
  `referenceBlind=true` Create packets remain non-interactive. If invoked with no arguments, combine
  this choice with the normal goal/constraint question.
- Generation run flow: call the plugin MCP tool
  `start_generation_run(memory_mode="memory_assisted")` (or `memory_mode="no_memory"` when the
  user explicitly invokes `/poe-bd-create --no-memory`). Do not search for a repository checkout,
  run a relative helper script, or guess the current working directory. The published plugin owns
  the run store. Assemble the active PoB with small
  `apply_build_mutation_batch` calls using one `batch_kind` at a time:
  `bootstrap`, `mechanism_shell`, `skill_loadout`, `passive_delta`, `required_gear`,
  `ordinary_gear`, then `config` as needed. Do not mix the whole build into one transaction.
  Only a bootstrap starting with `new_build` may omit `expected_state_hash`; carry every
  `outputStateHash` into the next batch. A rejection preserves earlier committed scopes and rolls
  back only the current one; continue only when `rolledBack=true`. If
  `recoveryRequired=true`, later functional batches are blocked until an explicit bootstrap from
  `new_build` recovers the session.
  Then call
  `inspect_generation_checkpoint()` and repair completeness/preflight blocking issues before calling
  `evaluate_generation_candidate(run_id, run_token, candidate_id, version_context)`. Perform at
  most two Agent-led retries in the same conversation and same run. Each compact attempt needs only
  its index, candidate, and failure audit; trusted state and Judge fields are hydrated from the
  run-bound receipts. Submit the safe object to
  `validate_generation_output(run_id, run_token, agent_output)` until the contract passes, then
  submit the same final object to `complete_generation_review(run_id, run_token, agent_output)`.
  Both tools persist internally under managed user data; the Agent never edits a run file.
- `optimize_build` is temporarily disabled by default and is not part of Create. Do not use global
  passive-tree resets/replans either. Use targeted support/item tools and exact passive decisions
  for identified gaps and deliberate high-impact quality exploration; a Judge warning is not
  required first. Generated candidates at level 80+ must reach at least 60% fire/cold/lightning
  resistance and 30% chaos resistance; Chaos Inoculation only waives the chaos minimum. The shared
  preflight blocks this before Judge without consuming an attempt. Lower-level stages and trusted
  reference builds remain `judgeElementalResistancePolicy=diagnostic_only`; level 80+ generated
  candidates use `judgeElementalResistancePolicy=endgame_minimums_60_30`. Elemental Max Hit and
  other defense evidence remain evaluated.
- Progression lifecycle verification has a separate level-aware elemental resistance floor, using
  the evaluated PoB level rather than the lifecycle label or caller hint: 30% at levels 45-64, 50%
  at 65-79, and 60% at 80-89. It adds no percentage floor below 45 or at 90+, and never requires
  75% capped resistances as a lifecycle hard gate. Chaos resistance remains governed by the Judge
  and gear-planning contracts above rather than this lifecycle check.
- `trustedEvaluation` covers only the immutable snapshot and Judge result. The tool intentionally
  returns `trustedEvaluationScope=snapshot_and_judge_only` and `versionContextTrusted=false`;
  cross-check the supplied version context against this run's freshness result before making a
  current-season verified claim.
- Normal create mode uses progressive research recall. Normally pass
  `response_profile="create_compact"` on Create queries so the response lifts conditions, failure
  conditions and verification tasks into `criticalPremiseDigest` without repeating retrieval
  plumbing; durable typed receipts are unchanged and compact mode does not truncate result lists.
  Use `response_profile="full"` when a concrete ambiguity depends on an omitted field. Resolve the
  intended ascendancy and primary
  skill to stable graph keys. The first exact-Family query sets `ascendancy_key` and
  `primary_skill_key`, while `component_keys` contains only those two identities; ordinary supports,
  utility skills, and secondary skills must not become mandatory AND filters. Natural-language
  `query` expresses planning intent and ranking preference, not Family identity.
  `query_research_memory` treats graph-backed gem/active-skill keys as the same physical component.
  Inspect `buildFamilies`, including `secondarySkillKeys` and `recordKindCounts`, plus
  `deepResearchRecords`, `buildPatterns`, and `semanticEdges`. After selecting a Family, use
  `build_family_keys` and `record_kinds` to fetch dimension-specific summaries, then
  `detail_level=record` with every `record_id` needed to close the design. Apply `supportPackages`
  as verified
  support candidates, `gearResponsibilities` as gear roles rather than copied items,
  `ascendancyResponsibilities` as node-selection evidence, and `resourceMechanisms` plus rotation
  records as resource/failure-state checks. Record the real `dedupeQueryRef` values, recalled item IDs,
  and adopted/caveated/rejected applications in `researchMemoryUse`. A `case_observation` is a
  candidate hypothesis, not a general rule. Before adopting a claim about an item, passive, trigger,
  conversion, or resource interaction, verify its premise against current static/mechanic evidence;
  successful component resolution proves existence, not the claimed interaction. If exact Family
  evidence is missing/thin or a concrete
  design axis remains unresolved, query the primary skill alone and/or set `include_transferable=true`
  with canonical `research_axes`. Read the separately returned `transferablePatterns` as lower-priority
  conditional inspiration, never as current-Family evidence. A component-scoped pattern from the
  queried Family is returned in `buildPatterns` with Family weight and is omitted from
  `transferablePatterns` to avoid duplication. An explicit `no_matching_memory` result is valid; a
  tool-only call with no structured use is not. No-memory mode skips only research memory, keeps
  every other corpus/graph/mechanic/PoB/Judge tool available, leaves `memoryReferences` empty,
  omits `researchMemoryUse`, and sets `researchMemoryRef=disabled:no_memory_baseline`. The product
  does not automatically compare or choose between these modes; the user may run the same request
  both ways.
- If a retry changes the trusted ascendancy or primary skill, resolve the new identity and call
  `query_research_memory` again. The new attempt must use a fresh `dedupeQueryRef`; support, gear,
  passive-path, or configuration-only repairs do not require another memory query.
- Probe MCP availability by actually calling `get_freshness_report`. Do not claim that the PoE2 MCP
  tools are unavailable merely because they were not found through shell/file search or were not
  shown in a UI group. If that MCP call is genuinely unavailable, stop the build-generation run;
  do not substitute an old candidate or repository artifact.
- A generic freshness decision of `blocked_stale` does not automatically stop Phase 5 generation.
  Game-patch compatibility is compared by season family: patch details such as `0.5.3`, `0.5.4`,
  and `0.5.4b` remain compatible with season `0.5`. Preserve the exact patch in provenance, but
  do not stop generation solely because those details differ. A cross-season or passive-tree
  conflict still blocks current verification.
  A `github_rate_limited` provider diagnostic only means the latest official commit could not be
  refreshed. If the report has already corroborated the same passive-tree generation from the
  validated local runtime and poe.ninja and exposes no tree blocker, do not call the tree unusable.
  If the current game patch, league, and passive tree are known and only local `pob_engine` or
  `pob_data` is stale, continue in stale-PoB limited-evidence mode: assemble the build, run Judge,
  and clearly forbid current-patch verified claims. Stop or clarify when the current game rules,
  passive tree, or required core mechanic data is conflicted or unknown. Inspect component blockers;
  never branch only on the top-level decision name.
- Every generation request must use the new run binding returned by `start_generation_run`. Never
  read or reuse a previous review packet or historical candidate as the current request's output.
  The managed run service rejects mismatched run
  credentials, and a second review of an already accepted run.
- `evaluate_generation_candidate` is the only formal Phase 1 Judge entry for generated candidates.
  `evaluate_build` and `pinnacle_readiness` are local numeric gates, not substitutes for Judge.
- Its `version_context` must include `league`, `ruleset`, `gamePatch`, `passiveTreeVersion`,
  `pobVersionOrCommit`, `graphSnapshotId`, and `researchMemoryRef` in one call, using values from
  the current freshness, graph, and memory queries.
- Before formal evaluation, reset with `new_build`, then assemble and read back a real active build:
  class/ascendancy, level, main and support gems, secondary groups, gear, passives, combat config,
  attributes, resistances, Spirit, and resource state. Do not submit a class-plus-skill skeleton.
- The evaluation tool snapshots the active build, evaluates the immutable XML in a dedicated Judge
  engine, and persists only a raw-free receipt bound to the run and candidate. The exact XML remains
  process-local only until final artifact save; the receipt's semantic state hash lets the saver
  reject real build changes without mistaking refreshed PoB output nodes for mutations. Never invent
  or edit its snapshot id, source hash, semantic state hash, hard failures, caveats, or score.
- Create validation defaults to `strict_mode=false`. The Judge still computes internally, but the
  trusted report and every downstream artifact expose only deterministic hard failures, pass state,
  snapshot binding, selected-skill/socket diagnostics, and attribute shortfalls. Aggregate score,
  quality band, playability/quality warnings, reward, modelability scoring and subjective caveats
  are suppressed. Only an explicit user request for strict mode authorizes
  `strict_mode=true`; use it consistently for preflight/checkpoint, lifecycle and every Judge
  attempt. A run rejects mode changes after its first attempt without consuming a retry.
- Preflight and Judge use the same captured XML. A deterministic preflight blocker returns
  `generation_preflight_failed` without creating a Judge engine, receipt, or retry attempt.
- Treat `rewardLimitReasons` and the sanitized `offenseEvidence` separately from legality. Positive
  strong-evidence DPS below a stage floor is an established measurement that missed the floor, not
  a delivery-evidence gap. Limited evidence must never become a strong reward. A non-endgame level
  is scope, not an automatic score or reward penalty; compare only within the same stage contract.
- The helper receives Agent-produced safe artifacts: `agentRefinedBuildPrompt`,
  `prototypeBuildCandidate`, `transientBuildState`, `judgeAdvisoryReport`, and optional
  `toolFeedbackEvents`.
- Run every PoB/compute tool sequentially. Some tools that look read-only temporarily mutate and
  restore the one active build while measuring alternatives, so tool names are not a safe basis for
  parallelism. Only corpus, graph, mechanic, and other static queries that do not touch the active
  build may run in parallel.
- An available transient state must include `testedSkillGroups`, recording each tested group's index,
  neutral PoB-current/additional role, all active skills and their count, actual supports, and enabled
  state. `mainSocketGroup` is the PoB calculation focus, not proof that a build has only one main
  damage skill. The trusted Judge report distinguishes the selected offense component from
  conditional supplemental components and provides socket-group diagnostics and concrete attribute
  shortfalls. Numeric claims such as mana cost or Spirit must be traceable to this tested configuration.
- P5.1 output is safe-only and must not include hidden chain-of-thought, raw transcript, raw PoB
  code/XML, account or character details, full URLs, or raw database/graph query text. Phase 5
  candidates may contain Agent-generated skill packages, support packages, gear-slot summaries,
  passive anchors, and transition routes; the helper must not reject them merely because they
  resemble a strong or common build.
- Interpret lifecycle fields carefully: `currentOutputStages` is the current stage set to output now,
  while `targetLifecycleStages` is the broader lifecycle target that should shape class and design
  direction. For "starter now, respec later into bossing/endgame", preserve future targets and keep
  `crossStageLockedDimensions=["class"]`; later stages may change ascendancy, skills, passives,
  gear, and supports.
- Report `lifecycleEvidenceCoverage` to the user. It is derived from the final trusted snapshot and
  validates at most one lifecycle stage; all other claimed stages remain text-only until separately
  snapshotted and judged.
- Copyable build links or PoB-like material in the user request must be redacted before persistence
  and carried only as caveats or clarification items.
- Lifecycle helpers may return only stage structure, transition gates, and design principles. Missing
  concrete skill names from a lifecycle helper is not a failure; the Agent should choose skills with
  skill, mechanic, and compute tools.
- `complete_generation_review` requires the trusted receipt. It rejects a missing receipt, candidate mismatch, or
  any Agent-side change to the returned transient state or Judge report. Acceptance means the
  packet is ready for human review, not that the human accepted the build or that Judge is an
  infallible power oracle.
- A Judge `error` means the Judge invocation failed; it must not carry build hard failures. If the
  snapshot tool rejects an incomplete active build, continue assembling it before review.
- In explicit strict mode, Judge has four separate layers: `hardFailures` for deterministic illegality,
  `playabilityFailures` for severe but legal weaknesses, `qualityWarnings` for missed quality
  targets, and `modelability` for what PoB can support. `passed=true` means legality passed only. A
  `barely_playable` candidate, any playability failure, a goal-critical zero score (for example
  offense or recovery in a starter request), or an unresolved support conflict should be repaired
  when retries remain. If
  retries are exhausted, present it only as a weak prototype with explicit gaps, not a recommended
  smooth starter. In default hard-only mode these fields do not exist and must not be reconstructed
  from hidden Judge output. Starter review still covers clear speed, boss/single-target duty and
  sustain using Research, mechanism evidence and raw PoB facts.
- Under the current temporary delivery policy, non-hard Judge findings do not block final artifact
  save or export after retries are exhausted. A candidate may be exported when Judge evaluated it,
  `passed=true`, there are no `hardFailures`, and the trusted active snapshot is still valid. Preserve
  every playability failure, quality warning, zero-score caveat, quality band, and score-applicability
  limitation in the user-facing result when strict mode was explicitly requested; exportability is
  not a quality endorsement. In hard-only mode report that subjective Judge feedback was suppressed,
  not an invented quality grade.
- In explicit strict mode, `scoreApplicability="unavailable"` means the core mechanic cannot be scored reliably. Do not quote
  aggregate/DPS strength, call the build illegal, or silently replace the requested archetype merely
  to make it modelable; preserve it as a legal candidate requiring reference or in-game validation.
- If legality fails, modify the active build without starting
  a new generation run, then evaluate again. Keep each returned evaluation as a separate immutable
  `generationAttempts` row. There may be at most three attempts total (initial plus two retries).
  Each row carries a short failure-audit conclusion and planned changes, never hidden reasoning.
  Stop after the safe human review packet. A normal `/poe-bd-create` run does not start comparative
  learning by itself. Only in explicit strict mode may a concrete playability finding inform this
  retry decision; it still cannot replace Agent judgment.
- If the final attempt passes legality, has no playability failures, has applicable scoring, and the
  Agent accepts it, call `save_final_build_artifact` before the review helper consumes the run token.
  Only the latest trusted attempt can be saved. Failed and
  older attempts keep safe Judge summaries but never persist full PoB XML. The artifact tool stores
  the exact Judge XML privately and returns only safe metadata; never copy XML into chat or the
  review packet. If a process restart discarded that exact transient snapshot and raw serialization
  has changed, `trusted_evaluation_snapshot_unavailable` requires a fresh evaluation when retries
  remain; never substitute a different XML or hand-edit a hash.
- After saving, call `export_final_build_package` once. It always inventories the expected PoB XML,
  import-code text, and official `.build` deliverables. Report every inventory row: successful rows
  with paths, failed rows with error codes. Never silently omit a format or paste raw file contents.
- Separate design judgment from tool-verified evidence in user-facing text. Expected campaign feel
  is an Agent judgment; PoB/Judge-verified defenses, sustain, and stage gates are evidence claims.
- The sections below describe general compute-tool usage. For `/poe-bd-create`, formal evaluation
  still ends with `evaluate_generation_candidate` and the safe human review packet.

## Phase 7 comparative learning

- Use `$poe-bd-learning-loop` only when the user asks to profile a reference build, run comparative
  learning, resume a learning campaign, or inspect its status. The repository state service does not
  create Desktop tasks or call a model; the skill coordinates visible tasks.
- A case uses one Reference/Comparator task and a different Create task. The Create task receives
  only the exact `FamilyTarget`, target level, version context, and the default goal: softcore trade,
  no fixed budget, favor overall strength and playability.
- Query Learning Memory inside the active Create claim. The service binds Family/level/version,
  persists only a safe query receipt, and returns a new campaign revision. The final
  `learningMemoryUse` must match that receipt and record an adopted/caveated/rejected decision for
  every recalled lesson.
- Never include reference gear, passives, skill groups, mechanism summaries, configuration, Judge
  results, source URLs, PoB code, or XML in a blind Create packet. Ambiguous Family or level evidence
  fails closed.
- Blind Create must not query or consume Phase 8 starter-research packets, starter cache entries or
  progression state. Those web-derived candidates belong only to an explicit progression request.
- The Phase 5 run may use its existing bounded internal attempts, but after comparison the same case
  is never regenerated or repaired. Improvements apply only to later cases.
- Compare damage loop/delivery, skill duties/supports, configuration realism, trigger/conversion
  chains, gear/passive/ascendancy synergy, clear/boss/burst, defenses/recovery/resources/Spirit,
  mobility/playability, legality/modelability, and gear effort/attainability.
- Judge data must be attached with `advisoryOnly=true`. It must never automatically choose the
  overall verdict or write a reward.
- Route concrete skills, mechanisms, rotations, gear, passives, defenses, resources, tradeoffs,
  failures, and modelability knowledge through Research schemas. Learning Memory is only for
  cross-dimensional guidance about how a future Create should reason or verify.
- Learning Memory corrections are append-only. Recall both the effective lesson and relevant
  correction/do-not-repeat summaries; a corrected equivalent lesson needs the old correction ref
  plus new evidence before it can be submitted again.
- Campaigns default to ten strictly serial cases with a three-case rolling window. A first-three vs
  last-three improvement is directional evidence only, never a causal claim.

## Phase 8 multi-stage progression

- Enter progression mode only for an explicit complete campaign-to-target request. A normal
  single-stage Create keeps the Phase 5 save/export flow and level-band semantics. Progression
  verification floors such as 82/92 must never change ordinary Create behavior.
- Long progression conversations must use the bounded semantic working set. After selecting
  important Research, changing the mechanism plan, before Judge, and before stage completion call
  `checkpoint_build_progression_context`. Save only adopted/caveated/rejected evidence, critical
  conditions, failure conditions, verification tasks, concise mechanism/configuration conclusions,
  unresolved items and next actions — never hidden reasoning or raw material. Normal status polling
  uses `get_build_progression_status(detail="compact")`; after context compaction, restart or
  uncertainty, call it once with `detail="resume"` before another PoB mutation. Use `detail="full"`
  only for a specifically required complete safe state.
- For one unchanged target/stage Family, do not impose a fixed summary, dimension-query, record-read,
  or candidate-count ceiling. Continue targeted retrieval until design duties, critical conditions,
  failure modes and verification tasks are adequately covered. Component/passive/mod/item searches
  use precise queries and read exact detail after choosing candidates; their default result count is
  not a maximum. A resume packet prevents replay of an identical query receipt, not new evidence-
  seeking queries.
- For an exact selected Family, inspect `familyRecordCoverage`, `familyRecordIndex`, and
  `familyPremiseCatalog`. The query `limit` controls only the first expanded page. Build explicit
  decisions for every failure premise: `resolved`, `caveated`, or `not_applicable`. A resolved
  premise must cite a solution record actually returned by a `detail_level="record"` receipt;
  seeing its ID in a summary is insufficient. Ordinary single-stage Create and progression targets
  use the same receipt audit through `ResearchMemoryUse.premiseDecisions`. Continue targeted
  Family/component/kind/record/failure-text queries
  until each design responsibility is handled; alternative solutions are valid and no named
  mechanic is hard-coded.
- Call `start_build_progression` with the base class, target level, safe goal and current
  `VersionContext`. Preserve every returned revision and use a unique operation id for each
  mutation. Unless the user supplied a complete unique locked Family, new runs start in
  `selection_pending` and return a `TargetCandidateSelectionPacket` plus an exact Family-discovery
  request.
- Run `query_research_memory(detail_level="family")` with the packet's class key, exact game patch,
  passive-tree version and optional hard Family filters. It requests ten mature Families and returns
  every eligible Family when fewer exist. Only exact-version, valid, creator-visible, train-context,
  copy-safe deep Research qualifies; never backfill the comparison with stale/old-patch or invented
  Families. Five to ten candidates are sufficient coverage, two to four are limited coverage, and
  fewer than two pauses the progression as a Research gap.
- Compare and completely rank every Family returned by the trusted discovery receipt (2-10), not a
  hand-picked subset. Compare mechanism closure, Research support, goal fit and strength evidence,
  playability risk, and modelability. The first rank is selected and the second is reserve.
  Modelability alone must not select a Family that has no advantage in the first three dimensions.
  Do not assemble full gear/tree, run formal Judge, or call a global optimizer for these candidates.
  A complete user-locked identity skips discovery and cannot switch Family. Call
  `submit_build_progression_target_selection`; only then use the returned
  `TargetAnchorCreatePacket`.
- Before starter research or blueprint work, follow the ordinary single-stage Create workflow from
  a blank build for the requested target level. Use normal progressive Research recall, Phase 5
  retries and Judge. Bind the fresh run with `bind_build_progression_target_run`. Run the target-level
  lifecycle gate on the active snapshot before saving;
  repair a failed/unknown resource or mechanism check within the existing Phase 5 retries. After
  `inspect_generation_checkpoint` separates hard legality, mechanism readiness, and quality
  advisories. Deterministic attribute/item/gem/weapon/Spirit/passive/affix failures return
  `attemptConsumed=false` and must be fixed before Judge. Once the first legal attempt passes,
  protect it as a baseline and still perform the required active quality pass. Select a better legal
  attempt when found; if the quality delta regresses, save the earlier exact passing snapshot with an
  explicit candidate-delta-only reason. This also applies when the quality delta is rejected by
  deterministic preflight before it can create another Judge receipt: active-state divergence must
  still be proven, and the earlier in-process Judge snapshot remains the only savable source. After
  saving, call
  `verify_lifecycle_stage(..., artifact_id=..., detail="compact")` exactly once to
  create a trusted
  `verificationRef`, then consume review. Do not export the anchor individually or read starter
  evidence while building this target.
- Resolve the target ascendancy and primary skill to stable keys. Build
  `TargetDesignCoverage` with exactly ten dimensions: skill package, clear, boss, delivery,
  ascendancy/passives, gear synergy, defense/recovery, resource/Spirit, combat configuration, and
  modelability. A `research_adopted` dimension must cite a Family, deep record, pattern, semantic
  edge, or fragment actually adopted from the candidate's typed Research results; a `dq-*` query
  receipt alone proves retrieval, not adoption. An `independently_verified` dimension must cite
  the current target artifact or its Phase 5 run/source-hash evidence. Call
  `bind_build_progression_target_anchor` with the artifact-bound `verificationRef`. A
  failed/unknown lifecycle result or a final failure audit classified as a true/mixed build
  failure cannot become an anchor. Judge scores and warnings are advisory only. If any premise is
  `caveated`, use `limited_accepted`, cite its premise id in TargetDesignCoverage, and preserve the
  risk in the route report; do not silently use `accepted`.
- If the first-ranked Family cannot close its mechanism, remains qualitatively unacceptable after
  the complete quality pass, or lacks evidence, call `fail_build_progression_target_anchor`. Only an
  explicit Agent decision with evidence may call `reselect_build_progression_target_candidate`, and
  only once to the recorded reserve; Judge never switches automatically. Tool/approval/control
  interruptions use the one same-Family `retry_build_progression_target_anchor`, not a Family switch.
  Bind the final artifact with `acceptance_decision=accepted` or `limited_accepted`; preserve all
  limited caveats in the route.
- Mature progression Family identity uses the player `active_skill` `skill:` key. A graph-backed `gem:`
  key may be used for Research discovery/querying because typed receipts preserve the verified
  gem/active-skill equivalence set, but do not put the gem key into `TargetAnchorIdentity` or
  `StageFamilyIdentity`. A pre-ascendancy or otherwise not-yet-mature starter is not a Family:
  use `knowledgeMode=starter_common`, `StarterStageIdentity`, and public starter/corpus/mechanics
  refs instead of inventing an ascendancy or forcing an empty mature-Family lookup.
- Research and PoB may use different display names for the same component. Keep the stable key as
  the Family authority and put the artifact's actual display name in `TargetAnchorIdentity`. The
  typed Family discovery receipt must first validate the candidate key. When the names differ, the
  artifact's exact graph snapshot must uniquely resolve the artifact name to that same key; the
  Research Family title need not itself be a graph alias. Missing, ambiguous, cross-snapshot, or
  different-key artifact resolutions fail closed.
- If the target Family has confirmed core secondary skills, include aligned stable keys and
  canonical names in `TargetAnchorIdentity`; every name must exist in an enabled tested skill
  group of the same artifact.
- `StarterResearchPacket` and stale candidates are deliberately withheld from the start/status
  response while target selection or anchor creation is pending; only a cache-presence flag may be
  visible. After the
  anchor is bound, read the safe exact-patch packet from status. Otherwise the host Agent may
  perform bounded web research:
  at most six sources, preferably current-patch level-banded guides.
  Aggregators/comments only discover sources. Two independent current-patch sources, or one
  exact-patch structured/official/creator guide with explicit level bands, is required for
  `supported`; otherwise submit `limited`. If the web is unavailable, submit
  `limited_offline_inference` and continue with clear caveats.
- An expired or same-season mismatched cache entry is returned only as a safe
  `starterResearchCandidate`. Revalidate it and submit a new packet; never bind it directly.
- Read each progression tool's nested input schema before assembling starter packets, blueprints,
  cost requests or completion reports; do not infer typed fields through repeated failed calls.
- Pass source URLs only through transient `intake_starter_research_packet` input. It hashes them
  immediately. Never put page prose, full URLs, PoB material, whole gear/passive/skill mirrors or
  account/character data in starter claims, blueprint state or chat.
- For skill-package claims, structure each resolved skill's clear/boss/setup/payoff duties plus
  what it provides and requires. Preserve applicability and exclusion conditions. Do not harden an
  ambiguous "skills share clear and boss duty" summary into one primary skill before checking the
  actual setup/payoff loop.
- Starter web research must not stop at the named main skill. Search for stage-appropriate Spirit
  or reservation skills, a separate boss/setup skill, their approximate availability, Spirit or
  resource requirements, and the duty each adds. A guide that omits Spirit skills does not prove
  that none are useful; verify candidates through corpus/mechanics/PoB. If no useful option is
  available at that level, record the checked alternative and use a non-Spirit secondary/mark/
  curse/setup package instead. This is a soft design instruction, never a fixed skill-count,
  reservation, DPS, Judge, or Lifecycle gate.
- `ProgressionBlueprint` normally has four real milestones, may merge unchanged milestones, and is
  capped at five. The default four artifacts are the bound target anchor plus three pre-target
  starter/bridge milestones. Every milestone has a stable `stageId`; the final target stage must
  reference `targetAnchorArtifactId`, the same target Family and target level. The base class is the
  only cross-stage lock.
- Before locking the starter blueprint, compare at least two plausible skill packages cheaply:
  duties, setup/payoff premises, availability, weapon compatibility, resource method, Spirit or
  reservation synergy and explicit exclusions. Each candidate should explain clear, rare/boss and
  persistent-buff duties instead of presenting one main skill as the whole build. This is candidate
  selection, not another Judge gate. Do not run the endgame-oriented
  `optimize_build` while choosing the direction; compare the route first, then build the selected
  stage completely.
- Obey each `StageCreatePacket.optimizationPolicy`. Every stage, including `campaign_early`, uses
  `loadoutScope=stage_complete_loadout` and `qualityGoal=complete_stage_build`: deliver a complete,
  strong and playable build for that level, with full skill duties, suitable gear, a coherent
  passive plan, resource closure and practical operation. Do not excuse missing work as a temporary
  stage, and do not invent fixed DPS/EHP, gear-slot or passive-point thresholds. Whole-build and
  global passive-tree optimization remain disabled; use deliberate, targeted local exploration.
- Freeze the route design before PoB construction. The packet's
  `mutationStrategy=single_initialization_then_function_scoped_deltas` permits one initialization,
  then function-scoped changes only. Later stages inherit the prior artifact unless the blueprint
  declares a genuine skill/ascendancy/resource-system transition with `rebuildFromScratch=true` and
  a non-empty `rebuildReason`; the first stage cannot declare rebuild. After claim, ordinary
  legality, sustain, gear, passive or support failures require local repair. A whole direction may
  change only through the existing one-time versioned stage replan after deterministic failure;
  this is `designChangePolicy=blueprint_declared_or_versioned_replan_only`.
- Route knowledge by maturity. `starter_common` stages use `StarterStageIdentity`, no mature Family
  query refs, `generationMemoryMode=standard`, and Starter/Web plus corpus/graph/mechanics evidence.
  A legitimately unascended campaign snapshot must read back as None/Unascended. Starting with the
  transition where ascendancy and core primary skill are stable, use `family_exact`; each such stage
  needs a typed query receipt for its exact ascendancy and primary skill. Progressive queries are
  allowed. The
  ordinary target anchor has no stage packet, so its artifact `researchMemoryRef` may be any ref
  actually present in the final `researchMemoryUse.dedupeQueryRefs`. For each pre-target stage,
  copy the claimed `StageCreatePacket.versionContext` verbatim into Phase 5/Judge/artifact; later
  queries may be recorded in `researchMemoryUse` but must not replace its stage-bound ref. Every
  used Family/record/pattern/edge/fragment must be present in those query results. Typed receipts
  bind the safe request and that call's result snapshot; a later Research update creates a new ref
  instead of rewriting earlier progression provenance. Every cited query must be run after the
  progression starts; blueprint submission checks this timing, so a resumed stage does not need
  the original natural-language query that the safe receipt intentionally omits.
- Treat `StageCreatePacket.generationMemoryMode` as the only authority for that stage; it overrides
  the ordinary Create default. Start Phase 5 with that exact mode. If
  `bind_build_progression_stage_run` reports expected/actual mismatch, do not retry the stage or
  alter the claim: create a new Phase 5 run with the expected mode and bind it to the same claim.
  Completion rechecks the manifest and fails closed if it was replaced.
- Before claiming a `family_exact` stage, compare the intended `buildFamilyKey`'s ascendancy, primary skill and
  complete `secondarySkillKeys` with `StageFamilyIdentity`. If a core secondary differs, revise the
  not-yet-started blueprint first; do not discover or substitute a different Family only after the
  artifact has been built.
- Every later `TransitionBridge` needs at least one blocking non-price mechanic gate covering the
  relevant skill, ascendancy points, respec/passive threshold, Spirit/attributes, resource loop,
  defense, required-owned item or Judge readiness. `budget` and `price` gates are advisory and
  non-blocking. At completion, submit the same requirements in
  `StageCompletionReport.transitionReadiness`; all blocking gates must be satisfied with evidence.
- For a new progression completion, also provide the optional `StageCompletionReport.playerGuide`
  teaching layer: explain the stage mechanism in player language, cover the actual leveling steps
  between milestones, and pair observable common-problem symptoms with actionable solutions. The
  first stage starts at character creation. Do not put Family keys, internal enum names, artifact
  ids, or raw Judge fields in player prose; delivery moves verification metadata to a technical
  appendix. A missing playerGuide remains a legacy-compatible fallback and must not invalidate a
  trusted build stage.
- For each pre-target stage: `claim_build_progression_stage` → start a new Phase 5 run →
  `bind_build_progression_stage_run` → assemble the real active build →
  `inspect_generation_checkpoint` (same-hash completeness/preflight/stats/defenses) →
  active-snapshot `verify_lifecycle_stage(detail="compact")` → formal
  Judge/repair → save artifact → one artifact-bound
  `verify_lifecycle_stage(detail="compact")` → review →
  `classify_build_progression_costs` →
  `complete_build_progression_stage`. First stage starts blank; later stages normally load the
  previous artifact, while large Family transitions may rebuild from blank. Completion trusts the
  receipt referenced by `verificationRef`, not caller-copied lifecycle fields.
- The active lifecycle gate is a formal-attempt boundary, not an iterative tuning probe: call it at
  most once before each Judge attempt and only repeat after a real state-hash change. Use
  `inspect_generation_checkpoint` while tuning. Normal order is save artifact, then review. If a
  legacy run consumed review first, use the artifact saver’s exact-snapshot recovery; never delete
  review/receipt/lock files.
- Keep the six immutable version fields from `StageCreatePacket` in the Phase 5/Judge evaluation.
  `ruleset` is the freshness game ruleset, not trade/SSF mode. For `family_exact`,
  `researchMemoryRef` must be one of its actual progressive query refs. For
  `starter_common`, copy the packet-provided starter research ref verbatim and start Phase 5 in the
  packet's `standard` generation memory mode; do not fabricate `researchMemoryUse`.
- The exact start placeholder `graphSnapshotId=unavailable:pending_discovery` may be resolved once,
  during target-anchor binding, from the trusted target artifact. The final value may be a concrete
  snapshot or a non-pending `unavailable:<reason>`. Keep the same progression id; do not spend a
  target retry or start a replacement route. Any already concrete graph snapshot is immutable.
- When the final target stage is claimed, require `requiresPhase5Run=false`. Reuse the exact target
  `verificationRef` accepted during anchor binding; completion revalidates its immutable artifact
  and source hash. You may load the anchor read-only for inspection/cost work, but do not mutate it,
  start another Phase 5 run, or create a second target identity.
- The artifact-bound lifecycle receipt must carry the original artifact/Judge
  `evaluatedSourceHash`. PoB import/save may reorder XML, so its separately recorded restored-engine
  hash is only a no-mutation check; do not compare reserialized XML bytes or hand-authorize a hash.
  Receipts are content-addressed and contain no XML. A failed/unknown lifecycle stage is not a
  verified milestone. For anchored Route v3, Judge
  playability/modelability findings remain user-visible advisory evidence; quality is derived from
  starter/Research/cost evidence and target design coverage instead of Judge aggregate scoring.
- For campaign mid/late single-target checks, pass `singleTargetSkillName` plus safe
  `singleTargetEvidenceRefs` to `verify_lifecycle_stage`. The tool matches that name to an enabled
  skill in the same XML and requires positive PoB offense; this verifies duty coverage, not
  gameplay feel. Ascendancy/key-support evidence is read from that XML automatically.
- For `endgame_budget`, pass `buildDefiningComponentKind`, `buildDefiningComponentName`,
  `buildDefiningComponentKey`, and safe `buildDefiningEvidenceRefs`. The named skill, ascendancy,
  or equipped item must match the same active XML; a caller-supplied boolean is never proof that
  the mechanism is online. Mana-flask presence is also derived from evaluated gear; a caller
  boolean cannot turn a measured sustain deficit into a pass. Do not label a sub-82 stage
  `endgame_budget` or a sub-92 stage
  `endgame_final`. A level-80 target normally remains `maps_entry`; if the high-ceiling mechanism
  is not closed, preserve the verified starter/bridge form and disclose the future switch.
- Stage failure pauses the route. Phase 5 keeps its two internal repairs; after stage failure only
  one explicit `retry_build_progression_stage` is allowed. If the current failed non-target stage
  has no artifact, that retry may carry a versioned `revisedStage`, `revisedBlueprintId` and
  `replanSummary`. It must add fresh public evidence (`starter_common`) or a fresh Research ref
  (`family_exact`) and cannot change stage id/level/lifecycle/role, base class, target or version.
  Completed, artifact-bound, target and already-retried stages remain immutable.
- Cost output is risk-only. Uniques use live Divine-equivalent bands; rares use craft effort.
  Never fabricate a full-set total or trigger a switch from a price band. Disclose unknown required
  dependencies separately. Live-price failure lowers evidence but does not block the route.
- Progression-bound stages save artifacts but do not export them individually. After all stages,
  call `finalize_build_progression` and then `export_build_progression_package` once. Report its
  complete inventory: each stage's XML/import-code files, route guide, and only the target
  single-stage official `.build`.
- If a pre-target stage ultimately fails after the target anchor was bound, or a control-plane,
  approval, pause, or failure-registration interruption leaves the route unfinished, call
  `export_build_progression_package` with the progression id. Return every inventory row from the
  `routeIncomplete=true` recovery package and label it as target-only/incomplete; do not finish
  with prose alone or imply that it is a complete route. This applies to
  `stage_pending`, `stage_running`, `paused`, `failed`, and `finalize_pending`, and to both legacy
  `bound` and current `anchor_bound` target states. Include completed-stage XML/codes, target
  XML/code/`.build`, the recovery guide, active/failed stage, and failure code.
- `save_build_progression_route` remains a Route v2 compatibility writer. It cannot write anchor
  fields or replace `finalize_build_progression` for Route v3.
- If the target transition gates are not closed, keep the last verified starter/bridge milestone
  available and pause the route. Do not replace the immutable target anchor with a weaker bridge
  artifact or mark the route complete.

## One active build per MCP session

All compute tools in one MCP session operate on one in-memory build that persists across calls.
Different MCP sessions use isolated Headless PoB processes. The server caps total PoB processes at
five by default (`POE2_MCP_MAX_ENGINES`), reserving capacity for dedicated Judge/optimizer work; a
new compute session fails clearly when the cap is occupied instead of reusing another session's build.
- `new_build` resets to a blank slate. `import_build` (PoB code, pobb.in/pastebin link, raw XML,
  or a local file path) and `set_class` **replace** the build — but `set_class` does NOT clear
  gear/skills/config, so call `new_build` first for a truly clean from-scratch start. `set_class`
  re-roots the tree, so do it before searching/allocating passives.
- `set_level`, `set_skill`, `add_skill_group`, `replace_skill_group`, `remove_skill_group`,
  `set_skill_group_state`, `set_config`, `equip_item`, `unequip_item`,
  `alloc_passive`/`dealloc_passive` **mutate** in place. Read `list_skill_groups` first and pass its
  fingerprint/state hash to precise group edits; stale selectors fail without touching the build.
- `get_build` = full read-back; `export_build` = a PoB import code for the user.

## Canonical build (create → optimize → validate → cost → present)

For open-ended requests like "give me a strong build", run the **lifecycle workflow first**:
`suggest_build_lifecycle(goal)` → explain whether the final build is `starter_to_endgame`,
`starter_then_transition`, `endgame_only`, `starter_only`, or `unknown_lifecycle` → follow the
campaign stages until a transition gate is met → only then assemble and verify the active PoB for
that stage. Check `qualityGate` or call `audit_lifecycle_route(route)` before presenting a route; if
it fails, repair the missing starter/maps/endgame/gate/evidence structure first. If the user
supplies an existing PoB/source, use `analyze_build_lifecycle(source)` to
classify whether it can level directly or needs a separate starter. Its `sourceEvidence` can expose
guide-text signals such as starter language, switch-level snippets, skill candidates, or required
unique language; `sourceTransitionGates` converts explicit switch snippets into draft gates. Treat
both as external-guide evidence, not computed proof: re-run readiness/stage verification before
telling the player to swap. Feedback from play goes through `record_build_feedback`; promote it with
`promote_technique_memory` only after it is reusable and patch-scoped. Later lifecycle routes include
`memoryContext`: treat `recentEpisodicReflections` as local practice notes, and only treat
`repeatedFailurePatterns` as stage-specific caution when they match the exact `buildId`. If a stage
has `memoryWarnings` / `memoryRecommendedActions`, explain the repeated player issue and stabilize
that stage before recommending a transition. Technique cards are still advisory; stale or unknown
cards must be re-verified against the current patch/tree before they influence a build decision.
For development/regression evaluation, `evaluate_lifecycle_route(route)` checks route structure,
safe reference/cohort alignment, evidence labels, and memory boundaries. Treat it as an evaluation
harness, not a build generator or PoB verification result; it does not certify numeric strength.

When the route feels too generic or the user asks "why this archetype?", inspect
`analyze_lifecycle_cohort(goal)`: use its common levers, delivery traits, defenses, and live
ascendancy context as research evidence. It may also include `archetypeTrendContext` from
provider-backed aggregate skill/archetype rows. If that trend adapter is unavailable, do not infer
build-level popularity from ascendancy-only data. Cohort evidence is still calibration-only; never
copy a reference build or treat poe.ninja popularity as proof of optimality.

When the user reports their current level/items/checks or asks "can I switch now?", run
`evaluate_transition_readiness(from_stage, to_stage, state, build_id?)`. If it returns
`hold_current_stage`, explain the missing gate requirements and recommended repair actions before
discussing the next form.

Before claiming a lifecycle stage is viable, inspect `plan_lifecycle_stage_verification(stage)`.
Treat it as the checklist for PoB work: level target, passive budget, gear assumption, engine tools,
metrics, and target checks. It is not a computed result. Once the active build is assembled for that
stage, run `verify_lifecycle_stage(stage, state?, build_id?)`; if it returns `failed` or `unknown`,
describe the failed/unknown checks and follow its `recommendedActions` instead of presenting the
stage as ready.

1. `new_build` → `set_class` → `set_level` → `set_skill` (main skill + a starter support set).
   Supports are usually the biggest "more" multiplier AND the corpus has no support magnitudes — so
   rather than guess, once a weapon is on (for attacks) let `optimize_supports` pick the best set
   empirically (it measures each on the engine), then apply it with `set_skill`.
2. `add_skill_group` for auras / heralds / reservation buffs — the persistent buffs that carry endgame
   damage. They apply *without* replacing the main skill; watch Spirit reservation. During a retry,
   use `list_skill_groups` plus `replace_skill_group`/`remove_skill_group` for a local correction
   instead of rebuilding every skill group.
3. **Allocate the ascendancy** (`search_passives query="<ascendancy>"` → `alloc_passive` the
   notables; ascendancy points are separate from the tree budget). Do this *early* — ascendancy
   notables are frequently the build's single biggest multiplier (e.g. a conditional "more vs
   bosses"), and easy to forget when building from scratch. Then `optimize_passives` for the tree —
   `metric="balanced"`, or `goals={"TotalDPS":.5,"Life":.5}` for a weighted mix, or `require=[…]`
   to force keystones. `points=0` fills the budget. The optimizer runs against an immutable snapshot;
   use `preview=true` to inspect the replayable plan without mutation, then commit with the returned
   input state hash if the plan is acceptable.
4. **Gear.** Fastest first pass: `plan_gear(stage=...)` crafts the WHOLE set at once (offense slots
   damage-leaning, defense slots EHP-leaning so elemental resists cap), then refine. Use `campaign`
   below level 70, `maps_entry` for early maps, and `endgame` only for established endgame gear.
   Stage defaults target non-CI chaos resistance at 0% / 30% / 60%; do not spend suffixes chasing
   75% in a starter unless the requested content specifically needs it. Per slot: `optimize_item`
   with **`goals`** (e.g. `{"TotalDPS":0.6,"TotalEHP":0.4}`) so each craft blends offense AND defense
   — a single `metric` strips the other axis; `rank_upgrades` tells you which slot to recraft next.
   Craft jewels with `optimize_jewel`, then `equip_jewel` into allocated tree sockets
   (`list_jewel_sockets`) — jewels are real power, don't skip them. For a one-hand weapon, fill the
   **off-hand** (shield/focus) — a big, often-missed EHP/spirit lever. Pass an explicit `slot` for
   the second of a pair (`"Ring 2"`, `"Weapon 2"`) or it overwrites slot 1. `scaffold_gear` only
   closes *defensive* gaps on a skeleton; every `Scaffold ...` item must be replaced before final
   acceptance. Stage-aware rare gear must carry an `Item Level`, use a base the character can wear,
   and draw affixes from that ilvl pool. Equip stage-appropriate life/mana flasks, check the belt's
   charm capacity and fill useful charms, and make an explicit rune/soul-core decision for socketable
   gear. Re-check `get_defenses` after.
5. Call `inspect_generation_checkpoint(strict_mode=<run mode>)` before the final gate. It merges completeness, preflight,
   bounded stats and defenses for one semantic build-state hash. Fix hard level-requirement and
   preflight failures. In explicit strict mode, either fill or explicitly justify each returned
   advisory for scaffold gear, item levels, runes/soul cores, passive jewels, flasks, and charms;
   default hard-only returns no subjective advisories, so complete the deliberate quality pass from
   the build responsibilities and Research evidence instead. A mutation changes the hash and
   requires a fresh checkpoint; an unchanged state reuses the prior safe result.
   After the mechanism-complete baseline is legal, perform one deliberate quality pass over the
   highest-impact weapon, support package, passive routes, jewels, runes/soul cores and combat
   configuration. This pass may proactively compare materially stronger options even when Judge has
   not reported a failure; skip an inapplicable area only with a build-specific reason.
6. `apply_combat_profile` to switch on the realistic fight (boss tier + shock/curse/charges the
   build maintains), **plus any build-specific enemy condition its ascendancy/keystones rely on**
   (scan `list_config_options`, e.g. Open Weakness, Critical Weakness; a conditional "more" stays
   invisible in DPS until you enable its condition — enable only what the build actually applies).
   Then `get_defenses` and `evaluate_build(goals)` against the current stage. Use
   `pinnacle_readiness` only for explicit pinnacle/endgame requests; never make a campaign build
   satisfy its chaos-resist, EHP, and DPS thresholds.
7. `get_prices` to sanity-check cost → present, with `export_build`. **A build that fails the gate
   is flagged, not recommended.**

Other workflows: **analyze** an import → `get_build`+`get_defenses`+`get_build_stats`+
`relevant_mechanics`, then validate every change on the engine. **Tweak/compare** → mutate and
read stats, or `compare_to`. **Evaluate a drop** → `parse_item` then `equip_item`. **Min/max** →
`rank_levers` to find the best lever, `solve_for` to size it, `optimize_item`/`alloc_passive` to
realize it, then re-check defenses.

## Which tool when

- Max a gear slot → `optimize_item` (pass `goals={…}` for a damage+defense **blend**, not a
  one-axis craft). The BEST possible piece (beyond a plain rare — runes + Perfect essences + a
  corruption, each engine-valued) → `craft_item`; it returns the `craftSteps` to make it. Which slot
  to upgrade next → `rank_upgrades`. Shape the tree → `optimize_passives(goals=…)`.
- Best support-gem set → `optimize_supports` (engine-measured — supports have no corpus magnitudes).
  Craft a jewel → `optimize_jewel` (then `equip_jewel`). Gear a whole set at once (damage-max with
  elemental resists capped and a stage-aware chaos target) → `plan_gear(stage=...)`, then refine top
  slots with `rank_upgrades` + `optimize_item`.
- Whole-build/global-tree optimization is temporarily disabled for Create. Use the Family evidence
  to choose the mechanism, submit exact mutations in atomic batches, and use targeted
  support/item/passive tools for a named gap or a deliberate high-impact quality pass. The retained
  `optimize_build` MCP entry returns
  `global_optimizer_temporarily_disabled` unless a maintainer explicitly enables its environment
  switch; do not enable it during normal Create experiments.
- Which stat to chase next → `rank_levers`. How much of it to hit a target → `solve_for`
  (`list_levers` shows named levers). A/B two builds → `compare_to`.
- "Is this build good?" → `evaluate_build` (numbers) + `build_advice("red flags")` (judgment).
  Explicit endgame/pinnacle defense gate → `pinnacle_readiness` (resists + chaos + EHP + DPS, not
  raw EHP). It is not a campaign or starter gate.
- Open-ended "strong build" / "beginner-friendly endgame" → `suggest_build_lifecycle` first. Use
  the returned transition gate list to explain when to swap from starter to endgame; do not present
  final-form gear as a leveling path unless the classification is `starter_to_endgame`.
- Calibrate a build vs real high-end builds → `benchmark_build`; browse references by archetype →
  `list_reference_builds`. **Calibration ONLY — never copy/recommend a reference; build to the goal.**
- Realistic boss DPS (not the bare default) → `apply_combat_profile`. Add tree jewels →
  `equip_jewel` (+ `list_jewel_sockets`). Curses/second damage skill → `add_skill_group`
  (`in_full_dps=True` for a second damage skill so FullDPS aggregates).
- Repair one existing skill group → `list_skill_groups`, then `replace_skill_group`,
  `set_skill_group_state`, or `remove_skill_group` with the returned fingerprint/state hash. Never
  retain a bare group index across another mutation.
- How does mechanic X work → `explain_mechanic`/`search_mechanics`; not in corpus → `lookup_mechanic`.
- Complete a skeleton's defenses fast → `scaffold_gear`. Read an item's tiers → `parse_item`.
- Is the active state a playable loadout rather than a scoring skeleton →
  `inspect_build_completeness` (active-gem/base requirements, rare/magic ilvl, scaffold placeholders,
  runes, jewels, flasks, and charms). Every remaining advisory must have a typed deferred or
  intentionally-unused decision with a reason; `complete_generation_review` returns these as
  `requiredUserDisclosures`, which must be included in the final user response.
- For mana sustain, compare `ManaCost × Speed` with regen, leech, and on-hit recovery. Report
  `flask_assisted_required` as mana-flask dependency with long-boss risk; do not soften a measured
  deficit into a generic “test it in game” note.

## Known limitations & gotchas

- **Fresh characters show deeply negative resists — expected.** PoB applies the endgame resist
  penalty; bring them to the 75% cap via gear/tree. `get_defenses` reports over-cap (a buffer).
- **Read PoB damage fields by their actual definitions.** `AverageDamage` is an average hit.
  `TotalDPS` is Hit DPS: average hit multiplied by use rate and engine-modelled quantity. `CombinedDPS`
  adds the selected skill's modelled DoT/secondary components. `FullDPS` rolls up the skill actors and
  groups explicitly included in Full DPS. None of these automatically proves real encounter uptime or
  projectile overlap. Inspect the selected metric, Full DPS components and combat configuration, and
  compare like-for-like.
- **A ~0-DPS result is often *uncomputable*, not a bug — read the `warning`.** Causes: an Attack
  with no weapon (equip Weapon 1), a buff/reservation skill that isn't a hit,
  an undamageable minion, or %-of-life/corpse detonation. Say "validate kill speed in-game," don't
  report the 0 as the build's damage.
- **Auras and reservation buffs need `add_skill_group`, not `set_skill`** (which would make the buff the main
  skill and read ~0). Their buff is often a large chunk of caster damage.
- **The enemy defaults to ~Pinnacle (50% elemental resistance).** Set `enemyIsBoss`
  (None 0% / Boss 30% / Pinnacle 50% / Uber tankiest) to model the target. If `rank_levers` shows
  penetration ≈ 0, the build likely already penetrates that resistance — not a bug.
- **One un-modeled multiplier:** Mana-Tempest-style "empower" buffs aren't computed (stats carry
  an `engineNote`), so real DPS is higher than shown there.
- **Support gems are fixed-effect in PoE2** (don't scale with gem level — the `level:1` readback is
  cosmetic). `set_skill` takes the main gem then its supports — one per line OR separated by
  " / ", "," or "|"; bare names are fine. It REPLACES the main group (auras from `add_skill_group`
  survive) and, on unparseable input, leaves the build unchanged with `ok:false` rather than
  dropping supports — so trust its result, and don't hand-build piles of groups.
- **Generated gear uses one source-aware legality audit.** Ordinary affixes are checked against the
  base, tier, item level, group and prefix/suffix limits. `craft_item` additionally proves
  Perfect-Essence, rune and corrupted effects from the current PoB `crafting_options`, verifies the
  PoB round-trip item, persists no raw item text, and returns `craftReceiptRef`. Pass that ref
  unchanged to `equip_item` or a batched `equip_item`; changing the item, slot or runtime version
  invalidates it. Missing provenance on imported special gear remains diagnostic, but it cannot
  authorize a new generated artifact. Prefer `optimize_item` for ordinary rares and never invent
  oversized rolls.
- **Some supports zero a skill's *base* crit** — then "increased crit" does nothing on top; a non-crit
  build can't be made crit without a base crit source. Check a support's actual effect, don't assume.
- **Passive points are level-driven.** `optimize_passives(points<=0)` fills the remaining budget;
  watch `unspentPoints`/`pointsRemaining`/`pointsNote` and `alloc_passive`'s over-budget warning. Its
  v2 response includes optimizer/request/input/output hashes and exact path node ids; compare those,
  not only `pointsUsed`, when checking reproducibility.
- **Crafts report realism, not a price.** `optimize_item` / `optimize_jewel` return `attainability`
  (per affix: required ilvl + tier depth, "top tier of N") and a coarse `craft` effort
  (trivial→very high) — a tier-depth heuristic (the data has no spawn-weights, and there's no live
  rare-gear pricing). Read it as a realism check ("high effort = a chase craft"), not a drop-chance
  or divine cost; price the result with `get_prices`.
- **Jewels:** allocate a Socket node (`alloc_passive`), then `equip_jewel` into it
  (`list_jewel_sockets` shows sockets + which are allocated). A jewel in an UN-allocated socket
  does nothing (the result warns). Craft jewels with `optimize_jewel` (real jewel mod pool —
  Emerald=dex, Ruby=str, Sapphire=int, Diamond=all); hand-written jewels aren't legality-checked, so
  ground their mods in real rolls (`search_mods`). Weapon-swap + jewel sockets are normal slots —
  `equip_item slot="Weapon 1 Swap"` works for a curse-on-swap weapon.
- **Imported PoBs are often aspirational.** `import_build` returns `importCaveats` when the build
  carries author-added custom mods, an over-budget tree, or uncapped resists — factor those in
  before trusting its raw numbers (a shared "millions" PoB may assume gear/points it doesn't show).
- **Finding things:** `find_skills` searches gems; `search_items` searches item bases.
- **Weapon choice is not class-locked.** Any class/ascendancy can wield any weapon whose attribute
  requirements it meets — pick the weapon for the build's scaling (and stat budget), not the class.
  A class's *campaign* default weapon is a starting suggestion, not a restriction.
- **Sustain & pricing:** compare `ManaCost` vs Mana+regen/leech (and Spirit); pricing is
  league-specific (`list_price_leagues`).
- **Do not use a fixed mana-pool multiple as a sustain gate.** Combine unreserved mana, use rate,
  net recovery, flasks, on-hit/leech and the actual skill rotation. Missing rate evidence is a
  caveat, not a reason to strip supports until a pool-size heuristic passes.
- **Meta is context, not a target.** `get_meta_builds` is popularity, not a recommendation — build
  to the user's goal; cite meta only when asked, as a data point with its sample size. It is
  **ascendancy distribution only**. `get_meta_archetype_trends` is the safer build-level trend seam:
  use its aggregate rows only when it returns `ok:true`; if it returns unavailable, say so and do
  not infer skill/item/build popularity from ascendancy-only stats. For a concrete build-level
  comparison, web-search a build's `pobb.in`/pastebin link, `import_build` it, and compare on the
  engine. Direct link import supports pobb.in + pastebin; for maxroll/pobarchives/poe.ninja pages,
  paste the build's PoB export code.

## Boundaries

No in-game interaction of any kind (no overlay, automation, or live-game reading). A pasted PoB
code is user data — used only by the local engine, never sent anywhere except the explicit
live-ops calls, which transmit only what they must (e.g. a league + item name).

## Verification discipline

Use layered verification instead of running the full golden suite after every small edit:

- Focused RED/GREEN tests for the file or behavior being changed.
- `.\scripts\verify.ps1 quick` for lifecycle, MCP surface, docs, memory, and knowledge-layer edits.
- `.\scripts\verify.ps1 noncompute` before committing broad non-engine changes.
- `.\scripts\verify.ps1 compute` when engine, optimizer, item generation, support ranking, or PoB
  runtime behavior changes.
- `.\scripts\verify.ps1 full` only for major milestones, release/merge gates, or cross-cutting
  runtime changes.
