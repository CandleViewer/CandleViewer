# Derivatives golden and parity manifest (E24-T06, OI half)

Parity of the derivatives engine (`candleviewer/orderflow/derivatives.py`) against an independent
offline DuckDB reference. Harness: `services/api/tests/golden/e24/` (reference SQL in
`reference/oi.sql` and `reference/funding_basis.sql`; the reference imports no engine code).

Files: `cases.json` (the case manifest), `expected_<case>.json.gz` (the engine's canonical JSON per
default-lane case: sorted keys, Decimal as string), `summary.json` (bars and sha256 per case).
`CV_REGEN_GOLDEN=1 pytest .../test_derivatives_parity.py -k golden_matches` rewrites them; review
the diff; it is refused when `CI` or `GITHUB_ACTIONS` is set; there is no version guard because the engine carries no `ALGO_VERSION`.

## Provenance and the corpus deviation (C-13.5)

Inputs are referenced by id (their path in `packages/fixtures/bybit/2026-10-05/manifest.json`),
never copied: three 1 m kline pages (450 bars, 2023-11-14T22:13Z to 05:42Z), two 5 min OI pages,
`ws/burst_tickers_BTCUSDT.jsonl` (22:13:20 to 22:14:20, deltas folded into cumulative snapshots),
and the BTC 8 h / ETH 4 h funding history. These are `documented-shape (exception #1778 A)`
files, generated, not a live capture. **Deviation: this is NOT a recorded symbol-day** (AC1 says
recorded). A real capture drops in as new `cases` entries plus a `fixture_dir`; no harness code
changes. Like the big-trade golden, it stays "not a symbol-day" until the E16 capture exists.
Declared loader transforms (nothing else is synthesised):
- the REST OI history has no USD value, so `open_interest_value = openInterest * 60000`
  (`oi_value_price`, one constant applied to engine and reference alike);
- a coarser bar folds the 1 m klines (first open, last close);
- `drops` remove whole rows from the OI or ticker stream by half-open `[from_ms, to_ms)` span
  (the no-OI bar and the recorder gap, modelled on a `recording_gaps` row);
- the `paired` 4 h case runs the BTCUSDT grid, OI and tickers with the ETHUSDT 4 h settled rows
  (the corpus has no ETH grid).

## Cases

| id | lane | what it proves |
| --- | --- | --- |
| `btc_8h_slice` | PR | 150 1 m bars; UTC day boundary and the 8 h settlement inside |
| `btc_8h_no_oi` | PR | six OI samples dropped: no-OI bars, a bounded carry, an expired open |
| `btc_8h_15m_stale_open` | PR | 15 min bars, three samples dropped: a stale open gives delta None, never 0 |
| `btc_8h_recorder_gap` | PR | head span with no OI and no ticker: settled funding, basis None |
| `btc_4h_paired` | PR | 4 h funding, annualisation factor 2190 |
| `btc_8h_15m` | PR | 15 min bars: the OI delta is non-zero, the quadrant classifies |
| `btc_8h_full`, `btc_4h_paired_full`, `btc_8h_5m_full` | `harness` | the whole 450-bar window |

**Follow-up PR once #5273 lands** (needs `ws/allLiquidation_BTCUSDT_burst.jsonl`, listed in
`cases.json` under `follow_up_cases`): `btc_8h_cascade` (per-side buckets, the split at 00:00),
`btc_8h_liquidation_dedup` (twin prints and the replayed push, counted once), `reference/
liquidations.sql`, the `liquidation_notional` series (both/long/short) and mutation 4. The
scheduled nightly workflow and its divergence-count artifact upload are also a later PR; the
harness already writes the counts when `CV_PARITY_SUMMARY=<path>` is set.

## Comparison rule

Numbers load as `DECIMAL(38,18)`, never `DOUBLE`. Exact equality for every series and None-ness
everywhere, except two declared divisions: `funding_annualized` and `premium_pct` (last, mark),
`abs diff <= 5e-19` for annualised (half the reference's 1e-18 step) and `<= 1e-12` for premium (`TOLERANCE` in `_parity.py`, asserted by a test). DuckDB decimal division is
`DOUBLE`, so the reference divides in exact `HUGEINT` arithmetic rounded half away from zero (1e-18
for annualised, 1e-12 for premium); the engine divides at 28 digits, half-even. Every series is read
through `metric_value`. `time_to_funding_ms` is the per-bar value (last snapshot, `next - ts`,
floored at 0); the live-clock `time_to_funding_ms(now, offset)` is not compared.

## Spec-by-ruling (not stated in 24 §7.2)

The OI staleness bound of 600 000 ms (the open sample is absent past it, never carried; #723 BQ-5)
and "a flat price or a flat OI delta classifies nothing" (quadrant None). The SQL headers cite them.

## Parquet

The harness writes the rows as Parquet in `tmp_path` with plain DuckDB (tickers hive-partitioned
`symbol=/dt=`; OI `symbol,ym`; funding `symbol,y`, the registered cold-tier templates) and the
SQL reads them with `read_parquet(..., hive_partitioning=true)`. It does not go through the storage
code; production rolls off only trades, order-book deltas, tickers and liquidations, so OI and
funding have no production Parquet path yet.
