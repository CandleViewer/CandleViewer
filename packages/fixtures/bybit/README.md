# Bybit fixture corpus (E08-T05)

The shared, offline input set for every E08 test (`24-internal-schemas.md` §14.2 rule 5,
C-13.5). Tests load it only through `services/api/tests/_corpus.py`.

## Layout

`<capture-date>/` (today `2026-10-05/`). A full refresh adds a new dated directory, so it is
additive and an old test can pin an old corpus (`corpus_path(..., capture_date=...)`). Frames
recorded later for fields the corpus lacks join the current directory instead, each with its
own `capture_date` (the `recorded_*` files below).

- `ws/*.jsonl` - raw public WS frames, one per line, exactly as received.
- `rest/*.json` - REST response bodies (`http_status` is recorded in the manifest).
- `manifest.json` - one entry per file: `path`, `symbol`, `stream`, `host`, `capture_date`,
  `source`, `notable_event`, `http_status`, `size_cap_bytes`, `window_ms` (first and last frame
  `ts`) for a recorded capture, and `retrieved`, `source_url` and `source_ref` for a
  docs-transcribed file, whose `http_status` is null (no documentation page shows one). A REST
  file's `stream` is `<METHOD> /v5/<path>`, the route it answers. A unit test fails if a file is
  unlisted or over its cap.
- `schema_expectations.json` - field path to JSON-type expectations used by the drift check.
- `README.tickers.md`, `README.trades.md` - provenance notes from E08-S03/S04.

## Coverage

| Scenario                                              | File                                                                         |
| ----------------------------------------------------- | ---------------------------------------------------------------------------- |
| Clean 3 h windows (BTCUSDT, ETHUSDT, mid-cap SOLUSDT) | `ws/clean_publicTrade_*.jsonl`                                               |
| Sequence gap                                          | `ws/gap_orderbook_ETHUSDT.jsonl`, `ws/orderbook_BTCUSDT.jsonl`               |
| Reconnect                                             | `ws/reconnect_publicTrade_ETHUSDT.jsonl`, `ws/publicTrade_BTCUSDT.jsonl`     |
| Ticker delta-only burst                               | `ws/burst_tickers_BTCUSDT.jsonl`                                             |
| Kline page boundary (450 rows, limit 200)             | `rest/kline_BTCUSDT_1_page{0,1,2}.json`                                      |
| Errors 10018 / 10002 / 5xx                            | `rest/error_10018.json`, `rest/error_10002.json`, `rest/error_503.json`      |
| Delisted symbol + changed tick size                   | `rest/instruments_before.json` -> `rest/instruments_after.json`              |
| Live feed fields (#3447): `RPI`, `seq`, newer tickers | `ws/recorded_publicTrade_BTCUSDT.jsonl`, `ws/recorded_tickers_BTCUSDT.jsonl` |
| Order path (#2877): trade replies, reads, two errors  | `rest/trading-*.json` (docs-transcribed, below)                              |

## Provenance and size

The current corpus is **built from documented shapes** and the existing recorded fixtures by
`tools/fixtures/build_corpus.py` and `tools/fixtures/gen_orderbook.py`. Both are
deterministic (seeded) and make no network calls. The owner recorded this in exception #1778
group A. Field names come only from the existing fixtures and the `exchange/bybit` parsers.
Refresh with `tools/fixtures/capture_fixture.py` (public stream only, redacts every frame,
aborts on a leftover secret pattern, enforces a size cap).

The two `recorded_*` files are such captures, copied unchanged. They are 20 frames each of
`publicTrade.BTCUSDT` and `tickers.BTCUSDT`, from Bybit's mainnet public stream
(`stream.bybit.com`, env live, public data only), recorded by `fixture-drift.yml` run 39210373369
on 2026-10-19 (#3447). They carry the live fields the documented shapes lacked. Each
`fixture-drift` run that is not cancelled keeps its redacted sample as the
`fixture-drift-sample` artifact for 14 days, so a refresh can start from it when the recording machine cannot reach the public
stream (`gh run download <run> -n fixture-drift-sample`, into a new empty directory). After
adding frames: list them in `build_corpus.py`, rebuild the manifest
(`python tools/fixtures/build_corpus.py`), refresh the expectations
(`python tools/fixtures/drift_check.py --write-expectations`), and reference each new file
from a contract test.

The total cap is 2.5 MB. Per-file caps are in the manifest. Captures larger than 1.5 MB must
go through Git LFS.

### Docs-transcribed order-path shapes (#2877, ruling R2)

No recording holds an order-path reply yet (E29-K01, #843, records them). Under the #1778 group A
pattern each `rest/trading-*.json` file is one shape transcribed from the Bybit v5 documentation:
the page's Response Example with its keys and values unchanged (whitespace compacted), or, for an
error, the code and text of its row in the error table, which shows nothing else. The manifest
gives each file's `source_url`, `retrieved` date and `source_ref` (the page's source file at
`bybit-exchange/docs` commit `19518b90fb36`). They are evidence of the documented shapes only,
never of live values. `tests/contract/bybit/test_contract_trading_drift.py` compares each one
with every recording of the same route (the method and path of its `stream` label) and return
code, and fails the moment one disagrees; an error-row transcription is compared on its code and
text only, and a REST recording whose label names no route fails the check. The PR that adds
such a recording (E29-K01, #843) deletes the transcription it replaces: the file, its manifest
entry and `build_corpus.py` row, and its line below. The same PR removes the file from
`TRANSCRIBED` in `services/api/tests/contract/bybit/test_contract_trading.py`, and repoints to the
recording, or updates, every test that loads the file by name (`rest("rest/trading-...")`; the
modules are those `grep -rln 'rest/trading-' services/api/tests` lists), so no test reads a
deleted file. Not documented, so not transcribed: a `10001` duplicate's text (E29
model O-1), a Partial-mode TP/SL order row, a REST `create-batch` reply with a refused item, and a
linear position, wallet (USDT) or fee-rate row; strict-model unit tests alone cover those parsers.

Licence: the upstream repository `bybit-exchange/docs` has no licence file at that commit, so no
licence grants these examples. Each file reproduces one short documented example, used only to
test this adapter's parsers against the documented shape, under ruling R2 (#2701); E29-K01's
recordings replace them.

Each line: file; source; date; symbol; env; redaction. Every env is none (a documentation
example, from no account), and no redaction is needed: no file holds a key, a signature or an
account id.

- `trading-create-reply.json`: source: docs-transcribed, `order/create-order`; 2026-10-21; symbol none; env none; redaction none.
- `trading-amend-reply.json`: source: docs-transcribed, `order/amend-order`; 2026-10-21; symbol none; env none; redaction none.
- `trading-cancel-reply.json`: source: docs-transcribed, `order/cancel-order`; 2026-10-21; symbol none; env none; redaction none.
- `trading-cancel-all-reply.json`: source: docs-transcribed, `order/cancel-all`; 2026-10-21; symbol none; env none; redaction none.
- `trading-create-batch-reply.json`: source: docs-transcribed, `order/batch-place`; 2026-10-21; symbol BTCUSDT and ATOMUSDT (spot); env none; redaction none.
- `trading-order-realtime.json`: source: docs-transcribed, `order/open-order`; 2026-10-21; symbol ETHUSDT; env none; redaction none.
- `trading-order-history.json`: source: docs-transcribed, `order/order-list`; 2026-10-21; symbol BTCUSDT; env none; redaction none.
- `trading-execution-list.json`: source: docs-transcribed, `order/execution`; 2026-10-21; symbol ETHPERP; env none; redaction none.
- `trading-position-list.json`: source: docs-transcribed, `position`; 2026-10-21; symbol BTCUSD (inverse); env none; redaction none.
- `trading-closed-pnl.json`: source: docs-transcribed, `position/close-pnl`; 2026-10-21; symbol ETHPERP; env none; redaction none.
- `trading-trading-stop-reply.json`: source: docs-transcribed, `position/trading-stop`; 2026-10-21; symbol none; env none; redaction none.
- `trading-set-leverage-reply.json`: source: docs-transcribed, `position/leverage`; 2026-10-21; symbol none; env none; redaction none.
- `trading-wallet-balance.json`: source: docs-transcribed, `account/wallet-balance`; 2026-10-21; symbol none (one BTC coin row); env none; redaction none.
- `trading-fee-rate.json`: source: docs-transcribed, `account/fee-rate`; 2026-10-21; symbol BTCUSDT (spot); env none; redaction none.
- `trading-account-info.json`: source: docs-transcribed, `account/account-info`; 2026-10-21; symbol none; env none; redaction none.
- `trading-error-110072.json`: source: docs-transcribed, `error (UTA table, 110072)`; 2026-10-21; symbol none; env none; redaction none.
- `trading-error-110001.json`: source: docs-transcribed, `error (UTA table, 110001)`; 2026-10-21; symbol none; env none; redaction none.

## Gates

- Secret scan: `node packages/fixtures/scripts/verify.mjs` (scans `bybit/`) and
  `python scripts/check_secrets_hygiene.py fixtures`, both already in CI.
- Drift: `python tools/fixtures/drift_check.py --sample <dir>`, run nightly by
  `.github/workflows/fixture-drift.yml`, which reports drift on its one open issue (#1849).
