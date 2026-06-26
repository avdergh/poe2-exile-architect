# PoB dev-export certification

The normal path is to certify a tagged PathOfBuilding-PoE2 release. When GGG publishes a
new game patch before PoB cuts a release, this project may certify an exact PoB `dev`
commit only if every condition below is true:

1. GGG live patch evidence has advanced beyond the latest certified compatibility manifest entry.
2. The PoB `dev` history contains an explicit export/data commit for that game patch.
3. The selected commit is pinned by full SHA and includes any follow-up generated cache commit.
4. The local headless PoB golden suite passes against that exact SHA with tracked fork patches applied.
5. `data/compatibility/pob.json` records the candidate separately from tagged releases.

This keeps the freshness gate conservative: an untagged upstream commit may become a
candidate, but it never becomes an authority until our local certification proves the
headless bridge, fork patches, corpus, and golden calculations still work together.

## 2026-06-26 0.5.4 drift

The 2026-06-26 live smoke detected a real cross-source drift:

- GGG patch provider reports `0.5.4 Hotfix 2` and claim `game_patch=0.5.4`.
- Latest tagged PoB release remains `v0.21.1` at
  `dc409a7073e4e2752e9a642db7544af53551d006`.
- The installed validated runtime (`v0.1.39`) and existing compatibility manifest still
  assert `game_patch=0.5.3`.

PoB `dev` has a suitable candidate chain:

| Commit | Message | Role |
| --- | --- | --- |
| `7f52b81ba25217737524257799732361bc8fda42` | `0.5.4 Export` | Imports the current game patch data. |
| `7d1aa43c8c938d7be150d197ed9cdec8a4c1c620` | `ModCache` | Regenerates the derived mod cache after the export. |

The candidate to certify is the later `ModCache` commit:

```text
7d1aa43c8c938d7be150d197ed9cdec8a4c1c620
```

## Runtime implication

Updating `pob/PINNED.md`, `.github/workflows/release.yml`, and
`data/compatibility/pob.json` prepares the next validated release. A local smoke against
`.runtime-data` can still block until that runtime is rebuilt/installed, because the local
provider reads `installed.json` and must not pretend an older release has new patch claims.

The PoB provider must also distinguish "latest tagged release is newer" from "latest
tagged release is older than a certified dev-export candidate." A compatibility entry
containing `pob-dev-export` remains current only while its `verified_at` timestamp is
strictly later than the latest tagged release `published_at`; equality is treated as unsafe
because both sources are second-resolution timestamps. A future tagged release published at
or after that timestamp supersedes the candidate and forces a new certification.
