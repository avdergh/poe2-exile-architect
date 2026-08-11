# Exile Architect — Knowledge server

Offline corpus, physical graph, mechanics, Research queries, live freshness/prices and lifecycle
research. No PoB engine here.

## Hard boundaries

1. Static facts come from corpus/graph/mechanics/Research; time-sensitive facts from freshness,
   prices and live sources. Missing sources require an explicit evidence caveat — never guess.
2. Build numbers (DPS/EHP/resists/Spirit/sustain) are never invented here: they come from the
   separate build server's PoB readback. Research discovery can state expectations, not values.
3. Only `get_freshness_report` with `verified_current` permits a "current-season" label;
   otherwise preserve the returned blockers/caveats verbatim.
4. Fuzzy component queries are candidate discovery only: resolve stable keys before adopting, and
   never let fuzzy similarity authorize a semantic edge or a target anchor.
5. Preserve Research `conditions`, `failureConditions`, exclusions and verification tasks when
   adopting a record; receipts are typed and run-bound (progressive, exact version).
6. `query_public_learning_memory` returns only the copy-safe release/local lesson projection.

Full workflow lives in the poe-bd-create / poe-bd-research skills.
