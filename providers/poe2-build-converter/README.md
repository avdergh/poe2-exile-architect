# PoB2 to `.build` provider adapter

This directory is an isolated adapter for the MIT-licensed
[`PraedythXIV/poe2-build-converter`](https://github.com/PraedythXIV/poe2-build-converter).

The upstream dependency is pinned to commit
`27f5dad0d0979aa23a604defd11fcf7ae4668444`. Exile Architect communicates with `runner.ts`
through newline-delimited JSON and does not depend on the upstream web UI or internal TypeScript
types.

Prepare the provider with:

```powershell
.\.tools\uv\uv.exe run python scripts/install_build_converter_provider.py
```

The installer runs the pinned npm install and compiles the adapter plus upstream conversion core
into `dist/runner.cjs`. Runtime conversion needs a compatible Node.js executable, the compiled
runner, and the provider-private DOM dependency. The Python service never imports upstream
TypeScript types.

The upstream MIT license and game-data notice are retained in `UPSTREAM_LICENSE.txt`. The provider
installer removes build-only npm dependencies after compilation; runtime keeps only the compiled
conversion core and its private DOM dependency.
