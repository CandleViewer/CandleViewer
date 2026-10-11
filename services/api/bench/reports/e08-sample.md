# E08-Q04 ingestion performance report — FAIL

- Harness: `e08-q04/1` · machine profile: `laptop-i7-8550U`
- Run: 2026-10-11T14:39:07Z → 2026-10-11T14:39:56Z
- Grafana range: `from=1791729547393&to=1791729596553`
- Data: recorded corpus `packages/fixtures/bybit/2026-10-05` + seeded synthetic feed; no network.

## soak_steady — Steady-state soak, >=3 symbols (budgets #5, #8, #11, #12 + ±5% memory flatness) — PASS (gate PASS)

Profile `smoke`. Scaling: 90 s of scenario time on a virtual clock (runs ~20x faster than 1x on the laptop), sample every 5 s; flatness baseline at the same 1/12 fraction (t=7.5 s)

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| undetected_loss | #5 | 0 | 0 | events | pass |
| rss_per_symbol_p95 | #8 | 36.2 | 300 | MB | pass |
| vcpu_per_symbol_p95 | #11 | 0.03229 | 0.5 | vCPU | pass |
| storage_gb_day_symbol — modelled bytes/row (E16-K01) | #12 | 0.114 | 0.75 | GB/day | pass |
| memory_flatness — max deviation from the t=10s baseline sample | ±5% | 0.0343 | 0.05 | ratio | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| event_loop_lag_ms | 2.13 | 2.739 | 2.739 | 19 |
| ingest_lag_ms | 0.1127 | 0.4025 | 1.28 | 5400 |
| queue_depth | 0 | 0 | 0 | 19 |
| rss_mb_per_symbol | 36.05 | 36.2 | 36.2 | 19 |
| sampling_cost_ms | 0.08467 | 0.08467 | 0.08467 | 19 |
| vcpu_per_symbol | 0.02813 | 0.03229 | 0.03229 | 18 |

RSS curve (MiB):

<svg xmlns="http://www.w3.org/2000/svg" width="480" height="120" role="img" aria-label="RSS 102.2-108.6 MiB over 90 s"><polyline fill="none" stroke="black" points="0.0,120.0 26.7,93.8 53.3,67.9 80.0,43.6 106.7,16.9 133.3,14.2 160.0,12.2 186.7,11.0 213.3,10.8 240.0,8.7 266.7,8.4 293.3,7.5 320.0,6.1 346.7,4.0 373.3,2.8 400.0,2.8 426.7,1.6 453.3,0.4 480.0,0.0"/></svg>

Baseline gate: **PASS** (no baseline recorded)

## aggregate_10sym — 10-symbol aggregate steady state: per-symbol task isolation — PASS (gate PASS)

Profile `smoke`. Scaling: 60 s virtual clock, 10 symbols, BTCUSDT 3x for 30 s

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| undetected_loss | #5 | 0 | 0 | events | pass |
| cross_symbol_lag_band — worst=SYN03USDT p95=0.435ms (0.00x band) | #5/#6 | 0.004141 | 1 | x band | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| loaded_symbol_lag_ms | 0.0953 | 0.4873 | 1.134 | 1800 |
| max_backlog | 0 | 0 | 0 | 1 |
| recovery_s | 0 | 0 | 0 | 1 |
| unaffected_lag_loaded_ms | 0.1544 | 0.3869 | 9.797 | 5400 |

Baseline gate: **PASS** (no baseline recorded)

## burst_5x — Burst injector: 5x trade+orderbook rate for 60 s on one symbol (06-perf §6.4) — PASS (gate PASS)

Profile `smoke`. Scaling: burst shortened to 10 s (15-25 s) on a virtual clock, backlog bound scaled with it; same assertions

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| undetected_loss | #5 | 0 | 0 | events | pass |
| cross_symbol_lag_band — worst=SYN04USDT p95=0.504ms (0.00x band) | #5/#6 | 0.004797 | 1 | x band | pass |
| queue_growth_bounded | #5 | 200 | 400 | events | pass |
| recovery_s — burst end -> backlog empty | #5 | 3.3 | 30 | s | pass |
| backpressure_applied — the burst must actually exercise backpressure | #5 | 95 | 1 | events | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| loaded_symbol_lag_ms | 1000 | 1900 | 2000 | 800 |
| max_backlog | 200 | 200 | 200 | 1 |
| recovery_s | 3.3 | 3.3 | 3.3 | 1 |
| unaffected_lag_loaded_ms | 0.1138 | 0.4798 | 1.264 | 1800 |

Baseline gate: **PASS** (no baseline recorded)

## rest_k6 — k6 REST profile: instruments, klines (cold/warm/page-boundary), trades, orderbook, data-coverage (budget #13) — FAIL (gate PASS)

Profile `smoke`. Scaling: in-process httpx ASGI driver (no sockets, no k6) issuing the same request plan, 12 rounds at concurrency 5

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| rest_p95[data_coverage] | #13 | 118.1 | 150 | ms | pass |
| rest_p95[instruments] | #13 | 106.8 | 150 | ms | pass |
| rest_p95[klines_cold] | #13 | 645.5 | 150 | ms | FAIL |
| rest_p95[klines_page_boundary] | #13 | 524.1 | 150 | ms | FAIL |
| rest_p95[klines_warm] | #13 | 18.96 | 150 | ms | pass |
| rest_p95[orderbook] | #13 | 114.6 | 150 | ms | pass |
| rest_p95[trades] | #13 | 109 | 150 | ms | pass |
| klines_cache_speedup — cold p95 645.48ms vs warm p95 18.96ms | #13 | 34.05 | 2 | x | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| rest_data_coverage_ms | 2.795 | 118.1 | 118.1 | 12 |
| rest_instruments_ms | 2.189 | 106.8 | 106.8 | 12 |
| rest_klines_cold_ms | 482.1 | 645.5 | 645.5 | 12 |
| rest_klines_page_boundary_ms | 460.5 | 524.1 | 524.1 | 12 |
| rest_klines_warm_ms | 7.16 | 18.96 | 18.96 | 12 |
| rest_orderbook_ms | 2.711 | 114.6 | 114.6 | 12 |
| rest_trades_ms | 3.656 | 109 | 109 | 12 |

Baseline gate: **PASS** (no baseline recorded)

## latency_internal — Backend-internal latency: ingestion receipt -> internal publish (§5.1 spans, E08 slice of #6) — PASS (gate PASS)

Profile `smoke`. Scaling: 30 s virtual clock, 3 symbols, every trade frame stage-stamped

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| receipt_to_publish_p95 — E08 slice (parse+derive); fan-out slice is E17 | #6 | 0.531 | 20 | ms | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| receipt_to_publish_ms | 0.271 | 0.531 | 0.707 | 900 |
| stage_derive_ms | 0.217 | 0.433 | 0.652 | 900 |
| stage_parse_ms | 0.053 | 0.097 | 0.147 | 900 |

Baseline gate: **PASS** (no baseline recorded)

## ratelimit_headroom — Rate-limit headroom: catalogue refresh + backfill paging under the per-UID bucket (C-12.7) — PASS (gate PASS)

Profile `smoke`. Scaling: 120 s virtual time, same rates

| check | budget | measured | limit | unit | result |
|---|---|---:|---:|---|---|
| min_bucket_headroom — headroom must never reach zero | C-12.7 | 6 | 0 | tokens | pass |
| provoked_10018 | C-12.7 | 0 | 0 | responses | pass |

| metric | p50 | p95 | max | n |
|---|---:|---:|---:|---:|
| ip_window_headroom_min | 584 | 584 | 584 | 362 |
| uid_tokens | 9 | 10 | 10 | 362 |

Baseline gate: **PASS** (no baseline recorded)
