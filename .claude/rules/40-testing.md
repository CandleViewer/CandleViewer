---
description: Testing rules - pyramid, recorded Bybit fixtures, contract tests from OpenAPI/WS schemas, Playwright e2e, chaos list, test-quality rules.
---
# Testing

Source: `CONSTITUTION.md` §13 (C-13.1 to C-13.9), §9; `docs/plan/03-testing-strategy.md`; ADR-0012.

## Pyramid (C-13.1)
- About 70% unit / 20% integration + contract / 10% E2E by count.
- **Unit (C-13.2):** pure logic, no I/O: bar builders, footprint/profile/CVD/imbalance, book deltas, rounding,
  sizing, risk math, rule-IR evaluation, reducers, engine math. Use hypothesis / fast-check for invariants.
- **Integration (C-13.3):** anything crossing a process/store boundary: repositories vs real Postgres/QuestDB
  (docker compose), adapter vs recorded WS/REST replays, Alembic round-trips. Mark `@pytest.mark.integration`.
- **E2E (C-13.4):** only user-visible critical paths, Playwright, against a seeded stack (web + Electron smoke).

## Fixtures (C-13.5)
- Market/exchange data comes **only** from recorded, redacted Bybit captures in `packages/fixtures/bybit/`,
  one dated directory per capture. Each file has an entry in that directory's `manifest.json`: source, capture
  date, symbol, stream, host (its README).
- **No live-exchange calls in any test, local or CI.** Hosts `*.bybit.com`, `*.bytick.com` are denied.
- New fixture = recorded via the recorder tool, redacted (keys, signatures, UIDs, order ids), reviewed.

## Contract tests
- REST: provider + consumer tests generated from `docs/plan/22-api-openapi.yaml`; Schemathesis fuzz on `/v1`.
- WS: every frame validated against the schemas in `docs/plan/23-ws-protocol.md` / `packages/protocol`.
- Contract diff (breaking change detection) runs in CI job `contract`; breaking = `!` + ADR (CONSTITUTION §6).
- Statecharts: `tests/xstate_contract/` is a blocking gate (see `21-statecharts.md`).

## Quality rules (C-13.7)
- No sleeps: fake clocks, event waiters, `asyncio.Event`. No network. No shared mutable global state.
- Deterministic: seed randomness; freeze time; order-independent (pytest-randomly / vitest shuffle).
- One behaviour per test, named `test_<unit>_<condition>_<expected>`.
- Flaky test: quarantine with `@flaky` within 24 h + P1 ticket (C-9.3). Never delete to go green.
- Each feature has a QA black-box plan in its ticket plus white-box tests (C-13.8).

## Coverage gates (CONSTITUTION §9)
- `services/api/**` >=85% line, >=75% branch; `packages/chart-engine/**` >=85%; `apps/web`, `packages/ui` >=80%.
- Never lower a threshold; no decrease vs `main`.

## Chaos (C-13.6, nightly, required before release)
The 14-scenario list is owned by C-13.6; do not copy it. When a ticket touches reconnect, OMS, fan-out,
recorder, storage or backpressure, name the chaos scenario number(s) it affects in the PR.

## Performance (C-13.9)
- k6 (REST + WS fan-out), Locust ingestion soak, engine benchmarks (`31-chart-engine.md`).
