# Live freshness service integration

## Purpose

This slice connects the live freshness providers to the MCP surface.

The service answers one operational question: **can the assistant safely describe a
build as current-season verified right now?** It does not certify new PoB commits, rank
builds, or update the local corpus. It only gathers source evidence, applies the
existing freshness gate, and returns enough diagnostics for the assistant to explain
why the gate passed or blocked.

## Provider set

The service aggregates five provider families:

- local validated release evidence from `server.freshness.providers`;
- official GGG patch notes, producing `GAME_PATCH` evidence;
- official GGG passive-tree release/JSON, producing `LEAGUE` and `PASSIVE_TREE` evidence;
- poe.ninja build snapshots, producing `META_SNAPSHOT` evidence;
- Path of Building compatibility evidence, producing `POB_ENGINE` and `POB_DATA`
  evidence.

Providers remain independent. Each provider owns source parsing, cache policy, and
source-specific diagnostics. The service owns orchestration only.

## Time budget

The MCP tool must be responsive even when a live source stalls. The service therefore
uses a bounded parallel collection pass:

- maximum workers: `4`;
- default total timeout: short enough for interactive MCP use;
- any provider that does not finish inside the remaining budget is cancelled when
  possible and represented as a missing provider result;
- finished providers are still included even if another provider fails or times out.

The timeout is a total service budget, not a per-provider timeout. This prevents three
slow sources from serially consuming the user's whole turn.

## Failure behavior

Provider exceptions never abort the whole report. A failed provider contributes:

- no evidence;
- `cache_state = "missing"`;
- a diagnostic containing the provider name and failure type.

The freshness evaluator then blocks because required components are missing or unknown.
This is intentionally conservative and keeps one source outage from hiding the rest of
the evidence.

## Provider diagnostics in the report

`FreshnessReport` stays the domain output of the pure evaluator. The service extends the
serialized MCP response with a `provider_status` array. `providers` is retained as a
backward-compatible alias for existing smoke and development tooling:

```json
[
  {
    "source": "poe-ninja",
    "cache_state": "refreshed",
    "duration_ms": 153,
    "diagnostics": ["selected league Runes of Aldur with 124269 indexed builds"]
  }
]
```

Provider order is deterministic:

1. local validated release;
2. GGG patch;
3. GGG official tree;
4. poe.ninja snapshot;
5. PoB compatibility.

The ordering makes tests stable and makes user-facing explanations easier to compare
between runs.

## MCP tools

`get_freshness_report(force_refresh: bool = False)` calls the service and returns the
strict gate report plus provider diagnostics.

`check_data_version()` remains as a compatibility wrapper. It calls the same service
once, uses the strict decision as its top-level `recommendation`, and nests the old
RePoE timestamp probe under `legacy_corpus_probe`.

The manifest keeps the same tool names. Descriptions should make clear that freshness is
now cross-source and live, not just a local RePoE timestamp check.

## Test obligations

Service tests must cover:

- all required live/local evidence matching -> `verified_current`;
- stale local PoB evidence -> `blocked_stale`;
- poe.ninja passive-tree claim conflicting with GGG tree -> `blocked_conflict`;
- provider diagnostics are serialized in deterministic order;
- one provider exception becomes a provider-level missing/unknown diagnostic without
  losing other evidence;
- total timeout returns promptly with a missing-provider diagnostic.

Server tests must cover:

- `get_freshness_report(force_refresh=True)` forwards the force flag to the service;
- `check_data_version()` calls the service once and keeps the legacy corpus probe nested;
- the MCP tool surface remains stable.
