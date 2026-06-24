# poe.ninja freshness fixtures

These compact JSON fixtures are hand-trimmed excerpts modeled after the public
poe.ninja Path of Exile 2 index endpoints documented in
`docs/architecture/poe-ninja-freshness-provider.md`.

Only fields required by the Task3 parser and selection rules are retained:
league names/API URL tokens, snapshot versions, `snapshotName`, passive-tree
tokens, and build sample totals. The selected league URL uses the live
poe.ninja token shape (`runesofaldur`), while `snapshotName` retains the
hyphenated display slug (`runes-of-aldur`) and must not be used as the API
league URL.

The fixture also includes an old race snapshot URL containing dots
(`0.4.0act4bosskillrace3ssf`). It is intentionally absent from
`buildLeagues[]` so tests prove archival snapshots do not break current-league
selection.
