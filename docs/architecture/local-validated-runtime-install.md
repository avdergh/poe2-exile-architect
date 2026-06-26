# Local validated runtime install

The live freshness gate reads the active runtime from `POE2_MCP_DATA` before falling back to
the bundled seed data. After certifying a new PoB commit in source, local development needs a
repeatable way to install that exact certified corpus/engine pair into `.runtime-data` so the
same freshness gate can be smoke-tested before a public GitHub release exists.

`scripts/install_local_validated_runtime.py` is that local-only bridge. It does not weaken
the production self-update path:

1. It reads the current pinned PoB working copy commit.
2. It resolves that commit through `data/compatibility/pob.json`.
3. It refuses to install if the commit has no compatibility entry.
4. It copies the already-built corpus and the headless PoB runtime subset into the target data
   directory.
5. It writes `installed.json` with the certified `pob_commit`, `pob_version`, `game_patch`,
   and `passive_tree` claims.

The script is intended for development targets such as `.runtime-data`. It deliberately refuses
to use the repository root as the target, because replacing `<target>/pob` at the repository root
would destroy the tracked/ignored PoB source layout.

For the 2026-06-26 `0.5.4` certification, the local runtime version used for smoke testing is:

```text
0.1.39.1-local.20260626
```

That version is higher than the previously installed `0.1.39` local data but lower than a future
`0.1.40` release under the updater's numeric comparison.
