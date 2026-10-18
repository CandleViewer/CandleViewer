# CLAUDE.md — Claude Code entry point for CandleViewer

> Every Claude Code session in this repo loads this file automatically. It is a **condensed pointer**, not
> a second rulebook: per `CONSTITUTION.md` C-16.5 each rule has exactly one owning document. Where this
> file paraphrases a rule it cites the owner (`C-x.y`, `AGENTS.md §n`, `docs/plan/NN-*.md`). **If anything
> here contradicts `CONSTITUTION.md` or `AGENTS.md`, those win and this file is a bug — fix it in the same
> PR.** Required-check names (C-9.1) and command names (`AGENTS.md` §4) are owned elsewhere; the tables
> below are quick-reference mirrors and must be updated whenever the owners change.

## 1. Purpose and product summary

CandleViewer is a **private, self-hosted trading terminal** for one owner plus a few account managers.
A React + TypeScript web app with a **fully custom WebGL2 chart engine** (footprint, volume/market
profile, CVD, DOM heatmap, Deep Stats) is wrapped by an Electron desktop shell; a Python 3.12
FastAPI/asyncio **modular monolith** talks to **Bybit v5, USDT linear perpetuals only**, storing hot data
in QuestDB, cold/replay data in Parquet/DuckDB and relational data in Postgres. It provides the full
execution loop (OMS, multi-account trade-group fan-out, emulated algos, kill switch), a rule engine,
paper trading on Bybit demo, recording/replay, a journal, and RBAC-gated owner/admin screens **inside the
web app**. Hard boundaries (C-1.3): no mobile, no separate admin app, no other exchange or product
category, no options/GEX, **no withdrawals**, no public internet exposure. It moves real money.

## 2. Read these first

Every session, in this order:

1. **`CONSTITUTION.md`** — the non-negotiables. Appendix A is the rule index; cite rule ids in PRs.
2. **`AGENTS.md`** — the operating manual (repo map, ticket workflow, commands §4, coding standards §5,
   test rules §6, PR checklist §7, NEVER list §8, escalation §9).
3. **Your ticket, in full** — the GitHub issue _and_ its JSON in `docs/plan/backlog/E*.json`, especially
   the **`## Agent execution brief`** (Stories/Tasks/Spikes/Bugs/Chores) or **`## Agent guidance`** (Epics).
4. **`docs/plan/README.md`** — the plan index; follow its reading order for your role:

| Role / ticket area            | Read (in `docs/plan/`)                                                                                                                                   |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Everyone                      | `01-sdlc-and-branching.md`, `02-definition-of-ready-done.md`, `03-testing-strategy.md`                                                                   |
| Backend / OMS / ingestion     | `20-architecture.md`, `21-database-schema.md`, `22-api-openapi.yaml`, `23-ws-protocol.md`, `24-internal-schemas.md`                                      |
| Any lifecycle / state machine | `28-statechart-catalogue.md`, `29-statechart-adoption-plan.md`, `27-adrs/ADR-0016-statechart-runtime.md`                                                 |
| Chart engine                  | `26-chart-engine-design.md`, `27-adrs/ADR-0002-custom-webgl-chart-engine.md`, `06-performance-and-load-standard.md`                                      |
| Frontend / design             | `12-sitemap.md`, `13-user-flows.md`, `14-screens-catalogue.md`, `15-component-catalogue.md`, `16-design-system-brief.md`, `05-accessibility-standard.md` |
| Security-labelled             | `04-security-program.md`, `27-adrs/ADR-0009…0010`                                                                                                        |
| Release / infra               | `07-release-and-prr.md`, `27-adrs/ADR-0013-ci-pipeline.md`, `30-release-roadmap.md`                                                                      |
| Planning / traceability       | `10-personas.md`, `11-user-stories.md`, `18-traceability-matrix.md`, `31-sprint-plan.md`, `32-risk-register.md`, `33-raci.md`                            |

Do not write code before step 3. If the Definition of Ready (C-11.1, `02-definition-of-ready-done.md`)
is not met, **stop and comment on the issue** listing exactly what is missing.

## 3. Repo map

Planned monorepo layout (authoritative: `docs/plan/20-architecture.md` §5; annotated in `AGENTS.md` §2).
**Today only the ✅ items exist** — everything else is created by its owning ticket (scaffolding shipped
via `E02-T11`). Do not create a top-level directory your ticket does not own.

```text
CandleViewer/
├─ ✅ CONSTITUTION.md  AGENTS.md  CLAUDE.md  CONTRIBUTING.md  SECURITY.md  CODE_OF_CONDUCT.md  README.md  LICENSE
├─ ✅ .github/              # CODEOWNERS, ISSUE_TEMPLATE/, PULL_REQUEST_TEMPLATE.md (workflows: pending)
├─ ✅ docs/plan/            # all planning docs, ADRs, backlog/ (ticket JSON + _tools/validate.py)
├─ ✅ docs/research/        # xstate verification rounds + gate (docs/research/xstate/gate/run_gate.py)
├─ apps/web/               # React SPA (Vite): routes, feature slices, ws client, Zustand/Jotai, e2e/
├─ apps/desktop/           # Electron shell — NO business logic (main, preload IPC allow-list, e2e/)
├─ packages/chart-engine/  # custom WebGL2 engine: core, gl, layers, text (SDF), worker, plugins, bench/
├─ packages/ui/            # design system: tokens, primitives, trading components (Storybook)
├─ packages/protocol/      # GENERATED TS types/decoders from OpenAPI + WS schema — never hand-edit src/generated
├─ packages/fixtures/      # recorded, redacted Bybit fixtures + golden outputs (shared TS & Py)
├─ packages/config/        # shared eslint / tsconfig / prettier / vitest presets
├─ services/api/candleviewer/  # Python backend: app.py, bus/, exchange/bybit/, ingestion/, book/, bars/,
│                          # orderflow/, oms/, rules/, paper/, recorder/, replay/, auth/, admin/, api/, ws/,
│                          # storage/, observability/, migrations/ (alembic), statechart/ (factory + machines/)
├─ tests/                  # xstate_contract/, load/ (k6, locust), chaos
├─ tools/                  # lint_statecharts.py and other repo tooling
└─ infra/                  # docker-compose.dev.yml, images, deploy
```

## 4. How to pick up a ticket

Full flow: `AGENTS.md` §3 (flowchart) and `docs/plan/01-sdlc-and-branching.md` §4–§7.

1. **Find it.** The GitHub issue in the project board; its JSON twin is in `docs/plan/backlog/E<nn>.json`
   (merged: `all-tickets.json`). Tickets labelled **`retired`** are superseded — never implement them;
   follow the replacement named in their body.
2. **Read the Agent execution brief** (Read first / Repo paths / Interfaces you must not break /
   Commands / Branch & PR / Done means / Do NOT / If blocked) and every doc it links.
3. **Check `blocked_by`.** Every listed ticket must be **Done**. If not, do not start — pick another.
4. **Claim it** (see §10): assign yourself, set Status **In Progress**, comment "claimed by <agent>".
5. **Check open PRs** for overlapping paths (`gh pr list`, `gh pr diff`). Overlap ⇒ coordinate first.
6. **Branch** from fresh `main`: `<type>/<epic-key>-<short-slug>` (C-4.4), ≤3 working days lifetime (C-4.3).
7. **Contract first** if the API/WS/DB/statechart surface changes (C-6.1, §10 below).
8. **Tests first** from the Gherkin acceptance criteria, at the right pyramid level (C-13.2–13.4).
9. **Implement the minimum**; read two neighbouring files and follow their patterns.
10. **Run the local gate** (`pnpm verify` / backend commands — `AGENTS.md` §4). Never open an unrun PR.
11. **Open the PR** with `.github/PULL_REQUEST_TEMPLATE.md` fully filled, `Closes #N`, labels, evidence
    (tests, screenshots/capture for UI, bench output, migration up/down output). Status → **In Review**.
12. **Iterate**: reply to every comment, rebase (never merge `main` in). After squash-merge the ticket is
    **In Test**, not Done; QA (and Design/Security where labelled) moves it to **Done** (C-10.4).

## 5. Non-negotiables (condensed — owners in parentheses)

- **Trunk-based.** `main` is the only long-lived branch, protected, linear history, always releasable;
  no direct/force pushes (C-4.1–4.3). Unfinished multi-PR work ships behind a feature flag (C-4.13);
  **flags never gate a safety invariant** (C-4.14).
- **One ticket = one branch = one PR**, preferred **≤400 changed LOC** excluding generated/lockfiles/
  snapshots; larger needs a "why this can't be split" note (C-4.8).
- **Conventional commits**: `type(scope): summary`;
  types `feat fix chore docs test refactor perf build ci`; scope = the `area/*` slug without prefix
  (`chart-engine`, `charting-ui`, `order-flow`,
  `oms-execution`, `rule-engine`, `paper-trading`, `accounts-admin`, `auth-rbac`, `ingestion`,
  `recorder-replay`, `journal-analytics`, `backend-platform`, `frontend-platform`, `electron-shell`,
  `design-system`, `infra-devops`, `docs`) — `01-sdlc-and-branching.md` §5.2/§6.2. Breaking: `!` + footer.
- **Reviews:** 2 independent agent reviews (`code-reviewer`, plus `security-reviewer` on security paths); code PRs merge by the orchestrator once green, design PRs only with owner approval (C-10.1 v1.1.0); security-path changes get the
  `security-review` label and a security reviewer (C-10.2); UI needs design sign-off (C-10.3).
- **Required CI checks:** the exact names live **only** in `CONSTITUTION.md` C-9.1 (20 checks — lint,
  typecheck, unit suites, contract, integration, e2e, a11y, SAST/SCA/secrets/container/licence, bundle,
  bench, migrations, architecture, generated-code, pr-metadata). Do not copy the list; `pr-metadata`
  rejects duplicated single-source lists (C-16.5). Red is never merged; no admin merge.
- **Coverage floors:** ≥85% line for `services/api/**` (branch ≥75%) and `packages/chart-engine/**`;
  ≥80% for `apps/web/**` and `packages/ui/**`; never lowered in the PR that fails them (C-9.4).
- **No secrets, ever.** Never create, read, print, commit or fixture an API key/token/`.env` value; keys
  are envelope-encrypted and plaintext only in memory in the secrets module (C-2.7, C-12.2).
- **No live-exchange or any network calls in tests/CI/dev defaults** — use recorded fixtures in
  `packages/fixtures` (C-13.5, `AGENTS.md` §8.7).
- **Every order/auth/key action writes an append-only audit record** (C-2.9); audit tables never get
  `UPDATE`/`DELETE`.
- **Native exchange stop-loss invariant:** every position-opening order on every account carries a native
  exchange SL (C-2.6). Nothing — flag, config, test shortcut — may bypass it.
- **Withdrawal permission never:** stored keys must have withdrawal off, verified at startup and hourly;
  no code may call a withdrawal endpoint (C-2.8; Semgrep-enforced).
- **RBAC and risk are enforced server-side** (C-12.4); statecharts record, synchronous code enforces (C-2.21).
- **Migrations:** one per PR, never edit a merged one — fix forward (CONSTITUTION §5, C-5.4).

## 6. Statechart rules (C-2.19–C-2.22, ADR-0016 Accepted)

- **Every catalogue lifecycle** (`28-statechart-catalogue.md` B1–B20: order, trade group + legs, the four
  emulated algos, native-SL protection, rule instance, alert, recording/replay sessions, exchange
  connection, book health, paper liquidation, auth session, live-enablement gate, kill switch,
  reconciliation job, risk lockout) is a **JSON contract** at
  `services/api/candleviewer/statechart/machines/<name>.machine.json`. Same state/event/guard names and
  transition table as the catalogue; **where code and contract disagree, the contract is right**.
- **Executor is fixed:** `xstate-statemachine==0.9.1`, run **only** through `cv.statechart.factory`
  (`build(chart_id)`). Calling `create_machine`, `Interpreter` or `SyncInterpreter` anywhere else is a CI
  failure. No in-house shim, no dual runtime.
- **Mandatory config block** (`28-statechart-catalogue.md` §1.3c — copy from there, never from memory):
  `strict_config=True`, `strict=True`, `event_schemas=CV_EVENT_SCHEMAS`, bounded `max_queue_size` +
  `overflow_policy="refuse"` (async only), `.use(CvErrorHooks())`, chart root `"onUnhandled": "defer"` +
  ordered unguarded audit arm, `"maxIterations": 500`. Restore via
  `from_snapshot(..., minimum_version=3, plugins=[CvErrorHooks()])`; drain + journal before `stop()`;
  `cv_re_mint()` payload-only (CV-C68).
  The CV-C constraint list in C-2.22 is binding.
- **Hot paths are never statecharts** (C-2.20): book deltas, bar builders, footprint aggregation, per-tick
  rule evaluation, paper fill/queue/fee math, rate-limit governor and fan-out admission. Nothing >~100 Hz
  queries an interpreter — machines publish a plain `bool`/enum on state entry.
- **Statecharts record; synchronous code enforces** (C-2.21): kill switch, live gate, risk caps, rate
  budgets are sync checks consulted _before_ any interpreter.
- **Gates (blocking):** `tests/xstate_contract/` (golden traces on the library), `tools/lint_statecharts.py`
  (`29-statechart-adoption-plan.md` §1.6), the committed `machine_hashes.lock` diff, and attestation verify.
- **`machine_hash`:** any semantic change needs a hash bump **plus** a version bump or a registered
  upcaster with a golden-snapshot test. A no-op upcaster to silence a mismatch is a defect.
- **Snapshot trust:** `machine_hash` is a fingerprint, not a MAC; the boundary is the HMAC'd journal (CV-C53).
- **Pin discipline:** `==` pin with sha256 hash **and** PEP 740 attestation. Moving the pin requires
  `docs/research/xstate/gate/run_gate.py` + the contract suite + BENCH-6 green, in its own PR.

## 7. Coding standards (owner: `AGENTS.md` §5)

- **TypeScript/React:** `strict: true` (plus `noUncheckedIndexedAccess` etc. per §5.1), ESLint flat
  config + Prettier, `--max-warnings=0`; workspace-alias imports, no deep imports, no cycles
  (dependency-cruiser). UI state in Zustand, high-frequency data in Jotai. Chart engine: no React/DOM
  framework/`fetch`/singletons, explicit `dispose()`, pooled GPU resources, every API change benchmarked.
- **Python:** 3.12+, **asyncio only** (no blocking calls on the loop, every task tracked, every queue
  bounded — C-2.18), Ruff + Black (100 cols) + `mypy --strict`, **Pydantic v2** at every boundary,
  msgspec/orjson for hot serialization, `Decimal` for money/prices, tz-aware UTC, typed domain errors,
  order retries reuse `orderLinkId` (C-2.10), structured logs with `traceId` and no secrets.
- **Module boundaries** enforced by `import-linter` (CONSTITUTION §3); `packages/protocol/src/generated` is
  regenerated (`pnpm generate`, `AGENTS.md` §4) and committed, never hand-edited.

## 8. Commands

Command names are owned solely by `AGENTS.md` §4 (C-16.5) — read that table there; this file does not
mirror it, to avoid drift. The monorepo scaffold shipped with `E02-T11`, so `AGENTS.md` §4 mirrors the
real, runnable task graph (drift is caught by the `generated-code` required check). If a command doesn't
exist yet because its epic hasn't landed, say so in the PR — never invent an alternative.

## 9. Testing, security, and the NEVER list

**Testing** (owner: `AGENTS.md` §6, C-13, `03-testing-strategy.md`): tests first from Gherkin; right
pyramid level; deterministic (fake clock, seeded RNG, no `sleep`); **no network**, no filesystem outside
`tmp_path`; recorded, redacted Bybit fixtures only — never invent payload shapes; every bug fix ships a
regression test that fails without it; safety-critical modules (OMS, risk, rules, secrets, book) ≥95% +
mutation testing and an explicit native-SL assertion for every new order path; frontend tests query the
accessibility tree, assert keyboard nav and `axe`; engine: geometry unit tests + bench + golden images;
contract changes update provider **and** consumer tests. Flaky ⇒ quarantine within 24 h (C-9.3).

**Security** (owner: C-12, `04-security-program.md`, `SECURITY.md`): STRIDE per epic before first
implementation ticket; envelope-encrypted keys; TOTP for every user; RBAC server-side (Owner / Manager
scoped to assigned accounts); redaction filter on logs; demo/live isolation (C-2.11); rate-limit reserve
(C-12.7); new deps need justification + allowlisted licence + CODEOWNER (none into chart-engine without
an ADR). Suspected vulnerability ⇒ follow `SECURITY.md`, never a public issue.

**NEVER** (full list with rationale: `AGENTS.md` §8 — violations are incidents):
force-push/direct-push `main` · edit a merged migration · touch a C-10.2 security path without
`security-review` · skip/weaken any check (`--no-verify`,
bare `noqa`/`eslint-disable`/`type: ignore`, `.skip`/`.only`, lowering coverage, moving a bench
baseline) · widen scope · handle real credentials · call a live exchange from tests/CI/dev defaults ·
bypass a safety invariant (native SL, RBAC/risk, audit, withdrawal check, rate reserve, demo/live
isolation) · add out-of-scope features (C-1.2) · **approve or merge a design PR, or any PR you authored** · **mark a ticket Done** ·
invent UI not in the signed-off design · implement a `retired` ticket · call the statechart library
outside `cv.statechart.factory`.

## 10. Multi-agent coordination

The owner runs **several AI agents on this backlog in parallel**. Because of that, the delivery calendar is
**1-week sprints (Fri→Thu), Sprint 01 = 2026-09-25, GA cut = 2027-03-25** — story points per sprint are the
original 90; only the calendar is compressed (owner decision 2026-09-24; canonical dates in
`docs/plan/backlog/_tools/calendar_cv.py`, mirrored on the board's `Start`/`Due` fields). The pacing
constraint is the owner's review/sign-off bandwidth, so keep PRs small and evidence complete so reviews are fast.
These rules keep agents from colliding:

1. **Claim before you code.** Assign yourself on the GitHub issue, set project Status **In Progress**,
   and comment `claimed by <agent/session id> — branch <name>`. An issue already assigned or In Progress
   is **not available**; pick another. Release the claim (unassign + comment + Status back to Ready) if
   you stop.
2. **Respect `blocked_by`.** Only start when every blocker is Done. Epic `## Agent guidance` gives the
   dependency order and the parallel lanes — stay in your lane.
3. **File ownership.** Before editing a file, check open PRs/claimed tickets that touch it
   (`gh pr list --search`, the ticket's _Repo paths_). Never edit a file owned by another in-flight
   ticket without first
   commenting on that ticket and agreeing; otherwise, wait for it to merge and rebase.
4. **Interface first.** Changes to shared contracts — `packages/protocol` (OpenAPI `22-api-openapi.yaml`,
   WS `23-ws-protocol.md`), internal schemas (`24-internal-schemas.md`), DB migrations, statechart JSON —
   land in their own small PR **before** consumers (C-6.1, CONSTITUTION §7). Consumers rebase onto it; never propose
   a competing shape in parallel. Use draft PRs for interface stubs.
5. **Feature flags for incomplete work** (C-4.13, default off, removal ticket linked); never gate a safety
   invariant (C-4.14).
6. **Single-writer files.** Only one in-flight PR may add a migration (single-head check) or change
   `machine_hashes.lock`; coordinate via the ticket comments. Rebase, don't merge `main` in.
7. **Blocked? Stop loudly.** Comment with the exact failure/question, set Status **Blocked**, link the
   blocker — never work around a failing gate or silently change scope (`AGENTS.md` §9).
8. **Ticket JSON edits** only via Python, as `AGENTS.md` §3a says (it owns the recipe), then run
   `validate.py`. Keep individual file writes small (chunked) to avoid truncation.

## 10a. Project `.claude/` toolkit

- **Rules** (`.claude/rules/`, one concern each, pointers to the owners above): `00-constitution-pointers`,
  `10-branching-and-prs`, `20-python-backend`, `21-statecharts`, `22-exchange-adapter`, `30-frontend-react`,
  `31-chart-engine`, `40-testing`, `50-security`, `60-database-migrations`, `70-multi-agent`. Load the ones
  matching the paths you touch.
- **Subagents** (`.claude/agents/`): `backend-implementer`, `frontend-implementer`, `chart-engine-implementer`,
  `statechart-author`, `test-writer`, `security-reviewer`, `code-reviewer`, `ticket-triager`.
- **Commands**: `/pickup <issue#>`, `/ready-check`, `/statechart-new <B>`, `/pr`.
- **Skills** (`.claude/skills/`): `/candleviewer-relayroom-check` (manual RelayRoom identity/inbox check; see `docs/ops/relayroom-main-orchestrator-setup.md`).
- **Hooks** (`.claude/settings.json`): edits to applied migrations (C-5.4) and `xstate_statemachine` imports
  outside `statechart/` are blocked; after an edit you get a reminder of the package lint command.

## 11. Updating this file

- Change `CLAUDE.md` in the **same PR** as the change that made it stale (C-15.4); `docs` scope,
  CODEOWNER review.
- Keep it a pointer (< ~400 lines). Add a rule to its **owner** (`CONSTITUTION.md` via the amendment
  process C-16, or `AGENTS.md` §10) and link it here — never introduce a rule that exists only in
  this file, and never restate single-source lists (required-check names C-9.1).
- Every `C-x.y` cited here must exist in `CONSTITUTION.md` (checked by `pr-metadata`, C-16.4).
- Personal, machine-local preferences belong in `CLAUDE.local.md` (gitignored), not here.
