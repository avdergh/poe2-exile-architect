# Exile Architect — Research server

Mature-build queue/lease/review acceptance plus clean fragment/edge/record/pattern validation.
Installed-product runtime is private user data addressed by opaque `runRef`; Agents never edit its
queue, review, quarantine or database files directly.

## Hard boundaries

1. Raw intake is quarantine-only: raw PoB code/XML and whole-character mirrors never leave
   quarantine and never enter Research memory, Learning Memory or Git.
2. No static source → no physical graph node; no existing graph node → no semantic edge; no
   patch/version/status → no durable memory; no copy-safety pass → no mature knowledge.
3. `accept_research_review` / `retry_research_review` are the ordinary case writers. Candidate
   signals from `inspect_research_merge_candidates` never decide semantics. A model-authored
   deep-record merge may write only through `preview_research_record_merge` followed by an exact
   revision/hash-bound `apply_research_record_merge` after explicit user approval. The server never
   decides semantic equivalence.
   Validation may atomically save the lease-bound safe review runtime, but never accepts knowledge.
   Formal v3 acceptance writes pattern/deep/edge/final receipt and one memory revision in a single
   Memory transaction; queue/ledger finalize idempotently from that receipt.
4. Edges require resolved stable keys, never fuzzy/vendor names; ambiguity fails closed.
5. Fragment bodies stay bounded (Chinese ≤400 chars / English ≤250 words per record question).
6. This server never calls a model provider, searches the working directory, or writes into a
   checkout/plugin cache. Product tools read local source files only from explicitly submitted
   absolute paths.
7. Every enabled source skill container has an explicit research/support disposition. Preserve its
   root skill and socketed items; socketed payload effects do not replace that physical relation.
   Unresolved or coverage-gap containers cannot be reported as clean.
8. A merge reviewer must browse primary PoE2 sources when mechanics are unfamiliar, patch-sensitive
   or disputed. Full URLs and copied pages remain outside durable memory; unavailable or conflicting
   authority rejects the merge or keeps the records distinct.
