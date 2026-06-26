# Phase 3F Lifecycle Source Evidence Extraction

## Purpose

`analyze_build_lifecycle` can already classify imported PoB builds, but a research agent often sees
forum posts, guide snippets, pobb.in descriptions, or user-written notes before it has a clean PoB
code. Phase 3F adds a conservative text evidence extractor so those sources can inform lifecycle
classification without being treated as computed truth.

## Evidence Contract

`extract_lifecycle_source_evidence(source)` returns:

- `stageSignals`: lifecycle stages explicitly hinted by the text.
- `lifecycleHints`: starter/endgame/transition signals found in plain language.
- `skillCandidates`: active/support gem names confirmed by the local corpus where possible.
- `uniqueCandidates`: unique item names confirmed by the local corpus where possible.
- `transitionHints`: short source snippets around switch/respec/transition language, with any level
  numbers mentioned nearby.
- `riskFlags`: warnings such as "endgame language without starter language" or "required unique
  language".
- `evidenceTags`: `external-guide`, `corpus`, and `lifecycle-source-extraction`.

## Boundaries

- The extractor is not a web crawler and does not fetch pages by itself.
- It does not invent exact PoB numbers, item prices, passive routes, or final viability.
- Corpus-confirmed names are candidates, not recommendations. The engine must still verify them.
- Single-source text evidence cannot be promoted into durable memory unless later corroborated by
  engine deltas, repeated feedback, or fresh meta/reference evidence.

## Classification Use

`analyze_build_lifecycle` consumes the extracted evidence when direct PoB import fails or when an
imported build needs additional lifecycle context:

- Required unique/threshold language makes the build less likely to be a direct starter.
- Starter/leveling language supports `starter_route_available`.
- Explicit low-level starter language supports `low_level_viable`.
- Endgame/final-form language supports `endgame_scaling`.

The output must preserve the extracted evidence so the assistant can explain *why* it classified a
guide as starter, transition, or endgame-only.
