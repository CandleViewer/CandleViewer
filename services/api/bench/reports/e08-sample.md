# E08-Q04 ingestion performance report — FAIL

- Harness: `e08-q04/1` · machine profile: `laptop-i7-8550U`
- Run: 2026-10-11T14:48:18Z → 2026-10-11T14:48:58Z
- Grafana range: `from=1791730098962&to=1791730138758`
- Data: recorded exchange corpus (capture 2026-10-05) + seeded synthetic feed; no network.

## soak_steady — Steady-state soak, >=3 symbols (budgets #5, #8, #11, #12 + ±5% memory flatness) — PASS (gate WARN)

Profile `smoke`. Scaling: 90 s of scenario time on a virtual clock (runs ~20x faster than 1x on the laptop), sample every 5 s; flatness baseline at the same 1/12 fraction (t=7.5 s)

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| undetected_loss | #5 | 0 | 0 | events | pass |
| rss_per_symbol_p95 | #8 | 36.21 | 300 | MB | pass |
| vcpu_per_symbol_p95 | #11 | 0.03021 | 0.5 | vCPU | pass |
| storage_gb_day_symbol — modelled bytes/row (E16-K01) | #12 | 0.114 | 0.75 | GB/day | pass |
| memory_flatness — max deviation from the t=10s baseline sample | ±5% | 0.03372 | 0.05 | ratio | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| event_loop_lag_ms | 2.218 | 5.026 | 5.026 | 19 |
| ingest_lag_ms | 0.1192 | 0.3932 | 2.213 | 5400 |
| queue_depth | 0 | 0 | 0 | 19 |
| rss_mb_per_symbol | 36.04 | 36.21 | 36.21 | 19 |
| sampling_cost_ms | 0.08607 | 0.08607 | 0.08607 | 19 |
| vcpu_per_symbol | 0.02708 | 0.03021 | 0.03021 | 18 |

RSS curve (MiB):

<svg xmlns="http://www.w3.org/2000/svg" width="480" height="120" role="img" aria-label="RSS 102.3-108.6 MiB over 90 s"><polyline fill="none" stroke="black" points="0.0,120.0 26.7,93.7 53.3,66.8 80.0,42.7 106.7,16.4 133.3,14.2 160.0,11.9 186.7,11.6 213.3,10.9 240.0,9.6 266.7,8.7 293.3,7.5 320.0,6.3 346.7,4.8 373.3,3.6 400.0,2.4 426.7,1.3 453.3,0.7 480.0,0.0"/></svg>

Baseline gate: **WARN** (baseline marked warn-only until a CI-runner baseline exists)
- WARN event_loop_lag_ms: p95 5.026 vs baseline 2.739 (+83.5%, fail band 25%)

| metric | baseline p95 | run p95 | change |
|---|---:|---:|---:|
| event_loop_lag_ms | 2.739 | 5.026 | +83.5% |
| ingest_lag_ms | 0.4025 | 0.3932 | -2.3% |
| queue_depth | 0 | 0 | +0.0% |
| rss_mb_per_symbol | 36.2 | 36.21 | +0.0% |
| sampling_cost_ms | 0.08467 | 0.08607 | +1.6% |
| vcpu_per_symbol | 0.03229 | 0.03021 | -6.5% |

## aggregate_10sym — 10-symbol aggregate steady state: per-symbol task isolation — PASS (gate PASS)

Profile `smoke`. Scaling: 60 s virtual clock, 10 symbols, BTCUSDT 3x for 30 s

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| undetected_loss | #5 | 0 | 0 | events | pass |
| cross_symbol_lag_band — worst=ETHUSDT p95=0.267ms (0.00x band) | #5/#6 | 0.002543 | 1 | x band | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| loaded_symbol_lag_ms | 0.0636 | 0.3344 | 0.6938 | 1800 |
| max_backlog | 0 | 0 | 0 | 1 |
| recovery_s | 0 | 0 | 0 | 1 |
| unaffected_lag_loaded_ms | 0.1168 | 0.2563 | 0.6874 | 5400 |

Baseline gate: **PASS** (baseline marked warn-only until a CI-runner baseline exists)

| metric | baseline p95 | run p95 | change |
|---|---:|---:|---:|
| loaded_symbol_lag_ms | 0.4873 | 0.3344 | -31.4% |
| max_backlog | 0 | 0 | +0.0% |
| recovery_s | 0 | 0 | +0.0% |
| unaffected_lag_loaded_ms | 0.3869 | 0.2563 | -33.8% |

## burst_5x — Burst injector: 5x trade+orderbook rate for 60 s on one symbol (06-perf §6.4) — PASS (gate PASS)

Profile `smoke`. Scaling: burst shortened to 10 s (15-25 s) on a virtual clock, backlog bound scaled with it; same assertions

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| undetected_loss | #5 | 0 | 0 | events | pass |
| cross_symbol_lag_band — worst=SYN00USDT p95=0.273ms (0.00x band) | #5/#6 | 0.002596 | 1 | x band | pass |
| queue_growth_bounded | #5 | 200 | 400 | events | pass |
| recovery_s — burst end -> backlog empty | #5 | 3.3 | 30 | s | pass |
| backpressure_applied — the burst must actually exercise backpressure | #5 | 95 | 1 | events | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| loaded_symbol_lag_ms | 1000 | 1900 | 2000 | 800 |
| max_backlog | 200 | 200 | 200 | 1 |
| recovery_s | 3.3 | 3.3 | 3.3 | 1 |
| unaffected_lag_loaded_ms | 0.0739 | 0.2501 | 1.459 | 1800 |

Baseline gate: **PASS** (baseline marked warn-only until a CI-runner baseline exists)

| metric | baseline p95 | run p95 | change |
|---|---:|---:|---:|
| loaded_symbol_lag_ms | 1900 | 1900 | -0.0% |
| max_backlog | 200 | 200 | +0.0% |
| recovery_s | 3.3 | 3.3 | +0.0% |
| unaffected_lag_loaded_ms | 0.4798 | 0.2501 | -47.9% |

## rest_k6 — k6 REST profile: instruments, klines (cold/warm/page-boundary), trades, orderbook, data-coverage (budget #13) — FAIL (gate WARN)

Profile `smoke`. Scaling: in-process httpx ASGI driver (no sockets, no k6) issuing the same request plan, 12 rounds at concurrency 5

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| rest_p95[data_coverage] | #13 | 108.3 | 150 | ms | pass |
| rest_p95[instruments] | #13 | 99.18 | 150 | ms | pass |
| rest_p95[klines_cold] | #13 | 527.5 | 150 | ms | FAIL |
| rest_p95[klines_page_boundary] | #13 | 467.7 | 150 | ms | FAIL |
| rest_p95[klines_warm] | #13 | 63.65 | 150 | ms | pass |
| rest_p95[orderbook] | #13 | 3.418 | 150 | ms | pass |
| rest_p95[trades] | #13 | 12.42 | 150 | ms | pass |
| klines_cache_speedup — cold p95 527.51ms vs warm p95 63.65ms | #13 | 8.288 | 2 | x | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| rest_data_coverage_ms | 2.229 | 108.3 | 108.3 | 12 |
| rest_instruments_ms | 2.089 | 99.18 | 99.18 | 12 |
| rest_klines_cold_ms | 412 | 527.5 | 527.5 | 12 |
| rest_klines_page_boundary_ms | 388.8 | 467.7 | 467.7 | 12 |
| rest_klines_warm_ms | 6.052 | 63.65 | 63.65 | 12 |
| rest_orderbook_ms | 2.325 | 3.418 | 3.418 | 12 |
| rest_trades_ms | 3.298 | 12.42 | 12.42 | 12 |

Baseline gate: **WARN** (baseline marked warn-only until a CI-runner baseline exists)
- WARN rest_klines_warm_ms: p95 63.65 vs baseline 18.96 (+235.7%, fail band 25%)

| metric | baseline p95 | run p95 | change |
|---|---:|---:|---:|
| rest_data_coverage_ms | 118.1 | 108.3 | -8.3% |
| rest_instruments_ms | 106.8 | 99.18 | -7.1% |
| rest_klines_cold_ms | 645.5 | 527.5 | -18.3% |
| rest_klines_page_boundary_ms | 524.1 | 467.7 | -10.8% |
| rest_klines_warm_ms | 18.96 | 63.65 | +235.7% |
| rest_orderbook_ms | 114.6 | 3.418 | -97.0% |
| rest_trades_ms | 109 | 12.42 | -88.6% |

## latency_internal — Backend-internal latency: ingestion receipt -> internal publish (§5.1 spans, E08 slice of #6) — PASS (gate PASS)

Profile `smoke`. Scaling: 30 s virtual clock, 3 symbols, every trade frame stage-stamped

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| receipt_to_publish_p95 — E08 slice (parse+derive); fan-out slice is E17 | #6 | 0.292 | 20 | ms | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| receipt_to_publish_ms | 0.237 | 0.292 | 0.584 | 900 |
| stage_derive_ms | 0.191 | 0.238 | 0.47 | 900 |
| stage_parse_ms | 0.046 | 0.056 | 0.155 | 900 |

Baseline gate: **PASS** (baseline marked warn-only until a CI-runner baseline exists)

| metric | baseline p95 | run p95 | change |
|---|---:|---:|---:|
| receipt_to_publish_ms | 0.531 | 0.292 | -45.0% |
| stage_derive_ms | 0.433 | 0.238 | -45.0% |
| stage_parse_ms | 0.097 | 0.056 | -42.3% |

## ratelimit_headroom — Rate-limit headroom: catalogue refresh + backfill paging under the per-UID bucket (C-12.7) — PASS (gate PASS)

Profile `smoke`. Scaling: 120 s virtual time, same rates

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| min_bucket_headroom — headroom must never reach zero | C-12.7 | 6 | 0 | tokens | pass |
| provoked_ip_limit | C-12.7 | 0 | 0 | responses | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| ip_window_headroom_min | 584 | 584 | 584 | 362 |
| uid_tokens | 9 | 10 | 10 | 362 |

Baseline gate: **PASS** (baseline marked warn-only until a CI-runner baseline exists)

| metric | baseline p95 | run p95 | change |
|---|---:|---:|---:|
| ip_window_headroom_min | 584 | 584 | +0.0% |
| uid_tokens | 10 | 10 | +0.0% |
