# Exile Architect — Research server

Mature-build intake, clean fragment/edge/record/pattern proposals and validation. The external
Researcher Agent consumes packets built by the research orchestrator.

## Hard boundaries

1. Raw intake is quarantine-only: raw PoB code/XML and whole-character mirrors never leave
   quarantine and never enter Research memory, Learning Memory or Git.
2. No static source → no physical graph node; no existing graph node → no semantic edge; no
   patch/version/status → no durable memory; no copy-safety pass → no mature knowledge.
3. Acceptance is the only durable writer. Proposal/validate tools never persist; they type-check
   schemas and dedupe (query-before-propose).
4. Edges require resolved stable keys, never fuzzy/vendor names; ambiguity fails closed.
5. Fragment bodies stay bounded (Chinese ≤400 chars / English ≤250 words per record question).
6. This server never calls a model provider and never reads the working directory.
