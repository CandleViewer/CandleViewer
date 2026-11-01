# Bybit fixture corpus (E08-T05)

The shared, offline input set for every E08 test (`24-internal-schemas.md` §14.2 rule 5,
C-13.5). Tests load it only through `services/api/tests/_corpus.py`.

## Layout

`<capture-date>/` (today `2026-10-05/`). A full refresh adds a new dated directory, so it is
additive and an old test can pin an old corpus (`corpus_path(..., capture_date=...)`). Frames
recorded later for fields the corpus lacks join the current directory instead, each with its
own `capture_date` (the `recorded_*` files below).

- `ws/*.jsonl` - raw public WS frames, one per line, exactly as received, and the private stream's
  docs-transcribed frames (below).
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

| Scenario                                               | File                                                                             |
| ------------------------------------------------------ | -------------------------------------------------------------------------------- |
| Clean 3 h windows (BTCUSDT, ETHUSDT, mid-cap SOLUSDT)  | `ws/clean_publicTrade_*.jsonl`                                                   |
| Sequence gap                                           | `ws/gap_orderbook_ETHUSDT.jsonl`, `ws/orderbook_BTCUSDT.jsonl`                   |
| Reconnect                                              | `ws/reconnect_publicTrade_ETHUSDT.jsonl`, `ws/publicTrade_BTCUSDT.jsonl`         |
| Ticker delta-only burst                                | `ws/burst_tickers_BTCUSDT.jsonl`                                                 |
| Kline page boundary (450 rows, limit 200)              | `rest/kline_BTCUSDT_1_page{0,1,2}.json`                                          |
| Errors 10018 / 10002 / 5xx                             | `rest/error_10018.json`, `rest/error_10002.json`, `rest/error_503.json`          |
| Delisted symbol + changed tick size                    | `rest/instruments_before.json` -> `rest/instruments_after.json`                  |
| Live feed fields (#3447): `RPI`, `seq`, newer tickers  | `ws/recorded_publicTrade_BTCUSDT.jsonl`, `ws/recorded_tickers_BTCUSDT.jsonl`     |
| Risk-limit tiers (#913): one recorded page each        | `rest/risk_limit_BTCUSDT.json`, `rest/risk_limit_ETHUSDT.json`                   |
| Bulk ticker route (#4707): one recorded reply each     | `rest/recorded_tickers_{BTCUSDT,ETHUSDT,SOLUSDT}.json`                           |
| Order path (#2877): trade replies, reads, two errors   | `rest/trading-*.json` (docs-transcribed, below)                                  |
| Private stream (#3963): replies and topic pushes       | `ws/private-*.jsonl` (docs-transcribed, below)                                   |
| Open-interest history (#665): 260 rows, 2 cursor pages | `rest/open_interest_BTCUSDT_5min_page{0,1}.json`, `rest/docs-open-interest.json` |

## Provenance and size

The current corpus is **built from documented shapes** and the existing recorded fixtures by
`tools/fixtures/build_corpus.py` and `tools/fixtures/gen_orderbook.py`. Both are
deterministic (seeded) and make no network calls. The owner recorded this in exception #1778
group A. Field names come only from the existing fixtures and the `exchange/bybit` parsers.
Refresh with `tools/fixtures/capture_fixture.py` (public stream only, redacts every frame,
aborts on a leftover secret pattern, enforces a size cap). Its redactor (`tools/fixtures/redact.py`)
finds a secret by key name and value shape only. That holds for public frames, which carry no
account data; it is not enough for a private-stream capture (the module docstring says what one
would need).

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

### Recorded risk-limit replies (S-RL, #913)

Two `GET /v5/market/risk-limit` replies, recorded once with
`capture_fixture.py --rest-path` from Bybit's public `api.bybit.com` endpoint, with no key and
no signing. Each is one page, `category=linear`, one symbol. The tool redacted and leak-checked
the body as received; the public reply holds no credential or account field, so nothing was
replaced. `tests/contract/bybit/test_contract_risk_limits.py` reads both. They sit in the
`2026-10-05` directory because the corpus is one dated set; the manifest and the lines below carry
their own retrieval date, 2026-10-25.

Each line: file; source; date; symbol; env; redaction.

- `risk_limit_BTCUSDT.json`: source: recorded, `capture_fixture.py --rest-path /v5/market/risk-limit`; 2026-10-25 18:45Z; symbol BTCUSDT (35 tiers); env live public endpoint, no key; redaction: `redact()` / `find_leaks()` clean, no credential fields.
- `risk_limit_ETHUSDT.json`: source: recorded, `capture_fixture.py --rest-path /v5/market/risk-limit`; 2026-10-25 18:45Z; symbol ETHUSDT (35 tiers); env live public endpoint, no key; redaction: `redact()` / `find_leaks()` clean, no credential fields.

### Recorded bulk-ticker replies (#4707, E08-T08)

Three `GET /v5/market/tickers` replies (`category=linear`, one symbol each), recorded once with
`capture_fixture.py --rest-path` from Bybit's public `api.bybit.com` endpoint on 2026-10-28, with
no key and no signing, from the orchestrator's host (the VPS lane's run was refused with HTTP 403
by the endpoint, so the orchestrator ran the same command). The full `category=linear` reply
exceeds the tool's 512 KB cap and was not recorded; the bulk route's shape is the same envelope
with a longer `list`, which `tests/_tickers.py` assembles from these recorded items for the
120-symbol case (symbol and price varied only, as the test docstring says). Each reply carries
`highPrice24h` / `lowPrice24h`, the fields E08-T08 maps to `high_24h` / `low_24h`. The tool
redacted and leak-checked each body as received; a public ticker holds no credential or account
field, so nothing was replaced.

Each line: file; source; date; symbol; env; redaction.

- `recorded_tickers_BTCUSDT.json`: source: recorded, `capture_fixture.py --rest-path /v5/market/tickers --param category=linear --param symbol=BTCUSDT`; 2026-10-28 12:45Z; symbol BTCUSDT; env live public endpoint, no key; redaction: `redact()` / `find_leaks()` clean, no credential fields.
- `recorded_tickers_ETHUSDT.json`: source: recorded, same command with `symbol=ETHUSDT`; 2026-10-28 12:45Z; symbol ETHUSDT; env live public endpoint, no key; redaction: clean, no credential fields.
- `recorded_tickers_SOLUSDT.json`: source: recorded, same command with `symbol=SOLUSDT`; 2026-10-28 12:45Z; symbol SOLUSDT; env live public endpoint, no key; redaction: clean, no credential fields.

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
model O-1), a Partial-mode TP/SL order row, a REST `create-batch` reply with a refused item (whose
echo of its request's `orderLinkId`, which the port pairs it by, is assumed pending E29-K01: 24
§14.1), and a linear position, wallet (USDT) or fee-rate row; strict-model unit tests alone
cover those parsers.

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

### Docs-transcribed private-stream frames (#3963, G-8b ruling 11)

No recording holds a private-stream frame yet (E29-K01, #843, records them). Under the same #1778
group A pattern each `ws/private-*.jsonl` file is one frame transcribed from the Bybit v5
documentation: a reply sample of the Connect page (`ws/connect`, source
`websocket/wss-authentication.mdx`) or a private topic's Stream Example, keys and values
unchanged (whitespace compacted), at the same `bybit-exchange/docs` commit `19518b90fb36`. Each
manifest `stream` is the topic as the adapter subscribes it (`order.linear`, `wallet`, ...) or
`op <name>` for a reply; the samples use the all-in-one topics, the order sample is an option's,
the fast fill an `ICPUSDT` one and the wallet a BTC row, and tests derive linear USDT rows from
them in-test, never presenting a derived value as evidence. `test_contract_trading_drift.py`
compares each with every recording of the same topic or op (all-in-one and categorised names
alike, `.jsonl.gz` too) and fails the moment one disagrees, and it fails on a private recording
it cannot pair. Not documented, so not transcribed: a linear order push, and the two refused
replies below, which tests derive from the granted ones (E29-K01, #843, records them).

- refused `auth` reply (`op auth`, `success` false): no public example — K01.
- refused `subscribe` reply (`op subscribe`, `success` false): no public example — K01.

A K01 recording of a private push has its envelope `id` redacted before it is committed: its
first segment is the account's UID (C-13.5), as in the documented `386825804_BTCUSDT_...`
sample. The drift check compares keys and types, never values, so the redacted id still pairs.

Each line: file; source; date; symbol; env; redaction. Every env is none (a documentation
example, from no account), and no redaction is needed: no file holds a key, a signature or an
account id.

- `private-auth-ok.jsonl`: source: docs-transcribed, `ws/connect`; 2026-10-21; symbol none; env none; redaction none.
- `private-subscribe-ok.jsonl`: source: docs-transcribed, `ws/connect` (Private tab); 2026-10-21; symbol none; env none; redaction none.
- `private-pong.jsonl`: source: docs-transcribed, `ws/connect` (private channels); 2026-10-21; symbol none; env none; redaction none.
- `private-order.jsonl`: source: docs-transcribed, `websocket/private/order`; 2026-10-21; symbol ETH-30DEC22-1400-C (option); env none; redaction none.
- `private-execution.jsonl`: source: docs-transcribed, `websocket/private/execution`; 2026-10-21; symbol BTCUSDT; env none; redaction none.
- `private-execution-fast.jsonl`: source: docs-transcribed, `websocket/private/fast-execution`; 2026-10-21; symbol ICPUSDT; env none; redaction none.
- `private-position.jsonl`: source: docs-transcribed, `websocket/private/position`; 2026-10-21; symbol BTCUSDT; env none; redaction none.
- `private-wallet.jsonl`: source: docs-transcribed, `websocket/private/wallet`; 2026-10-21; symbol none (one BTC coin row); env none; redaction none.

### Docs-transcribed open-interest shape (#665, E24-T01)

No recording holds a `GET /v5/market/open-interest` reply yet. `rest/docs-open-interest.json` is
the docs page's Response Example (`market/open-interest`, at `bybit-exchange/docs` commit
`19518b90fb36`), keys and values unchanged (whitespace compacted): an inverse `BTCUSD` page, so
evidence of the documented shape only. The two `open_interest_BTCUSDT_5min_page*.json` files are
documented-shape (exception #1778 A), not docs-transcribed: they take that row and envelope shape,
read from the page retrieved 2026-10-31, with generated (seeded) linear values, built by
`build_corpus.py`.
A recording made with `capture_fixture.py --rest-path` replaces all three.

- `docs-open-interest.json`: source: docs-transcribed, `market/open-interest`; 2026-10-31; symbol BTCUSD (inverse); env none; redaction none.

## Gates

- Secret scan: `node packages/fixtures/scripts/verify.mjs` (scans `bybit/`) and
  `python scripts/check_secrets_hygiene.py fixtures`, both already in CI.
- Drift: `python tools/fixtures/drift_check.py --sample <dir>`, run nightly by
  `.github/workflows/fixture-drift.yml`, which reports drift on its one open issue (#1849).
