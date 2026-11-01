# @candleviewer/fixtures

Recorded, **redacted** Bybit fixtures + golden outputs, shared by the
TypeScript and Python test suites (CONSTITUTION.md C-13.5, `.claude/rules/40-testing.md`).

## Layout

- `raw/` — recorded WS/REST captures (redacted: no API keys, signatures,
  UIDs, or order ids tied to a real account).
- `golden/` — expected outputs (bar aggregation, footprint, decoders) for
  regression comparisons.
- `accounts/` — the E27 accounts and key-vault fault-injection pack: one
  directory per scenario with a `manifest.json` (see `accounts/README.md`).
- `scripts/verify.mjs` — the redaction gate: fails if any file under `raw/`,
  `golden/`, `bybit/` or `accounts/` contains a credential-shaped string (API
  key, signature, `Authorization` header, PEM key block), or a bare
  key-shaped token under `accounts/`, and runs the accounts pack checks. Every
  new fixture must pass this before being committed (E02-X01 threat:
  "recorded fixture leaks credentials").
- `scripts/accounts-pack.mjs` — the accounts pack's schema and structure checks,
  and its comparison with the E27 test plan's section 9.3 table
  (`qa/plans/e27-accounts-test-plan.md`).
- `turbo.json` — makes every data file and that plan an input of `lint` and the
  tests, so a data-only change can never be answered from a cached run.

## `e2e` subpath: shared Playwright support (E10-Q02)

`@candleviewer/fixtures/e2e` and `@candleviewer/fixtures/e2e/stubs` (TypeScript, `src/e2e/`) are
the support both E2E suites share: `apps/desktop` imports them and never `apps/web` (C-3.5). Test-only,
never bundled into an app; stubs only, no secret, no live backend, no exchange (C-13.5).

| Module    | What it gives                                                                                                  |
| --------- | -------------------------------------------------------------------------------------------------------------- |
| `stubs`   | Network-layer API stubs (`stubSession`, `json`, the leak guard); `apps/web/e2e/support/api.ts` re-exports them |
| `routes`  | `ROUTE_EXPECTATIONS`: the declared outcome of every route id × role, and the landing classifier                |
| `outcome` | `expectSettledOutcome`: a landing classified the same three reads in a row, no fixed sleep                     |
| `csp`     | `sr112Findings`: a policy compared with SR-112 directive by directive, plus SR-119's exchange-host ban         |
| `egress`  | The egress guard for a browser context and for the Electron main process (loopback only)                       |
| `capture` | Capture conventions for the screenshot corpus: frozen clock, no motion, fixed viewports, capture twice         |

`bin/flaky-summary.mjs` writes a Playwright JSON report's counts to the CI job summary. The unit
tests of the pure helpers are `test/e2e/`; the test plan is `docs/qa/e10-shell-test-plan.md`.

**No fixture in this package may originate from a live network call in a test
or CI run.** Fixtures are recorded via the (future) recorder tool and reviewed
before commit.

## Golden provenance (C-13.5)

- `src/synthetic-ticks.mjs` — seeded synthetic price-tick generator (`generateTicks`,
  `generatePresetTicks`; presets `burst` 40 Hz for 5 s, `idle` 0.2 Hz, `steady-40hz`). Source:
  synthetic, seeded (mulberry32), no recording; rate: configurable, default 40 Hz; purpose:
  flash-rate harness for E47-S04 / G005; env: none; redaction: n/a, nothing recorded. Not a venue
  payload (C-13.5 not engaged). Timestamps come from a fake clock, prices are integer ticks plus a
  decimal string.
- `golden/bars/time_bars_BTCUSDT.jsonl` — E12-S01 time bars (1m/5m/1h, one bar per line).
  Source: corpus `bybit/2026-10-05/ws/clean_publicTrade_BTCUSDT.jsonl`; date 2026-10-05; symbol
  BTCUSDT; env: public live stream shape (no account data); redaction: derived output of an
  already-redacted corpus, no identifiers. Regenerate from `services/api` with
  `CV_REGEN_GOLDEN=1 pytest tests/unit/bars/test_time_builder_golden.py` and review the diff.
- `golden/bars/activity_bars_BTCUSDT.jsonl` — E12-S02 tick/volume bars (tick:50, tick:500, vol:5,
  vol:0.25, one bar per line). Source: same corpus, date, symbol and env as above; redaction: derived
  output of an already-redacted corpus, no identifiers. Regenerate with
  `CV_REGEN_GOLDEN=1 pytest tests/unit/bars/test_activity_builders_golden.py` and review the diff.
- `golden/bars/threshold_bars_BTCUSDT.jsonl` — E12-S03 range/delta bars (range:20, delta:1,
  delta:2, one bar per line; the ticket's `delta:500` is replaced by delta:1/2 because it would
  yield a single bar on this 137 BTC day). Source: same corpus, date, symbol and env as
  above; redaction: derived output of an already-redacted corpus, no identifiers. Regenerate with
  `CV_REGEN_GOLDEN=1 pytest tests/unit/bars/test_threshold_builders_golden.py` and review the diff.
- `golden/bigtrade/` — E22-T04 big-trade golden (trades input, expected events for three
  configurations, `algo_version`). Provenance, deviation (2.99 h window, not a symbol-day) and
  regeneration (needs an `ALGO_VERSION` bump): see `golden/bigtrade/README.md`.
- `golden/indicators/` — E13-T02 indicator-kernel golden vectors: densified input bars
  (`inputs_*.jsonl`), per-case kernel float64 outputs and exact-reference values
  (`vectors_*.jsonl`), `spec_hash_vectors.json` and `manifest.json` (sha256, build versions,
  tolerance), read by the Python kernel tests, the TS worker mirror (E13-T01) and the parity pack
  (E13-Q05). Sources: `bybit/2026-10-05/rest/kline_BTCUSDT_1_page{0,1,2}.json` (450 1m klines,
  bars 200-214 removed and refilled by `densify()`), `golden/bars/time_bars_BTCUSDT.jsonl` (1m)
  and a seeded offline synthetic day; date 2026-10-05; symbol BTCUSDT; env: public market data,
  no account data; redaction: derived output of already-redacted fixtures, no identifiers. No
  recorded symbol-day exists yet (exception #1778 A). Regenerate with
  `CV_REGEN_GOLDEN=1 pytest tests/unit/orderflow/indicators/test_golden_vectors.py` and review
  the diff; a changed kernel output needs that kernel's `build_version` bumped and its output
  digest re-pinned in that test (`KERNEL_OUTPUT_PINS`), which regeneration does not touch.
- `golden/rule-ir/hash_vectors.json` — E37-T01 rule IR hash vectors: per request body, the server's
  canonical bytes, `ir_hash` and form reasons, or its refusal; the reference for the client mirror
  in `packages/rule-graph`. Sources: `services/api/tests/fixtures/rule_corpus/` (the 30 rules), then
  edge, quirk and refused variants of `services/api/tests/fixtures/rule_ir/form_simple_0.json`.
  Date 2026-10-22; no recorded data (symbols and account ids appear only as rule values), no
  credentials. Written and byte-checked by `tests/rules/roundtrip/test_client_hash_vectors.py`;
  regenerate with `CV_REGEN_GOLDEN=1` on that test and review the diff.
- `golden/storage/storage_usage_baseline.golden.json` — E07-D02 frozen `StorageUsage` baseline for
  E16 (the 13-field body of `GET /recording/storage`, one sample). Source: the real
  `DiskBudget.sample_once()` on a fake meter, served by the real route as the Owner; date
  2026-11-01; env: demo; no recording and no measurement of any disk; redaction: none needed, sample
  figures only, no path, no id, no secret. Read by `services/api/tests/contract/storage/` and meant
  for E16's mock layer. Regenerate from `services/api` with
  `python -m tests.contract.storage.test_storage_usage_verification --write-baseline`.

## Scripts

- `pnpm --filter @candleviewer/fixtures lint` — ESLint, then `scripts/verify.mjs`
  (the redaction gate and the accounts pack checks), then the Vitest suite
  (`vitest run`, the `test` script's run). This is how CI runs the gate and the
  suite: the js lane's `lint` job schedules this package whenever a file in it
  changes, while CI's unit-test jobs filter to other packages. The security
  lane's `scripts/check_secrets_hygiene.py` repeats the accounts key-shape rule
  (see `accounts/README.md`, "Checks").
- `pnpm --filter @candleviewer/fixtures verify` — `scripts/verify.mjs` alone.
- `pnpm --filter @candleviewer/fixtures test` — Vitest unit tests for the
  verify script and the accounts pack checks, which also run both over the
  real fixtures and over planted copies (CLI exit codes included).
