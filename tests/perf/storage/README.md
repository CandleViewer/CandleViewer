# Storage performance harness (E07-Q03)

Run: `CV_ENV=test uv run --project services/api python tests/perf/storage/harness.py`
(`--update-baseline` rewrites `baseline.json`; exits 1 and prints shape + delta when a warm p95 is >20 % over baseline).
Unit tests: `CV_ENV=test uv run --project services/api pytest tests/perf/storage`.

## R0 numbers (results.json, dev box, unrestricted CPU/mem)

**Conditions: no docker/QuestDB.** Query shapes #1-#11 run on an in-process DuckDB *proxy* over a seeded 20 000-row
dataset (regression baseline only; not comparable to section 13.2 targets). Ingest drives the real `IlpWriter`
over a real loopback TCP socket into a sink that throttles reads (kernel buffers fill, `drain()` blocks).
Cold samples run in a fresh subprocess + fresh DuckDB instance each (OS page cache cannot be dropped without root).

| Measure | R0 value | Target |
|---|---|---|
| Ingest sustained (3 s) | ~45k rows/s, 140 000 sent = 140 000 received, 0 dropped | >=600k (QuestDB) / 25k realistic |
| Ingest stress (throttled sink) | ~14.8k rows/s, backpressure onset recorded, 50 000 = 50 000, 0 dropped | never drop trades |
| Real `Reaper.run()` loop lag (1200 partitions) | max 118 ms (threshold 50-100 ms): **over**; defect #1826 (E07-T05-B1); local rerun not possible (no docker), re-measure on CI runner | 50-100 ms |
| 24 h growth | **not measured**: CI QuestDB diskSize deltas are 16 MiB page-allocation multiples (see 21-database-schema 11.1 note); R0 proxy figure withdrawn | 0.5-0.75 total |

Overflow policy (C-2.18): the ILP writer blocks the producer and self-flushes when its bounded queue is full — rows are never dropped (see #1835).
Gate check: `test_baseline_gate_fires_on_deliberate_slowdown` injects a 50 ms slowdown and asserts regressions fire.
Not run (needs docker / hours): 10-minute ingest, 12-month scans, reference 4 vCPU/8 GB profile -> deferred to nightly - tracked in #1778 A (owner exception).

## Real-engine harness (CI `integration` job)

`services/api/tests/integration/storage/test_storage_perf_harness.py` (`integration` + `perf`) drives the real
`IlpWriter` and `Reaper` against QuestDB 8.1.1, writes `services/api/build/reports/storage-perf.json` (artifact
`storage-perf`), and fails when a metric is >20 % and >25 ms over `baseline_integration.json`.
"Cold" = fresh connection + untouched partition; the OS page cache is **not** dropped (no root in CI).

## Nightly (`perf-storage-nightly.yml`)

Runs both harnesses (DuckDB shapes + real-QuestDB testcontainers suite; docker is available on `ubuntu-latest`) and
uploads `results.json` + `storage-perf.json`. A perf-gate failure opens a `perf` issue (AC2): the proxy harness's >20 %
baseline gate (exit 1) or a failed real-engine perf test (pytest exit 1); any other failure fails the job without one.
The real-engine run is `--no-cov`: `services/api`'s coverage floor applies to the whole package, which four perf tests cannot reach (#3429).
The 24 h growth figure and the 4 vCPU / 8 GB profile remain **unmeasured** until a nightly run yields non-quantized
numbers (follow-up on #274); this PR does not claim them. Not run locally: no docker.
