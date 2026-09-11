# Exile Architect runtime guide

This is a tool-fact and safety index for the Agent-led prototype. Product skills own the
workflows; this document does not define a second build or Research procedure. The MCP servers
inject their small domain-specific `MCP_*_BOOTSTRAP.md` files, not this full guide.

## Route the request

- Route user-triggered Create through `/poe-bd-create`. Load that installed skill before starting
  a run. It directly generates the requested target-level endgame build; there is no blocking
  leveling-progression question. At interactive start, ask only for local versus local-plus-share
  delivery when the user has not already chosen. Internal Blind packets stay non-interactive.
- Route mature-build research through `/poe-bd-research` / `$poe-bd-research`. Its Controller owns
  scheduling; `poe-bd-research-worker` owns the single leased case and typed review. The Controller
  never claims cases or reads case evidence. Use the skill's mode selection before any network
  crawl; an explicit request for real research must not be replaced by a link-only preflight.
- Use `$poe-bd-learning-loop` only for explicitly requested comparative learning, campaign
  inspection or recovery. The status service does not create tasks or call a model. Repairing
  that service does not authorize starting or resuming a campaign.
- General mechanic or imported-build diagnostics may use the appropriate tools below without
  creating a generation or learning run.
- Discover unavailable-looking tools by exact name through the host's tool search. Probe
  availability with an actual `get_freshness_report` call before declaring the toolset unavailable.
  Do not search the user's project for helper scripts or substitute a previous artifact.

Installed skills live under the plugin's `skills/` directory; in a source checkout they live under
`poe-bd-creator-plugin/skills/`. Within `poe-bd-create`, load references only when needed:
`research-use.md` for source authority, `mechanism-blueprint.md` before construction,
`build-and-refine.md` for assembly and quality work, `validation-and-recovery.md` for Judge/retry,
`output-contract.md` for submissions, and `delivery.md` for artifact verification and export.
`references/blind-mode.md` owns the Phase 7 handoff exceptions.

Do not ask Codex Desktop users to paste PowerShell/Python commands into the chat box. Product
Create and Research use typed MCP tools and private managed user data. Repository CLI scripts
are development compatibility entry points. During a runtime product workflow, report safe tool
failures rather than editing source, tests, installers, run files or databases.

## Evidence and authority

- PoB numbers describe the exact observed state, output skill and combat configuration. Static
  corpus facts, Graph identity, Agent interpretation and model hypotheses have different scopes.
  Never invent DPS, EHP, resistances, Spirit legality or sustain.
- Agent DPS scenario estimates are allowed in `performanceEstimates`, separately from observed
  PoB values. Require finite ranges, inspected evidence, assumptions, overlap/double-count handling
  and limitations, with fixed `evidenceKind=agent_estimated`. They never replace Judge/reward values
  or prove hard legality. Unknown modelling is not zero benefit or a reason to lower adoption value;
  choose skills by their mechanisms, duties, conditions and evidence-backed scenario estimates.
  Candidate status describes verification coverage, not build strength. Full and compact Review
  preserve the estimates for explicit disclosure.
- `ToolReference` contains `toolName/queryRef/summary/evidenceKind/reviewBasis`.
  Missing `evidenceKind` means `unverified`; a plausible query string is not a receipt.
  `internal_receipt` is currently supported only for validated run-fresh Research references.
  `agent_reviewed` requires a substantive `reviewBasis` describing the exact inspected evidence
  and relevant conditions. Graph, corpus, compute and web observations without a supported receipt
  registry use that declaration; it is not backend proof of tool execution or semantic truth.
- Blueprint `grounded/inferred/rejected` claims cannot rely on unverified references. A
  `hypothesis` may retain them with explicit verification tasks; `unknown` remains unknown.
  Blueprint validation returns `evidenceAudit`, separately binding source authority without
  certifying numeric legality. Draft, Judge, saved baselines and final Review retain that binding.
  Legacy evidence is not silently promoted.
  Original package/plan-to-source associations are protected separately: an old reference used
  elsewhere cannot replace its original association. Same-subject corroboration may be appended.
- `search_graph_components` discovers candidates; pass the selected `resolverPayload` unchanged to
  `resolve_graph_component`. Successful component resolution proves existence, not the claimed
  interaction. Family identity uses player `skill:` keys; `gem:` aliases need typed equivalence.
  Never issue raw Cypher/Gremlin/SQL. Physical nodes need static sources; semantic edges need
  resolved existing nodes.
- Full-text mechanic search also discovers candidates. Read the selected exact content; Research
  records `mechanicAudit` supports/contradicts/silent and `relevanceReason` with independent
  corroboration. Page title, ID, redirect, revision and search rank prove neither relevance nor
  mechanism truth.
- Use `query_research_memory` for progressive research recall with `response_profile="create_compact"` for Create. Inspect
  `familyRecordCoverage/familyRecordIndex/familyPremiseCatalog`, consume the complete page chain,
  and deep-read the eligible records required by the selected Family. Preserve `researchMemoryUse`
  and source-case authority. External evidence never resolves a Research premise; resolution needs
  a current-run deep-read receipt. The Create skill owns comparison lanes and package decisions.
- Pinned PoB data, physical graph, and corpus override patch-sensitive prose in `build_advice`.
  Model knowledge can guide an explicitly qualified design hypothesis where the Create skill
  allows it. It cannot replace an available Family's identity or conclusions.

## Freshness and version limits

Call `get_freshness_report` before describing a build as current-season verified. Only
`verified_current` permits that label; `current_unmodelled` needs the reported calculation caveat.
Inspect component blockers instead of branching only on the top-level decision. Known current
game rules/tree with only stale local PoB can support a limited-evidence candidate; unknown or
conflicting core rules/tree/mechanics cannot be guessed away. A provider rate limit alone is not
proof that independently corroborated local tree data is unusable.

`trustedEvaluationScope=snapshot_and_judge_only` and `versionContextTrusted=false` mean the Judge
receipt does not certify caller-supplied versions. Exact patches matter; season/tree agreement is
not numeric model certification. Research readback keeps source patch separate from model patch.

Cross-patch Family identity stays stable. Historical Research keeps its original patch,
`targetApplicability` and verification tasks; `reviewed_compatible` covers a specified patch delta,
not a new sample or current PoB numbers. `incompatible/changed_scope` cannot authorize target-patch
adoption. Shared `contentRevisionRef` identifies text, not transferable source permissions.

## Managed run tools

| Purpose | Tools and authoritative result |
| --- | --- |
| Start ordinary Create | `start_generation_run`; current run binding and safe draft template |
| Bind Family | `record_generation_family_discovery`; terminal discovery receipt |
| Prepare design | `construct_research_execution_contract`, then `validate_generation_blueprint` before PoB mutation/planning |
| Validate implementation | `validate_generation_draft`; final exact offense group/name and observed implementation signature |
| Inspect active candidate | `inspect_generation_checkpoint`; merged checks for one semantic state hash |
| Formal generated-candidate Judge | `evaluate_generation_candidate`; exact snapshot and trusted receipt |
| Preserve final candidate | `save_final_build_artifact`; exact passing Judge snapshot or explicitly selected protected baseline |
| Verify saved artifact | `verify_lifecycle_stage(..., artifact_id=...)`; independent artifact-bound lifecycle receipt |
| Validate and consume final submission | `validate_generation_output`, then `complete_generation_review`, after artifact save and verification |
| Local delivery | `export_final_pob_artifact`, `export_final_build_artifact` |
| Requested local + share delivery | `export_final_build_package`; report every returned output and its status |
| Research queue and case | `start_research_run/claim_research_case/inspect_research_case/read_research_case/search_research_case` |
| Research review | `get_research_review_contract/initialize_research_review/validate_research_review/accept_research_review` |
| Research status/recovery | `get_research_run_status/retry_research_review/cleanup_research_run` |
| Follow-up evidence | `get_research_followup_status/submit_research_gap_review/reacquire_research_source/submit_research_patch_review` |

Saving a human review packet alone does not finish Create. The skill's artifact, lifecycle,
Review and selected delivery route determine completion. `evaluate_build` and
`pinnacle_readiness` are diagnostics, not substitutes for the formal generated-candidate Judge.
Blind Create keeps its internal artifact and uses the learning skill's submit contract without
user-facing export or ordinary delivery cleanup.

Every new Create needs a new run. Ordinary Create uses `memory_assisted`; explicit `--no-memory`
skips Research and Learning and uses `researchMemoryRef=disabled:no_memory_baseline`.
Both retain Blueprint and Judge. Governed runs from an older output/evidence contract must restart;
old artifacts and receipts are not rewritten.

## One active PoB state

Run every PoB/compute tool sequentially: apparently read-only probes can temporarily mutate and
restore the active build. Independent static corpus/graph/mechanic queries may run in parallel.
One MCP session owns one in-memory build; other sessions use isolated engines. The default
process cap is five, including reserved Judge/optimizer capacity.

- `new_build` resets the build. `import_build` replaces it. `set_class` re-roots the tree but
  retains gear/skills/config; use a fresh bootstrap for a new build.
- `apply_build_mutation_batch` accepts exact, function-scoped transactions:
  `bootstrap/mechanism_shell/skill_loadout/passive_delta/required_gear/ordinary_gear/config`.
  Do not mix the whole build into one transaction. Only a bootstrap starting with `new_build`
  can omit the input hash; chain subsequent `outputStateHash` values.
- Public mutators share the same state. Independent `equip_item/set_config/replace_skill_group`
  calls change the hash too. On mutation failure, only `rolledBack=true` proves restoration.
  Stop on `recoveryRequired=true` and follow explicit recovery; residual state is not a baseline.
- Read `list_skill_groups` before exact edits. Group writes resolve all gems and compare the
  persisted canonical multiset. `skill_group_incomplete` restores the prior XML rather than
  silently discarding requested gems.
- `apply_combat_profile` replaces its Boss tier and six booleans, including false values;
  `set_config` remains a partial patch. Both return the latest semantic state hash.
- Use `testedSkillGroups` and the exact offense group/name to interpret measurements.
  `mainSocketGroup` is calculation focus, not proof of a single damage skill.
  `AverageDamage` is average hit; `TotalDPS` is selected Hit DPS; `CombinedDPS` includes the
  selected skill's modeled secondary/DoT components; `FullDPS` rolls up enabled actors/groups.
  These fields do not prove real encounter uptime or projectile overlap.

## Targeted tool facts

| Question | Tool |
| --- | --- |
| Exact component facts | `find_skills/get_gem`, `search_items/get_item`, `search_uniques/get_unique`, `search_mods` |
| Mechanic explanation | `search_mechanics/explain_mechanic`; `lookup_mechanic` for live fallback; retain returned attribution |
| Passive reachability | Build-server `search_passives/get_passive`; `alloc_passive(path_attribute=...)` for new paths, `set_passive_attribute` for exact allocated attribute nodes; no rerouting |
| Stat sensitivity | `rank_levers/list_levers/solve_for` |
| Complete item comparison | `optimize_item/rank_upgrades/plan_gear` |
| Proven special crafting | `craft_item`; pass its unchanged `craftReceiptRef` to `equip_item` |
| Existing-item sockets | `optimize_item_sockets`; apply the returned plan through trusted equip |
| Support combination | `optimize_supports`; same exact effect, full current/candidate combinations |
| Jewel replacement | `list_jewel_sockets/evaluate_jewel_socket/optimize_jewel/equip_jewel`; explicit already allocated sockets, transactional source/legality/active-Spec readback. A positive replacement is allowed; acquiring an extra socket still uses the protected evaluate/apply decision |
| Next reachable jewel socket | `evaluate_next_jewel_socket/apply_next_jewel_socket_decision` |
| Ordinary Flask | use `optimize_flask` to create a legal Magic target |
| Numeric comparison/calibration | `compare_to/benchmark_build/list_reference_builds`; reference library is calibration-only |
| Live context after design lock | `get_prices/list_price_leagues/get_meta_archetype_trends` |

Whole-build `optimize_build` and global passive-tree replanning remain disabled for normal Create.
A hard-only Judge pass does not replace the Agent-led quality pass. For next-jewel review at 90+,
protect core/support nodes with `protected_node_ids` and compare the selected jewel across every
currently reachable empty socket. Do not stop on a fixed round or jewel count. The protected
policy permits safe single-leaf exchanges, not branch dismantling.

Generated ordinary rares default to `realistic_trade`: at most five explicit affixes and two deep
T1 rolls. Explicit `theoretical` describes an upgrade ceiling. Special crafting provenance and
game legality are separate from attainability. Item searches remove the old slot for resistance
pruning, compare complete loadouts on the same output/config, and require recoverable measurements.
`plan_gear` projections must replay from the original state. Failed measurement is not no gain.

Final support, jewel and socket audits bind the locked state. Stale/missing receipts and unapplied
positive plans block Judge. Only the documented current support capability gap with verified
application, complete structure and satisfied constraints may continue as unknown; this includes
runtime-attested rate and incomplete duration/DoT object models and retains candidate status. Support application can target
the host or payload but every support needs a real active effect. Searches preserve runtime-observed
support usage conditions on every group effect; changing those conditions requires an explicit Agent
edit before re-auditing, and does not prove uptime. Numeric comparisons stay within the observed
model. Proxy spawns and Herald procs require an independent
rate; payload attack Speed and zero DPS cannot replace it. A duration/DoT object's positive partial
impact readout cannot authorize whole-set damage ranking when duration and DoT outputs are absent. That broader gap
retains its incomplete-model diagnosis and unsupported numeric ranking, while candidate review may
continue. Unknown model coverage is not zero benefit or low adoption value. `support_audit_v4` compares full
combinations, including removal-only changes. Support-granted effects need an independently valid host;
self-grants and unanchored grant cycles cannot establish compatibility. Every candidate reads PoB Life,
LifeReserved and LifeUnreserved; exhausting available Life is illegal even with CI or freed Spirit.
Older support audits require revalidation. `item_socket_review_v2` distinguishes failed or
unmodeled measurements from `no_positive`; pending `socketed/partial_socketed` plans need trusted
equip, and a failed recheck revokes the prior pending plan.

Price only discloses acquisition risk after design lock. Do not replace an adopted Family component
because it is expensive or because the user supplied a budget. The Create skill owns required
unique adoption, ordinary gear planning, and Rune/Soul Core quality decisions.

## Legality, lifecycle and delivery scope

Default Create feedback is `strict_mode=false` (hard-only). The Judge still computes internally;
deterministic failures, state bindings and factual diagnostics remain visible. Strict feedback
requires explicit user choice and cannot change after the first attempt. Preflight and Judge
share `HardLegalityAudit`; deterministic preflight rejection has `attemptConsumed=false`.

Generated level-80+ candidates need at least 60% fire/cold/lightning and 30% non-CI chaos.
Lower-level and trusted reference resistance values are read back for diagnostics under that
Judge rule. Lifecycle separately uses actual PoB level: 30% elements at 45–64, 50% at 65–79,
60% at 80–89, no added percentage floor below 45 or at 90+. It does not add a 75% rule.
Level-90 softcore ordinary resistance optimization stops at 60/30 unless the user requests 75%.

Spirit legality uses uncapped `spiritRequested/spiritOverBy`; `SpiritReserved` may be capped.
At final completion, allocated jewel sockets must be filled and `unspentPoints` must be zero.
Low Spirit utilization needs a coherent opportunity review, not arbitrary filler. Charm capacity
comes from actual PoB `CharmLimit`, capped at three; missing slot data is unknown.

Sustain covers Mana and Life per-use/per-second flat and percentage costs. `*LeechGainRate`
already includes on-hit; `*OnHitRate` is only a fallback. Unmodeled Mana recovery cannot cover a
deterministic Life failure. Missing recovery modeling means verification is needed, not an
automatic claim that the build will run out of Mana.

`lifecycleEvidenceCoverage` covers only the trusted snapshot/stage. Artifact verification inherits
the Judge output selection. Caller booleans cannot authorize recovery, flasks or a build-defining
mechanism: typed declarations are re-observed from the exact snapshot. Saved baseline restoration
requires the process-local exact Judge snapshot and its original design evidence, plus explicit
`laterFindingsScope=candidate_delta_only`. Missing/stale evidence cannot promote an old unknown.
Only the final manifest's `recommended` status permits a finished recommendation; otherwise
clearly deliver a candidate with its unresolved limitations.

## Research storage and comparative learning

Research runs use opaque `runRef` and private user data, never caller projects or plugin cache.
`initialize_research_review` returns an in-memory safe review object. Typed validate/accept owns
writes; `fullyResolvedForAccept` and safe-subset acceptance are distinct. The review contract and
worker skill own extraction, evidence, source-claim and completion requirements.

Different conditions and topics coexist; exact source/projection bindings control revisions.
Accepted source versions and immutable shared content revisions are separate. Original gap
diagnostics stay unchanged; typed follow-up evidence closes effective gaps, and stale support
reopens them. Retention expiry authorizes bounded cleanup when invoked, not research completion;
live leases and pending acceptance recovery protect the source. Cleanup preserves safe audits.

Phase 7 uses a `FamilyTarget`, equal levels, and separate Reference/Comparator and Create tasks.
The Blind packet includes only target/version/default goals; it contains no reference equipment,
passives, skills, mechanism summary, source material or Judge result. Blind Create cannot consume
starter research, starter caches or comparative state. After Compare, no repair/regeneration of
that case is allowed. Improvements apply to later cases.

`BuildComparisonReport` v2 retains the external Comparator's verdict. Non-unknown dimensions need
both sides' evidence references, bound to the stored safe packets for that case. Evidence packets
and comparisons share the bounded reference syntax, preserving canonical ASCII apostrophes.
Critical flags must match typed critical gaps. `tradeoff` is separate and never automatically counts as
`notWeaker`. Unknown dimensions remain explicit. Ten-case trends require complete bound coverage
for all cases and the joint first-three/last-three conditions; legacy/unbound evidence cannot
produce `initial_progress_signal`. Judge stays `advisoryOnly=true`, with no automatic winner or
reward write; directional evidence is not causal proof. Learning Memory only holds cross-dimensional
Create guidance; concrete build knowledge belongs in Research. Corrections remain append-only.

## Safety boundary

No in-game interaction, overlay, automation, memory reading or live-screen parsing. Third-party
PoB code/XML, account/character details and whole-character mirrors remain in private transient
quarantine. Durable knowledge may retain complete reusable core mechanism packages; component
count alone is not a copyability rule. Agent-generated safe summaries are allowed: the helper
must not reject them merely because they resemble a common build.

Full generated XML can live only in the accepted local private final artifact and user-authorized
exports, never in chat, Research/Learning Memory or Git. HumanReviewPacket is safe-only, with no
hidden reasoning transcript or raw queries. No repository-owned model/provider loop is permitted.

Developer verification uses focused tests, then `verify.ps1 quick` for MCP/knowledge/lifecycle/docs
and `noncompute` for broad non-engine work. `full` is the release/merge gate; `compute` is manual
for direct engine/Lua/numeric/optimizer changes, not an ordinary documentation gate.
