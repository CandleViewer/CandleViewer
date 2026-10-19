# Bybit fixture corpus (E08-T05)

The shared, offline input set for every E08 test (`24-internal-schemas.md` §14.2 rule 5,
C-13.5). Tests load it only through `services/api/tests/_corpus.py`.

## Layout

`<capture-date>/` (today `2026-10-05/`). A refresh adds a new dated directory, so it is
additive and an old test can pin an old corpus (`corpus_path(..., capture_date=...)`).

- `ws/*.jsonl` - raw public WS frames, one per line, exactly as received.
- `rest/*.json` - REST response bodies (`http_status` is recorded in the manifest).
- `manifest.json` - one entry per file: `path`, `symbol`, `stream`, `host`, `capture_date`,
  `source`, `notable_event`, `http_status`, `size_cap_bytes`. A unit test fails if a file
  is unlisted or over its cap.
- `schema_expectations.json` - field path to JSON-type expectations used by the drift check.
- `README.tickers.md`, `README.trades.md` - provenance notes from E08-S03/S04.

## Coverage

| Scenario                                              | File                                                                     |
| ----------------------------------------------------- | ------------------------------------------------------------------------ |
| Clean 3 h windows (BTCUSDT, ETHUSDT, mid-cap SOLUSDT) | `ws/clean_publicTrade_*.jsonl`                                           |
| Sequence gap                                          | `ws/gap_orderbook_ETHUSDT.jsonl`, `ws/orderbook_BTCUSDT.jsonl`           |
| Reconnect                                             | `ws/reconnect_publicTrade_ETHUSDT.jsonl`, `ws/publicTrade_BTCUSDT.jsonl` |
| Ticker delta-only burst                               | `ws/burst_tickers_BTCUSDT.jsonl`                                         |
| Kline page boundary (450 rows, limit 200)             | `rest/kline_BTCUSDT_1_page{0,1,2}.json`                                  |
| Errors 10018 / 10002 / 5xx                            | `rest/error_10018.json`, `rest/error_10002.json`, `rest/error_503.json`  |
| Delisted symbol + changed tick size                   | `rest/instruments_before.json` -> `rest/instruments_after.json`          |

## Provenance and size

The current corpus is **built from documented shapes** and the existing recorded fixtures by
`tools/fixtures/build_corpus.py` and `tools/fixtures/gen_orderbook.py`. Both are
deterministic (seeded) and make no network calls. The owner recorded this in exception #1778
group A. Field names come only from the existing fixtures and the `exchange/bybit` parsers.
Refresh with `tools/fixtures/capture_fixture.py` (public stream only, redacts every frame,
aborts on a leftover secret pattern, enforces a size cap).

The total cap is 2.5 MB. Per-file caps are in the manifest. Captures larger than 1.5 MB must
go through Git LFS.

## Gates

- Secret scan: `node packages/fixtures/scripts/verify.mjs` (scans `bybit/`) and
  `python scripts/check_secrets_hygiene.py fixtures`, both already in CI.
- Drift: `python tools/fixtures/drift_check.py --sample <dir>`, run nightly by
  `.github/workflows/fixture-drift.yml`, which reports drift on its one open issue (#1849).
