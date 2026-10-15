# E08-Q03 — Exchange-boundary chaos catalogue

Suite: `services/api/tests/chaos/ingestion/` (marker `chaos`; ~10 s total, PR-lane safe).
Run: `cd services/api && uv run pytest tests/chaos/ingestion -m chaos --no-cov`
(`--runxfail` shows the live failure behind each strict xfail).

**Harness.** `_stub_exchange.StubExchange` is the fault-injecting proxy at the transport seam:
it is the `ConnectionManager` socket factory and the `httpx` transport of a real
`BybitRestClient`. `inject(Fault)` arms a fault; `replay(frames)` / `_feed.Feeder` stream the
recorded E08-T05 corpus (re-timed only). `_rig.Rig` wires the production composition
(`IngestionService` pump, B13 `ws_conn` chart via the factory, `TradeStream`, `BookStream`,
`InstrumentsRefreshScheduler`, bus) exactly as `app.wire_public_ws` does. Time is a
`VirtualClock` (no wall-clock sleeps, C-13.7); jitter is seeded; `settle()` is the
quiescence barrier assertions run after. The venue keeps a book/trade **oracle** (the REST
snapshot truth). No sockets are opened; the live host is asserted unreachable.

**E08-X02 hook.** `StubExchange.inject()` / `.replay()` / `Rig` are the entry points the
abuse-case corpus (`tests/security/ingestion/corpus.iter_hostile_frames()`) can replay through
the same pump.

Legend — **C-13.6**: constitution chaos number. **xfail**: strict xfail on a filed defect
(turns red the moment the fix lands, so the marker must be removed in the fix PR).

## Deviations from the composition root

`Rig` is modelled on `app.wire_public_ws`, not identical to it:

- Virtual clock/RNG and the stub transport replace the real ones.
- s08's signed client wires `on_signature_failure` although production has no signed-client
  composition yet (#1949, #1911): s08 proves client + guard, not the app.
- No `B14BookSupervisor`; no ticker stream.
- Instrument launch-time callback is `lambda _s: None`.
- `ClockGuard` feeds the `EventWindow` but is not attached to `IngestionService`.
- The book timeout loop is replaced by `check_timeouts()` on the virtual clock.
- `IngestionService.start()` is never called, so the rig registers `prune_unlisted`, the frame
  router and the pump itself.

Parity follow-up: #1975.

## Catalogue

| #   | C-13.6 | Fault injected                        | Declared degradation → recovery (SLO)                                                                          | User-visible signal                                                                 | Metric                                                                                                                 | Observed       |
| --- | ------ | ------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | -------------- |
| 1   | #1     | `RESET` (TCP reset) mid-stream        | backoff+jitter → reconnect → one subscribe per topic → fresh snapshot; book LIVE ≤ 5 s                         | feed `degraded`→`resubscribing`→`healthy` (SCR-152); `BookStatus(reason=reconnect)` | `ingest_ws_up` 1→0→1                                                                                                   | ✅             |
| 1b  | #1     | demand change while LIVE              | re-plan subscription, no reconnect                                                                             | new topic subscribed                                                                | —                                                                                                                      | ❌ xfail #1915 |
| 2   | #1     | `STALL` (open, silent)                | watchdog fires in [2.0, 2.5] s → socket recycled → LIVE ≤ 5 s                                                  | feed `stale` on the topic, then `healthy`                                           | `ingest_ws_up` 1→0→1                                                                                                   | ✅             |
| 3   | #3     | `DROP` / `REORDER` on `orderbook.200` | DESYNCED **before** any post-hole delta; unsub+sub; buffered replay; == oracle at full depth ≤ 3 s             | `BookStatus(desynced, sequence_gap)` → LIVE                                         | `ingest_book_resyncs_total{reason=sequence_gap}` +1; `ingest_book_live` 1→0→1                                          | ✅             |
| 3   | #3     | `DUPLICATE` delta                     | resync, never double-apply; == oracle                                                                          | as above                                                                            | resyncs +1                                                                                                             | ✅             |
| 4   | #1     | lost prints + reconnect               | REST backfill; missing prints `source=backfill`; no dups                                                       | `GapEvent(recovered=true)`                                                          | `trade_gaps_total{recovered=true}` +1                                                                                  | ✅             |
| 4   | #1     | + REST 503 during backfill            | unrecovered gap raised, never absorbed                                                                         | `GapEvent(recovered=false)`                                                         | `trade_gaps_total{recovered=false}` +1 → `IngestionTradeGapUnrecovered`; `trade_backfill_rows_total{result=error}` +1  | ✅             |
| 4   | #1     | + REST 503 during backfill            | WS/book unaffected by a REST outage                                                                            | no `stale`                                                                          | —                                                                                                                      | ❌ xfail #1905 |
| 5   | #5     | 10018 ×4 with reset headers           | `RateLimitError`; bucket set from `X-Bapi-Limit-Status`; no WS recycle; headroom recovers                      | —                                                                                   | `bybit_rate_limited_total{code=10018}` +4; `bybit_rate_limit_remaining` 0 → >1 → `IngestionRateLimitHeadroomExhausted` | ✅             |
| 5   | #5     | 10018, reset in 30 s                  | retry not before `X-Bapi-Limit-Reset-Timestamp`                                                                | —                                                                                   | —                                                                                                                      | ❌ xfail #1908 |
| 6   | #4     | HTTP 503 / 502 HTML / malformed JSON  | `TransportError` / `TransportError` / `UnknownStateError`; 5xx retried with backoff (4 attempts); WS untouched | degraded, not crashed                                                               | `bybit_rest_requests_total{result=5xx\|error}` +N                                                                      | ✅             |
| 6   | #4     | hostile row (NaN price, SR-040b)      | page rejected; nothing trusted                                                                                 | —                                                                                   | —                                                                                                                      | ✅             |
| 6   | #4     | one truncated 200 body                | retried like 5xx                                                                                               | —                                                                                   | —                                                                                                                      | ✅ |
| 7   | #1     | 200 resets+refusals / 300 s           | dials ≤ guard budget per 300 s window, < 500 (SR-039); exhaustion → `budget_blocked`                           | feed `degraded`                                                                     | sliding-window dial count (hard fail)                                                                                  | ✅             |
| 8   | #6     | host clock ±10 s                      | offset measured ≈ ∓10 s; signed call inside recv_window                                                        | drift `critical` (SCR-147)                                                          | `exchange_clock_drift_ms` ≈ ∓10 000 → `BybitClockDriftCritical`                                                        | ✅             |
| 8   | #6     | jump mid-session, signed call         | 10002 → exactly one retry → `ClockDriftError`, no loop                                                         | —                                                                                   | 2 × 10002 at venue                                                                                                     | ✅             |
| 8   | #6     | as above                              | re-measure before the retry; retry succeeds                                                                    | —                                                                                   | `clock_resync_triggered_total{reason=signature_failure}` +1                                                            | ❌ xfail #1911 |
| 8   | #6     | host +10 s / −2.5 s                   | `ts_event` == venue `T`; bar bucket unchanged                                                                  | —                                                                                   | —                                                                                                                      | ✅             |
| 8   | #6     | host −10 s                            | live prints accepted                                                                                           | —                                                                                   | `trade_prints_rejected_total` +0                                                                                       | ❌ xfail #1912 |
| 9   | #1     | `DELIST` (`instruments_after.json`)   | not listed; `acquire` refused                                                                                  | delisted/paused (`UnknownSymbolError`)                                              | `instruments_refresh_total{result=ok}`                                                                                 | ✅             |
| 9   | #1     | release after delist                  | topics unsubscribed                                                                                            | —                                                                                   | —                                                                                                                      | ❌ xfail #1915 |
| 9   | #1     | delisted topic held                   | no resubscribe loop; others untouched                                                                          | —                                                                                   | —                                                                                                                      | ❌ xfail #1913 |
| 10  | #11    | slow `INVALIDATE_ON_FULL`             | flush + `StreamInvalidated`; fast path unaffected                                                              | consumer resnapshots                                                                | `bus_stream_invalidated_total{md.book}`                                                                                | ✅             |
| 10  | #11    | slow `CONFLATE_LATEST`                | holds newest only                                                                                              | —                                                                                   | —                                                                                                                      | ✅             |
| 10  | #11    | slow `NEVER_DROP`                     | publisher waits; nothing lost; gap-free                                                                        | log `bus subscriber lagging subscriber=<name>`                                      | `ingest_queue_full_total{class=md.book}`                                                                               | ✅             |
| 10  | #11    | as above, 2 symbols                   | other symbol not starved (06 §6.1)                                                                             | —                                                                                   | —                                                                                                                      | ❌ xfail #1916 |
| 11  | #10    | hot tier down 10 s                    | live publish continues; failure logged; never over-acked; writes resume                                        | —                                                                                   | log `trade write-behind failed`                                                                                        | ✅             |
| 11  | #10    | catalogue fetch 503 ×40               | last snapshot served, `stale_since` set                                                                        | catalogue stale                                                                     | `instruments_refresh_total{result=error}`                                                                              | ✅             |
| 11  | #10    | hot tier down 10 s                    | buffered writes drain after recovery                                                                           | —                                                                                   | —                                                                                                                      | ❌ xfail #1918 |
| AC  | —      | unrecovered fault                     | topic signal present                                                                                           | feed `degraded`/`stale`                                                             | —                                                                                                                      | ✅             |
| AC  | —      | unrecovered fault                     | health endpoint `degraded`                                                                                     | `/readyz`                                                                           | —                                                                                                                      | ❌ xfail #1919 |

## Verification recorded

- **Mutation:** with `ConnectionRateGuard.reserve()` neutered, scenario 7 fails with
  `251 dials in a 300 s window > budget 120` (restored; production code is unchanged in this PR).
- **Flake budget:** 20 consecutive full-suite runs, 20/20 green (`43 passed, 1 xfailed`, ~30 s virtual-time).
- **Determinism:** same seed ⇒ identical fault trace (`test_harness_guards.py`).
- **Not covered here (scope):** private-WS / order-path halves of C-13.6 #2, #4, #5, #7–#9, #12
  (E29-Q04, E45-T07); client-WS fan-out (E17); a11y text of SCR-152 (E08-Q05/E47-Q06).

## Runbook fragments (feed `04-security-program.md` IR-05)

| Symptom                      | Metric / alert                                   | Expected auto-recovery               | Manual action if not                                                              |
| ---------------------------- | ------------------------------------------------ | ------------------------------------ | --------------------------------------------------------------------------------- |
| "Reconnecting" banner        | `ingest_ws_up`=0                                 | backoff ≤30 s, resubscribe, snapshot | check egress/DNS to the stream host; `budget_blocked` ⇒ wait out the 300 s window |
| Panel shaded stale           | `IngestionTopicStale`                            | watchdog recycles in ≤2.5 s          | single quiet topic recycling the feed ⇒ #1913; release the symbol                 |
| "Book resynchronising"       | `IngestionBookResyncRateHigh`, `BookResyncStorm` | resync with 250 ms→30 s backoff      | sustained ⇒ capture frames, open a P1                                             |
| Tape gap marker              | `IngestionTradeGapUnrecovered`                   | REST backfill on next print          | backfill REST later from journal/recorder; check REST health                      |
| Rate limited                 | `IngestionRateLimitHeadroomExhausted`            | bucket refills                       | stop non-essential REST callers; honour reset (#1908)                             |
| Clock drift                  | `BybitClockDriftWarning/Critical`                | re-measure every 300 s               | fix host NTP/WSL time sync; orders are gated by E29                               |
| Hot-tier down                | `trade write-behind failed` logs                 | writes resume                        | rows in the outage window are lost until #1918 — re-backfill                      |
| Readyz green while feed down | — (#1919)                                        | —                                    | trust SCR-152 / `ingest_ws_up`, not `/readyz`                                     |
