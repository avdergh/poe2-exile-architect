# PoE2 BD Creator Architecture

[English](ARCHITECTURE.md) | [中文](ARCHITECTURE.CN.md)

Last updated: 2026-07-09

This document describes the high-level module layout and data flow. Detailed implementation work
belongs in `docs/phases/`. Architecture is the only document family currently maintained in both
English and Chinese; the project spec, schemas, and phase plans are Chinese-only.

## High-Level Shape

```text
External Agents
  Researcher / Architect / Critic
        |
        v
server/main.py  (MCP tools, prompts, instructions)
        |
        v
domain routers / workflow services  (thin orchestration, no hidden LLM loop)
        |
        +-- compute: Headless PoB, build mutation, item/support/passive tools
        +-- knowledge: corpus, mature learning, copy-safety, lifecycle, schemas
        +-- graph/memory: physical facts, semantic edges, reward-weighted memory
        +-- judge: build evaluation, comparison, modelability, benchmark reporting
        +-- agent helper tools: lookup, PoB operations, candidate-state shaping, `.build` export
        +-- freshness/live: patch/tree/PoB/poe.ninja/wiki/price context
        |
        v
data/* / user-data / pob/*
```

The server exposes typed tools and contracts. External agents perform creative reasoning. The
repository does not run its own hidden LLM loop. `server/main.py` should stay a thin MCP entrypoint:
tool registration, parameter adaptation, and response shaping. Cross-domain workflows should live in
router/service modules so the entrypoint does not become the owner of compute, graph, judge, and
cross-layer workflow logic. A durable event bus is a later scaling option, not a Phase 0 architecture
requirement.

## Data Flow

```text
source probe
  -> quarantine payload
  -> ResearchPacket
  -> Researcher Agent
  -> CleanFragment + semantic edge proposals
  -> validators + copy-safety + graph resolution
  -> long-term memory / semantic graph

User request / BuildBrief summary
  -> Architect Agent queries graph / memory / corpus / PoB tools as needed
  -> Agent-led candidate build design
  -> Agent uses tools to assemble an evaluable transient build state
  -> BuildSnapshot / local transient state reference
  -> Headless PoB Judge
  -> BuildEvaluation / BuildComparison
  -> Critic Agent gaps
  -> rollback / repair / early stop
  -> StatePruner / ContextPack
  -> compact agent retry context
  -> RewardEvent
  -> graph/memory weight updates
```

## Core Runtime Modules

| Area | Current Files | Responsibility |
| --- | --- | --- |
| MCP entry | `server/main.py` | Thin public tool registration, parameter adaptation, and response shaping. |
| Domain routing | planned router/service modules | Cross-layer workflow orchestration outside the MCP entrypoint. |
| Agent instructions | `server/ASSISTANT_GUIDE.md`, `AGENTS.md`, `CLAUDE.md` | Human/agent-facing operating guidance. |
| Compute | `server/compute/*`, `pob/pob_headless.lua` | Headless PoB calls, import/export, build mutation, numeric evaluation helpers. |
| Knowledge | `server/knowledge/db.py`, `mechanics.py`, `refbuilds.py` | Static corpus lookup and mechanics context. |
| Mature intake | `server/knowledge/mature_*`, `server/live/mature_*` | Quarantine-only mature sample intake and clean fragment contracts. |
| Copy-safety | `server/knowledge/copy_safety.py` | Guardrails against reconstructable build material. |
| Lifecycle/eval | `server/knowledge/lifecycle*` | Existing route, verification, quality, and evaluation helpers. |
| Freshness/live | `server/freshness/*`, `server/live/*` | Patch/tree/PoB/poe.ninja/wiki/price context. |
| Scripts | `scripts/*` | Verification, smoke tests, packaging, source probes. |

Planned modules should follow the same layering:

- graph and memory code belongs in knowledge-layer modules until it needs its own package;
- judge code should be deterministic and compute-backed;
- agent helper tools should provide focused, auditable, repeatable lookup or mutation operations; they
  must not become an "agent writes a plan, the program automatically completes the whole build" flow;
- workflow orchestration should move into router/service modules before `server/main.py` becomes a
  coordination bottleneck;
- repair loops should pass compact `ContextPack` inputs to agents while full snapshots and round
  logs stay in local state;
- MCP tools should wrap already-tested lower-layer functions.

## Authority Boundaries

- PoB/compute owns numeric claims.
- Static data owns physical graph facts.
- External agents own reasoning and proposed semantic links, but not validation.
- The external Architect Agent owns build creation, query choices, transient-state assembly strategy,
  and failure-correction direction.
- Validators own schema, copy-safety, graph-resolution, and split-boundary enforcement.
- Judge outputs own reward signals.
- State pruning owns the agent-facing retry context for rollback/repair loops; full local history is
  not automatically resent to external agents.
- Phase benchmark reports own claims of progress.

## Documentation Map

| Path | Role |
| --- | --- |
| `docs/PROJECT_SPEC.md` | Chinese-only project constitution, hard boundaries, phase relationships, and phase status. |
| `docs/ARCHITECTURE.md` / `docs/ARCHITECTURE.CN.md` | This bilingual high-level architecture and data-flow map. |
| `docs/SCHEMAS.md` | Chinese-only core artifact contracts. |
| `docs/phases/*.md` | Chinese-only detailed phase work, dependencies, progress, and acceptance criteria. |

## Runtime State

- Active build state is isolated per MCP session. The process runs at most five Headless PoB
  instances by default, and complete tool calls within one session are serialized so multi-step
  optimizer state cannot interleave.
- Durable generated reports are not stored in the repository.
- Mature raw payloads are quarantine-only and transient.
- Long-term knowledge must be clean, versioned, evidence-backed, and copy-safe.
- User-data/runtime directories may hold local state; repository docs must describe contracts, not
  accidental local artifacts.
