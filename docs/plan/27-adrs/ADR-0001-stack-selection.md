# ADR-0001 — Technology stack selection

- Status: **decided**
- Date: 2026-09-14
- Deciders: Owner (basiltt), Architect, Backend lead, Frontend lead
- Consulted: `docs/research/10-frontend-tech.md`, `docs/research/11-backend-tech.md`, `docs/research/22-architecture-options.md` §12, `docs/research/24-owner-decisions.md`
- Supersedes: —

## Context and problem statement

CandleViewer is a private, self-hosted, single-owner-plus-a-few-managers trading terminal for Bybit USDT linear perpetuals. It must deliver TradingView-grade charting, DeepCharts-grade order-flow visibility, a full execution loop with multi-account fan-out, a rule engine, paper trading, replay, journal and admin — all within a ~15-person team on 2-week sprints, self-hosted on WSL today and a small VPS later. We must choose the language/runtime/framework baseline for the client and the server, and we must choose it once, because every other decision in this planning set depends on it.

## Decision drivers

- Owner has locked React + TypeScript on the client and Python on the server (planning brief, "Locked decisions").
- The backend is a real-time ingestion and execution system: WS fan-out, book reconstruction, order-flow aggregation, OMS correctness under reconnects.
- Team skills: 5 backend engineers (Python), 5 frontend engineers (React/TS).
- Anti-lock-in and zero recurring licence cost are explicit project values.
- The deployment target is a single box; operational simplicity outweighs horizontal scalability at this scale.
- The protocol must stay client-agnostic so a mobile client can be added later without backend rework.

## Considered options

1. **React + TypeScript web app, Electron shell, Python 3.12 asyncio (FastAPI/Starlette) modular monolith** — the locked baseline.
2. **React + TypeScript web app, Rust backend (axum + tokio)** — best raw performance for book/aggregation hot paths.
3. **React + TypeScript web app, Node/TypeScript backend** — one language across the stack.
4. **Go backend** — good concurrency story, simple deployment.

## Decision outcome

**Chosen: option 1** — React 18 + TypeScript 5 (Vite) on the client, packaged by an Electron shell; Python 3.12 with asyncio (uvloop), FastAPI/Starlette and a modular-monolith internal structure on the server.

Concrete stack:

| Layer | Choice |
|---|---|
| Web app | React 18, TypeScript 5, Vite, Zustand (UI state), Jotai (high-frequency per-symbol atoms), TanStack Query (REST), Dockview (layouts), Radix + Tailwind, React Flow (rule node-graph editor) |
| Chart | Custom WebGL2 engine in `packages/chart-engine` (ADR-0002) |
| Desktop | Electron with hardened defaults (ADR-0011 keeps the Tauri comparison open) |
| API | FastAPI + Starlette on uvicorn with uvloop, pydantic v2 |
| Async | Single event loop, structured concurrency via `asyncio.TaskGroup` |
| Exchange I/O | Hand-built asyncio WS client (`websockets`) + `httpx` REST, behind an adapter port (ADR-0004, and `20-architecture.md` §9) |
| Data | `numpy` for vectorised aggregation; SQLAlchemy 2.0 + Alembic for Postgres; QuestDB ILP client; DuckDB for cold analytics |
| Packaging | `uv` + Hatch (Python), pnpm + Turborepo (JS), docker compose (runtime) |

### Amendment 2026-11-02 — the web app's state and data layer as built

The "Web app" row above named Zustand (UI state), Jotai (high-frequency atoms) and TanStack Query (REST);
`AGENTS.md` §5.1 and `.claude/rules/30-frontend-react.md` added RxJS stream coalescing. The application
adopted none of them. As of `main` on 2026-11-02 `apps/web`'s runtime dependencies are `react`, `react-dom`
and `react-router` only; its stores are plain external stores read through React's `useSyncExternalStore`
(21 files call the hook — stores, hooks and components) with selectors and no stored derived state; WS
ingestion is coalesced by the transport layer (rAF / timer batches) before it touches React; REST reads are
per-feature typed fetch helpers (for example `features/auth/authApi.ts`) over `packages/protocol`'s generated
types, with `react-router` loaders used for guards and redirects. E22-S01 (#5288) recorded the choice in
code as its local constraint "C-69: no Jotai, RxJS or Zustand in `apps/web`" (a BQ-list id, not a
Constitution rule); the delivery orchestrator kept it for new stores on E14-T02 (#400 BQ-01, decided
2026-11-02 under the owner's 2026-10-29 delegation; the owner's veto window is open on #2701). **Rule from
this amendment:** new `apps/web` state builds on `useSyncExternalStore`; adding Zustand, Jotai, RxJS or
TanStack Query (or any state / data library) needs an amendment to this ADR under the dependency policy
(C-12.3: justification, allowlisted licence, CODEOWNER review), never a per-feature `package.json` change.
Status of the decision is unchanged; the plan and agent documents that name the web app's state layer
point here (C-16.5).

### Consequences

Positive:
- Matches the team's actual skill distribution, so velocity is predictable.
- FastAPI + pydantic v2 gives an OpenAPI document for free, which generates `packages/protocol` types and enforces the client-agnostic contract (planning brief P1).
- One process, one loop: no distributed-systems complexity for a single-box deployment.
- Zero licence cost, no vendor approval gates.

Negative / risks:
- Python's GIL bounds single-loop throughput. Mitigated by a pre-designed escape-hatch ladder (`20-architecture.md` §4.1 rule 4): `numpy` vectorisation → symbol-sharded `ProcessPoolExecutor` → Rust/PyO3 extension for book application and footprint binning. Free-threaded CPython is explicitly not relied upon.
- No mature async Python Bybit client with the reconnect/resubscribe ergonomics we need; we must build it (validated by spike S3, ADR-0006).
- Electron's memory footprint is larger than Tauri's; accepted for predictable GPU behaviour (ADR-0011).

### Why not the alternatives

- **Rust backend**: the best technical fit for the hot path, but we have zero Rust-capable headcount allocated and it would halve delivery velocity across 5 backend engineers. We keep the door open at the *module* level instead (PyO3 extension) rather than betting the whole service.
- **Node/TypeScript backend**: single language is attractive, but the numerical/aggregation ecosystem is far weaker than `numpy`/`polars`, and the team's backend engineers are Python engineers.
- **Go**: good runtime properties, but again no allocated headcount, and the scientific/aggregation ecosystem is the weakest of the four.

## Validation

- Spike S3 (Bybit private WS client reliability) must pass a 24 h soak with zero missed executions before R3.
- Event-loop lag SLO (p99 ≤ 50 ms) is a required load-test gate in `06-performance-and-load-standard.md`; breaching it triggers the escape-hatch decision procedure rather than a stack change.
