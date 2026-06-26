# poe2-build-mcp

[![Release](https://img.shields.io/github/v/release/MaxWilk/poe2-build-mcp?sort=semver)](https://github.com/MaxWilk/poe2-build-mcp/releases/latest)
[![License](https://img.shields.io/github/license/MaxWilk/poe2-build-mcp)](LICENSE)
![Platforms](https://img.shields.io/badge/platforms-win%20%7C%20mac%20%7C%20linux-blue)

> A **Path of Exile 2** build assistant for LLMs. It pairs a queryable game corpus with a
> **Path-of-Building–faithful calculation engine**, so an AI can import your build, answer
> questions, and theorycraft against **real, computed numbers — never invented ones.**

Install it as a one-click `.mcpb` in Claude Desktop and ask things like:

- *"Import this PoB code — where's my DPS bottlenecked, and what's the cheapest fix?"*
- *"Build me a level-90 Witchhunter Detonate Living and make sure it caps resistances."*
- *"What supports should Spark use, and how much does each one actually add?"*
- *"Is this build tanky enough for endgame bosses? What's my weakest defensive layer?"*

Every DPS / EHP / resistance figure it reports is computed by a real headless Path of Building,
not guessed. When PoB can't model something, it says so instead of making a number up.

## Install (Claude Desktop)

1. Download the `.mcpb` for your OS from the [latest release](https://github.com/MaxWilk/poe2-build-mcp/releases/latest).
2. Open it with Claude Desktop and install it when prompted (extensions are managed under **Settings → Extensions**).
3. Start asking build questions. The first call boots the engine (a few seconds to load game
   data); everything after is fast.

The bundle ships the PoB engine, LuaJIT, the game-data corpus, and Python deps. You need
**Python 3.11+** available on your system. The corpus and engine **self-update** from validated
GitHub releases into a writable user-data folder, so the data stays current without a reinstall
(server *code* updates land when you install a newer `.mcpb`). See [PACKAGING.md](PACKAGING.md).

### Starting a session

Once the extension is enabled, just ask a Path of Exile 2 question — Claude will reach for the
tools. To kick off explicitly, pick the **`start_build_session`** prompt from Claude Desktop's
prompt menu (or a task-specific one: `analyze_build`, `build_from_goal`, `audit_defenses`). In
Claude Code, configure the server (see [Build from source](#build-from-source-development)) and,
if you like, add a line to your `CLAUDE.md` such as *"For Path of Exile 2 build questions, use the
poe2-build MCP tools."* so it prefers them automatically.

## What it can do

**Import & analyze** a build from a PoB share code, a pobb.in/pastebin link, or raw PoB XML —
then read back computed DPS, EHP, resistances, life/ES, and more.

**Create, craft & max** builds from scratch: set class/ascendancy, level, skills, gear, config, and
the passive tree, validating every change on the engine. Optimizers craft blended best-in-slot gear
and jewels, auto-base and plan a whole gear set that caps resists (with an EHP floor), pick the
strongest support set (engine-measured), surface build-defining uniques, and rank what to upgrade
next — plus a greedy passive optimizer and an A/B `compare_to`.

> From-scratch construction yields a *complete, resist-capped, engine-verified* build that clears
> most endgame. The absolute 600k–1M-DPS meta ceiling comes from expert archetype synthesis, perfect
> gear/uniques, and a few mechanics PoB doesn't yet model (e.g. energy-meta triggers) — for that,
> `import_build` an established build and **verify + improve** it with the same tools.

**Look things up** offline: items, skill/support gems, affixes, uniques, passives, ascendancies
— a bundled SQLite/FTS corpus, no network needed.

**Reason well**, not just compute: `build_advice` and `explain_mechanic` provide durable PoE2
optimization principles and mechanics references (see
[server/BUILD_ADVICE.md](server/BUILD_ADVICE.md)) so the assistant knows *what* to change; the
engine confirms the effect.

**Plan build lifecycles**: open-ended requests can return campaign starter → transition gates →
budget endgame → final endgame, with local feedback memory so practical lessons can later become
patch-scoped technique cards.

**Stay current**: live currency/unique prices, corpus freshness checks, and one-click self-update.

### The toolset (74 MCP tools)

*Build / compute — real Path of Building numbers:*
- `import_build(source)` — PoB share code, pobb.in/pastebin link, or raw XML
- `get_build_stats(keys?)` — computed stats (DPS, EHP, resistances, life/ES/mana, …)
- `get_build()` / `export_build()` — full read-back / export as a PoB import code
- `get_defenses()` — resists (+over-cap), EHP, and the active resistance-penalty assumption
- `set_class(class, ascendancy?)` · `set_level(level)` · `set_skill(skill)` · `set_config(…)`
- `add_skill_group(skill)` — add an aura/herald/buff (e.g. Archmage) that buffs the build without replacing the main skill
- `equip_item(raw)` · `unequip_item(slot)` · `list_config_options(query?)`
- `list_jewel_sockets()` / `equip_jewel(raw, socket?)` — list tree jewel sockets / socket a jewel
- `apply_combat_profile(tier, …)` — switch on a realistic boss-fight profile (shock/curse/charges) in one call
- `evaluate_build(goals)` — pass/fail against numeric goals · `compare_to(source)` — A/B deltas
- `pinnacle_readiness(min_dps?, min_ehp?)` — gate a build against the endgame checklist (resists + chaos + EHP + DPS)
- `list_reference_builds(query?)` / `benchmark_build()` — browse / calibrate against engine-verified reference builds (calibration only)
- `solve_for(metric, target, lever)` — root-find the modifier magnitude needed to hit a stat target
- `rank_levers(metric?, unit?, levers?)` — rank stat levers by marginal gain; the min/max "where to invest next" tool
- `list_levers()` — the named levers `solve_for`/`rank_levers` accept
- `search_passives(query?, node_type?)` / `get_passive(node)`
- `alloc_passive(node)` / `dealloc_passive(node)` — allocate/route by id or name, with deltas
- `optimize_passives(metric, points, goals?, require?)` — greedy allocation: one stat, `"balanced"`, or weighted `goals` (e.g. Life+Crit); can `require` nodes
- `optimize_item(slot, metric?, goals?)` — craft a best-in-slot rare for one metric or a weighted `goals` blend (damage+defense); reports per-affix attainability (ilvl/tier) + craft-effort
- `craft_item(slot, metric?, goals?)` — best-in-slot using the FULL crafting system: runes/soul cores + Perfect essences (beyond-pool mods) + corruptions, each engine-valued
- `optimize_jewel(metric?, base?, goals?)` — craft the best rare jewel (then socket with `equip_jewel`)
- `optimize_supports(metric?, goals?)` — pick the best support-gem set, measured on the engine
- `rank_upgrades(metric?, goals?)` — rank gear slots by recraft gain ("what to upgrade next")
- `plan_gear(dps_weight?)` — plan a whole gear set: damage-max with resists capped (cross-slot budget allocation)
- `optimize_build(metric?, min_ehp?, levers?, try_uniques?, archetypes?)` — the holistic whole-build optimizer: archetype-seeded commit-and-max across tree + gear + jewels + supports (does the synthesis the per-slot tools can't); leaves the best build loaded
- `scaffold_gear(pool?, target_resist?)` — fill empty defensive slots to close resist/pool gaps (baseline, not optimal)
- `new_build()` — reset to a blank build (clean from-scratch start)
- `engine_health()` — engine + install diagnostics (liveness, LuaJIT/tree/data/server versions)

*Corpus / knowledge — bundled SQLite + FTS, no engine needed:*
- `search_items(query, item_class?)` / `get_item(name_or_id)`
- `find_skills(query?, gem_type?, tag?, color?)` / `get_gem(name_or_id)` / `find_supports_for(skill)`
- `build_advice(topic?)` — evergreen build-optimization principles
- `explain_mechanic(topic)` — our principle + the matching auto-refreshed wiki page (attributed)
- `search_mechanics(query)` — full-text search the bundled wiki mechanics tier
- `relevant_mechanics()` — mechanics worth reading for the *active* build + the engine damage diagnostic
- `search_mods(query, item_tag?, mod_type?)` / `reverse_lookup(stat)`
- `search_uniques(query, item_type?)` / `get_unique(name)`
- `relevant_uniques()` — unique items + unique jewels that synergize with the *active* build (build-defining gear a rare-only build misses; corpus suggestions, verify on the engine)
- `parse_item(text)` — parse an item's text → affix tiers (T1=best) + open prefix/suffix slots
- `list_ascendancies(character?)` / `corpus_info()`
- `suggest_build_lifecycle(goal, preferences?, budget?, mode?)` — research campaign → transition → endgame route
- `analyze_lifecycle_cohort(goal, preferences?, limit?)` — inspect non-copyable mature-build cohort evidence for a goal
- `analyze_build_lifecycle(source)` — classify an imported/source build as starter, transition, or endgame-only
- `compare_lifecycle_routes(route_a, route_b)` / `list_transition_gates(build_id?)`
- `evaluate_transition_readiness(from_stage, to_stage, state, build_id?)` — decide whether a stage swap is safe now
- `plan_lifecycle_stage_verification(stage, state?, build_id?)` — return the PoB verification budget for a lifecycle stage
- `record_build_feedback(build_id, stage, feedback, outcome?)` — save practical feedback as episodic memory
- `promote_technique_memory(evidence_ids, reason)` — promote verified feedback into patch-scoped technique memory

*Live ops & self-update — network:*
- `get_prices(query, kind, league?)` — poe2scout currency/unique prices · `list_price_leagues()`
- `get_meta_builds(league?)` — live ascendancy popularity (poe.ninja; context, not a recommendation)
- `lookup_mechanic(topic)` — fetch a mechanic/skill/item live from the PoE2 Wiki (long-tail fallback)
- `check_for_updates()` / `apply_updates()` — pull validated engine + corpus releases
- `check_data_version()` / `update_corpus(rebuild_from_source?)`

The connector also ships an LLM-facing operating guide (delivered via the MCP `instructions`
channel, from [server/ASSISTANT_GUIDE.md](server/ASSISTANT_GUIDE.md)) plus workflow prompts
(`analyze_build`, `build_from_goal`, `audit_defenses`) so the assistant uses the tools cohesively.

## How it works

Two layers behind one Python server:

- **Compute** — a vendored [PathOfBuilding-PoE2](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2)
  fork run headless under LuaJIT as a persistent JSON-RPC subprocess (loads game data once,
  answers many calls cheaply). PoB is pinned to a release tag and bumped deliberately behind
  golden-build tests.
- **Knowledge** — a bundled, read-only SQLite/FTS corpus built offline from RePoE/poe2db, plus a
  wiki-sourced **mechanics** tier (PoE2 Wiki). Both refresh **without a new install**: the server
  pulls validated corpus + engine on startup, and a scheduled CI job rebuilds the corpus from
  upstream when it actually changes — so game data and mechanics stay current automatically.

Knowledge code never imports compute code; cross-layer orchestration lives in `server/main.py`.
See [PLAN.md](PLAN.md) for the full design and [CLAUDE.md](CLAUDE.md) for engineering conventions.

## Build from source (development)

Prerequisites: **Python 3.11+**, **uv** (`python -m pip install uv`), and **LuaJIT 2.1**
(Windows via MSYS2: `pacman -S mingw-w64-ucrt-x86_64-luajit`; auto-detected at
`C:\msys64\ucrt64\bin\luajit.exe`, override with the `POB_LUAJIT` env var). Then clone the
git-ignored PoB working copy (pinned in [pob/PINNED.md](pob/PINNED.md)):

```sh
git clone --depth 1 --branch dev \
  https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git \
  pob/PathOfBuilding-PoE2
```

Set up and verify:

```sh
uv sync                                    # create venv, install deps
uv run python -m pipeline.build_corpus     # build data/corpus.sqlite from RePoE (network)
.\scripts\verify.ps1 quick                 # fast inner loop: lifecycle/server + static checks
.\scripts\verify.ps1 full                  # expensive full gate: engine + corpus + static checks
uv run python scripts/smoke_mcp_client.py  # full MCP protocol over stdio (all tool groups)
```

The `scripts/verify.ps1` profiles keep the normal development loop short: use `quick` for
knowledge/MCP/lifecycle edits, `noncompute` for broad non-engine regression, `compute` when the PoB
engine or optimizer changes, and `full` for release/merge gates. The `scripts/smoke_*.py` files
cover each tool group individually. On Windows, run the smoke scripts with `PYTHONUTF8=1` to avoid
code-page issues with some item/skill names (the server itself is unaffected).

To run from source in Claude Desktop, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "poe2-build": {
      "command": "C:\\Users\\<you>\\AppData\\Roaming\\Python\\Python312\\Scripts\\uv.exe",
      "args": ["run", "--directory", "W:\\GitHub\\poe2-build-mcp", "python", "-m", "server.main"]
    }
  }
}
```

## Data & credit

Game data is GGG's IP, redistributed as *derived* data within established community-tool norms —
with credit to the [RePoE fork](https://repoe-fork.github.io/poe2/) and poe2db. Build numbers come
from the [PathOfBuilding-PoE2](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2)
community fork. Mechanics pages are sourced from the [PoE2 Wiki](https://www.poe2wiki.net/),
licensed **CC BY-NC-SA 3.0**; they're kept in a separate, attributed corpus tier (each entry
carries its source link + license). This is a free, non-commercial tool, and is not affiliated
with or endorsed by Grinding Gear Games.
