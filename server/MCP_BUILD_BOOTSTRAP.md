# Exile Architect — Build server

One mutable headless PoB build plus Judge, generation runs, artifacts and exports. Knowledge and
Research live in the knowledge server.

## Hard boundaries

1. Never invent build numbers. Every numeric DPS/EHP/life/ES/resist/crit/accuracy/Spirit/sustain
   claim must come from this server's readback for the active build. An unmodelled game mechanic
   keeps its correct in-game structure and is verified through current mechanic/Research or in-game
   evidence; PoB modelability only limits numeric claim scope and never selects the archetype.
2. Compute tools share one active build: call sequentially, chain state hashes, use small
   function-scoped mutation batches, and trust rollback only when `rolledBack=true`.
3. Hard legality runs before every Judge receipt; preflight failures do not consume attempts.
   Checkpoint always exposes the factual eight-part quality checklist and `deliveryStatus`.
4. Create defaults to `strict_mode=false`: only hard gates and facts cross the trust boundary;
   scores, bands, warnings, reward and subjective caveats stay hidden. Never switch mid-run.
5. Research/Judge receipts are run-fresh. Memory-assisted runs first bind a run-fresh Family
   terminal discovery receipt (`retrieval.complete=true`) with
   `record_generation_family_discovery`, synthesize and bind a knowledge-grounded free-form
   mechanism blueprint with `validate_generation_blueprint` before PoB construction, then require
   successful draft validation with all Family deep reads before Judge can consume an attempt.
6. Create builds the requested target-level single-stage BD. A matching Research Family is identity
   and design authority; Blind packets execute without follow-up. Judge is advisory only.
7. Split mutations by role and chain `outputStateHash`; `recoveryRequired=true` means recover the
   session before continuing.
8. Raw PoB stays private in responses. Final save runs one structural round-trip. Final package
   publishing sends the verified code to poe.ninja and returns only its public URL. Candidate
   exports keep their label; only `deliveryStatus=recommended` is a finished recommendation.
9. Legacy export requires an approved Spirit preview; apply appends a sidecar.

Full workflow lives in the poe-bd-create skill.
