# PoE2 BD Creator Architecture

[English](ARCHITECTURE.md) | [中文](ARCHITECTURE.CN.md)

Last updated: 2026-07-27

This document describes the high-level module layout and data flow. Detailed implementation work
belongs in `docs/phases/`. Architecture is the only document family currently maintained in both
English and Chinese; the project spec, schemas, and phase plans are Chinese-only.

## High-Level Shape

```text
External Agents
  Researcher / Architect / Reference-Comparator
        |
        v
server/main.py  (MCP tools, prompts, instructions)
        |
        v
domain routers / workflow services  (thin orchestration, no hidden LLM loop)
        |
        +-- compute: Headless PoB, build mutation, item/support/passive tools
        +-- knowledge: corpus, mature learning, copy-safety, lifecycle, schemas
        +-- graph/memory: physical facts, semantic edges, Research DB, local Learning Memory
        +-- judge: build evaluation, modelability, advisory-only numeric evidence
        +-- comparative learning: quarantine cases, blind packets, comparisons, campaign state
        +-- build progression: starter evidence, semantic checkpoints, recoverable orchestration
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
  -> BuildEvaluation / final local artifact

Mature reference build
  -> case-bound quarantine
  -> safe Profile by a Reference/Comparator Agent
  -> FamilyTarget + reference evidence
  -> independent Create Agent receives only FamilyTarget + level
  -> generated evidence + Judge advisoryOnly
  -> dimension-by-dimension comparison by the Reference/Comparator Agent
  -> Research feedback / Learning Memory lesson + correction
  -> recall for the next case

Complete progression request
  -> discover up to ten mature Families from exact class/patch/tree Research
  -> Agent compares and ranks every returned Family (2-10), retaining selected and reserve
  -> ordinary single-stage Create builds the selected target from blank
  -> shared pre-Judge hard-legality audit; preserve every passing baseline
  -> TargetAnchorIdentity + ten-dimensional TargetDesignCoverage + immutable artifact/hash
  -> external Agent performs bounded current-patch starter research for the base class
  -> safe StarterResearchPacket cache; no page prose or full URL is persisted
  -> independent starter selection + TransitionBridge + typed Research query receipts
  -> selected premises and decisions checkpointed outside conversation context
  -> recoverable Progression service serializes pre-target Phase 5 runs
  -> final target closure reuses the same anchor without another Create
  -> ProgressionRouteArtifact v3 + multi-stage delivery package
```

## Core Runtime Modules

| Area | Current Files | Responsibility |
| --- | --- | --- |
| MCP entry | `server/main.py` | Thin public tool registration, parameter adaptation, and response shaping. |
| Domain routing | planned router/service modules | Cross-layer workflow orchestration outside the MCP entrypoint. |
| Agent instructions | `server/MCP_BOOTSTRAP.md`, `server/ASSISTANT_GUIDE.md`, `AGENTS.md`, `CLAUDE.md` | Small MCP bootstrap plus complete human/agent-facing operating guidance. |
| Compute | `server/compute/*`, `pob/pob_headless.lua` | Headless PoB calls, import/export, build mutation, numeric evaluation helpers. |
| Knowledge | `server/knowledge/db.py`, `mechanics.py`, `refbuilds.py` | Static corpus lookup and mechanics context. |
| Mature intake | `server/knowledge/mature_*`, `server/live/mature_*` | Quarantine-only mature sample intake and clean fragment contracts. |
| Copy-safety | `server/knowledge/copy_safety.py` | Guardrails against reconstructable build material. |
| Lifecycle/eval | `server/knowledge/lifecycle*` | Existing route, verification, quality, and evaluation helpers. |
| Comparative learning | `server/learning/*` | Phase 7 typed contracts, case quarantine, blind packets, comparison reports, Learning Memory, and recoverable campaign state. |
| Build progression | `server/generation/progression*.py` | Phase 8 exact-version Family discovery with complete comparison of the returned 2-10 candidates; selected/reserve identities; exact-Family coverage, unexpanded indexes, premise catalogs, and deep-read usage audits; recoverable target run/failure/same-Family retry/one explicit reserve switch; one-time pending graph-snapshot resolution within the same route; immutable target anchors; StageCreatePacket memory-mode validation; stage optimization masks; state-hash merged validation; compact lifecycle responses and receipt-based retrieval deduplication without post-selection evidence caps; `starter_common` public campaign knowledge followed by transition-time `family_exact` recall; bounded semantic working checkpoints with premise decisions; audited failed-stage replans; complete target recovery packages for any unfinished anchored route; artifact-bound lifecycle receipts, CAS state, cost profiles, and multi-stage export. |
| Hard legality / artifact selection | `server/judge/hard_legality.py`, `server/generation/artifacts.py` | Reuses one score-free deterministic legality audit across checkpoints, Judge, item candidates, and artifact saving; preflight failures do not consume Judge attempts, and a still-trusted passing baseline can be restored after a quality-pass regression. |
| Judge feedback projection | `server/generation/evaluation.py`, `preflight.py`, `validation_checkpoint.py`, `retry.py`, `prototype.py` | Runs the same internal Judge but defaults Create to `strict_mode=false`: only hard gates and deterministic diagnostics cross the trust boundary. Explicit `strict_mode=true` restores full subjective scoring for one mode-locked run. |
| Context telemetry | `server/runtime/tool_telemetry.py` | Records only tool name, latency, response bytes, and safe correlation ids to locate context amplification. |
| Freshness/live | `server/freshness/*`, `server/live/*` | Patch/tree/PoB/poe.ninja/wiki/price context. |
| Scripts | `scripts/*` | Verification, smoke tests, packaging, source probes. |

Planned modules should follow the same layering:

- graph and memory code belongs in knowledge-layer modules until it needs its own package;
- judge code should be deterministic and compute-backed;
- agent helper tools should provide focused, auditable, repeatable lookup or mutation operations; they
  must not become an "agent writes a plan, the program automatically completes the whole build" flow;
- workflow orchestration should move into router/service modules before `server/main.py` becomes a
  coordination bottleneck;
- comparative learning must send only `FamilyTarget + level` to Create; reference details remain in
  the isolated Comparator context;
- MCP tools should wrap already-tested lower-layer functions.

## Authority Boundaries

- PoB/compute owns numeric claims.
- Static data owns physical graph facts.
- External agents own reasoning and proposed semantic links, but not validation.
- The external Architect Agent owns build creation, query choices, transient-state assembly strategy,
  and failure-correction direction.
- Validators own schema, copy-safety, graph-resolution, and split-boundary enforcement.
- The Comparator Agent owns dimension tradeoffs and the overall verdict; Judge numbers are an
  `advisoryOnly` attachment.
- The Phase 7 state service owns CAS, idempotency, pause, resume, and safe checkpoints; it does not
  create tasks or call models.
- Research schemas own concrete build knowledge. Learning Memory accepts only cross-dimensional
  Create behavior lessons and their corrections.
- The external Phase 8 Agent owns web research and stage design. The progression service validates
  safe summaries, orchestration state, and trusted artifacts; it does not crawl, call models, or
  derive early builds by downgrading a final PoB.
- Phase 8 must not change ordinary Create semantics. Exact-version Research first returns up to ten
  mature Families, and the Agent compares every returned candidate (2-10); a uniquely user-locked
  Family skips discovery. Candidate comparison uses no full Judge/global optimization. Ordinary
  single-stage Create builds the first-ranked target; only an evidence-backed Agent decision may
  switch once to the reserve. The final stage reuses the identical artifact/source hash. Judge is
  advisory; typed query receipts validate Family identity and every adopted Research item.
- Conversation context is transport, not Phase 8 storage. Selected Research premises, failure
  conditions, verification tasks and concise decisions live in a bounded local working checkpoint;
  a resume packet rehydrates them after compaction without persisting hidden reasoning.
- Starter and target stages share only the base class. Community guides are candidate evidence and
  never write directly to Research or Learning Memory; current graph/corpus/mechanic evidence must
  revalidate their premises.
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
- Phase 7 raw sources are isolated per case; control state, reports, and Learning Memory persist only
  safe hashes/references and summaries.
- Phase 8 starter caches and progression manifests store only safe summaries, source hashes, typed
  query-receipt references, stage deltas, target coverage, and artifact references. Page prose,
  full URLs, and milestone XML remain outside them.
- Phase 8 working checkpoints are local and bounded. They store selected evidence applications and
  unresolved items, use an independent context revision, and never enter Research or Learning
  Memory. MCP telemetry stores sizes and timings, never argument/result content.
- Long-term knowledge must be clean, versioned, evidence-backed, and copy-safe.
- User-data/runtime directories may hold local state; repository docs must describe contracts, not
  accidental local artifacts.
