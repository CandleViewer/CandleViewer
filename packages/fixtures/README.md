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

**No fixture in this package may originate from a live network call in a test
or CI run.** Fixtures are recorded via the (future) recorder tool and reviewed
before commit.

## Golden provenance (C-13.5)

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
