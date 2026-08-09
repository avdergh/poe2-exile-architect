"""Exile Architect MCP servers.

The full tool surface lives in ``server.main`` (single fact source). This package exposes four
focused MCP servers that re-register their domain's tools, so a task only discovers the tools it
needs:

- ``knowledge_server``  — corpus, graph, mechanics, Research queries, freshness/prices/live,
  lifecycle research (no PoB engine).
- ``build_server``     — the single headless PoB engine, active build, Judge, Phase 5 runs,
  final artifacts/exports.
- ``research_server``  — mature-build intake, proposals and validation (quarantine-only).
- ``learning_server``  — Phase 7 campaign state, blind Create packets and Learning Memory.

``server/main`` keeps the legacy aggregate server and all shared session state (engine pool,
session gate, telemetry), so tests, smoke scripts and old host configurations keep working.
Each server process imports ``server.main`` once and re-registers its own subset with its own
short bootstrap instructions.
"""
