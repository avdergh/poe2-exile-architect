# Exile Architect — Build server

One headless PathOfBuilding-PoE2 engine, the mutable active build, Judge, Phase 5 runs, final
artifacts/exports and artifact-bound lifecycle receipts. Knowledge/Research queries live in the
separate knowledge server.

## Hard boundaries

1. Never invent build numbers. Every DPS/EHP/life/ES/resist/crit/accuracy/Spirit/sustain claim
   must come from this server's readback for the active build.
2. All compute tools share one mutable active build — call sequentially and chain state hashes.
   Submit exact Agent-authored changes as small function-scoped `apply_build_mutation_batch`
   calls (never a mixed whole-build batch). Trust rollback only when `rolledBack=true`.
3. The shared score-free hard-legality audit (attributes, item/gem levels, weapon compatibility,
   Spirit, passive budgets, affixes, `Scaffold ...`/Item-Level issues) runs before every Judge
   receipt; preflight failures return `attemptConsumed=false`.
4. Create defaults to `strict_mode=false`: only hard gates and facts cross the trust boundary;
   scores, bands, warnings, reward and subjective caveats stay hidden. Never switch mid-run.
5. Research/Judge receipts are run-fresh: `evaluate_generation_candidate`'s
   `researchMemoryRef` must have been queried inside the current Phase 5 run; stale or missing
   receipts fail closed.
6. Ordinary Create directly builds the requested target-level single-stage endgame BD (typically
   80+); internal Blind Create packets (`referenceBlind=true`) execute the locked packet without
   follow-up questions. A matching Research Family is the identity and design authority — model
   knowledge only supplements dimensions, never replaces Family conclusions. Judge is advisory
   only.
7. Mechanic changes are submitted as small function-scoped `apply_build_mutation_batch` batches
   split by role (`bootstrap`/`mechanism_shell`/`skill_loadout`/`passive_delta`/`required_gear`/
   `ordinary_gear`/`config`); later batches chain the previous `outputStateHash` and only a
   `rolledBack=true` result confirms restoration. `recoveryRequired=true` means stop and recover
   the session.
8. Final generated XML is private to the artifact/export layer — never return raw XML or whole
   PoB material to the client.

Full workflow lives in the poe-bd-create skill.
