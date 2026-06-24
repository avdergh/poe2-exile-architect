# poe.ninja freshness fixtures

These compact JSON fixtures are hand-trimmed excerpts modeled after the public
poe.ninja Path of Exile 2 index endpoints documented in
`docs/architecture/poe-ninja-freshness-provider.md`.

Only fields required by the Task3 parser and selection rules are retained:
league names/URLs, snapshot versions, passive-tree tokens, and build sample
sizes. Values are intentionally small and synthetic where that keeps tests
focused on selection behavior.
