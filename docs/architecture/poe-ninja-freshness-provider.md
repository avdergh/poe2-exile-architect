# poe.ninja freshness provider

## Purpose

The poe.ninja provider is a popularity-snapshot freshness source, not a patch authority.
It answers: "Which current softcore trade league build snapshot is poe.ninja indexing,
and which passive-tree series does that snapshot use?"

The provider emits exactly one `META_SNAPSHOT` evidence record with:

- a `league` claim, normalized by `VersionClaim`;
- a `passive_tree` claim, normalized from poe.ninja's `PassiveTree-x.y` token;
- diagnostics for sample size and snapshot date.

It must not emit `GAME_PATCH`, `LEAGUE`, or `PASSIVE_TREE` authority records. Those come
from official GGG sources.

## Live source contracts

Primary JSON endpoints:

- `https://poe.ninja/poe2/api/data/index-state`
- `https://poe.ninja/poe2/api/data/build-index-state`

Observed on 2026-06-24:

- `index-state.buildLeagues[]` contains league descriptors such as `Runes of Aldur`,
  HC/SSF variants, `Standard`, and private leagues.
- `index-state.oldBuildLeagues[]` contains historical build league descriptors.
  Its `url` tokens are treated as an exclusion set for current softcore trade
  selection. If the field is absent, the parser defaults the old-league set to
  empty for compatibility with compact fixtures or schema drift.
- `index-state.snapshotVersions[]` contains snapshot facts:
  - `name`
  - `url`, the API league URL token, for example `runesofaldur`
  - `version`, for example `0137-20260624-38624`
  - `snapshotName`, the display slug, for example `runes-of-aldur`
  - `passiveTree`, for example `PassiveTree-0.5`
- `build-index-state.leagueBuilds[]` contains build sample counts keyed by
  `leagueName` and `leagueUrl`, with the sample count in `total`.

`snapshotVersions[]` can also include archival or race snapshots whose `url` is not
a canonical current league token, for example `0.4.0act4bosskillrace3ssf`. These
entries must not break parsing unless their URL is selected through current
`buildLeagues[]`.

Fixtures in `tests/fixtures/freshness/` must be compact, attributed excerpts that
preserve only fields needed by the parser and selection logic.

## Selection rules

The selected candidate is the newest current softcore trade league snapshot.

Candidates are built by joining:

1. `buildLeagues[]` league descriptors,
2. `snapshotVersions[]` entries, and
3. `leagueBuilds[]` sample-size entries

on canonical lowercase API URL tokens such as `runesofaldur`. Do not substitute
the hyphenated `snapshotName` slug for `league_url`.

Exclude any candidate when:

- name/display name/token set contains `HC`, `SSF`, `Ruthless`, or `Standard`;
- the URL or name identifies a private league:
  - `PL\d+` in the name, or
  - `pl\d+` in the URL;
- the URL appears in `oldBuildLeagues[]`, even if the same URL is also present in
  `buildLeagues[]`, `snapshotVersions[]`, or `leagueBuilds[]`;
- no matching snapshot exists;
- no matching build count exists;
- `total` sample size is missing, zero, or negative.

Parse `version` with the strict shape:

```text
^\d{4}-(\d{8})-\d{5}$
```

The middle `YYYYMMDD` segment is the UTC snapshot date. Select the candidate with
the newest parsed date. If two different non-excluded league names tie on the same
newest date, treat the source as conflicted/unknown rather than choosing the first
entry.

Convert poe.ninja passive-tree tokens with:

```text
PassiveTree-0.5 -> 0_5
```

Any other passive-tree token shape is a parse failure.

## Provider behavior

Cache policy:

- refresh after: 30 minutes;
- reject after: 2 hours.

`index-state` and `build-index-state` are separate cache source URLs and separate cache
files:

- `ninja-index.json`
- `ninja-build-index.json`

Each endpoint uses the same poe.ninja TTL policy, conditional request handling, content
hash validation, and hard-stale fallback rules. The provider combines the latest acceptable
envelopes from both caches before selecting a snapshot. If either cache is missing or
invalid, the provider emits `UNKNOWN`; if either accepted cache is hard-stale, the selected
snapshot is emitted as `STALE`.

Cached payloads are treated as untrusted source data. The provider must revalidate
the selected league name, URL, snapshot version, passive-tree token, date, and sample
size before emitting evidence.

Failure semantics:

- fresh/refreshed/revalidated payloads for both endpoints -> `CURRENT` evidence;
- hard-stale fallback -> `STALE` evidence;
- missing cache, network failure, malformed JSON, ambiguous candidates, zero samples,
  missing snapshot/build count, or passive-tree mismatch -> `UNKNOWN` evidence.

The evidence `source_url` should point to the public poe.ninja builds page for the
selected league:

```text
https://poe.ninja/poe2/builds/{league_url}
```

For example, Runes of Aldur uses
`https://poe.ninja/poe2/builds/runesofaldur`, not the synthetic
`snapshotName` slug `runes-of-aldur`. The cached API URLs remain in diagnostics
and cache identity, not in user-facing evidence when a selected snapshot is
available.

## Test obligations

`tests/test_freshness_ninja.py` must cover:

- selecting `Runes of Aldur` from fixtures containing HC, SSF, Standard, old league,
  and private league candidates;
- parsing `version` date;
- converting `PassiveTree-0.5` to `0_5`;
- looking up sample size from `total`;
- ignoring archival/race snapshot URLs outside selectable `buildLeagues[]`;
- ambiguous current candidates;
- missing snapshot;
- malformed `version`;
- missing or zero sample size;
- passive-tree mismatch between candidates or expected shape;
- provider success, hard-stale fallback, missing/fetch failure, and invalid cached
  payload behavior.
