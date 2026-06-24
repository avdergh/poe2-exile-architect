# PoB freshness fixtures

- `pob-release.json` is a compact copy of the GitHub latest release response for
  `PathOfBuildingCommunity/PathOfBuilding-PoE2`, retrieved 2026-06-24.
- `pob-release-commit.json` is a compact copy of
  `https://api.github.com/repos/PathOfBuildingCommunity/PathOfBuilding-PoE2/commits/v0.21.1`,
  retrieved 2026-06-24.

The release body is intentionally shortened and contains patch/tree-looking text so tests can
prove release notes never grant PoB compatibility claims without `data/compatibility/pob.json`.
