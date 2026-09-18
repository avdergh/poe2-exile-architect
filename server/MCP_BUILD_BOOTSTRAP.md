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
5. Receipts must be run-fresh. Memory-assisted Create binds complete Family discovery and an
   accepted Blueprint before construction, then validates Draft after deep reads, before Judge.
   ToolReferences default to unverified; a queryRef alone proves no execution.
6. Create builds one target-level BD. Matching Family defines identity/design; Blind never asks
   follow-up questions. Judge is advisory only.
7. Stop on `recoveryRequired=true`; explicitly recover the session before continuing.
   `engine_health` is a non-queued process/activity observation: `busy` is not failure.
   A client timeout does not prove backend completion; `new_build` clears a build, not the process.
8. Raw PoB stays private in responses. Final save runs one structural round-trip. Final package
   publishing sends the verified code to poe.ninja and returns only its public URL. Candidate
   exports keep their label; only `deliveryStatus=recommended` is a finished recommendation.
9. Legacy export requires an approved Spirit preview; apply appends a sidecar.
10. Support/socket tools: use `background=true`, then `get_compute_operation`; cancellation uses
    `cancel_compute_operation` at safe boundaries. Results are process-local, not audit passes.
    Final support checks use `purpose="final_audit"`; exploration cannot certify them.

Full workflow lives in the poe-bd-create skill.
