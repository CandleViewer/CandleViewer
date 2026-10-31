"""E16-Q04 recorder perf pack (#481): the ingest load, the soak and the API/WS load's fixture app.

- `generator.py`: a seeded message mix (trade bursts, depth churn, liquidation cascades) built on
  the recorded corpus through the E08 normalisers, with a produced-row counter (the oracle's side).
- `harness.py`: drives the real `StreamWriter` with that mix, on wall time (the ingest load) or a
  virtual clock (the soak), and samples flush time, RSS, backlog, spill and drops.
- `budgets.py`: the pure pass/fail checks (06-performance budgets, ticket perf notes).
- `ingest_load.py`, `soak.py`: one command each; exit 1 when a hard budget fails.
- `api_app.py`: the loopback app `tests/load/k6/recorder_api.js` loads (status, coverage, WS).

Offline only (C-13.5): the corpus is `packages/fixtures/<venue>/2026-10-05`; no exchange client is
built. Baselines: `bench/baselines/e16/` (provisional until the live re-measure, #1778).

    uv run python -m bench.recorder.ingest_load --profile smoke
    uv run python -m bench.recorder.soak --profile smoke
    uv run python -m bench.recorder.api_app            # then k6, see recorder_api.js
"""

#: Bumped when a metric's definition changes: `gate.compare` reads no baseline from another version.
HARNESS_VERSION = "e16-q04/1"
