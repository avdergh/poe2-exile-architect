# PoB freshness provider

## Purpose

The PoB provider reports whether the locally installed Path of Building Community
PoE2 engine/data can safely participate in current-season build research.

This provider is deliberately conservative. A remote PoB release can prove that a
newer engine exists, but it cannot prove this project has verified that engine. Only
`data/compatibility/pob.json` can grant `game_patch` and `passive_tree` compatibility
claims.

## Source contracts

Remote GitHub sources:

- `https://api.github.com/repos/PathOfBuildingCommunity/PathOfBuilding-PoE2/releases/latest`
- the release tag/commit endpoint used to resolve the release to a full commit SHA

Observed on 2026-06-24:

- latest release tag: `v0.21.1`
- release name: `Release 0.21.1`
- published at: `2026-06-23T05:51:33Z`
- release commit: `dc409a7073e4e2752e9a642db7544af53551d006`
- local pin `a82a33b4` is behind that release by 16 commits

Local sources:

- `.runtime-data/installed.json` when a validated app/data release has installed an
  engine payload;
- `pob/PINNED.md` for the repository's development-time fallback pin;
- `data/compatibility/pob.json`, maintained by this project after golden verification.

The local installed metadata currently records:

```json
{
  "version": "v0.1.39",
  "app_version": "0.1.39",
  "pob_commit": "a82a33b4",
  "engine_sha256": "5e48ae5319203958e05d78a117424ff065515674fd4d72c7b659bfb6615a8760"
}
```

## Compatibility manifest

Initial file:

```json
{
  "schema_version": 1,
  "entries": []
}
```

Entry shape after a PoB upgrade has passed this project's golden tests:

```json
{
  "commit": "dc409a7073e4e2752e9a642db7544af53551d006",
  "pob_version": "0.21.1",
  "game_patch": "0.5.3",
  "passive_tree": "0_5",
  "verified_by": ["golden-tests"],
  "verified_at": "2026-06-24T00:00:00+00:00"
}
```

Rules:

- `schema_version` must be exactly `1`.
- `entries` must be an array.
- `commit` must be a 40-character hex SHA.
- `pob_version`, `game_patch`, and `passive_tree` must be non-empty strings.
- `verified_by` must be a non-empty array of non-empty strings.
- `verified_at` must be timezone-aware ISO-8601.
- Duplicate commits are invalid.
- Short local commits can match a manifest entry only when the prefix is unambiguous.

Release notes, commit messages, and filenames are useful discovery hints, but they do
not grant compatibility claims.

## Evidence behavior

The provider emits two local evidence records:

- `POB_ENGINE`
- `POB_DATA`

If the local commit resolves to a manifest entry:

- status is `CURRENT`, unless a newer remote release proves the installed commit is
  behind;
- both records carry `game_patch` and `passive_tree` claims from the manifest entry.

If the local commit is absent from the manifest:

- records never carry `game_patch` or `passive_tree` claims;
- status is `STALE` when the latest remote release is ahead;
- otherwise status is `UNKNOWN`, because the local engine may be usable but is not
  certified.

If no local commit is available, emit `UNKNOWN` evidence for both records.

If the latest remote release is unreachable:

- use local manifest facts if present;
- include a diagnostic describing the unavailable remote source;
- do not infer staleness from a failed network request.

Remote cache policy:

- refresh after: 1 hour;
- reject after: 6 hours.

## Provider boundaries

This task does not upgrade PoB, run golden certification, or edit the vendored PoB
payload. That is a later certification task.

This task creates the manifest and provider logic only. Service/MCP aggregation remains
Task 5.

## Test obligations

`tests/test_freshness_pob.py` must cover:

- local commit absent from the compatibility manifest never receives patch/tree claims;
- matching verified commit receives `game_patch` and `passive_tree` claims;
- remote release ahead of the local pin marks local PoB engine/data stale;
- release-note text alone cannot grant compatibility;
- malformed manifest entries are rejected;
- unambiguous local short-prefix commit matches a full manifest commit;
- ambiguous short prefixes are rejected;
- missing local commit emits `UNKNOWN`;
- remote fetch failure with no cache emits `UNKNOWN` but does not crash.

