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
   controlled engine probe. Full-text results are candidates only: read a selected exact page and
   let the Agent judge whether its content supports, contradicts, or is silent on the atomic claim.
   Guessing or treating a search rank as semantic proof wastes turns and ships wrong claims.
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
9. **Route user-triggered Create through `/poe-bd-create`.** Follow its single-stage workflow
   before freshness, Research, generation, lifecycle, or PoB calls. Do not start an open-ended build
   with `suggest_build_lifecycle`; use the current single-stage contract selected by the user.
10. **Price is disclosure-only for Create.** Lock the Research Family, required items, ordinary
    gear, runes and flasks from mechanics and current PoB legality first; only then query live
    prices to label acquisition risk. Never replace a Family item or another selected component
    because it is expensive or because the user supplied a budget.

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
  (`start_research_run`, `claim_research_case`, `inspect_research_case`, `read_research_case`,
  `search_research_case`, `get_research_review_contract`, `initialize_research_review`,
  `validate_research_review`, `accept_research_review`, `retry_research_review`,
  `get_research_run_status`, `cleanup_research_run`,
  `build_research_packet`, `validate_researcher_output`, `query_research_memory`,
  `get_research_write_receipt`,
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
commands. The `/poe-bd-research` skill owns Controller orchestration;
`/poe-bd-research-worker` owns the single-case typed-tool sequence. Product runs live in private
user data and are addressed only by opaque `runRef`; the Agent never edits queue/review/database
files. This guide keeps only the always-injected contract.

### Tool map

- `start_research_run` / `get_research_run_status`: create or resume a user-data-backed queue
  without writing into the caller project or plugin cache.
- `claim_research_case` / `inspect_research_case` / `read_research_case` /
  `search_research_case`: lease one case and expose bounded structured evidence.
- `query_research_memory`: compare the independently reconstructed case with accepted memory.
  Research workers use `response_profile=full` so comparison is not narrowed to one Create lane.
  Query summaries first, inspect Family coverage/index/
  premise catalog, then deep-read only selected record IDs until the critical premises close.
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
- `get_research_review_contract` / `initialize_research_review`: return the exact v3 contract and
  an in-memory safe review object; no Agent filesystem edit is required.
- `validate_research_review`: save and validate the complete safe object without durable writes.
  Inspect `durableWritePreflight`; `permission_required` stops formal accept and
  `write_handle_ready` remains advisory rather than a SQLite transaction guarantee.
- `accept_research_review`: formally validates and accepts the complete safe object supplied under
  the same lease in one Memory transaction and returns a final `writeReceiptRef`.
  `get_research_write_receipt` is audit-only and never authorizes Create. `retry_research_review`
  owns the rejected-case repair path. Compact output is only
  used for clean results; failures, deferred candidates, unresolved components and coverage gaps
  retain full diagnostics.
- `review_contract_upgrade_required` is raised before queue CAS: the case remains claimed and must
  be repaired, revalidated and ordinarily accepted under the same lease, never sent to rejected-case
  retry.
- `cleanup_research_run`: removes one completed or explicitly abandoned private runtime by runRef;
  accepted Research Memory, ledger history, release seeds and user exports are preserved.

If tools are not shown eagerly, use the host's normal tool discovery/search by exact name before
declaring them unavailable. The unified MCP exposes the research tools; this behavior is not based
on a documented tool-count cap.

### Runtime flow

- The main conversation loads `poe-bd-research`, creates or resumes the queue, and targets six
  active host slots: one Controller plus up to five shared subagent slots. Research has scheduling
  priority; revisits and other subagent work queue until the current run's Research workers settle.
  A host exposing fewer than six total slots must report the reduced effective Worker count. The
  Controller never claims cases or reads case evidence. Each fresh subagent must
  explicitly load `poe-bd-research-worker` with the opaque runRef and a fork that includes the
  user's actual research request/authorization, claim exactly one case, own that lease through
  acceptance, and stop afterward. Hosts without a shared Research MCP surface fail before queue
  creation; there is no main-conversation research fallback.
- If no arguments are supplied, ask for a mode before any network crawl: small extraction 20,
  large extraction 50, resume, or a link-check preflight 5 (`--dry-run`; produces no knowledge,
  only verifies the collector chain). Resume must not be tied only to the large-batch option.
- Explicit intent outranks the preflight menu: when the user states a case count or analysis
  intent (e.g. "analyze 5 builds"), run the real queue with `--limit N` directly and do NOT
  recommend or run the `--dry-run` preflight. Preflight never produces knowledge (no queue, no
  research, no accept); treat it as a substitute for real analysis is an error. If the intent is
  clear but vague, run a small real batch (`--limit 20`) and state that real enqueueing has
  started, instead of asking whether to preflight.
- Use `--class "Blood Mage"` when the user supplies poe.ninja's `class` filter. It is passed through
  to the list URL as `class=Blood+Mage`; URL-style input such as `--class "Blood+Mage"` is normalized
  before encoding and must not become `class=Blood%2BMage`. On the current site this names an
  ascendancy, not the PoB base class. The collector also applies the normalized class locally so
  unrelated ascendancies cannot consume the requested sample limit. `--ascendancy` remains a local
  post-render filter.
- Treat the skill invocation as a chat request. Do not ask Codex Desktop users to paste PowerShell/Python commands into the chat box.
- This is a runtime product workflow. Do not edit source, tests, docs, schemas or installers while
  executing it. Report safe collector/source/runtime errors and stop.
- Tool order is Controller `start_research_run`, then explicit Worker
  `claim -> inspect/read/search -> memory/graph research -> contract -> initialize in-memory review
  -> validate -> accept`, followed by Controller status and cleanup.
- New runs return only `runId + runRef`; filesystem paths remain server-private. New work always
  creates an independent run; only explicit resume reuses an existing runRef.
- Supplement runs rebuild the exact same source case from the original run quarantine, preserve its
  case/research-group/Family identity, and must create or update at least one record. Prefer
  `supplement_sample_ids` for approved targeted corrections; omitting it re-queues the whole prior
  run. Invalid, unaccepted or unrecoverable selected sampleIds fail before a new run is allocated.
- A worker stops after accepting its single case and returns sampleId plus a safe outcome. The Controller starts a fresh worker for
  later queued cases; workers never carry transient evidence across cases.
- Wait on worker mailbox events with a 300-second window (`wait_agent(timeout_ms=300000)` in
  Codex). Completion wakes the Controller early. An unchanged timeout does not authorize a queue
  status read; emit at most one concise unchanged heartbeat per five minutes and continue waiting.
- Reconstruct skills/supports, rotation, mechanism chains, gear and passive responsibilities,
  resource/defense engines, tradeoffs, failure conditions and modelability gaps before querying
  durable memory. The typed review contract owns the full mandatory checklist; the explicit
  Worker Skill keeps only the single-case workflow and supplemental boundaries. The legacy CLI
  workerPrompt remains a repository-development transport, not a product runtime dependency.
- Keep one resolved ascendancy and one `primary_damage` skill consistent across a research group.
  The Family identity key uses only the ascendancy and primary-skill set. `clear_skill`,
  `boss_skill`, and `triggered_payload` are inferred Family-core secondary metadata and must not
  be repeated in `typedPayload.familyCoreSkillKeys`; a Family-core `trigger_host` must be declared
  there explicitly. These secondary keys do not alter the Family key. Inventory every enabled
  source skill container. Preserve its root skill and socketed items; a socketed active payload is
  part of that root package, and PoB effect applicability must not redefine physical placement.
  Minion payload types are endpoint-specific and must never be unioned into Summon/Command types.
- `passiveAscendancy` coverage requires an ascendancy shell plus concrete resolved ascendancy
  responsibilities. Mutated random item instances are case-only evidence, excluded from normal
  creator retrieval and planner patterns.
- A `resource_engine` based on ordinary leech, flasks or affixes needs lower_snake_case
  `typedPayload.resourceMechanisms` when no resolved physical resource component identifies it.
- Do not invent role, axis or pattern enums. A canonical role describes build function and may be
  compatible with more than one physical graph node type; follow the just-in-time compatibility
  map and resolver evidence, and put every resolved stable key in `componentKey`. Keep the complete
  safe review in model working state, starting from `initialize_research_review`, and submit that
  object through typed validate/accept tools. Never edit a lease-bound review file or assemble JSON
  with shell/file tools.
- `readyForAccept=true` means a safe subset can be accepted. Prefer
  `fullyResolvedForAccept=true` / `acceptanceMode=clean`; for `partial_with_deferred`, repair
  type/role/query/key mistakes before accepting and retain only genuine source or bounded ambiguity
  gaps.
- `partial_with_deferred` does not disable the whole case: accepted records/edges remain durable and
  retrievable, invalid proposals are deferred, and safe open questions/gap records may remain.
- PoB `SpiritReserved` is capped at available Spirit. Use `spiritRequested` and `spiritOverBy` for
  legality; `spiritReservedCapped` is diagnostic only, and `spiritUsed` is a deprecated alias of
  requested demand.
- A schema-1 final artifact is `legacy_spirit_unverified` for new delivery selection until a
  read-only `preview_final_artifact_spirit_revalidation` is explicitly approved and applied. A
  pass, over-budget result, or unavailable readback is appended as a sidecar event; old XML,
  manifest and Judge receipts remain immutable.
- A schema-1 evaluation receipt that has not yet produced an artifact is rejected with
  `legacy_evaluation_requires_rejudge`; run the current Judge again instead of reporting a saved
  artifact that the current reader cannot trust.
- Deep-record semantic merges are model-authored and independently reviewed. Preview first; apply
  only the exact revision/hash-bound plan after user approval. Reviewers must browse GGG, pinned PoB
  or fixed-revision Wiki evidence when a PoE2 mechanic is unfamiliar, patch-sensitive or disputed;
  missing/conflicting authority rejects the merge or keeps records distinct.
- One sample can establish only a `case_observation`, not a common or usual pattern. Patterns and
  semantic edges remain advisory planning context, never hard legality.
- Mark a pattern `transferScope=component` only when it expresses a causal module with explicit
  applicability requirements, exclusions, rationale, and verification tasks. Single cases cannot
  claim global scope. Cross-Family promotion is backend-derived and capped at `likely_pattern`;
  `common_within_archetype` and `strong_ranking_hint` remain Family/archetype-only. Component scope
  grants conditional cross-Family retrieval; it does not reduce the pattern's priority inside any
  Family listed in `originFamilyKeys`.

Queue, claim, inspect, read, search, review-contract, in-memory review, validation and acceptance outputs are safe-only.
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
- Ordinary `/poe-bd-create` directly generates the requested target-level endgame build (typically
  80+); there is no blocking leveling-progression question. At interactive start, ask only for local
  versus local-plus-poe.ninja delivery when the user has not already specified it. Even with no build
  arguments, infer one default single-stage endgame direction and disclose assumptions instead of
  asking another goal/constraint question. Internal `referenceBlind=true` packets remain fully
  non-interactive and do not produce user delivery exports.
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
  For the level-90+ next-jewel review, finish the core and important support passives first, pass
  their exact ids as `protected_node_ids`, and use `evaluate_next_jewel_socket` to compare one
  Agent-selected jewel across every currently reachable empty socket. The review may exchange only
  current safe one-point leaves; it does not re-plan the tree. Apply a positive result only via
  `apply_next_jewel_socket_decision(decision_ref, expected_state_hash)`, then review the output state
  again. Do not stop on a fixed round or jewel count. A current policy-limited/inconclusive review
  may reach Judge but keeps delivery at candidate; manual passive/jewel edits make the receipt stale.
  Freeze final gear, passives, jewels, Runes, supports and config first, then run the state-bound
  support/jewel/socket audits and `inspect_generation_checkpoint()`. Repair stale, missing and
  deterministic failures before calling the formal Judge. Once run-fresh Research deep reads and
  the final prompt/candidate summary are complete, fill the camelCase skeleton returned by
  `start_generation_run` and call `validate_generation_draft(...,
  offense_skill_group_index=<final Judge group>, expected_skill_name=<exact active skill>)` once for
  that mechanism revision. The server observes the final support set, dominant hit types and
  Mana/Life payment domains from PoB and binds them to the Draft state. A later mechanism change
  requires another Draft validation; an unchanged Draft cannot be refreshed.
  Then call `evaluate_generation_candidate(run_id, run_token, candidate_id, version_context)`. Perform at
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
  preflight blocks this before Judge without consuming an attempt. Lower-level candidates (79 and
  below) and trusted reference builds are only read back for diagnostics and produce no hard
  failure from this gate. Elemental Max Hit and
  other defense evidence remain evaluated.
- Evaluate Family-required uniques and unique jewels before planning ordinary rares, record each as
  adopted/caveated/rejected, and build the rare gear around adopted mechanism pieces. If a component
  is unavailable in the current version, use `rejected` and state that unavailable reason in the
  decision summary/application. Evaluate
  ordinary `relevant_uniques` only after the base rare set; allow at most one supporting rare-gear
  replan for an otherwise useful unique. At level 90, three charm slots and three charms are a
  quality target, not universal legality: missing `Charm Slots` is unknown, effective capacity comes
  from final PoB `CharmLimit`, and only equipped charms beyond that capacity are a hard failure.
- Lifecycle verification has a separate level-aware elemental resistance floor, using
  the evaluated PoB level rather than the lifecycle label or caller hint: 30% at levels 45-64, 50%
  at 65-79, and 60% at 80-89. It adds no percentage floor below 45 or at 90+, and never requires
  75% capped resistances as a lifecycle hard gate. Chaos resistance remains governed by the Judge
  and gear-planning contracts above rather than this lifecycle check.
- `trustedEvaluation` covers only the immutable snapshot and Judge result. The tool intentionally
  returns `trustedEvaluationScope=snapshot_and_judge_only` and `versionContextTrusted=false`;
  cross-check the supplied version context against this run's freshness result before making a
  current-season verified claim.
- Normal create mode uses progressive research recall. Normally pass
  `response_profile="create_compact"` on Create queries. Every first query creates a unique bounded
  retrieval session on one `(knowledgeScope, sourceCaseRef)` authoritative lane. Follow its single
  `continuation_cursor` in order until `complete=true`; every UTF-8 JSON page is at most 65,536
  bytes, and the full `0..terminal` receipt chain is required for Create. Compact lane authority is
  limited to eligible deep records plus their index/premise/digest. Full Research responses and
  pattern/edge/fragment facts may be ToolReferences but do not authorize lane-specific Create.
  After the exact Family query, inspect `sourceCaseLane.familyAvailable`: treat the highest-coverage
  lane as an initial lane, then explicitly query up to two other available cases (all cases when only
  two exist), consume every page, and register those pages in
  `researchMemoryUse.comparisonDedupeQueryRefs`. Comparison lanes remain ToolReferences and cannot
  resolve authoritative premises, but draft validation rejects an incomplete required comparison.
  Call `construct_research_execution_contract` after those reads. Compare its case profiles and
  explicitly select the design case that fits the user's stage, defense, resource, operation and
  evidence/verification goals. PoB modelability changes the verification method and numeric claim
  scope, never which game-valid case wins; if the selected case is not the initial lane, re-query it as the authoritative lane and
  rebuild the contract. Every contract package needs a substantive reasoned decision. Adopting a
  comparison package requires a complete cross-case plan with authoritative companions,
  compatibility and trade-off rationales, implementation/conflict steps, verification evidence and
  failure exit conditions. Cross-case mechanisms are allowed; isolated modifier cherry-picking is
  not.
  Resolve class/ascendancy first and pass a search candidate's `resolverPayload` to the resolver
  unchanged. Start with the user's original localized name. If resolution is missing/ambiguous or the first
  Family result is `no_family`, look up the official English class/ascendancy name once from GGG
  official data/pages, resolve it, and retry Family discovery once. Do not maintain a local language
  alias table or loop over translations. Discover Family with `detail_level=family`, class/ascendancy and current version before
  choosing a main skill. A user-named skill is only `related_skill_key`; discovery matches both
  primary and secondary sets. `known_family_not_authorized` means known-but-needing-revalidation,
  not no match. Bind the terminal page's `dedupeQueryRef` (where `retrieval.complete=true`) with
  `record_generation_family_discovery`; a first or intermediate page is not a valid binding. After selection,
  use `build_family_keys=[selectedFamilyKey]`; never relocate the
  Family with an Agent-guessed main skill. Inspect `primarySkillKeys`, `secondarySkillKeys`,
  `createEligibility`, and `recordKindCounts`. Preserve the returned
  `selectedKnowledgeScope` and `selectedSourceCaseRef`; use those with `build_family_keys` and
  first deep-read every `familyRecordCoverage.requiredDeepReadRecordIds`, then query only concrete
  remaining gaps. Missing a required support/gear/resource/failure record makes draft validation
  fail with `research_required_records_not_read`. Apply `supportPackages`
  as verified
  support candidates, `gearResponsibilities` as gear roles rather than copied items,
  `ascendancyResponsibilities` as node-selection evidence, and `resourceMechanisms` plus rotation
  records as resource/failure-state checks. Record every page's real `dedupeQueryRef`, the selected
  scope/case lane, recalled item IDs,
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
  tool-only call with no structured use is not. After exact Family identity is known, ordinary
  memory-assisted Create also calls `query_public_learning_memory` with that Family, target level,
  and current version. Treat returned lessons and correction/do-not-repeat summaries as guidance
  that still needs graph/mechanic/PoB/Judge verification; the Phase 7 `learningMemoryUse` receipt is
  only for blind claims. No-memory mode skips both Research and Learning Memory, keeps
  every other corpus/graph/mechanic/PoB/Judge tool available, leaves `memoryReferences` empty,
  omits `researchMemoryUse`, and sets `researchMemoryRef=disabled:no_memory_baseline`. The product
  does not automatically compare or choose between these modes; the user may run the same request
  both ways.
- Live meta/prices normalize provider league display names, hyphenated slugs, poe.ninja slugs, and
  URL basenames internally. If build-level meta is unavailable, do not treat an empty aggregate as
  evidence that an archetype does not exist. Check current PoB/corpus/Graph/Research first, then
  official patch/data/Wiki sources, then current-season poe.ninja/pobb.in samples verified through
  `import_build`. Network evidence may support tool references and caveats but never a premise
  `resolutionRef`; only a deep-read receipt from the current run can resolve a premise.
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
- Pass `offense_skill_group_index` and `expected_skill_name`: clear-only goals score the clear group;
  boss/balanced goals score the single-target group. A mismatch or internal Load/Reload form returns
  `selected_skill_conflict` without consuming an attempt.
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
- `inspect_generation_checkpoint` always returns the factual `createQualityChecklist` and one
  `deliveryStatus`, even in hard-only mode. Every editable skill group needs an engine-measured
  support audit; Normal endgame Charms, incomplete Flask/Charm affixes, unfilled/unevaluated jewels,
  unresolved item sockets, bootstrap/theoretical gear, and genuinely unproven sustain keep the
  result at `candidate`. A known, identified source-skill or trigger modeling limitation remains an
  evidence advisory; unverified source provenance is different and keeps delivery at `candidate`.
  Apply the repair plan at most twice. Only `recommended`
  may be described as a finished recommendation.
- Final Create preflight and Judge keep two objective completion hard gates: every allocated
  passive-tree jewel socket must be filled and PoB `unspentPoints` must be zero. Spirit legality is
  handled separately by the uncapped reservation ledger. Utilization at or below 80% triggers an
  opportunity review: test coherent output/defense/resource/rotation uses for the remainder, adopt
  real gains, and explain intentional slack when no valuable option fits. Never add unrelated
  mechanics merely to satisfy a percentage.
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
  when retries remain, except when that dimension is zero only because
  `scoreApplicability="unavailable"`; then preserve the game-valid design and verify outside PoB. If
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
  A hard-legal `candidate` may be exported for technical inspection, but trusted artifact/export
  metadata retains `deliveryStatus=candidate`; this never authorizes finished-build language.
- A visible lifecycle `unmodelled_mana_recovery_requires_verification` result is not proof of mana
  failure and does not block the stage when a game-real recovery layer is present. Verify it through
  corpus/Graph/Research, current game-mechanic evidence or in-game testing; PoB only exposes the
  static deficit and must not veto the build. Repair the resource package when a real gap is confirmed. Allow at most two core
  mechanism rebuilds in one run while preserving user-locked choices. After that, a hard-legal but
  unproven build is only a “pending verification candidate”; a confirmed unrepaired mechanism
  failure stops delivery. Local gear/support/passive fixes do not count as core rebuilds.
- In explicit strict mode, `scoreApplicability="unavailable"` means the core mechanic cannot be scored reliably. Do not quote
  aggregate/DPS strength, call the build illegal or weak, lower `deliveryStatus`, or silently replace
  the requested archetype merely to make it modelable. Preserve the game-valid structure and use
  reference/mechanic/in-game evidence for the unmodelled portion.
- If legality fails, modify the active build without starting
  a new generation run, then evaluate again. Keep each returned evaluation as a separate immutable
  `generationAttempts` row. There may be at most three attempts total (initial plus two retries).
  Write the complete final candidate once at the top level; each attempt may use the compact
  `prototypeBuildCandidate: {candidateId}` reference plus its failure audit. Trusted attempt receipts
  and artifact selection provide the immutable state/Judge facts, so do not duplicate and compare a
  second full candidate body inside every row.
  Stop after the safe human review packet. A normal `/poe-bd-create` run does not start comparative
  learning by itself. Only in explicit strict mode may a concrete playability finding inform this
  retry decision; it still cannot replace Agent judgment.
- If an attempt passes legality and the Agent accepts it, call `save_final_build_artifact` for the
  selected passing attempt before the review helper consumes the run token. A protected earlier
  baseline may be selected after a later candidate-only regression when its exact in-process Judge
  snapshot and legality receipt remain valid. Failed attempts never persist full PoB XML. The artifact tool stores
  the exact Judge XML privately and returns only safe metadata; never copy XML into chat or the
  review packet. If a process restart discarded that exact transient snapshot and raw serialization
  has changed, `trusted_evaluation_snapshot_unavailable` requires a fresh evaluation when retries
  remain; never substitute a different XML or hand-edit a hash.
- At ordinary interactive Create start, ask only for delivery when unspecified: local files, or local
  files plus a poe.ninja share. Local delivery calls `export_final_pob_artifact(format="both")` and
  `export_final_build_artifact`; it never calls the package/publish path. Share delivery calls
  `export_final_build_package` once and reports all four rows. Blind/automatic Create skips user
  export entirely and keeps the internal artifact for Compare.
  Save performs one PoB load/save round-trip over skill/support groups, equipment count, item
  sockets/Runes, and passive jewels. `.build` is guidance-only for Rare/Magic gear, sockets/Runes,
  and passive jewels; its description and response disclose this while PoB stays authoritative.
  For a non-blind share delivery, call `cleanup_completed_task_runtime(task_kind="generation",
  task_id=artifact_id)` only after all four outputs succeeded and `runtimeCleanupReady=true`.
  Local delivery retains runtime because the separate local tools return no package cleanup receipt.
  Completed Research and Learning
  workflows use the same cleanup tool with their own task kind; memories and exported files are
  preserved. Partial delivery and active tasks remain recoverable. Only an explicit user decision
  to discard an unfinished Research run authorizes `abandon_incomplete=true`; that mode releases
  only exact queued intake-ledger reservations owned by the run and preserves accepted ledger
  history plus Research Memory. Identity mismatch or directory-removal failure fails closed and
  rolls released reservations back.
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
- Every Blind `query_research_memory` first query carries the active campaign `run_ref` and Create
  `claim_ref`; the server validates that binding and forces Global Research regardless of the
  compatibility `blind_global_only` flag. The final submit includes the complete claim-bound
  `researchMemoryUse` as well as `learningMemoryUse`. A Global no-match keeps its selected lane
  empty while the receipt's effective scope remains `global_seed`.
- Never include reference gear, passives, skill groups, mechanism summaries, configuration, Judge
  results, source URLs, PoB code, or XML in a blind Create packet. Ambiguous Family or level evidence
  fails closed.
- Blind Create must not query or consume starter-research materials, starter caches, or
  comparative-learning state. Those web-derived candidates belong only to an explicit research
  request in the ordinary workflow.
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
  Skill-group writes are all-or-nothing: unknown gems are rejected before mutation, and a mismatch
  between requested and persisted canonical gems restores the prior XML with
  `skill_group_incomplete`.
- `get_build` = full read-back; `export_build` = a PoB import code for the user.

## Which tool when

- Max a gear slot → `optimize_item` (pass `goals={…}` for a damage+defense **blend**, not a
  one-axis craft). The BEST possible piece (beyond a plain rare — runes + Perfect essences + a
  corruption, each engine-valued) → `craft_item`; it returns the `craftSteps` to make it. Which slot
  to upgrade next → `rank_upgrades`. To preserve an existing item and optimize only its supported
  1–2 rune/soul-core sockets, use `optimize_item_sockets`, then submit the returned receipt through
  `equip_item`.
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
- Calibrate a build vs real high-end builds → `benchmark_build`; browse references by archetype →
  `list_reference_builds`. **Calibration ONLY — never copy/recommend a reference; build to the goal.**
- Realistic boss DPS (not the bare default) → `apply_combat_profile`. Add tree jewels →
  `equip_jewel` (+ `list_jewel_sockets`). Use `evaluate_jewel_socket` for replacements in an
  already allocated socket; use the protected `evaluate_next_jewel_socket` review for unopened
  sockets. Build Time-Lost candidates from exact `search_mods` ids with
  `optimize_jewel(selected_mod_ids=[...])`, never from unverified handwritten affixes. Curses/second damage skill →
  `add_skill_group`
  (`in_full_dps=True` for a second damage skill so FullDPS aggregates).
- Repair one existing skill group → `list_skill_groups`, then `replace_skill_group`,
  `set_skill_group_state`, or `remove_skill_group` with the returned fingerprint/state hash. Never
  retain a bare group index across another mutation.
- How does mechanic X work → `explain_mechanic`/`search_mechanics`; not in corpus → `lookup_mechanic`.
- Complete a skeleton's defenses fast → `scaffold_gear`. Read an item's tiers → `parse_item`.
- Is the active state a playable loadout rather than a scoring skeleton →
  `inspect_build_completeness` (active-gem/base requirements, rare/magic ilvl, scaffold placeholders,
  runes, jewels, flasks, and charms). Every remaining advisory must have a typed deferred or
  intentionally-unused decision with a reason. `spirit_opportunity_review_required` is stricter:
  adopt a valuable reservation so the advisory disappears, or use `intentionally_unused` after
  recording why the measured options had no positive value; it cannot remain deferred.
  `complete_generation_review` returns these as `requiredUserDisclosures`, which must be included
  in the final user response.
- For sustain, inspect Mana and Life flat/percent costs per use and per second. Compare the combined
  demand with net regeneration plus PoB's combined `*LeechGainRate`; use `*OnHitRate` only when the
  combined value is absent. A deterministic Life failure remains blocking even when an unmodelled
  Mana mechanism exists. An unmodelled Mana recovery pass must retain `verificationRequired=true`.

## Known limitations & gotchas

- **Fresh characters show deeply negative resists — expected.** PoB applies the endgame resist
  penalty. For ordinary level-90 softcore Create optimization, stop buying generic resistance after
  60% elemental and 30% non-CI chaos unless the user explicitly requests 75%; `get_defenses` still
  reports the actual cap/over-cap state.
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
- **Flasks:** Family-declared Unique Flasks stay locked unless their current mechanics or legality
  fail. For an ordinary life/mana Flask, use `optimize_flask` to create a legal Magic target from
  the Flask-domain pool; `optimize_item` deliberately refuses Flask bases.
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
  comparison, use current-season external samples only as supplementary evidence, `import_build`
  them, and compare on the
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
