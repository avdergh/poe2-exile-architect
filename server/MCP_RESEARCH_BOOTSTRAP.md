# Exile Architect — Research server

Mature-build queue/lease/review acceptance plus clean fragment/edge/record/pattern validation.
Installed-product runtime is private user data addressed by opaque `runRef`; Agents never edit its
queue, review, quarantine or database files directly.

## Hard boundaries

1. Raw intake is quarantine-only: raw PoB code/XML and whole-character mirrors never leave
   quarantine and never enter Research memory, Learning Memory or Git.
2. No static source → no physical graph node; no existing graph node → no semantic edge; no
   patch/version/status → no durable memory; no copy-safety pass → no mature knowledge.
3. `accept_research_review` / `retry_research_review` are the only durable Research Memory writers.
   Validation may atomically save the lease-bound safe review runtime, but never accepts knowledge.
4. Edges require resolved stable keys, never fuzzy/vendor names; ambiguity fails closed.
5. Fragment bodies stay bounded (Chinese ≤400 chars / English ≤250 words per record question).
6. This server never calls a model provider, searches the working directory, or writes into a
   checkout/plugin cache. It reads local source files only when their exact paths were submitted.
