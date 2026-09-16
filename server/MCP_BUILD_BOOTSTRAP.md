# Exile Architect — Build server

Build/Judge/exports. Study uses isolated PoB, never the active build or Judge attempts.

## Hard boundaries

1. Never invent build numbers. Numeric DPS/EHP/life/ES/resist/crit/accuracy/Spirit/sustain claims
   require this server's active-build readback. Unmodelled mechanics keep their correct in-game
   structure and require mechanic/Research or in-game evidence. PoB coverage limits numeric claims,
   never archetype choice.
2. Compute tools share one active build: call sequentially, chain state hashes, use small
   function-scoped mutation batches, and trust rollback only when `rolledBack=true`.
3. Hard legality runs before every Judge receipt; preflight failures do not consume attempts.
   Checkpoint always exposes the factual eight-part quality checklist and `deliveryStatus`.
4. Create defaults to `strict_mode=false`: only hard gates and facts cross the trust boundary;
   scores, bands, warnings, reward and subjective caveats stay hidden. Never switch mid-run.
5. Research/Judge receipts must be run-fresh. Memory-assisted runs bind complete Family discovery
   (`retrieval.complete=true`) via `record_generation_family_discovery`, then bind a researched
   free-form blueprint via `validate_generation_blueprint` before PoB construction. Judge requires
   draft validation after all Family deep reads.
   ToolReferences default to unverified. agent_reviewed needs reviewBasis; internal_receipt needs
   run-validated Research. queryRef alone proves no execution.
6. Create builds the requested target-level single-stage BD. A matching Research Family is identity
   and design authority; Blind packets execute without follow-up. Judge is advisory only.
7. Stop on `recoveryRequired=true`; explicitly recover the session before continuing.
   `engine_health` is a non-queued process/activity observation: `busy` is not failure.
   A client timeout does not prove backend completion; `new_build` clears a build, not the process.
8. Raw PoB stays private in responses. Final save runs one structural round-trip. Final package
   publishing sends the verified code to poe.ninja and returns only its public URL. Candidate
   exports keep their label; only `deliveryStatus=recommended` is a finished recommendation.
9. Legacy export requires an approved Spirit preview; apply appends a sidecar.

Full workflow lives in the poe-bd-create skill.
