# CandleViewer

**The open-source charting platform for traders who outgrew TradingView.**

CandleViewer is a modern, high-performance web (and eventually desktop/PWA) charting platform combining a GPU-accelerated chart engine, multi-source real-time market data, a rich indicator and custom scripting ecosystem, professional drawing tools, alerts, backtesting/replay, and real-time collaboration — fully open source.

> **Status: Pre-alpha.** APIs, architecture, and even the technology stack are still being decided. Expect breaking changes daily. Not ready for production use. Contributions and design input very welcome!

---

## Why CandleViewer instead of TradingView?

|               | TradingView                                | CandleViewer (goal)                                                                 |
| ------------- | ------------------------------------------ | ----------------------------------------------------------------------------------- |
| Source        | Closed, proprietary                        | 100% open source (MIT)                                                              |
| Rendering     | Fast, but capped feature set on free tiers | GPU-accelerated engine targeting 1M+ candles at 60fps, no paywalls on core charting |
| Data          | TradingView-curated feeds only             | Bring-your-own-adapter multi-source feeds (crypto/stocks/forex), self-hostable      |
| Scripting     | Pine Script (closed, rate-limited)         | Open scripting language, sandboxed WASM execution, no arbitrary limits              |
| Backtesting   | Strategy Tester (limited history, slow)    | Fast historical simulation engine + tick-level replay, walk-forward optimization    |
| Collaboration | Limited chart sharing                      | Real-time multi-user co-editing, embeddable widgets, public share links             |
| Extensibility | Closed plugin ecosystem                    | Fully pluggable indicators, adapters, and scripts; community marketplace            |
| Self-hosting  | Not possible                               | First-class support — run your own instance, own your data                          |

We're not just cloning TradingView — we intend to **exceed it** on performance, openness, and extensibility.

---

## Feature Roadmap

| Milestone                                | Focus                     | Key Deliverables                                                                                                                |
| ---------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **M0 — Foundation**                      | Repo & infra bootstrap    | Monorepo scaffolding, CI/CD, MIT license, CONTRIBUTING, ADR-0001 stack decision                                                 |
| **M1 — Core Charting Engine**            | Rendering core            | WebGL/Canvas engine, viewport & coordinate system, candlestick renderer, time/price axes, crosshair, auth scaffolding           |
| **M2 — Data Feeds & Indicators**         | Data + analysis           | Multi-source real-time data adapters (crypto/stocks/forex), TimescaleDB storage, 50+ built-in indicators, streaming computation |
| **M3 — Drawing Tools & Alerts**          | Annotation + notification | 20+ drawing tools, snapping/magnet mode, server-side alert engine, multi-channel notifications                                  |
| **M4 — Backtesting & Scripting**         | Strategy development      | Historical simulation & replay engine, performance analytics, custom scripting language with sandboxed execution                |
| **M5 — Collaboration, Layouts & Polish** | UX + real-time collab     | Multi-chart layouts, watchlists, real-time co-editing, shareable/embeddable charts, PWA, accessibility polish                   |

---

## Proposed Architecture (subject to change — see ADR-0001)

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Web)                        │
│  React / Next.js UI  +  Custom WebGL/Canvas Chart Engine      │
│  Watchlists · Drawing Tools · Scripting Editor · Layouts      │
└───────────────────────────▲───────────────────────────────────┘
                            │ WebSocket / REST
┌───────────────────────────┴───────────────────────────────────┐
│                        Backend Services                       │
│  Node or Rust services:                                       │
│   - Data Ingestion & Normalization (crypto/stocks/forex)       │
│   - Alert Evaluation Engine                                   │
│   - Backtesting/Replay Engine                                 │
│   - Scripting Sandbox (WASM)                                  │
│   - Auth & Account Sync                                       │
│   - Collaboration (real-time sync, CRDT)                       │
└───────────────────────────▲───────────────────────────────────┘
                            │
┌───────────────────────────┴───────────────────────────────────┐
│                        Data Layer                              │
│   Postgres + TimescaleDB (OHLCV, ticks, user data)             │
│   Redis / message queue for real-time fan-out                  │
└─────────────────────────────────────────────────────────────┘
```

This stack is a **starting proposal, not a final decision** — see `docs/adr/0001-stack-decision.md` (tracked in M0) for the open questions and rationale as they're resolved. Where possible, issues in this repo are written to remain stack-agnostic until an ADR is merged.

---

## Monorepo Structure (proposed)

```
candleviewer/
├── apps/
│   ├── web/              # Frontend app (Next.js)
│   └── desktop/          # Future Electron/Tauri wrapper
├── packages/
│   ├── chart-engine/     # Core rendering engine
│   ├── indicators/       # Indicator library
│   ├── scripting/        # Custom scripting language + sandbox
│   └── ui/               # Shared UI components
├── services/
│   ├── data-ingestion/
│   ├── alerts/
│   ├── backtesting/
│   └── collaboration/
├── docs/
│   └── adr/              # Architecture decision records
└── infra/                # IaC, Docker, CI configs
```

---

## Getting Started

This is the working onboarding path (E02-T12); the deeper reference for commands is
`AGENTS.md` §4 and for process is `CONTRIBUTING.md` — this section only links to them,
it does not duplicate them (`CONSTITUTION.md` C-16.5).

### Prerequisites (pinned minimums)

| Tool                     | Minimum version                                        | Check                    |
| ------------------------ | ------------------------------------------------------ | ------------------------ |
| Node.js                  | 20.19.5 (Electron 45 installer needs require(esm))     | `node --version`         |
| pnpm                     | 12.5.1 (pinned via `packageManager` in `package.json`) | `pnpm --version`         |
| Python                   | 3.12                                                   | `python --version`       |
| uv                       | latest                                                 | `uv --version`           |
| Docker (with compose v2) | any recent Docker Desktop / Docker Engine              | `docker compose version` |

Target environment is **WSL Ubuntu** with Docker Desktop's WSL2 integration enabled
(`docs/plan/20-architecture.md` §5). Clone the repo **inside the WSL filesystem**
(e.g. `~/code/CandleViewer`), not under `/mnt/c/...` — see Troubleshooting below.

### Clone → install → verify → up → dev

```bash
git clone <repo-url> && cd CandleViewer
pnpm install
uv sync --frozen --project services/api
pnpm verify          # the full local gate (lint/typecheck/tests/arch) — AGENTS.md §4
make up              # docker compose stack (Postgres, QuestDB, API, Prometheus, Grafana)
make dev             # the full loop: stack + api in CV_FEED=synthetic + web dev server
```

`make dev` never needs Bybit credentials: the api starts with `CV_FEED=synthetic`
(the default), which replays a small committed sample from `packages/fixtures/raw/`
as normalised `Trade`/`Ticker` events — see `services/api/candleviewer/ingestion/`.
Setting `CV_FEED=live` without `CV_BYBIT_API_KEY`/`CV_BYBIT_API_SECRET` fails fast
with a clear error rather than starting half-configured.

Teardown: `make dev-down` (equivalent to `make down`) stops containers but keeps
volumes; `make reset` also drops volumes for a clean-state rebuild.

New joiner? Work through `docs/plan/qa/first-hour-checklist.md` — it is the
concrete acceptance evidence for this section (validated by a non-author, per
E02-Q02's charter).

### Troubleshooting

- **WSL filesystem vs `/mnt/c`**: cloning under `/mnt/c/...` makes every file
  operation cross the 9p filesystem boundary, which is dramatically slower and
  can surface stale-file/permission errors under `docker compose`. Clone inside
  the WSL filesystem (`~/code/...`).
- **Port conflicts**: `make up`'s healthcheck (`infra/scripts/healthcheck.sh`)
  will hang if `5432`, `8000`, `8812`/`9009`, `9090` or `3000` are already bound
  by another local service — `docker compose -f infra/docker-compose.dev.yml ps`
  and stop the conflicting process, or override the port via the relevant
  `CV_*`/`*_PORT` environment variable.
- **Docker Desktop integration**: on WSL Ubuntu, enable _Settings → Resources →
  WSL Integration_ for your distro in Docker Desktop; without it, `docker` and
  `docker compose` are not on `PATH` inside WSL.
- **`CV_FEED=live` refuses to start**: this is by design — see the sample loop
  above. Use `CV_FEED=synthetic` (the default) unless you have real, provisioned
  Bybit credentials.

---

## Contributing

We'd love your help! CandleViewer is early-stage, which means there's a lot of room to shape core architecture.

- Read `CONTRIBUTING.md` before opening a PR.
- Check issues labeled `good-first-issue` and `help-wanted` to get started.
- Larger design discussions happen via ADRs in `docs/adr/` and GitHub Discussions.
- Please be respectful and constructive — see `CODE_OF_CONDUCT.md`.

---

## License

CandleViewer is licensed under the [MIT License](LICENSE).
