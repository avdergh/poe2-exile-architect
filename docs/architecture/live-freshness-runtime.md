# Live freshness runtime

## Purpose

The live freshness runtime is the operational layer behind `get_freshness_report`.
It lets the assistant check current-season safety without turning a slow or offline
network source into a hanging MCP call.

The runtime is intentionally conservative: network evidence can make a report more
specific, but missing, stale, or conflicting required sources still block
`verified_current`.

## Runtime entry points

- MCP tool: `get_freshness_report(force_refresh: bool = False)`
- Compatibility wrapper: `check_data_version()`
- Development smoke command: `scripts/smoke_freshness.py`

`check_data_version()` keeps the old RePoE probe nested under `legacy_corpus_probe`.
Its top-level `recommendation` is the strict live freshness decision, not the legacy
single-source corpus timestamp result.

## Cache location

Freshness caches live under the writable user-data directory:

```text
<POE2_MCP_DATA or platform user-data>/freshness/
```

Current cache files:

- `ggg-patch.json`
- `ggg-tree.json`
- `poe-ninja.json`
- `pob.json`

Set `POE2_MCP_DATA` to relocate this directory during development or smoke tests. For
example:

```powershell
$env:POE2_MCP_DATA='E:\poe-bd-creator\.runtime-data'
```

## Time budgets

Service budget:

- total freshness service timeout: `5.0s`;
- provider worker pool: shared `ThreadPoolExecutor(max_workers=4)`;
- per HTTP request timeout: `2.0s`.

The service timeout is a response budget. If a provider does not finish inside that
budget, this report treats that provider as missing and fails closed. Python cannot
preempt an already-running thread, so provider cancellation is best-effort; the shared
bounded executor prevents timed-out provider work from creating unbounded new worker
threads across repeated MCP calls.

## Cache policies

| Source | Refresh after | Reject after | Minimum forced refresh interval |
| --- | ---: | ---: | ---: |
| GGG patch forum | 15 minutes | 2 hours | 60 seconds |
| GGG official passive tree | 1 hour | 6 hours | 60 seconds |
| poe.ninja build snapshot | 30 minutes | 2 hours | 60 seconds |
| Path of Building release | 1 hour | 6 hours | 60 seconds |

`force_refresh=True` asks providers to refresh now, but the minimum forced refresh
interval still suppresses rapid repeated refreshes for the same cache key.

## Conditional requests and cache integrity

Cache envelopes store:

- source identity and source URL;
- fetched and checked timestamps;
- `ETag` / `Last-Modified` validators when the server provides them;
- canonical JSON payload SHA-256;
- the compact parsed payload needed by the provider.

On refresh, providers send conditional headers from the existing cache. A `304` response
updates `checked_at` without changing the payload. A corrupt, mismatched, future-dated,
or wrong-source cache is ignored rather than trusted.

Cache writes are atomic sibling-file replacements. The runtime never stores full HTML or
large raw upstream responses in these JSON caches; providers keep compact, shaped payloads.

## Offline and stale fallback

Provider network failures degrade to provider diagnostics. They do not raise through the
MCP tool unless the failure is an internal programming error outside the expected cache or
transport vocabulary.

Fallback rules:

- fresh cache: provider returns cached evidence as `fresh`;
- successful refresh: provider returns `refreshed`;
- `304` revalidation: provider returns `revalidated`;
- network failure with acceptable cache age: provider returns `fallback`;
- network failure after `reject_after`: provider may mark evidence stale or unknown,
  depending on the provider's source authority;
- no cache and no network: provider returns missing/unknown evidence and the evaluator
  blocks verification.

This means offline mode can still explain the latest known source facts, but it cannot
invent current-season verification.

## Expected current blocker before PoB certification

As of the Phase 2 implementation, the local repository/development pin is:

```text
PoB commit: a82a33b4
```

The observed upstream Path of Building Community PoE2 release on 2026-06-24 was:

```text
tag: v0.21.1
commit: dc409a7073e4e2752e9a642db7544af53551d006
```

Until a PoB upgrade is imported and certified in `data/compatibility/pob.json`, the
full report is expected to remain blocked. This is a safety result: remote release notes
can prove a newer PoB exists, but only this project's compatibility manifest can certify
which `game_patch` and `passive_tree` the local engine/data have passed golden tests
against.

## Smoke output policy

`scripts/smoke_freshness.py` is a developer diagnostic, not a CI gate for live network
availability. It should:

- call the service with `force_refresh=True`;
- print the top-level decision, blockers, provider cache states, evidence versions, and
  short diagnostics;
- sanitize diagnostics by truncating long values and replacing newlines;
- exit non-zero only for internal script/service errors;
- exit zero for `blocked_stale`, `blocked_unknown`, or temporary network unavailability,
  because those are valid freshness outcomes.

