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
5. Mechanic full-text results are candidates only. Read a selected exact page and let the Agent
   judge supports/contradicts/silent; title, redirect, page ID and ranking never authorize a claim.
6. Preserve Research `conditions`, `failureConditions`, exclusions and verification tasks when
   adopting a record. Create receipts are typed, run-bound, memory-revision-bound and paginated;
   only a complete single-session chain from one scope/sourceCase lane authorizes Create.
   Create discovers Family by class/ascendancy before choosing a main skill; an explicitly requested
   skill is only a primary/secondary `related_skill_key`. Distinguish `no_family` from
   `known_family_not_authorized`, then deep-read every returned `requiredDeepReadRecordIds` entry.
   After authoritative and comparison lanes are complete, use
   `construct_research_execution_contract` to compare case profiles and create reason-required
   packages. Cross-case adoption is legal only through a full companion/compatibility/
   implementation/verification/exit plan; the contract never auto-assembles a build.
7. `query_public_learning_memory` returns only the copy-safe release/local lesson projection.

Full workflow lives in the poe-bd-create / poe-bd-research skills.
