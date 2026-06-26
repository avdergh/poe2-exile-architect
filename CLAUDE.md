# CLAUDE.md — engineering conventions for poe2-build-mcp

This file is the working agreement for anyone (human or AI) building on this repo.
For *what* we're building and *why*, read [PLAN.md](PLAN.md). This file is *how* we build it.

## What this project is (one paragraph)

An `.mcpb`-installable MCP server that gives an LLM a queryable Path of Exile 2 corpus
(bundled SQLite, **knowledge layer**) plus a Path-of-Building–faithful calculation engine
(headless LuaJIT subprocess, **compute layer**). It answers build questions, imports a
user's PoB build, and helps create/tweak builds against natural-language goals — with every
number *computed by PoB*, never invented.

## Non-negotiable invariants

These are the rules that keep the project trustworthy. Don't violate them without changing
this file first.

1. **The engine is the source of truth for numbers.** Never hand-compute, approximate, or
   hard-code PoE2 damage/defense math in server code, and never let an answer state a number
   the engine didn't produce. If PoB can't model something, surface that via
   `validate_build` — do not fake a value.
2. **The server is a substrate, not a build AI.** Expose composable primitives (query,
   mutate, compute, validate, price). Creative synthesis is the LLM's job. Resist adding
   "smart" heuristics to the server that belong in the model's reasoning.
3. **Knowledge is offline-first and deterministic.** The corpus is a bundled, read-only
   SQLite file. The only network calls at runtime are the live-ops tools (`get_prices`,
   `list_price_leagues`, `get_meta_builds`, `get_meta_archetype_trends`,
   `get_freshness_report`, `check_data_version`, `check_for_updates`, `apply_updates`,
   `update_corpus`, and `lookup_mechanic`).
   `lookup_mechanic` is a deliberate, narrow exception: a single user-triggered, read-only wiki
   *lookup* for the long tail not in the corpus. It returns a targeted slice (not a dump),
   degrades to "unavailable", and never alters the corpus — it is *not* bundled redistribution
   and *not* scraping (see #4). The deterministic corpus remains the default; live lookup is the
   fallback when the corpus lacks a topic.
4. **Scraping happens only at build time, never at runtime.** poe2db/RePoE/wiki ingestion lives
   in `pipeline/` and runs in CI. The runtime never *scrapes* (bulk-fetches to store); it
   downloads vetted artifacts. The single on-demand `lookup_mechanic` read (#3) is not scraping:
   it fetches one page for immediate display and stores nothing.
5. **Generated builds are always verified before being presented.** The norm is
   `create → validate → cost → present`. A build that fails `validate_build` is flagged, not
   recommended.
6. **No in-game interaction, ever.** No overlay, automation, memory reading, or live-screen
   parsing. It's out of scope and against GGG's ToS. Reject features that head this way.
7. **PoB is pinned and bumped deliberately.** The PoB-PoE2 submodule is pinned to a release
   tag. Updating it is a conscious change gated by the golden-build tests (§ Testing).

## Architecture map

```
server/knowledge/  → SQLite + FTS queries        (offline, deterministic)
server/compute/    → PoB RPC client + sessions    (talks to headless LuaJIT)
server/live/       → prices, meta, version, update, wiki lookup (the only runtime network)
pob/               → vendored PoB-PoE2 + pob_headless.lua (JSON-RPC over stdio)
pipeline/          → offline corpus build (CI only)
data/corpus.sqlite → bundled prebuilt artifact
```

Keep these boundaries clean: knowledge code must not import compute code, and neither should
reach into `live/`. Cross-layer orchestration belongs in `server/main.py` or a thin
coordinator, not buried in a layer.

## Code conventions

**Python (3.11+)**
- Managed with `uv`; all deps in `pyproject.toml` with a committed lockfile. No `pip install`
  into the ambient env.
- **Full type hints** on public functions; `mypy` clean. Prefer typed structures (dataclasses /
  `TypedDict`) for data crossing layer boundaries; MCP tools themselves return JSON-friendly
  `dict[str, Any]` (there is no central `models.py`).
- Format with `ruff format`; lint with `ruff` — both must pass in CI.
- Small, single-purpose modules. One tool per logically-cohesive function; register tools in
  `main.py`, keep implementations in the layer packages.
- Errors: fail loud in the pipeline (CI should break on bad data), degrade gracefully at
  runtime (a missing live price returns "unavailable", it doesn't crash the tool).
- No secrets or tokens in code. Live endpoints are public/no-auth for v1.

**Lua (compute shim)**
- `pob/pob_headless.lua` is the only Lua we own. Keep it thin: stub host functions, run the
  JSON-RPC loop, call into PoB — don't reimplement PoB logic.
- Don't edit vendored PoB source; if a change is unavoidable, it goes in the shim or is
  upstreamed to the fork, never patched in place silently.
- `luacheck` clean.

## Tool design conventions

Every MCP tool should:
- Have a precise, typed input schema and a stable, documented return shape.
- Return **targeted slices**, never raw data dumps. Never return all of `mods` or a whole
  tree into context — that's what search/filter params are for.
- Return **human-readable strings** (stat translations resolved), not internal stat IDs.
- Be **idempotent and side-effect-free** except for the explicit state tools (`update_corpus`
  and the build-session mutators).
- Clearly distinguish *computed* facts (from the engine) from *looked-up* facts (from the
  corpus) from *live* facts (from the network), so the model can caveat appropriately.

**Checklist for adding a tool:** typed inputs + a documented return shape on the tool fn → implementation
in the right layer → registration in `main.py` → smoke test in `tests/` → docstring that
states the data source (corpus / engine / live) → update PLAN.md catalog if it's new surface.

## Testing

- **Golden builds are the safety net.** `tests/golden_builds/` holds reference build XML +
  expected engine output. These must pass; they catch both our regressions and PoB bumps.
  When you bump the PoB submodule, re-validate and update goldens in the *same* commit with a
  note on what changed.
- Corpus ingestion is **schema-validated**; a parser/scrape change must include a test.
- Each tool has at least a smoke test; `import_build` has round-trip tests.
- CI matrix boots the headless engine on every shipped OS target.
- Don't mark a task done on the basis of "it should work" — run it. If something is skipped
  or failing, say so plainly.

## Commands

> Wired up as scaffolding lands; treat as the intended interface and keep them working.

```
uv sync                      # install deps
uv run poe2-mcp              # run the MCP server locally
uv run pytest                # run tests
uv run ruff check . && uv run mypy server   # lint + types
uv run python -m pipeline.build_db          # build corpus.sqlite locally
uv run python pob/spike.py                  # M0 headless spike harness
```

## Data, licensing, privacy

- Game data is GGG's IP; we redistribute *derived* data within established community-tool
  norms. Credit RePoE-fork and poe2db. Don't overclaim ownership or relicense game data.
- **Wiki mechanics are CC BY-NC-SA 3.0** (PoE2 Wiki / poe2wiki.net). They live in their own
  `mechanics` table, each row stamped with `source` + `license` + `url`, and tool output carries
  attribution. Keep this tier **segregated** from our own (Tier-1) prose so it stays a clearly-
  attributed aggregation, not a derivative of our code. **NonCommercial**: this is a free,
  non-commercial tool — if that ever changes, the wiki tier must be dropped (it's designed to be
  removable without breaking Tier-1 or the engine). Never let a wiki *number* override an engine
  number; the wiki informs *how mechanics work*, not magnitudes.
- Scrape politely: cache, rate-limit, identify the tool, respect the source. Pipeline only
  (plus the single on-demand `lookup_mechanic` read, which stores nothing).
- Treat pasted PoB codes as **user data**: don't log them, don't transmit them anywhere
  except the local engine. Live-ops calls send only what they must (e.g. a league + item
  name for pricing), never the user's whole build.

## Git / workflow

- Conventional, scoped commits (e.g. `compute: add pathfind RPC`, `pipeline: scrape uniques`).
- Work on feature branches; do not initialize a new repository or rewrite history unless the
  human explicitly asks for that operation.
- Don't commit the bundled `data/corpus.sqlite` build artifact to source history; it's a
  release asset. Commit `schema.sql` and the pipeline that produces it.
- Keep PLAN.md and this file current when decisions change — they're the source of truth for
  intent and conventions.
- Starting with the next new requirement-development round, run a pre-implementation design/spec
  review subagent before coding. Give it the project goal, optional current phase goal, the new
  requirement goal, and the intended work; ask whether the direction is reasonable and whether a
  better design exists. This is separate from the post-implementation spec review and code review.

## Codex skill loading

- Never construct a skill path from memory or from the skill name alone. Always read the current
  turn's `Skill roots` table, expand the listed alias (`r0`, `r1`, `r5`, etc.), then append the
  exact skill-relative path shown in the available-skills list.
- Plugin-provided skills may live under a plugin cache or another root chosen by the current
  Codex session. Do not assume `$CODEX_HOME/skills/<skill-name>` or any other fixed directory unless
  the current `Skill roots` table explicitly maps a root there.
- If a skill path lookup fails, stop and re-check the root alias mapping before reading any more
  skill files or continuing implementation.
