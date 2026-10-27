# 31 - Sprint Plan (S01-S26)

Date: 2026-09-15 | Owner: basiltt | Status: **operational plan derived from `30-release-roadmap.md` (locked) and `backlog/all-tickets.json` (50 epic files, 1327 child tickets)**
Companions: `30-release-roadmap.md` (train sequencing, epic register, dependency graph), `02-definition-of-ready-done.md` (gates every ticket below must pass), `backlog/_reconciliation-report.md` (validator output), `32-risk-register.md`, `33-raci.md`, `07-release-and-prr.md` (PRR & Live gate).

Scope (inherited, unchanged): **web app only** - React + TypeScript + custom WebGL chart engine, Electron desktop shell; owner/admin functions are RBAC-gated routes **inside** the web app; **no Android**, **no separate admin app**; **Bybit v5 USDT linear perpetuals only**.

> **What this document is.** `30-release-roadmap.md` decides *which train* each epic rides and *may not be changed here*. This document decides *which tickets are in which sprint*, who has capacity for them, what must be demoed, and how to re-plan when reality disagrees. Where the two disagree, the roadmap wins on sequencing and dates; this document wins on ticket-level allocation.

---

## 1. How to read this plan

| Constant | Value | Source |
|---|---|---|
| Sprint length | **1 week**, Fri -> Thu (AI-driven cadence, owner decision 2026-09-24) | roadmap 1, `calendar_cv.py` |
| S01 start / S26 end | **2026-09-25** -> **2027-03-25** | roadmap 1.1 |
| Engineering capacity | **90 pts/sprint** (S07 = 45, reduced) | roadmap 1.1 |
| Engineering pool | BE 40 / FE 40 / QA 6 / DevSecOps 2 / Security 2 pts | `01-sdlc-and-branching.md` 11.3 |
| Separate discipline pools | Design ~60, QA ~45, Security ~20 pts/sprint | section 2.2 |
| Estimation scale | Fibonacci 1-2-3-5-8; >8 must split | DoR |
| Design-ahead rule | design Done **>=2 sprints** before its FE story enters a sprint | DoR, roadmap 11.3 rule 1 |
| Tickets planned here | **1327** child tickets under **50** epic files | `backlog/all-tickets.json` |
| Points planned here | eng **1986** / design **918** / QA **802** / security **356** = **4062** total | backlog rollup |
| Engineering capacity over 26 sprints | **2295** pts; planned **1986** (**87%**) | section 2.3 |

### 1.1 Ticket key grammar

Every child ticket key is `E<nn>-<D><nn>` where the discipline letter routes it to a pool and a board swimlane:

| Letter | Kind | Pool | Counts against the 90-pt engineering capacity? |
|---|---|---|---|
| `S` | Story | Engineering | **Yes** |
| `T` | Task | Engineering | **Yes** |
| `K` | Spike | Engineering | **Yes** |
| `C` | Chore | Engineering | **Yes** |
| `D` | Design task | Design org | No - separate pool, runs 2 sprints ahead |
| `Q` | QA/test task | QA/SDET | No - separate pool |
| `X` | Security task | Security engineer | No - separate pool |

This split is the single most important thing to understand about the tables below: **a sprint at 90/90 engineering points can still be over-committed** if its QA or design column exceeds that pool. S13 and S19 are exactly this failure mode.

---

## 2. Capacity model

### 2.1 Engineering (the 90-pt line)

The 90 pts/sprint is the **engineering** number from `01-sdlc-and-branching.md` 11.3 and decomposes as BE 40 / FE 40 / QA 6 / DevSecOps 2 / Security 2. The QA, DevSecOps and Security slivers inside that 90 are for *engineering work done by those roles* (e.g. a DevSecOps pipeline task), not for the QA/design/security ticket pools below.

### 2.2 The other three pools

The org described in `00-planning-brief.md` has a large design organisation, 2 QA/SDET, 1 DevSecOps and 1 Security engineer. Their ticket output is tracked in the `D`/`Q`/`X` columns and sized as:

| Pool | Assumed steady-state capacity | Basis | Sprints that exceed it |
|---|---|---|---|
| Design | ~60 pts/sprint | large design org (CDO, UX research, product designers, DS team, motion, a11y) | S01, S02, S04, S05, S15, S23 |
| QA / SDET | ~45 pts/sprint | 2 QA/SDET at ~22 pts each | S04, S08, S09, S12, S13, S18, S19 |
| Security | ~20 pts/sprint | 1 Security engineer + DevSecOps overlap | S04, S15, S19 |

> **These capacities are assumptions, not measurements.** They are the first thing to recalibrate after S02 and S04 (section 31.2). The `Flag` column in every sprint table below is computed against them.

### 2.3 Master capacity table (all 26 sprints)

| Sprint | Dates | Train | Eng | Cap | Head | Design | QA | Sec | Total | Flag |
|---|---|---|---|---|---|---|---|---|---|---|
| **S01** | 2026-09-25 -> 2026-10-01 | R0 | 90 | 90 | +0 | 63 | 1 | 8 | 162 | DES +3 |
| **S02** | 2026-10-02 -> 2026-10-08 | R0 | 90 | 90 | +0 | 98 | 6 | 15 | 209 | DES +38 |
| **S03** | 2026-10-09 -> 2026-10-15 | R0 | 87 | 90 | +3 | 49 | 17 | 7 | 160 | ok |
| **S04** | 2026-10-16 -> 2026-10-22 | R0 | 88 | 90 | +2 | 81 | 62 | 26 | 257 | DES +21, **QA +17**, SEC +6 |
| **S05** | 2026-10-23 -> 2026-10-29 | R1 | 90 | 90 | +0 | 80 | 0 | 9 | 179 | DES +20 |
| **S06** | 2026-10-30 -> 2026-11-05 | R1 | 90 | 90 | +0 | 10 | 17 | 8 | 125 | ok |
| **S07** | 2026-11-06 -> 2026-11-12 | R1 | 47 | 45 | -2 | 18 | 32 | 9 | 106 | **ENG -2** |
| **S08** | 2026-11-13 -> 2026-11-19 | R1 | 90 | 90 | +0 | 59 | 59 | 18 | 226 | **QA +14** |
| **S09** | 2026-11-20 -> 2026-11-26 | R1 | 90 | 90 | +0 | 25 | 69 | 19 | 203 | **QA +24** |
| **S10** | 2026-11-27 -> 2026-12-03 | R2 | 89 | 90 | +1 | 23 | 2 | 16 | 130 | ok |
| **S11** | 2026-12-04 -> 2026-12-10 | R2 | 89 | 90 | +1 | 24 | 13 | 8 | 134 | ok |
| **S12** | 2026-12-11 -> 2026-12-17 | R2 | 89 | 90 | +1 | 18 | 55 | 11 | 173 | **QA +10** |
| **S13** | 2026-12-18 -> 2026-12-24 | R2 | 90 | 90 | +0 | 52 | 83 | 19 | 244 | **QA +38** |
| **S14** | 2026-12-25 -> 2026-12-31 | R3 | 88 | 90 | +2 | 58 | 6 | 12 | 164 | ok |
| **S15** | 2027-01-01 -> 2027-01-07 | R3 | 89 | 90 | +1 | 66 | 20 | 21 | 196 | DES +6, SEC +1 |
| **S16** | 2027-01-08 -> 2027-01-14 | R3 | 89 | 90 | +1 | 35 | 32 | 13 | 169 | ok |
| **S17** | 2027-01-15 -> 2027-01-21 | R3 | 89 | 90 | +1 | 20 | 35 | 16 | 160 | ok |
| **S18** | 2027-01-22 -> 2027-01-28 | R3 | 88 | 90 | +2 | 15 | 46 | 13 | 162 | **QA +1** |
| **S19** | 2027-01-29 -> 2027-02-04 | R3 | 45 | 90 | +45 | 31 | 113 | 30 | 219 | **QA +68**, SEC +10 |
| **S20** | 2027-02-05 -> 2027-02-11 | R4 | 87 | 90 | +3 | 6 | 11 | 12 | 116 | ok |
| **S21** | 2027-02-12 -> 2027-02-18 | R4 | 56 | 90 | +34 | 8 | 22 | 16 | 102 | ok |
| **S22** | 2027-02-19 -> 2027-02-25 | R4 | 11 | 90 | +79 | 2 | 9 | 13 | 35 | ok |
| **S23** | 2027-02-26 -> 2027-03-04 | R5 | 87 | 90 | +3 | 66 | 26 | 9 | 188 | DES +6 |
| **S24** | 2027-03-05 -> 2027-03-11 | R5 | 62 | 90 | +28 | 0 | 20 | 5 | 87 | ok |
| **S25** | 2027-03-12 -> 2027-03-18 | R5 | 48 | 90 | +42 | 5 | 30 | 9 | 92 | ok |
| **S26** | 2027-03-19 -> 2027-03-25 | R5 | 5 | 90 | +85 | 6 | 16 | 11 | 38 | ok |
| | | **Total** | **1963** | **2295** | **+332** | **918** | **802** | **353** | **4036** | |

Unscheduled (`Backlog`, section 32.2): **11** tickets, 46 pts - not in any row above.

**Three structural observations, all of which drive section 31:**

1. **Engineering is 86% loaded across the horizon (1963 of 2295 pts incl. 5 upstream-coordination pts; post-adoption re-plan 2026-09-24).** That is not free slack - it is the roadmap 3.1 named reserves (90 pen-test remediation + 140 defect/polish) plus the per-train buffer. Treat the apparent headroom as already spoken for.
2. **The load is violently uneven.** S26 carries 5 eng pts; S01–S06 and S08–S09 sit at the cap. Sprints sitting at or within 1 pt of the cap have zero room for carry-in, so any spill immediately over-commits them.
3. **QA is the real constraint, not engineering.** QA exceeds its pool in 7 sprints, peaking at 113 pts in S19 - 2.5x capacity. Engineering exceeds its cap only in S07 (+2, holiday; pre-accepted) after the 2026-09-24 post-adoption re-plan.

---

# R0 - Foundations

| | |
|---|---|
| Sprints | S01-S04 |
| Dates | 2026-09-25 -> 2026-10-22 |
| Version at cut | `0.1.0` |
| Deploys to | dev continuous, staging smoke only |
| Gate | PRR-lite |
| Eng pts in backlog | 355 of 360 capacity (99%) |
| All-discipline pts | 796 |

Nothing in R0 is user-visible. Its entire job is to make every later sprint *possible*: a governed repo, a building monorepo, a deploying pipeline, a measured engine decision, a wired data tier, a design system, an ingestion skeleton and working auth. The two spikes (E06 engine, E07 storage) are the highest-information work in the whole plan - they either confirm the architecture or invalidate a year of estimates.

---

## 3. S01 - 2026-09-25 -> 2026-10-01 (R0)

### 3.1 Sprint goal(s)

- **Make the repo governable before any feature code exists.** Ratify `CONSTITUTION.md`, enforce `CODEOWNERS` over every path, and prove a 2-approval PR gate is unbypassable (E01).
- Stand up the monorepo skeleton and toolchain so every later epic has a place to land (E02).
- Open the CI spine: lint/typecheck/unit on every PR, merge queue configured (E03).
- Start the **chart-engine spike** on day 1 - it is the longest pole in the plan and its go/no-go is 2026-10-08 (E06).
- **Design is over pool: 63 pts vs 60 (+3).**

### 3.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 90 | 90 | +0 | ok |
| Design (D) | 63 | 60 | -3 | **OVER** |
| QA (Q) | 1 | 45 | +44 | ok |
| Security (X) | 8 | 20 | +12 | ok |
| **Total** | **162** | **215** | **+53** | |

### 3.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E02** | Monorepo scaffold & toolchain | Platform & DevSecOps | 35 | 14 |
| **E03** | CI/CD pipeline & environments | Platform & DevSecOps | 27 | 9 |
| **E08** | Bybit adapter & ingestion skeleton | Data & Feeds (BE-Feeds) | 27 | 8 |
| **E09** | Auth, sessions, 2FA & RBAC | Accounts & Security (BE-Sec) | 24 | 7 |
| **E01** | Governance & repo constitution: make CandleViewer governable from commit #1 | Governance & Docs | 19 | 12 |
| **E05** | Design system v0 - tokens, primitives, Storybook | Design System | 9 | 3 |
| **E06** | Chart-engine spike & ADR (WebGL2 feasibility, Electron vs Tauri) | Chart Engine (FE-Engine) | 8 | 5 |
| **E04** | Observability baseline: structured logs, metrics, health, dashboards, alerting | Platform & DevSecOps | 6 | 2 |
| **E12** | Bar builders & series rendering (time/tick/volume/range/renko) | Data & Feeds (BE-Feeds) | 3 | 1 |
| **E07** | Storage spike & data-tier wiring (QuestDB / Parquet+DuckDB / Postgres) | Data & Feeds (BE-Feeds) | 2 | 1 |
| **E10** | App shell, routing & Electron wrapper | App & Charting UI (FE-App) | 2 | 1 |


**Statechart lane:** none this sprint.

### 3.4 Tickets (63)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E01-D01` | Design the contributor information architecture and issue-form field set | Task | 1 | docs |  |
| `E01-K01` | Spike: GitHub Projects v2 + Actions automation capability and limits | Spike | 1 | docs |  |
| `E01-Q01` | Author and execute the governance conformance test plan and exploratory charter | Task | 1 | docs | `E01-T01`, `E01-T08` |
| `E01-T01` | Ratify CONSTITUTION.md v1.0.0 and make rule references machine-verified | Task | 2 | docs |  |
| `E01-T02` | Reconcile CONTRIBUTING, CODE_OF_CONDUCT and AGENTS with the constitution | Task | 1 | docs | `E01-T01` |
| `E01-T03` | Finalise SECURITY.md: reporting, supported versions and disclosure timeline | Task | 1 | docs | `E01-T01` |
| `E01-T04` | Make .github/CODEOWNERS cover every path and prove it with a checker | Task | 1 | docs | `E01-T01` |
| `E01-T05` | Refresh PR template and issue forms to the ticket taxonomy | Task | 2 | docs | `E01-T01`, `E01-D01` |
| `E01-T06` | Publish the backlog ticket JSON schema and validate every backlog file | Task | 2 | docs | `E01-T01` |
| `E01-T07` | Implement board automation: Kind-label sync and QA/security/a11y close guards | Task | 3 | docs | `E01-K01`, `E01-T05`, `E01-T06`, `E01-X01` |
| `E01-T08` | Configure branch protection and merge queue as reviewable code | Task | 2 | docs | `E01-T01`, `E01-T04`, `E01-X01` |
| `E01-X01` | STRIDE threat model for the repository, CI and board administration surface | Task | 2 | docs |  |
| `E02-D01` | Design: define the design-token → code handoff contract for the packages/ui build | Task | 2 | web |  |
| `E02-K01` | Spike: pnpm+Turborepo vs Nx and uv vs Poetry for the CandleViewer monorepo | Spike | 2 | infra |  |
| `E02-T01` | Create root pnpm workspace, Turborepo task graph and shared config package | Task | 5 | infra | `E01`, `E02-K01` |
| `E02-T02` | Create services/api Python workspace with uv, ruff, black, mypy strict and pytest | Task | 2 | infra | `E02-K01` |
| `E02-T03` | Scaffold packages chart-engine, ui, protocol and fixtures with build and test wiring | Task | 3 | infra | `E02-T01`, `E02-D01` |
| `E02-T04` | Scaffold apps/web (Vite+React+TS) and apps/desktop (Electron shell) skeletons | Task | 2 | web | `E02-T03` |
| `E02-T05` | Create services/api module tree M1-M24, composition root and typed settings | Task | 3 | api | `E02-T02` |
| `E02-T06` | Encode module boundaries as import-linter and dependency-cruiser contracts | Task | 5 | infra | `E02-T05`, `E02-T03` |
| `E02-T07` | Add commitlint, husky, lint-staged and .editorconfig with conventional-commit enforcement | Task | 1 | infra | `E02-T01` |
| `E02-T08` | Author docker compose stack for WSL Ubuntu (api, postgres, questdb, prometheus, grafana, minio) | Task | 2 | infra | `E02-T05`, `E02-T02` |
| `E02-T09` | Build packages/protocol code generation from OpenAPI + WS schema with staleness gate | Task | 3 | api | `E02-T03`, `E02-T05` |
| `E02-T11` | Merge ADR-0016 monorepo tooling and reconcile AGENTS.md §4 with the shipped task graph | Task | 1 | docs | `E02-T06`, `E02-T09` |
| `E02-T12` | Write repository onboarding docs and the make dev synthetic-feed developer loop | Task | 2 | docs | `E02-T08`, `E02-T04` |
| `E02-X01` | Security: STRIDE threat model for the monorepo supply chain and local dev stack | Task | 2 | infra | `E02-T01` |
| `E03-T01` | Build the Actions PR skeleton with path filters and a checks resolver | Task | 3 | infra | `E02` |
| `E03-T02` | Implement the JavaScript/TypeScript CI lane with Turborepo remote caching | Task | 3 | infra | `E03-T01`, `E02` |
| `E03-T03` | Implement the Python CI lane with ruff, mypy strict, pytest and uv caching | Task | 3 | infra | `E03-T01`, `E02` |
| `E03-T04` | Enforce coverage thresholds as a blocking CI gate | Task | 2 | infra | `E03-T02`, `E03-T03` |
| `E03-T05` | Add the generated-code freshness gate for packages/protocol | Task | 2 | infra | `E03-T01`, `E02` |
| `E03-T06` | Wire contract, integration, E2E and axe-core jobs into the PR pipeline | Task | 3 | infra | `E03-T02`, `E03-T03` |
| `E03-T07` | Build the SAST, SCA, secrets, licence and container scanning lane | Task | 5 | infra | `E03-T01`, `E03-X01` |
| `E03-T10` | Add the Alembic migration job with single-head, drift and expand/contract checks | Task | 3 | infra | `E03-T03` |
| `E03-X01` | Produce the STRIDE threat model for the CI/CD supply chain (mandatory R0 gate) | Task | 3 | infra | `E01` |
| `E04-D01` | Design the system-health, incident-log and degraded-state surfaces (SCR-143, SCR-144, SCR-152, SCR-156) | Task | 5 | web | `E05-D01` |
| `E04-K01` | Measure instrumentation overhead: metrics, structlog and OTel on the hot paths | Spike | 1 | infra | `E03` |
| `E05-D01` | Build Figma Foundations file: token variables for 3 themes x 2 densities | Task | 5 | web | `E05-D07` |
| `E05-D07` | UX research: density, numeric legibility and CVD palette validation | Task | 3 | web |  |
| `E05-K01` | Select visual-regression tooling for theme x density snapshot coverage | Spike | 1 | web |  |
| `E06-D01` | UX research: footprint LOD legibility thresholds and non-colour encodings | Task | 2 | chart-engine | `E02` |
| `E06-D02` | Design SCR-046 diagnostics overlay and heatmap colour/legend convention | Task | 1 | chart-engine | `E06-K01` |
| `E06-K01` | Build M0 benchmark harness and deterministic seeded fixture generator | Spike | 3 | chart-engine | `E02` |
| `E06-K02` | Prototype scene A: 100k-bar model, visible-window draw and LOD ladder | Spike | 1 | chart-engine | `E06-K01` |
| `E06-X01` | STRIDE model of the engine and desktop-shell boundary; hardening checklist | Task | 1 | chart-engine | `E01` |
| `E07-T01` | Create M10 storage package: repository Protocols, AppContext wiring, in-memory fakes, import-linter contract | Task | 2 | infra | `E02-T05`, `E02-T06` |
| `E08-D01` | UX research: how traders read staleness, gaps and resync in live data | Task | 3 | data-feeds |  |
| `E08-D02` | Wireframes: market-data connection, staleness and resync states | Task | 3 | data-feeds | `E08-D01` |
| `E08-D03` | Hi-fi: SCR-152 disconnected / reconnecting banner and per-panel treatment | Task | 5 | data-feeds | `E08-D02` |
| `E08-D04` | Design-system contribution: data-confidence tokens, states and badges | Task | 5 | data-feeds | `E08-D01`, `E08-D02` |
| `E08-D05` | Hi-fi: SCR-102 symbol search and SCR-041 quick-switcher from the catalogue | Task | 5 | data-feeds | `E08-D02`, `E08-D04` |
| `E08-K01` | Spike: book depth-tier and cadence policy (200 vs 500) under recorded load | Spike | 2 | data-feeds | `E08-T03` |
| `E08-T01` | Define ExchangeAdapter ports, capability record and internal error taxonomy | Task | 2 | data-feeds | `E02` |
| `E08-T03` | Implement the in-process topic bus with bounded queues and backpressure policy | Task | 2 | data-feeds | `E08-T01` |
| `E09-D01` | UX research: sign-in, 2FA and recovery mental models | Task | 3 | web |  |
| `E09-D02` | Wireframes: end-to-end auth, session and onboarding flow | Task | 5 | web | `E09-D01` |
| `E09-D03` | Hi-fi design: Login and TOTP challenge (SCR-001, SCR-002) | Task | 5 | web | `E09-D02` |
| `E09-D04` | Hi-fi design: TOTP enrolment, recovery codes and owner reset | Task | 5 | web | `E09-D02` |
| `E09-K01` | Spike: session, token rotation and revocation model (ADR) | Spike | 2 | auth | `E03` |
| `E09-T01` | Postgres migration: identity, sessions, MFA and RBAC tables | Task | 3 | auth | `E09-K01` |
| `E09-T04` | Tailscale-only reachability self-check and CIDR guard (US-ONB-008) | Task | 1 | infra | `E09-K01` |
| `E10-D02` | Wireframe app shell, nav rail, command surfaces and system states | Task | 2 | web | `E05-D01` |
| `E12-D01` | UX research: how traders choose, parameterise and trust non-time bars | Task | 3 | chart-engine |  |

### 3.5 Design-track deliverables due

**Design sprint D-S01** (roadmap 1.2) produces: Design-system v0 tokens, grid, density, theming, motion spec; auth/onboarding screens

> Consumed by engineering sprint **S03** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S03 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E01-D01` | Design the contributor information architecture and issue-form field set | 1 | 2026-10-01 |
| `E02-D01` | Design: define the design-token → code handoff contract for the packages/ui build | 2 | 2026-10-01 |
| `E04-D01` | Design the system-health, incident-log and degraded-state surfaces (SCR-143, SCR-144, SCR-152, SCR-156) | 5 | 2026-10-01 |
| `E05-D01` | Build Figma Foundations file: token variables for 3 themes x 2 densities | 5 | 2026-10-01 |
| `E05-D07` | UX research: density, numeric legibility and CVD palette validation | 3 | 2026-10-01 |
| `E06-D01` | UX research: footprint LOD legibility thresholds and non-colour encodings | 2 | 2026-10-01 |
| `E06-D02` | Design SCR-046 diagnostics overlay and heatmap colour/legend convention | 1 | 2026-10-01 |
| `E08-D01` | UX research: how traders read staleness, gaps and resync in live data | 3 | 2026-10-01 |
| `E08-D02` | Wireframes: market-data connection, staleness and resync states | 3 | 2026-10-01 |
| `E08-D03` | Hi-fi: SCR-152 disconnected / reconnecting banner and per-panel treatment | 5 | 2026-10-01 |
| `E08-D04` | Design-system contribution: data-confidence tokens, states and badges | 5 | 2026-10-01 |
| `E08-D05` | Hi-fi: SCR-102 symbol search and SCR-041 quick-switcher from the catalogue | 5 | 2026-10-01 |
| `E09-D01` | UX research: sign-in, 2FA and recovery mental models | 3 | 2026-10-01 |
| `E09-D02` | Wireframes: end-to-end auth, session and onboarding flow | 5 | 2026-10-01 |
| `E09-D03` | Hi-fi design: Login and TOTP challenge (SCR-001, SCR-002) | 5 | 2026-10-01 |
| `E09-D04` | Hi-fi design: TOTP enrolment, recovery codes and owner reset | 5 | 2026-10-01 |
| `E10-D02` | Wireframe app shell, nav rail, command surfaces and system states | 2 | 2026-10-01 |
| `E12-D01` | UX research: how traders choose, parameterise and trust non-time bars | 3 | 2026-10-01 |

Design total: **63 pts** across 18 tickets.

### 3.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: STRIDE R0 epics (s01, S01-S04)
- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- qa: Test framework build-out (q01, S01-S04)

**QA tickets (1 pts, 1 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E01-Q01` | Author and execute the governance conformance test plan and exploratory charter | 1 | `E01-T01`, `E01-T08` |

**Security tickets (8 pts, 4 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E01-X01` | STRIDE threat model for the repository, CI and board administration surface | 2 |  |
| `E02-X01` | Security: STRIDE threat model for the monorepo supply chain and local dev stack | 2 | `E02-T01` |
| `E03-X01` | Produce the STRIDE threat model for the CI/CD supply chain (mandatory R0 gate) | 3 | `E01` |
| `E06-X01` | STRIDE model of the engine and desktop-shell boundary; hardening checklist | 1 | `E01` |

### 3.7 Risks & dependency watch-list

- **E06 engine spike is the schedule's longest pole.** If WebGL text-LOD cannot hit the footprint density target, every R1+ frontend estimate is invalid. Fallback to Lightweight Charts is pre-decided in ADR-0006.
- E01 -> E02 -> E03 is a strict serial root: any governance slip pushes the whole plan right.
- Design track D-S01 must produce DS v0 tokens this sprint or S03's UI work has no foundation (design-ahead rule).

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S01 |
|---|---|---|
| `E02` | epic E02 (whole epic must be Done) | 7 |
| `E01` | epic E01 (whole epic must be Done) | 3 |
| `E03` | epic E03 (whole epic must be Done) | 2 |

### 3.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** A PR that lacks 2 approvals or a code-owner is demonstrably unmergeable; `make bootstrap` produces a working dev env; CI runs green on a trivial PR.

**Exit expectation:** R0 exit criterion #1 evidenced. Engine spike has a measured first data point.

### 3.9 Burn-up - R0 train

| Sprint | Eng pts this sprint | Cumulative R0 | R0 total | Remaining | % complete |
|---|---|---|---|---|---|
| S01 **<- this sprint** | 90 | 90 | 355 | 265 | 25% |
| S02 | 90 | 180 | 355 | 175 | 51% |
| S03 | 87 | 267 | 355 | 88 | 75% |
| S04 | 88 | 355 | 355 | 0 | 100% |

---

## 4. S02 - 2026-10-02 -> 2026-10-08 (R0)

### 4.1 Sprint goal(s)

- Finish the monorepo scaffold: workspaces, shared tsconfig/ruff/mypy, dependency policy, reproducible dev container (E02).
- **Engine spike go/no-go (2026-10-08)** - WebGL text-LOD and Electron-vs-Tauri measurements land as ADR-0006 (E06).
- Storage spike: prove QuestDB hot-path write rates and Parquet/DuckDB cold reads against a recorded Bybit fixture (E07).
- Observability baseline: structured logs, Prometheus scrape, first Grafana board (E04).
- **Design is over pool: 98 pts vs 60 (+38).**

### 4.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 90 | 90 | +0 | ok |
| Design (D) | 98 | 60 | -38 | **OVER** |
| QA (Q) | 6 | 45 | +39 | ok |
| Security (X) | 15 | 20 | +5 | ok |
| **Total** | **209** | **215** | **+6** | |

### 4.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E08** | Bybit adapter & ingestion skeleton | Data & Feeds (BE-Feeds) | 49 | 15 |
| **E09** | Auth, sessions, 2FA & RBAC | Accounts & Security (BE-Sec) | 34 | 9 |
| **E07** | Storage spike & data-tier wiring (QuestDB / Parquet+DuckDB / Postgres) | Data & Feeds (BE-Feeds) | 27 | 7 |
| **E04** | Observability baseline: structured logs, metrics, health, dashboards, alerting | Platform & DevSecOps | 25 | 9 |
| **E12** | Bar builders & series rendering (time/tick/volume/range/renko) | Data & Feeds (BE-Feeds) | 15 | 3 |
| **E03** | CI/CD pipeline & environments | Platform & DevSecOps | 14 | 5 |
| **E05** | Design system v0 - tokens, primitives, Storybook | Design System | 13 | 3 |
| **E02** | Monorepo scaffold & toolchain | Platform & DevSecOps | 7 | 5 |
| **E50** | xstate-statemachine adoption: factory, persistence, plugins, contract suite, catalogue | Platform & DevSecOps | 7 | 2 |
| **E10** | App shell, routing & Electron wrapper | App & Charting UI (FE-App) | 5 | 3 |
| **E01** | Governance & repo constitution: make CandleViewer governable from commit #1 | Governance & Docs | 3 | 3 |
| **E14** | Drawing tools | App & Charting UI (FE-App) | 3 | 1 |
| **E15** | Layouts & workspaces | App & Charting UI (FE-App) | 3 | 1 |
| **E06** | Chart-engine spike & ADR (WebGL2 feasibility, Electron vs Tauri) | Chart Engine (FE-Engine) | 2 | 2 |
| **E13** | Indicators framework & v1 indicator set | App & Charting UI (FE-App) | 2 | 1 |


**Statechart lane:** E50 (`E50-T11`, `E50-T57`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 4.4 Tickets (69)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E01-D02` | Design-QA and accessibility review of the built contributor surfaces | Task | 1 | docs | `E01-T05`, `E01-T07`, `E01-D01` |
| `E01-Q02` | Ship the governance regression pack as a required CI job | Task | 1 | docs | `E01-Q01`, `E01-T06`, `E01-T07` |
| `E01-X02` | Security review of governance automation: tokens, pinning, abuse cases | Task | 1 | docs | `E01-T07`, `E01-X01` |
| `E02-Q01` | QA: black-box test plan for the monorepo scaffold and toolchain | Task | 2 | infra | `E02-T10` |
| `E02-Q02` | QA: exploratory charter — clean-clone onboarding on a second engineer's machine | Task | 1 | infra | `E02-T08` |
| `E02-Q03` | QA: automated toolchain regression pack guarding the scaffold's gates | Task | 1 | infra | `E02-T10`, `E02-T06` |
| `E02-T10` | Wire coverage gates, size-limit budgets and the local `verify` gate to Constitution §9 thresholds | Task | 1 | infra | `E02-T03`, `E02-T05`, `E02-T02` |
| `E02-X02` | Security: baseline SAST, secrets, SCA and license scanning configuration for the scaffold | Task | 2 | infra | `E02-X01`, `E02-T02`, `E02-T01` |
| `E03-T08` | Build, scan, SBOM and cosign-sign container images on merge to main | Task | 3 | infra | `E03-T07` |
| `E03-T09` | Automate dev deploy and add a gated staging deploy with rollback | Task | 5 | infra | `E03-T08`, `E03-T10` |
| `E03-T11` | Add the release workflow: changelog, semver tagging and artefacts | Task | 2 | infra | `E03-T08` |
| `E03-T13` | Configure branch protection, required checks and the merge queue | Task | 2 | infra | `E03-T04`, `E03-T06`, `E03-T07`, `E01` |
| `E03-T15` | Write the CI/CD runbook and execute the ADR-0013 validation exercises | Task | 2 | infra | `E03-T13` |
| `E04-S01` | Provision six Grafana dashboards as reviewed JSON in the repository | Story | 3 | infra | `E04-T03`, `E04-T04` |
| `E04-S02` | Generate a secret-scanned, size-capped diagnostic support bundle | Story | 2 | api | `E04-T02`, `E04-T04` |
| `E04-T01` | Implement structlog JSON logging with handler-level redaction filter | Task | 3 | infra | `E03`, `E04-X01` |
| `E04-T02` | Propagate correlation ids across HTTP, WS and async tasks; runtime log-level override | Task | 3 | infra | `E04-T01` |
| `E04-T03` | Build the Prometheus registry, metrics facade and R0 metric catalogue | Task | 5 | infra | `E04-T01` |
| `E04-T04` | Implement health, readiness, build-info and the aggregated admin health report | Task | 3 | api | `E04-T03` |
| `E04-T05` | Configure Alertmanager: two-severity rule set, routing, grouping and runbook links | Task | 3 | infra | `E04-T03`, `E04-T04` |
| `E04-T07` | Write alert runbooks and reconcile ADR-0014 with the shipped observability stack | Task | 1 | docs | `E04-T05`, `E04-S01` |
| `E04-X01` | STRIDE threat model for the observability baseline | Task | 2 | infra | `E03` |
| `E05-D02` | Design Figma atoms and molecules library (CMP-001..CMP-069 v0 subset) | Task | 8 | web | `E05-D01` |
| `E05-D03` | Specify motion recipes with motion-safe/motion-reduce pairs | Task | 3 | web | `E05-D01` |
| `E05-D06` | Document handoff spec and the design-to-code token pipeline | Task | 2 | docs | `E05-D01` |
| `E06-Q01` | Validate benchmark methodology and reproducibility before ADR evidence use | Task | 1 | chart-engine | `E06-K01` |
| `E06-X02` | Pin and scan spike toolchain; enforce throwaway-code containment | Task | 1 | chart-engine | `E06-K01`, `E06-X01` |
| `E07-D01` | Define the operator content model for storage telemetry and review the StorageUsage contract | Task | 3 | api | `E07-T01` |
| `E07-K01` | Spike: benchmark QuestDB vs TimescaleDB on the three real CandleViewer query shapes | Spike | 5 | infra | `E02-T08` |
| `E07-T02` | Bootstrap Postgres relational tier: SQLAlchemy metadata, Alembic 0001/0002, naming conventions and CI migration gates | Task | 5 | infra | `E07-T01`, `E02-T08` |
| `E07-T03` | Implement QuestDB hot tier: DDL runner, batched ILP writer, PGWire reader and MarketDataRepository | Task | 5 | data-feeds | `E07-T01`, `E07-K01` |
| `E07-T04` | Implement Parquet cold tier: hot->cold exporter with checksum manifest, compactor and DuckDB view layer | Task | 5 | infra | `E07-T03` |
| `E07-T06` | Write and merge ADR-0008 hot-tier selection; reconcile ADR-0003, architecture and schema docs | Task | 1 | docs | `E07-K01` |
| `E07-X01` | Security: STRIDE threat model for recorder data & storage (Area 8) with abuse cases | Task | 3 | infra | `E02` |
| `E08-C01` | ADR-0006 exchange-adapter boundary and the market-data trust contract doc | Chore | 2 | docs | `E08-X01`, `E08-K01` |
| `E08-D06` | Hi-fi: SCR-103 symbol info drawer - contract specs and precision rules | Task | 3 | data-feeds | `E08-D04` |
| `E08-D07` | Hi-fi: SCR-100 watchlist panel & SCR-101 manager with live-column states | Task | 5 | data-feeds | `E08-D02`, `E08-D04` |
| `E08-D08` | Hi-fi: SCR-104 scanner panel - live criteria, caps and estimated metrics | Task | 3 | data-feeds | `E08-D04`, `E08-D07` |
| `E08-D09` | Hi-fi: SCR-147 exchange connectivity, rate limits and clock skew | Task | 5 | data-feeds | `E08-D02`, `E08-D04` |
| `E08-D10` | Hi-fi: SCR-151 empty/backfill states for history, coverage and gaps | Task | 3 | data-feeds | `E08-D02`, `E08-D04` |
| `E08-D11` | Motion spec: connection transitions, resync and freshness without strobing | Task | 3 | data-feeds | `E08-D03`, `E08-D04` |
| `E08-D12` | Accessibility design review of all E08 market-data surfaces | Task | 3 | data-feeds | `E08-D03`, `E08-D05`, `E08-D06`, `E08-D07`, `E08-D08`, `E08-D09`, `E08-D10`, `E08-D11` |
| `E08-D13` | Handoff pack for E08 market-data surfaces (specs, tokens, states, test ids) | Task | 3 | data-feeds | `E08-D12` |
| `E08-S01` | Instrument catalogue: fetch, cache, version-track and expose USDT perps | Story | 3 | data-feeds | `E08-T02`, `E07` |
| `E08-S02` | Precision & filter validation: one shared rounding rule for client and server | Story | 3 | data-feeds | `E08-S01` |
| `E08-S06` | Historical OHLCV backfill: paged klines, local cache and rate-limit-safe paging | Story | 3 | data-feeds | `E08-S01`, `E07` |
| `E08-S07` | Clock sync: server-time offset, drift alarm and signature-failure re-measure | Story | 2 | data-feeds | `E08-T02` |
| `E08-T02` | Bybit v5 REST client: signing, per-UID token bucket, retry and error mapping | Task | 5 | data-feeds | `E08-T01`, `E04` |
| `E08-X01` | STRIDE threat model for the exchange boundary and ingestion pipeline | Task | 3 | data-feeds | `E08-T01` |
| `E09-D05` | Hi-fi design: forced password change & password policy surface | Task | 3 | web | `E09-D02` |
| `E09-D06` | Hi-fi design: idle lock, session-expiry re-auth and step-up modals | Task | 5 | web | `E09-D02`, `E09-D01` |
| `E09-D07` | Design-system contribution: auth component band CMP-200..206 + CMP-097/098 | Task | 5 | web | `E09-D03`, `E09-D04`, `E09-D05`, `E09-D06` |
| `E09-D08` | Motion & transition spec for auth, lock and step-up surfaces | Task | 2 | web | `E09-D06` |
| `E09-D09` | Design the RBAC permission-denied pattern (owner/manager/viewer) | Task | 5 | web | `E09-D02` |
| `E09-D10` | Accessibility design review & screen-reader script for the auth band | Task | 3 | web | `E09-D03`, `E09-D04`, `E09-D05`, `E09-D06`, `E09-D09` |
| `E09-D12` | Engineering handoff pack for the auth, session and RBAC band | Task | 3 | web | `E09-D03`, `E09-D04`, `E09-D05`, `E09-D06`, `E09-D07` |
| `E09-T02` | Append-only hash-chained audit writer (M19) and audit query API | Task | 5 | auth | `E09-T01` |
| `E09-X01` | STRIDE threat model for authentication, sessions, 2FA, RBAC and audit | Task | 3 | auth | `E09-D01` |
| `E10-D03` | Produce hi-fi Figma designs for shell chrome, Electron windows and system states | Task | 3 | web | `E10-D02`, `E05-D02` |
| `E10-D04` | Specify shell motion, run the a11y design review and publish handoff | Task | 1 | web | `E10-D03` |
| `E10-K01` | Define and validate the ShellPort abstraction (Electron vs browser vs Tauri) | Spike | 1 | web | `E06-K01` |
| `E12-D02` | Wireframes: bar-mode selection, parameter entry and rebuild flow | Task | 5 | chart-engine | `E12-D01` |
| `E12-D03` | Hi-fi design: SCR-042 interval & bar-mode menu with parameter entry | Task | 5 | chart-engine | `E12-D02` |
| `E12-D06` | Hi-fi design: price series visual language (candle, bar, line, area, HA) | Task | 5 | chart-engine | `E12-D01` |
| `E13-D01` | UX research: how traders add, tune and manage indicators | Task | 2 | indicators | `E05-D01` |
| `E14-D01` | UX research: drawing, magnet and object-management mental models | Task | 3 | web |  |
| `E15-D01` | UX research: multi-pane workflows, sync groups and panel-docking mental models | Task | 3 | web |  |
| `E50-T11` | tools/lint_statecharts.py: the full standing CV lint set, JSON + AST, CI-blocking | Task | 5 | api | `E50-T57` |
| `E50-T57` | Adopt xstate-statemachine==0.9.1: dependency pin with hash lock + PEP 740 attestation verify in CI | Task | 2 | api | `E02-T02` |

### 4.5 Design-track deliverables due

**Design sprint D-S02** (roadmap 1.2) produces: Shell/navigation, workspace chrome, symbol picker, admin IA

> Consumed by engineering sprint **S04** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S04 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E01-D02` | Design-QA and accessibility review of the built contributor surfaces | 1 | 2026-10-08 |
| `E05-D02` | Design Figma atoms and molecules library (CMP-001..CMP-069 v0 subset) | 8 | 2026-10-08 |
| `E05-D03` | Specify motion recipes with motion-safe/motion-reduce pairs | 3 | 2026-10-08 |
| `E05-D06` | Document handoff spec and the design-to-code token pipeline | 2 | 2026-10-08 |
| `E07-D01` | Define the operator content model for storage telemetry and review the StorageUsage contract | 3 | 2026-10-08 |
| `E08-D06` | Hi-fi: SCR-103 symbol info drawer - contract specs and precision rules | 3 | 2026-10-08 |
| `E08-D07` | Hi-fi: SCR-100 watchlist panel & SCR-101 manager with live-column states | 5 | 2026-10-08 |
| `E08-D08` | Hi-fi: SCR-104 scanner panel - live criteria, caps and estimated metrics | 3 | 2026-10-08 |
| `E08-D09` | Hi-fi: SCR-147 exchange connectivity, rate limits and clock skew | 5 | 2026-10-08 |
| `E08-D10` | Hi-fi: SCR-151 empty/backfill states for history, coverage and gaps | 3 | 2026-10-08 |
| `E08-D11` | Motion spec: connection transitions, resync and freshness without strobing | 3 | 2026-10-08 |
| `E08-D12` | Accessibility design review of all E08 market-data surfaces | 3 | 2026-10-08 |
| `E08-D13` | Handoff pack for E08 market-data surfaces (specs, tokens, states, test ids) | 3 | 2026-10-08 |
| `E09-D05` | Hi-fi design: forced password change & password policy surface | 3 | 2026-10-08 |
| `E09-D06` | Hi-fi design: idle lock, session-expiry re-auth and step-up modals | 5 | 2026-10-08 |
| `E09-D07` | Design-system contribution: auth component band CMP-200..206 + CMP-097/098 | 5 | 2026-10-08 |
| `E09-D08` | Motion & transition spec for auth, lock and step-up surfaces | 2 | 2026-10-08 |
| `E09-D09` | Design the RBAC permission-denied pattern (owner/manager/viewer) | 5 | 2026-10-08 |
| `E09-D10` | Accessibility design review & screen-reader script for the auth band | 3 | 2026-10-08 |
| `E09-D12` | Engineering handoff pack for the auth, session and RBAC band | 3 | 2026-10-08 |
| `E10-D03` | Produce hi-fi Figma designs for shell chrome, Electron windows and system states | 3 | 2026-10-08 |
| `E10-D04` | Specify shell motion, run the a11y design review and publish handoff | 1 | 2026-10-08 |
| `E12-D02` | Wireframes: bar-mode selection, parameter entry and rebuild flow | 5 | 2026-10-08 |
| `E12-D03` | Hi-fi design: SCR-042 interval & bar-mode menu with parameter entry | 5 | 2026-10-08 |
| `E12-D06` | Hi-fi design: price series visual language (candle, bar, line, area, HA) | 5 | 2026-10-08 |
| `E13-D01` | UX research: how traders add, tune and manage indicators | 2 | 2026-10-08 |
| `E14-D01` | UX research: drawing, magnet and object-management mental models | 3 | 2026-10-08 |
| `E15-D01` | UX research: multi-pane workflows, sync groups and panel-docking mental models | 3 | 2026-10-08 |

Design total: **98 pts** across 28 tickets.

### 4.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: STRIDE R0 epics (s01, S01-S04)
- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- qa: Test framework build-out (q01, S01-S04)
- qa: Contract test harness (q02, S02-S03)

**QA tickets (6 pts, 5 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E01-Q02` | Ship the governance regression pack as a required CI job | 1 | `E01-Q01`, `E01-T06`, `E01-T07` |
| `E02-Q01` | QA: black-box test plan for the monorepo scaffold and toolchain | 2 | `E02-T10` |
| `E02-Q02` | QA: exploratory charter — clean-clone onboarding on a second engineer's machine | 1 | `E02-T08` |
| `E02-Q03` | QA: automated toolchain regression pack guarding the scaffold's gates | 1 | `E02-T10`, `E02-T06` |
| `E06-Q01` | Validate benchmark methodology and reproducibility before ADR evidence use | 1 | `E06-K01` |

**Security tickets (15 pts, 7 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E01-X02` | Security review of governance automation: tokens, pinning, abuse cases | 1 | `E01-T07`, `E01-X01` |
| `E02-X02` | Security: baseline SAST, secrets, SCA and license scanning configuration for the scaffold | 2 | `E02-X01`, `E02-T02`, `E02-T01` |
| `E04-X01` | STRIDE threat model for the observability baseline | 2 | `E03` |
| `E06-X02` | Pin and scan spike toolchain; enforce throwaway-code containment | 1 | `E06-K01`, `E06-X01` |
| `E07-X01` | Security: STRIDE threat model for recorder data & storage (Area 8) with abuse cases | 3 | `E02` |
| `E08-X01` | STRIDE threat model for the exchange boundary and ingestion pipeline | 3 | `E08-T01` |
| `E09-X01` | STRIDE threat model for authentication, sessions, 2FA, RBAC and audit | 3 | `E09-D01` |

### 4.7 Risks & dependency watch-list

- **Go/no-go gate 2026-10-08 on E06.** Architect + Owner decision required; a 'no-go' triggers an immediate re-plan of R1.
- E07 storage spike may show QuestDB write rates below the ingestion budget - contingency is a partitioning-strategy change, not a storage swap.
- E02 at 25 pts is the sprint's largest item; scaffold churn blocks every other lane.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S02 |
|---|---|---|
| `E08-D04` | Sprint 01 | 6 |
| `E05-D01` | Sprint 01 | 4 |
| `E01-T07` | Sprint 01 | 3 |
| `E02-T08` | Sprint 01 | 3 |
| `E06-K01` | Sprint 01 | 3 |
| `E07-T01` | Sprint 01 | 3 |
| `E08-D02` | Sprint 01 | 3 |
| `E08-T01` | Sprint 01 | 3 |
| `E09-D02` | Sprint 01 | 3 |
| `E09-D03` | Sprint 01 | 3 |
| `E09-D04` | Sprint 01 | 3 |
| `E02-T02` | Sprint 01 | 2 |
| _... 27 more_ | | |

### 4.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Monorepo builds all packages from a cold clone; engine spike demo shows measured FPS at target footprint density; QuestDB ingest benchmark shown live.

**Exit expectation:** **ADR-0006 merged with the go/no-go decision recorded.**

### 4.9 Burn-up - R0 train

| Sprint | Eng pts this sprint | Cumulative R0 | R0 total | Remaining | % complete |
|---|---|---|---|---|---|
| S01 | 90 | 90 | 355 | 265 | 25% |
| S02 **<- this sprint** | 90 | 180 | 355 | 175 | 51% |
| S03 | 87 | 267 | 355 | 88 | 75% |
| S04 | 88 | 355 | 355 | 0 | 100% |

---

## 5. S03 - 2026-10-09 -> 2026-10-15 (R0)

### 5.1 Sprint goal(s)

- Complete CI/CD to staging: build, container scan, deploy pipeline, environment separation (E03).
- Wire the data tier for real - QuestDB + Parquet + Postgres schemas migrated from `21-database-schema.md` (E07).
- Bring up the app shell and Electron wrapper on design-system v0 primitives (E10).
- Land the observability baseline's alerting rules and the first SLO dashboard (E04).

### 5.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 87 | 90 | +3 | ok |
| Design (D) | 49 | 60 | +11 | ok |
| QA (Q) | 17 | 45 | +28 | ok |
| Security (X) | 7 | 20 | +13 | ok |
| **Total** | **160** | **215** | **+55** | |

### 5.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E09** | Auth, sessions, 2FA & RBAC | Accounts & Security (BE-Sec) | 28 | 8 |
| **E50** | xstate-statemachine adoption: factory, persistence, plugins, contract suite, catalogue | Platform & DevSecOps | 28 | 6 |
| **E12** | Bar builders & series rendering (time/tick/volume/range/renko) | Data & Feeds (BE-Feeds) | 25 | 6 |
| **E10** | App shell, routing & Electron wrapper | App & Charting UI (FE-App) | 14 | 4 |
| **E06** | Chart-engine spike & ADR (WebGL2 feasibility, Electron vs Tauri) | Chart Engine (FE-Engine) | 11 | 7 |
| **E04** | Observability baseline: structured logs, metrics, health, dashboards, alerting | Platform & DevSecOps | 10 | 3 |
| **E05** | Design system v0 - tokens, primitives, Storybook | Design System | 9 | 4 |
| **E07** | Storage spike & data-tier wiring (QuestDB / Parquet+DuckDB / Postgres) | Data & Feeds (BE-Feeds) | 8 | 3 |
| **E03** | CI/CD pipeline & environments | Platform & DevSecOps | 5 | 1 |
| **E14** | Drawing tools | App & Charting UI (FE-App) | 5 | 1 |
| **E15** | Layouts & workspaces | App & Charting UI (FE-App) | 5 | 1 |
| **E08** | Bybit adapter & ingestion skeleton | Data & Feeds (BE-Feeds) | 3 | 1 |
| **E11** | Chart engine core (scene, axes, interaction, LOD) | Chart Engine (FE-Engine) | 3 | 1 |
| **E13** | Indicators framework & v1 indicator set | App & Charting UI (FE-App) | 3 | 1 |
| **E17** | Market-data WS protocol & binary framing | Data & Feeds (BE-Feeds) | 3 | 2 |


**Statechart lane:** E09 (`E09-S03`, `E09-S04`); E17 (`E17-D01`, `E17-D03`); E50 (`E50-T01`, `E50-T02`, `E50-T10`, `E50-T49`, `E50-T59`, `E50-T60`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 5.4 Tickets (49)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E03-Q01` | Verify every CI gate with negative fixtures and give epic QA sign-off | Task | 5 | infra | `E03-T05`, `E03-T06`, `E03-T07`, `E03-T09`, `E03-T13` |
| `E04-D02` | Run design QA and the accessibility review on the shipped observability surfaces | Task | 2 | web | `E04-D01` |
| `E04-Q01` | Write and execute the black-box test plan and alert drill for the observability baseline | Task | 3 | infra | `E04-T05`, `E04-S01` |
| `E04-T06` | Instrument the latency budget end to end and add the frontend telemetry endpoint | Task | 5 | infra | `E04-T03`, `E04-K01` |
| `E05-T01` | Implement token source of truth and Style Dictionary multi-target build | Task | 5 | web | `E05-D01`, `E02` |
| `E05-T05` | Build contrast-matrix generator and CI gate over token changes | Task | 1 | web | `E05-T01` |
| `E05-T07` | Write ADR-0016: design-token architecture and theming strategy | Task | 1 | docs | `E05-T01` |
| `E05-X01` | STRIDE threat model: design-system supply chain and Storybook exposure | Task | 2 | web | `E05-T01` |
| `E06-D03` | A11y design review: cost and shape of the engine DOM-mirror layer | Task | 1 | chart-engine | `E06-K04` |
| `E06-K03` | Prototype scene B: SDF text atlas and 2,500-cell footprint density (B3) | Spike | 3 | chart-engine | `E06-K01`, `E06-D01` |
| `E06-K04` | Prototype scene C: 200-depth heatmap texture ring, 4h trail and 30-min soak | Spike | 3 | chart-engine | `E06-K01`, `E06-D02` |
| `E06-Q02` | GPU/browser compatibility sweep and degraded-2d exploratory charter | Task | 1 | chart-engine | `E06-K02`, `E06-K03` |
| `E06-T01` | Run the measurement matrix across Chromium, Electron and Tauri/WebView2 | Task | 1 | chart-engine | `E06-K02`, `E06-K03`, `E06-K04`, `E06-X01`, `E06-Q02` |
| `E06-T02` | Write the M0 findings report and commit the CI benchmark harness job | Task | 1 | chart-engine | `E06-T01`, `E06-Q01`, `E06-D03` |
| `E06-T03` | Amend ADR-0002 and move ADR-0011 to decided with measured evidence | Task | 1 | chart-engine | `E06-T02` |
| `E07-D02` | Verify the shipped StorageUsage payload against the operator content model | Task | 2 | api | `E07-D01`, `E07-T05` |
| `E07-Q01` | QA: black-box test plan and storage contract/integration suite for the three tiers | Task | 3 | infra | `E07-T02`, `E07-T03` |
| `E07-T05` | Build retention/archive job skeleton and the source_tier=auto query router | Task | 3 | infra | `E07-T04`, `E07-T02`, `E07-X01` |
| `E08-X03` | SAST/SCA rules, secret scanning and the P3 vocabulary-leak lint gate | Task | 3 | infra | `E08-X01`, `E08-T01` |
| `E09-Q01` | Black-box test plan for the E09 auth, session and RBAC story groups | Task | 5 | auth | `E09-S01` |
| `E09-S01` | Password sign-in with lockout and uniform failures (US-ONB-001) | Story | 5 | auth | `E09-T01`, `E09-T02`, `E09-T04` |
| `E09-S02` | TOTP second factor, enrolment and recovery codes (US-ONB-002/003) | Story | 5 | auth | `E09-S01` |
| `E09-S03` | Session lifetime, idle lock and sign-out everywhere (US-ONB-004/009) | Story | 3 | auth | `E09-S02` |
| `E09-S04` | Step-up re-authentication and owner-initiated TOTP reset (US-ONB-005/010) | Story | 2 | auth | `E09-S03`, `E09-T03` |
| `E09-S05` | Invite-based user creation and redemption (US-ONB-006) | Story | 3 | auth | `E09-S04` |
| `E09-S06` | Guided first-run checklist for a new manager (US-ONB-007) | Story | 2 | web | `E09-S05` |
| `E09-T03` | RBAC decision point, generated permissions, deny-by-default enforcement | Task | 3 | auth | `E09-S02`, `E09-T02` |
| `E10-T01` | Implement the route tree, auth/RBAC/step-up guards and deep-link validation | Task | 5 | web | `E09`, `E02` |
| `E10-T02` | Build the hardened Electron main and preload processes (SR-110..SR-119) | Task | 5 | web | `E10-K01`, `E02` |
| `E10-T04` | Implement shell bootstrap: /me, preferences, keymap and WS system topic | Task | 2 | web | `E10-T01`, `E09`, `E17` |
| `E10-X01` | Produce the STRIDE threat model for the app shell, routing and Electron wrapper | Task | 2 | web | `E10-K01` |
| `E11-D01` | Run UX research on chart navigation, scale control and keyboard-first charting | Task | 3 | chart-engine | `E05` |
| `E12-D04` | Hi-fi design: SCR-041 symbol/interval quick-switcher & hotkey ladder | Task | 3 | chart-engine | `E12-D02`, `E12-D03` |
| `E12-D05` | Hi-fi design: SCR-031 chart settings — bar mode, chart type & precision | Task | 5 | chart-engine | `E12-D02`, `E12-D03` |
| `E12-D07` | Hi-fi design: SCR-045 data-table alternative for every bar mode | Task | 5 | chart-engine | `E12-D02`, `E12-D06` |
| `E12-D08` | Hi-fi design: rebuild, partial history, empty & error states (SCR-047/048) | Task | 5 | chart-engine | `E12-D01`, `E12-D02`, `E12-D06` |
| `E12-D09` | Design-system: bar-mode & series components (CMP-181, 220, 222, 226) | Task | 5 | chart-engine | `E12-D03`, `E12-D04`, `E12-D05`, `E12-D06` |
| `E12-D10` | Motion spec: bar-mode transitions, forming bar, rebuild progress, LOD change | Task | 2 | chart-engine | `E12-D06`, `E12-D08` |
| `E13-D02` | Wireframe SCR-034, SCR-035 and SCR-036 with all states | Task | 3 | indicators | `E13-D01` |
| `E14-D02` | Wireframes: drawing toolbar, canvas interaction model and object tree | Task | 5 | web | `E14-D01` |
| `E15-D02` | Wireframes: workspace shell, dock model, presets and sync - greyscale end to end | Task | 5 | web | `E15-D01` |
| `E17-D01` | UX research: how a trader must experience a degraded or dropped feed | Task | 2 | web | `E05` |
| `E17-D03` | Confirm the heatmap column legibility band (DES-HEATMAP-01) | Task | 1 | web | `E05` |
| `E50-T01` | Machine-JSON registry: schema/target validation, recursive key walk (CV-C57), machine_hash, Stately export | Task | 5 | api | `E50-T11`, `E03-T02` |
| `E50-T02` | machine_hash lock in CI, snapshot envelope version ≥3, upcaster registry with golden-snapshot rule | Task | 3 | api | `E50-T01` |
| `E50-T10` | Persistence module: quiescent persist + drain journal (C40, C41, C49′/C58, C65′) | Task | 5 | api | `E50-T59`, `E50-T02` |
| `E50-T49` | Persistence restore + HMAC envelope: from_snapshot(plugins=, minimum_version=3, expected_machine_hash=), C27′/C45″/C54/C60 checks, chain_trips latch | Task | 5 | api | `E50-T10` |
| `E50-T59` | Statechart factory + mandatory config block (factory.py, config.py, lane table, bounded start(), bring-up, async-only assert) | Task | 5 | api | `E50-T57`, `E50-T01` |
| `E50-T60` | CvErrorHooks / CvMetricsPlugin / CvAuditPlugin (C09, C36, C50, C59, C63, C69; cv_machine_* families; write-ahead machine_events) | Task | 5 | api | `E50-T59`, `E04-T03`, `E09-T02` |

### 5.5 Design-track deliverables due

**Design sprint D-S03** (roadmap 1.2) produces: Chart surface, time/price axes, crosshair, chart toolbar, indicator UI

> Consumed by engineering sprint **S05** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S05 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E04-D02` | Run design QA and the accessibility review on the shipped observability surfaces | 2 | 2026-10-15 |
| `E06-D03` | A11y design review: cost and shape of the engine DOM-mirror layer | 1 | 2026-10-15 |
| `E07-D02` | Verify the shipped StorageUsage payload against the operator content model | 2 | 2026-10-15 |
| `E11-D01` | Run UX research on chart navigation, scale control and keyboard-first charting | 3 | 2026-10-15 |
| `E12-D04` | Hi-fi design: SCR-041 symbol/interval quick-switcher & hotkey ladder | 3 | 2026-10-15 |
| `E12-D05` | Hi-fi design: SCR-031 chart settings — bar mode, chart type & precision | 5 | 2026-10-15 |
| `E12-D07` | Hi-fi design: SCR-045 data-table alternative for every bar mode | 5 | 2026-10-15 |
| `E12-D08` | Hi-fi design: rebuild, partial history, empty & error states (SCR-047/048) | 5 | 2026-10-15 |
| `E12-D09` | Design-system: bar-mode & series components (CMP-181, 220, 222, 226) | 5 | 2026-10-15 |
| `E12-D10` | Motion spec: bar-mode transitions, forming bar, rebuild progress, LOD change | 2 | 2026-10-15 |
| `E13-D02` | Wireframe SCR-034, SCR-035 and SCR-036 with all states | 3 | 2026-10-15 |
| `E14-D02` | Wireframes: drawing toolbar, canvas interaction model and object tree | 5 | 2026-10-15 |
| `E15-D02` | Wireframes: workspace shell, dock model, presets and sync - greyscale end to end | 5 | 2026-10-15 |
| `E17-D01` | UX research: how a trader must experience a degraded or dropped feed | 2 | 2026-10-15 |
| `E17-D03` | Confirm the heatmap column legibility band (DES-HEATMAP-01) | 1 | 2026-10-15 |

Design total: **49 pts** across 15 tickets.

### 5.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: STRIDE R0 epics (s01, S01-S04)
- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- qa: Test framework build-out (q01, S01-S04)
- qa: Contract test harness (q02, S02-S03)

**QA tickets (17 pts, 5 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E03-Q01` | Verify every CI gate with negative fixtures and give epic QA sign-off | 5 | `E03-T05`, `E03-T06`, `E03-T07`, `E03-T09`, `E03-T13` |
| `E04-Q01` | Write and execute the black-box test plan and alert drill for the observability baseline | 3 | `E04-T05`, `E04-S01` |
| `E06-Q02` | GPU/browser compatibility sweep and degraded-2d exploratory charter | 1 | `E06-K02`, `E06-K03` |
| `E07-Q01` | QA: black-box test plan and storage contract/integration suite for the three tiers | 3 | `E07-T02`, `E07-T03` |
| `E09-Q01` | Black-box test plan for the E09 auth, session and RBAC story groups | 5 | `E09-S01` |

**Security tickets (7 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E05-X01` | STRIDE threat model: design-system supply chain and Storybook exposure | 2 | `E05-T01` |
| `E08-X03` | SAST/SCA rules, secret scanning and the P3 vocabulary-leak lint gate | 3 | `E08-X01`, `E08-T01` |
| `E10-X01` | Produce the STRIDE threat model for the app shell, routing and Electron wrapper | 2 | `E10-K01` |

### 5.7 Risks & dependency watch-list

- E03 CI/CD must reach staging this sprint or the R0 exit criterion on deployability fails.
- Data-tier migrations are irreversible in staging; rehearse rollback.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S03 |
|---|---|---|
| `E12-D02` | Sprint 02 | 4 |
| `E12-D06` | Sprint 02 | 4 |
| `E02` | epic E02 (whole epic must be Done) | 3 |
| `E05` | epic E05 (whole epic must be Done) | 3 |
| `E12-D03` | Sprint 02 | 3 |
| `E06-K01` | Sprint 01 | 2 |
| `E06-K02` | Sprint 01 | 2 |
| `E07-T02` | Sprint 02 | 2 |
| `E08-X01` | Sprint 02 | 2 |
| `E08-K01` | Sprint 01 | 2 |
| `E08-T01` | Sprint 01 | 2 |
| `E08-T04` | Sprint 02 | 2 |
| _... 33 more_ | | |

### 5.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** A commit flows to staging through the pipeline unattended; Grafana shows live ingestion metrics; the app shell renders an RBAC-gated route.

**Exit expectation:** Staging deployment is repeatable and rollback is demonstrated.

### 5.9 Burn-up - R0 train

| Sprint | Eng pts this sprint | Cumulative R0 | R0 total | Remaining | % complete |
|---|---|---|---|---|---|
| S01 | 90 | 90 | 355 | 265 | 25% |
| S02 | 90 | 180 | 355 | 175 | 51% |
| S03 **<- this sprint** | 87 | 267 | 355 | 88 | 75% |
| S04 | 88 | 355 | 355 | 0 | 100% |

---

## 6. S04 - 2026-10-16 -> 2026-10-22 (R0)

### 6.1 Sprint goal(s)

- **Close R0.** Design-system v0 ships its full primitive set and Storybook (E05) - the biggest single-epic sprint load in the train at 47 pts.
- App shell routing, RBAC-gated route guards and the Electron packaging path complete (E10).
- First engine-core foundations land against the ratified ADR (E11).
- Recorder groundwork starts so the >=2-sprint recording rule (roadmap 11.3 rule 4) can be met by R2 (E16).
- **QA is over pool: 65 pts vs 45 (+20).**
- **Design is over pool: 81 pts vs 60 (+21).**
- **Security is over pool: 26 pts vs 20 (+6).**

### 6.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 88 | 90 | +2 | ok |
| Design (D) | 81 | 60 | -21 | **OVER** |
| QA (Q) | 62 | 45 | -17 | **OVER** |
| Security (X) | 26 | 20 | -6 | **OVER** |
| **Total** | **257** | **215** | **-42** | |

### 6.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E08** | Bybit adapter & ingestion skeleton | Data & Feeds (BE-Feeds) | 49 | 12 |
| **E05** | Design system v0 - tokens, primitives, Storybook | Design System | 47 | 14 |
| **E09** | Auth, sessions, 2FA & RBAC | Accounts & Security (BE-Sec) | 35 | 10 |
| **E50** | xstate-statemachine adoption: factory, persistence, plugins, contract suite, catalogue | Platform & DevSecOps | 26 | 5 |
| **E11** | Chart engine core (scene, axes, interaction, LOD) | Chart Engine (FE-Engine) | 16 | 4 |
| **E10** | App shell, routing & Electron wrapper | App & Charting UI (FE-App) | 15 | 7 |
| **E15** | Layouts & workspaces | App & Charting UI (FE-App) | 13 | 3 |
| **E07** | Storage spike & data-tier wiring (QuestDB / Parquet+DuckDB / Postgres) | Data & Feeds (BE-Feeds) | 11 | 4 |
| **E16** | Recorder, retention & disk budget | Data & Feeds (BE-Feeds) | 11 | 3 |
| **E13** | Indicators framework & v1 indicator set | App & Charting UI (FE-App) | 10 | 3 |
| **E14** | Drawing tools | App & Charting UI (FE-App) | 10 | 2 |
| **E12** | Bar builders & series rendering (time/tick/volume/range/renko) | Data & Feeds (BE-Feeds) | 6 | 2 |
| **E04** | Observability baseline: structured logs, metrics, health, dashboards, alerting | Platform & DevSecOps | 5 | 2 |
| **E17** | Market-data WS protocol & binary framing | Data & Feeds (BE-Feeds) | 3 | 1 |


**Statechart lane:** E08 (`E08-S05`, `E08-T04`); E16 (`E16-D01`, `E16-D02`, `E16-D03`); E17 (`E17-D02`); E50 (`E50-S01`, `E50-S02`, `E50-T04`, `E50-T15`, `E50-T31`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 6.4 Tickets (72)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E04-Q02` | Run an exploratory charter on observability blind spots and build the regression pack | Task | 2 | infra | `E04-Q01`, `E04-D02` |
| `E04-X02` | Security review, abuse cases and SAST rules for logging, metrics and diagnostics | Task | 3 | infra | `E04-X01`, `E04-S02`, `E04-T05` |
| `E05-D04` | Run accessibility and CVD design review and record sign-off | Task | 3 | web | `E05-S04`, `E05-T05` |
| `E05-D05` | Perform design QA of the built component library against spec | Task | 3 | web | `E05-S04` |
| `E05-Q01` | Write and execute component black-box test plan and exploratory charter | Task | 3 | web | `E05-S03` |
| `E05-Q02` | Run a11y audit of design system v0 (axe sweep plus manual screen reader) | Task | 3 | web | `E05-S04`, `E05-T03` |
| `E05-Q03` | Assemble visual-regression regression pack and record epic QA sign-off | Task | 3 | web | `E05-T04`, `E05-Q01`, `E05-Q02` |
| `E05-S01` | Implement interactive control atoms CMP-001..CMP-010 with full state matrix | Story | 8 | web | `E05-D02`, `E05-D06`, `E05-T03`, `E05-T06` |
| `E05-S02` | Implement display, feedback and utility atoms CMP-011..CMP-039 | Story | 5 | web | `E05-S01` |
| `E05-S03` | Implement molecules: forms, overlays, table and navigation primitives | Story | 5 | web | `E05-S02` |
| `E05-S04` | Implement theming, density, preview and app-state components | Story | 3 | web | `E05-S03`, `E05-T02` |
| `E05-T02` | Implement theme, density and reduced-motion runtime in packages/ui | Task | 3 | web | `E05-T01`, `E05-D03` |
| `E05-T03` | Set up Storybook 8 with a11y addon, theme/density toolbars and CI test-runner | Task | 2 | web | `E05-T02`, `E03` |
| `E05-T04` | Establish visual-regression baseline across theme x density | Task | 2 | web | `E05-K01`, `E05-T03`, `E05-S03` |
| `E05-T06` | Create icon registry and custom trading-domain icons | Task | 2 | web | `E05-D02` |
| `E05-X02` | Security review of design-system dependencies, CSP impact and Storybook hosting | Task | 2 | web | `E05-X01`, `E05-T03`, `E05-S04` |
| `E07-Q02` | QA: exploratory charter - tier boundaries, backfill idempotency and lifecycle surprises | Task | 2 | infra | `E07-T05` |
| `E07-Q03` | QA: storage performance harness - ILP ingest rate, query-shape regression, export throughput | Task | 3 | infra | `E07-T03`, `E07-T04` |
| `E07-Q04` | QA: chaos scenarios - DB down, disk full, crash between export and partition drop | Task | 3 | infra | `E07-T05` |
| `E07-X02` | Security: verify storage controls SR-047/048/090-099, add SAST rules and a DAST/path-traversal probe | Task | 3 | infra | `E07-X01`, `E07-T05` |
| `E08-D14` | Design QA of the implemented E08 market-data surfaces | Task | 3 | data-feeds | `E08-D13` |
| `E08-Q01` | Black-box test plan for the E08 market-data and ingestion story groups | Task | 5 | data-feeds | `E08-T01`, `E08-S01`, `E08-T04` |
| `E08-Q02` | Contract & integration test pack for the adapter against recorded Bybit fixtures | Task | 5 | data-feeds | `E08-Q01`, `E08-T05`, `E08-S05`, `E08-S06` |
| `E08-Q03` | Chaos & failure-injection scenarios for the exchange boundary | Task | 5 | data-feeds | `E08-Q02`, `E08-T04`, `E08-S05`, `E08-S07` |
| `E08-Q04` | Ingestion performance pack: 24h soak, 5x burst injector and k6 REST load | Task | 5 | data-feeds | `E08-Q02`, `E08-T06` |
| `E08-S03` | Live ticker stream: subscribe once, fan out, delta-merge and reconnect | Story | 3 | data-feeds | `E08-T04`, `E08-S01` |
| `E08-S04` | Trade (tape) stream ingestion: normalise, dedupe by tradeId and backfill gaps | Story | 5 | data-feeds | `E08-S03` |
| `E08-S05` | Order-book reconstruction: snapshot+delta, gap resync, atomic depth-tier change | Story | 5 | data-feeds | `E08-T04`, `E08-K01`, `E50-T59`, `E50-S01` |
| `E08-T04` | Public WS ingestion skeleton: ConnectionManager, SubscriptionPlanner, reconnect | Task | 3 | data-feeds | `E08-T01`, `E08-T03`, `E50-T59`, `E50-S01` |
| `E08-T05` | Recorded Bybit fixture corpus and the demo connectivity smoke-test suite | Task | 3 | data-feeds | `E08-S04`, `E08-S05` |
| `E08-T06` | Ingestion observability, 24h soak harness and doc/ADR reconciliation for R0 exit | Task | 2 | data-feeds | `E08-S05`, `E08-S06`, `E04` |
| `E08-X02` | Abuse cases and adversarial input testing against the exchange boundary | Task | 5 | data-feeds | `E08-X01`, `E08-Q02`, `E08-S05` |
| `E09-D11` | Design QA of the built auth, session and RBAC surfaces | Task | 3 | web | `E09-D03`, `E09-D04`, `E09-D05`, `E09-D06`, `E09-D07`, `E09-D09`, `E09-D10` |
| `E09-K02` | Publish the auth/RBAC operator runbook and ADR-0010 implementation addendum | Chore | 2 | docs | `E09-X04`, `E09-Q06` |
| `E09-Q02` | Playwright E2E suite for login, TOTP, idle lock, step-up and onboarding | Task | 5 | auth | `E09-Q01`, `E09-S03`, `E09-S05` |
| `E09-Q03` | RBAC allow/deny matrix regression pack across every route and WS topic | Task | 5 | auth | `E09-T03`, `E09-S03` |
| `E09-Q04` | Accessibility audit of the auth, onboarding and settings surfaces | Task | 3 | auth | `E09-S02`, `E09-S05` |
| `E09-Q05` | Auth perf profile and chaos: k6 load, clock skew, Postgres restart | Task | 3 | auth | `E09-S01`, `E09-S03` |
| `E09-Q06` | Exploratory charters, epic regression pack and QA sign-off for E09 | Task | 3 | auth | `E09-Q02`, `E09-Q03`, `E09-Q04`, `E09-Q05` |
| `E09-X02` | Abuse cases and adversarial testing of auth, session and RBAC boundaries | Task | 5 | auth | `E09-X01`, `E09-S01`, `E09-S03` |
| `E09-X03` | SAST/DAST rules, secret scanning and CI security gates for the auth surface | Task | 3 | auth | `E09-X01`, `E09-T04` |
| `E09-X04` | Security review, break-glass drill and Owner sign-off for E09 | Task | 3 | auth | `E09-X02`, `E09-X03`, `E09-T02`, `E09-T04` |
| `E10-Q02` | Build the Playwright web + Playwright-Electron E2E suite for the shell | Task | 2 | web | `E10-T02`, `E10-S01`, `E10-S04` |
| `E10-Q03` | Run the accessibility audit of the shell surfaces (WCAG 2.2 AA) | Task | 1 | web | `E10-S01`, `E10-S02`, `E10-S04`, `E10-D04` |
| `E10-Q04` | Benchmark shell cold start, route change and chrome isolation against budget #10 | Task | 1 | web | `E10-T02`, `E10-T04`, `E10-S01` |
| `E10-S01` | Render the persistent app shell chrome and navigation rail (SCR-010, SCR-011) | Story | 5 | web | `E10-T01`, `E10-T04`, `E10-D04`, `E05-S01` |
| `E10-S02` | Implement the global hotkey registry with remapping and conflicts (US-SET-002) | Story | 2 | web | `E10-S01`, `E10-T04`, `E10-D04` |
| `E10-S04` | Implement the system-state surfaces: 403, 404, degraded, offline, crash boundary | Story | 2 | web | `E10-T01`, `E10-T04`, `E10-D04` |
| `E10-X02` | Add the electron-hardening CI gate and SAST rules, and run security review | Task | 2 | web | `E10-T02`, `E10-X01`, `E03` |
| `E11-D02` | Design the chart chassis: pane chrome, axes, crosshair, legend, diagnostics | Task | 8 | chart-engine | `E11-D01`, `E05` |
| `E11-D03` | Design the price/time scale menus, scale settings and the go-to-date dialog | Task | 3 | chart-engine | `E11-D02` |
| `E11-D05` | Contribute chart primitives, tokens and density modes to the design system | Task | 3 | chart-engine | `E11-D02`, `E05` |
| `E11-D06` | Specify chart motion: momentum, transitions and reduced-motion variants | Task | 2 | chart-engine | `E11-D02` |
| `E12-D11` | Accessibility design review & screen-reader script for the bar/series band | Task | 3 | chart-engine | `E12-D03`, `E12-D04`, `E12-D05`, `E12-D06`, `E12-D07`, `E12-D08` |
| `E12-D12` | Engineering handoff pack for the bar-builder & series-rendering band | Task | 3 | chart-engine | `E12-D09`, `E12-D10`, `E12-D11` |
| `E13-D03` | Hi-fi design for SCR-034/035/036 and the indicator visual language | Task | 5 | indicators | `E13-D02` |
| `E13-D04` | Design-system contribution: indicator palette tokens and motion spec | Task | 3 | indicators | `E13-D03` |
| `E13-D05` | Accessibility design review of the indicator surfaces | Task | 2 | indicators | `E13-D03` |
| `E14-D03` | Hi-fi design: drawing tool rail & tool palette (SCR-037, CMP-223) | Task | 5 | web | `E14-D02` |
| `E14-D04` | Hi-fi design: drawing properties popover, styling & template library | Task | 5 | web | `E14-D02` |
| `E15-D03` | Hi-fi design: SCR-020 workspace page, tab strip and panel chrome | Task | 5 | web | `E15-D02` |
| `E15-D04` | Hi-fi design: SCR-021 dock system - drop zones, drag preview, keyboard move mode | Task | 5 | web | `E15-D02` |
| `E15-D05` | Hi-fi design: SCR-022 layout preset gallery & SCR-011 workspace switcher | Task | 3 | web | `E15-D02` |
| `E16-D01` | UX research: recorder mental model, auto-record surprise and disk anxiety | Task | 3 | web | `E05` |
| `E16-D02` | Design SCR-140 recorder & storage screen and CMP-177 RecorderStatusRow | Task | 5 | web | `E16-D01`, `E05` |
| `E16-D03` | Design SCR-141 retention policy editor with destructive-change confirmation | Task | 3 | web | `E16-D02` |
| `E17-D02` | Design SCR-152 and the connection-state component set to hi-fi with handoff | Task | 3 | web | `E17-D01`, `E05` |
| `E50-S01` | Commit B1–B9 machine.json + bindings/ stubs from the corrected v0.9.1 contracts; hashes locked | Story | 5 | api | `E50-T01`, `E50-T02` |
| `E50-S02` | Commit B10–B20 machine.json + bindings/ stubs from the corrected v0.9.1 contracts; hashes locked | Story | 5 | api | `E50-T01`, `E50-T02` |
| `E50-T04` | Nightly run_gate.py against the pinned 0.9.1 wheel + latest-upstream informational + nightly BENCH-6 on target hardware (P3-G6) | Task | 3 | api | `E50-T57`, `E50-T31` |
| `E50-T15` | gateway.py: send/send_threadsafe (C33), futures read + refusals paged (C36), no priority (C42), receipt rule (C06), order-lane RAISE→503 | Task | 5 | api | `E50-T59`, `E50-T60` |
| `E50-T31` | tests/xstate_contract/ BLOCKING gate: all 20 machines, both spellings, snapshot round-trip at every quiescence point, -W error::RuntimeWarning | Task | 8 | api | `E50-S01`, `E50-S02`, `E50-T49`, `E50-T15` |

### 6.5 Design-track deliverables due

**Design sprint D-S04** (roadmap 1.2) produces: Drawing-tool UX, layouts/workspaces, recorder UI

> Consumed by engineering sprint **S06** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S06 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E05-D04` | Run accessibility and CVD design review and record sign-off | 3 | 2026-10-22 |
| `E05-D05` | Perform design QA of the built component library against spec | 3 | 2026-10-22 |
| `E08-D14` | Design QA of the implemented E08 market-data surfaces | 3 | 2026-10-22 |
| `E09-D11` | Design QA of the built auth, session and RBAC surfaces | 3 | 2026-10-22 |
| `E11-D02` | Design the chart chassis: pane chrome, axes, crosshair, legend, diagnostics | 8 | 2026-10-22 |
| `E11-D03` | Design the price/time scale menus, scale settings and the go-to-date dialog | 3 | 2026-10-22 |
| `E11-D05` | Contribute chart primitives, tokens and density modes to the design system | 3 | 2026-10-22 |
| `E11-D06` | Specify chart motion: momentum, transitions and reduced-motion variants | 2 | 2026-10-22 |
| `E12-D11` | Accessibility design review & screen-reader script for the bar/series band | 3 | 2026-10-22 |
| `E12-D12` | Engineering handoff pack for the bar-builder & series-rendering band | 3 | 2026-10-22 |
| `E13-D03` | Hi-fi design for SCR-034/035/036 and the indicator visual language | 5 | 2026-10-22 |
| `E13-D04` | Design-system contribution: indicator palette tokens and motion spec | 3 | 2026-10-22 |
| `E13-D05` | Accessibility design review of the indicator surfaces | 2 | 2026-10-22 |
| `E14-D03` | Hi-fi design: drawing tool rail & tool palette (SCR-037, CMP-223) | 5 | 2026-10-22 |
| `E14-D04` | Hi-fi design: drawing properties popover, styling & template library | 5 | 2026-10-22 |
| `E15-D03` | Hi-fi design: SCR-020 workspace page, tab strip and panel chrome | 5 | 2026-10-22 |
| `E15-D04` | Hi-fi design: SCR-021 dock system - drop zones, drag preview, keyboard move mode | 5 | 2026-10-22 |
| `E15-D05` | Hi-fi design: SCR-022 layout preset gallery & SCR-011 workspace switcher | 3 | 2026-10-22 |
| `E16-D01` | UX research: recorder mental model, auto-record surprise and disk anxiety | 3 | 2026-10-22 |
| `E16-D02` | Design SCR-140 recorder & storage screen and CMP-177 RecorderStatusRow | 5 | 2026-10-22 |
| `E16-D03` | Design SCR-141 retention policy editor with destructive-change confirmation | 3 | 2026-10-22 |
| `E17-D02` | Design SCR-152 and the connection-state component set to hi-fi with handoff | 3 | 2026-10-22 |

Design total: **81 pts** across 22 tickets.

### 6.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: STRIDE R0 epics (s01, S01-S04)
- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- qa: Test framework build-out (q01, S01-S04)

**QA tickets (62 pts, 19 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E04-Q02` | Run an exploratory charter on observability blind spots and build the regression pack | 2 | `E04-Q01`, `E04-D02` |
| `E05-Q01` | Write and execute component black-box test plan and exploratory charter | 3 | `E05-S03` |
| `E05-Q02` | Run a11y audit of design system v0 (axe sweep plus manual screen reader) | 3 | `E05-S04`, `E05-T03` |
| `E05-Q03` | Assemble visual-regression regression pack and record epic QA sign-off | 3 | `E05-T04`, `E05-Q01`, `E05-Q02` |
| `E07-Q02` | QA: exploratory charter - tier boundaries, backfill idempotency and lifecycle surprises | 2 | `E07-T05` |
| `E07-Q03` | QA: storage performance harness - ILP ingest rate, query-shape regression, export throughput | 3 | `E07-T03`, `E07-T04` |
| `E07-Q04` | QA: chaos scenarios - DB down, disk full, crash between export and partition drop | 3 | `E07-T05` |
| `E08-Q01` | Black-box test plan for the E08 market-data and ingestion story groups | 5 | `E08-T01`, `E08-S01`, `E08-T04` |
| `E08-Q02` | Contract & integration test pack for the adapter against recorded Bybit fixtures | 5 | `E08-Q01`, `E08-T05`, `E08-S05`, `E08-S06` |
| `E08-Q03` | Chaos & failure-injection scenarios for the exchange boundary | 5 | `E08-Q02`, `E08-T04`, `E08-S05`, `E08-S07` |
| `E08-Q04` | Ingestion performance pack: 24h soak, 5x burst injector and k6 REST load | 5 | `E08-Q02`, `E08-T06` |
| `E09-Q02` | Playwright E2E suite for login, TOTP, idle lock, step-up and onboarding | 5 | `E09-Q01`, `E09-S03`, `E09-S05` |
| `E09-Q03` | RBAC allow/deny matrix regression pack across every route and WS topic | 5 | `E09-T03`, `E09-S03` |
| `E09-Q04` | Accessibility audit of the auth, onboarding and settings surfaces | 3 | `E09-S02`, `E09-S05` |
| `E09-Q05` | Auth perf profile and chaos: k6 load, clock skew, Postgres restart | 3 | `E09-S01`, `E09-S03` |
| `E09-Q06` | Exploratory charters, epic regression pack and QA sign-off for E09 | 3 | `E09-Q02`, `E09-Q03`, `E09-Q04`, `E09-Q05` |
| `E10-Q02` | Build the Playwright web + Playwright-Electron E2E suite for the shell | 2 | `E10-T02`, `E10-S01`, `E10-S04` |
| `E10-Q03` | Run the accessibility audit of the shell surfaces (WCAG 2.2 AA) | 1 | `E10-S01`, `E10-S02`, `E10-S04`, `E10-D04` |
| `E10-Q04` | Benchmark shell cold start, route change and chrome isolation against budget #10 | 1 | `E10-T02`, `E10-T04`, `E10-S01` |

**Security tickets (26 pts, 8 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E04-X02` | Security review, abuse cases and SAST rules for logging, metrics and diagnostics | 3 | `E04-X01`, `E04-S02`, `E04-T05` |
| `E05-X02` | Security review of design-system dependencies, CSP impact and Storybook hosting | 2 | `E05-X01`, `E05-T03`, `E05-S04` |
| `E07-X02` | Security: verify storage controls SR-047/048/090-099, add SAST rules and a DAST/path-traversal probe | 3 | `E07-X01`, `E07-T05` |
| `E08-X02` | Abuse cases and adversarial input testing against the exchange boundary | 5 | `E08-X01`, `E08-Q02`, `E08-S05` |
| `E09-X02` | Abuse cases and adversarial testing of auth, session and RBAC boundaries | 5 | `E09-X01`, `E09-S01`, `E09-S03` |
| `E09-X03` | SAST/DAST rules, secret scanning and CI security gates for the auth surface | 3 | `E09-X01`, `E09-T04` |
| `E09-X04` | Security review, break-glass drill and Owner sign-off for E09 | 3 | `E09-X02`, `E09-X03`, `E09-T02`, `E09-T04` |
| `E10-X02` | Add the electron-hardening CI gate and SAST rules, and run security review | 2 | `E10-T02`, `E10-X01`, `E03` |

### 6.7 Risks & dependency watch-list

- **R0 exit gate 2026-10-22.** All four exit criteria must have evidence links or R1 cannot open.
- E05 at 47 pts is the heaviest single-epic sprint load in R0 - a design-system slip cascades to every FE lane.
- Recorder (E16) must begin recording now: roadmap 11.3 rule 4 requires >=2 sprints of history before any view that depends on it ships.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S04 |
|---|---|---|
| `E05` | epic E05 (whole epic must be Done) | 5 |
| `E09-S03` | Sprint 03 | 4 |
| `E10-D04` | Sprint 02 | 4 |
| `E10-T04` | Sprint 03 | 4 |
| `E07-T05` | Sprint 03 | 3 |
| `E08-S05` | Sprint 03 | 3 |
| `E10-T02` | Sprint 03 | 3 |
| `E15-D02` | Sprint 03 | 3 |
| `E05-D02` | Sprint 02 | 2 |
| `E03` | epic E03 (whole epic must be Done) | 2 |
| `E08-Q01` | Sprint 03 | 2 |
| `E09-S05` | Sprint 03 | 2 |
| _... 52 more_ | | |

### 6.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Storybook published with the full DS v0 primitive set; Electron app launches and navigates; recorder is writing ticks for the seed symbol list.

**Exit expectation:** **R0 gate (PRR-lite) 2026-10-22 - `0.1.0` tagged.** All four R0 exit criteria evidenced.

### 6.9 Burn-up - R0 train

| Sprint | Eng pts this sprint | Cumulative R0 | R0 total | Remaining | % complete |
|---|---|---|---|---|---|
| S01 | 90 | 90 | 355 | 265 | 25% |
| S02 | 90 | 180 | 355 | 175 | 51% |
| S03 | 87 | 267 | 355 | 88 | 75% |
| S04 **<- this sprint** | 88 | 355 | 355 | 0 | 100% |

---

# R1 - Charting alpha

| | |
|---|---|
| Sprints | S05-S09 |
| Dates | 2026-10-23 -> 2026-11-26 |
| Version at cut | `0.2.0` |
| Deploys to | staging (demo) |
| Gate | PRR |
| Eng pts in backlog | 407 of 405 capacity (100%) |
| All-discipline pts | 831 |

R1 turns the engine spike into a real chart: scene graph, axes, interaction, LOD, bar builders across five bar types, an indicator framework, drawing tools, layouts, the recorder and the market-data WS protocol. This is the train where the frontend becomes a product rather than a prototype, and where the critical path `E11 -> E12` runs at full load.

---

## 7. S05 - 2026-10-23 -> 2026-10-29 (R1)

### 7.1 Sprint goal(s)

- **Open R1 on the critical path.** Engine core scene graph, camera, axes and the shared tick-precise time/price transform (E11).
- Market-data WS protocol and binary framing - the contract every later pane consumes (E17).
- Recorder continues so symbol history accumulates ahead of R2 (E16).
- **Design is over pool: 80 pts vs 60 (+20).**

### 7.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 90 | 90 | +0 | ok |
| Design (D) | 80 | 60 | -20 | **OVER** |
| QA (Q) | 0 | 45 | +45 | ok |
| Security (X) | 9 | 20 | +11 | ok |
| **Total** | **179** | **215** | **+36** | |

### 7.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E11** | Chart engine core (scene, axes, interaction, LOD) | Chart Engine (FE-Engine) | 40 | 12 |
| **E14** | Drawing tools | App & Charting UI (FE-App) | 40 | 11 |
| **E15** | Layouts & workspaces | App & Charting UI (FE-App) | 35 | 12 |
| **E12** | Bar builders & series rendering (time/tick/volume/range/renko) | Data & Feeds (BE-Feeds) | 24 | 6 |
| **E17** | Market-data WS protocol & binary framing | Data & Feeds (BE-Feeds) | 20 | 6 |
| **E16** | Recorder, retention & disk budget | Data & Feeds (BE-Feeds) | 12 | 4 |
| **E13** | Indicators framework & v1 indicator set | App & Charting UI (FE-App) | 4 | 2 |
| **E19** | Volume / delta / TPO profiles | Order Flow (BE-Flow + FE-Engine) | 3 | 1 |
| **E50** | xstate-statemachine adoption: factory, persistence, plugins, contract suite, catalogue | Platform & DevSecOps | 1 | 1 |


**Statechart lane:** E16 (`E16-D04`, `E16-D05`, `E16-D06`, `E16-T01`); E17 (`E17-K01`, `E17-S01`, `E17-S02`, `E17-T01`, `E17-T02`, `E17-X01`); E19 (`E19-D01`); E50 (`E50-T14`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 7.4 Tickets (55)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E11-D04` | Design the data-table alternative and the chart empty and error states | Task | 5 | chart-engine | `E11-D02` |
| `E11-D07` | Run an accessibility design review of the chart engine's canvas strategy | Task | 3 | chart-engine | `E11-D04` |
| `E11-D09` | Produce the chart-engine design handoff pack and run the engineering walkthrough | Task | 2 | chart-engine | `E11-D05`, `E11-D06` |
| `E11-K01` | Spike: fix the SDF glyph set and atlas size for the design font (O2) | Spike | 2 | chart-engine | `E05`, `E11-T01` |
| `E11-S01` | Render via a dirty-flagged scene graph and budgeted frame scheduler | Story | 5 | chart-engine | `E11-T01` |
| `E11-S02` | Build the WebGL2 backend with capability probing and context-loss recovery | Story | 5 | chart-engine | `E11-S01` |
| `E11-S03` | Project time and price to screen through one shared, tick-precise transform | Story | 3 | chart-engine | `E11-S02` |
| `E11-S11` | Render all chart text from an SDF glyph atlas with instanced, batched draws | Story | 3 | chart-engine | `E11-S03`, `E11-K01` |
| `E11-T01` | Create packages/chart-engine with the public API surface and thin React bindings | Task | 3 | chart-engine | `E02`, `E06`, `E10` |
| `E11-T02` | Implement the OffscreenCanvas render worker, protocol and inline fallback | Task | 3 | chart-engine | `E11-T01` |
| `E11-T03` | Implement columnar typed-array data stores with append/patch/prepend mutations | Task | 3 | chart-engine | `E11-T02` |
| `E11-X01` | Build the STRIDE threat model for the chart engine and its data plane | Task | 3 | chart-engine | `E11-S01`, `E11-T03` |
| `E12-S01` | Build deterministic time bars from the trade tape with clock-driven closes | Story | 5 | data-feeds | `E12-T01` |
| `E12-S02` | Build tick and volume bars with exact splitting and volume conservation | Story | 5 | data-feeds | `E12-S01` |
| `E12-S03` | Build range and delta bars with no phantom bars and no delta splitting | Story | 5 | data-feeds | `E12-S02` |
| `E12-T01` | Implement the bar domain model: BarSpec, Bar, BarUpdate and spec_hash | Task | 3 | data-feeds | `E08` |
| `E12-T02` | Create the bars_* QuestDB tables, write path and retention policy | Task | 3 | data-feeds | `E12-T01`, `E07` |
| `E12-X01` | STRIDE threat model for bar builders, backfill and the bars topic | Task | 3 | data-feeds | `E12-T01` |
| `E13-D06` | Design handoff pack for E13 indicator surfaces | Task | 2 | indicators | `E13-D04`, `E13-D05` |
| `E13-K01` | Resolve O4: where each v1 indicator is computed (worker vs backend) | Spike | 2 | indicators | `E12` |
| `E14-D05` | Hi-fi design: Fibonacci, anchored VWAP and measure tool visual language | Task | 5 | web | `E14-D02`, `E14-D03` |
| `E14-D06` | Hi-fi design: long/short position tool and its send-to-ticket handoff | Task | 5 | web | `E14-D01`, `E14-D02` |
| `E14-D07` | Hi-fi design: drawings branch of the object tree & cross-chart sync (SCR-036) | Task | 3 | web | `E14-D02` |
| `E14-D08` | Design-system contribution: drawing primitives, tokens & CMP-191/CMP-223 entries | Task | 3 | web | `E14-D03`, `E14-D04` |
| `E14-D09` | Motion spec: drawing creation, selection, snap feedback and undo | Task | 2 | web | `E14-D03`, `E14-D04` |
| `E14-D10` | Accessibility design review & keyboard-draw screen-reader script for E14 | Task | 3 | web | `E14-D03`, `E14-D04`, `E14-D05`, `E14-D06`, `E14-D07` |
| `E14-D12` | Engineering handoff pack for the drawing-tools band | Task | 2 | web | `E14-D03`, `E14-D04`, `E14-D05`, `E14-D06`, `E14-D07`, `E14-D08` |
| `E14-K01` | Spike: keyboard-only drawing creation and canvas surrogate a11y pattern | Spike | 2 | drawing-tools | `E11` |
| `E14-T01` | drawings table migration and owner-scoped /drawings REST endpoints | Task | 5 | api | `E09` |
| `E14-T03` | Engine drawings layer: instanced thick lines, dashes, fills and SDF labels | Task | 5 | chart-engine | `E11` |
| `E14-T04` | Hit-test index, grab handles, multi-select and group transform | Task | 5 | chart-engine | `E14-T03` |
| `E15-D06` | Hi-fi design: SCR-023 cross-pane sync groups and price-scale linking | Task | 5 | web | `E15-D02` |
| `E15-D07` | Hi-fi design: SCR-024 panel picker and SCR-028 panel context menu | Task | 3 | web | `E15-D02` |
| `E15-D08` | Hi-fi design: SCR-025 workspace settings & SCR-029 unsaved / conflict dialog | Task | 3 | web | `E15-D02` |
| `E15-D09` | Hi-fi design: SCR-026 workspace import/export, preview and rejection states | Task | 3 | web | `E15-D02` |
| `E15-D10` | Hi-fi design: SCR-027 floating panel window (Electron) and its browser fallback | Task | 3 | web | `E15-D04` |
| `E15-D11` | Hi-fi design: SCR-049 multi-chart grid panel - cells, per-cell header, maximise | Task | 3 | web | `E15-D03`, `E15-D06` |
| `E15-D12` | Hi-fi design: responsive & reduced-capability layout (SCR-153, SCR-150 restore) | Task | 3 | web | `E15-D03` |
| `E15-D13` | Design-system contribution: layout tokens, dock primitives, catalogue entries | Task | 3 | web | `E15-D03`, `E15-D04`, `E15-D06` |
| `E15-D14` | Motion spec: docking, layout transitions, workspace switching and reduced motion | Task | 2 | web | `E15-D04` |
| `E15-D15` | Accessibility design review: keyboard model and screen-reader script (E15) | Task | 3 | web | `E15-D04`, `E15-D06`, `E15-D07`, `E15-D08` |
| `E15-D16` | Engineering handoff pack for the layouts & workspaces band | Task | 2 | web | `E15-D03`, `E15-D04`, `E15-D05`, `E15-D06`, `E15-D07`, `E15-D08`, `E15-D09`, `E15-D10`, `E15-D11`, `E15-D12`, `E15-D13`, `E15-D14` |
| `E15-K01` | Spike: pane-count budget curve and measured capability profile | Spike | 2 | web | `E11` |
| `E16-D04` | Design SCR-142 storage & database panel with tier health and projections | Task | 3 | web | `E16-D02` |
| `E16-D05` | Design recorder-dependent empty and partial-history states (SCR-047, SCR-151) | Task | 3 | web | `E16-D02` |
| `E16-D06` | Accessibility review and engineering handoff for the recorder design set | Task | 3 | web | `E16-D03`, `E16-D04`, `E16-D05` |
| `E16-T01` | Add migration 0007_recorder and the recorder repository layer | Task | 3 | api | `E07` |
| `E17-K01` | Measure binary vs JSON on the reference workspace and close ADR-0005's gate | Spike | 3 | api | `E08`, `E02` |
| `E17-S01` | Implement the WS connection lifecycle: negotiation, auth handshake, in-place re-auth and heartbeats | Story | 3 | api | `E17-T01`, `E09` |
| `E17-S02` | Implement subscriptions, the topic registry, per-topic authorisation and live revocation | Story | 5 | api | `E17-S01` |
| `E17-T01` | Build packages/protocol WS schema extraction, codegen and the ws_message_schemas gate | Task | 3 | api | `E02-T09` |
| `E17-T02` | Implement the CVWB binary frame codec (header + body kinds 1-6) in Python and TypeScript | Task | 3 | api | `E17-K01`, `E17-T01` |
| `E17-X01` | STRIDE threat model for the client WS protocol and gateway | Task | 3 | api | `E17-S02` |
| `E19-D01` | UX research: how traders read value, POC and profile period modes | Task | 3 | web | `E05` |
| `E50-T14` | Verify OC-01..OC-10 fixes are present in committed JSON (regression tests only) | Task | 1 | api | `E50-S01` |

### 7.5 Design-track deliverables due

**Design sprint D-S05** (roadmap 1.2) produces: Footprint cell design, profiles, Deep-Stats rows

> Consumed by engineering sprint **S07** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S07 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E11-D04` | Design the data-table alternative and the chart empty and error states | 5 | 2026-10-29 |
| `E11-D07` | Run an accessibility design review of the chart engine's canvas strategy | 3 | 2026-10-29 |
| `E11-D09` | Produce the chart-engine design handoff pack and run the engineering walkthrough | 2 | 2026-10-29 |
| `E13-D06` | Design handoff pack for E13 indicator surfaces | 2 | 2026-10-29 |
| `E14-D05` | Hi-fi design: Fibonacci, anchored VWAP and measure tool visual language | 5 | 2026-10-29 |
| `E14-D06` | Hi-fi design: long/short position tool and its send-to-ticket handoff | 5 | 2026-10-29 |
| `E14-D07` | Hi-fi design: drawings branch of the object tree & cross-chart sync (SCR-036) | 3 | 2026-10-29 |
| `E14-D08` | Design-system contribution: drawing primitives, tokens & CMP-191/CMP-223 entries | 3 | 2026-10-29 |
| `E14-D09` | Motion spec: drawing creation, selection, snap feedback and undo | 2 | 2026-10-29 |
| `E14-D10` | Accessibility design review & keyboard-draw screen-reader script for E14 | 3 | 2026-10-29 |
| `E14-D12` | Engineering handoff pack for the drawing-tools band | 2 | 2026-10-29 |
| `E15-D06` | Hi-fi design: SCR-023 cross-pane sync groups and price-scale linking | 5 | 2026-10-29 |
| `E15-D07` | Hi-fi design: SCR-024 panel picker and SCR-028 panel context menu | 3 | 2026-10-29 |
| `E15-D08` | Hi-fi design: SCR-025 workspace settings & SCR-029 unsaved / conflict dialog | 3 | 2026-10-29 |
| `E15-D09` | Hi-fi design: SCR-026 workspace import/export, preview and rejection states | 3 | 2026-10-29 |
| `E15-D10` | Hi-fi design: SCR-027 floating panel window (Electron) and its browser fallback | 3 | 2026-10-29 |
| `E15-D11` | Hi-fi design: SCR-049 multi-chart grid panel - cells, per-cell header, maximise | 3 | 2026-10-29 |
| `E15-D12` | Hi-fi design: responsive & reduced-capability layout (SCR-153, SCR-150 restore) | 3 | 2026-10-29 |
| `E15-D13` | Design-system contribution: layout tokens, dock primitives, catalogue entries | 3 | 2026-10-29 |
| `E15-D14` | Motion spec: docking, layout transitions, workspace switching and reduced motion | 2 | 2026-10-29 |
| `E15-D15` | Accessibility design review: keyboard model and screen-reader script (E15) | 3 | 2026-10-29 |
| `E15-D16` | Engineering handoff pack for the layouts & workspaces band | 2 | 2026-10-29 |
| `E16-D04` | Design SCR-142 storage & database panel with tier health and projections | 3 | 2026-10-29 |
| `E16-D05` | Design recorder-dependent empty and partial-history states (SCR-047, SCR-151) | 3 | 2026-10-29 |
| `E16-D06` | Accessibility review and engineering handoff for the recorder design set | 3 | 2026-10-29 |
| `E19-D01` | UX research: how traders read value, POC and profile period modes | 3 | 2026-10-29 |

Design total: **80 pts** across 26 tickets.

### 7.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: STRIDE R1 epics (s03, S05-S09)
- qa: E2E suite (web + Electron) (q04, S05-S10)

**QA tickets (0 pts, 0 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|

None scheduled. The qa pool works the continuous track bars above.

**Security tickets (9 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E11-X01` | Build the STRIDE threat model for the chart engine and its data plane | 3 | `E11-S01`, `E11-T03` |
| `E12-X01` | STRIDE threat model for bar builders, backfill and the bars topic | 3 | `E12-T01` |
| `E17-X01` | STRIDE threat model for the client WS protocol and gateway | 3 | `E17-S02` |

### 7.7 Risks & dependency watch-list

- **E11 engine core is on the critical path** (`E02->E06->E11->E12->E18->E26->E38->E44->E46->GA`). Staffed with the chart-engine lead + 2 FE; the benchmark harness must be in CI from day 1 so regressions surface same-day.
- E17 WS protocol is an interface-first contract: it must merge before any consumer story enters a sprint (DoR).

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S05 |
|---|---|---|
| `E14-D03` | Sprint 04 | 5 |
| `E15-D04` | Sprint 04 | 5 |
| `E14-D04` | Sprint 04 | 4 |
| `E15-D02` | Sprint 03 | 4 |
| `E15-D03` | Sprint 04 | 4 |
| `E08` | epic E08 (whole epic must be Done) | 3 |
| `E14-D02` | Sprint 03 | 3 |
| `E05` | epic E05 (whole epic must be Done) | 2 |
| `E02` | epic E02 (whole epic must be Done) | 2 |
| `E09` | epic E09 (whole epic must be Done) | 2 |
| `E16-D02` | Sprint 04 | 2 |
| `E11-D02` | Sprint 04 | 1 |
| _... 12 more_ | | |

### 7.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** A live candlestick chart panning and zooming at budget FPS on real Bybit WS data, end to end.

**Exit expectation:** Engine benchmark harness reporting in CI on every PR.

### 7.9 Burn-up - R1 train

| Sprint | Eng pts this sprint | Cumulative R1 | R1 total | Remaining | % complete |
|---|---|---|---|---|---|
| S05 **<- this sprint** | 90 | 90 | 407 | 317 | 22% |
| S06 | 90 | 180 | 407 | 227 | 44% |
| S07 | 47 | 227 | 407 | 180 | 56% |
| S08 | 90 | 317 | 407 | 90 | 78% |
| S09 | 90 | 407 | 407 | 0 | 100% |

---

## 8. S06 - 2026-10-30 -> 2026-11-05 (R1)

### 8.1 Sprint goal(s)

- Finish the WS protocol: subscription lifecycle, backpressure, reconnect/resume semantics (E17).
- Engine core interaction layer - crosshair, pan/zoom, LOD switching at target FPS (E11).
- Recorder retention and disk-budget enforcement (E16).
- **Planned over capacity: 101 eng pts vs 90 (+11).** Roadmap 13 forbids moving dates; resolve at sprint planning per section 31, never mid-sprint.

### 8.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 90 | 90 | +0 | ok |
| Design (D) | 10 | 60 | +50 | ok |
| QA (Q) | 17 | 45 | +28 | ok |
| Security (X) | 8 | 20 | +12 | ok |
| **Total** | **125** | **215** | **+90** | |

### 8.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E11** | Chart engine core (scene, axes, interaction, LOD) | Chart Engine (FE-Engine) | 33 | 9 |
| **E17** | Market-data WS protocol & binary framing | Data & Feeds (BE-Feeds) | 31 | 8 |
| **E12** | Bar builders & series rendering (time/tick/volume/range/renko) | Data & Feeds (BE-Feeds) | 22 | 7 |
| **E16** | Recorder, retention & disk budget | Data & Feeds (BE-Feeds) | 14 | 4 |
| **E15** | Layouts & workspaces | App & Charting UI (FE-App) | 12 | 3 |
| **E14** | Drawing tools | App & Charting UI (FE-App) | 5 | 1 |
| **E19** | Volume / delta / TPO profiles | Order Flow (BE-Flow + FE-Engine) | 5 | 1 |
| **E21** | DOM ladder & liquidity heatmap | Order Flow (BE-Flow + FE-Engine) | 3 | 1 |


**Statechart lane:** E16 (`E16-Q01`, `E16-T02`, `E16-T03`, `E16-X01`); E17 (`E17-D04`, `E17-Q01`, `E17-Q02`, `E17-S03`, `E17-T03`, `E17-T04`, `E17-T08`, `E17-X02`); E19 (`E19-D02`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 8.4 Tickets (34)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E11-Q01` | Write the black-box test plan for chart navigation, scales, crosshair and axes | Task | 3 | chart-engine | `E11-S07` |
| `E11-S04` | Pan and zoom with cursor-anchored zoom, momentum and keyboard equivalents | Story | 5 | chart-engine | `E11-S03`, `E11-D06` |
| `E11-S05` | Support linear, log, percent and inverted scales with autoscale and lock | Story | 5 | chart-engine | `E11-S03`, `E11-D03` |
| `E11-S06` | Render price and time axes with label decimation and keyboard rescale | Story | 5 | chart-engine | `E11-S05`, `E11-S11`, `E11-D02` |
| `E11-S07` | Show a synced crosshair with an OHLCV readout and a bar-close countdown | Story | 5 | chart-engine | `E11-S04`, `E11-S06` |
| `E11-S08` | Pick chart objects in under 1 ms via structural and uniform-grid indices | Story | 3 | chart-engine | `E11-S03`, `E11-T03` |
| `E11-T04` | Ingest design-system theme tokens, colour LUTs and density modes into the engine | Task | 2 | chart-engine | `E11-S01`, `E05`, `E11-D05` |
| `E11-T08` | Build a deterministic golden-image regression harness running on SwiftShader | Task | 3 | chart-engine | `E11-S06` |
| `E11-X02` | Configure SAST, SCA and CI guardrails for the chart-engine package | Task | 2 | chart-engine | `E11-X01` |
| `E12-Q01` | Black-box test plan for the E12 bar-builder and series story groups | Task | 3 | chart-engine | `E12-S01`, `E12-S03`, `E12-T02`, `E12-T05` |
| `E12-S05` | Backfill historical OHLCV from Bybit klines with paging, cache and backoff | Story | 5 | data-feeds | `E12-T02`, `E12-S01` |
| `E12-S06` | Render candlestick and OHLC bar series through the WebGL engine | Story | 5 | chart-engine | `E12-T05`, `E11` |
| `E12-S10` | Show the forming bar distinctly from closed bars with a live countdown | Story | 1 | chart-engine | `E12-T06`, `E12-S06` |
| `E12-T03` | Implement BarBuilderSet fan-out with snapshot/restore state persistence | Task | 3 | data-feeds | `E12-S01`, `E12-S02`, `E12-T02` |
| `E12-T05` | Implement GET /market/klines and GET /market/bars with source metadata | Task | 3 | api | `E12-S05`, `E12-T03` |
| `E12-T06` | Publish the bars.{symbol}.{bar_type}.{param} WS topic with snapshot and deltas | Task | 2 | api | `E12-T05`, `E17` |
| `E14-T02` | Client DrawingStore: optimistic sync, debounced batch writes and undo/redo stack | Task | 5 | web | `E14-T01`, `E14-T03` |
| `E15-S01` | Grid presets, preset gallery and layout hotkeys (SCR-022) | Story | 2 | web | `E15-T02`, `E15-K01`, `E05` |
| `E15-T01` | workspaces/layouts/layout_panes migration and /workspaces REST API | Task | 5 | api | `E09` |
| `E15-T02` | packages/dock: layout tree, reconciler and DockGrid without GL churn | Task | 5 | web | `E15-K01`, `E11`, `E10` |
| `E16-Q01` | Write the black-box test plan for recorder lifecycle, retention and disk budget | Task | 3 | cross-cutting | `E16-D06` |
| `E16-T02` | Implement RecordingPolicy: effective set, auto-record triggers, grace period | Task | 3 | data-feeds | `E16-T01`, `E08`, `E50-T59`, `E50-S01` |
| `E16-T03` | Implement StreamWriter: batched QuestDB writes, WAL spill and recovery | Task | 5 | data-feeds | `E16-T02`, `E07` |
| `E16-X01` | STRIDE threat model and abuse cases for the recorder and storage subsystem | Task | 3 | cross-cutting | `E16-T01` |
| `E17-D04` | Design QA and accessibility review of the shipped connection-state chrome | Task | 2 | web | `E17-D02`, `E17-T04` |
| `E17-Q01` | Build the WS protocol conformance suite and the black-box test plan | Task | 5 | api | `E17-S03`, `E17-T01` |
| `E17-Q02` | Build and run the WS chaos scenarios: upstream loss, slow consumer, burst and restart | Task | 3 | api | `E17-T03` |
| `E17-S03` | Implement snapshot+delta sequencing, resync triggers and snapshot chunking | Story | 5 | api | `E17-S02`, `E17-T02` |
| `E17-T03` | Implement per-topic coalescing, adaptive throttling and bounded-queue backpressure | Task | 5 | api | `E17-S03` |
| `E17-T04` | Build the web WS client: reconnect, gap detection, visibility throttling and worker decode | Task | 5 | web | `E17-S03`, `E17-T02`, `E17-D02` |
| `E17-T08` | Statechart-backed WS topic: machines.{entity}.state (state/enum, snapshot+delta, per-entity RBAC) | Task | 3 | api | `E17-S02`, `E17-S03`, `E50-T60` |
| `E17-X02` | Security review, abuse cases, decoder fuzzing and SAST/DAST rules for the WS surface | Task | 3 | api | `E17-X01`, `E17-T02`, `E17-T03` |
| `E19-D02` | Wireframes: SCR-038 profile panel and SCR-039 settings dialog | Task | 5 | web | `E19-D01`, `E05` |
| `E21-D01` | UX research: how traders read a ladder and a liquidity trail | Task | 3 | web | `E05` |

### 8.5 Design-track deliverables due

**Design sprint D-S06** (roadmap 1.2) produces: DOM ladder + heatmap, big-trade bubbles, tape

> Consumed by engineering sprint **S08** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S08 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E17-D04` | Design QA and accessibility review of the shipped connection-state chrome | 2 | 2026-11-05 |
| `E19-D02` | Wireframes: SCR-038 profile panel and SCR-039 settings dialog | 5 | 2026-11-05 |
| `E21-D01` | UX research: how traders read a ladder and a liquidity trail | 3 | 2026-11-05 |

Design total: **10 pts** across 3 tickets.

### 8.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: STRIDE R1 epics (s03, S05-S09)
- qa: Golden-fixture corpus (q03, S06-S09)
- qa: E2E suite (web + Electron) (q04, S05-S10)

**QA tickets (17 pts, 5 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E11-Q01` | Write the black-box test plan for chart navigation, scales, crosshair and axes | 3 | `E11-S07` |
| `E12-Q01` | Black-box test plan for the E12 bar-builder and series story groups | 3 | `E12-S01`, `E12-S03`, `E12-T02`, `E12-T05` |
| `E16-Q01` | Write the black-box test plan for recorder lifecycle, retention and disk budget | 3 | `E16-D06` |
| `E17-Q01` | Build the WS protocol conformance suite and the black-box test plan | 5 | `E17-S03`, `E17-T01` |
| `E17-Q02` | Build and run the WS chaos scenarios: upstream loss, slow consumer, burst and restart | 3 | `E17-T03` |

**Security tickets (8 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E11-X02` | Configure SAST, SCA and CI guardrails for the chart-engine package | 2 | `E11-X01` |
| `E16-X01` | STRIDE threat model and abuse cases for the recorder and storage subsystem | 3 | `E16-T01` |
| `E17-X02` | Security review, abuse cases, decoder fuzzing and SAST/DAST rules for the WS surface | 3 | `E17-X01`, `E17-T02`, `E17-T03` |

### 8.7 Risks & dependency watch-list

- E17 at 38 pts plus E11 at 36 pts loads both the platform and engine leads simultaneously - watch for review bottlenecks.
- Recorder disk-budget enforcement can silently drop data if misconfigured; needs a chaos test, not just a unit test.
- Holiday sprint S07 follows: nothing started here should require S07 completion.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S06 |
|---|---|---|
| `E12-T02` | Sprint 05 | 4 |
| `E11` | epic E11 (whole epic must be Done) | 4 |
| `E11-S03` | Sprint 05 | 3 |
| `E05` | epic E05 (whole epic must be Done) | 3 |
| `E12-S01` | Sprint 05 | 3 |
| `E07` | epic E07 (whole epic must be Done) | 3 |
| `E17-T02` | Sprint 05 | 3 |
| `E12-S03` | Sprint 05 | 2 |
| `E08` | epic E08 (whole epic must be Done) | 2 |
| `E17-D02` | Sprint 04 | 2 |
| `E11-D06` | Sprint 04 | 1 |
| `E11-D03` | Sprint 04 | 1 |
| _... 17 more_ | | |

### 8.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** WS reconnect/resume demonstrated by killing the feed mid-stream; recorder retention prunes to budget on demand.

**Exit expectation:** Chaos test for WS disconnect passes.

### 8.9 Burn-up - R1 train

| Sprint | Eng pts this sprint | Cumulative R1 | R1 total | Remaining | % complete |
|---|---|---|---|---|---|
| S05 | 90 | 90 | 407 | 317 | 22% |
| S06 **<- this sprint** | 90 | 180 | 407 | 227 | 44% |
| S07 | 47 | 227 | 407 | 180 | 56% |
| S08 | 90 | 317 | 407 | 90 | 78% |
| S09 | 90 | 407 | 407 | 0 | 100% |

---

## 9. S07 - 2026-11-06 -> 2026-11-12 (R1)

### 9.1 Sprint goal(s)

- **Holiday sprint - 45 pts capacity, plan accordingly.** Do not start new critical-path work.
- Indicators framework lands its evaluation core and first indicator set (E13).
- Engine core hardening and benchmark-harness stabilisation (E11).
- **Planned over capacity: 61 eng pts vs 45 (+16).** Roadmap 13 forbids moving dates; resolve at sprint planning per section 31, never mid-sprint.

### 9.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 47 | 45 | -2 | **OVER** |
| Design (D) | 18 | 60 | +42 | ok |
| QA (Q) | 32 | 45 | +13 | ok |
| Security (X) | 9 | 20 | +11 | ok |
| **Total** | **106** | **170** | **+64** | |

### 9.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E13** | Indicators framework & v1 indicator set | App & Charting UI (FE-App) | 32 | 7 |
| **E14** | Drawing tools | App & Charting UI (FE-App) | 17 | 5 |
| **E15** | Layouts & workspaces | App & Charting UI (FE-App) | 16 | 4 |
| **E12** | Bar builders & series rendering (time/tick/volume/range/renko) | Data & Feeds (BE-Feeds) | 13 | 3 |
| **E19** | Volume / delta / TPO profiles | Order Flow (BE-Flow + FE-Engine) | 8 | 2 |
| **E11** | Chart engine core (scene, axes, interaction, LOD) | Chart Engine (FE-Engine) | 5 | 1 |
| **E21** | DOM ladder & liquidity heatmap | Order Flow (BE-Flow + FE-Engine) | 5 | 1 |
| **E50** | xstate-statemachine adoption: factory, persistence, plugins, contract suite, catalogue | Platform & DevSecOps | 5 | 1 |
| **E26** | Replay engine & scrubbing | Data & Feeds (BE-Feeds) | 3 | 1 |
| **E22** | Big trades & bubbles: tape, thresholds, clustering and the bubble overlay | Order Flow (BE-Flow + FE-Engine) | 2 | 1 |


**Statechart lane:** E19 (`E19-D03`, `E19-D04`); E50 (`E50-Q01`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 9.4 Tickets (26)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E11-S12` | Select LOD with hysteresis and decimate candles without losing spikes | Story | 5 | chart-engine | `E11-S03`, `E11-T04` |
| `E12-Q03` | Playwright E2E for bar modes, series types and timeframe switching | Task | 5 | chart-engine | `E12-Q01`, `E12-S01`, `E12-S02`, `E12-S03`, `E12-S05` |
| `E12-Q04` | Contract tests for /market/klines, /market/bars and the bars WS topic | Task | 3 | api | `E12-T05`, `E12-T06`, `E12-Q01` |
| `E12-S09` | Decimate series by LOD tier with hysteresis and min/max spike preservation | Story | 5 | chart-engine | `E12-S06`, `E11` |
| `E13-Q01` | Black-box test plan for the indicator framework and v1 set | Task | 3 | indicators | `E13-D06` |
| `E13-S01` | Add, configure and remove indicators from the chart | Story | 5 | indicators | `E13-T01`, `E13-T02`, `E13-T03`, `E13-D06` |
| `E13-S02` | Moving-average family indicators (SMA, EMA, WMA, VWMA, SMMA, DEMA, TEMA, ribbon) | Story | 3 | indicators | `E13-T01`, `E13-T02`, `E13-D06` |
| `E13-T01` | Indicator plugin API and worker-hosted runtime in packages/chart-engine | Task | 8 | indicators | `E13-K01`, `E11`, `E12` |
| `E13-T02` | Backend indicator kernel (M9), MetricRegistry bindings and GET /indicators | Task | 8 | indicators | `E13-K01`, `E12` |
| `E13-T03` | Indicator presets: migration, CRUD endpoints and built-in seed data | Task | 2 | indicators | `E13-T02` |
| `E13-X01` | STRIDE threat model and abuse cases for the indicator framework | Task | 3 | indicators | `E13-K01` |
| `E14-Q01` | Black-box test plan for the E14 drawing-tools story groups | Task | 3 | drawing-tools | `E14-T02`, `E14-T04`, `E14-S10` |
| `E14-Q02` | Geometry & persistence conformance suite for drawing anchoring | Task | 5 | drawing-tools | `E14-Q01`, `E14-T03`, `E14-T04` |
| `E14-Q04` | Contract tests for the /drawings REST surface including batch | Task | 3 | api | `E14-T01` |
| `E14-S10` | Drawing toolbar and properties popover (SCR-037) | Story | 3 | drawing-tools | `E14-T02`, `E14-T04`, `E14-K01` |
| `E14-X01` | STRIDE threat model for drawings persistence, sync and annotation content | Task | 3 | drawing-tools | `E14-T01` |
| `E15-Q01` | Black-box test plan for the E15 layout, workspace and sync story groups | Task | 5 | web | `E15-S01`, `E15-S02`, `E15-T03` |
| `E15-S02` | Panel docking, floating windows, panel picker and panel menu | Story | 5 | web | `E15-T02`, `E10`, `E05` |
| `E15-T03` | SyncBus: cross-pane crosshair, symbol, interval and time-range propagation | Task | 3 | chart-engine | `E15-T02`, `E11` |
| `E15-X01` | STRIDE threat model for workspaces, layout persistence and export/import | Task | 3 | web | `E15-S02` |
| `E19-D03` | Hi-fi SCR-038/SCR-039 and design-system contribution for profile primitives | Task | 5 | web | `E19-D02` |
| `E19-D04` | Design the profile preset, period-anchoring and drawing-anchor flows | Task | 3 | web | `E19-D02` |
| `E21-D02` | Wireframe to hi-fi SCR-050 Heatmap + DOM ladder panel | Task | 5 | web | `E21-D01`, `E05` |
| `E22-D01` | UX research: how traders read the tape and size on the chart | Task | 2 | web | `E08` |
| `E26-D01` | UX research: how traders study a recorded session and what replay must not hide | Task | 3 | web | `E16-D01` |
| `E50-Q01` | Invariant and chaos suite over every §Bn.7 invariant | Task | 5 | api | `E50-T31` |

### 9.5 Design-track deliverables due

**Design sprint D-S07** (roadmap 1.2) produces: CVD/derivatives panes, detector badges + "(estimated)" pattern

> Consumed by engineering sprint **S09** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S09 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E19-D03` | Hi-fi SCR-038/SCR-039 and design-system contribution for profile primitives | 5 | 2026-11-12 |
| `E19-D04` | Design the profile preset, period-anchoring and drawing-anchor flows | 3 | 2026-11-12 |
| `E21-D02` | Wireframe to hi-fi SCR-050 Heatmap + DOM ladder panel | 5 | 2026-11-12 |
| `E22-D01` | UX research: how traders read the tape and size on the chart | 2 | 2026-11-12 |
| `E26-D01` | UX research: how traders study a recorded session and what replay must not hide | 3 | 2026-11-12 |

Design total: **18 pts** across 5 tickets.

### 9.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: STRIDE R1 epics (s03, S05-S09)
- qa: Golden-fixture corpus (q03, S06-S09)
- qa: E2E suite (web + Electron) (q04, S05-S10)

**QA tickets (32 pts, 8 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E12-Q03` | Playwright E2E for bar modes, series types and timeframe switching | 5 | `E12-Q01`, `E12-S01`, `E12-S02`, `E12-S03`, `E12-S05` |
| `E12-Q04` | Contract tests for /market/klines, /market/bars and the bars WS topic | 3 | `E12-T05`, `E12-T06`, `E12-Q01` |
| `E13-Q01` | Black-box test plan for the indicator framework and v1 set | 3 | `E13-D06` |
| `E14-Q01` | Black-box test plan for the E14 drawing-tools story groups | 3 | `E14-T02`, `E14-T04`, `E14-S10` |
| `E14-Q02` | Geometry & persistence conformance suite for drawing anchoring | 5 | `E14-Q01`, `E14-T03`, `E14-T04` |
| `E14-Q04` | Contract tests for the /drawings REST surface including batch | 3 | `E14-T01` |
| `E15-Q01` | Black-box test plan for the E15 layout, workspace and sync story groups | 5 | `E15-S01`, `E15-S02`, `E15-T03` |
| `E50-Q01` | Invariant and chaos suite over every §Bn.7 invariant | 5 | `E50-T31` |

**Security tickets (9 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E13-X01` | STRIDE threat model and abuse cases for the indicator framework | 3 | `E13-K01` |
| `E14-X01` | STRIDE threat model for drawings persistence, sync and annotation content | 3 | `E14-T01` |
| `E15-X01` | STRIDE threat model for workspaces, layout persistence and export/import | 3 | `E15-S02` |

### 9.7 Risks & dependency watch-list

- **45-pt capacity.** Any item carried in at full estimate will slip. The 45-pt shortfall is absorbed by the train buffer, never by weakening R1 exit criteria.
- Design sprint D-S07 is also reduced - CVD/detector designs may arrive thin; verify before S09 planning.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S07 |
|---|---|---|
| `E11` | epic E11 (whole epic must be Done) | 3 |
| `E12` | epic E12 (whole epic must be Done) | 3 |
| `E13-D06` | Sprint 05 | 3 |
| `E14-T04` | Sprint 05 | 3 |
| `E15-T02` | Sprint 06 | 3 |
| `E05` | epic E05 (whole epic must be Done) | 3 |
| `E12-Q01` | Sprint 06 | 2 |
| `E12-S05` | Sprint 06 | 2 |
| `E12-T05` | Sprint 06 | 2 |
| `E14-T02` | Sprint 06 | 2 |
| `E14-T01` | Sprint 05 | 2 |
| `E19-D02` | Sprint 06 | 2 |
| _... 19 more_ | | |

### 9.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Indicator overlay and pane rendering on the live chart with parameter editing.

**Exit expectation:** Reduced-scope review; no gate.

### 9.9 Burn-up - R1 train

| Sprint | Eng pts this sprint | Cumulative R1 | R1 total | Remaining | % complete |
|---|---|---|---|---|---|
| S05 | 90 | 90 | 407 | 317 | 22% |
| S06 | 90 | 180 | 407 | 227 | 44% |
| S07 **<- this sprint** | 47 | 227 | 407 | 180 | 56% |
| S08 | 90 | 317 | 407 | 90 | 78% |
| S09 | 90 | 407 | 407 | 0 | 100% |

---

## 10. S08 - 2026-11-13 -> 2026-11-19 (R1)

### 10.1 Sprint goal(s)

- Recorder, retention and disk budget complete - the heaviest sprint for E16 (47 pts, half the epic).
- Indicator v1 set finishes: overlays, panes, parameter UI (E13).
- Replay engine and footprint groundwork begin one train early (E26, E18).
- **QA is over pool: 60 pts vs 45 (+15).**

### 10.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 90 | 90 | +0 | ok |
| Design (D) | 59 | 60 | +1 | ok |
| QA (Q) | 59 | 45 | -14 | **OVER** |
| Security (X) | 18 | 20 | +2 | ok |
| **Total** | **226** | **215** | **-11** | |

### 10.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E16** | Recorder, retention & disk budget | Data & Feeds (BE-Feeds) | 51 | 17 |
| **E13** | Indicators framework & v1 indicator set | App & Charting UI (FE-App) | 38 | 13 |
| **E14** | Drawing tools | App & Charting UI (FE-App) | 29 | 8 |
| **E11** | Chart engine core (scene, axes, interaction, LOD) | Chart Engine (FE-Engine) | 19 | 6 |
| **E26** | Replay engine & scrubbing | Data & Feeds (BE-Feeds) | 19 | 6 |
| **E12** | Bar builders & series rendering (time/tick/volume/range/renko) | Data & Feeds (BE-Feeds) | 16 | 4 |
| **E18** | Footprint: cell aggregation, imbalance detection and cell rendering | Order Flow (BE-Flow + FE-Engine) | 12 | 5 |
| **E15** | Layouts & workspaces | App & Charting UI (FE-App) | 11 | 3 |
| **E21** | DOM ladder & liquidity heatmap | Order Flow (BE-Flow + FE-Engine) | 10 | 4 |
| **E08** | Bybit adapter & ingestion skeleton | Data & Feeds (BE-Feeds) | 8 | 2 |
| **E19** | Volume / delta / TPO profiles | Order Flow (BE-Flow + FE-Engine) | 7 | 3 |
| **E22** | Big trades & bubbles: tape, thresholds, clustering and the bubble overlay | Order Flow (BE-Flow + FE-Engine) | 6 | 2 |


**Statechart lane:** E16 (`E16-K01`, `E16-Q02`, `E16-Q03`, `E16-Q04`, `E16-Q05`, `E16-Q06`, `E16-S01`, `E16-S03`, `E16-S04`, `E16-S05`, `E16-T04`, `E16-T05`, `E16-T06`, `E16-T07`, `E16-T08`, `E16-T10`, `E16-X02`); E18 (`E18-D01`, `E18-D02`, `E18-D03`, `E18-D04`, `E18-D05`); E19 (`E19-D05`, `E19-D06`, `E19-D07`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 10.4 Tickets (73)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E08-Q05` | E2E and a11y audit: watchlist, symbol search, data-confidence states | Task | 5 | web | `E08-Q01`, `E08-S03`, `E08-D03`, `E08-D07`, `E08-S08`, `E08-S09`, `E08-S10`, `E08-S11` |
| `E08-Q06` | Exploratory charters, E08 regression pack and epic QA sign-off for R0 exit | Task | 3 | data-feeds | `E08-Q02`, `E08-Q03`, `E08-Q04`, `E08-Q05` |
| `E11-Q02` | Build the Playwright E2E suite for chart interaction, multi-pane and sync | Task | 5 | chart-engine | `E11-S09`, `E11-Q01` |
| `E11-Q03` | Establish and sign off the engine performance baselines against the budgets | Task | 3 | chart-engine | `E11-T06`, `E11-S15` |
| `E11-S09` | Stack panes on a shared time axis and sync range, crosshair and levels | Story | 3 | chart-engine | `E11-S01`, `E11-S07` |
| `E11-S10` | Render device-pixel-correct at any DPI and survive resize and monitor changes | Story | 2 | chart-engine | `E11-S02` |
| `E11-S15` | Govern chart memory with a budget, eviction and days-to-load estimates | Story | 3 | chart-engine | `E11-T03`, `E11-S12` |
| `E11-T06` | Make the engine benchmark harness a required CI check with enforced baselines | Task | 3 | chart-engine | `E11-S12`, `E11-T08` |
| `E12-D13` | Design QA of the built bar modes, series rendering and their states | Task | 3 | chart-engine | `E12-D12` |
| `E12-S11` | Switch symbol and timeframe without tearing down the engine | Story | 5 | chart-engine | `E12-S09`, `E12-S10` |
| `E12-X02` | Abuse cases: parameter fuzzing, resource exhaustion and data-integrity attacks | Task | 5 | api | `E12-X01`, `E12-T05`, `E12-T06` |
| `E12-X03` | SAST/DAST rules and CI security gates for the bar and market-data surface | Task | 3 | infra | `E12-X01`, `E12-T02`, `E12-S05` |
| `E13-D07` | Design QA of the built indicator surfaces | Task | 2 | indicators | `E13-S01`, `E13-S03` |
| `E13-Q02` | Playwright E2E suite additions for indicators (web and Electron) | Task | 3 | indicators | `E13-S01`, `E13-S03`, `E13-S08` |
| `E13-Q03` | Indicator performance benchmark and CI regression gate | Task | 3 | indicators | `E13-S03`, `E13-S05` |
| `E13-Q04` | Accessibility audit of the indicator surfaces (axe-core plus manual SR pass) | Task | 3 | indicators | `E13-S01`, `E13-S03` |
| `E13-Q05` | Parity and fixture regression pack for indicator values | Task | 3 | indicators | `E13-S05`, `E13-S06`, `E13-S07` |
| `E13-Q06` | Exploratory charters, chaos scenarios and E13 QA sign-off | Task | 3 | indicators | `E13-Q02`, `E13-Q03`, `E13-Q04`, `E13-Q05` |
| `E13-S03` | Oscillators in linked sub-panes (RSI, MACD, Stochastic, CCI, Williams %R) | Story | 5 | indicators | `E13-S02`, `E13-S01` |
| `E13-S04` | Volatility and band indicators (Bollinger, ATR, ADX, Keltner, Donchian) | Story | 3 | indicators | `E13-S02`, `E13-D06` |
| `E13-S05` | Trend tools: Supertrend, Zig Zag, Ichimoku and Parabolic SAR | Story | 3 | indicators | `E13-S04` |
| `E13-S06` | Volume indicators: histogram, volume MA, OBV and delta-aware colouring | Story | 3 | indicators | `E13-S02`, `E13-D06` |
| `E13-S07` | Session and anchored VWAP as indicators with sigma envelopes | Story | 2 | indicators | `E13-S02`, `E13-D06` |
| `E13-S08` | Expose every enabled indicator as a named metric for alerts and rules | Story | 3 | indicators | `E13-S04`, `E13-S06`, `E13-S01` |
| `E13-X02` | Security review of indicator endpoints, presets and metric exposure | Task | 2 | indicators | `E13-X01`, `E13-T03`, `E13-S08` |
| `E14-Q03` | Playwright E2E: drawing lifecycle, object tree and cross-chart sync | Task | 5 | drawing-tools | `E14-Q01`, `E14-S03`, `E14-S04` |
| `E14-Q05` | Performance pack: drag FPS with 200 drawings, dense tree and batch write load | Task | 5 | drawing-tools | `E14-T03`, `E14-T04`, `E14-S03` |
| `E14-Q06` | Chaos scenarios for drawings: offline edits, conflicts and partial batch failure | Task | 3 | drawing-tools | `E14-T02`, `E14-Q04` |
| `E14-S01` | Horizontal line, horizontal ray and vertical line with server persistence | Story | 2 | drawing-tools | `E14-S10` |
| `E14-S02` | Trendline, ray and extended line with magnet-to-OHLC snapping | Story | 3 | drawing-tools | `E14-S01` |
| `E14-S03` | Rectangle, ellipse, parallel channel and triangle zone tools | Story | 3 | drawing-tools | `E14-S02` |
| `E14-S04` | Fibonacci retracement, extension and time-zone tools with configurable levels | Story | 3 | drawing-tools | `E14-S02` |
| `E14-X02` | Abuse cases: stored XSS in annotations, IDOR on /drawings and payload exhaustion | Task | 5 | drawing-tools | `E14-X01`, `E14-Q04` |
| `E15-Q03` | Functional pack for cross-pane sync groups and price-scale linking | Task | 3 | web | `E15-Q01`, `E15-S03`, `E15-S04` |
| `E15-S03` | Saved workspaces: switcher, settings, restore and conflict handling | Story | 5 | web | `E15-T01`, `E15-T02`, `E13`, `E14` |
| `E15-S04` | Cross-pane sync configuration: groups and per-axis toggles (SCR-023) | Story | 3 | web | `E15-T03`, `E05` |
| `E16-K01` | Spike S6: measure real GB/day per stream for BTCUSDT and ETHUSDT | Spike | 2 | data-feeds | `E07`, `E08` |
| `E16-Q02` | Automate the E2E suite for recorder lifecycle, retention and empty states | Task | 3 | cross-cutting | `E16-Q01`, `E16-S01`, `E16-S03`, `E16-S04`, `E16-S05` |
| `E16-Q03` | Run the exploratory charter for recorder surprise, honesty and data-loss traps | Task | 2 | cross-cutting | `E16-S01`, `E16-S03`, `E16-S04`, `E16-S05` |
| `E16-Q04` | Build the recorder perf, soak and disk-pressure chaos scripts | Task | 3 | cross-cutting | `E16-Q01`, `E16-T07`, `E16-T05` |
| `E16-Q05` | Run the accessibility audit for the recorder screens and empty-state pattern | Task | 2 | web | `E16-S01`, `E16-S03`, `E16-S04`, `E16-S05` |
| `E16-Q06` | Assemble the recorder regression pack and record epic QA sign-off | Task | 2 | cross-cutting | `E16-Q02`, `E16-Q03`, `E16-Q04`, `E16-Q05` |
| `E16-S01` | Build SCR-140 recorder & storage screen with the recorded-symbol list | Story | 5 | web | `E16-T08`, `E16-D06`, `E10`, `E09` |
| `E16-S03` | Build SCR-141 retention policy editor with destructive-change preview | Story | 3 | web | `E16-S01`, `E16-T06`, `E16-D06` |
| `E16-S04` | Build SCR-142 storage panel with tier health, projections and import progress | Story | 3 | web | `E16-S01`, `E16-T07`, `E16-T10`, `E16-D06` |
| `E16-S05` | Implement recorder-dependent empty and partial-history states (SCR-047, SCR-151) | Story | 2 | web | `E16-T04`, `E16-D05`, `E11` |
| `E16-T04` | Implement recording sessions, gap detection and the data-coverage service | Task | 2 | data-feeds | `E16-T03`, `E50-T59`, `E50-S01`, `E50-T49` |
| `E16-T05` | Implement RollOffJob: verified hot-to-cold Parquet export and weekly compaction | Task | 3 | infra | `E16-T03`, `E07` |
| `E16-T06` | Implement RetentionManager: policy resolution, dry-run preview, reaper and purge | Task | 5 | api | `E16-T05`, `E16-T01` |
| `E16-T07` | Implement DiskBudget: measured growth, projection and the disk-pressure ladder | Task | 3 | infra | `E16-T03`, `E16-K01` |
| `E16-T08` | Implement the recording REST surface and the recorder WS topic | Task | 5 | api | `E16-T04`, `E16-T06`, `E16-T07`, `E17` |
| `E16-T10` | Implement resumable bulk import of Bybit public trade archives | Task | 3 | data-feeds | `E16-T05` |
| `E16-X02` | Security review: destructive paths, RBAC, path containment, config gating | Task | 3 | cross-cutting | `E16-X01`, `E16-T06`, `E16-T08`, `E16-T10` |
| `E18-D01` | UX research: how order-flow traders read and act on footprint cells | Task | 2 | chart-engine | `E12` |
| `E18-D02` | Wireframe the footprint layer on SCR-030, SCR-032 and the SCR-056 imbalance rows | Task | 3 | chart-engine | `E18-D01` |
| `E18-D03` | Hi-fi footprint designs and design-system entries for the cell components | Task | 3 | chart-engine | `E18-D02` |
| `E18-D04` | Motion spec and accessibility review for the footprint surfaces | Task | 2 | chart-engine | `E18-D03` |
| `E18-D05` | Design handoff pack for E18 with sign-off | Task | 2 | chart-engine | `E18-D03`, `E18-D04` |
| `E19-D05` | Motion spec: developing value area, recompute and profile transitions | Task | 2 | web | `E19-D03` |
| `E19-D06` | Accessibility design review of the profile panel and settings dialog | Task | 2 | web | `E19-D03`, `E19-D04`, `E19-D05` |
| `E19-D07` | Engineering handoff pack for the profile surface (SCR-038/039, CMP-110/183/184) | Task | 3 | web | `E19-D06` |
| `E21-D03` | Hi-fi SCR-051 settings dialog and the SCR-153 depth-shed banner variant | Task | 3 | web | `E21-D02` |
| `E21-D04` | Design-system contributions: ladder, heatmap and own-order components | Task | 3 | web | `E21-D02` |
| `E21-D05` | Motion and reduced-motion spec for the trail, re-centring and resync states | Task | 2 | web | `E21-D02` |
| `E21-D06` | Accessibility design review of the ladder grid and windowed heatmap reveal | Task | 2 | web | `E21-D02`, `E21-D03`, `E21-D04` |
| `E22-D02` | Wireframe SCR-053 tape + bubble panel with all states | Task | 3 | web | `E22-D01` |
| `E22-D03` | Hi-fi SCR-053 and design-system entry for CMP-112 BigTradeBubble | Task | 3 | web | `E22-D02` |
| `E26-D02` | Wireframe to hi-fi SCR-097 replay page: transport, coverage scrubber, states | Task | 5 | web | `E26-D01` |
| `E26-D03` | Hi-fi SCR-098 replay setup modal with coverage timeline and honest preparation | Task | 3 | web | `E26-D02` |
| `E26-D04` | Hi-fi SCR-099 replay paper-trading results with simulated framing throughout | Task | 3 | web | `E26-D02` |
| `E26-D05` | Design-system entries for CMP-170, CMP-171 and CMP-172 replay components | Task | 3 | web | `E26-D02` |
| `E26-D06` | Motion spec and accessibility design review for the replay transport and chrome | Task | 3 | web | `E26-D05`, `E26-D03`, `E26-D04` |
| `E26-D07` | Produce the replay design handoff pack and run the engineering handoff session | Task | 2 | web | `E26-D06` |

### 10.5 Design-track deliverables due

**Design sprint D-S08** (roadmap 1.2) produces: Replay UI, alerts UI

> Consumed by engineering sprint **S10** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S10 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E12-D13` | Design QA of the built bar modes, series rendering and their states | 3 | 2026-11-19 |
| `E13-D07` | Design QA of the built indicator surfaces | 2 | 2026-11-19 |
| `E18-D01` | UX research: how order-flow traders read and act on footprint cells | 2 | 2026-11-19 |
| `E18-D02` | Wireframe the footprint layer on SCR-030, SCR-032 and the SCR-056 imbalance rows | 3 | 2026-11-19 |
| `E18-D03` | Hi-fi footprint designs and design-system entries for the cell components | 3 | 2026-11-19 |
| `E18-D04` | Motion spec and accessibility review for the footprint surfaces | 2 | 2026-11-19 |
| `E18-D05` | Design handoff pack for E18 with sign-off | 2 | 2026-11-19 |
| `E19-D05` | Motion spec: developing value area, recompute and profile transitions | 2 | 2026-11-19 |
| `E19-D06` | Accessibility design review of the profile panel and settings dialog | 2 | 2026-11-19 |
| `E19-D07` | Engineering handoff pack for the profile surface (SCR-038/039, CMP-110/183/184) | 3 | 2026-11-19 |
| `E21-D03` | Hi-fi SCR-051 settings dialog and the SCR-153 depth-shed banner variant | 3 | 2026-11-19 |
| `E21-D04` | Design-system contributions: ladder, heatmap and own-order components | 3 | 2026-11-19 |
| `E21-D05` | Motion and reduced-motion spec for the trail, re-centring and resync states | 2 | 2026-11-19 |
| `E21-D06` | Accessibility design review of the ladder grid and windowed heatmap reveal | 2 | 2026-11-19 |
| `E22-D02` | Wireframe SCR-053 tape + bubble panel with all states | 3 | 2026-11-19 |
| `E22-D03` | Hi-fi SCR-053 and design-system entry for CMP-112 BigTradeBubble | 3 | 2026-11-19 |
| `E26-D02` | Wireframe to hi-fi SCR-097 replay page: transport, coverage scrubber, states | 5 | 2026-11-19 |
| `E26-D03` | Hi-fi SCR-098 replay setup modal with coverage timeline and honest preparation | 3 | 2026-11-19 |
| `E26-D04` | Hi-fi SCR-099 replay paper-trading results with simulated framing throughout | 3 | 2026-11-19 |
| `E26-D05` | Design-system entries for CMP-170, CMP-171 and CMP-172 replay components | 3 | 2026-11-19 |
| `E26-D06` | Motion spec and accessibility design review for the replay transport and chrome | 3 | 2026-11-19 |
| `E26-D07` | Produce the replay design handoff pack and run the engineering handoff session | 2 | 2026-11-19 |

Design total: **59 pts** across 22 tickets.

### 10.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: STRIDE R1 epics (s03, S05-S09)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Golden-fixture corpus (q03, S06-S09)
- qa: E2E suite (web + Electron) (q04, S05-S10)

**QA tickets (59 pts, 18 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E08-Q05` | E2E and a11y audit: watchlist, symbol search, data-confidence states | 5 | `E08-Q01`, `E08-S03`, `E08-D03`, `E08-D07`, `E08-S08`, `E08-S09`, `E08-S10`, `E08-S11` |
| `E08-Q06` | Exploratory charters, E08 regression pack and epic QA sign-off for R0 exit | 3 | `E08-Q02`, `E08-Q03`, `E08-Q04`, `E08-Q05` |
| `E11-Q02` | Build the Playwright E2E suite for chart interaction, multi-pane and sync | 5 | `E11-S09`, `E11-Q01` |
| `E11-Q03` | Establish and sign off the engine performance baselines against the budgets | 3 | `E11-T06`, `E11-S15` |
| `E13-Q02` | Playwright E2E suite additions for indicators (web and Electron) | 3 | `E13-S01`, `E13-S03`, `E13-S08` |
| `E13-Q03` | Indicator performance benchmark and CI regression gate | 3 | `E13-S03`, `E13-S05` |
| `E13-Q04` | Accessibility audit of the indicator surfaces (axe-core plus manual SR pass) | 3 | `E13-S01`, `E13-S03` |
| `E13-Q05` | Parity and fixture regression pack for indicator values | 3 | `E13-S05`, `E13-S06`, `E13-S07` |
| `E13-Q06` | Exploratory charters, chaos scenarios and E13 QA sign-off | 3 | `E13-Q02`, `E13-Q03`, `E13-Q04`, `E13-Q05` |
| `E14-Q03` | Playwright E2E: drawing lifecycle, object tree and cross-chart sync | 5 | `E14-Q01`, `E14-S03`, `E14-S04` |
| `E14-Q05` | Performance pack: drag FPS with 200 drawings, dense tree and batch write load | 5 | `E14-T03`, `E14-T04`, `E14-S03` |
| `E14-Q06` | Chaos scenarios for drawings: offline edits, conflicts and partial batch failure | 3 | `E14-T02`, `E14-Q04` |
| `E15-Q03` | Functional pack for cross-pane sync groups and price-scale linking | 3 | `E15-Q01`, `E15-S03`, `E15-S04` |
| `E16-Q02` | Automate the E2E suite for recorder lifecycle, retention and empty states | 3 | `E16-Q01`, `E16-S01`, `E16-S03`, `E16-S04`, `E16-S05` |
| `E16-Q03` | Run the exploratory charter for recorder surprise, honesty and data-loss traps | 2 | `E16-S01`, `E16-S03`, `E16-S04`, `E16-S05` |
| `E16-Q04` | Build the recorder perf, soak and disk-pressure chaos scripts | 3 | `E16-Q01`, `E16-T07`, `E16-T05` |
| `E16-Q05` | Run the accessibility audit for the recorder screens and empty-state pattern | 2 | `E16-S01`, `E16-S03`, `E16-S04`, `E16-S05` |
| `E16-Q06` | Assemble the recorder regression pack and record epic QA sign-off | 2 | `E16-Q02`, `E16-Q03`, `E16-Q04`, `E16-Q05` |

**Security tickets (18 pts, 5 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E12-X02` | Abuse cases: parameter fuzzing, resource exhaustion and data-integrity attacks | 5 | `E12-X01`, `E12-T05`, `E12-T06` |
| `E12-X03` | SAST/DAST rules and CI security gates for the bar and market-data surface | 3 | `E12-X01`, `E12-T02`, `E12-S05` |
| `E13-X02` | Security review of indicator endpoints, presets and metric exposure | 2 | `E13-X01`, `E13-T03`, `E13-S08` |
| `E14-X02` | Abuse cases: stored XSS in annotations, IDOR on /drawings and payload exhaustion | 5 | `E14-X01`, `E14-Q04` |
| `E16-X02` | Security review: destructive paths, RBAC, path containment, config gating | 3 | `E16-X01`, `E16-T06`, `E16-T08`, `E16-T10` |

### 10.7 Risks & dependency watch-list

- E16 at 51 pts is the sprint's dominant load and it gates R2's replay and footprint work.
- QA load jumps to 38 pts (golden-fixture corpus) - QA is the constraint this sprint, not engineering.
- DAST quarterly scans begin (s06); first-run findings often spike triage load.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S08 |
|---|---|---|
| `E13-S01` | Sprint 07 | 5 |
| `E13-S02` | Sprint 07 | 4 |
| `E21-D02` | Sprint 07 | 4 |
| `E12-T06` | Sprint 07 | 3 |
| `E12-X01` | Sprint 05 | 3 |
| `E13-D06` | Sprint 05 | 3 |
| `E16-D06` | Sprint 05 | 3 |
| `E12-Q02` | Sprint 06 | 2 |
| `E12-T02` | Sprint 05 | 2 |
| `E12-S05` | Sprint 06 | 2 |
| `E12-S09` | Sprint 07 | 2 |
| `E14-Q04` | Sprint 07 | 2 |
| _... 49 more_ | | |

### 10.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Full v1 indicator set on a live chart; replay scrubbing a recorded session; footprint first pixels.

**Exit expectation:** Golden-fixture corpus published and consumed by contract tests.

### 10.9 Burn-up - R1 train

| Sprint | Eng pts this sprint | Cumulative R1 | R1 total | Remaining | % complete |
|---|---|---|---|---|---|
| S05 | 90 | 90 | 407 | 317 | 22% |
| S06 | 90 | 180 | 407 | 227 | 44% |
| S07 | 47 | 227 | 407 | 180 | 56% |
| S08 **<- this sprint** | 90 | 317 | 407 | 90 | 78% |
| S09 | 90 | 407 | 407 | 0 | 100% |

---

## 11. S09 - 2026-11-20 -> 2026-11-26 (R1)

### 11.1 Sprint goal(s)

- **Close R1 and cut `0.2.0`.** Engine core final acceptance against the FPS budgets in `06-performance-and-load-standard.md` (E11).
- Deep-Stats and footprint scaffolding land so R2 opens at full speed (E20, E18).
- Light engineering sprint by design (3 pts) - the load is design (31) and QA (8): R1 exit evidence, not new scope.
- **QA is over pool: 50 pts vs 45 (+5).**

### 11.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 90 | 90 | +0 | ok |
| Design (D) | 25 | 60 | +35 | ok |
| QA (Q) | 69 | 45 | -24 | **OVER** |
| Security (X) | 19 | 20 | +1 | ok |
| **Total** | **203** | **215** | **+12** | |

### 11.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E15** | Layouts & workspaces | App & Charting UI (FE-App) | 49 | 15 |
| **E12** | Bar builders & series rendering (time/tick/volume/range/renko) | Data & Feeds (BE-Feeds) | 43 | 14 |
| **E11** | Chart engine core (scene, axes, interaction, LOD) | Chart Engine (FE-Engine) | 38 | 11 |
| **E14** | Drawing tools | App & Charting UI (FE-App) | 34 | 10 |
| **E17** | Market-data WS protocol & binary framing | Data & Feeds (BE-Feeds) | 10 | 5 |
| **E20** | Deep-Stats rows: per-bar statistics strip, configuration and export | Order Flow (BE-Flow + FE-Engine) | 8 | 3 |
| **E50** | xstate-statemachine adoption: factory, persistence, plugins, contract suite, catalogue | Platform & DevSecOps | 7 | 4 |
| **E16** | Recorder, retention & disk budget | Data & Feeds (BE-Feeds) | 6 | 3 |
| **E22** | Big trades & bubbles: tape, thresholds, clustering and the bubble overlay | Order Flow (BE-Flow + FE-Engine) | 4 | 2 |
| **E13** | Indicators framework & v1 indicator set | App & Charting UI (FE-App) | 2 | 1 |
| **E21** | DOM ladder & liquidity heatmap | Order Flow (BE-Flow + FE-Engine) | 2 | 1 |


**Statechart lane:** E16 (`E16-D07`, `E16-S02`, `E16-T09`); E17 (`E17-Q03`, `E17-Q04`, `E17-T05`, `E17-T06`, `E17-T07`); E20 (`E20-D01`, `E20-D02`, `E20-D03`); E50 (`E50-C17`, `E50-T16`, `E50-T43`, `E50-T56`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 11.4 Tickets (69)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E11-D08` | Run design QA on the built chart engine surfaces against the specs | Task | 3 | chart-engine | `E11-S14`, `E11-S09` |
| `E11-Q04` | Run a chaos charter for context loss, feed faults and resource pressure | Task | 3 | chart-engine | `E11-S02`, `E11-T05` |
| `E11-Q05` | Audit the chart engine for WCAG 2.2 AA with axe-core and screen readers | Task | 5 | chart-engine | `E11-S14`, `E11-D07` |
| `E11-Q06` | Assemble the chart-engine regression pack and run the epic-level QA sign-off | Task | 3 | chart-engine | `E11-Q05`, `E11-Q03`, `E11-Q04` |
| `E11-Q07` | Run an exploratory GPU, driver and runtime matrix charter for the engine | Task | 3 | chart-engine | `E11-T05`, `E11-T08` |
| `E11-S13` | Expose the chart to AT via a windowed DOM mirror and keyboard data cursor | Story | 5 | chart-engine | `E11-S07`, `E11-S08`, `E11-D07` |
| `E11-S14` | Ship the SCR-045 data-table alternative as an equal-status chart view | Story | 5 | chart-engine | `E11-S13`, `E11-D04` |
| `E11-T05` | Provide a degraded-2d Canvas fallback when WebGL2 is unavailable | Task | 3 | chart-engine | `E11-S02` |
| `E11-T07` | Feed the SCR-046 diagnostics overlay with telemetry and a copy snapshot | Task | 2 | chart-engine | `E11-T06` |
| `E11-T09` | Freeze the public engine API, document it and amend the ADR for open item O2 | Task | 3 | chart-engine | `E11-S14`, `E11-S15` |
| `E11-X03` | Run abuse-case testing and the security review sign-off for the chart engine | Task | 3 | chart-engine | `E11-X01`, `E11-X02`, `E11-S15` |
| `E12-K01` | Spike: Renko brick sizing, ATR bricks and cancellable series rebuilds | Spike | 2 | data-feeds | `E08` |
| `E12-K02` | Publish the bar-semantics reference and ADR addendum for downstream epics | Chore | 2 | docs | `E12-Q02`, `E12-Q04`, `E12-X04` |
| `E12-Q02` | Golden-fixture conformance suite for all six bar builders | Task | 5 | chart-engine | `E12-Q01`, `E12-T02`, `E12-T03`, `E12-T04`, `E12-T05` |
| `E12-Q05` | Performance and load scripts for bar building, backfill and series rendering | Task | 5 | chart-engine | `E12-Q02`, `E12-S05`, `E12-S09` |
| `E12-Q06` | Chaos scenarios for bar building: feed gaps, store outages and clock skew | Task | 3 | data-feeds | `E12-Q02`, `E12-T02`, `E12-T06` |
| `E12-Q07` | Accessibility audit of bar-mode, series and interval surfaces | Task | 3 | web | `E12-S02`, `E12-S04`, `E12-S05`, `E12-D06` |
| `E12-Q08` | Exploratory charters, E12 regression pack and epic QA sign-off | Task | 3 | chart-engine | `E12-Q02`, `E12-Q03`, `E12-Q04`, `E12-Q05`, `E12-Q06`, `E12-Q07` |
| `E12-S04` | Build Renko bricks with reversal cost and single-allocation volume | Story | 5 | data-feeds | `E12-S03`, `E12-K01` |
| `E12-S07` | Add line, area, baseline, hollow-candle and Heikin-Ashi series types | Story | 3 | chart-engine | `E12-S06` |
| `E12-S08` | Render the volume column sub-pane linked to the price pane | Story | 1 | chart-engine | `E12-S07` |
| `E12-S12` | Select bar mode and parameters with a cancellable rebuild and history markers | Story | 3 | chart-engine | `E12-S11`, `E12-S04` |
| `E12-T04` | Build the bar determinism harness: BI-1..BI-6 properties and golden fixtures | Task | 5 | data-feeds | `E12-T03`, `E12-S03`, `E12-S04` |
| `E12-T07` | Add series-rendering scenarios to the engine benchmark CI gate | Task | 1 | chart-engine | `E12-S09`, `E12-S11` |
| `E12-X04` | Security review and sign-off for E12 bar builders and series | Task | 2 | cross-cutting | `E12-X01`, `E12-X02`, `E12-X03`, `E12-Q06` |
| `E13-T04` | ADR for indicator compute placement and parity, plus plan-doc updates | Task | 2 | docs | `E13-K01`, `E13-S08` |
| `E14-C01` | ADR-0014 drawing persistence model and chart-space geometry contract | Chore | 2 | docs | `E14-T01`, `E14-T02` |
| `E14-D11` | Design QA of the built drawing tools, object tree and position tool | Task | 3 | web | `E14-D03`, `E14-D04`, `E14-D05`, `E14-D06`, `E14-D07`, `E14-D08`, `E14-D09`, `E14-D10` |
| `E14-Q07` | Accessibility audit of the drawing surface, toolbar and object tree | Task | 5 | drawing-tools | `E14-Q03`, `E14-S04`, `E14-S05` |
| `E14-Q08` | Exploratory charters, E14 regression pack and epic QA sign-off | Task | 3 | drawing-tools | `E14-Q02`, `E14-Q03`, `E14-Q05`, `E14-Q06`, `E14-Q07` |
| `E14-S05` | Anchored VWAP drawing with standard-deviation bands and incremental update | Story | 3 | drawing-tools | `E14-S02` |
| `E14-S06` | Text note, callout, arrow and measure tool annotations | Story | 3 | drawing-tools | `E14-S01` |
| `E14-S07` | Long/short position tool with R:R, risk sizing and send-to-ticket handoff | Story | 5 | drawing-tools | `E14-S03` |
| `E14-S08` | Object tree, lock/hide, clone, z-order and undo/redo UI (SCR-036) | Story | 5 | drawing-tools | `E14-S01`, `E14-S06` |
| `E14-S09` | Drawing style templates and cross-pane level sync | Story | 2 | drawing-tools | `E14-S08`, `E14-S04` |
| `E14-X03` | SAST/DAST rules and CI guards for the drawings render and persistence paths | Task | 3 | infra | `E14-X01` |
| `E15-C01` | ADR and operator/user docs for the workspace document format and sharing rules | Chore | 2 | docs | `E15-X01`, `E15-Q04`, `E15-S07` |
| `E15-D17` | Design QA of the built workspace, dock system, presets and sync surfaces | Task | 3 | web | `E15-D16` |
| `E15-Q02` | Playwright E2E suite for dock, workspace save/restore and preset gallery | Task | 5 | web | `E15-Q01`, `E15-S01`, `E15-S02`, `E15-S06` |
| `E15-Q04` | Multi-pane performance benchmark and workspace restore/load scripts | Task | 5 | web | `E15-Q02`, `E15-Q03`, `E15-S01`, `E15-S02`, `E15-S08` |
| `E15-Q05` | Chaos: WS loss, API 5xx, storage failure and workspace crash-restore | Task | 3 | web | `E15-Q02`, `E15-S02`, `E15-S07` |
| `E15-Q06` | Accessibility audit of the dock system, workspace switcher and layout surfaces | Task | 5 | web | `E15-S01`, `E15-S05`, `E15-S06`, `E15-Q02` |
| `E15-Q07` | Exploratory charters and cross-epic layout regression pack | Task | 3 | web | `E15-Q02`, `E15-Q03`, `E15-Q05` |
| `E15-Q08` | E15 QA sign-off: rollup, traceability evidence and R1 exit-gate input | Task | 3 | web | `E15-Q01`, `E15-Q02`, `E15-Q03`, `E15-Q04`, `E15-Q05`, `E15-Q06`, `E15-Q07`, `E15-X04` |
| `E15-S05` | Linked vs independent price scaling with incompatible-link refusal | Story | 2 | chart-engine | `E15-S04`, `E11` |
| `E15-S06` | Multi-chart grid panel: cells, per-cell binding, maximise and budget prompt | Story | 2 | web | `E15-T02`, `E15-T03`, `E15-K01`, `E11`, `E05` |
| `E15-S07` | Workspace export and import with schema validation and redaction (SCR-026) | Story | 3 | web | `E15-S03`, `E15-T01` |
| `E15-S08` | Responsive layout and measured reduced-capability profile (SCR-153) | Story | 2 | web | `E15-S02`, `E15-K01` |
| `E15-X02` | Abuse cases: malicious workspace import, cross-user access and layout DoS | Task | 5 | web | `E15-X01`, `E15-S02`, `E15-S07` |
| `E15-X03` | SAST/DAST rules and CI security gates for the workspace document surface | Task | 3 | infra | `E15-X01`, `E15-S07` |
| `E15-X04` | Security review and sign-off for E15 layouts, workspaces and sharing | Task | 3 | web | `E15-X01`, `E15-X02`, `E15-X03` |
| `E16-D07` | Design QA of the built recorder screens against spec | Task | 2 | web | `E16-D06`, `E16-S05` |
| `E16-S02` | Surface recording status and auto-record triggers across chart and watchlist | Story | 2 | web | `E16-S01`, `E16-D05` |
| `E16-T09` | Add recorder dashboards, alert rules and the recorder ops runbook | Task | 2 | infra | `E16-T07`, `E16-T08` |
| `E17-Q03` | Write and run the k6 WS load profile and record the section 16.3 budgets | Task | 2 | api | `E17-T03`, `E17-T06` |
| `E17-Q04` | E2E suite, exploratory charter, regression pack and QA sign-off for E17 | Task | 2 | api | `E17-T04`, `E17-Q01`, `E17-T07`, `E17-D04` |
| `E17-T05` | Generate the single-source error registry and wire the error_registry_single_source gate | Task | 2 | api | `E17-T01` |
| `E17-T06` | Instrument the WS gateway: metrics, budget-#6 spans and connection-quality telemetry | Task | 2 | api | `E17-T03`, `E04` |
| `E17-T07` | Freeze the protocol: reconcile 23-ws-protocol.md, amend ADR-0005 and add the breaking-change gate | Task | 2 | api | `E17-T03`, `E17-T04`, `E17-T05` |
| `E20-D01` | UX research: how traders read per-bar statistics | Task | 2 | chart-engine | `E18-D02` |
| `E20-D02` | Wireframe SCR-033 and the CMP-225 strip with all states | Task | 3 | chart-engine | `E20-D01` |
| `E20-D03` | Hi-fi design for SCR-033 and design-system entry for CMP-225 | Task | 3 | chart-engine | `E20-D02` |
| `E21-D07` | Design handoff package for the DOM ladder and heatmap build | Task | 2 | web | `E21-D02`, `E21-D03`, `E21-D04`, `E21-D05`, `E21-D06` |
| `E22-D04` | Motion spec and accessibility review for tape and bubbles | Task | 2 | web | `E22-D03` |
| `E22-D05` | Design handoff pack for E22 with sign-off | Task | 2 | web | `E22-D03`, `E22-D04` |
| `E50-C17` | Upstream liaison: track #26 meta + R14-01; re-verify (T04 nightly + T31) on every library release; propose pin bumps via ADR-0016 amendment | Chore | 1 | api | `E50-T04` |
| `E50-T16` | Verify mandatory-config round-6 keys on all 20 charts (policy lint fixtures) | Task | 1 | api | `E50-S02`, `E50-T11` |
| `E50-T43` | Land the round-14 four our-side fixes: B16 C-04 hoist, B18 C-07b fall-through, B11 R14-03, B8 attempt counter B610-OC-CD03 (P3-G1) | Task | 3 | api | `E50-S01`, `E50-S02` |
| `E50-T56` | CV-C68 payload-only cv_re_mint wrapper + CV-LINT-REMINT (R14-01 containment) | Task | 2 | api | `E50-T15`, `E50-T11` |

### 11.5 Design-track deliverables due

**Design sprint D-S09** (roadmap 1.2) produces: Accounts, API-key flows, per-account profiles, trade-group picker

> Consumed by engineering sprint **S11** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S11 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E11-D08` | Run design QA on the built chart engine surfaces against the specs | 3 | 2026-11-26 |
| `E14-D11` | Design QA of the built drawing tools, object tree and position tool | 3 | 2026-11-26 |
| `E15-D17` | Design QA of the built workspace, dock system, presets and sync surfaces | 3 | 2026-11-26 |
| `E16-D07` | Design QA of the built recorder screens against spec | 2 | 2026-11-26 |
| `E20-D01` | UX research: how traders read per-bar statistics | 2 | 2026-11-26 |
| `E20-D02` | Wireframe SCR-033 and the CMP-225 strip with all states | 3 | 2026-11-26 |
| `E20-D03` | Hi-fi design for SCR-033 and design-system entry for CMP-225 | 3 | 2026-11-26 |
| `E21-D07` | Design handoff package for the DOM ladder and heatmap build | 2 | 2026-11-26 |
| `E22-D04` | Motion spec and accessibility review for tape and bubbles | 2 | 2026-11-26 |
| `E22-D05` | Design handoff pack for E22 with sign-off | 2 | 2026-11-26 |

Design total: **25 pts** across 10 tickets.

### 11.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: STRIDE R1 epics (s03, S05-S09)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Golden-fixture corpus (q03, S06-S09)
- qa: E2E suite (web + Electron) (q04, S05-S10)
- qa: Load & soak campaigns (q07, S09-S20)

**QA tickets (69 pts, 19 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E11-Q04` | Run a chaos charter for context loss, feed faults and resource pressure | 3 | `E11-S02`, `E11-T05` |
| `E11-Q05` | Audit the chart engine for WCAG 2.2 AA with axe-core and screen readers | 5 | `E11-S14`, `E11-D07` |
| `E11-Q06` | Assemble the chart-engine regression pack and run the epic-level QA sign-off | 3 | `E11-Q05`, `E11-Q03`, `E11-Q04` |
| `E11-Q07` | Run an exploratory GPU, driver and runtime matrix charter for the engine | 3 | `E11-T05`, `E11-T08` |
| `E12-Q02` | Golden-fixture conformance suite for all six bar builders | 5 | `E12-Q01`, `E12-T02`, `E12-T03`, `E12-T04`, `E12-T05` |
| `E12-Q05` | Performance and load scripts for bar building, backfill and series rendering | 5 | `E12-Q02`, `E12-S05`, `E12-S09` |
| `E12-Q06` | Chaos scenarios for bar building: feed gaps, store outages and clock skew | 3 | `E12-Q02`, `E12-T02`, `E12-T06` |
| `E12-Q07` | Accessibility audit of bar-mode, series and interval surfaces | 3 | `E12-S02`, `E12-S04`, `E12-S05`, `E12-D06` |
| `E12-Q08` | Exploratory charters, E12 regression pack and epic QA sign-off | 3 | `E12-Q02`, `E12-Q03`, `E12-Q04`, `E12-Q05`, `E12-Q06`, `E12-Q07` |
| `E14-Q07` | Accessibility audit of the drawing surface, toolbar and object tree | 5 | `E14-Q03`, `E14-S04`, `E14-S05` |
| `E14-Q08` | Exploratory charters, E14 regression pack and epic QA sign-off | 3 | `E14-Q02`, `E14-Q03`, `E14-Q05`, `E14-Q06`, `E14-Q07` |
| `E15-Q02` | Playwright E2E suite for dock, workspace save/restore and preset gallery | 5 | `E15-Q01`, `E15-S01`, `E15-S02`, `E15-S06` |
| `E15-Q04` | Multi-pane performance benchmark and workspace restore/load scripts | 5 | `E15-Q02`, `E15-Q03`, `E15-S01`, `E15-S02`, `E15-S08` |
| `E15-Q05` | Chaos: WS loss, API 5xx, storage failure and workspace crash-restore | 3 | `E15-Q02`, `E15-S02`, `E15-S07` |
| `E15-Q06` | Accessibility audit of the dock system, workspace switcher and layout surfaces | 5 | `E15-S01`, `E15-S05`, `E15-S06`, `E15-Q02` |
| `E15-Q07` | Exploratory charters and cross-epic layout regression pack | 3 | `E15-Q02`, `E15-Q03`, `E15-Q05` |
| `E15-Q08` | E15 QA sign-off: rollup, traceability evidence and R1 exit-gate input | 3 | `E15-Q01`, `E15-Q02`, `E15-Q03`, `E15-Q04`, `E15-Q05`, `E15-Q06`, `E15-Q07`, `E15-X04` |
| `E17-Q03` | Write and run the k6 WS load profile and record the section 16.3 budgets | 2 | `E17-T03`, `E17-T06` |
| `E17-Q04` | E2E suite, exploratory charter, regression pack and QA sign-off for E17 | 2 | `E17-T04`, `E17-Q01`, `E17-T07`, `E17-D04` |

**Security tickets (19 pts, 6 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E11-X03` | Run abuse-case testing and the security review sign-off for the chart engine | 3 | `E11-X01`, `E11-X02`, `E11-S15` |
| `E12-X04` | Security review and sign-off for E12 bar builders and series | 2 | `E12-X01`, `E12-X02`, `E12-X03`, `E12-Q06` |
| `E14-X03` | SAST/DAST rules and CI guards for the drawings render and persistence paths | 3 | `E14-X01` |
| `E15-X02` | Abuse cases: malicious workspace import, cross-user access and layout DoS | 5 | `E15-X01`, `E15-S02`, `E15-S07` |
| `E15-X03` | SAST/DAST rules and CI security gates for the workspace document surface | 3 | `E15-X01`, `E15-S07` |
| `E15-X04` | Security review and sign-off for E15 layouts, workspaces and sharing | 3 | `E15-X01`, `E15-X02`, `E15-X03` |

### 11.7 Risks & dependency watch-list

- **R1 exit gate 2026-11-26 + PRR.** Engineering is only 3 pts - the risk is that exit *evidence* (benchmarks, E2E, a11y) is treated as slack and slips.
- Load & soak campaigns open (q07, running to S20). Early results may invalidate R2 render budgets.
- Design load is 31 pts against a 3-pt eng load: confirm the design org is actually ahead, not just busy.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S09 |
|---|---|---|
| `E15-S02` | Sprint 07 | 5 |
| `E15-X01` | Sprint 07 | 4 |
| `E11-S14` | Sprint 08 | 3 |
| `E15-S01` | Sprint 07 | 3 |
| `E15-Q03` | Sprint 08 | 3 |
| `E17-T03` | Sprint 06 | 3 |
| `E11-S02` | Sprint 05 | 2 |
| `E11-S15` | Sprint 08 | 2 |
| `E14-Q03` | Sprint 08 | 2 |
| `E14-S04` | Sprint 08 | 2 |
| `E14-S01` | Sprint 08 | 2 |
| `E15-Q01` | Sprint 07 | 2 |
| _... 58 more_ | | |

### 11.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** R1 acceptance walkthrough: charting alpha on staging (demo) with FPS budgets met, axe-core clean, E2E suite green.

**Exit expectation:** **R1 gate (PRR) 2026-11-26 - `0.2.0` tagged, deployed to staging (demo).**

### 11.9 Burn-up - R1 train

| Sprint | Eng pts this sprint | Cumulative R1 | R1 total | Remaining | % complete |
|---|---|---|---|---|---|
| S05 | 90 | 90 | 407 | 317 | 22% |
| S06 | 90 | 180 | 407 | 227 | 44% |
| S07 | 47 | 227 | 407 | 180 | 56% |
| S08 | 90 | 317 | 407 | 90 | 78% |
| S09 **<- this sprint** | 90 | 407 | 407 | 0 | 100% |

---

# R2 - Order-flow beta

| | |
|---|---|
| Sprints | S10-S13 |
| Dates | 2026-11-27 -> 2026-12-24 |
| Version at cut | `0.3.0` |
| Deploys to | staging (demo) |
| Gate | PRR |
| Eng pts in backlog | 357 of 360 capacity (99%) |
| All-discipline pts | 681 |

R2 is the order-flow differentiator: footprint, profiles, Deep-Stats rows, DOM ladder and liquidity heatmap, big trades, CVD, derivatives metrics, estimated detectors and the replay engine. Every one of these renders through the engine built in R1, so the render hot path is the shared surface that decides whether R2 fits.

---

## 12. S10 - 2026-11-27 -> 2026-12-03 (R2)

### 12.1 Sprint goal(s)

- **Open R2.** Footprint is scheduled first because it is the heaviest render path and sets R2's ceiling (E18).
- DOM ladder and liquidity heatmap begin on the engine core (E21).
- CVD/delta panes and derivatives metrics start their backend aggregations (E23, E24).

### 12.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 89 | 90 | +1 | ok |
| Design (D) | 23 | 60 | +37 | ok |
| QA (Q) | 2 | 45 | +43 | ok |
| Security (X) | 16 | 20 | +4 | ok |
| **Total** | **130** | **215** | **+85** | |

### 12.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E18** | Footprint: cell aggregation, imbalance detection and cell rendering | Order Flow (BE-Flow + FE-Engine) | 39 | 13 |
| **E26** | Replay engine & scrubbing | Data & Feeds (BE-Feeds) | 22 | 8 |
| **E21** | DOM ladder & liquidity heatmap | Order Flow (BE-Flow + FE-Engine) | 18 | 5 |
| **E19** | Volume / delta / TPO profiles | Order Flow (BE-Flow + FE-Engine) | 14 | 5 |
| **E23** | CVD & delta panes: cumulative delta, anchors, display modes and divergence | Order Flow (BE-Flow + FE-Engine) | 12 | 5 |
| **E25** | Detectors: tape speed, imbalance, regime, iceberg/stop-run (estimated) | Order Flow (BE-Flow + FE-Engine) | 10 | 4 |
| **E24** | Derivatives metrics: open interest, funding, liquidations and basis | Order Flow (BE-Flow + FE-Engine) | 7 | 3 |
| **E20** | Deep-Stats rows: per-bar statistics strip, configuration and export | Order Flow (BE-Flow + FE-Engine) | 4 | 2 |
| **E22** | Big trades & bubbles: tape, thresholds, clustering and the bubble overlay | Order Flow (BE-Flow + FE-Engine) | 4 | 2 |


**Statechart lane:** E18 (`E18-K01`, `E18-Q01`, `E18-S01`, `E18-S02`, `E18-S03`, `E18-S04`, `E18-S06`, `E18-T01`, `E18-T02`, `E18-T03`, `E18-T04`, `E18-T05`, `E18-X01`); E19 (`E19-K01`, `E19-T01`, `E19-T02`, `E19-T03`, `E19-X01`); E20 (`E20-D04`, `E20-D05`); E26 (`E26-T01`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 12.4 Tickets (47)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E18-K01` | Measure footprint cell density, glyph cost and the text-LOD threshold | Spike | 2 | chart-engine | `E06`, `E11` |
| `E18-Q01` | Black-box test plan and exploratory charter for footprint | Task | 2 | chart-engine | `E18-D05`, `E18-T02` |
| `E18-S01` | Render the footprint cell grid with tick aggregation and text LOD | Story | 8 | chart-engine | `E18-T03`, `E18-T04`, `E18-K01`, `E18-D05`, `E11` |
| `E18-S02` | Render bid/ask split cells with narrow-cell degradation | Story | 2 | chart-engine | `E18-S01` |
| `E18-S03` | Add delta and delta+total cell modes sharing one aggregate store | Story | 2 | chart-engine | `E18-S02` |
| `E18-S04` | Support profile and box display modes with per-pane independence | Story | 2 | chart-engine | `E18-S01` |
| `E18-S06` | Apply delta/imbalance colouring, the noise filter and non-colour alternatives | Story | 3 | chart-engine | `E18-S03` |
| `E18-T01` | Implement FootprintEngine native-tick cell aggregation in M9 | Task | 5 | data-feeds | `E12`, `E16` |
| `E18-T02` | Implement imbalance, unfinished-auction, POC and value-area algorithms | Task | 5 | data-feeds | `E18-T01` |
| `E18-T03` | Serve GET /market/footprint and POST /market/footprint/recompute | Task | 2 | api | `E18-T02`, `E18-X01` |
| `E18-T04` | Publish the footprint WS topic with binary body_kind 5 and cell coalescing | Task | 2 | api | `E18-T02`, `E17` |
| `E18-T05` | Persist footprint_cells, export to the cold tier and implement the rebuild job | Task | 2 | infra | `E18-T01`, `E16` |
| `E18-X01` | STRIDE threat model for the footprint epic | Task | 2 | api | `E12`, `E17` |
| `E19-K01` | Spike: reuse footprint aggregates for profiles and prove the recompute budget | Spike | 2 | indicators | `E18` |
| `E19-T01` | ProfileEngine: period accumulators, QuestDB profiles table and rebuild | Task | 5 | indicators | `E19-K01`, `E18`, `E16` |
| `E19-T02` | GET /market/profile endpoint with ProfileResponse contract and bounded windows | Task | 2 | api | `E19-T01` |
| `E19-T03` | WS topic profile.{symbol}.{kind}: keys, coalescing and backpressure degradation | Task | 2 | api | `E19-T02`, `E17` |
| `E19-X01` | STRIDE threat model for the profile engine, API and WS topic | Task | 3 | indicators | `E19-T01` |
| `E20-D04` | Motion spec and accessibility review for the Deep-Stats strip | Task | 2 | chart-engine | `E20-D03` |
| `E20-D05` | Design handoff pack for E20 with sign-off | Task | 2 | chart-engine | `E20-D03`, `E20-D04` |
| `E21-K01` | Prove the 500-depth heatmap ring buffer and runtime parity | Spike | 3 | chart-engine | `E11`, `E06` |
| `E21-T01` | Book engine: depth tiers, tick aggregation and the ladder publisher | Task | 5 | data-feeds | `E08`, `E17` |
| `E21-T02` | HeatmapEngine columns, the heatmap topic and heatmap_cells persistence | Task | 5 | data-feeds | `E21-T01`, `E17`, `E16` |
| `E21-T03` | GET /market/heatmap and GET /market/orderbook backfill from recorded history | Task | 2 | api | `E21-T02`, `E16` |
| `E21-X01` | STRIDE threat model for the DOM ladder and liquidity heatmap | Task | 3 | cross-cutting | `E17`, `E08` |
| `E22-K01` | Spike: bubble instancing cost and LOD ladder at 5 000 visible prints | Spike | 2 | chart-engine | `E11` |
| `E22-X01` | STRIDE threat model for the big trades & bubbles epic | Task | 2 | data-feeds | `E08` |
| `E23-D01` | UX research: how traders read cumulative delta and divergence | Task | 2 | web | `E18` |
| `E23-D02` | Wireframe SCR-052 CVD / delta panel with every state | Task | 3 | web | `E23-D01` |
| `E23-D03` | Hi-fi SCR-052 and design-system entry for CMP-185 CvdPane | Task | 3 | web | `E23-D02` |
| `E23-K01` | Spike: intrabar CVD OHLC cost and 1M-print recompute inside 2 s | Spike | 2 | data-feeds | `E07`, `E16`, `E18` |
| `E23-X01` | STRIDE threat model for the CVD & delta panes epic | Task | 2 | data-feeds | `E17`, `E18` |
| `E24-D01` | UX research: how perp traders read OI, funding and liquidations | Task | 2 | web |  |
| `E24-D02` | Wireframe SCR-054 derivatives panel with every state | Task | 3 | web | `E24-D01` |
| `E24-X01` | STRIDE threat model for the derivatives metrics epic | Task | 2 | cross-cutting |  |
| `E25-D01` | UX research: how traders read speed, imbalance and estimated signals | Task | 3 | web |  |
| `E25-D05` | Design-system contribution: detector components and the estimated badge | Task | 3 | web |  |
| `E25-K01` | Spike: calibrate iceberg/stop-run/absorption heuristics on recorded data | Spike | 2 | data-feeds | `E16`, `E21` |
| `E25-X01` | STRIDE threat model and abuse cases for the detector subsystem | Task | 2 | cross-cutting |  |
| `E26-K01` | Spike: measure seek cost and hot/cold source throughput at 200-depth symbol-day | Spike | 2 | data-feeds | `E16-T05`, `E07` |
| `E26-S01` | Create a replay session from SCR-098 with coverage-aware range selection | Story | 3 | web | `E26-T05`, `E26-D07` |
| `E26-T01` | Add the replay_sessions migration, repository and session lifecycle service | Task | 2 | api | `E16-T01`, `E09`, `E50-T59`, `E50-S01` |
| `E26-T02` | Implement ReplaySource: hot/cold readers, ordered k-way merge and gap reporting | Task | 3 | api | `E26-K01`, `E16-T05` |
| `E26-T03` | Implement ReplayClock and Injector: pacing, step modes, same-pipeline injection | Task | 3 | api | `E26-T02`, `E26-T01` |
| `E26-T04` | Implement SeekEngine: snapshot anchoring, delta re-apply, builder restore | Task | 3 | api | `E26-T03`, `E12` |
| `E26-T05` | Implement the replay REST surface and WS replay_session_id routing | Task | 3 | api | `E26-T04`, `E26-T01`, `E17-S02` |
| `E26-T06` | Build the replay determinism and live-parity harness as a required CI check | Task | 3 | api | `E26-T03`, `E18`, `E23` |

### 12.5 Design-track deliverables due

**Design sprint D-S10** (roadmap 1.2) produces: Order ticket, chart trading, DOM trading, arm/lock + env badge

> Consumed by engineering sprint **S12** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S12 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E20-D04` | Motion spec and accessibility review for the Deep-Stats strip | 2 | 2026-12-03 |
| `E20-D05` | Design handoff pack for E20 with sign-off | 2 | 2026-12-03 |
| `E23-D01` | UX research: how traders read cumulative delta and divergence | 2 | 2026-12-03 |
| `E23-D02` | Wireframe SCR-052 CVD / delta panel with every state | 3 | 2026-12-03 |
| `E23-D03` | Hi-fi SCR-052 and design-system entry for CMP-185 CvdPane | 3 | 2026-12-03 |
| `E24-D01` | UX research: how perp traders read OI, funding and liquidations | 2 | 2026-12-03 |
| `E24-D02` | Wireframe SCR-054 derivatives panel with every state | 3 | 2026-12-03 |
| `E25-D01` | UX research: how traders read speed, imbalance and estimated signals | 3 | 2026-12-03 |
| `E25-D05` | Design-system contribution: detector components and the estimated badge | 3 | 2026-12-03 |

Design total: **23 pts** across 9 tickets.

### 12.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: STRIDE R2 epics (s04, S10-S13)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: E2E suite (web + Electron) (q04, S05-S10)
- qa: Order-flow correctness suite (q05, S10-S13)
- qa: Load & soak campaigns (q07, S09-S20)

**QA tickets (2 pts, 1 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E18-Q01` | Black-box test plan and exploratory charter for footprint | 2 | `E18-D05`, `E18-T02` |

**Security tickets (16 pts, 7 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E18-X01` | STRIDE threat model for the footprint epic | 2 | `E12`, `E17` |
| `E19-X01` | STRIDE threat model for the profile engine, API and WS topic | 3 | `E19-T01` |
| `E21-X01` | STRIDE threat model for the DOM ladder and liquidity heatmap | 3 | `E17`, `E08` |
| `E22-X01` | STRIDE threat model for the big trades & bubbles epic | 2 | `E08` |
| `E23-X01` | STRIDE threat model for the CVD & delta panes epic | 2 | `E17`, `E18` |
| `E24-X01` | STRIDE threat model for the derivatives metrics epic | 2 |  |
| `E25-X01` | STRIDE threat model and abuse cases for the detector subsystem | 2 |  |

### 12.7 Risks & dependency watch-list

- **E18 footprint sets the ceiling for all of R2.** If its render budget is missed, the descoping ladder starts at E19 TPO/composite profiles.
- Security load spikes to 13 pts (STRIDE R2 epics) - book the Security engineer early.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S10 |
|---|---|---|
| `E16` | epic E16 (whole epic must be Done) | 7 |
| `E17` | epic E17 (whole epic must be Done) | 7 |
| `E18` | epic E18 (whole epic must be Done) | 6 |
| `E11` | epic E11 (whole epic must be Done) | 4 |
| `E12` | epic E12 (whole epic must be Done) | 3 |
| `E08` | epic E08 (whole epic must be Done) | 3 |
| `E06` | epic E06 (whole epic must be Done) | 2 |
| `E18-D05` | Sprint 08 | 2 |
| `E20-D03` | Sprint 09 | 2 |
| `E07` | epic E07 (whole epic must be Done) | 2 |
| `E16-T05` | Sprint 08 | 2 |
| `E18-D04` | Sprint 08 | 1 |
| _... 6 more_ | | |

### 12.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Footprint cells rendering at production density; DOM ladder with live heatmap; CVD pane tracking the tape.

**Exit expectation:** Order-flow correctness suite (q05) reporting.

### 12.9 Burn-up - R2 train

| Sprint | Eng pts this sprint | Cumulative R2 | R2 total | Remaining | % complete |
|---|---|---|---|---|---|
| S10 **<- this sprint** | 89 | 89 | 357 | 268 | 25% |
| S11 | 89 | 178 | 357 | 179 | 50% |
| S12 | 89 | 267 | 357 | 90 | 75% |
| S13 | 90 | 357 | 357 | 0 | 100% |

---

## 13. S11 - 2026-12-04 -> 2026-12-10 (R2)

### 13.1 Sprint goal(s)

- **First sprint at the capacity line (89/90).** Footprint and DOM heatmap run in parallel on separate render passes (E18 17, E21 24).
- Deep-Stats rows and detectors build on the now-live order-flow aggregates (E20, E25).
- Replay engine continues its three-sprint run (E26).

### 13.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 89 | 90 | +1 | ok |
| Design (D) | 24 | 60 | +36 | ok |
| QA (Q) | 13 | 45 | +32 | ok |
| Security (X) | 8 | 20 | +12 | ok |
| **Total** | **134** | **215** | **+81** | |

### 13.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E19** | Volume / delta / TPO profiles | Order Flow (BE-Flow + FE-Engine) | 26 | 7 |
| **E21** | DOM ladder & liquidity heatmap | Order Flow (BE-Flow + FE-Engine) | 24 | 6 |
| **E24** | Derivatives metrics: open interest, funding, liquidations and basis | Order Flow (BE-Flow + FE-Engine) | 20 | 7 |
| **E18** | Footprint: cell aggregation, imbalance detection and cell rendering | Order Flow (BE-Flow + FE-Engine) | 15 | 6 |
| **E23** | CVD & delta panes: cumulative delta, anchors, display modes and divergence | Order Flow (BE-Flow + FE-Engine) | 15 | 6 |
| **E25** | Detectors: tape speed, imbalance, regime, iceberg/stop-run (estimated) | Order Flow (BE-Flow + FE-Engine) | 13 | 5 |
| **E20** | Deep-Stats rows: per-bar statistics strip, configuration and export | Order Flow (BE-Flow + FE-Engine) | 11 | 4 |
| **E22** | Big trades & bubbles: tape, thresholds, clustering and the bubble overlay | Order Flow (BE-Flow + FE-Engine) | 7 | 2 |
| **E26** | Replay engine & scrubbing | Data & Feeds (BE-Feeds) | 3 | 1 |


**Statechart lane:** E18 (`E18-S05`, `E18-S07`, `E18-S08`, `E18-S09`, `E18-T06`, `E18-T07`); E19 (`E19-Q01`, `E19-Q02`, `E19-S01`, `E19-S02`, `E19-S04`, `E19-S07`, `E19-T04`); E20 (`E20-K01`, `E20-T01`, `E20-T02`, `E20-X01`); E23 (`E23-T06`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 13.4 Tickets (44)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E18-S05` | Support footprint input types and make the order-based source honestly absent | Story | 1 | chart-engine | `E18-S01`, `E18-T01` |
| `E18-S07` | Flag diagonal imbalances with configurable per-symbol thresholds | Story | 3 | chart-engine | `E18-S02`, `E18-T02` |
| `E18-S08` | Render stacked imbalance zones with virgin/broken tracking | Story | 5 | chart-engine | `E18-S07` |
| `E18-S09` | Mark bar POC, value area and unfinished auctions without flicker | Story | 2 | chart-engine | `E18-S01`, `E18-T02` |
| `E18-T06` | Golden-fixture parity harness: served footprint vs offline DuckDB recomputation | Task | 3 | chart-engine | `E18-T02`, `E18-T05` |
| `E18-T07` | Write ADR-0016 footprint aggregation and text-LOD strategy, update plan docs | Task | 1 | docs | `E18-K01`, `E18-T06`, `E18-S01` |
| `E19-Q01` | Black-box test plan for the E19 profile story groups | Task | 5 | indicators | `E19-T01`, `E19-T02`, `E19-T03`, `E19-S01` |
| `E19-Q02` | Profile correctness conformance suite: oracle, golden fixtures and contracts | Task | 5 | indicators | `E19-Q01`, `E19-T01`, `E19-T02`, `E19-T03` |
| `E19-S01` | Session volume profile with live update and approximated-from-bars fallback | Story | 3 | indicators | `E19-T03`, `E19-T04` |
| `E19-S02` | Fixed-range, visible-range and anchored profiles with throttled recompute | Story | 3 | indicators | `E19-S01` |
| `E19-S04` | POC, configurable value area and developing VA with deterministic tie-breaks | Story | 3 | indicators | `E19-S01` |
| `E19-S07` | Delta profile with split bid/ask rows and side-by-side combined view | Story | 2 | indicators | `E19-S04` |
| `E19-T04` | Engine profile series plugin: instanced rows, POC/VA lines, LOD merging | Task | 5 | chart-engine | `E19-T01`, `E12` |
| `E20-K01` | Measure strip frame cost and bar-grid alignment strategy | Spike | 2 | chart-engine | `E18-S01`, `E18-S02` |
| `E20-T01` | Implement DeepStatsEngine and register Deep-Stats metric descriptors | Task | 5 | chart-engine | `E18-T01`, `E18-T02` |
| `E20-T02` | Expose Deep-Stats rows over /market/metrics and the footprint WS topic | Task | 2 | api | `E20-T01`, `E20-X01` |
| `E20-X01` | STRIDE threat model for the Deep-Stats epic | Task | 2 | chart-engine | `E18-T03`, `E18-T04` |
| `E21-Q01` | Black-box test plan for the DOM ladder and heatmap | Task | 3 | web | `E21-D07`, `E21-T01`, `E21-T02` |
| `E21-S01` | Render the live DOM ladder grid on SCR-050 | Story | 8 | web | `E21-T01`, `E21-D07`, `E11` |
| `E21-S02` | Render the liquidity heatmap surface with legend, empty state and accessible reveal | Story | 3 | web | `E21-T05`, `E21-T02`, `E21-D07` |
| `E21-T05` | Chart engine: rolling-texture heatmap layer (CMP-193) | Task | 5 | chart-engine | `E11`, `E21-K01`, `E21-T02` |
| `E21-T06` | Adaptive colour scale, LUT pipeline and the bid/ask palette convention | Task | 2 | chart-engine | `E21-T05`, `E21-D04` |
| `E21-X02` | Subscription quotas, abuse cases and path-safety controls for market-data reads | Task | 3 | api | `E21-X01`, `E21-T01`, `E21-T03` |
| `E22-T01` | Implement BigTradeEngine: thresholds, percentiles and deterministic clustering | Task | 5 | data-feeds | `E08`, `E22-X01` |
| `E22-T02` | Expose big trades over trades.{symbol} WS options and /market/trades | Task | 2 | api | `E22-T01`, `E17` |
| `E23-D04` | Motion spec and accessibility review for the CVD / delta pane | Task | 2 | web | `E23-D03` |
| `E23-D05` | Design handoff pack for E23 with CDO sign-off | Task | 2 | web | `E23-D03`, `E23-D04` |
| `E23-T01` | Implement CvdEngine in M9: anchors, intrabar path and EMA smoothing | Task | 5 | data-feeds | `E18`, `E12`, `E23-K01`, `E23-X01` |
| `E23-T02` | Expose CVD and delta over metrics.{symbol} WS and /market/metrics | Task | 2 | api | `E23-T01`, `E17` |
| `E23-T03` | Recompute CVD from the recorded tape on WS gap or reconnect | Task | 3 | data-feeds | `E23-T01`, `E16`, `E17` |
| `E23-T06` | Assert CvdEngine/delta aggregation exclusion from the statechart catalogue (CV-LINT-HOTPATH, BENCH-2) | Chore | 1 | data-feeds | `E50-T11`, `E23-T01` |
| `E24-D03` | Hi-fi SCR-054 and design-system entries for CMP-186, CMP-126, CMP-127 | Task | 3 | web | `E24-D02`, `E24-K01` |
| `E24-D04` | Motion spec and accessibility review for the derivatives panel | Task | 2 | web | `E24-D03` |
| `E24-D05` | Design handoff pack for E24 with sign-off | Task | 2 | web | `E24-D04` |
| `E24-K01` | Spike: liquidation-zone estimation methodology and its honesty limits | Spike | 2 | data-feeds | `E24-X01` |
| `E24-T01` | Open-interest ingest, REST backfill and /market/open-interest endpoint | Task | 5 | data-feeds | `E24-X01`, `E08`, `E16` |
| `E24-T02` | Funding-rate service, interval resolution and /market/funding endpoint | Task | 3 | data-feeds | `E24-X01`, `E08` |
| `E24-T03` | Liquidation socket, persistence and /market/liquidations endpoint | Task | 3 | data-feeds | `E24-X01`, `E08`, `E16`, `E17` |
| `E25-D02` | Wireframe SCR-055..059 detector surfaces with all documented states | Task | 3 | web | `E25-D01` |
| `E25-D03` | Hi-fi design: speed-of-tape, imbalance and regime panels (SCR-055..057) | Task | 3 | web | `E25-D02`, `E25-D05` |
| `E25-D04` | Hi-fi design: methodology drawer and detector settings (SCR-058, SCR-059) | Task | 3 | web | `E25-D02`, `E25-D05` |
| `E25-D06` | Accessibility design review of SCR-055..059 before handoff | Task | 2 | web | `E25-D03`, `E25-D04` |
| `E25-D07` | Design handoff and sign-off for the five detector surfaces | Task | 2 | web | `E25-D06` |
| `E26-X01` | STRIDE threat model and abuse cases for the replay engine and its data access | Task | 3 | api | `E26-T01` |

### 13.5 Design-track deliverables due

**Design sprint D-S11** (roadmap 1.2) produces: Bracket/scaled/emulated-algo UI, positions & orders manager

> Consumed by engineering sprint **S13** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S13 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E23-D04` | Motion spec and accessibility review for the CVD / delta pane | 2 | 2026-12-10 |
| `E23-D05` | Design handoff pack for E23 with CDO sign-off | 2 | 2026-12-10 |
| `E24-D03` | Hi-fi SCR-054 and design-system entries for CMP-186, CMP-126, CMP-127 | 3 | 2026-12-10 |
| `E24-D04` | Motion spec and accessibility review for the derivatives panel | 2 | 2026-12-10 |
| `E24-D05` | Design handoff pack for E24 with sign-off | 2 | 2026-12-10 |
| `E25-D02` | Wireframe SCR-055..059 detector surfaces with all documented states | 3 | 2026-12-10 |
| `E25-D03` | Hi-fi design: speed-of-tape, imbalance and regime panels (SCR-055..057) | 3 | 2026-12-10 |
| `E25-D04` | Hi-fi design: methodology drawer and detector settings (SCR-058, SCR-059) | 3 | 2026-12-10 |
| `E25-D06` | Accessibility design review of SCR-055..059 before handoff | 2 | 2026-12-10 |
| `E25-D07` | Design handoff and sign-off for the five detector surfaces | 2 | 2026-12-10 |

Design total: **24 pts** across 10 tickets.

### 13.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: STRIDE R2 epics (s04, S10-S13)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Order-flow correctness suite (q05, S10-S13)
- qa: Load & soak campaigns (q07, S09-S20)

**QA tickets (13 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E19-Q01` | Black-box test plan for the E19 profile story groups | 5 | `E19-T01`, `E19-T02`, `E19-T03`, `E19-S01` |
| `E19-Q02` | Profile correctness conformance suite: oracle, golden fixtures and contracts | 5 | `E19-Q01`, `E19-T01`, `E19-T02`, `E19-T03` |
| `E21-Q01` | Black-box test plan for the DOM ladder and heatmap | 3 | `E21-D07`, `E21-T01`, `E21-T02` |

**Security tickets (8 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E20-X01` | STRIDE threat model for the Deep-Stats epic | 2 | `E18-T03`, `E18-T04` |
| `E21-X02` | Subscription quotas, abuse cases and path-safety controls for market-data reads | 3 | `E21-X01`, `E21-T01`, `E21-T03` |
| `E26-X01` | STRIDE threat model and abuse cases for the replay engine and its data access | 3 | `E26-T01` |

### 13.7 Risks & dependency watch-list

- E18 and E21 both write to the engine render path; enforce the lane separation or expect merge conflicts in the hot path.
- E26 replay is started one train early precisely because R3 depends on it - protect it from being raided for R2 scope.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S11 |
|---|---|---|
| `E18-T02` | Sprint 10 | 4 |
| `E08` | epic E08 (whole epic must be Done) | 4 |
| `E17` | epic E17 (whole epic must be Done) | 4 |
| `E24-X01` | Sprint 10 | 4 |
| `E18-S01` | Sprint 10 | 3 |
| `E19-T01` | Sprint 10 | 3 |
| `E19-T03` | Sprint 10 | 3 |
| `E21-D07` | Sprint 09 | 3 |
| `E21-T01` | Sprint 10 | 3 |
| `E21-T02` | Sprint 10 | 3 |
| `E16` | epic E16 (whole epic must be Done) | 3 |
| `E18-T01` | Sprint 10 | 2 |
| _... 24 more_ | | |

### 13.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Footprint + heatmap + Deep-Stats rows on one workspace simultaneously at budget FPS.

**Exit expectation:** Render budget held with all order-flow panes active.

### 13.9 Burn-up - R2 train

| Sprint | Eng pts this sprint | Cumulative R2 | R2 total | Remaining | % complete |
|---|---|---|---|---|---|
| S10 | 89 | 89 | 357 | 268 | 25% |
| S11 **<- this sprint** | 89 | 178 | 357 | 179 | 50% |
| S12 | 89 | 267 | 357 | 90 | 75% |
| S13 | 90 | 357 | 357 | 0 | 100% |

---

## 14. S12 - 2026-12-11 -> 2026-12-17 (R2)

### 14.1 Sprint goal(s)

- DOM ladder + heatmap hits peak load (E21) - the render-budget risk sprint of R2.
- Deep-Stats rows complete (E20); detectors reach their *(estimated)* badge UX (E25).
- OMS core and accounts work start early to de-risk R3's opening (E29, E27).
- **QA is over pool: 55 pts vs 45 (+10).**

### 14.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 89 | 90 | +1 | ok |
| Design (D) | 18 | 60 | +42 | ok |
| QA (Q) | 55 | 45 | -10 | **OVER** |
| Security (X) | 11 | 20 | +9 | ok |
| **Total** | **173** | **215** | **+42** | |

### 14.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E21** | DOM ladder & liquidity heatmap | Order Flow (BE-Flow + FE-Engine) | 50 | 17 |
| **E20** | Deep-Stats rows: per-bar statistics strip, configuration and export | Order Flow (BE-Flow + FE-Engine) | 33 | 13 |
| **E19** | Volume / delta / TPO profiles | Order Flow (BE-Flow + FE-Engine) | 24 | 7 |
| **E25** | Detectors: tape speed, imbalance, regime, iceberg/stop-run (estimated) | Order Flow (BE-Flow + FE-Engine) | 21 | 6 |
| **E22** | Big trades & bubbles: tape, thresholds, clustering and the bubble overlay | Order Flow (BE-Flow + FE-Engine) | 13 | 8 |
| **E24** | Derivatives metrics: open interest, funding, liquidations and basis | Order Flow (BE-Flow + FE-Engine) | 8 | 2 |
| **E29** | OMS core & order state machine | OMS & Execution (BE-OMS) | 8 | 2 |
| **E18** | Footprint: cell aggregation, imbalance detection and cell rendering | Order Flow (BE-Flow + FE-Engine) | 5 | 2 |
| **E27** | Accounts, sub-accounts & API-key vault | Accounts & Security (BE-Sec) | 5 | 2 |
| **E23** | CVD & delta panes: cumulative delta, anchors, display modes and divergence | Order Flow (BE-Flow + FE-Engine) | 4 | 2 |
| **E26** | Replay engine & scrubbing | Data & Feeds (BE-Feeds) | 2 | 1 |


**Statechart lane:** E18 (`E18-S10`, `E18-X02`); E19 (`E19-Q03`, `E19-Q04`, `E19-Q05`, `E19-S05`, `E19-S06`, `E19-S09`, `E19-X02`); E20 (`E20-D06`, `E20-Q01`, `E20-Q02`, `E20-Q03`, `E20-Q04`, `E20-Q05`, `E20-S01`, `E20-S02`, `E20-S03`, `E20-S04`, `E20-T03`, `E20-T04`, `E20-X02`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 14.4 Tickets (62)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E18-S10` | Build the footprint settings dialog SCR-032 with live preview | Story | 3 | web | `E18-S06`, `E18-S08`, `E18-D05` |
| `E18-X02` | Security review and abuse-case testing of the footprint read and rebuild paths | Task | 2 | api | `E18-X01`, `E18-T03`, `E18-T04`, `E18-T05` |
| `E19-Q03` | Playwright E2E for the profile panel, period modes and settings dialog | Task | 5 | web | `E19-Q01`, `E19-S01`, `E19-S04`, `E19-T04` |
| `E19-Q04` | Performance and load pack for profile compute, WS fan-out and row rendering | Task | 5 | indicators | `E19-Q02`, `E19-T03`, `E19-T04` |
| `E19-Q05` | Chaos scenarios: feed gaps, store outages, recorder limits and restart recovery | Task | 3 | indicators | `E19-Q02`, `E19-T01`, `E19-T03` |
| `E19-S05` | HVN / LVN detection with configurable prominence and metric exposure | Story | 2 | indicators | `E19-S04` |
| `E19-S06` | Naked / virgin POC tracking with server-side tested state and clutter limit | Story | 2 | indicators | `E19-S05` |
| `E19-S09` | Profile settings dialog and presets shared across instances (SCR-039) | Story | 2 | web | `E19-S02`, `E19-S04` |
| `E19-X02` | Abuse cases: parameter fuzzing, exhaustion and profile integrity | Task | 5 | api | `E19-X01`, `E19-T02`, `E19-T03` |
| `E20-D06` | Design QA sweep of the built Deep-Stats surfaces | Task | 2 | chart-engine | `E20-S02`, `E20-S03`, `E20-S04` |
| `E20-Q01` | Black-box test plan and exploratory charter for Deep-Stats rows | Task | 2 | chart-engine | `E20-S01`, `E20-D05` |
| `E20-Q02` | E2E suite additions for the Deep-Stats strip, configuration and export | Task | 3 | chart-engine | `E20-S02`, `E20-S03`, `E20-S04`, `E20-Q01` |
| `E20-Q03` | Performance benchmark and load profile for the Deep-Stats strip | Task | 3 | chart-engine | `E20-S03`, `E20-K01` |
| `E20-Q04` | Accessibility audit of the Deep-Stats strip, SCR-033 and SCR-045 | Task | 2 | web | `E20-S03`, `E20-S04`, `E20-D04` |
| `E20-Q05` | Epic-level QA sign-off: regression pack and exploratory debrief for E20 | Task | 2 | chart-engine | `E20-Q02`, `E20-Q03`, `E20-Q04`, `E20-X02`, `E20-T03` |
| `E20-S01` | Render the per-bar Deep-Stats strip aligned to the bar grid | Story | 5 | chart-engine | `E20-T02`, `E20-D05`, `E20-K01` |
| `E20-S02` | Select, order and persist Deep-Stats rows via SCR-033 | Story | 3 | web | `E20-S01`, `E20-D05` |
| `E20-S03` | Threshold highlighting for Deep-Stats values with per-symbol sets | Story | 2 | web | `E20-S02`, `E20-D05` |
| `E20-S04` | Accessible stats table and chunked CSV export of the visible range | Story | 3 | web | `E20-S01`, `E20-T02`, `E20-X02` |
| `E20-T03` | Golden-fixture parity harness: strip values vs offline DuckDB recompute | Task | 3 | chart-engine | `E20-T01`, `E20-T02` |
| `E20-T04` | ADR-0016 Deep-Stats rendering strategy and docs update | Task | 1 | docs | `E20-K01`, `E20-T03`, `E20-S01` |
| `E20-X02` | Security review of the Deep-Stats export path and abuse-case testing | Task | 2 | api | `E20-X01`, `E20-T02` |
| `E21-D08` | Design QA of the shipped DOM ladder and heatmap | Task | 3 | web | `E21-S01`, `E21-S02`, `E21-S05`, `E21-S09`, `E21-D07` |
| `E21-Q02` | E2E suite additions for SCR-050 and SCR-051 | Task | 5 | web | `E21-Q01`, `E21-S01`, `E21-S02`, `E21-S05` |
| `E21-Q03` | Performance and load scripts for the heatmap cadence and book fan-out | Task | 5 | infra | `E21-K01`, `E21-T02`, `E21-S02`, `E21-S05` |
| `E21-Q04` | Chaos scenarios: desync storms, slow consumers and exchange failures | Task | 3 | infra | `E21-Q02`, `E21-T01`, `E21-T02` |
| `E21-Q05` | Accessibility audit of the ladder grid, heatmap reveal and settings dialog | Task | 5 | web | `E21-S01`, `E21-S02`, `E21-S09`, `E21-D06` |
| `E21-Q06` | Exploratory charter and regression pack for the order-flow DOM surface | Task | 3 | web | `E21-Q02`, `E21-Q04` |
| `E21-Q07` | QA sign-off for the DOM ladder and liquidity heatmap epic | Task | 2 | web | `E21-Q01`, `E21-Q02`, `E21-Q03`, `E21-Q04`, `E21-Q05`, `E21-Q06`, `E21-D08` |
| `E21-S03` | Adaptive, locked and logarithmic colour-scale controls | Story | 2 | web | `E21-T06`, `E21-S02` |
| `E21-S04` | Trail duration, decay mode and the client memory guard | Story | 2 | web | `E21-S02`, `E21-T05` |
| `E21-S05` | Depth tiers 50/200/500 with automatic load shedding and pinning | Story | 5 | web | `E21-T01`, `E21-S01`, `E21-S02`, `E21-K01` |
| `E21-S06` | Own-order and position column on the ladder against the reconciled-OMS contract | Story | 3 | web | `E21-S01`, `E21-T01`, `E21-D07` |
| `E21-S07` | Deep liquidity scan panel: band thickness and reload detection | Story | 2 | web | `E21-T04`, `E21-S01` |
| `E21-S08` | Progressive book-history backfill when a symbol is opened | Story | 2 | web | `E21-T03`, `E21-S02` |
| `E21-S09` | SCR-051 Heatmap & ladder settings dialog | Story | 2 | web | `E21-S03`, `E21-S04`, `E21-S05`, `E21-D07` |
| `E21-T04` | LiquidityTracker: depth bands, thickness and refill/reload detection | Task | 2 | data-feeds | `E21-T01` |
| `E21-T07` | ADR-0016 depth-tier shedding policy and plan-doc reconciliation | Task | 2 | docs | `E21-K01`, `E21-S05` |
| `E21-X03` | Security review and sign-off of the shipped DOM and heatmap surface | Task | 2 | cross-cutting | `E21-X01`, `E21-X02`, `E21-S06`, `E21-Q04` |
| `E22-Q01` | Black-box test plan and exploratory charter for big trades & bubbles | Task | 2 | chart-engine | `E22-D05`, `E22-T02` |
| `E22-S01` | Render the time & sales tape panel (SCR-053) at 2 000 prints/s | Story | 3 | web | `E22-T02`, `E22-D05` |
| `E22-S02` | Big-trade threshold configuration with per-symbol memory | Story | 1 | web | `E22-S01`, `E22-T02`, `E22-D05` |
| `E22-S03` | Draw big-trade bubbles on the chart (CMP-112) with linear/log scaling | Story | 2 | chart-engine | `E22-S02`, `E22-K01`, `E22-D05` |
| `E22-S04` | Print clustering controls with (estimated) badge and constituent tooltip | Story | 1 | web | `E22-S02`, `E22-S03`, `E22-D05` |
| `E22-S05` | Tape filters, column set and buffered-store memory estimate | Story | 1 | web | `E22-S01`, `E22-D05` |
| `E22-T03` | ADR-0016 big-trade evaluation and bubble LOD; update plan docs | Task | 1 | docs | `E22-K01`, `E22-T04`, `E22-S03` |
| `E22-T04` | Golden-fixture parity and replay-determinism harness for big trades | Task | 2 | data-feeds | `E22-T01` |
| `E23-Q01` | Black-box test plan and exploratory charter for CVD & delta panes | Task | 2 | web | `E23-D05`, `E23-T02` |
| `E23-T04` | Golden-fixture parity harness: CVD vs offline DuckDB recomputation | Task | 2 | data-feeds | `E23-T01`, `E23-T03` |
| `E24-T04` | DerivativesEngine and metric-descriptor registration in the MetricRegistry | Task | 5 | indicators | `E24-T01`, `E24-T02`, `E24-T03` |
| `E24-T06` | Golden-fixture parity harness for derivatives metrics vs offline DuckDB | Task | 3 | indicators | `E24-T04` |
| `E25-Q01` | Author the black-box test plan and exploratory charters for detectors | Task | 3 | cross-cutting | `E25-T02` |
| `E25-T01` | Build MetricsEngine: rolling tape and book statistics with z-scores | Task | 5 | data-feeds | `E08`, `E21` |
| `E25-T02` | Detector framework, config persistence and the three detector endpoints | Task | 3 | api | `E25-T01`, `E25-X01` |
| `E25-T03` | Implement absorption and iceberg detectors (estimated) in M9 | Task | 5 | data-feeds | `E25-T02`, `E25-K01`, `E18` |
| `E25-T05` | Implement market-regime classifier and /market/regime/explain | Task | 3 | data-feeds | `E25-T01`, `E23` |
| `E25-T06` | Track stacked imbalance runs over footprint cells and publish them | Task | 2 | data-feeds | `E25-T02`, `E18` |
| `E26-T07` | Finalise ADR-0018, replay observability and plan-doc reconciliation | Task | 2 | docs | `E26-T06`, `E26-T05`, `E26-D01` |
| `E27-D01` | UX research: how the owner actually manages exchange keys, rotation and compromise | Task | 2 | web | `E09` |
| `E27-D02` | Wireframe SCR-125, SCR-126, SCR-127, SCR-128, SCR-129 and SCR-079 with every state | Task | 3 | web | `E27-D01` |
| `E29-D01` | UX research: what traders need from a positions and orders blotter | Task | 3 | web | `E27` |
| `E29-D02` | Wireframe to hi-fi: SCR-063 positions & orders grid panel | Task | 5 | web | `E29-D01` |

### 14.5 Design-track deliverables due

**Design sprint D-S12** (roadmap 1.2) produces: Rule engine form editor

> Consumed by engineering sprint **S14** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S14 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E20-D06` | Design QA sweep of the built Deep-Stats surfaces | 2 | 2026-12-17 |
| `E21-D08` | Design QA of the shipped DOM ladder and heatmap | 3 | 2026-12-17 |
| `E27-D01` | UX research: how the owner actually manages exchange keys, rotation and compromise | 2 | 2026-12-17 |
| `E27-D02` | Wireframe SCR-125, SCR-126, SCR-127, SCR-128, SCR-129 and SCR-079 with every state | 3 | 2026-12-17 |
| `E29-D01` | UX research: what traders need from a positions and orders blotter | 3 | 2026-12-17 |
| `E29-D02` | Wireframe to hi-fi: SCR-063 positions & orders grid panel | 5 | 2026-12-17 |

Design total: **18 pts** across 6 tickets.

### 14.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: STRIDE R2 epics (s04, S10-S13)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Order-flow correctness suite (q05, S10-S13)
- qa: Load & soak campaigns (q07, S09-S20)

**QA tickets (55 pts, 17 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E19-Q03` | Playwright E2E for the profile panel, period modes and settings dialog | 5 | `E19-Q01`, `E19-S01`, `E19-S04`, `E19-T04` |
| `E19-Q04` | Performance and load pack for profile compute, WS fan-out and row rendering | 5 | `E19-Q02`, `E19-T03`, `E19-T04` |
| `E19-Q05` | Chaos scenarios: feed gaps, store outages, recorder limits and restart recovery | 3 | `E19-Q02`, `E19-T01`, `E19-T03` |
| `E20-Q01` | Black-box test plan and exploratory charter for Deep-Stats rows | 2 | `E20-S01`, `E20-D05` |
| `E20-Q02` | E2E suite additions for the Deep-Stats strip, configuration and export | 3 | `E20-S02`, `E20-S03`, `E20-S04`, `E20-Q01` |
| `E20-Q03` | Performance benchmark and load profile for the Deep-Stats strip | 3 | `E20-S03`, `E20-K01` |
| `E20-Q04` | Accessibility audit of the Deep-Stats strip, SCR-033 and SCR-045 | 2 | `E20-S03`, `E20-S04`, `E20-D04` |
| `E20-Q05` | Epic-level QA sign-off: regression pack and exploratory debrief for E20 | 2 | `E20-Q02`, `E20-Q03`, `E20-Q04`, `E20-X02`, `E20-T03` |
| `E21-Q02` | E2E suite additions for SCR-050 and SCR-051 | 5 | `E21-Q01`, `E21-S01`, `E21-S02`, `E21-S05` |
| `E21-Q03` | Performance and load scripts for the heatmap cadence and book fan-out | 5 | `E21-K01`, `E21-T02`, `E21-S02`, `E21-S05` |
| `E21-Q04` | Chaos scenarios: desync storms, slow consumers and exchange failures | 3 | `E21-Q02`, `E21-T01`, `E21-T02` |
| `E21-Q05` | Accessibility audit of the ladder grid, heatmap reveal and settings dialog | 5 | `E21-S01`, `E21-S02`, `E21-S09`, `E21-D06` |
| `E21-Q06` | Exploratory charter and regression pack for the order-flow DOM surface | 3 | `E21-Q02`, `E21-Q04` |
| `E21-Q07` | QA sign-off for the DOM ladder and liquidity heatmap epic | 2 | `E21-Q01`, `E21-Q02`, `E21-Q03`, `E21-Q04`, `E21-Q05`, `E21-Q06`, `E21-D08` |
| `E22-Q01` | Black-box test plan and exploratory charter for big trades & bubbles | 2 | `E22-D05`, `E22-T02` |
| `E23-Q01` | Black-box test plan and exploratory charter for CVD & delta panes | 2 | `E23-D05`, `E23-T02` |
| `E25-Q01` | Author the black-box test plan and exploratory charters for detectors | 3 | `E25-T02` |

**Security tickets (11 pts, 4 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E18-X02` | Security review and abuse-case testing of the footprint read and rebuild paths | 2 | `E18-X01`, `E18-T03`, `E18-T04`, `E18-T05` |
| `E19-X02` | Abuse cases: parameter fuzzing, exhaustion and profile integrity | 5 | `E19-X01`, `E19-T02`, `E19-T03` |
| `E20-X02` | Security review of the Deep-Stats export path and abuse-case testing | 2 | `E20-X01`, `E20-T02` |
| `E21-X03` | Security review and sign-off of the shipped DOM and heatmap surface | 2 | `E21-X01`, `E21-X02`, `E21-S06`, `E21-Q04` |

### 14.7 Risks & dependency watch-list

- E21 at 50 pts on the heatmap render path, concurrent with E20 at 33 - the peak engine-contention sprint of R2.
- E27/E29 start early inside R2; they must not consume R2 buffer meant for footprint/heatmap overruns.
- QA jumps to 42 pts (order-flow correctness suite) - the QA pool, not eng, is the binding constraint.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S12 |
|---|---|---|
| `E21-S02` | Sprint 11 | 8 |
| `E21-S01` | Sprint 11 | 6 |
| `E22-D05` | Sprint 09 | 6 |
| `E20-D05` | Sprint 10 | 4 |
| `E20-T02` | Sprint 11 | 4 |
| `E21-T01` | Sprint 10 | 4 |
| `E19-T03` | Sprint 10 | 3 |
| `E20-K01` | Sprint 11 | 3 |
| `E21-D07` | Sprint 09 | 3 |
| `E21-K01` | Sprint 10 | 3 |
| `E22-T02` | Sprint 11 | 3 |
| `E19-S01` | Sprint 11 | 2 |
| _... 45 more_ | | |

### 14.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Deep-Stats rows complete; detector badges showing the *(estimated)* pattern; derivatives metrics live.

**Exit expectation:** No render-budget regression vs the S11 baseline.

### 14.9 Burn-up - R2 train

| Sprint | Eng pts this sprint | Cumulative R2 | R2 total | Remaining | % complete |
|---|---|---|---|---|---|
| S10 | 89 | 89 | 357 | 268 | 25% |
| S11 | 89 | 178 | 357 | 179 | 50% |
| S12 **<- this sprint** | 89 | 267 | 357 | 90 | 75% |
| S13 | 90 | 357 | 357 | 0 | 100% |

---

## 15. S13 - 2026-12-18 -> 2026-12-24 (R2)

### 15.1 Sprint goal(s)

- **Close R2 and cut `0.3.0`.** Replay engine completes (E26) - the deterministic test harness R3 depends on.
- Derivatives metrics and CVD panes finish (E24 40, E23 30); detectors land (E25 31).
- **QA is over pool: 83 pts vs 45 (+38).**

### 15.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 90 | 90 | +0 | ok |
| Design (D) | 52 | 60 | +8 | ok |
| QA (Q) | 83 | 45 | -38 | **OVER** |
| Security (X) | 19 | 20 | +1 | ok |
| **Total** | **244** | **215** | **-29** | |

### 15.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E26** | Replay engine & scrubbing | Data & Feeds (BE-Feeds) | 50 | 16 |
| **E24** | Derivatives metrics: open interest, funding, liquidations and basis | Order Flow (BE-Flow + FE-Engine) | 40 | 16 |
| **E25** | Detectors: tape speed, imbalance, regime, iceberg/stop-run (estimated) | Order Flow (BE-Flow + FE-Engine) | 31 | 14 |
| **E23** | CVD & delta panes: cumulative delta, anchors, display modes and divergence | Order Flow (BE-Flow + FE-Engine) | 30 | 13 |
| **E19** | Volume / delta / TPO profiles | Order Flow (BE-Flow + FE-Engine) | 27 | 9 |
| **E18** | Footprint: cell aggregation, imbalance detection and cell rendering | Order Flow (BE-Flow + FE-Engine) | 15 | 6 |
| **E22** | Big trades & bubbles: tape, thresholds, clustering and the bubble overlay | Order Flow (BE-Flow + FE-Engine) | 14 | 6 |
| **E29** | OMS core & order state machine | OMS & Execution (BE-OMS) | 10 | 4 |
| **E27** | Accounts, sub-accounts & API-key vault | Accounts & Security (BE-Sec) | 6 | 4 |
| **E28** | Per-account profiles & trade groups | OMS & Execution (BE-OMS) | 5 | 2 |
| **E42** | Admin screens (users, roles, audit, health, flags) | Accounts & Security (BE-Sec) | 5 | 2 |
| **E30** | Order ticket UI | App & Charting UI (FE-App) | 3 | 1 |
| **E32** | Brackets, scaled orders & native SL invariant | OMS & Execution (BE-OMS) | 3 | 1 |
| **E39** | Risk caps, lockouts & kill-switch | OMS & Execution (BE-OMS) | 3 | 1 |
| **E37** | Rule node-graph editor (SCR-082) with lossless IR round-trip | App & Charting UI (FE-App) | 2 | 1 |


**Statechart lane:** E18 (`E18-D06`, `E18-Q02`, `E18-Q03`, `E18-Q04`, `E18-Q05`, `E18-S11`); E19 (`E19-C01`, `E19-D08`, `E19-Q06`, `E19-Q07`, `E19-Q08`, `E19-S03`, `E19-S08`, `E19-X03`, `E19-X04`); E32 (`E32-D01`); E39 (`E39-D01`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 15.4 Tickets (96)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E18-D06` | Design QA sweep of the built footprint surfaces at all densities | Task | 2 | chart-engine | `E18-S09`, `E18-S10`, `E18-S06` |
| `E18-Q02` | Add the footprint E2E and integration suite to CI | Task | 3 | chart-engine | `E18-Q01`, `E18-S10`, `E18-S08`, `E18-S09` |
| `E18-Q03` | Footprint performance benchmark, load profile and CI gate | Task | 3 | chart-engine | `E18-K01`, `E18-S06`, `E18-S02`, `E18-T04` |
| `E18-Q04` | Accessibility audit of the footprint surfaces | Task | 2 | web | `E18-S11`, `E18-S10`, `E18-D04` |
| `E18-Q05` | Epic-level regression pack and QA sign-off for E18 | Task | 2 | chart-engine | `E18-Q02`, `E18-Q03`, `E18-Q04`, `E18-X02`, `E18-T06` |
| `E18-S11` | Make footprint cells keyboard-navigable and screen-reader accessible | Story | 3 | web | `E18-S01`, `E18-D04` |
| `E19-C01` | ADR and reference doc for profile period semantics, value area and naked POC | Chore | 2 | docs | `E19-Q02`, `E19-X04` |
| `E19-D08` | Design QA of the shipped profile panel, settings dialog and TPO pane | Task | 3 | web | `E19-D07` |
| `E19-Q06` | Accessibility audit of the profile panel, table alternative and settings dialog | Task | 5 | web | `E19-Q03`, `E19-S01`, `E19-S04`, `E19-D03` |
| `E19-Q07` | Exploratory charters and the E19 profile regression pack | Task | 3 | indicators | `E19-Q02`, `E19-Q03`, `E19-Q05` |
| `E19-Q08` | E19 QA sign-off: rollup, traceability evidence and R2 exit-gate input | Task | 3 | indicators | `E19-Q02`, `E19-Q03`, `E19-Q04`, `E19-Q05`, `E19-Q06`, `E19-Q07`, `E19-X03` |
| `E19-S03` | Composite and per-session multiple profiles served from the cold tier | Story | 3 | indicators | `E19-S02`, `E16` |
| `E19-S08` | TPO / market profile with 24-7 periods, initial balance and single prints | Story | 3 | indicators | `E19-S04` |
| `E19-X03` | SAST/DAST rules and CI security gates for the profile compute and read paths | Task | 3 | infra | `E19-X01`, `E19-T01`, `E19-T02` |
| `E19-X04` | Security review and sign-off for E19 profiles | Task | 2 | cross-cutting | `E19-X01`, `E19-X02`, `E19-X03`, `E19-Q05` |
| `E22-D06` | Design QA sweep of the built tape and bubble overlay | Task | 2 | web | `E22-S01`, `E22-S03`, `E22-S05` |
| `E22-Q02` | Playwright E2E suite for tape, thresholds, clustering and bubbles | Task | 3 | web | `E22-Q01`, `E22-S01`, `E22-S03`, `E22-S05` |
| `E22-Q03` | Perf and load scripts: 2 000 prints/s tape and 5 000-bubble scene | Task | 3 | chart-engine | `E22-K01`, `E22-S03`, `E22-S01` |
| `E22-Q04` | Accessibility audit of SCR-053 tape and the bubble DOM mirror | Task | 2 | web | `E22-S01`, `E22-S04`, `E22-D04` |
| `E22-Q05` | Epic-level QA sign-off: regression pack and exploratory debrief for E22 | Task | 2 | chart-engine | `E22-Q02`, `E22-Q03`, `E22-Q04`, `E22-X02`, `E22-T04`, `E22-D06` |
| `E22-X02` | Security review and abuse-case testing of the big-trade data surfaces | Task | 2 | api | `E22-X01`, `E22-T02`, `E22-S02` |
| `E23-D06` | Design QA sweep of the built CVD / delta pane | Task | 2 | web | `E23-S03`, `E23-S05`, `E23-D05` |
| `E23-Q02` | Playwright E2E suite for the CVD pane: anchors, modes and divergence | Task | 3 | web | `E23-Q01`, `E23-S03`, `E23-S05` |
| `E23-Q03` | Performance scripts: three CVD panes at 5,000 trades/min and 1M-print recompute | Task | 3 | web | `E23-K01`, `E23-S03`, `E23-T02` |
| `E23-Q04` | Accessibility audit of SCR-052 including the table alternative | Task | 2 | web | `E23-S04`, `E23-S05`, `E23-D04` |
| `E23-Q05` | QA sign-off for E23: regression pack, exploratory debrief and PRR evidence | Task | 2 | cross-cutting | `E23-Q02`, `E23-Q03`, `E23-Q04`, `E23-Q06`, `E23-X02`, `E23-D06`, `E23-T05` |
| `E23-Q06` | Chaos scenarios: WS gaps, recorder holes and repair storms on the CVD path | Task | 3 | data-feeds | `E23-T03`, `E23-T04` |
| `E23-S01` | Render the per-bar delta pane (SCR-052, CMP-185) with live and gapped bars | Story | 3 | web | `E23-T02`, `E23-D05`, `E11` |
| `E23-S02` | Cumulative delta with session, UTC-day, never and manual reset anchors | Story | 2 | web | `E23-S01`, `E23-T03`, `E23-D05` |
| `E23-S03` | CVD display modes (line, histogram, candles) and EMA smoothing overlay | Story | 2 | web | `E23-S02`, `E23-D05` |
| `E23-S04` | Single-bar delta divergence flags with threshold control and (estimated) chip | Story | 2 | web | `E23-S01`, `E23-D05` |
| `E23-S05` | Multi-bar swing divergence between price and CVD with no repainting | Story | 3 | web | `E23-S02`, `E23-S04`, `E13`, `E23-D05` |
| `E23-T05` | ADR-0017: CVD anchor semantics, reconnect recompute and divergence determinism | Task | 1 | docs | `E23-K01`, `E23-T03`, `E23-T04`, `E23-S05` |
| `E23-X02` | Security review and abuse-case testing of the CVD metrics surface | Task | 2 | api | `E23-X01`, `E23-T02`, `E23-T03` |
| `E24-D06` | Design QA sweep of the built derivatives panel | Task | 2 | web | `E24-S07`, `E24-S08` |
| `E24-Q01` | Black-box test plan and exploratory charter for derivatives metrics | Task | 2 | cross-cutting | `E24-S02`, `E24-S04`, `E24-D05` |
| `E24-Q02` | Playwright E2E suite additions for the SCR-054 derivatives panel | Task | 3 | cross-cutting | `E24-Q01`, `E24-S06` |
| `E24-Q03` | Cascade load script and perf benchmark for the derivatives surfaces | Task | 3 | cross-cutting | `E24-S05`, `E24-S08` |
| `E24-Q04` | Accessibility audit of SCR-054 and the derivatives table alternatives | Task | 2 | cross-cutting | `E24-Q02`, `E24-D04` |
| `E24-Q05` | Epic QA sign-off: derivatives regression pack and exploratory debrief | Task | 2 | cross-cutting | `E24-Q03`, `E24-Q04`, `E24-D06`, `E24-T06` |
| `E24-S01` | Render the open-interest sub-pane on SCR-054 with backfill and gap states | Story | 3 | web | `E24-T04`, `E24-D05` |
| `E24-S02` | OI delta mode and OI/price quadrant classification on the OI sub-pane | Story | 3 | web | `E24-S01` |
| `E24-S03` | Funding rate, stepped history and second-accurate settlement countdown | Story | 3 | web | `E24-T02`, `E24-T04`, `E24-D05` |
| `E24-S04` | Predicted and annualised funding with explicit non-settled styling | Story | 2 | web | `E24-S03` |
| `E24-S05` | Liquidation feed with burst coalescing and recorder-bounded history disclosure | Story | 3 | web | `E24-T03`, `E24-T04`, `E24-D05` |
| `E24-S06` | Per-bar liquidation bars split long/short with threshold and history boundary | Story | 3 | web | `E24-S05` |
| `E24-S07` | Estimated liquidation zones: off by default, acknowledged, badged and disclosed | Story | 3 | web | `E24-S06`, `E24-K01` |
| `E24-S08` | Basis, mark/index readout and long/short ratio with retry state | Story | 3 | web | `E24-T04`, `E24-D05` |
| `E24-T05` | ADR-0017 derivatives provenance and plan-doc reconciliation for E24 | Task | 1 | docs | `E24-S08`, `E24-Q05` |
| `E24-X02` | Security review and abuse-case testing of the derivatives surfaces | Task | 2 | cross-cutting | `E24-X01`, `E24-S07`, `E24-S08` |
| `E25-D08` | Design QA sweep of the built detector surfaces against the specs | Task | 2 | web | `E25-S01`, `E25-S02`, `E25-S03`, `E25-S04`, `E25-S05`, `E25-S06` |
| `E25-Q02` | Add Playwright E2E coverage for the detector surfaces and flows | Task | 3 | cross-cutting | `E25-Q01`, `E25-S01`, `E25-S05` |
| `E25-Q03` | Determinism, perf and chaos testing for the detector pipeline | Task | 3 | cross-cutting | `E25-Q01`, `E25-T03`, `E25-T04`, `E25-T05`, `E25-S06` |
| `E25-Q04` | Accessibility audit of SCR-055..059 and the detector markers | Task | 2 | cross-cutting | `E25-Q01`, `E25-S02`, `E25-S03`, `E25-S04`, `E25-S05` |
| `E25-Q05` | Run the detector regression pack and give QA sign-off for E25 | Task | 1 | cross-cutting | `E25-Q02`, `E25-Q03`, `E25-Q04`, `E25-D08`, `E25-X02` |
| `E25-S01` | Build the speed-of-tape panel (SCR-055) with gauge, strip and z-score | Story | 3 | web | `E25-T01`, `E25-D07` |
| `E25-S02` | Build the imbalance tracker panel (SCR-056) with chart cross-highlight | Story | 3 | web | `E25-T06`, `E25-D07` |
| `E25-S03` | Build the market regime panel (SCR-057) with sub-signal breakdown | Story | 2 | web | `E25-T05`, `E25-D07` |
| `E25-S04` | Build the detector methodology drawer SCR-058 ("Why estimated?") | Story | 1 | web | `E25-T07`, `E25-D07` |
| `E25-S05` | Build the detector settings dialog SCR-059 with armed-rule warnings | Story | 3 | web | `E25-T02`, `E25-D07` |
| `E25-S06` | Render detector event markers and DetectorEventCard on the chart | Story | 2 | chart-engine | `E25-T03`, `E25-T04`, `E25-D07` |
| `E25-T04` | Implement stop-run / liquidity-sweep detector (estimated) in M9 | Task | 3 | data-feeds | `E25-T02`, `E25-K01`, `E21` |
| `E25-T07` | Author detector methodology content, vocabulary docs and feature flags | Task | 1 | docs | `E25-T03`, `E25-T04`, `E25-T05`, `E25-K01` |
| `E25-X02` | Security review of the detector config write path and event bus | Task | 2 | cross-cutting | `E25-X01`, `E25-T02`, `E25-S05` |
| `E26-D08` | Design QA of the built replay surfaces against spec | Task | 2 | web | `E26-S02`, `E26-S06`, `E26-S07` |
| `E26-Q01` | Write the black-box test plan for replay sessions, playback and fidelity | Task | 3 | data-feeds | `E26-D07`, `E26-T05` |
| `E26-Q02` | Automate the Playwright E2E suite for replay setup, playback and navigation | Task | 3 | web | `E26-Q01`, `E26-S02`, `E26-S06` |
| `E26-Q03` | Build replay performance, 100x soak and seek-budget benchmarks as CI gates | Task | 3 | data-feeds | `E26-Q01`, `E26-T04`, `E26-S05` |
| `E26-Q04` | Chaos scenarios for replay: gaps, pruning, slow consumers, restarts, expiry | Task | 3 | data-feeds | `E26-Q01`, `E26-T03` |
| `E26-Q05` | Accessibility audit of SCR-097, SCR-098, SCR-099 and the replay components | Task | 3 | web | `E26-Q02`, `E26-S07` |
| `E26-Q06` | Assemble the replay regression pack, run charters and record epic QA sign-off | Task | 3 | data-feeds | `E26-Q02`, `E26-Q03`, `E26-Q04`, `E26-Q05`, `E26-S08`, `E26-D08`, `E26-X03` |
| `E26-S02` | Build SCR-097 replay page: transport, scrubbing and unmistakable REPLAY chrome | Story | 8 | web | `E26-S01`, `E26-T05`, `E26-D07` |
| `E26-S03` | Tick-by-tick replay with honest rate reporting and a no-tick-data fallback | Story | 2 | web | `E26-S02` |
| `E26-S04` | Replay the order book and liquidity heatmap with a not-recorded state | Story | 3 | web | `E26-S03`, `E21` |
| `E26-S05` | Synchronise every pane to one replay clock, with a per-pane live opt-out | Story | 2 | web | `E26-S02`, `E15` |
| `E26-S06` | Replay navigation aids, bookmarks and loop ranges | Story | 2 | web | `E26-S02`, `E25` |
| `E26-S07` | Simulated trading in replay with hard isolation and the SCR-099 results drawer | Story | 5 | web | `E26-S04`, `E26-X02` |
| `E26-S08` | Restore replay position, speed and pane configuration across machines | Story | 2 | web | `E26-S05`, `E26-S06` |
| `E26-X02` | Implement replay abuse-case tests, path-safety controls and SAST/DAST rules | Task | 3 | api | `E26-X01`, `E26-T05` |
| `E26-X03` | Security review and sign-off of replay and simulated-trading isolation | Task | 3 | api | `E26-X02`, `E26-S07`, `E26-T07` |
| `E27-D03` | Hi-fi design and design-system contributions for the accounts and key-vault surfaces | Task | 3 | web | `E27-D02` |
| `E27-D04` | Specify motion and state-transition choreography for key verification, rotation and danger states | Task | 1 | web | `E27-D03` |
| `E27-D05` | Accessibility design review of the six accounts and key-vault surfaces | Task | 1 | web | `E27-D03`, `E27-D04` |
| `E27-D06` | Produce and sign off the engineering handoff pack for the accounts and key-vault epic | Task | 1 | web | `E27-D03`, `E27-D04`, `E27-D05` |
| `E28-D01` | UX research: how the owner sets risk policy per account and thinks about fan-out | Task | 2 | web | `E27-D01` |
| `E28-D02` | Wireframe SCR-130, SCR-131, SCR-132, SCR-133, SCR-062 and the SCR-061 preview with every state | Task | 3 | web | `E28-D01` |
| `E29-D03` | Hi-fi: SCR-078 fills detail and the reconciling/desync states on SCR-152 | Task | 3 | web | `E29-D01` |
| `E29-D04` | Design-system contributions and motion spec for blotter components | Task | 3 | web | `E29-D02`, `E29-D03` |
| `E29-D05` | Accessibility design review of the blotters and correction messaging | Task | 2 | web | `E29-D02`, `E29-D03`, `E29-D04` |
| `E29-D06` | Design handoff package for the OMS blotters | Task | 2 | web | `E29-D05` |
| `E30-D01` | UX research: how traders decide, size and fire an order under time pressure | Task | 3 | web | `E27`, `E28` |
| `E32-D01` | Run UX research on bracket, ladder and mandatory-stop mental models | Task | 3 | web |  |
| `E37-D01` | UX research: how rule authors reason about a node graph vs a condition list | Task | 2 | web |  |
| `E39-D01` | UX research and wireframes for risk caps, lockout and kill-switch flows | Task | 3 | web |  |
| `E42-D01` | UX research: how an owner supervises, delegates and investigates | Task | 2 | web |  |
| `E42-D02` | Wireframe the admin area: shell, overview, users, audit, health and flags | Task | 3 | web | `E42-D01` |

### 15.5 Design-track deliverables due

**Design sprint D-S13** (roadmap 1.2) produces: Rule engine node-graph editor, simulation UX

> Consumed by engineering sprint **S15** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S15 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E18-D06` | Design QA sweep of the built footprint surfaces at all densities | 2 | 2026-12-24 |
| `E19-D08` | Design QA of the shipped profile panel, settings dialog and TPO pane | 3 | 2026-12-24 |
| `E22-D06` | Design QA sweep of the built tape and bubble overlay | 2 | 2026-12-24 |
| `E23-D06` | Design QA sweep of the built CVD / delta pane | 2 | 2026-12-24 |
| `E24-D06` | Design QA sweep of the built derivatives panel | 2 | 2026-12-24 |
| `E25-D08` | Design QA sweep of the built detector surfaces against the specs | 2 | 2026-12-24 |
| `E26-D08` | Design QA of the built replay surfaces against spec | 2 | 2026-12-24 |
| `E27-D03` | Hi-fi design and design-system contributions for the accounts and key-vault surfaces | 3 | 2026-12-24 |
| `E27-D04` | Specify motion and state-transition choreography for key verification, rotation and danger states | 1 | 2026-12-24 |
| `E27-D05` | Accessibility design review of the six accounts and key-vault surfaces | 1 | 2026-12-24 |
| `E27-D06` | Produce and sign off the engineering handoff pack for the accounts and key-vault epic | 1 | 2026-12-24 |
| `E28-D01` | UX research: how the owner sets risk policy per account and thinks about fan-out | 2 | 2026-12-24 |
| `E28-D02` | Wireframe SCR-130, SCR-131, SCR-132, SCR-133, SCR-062 and the SCR-061 preview with every state | 3 | 2026-12-24 |
| `E29-D03` | Hi-fi: SCR-078 fills detail and the reconciling/desync states on SCR-152 | 3 | 2026-12-24 |
| `E29-D04` | Design-system contributions and motion spec for blotter components | 3 | 2026-12-24 |
| `E29-D05` | Accessibility design review of the blotters and correction messaging | 2 | 2026-12-24 |
| `E29-D06` | Design handoff package for the OMS blotters | 2 | 2026-12-24 |
| `E30-D01` | UX research: how traders decide, size and fire an order under time pressure | 3 | 2026-12-24 |
| `E32-D01` | Run UX research on bracket, ladder and mandatory-stop mental models | 3 | 2026-12-24 |
| `E37-D01` | UX research: how rule authors reason about a node graph vs a condition list | 2 | 2026-12-24 |
| `E39-D01` | UX research and wireframes for risk caps, lockout and kill-switch flows | 3 | 2026-12-24 |
| `E42-D01` | UX research: how an owner supervises, delegates and investigates | 2 | 2026-12-24 |
| `E42-D02` | Wireframe the admin area: shell, overview, users, audit, health and flags | 3 | 2026-12-24 |

Design total: **52 pts** across 23 tickets.

### 15.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: STRIDE R2 epics (s04, S10-S13)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Order-flow correctness suite (q05, S10-S13)
- qa: Load & soak campaigns (q07, S09-S20)

**QA tickets (83 pts, 31 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E18-Q02` | Add the footprint E2E and integration suite to CI | 3 | `E18-Q01`, `E18-S10`, `E18-S08`, `E18-S09` |
| `E18-Q03` | Footprint performance benchmark, load profile and CI gate | 3 | `E18-K01`, `E18-S06`, `E18-S02`, `E18-T04` |
| `E18-Q04` | Accessibility audit of the footprint surfaces | 2 | `E18-S11`, `E18-S10`, `E18-D04` |
| `E18-Q05` | Epic-level regression pack and QA sign-off for E18 | 2 | `E18-Q02`, `E18-Q03`, `E18-Q04`, `E18-X02`, `E18-T06` |
| `E19-Q06` | Accessibility audit of the profile panel, table alternative and settings dialog | 5 | `E19-Q03`, `E19-S01`, `E19-S04`, `E19-D03` |
| `E19-Q07` | Exploratory charters and the E19 profile regression pack | 3 | `E19-Q02`, `E19-Q03`, `E19-Q05` |
| `E19-Q08` | E19 QA sign-off: rollup, traceability evidence and R2 exit-gate input | 3 | `E19-Q02`, `E19-Q03`, `E19-Q04`, `E19-Q05`, `E19-Q06`, `E19-Q07`, `E19-X03` |
| `E22-Q02` | Playwright E2E suite for tape, thresholds, clustering and bubbles | 3 | `E22-Q01`, `E22-S01`, `E22-S03`, `E22-S05` |
| `E22-Q03` | Perf and load scripts: 2 000 prints/s tape and 5 000-bubble scene | 3 | `E22-K01`, `E22-S03`, `E22-S01` |
| `E22-Q04` | Accessibility audit of SCR-053 tape and the bubble DOM mirror | 2 | `E22-S01`, `E22-S04`, `E22-D04` |
| `E22-Q05` | Epic-level QA sign-off: regression pack and exploratory debrief for E22 | 2 | `E22-Q02`, `E22-Q03`, `E22-Q04`, `E22-X02`, `E22-T04`, `E22-D06` |
| `E23-Q02` | Playwright E2E suite for the CVD pane: anchors, modes and divergence | 3 | `E23-Q01`, `E23-S03`, `E23-S05` |
| `E23-Q03` | Performance scripts: three CVD panes at 5,000 trades/min and 1M-print recompute | 3 | `E23-K01`, `E23-S03`, `E23-T02` |
| `E23-Q04` | Accessibility audit of SCR-052 including the table alternative | 2 | `E23-S04`, `E23-S05`, `E23-D04` |
| `E23-Q05` | QA sign-off for E23: regression pack, exploratory debrief and PRR evidence | 2 | `E23-Q02`, `E23-Q03`, `E23-Q04`, `E23-Q06`, `E23-X02`, `E23-D06`, `E23-T05` |
| `E23-Q06` | Chaos scenarios: WS gaps, recorder holes and repair storms on the CVD path | 3 | `E23-T03`, `E23-T04` |
| `E24-Q01` | Black-box test plan and exploratory charter for derivatives metrics | 2 | `E24-S02`, `E24-S04`, `E24-D05` |
| `E24-Q02` | Playwright E2E suite additions for the SCR-054 derivatives panel | 3 | `E24-Q01`, `E24-S06` |
| `E24-Q03` | Cascade load script and perf benchmark for the derivatives surfaces | 3 | `E24-S05`, `E24-S08` |
| `E24-Q04` | Accessibility audit of SCR-054 and the derivatives table alternatives | 2 | `E24-Q02`, `E24-D04` |
| `E24-Q05` | Epic QA sign-off: derivatives regression pack and exploratory debrief | 2 | `E24-Q03`, `E24-Q04`, `E24-D06`, `E24-T06` |
| `E25-Q02` | Add Playwright E2E coverage for the detector surfaces and flows | 3 | `E25-Q01`, `E25-S01`, `E25-S05` |
| `E25-Q03` | Determinism, perf and chaos testing for the detector pipeline | 3 | `E25-Q01`, `E25-T03`, `E25-T04`, `E25-T05`, `E25-S06` |
| `E25-Q04` | Accessibility audit of SCR-055..059 and the detector markers | 2 | `E25-Q01`, `E25-S02`, `E25-S03`, `E25-S04`, `E25-S05` |
| `E25-Q05` | Run the detector regression pack and give QA sign-off for E25 | 1 | `E25-Q02`, `E25-Q03`, `E25-Q04`, `E25-D08`, `E25-X02` |
| `E26-Q01` | Write the black-box test plan for replay sessions, playback and fidelity | 3 | `E26-D07`, `E26-T05` |
| `E26-Q02` | Automate the Playwright E2E suite for replay setup, playback and navigation | 3 | `E26-Q01`, `E26-S02`, `E26-S06` |
| `E26-Q03` | Build replay performance, 100x soak and seek-budget benchmarks as CI gates | 3 | `E26-Q01`, `E26-T04`, `E26-S05` |
| `E26-Q04` | Chaos scenarios for replay: gaps, pruning, slow consumers, restarts, expiry | 3 | `E26-Q01`, `E26-T03` |
| `E26-Q05` | Accessibility audit of SCR-097, SCR-098, SCR-099 and the replay components | 3 | `E26-Q02`, `E26-S07` |
| `E26-Q06` | Assemble the replay regression pack, run charters and record epic QA sign-off | 3 | `E26-Q02`, `E26-Q03`, `E26-Q04`, `E26-Q05`, `E26-S08`, `E26-D08`, `E26-X03` |

**Security tickets (19 pts, 8 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E19-X03` | SAST/DAST rules and CI security gates for the profile compute and read paths | 3 | `E19-X01`, `E19-T01`, `E19-T02` |
| `E19-X04` | Security review and sign-off for E19 profiles | 2 | `E19-X01`, `E19-X02`, `E19-X03`, `E19-Q05` |
| `E22-X02` | Security review and abuse-case testing of the big-trade data surfaces | 2 | `E22-X01`, `E22-T02`, `E22-S02` |
| `E23-X02` | Security review and abuse-case testing of the CVD metrics surface | 2 | `E23-X01`, `E23-T02`, `E23-T03` |
| `E24-X02` | Security review and abuse-case testing of the derivatives surfaces | 2 | `E24-X01`, `E24-S07`, `E24-S08` |
| `E25-X02` | Security review of the detector config write path and event bus | 2 | `E25-X01`, `E25-T02`, `E25-S05` |
| `E26-X02` | Implement replay abuse-case tests, path-safety controls and SAST/DAST rules | 3 | `E26-X01`, `E26-T05` |
| `E26-X03` | Security review and sign-off of replay and simulated-trading isolation | 3 | `E26-X02`, `E26-S07`, `E26-T07` |

### 15.7 Risks & dependency watch-list

- **QA at 72 pts and design at 56 pts** - both far above steady state. This is an R2-exit evidence pile-up.
- **10 DESIGN-AHEAD errors land here**: E24-S01/S03/S05/S08 consume E24-D05 (same sprint) and E25-S01..S06 consume E25-D07 (one sprint prior). Both violate the >=2-sprint rule - needs an Architect/CDO waiver or a re-sequence before S13 opens.
- **R2 exit gate 2026-12-24 + PRR.**

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S13 |
|---|---|---|
| `E23-D05` | Sprint 11 | 6 |
| `E25-D07` | Sprint 11 | 6 |
| `E24-D05` | Sprint 11 | 5 |
| `E22-S01` | Sprint 12 | 4 |
| `E23-T03` | Sprint 11 | 4 |
| `E24-T04` | Sprint 12 | 4 |
| `E18-S10` | Sprint 12 | 3 |
| `E19-Q02` | Sprint 11 | 3 |
| `E19-Q03` | Sprint 12 | 3 |
| `E19-S04` | Sprint 11 | 3 |
| `E19-Q05` | Sprint 12 | 3 |
| `E22-S03` | Sprint 12 | 3 |
| _... 68 more_ | | |

### 15.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** R2 acceptance: replay a recorded session with footprint, profiles, heatmap, CVD, derivatives and detectors all active and deterministic.

**Exit expectation:** **R2 gate (PRR) 2026-12-24 - `0.3.0` tagged, deployed to staging (demo).**

### 15.9 Burn-up - R2 train

| Sprint | Eng pts this sprint | Cumulative R2 | R2 total | Remaining | % complete |
|---|---|---|---|---|---|
| S10 | 89 | 89 | 357 | 268 | 25% |
| S11 | 89 | 178 | 357 | 179 | 50% |
| S12 | 89 | 267 | 357 | 90 | 75% |
| S13 **<- this sprint** | 90 | 357 | 357 | 0 | 100% |

---

# R3 - Trading on demo

| | |
|---|---|
| Sprints | S14-S19 |
| Dates | 2026-12-25 -> 2027-02-04 |
| Version at cut | `0.4.0` |
| Deploys to | staging (demo), 7-day soak |
| Gate | PRR + demo-trading soak gate |
| Eng pts in backlog | 488 of 540 capacity (90%) |
| All-discipline pts | 1070 |

R3 is the largest train in the plan: accounts and the key vault, per-account profiles, the OMS, order ticket, chart and DOM trading, brackets with the native-SL invariant, emulated algos, trade-group fan-out, the rule engine and both editors, paper trading, risk caps and kill-switch, alerts, journal and admin screens. Safety ordering (roadmap 11.3 rule 2) governs sequencing throughout: no order-placing UI ships before the vault, risk caps and native SL are Done.

---

## 16. S14 - 2026-12-25 -> 2026-12-31 (R3)

### 16.1 Sprint goal(s)

- **Open R3 on the two safety-critical roots.** Accounts + API-key vault (E27) and OMS core state machine (E29) start day 1.
- Rule-engine IR and compiler begin (E35); rule form editor starts behind it (E36).
- Deliberately light eng load (34 pts) against a heavy design load (58 pts) - R3's UI surface is being designed ahead.

### 16.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 88 | 90 | +2 | ok |
| Design (D) | 58 | 60 | +2 | ok |
| QA (Q) | 6 | 45 | +39 | ok |
| Security (X) | 12 | 20 | +8 | ok |
| **Total** | **164** | **215** | **+51** | |

### 16.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E35** | Rule engine IR, compiler & runtime | Rules & Alerts (BE-Rules) | 31 | 11 |
| **E27** | Accounts, sub-accounts & API-key vault | Accounts & Security (BE-Sec) | 23 | 7 |
| **E29** | OMS core & order state machine | OMS & Execution (BE-OMS) | 17 | 7 |
| **E39** | Risk caps, lockouts & kill-switch | OMS & Execution (BE-OMS) | 16 | 6 |
| **E42** | Admin screens (users, roles, audit, health, flags) | Accounts & Security (BE-Sec) | 15 | 5 |
| **E30** | Order ticket UI | App & Charting UI (FE-App) | 11 | 3 |
| **E34** | Trade-group fan-out & rate-limit governor | OMS & Execution (BE-OMS) | 11 | 2 |
| **E36** | Rule form editor | App & Charting UI (FE-App) | 11 | 3 |
| **E37** | Rule node-graph editor (SCR-082) with lossless IR round-trip | App & Charting UI (FE-App) | 10 | 3 |
| **E28** | Per-account profiles & trade groups | OMS & Execution (BE-OMS) | 6 | 4 |
| **E32** | Brackets, scaled orders & native SL invariant | OMS & Execution (BE-OMS) | 5 | 2 |
| **E31** | Chart & DOM trading interactions | App & Charting UI (FE-App) | 3 | 2 |
| **E33** | Emulated algos (OCO, iceberg, TWAP, chase) | OMS & Execution (BE-OMS) | 3 | 1 |
| **E40** | Alerts & notifications | Rules & Alerts (BE-Rules) | 2 | 2 |


**Statechart lane:** E29 (`E29-T03`, `E29-T05`); E31 (`E31-D01`, `E31-K01`); E32 (`E32-D02`, `E32-K01`); E33 (`E33-D01`); E34 (`E34-K01`, `E34-T02`); E35 (`E35-D01`, `E35-K01`, `E35-S02`, `E35-S03`, `E35-S04`, `E35-S06`, `E35-S07`, `E35-T01`, `E35-T02`, `E35-T03`, `E35-T04`); E39 (`E39-D02`, `E39-D03`, `E39-K01`, `E39-T01`, `E39-T02`, `E39-X01`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 16.4 Tickets (58)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E27-K01` | Spike: KEK custody, injection and rotation for the WSL and VPS deployments | Spike | 2 | infra | `E09` |
| `E27-Q01` | Write the black-box test plan and fault-injection fixtures for accounts and the key vault | Task | 3 | api | `E27-T01`, `E27-D02` |
| `E27-T01` | Land exchange_accounts, api_keys and api_key_rotations migrations and domain models | Task | 3 | api | `E09` |
| `E27-T02` | Build the M2 credential broker: envelope encryption, KEK loader and degraded mode | Task | 5 | api | `E27-K01`, `E27-T01` |
| `E27-T03` | Implement the mandatory API-key verification pipeline and the key self-check service | Task | 5 | api | `E27-T02` |
| `E27-T04` | Add per-account health monitoring, key-age policy evaluation and the wallet snapshot cache | Task | 2 | api | `E27-T03` |
| `E27-X01` | Produce the STRIDE threat model for accounts, sub-accounts and the API-key vault | Task | 3 | api | `E27-K01`, `E09` |
| `E28-D03` | Hi-fi design and design-system contributions for the profile and trade-group surfaces | Task | 3 | web | `E28-D02` |
| `E28-D04` | Specify motion and state-transition choreography for profile saves, previews and readiness | Task | 1 | web | `E28-D03` |
| `E28-D05` | Accessibility design review of the six profile and trade-group surfaces | Task | 1 | web | `E28-D03` |
| `E28-D06` | Produce and sign off the engineering handoff pack for the profiles and trade-groups epic | Task | 1 | web | `E28-D03`, `E28-D04`, `E28-D05` |
| `E29-K01` | Spike: measure the Bybit demo order path and private-WS parity before the OMS is built | Spike | 2 | api | `E08`, `E27` |
| `E29-Q01` | Write the black-box test plan and Bybit fixtures for the OMS and its blotters | Task | 3 | docs | `E29-D06`, `E29-K01` |
| `E29-T01` | Create the OMS schema migration and repositories for orders, events, executions, positions | Task | 2 | api | `E27` |
| `E29-T02` | Implement the orderLinkId generator, collision check and adoption rules | Task | 1 | api | `E29-T01` |
| `E29-T03` | Implement the canonical order state machine with write-ahead events | Task | 3 | api | `E29-T01`, `E50-S01`, `E50-T49`, `E50-T59` |
| `E29-T05` | Consume the private WS streams as the source of truth for orders, fills and positions | Task | 3 | api | `E29-K01`, `E29-T03`, `E50-S01`, `E50-T59` |
| `E29-X01` | Produce the STRIDE threat model for the OMS and its order-placement path | Task | 3 | docs | `E29-K01`, `E27` |
| `E30-D02` | Wireframe to hi-fi SCR-060 order ticket with every state drawn | Task | 5 | web | `E30-D01` |
| `E30-D03` | Hi-fi SCR-076, SCR-077, SCR-114 and the account / trade-group selector | Task | 5 | web | `E30-D02` |
| `E30-K01` | Measure order-path latency: recompute, click-to-request and hotkey | Spike | 1 | web | `E29`, `E13` |
| `E31-D01` | UX research and hi-fi design for the chart trading layer (SCR-030, SCR-040) | Task | 2 | web | `E21` |
| `E31-K01` | Prove drag latency, overlay hit-testing and the trading-layer frame budget | Spike | 1 | chart-engine | `E11`, `E21` |
| `E32-D02` | Wireframe SCR-064, SCR-065 and SCR-069 with every state enumerated | Task | 3 | web | `E32-D01` |
| `E32-K01` | Measure attached-SL versus trading-stop attach latency and failure modes on demo | Spike | 2 | api | `E27`, `E29` |
| `E33-D01` | UX research: how traders configure and trust an emulated algorithm | Task | 3 | web |  |
| `E34-K01` | Measure real per-UID rate-limit behaviour and 5-account fan-out latency on demo | Spike | 3 | api | `E27`, `E29` |
| `E34-T02` | Per-UID rate-limit governor: three-bucket budgets, header feedback and 10018 back-off | Task | 8 | api | `E34-K01`, `E29` |
| `E35-D01` | UX research: how a trader decides to trust an automated rule with real orders | Task | 3 | web |  |
| `E35-K01` | Fix IR canonicalisation and round-trip fuzz strategy before schema freeze | Spike | 2 | api |  |
| `E35-S02` | Build the deterministic evaluator with snapshotting, guards and timeouts | Story | 5 | api | `E35-T04` |
| `E35-S03` | Execute rule actions through the OMS under the per-rule safety limits | Story | 5 | api | `E35-S02` |
| `E35-S04` | Enforce rule scope on every action at runtime, not only at save time | Story | 2 | api | `E35-S02` |
| `E35-S06` | Persist the firing log and publish rule state on the rules WS topic | Story | 2 | api | `E35-S03`, `E50-T59`, `E50-S01` |
| `E35-S07` | Detect rule conflicts at arming time and arbitrate deterministically at runtime | Story | 2 | api | `E35-S06` |
| `E35-T01` | Implement the rule IR models, canonical serialisation and content hash | Task | 3 | api | `E35-K01` |
| `E35-T02` | Add the rules, rule_versions, rule_runs and rule_events migration with retention | Task | 2 | api | `E35-T01` |
| `E35-T03` | Build the metric and action vocabulary registry and serve GET /rules/vocabulary | Task | 2 | api | `E35-T01` |
| `E35-T04` | Implement the semantic validator and the compile and validate endpoints | Task | 3 | api | `E35-T01`, `E35-T03` |
| `E36-D01` | UX research: how a trader expresses a stop-management rule in words | Task | 3 | web | `E35` |
| `E36-D02` | Wireframe to hi-fi: SCR-081 form editor and SCR-083 templates gallery | Task | 5 | web | `E36-D01` |
| `E36-D03` | Hi-fi SCR-080, SCR-088, SCR-089 plus rule-editor design-system contributions and motion | Task | 3 | web | `E36-D01` |
| `E37-D02` | Wireframe to hi-fi: SCR-082 node editor, all states and round-trip indicator | Task | 5 | web | `E37-D01` |
| `E37-D03` | Design-system tokens and motion spec for node, port, edge and canvas primitives | Task | 3 | web | `E37-D02` |
| `E37-K01` | Spike: validate the graph library for 200-node fps and keyboard connect | Spike | 2 | web | `E35` |
| `E39-D02` | Hi-fi SCR-071 risk dashboard and SCR-073 lockout notice with CMP-117/CMP-138 specs | Task | 3 | web | `E39-D01` |
| `E39-D03` | Hi-fi SCR-072 kill-switch modal and SCR-134 risk policy, CMP-211 spec and handoff | Task | 3 | web | `E39-D01` |
| `E39-K01` | Spike: authoritative daily-PnL source and day-boundary semantics for the loss cap | Spike | 2 | api | `E29`, `E27` |
| `E39-T01` | Implement the M17 risk evaluator core with rolling per-account counters | Task | 3 | api | `E39-T02`, `E39-K01`, `E39-X01` |
| `E39-T02` | Postgres migrations and internal schemas for risk_lockouts, risk_policy and kill_switch_state | Task | 2 | api | `E27`, `E28` |
| `E39-X01` | STRIDE threat model for risk caps, lockouts and the kill-switch | Task | 3 | api | `E27` |
| `E40-K01` | Spike: alert evaluation placement, subscription sharing and storm thresholds | Spike | 1 | alerts | `E35` |
| `E40-T01` | Land the 0009_alerts migration, repositories and alert outbox topics | Task | 1 | api | `E35-T02` |
| `E42-D03` | Hi-fi: admin shell, re-auth gate, SCR-120 overview, SCR-121/122/123/124 users | Task | 3 | web | `E42-D02` |
| `E42-D04` | Hi-fi: SCR-135/136 audit, SCR-145 flags, SCR-148 maintenance, motion spec | Task | 3 | web | `E42-D02` |
| `E42-K01` | Spike: audit query plan and index strategy at 10 million rows | Spike | 1 | api |  |
| `E42-T02` | Implement audit query, hash-chain verify and signed export endpoints | Task | 5 | api | `E09`, `E42-K01` |
| `E42-X01` | STRIDE threat model for the admin area, with abuse cases | Task | 3 | api | `E42-D02` |

### 16.5 Design-track deliverables due

**Design sprint D-S14** (roadmap 1.2) produces: Journal & analytics, paper-vs-live comparison

> Consumed by engineering sprint **S16** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S16 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E28-D03` | Hi-fi design and design-system contributions for the profile and trade-group surfaces | 3 | 2026-12-31 |
| `E28-D04` | Specify motion and state-transition choreography for profile saves, previews and readiness | 1 | 2026-12-31 |
| `E28-D05` | Accessibility design review of the six profile and trade-group surfaces | 1 | 2026-12-31 |
| `E28-D06` | Produce and sign off the engineering handoff pack for the profiles and trade-groups epic | 1 | 2026-12-31 |
| `E30-D02` | Wireframe to hi-fi SCR-060 order ticket with every state drawn | 5 | 2026-12-31 |
| `E30-D03` | Hi-fi SCR-076, SCR-077, SCR-114 and the account / trade-group selector | 5 | 2026-12-31 |
| `E31-D01` | UX research and hi-fi design for the chart trading layer (SCR-030, SCR-040) | 2 | 2026-12-31 |
| `E32-D02` | Wireframe SCR-064, SCR-065 and SCR-069 with every state enumerated | 3 | 2026-12-31 |
| `E33-D01` | UX research: how traders configure and trust an emulated algorithm | 3 | 2026-12-31 |
| `E35-D01` | UX research: how a trader decides to trust an automated rule with real orders | 3 | 2026-12-31 |
| `E36-D01` | UX research: how a trader expresses a stop-management rule in words | 3 | 2026-12-31 |
| `E36-D02` | Wireframe to hi-fi: SCR-081 form editor and SCR-083 templates gallery | 5 | 2026-12-31 |
| `E36-D03` | Hi-fi SCR-080, SCR-088, SCR-089 plus rule-editor design-system contributions and motion | 3 | 2026-12-31 |
| `E37-D02` | Wireframe to hi-fi: SCR-082 node editor, all states and round-trip indicator | 5 | 2026-12-31 |
| `E37-D03` | Design-system tokens and motion spec for node, port, edge and canvas primitives | 3 | 2026-12-31 |
| `E39-D02` | Hi-fi SCR-071 risk dashboard and SCR-073 lockout notice with CMP-117/CMP-138 specs | 3 | 2026-12-31 |
| `E39-D03` | Hi-fi SCR-072 kill-switch modal and SCR-134 risk policy, CMP-211 spec and handoff | 3 | 2026-12-31 |
| `E42-D03` | Hi-fi: admin shell, re-auth gate, SCR-120 overview, SCR-121/122/123/124 users | 3 | 2026-12-31 |
| `E42-D04` | Hi-fi: SCR-135/136 audit, SCR-145 flags, SCR-148 maintenance, motion spec | 3 | 2026-12-31 |

Design total: **58 pts** across 19 tickets.

### 16.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: Threat-model refresh (OMS) (s05, S14-S19)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Load & soak campaigns (q07, S09-S20)

**QA tickets (6 pts, 2 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E27-Q01` | Write the black-box test plan and fault-injection fixtures for accounts and the key vault | 3 | `E27-T01`, `E27-D02` |
| `E29-Q01` | Write the black-box test plan and Bybit fixtures for the OMS and its blotters | 3 | `E29-D06`, `E29-K01` |

**Security tickets (12 pts, 4 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E27-X01` | Produce the STRIDE threat model for accounts, sub-accounts and the API-key vault | 3 | `E27-K01`, `E09` |
| `E29-X01` | Produce the STRIDE threat model for the OMS and its order-placement path | 3 | `E29-K01`, `E27` |
| `E39-X01` | STRIDE threat model for risk caps, lockouts and the kill-switch | 3 | `E27` |
| `E42-X01` | STRIDE threat model for the admin area, with abuse cases | 3 | `E42-D02` |

### 16.7 Risks & dependency watch-list

- **E27 and E29 are the roots of all of R3.** Both start day 1; neither has slack.
- Design load is 58 pts vs 34 eng - R3's UI is being designed two sprints ahead, as required. If design slips here, S16-S17 FE work is blocked by DoR.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S14 |
|---|---|---|
| `E27` | epic E27 (whole epic must be Done) | 8 |
| `E09` | epic E09 (whole epic must be Done) | 4 |
| `E29` | epic E29 (whole epic must be Done) | 4 |
| `E35` | epic E35 (whole epic must be Done) | 3 |
| `E42-D02` | Sprint 13 | 3 |
| `E39-D01` | Sprint 13 | 2 |
| `E27-D02` | Sprint 12 | 1 |
| `E28-D02` | Sprint 13 | 1 |
| `E08` | epic E08 (whole epic must be Done) | 1 |
| `E29-D06` | Sprint 13 | 1 |
| `E30-D01` | Sprint 13 | 1 |
| `E21` | epic E21 (whole epic must be Done) | 1 |
| _... 3 more_ | | |

### 16.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** An API key is added, envelope-encrypted, verified withdrawal-OFF, and an order state machine transitions through a full lifecycle in simulation.

**Exit expectation:** Key vault threat model signed off by the Security engineer.

### 16.9 Burn-up - R3 train

| Sprint | Eng pts this sprint | Cumulative R3 | R3 total | Remaining | % complete |
|---|---|---|---|---|---|
| S14 **<- this sprint** | 88 | 88 | 488 | 400 | 18% |
| S15 | 89 | 177 | 488 | 311 | 36% |
| S16 | 89 | 266 | 488 | 222 | 55% |
| S17 | 89 | 355 | 488 | 133 | 73% |
| S18 | 88 | 443 | 488 | 45 | 91% |
| S19 | 45 | 488 | 488 | 0 | 100% |

---

## 17. S15 - 2027-01-01 -> 2027-01-07 (R3)

### 17.1 Sprint goal(s)

- Key vault completes with envelope encryption and the **withdrawal-permission-OFF check** (E27).
- Risk caps, lockouts and kill-switch (E39) land *before* any order-placing UI, per roadmap 11.3 rule 2.
- Brackets and the native-SL invariant begin (E32); rule IR runtime continues (E35).
- **Design is over pool: 66 pts vs 60 (+6).**
- **Security is over pool: 21 pts vs 20 (+1).**

### 17.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 89 | 90 | +1 | ok |
| Design (D) | 66 | 60 | -6 | **OVER** |
| QA (Q) | 20 | 45 | +25 | ok |
| Security (X) | 21 | 20 | -1 | **OVER** |
| **Total** | **196** | **215** | **+19** | |

### 17.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E27** | Accounts, sub-accounts & API-key vault | Accounts & Security (BE-Sec) | 34 | 13 |
| **E32** | Brackets, scaled orders & native SL invariant | OMS & Execution (BE-OMS) | 30 | 11 |
| **E35** | Rule engine IR, compiler & runtime | Rules & Alerts (BE-Rules) | 28 | 9 |
| **E28** | Per-account profiles & trade groups | OMS & Execution (BE-OMS) | 17 | 7 |
| **E29** | OMS core & order state machine | OMS & Execution (BE-OMS) | 15 | 6 |
| **E42** | Admin screens (users, roles, audit, health, flags) | Accounts & Security (BE-Sec) | 14 | 7 |
| **E39** | Risk caps, lockouts & kill-switch | OMS & Execution (BE-OMS) | 12 | 5 |
| **E30** | Order ticket UI | App & Charting UI (FE-App) | 10 | 4 |
| **E33** | Emulated algos (OCO, iceberg, TWAP, chase) | OMS & Execution (BE-OMS) | 10 | 2 |
| **E37** | Rule node-graph editor (SCR-082) with lossless IR round-trip | App & Charting UI (FE-App) | 8 | 3 |
| **E36** | Rule form editor | App & Charting UI (FE-App) | 7 | 3 |
| **E31** | Chart & DOM trading interactions | App & Charting UI (FE-App) | 3 | 2 |
| **E34** | Trade-group fan-out & rate-limit governor | OMS & Execution (BE-OMS) | 3 | 1 |
| **E38** | Paper trading & demo/live parity | OMS & Execution (BE-OMS) | 2 | 1 |
| **E41** | Journal & analytics | App & Charting UI (FE-App) | 2 | 1 |
| **E40** | Alerts & notifications | Rules & Alerts (BE-Rules) | 1 | 1 |


**Statechart lane:** E29 (`E29-T04`, `E29-T06`, `E29-T08`); E31 (`E31-D02`, `E31-D03`); E32 (`E32-D03`, `E32-D04`, `E32-D05`, `E32-D06`, `E32-D07`, `E32-S01`, `E32-S02`, `E32-S04`, `E32-T01`, `E32-T02`, `E32-X01`); E33 (`E33-D02`, `E33-D03`); E34 (`E34-D01`); E35 (`E35-D02`, `E35-D03`, `E35-D04`, `E35-D05`, `E35-Q01`, `E35-S01`, `E35-S05`, `E35-T05`, `E35-X01`); E39 (`E39-Q01`, `E39-S01`, `E39-S02`, `E39-S03`, `E39-T03`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 17.4 Tickets (76)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E27-Q02` | Automate the accounts and key-vault E2E suite in Playwright against the demo environment | Task | 3 | web | `E27-Q01`, `E27-S02`, `E27-S03`, `E27-S04`, `E27-S05` |
| `E27-Q03` | Run the load, soak and chaos scenarios for account health, key verification and rate limits | Task | 2 | api | `E27-T04`, `E27-Q01` |
| `E27-Q04` | Audit accessibility and run an exploratory charter across the six accounts and key-vault screens | Task | 3 | web | `E27-S01`, `E27-S02`, `E27-S03`, `E27-S04`, `E27-S05`, `E27-D05` |
| `E27-Q05` | Assemble the E27 regression pack and record QA sign-off for the epic | Task | 2 | api | `E27-Q02`, `E27-Q03`, `E27-Q04`, `E27-T05` |
| `E27-S01` | Register Bybit main and sub-accounts and browse them on the admin accounts list | Story | 5 | web | `E27-T01`, `E27-T04`, `E27-D06` |
| `E27-S02` | Add and edit a Bybit account's API key with write-only fields and a mandatory connection test | Story | 3 | web | `E27-T03`, `E27-S01`, `E27-D06` |
| `E27-S03` | Rotate an API key with an overlap window and surface key-age policy in the health panel | Story | 3 | web | `E27-T03`, `E27-T04`, `E27-S02`, `E27-D06` |
| `E27-S04` | Revoke a key immediately and disable or delete an account with consequences stated up front | Story | 2 | web | `E27-T02`, `E27-S01`, `E27-D06` |
| `E27-S05` | Show per-account balance, margin and connection state and control leverage and margin mode | Story | 2 | web | `E27-T04`, `E27-S01`, `E27-D06` |
| `E27-T05` | Write the accounts and key-vault operator runbook and amend ADR-0009 | Task | 2 | docs | `E27-T02`, `E27-T03`, `E27-S03`, `E27-S04` |
| `E27-X02` | Security-review the credential broker, verification pipeline and key lifecycle implementation | Task | 3 | api | `E27-X01`, `E27-T02`, `E27-T03`, `E27-S02`, `E27-S03`, `E27-S04` |
| `E27-X03` | Implement the RBAC and account-scope assertion matrix for every accounts and key route and topic | Task | 2 | api | `E27-X01`, `E27-T03`, `E27-S01` |
| `E27-X04` | Run the key-compromise, restore and rotation drills and record the epic security sign-off | Task | 2 | infra | `E27-X02`, `E27-X03`, `E27-T05`, `E27-Q03` |
| `E28-Q01` | Write the black-box test plan and fixture set for profiles, sizing and trade groups | Task | 2 | api | `E28-T01` |
| `E28-T01` | Land account_profiles, trade_groups and trade_group_legs migrations and domain models | Task | 2 | api | `E27`, `E28-X01` |
| `E28-T02` | Implement profile CRUD routes with exchange-limit validation and audited step-up saves | Task | 2 | api | `E28-T01`, `E27` |
| `E28-T03` | Build the server-side leg sizer: sizing rules, stop resolution and lot/notional rounding | Task | 5 | api | `E28-T01`, `E28-T02` |
| `E28-T04` | Enforce allowed symbols and risk caps inside the order path with audited refusals | Task | 2 | api | `E28-T03`, `E29` |
| `E28-T05` | Implement trade-group definition, preview endpoint and the trade_groups WS projection | Task | 2 | api | `E28-T03`, `E28-T02` |
| `E28-X01` | Produce the STRIDE threat model for per-account profiles and trade groups | Task | 2 | api | `E27-X01` |
| `E29-S01` | Build the SCR-063 positions tab with cross-account rows, grouping and liq-proximity warnings | Story | 3 | web | `E29-T07`, `E29-D06`, `E29-T05` |
| `E29-S02` | Build the SCR-063 working-orders tab with inline amend, cancel and conditional-order sections | Story | 3 | web | `E29-S01`, `E29-T07` |
| `E29-T04` | Implement the submission pipeline: validate, size-round, persist, send, ack | Task | 3 | api | `E29-K01`, `E29-T02`, `E29-T03`, `E50-S01`, `E50-T59` |
| `E29-T06` | Implement the reconciliation loop against order/realtime, position/list and execution/list | Task | 3 | api | `E29-T04`, `E29-T05`, `E50-S01`, `E50-T59` |
| `E29-T07` | Expose the OMS REST surface and order diagnostics | Task | 2 | api | `E29-T04`, `E29-T05` |
| `E29-T08` | Stuck-order and unknown-order detection with the OMS metric and alert set | Task | 1 | api | `E29-T06`, `E50-S01`, `E50-T59`, `E50-T60` |
| `E30-D04` | Design-system contributions and motion spec for the trading ticket components | Task | 3 | web | `E30-D03` |
| `E30-D05` | Accessibility design review of ticket, confirmation and defaults | Task | 2 | web | `E30-D03`, `E30-D04` |
| `E30-D06` | Assemble and sign off the engineering handoff pack for the order ticket | Task | 2 | web | `E30-D04`, `E30-D05` |
| `E30-X01` | Produce the STRIDE threat model for the order ticket surface | Task | 3 | web | `E30-D03`, `E29` |
| `E31-D02` | Hi-fi DOM trading, design-system, motion spec and a11y review | Task | 2 | web | `E31-D01` |
| `E31-D03` | Design handoff package for chart and DOM trading | Task | 1 | web | `E31-D02` |
| `E32-D03` | Design hi-fi SCR-069 bracket builder and the CMP-119 BracketEditor spec | Task | 3 | web | `E32-D02` |
| `E32-D04` | Design hi-fi SCR-065 scaled/DCA ladder builder with its preview table | Task | 3 | web | `E32-D02` |
| `E32-D05` | Design hi-fi SCR-064 position SL/TP editor and the CMP-120 TrailingStopEditor | Task | 3 | web | `E32-D02` |
| `E32-D06` | Contribute CMP-158, the native-SL affordance pattern and motion to the DS | Task | 2 | web | `E32-D03`, `E32-D04`, `E32-D05` |
| `E32-D07` | Run the a11y design review and publish the E32 engineering handoff pack | Task | 3 | web | `E32-D03`, `E32-D04`, `E32-D05`, `E32-D06` |
| `E32-S01` | Make a bracket a first-class object with partial-fill-aware child sizing | Story | 3 | api | `E29`, `E32-T01`, `E50-S01`, `E50-S02`, `E50-T49`, `E50-T59` |
| `E32-S02` | Ship partial take-profit ladders that resize the stop as legs fill | Story | 3 | api | `E32-S01` |
| `E32-S04` | Translate percentage and ATR trailing stops into Bybit price distances | Story | 3 | api | `E32-T01`, `E29` |
| `E32-T01` | Enforce the native-SL invariant at the single OMS submission choke point | Task | 3 | api | `E28`, `E29`, `E32-K01`, `E32-X01`, `E39`, `E50-S02`, `E50-T59` |
| `E32-T02` | Build the unprotected-position watchdog with fallback attach and alert | Task | 1 | api | `E32-T01`, `E50-S02`, `E50-T59`, `E50-T60` |
| `E32-X01` | Produce the STRIDE threat model for brackets, ladders and the SL invariant | Task | 3 | api | `E29` |
| `E33-D02` | Wireframe to hi-fi: TWAP, iceberg and chase builders (SCR-066, 067, 068) | Task | 5 | web | `E33-D01` |
| `E33-D03` | Hi-fi: OCO builder (SCR-069) and algo monitor panel (SCR-070) | Task | 5 | web | `E33-D01` |
| `E34-D01` | UX research: how an owner reasons about a multi-account fan-out and its partial failure | Task | 3 | web | `E28` |
| `E35-D02` | Wireframe to hi-fi: rule simulation panel SCR-084 and arming dialog SCR-085 | Task | 5 | web | `E35-D01` |
| `E35-D03` | Hi-fi for conflict resolver, fire history, IR inspector and import/export | Task | 5 | web | `E35-D01` |
| `E35-D04` | Accessibility design review of the six rule-engine screens | Task | 2 | web | `E35-D02`, `E35-D03` |
| `E35-D05` | Design handoff package and design-system entries for the rule-engine screens | Task | 2 | web | `E35-D04` |
| `E35-Q01` | Write the black-box test plan and exploratory charters for the rule engine | Task | 3 | api | `E35-T04` |
| `E35-S01` | Store, version and mode-switch rules through the rules API | Story | 2 | api | `E35-T02`, `E35-T04`, `E50-T59`, `E50-S01` |
| `E35-S05` | Run rules in simulate mode and auto-backtest them on save | Story | 5 | api | `E35-S03` |
| `E35-T05` | Add IR version upcasters and the built-in system rules | Task | 1 | api | `E35-T01`, `E35-S03` |
| `E35-X01` | STRIDE threat model for the rule engine IR, compiler and runtime | Task | 3 | api | `E35-T04` |
| `E36-D04` | Accessibility design review of the form editor as the mandated non-canvas alternative | Task | 2 | web | `E36-D02`, `E36-D03` |
| `E36-D05` | Assemble and sign off the rule-form-editor engineering handoff pack | Task | 2 | web | `E36-D04` |
| `E36-X01` | Produce the STRIDE threat model for the rule authoring surface | Task | 3 | web | `E35`, `E36-D02` |
| `E37-D04` | Accessibility design review of the node editor keyboard authoring strategy | Task | 2 | web | `E37-D02`, `E37-D03` |
| `E37-D05` | Design handoff package for SCR-082 and the node-graph component set | Task | 3 | web | `E37-D03`, `E37-D04` |
| `E37-T01` | Build packages/rule-graph: graph<->IR adapter, typed ports, analysis | Task | 3 | web | `E35`, `E37-K01` |
| `E38-K01` | Spike: enumerate real Bybit demo-vs-live behavioural differences | Spike | 2 | api | `E27`, `E29` |
| `E39-Q01` | Black-box test plan, risk fixtures and regression pack for caps and lockouts | Task | 3 | api | `E39-S01`, `E39-S02` |
| `E39-S01` | Enforce per-account risk caps server-side inside the order path | Story | 3 | api | `E39-T01`, `E29` |
| `E39-S02` | Automatic lockout on cap breach with day-boundary reset and step-up override | Story | 2 | api | `E39-S01`, `E39-T01`, `E50-T59`, `E50-S02`, `E50-T49` |
| `E39-S03` | Kill-switch engine: global and scoped freeze over REST with WS propagation | Story | 3 | api | `E39-T01`, `E39-T02`, `E29`, `E50-T59`, `E50-S02`, `E50-T49` |
| `E39-T03` | ADR-0016 risk enforcement model plus the flatten-all runbook and doc updates | Task | 1 | docs | `E39-S02`, `E39-S03` |
| `E40-D01` | Research alert attention behaviour and run the a11y design review | Task | 1 | web |  |
| `E41-K01` | Spike: choose the analytics query tier (Postgres vs DuckDB/Parquet) | Spike | 2 | api | `E07` |
| `E42-D05` | Hi-fi: SCR-143/144 health and incidents, SCR-146 backups, onboarding wizard | Task | 3 | web | `E42-D02`, `E04-D01` |
| `E42-D06` | Accessibility design review and engineering handoff pack for the admin area | Task | 2 | web | `E42-D03`, `E42-D04`, `E42-D05` |
| `E42-Q01` | Write the black-box test plan and fixture set for the admin area | Task | 2 | web | `E42-D02` |
| `E42-T01` | Implement GET /admin/overview and /admin/capacity read models | Task | 2 | api | `E09`, `E04-T04`, `E27-T01`, `E16-T07` |
| `E42-T03` | Implement the feature-flag service, control allowlist and system push | Task | 1 | api | `E09`, `E42-T01` |
| `E42-T04` | Implement user lifecycle: disable cascade, anonymised delete, revocation | Task | 3 | api | `E09`, `E27-S04` |
| `E42-T05` | Wire the admin health, incidents and backups read models to the admin API | Task | 1 | api | `E04-T04`, `E42-T01` |

### 17.5 Design-track deliverables due

**Design sprint D-S15** (roadmap 1.2) produces: Admin screens: users/roles, audit log, health, feature flags, kill-switch

> Consumed by engineering sprint **S17** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S17 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E30-D04` | Design-system contributions and motion spec for the trading ticket components | 3 | 2027-01-07 |
| `E30-D05` | Accessibility design review of ticket, confirmation and defaults | 2 | 2027-01-07 |
| `E30-D06` | Assemble and sign off the engineering handoff pack for the order ticket | 2 | 2027-01-07 |
| `E31-D02` | Hi-fi DOM trading, design-system, motion spec and a11y review | 2 | 2027-01-07 |
| `E31-D03` | Design handoff package for chart and DOM trading | 1 | 2027-01-07 |
| `E32-D03` | Design hi-fi SCR-069 bracket builder and the CMP-119 BracketEditor spec | 3 | 2027-01-07 |
| `E32-D04` | Design hi-fi SCR-065 scaled/DCA ladder builder with its preview table | 3 | 2027-01-07 |
| `E32-D05` | Design hi-fi SCR-064 position SL/TP editor and the CMP-120 TrailingStopEditor | 3 | 2027-01-07 |
| `E32-D06` | Contribute CMP-158, the native-SL affordance pattern and motion to the DS | 2 | 2027-01-07 |
| `E32-D07` | Run the a11y design review and publish the E32 engineering handoff pack | 3 | 2027-01-07 |
| `E33-D02` | Wireframe to hi-fi: TWAP, iceberg and chase builders (SCR-066, 067, 068) | 5 | 2027-01-07 |
| `E33-D03` | Hi-fi: OCO builder (SCR-069) and algo monitor panel (SCR-070) | 5 | 2027-01-07 |
| `E34-D01` | UX research: how an owner reasons about a multi-account fan-out and its partial failure | 3 | 2027-01-07 |
| `E35-D02` | Wireframe to hi-fi: rule simulation panel SCR-084 and arming dialog SCR-085 | 5 | 2027-01-07 |
| `E35-D03` | Hi-fi for conflict resolver, fire history, IR inspector and import/export | 5 | 2027-01-07 |
| `E35-D04` | Accessibility design review of the six rule-engine screens | 2 | 2027-01-07 |
| `E35-D05` | Design handoff package and design-system entries for the rule-engine screens | 2 | 2027-01-07 |
| `E36-D04` | Accessibility design review of the form editor as the mandated non-canvas alternative | 2 | 2027-01-07 |
| `E36-D05` | Assemble and sign off the rule-form-editor engineering handoff pack | 2 | 2027-01-07 |
| `E37-D04` | Accessibility design review of the node editor keyboard authoring strategy | 2 | 2027-01-07 |
| `E37-D05` | Design handoff package for SCR-082 and the node-graph component set | 3 | 2027-01-07 |
| `E40-D01` | Research alert attention behaviour and run the a11y design review | 1 | 2027-01-07 |
| `E42-D05` | Hi-fi: SCR-143/144 health and incidents, SCR-146 backups, onboarding wizard | 3 | 2027-01-07 |
| `E42-D06` | Accessibility design review and engineering handoff pack for the admin area | 2 | 2027-01-07 |

Design total: **66 pts** across 24 tickets.

### 17.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: Threat-model refresh (OMS) (s05, S14-S19)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Safety-invariant suite (q06, S15-S18)
- qa: Load & soak campaigns (q07, S09-S20)

**QA tickets (20 pts, 8 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E27-Q02` | Automate the accounts and key-vault E2E suite in Playwright against the demo environment | 3 | `E27-Q01`, `E27-S02`, `E27-S03`, `E27-S04`, `E27-S05` |
| `E27-Q03` | Run the load, soak and chaos scenarios for account health, key verification and rate limits | 2 | `E27-T04`, `E27-Q01` |
| `E27-Q04` | Audit accessibility and run an exploratory charter across the six accounts and key-vault screens | 3 | `E27-S01`, `E27-S02`, `E27-S03`, `E27-S04`, `E27-S05`, `E27-D05` |
| `E27-Q05` | Assemble the E27 regression pack and record QA sign-off for the epic | 2 | `E27-Q02`, `E27-Q03`, `E27-Q04`, `E27-T05` |
| `E28-Q01` | Write the black-box test plan and fixture set for profiles, sizing and trade groups | 2 | `E28-T01` |
| `E35-Q01` | Write the black-box test plan and exploratory charters for the rule engine | 3 | `E35-T04` |
| `E39-Q01` | Black-box test plan, risk fixtures and regression pack for caps and lockouts | 3 | `E39-S01`, `E39-S02` |
| `E42-Q01` | Write the black-box test plan and fixture set for the admin area | 2 | `E42-D02` |

**Security tickets (21 pts, 8 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E27-X02` | Security-review the credential broker, verification pipeline and key lifecycle implementation | 3 | `E27-X01`, `E27-T02`, `E27-T03`, `E27-S02`, `E27-S03`, `E27-S04` |
| `E27-X03` | Implement the RBAC and account-scope assertion matrix for every accounts and key route and topic | 2 | `E27-X01`, `E27-T03`, `E27-S01` |
| `E27-X04` | Run the key-compromise, restore and rotation drills and record the epic security sign-off | 2 | `E27-X02`, `E27-X03`, `E27-T05`, `E27-Q03` |
| `E28-X01` | Produce the STRIDE threat model for per-account profiles and trade groups | 2 | `E27-X01` |
| `E30-X01` | Produce the STRIDE threat model for the order ticket surface | 3 | `E30-D03`, `E29` |
| `E32-X01` | Produce the STRIDE threat model for brackets, ladders and the SL invariant | 3 | `E29` |
| `E35-X01` | STRIDE threat model for the rule engine IR, compiler and runtime | 3 | `E35-T04` |
| `E36-X01` | Produce the STRIDE threat model for the rule authoring surface | 3 | `E35`, `E36-D02` |

### 17.7 Risks & dependency watch-list

- **Safety ordering is non-negotiable**: E39 risk caps + kill-switch and E27 key vault must be Done before any order-placing UI enters a sprint (roadmap 11.3 rule 2).
- Security load spikes to 21 pts; design to 66 pts (the highest of the plan). Both are above their pool's steady state.
- Safety-invariant QA suite (q06) opens and runs to S18 - it is the evidence base for the Live gate.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S15 |
|---|---|---|
| `E29` | epic E29 (whole epic must be Done) | 8 |
| `E27-D06` | Sprint 13 | 5 |
| `E27-T03` | Sprint 14 | 5 |
| `E27-T04` | Sprint 14 | 4 |
| `E27-T02` | Sprint 14 | 3 |
| `E27-X01` | Sprint 14 | 3 |
| `E27` | epic E27 (whole epic must be Done) | 3 |
| `E29-T05` | Sprint 14 | 3 |
| `E29-T04` | Sprint 14 | 3 |
| `E30-D03` | Sprint 14 | 3 |
| `E32-D02` | Sprint 14 | 3 |
| `E35-T04` | Sprint 14 | 3 |
| _... 29 more_ | | |

### 17.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Kill-switch halts all order flow in <1s; a risk cap blocks an over-sized order; the rule IR compiles and runs a simple rule.

**Exit expectation:** Safety prerequisites (E27, E39) Done - unblocks order-placing UI for S16.

### 17.9 Burn-up - R3 train

| Sprint | Eng pts this sprint | Cumulative R3 | R3 total | Remaining | % complete |
|---|---|---|---|---|---|
| S14 | 88 | 88 | 488 | 400 | 18% |
| S15 **<- this sprint** | 89 | 177 | 488 | 311 | 36% |
| S16 | 89 | 266 | 488 | 222 | 55% |
| S17 | 89 | 355 | 488 | 133 | 73% |
| S18 | 88 | 443 | 488 | 45 | 91% |
| S19 | 45 | 488 | 488 | 0 | 100% |

---

## 18. S16 - 2027-01-08 -> 2027-01-14 (R3)

### 18.1 Sprint goal(s)

- Brackets + native SL invariant (E32, 21 pts this sprint) and risk caps (E39, 20 pts this sprint) advance - the safety floor for all trading UI.
- Per-account profiles and trade groups (E28) and admin screens (E42) reach the halfway mark.
- Order ticket and chart/DOM trading UI can now legally start (their safety prerequisites are Done).

### 18.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 89 | 90 | +1 | ok |
| Design (D) | 35 | 60 | +25 | ok |
| QA (Q) | 32 | 45 | +13 | ok |
| Security (X) | 13 | 20 | +7 | ok |
| **Total** | **169** | **215** | **+46** | |

### 18.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E28** | Per-account profiles & trade groups | OMS & Execution (BE-OMS) | 21 | 9 |
| **E33** | Emulated algos (OCO, iceberg, TWAP, chase) | OMS & Execution (BE-OMS) | 20 | 8 |
| **E39** | Risk caps, lockouts & kill-switch | OMS & Execution (BE-OMS) | 20 | 5 |
| **E41** | Journal & analytics | App & Charting UI (FE-App) | 17 | 5 |
| **E34** | Trade-group fan-out & rate-limit governor | OMS & Execution (BE-OMS) | 16 | 5 |
| **E38** | Paper trading & demo/live parity | OMS & Execution (BE-OMS) | 16 | 6 |
| **E29** | OMS core & order state machine | OMS & Execution (BE-OMS) | 15 | 6 |
| **E42** | Admin screens (users, roles, audit, health, flags) | Accounts & Security (BE-Sec) | 12 | 5 |
| **E32** | Brackets, scaled orders & native SL invariant | OMS & Execution (BE-OMS) | 10 | 3 |
| **E30** | Order ticket UI | App & Charting UI (FE-App) | 8 | 2 |
| **E40** | Alerts & notifications | Rules & Alerts (BE-Rules) | 8 | 4 |
| **E35** | Rule engine IR, compiler & runtime | Rules & Alerts (BE-Rules) | 5 | 1 |
| **E27** | Accounts, sub-accounts & API-key vault | Accounts & Security (BE-Sec) | 1 | 1 |


**Statechart lane:** E32 (`E32-Q01`, `E32-Q02`, `E32-T03`); E33 (`E33-D04`, `E33-D05`, `E33-D06`, `E33-K01`, `E33-S01`, `E33-T01`, `E33-T02`, `E33-X01`); E34 (`E34-D02`, `E34-D03`, `E34-D04`, `E34-S01`, `E34-T01`); E35 (`E35-Q02`); E39 (`E39-D04`, `E39-Q02`, `E39-Q03`, `E39-S04`, `E39-S05`); E40 (`E40-T03`); E42 (`E42-T07`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 18.4 Tickets (60)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E27-D07` | Design QA the implemented accounts and key-vault screens against the handoff pack | Task | 1 | web | `E27-S01`, `E27-S02`, `E27-S03`, `E27-S04`, `E27-S05`, `E27-D06` |
| `E28-K01` | Spike: per-trade override semantics and profile-change propagation to open tickets | Spike | 1 | api | `E28-T01` |
| `E28-Q02` | Automate the profiles, symbol-permission and trade-group E2E suite in Playwright | Task | 3 | web | `E28-Q01`, `E28-S01`, `E28-S03` |
| `E28-Q03` | Run the performance, load and chaos scenarios for sizing, the risk guard and group preview | Task | 2 | api | `E28-T04`, `E28-T05` |
| `E28-S01` | Create and edit a per-account profile from the admin profiles list and editor | Story | 3 | web | `E28-T02`, `E28-D06` |
| `E28-S02` | Apply profile templates and manage the account-by-symbol permissions matrix | Story | 2 | web | `E28-S01`, `E28-D06` |
| `E28-S03` | Define and manage trade groups with readiness, environment and symbol-intersection guards | Story | 3 | web | `E28-T05`, `E28-D06` |
| `E28-S04` | Show the per-account fan-out preview with per-leg sizing, exclusions and aggregate totals | Story | 3 | web | `E28-T05`, `E28-S03`, `E28-D06` |
| `E28-X02` | Security-review the sizing, risk-guard and override implementation against its threat model | Task | 2 | api | `E28-X01`, `E28-T04`, `E28-T05` |
| `E28-X03` | Automate the abuse-case and RBAC assertion suite for every profile and trade-group route | Task | 2 | api | `E28-X01`, `E28-T02`, `E28-T05` |
| `E29-Q03` | Build the k6 load scripts proving budget #4 and the blotter frame budget | Task | 3 | infra | `E29-K01`, `E29-T07`, `E29-S01` |
| `E29-S03` | Implement partial close with reduce-only sizing and protective-order quantity adjustment | Story | 3 | api | `E29-S01`, `E29-T04`, `E29-T07` |
| `E29-S04` | Build the fills tab and the SCR-078 executions detail drawer | Story | 2 | web | `E29-S01`, `E29-T05`, `E29-D06` |
| `E29-S05` | Render execution marks on the chart from the execution stream with clustering | Story | 2 | web | `E29-S04`, `E11`, `E12` |
| `E29-S06` | Ship closed positions and today's realised PnL with the configured day boundary | Story | 2 | web | `E29-S04`, `E29-T07` |
| `E29-X02` | Implement the abuse-case suite, RBAC scope assertions and SAST rules for the OMS | Task | 3 | api | `E29-X01`, `E29-T07`, `E29-S02` |
| `E30-Q01` | Write the black-box test plan and fixtures for the order ticket | Task | 3 | web | `E30-D06`, `E29` |
| `E30-T01` | Build packages/order-ticket-core: draft, validation, sizing, submit | Task | 5 | web | `E30-K01`, `E29`, `E28` |
| `E32-Q01` | Build the zero-escape native-SL invariant suite as a required merge check | Task | 5 | api | `E32-T01` |
| `E32-Q02` | Write the black-box test plan for brackets, TP ladders and trailing stops | Task | 3 | api | `E32-Q01` |
| `E32-T03` | Implement break-even automation as an only-tighten system behaviour | Task | 2 | api | `E32-S04`, `E32-S01` |
| `E33-D04` | Design-system contribution and motion spec for emulated-algo surfaces | Task | 3 | web | `E33-D02`, `E33-D03` |
| `E33-D05` | Accessibility design review of the algo builders and monitor panel | Task | 2 | web | `E33-D02`, `E33-D03` |
| `E33-D06` | Design handoff package for the emulated-algo builders and monitor | Task | 2 | web | `E33-D04`, `E33-D05` |
| `E33-K01` | Prove the emulated-algo scheduler, crash-resume seam and orphan adoption | Spike | 2 | api | `E29` |
| `E33-S01` | Emulate OCO: race two legs and settle the loser safely | Story | 3 | api | `E33-T01`, `E50-S01`, `E50-T49`, `E50-T59` |
| `E33-T01` | Build the AlgoSupervisor framework: state store, scheduler, resume, adoption | Task | 3 | api | `E32`, `E33-K01`, `E33-X01`, `E39`, `E50-S01`, `E50-T49`, `E50-T59` |
| `E33-T02` | Expose algo control API, WS projection, feature flags and audit events | Task | 2 | api | `E33-T01`, `E50-T59`, `E50-T60` |
| `E33-X01` | STRIDE threat model for the emulated-algo supervisor | Task | 3 | api | `E33-D01` |
| `E34-D02` | Wireframe to hi-fi: trade-group ticket SCR-061 including every failure state | Task | 5 | web | `E34-D01` |
| `E34-D03` | Hi-fi for the trade-group manager SCR-062 plus design-system and motion specs | Task | 3 | web | `E34-D01` |
| `E34-D04` | Accessibility design review of the fan-out ticket and trade-group manager | Task | 2 | web | `E34-D02`, `E34-D03` |
| `E34-S01` | Dry-run a fan-out and return resolved per-account sizing, risk and rejections | Story | 3 | api | `E34-T01`, `E28`, `E32` |
| `E34-T01` | Trade-group persistence, lifecycle derivation and the trade_groups WS topic | Task | 3 | api | `E28`, `E29`, `E50-T59`, `E50-S01` |
| `E35-Q02` | Build the round-trip property suite and the 30-rule corpus gate | Task | 5 | api | `E35-Q01`, `E35-T04` |
| `E38-D01` | UX research: how traders tell demo from live and trust simulated fills | Task | 2 | web | `E30`, `E29` |
| `E38-D02` | Hi-fi design: environment switcher SCR-074 and demo/live chrome SCR-075 | Task | 5 | web | `E38-D01` |
| `E38-S01` | Trade Bybit demo through the same code paths as live | Story | 2 | api | `E38-T01`, `E29`, `E27` |
| `E38-S02` | Switch session environment safely with step-up and full resubscription | Story | 2 | api | `E38-T02`, `E09` |
| `E38-T01` | Environment capability matrix and demo host routing in the exchange adapter | Task | 2 | api | `E38-K01`, `E29`, `E27` |
| `E38-T02` | Server-side environment isolation middleware with 403 and high-severity audit | Task | 3 | api | `E38-T01`, `E29`, `E09` |
| `E39-D04` | Design QA of the built risk, lockout and kill-switch surfaces | Task | 2 | web | `E39-S04`, `E39-S05` |
| `E39-Q02` | E2E suite proving no order path escapes the kill-switch or a lockout | Task | 5 | web | `E39-S04`, `E39-S05` |
| `E39-Q03` | Performance and chaos scenarios for risk evaluation and kill-switch propagation | Task | 3 | infra | `E39-S03` |
| `E39-S04` | Build the risk dashboard SCR-071 and the lockout notice SCR-073 | Story | 5 | web | `E39-D02`, `E39-S01`, `E39-S02` |
| `E39-S05` | Build the kill-switch modal SCR-072, panic cluster, global hotkey and risk policy SCR-134 | Story | 5 | web | `E39-D03`, `E39-S03` |
| `E40-D02` | Design all five alert surfaces and ship the engineering handoff pack | Task | 2 | web | `E40-D01` |
| `E40-T02` | Implement the notify-only alert compiler and the alert CRUD API | Task | 2 | api | `E35-T04`, `E40-K01`, `E40-T01` |
| `E40-T03` | Build the server-side alert evaluator with gating and storm suppression | Task | 2 | alerts | `E40-K01`, `E40-T02`, `E50-T59`, `E50-S02`, `E50-T49` |
| `E40-T04` | Build the delivery dispatcher, deliveries API and the alerts WS topic | Task | 2 | api | `E40-T03` |
| `E41-D01` | UX research + wireframes for the journal surfaces (SCR-093..096) | Task | 3 | web | `E05` |
| `E41-D02` | Hi-fi SCR-093 journal list and SCR-096 tag manager | Task | 3 | web | `E41-D01` |
| `E41-T01` | Create M20 journal module, migrations and the read API | Task | 3 | api | `E09`, `E29` |
| `E41-T02` | Build the trade materialiser with MAE/MFE and closed-pnl reconciliation | Task | 5 | api | `E41-T01`, `E29`, `E34` |
| `E41-T03` | Implement the analytics aggregation service and GET /journal/analytics | Task | 3 | api | `E41-T02`, `E41-K01` |
| `E42-S01` | Build the admin shell, re-auth gate and SCR-120 admin overview | Story | 2 | web | `E42-D03`, `E42-T01`, `E09` |
| `E42-S02` | Build SCR-121 users list and SCR-123 invite user with lifecycle actions | Story | 2 | web | `E42-S01`, `E42-D03`, `E42-T04` |
| `E42-S05` | Build SCR-145 feature-flag console and SCR-148 maintenance mode | Story | 2 | web | `E42-S01`, `E42-D04`, `E42-T03` |
| `E42-T07` | Statechart inspector read API: machines, config, chain_trips, dropped_receipts, deferred depth, Stately export | Task | 3 | api | `E50-T60`, `E50-T01`, `E42-T01` |
| `E42-X03` | Automate admin abuse cases, RBAC assertions and SAST/DAST rules | Task | 3 | api | `E42-X01`, `E42-T04` |

### 18.5 Design-track deliverables due

**Design sprint D-S16** (roadmap 1.2) produces: Live-mode visual language, danger states, confirmation patterns

> Consumed by engineering sprint **S18** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S18 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E27-D07` | Design QA the implemented accounts and key-vault screens against the handoff pack | 1 | 2027-01-14 |
| `E33-D04` | Design-system contribution and motion spec for emulated-algo surfaces | 3 | 2027-01-14 |
| `E33-D05` | Accessibility design review of the algo builders and monitor panel | 2 | 2027-01-14 |
| `E33-D06` | Design handoff package for the emulated-algo builders and monitor | 2 | 2027-01-14 |
| `E34-D02` | Wireframe to hi-fi: trade-group ticket SCR-061 including every failure state | 5 | 2027-01-14 |
| `E34-D03` | Hi-fi for the trade-group manager SCR-062 plus design-system and motion specs | 3 | 2027-01-14 |
| `E34-D04` | Accessibility design review of the fan-out ticket and trade-group manager | 2 | 2027-01-14 |
| `E38-D01` | UX research: how traders tell demo from live and trust simulated fills | 2 | 2027-01-14 |
| `E38-D02` | Hi-fi design: environment switcher SCR-074 and demo/live chrome SCR-075 | 5 | 2027-01-14 |
| `E39-D04` | Design QA of the built risk, lockout and kill-switch surfaces | 2 | 2027-01-14 |
| `E40-D02` | Design all five alert surfaces and ship the engineering handoff pack | 2 | 2027-01-14 |
| `E41-D01` | UX research + wireframes for the journal surfaces (SCR-093..096) | 3 | 2027-01-14 |
| `E41-D02` | Hi-fi SCR-093 journal list and SCR-096 tag manager | 3 | 2027-01-14 |

Design total: **35 pts** across 13 tickets.

### 18.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: Threat-model refresh (OMS) (s05, S14-S19)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Safety-invariant suite (q06, S15-S18)
- qa: Load & soak campaigns (q07, S09-S20)

**QA tickets (32 pts, 9 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E28-Q02` | Automate the profiles, symbol-permission and trade-group E2E suite in Playwright | 3 | `E28-Q01`, `E28-S01`, `E28-S03` |
| `E28-Q03` | Run the performance, load and chaos scenarios for sizing, the risk guard and group preview | 2 | `E28-T04`, `E28-T05` |
| `E29-Q03` | Build the k6 load scripts proving budget #4 and the blotter frame budget | 3 | `E29-K01`, `E29-T07`, `E29-S01` |
| `E30-Q01` | Write the black-box test plan and fixtures for the order ticket | 3 | `E30-D06`, `E29` |
| `E32-Q01` | Build the zero-escape native-SL invariant suite as a required merge check | 5 | `E32-T01` |
| `E32-Q02` | Write the black-box test plan for brackets, TP ladders and trailing stops | 3 | `E32-Q01` |
| `E35-Q02` | Build the round-trip property suite and the 30-rule corpus gate | 5 | `E35-Q01`, `E35-T04` |
| `E39-Q02` | E2E suite proving no order path escapes the kill-switch or a lockout | 5 | `E39-S04`, `E39-S05` |
| `E39-Q03` | Performance and chaos scenarios for risk evaluation and kill-switch propagation | 3 | `E39-S03` |

**Security tickets (13 pts, 5 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E28-X02` | Security-review the sizing, risk-guard and override implementation against its threat model | 2 | `E28-X01`, `E28-T04`, `E28-T05` |
| `E28-X03` | Automate the abuse-case and RBAC assertion suite for every profile and trade-group route | 2 | `E28-X01`, `E28-T02`, `E28-T05` |
| `E29-X02` | Implement the abuse-case suite, RBAC scope assertions and SAST rules for the OMS | 3 | `E29-X01`, `E29-T07`, `E29-S02` |
| `E33-X01` | STRIDE threat model for the emulated-algo supervisor | 3 | `E33-D01` |
| `E42-X03` | Automate admin abuse cases, RBAC assertions and SAST/DAST rules | 3 | `E42-X01`, `E42-T04` |

### 18.7 Risks & dependency watch-list

- E32 native-SL invariant is on the **never-cut** list. It cannot be descoped to make the sprint fit.
- Four epics >=17 pts run concurrently (E32, E39, E28, E42) against an 89/90 load - one carry-in breaks the sprint.
- E42 admin screens touch auth/RBAC: the security label is **default-on** for DoD regardless of what was applied at creation.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S16 |
|---|---|---|
| `E29` | epic E29 (whole epic must be Done) | 8 |
| `E28-T05` | Sprint 15 | 5 |
| `E28-D06` | Sprint 14 | 3 |
| `E29-T07` | Sprint 15 | 3 |
| `E32-T01` | Sprint 15 | 3 |
| `E28-T04` | Sprint 15 | 2 |
| `E28-T02` | Sprint 15 | 2 |
| `E28-X01` | Sprint 15 | 2 |
| `E29-S01` | Sprint 15 | 2 |
| `E33-D02` | Sprint 15 | 2 |
| `E33-D03` | Sprint 15 | 2 |
| `E34-D01` | Sprint 15 | 2 |
| _... 44 more_ | | |

### 18.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** A bracket order places with a **native exchange-side SL** attached, on demo; trade-group profile applied; the admin audit log shows every action.

**Exit expectation:** Native-SL invariant proven by an automated safety-invariant test, not a manual demo.

### 18.9 Burn-up - R3 train

| Sprint | Eng pts this sprint | Cumulative R3 | R3 total | Remaining | % complete |
|---|---|---|---|---|---|
| S14 | 88 | 88 | 488 | 400 | 18% |
| S15 | 89 | 177 | 488 | 311 | 36% |
| S16 **<- this sprint** | 89 | 266 | 488 | 222 | 55% |
| S17 | 89 | 355 | 488 | 133 | 73% |
| S18 | 88 | 443 | 488 | 45 | 91% |
| S19 | 45 | 488 | 488 | 0 | 100% |

---

## 19. S17 - 2027-01-15 -> 2027-01-21 (R3)

### 19.1 Sprint goal(s)

- Rule **form editor** completes (E36) - it must merge together with the node editor (roadmap 11.3 rule 5).
- Emulated algos (OCO, iceberg, TWAP, chase) build out (E33).
- Paper trading and demo/live parity work begins (E38).

### 19.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 89 | 90 | +1 | ok |
| Design (D) | 20 | 60 | +40 | ok |
| QA (Q) | 35 | 45 | +10 | ok |
| Security (X) | 16 | 20 | +4 | ok |
| **Total** | **160** | **215** | **+55** | |

### 19.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E36** | Rule form editor | App & Charting UI (FE-App) | 37 | 14 |
| **E37** | Rule node-graph editor (SCR-082) with lossless IR round-trip | App & Charting UI (FE-App) | 26 | 8 |
| **E35** | Rule engine IR, compiler & runtime | Rules & Alerts (BE-Rules) | 16 | 6 |
| **E32** | Brackets, scaled orders & native SL invariant | OMS & Execution (BE-OMS) | 13 | 3 |
| **E38** | Paper trading & demo/live parity | OMS & Execution (BE-OMS) | 12 | 5 |
| **E31** | Chart & DOM trading interactions | App & Charting UI (FE-App) | 11 | 6 |
| **E34** | Trade-group fan-out & rate-limit governor | OMS & Execution (BE-OMS) | 9 | 3 |
| **E30** | Order ticket UI | App & Charting UI (FE-App) | 8 | 3 |
| **E29** | OMS core & order state machine | OMS & Execution (BE-OMS) | 6 | 2 |
| **E39** | Risk caps, lockouts & kill-switch | OMS & Execution (BE-OMS) | 6 | 2 |
| **E41** | Journal & analytics | App & Charting UI (FE-App) | 6 | 3 |
| **E33** | Emulated algos (OCO, iceberg, TWAP, chase) | OMS & Execution (BE-OMS) | 3 | 1 |
| **E42** | Admin screens (users, roles, audit, health, flags) | Accounts & Security (BE-Sec) | 3 | 2 |
| **E50** | xstate-statemachine adoption: factory, persistence, plugins, contract suite, catalogue | Platform & DevSecOps | 3 | 1 |
| **E28** | Per-account profiles & trade groups | OMS & Execution (BE-OMS) | 1 | 1 |


**Statechart lane:** E31 (`E31-S01`, `E31-S02`, `E31-S03`, `E31-S04`, `E31-S05`, `E31-T01`); E32 (`E32-Q05`, `E32-S05`, `E32-S07`); E33 (`E33-Q01`); E34 (`E34-D05`, `E34-Q01`, `E34-X01`); E35 (`E35-Q03`, `E35-Q04`, `E35-S08`, `E35-S09`, `E35-T06`, `E35-X02`); E39 (`E39-Q04`, `E39-X02`); E50 (`E50-T05`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 19.4 Tickets (60)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E28-T06` | Document profile and trade-group semantics and amend ADR-0008 with the shipped model | Task | 1 | docs | `E28-T05`, `E28-T04` |
| `E29-S07` | Ship the reconciliation UX: desync banner, stale-account lockout and the while-you-were-away report | Story | 5 | web | `E29-T06`, `E29-S02`, `E29-D06` |
| `E29-T09` | Reconcile the plan docs and ADR-0006 with the shipped OMS behaviour | Chore | 1 | docs | `E29-T07`, `E29-T08`, `E29-S07` |
| `E30-S01` | Build SCR-060 order ticket with entry types and all order flags | Story | 5 | web | `E30-T01`, `E30-D06`, `E29` |
| `E30-S02` | Add sizing modes and the quantity preset ladder to the ticket | Story | 2 | web | `E30-S01`, `E30-T01`, `E28` |
| `E30-T02` | Build the SCR-077 rejection drawer and the SCR-158 rate-limited ticket state | Task | 1 | web | `E30-S01`, `E29` |
| `E31-S01` | Place an order by clicking a price on the chart | Story | 2 | web | `E31-T01`, `E31-D03` |
| `E31-S02` | Drag order, stop and target lines on the chart to amend | Story | 3 | web | `E31-S01`, `E30`, `E32` |
| `E31-S03` | Cancel orders from the chart and the DOM ladder | Story | 1 | web | `E31-S02`, `E31-S04` |
| `E31-S04` | Click-to-trade on the DOM ladder | Story | 2 | web | `E31-T01`, `E31-D03`, `E21` |
| `E31-S05` | Drag an order marker on the ladder to reprice it | Story | 1 | web | `E31-S04`, `E31-S02` |
| `E31-T01` | Chart/DOM trading intent layer: guards, optimistic state, undo window and audit | Task | 2 | web | `E31-K01`, `E29`, `E39`, `E31-D03` |
| `E32-Q05` | Build the chaos scenarios for crash seams, failover and disconnects in E32 | Task | 5 | api | `E32-T02` |
| `E32-S05` | Build the SCR-069 bracket builder with a non-removable native stop floor | Story | 3 | web | `E32-S01`, `E32-D07`, `E30` |
| `E32-S07` | Build the SCR-064 position SL/TP editor with trailing, break-even and TP ladder | Story | 5 | web | `E32-S02`, `E32-S04`, `E32-T03`, `E32-D07`, `E30` |
| `E33-Q01` | Black-box test plan for the four emulated strategies | Task | 3 | api | `E33-T02` |
| `E34-D05` | Design handoff package for the fan-out ticket and trade-group manager | Task | 3 | web | `E34-D04` |
| `E34-Q01` | Write the black-box test plan for trade-group fan-out | Task | 3 | cross-cutting | `E34-D05`, `E28` |
| `E34-X01` | STRIDE threat model for trade-group fan-out and the rate governor | Task | 3 | api | `E27`, `E28`, `E29` |
| `E35-Q03` | Build the determinism suite and the rule-engine end-to-end tests | Task | 5 | api | `E35-Q01`, `E35-S09` |
| `E35-Q04` | Build the rule-engine performance and load benchmarks | Task | 3 | api | `E35-Q03` |
| `E35-S08` | Build the rule simulation panel and the rule arming dialog | Story | 2 | web | `E35-S05`, `E35-D05` |
| `E35-S09` | Build the fire history, IR inspector, conflict resolver and import/export UI | Story | 2 | web | `E35-S06`, `E35-S07`, `E35-D05` |
| `E35-T06` | Reconcile the plan documents and ADRs with the shipped rule engine | Task | 1 | docs | `E35-S09` |
| `E35-X02` | Abuse-case suite, SAST rules and permission checks for the rule engine | Task | 3 | api | `E35-X01`, `E35-S04` |
| `E36-D06` | Design QA the shipped form editor against the handoff pack | Task | 2 | web | `E36-S02`, `E36-D05` |
| `E36-Q01` | Write the black-box test plan, fixtures and exploratory charters for the form editor | Task | 3 | web | `E36-D05`, `E36-T01` |
| `E36-Q02` | Automate the Playwright E2E suite for rule authoring, templates, list and import/export | Task | 3 | web | `E36-Q01`, `E36-S02` |
| `E36-Q03` | Accessibility audit of the rule form editor and its supporting screens | Task | 3 | web | `E36-Q01`, `E36-S02`, `E36-D04` |
| `E36-Q04` | Build the performance benchmarks for validation, compile round-trip, list and import | Task | 2 | web | `E36-Q01`, `E36-S05` |
| `E36-S01` | Build the condition, action, trigger and scope components of the form editor | Story | 5 | web | `E36-T01` |
| `E36-S02` | Ship SCR-081 rule editor page with validation, save and scoping | Story | 5 | web | `E36-S01` |
| `E36-S03` | Ship the round-trip indicator, graph-only read-only rendering and SCR-088 IR inspector | Story | 3 | web | `E36-S02` |
| `E36-S04` | Ship SCR-083 rule templates gallery with the twelve catalogue templates | Story | 1 | web | `E36-S02` |
| `E36-S05` | Ship SCR-080 rules list with filtering, bulk disarm and live state | Story | 2 | web | `E36-S02` |
| `E36-S06` | Ship SCR-089 rule import and export with scope stripping and per-rule preview | Story | 1 | web | `E36-S03`, `E36-S05` |
| `E36-T01` | Build packages/rule-editor-core: form model, IR adapter, vocabulary cache, diagnostics anchoring | Task | 3 | web | `E35`, `E36-D05` |
| `E36-T02` | Reconcile plan docs, ADR and changelog with the shipped form editor | Chore | 1 | docs | `E36-S06`, `E36-S04` |
| `E36-X02` | Implement the abuse-case suite, scope assertions and SAST rules for rule authoring | Task | 3 | web | `E36-X01`, `E36-S02` |
| `E37-Q01` | Write the black-box test plan for the node-graph editor | Task | 2 | web | `E37-D05` |
| `E37-S01` | Render the node canvas with palette, typed ports and pointer connect | Story | 5 | web | `E37-T01`, `E37-D05` |
| `E37-S02` | Implement the node library and inspector over the rule vocabulary | Story | 5 | web | `E37-S01` |
| `E37-S03` | Surface validation, cycles, orphans and diagnostics on the offending node | Story | 3 | web | `E37-S02`, `E37-T01` |
| `E37-S04` | Implement round-trip switching, the four-state indicator and the mismatch diff | Story | 5 | web | `E37-S03`, `E36` |
| `E37-S05` | Deliver keyboard-equal authoring: node list, connect, announcements | Story | 3 | web | `E37-S02`, `E37-D05` |
| `E37-T03` | Document the node editor and add the ADR-0007 addendum on graph-only constructs | Chore | 1 | docs | `E37-S04` |
| `E37-X01` | STRIDE threat model for the node-graph editor and its compile/save path | Task | 2 | web | `E37-S01` |
| `E38-D03` | Hi-fi design: parity report, paper fidelity panel, reset and eligibility | Task | 3 | web | `E38-D01` |
| `E38-D04` | Hi-fi design: simulated-fill results SCR-099 and simulated-everywhere labelling | Task | 3 | web | `E38-D01` |
| `E38-D05` | Accessibility design review of every E38 surface | Task | 2 | web | `E38-D02`, `E38-D03`, `E38-D04` |
| `E38-D06` | Design handoff package for the E38 surfaces | Task | 2 | web | `E38-D05` |
| `E38-X01` | STRIDE threat model for paper trading and demo/live separation | Task | 2 | cross-cutting | `E38-K01`, `E29`, `E27` |
| `E39-Q04` | Accessibility audit, exploratory charter and epic QA sign-off for E39 | Task | 3 | web | `E39-Q02`, `E39-D04` |
| `E39-X02` | Execute abuse cases, add SAST/DAST rules and complete the E39 security review | Task | 3 | api | `E39-X01`, `E39-S05`, `E39-Q03` |
| `E41-D03` | Hi-fi SCR-094 trade post-mortem and SCR-095 analytics dashboard | Task | 3 | web | `E41-D01` |
| `E41-D04` | Journal a11y design review, motion spec and engineering handoff | Task | 2 | web | `E41-D02`, `E41-D03` |
| `E41-T05` | Author the journal statistics formula reference and ADR-0016 follow-up | Task | 1 | docs | `E41-T03` |
| `E42-S06` | Build SCR-143 system health, SCR-144 incident log and SCR-146 backups/restore | Story | 2 | web | `E42-S01`, `E42-D05`, `E42-T05`, `E04-T04` |
| `E42-T06` | Document admin operations and record ADR-0022 on the admin re-auth model | Task | 1 | docs | `E42-S01`, `E42-S05` |
| `E50-T05` | Event-name coverage gate (MUST-10) | Task | 3 | api | `E50-T15`, `E50-T31` |

### 19.5 Design-track deliverables due

**Design sprint D-S17** (roadmap 1.2) produces: A11y remediation designs, high-contrast + colour-blind themes

> Consumed by engineering sprint **S19** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S19 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E34-D05` | Design handoff package for the fan-out ticket and trade-group manager | 3 | 2027-01-21 |
| `E36-D06` | Design QA the shipped form editor against the handoff pack | 2 | 2027-01-21 |
| `E38-D03` | Hi-fi design: parity report, paper fidelity panel, reset and eligibility | 3 | 2027-01-21 |
| `E38-D04` | Hi-fi design: simulated-fill results SCR-099 and simulated-everywhere labelling | 3 | 2027-01-21 |
| `E38-D05` | Accessibility design review of every E38 surface | 2 | 2027-01-21 |
| `E38-D06` | Design handoff package for the E38 surfaces | 2 | 2027-01-21 |
| `E41-D03` | Hi-fi SCR-094 trade post-mortem and SCR-095 analytics dashboard | 3 | 2027-01-21 |
| `E41-D04` | Journal a11y design review, motion spec and engineering handoff | 2 | 2027-01-21 |

Design total: **20 pts** across 8 tickets.

### 19.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: Threat-model refresh (OMS) (s05, S14-S19)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Safety-invariant suite (q06, S15-S18)
- qa: Load & soak campaigns (q07, S09-S20)

**QA tickets (35 pts, 11 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E32-Q05` | Build the chaos scenarios for crash seams, failover and disconnects in E32 | 5 | `E32-T02` |
| `E33-Q01` | Black-box test plan for the four emulated strategies | 3 | `E33-T02` |
| `E34-Q01` | Write the black-box test plan for trade-group fan-out | 3 | `E34-D05`, `E28` |
| `E35-Q03` | Build the determinism suite and the rule-engine end-to-end tests | 5 | `E35-Q01`, `E35-S09` |
| `E35-Q04` | Build the rule-engine performance and load benchmarks | 3 | `E35-Q03` |
| `E36-Q01` | Write the black-box test plan, fixtures and exploratory charters for the form editor | 3 | `E36-D05`, `E36-T01` |
| `E36-Q02` | Automate the Playwright E2E suite for rule authoring, templates, list and import/export | 3 | `E36-Q01`, `E36-S02` |
| `E36-Q03` | Accessibility audit of the rule form editor and its supporting screens | 3 | `E36-Q01`, `E36-S02`, `E36-D04` |
| `E36-Q04` | Build the performance benchmarks for validation, compile round-trip, list and import | 2 | `E36-Q01`, `E36-S05` |
| `E37-Q01` | Write the black-box test plan for the node-graph editor | 2 | `E37-D05` |
| `E39-Q04` | Accessibility audit, exploratory charter and epic QA sign-off for E39 | 3 | `E39-Q02`, `E39-D04` |

**Security tickets (16 pts, 6 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E34-X01` | STRIDE threat model for trade-group fan-out and the rate governor | 3 | `E27`, `E28`, `E29` |
| `E35-X02` | Abuse-case suite, SAST rules and permission checks for the rule engine | 3 | `E35-X01`, `E35-S04` |
| `E36-X02` | Implement the abuse-case suite, scope assertions and SAST rules for rule authoring | 3 | `E36-X01`, `E36-S02` |
| `E37-X01` | STRIDE threat model for the node-graph editor and its compile/save path | 2 | `E37-S01` |
| `E38-X01` | STRIDE threat model for paper trading and demo/live separation | 2 | `E38-K01`, `E29`, `E27` |
| `E39-X02` | Execute abuse cases, add SAST/DAST rules and complete the E39 security review | 3 | `E39-X01`, `E39-S05`, `E39-Q03` |

### 19.7 Risks & dependency watch-list

- **Roadmap 11.3 rule 5: both rule editors must merge together or not at all.** E36 completes here at 37 pts but E37 does not finish until S18 - the merge is therefore an S18 event; plan the feature flag now.
- 89/90 load with E36, E33, E35 and E37 all active in the rule-engine lane - real contention on `area/rule-engine`.
- E38 paper-trading parity begins; parity gaps discovered late are expensive at the Live gate.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S17 |
|---|---|---|
| `E29` | epic E29 (whole epic must be Done) | 6 |
| `E28` | epic E28 (whole epic must be Done) | 4 |
| `E36-D05` | Sprint 15 | 3 |
| `E37-D05` | Sprint 15 | 3 |
| `E31-D03` | Sprint 15 | 2 |
| `E32-D07` | Sprint 15 | 2 |
| `E30` | epic E30 (whole epic must be Done) | 2 |
| `E27` | epic E27 (whole epic must be Done) | 2 |
| `E35-D05` | Sprint 15 | 2 |
| `E37-T01` | Sprint 16 | 2 |
| `E38-D01` | Sprint 16 | 2 |
| `E09` | epic E09 (whole epic must be Done) | 2 |
| _... 45 more_ | | |

### 19.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** A rule authored in the form editor executes against live demo data and fires an alert; an OCO pair cancels correctly.

**Exit expectation:** Paper/live parity report published with first delta measurements.

### 19.9 Burn-up - R3 train

| Sprint | Eng pts this sprint | Cumulative R3 | R3 total | Remaining | % complete |
|---|---|---|---|---|---|
| S14 | 88 | 88 | 488 | 400 | 18% |
| S15 | 89 | 177 | 488 | 311 | 36% |
| S16 | 89 | 266 | 488 | 222 | 55% |
| S17 **<- this sprint** | 89 | 355 | 488 | 133 | 73% |
| S18 | 88 | 443 | 488 | 45 | 91% |
| S19 | 45 | 488 | 488 | 0 | 100% |

---

## 20. S18 - 2027-01-22 -> 2027-01-28 (R3)

### 20.1 Sprint goal(s)

- Emulated algos complete (E33); rule **node-graph editor** reaches feature parity with the form editor (E37).
- Fan-out and rate-limit governor continue (E34); alerts and journal open (E40, E41).
- R4 hardening work starts overlapping (E43) so the pen-test window is not the first security pass.
- **QA is over pool: 46 pts vs 45 (+1).**

### 20.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 88 | 90 | +2 | ok |
| Design (D) | 15 | 60 | +45 | ok |
| QA (Q) | 46 | 45 | -1 | **OVER** |
| Security (X) | 13 | 20 | +7 | ok |
| **Total** | **162** | **215** | **+53** | |

### 20.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E33** | Emulated algos (OCO, iceberg, TWAP, chase) | OMS & Execution (BE-OMS) | 42 | 14 |
| **E30** | Order ticket UI | App & Charting UI (FE-App) | 19 | 5 |
| **E37** | Rule node-graph editor (SCR-082) with lossless IR round-trip | App & Charting UI (FE-App) | 19 | 8 |
| **E42** | Admin screens (users, roles, audit, health, flags) | Accounts & Security (BE-Sec) | 17 | 4 |
| **E35** | Rule engine IR, compiler & runtime | Rules & Alerts (BE-Rules) | 11 | 4 |
| **E32** | Brackets, scaled orders & native SL invariant | OMS & Execution (BE-OMS) | 9 | 3 |
| **E38** | Paper trading & demo/live parity | OMS & Execution (BE-OMS) | 9 | 3 |
| **E34** | Trade-group fan-out & rate-limit governor | OMS & Execution (BE-OMS) | 8 | 2 |
| **E43** | Security hardening & pen-test remediation | Accounts & Security (BE-Sec) | 8 | 2 |
| **E36** | Rule form editor | App & Charting UI (FE-App) | 5 | 2 |
| **E40** | Alerts & notifications | Rules & Alerts (BE-Rules) | 5 | 3 |
| **E41** | Journal & analytics | App & Charting UI (FE-App) | 5 | 2 |
| **E44** | Live-enablement gating & environment separation | Accounts & Security (BE-Sec) | 3 | 1 |
| **E31** | Chart & DOM trading interactions | App & Charting UI (FE-App) | 2 | 1 |


**Statechart lane:** E31 (`E31-S06`); E32 (`E32-S03`, `E32-S06`, `E32-T04`); E33 (`E33-D07`, `E33-Q02`, `E33-Q03`, `E33-Q04`, `E33-Q05`, `E33-Q06`, `E33-S02`, `E33-S03`, `E33-S04`, `E33-S05`, `E33-S06`, `E33-T03`, `E33-X02`, `E33-X03`); E34 (`E34-S02`, `E34-S03`); E35 (`E35-Q05`, `E35-Q06`, `E35-Q07`, `E35-X03`); E38 (`E38-S03`); E42 (`E42-S08`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 20.4 Tickets (54)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E30-S03` | Ship risk-based sizing and the mandatory native stop-loss field in the ticket | Story | 5 | web | `E30-S02`, `E30-T01`, `E32`, `E28` |
| `E30-S04` | Implement arm/lock, the environment badge and confirmation policy | Story | 5 | web | `E30-S01`, `E30-X01`, `E39` |
| `E30-S05` | Wire trading hotkeys with focus suppression and hold-to-confirm | Story | 2 | web | `E30-S04`, `E30-S02`, `E13` |
| `E30-S06` | Add the pre-trade risk preview and account / trade-group selector | Story | 5 | web | `E30-S03`, `E28`, `E34` |
| `E30-S07` | Ship order templates and the SCR-114 trading-defaults settings section | Story | 2 | web | `E30-S04`, `E30-S02` |
| `E31-S06` | One-click flatten, cancel-all and reverse with the confirmation policy | Story | 2 | web | `E31-T01`, `E31-D03`, `E30`, `E32`, `E39` |
| `E32-S03` | Generate and submit scaled entry ladders and DCA ladders with a shared stop | Story | 5 | api | `E32-T01`, `E29`, `E28` |
| `E32-S06` | Build the SCR-065 scaled and DCA ladder builder with a full preview table | Story | 3 | web | `E32-S03`, `E32-D07`, `E30` |
| `E32-T04` | Update schemas, OpenAPI, WS contract and write ADR-0016 for E32 | Chore | 1 | docs | `E32-T03`, `E32-S02`, `E32-S03` |
| `E33-D07` | Design QA of the shipped algo builders and monitor panel | Task | 2 | web | `E33-S05`, `E33-S06` |
| `E33-Q02` | E2E suite additions for algo builders, monitor panel and full algo lifecycles | Task | 5 | web | `E33-S05`, `E33-S06` |
| `E33-Q03` | Performance and load scripts for algo request rate and scheduler fidelity | Task | 3 | api | `E33-S03`, `E33-S04` |
| `E33-Q04` | Chaos scenarios: crash seams, disconnects and risk-control halts for algos | Task | 5 | api | `E33-S03`, `E33-S04`, `E33-S01` |
| `E33-Q05` | Accessibility audit of the algo builders and monitor panel | Task | 3 | web | `E33-S05`, `E33-S06` |
| `E33-Q06` | Exploratory charter, regression pack and QA sign-off for emulated algos | Task | 3 | api | `E33-Q02`, `E33-Q04` |
| `E33-S02` | Emulate iceberg: slice a large order into randomised visible tranches | Story | 3 | api | `E33-T01`, `E50-S02`, `E50-T49`, `E50-T59` |
| `E33-S03` | Emulate TWAP: schedule slices over a window with jitter and catch-up | Story | 3 | api | `E33-S02`, `E50-S02`, `E50-T49`, `E50-T59` |
| `E33-S04` | Emulate chase: peg a limit to the best price with hard anti-runaway bounds | Story | 3 | api | `E33-S02`, `E33-T01`, `E50-S02`, `E50-T49`, `E50-T59` |
| `E33-S05` | Build the emulated-algo builder modals SCR-066, SCR-067, SCR-068 and SCR-069 | Story | 3 | web | `E33-T02`, `E33-D06` |
| `E33-S06` | Build the algo monitor panel SCR-070 with orphan adoption and bulk controls | Story | 3 | web | `E33-T02`, `E33-D06` |
| `E33-T03` | Write ADR-0016 and reconcile plan docs with the shipped emulated algos | Chore | 1 | docs | `E33-S06`, `E33-S04` |
| `E33-X02` | Abuse cases, SAST/DAST rules and permission checks for emulated algos | Task | 3 | api | `E33-X01`, `E33-S04`, `E33-S06` |
| `E33-X03` | Security review and sign-off of the shipped emulated-algo surfaces | Task | 2 | api | `E33-X02`, `E33-Q04` |
| `E34-S02` | Execute a fan-out with admission control, parallel submission and a native SL per leg | Story | 5 | api | `E34-S01`, `E34-T02`, `E34-X01`, `E32`, `E39`, `E50-T59`, `E50-S01` |
| `E34-S03` | Handle partial fan-out failure with a restartable compensating unwind and per-leg retry | Story | 3 | api | `E34-S02`, `E34-T01`, `E50-T59`, `E50-S01` |
| `E35-Q05` | Run chaos scenarios against the rule engine | Task | 3 | api | `E35-Q03` |
| `E35-Q06` | Accessibility audit of the six rule-engine screens | Task | 3 | web | `E35-S09`, `E35-D04` |
| `E35-Q07` | Execute the exploratory charters, regression pack and epic QA sign-off | Task | 3 | api | `E35-Q05`, `E35-Q06` |
| `E35-X03` | Security review and sign-off of the shipped rule engine | Task | 2 | api | `E35-X02`, `E35-S09`, `E35-T05` |
| `E36-Q05` | Run the exploratory charters, assemble the regression pack and give QA sign-off | Task | 3 | web | `E36-Q02`, `E36-Q03`, `E36-Q04`, `E36-S06` |
| `E36-X03` | Security review and sign-off of the shipped rule authoring surface | Task | 2 | web | `E36-X02`, `E36-S06`, `E36-Q05` |
| `E37-D06` | Design QA of the built node-graph editor against the SCR-082 specification | Task | 2 | web | `E37-S04`, `E37-S05` |
| `E37-Q02` | Automate the node-editor E2E suite in Playwright (web and Electron) | Task | 3 | web | `E37-Q01`, `E37-S04`, `E37-S05` |
| `E37-Q03` | Build the >=30-rule round-trip corpus and the IR fuzz gate (R3 exit criterion 5) | Task | 3 | web | `E37-S04` |
| `E37-Q04` | Benchmark the 200-node 60 fps and 500 ms compile+diff budgets | Task | 2 | web | `E37-T02`, `E37-S03` |
| `E37-Q05` | Accessibility audit of the node editor incl. the verified non-canvas alternative | Task | 3 | web | `E37-S05`, `E37-D04` |
| `E37-Q06` | Exploratory charter, regression pack and QA sign-off for the node editor | Task | 2 | web | `E37-Q02`, `E37-Q05`, `E37-Q03` |
| `E37-T02` | Add auto-layout, node search and minimap navigation for large graphs | Task | 2 | web | `E37-S01`, `E37-K01` |
| `E37-X02` | Execute abuse cases and the security review of the node editor | Task | 2 | web | `E37-X01`, `E37-S04` |
| `E38-Q01` | Black-box test plan for paper trading and demo/live parity | Task | 2 | cross-cutting | `E38-D06`, `E38-K01` |
| `E38-S03` | Simulate fills locally with the paper matcher's queue, latency and fee models | Story | 5 | backtesting | `E38-S01`, `E26`, `E29`, `E50-T59`, `E50-S02` |
| `E38-T03` | Nightly paper-versus-demo fill divergence job and fidelity panel data | Task | 2 | backtesting | `E38-S03`, `E38-S01`, `E26` |
| `E40-S01` | Ship the SCR-090 alerts centre and the SCR-091 alert editor | Story | 2 | web | `E40-D02`, `E40-T02`, `E40-T04` |
| `E40-S02` | Ship fired-alert toasts, SCR-092/SCR-014 content and SCR-115 preferences | Story | 2 | web | `E40-D02`, `E40-S01`, `E40-T04` |
| `E40-T05` | Reconcile plan docs, ADRs and the changelog with the shipped alert system | Chore | 1 | docs | `E40-S02`, `E40-T04` |
| `E41-T04` | Implement tags, notes, auto-tagging and the audited export job | Task | 3 | api | `E41-T01` |
| `E41-X01` | STRIDE threat model and abuse cases for journal & analytics | Task | 2 | api | `E41-T01` |
| `E42-S03` | Build SCR-122 user detail with role/account binding, limits and SCR-124 view-as | Story | 5 | web | `E42-S02`, `E42-D03`, `E42-T04`, `E28-T02`, `E39-T02` |
| `E42-S04` | Build SCR-135 audit log browser and SCR-136 event detail with integrity state | Story | 5 | web | `E42-S01`, `E42-D04`, `E42-T02` |
| `E42-S07` | Build the manager onboarding wizard and trade-group/recorder governance | Story | 2 | web | `E42-S03`, `E42-D05`, `E27-S01`, `E28-S03`, `E16-S03` |
| `E42-S08` | Build the admin statechart inspector screen: machine list, state diagram, event timeline, latch acknowledge | Story | 5 | web | `E42-T07`, `E42-S01`, `E09-S04` |
| `E43-D01` | Wireframe to hi-fi: SCR-137 security centre and the Live-enablement gate | Task | 5 | web | `E42` |
| `E43-D02` | Hi-fi SCR-128 key health panel and SCR-136 audit event detail hardening states | Task | 3 | web | `E42`, `E27` |
| `E44-D01` | Wireframe the live-enablement gate, hardened switch and live visual language | Task | 3 | web | `E42`, `E38` |

### 20.5 Design-track deliverables due

**Design sprint D-S18** (roadmap 1.2) produces: Design-QA sweep specs, empty/error/loading state audit, GA polish

> Consumed by engineering sprint **S20** (+2 sprints). Every one of these must reach Status=Done with CDO sign-off **inside this sprint**, or the S20 frontend stories fail DoR and cannot be pulled.

| Key | Title | Est | Due |
|---|---|---|---|
| `E33-D07` | Design QA of the shipped algo builders and monitor panel | 2 | 2027-01-28 |
| `E37-D06` | Design QA of the built node-graph editor against the SCR-082 specification | 2 | 2027-01-28 |
| `E43-D01` | Wireframe to hi-fi: SCR-137 security centre and the Live-enablement gate | 5 | 2027-01-28 |
| `E43-D02` | Hi-fi SCR-128 key health panel and SCR-136 audit event detail hardening states | 3 | 2027-01-28 |
| `E44-D01` | Wireframe the live-enablement gate, hardened switch and live visual language | 3 | 2027-01-28 |

Design total: **15 pts** across 5 tickets.

### 20.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: Threat-model refresh (OMS) (s05, S14-S19)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Safety-invariant suite (q06, S15-S18)
- qa: Load & soak campaigns (q07, S09-S20)
- qa: Chaos catalogue (q08, S18-S23)

**QA tickets (46 pts, 15 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E33-Q02` | E2E suite additions for algo builders, monitor panel and full algo lifecycles | 5 | `E33-S05`, `E33-S06` |
| `E33-Q03` | Performance and load scripts for algo request rate and scheduler fidelity | 3 | `E33-S03`, `E33-S04` |
| `E33-Q04` | Chaos scenarios: crash seams, disconnects and risk-control halts for algos | 5 | `E33-S03`, `E33-S04`, `E33-S01` |
| `E33-Q05` | Accessibility audit of the algo builders and monitor panel | 3 | `E33-S05`, `E33-S06` |
| `E33-Q06` | Exploratory charter, regression pack and QA sign-off for emulated algos | 3 | `E33-Q02`, `E33-Q04` |
| `E35-Q05` | Run chaos scenarios against the rule engine | 3 | `E35-Q03` |
| `E35-Q06` | Accessibility audit of the six rule-engine screens | 3 | `E35-S09`, `E35-D04` |
| `E35-Q07` | Execute the exploratory charters, regression pack and epic QA sign-off | 3 | `E35-Q05`, `E35-Q06` |
| `E36-Q05` | Run the exploratory charters, assemble the regression pack and give QA sign-off | 3 | `E36-Q02`, `E36-Q03`, `E36-Q04`, `E36-S06` |
| `E37-Q02` | Automate the node-editor E2E suite in Playwright (web and Electron) | 3 | `E37-Q01`, `E37-S04`, `E37-S05` |
| `E37-Q03` | Build the >=30-rule round-trip corpus and the IR fuzz gate (R3 exit criterion 5) | 3 | `E37-S04` |
| `E37-Q04` | Benchmark the 200-node 60 fps and 500 ms compile+diff budgets | 2 | `E37-T02`, `E37-S03` |
| `E37-Q05` | Accessibility audit of the node editor incl. the verified non-canvas alternative | 3 | `E37-S05`, `E37-D04` |
| `E37-Q06` | Exploratory charter, regression pack and QA sign-off for the node editor | 2 | `E37-Q02`, `E37-Q05`, `E37-Q03` |
| `E38-Q01` | Black-box test plan for paper trading and demo/live parity | 2 | `E38-D06`, `E38-K01` |

**Security tickets (13 pts, 6 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E33-X02` | Abuse cases, SAST/DAST rules and permission checks for emulated algos | 3 | `E33-X01`, `E33-S04`, `E33-S06` |
| `E33-X03` | Security review and sign-off of the shipped emulated-algo surfaces | 2 | `E33-X02`, `E33-Q04` |
| `E35-X03` | Security review and sign-off of the shipped rule engine | 2 | `E35-X02`, `E35-S09`, `E35-T05` |
| `E36-X03` | Security review and sign-off of the shipped rule authoring surface | 2 | `E36-X02`, `E36-S06`, `E36-Q05` |
| `E37-X02` | Execute abuse cases and the security review of the node editor | 2 | `E37-X01`, `E37-S04` |
| `E41-X01` | STRIDE threat model and abuse cases for journal & analytics | 2 | `E41-T01` |

### 20.7 Risks & dependency watch-list

- 90/90 load, zero headroom, immediately before the R3-exit sprint.
- E33 at 43 pts (emulated algos) is the largest item; the chase algo is descoping-ladder item #5 if the sprint is at risk.
- QA at 46 pts; the chaos catalogue (q08) opens and runs to S23.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S18 |
|---|---|---|
| `E29` | epic E29 (whole epic must be Done) | 5 |
| `E28` | epic E28 (whole epic must be Done) | 4 |
| `E32` | epic E32 (whole epic must be Done) | 4 |
| `E33-S04` | Sprint 16 | 4 |
| `E37-S04` | Sprint 17 | 4 |
| `E39` | epic E39 (whole epic must be Done) | 3 |
| `E30` | epic E30 (whole epic must be Done) | 3 |
| `E35-S09` | Sprint 17 | 3 |
| `E37-S05` | Sprint 17 | 3 |
| `E42` | epic E42 (whole epic must be Done) | 3 |
| `E31-T01` | Sprint 17 | 2 |
| `E31-D03` | Sprint 15 | 2 |
| _... 58 more_ | | |

### 20.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Iceberg and TWAP execute on demo; the node-graph editor round-trips a rule authored in the form editor through the same IR.

**Exit expectation:** Both rule editors behind one feature flag, ready to merge together in S19.

### 20.9 Burn-up - R3 train

| Sprint | Eng pts this sprint | Cumulative R3 | R3 total | Remaining | % complete |
|---|---|---|---|---|---|
| S14 | 88 | 88 | 488 | 400 | 18% |
| S15 | 89 | 177 | 488 | 311 | 36% |
| S16 | 89 | 266 | 488 | 222 | 55% |
| S17 | 89 | 355 | 488 | 133 | 73% |
| S18 **<- this sprint** | 88 | 443 | 488 | 45 | 91% |
| S19 | 45 | 488 | 488 | 0 | 100% |

---

## 21. S19 - 2027-01-29 -> 2027-02-04 (R3)

### 21.1 Sprint goal(s)

- **Close R3, cut `0.4.0`, and enter the 7-day demo-trading soak.**
- Order ticket UI (E30) and fan-out + rate governor (E34) complete - both gate the Live train.
- **QA is over pool: 113 pts vs 45 (+68).**
- **Security is over pool: 30 pts vs 20 (+10).**

### 21.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 45 | 90 | +45 | ok |
| Design (D) | 31 | 60 | +29 | ok |
| QA (Q) | 113 | 45 | -68 | **OVER** |
| Security (X) | 30 | 20 | -10 | **OVER** |
| **Total** | **219** | **215** | **-4** | |

### 21.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E34** | Trade-group fan-out & rate-limit governor | OMS & Execution (BE-OMS) | 40 | 11 |
| **E30** | Order ticket UI | App & Charting UI (FE-App) | 28 | 9 |
| **E38** | Paper trading & demo/live parity | OMS & Execution (BE-OMS) | 26 | 14 |
| **E41** | Journal & analytics | App & Charting UI (FE-App) | 25 | 9 |
| **E32** | Brackets, scaled orders & native SL invariant | OMS & Execution (BE-OMS) | 24 | 8 |
| **E29** | OMS core & order state machine | OMS & Execution (BE-OMS) | 21 | 7 |
| **E42** | Admin screens (users, roles, audit, health, flags) | Accounts & Security (BE-Sec) | 17 | 7 |
| **E28** | Per-account profiles & trade groups | OMS & Execution (BE-OMS) | 8 | 5 |
| **E50** | xstate-statemachine adoption: factory, persistence, plugins, contract suite, catalogue | Platform & DevSecOps | 8 | 3 |
| **E31** | Chart & DOM trading interactions | App & Charting UI (FE-App) | 7 | 6 |
| **E44** | Live-enablement gating & environment separation | Accounts & Security (BE-Sec) | 6 | 2 |
| **E40** | Alerts & notifications | Rules & Alerts (BE-Rules) | 4 | 4 |
| **E43** | Security hardening & pen-test remediation | Accounts & Security (BE-Sec) | 3 | 1 |
| **E35** | Rule engine IR, compiler & runtime | Rules & Alerts (BE-Rules) | 2 | 1 |


**Statechart lane:** E31 (`E31-D07`, `E31-Q01`, `E31-Q02`, `E31-T02`, `E31-X01`, `E31-X02`); E32 (`E32-D08`, `E32-Q03`, `E32-Q04`, `E32-Q06`, `E32-Q07`, `E32-Q08`, `E32-X02`, `E32-X03`); E34 (`E34-D06`, `E34-Q02`, `E34-Q03`, `E34-Q04`, `E34-Q05`, `E34-Q06`, `E34-S04`, `E34-S05`, `E34-T03`, `E34-X02`, `E34-X03`); E35 (`E35-D06`); E50 (`E50-C01`, `E50-C02`, `E50-T06`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 21.4 Tickets (87)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E28-D07` | Design QA the implemented profile and trade-group screens against the handoff pack | Task | 1 | web | `E28-S01`, `E28-S02`, `E28-S03`, `E28-S04` |
| `E28-Q04` | Audit accessibility and run exploratory charters across the six profile and group screens | Task | 2 | web | `E28-S02`, `E28-S04`, `E28-D05` |
| `E28-Q05` | Assemble the E28 regression pack and record QA sign-off for the epic | Task | 2 | api | `E28-Q02`, `E28-Q03`, `E28-Q04`, `E28-S05` |
| `E28-S05` | Apply audited per-trade profile overrides that can narrow but never widen a risk cap | Story | 2 | web | `E28-K01`, `E28-S04`, `E28-T04` |
| `E28-X04` | Run the cap-bypass and privilege-escalation drills and record the E28 security sign-off | Task | 1 | api | `E28-X02`, `E28-X03`, `E28-S05` |
| `E29-D07` | Design QA of the shipped OMS blotters | Task | 3 | web | `E29-S01`, `E29-S02`, `E29-S04`, `E29-S07` |
| `E29-Q02` | Automate the E2E and contract suites for the OMS lifecycle and blotters | Task | 5 | web | `E29-Q01`, `E29-S02`, `E29-S07` |
| `E29-Q04` | Build the chaos scenarios for lost acks, reconnect storms and Postgres failover | Task | 3 | infra | `E29-T06`, `E29-T08`, `E29-S07` |
| `E29-Q05` | Run the accessibility audit of the blotters, fills detail and reconciliation states | Task | 3 | web | `E29-D05`, `E29-S07`, `E29-S08` |
| `E29-Q06` | Execute the exploratory charters, assemble the regression pack and record E29 QA sign-off | Task | 3 | docs | `E29-Q02`, `E29-Q03`, `E29-Q04`, `E29-Q05` |
| `E29-S08` | Build the position detail view assembled from OMS state and executions | Story | 2 | web | `E29-S04`, `E29-S06` |
| `E29-X03` | Security review and sign-off of the shipped OMS | Task | 2 | docs | `E29-X02`, `E29-Q04`, `E29-Q06` |
| `E30-D07` | Design QA the shipped order ticket against the handoff pack | Task | 3 | web | `E30-S07`, `E30-T02`, `E30-S06` |
| `E30-Q02` | Automate the Playwright E2E suite for the order ticket on demo | Task | 5 | web | `E30-Q01`, `E30-S05`, `E30-S06` |
| `E30-Q03` | Build the performance and load scripts for the ticket's latency budgets | Task | 3 | web | `E30-K01`, `E30-S06` |
| `E30-Q04` | Chaos scenarios for in-flight orders, lost acknowledgements and revoked arming | Task | 3 | web | `E30-S04`, `E30-S06`, `E29` |
| `E30-Q05` | Accessibility audit of ticket, confirmation, rejection, defaults | Task | 5 | web | `E30-D05`, `E30-S06`, `E30-S07`, `E30-T02` |
| `E30-Q06` | Run exploratory charters, assemble regression pack, QA sign-off | Task | 3 | web | `E30-D07`, `E30-Q02`, `E30-Q03`, `E30-Q04`, `E30-Q05` |
| `E30-T03` | Reconcile the plan docs and changelog with the shipped order ticket | Chore | 1 | docs | `E30-Q06`, `E30-S07`, `E30-T02` |
| `E30-X02` | Implement the abuse-case suite, scope assertions and SAST rules for the ticket | Task | 3 | web | `E30-X01`, `E30-S04`, `E30-S06`, `E30-S07` |
| `E30-X03` | Security review and sign-off of the shipped order ticket | Task | 2 | web | `E30-D07`, `E30-X02`, `E30-Q04`, `E30-Q06` |
| `E31-D07` | Design QA of shipped chart and DOM trading | Task | 1 | web | `E31-S02`, `E31-S05`, `E31-S06` |
| `E31-Q01` | Test plan and E2E suite for chart and DOM trading | Task | 1 | web | `E31-D03`, `E31-S01`, `E31-S04` |
| `E31-Q02` | Perf, chaos and a11y audit plus QA sign-off for chart & DOM trading | Task | 2 | web | `E31-Q01`, `E31-K01`, `E31-S03`, `E31-S05`, `E31-S06`, `E31-D07` |
| `E31-T02` | Reconcile plan docs with the shipped chart and DOM trading behaviour | Chore | 1 | docs | `E31-S02`, `E31-S05`, `E31-S06`, `E31-Q02` |
| `E31-X01` | STRIDE threat model for chart and DOM trading interactions | Task | 1 | web | `E29`, `E39`, `E31-K01`, `E31-D03` |
| `E31-X02` | Abuse cases, RBAC/arm bypass checks and security sign-off for trading surfaces | Task | 1 | web | `E31-X01`, `E31-S04`, `E31-S06`, `E31-Q02` |
| `E32-D08` | Execute design QA on the built bracket, ladder and SL/TP screens | Task | 2 | web | `E32-S05`, `E32-S06`, `E32-S07`, `E32-D07` |
| `E32-Q03` | Write the black-box test plan for scaled and DCA ladders | Task | 3 | api | `E32-S03` |
| `E32-Q04` | Automate the Playwright E2E suite for the three E32 screens on demo | Task | 5 | web | `E32-S05`, `E32-S06`, `E32-S07` |
| `E32-Q06` | Build the perf and load scripts proving budget #4 for E32's order paths | Task | 3 | api | `E32-S01`, `E32-S03` |
| `E32-Q07` | Run the accessibility audit of SCR-064, SCR-065 and SCR-069 | Task | 3 | web | `E32-S05`, `E32-S06`, `E32-S07` |
| `E32-Q08` | Run exploratory charters, assemble the regression pack and record QA sign-off | Task | 3 | api | `E32-Q04`, `E32-Q05`, `E32-Q07` |
| `E32-X02` | Implement the abuse-case suite, RBAC scope assertions and SAST rules for E32 | Task | 3 | api | `E32-X01`, `E32-T01`, `E32-S03` |
| `E32-X03` | Perform the security review and sign-off of the shipped E32 surface | Task | 2 | api | `E32-X02`, `E32-Q05` |
| `E34-D06` | Design QA of the shipped trade-group ticket and manager | Task | 3 | web | `E34-S04`, `E34-S05` |
| `E34-Q02` | Add the fan-out end-to-end suite (Playwright web + Electron) | Task | 5 | cross-cutting | `E34-Q01`, `E34-S02`, `E34-S03`, `E34-S04`, `E34-S05` |
| `E34-Q03` | Build the k6 load profile for sustained fan-out at the per-UID rate limit | Task | 5 | infra | `E34-T02`, `E34-S02` |
| `E34-Q04` | Run chaos scenarios against in-flight fan-outs and unwinds | Task | 5 | infra | `E34-S03`, `E34-Q02` |
| `E34-Q05` | Accessibility audit of the trade-group ticket and manager | Task | 3 | web | `E34-S04`, `E34-S05`, `E34-D04` |
| `E34-Q06` | Execute the exploratory charters, regression pack and QA sign-off for E34 | Task | 5 | cross-cutting | `E34-Q02`, `E34-Q03`, `E34-Q04`, `E34-Q05` |
| `E34-S04` | Build the trade-group ticket (SCR-061) with per-account preview and partial-failure state | Story | 5 | web | `E34-D05`, `E34-S01`, `E34-S02`, `E34-S03`, `E30` |
| `E34-S05` | Build the trade-group manager (SCR-062) with aggregate and per-account PnL | Story | 3 | web | `E34-D05`, `E34-T01`, `E34-S03` |
| `E34-T03` | Reconcile the plan docs and ADR-0008 with the shipped fan-out behaviour | Chore | 1 | docs | `E34-S03`, `E34-S05` |
| `E34-X02` | Abuse cases, permission checks and SAST/DAST rules for the fan-out path | Task | 3 | api | `E34-X01`, `E34-S02`, `E34-S03` |
| `E34-X03` | Security review and sign-off of the shipped fan-out and trade-group surfaces | Task | 2 | api | `E34-S04`, `E34-S05`, `E34-X02` |
| `E35-D06` | Design QA of the shipped rule-engine screens | Task | 2 | web | `E35-S08`, `E35-S09` |
| `E38-D07` | Design QA of the shipped E38 surfaces | Task | 2 | web | `E38-S03`, `E38-S04`, `E38-S05`, `E38-S06`, `E38-S07`, `E38-S08` |
| `E38-Q02` | Automate the E38 end-to-end suite in Playwright web and Electron | Task | 3 | cross-cutting | `E38-Q01`, `E38-S04`, `E38-S05`, `E38-S06`, `E38-S07`, `E38-S08` |
| `E38-Q03` | Performance and load validation of the demo order path and paper matcher | Task | 2 | cross-cutting | `E38-S01`, `E38-S03`, `E38-S02` |
| `E38-Q04` | Chaos scenarios for environment switching and paper state recovery | Task | 2 | cross-cutting | `E38-S02`, `E38-S03`, `E38-S01` |
| `E38-Q05` | Accessibility audit of every E38 surface with screen-reader passes | Task | 2 | cross-cutting | `E38-S04`, `E38-S05`, `E38-S06`, `E38-S07`, `E38-S08`, `E38-D05` |
| `E38-Q06` | Execute the E38 regression pack, exploratory charters and QA sign-off | Task | 2 | cross-cutting | `E38-Q02`, `E38-Q03`, `E38-Q04`, `E38-Q05` |
| `E38-S04` | Show demo/live chrome everywhere and switch environments from the shell | Story | 3 | web | `E38-D06`, `E38-S02`, `E38-T02` |
| `E38-S05` | Present simulated results with model disclosure and simulated-everywhere labels | Story | 1 | web | `E38-D06`, `E38-S03`, `E26`, `E41-T01`, `E41-T03` |
| `E38-S06` | Reset a paper balance safely and never in live | Story | 1 | web | `E38-D06`, `E38-S03`, `E38-S01` |
| `E38-S07` | Grant, revoke and acknowledge per-user demo and live eligibility | Story | 2 | auth | `E38-D06`, `E38-T02`, `E09`, `E42` |
| `E38-S08` | Generate and display the demo-versus-live parity report with staleness flags | Story | 2 | web | `E38-D06`, `E38-K01`, `E38-T01`, `E42` |
| `E38-T04` | Reconcile plan docs and ADRs with the shipped paper and parity behaviour | Chore | 1 | docs | `E38-S03`, `E38-S08`, `E38-T03` |
| `E38-X02` | Abuse cases, permission checks and SAST rules for the environment boundary | Task | 2 | cross-cutting | `E38-X01`, `E38-T02`, `E38-S02`, `E38-S03`, `E38-S07` |
| `E38-X03` | Security review and sign-off of the shipped paper-trading and parity surfaces | Task | 1 | cross-cutting | `E38-X02`, `E38-Q06`, `E38-S08` |
| `E40-D03` | Design QA the shipped alert surfaces against the handoff pack | Task | 1 | web | `E40-D02`, `E40-S02` |
| `E40-Q01` | Write the alert test plan and automate the E2E and contract suites | Task | 1 | alerts | `E40-S01`, `E40-S02`, `E40-T04` |
| `E40-Q02` | Run alert perf/storm/chaos and a11y audits, then give QA sign-off | Task | 1 | alerts | `E40-Q01`, `E40-S02` |
| `E40-X01` | Threat-model, abuse-test and security sign-off the alert system | Task | 1 | alerts | `E40-Q02`, `E40-T04` |
| `E41-D05` | Design QA of the built journal screens against the hi-fi | Task | 2 | web | `E41-S01`, `E41-S02`, `E41-S03`, `E41-S04` |
| `E41-Q01` | Author the journal black-box test plan and extend the E2E suite | Task | 3 | web | `E41-S01`, `E41-S02`, `E41-S03` |
| `E41-Q02` | Run journal performance, load and chaos scenarios | Task | 3 | api | `E41-T03`, `E41-S03` |
| `E41-Q03` | Journal accessibility audit, regression pack and QA sign-off | Task | 2 | web | `E41-Q01`, `E41-Q02`, `E41-D05`, `E41-X02` |
| `E41-S01` | Build the journal trade list screen SCR-093 | Story | 5 | web | `E41-T01`, `E41-T04`, `E41-D04` |
| `E41-S02` | Build the trade detail / post-mortem screen SCR-094 with replay deep-link | Story | 3 | web | `E41-S01`, `E41-T02`, `E41-D04` |
| `E41-S03` | Build the journal analytics dashboard SCR-095 | Story | 3 | web | `E41-T03`, `E41-D04` |
| `E41-S04` | Build the journal tag manager SCR-096 and the export flow UI | Story | 1 | web | `E41-S01`, `E41-T04`, `E41-D04` |
| `E41-X02` | Security review of journal writes, scoping and export controls | Task | 3 | api | `E41-X01`, `E41-T04`, `E41-S04` |
| `E42-D07` | Design QA the built admin screens against spec and sign off | Task | 2 | web | `E42-S04`, `E42-S05`, `E42-S06`, `E42-S07` |
| `E42-Q02` | Automate the admin E2E suite including cross-session and timing assertions | Task | 3 | web | `E42-Q01`, `E42-S02`, `E42-S03`, `E42-S04` |
| `E42-Q03` | Run admin performance, load and chaos scenarios including degraded rendering | Task | 3 | web | `E42-Q01`, `E42-S04`, `E42-S06`, `E42-T02` |
| `E42-Q04` | Run exploratory charters and assemble the E42 regression pack with QA sign-off | Task | 2 | web | `E42-Q02`, `E42-S05`, `E42-S06`, `E42-S07`, `E42-Q06` |
| `E42-Q05` | Run the WCAG 2.2 AA accessibility audit across every admin screen | Task | 2 | web | `E42-D06`, `E42-S04`, `E42-S05`, `E42-S06` |
| `E42-Q06` | Verify deferred ADMIN Musts are owned by E43/E44 and no enable path ships | Task | 2 | web | `E42-S01`, `E42-S05`, `E42-T03`, `E42-Q01` |
| `E42-X02` | Security review: RBAC, elevation, audit and destructive admin paths | Task | 3 | api | `E42-X01`, `E42-S03`, `E42-S04`, `E42-S05`, `E42-T02`, `E42-T03`, `E42-T04` |
| `E43-D03` | Accessibility review, design QA and handoff for E43 security surfaces | Task | 3 | web | `E43-D01`, `E43-D02` |
| `E44-D02` | Hi-fi designs for SCR-137/SCR-145 gate and SCR-074 hardened switch | Task | 3 | web | `E44-D01` |
| `E44-D03` | Live visual language, eligibility control, motion, a11y review and handoff | Task | 3 | web | `E44-D01`, `E44-D02` |
| `E50-C01` | Contribute the conformance suite upstream | Task | 3 | api | `E50-T31` |
| `E50-C02` | Contribute the benchmark harness upstream | Task | 2 | api | `E50-T06` |
| `E50-T06` | Contract suite <60 s budget gate + throughput budget; BENCH-1 idle re-run (P3-G4) | Task | 3 | api | `E50-T31` |

### 21.5 Design-track deliverables due

The design org is past D-S18 and is on **design-QA and defect support** (roadmap 1.2): no new screens, capacity reserved for GA polish.

| Key | Title | Est | Due |
|---|---|---|---|
| `E28-D07` | Design QA the implemented profile and trade-group screens against the handoff pack | 1 | 2027-02-04 |
| `E29-D07` | Design QA of the shipped OMS blotters | 3 | 2027-02-04 |
| `E30-D07` | Design QA the shipped order ticket against the handoff pack | 3 | 2027-02-04 |
| `E31-D07` | Design QA of shipped chart and DOM trading | 1 | 2027-02-04 |
| `E32-D08` | Execute design QA on the built bracket, ladder and SL/TP screens | 2 | 2027-02-04 |
| `E34-D06` | Design QA of the shipped trade-group ticket and manager | 3 | 2027-02-04 |
| `E35-D06` | Design QA of the shipped rule-engine screens | 2 | 2027-02-04 |
| `E38-D07` | Design QA of the shipped E38 surfaces | 2 | 2027-02-04 |
| `E40-D03` | Design QA the shipped alert surfaces against the handoff pack | 1 | 2027-02-04 |
| `E41-D05` | Design QA of the built journal screens against the hi-fi | 2 | 2027-02-04 |
| `E42-D07` | Design QA the built admin screens against spec and sign off | 2 | 2027-02-04 |
| `E43-D03` | Accessibility review, design QA and handoff for E43 security surfaces | 3 | 2027-02-04 |
| `E44-D02` | Hi-fi designs for SCR-137/SCR-145 gate and SCR-074 hardened switch | 3 | 2027-02-04 |
| `E44-D03` | Live visual language, eligibility control, motion, a11y review and handoff | 3 | 2027-02-04 |

Design total: **31 pts** across 14 tickets.

### 21.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: Threat-model refresh (OMS) (s05, S14-S19)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Load & soak campaigns (q07, S09-S20)
- qa: Chaos catalogue (q08, S18-S23)
- qa: R3 7-day soak (q09, S19-S19)

**QA tickets (113 pts, 38 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E28-Q04` | Audit accessibility and run exploratory charters across the six profile and group screens | 2 | `E28-S02`, `E28-S04`, `E28-D05` |
| `E28-Q05` | Assemble the E28 regression pack and record QA sign-off for the epic | 2 | `E28-Q02`, `E28-Q03`, `E28-Q04`, `E28-S05` |
| `E29-Q02` | Automate the E2E and contract suites for the OMS lifecycle and blotters | 5 | `E29-Q01`, `E29-S02`, `E29-S07` |
| `E29-Q04` | Build the chaos scenarios for lost acks, reconnect storms and Postgres failover | 3 | `E29-T06`, `E29-T08`, `E29-S07` |
| `E29-Q05` | Run the accessibility audit of the blotters, fills detail and reconciliation states | 3 | `E29-D05`, `E29-S07`, `E29-S08` |
| `E29-Q06` | Execute the exploratory charters, assemble the regression pack and record E29 QA sign-off | 3 | `E29-Q02`, `E29-Q03`, `E29-Q04`, `E29-Q05` |
| `E30-Q02` | Automate the Playwright E2E suite for the order ticket on demo | 5 | `E30-Q01`, `E30-S05`, `E30-S06` |
| `E30-Q03` | Build the performance and load scripts for the ticket's latency budgets | 3 | `E30-K01`, `E30-S06` |
| `E30-Q04` | Chaos scenarios for in-flight orders, lost acknowledgements and revoked arming | 3 | `E30-S04`, `E30-S06`, `E29` |
| `E30-Q05` | Accessibility audit of ticket, confirmation, rejection, defaults | 5 | `E30-D05`, `E30-S06`, `E30-S07`, `E30-T02` |
| `E30-Q06` | Run exploratory charters, assemble regression pack, QA sign-off | 3 | `E30-D07`, `E30-Q02`, `E30-Q03`, `E30-Q04`, `E30-Q05` |
| `E31-Q01` | Test plan and E2E suite for chart and DOM trading | 1 | `E31-D03`, `E31-S01`, `E31-S04` |
| `E31-Q02` | Perf, chaos and a11y audit plus QA sign-off for chart & DOM trading | 2 | `E31-Q01`, `E31-K01`, `E31-S03`, `E31-S05`, `E31-S06`, `E31-D07` |
| `E32-Q03` | Write the black-box test plan for scaled and DCA ladders | 3 | `E32-S03` |
| `E32-Q04` | Automate the Playwright E2E suite for the three E32 screens on demo | 5 | `E32-S05`, `E32-S06`, `E32-S07` |
| `E32-Q06` | Build the perf and load scripts proving budget #4 for E32's order paths | 3 | `E32-S01`, `E32-S03` |
| `E32-Q07` | Run the accessibility audit of SCR-064, SCR-065 and SCR-069 | 3 | `E32-S05`, `E32-S06`, `E32-S07` |
| `E32-Q08` | Run exploratory charters, assemble the regression pack and record QA sign-off | 3 | `E32-Q04`, `E32-Q05`, `E32-Q07` |
| `E34-Q02` | Add the fan-out end-to-end suite (Playwright web + Electron) | 5 | `E34-Q01`, `E34-S02`, `E34-S03`, `E34-S04`, `E34-S05` |
| `E34-Q03` | Build the k6 load profile for sustained fan-out at the per-UID rate limit | 5 | `E34-T02`, `E34-S02` |
| `E34-Q04` | Run chaos scenarios against in-flight fan-outs and unwinds | 5 | `E34-S03`, `E34-Q02` |
| `E34-Q05` | Accessibility audit of the trade-group ticket and manager | 3 | `E34-S04`, `E34-S05`, `E34-D04` |
| `E34-Q06` | Execute the exploratory charters, regression pack and QA sign-off for E34 | 5 | `E34-Q02`, `E34-Q03`, `E34-Q04`, `E34-Q05` |
| `E38-Q02` | Automate the E38 end-to-end suite in Playwright web and Electron | 3 | `E38-Q01`, `E38-S04`, `E38-S05`, `E38-S06`, `E38-S07`, `E38-S08` |
| `E38-Q03` | Performance and load validation of the demo order path and paper matcher | 2 | `E38-S01`, `E38-S03`, `E38-S02` |
| `E38-Q04` | Chaos scenarios for environment switching and paper state recovery | 2 | `E38-S02`, `E38-S03`, `E38-S01` |
| `E38-Q05` | Accessibility audit of every E38 surface with screen-reader passes | 2 | `E38-S04`, `E38-S05`, `E38-S06`, `E38-S07`, `E38-S08`, `E38-D05` |
| `E38-Q06` | Execute the E38 regression pack, exploratory charters and QA sign-off | 2 | `E38-Q02`, `E38-Q03`, `E38-Q04`, `E38-Q05` |
| `E40-Q01` | Write the alert test plan and automate the E2E and contract suites | 1 | `E40-S01`, `E40-S02`, `E40-T04` |
| `E40-Q02` | Run alert perf/storm/chaos and a11y audits, then give QA sign-off | 1 | `E40-Q01`, `E40-S02` |
| `E41-Q01` | Author the journal black-box test plan and extend the E2E suite | 3 | `E41-S01`, `E41-S02`, `E41-S03` |
| `E41-Q02` | Run journal performance, load and chaos scenarios | 3 | `E41-T03`, `E41-S03` |
| `E41-Q03` | Journal accessibility audit, regression pack and QA sign-off | 2 | `E41-Q01`, `E41-Q02`, `E41-D05`, `E41-X02` |
| `E42-Q02` | Automate the admin E2E suite including cross-session and timing assertions | 3 | `E42-Q01`, `E42-S02`, `E42-S03`, `E42-S04` |
| `E42-Q03` | Run admin performance, load and chaos scenarios including degraded rendering | 3 | `E42-Q01`, `E42-S04`, `E42-S06`, `E42-T02` |
| `E42-Q04` | Run exploratory charters and assemble the E42 regression pack with QA sign-off | 2 | `E42-Q02`, `E42-S05`, `E42-S06`, `E42-S07`, `E42-Q06` |
| `E42-Q05` | Run the WCAG 2.2 AA accessibility audit across every admin screen | 2 | `E42-D06`, `E42-S04`, `E42-S05`, `E42-S06` |
| `E42-Q06` | Verify deferred ADMIN Musts are owned by E43/E44 and no enable path ships | 2 | `E42-S01`, `E42-S05`, `E42-T03`, `E42-Q01` |

**Security tickets (30 pts, 15 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E28-X04` | Run the cap-bypass and privilege-escalation drills and record the E28 security sign-off | 1 | `E28-X02`, `E28-X03`, `E28-S05` |
| `E29-X03` | Security review and sign-off of the shipped OMS | 2 | `E29-X02`, `E29-Q04`, `E29-Q06` |
| `E30-X02` | Implement the abuse-case suite, scope assertions and SAST rules for the ticket | 3 | `E30-X01`, `E30-S04`, `E30-S06`, `E30-S07` |
| `E30-X03` | Security review and sign-off of the shipped order ticket | 2 | `E30-D07`, `E30-X02`, `E30-Q04`, `E30-Q06` |
| `E31-X01` | STRIDE threat model for chart and DOM trading interactions | 1 | `E29`, `E39`, `E31-K01`, `E31-D03` |
| `E31-X02` | Abuse cases, RBAC/arm bypass checks and security sign-off for trading surfaces | 1 | `E31-X01`, `E31-S04`, `E31-S06`, `E31-Q02` |
| `E32-X02` | Implement the abuse-case suite, RBAC scope assertions and SAST rules for E32 | 3 | `E32-X01`, `E32-T01`, `E32-S03` |
| `E32-X03` | Perform the security review and sign-off of the shipped E32 surface | 2 | `E32-X02`, `E32-Q05` |
| `E34-X02` | Abuse cases, permission checks and SAST/DAST rules for the fan-out path | 3 | `E34-X01`, `E34-S02`, `E34-S03` |
| `E34-X03` | Security review and sign-off of the shipped fan-out and trade-group surfaces | 2 | `E34-S04`, `E34-S05`, `E34-X02` |
| `E38-X02` | Abuse cases, permission checks and SAST rules for the environment boundary | 2 | `E38-X01`, `E38-T02`, `E38-S02`, `E38-S03`, `E38-S07` |
| `E38-X03` | Security review and sign-off of the shipped paper-trading and parity surfaces | 1 | `E38-X02`, `E38-Q06`, `E38-S08` |
| `E40-X01` | Threat-model, abuse-test and security sign-off the alert system | 1 | `E40-Q02`, `E40-T04` |
| `E41-X02` | Security review of journal writes, scoping and export controls | 3 | `E41-X01`, `E41-T04`, `E41-S04` |
| `E42-X02` | Security review: RBAC, elevation, audit and destructive admin paths | 3 | `E42-X01`, `E42-S03`, `E42-S04`, `E42-S05`, `E42-T02`, `E42-T03`, `E42-T04` |

### 21.7 Risks & dependency watch-list

- E30 (30 pts landing here, 87 across the epic) and E34 (40 pts here, 91 across the epic) both complete in this sprint and both gate R4. Neither can slip without moving the Live train.
- **7-day soak (q09) closes 2027-02-03, one day before the R3 gate** - zero recovery time if the soak surfaces a defect.
- Mitigation to decide at S18 planning: pull E41 advanced analytics (ladder #7) and E40 webhook delivery (ladder #6) into R5.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S19 |
|---|---|---|
| `E38-S03` | Sprint 18 | 8 |
| `E30-S06` | Sprint 18 | 6 |
| `E34-S03` | Sprint 18 | 6 |
| `E38-D06` | Sprint 17 | 5 |
| `E42-S04` | Sprint 18 | 5 |
| `E42-S05` | Sprint 16 | 5 |
| `E29-S07` | Sprint 15 | 4 |
| `E31-S06` | Sprint 18 | 4 |
| `E34-S02` | Sprint 18 | 4 |
| `E38-S01` | Sprint 18 | 4 |
| `E38-S02` | Sprint 17 | 4 |
| `E40-T04` | Sprint 17 | 4 |
| _... 91 more_ | | |

### 21.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** **Full R3 walkthrough on demo:** ticket -> fan-out to N accounts -> every child order carries a native SL -> positions manager -> journal entry -> alert.

**Exit expectation:** **R3 gate (PRR + 7-day demo-trading soak) 2027-02-04 - `0.4.0`.** Soak closes 2027-02-03.

### 21.9 Burn-up - R3 train

| Sprint | Eng pts this sprint | Cumulative R3 | R3 total | Remaining | % complete |
|---|---|---|---|---|---|
| S14 | 88 | 88 | 488 | 400 | 18% |
| S15 | 89 | 177 | 488 | 311 | 36% |
| S16 | 89 | 266 | 488 | 222 | 55% |
| S17 | 89 | 355 | 488 | 133 | 73% |
| S18 | 88 | 443 | 488 | 45 | 91% |
| S19 **<- this sprint** | 45 | 488 | 488 | 0 | 100% |

---

# R4 - Live enablement

| | |
|---|---|
| Sprints | S20-S22 |
| Dates | 2027-02-05 -> 2027-02-25 |
| Version at cut | `1.0.0` |
| Deploys to | prod (live) |
| Gate | PRR + **Live-enablement gate** |
| Eng pts in backlog | 154 of 270 capacity (57%) |
| All-discipline pts | 253 |

R4 exists to earn the right to touch real money: pre-pen-test hardening, an independent pen-test with a pre-allocated 90-pt remediation reserve, reconciliation and chaos resilience, and the live-enablement gate that defaults OFF. Code freeze is 2027-02-11.

---

## 22. S20 - 2027-02-05 -> 2027-02-11 (R4)

### 22.1 Sprint goal(s)

- **Open R4.** Pre-pen-test hardening sweep and full STRIDE refresh across all ten areas (E43).
- Live-enablement gating and environment separation - the gate defaults **OFF** (E44).
- No new feature scope enters R4. Code freeze for pen-test is 2027-02-11.

### 22.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 87 | 90 | +3 | ok |
| Design (D) | 6 | 60 | +54 | ok |
| QA (Q) | 11 | 45 | +34 | ok |
| Security (X) | 12 | 20 | +8 | ok |
| **Total** | **116** | **215** | **+99** | |

### 22.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E43** | Security hardening & pen-test remediation | Accounts & Security (BE-Sec) | 68 | 18 |
| **E44** | Live-enablement gating & environment separation | Accounts & Security (BE-Sec) | 29 | 7 |
| **E45** | Reconciliation, chaos & failover resilience | OMS & Execution (BE-OMS) | 19 | 6 |


**Statechart lane:** E44 (`E44-T04`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 22.4 Tickets (31)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E43-K01` | Validate the Tailscale-only boundary assumption from off-tailnet | Spike | 3 | infra | `E43-X01` |
| `E43-Q01` | Black-box test plan for the security centre, posture checks and the Live gate | Task | 3 | web | `E43-D01`, `E43-D02` |
| `E43-Q02` | Exploratory charters for authentication, authorisation and admin surfaces | Task | 3 | api | `E43-T03`, `E43-T04`, `E43-T09` |
| `E43-Q03` | Automate the SR-152 negative-scenario E2E suite | Task | 5 | api | `E43-T03`, `E43-T09`, `E43-T04` |
| `E43-S02` | Machine-evaluated security posture checks and the security centre panel | Story | 8 | api | `E43-D02`, `E43-T04`, `E43-T10`, `E27`, `E42` |
| `E43-T01` | Tighten and CI-enforce the Content Security Policy across web and Electron | Task | 3 | web | `E43-X01`, `E43-X05` |
| `E43-T02` | Electron shell hardening and fuse audit with a build-time assertion gate | Task | 5 | infra | `E43-X01` |
| `E43-T03` | Session fixation, cookie and CSRF review across REST and WebSocket | Task | 5 | auth | `E43-X01`, `E09` |
| `E43-T04` | Auth rate-limit, lockout and enumeration-resistance review | Task | 3 | auth | `E43-X01`, `E09` |
| `E43-T05` | Dependency freeze, full SCA sweep and license-policy enforcement | Task | 3 | infra | `E02` |
| `E43-T06` | Full-history secrets scanning and credential-hygiene verification | Task | 3 | infra | `E02` |
| `E43-T08` | Authenticated OWASP ZAP full scan against staging with triage | Task | 3 | infra | `E43-T01`, `E43-T03`, `E43-T04`, `E43-T09` |
| `E43-T09` | Complete RBAC capability declarations and matrix-driven authorisation coverage | Task | 5 | api | `E09`, `E43-X01` |
| `E43-T10` | Verify audit-chain integrity, append-only grants and off-box mirroring | Task | 5 | api | `E09`, `E42` |
| `E43-T12` | Record ADR-0016 security-hardening decisions and update security docs | Task | 2 | docs | `E43-T01`, `E43-T03`, `E43-T09`, `E43-K01` |
| `E43-X01` | Refresh the STRIDE threat model across all ten areas for the R4 surface | Task | 3 | cross-cutting | `E34`, `E42` |
| `E43-X04` | Author the abuse-case catalogue for auth, order path, fan-out and admin | Task | 3 | cross-cutting | `E43-X01` |
| `E43-X05` | Complete the custom Semgrep ruleset and DAST rule tuning | Task | 3 | infra | `E02`, `E43-X01` |
| `E44-K01` | Spike: choose the physical environment-separation mechanism for OMS state | Spike | 2 | infra | `E44-X01` |
| `E44-T01` | Make environment a typed first-class setting with a fail-fast startup self-check | Task | 5 | api | `E44-X01`, `E27`, `E38` |
| `E44-T02` | Separate OMS state storage per environment (Postgres schemas, QuestDB namespaces) | Task | 8 | infra | `E44-K01`, `E44-T01` |
| `E44-T03` | Enforce the cross-environment guard in one middleware on every trading route | Task | 5 | api | `E44-T01`, `E44-X01` |
| `E44-T04` | Implement the live_trading gate: evidence-bound flag write and gate evaluation API | Task | 3 | api | `E44-T03`, `E44-T05`, `E50-T59`, `E50-S02`, `E50-T49` |
| `E44-T05` | Build the production key-permission audit tool reporting Bybit-declared scopes | Task | 3 | api | `E44-T01`, `E27` |
| `E44-X01` | STRIDE threat model and abuse cases for live gating and environment separation | Task | 3 | cross-cutting | `E43`, `E39` |
| `E45-D01` | Wireframe the reconciliation, discrepancy and drill surfaces | Task | 3 | web | `E42` |
| `E45-D02` | Deliver hi-fi designs, motion and engineering handoff for the discrepancy flow | Task | 3 | web | `E45-D01` |
| `E45-K01` | Choose the fault-injection mechanism for the chaos harness | Spike | 2 | infra | `E03`, `E29` |
| `E45-T06` | Build the chaos harness and wire the CI @chaos job | Task | 5 | infra | `E45-K01`, `E03` |
| `E45-T09` | Automate the rollback rehearsal and make its report a release gate artefact | Task | 3 | infra | `E45-T06`, `E44` |
| `E45-T10` | Automate the Postgres and Parquet restore drills | Task | 3 | infra | `E45-T09` |

### 22.5 Design-track deliverables due

The design org is past D-S18 and is on **design-QA and defect support** (roadmap 1.2): no new screens, capacity reserved for GA polish.

| Key | Title | Est | Due |
|---|---|---|---|
| `E45-D01` | Wireframe the reconciliation, discrepancy and drill surfaces | 3 | 2027-02-11 |
| `E45-D02` | Deliver hi-fi designs, motion and engineering handoff for the discrepancy flow | 3 | 2027-02-11 |

Design total: **6 pts** across 2 tickets.

### 22.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- sec: Pre-pen-test hardening (s07, S20-S20)
- qa: Load & soak campaigns (q07, S09-S20)
- qa: Chaos catalogue (q08, S18-S23)

**QA tickets (11 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E43-Q01` | Black-box test plan for the security centre, posture checks and the Live gate | 3 | `E43-D01`, `E43-D02` |
| `E43-Q02` | Exploratory charters for authentication, authorisation and admin surfaces | 3 | `E43-T03`, `E43-T04`, `E43-T09` |
| `E43-Q03` | Automate the SR-152 negative-scenario E2E suite | 5 | `E43-T03`, `E43-T09`, `E43-T04` |

**Security tickets (12 pts, 4 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E43-X01` | Refresh the STRIDE threat model across all ten areas for the R4 surface | 3 | `E34`, `E42` |
| `E43-X04` | Author the abuse-case catalogue for auth, order path, fan-out and admin | 3 | `E43-X01` |
| `E43-X05` | Complete the custom Semgrep ruleset and DAST rule tuning | 3 | `E02`, `E43-X01` |
| `E44-X01` | STRIDE threat model and abuse cases for live gating and environment separation | 3 | `E43`, `E39` |

### 22.7 Risks & dependency watch-list

- **Code freeze for pen-test is 2027-02-11 (end of this sprint).** Anything not merged does not get pen-tested.
- E43 at 77 pts is the largest single-epic sprint load in the entire plan.
- Pre-pen-test hardening (s07) is a hard-dated bar - the pen-test vendor slot is booked and non-movable.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S20 |
|---|---|---|
| `E42` | epic E42 (whole epic must be Done) | 4 |
| `E09` | epic E09 (whole epic must be Done) | 4 |
| `E27` | epic E27 (whole epic must be Done) | 3 |
| `E02` | epic E02 (whole epic must be Done) | 3 |
| `E43-D02` | Sprint 18 | 2 |
| `E03` | epic E03 (whole epic must be Done) | 2 |
| `E43-D01` | Sprint 18 | 1 |
| `E34` | epic E34 (whole epic must be Done) | 1 |
| `E38` | epic E38 (whole epic must be Done) | 1 |
| `E43` | epic E43 (whole epic must be Done) | 1 |
| `E39` | epic E39 (whole epic must be Done) | 1 |
| `E29` | epic E29 (whole epic must be Done) | 1 |
| _... 1 more_ | | |

### 22.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Live gate demonstrated in the OFF position: no code path can reach live regardless of input. STRIDE refresh presented.

**Exit expectation:** **Code freeze 2027-02-11 for pen-test.**

### 22.9 Burn-up - R4 train

| Sprint | Eng pts this sprint | Cumulative R4 | R4 total | Remaining | % complete |
|---|---|---|---|---|---|
| S20 **<- this sprint** | 87 | 87 | 154 | 67 | 56% |
| S21 | 56 | 143 | 154 | 11 | 93% |
| S22 | 11 | 154 | 154 | 0 | 100% |

---

## 23. S21 - 2027-02-12 -> 2027-02-18 (R4)

### 23.1 Sprint goal(s)

- **Independent pen-test runs this sprint.** Engineering load is deliberately held at 43 pts to absorb findings.
- Live gating completes (E44); reconciliation and chaos/failover begin (E45).
- The 90-pt pen-test remediation reserve is live from 2027-02-16.

### 23.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 56 | 90 | +34 | ok |
| Design (D) | 8 | 60 | +52 | ok |
| QA (Q) | 22 | 45 | +23 | ok |
| Security (X) | 16 | 20 | +4 | ok |
| **Total** | **102** | **215** | **+113** | |

### 23.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E44** | Live-enablement gating & environment separation | Accounts & Security (BE-Sec) | 35 | 10 |
| **E45** | Reconciliation, chaos & failover resilience | OMS & Execution (BE-OMS) | 33 | 10 |
| **E43** | Security hardening & pen-test remediation | Accounts & Security (BE-Sec) | 28 | 6 |
| **E46** | Performance hardening & budget enforcement | Chart Engine (FE-Engine) | 6 | 2 |


**Statechart lane:** E45 (`E45-T01`, `E45-T02`) — built on `cv.statechart.factory` over `xstate-statemachine==0.9.1` (ADR-0016 Accepted); each must stay green in the BLOCKING `tests/xstate_contract` suite.

### 23.4 Tickets (28)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E43-Q04` | Rate-limit and auth denial-of-service load profiles | Task | 3 | infra | `E43-T04`, `E34` |
| `E43-Q05` | Accessibility audit of the security centre, key health and audit detail screens | Task | 3 | web | `E43-S01`, `E43-S02`, `E43-D03` |
| `E43-S01` | Enforce and surface the Live-trading enablement gate on the security centre | Story | 8 | web | `E43-D01`, `E43-S02`, `E42`, `E09` |
| `E43-T07` | Generate, sign and publish SBOMs for backend, web bundle and desktop app | Task | 3 | infra | `E43-T05`, `E43-T02` |
| `E43-X02` | Commission and run the independent penetration test against the frozen build | Task | 8 | cross-cutting | `E43-X01`, `E43-X04`, `E43-X06`, `E43-T05`, `E43-T06`, `E43-T08`, `E43-K01`, `E43-S01` |
| `E43-X06` | Key-permission and RBAC-grant verification audit ahead of the pen-test | Task | 3 | auth | `E43-S02`, `E43-T09`, `E27` |
| `E44-D04` | Design QA of the built live-gating surfaces against the hi-fi specs | Task | 2 | web | `E44-S01`, `E44-S02`, `E44-S03`, `E44-S04` |
| `E44-Q01` | Author the live-gating black-box test plan and extend the E2E suite | Task | 5 | web | `E44-S01`, `E44-S02`, `E44-S03`, `E44-S04` |
| `E44-Q02` | Prove environment isolation and run gating perf, load and chaos scenarios | Task | 5 | infra | `E44-T02`, `E44-T03`, `E44-T04` |
| `E44-Q03` | Accessibility audit, regression pack and QA sign-off for live gating | Task | 3 | web | `E44-Q01`, `E44-D04` |
| `E44-S01` | Build the live-enablement gate UI on SCR-137 and SCR-145 | Story | 3 | web | `E44-D03`, `E44-T04` |
| `E44-S02` | Harden the Demo to Live switch on SCR-074 with gate, step-up and disarm | Story | 5 | web | `E44-D03`, `E44-T04`, `E44-T03` |
| `E44-S03` | Ship the pervasive live-mode visual language and confirm-on-every-order default | Story | 5 | web | `E44-D03`, `E44-T03` |
| `E44-S04` | Implement per-manager live eligibility with audited grant and revocation | Story | 3 | web | `E44-D03`, `E44-T03` |
| `E44-T06` | Write ADR-0016 environment separation and update the affected plan docs | Task | 1 | docs | `E44-K01`, `E44-T02`, `E44-T04` |
| `E44-X02` | Security review and abuse-case verification of the live gate and isolation | Task | 3 | cross-cutting | `E44-X01`, `E44-Q02`, `E44-Q01`, `E44-T04`, `E44-T05` |
| `E45-Q01` | Author the black-box test plan for reconciliation, dead-man's-switch and drills | Task | 3 | api | `E45-T01` |
| `E45-T01` | Implement the reconciliation core over orders, executions and positions | Task | 5 | api | `E29`, `E32`, `E45-X01`, `E50-T59`, `E50-S02`, `E50-T49` |
| `E45-T02` | Drive reconciliation triggers and the stale-account lockout | Task | 2 | api | `E45-T01`, `E50-T59`, `E50-S02`, `E50-T49` |
| `E45-T03` | Persist, expose and instrument the reconciliation report | Task | 3 | api | `E45-T01`, `E04` |
| `E45-T04` | Reconcile wallet balances and trade-group legs | Task | 3 | api | `E45-T01`, `E34` |
| `E45-T05` | Integrate the Bybit dead-man's-switch behind an explicit opt-in policy | Task | 3 | api | `E45-T02`, `E39` |
| `E45-T07` | Automate chaos catalogue part 1 - exchange and transport faults | Task | 5 | api | `E45-T06`, `E45-T02`, `E34` |
| `E45-T08` | Automate chaos catalogue part 2 - infrastructure, clock and client faults | Task | 5 | infra | `E45-T06`, `E45-T04` |
| `E45-T11` | Write the resilience runbooks and record ADR-0016 on reconciliation authority | Task | 2 | docs | `E45-T05`, `E45-T10` |
| `E45-X01` | STRIDE threat model for reconciliation, chaos tooling and failover | Task | 2 | api | `E29` |
| `E46-D01` | Design the completed engine diagnostics overlay and the compact latency indicator | Task | 3 | web | `E11`, `E04` |
| `E46-D02` | Design SCR-118 benchmark flow, recommended preset, degradation indicator and handoff | Task | 3 | web | `E46-D01` |

### 23.5 Design-track deliverables due

The design org is past D-S18 and is on **design-QA and defect support** (roadmap 1.2): no new screens, capacity reserved for GA polish.

| Key | Title | Est | Due |
|---|---|---|---|
| `E44-D04` | Design QA of the built live-gating surfaces against the hi-fi specs | 2 | 2027-02-18 |
| `E46-D01` | Design the completed engine diagnostics overlay and the compact latency indicator | 3 | 2027-02-18 |
| `E46-D02` | Design SCR-118 benchmark flow, recommended preset, degradation indicator and handoff | 3 | 2027-02-18 |

Design total: **8 pts** across 3 tickets.

### 23.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- sec: Independent pen-test (s08, S21-S21)
- sec: Pen-test remediation (s09, S21-S22)
- qa: Chaos catalogue (q08, S18-S23)

**QA tickets (22 pts, 6 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E43-Q04` | Rate-limit and auth denial-of-service load profiles | 3 | `E43-T04`, `E34` |
| `E43-Q05` | Accessibility audit of the security centre, key health and audit detail screens | 3 | `E43-S01`, `E43-S02`, `E43-D03` |
| `E44-Q01` | Author the live-gating black-box test plan and extend the E2E suite | 5 | `E44-S01`, `E44-S02`, `E44-S03`, `E44-S04` |
| `E44-Q02` | Prove environment isolation and run gating perf, load and chaos scenarios | 5 | `E44-T02`, `E44-T03`, `E44-T04` |
| `E44-Q03` | Accessibility audit, regression pack and QA sign-off for live gating | 3 | `E44-Q01`, `E44-D04` |
| `E45-Q01` | Author the black-box test plan for reconciliation, dead-man's-switch and drills | 3 | `E45-T01` |

**Security tickets (16 pts, 4 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E43-X02` | Commission and run the independent penetration test against the frozen build | 8 | `E43-X01`, `E43-X04`, `E43-X06`, `E43-T05`, `E43-T06`, `E43-T08`, `E43-K01`, `E43-S01` |
| `E43-X06` | Key-permission and RBAC-grant verification audit ahead of the pen-test | 3 | `E43-S02`, `E43-T09`, `E27` |
| `E44-X02` | Security review and abuse-case verification of the live gate and isolation | 3 | `E44-X01`, `E44-Q02`, `E44-Q01`, `E44-T04`, `E44-T05` |
| `E45-X01` | STRIDE threat model for reconciliation, chaos tooling and failover | 2 | `E29` |

### 23.7 Risks & dependency watch-list

- **Pen-test findings are certain; their content is not.** The 90-pt remediation reserve is deliberately unallocated - resist filling it with feature scope.
- E44 live gating completes here; it is the *only* mechanism that can enable live and it defaults OFF (roadmap 11.3 rule 3).
- Eng load held low (43 pts) on purpose. If the sprint looks 'underloaded' at planning, that is the plan working.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S21 |
|---|---|---|
| `E44-T03` | Sprint 20 | 5 |
| `E44-D03` | Sprint 19 | 4 |
| `E34` | epic E34 (whole epic must be Done) | 3 |
| `E43-S02` | Sprint 20 | 3 |
| `E44-T02` | Sprint 20 | 2 |
| `E44-T05` | Sprint 20 | 2 |
| `E29` | epic E29 (whole epic must be Done) | 2 |
| `E04` | epic E04 (whole epic must be Done) | 2 |
| `E45-T06` | Sprint 20 | 2 |
| `E43-T04` | Sprint 20 | 1 |
| `E43-D03` | Sprint 19 | 1 |
| `E43-D01` | Sprint 18 | 1 |
| _... 16 more_ | | |

### 23.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Pen-test findings presented and triaged live; reconciliation detects and reports an injected divergence.

**Exit expectation:** Remediation plan agreed, with Owner sign-off on any accepted risk.

### 23.9 Burn-up - R4 train

| Sprint | Eng pts this sprint | Cumulative R4 | R4 total | Remaining | % complete |
|---|---|---|---|---|---|
| S20 | 87 | 87 | 154 | 67 | 56% |
| S21 **<- this sprint** | 56 | 143 | 154 | 11 | 93% |
| S22 | 11 | 154 | 154 | 0 | 100% |

---

## 24. S22 - 2027-02-19 -> 2027-02-25 (R4)

### 24.1 Sprint goal(s)

- **Close R4 and cut `1.0.0`.** Reconciliation correctness and chaos/failover complete (E45).
- Pen-test remediation finishes (E43); **key-permission audit** runs in week 1 (2027-02-19).
- The Live-enablement gate is walked through under PRR - the only controlled live exception.

### 24.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 11 | 90 | +79 | ok |
| Design (D) | 2 | 60 | +58 | ok |
| QA (Q) | 9 | 45 | +36 | ok |
| Security (X) | 13 | 20 | +7 | ok |
| **Total** | **35** | **215** | **+180** | |

### 24.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E45** | Reconciliation, chaos & failover resilience | OMS & Execution (BE-OMS) | 19 | 6 |
| **E43** | Security hardening & pen-test remediation | Accounts & Security (BE-Sec) | 16 | 4 |


**Statechart lane:** none this sprint.

### 24.4 Tickets (10)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E43-Q06` | Execute the R4 security regression pack and record QA sign-off | Task | 3 | api | `E43-Q01`, `E43-Q03`, `E43-Q04`, `E43-Q05`, `E43-T11` |
| `E43-T11` | Build the security regression harness for pen-test findings | Task | 3 | api | `E43-X03` |
| `E43-X03` | Triage pen-test findings and file remediation tickets against the reserve | Task | 5 | cross-cutting | `E43-X02`, `E43-Q02` |
| `E43-X07` | Retest Critical and High findings and assemble the R4 evidence pack | Task | 5 | cross-cutting | `E43-X03`, `E43-T11`, `E43-T12`, `E43-Q06`, `E43-X06` |
| `E45-D03` | Design QA and accessibility review of the shipped reconciliation surfaces | Task | 2 | web | `E45-S01`, `E45-S02` |
| `E45-Q02` | Run the staging chaos game-day and exploratory charter | Task | 3 | api | `E45-Q01`, `E45-T07`, `E45-T08` |
| `E45-Q03` | Add the E2E suite, build the regression pack and record QA sign-off for E45 | Task | 3 | web | `E45-S01`, `E45-S02`, `E45-Q02` |
| `E45-S01` | Resolve untracked orders and position drift from the admin discrepancy view | Story | 5 | web | `E45-T03`, `E45-D02` |
| `E45-S02` | Surface reconciliation status and drill outcomes on SCR-143 and SCR-144 | Story | 3 | web | `E45-T03`, `E45-D02` |
| `E45-X02` | Security review, abuse-case testing and detection rules for E45 | Task | 3 | api | `E45-X01`, `E45-S01`, `E45-T05` |

### 24.5 Design-track deliverables due

The design org is past D-S18 and is on **design-QA and defect support** (roadmap 1.2): no new screens, capacity reserved for GA polish.

| Key | Title | Est | Due |
|---|---|---|---|
| `E45-D03` | Design QA and accessibility review of the shipped reconciliation surfaces | 2 | 2027-02-25 |

Design total: **2 pts** across 1 tickets.

### 24.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- sec: Pen-test remediation (s09, S21-S22)
- sec: Key-permission audit (s10, S22-S22)
- qa: Chaos catalogue (q08, S18-S23)

**QA tickets (9 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E43-Q06` | Execute the R4 security regression pack and record QA sign-off | 3 | `E43-Q01`, `E43-Q03`, `E43-Q04`, `E43-Q05`, `E43-T11` |
| `E45-Q02` | Run the staging chaos game-day and exploratory charter | 3 | `E45-Q01`, `E45-T07`, `E45-T08` |
| `E45-Q03` | Add the E2E suite, build the regression pack and record QA sign-off for E45 | 3 | `E45-S01`, `E45-S02`, `E45-Q02` |

**Security tickets (13 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E43-X03` | Triage pen-test findings and file remediation tickets against the reserve | 5 | `E43-X02`, `E43-Q02` |
| `E43-X07` | Retest Critical and High findings and assemble the R4 evidence pack | 5 | `E43-X03`, `E43-T11`, `E43-T12`, `E43-Q06`, `E43-X06` |
| `E45-X02` | Security review, abuse-case testing and detection rules for E45 | 3 | `E45-X01`, `E45-S01`, `E45-T05` |

### 24.7 Risks & dependency watch-list

- **R4 exit = Live-enablement gate 2027-02-25.** This is the highest-consequence gate in the plan.
- Key-permission audit (s10) closes 2027-02-21, a week before the gate - enough margin for one remediation cycle only.
- E45 reconciliation correctness is **never-cut**: a reconciliation bug at the Live gate is a stop-ship.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S22 |
|---|---|---|
| `E45-T03` | Sprint 21 | 2 |
| `E45-D02` | Sprint 20 | 2 |
| `E43-Q01` | Sprint 20 | 1 |
| `E43-Q03` | Sprint 20 | 1 |
| `E43-Q04` | Sprint 21 | 1 |
| `E43-Q05` | Sprint 21 | 1 |
| `E43-X02` | Sprint 21 | 1 |
| `E43-Q02` | Sprint 20 | 1 |
| `E43-T12` | Sprint 20 | 1 |
| `E43-X06` | Sprint 21 | 1 |
| `E45-Q01` | Sprint 21 | 1 |
| `E45-T07` | Sprint 21 | 1 |
| _... 3 more_ | | |

### 24.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** **Live-enablement gate walkthrough** - the one controlled exception where a demo touches prod (`07-release-and-prr.md` 6). Chaos suite passes: WS disconnect, exchange 5xx, rate-limit 10018.

**Exit expectation:** **R4 gate + Live-enablement gate 2027-02-25 - `1.0.0` to prod (live).**

### 24.9 Burn-up - R4 train

| Sprint | Eng pts this sprint | Cumulative R4 | R4 total | Remaining | % complete |
|---|---|---|---|---|---|
| S20 | 87 | 87 | 154 | 67 | 56% |
| S21 | 56 | 143 | 154 | 11 | 93% |
| S22 **<- this sprint** | 11 | 154 | 154 | 0 | 100% |

---

# R5 - Hardening / GA

| | |
|---|---|
| Sprints | S23-S26 |
| Dates | 2027-02-26 -> 2027-03-25 |
| Version at cut | `1.1.0` (GA) |
| Deploys to | prod (live) |
| Gate | PRR re-run + GA checklist |
| Eng pts in backlog | 202 of 360 capacity (56%) |
| All-discipline pts | 405 |

R5 is hardening only: performance budget enforcement, WCAG 2.2 AA conformance, chaos catalogue completion, documentation and runbooks, and the defect burn-down / design-QA sweep. No new product scope enters R5 except descoped ladder items explicitly moved here.

---

## 25. S23 - 2027-02-26 -> 2027-03-04 (R5)

### 25.1 Sprint goal(s)

- **Open R5.** Defect burn-down and design-QA sweep begin their four-sprint run (E49).
- Performance hardening against the budgets in `06-performance-and-load-standard.md` (E46).
- Accessibility conformance work (E47) runs on the design track; live ramp verification starts (QA q10).
- **Design is over pool: 66 pts vs 60 (+6).**

### 25.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 87 | 90 | +3 | ok |
| Design (D) | 66 | 60 | -6 | **OVER** |
| QA (Q) | 26 | 45 | +19 | ok |
| Security (X) | 9 | 20 | +11 | ok |
| **Total** | **188** | **215** | **+27** | |

### 25.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E47** | Accessibility conformance (WCAG 2.2 AA) | Design System | 93 | 27 |
| **E49** | Burn down defects and sweep design QA to a defensible GA bar | Cross-cutting defect & design-QA | 60 | 15 |
| **E46** | Performance hardening & budget enforcement | Chart Engine (FE-Engine) | 26 | 6 |
| **E48** | Documentation, runbooks & GA readiness | Governance & Docs | 9 | 3 |


**Statechart lane:** none this sprint.

### 25.4 Tickets (51)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E46-K01` | Spike: choose and prove the profiling toolchain for the R5 optimisation pass | Spike | 3 | cross-cutting | `E44`, `E45` |
| `E46-Q01` | Write the E46 performance test plan, harness scripts and regression pack | Task | 5 | cross-cutting | `E46-K01`, `E45`, `E03` |
| `E46-T01` | Emit machine-readable per-stage frame timings from the engine and the benchmark harness | Task | 5 | chart-engine | `E46-K01`, `E11`, `E04` |
| `E46-T04` | Profile the backend hot paths and add the WS tick-to-screen span breakdown | Task | 5 | api | `E46-K01`, `E04` |
| `E46-T05` | Optimise WS fan-out serialisation and binary framing against the 7ms emit budget | Task | 5 | api | `E46-T04` |
| `E46-X01` | STRIDE threat model for performance telemetry, diagnostics and profiling artefacts | Task | 3 | cross-cutting | `E46-K01`, `E43` |
| `E47-D01` | UX research: keyboard-only and screen-reader trading baseline study | Task | 3 | web | `E44` |
| `E47-D02` | Accessibility design audit of all screens: annotated findings catalogue | Task | 5 | web | `E47-D01` |
| `E47-D03` | High-contrast and colour-vision-safe theme design (SCR-116) | Task | 5 | web | `E47-D02` |
| `E47-D04` | Focus order, focus visibility and landmark model spec | Task | 3 | web | `E47-D02` |
| `E47-D05` | Accessibility settings hi-fi (SCR-117) incl. preference previews | Task | 3 | web | `E47-D03`, `E47-D04` |
| `E47-D06` | Canvas accessibility design: DOM mirror, surrogates and table alternatives | Task | 5 | web | `E47-D02`, `E47-D04` |
| `E47-D07` | Live-region announcement design: content, politeness and throttling | Task | 5 | web | `E47-D05`, `E47-D06` |
| `E47-D08` | Motion design: reduced-motion variants and flash-rate safety | Task | 3 | web | `E47-D03`, `E47-D05` |
| `E47-D09` | Keyboard operability design: cheatsheet, command palette and drag alternatives | Task | 3 | web | `E47-D04` |
| `E47-D10` | Design-system contribution: a11y primitives, patterns and Storybook a11y stories | Task | 5 | web | `E47-D03`, `E47-D04`, `E47-D07`, `E47-D08` |
| `E47-D11` | Handoff pack: a11y remediation specs, redlines and acceptance checklists | Task | 3 | web | `E47-D06`, `E47-D09`, `E47-D10` |
| `E47-D13` | Accessibility statement and VPAT-shaped conformance report design | Task | 3 | web | `E47-D02` |
| `E47-D14` | Standing a11y design-review gate for all new and changed UI | Task | 2 | web | `E47-D10` |
| `E47-K01` | Spike: audit methodology, tooling and screen-reader harness baseline | Spike | 2 | web |  |
| `E47-Q01` | Black-box accessibility test plan for the E47 remediation story groups | Task | 5 | web | `E47-D01`, `E47-D02` |
| `E47-Q04` | axe-core, pa11y and Lighthouse CI gates with a violation burn-down dashboard | Task | 3 | web | `E47-Q01` |
| `E47-S01` | Chart canvas surrogate and table alternative reach AA (SCR-030, SCR-045) | Story | 5 | chart-engine | `E47-T01` |
| `E47-S03` | Rule form and node-graph editors keyboard/screen-reader operable | Story | 3 | scripting | `E47-T01` |
| `E47-S04` | Reduced-motion coverage and the three-flashes-per-second ceiling | Story | 3 | web | `E47-S07` |
| `E47-S05` | Focus order, focus visibility, target size and drag alternatives | Story | 3 | web | `E47-T01` |
| `E47-S06` | High-contrast and CVD-safe themes across every order-flow encoding | Story | 3 | web | `E47-T03` |
| `E47-S07` | Accessibility preferences applied everywhere incl. WebGL (SCR-117) | Story | 3 | web |  |
| `E47-S08` | Settings, hotkey layer and destructive-confirm keyboard conformance | Story | 3 | web | `E47-T01` |
| `E47-T01` | Full WCAG 2.2 AA sweep of SCR-001..SCR-159 into a findings register | Task | 3 | web | `E47-K01`, `E47-T02` |
| `E47-T02` | Promote the six accessibility CI gates to required checks | Task | 3 | infra |  |
| `E47-T03` | Contrast and colour-vision validation matrix for every theme and data-ink token | Task | 3 | web |  |
| `E47-X01` | STRIDE threat model for a11y surfaces: mirrors, live regions, preferences | Task | 3 | web | `E47-D01`, `E47-D02` |
| `E48-D01` | Design the Help & about surface and the user-guide information architecture | Task | 5 | web | `E42`, `E10` |
| `E48-K01` | Spike: choose the documentation toolchain and reference-generation pipeline | Spike | 1 | docs |  |
| `E48-T01` | Reconcile architecture, schema and ADR documents with the system as built | Task | 3 | docs | `E46`, `E45`, `E44` |
| `E49-D01` | Author the design-QA audit protocol and open the per-screen findings ledger | Task | 5 | web | `E47` |
| `E49-D02` | Specify the unified empty, loading and error state patterns for the GA sweep | Task | 3 | web | `E49-D01` |
| `E49-D03` | Write the GA copy and terminology specification for every user-visible string | Task | 3 | web | `E49-D02` |
| `E49-D04` | Sweep motion and reduced-motion behaviour across every animated surface | Task | 2 | web | `E49-D02` |
| `E49-K01` | Spike: cluster the accumulated defect backlog by root cause to plan the waves | Spike | 2 | cross-cutting | `E49-T01` |
| `E49-Q01` | Assemble and automate the GA regression pack across web and Electron | Task | 8 | web | `E49-T01` |
| `E49-Q02` | Run exploratory charters and two cross-team bug bashes on the GA candidate | Task | 5 | cross-cutting | `E49-T01` |
| `E49-S01` | Burn down wave 1: close every open P0 and the highest-impact P1 clusters | Story | 8 | cross-cutting | `E49-K01` |
| `E49-S02` | Burn down wave 2: close the remaining P1 backlog and its root-cause clusters | Story | 8 | cross-cutting | `E49-S01`, `E49-Q02` |
| `E49-S07` | Resolve hotkey conflicts and make invalid-context bindings explain themselves | Story | 3 | web | `E49-T04` |
| `E49-T01` | Build the GA defect triage queue with enforced fields and SLA automation | Task | 3 | infra |  |
| `E49-T02` | Publish the defect burn-down and ageing dashboard against the GA target line | Task | 2 | infra | `E49-T01` |
| `E49-T03` | Re-review every accepted risk and enforce expiry dates before GA | Task | 3 | docs | `E49-T02` |
| `E49-T04` | Add a CI lint that proves the keymap is conflict-free in every context | Task | 2 | web |  |
| `E49-X01` | STRIDE-model the defect-fix and hotfix path and write its abuse cases | Task | 3 | cross-cutting |  |

### 25.5 Design-track deliverables due

The design org is past D-S18 and is on **design-QA and defect support** (roadmap 1.2): no new screens, capacity reserved for GA polish.

| Key | Title | Est | Due |
|---|---|---|---|
| `E47-D01` | UX research: keyboard-only and screen-reader trading baseline study | 3 | 2027-03-04 |
| `E47-D02` | Accessibility design audit of all screens: annotated findings catalogue | 5 | 2027-03-04 |
| `E47-D03` | High-contrast and colour-vision-safe theme design (SCR-116) | 5 | 2027-03-04 |
| `E47-D04` | Focus order, focus visibility and landmark model spec | 3 | 2027-03-04 |
| `E47-D05` | Accessibility settings hi-fi (SCR-117) incl. preference previews | 3 | 2027-03-04 |
| `E47-D06` | Canvas accessibility design: DOM mirror, surrogates and table alternatives | 5 | 2027-03-04 |
| `E47-D07` | Live-region announcement design: content, politeness and throttling | 5 | 2027-03-04 |
| `E47-D08` | Motion design: reduced-motion variants and flash-rate safety | 3 | 2027-03-04 |
| `E47-D09` | Keyboard operability design: cheatsheet, command palette and drag alternatives | 3 | 2027-03-04 |
| `E47-D10` | Design-system contribution: a11y primitives, patterns and Storybook a11y stories | 5 | 2027-03-04 |
| `E47-D11` | Handoff pack: a11y remediation specs, redlines and acceptance checklists | 3 | 2027-03-04 |
| `E47-D13` | Accessibility statement and VPAT-shaped conformance report design | 3 | 2027-03-04 |
| `E47-D14` | Standing a11y design-review gate for all new and changed UI | 2 | 2027-03-04 |
| `E48-D01` | Design the Help & about surface and the user-guide information architecture | 5 | 2027-03-04 |
| `E49-D01` | Author the design-QA audit protocol and open the per-screen findings ledger | 5 | 2027-03-04 |
| `E49-D02` | Specify the unified empty, loading and error state patterns for the GA sweep | 3 | 2027-03-04 |
| `E49-D03` | Write the GA copy and terminology specification for every user-visible string | 3 | 2027-03-04 |
| `E49-D04` | Sweep motion and reduced-motion behaviour across every animated surface | 2 | 2027-03-04 |

Design total: **66 pts** across 18 tickets.

### 25.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Chaos catalogue (q08, S18-S23)
- qa: Live ramp verification (q10, S23-S24)

**QA tickets (26 pts, 5 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E46-Q01` | Write the E46 performance test plan, harness scripts and regression pack | 5 | `E46-K01`, `E45`, `E03` |
| `E47-Q01` | Black-box accessibility test plan for the E47 remediation story groups | 5 | `E47-D01`, `E47-D02` |
| `E47-Q04` | axe-core, pa11y and Lighthouse CI gates with a violation burn-down dashboard | 3 | `E47-Q01` |
| `E49-Q01` | Assemble and automate the GA regression pack across web and Electron | 8 | `E49-T01` |
| `E49-Q02` | Run exploratory charters and two cross-team bug bashes on the GA candidate | 5 | `E49-T01` |

**Security tickets (9 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E46-X01` | STRIDE threat model for performance telemetry, diagnostics and profiling artefacts | 3 | `E46-K01`, `E43` |
| `E47-X01` | STRIDE threat model for a11y surfaces: mirrors, live regions, preferences | 3 | `E47-D01`, `E47-D02` |
| `E49-X01` | STRIDE-model the defect-fix and hotfix path and write its abuse cases | 3 |  |

### 25.7 Risks & dependency watch-list

- Live ramp verification (q10) begins - first real-money exposure, tightly bounded.
- E49 defect burn-down (44 pts) is sized from the 140-pt R5 reserve; if R4 spilled, this is where it shows.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S23 |
|---|---|---|
| `E44` | epic E44 (whole epic must be Done) | 3 |
| `E45` | epic E45 (whole epic must be Done) | 3 |
| `E04` | epic E04 (whole epic must be Done) | 2 |
| `E03` | epic E03 (whole epic must be Done) | 1 |
| `E11` | epic E11 (whole epic must be Done) | 1 |
| `E43` | epic E43 (whole epic must be Done) | 1 |
| `E42` | epic E42 (whole epic must be Done) | 1 |
| `E10` | epic E10 (whole epic must be Done) | 1 |
| `E46` | epic E46 (whole epic must be Done) | 1 |
| `E47` | epic E47 (whole epic must be Done) | 1 |

### 25.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Performance budgets met under load; live ramp verification shows controlled, bounded real-money exposure.

**Exit expectation:** Defect burn-down trend published and trending down.

### 25.9 Burn-up - R5 train

| Sprint | Eng pts this sprint | Cumulative R5 | R5 total | Remaining | % complete |
|---|---|---|---|---|---|
| S23 **<- this sprint** | 87 | 87 | 202 | 115 | 43% |
| S24 | 62 | 149 | 202 | 53 | 74% |
| S25 | 48 | 197 | 202 | 5 | 98% |
| S26 | 5 | 202 | 202 | 0 | 100% |

---

## 26. S24 - 2027-03-05 -> 2027-03-11 (R5)

### 26.1 Sprint goal(s)

- Performance hardening continues (E46) - engine FPS, WS fan-out, ingestion soak.
- Defect burn-down continues (E49). Lightest sprint of R5 by design: it is the shock absorber for R4 spillover.

### 26.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 62 | 90 | +28 | ok |
| Design (D) | 0 | 60 | +60 | ok |
| QA (Q) | 20 | 45 | +25 | ok |
| Security (X) | 5 | 20 | +15 | ok |
| **Total** | **87** | **215** | **+128** | |

### 26.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E46** | Performance hardening & budget enforcement | Chart Engine (FE-Engine) | 44 | 10 |
| **E47** | Accessibility conformance (WCAG 2.2 AA) | Design System | 30 | 7 |
| **E49** | Burn down defects and sweep design QA to a defensible GA bar | Cross-cutting defect & design-QA | 13 | 2 |


**Statechart lane:** none this sprint.

### 26.4 Tickets (19)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E46-S01` | Complete the SCR-046 engine diagnostics overlay with the stage table and WS-to-pixel latency | Story | 5 | web | `E46-D01`, `E46-T01`, `E46-T04`, `E11`, `E04` |
| `E46-S02` | Add the SCR-118 benchmark action and the recommended-for-this-machine performance preset | Story | 5 | web | `E46-D02`, `E46-T01`, `E46-T09`, `E11` |
| `E46-T02` | Optimise the footprint cell text path against its 4ms frame slice | Task | 5 | chart-engine | `E46-T01`, `E18` |
| `E46-T03` | Profile and tune the DOM heatmap texture upload path under real ring-wrap conditions | Task | 3 | chart-engine | `E46-T01`, `E21` |
| `E46-T06` | Hunt and fix frontend memory leaks against the 1.5GB workspace ceiling | Task | 5 | chart-engine | `E46-T02`, `E46-T03` |
| `E46-T07` | Bring backend per-symbol CPU and memory inside the 0.5 vCPU and 300MB ceilings | Task | 5 | api | `E46-T04` |
| `E46-T08` | Tune QuestDB replay-scan queries and the engine_metrics write path | Task | 3 | infra | `E46-T04`, `E26` |
| `E46-T09` | Build the startup and workspace-restore harness and hit the 3s cold-start budget | Task | 3 | web | `E46-T01` |
| `E46-T10` | Promote every hard budget to a CI-enforced required check with regression alarms | Task | 8 | infra | `E46-T02`, `E46-T03`, `E46-T05`, `E46-T07`, `E46-T08`, `E46-T09` |
| `E46-T11` | Write ADR-0016 on budget enforcement and seed the perf-incidents log | Task | 2 | docs | `E46-T10`, `E46-K01` |
| `E47-Q02` | Manual screen-reader passes across the NVDA, JAWS and VoiceOver matrix | Task | 5 | web | `E47-Q01`, `E47-S01`, `E47-S02` |
| `E47-Q03` | Keyboard-only Playwright E2E suite and accessibility-tree snapshot regression | Task | 5 | web | `E47-Q01`, `E47-S01` |
| `E47-Q05` | Motion/flash audit script and accessibility-overhead performance benchmarks | Task | 5 | web | `E47-Q01`, `E47-S04` |
| `E47-S02` | Footprint, DOM ladder and heatmap grids reach AA keyboard-only | Story | 5 | chart-engine | `E47-T01` |
| `E47-T04` | Screen-reader scripts and pinned-matrix sign-off passes (NVDA, JAWS, VoiceOver) | Task | 3 | web | `E47-K01`, `E47-S01`, `E47-S02`, `E47-S03` |
| `E47-T05` | Publish the VPAT-shaped conformance report and the exception register | Task | 2 | docs | `E47-T04`, `E47-S04`, `E47-S05`, `E47-S06`, `E47-S08` |
| `E47-X02` | Abuse cases: accessible-surface leakage, hotkey tampering, announcement DoS | Task | 5 | web | `E47-X01`, `E47-Q03` |
| `E49-Q04` | Author the black-box state-matrix test plan for every panel and failure mode | Task | 5 | web | `E49-D02` |
| `E49-S03` | Burn down wave 3: bring open P2s to the GA bar and triage every P3 | Story | 8 | cross-cutting | `E49-S02` |

### 26.5 Design-track deliverables due

The design org is past D-S18 and is on **design-QA and defect support** (roadmap 1.2): no new screens, capacity reserved for GA polish.

No design tickets are scheduled in this sprint.

### 26.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- qa: Live ramp verification (q10, S23-S24)

**QA tickets (20 pts, 4 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E47-Q02` | Manual screen-reader passes across the NVDA, JAWS and VoiceOver matrix | 5 | `E47-Q01`, `E47-S01`, `E47-S02` |
| `E47-Q03` | Keyboard-only Playwright E2E suite and accessibility-tree snapshot regression | 5 | `E47-Q01`, `E47-S01` |
| `E47-Q05` | Motion/flash audit script and accessibility-overhead performance benchmarks | 5 | `E47-Q01`, `E47-S04` |
| `E49-Q04` | Author the black-box state-matrix test plan for every panel and failure mode | 5 | `E49-D02` |

**Security tickets (5 pts, 1 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E47-X02` | Abuse cases: accessible-surface leakage, hotkey tampering, announcement DoS | 5 | `E47-X01`, `E47-Q03` |

### 26.7 Risks & dependency watch-list

- Lightest R5 sprint (41 eng pts) - deliberately reserved as the shock absorber for R4 spillover and live-ramp findings.
- Zero design and zero security points planned. If either discipline has open work, it is unplanned and needs surfacing.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S24 |
|---|---|---|
| `E46-T01` | Sprint 23 | 5 |
| `E46-T04` | Sprint 23 | 3 |
| `E47-Q01` | Sprint 23 | 3 |
| `E47-S01` | Sprint 23 | 3 |
| `E11` | epic E11 (whole epic must be Done) | 2 |
| `E47-S04` | Sprint 23 | 2 |
| `E46-D01` | Sprint 21 | 1 |
| `E04` | epic E04 (whole epic must be Done) | 1 |
| `E46-D02` | Sprint 21 | 1 |
| `E18` | epic E18 (whole epic must be Done) | 1 |
| `E21` | epic E21 (whole epic must be Done) | 1 |
| `E26` | epic E26 (whole epic must be Done) | 1 |
| _... 11 more_ | | |

### 26.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Engine FPS, WS fan-out and ingestion soak all within budget on production-shaped load.

**Exit expectation:** No demo gate; progress review only.

### 26.9 Burn-up - R5 train

| Sprint | Eng pts this sprint | Cumulative R5 | R5 total | Remaining | % complete |
|---|---|---|---|---|---|
| S23 | 87 | 87 | 202 | 115 | 43% |
| S24 **<- this sprint** | 62 | 149 | 202 | 53 | 74% |
| S25 | 48 | 197 | 202 | 5 | 98% |
| S26 | 5 | 202 | 202 | 0 | 100% |

---

## 27. S25 - 2027-03-12 -> 2027-03-18 (R5)

### 27.1 Sprint goal(s)

- Documentation, runbooks and GA readiness ramp up (E48).
- Performance hardening completes (E46); defect burn-down peaks (E49).
- **GA regression + 72h soak starts in week 2** (2027-03-16); final security sweep runs.

### 27.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 48 | 90 | +42 | ok |
| Design (D) | 5 | 60 | +55 | ok |
| QA (Q) | 30 | 45 | +15 | ok |
| Security (X) | 9 | 20 | +11 | ok |
| **Total** | **92** | **215** | **+123** | |

### 27.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E48** | Documentation, runbooks & GA readiness | Governance & Docs | 33 | 9 |
| **E49** | Burn down defects and sweep design QA to a defensible GA bar | Cross-cutting defect & design-QA | 21 | 4 |
| **E46** | Performance hardening & budget enforcement | Chart Engine (FE-Engine) | 19 | 4 |
| **E47** | Accessibility conformance (WCAG 2.2 AA) | Design System | 19 | 6 |


**Statechart lane:** none this sprint.

### 27.4 Tickets (23)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E46-Q02` | Execute the 72-hour soak and the full-capacity composite load scenario on the GA candidate | Task | 8 | cross-cutting | `E46-Q01`, `E46-T06`, `E46-T07`, `E46-T10` |
| `E46-Q03` | Run the exploratory performance charter, degradation-ladder verification and a11y audit of SCR-046/SCR-118 | Task | 5 | cross-cutting | `E46-Q01`, `E46-S01`, `E46-S02` |
| `E46-Q04` | Assemble the GA performance evidence pack and give epic-level QA sign-off | Task | 3 | cross-cutting | `E46-Q02`, `E46-Q03`, `E46-T10`, `E46-T11`, `E46-X02` |
| `E46-X02` | Security review, abuse cases and SAST rules for the E46 telemetry and benchmark surface | Task | 3 | cross-cutting | `E46-X01`, `E46-S01`, `E46-S02`, `E46-T01`, `E46-T04`, `E46-T10` |
| `E47-D12` | Design QA of a11y remediation across all screens | Task | 5 | web | `E47-D11` |
| `E47-K02` | ADR and operator docs for the accessible-surface parity and evidence model | Chore | 2 | docs | `E47-X01`, `E47-Q08` |
| `E47-Q06` | Chaos scenarios: accessibility of degraded, disconnected and error states | Task | 3 | web | `E47-Q03`, `E47-S03` |
| `E47-Q07` | Exploratory accessibility charters with assistive-technology users | Task | 3 | web | `E47-Q02` |
| `E47-Q08` | Accessibility regression pack and cross-epic guardrails for future screens | Task | 3 | web | `E47-Q03`, `E47-Q04`, `E47-Q06` |
| `E47-X03` | SAST/DAST rules and CI guards for accessible-surface data parity | Task | 3 | web | `E47-X01`, `E47-X02` |
| `E48-Q01` | Author the documentation-accuracy test plan, charter and E2E additions | Task | 5 | docs | `E48-T02`, `E48-D01` |
| `E48-S01` | Ship the persona user guide and the Help & about screen with diagnostics | Story | 5 | web | `E48-D01`, `E48-T02` |
| `E48-S02` | Add the keyboard cheatsheet, glossary, methodology link and tour restart | Story | 3 | web | `E48-S01` |
| `E48-T02` | Build the documentation site with a generated, drift-proof API and WS reference | Task | 5 | docs | `E48-K01`, `E48-T01`, `E48-X01` |
| `E48-T03` | Author the operations runbook set for every PRR procedure and failure mode | Task | 5 | docs | `E45`, `E44`, `E42`, `E48-T02` |
| `E48-T04` | Write and execute the disaster-recovery playbook with measured RTO and RPO | Task | 3 | infra | `E48-T03`, `E45` |
| `E48-T05` | Write the engineer onboarding guide and prove it on a clean machine | Task | 2 | docs | `E48-T01`, `E48-T02` |
| `E48-T07` | Finalise the changelog and publish GA release notes in What's New | Task | 2 | web | `E48-S01` |
| `E48-X01` | STRIDE threat model for the documentation, diagnostics and GA-evidence surface | Task | 3 | docs |  |
| `E49-S04` | Remediate design-QA findings across the screens catalogue against the specs | Story | 8 | web | `E49-D01`, `E49-D04` |
| `E49-S05` | Bring every empty, loading and error surface into state-pattern conformance | Story | 8 | web | `E49-D02`, `E49-Q04` |
| `E49-S06` | Apply the GA copy and terminology fixes across every user-visible string | Story | 3 | web | `E49-D03`, `E49-S05` |
| `E49-T05` | Reconcile plan docs with shipped behaviour and write the defect-disposition ADR | Task | 2 | docs | `E49-S03`, `E49-S05`, `E49-S06` |

### 27.5 Design-track deliverables due

The design org is past D-S18 and is on **design-QA and defect support** (roadmap 1.2): no new screens, capacity reserved for GA polish.

| Key | Title | Est | Due |
|---|---|---|---|
| `E47-D12` | Design QA of a11y remediation across all screens | 5 | 2027-03-18 |

Design total: **5 pts** across 1 tickets.

### 27.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: DAST full scans (quarterly) (s06, S08-S25)
- sec: Final security sweep (s11, S25-S26)
- qa: GA regression + 72h soak (q11, S25-S26)

**QA tickets (30 pts, 7 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E46-Q02` | Execute the 72-hour soak and the full-capacity composite load scenario on the GA candidate | 8 | `E46-Q01`, `E46-T06`, `E46-T07`, `E46-T10` |
| `E46-Q03` | Run the exploratory performance charter, degradation-ladder verification and a11y audit of SCR-046/SCR-118 | 5 | `E46-Q01`, `E46-S01`, `E46-S02` |
| `E46-Q04` | Assemble the GA performance evidence pack and give epic-level QA sign-off | 3 | `E46-Q02`, `E46-Q03`, `E46-T10`, `E46-T11`, `E46-X02` |
| `E47-Q06` | Chaos scenarios: accessibility of degraded, disconnected and error states | 3 | `E47-Q03`, `E47-S03` |
| `E47-Q07` | Exploratory accessibility charters with assistive-technology users | 3 | `E47-Q02` |
| `E47-Q08` | Accessibility regression pack and cross-epic guardrails for future screens | 3 | `E47-Q03`, `E47-Q04`, `E47-Q06` |
| `E48-Q01` | Author the documentation-accuracy test plan, charter and E2E additions | 5 | `E48-T02`, `E48-D01` |

**Security tickets (9 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E46-X02` | Security review, abuse cases and SAST rules for the E46 telemetry and benchmark surface | 3 | `E46-X01`, `E46-S01`, `E46-S02`, `E46-T01`, `E46-T04`, `E46-T10` |
| `E47-X03` | SAST/DAST rules and CI guards for accessible-surface data parity | 3 | `E47-X01`, `E47-X02` |
| `E48-X01` | STRIDE threat model for the documentation, diagnostics and GA-evidence surface | 3 |  |

### 27.7 Risks & dependency watch-list

- **GA regression + 72h soak starts 2027-03-16 (week 2).** A soak failure here has only one sprint of recovery.
- E48 docs at 30 pts plus E49 at 33 and E46 at 29 - 65 eng pts across three epics closing simultaneously.
- Final security sweep (s11) runs S25-S26; findings at this point are GA-blocking by definition.

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S25 |
|---|---|---|
| `E46-T10` | Sprint 24 | 3 |
| `E46-Q01` | Sprint 23 | 2 |
| `E46-S01` | Sprint 24 | 2 |
| `E46-S02` | Sprint 24 | 2 |
| `E47-X01` | Sprint 23 | 2 |
| `E47-Q03` | Sprint 24 | 2 |
| `E48-D01` | Sprint 23 | 2 |
| `E48-T01` | Sprint 23 | 2 |
| `E45` | epic E45 (whole epic must be Done) | 2 |
| `E46-T06` | Sprint 24 | 1 |
| `E46-T07` | Sprint 24 | 1 |
| `E46-T11` | Sprint 24 | 1 |
| _... 17 more_ | | |

### 27.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** Runbooks exercised by someone who did not write them; GA regression suite green; 72h soak running.

**Exit expectation:** Final security sweep findings triaged to zero GA-blockers.

### 27.9 Burn-up - R5 train

| Sprint | Eng pts this sprint | Cumulative R5 | R5 total | Remaining | % complete |
|---|---|---|---|---|---|
| S23 | 87 | 87 | 202 | 115 | 43% |
| S24 | 62 | 149 | 202 | 53 | 74% |
| S25 **<- this sprint** | 48 | 197 | 202 | 5 | 98% |
| S26 | 5 | 202 | 202 | 0 | 100% |

---

## 28. S26 - 2027-03-19 -> 2027-03-25 (R5)

### 28.1 Sprint goal(s)

- **GA cut 2027-03-25 - `1.1.0`.** Docs and runbooks complete (E48); final defect sweep (E49).
- GA regression and 72h soak close on the cut date. PRR re-run + GA checklist is the exit.

### 28.2 Capacity by discipline vs planned points

| Discipline | Planned | Capacity | Headroom | Status |
|---|---|---|---|---|
| Engineering (S/T/K/C) | 5 | 90 | +85 | ok |
| Design (D) | 6 | 60 | +54 | ok |
| QA (Q) | 16 | 45 | +29 | ok |
| Security (X) | 11 | 20 | +9 | ok |
| **Total** | **38** | **215** | **+177** | |

### 28.3 Epic mix

| Epic | Title | Lane | Pts | Tickets |
|---|---|---|---|---|
| **E48** | Documentation, runbooks & GA readiness | Governance & Docs | 19 | 4 |
| **E49** | Burn down defects and sweep design QA to a defensible GA bar | Cross-cutting defect & design-QA | 13 | 3 |
| **E47** | Accessibility conformance (WCAG 2.2 AA) | Design System | 6 | 2 |


**Statechart lane:** none this sprint.

### 28.4 Tickets (9)

| Key | Title | Kind | Est | Component | blocked_by |
|---|---|---|---|---|---|
| `E47-Q09` | E47 QA sign-off: conformance evidence rollup and R5 GA a11y gate input | Task | 3 | web | `E47-Q02`, `E47-Q04`, `E47-Q05`, `E47-Q06`, `E47-Q07`, `E47-Q08`, `E47-D03` |
| `E47-X04` | Security review and sign-off for the E47 accessibility surface | Task | 3 | web | `E47-X02`, `E47-X03`, `E47-S04` |
| `E48-D02` | Design QA and a11y review of the Help, guide and release-notes surfaces | Task | 3 | web | `E48-S02`, `E48-T07` |
| `E48-Q02` | Execute the runbook rehearsals, GA documentation regression and epic QA sign-off | Task | 8 | docs | `E48-Q01`, `E48-T03`, `E48-T04`, `E48-S02` |
| `E48-T06` | Execute the GA release and PRR checklists and assemble the v1.1.0 evidence pack | Task | 5 | docs | `E48-T02`, `E48-T04`, `E48-T05`, `E48-T07`, `E48-X02`, `E46`, `E47`, `E49` |
| `E48-X02` | Security review, leakage abuse cases and scanning rules for E48 docs | Task | 3 | docs | `E48-X01`, `E48-S01`, `E48-T03`, `E48-T04` |
| `E49-D05` | Run the final design QA over the GA candidate and record design sign-off | Task | 3 | web | `E49-D01`, `E49-S04`, `E49-S05`, `E49-S06` |
| `E49-Q03` | Verify accessibility non-regression and record the epic-level QA sign-off for GA | Task | 5 | web | `E49-Q01`, `E49-S03`, `E49-S05` |
| `E49-X02` | Verify the abuse cases and run the GA security scan sweep on the candidate | Task | 5 | cross-cutting | `E49-X01`, `E49-S02`, `E49-S03` |

### 28.5 Design-track deliverables due

The design org is past D-S18 and is on **design-QA and defect support** (roadmap 1.2): no new screens, capacity reserved for GA polish.

| Key | Title | Est | Due |
|---|---|---|---|
| `E48-D02` | Design QA and a11y review of the Help, guide and release-notes surfaces | 3 | 2027-03-25 |
| `E49-D05` | Run the final design QA over the GA candidate and record design sign-off | 3 | 2027-03-25 |

Design total: **6 pts** across 2 tickets.

### 28.6 QA & security items

**Continuous track bars active this sprint** (roadmap 10.1):

- sec: SAST/SCA/secrets continuous (s02, S01-S26)
- sec: Final security sweep (s11, S25-S26)
- qa: GA regression + 72h soak (q11, S25-S26)

**QA tickets (16 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E47-Q09` | E47 QA sign-off: conformance evidence rollup and R5 GA a11y gate input | 3 | `E47-Q02`, `E47-Q04`, `E47-Q05`, `E47-Q06`, `E47-Q07`, `E47-Q08`, `E47-D03` |
| `E48-Q02` | Execute the runbook rehearsals, GA documentation regression and epic QA sign-off | 8 | `E48-Q01`, `E48-T03`, `E48-T04`, `E48-S02` |
| `E49-Q03` | Verify accessibility non-regression and record the epic-level QA sign-off for GA | 5 | `E49-Q01`, `E49-S03`, `E49-S05` |

**Security tickets (11 pts, 3 tickets):**

| Key | Title | Est | blocked_by |
|---|---|---|---|
| `E47-X04` | Security review and sign-off for the E47 accessibility surface | 3 | `E47-X02`, `E47-X03`, `E47-S04` |
| `E48-X02` | Security review, leakage abuse cases and scanning rules for E48 docs | 3 | `E48-X01`, `E48-S01`, `E48-T03`, `E48-T04` |
| `E49-X02` | Verify the abuse cases and run the GA security scan sweep on the candidate | 5 | `E49-X01`, `E49-S02`, `E49-S03` |

### 28.7 Risks & dependency watch-list

- **GA cut 2027-03-25.** No scope may be added. Only defect fixes with a named GA-blocking justification.
- E48 must land the runbooks - an un-runbooked production system fails the GA checklist regardless of code quality.
- Unused reserve converts to post-GA backlog, never to an earlier date claim (roadmap 3.1).

**External `blocked_by` entering this sprint** (must be Done before the dependent ticket starts):

| Blocker | Where it lives | Dependents in S26 |
|---|---|---|
| `E48-T04` | Sprint 25 | 3 |
| `E48-S02` | Sprint 25 | 2 |
| `E48-T07` | Sprint 25 | 2 |
| `E48-T03` | Sprint 25 | 2 |
| `E49-S05` | Sprint 25 | 2 |
| `E49-S03` | Sprint 24 | 2 |
| `E47-Q02` | Sprint 24 | 1 |
| `E47-Q04` | Sprint 23 | 1 |
| `E47-Q05` | Sprint 24 | 1 |
| `E47-Q06` | Sprint 25 | 1 |
| `E47-Q07` | Sprint 25 | 1 |
| `E47-Q08` | Sprint 25 | 1 |
| _... 18 more_ | | |

### 28.8 Demo & exit expectations

**Sprint Review demo (on staging/demo, never live):** **GA walkthrough against the GA checklist.** Every exit criterion of every train re-evidenced.

**Exit expectation:** **R5 / GA gate 2027-03-25 - `1.1.0` (GA).** PRR re-run + GA checklist complete.

### 28.9 Burn-up - R5 train

| Sprint | Eng pts this sprint | Cumulative R5 | R5 total | Remaining | % complete |
|---|---|---|---|---|---|
| S23 | 87 | 87 | 202 | 115 | 43% |
| S24 | 62 | 149 | 202 | 53 | 74% |
| S25 | 48 | 197 | 202 | 5 | 98% |
| S26 **<- this sprint** | 5 | 202 | 202 | 0 | 100% |

---

# 29. Parallel-work lanes

## 29.1 The lane model

A **lane** is a standing team that owns a set of epics which touch a disjoint set of modules. Two lanes may run in the same sprint without coordination overhead only if their module sets do not intersect. Where they do intersect, the intersection is named explicitly below and needs a written interface-first contract merged *before* both lanes start (DoR: "the interface-first contract is already merged or is itself a prerequisite Task marked `blocked_by`").

| Lane | Owns epics | Primary modules / areas | Typical staffing |
|---|---|---|---|
| **Accounts & Security (BE-Sec)** | E09, E27, E42, E43, E44 | `area/auth-rbac`, `area/accounts-admin`; M2, M13, M18, M19, M21 | 1-2 BE + Security engineer |
| **App & Charting UI (FE-App)** | E10, E13, E14, E15, E30, E31, E36, E37, E41 | `area/charting-ui`, `area/electron-shell`, `area/journal-analytics`; M9 (read), M20 | 2-3 FE |
| **Chart Engine (FE-Engine)** | E06, E11, E46 | `area/chart-engine`; the WebGL render package (no backend modules) | chart-engine lead + 2 FE |
| **Cross-cutting defect & design-QA** | E49 | all | whole team, rotating |
| **Data & Feeds (BE-Feeds)** | E07, E08, E12, E16, E17, E26 | `area/ingestion`, `area/recorder-replay`; M3-M8, M10-M12, M23 | 2 BE |
| **Design System** | E05, E47 | `area/design-system`; `packages/design-system`, Storybook | DS team + a11y specialist |
| **Governance & Docs** | E01, E48 | `area/docs`; repo root, `.github/` | Architect + tech writer (part-time) |
| **OMS & Execution (BE-OMS)** | E28, E29, E32, E33, E34, E38, E39, E45 | `area/oms-execution`, `area/paper-trading`; M14, M16, M17 | 2-3 BE |
| **Order Flow (BE-Flow + FE-Engine)** | E18, E19, E20, E21, E22, E23, E24, E25 | `area/order-flow`; M7, M9 + engine render passes | 2 BE + 1 FE (shared with engine lane) |
| **Platform & DevSecOps** | E02, E03, E04 | `area/backend-platform`, `area/infra-devops`, `area/frontend-platform`; M1, M24 | 1 BE + DevSecOps |
| **Rules & Alerts (BE-Rules)** | E35, E40 | `area/rule-engine`; M15, M22 | 1-2 BE + 1 FE |

Every epic in the register belongs to exactly one lane; no epic is unassigned.

## 29.2 Known lane collisions (the ones that actually bite)

| Sprints | Lanes | Shared surface | Rule |
|---|---|---|---|
| S10-S12 | Order Flow vs Chart Engine | the engine **render hot path** - E18 footprint and E21 heatmap both add draw passes | Separate render passes with an agreed pass-ordering contract merged in S09. Neither lane edits the other's pass. The benchmark harness gates every PR so a regression is attributed same-day. |
| S12-S13 | Order Flow vs OMS & Accounts | E27/E29 start *inside* R2 while R2 is still finishing | E27/E29 draw from the **R3** budget, not the R2 buffer. They may not take R2 review capacity from E18/E21/E26. |
| S15-S19 | OMS & Execution vs App & Charting UI | E30/E31 order-placing UI calls into E29/E32/E39 | Safety ordering (roadmap 11.3 rule 2) means the BE side is Done first by construction. FE consumes a frozen OpenAPI/WS contract (`22-api-openapi.yaml`, `23-ws-protocol.md`). |
| S17-S18 | Rules & Alerts internal | E35 IR, E36 form editor, E37 node editor all live in `area/rule-engine` | The single IR is the contract (ADR). Both editors merge **together or not at all** (roadmap 11.3 rule 5) - one feature flag covering both. |
| S18-S22 | Accounts & Security vs everyone | E43 hardening touches every area | E43 lands as review + targeted fixes, not refactors. Any fix >8 pts becomes its own ticket in the owning lane. |
| S23-S26 | Cross-cutting vs all | E49 defect burn-down edits any module | Defects are routed to the **owning lane**, not fixed by the finder, unless trivial. E49 is a coordination ticket set, not a parallel team. |

## 29.3 Lane occupancy by sprint

Which lanes are active in each sprint, and at what point load. Figures are **all-discipline totals** (eng + design + QA + security) for the epics that lane owns, so they are deliberately larger than the engineering-only numbers in section 2.3 - this table is about *who is busy*, not about the 90-pt line. A blank cell means the lane has no scheduled work and its people are available to the loaded lanes in the same row.

| Sprint | Plat | Gov | DS | Engine | Feeds | FE-App | Flow | Acct/Sec | OMS | Rules | Defect |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **S01** | 68 | 19 | 9 | 8 | 32 | 2 |  | 24 |  |  |  |
| **S02** | 46 | 3 | 13 | 2 | 97 | 13 |  | 34 |  |  |  |
| **S03** | 15 |  | 9 | 14 | 61 | 27 |  | 31 |  |  |  |
| **S04** | 5 |  | 47 | 16 | 62 | 48 |  | 35 |  |  |  |
| **S05** |  |  |  | 42 | 60 | 73 | 3 |  |  |  |  |
| **S06** |  |  |  | 33 | 81 | 19 | 8 |  |  |  |  |
| **S07** |  |  |  | 13 | 23 | 69 | 15 |  |  |  |  |
| **S08** |  |  |  | 19 | 95 | 78 | 35 |  |  |  |  |
| **S09** |  |  |  | 28 | 25 | 85 | 14 |  |  |  |  |
| **S10** |  |  |  |  | 22 |  | 108 |  |  |  |  |
| **S11** |  |  |  |  | 5 |  | 129 |  |  |  |  |
| **S12** |  |  |  |  |  |  | 160 | 5 | 8 |  |  |
| **S13** |  |  |  |  | 50 | 5 | 156 | 11 | 21 |  |  |
| **S14** |  |  |  |  |  | 33 |  | 38 | 63 | 31 |  |
| **S15** |  |  |  |  |  | 26 |  | 47 | 90 | 32 |  |
| **S16** |  |  |  |  |  | 16 |  | 9 | 135 | 9 |  |
| **S17** |  |  |  |  |  | 79 |  | 3 | 59 | 19 |  |
| **S18** |  |  |  |  |  | 72 |  | 16 | 60 | 14 |  |
| **S19** |  |  |  |  |  | 62 |  | 35 | 121 | 9 |  |
| **S20** |  |  |  |  |  |  |  | 97 | 19 |  |  |
| **S21** |  |  |  | 6 |  |  |  | 65 | 34 |  |  |
| **S22** |  |  |  |  |  |  |  | 16 | 19 |  |  |
| **S23** |  | 9 | 93 | 26 |  |  |  |  |  |  | 60 |
| **S24** |  |  | 30 | 44 |  |  |  |  |  |  | 13 |
| **S25** |  | 33 | 19 | 19 |  |  |  |  |  |  | 21 |
| **S26** |  | 19 | 6 |  |  |  |  |  |  |  | 13 |

Read this table for **staffing conflicts**, not for totals. Columns that light up together in one row are teams that must not be the same people: S01 has 7 lanes active at once against a 10-engineer BE+FE pool, and it is the sprint most likely to discover that the lane model is aspirational.

## 29.4 Parallelisable lane pairs per sprint

Two lanes may be run by two independent teams in the same sprint **without a shared-module contract** when their module sets are disjoint and neither appears in the collision table (29.2). The pairs below are safe by construction and are how the sprint is split across teams at planning.

| Sprint | Safe concurrent lanes (disjoint modules) | Requires a written contract first |
|---|---|---|
| S01 | Plat+Gov, Plat+DS, Plat+Engine, Plat+Feeds, Plat+FE-App, Plat+Acct/Sec ... | - |
| S02 | Plat+Gov, Plat+DS, Plat+Engine, Plat+Feeds, Plat+FE-App, Plat+Acct/Sec ... | - |
| S03 | Plat+DS, Plat+Engine, Plat+Feeds, Plat+FE-App, Plat+Acct/Sec, DS+Engine ... | - |
| S04 | Plat+DS, Plat+Engine, Plat+Feeds, Plat+FE-App, Plat+Acct/Sec, DS+Engine ... | - |
| S05 | Engine+Feeds, Engine+FE-App, Feeds+FE-App, Feeds+Flow, FE-App+Flow | Engine+Flow: render pass-ordering contract (S09) |
| S06 | Engine+Feeds, Engine+FE-App, Feeds+FE-App, Feeds+Flow, FE-App+Flow | Engine+Flow: render pass-ordering contract (S09) |
| S07 | Engine+Feeds, Engine+FE-App, Feeds+FE-App, Feeds+Flow, FE-App+Flow | Engine+Flow: render pass-ordering contract (S09) |
| S08 | Engine+Feeds, Engine+FE-App, Feeds+FE-App, Feeds+Flow, FE-App+Flow | Engine+Flow: render pass-ordering contract (S09) |
| S09 | Engine+Feeds, Engine+FE-App, Feeds+FE-App, Feeds+Flow, FE-App+Flow | Engine+Flow: render pass-ordering contract (S09) |
| S10 | Feeds+Flow | - |
| S11 | Feeds+Flow | - |
| S12 | Acct/Sec+OMS | Flow+Acct/Sec: R3-budget ring-fence for E27/E29; Flow+OMS: R3-budget ring-fence for E27/E29 |
| S13 | Feeds+FE-App, Feeds+Flow, Feeds+Acct/Sec, Feeds+OMS, FE-App+Flow, FE-App+Acct/Sec ... | FE-App+OMS: frozen OpenAPI/WS order contract; Flow+Acct/Sec: R3-budget ring-fence for E27/E29; Flow+OMS: R3-budget ring-fence for E27/E29 |
| S14 | FE-App+Acct/Sec, Acct/Sec+OMS, Acct/Sec+Rules, OMS+Rules | FE-App+OMS: frozen OpenAPI/WS order contract; FE-App+Rules: single-IR contract; both editors merge together |
| S15 | FE-App+Acct/Sec, Acct/Sec+OMS, Acct/Sec+Rules, OMS+Rules | FE-App+OMS: frozen OpenAPI/WS order contract; FE-App+Rules: single-IR contract; both editors merge together |
| S16 | FE-App+Acct/Sec, Acct/Sec+OMS, Acct/Sec+Rules, OMS+Rules | FE-App+OMS: frozen OpenAPI/WS order contract; FE-App+Rules: single-IR contract; both editors merge together |
| S17 | FE-App+Acct/Sec, Acct/Sec+OMS, Acct/Sec+Rules, OMS+Rules | FE-App+OMS: frozen OpenAPI/WS order contract; FE-App+Rules: single-IR contract; both editors merge together |
| S18 | FE-App+Acct/Sec, Acct/Sec+OMS, Acct/Sec+Rules, OMS+Rules | FE-App+OMS: frozen OpenAPI/WS order contract; FE-App+Rules: single-IR contract; both editors merge together |
| S19 | FE-App+Acct/Sec, Acct/Sec+OMS, Acct/Sec+Rules, OMS+Rules | FE-App+OMS: frozen OpenAPI/WS order contract; FE-App+Rules: single-IR contract; both editors merge together |
| S20 | Acct/Sec+OMS | - |
| S21 | Engine+Acct/Sec, Engine+OMS, Acct/Sec+OMS | - |
| S22 | Acct/Sec+OMS | - |
| S23 | Gov+DS, Gov+Engine, Gov+Defect, DS+Engine, DS+Defect, Engine+Defect | - |
| S24 | DS+Engine, DS+Defect, Engine+Defect | - |
| S25 | Gov+DS, Gov+Engine, Gov+Defect, DS+Engine, DS+Defect, Engine+Defect | - |
| S26 | Gov+DS, Gov+Defect, DS+Defect | - |

---

# 30. Per-train burn-up

Cumulative engineering points completed against the train total. The plan line below is what a train check-in (section 31) compares actuals against; a train that is more than one sprint behind this line is amber by definition (section 31.3).

### 30.1 R0 - Foundations (S01-S04)

| Sprint | Eng pts | Cumulative | Remaining | % complete | Design cum | QA cum | Sec cum |
|---|---|---|---|---|---|---|---|
| S01 | 90 | 90 | 209 | 30% | 63 | 1 | 8 |
| S02 | 89 | 179 | 120 | 60% | 161 | 7 | 23 |
| S03 | 79 | 258 | 41 | 86% | 210 | 29 | 30 |
| S04 | 41 | 299 | 0 | 100% | 291 | 94 | 56 |
| **Total** | **299** | | | | **291** | **94** | **56** |

Engineering capacity across R0: **360** pts; planned **299** (**83%**), leaving **61** pts of train buffer and named reserve (roadmap 3.1). All-discipline load: **740** pts.

### 30.2 R1 - Charting alpha (S05-S09)

| Sprint | Eng pts | Cumulative | Remaining | % complete | Design cum | QA cum | Sec cum |
|---|---|---|---|---|---|---|---|
| S05 | 89 | 89 | 310 | 22% | 80 | 0 | 9 |
| S06 | 101 | 190 | 209 | 48% | 90 | 22 | 17 |
| S07 | 61 | 251 | 148 | 63% | 108 | 54 | 26 |
| S08 | 88 | 339 | 60 | 85% | 167 | 114 | 46 |
| S09 | 60 | 399 | 0 | 100% | 192 | 164 | 63 |
| **Total** | **399** | | | | **192** | **164** | **63** |

Engineering capacity across R1: **405** pts; planned **399** (**99%**), leaving **6** pts of train buffer and named reserve (roadmap 3.1). All-discipline load: **818** pts.

### 30.3 R2 - Order-flow beta (S10-S13)

| Sprint | Eng pts | Cumulative | Remaining | % complete | Design cum | QA cum | Sec cum |
|---|---|---|---|---|---|---|---|
| S10 | 89 | 89 | 267 | 25% | 23 | 2 | 16 |
| S11 | 89 | 178 | 178 | 50% | 47 | 15 | 24 |
| S12 | 89 | 267 | 89 | 75% | 65 | 70 | 35 |
| S13 | 89 | 356 | 0 | 100% | 117 | 153 | 54 |
| **Total** | **356** | | | | **117** | **153** | **54** |

Engineering capacity across R2: **360** pts; planned **356** (**99%**), leaving **4** pts of train buffer and named reserve (roadmap 3.1). All-discipline load: **680** pts.

### 30.4 R3 - Trading on demo (S14-S19)

| Sprint | Eng pts | Cumulative | Remaining | % complete | Design cum | QA cum | Sec cum |
|---|---|---|---|---|---|---|---|
| S14 | 89 | 89 | 407 | 18% | 58 | 6 | 12 |
| S15 | 88 | 177 | 319 | 36% | 124 | 26 | 33 |
| S16 | 89 | 266 | 230 | 54% | 159 | 58 | 46 |
| S17 | 89 | 355 | 141 | 72% | 179 | 93 | 62 |
| S18 | 88 | 443 | 53 | 89% | 194 | 139 | 75 |
| S19 | 53 | 496 | 0 | 100% | 225 | 252 | 105 |
| **Total** | **496** | | | | **225** | **252** | **105** |

Engineering capacity across R3: **540** pts; planned **496** (**92%**), leaving **44** pts of train buffer and named reserve (roadmap 3.1). All-discipline load: **1078** pts.

### 30.5 R4 - Live enablement (S20-S22)

| Sprint | Eng pts | Cumulative | Remaining | % complete | Design cum | QA cum | Sec cum |
|---|---|---|---|---|---|---|---|
| S20 | 87 | 87 | 70 | 55% | 6 | 11 | 12 |
| S21 | 59 | 146 | 11 | 93% | 14 | 33 | 28 |
| S22 | 11 | 157 | 0 | 100% | 16 | 42 | 41 |
| **Total** | **157** | | | | **16** | **42** | **41** |

Engineering capacity across R4: **270** pts; planned **157** (**58%**), leaving **113** pts of train buffer and named reserve (roadmap 3.1). All-discipline load: **256** pts.

### 30.6 R5 - Hardening / GA (S23-S26)

| Sprint | Eng pts | Cumulative | Remaining | % complete | Design cum | QA cum | Sec cum |
|---|---|---|---|---|---|---|---|
| S23 | 87 | 87 | 115 | 43% | 66 | 26 | 9 |
| S24 | 62 | 149 | 53 | 74% | 66 | 46 | 14 |
| S25 | 48 | 197 | 5 | 98% | 71 | 76 | 23 |
| S26 | 5 | 202 | 0 | 100% | 77 | 92 | 34 |
| **Total** | **202** | | | | **77** | **92** | **34** |

Engineering capacity across R5: **360** pts; planned **202** (**56%**), leaving **158** pts of train buffer and named reserve (roadmap 3.1). All-discipline load: **405** pts.

### 30.7 Whole-plan burn-up

| Train | Sprints | Eng pts | Cumulative eng | % of plan complete at train exit | Cut version |
|---|---|---|---|---|---|
| R0 | S01-S04 | 299 | 299 | 16% | `0.1.0` |
| R1 | S05-S09 | 399 | 698 | 37% | `0.2.0` |
| R2 | S10-S13 | 356 | 1054 | 55% | `0.3.0` |
| R3 | S14-S19 | 496 | 1550 | 81% | `0.4.0` |
| R4 | S20-S22 | 157 | 1707 | 89% | `1.0.0` |
| R5 | S23-S26 | 202 | 1909 | 100% | `1.1.0` (GA) |
| **Total** | S01-S26 | **1909** | | | |

---

# 31. Release-train check-ins and re-planning

## 31.1 Cadence

| Ceremony | When | Who | Output |
|---|---|---|---|
| Sprint Planning | Mon week 1, day 1 | lane leads + QA lead + Security + Architect + Owner | Committed sprint scope; any over-capacity resolved **before** commit |
| Daily stand-up | daily, per lane | lane | Blockers surfaced within 24h |
| Scrum-of-scrums | Wed each week | lane leads + Architect | Cross-lane blockers, contract changes |
| Design Review | weekly | CDO + designers + consuming FE lead | Design tickets move to Done (gates DoR two sprints out) |
| Backlog refinement | Wed week 2 | lane leads + QA + Owner | Next sprint DoR-ready; estimates via planning poker |
| Sprint Review / demo | Fri week 2 | whole team + Owner | Demo on staging; Owner acceptance recorded on tickets |
| Retro | Fri week 2 | whole team | Learnings -> Chore/action tickets |
| **Train check-in** | Fri week 2 of **every even sprint** | Architect + lane leads + QA + Security + Owner | Train health call: green / amber / red |
| **Train gate (PRR)** | last day of the train | PRR board per `07-release-and-prr.md` | Go / no-go on the release cut |

## 31.2 Train check-in agenda (the 6 questions)

Every even-sprint check-in answers exactly these, in this order, in writing:

1. **Burn-up vs plan.** Is cumulative eng points for this train on the line in section 30? State the delta in points *and* in sprints.
2. **Exit criteria evidence.** For each train exit criterion (roadmap 4.3/5.3/6.3/7.3/8.3/9.3), is there a *link* to evidence, or only an intention? Intentions count as red.
3. **Critical path.** Has any item on `E02->E06->E11->E12->E18->E26->E38->E44->E46->GA` or `E09->E27->E29->E32->E34->E43->E44` slipped? Any slip >1 sprint triggers the mandatory re-plan session (roadmap 13).
4. **Design-ahead health.** Are the design tickets for sprint *n+2* Done? If not, which FE stories will fail DoR, and is a CDO waiver being requested?
5. **Constraint check.** Which pool was actually binding last sprint - eng, QA, design or security? Compare against the assumed capacities in section 2.2 and adjust.
6. **Reserve position.** How much train buffer and named reserve remains? Reserves are reported as a number, never as "we should be fine".

## 31.3 Train health definitions

| Status | Definition | Required action |
|---|---|---|
| **Green** | Burn-up within 1 sprint of section 30; all exit criteria have evidence or a dated owner; no critical-path slip | Continue |
| **Amber** | Burn-up 1-2 sprints behind, **or** any pool over capacity two sprints running, **or** a design-ahead violation without a waiver | Descoping ladder (roadmap 12) opened at the next planning; Owner informed |
| **Red** | Burn-up >2 sprints behind, **or** critical-path slip >1 sprint, **or** an exit criterion with no credible path | Immediate re-plan session (Architect + affected lead + QA lead + Owner); risk-register entry; roadmap amendment at the train boundary |

## 31.4 Check-in schedule

| Check-in | Date | Train | Special focus |
|---|---|---|---|
| S02 check-in | 2026-10-08 | R0 | **Engine spike go/no-go (2026-10-08)** + first velocity recalibration (31.6) |
| S04 check-in | 2026-10-22 | R0 | **R0 gate / PRR-lite** + second velocity recalibration; R1 re-baselined here |
| S06 check-in | 2026-11-05 | R1 | R1 mid-train; **S06/S07 eng over-capacity must already be resolved**; engine core FPS trend |
| S08 check-in | 2026-11-19 | R1 | R1 pre-exit; golden-fixture corpus readiness; DAST first-run triage |
| S10 check-in | 2026-12-03 | R2 | R2 open; footprint render budget - the single number that decides R2 scope |
| S12 check-in | 2026-12-17 | R2 | R2 mid-train; **S13 QA pile-up decision must be made here, not in S13** |
| S14 check-in | 2026-12-31 | R3 | R3 open; safety ordering confirmed; design-ahead for S16-S17 verified |
| S16 check-in | 2027-01-14 | R3 | R3 mid-train; native-SL invariant evidence; **S19 QA over-commit mitigation decided here** |
| S18 check-in | 2027-01-28 | R3 | R3 pre-exit; rule-editor joint-merge readiness; soak window pre-flight |
| S20 check-in | 2027-02-11 | R4 | R4 open; **code-freeze readiness for 2027-02-11** |
| S22 check-in | 2027-02-25 | R4 | **R4 / Live-enablement gate** - highest-consequence check-in in the plan |
| S24 check-in | 2027-03-11 | R5 | R5 mid-train; defect burn-down trend; GA scope freeze |
| S26 check-in | 2027-03-25 | R5 | **GA** - PRR re-run + GA checklist |

## 31.5 What may and may not change

| Element | Changeable? | Mechanism |
|---|---|---|
| Sprint dates (roadmap 1.1) | **No** | Fixed for the whole horizon. Scope moves between sprints; dates do not. |
| Train exit criteria | **No**, once the train has started | Owner decision recorded as an ADR + risk-register entry |
| Which train an epic rides | Only at a train boundary | Roadmap amendment (roadmap 13) |
| Ticket -> sprint assignment | **Yes**, at sprint planning | This document, amended in-place (31.9) |
| Estimates | **Yes**, at refinement | Planning poker; re-estimate is data, not failure |
| Assumed pool capacities (section 2.2) | **Yes** - that is the point | Velocity recalibration below |

## 31.6 Velocity recalibration after S02 and S04

The 90-pt engineering capacity and the design/QA/security pool sizes in section 2.2 are **assumptions inherited from the planning brief**. They have never been measured on this team, on this codebase. Two recalibration points are scheduled deliberately early, while the cost of being wrong is still small.

### Recalibration 1 - end of S02 (2026-10-08)

Two sprints of actuals exist. This is a *sanity* check, not a re-baseline: S01-S02 are scaffolding-heavy and unrepresentative of steady-state feature work.

**Inputs:** completed points per discipline for S01 and S02; carry-in/carry-out; the count of tickets that failed DoD on first review; actual PR cycle time vs the 400-LOC preference.

```
observed_velocity = mean(completed_eng_pts[S01], completed_eng_pts[S02])
estimate_bias     = completed_pts / originally_estimated_pts   # per discipline
```

| Observation | Action |
|---|---|
| `observed_velocity` within +/-15% of 90 | No change. Note it and move on. |
| `observed_velocity` < 76 pts | Do **not** re-baseline yet - flag amber, re-check at S04. Two scaffolding sprints are weak evidence. |
| `estimate_bias` consistently <0.8 in one discipline | That discipline is systematically over-estimating; recalibrate its reference stories at refinement, not its capacity number. |
| Any pool (design/QA/sec) finished <70% of its tickets | Its section 2.2 capacity is wrong. Adjust the number and re-run the flags in section 2.3. |

> S01 and S02 are planned at **90** and **89** eng pts against 90 - i.e. at the line. There is no slack to hide a low velocity in, which is precisely why this check-in is scheduled.

### Recalibration 2 - end of S04 (2026-10-22), at the R0 gate

**This one is a real re-baseline.** Four sprints of actuals, a completed train, and a PRR-lite gate that forces honest evidence. R1 is re-planned against the recalibrated numbers *before* S05 opens.

```
V = mean(completed_eng_pts[S01..S04])           # new engineering capacity
for pool in (design, qa, security):
    C[pool] = mean(completed_pts[pool][S01..S04])
scale = V / 90                                   # re-baseline factor
```

**Then, in this order:**

1. **Replace the capacity numbers** in section 2.2 and re-generate section 2.3. Record old and new values in the amendment log (31.9) - never silently overwrite.
2. **Re-run the flags.** Every sprint whose load now exceeds the recalibrated pool becomes a planning item. With `scale < 1`, expect the already-over sprints (S06 (101), S07 (61)) plus everything within 2 pts of the cap to go red.
3. **Do not move dates.** Apply the descoping ladder (roadmap 12) in its pre-agreed order, starting at item 1, until each train fits. The ladder exists precisely so this decision is not made under pressure.
4. **Protect the never-cut list.** E32 native SL, E39 kill-switch + risk caps, E09 RBAC, E27 key vault, E42 audit completeness, E43/E44 pen-test + Live gate, E47 a11y Level A, E45 reconciliation. Cutting any of these needs a written Owner decision, an ADR and a risk-register entry, and it **blocks the Live-enablement gate by default**.
5. **Re-check design-ahead.** If engineering slows, design gets *further* ahead, which is safe. If design slows, FE stories start failing DoR two sprints later - that is the dangerous direction and it must be called out explicitly.
6. **Re-forecast GA.** State the new GA date implied by `V` even if the answer is unwelcome. At `V = 75`, the 1986 planned eng points need ~26 sprints of pure delivery against 26 available - report how much reserve remains, not a reassurance.

### Ongoing recalibration

After S04, velocity is re-computed as a **rolling 3-sprint mean** at every train check-in. A single bad sprint never triggers a re-plan; two consecutive sprints below 85% of the rolling mean does.

## 31.7 Re-plan triggers (any one fires a session)

| Trigger | Detected at | Session attendees | Deadline |
|---|---|---|---|
| Critical-path item slips >1 sprint | Any stand-up or check-in | Architect + affected lead + QA lead + Owner | Within 2 working days |
| Rolling velocity <85% of mean for 2 sprints | Train check-in | Lane leads + Architect + Owner | Next sprint planning |
| A pool over capacity 2 sprints running | Train check-in | That pool lead + Architect + Owner | Next sprint planning |
| Engine spike returns no-go (S02) | 2026-10-08 | Architect + CDO + Owner | Immediately - R1 is re-planned wholesale |
| Pen-test findings exceed the 90-pt reserve | S21 | Security + Architect + Owner | Within 2 working days; Live gate date is at risk |
| Soak failure in S19 or S25 | q09 / q11 | QA lead + Architect + Owner | Immediately - these have near-zero recovery margin |
| A never-cut item is proposed for cutting | Anywhere | Owner (decision), Architect, Security | ADR before the decision is actioned |

## 31.8 Sprints already known to need re-planning

These are not predictions - they are arithmetic from the current backlog, visible today.

| Sprint | Problem | Decide by | Pre-agreed remedy |
|---|---|---|---|
| **S01** | design 63 vs 60 (+3) | S01 planning | Absorb from the train buffer or apply the descoping ladder (roadmap 12) in order. |
| **S02** | design 98 vs 60 (+38) | S01 planning | Absorb from the train buffer or apply the descoping ladder (roadmap 12) in order. |
| **S04** | **QA 65 vs 45 (+20)**; design 81 vs 60 (+21); sec 26 vs 20 (+6) | S02 check-in | QA pile-up is R0-exit evidence. Move non-gate-blocking evidence tasks into S05, which opens with zero QA load. |
| **S05** | design 80 vs 60 (+20) | S04 check-in | Absorb from the train buffer or apply the descoping ladder (roadmap 12) in order. |
| **S06** | 101 eng vs 90 (+11) | S04 check-in | Draw the R1 buffer, or move the non-gating E16 retention tasks to S09 (which has ~30 free eng pts inside the same train). |
| **S07** | 61 eng vs 45 (+16) | S06 check-in | Holiday sprint at 45 pts. Nothing on the critical path may start here; move the overage to S08/S09 at S06 planning and absorb the remainder from the R1 buffer. |
| **S08** | **QA 60 vs 45 (+15)** | S06 check-in | Split the QA load with S09 (R1 exit evidence can start one sprint early against recorded fixtures). |
| **S09** | **QA 50 vs 45 (+5)** | S08 check-in | R1-exit QA. Front-load fixture-dependent suites into S08 and keep only gate evidence here. |
| **S12** | **QA 55 vs 45 (+10)** | S10 check-in | Move non-gating order-flow correctness cases into S14, which opens R3 lightly on QA. |
| **S13** | **QA 83 vs 45 (+38)** | S12 check-in | R2-exit evidence pile-up. Per roadmap 12, move non-gate-blocking QA to S14 and re-sequence the design tickets consumed here; decide at the S12 check-in. |
| **S15** | design 66 vs 60 (+6); sec 21 vs 20 (+1) | S14 check-in | Absorb from the train buffer or apply the descoping ladder (roadmap 12) in order. |
| **S18** | **QA 46 vs 45 (+1)** | S16 check-in | One point over - absorb, no action beyond noting it. |
| **S19** | **QA 113 vs 45 (+68)**; sec 30 vs 20 (+10) | S18 check-in | QA cannot absorb this under any assumption. Pull descoping-ladder items #6 (E40 webhook delivery) and #7 (E41 advanced analytics) into R5 now, and move non-gate-blocking QA into S20. The 7-day soak closing one day before the gate is the real constraint and cannot be compressed. |
| **S23** | design 66 vs 60 (+6) | S22 check-in | Design overage is GA-polish work with no hard date - spread across S24-S25, which carry almost no design load. |

Two structural notes the table cannot express:

- **R1 is the tight train.** It carries 399 eng pts against 405 of holiday-adjusted capacity, so it fits only with near-perfect packing, and S07 at 45 pts forces the pinch into S06. Every S06/S07 ticket is pinned by a same-train dependent, so relieving this needs a human call - absorb from the train buffer, descope per roadmap 12, or raise S07 capacity. This is a roadmap 12 decision, not a data error.
- **QA is the binding constraint of the whole plan.** 7 of 26 sprints exceed the QA pool; engineering exceeds its cap in 2. Every mitigation above that moves QA work sideways assumes the receiving sprint's QA column stays under 45 - check that before committing the move.

## 31.9 Amendment log

All scope moves between sprints are recorded here. Roadmap-level changes go to `30-release-roadmap.md` at a train boundary instead (roadmap 13).

| Date | Sprint(s) | Change | Reason | Decided by |
|---|---|---|---|---|
| 2026-09-14 | - | Initial plan generated from `backlog/all-tickets.json` | Planning phase | basiltt |
| 2026-09-15 | all | Regenerated against the completed backlog (49 epic files, 1302 children, 3985 pts) | All 49 roadmap epics now have backlog files; the previous revision was built on 42 | basiltt |
| 2026-09-15 | S02-S09 | Inserted **E50** (statechart contracts & xstate-statemachine adoption readiness, 25 tickets, 85 pts) into the sprint tables and refreshed every derived total | ADR-0016 / roadmap 3.1.1: the statechart linter and contract suite must ship before the first statechart (MUST-09). See `backlog/_reconciliation-report.md` 14. | basiltt |

---

# 32. Gap register - what this plan cannot yet schedule

`backlog/_reconciliation-report.md` is the authority here. As of this revision it reports **4 errors** and 142 warnings; the warnings are all `LONG-TITLE` (cosmetic, >80 chars) and are not planning items.

## 32.1 Resolved since the previous revision

| Previously | Status now |
|---|---|
| 7 epics with no backlog file (E08, E09, E12, E14, E15, E19, E47 - 296 roadmap pts) | **Resolved.** All 49 roadmap epics have files; those 7 contribute 276 child tickets to the sprint tables above. |
| 10 design-ahead violations in S13 (E24-D05, E25-D07) | **Resolved** by pulling the design chains 1-2 sprints earlier (reconciliation report 12). |
| `E26-S07` inverted `blocked_by: E38` | **Resolved** - blocker removed, reason recorded on the ticket `notes`. |
| Dangling `blocked_by` references | **Zero.** All 3045 dependency links resolve, 530 of them to a whole epic. |

## 32.2 Open errors (2) — post-adoption re-plan 2026-09-24

ADR-0016 is **Accepted**: `xstate-statemachine==0.9.1` is adopted completely (no shim, no dual-runtime harness). 59 E50 tickets are retired at 0 pts (label `retired`, sprint `Backlog`; validate.py counts them in no pool). The E50 build now fits R0 (S02–S04), with the BLOCKING `tests/xstate_contract` gate (`E50-T31`), gateway (`E50-T15`), nightly `run_gate.py` (`E50-T04`) and event-coverage gate landing in S04. S05 (+5) and S06 (+14) overages are gone. Remaining, pre-accepted:

- `OVER-CAPACITY Sprint 07: 47 eng pts vs capacity 45 (+2)` — holiday sprint, baseline E11–E15 charting chain, 0 E50 eng pts.
- `TRAIN-OVER-CAPACITY R1: 407 eng pts vs 405 available` — same 2 pts.

Absorbed from the R1 train buffer per roadmap §12. The secondary gates `E50-T05`/`E50-T06` and upstream contributions `E50-C01`/`E50-C02` moved to S17/S19 headroom (non-critical; no R1 exit criterion depends on them). Full before/after: `backlog/_reconciliation-report.md` §17.

## 32.3 Unscheduled tickets

11 tickets (46 pts) sit in `Backlog` with no sprint. The four older ones are small and non-blocking; the seven E08 build tickets wait on a capacity re-plan. Either way, "Backlog" is not a decision - each must be scheduled or explicitly deferred at the next refinement.

| Key | Title | Kind | Est | Parent epic | Suggested disposition |
|---|---|---|---|---|---|
| `E20-S05` | Rolling N-bar sparkline per Deep-Stats row | Story | 3 | E20 | R5 polish - it is a presentation refinement on an already-shipped row. |
| `E22-S06` | Big-trade (whale) alerts with flood control | Story | 2 | E22 | Fold into E40 alerts in R3, or defer to R5 with ladder item #6. |
| `E23-S06` | Composite normalised CVD across up to five symbols | Story | 2 | E23 | Descoping-ladder item #4 (multi-symbol CVD) - defer to R5 by default. |
| `E40-S03` | Ship HMAC-signed webhook alert delivery with allow-listed egress | Story | 1 | E40 | Descoping-ladder item #6 (webhook delivery) - defer to R5 by default. |
| `E08-S08` | Build the SCR-100 watchlist panel and SCR-101 manager with live and stale states | Story | 8 | E08 | Planned for Sprint 06; held in `Backlog` because S06 is at 90/90 eng pts and R1 at 407/405. Schedule once capacity is re-planned. |
| `E08-S09` | Build SCR-102 symbol search and the SCR-041 quick-switcher on one ranking rule | Story | 5 | E08 | Planned for Sprint 06; held in `Backlog` because S06 is at 90/90 eng pts and R1 at 407/405. Schedule once capacity is re-planned. |
| `E08-S10` | Build the SCR-103 symbol info drawer: contract rules, live market, coverage | Story | 5 | E08 | Planned for Sprint 07; held in `Backlog` because S07 is at 47/45 eng pts (holiday sprint) and R1 at 407/405. Schedule once capacity is re-planned. Ready only when E08-D06 (#174) is Done. |
| `E08-S11` | Build the SCR-104 scanner panel: live criteria, result cap, estimated flags | Story | 5 | E08 | Planned for Sprint 07; held in `Backlog` because S07 is at 47/45 eng pts (holiday sprint) and R1 at 407/405. Schedule once capacity is re-planned. Ready only when E08-D08 (#176) is Done. |
| `E08-T07` | /watchlists persistence: migration, routes, RBAC, audit key and version | Task | 5 | E08 | Planned for Sprint 06; held in `Backlog` because S06 is at 90/90 eng pts and R1 at 407/405. Schedule once capacity is re-planned. |
| `E08-T08` | Server side of the ticker WS topic, bulk ticker snapshot and 24 h high/low | Task | 5 | E08 | Planned for Sprint 06; held in `Backlog` because S06 is at 90/90 eng pts and R1 at 407/405. Schedule once capacity is re-planned. |
| `E08-T09` | GET /scanner server and saved scanner presets endpoint | Task | 5 | E08 | Planned for Sprint 07; held in `Backlog` because S07 is at 47/45 eng pts (holiday sprint) and R1 at 407/405. Schedule once capacity is re-planned. |

---

# 33. Backlog import

How `docs/plan/backlog/all-tickets.json` maps onto the GitHub Project at <https://github.com/orgs/CandleViewer/projects/3> (PenniLogic-style schema, per `00-planning-brief.md`).

## 33.1 Source of truth

`all-tickets.json` is a flat JSON array of **1377 objects** (**50** epics + **1327** children), assembled from the per-epic files `backlog/E01.json .. E50.json` and validated by `backlog/_tools/validate.py`, whose output is `backlog/_reconciliation-report.md`.

**The JSON is the source of truth for the initial import only.** After import, GitHub Issues become the source of truth for status and assignment; the JSON remains the source of truth for *structure* (parentage, dependencies, estimates) until the first train boundary, after which the board wins outright. Do not re-run a full import over a live board.

## 33.2 Field mapping

| JSON field | Type | GitHub target | Mapping rule |
|---|---|---|---|
| `key` | string (`E12-S03`) | Issue **title prefix** | Title is rendered as `<key>: <title>`. The key is the only stable cross-reference and must survive into the issue title - board filters, this document and `blocked_by` all key off it. |
| `title` | string | Issue title (after the prefix) | 121 titles exceed 80 chars (`LONG-TITLE` warnings); truncate for display only, never in the issue. |
| `kind` | `Epic`/`Story`/`Task`/`Spike`/`Chore` | Project field **Kind** + `type/*` label | Task 961, Story 274, Spike 50, Chore 17 |
| `labels` | string[] | Issue labels | ~57 distinct labels. Create them all before step 4 or the API silently drops unknown ones. |
| `component` | string | Project field **Component** | Vocabulary: alerts, api, auth, backtesting, chart-engine, cross-cutting, data-feeds, docs, drawing-tools, indicators, infra, scripting, web. |
| `phase` | `P0 Foundations` .. `P5 Collaboration & Polish` | Project field **Phase** | 1:1 with milestone; kept because the board schema has both. |
| `sprint` | `Sprint 01` .. `Sprint 26`, or `Backlog` | Project field **Sprint** (iteration) | Iterations must be created with the exact dates from section 2.3. `Backlog` maps to *no iteration*, not to an iteration named "Backlog" (4 tickets, section 32.3). |
| `priority` | `P0 Critical` .. `P3 Low` | Project field **Priority** | Also duplicated as a `priority/*` label - see caveat 2. |
| `perspective` | `Product`/`Development`/`Test`/`Security`/`Architecture`/`QA`/`Ops`/`Compliance` | Project field **Perspective** | Free-text single select. |
| `risk` | `R<n> <name>` or `None` | Project field **Risk** | Cross-references `32-risk-register.md`; `None` is a legitimate value, not a null. |
| `estimate` | int (Fibonacci 1-8; epics roll up) | Project field **Estimate** | Child estimates only are summed in this document. Epic estimates are roadmap-level and must **not** be added to sprint totals or every point is counted twice. |
| `parent` | key or `null` | **Sub-issue** relationship | `null` => epic. Every one of the 1327 children has a parent that exists. |
| `blocked_by` | key[] | Issue **relationship** / `Blocked by` | 2831 links total, 343 of which name a whole epic rather than a ticket - legitimate, see caveat 3. |
| `milestone` | `R0 Foundations` .. `R5 Hardening / GA` | **Milestone** | Due date = train end date from roadmap 1.1. |
| `body` | markdown | Issue body | Already DoR-shaped: context, acceptance criteria in Gherkin, test plan, security notes, a11y notes, DoD, out-of-scope, doc references. |
| `notes` | markdown (1 ticket) | Appended to the issue body under `## Planning notes` | Only `E26-S07` carries it (the resolved inverted dependency). |

## 33.3 Derived fields the importer must compute

| Target field | Derivation |
|---|---|
| **Start** | Monday of the `sprint` iteration (section 2.3 column 2) |
| **Due** | Friday of the `sprint` iteration (section 2.3 column 3) |
| **Status** | Always `Backlog` at import - no ticket is pre-promoted to Ready |
| **Discipline** (if the board has it) | From the key letter: `S`/`T`/`K`/`C` -> Engineering, `D` -> Design, `Q` -> QA, `X` -> Security (section 1.1) |
| **Lane** (if the board has it) | From the `parent` epic via the lane table in section 29.1 |
| **Rollup** | Epic estimate = sum of child estimates; recompute after import rather than trusting the JSON epic estimate, which is the roadmap figure |

## 33.4 Import order (dependencies force this sequence)

```
1. Milestones      x6      R0..R5, due dates = train end dates (roadmap 1.1)
2. Labels          ~57     all type/*, area/*, priority/* and gate labels
3. Project fields          Kind, Phase, Sprint (26 iterations), Component,
                           Priority, Perspective, Risk, Estimate, Status
4. Epic issues     x49      parent == null; record key -> issue number
5. Child issues    x1327    set the sub-issue parent during creation
6. Second pass             resolve blocked_by keys -> issue numbers, set relationships
7. Field values            set all project fields from the JSON + derived values
8. Validation              re-run the checks below
```

Steps 4-5 must not be parallelised across epics: a child may be `blocked_by` a ticket in another epic, and step 6 needs the full key->number map.

## 33.5 Sub-issue and blocked-by relationships

| Relationship | Count | Shape | Import rule |
|---|---|---|---|
| Sub-issue (epic -> child) | 1327 | Exactly one parent per child; depth 1 (no child-of-child) | Set at creation (step 5). An epic's progress bar is then automatic. |
| Blocked-by (ticket -> ticket) | 2488 | DAG; may cross epics and trains | Step 6 only. Zero dangling references today - if the importer finds one, stop and fix the JSON, do not create a placeholder issue. |
| Blocked-by (ticket -> epic) | 343 | "blocked until that whole epic is Done" | Legitimate. Link to the epic issue; the board shows it as blocked until the epic closes. |

Dependency direction is **`blocked_by`**, i.e. the edge points *backwards*: `A.blocked_by = [B]` means B must finish first. The roadmap 11.1 graph draws the same edges forwards (`B --> A`); do not invert them during import (this is exactly the bug that produced the `E26-S07` error in the previous revision).

## 33.6 Post-import validation

The import is not complete until all of these pass:

| Check | Expected |
|---|---|
| Issue count | 1377 (50 epics + 1327 children) |
| Every child has a parent | 1327 sub-issue links |
| Every `blocked_by` resolved | 0 dangling references |
| Sum of Estimate by Sprint | matches section 2.3 exactly, per discipline |
| Total points | eng 1986 / design 918 / QA 802 / security 356 = 4062 |
| Milestone distribution | R0: 205; R1: 251; R2: 264; R3: 405; R4: 73; R5: 104 |
| Kind distribution | Task 961; Story 274; Spike 50; Chore 17 |
| All issues Status=Backlog | no ticket is pre-promoted to Ready |
| Unscheduled | exactly 4 tickets with no iteration (section 32.3) |

## 33.7 Known import caveats

1. **Duplicate priority encoding.** Both `priority` (field) and `priority/*` (label) exist, and the label vocabulary is inconsistent - `priority/p0` (539 uses) and `priority/p0-critical` (25 uses) both appear. Normalise to one form during import or board filters will silently miss tickets.
2. **`blocked_by` sometimes names an epic, not a ticket** (343 links). That is legitimate; the importer must not treat it as dangling.
3. **The JSON has no assignee.** Assignment happens at sprint planning, via the lane model in section 29.1.
4. **Re-import is destructive.** There is no idempotency key beyond the title prefix. If the import must be re-run, delete the project and issues first, or match on the `<key>:` title prefix and update in place.
5. **Body content is DoR-shaped but not DoR-complete.** Gherkin acceptance criteria are present; estimates were not set by planning poker with this team. Every ticket still needs the DoR checklist walked at refinement before it moves to Ready.
6. **Epic estimates are roadmap figures, not rollups.** Import them into a separate field or recompute from children; adding both to a sprint total double-counts every point.

---

## Document control

| | |
|---|---|
| Generated from | `docs/plan/backlog/all-tickets.json` (1351 tickets) + `docs/plan/30-release-roadmap.md` |
| Regenerate | re-run the aggregation over the backlog JSON; the per-sprint tables are mechanical, the narrative sections are not |
| Review cadence | every sprint planning (ticket allocation), every train check-in (capacity), every train boundary (roadmap reconciliation) |
| Changes to sequencing/dates | belong in `30-release-roadmap.md`, not here |
| Changes to ticket allocation | belong here, logged in the amendment log (31.9) |
