# E08-X02 findings register — adversarial input at the exchange boundary

Ticket: E08-X02 (#290). Threat source: E08-X01 STRIDE (W1, W9, W10, O9) and
`docs/plan/04-security-program.md` SR-038, SR-040, SR-040a, SR-040b.
Severities: `04-security-program.md` §10.1 (P1..P4) plus the ticket rule **wrong data
with no visible signal = P0**.

**How it was run.** In-process, with no network. Hostile bytes go into the production
entry points the socket pump calls (`TradeStream` / `TickerStream` /
`BookStream.handle_frame`, `IngestionService.offer_frame` / `_pump_frames`,
`BybitRestClient` over `httpx.MockTransport`, the `parse_*` adapters). Time comes from a
fake clock and memory is measured with `tracemalloc`.

**Deviation.** The ticket asks for this to go through the E08-Q03 fault-injecting proxy.
That proxy (#280) is not built yet, so nothing here reimplements it. The hook for it is
`corpus.iter_hostile_frames()`: when E08-Q03 lands, the proxy replays that iterator over
its socket.

**Corpus split.** Hostile payloads are built in code, either in `corpus.py` or by
mutating a recorded E08-T05 frame. They never live in `packages/fixtures`. Minimised
crashers are in `regressions/`, with `INDEX.json` mapping each one to its issue.

Verdicts: **PASS** (the control holds), **DEFECT #n** (filed; test is
`xfail(strict=True)` so a fix flips it), **ACCEPTED** (behaviour is by design; the
rationale is given), **MANUAL** (not automatable here; the cadence is given).

## Defects filed

| Issue | Sev             | Summary                                                                                                                                                                                                                                                                                                                |
| ----- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #1889 | P1 (historical) | fixed → #1898 (residual #1900). Visible signal now: `ingest_rejected_total{reason="depth_limit"}` + the `IngestionFramesRejectedSustained` alert, and the pump survives. Deep-nested frame (`RecursionError`) or `ts: Infinity` (`OverflowError`) escapes `handle_frame`, which kills the frame pump for every stream. |
| #1890 | P0              | fixed → #1898. Off-tick book prices are truncated into the same `price_ticks`, so a level is silently lost or mispriced.                                                                                                                                                                                               |
| #1891 | P1              | milestone: R0. Regraded from P2: the signed request (key + signature + timestamp) goes off-host, so exfiltration plus replay within recvWindow. `BybitRestClient` signs and sends to any absolute URL given as `path` (bypasses SR-040a).                                                                              |
| #1892 | P0              | fixed → #1898. No plausibility checks: negative or crossed ticker, far-future trade `T`, `1e308` price and kline `high<low` are all accepted.                                                                                                                                                                          |
| #1893 | P2              | milestone: R0. CPU part fixed → #1898; pump yield open. Frame pump never yields under a backlog (event-loop starvation); `1e4200` prices cost about 1.2 s of CPU per frame.                                                                                                                                            |
| #1894 | P3              | fixed → #1898. No `ingest_rejected_total{reason}` counter; ticker and book rejections are uncounted and have no fingerprint.                                                                                                                                                                                           |
| #1895 | P2              | fixed → #2339 (the signer holds a capability and a credential id, not the key; strict xfail removed). Was: the full key in `repr` reaches tracebacks/exc_info/debugger dumps and the redactor misses a bare key.                                                                                                       |
| #1896 | P2              | milestone: R0. A malformed `instruments-info` row (`AttributeError` / `TypeError` / `OverflowError`) aborts the whole catalogue refresh.                                                                                                                                                                               |

## A — Malformed and hostile payloads (`test_hostile_payloads.py`, `corpus.py`)

| Id   | Attempted                                                                                      | Observed                                                                                                        | Expected                                                                                                       | Verdict                                                              |
| ---- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| A-01 | Frame cut in half                                                                              | `json.loads` fails; parser returns `None`; no event                                                             | Rejected, no event                                                                                             | PASS                                                                 |
| A-02 | Invalid UTF-8 (lone surrogate)                                                                 | Not valid JSON; no event                                                                                        | Rejected                                                                                                       | PASS                                                                 |
| A-03 | HTML 502 page / redirect text where a JSON frame is expected                                   | No event                                                                                                        | Rejected                                                                                                       | PASS                                                                 |
| A-04 | Top-level array                                                                                | No event                                                                                                        | Rejected                                                                                                       | PASS                                                                 |
| A-05 | NaN, ±Infinity, `-0`, `0`, `-1`, `"abc"`, null, bool, list as trade price or qty               | `ValueError`; `trade_prints_rejected_total` +1; `trade frame rejected` logged                                   | Rejected and counted                                                                                           | PASS                                                                 |
| A-06 | Unknown extra fields                                                                           | Ignored; core event published                                                                                   | SR-040 says `extra="forbid"`, but Bybit adds fields over time and the strict models sit at the domain boundary | ACCEPTED (forward-compatible; the domain models are `extra=forbid`)  |
| A-07 | Duplicate JSON key (`S` twice)                                                                 | Last value wins, consistently                                                                                   | Deterministic                                                                                                  | ACCEPTED (Bybit never emits duplicates; no ambiguity across parsers) |
| A-08 | `null` in every required trade field (`s,i,T,p,v,S`)                                           | Rejected                                                                                                        | Rejected                                                                                                       | PASS                                                                 |
| A-09 | Ticker NaN / word / bool / null `ts`; book NaN qty / negative price / null `u` / 1-element row | Rejected; `... frame rejected` logged                                                                           | Rejected and counted                                                                                           | PASS (log); FIXED → #1898 (#1894)                                    |
| A-10 | Nesting 5 000 deep (~10 KB, under the size cap)                                                | `RecursionError` escapes; `_pump_frames` dies; all market data stops                                            | Depth-limited before parse; pump survives                                                                      | FIXED → #1898 (#1889)                                                |
| A-11 | Nesting 500 deep                                                                               | Rejected                                                                                                        | Rejected                                                                                                       | PASS                                                                 |
| A-12 | `ts: Infinity` on a book frame (found by long fuzz)                                            | `OverflowError` escapes, same as A-10                                                                           | Rejected                                                                                                       | FIXED → #1898 (#1889)                                                |
| A-13 | 100 MB frame                                                                                   | Refused at `MAX_FRAME_BYTES` (1 MiB) by `websockets` `max_size` before buffering, and again by `_WsSocket.recv` | Refused before parse                                                                                           | PASS (config + adapter tests; 100 MB is not allocated in CI)         |
| A-14 | Every rejection emits `ingest_rejected_total{reason}` plus a fingerprinted log                 | Only trades have an (unlabelled) counter                                                                        | Counter on all three streams                                                                                   | FIXED → #1898 (#1894)                                                |

## B — Semantic attacks on market integrity (`test_market_integrity.py`)

| Id   | Attempted                                                           | Observed                                                                                                                                                      | Expected                           | Verdict                                                                                            |
| ---- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | -------------------------------------------------------------------------------------------------- |
| B-01 | Delta pushing best bid above best ask                               | `BookInvariantError("crossed")`; book DESYNCED; `BookStatus(reason=crossed)` published; resubscribe; `view()` is `None`; the crossed state is never published | Invalid and resynced, never served | PASS                                                                                               |
| B-02 | Crossed snapshot                                                    | `from_levels` check fails; never LIVE                                                                                                                         | Never served                       | PASS                                                                                               |
| B-03 | Delete of a level that does not exist                               | No-op; book unchanged                                                                                                                                         | No corruption                      | PASS                                                                                               |
| B-04 | Negative or NaN size level                                          | Parser rejects                                                                                                                                                | Rejected                           | PASS                                                                                               |
| B-05 | Zero-size level in a snapshot                                       | Never LIVE                                                                                                                                                    | Rejected                           | PASS                                                                                               |
| B-06 | Sequence goes backwards or repeats                                  | `prev_update_id` mismatch leads to a resync; no delta published                                                                                               | Resync                             | PASS                                                                                               |
| B-07 | Off-tick price (`100.05` on a 0.1 tick)                             | Truncated into the same `price_ticks` as `100.0`; the level is overwritten silently                                                                           | Rejected with a signal             | FIXED → #1898 (#1890)                                                                              |
| B-08 | Zero-qty trade                                                      | Rejected                                                                                                                                                      | Rejected                           | PASS                                                                                               |
| B-09 | Trade `T` 3 000 years ahead / before listing                        | Accepted                                                                                                                                                      | Rejected                           | FIXED → #1898 (#1892)                                                                              |
| B-10 | Trade price `1e308`                                                 | Accepted as a print                                                                                                                                           | Rejected (plausibility bound)      | FIXED → #1898 (#1892)                                                                              |
| B-11 | Ticker `lastPrice=-5`, bid > ask                                    | Merged and published as `TickerEvent`                                                                                                                         | Rejected                           | FIXED → #1898 (#1892)                                                                              |
| B-12 | `KlineEvent` with `high < low`                                      | Model validates                                                                                                                                               | Rejected                           | FIXED → #1898 (#1892) (no adapter kline parser exists yet; the gate belongs in it or in the model) |
| B-13 | `tickSize` set to `0`, `-0.1` or `NaN`                              | Row rejected                                                                                                                                                  | Rejected                           | PASS                                                                                               |
| B-14 | `minNotionalValue=1e12`                                             | Accepted and surfaced in `changed_fields`, which bumps `metadata_version`                                                                                     | Visible change                     | ACCEPTED (an exchange-side change is legitimate; the signal exists)                                |
| B-15 | `priceFilter: ["x"]`, `status: ["Trading"]`, `launchTime: Infinity` | Non-`InstrumentParseError` escapes; the whole refresh fails                                                                                                   | Per-row rejection                  | **DEFECT #1896**                                                                                   |

## C — Decoding abuse (`test_resource_exhaustion.py`)

| Id   | Attempted                                                                                                              | Observed                                                            | Expected                                    | Verdict         |
| ---- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------- | --------------- |
| C-01 | permessage-deflate is negotiable: `websockets` 17 offers it by default and `public_socket_factory` does not disable it | Negotiable                                                          | If negotiated, decompressed size is bounded | PASS (see C-02) |
| C-02 | 48 KB deflate bomb that inflates to 50 MB                                                                              | `PayloadTooBig` at `max_size` = 1 MiB; tracemalloc peak under 8 MiB | Aborted mid-inflate                         | PASS            |

## D — Resource exhaustion (`test_resource_exhaustion.py`)

| Id   | Attempted                                                                    | Observed                                                                     | Expected                         | Verdict                                                       |
| ---- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------- |
| D-01 | 1 500 distinct symbols in one trade frame                                    | Rejected as a whole (symbol mismatch; `MAX_PRINTS_PER_BATCH`)                | No per-symbol state is created   | PASS                                                          |
| D-02 | 10 000 distinct symbol label values                                          | Fold to `other` once `MAX_SYMBOLS` = 32; free text becomes `other`           | Bounded cardinality              | PASS                                                          |
| D-03 | `ws_frames` flood beyond 4 096                                               | Drop-newest; `ws_frames_dropped` counted; trade gap marked; book invalidated | Bounded and visible              | PASS                                                          |
| D-04 | 5 000 resubscribe reservations                                               | `ConnectionRateGuard` paces beyond 480 per 300 s; its deque stays bounded    | Bounded                          | PASS                                                          |
| D-05 | 3 000 subscribe/unsubscribe cycles across all streams (fake clock)           | After the bounded caches fill, growth is under 64 KiB                        | No unbounded growth              | PASS                                                          |
| D-06 | Never-idle stream (2 000 queued frames)                                      | `_pump_frames` drains everything without yielding; other tasks starve        | Pump yields every N frames       | PARTIAL: CPU part FIXED → #1898; pump starvation open (#1893) |
| D-07 | 1 000 levels at `1e4200` (15 KB frame)                                       | About 1.2 s of loop CPU before rejection                                     | Rejected cheaply (≤ 20 ms slice) | FIXED → #1898 (#1893)                                         |
| D-08 | "Memory returns to baseline within the declared window" after a 100 MB frame | Not applicable: the frame is never buffered (A-13)                           | —                                | PASS by construction                                          |

## E — Credential and leakage probes (`test_leakage.py`)

The scan is the repo pattern set (`tools/fixtures/redact.find_leaks`, which mirrors
`scripts/check_secrets_hygiene.py`) plus the three `.gitleaks.toml` bybit rules and the
literal synthetic key, secret and UID. It runs over captured structlog/stdlib output,
the Prometheus exposition, `str`/`repr` of the exception and its cause, and the problem
body.

| Id   | Attempted                                                                                                                        | Observed                                                         | Expected         | Verdict                                                                              |
| ---- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- | ---------------- | ------------------------------------------------------------------------------------ |
| E-01 | Signed call with transport error, HTML 502, retCode 10003, an unmapped code, 403 with no `retCode`, recorded 10002 / 10018 / 503 | Zero hits in every channel; headers are logged as `**redacted**` | Zero hits        | PASS                                                                                 |
| E-02 | Planted token: JSON `api_key`, an `X-BAPI-SIGN` header, a UID, a JSON `sign`                                                     | Every one detected                                               | Scan proven live | PASS                                                                                 |
| E-03 | UID in metric labels                                                                                                             | `scope=public/account` only                                      | No UID label     | PASS                                                                                 |
| E-04 | `repr(BybitSigner)`                                                                                                              | Credential id and purpose only (no key, no secret)               | Masked           | PASS (was DEFECT #1895; fixed → #2339)                                               |
| E-05 | Trace attributes                                                                                                                 | No tracer is wired on the adapter path yet                       | —                | MANUAL: re-run E-01 over the OTel exporter when E04 tracing reaches `exchange.bybit` |

## F — Environment confusion, SR-040a (`test_env_and_capability.py`)

| Id   | Attempted                                                                  | Observed                                                      | Expected               | Verdict                            |
| ---- | -------------------------------------------------------------------------- | ------------------------------------------------------------- | ---------------------- | ---------------------------------- |
| F-01 | `base_url` over http, a non-allowlisted host, with a path, or with a query | `ValidationError`                                             | Refused                | PASS                               |
| F-02 | Mutating `RestClientConfig.base_url` at runtime                            | Frozen model refuses                                          | Immutable              | PASS                               |
| F-03 | Absolute or scheme-relative URL passed as `path` on a live client          | Signed request sent to the demo or an arbitrary host          | Refused before signing | **DEFECT #1891**                   |
| F-04 | Public WS for demo                                                         | Uses the mainnet public stream (demo has none); `wss://` only | SR-040a                | PASS                               |
| F-05 | WS-trade path on demo                                                      | No WS-trade or private-WS code exists yet                     | Unreachable            | PASS (vacuous; re-assess with E29) |

## G — Capability creep (`test_env_and_capability.py`)

| Id   | Attempted                                                                                                                                                                                         | Observed                                                                                      | Expected                    | Verdict                       |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | --------------------------- | ----------------------------- |
| G-01 | AST scan of `ingestion`, `book`, `bars`, `orderflow`, `recorder` and `replay` for `TradingPort`, `signed_request`, `BybitSigner`, `oms`, `secrets` and `/v5/order` / `/v5/position` / `/v5/asset` | None found                                                                                    | Unreachable by construction | PASS                          |
| G-02 | Planted violation in `tmp_path`                                                                                                                                                                   | Detected by the same scan                                                                     | Scan proven live            | PASS                          |
| G-03 | `MarketDataPort` compared with `TradingPort`                                                                                                                                                      | Disjoint; no `place` / `cancel` / `amend` / `set_` methods                                    | No trading surface          | PASS                          |
| G-04 | Runtime: `ExchangeBybitService` and its public REST client                                                                                                                                        | Not a `TradingPort`; the public client has `signer=None`; `signed_request` raises `TypeError` | Fails by construction       | PASS                          |
| G-05 | Market-data credentials carry no trading permission                                                                                                                                               | The market-data path holds no credentials at all (public endpoints only)                      | No trading flag             | PASS (stronger than required) |

## H — Fuzzing (`test_fuzz_parsers.py`)

Strategies are structure-aware Hypothesis generators for each parser: trade, ticker and
book frames, raw text, recent-trade pages and instrument rows. The PR lane runs 150
examples per parser. The nightly long session is `CV_FUZZ_LONG=1 pytest -m fuzz` at
20 000 examples per parser; locally it took about 7.5 min. The contract is that a parser
returns or raises `ValueError` / `InstrumentParseError`.

| Id   | Attempted                                | Observed                                                                                                   | Verdict               |
| ---- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------- | --------------------- |
| H-01 | Bounded fuzz over trade, ticker and book | Holds within the PR budget                                                                                 | PASS                  |
| H-02 | Long session, book                       | `ts: Infinity` leads to `OverflowError` (now `regressions/book_ts_infinity.frame`)                         | FIXED → #1898 (#1889) |
| H-03 | Instrument rows                          | `launchTime: Infinity` leads to `OverflowError`; list-typed filters lead to `AttributeError` / `TypeError` | **DEFECT #1896**      |
| H-04 | Checked-in crashers replay every PR      | `regressions/*.frame`; known-open crashers are `xfail` against their issue                                 | PASS (harness)        |

## Planted-defect verification (ticket test plan)

| Control removed (locally, then reverted)           | Case that went red                                                                        |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `MAX_FRAME_BYTES` check in `_WsSocket.recv`        | `test_oversized_frame_refused_by_socket_adapter`                                          |
| `BookState.check()` crossed test                   | `test_crossed_delta_desyncs_and_is_never_served`, `test_crossed_snapshot_never_goes_live` |
| `_redact()` in `rest.py` returns headers unchanged | `test_signed_error_path_leaks_nothing[*]` (8 cases)                                       |
| Planted token                                      | `test_scan_detects_planted_token`                                                         |

## Not covered here (by scope)

- The sustained-rejection alert rule cannot be validated until #1894 adds the counter.
  It is tracked on #1894.
- The p95 ≤ 20 ms rejection-flood latency slice is blocked by #1893 (D-06 / D-07). Once
  that is fixed, the `perf` case becomes the budget gate.
- TLS behaviour is asserted by configuration only (`wss://` / `https://`, allowlist).
  There is no MITM against Bybit (out of scope).
